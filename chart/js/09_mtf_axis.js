// chart/js/09_mtf_axis.js
// Phase 21.03.11 (Bug 4) – TF-spezifische Achsen-Ticks
//
// Problem (User-Meldung): Bei M15 statt H1 zeigte die X-Achse weiterhin
// 12-Stunden-Blöcke – LWC v5 wählt die Tick-Dichte nur aus der Viewport-
// Breite, nicht aus dem gewählten Timeframe.
//
// Lösung: Ein Overlay-Layer (#mtf-axis-layer) rendert Zeit-Tick-Labels,
// die zum TF des Charts ausgerichtet sind (M15 -> 15-min-Marken, H1 ->
// 1h-Marken, darunter gröbere Stufen je nach Zoom). Die LWC-eigenen
// Intraday-Labels liefert der tickMarkFormatter (04_live_updates.js)
// zugunsten des Overlays zurück (Tagesgrenzen behalten das Datum).
//
// Abhängigkeiten: 02_time_utils.js (getBerlinParts, toReal, toCont),
// 01_core.js (chart, rawCandleData, currentTfInSeconds). Rein additiv,
// kein Umbau des Kern-Rendering-Pfads.

// =============================================================================
// Zustand
// =============================================================================
let _mtfAxis = {
    active: false,     // true = Intraday-TF (Overlay aktiv)
    tfSeconds: 0,      // Sekunden des aktuellen Chart-TF
};

//: Kleinstmöglicher Label-Abstand in Pixeln (gegen Überlappung).
const MTF_AXIS_MIN_LABEL_PX = 90;

//: "Schöne" absolute Schritt-Größen (Sekunden), aus denen je Zoom der
//: erste Wert >= gewünschtem Abstand gewählt wird.
const MTF_AXIS_STEPS = [
    60, 120, 300, 600, 900, 1800, 2700, 3600, 5400, 7200, 10800, 14400,
    21600, 43200, 86400, 3 * 86400, 7 * 86400, 30 * 86400, 365 * 86400,
];

// =============================================================================
// Container sicherstellen
// =============================================================================
function _mtfAxisContainer() {
    var c = document.getElementById('chart-container');
    if (!c) return null;
    var layer = document.getElementById('mtf-axis-layer');
    if (!layer) {
        layer = document.createElement('div');
        layer.id = 'mtf-axis-layer';
        layer.style.cssText =
            'position:absolute; left:0; right:0; bottom:0; height:22px;' +
            ' pointer-events:none; z-index:998; overflow:hidden;' +
            ' font-size:10px; color:#787B86; font-family:sans-serif;';
        c.appendChild(layer);
    }
    return layer;
}

