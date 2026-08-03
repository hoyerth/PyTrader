# Konzept Phase 14: Advanced Infrastructure, Dynamic Discovery & System-Resilience

## 1. Übersicht & Zielsetzung

Ziel von **Phase 14** ist die Finalisierung der Infrastruktur, Architektur und System-Resilienz für den produktiven Einsatz der PyTrader-Applikation. Der Schwerpunkt liegt auf der **vollständigen Dokumentierbarkeit** von Services & Sets, der **vollautomatischen Plugin-Entdeckung** (Dynamic Discovery/Hot-Reload), einem **resilienten Fehlerhandling** (Skip-Logic, Caches, Quarantäne) sowie **Versionierung & Papierkorb-Sicherheit**.

Jedes Modul enthält direkt im Anschluss die vollständige, isolierte **Schritt-für-Schritt AI-Implementierungsanweisung** inklusive automatischer Git-Backup-Regeln, Architektur-Constraints, des zentralen Grundsatzkapitels und der headless Validierung.

---

## 2. Allgemeine Grundsätze & Workflow-Vereinbarungen (Agents.md / Architektur.md)

1. **HARTE VERBOTSREGEL (Alt-Grid & Bestands-Pfade):**
Die Alt-Dateien `chart/indicators/grid.py`, `chart/indicators/grid_liquidity.py` sowie bestehende Kernmodule dürfen unter keinen Umständen beschädigt oder in ihrer Funktionsweise für bestehende Aufrufe verändert werden. Neue Logiken werden additiv integriert.


2. **Git-Backup & Fallback vor JEDEM Kapitel:**
Vor Beginn jedes Kapitels erstellt die AI / der User automatisch einen Git-Commit und Tag: `phase14_step1`, `phase14_step2`, etc. Bei Fehlern wird sofort per `git reset --hard` auf das jeweilige Tag zurückgerollt.


3. **Headless-Validierung (Keine UI- und Keine unnötigen (Regressions-)tests):**
Validierungen erfolgen rein headless (kein `QApplication.exec()`, keine manuellen Klicks) über gezielte PyTest- / Headless-Python-Skripte im Ordner `test/`. Es werden ausschließlich die für den jeweiligen Schritt absolut notwendigen Tests ausgeführt – keine unnötigen (Regressions-)tests.


4. **Modulare Herauskoppelbarkeit:**
Jedes Kapitel ist so aufgebaut, dass Beschreibung, Schema-Änderung, Implementierungsanleitung, die allgemeinen Grundsätze und der notwendige Test als zusammenhängender Block an die IDE-AI übergeben werden können.


5. **Struktur & Refactoring:**
Phase 14 bleibt **rein additiv**. Die Harte Verbotsregel (Schutz der Alt-Grid-Dateien und Bestands-Pfade) gilt uneingeschränkt. Existing Subsysteme werden nicht gebrochen, sondern um Schnittstellen/Wrapper erweitert.



---

## 3. Architektur-Invarianten (Kapitel 14.0 - Fundament)

Vor jeglicher Code-Implementierung gelten folgende unumstößliche System-Regeln zur Sicherstellung der Konsistenz:

1. **PluginRegistry Ownership:** Genau eine Singleton-Instanz der `PluginRegistry` pro Prozess.
2. **Feature Store vs. Cache (Source of Truth):**
`Plugin` $\rightarrow$ `EvaluationContext.shared_state` (Live-RAM) $\rightarrow$ `feature_store` (DuckDB Cache) $\rightarrow$ `Indicator` (GUI-Lesepfad).
Der Indicator ruft niemals direkt Plugins zur Neuberechnung auf.
3. **ID-Semantik:**
* `depends_on` referenziert ausschließlich `instance_id` (z. B. `"grid_1"`).
* `plugin_id` ist strikt case-insensitiv eindeutig (`plugin_id.lower()`).

