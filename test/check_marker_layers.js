// test/check_marker_layers.js
// Regressionstest: Signal-Marker und Grid-Circles sind getrennte Layer.
// - Signal-Marker gehen in das SeriesMarkers-Plugin der candleSeries.
// - Proximity-Circles werden auf der ZUGEHOERIGEN LIQ-LINE geplottet:
//   Je Level-Preis wird eine UNSICHTBARE LineSeries erzeugt, deren Datenpunkt
//   exakt auf dem Level-Preis liegt; die Circle-Marker (shape 'circle',
//   position 'inBar') haengen an dieser Serie -> die Engine positioniert sie
//   direkt auf der Liq-Line (native, folgt Zoom/Scroll, kein Redraw-Bug).
// Ein Grid-Render darf die EMA-Signale nie verdrängen (Bug: "EMA-Signale
// verschwinden bei Grid an").
//
// Laedt die ECHTE 03_chart_rendering.js mit Mock-Objekten (kein DOM/Chart).
const fs = require('fs');
const path = require('path');

const rendering = fs.readFileSync(path.join(__dirname, '..', 'chart', 'js', '03_chart_rendering.js'), 'utf8');

// --- Mock-Umgebung ---
let pluginMarkers = [];        // Marker auf der candleSeries (NUR Signale)
let circleSeriesList = [];     // unsichtbare Level-Serien der Circles
let removedSeries = [];

global._circleSeries = [];     // in 01_core.js deklariert (nicht in 03 geladen)
global._circleMarkerPlugins = [];
global.seriesMarkersPlugin = {
    setMarkers: (markers) => { pluginMarkers = markers || []; },
};
global.chart = {
    addSeries: (type, options) => {
        const s = {
            type: type,
            options: options,
            data: [],
            markers: [],
            setData: (d) => { s.data = d; },
        };
        circleSeriesList.push(s);
        return s;
    },
    removeSeries: (s) => {
        const i = circleSeriesList.indexOf(s);
        if (i >= 0) circleSeriesList.splice(i, 1);
        removedSeries.push(s);
    },
};
global.candleSeries = { removePriceLine: () => {}, createPriceLine: () => ({}) };
global.LightweightCharts = {
    LineSeries: 'LineSeries',
    CandlestickSeries: 'CandlestickSeries',
    createSeriesMarkers: (series, initial) => ({
        setMarkers: (m) => { series.markers = m || []; },
    }),
};
global.document = {
    getElementById: () => null, // DaySeparator wird nur definiert, nicht genutzt
    createElement: () => ({ style: {} }),
};
global.toReal = (t) => t;
global.SECONDS_PER_DAY = 86400;
global.WEEKEND_GAP_SECONDS = 43200;
global.MIN_SEPARATOR_SPACING_SECONDS = 21600;
global.currentTfInSeconds = 3600;

// candleSeries-Setup fuer _applyAllMarkers (echte Funktion in 03 benutzt
// LightweightCharts.createSeriesMarkers(candleSeries, []))
eval(rendering);

let failures = 0;
function check(label, cond, extra) {
    if (cond) {
        console.log('OK   ' + label + (extra ? ' -> ' + extra : ''));
    } else {
        failures++;
        console.error('FAIL ' + label);
    }
}
function signalShapes() {
    return pluginMarkers.map(m => m.time + ':' + m.shape);
}
function hasSignal(shape) {
    return pluginMarkers.some(m => m.shape === shape);
}
// Alle Circle-Marker ueber alle Level-Serien
function allCircleMarkers() {
    const out = [];
    for (const s of circleSeriesList) {
        for (const m of (s.markers || [])) out.push(m);
    }
    return out;
}
function hasCircleTime(t) {
    return allCircleMarkers().some(m => m.time === t);
}
function levelSeriesCount() {
    return circleSeriesList.length;
}

console.log('=== Marker-Layer: Signale (candleSeries) + Circles (Level-Serien) getrennt ===');

// --- Szenario 1: Signal an, Grid an -> EMA auf candleSeries, Circles auf Level-Serien ---
renderSignalMarkers([{ time: 1001, shape: 'square', position: 'aboveBar', color: '#FF9800' }, { time: 1002, shape: 'square' }]);
renderGridCircles([{ time: 1003, price: 30.5 }, { time: 1004, price: 31.0 }]);
check('Signal an + Grid an -> Signale sichtbar', hasSignal('square'), JSON.stringify(signalShapes()));
check('Circles NICHT im Signal-Marker-Plugin', !hasSignal('circle'), JSON.stringify(signalShapes()));
check('Circles -> 2 Level-Serien', levelSeriesCount() === 2, 'serien=' + levelSeriesCount());
// Serie fuer Level 30.5 hat Datenpunkt exakt auf dem Level -> Circle auf der Liq-Line
const s30 = circleSeriesList.find(s => (s.data[0] || {}).value === 30.5);
check('Level 30.5: Datenpunkt (time=1003, value=30.5)', s30 && s30.data.length === 1 && s30.data[0].time === 1003 && s30.data[0].value === 30.5, JSON.stringify(s30 && s30.data));
check('Level 30.5: Circle-Marker (inBar, size 1)', s30 && s30.markers[0] && s30.markers[0].position === 'inBar' && s30.markers[0].size === 1, JSON.stringify(s30 && s30.markers[0]));
check('Level 30.5: LineSeries unsichtbar (lineVisible:false)', s30 && s30.options.lineVisible === false, '');
check('Level 30.5: priceScaleId=right', s30 && s30.options.priceScaleId === 'right', '');
check('Level 30.5: autoscaleInfoProvider -> null', s30 && typeof s30.options.autoscaleInfoProvider === 'function' && s30.options.autoscaleInfoProvider() === null, '');

