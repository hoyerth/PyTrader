# BEREIT FÜR PHASE 15
# test/simulate_chart_mapping.py
"""Simuliert exakt den Chart-Mapping-Pfad aus chart_win._do_refresh_chart_data:
1) laedt die letzten 3000 SILVER M1-Candles aus der DB
2) baut kontinuierliche Zeiten (base + i*60)
3) erzeugt timeMap cont->real
4) berechnet, welche Labels der Chart anzeigen wuerde (Wanduhrzeit)
5) sucht nach diskontinuitaeten / falschen Labels / Tagesseparator-Positionen.
WICHTIG: Die DB-Epochs (EXTRACT) sind Berlin-Wanduhr-encoded -
datetime.fromtimestamp(e, tz=utc) liefert direkt die Wanduhrzeit (keine +2h).
KEIN UI-Test."""
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import duckdb

DB = r"F:\Python\PyTrader\data\market_data.duckdb"
LIMIT = 3000
TF_SEC = 60

con = duckdb.connect(DB, read_only=True)
rows = con.execute("""
    SELECT EXTRACT(epoch FROM "time")::BIGINT AS e, "time"
    FROM ohlcv_bars
    WHERE LOWER(symbol)='silver' AND LOWER(timeframe)='m1'
      AND "time" IS NOT NULL AND open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL
    ORDER BY "time" DESC LIMIT ?
""", [LIMIT]).fetchall()
con.close()

# aufsteigend sortieren (wie fetch_historical_candles)
rows = list(reversed(rows))
reals = [int(r[0]) for r in rows]
print(f"Candles: {len(rows)}")
print(f"  erste real: {datetime.fromtimestamp(reals[0], tz=timezone.utc)} (Wanduhr)")
print(f"  letzte real: {datetime.fromtimestamp(reals[-1], tz=timezone.utc)} (Wanduhr)")

# Kontinuierliches Mapping exakt wie in chart_win.py
base_time = reals[0]
cont_to_real = {}
real_to_cont = {}
cont_candles = []
for i, c in enumerate(rows):
    cont_time = base_time + i * TF_SEC
    real_time = int(c[0])
    cont_to_real[cont_time] = real_time
    real_to_cont[real_time] = cont_time
    cont_candles.append(cont_time)

print(f"\nKontinuierliche Zeit: base={base_time} ({datetime.fromtimestamp(base_time, tz=timezone.utc)} Wanduhr)")
print(f"  cont-Minimum={cont_candles[0]}  cont-Maximum={cont_candles[-1]}")

# Pruefen: kontinuierlich?
issues = 0
for i in range(1, len(cont_candles)):
    if cont_candles[i] - cont_candles[i-1] != TF_SEC:
        print(f"  [!!!] cont-Luecke bei i={i}: {cont_candles[i-1]} -> {cont_candles[i]}")
        issues += 1
print(f"  cont-Luecken: {issues}")

# Zeitbereich um die Tagesgrenze 30.07->31.07 (Wanduhr) ausgeben
print("\n=== Bars im Bereich 30.07 23:40 Wanduhr bis 31.07 02:10 Wanduhr ===")
t0 = datetime(2026, 7, 30, 23, 40, tzinfo=timezone.utc)
t1 = datetime(2026, 7, 31, 2, 10, tzinfo=timezone.utc)
for i, e in enumerate(reals):
    wall = datetime.fromtimestamp(e, tz=timezone.utc)
    if t0 <= wall <= t1:
        cont = cont_candles[i]
        # Label, das der Chart anzeigen wuerde
        realT = cont_to_real.get(cont, cont)
        b = datetime.fromtimestamp(realT, tz=timezone.utc)
        label = f"{b.strftime('%w')} {b.strftime('%d.%m.%y %H:%M')}"
        # Wochenende/Wanduhr-Tag-Wechsel?
        prev_real = reals[i-1] if i > 0 else None
        sep = ""
        if prev_real is not None and (int(prev_real)//86400 != e//86400):
            sep = "  <== WANDUHR-TAGWECHSEL"
        print(f"  i={i:4d} real={wall.strftime('%d.%m %H:%M')}  cont={cont}  label={label}{sep}")

# Tagesseparator-Positionen (wie DaySeparator.computeDaySeparatorTimes in
# chart/js/03_chart_rendering.js - reine Logik-Referenz, kein UI-Test)
print("\n=== Tagesseparatoren (Wanduhr-Tagwechsel) im Fenster ===")
last_line_time = 0
for i in range(1, len(reals)):
    prevReal = cont_to_real.get(cont_candles[i-1], cont_candles[i-1])
    currReal = cont_to_real.get(cont_candles[i], cont_candles[i])
    prevUtcDay = int(prevReal) // 86400
    currUtcDay = int(currReal) // 86400
    isUtcDayChange = currUtcDay != prevUtcDay
    isWeekendGap = currReal - prevReal > 43200
    isTooClose = (last_line_time > 0 and (cont_candles[i] - last_line_time) < 21600)
    if (isUtcDayChange or isWeekendGap) and not isTooClose:
        last_line_time = cont_candles[i]
        wall = datetime.fromtimestamp(int(currReal), tz=timezone.utc)
        print(f"  Separator bei cont={cont_candles[i]}  (real Wanduhr {wall.strftime('%d.%m.%y %H:%M')})  currTime-0.5={cont_candles[i]-0.5}  currTime+0.5={cont_candles[i]+0.5}")

# Fallback-Labels: kontinuierliche Zeit ohne Real-Mapping? (tickMarkFormatter-Fallback)
print("\n=== Tick-Labels: kontinuierliche Zeiten OHNE Real-Mapping? ===")
# Tickmarken, die LWC bei jedem vollen cont-stunde generieren wuerde
missing = 0
for tick in range(cont_candles[0] - cont_candles[0] % 3600, cont_candles[-1], 3600):
    if tick in cont_to_real:
        realT = cont_to_real[tick]
        b = datetime.fromtimestamp(realT, tz=timezone.utc)
        print(f"  Tick {tick} -> real {b.strftime('%d.%m.%y %H:%M')} OK")
    else:
        missing += 1
        print(f"  Tick {tick} -> [FALLBACK fake] {tick}  => label {datetime.fromtimestamp(tick, tz=timezone.utc)}")
print(f"  Ticks ohne Mapping: {missing}")