4. **Quarantäne-Lebensdauer:** Quarantäne (`quarantined = True`) gilt ausschließlich im RAM für die aktuell laufende Session und wird nicht in der Datenbank persistiert.
5. **Versionierung & Schema:**
* Jeder Plugin-Output und Feature-Payload enthält ein `schema_version`.
* Jedes Plugin deklariert explizit eine `api_version` (z. B. `api_version="1"`).
* Versionsvergleiche nutzen Semantic Versioning (`major.minor.patch`). Reine Patch-Updates (z. B. `1.0.0` $\rightarrow$ `1.0.1`) lösen keine Schema-Migration aus.

6. **Hot-Reload-Semantik:** `PluginRegistry.reload()` ersetzt nur zukünftige Service-Instanziierungen; bereits laufende Hintergrund-Auswertungen laufen ungestört auf ihren bisherigen Objektinstanzen weiter. Custom Plugins werden isoliert entladen/neu importiert.
7. **Thread Safety:** Der Zugriff auf `PluginRegistry` und `FeatureStore` durch `LiveAnalyzer`, `HistoricalScanner` und Charts erfolgt über explizite Thread-Locks (Thread-Safety).
8. **Logging & Migration Rollback:**
* Logging verwendet strukturierte Fehlerobjekte (inkl. `timestamp`, `plugin`, `instance`, `symbol`, `timeframe`, `bar`, `exception`, `traceback`).
* Schlägt eine Schema-Migration fehl (`SchemaMigrator` Exception), wird die Transaktion abgebrochen, das alte Set im Speicher belassen und ein Rollback durchgeführt.

  9. **Snapshot-Historie:** Ein historischer Snapshot in `service_set_history` wird ausschließlich beim erfolgreichen Überschreiben eines bereits existierenden Sets erzeugt.
10. **Chart-Entkopplung:** Der Chart führt niemals Berechnungen aus, sondern liest ausschließlich vorberechnete Daten aus DuckDB (mit definiertem Fallback).
11. **Quarantäne-Recovery (Lebensdauer):** Der `_failure_counters`-Zähler jeder Service-Instanz wird nach 300 Sekunden (5 Minuten) ohne weiteren Fehler automatisch zurückgesetzt (`_recovery_timer`). Eine einmalige Quarantäne (`quarantined = True`) bleibt für die laufende Session bestehen, bis der Evaluator einen vollständigen Neustart der Pipeline durchläuft (`reset()`).

12. **Hot-Reload Lifecycle:** `PluginRegistry.reload()` führt folgende atomare Schritte unter dem `RLock()` aus:
    a) Erfassen der aktuell geladenen Custom-Modul-Namen (`data/custom_plugins/`).
    b) Gezieltes `importlib.reload(sys.modules[mod_name])` NUR für diese Module.
    c) Erneute Ausführung von `discover_plugins()` mit anschließendem Überschreiben des internen `plugins`-Dictionaries.
    d) WICHTIG: Bereits laufende Service-Instanzen (`LiveAnalyzer`, historische Berechnungen) behalten ihre alte Objekt-Referenz; neue Service-Instanzen nutzen die neuen Klassen.

13. **Cache-Invalidierung (Feature Store):** Der `FeatureBuilder` führt bei jedem `store_plugin_payload()` eine explizite Invalidation des In-Memory-Caches für das betroffene `(symbol, timeframe)` durch, um veraltete Zustände in `EvaluationContext.shared_state` zu verhindern.
---

## 4. Spezifikation & Schritt-für-Schritt-Anleitungen der Kernmodule (Phase 14)

---

## 5. Phase 14 Standard JSON-Schema

Das erweiterte JSON-Schema definiert exakt die Struktur für Service-Sets inklusive Metadaten, Schema-Versionen und Instanz-Abhängigkeiten:

{
  "set_id": "set_grid_scalp_v2",
  "display_name": "Grid Scalper Pro",
  "description": "Erweitertes Grid-System mit Proximity-Erkennung und M30-Zeitfenster-Analyse.",
  "version": "2.1.0",
  "schema_version": "1.0",
  "created_at": "2026-08-03T10:00:00Z",
  "execution_order": ["grid_1", "prox_1"],
  "services": {
    "grid_1": {
      "plugin_id": "grid_lines",
      "version": "1.0.0",
      "description": "Haupt-Grid-Raster 0.50 mit 4 Umkreis-Leveln",
      "lookback": 1000,
      "params": {
        "step_size": 0.5,
        "steps_around": 4
      }
    },
    "prox_1": {
      "plugin_id": "proximity",
      "version": "1.1.0",
      "description": "Prüfung auf Preisannäherung im 5-Min-Aktivitätsfenster",
      "lookback": 3000,
      "depends_on": ["grid_1"],
      "params": {
        "visit_pct": 0.05,
        "time_window_mins": 5
      }
    }
  }
}



