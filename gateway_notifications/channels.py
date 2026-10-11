"""Delivery to each supported destination.

Every function here is blocking and is called from a worker thread — never from
the event loop, which serves IPC, the console and forwarding.

Each webhook flavour builds the body its provider actually expects, so an
operator pastes the URL their provider gave them and it works. A generic
receiver gets the whole notification as JSON, which is what integration tools
(n8n, Zapier, Make, custom endpoints) want.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any


TIMEOUT_S = 15.0
PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"
USER_AGENT = "MetaCrust-Gateway/1.0"

_SEVERITY_COLOUR = {"critical": "#d93025", "warning": "#f0a64b", "info": "#39d0c8"}
_PAGERDUTY_SEVERITY = {"critical": "critical", "warning": "warning", "info": "info"}


def deliver(channel: dict[str, Any], note: dict[str, Any]) -> None:
    """Send one notification. Raises on failure so the caller can retry."""
    kind = channel.get("type")
    if kind == "email":
        _send_email(channel, note)
        return
    url = str(channel.get("url") or "").strip()
    if kind == "pagerduty":
        url = url or PAGERDUTY_EVENTS_URL
        if not str(channel.get("routing_key") or channel.get("secret") or "").strip():
            raise ValueError("PagerDuty needs an integration (routing) key")
    if not url:
        raise ValueError("channel has no URL configured")
    body = build_body(kind, note, channel)
    _post(url, body, channel)


def build_body(kind: str, note: dict[str, Any], channel: dict[str, Any] | None = None) -> dict[str, Any]:
    """The provider-shaped payload for a notification."""
    if kind == "slack":
        return _slack_body(note)
    if kind == "teams":
        return _teams_body(note)
    if kind == "discord":
        return _discord_body(note)
    if kind == "pagerduty":
        return _pagerduty_body(note, channel or {})
    return _generic_body(note)


# ── payload shapes ───────────────────────────────────────────────────────

def _generic_body(note: dict[str, Any]) -> dict[str, Any]:
    """Everything we know, unopinionated, for custom receivers."""
    return {
        "source": "metacrust-gateway",
        "gateway_id": note.get("gateway_id"),
        "event": note.get("event"),
        "severity": note.get("severity"),
        "incident_ref": note.get("incident_ref"),
        "title": note.get("title"),
        "message": note.get("message"),
        "failure_domain": note.get("failure_domain"),
        "started_at": note.get("started_at"),
        "resolved_at": note.get("resolved_at"),
        "buffered_records": note.get("buffered_records"),
        "affected": note.get("affected") or [],
        "status": note.get("status"),
        "status_label": note.get("status_label"),
        "details": note.get("details"),
        "dashboard_url": note.get("dashboard_url"),
        "links": note.get("links") or [],
        "timestamp": note.get("timestamp"),
    }


def _slack_body(note: dict[str, Any]) -> dict[str, Any]:
    ref = note.get("incident_ref") or ""
    fields = [f"*{k}*\n{v}" for k, v in _facts(note)]
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": _subject(note)[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": note.get("message") or ""}},
    ]
    if fields:
        blocks.append({"type": "section", "fields": [
            {"type": "mrkdwn", "text": f[:2000]} for f in fields[:10]
        ]})
    if note.get("dashboard_url"):
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"<{note['dashboard_url']}|Open {ref} in the gateway console>"},
        ]})
    return {"text": _subject(note), "blocks": blocks}


def _teams_body(note: dict[str, Any]) -> dict[str, Any]:
    card: dict[str, Any] = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": _subject(note),
        "themeColor": _SEVERITY_COLOUR.get(str(note.get("severity")), "#39d0c8").lstrip("#"),
        "title": _subject(note),
        "text": note.get("message") or "",
        "sections": [{"facts": [{"name": k, "value": str(v)} for k, v in _facts(note)]}],
    }
    if note.get("dashboard_url"):
        card["potentialAction"] = [{
            "@type": "OpenUri",
            "name": "Open in gateway console",
            "targets": [{"os": "default", "uri": note["dashboard_url"]}],
        }]
    return card


def _discord_body(note: dict[str, Any]) -> dict[str, Any]:
    colour = int(_SEVERITY_COLOUR.get(str(note.get("severity")), "#39d0c8").lstrip("#"), 16)
    embed: dict[str, Any] = {
        "title": _subject(note)[:256],
        "description": (note.get("message") or "")[:4000],
        "color": colour,
        "fields": [{"name": k, "value": str(v)[:1024], "inline": True} for k, v in _facts(note)][:25],
    }
    if note.get("dashboard_url"):
        embed["url"] = note["dashboard_url"]
    return {"embeds": [embed]}


def _pagerduty_body(note: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
    """Events API v2. The incident reference is the dedup key, so PagerDuty
    groups our alerts exactly as the gateway groups them, and a recovery
    notification resolves the alert it opened rather than raising a new one."""
    resolved = note.get("event") == "recovery"
    return {
        # PagerDuty authenticates by integration key in the body, not by URL,
        # so it is stored per channel rather than carried on the notification.
        "routing_key": str(channel.get("routing_key") or channel.get("secret") or ""),
        "event_action": "resolve" if resolved else "trigger",
        "dedup_key": note.get("incident_ref") or note.get("event"),
        "payload": {
            "summary": _subject(note)[:1024],
            "severity": _PAGERDUTY_SEVERITY.get(str(note.get("severity")), "warning"),
            "source": note.get("gateway_id") or "metacrust-gateway",
            "component": note.get("failure_domain") or "",
            "custom_details": _generic_body(note),
        },
        "links": (
            [{"href": note["dashboard_url"], "text": "Open in gateway console"}]
            if note.get("dashboard_url") else []
        ),
    }


def _facts(note: dict[str, Any]) -> list[tuple[str, Any]]:
    facts: list[tuple[str, Any]] = []
    if note.get("incident_ref"):
        facts.append(("Incident", note["incident_ref"]))
    if note.get("failure_domain"):
        facts.append(("Likely failure domain", note["failure_domain"]))
    if note.get("started_at"):
        facts.append(("Started", note["started_at"]))
    if note.get("resolved_at"):
        facts.append(("Resolved", note["resolved_at"]))
    if note.get("buffered_records") is not None:
        facts.append(("Records waiting in buffer", f"{int(note['buffered_records']):,}"))
    affected = note.get("affected") or []
    if affected:
        facts.append(("Affected", ", ".join(str(a) for a in affected)))
    return facts


def _subject(note: dict[str, Any]) -> str:
    # Plain ASCII hyphen: an em dash forces RFC 2047 encoded-words in email
    # subjects, which some clients render raw as "=?utf-8?b?...?=".
    ref = note.get("incident_ref")
    title = note.get("title") or "Gateway notification"
    status = f"[{note['status_label']}] " if note.get("status_label") else ""
    return f"MetaCrust {status}Incident {ref} - {title}" if ref else f"MetaCrust - {title}"


# ── transport ────────────────────────────────────────────────────────────

def _post(url: str, body: dict[str, Any], channel: dict[str, Any]) -> None:
    import httpx  # lazy: optional on dev machines

    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    headers.update(channel.get("headers") or {})
    secret = str(channel.get("secret") or "")
    if secret:
        # Lets a generic receiver verify the request really came from us.
        headers["X-MetaCrust-Signature"] = "sha256=" + hmac.new(
            secret.encode("utf-8"), raw, hashlib.sha256
        ).hexdigest()

    response = httpx.post(url, content=raw, headers=headers, timeout=TIMEOUT_S)
    if response.status_code >= 400:
        raise RuntimeError(f"{response.status_code} {response.text[:200]}")


def _send_email(channel: dict[str, Any], note: dict[str, Any]) -> None:
    settings = channel.get("email") or {}
    host = str(settings.get("smtp_host") or "").strip()
    recipients = [a for a in (settings.get("to_addresses") or []) if a]
    if not host or not recipients:
        raise ValueError("email channel needs an SMTP host and at least one recipient")

    message = EmailMessage()
    message["Subject"] = _subject(note)
    message["From"] = settings.get("from_address") or settings.get("username") or "gateway@metacrust"
    message["To"] = ", ".join(recipients)
    message.set_content(email_text(note))
    message.add_alternative(email_html(note), subtype="html")

    # Encryption is chosen explicitly rather than inferred from the port, so
    # what the operator selected is what actually happens on the wire.
    security = str(settings.get("security") or "starttls")
    port = int(settings.get("smtp_port") or 587)

    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_S, context=ssl.create_default_context()) as smtp:
            _authenticate(smtp, settings)
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=TIMEOUT_S) as smtp:
        if security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        _authenticate(smtp, settings)
        smtp.send_message(message)


def _authenticate(smtp: smtplib.SMTP, settings: dict[str, Any]) -> None:
    username = str(settings.get("username") or "")
    password = str(settings.get("password") or "")
    if username and password:
        smtp.login(username, password)


# ── email body ───────────────────────────────────────────────────────────
# The email is meant to be read on its own: everything the console would show
# about the incident is in it, so the reader can judge and act without first
# reaching the gateway. The links come last, for those who want to dig in.

def email_text(note: dict[str, Any]) -> str:
    d = note.get("details")
    if not d:
        lines = [note.get("message") or ""]
        if facts := _facts(note):
            lines += ["", *[f"{k}: {v}" for k, v in facts]]
        lines += ["", *_text_links(note)]
        return "\n".join(lines)

    out = [f"{d['headline'].upper()}: {note.get('title')}", ""]
    out += [f"Status: {d['status_label']} - {d['status_explain']}", ""]
    out += _section("What happened", [d["summary"]])
    out += _section("What to do", [d["action"]])
    out += _section("Details", [f"{k}: {v}" for k, v in d["facts"]])
    affected = d["affected"]
    rows = []
    if affected["sources"]:
        rows.append("Sources: " + ", ".join(affected["sources"]))
    if affected["destinations"]:
        rows.append("Destinations: " + ", ".join(affected["destinations"]))
    out += _section("Affected", rows)
    cause = d["cause"]
    out += _section("Likely cause (inferred)", [
        f"{cause['domain']} - {cause['confidence']} confidence.",
        f"Basis: {cause['basis']}.",
        cause["note"],
    ])
    out += _section("What the gateway checked", [
        f"[{c['result']}] {c['check']}: {c['finding']}" for c in d["checks"]
    ])
    out += _section("Timeline", [
        f"{t['at']}  {t['event']}" + (f"\n    {t['detail']}" if t.get("detail") else "")
        for t in d["timeline"]
    ])
    out += _section("Data", [f"{k}: {v}" for k, v in d["data"]] + ([d["data_note"]] if d["data_note"] else []))
    out += _text_links(note)
    out += ["", f"Gateway: {note.get('gateway_id') or 'MetaCrust Edge Gateway'}"]
    return "\n".join(out)


def _section(title: str, rows: list[str]) -> list[str]:
    rows = [r for r in rows if r]
    return [title.upper(), *rows, ""] if rows else []


def _text_links(note: dict[str, Any]) -> list[str]:
    links = note.get("links") or []
    if links:
        return ["OPEN IN THE GATEWAY CONSOLE", *[f"{l['label']}: {l['url']}" for l in links]]
    if note.get("dashboard_url"):
        return ["", f"Open in the gateway console: {note['dashboard_url']}"]
    return []


_STATE_COLOUR = {"open": "#d93025", "recovering": "#1e8e5a", "resolved": "#1e8e5a"}
_CHECK_COLOUR = {"failed": "#d93025", "ok": "#1e8e5a", "later": "#b06000"}


def email_html(note: dict[str, Any]) -> str:
    """Inline-styled HTML; mail clients ignore stylesheets and most layout."""
    e = html.escape
    d = note.get("details")
    if not d:
        body = f"<p>{e(note.get('message') or '')}</p>" + _html_facts(_facts(note)) + _html_links(note)
        return _html_page(e(note.get("title") or "Gateway notification"), "#39d0c8", "", body)

    colour = _STATE_COLOUR.get(d["status"], "#5f6368")
    affected = d["affected"]
    affected_rows = []
    if affected["sources"]:
        affected_rows.append(("Sources", ", ".join(affected["sources"])))
    if affected["destinations"]:
        affected_rows.append(("Destinations", ", ".join(affected["destinations"])))
    cause = d["cause"]

    checks = "".join(
        f"<tr><td style='padding:6px 10px;border-bottom:1px solid #eee;white-space:nowrap;"
        f"color:{_CHECK_COLOUR.get(str(c['state']), '#5f6368')};font-weight:600'>{e(c['result'])}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #eee;white-space:nowrap'>{e(str(c['check']))}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #eee;color:#3c4043'>{e(str(c['finding'] or ''))}</td></tr>"
        for c in d["checks"]
    )
    timeline = "".join(
        f"<tr><td style='padding:6px 10px;border-bottom:1px solid #eee;white-space:nowrap;color:#5f6368;"
        f"vertical-align:top'>{e(t['at'])}</td><td style='padding:6px 10px;border-bottom:1px solid #eee'>"
        f"<strong>{e(str(t['event']))}</strong>"
        + (f"<br><span style='color:#5f6368;font-size:13px'>{e(t['detail'])}</span>" if t.get("detail") else "")
        + "</td></tr>"
        for t in d["timeline"]
    )

    body = "".join([
        f"<p style='margin:0 0 16px;font-size:15px;line-height:1.5'>{e(d['summary'])}</p>",
        _html_box("What to do", f"<p style='margin:0;line-height:1.5'>{e(d['action'])}</p>", colour),
        _html_h("Details"), _html_facts(d["facts"]),
        (_html_h("Affected") + _html_facts(affected_rows)) if affected_rows else "",
        _html_h("Likely cause <span style='font-weight:400;color:#5f6368'>(inferred)</span>"),
        f"<p style='margin:0 0 4px'><strong>{e(str(cause['domain']))}</strong> &middot; "
        f"{e(str(cause['confidence']))} confidence</p>"
        f"<p style='margin:0 0 4px;color:#3c4043'>Basis: {e(cause['basis'])}.</p>"
        f"<p style='margin:0;color:#5f6368;font-size:13px'>{e(cause['note'])}</p>",
        (_html_h("What the gateway checked") + _html_table(checks)) if checks else "",
        (_html_h("Timeline") + _html_table(timeline)) if timeline else "",
        (_html_h("Data") + _html_facts(d["data"])
         + (f"<p style='margin:8px 0 0;color:#5f6368;font-size:13px'>{e(d['data_note'])}</p>" if d["data_note"] else ""))
        if d["data"] or d["data_note"] else "",
        _html_links(note),
    ])
    banner = (f"{e(d['headline'])} &middot; {e(d['status_label'])}",
              e(d["status_explain"]))
    return _html_page(e(str(note.get("title") or "")), colour, banner, body,
                      ref=e(str(note.get("incident_ref") or "")), gateway=e(str(note.get("gateway_id") or "")))


def _html_page(title: str, colour: str, banner: Any, body: str, *, ref: str = "", gateway: str = "") -> str:
    head, explain = banner if banner else ("", "")
    return (
        "<!doctype html><html><body style='margin:0;padding:0;background:#f4f5f7'>"
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='background:#f4f5f7'>"
        "<tr><td align='center' style='padding:24px 12px'>"
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='max-width:680px;"
        "background:#ffffff;border-radius:10px;overflow:hidden;font-family:Segoe UI,Helvetica,Arial,sans-serif;"
        "font-size:14px;color:#202124'>"
        f"<tr><td style='background:{colour};color:#ffffff;padding:16px 24px'>"
        f"<div style='font-size:12px;letter-spacing:.06em;text-transform:uppercase;opacity:.9'>"
        f"MetaCrust Edge Gateway{(' &middot; ' + ref) if ref else ''}</div>"
        f"<div style='font-size:20px;font-weight:600;margin-top:4px'>{title}</div>"
        + (f"<div style='margin-top:8px;font-size:14px;font-weight:600'>{head}</div>"
           f"<div style='font-size:13px;opacity:.95;margin-top:2px'>{explain}</div>" if head else "")
        + f"</td></tr><tr><td style='padding:20px 24px'>{body}</td></tr>"
        f"<tr><td style='padding:12px 24px;background:#fafafa;color:#80868b;font-size:12px'>"
        f"Sent by gateway {gateway or 'MetaCrust Edge Gateway'}. Times are the gateway's local time.</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def _html_h(text: str) -> str:
    return (f"<h3 style='margin:22px 0 8px;font-size:13px;letter-spacing:.05em;text-transform:uppercase;"
            f"color:#202124'>{text}</h3>")


def _html_box(title: str, inner: str, colour: str) -> str:
    return (f"<div style='border-left:4px solid {colour};background:#f8f9fa;padding:12px 14px;"
            f"border-radius:4px'><div style='font-weight:600;margin-bottom:4px'>{html.escape(title)}</div>"
            f"{inner}</div>")


def _html_table(rows: str) -> str:
    return f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse'>{rows}</table>"


def _html_facts(facts: list[tuple[str, Any]]) -> str:
    if not facts:
        return ""
    rows = "".join(
        f"<tr><td style='padding:5px 10px 5px 0;color:#5f6368;white-space:nowrap;vertical-align:top;width:1%'>"
        f"{html.escape(str(k))}</td><td style='padding:5px 0'>{html.escape(str(v))}</td></tr>"
        for k, v in facts
    )
    return _html_table(rows)


def _html_links(note: dict[str, Any]) -> str:
    links = note.get("links") or (
        [{"label": "Gateway console", "url": note["dashboard_url"]}] if note.get("dashboard_url") else []
    )
    if not links:
        return ""
    items = "".join(
        f"<p style='margin:6px 0'><a href='{html.escape(l['url'], quote=True)}' style='display:inline-block;"
        f"padding:8px 14px;border-radius:6px;text-decoration:none;font-weight:600;"
        f"{'background:#1a73e8;color:#ffffff' if i == 0 else 'border:1px solid #dadce0;color:#1a73e8'}'>"
        f"{html.escape(l['label'])}</a> <span style='color:#80868b;font-size:12px'>{html.escape(l['url'])}</span></p>"
        for i, l in enumerate(links)
    )
    return _html_h("Open in the gateway console") + items
