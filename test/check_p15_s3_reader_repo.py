# test/check_p15_s3_reader_repo.py
"""
Phase 15 15.03 Schritt 3 – Headless Validierung (KEINE UI, KEIN QApplication).

Prueft FeatureStoreReader (analytics/engine/feature_store_reader.py) und
AnalyticsRepository (analytics/engine/analytics_repository.py) auf
Logik-/DB-Ebene mit einer Test-DB in test/ (Regel: keine Test-DBs im
Root/data).

Testdaten (Berlin-Wanduhr-encoded, Invariante 7 – die UTC-Darstellung der
gespeicherten TIMESTAMPTZ IST die Wanduhr-Zeit, kein Offset):
  - Mo 03.08.2026 12:00  (DOW=1, HOUR=12)  ema_diff=0.10 rsi=55.0 atr=0.02
  - Mo 03.08.2026 13:00  (DOW=1, HOUR=13)  ema_diff=0.12 rsi=57.0 atr=0.03
  - Mo 03.08.2026 14:00  (DOW=1, HOUR=14)  OHNE schema_version (Alt-Row)
  - Mi 05.08.2026 08:00  (DOW=3, HOUR=8)   ema_diff=-0.05 rsi=42.0 atr=0.015
                                            feature_id='grid_lines'
  - Fr 07.08.2026 23:00  (DOW=5, HOUR=23)  ema_diff=0.08 rsi=60.0 atr=0.04
                                            (Tagesgrenze: ohne UTC-Forcierung
                                             waere HOUR=1 Sa / DOW=6)

A) FeatureStoreReader.fetch_rows:
   - Zeilenanzahl, Wanduhr-Epoch, feature_data-Parsing
   - E-3: Alt-Row ohne schema_version erhaelt Default "1.0" beim Lesen
   - feature_id-Filter, limit

B) FeatureStoreReader.fetch_heatmap:
   - Matrix 24x7, count/avg an korrekter Zelle
   - leere Zellen (count=0, avg=nan)
   - Tagesgrenze Wanduhr (23:00 Fr -> HOUR=23, DOW=5)  [Invariante 7]
   - ungueltige Metrik -> ValueError

C) AnalyticsRepository:
   - get_table, get_scatter, get_distribution
   - ungueltige Spalten -> ValueError
   - get_available_features
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, r"F:\Python\PyTrader")

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "p15_s3_reader_test.duckdb")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

from db_service import DbPool  # noqa: E402
from analytics.engine.feature_store_reader import (  # noqa: E402
    FeatureStoreReader,
    SCHEMA_VERSION_DEFAULT,
    DOW_LABELS,
    HOURS_PER_DAY,
    DAYS_PER_WEEK,
)
from analytics.engine.analytics_repository import (  # noqa: E402
    AnalyticsRepository,
)

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Test-DB + feature_store-Tabelle + Testdaten anlegen
# ---------------------------------------------------------------------------
con = DbPool.get(TEST_DB)
con.execute("""
    CREATE TABLE IF NOT EXISTS feature_store (
        symbol      VARCHAR NOT NULL,
        timeframe   VARCHAR NOT NULL,
        bar_time    TIMESTAMPTZ NOT NULL,
        ema_diff    DOUBLE,
        rsi_14      DOUBLE,
        atr_normalized DOUBLE,
        created_at  TIMESTAMP DEFAULT current_timestamp,
        feature_id  VARCHAR,
        plugin_version VARCHAR,
        feature_data JSON,
        PRIMARY KEY (symbol, timeframe, bar_time)
    );
""")


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


rows_to_insert = [
    # (bar_time, feature_id, version, ema, rsi, atr, feature_data)
    (_utc(2026, 8, 3, 12), "proximity", "1.0.0", 0.10, 55.0, 0.02,
     {"schema_version": "1.0", "is_hit": True, "in_time_window": True}),
    (_utc(2026, 8, 3, 13), "proximity", "1.0.0", 0.12, 57.0, 0.03,
     {"schema_version": "1.0", "is_hit": False, "in_time_window": False}),
    (_utc(2026, 8, 3, 14), "proximity", "1.0.0", 0.11, 56.0, 0.025,
     {"is_hit": True, "in_time_window": False}),  # Alt-Row OHNE schema_version
    (_utc(2026, 8, 5, 8), "grid_lines", "0.9.0", -0.05, 42.0, 0.015,
     {"schema_version": "1.0"}),
    (_utc(2026, 8, 7, 23), "proximity", "1.0.0", 0.08, 60.0, 0.04,
     {"schema_version": "1.0", "is_hit": True, "in_time_window": False}),
]
for (bt, fid, ver, ema, rsi, atr, fdata) in rows_to_insert:
    con.execute("""
        INSERT INTO feature_store
            (symbol, timeframe, bar_time, feature_id, plugin_version,
             ema_diff, rsi_14, atr_normalized, feature_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ["SILVER", "M1", bt, fid, ver, ema, rsi, atr, json.dumps(fdata)])

