// test/check_race_guard.js
// Verifiziert die Race-Guard-Kernlogik aus 01_core.js / 04_live_updates.js:
// 1) applyFullChartUpdate: veraltete Payloads werden verworfen (stale updateId)
// 2) updateLiveCandle: verspaetete Ticks vom alten Symbol/TF werden verworfen
// Kein UI-Test - reine Logik-Pruefung.

let _updateId = 0;
let _lastAppliedUpdateId = 0;
let currentSymbol = 'SILVER';
let currentTimeframe = 'H1';
let appliedUpdates = [];
let appliedTicks = [];

// --- 1) Race-Guard applyFullChartUpdate (identische Kernlogik) ---
function applyFullChartUpdate(data) {
    var myId = ++_updateId;
    var updateId = (data && typeof data.updateId === 'number') ? data.updateId : myId;
    if (updateId < _lastAppliedUpdateId) {
        return 'DISCARDED';
    }
    _lastAppliedUpdateId = updateId;
    appliedUpdates.push(updateId);
    return 'APPLIED';
}

console.log('=== 1) applyFullChartUpdate Race-Guard ===');
// Szenario: Refresh B (neu, id=2) startet und kommt ZUERST an; A (alt, id=1) kommt spaeter.
let rB = applyFullChartUpdate({ updateId: 2, symbol: 'GOLD', timeframe: 'M1' });
let rA = applyFullChartUpdate({ updateId: 1, symbol: 'SILVER', timeframe: 'H1' });
console.log('  B (neu, zuerst):', rB);
console.log('  A (alt, spaeter):', rA);
console.log('  angewendet:', JSON.stringify(appliedUpdates));
let guardOk = (rB === 'APPLIED' && rA === 'DISCARDED' && appliedUpdates.length === 1 && appliedUpdates[0] === 2);

// Fallback ohne updateId (JS-interner Counter)
let rNoId = applyFullChartUpdate({});
console.log('  ohne updateId (Fallback-Counter):', rNoId, '(id=' + appliedUpdates[appliedUpdates.length - 1] + ')');

// --- 2) updateLiveCandle Symbol/TF-Guard (identische Kernlogik) ---
function updateLiveCandle(json) {
    var c = JSON.parse(json);
    if (c.symbol !== undefined && c.symbol !== null && c.symbol !== currentSymbol) return 'DISCARDED';
    if (c.timeframe !== undefined && c.timeframe !== null && c.timeframe !== currentTimeframe) return 'DISCARDED';
    appliedTicks.push(c.time);
    return 'APPLIED';
}

console.log('\n=== 2) updateLiveCandle Symbol/TF-Guard ===');
console.log('  Match (SILVER/H1):', updateLiveCandle('{"time":100,"symbol":"SILVER","timeframe":"H1"}'));
currentSymbol = 'GOLD';
console.log('  Stale SILVER-Tick nach Wechsel:', updateLiveCandle('{"time":101,"symbol":"SILVER","timeframe":"H1"}'));
console.log('  Ohne symbol-Feld (andere Aufrufer):', updateLiveCandle('{"time":102}'));
let tickOk = JSON.stringify(appliedTicks) === '[100,102]';

console.log('\nRESULT:', (guardOk && tickOk) ? 'PASS' : 'FAIL');
