// chart/js/07_mtf_fc.js
// Phase 21.03.08 – MTF-FC Chart-Integration (JS-Tier)
//
// Zuständigkeiten:
//   * Zoom-Hook: bei visibleRangeChanged werden die Viewport-Kanten
//     (reale Wanduhr-Epochs) debounced an Python geschickt
//     (pyBridge.onViewportChanged) -> Python bewertet die Kaskade (21.03.03)
//     und liefert {current_tf, candidate_tf} via Payload zurück.
//   * Puls-Breadcrumb: transparenter Badge `[ ⚡ Kerzen: M5 ]` oben rechts,
//     der bei TF-Umschaltung kurz hellblau aufleuchtet (§4 Säule 2.2).
//   * Boundary-UI: `ℹ️ M1 verfügbar ab DD.MM.JJJJ` sowie Fallback-Hinweis
//     "Keine M1-Rohdaten für diesen Zeitraum" (§4 Säule 1.3, 21.03.02).
//
// Dieses Modul wird NACH 04_live_updates.js geladen und hängt sich über die
// optionalen Hooks ein:
//   window._onMtfFcFullUpdate(data)        – State-Reset nach Full-Update
//   window._onMtfFcVisibleRangeChanged()   – Kaskaden-Trigger (Zoom)
// (04_live_updates.js ruft beide optional auf – Muster 06_two_tier.js.)

// =============================================================================
// Zustand
// =============================================================================
let _mtfFc = {
    activeChartTf: null,       // aktueller Chart-TF (aus Python-Payload)
    lastChartTf: null,         // vorheriger Chart-TF (Breadcrumb-Detection)
    transitionStartedAt: 0,    // Transition Guard (Zeitstempel der letzten Schaltung)
    rangeDays: 0,
    historyBoundaries: null,   // { m1AvailableFrom, coverageStatus, sourceTf }
    breadcrumbTimer: null,
    viewportTimer: null,       // Debounce-Timer für Kaskaden-Trigger
};

const MTF_FC_VIEWPORT_DEBOUNCE_MS = 150;  // JS-Debounce für Zoom-Hook
const MTF_FC_BREADCRUMB_MS = 1500;        // Puls-Dauer des Breadcrumbs

// =============================================================================
// Helper: Viewport-Epochs aus der logischen Range
// =============================================================================
function _mtfFcComputeViewportEpochs() {
    if (!chart || !rawCandleData || rawCandleData.length === 0) return null;
    try {
        var lr = chart.timeScale().getVisibleLogicalRange();
        if (!lr || lr.from === null || lr.to === null) return null;
        var fromIdx = Math.max(0, Math.floor(lr.from));
        var toIdx = Math.min(rawCandleData.length - 1, Math.floor(lr.to));
        if (toIdx < fromIdx) return null;
        var fromEpoch = toReal(rawCandleData[fromIdx].time);
        var toEpoch = toReal(rawCandleData[toIdx].time);
        if (fromEpoch === undefined || toEpoch === undefined) return null;
        return { from: fromEpoch, to: toEpoch };
    } catch (e) {
        return null;
    }
}

// =============================================================================
// Puls-Breadcrumb (§4 Säule 2.2)
// =============================================================================
function _mtfFcEnsureBreadcrumb() {
    var el = document.getElementById('mtf-fc-breadcrumb');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'mtf-fc-breadcrumb';
    el.style.cssText =
        'position:absolute; top:4px; right:70px; background:rgba(41,98,255,0.15);' +
        ' border:1px solid #2962FF; color:#d1d4dc; font-size:11px; font-weight:bold;' +
        ' padding:2px 8px; border-radius:3px; z-index:1001; pointer-events:none;' +
        ' opacity:0; transition:opacity 0.25s;';
    document.getElementById('chart-container').appendChild(el);
    return el;
}

function _mtfFcShowBreadcrumb(text) {
    var el = _mtfFcEnsureBreadcrumb();
    el.innerText = text;
    el.style.opacity = '1';
    if (_mtfFc.breadcrumbTimer) clearTimeout(_mtfFc.breadcrumbTimer);
    _mtfFc.breadcrumbTimer = setTimeout(function() {
        el.style.opacity = '0';
    }, MTF_FC_BREADCRUMB_MS);
}

