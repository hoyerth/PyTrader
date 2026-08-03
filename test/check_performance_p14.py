# test/check_performance_p14.py
"""
Phase 14 – Performance-Benchmarks (Kapitel 7.2 AKTUELLE_UMSETZUNG).

Headless Laufzeit-Messungen (KEINE UI, KEIN exec_()):

  1. Plugin-Discovery-Speed : PluginRegistry().reload() (Hot-Reload, Singleton)
  2. Service-Evaluation-Speed: ServiceSetEvaluator.execute_set() auf 1000
     synthetischen Bars mit grid_lines + proximity (kein DB-Schreibzugriff –
     die Services bauen nur Payload-Dicts).
  3. Feature-Store-Read-Speed: DuckDB-SELECT auf einer Test-DB mit
     feature_store-Tabelle (Test-DB in test/).

Schwellwerte sind GROZZUEGIG (Entwicklungs-Rechner, Debug-Build). Sie dienen
der Erkennung krasser Regressions (nicht als Release-SLA). Reale SLA-
Schwellen laut Kapitel 7.1: plugin_loading_time > 500ms Warnung.

Test-DB liegt im Unterordner test/ (Regel: keine Test-DBs im Root/data).
Nur ASCII-Ausgaben (cp1252-Konsole), keine Emojis.
"""
import os
import sys
import time

sys.path.insert(0, r"F:\Python\PyTrader")

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "phase14_perf_test.duckdb")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _fmt(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms"


# ===========================================================================
# 1) Plugin-Discovery-Speed (Hot-Reload)
# ===========================================================================
try:
    from analytics.features.feature_builder import PluginRegistry  # noqa: E402
    registry = PluginRegistry()
    n_plugins = len(registry.plugins)

    start = time.perf_counter()
    registry.reload()
    elapsed = time.perf_counter() - start
    print(f"  . Plugin-Discovery: {n_plugins} Plugins in {_fmt(elapsed)}")
    # Kapitel 7.1: Alert-Schwelle > 500ms (Warnung). Dev-Schwellwert 2.0 s.
    check("Perf-1) Plugin-Discovery < 2.0 s", elapsed < 2.0, _fmt(elapsed))
except ImportError as e:
    check("Perf-1) Plugin-Discovery < 2.0 s", False, str(e))

# ===========================================================================
# 2) Service-Evaluation-Speed (1000 Bars, 2 Services)
# ===========================================================================
try:
    import pandas as pd  # noqa: E402
    from analytics.engine.set_evaluator import ServiceSetEvaluator  # noqa: E402

    n_bars = 1000
    base_epoch = 1700000000
    df = pd.DataFrame({
        "time": [base_epoch + i * 60 for i in range(n_bars)],
        "open": [25.0 + i * 0.001 for i in range(n_bars)],
        "high": [25.1 + i * 0.001 for i in range(n_bars)],
        "low": [24.9 + i * 0.001 for i in range(n_bars)],
        "close": [25.05 + i * 0.001 for i in range(n_bars)],
        "tick_volume": [100] * n_bars,
    })
    set_def = {
        "execution_order": ["grid_1", "prox_1"],
        "services": {
            "grid_1": {"plugin_id": "grid_lines", "lookback": n_bars,
                       "params": {"step_size": 0.5, "steps_around": 4}},
            "prox_1": {"plugin_id": "proximity", "lookback": n_bars,
                       "depends_on": ["grid_1"],
                       "params": {"visit_pct": 0.05, "time_window_mins": 5}},
        },
    }
    evaluator = ServiceSetEvaluator()

    start = time.perf_counter()
    results = evaluator.execute_set(set_def, df)
    elapsed = time.perf_counter() - start
    print(f"  . Service-Evaluation: {len(results)} Services auf {n_bars} Bars "
          f"in {_fmt(elapsed)}")
    check("Perf-2) Evaluation < 2.0 s", elapsed < 2.0, _fmt(elapsed))
    check("Perf-2b) Ergebnisse vorhanden", len(results) >= 1, str(len(results)))
except ImportError as e:
    check("Perf-2) Evaluation < 2.0 s", False, str(e))
    check("Perf-2b) Ergebnisse vorhanden", False, str(e))

# ===========================================================================
# 3) Feature-Store-Read-Speed (DuckDB-SELECT auf Test-DB)
# ===========================================================================
try:
    from db_service import DbPool  # noqa: E402

    con = DbPool.get(TEST_DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS feature_store (
            symbol VARCHAR,
            timeframe VARCHAR,
            bar_time TIMESTAMPTZ,
            feature_id VARCHAR,
            plugin_version VARCHAR,
            feature_data JSON,
            PRIMARY KEY (symbol, timeframe, bar_time)
        )
    """)
    # 1000 Test-Records (analog zur realen Store-Groesse pro (Symbol, TF))
    con.execute("""
        INSERT INTO feature_store (symbol, timeframe, bar_time, feature_id,
                                   plugin_version, feature_data)
        SELECT 'SILVER', 'M1', TIMESTAMPTZ 'epoch' + INTERVAL (i) MINUTE,
               'proximity', '1.0.0',
               JSON('{"levels_hit": [1.0], "is_hit": true}')
        FROM range(1000) AS t(i)
    """)

    start = time.perf_counter()
    rows = con.execute(
        "SELECT bar_time, feature_data FROM feature_store "
        "WHERE LOWER(symbol) = LOWER('SILVER') AND LOWER(timeframe) = LOWER('M1') "
        "ORDER BY bar_time"
    ).fetchall()
    elapsed = time.perf_counter() - start
    print(f"  . Feature-Store-Read: {len(rows)} Zeilen in {_fmt(elapsed)}")
    check("Perf-3) Store-Read < 0.2 s", elapsed < 0.2, _fmt(elapsed))
    check("Perf-3b) Zeilen gelesen", len(rows) == 1000, str(len(rows)))
except ImportError as e:
    check("Perf-3) Store-Read < 0.2 s", False, str(e))
    check("Perf-3b) Zeilen gelesen", False, str(e))

# ===========================================================================
print("-" * 60)
if FAILURES:
    print(f"FEHLER: {len(FAILURES)} Pruefung(en) fehlgeschlagen: {FAILURES}")
    sys.exit(1)
print("ALLE PRUEFUNGEN BESTANDEN (OK)")
sys.exit(0)
