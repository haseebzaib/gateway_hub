"""Per-incident continuity KPIs.

These are the numbers a pilot report is written from, so they are computed
from counters rather than estimated, and every ratio names its denominator.

The distinction that shapes everything here: data that *reached the gateway*
is countable — it entered the buffer, so we know exactly how much was replayed
and how much was not. Data that *never reached the gateway* is not countable at
all. When a sensor stops answering, those readings were never taken; nothing
buffered them and nothing can recover them. Reporting "100% recovered" in that
situation would be measuring only the records we happened to receive and
calling it completeness.

So recovery is always expressed against records that entered the gateway
buffer, and an incident where a source went silent is marked as having
unverifiable completeness no matter how well the buffer performed.
"""

from __future__ import annotations

from typing import Any


VERIFIED = "verified"
UNVERIFIABLE = "unverifiable"


def baseline_from(counters: dict[str, int]) -> dict[str, int]:
    """Freeze the cumulative counters an incident will be measured against."""
    return {
        "replayed": int(counters.get("replayed") or 0),
        "dropped": int(counters.get("dropped") or 0),
        "uplink_switches": int(counters.get("uplink_switches") or 0),
        "forwarding_failures": int(counters.get("forwarding_failures") or 0),
    }


def compute(
    *,
    incident: dict[str, Any],
    baseline: dict[str, int],
    counters: dict[str, int],
    received_during: int,
    buffered_peak: int,
    pending: int,
    source_gap: bool,
    now_ms: int,
) -> dict[str, Any]:
    """Build the KPI record for one incident.

    `counters` are the current cumulative values; deltas against `baseline` give
    the activity attributable to this incident rather than to the lifetime of
    the gateway.
    """
    started = int(incident.get("started_ms") or 0)
    detected = int(incident.get("detected_ms") or 0)
    restored = incident.get("restored_ms")
    ended = int(restored or 0) or now_ms

    replayed = _delta(counters.get("replayed"), baseline.get("replayed"))
    evicted = _delta(counters.get("dropped"), baseline.get("dropped"))
    switches = _delta(counters.get("uplink_switches"), baseline.get("uplink_switches"))
    failures = _delta(counters.get("forwarding_failures"), baseline.get("forwarding_failures"))

    # Everything known to have entered the gateway buffer during this incident.
    # This is the only honest denominator for a recovery percentage: it counts
    # what we actually hold, never what a source failed to send.
    accounted = replayed + max(0, int(pending)) + evicted
    if accounted > 0:
        recovery_pct = round(100.0 * replayed / accounted, 1)
        basis = (
            f"{replayed:,} of {accounted:,} records that entered the gateway buffer "
            f"during this incident"
        )
    else:
        recovery_pct = None
        basis = "No records entered the gateway buffer during this incident"

    if source_gap:
        completeness = UNVERIFIABLE
        note = (
            "A source stopped reporting during this incident, so readings for that "
            "period were never taken and never reached the gateway. They cannot be "
            "recovered or counted, and the recovery figure above covers only records "
            "the gateway actually holds — not total data completeness."
        )
    else:
        completeness = VERIFIED
        note = (
            "Sources kept delivering throughout, so every record for this period "
            "reached the gateway and is accounted for above."
        )

    return {
        "detection_latency_ms": max(0, detected - started) if started and detected else None,
        "blind_time_ms": max(0, ended - started) if started else None,
        "received_during": max(0, int(received_during)),
        "buffered_peak": max(0, int(buffered_peak)),
        "replayed": replayed,
        "pending": max(0, int(pending)),
        "evicted": evicted,
        "uplink_switches": switches,
        "forwarding_failures": failures,
        "recovery_pct": recovery_pct,
        "recovery_basis": basis,
        "accounted": accounted,
        "completeness": completeness,
        "completeness_note": note,
        "baseline": baseline,
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll several incidents' KPIs into one pilot summary.

    Sums are over incidents, and each incident contributes its own counters
    exactly once, so replaying the same window twice cannot inflate the totals.
    Completeness is deliberately pessimistic: one incident with an unverifiable
    gap makes the whole summary unverifiable, because a total recovery figure
    would otherwise imply a completeness the data cannot support.
    """
    kpis = [r.get("kpi") or {} for r in records if r.get("kpi")]
    total_replayed = sum(int(k.get("replayed") or 0) for k in kpis)
    total_pending = sum(int(k.get("pending") or 0) for k in kpis)
    total_evicted = sum(int(k.get("evicted") or 0) for k in kpis)
    accounted = total_replayed + total_pending + total_evicted
    unverifiable = [k for k in kpis if k.get("completeness") == UNVERIFIABLE]

    blind_times = [int(k["blind_time_ms"]) for k in kpis if k.get("blind_time_ms")]
    latencies = [int(k["detection_latency_ms"]) for k in kpis if k.get("detection_latency_ms") is not None]

    return {
        "incidents": len(records),
        "resolved": sum(1 for r in records if r.get("status") == "resolved"),
        "ongoing": sum(1 for r in records if r.get("status") != "resolved"),
        "total_blind_time_ms": sum(blind_times),
        "longest_blind_time_ms": max(blind_times) if blind_times else 0,
        "median_detection_latency_ms": _median(latencies),
        "received_during": sum(int(k.get("received_during") or 0) for k in kpis),
        "buffered_peak": max([int(k.get("buffered_peak") or 0) for k in kpis] or [0]),
        "replayed": total_replayed,
        "pending": total_pending,
        "evicted": total_evicted,
        "accounted": accounted,
        "uplink_switches": sum(int(k.get("uplink_switches") or 0) for k in kpis),
        "forwarding_failures": sum(int(k.get("forwarding_failures") or 0) for k in kpis),
        "recovery_pct": round(100.0 * total_replayed / accounted, 1) if accounted else None,
        "recovery_basis": (
            f"{total_replayed:,} of {accounted:,} records that entered the gateway buffer"
            if accounted else "No records entered the gateway buffer in this period"
        ),
        "completeness": UNVERIFIABLE if unverifiable else VERIFIED,
        "completeness_note": (
            f"{len(unverifiable)} of {len(kpis)} incidents involved a source that stopped "
            "reporting, so total data completeness cannot be verified for this period. "
            "The recovery figure covers only records the gateway received."
            if unverifiable else
            "Every incident in this period kept its sources delivering, so the records "
            "above account for all data in the period."
        ),
    }


def _delta(current: Any, base: Any) -> int:
    """Counter difference, floored at zero.

    Some sources reset on restart (in-memory failure counts), which would
    otherwise produce a negative and a nonsensical KPI.
    """
    return max(0, int(current or 0) - int(base or 0))


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2
