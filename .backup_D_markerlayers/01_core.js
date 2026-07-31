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
let gridPriceLines = [], dayLinesSeries = [], _storedCircleMarkers = [];
let currentPriceLine = null, resizeTimeout = null;
let currentPrecision = 2;
let pendingRange = null;
let _updateId = 0;
let _lastAppliedUpdateId = 0; // höchste akzeptierte updateId (Race-Guard)
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
// HINWEIS: TF_SECONDS_MAP wird bei jedem applyFullChartUpdate durch die von
// Python mitgelieferte tfSecondsMap (Single Source of Truth) überschrieben.
// Diese lokale Map ist nur der Offline-/Start-Default (Abwärtskompatibilität).

// HINWEIS: resolveRealTime()/toReal()/toCont()/_rebuildTimeMaps() sind nach
// 02_time_utils.js verschoben – das ist die EINZIGE Zeit-Mapping-Schnittstelle.

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
