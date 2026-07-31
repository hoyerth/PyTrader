// chart/js/01_core.js
// Kern-Variablen, WebChannel-Bridge, Fenster-Fokus-Event & Fehlerbehandlung

window.onerror = function(m, s, l, c, e) {
    if (m === "Script error." && !s) return true;
    console.error(`[JS ERROR] ${m} | L${l}:${c}`);
    return true;
};

let chart = null, candleSeries = null, pyBridge = null, isUpdatingChart = false;
let currentTfInSeconds = 3600, lastClosePrice = null, activeTimer = null, countdownTimer = null;
let rawCandleData = [], currentSymbol = null, currentTimeframe = null;
let gridPriceLines = [], dayLinesSeries = [], _storedCircleMarkers = null;
let currentPriceLine = null, resizeTimeout = null;
let currentPrecision = 2;
let pendingRange = null;
let _updateId = 0;
let _continuousTimeMap = {};  // { cont_time: real_epoch } für tickMarkFormatter
let _continuousKeys = [];     // sortierte cont-Schlüssel für resolveRealTime()
// LWC v5: setMarkers() auf der Serie existiert nicht mehr – SeriesMarkers-Plugin verwenden
let seriesMarkersPlugin = null;

let isWindowActive = true;
let lastRenderedPrice = null;
let lastRenderedTop = null;
let lastFormattedPriceStr = "";
let lastFormattedTimeStr = "";

const TF_SECONDS_MAP = { 'M1': 60, 'M2': 120, 'M5': 300, 'M10': 600, 'M15': 900, 'M30': 1800, 'H1': 3600, 'H4': 14400, 'D1': 86400, 'W1': 604800, 'MN1': 2592000 };

// =============================================================================
// resolveRealTime(): kontinuierliche (Fake-)Zeit -> echte epoch
// WICHTIG: Bei unbekannten Werten (Padding-Ticks ausserhalb des Datensatzes)
// NIE die Fake-Zeit selbst zurueckgeben – sonst zeigt die Zeitachse
// irrefuehrende Labels (z. B. "30.7.26 23:58" an der Tagesgrenze, weil die
// Fake-Zeit der 00:59-Candle als Realzeit formatiert wird).
// Stattdessen wird der naechstgelegene bekannte Zeitpunkt verwendet.
// =============================================================================
function resolveRealTime(ts) {
    if (ts === null || ts === undefined || typeof ts !== 'number' || !isFinite(ts)) return ts;
    var direct = _continuousTimeMap[ts];
    if (direct !== undefined) return direct;
    if (_continuousKeys.length === 0) return ts;
    var n = _continuousKeys.length;
    if (ts <= _continuousKeys[0]) return _continuousTimeMap[_continuousKeys[0]];
    if (ts >= _continuousKeys[n - 1]) return _continuousTimeMap[_continuousKeys[n - 1]];
    var lo = 0, hi = n - 1;
    while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (_continuousKeys[mid] === ts) return _continuousTimeMap[_continuousKeys[mid]];
        if (_continuousKeys[mid] < ts) lo = mid + 1; else hi = mid - 1;
    }
    // hi = letzter Key < ts, lo = erster Key > ts
    var a = _continuousKeys[hi], b = _continuousKeys[lo];
    return (ts - a <= b - ts) ? _continuousTimeMap[a] : _continuousTimeMap[b];
}

if (typeof qt !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function(channel) {
        pyBridge = channel.objects.pyBridge;
    });
}

window.addEventListener('focus', () => { isWindowActive = true; if(lastClosePrice !== null) updateCountdownDisplay(); });
window.addEventListener('blur', () => { isWindowActive = false; });
document.addEventListener('visibilitychange', () => {
    isWindowActive = !document.hidden;
    if (isWindowActive && lastClosePrice !== null) updateCountdownDisplay();
});
