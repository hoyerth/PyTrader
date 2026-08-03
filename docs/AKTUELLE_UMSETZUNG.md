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

### Kapitel 4.4 [P14-04]: Semantische Versionierung, Schema-Migration & Rollback-Schutz

#### A. Konzept & Datenmodell

Sicherstellung der dauerhaften Lauffähigkeit alter Service-Sets bei Weiterentwicklung von Plugins unter Einsatz von Semantic Versioning.

1. **Lückenlose Versions-Erfassung:**
* Jede `ServiceInstanceConfig` führt verpflichtend das Feld `version: str` (z. B. `"1.0.0"`).
* In `service_win.py` (`collect_set_definition()`) wird beim Erstellen/Speichern einer Instanz automatisch die aktuelle Version des erzeugenden Plugins eingestempelt (`version = plugin.version`).


2. **Semantic Versioning Matching:**
* Abgleich der in `ServiceInstanceConfig` gespeicherten `version` mit `PluginFeature.version` via Semantic Versioning (`major.minor.patch`).
* Fehlt das `version`-Feld (`None`), wird es als Legacy-Stand `"0.0.0"` interpretiert.
* Reine Patch-Abweichungen (z. B. `1.0.0` vs. `1.0.1`) lösen keine Schema-Migration aus.
* Major-/Minor-Abweichungen triggern den `SchemaMigrator`.


3. **Auto-Migration Engine & Rollback (`analytics/engine/schema_migrator.py`):**
* Der `SchemaMigrator` führt folgende Schritte aus:
* Füllt fehlende Standardwerte (`default`) ergänzter Parameter auf.
* Entfernt veraltete, nicht mehr im Parameter-Schema enthaltene Keys.
* Ändert die Instanz-Version auf die aktuelle `plugin.version`.


* **Rollback-Schutz:** Wirft der `SchemaMigrator` während der Aufbereitung eine Exception, wird die Migration abgebrochen, das originale Set unverändert geladen und eine Fehlermeldung geloggt.
* `ServiceSetRepository.get_set()` wendet den Migrator transparent im Speicher an.



---

#### B. Schritt-für-Schritt AI-Anleitung (Kopierblock P14-04)

### AI-Auftrag: Implementierung P14-04 (Schema-Migration, Semantic Versioning & Rollback)

#### 2. Allgemeine Grundsätze & Workflow-Vereinbarungen (Agents.md / Architektur.md)

1. **HARTE VERBOTSREGEL (Alt-Grid & Bestands-Pfade):**
Die Alt-Dateien `chart/indicators/grid.py`, `chart/indicators/grid_liquidity.py` sowie bestehende Kernmodule dürfen unter keinen Umständen beschädigt oder in ihrer Funktionsweise für bestehende Aufrufe verändert werden. Neue Logiken werden additiv integriert.


2. **Git-Backup & Fallback vor JEDEM Kapitel:**
Vor Beginn jedes Kapitels erstellt die AI / der User automatisch einen Git-Commit und Tag: `phase14_step1`, `phase14_step2`, etc. Bei Fehlern wird sofort per `git reset --hard` auf das jeweilige Tag zurückgerollt.


3. **Headless-Validierung (Keine UI- und Keine unnötigen (Regressions-)tests):**
Validierungen erfolgen rein headless (kein `QApplication.exec()`, keine manuellen Klicks) over gezielte PyTest- / Headless-Python-Skripte im Ordner `test/`. Es werden ausschließlich die für den jeweiligen Schritt absolut notwendigen Tests ausgeführt – keine unnötigen (Regressions-)tests.


4. **Modulare Herauskoppelbarkeit:**
Jedes Kapitel ist so aufgebaut, dass Beschreibung, Schema-Änderung, Implementierungsanleitung, die allgemeinen Grundsätze und der notwendige Test als zusammenhängender Block an die IDE-AI übergeben werden können.



#### Schritt 0: Fallback & Backup

1. Führe vor Code-Änderungen folgendes Git-Backup aus:
git add -A && git commit -m "backup: pre P14-04" && git tag -f phase14_step4

#### Schritt 1: Datenmodell-Nachrüstung & UI-Serialisierung

1. Öffne `analytics/engine/service_models.py`:
* Stelle sicher, dass `ServiceInstanceConfig` das Feld `version: Optional[str]` enthält.


2. Öffne `service_win.py` (`collect_set_definition()`):
* Stelle sicher, dass beim Zusammenbauen der `services`-Konfiguration für jede `instance_id` das `version`-Feld mit der aktuellen `plugin.version` aus der `PluginRegistry` belegt wird:
`cfg["version"] = plugin.version`



#### Schritt 2: Migrations-Engine mit SemVer, Rollback & Bestands-Migration

1. Erstelle `analytics/engine/schema_migrator.py`:
   * Implementiere SemVer-Vergleichsfunktion `_needs_migration(v_old: str, v_new: str) -> bool` (True bei Major/Minor-Differenz; False bei bloßer Patch-Differenz).
   * Implementiere `SchemaMigrator.migrate_instance_config(config: Dict, plugin: PluginFeature) -> Dict`:
     * Umschließe die Bearbeitung mit `try...except Exception`:
     * Ermittle Instanz-Version: `current_ver = config.get("version") or "0.0.0"`.
     * Wenn `_needs_migration(current_ver, plugin.version)` True ist:
       * Fülle fehlende Schema-Keys mit `default`-Werten auf.
       * Entferne nicht mehr im Schema existierende Parameter-Keys.
       * Setze `config["version"] = plugin.version`.
     * Bei Fehler: Logge Fehler und wirf `MigrationError` zur Auslösung eines Rollbacks.

2. Öffne `analytics/engine/service_set_repository.py`:
   * **Neu (Bestands-Migration):** Füge in `_init_db()` eine private Methode `_migrate_existing_sets()` ein, die alle Sets lädt, prüft, ob `description` fehlt (und es mit `""` füllt) und diese dann speichert. Rufe diese Methode NACH dem `ALTER TABLE` auf.
   * Koppel den `SchemaMigrator` in `get_set()` ein:
     * Lade das Original-Set aus der DB.
     * Erstelle eine tiefe Kopie (`original = dict(definition)`).
     * Iteriere über alle Instanzen. Tritt ein `MigrationError` auf, breche die Migration ab und gib das UNMIGRIERTE Original-Set (`original`) zurück (Rollback auf Datenbank-Ebene).


#### Schritt 3: Headless Validierung

1. Erstelle und führe aus: `test/check_p14_s4_migration.py`:
* Erzeuge eine alte `ServiceInstanceConfig` ohne `version`-Feld und mit veralteten Parameter-Keys.
* Übergebe sie an den `SchemaMigrator` und verifiziere:
a) Version wurde bei Major/Minor-Änderung auf die aktuelle `plugin.version` angehoben.
b) Bei einer bloßen Patch-Änderung (`1.0.0` -> `1.0.1`) erfolgte keine unnötige Migration.
c) Fehlende Parameter wurden ergänzt, veraltete Keys entfernt.
d) Bei Auslösen eines Fehlers griff das Rollback sauber.



