"""How incidents are described to people.

One copy of the wording, used by the console and by notifications alike, so an
email can never describe an incident differently from the dashboard.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


# The three states as an operator should read them. "recovering" is a real
# lifecycle state, but the word suggests the fault is still being worked; what
# it actually means is that service is back and the incident is waiting to see
# that it stays back.
STATUS_LABELS = {
    "open": "Active",
    "recovering": "Restored",
    "resolved": "Closed",
}

STATUS_EXPLAIN = {
    "open": "The problem is happening now.",
    "recovering": (
        "Service is working again. The incident closes automatically once it has "
        "stayed healthy for 5 minutes, so a brief relapse is caught as the same "
        "incident rather than a new one."
    ),
    "resolved": "Service recovered and stayed healthy. Nothing further is needed.",
}

# Timeline wording lives here, not in the database, so improving it also fixes
# incidents recorded earlier. "Began" and "raised" are different moments, so
# each step carries a plain-English explanation.
TIMELINE_TEXT = {
    "started": (
        "Problem began",
        "The earliest failure the gateway has on record for this incident.",
    ),
    "detected": (
        "Gateway raised the incident",
        "When the gateway connected the separate signals together and opened this "
        "incident. Normally seconds after it began; longer if the gateway was "
        "restarting and replayed earlier history.",
    ),
    "restored": (
        "Service came back",
        "Working again. The incident stays open 5 more minutes to be sure it holds.",
    ),
    "revised": (
        "Likely cause revised",
        "New evidence changed the gateway's conclusion about the likely cause.",
    ),
    "closed_stable": (
        "Incident closed",
        "Stayed healthy for 5 minutes after recovering, so the incident was closed.",
    ),
    "closed_retired": (
        "Incident closed",
        "The failing item was removed from the configuration, so there is nothing "
        "left to recover.",
    ),
}

# Labels written by older builds, mapped onto the same kinds so the clearer
# wording applies to them too.
TIMELINE_LEGACY = {
    "Problem started": "started",
    "First failure recorded": "started",
    "Detected by gateway": "detected",
    "Gateway correlated and raised this incident": "detected",
    "Service restored — confirming stability": "restored",
    "Service restored — watching for stability": "restored",
    "Service restored": "restored",
    "Closed after stable recovery": "closed_stable",
    "Closed — stayed healthy after recovery": "closed_stable",
    "Closed — no longer configured": "closed_retired",
}

# Which evidence rows belong on which incident: only the chain that informed
# its own diagnosis. A forwarding incident listing "Source polling: failed"
# read as a contradiction of its own verdict.
EVIDENCE_LAYERS = {
    "source": ("source", "gateway", "local_network"),
    "path": ("gateway", "local_network", "uplink", "destination"),
}


def local_clock(ms: Any) -> str:
    """A timestamp in the gateway's own time zone, with the zone named.

    Readers act on the site's clock, so text sent to people uses it; the zone
    name keeps it unambiguous when forwarded elsewhere.
    """
    if not ms:
        return "an unrecorded time"
    return datetime.fromtimestamp(int(ms) / 1000).astimezone().strftime("%d %b %Y, %H:%M:%S %Z")


# Where an incident comes from, as the first word of its title, so a reader
# knows which part of the system it concerns before reading further.
ORIGIN_LABELS = {
    "sensors": "Sensor",
    "forwarding": "Data Forwarding",
    "edge": "Edge Server",
    "network": "Network",
    "gateway": "Gateway",
}


def incident_title(incident: dict[str, Any]) -> str:
    """"<Origin>: <named subject> <what happened>", built from the incident's
    own fields every time it is shown.

    Built rather than stored, so the wording applies to incidents recorded
    earlier too, and the console, emails and reports always agree. Subjects
    use the names the customer configured, and a delivery problem names the
    server(s) that failed rather than counting the sources behind it.
    """
    from .correlator import incident_home  # the correlator imports this module

    origin = ORIGIN_LABELS.get(incident_home(incident), "Gateway")
    affected = incident.get("affected") or []
    names = lambda kind: [str(a.get("name")) for a in affected if a.get("kind") == kind and a.get("name")]
    scope_kind = str(incident.get("scope_kind") or "")
    scope_key = str(incident.get("scope_key") or "")
    domain = str(incident.get("domain") or "unknown")

    if scope_kind == "source":
        # Titled by where the problem showed up, whatever its likely cause:
        # the cause has its own label next to the title.
        edge = scope_key.startswith("edgeServer:")
        subject = (names("source") or [scope_key.split(":", 1)[-1]])[0]
        return (f"Edge Server: {subject} stopped sending data" if edge
                else f"Sensor: {subject} stopped reporting")
    if domain == "gateway":
        return f"{origin}: health degraded"
    if domain == "uplink":
        return f"{origin}: internet uplink lost"
    if domain == "local_network":
        ifaces = names("local_network")
        return f"{origin}: local network interface {_join(ifaces)} down" if ifaces else f"{origin}: local network interrupted"
    servers = names("destination")
    if domain == "destination" and servers:
        verb = "is" if len(servers) == 1 else "are"
        return f"{origin}: {_join(servers)} {verb} not accepting data"
    return f"{origin}: data delivery interrupted"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def _domain_name(domain: Any) -> str:
    # Imported here: the correlator imports this module.
    from .correlator import DOMAIN_LABELS
    return DOMAIN_LABELS.get(str(domain or "unknown"), str(domain or "Unknown"))


def status_label(status: Any) -> str:
    return STATUS_LABELS.get(str(status or ""), str(status or ""))


def timeline_rows(incident: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in incident.get("timeline") or []:
        stored_label = str(entry.get("label") or "")
        kind = str(entry.get("kind") or "") or TIMELINE_LEGACY.get(stored_label, "")
        label, hint = TIMELINE_TEXT.get(kind, (stored_label, ""))
        if kind == "revised":
            label = f"{label}: {_domain_name(entry.get('from'))} → {_domain_name(entry.get('to'))}"
        rows.append({"ts_ms": entry.get("ts_ms"), "kind": kind, "label": label, "hint": hint})
    return rows


def evidence_rows(incident: dict[str, Any]) -> list[dict[str, Any]]:
    keep = EVIDENCE_LAYERS.get(str(incident.get("scope_kind") or "path"), ())
    return [row for row in incident.get("evidence") or [] if row.get("layer") in keep]
