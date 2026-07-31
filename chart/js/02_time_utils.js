// chart/js/02_time_utils.js
// Zeit-Formatierung für die Chart-Achsen (Wanduhrzeit direkt aus dem Epoch) +
// ZENTRALE Zeit-Konstanten & Zeit-Mapping-Helper (Single Source of Truth).
//
// WICHTIG (empirisch verifiziert via test/check_broker_tz.py, DB-Abgleich &
// Live-Messung an MT5):
// - MT5 liefert Zeiten als BERLIN-WANDUHR-encoded Epochs: Bei echter UTC 10:00
//   ist tick.time bereits die Zahl "12:00" (diff = +7200s). Der User hat recht.
// - sync_market_data() schreibt die Roh-Epochs via
//   pd.to_datetime(..., unit="s", utc=True) 1:1 in die DB; EXTRACT(EPOCH) und
//   fetch_historical_candles() geben exakt diese Roh-Epochs an den Chart.
// => Eine zusätzliche Berlin-Offset-Umrechnung (+2h/+1h) wäre DOPPELT und
//    würde alle Achsen-Labels 2h zu spät anzeigen.
// => getBerlinParts formatiert den Epoch direkt über die UTC-Getter; der Wert
//    IST bereits die gewünschte Wanduhrzeit. Das ist automatisch DST-robust
//    (keine Saison-Logik nötig): Im Winter liefert der Broker CET-encoded
//    Werte, die ebenfalls direkt korrekt dargestellt werden.

// =============================================================================
// ZENTRALE ZEIT-KONSTANTEN (keine magischen Zahlen im restlichen Code)
// =============================================================================
const SECONDS_PER_DAY = 86400;
const WEEKEND_GAP_SECONDS = 43200;   // >12h Lücke ohne Kerzen = Wochenend-Gap
const MIN_SEPARATOR_SPACING_SECONDS = 21600; // Mindestabstand zweier Trennlinien

function getBerlinParts(t) {
    var weekdays = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
    var pad = function(n) { return String(n).padStart(2, '0'); };
    
    // Ungueltige Eingaben abfangen (verhindert NaN-Ausgabe & Endlosschleifen)
    if (typeof t !== 'number' || !isFinite(t)) {
        return { weekday: '', day: '--', month: '--', year: '----', hour: '--', minute: '--', rawDayOfWeek: -1 };
    }
    
    // Roh-Epoch = bereits Berliner Wanduhrzeit => direkt via UTC-Getter lesen.
    var bd = new Date(t * 1000);
    
    return {
        weekday: weekdays[bd.getUTCDay()],
        day: pad(bd.getUTCDate()),
        month: pad(bd.getUTCMonth() + 1),
        year: String(bd.getUTCFullYear()),
        hour: pad(bd.getUTCHours()),
        minute: pad(bd.getUTCMinutes()),
        rawDayOfWeek: bd.getUTCDay()
    };
}

function formatDT(t) { 
    var p = getBerlinParts(t); 
    return p.weekday + ' ' + p.day + '.' + p.month + '.' + p.year.slice(-2) + ' ' + p.hour + ':' + p.minute; 
}

// =============================================================================
// ZEIT-MAPPING (kontinuierliche Fake-Zeit <-> echte epoch)
// -----------------------------------------------------------------------------
// Die Charts arbeiten auf kontinuierlicher Zeit (base_time + i*tf_sec), damit
// keinerlei Lücken/Whitespace entstehen. Die _continuousTimeMap (cont->real)
// wird aus Python mitgeliefert (data.timeMap). Diese Funktionen sind die
// EINZIGE Schnittstelle zum Zeit-Mapping – kein roher Map-Zugriff im Rest.
//
// INVARIANTE: Das Mapping ist bijektiv (jede Candle hat genau eine cont-Zeit
// und genau eine real-Epoch) und monoton steigend (cont & real wachsen
// gemeinsam). Verletzungen erzeugen Fake-Labels an Tagesgrenzen.
// =============================================================================
let _realToContMap = {};  // { real_epoch: cont_time } – invers zu _continuousTimeMap

function _rebuildTimeMaps(timeMap) {
    // Setzt beide Maps aus der von Python gelieferten cont->real Map.
    _continuousTimeMap = timeMap || {};
    _continuousKeys = Object.keys(_continuousTimeMap).map(Number).sort(function(a, b) { return a - b; });
    _realToContMap = {};
    for (var i = 0; i < _continuousKeys.length; i++) {
        var contKey = _continuousKeys[i];
        _realToContMap[_continuousTimeMap[contKey]] = contKey;
    }
}

// =============================================================================
// resolveRealTime(): kontinuierliche (Fake-)Zeit -> echte epoch
// WICHTIG: Bei unbekannten Werten (Padding-Ticks ausserhalb des Datensatzes)
// NIE die Fake-Zeit selbst zurueckgeben – sonst zeigt die Zeitachse
// irrefuehrende Labels (z. B. "30.7.26 23:58" an der Tagesgrenze, weil die
// Fake-Zeit der 00:59-Candle als Realzeit formatiert wird).
// Stattdessen wird der naechstgelegene bekannte Zeitpunkt verwendet.
// =============================================================================
function resolveRealTime(ts) {
    if (ts === null || ts === undefined || typeof ts !== 'number' || !isFinite(ts)) return ts;
    var direct = _continuousTimeMap[ts];
    if (direct !== undefined) return direct;
    if (_continuousKeys.length === 0) return ts;
    var n = _continuousKeys.length;
    if (ts <= _continuousKeys[0]) return _continuousTimeMap[_continuousKeys[0]];
    if (ts >= _continuousKeys[n - 1]) return _continuousTimeMap[_continuousKeys[n - 1]];
    var lo = 0, hi = n - 1;
    while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (_continuousKeys[mid] === ts) return _continuousTimeMap[_continuousKeys[mid]];
        if (_continuousKeys[mid] < ts) lo = mid + 1; else hi = mid - 1;
    }
    // hi = letzter Key < ts, lo = erster Key > ts
    var a = _continuousKeys[hi], b = _continuousKeys[lo];
    return (ts - a <= b - ts) ? _continuousTimeMap[a] : _continuousTimeMap[b];
}

// Alias mit sprechendem Namen – überall verwenden, wo echte Zeit gebraucht wird.
function toReal(ts) { return resolveRealTime(ts); }

// echte epoch -> kontinuierliche Zeit (inverse Zuordnung).
// Liefert undefined, wenn die real-Epoch nicht im Datensatz liegt.
function toCont(realEpoch) { return _realToContMap[realEpoch]; }
