// test/check_marker_layers.js
// Regressionstest: Signal-Marker und Grid-Circle-Marker sind getrennte Layer.
// _applyAllMarkers() kombiniert beide Caches – ein Grid-Render darf die
// EMA-Signale nie verdrängen (Bug: "EMA-Signale verschwinden bei Grid an").
//
// Laedt die ECHTE 03_chart_rendering.js mit Mock-Objekten (kein DOM/Chart).
const fs = require('fs');
const path = require('path');

const rendering = fs.readFileSync(path.join(__dirname, '..', 'chart', 'js', '03_chart_rendering.js'), 'utf8');

// --- Mock-Umgebung ---
let pluginMarkers = []; // was "im Chart sichtbar" ist
global._storedCircleMarkers = []; // in 01_core.js deklariert (nicht in 03 geladen)
global.seriesMarkersPlugin = {
    setMarkers: (markers) => { pluginMarkers = markers || []; },
};
global.candleSeries = { removePriceLine: () => {}, createPriceLine: () => ({}) };
global.LightweightCharts = {
    createSeriesMarkers: (series, initial) => ({ setMarkers: (m) => { pluginMarkers = m || []; } }),
};
global.document = {
    getElementById: () => null, // DaySeparator wird nur definiert, nicht genutzt
    createElement: () => ({ style: {} }),
};
global.chart = null;
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
function visibleShapes() {
    return pluginMarkers.map(m => m.time + ':' + m.shape);
}
function has(shape) {
    return pluginMarkers.some(m => m.shape === shape);
}

console.log('=== Marker-Layer: Signale + Circles bleiben getrennt ===');

// --- Szenario 1: Signal an, Grid an -> EMA + Circles sichtbar ---
renderSignalMarkers([{ time: 1001, shape: 'square', position: 'aboveBar', color: '#FF9800' }, { time: 1002, shape: 'square' }]);
renderGridCircles([{ time: 1003 }, { time: 1004 }]);
check('Signal an + Grid an -> Signale sichtbar', has('square'), JSON.stringify(visibleShapes()));
check('Signal an + Grid an -> Circles sichtbar', has('circle'), JSON.stringify(visibleShapes()));

// --- Szenario 2: Grid render_indicators (clearGridCircles + renderGridCircles) ---
clearGridCircles();
renderGridCircles([{ time: 1005 }]);
check('clearGridCircles + renderGridCircles -> Signale bleiben', has('square'), JSON.stringify(visibleShapes()));
check('clearGridCircles + renderGridCircles -> Circles aktualisiert', pluginMarkers.some(m => m.time === 1005 && m.shape === 'circle'), JSON.stringify(visibleShapes()));

// --- Szenario 3: Signal AUS (renderSignalMarkers([])) + Grid an -> NUR Circles ---
renderSignalMarkers([]);
renderGridCircles([{ time: 1006 }]);
check('Signal AUS + Grid an -> keine Signale', !has('square'), JSON.stringify(visibleShapes()));
check('Signal AUS + Grid an -> Circles da', has('circle'), JSON.stringify(visibleShapes()));

// --- Szenario 4: Grid AUS (clearGridCircles) bei aktiven Signalen -> EMA bleibt ---
renderSignalMarkers([{ time: 1007, shape: 'square' }]);
renderGridCircles([{ time: 1008 }]);
clearGridCircles();
check('Grid AUS -> EMA bleibt', has('square'), JSON.stringify(visibleShapes()));
check('Grid AUS -> Circles weg', !has('circle'), JSON.stringify(visibleShapes()));

// --- Szenario 5: clearSignalMarkers leert Signale, Circles bleiben ---
renderSignalMarkers([{ time: 1009, shape: 'square' }]);
renderGridCircles([{ time: 1010 }]);
clearSignalMarkers();
check('clearSignalMarkers -> Signale weg', !has('square'), JSON.stringify(visibleShapes()));
check('clearSignalMarkers -> Circles bleiben', has('circle'), JSON.stringify(visibleShapes()));