// --- Szenario 2: Grid render_indicators (clearGridCircles + renderGridCircles) ---
clearGridCircles();
check('clearGridCircles -> Level-Serien entfernt', levelSeriesCount() === 0, 'serien=' + levelSeriesCount());
check('clearGridCircles -> Signale bleiben', hasSignal('square'), JSON.stringify(signalShapes()));
renderGridCircles([{ time: 1005, price: 30.0 }]);
check('renderGridCircles -> neue Level-Serie', levelSeriesCount() === 1, 'serien=' + levelSeriesCount());
check('renderGridCircles -> Circle aktualisiert', hasCircleTime(1005), JSON.stringify(allCircleMarkers().map(m => m.time)));

// --- Szenario 3: Signal AUS (renderSignalMarkers([])) + Grid an -> NUR Circles ---
renderSignalMarkers([]);
check('Signal AUS -> keine Signale', !hasSignal('square'), JSON.stringify(signalShapes()));
check('Signal AUS -> Circles da', hasCircleTime(1005), JSON.stringify(allCircleMarkers().map(m => m.time)));

// --- Szenario 4: Grid AUS (clearGridCircles) bei aktiven Signalen -> EMA bleibt ---
renderSignalMarkers([{ time: 1007, shape: 'square' }]);
renderGridCircles([{ time: 1008, price: 30.0 }]);
clearGridCircles();
check('Grid AUS -> EMA bleibt', hasSignal('square'), JSON.stringify(signalShapes()));
check('Grid AUS -> Circles weg', levelSeriesCount() === 0, 'serien=' + levelSeriesCount());

// --- Szenario 5: clearSignalMarkers leert Signale, Circles bleiben ---
renderSignalMarkers([{ time: 1009, shape: 'square' }]);
renderGridCircles([{ time: 1010, price: 30.0 }]);
clearSignalMarkers();
check('clearSignalMarkers -> Signale weg', !hasSignal('square'), JSON.stringify(signalShapes()));
check('clearSignalMarkers -> Circles bleiben', hasCircleTime(1010), JSON.stringify(allCircleMarkers().map(m => m.time)));

// --- Szenario 6: reapplySignalMarkers kombiniert aus Caches ---
renderSignalMarkers([{ time: 1011, shape: 'square' }]);
renderGridCircles([{ time: 1012, price: 30.0 }]);
clearSignalMarkers();
renderSignalMarkers([{ time: 1011, shape: 'square' }]);
check('reapplySignalMarkers -> Signale + Circles', hasSignal('square') && hasCircleTime(1012), JSON.stringify(signalShapes()) + ' / ' + JSON.stringify(allCircleMarkers().map(m => m.time)));

console.log('\n=== Sortierung (gleiches Level, mehrere Circles) ===');
// LWC v5: Serie & Markers brauchen NACH ZEIT SORTIERTE Daten.
renderGridCircles([
    { time: 2003, price: 30.0 },
    { time: 2001, price: 30.0 },
    { time: 2002, price: 30.0 },
]);
const sLevel = circleSeriesList[0];
check('1 Level-Serie fuer gleichen Preis', levelSeriesCount() === 1, 'serien=' + levelSeriesCount());
check('Daten nach Zeit sortiert', JSON.stringify(sLevel.data.map(d => d.time)) === JSON.stringify([2001, 2002, 2003]), JSON.stringify(sLevel.data.map(d => d.time)));
check('Markers nach Zeit sortiert', JSON.stringify(sLevel.markers.map(m => m.time)) === JSON.stringify([2001, 2002, 2003]), JSON.stringify(sLevel.markers.map(m => m.time)));

console.log('\n=== Sortierung (Signal-Marker auf candleSeries) ===');
renderSignalMarkers([
    { time: 3002, shape: 'square' },
    { time: 3001, shape: 'square' },
]);
function isSorted(arr) {
    for (let i = 1; i < arr.length; i++) {
        if (arr[i].time < arr[i - 1].time) return false;
    }
    return true;
}
check('Signal-Array nach Zeit sortiert', isSorted(pluginMarkers), JSON.stringify(signalShapes()));

console.log('\nRESULT: ' + (failures === 0 ? 'PASS' : 'FAIL (' + failures + ')'));
process.exit(failures === 0 ? 0 : 1);
