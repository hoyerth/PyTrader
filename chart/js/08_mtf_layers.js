// chart/js/08_mtf_layers.js
// Phase 21.03.09 – Interaktives Layering: TF-Badges & Geister-Marker
//
// Zuständigkeiten (§4 Säule 3):
//   * Interaktive TF-Badges (z. B. `[ H4-Swing ]`): Klick filtert die
//     aktuelle Ansicht synchron auf diesen Timeframe; Strg+Klick = Multi-
//     Select. Badge-Klicks werden an Python gereicht
//     (pyBridge.onBadgeClick(tf, ctrlKey)).
//   * Geister-Marker (Off-Screen Level): übergeordnete Level außerhalb des
//     Zoom-Blicks werden am Rand des Viewports als verblasster Pfeil
//     gerendert (`▲ D1-Widerstand (27.85)`). Klick löst den Guard-Override
//     aus (pyBridge.onGhostMarkerClick(price, targetTf)) und animiert den
//     Viewport sanft zum Ziel-Level.
//   * Reset-Badge `[ 🌐 Data-TF gelockert ]`: Klick auf *Reset* stellt
//     previous_data_tf wieder her (pyBridge.onGuardOverrideReset()).
//
// Verhalten defensiv: Fehlende Elemente/pyBridge werden abgefangen
// (kein Chart-Abbruch).

// =============================================================================
// Konstanten & Zustand
// =============================================================================
let _mtfLayers = {
    badges: [],            // [{tf, label, active}]
    ghostMarkers: [],      // [{price, tf, label, side}]
    overrideActive: false,
    overrideTargetTf: null,
    animFrame: null,
    animStart: null,
};

const MTF_GHOST_ANIMATION_MS = 400;  // sanfte Viewport-Animation

// =============================================================================
// Container sicherstellen
// =============================================================================
function _mtfLayersEnsureContainer() {
    var c = document.getElementById('chart-container');
    if (!c) return null;
    var layer = document.getElementById('mtf-layers-layer');
    if (!layer) {
        layer = document.createElement('div');
        layer.id = 'mtf-layers-layer';
        layer.style.cssText =
            'position:absolute; left:0; top:0; right:0; bottom:0;' +
            ' pointer-events:none; z-index:1002; overflow:hidden;';
        c.appendChild(layer);
    }
    return layer;
}

// =============================================================================
// TF-Badges
// =============================================================================
function _mtfLayersRenderBadges() {
    var layer = _mtfLayersEnsureContainer();
    if (!layer) return;
    var old = layer.querySelectorAll('.mtf-tf-badge');
    for (var i = 0; i < old.length; i++) old[i].remove();

    if (!_mtfLayers.badges || _mtfLayers.badges.length === 0) return;
    var wrap = document.createElement('div');
    wrap.className = 'mtf-tf-badge-wrap';
    wrap.style.cssText =
        'position:absolute; left:8px; top:28px; display:flex; gap:4px;' +
        ' pointer-events:auto; z-index:1003; flex-wrap:wrap; max-width:70%;';

    for (var b = 0; b < _mtfLayers.badges.length; b++) {
        (function(badge) {
            var btn = document.createElement('button');
            btn.className = 'mtf-tf-badge';
            btn.innerText = badge.label || ('[' + badge.tf + ']');
            btn.title = (badge.active ? 'Aktiv – Klick: Filter' : 'Klick: Filter auf ' + badge.tf)
                + ' | Strg+Klick: Multi-Select';
            var activeStyle = badge.active
                ? 'background:rgba(41,98,255,0.35); border:1px solid #2962FF;'
                : 'background:rgba(30,34,45,0.8); border:1px solid #3d4450;';
            btn.style.cssText = activeStyle +
                ' color:#d1d4dc; font-size:11px; font-weight:bold;' +
                ' padding:2px 8px; border-radius:3px; cursor:pointer;';
            btn.addEventListener('click', function(ev) {
                try {
                    if (pyBridge && pyBridge.onBadgeClick) {
                        pyBridge.onBadgeClick(badge.tf, !!(ev.ctrlKey || ev.metaKey));
                    }
                } catch (e) {}
            });
            wrap.appendChild(btn);
        })(_mtfLayers.badges[b]);
    }
    layer.appendChild(wrap);

    // Reset-Badge bei aktivem Temporary Override
    if (_mtfLayers.overrideActive) {
        var resetBtn = document.createElement('button');
        resetBtn.className = 'mtf-tf-badge';
        resetBtn.innerText = '🌐 Data-TF gelockert auf ' +
            (_mtfLayers.overrideTargetTf || '?') + ' | Reset';
        resetBtn.style.cssText =
            'background:rgba(255,152,0,0.25); border:1px solid #FF9800;' +
            ' color:#d1d4dc; font-size:11px; font-weight:bold;' +
            ' padding:2px 8px; border-radius:3px; cursor:pointer;' +
            ' pointer-events:auto;';
        resetBtn.addEventListener('click', function() {
            try {
                if (pyBridge && pyBridge.onGuardOverrideReset) pyBridge.onGuardOverrideReset();
            } catch (e) {}
        });
        // Unter den TF-Badges positionieren
        var wrap2 = document.createElement('div');
        wrap2.className = 'mtf-tf-badge-wrap';
        wrap2.style.cssText = wrap.style.cssText + ' top:52px;';
        wrap2.appendChild(resetBtn);
        layer.appendChild(wrap2);
    }
}

