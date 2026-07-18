"""Bridge between the web console and the on-device network runtime.

The image ships a self-contained network stack (gateway-network-apply.sh,
gateway-network-monitor.sh, gateway-cellular-qmi, driven via gateway-networkctl):
  * reads   /opt/metacrust/config/network/config.json   (written by us)
  * writes  /opt/metacrust/state/network/state.json      (rich live state)
            /opt/metacrust/state/network/apply-result.json
            /opt/metacrust/state/network/cellular-state.json

This module: loads/saves the config, serves the state files, shells out to
gateway-networkctl for actions (apply / wifi scan / cellular refresh), builds
interface details from the kernel, and records uplink/outage transition events
by diffing state.json — the runtime itself keeps no event log.

Every path/binary is env-overridable and everything degrades gracefully on a
dev machine where none of it exists.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(os.environ.get("GATEWAY_NETWORK_CONFIG_PATH", "/opt/metacrust/config/network/config.json"))
STATE_DIR = Path(os.environ.get("GATEWAY_NETWORK_STATE_DIR", "/opt/metacrust/state/network"))
CTL = Path(os.environ.get("GATEWAY_NETWORKCTL", "/opt/metacrust/scripts/gateway-networkctl"))
DEFAULTS_FILE = Path(os.environ.get("GATEWAY_NETWORK_DEFAULTS", "/usr/share/metacrust/network/defaults.json"))

_EVENTS_DEFAULT = Path("/opt/metacrust/data/network/events.jsonl")
_EVENTS_FALLBACK = Path.home() / ".metacrust" / "data" / "network" / "events.jsonl"

WINDOW_MS = {"1h": 3_600_000, "6h": 6 * 3_600_000, "24h": 24 * 3_600_000, "7d": 7 * 86_400_000, "30d": 31 * 86_400_000}

# uplink_stats interface statuses that count as healthy / unhealthy for events
_UP_STATUSES = {"up", "ok", "active", "ready", "connected"}
_DOWN_STATUSES = {"down", "failed", "error", "no_link", "disconnected"}


def _events_path() -> Path:
    override = os.environ.get("GATEWAY_NETWORK_EVENTS_PATH")
    if override:
        return Path(override)
    for candidate in (_EVENTS_DEFAULT.parent, *_EVENTS_DEFAULT.parent.parents):
        if candidate.exists():
            return _EVENTS_DEFAULT if os.access(candidate, os.W_OK) else _EVENTS_FALLBACK
    return _EVENTS_FALLBACK


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class NetworkRuntime:
    def __init__(self) -> None:
        self.events_path = _events_path()
        self._prev_state: dict[str, Any] | None = None
        self._poll_task: asyncio.Task[None] | None = None

    # ── settings ─────────────────────────────────────────────────────────
    def load_settings(self) -> dict[str, Any] | None:
        return _read_json(CONFIG_PATH) or _read_json(DEFAULTS_FILE)

    def save_settings(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict) or "network" not in payload:
            raise ValueError("settings payload must contain a 'network' object")
        payload = dict(payload)
        payload.setdefault("version", 2)
        payload.pop("ok", None)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(CONFIG_PATH.parent), prefix=".net-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle, indent=2)
            os.replace(tmp, CONFIG_PATH)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ── state files ──────────────────────────────────────────────────────
    def state(self) -> dict[str, Any] | None:
        return _read_json(STATE_DIR / "state.json")

    def apply_result(self) -> dict[str, Any] | None:
        return _read_json(STATE_DIR / "apply-result.json")

    def cellular_state(self) -> dict[str, Any] | None:
        return _read_json(STATE_DIR / "cellular-state.json")

    @property
    def available(self) -> bool:
        return CTL.is_file()

    # ── actions (blocking; call via asyncio.to_thread) ───────────────────
    def _run_ctl(self, *args: str, timeout: float) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                [str(CTL), *args], capture_output=True, text=True, timeout=timeout
            )
            return proc.returncode, proc.stdout, proc.stderr
        except FileNotFoundError:
            return 127, "", "gateway-networkctl not found on this system"
        except subprocess.TimeoutExpired:
            return 124, "", f"gateway-networkctl {' '.join(args)} timed out"

    def apply(self) -> dict[str, Any]:
        rc, _, err = self._run_ctl("apply", timeout=120)
        result = self.apply_result()
        if result is not None:
            return {"ok": bool(result.get("ok", rc == 0)), "apply_requested": True, "apply_result": result}
        return {
            "ok": rc == 0,
            "apply_requested": True,
            "apply_result": {
                "ok": rc == 0,
                "status": "apply_error" if rc else "applied",
                "timestamp": _iso_now(),
                "errors": [] if rc == 0 else [{"scope": "network", "code": "ctl_failed", "message": err.strip() or f"exit {rc}"}],
                "warnings": [],
            },
        }

    def scan_wifi(self, iface: str = "wlan0") -> dict[str, Any]:
        rc, out, err = self._run_ctl("scan-wifi", iface, timeout=45)
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
        return {
            "ok": False,
            "status": "scan_error",
            "networks": [],
            "errors": [{"scope": "wifi_client", "code": "scan_failed", "message": err.strip() or f"scan exited {rc}"}],
        }

    def cellular_refresh(self) -> dict[str, Any]:
        self._run_ctl("cellular", "refresh-state", timeout=60)
        cellular = self.cellular_state()
        state = self.state() or {}
        if cellular is None:
            cellular = state.get("cellular") if isinstance(state.get("cellular"), dict) else None
        return {
            "ok": cellular is not None,
            "cellular": cellular or {},
            "active_uplink": state.get("active_uplink", "none"),
        }

    # ── interface details (kernel-sourced, no runtime needed) ────────────
    def iface_details(self) -> dict[str, Any]:
        state = self.state() or {}
        uplink_ifaces = ((state.get("uplink_stats") or {}).get("interfaces")) or {}
        result: dict[str, Any] = {
            "ok": True,
            "active_uplink": state.get("active_uplink", "none"),
            "interfaces": {},
            "wifi": None,
        }
        for name in ("eth0", "eth1"):
            info = _eth_details(name)
            stats_key = uplink_ifaces.get(name) or {}
            info["internet_ok"] = bool(stats_key.get("internet_ok"))
            result["interfaces"][name] = info
        result["wifi"] = _wifi_details("wlan0")
        return result

    # ── event recorder ───────────────────────────────────────────────────
    async def start(self) -> None:
        if self._poll_task is None or self._poll_task.done():
            self._prev_state = self.state()
            self._poll_task = asyncio.create_task(self._poll_loop(), name="network-event-recorder")

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            try:
                new = self.state()
                if new is not None:
                    if self._prev_state is not None:
                        for event in self._diff(self._prev_state, new):
                            self._append_event(event)
                    self._prev_state = new
            except Exception:
                pass

    def _diff(self, prev: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        now_ms = int(time.time() * 1000)

        def base(event_type: str, severity: str) -> dict[str, Any]:
            return {
                "timestamp_ms": now_ms,
                "timestamp_utc": _iso_now(),
                "event_type": event_type,
                "severity": severity,
            }

        prev_stats = prev.get("uplink_stats") or {}
        new_stats = new.get("uplink_stats") or {}

        # whole-network outage transitions
        prev_up = bool((prev_stats.get("network") or {}).get("has_uplink"))
        new_up = bool((new_stats.get("network") or {}).get("has_uplink"))
        if prev_up and not new_up:
            event = base("outage_started", "error")
            event["message"] = "No working internet uplink."
            events.append(event)
        elif not prev_up and new_up:
            event = base("outage_recovered", "info")
            duration_s = int((new_stats.get("network") or {}).get("last_down_duration_seconds") or 0)
            if duration_s:
                event["duration_ms"] = duration_s * 1000
            event["active_uplink"] = new.get("active_uplink", "")
            events.append(event)

        # active uplink switches
        prev_active = str(prev.get("active_uplink") or "none")
        new_active = str(new.get("active_uplink") or "none")
        if prev_active != new_active:
            event = base("uplink_switch", "warning" if new_active in ("none", "cellular") else "info")
            event["previous_uplink"] = prev_active
            event["active_uplink"] = new_active
            failover = new_stats.get("last_failover") or {}
            if failover.get("reason"):
                event["reason"] = str(failover["reason"])
            events.append(event)

        # per-interface health transitions
        prev_ifaces = prev_stats.get("interfaces") or {}
        new_ifaces = new_stats.get("interfaces") or {}
        for key, entry in new_ifaces.items():
            if not isinstance(entry, dict):
                continue
            old = prev_ifaces.get(key) or {}
            old_status = str(old.get("status") or "").lower()
            new_status = str(entry.get("status") or "").lower()
            if old_status == new_status or not old_status:
                continue
            if new_status in _DOWN_STATUSES and old_status not in _DOWN_STATUSES:
                event = base("interface_issue_started", "warning")
                event["iface"] = key
                event["message"] = f"{key} is {new_status}."
                events.append(event)
            elif new_status in _UP_STATUSES and old_status in _DOWN_STATUSES:
                event = base("interface_recovered", "info")
                event["iface"] = key
                event["message"] = f"{key} recovered."
                duration_s = int(entry.get("last_down_duration_seconds") or 0)
                if duration_s:
                    event["duration_ms"] = duration_s * 1000
                events.append(event)

        # tailscale recovery triggers
        prev_ts = prev.get("tailscale_recovery") or {}
        new_ts = new.get("tailscale_recovery") or {}
        prev_count = int(prev_ts.get("count") or prev_ts.get("trigger_count") or 0)
        new_count = int(new_ts.get("count") or new_ts.get("trigger_count") or 0)
        if new_count > prev_count:
            event = base("tailscale_recovery", "info")
            if new_ts.get("last_reason"):
                event["reason"] = str(new_ts["last_reason"])
            events.append(event)

        return events

    def _append_event(self, event: dict[str, Any]) -> None:
        try:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a") as handle:
                handle.write(json.dumps(event, separators=(",", ":")) + "\n")
            self._maybe_compact()
        except OSError:
            pass

    def _maybe_compact(self) -> None:
        try:
            if self.events_path.stat().st_size < 2_000_000:
                return
            lines = self.events_path.read_text().splitlines()[-5000:]
            self.events_path.write_text("\n".join(lines) + "\n")
        except OSError:
            pass

    def events(self, window: str = "7d", limit: int = 100) -> dict[str, Any]:
        cutoff = int(time.time() * 1000) - WINDOW_MS.get(window, WINDOW_MS["7d"])
        rows: list[dict[str, Any]] = []
        try:
            for line in self.events_path.read_text().splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and int(event.get("timestamp_ms") or 0) >= cutoff:
                    rows.append(event)
        except OSError:
            pass
        rows.sort(key=lambda e: e.get("timestamp_ms") or 0, reverse=True)
        rows = rows[: max(1, int(limit))]

        summary = {
            "outages": sum(1 for e in rows if e.get("event_type") == "outage_started"),
            "recovered": sum(1 for e in rows if e.get("event_type") == "outage_recovered"),
            "switches": sum(1 for e in rows if e.get("event_type") == "uplink_switch"),
        }
        open_outage = None
        state = self.state() or {}
        network = (state.get("uplink_stats") or {}).get("network") or {}
        if network and not network.get("has_uplink", True):
            open_outage = {
                "started_at": network.get("down_since_timestamp") or "",
                "duration_seconds": int(network.get("current_down_seconds") or 0),
            }
        return {"ok": True, "events": rows, "open_outage": open_outage, "summary": summary}


# ── kernel-level interface introspection ─────────────────────────────────
def _sys_net(name: str, attr: str) -> str:
    try:
        return (Path("/sys/class/net") / name / attr).read_text().strip()
    except OSError:
        return ""


def _ip_json(*args: str) -> list[Any]:
    try:
        proc = subprocess.run(["ip", "-j", *args], capture_output=True, text=True, timeout=5)
        data = json.loads(proc.stdout or "[]")
        return data if isinstance(data, list) else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def _addresses(name: str) -> tuple[str, list[str]]:
    ipv4, ipv6 = "", []
    for entry in _ip_json("addr", "show", "dev", name):
        for addr in entry.get("addr_info") or []:
            value = f"{addr.get('local', '')}/{addr.get('prefixlen', '')}"
            if addr.get("family") == "inet" and not ipv4:
                ipv4 = value
            elif addr.get("family") == "inet6":
                ipv6.append(value)
    return ipv4, ipv6


def _default_gateway(name: str) -> str:
    for route in _ip_json("route", "show", "default", "dev", name):
        if route.get("gateway"):
            return str(route["gateway"])
    return ""


def _dns_servers() -> list[str]:
    servers: list[str] = []
    try:
        for line in Path("/etc/resolv.conf").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "nameserver":
                servers.append(parts[1])
    except OSError:
        pass
    return servers[:3]


def _eth_details(name: str) -> dict[str, Any]:
    operstate = _sys_net(name, "operstate") or "missing"
    ipv4, ipv6 = _addresses(name)
    speed = _sys_net(name, "speed")
    if speed in ("", "-1"):
        speed = ""
    else:
        speed = f"{speed} Mb/s"
    return {
        "link_up": operstate == "up",
        "operstate": operstate,
        "mac": _sys_net(name, "address"),
        "mtu": _sys_net(name, "mtu"),
        "speed": speed,
        "duplex": _sys_net(name, "duplex"),
        "ipv4": ipv4,
        "ipv6": [{"addr": a, "scope": ""} for a in ipv6],
        "gateway": _default_gateway(name),
        "dns": _dns_servers(),
    }


def _wifi_details(name: str) -> dict[str, Any] | None:
    operstate = _sys_net(name, "operstate")
    if not operstate:
        return None
    info: dict[str, Any] = {
        "mac": _sys_net(name, "address"),
        "operstate": operstate,
        "link_up": operstate == "up",
        "ssid": "", "bssid": "", "mode": "", "channel": "", "freq_mhz": 0,
        "signal_dbm": None, "signal_pct": None, "tx_bitrate": "", "rx_bitrate": "",
    }
    info["ipv4"], v6 = _addresses(name)
    info["ipv6"] = [{"addr": a, "scope": ""} for a in v6]
    try:
        link = subprocess.run(["iw", "dev", name, "link"], capture_output=True, text=True, timeout=5).stdout
        iw_info = subprocess.run(["iw", "dev", name, "info"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return info
    match = re.search(r"Connected to ([0-9a-f:]{17})", link)
    if match:
        info["bssid"] = match.group(1)
    for pattern, key, cast in (
        (r"SSID: (.+)", "ssid", str),
        (r"freq: (\d+)", "freq_mhz", int),
        (r"signal: (-?\d+)", "signal_dbm", int),
        (r"tx bitrate: ([\d.]+ [A-Za-z/]+)", "tx_bitrate", str),
        (r"rx bitrate: ([\d.]+ [A-Za-z/]+)", "rx_bitrate", str),
    ):
        match = re.search(pattern, link)
        if match:
            info[key] = cast(match.group(1).strip())
    match = re.search(r"type (\w+)", iw_info)
    if match:
        info["mode"] = match.group(1)
    match = re.search(r"channel (\d+)", iw_info)
    if match:
        info["channel"] = match.group(1)
    if isinstance(info["signal_dbm"], int):
        info["signal_pct"] = max(0, min(100, 2 * (info["signal_dbm"] + 100)))
    return info


RUNTIME = NetworkRuntime()
