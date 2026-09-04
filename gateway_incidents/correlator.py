"""Correlate raw subsystem events into customer-understandable incidents.

Every subsystem reports its own faults — a sensor stops answering, an uplink
drops, an HTTPS endpoint refuses, the gateway overheats. On their own they are
a wall of unrelated lines, and one server outage looks like dozens of separate
problems. This turns them into one incident per real problem, and names the
layer most likely responsible.

The delivery path is:

    Source/Device -> Gateway -> Local Network -> Uplink/Internet -> Destination

A fault in any of the four shared layers interrupts delivery for *every*
device, so those collapse into a single incident that lists the affected
sources. A source that fails on its own is genuinely its own problem, so those
stay per-device.

Classification is evidence-driven and refuses to guess: when a check cannot be
evaluated — the network runtime is unavailable, say — the domain is reported as
Unknown rather than inferred from what is left.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# A fault must clear and stay clear this long before its incident is closed,
# so a flapping link is one incident rather than one per flap.
STABILITY_WINDOW_MS = 5 * 60_000
# How far back a correlation pass replays raw events to rebuild fault state.
LOOKBACK_MS = 7 * 86_400_000

SOURCE = "source"
GATEWAY = "gateway"
LOCAL_NETWORK = "local_network"
UPLINK = "uplink"
DESTINATION = "destination"
PATH_LAYERS = (GATEWAY, LOCAL_NETWORK, UPLINK, DESTINATION)

DOMAIN_LABELS = {
    SOURCE: "Source/Device",
    GATEWAY: "Gateway",
    LOCAL_NETWORK: "Local Network",
    UPLINK: "Uplink/Internet",
    DESTINATION: "Destination/Server",
    "unknown": "Unknown",
}

_DOWN_STATUSES = {"disconnected", "error", "offline", "silent", "timeout"}
# Only metrics that genuinely indicate the gateway itself is the problem.
_GATEWAY_METRICS = ("cpu.", "memory.", "storage.", "system.")


@dataclass
class Signal:
    """One up/down transition reported by a subsystem."""

    ts_ms: int
    layer: str
    scope: str
    label: str
    state: str  # "down" | "up"
    detail: str = ""


@dataclass
class Fault:
    """A currently-unresolved down signal."""

    layer: str
    scope: str
    label: str
    since_ms: int
    detail: str
    cleared_ms: int | None = None
    # Ended because the thing it was about stopped existing (profile disabled or
    # deleted, device removed) rather than because it recovered.
    retired: bool = False


def retire_vanished(
    open_faults: dict[tuple[str, str], Fault],
    live_scopes: dict[str, set[str]],
    now_ms: int,
) -> dict[tuple[str, str], Fault]:
    """Clear faults whose subject is no longer configured.

    A fault only clears when its subsystem reports recovery — but a disabled or
    deleted forwarding profile stops reporting anything at all, so its incident
    would stay open forever with no event that could ever close it. Anything
    that has left the configuration is retired here instead.
    """
    retired: dict[tuple[str, str], Fault] = {}
    for key, fault in list(open_faults.items()):
        allowed = live_scopes.get(fault.layer)
        if allowed is None or fault.scope in allowed:
            continue
        fault.cleared_ms = now_ms
        fault.retired = True
        retired[key] = fault
        open_faults.pop(key, None)
    return retired


@dataclass
class Checks:
    """Per-layer verdicts backing a classification.

    `None` means the check could not be evaluated — the difference between
    "healthy" and "unknown" is what keeps the classifier from guessing.
    """

    verdicts: dict[str, bool | None] = field(default_factory=dict)
    findings: dict[str, str] = field(default_factory=dict)

    def set(self, layer: str, ok: bool | None, finding: str) -> None:
        self.verdicts[layer] = ok
        self.findings[layer] = finding


# ── signal collection ────────────────────────────────────────────────────

def collect_signals(
    *, interfaces_storage: Any = None, forwarding: Any = None,
    network_runtime: Any = None, monitor_storage: Any = None,
    from_ms: int, to_ms: int,
) -> list[Signal]:
    signals: list[Signal] = []
    signals += _source_signals(interfaces_storage, from_ms, to_ms)
    signals += _destination_signals(forwarding, from_ms)
    signals += _network_signals(network_runtime, from_ms)
    signals += _gateway_signals(monitor_storage, from_ms)
    signals.sort(key=lambda s: s.ts_ms)
    return signals


def _source_signals(storage: Any, from_ms: int, to_ms: int) -> list[Signal]:
    if storage is None:
        return []
    try:
        rows = storage.status_events(from_ms=from_ms, to_ms=to_ms, limit=5000)
    except Exception:
        return []
    names = _source_names(storage)
    out: list[Signal] = []
    for row in rows:
        scope = f"{row['source_type']}:{row['source_id']}"
        status = str(row.get("status") or "").lower()
        out.append(Signal(
            ts_ms=int(row["ts_ms"]), layer=SOURCE, scope=scope,
            label=names.get(scope, row["source_id"]),
            state="down" if status in _DOWN_STATUSES else "up",
            detail=str(row.get("error") or "") or f"source {status}",
        ))
    return out


def _source_names(storage: Any) -> dict[str, str]:
    try:
        return {f"{row['source_type']}:{row['source_id']}": row["source_id"] for row in storage.sources()}
    except Exception:
        return {}


def _destination_signals(forwarding: Any, from_ms: int) -> list[Signal]:
    if forwarding is None:
        return []
    try:
        rows = forwarding.storage.recent_events(limit=2000, since_ms=from_ms)
    except Exception:
        return []
    names = _profile_names(forwarding)
    out: list[Signal] = []
    for row in rows:
        event = str(row.get("event") or "")
        if event not in {"connected", "disconnected", "connect_failed"}:
            continue
        pid = str(row.get("profile_id") or "")
        out.append(Signal(
            ts_ms=int(row["ts_ms"]), layer=DESTINATION, scope=pid,
            label=names.get(pid, pid), state="up" if event == "connected" else "down",
            detail=str(row.get("message") or ""),
        ))
    return out


def _profile_names(forwarding: Any) -> dict[str, str]:
    try:
        return {p["id"]: p.get("name", p["id"]) for p in (forwarding.config.get("profiles") or [])}
    except Exception:
        return {}


def _network_signals(network_runtime: Any, from_ms: int) -> list[Signal]:
    if network_runtime is None:
        return []
    try:
        payload = network_runtime.events(window="7d", limit=500)
    except Exception:
        return []
    out: list[Signal] = []
    for event in payload.get("events") or []:
        kind = str(event.get("event_type") or "")
        ts_ms = int(event.get("timestamp_ms") or 0)
        if ts_ms < from_ms:
            continue
        if kind == "outage_started":
            out.append(Signal(ts_ms, UPLINK, "uplink", "Internet uplink", "down",
                              str(event.get("message") or "no uplink available")))
        elif kind == "outage_recovered":
            out.append(Signal(ts_ms, UPLINK, "uplink", "Internet uplink", "up",
                              str(event.get("message") or "uplink restored")))
        elif kind == "interface_issue_started":
            iface = str(event.get("interface") or "interface")
            out.append(Signal(ts_ms, LOCAL_NETWORK, iface, iface, "down",
                              str(event.get("message") or "interface unavailable")))
        elif kind == "interface_recovered":
            iface = str(event.get("interface") or "interface")
            out.append(Signal(ts_ms, LOCAL_NETWORK, iface, iface, "up",
                              str(event.get("message") or "interface recovered")))
    return out


def _gateway_signals(monitor_storage: Any, from_ms: int) -> list[Signal]:
    """Critical device-health anomalies mean the gateway itself is degraded.

    The engine re-emits while a condition holds, so only the leading edge of
    each episode becomes a down signal, and the gateway is treated as healthy
    again once one stability window passes with nothing critical.
    """
    if monitor_storage is None:
        return []
    try:
        rows = monitor_storage.recent_anomalies(from_ms, limit=1000)
    except Exception:
        return []
    critical = sorted(
        (
            row for row in rows
            if str(row.get("severity") or "") == "Critical"
            and str(row.get("metric") or "").startswith(_GATEWAY_METRICS)
        ),
        key=lambda row: int(row["ts_ms"]),
    )
    out: list[Signal] = []
    last_ts = 0
    for row in critical:
        ts_ms = int(row["ts_ms"])
        if ts_ms - last_ts > STABILITY_WINDOW_MS:
            if last_ts:
                out.append(Signal(last_ts + STABILITY_WINDOW_MS, GATEWAY, "gateway",
                                  "Gateway health", "up", "device health returned to normal"))
            out.append(Signal(ts_ms, GATEWAY, "gateway", "Gateway health", "down",
                              str(row.get("headline") or row.get("message") or "device health critical")))
        last_ts = ts_ms
    if last_ts and time.time() * 1000 - last_ts > STABILITY_WINDOW_MS:
        out.append(Signal(last_ts + STABILITY_WINDOW_MS, GATEWAY, "gateway",
                          "Gateway health", "up", "device health returned to normal"))
    return out


# ── fault state ──────────────────────────────────────────────────────────

def replay_faults(signals: list[Signal]) -> tuple[dict[tuple[str, str], Fault], dict[tuple[str, str], Fault]]:
    """Fold signals into currently-open faults and recently-cleared ones."""
    open_faults: dict[tuple[str, str], Fault] = {}
    cleared: dict[tuple[str, str], Fault] = {}
    for signal in signals:
        key = (signal.layer, signal.scope)
        if signal.state == "down":
            cleared.pop(key, None)
            if key not in open_faults:
                open_faults[key] = Fault(signal.layer, signal.scope, signal.label, signal.ts_ms, signal.detail)
        else:
            fault = open_faults.pop(key, None)
            if fault is not None:
                fault.cleared_ms = signal.ts_ms
                cleared[key] = fault
    return open_faults, cleared


# ── classification ───────────────────────────────────────────────────────

def build_checks(faults: list[Fault], *, network_state: dict[str, Any] | None, source_total: int) -> Checks:
    """Evaluate every layer, recording unknowns honestly."""
    checks = Checks()
    by_layer: dict[str, list[Fault]] = {}
    for fault in faults:
        by_layer.setdefault(fault.layer, []).append(fault)

    down_sources = by_layer.get(SOURCE, [])
    if source_total == 0 and not down_sources:
        checks.set(SOURCE, None, "no sources configured")
    elif down_sources:
        names = ", ".join(sorted(f.label for f in down_sources))
        checks.set(SOURCE, False, f"not reporting: {names}")
    else:
        checks.set(SOURCE, True, "healthy — readings continued")

    if by_layer.get(GATEWAY):
        checks.set(GATEWAY, False, by_layer[GATEWAY][0].detail or "device health critical")
    else:
        checks.set(GATEWAY, True, "healthy")

    if network_state is None:
        checks.set(LOCAL_NETWORK, None, "network runtime unavailable")
        checks.set(UPLINK, None, "network runtime unavailable")
    else:
        local_faults = by_layer.get(LOCAL_NETWORK, [])
        if local_faults:
            checks.set(LOCAL_NETWORK, False, f"interface down: {', '.join(sorted(f.label for f in local_faults))}")
        else:
            checks.set(LOCAL_NETWORK, True, "interfaces up")
        if by_layer.get(UPLINK):
            checks.set(UPLINK, False, "no internet uplink")
        else:
            active = str((network_state or {}).get("active_uplink") or "") or "uplink"
            checks.set(UPLINK, True, f"reachable via {active}")

    dest_faults = by_layer.get(DESTINATION, [])
    if dest_faults:
        checks.set(DESTINATION, False, dest_faults[0].detail or "destination unreachable")
    else:
        checks.set(DESTINATION, True, "accepting data")
    return checks


def classify(checks: Checks, *, scope_kind: str = "path") -> tuple[str, str]:
    """Pick the most likely failure domain, or Unknown when unprovable.

    Ordered by depth: a fault closer to the gateway explains everything
    downstream of it, so it wins. A destination fault is only blamed on the
    destination once every layer in front of it has been positively verified —
    otherwise the honest answer is Unknown.

    Scope matters. For a delivery-path incident the question is "what stopped
    the data getting out", so every layer counts. For a single source that went
    quiet the question is "why did this sensor stop", and the destination and
    uplink sit *downstream* of it — an unreachable server cannot stop a sensor
    answering, so those layers are excluded rather than blamed.
    """
    verdicts = checks.verdicts

    def failed(layer: str) -> bool:
        return verdicts.get(layer) is False

    def healthy(layer: str) -> bool:
        return verdicts.get(layer) is True

    if scope_kind == "source":
        if failed(GATEWAY):
            return GATEWAY, "high"
        if failed(LOCAL_NETWORK):
            return LOCAL_NETWORK, "high"
        if failed(SOURCE):
            if healthy(GATEWAY) and verdicts.get(LOCAL_NETWORK) is not False:
                return SOURCE, "high"
            return SOURCE, "medium"
        return "unknown", "low"

    if failed(GATEWAY):
        return GATEWAY, "high"
    if failed(UPLINK):
        return UPLINK, "high"
    if failed(LOCAL_NETWORK):
        return LOCAL_NETWORK, "high"
    if failed(DESTINATION):
        upstream = (GATEWAY, LOCAL_NETWORK, UPLINK)
        if all(healthy(layer) for layer in upstream):
            return DESTINATION, "high"
        if any(verdicts.get(layer) is None for layer in upstream):
            return "unknown", "low"
        return DESTINATION, "medium"
    if failed(SOURCE):
        if healthy(GATEWAY) and verdicts.get(LOCAL_NETWORK) is not False:
            return SOURCE, "high"
        return "unknown", "low"
    return "unknown", "low"


def evidence_rows(checks: Checks) -> list[dict[str, Any]]:
    order = (SOURCE, GATEWAY, LOCAL_NETWORK, UPLINK, DESTINATION)
    labels = {
        SOURCE: "Source polling", GATEWAY: "Gateway", LOCAL_NETWORK: "Local network",
        UPLINK: "Uplink/Internet", DESTINATION: "Destination server",
    }
    rows = []
    for layer in order:
        if layer not in checks.verdicts:
            continue
        ok = checks.verdicts[layer]
        rows.append({
            "layer": layer,
            "check": labels[layer],
            "state": "unknown" if ok is None else ("ok" if ok else "failed"),
            "finding": checks.findings.get(layer, ""),
        })
    return rows