// --- Szenario 6: reapplySignalMarkers kombiniert aus Caches ---
renderSignalMarkers([{ time: 1011, shape: 'square' }]);
renderGridCircles([{ time: 1012 }]);
clearSignalMarkers();
renderSignalMarkers([{ time: 1011, shape: 'square' }]);
check('reapplySignalMarkers -> Signale + Circles', has('square') && has('circle'), JSON.stringify(visibleShapes()));

console.log('\\n=== Sortierung (Kern des Overlap-Fixes) ===');
// LWC v5.2.0 setMarkers() erwartet ein nach Zeit SORTIERTES Array:
//  - interne Binärsuche für den sichtbaren Bereich
//  - Marker derselben Kerze müssen BENACHBART sein, sonst setzt der
//    Stack-Offset zurück und der zweite überdeckt den ersten exakt.
// Test: unsortierte Mischung (Signale [2002,2001], Circles [2003,2001])
renderSignalMarkers([
    { time: 2002, shape: 'square' },
    { time: 2001, shape: 'square' },
]);
renderGridCircles([{ time: 2003 }, { time: 2001 }]);

function isSorted(arr) {
    for (let i = 1; i < arr.length; i++) {
        if (arr[i].time < arr[i - 1].time) return false;
    }
    return true;
}
function sameTimeAdjacent(arr) {
    // Marker mit gleicher Zeit muessen als Gruppe benachbart sein
    for (let i = 0; i < arr.length; i++) {
        const t = arr[i].time;
        // finde letzten Index mit derselben Zeit
        let j = i;
        while (j + 1 < arr.length && arr[j + 1].time === t) j++;
        // keine fremden Marker zwischen i und j -> Gruppe ist benachbart
        for (let k = i; k <= j; k++) {
            if (arr[k].time !== t) return false;
        }
        i = j;
    }
    return true;
}
check('Array nach Zeit sortiert', isSorted(pluginMarkers), JSON.stringify(visibleShapes()));
check('Gleiche Zeit benachbart (Stacking)', sameTimeAdjacent(pluginMarkers), JSON.stringify(visibleShapes()));
check('Beide Marker bei Zeit 2001 vorhanden (EMA + Circle)', pluginMarkers.filter(m => m.time === 2001).length === 2, JSON.stringify(visibleShapes()));

console.log('\\n=== Prioritäts-Sortierung (Punkt 2: Stapel-Reihenfolge bei gleicher Kerze) ===');
// Semantik: niedrige priority = näher an der Kerze (unten), hohe = weiter oben.
// engine-ignoriert priority (explizite Feldliste) – dient NUR unserer Sortierung.
renderSignalMarkers([
    { time: 3001, shape: 'square', priority: 4 },  // EMA (nahe an Kerze)
    { time: 3001, shape: 'circle', priority: 10 }, // Grid-Proximity (oben)
    { time: 3001, shape: 'square', priority: 2 },  // niedrigste Prio -> ganz unten
]);
renderGridCircles([{ time: 3001 }]);               // Grid-Circle, Default-Prio 10
const t3001 = pluginMarkers.filter(m => m.time === 3001);
const prios3001 = t3001.map(m => m.priority);
check('Priority aufsteigend sortiert [2,4,10,10]', JSON.stringify(prios3001) === JSON.stringify([2, 4, 10, 10]), JSON.stringify(prios3001));
check('Gleiche priority (10) behält Einfüge-Reihenfolge (stabiler Sort)', t3001[2].shape === 'circle' && t3001[3].shape === 'circle', JSON.stringify(t3001.map(m => m.shape)));
check('priority-Feld wird an Plugin durchgereicht (Engine ignoriert es)', pluginMarkers.some(m => m.priority === 2), JSON.stringify(prios3001));

// Ohne explizite priority: Signal-Default 0, Circle-Default 10
renderSignalMarkers([{ time: 3002, shape: 'square' }]); // kein priority
renderGridCircles([{ time: 3002 }]);                    // Default-Prio 10
const t3002 = pluginMarkers.filter(m => m.time === 3002);
check('Default: Signal (0) vor Circle (10)', JSON.stringify(t3002.map(m => m.priority)) === JSON.stringify([0, 10]), JSON.stringify(t3002.map(m => m.priority)));

console.log('\nRESULT: ' + (failures === 0 ? 'PASS' : 'FAIL (' + failures + ')'));
process.exit(failures === 0 ? 0 : 1);