reader = FeatureStoreReader(db_path=TEST_DB)
repo = AnalyticsRepository(reader=reader)

# ---------------------------------------------------------------------------
# A) FeatureStoreReader.fetch_rows
# ---------------------------------------------------------------------------
rows = reader.fetch_rows("SILVER", "M1")
check("A1) fetch_rows liefert 5 Zeilen", len(rows) == 5, str(len(rows)))
check("A2) time = Wanduhr-Epoch (int)",
      all(isinstance(r["time"], int) and r["time"] > 0 for r in rows))
check("A3) symbol/timeframe gesetzt",
      all(r["symbol"] == "SILVER" and r["timeframe"] == "M1" for r in rows))

# Erste Zeile: Montag 12:00 -> Epoch
exp_epoch = int(_utc(2026, 8, 3, 12).timestamp())
check("A4) Zeitstempel korrekt (Wanduhr-Epoch)",
      rows[0]["time"] == exp_epoch, f"{rows[0]['time']} != {exp_epoch}")

# feature_data geparst + schema_version
fd0 = rows[0]["feature_data"]
check("A5) feature_data geparst (dict)",
      isinstance(fd0, dict) and fd0.get("is_hit") is True)
check("A6) schema_version-Pflichtfeld vorhanden",
      fd0.get("schema_version") == SCHEMA_VERSION_DEFAULT)

# Alt-Row ohne schema_version -> Default beim Lesen (E-3)
fd_alt = rows[2]["feature_data"]
check("A7) Alt-Row erhaelt schema_version-Default beim Lesen",
      isinstance(fd_alt, dict)
      and fd_alt.get("schema_version") == SCHEMA_VERSION_DEFAULT
      and "is_hit" in fd_alt)

# feature_id-Filter
rows_prox = reader.fetch_rows("SILVER", "M1", feature_id="proximity")
check("A8) feature_id-Filter (proximity -> 4)",
      len(rows_prox) == 4, str(len(rows_prox)))
rows_gl = reader.fetch_rows("SILVER", "M1", feature_id="grid_lines")
check("A9) feature_id-Filter (grid_lines -> 1)",
      len(rows_gl) == 1, str(len(rows_gl)))

# limit
rows_lim = reader.fetch_rows("SILVER", "M1", limit=3)
check("A10) limit=3", len(rows_lim) == 3, str(len(rows_lim)))

# leerer Filter -> []
check("A11) leere Filter -> []", reader.fetch_rows("", "M1") == [])

# ---------------------------------------------------------------------------
# B) FeatureStoreReader.fetch_heatmap
# ---------------------------------------------------------------------------
hm = reader.fetch_heatmap("SILVER", "M1", metric="count")
mat = hm["matrix"]
check("B1) Matrix 24x7",
      len(mat) == HOURS_PER_DAY and all(len(r) == DAYS_PER_WEEK for r in mat))
check("B2) x_labels/y_labels korrekt",
      hm["x_labels"] == list(DOW_LABELS)
      and hm["y_labels"][0] == "00:00" and hm["y_labels"][23] == "23:00")

# count an Mo 12:00 -> Zelle [12][1] == 1 (DOW: 0=So, 1=Mo)
check("B3) count Mo 12:00 == 1", mat[12][1] == 1.0,
      f"mat[12][1]={mat[12][1]}")
# count an Mo 13:00 -> [13][1] == 1, Mo 14:00 -> [14][1] == 1
check("B4) count Mo 13:00 == 1", mat[13][1] == 1.0)
check("B5) count Mo 14:00 == 1 (Alt-Row zaehlt mit)", mat[14][1] == 1.0)

# Tagesgrenze: Fr 23:00 -> HOUR=23, DOW=5 (Wanduhr! Ohne UTC-Forcierung
# waere HOUR=1, DOW=6 – Berlin +2h -> Sa 01:00)
check("B6) Tagesgrenze Wanduhr: Fr 23:00 -> [23][5] == 1",
      mat[23][5] == 1.0, f"mat[23][5]={mat[23][5]} mat[1][6]={mat[1][6]}")
check("B7) keine falsche Zelle Sa 01:00 (ohne UTC waere hier)",
      mat[1][6] == 0.0)

# leere Zelle count == 0
check("B8) leere Zelle count == 0", mat[0][0] == 0.0)