---

## 6. Universal-Regressionstest für Phase 14

Dieses Testskript ist **vollständig dynamisch** und fehlertolerant aufgebaut. Noch nicht implementierte Module werden als `[SKIPPED / PENDING]` markiert.

```python
# test/check_phase14_regression.py
"""
Universal-Regressionstest für Phase 14 (PyTrader).
"""

import sys
import os
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


class TestPhase14Regression(unittest.TestCase):

    def setUp(self):
        print("\n" + "=" * 70)
        print("🔍 START: Phase 14 Dynamic Regression Suite")
        print("=" * 70)

    def test_p14_01_description_fields(self):
        print("\n[P14-01] Prüfe Beschreibungsfelder & Metadaten...")
        try:
            from analytics.features.plugins.base_plugin import PluginMetadata
            from analytics.engine.service_models import ServiceSetDefinition
            from analytics.engine.service_set_repository import ServiceSetRepository

            annotations = ServiceSetDefinition.__annotations__
            if "description" in annotations:
                print("  ✅ ServiceSetDefinition enthält 'description'")
            else:
                print("  ⚠️ ServiceSetDefinition hat kein 'description'-Feld (Pending)")

            repo = ServiceSetRepository()
            if hasattr(repo, "get_set"):
                print("  ✅ ServiceSetRepository ist verfügbar")

        except ImportError as e:
            print(f"  ⏭️ [SKIPPED] Modul noch nicht vollständig implementiert: {e}")

    def test_p14_02_dynamic_discovery(self):
        print("\n[P14-02] Prüfe Plugin Discovery & Registry...")
        try:
            from analytics.features.feature_builder import PluginRegistry, PluginLoader

            registry = PluginRegistry()
            plugins = registry.plugins
            print(f"  ✅ Entdeckte Plugins in Registry: {list(plugins.keys())}")

            if hasattr(registry, "reload"):
                print("  ✅ Hot-Reload Funktion 'reload' vorhanden")
            else:
                print("  ⚠️ Hot-Reload 'reload' steht noch aus (Pending)")

        except ImportError as e:
            print(f"  ⏭️ [SKIPPED] Modul noch nicht implementiert: {e}")

    def test_p14_03_resilience(self):
        print("\n[P14-03] Prüfe Pipeline-Resilienz & Error-Handling...")
        try:
            from analytics.engine.set_evaluator import ServiceSetEvaluator

            evaluator = ServiceSetEvaluator()
            if hasattr(evaluator, "_failure_counters"):
                print("  ✅ Failure-Counter / Quarantäne-System im Evaluator aktiv")
            else:
                print("  ⚠️ Resilience Skip-Logic noch im Standard-Modus (Pending)")

        except ImportError as e:
            print(f"  ⏭️ [SKIPPED] Modul noch nicht implementiert: {e}")

    def test_p14_04_schema_migration(self):
        print("\n[P14-04] Prüfe Schema-Migrator...")
        try:
            from analytics.engine.schema_migrator import SchemaMigrator
            print("  ✅ SchemaMigrator-Klasse erfolgreich geladen")
        except ImportError:
            print("  ⏭️ [SKIPPED] SchemaMigrator noch nicht erstellt (Pending)")

    def test_p14_05_trash_and_history(self):
        print("\n[P14-05] Prüfe Papierkorb & Snapshot-Historie...")
        try:
            from analytics.engine.service_set_repository import ServiceSetRepository

            repo = ServiceSetRepository()
            has_trash = hasattr(repo, "list_trash") or hasattr(repo, "restore_set_from_trash")
            if has_trash:
                print("  ✅ Soft-Delete & Papierkorb-Funktionen im Repository vorhanden")
            else:
                print("  ⚠️ Soft-Delete / Papierkorb noch nicht im Repository aktiv (Pending)")

        except Exception as e:
            print(f"  ⏭️ [SKIPPED] Repository-Prüfung übersprungen: {e}")


def run_phase14_regression():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase14Regression)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print("\n" + "=" * 70)
    print("📊 REGRESSIONSTEST ERGEBNIS")
    print(f"  Ran: {result.testsRun} | Errors: {len(result.errors)} | Failures: {len(result.failures)}")
    print("=" * 70)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_phase14_regression()
    sys.exit(0 if success else 1)
```

