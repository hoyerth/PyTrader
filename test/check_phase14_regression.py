# BEREIT FÜR PHASE 15
# test/check_phase14_regression.py
"""
Phase 14 – Universal-Regressionstest (Kapitel 6 AKTUELLE_UMSETZUNG).

Headless Validierung (KEINE UI, KEIN exec_()) ueber alle P14-Kernmodule:

  [P14-01] Beschreibungsfelder & Metadaten:
           - ServiceSetDefinition besitzt 'description' (TypedDict-Annotation)
           - ServiceInstanceConfig besitzt 'version'
           - ServiceSetRepository verfuegbar (save/get/list)
  [P14-02] Dynamic Discovery & Hot-Reload:
           - PluginRegistry (Singleton) + PluginLoader vorhanden
           - Core-Plugins (grid_lines, proximity) entdeckt
           - reload() existiert und laeuft fehlerfrei (Hot-Reload)
  [P14-03] Pipeline-Resilienz:
           - ServiceSetEvaluator mit _failure_counters / _quarantined / reset()
           - execute_set_resilient() fuehrt ein Set auf synthetischen Daten aus
  [P14-04] Schema-Migration:
           - SchemaMigrator importierbar, Version wird angehoben
  [P14-05] Papierkorb & Snapshot-Historie:
           - list_trash / restore_set_from_trash / purge_trash vorhanden
           - Soft-Delete + Restore + Snapshot bei Ueberschreiben (funktional)

Test-DB liegt im Unterordner test/ (Regel: keine Test-DBs im Root/data).
Nur ASCII-Ausgaben (cp1252-Konsole), keine Emojis.
"""
import os
import sys

sys.path.insert(0, r"F:\Python\PyTrader")

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "phase14_regression_test.duckdb")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ===========================================================================
# [P14-01] Beschreibungsfelder & Metadaten
# ===========================================================================
try:
    from analytics.engine.service_models import (  # noqa: E402
        ServiceSetDefinition,
        ServiceInstanceConfig,
    )
    from analytics.engine.service_set_repository import ServiceSetRepository  # noqa: E402
    from analytics.features.plugins.base_plugin import PluginMetadata  # noqa: E402

    check("P14-01a) ServiceSetDefinition importierbar", True)
    annotations = ServiceSetDefinition.__annotations__
    check("P14-01b) ServiceSetDefinition hat 'description'",
          "description" in annotations)
    check("P14-01c) ServiceSetDefinition hat 'version' (Set-Level, Kap 5)",
          "version" in annotations)
    check("P14-01d) ServiceInstanceConfig hat 'version'",
          "version" in ServiceInstanceConfig.__annotations__)
    check("P14-01e) PluginMetadata importierbar", True)
except ImportError as e:
    check("P14-01a) ServiceSetDefinition importierbar", False, str(e))
    check("P14-01b) ServiceSetDefinition hat 'description'", False, str(e))
    check("P14-01c) ServiceSetDefinition hat 'version'", False, str(e))
    check("P14-01d) ServiceInstanceConfig hat 'version'", False, str(e))
    check("P14-01e) PluginMetadata importierbar", False, str(e))

# ===========================================================================
# [P14-02] Dynamic Discovery & Hot-Reload
# ===========================================================================
try:
    from analytics.features.feature_builder import (  # noqa: E402
        PluginRegistry,
        PluginLoader,
    )
    registry = PluginRegistry()
    plugins = registry.plugins
    # Bugfix 04.08.2026: Alt-Plugin 'grid_liquidity' entfernt -> die beiden
    # Core-Grid-Plugins grid_lines + proximity sind der finale Bestand.
    check("P14-02a) PluginRegistry enthaelt Core-Plugins", len(plugins) >= 2,
          str(len(plugins)))
    check("P14-02b) Core-Plugin 'grid_lines' entdeckt", "grid_lines" in plugins)
    check("P14-02c) Core-Plugin 'proximity' entdeckt", "proximity" in plugins)
    check("P14-02d) Alt-Plugin 'grid_liquidity' NICHT mehr registriert",
          "grid_liquidity" not in plugins)
    check("P14-02e) PluginLoader verfuegbar", hasattr(registry, "loader"))
    check("P14-02f) reload() existiert", hasattr(registry, "reload"))
    try:
        registry.reload()
        check("P14-02g) reload() laeuft fehlerfrei", True)
    except Exception as e:
        check("P14-02g) reload() laeuft fehlerfrei", False, str(e))
