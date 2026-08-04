// BEREIT FÜR PHASE 15
// test/check_time_constants.js
// Verifiziert Punkt B4: die zentralen Zeit-Konstanten aus 02_time_utils.js.
// Zusaetzlich (Punkt C/D): die Tageswechsel-Erkennung wird NICHT mehr dupliziert,
// sondern direkt aus dem gekapselten Modul getestet:
//   DaySeparator.computeDaySeparatorTimes(candleData)
// (pure Funktion in chart/js/03_chart_rendering.js - ohne DOM/Chart).
// Kein UI-Test - reine Logik-Pruefung (laeuft ohne Chart/DOM).
//
// Hinweis: const-Deklarationen sind im eval-Scope nicht von aussen sichtbar,
// deshalb wird der Testcode in denselben eval-Kontext eingebettet.
const fs = require('fs');
const path = require('path');

const utils = fs.readFileSync(path.join(__dirname, '..', 'chart', 'js', '02_time_utils.js'), 'utf8');
const rendering = fs.readFileSync(path.join(__dirname, '..', 'chart', 'js', '03_chart_rendering.js'), 'utf8');

const testBody = `
let failures = 0;
function assert(label, cond, extra) {
    if (cond) {
        console.log('OK   ' + label + (extra ? ' -> ' + extra : ''));
    } else {
        failures++;
        console.error('FAIL ' + label);
    }
}

console.log('=== B4: Zentrale Zeit-Konstanten ===');
assert('SECONDS_PER_DAY = 86400', SECONDS_PER_DAY === 86400, String(SECONDS_PER_DAY));
assert('WEEKEND_GAP_SECONDS = 43200', WEEKEND_GAP_SECONDS === 43200, String(WEEKEND_GAP_SECONDS));
assert('MIN_SEPARATOR_SPACING_SECONDS = 21600', MIN_SEPARATOR_SPACING_SECONDS === 21600, String(MIN_SEPARATOR_SPACING_SECONDS));

console.log('\\n=== C/D: DaySeparator.computeDaySeparatorTimes (echtes Modul, keine Duplikation) ===');
assert('DaySeparator-Modul geladen', typeof DaySeparator === 'object' && typeof DaySeparator.computeDaySeparatorTimes === 'function');

// Simulierte Candles (kontinuierliche Zeiten), real via _rebuildTimeMaps gesetzt
_rebuildTimeMaps({
    1000: 1785452340, // Do 30.07.26 22:59 Wanduhr (letzte vor Pause)
    1001: 1785456060, // Fr 31.07.26 00:01 Wanduhr (erste nach Pause) -> Tagwechsel
    1002: 1785459660, // Fr 31.07.26 01:01 -> gleicher Tag, kein Wechsel
    1003: 1785463260, // Fr 31.07.26 02:01 -> gleicher Tag
});

const candles = [
    { time: 1000 }, // Do 22:59
    { time: 1001 }, // Fr 00:01  -> Tagwechsel -> Linie
    { time: 1002 }, // Fr 01:01  -> kein Wechsel
    { time: 1003 }, // Fr 02:01  -> kein Wechsel
];
const detected = DaySeparator.computeDaySeparatorTimes(candles);
assert('Tagwechsel bei 1001 erkannt', detected.length === 1 && detected[0] === 1001, JSON.stringify(detected));

// Weekend-Gap: Luecke > 12h ohne Tagwechsel -> Linie
const gapCandles = [
    { time: 2000 }, // real 1785452340 (Do 22:59)
    { time: 2001 }, // real 1785452340 + 50000 (> WEEKEND_GAP_SECONDS) -> Gap
];
_rebuildTimeMaps({ 2000: 1785452340, 2001: 1785452340 + 50000 });
const gapLines = DaySeparator.computeDaySeparatorTimes(gapCandles);
assert('Weekend-Gap erkannt', gapLines.length === 1, JSON.stringify(gapLines));

// Zu dicht aufeinanderfolgende Linien werden gefiltert (< MIN_SEPARATOR_SPACING_SECONDS cont)
const closeCandles = [
    { time: 1000 }, // Linie 1
    { time: 1001 }, // wuerde Linie 2 -> aber Abstand < MIN -> gefiltert
];
_rebuildTimeMaps({ 1000: 1785452340, 1001: 1785456060 });
const closeLines = DaySeparator.computeDaySeparatorTimes(closeCandles);
assert('Dichte Folge wird gefiltert', closeLines.length === 1, JSON.stringify(closeLines));

// Leere / ungueltige Eingaben -> leeres Array, kein Crash
assert('Leere Eingabe -> []', JSON.stringify(DaySeparator.computeDaySeparatorTimes([])) === '[]', JSON.stringify(DaySeparator.computeDaySeparatorTimes([])));
assert('null Eingabe -> []', JSON.stringify(DaySeparator.computeDaySeparatorTimes(null)) === '[]', JSON.stringify(DaySeparator.computeDaySeparatorTimes(null)));

// Wichtiger Testwert: einzelne Candle -> keine Linie (braucht Vorgaenger)
assert('Einzelne Candle -> []', JSON.stringify(DaySeparator.computeDaySeparatorTimes([{ time: 1000 }])) === '[]');

console.log('\\nRESULT: ' + (failures === 0 ? 'PASS' : 'FAIL (' + failures + ')'));
if (failures !== 0) process.exit(1);
`;

eval(utils + '\n' + rendering + '\n' + testBody);
