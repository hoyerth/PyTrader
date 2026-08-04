# BEREIT FÜR PHASE 15
# test/check_m1_consistency.py
"""Prueft die SILVER M1-Daten auf Konsistenz: Luecken, Handelspause,
Tagesgrenzen, ungueltige Candles. Kein UI-Test - nur DB-Logik.
HINWEIS Handelspause: SILVER (XAG) handelt 24/5. Die einzige taegliche Pause
ist Berlin-Wanduhr 23:00-23:59. Die DB-Roh-Epochs sind Wanduhr-encoded
(MT5 liefert Wanduhr-Zeiten, sync_market_data schreibt sie via
pd.to_datetime(unit='s', utc=True) 1:1) - deshalb liefert
t.astimezone(timezone.utc) exakt diese Wanduhrzeit. Zusaetzlich
Wochenend-Luecken (Fr 23:00 Wanduhr -> So/Mo 00:00 Wanduhr)."""
import sys
import os
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import duckdb

DB = r"F:\Python\PyTrader\data\market_data.duckdb"
SYMBOL = "SILVER"
TF = "M1"

con = duckdb.connect(DB, read_only=True)

# 1) Zeitbereich letzte Tage
print("=== Zeitbereich SILVER M1 (letzte 5 Tage) ===")
rows = con.execute("""
    SELECT EXTRACT(epoch FROM "time")::BIGINT AS e, "time" AS t, open, high, low, close
    FROM ohlcv_bars
    WHERE LOWER(symbol)=LOWER(?) AND LOWER(timeframe)=LOWER(?)
    ORDER BY "time" DESC
    LIMIT 5
""", [SYMBOL, TF]).fetchall()
for r in rows:
    print(f"  {r[1]}  O={r[2]} H={r[3]} L={r[4]} C={r[5]}")

# 2) Alle Bars ab 29.07. laden und Luecken pruefen
print("\n=== Luecken-Analyse ab 2026-07-29 (Handelspause Wanduhr 23:00-23:59 erlaubt) ===")
rows = con.execute("""
    SELECT EXTRACT(epoch FROM "time")::BIGINT AS e, "time" AS t, open, high, low, close
    FROM ohlcv_bars
    WHERE LOWER(symbol)=LOWER(?) AND LOWER(timeframe)=LOWER(?)
      AND "time" >= '2026-07-29 00:00:00+02:00'
      AND "time" IS NOT NULL
      AND open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL
    ORDER BY "time" ASC
""", [SYMBOL, TF]).fetchall()

print(f"Anzahl Bars: {len(rows)}")
if rows:
    print(f"Erste Bar: {rows[0][1]}")
    print(f"Letzte Bar: {rows[-1][1]}")

# Luecken finden (Differenz > 60s), Handelspause ignorieren
gaps = []
for i in range(1, len(rows)):
    prev_e, prev_t = rows[i-1][0], rows[i-1][1]
    curr_e, curr_t = rows[i][0], rows[i][1]
    diff = curr_e - prev_e
    if diff > 60:
        # Pruefen ob die Luecke die Handelspause 23:00-23:59 abdeckt
        prev_dt = prev_t.astimezone(timezone.utc)
        curr_dt = curr_t.astimezone(timezone.utc)
        gaps.append((prev_t, curr_t, diff, prev_dt, curr_dt))

print(f"\nLuecken > 60s: {len(gaps)}")
for prev_t, curr_t, diff, prev_dt, curr_dt in gaps[:40]:
    # Handelspause-Erkennung: letzte Bar 22:xx Wanduhr, naechste 00:xx Wanduhr
    # (Pause = Wanduhr 23:00-23:59; astimezone(utc) == Wanduhrzeit der DB-Epochs)
    prev_hour = prev_dt.hour
    curr_hour = curr_dt.hour
    pause = (prev_hour >= 22 and curr_hour < 1)
    print(f"  {prev_t} -> {curr_t}  diff={diff}s  (Wanduhr {prev_dt.hour}:{prev_dt.minute:02d} -> {curr_dt.hour}:{curr_dt.minute:02d}) {'[PAUSE]' if pause else '[!!! LUEKE]'}")

# 3) Handelspausen genauer: pro Tag fehlt die Wanduhr-Stunde 23 (23:00-23:59).
#    WICHTIG: Die Pause liegt bei Wanduhr 23:00-23:59 (keine Berlin-Offset-
#    Umrechnung noetig - die DB-Epochs sind bereits Wanduhr-encoded).
print("\n=== Handelspausen (Wanduhr 23:00-23:59) in den letzten Tagen ===")
pause_rows = con.execute("""
    SELECT "time", open, high, low, close
    FROM ohlcv_bars
    WHERE LOWER(symbol)=LOWER(?) AND LOWER(timeframe)=LOWER(?)
      AND "time" >= '2026-07-28 00:00:00+02:00'
      AND "time" <= '2026-07-31 23:59:59+02:00'
    ORDER BY "time" ASC
""", [SYMBOL, TF]).fetchall()

from collections import defaultdict
by_day = defaultdict(list)
for t, o, h, l, c in pause_rows:
    wall = t.astimezone(timezone.utc)  # == Wanduhrzeit der DB-Epochs
    by_day[wall.date()].append((wall, o, h, l, c))

for day in sorted(by_day.keys()):
    bars = by_day[day]
    first, last = bars[0][0], bars[-1][0]
    # Bars mit Wanduhr-Stunde 23 (die Pausen-Stunde) - sollten 0 sein
    in_pause = [b for b in bars if b[0].hour == 23]
    # Letzte Bar vor der Pause (Wanduhr <= 22:59) und erste danach (00:xx)
    last_before = None
    first_after = None
    for b in bars:
        if b[0].hour == 22 and b[0].minute >= 55:
            last_before = b
        if b[0].hour == 0 and b[0].minute < 5:
            first_after = b
    print(f"  {day} (Wanduhr): erste={first.strftime('%H:%M')} letzte={last.strftime('%H:%M')} "
          f"bars_in_Wanduhr23={len(in_pause)} "
          f"letzte_vorPause={last_before[0].strftime('%H:%M') if last_before else '?'} "
          f"erste_nachPause={first_after[0].strftime('%H:%M') if first_after else '?'}")

# 4) Ungueltige Candles (open<=0, high<low, close ausserhalb, NaN)
print("\n=== Ungueltige Candles (ab 29.07.) ===")
invalid = con.execute("""
    SELECT COUNT(*)
    FROM ohlcv_bars
    WHERE LOWER(symbol)=LOWER(?) AND LOWER(timeframe)=LOWER(?)
      AND "time" >= '2026-07-29 00:00:00+02:00'
      AND (open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
           OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
           OR high < low OR close < low OR close > high)
""", [SYMBOL, TF]).fetchone()[0]
print(f"  Ungueltige Candles: {invalid}")

# 5) Duplikate pruefen
print("\n=== Duplikate (PRIMARY KEY verhindert, trotzdem pruefen) ===")
dups = con.execute("""
    SELECT COUNT(*) FROM (
        SELECT symbol, timeframe, "time", COUNT(*) c
        FROM ohlcv_bars
        WHERE LOWER(symbol)=LOWER(?) AND LOWER(timeframe)=LOWER(?)
        GROUP BY symbol, timeframe, "time"
        HAVING COUNT(*) > 1
    )
""", [SYMBOL, TF]).fetchone()[0]
print(f"  Duplikate: {dups}")

con.close()
