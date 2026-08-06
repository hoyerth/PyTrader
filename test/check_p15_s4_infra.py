# test/check_p15_s4_infra.py
"""
Phase 15.04 – Headless Verifikation (Infrastructure & EventBus Hardening).

Prueft angepasst an den Ist-Stand (KEINE UI-Ausfuehrung, offscreen,
Temp-DBs unter test/ – Regel: Tests nur in test/):

 1. EventBus-Bestand (statt Implementierung):
    - Alle 5 Signale existieren auf `event_bus` und sind per connect + emit
      empfangbar (favorites_changed, profile_changed(str),
      service_set_changed, service_run_started, service_run_finished).
    - KEINE Aenderung an config/event_bus.py noetig (Ist-Analyse 05.08.2026).

 2. WindowStateRepository (Temp-DB, Patch analog test/test.py):
    - save_window_geometry/get_window_geometry-Roundtrip (inkl. is_maximized),
    - save_instance_state + load_all_instances (String-Normalisierung),
    - delete_instance (beide Tabellen),
    - get_next_instance_id (win_1, win_2, ...),
    - symbol_tf_state-Roundtrip.
    - Fassaden-Delegation: `StateManager` liefert ueber seine Bestands-
      Methoden identische Werte wie das Repository (gleiche DB).
    - Patch-Strategie (test.py) auf WindowStateRepository erweitert
      (gleiche Temp-DB).

 3. schema_version (harmonisiert):
    - GridLinesService.calculate() und ProximityService.calculate()
      (synthetischer OHLCV-DataFrame) liefern
      payload["metadata"]["schema_version"] == "1.0.0".
    - FeatureStoreReader._normalize_feature_data(None) bzw. Alt-Row ohne
      Feld -> "1.0.0" (Default); vorhandenes Feld bleibt unangetastet;
      DB-Zeile unveraendert.
"""
import os
import sys

sys.path.insert(0, r"F:\Python\PyTrader")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# UTF-8-Konsole erzwingen (wie main.py / test.py)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DB = os.path.join(TEST_DIR, "p15_s4_infra_test.duckdb")
TEST_FS_DB = os.path.join(TEST_DIR, "p15_s4_infra_fs_test.duckdb")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from config.event_bus import event_bus  # noqa: E402
from state_manager import StateManager  # noqa: E402
from window_state_repository import WindowStateRepository  # noqa: E402
from db_service import DbPool  # noqa: E402
from analytics.engine.feature_store_reader import (  # noqa: E402
    FeatureStoreReader,
    SCHEMA_VERSION_DEFAULT,
)

FAILURES = []


