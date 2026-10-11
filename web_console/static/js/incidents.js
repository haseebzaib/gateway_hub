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
    // What each lifecycle state is called on screen — the same words as
    // gateway_incidents/wording.py, so the emails and the console agree.
    // "recovering" means service is back and the incident is waiting out its
    // stability window, never a live fault.
    const STATUS_TEXT = { open: "Active", recovering: "Restored", resolved: "Closed" };
    const statusText = (s) => STATUS_TEXT[s] || s;

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
                <span class="inc-status-badge is-${inc.status}">${esc(statusText(inc.status))}</span>
            </div>
            ${inc.recovering ? `<p class="inc-confirming">Service came back at ${stamp(inc.restored_ms)} and is working now. This incident closes automatically after 5 minutes of stable service, so a brief relapse is caught as the same incident rather than a new one.</p>` : ""}

            <div class="inc-export">
                <span class="inc-export-label">Export incident</span>
                <a class="inc-export-btn is-primary" href="/api/insights/incidents/${encodeURIComponent(inc.ref)}/report" target="_blank" rel="noopener">Report (print / PDF)</a>
                <a class="inc-export-btn" href="/api/insights/incidents/${encodeURIComponent(inc.ref)}/report.csv">CSV</a>
                <a class="inc-export-btn" href="/api/insights/incidents/${encodeURIComponent(inc.ref)}/report.json" target="_blank" rel="noopener">JSON</a>
            </div>

            <div class="inc-when">
                <div>
                    <span class="inc-when-label">Started</span>
                    <span class="inc-when-value">${stamp(inc.started_ms)}</span>
                </div>
                <div>
                    <span class="inc-when-label">${inc.ongoing ? "Active for" : inc.recovering ? "Restored" : "Ended"}</span>
                    <span class="inc-when-value">${inc.ongoing ? duration(inc.duration_ms) : inc.recovering ? stamp(inc.restored_ms) : stamp(inc.ended_ms)}</span>
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

    /** Pilot Summary: KPIs totalled across a date range.
     *
     * Reports on a whole pilot rather than a single incident. Every figure
     * carries the same caveats as the per-incident KPIs — the recovery basis is
     * shown, and one incident with an unverifiable gap makes the whole period
     * unverifiable, because a headline total would otherwise imply a
     * completeness the data cannot support.
     */
    const attachPilotSummary = (panel, scope) => {
        if (!panel) return null;
        const toggle = panel.querySelector("[data-pilot-toggle]");
        const range  = panel.querySelector("[data-pilot-range]");
        const body   = panel.querySelector("[data-pilot-body]");
        const fromEl = panel.querySelector("[data-pilot-from]");
        const toEl   = panel.querySelector("[data-pilot-to]");
        const csvEl  = panel.querySelector("[data-pilot-csv]");

        const iso = (d) => d.toISOString().slice(0, 10);
        const today = new Date();
        const weekAgo = new Date(today.getTime() - 7 * 86400000);
        if (fromEl && !fromEl.value) fromEl.value = iso(weekAgo);
        if (toEl && !toEl.value) toEl.value = iso(today);

        const params = () => {
            const p = new URLSearchParams();
            if (fromEl?.value) p.set("from_ms", String(new Date(`${fromEl.value}T00:00:00`).getTime()));
            if (toEl?.value)   p.set("to_ms",   String(new Date(`${toEl.value}T23:59:59`).getTime()));
            if (scope) p.set("scope", scope);
            return p;
        };

        const load = async () => {
            if (!body) return;
            body.innerHTML = `<p style="color:var(--muted)">Loading…</p>`;
            if (csvEl) csvEl.href = `/api/insights/pilot-summary.csv?${params()}`;
            try {
                const r = await fetch(`/api/insights/pilot-summary?${params()}`);
                if (!r.ok) { body.innerHTML = "<p>Could not load the summary.</p>"; return; }
                const s = (await r.json()).summary || {};
                const verified = s.completeness === "verified";
                const pct = s.recovery_pct === null || s.recovery_pct === undefined ? "n/a" : `${s.recovery_pct}%`;
                body.innerHTML = `
                    <div class="inc-kpis">
                        <div class="inc-kpi"><div class="inc-kpi-value">${num(s.incidents)}</div><div class="inc-kpi-label">Incidents</div></div>
                        <div class="inc-kpi"><div class="inc-kpi-value">${num(s.resolved)}</div><div class="inc-kpi-label">Resolved</div></div>
                        <div class="inc-kpi ${s.ongoing ? "is-loss" : ""}"><div class="inc-kpi-value">${num(s.ongoing)}</div><div class="inc-kpi-label">Still open</div></div>
                        <div class="inc-kpi"><div class="inc-kpi-value">${duration(s.total_blind_time_ms)}</div><div class="inc-kpi-label">Total blind time</div></div>
                        <div class="inc-kpi"><div class="inc-kpi-value">${duration(s.longest_blind_time_ms)}</div><div class="inc-kpi-label">Longest outage</div></div>
                        <div class="inc-kpi"><div class="inc-kpi-value">${duration(s.median_detection_latency_ms)}</div><div class="inc-kpi-label">Median detection</div></div>
                        <div class="inc-kpi"><div class="inc-kpi-value">${num(s.buffered_peak)}</div><div class="inc-kpi-label">Peak buffered</div></div>
                        <div class="inc-kpi ${s.replayed ? "is-good" : ""}"><div class="inc-kpi-value">${num(s.replayed)}</div><div class="inc-kpi-label">Recovered</div></div>
                        <div class="inc-kpi ${(s.pending || 0) + (s.evicted || 0) > 0 ? "is-loss" : ""}"><div class="inc-kpi-value">${num((s.pending || 0) + (s.evicted || 0))}</div><div class="inc-kpi-label">Unrecovered</div></div>
                        <div class="inc-kpi"><div class="inc-kpi-value">${pct}</div><div class="inc-kpi-label">Recovery</div></div>
                        <div class="inc-kpi"><div class="inc-kpi-value">${num(s.uplink_switches)}</div><div class="inc-kpi-label">Uplink switches</div></div>
                        <div class="inc-kpi"><div class="inc-kpi-value">${num(s.forwarding_failures)}</div><div class="inc-kpi-label">Forwarding retries</div></div>
                    </div>
                    <p class="inc-kpi-basis">Recovery measured as ${esc(s.recovery_basis || "")}.</p>
                    <div class="inc-completeness ${verified ? "is-verified" : "is-unverifiable"}">
                        <span class="inc-completeness-tag">${verified ? "Completeness verified" : "Completeness unverifiable"}</span>
                        <span class="inc-completeness-note">${esc(s.completeness_note || "")}</span>
                    </div>`;
            } catch (e) {
                body.innerHTML = "<p>Could not load the summary.</p>";
            }
        };

        toggle?.addEventListener("click", () => {
            const hidden = body?.classList.contains("ov-hidden");
            body?.classList.toggle("ov-hidden", !hidden);
            range?.classList.toggle("ov-hidden", !hidden);
            toggle.classList.toggle("is-current", hidden);
            if (hidden) load();
        });
        panel.querySelector("[data-pilot-apply]")?.addEventListener("click", load);
        return { load };
    };

    /** Page a long incident history so the list never grows without bound. */
    const paginate = (rows, page, perPage) => {
        const pageCount = Math.max(1, Math.ceil(rows.length / perPage));
        const current = Math.min(Math.max(0, page), pageCount - 1);
        return { pageCount, current, slice: rows.slice(current * perPage, (current + 1) * perPage) };
    };

    // Numbered pages, so any page is one click away. Long runs collapse to
    // first · neighbours · last with an ellipsis between.
    const pageNumbers = (current, pageCount) => {
        const keep = new Set([0, pageCount - 1, current - 1, current, current + 1]);
        const out = [];
        for (let i = 0; i < pageCount; i += 1) {
            if (keep.has(i)) out.push(i);
            else if (out[out.length - 1] !== "…") out.push("…");
        }
        return out;
    };

    const pagerHtml = (current, pageCount, total) => pageCount > 1 ? `
        <button class="ev-page-btn" data-inc-page="${current - 1}" ${current === 0 ? "disabled" : ""} aria-label="Previous page">‹</button>
        ${pageNumbers(current, pageCount).map((n) => n === "…"
            ? `<span class="ev-page-gap">…</span>`
            : `<button class="ev-page-btn ev-page-num${n === current ? " is-current" : ""}" data-inc-page="${n}" ${n === current ? 'aria-current="page"' : ""}>${n + 1}</button>`).join("")}
        <button class="ev-page-btn" data-inc-page="${current + 1}" ${current >= pageCount - 1 ? "disabled" : ""} aria-label="Next page">›</button>
        <span class="ev-page-label">${total} incidents</span>` : "";

    /** Wire a rendered pager: every button carries the page it goes to. */
    const bindPager = (pager, go) => {
        pager.querySelectorAll("[data-inc-page]").forEach((b) => {
            b.addEventListener("click", () => go(Number(b.dataset.incPage)));
        });
    };

    const rowHtml = (inc) => `
        <div class="inc-row is-${inc.status}" data-inc-ref="${esc(inc.ref)}">
            <div class="inc-row-top">
                <span class="inc-ref">${esc(inc.ref)}</span>
                <span class="inc-title">${esc(inc.title)}</span>
                <span class="inc-status-badge is-${inc.status}">${esc(statusText(inc.status))}</span>
                <span class="inc-domain-pill ${inc.domain !== "unknown" ? "is-known" : "is-unknown"}">${esc(inc.domain_label)}</span>
                <a class="inc-row-export" data-inc-row-export
                   href="/api/insights/incidents/${encodeURIComponent(inc.ref)}/report"
                   target="_blank" rel="noopener" title="Open the customer report for ${esc(inc.ref)}">Export</a>
            </div>
            <div class="inc-row-meta">
                <span>Started <strong>${shortStamp(inc.started_ms)}</strong></span>
                ${inc.ongoing
                    ? `<span>Active for <strong>${duration(inc.duration_ms)}</strong></span>`
                    : inc.recovering
                    ? `<span>Restored <strong>${shortStamp(inc.restored_ms)}</strong></span>
                       <span>Closes after 5 min stable</span>`
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
        // The export link sits inside a row that opens the drawer on click, so
        // it has to stop the click reaching the row or both would fire.
        container?.querySelectorAll("[data-inc-row-export]").forEach((link) => {
            link.addEventListener("click", (e) => e.stopPropagation());
        });
    };

    const summaryHtml = (open, resolved, total, resolvedLabel = "Resolved in window") => `
        <div class="inc-sum-card${open > 0 ? " is-alert" : ""}">
            <div class="inc-sum-value">${open}</div>
            <div class="inc-sum-label">Active now</div>
        </div>
        <div class="inc-sum-card">
            <div class="inc-sum-value">${resolved}</div>
            <div class="inc-sum-label">${esc(resolvedLabel)}</div>
        </div>
        <div class="inc-sum-card">
            <div class="inc-sum-value">${total}</div>
            <div class="inc-sum-label">Total in window</div>
        </div>`;

    /** The incident a page was opened for, from ?incident=MC-1042. */
    const linkedRef = () => new URLSearchParams(window.location.search).get("incident");

    /**
     * A complete, self-contained incidents section for a page: summary, pilot
     * summary, paginated list and an in-place detail drawer, scoped to the
     * incidents that page owns. Returns { load }.
     */
    const attachPanel = (host, scope, { windowKey = "7d", label = "7 d" } = {}) => {
        if (!host) return null;
        host.innerHTML = `
            <div class="inc-summary" data-p-summary></div>
            <div class="pilot-panel" data-pilot-panel>
                <div class="pilot-head">
                    <button class="ev-view-btn" data-pilot-toggle>Pilot Summary</button>
                    <div class="pilot-range ov-hidden" data-pilot-range>
                        <label>From <input type="date" class="sv-date-input" data-pilot-from></label>
                        <label>To <input type="date" class="sv-date-input" data-pilot-to></label>
                        <button class="ev-win-btn" data-pilot-apply>Show</button>
                        <a class="inc-export-btn" data-pilot-csv href="#">↓ CSV</a>
                    </div>
                </div>
                <div class="pilot-body ov-hidden" data-pilot-body></div>
            </div>
            <div class="inc-list" data-p-list></div>
            <div class="ev-pager" data-p-pager></div>
            <div class="ev-empty ov-hidden" data-p-empty><p>No incidents in the last ${esc(label)}.</p></div>
            <div class="inc-drawer ov-hidden" data-inc-drawer>
                <div class="inc-drawer-scrim" data-inc-drawer-close></div>
                <aside class="inc-drawer-panel" data-inc-drawer-body></aside>
            </div>`;
        const list = host.querySelector("[data-p-list]");
        const pager = host.querySelector("[data-p-pager]");
        const empty = host.querySelector("[data-p-empty]");
        const summary = host.querySelector("[data-p-summary]");
        const drawer = attachDrawer(host.querySelector("[data-inc-drawer]"));
        attachPilotSummary(host.querySelector("[data-pilot-panel]"), scope);
        let rows = [];
        let page = 0;

        const render = () => {
            empty.classList.toggle("ov-hidden", rows.length > 0);
            const { pageCount, current, slice } = paginate(rows, page, 8);
            page = current;
            list.innerHTML = slice.map(rowHtml).join("");
            bindRows(list, drawer);
            pager.innerHTML = pagerHtml(current, pageCount, rows.length);
            bindPager(pager, (n) => { page = n; render(); });
        };

        const load = async () => {
            try {
                const r = await fetch(`/api/insights/incidents?window=${windowKey}&scope=${scope}`);
                if (!r.ok) return;
                rows = (await r.json()).incidents || [];
                const open = rows.filter((i) => i.ongoing).length;
                summary.innerHTML = summaryHtml(open, rows.length - open, rows.length, `Resolved · ${label}`);
                render();
            } catch (e) {
                console.warn(`[Incidents:${scope}] load failed`, e);
            }
        };
        return { load, drawer };
    };

    /** Open the linked incident on arrival: switch to its tab, then its detail. */
    const openLinked = async (showTab, drawer, load) => {
        const ref = linkedRef();
        if (!ref || !drawer) return;
        showTab?.();
        await load?.();
        drawer.open(ref);
    };

    return {
        attachPanel, openLinked, linkedRef,
        esc, stamp, shortStamp, duration, detailHtml, attachDrawer,
        statusText, paginate, pagerHtml, bindPager, rowHtml, bindRows, summaryHtml, attachPilotSummary, DOMAIN_PAGE,
    };
})();
