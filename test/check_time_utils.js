// BEREIT FÜR PHASE 15
// test/check_time_utils.js
// Verifiziert: keine Endlosschleife bei ungueltigen Eingaben in getBerlinParts/formatDT
// (Root Cause: timeFormatter erhielt UTCTimestamp-Zahl, Code griff auf t.time zu -> undefined
//  -> formatDT(undefined) -> Endlosschleife im alten DST-Check -> Chart-Hang, kein Crosshair/Panning)
// Hinweis: Seit dem Wanduhr-Fix gibt es keinen _isBerlinDST-Check mehr –
// getBerlinParts formatiert die (bereits Wanduhr-encoded) Roh-Epochs direkt.
const fs = require('fs');
const path = require('path');

// Gefixte Zeit-Utils laden
const utils = fs.readFileSync(path.join(__dirname, '..', 'chart', 'js', '02_time_utils.js'), 'utf-8');
eval(utils);

let failures = 0;

function check(label, fn, expectThrowFree) {
    try {
        const result = fn();
        if (expectThrowFree) {
            console.log(`OK   ${label} -> ${JSON.stringify(result)}`);
        }
    } catch (e) {
        failures++;
        console.error(`FAIL ${label} -> Exception: ${e.message}`);
    }
}

console.log('--- Szenario 1: timeFormatter mit Zahl (der Bug-Fall, t.time = undefined) ---');
check('formatDT mit Zahl (kein .time)', () => {
    const t = 1770192000; // UTCTimestamp-Zahl
    const ts = (t !== null && typeof t === 'object') ? t.time : t; // gefixter Zugriff
    const realT = ({}[ts] || ts); // leere _continuousTimeMap
    return formatDT(realT);
}, true);

console.log('--- Szenario 2: formatDT(undefined) (absoluter Crash-Fall) ---');
check('formatDT(undefined)', () => formatDT(undefined), true);

console.log('--- Szenario 3: valider Timestamp (normaler Betrieb) ---');
check('formatDT(1770192000)', () => formatDT(1770192000), true);
check('getBerlinParts(1770192000)', () => getBerlinParts(1770192000), true);

console.log('--- Szenario 4: Wanduhr-Formatierung (kein Berlin-Offset) ---');
// Roh-Epoch 1785456060 = erste Candle nach der Pause (Wanduhr 00:01 am 31.07.)
// Ohne Berlin-Offset wird direkt "Fr 31.07.26 00:01" erwartet.
check('formatDT(1785456060) Wanduhr 00:01', () => {
    const lbl = formatDT(1785456060);
    if (lbl !== 'Fr 31.07.26 00:01') throw new Error(`erwartet Fr 31.07.26 00:01, war ${lbl}`);
    return lbl;
}, true);
// Letzte Candle vor der Pause: Wanduhr 22:59 am 30.07. (Pause = 23:00-23:59)
check('formatDT(1785452340) Wanduhr 22:59', () => {
    const lbl = formatDT(1785452340);
    if (lbl !== 'Do 30.07.26 22:59') throw new Error(`erwartet Do 30.07.26 22:59, war ${lbl}`);
    return lbl;
}, true);

if (failures === 0) {
    console.log('\nALLE TESTS OK - KEINE ENDLOSSCHLEIFE');
    process.exit(0);
} else {
    console.error(`\n${failures} TEST(S) FEHLGESCHLAGEN`);
    process.exit(1);
}
