# test/check_p15_s3_analytics.py
"""
Phase 15 15.03 Schritt 6 – Headless Gesamt-Validierung (KEINE UI, KEIN
QApplication.exec()). Test-DBs in test/ (Regel: keine Test-DBs im Root/data).

A) Analytics-Profile-CRUD + schema_version-Pflichtfeld (app_data)
B) SQL-Aggregationen: fetch_rows/heatmap/scatter/distribution + NEUE
   Jump-to-Chart-Methoden get_latest_bar_time / get_recent_bar_time_for_cell
   (Wanduhr-Garantie, Invariante 7)
C) AnalyticsViewModel: Profil-Verwaltung (Dirty/Save) + Jump-to-Chart-
   Resolution mit echtem AnalyticsRepository
D) E-2-Migration: win_statistics -> win_analytics (StateManager, app_data)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, r"F:\Python\PyTrader")

from PySide6.QtCore import QCoreApplication  # noqa: E402

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

from db_service import DbPool  # noqa: E402
from state_manager import StateManager  # noqa: E402
from analytics.engine.feature_store_reader import (  # noqa: E402
    FeatureStoreReader,
    SCHEMA_VERSION_DEFAULT,
    HOURS_PER_DAY,
    DAYS_PER_WEEK,
)
from analytics.engine.analytics_repository import (  # noqa: E402
    AnalyticsRepository,
)
from analytics.engine.analytics_view_model import (  # noqa: E402
    AnalyticsViewModel,
)
from analytics_profile_repository import (  # noqa: E402
    AnalyticsProfileRepository,
    SCHEMA_VERSION_DEFAULT as PROFILE_SCHEMA_VERSION,
)
from analytics.ui.analytics_win import (  # noqa: E402
    migrate_statistics_persistence,
)

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DB_ANALYTICS = os.path.join(TEST_DIR, "p15_s3_analytics_test.duckdb")
TEST_DB_APP = os.path.join(TEST_DIR, "p15_s3_analytics_app.duckdb")
TEST_DB_MIGRATION = os.path.join(TEST_DIR, "p15_s3_migration_test.duckdb")
for _db in (TEST_DB_ANALYTICS, TEST_DB_APP, TEST_DB_MIGRATION):
    if os.path.exists(_db):
        os.remove(_db)

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test-DB analytics: feature_store mit Wanduhr-encoded Testdaten
# ---------------------------------------------------------------------------
con_ana = DbPool.get(TEST_DB_ANALYTICS)
con_ana.execute("""
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
rows_to_insert = [
    # (bar_time, feature_id, version, ema, rsi, atr, feature_data)
    (_utc(2026, 8, 3, 12), "proximity", "1.0.0", 0.10, 55.0, 0.02,
     {"schema_version": "1.0", "is_hit": True}),
    (_utc(2026, 8, 3, 13), "proximity", "1.0.0", 0.12, 57.0, 0.03,
     {"schema_version": "1.0", "is_hit": False}),
    (_utc(2026, 8, 3, 14), "proximity", "1.0.0", 0.11, 56.0, 0.025,
     {"is_hit": True}),  # Alt-Row OHNE schema_version (E-3)
    (_utc(2026, 8, 5, 8), "grid_lines", "0.9.0", -0.05, 42.0, 0.015,
     {"schema_version": "1.0"}),
    (_utc(2026, 8, 7, 23), "proximity", "1.0.0", 0.08, 60.0, 0.04,
     {"schema_version": "1.0", "is_hit": True}),
]
for (bt, fid, ver, ema, rsi, atr, fdata) in rows_to_insert:
    con_ana.execute("""
        INSERT INTO feature_store
            (symbol, timeframe, bar_time, feature_id, plugin_version,
             ema_diff, rsi_14, atr_normalized, feature_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ["SILVER", "M1", bt, fid, ver, ema, rsi, atr, json.dumps(fdata)])

reader = FeatureStoreReader(db_path=TEST_DB_ANALYTICS)
repo = AnalyticsRepository(reader=reader)

EPOCH_MO_12 = int(_utc(2026, 8, 3, 12).timestamp())
EPOCH_FR_23 = int(_utc(2026, 8, 7, 23).timestamp())

# ---------------------------------------------------------------------------
# A) Analytics-Profile-CRUD + schema_version
# ---------------------------------------------------------------------------
prepo = AnalyticsProfileRepository(db_path=TEST_DB_APP)
check("A1) anfangs 0 Profile", prepo.count() == 0)

pid = prepo.create_profile(
    name="Standard", payload={"view": "heatmap", "lookback": 5000},
    description="Default",
)
p = prepo.get_profile(pid)
check("A2) create + get", p is not None and p["name"] == "Standard")
check("A3) schema_version-Pflichtfeld (Default 1)",
      p["payload"].get("schema_version") == PROFILE_SCHEMA_VERSION)
check("A4) get_profile_by_name case-insensitive",
      prepo.get_profile_by_name("standard")["profile_id"] == pid)

pid2 = prepo.create_profile(name="Alpha", payload={"view": "scatter"})
names = [x["name"] for x in prepo.list_profiles()]
check("A5) list_profiles sortiert", names == sorted(names), str(names))

check("A6) update additiv",
      prepo.update_profile(pid, payload={"view": "table"}) is True
      and prepo.get_profile(pid)["payload"]["view"] == "table"
      and prepo.get_profile(pid)["description"] == "Default")
check("A7) update ergaenzt schema_version additiv",
      prepo.get_profile(pid)["payload"].get("schema_version") == PROFILE_SCHEMA_VERSION)

check("A8) genau EIN aktives Profil",
      prepo.set_active(pid) is True and prepo.set_active(pid2) is True
      and prepo.get_active_profile()["profile_id"] == pid2
      and prepo.get_profile(pid)["is_active"] is False)

# Alt-Row ohne schema_version -> Default beim Lesen
con_app = DbPool.get(TEST_DB_APP)
con_app.execute("""
    UPDATE analytics_profiles SET payload = CAST(? AS JSON) WHERE profile_id = ?
""", [json.dumps({"view": "alt"}), pid])
check("A9) Alt-Row erhaelt schema_version-Default beim Lesen",
      prepo.get_profile(pid)["payload"].get("schema_version") == PROFILE_SCHEMA_VERSION)

check("A10) delete + count",
      prepo.delete_profile(pid2) is True and prepo.delete_profile(pid) is True
      and prepo.count() == 0)

# ---------------------------------------------------------------------------
# B) SQL-Aggregationen + NEUE Jump-to-Chart-Methoden
# ---------------------------------------------------------------------------
rows = reader.fetch_rows("SILVER", "M1")
check("B1) fetch_rows 5 Zeilen", len(rows) == 5)
check("B2) Alt-Row schema_version-Default beim Lesen",
      rows[2]["feature_data"].get("schema_version") == SCHEMA_VERSION_DEFAULT)

hm = repo.get_heatmap("SILVER", "M1", metric="count")
check("B3) Heatmap 24x7", len(hm["matrix"]) == HOURS_PER_DAY)
check("B4) Heatmap Mo 12:00 count == 1", hm["matrix"][12][1] == 1.0)
check("B5) Tagesgrenze Wanduhr Fr 23:00 -> [23][5]",
      hm["matrix"][23][5] == 1.0 and hm["matrix"][1][6] == 0.0)

sc = repo.get_scatter("SILVER", "M1", x_column="ema_diff", y_column="rsi_14")
check("B6) Scatter 5 Punkte", sc["total"] == 5 and len(sc["points"]) == 5)

di = repo.get_distribution("SILVER", "M1", column="atr_normalized", bins=4)
check("B7) Verteilung bins/counts",
      len(di["bins"]) == 5 and sum(di["counts"]) == 5)

# NEU (Schritt 5): Jump-to-Chart-Aufloesung
check("B8) get_latest_bar_time = Fr 23:00 (max)",
      repo.get_latest_bar_time("SILVER", "M1") == EPOCH_FR_23,
      str(repo.get_latest_bar_time("SILVER", "M1")))
check("B9) get_latest_bar_time leer -> None",
      repo.get_latest_bar_time("", "M1") is None)
check("B10) get_recent_bar_time_for_cell (Mo 12:00)",
      repo.get_recent_bar_time_for_cell("SILVER", "M1", 1, 12) == EPOCH_MO_12,
      str(repo.get_recent_bar_time_for_cell("SILVER", "M1", 1, 12)))
check("B11) get_recent_bar_time_for_cell (Fr 23:00, Tagesgrenze)",
      repo.get_recent_bar_time_for_cell("SILVER", "M1", 5, 23) == EPOCH_FR_23)
check("B12) get_recent_bar_time_for_cell ohne Daten -> None",
      repo.get_recent_bar_time_for_cell("SILVER", "M1", 0, 5) is None)
check("B13) get_recent_bar_time_for_cell ungueltige Zelle -> None",
      repo.get_recent_bar_time_for_cell("SILVER", "M1", 9, 5) is None
      and repo.get_recent_bar_time_for_cell("SILVER", "M1", 1, 30) is None)
check("B14) get_recent_bar_time_for_cell feature_id-Filter",
      repo.get_recent_bar_time_for_cell("SILVER", "M1", 5, 23,
                                        feature_id="grid_lines") is None
      and repo.get_recent_bar_time_for_cell("SILVER", "M1", 5, 23,
                                            feature_id="proximity") == EPOCH_FR_23)

# ---------------------------------------------------------------------------
# C) AnalyticsViewModel: Profil + Dirty/Save + Jump-to-Chart-Resolution
# ---------------------------------------------------------------------------
vm = AnalyticsViewModel(analytics_repo=repo, profile_repo=prepo)
vm.set_symbol("SILVER")
vm.set_timeframe("M1")

pid_vm = vm.create_profile("VM-Profil")
check("C1) create_profile -> aktiv", vm.active_profile is not None
      and vm.active_profile["name"] == "VM-Profil")
check("C2) anfangs nicht dirty", vm.is_dirty is False)

vm.set_heatmap_metric("ema_diff")
check("C3) Parametertrend -> dirty", vm.is_dirty is True)
check("C4) save -> dirty False + Payload persistiert",
      vm.save_profile() is True and vm.is_dirty is False
      and prepo.get_profile(pid_vm)["payload"]["heatmap_metric"] == "ema_diff"
      and prepo.get_profile(pid_vm)["payload"]["schema_version"] == PROFILE_SCHEMA_VERSION)

check("C5) resolve_latest_bar_time via ViewModel",
      vm.resolve_latest_bar_time("SILVER", "M1") == EPOCH_FR_23)
check("C6) resolve_recent_bar_time_for_cell via ViewModel",
      vm.resolve_recent_bar_time_for_cell("SILVER", "M1", 1, 12) == EPOCH_MO_12)
check("C7) resolve ohne Daten -> None",
      vm.resolve_latest_bar_time("SILVER", "H4") is None)

vm.shutdown()

# ---------------------------------------------------------------------------
# D) E-2-Migration: win_statistics -> win_analytics (StateManager)
# ---------------------------------------------------------------------------
sm = StateManager(db_path=TEST_DB_MIGRATION)
sm.save_window_geometry("win_statistics", 120, 80, 900, 620, False)
sm.save_instance_state("win_statistics", "SILVER", "H1")

check("D1) win_statistics vor Migration vorhanden",
      sm.get_window_geometry("win_statistics") is not None)
check("D2) win_analytics vor Migration leer",
      sm.get_window_geometry("win_analytics") is None)

migrated = migrate_statistics_persistence(sm)
check("D3) Migration liefert True", migrated is True)
check("D4) Geometrie nach win_analytics kopiert",
      sm.get_window_geometry("win_analytics") is not None
      and sm.get_window_geometry("win_analytics")["width"] == 900
      and sm.get_window_geometry("win_analytics")["pos_x"] == 120)
insts = {i["instance_id"]: i for i in sm.load_all_instances()}
check("D5) Instanz-Zustand nach win_analytics kopiert",
      insts.get("win_analytics", {}).get("symbol") == "SILVER"
      and insts["win_analytics"]["timeframe"] == "H1")
check("D6) win_statistics entfernt",
      "win_statistics" not in insts
      and sm.get_window_geometry("win_statistics") is None)

check("D7) Idempotenz: zweiter Aufruf -> False",
      migrate_statistics_persistence(sm) is False)

# D8) Bestehende win_analytics-Geometrie wird NICHT ueberschrieben
sm2 = StateManager(db_path=TEST_DB_MIGRATION)
sm2.save_window_geometry("win_analytics", 10, 10, 1280, 800, True)
sm2.save_window_geometry("win_statistics", 1, 1, 100, 100, False)
migrated2 = migrate_statistics_persistence(sm2)
geom_ana = sm2.get_window_geometry("win_analytics")
check("D8) bestehende win_analytics-Geometrie bleibt (kein Overwrite)",
      migrated2 is False and geom_ana is not None
      and geom_ana["width"] == 1280 and geom_ana["pos_x"] == 10)
check("D9) win_statistics trotzdem entfernt",
      sm2.get_window_geometry("win_statistics") is None)

# ---------------------------------------------------------------------------
# Aufraeumen
# ---------------------------------------------------------------------------
for _db in (TEST_DB_ANALYTICS, TEST_DB_APP, TEST_DB_MIGRATION):
    try:
        os.remove(_db)
    except OSError:
        pass

print("-" * 60)
if FAILURES:
    print(f"FEHLER: {len(FAILURES)} Pruefung(en) fehlgeschlagen: {FAILURES}")
    sys.exit(1)
print("ALLE PRUEFUNGEN BESTANDEN (OK)")
sys.exit(0)
