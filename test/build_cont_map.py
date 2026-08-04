# BEREIT FÜR PHASE 15
# test/build_cont_map.py
"""Baut die kontinuierliche cont->real Map fuer die letzten 3000 SILVER M1 Bars
(exakt wie chart_win._do_refresh_chart_data) und schreibt sie als JSON,
damit der Node-Test die resolveRealTime-Logik mit echten Daten pruefen kann.
KEIN UI-Test."""
import json
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import duckdb

con = duckdb.connect("data/market_data.duckdb", read_only=True)
rows = con.execute("""
    SELECT EXTRACT(epoch FROM "time")::BIGINT AS e
    FROM ohlcv_bars
    WHERE LOWER(symbol)='silver' AND LOWER(timeframe)='m1'
      AND "time" IS NOT NULL AND open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL
    ORDER BY "time" DESC LIMIT 3000
""").fetchall()
con.close()

reals = [int(r[0]) for r in rows][::-1]
base_time = reals[0]
cont_to_real = {}
for i, r in enumerate(reals):
    cont_to_real[str(base_time + i * 60)] = r  # JSON keys muessen Strings sein

out = {
    "base_time": base_time,
    "count": len(reals),
    "map": cont_to_real,
}
with open("test/tmp_cont_map.json", "w", encoding="utf-8") as f:
    json.dump(out, f)

print(f"Map geschrieben: {len(cont_to_real)} Eintraege, base={base_time}")
# Roh-Epochs sind Berlin-Wanduhr-encoded -> fromtimestamp(e, utc) direkt
for probe in [base_time, base_time + 2307 * 60, base_time + 2308 * 60]:
    b = datetime.fromtimestamp(int(cont_to_real[str(probe)]), tz=timezone.utc)
    print(f"  cont={probe} -> real={cont_to_real[str(probe)]} (Wanduhr {b.strftime('%d.%m %H:%M')})")