def check(name, cond, detail=""):
    s = "PASS" if cond else "FAIL"
    print(f"[{s}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Test-Infrastruktur: frische Temp-DBs unter test/ (Regel: keine Test-DBs im
# Root/data). Die echten DBs (data/*.duckdb) sind durch die laufende App
# gesperrt (DuckDB: Single-Writer) – alle Zugriffe laufen ueber Temp-DBs.
# ---------------------------------------------------------------------------
for _db in (TEST_DB, TEST_FS_DB):
    if os.path.exists(_db):
        os.remove(_db)

# Patch-Strategie analog test/test.py: WindowStateRepository.__init__ wird
# direkt gepatcht (nicht Modul-Attribut), damit ein no-arg-Konstruktor auf
# die gleiche Temp-DB faellt (Test-Isolation gegen die laufende App).
import window_state_repository as _wsr_mod  # noqa: E402
_orig_wsr_init = _wsr_mod.WindowStateRepository.__init__
def _patched_wsr_init(self, db_path=None, *a, **kw):
    _orig_wsr_init(self, db_path or TEST_DB, *a, **kw)
_wsr_mod.WindowStateRepository.__init__ = _patched_wsr_init

sm = StateManager(db_path=TEST_DB)
repo = WindowStateRepository(db_path=TEST_DB)
check("I1) Patch erweitert: WindowStateRepository() faellt auf Temp-DB",
      WindowStateRepository().db_path == TEST_DB, WindowStateRepository().db_path)

# ---------------------------------------------------------------------------
# 1) EventBus-Bestand: 5 Signale existieren, connect + emit empfangbar
# ---------------------------------------------------------------------------
print("\n=== 1) EventBus-Bestand ===")
_fav, _prof, _set, _s_start, _s_fin = [], [], [], [], []
event_bus.favorites_changed.connect(lambda: _fav.append(1))
event_bus.profile_changed.connect(lambda s: _prof.append(s))
event_bus.service_set_changed.connect(lambda: _set.append(1))
event_bus.service_run_started.connect(lambda: _s_start.append(1))
event_bus.service_run_finished.connect(lambda: _s_fin.append(1))

event_bus.favorites_changed.emit()
event_bus.profile_changed.emit("profil_42")
event_bus.service_set_changed.emit()
event_bus.service_run_started.emit()
event_bus.service_run_finished.emit()

check("B1) favorites_changed existiert + empfangbar",
      hasattr(event_bus, "favorites_changed") and _fav == [1], str(_fav))
check("B2) profile_changed(str) existiert + empfangbar (Payload)",
      hasattr(event_bus, "profile_changed") and _prof == ["profil_42"],
      str(_prof))
check("B3) service_set_changed existiert + empfangbar",
      hasattr(event_bus, "service_set_changed") and _set == [1], str(_set))
check("B4) service_run_started existiert + empfangbar (Concurrency-Guard)",
      hasattr(event_bus, "service_run_started") and _s_start == [1],
      str(_s_start))
check("B5) service_run_finished existiert + empfangbar (Concurrency-Guard)",
      hasattr(event_bus, "service_run_finished") and _s_fin == [1],
      str(_s_fin))

# ---------------------------------------------------------------------------
# 2) WindowStateRepository (Temp-DB)
# ---------------------------------------------------------------------------
print("\n=== 2) WindowStateRepository ===")

# 2.1 save_window_geometry/get_window_geometry (inkl. is_maximized)
repo.save_window_geometry("win_1", 150, 120, 640, 400, False, preset_id="p_a")
geom = repo.get_window_geometry("win_1")
check("W1) Geometry-Roundtrip (pos/size/is_maximized/preset_id)",
      geom is not None
      and geom["pos_x"] == 150 and geom["pos_y"] == 120
      and geom["width"] == 640 and geom["height"] == 400
      and geom["is_maximized"] is False,
      str(geom))
repo.save_window_geometry("win_1", 10, 20, 800, 600, True)
geom2 = repo.get_window_geometry("win_1")
check("W2) is_maximized=True + Upsert auf bestehende Instanz",
      geom2 is not None and geom2["is_maximized"] is True
      and geom2["pos_x"] == 10 and geom2["pos_y"] == 20
      and geom2["width"] == 800 and geom2["height"] == 600,
      str(geom2))
check("W3) get_window_geometry(Unbekannte) == None",
      repo.get_window_geometry("win_nope") is None)

# 2.2 save_instance_state + load_all_instances (String-Normalisierung)
repo.save_instance_state(
    "win_1", "SILVER", "M1",
    visible_range_from=1600000000, visible_range_to=1600003600,
    visible_price_from=30.0, visible_price_to=31.0,
    indicators_state={"grid_lines": {"active": True}},
    measurement_state={"hits": 3},
)
insts = repo.load_all_instances()
r1 = next((i for i in insts if i.get("instance_id") == "win_1"), None)
check("W4) load_all_instances liefert Instanz mit Zustand",
      r1 is not None
      and r1["symbol"] == "SILVER" and r1["timeframe"] == "M1"
      and r1["visible_range_from"] == 1600000000
      and r1["visible_price_from"] == 30.0
      and r1["is_maximized"] is True,
      str(r1))
# Bestandsverhalten EXAKT: load_all_instances (pandas-.df()-Leseart) liefert
# indicators_state/measurement_state als rohe JSON-Strings (kein Parsing – die
# Normalisierung betrifft NUR symbol/timeframe). Der String muss sich in das
# urspruengliche Dict aufloesen lassen.
import json as _json_wsr  # noqa: E402
_ind_raw = r1.get("indicators_state") if r1 else None
_meas_raw = r1.get("measurement_state") if r1 else None
_ind_parsed = _json_wsr.loads(_ind_raw) if isinstance(_ind_raw, str) else _ind_raw
_meas_parsed = _json_wsr.loads(_meas_raw) if isinstance(_meas_raw, str) else _meas_raw
check("W5) indicators/measurement JSON im Bestandsformat (rohe Strings)",
      _ind_parsed == {"grid_lines": {"active": True}}
      and _meas_parsed == {"hits": 3},
      f"ind={_ind_raw!r} meas={_meas_raw!r}")
check("W6) String-Normalisierung: symbol/timeframe sind str",
      r1 is not None and isinstance(r1["symbol"], str)
      and isinstance(r1["timeframe"], str))

# NaN->None-Normalisierung: Geometrie OHNE instance_state -> LEFT JOIN
# liefert NULL-Spalten (pandas: NaN) -> werden auf None normalisiert.
repo.save_window_geometry("win_no_state", 5, 6, 100, 100, False)
r_ns = next((i for i in repo.load_all_instances()
             if i.get("instance_id") == "win_no_state"), None)
check("W7) LEFT JOIN ohne instance_state -> symbol/timeframe None (kein NaN)",
      r_ns is not None and r_ns["symbol"] is None and r_ns["timeframe"] is None,
      str(r_ns))

# 2.3 get_next_instance_id (win_1, win_2, ...)
check("W8) get_next_instance_id nach win_1 == 'win_2'",
      repo.get_next_instance_id() == "win_2", repo.get_next_instance_id())
repo.save_window_geometry("win_2", 0, 0, 100, 100, False)
check("W9) get_next_instance_id nach win_2 == 'win_3'",
      repo.get_next_instance_id() == "win_3", repo.get_next_instance_id())

# 2.4 delete_instance (beide Tabellen)
repo.save_instance_state("win_2", "GOLD", "H1")
check("W10) Instanz vor delete vorhanden",
      len([i for i in repo.load_all_instances() if i.get("instance_id") == "win_2"]) == 1)
repo.delete_instance("win_2")
con = DbPool.get(TEST_DB)
inst_rows = con.execute(
    "SELECT COUNT(*) FROM instance_states WHERE instance_id = 'win_2'").fetchone()[0]
win_rows = con.execute(
    "SELECT COUNT(*) FROM window_instances WHERE instance_id = 'win_2'").fetchone()[0]
check("W11) delete_instance raeumt BEIDE Tabellen ab",
      inst_rows == 0 and win_rows == 0, f"inst={inst_rows} win={win_rows}")

# 2.5 symbol_tf_state-Roundtrip
repo.save_symbol_tf_state(
    "SILVER", "M1",
    visible_range_from=1600000000, visible_range_to=1600003600,
    visible_price_from=30.0, visible_price_to=31.0,
    indicators_state={"grid_liquidity": {"active": True}},
    measurement_state={"x": 1},
)
st = repo.get_symbol_tf_state("SILVER", "M1")
check("W12) symbol_tf_state-Roundtrip",
      st is not None
      and st["visible_range_from"] == 1600000000
      and st["visible_price_to"] == 31.0
      and st["indicators_state"] == {"grid_liquidity": {"active": True}}
      and st["measurement_state"] == {"x": 1},
      str(st))
repo.delete_symbol_tf_state("SILVER", "M1")
check("W13) delete_symbol_tf_state entfernt Eintrag",
      repo.get_symbol_tf_state("SILVER", "M1") is None)

# ---------------------------------------------------------------------------
# 2b) Fassaden-Delegation: StateManager liefert identische Werte (gleiche DB)
# ---------------------------------------------------------------------------
print("\n=== 2b) Fassaden-Delegation (StateManager -> Repository) ===")
sm.save_window_geometry("win_10", 111, 222, 333, 444, True, preset_id="p_x")
sm.save_instance_state("win_10", "BTCUSD", "D1",
                       indicators_state={"k": "v"}, measurement_state={"m": 2})
sm.save_symbol_tf_state("GOLD", "H1", visible_price_from=2000.0,
                        indicators_state={"g": 1})
check("F1) get_window_geometry Fassade == Repository",
      sm.get_window_geometry("win_10") == repo.get_window_geometry("win_10"),
      str(sm.get_window_geometry("win_10")))
# ORDER BY s.updated_at ist sekundengenau – mehrere Writes in derselben
# Sekunde haben identische Zeitstempel, daher deterministisch nach
# instance_id sortiert vergleichen (Inhalts-Gleichheit der Fassaden).
# NULL-DOUBLE-Spalten liest pandas als NaN (exaktes Bestandsverhalten) –
# NaN != NaN, daher NaN->None normalisieren.
import math as _math  # noqa: E402
def _norm_nan(v):
    if isinstance(v, float) and _math.isnan(v):
        return None
    return v

def _sorted_instances(records):
    return sorted(
        [{k: _norm_nan(v) for k, v in r.items()} for r in records],
        key=lambda r: r.get("instance_id") or "",
    )

check("F2) load_all_instances Fassade == Repository (sortiert)",
      _sorted_instances(sm.load_all_instances())
      == _sorted_instances(repo.load_all_instances()))
check("F3) get_symbol_tf_state Fassade == Repository",
      sm.get_symbol_tf_state("GOLD", "H1") == repo.get_symbol_tf_state("GOLD", "H1"),
      str(sm.get_symbol_tf_state("GOLD", "H1")))
check("F4) get_next_instance_id Fassade == Repository",
      sm.get_next_instance_id() == repo.get_next_instance_id(),
      f"{sm.get_next_instance_id()} vs {repo.get_next_instance_id()}")
sm.delete_instance("win_10")
check("F5) delete_instance via Fassade raeumt ab (beide Tabellen)",
      sm.get_window_geometry("win_10") is None
      and len([i for i in sm.load_all_instances()
               if i.get("instance_id") == "win_10"]) == 0)
sm.delete_symbol_tf_state("GOLD", "H1")
check("F6) delete_symbol_tf_state via Fassade entfernt",
      sm.get_symbol_tf_state("GOLD", "H1") is None)
# Additive Fassade: die NICHT-instanzbezogenen Bestands-Methoden bleiben
# (Preset-/Settings-CRUD) erhalten.
for _m in ("save_indicator_preset", "get_indicator_preset",
           "list_indicator_presets", "get_app_settings",
           "save_app_settings", "save_dialog_geometry"):
    check(f"F7) Fassade behaelt Bestands-Methode {_m}()",
          hasattr(sm, _m) and callable(getattr(sm, _m)))

# ---------------------------------------------------------------------------
# 3) schema_version (harmonisiert)
# ---------------------------------------------------------------------------
print("\n=== 3) schema_version ===")
import pandas as pd  # noqa: E402
from analytics.features.definitions.grid_lines_service import GridLinesService  # noqa: E402
from analytics.features.definitions.proximity_service import ProximityService  # noqa: E402
from analytics.features.plugins.base_plugin import PluginContext  # noqa: E402

check("V1) SCHEMA_VERSION_DEFAULT harmonisiert auf '1.0.0'",
      SCHEMA_VERSION_DEFAULT == "1.0.0", SCHEMA_VERSION_DEFAULT)

df_synth = pd.DataFrame({
    "time": [1600000000, 1600000360],
    "open": [30.0, 30.2],
    "high": [30.15, 30.4],
    "low": [29.85, 30.1],
    "close": [30.1, 30.25],
})

gl = GridLinesService()
res_gl = gl.calculate(df_synth, {"step_size": 0.5, "steps_around": 4})
meta_gl = (res_gl.get("feature_store_payload") or {}).get("metadata") or {}
check("V2) GridLinesService metadata.schema_version == '1.0.0'",
      meta_gl.get("schema_version") == "1.0.0", str(meta_gl))

_lines = [{"price": 30.0}, {"price": 30.5}, {"price": 29.5}]
ctx = PluginContext(
    symbol="SILVER", timeframe="M1", mode="batch",
    shared_state={"g1": _lines}, depends_on=["g1"], instance_id="p1",
)
prox = ProximityService()
res_prox = prox.calculate(
    df_synth,
    {"visit_pct": 0.05, "time_window_mins": 5, "use_time_filter": True},
    context=ctx,
)
meta_prox = (res_prox.get("feature_store_payload") or {}).get("metadata") or {}
check("V3) ProximityService metadata.schema_version == '1.0.0'",
      meta_prox.get("schema_version") == "1.0.0", str(meta_prox))

# _normalize_feature_data: None/Alt-Row -> "1.0.0"; vorhandenes Feld bleibt.
check("V4) _normalize_feature_data(None) -> {'schema_version': '1.0.0'}",
      FeatureStoreReader._normalize_feature_data(None)
      == {"schema_version": "1.0.0"},
      str(FeatureStoreReader._normalize_feature_data(None)))
check("V5) vorhandenes schema_version bleibt unangetastet",
      FeatureStoreReader._normalize_feature_data('{"schema_version":"1.2.3","a":1}')
      == {"schema_version": "1.2.3", "a": 1},
      str(FeatureStoreReader._normalize_feature_data('{"schema_version":"1.2.3","a":1}')))

# DB-Zeile unveraendert: Alt-Row OHNE schema_version in feature_data wird
# beim Lesen additiv ergaenzt, aber die DB-Zeile selbst bleibt identisch.
import duckdb as _duckdb  # noqa: E402
_fs_con = _duckdb.connect(TEST_FS_DB)
_fs_con.execute("""
    CREATE TABLE feature_store (
        symbol VARCHAR, timeframe VARCHAR, bar_time TIMESTAMPTZ,
        ema_diff DOUBLE, rsi_14 DOUBLE, atr_normalized DOUBLE,
        feature_id VARCHAR, plugin_version VARCHAR, feature_data JSON
    )
""")
_fs_con.execute("""
    INSERT INTO feature_store (symbol, timeframe, bar_time, feature_id,
                               plugin_version, feature_data)
    VALUES ('SILVER', 'M1', TIMESTAMPTZ '2026-08-01 10:00:00+00', 'grid_lines',
            '1.0.0', '{"step_size": 0.5}')
""")
_fs_con.close()

fs_reader = FeatureStoreReader(db_path=TEST_FS_DB)
rows = fs_reader.fetch_rows("SILVER", "M1", feature_id="grid_lines")
check("V6) Alt-Row ohne schema_version -> Lesedefault '1.0.0'",
      len(rows) == 1
      and rows[0]["feature_data"].get("schema_version") == "1.0.0",
      str([r.get("feature_data") for r in rows]))
_raw = DbPool.get(TEST_FS_DB).execute(
    "SELECT feature_data FROM feature_store LIMIT 1").fetchone()[0]
import json as _json  # noqa: E402
raw_dict = _raw if isinstance(_raw, dict) else (
    _json.loads(_raw) if isinstance(_raw, str) else {})
check("V7) DB-Zeile bleibt unveraendert (kein schema_version geschrieben)",
      "schema_version" not in raw_dict and raw_dict.get("step_size") == 0.5,
      str(raw_dict))

# ---------------------------------------------------------------------------
# Aufraeumen (best effort – DbPool-Connections enden mit dem Prozess)
# ---------------------------------------------------------------------------
for _db in (TEST_DB, TEST_FS_DB):
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