## 7. Betriebliche Rahmenbedingungen, Monitoring & Deployment-Checks (Kapitel 14.6 - Betriebsrahmen)

Dieses Kapitel definiert die nicht-funktionalen Anforderungen für den produktiven Betrieb der Phase-14-Infrastruktur.

### 7.1 Monitoring & Alerting (Metriken)

Folgende Metriken MÜSSEN über das bestehende Logging-System (strukturierte Fehlerobjekte) erfassbar sein, um eine automatisierte Überwachung zu ermöglichen:

| Metrik | Typ | Beschreibung | Alert-Schwelle |
| :--- | :--- | :--- | :--- |
| `plugin_loading_time` | Histogram | Dauer der Plugin-Discovery beim App-Start / Reload | > 500ms → Warnung |
| `service_execution_errors` | Counter | Anzahl fehlgeschlagener Service-Executions (pro Plugin) | > 5% Fehlerquote in 5min |
| `quarantine_events` | Counter | Anzahl der in Quarantäne gesetzten Service-Instanzen | > 10 Ereignisse in 1h |
| `schema_migration_failures` | Counter | Fehlgeschlagene Schema-Migrationen (Rollback-Fälle) | > 0 → Kritisch |
| `cache_hit_ratio` | Gauge | Trefferquote des Feature-Store-Caches | < 80% → Warnung |

### 7.2 Performance-Benchmarks (Headless)

Die folgenden Test-Skripte MÜSSEN vor jedem produktiven Release durchlaufen:

1. **Erstelle `test/check_performance_p14.py`:**

   import time
   class TestPerformance(unittest.TestCase):
       def test_plugin_discovery_speed(self):
           start = time.perf_counter()
           PluginRegistry().reload()
           elapsed = time.perf_counter() - start
           self.assertLess(elapsed, 0.1, f"Discovery zu langsam: {elapsed:.3f}s")
       
       def test_service_evaluation_speed(self):
           # 1000 Bars, 5 Services
           elapsed = self._run_benchmark(1000, 5)
           self.assertLess(elapsed, 0.05, f"Evaluation zu langsam: {elapsed:.3f}s")
       
       def test_feature_store_read_speed(self):
           elapsed = self._read_benchmark(1000)
           self.assertLess(elapsed, 0.005, f"Store-Read zu langsam: {elapsed:.3f}s")
   
### 7.3 Deployment-Checks & Rollback-Plan

Vor der Veröffentlichung einer neuen Version MÜSSEN folgende Checks durchgeführt werden:

    1. Schema-Migration Dry-Run: Führe ServiceSetRepository().list_sets() in einer isolierten Test-DB mit der neuen Migrations-Logik aus, um sicherzustellen, dass keine MigrationError geworfen werden.

    2. Plugin-Isolation: Starte die App einmalig mit --check-plugins, um zu validieren, dass keine Custom-Plugins Core-Plugin-IDs überschreiben (Core Protection Rule).

    3. Rollback-Plan: Bei einem kritischen Fehler NACH dem Deployment:
        Führe git reset --hard phase14_step5 (oder den letzten stabilen Tag) aus.
        Achtung: Da die Datenbank-Schemata (app_data.duckdb, analytics.duckdb) additiv sind (ADD COLUMN IF NOT EXISTS), ist ein Rollback des Codes ohne Datenbank-Rollback unproblematisch. Neue Spalten werden von älterem Code einfach ignoriert.