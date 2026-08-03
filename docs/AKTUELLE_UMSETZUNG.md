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

Die ausführlichen Kapitel 4.1–4.5 (P14-01 bis P14-05) inkl. Kopierblöcken,
Schritt-für-Schritt-Anleitungen und pro-Kapitel Validierung sind **archiviert** in:

* `docs/Old/x_Roadmap_Phase14.md` (verbindliche Referenz, NICHT Bestandteil der
  Hauptanweisung – siehe System-Regeln `docs/Old`)

Alle P14-Kapitel sind **umgesetzt und committet** (Commits `6878a23`–`1408e46`,
Tags `phase14_step1`–`phase14_step6`). Die aktive Hauptanweisung für weitere
Umsetzungen sind die Kapitel 5 (JSON-Schema), 6 (Regressionstest) und 7
(Betriebsrahmen) dieser Datei.

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


**Umsetzungs-Status (additiv):** `ServiceSetRepository.save_set()` stempelt die
Set-Level-Felder automatisch in jede Definition (idempotent):
* `schema_version` → `"1.0"` (Default, aus Definition/Bestand übernommen)
* `version` → Aufrufer-Version gewinnt; sonst **Patch-Bump** (`major.minor.patch`)
  bei jedem Überschreiben, `"1.0.0"` bei Neuanlage
* `created_at` → ISO-8601 UTC bei Neuanlage; bleibt bei Überschreiben stabil
* `ServiceSetDefinition` (TypedDict) enthält die Felder `version`,
  `schema_version`, `created_at` (analog `description`)

Das `depends_on`-Feld je Service wird vom TypedDict unterstützt und vom
Evaluator validiert; die Erzeugung erfolgt durch die aufrufenden Komponenten
(Indikator-Pipeline), nicht durch das Repository.

---

## 6. Universal-Regressionstest für Phase 14

**Umgesetzt:** `test/check_phase14_regression.py` (headless, KEINE UI, KEIN `exec_()`).

Ausführen:
    python test/check_phase14_regression.py

Der Test validiert alle P14-Kernmodule funktional (ASCII-Ausgabe, Test-DB in `test/phase14_regression_test.duckdb`, 41 Checks):

* **P14-01** – `ServiceSetDefinition` enthält `description` + `version` (Kap 5), `ServiceInstanceConfig.version`, `PluginMetadata` importierbar.
* **P14-02** – `PluginRegistry` (Singleton) entdeckt Core-Plugins (`grid_lines`, `proximity`, `grid_liquidity`); `reload()` läuft fehlerfrei.
* **P14-03** – `ServiceSetEvaluator` mit `_failure_counters` / `_quarantined` / `reset()`; `execute_set_resilient()` liefert Ergebnisse auf synthetischen Daten.
* **P14-04** – `SchemaMigrator` importierbar; SemVer-Matrix (Legacy → Migration, Patch → keine unnötige Migration).
* **P14-05** – Soft-Delete/Restore/purge funktional; Set-Level-Metadaten (`version`/`schema_version`/`created_at`, Kap 5) und Snapshot-Historie verifiziert.

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

1. **`test/check_performance_p14.py`** (umgesetzt, headless):

   Ausführen:
       python test/check_performance_p14.py

   Der Test misst (Test-DBs in `test/`, großzügige Dev-Schwellen – Produktiv-Alerts siehe 7.1):
   * **Plugin-Discovery-Speed** – `PluginRegistry().reload()` (< 2,0 s; Produktiv-Warnung laut 7.1: > 500 ms)
   * **Service-Evaluation-Speed** – `ServiceSetEvaluator.execute_set()` auf 1000 synthetischen Bars mit grid_lines + proximity (< 2,0 s)
   * **Feature-Store-Read-Speed** – DuckDB-SELECT auf 1000 Zeilen der feature_store-Test-Tabelle (< 0,2 s)

### 7.3 Deployment-Checks & Rollback-Plan

Vor der Veröffentlichung einer neuen Version MÜSSEN folgende Checks durchgeführt werden:

    1. Schema-Migration Dry-Run: Führe ServiceSetRepository().list_sets() in einer isolierten Test-DB mit der neuen Migrations-Logik aus, um sicherzustellen, dass keine MigrationError geworfen werden.

    2. Plugin-Isolation: Starte die App einmalig mit --check-plugins, um zu validieren, dass keine Custom-Plugins Core-Plugin-IDs überschreiben (Core Protection Rule).
       **Umgesetzt:** `python main.py --check-plugins` (headless, ohne GUI). Nutzt `PluginLoader.find_custom_conflicts()`; Exit-Code 0 = OK, 1 = Konflikt.

    3. Rollback-Plan: Bei einem kritischen Fehler NACH dem Deployment:
        Führe git reset --hard phase14_step5 (oder den letzten stabilen Tag) aus.
        Achtung: Da die Datenbank-Schemata (app_data.duckdb, analytics.duckdb) additiv sind (ADD COLUMN IF NOT EXISTS), ist ein Rollback des Codes ohne Datenbank-Rollback unproblematisch. Neue Spalten werden von älterem Code einfach ignoriert.