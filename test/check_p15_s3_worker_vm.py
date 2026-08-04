# test/check_p15_s3_worker_vm.py
"""
Phase 15 15.03 Schritt 4 – Headless Validierung (KEINE UI, KEIN QApplication.exec()).

Prueft den AnalyticsAsyncWorker (analytics/engine/analytics_worker.py) und
das AnalyticsViewModel (analytics/engine/analytics_view_model.py) auf
Logik-/DB-Ebene mit Test-DBs in test/ (Regel: keine Test-DBs im Root/data).
Es wird NUR QCoreApplication (QtCore, ohne GUI) + processEvents() genutzt.

A) Worker-Dispatch & Max-Lookback-Cap (synchron, RecordingRepo-Stub):
   - table/heatmap/scatter/distribution/features werden korrekt dispatched
   - limit wird hart auf MAX_LOOKBACK_LIMIT (50.000) gedeckelt
   - unbekannter query_kind -> failed-Signal

B) Worker mit echtem AnalyticsRepository + Test-DB (synchron, run() direkt):
   - get_table/get_heatmap/get_scatter/get_distribution/get_available_features

C) AnalyticsViewModel – Profil & Dirty (ohne Event-Loop):
   - create -> aktives Profil + EventBus profile_changed
   - Parametertrend -> dirty True; save -> dirty False + Payload persistiert
   - set_active/delete; set_limit-Cap; Duplikat-Name -> ValueError

D) AnalyticsViewModel – asynchroner Datenfluss (QCoreApplication +
   processEvents, Worker-Thread + Debounce-QTimer):
   - set_symbol/set_timeframe + Debounce -> data_ready fuer alle Kinds
   - busy_changed True->False (Progress-Spinner)
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
from analytics.engine.feature_store_reader import (  # noqa: E402
    FeatureStoreReader,
    HOURS_PER_DAY,
    DAYS_PER_WEEK,
)
from analytics.engine.analytics_repository import (  # noqa: E402
    AnalyticsRepository,
)
from analytics.engine.analytics_worker import (  # noqa: E402
    AnalyticsAsyncWorker,
    QUERY_TABLE,
    QUERY_HEATMAP,
    QUERY_SCATTER,
    QUERY_DISTRIBUTION,
    QUERY_FEATURES,
    MAX_LOOKBACK_LIMIT,
    cap_lookback_limit,
)
from analytics.engine.analytics_view_model import (  # noqa: E402
    AnalyticsViewModel,
    DEFAULT_BINS,
    DEFAULT_LIMIT,
)
from analytics_profile_repository import (  # noqa: E402
    AnalyticsProfileRepository,
    SCHEMA_VERSION_DEFAULT,
)
from config.event_bus import event_bus  # noqa: E402

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DB_ANALYTICS = os.path.join(TEST_DIR, "p15_s3_worker_analytics.duckdb")
TEST_DB_APP = os.path.join(TEST_DIR, "p15_s3_worker_app.duckdb")
for _db in (TEST_DB_ANALYTICS, TEST_DB_APP):
    if os.path.exists(_db):
        os.remove(_db)

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def run_until(condition, timeout_s: float = 6.0) -> bool:
    """Verarbeitet Qt-Events (QCoreApplication.processEvents) bis Bedingung."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return condition()


# ---------------------------------------------------------------------------
# Test-DB: feature_store (analytics) mit Wanduhr-encoded Testdaten
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


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