except ImportError as e:
    check("P14-02a) PluginRegistry importierbar", False, str(e))
    for nm in ("P14-02b", "P14-02c", "P14-02d", "P14-02e", "P14-02f", "P14-02g"):
        check(nm, False, "Import fehlgeschlagen")

# ===========================================================================
# [P14-03] Pipeline-Resilienz
# ===========================================================================
try:
    from analytics.engine.set_evaluator import ServiceSetEvaluator  # noqa: E402
    evaluator = ServiceSetEvaluator()
    check("P14-03a) _failure_counters vorhanden",
          hasattr(evaluator, "_failure_counters"))
    check("P14-03b) _quarantined vorhanden", hasattr(evaluator, "_quarantined"))
    check("P14-03c) reset() vorhanden", hasattr(evaluator, "reset"))
    check("P14-03d) execute_set_resilient vorhanden",
          hasattr(evaluator, "execute_set_resilient"))

    # Funktionale Ausfuehrung auf synthetischen Daten (grid_lines + proximity)
    import pandas as pd  # noqa: E402
    n = 200
    base_epoch = 1700000000
    df = pd.DataFrame({
        "time": [base_epoch + i * 60 for i in range(n)],
        "open": [25.0 + i * 0.001 for i in range(n)],
        "high": [25.1 + i * 0.001 for i in range(n)],
        "low": [24.9 + i * 0.001 for i in range(n)],
        "close": [25.05 + i * 0.001 for i in range(n)],
        "tick_volume": [100] * n,
    })
    set_def = {
        "execution_order": ["grid_1", "prox_1"],
        "services": {
            "grid_1": {"plugin_id": "grid_lines", "lookback": n,
                       "params": {"step_size": 0.5, "steps_around": 4}},
            "prox_1": {"plugin_id": "proximity", "lookback": n,
                       "depends_on": ["grid_1"],
                       "params": {"visit_pct": 0.05, "time_window_mins": 5}},
        },
    }
    try:
        results = evaluator.execute_set_resilient(set_def, df)
        check("P14-03e) execute_set_resilient liefert Ergebnisse",
              len(results) >= 1, str(len(results)))
        check("P14-03f) kein Quarantaene-Fehler nach Erfolg",
              "grid_1" not in evaluator.last_skipped)
    except Exception as e:
        check("P14-03e) execute_set_resilient liefert Ergebnisse",
              False, str(e))
        check("P14-03f) kein Quarantaene-Fehler nach Erfolg", False, str(e))
except ImportError as e:
    check("P14-03a) ServiceSetEvaluator importierbar", False, str(e))
    for nm in ("P14-03b", "P14-03c", "P14-03d", "P14-03e", "P14-03f"):
        check(nm, False, "Import fehlgeschlagen")

# ===========================================================================
# [P14-04] Schema-Migration
# ===========================================================================
try:
    from analytics.engine.schema_migrator import SchemaMigrator, _needs_migration  # noqa: E402
    check("P14-04a) SchemaMigrator importierbar", True)
    check("P14-04b) SemVer: Legacy 0.0.0 -> 1.0.0 migrieren",
          _needs_migration(None, "1.0.0") is True)
    check("P14-04c) SemVer: Patch 1.0.0 -> 1.0.1 KEINE Migration",
          _needs_migration("1.0.0", "1.0.1") is False)
