"""Periodic correlation pass: open, update and close incidents."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .correlator import (
    DESTINATION as DESTINATION_LAYER,
    DOMAIN_LABELS,
    GATEWAY as GATEWAY_LAYER,
    LOCAL_NETWORK as LOCAL_NETWORK_LAYER,
    LOOKBACK_MS,
    PATH_LAYERS,
    SOURCE,
    STABILITY_WINDOW_MS,
    Fault,
    build_checks,
    classify,
    collect_signals,
    evidence_rows,
    incident_worthy,
    replay_faults,
    retire_vanished,
)
from . import kpi as kpi_mod
from .storage import IncidentStorage


LOGGER = logging.getLogger("edge_server")
CORRELATE_INTERVAL_S = 20.0
PATH_SCOPE_KEY = "delivery"
# A source must have reported this recently to count as affected by a delivery
# interruption — anything older had nothing in flight to lose.
ACTIVE_SOURCE_WINDOW_MS = 60 * 60_000
_DOWN_STATUSES = {"disconnected", "error", "offline", "silent", "timeout"}


class IncidentTask:
    """Owns incident lifecycle. Every pass runs on a worker thread."""

    def __init__(self, storage: IncidentStorage | None = None) -> None:
        self.storage = storage or IncidentStorage()
        self.interfaces_storage: Any = None
        self.forwarding: Any = None
        self.network_runtime: Any = None
        self.monitor_storage: Any = None
        self.edge_server: Any = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        try:
            self.storage.open()
        except Exception as exc:
            LOGGER.error("incident_storage_unavailable error=%s", exc)
            return
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run(), name="incident-correlator")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        try:
            self.storage.close()
        except Exception as exc:
            LOGGER.error("incident_storage_close_failed error=%s", exc)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self.correlate_once)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.error("incident_correlation_failed error=%s", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=CORRELATE_INTERVAL_S)
                return
            except TimeoutError:
                continue

    # ── one pass ─────────────────────────────────────────────────────────
    def correlate_once(self) -> None:
        now_ms = int(time.time() * 1000)
        signals = collect_signals(
            interfaces_storage=self.interfaces_storage,
            forwarding=self.forwarding,
            network_runtime=self.network_runtime,
            monitor_storage=self.monitor_storage,
            edge_server=self.edge_server,
            from_ms=now_ms - LOOKBACK_MS,
            to_ms=now_ms,
        )
        open_faults, cleared = replay_faults(signals)
        # Anything that has left the configuration can never report recovery, so
        # retire it here rather than leaving its incident open indefinitely.
        cleared.update(retire_vanished(open_faults, self._live_scopes(), now_ms))
        network_state = self._network_state()
        source_total = self._source_total()
        continuity = self._continuity()
        counters = self._counters()

        # Every open path fault informs the evidence; only the significant ones
        # may raise an incident. A two-second failover is context, not news.
        path_faults_seen = [f for key, f in open_faults.items() if key[0] in PATH_LAYERS]
        path_faults = [f for f in path_faults_seen if incident_worthy(f, now_ms)]
        source_faults = [f for key, f in open_faults.items() if key[0] == SOURCE]

        # A shared-layer fault interrupts delivery for every device, so it is one
        # incident naming all affected sources — not one per device.
        self._reconcile(
            scope_kind="path", scope_key=PATH_SCOPE_KEY, faults=path_faults,
            cleared={k: v for k, v in cleared.items() if k[0] in PATH_LAYERS},
            now_ms=now_ms, network_state=network_state, source_total=source_total,
            continuity=continuity, all_faults=path_faults_seen + source_faults,
            counters=counters, source_gap=bool(source_faults),
        )

        # A source failing on its own is its own incident. It is only folded into
        # the path incident when a fault that could plausibly *cause* it is open:
        # a degraded gateway or a downed local interface can stop sources being
        # polled, whereas an unreachable uplink or destination cannot — those are
        # downstream of the sensors, so a sensor failing at the same time is a
        # genuinely separate problem and deserves its own incident.
        explains_source_loss = any(f.layer in (GATEWAY_LAYER, LOCAL_NETWORK_LAYER) for f in path_faults_seen)
        for fault in source_faults:
            self._reconcile(
                scope_kind="source", scope_key=fault.scope, faults=[fault],
                cleared={}, now_ms=now_ms, network_state=network_state,
                source_total=source_total, continuity=continuity,
                all_faults=path_faults_seen + [fault], suppressed=explains_source_loss,
                counters=counters, source_gap=True,
            )
        for key, fault in cleared.items():
            if key[0] == SOURCE:
                self._reconcile(
                    scope_kind="source", scope_key=fault.scope, faults=[],
                    cleared={key: fault}, now_ms=now_ms, network_state=network_state,
                    source_total=source_total, continuity=continuity, all_faults=path_faults_seen,
                    counters=counters, source_gap=True,
                )

    def _reconcile(
        self, *, scope_kind: str, scope_key: str, faults: list[Fault],
        cleared: dict[tuple[str, str], Fault], now_ms: int,
        network_state: dict[str, Any] | None, source_total: int,
        continuity: dict[str, Any], all_faults: list[Fault], counters: dict[str, int],
        source_gap: bool = False, suppressed: bool = False,
    ) -> None:
        existing = self.storage.open_for_scope(scope_kind, scope_key)

        if not faults:
            if existing is None:
                return
            restored = existing.get("restored_ms") or self._latest_clear(cleared) or now_ms
            # Nothing to wait for when the subject itself is gone: there is no
            # link left that could flap, so it closes at once and says why.
            retired = any(f.retired for f in cleared.values())
            if retired or now_ms - int(restored) >= STABILITY_WINDOW_MS:
                timeline = list(existing.get("timeline") or [])
                timeline.append({
                    "ts_ms": now_ms,
                    "kind": "closed_retired" if retired else "closed_stable",
                })
                final_continuity = {**existing.get("continuity", {}), **continuity,
                                    "unrecovered": continuity.get("pending", 0)}
                closed = {**existing, "restored_ms": int(restored)}
                self.storage.update_incident(existing["id"], {
                    "status": "resolved", "restored_ms": int(restored), "closed_ms": now_ms,
                    "continuity_json": final_continuity,
                    "timeline_json": timeline,
                    # Frozen at close: the pilot report reads this record, so it
                    # must not drift as lifetime counters keep moving afterwards.
                    "kpi_json": self._kpi_for(closed, counters, final_continuity, source_gap, now_ms),
                })
            else:
                # Still inside the stability window. Keep refreshing continuity so
                # the operator can watch the buffered backlog drain during replay.
                merged = {**(existing.get("continuity") or {}), **continuity}
                updates: dict[str, Any] = {
                    "restored_ms": int(restored), "continuity_json": merged,
                    # Replay happens in this window, so the KPI must follow it;
                    # otherwise a restored incident shows "0 replayed" until close.
                    "kpi_json": self._kpi_for(
                        {**existing, "restored_ms": int(restored)},
                        counters, merged, source_gap, now_ms,
                    ),
                }
                if existing.get("status") != "recovering":
                    timeline = list(existing.get("timeline") or [])
                    timeline.append({"ts_ms": int(restored), "kind": "restored"})
                    updates["status"] = "recovering"
                    updates["timeline_json"] = timeline
                self.storage.update_incident(existing["id"], updates)
            return

        if suppressed and existing is None:
            return

        checks = build_checks(all_faults, network_state=network_state, source_total=source_total)
        domain, confidence = classify(checks, scope_kind=scope_kind)
        evidence = evidence_rows(checks)
        affected = self._affected(scope_kind, faults, source_total)
        started = min(int(f.since_ms) for f in faults)

        if existing is None:
            ref = self.storage.next_ref()
            incident = self.storage.open_incident({
                "ref": ref, "scope_kind": scope_kind, "scope_key": scope_key,
                "title": self._title(scope_kind, affected, domain),
                "started_ms": started, "detected_ms": now_ms,
                "domain": domain, "domain_conf": confidence,
                "severity": self._severity(domain, continuity),
                "affected": affected, "evidence": evidence, "continuity": continuity,
                "timeline": [
                    {"ts_ms": started, "kind": "started"},
                    {"ts_ms": now_ms, "kind": "detected"},
                ],
                # The baseline is frozen now so later counter readings measure
                # this incident rather than the gateway's whole lifetime.
                "kpi": {"baseline": kpi_mod.baseline_from(counters)},
            })
            self._write_kpi(incident, counters, continuity, source_gap, now_ms)
            LOGGER.info(
                "incident_opened ref=%s scope=%s domain=%s confidence=%s",
                incident["ref"], scope_key, domain, confidence,
            )
            return

        # Still open: refresh the live picture, and keep the worst buffering seen.
        merged = dict(existing.get("continuity") or {})
        merged.update(continuity)
        merged["buffered_peak"] = max(
            int((existing.get("continuity") or {}).get("buffered_peak") or 0),
            int(continuity.get("pending") or 0),
        )
        updates: dict[str, Any] = {
            "domain": domain, "domain_conf": confidence,
            "severity": self._severity(domain, merged),
            "affected_json": affected, "evidence_json": evidence, "continuity_json": merged,
            "title": self._title(scope_kind, affected, domain),
            "kpi_json": self._kpi_for(existing, counters, merged, source_gap, now_ms),
        }
        if existing.get("status") == "recovering":
            # It broke again inside the stability window — same incident.
            updates["status"] = "open"
            updates["restored_ms"] = None
        self.storage.update_incident(existing["id"], updates)

    # ── helpers ──────────────────────────────────────────────────────────
    def _latest_clear(self, cleared: dict[tuple[str, str], Fault]) -> int | None:
        stamps = [f.cleared_ms for f in cleared.values() if f.cleared_ms]
        return max(stamps) if stamps else None

    def _affected(self, scope_kind: str, faults: list[Fault], source_total: int) -> list[dict[str, Any]]:
        if scope_kind == "source":
            return [{"kind": "source", "id": f.scope, "name": f.label} for f in faults]
        # Only sources that were actually producing data are affected by a
        # delivery interruption. A port that is disabled, or a device that is
        # itself down, has nothing in flight to lose — listing it would overstate
        # the blast radius.
        rows: list[dict[str, Any]] = []
        cutoff = int(time.time() * 1000) - ACTIVE_SOURCE_WINDOW_MS
        try:
            for row in (self.interfaces_storage.sources() if self.interfaces_storage else []):
                if int(row.get("last_seen_ms") or 0) < cutoff:
                    continue
                if str(row.get("last_status") or "").lower() in _DOWN_STATUSES:
                    continue
                rows.append({
                    "kind": "source",
                    "id": f"{row['source_type']}:{row['source_id']}",
                    "name": row["source_id"],
                })
        except Exception:
            pass
        for fault in faults:
            rows.append({"kind": fault.layer, "id": fault.scope, "name": fault.label})
        return rows

    def _title(self, scope_kind: str, affected: list[dict[str, Any]], domain: str) -> str:
        sources = [a["name"] for a in affected if a.get("kind") == "source"]
        if scope_kind == "source":
            return f"{sources[0] if sources else 'Source'} stopped reporting"
        if len(sources) == 1:
            return f"{sources[0]} data delivery interruption"
        if sources:
            return f"Data delivery interruption — {len(sources)} sources"
        return f"{DOMAIN_LABELS.get(domain, 'Delivery')} interruption"

    def _severity(self, domain: str, continuity: dict[str, Any]) -> str:
        if int(continuity.get("dropped") or 0) > 0:
            return "critical"
        if domain in ("gateway", "uplink"):
            return "critical"
        return "warning"

    # ── KPI plumbing ─────────────────────────────────────────────────────
    def _counters(self) -> dict[str, int]:
        """Cumulative counters an incident's KPIs are measured against."""
        out = {"replayed": 0, "dropped": 0, "uplink_switches": 0, "forwarding_failures": 0}
        if self.forwarding is not None:
            try:
                stats = self.forwarding.buffer_stats()
                out["replayed"] = int(stats.get("total_replayed") or 0)
                out["dropped"] = int(stats.get("total_dropped") or 0)
            except Exception:
                pass
            try:
                # Counts every failed publish cycle, including the retries that
                # are deliberately not written to the event log.
                out["forwarding_failures"] = sum(
                    int((state or {}).get("failed_count") or 0)
                    for state in (getattr(self.forwarding, "_states", {}) or {}).values()
                )
            except Exception:
                pass
        state = self._network_state() or {}
        try:
            out["uplink_switches"] = int((state.get("uplink_stats") or {}).get("switch_count") or 0)
        except Exception:
            pass
        return out

    def _received_during(self, started_ms: int, ended_ms: int) -> int:
        """Messages that actually reached the gateway across the incident.

        This is the countable half of the picture: whatever a source failed to
        send never appears here, which is exactly why completeness cannot be
        claimed from it alone.
        """
        if self.interfaces_storage is None or not started_ms:
            return 0
        try:
            rows = self.interfaces_storage.sensor_messages(
                from_ms=int(started_ms), to_ms=int(ended_ms), limit=10000,
            )
            return len(rows)
        except Exception:
            return 0

    def _kpi_for(
        self, incident: dict[str, Any], counters: dict[str, int],
        continuity: dict[str, Any], source_gap: bool, now_ms: int,
    ) -> dict[str, Any]:
        stored = incident.get("kpi") or {}
        baseline = stored.get("baseline") or kpi_mod.baseline_from(counters)
        started = int(incident.get("started_ms") or 0)
        ended = int(incident.get("restored_ms") or 0) or now_ms
        record = kpi_mod.compute(
            incident=incident,
            baseline=baseline,
            counters=counters,
            received_during=self._received_during(started, ended),
            buffered_peak=int(continuity.get("buffered_peak") or continuity.get("pending") or 0),
            pending=int(continuity.get("pending") or 0),
            source_gap=source_gap,
            now_ms=now_ms,
        )
        if incident.get("scope_kind") == "source":
            record = kpi_mod.for_source_outage(record)
        return record

    def _write_kpi(
        self, incident: dict[str, Any], counters: dict[str, int],
        continuity: dict[str, Any], source_gap: bool, now_ms: int,
    ) -> None:
        try:
            self.storage.update_incident(incident["id"], {
                "kpi_json": self._kpi_for(incident, counters, continuity, source_gap, now_ms),
            })
        except Exception as exc:
            LOGGER.error("incident_kpi_write_failed ref=%s error=%s", incident.get("ref"), exc)

    def _live_scopes(self) -> dict[str, set[str]]:
        """Scopes that still exist in configuration, per layer.

        Only layers listed here are subject to retirement; a layer that is
        absent is left alone, so an unlisted layer can never be retired by
        accident.
        """
        scopes: dict[str, set[str]] = {}
        if self.forwarding is not None:
            try:
                profiles = self.forwarding.config.get("profiles") or []
                scopes[DESTINATION_LAYER] = {
                    str(p.get("id")) for p in profiles if p.get("enabled", True)
                }
            except Exception:
                pass
        return scopes

    def _network_state(self) -> dict[str, Any] | None:
        if self.network_runtime is None:
            return None
        try:
            return self.network_runtime.state()
        except Exception:
            return None

    def _source_total(self) -> int:
        try:
            return len(self.interfaces_storage.sources()) if self.interfaces_storage else 0
        except Exception:
            return 0

    def _continuity(self) -> dict[str, Any]:
        if self.forwarding is None:
            return {"pending": 0, "replayed": 0, "dropped": 0}
        try:
            stats = self.forwarding.buffer_stats()
        except Exception:
            return {"pending": 0, "replayed": 0, "dropped": 0}
        return {
            "pending": int(stats.get("total_pending") or 0),
            "replayed": int(stats.get("total_replayed") or 0),
            "dropped": int(stats.get("total_dropped") or 0),
        }
