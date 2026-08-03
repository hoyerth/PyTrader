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
let gridPriceLines = [], dayLinesSeries = [];
// Proximity-Circles: je Level-Preis eine unsichtbare LineSeries (Datenpunkte
// exakt auf dem Level) + SeriesMarkers-Plugin -> Circles liegen auf den
// Liq-Lines statt auf der Bar (native Engine-Positionierung, kein CSS-Overlay).
let _circleSeries = [], _circleMarkerPlugins = [];
// P14-03-E: Circle-Cache für Merged-Render (historische + Live-Circles).
// Wird in applyFullChartUpdate() aus data.gridCircles befüllt; applyLiveOverlays()
// ersetzt nur die Live-Zeit-Einträge und rendert den Cache neu.
let _gridCirclesCache = [];
// P14-03-E (Flacker-Fix): Level-Registry für INKREMENTELLES Circle-Rendering.
// renderGridCircles() aktualisiert nur veränderte Level per setData/setMarkers,
// statt alle Serien via removeSeries/addSeries zu entfernen und neu aufzubauen –
// dieser Full-Layer-Rebuild pro Live-Tick (sobald die Proximity-Bedingung erfüllt
// war) verursachte das Live-Flackern. Schluessel = String(c.price).
let _circleLevelSeries = {};
// P14-03-E (Flacker-Fix): Change-Detection für Live-Circles. Identische Circle-
// Sets zwischen Ticks (gleiche Level-Hits, gleiche Farbe) lösen KEINEN Re-Render
// aus – sonst re-rendert jeder Tick mit erfüllter Bedingung den ganzen Layer.
let _lastLiveCirclesJson = '[]';
// P14-03-E (Flacker-Fix): Live-Zeit der letzten Live-Overlay-Anwendung. Beim
// Wechsel auf eine neue Live-Bar werden auch die Kreise der VORHERIGEN Live-Zeit
// aus dem Cache entfernt (sonst bleiben veraltete Live-Kreise der Vor-Bar bis zum
// Refresh sichtbar). Wird in applyFullChartUpdate auf null zurückgesetzt.
let _lastLiveOverlayTime = null;
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
