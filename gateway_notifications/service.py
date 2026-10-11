"""Watches for things worth telling an operator about, and delivers them.

Notifications are driven by *incident transitions* rather than raw events. The
correlator has already reduced a fault to one incident with an ID, tracked when
it recovered, and named the likely failure domain — so an unreachable server
produces exactly one notification when it breaks and one when it comes back,
however many underlying events occurred. That is what stops a single fault
paging someone forty times.

Everything here runs on a worker thread; nothing blocks the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from . import channels as channel_delivery
from .compose import domain_label, incident_details
from .config import EVENT_TYPES, SEVERITIES, load_config
from .console_links import console_links
from gateway_incidents import INCIDENT_HOMES, incident_home, wording


LOGGER = logging.getLogger("edge_server")
POLL_INTERVAL_S = 20.0
# A changed diagnosis must hold this long before a correction is sent, so
# evidence that wobbles between two verdicts cannot produce a stream of emails.
REVISION_SETTLE_MS = 60_000
RETRY_BASE_S = 5.0
MAX_LOG_ENTRIES = 200

# Which notification event an incident maps to when it opens.
_DOMAIN_EVENT = {
    "source": "source_offline",
    "destination": "destination_unavailable",
    "gateway": "gateway_outage",
    "uplink": "gateway_outage",
    "local_network": "gateway_outage",
}


class NotificationService:
    def __init__(self) -> None:
        self.incidents: Any = None
        self.forwarding: Any = None
        self.gateway_id: str = ""
        self.base_url: str = ""
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._buffer_warned = False
        # incident id -> (candidate domain, first seen ms) while a revision settles
        self._revisions: dict[int, tuple[str, int]] = {}
        self._sent_times: deque[float] = deque(maxlen=1000)
        self._log: deque[dict[str, Any]] = deque(maxlen=MAX_LOG_ENTRIES)

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run(), name="notifications")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self.poll_once)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.error("notification_poll_failed error=%s", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=POLL_INTERVAL_S)
                return
            except TimeoutError:
                continue

    # ── detection ────────────────────────────────────────────────────────
    def poll_once(self) -> None:
        config = load_config()
        notes = self._pending_notifications(config)
        # Transitions are recorded even with no channel enabled, so adding a
        # channel later does not suddenly announce a backlog of old incidents.
        if not any(c.get("enabled") for c in config.get("channels") or []):
            return
        for note in notes:
            self._dispatch(config, note)

    def _pending_notifications(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        store = getattr(self.incidents, "storage", None)

        now_ms = int(time.time() * 1000)
        for incident in self._recent_incidents():
            status = str(incident.get("status") or "")
            domain = str(incident.get("domain") or "")
            previous = incident.get("notified_state")
            told = incident.get("notified_domain")
            incident_id = int(incident["id"])

            if previous == status:
                # No state change — but if the diagnosis readers were given has
                # since changed, they are acting on a wrong cause; correct it.
                if status in ("open", "recovering") and told and domain != told:
                    if self._revision_settled(incident_id, domain, now_ms):
                        notes.append(self._incident_note(incident, stage="revised", told_domain=told))
                        self._revisions.pop(incident_id, None)
                        if store is not None:
                            store.mark_notified(incident_id, status, domain)
                else:
                    self._revisions.pop(incident_id, None)
                continue

            # One message per state a reader cares about: it broke, it is
            # working again (sent the moment service returns, not 5 minutes
            # later), and it is closed with final figures. A relapse inside the
            # stability window is announced as active again.
            if previous is None and status in ("open", "recovering"):
                notes.append(self._incident_note(incident, stage="open"))
            elif previous == "open" and status == "recovering":
                notes.append(self._incident_note(incident, stage="restored", told_domain=told))
            elif previous == "recovering" and status == "open":
                notes.append(self._incident_note(incident, stage="relapsed", told_domain=told))
            elif status == "resolved":
                # Also covers opened-and-closed between two polls.
                notes.append(self._incident_note(incident, stage="closed", told_domain=told))
            self._revisions.pop(incident_id, None)
            if store is not None:
                store.mark_notified(incident_id, status, domain)

        buffer_note = self._buffer_note(config)
        if buffer_note is not None:
            notes.append(buffer_note)
        return notes

    def _revision_settled(self, incident_id: int, domain: str, now_ms: int) -> bool:
        candidate = self._revisions.get(incident_id)
        if candidate is None or candidate[0] != domain:
            self._revisions[incident_id] = (domain, now_ms)
            return False
        return now_ms - candidate[1] >= REVISION_SETTLE_MS

    def _incident_note(
        self, incident: dict[str, Any], *, stage: str, told_domain: str | None = None,
    ) -> dict[str, Any]:
        kpi = incident.get("kpi") or {}
        # A revision of a live incident is as actionable as the first alert.
        opened = stage in ("open", "relapsed") or (stage == "revised" and incident.get("status") == "open")
        details = incident_details(incident, stage=stage, told_domain=told_domain)
        ref = str(incident.get("ref") or "")
        domain = str(incident.get("domain") or "")
        # Opens the incident over the page that owns it, on every address the
        # gateway can be reached at.
        path = INCIDENT_HOMES[incident_home(incident)]
        links = self._links(ref, path)
        return {
            "event": "recovery" if not opened else _DOMAIN_EVENT.get(domain, "source_offline"),
            "severity": "info" if not opened else _severity_for(incident),
            "incident_ref": ref,
            "status": details["status"],
            "status_label": details["status_label"],
            "title": wording.incident_title(incident),
            "message": details["summary"],
            "failure_domain": domain_label(incident),
            "started_at": _iso(incident.get("started_ms")),
            "resolved_at": _iso(incident.get("restored_ms")) if not opened else None,
            "stage": stage,
            # What is waiting to be delivered — not the whole queue's peak, and
            # nothing at all for a source that stopped, which buffers nothing.
            "buffered_records": None if kpi.get("source_outage") else kpi.get("pending"),
            "affected": details["affected"]["sources"],
            "details": details,
            "links": links,
            "dashboard_url": links[0]["url"] if links else "",
            "gateway_id": self.gateway_id,
            "timestamp": _iso(int(time.time() * 1000)),
        }

    def _buffer_note(self, config: dict[str, Any]) -> dict[str, Any] | None:
        """Warn once while there is still room to act, and reset on recovery."""
        threshold = int((config.get("rules") or {}).get("buffer_warn_percent") or 80)
        usage = self._buffer_usage_percent()
        if usage is None:
            return None
        if usage < threshold:
            self._buffer_warned = False
            return None
        if self._buffer_warned:
            return None
        self._buffer_warned = True
        return {
            "event": "buffer_threshold",
            "severity": "warning",
            "incident_ref": None,
            "title": "Local buffer approaching capacity",
            "message": (
                f"The local message buffer is at {usage}% of its configured capacity. "
                "Once full, the oldest records are dropped to make room for new ones."
            ),
            "failure_domain": None,
            "started_at": None,
            "resolved_at": None,
            "buffered_records": self._buffer_pending(),
            "affected": [],
            "links": self._links(None, "/forwarding"),
            "dashboard_url": self._dashboard_url(None, path="/forwarding"),
            "gateway_id": self.gateway_id,
            "timestamp": _iso(int(time.time() * 1000)),
        }

    # ── delivery ─────────────────────────────────────────────────────────
    def _dispatch(self, config: dict[str, Any], note: dict[str, Any]) -> None:
        rules = config.get("rules") or {}
        if not self._within_rate_limit(int(rules.get("max_per_hour") or 30)):
            LOGGER.warning("notification_rate_limited event=%s", note.get("event"))
            self._record(note, None, "rate-limited", ok=False)
            return
        for channel in config.get("channels") or []:
            if not channel.get("enabled") or not self._wants(channel, note):
                continue
            self._deliver_with_retry(channel, note, int(rules.get("max_retries") or 4))

    def _wants(self, channel: dict[str, Any], note: dict[str, Any]) -> bool:
        if note.get("event") not in (channel.get("events") or []):
            return False
        minimum = str(channel.get("min_severity") or "warning")
        try:
            return SEVERITIES.index(str(note.get("severity"))) >= SEVERITIES.index(minimum)
        except ValueError:
            return True

    def _deliver_with_retry(self, channel: dict[str, Any], note: dict[str, Any], max_retries: int) -> None:
        """Retry a temporarily unreachable destination with exponential backoff.

        Bounded: a destination that is simply down must not hold the notifier
        open indefinitely or queue unbounded work behind it.
        """
        attempt = 0
        while True:
            try:
                channel_delivery.deliver(channel, note)
                self._sent_times.append(time.time())
                self._record(note, channel, "delivered", ok=True, attempts=attempt + 1)
                return
            except Exception as exc:
                attempt += 1
                if attempt > max_retries:
                    LOGGER.error(
                        "notification_failed channel=%s event=%s error=%s",
                        channel.get("name"), note.get("event"), exc,
                    )
                    self._record(note, channel, str(exc)[:200], ok=False, attempts=attempt)
                    return
                if self._stop_event.is_set():
                    return
                time.sleep(min(60.0, RETRY_BASE_S * (2 ** (attempt - 1))))

    def _within_rate_limit(self, max_per_hour: int) -> bool:
        cutoff = time.time() - 3600
        while self._sent_times and self._sent_times[0] < cutoff:
            self._sent_times.popleft()
        return len(self._sent_times) < max_per_hour

    def _record(
        self, note: dict[str, Any], channel: dict[str, Any] | None,
        detail: str, *, ok: bool, attempts: int = 0,
    ) -> None:
        self._log.appendleft({
            "at": _iso(int(time.time() * 1000)),
            "event": note.get("event"),
            "incident_ref": note.get("incident_ref"),
            "channel": (channel or {}).get("name") or "—",
            "channel_type": (channel or {}).get("type") or "—",
            "ok": ok,
            "detail": detail,
            "attempts": attempts,
        })

    def recent_deliveries(self) -> list[dict[str, Any]]:
        return list(self._log)

    def send_test(self, channel: dict[str, Any]) -> None:
        """Deliver a sample notification so an operator can verify a channel."""
        channel_delivery.deliver(channel, {
            "event": "recovery",
            "severity": "info",
            "incident_ref": "MC-TEST",
            "title": "Test notification",
            "message": (
                "This is a test from the MetaCrust Edge Gateway. If you can read this, "
                "the channel is configured correctly."
            ),
            "failure_domain": None,
            "started_at": _iso(int(time.time() * 1000)),
            "resolved_at": None,
            "buffered_records": None,
            "affected": [],
            "links": self._links(None, "/"),
            "dashboard_url": self._dashboard_url(None, path="/"),
            "gateway_id": self.gateway_id,
            "timestamp": _iso(int(time.time() * 1000)),
        })

    # ── data access ──────────────────────────────────────────────────────
    def _recent_incidents(self) -> list[dict[str, Any]]:
        store = getattr(self.incidents, "storage", None)
        if store is None:
            return []
        try:
            since = int(time.time() * 1000) - 86_400_000
            rows = store.query(from_ms=since, limit=200)
            open_rows = store.open_incidents()
        except Exception:
            return []
        merged = {row["id"]: row for row in rows}
        merged.update({row["id"]: row for row in open_rows})
        return list(merged.values())

    def _open_incidents(self) -> list[dict[str, Any]]:
        store = getattr(self.incidents, "storage", None)
        try:
            return store.open_incidents() if store is not None else []
        except Exception:
            return []

    def _buffer_usage_percent(self) -> int | None:
        stats = self._buffer_stats()
        if not stats:
            return None
        pending = int(stats.get("total_pending") or 0)
        capacity = int(stats.get("capacity") or 0)
        if capacity <= 0:
            return None
        return min(100, round(100 * pending / capacity))

    def _buffer_pending(self) -> int:
        return int((self._buffer_stats() or {}).get("total_pending") or 0)

    def _buffer_stats(self) -> dict[str, Any] | None:
        if self.forwarding is None:
            return None
        try:
            return self.forwarding.buffer_stats()
        except Exception:
            return None

    def _links(self, ref: str | None, path: str) -> list[dict[str, str]]:
        """Console links on every reachable address, Tailscale first."""
        suffix = f"{path}?incident={ref}" if ref else path
        try:
            bases = console_links(self.base_url or "")
        except Exception:
            bases = []
        if not bases and self.base_url:
            bases = [{"label": "Gateway console", "url": self.base_url.rstrip("/")}]
        return [{"label": b["label"], "url": b["url"] + suffix} for b in bases]

    def _dashboard_url(self, ref: str | None, path: str = "/insights") -> str:
        links = self._links(ref, path)
        return links[0]["url"] if links else ""


def _severity_for(incident: dict[str, Any]) -> str:
    return "critical" if str(incident.get("severity")) == "critical" else "warning"


def _iso(ms: Any) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")



__all__ = ["NotificationService", "EVENT_TYPES"]