// =============================================================================
// Geister-Marker (Off-Screen Level)
// =============================================================================
function _mtfLayersRenderGhostMarkers() {
    var layer = _mtfLayersEnsureContainer();
    if (!layer) return;
    var old = layer.querySelectorAll('.mtf-ghost-marker');
    for (var i = 0; i < old.length; i++) old[i].remove();

    if (!_mtfLayers.ghostMarkers || _mtfLayers.ghostMarkers.length === 0 || !candleSeries) return;

    for (var m = 0; m < _mtfLayers.ghostMarkers.length; m++) {
        (function(marker) {
            var y = candleSeries.priceToCoordinate(marker.price);
            if (y === null || y === undefined || isNaN(y)) return;
            var x = (marker.side === 'left') ? 2 : (layer.clientWidth - 26);
            var el = document.createElement('div');
            el.className = 'mtf-ghost-marker';
            el.style.cssText =
                'position:absolute; left:' + x + 'px; top:' + Math.round(y - 10) + 'px;' +
                ' background:rgba(30,34,45,0.6); border:1px solid #787B86;' +
                ' color:#b2b5be; font-size:10px; padding:1px 5px; border-radius:3px;' +
                ' opacity:0.55; cursor:pointer; pointer-events:auto; white-space:nowrap;';
            el.innerText = (marker.side === 'left' ? '◀ ' : '▲ ') +
                (marker.label || (marker.tf + '-Level')) + ' (' +
                marker.price.toFixed(2) + ')';
            el.addEventListener('click', function() {
                try {
                    if (pyBridge && pyBridge.onGhostMarkerClick) {
                        pyBridge.onGhostMarkerClick(marker.price, marker.tf || 'D1');
                    }
                } catch (e) {}
            });
            layer.appendChild(el);
        })(_mtfLayers.ghostMarkers[m]);
    }
}

// Sanfte Viewport-Animation zum Ziel-Level (Preis-/Zeitkoordinaten)
function animateToGhostLevel(price, targetTf) {
    if (!chart || !candleSeries) return;
    _mtfLayers.animStart = null;
    if (_mtfLayers.animFrame) cancelAnimationFrame(_mtfLayers.animFrame);

    function step(ts) {
        if (!_mtfLayers.animStart) _mtfLayers.animStart = ts;
        var progress = Math.min(1.0, (ts - _mtfLayers.animStart) / MTF_GHOST_ANIMATION_MS);
        var eased = progress < 0.5 ? 2 * progress * progress : 1 - Math.pow(-2 * progress + 2, 2) / 2;
        try {
            var lr = chart.timeScale().getVisibleLogicalRange();
            if (!lr) return;
            var target = candleSeries.coordinateToPrice(50);  // Ziel-Preisbereich Mitte
            if (target !== null && target !== undefined) {
                chart.priceScale('right').setVisibleRange({
                    from: price - Math.abs(price - target) * (1 - eased) - 1,
                    to: price + Math.abs(price - target) * (1 - eased) + 1,
                });
            }
        } catch (e) {}
        if (progress < 1.0) {
            _mtfLayers.animFrame = requestAnimationFrame(step);
        } else {
            _mtfLayers.animFrame = null;
        }
    }
    _mtfLayers.animFrame = requestAnimationFrame(step);
}

// =============================================================================
// Externe API (Python -> JS via runJavaScript)
// =============================================================================
function renderMtfLayers(payload) {
    // payload: { badges: [{tf,label,active}], ghostMarkers: [{price,tf,label,side}],
    //            overrideActive: bool, overrideTargetTf: str }
    if (!payload || typeof payload !== 'object') return;
    if (Array.isArray(payload.badges)) _mtfLayers.badges = payload.badges;
    if (Array.isArray(payload.ghostMarkers)) _mtfLayers.ghostMarkers = payload.ghostMarkers;
    if (typeof payload.overrideActive === 'boolean') _mtfLayers.overrideActive = payload.overrideActive;
    if (payload.overrideTargetTf) _mtfLayers.overrideTargetTf = payload.overrideTargetTf;
    _mtfLayersRenderBadges();
    _mtfLayersRenderGhostMarkers();
}

function clearMtfLayers() {
    _mtfLayers.badges = [];
    _mtfLayers.ghostMarkers = [];
    _mtfLayers.overrideActive = false;
    _mtfLayers.overrideTargetTf = null;
    var layer = document.getElementById('mtf-layers-layer');
    if (layer) {
        layer.innerHTML = '';
        layer.remove();
    }
}

// =============================================================================
// Full-Update-Hook: Layer auf bekannten State zurücksetzen (Muster 06)
// =============================================================================
function _onMtfLayersFullUpdate(data) {
    var st = (data && data.mtfFcState) ? data.mtfFcState : {};
    _mtfLayers.overrideActive = !!(st.temporaryGuardOverride &&
        st.temporaryGuardOverride.active);
    _mtfLayers.overrideTargetTf = (st.temporaryGuardOverride &&
        st.temporaryGuardOverride.targetTf) || null;
    _mtfLayersRenderBadges();
}