# avg-Metrik
hm_avg = reader.fetch_heatmap("SILVER", "M1", metric="ema_diff")
check("B9) avg ema_diff Mo 12:00 == 0.10",
      abs(hm_avg["matrix"][12][1] - 0.10) < 1e-9,
      str(hm_avg["matrix"][12][1]))
import math
check("B10) leere Zelle avg == nan",
      math.isnan(hm_avg["matrix"][0][0]))

# feature_id-Filter in Heatmap
hm_prox = reader.fetch_heatmap("SILVER", "M1", metric="count",
                               feature_id="proximity")
check("B11) Heatmap feature_id-Filter (proximity: Mi 08:00 == 0)",
      hm_prox["matrix"][8][3] == 0.0, str(hm_prox["matrix"][8][3]))
hm_gl = reader.fetch_heatmap("SILVER", "M1", metric="count",
                             feature_id="grid_lines")
check("B12) Heatmap feature_id-Filter (grid_lines: Mi 08:00 == 1)",
      hm_gl["matrix"][8][3] == 1.0, str(hm_gl["matrix"][8][3]))

# ungueltige Metrik -> ValueError
try:
    reader.fetch_heatmap("SILVER", "M1", metric="bogus")
    check("B13) ungueltige Metrik -> ValueError", False, "kein Fehler")
except ValueError:
    check("B13) ungueltige Metrik -> ValueError", True)

# leerer Filter -> leere Matrix (kein Absturz)
hm_empty = reader.fetch_heatmap("", "M1", metric="count")
check("B14) leerer Filter -> leere Matrix",
      len(hm_empty["matrix"]) == HOURS_PER_DAY)

# ---------------------------------------------------------------------------
# C) AnalyticsRepository
# ---------------------------------------------------------------------------
tab = repo.get_table("SILVER", "M1")
check("C1) get_table rows+total",
      tab["total"] == 5 and len(tab["rows"]) == 5, str(tab["total"]))

scatter = repo.get_scatter("SILVER", "M1", x_column="ema_diff", y_column="rsi_14")
check("C2) get_scatter liefert 5 Punkte (alle non-null)",
      scatter["total"] == 5 and len(scatter["points"]) == 5,
      f"total={scatter['total']}")
check("C3) get_scatter x/y-Keys",
      all(set(p.keys()) == {"x", "y"} for p in scatter["points"]))

dist = repo.get_distribution("SILVER", "M1", column="atr_normalized", bins=4)
check("C4) get_distribution bins+counts",
      len(dist["bins"]) == 5 and len(dist["counts"]) == 4
      and dist["total"] == 5, f"bins={len(dist['bins'])} counts={len(dist['counts'])}")
check("C5) get_distribution counts summieren auf total",
      sum(dist["counts"]) == 5, str(sum(dist["counts"])))

# leere Verteilung (Spalte ohne Daten -> keine Zeilen mit atr)
dist_empty = repo.get_distribution("SILVER", "H4", column="atr_normalized")
check("C6) get_distribution ohne Daten -> leer",
      dist_empty["bins"] == [] and dist_empty["counts"] == [])

# ungueltige Spalten -> ValueError
scatter_bad = [
    ("C7a) ungueltige x-Spalte -> ValueError",
     lambda: repo.get_scatter("SILVER", "M1", x_column="nix", y_column="rsi_14")),
    ("C7b) ungueltige y-Spalte -> ValueError",
     lambda: repo.get_scatter("SILVER", "M1", x_column="ema_diff", y_column="nix")),
    ("C7c) ungueltige Verteilungs-Spalte -> ValueError",
     lambda: repo.get_distribution("SILVER", "M1", column="nix")),
]
for name, fn in scatter_bad:
    try:
        fn()
        check(name, False, "kein Fehler")
    except ValueError:
        check(name, True)

meta = repo.get_available_features("SILVER", "M1")
check("C8) get_available_features",
      meta["feature_ids"] == ["grid_lines", "proximity"]
      and meta["total_rows"] == 5
      and set(meta["columns"]) == {"ema_diff", "rsi_14", "atr_normalized"},
      str(meta))

check("C9) available_heatmap_metrics",
      repo.available_heatmap_metrics() == ["count", "ema_diff", "rsi_14",
                                           "atr_normalized"])

# ---------------------------------------------------------------------------
# Aufraeumen
# ---------------------------------------------------------------------------
try:
    os.remove(TEST_DB)
except OSError:
    pass

print("-" * 60)
if FAILURES:
    print(f"FEHLER: {len(FAILURES)} Pruefung(en) fehlgeschlagen: {FAILURES}")
    sys.exit(1)
print("ALLE PRUEFUNGEN BESTANDEN (OK)")
sys.exit(0)
