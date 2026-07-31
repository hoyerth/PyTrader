// test/check_resolve_realtime.js
// Beweist den Fix fuer die "Leerstelle 30.7.26 23:58" (Wanduhr-Zeitachse):
// 1) Laedt die echte cont->real Map (test/tmp_cont_map.json)
// 2) Nutzt die ECHTEN Funktionen aus chart/js/02_time_utils.js (resolveRealTime,
//    _rebuildTimeMaps, toReal/toCont) – Single Source of Truth, kein Duplikat.
// 3) Zeigt den FIX: resolveRealTime(1785448739.5) -> naechste reale Candle
//    -> formatDT -> "Fr 31.07.26 00:01" (erste reale Candle nach der Pause)
// Hintergrund (empirisch verifiziert): Die Roh-Epochs sind bereits Berlin-
// Wanduhr-encoded (MT5 liefert Wanduhr, sync_market_data schreibt 1:1 via
// pd.to_datetime(unit="s", utc=True)). formatDT/getBerlinParts formatieren
// deshalb OHNE Berlin-Offset direkt – sonst waeren alle Labels 2h zu spaet.
// KEIN UI-Test - reine Logik-Pruefung.
// Kein 'use strict' - sonst bleiben eval-deklarierte Funktionen lokal.
const fs = require('fs');
const path = require('path');

// 02_time_utils.js ist self-contained (kein window/document) -> direkt laden
const timeUtilsSrc = fs.readFileSync(path.join(__dirname, '..', 'chart', 'js', '02_time_utils.js'), 'utf8');
eval(timeUtilsSrc);

const mapData = JSON.parse(fs.readFileSync(path.join(__dirname, 'tmp_cont_map.json'), 'utf8'));

// ECHTE _rebuildTimeMaps aus 02_time_utils.js verwenden (setzt beide Maps
// inkl. inverser real->cont Map). Kein manuelles Map-Befüllen im Test.
_rebuildTimeMaps(mapData.map);

// Die Phantom-Zeit, die durch currTime-0.5 entsteht (Separator bei der 00:01-Candle)
const PHANTOM_TS = 1785448739.5;
const CANDLE_2307 = 1785448680; // cont der 22:59-Candle (i=2307, real 1785452340)
const CANDLE_2308 = 1785448740; // cont der 00:01-Candle (i=2308, real 1785456060)

console.log('=== BUG-Reproduktion (altes Verhalten: _continuousTimeMap[ts] || ts) ===');
const oldReal = mapData.map[PHANTOM_TS] || PHANTOM_TS;
const oldLabel = formatDT(oldReal);
console.log(`  ts=${PHANTOM_TS} -> Fallback=${oldReal} -> Label="${oldLabel}"`);
console.log(`  ${oldLabel === 'Do 30.07.26 21:58' ? '>>> BUG: Fake-Zeit (21:58 existiert nicht; echte letzte Candle = 22:59)' : '  (kein Match)'}`);

console.log('\n=== FIX (resolveRealTime aus 02_time_utils.js) ===');
const newReal = resolveRealTime(PHANTOM_TS);
const newLabel = formatDT(newReal);
console.log(`  ts=${PHANTOM_TS} -> real=${newReal} -> Label="${newLabel}"`);
console.log(`  ${newReal === 1785456060 ? '>>> KORREKT: naechste reale Candle (31.07 00:01 Wanduhr, erste nach Pause 23:00-23:59)' : '  (andere reale Zeit)'}`);
console.log(`  ${newLabel === 'Fr 31.07.26 00:01' ? '>>> KORREKT: Wanduhr-Label OHNE Berlin-Offset (+2h) ' : '  (Label weicht ab)'}`);

console.log('\n=== toReal() = resolveRealTime() (Alias) ===');
console.log(`  toReal(1785448739.5) -> ${toReal(PHANTOM_TS)} (muss 1785456060 sein)`);

console.log('\n=== toCont() (inverse Zuordnung, real->cont) ===');
const contOfReal = toCont(1785456060);
console.log(`  toCont(1785456060) -> ${contOfReal} (muss 1785448740 sein)`);
console.log(`  toCont(999999999) -> ${toCont(999999999)} (muss undefined sein)`);

console.log('\n=== Genauigkeit: alle 3000 Candle-Zeiten muessen exakt matchen ===');
let ok = 0, bad = 0;
const keys = Object.keys(mapData.map).map(Number).sort((a, b) => a - b);
for (const k of keys) {
    const kNum = Number(k);
    const r = resolveRealTime(kNum);
    if (r === mapData.map[k]) ok++; else { bad++; if (bad < 5) console.log(`  MISMATCH cont=${kNum} -> ${r} erwartet ${mapData.map[k]}`); }
}
console.log(`  exakte Treffer: ${ok}, Mismatch: ${bad}`);

console.log('\n=== Padding-Ticks (ausserhalb des Datensatzes) ===');
const lastCont = keys[keys.length - 1];
const padReal = resolveRealTime(lastCont + 3600);
const padLabel = formatDT(padReal);
console.log(`  ts=${lastCont + 3600} -> real=${padReal} -> Label="${padLabel}" (clamped auf letzte Candle)`);
const firstCont = keys[0];
const firstLabel = formatDT(resolveRealTime(firstCont - 3600));
console.log(`  ts=${firstCont - 3600} -> Label="${firstLabel}" (clamped auf erste Candle)`);

console.log('\n=== Pausen-Grenze (Wanduhr 22:59 -> 00:01, Pause = 23:00-23:59) ===');
console.log(`  letzte vor Pause:  real=1785452340 -> Label="${formatDT(1785452340)}"`);
console.log(`  erste nach Pause:  real=1785456060 -> Label="${formatDT(1785456060)}"`);

console.log('\n=== Ungueltige Eingaben ===');
console.log(`  undefined -> ${resolveRealTime(undefined)}`);
console.log(`  NaN -> ${resolveRealTime(NaN)}`);
console.log(`  null -> ${resolveRealTime(null)}`);

console.log('\nRESULT:', (ok === 3000 && newReal === 1785456060 && newLabel === 'Fr 31.07.26 00:01' && formatDT(1785452340) === 'Do 30.07.26 22:59' && contOfReal === 1785448740) ? 'PASS' : 'FAIL');
