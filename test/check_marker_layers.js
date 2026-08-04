// BEREIT FÜR PHASE 15
// test/check_marker_layers.js
// Regressionstest: Grid-Circles auf unsichtbaren Level-Linien (getrennte Layer).
// - Proximity-Circles werden auf der ZUGEHOERIGEN LIQ-LINE geplottet:
//   Je Level-Preis wird eine UNSICHTBARE LineSeries erzeugt, deren Datenpunkt
//   exakt auf dem Level-Preis liegt; die Circle-Marker (shape 'circle',
//   position 'inBar') haengen an dieser Serie -> die Engine positioniert sie
//   direkt auf der Liq-Line (native, folgt Zoom/Scroll, kein Redraw-Bug).
// - Phase 15 (Signal-Rückbau): Signal-Marker-Funktionen (renderSignalMarkers,
//   clearSignalMarkers, reapplySignalMarkers, seriesMarkersPlugin) sind
//   ENTFERNT – nur noch Grid-Lines/Circles + DaySeparator existieren.
//
// Laedt die ECHTE 03_chart_rendering.js mit Mock-Objekten (kein DOM/Chart).
const fs = require('fs');
const path = require('path');

const rendering = fs.readFileSync(path.join(__dirname, '..', 'chart', 'js', '03_chart_rendering.js'), 'utf8');

// --- Mock-Umgebung ---
let circleSeriesList = [];     // unsichtbare Level-Serien der Circles
let removedSeries = [];

global._circleSeries = [];     // in 01_core.js deklariert (nicht in 03 geladen)
global._circleMarkerPlugins = [];
global._circleLevelSeries = {};
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
global.gridPriceLines = [];
global.LightweightCharts = {
    LineSeries: 'LineSeries',
    CandlestickSeries: 'CandlestickSeries',
    LineStyle: { Solid: 0 },
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

console.log('=== Marker-Layer: Grid-Circles (unsichtbare Level-Serien) ===');

// --- Phase 15: Signal-Marker-Funktionen ENTFERNT ---
console.log('\n=== Phase 15: Signal-Marker-Funktionen entfernt ===');
check('renderSignalMarkers NICHT definiert', typeof renderSignalMarkers === 'undefined');
check('clearSignalMarkers NICHT definiert', typeof clearSignalMarkers === 'undefined');
check('reapplySignalMarkers NICHT definiert', typeof reapplySignalMarkers === 'undefined');
check('seriesMarkersPlugin NICHT referenziert', !rendering.includes('seriesMarkersPlugin'));

// --- Szenario 1: Grid an -> Circles auf Level-Serien ---
console.log('\n=== Grid-Circles auf unsichtbaren Level-Serien ===');
renderGridCircles([{ time: 1003, price: 30.5 }, { time: 1004, price: 31.0 }]);
check('Circles -> 2 Level-Serien', levelSeriesCount() === 2, 'serien=' + levelSeriesCount());
// Serie fuer Level 30.5 hat Datenpunkt exakt auf dem Level -> Circle auf der Liq-Line
const s30 = circleSeriesList.find(s => (s.data[0] || {}).value === 30.5);
check('Level 30.5: Datenpunkt (time=1003, value=30.5)', s30 && s30.data.length === 1 && s30.data[0].time === 1003 && s30.data[0].value === 30.5, JSON.stringify(s30 && s30.data));
check('Level 30.5: Circle-Marker (inBar, size 1)', s30 && s30.markers[0] && s30.markers[0].position === 'inBar' && s30.markers[0].size === 1, JSON.stringify(s30 && s30.markers[0]));
check('Level 30.5: LineSeries unsichtbar (lineVisible:false)', s30 && s30.options.lineVisible === false, '');
check('Level 30.5: priceScaleId=right', s30 && s30.options.priceScaleId === 'right', '');
check('Level 30.5: autoscaleInfoProvider -> null', s30 && typeof s30.options.autoscaleInfoProvider === 'function' && s30.options.autoscaleInfoProvider() === null, '');

// --- Szenario 2: clearGridCircles entfernt Level-Serien ---
clearGridCircles();
check('clearGridCircles -> Level-Serien entfernt', levelSeriesCount() === 0, 'serien=' + levelSeriesCount());
renderGridCircles([{ time: 1005, price: 30.0 }]);
check('renderGridCircles -> neue Level-Serie', levelSeriesCount() === 1, 'serien=' + levelSeriesCount());
check('renderGridCircles -> Circle aktualisiert', hasCircleTime(1005), JSON.stringify(allCircleMarkers().map(m => m.time)));

// --- Szenario 3: leerer Satz -> alle Circles weg ---
renderGridCircles([]);
check('renderGridCircles([]) -> keine Level-Serien', levelSeriesCount() === 0, 'serien=' + levelSeriesCount());

// --- Szenario 4: Grid AUS (clearGridCircles) ---
renderGridCircles([{ time: 1008, price: 30.0 }]);
clearGridCircles();
check('Grid AUS -> Circles weg', levelSeriesCount() === 0, 'serien=' + levelSeriesCount());

// --- Szenario 5: P14-03-E Inkrementell (kein Rebuild bei unveraendertem Level) ---
renderGridCircles([{ time: 2001, price: 30.0 }]);
const firstSeries = circleSeriesList[0];
renderGridCircles([{ time: 2001, price: 30.0 }, { time: 2002, price: 31.0 }]);
check('Inkrementell: bestehendes Level bleibt (gleiche Serie)', circleSeriesList[0] === firstSeries, '');
check('Inkrementell: neues Level hinzugefuegt', levelSeriesCount() === 2, 'serien=' + levelSeriesCount());
renderGridCircles([{ time: 2001, price: 30.0 }]);
check('Inkrementell: verschwundenes Level entfernt', levelSeriesCount() === 1, 'serien=' + levelSeriesCount());

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

console.log('\n=== Grid-Lines (PriceLines auf candleSeries) ===');
renderGridLines([{ price: 30.0, color: '#2196F3', width: 1 }, { price: 30.5, color: '#2196F3', width: 1 }]);
check('renderGridLines -> 2 PriceLines', gridPriceLines.length === 2, 'lines=' + gridPriceLines.length);
clearGridLines();
check('clearGridLines -> PriceLines entfernt', gridPriceLines.length === 0, 'lines=' + gridPriceLines.length);

console.log('\nRESULT: ' + (failures === 0 ? 'PASS' : 'FAIL (' + failures + ')'));
process.exit(failures === 0 ? 0 : 1);