rows_to_insert = [
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


# ---------------------------------------------------------------------------
# A) Worker-Dispatch & Max-Lookback-Cap (synchron, Stub)
# ---------------------------------------------------------------------------
class RecordingRepo:
    """Stub-Repository: zeichnet die erhaltenen Argumente auf."""

    def __init__(self):
        self.calls: list = []

    def get_table(self, symbol, timeframe, feature_id=None, limit=None):
        self.calls.append(("table", symbol, timeframe, feature_id, limit))
        return {"rows": [], "total": 0}

    def get_heatmap(self, symbol, timeframe, metric="count", feature_id=None):
        self.calls.append(("heatmap", symbol, timeframe, metric, feature_id))
        return {"matrix": [], "x_labels": [], "y_labels": []}

    def get_scatter(self, symbol, timeframe, x_column="ema_diff", y_column="rsi_14",
                    feature_id=None, limit=None):
        self.calls.append(("scatter", symbol, timeframe, x_column, y_column,
                           feature_id, limit))
        return {"points": [], "x_label": x_column, "y_label": y_column, "total": 0}

    def get_distribution(self, symbol, timeframe, column="atr_normalized",
                         bins=20, feature_id=None, limit=None):
        self.calls.append(("dist", symbol, timeframe, column, bins, feature_id,
                           limit))
        return {"bins": [], "counts": [], "column": column, "total": 0}

    def get_available_features(self, symbol, timeframe):
        self.calls.append(("features", symbol, timeframe))
        return {"feature_ids": [], "columns": [], "total_rows": 0}


def run_worker_sync(stub, kind, params):
    captured = {}
    w = AnalyticsAsyncWorker(stub, kind, params)
    w.finished_ok.connect(lambda k, d: captured.__setitem__(k, d))
    w.failed.connect(lambda k, e: captured.__setitem__(k, e))
    w.run()
    return captured


# A1) Cap: limit=100000 -> 50000
stub = RecordingRepo()
res = run_worker_sync(stub, QUERY_TABLE, {"symbol": "S", "timeframe": "M1",
                                          "limit": 100_000})
check("A1) table dispatch + limit-Cap (100000 -> 50000)",
      stub.calls and stub.calls[0][0] == "table"
      and stub.calls[0][4] == MAX_LOOKBACK_LIMIT
      and res.get(QUERY_TABLE) == {"rows": [], "total": 0},
      str(stub.calls))

# A2) limit=None bleibt None (Repo-Default)
stub = RecordingRepo()
run_worker_sync(stub, QUERY_TABLE, {"symbol": "S", "timeframe": "M1",
                                    "limit": None})
check("A2) limit=None bleibt None (kein Cap-Eingriff)",
      stub.calls and stub.calls[0][4] is None, str(stub.calls))

# A3) limit negativ -> 1
stub = RecordingRepo()
run_worker_sync(stub, QUERY_TABLE, {"symbol": "S", "timeframe": "M1",
                                    "limit": -7})
check("A3) limit<1 -> 1 (Untergrenze)",
      stub.calls and stub.calls[0][4] == 1, str(stub.calls))

# A4) cap_lookback_limit als Funktion
check("A4) cap_lookback_limit direkt",
      cap_lookback_limit(10 ** 9) == MAX_LOOKBACK_LIMIT
      and cap_lookback_limit("x") is None
      and cap_lookback_limit(None) is None)

# A5) Heatmap-Dispatch (metric + feature_id)
stub = RecordingRepo()
run_worker_sync(stub, QUERY_HEATMAP,
                {"symbol": "S", "timeframe": "M1", "metric": "rsi_14",
                 "feature_id": "prox"})
check("A5) heatmap dispatch (metric/feature_id)",
      stub.calls and stub.calls[0][0] == "heatmap"
      and stub.calls[0][3] == "rsi_14" and stub.calls[0][4] == "prox",
      str(stub.calls))

# A6) Scatter-Dispatch (Spalten + limit)
stub = RecordingRepo()
run_worker_sync(stub, QUERY_SCATTER,
                {"symbol": "S", "timeframe": "M1", "x_column": "ema_diff",
                 "y_column": "atr_normalized", "limit": 5000})
check("A6) scatter dispatch",
      stub.calls and stub.calls[0][0] == "scatter"
      and stub.calls[0][3] == "ema_diff" and stub.calls[0][4] == "atr_normalized"
      and stub.calls[0][6] == 5000, str(stub.calls))

# A7) Distribution-Dispatch (column/bins)
stub = RecordingRepo()
run_worker_sync(stub, QUERY_DISTRIBUTION,
                {"symbol": "S", "timeframe": "M1", "column": "rsi_14",
                 "bins": 8, "limit": 1000})
check("A7) distribution dispatch",
      stub.calls and stub.calls[0][0] == "dist"
      and stub.calls[0][3] == "rsi_14" and stub.calls[0][4] == 8
      and stub.calls[0][6] == 1000, str(stub.calls))

# A8) Features-Dispatch
stub = RecordingRepo()
run_worker_sync(stub, QUERY_FEATURES, {"symbol": "S", "timeframe": "M1"})
check("A8) features dispatch",
      stub.calls and stub.calls[0][0] == "features"
      and stub.calls[0][1] == "S" and stub.calls[0][2] == "M1", str(stub.calls))

# A9) unbekannter query_kind -> failed-Signal
stub = RecordingRepo()
captured = {}
w = AnalyticsAsyncWorker(stub, "bogus", {"symbol": "S", "timeframe": "M1"})
w.finished_ok.connect(lambda k, d: captured.__setitem__(k, d))
w.failed.connect(lambda k, e: captured.__setitem__(k, e))
w.run()
check("A9) unbekannter query_kind -> failed",
      "bogus" in captured and "Unbekannte" in str(captured["bogus"]),
      str(captured))

# ---------------------------------------------------------------------------
# B) Worker mit echtem AnalyticsRepository + Test-DB (synchron)
# ---------------------------------------------------------------------------
cap = {}
w = AnalyticsAsyncWorker(repo, QUERY_TABLE,
                         {"symbol": "SILVER", "timeframe": "M1", "limit": 5000})
w.finished_ok.connect(lambda k, d: cap.__setitem__(k, d))
w.failed.connect(lambda k, e: cap.__setitem__(k, e))
w.run()
tab = cap.get(QUERY_TABLE)
check("B1) get_table via Worker (total=5, rows=5)",
      tab is not None and tab["total"] == 5 and len(tab["rows"]) == 5,
      str(tab))

cap2 = {}
w = AnalyticsAsyncWorker(repo, QUERY_HEATMAP,
                         {"symbol": "SILVER", "timeframe": "M1",
                          "metric": "count"})
w.finished_ok.connect(lambda k, d: cap2.__setitem__(k, d))
w.failed.connect(lambda k, e: cap2.__setitem__(k, e))
w.run()
hm = cap2.get(QUERY_HEATMAP)
check("B2) get_heatmap via Worker (24x7, Mo 12:00 == 1)",
      hm is not None and len(hm["matrix"]) == HOURS_PER_DAY
      and hm["matrix"][12][1] == 1.0, str(hm)[:120])

cap3 = {}
w = AnalyticsAsyncWorker(repo, QUERY_SCATTER,
                         {"symbol": "SILVER", "timeframe": "M1",
                          "x_column": "ema_diff", "y_column": "rsi_14"})
w.finished_ok.connect(lambda k, d: cap3.__setitem__(k, d))
w.failed.connect(lambda k, e: cap3.__setitem__(k, e))
w.run()
sc = cap3.get(QUERY_SCATTER)
check("B3) get_scatter via Worker (5 Punkte)",
      sc is not None and sc["total"] == 5 and len(sc["points"]) == 5, str(sc))

cap4 = {}
w = AnalyticsAsyncWorker(repo, QUERY_DISTRIBUTION,
                         {"symbol": "SILVER", "timeframe": "M1",
                          "column": "atr_normalized", "bins": 4})
w.finished_ok.connect(lambda k, d: cap4.__setitem__(k, d))
w.failed.connect(lambda k, e: cap4.__setitem__(k, e))
w.run()
di = cap4.get(QUERY_DISTRIBUTION)
check("B4) get_distribution via Worker (bins=4)",
      di is not None and len(di["bins"]) == 5 and di["total"] == 5, str(di))

cap5 = {}
w = AnalyticsAsyncWorker(repo, QUERY_FEATURES,
                         {"symbol": "SILVER", "timeframe": "M1"})
w.finished_ok.connect(lambda k, d: cap5.__setitem__(k, d))
w.failed.connect(lambda k, e: cap5.__setitem__(k, e))
w.run()
fe = cap5.get(QUERY_FEATURES)
check("B5) get_available_features via Worker",
      fe is not None and fe["feature_ids"] == ["grid_lines", "proximity"]
      and fe["total_rows"] == 5, str(fe))

# ---------------------------------------------------------------------------
# C) AnalyticsViewModel – Profil & Dirty (ohne Event-Loop)
# ---------------------------------------------------------------------------
prepo = AnalyticsProfileRepository(db_path=TEST_DB_APP)
vm = AnalyticsViewModel(analytics_repo=repo, profile_repo=prepo)

events: list = []
bus_events: list = []
vm.profiles_available.connect(lambda lst: events.append(("list", len(lst))))
vm.active_profile_changed.connect(
    lambda p: events.append(("active", p["name"] if p else None)))
vm.dirty_changed.connect(lambda d: events.append(("dirty", d)))
vm.profile_saved.connect(lambda pid: events.append(("saved", pid)))
vm.profile_deleted.connect(lambda pid: events.append(("deleted", pid)))
event_bus.profile_changed.connect(lambda name: bus_events.append(name))

check("C1) anfangs kein aktives Profil", vm.active_profile is None
      and vm.is_dirty is False)

pid = vm.create_profile("Standard", description="Default")
check("C2) create_profile -> aktiv + events",
      pid is not None and vm.active_profile is not None
      and vm.active_profile["name"] == "Standard"
      and vm.is_dirty is False)
check("C3) EventBus profile_changed bei create",
      bus_events and bus_events[-1] == "Standard", str(bus_events))
p = prepo.get_profile(pid)
check("C4) Payload enthaelt schema_version",
      p is not None and p["payload"].get("schema_version") == SCHEMA_VERSION_DEFAULT)

# Duplikat-Name -> ValueError
try:
    vm.create_profile("Standard")
    check("C5) Duplikat-Name -> ValueError", False, "kein Fehler")
except ValueError:
    check("C5) Duplikat-Name -> ValueError", True)

# Parametertrend -> dirty True
vm.set_symbol("SILVER")
vm.set_timeframe("M1")
vm.set_heatmap_metric("ema_diff")
check("C6) Parametertrends setzen dirty",
      vm.is_dirty is True and vm.params["symbol"] == "SILVER"
      and vm.params["heatmap_metric"] == "ema_diff")

# Save -> dirty False + Payload persistiert
check("C7) save_profile liefert True", vm.save_profile() is True)
check("C8) nach Save dirty False", vm.is_dirty is False)
p = prepo.get_profile(pid)
check("C9) Payload nach Save persistiert (symbol/metric)",
      p is not None and p["payload"].get("symbol") == "SILVER"
      and p["payload"].get("heatmap_metric") == "ema_diff"
      and p["payload"].get("schema_version") == SCHEMA_VERSION_DEFAULT,
      str(p["payload"]) if p else "None")

# Zweites Profil + set_active
pid2 = vm.create_profile("Zweites")
check("C10) Zweites Profil aktiv", vm.active_profile["profile_id"] == pid2)
check("C11) set_active liefert True", vm.set_active_profile(pid) is True)
check("C12) aktives Profil im Repo umgeschaltet",
      prepo.get_active_profile()["profile_id"] == pid
      and prepo.get_profile(pid2)["is_active"] is False)
check("C13) set_active unbekannt -> False", vm.set_active_profile("gibtsnicht") is False)

# limit-Cap im ViewModel
vm.set_limit(100_000)
check("C14) set_limit-Cap (100000 -> 50000)",
      vm.params["limit"] == MAX_LOOKBACK_LIMIT and vm.is_dirty is True)
vm.set_limit(-3)
check("C15) set_limit-Untergrenze (-> 1)", vm.params["limit"] == 1)

# Delete
check("C16) delete unbekannt -> False", vm.delete_profile("gibtsnicht") is False)
check("C17) delete Profil", vm.delete_profile(pid2) is True)
check("C18) delete aktives Profil",
      vm.delete_profile(pid) is True and vm.active_profile is None
      and vm.is_dirty is False)
check("C19) kein Profil mehr aktiv", prepo.get_active_profile() is None)

# save ohne aktives Profil -> False
vm2 = AnalyticsViewModel(analytics_repo=repo, profile_repo=prepo)
check("C20) save ohne aktives Profil -> False", vm2.save_profile() is False)

# Datenfluss-Properties
check("C21) heatmap_metrics/native_columns via ViewModel",
      vm2.heatmap_metrics == ["count", "ema_diff", "rsi_14", "atr_normalized"]
      and set(vm2.native_columns) == {"ema_diff", "rsi_14", "atr_normalized"})
check("C22) max_lookback_limit Property",
      vm2.max_lookback_limit == MAX_LOOKBACK_LIMIT)
check("C23) Default-Parameter", vm2.params["bins"] == DEFAULT_BINS
      and vm2.params["limit"] == DEFAULT_LIMIT)

vm.shutdown()
vm2.shutdown()

# ---------------------------------------------------------------------------
# D) AnalyticsViewModel – asynchroner Datenfluss (Event-Loop + Worker-Thread)
# ---------------------------------------------------------------------------
received: dict = {}
busy: list = []
vm3 = AnalyticsViewModel(analytics_repo=repo, profile_repo=prepo)
vm3.data_ready.connect(lambda k, d: received.__setitem__(k, d))
vm3.busy_changed.connect(busy.append)
vm3.query_failed.connect(
    lambda k, e: received.__setitem__(("failed", k), e))

vm3.set_symbol("SILVER")
vm3.set_timeframe("M1")

check("D1) data_ready fuer table nach Debounce+Worker",
      run_until(lambda: QUERY_TABLE in received))
check("D2) table-Daten korrekt (total=5)",
      received.get(QUERY_TABLE, {}).get("total") == 5,
      str(received.get(QUERY_TABLE)))

check("D3) alle 5 Kinds nach Debounce+Worker",
      run_until(lambda: all(k in received for k in (
          QUERY_TABLE, QUERY_HEATMAP, QUERY_SCATTER,
          QUERY_DISTRIBUTION, QUERY_FEATURES))))
check("D4) heatmap-Daten (Mo 12:00 == 1)",
      received[QUERY_HEATMAP]["matrix"][12][1] == 1.0)
check("D5) features-Daten",
      received[QUERY_FEATURES]["feature_ids"] == ["grid_lines", "proximity"])
check("D6) busy_changed True und False (Progress-Spinner)",
      busy.count(True) >= 1 and busy.count(False) >= 1, str(busy))
check("D7) keine query_failed", not any(k == ("failed", QUERY_TABLE)
                                        for k in received))

vm3.shutdown()
# Laufende Worker ausraeumen
for _ in range(5):
    QCoreApplication.processEvents()
    time.sleep(0.01)

# ---------------------------------------------------------------------------
# Aufraeumen
# ---------------------------------------------------------------------------
for _db in (TEST_DB_ANALYTICS, TEST_DB_APP):
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
