document.addEventListener("DOMContentLoaded", () => {
    const dashboardShell = document.querySelector("[data-dashboard-shell]");
    const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
    const sidebarStorageKey = "metacrust.sidebar.collapsed";

    if (dashboardShell && sidebarToggle) {
        const applySidebarState = (collapsed) => {
            dashboardShell.classList.toggle("is-sidebar-collapsed", collapsed);
            sidebarToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        };

        const storedSidebarState = window.localStorage.getItem(sidebarStorageKey);
        applySidebarState(storedSidebarState === "true");

        sidebarToggle.addEventListener("click", () => {
            const collapsed = !dashboardShell.classList.contains("is-sidebar-collapsed");
            applySidebarState(collapsed);
            window.localStorage.setItem(sidebarStorageKey, collapsed ? "true" : "false");
        });
    }

    const overviewShell = document.querySelector("[data-overview-shell]");
    if (overviewShell) {
        const chipGateway  = overviewShell.querySelector('[data-overview-chip="gateway"]');
        const chipPrimary  = overviewShell.querySelector('[data-overview-chip="primary-link"]');
        const chipWireless = overviewShell.querySelector('[data-overview-chip="wireless"]');
        const chipCellular = overviewShell.querySelector('[data-overview-chip="cellular"]');
        const led = overviewShell.querySelector("[data-overview-led]");
        const ethLink = overviewShell.querySelector("[data-overview-eth-link]");
        const wifiLink = overviewShell.querySelector("[data-overview-wifi-link]");
        const ethPort = overviewShell.querySelector("[data-overview-eth-port]");
        const wifiPort = overviewShell.querySelector("[data-overview-wifi-port]");
        const ethernetItem = overviewShell.querySelector('[data-overview-item="ethernet"]');
        const wifiItem = overviewShell.querySelector('[data-overview-item="wi-fi"]');
        const systemMetricsShell = document.querySelector("[data-system-metrics-shell]");
        const systemCpuSummary = document.querySelector("[data-system-cpu-summary]");
        const systemMemorySummary = document.querySelector("[data-system-memory-summary]");
        const systemTempSummary = document.querySelector("[data-system-temp-summary]");
        const systemNetworkSummary = document.querySelector("[data-system-network-summary]");

        const setTone = (badge, tone) => {
            if (!badge) {
                return;
            }
            badge.classList.remove("is-active", "is-standby", "is-inactive");
            badge.classList.add(`is-${tone}`);
        };

        const updateItem = (item, state, detail, tone) => {
            if (!item) {
                return;
            }
            const stateNode = item.querySelector("[data-overview-state]");
            const detailNode = item.querySelector("[data-overview-detail]");
            const badge = item.querySelector("[data-overview-badge]");
            if (stateNode) {
                stateNode.textContent = state;
            }
            if (detailNode) {
                detailNode.textContent = detail;
            }
            setTone(badge, tone);
        };

        const cellularItem    = overviewShell.querySelector('[data-overview-item="cellular"]');
        const fwdOverviewItem = document.querySelector('[data-overview-item="data-forwarding"]');
        const cellLink        = overviewShell.querySelector("[data-overview-cell-link]");
        const cellPort        = overviewShell.querySelector("[data-overview-cell-port]");
        const gatewayIfaceBoxes = {
            eth0: overviewShell.querySelector('[data-gateway-iface="eth0"]'),
            eth1: overviewShell.querySelector('[data-gateway-iface="eth1"]'),
            wifi: overviewShell.querySelector('[data-gateway-iface="wifi"]'),
            cellular: overviewShell.querySelector('[data-gateway-iface="cellular"]'),
        };

        const _fmtDur = (secs) => {
            if (!secs && secs !== 0) return "—";
            secs = Math.round(secs);
            if (secs < 60)   return `${secs}s`;
            if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
            const h = Math.floor(secs / 3600);
            const m = Math.floor((secs % 3600) / 60);
            return `${h}h ${m}m`;
        };
        const _fmtDurMs = (ms) => (ms || ms === 0) ? _fmtDur(Math.round(ms / 1000)) : "—";
        const _fmtDateTime = (ms) => {
            if (!ms) return "—";
            try {
                return new Date(Number(ms)).toLocaleString([], {
                    year: "numeric", month: "2-digit", day: "2-digit",
                    hour: "2-digit", minute: "2-digit", second: "2-digit",
                });
            } catch (_) {
                return "—";
            }
        };
        const _uplinkName = (key) =>
            key === "eth0"        ? "Ethernet (eth0)"
          : key === "eth1"        ? "Ethernet (eth1)"
          : key === "wifi_client" ? "Wi-Fi"
          : key === "cellular"    ? "Cellular"
          : key === "none"        ? "Offline"
          : (key || "—");

        const updateGatewayIface = (key, state, detail, tone) => {
            const box = gatewayIfaceBoxes[key];
            if (!box) return;
            box.classList.remove("is-active", "is-standby", "is-inactive");
            box.classList.add(`is-${tone}`);
            const stateEl = box.querySelector("[data-gateway-iface-state]");
            const detailEl = box.querySelector("[data-gateway-iface-detail]");
            if (stateEl) stateEl.textContent = state;
            if (detailEl) detailEl.textContent = detail;
        };

        const applyOverviewState = (networkState) => {
            const eth0       = networkState?.eth0        || {};
            const eth1       = networkState?.eth1        || {};
            const wifiClient = networkState?.wifi_client || {};
            const wifiAp     = networkState?.wifi_ap     || {};
            const cellular   = networkState?.cellular    || {};
            const audit      = networkState?._audit || {};
            const activeUplink = String(networkState?.active_uplink || "none");

            const eth0Connected     = Boolean(eth0.link_up) && Boolean(eth0.address);
            const eth1Connected     = Boolean(eth1.link_up) && Boolean(eth1.address);
            const ethernetConnected = eth0Connected || eth1Connected;
            const wifiConnected     = Boolean(wifiClient.connected_ssid);
            const wifiApEnabled     = Boolean(wifiAp.enabled);
            const wifiPresent       = wifiClient.present !== false;
            const celConnected      = Boolean(cellular.connected);
            const celEnabled        = Boolean(cellular.enabled);
            const celPresent        = Boolean(cellular.present);

            const anyOnline    = ethernetConnected || wifiConnected || wifiApEnabled || celConnected;
            const gatewayHealth = anyOnline ? "Online" : "Standby";
            const primaryLink   = ["eth0","eth1"].includes(activeUplink) ? "Ethernet"
                                : activeUplink === "wifi_client"         ? "Wi-Fi"
                                : activeUplink === "cellular"            ? "Cellular"
                                : "Offline";
            const wirelessState = wifiConnected ? "Connected" : wifiApEnabled ? "Access Point" : wifiPresent ? "Standby" : "Unavailable";

            if (chipGateway)  chipGateway.textContent  = gatewayHealth;
            if (chipPrimary)  chipPrimary.textContent  = primaryLink;
            if (chipWireless) chipWireless.textContent = wirelessState;

            if (led) led.classList.toggle("is-offline", !anyOnline);
            if (ethLink)  ethLink.classList.toggle("is-inactive",  !ethernetConnected && !["eth0","eth1"].includes(activeUplink));
            if (wifiLink) wifiLink.classList.toggle("is-inactive", !wifiConnected && !wifiApEnabled && activeUplink !== "wifi_client");
            if (cellLink) cellLink.classList.toggle("is-inactive", !celConnected && activeUplink !== "cellular");
            if (ethPort)  ethPort.classList.toggle("is-active",   ethernetConnected || ["eth0","eth1"].includes(activeUplink));
            if (wifiPort) wifiPort.classList.toggle("is-active",  wifiConnected || wifiApEnabled || activeUplink === "wifi_client");
            if (cellPort) cellPort.classList.toggle("is-active",  celConnected || activeUplink === "cellular");

            updateGatewayIface(
                "eth0",
                activeUplink === "eth0" ? "Active" : eth0Connected ? "Ready" : "Down",
                eth0.address || (eth0.link_up ? "Waiting for IP" : "No link"),
                activeUplink === "eth0" ? "active" : eth0Connected ? "standby" : "inactive",
            );
            updateGatewayIface(
                "eth1",
                activeUplink === "eth1" ? "Active" : eth1Connected ? "Ready" : "Down",
                eth1.address || (eth1.link_up ? "Waiting for IP" : "No link"),
                activeUplink === "eth1" ? "active" : eth1Connected ? "standby" : "inactive",
            );

            const ethAddress = eth0.address || eth1.address || "";
            const ethDetail  = ethAddress
                ? `${activeUplink === "eth1" ? "eth1" : "eth0"}: ${ethAddress}`
                : "Waiting for DHCP";
            updateItem(ethernetItem,
                ethernetConnected ? "Connected" : "Disconnected",
                ethernetConnected ? ethDetail   : "No cable link",
                ethernetConnected ? "active"    : "inactive");

            // WiFi diagnostic reason for improved status detail
            const wifiDiag    = wifiClient.diagnostics || {};
            const wifiCfgSsid = wifiClient.configured_ssid || "";
            const _wifiReasonLabel = (r) => ({
                scanning:                   "Scanning for network…",
                disconnected:               "Disconnected",
                authenticating:             "Authenticating…",
                associating:                "Associating with AP…",
                waiting_for_ip:             "Waiting for IP (DHCP)…",
                connected_no_internet:      "Connected — no internet",
                supplicant_inactive:        "Wi-Fi supplicant not running",
                interface_missing:          "Interface not detected",
                interface_disabled:         "Interface disabled",
                ssid_missing:               "No SSID configured",
                disabled:                   "Wi-Fi disabled",
                supplicant_status_unavailable: "Status unavailable",
            }[r] || r || "");

            const wifiStandbyDetail = (() => {
                if (wifiApEnabled) return `${wifiAp.clients ?? 0} client(s) on hotspot`;
                if (!wifiPresent)  return "Wireless interface not detected";
                if (wifiCfgSsid && wifiDiag.reason && wifiDiag.reason !== "disabled") {
                    return `Target: "${wifiCfgSsid}" · ${_wifiReasonLabel(wifiDiag.reason)}`;
                }
                return wifiCfgSsid ? `Target: "${wifiCfgSsid}"` : "Radio available for setup";
            })();

            updateItem(wifiItem,
                wifiConnected ? "Connected" : wifiApEnabled ? "Access Point" : wifiPresent ? "Standby" : "Unavailable",
                wifiConnected ? (wifiClient.connected_ssid || "Wireless uplink active")
                              : wifiStandbyDetail,
                wifiConnected ? "active" : wifiApEnabled || wifiPresent ? "standby" : "inactive");
            updateGatewayIface(
                "wifi",
                activeUplink === "wifi_client" ? "Active" : wifiConnected ? "Ready" : wifiApEnabled ? "AP" : wifiPresent ? "Standby" : "Down",
                wifiConnected ? (wifiClient.connected_ssid || "Connected") : wifiApEnabled ? `${wifiAp.clients ?? 0} client(s)` : wifiStandbyDetail,
                activeUplink === "wifi_client" ? "active" : wifiConnected || wifiApEnabled || wifiPresent ? "standby" : "inactive",
            );

            // Cellular item
            const simStatus = String(cellular.sim_status || "");
            let celState, celDetail, celTone;
            if (celConnected) {
                const operator = cellular.operator || "Unknown operator";
                const sigPct   = cellular.signal_percent;
                const sigDbm   = cellular.signal_dbm;
                const sigQual  = sigPct == null ? "" : sigPct >= 80 ? "Strong" : sigPct >= 60 ? "Good" : sigPct >= 40 ? "Fair" : sigPct >= 20 ? "Weak" : "Poor";
                const sigStr   = sigPct != null
                    ? ` · ${sigQual} signal (${sigPct}%${sigDbm != null ? ` · ${sigDbm} dBm` : ""})`
                    : "";
                celState  = "Connected";
                celDetail = `${operator}${sigStr}`;
                celTone   = "active";
            } else if (celEnabled && celPresent) {
                if (simStatus === "locked")  { celState = "PIN Locked";  celDetail = "SIM PIN required";             celTone = "standby"; }
                else if (simStatus === "missing") { celState = "No SIM";   celDetail = "No SIM card detected";       celTone = "standby"; }
                else                         { celState = "Connecting"; celDetail = "Modem present, establishing link"; celTone = "standby"; }
            } else if (celEnabled && !celPresent) {
                celState = "No Modem";  celDetail = "SIM7600 not detected"; celTone = "inactive";
            } else {
                celState = "Disabled";  celDetail = "Cellular fallback is off"; celTone = "inactive";
            }
            updateItem(cellularItem, celState, celDetail, celTone);
            if (chipCellular) chipCellular.textContent = celState;
            updateGatewayIface(
                "cellular",
                activeUplink === "cellular" ? "Active" : celState,
                celDetail,
                activeUplink === "cellular" ? "active" : celTone === "active" || celTone === "standby" ? "standby" : "inactive",
            );

            // ── Active uplink banner (connectivity summary card) ─────────────
            const uplinkBadgeEl = document.querySelector("[data-ov-uplink-badge]");
            const uplinkSinceEl = document.querySelector("[data-ov-uplink-since]");
            const failoverSumEl = document.querySelector("[data-ov-failover-summary]");

            if (uplinkBadgeEl) {
                uplinkBadgeEl.textContent = _uplinkName(activeUplink);
                uplinkBadgeEl.className   = "ov-uplink-badge"
                    + (activeUplink === "none" ? " is-none" : anyOnline ? " is-active" : " is-none");
            }
            if (uplinkSinceEl) {
                uplinkSinceEl.textContent = audit.active_duration_ms !== undefined && activeUplink !== "none"
                    ? `Active since ${_fmtDateTime(audit.active_uplink_since_ms)} (${_fmtDurMs(audit.active_duration_ms)})`
                    : activeUplink === "none" ? "No active uplink" : "Waiting for AES audit sample";
            }
            const outageAlert = document.querySelector("[data-ov-outage-alert]");
            const outageTitle = document.querySelector("[data-ov-outage-title]");
            const outageTime = document.querySelector("[data-ov-outage-time]");
            const outageReason = document.querySelector("[data-ov-outage-reason]");
            const openOutage = audit.open_outage || null;
            const lastOutage = audit.last_outage || null;
            if (outageAlert) {
                outageAlert.hidden = false;
                outageAlert.classList.toggle("is-active", Boolean(openOutage));
                if (openOutage) {
                    if (outageTitle) outageTitle.textContent = `Outage now · ${_fmtDurMs(openOutage.duration_ms || 0)}`;
                    if (outageTime) outageTime.textContent = `Started ${_fmtDateTime(openOutage.started_at_ms)}`;
                    if (outageReason) outageReason.textContent = openOutage.reason || "No active uplink";
                } else if (lastOutage) {
                    if (outageTitle) outageTitle.textContent = `Last outage · ${_fmtDurMs(lastOutage.duration_ms)}`;
                    if (outageTime) outageTime.textContent = `${_fmtDateTime(lastOutage.started_at_ms)} → ${_fmtDateTime(lastOutage.ended_at_ms)}`;
                    if (outageReason) outageReason.textContent = lastOutage.reason || "Recovered";
                } else {
                    if (outageTitle) outageTitle.textContent = "No outage recorded";
                    if (outageTime) outageTime.textContent = "monitoring";
                    if (outageReason) outageReason.textContent = "Events will appear after first outage or failover.";
                }
            }
            if (failoverSumEl) {
                const sw = audit.uplink_switch_count ?? audit.counts?.uplink_switches ?? 0;
                const ls = audit.last_switch || null;
                if (ls) {
                    failoverSumEl.textContent = `${sw} switch${sw === 1 ? "" : "es"} · last ${_fmtDateTime(ls.timestamp_ms)} · ${_uplinkName(ls.previous_uplink)} → ${_uplinkName(ls.active_uplink)}`;
                } else {
                    failoverSumEl.textContent = openOutage
                        ? `Open outage started ${_fmtDateTime(openOutage.started_at_ms)}`
                        : "No failover/outage recorded by AES";
                }
            }
        };

        const refreshOverviewState = async () => {
            try {
                const [stateResponse, metricsResponse] = await Promise.all([
                    fetch("/api/network/state"),
                    fetch("/api/system/metrics"),
                ]);
                if (!stateResponse.ok) {
                    return;
                }
                const stateData = await stateResponse.json();
                applyOverviewState(stateData);
                if (systemMetricsShell && metricsResponse.ok) {
                    const metrics = await metricsResponse.json();
                    if (systemCpuSummary) {
                        systemCpuSummary.textContent = `${metrics?.cpu?.total_percent ?? "—"}%`;
                    }
                    if (systemMemorySummary) {
                        systemMemorySummary.textContent = `${metrics?.memory?.memory_bytes?.used_percent ?? "—"}%`;
                    }
                    if (systemTempSummary) {
                        systemTempSummary.textContent = metrics?.temperature_c != null ? `${metrics.temperature_c} °C` : "—";
                    }
                    if (systemNetworkSummary) {
                        const eth0 = metrics?.network?.eth0?.rates;
                        const eth1 = metrics?.network?.eth1?.rates;
                        const wifi = metrics?.network?.wlan0?.rates;
                        if (eth0 || eth1 || wifi) {
                            const parts = [];
                            if (eth0) parts.push(`ETH0 rx ${Math.round(eth0.rx_bytes_per_sec)} B/s tx ${Math.round(eth0.tx_bytes_per_sec)} B/s`);
                            if (eth1) parts.push(`ETH1 rx ${Math.round(eth1.rx_bytes_per_sec)} B/s tx ${Math.round(eth1.tx_bytes_per_sec)} B/s`);
                            if (wifi) parts.push(`WIFI rx ${Math.round(wifi.rx_bytes_per_sec)} B/s tx ${Math.round(wifi.tx_bytes_per_sec)} B/s`);
                            systemNetworkSummary.textContent = parts.join(" · ");
                        } else {
                            systemNetworkSummary.textContent = "No samples yet";
                        }
                    }
                }
            } catch (error) {
                console.warn("Failed to refresh overview network state", error);
            }
        };

        refreshOverviewState();
        window.setInterval(refreshOverviewState, 5000);

        // ── Insights summary for overview domain card ──────────────────────
        const refreshInsightsSummary = async () => {
            try {
                const r = await fetch("/api/insights/summary");
                if (!r.ok) return;
                const d = await r.json();
                const devEl  = document.querySelector("[data-ov-insights-devices]");
                const anEl   = document.querySelector("[data-ov-insights-anomalies]");
                const subEl  = document.querySelector("[data-ov-insights-sub]");
                const total  = d.total_devices  ?? 0;
                const live   = d.live_devices   ?? 0;
                const anoms  = d.anomaly_count  ?? 0;
                if (devEl) devEl.textContent = String(live);
                if (anEl)  anEl.textContent  = String(anoms);
                if (subEl) {
                    subEl.textContent = anoms > 0
                        ? `${anoms} anomal${anoms > 1 ? "ies" : "y"} detected`
                        : live > 0 ? "All readings nominal" : `${total} configured, none live`;
                    subEl.style.color = anoms > 0 ? "var(--accent)" : "";
                }
            } catch (e) {
                console.warn("[Overview] insights summary failed:", e);
            }
        };
        refreshInsightsSummary();
        window.setInterval(refreshInsightsSummary, 15000);

        // ── Forwarding status strip (lives outside overviewShell — use document) ──
        const fwdStrip = document.querySelector("[data-ov-fwd-strip]");
        const fwdCards = document.querySelector("[data-ov-fwd-cards]");
        const fwdHint  = document.querySelector("[data-ov-fwd-hint]");

        const _fwdAgo = (secs) => {
            if (secs === null || secs === undefined) return "never";
            if (secs < 60)  return `${secs}s ago`;
            if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
            return `${Math.floor(secs / 3600)}h ago`;
        };

        const _fwdStateClass = (state) => {
            if (state === "connected" || state === "active") return "is-ok";
            if (state === "connecting") return "is-warn";
            return "is-err";
        };

        const refreshFwdStrip = async () => {
            try {
                const r = await fetch("/api/forwarding/status");
                if (!r.ok) return;
                const d = await r.json();
                if (!d.ok) return;

                const mqttItems  = d.mqtt  || [];
                const httpsItems = d.https || [];
                const allItems   = [...mqttItems, ...httpsItems];

                // Build a quick name map from config (always current after saves)
                const ovNameMap = {};
                try {
                    const cr = await fetch("/api/forwarding/config");
                    if (cr.ok) {
                        const cd = await cr.json();
                        for (const p of (cd.profiles || [])) {
                            if (p.id) ovNameMap[p.id] = p.name || "Unnamed";
                        }
                    }
                } catch (_) {}
                const _fwdName = (x) => (x.profile_id && ovNameMap[x.profile_id]) || x.profile_name || "Profile";

                // ── Update Data Forwarding domain card (always) ───────────────
                if (fwdOverviewItem) {
                    if (allItems.length === 0) {
                        updateItem(fwdOverviewItem, "No profiles", "No forwarding profiles configured", "inactive");
                        const pipeline = document.querySelector("[data-ov-fw-pipeline]");
                        if (pipeline) pipeline.style.display = "none";
                    } else {
                        const okCount   = allItems.filter((x) =>
                            ("broker" in x) ? x.state === "connected" : x.tunnel_alive === true
                        ).length;
                        const errCount  = allItems.length - okCount;
                        const totalSent = allItems.reduce((s, x) => s + (x.publish_count ?? x.post_count ?? 0), 0);
                        const totalBuf  = allItems.reduce((s, x) => s + (x.buffer?.pending ?? 0), 0);
                        const totalRec  = allItems.reduce((s, x) => s + (x.buffer?.replayed ?? 0), 0);
                        const totalDrop = allItems.reduce((s, x) => s + (x.buffer?.dropped ?? 0), 0);

                        const fwdTone  = totalDrop > 0 ? "inactive"
                                       : totalBuf > 0  ? "standby"
                                       : okCount === allItems.length ? "active" : errCount === allItems.length ? "inactive" : "standby";
                        const fwdState = totalBuf > 0 ? `Active — ${totalBuf.toLocaleString()} buffered`
                                       : okCount === allItems.length ? "Active"
                                       : okCount > 0 ? `${okCount}/${allItems.length} active` : "Error";
                        const fwdDetail = allItems.map((x) => {
                            const name = _fwdName(x);
                            const ok   = ("broker" in x) ? x.state === "connected" : x.tunnel_alive;
                            return `${name}: ${ok ? "✓" : "✗"}`;
                        }).join("  ·  ");
                        updateItem(fwdOverviewItem, fwdState, fwdDetail, fwdTone);

                        // Pipeline stats counters
                        const pipeline = document.querySelector("[data-ov-fw-pipeline]");
                        if (pipeline) {
                            pipeline.style.display = "";
                            const sentEl = document.querySelector("[data-ov-fw-sent]");
                            const bufEl  = document.querySelector("[data-ov-fw-buffered]");
                            const recEl  = document.querySelector("[data-ov-fw-recovered]");
                            const bufWrap = document.querySelector("[data-ov-fw-buf-wrap]");
                            const recWrap = document.querySelector("[data-ov-fw-rec-wrap]");
                            if (sentEl) sentEl.textContent = totalSent.toLocaleString();
                            if (bufEl)  bufEl.textContent  = totalBuf.toLocaleString();
                            if (recEl)  recEl.textContent  = totalRec.toLocaleString();
                            if (bufWrap) {
                                bufWrap.className = `ov-fw-pipe-stat${totalBuf > 0 ? " is-buffering" : totalDrop > 0 ? " is-dropped" : ""}`;
                            }
                            if (recWrap) {
                                recWrap.className = `ov-fw-pipe-stat${totalRec > 0 ? " is-recovered" : ""}`;
                            }
                        }
                    }
                }

                // ── Update forwarding strip (only if element exists) ──────────
                if (!fwdStrip) return;
                if (allItems.length === 0) {
                    fwdStrip.classList.add("ov-hidden");
                    return;
                }
                fwdStrip.classList.remove("ov-hidden");
                if (fwdHint) fwdHint.textContent = `${allItems.length} profile${allItems.length > 1 ? "s" : ""} active`;

                if (fwdCards) {
                    fwdCards.innerHTML = allItems.map((item) => {
                        const isMqtt = "broker" in item;
                        const state  = isMqtt ? item.state : (item.tunnel_alive ? "active" : "error");
                        const stCls  = _fwdStateClass(state);
                        const label  = isMqtt ? "MQTT" : "HTTPS";
                        const dest   = isMqtt ? item.broker : item.endpoint;
                        const lastEv = isMqtt
                            ? (item.last_publish_ago !== null ? `Last pub: ${_fwdAgo(item.last_publish_ago)}` : "No publishes yet")
                            : (item.last_post_ago   !== null ? `Last POST: ${_fwdAgo(item.last_post_ago)} (HTTP ${item.last_status_code || "?"})` : "No posts yet");
                        const errLine = item.last_error
                            ? `<span class="ov-fwd-error">${item.last_error}</span>` : "";
                        return `
                        <div class="ov-fwd-card ${stCls}">
                            <div class="ov-fwd-card-head">
                                <span class="ov-fwd-badge">${label}</span>
                                <span class="ov-fwd-name">${item.profile_name || item.profile_id || "—"}</span>
                                <span class="ov-fwd-state">${state}</span>
                            </div>
                            <div class="ov-fwd-dest">${dest}</div>
                            <div class="ov-fwd-meta">${lastEv}${errLine}</div>
                        </div>`;
                    }).join("");
                }
            } catch (e) {
                console.warn("[Dashboard] fwd status fetch failed:", e);
            }
        };
        refreshFwdStrip();
        window.setInterval(refreshFwdStrip, 8000);
    }

    const systemShell = document.querySelector("[data-system-shell]");
    if (systemShell) {
        const tabs = Array.from(systemShell.querySelectorAll("[data-system-tab]"));
        const panels = Array.from(systemShell.querySelectorAll("[data-system-panel]"));

        const syncPanels = (tabId) => {
            tabs.forEach((tab) => {
                const isCurrent = tab.getAttribute("data-system-tab") === tabId;
                tab.classList.toggle("is-current", isCurrent);
                tab.setAttribute("aria-selected", isCurrent ? "true" : "false");
            });

            panels.forEach((panel) => {
                const panelId = panel.getAttribute("data-system-panel");
                const visible = panelId === tabId || panelId === `${tabId}-side`;
                panel.classList.toggle("is-hidden", !visible);
            });
        };

        tabs.forEach((tab) => {
            if (tab.hasAttribute("disabled")) {
                return;
            }
            tab.addEventListener("click", () => syncPanels(tab.getAttribute("data-system-tab")));
        });

        const initialTab = tabs.find((tab) => tab.classList.contains("is-current") && !tab.hasAttribute("disabled"))
            || tabs.find((tab) => !tab.hasAttribute("disabled"));
        if (initialTab) {
            syncPanels(initialTab.getAttribute("data-system-tab"));
        }

        const accessForm = systemShell.querySelector("[data-access-form]");
        const accessMessage = systemShell.querySelector("[data-access-message]");
        if (accessForm instanceof HTMLFormElement && accessMessage) {
            accessForm.addEventListener("submit", async (event) => {
                event.preventDefault();
                accessMessage.textContent = "";

                const formData = new FormData(accessForm);
                const payload = {
                    new_username: String(formData.get("new_username") || ""),
                    current_password: String(formData.get("current_password") || ""),
                    new_password: String(formData.get("new_password") || ""),
                    confirm_password: String(formData.get("confirm_password") || ""),
                };

                const button = accessForm.querySelector('button[type="submit"]');
                if (button instanceof HTMLButtonElement) {
                    button.disabled = true;
                    button.textContent = "Saving...";
                }

                try {
                    const response = await fetch("/api/system/access", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    });
                    const data = await response.json();
                    accessMessage.textContent = data.message || "Saved.";
                    accessMessage.classList.toggle("is-success", response.ok && data.ok);
                    if (!response.ok || !data.ok) {
                        throw new Error(data.message || "Could not update credentials.");
                    }
                    accessForm.reset();
                    const usernameField = accessForm.querySelector('input[name="current_username"]');
                    const newUsernameField = accessForm.querySelector('input[name="new_username"]');
                    if (usernameField instanceof HTMLInputElement) {
                        usernameField.value = payload.new_username;
                    }
                    if (newUsernameField instanceof HTMLInputElement) {
                        newUsernameField.value = payload.new_username;
                    }
                } catch (error) {
                    accessMessage.textContent = error instanceof Error ? error.message : "Could not update credentials.";
                    accessMessage.classList.remove("is-success");
                } finally {
                    if (button instanceof HTMLButtonElement) {
                        button.disabled = false;
                        button.textContent = "Save credentials";
                    }
                }
            });
        }

    }

    const connectivityShell = document.querySelector("[data-connectivity-shell]");
    if (connectivityShell) {
        const tabs = Array.from(connectivityShell.querySelectorAll("[data-network-tab]"));
        const panels = Array.from(connectivityShell.querySelectorAll("[data-network-panel]"));
        const networkForm = connectivityShell.querySelector("[data-network-form]");
        const networkMessage = connectivityShell.querySelector("[data-network-message]");
        const runtimeToggle = connectivityShell.querySelector("[data-network-runtime-toggle]");
        const runtimePanel = connectivityShell.querySelector("[data-network-runtime-panel]");
        const revertButton = connectivityShell.querySelector("[data-network-revert]");
        const saveButton = connectivityShell.querySelector("[data-network-save]");
        const saveApplyButton = connectivityShell.querySelector("[data-network-save-apply]");
        const scanButton = connectivityShell.querySelector("[data-network-scan]");
        const scanMessage = connectivityShell.querySelector("[data-network-scan-message]");
        const scanResults = connectivityShell.querySelector("[data-network-scan-results]");
        const runtimeWifiStatus = connectivityShell.querySelector("[data-runtime-wifi-status]");
        const runtimeWifiDetail = connectivityShell.querySelector("[data-runtime-wifi-detail]");
        const runtimeApStatus = connectivityShell.querySelector("[data-runtime-ap-status]");
        const runtimeApDetail = connectivityShell.querySelector("[data-runtime-ap-detail]");
        const runtimeApplyStatus = connectivityShell.querySelector("[data-runtime-apply-status]");
        const runtimeApplyTimestamp = connectivityShell.querySelector("[data-runtime-apply-timestamp]");
        const runtimeMonitorStatus = connectivityShell.querySelector("[data-runtime-monitor-status]");
        const runtimeMonitorDetail = connectivityShell.querySelector("[data-runtime-monitor-detail]");
        const wifiSubtabs = Array.from(connectivityShell.querySelectorAll("[data-wifi-subtab]"));
        const wifiSubpanels = Array.from(connectivityShell.querySelectorAll("[data-wifi-subpanel]"));

        // ── Status tab helpers ───────────────────────────────────────────────
        const _stFmt = (secs) => {
            if (!secs && secs !== 0) return "—";
            secs = Math.round(secs);
            if (secs < 60) return `${secs}s`;
            if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
            const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
            return `${h}h ${m}m`;
        };
        const _stFmtMs = (ms) => (ms || ms === 0) ? _stFmt(Math.round(ms / 1000)) : "—";
        const _stDateTime = (ms) => {
            if (!ms) return "—";
            try {
                return new Date(Number(ms)).toLocaleString([], {
                    year: "numeric", month: "2-digit", day: "2-digit",
                    hour: "2-digit", minute: "2-digit", second: "2-digit",
                });
            } catch (_) {
                return "—";
            }
        };
        const _stEsc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        }[ch]));
        // Short display name for interface cards
        const _stIfaceName = (key) =>
            key === "eth0" ? "Ethernet 0" : key === "eth1" ? "Ethernet 1"
          : key === "wifi_client" ? "Wi-Fi" : key === "cellular" ? "Cellular"
          : key === "none" ? "Offline" : (key || "—");

        // Full name for hero/failover labels
        const _stUplink = (key) =>
            key === "eth0" ? "Ethernet (eth0)" : key === "eth1" ? "Ethernet (eth1)"
          : key === "wifi_client" ? "Wi-Fi (wlan0)" : key === "cellular" ? "Cellular"
          : key === "none" ? "Offline" : (key || "—");

        // Determine real interface status by cross-referencing uplink_stats + network_state
        const _ifaceRealStatus = (key, uplinkStatus, activeUplink, state) => {
            if (key === activeUplink && uplinkStatus === "up") return { label: "Active",   cls: "is-active",   tone: "active" };
            if (uplinkStatus === "up")                         return { label: "Standby",  cls: "is-up",       tone: "standby" };
            if (uplinkStatus === "disabled")                   return { label: "Disabled", cls: "is-disabled", tone: "inactive" };
            // "down" — cross-reference actual link/connection state
            if (key === "eth0" || key === "eth1") {
                const l = key === "eth0" ? state?.eth0?.link_up : state?.eth1?.link_up;
                return l ? { label: "Up",      cls: "is-standby", tone: "standby" }
                         : { label: "No link", cls: "is-down",    tone: "inactive" };
            }
            if (key === "wifi_client") {
                const s = state?.wifi_client?.connected_ssid;
                return s ? { label: "Standby",      cls: "is-standby", tone: "standby" }
                         : { label: "Not connected", cls: "is-down",   tone: "inactive" };
            }
            if (key === "cellular") {
                const c = state?.cellular?.connected;
                const e = state?.cellular?.enabled;
                if (!e) return { label: "Off",     cls: "is-disabled", tone: "inactive" };
                return c ? { label: "Standby",     cls: "is-standby",  tone: "standby" }
                         : { label: "Offline",     cls: "is-down",     tone: "inactive" };
            }
            return { label: "Unknown", cls: "is-unknown", tone: "inactive" };
        };

        const renderStatusTab = (state) => {
            const uplinkStats  = state?.uplink_stats  || {};
            const tailscale    = state?.tailscale_recovery || {};
            const audit        = state?._audit || {};
            const auditStatus  = audit.status || {};
            const hasAudit     = Boolean(audit.status);
            const activeUplink = String(state?.active_uplink || "none");
            const network      = uplinkStats.network   || {};
            const ifaces       = uplinkStats.interfaces || {};
            const hasUplink    = auditStatus.has_uplink !== undefined
                ? Boolean(auditStatus.has_uplink)
                : network.has_uplink !== undefined ? Boolean(network.has_uplink) : activeUplink !== "none";

            // Detect if network monitor hasn't written data yet
            const monitorHasData = uplinkStats && (
                uplinkStats.started_epoch > 0 ||
                Object.keys(ifaces).length > 0 ||
                uplinkStats.switch_count !== undefined
            );

            // Hero — active uplink
            const nsActiveDot  = connectivityShell.querySelector("[data-ns-active-dot]");
            const nsActiveName = connectivityShell.querySelector("[data-ns-active-name]");
            const nsActiveSince= connectivityShell.querySelector("[data-ns-active-since]");
            const nsInternet   = connectivityShell.querySelector("[data-ns-internet]");
            const nsOutageNow  = connectivityShell.querySelector("[data-ns-current-outage]");
            const nsSwCount    = connectivityShell.querySelector("[data-ns-switch-count]");
            const nsLastOutage = connectivityShell.querySelector("[data-ns-last-outage]");

            if (nsActiveDot) nsActiveDot.className = "net-status-active-dot " + (hasUplink ? "is-active" : "is-none");
            if (nsActiveName) nsActiveName.textContent = _stUplink(activeUplink);
            if (nsActiveSince) {
                if (!monitorHasData) {
                    nsActiveSince.textContent = "Network monitor not running — check systemctl status gateway-network-monitor";
                    nsActiveSince.style.color = "var(--accent)";
                } else {
                    nsActiveSince.style.color = "";
                    nsActiveSince.textContent = hasAudit && audit.active_duration_ms !== undefined && activeUplink !== "none"
                        ? `Active since ${_stDateTime(audit.active_uplink_since_ms)} (${_stFmtMs(audit.active_duration_ms)})`
                        : !hasAudit ? "Waiting for AES audit sample"
                        : activeUplink === "none" ? "No active uplink detected" : "";
                }
            }
            // Internet reachability — cross-reference all interfaces (eth0, eth1, wifi_client, cellular).
            // Only show "Unavailable" if the monitor explicitly tested and failed.
            // If internet_ok is absent from all interfaces, monitor hasn't tested yet → show "Not checked".
            const eth0    = state?.eth0         ?? {};
            const eth1    = state?.eth1         ?? {};
            const wifi    = state?.wifi_client  ?? {};
            const cel     = state?.cellular     ?? {};
            const monitorTestedInternet = "internet_ok" in eth0
                || "internet_ok" in eth1
                || "internet_ok" in wifi
                || "internet_ok" in cel;
            const internetOk = eth0.internet_ok || eth1.internet_ok
                || wifi.internet_ok || cel.internet_ok
                || Boolean(cel.connected);
            if (nsInternet) {
                if (!monitorTestedInternet) {
                    nsInternet.textContent = "Not checked";
                    nsInternet.style.color = "var(--muted)";
                } else {
                    nsInternet.textContent = internetOk ? "Available" : "Unavailable";
                    nsInternet.style.color = internetOk ? "var(--success)" : "#f87171";
                }
            }
            const auditOpenOutage = audit.open_outage || null;
            const outageNow = auditOpenOutage ? Math.round((auditOpenOutage.duration_ms || 0) / 1000) : 0;
            if (nsOutageNow) {
                nsOutageNow.textContent = outageNow > 0 ? _stFmt(outageNow) : "None";
                nsOutageNow.style.color = outageNow > 0 ? "#f87171" : "";
            }
            const auditSwitches = audit.uplink_switch_count ?? audit.counts?.uplink_switches;
            if (nsSwCount) {
                const swCount = auditSwitches ?? uplinkStats.switch_count ?? 0;
                nsSwCount.textContent = String(swCount) + (swCount ? " switches" : "");
            }
            if (nsLastOutage) {
                const lastMs = audit.last_outage?.duration_ms;
                nsLastOutage.textContent = lastMs ? _stFmtMs(lastMs) : "None";
            }

            // Interface cards
            const nsIfaceGrid = connectivityShell.querySelector("[data-ns-iface-grid]");
            if (nsIfaceGrid) {
                // Ordered: show known interfaces in priority order
                const ifaceOrder = ["eth0", "eth1", "wifi_client", "cellular"];
                const allKeys = [...new Set([...ifaceOrder, ...Object.keys(ifaces)])];
                const cards = allKeys.map((key) => {
                    const iface  = ifaces[key] || {};
                    const st     = iface.status || "unknown";
                    const rslt   = _ifaceRealStatus(key, st, activeUplink, state);
                    const name   = _stUplink(key);
                    const isActive = key === activeUplink;

                    // Extra context per interface
                    let extraLines = "";
                    const _wifiReason = (r) => ({
                        scanning: "Scanning for network",
                        disconnected: "Disconnected",
                        authenticating: "Authenticating",
                        associating: "Associating with AP",
                        waiting_for_ip: "Waiting for IP",
                        connected_no_internet: "Connected, no internet",
                        supplicant_inactive: "Supplicant not running",
                        interface_missing: "Interface not found",
                        interface_disabled: "Interface disabled",
                        ssid_missing: "No SSID configured",
                        disabled: "Wi-Fi disabled",
                    }[r] || r || "");
                    if (key === "eth0" || key === "eth1") {
                        const eth = state?.[key] || {};
                        if (eth.address)   extraLines += `<div class="ns-iface-extra"><span>IPv4</span><strong>${eth.address}</strong></div>`;
                        if (eth.internet_ok) extraLines += `<div class="ns-iface-extra"><span>Internet</span><strong style="color:var(--success)">Reachable</strong></div>`;
                        if (iface.last_ready === false) extraLines += `<div class="ns-iface-extra is-warn"><span>Probe</span><strong>Last probe failed</strong></div>`;
                    } else if (key === "wifi_client") {
                        const wc = state?.wifi_client || {};
                        const diag = wc.diagnostics || {};
                        if (wc.configured_ssid) extraLines += `<div class="ns-iface-extra"><span>Target SSID</span><strong>${wc.configured_ssid}</strong></div>`;
                        if (wc.connected_ssid) {
                            extraLines += `<div class="ns-iface-extra"><span>Connected SSID</span><strong style="color:var(--success)">${wc.connected_ssid}</strong></div>`;
                        } else if (diag.reason && diag.reason !== "disabled") {
                            const isWarn = !["connected_internet_ok"].includes(diag.reason);
                            extraLines += `<div class="ns-iface-extra${isWarn ? " is-warn" : ""}"><span>Reason</span><strong>${_wifiReason(diag.reason)}</strong></div>`;
                        }
                        if (wc.address) extraLines += `<div class="ns-iface-extra"><span>IPv4</span><strong>${wc.address}</strong></div>`;
                        if (diag.supplicant_state && diag.supplicant_state !== "COMPLETED") {
                            extraLines += `<div class="ns-iface-extra"><span>Supplicant</span><strong>${diag.supplicant_state}</strong></div>`;
                        }
                        if (diag.signal_dbm) extraLines += `<div class="ns-iface-extra"><span>Signal</span><strong>${diag.signal_dbm} dBm</strong></div>`;
                    } else if (key === "cellular") {
                        const cel = state?.cellular || {};
                        if (cel.operator) extraLines += `<div class="ns-iface-extra"><span>Operator</span><strong>${cel.operator}</strong></div>`;
                        if (cel.signal_percent != null) {
                            const q = cel.signal_percent >= 80 ? "Strong" : cel.signal_percent >= 60 ? "Good" : cel.signal_percent >= 40 ? "Fair" : cel.signal_percent >= 20 ? "Weak" : "Poor";
                            const dbmStr = cel.signal_dbm != null ? ` · ${cel.signal_dbm} dBm` : "";
                            extraLines += `<div class="ns-iface-extra"><span>Signal</span><strong>${q} (${cel.signal_percent}%${dbmStr})</strong></div>`;
                        }
                        if (cel.access_technology) extraLines += `<div class="ns-iface-extra"><span>Technology</span><strong>${cel.access_technology}</strong></div>`;
                    }
                    // Show last_ready / eligible from uplink_stats
                    if (iface.eligible === false && iface.last_ready === true) {
                        extraLines += `<div class="ns-iface-extra"><span>Recovery</span><strong>Waiting for threshold</strong></div>`;
                    }

                    // Stats from uplink_stats — contextual labels to avoid confusion
                    const downNow  = iface.current_down_seconds || 0;
                    const totalDn  = iface.total_down_seconds   || 0;
                    const downEvts = iface.down_events          || 0;

                    // "current_down_seconds" means "not eligible as active route" — not modem/link offline.
                    // It accumulates while the interface is in "not eligible" state, which for cellular
                    // includes standby time (modem connected but eth0 is active). So if cellular was
                    // standby for 2h and then the modem disconnected, the timer shows 2h+5m, not 5m.
                    // Therefore: never use this timer for cellular. Show modem state explicitly instead.
                    const celConnected = key === "cellular" && Boolean(state?.cellular?.connected);
                    const celEnabled   = key === "cellular" && Boolean(state?.cellular?.enabled);
                    const wifiAssociated = key === "wifi_client" && Boolean(state?.wifi_client?.connected_ssid);
                    const ethLinkUp    = (key === "eth0" && Boolean(state?.eth0?.link_up))
                                      || (key === "eth1" && Boolean(state?.eth1?.link_up));

                    let downLine = "";
                    if (key === "cellular") {
                        // Never show cumulative timer for cellular (includes standby time, misleading).
                        // Instead show modem connectivity state as a detail line if offline.
                        if (!celConnected && celEnabled) {
                            downLine = `<div class="ns-iface-extra is-warn"><span>Modem</span><strong>Offline / disconnected</strong></div>`;
                        }
                        // If connected: no extra line (status badge already says "Standby" or "Active Uplink")
                    } else if (downNow > 0) {
                        if (wifiAssociated || (isActive && ethLinkUp)) {
                            // Genuinely up — don't show
                        } else if (ethLinkUp && !isActive) {
                            // Cable plugged in but not the active route
                            downLine = `<div class="ns-iface-extra"><span>Not routing for</span><strong>${_stFmt(downNow)}</strong></div>`;
                        } else {
                            // Truly unavailable: no link / not associated
                            downLine = `<div class="ns-iface-extra is-warn"><span>Unavailable for</span><strong>${_stFmt(downNow)}</strong></div>`;
                        }
                    }

                    const statsLines = [
                        downLine,
                        downEvts > 0 ? `<div class="ns-iface-extra"><span>Down events</span><strong>${downEvts}</strong></div>` : "",
                        totalDn > 0 && !celConnected ? `<div class="ns-iface-extra"><span>Total downtime</span><strong>${_stFmt(totalDn)}</strong></div>` : "",
                    ].filter(Boolean).join("");

                    const dotCls   = rslt.tone === "active" ? "is-active" : rslt.tone === "standby" ? "is-standby" : "is-inactive";
                    const cardName = _stIfaceName(key);   // short: "Ethernet 0", "Wi-Fi", etc.
                    return `<article class="ns-iface-card ${isActive ? "is-active-uplink" : ""}">
                        <div class="ns-iface-head">
                            <div class="ns-iface-head-left">
                                <span class="ns-iface-dot connectivity-badge ${dotCls}"></span>
                                <span class="ns-iface-name">${cardName}</span>
                            </div>
                            <div class="ns-iface-head-right">
                                ${isActive ? `<span class="ns-active-pill">Active</span>` : ""}
                                <span class="ns-iface-status-badge ns-status-${rslt.tone}">${rslt.label}</span>
                            </div>
                        </div>
                        <div class="ns-iface-details">${extraLines}${statsLines}</div>
                    </article>`;
                }).join("");
                nsIfaceGrid.innerHTML = cards || (monitorHasData
                    ? `<p class="insights-empty-note">No interface data available yet.</p>`
                    : `<p class="insights-empty-note" style="color:var(--accent)">Network monitor has not written data yet. Run: <code>systemctl status gateway-network-monitor</code></p>`);
            }

            // Last failover
            const nsFailover = connectivityShell.querySelector("[data-ns-failover-detail]");
            if (nsFailover) {
                const sw = auditSwitches ?? uplinkStats.switch_count ?? 0;
                const auditSwitch = audit.last_switch || null;
                const ls = uplinkStats.last_switch  || {};
                if (auditSwitch) {
                    nsFailover.innerHTML = `
                        <div class="ns-stat-grid">
                            <div class="ns-stat-row"><span>Uplink switches (total)</span><strong>${sw}</strong></div>
                            <div class="ns-stat-row"><span>From</span><strong>${_stUplink(auditSwitch.previous_uplink)}</strong></div>
                            <div class="ns-stat-row"><span>To</span><strong>${_stUplink(auditSwitch.active_uplink)}</strong></div>
                            <div class="ns-stat-row"><span>Completed</span><strong>${_stDateTime(auditSwitch.timestamp_ms)}</strong></div>
                            ${auditSwitch.reason ? `<div class="ns-stat-row ns-stat-row-full"><span>Reason</span><strong>${_stEsc(auditSwitch.reason).replace(/_/g," ")}</strong></div>` : ""}
                        </div>`;
                } else if (!hasAudit && sw > 0 && ls.from) {
                    nsFailover.innerHTML = `
                        <div class="ns-stat-grid">
                            <div class="ns-stat-row"><span>Uplink switches (total)</span><strong>${sw}</strong></div>
                            <div class="ns-stat-row"><span>From</span><strong>${_stUplink(ls.from)}</strong></div>
                            <div class="ns-stat-row"><span>To</span><strong>${_stUplink(ls.to)}</strong></div>
                            ${ls.duration_seconds !== undefined ? `<div class="ns-stat-row"><span>Duration</span><strong>${ls.duration_seconds}s</strong></div>` : ""}
                            ${ls.completed_timestamp ? `<div class="ns-stat-row"><span>Completed</span><strong>${ls.completed_timestamp.replace("T"," ").slice(0,16)}</strong></div>` : ""}
                            ${ls.reason ? `<div class="ns-stat-row ns-stat-row-full"><span>Reason</span><strong>${ls.reason.replace(/_/g," ")}</strong></div>` : ""}
                        </div>`;
                } else {
                    nsFailover.innerHTML = `<p class="insights-empty-note">No failover recorded since monitor started.</p>`;
                }
            }

            // Network outage
            const nsOutage = connectivityShell.querySelector("[data-ns-outage-detail]");
            if (nsOutage) {
                const lastDnMs = audit.last_outage?.duration_ms;
                const totDnMs  = audit.total_downtime_ms;
                const dnEvts = audit.counts?.outage_starts ?? 0;
                nsOutage.innerHTML = `
                    <div class="ns-stat-grid">
                        <div class="ns-stat-row"><span>Network status</span><strong style="color:${hasUplink?"var(--success)":"#f87171"}">${hasUplink?"Uplink available":"No uplink"}</strong></div>
                        ${outageNow > 0 ? `<div class="ns-stat-row is-warn"><span>Current outage</span><strong>${_stFmt(outageNow)}</strong></div>` : ""}
                        ${audit.last_outage?.started_at_ms ? `<div class="ns-stat-row"><span>Last outage started</span><strong>${_stDateTime(audit.last_outage.started_at_ms)}</strong></div>` : ""}
                        ${audit.last_outage?.ended_at_ms ? `<div class="ns-stat-row"><span>Last outage recovered</span><strong>${_stDateTime(audit.last_outage.ended_at_ms)}</strong></div>` : ""}
                        <div class="ns-stat-row"><span>Last outage duration</span><strong>${lastDnMs ? _stFmtMs(lastDnMs) : "None"}</strong></div>
                        <div class="ns-stat-row"><span>Total downtime</span><strong>${totDnMs ? _stFmtMs(totDnMs) : "0s"}</strong></div>
                        <div class="ns-stat-row"><span>Down events</span><strong>${dnEvts}</strong></div>
                    </div>`;
            }

            // Tailscale recovery
            const nsTailscale = connectivityShell.querySelector("[data-ns-tailscale-detail]");
            if (nsTailscale) {
                const count = audit.counts?.recovery_actions ?? tailscale.count ?? 0;
                const lastRecovery = audit.last_recovery || null;
                if (lastRecovery) {
                    nsTailscale.innerHTML = `
                        <div class="ns-stat-grid">
                            <div class="ns-stat-row"><span>Recovery count</span><strong>${count}</strong></div>
                            <div class="ns-stat-row"><span>Last recovery</span><strong>${_stDateTime(lastRecovery.timestamp_ms)}</strong></div>
                            ${lastRecovery.reason ? `<div class="ns-stat-row ns-stat-row-full"><span>Reason</span><strong>${_stEsc(lastRecovery.reason)}</strong></div>` : ""}
                        </div>`;
                } else if (!hasAudit && count > 0) {
                    nsTailscale.innerHTML = `
                        <div class="ns-stat-grid">
                            <div class="ns-stat-row"><span>Recovery count</span><strong>${count}</strong></div>
                            ${tailscale.last_timestamp ? `<div class="ns-stat-row"><span>Last recovery</span><strong>${tailscale.last_timestamp.replace("T"," ").slice(0,16)}</strong></div>` : ""}
                            ${tailscale.last_reason ? `<div class="ns-stat-row ns-stat-row-full"><span>Reason</span><strong>${tailscale.last_reason}</strong></div>` : ""}
                        </div>`;
                } else {
                    nsTailscale.innerHTML = `<p class="insights-empty-note">No Tailscale recovery events recorded.</p>`;
                }
            }
        };

        const renderNetworkAudit = (payload) => {
            const summaryEl = connectivityShell.querySelector("[data-net-audit-summary]");
            const listEl = connectivityShell.querySelector("[data-net-audit-list]");
            if (!summaryEl && !listEl) return;

            const summary = payload?.summary || {};
            const counts = summary.counts || {};
            const events = Array.isArray(payload?.events) ? payload.events : [];
            const open = summary.open_outage || null;
            const totalMs = (summary.total_downtime_ms || 0) + (open?.duration_ms || 0);

            if (summaryEl) {
                summaryEl.innerHTML = `
                    <div class="fw-audit-stat"><strong>${counts.outage_starts || 0}</strong><span>Gateway outages</span></div>
                    <div class="fw-audit-stat"><strong>${counts.interface_issues || 0}</strong><span>Interface issues</span></div>
                    <div class="fw-audit-stat"><strong>${counts.uplink_switches || 0}</strong><span>Uplink switches</span></div>
                    <div class="fw-audit-stat"><strong>${_stFmtMs(totalMs)}</strong><span>Total downtime</span></div>
                `;
            }

            if (!listEl) return;
            if (!events.length) {
                listEl.innerHTML = `<p class="fw-audit-empty">No connectivity audit events in selected window.</p>`;
                return;
            }

            const label = (type) => ({
                outage_started: "Outage started",
                outage_recovered: "Outage recovered",
                uplink_switch: "Uplink switch",
                recovery_action: "Recovery action",
                tailscale_recovery: "Tailscale recovery",
                interface_issue_started: "Interface issue started",
                interface_issue_changed: "Interface issue changed",
                interface_recovered: "Interface recovered",
            }[type] || String(type || "Event").replace(/_/g, " "));

            listEl.innerHTML = events.map((event) => {
                const sev = String(event.severity || "info").toLowerCase();
                const rowCls = sev === "error" || sev === "critical" ? "is-err" : sev === "warning" ? "is-warn" : "";
                const when = event.timestamp_utc || _stDateTime(event.timestamp_ms);
                const type = label(event.event_type);
                const uplinkBits = [];
                if (event.previous_uplink) uplinkBits.push(`from ${_stUplink(event.previous_uplink)}`);
                if (event.active_uplink) uplinkBits.push(`to ${_stUplink(event.active_uplink)}`);
                const meta = uplinkBits.join(" ");
                const duration = event.duration || (event.duration_ms ? _stFmtMs(event.duration_ms) : "");
                return `<article class="fw-audit-row ${rowCls}">
                    <div class="fw-audit-time">
                        <strong>${_stEsc(when)}</strong>
                        <span>${event.started_at_utc ? `Start ${_stEsc(event.started_at_utc)}` : ""}</span>
                    </div>
                    <div class="fw-audit-main">
                        <div class="fw-audit-head">
                            <span class="fw-audit-type">${_stEsc(type)}</span>
                            ${meta ? `<span class="fw-audit-profile">${_stEsc(meta)}</span>` : ""}
                            <span class="fw-audit-sev">${_stEsc(sev)}</span>
                        </div>
                        ${event.reason ? `<p class="fw-audit-reason">${_stEsc(event.reason)}</p>` : ""}
                        ${duration ? `<span class="fw-audit-duration">Duration ${_stEsc(duration)}</span>` : ""}
                        ${event.message ? `<span class="fw-audit-meta">${_stEsc(event.message)}</span>` : ""}
                    </div>
                </article>`;
            }).join("");
        };

        const refreshNetworkAudit = async () => {
            const win = connectivityShell.querySelector("[data-net-audit-window]")?.value || "7d";
            const exportLink = connectivityShell.querySelector("[data-net-audit-export]");
            if (exportLink) exportLink.href = `/api/network/events/export/csv?window=${encodeURIComponent(win)}`;
            try {
                const r = await fetch(`/api/network/events?window=${encodeURIComponent(win)}&limit=100`);
                if (!r.ok) return;
                renderNetworkAudit(await r.json());
            } catch (e) {
                console.warn("[Status] network audit fetch failed:", e);
            }
        };

        const refreshStatusTab = async () => {
            try {
                const r = await fetch("/api/network/state");
                if (!r.ok) return;
                renderStatusTab(await r.json());
                refreshNetworkAudit();
            } catch (e) {
                console.warn("[Status] network state fetch failed:", e);
            }
        };

        const syncWifiSubpanels = (tabId) => {
            wifiSubtabs.forEach((tab) => {
                const isCurrent = tab.getAttribute("data-wifi-subtab") === tabId;
                tab.classList.toggle("is-current", isCurrent);
                tab.setAttribute("aria-selected", isCurrent ? "true" : "false");
            });

            wifiSubpanels.forEach((panel) => {
                const visible = panel.getAttribute("data-wifi-subpanel") === tabId;
                panel.classList.toggle("is-hidden", !visible);
            });
        };

        let cellularRefreshTimer = null;
        let statusRefreshTimer   = null;

        const networkActionRow = connectivityShell.querySelector(".network-action-row");

        const syncNetworkPanels = (tabId) => {
            tabs.forEach((tab) => {
                const isCurrent = tab.getAttribute("data-network-tab") === tabId;
                tab.classList.toggle("is-current", isCurrent);
                tab.setAttribute("aria-selected", isCurrent ? "true" : "false");
            });

            panels.forEach((panel) => {
                const visible = panel.getAttribute("data-network-panel") === tabId;
                panel.classList.toggle("is-hidden", !visible);
            });

            // Hide save/apply buttons on Status tab (read-only)
            if (networkActionRow) {
                networkActionRow.style.display = tabId === "status" ? "none" : "";
            }

            if (tabId === "wifi" && wifiSubtabs.length > 0) {
                syncWifiSubpanels("client");
            }

            // Auto-refresh cellular status while on the cellular tab
            clearInterval(cellularRefreshTimer);
            if (tabId === "cellular") {
                refreshCellularStatus();
                cellularRefreshTimer = setInterval(refreshCellularStatus, 5000);
            }

            // Auto-refresh status tab
            clearInterval(statusRefreshTimer);
            if (tabId === "status") {
                refreshStatusTab();
                statusRefreshTimer = setInterval(refreshStatusTab, 5000);
            }
        };

        tabs.forEach((tab) => {
            if (tab.hasAttribute("disabled")) {
                return;
            }
            tab.addEventListener("click", () => syncNetworkPanels(tab.getAttribute("data-network-tab")));
        });
        connectivityShell.querySelector("[data-net-audit-window]")?.addEventListener("change", refreshNetworkAudit);

        const initialTab = tabs.find((tab) => tab.classList.contains("is-current") && !tab.hasAttribute("disabled"))
            || tabs.find((tab) => !tab.hasAttribute("disabled"));
        if (initialTab) {
            syncNetworkPanels(initialTab.getAttribute("data-network-tab"));
        }

        wifiSubtabs.forEach((tab) => {
            tab.addEventListener("click", () => syncWifiSubpanels(tab.getAttribute("data-wifi-subtab")));
        });
        if (wifiSubtabs.length > 0) {
            syncWifiSubpanels("client");
        }

        const syncConditionalFields = () => {
            if (!(networkForm instanceof HTMLFormElement)) {
                return;
            }
            const ethernetDhcp = networkForm.elements.namedItem("ethernet_dhcp");
            const wifiClientDhcp = networkForm.elements.namedItem("wifi_client_dhcp");
            const wifiApDhcp = networkForm.elements.namedItem("wifi_ap_dhcp_server_enabled");

            const conditions = {
                "ethernet-static": !(ethernetDhcp instanceof HTMLInputElement && ethernetDhcp.checked),
                "wifi-client-static": !(wifiClientDhcp instanceof HTMLInputElement && wifiClientDhcp.checked),
                "wifi-ap-dhcp": wifiApDhcp instanceof HTMLInputElement && wifiApDhcp.checked,
            };

            const conditionalFields = Array.from(connectivityShell.querySelectorAll("[data-network-visible-when]"));
            conditionalFields.forEach((field) => {
                const key = field.getAttribute("data-network-visible-when");
                field.classList.toggle("is-hidden", !conditions[key]);
            });
        };

        if (networkForm instanceof HTMLFormElement) {
            networkForm.addEventListener("change", syncConditionalFields);
            syncConditionalFields();
        }

        if (runtimeToggle && runtimePanel) {
            runtimeToggle.addEventListener("click", () => {
                const isHidden = runtimePanel.classList.toggle("is-hidden");
                runtimeToggle.textContent = isHidden ? "Show Runtime State" : "Hide Runtime State";
            });
        }

        if (revertButton) {
            revertButton.addEventListener("click", () => window.location.reload());
        }

        const parseDns = (value) =>
            String(value || "")
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean);

        const parseTargets = (value) =>
            String(value || "")
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean);

        const buildNetworkPayload = () => {
            if (!(networkForm instanceof HTMLFormElement)) {
                return null;
            }

            const formData = new FormData(networkForm);
            return {
                version: 2,
                network: {
                    defaults_behavior: {
                        create_defaults_if_missing: true,
                        restore_defaults_if_invalid: true,
                        backup_invalid_file: true,
                    },
                    wifi_client: {
                        enabled: formData.get("wifi_client_enabled") === "on",
                        interface: String(formData.get("wifi_client_interface") || "wlan0"),
                        auto_connect: formData.get("wifi_client_auto_connect") === "on",
                        ssid: String(formData.get("wifi_client_ssid") || "").trim(),
                        hidden_ssid: formData.get("wifi_client_hidden_ssid") === "on",
                        security: String(formData.get("wifi_client_security") || "wpa2-psk"),
                        passphrase: String(formData.get("wifi_client_passphrase") || ""),
                        country_code: String(formData.get("wifi_client_country_code") || "").trim().toUpperCase(),
                        band: String(formData.get("wifi_client_band") || "auto"),
                        dhcp: formData.get("wifi_client_dhcp") === "on",
                        static_address: String(formData.get("wifi_client_static_address") || "").trim(),
                        static_gateway: String(formData.get("wifi_client_static_gateway") || "").trim(),
                        static_dns: parseDns(formData.get("wifi_client_static_dns")),
                        route_metric: Number.parseInt(String(formData.get("wifi_client_route_metric") || "200"), 10),
                        uplink_allowed: true,
                    },
                    wifi_ap: {
                        enabled: formData.get("wifi_ap_enabled") === "on",
                        interface: String(formData.get("wifi_ap_interface") || "wlan0"),
                        ssid: String(formData.get("wifi_ap_ssid") || "").trim(),
                        security: String(formData.get("wifi_ap_security") || "wpa2-psk"),
                        passphrase: String(formData.get("wifi_ap_passphrase") || ""),
                        country_code: String(formData.get("wifi_ap_country_code") || "").trim().toUpperCase(),
                        band: String(formData.get("wifi_ap_band") || "2.4ghz"),
                        channel: String(formData.get("wifi_ap_channel") || "auto").trim(),
                        channel_width: "20",
                        subnet_cidr: String(formData.get("wifi_ap_subnet_cidr") || "").trim(),
                        dhcp_server_enabled: formData.get("wifi_ap_dhcp_server_enabled") === "on",
                        dhcp_range_start: String(formData.get("wifi_ap_dhcp_range_start") || "").trim(),
                        dhcp_range_end: String(formData.get("wifi_ap_dhcp_range_end") || "").trim(),
                        nat_enabled: formData.get("wifi_ap_nat_enabled") === "on",
                        client_isolation: formData.get("wifi_ap_client_isolation") === "on",
                        shared_uplink_mode: String(formData.get("wifi_ap_shared_uplink_mode") || "auto"),
                    },
                    cellular: {
                        enabled:         formData.get("cellular_enabled") === "on",
                        active_modem_id: "sim7600",
                        apn:             String(formData.get("cellular_apn")      || "").trim(),
                        username:        String(formData.get("cellular_username") || "").trim(),
                        password:        String(formData.get("cellular_password") || ""),
                        pin:             String(formData.get("cellular_pin")      || "").trim(),
                        roaming_allowed: formData.get("cellular_roaming_allowed") === "on",
                        modems: [
                            {
                                id:               "sim7600",
                                enabled:          true,
                                backend:          "qmi",
                                interface_type:   "qmi",
                                control_device:   "/dev/cdc-wdm0",
                                data_interface:   "wwan0",
                                route_metric:     500,
                                ip_type:          "4",
                            },
                        ],
                    },
                    uplink: {
                        uplink_priority: [
                            String(formData.get("uplink_priority_1") || "eth0"),
                            String(formData.get("uplink_priority_2") || "eth1"),
                            String(formData.get("uplink_priority_3") || "wifi_client"),
                            String(formData.get("uplink_priority_4") || "cellular"),
                        ],
                        failback_enabled: formData.get("uplink_failback_enabled") === "on",
                        stable_seconds_before_switch: Number.parseInt(String(formData.get("uplink_stable_seconds_before_switch") || "0"), 10),
                        require_connectivity_check: formData.get("uplink_require_connectivity_check") === "on",
                        fail_count_threshold: Number.parseInt(String(formData.get("uplink_fail_count_threshold") || "1"), 10),
                        recover_count_threshold: Number.parseInt(String(formData.get("uplink_recover_count_threshold") || "1"), 10),
                        connectivity_targets: parseTargets(formData.get("uplink_connectivity_targets") || "1.1.1.1, 8.8.8.8"),
                    },
                },
            };
        };

        const validateNetworkPayload = (payload) => {
            const wifiClientEnabled = Boolean(payload?.network?.wifi_client?.enabled);
            const wifiApEnabled = Boolean(payload?.network?.wifi_ap?.enabled);
            const sharedUplinkMode = String(payload?.network?.wifi_ap?.shared_uplink_mode || "auto");

            if (wifiClientEnabled && wifiApEnabled) {
                return "Current gateway image supports either Wi-Fi client or Wi-Fi AP on wlan0, not both at the same time.";
            }

            if (!["auto", "ethernet", "eth0"].includes(sharedUplinkMode)) {
                return "Current gateway image supports Wi-Fi AP sharing only through Ethernet or Auto.";
            }

            return "";
        };

        const updateRuntimeState = (networkState, applyResult) => {
            const runtimeEth0Status = connectivityShell.querySelector("[data-runtime-eth0-status]");
            const runtimeEth0Address = connectivityShell.querySelector("[data-runtime-eth0-address]");
            const runtimeEth1Status = connectivityShell.querySelector("[data-runtime-eth1-status]");
            const runtimeEth1Address = connectivityShell.querySelector("[data-runtime-eth1-address]");
            if (runtimeEth0Status) runtimeEth0Status.textContent = networkState?.eth0?.link_up ? "Link up" : "Link down";
            if (runtimeEth0Address) runtimeEth0Address.textContent = networkState?.eth0?.address || "No address";
            if (runtimeEth1Status) runtimeEth1Status.textContent = networkState?.eth1?.link_up ? "Link up" : "Link down";
            if (runtimeEth1Address) runtimeEth1Address.textContent = networkState?.eth1?.address || "No address";

            if (runtimeWifiStatus) {
                runtimeWifiStatus.textContent = networkState?.wifi_client?.connected_ssid ? "Connected" : "Disconnected";
            }
            if (runtimeWifiDetail) {
                const wifiBase = networkState?.wifi_client?.connected_ssid || networkState?.wifi_client?.address || "No active SSID";
                const wifiInternet = networkState?.wifi_client?.internet_ok ? "Internet OK" : "Internet pending";
                const wifiText = networkState?.wifi_client?.connected_ssid || networkState?.wifi_client?.address
                    ? `${wifiBase} · ${wifiInternet}`
                    : wifiBase;
                runtimeWifiDetail.textContent = wifiText;
            }

            if (runtimeApStatus) {
                runtimeApStatus.textContent = networkState?.wifi_ap?.enabled ? "Enabled" : "Disabled";
            }
            if (runtimeApDetail) {
                runtimeApDetail.textContent = `${networkState?.wifi_ap?.clients ?? 0} client(s)`;
            }

            if (runtimeApplyStatus) {
                const statusText = String(applyResult?.status || "unknown").replaceAll("_", " ");
                runtimeApplyStatus.textContent = statusText.charAt(0).toUpperCase() + statusText.slice(1);
            }
            if (runtimeApplyTimestamp) {
                runtimeApplyTimestamp.textContent = applyResult?.timestamp || "No apply run yet";
            }

            if (runtimeMonitorStatus) {
                const statusText = String(networkState?.monitor_status || "unknown").replaceAll("_", " ");
                runtimeMonitorStatus.textContent = statusText.charAt(0).toUpperCase() + statusText.slice(1);
            }
            if (runtimeMonitorDetail) {
                const recovery = networkState?.recovery || {};
                runtimeMonitorDetail.textContent = recovery?.last_reason
                    ? `Recovery ${recovery.count ?? 0} · ${recovery.last_reason}`
                    : "No recovery action recorded";
            }

            // ── Cellular status ──────────────────────────────────────────────
            updateCellularStatus(networkState?.cellular || null, networkState?.active_uplink);
        };

        const _celStat = (key) => connectivityShell.querySelector(`[data-cel-stat="${key}"]`);
        const _celSet   = (key, val) => { const el = _celStat(key); if (el) el.textContent = val ?? "—"; };

        const _fmtBytes = (bytes) => {
            if (!bytes || bytes === 0) return "0 B";
            const units = ["B","KB","MB","GB"];
            let b = Number(bytes), i = 0;
            while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
            return `${b.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
        };

        const _celFmtTs = (ts) => {
            if (!ts) return "—";
            try { return new Date(ts).toLocaleString(); } catch { return ts; }
        };

        const updateCellularStatus = (cel, activeUplink) => {
            if (!connectivityShell.querySelector("[data-cellular-status-grid]")) return;
            const allKeys = [
                "present","modem_hardware","sim_status","operator","signal",
                "registration_state","registered","roaming","access_tech",
                "connected","internet_ok","address","gateway","dns","active_uplink",
                "session_usage","total_usage","last_connect","last_disconnect",
            ];
            if (!cel) {
                allKeys.forEach((k) => _celSet(k, "—"));
                return;
            }

            _celSet("present", cel.present ? "Yes — SIM7600 detected" : "No modem detected");

            // Modem hardware: manufacturer / model / revision
            const hw = [cel.modem_manufacturer, cel.modem_model, cel.modem_revision]
                .filter(Boolean).join(" / ");
            _celSet("modem_hardware", hw || (cel.present ? "—" : "Not detected"));

            _celSet("sim_status", ({
                ready:   "Ready",
                locked:  "Locked (PIN required)",
                missing: "No SIM inserted",
                error:   "SIM error",
            }[cel.sim_status] || cel.sim_status || "—"));

            _celSet("operator", cel.operator || (cel.registered ? "Unknown operator" : "—"));

            // Signal: dBm + percent
            const sigParts = [];
            if (cel.signal_dbm !== undefined && cel.signal_dbm !== null && cel.signal_dbm !== 0)
                sigParts.push(`${cel.signal_dbm} dBm`);
            if (cel.signal_percent !== undefined && cel.signal_percent !== null)
                sigParts.push(`${cel.signal_percent}%`);
            _celSet("signal", sigParts.length ? sigParts.join("  ") : "—");

            _celSet("registration_state", cel.registration_state || "—");
            _celSet("registered",  cel.registered ? "Yes" : "No");
            _celSet("roaming",     cel.roaming    ? "Yes (roaming)" : cel.registered ? "No" : "—");
            _celSet("access_tech", cel.access_technology || "—");

            _celSet("connected",   cel.connected   ? "Yes" : "No");
            _celSet("internet_ok", cel.internet_ok ? "✓ Reachable" : cel.connected ? "✗ No route" : "—");
            _celSet("address",     cel.address || "—");
            _celSet("gateway",     cel.gateway || "—");
            _celSet("dns",         Array.isArray(cel.dns) && cel.dns.length ? cel.dns.join(", ") : "—");
            _celSet("active_uplink", activeUplink === "cellular" ? "Cellular (active)" : activeUplink || "—");

            const sRx = cel.session_rx_bytes ?? 0;
            const sTx = cel.session_tx_bytes ?? 0;
            const tRx = cel.rx_bytes ?? 0;
            const tTx = cel.tx_bytes ?? 0;
            _celSet("session_usage", `↓ ${_fmtBytes(sRx)}  ↑ ${_fmtBytes(sTx)}`);
            _celSet("total_usage",   `↓ ${_fmtBytes(tRx)}  ↑ ${_fmtBytes(tTx)}`);

            _celSet("last_connect",    _celFmtTs(cel.last_connect_timestamp));
            _celSet("last_disconnect", _celFmtTs(cel.last_disconnect_timestamp));

            const errRow = connectivityShell.querySelector("[data-cel-error-row]");
            if (errRow) {
                const hasErr = !!(cel.last_error);
                errRow.style.display = hasErr ? "" : "none";
                if (hasErr) _celSet("last_error", cel.last_error);
            }

            // Retry status — only shown when there have been connection attempts
            const retry = (typeof cel.retry === "object" && cel.retry !== null) ? cel.retry : null;
            const retryRows = connectivityShell.querySelectorAll("[data-cel-retry-row]");
            const hasRetry  = retry && (retry.attempt_count > 0 || retry.last_result);
            retryRows.forEach((r) => { r.style.display = hasRetry ? "" : "none"; });
            if (hasRetry) {
                _celSet("retry_count", `${retry.attempt_count ?? 0} attempt(s)`);
                _celSet("retry_last",  _celFmtTs(retry.last_attempt_timestamp));

                // next_attempt_epoch is a Unix timestamp (seconds)
                const nextEp = retry.next_attempt_epoch;
                if (nextEp && nextEp > 0) {
                    const secsUntil = Math.round(nextEp - Date.now() / 1000);
                    if (secsUntil > 0) {
                        _celSet("retry_next", `in ${secsUntil}s  (${new Date(nextEp * 1000).toLocaleTimeString()})`);
                    } else {
                        _celSet("retry_next", "Pending…");
                    }
                } else {
                    _celSet("retry_next", "—");
                }

                const resultParts = [retry.last_result, retry.last_reason].filter(Boolean);
                _celSet("retry_result", resultParts.join(" — ") || "—");
            }
        };

        const refreshRuntimeState = async () => {
            try {
                const [stateResponse, applyResponse] = await Promise.all([
                    fetch("/api/network/state"),
                    fetch("/api/network/apply-result"),
                ]);
                if (!stateResponse.ok || !applyResponse.ok) return;
                const [stateData, applyData] = await Promise.all([stateResponse.json(), applyResponse.json()]);
                updateRuntimeState(stateData, applyData);
            } catch (error) {
                console.warn("Failed to refresh runtime network state", error);
            }
        };

        // ── Cellular status refresh ──────────────────────────────────────────
        const refreshCellularStatus = async () => {
            try {
                const r = await fetch("/api/network/state");
                if (!r.ok) return;
                const d = await r.json();
                updateCellularStatus(d?.cellular || null, d?.active_uplink);
            } catch (e) {
                console.warn("[Connectivity] cellular state fetch failed:", e);
            }
        };

        // Manual refresh button: calls gateway-cellular-qmi refresh-state for
        // truly fresh modem data, then reads the updated state.
        const refreshBtn = connectivityShell.querySelector("[data-cellular-refresh]");
        if (refreshBtn) {
            refreshBtn.addEventListener("click", async () => {
                refreshBtn.disabled = true;
                refreshBtn.textContent = "Refreshing…";
                try {
                    const r = await fetch("/api/cellular/refresh-state", { method: "POST" });
                    const d = await r.json();
                    if (d.ok) {
                        updateCellularStatus(d.cellular || null, d.active_uplink || null);
                    } else {
                        // Fall back to regular state poll
                        await refreshCellularStatus();
                    }
                } catch (e) {
                    console.warn("[Connectivity] cellular refresh failed:", e);
                    await refreshCellularStatus();
                } finally {
                    refreshBtn.disabled = false;
                    refreshBtn.textContent = "↻ Refresh";
                }
            });
        }

        // Auto-refresh runtime panel every 5s while it's visible
        let runtimeRefreshTimer = null;
        if (runtimeToggle && runtimePanel) {
            runtimeToggle.addEventListener("click", () => {
                const isVisible = !runtimePanel.classList.contains("is-hidden");
                if (!isVisible) {
                    refreshRuntimeState();
                    runtimeRefreshTimer = setInterval(refreshRuntimeState, 5000);
                } else {
                    clearInterval(runtimeRefreshTimer);
                }
            });
        }

        // Poll connection status after Save and Apply
        const startConnectionPoll = (wifiEnabled) => {
            const strip = connectivityShell.querySelector("[data-net-apply-strip]");
            const title = connectivityShell.querySelector("[data-net-apply-title]");
            const detail = connectivityShell.querySelector("[data-net-apply-detail]");
            const uplinkBadge = connectivityShell.querySelector("[data-net-apply-uplink]");
            if (!strip) return;

            strip.style.display = "";
            strip.className = "net-apply-strip is-pending";
            title.textContent = wifiEnabled ? "Connecting to Wi-Fi…" : "Applying network configuration…";
            detail.textContent = "Waiting for network monitor…";
            if (uplinkBadge) uplinkBadge.textContent = "";

            const MAX_POLLS = 20;
            const INTERVAL_MS = 2000;
            let polls = 0;
            let pollTimer = null;

            const stopPoll = () => clearTimeout(pollTimer);

            const tick = async () => {
                polls++;
                try {
                    const res = await fetch("/api/network/state");
                    if (!res.ok) throw new Error("state fetch failed");
                    const state = await res.json();
                    updateRuntimeState(state, {});

                    const activeUplink = String(state.active_uplink || "none");
                    const wifiSsid    = state.wifi_client?.connected_ssid;
                    const wifiAddr    = state.wifi_client?.address;
                    const eth0Addr    = state.eth0?.address;
                    const eth1Addr    = state.eth1?.address;

                    if (wifiEnabled && wifiSsid) {
                        strip.className = "net-apply-strip is-success";
                        title.textContent = `Connected — ${wifiSsid}`;
                        detail.textContent = wifiAddr || "Address assigned";
                        if (uplinkBadge) uplinkBadge.textContent = "Active uplink";
                        return stopPoll();
                    }

                    if (!wifiEnabled && ["eth0", "eth1"].includes(activeUplink)) {
                        const addr = activeUplink === "eth1" ? eth1Addr : eth0Addr;
                        strip.className = "net-apply-strip is-success";
                        title.textContent = "Configuration applied";
                        detail.textContent = addr ? `${activeUplink}: ${addr}` : activeUplink;
                        if (uplinkBadge) uplinkBadge.textContent = "Active uplink";
                        return stopPoll();
                    }

                    if (polls >= MAX_POLLS) {
                        strip.className = "net-apply-strip is-error";
                        title.textContent = wifiEnabled ? "Wi-Fi did not connect" : "No uplink established";
                        detail.textContent = wifiEnabled
                            ? "Check SSID, password, and signal strength."
                            : "Check cable or network configuration.";
                        return stopPoll();
                    }

                    detail.textContent = `Checking… (${polls * 2}s elapsed)`;
                } catch {
                    detail.textContent = "Could not reach gateway.";
                }
                pollTimer = setTimeout(tick, INTERVAL_MS);
            };

            pollTimer = setTimeout(tick, INTERVAL_MS);
        };

        const renderScanResults = (networks) => {
            if (!scanResults) {
                return;
            }

            if (!Array.isArray(networks) || networks.length === 0) {
                scanResults.innerHTML = '<p class="settings-inline-note">No Wi-Fi networks were found in the last scan.</p>';
                return;
            }

            scanResults.innerHTML = networks
                .map((network, index) => `
                    <button type="button" class="ghost-action" data-network-scan-select="${index}">
                        ${network.ssid || "(Hidden SSID)"} · ${network.band} · ${network.signal_dbm} dBm · ${network.security}
                    </button>
                `)
                .join("");

            const ssidInput = networkForm?.elements?.namedItem("wifi_client_ssid");
            const bandInput = networkForm?.elements?.namedItem("wifi_client_band");
            const securityInput = networkForm?.elements?.namedItem("wifi_client_security");

            scanResults.querySelectorAll("[data-network-scan-select]").forEach((button) => {
                button.addEventListener("click", () => {
                    const index = Number.parseInt(button.getAttribute("data-network-scan-select") || "-1", 10);
                    const network = networks[index];
                    if (!network) {
                        return;
                    }
                    if (ssidInput instanceof HTMLInputElement) {
                        ssidInput.value = network.ssid || "";
                    }
                    if (bandInput instanceof HTMLSelectElement && ["auto", "2.4ghz", "5ghz"].includes(network.band)) {
                        bandInput.value = network.band;
                    }
                    if (securityInput instanceof HTMLSelectElement) {
                        securityInput.value = network.security === "open" ? "open" : "wpa2-psk";
                    }
                });
            });
        };

        const runNetworkAction = async (endpoint, activeButton, busyLabel, idleLabel, afterSuccess = null) => {
            if (!(networkForm instanceof HTMLFormElement) || !networkMessage) {
                return;
            }

            const payload = buildNetworkPayload();
            if (!payload) {
                return;
            }

            const validationMessage = validateNetworkPayload(payload);
            if (validationMessage) {
                networkMessage.textContent = validationMessage;
                networkMessage.classList.remove("is-success");
                return;
            }

            networkMessage.textContent = "";
            networkMessage.classList.remove("is-success");

            const buttons = [saveButton, saveApplyButton].filter((button) => button instanceof HTMLButtonElement);
            buttons.forEach((button) => {
                button.disabled = true;
            });
            if (activeButton instanceof HTMLButtonElement) {
                activeButton.textContent = busyLabel;
            }

            try {
                const response = await fetch(endpoint, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                const firstError = Array.isArray(data.errors) && data.errors.length > 0 ? data.errors[0].message : null;
                const message = firstError || data.message || data.apply_status || "Saved.";
                networkMessage.textContent = message;
                networkMessage.classList.toggle("is-success", response.ok && data.ok);
                await refreshRuntimeState();
                if (!response.ok || !data.ok) {
                    throw new Error(message);
                }
                if (afterSuccess) afterSuccess();
            } catch (error) {
                networkMessage.textContent = error instanceof Error ? error.message : "Could not save network settings.";
                networkMessage.classList.remove("is-success");
            } finally {
                buttons.forEach((button) => {
                    button.disabled = false;
                });
                if (saveButton instanceof HTMLButtonElement) {
                    saveButton.textContent = "Save";
                }
                if (saveApplyButton instanceof HTMLButtonElement) {
                    saveApplyButton.textContent = "Save and Apply";
                }
                if (activeButton instanceof HTMLButtonElement) {
                    activeButton.textContent = idleLabel;
                }
            }
        };

        if (saveButton) {
            saveButton.addEventListener("click", () => {
                runNetworkAction("/api/network/settings", saveButton, "Saving...", "Save");
            });
        }

        if (saveApplyButton) {
            saveApplyButton.addEventListener("click", () => {
                const wifiEnabled = networkForm?.elements?.namedItem("wifi_client_enabled") instanceof HTMLInputElement
                    && networkForm.elements.namedItem("wifi_client_enabled").checked;
                runNetworkAction(
                    "/api/network/save-and-apply",
                    saveApplyButton,
                    "Applying…",
                    "Save and Apply",
                    () => startConnectionPoll(wifiEnabled),
                );
            });
        }

        if (scanButton) {
            scanButton.addEventListener("click", async () => {
                if (scanButton instanceof HTMLButtonElement) {
                    scanButton.disabled = true;
                    scanButton.textContent = "Scanning...";
                }
                if (scanMessage) {
                    scanMessage.classList.add("is-hidden");
                    scanMessage.textContent = "";
                }

                try {
                    const response = await fetch("/api/network/wifi/scan", { method: "POST" });
                    const data = await response.json();
                    if (!response.ok || !data.ok) {
                        throw new Error((data.errors && data.errors[0]?.message) || "Wi-Fi scan failed.");
                    }
                    renderScanResults(data.networks || []);
                } catch (error) {
                    if (scanMessage) {
                        scanMessage.classList.remove("is-hidden");
                        scanMessage.textContent = error instanceof Error ? error.message : "Wi-Fi scan failed.";
                    }
                } finally {
                    if (scanButton instanceof HTMLButtonElement) {
                        scanButton.disabled = false;
                        scanButton.textContent = "Scan Wi-Fi";
                    }
                }
            });
        }

        refreshRuntimeState();
        window.setInterval(refreshRuntimeState, 5000);

        // ── Ethernet interface details ─────────────────────────────────────
        const ethGrid = document.getElementById("eth-iface-grid");
        if (ethGrid) {
            const ethNote = document.getElementById("eth-refresh-note");

            const setEl = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.textContent = val;
            };
            const showEl = (id, show) => {
                const el = document.getElementById(id);
                if (el) el.style.display = show ? "" : "none";
            };

            const renderIface = (name, d, activeUplink) => {
                const isUp     = d.link_up || d.operstate === "up";
                const isActive = activeUplink === name;

                // Status dot + state
                const dot = document.getElementById(`${name}-dot`);
                if (dot) {
                    dot.className = `eth-link-dot ${isUp ? "is-up" : "is-down"}`;
                }
                setEl(`${name}-state`, isUp ? "Link up" : "Link down");
                showEl(`${name}-pill`, isActive);
                showEl(`${name}-inet`, d.internet_ok);

                // Address fields
                setEl(`${name}-mac`,     d.mac     || "—");
                setEl(`${name}-ipv4`,    d.ipv4    || "Waiting for DHCP");
                setEl(`${name}-gateway`, d.gateway || "—");
                setEl(`${name}-dns`,     d.dns?.join(", ") || "—");
                setEl(`${name}-speed`,   d.speed   || "—");
                setEl(`${name}-duplex`,  d.duplex  || "—");
                setEl(`${name}-mtu`,     d.mtu     || "—");

                // IPv6 list
                const ipv6El = document.getElementById(`${name}-ipv6`);
                if (ipv6El) {
                    if (d.ipv6 && d.ipv6.length > 0) {
                        ipv6El.innerHTML = d.ipv6.map((e) =>
                            `<span class="eth-ipv6-entry"><code>${e.addr}</code><span class="eth-ipv6-scope">${e.scope}</span></span>`
                        ).join("");
                    } else {
                        ipv6El.textContent = isUp ? "No IPv6 assigned" : "—";
                    }
                }
            };

            const renderWifi = (w) => {
                if (!w || !w.mac) {
                    const card = document.getElementById("eth-card-wlan0");
                    if (card) card.style.display = "none";
                    return;
                }
                const isUp = w.link_up || w.operstate === "up";
                const dot = document.getElementById("wlan0-dot");
                if (dot) dot.className = `eth-link-dot ${isUp ? "is-up" : "is-down"}`;

                const connected = !!w.ssid;
                setEl("wlan0-state", connected ? "Connected" : isUp ? "Up / not associated" : "Down");
                setEl("wlan0-mac",    w.mac     || "—");
                setEl("wlan0-ipv4",   w.ipv4    || "—");
                setEl("wlan0-ssid",   w.ssid    || (connected ? "—" : "Not associated"));
                setEl("wlan0-bssid",  w.bssid   || "—");
                setEl("wlan0-channel", w.channel || "—");
                setEl("wlan0-freq",   w.freq_mhz ? `${w.freq_mhz} MHz` : "—");

                const sigText = w.signal_dbm
                    ? `${w.signal_dbm}${w.signal_pct !== null ? ` (${w.signal_pct}%)` : ""}`
                    : "—";
                setEl("wlan0-signal", sigText);
                setEl("wlan0-rxrate", w.rx_bitrate || "—");
                setEl("wlan0-txrate", w.tx_bitrate || "—");

                // Mode pill
                const modePill = document.getElementById("wlan0-mode-pill");
                if (modePill) {
                    if (w.mode) {
                        modePill.textContent = w.mode === "AP" ? "Access Point" : w.mode;
                        modePill.style.display = "";
                    } else {
                        modePill.style.display = "none";
                    }
                }

                // IPv6
                const ipv6El = document.getElementById("wlan0-ipv6");
                if (ipv6El) {
                    if (w.ipv6 && w.ipv6.length > 0) {
                        ipv6El.innerHTML = w.ipv6.map((e) =>
                            `<span class="eth-ipv6-entry"><code>${e.addr}</code><span class="eth-ipv6-scope">${e.scope}</span></span>`
                        ).join("");
                    } else {
                        ipv6El.textContent = isUp ? "No IPv6 assigned" : "—";
                    }
                }

                // Hide SSID/BSSID rows if in AP mode or not connected
                const ssidRow  = document.getElementById("wlan0-ssid-row");
                const bssidRow = document.getElementById("wlan0-bssid-row");
                if (ssidRow)  ssidRow.style.display  = connected ? "" : "none";
                if (bssidRow) bssidRow.style.display = connected ? "" : "none";
            };

            const loadIfaceDetails = async () => {
                try {
                    const r = await fetch("/api/network/iface-details");
                    if (!r.ok) return;
                    const d = await r.json();
                    if (!d.ok) return;
                    const ifaces = d.interfaces || {};
                    renderIface("eth0", ifaces.eth0 || {}, d.active_uplink);
                    renderIface("eth1", ifaces.eth1 || {}, d.active_uplink);
                    renderWifi(d.wifi || null);
                    if (ethNote) {
                        const t = new Date().toLocaleTimeString();
                        ethNote.textContent = `Last refreshed: ${t}`;
                    }
                } catch (e) {
                    console.warn("[Connectivity] iface-details fetch failed:", e);
                }
            };

            document.getElementById("eth-refresh-btn")?.addEventListener("click", loadIfaceDetails);
            loadIfaceDetails();
            window.setInterval(loadIfaceDetails, 15000);
        }
    }

    const monitorShell = document.querySelector("[data-monitor-shell]");
    if (monitorShell) {
        const drawSparkline = (container, data, opts = {}) => {
            if (!container || !Array.isArray(data) || data.length < 2) return;
            const { stroke = "#39d0c8", min: minOverride, max: maxOverride, fmt = (v) => v.toFixed(1) } = opts;
            const W = container.clientWidth || 300;
            const H = container.clientHeight || 72;
            const pad = 3;
            const uH = H - pad * 2;
            const uW = W - pad * 2;
            const minV = minOverride !== undefined ? minOverride : Math.min(...data);
            const maxV = maxOverride !== undefined ? maxOverride : Math.max(...data);
            const range = maxV - minV || 1;
            const toX = (i) => pad + (i / (data.length - 1)) * uW;
            const toY = (v) => pad + uH - ((v - minV) / range) * uH;
            const pts = data.map((v, i) => `${toX(i)},${toY(v)}`).join(" ");
            const gradId = `sg${stroke.replace(/[^a-z0-9]/gi, "")}`;
            container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="${stroke}" stop-opacity="0.32"/>
                        <stop offset="100%" stop-color="${stroke}" stop-opacity="0.03"/>
                    </linearGradient>
                </defs>
                <path d="M ${toX(0)},${toY(data[0])} L ${pts} L ${toX(data.length - 1)},${H} L ${toX(0)},${H} Z" fill="url(#${gradId})"/>
                <polyline points="${pts}" fill="none" stroke="${stroke}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                <line class="ch-xhair" x1="0" y1="${pad}" x2="0" y2="${H - pad}" stroke="${stroke}" stroke-width="1" stroke-opacity="0.45" stroke-dasharray="3 2" opacity="0"/>
                <circle class="ch-dot" r="3.5" fill="${stroke}" stroke="#08141a" stroke-width="1.5" opacity="0"/>
                <g class="ch-tip" opacity="0">
                    <rect class="ch-tip-bg" rx="3" fill="rgba(8,20,26,0.92)" stroke="${stroke}" stroke-width="0.75" stroke-opacity="0.6"/>
                    <text class="ch-tip-txt" font-size="10" font-family="monospace" fill="${stroke}" text-anchor="middle" dominant-baseline="middle"/>
                </g>
                <rect class="ch-overlay" x="${pad}" y="${pad}" width="${uW}" height="${uH}" fill="transparent" style="cursor:crosshair"/>
            </svg>`;

            const svg = container.querySelector("svg");
            const xhair = svg.querySelector(".ch-xhair");
            const dot = svg.querySelector(".ch-dot");
            const tip = svg.querySelector(".ch-tip");
            const tipBg = svg.querySelector(".ch-tip-bg");
            const tipTxt = svg.querySelector(".ch-tip-txt");
            const overlay = svg.querySelector(".ch-overlay");
            const tipPadX = 6;
            const tipH = 16;

            overlay.addEventListener("mousemove", (e) => {
                const rect = svg.getBoundingClientRect();
                const mx = (e.clientX - rect.left) * (W / rect.width);
                const idx = Math.round(Math.max(0, Math.min(1, (mx - pad) / uW)) * (data.length - 1));
                const x = toX(idx);
                const y = toY(data[idx]);
                const label = fmt(data[idx]);
                const textW = label.length * 6 + tipPadX * 2;

                xhair.setAttribute("x1", x); xhair.setAttribute("x2", x); xhair.setAttribute("opacity", "1");
                dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("opacity", "1");

                let tx = x - textW / 2;
                let ty = y - tipH - 6;
                if (tx < pad) tx = pad;
                if (tx + textW > W - pad) tx = W - pad - textW;
                if (ty < pad) ty = y + 8;
                if (ty + tipH > H - pad) ty = H - pad - tipH;

                tipBg.setAttribute("x", tx); tipBg.setAttribute("y", ty);
                tipBg.setAttribute("width", textW); tipBg.setAttribute("height", tipH);
                tipTxt.setAttribute("x", tx + textW / 2); tipTxt.setAttribute("y", ty + tipH / 2);
                tipTxt.textContent = label;
                tip.setAttribute("opacity", "1");
            });

            overlay.addEventListener("mouseleave", () => {
                xhair.setAttribute("opacity", "0");
                dot.setAttribute("opacity", "0");
                tip.setAttribute("opacity", "0");
            });
        };

        const drawDualSparkline = (container, rxData, txData) => {
            if (!container || !Array.isArray(rxData) || rxData.length < 2) return;
            const W = container.clientWidth || 300;
            const H = container.clientHeight || 72;
            const pad = 3;
            const uH = H - pad * 2;
            const uW = W - pad * 2;
            const allVals = [...rxData, ...(Array.isArray(txData) ? txData : [])];
            const maxV = Math.max(1, ...allVals);
            const toX = (i) => pad + (i / (rxData.length - 1)) * uW;
            const toY = (v) => pad + uH - (v / maxV) * uH;
            const rxPts = rxData.map((v, i) => `${toX(i)},${toY(v)}`).join(" ");
            const hasTx = Array.isArray(txData) && txData.length >= 2;
            const txPts = hasTx ? txData.map((v, i) => `${toX(i)},${toY(v)}`).join(" ") : null;
            container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <linearGradient id="sg_netrx" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#a97df0" stop-opacity="0.28"/>
                        <stop offset="100%" stop-color="#a97df0" stop-opacity="0.02"/>
                    </linearGradient>
                </defs>
                <path d="M ${toX(0)},${toY(rxData[0])} L ${rxPts} L ${toX(rxData.length - 1)},${H} L ${toX(0)},${H} Z" fill="url(#sg_netrx)"/>
                <polyline points="${rxPts}" fill="none" stroke="#a97df0" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                ${txPts ? `<polyline points="${txPts}" fill="none" stroke="#f0a64b" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="4 3"/>` : ""}
                <line class="ch-xhair" x1="0" y1="${pad}" x2="0" y2="${H - pad}" stroke="rgba(255,255,255,0.35)" stroke-width="1" stroke-dasharray="3 2" opacity="0"/>
                <circle class="ch-dot-rx" r="3" fill="#a97df0" stroke="#08141a" stroke-width="1.5" opacity="0"/>
                ${hasTx ? `<circle class="ch-dot-tx" r="3" fill="#f0a64b" stroke="#08141a" stroke-width="1.5" opacity="0"/>` : ""}
                <g class="ch-tip" opacity="0">
                    <rect class="ch-tip-bg" rx="3" fill="rgba(8,20,26,0.92)" stroke="rgba(255,255,255,0.18)" stroke-width="0.75"/>
                    <text class="ch-tip-rx" font-size="9" font-family="monospace" fill="#a97df0" dominant-baseline="middle"/>
                    ${hasTx ? `<text class="ch-tip-tx" font-size="9" font-family="monospace" fill="#f0a64b" dominant-baseline="middle"/>` : ""}
                </g>
                <rect class="ch-overlay" x="${pad}" y="${pad}" width="${uW}" height="${uH}" fill="transparent" style="cursor:crosshair"/>
            </svg>`;

            const svg = container.querySelector("svg");
            const xhair = svg.querySelector(".ch-xhair");
            const dotRx = svg.querySelector(".ch-dot-rx");
            const dotTx = svg.querySelector(".ch-dot-tx");
            const tip = svg.querySelector(".ch-tip");
            const tipBg = svg.querySelector(".ch-tip-bg");
            const tipRxEl = svg.querySelector(".ch-tip-rx");
            const tipTxEl = svg.querySelector(".ch-tip-tx");
            const overlay = svg.querySelector(".ch-overlay");
            const tipPadX = 6;
            const tipPadY = 4;
            const lineH = 11;

            overlay.addEventListener("mousemove", (e) => {
                const rect = svg.getBoundingClientRect();
                const mx = (e.clientX - rect.left) * (W / rect.width);
                const idx = Math.round(Math.max(0, Math.min(1, (mx - pad) / uW)) * (rxData.length - 1));
                const x = toX(idx);
                const yRx = toY(rxData[idx]);
                const rxLabel = `rx ${fmtBps(rxData[idx])}`;
                const txLabel = hasTx ? `tx ${fmtBps(txData[idx])}` : null;
                const longestLabel = txLabel && txLabel.length > rxLabel.length ? txLabel : rxLabel;
                const textW = longestLabel.length * 5.5 + tipPadX * 2;
                const tipH = hasTx ? tipPadY * 2 + lineH * 2 : tipPadY * 2 + lineH;

                xhair.setAttribute("x1", x); xhair.setAttribute("x2", x); xhair.setAttribute("opacity", "1");
                dotRx.setAttribute("cx", x); dotRx.setAttribute("cy", yRx); dotRx.setAttribute("opacity", "1");
                if (dotTx) {
                    dotTx.setAttribute("cx", x); dotTx.setAttribute("cy", toY(txData[idx])); dotTx.setAttribute("opacity", "1");
                }

                let tx = x - textW / 2;
                let ty = yRx - tipH - 6;
                if (tx < pad) tx = pad;
                if (tx + textW > W - pad) tx = W - pad - textW;
                if (ty < pad) ty = yRx + 8;
                if (ty + tipH > H - pad) ty = H - pad - tipH;

                tipBg.setAttribute("x", tx); tipBg.setAttribute("y", ty);
                tipBg.setAttribute("width", textW); tipBg.setAttribute("height", tipH);
                tipRxEl.setAttribute("x", tx + tipPadX); tipRxEl.setAttribute("y", ty + tipPadY + lineH / 2);
                tipRxEl.textContent = rxLabel;
                if (tipTxEl && txLabel) {
                    tipTxEl.setAttribute("x", tx + tipPadX); tipTxEl.setAttribute("y", ty + tipPadY + lineH + lineH / 2);
                    tipTxEl.textContent = txLabel;
                }
                tip.setAttribute("opacity", "1");
            });

            overlay.addEventListener("mouseleave", () => {
                xhair.setAttribute("opacity", "0");
                dotRx.setAttribute("opacity", "0");
                if (dotTx) dotTx.setAttribute("opacity", "0");
                tip.setAttribute("opacity", "0");
            });
        };

        const fmtBps = (bps) => {
            if (bps >= 1048576) return `${(bps / 1048576).toFixed(1)} MB/s`;
            if (bps >= 1024) return `${(bps / 1024).toFixed(1)} KB/s`;
            return `${Math.round(bps)} B/s`;
        };

        const fmtBytes = (b) => {
            if (b >= 1073741824) return `${(b / 1073741824).toFixed(1)} GB`;
            if (b >= 1048576) return `${(b / 1048576).toFixed(0)} MB`;
            return `${Math.round(b / 1024)} KB`;
        };

        const fmtMb = (mb) => {
            const value = Number(mb || 0);
            if (value >= 1024) return `${(value / 1024).toFixed(1)} GB`;
            return `${Math.round(value).toLocaleString()} MB`;
        };

        const fmtDuration = (seconds) => {
            const total = Math.max(0, Number(seconds || 0));
            const days = Math.floor(total / 86400);
            const hours = Math.floor((total % 86400) / 3600);
            const mins = Math.floor((total % 3600) / 60);
            if (days > 0) return `${days}d ${hours}h`;
            if (hours > 0) return `${hours}h ${mins}m`;
            if (mins > 0) return `${mins}m`;
            return `${Math.floor(total)}s`;
        };

        const setKpiBar = (name, pct) => {
            const bar = monitorShell.querySelector(`[data-kpi-bar="${name}"]`);
            if (!bar) return;
            bar.style.width = `${Math.min(100, Math.max(0, pct))}%`;
            if (name === "temp") {
                bar.classList.toggle("is-warm", pct >= 50 && pct < 70);
                bar.classList.toggle("is-hot", pct >= 70);
            }
        };

        const clearChart = (name, label = "Waiting for telemetry") => {
            const container = monitorShell.querySelector(`[data-chart-svg="${name}"]`);
            if (container) {
                container.innerHTML = `<div class="chart-empty-state">${label}</div>`;
            }
        };

        const applyTelemetryUnavailable = () => {
            ["cpu", "memory", "temp", "disk"].forEach((name) => setKpiBar(name, 0));
            [
                ["cpu", "--"],
                ["memory", "--"],
                ["temp", "--"],
                ["disk", "--"],
            ].forEach(([name, value]) => {
                const el = monitorShell.querySelector(`[data-kpi-value="${name}"]`);
                if (el) el.textContent = value;
            });
            ["cpu", "memory", "temp", "disk"].forEach((name) => {
                const el = monitorShell.querySelector(`[data-kpi-sub="${name}"]`);
                if (el) el.textContent = "Waiting for telemetry";
            });
            [
                ["cpu", "--%"],
                ["memory", "--%"],
                ["temp", "-- °C"],
                ["storage", "--%"],
            ].forEach(([name, value]) => {
                const el = monitorShell.querySelector(`[data-chart-live="${name}"]`);
                if (el) el.textContent = value;
            });
            ["cpu", "memory", "temp", "storage"].forEach((name) => clearChart(name));

            const coreGrid = monitorShell.querySelector("[data-core-grid]");
            if (coreGrid) coreGrid.innerHTML = `<p class="insights-empty-note">Waiting for system telemetry...</p>`;
            ["1m", "5m", "15m"].forEach((key) => {
                const el = monitorShell.querySelector(`[data-load-avg="${key}"]`);
                if (el) el.textContent = "--";
            });
            const loadSummary = monitorShell.querySelector("[data-load-summary]");
            if (loadSummary) loadSummary.textContent = "Waiting for system telemetry.";
            [
                "[data-monitor-throttle]",
                "[data-monitor-emmc-life]",
                "[data-monitor-uptime]",
                "[data-monitor-swap]",
            ].forEach((selector) => {
                const el = monitorShell.querySelector(selector);
                if (el) el.textContent = "--";
            });
        };

        const applyCurrentMetrics = (m) => {
            if (!m?.cpu || m.source !== "gateway_core_ipc") {
                applyTelemetryUnavailable();
                return;
            }

            // CPU.
            const cpuPct = Number(m.cpu.total_percent ?? 0);
            const perCore = Array.isArray(m.cpu.per_core) ? m.cpu.per_core : [];
            const maxFreq = Math.max(0, ...perCore.map((c) => Number(c.freq_mhz || 0)));
            const cpuVal = monitorShell.querySelector("[data-kpi-value=\"cpu\"]");
            const cpuSub = monitorShell.querySelector("[data-kpi-sub=\"cpu\"]");
            const cpuLive = monitorShell.querySelector("[data-chart-live=\"cpu\"]");
            if (cpuVal) cpuVal.textContent = `${cpuPct.toFixed(1)}%`;
            if (cpuSub) {
                cpuSub.textContent = maxFreq
                    ? `${perCore.length} core${perCore.length !== 1 ? "s" : ""} · max ${maxFreq} MHz`
                    : `${perCore.length} core${perCore.length !== 1 ? "s" : ""}`;
            }
            if (cpuLive) cpuLive.textContent = `${cpuPct.toFixed(1)}%`;
            setKpiBar("cpu", cpuPct);

            // Memory.
            const memPct = Number(m.memory?.memory_bytes?.used_percent ?? 0);
            const memUsed = m.memory?.memory_bytes?.used ?? 0;
            const memTotal = m.memory?.memory_bytes?.total ?? 0;
            const memVal = monitorShell.querySelector("[data-kpi-value=\"memory\"]");
            const memSub = monitorShell.querySelector("[data-kpi-sub=\"memory\"]");
            const memLive = monitorShell.querySelector("[data-chart-live=\"memory\"]");
            if (memVal) memVal.textContent = `${memPct.toFixed(1)}%`;
            if (memSub) memSub.textContent = memTotal ? `${fmtBytes(memUsed)} of ${fmtBytes(memTotal)}` : "No data";
            if (memLive) memLive.textContent = `${memPct.toFixed(1)}%`;
            setKpiBar("memory", memPct);

            // Temperature.
            const tempC = m.temperature_c != null ? Number(m.temperature_c) : null;
            const tempVal = monitorShell.querySelector("[data-kpi-value=\"temp\"]");
            const tempSub = monitorShell.querySelector("[data-kpi-sub=\"temp\"]");
            const tempLive = monitorShell.querySelector("[data-chart-live=\"temp\"]");
            if (tempVal) tempVal.textContent = tempC != null ? `${tempC.toFixed(1)}\u00b0C` : "--";
            if (tempSub) tempSub.textContent = tempC == null ? "No sensor" : tempC < 50 ? "Normal operating range" : tempC < 70 ? "Warm, monitor load" : "Thermal risk";
            if (tempLive) tempLive.textContent = tempC != null ? `${tempC.toFixed(1)} \u00b0C` : "-- \u00b0C";
            setKpiBar("temp", tempC != null ? Math.min(100, (tempC / 85) * 100) : 0);

            // Storage.
            const diskPct = Number(m.filesystem?.used_percent ?? 0);
            const emmc = m.emmc ?? {};
            const emmcPct = Number(emmc.used_percent ?? diskPct);
            const emmcUsed = Number(emmc.used_mb ?? 0);
            const emmcTotal = Number(emmc.total_mb ?? 0);
            const diskVal = monitorShell.querySelector("[data-kpi-value=\"disk\"]");
            const diskSub = monitorShell.querySelector("[data-kpi-sub=\"disk\"]");
            const storageLive = monitorShell.querySelector("[data-chart-live=\"storage\"]");
            if (diskVal) diskVal.textContent = `${diskPct.toFixed(1)}%`;
            if (diskSub) {
                diskSub.textContent = emmcTotal > 0
                    ? `root ${diskPct.toFixed(1)}% · eMMC ${fmtMb(emmcUsed)} of ${fmtMb(emmcTotal)}`
                    : `root ${diskPct.toFixed(1)}%`;
            }
            if (storageLive) storageLive.textContent = `${emmcPct.toFixed(1)}%`;
            setKpiBar("disk", diskPct);

            // Per-core bars.
            const coreGrid = monitorShell.querySelector("[data-core-grid]");
            if (coreGrid && perCore.length > 0) {
                coreGrid.innerHTML = perCore.map((c) => {
                    const usage = Number(c.usage_percent || 0);
                    const freq = Number(c.freq_mhz || 0);
                    return `<div class="core-item">
                    <div class="core-bar-track"><div class="core-bar-fill" style="height:${Math.min(100, usage)}%"></div></div>
                    <p class="core-item-value">${usage.toFixed(1)}%</p>
                    <p class="core-item-label">C${c.core}${freq ? `<span>${freq} MHz</span>` : ""}</p>
                </div>`;
                }).join("");
            }

            // Load average.
            const loadAvg = m.cpu.load_average ?? {};
            ["1m", "5m", "15m"].forEach((key) => {
                const el = monitorShell.querySelector(`[data-load-avg="${key}"]`);
                if (el) el.textContent = loadAvg[key] != null ? Number(loadAvg[key]).toFixed(2) : "--";
            });
            const loadSummary = monitorShell.querySelector("[data-load-summary]");
            if (loadSummary) {
                const load1m = Number(loadAvg["1m"] ?? 0);
                const coreCount = Number(m.cpu.core_count || perCore.length || 1);
                const ratio = coreCount > 0 ? load1m / coreCount : 0;
                const tone = ratio < 0.5 ? "light" : ratio < 0.85 ? "moderate" : ratio <= 1.05 ? "near capacity" : "over capacity";
                loadSummary.textContent = `${load1m.toFixed(2)} active/queued tasks on ${coreCount} CPU core${coreCount !== 1 ? "s" : ""}; ${coreCount.toFixed(2)} means full CPU capacity. Current load is ${tone}.`;
            }

            const throttleFlags = Number(m.cpu.throttle_flags || 0);
            const throttleEl = monitorShell.querySelector("[data-monitor-throttle]");
            const emmcLifeEl = monitorShell.querySelector("[data-monitor-emmc-life]");
            const uptimeEl = monitorShell.querySelector("[data-monitor-uptime]");
            const swapEl = monitorShell.querySelector("[data-monitor-swap]");
            if (throttleEl) throttleEl.textContent = throttleFlags ? `0x${throttleFlags.toString(16)} active` : "None";
            if (emmcLifeEl) emmcLifeEl.textContent = Number(emmc.life_used_percent || 0) ? `${Number(emmc.life_used_percent)}%` : "Unavailable";
            if (uptimeEl) uptimeEl.textContent = fmtDuration(m.uptime_sec);
            if (swapEl) swapEl.textContent = fmtMb(m.memory?.swap_mb?.used || 0);
        };

        const applyHistoryMetrics = (history) => {
            const samples = Array.isArray(history?.samples) ? history.samples : [];
            if (history?.source !== "gateway_core_ipc" || samples.length < 2) {
                ["cpu", "memory", "temp", "storage"].forEach((name) => clearChart(name));
                return;
            }
            const cpuData = samples.map((s) => s.cpu_total_percent ?? 0);
            const memData = samples.map((s) => s.memory_used_percent ?? 0);
            const tempData = samples.map((s) => s.temperature_c ?? 0);
            const storageData = samples.map((s) => s.emmc_used_percent ?? s.disk_used_percent ?? 0);
            // Auto-scale: anchor min at 0, max = actual peak + 30% headroom (minimum 10 for %)
            const cpuMax = Math.max(10, ...cpuData) * 1.3;
            const memMax = Math.max(10, ...memData) * 1.3;
            const storageMax = Math.max(10, ...storageData) * 1.2;
            drawSparkline(monitorShell.querySelector("[data-chart-svg=\"cpu\"]"), cpuData, { stroke: "#39d0c8", min: 0, max: cpuMax, fmt: (v) => `${v.toFixed(1)}%` });
            drawSparkline(monitorShell.querySelector("[data-chart-svg=\"memory\"]"), memData, { stroke: "#f0a64b", min: 0, max: memMax, fmt: (v) => `${v.toFixed(1)}%` });
            drawSparkline(monitorShell.querySelector("[data-chart-svg=\"temp\"]"), tempData, { stroke: "#62d39e", fmt: (v) => `${v.toFixed(1)}°C` });
            drawSparkline(monitorShell.querySelector("[data-chart-svg=\"storage\"]"), storageData, { stroke: "#60a5fa", min: 0, max: storageMax, fmt: (v) => `${v.toFixed(1)}% used` });
        };

        const refreshMonitorCurrent = async () => {
            try {
                const response = await fetch("/api/system/metrics");
                if (!response.ok) return;
                applyCurrentMetrics(await response.json());
            } catch (err) {
                console.warn("Failed to refresh system metrics", err);
            }
        };

        const refreshMonitorHistory = async () => {
            try {
                const response = await fetch("/api/system/metrics/history");
                if (!response.ok) return;
                applyHistoryMetrics(await response.json());
            } catch (err) {
                console.warn("Failed to refresh system metrics history", err);
            }
        };

        refreshMonitorCurrent();
        refreshMonitorHistory();
        window.setInterval(refreshMonitorCurrent, 5000);
        window.setInterval(refreshMonitorHistory, 30000);

        // ── (uplink stats section removed — see Connectivity > Status tab) ──
        if (false) {
        if (uplinkSection) {
            const ifaceGrid      = uplinkSection.querySelector("[data-monitor-iface-grid]");
            const activeLabel    = uplinkSection.querySelector("[data-monitor-uplink-active-label]");
            const activeDot      = uplinkSection.querySelector("[data-monitor-uplink-dot]");
            const failoverDiv    = uplinkSection.querySelector("[data-monitor-failover-detail]");
            const outageDiv      = uplinkSection.querySelector("[data-monitor-outage-detail]");
            const tailscaleDiv   = uplinkSection.querySelector("[data-monitor-tailscale-detail]");

            const _statusLabel = (key) =>
                key === "eth0" ? "Ethernet (eth0)" : key === "eth1" ? "Ethernet (eth1)"
              : key === "wifi_client" ? "Wi-Fi" : key === "cellular" ? "Cellular"
              : key === "none" ? "None" : (key || "—");

            const _fmtDurMon = (secs) => {
                if (!secs && secs !== 0) return "—";
                secs = Math.round(secs);
                if (secs < 60) return `${secs}s`;
                if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
                const h = Math.floor(secs / 3600);
                const m = Math.floor((secs % 3600) / 60);
                return h > 0 && m > 0 ? `${h}h ${m}m` : h > 0 ? `${h}h` : `${m}m`;
            };

            const _ifaceStatus = (key, iface) => {
                const st = iface?.status || "unknown";
                return {
                    up:       { cls: "is-up",      label: "Up" },
                    down:     { cls: "is-down",    label: "Down" },
                    disabled: { cls: "is-disabled", label: "Disabled" },
                    unknown:  { cls: "is-unknown",  label: "Unknown" },
                }[st] || { cls: "is-unknown", label: st };
            };

            const renderUplinkStats = (state) => {
                const uplinkStats  = state?.uplink_stats  || {};
                const tailscale    = state?.tailscale_recovery || {};
                const activeUplink = String(state?.active_uplink || "none");
                const network      = uplinkStats.network   || {};
                const ifaces       = uplinkStats.interfaces || {};
                const hasUplink    = Boolean(network.has_uplink);

                // Active label + dot
                if (activeLabel) activeLabel.textContent = _statusLabel(activeUplink);
                if (activeDot) {
                    activeDot.className = "monitor-uplink-active-dot " + (hasUplink ? "is-up" : "is-none");
                }

                // Per-interface cards
                if (ifaceGrid) {
                    const ifaceKeys = Object.keys(ifaces);
                    if (ifaceKeys.length === 0) {
                        ifaceGrid.innerHTML = `<p class="insights-empty-note">No interface data available yet.</p>`;
                    } else {
                        ifaceGrid.innerHTML = ifaceKeys.map((key) => {
                            const iface = ifaces[key];
                            const { cls, label } = _ifaceStatus(key, iface);
                            const isActive = key === activeUplink;
                            const downSecs = iface.current_down_seconds || 0;
                            const totalDown = iface.total_down_seconds || 0;
                            const downEvts = iface.down_events || 0;
                            const ifaceName = _statusLabel(key);
                            return `<article class="monitor-iface-card ${cls}${isActive ? " is-active-uplink" : ""}">
                                <div class="monitor-iface-card-head">
                                    <span class="monitor-iface-dot ${cls}"></span>
                                    <span class="monitor-iface-name">${ifaceName}</span>
                                    ${isActive ? `<span class="monitor-iface-active-pill">Active</span>` : ""}
                                    <span class="monitor-iface-status-label">${label}</span>
                                </div>
                                <div class="monitor-iface-stats">
                                    ${downSecs > 0 ? `<div class="monitor-iface-stat is-warn"><span>Down for</span><strong>${_fmtDurMon(downSecs)}</strong></div>` : ""}
                                    <div class="monitor-iface-stat"><span>Total down</span><strong>${_fmtDurMon(totalDown)}</strong></div>
                                    <div class="monitor-iface-stat"><span>Down events</span><strong>${downEvts}</strong></div>
                                    ${iface.last_up_timestamp ? `<div class="monitor-iface-stat"><span>Last up</span><strong>${iface.last_up_timestamp.replace("T"," ").slice(0,16)}</strong></div>` : ""}
                                    ${iface.last_down_timestamp && downEvts > 0 ? `<div class="monitor-iface-stat"><span>Last down</span><strong>${iface.last_down_timestamp.replace("T"," ").slice(0,16)}</strong></div>` : ""}
                                </div>
                            </article>`;
                        }).join("");
                    }
                }

                // Last failover detail
                if (failoverDiv) {
                    const sw = uplinkStats.switch_count || 0;
                    const ls = uplinkStats.last_switch  || {};
                    if (sw > 0 && ls.from) {
                        failoverDiv.innerHTML = `
                            <div class="monitor-failover-grid">
                                <div class="monitor-stat-row"><span>Switch count</span><strong>${sw}</strong></div>
                                <div class="monitor-stat-row"><span>From</span><strong>${_statusLabel(ls.from)}</strong></div>
                                <div class="monitor-stat-row"><span>To</span><strong>${_statusLabel(ls.to)}</strong></div>
                                ${ls.duration_seconds !== undefined ? `<div class="monitor-stat-row"><span>Duration</span><strong>${ls.duration_seconds}s</strong></div>` : ""}
                                ${ls.completed_timestamp ? `<div class="monitor-stat-row"><span>Completed</span><strong>${ls.completed_timestamp.replace("T"," ").slice(0,16)}</strong></div>` : ""}
                                ${ls.reason ? `<div class="monitor-stat-row"><span>Reason</span><strong>${ls.reason.replace(/_/g," ")}</strong></div>` : ""}
                            </div>`;
                    } else {
                        failoverDiv.innerHTML = `<p class="insights-empty-note">No failover recorded since monitor started.</p>`;
                    }
                }

                // Network outage detail
                if (outageDiv) {
                    const netDown = network.current_down_seconds || 0;
                    const lastDown = network.last_down_duration_seconds || 0;
                    const totalDown = network.total_down_seconds || 0;
                    const downEvts = network.down_events || 0;
                    outageDiv.innerHTML = `
                        <div class="monitor-failover-grid">
                            <div class="monitor-stat-row"><span>Status</span><strong class="${hasUplink ? "is-text-ok" : "is-text-warn"}">${hasUplink ? "Uplink available" : "No uplink"}</strong></div>
                            ${netDown > 0 ? `<div class="monitor-stat-row is-warn"><span>Current outage</span><strong>${_fmtDurMon(netDown)}</strong></div>` : ""}
                            <div class="monitor-stat-row"><span>Last outage</span><strong>${lastDown > 0 ? _fmtDurMon(lastDown) : "None"}</strong></div>
                            <div class="monitor-stat-row"><span>Total down</span><strong>${totalDown > 0 ? _fmtDurMon(totalDown) : "0s"}</strong></div>
                            <div class="monitor-stat-row"><span>Down events</span><strong>${downEvts}</strong></div>
                        </div>`;
                }

                // Tailscale recovery
                if (tailscaleDiv) {
                    const count = tailscale.count || 0;
                    if (count > 0) {
                        const ts  = tailscale.last_timestamp || "";
                        const why = tailscale.last_reason    || "";
                        tailscaleDiv.innerHTML = `
                            <div class="monitor-failover-grid">
                                <div class="monitor-stat-row"><span>Recovery count</span><strong>${count}</strong></div>
                                ${ts ? `<div class="monitor-stat-row"><span>Last recovery</span><strong>${ts.replace("T"," ").slice(0,16)}</strong></div>` : ""}
                                ${why ? `<div class="monitor-stat-row monitor-stat-row-full"><span>Reason</span><strong>${why}</strong></div>` : ""}
                            </div>`;
                    } else {
                        tailscaleDiv.innerHTML = `<p class="insights-empty-note">No Tailscale recovery events recorded.</p>`;
                    }
                }
            };

            const refreshUplinkStats = async () => {
                try {
                    const r = await fetch("/api/network/state");
                    if (!r.ok) return;
                    renderUplinkStats(await r.json());
                } catch (e) {
                    console.warn("[Monitor] uplink stats fetch failed:", e);
                }
            };

            refreshUplinkStats();
            window.setInterval(refreshUplinkStats, 10000);
        }
        } // end if(false)

        // ── Anomaly Detection tab: interactive uPlot charts ─────────────
        const anomalyController = (() => {
            const root = monitorShell.querySelector("[data-monitor-anomaly]");
            if (!root) return { activate() {}, resizeAll() {} };

            const grid = root.querySelector("[data-anomaly-chart-grid]");
            const tooltip = root.querySelector("[data-anomaly-tooltip]");
            const groupsList = root.querySelector("[data-anomaly-groups]");
            const coverageEl = root.querySelector("[data-anomaly-coverage]");
            const rangeButtons = Array.from(root.querySelectorAll("[data-anomaly-range]"));
            const modal = root.querySelector("[data-anomaly-modal]");
            const modalPlot = modal.querySelector("[data-anomaly-modal-plot]");
            const modalDetail = modal.querySelector("[data-anomaly-modal-detail]");
            const modalTitle = modal.querySelector("[data-anomaly-modal-title]");
            const modalSub = modal.querySelector("[data-anomaly-modal-sub]");

            const RANGES = { "1h": 3600e3, "6h": 6 * 3600e3, "24h": 24 * 3600e3, "7d": 7 * 86400e3, "30d": 30 * 86400e3 };
            const RANGE_LABELS = { "1h": "hour", "6h": "6 hours", "24h": "24 hours", "7d": "7 days", "30d": "30 days" };
            const SEV_COLOR = { Critical: "#f2545b", Warning: "#f0a64b", Info: "#60a5fa" };
            const SEV_RANK = { Info: 1, Warning: 2, Critical: 3 };
            const STROKES = ["#39d0c8", "#62d39e", "#f0a64b", "#60a5fa", "#c084fc", "#f472b6"];

            let currentRange = "1h";
            let catalog = [];
            let checks = [];                     // detection kinds (category + copy)
            const units = {};                    // metric -> unit string
            const charts = {};                   // metric -> { cfg, plotEl, liveEl, statusEl, footEl, u, anomalies, markers, xs, ys }
            const modalState = { metric: null, cfg: null, u: null, anomalies: [], markers: [] };
            let started = false;
            let refreshTimer = null;

            const dpr = () => window.devicePixelRatio || 1;

            const fmtVal = (v, unit) => {
                if (v == null || Number.isNaN(v)) return "--";
                const txt = Number.isInteger(v) ? String(v) : Number(v).toFixed(1);
                return `${txt}${unit || ""}`;
            };
            const fmtAgo = (ms) => {
                const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
                if (s < 60) return `${s}s ago`;
                if (s < 3600) return `${Math.floor(s / 60)}m ago`;
                if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
                return `${Math.floor(s / 86400)}d ago`;
            };
            const hexToRgba = (hex, a) => {
                const h = hex.replace("#", "");
                const n = parseInt(h, 16);
                return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
            };
            const statusFor = (cfg, v) => {
                if (v == null) return { label: "No data", cls: "is-idle" };
                if (cfg.crit_limit != null && v >= cfg.crit_limit) return { label: "Critical", cls: "is-critical" };
                if (cfg.safe_limit != null && v >= cfg.safe_limit) return { label: "Warning", cls: "is-warning" };
                return { label: "Healthy", cls: "is-healthy" };
            };

            // event.value is detector-specific: the real reading only for
            // threshold/range detectors; a z-score, delta or slope otherwise.
            // So the true "reading at that time" is read off the stored metric
            // line, and the dot is placed there — always on the line.
            const REAL_VALUE_DETECTORS = new Set(["thresholddetector", "rangecheckdetector"]);
            const seriesValueAt = (xs, ys, tSec) => {
                // nearest non-null point (series contains null gap-breaks)
                if (!xs || !xs.length) return null;
                let best = null, bestD = Infinity;
                for (let i = 0; i < xs.length; i++) {
                    if (ys[i] == null) continue;
                    const d = Math.abs(xs[i] - tSec);
                    if (d < bestD) { bestD = d; best = ys[i]; }
                }
                return best;
            };
            const hasDerived = (a) => a.z_score != null || a.delta_value != null || a.slope_value != null;
            const readingFor = (ref, a) => {
                const det = String(a.detector || "").toLowerCase();
                // threshold/range always carry the reading; the new engine puts
                // the reading in value for every detector (signalled by a derived
                // field being present). Old data or timeout/multi → read the line.
                if (REAL_VALUE_DETECTORS.has(det) && typeof a.value === "number") return a.value;
                if (hasDerived(a) && typeof a.value === "number") return a.value;
                return seriesValueAt(ref.xs, ref.ys, a.ts_ms / 1000);
            };

            const drawDiamond = (ctx, x, y, r, color) => {
                ctx.beginPath();
                ctx.moveTo(x, y - r); ctx.lineTo(x + r, y);
                ctx.lineTo(x, y + r); ctx.lineTo(x - r, y);
                ctx.closePath();
                ctx.fillStyle = color;
                ctx.fill();
                ctx.lineWidth = 1.5;
                ctx.strokeStyle = "rgba(15,23,42,0.85)";
                ctx.stroke();
            };

            // Shared plugin: coloured safe/warning/critical zones + a min/max
            // band (behind the avg line) so the chart shows the real range the
            // 1-second data swung through inside each bucket — the anomaly dots
            // then sit on the line at their true value, matching history.
            const zonesMarkersPlugin = (cfg, ref, big) => ({
                hooks: {
                    drawClear: (u) => {
                        const ctx = u.ctx;
                        const { left, top, width, height } = u.bbox;
                        const bottom = top + height;
                        const clampY = (v) => Math.max(top, Math.min(bottom, u.valToPos(v, "y", true)));
                        ctx.save();
                        // safe / warning / critical zones
                        if (cfg.safe_limit != null) {
                            const ySafe = clampY(cfg.safe_limit);
                            const yCrit = cfg.crit_limit != null ? clampY(cfg.crit_limit) : top;
                            ctx.fillStyle = "rgba(98,211,158,0.08)";
                            ctx.fillRect(left, ySafe, width, bottom - ySafe);
                            ctx.fillStyle = "rgba(240,166,75,0.10)";
                            ctx.fillRect(left, yCrit, width, ySafe - yCrit);
                            ctx.fillStyle = "rgba(242,84,91,0.11)";
                            ctx.fillRect(left, top, width, yCrit - top);
                        }
                        // min/max range band — only meaningful on the rolled-up
                        // hourly tier; the raw 1 s fine tier has min == max.
                        // Drawn per contiguous run so it never bridges the null
                        // gap-breaks inserted where the device was offline.
                        const xs = ref.xs, mins = ref.mins, maxs = ref.maxs;
                        if (ref.tier === "hourly" && xs && xs.length > 1 && mins && maxs) {
                            ctx.fillStyle = hexToRgba(cfg.stroke, 0.16);
                            let seg = [];
                            const flushSeg = () => {
                                if (seg.length > 1) {
                                    ctx.beginPath();
                                    seg.forEach((i, k) => {
                                        const x = u.valToPos(xs[i], "x", true), y = clampY(maxs[i]);
                                        k === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
                                    });
                                    for (let k = seg.length - 1; k >= 0; k--) {
                                        const i = seg[k];
                                        ctx.lineTo(u.valToPos(xs[i], "x", true), clampY(mins[i]));
                                    }
                                    ctx.closePath();
                                    ctx.fill();
                                }
                                seg = [];
                            };
                            for (let i = 0; i < xs.length; i++) {
                                if (mins[i] == null || maxs[i] == null) { flushSeg(); continue; }
                                seg.push(i);
                            }
                            flushSeg();
                        }
                        ctx.restore();
                    },
                    // Anomaly dots sit ON the line at their real reading, bucketed
                    // by time so a per-second flood shows as a few counted dots.
                    // Buckets shrink as you zoom in. Colour = severity only.
                    draw: (u) => {
                        const ctx = u.ctx;
                        const { left, top, width, height } = u.bbox;
                        const bottom = top + height;
                        const clampY = (v) => Math.max(top + 4, Math.min(bottom - 4, u.valToPos(v, "y", true)));
                        const xMin = u.scales.x.min, xMax = u.scales.x.max;
                        const spanSec = Math.max(1e-6, xMax - xMin);
                        const bucketSec = 22 / (width / spanSec);

                        const buckets = new Map();
                        for (const a of ref.anomalies) {
                            const tSec = a.ts_ms / 1000;
                            if (tSec < xMin || tSec > xMax) continue;
                            const key = Math.floor(tSec / bucketSec);
                            let items = buckets.get(key);
                            if (!items) { items = []; buckets.set(key, items); }
                            items.push(a);
                        }

                        ref.markers = [];
                        buckets.forEach((items, key) => {
                            let rep = items[0];
                            // distinct kinds that fired in this moment (worst severity each)
                            const typeMap = new Map();
                            for (const a of items) {
                                const r = SEV_RANK[a.severity] || 1, rr = SEV_RANK[rep.severity] || 1;
                                if (r > rr || (r === rr && a.ts_ms > rep.ts_ms)) rep = a;
                                const cat = a.category || "Anomaly";
                                const seen = typeMap.get(cat);
                                if (!seen || r > (SEV_RANK[seen.severity] || 1)) {
                                    typeMap.set(cat, { category: cat, severity: a.severity });
                                }
                            }
                            const xp = u.valToPos(rep.ts_ms / 1000, "x", true);
                            if (xp < left || xp > left + width) return;
                            const reading = readingFor(ref, rep);
                            const yp = (typeof reading === "number") ? clampY(reading) : top + 10;
                            ref.markers.push({ x: xp, y: yp, key, rep, reading, count: items.length, types: Array.from(typeMap.values()) });
                        });

                        ctx.save();
                        for (const m of ref.markers) {
                            const color = SEV_COLOR[m.rep.severity] || SEV_COLOR.Info;
                            const hot = ref.hoverKey === m.key;
                            const r = hot ? (big ? 12 : 10) : (big ? 9 : 8);
                            // soft halo so markers pop without close inspection
                            ctx.beginPath();
                            ctx.arc(m.x, m.y, r + (hot ? 5 : 4), 0, Math.PI * 2);
                            ctx.fillStyle = hexToRgba(color, hot ? 0.30 : 0.16);
                            ctx.fill();
                            drawDiamond(ctx, m.x, m.y, r, color);
                            if (m.count > 1) {
                                ctx.fillStyle = "rgba(255,255,255,0.95)";
                                ctx.font = `bold ${big ? 12 : 11}px sans-serif`;
                                ctx.textAlign = "center";
                                ctx.textBaseline = "bottom";
                                ctx.fillText(String(m.count), m.x, m.y - r - 4);
                            }
                        }
                        ctx.restore();
                    },
                },
            });

            const makeChartOpts = (cfg, ref, height, big) => ({
                width: 320,
                height,
                legend: { show: false },
                cursor: { drag: { x: false, y: false }, y: false },
                scales: { x: { time: true }, y: { range: [cfg.min, cfg.max] } },
                axes: [
                    { stroke: "rgba(148,163,184,0.9)", grid: { stroke: "rgba(148,163,184,0.10)" }, ticks: { stroke: "rgba(148,163,184,0.2)" } },
                    { stroke: "rgba(148,163,184,0.9)", grid: { stroke: "rgba(148,163,184,0.10)" }, size: 48 },
                ],
                series: [{}, { stroke: cfg.stroke, width: 2, fill: hexToRgba(cfg.stroke, 0.10), points: { show: false } }],
                plugins: [zonesMarkersPlugin(cfg, ref, big)],
            });

            // Real timeline interaction for the expanded chart: scroll to zoom
            // (centred on the cursor), drag to pan, double-click to reset. All
            // clamped to the loaded data window.
            const wheelPanZoom = (getFull) => ({
                hooks: {
                    ready: (u) => {
                        const over = u.over;
                        over.style.cursor = "grab";
                        const clampToFull = (nMin, nMax) => {
                            const full = getFull();
                            if (!full) return [nMin, nMax];
                            const range = nMax - nMin;
                            if (range >= full[1] - full[0]) return [full[0], full[1]];
                            if (nMin < full[0]) { nMin = full[0]; nMax = nMin + range; }
                            if (nMax > full[1]) { nMax = full[1]; nMin = nMax - range; }
                            return [nMin, nMax];
                        };
                        over.addEventListener("wheel", (e) => {
                            e.preventDefault();
                            const rect = over.getBoundingClientRect();
                            const curMin = u.scales.x.min, curMax = u.scales.x.max;
                            const range = curMax - curMin;
                            const cursorVal = u.posToVal(e.clientX - rect.left, "x");
                            const leftPct = (cursorVal - curMin) / range;
                            const factor = e.deltaY < 0 ? 0.8 : 1.25;
                            const newRange = range * factor;
                            const [nMin, nMax] = clampToFull(cursorVal - leftPct * newRange, cursorVal - leftPct * newRange + newRange);
                            u.setScale("x", { min: nMin, max: nMax });
                        }, { passive: false });
                        over.addEventListener("mousedown", (e) => {
                            if (e.button !== 0) return;
                            const rect = over.getBoundingClientRect();
                            const startX = e.clientX;
                            const min0 = u.scales.x.min, max0 = u.scales.x.max;
                            const perPx = (max0 - min0) / rect.width;
                            over.__dragged = false;
                            over.style.cursor = "grabbing";
                            const move = (e2) => {
                                const dx = e2.clientX - startX;
                                if (Math.abs(dx) > 3) over.__dragged = true;
                                const d = dx * perPx;
                                const [nMin, nMax] = clampToFull(min0 - d, max0 - d);
                                u.setScale("x", { min: nMin, max: nMax });
                            };
                            const up = () => {
                                over.style.cursor = "grab";
                                document.removeEventListener("mousemove", move);
                                document.removeEventListener("mouseup", up);
                            };
                            document.addEventListener("mousemove", move);
                            document.addEventListener("mouseup", up);
                        });
                        over.addEventListener("dblclick", () => {
                            const full = getFull();
                            if (full) u.setScale("x", { min: full[0], max: full[1] });
                        });
                    },
                },
            });

            // ── tooltip (hover) ──────────────────────────────────────────
            const positionTooltip = (ev) => {
                const pad = 14;
                let x = ev.clientX + pad, y = ev.clientY + pad;
                const rect = tooltip.getBoundingClientRect();
                if (x + rect.width > window.innerWidth) x = ev.clientX - rect.width - pad;
                if (y + rect.height > window.innerHeight) y = ev.clientY - rect.height - pad;
                tooltip.style.left = `${x}px`;
                tooltip.style.top = `${y}px`;
            };
            const showAnomalyTooltip = (ev, m, cfg) => {
                const a = m.rep;
                const badge = `<span class="anomaly-tip-badge is-${(a.severity || "Info").toLowerCase()}">${a.severity || "Info"}</span>`;
                const countLine = m.count > 1
                    ? `<p class="anomaly-tip-count">${m.count} flags around this moment &middot; most severe shown</p>` : "";
                tooltip.classList.remove("is-value");
                tooltip.innerHTML =
                    `<div class="anomaly-tip-head">${badge}<span>${a.category || "Anomaly"}</span></div>` +
                    `<p class="anomaly-tip-headline">${a.headline || a.message || ""}</p>` +
                    countLine +
                    `<p class="anomaly-tip-time">Reading ${fmtVal(m.reading, cfg.unit)} at ${new Date(a.ts_ms).toLocaleTimeString()}</p>`;
                tooltip.hidden = false;
                positionTooltip(ev);
            };
            const showValueTooltip = (ev, u, cfg) => {
                const xs = u.data && u.data[0], ys = u.data && u.data[1];
                if (!xs || !xs.length) { hideTooltip(); return; }
                const rect = u.over.getBoundingClientRect();
                const t = u.posToVal(ev.clientX - rect.left, "x");
                let idx = -1, bestD = Infinity;
                for (let i = 0; i < xs.length; i++) {
                    if (ys[i] == null) continue;   // skip gap-breaks
                    const d = Math.abs(xs[i] - t);
                    if (d < bestD) { bestD = d; idx = i; }
                }
                if (idx < 0) { hideTooltip(); return; }
                tooltip.classList.add("is-value");
                tooltip.innerHTML =
                    `<p class="anomaly-tip-metric">${cfg.label}</p>` +
                    `<p class="anomaly-tip-value">${fmtVal(ys[idx], cfg.unit)}</p>` +
                    `<p class="anomaly-tip-time">${new Date(xs[idx] * 1000).toLocaleTimeString()}</p>`;
                tooltip.hidden = false;
                positionTooltip(ev);
            };
            const hideTooltip = () => { tooltip.hidden = true; };

            const nearestMarker = (ref, u, ev) => {
                const rect = u.over.getBoundingClientRect();
                // marker.x is canvas-relative (includes the y-axis width), while
                // the over element starts at the plot area — add bbox.left so the
                // mouse position lines up with the drawn markers.
                const canvasX = (ev.clientX - rect.left) * dpr() + u.bbox.left;
                let nearest = null, best = 14 * dpr();
                for (const m of ref.markers) {
                    const d = Math.abs(m.x - canvasX);
                    if (d <= best) { best = d; nearest = m; }
                }
                return nearest;
            };
            const attachHover = (ref, cfg) => {
                const over = ref.u.over;
                over.addEventListener("mousemove", (ev) => {
                    const m = nearestMarker(ref, ref.u, ev);
                    const newKey = m ? m.key : null;
                    if (ref.hoverKey !== newKey) { ref.hoverKey = newKey; ref.u.redraw(); }
                    if (m) { over.style.cursor = "pointer"; showAnomalyTooltip(ev, m, cfg); }
                    else { over.style.cursor = ref === modalState ? "grab" : "pointer"; showValueTooltip(ev, ref.u, cfg); }
                });
                over.addEventListener("mouseleave", () => {
                    if (ref.hoverKey != null) { ref.hoverKey = null; ref.u.redraw(); }
                    hideTooltip();
                });
            };

            // ── cards ────────────────────────────────────────────────────
            const buildCards = () => {
                grid.innerHTML = "";
                catalog.forEach((cfg, idx) => {
                    cfg.stroke = STROKES[idx % STROKES.length];
                    units[cfg.metric] = cfg.unit || "";
                    const card = document.createElement("article");
                    card.className = "insight-chart-card anomaly-chart-card";
                    card.innerHTML =
                        `<div class="anomaly-card-head"><div>` +
                        `<h3 class="anomaly-card-title">${cfg.label}</h3>` +
                        `<p class="anomaly-card-plain">${cfg.plain || ""}</p></div>` +
                        `<div class="anomaly-card-status">` +
                        `<span class="anomaly-card-value" data-live>--</span>` +
                        `<span class="anomaly-status-pill is-idle" data-status>--</span></div></div>` +
                        `<div class="anomaly-plot" data-plot></div>` +
                        `<div class="anomaly-card-foot"><span data-flags>No flags in this window</span>` +
                        `<span class="anomaly-card-expand">Click to expand &#8599;</span></div>`;
                    grid.appendChild(card);
                    const entry = charts[cfg.metric] = {
                        cfg,
                        plotEl: card.querySelector("[data-plot]"),
                        liveEl: card.querySelector("[data-live]"),
                        statusEl: card.querySelector("[data-status]"),
                        footEl: card.querySelector("[data-flags]"),
                        u: null, anomalies: [], markers: [], xs: [], ys: [],
                    };
                    card.addEventListener("click", () => openModal(cfg.metric));
                });
            };

            const makeCardChart = (entry) => {
                const opts = makeChartOpts(entry.cfg, entry, 220, false);
                opts.width = entry.plotEl.clientWidth || 320;
                entry.u = new uPlot(opts, [[], []], entry.plotEl);
                attachHover(entry, entry.cfg);
            };

            const applySeries = (entry, data) => {
                const pts = data.points || [];
                // Insert a null break wherever the device was off/not reporting,
                // so the line (and band) show a real hole instead of a long
                // misleading straight bridge across days of missing data.
                const stepSec = data.tier === "hourly" ? 3600 : 1;
                const gapSec = stepSec * 3;
                const xs = [], ys = [], mins = [], maxs = [];
                for (const p of pts) {
                    const t = p.t / 1000;
                    if (xs.length && t - xs[xs.length - 1] > gapSec) {
                        xs.push(xs[xs.length - 1] + stepSec);
                        ys.push(null); mins.push(null); maxs.push(null);
                    }
                    xs.push(t); ys.push(p.avg); mins.push(p.min); maxs.push(p.max);
                }
                entry.xs = xs;
                entry.ys = ys;
                entry.mins = mins;
                entry.maxs = maxs;
                entry.tier = data.tier;
                entry.anomalies = data.anomalies || [];
                if (!entry.u) makeCardChart(entry);
                entry.u.setData([entry.xs, entry.ys]);
                const last = entry.ys.length ? entry.ys[entry.ys.length - 1] : null;
                entry.liveEl.textContent = last != null ? fmtVal(last, entry.cfg.unit) : "no data yet";
                const st = statusFor(entry.cfg, last);
                entry.statusEl.textContent = st.label;
                entry.statusEl.className = `anomaly-status-pill ${st.cls}`;
                const n = entry.anomalies.length;
                entry.footEl.textContent = n ? `${n} flag${n === 1 ? "" : "s"} in this window` : "No flags in this window";
            };

            // ── expand modal ─────────────────────────────────────────────
            const renderPointDetail = (m, cfg) => {
                const a = m.rep;
                const unit = cfg.unit;
                const rows = [];
                rows.push(["What kind", a.category || "Anomaly"]);
                rows.push(["When", new Date(a.ts_ms).toLocaleString()]);
                if (m.reading != null) rows.push(["Reading at that time", fmtVal(m.reading, unit)]);
                // "how unusual" from the engine's derived measurements
                if (a.z_score != null) rows.push(["How unusual", `${Math.abs(a.z_score).toFixed(1)}× its normal variation`]);
                if (a.delta_value != null) rows.push(["Sudden change", `${a.delta_value > 0 ? "+" : ""}${fmtVal(a.delta_value, unit)}`]);
                if (a.slope_value != null) rows.push(["Rate of change", `${a.slope_value > 0 ? "+" : ""}${fmtVal(a.slope_value, unit)}/min`]);
                if (a.warning_limit) rows.push(["Warning limit", fmtVal(a.warning_limit, unit)]);
                if (a.critical_limit) rows.push(["Critical limit", fmtVal(a.critical_limit, unit)]);
                const sev = (a.severity || "Info").toLowerCase();
                const types = m.types || [];
                let note = "";
                if (types.length > 1) {
                    note = `<p class="anomaly-detail-count">${types.length} different checks flagged this moment:</p>` +
                        `<div class="anomaly-detail-types">` +
                        types.map((t) => `<span class="anomaly-type-chip is-${(t.severity || "Info").toLowerCase()}">${t.category}</span>`).join("") +
                        `</div>`;
                } else if (m.count > 1) {
                    note = `<p class="anomaly-detail-count">${m.count} flags fired around this moment. Showing the most severe.</p>`;
                }
                modalDetail.innerHTML =
                    `<div class="anomaly-detail-head">` +
                    `<span class="anomaly-tip-badge is-${sev}">${a.severity || "Info"}</span>` +
                    `<span class="anomaly-detail-cat">${a.category || "Anomaly"}</span></div>` +
                    `<p class="anomaly-detail-headline">${a.headline || a.message || ""}</p>` +
                    note +
                    `<dl class="anomaly-detail-grid">` +
                    rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("") +
                    `</dl>`;
            };

            const modalFull = () => {
                const xs = modalState.xs;
                return (xs && xs.length) ? [xs[0], xs[xs.length - 1]] : null;
            };

            const makeModalChart = () => {
                if (modalState.u) { modalState.u.destroy(); modalState.u = null; }
                const opts = makeChartOpts(modalState.cfg, modalState, 380, true);
                opts.width = modalPlot.clientWidth || 640;
                opts.plugins.push(wheelPanZoom(modalFull));
                modalState.u = new uPlot(opts, [[], []], modalPlot);
                attachHover(modalState, modalState.cfg);
                modalState.u.over.addEventListener("click", (ev) => {
                    if (modalState.u.over.__dragged) { modalState.u.over.__dragged = false; return; }
                    const near = nearestMarker(modalState, modalState.u, ev);
                    if (near) renderPointDetail(near, modalState.cfg);
                });
            };

            const syncModal = () => {
                if (!modalState.metric) return;
                const entry = charts[modalState.metric];
                if (!entry) return;
                modalState.anomalies = entry.anomalies;
                modalState.xs = entry.xs;
                modalState.ys = entry.ys;
                modalState.mins = entry.mins;
                modalState.maxs = entry.maxs;
                modalState.tier = entry.tier;
                // keep the user's current zoom/pan while live data streams in
                if (modalState.u) modalState.u.setData([entry.xs, entry.ys], false);
            };

            const openModal = (metric) => {
                const entry = charts[metric];
                if (!entry) return;
                hideTooltip();
                modalState.metric = metric;
                modalState.cfg = entry.cfg;
                modalState.anomalies = entry.anomalies;
                modalState.xs = entry.xs;
                modalState.ys = entry.ys;
                modalState.mins = entry.mins;
                modalState.maxs = entry.maxs;
                modalState.tier = entry.tier;
                modalTitle.textContent = entry.cfg.label;
                modalSub.textContent = entry.cfg.plain || "";
                modalDetail.innerHTML = '<p class="insights-empty-note">Click a marked point on the chart to see what happened.</p>';
                modal.hidden = false;
                document.body.classList.add("anomaly-modal-open");
                makeModalChart();
                modalState.u.setData([entry.xs, entry.ys]);
            };
            const closeModal = () => {
                modal.hidden = true;
                document.body.classList.remove("anomaly-modal-open");
                modalState.metric = null;
                if (modalState.u) { modalState.u.destroy(); modalState.u = null; }
            };
            modal.querySelectorAll("[data-anomaly-modal-close]").forEach((el) => el.addEventListener("click", closeModal));
            document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !modal.hidden) closeModal(); });

            // ── summary + grouped issues ─────────────────────────────────
            const updateCounts = (counts) => {
                counts = counts || {};
                ["Critical", "Warning", "Info", "total"].forEach((k) => {
                    const el = root.querySelector(`[data-anomaly-count="${k}"]`);
                    if (el) el.textContent = counts[k] || 0;
                });
                const totalStat = root.querySelector('[data-anomaly-count="total"]');
                const totalLabel = totalStat && totalStat.closest(".anomaly-stat") && totalStat.closest(".anomaly-stat").querySelector(".anomaly-stat-label");
                if (totalLabel) totalLabel.textContent = `Flagged in last ${RANGE_LABELS[currentRange]}`;
            };

            // Which issue rows the user has expanded; keyed so the state
            // survives the 5s re-render.
            const expandedGroups = new Set();
            const groupKey = (g) => `${g.metric}|${g.category}|${g.severity}`;
            const renderGroups = (groups) => {
                if (!groups || !groups.length) {
                    groupsList.innerHTML = '<p class="insights-empty-note">No anomalies in this window. That is a good sign.</p>';
                    return;
                }
                groupsList.innerHTML = groups.map((g) => {
                    const sev = (g.severity || "Info").toLowerCase();
                    const key = groupKey(g);
                    const open = expandedGroups.has(key);
                    const unit = units[g.metric] || "";
                    let valueText = "";
                    if (g.latest_value != null) {
                        valueText = (g.min_value != null && g.max_value != null && g.min_value !== g.max_value)
                            ? `${fmtVal(g.min_value, unit)}–${fmtVal(g.max_value, unit)}`
                            : fmtVal(g.latest_value, unit);
                        valueText = ` &middot; ${valueText}`;
                    }
                    const advice = g.latest_message || g.latest_headline || "";
                    return `<div class="anomaly-group${open ? " is-open" : ""}" data-group-key="${key}">` +
                        `<div class="anomaly-group-row" role="button" tabindex="0">` +
                        `<span class="anomaly-dot is-${sev}"></span>` +
                        `<div class="anomaly-group-body">` +
                        `<p class="anomaly-group-headline">${g.metric_label || "Device"}: ${g.category || "Anomaly"}</p>` +
                        `<p class="anomaly-group-meta">latest ${fmtAgo(g.latest_ts)}${valueText}</p></div>` +
                        `<span class="anomaly-group-count">${g.count}&times;</span>` +
                        `<span class="anomaly-group-chevron" aria-hidden="true">&#9662;</span>` +
                        `</div>` +
                        `<div class="anomaly-group-detail" data-group-detail ${open ? "" : "hidden"}>` +
                        (g.latest_headline ? `<p class="anomaly-group-detail-headline">${g.latest_headline}</p>` : "") +
                        (advice ? `<p class="anomaly-group-advice"><strong>What could be wrong:</strong> ${advice}</p>` : "") +
                        `</div>` +
                        `</div>`;
                }).join("");
            };
            // One delegated listener; survives every re-render.
            groupsList.addEventListener("click", (ev) => {
                const group = ev.target.closest("[data-group-key]");
                if (!group) return;
                const key = group.getAttribute("data-group-key");
                const detail = group.querySelector("[data-group-detail]");
                const nowOpen = !group.classList.contains("is-open");
                group.classList.toggle("is-open", nowOpen);
                if (detail) detail.hidden = !nowOpen;
                if (nowOpen) expandedGroups.add(key); else expandedGroups.delete(key);
            });

            // ── detection coverage strip ─────────────────────────────────
            const buildCoverage = () => {
                if (!coverageEl) return;
                if (!checks.length) { coverageEl.innerHTML = ""; return; }
                coverageEl.innerHTML = checks.map((c) =>
                    `<div class="anomaly-coverage-card" data-coverage-cat="${c.category}">` +
                    `<div class="anomaly-coverage-head">` +
                    `<span class="anomaly-coverage-name">${c.title}</span>` +
                    `<span class="anomaly-coverage-count" data-coverage-count>0</span></div>` +
                    `<p class="anomaly-coverage-detail">${c.detail}</p></div>`
                ).join("");
            };
            const updateCoverageCounts = (catCounts) => {
                if (!coverageEl) return;
                catCounts = catCounts || {};
                coverageEl.querySelectorAll("[data-coverage-cat]").forEach((card) => {
                    const n = catCounts[card.getAttribute("data-coverage-cat")] || 0;
                    const el = card.querySelector("[data-coverage-count]");
                    if (el) el.textContent = n;
                    card.classList.toggle("is-active", n > 0);
                });
            };

            // ── refresh loop ─────────────────────────────────────────────
            const refreshAll = async () => {
                if (root.hidden) return;
                const to = Date.now();
                const from = to - RANGES[currentRange];
                await Promise.all(catalog.map(async (cfg) => {
                    const entry = charts[cfg.metric];
                    if (!entry) return;
                    try {
                        const r = await fetch(`/api/monitor/timeseries?metric=${encodeURIComponent(cfg.metric)}&from=${from}&to=${to}`);
                        if (!r.ok) return;
                        applySeries(entry, await r.json());
                    } catch (err) { /* ignore transient */ }
                }));
                syncModal();
                try {
                    const r = await fetch(`/api/monitor/anomalies/grouped?since=${from}`);
                    if (r.ok) {
                        const data = await r.json();
                        updateCounts(data.counts);
                        renderGroups(data.groups);
                        updateCoverageCounts(data.category_counts);
                    }
                } catch (err) { /* ignore */ }
            };

            const resizeAll = () => {
                Object.values(charts).forEach((entry) => {
                    if (entry.u) entry.u.setSize({ width: entry.plotEl.clientWidth || 320, height: 220 });
                });
                if (modalState.u && !modal.hidden) {
                    modalState.u.setSize({ width: modalPlot.clientWidth || 640, height: 380 });
                }
            };

            rangeButtons.forEach((btn) => btn.addEventListener("click", () => {
                rangeButtons.forEach((b) => b.classList.toggle("is-current", b === btn));
                currentRange = btn.getAttribute("data-anomaly-range");
                refreshAll();
            }));

            const activate = async () => {
                if (started) { resizeAll(); refreshAll(); return; }
                started = true;
                // The console content sits inside a backdrop-filtered ancestor,
                // which would trap position:fixed. Move the overlay + tooltip to
                // <body> so they anchor to the viewport instead.
                document.body.appendChild(modal);
                document.body.appendChild(tooltip);
                if (typeof window.uPlot !== "function") {
                    grid.innerHTML = '<p class="insights-empty-note">Charts unavailable (uPlot failed to load).</p>';
                    return;
                }
                try {
                    const cfg = await fetch("/api/monitor/anomaly-config").then((r) => r.json());
                    catalog = cfg.charts || [];
                    checks = cfg.checks || [];
                } catch (err) {
                    catalog = [];
                    checks = [];
                }
                buildCoverage();
                if (!catalog.length) {
                    grid.innerHTML = '<p class="insights-empty-note">No monitored metrics available.</p>';
                    return;
                }
                buildCards();
                await refreshAll();
                if (!refreshTimer) refreshTimer = window.setInterval(refreshAll, 5000);
                window.addEventListener("resize", resizeAll);
            };

            return { activate, resizeAll };
        })();

        // ── Live / Anomaly tab switching ────────────────────────────────
        const monitorTabs = Array.from(monitorShell.querySelectorAll("[data-monitor-tab]"));
        const monitorPanels = Array.from(monitorShell.querySelectorAll("[data-monitor-panel]"));
        const showMonitorTab = (tabId) => {
            monitorTabs.forEach((t) => {
                const cur = t.getAttribute("data-monitor-tab") === tabId;
                t.classList.toggle("is-current", cur);
                t.setAttribute("aria-selected", cur ? "true" : "false");
            });
            monitorPanels.forEach((p) => {
                const cur = p.getAttribute("data-monitor-panel") === tabId;
                p.classList.toggle("is-hidden", !cur);
                p.hidden = !cur;
            });
            if (tabId === "anomaly") anomalyController.activate();
        };
        monitorTabs.forEach((t) => t.addEventListener("click", () => showMonitorTab(t.getAttribute("data-monitor-tab"))));
    }

    // ── Overview: self-monitoring / anomaly explainer band ──────────────
    const overviewAnomaly = document.querySelector("[data-overview-anomaly]");
    if (overviewAnomaly) {
        const checksEl = overviewAnomaly.querySelector("[data-overview-anomaly-checks]");
        const load = async () => {
            try {
                const r = await fetch("/api/monitor/anomaly-config");
                if (!r.ok) return;
                const cfg = await r.json();
                if (checksEl && Array.isArray(cfg.checks)) {
                    checksEl.innerHTML = cfg.checks.map((c) =>
                        `<div class="ov-anomaly-check">` +
                        `<p class="ov-anomaly-check-title">${c.title}</p>` +
                        `<p class="ov-anomaly-check-detail">${c.detail}</p>` +
                        `</div>`
                    ).join("");
                }
            } catch (err) { /* overview band is best-effort */ }
        };
        load();
    }

    const interfacesShell = document.querySelector("[data-interfaces-shell]");
    if (interfacesShell) {
        // ── Interface type panel switching ─────────────────────────────────────
        const ifaceTypeBtns = Array.from(interfacesShell.querySelectorAll("[data-iface-type]"));
        const ifacePanels = Array.from(interfacesShell.querySelectorAll("[data-iface-panel]"));

        const switchIfacePanel = (type) => {
            ifaceTypeBtns.forEach((btn) => {
                const isActive = btn.getAttribute("data-iface-type") === type;
                btn.classList.toggle("is-current", isActive);
                if (!btn.classList.contains("is-locked")) {
                    btn.classList.toggle("is-preview", !isActive);
                }
                btn.setAttribute("aria-pressed", isActive ? "true" : "false");
            });
            ifacePanels.forEach((panel) => {
                panel.style.display = panel.getAttribute("data-iface-panel") === type ? "" : "none";
            });
        };

        ifaceTypeBtns.forEach((btn) => {
            btn.addEventListener("click", () => switchIfacePanel(btn.getAttribute("data-iface-type")));
        });

        // ── RS485 port tab switching ───────────────────────────────────────────
        const rtuTabBtns = Array.from(interfacesShell.querySelectorAll("[data-rtu-tab-btn]"));
        const rtuPanes = Array.from(interfacesShell.querySelectorAll("[data-rtu-port]"));

        rtuTabBtns.forEach((btn) => {
            btn.addEventListener("click", () => {
                const portId = btn.getAttribute("data-rtu-tab-btn");
                rtuTabBtns.forEach((b) => b.classList.toggle("is-active", b === btn));
                rtuPanes.forEach((p) => {
                    p.style.display = p.getAttribute("data-rtu-port") === portId ? "" : "none";
                });
            });
        });

        // ── RS232 port tabs ────────────────────────────────────────────────────
        const tabBtns = Array.from(interfacesShell.querySelectorAll("[data-rs232-tab-btn]"));
        const portPanes = Array.from(interfacesShell.querySelectorAll("[data-rs232-port]"));

        const switchTab = (portId) => {
            tabBtns.forEach((btn) => {
                btn.classList.toggle("is-active", btn.getAttribute("data-rs232-tab-btn") === portId);
            });
            portPanes.forEach((pane) => {
                pane.style.display = pane.getAttribute("data-rs232-port") === portId ? "" : "none";
            });
        };

        tabBtns.forEach((btn) => {
            btn.addEventListener("click", () => switchTab(btn.getAttribute("data-rs232-tab-btn")));
        });

        // ── Enable toggle per port ─────────────────────────────────────────────
        portPanes.forEach((pane) => {
            const portId = pane.getAttribute("data-rs232-port");
            const enableToggle = pane.querySelector("[data-rs232-enable]");
            const portBody = pane.querySelector("[data-rs232-port-body]");
            const disabledNote = pane.querySelector("[data-rs232-disabled-note]");
            const statusBadge = pane.querySelector(".iface-port-status");
            const tabDot = interfacesShell.querySelector(`[data-rs232-tab-dot="${portId}"]`);

            const applyPortState = (enabled) => {
                if (portBody) portBody.style.display = enabled ? "" : "none";
                if (disabledNote) disabledNote.style.display = enabled ? "none" : "";
                if (statusBadge) {
                    statusBadge.className = `iface-port-status ${enabled ? "is-active" : "is-idle"}`;
                    statusBadge.textContent = enabled ? "Active" : "Idle";
                }
                if (tabDot) {
                    tabDot.className = `iface-port-tab-dot ${enabled ? "is-active" : "is-idle"}`;
                }
            };

            if (enableToggle) {
                enableToggle.addEventListener("change", () => applyPortState(enableToggle.checked));
            }

            const modeButtons = Array.from(pane.querySelectorAll("[data-rs232-mode]"));
            const applyMode = (mode) => {
                modeButtons.forEach((button) => {
                    const selected = button.getAttribute("data-rs232-mode") === mode;
                    button.classList.toggle("is-current", selected);
                    button.setAttribute("aria-pressed", selected ? "true" : "false");
                });
                pane.querySelectorAll("[data-rs232-mode-content]").forEach((content) => {
                    content.style.display = content.getAttribute("data-rs232-mode-content") === mode ? "" : "none";
                });
            };
            modeButtons.forEach((button) => button.addEventListener("click", () => applyMode(button.getAttribute("data-rs232-mode"))));

            // ── Alarm accordion per port ───────────────────────────────────────
            pane.querySelectorAll("[data-alarm-toggle]").forEach((toggleBtn) => {
                const row = toggleBtn.closest("[data-alarm-ch]");
                const body = row?.querySelector("[data-alarm-body]");
                toggleBtn.addEventListener("click", () => {
                    const open = row.classList.toggle("is-open");
                    if (body) body.style.display = open ? "" : "none";
                });
            });

            // ── Analog output state → enable/disable channel select ────────────
            const analogStateSelect = pane.querySelector("[data-rs232-analog='state']");
            const analogChannelGroup = pane.querySelector("[data-analog-channel-group]");
            const analogChannelSelect = pane.querySelector("[data-rs232-analog='channel']");

            if (analogStateSelect) {
                const applyAnalogState = (state) => {
                    const off = state === "off";
                    if (analogChannelGroup) {
                        analogChannelGroup.style.opacity = off ? "0.45" : "";
                        analogChannelGroup.style.pointerEvents = off ? "none" : "";
                    }
                    if (analogChannelSelect) analogChannelSelect.disabled = off;
                };
                analogStateSelect.addEventListener("change", () => applyAnalogState(analogStateSelect.value));
            }
        });

        // ── Payload builder ────────────────────────────────────────────────────
        const buildPayload = () => {
            const buildPort = (portId) => {
                const pane = interfacesShell.querySelector(`[data-rs232-port="${portId}"]`);
                if (!pane) return null;

                const enabled = pane.querySelector("[data-rs232-enable]")?.checked ?? false;

                // Serial
                const serial = {};
                pane.querySelectorAll("[data-rs232-serial]").forEach((el) => {
                    const key = el.getAttribute("data-rs232-serial");
                    serial[key] = ["baud_rate", "stop_bits", "data_bits"].includes(key)
                        ? parseInt(el.value, 10)
                        : el.value;
                });

                // Polling
                const polling = {};
                pane.querySelectorAll("[data-rs232-poll]").forEach((el) => {
                    polling[el.getAttribute("data-rs232-poll")] = el.checked;
                });

                // Driver
                const driver = {};
                pane.querySelectorAll("[data-rs232-driver]").forEach((el) => {
                    driver[el.getAttribute("data-rs232-driver")] = el.checked;
                });

                // Alarms: collect by channel
                const alarms = {};
                pane.querySelectorAll("[data-rs232-alarm]").forEach((el) => {
                    const ch = el.getAttribute("data-rs232-alarm");
                    const field = el.getAttribute("data-rs232-alarm-field");
                    if (!alarms[ch]) alarms[ch] = {};
                    if (el.type === "checkbox") {
                        alarms[ch][field] = el.checked;
                    } else if (el.type === "number") {
                        alarms[ch][field] = parseFloat(el.value) || 0;
                    } else {
                        alarms[ch][field] = el.value;
                    }
                });

                // Analog output
                const analog = {};
                pane.querySelectorAll("[data-rs232-analog]").forEach((el) => {
                    const key = el.getAttribute("data-rs232-analog");
                    analog[key] = el.type === "number" ? parseFloat(el.value) || 0 : el.value;
                });
                if (analog.state === "off") analog.channel = null;

                const selectedMode = pane.querySelector("[data-rs232-mode].is-current")?.getAttribute("data-rs232-mode") || "sensor";
                const sniffer = {};
                pane.querySelectorAll("[data-rs232-sniffer]").forEach((el) => {
                    const key = el.getAttribute("data-rs232-sniffer");
                    if (el.type === "checkbox") sniffer[key] = el.checked;
                    else if (el.type === "number") sniffer[key] = parseInt(el.value, 10) || 0;
                    else sniffer[key] = el.value;
                });
                const capture = { format: "jsonl" };
                pane.querySelectorAll("[data-rs232-capture]").forEach((el) => {
                    const key = el.getAttribute("data-rs232-capture");
                    capture[key] = el.type === "checkbox" ? el.checked : (parseInt(el.value, 10) || 0);
                });
                sniffer.capture = capture;

                return {
                    enabled,
                    mode: selectedMode,
                    serial,
                    sensor: "dustrak",
                    dustrak: { polling, driver, alarms, analog_output: analog },
                    sniffer,
                };
            };

            return {
                version: 1,
                rs232: { port_0: buildPort("0"), port_1: buildPort("1") },
            };
        };

        // ── Save button ────────────────────────────────────────────────────────
        const saveBtn = interfacesShell.querySelector("[data-iface-save]");
        const saveMessage = interfacesShell.querySelector("[data-iface-save-message]");

        if (saveBtn) {
            saveBtn.addEventListener("click", async () => {
                if (saveMessage) {
                    saveMessage.textContent = "";
                    saveMessage.classList.remove("is-success");
                }
                saveBtn.disabled = true;
                saveBtn.textContent = "Saving…";
                try {
                    const response = await fetch("/api/interfaces/rs232/config", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(buildPayload()),
                    });
                    const data = await response.json();
                    if (saveMessage) {
                        saveMessage.textContent = data.message || (response.ok ? "Saved." : "Save failed.");
                        saveMessage.classList.toggle("is-success", response.ok && data.ok);
                    }
                } catch {
                    if (saveMessage) saveMessage.textContent = "Could not reach the gateway.";
                } finally {
                    saveBtn.disabled = false;
                    saveBtn.textContent = "Save Interface Configuration";
                }
            });
        }

        // ── Shared: register table add/delete row ──────────────────────────────
        const REG_ROW_HTML = () => `
            <tr data-reg-row>
                <td><input type="text" class="iface-number iface-reg-input" data-reg-field="name" placeholder="e.g. Temperature"></td>
                <td><select class="iface-select iface-select-sm" data-reg-field="register_type">
                    <option value="coil">Coil (0x)</option>
                    <option value="discrete_input">Discrete Input (1x)</option>
                    <option value="input_register">Input Reg (3x)</option>
                    <option value="holding_register" selected>Holding Reg (4x)</option>
                </select></td>
                <td><input type="number" class="iface-number iface-reg-input" data-reg-field="address" min="0" max="65535" value="40001"></td>
                <td><select class="iface-select iface-select-sm" data-reg-field="data_type">
                    <option value="uint16" selected>UInt16</option>
                    <option value="int16">Int16</option>
                    <option value="uint32">UInt32</option>
                    <option value="int32">Int32</option>
                    <option value="float32">Float32</option>
                    <option value="bool">Bool</option>
                </select></td>
                <td><select class="iface-select iface-select-sm" data-reg-field="word_order">
                    <option value="big" selected>Big</option>
                    <option value="little">Little</option>
                </select></td>
                <td><input type="number" class="iface-number iface-reg-input" data-reg-field="scale" step="any" value="1"></td>
                <td><input type="text" class="iface-number iface-reg-input" data-reg-field="unit" placeholder="°C"></td>
                <td><button type="button" class="iface-reg-delete-btn" data-reg-delete title="Remove">✕</button></td>
            </tr>`;

        const wireRegTable = (container) => {
            const tbody = container.querySelector("[data-reg-tbody]");
            const addBtn = container.querySelector("[data-reg-add]");
            const empty = container.querySelector("[data-reg-empty]");

            const refreshEmpty = () => {
                const hasRows = tbody.querySelectorAll("[data-reg-row]").length > 0;
                if (empty) empty.style.display = hasRows ? "none" : "";
            };

            if (addBtn) {
                addBtn.addEventListener("click", () => {
                    const tmp = document.createElement("tbody");
                    tmp.innerHTML = REG_ROW_HTML();
                    const row = tmp.firstElementChild;
                    row.querySelector("[data-reg-delete]").addEventListener("click", () => {
                        row.remove(); refreshEmpty();
                    });
                    tbody.appendChild(row);
                    refreshEmpty();
                });
            }

            tbody.querySelectorAll("[data-reg-delete]").forEach((btn) => {
                btn.addEventListener("click", () => { btn.closest("[data-reg-row]").remove(); refreshEmpty(); });
            });
            refreshEmpty();
        };

        const readRegTable = (container) => {
            return Array.from(container.querySelectorAll("[data-reg-row]")).map((row) => {
                const f = (attr) => row.querySelector(`[data-reg-field="${attr}"]`)?.value ?? "";
                return {
                    name: f("name"),
                    register_type: f("register_type"),
                    address: parseInt(f("address"), 10) || 0,
                    data_type: f("data_type"),
                    word_order: f("word_order"),
                    scale: parseFloat(f("scale")) || 1,
                    unit: f("unit"),
                };
            });
        };

        // ── RS485 panel ────────────────────────────────────────────────────────
        const rs485Panel = interfacesShell.querySelector("[data-iface-panel='rs485']");
        if (rs485Panel) {
            // Wire register tables
            rs485Panel.querySelectorAll("[data-reg-table]").forEach(wireRegTable);

            // Enable toggles
            rs485Panel.querySelectorAll("[data-rtu-port]").forEach((pane) => {
                const portId = pane.getAttribute("data-rtu-port");
                const toggle = pane.querySelector("[data-rtu-enable]");
                const body = pane.querySelector("[data-rtu-port-body]");
                const note = pane.querySelector("[data-rtu-disabled-note]");
                const status = pane.querySelector(".iface-port-status");
                const dot = rs485Panel.querySelector(`[data-rtu-tab-dot="${portId}"]`);

                const apply = (enabled) => {
                    if (body) body.style.display = enabled ? "" : "none";
                    if (note) note.style.display = enabled ? "none" : "";
                    if (status) { status.className = `iface-port-status ${enabled ? "is-active" : "is-idle"}`; status.textContent = enabled ? "Active" : "Idle"; }
                    if (dot) dot.className = `iface-port-tab-dot ${enabled ? "is-active" : "is-idle"}`;
                };

                if (toggle) toggle.addEventListener("change", () => apply(toggle.checked));
            });

            // Save
            const rtuSaveBtn = rs485Panel.querySelector("[data-rtu-save]");
            const rtuSaveMsg = rs485Panel.querySelector("[data-rtu-save-message]");

            const buildRtuPayload = () => {
                const buildPort = (portId) => {
                    const pane = rs485Panel.querySelector(`[data-rtu-port="${portId}"]`);
                    if (!pane) return null;
                    const serial = {};
                    pane.querySelectorAll("[data-rtu-serial]").forEach((el) => {
                        const k = el.getAttribute("data-rtu-serial");
                        serial[k] = ["baud_rate", "stop_bits", "data_bits"].includes(k) ? parseInt(el.value, 10) : el.value;
                    });
                    const modbus_rtu = { registers: readRegTable(pane.querySelector("[data-reg-table]")) };
                    pane.querySelectorAll("[data-rtu-modbus]").forEach((el) => {
                        const k = el.getAttribute("data-rtu-modbus");
                        modbus_rtu[k] = parseInt(el.value, 10) || 0;
                    });
                    return {
                        enabled: pane.querySelector("[data-rtu-enable]")?.checked ?? false,
                        serial,
                        modbus_rtu,
                    };
                };
                return { version: 1, rs485: { port_2: buildPort("0"), port_3: buildPort("1") } };
            };

            if (rtuSaveBtn) {
                rtuSaveBtn.addEventListener("click", async () => {
                    if (rtuSaveMsg) { rtuSaveMsg.textContent = ""; rtuSaveMsg.classList.remove("is-success"); }
                    rtuSaveBtn.disabled = true; rtuSaveBtn.textContent = "Saving…";
                    try {
                        const res = await fetch("/api/interfaces/rs485/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildRtuPayload()) });
                        const data = await res.json();
                        if (rtuSaveMsg) { rtuSaveMsg.textContent = data.message || (res.ok ? "Saved." : "Save failed."); rtuSaveMsg.classList.toggle("is-success", res.ok && data.ok); }
                    } catch { if (rtuSaveMsg) rtuSaveMsg.textContent = "Could not reach the gateway."; }
                    finally { rtuSaveBtn.disabled = false; rtuSaveBtn.textContent = "Save RS485 Configuration"; }
                });
            }
        }

        // ── Modbus TCP panel ───────────────────────────────────────────────────
        const mtcpPanel = interfacesShell.querySelector("[data-iface-panel='modbus-tcp']");
        if (mtcpPanel) {
            const mtcpList = mtcpPanel.querySelector("[data-mtcp-list]");
            const mtcpCount = mtcpPanel.querySelector("[data-mtcp-count]");
            const MAX_CONN = 10;

            const updateMtcpCount = () => {
                const n = mtcpList.querySelectorAll("[data-mtcp-conn]").length;
                if (mtcpCount) mtcpCount.textContent = `${n} / ${MAX_CONN}`;
                const addBtn = mtcpPanel.querySelector("[data-mtcp-add-conn]");
                if (addBtn) addBtn.disabled = n >= MAX_CONN;
            };

            const wireMtcpConn = (connEl) => {
                // Accordion toggle
                const header = connEl.querySelector("[data-mtcp-conn-toggle]");
                const body = connEl.querySelector("[data-mtcp-conn-body]");
                const chevron = connEl.querySelector(".iface-alarm-chevron");
                if (header) header.addEventListener("click", () => {
                    const open = connEl.classList.toggle("is-open");
                    if (body) body.style.display = open ? "" : "none";
                    if (chevron) chevron.style.transform = open ? "rotate(90deg)" : "";
                });

                // Live summary update
                const nameInput = connEl.querySelector("[data-mtcp-field='name']");
                const ifaceSelect = connEl.querySelector("[data-mtcp-field='interface']");
                const ipInput = connEl.querySelector("[data-mtcp-field='ip']");
                const portInput = connEl.querySelector("[data-mtcp-field='port']");
                const unitInput = connEl.querySelector("[data-mtcp-field='unit_id']");
                const nameLabel = connEl.querySelector("[data-mtcp-conn-name-label]");
                const summary = connEl.querySelector("[data-mtcp-conn-summary]");
                const dot = connEl.querySelector("[data-mtcp-conn-dot]");
                const enableToggle = connEl.querySelector("[data-mtcp-conn-enable]");

                const refreshSummary = () => {
                    if (nameLabel && nameInput) nameLabel.textContent = nameInput.value || "Unnamed";
                    if (summary) summary.textContent = `${ifaceSelect?.value ?? "eth0"} · ${ipInput?.value || "—"}:${portInput?.value || "502"} · Unit ${unitInput?.value || "1"}`;
                };
                const refreshDot = () => {
                    if (dot) dot.className = `iface-conn-status-dot ${enableToggle?.checked ? "is-active" : "is-idle"}`;
                };

                [nameInput, ifaceSelect, ipInput, portInput, unitInput].forEach((el) => el?.addEventListener("input", refreshSummary));
                enableToggle?.addEventListener("change", refreshDot);

                // Delete connection
                connEl.querySelector("[data-mtcp-del-conn]")?.addEventListener("click", () => {
                    connEl.remove();
                    updateMtcpCount();
                    const empty = mtcpList.querySelector("[data-mtcp-empty]");
                    if (empty) empty.style.display = mtcpList.querySelectorAll("[data-mtcp-conn]").length === 0 ? "" : "none";
                });

                // Wire register table
                const regTable = connEl.querySelector("[data-reg-table]");
                if (regTable) wireRegTable(regTable);
            };

            // Wire existing connections
            mtcpList.querySelectorAll("[data-mtcp-conn]").forEach(wireMtcpConn);

            // Add connection
            const addConnBtn = mtcpPanel.querySelector("[data-mtcp-add-conn]");
            if (addConnBtn) {
                addConnBtn.addEventListener("click", () => {
                    if (mtcpList.querySelectorAll("[data-mtcp-conn]").length >= MAX_CONN) return;
                    const empty = mtcpList.querySelector("[data-mtcp-empty]");
                    if (empty) empty.style.display = "none";
                    const tmpl = document.createElement("template");
                    tmpl.innerHTML = `
<div class="iface-alarm-row is-open" data-mtcp-conn>
    <button type="button" class="iface-alarm-header" data-mtcp-conn-toggle>
        <span class="iface-conn-status-dot is-idle" data-mtcp-conn-dot></span>
        <span class="iface-alarm-ch-label" style="min-width:auto;flex:1" data-mtcp-conn-name-label>New Device</span>
        <span class="iface-alarm-summary" data-mtcp-conn-summary>eth0 · —:502 · Unit 1</span>
        <span class="iface-alarm-chevron" style="transform:rotate(90deg)">▸</span>
    </button>
    <div class="iface-alarm-body" data-mtcp-conn-body style="display:block">
        <div class="iface-modbus-tcp-grid" style="margin-bottom:1rem">
            <label class="iface-field-group"><span class="iface-field-label">Name</span><input type="text" class="iface-number" data-mtcp-field="name" value="New Device"></label>
            <label class="iface-field-group"><span class="iface-field-label">Enabled</span><label class="iface-toggle" style="margin-top:0.35rem"><input type="checkbox" class="iface-toggle-input" data-mtcp-conn-enable><span class="iface-toggle-track" aria-hidden="true"></span></label></label>
            <label class="iface-field-group"><span class="iface-field-label">Ethernet Interface</span><select class="iface-select" data-mtcp-field="interface"><option value="eth0" selected>eth0 — Primary</option><option value="eth1">eth1 — Secondary</option></select></label>
            <label class="iface-field-group"><span class="iface-field-label">Device IP</span><input type="text" class="iface-number" data-mtcp-field="ip" placeholder="192.168.1.100"></label>
            <label class="iface-field-group"><span class="iface-field-label">Port</span><input type="number" class="iface-number" min="1" max="65535" data-mtcp-field="port" value="502"></label>
            <label class="iface-field-group"><span class="iface-field-label">Unit ID (1–247)</span><input type="number" class="iface-number" min="1" max="247" data-mtcp-field="unit_id" value="1"></label>
            <label class="iface-field-group"><span class="iface-field-label">Poll Interval</span><select class="iface-select" data-mtcp-field="poll_interval_ms"><option value="500">500 ms</option><option value="1000" selected>1 s</option><option value="2000">2 s</option><option value="5000">5 s</option><option value="10000">10 s</option></select></label>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem">
            <p class="iface-section-eyebrow" style="margin:0">Register Map</p>
            <button type="button" class="iface-reg-delete-btn" style="padding:0.3rem 0.8rem;border-radius:0.5rem" data-mtcp-del-conn>Remove Connection</button>
        </div>
        <div data-reg-table><table class="iface-register-table"><thead><tr><th>Name</th><th>Register Type</th><th>Address</th><th>Data Type</th><th>Word Order</th><th>Scale</th><th>Unit</th><th></th></tr></thead><tbody data-reg-tbody><tr class="iface-register-empty" data-reg-empty><td colspan="8">No registers defined — click Add Register to start</td></tr></tbody></table><button type="button" class="iface-add-register-btn" data-reg-add>+ Add Register</button></div>
    </div>
</div>`;
                    const connEl = tmpl.content.firstElementChild;
                    mtcpList.appendChild(connEl);
                    wireMtcpConn(connEl);
                    updateMtcpCount();
                });
            }

            // Save
            const mtcpSaveBtn = mtcpPanel.querySelector("[data-mtcp-save]");
            const mtcpSaveMsg = mtcpPanel.querySelector("[data-mtcp-save-message]");

            const buildMtcpPayload = () => {
                const connections = Array.from(mtcpList.querySelectorAll("[data-mtcp-conn]")).map((connEl, i) => {
                    const f = (attr) => connEl.querySelector(`[data-mtcp-field="${attr}"]`)?.value ?? "";
                    return {
                        id: `conn_${i + 1}`,
                        name: f("name") || "Unnamed Device",
                        enabled: connEl.querySelector("[data-mtcp-conn-enable]")?.checked ?? false,
                        interface: f("interface") || "eth0",
                        ip: f("ip"),
                        port: parseInt(f("port"), 10) || 502,
                        unit_id: parseInt(f("unit_id"), 10) || 1,
                        poll_interval_ms: parseInt(f("poll_interval_ms"), 10) || 1000,
                        registers: readRegTable(connEl.querySelector("[data-reg-table]")),
                    };
                });
                return { version: 1, max_connections: MAX_CONN, connections };
            };

            if (mtcpSaveBtn) {
                mtcpSaveBtn.addEventListener("click", async () => {
                    if (mtcpSaveMsg) { mtcpSaveMsg.textContent = ""; mtcpSaveMsg.classList.remove("is-success"); }
                    mtcpSaveBtn.disabled = true; mtcpSaveBtn.textContent = "Saving…";
                    try {
                        const res = await fetch("/api/interfaces/modbus-tcp/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildMtcpPayload()) });
                        const data = await res.json();
                        if (mtcpSaveMsg) { mtcpSaveMsg.textContent = data.message || (res.ok ? "Saved." : "Save failed."); mtcpSaveMsg.classList.toggle("is-success", res.ok && data.ok); }
                    } catch { if (mtcpSaveMsg) mtcpSaveMsg.textContent = "Could not reach the gateway."; }
                    finally { mtcpSaveBtn.disabled = false; mtcpSaveBtn.textContent = "Save Modbus TCP Configuration"; }
                });
            }
        }
    }

    const loginForm = document.querySelector(".auth-form");
    const loginError = document.querySelector("[data-login-error]");

    if (loginForm) {
        loginForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            const formData = new FormData(loginForm);
            const payload = {
                username: String(formData.get("username") || ""),
                password: String(formData.get("password") || ""),
            };

            if (loginError) {
                loginError.textContent = "";
            }

            const submitButton = loginForm.querySelector('button[type="submit"]');
            if (submitButton instanceof HTMLButtonElement) {
                submitButton.disabled = true;
                submitButton.textContent = "Signing in...";
            }

            try {
                const response = await fetch("/api/login", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify(payload),
                });

                const data = await response.json();

                if (!response.ok || !data.ok) {
                    throw new Error(data.message || "Login failed.");
                }

                window.location.href = data.redirect || "/dashboard";
            } catch (error) {
                if (loginError) {
                    loginError.textContent = error instanceof Error ? error.message : "Login failed.";
                }
            } finally {
                if (submitButton instanceof HTMLButtonElement) {
                    submitButton.disabled = false;
                    submitButton.textContent = "Enter Control Plane";
                }
            }
        });
    }

    // ══════════════════════════════════════════════════════════════════════
    //  Insights — Overview Command Dashboard
    // ══════════════════════════════════════════════════════════════════════
    const insightsShell = document.querySelector("[data-insights-shell]");
    console.log("[Insights] shell found:", !!insightsShell);
    if (insightsShell) {

        // ── State ────────────────────────────────────────────────────────
        let ovConfiguredCount = 0;   // total from /api/insights/configured
        let ovConfigured      = [];  // full device list (shared with Sensors tab)
        let ovLiveDevices     = [];  // latest from /api/insights/live
        let svRefreshFn       = null; // set by Sensors tab block
        let evRefreshFn       = null; // set by Events tab block

        // ── DOM refs ─────────────────────────────────────────────────────
        const ovDeviceGrid = insightsShell.querySelector("[data-ov-device-grid]");
        const ovNoSensors  = insightsShell.querySelector("[data-ov-no-sensors]");

        // ── Helpers ───────────────────────────────────────────────────────
        const fmtAge = (s) => {
            if (s < 5)    return "just now";
            if (s < 60)   return `${Math.round(s)}s ago`;
            if (s < 3600) return `${Math.round(s / 60)}m ago`;
            return `${Math.round(s / 3600)}h ago`;
        };

        const fmtVal = (v) => {
            if (v === null || v === undefined) return "--";
            if (typeof v !== "number") return String(v).trim();
            if (Number.isInteger(v)) return String(v);
            // Smart decimal: show enough significant digits without trailing zeros
            const abs = Math.abs(v);
            if (abs >= 100)  return v.toFixed(1);
            if (abs >= 10)   return v.toFixed(2);
            if (abs >= 1)    return v.toFixed(3);
            return v.toFixed(4);
        };

        // Known display names for common metric keys
        const METRIC_LABELS = {
            pm1: "PM1", pm25: "PM2.5", pm4: "PM4", pm10: "PM10", total: "Total PM",
        };

        const displayLabel = (rawName) => {
            const clean = (rawName || "").trim();
            return METRIC_LABELS[clean.toLowerCase()] ||
                clean.replace(/[_]+/g, " ")
                     .split(" ")
                     .map(w => w.charAt(0).toUpperCase() + w.slice(1))
                     .join(" ");
        };

        const tpStr = (tp) => {
            if (!tp) return "";
            if (tp.type === "serial")     return `${tp.endpoint || ""}`;
            if (tp.type === "modbus_rtu") return `${tp.endpoint || ""}`;
            if (tp.type === "modbus_tcp") return `${tp.endpoint || ""}:${tp.port || 502} · ${tp.interface || "eth0"}`;
            return tp.endpoint || "";
        };

        // ── Trend from sample array ────────────────────────────────────────
        const computeTrend = (values) => {
            if (!values || values.length < 10) return "flat";
            const recent  = values.slice(-5);
            const earlier = values.slice(-20, -15);
            if (earlier.length < 3) return "flat";
            const avg = (arr) => arr.reduce((a, b) => a + b, 0) / arr.length;
            const recentAvg  = avg(recent);
            const earlierAvg = avg(earlier);
            const base = Math.abs(earlierAvg) || 1;
            const pct  = (recentAvg - earlierAvg) / base * 100;
            if (pct > 3)  return "up";
            if (pct < -3) return "down";
            return "flat";
        };

        // ── Sparkline SVG ────────────────────────────────────────────────
        const drawSparkline = (svgEl, values, quality) => {
            if (!svgEl) return;
            const W = svgEl.clientWidth || 100;
            const H = 32;
            const pad = 3;
            const uH  = H - pad * 2;
            const color = quality === "good"  ? "rgba(57,208,200,0.72)" :
                          quality === "stale" ? "rgba(240,166,75,0.6)"  :
                                               "rgba(220,80,80,0.55)";

            if (!values || values.length < 2) {
                svgEl.innerHTML = `<line x1="0" y1="${H/2}" x2="${W}" y2="${H/2}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="2,3"/>`;
                return;
            }

            const min = Math.min(...values);
            const max = Math.max(...values);
            const rng = max - min || 1;
            const step = (W - pad * 2) / (values.length - 1);
            const toX = (i) => pad + i * step;
            const toY = (v) => pad + uH - ((v - min) / rng) * uH;

            // Area fill
            const pathD = values.map((v, i) => `${i === 0 ? "M" : "L"} ${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(" ");
            const areaD = `${pathD} L ${toX(values.length-1).toFixed(1)},${H} L ${pad},${H} Z`;

            svgEl.setAttribute("viewBox", `0 0 ${W} ${H}`);
            svgEl.innerHTML = `
                <path d="${areaD}" fill="${color.replace('0.72','0.1').replace('0.6','0.08').replace('0.55','0.07')}" stroke="none"/>
                <path d="${pathD}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>`;
        };

        // ── Build card skeleton from configured device ─────────────────────
        const buildCard = (device) => {
            const key     = `${device.source}:${device.device_id}`;
            const type    = device.device_type || device.source || "sensor";
            const tp      = tpStr(device.transport);
            const metrics = device.expected_metrics || [];

            const metricRows = metrics.map((m) => {
                const label = displayLabel(m.name);
                const unit  = (m.unit || "").trim();
                return `
                    <div class="ov-metric-row" data-ov-metric="${m.name}">
                        <span class="ov-metric-label" title="${label}">${label}</span>
                        <div class="ov-metric-reading">
                            <span class="ov-metric-val" data-ov-val>--</span>
                            <span class="ov-metric-unit">${unit}</span>
                            <span class="ov-trend" data-ov-trend></span>
                        </div>
                        <svg class="ov-sparkline" data-ov-spark height="32" preserveAspectRatio="none">
                            <line x1="0" y1="16" x2="100" y2="16" stroke="rgba(255,255,255,0.08)" stroke-dasharray="2,3"/>
                        </svg>
                        <span class="ov-quality-dot" data-ov-quality></span>
                    </div>`;
            }).join("");

            return `
                <article class="ov-card" data-ov-card="${key}">
                    <header class="ov-card-head">
                        <div>
                            <p class="ov-card-name">${device.name || device.device_id}</p>
                            <div class="ov-card-chips">
                                <span class="ov-chip ov-chip-type">${type}</span>
                                ${tp ? `<span class="ov-chip ov-chip-transport">${tp}</span>` : ""}
                            </div>
                        </div>
                        <span class="ov-status-badge ov-status-awaiting" data-ov-status>
                            <span class="ov-status-pulse"></span>
                            <span class="ov-status-text">Awaiting</span>
                        </span>
                    </header>
                    <div class="ov-card-issues" data-ov-issues hidden>
                        <span class="ov-card-issues-dot"></span>
                        <span class="ov-card-issues-text" data-ov-issues-text></span>
                    </div>
                    <div class="ov-metric-list">
                        ${metricRows || `<p style="padding:1rem;color:var(--muted);font-size:.84rem">No registers configured.</p>`}
                    </div>
                    <footer class="ov-card-foot">
                        <div class="ov-health-row">
                            <span class="ov-health-pct" data-ov-health-pct>-- health</span>
                            <span class="ov-last-seen" data-ov-last-seen></span>
                        </div>
                        <div class="ov-health-bar-track">
                            <div class="ov-health-bar-fill" data-ov-health-bar></div>
                        </div>
                    </footer>
                </article>`;
        };

        // ── Apply live data to existing card skeletons ─────────────────────
        const applyLiveToCards = () => {
            if (!ovDeviceGrid) return;

            const liveMap = {};
            for (const d of ovLiveDevices) {
                liveMap[`${d.source}:${d.device_id}`] = d;
            }

            ovDeviceGrid.querySelectorAll("[data-ov-card]").forEach((card) => {
                const key       = card.getAttribute("data-ov-card");
                const live      = liveMap[key];
                const status    = card.querySelector("[data-ov-status]");
                const stText    = status?.querySelector(".ov-status-text");
                const issuesEl  = card.querySelector("[data-ov-issues]");
                const issuesTx  = card.querySelector("[data-ov-issues-text]");

                if (!live) {
                    // Device configured but not live in Redis
                    if (status) {
                        status.className = "ov-status-badge ov-status-offline";
                        if (stText) stText.textContent = "Offline";
                    }
                    card.classList.remove("is-live", "is-warning", "is-error");
                    card.classList.add("is-offline");
                    if (issuesEl) issuesEl.hidden = true;
                    return;
                }

                // ── Status badge ──────────────────────────────────────────
                const devStatus = live.status || "ok";
                const sc = devStatus === "ok"      ? "ov-status-live"    :
                           devStatus === "warning"  ? "ov-status-warning" :
                                                     "ov-status-error";
                const sl = devStatus === "ok" ? "Live" :
                           devStatus === "warning" ? "Warning" : "Error";
                if (status) {
                    status.className = `ov-status-badge ${sc}`;
                    if (stText) stText.textContent = sl;
                }
                card.classList.remove("is-offline");
                card.classList.toggle("is-live",    devStatus === "ok");
                card.classList.toggle("is-warning", devStatus === "warning");
                card.classList.toggle("is-error",   devStatus === "error");

                // ── Last seen ─────────────────────────────────────────────
                const lastSeenEl = card.querySelector("[data-ov-last-seen]");
                if (lastSeenEl && live.timestamp_ms) {
                    lastSeenEl.textContent = fmtAge((Date.now() - live.timestamp_ms) / 1000);
                }

                // ── Metric rows ───────────────────────────────────────────
                const metrics  = live.metrics  || {};
                const samples  = live._samples || {};
                let goodCount  = 0;
                let totalCount = 0;
                let staleCount = 0;
                let errorCount = 0;

                card.querySelectorAll("[data-ov-metric]").forEach((row) => {
                    const mkey    = row.getAttribute("data-ov-metric");
                    const m       = metrics[mkey];
                    const valEl   = row.querySelector("[data-ov-val]");
                    const sparkEl = row.querySelector("[data-ov-spark]");
                    const qualEl  = row.querySelector("[data-ov-quality]");
                    const trendEl = row.querySelector("[data-ov-trend]");

                    if (!m) {
                        // Device has an error and this metric has no data at all —
                        // count it as errored so health doesn't default to 100%
                        if (live.error || live.status === "error") {
                            totalCount++;
                            errorCount++;
                        }
                        row.classList.remove("is-stale", "is-error");
                        return;
                    }

                    totalCount++;
                    // If value is null/undefined, treat as error regardless of stored quality flag
                    const valueIsNull = m.value === null || m.value === undefined;
                    const q = valueIsNull ? "error" : (m.quality || "good");
                    if (q === "good")  goodCount++;
                    if (q === "stale") staleCount++;
                    if (q === "error") errorCount++;

                    // Row tint
                    row.classList.toggle("is-stale", q === "stale");
                    row.classList.toggle("is-error", q === "error");

                    // Value
                    if (valEl) {
                        valEl.textContent = fmtVal(m.value);
                        valEl.className = `ov-metric-val${q === "stale" ? " is-stale" : q === "error" ? " is-error" : ""}`;
                    }

                    // Sparkline
                    if (sparkEl) {
                        drawSparkline(sparkEl, samples[mkey] || [], q);
                    }

                    // Trend arrow
                    if (trendEl) {
                        const trend = computeTrend(samples[mkey] || []);
                        trendEl.textContent = trend === "up" ? "↑" : trend === "down" ? "↓" : "";
                        trendEl.className   = `ov-trend ov-trend-${trend}`;
                    }

                    // Quality dot
                    if (qualEl) {
                        qualEl.className = `ov-quality-dot${q === "good" ? " is-good" : q === "stale" ? " is-stale" : " is-error"}`;
                    }
                });

                // ── Per-card issue banner ────────────────────────────────
                if (issuesEl && issuesTx) {
                    let txt = "";
                    let isErr = false;
                    if (live.error) {
                        txt = live.error.message || `${live.error.type || "device error"}`;
                        isErr = true;
                    } else if (errorCount > 0) {
                        txt = `${errorCount} reading${errorCount > 1 ? "s" : ""} errored`;
                        isErr = true;
                    } else if (staleCount > 0) {
                        txt = `${staleCount} reading${staleCount > 1 ? "s" : ""} stale`;
                        isErr = false;
                    }
                    if (txt) {
                        issuesTx.textContent = txt;
                        issuesEl.classList.toggle("is-error", isErr);
                        issuesEl.hidden = false;
                    } else {
                        issuesEl.hidden = true;
                    }
                }

                // ── Health bar ────────────────────────────────────────────
                // If device has an error OR no metrics counted, health is 0 — not 100.
                const pct = (live.error || live.status === "error")
                    ? 0
                    : totalCount > 0 ? Math.round((goodCount / totalCount) * 100) : 0;
                const hPctEl   = card.querySelector("[data-ov-health-pct]");
                const hBarEl   = card.querySelector("[data-ov-health-bar]");
                if (hPctEl)  hPctEl.textContent  = `${pct}% health`;
                if (hBarEl) {
                    hBarEl.style.width = `${pct}%`;
                    hBarEl.className   = `ov-health-bar-fill${pct < 70 ? " is-crit" : pct < 90 ? " is-warn" : ""}`;
                }
            });
        };

        // ── KPI Strip ─────────────────────────────────────────────────────
        const updateKPIs = () => {
            const kpi    = (k) => insightsShell.querySelector(`[data-ov-kpi="${k}"]`);
            const kpiSub = (k) => insightsShell.querySelector(`[data-ov-kpi-sub="${k}"]`);

            const liveCount = ovLiveDevices.length;
            const devEl     = kpi("devices");
            if (devEl) devEl.textContent = String(liveCount);
            const devSub = kpiSub("devices");
            if (devSub) devSub.textContent = `of ${ovConfiguredCount} configured`;

            // ── Data Quality: good readings / total metric slots ──────────────
            // A metric counts as "good" only when:
            //   • the device itself is ok (not error/offline/warning)
            //   • the metric has an actual value (not null)
            //   • PES quality field is "good"
            // If a device is in error, ALL its metrics count as bad — even if
            // the quality field still says "good" from the last successful read.
            let totalMetrics = 0, goodMetrics = 0;
            for (const d of ovLiveDevices) {
                const deviceOk = d.status === "ok" && !d.error;
                const metrics  = Object.values(d.metrics || {});
                if (metrics.length === 0) {
                    // Device has no metric data at all — count as one bad slot
                    totalMetrics++;
                } else {
                    for (const m of metrics) {
                        totalMetrics++;
                        if (deviceOk && m.value !== null && m.value !== undefined && m.quality === "good") {
                            goodMetrics++;
                        }
                    }
                }
            }
            const qualPct = ovConfiguredCount > 0
                ? Math.round((goodMetrics / Math.max(totalMetrics, 1)) * 100)
                : 0;

            // ── System Health: devices fully operational / configured ──────────
            // Distinct from data quality — measures device-level reachability.
            const okDevices = ovLiveDevices.filter(
                (d) => d.status === "ok" && !d.error &&
                       !Object.values(d.metrics || {}).some(
                           (m) => m.quality !== "good" || m.value === null || m.value === undefined
                       )
            ).length;
            const healthPct = ovConfiguredCount > 0
                ? Math.round((okDevices / ovConfiguredCount) * 100)
                : 0;

            const qEl = kpi("quality");
            if (qEl) qEl.textContent = ovConfiguredCount > 0 ? `${qualPct}%` : "--%";
            const qBar = insightsShell.querySelector(`[data-ov-kpi-bar="quality"]`);
            if (qBar) {
                qBar.style.width  = `${qualPct}%`;
                qBar.className    = `ov-kpi-bar-fill${qualPct < 70 ? " is-hot" : qualPct < 90 ? " is-warm" : ""}`;
            }

            const hEl = kpi("health");
            if (hEl) hEl.textContent = ovConfiguredCount > 0 ? `${healthPct}%` : "--%";
            const hBar = insightsShell.querySelector(`[data-ov-kpi-bar="health"]`);
            if (hBar) {
                hBar.style.width = `${healthPct}%`;
                hBar.className   = `ov-kpi-bar-fill${healthPct < 70 ? " is-hot" : healthPct < 90 ? " is-warm" : ""}`;
            }

            // Anomalies count
            const anCount = ovLiveDevices.filter((d) => {
                if (d.status !== "ok" || d.error) return true;
                return Object.values(d.metrics || {}).some(m => m.quality !== "good");
            }).length;
            const anEl  = kpi("anomalies");
            if (anEl) anEl.textContent = String(anCount);
            const anSub = kpiSub("anomalies");
            if (anSub) anSub.textContent = anCount === 0 ? "All systems nominal" : `${anCount} device${anCount > 1 ? "s" : ""} affected`;
        };

        // ── Load live data → overlay on skeletons ──────────────────────────
        const loadLive = async () => {
            try {
                const r = await fetch("/api/insights/live");
                if (!r.ok) return;
                const d = await r.json();
                if (!d.ok) return;
                ovLiveDevices = d.devices || [];
                applyLiveToCards();
                updateKPIs();
            } catch (e) {
                console.warn("[Insights] loadLive failed:", e);
            }
        };

        // ── Tab switching ─────────────────────────────────────────────────
        insightsShell.querySelectorAll("[data-ov-tab]").forEach((btn) => {
            btn.addEventListener("click", () => {
                if (btn.disabled) return;
                insightsShell.querySelectorAll("[data-ov-tab]").forEach((b) => b.classList.remove("is-current"));
                insightsShell.querySelectorAll("[data-ov-panel]").forEach((p) => p.classList.add("ov-hidden"));
                btn.classList.add("is-current");
                const panel = insightsShell.querySelector(`[data-ov-panel="${btn.getAttribute("data-ov-tab")}"]`);
                panel?.classList.remove("ov-hidden");
                // Sensors tab: force chart render now that the panel is visible
                if (btn.getAttribute("data-ov-tab") === "sensors" && svRefreshFn) {
                    svRefreshFn(true);
                }
                // Events tab: force event + rules load on tab open
                if (btn.getAttribute("data-ov-tab") === "events" && evRefreshFn) {
                    evRefreshFn();
                }
            });
        });

        // ══════════════════════════════════════════════════════════════════════
        //  Sensors tab — per-device deep dive with chart
        // ══════════════════════════════════════════════════════════════════════
        const svPanel = insightsShell.querySelector('[data-ov-panel="sensors"]');
        if (svPanel) {
            // ── State (key selections persisted across page navigations) ─────────
            let svSelectedKey = localStorage.getItem("metacrust.sv.selectedKey") || "";
            let svWindow      = localStorage.getItem("metacrust.sv.window")      || "1h";
            let svChartData   = {};    // { metricName: { timestamps, avg, min, max, count } }
            let svLastFetchMs = 0;     // throttle chart re-fetches to 60 s
            let svLastTabKeys = "";    // detect configured set changes

            // ── DOM refs ───────────────────────────────────────────────────────
            const svDeviceTabs   = svPanel.querySelector("[data-sv-device-tabs]");
            const svDeviceHeader = svPanel.querySelector("[data-sv-device-header]");
            const svMetricList   = svPanel.querySelector("[data-sv-metric-list]");
            const svChart        = svPanel.querySelector("[data-sv-chart]");
            const svChartEmpty   = svPanel.querySelector("[data-sv-chart-empty]");
            const svLegend       = svPanel.querySelector("[data-sv-legend]");
            const svStats        = svPanel.querySelector("[data-sv-stats]");
            const svWindowBar    = svPanel.querySelector("[data-sv-window-bar]");
            const svExportBtn    = svPanel.querySelector("[data-sv-export-btn]");
            const svNoDevice     = svPanel.querySelector("[data-sv-no-device]");
            const svBody         = svPanel.querySelector("[data-sv-body]");

            // ── Chart colours (up to 4 overlaid metrics) ──────────────────────
            const SV_COLORS = ["#39d0c8", "#f0a64b", "#a78bfa", "#fb7185"];

            // ── Metric toggle persistence (localStorage) ───────────────────────
            const SV_LS_KEY = "metacrust.sv.toggles";
            const svToggles = (() => {
                try { return JSON.parse(localStorage.getItem(SV_LS_KEY) || "{}"); }
                catch { return {}; }
            })();
            const svSaveToggles = () => {
                try { localStorage.setItem(SV_LS_KEY, JSON.stringify(svToggles)); } catch {}
            };
            const svGetToggle = (dKey, mName) =>
                (svToggles[dKey] || {})[mName] !== false;   // default ON
            const svSetToggle = (dKey, mName, val) => {
                if (!svToggles[dKey]) svToggles[dKey] = {};
                svToggles[dKey][mName] = val;
                svSaveToggles();
            };

            // ── Device tabs ────────────────────────────────────────────────────
            const svBuildTabs = () => {
                if (!svDeviceTabs) return;
                const keys = ovConfigured.map((d) => `${d.source}:${d.device_id}`).join(",");
                if (keys === svLastTabKeys) return;
                svLastTabKeys = keys;

                if (ovConfigured.length === 0) {
                    svDeviceTabs.innerHTML = "";
                    svBody?.classList.add("ov-hidden");
                    svNoDevice?.classList.remove("ov-hidden");
                    return;
                }
                svBody?.classList.remove("ov-hidden");
                svNoDevice?.classList.add("ov-hidden");

                if (!svSelectedKey || !ovConfigured.some((d) => `${d.source}:${d.device_id}` === svSelectedKey)) {
                    svSelectedKey = `${ovConfigured[0].source}:${ovConfigured[0].device_id}`;
                }

                svDeviceTabs.innerHTML = ovConfigured.map((d) => {
                    const key  = `${d.source}:${d.device_id}`;
                    const curr = key === svSelectedKey;
                    return `<button class="sv-device-tab${curr ? " is-current" : ""}" data-sv-key="${key}">${d.name || d.device_id}</button>`;
                }).join("");

                svDeviceTabs.querySelectorAll("[data-sv-key]").forEach((btn) => {
                    btn.addEventListener("click", () => {
                        const newKey = btn.getAttribute("data-sv-key");
                        if (newKey === svSelectedKey) return;
                        svSelectedKey = newKey;
                        localStorage.setItem("metacrust.sv.selectedKey", svSelectedKey);
                        svDeviceTabs.querySelectorAll("[data-sv-key]").forEach((b) => b.classList.remove("is-current"));
                        btn.classList.add("is-current");
                        svChartData   = {};
                        svLastFetchMs = 0;
                        svStatsData       = {};
                        svStatsLastFetch  = 0;
                        svTrendsData      = [];
                        svTrendsLastFetch = 0;
                        svRenderMetricList();
                        svFetchAndRenderChart();
                    });
                });
            };

            // ── Metric list ────────────────────────────────────────────────────
            const svRenderMetricList = () => {
                if (!svMetricList || !svDeviceHeader) return;
                const device = ovConfigured.find((d) => `${d.source}:${d.device_id}` === svSelectedKey);
                if (!device) {
                    svDeviceHeader.innerHTML = "";
                    svMetricList.innerHTML   = "";
                    return;
                }
                const live     = ovLiveDevices.find((d) => `${d.source}:${d.device_id}` === svSelectedKey);
                const dStatus  = live?.status || "offline";
                const sc       = dStatus === "ok" ? "ov-status-live" : dStatus === "warning" ? "ov-status-warning" : dStatus === "error" ? "ov-status-error" : "ov-status-offline";
                const sl       = dStatus === "ok" ? "Live" : dStatus === "warning" ? "Warning" : dStatus === "error" ? "Error" : "Offline";
                const tp       = tpStr(device.transport);

                svDeviceHeader.innerHTML = `
                    <div>
                        <p class="sv-device-name">${device.name || device.device_id}</p>
                        ${tp ? `<p class="sv-device-transport">${tp}</p>` : ""}
                    </div>
                    <span class="ov-status-badge ${sc}">
                        <span class="ov-status-pulse"></span>
                        <span>${sl}</span>
                    </span>`;

                const metrics = device.expected_metrics || [];
                const deviceInError = !!(live?.error || live?.status === "error");
                svMetricList.innerHTML = metrics.map((m) => {
                    const lm   = (live?.metrics || {})[m.name] || {};
                    const val  = lm.value !== undefined ? fmtVal(lm.value) : "--";
                    const unit = (m.unit || lm.unit || "").trim();
                    // Null value or device in error → not good quality
                    const valueIsNull = lm.value === null || lm.value === undefined;
                    const q    = deviceInError ? "error"
                               : valueIsNull   ? "error"
                               : lm.quality    ? lm.quality
                               : live          ? "good" : "none";
                    const on   = svGetToggle(svSelectedKey, m.name);
                    const lbl  = displayLabel(m.name);
                    return `
                        <div class="sv-metric-row" data-sv-row="${m.name}">
                            <span class="sv-quality-dot${q === "good" ? " is-good" : q === "stale" ? " is-stale" : q === "error" ? " is-error" : ""}"></span>
                            <span class="sv-metric-name" title="${lbl}">${lbl}</span>
                            <div class="sv-metric-reading">
                                <span class="sv-metric-val${q === "stale" ? " is-stale" : q === "error" ? " is-error" : ""}" data-sv-val="${m.name}">${val}</span>
                                <span class="sv-metric-unit">${unit}</span>
                            </div>
                            <span class="sv-quality-pill is-${q}">${q === "none" ? "—" : q}</span>
                            <button class="sv-toggle-btn${on ? " is-on" : ""}" data-sv-toggle="${m.name}">${on ? "ON" : "OFF"}</button>
                        </div>`;
                }).join("");

                svMetricList.querySelectorAll("[data-sv-toggle]").forEach((btn) => {
                    btn.addEventListener("click", () => {
                        const mName = btn.getAttribute("data-sv-toggle");
                        const curr  = svGetToggle(svSelectedKey, mName);
                        svSetToggle(svSelectedKey, mName, !curr);
                        btn.classList.toggle("is-on", !curr);
                        btn.textContent = !curr ? "ON" : "OFF";
                        svChartData   = {};
                        svLastFetchMs = 0;
                        svFetchAndRenderChart();
                    });
                });
            };

            // ── Live value updates (called every 3 s, no DOM rebuild) ──────────
            const svUpdateLiveValues = () => {
                if (!svMetricList) return;
                const live = ovLiveDevices.find((d) => `${d.source}:${d.device_id}` === svSelectedKey);

                // Also update the status badge in the device header
                if (svDeviceHeader && live) {
                    const badge  = svDeviceHeader.querySelector(".ov-status-badge");
                    const bText  = badge?.querySelector("span:last-child");
                    const dStatus = live.status || "ok";
                    if (badge) {
                        const sc = dStatus === "ok" ? "ov-status-live" : dStatus === "warning" ? "ov-status-warning" : "ov-status-error";
                        badge.className = `ov-status-badge ${sc}`;
                        if (bText) bText.textContent = dStatus === "ok" ? "Live" : dStatus === "warning" ? "Warning" : "Error";
                    }
                }

                if (!live) return;
                const liveInError = !!(live.error || live.status === "error");
                svMetricList.querySelectorAll("[data-sv-row]").forEach((row) => {
                    const mName  = row.getAttribute("data-sv-row");
                    const m      = (live.metrics || {})[mName];
                    const valEl  = row.querySelector(`[data-sv-val="${mName}"]`);
                    const dotEl  = row.querySelector(".sv-quality-dot");
                    const pillEl = row.querySelector(".sv-quality-pill");
                    if (!m) {
                        // Metric missing entirely — device is in error
                        const q = liveInError ? "error" : "none";
                        if (valEl)  { valEl.textContent = "--"; valEl.className = `sv-metric-val${liveInError ? " is-error" : ""}`; }
                        if (dotEl)  dotEl.className = `sv-quality-dot${liveInError ? " is-error" : ""}`;
                        if (pillEl) { pillEl.className = `sv-quality-pill is-${q}`; pillEl.textContent = q; }
                        return;
                    }
                    // Null value = error quality regardless of what Redis says
                    const valueIsNull = m.value === null || m.value === undefined;
                    const q = liveInError ? "error" : valueIsNull ? "error" : (m.quality || "good");
                    if (valEl)  { valEl.textContent = fmtVal(m.value); valEl.className = `sv-metric-val${q === "stale" ? " is-stale" : q === "error" ? " is-error" : ""}`; }
                    if (dotEl)  dotEl.className  = `sv-quality-dot${q === "good" ? " is-good" : q === "stale" ? " is-stale" : " is-error"}`;
                    if (pillEl) { pillEl.className = `sv-quality-pill is-${q}`; pillEl.textContent = q; }
                });
            };

            // ── History fetch ──────────────────────────────────────────────────
            const svFetchAndRenderChart = async () => {
                if (!svSelectedKey) return;
                const device = ovConfigured.find((d) => `${d.source}:${d.device_id}` === svSelectedKey);
                if (!device) return;

                const activeMetrics = (device.expected_metrics || [])
                    .filter((m) => svGetToggle(svSelectedKey, m.name))
                    .slice(0, 4)
                    .map((m) => m.name);

                if (activeMetrics.length === 0) {
                    svChartData = {};
                    svRenderChart();
                    svRenderStats();
                    return;
                }

                const [src, ...didParts] = svSelectedKey.split(":");
                const did    = didParts.join(":");
                const params = new URLSearchParams({
                    source:    src,
                    device_id: did,
                    metrics:   activeMetrics.join(","),
                    window:    svWindow,
                });

                try {
                    const r = await fetch(`/api/insights/history?${params}`);
                    if (!r.ok) return;
                    const d = await r.json();
                    if (!d.ok) return;
                    svChartData   = d.metrics || {};
                    svLastFetchMs = Date.now();
                } catch (e) {
                    console.warn("[Sensors] history fetch failed:", e);
                    return;
                }
                svRenderChart();
                svRenderStats();
            };

            // ═══════════════════════════════════════════════════════════════════
            //  Core chart drawing — shared by small chart + expanded modal
            // ═══════════════════════════════════════════════════════════════════
            const svDrawIntoSvg = (svgEl, data, visMetrics, zStart = 0, zEnd = 1) => {
                const active = visMetrics.filter((k) => (data[k]?.timestamps?.length || 0) > 1);
                if (!active.length) return null;

                // Stable color map: color is determined by position in the FULL data keyset,
                // so colors never shift when individual metrics are toggled off.
                const allDataKeys = Object.keys(data);
                const colorMap = {};
                allDataKeys.forEach((k, i) => { colorMap[k] = SV_COLORS[i % SV_COLORS.length]; });

                const W = svgEl.clientWidth  || 600;
                const H = svgEl.clientHeight || 260;
                const padL = 48, padR = 14, padT = 14, padB = 34;
                const cW = W - padL - padR;
                const cH = H - padT - padB;

                // Full time range, then apply zoom window
                const allTs     = active.flatMap((k) => data[k].timestamps);
                const gMin = Math.min(...allTs), gMax = Math.max(...allTs);
                const gRng      = gMax - gMin || 1;
                const visMin    = gMin + zStart * gRng;
                const visMax    = gMin + zEnd   * gRng;
                const visRng    = visMax - visMin || 1;
                const inView    = (ts) => ts >= visMin - visRng * 0.01 && ts <= visMax + visRng * 0.01;
                const toX       = (ts) => padL + ((ts - visMin) / visRng) * cW;

                // Per-metric Y scale (each metric normalised to its visible range)
                const mScale = {};
                for (const k of active) {
                    const vals = data[k].timestamps.map((ts, i) => inView(ts) ? data[k].avg[i] : null).filter((v) => v !== null);
                    const mn = vals.length ? Math.min(...vals) : 0;
                    const mx = vals.length ? Math.max(...vals) : 1;
                    mScale[k] = { min: mn, rng: mx - mn || 1, max: mx };
                }
                const toY = (k, v) => padT + cH - ((v - mScale[k].min) / mScale[k].rng) * cH;

                const parts = [];

                // Grid lines
                for (let i = 0; i <= 4; i++) {
                    const y = padT + (i / 4) * cH;
                    parts.push(`<line x1="${padL}" y1="${y.toFixed(1)}" x2="${(W - padR).toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,0.04)" stroke-width="1"/>`);
                }

                // Y axis labels (for first metric only — shows normalised %)
                for (let i = 0; i <= 4; i++) {
                    const y   = padT + (i / 4) * cH;
                    const pct = 100 - i * 25;
                    parts.push(`<text x="${padL - 4}" y="${(y + 3.5).toFixed(1)}" fill="rgba(157,179,187,0.4)" font-size="9" text-anchor="end" font-family="monospace">${pct}%</text>`);
                }

                // X axis time labels
                const lblCount = Math.min(6, Math.max(3, Math.floor(W / 110)));
                for (let i = 0; i <= lblCount; i++) {
                    const ts  = visMin + (i / lblCount) * visRng;
                    const x   = padL + (i / lblCount) * cW;
                    const dt  = new Date(ts);
                    const lbl = dt.getHours().toString().padStart(2, "0") + ":" + dt.getMinutes().toString().padStart(2, "0");
                    parts.push(`<text x="${x.toFixed(1)}" y="${H - 9}" fill="rgba(157,179,187,0.5)" font-size="10" text-anchor="middle" font-family="monospace">${lbl}</text>`);
                }

                // Crosshair (hidden by default)
                parts.push(`<line class="sv-xhair" x1="-9" y1="${padT}" x2="-9" y2="${padT + cH}" stroke="rgba(255,255,255,0.22)" stroke-width="1" stroke-dasharray="3,2" pointer-events="none"/>`);

                // Per-metric area + line
                active.forEach((k) => {
                    const color  = colorMap[k];
                    const series = data[k];
                    const pts    = series.timestamps
                        .map((ts, i) => (series.avg[i] !== null && inView(ts)) ? { x: toX(ts), y: toY(k, series.avg[i]), ts, v: series.avg[i] } : null)
                        .filter(Boolean);
                    if (pts.length < 2) return;
                    const lineD = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
                    const areaD = `${lineD} L${pts[pts.length-1].x.toFixed(1)},${(padT+cH).toFixed(1)} L${pts[0].x.toFixed(1)},${(padT+cH).toFixed(1)}Z`;
                    parts.push(`<path d="${areaD}" fill="${color}" fill-opacity="0.07" stroke="none"/>`);
                    parts.push(`<path d="${lineD}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/>`);
                });

                svgEl.setAttribute("viewBox", `0 0 ${W} ${H}`);
                svgEl.innerHTML = parts.join("");

                // Return state object for hit-testing (tooltip)
                return {
                    active, mScale, colorMap, visMin, visMax, visRng, padL, cW, gMin, gMax, gRng,
                    hitTest(xFrac) {
                        const ts = visMin + xFrac * visRng;
                        const result = {};
                        for (const k of active) {
                            const s = data[k];
                            let best = null, bestD = Infinity;
                            for (let i = 0; i < s.timestamps.length; i++) {
                                if (!inView(s.timestamps[i])) continue;
                                const d = Math.abs(s.timestamps[i] - ts);
                                if (d < bestD) { bestD = d; best = { ts: s.timestamps[i], v: s.avg[i], min: s.min[i], max: s.max[i] }; }
                            }
                            if (best) result[k] = best;
                        }
                        return result;
                    },
                };
            };

            // ── Hover tooltip handler ─────────────────────────────────────────
            const svAttachHover = (wrapEl, svgEl, ttEl, getState) => {
                if (!wrapEl || !svgEl || !ttEl) return;
                const onMove = (e) => {
                    const st = getState();
                    if (!st) { ttEl.style.display = "none"; return; }
                    const svgRect = svgEl.getBoundingClientRect();
                    const rawX    = e.clientX - svgRect.left;
                    const xFrac   = Math.max(0, Math.min(1, (rawX - 48) / (svgRect.width - 62)));
                    const hit     = st.hitTest(xFrac);
                    if (!Object.keys(hit).length) { ttEl.style.display = "none"; return; }

                    const xhair = svgEl.querySelector(".sv-xhair");
                    if (xhair) { const cx = rawX.toFixed(1); xhair.setAttribute("x1", cx); xhair.setAttribute("x2", cx); }

                    const firstTs = Object.values(hit)[0]?.ts;
                    const dt = firstTs ? new Date(firstTs) : null;
                    const hdr = dt
                        ? dt.toLocaleDateString([], { month: "short", day: "numeric" }) + "  " + dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
                        : "";
                    const rows = st.active.map((k) => {
                        const h = hit[k]; if (!h) return "";
                        const color = st.colorMap?.[k] || SV_COLORS[0];
                        const pct = Math.round(((h.v - st.mScale[k].min) / st.mScale[k].rng) * 100);
                        return `<div class="sv-tt-row"><span class="sv-tt-dot" style="background:${color}"></span><span class="sv-tt-label">${displayLabel(k)}</span><span class="sv-tt-val">${fmtVal(h.v)}</span><span class="sv-tt-pct">${pct}%</span></div>`;
                    }).join("");
                    ttEl.innerHTML = `<div class="sv-tt-hdr">${hdr}</div>${rows}`;
                    ttEl.style.display = "block";

                    const wrapRect = wrapEl.getBoundingClientRect();
                    const lx = e.clientX - wrapRect.left + 14;
                    const flip = lx + 175 > wrapRect.width;
                    ttEl.style.left = `${flip ? lx - 190 : lx}px`;
                    ttEl.style.top  = `${Math.max(0, e.clientY - wrapRect.top - 20)}px`;
                };
                wrapEl.addEventListener("mousemove", onMove);
                wrapEl.addEventListener("mouseleave", () => {
                    ttEl.style.display = "none";
                    const xhair = svgEl.querySelector(".sv-xhair");
                    if (xhair) { xhair.setAttribute("x1", "-9"); xhair.setAttribute("x2", "-9"); }
                });
            };

            // ── Small chart render ─────────────────────────────────────────────
            // Inject tooltip overlay + expand button once
            const svChartWrap = svPanel.querySelector(".sv-chart-wrap");
            let svSmallTt = null, svExpandBtn = null;
            if (svChartWrap) {
                svSmallTt = document.createElement("div");
                svSmallTt.className = "sv-tooltip";
                svSmallTt.style.display = "none";
                svChartWrap.appendChild(svSmallTt);

                svExpandBtn = document.createElement("button");
                svExpandBtn.className = "sv-expand-btn";
                svExpandBtn.title = "Expand / fullscreen";
                svExpandBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1 5V1h4M9 1h4v4M13 9v4H9M5 13H1V9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;
                svChartWrap.appendChild(svExpandBtn);
            }

            let svSmallChartState = null;
            svAttachHover(svChartWrap, svChart, svSmallTt, () => svSmallChartState);

            const svRenderChart = () => {
                if (!svChart) return;
                const active = Object.keys(svChartData).filter((k) => (svChartData[k]?.timestamps?.length || 0) > 1);
                if (active.length === 0) {
                    svChart.innerHTML = "";
                    svSmallChartState = null;
                    svChartEmpty?.classList.remove("ov-hidden");
                    if (svLegend) svLegend.innerHTML = "";
                    return;
                }
                svChartEmpty?.classList.add("ov-hidden");
                svSmallChartState = svDrawIntoSvg(svChart, svChartData, active, 0, 1);
                if (svLegend && svSmallChartState) {
                    const cm = svSmallChartState.colorMap;
                    svLegend.innerHTML = active.map((k) =>
                        `<span class="sv-legend-item"><span class="sv-legend-dot" style="background:${cm[k]}"></span>${displayLabel(k)}</span>`
                    ).join("");
                }
            };

            // ── Expanded modal ─────────────────────────────────────────────────
            let svModal        = null;
            let svModalVisible = new Set();
            let svZoomStart    = 0;
            let svZoomEnd      = 1;
            let svModalState   = null;

            const svBuildModal = () => {
                if (svModal) return;
                svModal = document.createElement("div");
                svModal.className = "sv-chart-modal";
                svModal.innerHTML = `
                    <div class="sv-modal-inner">
                        <header class="sv-modal-head">
                            <span class="sv-modal-device-name" data-sv-modal-dev></span>
                            <span class="sv-modal-window-lbl" data-sv-modal-win-lbl></span>
                            <div class="sv-modal-line-btns" data-sv-modal-line-btns></div>
                            <button class="sv-modal-close-btn" data-sv-modal-close>✕</button>
                        </header>
                        <div class="sv-modal-chart-area" data-sv-modal-area>
                            <svg class="sv-modal-svg" data-sv-modal-svg preserveAspectRatio="none"></svg>
                            <div class="sv-modal-tt" data-sv-modal-tt></div>
                        </div>
                        <footer class="sv-modal-foot">
                            <div class="sv-zoom-ctrls">
                                <button class="sv-zoom-btn" data-sv-zi>＋</button>
                                <button class="sv-zoom-btn" data-sv-zo>－</button>
                                <button class="sv-zoom-reset-btn" data-sv-zr>Reset zoom</button>
                            </div>
                            <div class="sv-minimap" data-sv-minimap>
                                <div class="sv-minimap-full" data-sv-mini-full></div>
                                <div class="sv-minimap-win"  data-sv-mini-win></div>
                            </div>
                        </footer>
                    </div>`;
                document.body.appendChild(svModal);

                const modalSvg  = svModal.querySelector("[data-sv-modal-svg]");
                const modalArea = svModal.querySelector("[data-sv-modal-area]");
                const modalTt   = svModal.querySelector("[data-sv-modal-tt]");
                const lineBtns  = svModal.querySelector("[data-sv-modal-line-btns]");
                const miniWin   = svModal.querySelector("[data-sv-mini-win]");
                const winLbl    = svModal.querySelector("[data-sv-modal-win-lbl]");

                const redraw = () => {
                    const vis = [...svModalVisible];
                    svModalState = svDrawIntoSvg(modalSvg, svChartData, vis, svZoomStart, svZoomEnd);
                    if (miniWin) {
                        miniWin.style.left  = `${svZoomStart * 100}%`;
                        miniWin.style.width = `${(svZoomEnd - svZoomStart) * 100}%`;
                    }
                    if (winLbl && svModalState) {
                        const fmtTs = (ms) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
                        const vMin  = svModalState.gMin + svZoomStart * svModalState.gRng;
                        const vMax  = svModalState.gMin + svZoomEnd   * svModalState.gRng;
                        winLbl.textContent = `${fmtTs(vMin)} – ${fmtTs(vMax)}`;
                    }
                };

                const buildLineBtns = () => {
                    if (!lineBtns) return;
                    const active = Object.keys(svChartData).filter((k) => (svChartData[k]?.timestamps?.length || 0) > 1);
                    svModalVisible = new Set(active);
                    // Stable color map so buttons always match the chart lines
                    const cm = {};
                    Object.keys(svChartData).forEach((k, i) => { cm[k] = SV_COLORS[i % SV_COLORS.length]; });
                    lineBtns.innerHTML = active.map((k) => {
                        const c = cm[k];
                        return `<button class="sv-modal-line-btn is-on" data-mline="${k}"><span class="sv-modal-line-dot" style="background:${c}"></span>${displayLabel(k)}</button>`;
                    }).join("");
                    lineBtns.querySelectorAll("[data-mline]").forEach((btn) => {
                        btn.addEventListener("click", () => {
                            const k = btn.getAttribute("data-mline");
                            if (svModalVisible.has(k)) {
                                if (svModalVisible.size > 1) { svModalVisible.delete(k); btn.classList.remove("is-on"); }
                            } else { svModalVisible.add(k); btn.classList.add("is-on"); }
                            redraw();
                        });
                    });
                };
                svModal._buildLineBtns = buildLineBtns;
                svModal._redraw        = redraw;

                svAttachHover(modalArea, modalSvg, modalTt, () => svModalState);

                // Mouse wheel zoom
                modalArea.addEventListener("wheel", (e) => {
                    e.preventDefault();
                    const rng = svZoomEnd - svZoomStart;
                    const factor = e.deltaY > 0 ? 1.3 : 0.77;
                    const newRng = Math.max(0.05, Math.min(1, rng * factor));
                    const r      = modalArea.getBoundingClientRect();
                    const frac   = (e.clientX - r.left) / r.width;
                    const center = svZoomStart + frac * rng;
                    svZoomStart = Math.max(0, center - newRng * frac);
                    svZoomEnd   = Math.min(1, svZoomStart + newRng);
                    if (svZoomEnd > 1) { svZoomStart = Math.max(0, 1 - newRng); svZoomEnd = 1; }
                    redraw();
                }, { passive: false });

                // Drag to pan
                let dragX = null, dZS = 0, dZE = 1;
                modalArea.addEventListener("mousedown", (e) => {
                    if (e.button !== 0) return;
                    dragX = e.clientX; dZS = svZoomStart; dZE = svZoomEnd;
                    modalArea.style.cursor = "grabbing";
                });
                document.addEventListener("mousemove", (e) => {
                    if (dragX === null) return;
                    const r   = modalArea.getBoundingClientRect();
                    const dx  = (dragX - e.clientX) / r.width;
                    const rng = dZE - dZS;
                    let ns = dZS + dx * rng * 3, ne = dZE + dx * rng * 3;
                    if (ns < 0) { ne += -ns; ns = 0; }
                    if (ne > 1) { ns -= ne - 1; ne = 1; }
                    svZoomStart = Math.max(0, ns); svZoomEnd = Math.min(1, ne);
                    redraw();
                });
                document.addEventListener("mouseup", () => { dragX = null; if (modalArea) modalArea.style.cursor = ""; });

                // Minimap click
                const miniFull = svModal.querySelector("[data-sv-mini-full]");
                if (miniFull) {
                    miniFull.parentElement.addEventListener("click", (e) => {
                        const r    = miniFull.parentElement.getBoundingClientRect();
                        const frac = (e.clientX - r.left) / r.width;
                        const rng  = svZoomEnd - svZoomStart;
                        svZoomStart = Math.max(0, frac - rng / 2);
                        svZoomEnd   = Math.min(1, svZoomStart + rng);
                        redraw();
                    });
                }

                // Zoom buttons
                svModal.querySelector("[data-sv-zi]")?.addEventListener("click", () => { const c=(svZoomStart+svZoomEnd)/2, r=(svZoomEnd-svZoomStart)*0.65; svZoomStart=Math.max(0,c-r/2); svZoomEnd=Math.min(1,c+r/2); redraw(); });
                svModal.querySelector("[data-sv-zo]")?.addEventListener("click", () => { const c=(svZoomStart+svZoomEnd)/2, r=Math.min(1,(svZoomEnd-svZoomStart)*1.5); svZoomStart=Math.max(0,c-r/2); svZoomEnd=Math.min(1,c+r/2); redraw(); });
                svModal.querySelector("[data-sv-zr]")?.addEventListener("click", () => { svZoomStart=0; svZoomEnd=1; redraw(); });

                // Close
                svModal.querySelector("[data-sv-modal-close]")?.addEventListener("click", svCloseModal);
                svModal.addEventListener("click", (e) => { if (e.target === svModal) svCloseModal(); });
                document.addEventListener("keydown", (e) => { if (e.key === "Escape" && svModal?.classList.contains("is-open")) svCloseModal(); });
            };

            const svOpenModal = () => {
                svBuildModal();
                const device = ovConfigured.find((d) => `${d.source}:${d.device_id}` === svSelectedKey);
                const devEl  = svModal.querySelector("[data-sv-modal-dev]");
                if (devEl) devEl.textContent = `${device?.name || svSelectedKey}  ·  ${svWindow}`;
                svZoomStart = 0; svZoomEnd = 1;
                svModal._buildLineBtns?.();
                svModal._redraw?.();
                svModal.classList.add("is-open");
                document.body.style.overflow = "hidden";
            };
            const svCloseModal = () => {
                svModal?.classList.remove("is-open");
                document.body.style.overflow = "";
            };

            if (svExpandBtn) {
                svExpandBtn.addEventListener("click", () => {
                    if (Object.keys(svChartData).length > 0) svOpenModal();
                });
            }

            // ── Stats strip ────────────────────────────────────────────────────
            const svRenderStats = () => {
                if (!svStats) return;
                const active = Object.keys(svChartData).filter((k) => (svChartData[k]?.timestamps?.length || 0) > 0);
                if (active.length === 0) { svStats.innerHTML = ""; return; }

                // Stable colors: same map used by svDrawIntoSvg
                const cm = {};
                Object.keys(svChartData).forEach((k, i) => { cm[k] = SV_COLORS[i % SV_COLORS.length]; });

                svStats.innerHTML = active.map((k) => {
                    const color  = cm[k];
                    const series = svChartData[k];
                    const avgs   = series.avg.filter((v) => v !== null);
                    const mins   = series.min.filter((v) => v !== null);
                    const maxs   = series.max.filter((v) => v !== null);
                    const total  = series.count.reduce((a, b) => a + (b || 0), 0);
                    const avg    = avgs.length ? fmtVal(avgs.reduce((a, b) => a + b, 0) / avgs.length) : "--";
                    const min    = mins.length ? fmtVal(Math.min(...mins)) : "--";
                    const max    = maxs.length ? fmtVal(Math.max(...maxs)) : "--";
                    return `
                        <div class="sv-stat-card">
                            <p class="sv-stat-name">
                                <span class="sv-stat-color" style="background:${color}"></span>
                                ${displayLabel(k)}
                            </p>
                            <div class="sv-stat-grid">
                                <div class="sv-stat-item"><span class="sv-stat-label">Avg</span><span class="sv-stat-value">${avg}</span></div>
                                <div class="sv-stat-item"><span class="sv-stat-label">Min</span><span class="sv-stat-value">${min}</span></div>
                                <div class="sv-stat-item"><span class="sv-stat-label">Max</span><span class="sv-stat-value">${max}</span></div>
                                <div class="sv-stat-item"><span class="sv-stat-label">Samples</span><span class="sv-stat-value">${total.toLocaleString()}</span></div>
                            </div>
                        </div>`;
                }).join("");
            };

            // ── Window bar ─────────────────────────────────────────────────────
            if (svWindowBar) {
                svWindowBar.querySelectorAll("[data-sv-win]").forEach((btn) => {
                    if (btn.getAttribute("data-sv-win") === svWindow) btn.classList.add("is-current");
                    btn.addEventListener("click", () => {
                        svWindow = btn.getAttribute("data-sv-win");
                        localStorage.setItem("metacrust.sv.window", svWindow);
                        svWindowBar.querySelectorAll("[data-sv-win]").forEach((b) => b.classList.remove("is-current"));
                        btn.classList.add("is-current");
                        svChartData   = {};
                        svLastFetchMs = 0;
                        svFetchAndRenderChart();
                    });
                });
            }

            // ── Export CSV ─────────────────────────────────────────────────────
            if (svExportBtn) {
                svExportBtn.addEventListener("click", () => {
                    if (!svSelectedKey) return;

                    const [src, ...didParts] = svSelectedKey.split(":");
                    const did    = didParts.join(":");
                    const device = ovConfigured.find((d) => d.source === src && d.device_id === did);

                    // Export the ON-toggled metrics (or all if none toggled)
                    const toggledMetrics = (device?.expected_metrics || [])
                        .filter((m) => svGetToggle(svSelectedKey, m.name))
                        .map((m) => m.name);

                    const params = new URLSearchParams({
                        source:    src,
                        device_id: did,
                        metrics:   toggledMetrics.length ? toggledMetrics.join(",") : "all",
                        window:    svWindow,
                        name:      device?.name || did,
                    });

                    // Trigger file download — browser handles the rest
                    const a = document.createElement("a");
                    a.href = `/api/insights/export/csv?${params}`;
                    a.download = "";
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                });
            }

            // ══════════════════════════════════════════════════════════════════════
            //  Analytics panel — Rolling Stats (Tier 2) + Trends (Tier 3)
            // ══════════════════════════════════════════════════════════════════════
            const svAnalyticsPanel = svPanel.querySelector(".sv-analytics-panel");
            const svStatsTable     = svPanel.querySelector("[data-sv-stats-table]");
            const svStatsEmpty     = svPanel.querySelector("[data-sv-stats-empty]");
            const svTrendsList     = svPanel.querySelector("[data-sv-trends-list]");
            const svTrendsEmpty    = svPanel.querySelector("[data-sv-trends-empty]");

            // ── Analytics panel tab switching ──────────────────────────────────
            if (svAnalyticsPanel) {
                svAnalyticsPanel.querySelectorAll("[data-sv-atab]").forEach((btn) => {
                    btn.addEventListener("click", () => {
                        const tab = btn.getAttribute("data-sv-atab");
                        svAnalyticsPanel.querySelectorAll("[data-sv-atab]").forEach((b) => b.classList.remove("is-current"));
                        svAnalyticsPanel.querySelectorAll("[data-sv-abody]").forEach((p) => p.classList.add("ov-hidden"));
                        btn.classList.add("is-current");
                        svAnalyticsPanel.querySelector(`[data-sv-abody="${tab}"]`)?.classList.remove("ov-hidden");
                    });
                });
            }

            // ── Rolling stats ──────────────────────────────────────────────────
            let svStatsWindow    = localStorage.getItem("metacrust.sv.statsWindow") || "5min";
            let svStatsData      = {};     // { window → { metric → stats } }
            let svStatsLastFetch = 0;

            const svFmtStat = (v) => v !== null && v !== undefined ? fmtVal(v) : "--";

            const svRenderStatsTable = () => {
                if (!svStatsTable) return;
                const windowData = svStatsData[svStatsWindow] || {};
                const metrics    = Object.keys(windowData);
                if (metrics.length === 0) {
                    svStatsTable.innerHTML = "";
                    svStatsEmpty?.classList.remove("ov-hidden");
                    return;
                }
                svStatsEmpty?.classList.add("ov-hidden");

                // Show freshness note using computed_at from first metric
                const firstComputedAt = windowData[metrics[0]]?.computed_at;
                const freshnessNote   = firstComputedAt
                    ? ` · updated ${svTrendAge(firstComputedAt)}`
                    : "";

                svStatsTable.innerHTML = `
                    <p class="sv-stats-freshness">Stats for window: <strong>${svStatsWindow}</strong>${freshnessNote} · Health = good readings / total</p>
                    <table class="sv-stats-table">
                        <thead>
                            <tr>
                                <th>Metric</th>
                                <th>Avg</th>
                                <th>Min</th>
                                <th>Max</th>
                                <th>±Std Dev</th>
                                <th>Samples</th>
                                <th>Health</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${metrics.map((m) => {
                                const s  = windowData[m];
                                const hp = s.health_pct;
                                const hc = hp === null ? "" : hp >= 95 ? "is-good" : hp >= 80 ? "is-warn" : "is-crit";
                                const hv = hp !== null ? `${hp}%` : "--";
                                return `<tr>
                                    <td>${displayLabel(m)}</td>
                                    <td>${svFmtStat(s.avg)}</td>
                                    <td>${svFmtStat(s.min)}</td>
                                    <td>${svFmtStat(s.max)}</td>
                                    <td>${s.stddev !== null ? `±${svFmtStat(s.stddev)}` : "--"}</td>
                                    <td>${(s.sample_count || 0).toLocaleString()}</td>
                                    <td class="sv-stats-health-cell ${hc}">${hv}</td>
                                </tr>`;
                            }).join("")}
                        </tbody>
                    </table>`;
            };

            const svFetchStats = async () => {
                if (!svSelectedKey) return;
                const [src, ...rest] = svSelectedKey.split(":");
                const did = rest.join(":");
                try {
                    const r = await fetch(`/api/insights/stats?source=${encodeURIComponent(src)}&device_id=${encodeURIComponent(did)}`);
                    if (!r.ok) return;
                    const d = await r.json();
                    if (d.ok) { svStatsData = d.stats || {}; svStatsLastFetch = Date.now(); }
                } catch (e) { console.warn("[Sensors] stats fetch failed:", e); }
                svRenderStatsTable();
            };

            // Stats window bar
            if (svPanel) {
                svPanel.querySelectorAll("[data-sv-swin]").forEach((btn) => {
                    if (btn.getAttribute("data-sv-swin") === svStatsWindow) btn.classList.add("is-current");
                    btn.addEventListener("click", () => {
                        svStatsWindow = btn.getAttribute("data-sv-swin");
                        localStorage.setItem("metacrust.sv.statsWindow", svStatsWindow);
                        svPanel.querySelectorAll("[data-sv-swin]").forEach((b) => b.classList.remove("is-current"));
                        btn.classList.add("is-current");
                        svRenderStatsTable();
                    });
                });
            }

            // ── Trends ─────────────────────────────────────────────────────────
            const SV_SENS_PCT = { low: 10, medium: 3, high: 1 };
            let svSensitivity     = localStorage.getItem("metacrust.sv.sensitivity") || "medium";
            let svTrendsData      = [];
            let svTrendsLastFetch = 0;

            // Set saved sensitivity on load
            if (svPanel) {
                svPanel.querySelectorAll("[data-sv-sens]").forEach((btn) => {
                    if (btn.getAttribute("data-sv-sens") === svSensitivity) btn.classList.add("is-current");
                    else btn.classList.remove("is-current");
                    btn.addEventListener("click", () => {
                        svSensitivity = btn.getAttribute("data-sv-sens");
                        localStorage.setItem("metacrust.sv.sensitivity", svSensitivity);
                        svPanel.querySelectorAll("[data-sv-sens]").forEach((b) => b.classList.remove("is-current"));
                        btn.classList.add("is-current");
                        svRenderTrends();
                    });
                });
            }

            const svClassifySlope = (slope, currentValue) => {
                if (!currentValue || currentValue === 0) return slope > 0.001 ? "rising" : slope < -0.001 ? "falling" : "stable";
                const pctPerMin = Math.abs(slope / currentValue) * 100;
                const threshold = SV_SENS_PCT[svSensitivity] ?? 3;
                if (pctPerMin < threshold) return "stable";
                return slope > 0 ? "rising" : "falling";
            };

            const svTrendAge = (computedAtMs) => {
                if (!computedAtMs) return "";
                const ageSec = Math.round((Date.now() - computedAtMs) / 1000);
                if (ageSec < 60)  return `${ageSec}s ago`;
                if (ageSec < 3600) return `${Math.round(ageSec / 60)}m ago`;
                return `${Math.round(ageSec / 3600)}h ago`;
            };

            const svRenderTrends = () => {
                if (!svTrendsList) return;
                if (svTrendsData.length === 0) {
                    svTrendsList.innerHTML = "";
                    if (svTrendsEmpty) {
                        svTrendsEmpty.innerHTML = `
                            <p style="margin:0 0 0.35rem;font-weight:600;color:var(--muted)">No trend data yet</p>
                            <p style="margin:0;font-size:0.8rem;color:rgba(157,179,187,0.5)">
                                Trend analysis needs ~5 minutes of sensor readings.<br>
                                Check back shortly — data is collected automatically.
                            </p>`;
                        svTrendsEmpty.classList.remove("ov-hidden");
                    }
                    return;
                }
                svTrendsEmpty?.classList.add("ov-hidden");

                // Get live values for client-side sensitivity re-classification
                const liveDevice = ovLiveDevices.find((d) => `${d.source}:${d.device_id}` === svSelectedKey);
                const liveVals   = {};
                for (const [k, m] of Object.entries(liveDevice?.metrics || {})) {
                    if (m.value !== null && m.value !== undefined) liveVals[k] = m.value;
                }

                const DIRS  = { rising: "↑", falling: "↓", stable: "→" };
                const TONES = { rising: "is-rising", falling: "is-falling", stable: "is-stable" };

                svTrendsList.innerHTML = svTrendsData.map((t) => {
                    const slope    = t.slope ?? 0;
                    const currVal  = liveVals[t.metric_name];
                    const dir      = svClassifySlope(slope, currVal ?? 0);
                    const arrow    = DIRS[dir]  || "→";
                    const tone     = TONES[dir] || "is-stable";
                    const slopeAbs = Math.abs(slope);

                    // Slope description: direction word + rate
                    let slopeDesc;
                    if (slopeAbs < 0.0001) {
                        slopeDesc = "stable";
                    } else {
                        const rateStr = slopeAbs < 0.01
                            ? `${fmtVal(slope)}/min`
                            : `${slope >= 0 ? "+" : ""}${fmtVal(slope)}/min`;
                        slopeDesc = dir === "stable" ? `~${rateStr}` : rateStr;
                    }

                    // Current live value chip
                    const liveChip = currVal !== undefined
                        ? `<span class="sv-trend-live">${fmtVal(currVal)}</span>`
                        : "";

                    // Sample count + age
                    const samples  = t.n_samples ? `${t.n_samples} pts` : "";
                    const age      = svTrendAge(t.computed_at);
                    const metaStr  = [samples, age].filter(Boolean).join(" · ");

                    // Time-to-threshold
                    let tttHtml = "";
                    const ttt   = t.ttt_minutes;
                    const rule  = t.ttt_rule;
                    if (ttt !== null && ttt !== undefined && dir !== "stable") {
                        const sev  = (rule?.severity || "warning").toLowerCase();
                        const tCls = sev === "critical" ? "is-crit" : "is-warn";
                        const mins = ttt < 1 ? "<1" : ttt < 60 ? `${Math.round(ttt)}` : `${(ttt / 60).toFixed(1)}h`;
                        const unit = ttt >= 60 ? "" : " min";
                        tttHtml = `<span class="sv-trend-ttt ${tCls}" title="${sev.toUpperCase()} threshold: ${rule?.threshold}">⚡ ~${mins}${unit} to alert</span>`;
                    }

                    return `
                        <div class="sv-trend-row ${tone}">
                            <div class="sv-trend-top">
                                <span class="sv-trend-direction ${tone}">${arrow}</span>
                                <span class="sv-trend-metric">${displayLabel(t.metric_name)}</span>
                                ${liveChip}
                            </div>
                            <div class="sv-trend-bottom">
                                <span class="sv-trend-slope">${slopeDesc}</span>
                                ${metaStr ? `<span class="sv-trend-meta">${metaStr}</span>` : ""}
                                ${tttHtml}
                            </div>
                        </div>`;
                }).join("");
            };

            const svFetchTrends = async () => {
                if (!svSelectedKey) return;
                const [src, ...rest] = svSelectedKey.split(":");
                const did = rest.join(":");
                try {
                    const r = await fetch(`/api/insights/trends?source=${encodeURIComponent(src)}&device_id=${encodeURIComponent(did)}`);
                    if (!r.ok) return;
                    const d = await r.json();
                    if (d.ok) { svTrendsData = d.trends || []; svTrendsLastFetch = Date.now(); }
                } catch (e) { console.warn("[Sensors] trends fetch failed:", e); }
                svRenderTrends();
            };

            // ── Entry point (called from main refresh loop) ────────────────────
            const svRefresh = (force = false) => {
                const tabBtn   = insightsShell.querySelector('[data-ov-tab="sensors"]');
                const isActive = tabBtn?.classList.contains("is-current");

                svBuildTabs();   // no-op if device set unchanged

                if (!isActive) return;

                // On first activation, build the metric list for the selected device
                if (!svMetricList?.children.length) svRenderMetricList();

                svUpdateLiveValues();

                // Chart: at most every 60 s
                if (force || !svLastFetchMs || (Date.now() - svLastFetchMs) > 60_000) {
                    svFetchAndRenderChart();
                }

                // Rolling stats: at most every 30 s
                if (force || !svStatsLastFetch || (Date.now() - svStatsLastFetch) > 30_000) {
                    svFetchStats();
                }

                // Trends: every 10 s (slopes change quickly)
                if (force || !svTrendsLastFetch || (Date.now() - svTrendsLastFetch) > 10_000) {
                    svFetchTrends();
                } else {
                    // Re-render with current sensitivity even without new data
                    svRenderTrends();
                }
            };

            svRefreshFn = svRefresh;   // expose to outer refresh() loop
        }

        // ── Bootstrap ─────────────────────────────────────────────────────
        // Rebuild cards only when the configured device set changes
        let ovConfiguredKeys = "";

        const refresh = async () => {
            // ── Fetch configured devices ──────────────────────────────────
            let configured = [];
            try {
                const r = await fetch("/api/insights/configured");
                if (r.ok) {
                    const d = await r.json();
                    if (d.ok) configured = d.devices || [];
                }
            } catch (e) {
                console.error("[Insights] configured fetch failed:", e);
            }

            ovConfigured      = configured;
            ovConfiguredCount = configured.length;

            if (configured.length === 0) {
                ovNoSensors?.classList.remove("ov-hidden");
                if (ovDeviceGrid) ovDeviceGrid.innerHTML = "";
            } else {
                ovNoSensors?.classList.add("ov-hidden");

                const newKeys = configured.map((x) => `${x.source}:${x.device_id}`).join(",");
                if (newKeys !== ovConfiguredKeys && ovDeviceGrid) {
                    // Build each card individually so one bad device can't block the rest
                    const htmlParts = [];
                    for (const device of configured) {
                        try {
                            htmlParts.push(buildCard(device));
                        } catch (e) {
                            console.error("[Insights] buildCard failed for", device.name, e);
                            htmlParts.push(`
                                <article class="ov-card is-error">
                                    <header class="ov-card-head">
                                        <div><p class="ov-card-name">${device.name || device.device_id}</p></div>
                                        <span class="ov-status-badge ov-status-error"><span class="ov-status-pulse"></span><span>Error</span></span>
                                    </header>
                                    <div style="padding:1rem;color:var(--muted);font-size:.84rem">Card render error: ${e.message}</div>
                                </article>`);
                        }
                    }
                    ovDeviceGrid.innerHTML = htmlParts.join("");
                    ovConfiguredKeys = newKeys;
                }
            }

            // ── Overlay live Redis data ───────────────────────────────────
            await loadLive();

            // ── Notify Sensors + Events tabs ─────────────────────────────
            if (svRefreshFn) svRefreshFn();
            if (evRefreshFn) evRefreshFn();
        };

        refresh();
        setInterval(refresh, 3000);

        // ══════════════════════════════════════════════════════════════════════
        //  Events tab — diagnostics timeline + Tier 1 alert rules management
        // ══════════════════════════════════════════════════════════════════════
        const evPanel = insightsShell.querySelector('[data-ov-panel="events"]');

        if (evPanel) {
            // ── State ──────────────────────────────────────────────────────────
            let evWindow    = "24h";
            let evSeverity  = "";
            let evDeviceKey = "";
            let evLastFetch = 0;

            // ── DOM refs ───────────────────────────────────────────────────────
            const evTimeline    = evPanel.querySelector("[data-ev-timeline]");
            const evEmpty       = evPanel.querySelector("[data-ev-empty]");
            const evRulesList   = evPanel.querySelector("[data-ev-rules-list]");
            const evRulesBadge  = evPanel.querySelector("[data-ev-rules-badge]");
            const evAddBtn      = evPanel.querySelector("[data-ev-add-btn]");
            const evAddForm     = evPanel.querySelector("[data-ev-add-form]");
            const evFormDevice  = evPanel.querySelector("[data-ev-form-device]");
            const evFormMetric  = evPanel.querySelector("[data-ev-form-metric]");
            const evFormCond    = evPanel.querySelector("[data-ev-form-cond]");
            const evFormThresh  = evPanel.querySelector("[data-ev-form-threshold]");
            const evFormSev     = evPanel.querySelector("[data-ev-form-severity]");
            const evFormSave    = evPanel.querySelector("[data-ev-form-save]");
            const evFormCancel  = evPanel.querySelector("[data-ev-form-cancel]");
            const evFilterSev   = evPanel.querySelector("[data-ev-filter-sev]");
            const evFilterDev   = evPanel.querySelector("[data-ev-filter-device]");
            const evWindowBar   = evPanel.querySelector(".ev-window-bar");

            // ── Helpers ────────────────────────────────────────────────────────
            const evFmtTs = (ms) => {
                if (!ms) return "";
                const d = new Date(ms);
                return d.toLocaleDateString([], { month: "short", day: "numeric" }) + "  " +
                       d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
            };
            const evFmtTime = (ms) => {
                if (!ms) return "";
                return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
            };

            const SEV_TONE = { error: "is-error", critical: "is-critical", warning: "is-warning", info: "is-info", resolved: "is-resolved" };

            // ── Device filter population ───────────────────────────────────────
            const evUpdateDeviceFilter = () => {
                if (!evFilterDev) return;
                const current = evFilterDev.value;
                const opts = ['<option value="">All devices</option>'];
                ovConfigured.forEach((d) => {
                    const k = `${d.source}:${d.device_id}`;
                    opts.push(`<option value="${k}"${k === current ? " selected" : ""}>${d.name || d.device_id}</option>`);
                });
                evFilterDev.innerHTML = opts.join("");
            };

            // ── Alert rules ────────────────────────────────────────────────────
            const evLoadRules = async () => {
                try {
                    const r = await fetch("/api/insights/alert-rules");
                    if (!r.ok) return;
                    const d = await r.json();
                    evRenderRules(d.rules || []);
                } catch (e) {
                    console.warn("[Events] rules fetch failed:", e);
                }
            };

            const evRenderRules = (rules) => {
                if (!evRulesList) return;
                if (evRulesBadge) evRulesBadge.textContent = String(rules.length);
                if (rules.length === 0) {
                    evRulesList.innerHTML = `<p class="ev-rules-empty">No alert rules configured.</p>`;
                    return;
                }
                const SYM = { gt: ">", lt: "<", gte: "≥", lte: "≤", eq: "=" };
                evRulesList.innerHTML = rules.map((rule) => {
                    const on  = rule.enabled;
                    const sev = (rule.severity || "warning").toLowerCase();
                    const sym = SYM[rule.condition] || rule.condition;
                    const expr = `${rule.metric_name} ${sym} ${rule.threshold}`;
                    const label = ovConfigured.find((d) => d.source === rule.source && d.device_id === rule.device_id)?.name || rule.device_id;
                    return `
                        <div class="ev-rule-row" data-rule-id="${rule.id}">
                            <span class="ev-rule-device">${label}</span>
                            <span class="ev-rule-expr">${expr}</span>
                            <span class="ev-rule-sev-pill is-${sev}">${sev}</span>
                            <button class="ev-rule-toggle-btn${on ? " is-on" : ""}" data-rule-toggle="${rule.id}">${on ? "ON" : "OFF"}</button>
                            <button class="ev-rule-del-btn" data-rule-del="${rule.id}" title="Delete">✕</button>
                        </div>`;
                }).join("");

                // Toggle
                evRulesList.querySelectorAll("[data-rule-toggle]").forEach((btn) => {
                    btn.addEventListener("click", async () => {
                        const rid     = Number(btn.getAttribute("data-rule-toggle"));
                        const curr    = btn.classList.contains("is-on");
                        const r       = await fetch(`/api/insights/alert-rules/${rid}`, {
                            method: "PUT",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ enabled: !curr }),
                        });
                        if (r.ok) evLoadRules();
                    });
                });
                // Delete
                evRulesList.querySelectorAll("[data-rule-del]").forEach((btn) => {
                    btn.addEventListener("click", async () => {
                        const rid = Number(btn.getAttribute("data-rule-del"));
                        if (!confirm("Delete this alert rule?")) return;
                        const r = await fetch(`/api/insights/alert-rules/${rid}`, { method: "DELETE" });
                        if (r.ok) evLoadRules();
                    });
                });
            };

            // ── Add-rule form ─────────────────────────────────────────────────
            // Populate device select from ovConfigured
            const evPopulateFormDevices = () => {
                if (!evFormDevice) return;
                evFormDevice.innerHTML = ['<option value="">Device…</option>',
                    ...ovConfigured.map((d) => {
                        const k = `${d.source}|${d.device_id}`;
                        return `<option value="${k}">${d.name || d.device_id}</option>`;
                    })
                ].join("");
            };

            if (evFormDevice) {
                evFormDevice.addEventListener("change", () => {
                    if (!evFormMetric) return;
                    const [src, did] = (evFormDevice.value || "").split("|");
                    const device = ovConfigured.find((d) => d.source === src && d.device_id === did);
                    const metrics = device?.expected_metrics || [];
                    evFormMetric.innerHTML = ['<option value="">Metric…</option>',
                        ...metrics.map((m) => `<option value="${m.name}">${displayLabel(m.name)}</option>`)
                    ].join("");
                });
            }

            if (evAddBtn && evAddForm) {
                evAddBtn.addEventListener("click", () => {
                    evPopulateFormDevices();
                    evAddForm.classList.remove("ev-hidden");
                    evAddBtn.classList.add("ev-hidden");
                });
            }
            if (evFormCancel) {
                evFormCancel.addEventListener("click", () => {
                    evAddForm?.classList.add("ev-hidden");
                    evAddBtn?.classList.remove("ev-hidden");
                });
            }
            if (evFormSave) {
                evFormSave.addEventListener("click", async () => {
                    const [src, did] = (evFormDevice?.value || "").split("|");
                    const metric    = evFormMetric?.value;
                    const cond      = evFormCond?.value;
                    const threshold = evFormThresh?.value;
                    const severity  = evFormSev?.value || "warning";
                    if (!src || !did || !metric || !cond || threshold === "") {
                        alert("Fill in all fields."); return;
                    }
                    try {
                        const r = await fetch("/api/insights/alert-rules", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ source: src, device_id: did, metric_name: metric, condition: cond, threshold: Number(threshold), severity }),
                        });
                        const d = await r.json();
                        if (!d.ok) { alert(d.message || "Failed to save."); return; }
                        evAddForm?.classList.add("ev-hidden");
                        evAddBtn?.classList.remove("ev-hidden");
                        if (evFormDevice)  evFormDevice.value  = "";
                        if (evFormMetric)  evFormMetric.innerHTML = '<option value="">Metric…</option>';
                        if (evFormThresh)  evFormThresh.value   = "";
                        evLoadRules();
                    } catch (e) { alert("Network error."); }
                });
            }

            // ── Event timeline ─────────────────────────────────────────────────
            const evLoadEvents = async () => {
                const params = new URLSearchParams({ window: evWindow });
                if (evSeverity)  params.set("severity",  evSeverity);
                if (evDeviceKey) {
                    const [src, ...rest] = evDeviceKey.split(":");
                    params.set("source",    src);
                    params.set("device_id", rest.join(":"));
                }
                try {
                    const r = await fetch(`/api/insights/events?${params}`);
                    if (!r.ok) return;
                    const d = await r.json();
                    evRenderTimeline(d.events || []);
                    evLastFetch = Date.now();
                } catch (e) {
                    console.warn("[Events] events fetch failed:", e);
                }
            };

            const evRenderTimeline = (events) => {
                if (!evTimeline) return;
                if (events.length === 0) {
                    evTimeline.innerHTML = "";
                    evEmpty?.classList.remove("ev-hidden");
                    return;
                }
                evEmpty?.classList.add("ev-hidden");

                evTimeline.innerHTML = events.map((ev) => {
                    const sev   = (ev.severity || "info").toLowerCase();
                    const tone  = SEV_TONE[sev] || "is-info";
                    const etype = (ev.event_type || "").replace("alert:", "⚡ ");
                    const name  = ev.device_name || ev.device_id || "";
                    const msg   = ev.message || "";
                    const count = ev._count || 1;

                    // Compact timestamp: single → "May 2  13:34:08"
                    //                   range  → "13:23:30 → 13:23:55"
                    const tsDisplay = count > 1
                        ? `${evFmtTime(ev._first_ts)} → ${evFmtTime(ev.timestamp_ms)}`
                        : evFmtTs(ev.timestamp_ms);
                    const fullTs = count > 1
                        ? `${evFmtTs(ev._first_ts)}  →  ${evFmtTs(ev.timestamp_ms)}`
                        : evFmtTs(ev.timestamp_ms);
                    const countBadge = count > 1
                        ? `<span class="ev-count-badge">×${count}</span>`
                        : "";

                    return `
                        <div class="ev-event-row ${tone}">
                            <div class="ev-row-top">
                                <span class="ev-sev-badge ${tone}">${sev}</span>
                                <span class="ev-device">${name}</span>
                                <span class="ev-type">${etype}</span>
                            </div>
                            <div class="ev-row-bottom">
                                <span class="ev-ts" title="${fullTs}">${tsDisplay}</span>
                                ${countBadge}
                                <span class="ev-message" title="${msg}">${msg}</span>
                            </div>
                        </div>`;
                }).join("");
            };

            // ── Filter wiring ──────────────────────────────────────────────────
            if (evFilterSev) {
                evFilterSev.addEventListener("change", () => {
                    evSeverity = evFilterSev.value;
                    evLoadEvents();
                });
            }
            if (evFilterDev) {
                evFilterDev.addEventListener("change", () => {
                    evDeviceKey = evFilterDev.value;
                    evLoadEvents();
                });
            }
            if (evWindowBar) {
                evWindowBar.querySelectorAll("[data-ev-win]").forEach((btn) => {
                    btn.addEventListener("click", () => {
                        evWindow = btn.getAttribute("data-ev-win");
                        evWindowBar.querySelectorAll("[data-ev-win]").forEach((b) => b.classList.remove("is-current"));
                        btn.classList.add("is-current");
                        evLastFetch = 0;
                        evLoadEvents();
                    });
                });
            }

            // ── Entry point ────────────────────────────────────────────────────
            const evRefresh = () => {
                const tabBtn   = insightsShell.querySelector('[data-ov-tab="events"]');
                const isActive = tabBtn?.classList.contains("is-current");

                evUpdateDeviceFilter();

                if (!isActive) return;

                // Load rules once per tab visit (they change rarely)
                if (!evRulesList?.children.length) evLoadRules();

                // Poll events every 10 s
                if (!evLastFetch || (Date.now() - evLastFetch) > 10_000) {
                    evLoadEvents();
                }
            };

            evRefreshFn = evRefresh;
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    //  Data Forwarding page
    // ══════════════════════════════════════════════════════════════════════════
    const fwShell = document.querySelector("[data-forwarding-shell]");
    if (fwShell) {
        // ── DOM refs ────────────────────────────────────────────────────────
        const fwFormCard    = fwShell.querySelector("[data-fw-form]");
        const fwFormTitle   = fwShell.querySelector("[data-fw-form-title]");
        const fwProfileList = fwShell.querySelector("[data-fw-profile-list]");
        const fwEmpty       = fwShell.querySelector("[data-fw-empty]");
        const fwSaveMsg     = fwShell.querySelector("[data-fw-save-msg]");

        const fwFName         = fwShell.querySelector("[data-fw-f-name]");
        const fwFProtocol     = fwShell.querySelector("[data-fw-f-protocol]");
        const fwFEnabled      = fwShell.querySelector("[data-fw-f-enabled]");
        const fwFScope        = fwShell.querySelector("[data-fw-f-scope]");
        // MQTT
        const fwFMqttHost     = fwShell.querySelector("[data-fw-f-mqtt-host]");
        const fwFMqttPort     = fwShell.querySelector("[data-fw-f-mqtt-port]");
        const fwFMqttTls      = fwShell.querySelector("[data-fw-f-mqtt-tls]");
        const fwFMqttCid      = fwShell.querySelector("[data-fw-f-mqtt-client-id]");
        const fwFMqttUser     = fwShell.querySelector("[data-fw-f-mqtt-user]");
        const fwFMqttPass     = fwShell.querySelector("[data-fw-f-mqtt-pass]");
        const fwFMqttQos      = fwShell.querySelector("[data-fw-f-mqtt-qos]");
        const fwFMqttRetain   = fwShell.querySelector("[data-fw-f-mqtt-retain]");
        const fwFMqttInterval = fwShell.querySelector("[data-fw-f-mqtt-interval]");
        const fwMqttTlsBlock  = fwShell.querySelector("[data-fw-mqtt-tls-block]");
        // HTTPS
        const fwFHttpsHost       = fwShell.querySelector("[data-fw-f-https-host]");
        const fwFHttpsPort       = fwShell.querySelector("[data-fw-f-https-port]");
        const fwFHttpsTlsBtn     = fwShell.querySelector("[data-fw-f-https-tls]");
        const fwFHttpsSensorPath    = fwShell.querySelector("[data-fw-f-https-sensor-path]");
        const fwFHttpsAnalyticsPath = fwShell.querySelector("[data-fw-f-https-analytics-path]");
        const fwFHttpsEventsPath    = fwShell.querySelector("[data-fw-f-https-events-path]");
        const fwFHttpsAuth       = fwShell.querySelector("[data-fw-f-https-auth-type]");
        const fwFHttpsAVal       = fwShell.querySelector("[data-fw-f-https-auth-val]");
        const fwFHttpsMtls       = fwShell.querySelector("[data-fw-f-https-mtls]");
        const fwFHttpsInt        = fwShell.querySelector("[data-fw-f-https-interval]");
        const fwFHttpsTout       = fwShell.querySelector("[data-fw-f-https-timeout]");
        const fwAuthValWrap      = fwShell.querySelector("[data-fw-auth-val-wrap]");
        const fwAuthValLbl       = fwShell.querySelector("[data-fw-auth-val-label]");
        const fwHttpsMtlsBlock   = fwShell.querySelector("[data-fw-https-mtls-block]");
        const fwHttpsTlsSection  = fwShell.querySelector("[data-fw-https-tls-section]");
        const fwHttpsSensorPrev    = fwShell.querySelector("[data-fw-https-sensor-preview]");
        const fwHttpsAnalyticsPrev = fwShell.querySelector("[data-fw-https-analytics-preview]");
        const fwHttpsEventsPrev    = fwShell.querySelector("[data-fw-https-events-preview]");

        // ── State ────────────────────────────────────────────────────────────
        let fwProfiles   = [];
        let fwEditId     = null;
        let fwEnabledVal = false;
        let fwTlsVal      = false;   // MQTT TLS
        let fwHttpsTlsVal = true;    // HTTPS TLS (default on)
        let fwRetainVal   = false;
        let fwMtlsVal     = false;

        // ── Cert widget factory ──────────────────────────────────────────────
        const fwInitCertWidget = (container) => {
            if (!container) return { getValue: () => null, setLoaded: () => {} };
            const fileInput = container.querySelector("[data-fw-cert-file]");
            const textarea  = container.querySelector("[data-fw-cert-val]");
            const status    = container.querySelector("[data-fw-cert-status]");
            const clearBtn  = container.querySelector("[data-fw-cert-clear]");
            const uploadBtn = container.querySelector("[data-fw-cert-btn]");

            let widgetState = "none"; // "none" | "server" | "new" | "cleared"

            const setStatus = (filename) => {
                // state: "none" | "server" | "new" | "cleared"
                if (!status) return;
                if (widgetState === "server") {
                    status.textContent = "✓ cert on device";
                    status.classList.add("is-loaded");
                    clearBtn?.classList.remove("fw-hidden");
                } else if (widgetState === "new" && filename) {
                    status.textContent = `✓ ${filename}`;
                    status.classList.add("is-loaded");
                    clearBtn?.classList.remove("fw-hidden");
                } else if (widgetState === "cleared") {
                    status.textContent = "Will be removed on save";
                    status.classList.remove("is-loaded");
                    clearBtn?.classList.add("fw-hidden");
                } else {
                    status.textContent = "No file";
                    status.classList.remove("is-loaded");
                    clearBtn?.classList.add("fw-hidden");
                }
            };

            uploadBtn?.addEventListener("click", () => fileInput?.click());
            fileInput?.addEventListener("change", () => {
                const file = fileInput.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = (e) => {
                    widgetState = "new";
                    if (textarea) textarea.value = e.target.result;
                    setStatus(file.name);
                };
                reader.readAsText(file);
                fileInput.value = "";
            });
            clearBtn?.addEventListener("click", () => {
                widgetState = "cleared";
                if (textarea) textarea.value = "";
                setStatus();
            });

            return {
                // null = keep existing  |  "" = delete  |  "<pem>" = new content
                getValue: () => {
                    if (widgetState === "server")  return null;   // keep on device
                    if (widgetState === "cleared") return "";     // delete from device
                    if (widgetState === "new")     return textarea?.value?.trim() || null;
                    return null; // "none"
                },
                // Called when loading a profile that already has a cert on the device
                setLoaded: (isLoaded) => {
                    widgetState = isLoaded ? "server" : "none";
                    if (textarea) textarea.value = "";
                    setStatus();
                },
            };
        };

        // Initialise all cert widgets keyed by data-fw-cert attribute
        const fwCerts = {};
        fwShell.querySelectorAll("[data-fw-cert]").forEach((el) => {
            fwCerts[el.getAttribute("data-fw-cert")] = fwInitCertWidget(el);
        });

        // ── Toggle button helper ─────────────────────────────────────────────
        const fwToggle = (btn, getVal, setVal) => {
            if (!btn) return;
            btn.addEventListener("click", () => {
                setVal(!getVal());
                btn.classList.toggle("is-on", getVal());
                btn.textContent = getVal() ? "ON" : "OFF";
            });
        };

        fwToggle(fwFEnabled, () => fwEnabledVal, (v) => { fwEnabledVal = v; });

        fwToggle(fwFMqttTls, () => fwTlsVal, (v) => {
            fwTlsVal = v;
            if (fwFMqttPort && !fwFMqttPort._userEdited) {
                fwFMqttPort.value = v ? 8883 : 1883;
            }
            fwMqttTlsBlock?.classList.toggle("fw-hidden", !v);
        });
        if (fwFMqttPort) {
            fwFMqttPort.addEventListener("input", () => { fwFMqttPort._userEdited = true; });
        }

        fwToggle(fwFMqttRetain, () => fwRetainVal, (v) => { fwRetainVal = v; });

        fwToggle(fwFHttpsTlsBtn, () => fwHttpsTlsVal, (v) => {
            fwHttpsTlsVal = v;
            fwHttpsTlsSection?.classList.toggle("fw-hidden", !v);
            // When TLS is turned off, also collapse mTLS cert section
            if (!v) {
                fwMtlsVal = false;
                fwSyncToggleBtn(fwFHttpsMtls, false);
                fwHttpsMtlsBlock?.classList.add("fw-hidden");
            }
            fwUpdateHttpsPreview();
        });

        fwToggle(fwFHttpsMtls, () => fwMtlsVal, (v) => {
            fwMtlsVal = v;
            fwHttpsMtlsBlock?.classList.toggle("fw-hidden", !v);
        });

        // ── Protocol switch ──────────────────────────────────────────────────
        const fwShowProto = (proto) => {
            fwShell.querySelectorAll("[data-fw-proto]").forEach((el) => {
                el.classList.toggle("fw-hidden", el.getAttribute("data-fw-proto") !== proto);
            });
        };
        fwFProtocol?.addEventListener("change", () => fwShowProto(fwFProtocol.value));

        // ── HTTPS auth type → show/hide auth value ───────────────────────────
        const fwUpdateAuthLabel = () => {
            const t = fwFHttpsAuth?.value;
            fwAuthValWrap?.classList.toggle("fw-hidden", t === "none");
            const labels = { bearer: "Bearer Token", api_key: "API Key", basic: "user:password" };
            if (fwAuthValLbl) fwAuthValLbl.textContent = labels[t] || "Token / Key";
        };
        fwFHttpsAuth?.addEventListener("change", fwUpdateAuthLabel);

        // ── HTTPS URL preview ────────────────────────────────────────────────
        const fwUpdateHttpsPreview = () => {
            const host    = fwFHttpsHost?.value.trim() || "host";
            const port    = Number(fwFHttpsPort?.value) || 443;
            const scheme  = fwHttpsTlsVal ? "https" : "http";
            const defPort = fwHttpsTlsVal ? 443 : 80;
            const ps      = port === defPort ? "" : `:${port}`;
            const base    = `${scheme}://${host}${ps}`;
            const sp    = fwFHttpsSensorPath?.value.trim();
            const ap    = fwFHttpsAnalyticsPath?.value.trim();
            const ep    = fwFHttpsEventsPath?.value.trim();
            if (fwHttpsSensorPrev)    fwHttpsSensorPrev.textContent    = sp ? `${base}${sp}` : "—";
            if (fwHttpsAnalyticsPrev) fwHttpsAnalyticsPrev.textContent = ap ? `${base}${ap}` : "(not configured)";
            if (fwHttpsEventsPrev)    fwHttpsEventsPrev.textContent    = ep ? `${base}${ep}` : "(not configured)";
        };
        [fwFHttpsHost, fwFHttpsPort, fwFHttpsSensorPath, fwFHttpsAnalyticsPath, fwFHttpsEventsPath].forEach((el) => {
            el?.addEventListener("input", fwUpdateHttpsPreview);
        });

        // ── Panel toggles (MQTT topics + HTTPS endpoint reference) ──────────
        const fwInitPanelToggle = (toggleAttr, bodyAttr, arrowAttr) => {
            fwShell.querySelectorAll(`[${toggleAttr}]`).forEach((btn) => {
                btn.addEventListener("click", () => {
                    const body  = fwShell.querySelector(`[${bodyAttr}]`);
                    const arrow = fwShell.querySelector(`[${arrowAttr}]`);
                    const shown = !body?.classList.contains("fw-hidden");
                    body?.classList.toggle("fw-hidden", shown);
                    if (arrow) arrow.textContent = shown ? "▼" : "▲";
                });
            });
        };
        fwInitPanelToggle("data-fw-topics-toggle",   "data-fw-topics-body",   "data-fw-topics-arrow");
        fwInitPanelToggle("data-fw-https-ref-toggle", "data-fw-https-ref-body", "data-fw-https-ref-arrow");

        // ── Gateway ID display (live from API) ───────────────────────────────
        const fwApplyGatewayId = (gwId) => {
            if (!gwId) return;
            // Pattern box and "live" label
            fwShell.querySelectorAll("[data-fw-gw-id]").forEach((el) => { el.textContent = gwId; });
            fwShell.querySelectorAll("[data-fw-gw-live]").forEach((el) => { el.textContent = gwId; });
            // Example chip in the label text
            fwShell.querySelectorAll("[data-fw-gw-eg]").forEach((el) => { el.textContent = gwId; });
            // Topic example rows
            fwShell.querySelectorAll("[data-fw-topic-eg]").forEach((el) => {
                const suffix = el.getAttribute("data-fw-topic-eg");
                el.textContent = `${gwId}/${suffix}`;
            });
        };

        // ── Load config ──────────────────────────────────────────────────────
        const fwLoad = async () => {
            try {
                const r = await fetch("/api/forwarding/config");
                if (!r.ok) return;
                const d = await r.json();
                fwProfiles = d.profiles || [];
                fwApplyGatewayId(d.gateway_id || "");
            } catch (e) {
                console.warn("[Forwarding] load failed:", e);
            }
            fwRender();
        };

        // ── Save config ──────────────────────────────────────────────────────
        const fwSave = async () => {
            if (fwSaveMsg) { fwSaveMsg.textContent = ""; fwSaveMsg.className = "fw-save-msg"; }

            const proto = fwFProtocol?.value || "mqtt";
            const profile = {
                id:       fwEditId || "",
                name:     fwFName?.value.trim() || "Unnamed Profile",
                enabled:  fwEnabledVal,
                protocol: proto,
                scope:    fwFScope?.value || "all",
            };

            if (proto === "mqtt") {
                profile.mqtt = {
                    host:             fwFMqttHost?.value.trim() || "",
                    port:             Number(fwFMqttPort?.value) || 1883,
                    tls:              fwTlsVal,
                    tls_ca:           fwCerts["mqtt-ca"]?.getValue(),
                    tls_cert:         fwCerts["mqtt-cert"]?.getValue(),
                    tls_key:          fwCerts["mqtt-key"]?.getValue(),
                    client_id:        fwFMqttCid?.value.trim()  || "",
                    username:         fwFMqttUser?.value.trim() || "",
                    password:         fwFMqttPass?.value        || "",
                    qos:              Number(fwFMqttQos?.value) || 1,
                    retain:           fwRetainVal,
                    interval_seconds: Number(fwFMqttInterval?.value) || 5,
                };
            } else {
                const hasMtls = fwMtlsVal;
                profile.https = {
                    host:             fwFHttpsHost?.value.trim() || "",
                    port:             Number(fwFHttpsPort?.value) || 443,
                    tls:              fwHttpsTlsVal,
                    sensor_path:      fwFHttpsSensorPath?.value.trim()    || "/ingest",
                    analytics_path:   fwFHttpsAnalyticsPath?.value.trim() || "",
                    events_path:      fwFHttpsEventsPath?.value.trim()    || "",
                    auth_type:        fwFHttpsAuth?.value || "none",
                    auth_value:       fwFHttpsAVal?.value || "",
                    // null=keep, ""=clear, "<pem>"=new. When mTLS toggled OFF, send "" to clear all.
                    tls_ca:           hasMtls ? fwCerts["https-ca"]?.getValue()   : "",
                    tls_cert:         hasMtls ? fwCerts["https-cert"]?.getValue() : "",
                    tls_key:          hasMtls ? fwCerts["https-key"]?.getValue()  : "",
                    interval_seconds: Number(fwFHttpsInt?.value)  || 30,
                    timeout_seconds:  Number(fwFHttpsTout?.value) || 10,
                };
            }

            if (fwEditId) {
                const idx = fwProfiles.findIndex((p) => p.id === fwEditId);
                if (idx >= 0) fwProfiles[idx] = profile;
                else fwProfiles.push(profile);
            } else {
                fwProfiles.push(profile);
            }

            try {
                const r = await fetch("/api/forwarding/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ profiles: fwProfiles }),
                });
                const d = await r.json();
                if (d.ok) {
                    if (fwSaveMsg) fwSaveMsg.textContent = "Saved.";
                    fwHideForm();
                    await fwLoad();
                    // Rebuild name map so Live Status + Buffer show new name immediately
                    await _buildConfigNameMap();
                    fwConfigNameMap = { ...fwConfigNameMap }; // force re-render trigger
                    fwRefreshStatus();
                    fwRefreshBuffer();
                    // Switch to Profiles tab so user sees the updated profile list
                    syncFwTabs("profiles");
                } else {
                    if (fwSaveMsg) { fwSaveMsg.textContent = d.message || "Save failed."; fwSaveMsg.className = "fw-save-msg is-error"; }
                }
            } catch (e) {
                if (fwSaveMsg) { fwSaveMsg.textContent = "Network error."; fwSaveMsg.className = "fw-save-msg is-error"; }
            }
        };

        // ── Form show / hide ─────────────────────────────────────────────────
        const fwSyncToggleBtn = (btn, val) => {
            if (!btn) return;
            btn.classList.toggle("is-on", val);
            btn.textContent = val ? "ON" : "OFF";
        };

        // ── Protocol option management (1 MQTT max) ──────────────────────────
        const _MAX_HTTPS_PROFILES = 5;

        const fwUpdateProtocolOptions = (editingProfileId = null) => {
            if (!fwFProtocol) return;
            const mqttTaken = fwProfiles.some(
                (p) => p.protocol === "mqtt" && p.id !== editingProfileId
            );
            const httpsCount = fwProfiles.filter(
                (p) => p.protocol === "https" && p.id !== editingProfileId
            ).length;
            const httpsFull = httpsCount >= _MAX_HTTPS_PROFILES;

            const mqttOpt  = fwFProtocol.querySelector('option[value="mqtt"]');
            const httpsOpt = fwFProtocol.querySelector('option[value="https"]');
            if (mqttOpt) {
                mqttOpt.disabled    = mqttTaken;
                mqttOpt.textContent = mqttTaken
                    ? "MQTT / MQTTS  (1 profile already configured)"
                    : "MQTT / MQTTS";
            }
            if (httpsOpt) {
                httpsOpt.disabled    = httpsFull;
                httpsOpt.textContent = httpsFull
                    ? `HTTPS / mTLS  (${_MAX_HTTPS_PROFILES} profiles max)`
                    : "HTTPS / mTLS";
            }
        };

        const fwShowForm = (profile = null) => {
            fwEditId = profile?.id || null;
            if (fwFormTitle) fwFormTitle.textContent = profile ? `Edit: ${profile.name}` : "New Forwarding Profile";

            // For new profiles: default to HTTPS if MQTT is already taken
            const mqttTaken = fwProfiles.some((p) => p.protocol === "mqtt" && p.id !== fwEditId);
            const proto = profile?.protocol || (mqttTaken ? "https" : "mqtt");
            fwUpdateProtocolOptions(fwEditId);
            if (fwFProtocol) fwFProtocol.value = proto;
            fwShowProto(proto);

            fwEnabledVal = profile ? !!profile.enabled : false;
            fwSyncToggleBtn(fwFEnabled, fwEnabledVal);

            if (fwFName)  fwFName.value  = profile?.name  || "";
            if (fwFScope) fwFScope.value = profile?.scope || "all";

            if (proto === "mqtt") {
                const m = profile?.mqtt || {};
                if (fwFMqttHost)     fwFMqttHost.value   = m.host || "";
                if (fwFMqttPort)     { fwFMqttPort.value = m.port || 1883; fwFMqttPort._userEdited = false; }
                if (fwFMqttCid)      fwFMqttCid.value    = m.client_id || "";
                if (fwFMqttUser)     fwFMqttUser.value   = m.username  || "";
                if (fwFMqttPass)     fwFMqttPass.value   = m.password  || "";
                if (fwFMqttQos)      fwFMqttQos.value    = String(m.qos ?? 1);
                if (fwFMqttInterval) fwFMqttInterval.value = String(m.interval_seconds || 5);

                fwTlsVal = !!m.tls;
                fwSyncToggleBtn(fwFMqttTls, fwTlsVal);
                fwMqttTlsBlock?.classList.toggle("fw-hidden", !fwTlsVal);

                fwRetainVal = !!m.retain;
                fwSyncToggleBtn(fwFMqttRetain, fwRetainVal);

                // API returns _loaded flags, not PEM content
                fwCerts["mqtt-ca"]?.setLoaded(!!m.tls_ca_loaded);
                fwCerts["mqtt-cert"]?.setLoaded(!!m.tls_cert_loaded);
                fwCerts["mqtt-key"]?.setLoaded(!!m.tls_key_loaded);

            } else {
                const h = profile?.https || {};
                fwHttpsTlsVal = h.tls !== undefined ? !!h.tls : true;
                fwSyncToggleBtn(fwFHttpsTlsBtn, fwHttpsTlsVal);
                fwHttpsTlsSection?.classList.toggle("fw-hidden", !fwHttpsTlsVal);
                if (fwFHttpsHost)           fwFHttpsHost.value           = h.host            || "";
                if (fwFHttpsPort)           fwFHttpsPort.value           = String(h.port     || 443);
                if (fwFHttpsSensorPath)     fwFHttpsSensorPath.value     = h.sensor_path     || "/ingest";
                if (fwFHttpsAnalyticsPath)  fwFHttpsAnalyticsPath.value  = h.analytics_path  || "";
                if (fwFHttpsEventsPath)     fwFHttpsEventsPath.value     = h.events_path     || "";
                if (fwFHttpsAuth)       fwFHttpsAuth.value       = h.auth_type    || "none";
                if (fwFHttpsAVal)       fwFHttpsAVal.value       = h.auth_value   || "";
                if (fwFHttpsInt)        fwFHttpsInt.value        = String(h.interval_seconds || 30);
                if (fwFHttpsTout)       fwFHttpsTout.value       = String(h.timeout_seconds  || 10);

                const hasCerts = !!(h.tls_ca_loaded || h.tls_cert_loaded || h.tls_key_loaded);
                fwMtlsVal = hasCerts;
                fwSyncToggleBtn(fwFHttpsMtls, fwMtlsVal);
                fwHttpsMtlsBlock?.classList.toggle("fw-hidden", !fwMtlsVal);

                fwCerts["https-ca"]?.setLoaded(!!h.tls_ca_loaded);
                fwCerts["https-cert"]?.setLoaded(!!h.tls_cert_loaded);
                fwCerts["https-key"]?.setLoaded(!!h.tls_key_loaded);

                fwUpdateAuthLabel();
                fwUpdateHttpsPreview();
            }

            fwFormCard?.classList.remove("fw-hidden");
            fwFormCard?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        };

        const fwHideForm = () => {
            fwFormCard?.classList.add("fw-hidden");
            fwEditId = null;
        };

        // ── Render profile list ──────────────────────────────────────────────
        const fwRender = () => {
            if (!fwProfileList) return;
            if (fwProfiles.length === 0) {
                fwProfileList.innerHTML = "";
                fwEmpty?.classList.remove("ov-hidden");
                fwUpdateProtocolOptions();
                return;
            }
            fwEmpty?.classList.add("ov-hidden");
            fwUpdateProtocolOptions();

            fwProfileList.innerHTML = fwProfiles.map((p) => {
                const proto   = p.protocol || "mqtt";
                const enabled = p.enabled;
                let details   = "";

                if (proto === "mqtt") {
                    const m    = p.mqtt || {};
                    const sec  = m.tls ? (m.tls_cert_loaded ? " · mTLS" : " · TLS") : "";
                    const intvl = `every ${m.interval_seconds || 5} s`;
                    details = `
                        <div class="fw-profile-detail">
                            <span class="fw-detail-label">Broker</span>
                            <span class="fw-detail-val">${m.host || "—"}:${m.port || 1883}${sec}</span>
                        </div>
                        <div class="fw-profile-detail">
                            <span class="fw-detail-label">Topics</span>
                            <span class="fw-detail-val">metacrust/{source}/{device_id}/{metric}</span>
                        </div>
                        <div class="fw-profile-detail">
                            <span class="fw-detail-label">QoS</span>
                            <span class="fw-detail-val">${m.qos ?? 1} · retain ${m.retain ? "on" : "off"}</span>
                        </div>
                        <div class="fw-profile-detail">
                            <span class="fw-detail-label">Publish</span>
                            <span class="fw-detail-val">${intvl}</span>
                        </div>`;
                } else {
                    const h       = p.https || {};
                    const port    = Number(h.port) || 443;
                    const scheme  = h.tls !== false ? "https" : "http";
                    const defPort = h.tls !== false ? 443 : 80;
                    const ps      = port === defPort ? "" : `:${port}`;
                    const base    = `${scheme}://${h.host || "—"}${ps}`;
                    const sec   = h.tls_cert_loaded ? " · mTLS" : h.tls_ca_loaded ? " · custom CA" : "";
                    details = `
                        <div class="fw-profile-detail">
                            <span class="fw-detail-label">Sensor URL</span>
                            <span class="fw-detail-val">${base}${h.sensor_path || "/ingest"}${sec}</span>
                        </div>
                        ${h.analytics_path ? `
                        <div class="fw-profile-detail">
                            <span class="fw-detail-label">Analytics URL</span>
                            <span class="fw-detail-val">${base}${h.analytics_path}</span>
                        </div>` : ""}
                        ${h.events_path ? `
                        <div class="fw-profile-detail">
                            <span class="fw-detail-label">Events URL</span>
                            <span class="fw-detail-val">${base}${h.events_path}</span>
                        </div>` : ""}
                        <div class="fw-profile-detail">
                            <span class="fw-detail-label">Auth</span>
                            <span class="fw-detail-val">${h.auth_type || "none"}</span>
                        </div>
                        <div class="fw-profile-detail">
                            <span class="fw-detail-label">POST</span>
                            <span class="fw-detail-val">every ${h.interval_seconds || 30} s</span>
                        </div>`;
                }

                return `
                    <div class="fw-profile-card ${enabled ? "is-enabled" : "is-disabled"}" data-fw-card="${p.id}">
                        <div class="fw-profile-head">
                            <span class="fw-profile-name">${p.name || "Unnamed"}</span>
                            <span class="fw-proto-badge is-${proto}">${proto === "mqtt" ? "MQTT" : "HTTPS"}</span>
                            <span class="fw-profile-status ${enabled ? "is-on" : "is-off"}">${enabled ? "● Active" : "○ Disabled"}</span>
                            <div class="fw-profile-actions">
                                <button class="fw-action-btn" data-fw-edit="${p.id}">Edit</button>
                                <button class="fw-action-btn is-del" data-fw-del="${p.id}">Delete</button>
                            </div>
                        </div>
                        <div class="fw-profile-body">${details}
                            <div class="fw-profile-detail">
                                <span class="fw-detail-label">Scope</span>
                                <span class="fw-detail-val">${p.scope === "all" ? "All devices" : p.scope}</span>
                            </div>
                        </div>
                    </div>`;
            }).join("");

            fwProfileList.querySelectorAll("[data-fw-edit]").forEach((btn) => {
                btn.addEventListener("click", () => {
                    const id = btn.getAttribute("data-fw-edit");
                    fwShowForm(fwProfiles.find((p) => p.id === id) || null);
                });
            });
            fwProfileList.querySelectorAll("[data-fw-del]").forEach((btn) => {
                btn.addEventListener("click", async () => {
                    const id   = btn.getAttribute("data-fw-del");
                    const prof = fwProfiles.find((p) => p.id === id);
                    if (!confirm(`Delete profile "${prof?.name || id}"?`)) return;
                    fwProfiles = fwProfiles.filter((p) => p.id !== id);
                    await fetch("/api/forwarding/config", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ profiles: fwProfiles }),
                    });
                    fwRender();
                });
            });
        };

        // ── Wire static buttons ──────────────────────────────────────────────
        // Use document scope — the "+ Add Profile" header button is outside fwShell
        document.querySelectorAll("[data-fw-add]").forEach((btn) => {
            btn.addEventListener("click", () => fwShowForm(null));
        });
        fwShell.querySelector("[data-fw-cancel]")?.addEventListener("click", fwHideForm);
        fwShell.querySelector("[data-fw-save]")?.addEventListener("click", fwSave);

        // ── Live status overview panel ────────────────────────────────────────
        const fwStatusPanel = fwShell.querySelector("[data-fw-status-panel]");
        const fwStatusList  = fwShell.querySelector("[data-fw-status-list]");
        const fwStatusTs    = fwShell.querySelector("[data-fw-status-ts]");

        // Shared map: profile_id → {name, protocol} so buffer panel can show names
        let fwProfileMeta = {};

        const _fwAgo = (secs) => {
            if (secs === null || secs === undefined) return "—";
            if (secs < 2)   return "just now";
            if (secs < 60)  return `${secs}s ago`;
            if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
            const h = Math.floor(secs / 3600);
            const m = Math.floor((secs % 3600) / 60);
            return m > 0 ? `${h}h ${m}m ago` : `${h}h ago`;
        };

        const _fwDur = (secs) => {
            if (!secs) return "—";
            if (secs < 60)  return `${secs}s`;
            if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
            if (secs < 86400) {
                const h = Math.floor(secs / 3600);
                const m = Math.floor((secs % 3600) / 60);
                return m > 0 ? `${h}h ${m}m` : `${h}h`;
            }
            const d = Math.floor(secs / 86400);
            const h = Math.floor((secs % 86400) / 3600);
            return h > 0 ? `${d}d ${h}h` : `${d}d`;
        };

        const _fwDurMs = (ms) => (ms || ms === 0) ? _fwDur(Math.round(ms / 1000)) : "—";

        const _fwDateTime = (ms) => {
            if (!ms) return "—";
            return new Date(ms).toLocaleString(undefined, {
                year: "numeric",
                month: "short",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
            });
        };

        const _fwEsc = (v) => String(v ?? "").replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        }[ch]));

        const _fwEventLabel = (type) => ({
            outage_started: "Outage started",
            outage_recovered: "Recovered",
            buffer_eviction: "Buffer eviction",
        }[type] || String(type || "event").replaceAll("_", " "));

        const _fwSeverityClass = (sev) => {
            if (sev === "error" || sev === "critical") return "is-err";
            if (sev === "warning") return "is-warn";
            return "is-ok";
        };

        const _fwEventReason = (event) => {
            if (event.reason) return event.reason;
            if (event.message) return event.message;
            return "No reason recorded.";
        };

        const _fwBuildAuditUrl = (csv = false) => {
            const win = fwShell.querySelector("[data-fw-audit-window]")?.value || (csv ? "30d" : "7d");
            return `/api/forwarding/events${csv ? "/export/csv" : ""}?window=${encodeURIComponent(win)}`;
        };

        const _fwRefreshAuditExport = () => {
            const exportLink = fwShell.querySelector("[data-fw-audit-export]");
            if (exportLink) exportLink.href = _fwBuildAuditUrl(true);
        };

        const _fwStateLabel = (item, isMqtt) => {
            if (isMqtt) {
                const map = { connected: "Connected", connecting: "Reconnecting…", error: "Connection error", stopped: "Stopped" };
                return map[item.state] || item.state;
            }
            return item.tunnel_alive ? "Connected" : "Connection down";
        };

        const _fwStateCls = (item, isMqtt) => {
            if (isMqtt) {
                if (item.state === "connected") return "is-ok";
                if (item.state === "connecting") return "is-warn";
                return "is-err";
            }
            return item.tunnel_alive ? "is-ok" : "is-err";
        };

        const fwRefreshStatus = async () => {
            if (!fwStatusPanel) return;
            try {
                const r = await fetch("/api/forwarding/status");
                if (!r.ok) return;
                const d = await r.json();
                if (!d.ok) return;

                const mqttItems  = (d.mqtt  || []).map((x) => ({...x, _isMqtt: true}));
                const httpsItems = (d.https || []).map((x) => ({...x, _isMqtt: false}));
                const all = [...mqttItems, ...httpsItems];

                // Build profile name/protocol lookup for buffer panel
                fwProfileMeta = {};
                for (const item of all) {
                    fwProfileMeta[item.profile_id] = {
                        name:     item.profile_name || item.profile_id,
                        protocol: item._isMqtt ? "MQTT" : "HTTPS",
                    };
                }

                const fwNoProfilesHint = fwShell.querySelector("[data-fw-status-no-profiles]");
                if (all.length === 0) {
                    fwStatusPanel.classList.add("ov-hidden");
                    if (fwNoProfilesHint) fwNoProfilesHint.classList.remove("ov-hidden");
                    return;
                }
                if (fwNoProfilesHint) fwNoProfilesHint.classList.add("ov-hidden");
                fwStatusPanel.classList.remove("ov-hidden");
                if (fwStatusTs) fwStatusTs.textContent = `Updated ${new Date().toLocaleTimeString()}`;

                // ── Pipeline alert banner ────────────────────────────────────
                const pipelineAlert  = fwShell.querySelector("[data-fw-pipeline-alert]");
                const totalPending   = all.reduce((s, x) => s + (x.buffer?.pending   ?? 0), 0);
                const totalReplayed  = all.reduce((s, x) => s + (x.buffer?.replayed  ?? 0), 0);
                const totalDropped   = all.reduce((s, x) => s + (x.buffer?.dropped   ?? 0), 0);

                // Find profiles with issues for root-cause context
                const droppingProfiles = all.filter((x) => (x.buffer?.dropped ?? 0) > 0);
                const bufferingProfiles = all.filter((x) => (x.buffer?.pending ?? 0) > 0);

                if (pipelineAlert) {
                    const isActive = totalPending > 0 || totalDropped > 0;
                    pipelineAlert.classList.toggle("ov-hidden", !isActive);
                    if (isActive) {
                        const titleEl  = pipelineAlert.querySelector("[data-fw-pa-title]");
                        const detailEl = pipelineAlert.querySelector("[data-fw-pa-detail]");
                        const pendEl   = pipelineAlert.querySelector("[data-fw-pa-pending]");
                        const recEl    = pipelineAlert.querySelector("[data-fw-pa-recovered]");
                        const dropEl   = pipelineAlert.querySelector("[data-fw-pa-dropped]");

                        // Build a helpful root-cause detail
                        const rootCauses = droppingProfiles.map((x) => {
                            const name = x.profile_name || "a profile";
                            const http = x.last_status_code ? ` (HTTP ${x.last_status_code})` : "";
                            const err  = x.last_error ? ` — ${x.last_error}` : http;
                            return `"${name}" is rejecting delivery${err}`;
                        });

                        if (titleEl) {
                            titleEl.textContent = totalDropped > 0
                                ? `${totalDropped} message${totalDropped > 1 ? "s" : ""} evicted from buffer — local buffer was full`
                                : `${totalPending} message${totalPending > 1 ? "s" : ""} saved locally, waiting for delivery`;
                        }
                        if (detailEl) {
                            detailEl.textContent = totalDropped > 0
                                ? `The local buffer reached capacity and oldest messages were removed to make room for new data. Connection issues may be preventing delivery — check profile status below.`
                                : totalPending > 0
                                ? `Messages are stored safely in the local buffer and will be sent automatically when the connection recovers.${totalReplayed > 0 ? ` ${totalReplayed} already recovered and delivered.` : ""}`
                                : "Check the profile configuration below.";
                        }
                        if (pendEl)  pendEl.textContent  = totalPending.toLocaleString();
                        if (recEl)   recEl.textContent   = totalReplayed.toLocaleString();
                        if (dropEl)  dropEl.textContent  = totalDropped.toLocaleString();
                    }
                }

                if (fwStatusList) {
                    fwStatusList.innerHTML = all.map((item) => {
                        const isMqtt   = item._isMqtt;
                        const stCls    = _fwStateCls(item, isMqtt);
                        const stLbl    = _fwStateLabel(item, isMqtt);
                        const badge    = isMqtt ? "MQTT" : "HTTPS";
                        const dest     = isMqtt ? item.broker : item.endpoint;
                        const tlsNote  = item.tls ? `<span class="fw-tls-chip">TLS</span>` : "";
                        // Resolve name from config map (always up-to-date after save)
                        const profileName = (item.profile_id && fwConfigNameMap[item.profile_id]?.name)
                            || item.profile_name || "Unnamed Profile";
                        const count    = isMqtt ? (item.publish_count ?? 0) : (item.post_count ?? 0);
                        const pending  = item.buffer?.pending  ?? 0;
                        const replayed = item.buffer?.replayed ?? 0;
                        const dropped  = item.buffer?.dropped  ?? 0;
                        const sucRate  = item.buffer?.success_rate ?? 100;

                        // Connection downtime (when not connected)
                        const downSecs = isMqtt ? item.not_connected_since : item.down_since_ago;
                        const isDown   = isMqtt ? (item.state !== "connected") : (!item.tunnel_alive);
                        const openOutage = item.open_outage || null;
                        const downStartedMs = openOutage?.started_at_ms || (isMqtt ? item.not_connected_since_ms : item.down_since_ms);
                        const lastMsgMs = isMqtt ? item.last_publish_at_ms : item.last_post_at_ms;
                        const lastErrMs = item.last_error_at_ms;

                        // Session uptime & message rate
                        const connSecs   = item.connected_since ?? 0;
                        const sessionStr = connSecs > 0 ? _fwDur(connSecs) : "—";
                        const ratePerSec = connSecs > 10 && count > 0 ? count / connSecs : 0;
                        const rateStr = ratePerSec >= 1
                            ? `${ratePerSec.toFixed(1)}/s`
                            : ratePerSec > 0 ? `${Math.round(ratePerSec * 60)}/min`
                            : "—";

                        // Last event line
                        const lastAgo  = isMqtt ? item.last_publish_ago : item.last_post_ago;
                        const lastStr  = lastAgo != null ? _fwAgo(lastAgo) : "never";
                        const httpInfo = !isMqtt && item.last_status_code ? ` · HTTP ${item.last_status_code}` : "";
                        const restarts = !isMqtt && item.tunnel_restarts > 5 ? ` · ${item.tunnel_restarts} reconnects` : "";

                        // Downtime banner (when connection is down)
                        const downLabel = isMqtt
                            ? (item.state === "connecting" ? "Reconnecting…" : "Connection error —")
                            : "Connection down —";
                        const downHtml = isDown && downSecs != null
                            ? `<div class="fw-st-downtime">
                                <span class="fw-st-dt-label">${downLabel}</span>
                                <span class="fw-st-dt-dur">down for ${_fwDur(downSecs)}</span>
                                <span class="fw-st-dt-since">since ${_fwEsc(_fwDateTime(downStartedMs))}</span>
                               </div>` : "";

                        // ── Error/failure reason row (shown for BOTH MQTT and HTTPS) ──
                        const httpCode    = item.last_status_code;
                        const httpIsErr   = httpCode && httpCode >= 400;
                        // Build the human-readable failure reason
                        let failReason = "";
                        if (httpIsErr) {
                            failReason = `Server rejected with HTTP ${httpCode} — check endpoint URL and authentication.`;
                        } else if (item.last_error) {
                            failReason = item.last_error;
                        }
                        // Show the error row whenever there's a reason — always, not just when down
                        const errRowHtml = failReason
                            ? `<div class="fw-st-err-row">
                                <span class="fw-st-err-icon">⚠</span>
                                <div class="fw-st-err-body">
                                    <span class="fw-st-err-label">${isDown ? "Failure reason" : "Last error"}</span>
                                    <span class="fw-st-err-msg">${_fwEsc(failReason)}</span>
                                    ${lastErrMs ? `<span class="fw-st-err-time">${_fwEsc(_fwDateTime(lastErrMs))}</span>` : ""}
                                </div>
                               </div>` : "";

                        const exactTimeHtml = `
                            <div class="fw-st-time-grid">
                                <div><span>Outage started</span><strong>${_fwEsc(_fwDateTime(downStartedMs))}</strong></div>
                                <div><span>Last message</span><strong>${_fwEsc(_fwDateTime(lastMsgMs))}</strong></div>
                                <div><span>Last error</span><strong>${_fwEsc(_fwDateTime(lastErrMs))}</strong></div>
                            </div>`;

                        // Root cause for buffer explain (only when no dedicated error row covers it)
                        const causeHint = httpIsErr && !failReason ? `HTTP ${httpCode}` : "";

                        // ── Buffer section data ───────────────────────────────
                        const oldestAge = item.buffer?.oldest_pending_age_s;
                        const cooling   = item.buffer?.cooling_down ?? 0;
                        const bufHealthy = pending === 0 && dropped === 0;

                        // Buffer section visual state
                        const bufSectionCls = dropped > 0 ? "is-evicting"
                            : pending > 0 ? "is-buffering"
                            : replayed > 0 ? "is-recovered"
                            : "is-healthy";

                        // Buffer status badge
                        const bufBadge = dropped > 0
                            ? `<span class="fw-st-buf-badge is-err">⚠ ${dropped.toLocaleString()} evicted</span>`
                            : pending > 0
                            ? `<span class="fw-st-buf-badge is-warn">⬆ ${pending.toLocaleString()} waiting</span>`
                            : replayed > 0
                            ? `<span class="fw-st-buf-badge is-ok">✓ ${replayed.toLocaleString()} recovered</span>`
                            : `<span class="fw-st-buf-badge is-ok">✓ Healthy</span>`;

                        // Plain-language explanation line
                        let bufExplain = "";
                        if (pending > 0) {
                            bufExplain = `Saved locally — will send automatically when connection recovers.`;
                        } else if (replayed > 0 && pending === 0) {
                            bufExplain = `${replayed.toLocaleString()} message${replayed !== 1 ? "s" : ""} recovered and delivered from buffer this session.`;
                        } else if (dropped > 0) {
                            bufExplain = `Buffer was full — oldest messages removed to make room for new data.`;
                        }

                        return `
                        <div class="fw-status-card ${stCls}">
                            <div class="fw-st-head">
                                <span class="fw-proto-badge is-${badge.toLowerCase()}">${badge}</span>
                                <span class="fw-st-name">${_fwEsc(profileName)}</span>
                                <span class="fw-st-state">${_fwEsc(stLbl)}</span>
                            </div>
                            <div class="fw-st-dest">${_fwEsc(dest)}${tlsNote}</div>
                            ${downHtml}
                            ${errRowHtml}
                            ${exactTimeHtml}
                            <div class="fw-st-runtime-grid">
                                <div class="fw-st-runtime-stat">
                                    <strong>${count.toLocaleString()}</strong>
                                    <span>${isMqtt ? "Published" : "Sent"}</span>
                                </div>
                                <div class="fw-st-runtime-stat">
                                    <strong>${rateStr}</strong>
                                    <span>Avg rate</span>
                                </div>
                                <div class="fw-st-runtime-stat">
                                    <strong>${isDown ? "—" : sessionStr}</strong>
                                    <span>${isDown ? "Not connected" : "Up for"}</span>
                                </div>
                                <div class="fw-st-runtime-stat">
                                    <strong>${lastStr}</strong>
                                    <span>Last message${httpInfo}${restarts}</span>
                                </div>
                            </div>
                            <div class="fw-st-buf-section ${bufSectionCls}">
                                <div class="fw-st-buf-header">
                                    <span class="fw-st-buf-title">Message Buffer</span>
                                    ${bufBadge}
                                </div>
                                <div class="fw-st-buf-stat-grid">
                                    <div class="fw-st-buf-stat">
                                        <strong>${pending.toLocaleString()}</strong>
                                        <span>Waiting to send</span>
                                    </div>
                                    <div class="fw-st-buf-stat">
                                        <strong>${oldestAge != null ? _fwAgo(oldestAge) : "—"}</strong>
                                        <span>${item.buffer?.oldest_pending_ms ? _fwDateTime(item.buffer.oldest_pending_ms) : "Oldest message"}</span>
                                    </div>
                                    <div class="fw-st-buf-stat">
                                        <strong>${cooling > 0 ? cooling.toLocaleString() : "—"}</strong>
                                        <span>In retry backoff</span>
                                    </div>
                                    <div class="fw-st-buf-stat">
                                        <strong>${replayed > 0 ? replayed.toLocaleString() : "—"}</strong>
                                        <span>Recovered</span>
                                    </div>
                                </div>
                                ${bufExplain ? `<p class="fw-st-buf-explain">${bufExplain}</p>` : ""}
                            </div>
                        </div>`;
                    }).join("");
                }
            } catch (e) {
                console.warn("[Forwarding] status fetch failed:", e);
            }
        };

        // ── Buffer stats panel ────────────────────────────────────────────────
        const fwBufPanel    = fwShell.querySelector("[data-fw-buffer-panel]");
        const fwBufPending  = fwShell.querySelector("[data-fw-buf-pending]");
        const fwBufReplayed = fwShell.querySelector("[data-fw-buf-replayed]");
        const fwBufDropped  = fwShell.querySelector("[data-fw-buf-dropped]");
        const fwBufRate     = fwShell.querySelector("[data-fw-buf-rate]");

        const _fwSparkline = (history, width = 120, height = 32) => {
            if (!history || history.length < 2) return "";
            const max = Math.max(...history, 1);
            const pts = history.map((v, i) => {
                const x = Math.round((i / (history.length - 1)) * width);
                const y = Math.round(height - (v / max) * (height - 2) - 1);
                return `${x},${y}`;
            }).join(" ");
            return `<svg width="${width}" height="${height}" class="fw-sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
                <polyline points="${pts}" fill="none" stroke="rgba(57,208,200,0.7)" stroke-width="1.5" stroke-linejoin="round"/>
            </svg>`;
        };

        // Name/protocol lookup built directly from config — most reliable source
        let fwConfigNameMap = {};   // profile_id → {name, protocol}

        const _buildConfigNameMap = async () => {
            try {
                const cr = await fetch("/api/forwarding/config");
                if (!cr.ok) return;
                const cd = await cr.json();
                fwConfigNameMap = {};
                for (const p of (cd.profiles || [])) {
                    if (p.id) {
                        fwConfigNameMap[p.id] = {
                            name:     p.name || "Unnamed Profile",
                            protocol: (p.protocol || "mqtt").toUpperCase(),
                        };
                    }
                }
            } catch { /* silent — fallback to fwProfileMeta */ }
        };

        const fwRefreshBuffer = async () => {
            if (!fwBufPanel) return;
            try {
                const r = await fetch("/api/forwarding/buffer-stats");
                if (!r.ok) return;
                const d = await r.json();
                if (!d.ok) return;

                fwBufPanel.classList.remove("ov-hidden");

                const totalPending  = d.total_pending  ?? 0;
                const totalReplayed = d.total_replayed ?? 0;
                const totalDropped  = d.total_dropped  ?? 0;
                const successRate   = d.success_rate   ?? 100;
                const allHealthy    = totalPending === 0 && totalDropped === 0;
                // "Delivery rate" = recovered / (recovered + evicted).
                // Only meaningful once some messages have left the buffer.
                // Show "—" when there's no history yet to avoid misleading 100%.
                const hasRateHistory = (totalReplayed + totalDropped) > 0;

                // Storage info in header
                const storageInfoEl = fwBufPanel.querySelector("[data-fw-storage-info]");
                if (storageInfoEl && d.storage) {
                    const s = d.storage;
                    const usedMb = s.db_size_mb ?? 0;
                    const capMb  = s.estimated_capacity_mb ?? 0;
                    const maxMsg = (s.max_per_profile ?? 0).toLocaleString();
                    storageInfoEl.textContent = usedMb > 0
                        ? `SQLite on disk · ${usedMb} MB used · capacity: ~${capMb} MB (${maxMsg} msgs/profile) · survives restarts`
                        : `SQLite on disk · capacity: ~${capMb} MB per profile (${maxMsg} msgs) · survives restarts`;
                }

                if (fwBufPending)  fwBufPending.textContent  = totalPending.toLocaleString();
                if (fwBufReplayed) fwBufReplayed.textContent = totalReplayed.toLocaleString();
                if (fwBufDropped)  fwBufDropped.textContent  = totalDropped.toLocaleString();
                if (fwBufRate) {
                    if (!hasRateHistory) {
                        fwBufRate.textContent = "—";
                        fwBufRate.style.color = "var(--muted)";
                    } else {
                        fwBufRate.textContent = `${successRate}%`;
                        fwBufRate.style.color = successRate >= 100 ? "var(--success)" : successRate < 90 ? "#f87171" : "var(--accent)";
                    }
                }
            } catch (e) {
                console.warn("[Forwarding] buffer stats fetch failed:", e);
            }
        };

        // ── Durable outage/error audit panel ─────────────────────────────────
        const fwAuditPanel = fwShell.querySelector("[data-fw-audit-panel]");
        const fwAuditList = fwShell.querySelector("[data-fw-audit-list]");
        const fwAuditEmpty = fwShell.querySelector("[data-fw-audit-empty]");
        const fwAuditWindow = fwShell.querySelector("[data-fw-audit-window]");

        const fwRefreshAudit = async () => {
            if (!fwAuditPanel || !fwAuditList) return;
            _fwRefreshAuditExport();
            try {
                const r = await fetch(_fwBuildAuditUrl(false));
                if (!r.ok) return;
                const d = await r.json();
                if (!d.ok) return;
                const events = d.events || [];

                const outageStarts = events.filter((e) => e.event_type === "outage_started").length;
                const recovered = events.filter((e) => e.event_type === "outage_recovered").length;
                const errors = events.filter((e) => e.severity === "error" || e.severity === "critical").length;
                const longestMs = events.reduce((max, e) => Math.max(max, e.duration_ms || 0), 0);

                const setText = (attr, value) => {
                    const el = fwShell.querySelector(`[${attr}]`);
                    if (el) el.textContent = value;
                };
                setText("data-fw-audit-outages", outageStarts.toLocaleString());
                setText("data-fw-audit-recovered", recovered.toLocaleString());
                setText("data-fw-audit-errors", errors.toLocaleString());
                setText("data-fw-audit-longest", longestMs ? _fwDurMs(longestMs) : "—");

                fwAuditEmpty?.classList.toggle("ov-hidden", events.length > 0);
                if (!events.length) {
                    fwAuditList.innerHTML = "";
                    return;
                }

                fwAuditList.innerHTML = events.slice(0, 80).map((event) => {
                    const cls = _fwSeverityClass(event.severity);
                    const profile = event.profile_name || event.profile_id || "Unknown profile";
                    const reason = _fwEventReason(event);
                    const duration = event.duration_ms != null ? _fwDurMs(event.duration_ms) : "";
                    const recoveryLine = event.event_type === "outage_recovered"
                        ? `<div class="fw-audit-duration">Outage: ${_fwEsc(_fwDateTime(event.started_at_ms))} → ${_fwEsc(_fwDateTime(event.ended_at_ms))} · ${_fwEsc(duration)}</div>`
                        : event.started_at_ms
                        ? `<div class="fw-audit-duration">Started: ${_fwEsc(_fwDateTime(event.started_at_ms))}</div>`
                        : "";
                    const http = event.http_status ? `HTTP ${event.http_status}` : "";
                    const pending = event.pending_count != null ? `${event.pending_count} pending` : "";
                    const metaBits = [event.protocol?.toUpperCase(), event.destination, http, pending].filter(Boolean);
                    return `
                        <div class="fw-audit-row ${cls}">
                            <div class="fw-audit-time">
                                <strong>${_fwEsc(_fwDateTime(event.timestamp_ms))}</strong>
                                <span>${_fwEsc(event.timestamp_utc || "")}</span>
                            </div>
                            <div class="fw-audit-main">
                                <div class="fw-audit-head">
                                    <span class="fw-audit-type">${_fwEsc(_fwEventLabel(event.event_type))}</span>
                                    <span class="fw-audit-profile">${_fwEsc(profile)}</span>
                                    <span class="fw-audit-sev">${_fwEsc(event.severity || "info")}</span>
                                </div>
                                <p class="fw-audit-reason">${_fwEsc(reason)}</p>
                                ${recoveryLine}
                                <div class="fw-audit-meta">${_fwEsc(metaBits.join(" · "))}</div>
                            </div>
                        </div>`;
                }).join("");
            } catch (e) {
                console.warn("[Forwarding] audit fetch failed:", e);
            }
        };

        fwAuditWindow?.addEventListener("change", () => {
            _fwRefreshAuditExport();
            fwRefreshAudit();
        });

        // ── Tab switching ────────────────────────────────────────────────────
        const fwTabBtns  = Array.from(fwShell.querySelectorAll("[data-fw-tab]"));
        const fwPanels   = Array.from(fwShell.querySelectorAll("[data-fw-panel]"));

        const syncFwTabs = (tabId) => {
            fwTabBtns.forEach((btn) => {
                const isCurrent = btn.getAttribute("data-fw-tab") === tabId;
                btn.classList.toggle("is-current", isCurrent);
                btn.setAttribute("aria-selected", isCurrent ? "true" : "false");
            });
            fwPanels.forEach((panel) => {
                panel.classList.toggle("is-hidden", panel.getAttribute("data-fw-panel") !== tabId);
            });
        };

        fwTabBtns.forEach((btn) => btn.addEventListener("click", () => syncFwTabs(btn.getAttribute("data-fw-tab"))));
        syncFwTabs("status");

        // Switch to profiles tab when form opens for a new profile
        fwShell.querySelectorAll("[data-fw-add]").forEach((btn) => {
            btn.addEventListener("click", () => syncFwTabs("profiles"), true);
        });

        // Inline "Profiles tab" link inside no-profiles hint
        fwShell.querySelectorAll("[data-fw-tab-goto]").forEach((btn) => {
            btn.addEventListener("click", () => syncFwTabs(btn.getAttribute("data-fw-tab-goto")));
        });

        fwLoad();
        _buildConfigNameMap().then(() => {
            fwRefreshStatus();
            fwRefreshBuffer();
            fwRefreshAudit();
        });
        window.setInterval(fwRefreshStatus, 6000);
        window.setInterval(fwRefreshBuffer, 8000);
        window.setInterval(fwRefreshAudit, 15000);
    }


    const edgeShell = document.querySelector("[data-edge-server-shell]");
    if (edgeShell) {
        let esConfig = null;
        let esForwardingProfiles = [];
        let esEditingHttpId = null;
        let esEditingMqttId = null;
        let esHttpMetricsCache = null;
        let esMqttMetricsCache = null;
        let esOverviewMetricsCache = null;
        let esAlertEventsCache = [];
        let esSelectedAlertIndex = -1;
        let esHttpDeviceSearch = "";
        let esMqttDeviceSearch = "";

        const esDefaultConfig = () => ({
            version: 1,
            listeners: {
                bind_mode: "interfaces",
                bind_interfaces: ["eth0", "eth1", "wlan0", "wwan0", "tailscale0"],
                http: { enabled: false, port: 8080 },
                https: { enabled: false, port: 8443, tls_mode: "server", mtls_required: false },
                mqtt: { enabled: false, port: 1883, allow_anonymous: false },
                mqtts: { enabled: false, port: 8883, tls_mode: "server", mtls_required: false },
            },
            http_endpoints: [],
            mqtt_topics: [],
            funnel: { enabled: false, http: true, https: false, mqtt: false, mqtts: false },
            storage: { enabled: true, retention_days: 30, max_size_mb: 5120 },
            tls: { managed: true, installed: { server_cert: false, server_key: false, client_ca: false } },
        });

        const esEsc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        }[ch]));

        const esId = () => `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 8)}`;

        const esSetToggle = (btn, enabled) => {
            if (!btn) return;
            btn.textContent = enabled ? "ON" : "OFF";
            btn.classList.toggle("is-on", Boolean(enabled));
            btn.classList.toggle("is-active", Boolean(enabled));
        };

        const esFillForwardingSelect = (select, selected) => {
            if (!select) return;
            const storeOnlyLabel = esForwardingProfiles.length
                ? "Store + anomaly detection only"
                : "Store + anomaly detection only (no forwarding profile configured)";
            const options = [
                `<option value="store_only">${storeOnlyLabel}</option>`,
                ...esForwardingProfiles.map((profile) =>
                    `<option value="${esEsc(profile.id)}">Store + anomaly + forward to ${esEsc(profile.name || profile.id)}</option>`
                ),
            ];
            select.innerHTML = options.join("");
            select.value = selected || "store_only";
        };

        const esGetForwardingLabel = (id) => {
            if (!id || id === "store_only") {
                return esForwardingProfiles.length
                    ? "Store + anomaly detection only"
                    : "Store + anomaly detection only (no forwarding profile configured)";
            }
            const profile = esForwardingProfiles.find((item) => String(item.id) === String(id));
            return profile ? `Store + anomaly + forward to ${profile.name || profile.id}` : id;
        };

        const esApplyCertStatus = () => {
            const installed = esConfig?.tls?.installed || {};
            const labels = {
                server_cert: "Server certificate",
                server_key: "Server private key",
                client_ca: "Client CA",
            };
            Object.entries(labels).forEach(([key, label]) => {
                const el = edgeShell.querySelector(`[data-es-cert-status="${key}"]`);
                if (!el) return;
                el.textContent = installed[key] ? `${label} installed` : `${label} missing`;
                el.classList.toggle("is-installed", Boolean(installed[key]));
            });
        };

        const esApplyListeners = () => {
            const cfg = esConfig || esDefaultConfig();
            const listeners = cfg.listeners || {};
            const selectedIfaces = Array.isArray(listeners.bind_interfaces)
                ? listeners.bind_interfaces
                : esDefaultConfig().listeners.bind_interfaces;
            edgeShell.querySelectorAll("[data-es-bind-interface]").forEach((input) => {
                input.checked = selectedIfaces.includes(input.value);
            });

            ["http", "https", "mqtt", "mqtts"].forEach((key) => {
                const item = listeners[key] || {};
                const port = edgeShell.querySelector(`[data-es-port="${key}"]`);
                if (port) port.value = item.port || ({ http: 8080, https: 8443, mqtt: 1883, mqtts: 8883 }[key]);
                esSetToggle(edgeShell.querySelector(`[data-es-listener-enabled="${key}"]`), item.enabled);
            });

            const httpsMtls = edgeShell.querySelector('[data-es-mtls="https"]');
            const mqttsMtls = edgeShell.querySelector('[data-es-mtls="mqtts"]');
            const anonymous = edgeShell.querySelector("[data-es-anonymous]");
            if (httpsMtls) httpsMtls.checked = Boolean(listeners.https?.mtls_required);
            if (mqttsMtls) mqttsMtls.checked = Boolean(listeners.mqtts?.mtls_required);
            if (anonymous) anonymous.checked = Boolean(listeners.mqtt?.allow_anonymous);

            cfg.tls = cfg.tls || esDefaultConfig().tls;
        };

        const esReadListeners = () => {
            const cfg = esConfig || esDefaultConfig();
            cfg.listeners = cfg.listeners || {};
            cfg.listeners.bind_mode = "interfaces";
            cfg.listeners.bind_interfaces = Array.from(edgeShell.querySelectorAll("[data-es-bind-interface]"))
                .filter((input) => input.checked)
                .map((input) => input.value);
            ["http", "https", "mqtt", "mqtts"].forEach((key) => {
                cfg.listeners[key] = cfg.listeners[key] || {};
                cfg.listeners[key].port = Number(edgeShell.querySelector(`[data-es-port="${key}"]`)?.value || cfg.listeners[key].port || 1);
            });
            cfg.listeners.https.mtls_required = Boolean(edgeShell.querySelector('[data-es-mtls="https"]')?.checked);
            cfg.listeners.mqtt.allow_anonymous = Boolean(edgeShell.querySelector("[data-es-anonymous]")?.checked);
            cfg.listeners.mqtts.mtls_required = Boolean(edgeShell.querySelector('[data-es-mtls="mqtts"]')?.checked);
            cfg.tls = cfg.tls || esDefaultConfig().tls;
        };

        const esApplyStorage = () => {
            const storage = (esConfig || esDefaultConfig()).storage || {};
            const enabled = edgeShell.querySelector("[data-es-storage-enabled]");
            const retention = edgeShell.querySelector("[data-es-retention-days]");
            const maxSize = edgeShell.querySelector("[data-es-max-size]");
            const configuredMax = Math.max(5120, Number(storage.max_size_mb || 5120));
            if (enabled) enabled.checked = storage.enabled !== false;
            if (retention) retention.value = storage.retention_days || 30;
            if (maxSize) maxSize.value = configuredMax;
        };

        const esReadStorage = () => {
            const cfg = esConfig || esDefaultConfig();
            cfg.storage = {
                enabled: Boolean(edgeShell.querySelector("[data-es-storage-enabled]")?.checked),
                retention_days: Number(edgeShell.querySelector("[data-es-retention-days]")?.value || 30),
                max_size_mb: Math.max(5120, Number(edgeShell.querySelector("[data-es-max-size]")?.value || 5120)),
            };
        };

        const esApplyFunnelConfig = () => {
            const funnel = (esConfig || esDefaultConfig()).funnel || esDefaultConfig().funnel;
            esSetToggle(edgeShell.querySelector("[data-es-funnel-enabled]"), Boolean(funnel.enabled));
            edgeShell.querySelectorAll("[data-es-funnel-service]").forEach((input) => {
                const key = input.getAttribute("data-es-funnel-service");
                input.checked = Boolean(funnel[key]);
            });
        };

        const esReadFunnelConfig = () => {
            const cfg = esConfig || esDefaultConfig();
            cfg.funnel = cfg.funnel || esDefaultConfig().funnel;
            cfg.funnel.enabled = edgeShell.querySelector("[data-es-funnel-enabled]")?.classList.contains("is-on") || false;
            edgeShell.querySelectorAll("[data-es-funnel-service]").forEach((input) => {
                const key = input.getAttribute("data-es-funnel-service");
                if (key) cfg.funnel[key] = Boolean(input.checked);
            });
            return cfg.funnel;
        };

        const esRenderFunnelStatus = (data) => {
            const config = data.config || {};
            esConfig = esConfig || esDefaultConfig();
            esConfig.funnel = { ...esDefaultConfig().funnel, ...config };
            esApplyFunnelConfig();
            esSetText("[data-es-funnel-host]", data.hostname || "Not available");
            esSetText("[data-es-funnel-state]", data.enabled ? "On" : "Off");
            esSetText("[data-es-funnel-state-detail]", data.enabled ? "public access requested" : "public access disabled");
            const services = data.services || [];
            const http = services.find((item) => item.service === "http");
            const mqtt = services.find((item) => item.service === "mqtt" || item.service === "mqtts");
            esSetText("[data-es-funnel-http-url]", http?.public_url || "Unavailable");
            esSetText("[data-es-funnel-mqtt-url]", mqtt?.public_url || "Unavailable");
            edgeShell.querySelector("[data-es-funnel-host]")?.setAttribute("title", data.hostname || "Not available");
            edgeShell.querySelector("[data-es-funnel-http-url]")?.setAttribute("title", http?.public_url || "Unavailable");
            edgeShell.querySelector("[data-es-funnel-mqtt-url]")?.setAttribute("title", mqtt?.public_url || "Unavailable");

            const list = edgeShell.querySelector("[data-es-funnel-services]");
            const empty = edgeShell.querySelector("[data-es-funnel-empty]");
            if (empty) empty.classList.toggle("es-hidden", services.length > 0);
            if (!list) return;
            list.innerHTML = services.map((item) => {
                const state = item.enabled ? "Public" : item.available ? "Ready" : "Unavailable";
                const address = item.public_url || "No public address";
                const note = item.reason || `Local target: ${item.target || "not configured"}`;
                const protocol = item.service === "http"
                    ? "HTTPS URL"
                    : item.service === "https"
                        ? "HTTPS TCP"
                        : item.service === "mqtts"
                            ? "MQTTS TCP"
                            : "MQTT TCP";
                return `
                    <article class="es-item-card es-funnel-published-service">
                        <div class="es-item-main">
                            <div class="es-item-title">
                                <strong>${esEsc(item.label || item.service)}</strong>
                                <span class="es-proto-tag ${item.enabled ? "is-secure" : ""}">${esEsc(state)}</span>
                            </div>
                            <code>${esEsc(address)}</code>
                            <p>${esEsc(protocol)} · public port ${esEsc(item.public_port || "n/a")}</p>
                            <small>${esEsc(note)}</small>
                        </div>
                    </article>
                `;
            }).join("");
        };

        const esRefreshFunnel = async () => {
            try {
                const response = await fetch("/api/edge-server/funnel");
                const data = await response.json();
                if (!response.ok || data.ok === false) throw new Error("Funnel status failed");
                esRenderFunnelStatus(data);
            } catch (error) {
                console.warn("[Edge Server] funnel status failed:", error);
            }
        };

        const esSaveFunnel = async () => {
            const msg = edgeShell.querySelector("[data-es-funnel-msg]");
            const payload = esReadFunnelConfig();
            if (msg) msg.textContent = "Applying...";
            try {
                const response = await fetch("/api/edge-server/funnel", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || data.ok === false) throw new Error("Public tunnel update failed");
                esRenderFunnelStatus(data);
                if (msg) msg.textContent = data.message || "Updated";
            } catch (error) {
                if (msg) msg.textContent = "Public tunnel update failed";
                console.warn("[Edge Server] funnel save failed:", error);
            }
        };

        const esHttpForm = edgeShell.querySelector("[data-es-http-form]");
        const esMqttForm = edgeShell.querySelector("[data-es-mqtt-form]");

        const esShowHttpForm = (endpoint = null) => {
            esEditingHttpId = endpoint?.id || null;
            esHttpForm?.classList.remove("es-hidden");
            edgeShell.querySelector("[data-es-http-name]").value = endpoint?.name || "";
            edgeShell.querySelector("[data-es-http-protocol]").value = endpoint?.protocol || "http";
            edgeShell.querySelector("[data-es-http-method]").value = endpoint?.method || "POST";
            edgeShell.querySelector("[data-es-http-path]").value = endpoint?.path || "/ingest";
            edgeShell.querySelector("[data-es-http-auth]").value = endpoint?.auth || "token";
            edgeShell.querySelector("[data-es-http-payload]").value = endpoint?.payload_type || "json";
            edgeShell.querySelector("[data-es-http-device-source]").value = endpoint?.device_id_source || "payload";
            edgeShell.querySelector("[data-es-http-device-key]").value = endpoint?.device_id_key || "device_id";
            esFillForwardingSelect(edgeShell.querySelector("[data-es-http-forwarding]"), endpoint?.forwarding_profile);
        };

        const esHideHttpForm = () => {
            esEditingHttpId = null;
            esHttpForm?.classList.add("es-hidden");
        };

        const esShowMqttForm = (topic = null) => {
            esEditingMqttId = topic?.id || null;
            esMqttForm?.classList.remove("es-hidden");
            edgeShell.querySelector("[data-es-mqtt-name]").value = topic?.name || "";
            edgeShell.querySelector("[data-es-mqtt-protocol]").value = topic?.protocol || "mqtt";
            edgeShell.querySelector("[data-es-mqtt-topic]").value = topic?.topic_filter || "devices/+/data";
            edgeShell.querySelector("[data-es-mqtt-qos]").value = String(topic?.qos ?? 0);
            edgeShell.querySelector("[data-es-mqtt-payload]").value = topic?.payload_type || "json";
            edgeShell.querySelector("[data-es-mqtt-device-source]").value = topic?.device_id_source || "topic_segment";
            edgeShell.querySelector("[data-es-mqtt-device-key]").value = topic?.device_id_key || "1";
            esFillForwardingSelect(edgeShell.querySelector("[data-es-mqtt-forwarding]"), topic?.forwarding_profile);
        };

        const esHideMqttForm = () => {
            esEditingMqttId = null;
            esMqttForm?.classList.add("es-hidden");
        };

        const esRenderHttp = () => {
            const list = edgeShell.querySelector("[data-es-http-list]");
            const empty = edgeShell.querySelector("[data-es-http-empty]");
            const items = esConfig?.http_endpoints || [];
            if (empty) empty.classList.toggle("ov-hidden", items.length > 0);
            if (!list) return;
            list.innerHTML = items.map((item) => `
                <article class="es-item-card">
                    <div class="es-item-main">
                        <div class="es-item-title">
                            <strong>${esEsc(item.name)}</strong>
                            <span>${item.enabled ? "Enabled" : "Disabled"}</span>
                        </div>
                        <code>${esEsc(item.method || "POST")} ${esEsc(item.path)}</code>
                        <p>${esEsc((item.protocol || "http").toUpperCase())} · ${esEsc(item.auth || "none")} auth · ${esEsc(item.payload_type || "json")} · device: ${esEsc(item.device_id_source)}:${esEsc(item.device_id_key)}</p>
                        <small>Pipeline: ${esEsc(esGetForwardingLabel(item.forwarding_profile))}</small>
                    </div>
                    <div class="es-item-actions">
                        <button type="button" class="ghost-action" data-es-toggle-http="${esEsc(item.id)}">${item.enabled ? "Disable" : "Enable"}</button>
                        <button type="button" class="ghost-action" data-es-edit-http="${esEsc(item.id)}">Edit</button>
                        <button type="button" class="ghost-action" data-es-delete-http="${esEsc(item.id)}">Delete</button>
                    </div>
                </article>
            `).join("");
        };

        const esRenderMqtt = () => {
            const list = edgeShell.querySelector("[data-es-mqtt-list]");
            const empty = edgeShell.querySelector("[data-es-mqtt-empty]");
            const items = esConfig?.mqtt_topics || [];
            if (empty) empty.classList.toggle("ov-hidden", items.length > 0);
            if (!list) return;
            list.innerHTML = items.map((item) => `
                <article class="es-item-card">
                    <div class="es-item-main">
                        <div class="es-item-title">
                            <strong>${esEsc(item.name)}</strong>
                            <span>${item.enabled ? "Enabled" : "Disabled"}</span>
                        </div>
                        <code>${esEsc(item.topic_filter)}</code>
                        <p>${esEsc((item.protocol || "mqtt").toUpperCase())} · QoS ${esEsc(item.qos ?? 0)} · ${esEsc(item.payload_type || "json")} · device: ${esEsc(item.device_id_source)}:${esEsc(item.device_id_key)}</p>
                        <small>Pipeline: ${esEsc(esGetForwardingLabel(item.forwarding_profile))}</small>
                    </div>
                    <div class="es-item-actions">
                        <button type="button" class="ghost-action" data-es-toggle-mqtt="${esEsc(item.id)}">${item.enabled ? "Disable" : "Enable"}</button>
                        <button type="button" class="ghost-action" data-es-edit-mqtt="${esEsc(item.id)}">Edit</button>
                        <button type="button" class="ghost-action" data-es-delete-mqtt="${esEsc(item.id)}">Delete</button>
                    </div>
                </article>
            `).join("");
        };

        const esRenderAll = () => {
            try {
                esApplyListeners();
                esApplyStorage();
                esApplyCertStatus();
                esApplyFunnelConfig();
                esFillForwardingSelect(edgeShell.querySelector("[data-es-http-forwarding]"));
                esFillForwardingSelect(edgeShell.querySelector("[data-es-mqtt-forwarding]"));
                esRenderHttp();
                esRenderMqtt();
                esRefreshOverviewVisuals();
            } catch (error) {
                console.warn("[Edge Server] initial render failed:", error);
            }
        };

        const esReadHttpForm = () => ({
            id: esEditingHttpId || esId(),
            enabled: true,
            name: edgeShell.querySelector("[data-es-http-name]")?.value || "HTTP Endpoint",
            protocol: edgeShell.querySelector("[data-es-http-protocol]")?.value || "http",
            method: edgeShell.querySelector("[data-es-http-method]")?.value || "POST",
            path: edgeShell.querySelector("[data-es-http-path]")?.value || "/ingest",
            auth: edgeShell.querySelector("[data-es-http-auth]")?.value || "token",
            payload_type: edgeShell.querySelector("[data-es-http-payload]")?.value || "json",
            device_id_source: edgeShell.querySelector("[data-es-http-device-source]")?.value || "payload",
            device_id_key: edgeShell.querySelector("[data-es-http-device-key]")?.value || "device_id",
            forwarding_profile: edgeShell.querySelector("[data-es-http-forwarding]")?.value || "store_only",
        });

        const esReadMqttForm = () => ({
            id: esEditingMqttId || esId(),
            enabled: true,
            name: edgeShell.querySelector("[data-es-mqtt-name]")?.value || "MQTT Topic",
            protocol: edgeShell.querySelector("[data-es-mqtt-protocol]")?.value || "mqtt",
            topic_filter: edgeShell.querySelector("[data-es-mqtt-topic]")?.value || "devices/+/data",
            qos: Number(edgeShell.querySelector("[data-es-mqtt-qos]")?.value || 0),
            payload_type: edgeShell.querySelector("[data-es-mqtt-payload]")?.value || "json",
            device_id_source: edgeShell.querySelector("[data-es-mqtt-device-source]")?.value || "topic_segment",
            device_id_key: edgeShell.querySelector("[data-es-mqtt-device-key]")?.value || "1",
            forwarding_profile: edgeShell.querySelector("[data-es-mqtt-forwarding]")?.value || "store_only",
        });

        const esSaveConfig = async () => {
            if (!esConfig) return false;
            esReadListeners();
            esReadStorage();
            const msg = edgeShell.querySelector("[data-es-save-msg]");
            if (msg) msg.textContent = "Saving...";
            try {
                const response = await fetch("/api/edge-server/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(esConfig),
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || result.ok === false) throw new Error("Save failed");
                if (msg) msg.textContent = result.message || "Saved";
                await esRefreshStatus();
                return true;
            } catch (error) {
                if (msg) msg.textContent = "Save failed";
                console.warn("[Edge Server] save failed:", error);
                return false;
            }
        };

        const esSaveCertificates = async () => {
            const msg = edgeShell.querySelector("[data-es-cert-msg]");
            const payload = {};
            edgeShell.querySelectorAll("[data-es-cert-input]").forEach((input) => {
                const key = input.getAttribute("data-es-cert-input");
                const value = input.value.trim();
                if (key && value) payload[key] = value;
            });
            if (!Object.keys(payload).length) {
                if (msg) msg.textContent = "Nothing to save";
                return;
            }
            if (msg) msg.textContent = "Saving...";
            try {
                const response = await fetch("/api/edge-server/tls", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const result = await response.json();
                if (!response.ok || !result.ok) throw new Error("Certificate save failed");
                esConfig.tls = esConfig.tls || {};
                esConfig.tls.installed = result.installed || {};
                edgeShell.querySelectorAll("[data-es-cert-input]").forEach((input) => { input.value = ""; });
                esApplyCertStatus();
                if (msg) msg.textContent = "Saved";
                await esRefreshStatus();
            } catch (error) {
                if (msg) msg.textContent = "Certificate save failed";
                console.warn("[Edge Server] certificate save failed:", error);
            }
        };

        edgeShell.querySelectorAll("[data-es-cert-file]").forEach((fileInput) => {
            fileInput.addEventListener("change", async () => {
                const key = fileInput.getAttribute("data-es-cert-file");
                const file = fileInput.files?.[0];
                const target = key ? edgeShell.querySelector(`[data-es-cert-input="${key}"]`) : null;
                if (!file || !target) return;
                target.value = await file.text();
            });
        });

        const esLoad = async () => {
            try {
                const response = await fetch("/api/edge-server/config");
                const payload = await response.json();
                esForwardingProfiles = payload.forwarding_profiles || [];
                delete payload.ok;
                delete payload.forwarding_profiles;
                esConfig = payload;
            } catch (error) {
                console.warn("[Edge Server] config fetch failed:", error);
                esConfig = esDefaultConfig();
            }
            esRenderAll();
        };

        const esSetText = (selector, value) => {
            const el = edgeShell.querySelector(selector);
            if (el) el.textContent = value;
        };

        const esTooltip = document.createElement("div");
        esTooltip.className = "es-chart-tooltip es-hidden";
        document.body.appendChild(esTooltip);
        let esTooltipPinned = false;

        const esMoveTooltip = (event) => {
            const offset = 14;
            const x = Math.min(window.innerWidth - 280, event.clientX + offset);
            const y = Math.min(window.innerHeight - 90, event.clientY + offset);
            esTooltip.style.left = `${Math.max(8, x)}px`;
            esTooltip.style.top = `${Math.max(8, y)}px`;
        };

        edgeShell.addEventListener("pointerover", (event) => {
            const target = event.target?.closest?.("[data-es-tooltip]");
            if (esTooltipPinned) return;
            if (!target) return;
            esTooltip.textContent = target.getAttribute("data-es-tooltip") || "";
            esTooltip.classList.remove("es-hidden");
            esMoveTooltip(event);
        });

        edgeShell.addEventListener("pointermove", (event) => {
            if (!esTooltipPinned && !esTooltip.classList.contains("es-hidden")) esMoveTooltip(event);
        });

        edgeShell.addEventListener("pointerout", (event) => {
            if (!esTooltipPinned && event.target?.closest?.("[data-es-tooltip]")) {
                esTooltip.classList.add("es-hidden");
            }
        });

        edgeShell.addEventListener("click", (event) => {
            const target = event.target?.closest?.("[data-es-tooltip]");
            if (!target) {
                esTooltipPinned = false;
                esTooltip.classList.add("es-hidden");
                return;
            }
            esTooltipPinned = true;
            esTooltip.textContent = target.getAttribute("data-es-tooltip") || "";
            esTooltip.classList.remove("es-hidden");
            esMoveTooltip(event);
        });

        const esShortTime = (value) => {
            if (!value) return "";
            const date = new Date(String(value).replace("Z", "+00:00"));
            return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString();
        };

        const esFullTime = (value) => {
            if (!value) return "";
            const date = typeof value === "number" ? new Date(value) : new Date(String(value).replace("Z", "+00:00"));
            if (Number.isNaN(date.getTime())) return String(value);
            return date.toLocaleString([], {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
            });
        };

        const esBucketTime = (value) => {
            const raw = String(value || "");
            if (!raw) return "";
            const date = new Date(raw.length === 16 ? `${raw}:00` : raw.replace("Z", "+00:00"));
            if (!Number.isNaN(date.getTime())) {
                return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
            }
            return raw.slice(11, 16) || raw;
        };

        const esChartTickLabel = (value, mode = "time") => {
            const date = new Date(value);
            if (Number.isNaN(date.getTime())) return "";
            if (mode === "date") {
                return date.toLocaleDateString([], { month: "short", day: "2-digit" });
            }
            if (mode === "datetime") {
                return date.toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
            }
            return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        };

        const esAge = (value) => {
            if (!value) return "not seen";
            const date = new Date(String(value).replace("Z", "+00:00"));
            if (Number.isNaN(date.getTime())) return String(value);
            const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
            if (seconds < 60) return `${seconds}s ago`;
            if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
            if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
            return `${Math.floor(seconds / 86400)}d ago`;
        };

        const esFormatMs = (value) => {
            const num = Number(value);
            if (!Number.isFinite(num)) return "n/a";
            if (num < 1000) return `${Math.round(num)} ms`;
            if (num < 60000) return `${(num / 1000).toFixed(num < 10000 ? 1 : 0)} s`;
            return `${(num / 60000).toFixed(num < 600000 ? 1 : 0)} min`;
        };

        const esFormatBytes = (value) => {
            const num = Number(value);
            if (!Number.isFinite(num)) return "n/a";
            if (num < 1024) return `${Math.round(num)} B`;
            return `${(num / 1024).toFixed(num < 10240 ? 1 : 0)} KiB`;
        };

        const esFormatStoreBytes = (value) => {
            const num = Number(value);
            if (!Number.isFinite(num) || num <= 0) return "0 MiB";
            const mib = num / (1024 * 1024);
            if (mib < 1024) return `${mib < 10 ? mib.toFixed(1) : Math.round(mib).toLocaleString()} MiB`;
            const gib = mib / 1024;
            return `${gib < 10 ? gib.toFixed(2) : gib.toFixed(1)} GiB`;
        };

        const esEventTitle = (type) => ({
            new_device: "New device",
            no_data_timeout: "No data timeout",
            device_recovered: "Device recovered",
            message_gap: "Message gap",
            rate_slowdown: "Rate slowdown",
            rate_spike: "Rate spike",
            payload_parse_error: "Payload parse error",
            payload_size_change: "Payload size change",
            payload_schema_change: "Payload fields changed",
            sequence_gap: "Sequence gap",
            sequence_duplicate: "Duplicate sequence",
            sequence_out_of_order: "Sequence out of order",
            sequence_reset: "Sequence reset",
            device_clock_drift: "Clock drift",
            device_timestamp_stale: "Stale device timestamp",
            mqtt_disconnected: "MQTT disconnect",
            mqtt_reconnect_storm: "MQTT reconnect storm",
            auth_failure: "Authentication failure",
            route_missing: "Unknown route/topic",
        }[type] || String(type || "Event").replaceAll("_", " "));

        const esEventMeaning = (type) => ({
            new_device: "gateway saw this device for the first time",
            no_data_timeout: "device stopped sending within its expected window",
            device_recovered: "device started sending again after silence/disconnect",
            message_gap: "current gap is much larger than learned normal gap",
            rate_slowdown: "device is publishing slower than its own baseline",
            rate_spike: "device is publishing faster than its own baseline",
            payload_parse_error: "payload could not be parsed as configured",
            payload_size_change: "payload size changed more than expected",
            payload_schema_change: "JSON field set changed from the learned shape",
            sequence_gap: "sequence jumped forward, so messages may be missing",
            sequence_duplicate: "same sequence number arrived again",
            sequence_out_of_order: "sequence number moved backward",
            sequence_reset: "sequence restarted, usually after device reboot/reset",
            device_clock_drift: "device timestamp differs from gateway time",
            device_timestamp_stale: "device timestamp is older than receive time",
            mqtt_disconnected: "MQTT session closed",
            mqtt_reconnect_storm: "client connected too many times in a short window",
            auth_failure: "request/client failed authentication",
            route_missing: "device used a path or topic not configured",
        }[type] || "gateway event");

        const esEventDetails = (event) => {
            let details = event.details ?? event.details_json ?? {};
            if (typeof details === "string" && details.trim()) {
                try {
                    details = JSON.parse(details);
                } catch {
                    return details;
                }
            }
            if (!details || typeof details !== "object") return "";
            const type = event.event_type || event.type;
            if (type === "message_gap" || type === "rate_slowdown" || type === "rate_spike") {
                return `last gap ${esFormatMs(details.interval_ms)}, normal ${esFormatMs(details.avg_interval_ms)}`;
            }
            if (type === "no_data_timeout") {
                return `silent ${esFormatMs(details.silent_ms)}, timeout ${esFormatMs(details.timeout_ms)}`;
            }
            if (type === "device_recovered") {
                return `previous status ${details.previous_status || "unknown"}`;
            }
            if (type === "payload_parse_error") {
                return `${details.payload_type || "payload"} parse failed: ${details.error || "invalid payload"}`;
            }
            if (type === "payload_size_change") {
                return `last payload ${esFormatBytes(details.payload_size)}, normal ${esFormatBytes(details.avg_payload_size)}`;
            }
            if (type === "payload_schema_change") {
                return `fields now ${details.payload_schema || "unknown"}; before ${details.last_payload_schema || "unknown"}`;
            }
            if (type === "sequence_gap") {
                return `received ${details.sequence ?? "?"}, expected ${details.expected_sequence ?? "?"}; missing ${details.missing_count ?? "?"}`;
            }
            if (type === "sequence_out_of_order") {
                return `received sequence ${details.sequence ?? "?"} after ${details.last_sequence ?? "?"}`;
            }
            if (type === "sequence_reset") {
                return `sequence restarted at ${details.sequence ?? "?"} after ${details.last_sequence ?? "?"}`;
            }
            if (type === "sequence_duplicate") {
                return event.message || "same sequence arrived twice";
            }
            if (type === "device_clock_drift") {
                return `clock drift ${esFormatMs(details.drift_ms)}`;
            }
            if (type === "device_timestamp_stale") {
                return `timestamp stale by ${esFormatMs(details.stale_ms)}`;
            }
            if (type === "mqtt_disconnected") {
                return details.clean ? "clean disconnect" : "connection dropped";
            }
            if (type === "mqtt_reconnect_storm") {
                return `${details.connects_in_60s || "many"} connects in 60s`;
            }
            return event.message || "";
        };

        const esSeverityTone = (severity) => {
            const tone = String(severity || "info").toLowerCase();
            if (tone === "critical") return "critical";
            if (tone === "error") return "error";
            if (tone === "warning" || tone === "warn") return "warning";
            return "info";
        };

        const esProtocolTag = (protocol) => {
            const value = String(protocol || "").toUpperCase();
            const secure = value === "HTTPS" || value === "MQTTS";
            const plain = value === "HTTP" || value === "MQTT";
            return `<span class="es-proto-tag ${secure ? "is-secure" : plain ? "is-plain" : ""}">${esEsc(value || "DATA")}</span>`;
        };

        const esRenderAlertCard = (event, compact = false, index = null) => {
            const type = event.event_type || event.type || "event";
            const tone = esSeverityTone(event.severity);
            const detail = esEventDetails(event);
            const when = event.created_at || event.timestamp || event.last_seen;
            const device = event.device_id || event.source || "unknown device";
            const protocol = event.protocol || event.protocol_group || "";
            const interactiveAttrs = index === null ? "" : ` data-es-alert-index="${index}"`;
            const selected = index !== null && index === esSelectedAlertIndex;
            return `
                <article class="es-alert-card ${compact ? "is-compact" : ""} ${index === null ? "" : "is-clickable"} ${selected ? "is-selected" : ""} is-${tone}"${interactiveAttrs}>
                    <div class="es-alert-top">
                        <strong class="es-alert-title">${esEsc(esEventTitle(type))}</strong>
                        <span class="es-severity-pill is-${tone}">${esEsc(tone)}</span>
                    </div>
                    <div class="es-alert-meta">
                        <span class="es-alert-device">${protocol ? `${esProtocolTag(protocol)} ` : ""}${esEsc(device)}</span>
                        <em class="es-alert-time">${esEsc(esFullTime(when))}${when ? ` · ${esEsc(esAge(when))}` : ""}</em>
                    </div>
                    <div class="es-alert-body"><strong>Measured:</strong> ${esEsc(detail || event.message || esEventMeaning(type))}</div>
                    <div class="es-alert-rule">Why it matters: ${esEsc(esEventMeaning(type))}</div>
                </article>`;
        };

        const esEventMs = (event) => {
            const raw = event?.created_at || event?.timestamp || event?.last_seen || event?.received_at;
            if (!raw) return Date.now();
            const ms = new Date(String(raw).replace("Z", "+00:00")).getTime();
            return Number.isFinite(ms) ? ms : Date.now();
        };

        const esChartBucketMs = (row) => {
            const raw = String(row?.minute || row?.bucket || row?.received_at || "");
            const ms = new Date(raw.length === 16 ? `${raw}:00Z` : raw.replace("Z", "+00:00")).getTime();
            return Number.isFinite(ms) ? ms : 0;
        };

        const esRateBaseline = (rows) => {
            const values = (Array.isArray(rows) ? rows : [])
                .map((row) => Number(row.count ?? row.value ?? 0))
                .filter((value) => Number.isFinite(value) && value > 0);
            if (values.length < 3) return 0;
            return values.reduce((sum, value) => sum + value, 0) / values.length;
        };

        const esNormalizeSeries = (rows, valueKey = "count") => {
            return (Array.isArray(rows) ? rows : [])
                .map((row) => ({
                    label: row.minute || row.bucket || row.received_at || "",
                    ms: esChartBucketMs(row),
                    value: Number(row[valueKey] || 0),
                }))
                .filter((row) => row.ms || row.label)
                .sort((a, b) => a.ms - b.ms);
        };

        const esSvgPointPath = (points) => points.map((point, idx) => `${idx ? "L" : "M"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");

        const esRenderLineChart = (selector, emptySelector, seriesItems, options = {}) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            if (!wrap) return;
            try {
            const hasFixedMin = options.minMs !== undefined && options.minMs !== null && Number.isFinite(Number(options.minMs));
            const hasFixedMax = options.maxMs !== undefined && options.maxMs !== null && Number.isFinite(Number(options.maxMs));
            const fixedMinMs = hasFixedMin ? Number(options.minMs) : null;
            const fixedMaxMs = hasFixedMax ? Math.max(Number(options.maxMs), Number(options.minMs || 0) + 60000) : null;
            const chartEvents = Array.isArray(options.events) ? options.events : [];
            let series = (Array.isArray(seriesItems) ? seriesItems : [])
                .map((item) => ({
                    ...item,
                    rows: esNormalizeSeries(item.rows || [], item.valueKey || "count"),
                }))
                .map((item) => {
                    if (fixedMinMs === null || fixedMaxMs === null || !item.rows.length) return item;
                    const bucketMs = Number(options.bucketMs || 0);
                    if (Number.isFinite(bucketMs) && bucketMs > 0 && ((fixedMaxMs - fixedMinMs) / bucketMs) <= 2000) {
                        const values = new Map();
                        item.rows.forEach((row) => {
                            const key = Math.floor(row.ms / bucketMs) * bucketMs;
                            values.set(key, (values.get(key) || 0) + Number(row.value || 0));
                        });
                        const rows = [];
                        for (let ms = Math.ceil(fixedMinMs / bucketMs) * bucketMs; ms <= fixedMaxMs; ms += bucketMs) {
                            rows.push({ label: new Date(ms).toISOString(), ms, value: values.get(ms) || 0 });
                        }
                        return { ...item, rows };
                    }
                    const rows = [
                        { label: "start", ms: fixedMinMs, value: 0 },
                        ...item.rows.filter((row) => row.ms >= fixedMinMs && row.ms <= fixedMaxMs),
                        { label: "end", ms: fixedMaxMs, value: 0 },
                    ].sort((a, b) => a.ms - b.ms);
                    return { ...item, rows };
                })
                .filter((item) => item.rows.length);
            if (!series.length && chartEvents.length && fixedMinMs !== null && fixedMaxMs !== null) {
                series = [{
                    className: options.fallbackClassName || "es-chart-line-secondary",
                    rows: [
                        { label: new Date(fixedMinMs).toISOString(), ms: fixedMinMs, value: 0 },
                        { label: new Date(fixedMaxMs).toISOString(), ms: fixedMaxMs, value: 0 },
                    ],
                }];
            }
            const hasData = series.some((item) => item.rows.some((row) => row.value > 0)) || chartEvents.length > 0;
            if (empty) empty.classList.toggle("es-hidden", hasData);
            if (!hasData) {
                wrap.innerHTML = "";
                return;
            }

            const width = 920;
            const height = options.height || 240;
            const pad = { left: 58, right: 18, top: 18, bottom: 42 };
            const plotW = width - pad.left - pad.right;
            const plotH = height - pad.top - pad.bottom;
            const allRows = series.flatMap((item) => item.rows);
            const dataMinMs = Math.min(...allRows.map((row) => row.ms || Date.now()));
            const dataMaxMs = Math.max(...allRows.map((row) => row.ms || Date.now()), dataMinMs + 60000);
            let minMs = hasFixedMin ? Number(options.minMs) : dataMinMs;
            let maxMs = hasFixedMax ? Math.max(Number(options.maxMs), minMs + 60000) : dataMaxMs;
            if (options.focusDataDomain && hasFixedMin && hasFixedMax) {
                const bucketMs = Math.max(60000, Number(options.bucketMs || 60000));
                const eventTimes = (Array.isArray(options.events) ? options.events : [])
                    .map((event) => esEventMs(event))
                    .filter((ms) => ms >= fixedMinMs && ms <= fixedMaxMs);
                const dataTimes = allRows
                    .filter((row) => Number(row.value || 0) > 0 && row.ms >= fixedMinMs && row.ms <= fixedMaxMs)
                    .map((row) => row.ms);
                const focusTimes = [...dataTimes, ...eventTimes];
                if (focusTimes.length) {
                    const focusMin = Math.min(...focusTimes);
                    const focusMax = Math.max(...focusTimes);
                    const selectedSpan = Math.max(60000, fixedMaxMs - fixedMinMs);
                    const focusSpan = Math.max(bucketMs, focusMax - focusMin);
                    if (focusSpan < selectedSpan * 0.45) {
                        const padMs = Math.max(bucketMs * 2, focusSpan * 0.25);
                        minMs = Math.max(fixedMinMs, focusMin - padMs);
                        maxMs = Math.min(fixedMaxMs, focusMax + padMs);
                        if (maxMs - minMs < bucketMs * 6) {
                            const center = focusMin + ((focusMax - focusMin) / 2);
                            minMs = Math.max(fixedMinMs, center - (bucketMs * 3));
                            maxMs = Math.min(fixedMaxMs, center + (bucketMs * 3));
                        }
                    }
                }
            }
            const chartSeries = series
                .map((item) => ({ ...item, rows: item.rows.filter((row) => row.ms >= minMs && row.ms <= maxMs) }))
                .filter((item) => item.rows.length);
            const chartRows = chartSeries.flatMap((item) => item.rows);
            const dataMaxValue = Math.max(1, ...chartRows.map((row) => row.value));
            const baselineValue = Number(options.baseline || 0);
            const showBaseline = baselineValue > 0 && baselineValue <= dataMaxValue * 3;
            const maxValue = Math.max(dataMaxValue, showBaseline ? baselineValue : 0);
            const x = (ms) => pad.left + (((ms - minMs) / Math.max(1, maxMs - minMs)) * plotW);
            const y = (value) => pad.top + plotH - ((value / maxValue) * plotH);
            const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => Math.round(maxValue * ratio));
            const xTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => minMs + ((maxMs - minMs) * ratio));
            const primaryRows = chartSeries[0]?.rows || [];
            const nearestPrimaryRow = (ms) => primaryRows.reduce(
                (best, row) => !best || Math.abs(row.ms - ms) < Math.abs(best.ms - ms) ? row : best,
                null,
            );
            const lines = yTicks.map((tick) => {
                const yy = y(tick);
                return `<line class="es-chart-grid" x1="${pad.left}" y1="${yy.toFixed(1)}" x2="${width - pad.right}" y2="${yy.toFixed(1)}"></line>
                    <text class="es-chart-axis" x="${pad.left - 10}" y="${(yy + 4).toFixed(1)}" text-anchor="end">${tick}</text>`;
            }).join("");
            const xLabels = xTicks.map((tick, idx) => {
                const label = esChartTickLabel(tick, options.exactTimeAxis ? "datetime" : (options.timeMode || "time"));
                return `<text class="es-chart-axis" x="${x(tick).toFixed(1)}" y="${height - 12}" text-anchor="${idx === 0 ? "start" : idx === xTicks.length - 1 ? "end" : "middle"}">${esEsc(label)}</text>`;
            }).join("");
            const baseline = showBaseline
                ? `<path class="es-chart-line-baseline" d="M ${pad.left} ${y(baselineValue).toFixed(1)} L ${width - pad.right} ${y(baselineValue).toFixed(1)}"></path>`
                : "";
            const paths = chartSeries.map((item) => {
                const points = item.rows.map((row) => ({ x: x(row.ms), y: y(row.value), row }));
                const cls = item.className || "es-chart-line-http";
                return `<path class="${cls}" d="${esSvgPointPath(points)}"></path>`;
            }).join("");
            const pointDots = chartSeries.map((item) => {
                const cls = `${item.className || "es-chart-line-http"}-dot`;
                return item.rows
                    .filter((row) => row.value > 0 && row.ms >= minMs && row.ms <= maxMs)
                    .map((row) => `<circle class="es-chart-point ${cls}" cx="${x(row.ms).toFixed(1)}" cy="${y(row.value).toFixed(1)}" r="${item.rows.length === 1 ? 5 : 3}" data-es-tooltip="${esEsc(`${Number(row.value || 0).toLocaleString()} messages · ${esFullTime(row.ms)}`)}">
                        <title>${Number(row.value || 0).toLocaleString()} · ${esEsc(esFullTime(row.ms))}</title>
                    </circle>`)
                    .join("");
            }).join("");
            const alertBucketMs = Math.max(1000, Number(options.eventBucketMs || options.bucketMs || 60000));
            const groupedEvents = new Map();
            chartEvents
                .map((event) => ({ event, ms: esEventMs(event) }))
                .filter((item) => item.ms >= minMs && item.ms <= maxMs)
                .forEach((item) => {
                    const keyMs = Math.floor(item.ms / alertBucketMs) * alertBucketMs;
                    const key = String(keyMs);
                    const bucket = groupedEvents.get(key) || { ms: item.ms, count: 0, events: [], severities: new Set(), types: new Set(), firstMs: item.ms, lastMs: item.ms };
                    bucket.count += 1;
                    bucket.events.push(item.event);
                    bucket.severities.add(esSeverityTone(item.event.severity));
                    bucket.types.add(esEventTitle(item.event.event_type || item.event.type));
                    bucket.firstMs = Math.min(bucket.firstMs, item.ms);
                    bucket.lastMs = Math.max(bucket.lastMs, item.ms);
                    bucket.ms = Math.min(bucket.ms, item.ms);
                    groupedEvents.set(key, bucket);
                });
            const alertBucketForMs = (ms) => groupedEvents.get(String(Math.floor(ms / alertBucketMs) * alertBucketMs));
            const alertSummaryText = (bucket) => {
                if (!bucket || !bucket.count) return "0 alerts";
                const typeList = [...bucket.types].slice(0, 3).join(", ");
                return `${bucket.count.toLocaleString()} alert${bucket.count === 1 ? "" : "s"}${typeList ? ` · ${typeList}${bucket.types.size > 3 ? ", ..." : ""}` : ""}`;
            };
            const bucketHoverTargets = primaryRows
                .filter((row) => row.ms >= minMs && row.ms <= maxMs)
                .map((row) => {
                    const bucket = alertBucketForMs(row.ms);
                    const messages = Number(row.value || 0);
                    const bandWidth = Math.max(8, Math.min(42, (Number(options.bucketMs || alertBucketMs) / Math.max(1, maxMs - minMs)) * plotW));
                    const cx = x(row.ms);
                    const title = [
                        `time ${esFullTime(row.ms)}`,
                        `${messages.toLocaleString()} message${messages === 1 ? "" : "s"}`,
                        alertSummaryText(bucket),
                    ].join(" · ");
                    return `<rect class="es-chart-hover-bucket" x="${Math.max(pad.left, cx - (bandWidth / 2)).toFixed(1)}" y="${pad.top}" width="${bandWidth.toFixed(1)}" height="${plotH.toFixed(1)}" data-es-tooltip="${esEsc(title)}">
                        <title>${esEsc(title)}</title>
                    </rect>`;
                }).join("");
            const visibleEvents = [...groupedEvents.values()].sort((a, b) => a.ms - b.ms);
            const eventCollisionCounts = new Map();
            visibleEvents.forEach((item) => {
                const key = Math.round(x(item.ms) / 12);
                eventCollisionCounts.set(key, (eventCollisionCounts.get(key) || 0) + 1);
            });
            const eventCollisionSeen = new Map();
            const alertDots = visibleEvents.map((bucket) => {
                const ms = bucket.ms;
                const collisionKey = Math.round(x(ms) / 12);
                const collisionIndex = eventCollisionSeen.get(collisionKey) || 0;
                eventCollisionSeen.set(collisionKey, collisionIndex + 1);
                const collisionTotal = eventCollisionCounts.get(collisionKey) || 1;
                const cx = Math.max(pad.left + 4, Math.min(width - pad.right - 4, x(ms) + ((collisionIndex - ((collisionTotal - 1) / 2)) * 10)));
                const rowAtAlert = nearestPrimaryRow(ms);
                const messagesAtAlert = Number(rowAtAlert?.value || 0);
                const yy = messagesAtAlert > 0 ? y(messagesAtAlert) : Math.max(pad.top + 8, y(0) - 10);
                const firstEvent = bucket.events[0] || {};
                const detail = esEventDetails(firstEvent) || firstEvent.message || "";
                const typeList = [...bucket.types].slice(0, 3).join(", ");
                const title = [
                    `${bucket.count.toLocaleString()} alert${bucket.count === 1 ? "" : "s"}`,
                    `${messagesAtAlert.toLocaleString()} message${messagesAtAlert === 1 ? "" : "s"} in this bucket`,
                    typeList ? `type ${typeList}${bucket.types.size > 3 ? ", ..." : ""}` : "",
                    bucket.firstMs === bucket.lastMs ? `time ${esFullTime(bucket.firstMs)}` : `time ${esFullTime(bucket.firstMs)} - ${esFullTime(bucket.lastMs)}`,
                    `device ${firstEvent.device_id || firstEvent.source || "unknown"}`,
                    firstEvent.route ? `route ${firstEvent.route}` : "",
                    bucket.severities.size ? `severity ${[...bucket.severities].join("/")}` : "",
                    detail ? `sample measured ${detail}` : "",
                ].filter(Boolean).join(" · ");
                return `<g class="es-chart-alert-marker" data-es-tooltip="${esEsc(title)}">
                    <circle class="es-chart-alert-dot" cx="${cx.toFixed(1)}" cy="${yy.toFixed(1)}" r="4.8">
                        <title>${esEsc(title)}</title>
                    </circle>
                    ${bucket.count > 1 ? `<text class="es-chart-alert-count" x="${cx.toFixed(1)}" y="${(yy - 7).toFixed(1)}" text-anchor="middle">${bucket.count > 99 ? "99+" : bucket.count}</text>` : ""}
                </g>`;
            }).join("");

            wrap.innerHTML = `<svg class="es-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esEsc(options.title || "time series chart")}">
                ${lines}
                ${baseline}
                ${paths}
                ${bucketHoverTargets}
                ${pointDots}
                ${alertDots}
                ${xLabels}
                <text class="es-chart-axis-title" x="${pad.left + plotW / 2}" y="${height - 2}" text-anchor="middle">${esEsc(options.xTitle || "time")}</text>
                <text class="es-chart-axis-title" transform="translate(14 ${pad.top + plotH / 2}) rotate(-90)" text-anchor="middle">${esEsc(options.yTitle || "messages / min")}</text>
            </svg>`;
            } catch (error) {
                console.warn("[Edge Server] line chart render failed:", error);
                wrap.innerHTML = "";
                if (empty) {
                    empty.textContent = "Chart data is not available for this window.";
                    empty.classList.remove("es-hidden");
                }
            }
        };

        const esRenderTimelineChart = (selector, emptySelector, rows, options = {}) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            if (!wrap) return;
            try {
            const events = Array.isArray(rows) ? rows : [];
            if (empty) empty.classList.toggle("es-hidden", events.length > 0);
            if (!events.length) {
                wrap.innerHTML = "";
                return;
            }

            const width = 920;
            const eventMinMs = Math.min(...events.map(esEventMs));
            const eventMaxMs = Math.max(...events.map(esEventMs), eventMinMs + 60000);
            const hasFixedMin = options.minMs !== undefined && options.minMs !== null && Number.isFinite(Number(options.minMs));
            const hasFixedMax = options.maxMs !== undefined && options.maxMs !== null && Number.isFinite(Number(options.maxMs));
            const fixedMinMs = hasFixedMin ? Number(options.minMs) : null;
            const fixedMaxMs = hasFixedMax ? Math.max(Number(options.maxMs), Number(options.minMs || 0) + 60000) : null;
            let minMs = fixedMinMs ?? eventMinMs;
            let maxMs = fixedMaxMs ?? eventMaxMs;
            if (fixedMinMs !== null && fixedMaxMs !== null && options.fitEvents !== false) {
                const fixedSpan = Math.max(60000, fixedMaxMs - fixedMinMs);
                const eventSpan = Math.max(0, eventMaxMs - eventMinMs);
                if (eventSpan / fixedSpan < 0.35) {
                    const padMs = Math.max(60000, eventSpan * 0.35);
                    minMs = Math.max(fixedMinMs, eventMinMs - padMs);
                    maxMs = Math.min(fixedMaxMs, eventMaxMs + padMs);
                    if (maxMs - minMs < 60000) {
                        const center = eventMinMs + (eventSpan / 2);
                        minMs = Math.max(fixedMinMs, center - 30000);
                        maxMs = Math.min(fixedMaxMs, center + 30000);
                    }
                }
            }

            const typeStats = new Map();
            events.forEach((event) => {
                const name = esEventTitle(event.event_type || event.type);
                const item = typeStats.get(name) || { name, count: 0 };
                item.count += 1;
                typeStats.set(name, item);
            });
            const sortedTypes = [...typeStats.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
            const topTypes = sortedTypes.slice(0, 9).map((item) => item.name);
            const laneNames = sortedTypes.length > topTypes.length ? [...topTypes, "Other alerts"] : topTypes;
            const laneForEvent = (event) => {
                const name = esEventTitle(event.event_type || event.type);
                return topTypes.includes(name) ? name : "Other alerts";
            };

            const height = Math.max(270, 100 + (laneNames.length * 38));
            const pad = { left: 155, right: 42, top: 24, bottom: 48 };
            const plotW = width - pad.left - pad.right;
            const plotH = height - pad.top - pad.bottom;
            const laneHeight = plotH / Math.max(1, laneNames.length);
            const x = (ms) => pad.left + (((ms - minMs) / Math.max(1, maxMs - minMs)) * plotW);
            const y = (idx) => pad.top + ((idx + 0.5) * laneHeight);

            const laneCounts = new Map(laneNames.map((name) => [name, 0]));
            events.forEach((event) => {
                const lane = laneForEvent(event);
                laneCounts.set(lane, (laneCounts.get(lane) || 0) + 1);
            });
            const lanes = laneNames.map((name, idx) => `
                <rect class="es-timeline-lane-band" x="${pad.left}" y="${(y(idx) - laneHeight / 2).toFixed(1)}" width="${plotW}" height="${laneHeight.toFixed(1)}"></rect>
                <line class="es-chart-grid" x1="${pad.left}" y1="${y(idx).toFixed(1)}" x2="${width - pad.right}" y2="${y(idx).toFixed(1)}"></line>
                <text class="es-timeline-lane-label" x="${pad.left - 12}" y="${(y(idx) + 4).toFixed(1)}" text-anchor="end">${esEsc(name)}</text>
                <text class="es-timeline-lane-count" x="${width - pad.right + 8}" y="${(y(idx) + 4).toFixed(1)}">${Number(laneCounts.get(name) || 0).toLocaleString()}</text>
            `).join("");

            const xTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => minMs + ((maxMs - minMs) * ratio));
            const xLabels = xTicks.map((tick, idx) => {
                const label = esChartTickLabel(tick, options.timeMode || "datetime");
                return `<text class="es-chart-axis" x="${x(tick).toFixed(1)}" y="${height - 12}" text-anchor="${idx === 0 ? "start" : idx === xTicks.length - 1 ? "end" : "middle"}">${esEsc(label)}</text>`;
            }).join("");

            const spanMs = Math.max(60000, maxMs - minMs);
            const bucketMs = spanMs <= 2 * 3600 * 1000
                ? 60000
                : spanMs <= 24 * 3600 * 1000
                    ? 15 * 60000
                    : spanMs <= 7 * 86400 * 1000
                        ? 3600 * 1000
                        : 6 * 3600 * 1000;
            const grouped = new Map();
            events.forEach((event, eventIndex) => {
                const ms = esEventMs(event);
                if (ms < minMs || ms > maxMs) return;
                const lane = laneForEvent(event);
                const bucketStart = Math.floor(ms / bucketMs) * bucketMs;
                const key = `${lane}|${bucketStart}`;
                const item = grouped.get(key) || {
                    lane,
                    firstMs: ms,
                    lastMs: ms,
                    events: [],
                    severities: new Map(),
                    devices: new Map(),
                    routes: new Set(),
                    firstIndex: eventIndex,
                };
                item.firstMs = Math.min(item.firstMs, ms);
                item.lastMs = Math.max(item.lastMs, ms);
                item.firstIndex = Math.min(item.firstIndex, eventIndex);
                item.events.push(event);
                const severity = esSeverityTone(event.severity);
                item.severities.set(severity, (item.severities.get(severity) || 0) + 1);
                const device = event.device_id || event.source || "unknown";
                item.devices.set(device, (item.devices.get(device) || 0) + 1);
                if (event.route) item.routes.add(event.route);
                grouped.set(key, item);
            });

            const dots = [...grouped.values()].sort((a, b) => a.firstMs - b.firstMs).map((bucket) => {
                const laneIdx = Math.max(0, laneNames.indexOf(bucket.lane));
                const total = bucket.events.length;
                const tone = bucket.severities.has("critical") ? "critical"
                    : bucket.severities.has("error") ? "error"
                        : bucket.severities.has("warning") ? "warning"
                            : "info";
                const sample = bucket.events[0] || {};
                const detail = esEventDetails(sample) || sample.message || "";
                const deviceList = [...bucket.devices.entries()]
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 3)
                    .map(([device, count]) => `${device}${count > 1 ? ` (${count})` : ""}`)
                    .join(", ");
                const severityList = [...bucket.severities.entries()]
                    .sort((a, b) => b[1] - a[1])
                    .map(([severity, count]) => `${severity} ${count}`)
                    .join(", ");
                const title = [
                    `${total.toLocaleString()} ${bucket.lane}`,
                    bucket.firstMs === bucket.lastMs ? `time ${esFullTime(bucket.firstMs)}` : `time ${esFullTime(bucket.firstMs)} - ${esFullTime(bucket.lastMs)}`,
                    deviceList ? `devices ${deviceList}` : "",
                    bucket.routes.size ? `routes ${[...bucket.routes].slice(0, 3).join(", ")}` : "",
                    severityList ? `severity ${severityList}` : "",
                    detail ? `sample measured ${detail}` : "",
                ].filter(Boolean).join(" · ");
                const selectedClass = bucket.firstIndex === esSelectedAlertIndex ? " is-selected" : "";
                const eventX = Math.max(pad.left + 6, Math.min(width - pad.right - 6, x(bucket.firstMs)));
                const radius = Math.min(13, 5.5 + Math.sqrt(total) * 1.15);
                return `<g class="es-timeline-bubble" data-es-alert-index="${bucket.firstIndex}" data-es-tooltip="${esEsc(title)}">
                    <circle class="es-timeline-dot is-${tone}${selectedClass}" cx="${eventX.toFixed(1)}" cy="${y(laneIdx).toFixed(1)}" r="${radius.toFixed(1)}">
                        <title>${esEsc(title)}</title>
                    </circle>
                    ${total > 1 ? `<text class="es-timeline-count" x="${eventX.toFixed(1)}" y="${(y(laneIdx) + 3).toFixed(1)}" text-anchor="middle">${total > 99 ? "99+" : total}</text>` : ""}
                </g>`;
            }).join("");

            wrap.innerHTML = `<svg class="es-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="alert timeline">
                ${lanes}
                ${dots}
                ${xLabels}
                <text class="es-chart-axis-title" x="${pad.left + plotW / 2}" y="${height - 2}" text-anchor="middle">event time</text>
            </svg>`;
            } catch (error) {
                console.warn("[Edge Server] alert timeline render failed:", error);
                wrap.innerHTML = "";
                if (empty) {
                    empty.textContent = "Alert timeline is not available for this filter.";
                    empty.classList.remove("es-hidden");
                }
            }
        };

        const esRenderActiveAlerts = (group, rows) => {
            const events = (Array.isArray(rows) ? rows : [])
                .filter((event) => ["critical", "error", "warning", "warn"].includes(String(event.severity || "info").toLowerCase()))
                .slice(0, 6)
                .map((event) => ({ ...event, protocol_group: event.protocol_group || group }));
            const prefix = group === "http" ? "http" : "mqtt";
            const list = edgeShell.querySelector(`[data-es-${prefix}-active-alerts]`);
            const empty = edgeShell.querySelector(`[data-es-${prefix}-active-alerts-empty]`);
            const summary = edgeShell.querySelector(`[data-es-${prefix}-active-alert-summary]`);
            const critical = events.filter((event) => ["critical", "error"].includes(esSeverityTone(event.severity))).length;
            const warning = events.filter((event) => esSeverityTone(event.severity) === "warning").length;
            if (summary) summary.textContent = events.length ? `${critical} critical/error · ${warning} warning` : "No active alerts";
            if (empty) empty.classList.toggle("es-hidden", events.length > 0);
            if (list) list.innerHTML = events.map((event) => esRenderAlertCard(event, true)).join("");
        };

        const esSetProgress = (selector, value, max) => {
            const node = edgeShell.querySelector(selector);
            if (!node) return;
            const amount = Number(value || 0);
            const top = Math.max(1, Number(max || 0));
            const pct = amount <= 0 ? 0 : Math.max(2, Math.min(100, Math.round((amount / top) * 100)));
            node.style.width = `${pct}%`;
        };

        const esRefreshOverviewVisuals = () => {
            const now = Date.now();
            const httpMetrics = esNormalizeProtocolMetrics("http", esOverviewMetricsCache?.http || esHttpMetricsCache);
            const mqttMetrics = esNormalizeProtocolMetrics("mqtt", esOverviewMetricsCache?.mqtt || esMqttMetricsCache);
            esRenderWatchlist("[data-es-overview-watchlist]", "all");
            esRenderLineChart("[data-es-overview-traffic]", "[data-es-overview-traffic-empty]", [
                { rows: httpMetrics.minute_series, className: "es-chart-line-http" },
                { rows: mqttMetrics.minute_series, className: "es-chart-line-mqtt" },
            ], {
                title: "Inbound traffic",
                xTitle: "gateway receive time",
                yTitle: "messages / min",
                events: [...httpMetrics.recent_events, ...mqttMetrics.recent_events],
                bucketMs: 60000,
                minMs: now - (60 * 60 * 1000),
                maxMs: now,
                relativeStart: "-60m",
                relativeEnd: "now",
                exactTimeAxis: true,
            });
        };

        const esRefreshOverviewMetrics = async () => {
            try {
                const response = await fetch("/api/edge-server/overview/metrics?minutes=60");
                if (!response.ok) {
                    throw new Error(`${response.status} ${response.statusText}`);
                }
                const data = await response.json();
                esOverviewMetricsCache = {
                    http: esNormalizeProtocolMetrics("http", data.http),
                    mqtt: esNormalizeProtocolMetrics("mqtt", data.mqtt),
                };
            } catch (error) {
                console.warn("[Edge Server] overview metrics fetch failed:", error);
                esOverviewMetricsCache = null;
            }
            esRefreshOverviewVisuals();
        };

        const esRenderBars = (selector, emptySelector, rows) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            const items = Array.isArray(rows) ? rows : [];
            if (empty) empty.classList.toggle("es-hidden", items.length > 0);
            if (!wrap) return;
            const max = Math.max(1, ...items.map((row) => Number(row.count || 0)));
            wrap.innerHTML = items.map((row) => {
                const count = Number(row.count || 0);
                const pct = Math.max(4, Math.round((count / max) * 100));
                const bucket = row.minute || row.bucket || "";
                const label = esBucketTime(bucket);
                return `
                    <div class="es-chart-bar" title="${esEsc(bucket || label)}">
                        <span>${esEsc(label)}</span>
                        <div class="es-chart-track"><div class="es-chart-fill" style="width:${pct}%"></div></div>
                        <strong>${count}</strong>
                    </div>`;
            }).join("");
        };

        const esRenderRoutes = (selector, emptySelector, rows) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            const items = Array.isArray(rows) ? rows : [];
            if (empty) empty.classList.toggle("es-hidden", items.length > 0);
            if (!wrap) return;
            wrap.innerHTML = items.map((row) => `
                <div class="es-route-row">
                    <strong>${esEsc(row.route || "unknown")}</strong>
                    <span>${Number(row.count || 0).toLocaleString()}</span>
                    <small>${Number(row.devices ?? row.sources ?? 0).toLocaleString()} ${row.sources !== undefined ? "sources" : "devices"}</small>
                    <em>${esEsc(esShortTime(row.last_seen))}</em>
                </div>
            `).join("");
        };

        const esRenderMessages = (selector, emptySelector, rows) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            const items = Array.isArray(rows) ? rows : [];
            if (empty) empty.classList.toggle("es-hidden", items.length > 0);
            if (!wrap) return;
            wrap.innerHTML = items.map((row) => `
                <div class="es-message-row">
                    <span>${esProtocolTag(row.protocol || "")}</span>
                    <strong>${esEsc(row.device_id || "unknown")}</strong>
                    <small>${esEsc(row.route || "")}</small>
                    <em>${Number(row.payload_size || 0).toLocaleString()} B</em>
                    <em>${esEsc(esShortTime(row.received_at))}</em>
                </div>
            `).join("");
        };

        const esRenderProtocolDevices = (selector, emptySelector, rows, group) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            const items = Array.isArray(rows) ? rows : [];
            if (empty) empty.classList.toggle("es-hidden", items.length > 0);
            if (!wrap) return;
            wrap.innerHTML = items.map((device) => {
                const health = device.health || (device.online ? "active" : group === "mqtt" ? "disconnected" : "recent");
                const label = device.health_label || (
                    group === "mqtt"
                        ? (device.online ? "Connected" : "Disconnected")
                        : (health === "active" ? "Receiving data" : "Recently seen")
                );
                const routeLabel = group === "http" ? "Path" : "Topic";
                const count = Number(device.message_count || 0).toLocaleString();
                const anomalies = Number(device.anomaly_count || 0);
                const signalParts = [
                    `last gap ${esFormatMs(device.last_interval_ms)}`,
                    `normal ${esFormatMs(device.avg_interval_ms)}`,
                    `payload ${esFormatBytes(device.last_payload_size)}`,
                    `normal payload ${esFormatBytes(device.avg_payload_size)}`,
                ];
                if (device.last_sequence !== undefined && device.last_sequence !== null && device.last_sequence !== "") {
                    signalParts.push(`seq ${device.last_sequence}`);
                }
                return `
                    <div class="es-device-row es-device-row-health is-${esEsc(health)}">
                        <strong>${esEsc(device.device_id || "unknown")}</strong>
                        <span>${esEsc(label)}</span>
                        <small>${routeLabel}: ${esEsc(device.endpoint || device.last_route || "unknown")} · ${count} message${count === "1" ? "" : "s"} · ${signalParts.map(esEsc).join(" · ")}${anomalies ? ` · ${anomalies} alerts` : ""}</small>
                        <em>${esEsc(esAge(device.last_seen))}</em>
                    </div>`;
            }).join("");
        };

        const esRenderAnomalySummary = (selector, emptySelector, rows) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            const items = Array.isArray(rows) ? rows : [];
            if (empty) empty.classList.toggle("es-hidden", items.length > 0);
            if (!wrap) return;
            wrap.innerHTML = items.map((row) => {
                const type = row.event_type || row.type || "event";
                return `
                    <div class="es-anomaly-row">
                        <strong>${esEsc(esEventTitle(type))}</strong>
                        <span>${Number(row.count || 0).toLocaleString()}</span>
                        <small>${esEsc(esEventMeaning(type))}</small>
                        <em>${esEsc(esShortTime(row.last_seen))}</em>
                    </div>`;
            }).join("");
        };

        const esRenderTypeBars = (selector, emptySelector, rows) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            const items = (Array.isArray(rows) ? rows : [])
                .map((row) => ({
                    event_type: row.event_type || row.type || "event",
                    count: Number(row.count || 0),
                    last_seen: row.last_seen || row.created_at || row.timestamp || "",
                }))
                .filter((row) => row.count > 0)
                .sort((a, b) => b.count - a.count);
            if (empty) empty.classList.toggle("es-hidden", items.length > 0);
            if (!wrap) return;
            const max = Math.max(1, ...items.map((row) => row.count));
            wrap.innerHTML = items.map((row) => {
                const width = Math.max(2, (row.count / max) * 100);
                const title = `${esEventTitle(row.event_type)} · ${row.count.toLocaleString()} event${row.count === 1 ? "" : "s"}${row.last_seen ? ` · latest ${esFullTime(row.last_seen)}` : ""}`;
                return `
                    <div class="es-type-bar-row" title="${esEsc(title)}">
                        <strong>${esEsc(esEventTitle(row.event_type))}</strong>
                        <div class="es-type-track"><span class="es-type-fill" style="width:${width.toFixed(1)}%"></span></div>
                        <span>${row.count.toLocaleString()}</span>
                    </div>`;
            }).join("");
        };

        const esRenderProtocolEvents = (selector, emptySelector, rows) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            const items = Array.isArray(rows) ? rows : [];
            if (empty) empty.classList.toggle("es-hidden", items.length > 0);
            if (!wrap) return;
            wrap.innerHTML = items.map(esRenderAlertCard).join("");
        };

        const esRenderAlertEvents = (selector, emptySelector, rows) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            const items = Array.isArray(rows) ? rows : [];
            if (empty) empty.classList.toggle("es-hidden", items.length > 0);
            if (!wrap) return;
            wrap.innerHTML = items.map((event, index) => esRenderAlertCard(event, false, index)).join("");
        };

        const esRenderSelectedAlert = () => {
            const wrap = edgeShell.querySelector("[data-es-alert-selected]");
            if (!wrap) return;
            const event = esAlertEventsCache[esSelectedAlertIndex];
            if (!event) {
                wrap.innerHTML = `<strong>Select an alert point or row</strong><span>Click a timeline dot or alert card to inspect the exact device, time, and measured values.</span>`;
                return;
            }
            const type = event.event_type || event.type || "event";
            const detail = esEventDetails(event) || event.message || esEventMeaning(type);
            const device = event.device_id || event.source || "unknown device";
            const protocol = event.protocol || "unknown";
            const route = event.route || "no route/topic";
            const when = event.created_at || event.timestamp || event.last_seen;
            wrap.innerHTML = `
                <strong>${esEsc(esEventTitle(type))}</strong>
                <span>${esProtocolTag(protocol)} ${esEsc(device)} · ${esEsc(route)} · ${esEsc(esFullTime(when))}</span>
                <small>${esEsc(detail)}</small>
                <small>${esEsc(esEventMeaning(type))}</small>
            `;
        };

        const esRenderAlertDevicePills = (events) => {
            const wrap = edgeShell.querySelector("[data-es-alert-device-pills]");
            if (!wrap) return;
            const selected = edgeShell.querySelector("[data-es-alert-device]")?.value || "";
            const counts = new Map();
            (Array.isArray(events) ? events : []).forEach((event) => {
                const device = String(event.device_id || event.source || "unknown");
                counts.set(device, (counts.get(device) || 0) + 1);
            });
            const rows = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
            wrap.innerHTML = [
                `<button type="button" class="es-alert-device-pill ${selected ? "" : "is-active"}" data-es-alert-device-pill="">All devices</button>`,
                ...rows.map(([device, count]) => `<button type="button" class="es-alert-device-pill ${selected === device ? "is-active" : ""}" data-es-alert-device-pill="${esEsc(device)}">${esEsc(device)} · ${count}</button>`),
            ].join("");
        };

        const esMergeAlertDeviceOptions = (events) => {
            const select = edgeShell.querySelector("[data-es-alert-device]");
            if (!select) return;
            const selected = select.value;
            const existing = new Set([...select.options].map((option) => option.value));
            const devices = [...new Set((Array.isArray(events) ? events : [])
                .map((event) => String(event.device_id || event.source || "unknown"))
                .filter(Boolean))]
                .sort();
            devices.forEach((device) => {
                if (existing.has(device)) return;
                const option = document.createElement("option");
                option.value = device;
                option.textContent = `${device} · alert source`;
                select.appendChild(option);
            });
            if (selected) select.value = selected;
        };

        const esRenderMetricBars = (selector, emptySelector, rows, valueKey, formatter = (value) => value) => {
            const wrap = edgeShell.querySelector(selector);
            const empty = edgeShell.querySelector(emptySelector);
            const items = Array.isArray(rows) ? rows.filter((row) => Number(row[valueKey] || 0) > 0) : [];
            if (empty) empty.classList.toggle("es-hidden", items.length > 0);
            if (!wrap) return;
            const max = Math.max(1, ...items.map((row) => Number(row[valueKey] || 0)));
            wrap.innerHTML = items.map((row) => {
                const value = Number(row[valueKey] || 0);
                const pct = Math.max(4, Math.round((value / max) * 100));
                const bucket = row.minute || row.bucket || "";
                const label = esBucketTime(bucket);
                return `
                    <div class="es-chart-bar" title="${esEsc(bucket || label)}">
                        <span>${esEsc(label)}</span>
                        <div class="es-chart-track"><div class="es-chart-fill" style="width:${pct}%"></div></div>
                        <strong>${esEsc(formatter(value))}</strong>
                    </div>`;
            }).join("");
        };

        const esProtocolWindowMinutes = (group) => {
            const raw = edgeShell.querySelector(`[data-es-protocol-window="${group}"]`)?.value || "60";
            const minutes = Number(raw);
            return Number.isFinite(minutes) ? Math.max(5, Math.min(1440, minutes)) : 60;
        };

        const esLiveWindowInfo = (group) => {
            const minutes = esProtocolWindowMinutes(group);
            const now = Date.now();
            const label = minutes < 60
                ? `Last ${minutes} minutes`
                : minutes === 60
                    ? "Last 60 minutes"
                    : minutes === 1440
                        ? "Last 24 hours"
                        : `Last ${Math.round(minutes / 60)} hours`;
            return {
                minutes,
                label,
                minMs: now - (minutes * 60 * 1000),
                maxMs: now,
                relativeStart: minutes === 60 ? "-60m" : `-${minutes}m`,
                relativeEnd: "now",
                timeMode: minutes > 360 ? "datetime" : "time",
            };
        };

        const esSelectedProtocolDevice = (group) => edgeShell.querySelector(`[data-es-${group}-device-filter]`)?.value || "";

        const esProtocolDeviceSearch = (group) => group === "http" ? esHttpDeviceSearch : esMqttDeviceSearch;

        const esRenderProtocolDeviceOptions = (devices, group) => {
            const select = edgeShell.querySelector(`[data-es-${group}-device-filter]`);
            if (!select) return;
            const selected = select.value;
            const search = esProtocolDeviceSearch(group).trim().toLowerCase();
            const rows = Array.isArray(devices) ? devices : [];
            const filtered = rows.filter((device) => {
                if (!search) return true;
                return [
                    device.device_id,
                    device.endpoint,
                    device.last_route,
                    device.topic,
                    device.health,
                    device.health_label,
                    device.status,
                ].some((value) => String(value || "").toLowerCase().includes(search));
            });
            const selectedDevice = rows.find((device) => String(device.device_id || "") === selected);
            const optionRows = selectedDevice && !filtered.some((device) => String(device.device_id || "") === selected)
                ? [selectedDevice, ...filtered]
                : filtered;
            const label = group === "http" ? "HTTP" : "MQTT";
            select.innerHTML = [
                `<option value="">All ${label} devices</option>`,
                ...optionRows.map((device) => {
                    const id = String(device.device_id || "unknown");
                    const label = `${id} · ${device.health_label || device.status || "seen"} · ${esAge(device.last_seen)}`;
                    return `<option value="${esEsc(id)}">${esEsc(label)}</option>`;
                }),
            ].join("");
            select.value = selected && optionRows.some((device) => String(device.device_id || "") === selected) ? selected : "";
        };

        const esUpdateProtocolSelectedCards = (group, device) => {
            const label = group === "http" ? "HTTP" : "MQTT";
            if (!device) {
                esSetText(`[data-es-${group}-selected-status]`, "All devices");
                esSetText(`[data-es-${group}-selected-last]`, "No single device selected");
                esSetText(`[data-es-${group}-selected-gap]`, "n/a");
                esSetText(`[data-es-${group}-selected-normal-gap]`, "n/a");
                esSetText(`[data-es-${group}-selected-payload]`, "n/a");
                return;
            }
            esSetText(`[data-es-${group}-selected-status]`, device.health_label || device.status || "Seen");
            esSetText(`[data-es-${group}-selected-last]`, `${device.device_id || "unknown"} · ${label} · last seen ${esAge(device.last_seen || device.last_seen_at)}`);
            esSetText(`[data-es-${group}-selected-gap]`, esFormatMs(device.last_interval_ms));
            esSetText(`[data-es-${group}-selected-normal-gap]`, esFormatMs(device.avg_interval_ms));
            esSetText(`[data-es-${group}-selected-payload]`, `${esFormatBytes(device.last_payload_size)} / ${esFormatBytes(device.avg_payload_size)}`);
        };

        const esRefreshProtocolDeviceDetail = async (group, deviceId = esSelectedProtocolDevice(group)) => {
            if (!deviceId) return;
            const windowInfo = esLiveWindowInfo(group);
            const cache = group === "mqtt" ? esMqttMetricsCache : esHttpMetricsCache;
            const device = (cache?.devices || []).find((item) => String(item.device_id || "") === String(deviceId));
            const trace = cache?.device_traces?.[deviceId] || { message_series: [], recent_events: [] };
            if (device) esUpdateProtocolSelectedCards(group, device);
            const lineClass = group === "mqtt" ? "es-chart-line-mqtt" : "es-chart-line-http";
            const action = group === "mqtt" ? "publishes" : "requests";
            const baseline = esRateBaseline(trace.message_series || []);
            esSetText(`[data-es-${group}-device-rate-caption]`, `Live selected device only · line is accepted ${action} per minute · red markers are grouped alert times`);
            esRenderLineChart(`[data-es-${group}-device-rate-chart]`, `[data-es-${group}-device-rate-empty]`, [
                { rows: trace.message_series || [], className: lineClass },
            ], {
                title: `Live selected ${group.toUpperCase()} device rate`,
                xTitle: "gateway receive time",
                yTitle: `${action} / min`,
                events: trace.recent_events || [],
                baseline,
                bucketMs: 60000,
                minMs: windowInfo.minMs,
                maxMs: windowInfo.maxMs,
                relativeStart: windowInfo.relativeStart,
                relativeEnd: windowInfo.relativeEnd,
                timeMode: windowInfo.timeMode,
                exactTimeAxis: true,
            });
        };

        const esEmptyProtocolMetrics = (group) => ({
            ok: true,
            protocol_group: group,
            total_messages: 0,
            device_count: 0,
            avg_payload_size: 0,
            max_payload_size: 0,
            route_missing: 0,
            auth_failures: 0,
            routes: [],
            minute_series: [],
            recent_messages: [],
            devices: [],
            anomaly_summary: [],
            recent_events: [],
            device_traces: {},
        });

        const esNormalizeProtocolMetrics = (group, data) => {
            const fallback = esEmptyProtocolMetrics(group);
            const metrics = data && typeof data === "object" ? { ...fallback, ...data } : fallback;
            metrics.routes = Array.isArray(metrics.routes) ? metrics.routes : [];
            metrics.minute_series = Array.isArray(metrics.minute_series) ? metrics.minute_series : [];
            metrics.recent_messages = Array.isArray(metrics.recent_messages) ? metrics.recent_messages : [];
            metrics.devices = Array.isArray(metrics.devices) ? metrics.devices : [];
            metrics.anomaly_summary = Array.isArray(metrics.anomaly_summary) ? metrics.anomaly_summary : [];
            metrics.recent_events = Array.isArray(metrics.recent_events) ? metrics.recent_events : [];
            metrics.device_traces = metrics.device_traces && typeof metrics.device_traces === "object" ? metrics.device_traces : {};
            return metrics;
        };

        const esApplyProtocolMetrics = async (group, data) => {
            data = esNormalizeProtocolMetrics(group, data);
            if (group === "http") esHttpMetricsCache = data || {};
            if (group === "mqtt") esMqttMetricsCache = data || {};

            const windowInfo = esLiveWindowInfo(group);
            const action = group === "mqtt" ? "publishes" : "requests";
            const routeLabel = group === "http" ? "paths with traffic" : "topics with traffic";
            const lineClass = group === "mqtt" ? "es-chart-line-mqtt" : "es-chart-line-http";

            esSetText(`[data-es-${group}-total]`, Number(data.total_messages || 0).toLocaleString());
            esSetText(`[data-es-${group}-devices]`, Number(data.device_count || 0).toLocaleString());
            esSetText(`[data-es-${group}-missing]`, Number(data.route_missing || 0).toLocaleString());
            esSetText(`[data-es-${group}-auth-fail]`, Number(data.auth_failures || 0).toLocaleString());
            esSetText(`[data-es-${group}-route-count]`, `${(data.routes || []).length} ${routeLabel}`);
            esSetText(`[data-es-${group}-chart-caption]`, `Live ${group.toUpperCase()} fleet · line is accepted ${action} per minute · red markers are grouped alert times/counts`);

            esRenderProtocolDeviceOptions(data.devices || [], group);
            esRenderActiveAlerts(group, data.recent_events || []);
            esRenderLineChart(`[data-es-${group}-chart]`, `[data-es-${group}-chart-empty]`, [
                { rows: data.minute_series || [], className: lineClass },
            ], {
                title: `${group.toUpperCase()} traffic by minute`,
                xTitle: "gateway receive time",
                yTitle: `${action} / min`,
                events: data.recent_events || [],
                bucketMs: 60000,
                minMs: windowInfo.minMs,
                maxMs: windowInfo.maxMs,
                relativeStart: windowInfo.relativeStart,
                relativeEnd: windowInfo.relativeEnd,
                timeMode: windowInfo.timeMode,
                exactTimeAxis: true,
            });
            esRenderRoutes(`[data-es-${group}-routes]`, `[data-es-${group}-routes-empty]`, data.routes || []);
            esRefreshOverviewVisuals();

            const selected = esSelectedProtocolDevice(group);
            const selectedDevice = selected
                ? (data.devices || []).find((device) => String(device.device_id || "") === selected)
                : null;
            esUpdateProtocolSelectedCards(group, selectedDevice);
            const deviceRows = selected ? (data.devices || []).filter((device) => String(device.device_id || "") === selected) : (data.devices || []);
            esRenderProtocolDevices(`[data-es-${group}-devices-list]`, `[data-es-${group}-devices-empty]`, deviceRows, group);

            if (!selected) {
                esRenderLineChart(`[data-es-${group}-device-rate-chart]`, `[data-es-${group}-device-rate-empty]`, [], {
                    title: `Selected ${group.toUpperCase()} device rate`,
                    xTitle: `time (${windowInfo.label.toLowerCase()})`,
                    yTitle: "messages / min",
                });
                esSetText(`[data-es-${group}-device-rate-caption]`, `Select a live device to show its accepted ${action} per minute and grouped alert markers.`);
                esSetText(`[data-es-${group}-device-summary]`, `${Number(data.device_count || 0).toLocaleString()} ${group.toUpperCase()} device${Number(data.device_count || 0) === 1 ? "" : "s"} · showing all`);
                return;
            }

            esSetText(`[data-es-${group}-device-summary]`, `Showing ${selected}. Graphs and latest rows are filtered to this device.`);
            await esRefreshProtocolDeviceDetail(group, selected);
        };

        const esPad2 = (value) => String(value).padStart(2, "0");

        const esLocalDateValue = (date = new Date()) => {
            return `${date.getFullYear()}-${esPad2(date.getMonth() + 1)}-${esPad2(date.getDate())}`;
        };

        const esHistoryDateValue = () => {
            const input = edgeShell.querySelector("[data-es-history-date]");
            if (!input) return esLocalDateValue();
            if (!input.value) input.value = esLocalDateValue();
            return input.value;
        };

        const esHistoryHourValue = () => {
            const input = edgeShell.querySelector("[data-es-history-hour]");
            if (!input) return esPad2(new Date().getHours());
            if (!input.value) input.value = esPad2(new Date().getHours());
            return input.value;
        };

        const esLocalRangeFromDay = (dayValue, hourValue = null) => {
            const [year, month, day] = String(dayValue || esLocalDateValue()).split("-").map((part) => Number(part));
            const hour = hourValue === null ? 0 : Number(hourValue);
            const start = new Date(year, Math.max(0, month - 1), day, hour, 0, 0, 0);
            const end = hourValue === null
                ? new Date(year, Math.max(0, month - 1), day + 1, 0, 0, 0, 0)
                : new Date(year, Math.max(0, month - 1), day, hour + 1, 0, 0, 0);
            return { start, end };
        };

        const esSetHistoryWindowControls = () => {
            const range = edgeShell.querySelector("[data-es-history-range]")?.value || "30d";
            const dateWrap = edgeShell.querySelector("[data-es-history-date-wrap]");
            const hourWrap = edgeShell.querySelector("[data-es-history-hour-wrap]");
            esHistoryDateValue();
            esHistoryHourValue();
            if (dateWrap) dateWrap.classList.toggle("is-hidden", range !== "day" && range !== "hour");
            if (hourWrap) hourWrap.classList.toggle("is-hidden", range !== "hour");
        };

        const esHistoryWindowInfo = () => {
            const range = edgeShell.querySelector("[data-es-history-range]")?.value || "30d";
            const params = new URLSearchParams();
            const protocol = edgeShell.querySelector("[data-es-history-protocol]")?.value || "";
            if (protocol) params.set("protocol_group", protocol);

            const now = Date.now();
            let startMs = null;
            let endMs = null;
            let label = "All stored data";
            let relativeStart = "";
            let relativeEnd = "";
            let timeMode = "datetime";
            let bucketMs = 86400 * 1000;
            let bucketLabel = "per day";

            if (range === "hour") {
                const day = esHistoryDateValue();
                const hour = esHistoryHourValue();
                const { start, end } = esLocalRangeFromDay(day, hour);
                startMs = start.getTime();
                endMs = end.getTime();
                label = `${start.toLocaleDateString()} ${hour}:00-${hour}:59`;
                timeMode = "time";
                bucketMs = 60000;
                bucketLabel = "per minute";
            } else if (range === "day") {
                const { start, end } = esLocalRangeFromDay(esHistoryDateValue());
                startMs = start.getTime();
                endMs = end.getTime();
                label = start.toLocaleDateString([], { year: "numeric", month: "short", day: "2-digit" });
                timeMode = "time";
                bucketMs = 60000;
                bucketLabel = "per minute";
            } else if (range !== "all") {
                const duration = range === "24h" ? 24 * 3600 * 1000 : range === "7d" ? 7 * 86400 * 1000 : 30 * 86400 * 1000;
                startMs = now - duration;
                endMs = now;
                label = range === "24h" ? "Last 24 hours" : range === "7d" ? "Last 7 days" : "Last 30 days";
                relativeStart = range === "24h" ? "-24h" : range === "7d" ? "-7d" : "-30d";
                relativeEnd = "now";
                timeMode = range === "24h" ? "time" : "datetime";
                bucketMs = range === "24h" ? 60000 : 3600 * 1000;
                bucketLabel = range === "24h" ? "per minute" : "per hour";
            }

            if (startMs !== null && endMs !== null) {
                params.set("from", new Date(startMs).toISOString());
                params.set("to", new Date(endMs).toISOString());
            }
            return { params, range, label, startMs, endMs, relativeStart, relativeEnd, timeMode, bucketMs, bucketLabel };
        };

        const esHistoryRangeParams = () => {
            return esHistoryWindowInfo().params;
        };

        const esAlertWindowInfo = () => {
            const range = edgeShell.querySelector("[data-es-alert-range]")?.value || "30d";
            const params = new URLSearchParams({ limit: "10000" });
            const protocolGroup = edgeShell.querySelector("[data-es-alert-protocol-group]")?.value || "";
            const protocol = edgeShell.querySelector("[data-es-alert-protocol]")?.value || "";
            const deviceId = edgeShell.querySelector("[data-es-alert-device]")?.value || "";
            if (protocol) {
                params.set("protocol", protocol);
            } else if (protocolGroup) {
                params.set("protocol_group", protocolGroup);
            }
            if (deviceId) params.set("device_id", deviceId);

            const now = Date.now();
            let startMs = null;
            let endMs = null;
            let label = "All stored data";
            let relativeStart = "";
            let relativeEnd = "";
            let timeMode = "datetime";

            if (range !== "all") {
                const duration = range === "24h" ? 24 * 3600 * 1000 : range === "7d" ? 7 * 86400 * 1000 : 30 * 86400 * 1000;
                startMs = now - duration;
                endMs = now;
                label = range === "24h" ? "Last 24 hours" : range === "7d" ? "Last 7 days" : "Last 30 days";
                relativeStart = range === "24h" ? "-24h" : range === "7d" ? "-7d" : "-30d";
                relativeEnd = "now";
                timeMode = range === "24h" ? "time" : "datetime";
                params.set("from", new Date(startMs).toISOString());
                params.set("to", new Date(endMs).toISOString());
            }
            return { params, range, label, startMs, endMs, relativeStart, relativeEnd, timeMode };
        };

        const esAlertTimelineOptions = (windowInfo = esAlertWindowInfo()) => ({
            minMs: windowInfo.startMs,
            maxMs: windowInfo.endMs,
            relativeStart: windowInfo.relativeStart,
            relativeEnd: windowInfo.relativeEnd,
            timeMode: windowInfo.timeMode,
        });

        const esSelectedHistoryDevice = () => edgeShell.querySelector("[data-es-history-device]")?.value || "";

        const esUpdateHistoryExports = () => {
            const deviceId = esSelectedHistoryDevice();
            const params = esHistoryRangeParams();
            if (deviceId) params.set("device_id", deviceId);
            const query = params.toString();
            const messages = edgeShell.querySelector("[data-es-history-messages-export]");
            const events = edgeShell.querySelector("[data-es-history-events-export]");
            if (messages) messages.setAttribute("href", `/api/edge-server/messages.csv${query ? `?${query}` : ""}`);
            if (events) events.setAttribute("href", `/api/edge-server/events.csv${query ? `?${query}` : ""}`);
        };

        const esRenderHistoryDevices = async () => {
            try {
                const response = await fetch("/api/edge-server/history/devices");
                const data = await response.json();
                const devices = data.devices || [];
                const select = edgeShell.querySelector("[data-es-history-device]");
                if (!select) return;
                const previous = select.value;
                select.innerHTML = devices.length
                    ? devices.map((device) => {
                        const label = `${device.device_id || "unknown"} · ${device.protocol || "unknown"} · ${esAge(device.last_seen || device.last_seen_at)}`;
                        return `<option value="${esEsc(device.device_id || "unknown")}">${esEsc(label)}</option>`;
                    }).join("")
                    : '<option value="">No stored devices</option>';
                if (previous && devices.some((device) => String(device.device_id || "") === previous)) {
                    select.value = previous;
                }
            } catch (error) {
                console.warn("[Edge Server] history devices fetch failed:", error);
            }
        };

        const esRenderAlertDevices = async () => {
            const select = edgeShell.querySelector("[data-es-alert-device]");
            if (!select) return;
            try {
                const response = await fetch("/api/edge-server/history/devices");
                const data = await response.json();
                const protocolGroup = edgeShell.querySelector("[data-es-alert-protocol-group]")?.value || "";
                const protocol = edgeShell.querySelector("[data-es-alert-protocol]")?.value || "";
                const protocols = protocolGroup === "http" ? ["HTTP", "HTTPS"] : protocolGroup === "mqtt" ? ["MQTT", "MQTTS"] : null;
                const previous = select.value;
                const devices = (data.devices || []).filter((device) => {
                    const itemProtocol = String(device.protocol || "").toUpperCase();
                    if (protocol && itemProtocol !== protocol) return false;
                    if (!protocol && protocols && !protocols.includes(itemProtocol)) return false;
                    return true;
                });
                select.innerHTML = `<option value="">All devices</option>${devices.map((device) => {
                    const label = `${device.device_id || "unknown"} · ${device.protocol || "unknown"} · ${esAge(device.last_seen || device.last_seen_at)}`;
                    return `<option value="${esEsc(device.device_id || "unknown")}">${esEsc(label)}</option>`;
                }).join("")}`;
                if (previous && devices.some((device) => String(device.device_id || "") === previous)) {
                    select.value = previous;
                } else if (previous) {
                    const option = document.createElement("option");
                    option.value = previous;
                    option.textContent = `${previous} · alert source`;
                    select.appendChild(option);
                    select.value = previous;
                }
            } catch (error) {
                console.warn("[Edge Server] alert devices fetch failed:", error);
            }
        };

        const esRefreshDeviceHistory = async () => {
            esSetHistoryWindowControls();
            const deviceId = esSelectedHistoryDevice();
            esUpdateHistoryExports();
            if (!deviceId) {
                esSetText("[data-es-history-total]", "0");
                esSetText("[data-es-history-events]", "0");
                esSetText("[data-es-history-last]", "Never");
                esSetText("[data-es-history-status]", "No device selected");
                esSetText("[data-es-history-payload]", "0 B");
                return;
            }
            const windowInfo = esHistoryWindowInfo();
            const params = windowInfo.params;
            params.set("device_id", deviceId);
            try {
                const response = await fetch(`/api/edge-server/history/device?${params.toString()}`);
                const data = await response.json();
                const summary = data.summary || {};
                const device = data.device || {};
                const baseline = esRateBaseline(data.message_series || []);
                esSetText("[data-es-history-total]", Number(summary.total_messages || 0).toLocaleString());
                esSetText("[data-es-history-events]", Number(summary.event_count || 0).toLocaleString());
                esSetText("[data-es-history-last]", esShortTime(summary.last_message_at || device.last_seen));
                esSetText("[data-es-history-status]", `${device.health_label || "Stored"} · ${esAge(summary.last_message_at || device.last_seen)}`);
                esSetText("[data-es-history-payload]", esFormatBytes(summary.avg_payload_size));
                esSetText("[data-es-history-message-window]", `${windowInfo.label} · messages ${windowInfo.bucketLabel}`);
                esSetText("[data-es-history-message-caption]", `Persisted device history · focused on data inside ${windowInfo.label} · line is stored messages ${windowInfo.bucketLabel} · red markers are grouped anomaly times/counts`);
                esRenderLineChart("[data-es-history-message-chart]", "[data-es-history-message-empty]", [
                    { rows: data.message_series || [], className: "es-chart-line-secondary" },
                ], {
                    title: "Stored message rate history",
                    xTitle: "gateway receive time",
                    yTitle: `messages ${windowInfo.bucketLabel}`,
                    events: data.recent_events || [],
                    baseline,
                    bucketMs: windowInfo.bucketMs,
                    minMs: windowInfo.startMs,
                    maxMs: windowInfo.endMs,
                    relativeStart: windowInfo.relativeStart,
                    relativeEnd: windowInfo.relativeEnd,
                    timeMode: windowInfo.timeMode,
                    exactTimeAxis: true,
                    focusDataDomain: true,
                });
                esRenderTypeBars("[data-es-history-event-summary]", "[data-es-history-event-summary-empty]", data.event_summary || []);
                esRenderProtocolEvents("[data-es-history-events-list]", "[data-es-history-events-empty]", data.recent_events || []);
            } catch (error) {
                console.warn("[Edge Server] device history fetch failed:", error);
            }
        };

        const esRefreshHistory = async () => {
            await esRenderHistoryDevices();
            await esRefreshDeviceHistory();
        };

        const esRenderWatchlist = (selector, group) => {
            const wrap = edgeShell.querySelector(selector);
            if (!wrap) return;
            const common = [
                ["Device silent", "No data arrived after the device's normal interval", "learns normal gap, then alerts after long silence"],
                ["Slow sending", "Messages are arriving slower than usual", "last gap is much higher than learned normal"],
                ["Fast sending", "Messages are arriving much faster than usual", "last gap is much lower than learned normal"],
                ["Payload size changed", "Payload is much larger or smaller than normal", "compares latest payload with learned average"],
                ["Fields changed", "JSON field names changed", "compares current top-level fields with previous shape"],
                ["Bad payload", "Payload could not be parsed", "configured JSON/form parser failed"],
                ["Sequence missing", "Sequence number skipped forward", "device sequence jumps ahead"],
                ["Sequence reset", "Sequence counter restarted", "common after device reboot/reset"],
                ["Clock mismatch", "Device timestamp differs from gateway time", "device clock differs by more than 5 minutes"],
            ];
            const httpSpecific = [["Unknown path", "Device used an unconfigured URL", "no matching HTTP endpoint"], ["Auth failure", "Request failed authentication", "token or mTLS check failed"]];
            const mqttSpecific = [["MQTT disconnect", "Persistent MQTT session closed", "broker receives disconnect or socket closes"], ["Reconnect storm", "Client repeatedly reconnects", "4+ connects in 60 seconds"]];
            const protocolSpecific = group === "mqtt" ? mqttSpecific : group === "all" ? [...httpSpecific, ...mqttSpecific] : httpSpecific;
            wrap.innerHTML = [...common, ...protocolSpecific].map(([name, meaning, trigger]) => `
                <div class="es-watch-item">
                    <strong>${esEsc(name)}</strong>
                    <span>${esEsc(meaning)}</span>
                    <small>${esEsc(trigger)}</small>
                </div>
            `).join("");
        };

        const esRefreshProtocolMetrics = async (group) => {
            try {
                const params = new URLSearchParams({ minutes: String(esProtocolWindowMinutes(group)) });
                const response = await fetch(`/api/edge-server/${group}/metrics?${params.toString()}`);
                if (!response.ok) {
                    throw new Error(`${response.status} ${response.statusText}`);
                }
                const data = await response.json();
                await esApplyProtocolMetrics(group, data);
            } catch (error) {
                console.warn(`[Edge Server] ${group} metrics fetch failed:`, error);
                await esApplyProtocolMetrics(group, esEmptyProtocolMetrics(group));
            }
        };

        const esRefreshAlerts = async () => {
            try {
                await esRenderAlertDevices();
                const windowInfo = esAlertWindowInfo();
                const query = windowInfo.params.toString();
                const csv = edgeShell.querySelector("[data-es-alert-events-csv]");
                const jsonl = edgeShell.querySelector("[data-es-alert-events-jsonl]");
                if (csv) csv.setAttribute("href", `/api/edge-server/events.csv${query ? `?${query}` : ""}`);
                if (jsonl) jsonl.setAttribute("href", `/api/edge-server/events.jsonl${query ? `?${query}` : ""}`);
                const response = await fetch(`/api/edge-server/alerts?${windowInfo.params.toString()}`);
                const data = await response.json();
                const summary = data.summary || {};
                const events = data.events || [];
                esAlertEventsCache = events;
                if (esSelectedAlertIndex >= events.length) esSelectedAlertIndex = events.length ? 0 : -1;
                if (esSelectedAlertIndex < 0 && events.length) esSelectedAlertIndex = 0;
                esMergeAlertDeviceOptions(events);
                esRenderAlertDevicePills(events);
                esSetText("[data-es-alert-total]", Number(summary.total || 0).toLocaleString());
                esSetText("[data-es-alert-warning]", Number(summary.warning || 0).toLocaleString());
                esSetText("[data-es-alert-error]", Number(summary.error || 0).toLocaleString());
                esSetText("[data-es-alert-critical]", Number(summary.critical || 0).toLocaleString());
                esSetText("[data-es-alert-summary]", `${Number(summary.total || 0).toLocaleString()} alerts`);
                esSetText("[data-es-alert-window]", `${windowInfo.label} · ${Number(summary.total || 0).toLocaleString()} filtered alert${Number(summary.total || 0) === 1 ? "" : "s"}`);
                esSetText("[data-es-alert-timeline-caption]", `x - exact alert time inside ${windowInfo.label} · y - anomaly type · each dot is clickable`);
                esRenderTimelineChart("[data-es-alert-timeline-chart]", "[data-es-alert-timeline-empty]", events, esAlertTimelineOptions(windowInfo));
                esRenderTypeBars("[data-es-alert-type-summary]", "[data-es-alert-type-empty]", data.type_summary || []);
                esRenderAlertEvents("[data-es-alert-list]", "[data-es-alert-empty]", events);
                esRenderSelectedAlert();
                esRefreshOverviewVisuals();
            } catch (error) {
                console.warn("[Edge Server] alerts fetch failed:", error);
            }
        };

        const esNormaliseAlertFilterPair = (source) => {
            const groupSelect = edgeShell.querySelector("[data-es-alert-protocol-group]");
            const protocolSelect = edgeShell.querySelector("[data-es-alert-protocol]");
            const group = groupSelect?.value || "";
            const protocol = protocolSelect?.value || "";
            const protocolGroup = ["HTTP", "HTTPS"].includes(protocol) ? "http" : ["MQTT", "MQTTS"].includes(protocol) ? "mqtt" : "";
            if (source === "group" && protocol) {
                const matches = group === "" || group === protocolGroup;
                if (!matches && protocolSelect) protocolSelect.value = "";
            }
            if (source === "protocol" && protocolGroup && groupSelect) {
                groupSelect.value = protocolGroup;
            }
        };

        const esRefreshAlertsResetSelection = async () => {
            esSelectedAlertIndex = -1;
            await esRefreshAlerts();
        };

        const esRenderStorageStatus = (storage, fallbackRecords = 0) => {
            const info = storage || {};
            const maxSizeInput = edgeShell.querySelector("[data-es-max-size]");
            const configuredMb = Math.max(5120, Number(info.max_size_mb || maxSizeInput?.value || 5120));
            const usedBytes = Math.max(0, Number(info.db_size_bytes || 0));
            const usedMb = usedBytes / (1024 * 1024);
            const pct = configuredMb > 0 ? Math.min(100, Math.max(0, (usedMb / configuredMb) * 100)) : 0;
            const records = Number(info.message_count ?? fallbackRecords ?? 0);
            const backend = String(info.backend || "memory");
            const mode = backend === "memory"
                ? "Memory only"
                : backend === "sqlcipher"
                    ? "SQLCipher encrypted"
                    : "SQLite persistent";
            const encryption = backend === "sqlcipher" || info.encrypted
                ? "SQLCipher"
                : backend === "memory"
                    ? "Memory"
                    : "SQLite";

            esSetText("[data-es-storage-mode]", info.configured_enabled === false ? "Storage disabled" : mode);
            esSetText("[data-es-storage-used]", esFormatStoreBytes(usedBytes));
            esSetText("[data-es-storage-limit]", `${configuredMb.toLocaleString()} MiB`);
            esSetText("[data-es-storage-percent]", `${pct.toFixed(pct < 10 && pct > 0 ? 1 : 0)}%`);
            esSetText("[data-es-storage-records]", records.toLocaleString());
            esSetText("[data-es-storage-oldest]", info.oldest_record_at ? esFullTime(info.oldest_record_at) : "No records");
            esSetText("[data-es-storage-newest]", info.newest_record_at ? esFullTime(info.newest_record_at) : "No records");
            esSetText("[data-es-storage-encryption]", encryption);
            esSetText("[data-es-storage-path]", info.path ? `Database: ${info.path}` : "Database: in-memory fallback");

            const bar = edgeShell.querySelector("[data-es-storage-used-bar]");
            if (bar) bar.style.width = `${pct}%`;
            if (maxSizeInput && document.activeElement !== maxSizeInput) maxSizeInput.value = configuredMb;
        };

        const esRefreshStatus = async () => {
            try {
                const response = await fetch("/api/edge-server/status");
                const status = await response.json();
                const state = edgeShell.querySelector("[data-es-state]");
                const message = edgeShell.querySelector("[data-es-message]");
                const httpCount = edgeShell.querySelector("[data-es-http-count]");
                const mqttCount = edgeShell.querySelector("[data-es-mqtt-count]");
                const stored = edgeShell.querySelector("[data-es-stored]");
                const storageBackend = edgeShell.querySelector("[data-es-storage-backend]");
                if (state) state.textContent = status.state || "standby";
                if (message) message.textContent = status.message || "";
                if (httpCount) httpCount.textContent = status.active_http_endpoints ?? 0;
                if (mqttCount) mqttCount.textContent = status.active_mqtt_topics ?? 0;
                if (stored) stored.textContent = status.stored_records ?? 0;
                if (storageBackend) {
                    const storage = status.storage || {};
                    storageBackend.textContent = storage.backend === "memory"
                        ? "memory only"
                        : `${storage.backend || "storage"} ${storage.encrypted ? "encrypted" : "persistent"}`;
                }
                esRenderStorageStatus(status.storage || {}, status.stored_records || 0);

                const services = status.services || [];
                const listenerMap = status.listeners || {};
                const runningListeners = Object.entries(listenerMap)
                    .filter(([, item]) => item && item.state === "running")
                    .map(([name, item]) => {
                        const hosts = Array.isArray(item.bind_hosts) && item.bind_hosts.length
                            ? item.bind_hosts
                            : (item.bind_host ? String(item.bind_host).split(",").map((host) => host.trim()).filter(Boolean) : []);
                        return `${name.toUpperCase()} ${(hosts.length ? hosts.join(", ") : "selected interfaces")}:${item.port || ""}`;
                    });
                const waitingListeners = Object.entries(listenerMap)
                    .filter(([, item]) => item && item.enabled && item.state === "waiting")
                    .map(([name]) => `${name.toUpperCase()}: waiting for selected interface`);
                const listenerErrors = Object.entries(listenerMap)
                    .filter(([, item]) => item && item.error)
                    .map(([name, item]) => `${name.toUpperCase()}: ${item.error}`);
                const buffer = status.buffer || {};
                const audit = status.audit || {};
                const devices = status.devices || [];
                const statusTs = edgeShell.querySelector("[data-es-status-ts]");
                const liveServices = edgeShell.querySelector("[data-es-live-services]");
                const liveServicesDetail = edgeShell.querySelector("[data-es-live-services-detail]");
                const liveDevices = edgeShell.querySelector("[data-es-live-devices]");
                const liveBuffered = edgeShell.querySelector("[data-es-live-buffered]");
                const liveEvents = edgeShell.querySelector("[data-es-live-events]");
                if (statusTs) statusTs.textContent = status.timestamp_ms ? new Date(status.timestamp_ms).toLocaleTimeString() : "";
                if (liveServices) liveServices.textContent = services.length;
                if (liveServicesDetail) {
                    liveServicesDetail.textContent = runningListeners.length
                        ? runningListeners.join(", ")
                        : waitingListeners.length
                            ? waitingListeners[0]
                            : listenerErrors.length
                                ? listenerErrors[0]
                                : "No listeners enabled";
                }
                if (liveDevices) liveDevices.textContent = status.connected_devices ?? devices.length ?? 0;
                if (liveBuffered) liveBuffered.textContent = Number(status.stored_records || 0).toLocaleString();
                if (liveEvents) liveEvents.textContent = audit.total ?? 0;

                const accepted = Number(buffer.pending ?? status.stored_records ?? 0);
                const processed = Number(buffer.processed ?? accepted);
                const forwarded = Number(buffer.forwarded ?? 0);
                const dropped = Number(buffer.dropped ?? 0);
                const progressMax = Math.max(accepted, processed, forwarded, dropped, 1);
                esSetText("[data-es-buffer-pending]", accepted.toLocaleString());
                esSetText("[data-es-buffer-processed]", processed.toLocaleString());
                esSetText("[data-es-buffer-forwarded]", forwarded.toLocaleString());
                esSetText("[data-es-buffer-dropped]", dropped.toLocaleString());
                esSetProgress("[data-es-buffer-pending-bar]", accepted, progressMax);
                esSetProgress("[data-es-buffer-processed-bar]", processed, progressMax);
                esSetProgress("[data-es-buffer-forwarded-bar]", forwarded, progressMax);
                esSetProgress("[data-es-buffer-dropped-bar]", dropped, progressMax);

                const protocolCounts = devices.reduce((counts, device) => {
                    const protocol = String(device.protocol || "").toUpperCase();
                    if (protocol === "HTTP" || protocol === "HTTPS" || protocol === "MQTT" || protocol === "MQTTS") {
                        counts[protocol] = (counts[protocol] || 0) + 1;
                    }
                    return counts;
                }, { HTTP: 0, HTTPS: 0, MQTT: 0, MQTTS: 0 });
                esSetText("[data-es-conn-http]", protocolCounts.HTTP || 0);
                esSetText("[data-es-conn-https]", protocolCounts.HTTPS || 0);
                esSetText("[data-es-conn-mqtt]", protocolCounts.MQTT || 0);
                esSetText("[data-es-conn-mqtts]", protocolCounts.MQTTS || 0);
                esSetText("[data-es-device-count]", `${devices.length} device${devices.length === 1 ? "" : "s"}`);
                esSetText("[data-es-audit-summary]", `${audit.outages ?? 0} outages · ${audit.errors ?? 0} errors · ${audit.auth_failures ?? 0} auth failures`);

                const deviceList = edgeShell.querySelector("[data-es-device-list]");
                const deviceEmpty = edgeShell.querySelector("[data-es-device-empty]");
                if (deviceEmpty) deviceEmpty.classList.toggle("es-hidden", devices.length > 0);
                if (deviceList) {
                    deviceList.innerHTML = devices.slice(0, 4).map((device) => `
                        <div class="es-device-row es-device-row-health is-${esEsc(device.health || "active")}">
                            <strong>${esEsc(device.device_id || "unknown")}</strong>
                            <span>${esEsc(device.health_label || device.protocol || "Receiving")}</span>
                            <small>${esEsc(device.endpoint || device.topic || "")}</small>
                            <em>${esEsc(esAge(device.last_seen))}</em>
                        </div>
                    `).join("");
                }

                const events = audit.events || [];
                const auditList = edgeShell.querySelector("[data-es-audit-list]");
                const auditEmpty = edgeShell.querySelector("[data-es-audit-empty]");
                if (auditEmpty) auditEmpty.classList.toggle("es-hidden", events.length > 0);
                if (auditList) {
                    auditList.innerHTML = events.slice(0, 5).map((event) => esRenderAlertCard({
                        ...event,
                        event_type: event.event_type || event.type,
                        created_at: event.created_at || event.timestamp,
                        severity: event.severity || "warning",
                    }, true)).join("");
                }
            } catch (error) {
                console.warn("[Edge Server] status fetch failed:", error);
            }
        };

        edgeShell.querySelectorAll("[data-es-tab]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const tab = btn.getAttribute("data-es-tab");
                edgeShell.querySelectorAll("[data-es-tab]").forEach((item) => {
                    const current = item.getAttribute("data-es-tab") === tab;
                    item.classList.toggle("is-current", current);
                    item.setAttribute("aria-selected", current ? "true" : "false");
                });
                edgeShell.querySelectorAll("[data-es-panel]").forEach((panel) => {
                    panel.classList.toggle("is-hidden", panel.getAttribute("data-es-panel") !== tab);
                });
                if (tab === "history") {
                    esRefreshHistory();
                }
                if (tab === "http" || tab === "mqtt") {
                    esRefreshProtocolMetrics(tab);
                }
                if (tab === "alerts") {
                    esRefreshAlerts();
                }
                if (tab === "funnel") {
                    esRefreshFunnel();
                }
            });
        });

        edgeShell.querySelector("[data-es-history-device]")?.addEventListener("change", esRefreshDeviceHistory);
        edgeShell.querySelector("[data-es-history-protocol]")?.addEventListener("change", esRefreshDeviceHistory);
        edgeShell.querySelector("[data-es-history-range]")?.addEventListener("change", () => {
            esSetHistoryWindowControls();
            esRefreshDeviceHistory();
        });
        edgeShell.querySelector("[data-es-history-date]")?.addEventListener("change", esRefreshDeviceHistory);
        edgeShell.querySelector("[data-es-history-hour]")?.addEventListener("change", esRefreshDeviceHistory);
        edgeShell.querySelector("[data-es-history-refresh]")?.addEventListener("click", esRefreshHistory);
        edgeShell.querySelector("[data-es-alert-protocol-group]")?.addEventListener("change", () => {
            esNormaliseAlertFilterPair("group");
            esRefreshAlertsResetSelection();
        });
        edgeShell.querySelector("[data-es-alert-protocol]")?.addEventListener("change", () => {
            esNormaliseAlertFilterPair("protocol");
            esRefreshAlertsResetSelection();
        });
        edgeShell.querySelector("[data-es-alert-device]")?.addEventListener("change", esRefreshAlertsResetSelection);
        edgeShell.querySelector("[data-es-alert-range]")?.addEventListener("change", esRefreshAlertsResetSelection);
        edgeShell.querySelector("[data-es-alert-refresh]")?.addEventListener("click", esRefreshAlertsResetSelection);
        edgeShell.addEventListener("click", (event) => {
            const alertTarget = event.target?.closest?.("[data-es-alert-index]");
            if (alertTarget) {
                const index = Number(alertTarget.getAttribute("data-es-alert-index"));
                if (Number.isInteger(index) && index >= 0 && index < esAlertEventsCache.length) {
                    esSelectedAlertIndex = index;
                    esRenderTimelineChart("[data-es-alert-timeline-chart]", "[data-es-alert-timeline-empty]", esAlertEventsCache, esAlertTimelineOptions());
                    esRenderAlertEvents("[data-es-alert-list]", "[data-es-alert-empty]", esAlertEventsCache);
                    esRenderSelectedAlert();
                }
                return;
            }
            const pill = event.target?.closest?.("[data-es-alert-device-pill]");
            if (pill) {
                const select = edgeShell.querySelector("[data-es-alert-device]");
                if (select) select.value = pill.getAttribute("data-es-alert-device-pill") || "";
                esRefreshAlertsResetSelection();
            }
        });
        edgeShell.querySelector("[data-es-http-device-search]")?.addEventListener("input", (event) => {
            esHttpDeviceSearch = event.target?.value || "";
            esRenderProtocolDeviceOptions(esHttpMetricsCache?.devices || [], "http");
        });
        edgeShell.querySelector("[data-es-http-device-filter]")?.addEventListener("change", async () => {
            if (esHttpMetricsCache) {
                await esApplyProtocolMetrics("http", esHttpMetricsCache);
            }
        });
        edgeShell.querySelector("[data-es-mqtt-device-search]")?.addEventListener("input", (event) => {
            esMqttDeviceSearch = event.target?.value || "";
            esRenderProtocolDeviceOptions(esMqttMetricsCache?.devices || [], "mqtt");
        });
        edgeShell.querySelector("[data-es-mqtt-device-filter]")?.addEventListener("change", async () => {
            if (esMqttMetricsCache) {
                await esApplyProtocolMetrics("mqtt", esMqttMetricsCache);
            }
        });
        edgeShell.querySelectorAll("[data-es-protocol-window]").forEach((select) => {
            select.addEventListener("change", () => {
                const group = select.getAttribute("data-es-protocol-window");
                if (group === "http" || group === "mqtt") {
                    esRefreshProtocolMetrics(group);
                }
            });
        });
        edgeShell.querySelector("[data-es-funnel-enabled]")?.addEventListener("click", () => {
            esConfig = esConfig || esDefaultConfig();
            const funnel = esConfig.funnel || esDefaultConfig().funnel;
            funnel.enabled = !Boolean(funnel.enabled);
            esConfig.funnel = funnel;
            esSetToggle(edgeShell.querySelector("[data-es-funnel-enabled]"), funnel.enabled);
        });
        edgeShell.querySelector("[data-es-funnel-save]")?.addEventListener("click", esSaveFunnel);
        edgeShell.querySelector("[data-es-funnel-refresh]")?.addEventListener("click", esRefreshFunnel);

        edgeShell.querySelectorAll("[data-es-listener-enabled]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const key = btn.getAttribute("data-es-listener-enabled");
                esConfig.listeners[key].enabled = !esConfig.listeners[key].enabled;
                esSetToggle(btn, esConfig.listeners[key].enabled);
                await esSaveConfig();
            });
        });

        edgeShell.querySelectorAll("[data-es-bind-interface]").forEach((input) => {
            input.addEventListener("change", async () => {
                await esSaveConfig();
            });
        });

        edgeShell.querySelectorAll("[data-es-add-http]").forEach((btn) => btn.addEventListener("click", () => esShowHttpForm()));
        edgeShell.querySelector("[data-es-cancel-http]")?.addEventListener("click", esHideHttpForm);
        edgeShell.querySelector("[data-es-save-http]")?.addEventListener("click", async () => {
            const endpoint = esReadHttpForm();
            const list = esConfig.http_endpoints || [];
            const idx = list.findIndex((item) => item.id === endpoint.id);
            if (idx >= 0) list[idx] = { ...list[idx], ...endpoint };
            else list.push(endpoint);
            esConfig.http_endpoints = list;
            esHideHttpForm();
            esRenderHttp();
            await esSaveConfig();
        });

        edgeShell.querySelectorAll("[data-es-add-mqtt]").forEach((btn) => btn.addEventListener("click", () => esShowMqttForm()));
        edgeShell.querySelector("[data-es-cancel-mqtt]")?.addEventListener("click", esHideMqttForm);
        edgeShell.querySelector("[data-es-save-mqtt]")?.addEventListener("click", async () => {
            const topic = esReadMqttForm();
            const list = esConfig.mqtt_topics || [];
            const idx = list.findIndex((item) => item.id === topic.id);
            if (idx >= 0) list[idx] = { ...list[idx], ...topic };
            else list.push(topic);
            esConfig.mqtt_topics = list;
            esHideMqttForm();
            esRenderMqtt();
            await esSaveConfig();
        });

        edgeShell.addEventListener("click", async (event) => {
            const rawTarget = event.target;
            if (!(rawTarget instanceof HTMLElement)) return;
            const target = rawTarget.closest("[data-es-edit-http], [data-es-delete-http], [data-es-toggle-http], [data-es-edit-mqtt], [data-es-delete-mqtt], [data-es-toggle-mqtt]");
            if (!(target instanceof HTMLElement)) return;
            const httpEdit = target.getAttribute("data-es-edit-http");
            const httpDelete = target.getAttribute("data-es-delete-http");
            const httpToggle = target.getAttribute("data-es-toggle-http");
            const mqttEdit = target.getAttribute("data-es-edit-mqtt");
            const mqttDelete = target.getAttribute("data-es-delete-mqtt");
            const mqttToggle = target.getAttribute("data-es-toggle-mqtt");

            if (httpEdit) {
                esShowHttpForm(esConfig.http_endpoints.find((item) => item.id === httpEdit));
                return;
            }
            if (httpDelete) {
                esConfig.http_endpoints = esConfig.http_endpoints.filter((item) => item.id !== httpDelete);
                esRenderHttp();
                await esSaveConfig();
                await esRefreshProtocolMetrics("http");
                return;
            }
            if (httpToggle) {
                const item = esConfig.http_endpoints.find((row) => row.id === httpToggle);
                if (!item) return;
                item.enabled = !Boolean(item.enabled);
                esRenderHttp();
                await esSaveConfig();
                await esRefreshProtocolMetrics("http");
                return;
            }
            if (mqttEdit) {
                esShowMqttForm(esConfig.mqtt_topics.find((item) => item.id === mqttEdit));
                return;
            }
            if (mqttDelete) {
                esConfig.mqtt_topics = esConfig.mqtt_topics.filter((item) => item.id !== mqttDelete);
                esRenderMqtt();
                await esSaveConfig();
                await esRefreshProtocolMetrics("mqtt");
                return;
            }
            if (mqttToggle) {
                const item = esConfig.mqtt_topics.find((row) => row.id === mqttToggle);
                if (!item) return;
                item.enabled = !Boolean(item.enabled);
                esRenderMqtt();
                await esSaveConfig();
                await esRefreshProtocolMetrics("mqtt");
            }
        });

        document.querySelectorAll("[data-es-save]").forEach((btn) => btn.addEventListener("click", esSaveConfig));
        edgeShell.querySelector("[data-es-save-certs]")?.addEventListener("click", esSaveCertificates);

        const esRefreshAllRuntime = async () => {
            await esRefreshStatus();
            await esRefreshOverviewMetrics();
            await esRefreshProtocolMetrics("http");
            await esRefreshProtocolMetrics("mqtt");
            await esRefreshAlerts();
            await esRefreshHistory();
            await esRefreshFunnel();
        };

        esSetHistoryWindowControls();
        esLoad().then(esRefreshAllRuntime);
        window.setInterval(esRefreshStatus, 6000);
        window.setInterval(esRefreshOverviewMetrics, 8000);
        window.setInterval(() => esRefreshProtocolMetrics("http"), 8000);
        window.setInterval(() => esRefreshProtocolMetrics("mqtt"), 8000);
        window.setInterval(esRefreshAlerts, 10000);
        window.setInterval(esRefreshHistory, 30000);
        window.setInterval(esRefreshFunnel, 30000);
    }

});
