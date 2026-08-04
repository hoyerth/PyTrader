# BEREIT FÜR PHASE 15
# test/check_chart_data.py
"""Kurzer Check: Verifiziert die DB-Queries, die das Chart-Fenster nutzt, fuer alle Symbol/TF-Kombos."""
import duckdb
from pathlib import Path

MARKET = Path(r"F:\Python\PyTrader\data\market_data.duckdb")
ANALYTICS = Path(r"F:\Python\PyTrader\data\analytics.duckdb")

con = duckdb.connect(str(MARKET), read_only=True)
pairs = [
    ("SILVER", "H1"), ("SILVER", "M5"), ("SILVER", "M15"), ("SILVER", "D1"), ("SILVER", "W1"), ("SILVER", "MN1"),
    ("GOLD", "H1"), ("GOLD", "M5"), ("GOLD", "M15"), ("GOLD", "D1"), ("GOLD", "W1"), ("GOLD", "MN1"),
]

for sym, tf in pairs:
    try:
        rows = con.execute("""
            SELECT EXTRACT(epoch FROM "time")::BIGINT AS time_epoch, open, high, low, close
            FROM (SELECT "time", open, high, low, close FROM ohlcv_bars
                  WHERE LOWER(symbol)=LOWER(?) AND LOWER(timeframe)=LOWER(?)
                  AND "time" IS NOT NULL AND open IS NOT NULL AND high IS NOT NULL
                  AND low IS NOT NULL AND close IS NOT NULL
                  ORDER BY "time" DESC LIMIT 3000) ORDER BY "time" ASC""", [sym, tf]).fetchall()
        ok = len(rows) > 0 and all(r[0] > 0 and r[1] > 0 and r[2] > 0 and r[3] > 0 and r[4] > 0 for r in rows)
        print(f"{sym:7s} {tf:4s} -> {len(rows):>5d} candles  valid={ok}")
    except Exception as e:
        print(f"{sym:7s} {tf:4s} -> ERROR: {e}")

# Marker-Query (SignalOverlay.fetch_markers) – Phase 13 7.B: feature_store
# (feature_data, feature_id), KEIN signal_results-Fallback mehr.
acon = duckdb.connect(str(ANALYTICS), read_only=True)
print("\n--- fetch_markers queries (feature_store, feature_id) ---")
for sym, tf, fid in [("SILVER", "H1", "grid_proximity_v1"), ("SILVER", "M5", "grid_proximity_v1"),
                     ("GOLD", "H1", "grid_proximity_v1"),
                     ("SILVER", "H1", "ema_atr_set_v1"), ("SILVER", "H1", "proximity")]:
    try:
        rows = acon.execute("""
            SELECT EXTRACT(epoch FROM bar_time)::BIGINT AS time_epoch, feature_data
            FROM (SELECT bar_time, feature_data FROM feature_store
                  WHERE symbol = ? AND timeframe = ? AND feature_id = ?
                    AND feature_data IS NOT NULL
                  ORDER BY bar_time DESC LIMIT 500) ORDER BY bar_time ASC""", [sym, tf, fid]).fetchall()
        print(f"{sym:7s} {tf:4s} {fid:20s} -> {len(rows)} markers")
    except Exception as e:
        print(f"{sym:7s} {tf:4s} {fid:20s} -> ERROR: {e}")