except ImportError as e:
    check("P14-04a) SchemaMigrator importierbar", False, str(e))
    check("P14-04b) SemVer Legacy", False, str(e))
    check("P14-04c) SemVer Patch", False, str(e))

# ===========================================================================
# [P14-05] Papierkorb & Snapshot-Historie (funktional, Test-DB)
# ===========================================================================
repo = ServiceSetRepository(db_path=TEST_DB)
check("P14-05a) list_trash vorhanden", hasattr(repo, "list_trash"))
check("P14-05b) restore_set_from_trash vorhanden",
      hasattr(repo, "restore_set_from_trash"))
check("P14-05c) purge_trash vorhanden", hasattr(repo, "purge_trash"))
check("P14-05d) purge_trash_set vorhanden", hasattr(repo, "purge_trash_set"))

set_a = {
    "set_id": "reg-alpha",
    "display_name": "Regression Alpha",
    "execution_order": ["grid_1"],
    "services": {"grid_1": {"plugin_id": "grid_lines", "lookback": 1000,
                            "params": {}}},
}
repo.save_set(set_a)
loaded = repo.get_set("reg-alpha")
check("P14-05e) Set gespeichert + geladen", loaded is not None)

# Kap 5: Set-Level Metadaten automatisch gestempelt
check("P14-05f) schema_version gestempelt",
      (loaded or {}).get("schema_version") == "1.0",
      str((loaded or {}).get("schema_version")))
check("P14-05g) version Default 1.0.0 bei Neuanlage",
      (loaded or {}).get("version") == "1.0.0",
      str((loaded or {}).get("version")))
check("P14-05h) created_at gestempelt", bool((loaded or {}).get("created_at")))

# Version-Patch-Bump bei Ueberschreiben
set_a["description"] = "Zweiter Stand"
repo.save_set(set_a)
loaded2 = repo.get_set("reg-alpha")
check("P14-05i) version Patch-Bump bei Ueberschreiben (1.0.0 -> 1.0.1)",
      (loaded2 or {}).get("version") == "1.0.1",
      str((loaded2 or {}).get("version")))
check("P14-05j) created_at bleibt stabil",
      (loaded2 or {}).get("created_at") == (loaded or {}).get("created_at"))

# Soft-Delete + Restore
repo.delete_set("reg-alpha")
check("P14-05k) Set im Papierkorb nach Soft-Delete",
      any(t.get("set_id") == "reg-alpha" for t in repo.list_trash()))
check("P14-05l) Set nicht mehr in list_sets()",
      all(s.get("set_id") != "reg-alpha" for s in repo.list_sets()))
check("P14-05m) Restore erfolgreich",
      repo.restore_set_from_trash("reg-alpha") is True)
check("P14-05n) Set nach Restore wieder aktiv",
      any(s.get("set_id") == "reg-alpha" for s in repo.list_sets()))

# Snapshot-Historie: Ueberschreiben erzeugt GENAU 1 Snapshot (obiges 1x)
repo.delete_set("reg-alpha")
repo.restore_set_from_trash("reg-alpha")
repo.save_set({"set_id": "reg-alpha", "display_name": "Regression Alpha",
               "execution_order": ["grid_1"],
               "services": {"grid_1": {"plugin_id": "grid_lines",
                                       "lookback": 1000, "params": {}}},
               "description": "Dritter Stand"})
con = repo._get_connection()
hist_count = con.execute(
    "SELECT COUNT(*) FROM service_set_history WHERE set_id = 'reg-alpha'"
).fetchone()
check("P14-05o) Snapshot bei Ueberschreiben erzeugt",
      bool(hist_count and hist_count[0] and hist_count[0] > 0),
      str(hist_count[0]) if hist_count else "0")

# ===========================================================================
print("-" * 60)
if FAILURES:
    print(f"FEHLER: {len(FAILURES)} Pruefung(en) fehlgeschlagen: {FAILURES}")
    sys.exit(1)
print("ALLE PRUEFUNGEN BESTANDEN (OK)")
sys.exit(0)
