"""Turns an incident into a notification a person can act on without the console.

An email that says "something broke, click here" forces the reader onto the
site network or a VPN before they know whether it matters. Everything the
console would tell them goes in the message instead: what happened, what the
gateway checked and found, the likely cause (labelled as a conclusion, never
as an observation), the timeline, what it means for the data, and what to do.

The wording comes from gateway_incidents.wording and .report, the same text
the console and the incident report use, so the three can never disagree.
"""

from __future__ import annotations

from typing import Any

from gateway_incidents import DOMAIN_LABELS
from gateway_incidents import report as incident_report
from gateway_incidents import wording


# What the reader should do while an incident is active, by failure domain.
ACTION_OPEN = {
    "destination": (
        "Check that {destination} is running and accepting connections from the gateway. "
        "Data keeps arriving and is held in the gateway buffer, so nothing is lost while the "
        "buffer has room; it is sent automatically once the server is reachable again."
    ),
    "source": (
        "Check the device's power, cabling and network link, and that its address and "
        "protocol settings still match the gateway configuration. No readings are taken "
        "from it until it answers again."
    ),
    "uplink": (
        "Check the gateway's internet connection (cable, router or SIM). Data is held in "
        "the gateway buffer and sent automatically when the connection returns."
    ),
    "local_network": "Check the gateway's local network connection (cable, switch or Wi-Fi).",
    "gateway": (
        "Check the gateway's health on the Monitor page: CPU, memory, storage and temperature."
    ),
    "unknown": (
        "The evidence does not single out one layer. Review the checks below, starting "
        "with any marked failed."
    ),
}

_CHECK_RESULT = {"ok": "OK", "failed": "Failed", "unknown": "Not checked"}


def incident_details(incident: dict[str, Any], *, opened: bool) -> dict[str, Any]:
    """The full, structured explanation of one incident at this transition."""
    view = dict(incident)
    view["timeline"] = wording.timeline_rows(incident)
    view["evidence"] = wording.evidence_rows(incident)
    kpi = incident.get("kpi") or {}
    affected = incident.get("affected") or []
    sources = [str(a.get("name")) for a in affected if a.get("kind") == "source"]
    destinations = [str(a.get("name")) for a in affected if a.get("kind") == "destination"]
    status = str(incident.get("status") or "")
    domain = str(incident.get("domain") or "unknown")

    summary = incident_report.summary_prose(
        incident, kpi, sources, destinations,
        still_open="The problem is still active as of this message.",
    )

    return {
        "status": status,
        "status_label": wording.status_label(status),
        "status_explain": wording.STATUS_EXPLAIN.get(status, ""),
        "headline": "Problem detected" if opened else "Resolved",
        "summary": summary,
        "affected": {"sources": sources, "destinations": destinations},
        "cause": {
            "domain": domain_label(incident),
            "confidence": incident.get("domain_conf"),
            "basis": _basis(view["evidence"]),
            "note": (
                "This is the gateway's conclusion from the checks below, not a direct "
                "observation of the remote system."
            ),
        },
        "checks": [
            {
                "check": row.get("check"),
                "result": _CHECK_RESULT.get(str(row.get("state")), str(row.get("state") or "")),
                "state": row.get("state"),
                "finding": row.get("finding"),
            }
            for row in view["evidence"]
        ],
        "timeline": [
            {"at": wording.local_clock(row.get("ts_ms")), "event": row.get("label"), "detail": row.get("hint")}
            for row in view["timeline"]
        ],
        "facts": _facts(incident, kpi),
        "data": _data_rows(kpi, opened=opened),
        "data_note": kpi.get("completeness_note") or "",
        "action": _action(incident, kpi, destinations, domain, opened=opened),
    }


def domain_label(incident: dict[str, Any]) -> str:
    """The failure domain's display name; storage keeps only its key."""
    domain = str(incident.get("domain") or "unknown")
    return str(incident.get("domain_label") or DOMAIN_LABELS.get(domain, domain))


def _basis(evidence: list[dict[str, Any]]) -> str:
    def names(state: str) -> str:
        return incident_report._join([e.get("check") for e in evidence if e.get("state") == state])

    bits = []
    if failed := names("failed"):
        bits.append(f"{failed} failed")
    if healthy := names("ok"):
        bits.append(f"{healthy} checked healthy")
    if unknown := names("unknown"):
        bits.append(f"{unknown} could not be checked")
    return "; ".join(bits) or "no checks were recorded"


def _facts(incident: dict[str, Any], kpi: dict[str, Any]) -> list[tuple[str, str]]:
    facts = [
        ("Incident", str(incident.get("ref") or "")),
        ("Status", wording.status_label(incident.get("status"))),
        ("Problem began", wording.local_clock(incident.get("started_ms"))),
    ]
    if incident.get("restored_ms"):
        facts.append(("Service came back", wording.local_clock(incident.get("restored_ms"))))
    if incident.get("closed_ms"):
        facts.append(("Incident closed", wording.local_clock(incident.get("closed_ms"))))
    blind = kpi.get("blind_time_ms")
    if blind is not None:
        facts.append(("Interruption lasted" if incident.get("restored_ms") else "Running for",
                      incident_report._duration(blind) or "—"))
    latency = kpi.get("detection_latency_ms")
    if latency is not None:
        facts.append(("Detected after", incident_report._duration(latency) or "—"))
    return facts


def _data_rows(kpi: dict[str, Any], *, opened: bool) -> list[tuple[str, str]]:
    """What the incident meant for the data — only figures the counters support."""
    if kpi.get("source_outage"):
        return [("Readings during the outage", "Not taken: the device was not answering")]
    if not kpi:
        return []
    rows: list[tuple[str, str]] = []
    if kpi.get("received_during") is not None:
        rows.append(("Records that reached the gateway since it began", f"{int(kpi['received_during']):,}"))
    if kpi.get("replayed") is not None:
        rows.append(("Delivered from the buffer" if not opened else "Delivered from the buffer so far",
                     f"{int(kpi['replayed']):,}"))
    if kpi.get("pending") is not None:
        # The live queue, which can include a few records from just before the
        # incident began — hence "now", not "from this incident".
        rows.append(("Waiting in the buffer now", f"{int(kpi['pending']):,}"))
    if kpi.get("evicted"):
        rows.append(("Dropped because the buffer was full", f"{int(kpi['evicted']):,}"))
    # Mid-outage a recovery percentage only measures how far replay has got,
    # and "0% recovered" reads as loss; it is stated once the incident closes.
    if opened:
        return rows
    if kpi.get("recovery_pct") is not None:
        rows.append(("Recovered", f"{kpi['recovery_pct']}% ({kpi.get('recovery_basis')})"))
    elif kpi.get("recovery_basis"):
        rows.append(("Recovered", str(kpi["recovery_basis"])))
    return rows


def _action(
    incident: dict[str, Any], kpi: dict[str, Any], destinations: list[str],
    domain: str, *, opened: bool,
) -> str:
    if opened:
        template = ACTION_OPEN.get(domain, ACTION_OPEN["unknown"])
        return template.format(destination=incident_report._join(destinations) or "the destination server")
    text = "No action needed. Service recovered and stayed healthy for 5 minutes, so the incident is closed."
    outstanding = int(kpi.get("pending") or 0)
    if outstanding and not kpi.get("source_outage"):
        text += (
            f" {outstanding:,} records were still in the buffer at closing; the gateway keeps "
            "retrying them automatically."
        )
    return text


__all__ = ["domain_label", "incident_details"]