// =============================================================================
// Boundary-UI (§4 Säule 1.3): ℹ️ M1 verfügbar ab + Fallback-Hinweis
// =============================================================================
function _mtfFcUpdateBoundaryInfo() {
    var hb = _mtfFc.historyBoundaries || {};
    var fallback = (hb.coverageStatus === 'fallback');
    var srcTf = hb.sourceTf || 'H1';

    // Fallback-Schraffur-Hinweis (keine Lücke, kein Absturz)
    var el = document.getElementById('mtf-fc-boundary-info');
    if (fallback) {
        if (!el) {
            el = document.createElement('div');
            el.id = 'mtf-fc-boundary-info';
            el.style.cssText =
                'position:absolute; left:8px; bottom:8px;' +
                ' background:rgba(242,54,69,0.15); border:1px solid #F23645;' +
                ' color:#d1d4dc; font-size:11px; padding:3px 8px;' +
                ' border-radius:3px; z-index:1000; pointer-events:none;';
            document.getElementById('chart-container').appendChild(el);
        }
        el.style.display = 'block';
        el.innerText = '⚠️ Keine M1-Rohdaten für diesen Zeitraum (' + srcTf + '-Fallback)';
    } else if (el) {
        el.style.display = 'none';
    }

    // ℹ️ M1 verfügbar ab DD.MM.JJJJ
    var info2 = document.getElementById('mtf-fc-m1-available');
    var from = hb.m1AvailableFrom;
    if (typeof from === 'number' && !isNaN(from)) {
        if (!info2) {
            info2 = document.createElement('div');
            info2.id = 'mtf-fc-m1-available';
            info2.style.cssText =
                'position:absolute; left:8px; top:4px;' +
                ' background:rgba(41,98,255,0.12); border:1px solid #2962FF;' +
                ' color:#d1d4dc; font-size:11px; padding:2px 8px;' +
                ' border-radius:3px; z-index:1000; pointer-events:none;';
            document.getElementById('chart-container').appendChild(info2);
        }
        var p = getBerlinParts(from);
        info2.style.display = 'block';
        info2.innerText = 'ℹ️ M1 verfügbar ab ' + p.day + '.' + p.month + '.' + p.year;
    } else if (info2) {
        info2.style.display = 'none';
    }
}

// =============================================================================
// Kaskaden-Trigger (Zoom-Hook)
// =============================================================================
function _mtfFcTriggerCascade() {
    if (!pyBridge || !pyBridge.onViewportChanged) return;
    if (isUpdatingChart) return;
    var vp = _mtfFcComputeViewportEpochs();
    if (!vp) return;
    if (_mtfFc.viewportTimer) clearTimeout(_mtfFc.viewportTimer);
    var from = Math.floor(vp.from);
    var to = Math.floor(vp.to);
    _mtfFc.viewportTimer = setTimeout(function() {
        _mtfFc.viewportTimer = null;
        try {
            pyBridge.onViewportChanged(from, to);
        } catch (e) {}
    }, MTF_FC_VIEWPORT_DEBOUNCE_MS);
}

// =============================================================================
// Hooks (04_live_updates.js ruft optional auf)
// =============================================================================
function _onMtfFcFullUpdate(data) {
    var st = (data && data.mtfFcState) ? data.mtfFcState : {};
    _mtfFc.historyBoundaries = st.historyBoundaries || null;
    if (st.activeChartTf) {
        _mtfFc.activeChartTf = st.activeChartTf;
        if (_mtfFc.lastChartTf && _mtfFc.lastChartTf !== st.activeChartTf) {
            _mtfFcShowBreadcrumb('⚡ Kerzen: ' + st.activeChartTf);
        }
        _mtfFc.lastChartTf = st.activeChartTf;
    }
    if (st.transitionStartedAt) {
        _mtfFc.transitionStartedAt = st.transitionStartedAt;
    }
    _mtfFcUpdateBoundaryInfo();
}

function _onMtfFcVisibleRangeChanged() {
    _mtfFcTriggerCascade();
}

// =============================================================================
// Externe API (Python -> JS via runJavaScript)
// =============================================================================
function applyMtfFcCascade(payload) {
    // Python liefert {current_tf, candidate_tf, direction, range_days}
    // nach einer Kaskaden-Entscheidung (Breadcrumb + State-Sync).
    if (!payload || typeof payload !== 'object') return;
    if (payload.current_tf && payload.current_tf !== _mtfFc.activeChartTf) {
        _mtfFc.activeChartTf = payload.current_tf;
        _mtfFcShowBreadcrumb('⚡ Kerzen: ' + payload.current_tf);
    }
    if (payload.rangeDays !== undefined) {
        _mtfFc.rangeDays = payload.rangeDays;
    }
    if (payload.transitionStartedAt) {
        _mtfFc.transitionStartedAt = payload.transitionStartedAt;
    }
}

// Viewport auf ein Range-Preset setzen (Python -> JS, 21.03.07).
function _mtfFcApplyRange(fromEpoch, toEpoch) {
    if (!chart || !rawCandleData || rawCandleData.length === 0) return;
    try {
        var fromIdx = -1, toIdx = -1;
        for (var i = 0; i < rawCandleData.length; i++) {
            var real = toReal(rawCandleData[i].time);
            if (real === undefined) continue;
            if (fromIdx < 0 && real >= fromEpoch) fromIdx = i;
            if (real <= toEpoch) toIdx = i;
        }
        if (fromIdx < 0) fromIdx = 0;
        if (toIdx < fromIdx) toIdx = rawCandleData.length - 1;
        chart.timeScale().setVisibleLogicalRange({ from: fromIdx, to: toIdx });
    } catch (e) {}
}
