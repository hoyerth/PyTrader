// test/check_measurement.js
// Regressionstest für die rekonstruierte Messfunktion (05_measurement.js):
// Strg+LMB Box -> Messwerte -> pyBridge-Sync -> Restore.
//
// Laedt die ECHTE 05_measurement.js mit Mock-Objekten (kein DOM/Chart).
const fs = require('fs');
const path = require('path');

const measurementJs = fs.readFileSync(path.join(__dirname, '..', 'chart', 'js', '05_measurement.js'), 'utf8');

// --- Mock-Umgebung ---
let sentPayloads = []; // was an Python geschickt wurde
global.pyBridge = {
    onMeasurementChanged: (m) => { sentPayloads.push(m); },
};
global._continuousKeys = [100, 200, 300, 400, 500, 600, 700]; // uniform (tf=100), Indizes 0..6
global._continuousTimeMap = {};
global.toReal = (ts) => ts + 1000000; // cont -> real (testbar)
global.currentPrecision = 2;
global.currentTfInSeconds = 3600;
global.SECONDS_PER_DAY = 86400;
global.formatDT = (t) => 'T' + t;
global.chart = null;          // pure Funktionen brauchen keinen Chart
global.isUpdatingChart = false;

function makeElement() {
    return { style: { display: 'none' }, innerText: '', offsetWidth: 200, offsetHeight: 70 };
}
const regionEl = makeElement();
const boxEl = makeElement();
global.document = {
    getElementById: (id) => {
        if (id === 'measurement-region') return regionEl;
        if (id === 'measurement-box') return boxEl;
        return null; // kein chart-container -> _bind() bricht ab
    },
    createElement: () => makeElement(),
};
global.window = { addEventListener: () => {}, removeEventListener: () => {} };

eval(measurementJs);

let failures = 0;
function check(label, cond, extra) {
    if (cond) {
        console.log('OK   ' + label + (extra ? ' -> ' + extra : ''));
    } else {
        failures++;
        console.error('FAIL ' + label + (extra ? ' -> ' + extra : ''));
    }
}

console.log('=== contTimeAtLogical: Interpolation & Clamping ===');
check('logical 0 -> erster Key', Measurement.contTimeAtLogical(0) === 100, String(Measurement.contTimeAtLogical(0)));
check('logical 1.5 -> Interpolation 250', Measurement.contTimeAtLogical(1.5) === 250, String(Measurement.contTimeAtLogical(1.5)));
check('logical 3 -> ganzzahlig 400', Measurement.contTimeAtLogical(3) === 400, String(Measurement.contTimeAtLogical(3)));
check('logical -5 -> clamp auf 100', Measurement.contTimeAtLogical(-5) === 100, String(Measurement.contTimeAtLogical(-5)));
check('logical 99 -> clamp auf 700', Measurement.contTimeAtLogical(99) === 700, String(Measurement.contTimeAtLogical(99)));
check('logical 6 (letzter) -> 700', Measurement.contTimeAtLogical(6) === 700, String(Measurement.contTimeAtLogical(6)));
check('keine Keys -> null', Measurement.contTimeAtLogical(NaN) === null, String(Measurement.contTimeAtLogical(NaN)));

console.log('\n=== computeMeasurementData: Deltas & Duration ===');
const d = Measurement.computeMeasurementData(0, 1000, 6, 1012);
check('deltaLogical = 6', d.deltaLogical === 6, String(d.deltaLogical));
check('deltaPrice = +12', d.deltaPrice === 12, String(d.deltaPrice));
check('pctChange = +1.2', Math.abs(d.pctChange - 1.2) < 1e-9, String(d.pctChange));
check('candleCount = 6', d.candleCount === 6, String(d.candleCount));
check('durationSeconds = 21600 (6*3600)', d.durationSeconds === 21600, String(d.durationSeconds));
check('from.realTime via toReal', d.from.realTime === 1000100, String(d.from.realTime));
check('to.contTime = 700', d.to.contTime === 700, String(d.to.contTime));
const d2 = Measurement.computeMeasurementData(6, 1012, 0, 1000);
check('Rückwärts: candleCount positiv', d2.candleCount === 6, String(d2.candleCount));
check('Rückwärts: duration positiv', d2.durationSeconds === 21600, String(d2.durationSeconds));

console.log('\n=== formatDuration: DD:HH:MM (ohne Sekunden) ===');
check('21600s -> 00:06:00', Measurement.formatDuration(21600) === '00:06:00', Measurement.formatDuration(21600));
check('90000s -> 01:01:00', Measurement.formatDuration(90000) === '01:01:00', Measurement.formatDuration(90000));
check('3661s -> 00:01:01', Measurement.formatDuration(3661) === '00:01:01', Measurement.formatDuration(3661));
check('negativ -> 00:00:00', Measurement.formatDuration(-5) === '00:00:00', Measurement.formatDuration(-5));

console.log('\n=== formatMeasurementText: Box-Inhalt ===');
const text = Measurement.formatMeasurementText(d);
check('Zeile Δ Preis mit % zuerst', text.indexOf('Δ Preis: +1.20%  (+12.00)') === 0, text.split('\n')[0]);
check('Zeile Δ Zeit mit Bars & DD:HH:MM', text.indexOf('6 Bars · 00:06:00') !== -1, text.split('\n')[1]);
check('Start-Zeile: Preis + Zeit', text.split('\n')[2] === 'Start:   ' + (1000).toFixed(2) + '  T1000100', text.split('\n')[2]);
check('Ende-Zeile: Preis + Zeit', text.split('\n')[3] === 'Ende:    ' + (1012).toFixed(2) + '  T1000700', text.split('\n')[3]);

console.log('\n=== pyBridge-Sync (State -> JSON an Python) ===');
sentPayloads = [];
Measurement._setStateForTest({ from: { logical: 1.23456, price: 1000 }, to: { logical: 6, price: 1012 } });
Measurement._syncToPython();
check('Sync sendet genau 1 Payload', sentPayloads.length === 1, String(sentPayloads.length));
let parsed = null;
try { parsed = JSON.parse(sentPayloads[0]); } catch(e) {}
check('Payload ist JSON', parsed !== null, sentPayloads[0]);
check('logical auf 4 Nachkommastellen gerundet', parsed.from.logical === 1.2346, String(parsed.from.logical));
check('price unverändert', parsed.to.price === 1012, String(parsed.to.price));

console.log('\n=== Restore / Clear / Escape ===');
Measurement.restore(JSON.stringify({ from: { logical: 2, price: 100 }, to: { logical: 4, price: 110 } }));
check('restore setzt State', Measurement.hasState(), JSON.stringify(Measurement._state()));
Measurement.restore({});
check('restore mit leerem Objekt -> kein State', !Measurement.hasState());
Measurement.restore('{kaputt');
check('restore mit kaputtem JSON -> kein State', !Measurement.hasState());
Measurement.restore({ from: { logical: 2, price: 100 }, to: { logical: 4, price: 110 } });
Measurement.clear();
check('clear -> kein State', !Measurement.hasState());
check('clear versteckt Region', regionEl.style.display === 'none');
check('clear versteckt Box', boxEl.style.display === 'none');

console.log('\nRESULT: ' + (failures === 0 ? 'PASS' : 'FAIL (' + failures + ')'));
process.exit(failures === 0 ? 0 : 1);
