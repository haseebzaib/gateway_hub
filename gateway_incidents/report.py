"""Customer-facing incident reports.

The audience is someone who was not watching the gateway and will not read a
log. The report has to say what happened, what the gateway observed, and what
recovered — in prose, from the same values the dashboard shows.

The separation this module is built around: **measured** facts come from
timestamps and counters and are stated flatly. The **likely failure domain** is
a conclusion drawn from those facts, and is always presented as an inference
with its supporting evidence attached. Blurring the two would let a plausible
guess be read as a measurement, which is exactly what a pilot report cannot do.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import wording


BRANDING_PATH = Path(
    os.environ.get("METACRUST_REPORT_BRANDING_PATH", "/opt/metacrust/config/reports/branding.json")
)

DOMAIN_PHRASE = {
    "destination": "the destination/server path rather than the source device",
    "source": "the source device rather than the gateway or the network beyond it",
    "gateway": "the gateway itself rather than the devices or the network",
    "local_network": "the local network rather than the source device or the destination",
    "uplink": "the internet uplink rather than the source device or the destination server",
    "unknown": "no single layer — the available evidence does not identify one",
}


def load_branding() -> dict[str, Any]:
    """Company/site identifiers for the report header.

    Identifiers are opt-in: a report generated without configuring them simply
    omits the header block rather than inventing a customer name.
    """
    defaults = {"company": "", "site": "", "include_identifiers": True}
    try:
        raw = json.loads(BRANDING_PATH.read_text())
    except (OSError, ValueError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    return {
        "company": str(raw.get("company") or ""),
        "site": str(raw.get("site") or ""),
        "include_identifiers": bool(raw.get("include_identifiers", True)),
    }


def save_branding(payload: dict[str, Any]) -> dict[str, Any]:
    branding = {
        "company": str(payload.get("company") or "")[:120],
        "site": str(payload.get("site") or "")[:120],
        "include_identifiers": bool(payload.get("include_identifiers", True)),
    }
    BRANDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    BRANDING_PATH.write_text(json.dumps(branding, indent=2))
    return branding


def build(
    incident: dict[str, Any],
    raw_events: list[dict[str, Any]],
    *,
    branding: dict[str, Any] | None = None,
    include_identifiers: bool | None = None,
) -> dict[str, Any]:
    """Assemble the full report for one incident."""
    brand = branding if branding is not None else load_branding()
    show_ids = brand.get("include_identifiers", True) if include_identifiers is None else include_identifiers

    kpi = incident.get("kpi") or {}
    evidence = incident.get("evidence") or []
    sources = [a.get("name") for a in incident.get("affected") or [] if a.get("kind") == "source"]
    destinations = [a.get("name") for a in incident.get("affected") or [] if a.get("kind") == "destination"]

    return {
        "reference": incident.get("ref"),
        "generated_at": _iso(_now_ms()),
        "identifiers": (
            {"company": brand.get("company", ""), "site": brand.get("site", "")}
            if show_ids and (brand.get("company") or brand.get("site")) else None
        ),
        "status": incident.get("status"),
        "status_label": wording.status_label(incident.get("status")),
        "title": incident.get("title"),
        "started_at": _iso(incident.get("started_ms")),
        "detected_at": _iso(incident.get("detected_ms")),
        "restored_at": _iso(incident.get("restored_ms")),
        "duration": _duration(incident.get("duration_ms")),
        "affected": {"sources": sources, "destinations": destinations},
        "summary": summary_prose(incident, kpi, sources, destinations),
        "timeline": [
            {"at": _iso(entry.get("ts_ms")), "event": entry.get("label"), "detail": entry.get("hint", "")}
            for entry in incident.get("timeline") or []
        ],
        "continuity": _continuity_section(kpi),
        "connectivity": _connectivity_section(evidence, kpi),
        "diagnosis": {
            # Explicitly an inference, never presented as an observation.
            "likely_failure_domain": incident.get("domain_label"),
            "confidence": incident.get("domain_conf"),
            "basis": _diagnosis_basis(incident, evidence),
            "evidence": [
                {"check": e.get("check"), "result": e.get("state"), "finding": e.get("finding")}
                for e in evidence
            ],
        },
        "related_events": [
            {"at": _iso(e.get("timestamp_ms")), "device": e.get("device_name") or e.get("device_id"),
             "detail": e.get("message")}
            for e in raw_events[:50]
        ],
        "measurement_statement": measurement_statement(incident, kpi),
    }


def summary_prose(
    incident: dict[str, Any], kpi: dict[str, Any],
    sources: list[str], destinations: list[str],
    *, still_open: str = "The condition had not cleared when this report was produced.",
) -> str:
    """The paragraph a non-technical reader gets, assembled from facts.

    `still_open` is the sentence for an incident that has not cleared; a live
    notification says "is still active" rather than speaking of a report.
    """
    domain = str(incident.get("domain") or "unknown")
    who = _join(sources) if sources else "device"
    started = _clock(incident.get("started_ms"))
    parts: list[str] = []

    if domain == "destination":
        target = _join(destinations) or "the configured destination"
        parts.append(
            f"MetaCrust detected that {who} data could no longer be delivered to {target} "
            f"at {started}."
        )
        parts.append("The gateway and source remained operational, so incoming records were stored locally.")
    elif domain == "source":
        parts.append(f"MetaCrust detected that {who} stopped reporting at {started}.")
        parts.append(
            "The gateway, the local network and the onward connection all remained operational, "
            "so the interruption was confined to the device itself."
        )
    elif domain == "uplink":
        parts.append(f"MetaCrust detected that the internet uplink became unavailable at {started}.")
        parts.append("The gateway and its sources continued running, so records were stored locally.")
    elif domain == "local_network":
        parts.append(f"MetaCrust detected a local network interruption at {started}.")
        parts.append("The gateway itself continued running throughout.")
    elif domain == "gateway":
        parts.append(f"MetaCrust recorded that the gateway itself became degraded at {started}.")
    else:
        parts.append(f"MetaCrust recorded a data continuity interruption at {started}.")

    restored = incident.get("restored_ms")
    if restored:
        parts.append(f"Normal operation resumed at {_clock(restored)}.")
    else:
        parts.append(still_open)

    parts.append(_replay_sentence(kpi))

    phrase = DOMAIN_PHRASE.get(domain, DOMAIN_PHRASE["unknown"])
    if domain == "unknown":
        parts.append(f"Evidence collected during the interruption points to {phrase}.")
    else:
        parts.append(f"Evidence therefore points to {phrase} as the likely failure domain.")
    return " ".join(parts)


def _replay_sentence(kpi: dict[str, Any]) -> str:
    """What recovered — stated only as far as the counters actually support."""
    if kpi.get("source_outage"):
        return (
            "A device that stops reporting sends nothing for the gateway to buffer, so "
            "readings for the outage period were never taken and cannot be recovered."
        )
    replayed = kpi.get("replayed")
    pending = kpi.get("pending")
    evicted = kpi.get("evicted")
    if replayed is None:
        return (
            "Buffer and replay volumes were not recorded for this incident, so the quantity "
            "of data involved cannot be stated."
        )
    outstanding = (pending or 0) + (evicted or 0)
    if replayed and not outstanding:
        return (
            f"All {replayed:,} records that entered the gateway buffer were subsequently replayed."
        )
    if replayed and outstanding:
        return (
            f"{replayed:,} records that entered the gateway buffer were replayed; "
            f"{outstanding:,} had not been delivered when this report was produced."
        )
    if outstanding:
        return f"{outstanding:,} records remained in the gateway buffer awaiting delivery."
    return "No records entered the gateway buffer during this interruption."


def measurement_statement(incident: dict[str, Any], kpi: dict[str, Any]) -> dict[str, Any]:
    """Separate what was measured from what was concluded.

    Required so a reader cannot mistake the failure domain — a judgement drawn
    from evidence — for something the gateway directly observed.
    """
    measured = [
        "Incident start, detection and restoration times.",
        "Which connectivity checks passed or failed during the interruption.",
    ]
    if kpi.get("source_outage"):
        measured.append(
            "Buffer and replay volumes do not apply: a stopped source sends nothing to buffer."
        )
    elif kpi.get("replayed") is not None:
        measured.append("Records buffered, replayed and left outstanding, taken from gateway counters.")
    else:
        measured.append("Buffer and replay volumes were not recorded for this incident.")
    if kpi.get("uplink_switches") is not None:
        measured.append("Uplink switches and forwarding retries counted during the interruption.")

    inferred = [
        f"The likely failure domain ({incident.get('domain_label')}) is a conclusion drawn from the "
        f"evidence listed above, at {incident.get('domain_conf')} confidence. It is not a direct "
        f"observation of the remote system."
    ]

    completeness = kpi.get("completeness")
    if completeness == "unverifiable":
        caveat = (
            kpi.get("completeness_note")
            or "Total data completeness cannot be verified for this incident."
        )
    else:
        caveat = (
            "Sources continued delivering throughout, so the records above account for all data "
            "in this period."
        )
    return {"measured": measured, "inferred": inferred, "completeness": caveat}


def _diagnosis_basis(incident: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    failed = [e.get("check") for e in evidence if e.get("state") == "failed"]
    healthy = [e.get("check") for e in evidence if e.get("state") == "ok"]
    unknown = [e.get("check") for e in evidence if e.get("state") == "unknown"]
    bits = []
    if failed:
        bits.append(f"{_join(failed)} failed")
    if healthy:
        bits.append(f"{_join(healthy)} verified healthy")
    if unknown:
        bits.append(f"{_join(unknown)} could not be checked")
    return "; ".join(bits) or "no checks were recorded"


def _continuity_section(kpi: dict[str, Any]) -> dict[str, Any]:
    return {
        "blind_time": _duration(kpi.get("blind_time_ms")),
        "detection_latency": _duration(kpi.get("detection_latency_ms")),
        "records_reaching_gateway": kpi.get("received_during"),
        "buffered": kpi.get("buffered_peak"),
        "replayed": kpi.get("replayed"),
        "outstanding": None if kpi.get("pending") is None and kpi.get("evicted") is None
                       else (kpi.get("pending") or 0) + (kpi.get("evicted") or 0),
        "recovery_percent": kpi.get("recovery_pct"),
        "recovery_basis": kpi.get("recovery_basis"),
        "completeness": kpi.get("completeness"),
    }


def _connectivity_section(evidence: list[dict[str, Any]], kpi: dict[str, Any]) -> dict[str, Any]:
    by_layer = {e.get("layer"): e for e in evidence}
    def finding(layer: str) -> str | None:
        row = by_layer.get(layer)
        return f"{row.get('state')} — {row.get('finding')}" if row else None
    return {
        "uplink": finding("uplink"),
        "local_network": finding("local_network"),
        "gateway": finding("gateway"),
        "uplink_switches": kpi.get("uplink_switches"),
        "forwarding_retries": kpi.get("forwarding_failures"),
    }


# ── formatting ───────────────────────────────────────────────────────────

def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _iso(ms: Any) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clock(ms: Any) -> str:
    return wording.local_clock(ms)


def _duration(ms: Any) -> str | None:
    if ms is None:
        return None
    seconds = max(0, int(ms) // 1000)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {mins}m"
    days, hrs = divmod(hours, 24)
    return f"{days}d {hrs}h"


def _join(items: list[Any]) -> str:
    names = [str(i) for i in items if i]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"
