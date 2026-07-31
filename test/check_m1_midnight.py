# test/check_m1_midnight.py
"""Prueft direkt, welche SILVER M1-Bars in der DB um Mitternacht 30.07->31.07 liegen.
Die DB-Roh-Epochs (EXTRACT) sind Berlin-Wanduhr-encoded - datetime.fromtimestamp(e, tz=utc)
liefert daher direkt die Wanduhrzeit (keine +2h-Umrechnung noetig).
KEIN UI-Test."""
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import duckdb

con = duckdb.connect("data/market_data.duckdb", read_only=True)
rows = con.execute("""
    SELECT "time", open, high, low, close, EXTRACT(epoch FROM "time")::BIGINT AS e
    FROM ohlcv_bars
    WHERE LOWER(symbol)='silver' AND LOWER(timeframe)='m1'
      AND "time" >= '2026-07-30 20:30:00+00:00'
      AND "time" <= '2026-07-31 02:30:00+00:00'
    ORDER BY "time" ASC
""").fetchall()
print(f"Bars gefunden: {len(rows)}")
for t, o, h, l, c, e in rows:
    wall = datetime.fromtimestamp(int(e), tz=timezone.utc)
    print(f"  e={e}  Wanduhr={wall.strftime('%d.%m %H:%M')}  raw={t}  O={o} H={h} L={l} C={c}")

# Jetzt ohne OHLC-Filter: gibt es Bars mit NULL/0 in dem Bereich?
print("\nOhne OHLC-Filter:")
rows2 = con.execute("""
    SELECT "time", open, high, low, close, EXTRACT(epoch FROM "time")::BIGINT AS e
    FROM ohlcv_bars
    WHERE LOWER(symbol)='silver' AND LOWER(timeframe)='m1'
      AND "time" >= '2026-07-30 20:30:00+00:00'
      AND "time" <= '2026-07-31 02:30:00+00:00'
    ORDER BY "time" ASC
""").fetchall()
print(f"Bars gefunden: {len(rows2)}")
for t, o, h, l, c, e in rows2:
    wall = datetime.fromtimestamp(int(e), tz=timezone.utc)
    print(f"  e={e}  Wanduhr={wall.strftime('%d.%m %H:%M')}  raw={t}  O={o} H={h} L={l} C={c}")
con.close()