// =============================================================================
// Render: TF-alignierte Tick-Labels über die Zeitachse legen
// =============================================================================
function mtfAxisRender() {
    var layer = _mtfAxisContainer();
    if (!layer) return;
    layer.innerHTML = '';

    if (!_mtfAxis.active || !chart || !rawCandleData ||
        rawCandleData.length === 0) {
        return;
    }
    var tfSec = _mtfAxis.tfSeconds;
    if (!tfSec || tfSec <= 0) return;

    var lr;
    try {
        lr = chart.timeScale().getVisibleLogicalRange();
    } catch (e) { return; }
    if (!lr || lr.from === null || lr.to === null) return;

    var fromIdx = Math.max(0, Math.floor(lr.from));
    var toIdx = Math.min(rawCandleData.length - 1, Math.ceil(lr.to));
    if (toIdx <= fromIdx) toIdx = fromIdx + 1;

    var fromReal = toReal(rawCandleData[fromIdx].time);
    var toRealTs = toReal(rawCandleData[toIdx].time);
    if (fromReal === undefined || toRealTs === undefined) return;

    var rangeSec = toRealTs - fromReal;
    if (rangeSec <= 0) return;

    var container = document.getElementById('chart-container');
    var totalPx = (container && container.clientWidth) || 800;
    var desired = rangeSec * MTF_AXIS_MIN_LABEL_PX / Math.max(1, totalPx);

    // Nächste "schöne" Schrittgröße >= gewünschtem Abstand. Dabei wird nur
    // ein Schritt gewählt, der ein Vielfaches des TF ist (Tick aligniert
    // auf TF-Grenzen). Ist das nicht möglich (sehr großer Zoom), fällt auf
    // den nächstgrößeren "schönen" Schritt zurück (dann zeigt LWC die
    // Datums-Labels selbst).
    var stepSec = null;
    for (var i = 0; i < MTF_AXIS_STEPS.length; i++) {
        var s = MTF_AXIS_STEPS[i];
        if (s >= desired) {
            stepSec = (s % tfSec === 0) ? s : null;
            if (stepSec) break;
        }
    }
    if (stepSec === null) {
        // Fallback: gröberer Schritt, der KEIN Vielfaches des TF ist – dann
        // trotzdem rendern (Tages-/Stunden-Marken), falls TF < 1 Tag.
        for (var k = 0; k < MTF_AXIS_STEPS.length; k++) {
            if (MTF_AXIS_STEPS[k] >= desired) { stepSec = MTF_AXIS_STEPS[k]; break; }
        }
    }
    if (stepSec === null) stepSec = 86400;
    if (stepSec >= 86400) return;  // LWC zeigt die Datums-Marken selbst

    var first = Math.ceil(fromReal / stepSec) * stepSec;
    for (var t = first; t <= toRealTs + stepSec / 2; t += stepSec) {
        var p = getBerlinParts(t);
        // Tagesgrenzen behält LWC (Datum) – hier überspringen (kein Duplikat).
        if (p.hour === '00' && p.minute === '00') continue;
        var cont = toCont(t);
        if (cont === undefined) continue;
        var x;
        try {
            x = chart.timeScale().timeToCoordinate(cont);
        } catch (e) { continue; }
        if (x === null || x === undefined || isNaN(x)) continue;
        var el = document.createElement('div');
        el.style.cssText =
            'position:absolute; top:4px; left:' + Math.round(x) + 'px;' +
            ' transform:translateX(-50%); white-space:nowrap;';
        el.innerText = p.hour + ':' + p.minute;
        layer.appendChild(el);
    }
}

// =============================================================================
// Externe API (04_live_updates.js ruft auf)
// =============================================================================
function mtfAxisSetTf(tfSeconds, active) {
    _mtfAxis.tfSeconds = (typeof tfSeconds === 'number') ? tfSeconds : 0;
    _mtfAxis.active = !!active;
    mtfAxisRender();
}

function mtfAxisClear() {
    _mtfAxis.active = false;
    _mtfAxis.tfSeconds = 0;
    var layer = document.getElementById('mtf-axis-layer');
    if (layer) {
        layer.innerHTML = '';
        layer.remove();
    }
}

//: Flag für den tickMarkFormatter (04): Intraday-Labels an das Overlay
//: abgeben (nur wenn das Overlay aktiv ist).
window._mtfAxisActive = false;

function _mtfAxisSyncWindowFlag() {
    window._mtfAxisActive = _mtfAxis.active;
    return _mtfAxis.active;
}

// In den Hook-Zyklus einhängen: nach Full-Update + nach Zoom/Range-Change.
// 04_live_updates.js ruft die optionalen Hooks auf – hier registrieren.
function _onMtfAxisFullUpdate(data) {
    if (data && typeof data.timeframe === 'string' &&
        TF_SECONDS_MAP && TF_SECONDS_MAP[data.timeframe]) {
        var tfSec = TF_SECONDS_MAP[data.timeframe];
        mtfAxisSetTf(tfSec, tfSec > 0 && tfSec < 86400);
    } else {
        mtfAxisSetTf(0, false);
    }
    _mtfAxisSyncWindowFlag();
}

function _onMtfAxisVisibleRangeChanged() {
    _mtfAxisSyncWindowFlag();
    mtfAxisRender();
}

// Kopplung: 04_live_updates.js ruft die dedizierten optionalen Hooks
// _onMtfAxisFullUpdate / _onMtfAxisVisibleRangeChanged auf (Muster
// 06_two_tier.js). Kein Konflikt mit den MTF-FC-Hooks von 07/08.
