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

### Kapitel 4.1 [P14-01]: Beschreibungsfelder für Services, Plugins und Service-Sets

#### A. Konzept & Datenmodell

Um die Komplexität verknüpfter Indikatoren und Handelsbedingungen transparent zu machen, erhält jedes Plugin, jede Service-Instanz und jedes Service-Set erweiterte Dokumentations- und Beschreibungsfelder.

1. **`PluginFeature` / `PluginMetadata` (`analytics/features/plugins/base_plugin.py`):**
* Metadaten-Erweiterung um `description_long: str` (Markdown-Hilfe), `condition_rules: List[str]` (strukturierte Liste der Regeln) und `api_version: str = "1"`.

2. **`ServiceInstanceConfig` (`analytics/engine/service_models.py`):**
* Optionales Feld `"description": "Individuelle Anmerkung für diese Instanz"` im JSON.

3. **`ServiceSetDefinition` & Datenbank (`analytics/engine/service_set_repository.py`):**

* Neues Feld `"description": "Ausführliche Strategie- oder Set-Beschreibung"` im JSON.
* Additive Tabellen-Erweiterung in `app_data.duckdb`:



```sql
ALTER TABLE service_sets ADD COLUMN IF NOT EXISTS description VARCHAR;

```

4. **UI/UX Integration (`service_win.py` & `indicator_dialog.py`):**
* Mehrzeiliges `QLineEdit` / `QTextEdit` für die Set-Beschreibung.
* Tooltip-Anzeige beim Behovern von Service-Instanzen in der Liste.
* Klickbarer Info-Button `[ℹ]` neben Instanzen öffnet einen `ServiceDescriptionDialog` mit vollen Details.

---

#### B. Schritt-für-Schritt AI-Anleitung (Kopierblock P14-01)

### AI-Auftrag: Implementierung P14-01 (Beschreibungsfelder & Info-Buttons)

#### 2. Allgemeine Grundsätze & Workflow-Vereinbarungen (Agents.md / Architektur.md)

1. **HARTE VERBOTSREGEL (Alt-Grid & Bestands-Pfade):**
Die Alt-Dateien `chart/indicators/grid.py`, `chart/indicators/grid_liquidity.py` sowie bestehende Kernmodule dürfen unter keinen Umständen beschädigt oder in ihrer Funktionsweise für bestehende Aufrufe verändert werden. Neue Logiken werden additiv integriert.

2. **Git-Backup & Fallback vor JEDEM Kapitel:**
Vor Beginn jedes Kapitels erstellt die AI / der User automatisch einen Git-Commit und Tag: `phase14_step1`, `phase14_step2`, etc. Bei Fehlern wird sofort per `git reset --hard` auf das jeweilige Tag zurückgerollt.

3. **Headless-Validierung (Keine UI- und Keine unnötigen (Regressions-)tests):**
Validierungen erfolgen rein headless (kein `QApplication.exec()`, keine manuellen Klicks) über gezielte PyTest- / Headless-Python-Skripte im Ordner `test/`. Es werden ausschließlich die für den jeweiligen Schritt absolut notwendigen Tests ausgeführt – keine unnötigen (Regressions-)tests.

4. **Modulare Herauskoppelbarkeit:**
Jedes Kapitel ist so aufgebaut, dass Beschreibung, Schema-Änderung, Implementierungsanleitung, die allgemeinen Grundsätze und der notwendige Test als zusammenhängender Block an die IDE-AI übergeben werden können.


#### Schritt 0: Fallback & Backup

1. Führe vor Code-Änderungen folgendes Git-Backup aus:
git add -A && git commit -m "backup: pre P14-01" && git tag -f phase14_step1

#### Schritt 1: Metadaten & Models erweitern

1. Öffne `analytics/features/plugins/base_plugin.py`:
* Erweitere `PluginMetadata` (TypedDict) um `description_long: str`, `condition_rules: List[str]` und `api_version: str`. Setze in `PluginFeature.metadata` sinnvolle Defaults (`""`, `[]`, `"1"`).


2. Öffne `analytics/engine/service_models.py`:
* Erweitere `ServiceInstanceConfig` um `description: Optional[str]` und `version: Optional[str] = "1.0.0"`.
* Erweitere `ServiceSetDefinition` um `description: Optional[str]`.


3. Öffne `analytics/engine/service_set_repository.py`:
* Ergänze in `_init_db()`:
con.execute("ALTER TABLE service_sets ADD COLUMN IF NOT EXISTS description VARCHAR;")
* Passe `save_set()`, `get_set()` und `list_sets()` so an, dass das `description`-Feld mitgespeichert und gelesen wird.

#### Schritt 2: UI-Komponenten & Tooltips (Erweitert)

1. Erstelle `analytics/engine/description_dialog.py`:
   * Implementiere `ServiceDescriptionDialog(QDialog)` (headless-fähig instanziierbar).
   * Anzeige von Plugin-Name, Version, API-Version, Autor, Kurz-Beschreibung, `description_long` und `condition_rules` in einem sauberen Read-Only `QTextBrowser` / `QVBoxLayout`.

2. Öffne `service_win.py` und `chart/indicator_dialog.py`:
   * Füge unter dem Feld für den Set-Namen ein `QLineEdit` / `QTextEdit` für `edit_set_description` ein.
   * **Neu:** Erweitere die Methode `_build_tooltip(self, instance_id, config)`, um Rich-Text-Tooltips (HTML) zu rendern. Beispiel:
     ```python
     def _build_tooltip(self, instance_id: str, config: dict) -> str:
         lines = [f"<b>{instance_id}</b>", f"Plugin: {config.get('plugin_id', '?')}"]
         if config.get("description"): lines.append(f"<i>{config['description']}</i>")
         return "<br>".join(lines)
   * Füge einen Info-Button btn_info_service hinzu, der bei Klick den ServiceDescriptionDialog für die aktuell markierte Instanz öffnet. Verbinde diesen mit itemClicked-Signal, um die aktuelle Selektion zu ermitteln.


#### Schritt 3: Headless Validierung

1. Erstelle und führe aus: `test/check_p14_s1_description.py`:
* Erstelle ein Test-Set mit `description`, speichere es im `ServiceSetRepository` und lade es zurück.
* Instanziiere den `ServiceDescriptionDialog` headless ohne `exec_()` und verifiziere die saubere Datenbefüllung.

