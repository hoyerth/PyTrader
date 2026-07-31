// chart/js/02_time_utils.js
// Zeit-Formatierung für die Chart-Achsen (Wanduhrzeit direkt aus dem Epoch).
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
