# BEREIT FÜR PHASE 15
# test/check_broker_tz.py
"""Klaert die Zeitzonen-Frage empirisch:
1) MT5-Tick-Zeit vs. Systemzeit -> Offset des Broker-Timestamps
   - diff ~ 0     -> Broker-Timestamp ist echte UTC (Chart muesste +DST rechnen)
   - diff ~ +7200 -> Broker-Timestamp kodiert BEREITS Berlin/CEST-Wanduhr
2) Vergleicht MT5-M1-Roh-Epoch mit dem DB-Epoch (speichert die DB Rohwerte?)
3) Prueft DuckDB-EXTRACT(epoch)-Verhalten.
Ergebnis (31.07.2026, empirisch): diff = +7200s -> MT5 liefert Berlin-Wanduhr.
sync_market_data() schreibt die Roh-Epochs via pd.to_datetime(unit='s', utc=True)
1:1 in die DB; EXTRACT(EPOCH) liefert exakt diese Wanduhr-encoded Epochs.
=> Der Chart muss diese Epochs DIREKT als Wanduhr formatieren (KEIN +2h).
KEIN UI-Test."""
import sys
import time
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import MetaTrader5 as mt5
import duckdb

print("=== 1) Broker-Timestamp vs Systemzeit ===")
if not mt5.initialize():
    print(f"MT5 init fehlgeschlagen: {mt5.last_error()}")
    sys.exit(1)

tick = mt5.symbol_info_tick("SILVER")
now = time.time()
if tick is None:
    print(f"Kein Tick fuer SILVER: {mt5.last_error()}")
else:
    diff = tick.time - int(now)
    print(f"  tick.time    = {tick.time}  -> als UTC gedeutet: {datetime.fromtimestamp(tick.time, tz=timezone.utc)}")
    print(f"  time.time()  = {int(now)} -> als UTC gedeutet: {datetime.fromtimestamp(now, tz=timezone.utc)}")
    print(f"  Diff (tick.time - time.time()) = {diff} s")
    if diff > 1000:
        print(f"  >>> Broker-Timestamp ist {diff/3600:.1f}h VOR der echten UTC")
        print(f"  >>> D.h. der Broker liefert BEREITS Berlin/CEST-Wanduhrzeit (Wanduhr-encoded)")
    elif diff < -1000:
        print(f"  >>> Broker-Timestamp ist {diff/3600:.1f}h HINTER der echten UTC")
    else:
        print(f"  >>> Broker-Timestamp ist die echte UTC (Diff ~ 0)")

print("\n=== 2) Letzte MT5-M1-Roh-Bars (raw epoch) ===")
rates = mt5.copy_rates_from_pos("SILVER", mt5.TIMEFRAME_M1, 0, 5)
if rates is None or len(rates) == 0:
    print("  Keine Rates:", mt5.last_error())
else:
    for r in rates[-5:]:
        print(f"  MT5 raw time={r['time']}  -> als UTC gedeutet: {datetime.fromtimestamp(int(r['time']), tz=timezone.utc)}  close={r['close']}")

print("\n=== 3) DB-Epoch der letzten SILVER M1 Bars ===")
con = duckdb.connect("data/market_data.duckdb", read_only=True)
rows = con.execute("""
    SELECT "time", EXTRACT(EPOCH FROM "time")::BIGINT AS e, close
    FROM ohlcv_bars
    WHERE LOWER(symbol)='silver' AND LOWER(timeframe)='m1'
    ORDER BY "time" DESC LIMIT 5
""").fetchall()
for t, e, c in rows:
    print(f"  DB time={t}  epoch={e}  (als Wanduhr gedeutet: {datetime.fromtimestamp(int(e), tz=timezone.utc)})  close={c}")
con.close()

print("\n=== 4) DuckDB-EXTRACT-Verhalten mit explizitem TIMESTAMPTZ-Literal ===")
con2 = duckdb.connect()
r = con2.execute("SELECT EXTRACT(EPOCH FROM TIMESTAMPTZ '2026-07-31 13:32:00+02:00') AS e").fetchone()
print(f"  EXTRACT(EPOCH FROM '2026-07-31 13:32:00+02:00') = {r[0]}")
print(f"  (Instanz 13:32+02:00 = 11:32 UTC, dessen korrektes UTC-Epoch = 1785497520)")
r2 = con2.execute("SELECT EXTRACT(EPOCH FROM TIMESTAMPTZ '2026-07-31 13:32:00') AS e").fetchone()
print(f"  EXTRACT(EPOCH FROM '2026-07-31 13:32:00' [ohne Offset]) = {r2[0]}")
con2.close()

mt5.shutdown()
print("\nFazit:")
print("  - MT5 liefert Wanduhr-encoded Epochs (diff ~ +7200).")
print("  - sync_market_data() schreibt sie via pd.to_datetime(unit='s', utc=True) 1:1.")
print("  - fetch_historical_candles() liefert diese Wanduhr-Epochs an den Chart.")
print("  - getBerlinParts/formatDT muessen DIREKT formatieren (KEIN +2h-Offset).")
