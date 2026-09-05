/* Incident presentation, shared by every page that lists incidents.
 *
 * Defined once so Sensor Insights and Data Forwarding cannot drift apart, and
 * so an incident opens where the operator already is rather than bouncing them
 * to another page.
 *
 * Loaded before app.js; exposed as the global `Incidents`.
 */
const Incidents = (() => {
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

    // Where each kind of failure is actually acted on. An incident is diagnosed
    // wherever it is being read, but fixed on the page that owns it.
    const DOMAIN_PAGE = {
        destination:   { href: "/forwarding",   label: "Open Data Forwarding" },
        uplink:        { href: "/connectivity", label: "Open Connectivity" },
        local_network: { href: "/connectivity", label: "Open Connectivity" },
        gateway:       { href: "/monitor",      label: "Open System Monitor" },
        source:        { href: "/interfaces",   label: "Open Interfaces" },
    };

    // Incidents always carry their date: an outage spanning midnight is
    // unreadable when only the clock time is shown.
    const stamp = (ms) => ms
        ? new Date(ms).toLocaleString([], {
            month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
        })
        : "—";

    const shortStamp = (ms) => ms
        ? new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
        : "—";

    const duration = (ms) => {
        if (!ms || ms < 0) return "—";
        const s = Math.round(ms / 1000);
        if (s < 60) return `${s}s`;
        const m = Math.floor(s / 60);
        if (m < 60) return `${m}m ${s % 60}s`;
        const h = Math.floor(m / 60);
        return h < 24 ? `${h}h ${m % 60}m` : `${Math.floor(h / 24)}d ${h % 24}h`;
    };

    // A KPI that was never measured is shown as "—", not as 0: zero would read
    // as "nothing was recovered", a stronger claim than the data supports.
    const num = (v) => (v === null || v === undefined) ? "—" : v.toLocaleString();

    /** KPI strip: the numbers a pilot report is written from.
     *
     * Recovery always states its denominator, and an incident whose source went
     * silent is labelled unverifiable however well the buffer performed —
     * a percentage of what we received is not a measure of completeness.
     */
    const kpiHtml = (inc) => {
        const k = inc.kpi;
        if (!k || Object.keys(k).length <= 1) return "";
        const verified = k.completeness === "verified";
        const partial = Boolean(k.partial);
        const pct = k.recovery_pct === null || k.recovery_pct === undefined
            ? "n/a" : `${k.recovery_pct}%`;
        return `
            <div class="inc-d-section">
                <h4>Continuity KPIs</h4>
                <div class="inc-kpis">
                    <div class="inc-kpi">
                        <div class="inc-kpi-value">${duration(k.blind_time_ms)}</div>
                        <div class="inc-kpi-label">Blind time</div>
                    </div>
                    <div class="inc-kpi">
                        <div class="inc-kpi-value">${duration(k.detection_latency_ms)}</div>
                        <div class="inc-kpi-label">Detection latency</div>
                    </div>
                    <div class="inc-kpi">
                        <div class="inc-kpi-value">${num(k.buffered_peak)}</div>
                        <div class="inc-kpi-label">Buffered</div>
                    </div>
                    <div class="inc-kpi${k.replayed ? " is-good" : ""}">
                        <div class="inc-kpi-value">${num(k.replayed)}</div>
                        <div class="inc-kpi-label">Recovered</div>
                    </div>
                    <div class="inc-kpi ${(k.pending || 0) + (k.evicted || 0) > 0 ? "is-loss" : ""}">
                        <div class="inc-kpi-value">${k.pending === null && k.evicted === null
                            ? "—" : num((k.pending || 0) + (k.evicted || 0))}</div>
                        <div class="inc-kpi-label">Unrecovered</div>
                    </div>
                    <div class="inc-kpi">
                        <div class="inc-kpi-value">${pct}</div>
                        <div class="inc-kpi-label">Recovery</div>
                    </div>
                    <div class="inc-kpi">
                        <div class="inc-kpi-value">${num(k.uplink_switches)}</div>
                        <div class="inc-kpi-label">Uplink switches</div>
                    </div>
                    <div class="inc-kpi">
                        <div class="inc-kpi-value">${num(k.forwarding_failures)}</div>
                        <div class="inc-kpi-label">Forwarding retries</div>
                    </div>
                </div>
                <p class="inc-kpi-basis">Recovery measured as ${esc(k.recovery_basis || "")}.</p>
                <div class="inc-completeness ${verified ? "is-verified" : "is-unverifiable"}">
                    <span class="inc-completeness-tag">${verified ? "Completeness verified"
                        : partial ? "Not measured" : "Completeness unverifiable"}</span>
                    <span class="inc-completeness-note">${esc(k.completeness_note || "")}</span>
                </div>
            </div>`;
    };

    const detailHtml = (inc, raw) => {
        const sources = (inc.affected || []).filter((a) => a.kind === "source");
        const others  = (inc.affected || []).filter((a) => a.kind !== "source");
        const c = inc.continuity || {};
        const known = inc.domain && inc.domain !== "unknown";
        const page = DOMAIN_PAGE[inc.domain];

        const timelineRows = (inc.timeline || []).map((t) => `
            <div class="inc-tl-row">
                <span class="inc-tl-time">${stamp(t.ts_ms)}</span>
                <span class="inc-tl-body">
                    <span class="inc-tl-label">${esc(t.label)}</span>
                    ${t.hint ? `<span class="inc-tl-hint">${esc(t.hint)}</span>` : ""}
                </span>
            </div>`).join("");

        const evidenceRows = (inc.evidence || []).map((e) => `
            <div class="inc-ev-row is-${e.state}">
                <span class="inc-ev-check">${esc(e.check)}</span>
                <span class="inc-ev-state">${esc(e.state)}</span>
                <span>${esc(e.finding)}</span>
            </div>`).join("");

        const rawRows = raw.length
            ? raw.slice(0, 40).map((r) => `
                <div class="inc-raw-row">
                    <span class="inc-raw-time">${shortStamp(r.timestamp_ms)}</span>
                    <span class="inc-raw-msg"><strong>${esc(r.device_name || r.device_id || "")}</strong> ${esc(r.message || "")}</span>
                </div>`).join("")
            : `<div class="inc-raw-row"><span class="inc-raw-msg">No raw events recorded for this incident.</span></div>`;

        return `
            <button class="inc-d-close" data-inc-close aria-label="Close">×</button>
            <div class="inc-d-head">
                <span class="inc-ref">${esc(inc.ref)}</span>
                <h3 class="inc-d-title">${esc(inc.title)}</h3>
                <span class="inc-status-badge is-${inc.status}">${esc(inc.status)}</span>
            </div>

            <div class="inc-when">
                <div>
                    <span class="inc-when-label">Started</span>
                    <span class="inc-when-value">${stamp(inc.started_ms)}</span>
                </div>
                <div>
                    <span class="inc-when-label">${inc.ongoing ? "Ongoing for" : "Ended"}</span>
                    <span class="inc-when-value">${inc.ongoing ? duration(inc.duration_ms) : stamp(inc.ended_ms)}</span>
                </div>
                ${inc.ongoing ? "" : `
                <div>
                    <span class="inc-when-label">Lasted</span>
                    <span class="inc-when-value">${duration(inc.duration_ms)}</span>
                </div>`}
            </div>

            <div class="inc-verdict${known ? "" : " is-unknown"}">
                <div class="inc-verdict-domain">Likely cause: ${esc(inc.domain_label || "Unknown")}</div>
                <div class="inc-verdict-note">${known
                    ? `Chosen with ${esc(inc.domain_conf)} confidence from the checks below.`
                    : "Not enough evidence to say reliably — the checks below show what could not be verified."}</div>
                ${page ? `<a class="inc-goto" href="${page.href}">${esc(page.label)} →</a>` : ""}
            </div>

            <div class="inc-d-section">
                <h4>What happened, and when</h4>
                <div class="inc-timeline">${timelineRows || '<div class="inc-tl-row"><span>—</span></div>'}</div>
            </div>

            <div class="inc-d-section">
                <h4>Impact</h4>
                <div class="inc-chips">
                    ${sources.length
                        ? sources.map((s) => `<span class="inc-chip">${esc(s.name)}</span>`).join("")
                        : '<span class="inc-chip">No sources were delivering at the time</span>'}
                    ${others.map((o) => `<span class="inc-chip">${esc(o.name)}</span>`).join("")}
                </div>
            </div>

            ${kpiHtml(inc)}

            <div class="inc-d-section">
                <h4>Data continuity detail</h4>
                <div class="inc-metrics">
                    <div class="inc-metric">
                        <div class="inc-metric-value">${(c.buffered_peak ?? c.pending ?? 0).toLocaleString()}</div>
                        <div class="inc-metric-label">Buffered</div>
                    </div>
                    <div class="inc-metric">
                        <div class="inc-metric-value">${(c.replayed ?? 0).toLocaleString()}</div>
                        <div class="inc-metric-label">Replayed</div>
                    </div>
                    <div class="inc-metric ${(c.unrecovered ?? c.pending ?? 0) > 0 ? "is-loss" : "is-good"}">
                        <div class="inc-metric-value">${(c.unrecovered ?? c.pending ?? 0).toLocaleString()}</div>
                        <div class="inc-metric-label">Unrecovered</div>
                    </div>
                    <div class="inc-metric ${(c.dropped ?? 0) > 0 ? "is-loss" : "is-good"}">
                        <div class="inc-metric-value">${(c.dropped ?? 0).toLocaleString()}</div>
                        <div class="inc-metric-label">Dropped</div>
                    </div>
                </div>
            </div>

            <div class="inc-d-section">
                <h4>What the gateway checked</h4>
                <div class="inc-evidence">${evidenceRows}</div>
            </div>

            <div class="inc-d-section">
                <h4>Raw events (${raw.length})</h4>
                <div class="inc-raw">${rawRows}</div>
            </div>`;
    };

    /** Wire a drawer element so incidents open in place, on whichever page. */
    const attachDrawer = (drawer) => {
        if (!drawer) return null;
        const body = drawer.querySelector("[data-inc-drawer-body]");
        const close = () => drawer.classList.add("ov-hidden");
        drawer.querySelector("[data-inc-drawer-close]")?.addEventListener("click", close);
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && !drawer.classList.contains("ov-hidden")) close();
        });
        return {
            close,
            open: async (ref) => {
                if (!body) return;
                drawer.classList.remove("ov-hidden");
                body.innerHTML = `<p style="color:var(--muted)">Loading ${esc(ref)}…</p>`;
                try {
                    const r = await fetch(`/api/insights/incidents/${encodeURIComponent(ref)}`);
                    if (!r.ok) { body.innerHTML = "<p>Incident not found.</p>"; return; }
                    const d = await r.json();
                    body.innerHTML = detailHtml(d.incident, d.raw_events || []);
                    body.querySelector("[data-inc-close]")?.addEventListener("click", close);
                } catch (e) {
                    body.innerHTML = "<p>Could not load this incident.</p>";
                }
            },
        };
    };

    /** Page a long incident history so the list never grows without bound. */
    const paginate = (rows, page, perPage) => {
        const pageCount = Math.max(1, Math.ceil(rows.length / perPage));
        const current = Math.min(Math.max(0, page), pageCount - 1);
        return { pageCount, current, slice: rows.slice(current * perPage, (current + 1) * perPage) };
    };

    const pagerHtml = (current, pageCount, total) => pageCount > 1 ? `
        <button class="ev-page-btn" data-inc-page-prev ${current === 0 ? "disabled" : ""}>← Newer</button>
        <span class="ev-page-label">Page ${current + 1} of ${pageCount} · ${total} incidents</span>
        <button class="ev-page-btn" data-inc-page-next ${current >= pageCount - 1 ? "disabled" : ""}>Older →</button>` : "";

    const rowHtml = (inc) => `
        <div class="inc-row is-${inc.status}" data-inc-ref="${esc(inc.ref)}">
            <div class="inc-row-top">
                <span class="inc-ref">${esc(inc.ref)}</span>
                <span class="inc-title">${esc(inc.title)}</span>
                <span class="inc-status-badge is-${inc.status}">${esc(inc.status)}</span>
                <span class="inc-domain-pill ${inc.domain !== "unknown" ? "is-known" : "is-unknown"}">${esc(inc.domain_label)}</span>
            </div>
            <div class="inc-row-meta">
                <span>Started <strong>${shortStamp(inc.started_ms)}</strong></span>
                ${inc.ongoing
                    ? `<span>Ongoing for <strong>${duration(inc.duration_ms)}</strong></span>`
                    : `<span>Ended <strong>${shortStamp(inc.ended_ms)}</strong></span>
                       <span>Lasted <strong>${duration(inc.duration_ms)}</strong></span>`}
                ${inc.resolution ? `<span>${esc(inc.resolution)}</span>` : ""}
            </div>
        </div>`;

    /** Bind click-to-open on every incident row inside a container. */
    const bindRows = (container, drawer) => {
        container?.querySelectorAll("[data-inc-ref]").forEach((row) => {
            row.addEventListener("click", () => drawer?.open(row.getAttribute("data-inc-ref")));
        });
    };

    const summaryHtml = (open, resolved, total, resolvedLabel = "Resolved in window") => `
        <div class="inc-sum-card${open > 0 ? " is-alert" : ""}">
            <div class="inc-sum-value">${open}</div>
            <div class="inc-sum-label">Ongoing now</div>
        </div>
        <div class="inc-sum-card">
            <div class="inc-sum-value">${resolved}</div>
            <div class="inc-sum-label">${esc(resolvedLabel)}</div>
        </div>
        <div class="inc-sum-card">
            <div class="inc-sum-value">${total}</div>
            <div class="inc-sum-label">Total in window</div>
        </div>`;

    return {
        esc, stamp, shortStamp, duration, detailHtml, attachDrawer,
        paginate, pagerHtml, rowHtml, bindRows, summaryHtml, DOMAIN_PAGE,
    };
})();
