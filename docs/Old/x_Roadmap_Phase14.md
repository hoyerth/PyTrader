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

---

### C. Nachtrag: Additive Anpassungen nach Umsetzung (Ist-Zustand, Commits `6878a23` – `4fccb09`)

Kapitel 4.1 [P14-01] ist **vollständig umgesetzt**. Zusätzlich zur ursprünglichen Anleitung wurden folgende additive Anpassungen vorgenommen (dokumentierter Ist-Zustand):

#### C.1 Bearbeitbare Instanz-Beschreibungen (Commit `6878a23`)
- `service_win.py` + `chart/indicator_dialog.py`: `Beschreibung:`-`QLineEdit` oben in jeder Service-Spalte/-Seite (`_service_desc_controls` / `_set_desc_controls`).
- Live-Tooltip-Update beim Tippen (`_update_service_tooltip`).
- Übernahme in `collect_set_definition()` als `ServiceInstanceConfig.description` (gehört NICHT in `params`).
- Info-Dialoge (`ServiceDescriptionDialog`) zeigen den Live-Wert.

#### C.2 Service-Parameter nur als Modell-Params (Commit `07930f2`)
- Das Prop-Fenster zeigt je Service NUR die im Service-Modell gespeicherten Parameter (Parität zum `service_win`).
- Die frühere „Plugin-Live-Seite" (Seite 0 mit `self.params`) entfällt – sie zeigte Werte, die nicht im Modell stehen.
- `_service_items()`: Fallback auf das aktive Plugin als Service, wenn weder Set-Services noch deklarierte Services existieren.
- `_on_service_selected()`: `setCurrentIndex(max(0, index))` (keine separate Plugin-Seite mehr).
- Rein visuelle Keys (`show_*`/`color`) werden ausgeblendet.

#### C.3 USER-REQ: 6 Custom-Levels als Einzelparameter (Commit `52d384b`)
- `grid_lines_service.py`: `parameter_order`/`param_labels`/`parameter_schema` um `prox_level1..6` („Level 1"–„Level 6") erweitert.
- `custom_levels` bleibt im Schema (interne Pipeline/Alt-Sets), ist aber NICHT mehr in der Editor-Reihenfolge (kein Komma-Textfeld).
- `calculate()` liest via `custom_levels_from_params()`: bevorzugt `prox_level1..6`, sonst `custom_levels` (beide Speicherformen rendern auf dem Chart).
- `map_custom_levels_to_prox_levels()`: Vorbefüllung der 6 Level-Felder aus `custom_levels`-Aggregat bei Alt-Sets (`indicator_dialog` + `service_win`).

#### C.4 USER-REQ: Prop-Fenster kompakte Buttons + Auto-Set-Ausführung (Commit `4fccb09`)
- „Set ausführen"-Button (`btn_execute_set`): nur noch Icon `▶` (28×28), Tooltip „Set ausführen".
- Auto-Set-Ausführung: Bei Verlassen des Eingabefeldes (`editingFinished`) bzw. sofortiger Änderung (CheckBox/Combo) wird das Set automatisch ausgeführt (`_connect_service_param_commit` → `_on_service_param_commit` → `execute_service_set`).
- `_collect_logic_params()` meldet zusätzlich die Service-Seiten-Werte (`step_size`, `prox_level1..6`, `visit_pct`, …) als Live-Overlay an den Chart.
- Service-Beschreibungs-Button (`btn_info_service`): nur noch Icon `i` (28×28), Tooltip „Beschreibung des Services".

#### C.5 Verifikation (headless, `test/`)
- `test/check_p14_s1_description.py` (27/27 PASS), `test/check_p14_service_params.py`, `test/check_p14_prop_ui.py`, `test/check_p13_s6.py`, `test/check_grid_parity.py`.
- Hinweis: `test/check_p13_s5.py` ist seit C.2 veraltet (testet das alte Layout mit `grid_step` in `param_controls`).




---

### Kapitel 4.2 [P14-02]: Dynamische Plugin Discovery, Hot-Reload & Thread-Safety

#### A. Konzept & Datenmodell

Ersetzung manueller Modul-Importe durch ein automatisches Reflection-System für Core- und Custom-Plugins unter Wahrung harter Konfliktregeln und Thread-Sicherheit.

1. **Folder Scanner & Auto-Directory (`analytics/features/feature_builder.py`):**
* `PluginLoader.discover_plugins()` stellt sicher, dass der Ordner `data/custom_plugins/` existiert (`os.makedirs(..., exist_ok=True)`).
* Automatisches, rekursives Durchsuchen von `analytics/features/definitions/` (Core) und `data/custom_plugins/` (User/Custom) mittels `pkgutil.walk_packages()` und `importlib.import_module()`.

2. **Konfliktregel, Case-Insensitivität & Core-Schutz:**
* Core-Plugins aus `analytics/features/definitions/` werden **zuerst** geladen.
* Die Eindeutigkeit der `plugin_id` wird strikt case-insensitiv (`plugin_id.lower()`) geprüft.
* Versucht ein Custom-Plugin aus `data/custom_plugins/` eine bereits registrierte `plugin_id` zu belegen, wird das Custom-Plugin verworfen und ein Warn-Log geschrieben (**Core Protection Rule**).
* Abstrakte Klassen (`inspect.isabstract`) werden ignoriert.

3. **Singleton & Process-Ownership:**
* `PluginRegistry` ist als Thread-sicheres Singleton pro Prozess ausgeführt.

4. **Hot-Reload & Thread Safety (`PluginRegistry.reload()`):**
* Schreib- und Lesezugriffe auf `PluginRegistry` werden durch einen `threading.RLock()` geschützt.
* `PluginRegistry.reload()` führt vor dem Discovery-Scan ein gezieltes `importlib.reload()` auf den geladenen Custom-Plugin-Modulen aus.
* Laufende Berechnungen nutzen weiterhin die bisher instanziierten Objekte. Neue Instanziiertungen greifen auf die aktualisierten Klassen zu.

---

#### B. Schritt-für-Schritt AI-Anleitung (Kopierblock P14-02)

### AI-Auftrag: Implementierung P14-02 (Dynamische Plugin Discovery, Hot-Reload & Thread-Safety)

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
git add -A && git commit -m "backup: pre P14-02" && git tag -f phase14_step2

#### Schritt 1: Dynamic Loader & Reflection mit Thread-Lock & Case-Insensitivität (Vollständig)

1. Öffne `analytics/features/feature_builder.py`:
   * Stelle sicher, dass `PluginRegistry` als Singleton mit einheitlicher Prozess-Instanz und internem `threading.RLock()` aufgebaut ist.
   * Erweitere `PluginLoader.discover_plugins()`:
     * Erstelle den Zielordner `data/custom_plugins/` automatisch per `os.makedirs(..., exist_ok=True)`.
     * Scanne zuerst `analytics/features/definitions/` (Core) via `pkgutil.walk_packages()` und `importlib.import_module()`.
     * Scanne danach `data/custom_plugins/` (Custom).
     * **Case-Insensitive Eindeutigkeit & Core-Schutz:** Normalisiere Schlüssel via `plugin_id.lower()`. Wenn eine entdeckte ID bereits in `registry.plugins` existiert, überspringe das Plugin und logge `WARN: Custom plugin skipped: plugin_id '{plugin_id}' already registered`.
     * Ignoriere abstrakte Klassen (`inspect.isabstract()`).
     * Fange Import-Fehler einzelner fehlerhafter Plugin-Dateien isoliert ab (strukturierte Warnung im Log, kein App-Absturz).

2. **Lifecycle-Erweiterung (Neu):** Füge in `PluginRegistry` eine interne Liste `_loaded_custom_modules` hinzu. Bei `reload()`:
   * Iteriere NUR über `_loaded_custom_modules` und führe `importlib.reload(sys.modules[mod_name])` aus.
   * Aktualisiere die Registry über `self.discover_plugins()` und überschreibe `self.plugins`.

#### Schritt 2: Hot-Reload Refactoring

1. Öffne `analytics/features/feature_builder.py` (`PluginRegistry`):
* Refactore die Methode `reload(self)` unter Reentrant Lock (`with self._lock:`):
* Iteriere über alle geladenen Custom-Plugin-Module und führe `importlib.reload(sys.modules[mod_name])` aus.
* Aktualisiere die Registry über `self.discover_plugins()`.

2. Öffne `service_win.py`:
* Verbinde den "Plugins neu laden"-Button mit `PluginRegistry().reload()`.

#### Schritt 3: Headless Validierung

1. Erstelle und führe aus: `test/check_p14_s2_discovery.py`:
* Erzeuge temporär eine Mock-Plugin-Datei `data/custom_plugins/tmp_dummy_plugin.py` mit `plugin_id = "tmp_dummy"`.
* Rufe `PluginRegistry().reload()` auf und verifiziere, dass `"tmp_dummy"` in `PluginRegistry().plugins` enthalten ist.
* Erzeuge eine kollidierende Datei `data/custom_plugins/tmp_collision.py` mit `plugin_id = "GRID_LINES"` (Core-ID Fallback-Case).
* Rufe `PluginRegistry().reload()` auf und verifiziere, dass das Core-Plugin `"grid_lines"` nicht überschrieben wurde.
* Lösche die temporären Test-Dateien, rufe erneut `reload()` auf und verifiziere die saubere Bereinigung.

---

### Kapitel 4.3 [P14-03]: Erweiterte Pipeline-Fehlerbehandlung, Auto-Recovery & Live-Feature-Store-Entkopplung

#### A. Konzept & Datenmodell

Ablösung des strikten Fail-Fast-Prinzips durch ein elastisches, fehlerfreies Pipeline-Handling sowie die saubere architektonische Trennung zwischen **Live-Tick-Performance**, **Feature-Store-Caching** und **Bar-Close-Service-Evaluierungen**.

1. **Architektur & Live-Entkopplung (Garantie der Phase-13-Performance):**
* **Live-Ticks in der GUI (`update_live_candle`):** Führen **keine** Service-Pipeline und keine DB-Abfragen aus. Der Indikator berechnet für den allerletzten Tick lediglich die mathematische Differenz zu den bereits im Arbeitsspeicher gecachten Grid-Linien.
* **Bar-Close Polling (`LiveAnalyzer`):** Der `LiveAnalyzer` evaluiert geschlossene Kerzen im Hintergrund. Er nutzt hierfür einen **stark verkürzten Lookback (1 bis 2 Bars)** gegen das im `EvaluationContext.shared_state` gepufferte Raster, um Rechnerlast und DB-I/O minimal zu halten.
* **Indikator-Lesepfad (`feature_store`):** Beim Chart-Re-Render / Refresh liest der `GridLiquidityIndicator` fertige Daten primär aus dem JSON-Feld `feature_data` (inkl. `schema_version`) der Tabelle `feature_store` in DuckDB aus, anstatt die Pipeline synchron auf der GUI neu zu berechnen.

2. **Ganzheitliche Fehlerkapselung (`PluginExecutor`):**
* Sämtliche Exceptions in der Ausführungskette eines Plugins – inklusive `validate_params()`, interner Dependency-Aufrufe (`depends_on` auf `instance_id`) und `calculate()` – werden innerhalb von `PluginExecutor.execute()` isoliert abgefangen.
* Fehler werden in ein strukturiertes Fehlerobjekt umgewandelt (inkl. Exception, Traceback, Symbol, Timeframe, Bar) und geloggt.

3. **Resiliente Evaluator-Schleife (`ServiceSetEvaluator`):**
* **Skip-Logic:** Schlägt ein unkritischer Service fehl, wird er geloggt und übersprungen. Unabhängige Services laufen weiter.
* **Dependency Skip:** Services, die per `depends_on` von der fehlerhaften `instance_id` abhängen, werden kontrolliert mit `skip_reason="dependency_failed"` übersprungen.

4. **State-Fallback & Session-Quarantäne:**
* **State-Fallback:** Tritt beim Bar-Close-Intervall oder Chart-Refresh ein Fehler auf, greift der Evaluator exklusiv auf `EvaluationContext.shared_state.get(instance_id)` der vorherigen Kerze zurück.
* **RAM-Quarantäne-System:** Fällt eine Service-Instanz in 3 aufeinanderfolgenden Ausführungen aus, wird sie im RAM für die laufende Session quarantänisiert (`quarantined = True`) und dauerhaft übersprungen. Quarantäne-Zustände werden **nicht** in DuckDB persistiert.


---

#### B. Schritt-für-Schritt AI-Anleitung (Kopierblock P14-03)

### AI-Auftrag: Implementierung P14-03 (Pipeline-Fehlerbehandlung, Feature-Store-Lesepfad & Live-Resilience)

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
git add -A && git commit -m "backup: pre P14-03" && git tag -f phase14_step3

#### Schritt 1: Absicherung im PluginExecutor & Evaluator

1. Öffne `analytics/features/feature_builder.py` (`PluginExecutor`):
* Umschließe in `execute()` die gesamte Kette mit `try...except Exception as e`.
* Prüfe `depends_on`-Abhängigkeiten strikt gegen vorhandene `instance_id`-Keys.
* Erzeuge bei Fehlern ein strukturiertes Fehlerobjekt (mit `timestamp`, `plugin`, `instance_id`, `symbol`, `timeframe`, `bar`, `exception`, `traceback`) im Log und liefere ein Error-Result-Dict `{"success": False, "error": str(e), "instance_id": instance_id}` zurück.


2. Öffne `analytics/engine/set_evaluator.py` (`ServiceSetEvaluator`):
* Ergänze Konfigurations-Flag `allow_skip_errors: bool = True` in `execute_set()`.
* Bei Fehler einer `instance_id`:
* Markiere davon per `depends_on` abhängige Instanzen als übersprungen (`skip_reason="dependency_failed"`).
* Führe unabhängige Services regulär fort.





#### Schritt 2: State-Fallback, Session-Quarantäne & Recovery (Erweitert)

1. Erweitere `ServiceSetEvaluator`:
   * Führe ein internes RAM-Dict `_failure_counters: Dict[str, int]` und `_last_failure_time: Dict[str, float]` für Service-Instanzen.
   * Bei Fehler:
     * Greife im Bar-Close-Betrieb exklusiv auf `context.shared_state.get(instance_id)` zurück.
     * Inkrementiere `_failure_counters[instance_id] += 1` und setze `_last_failure_time[instance_id] = time.time()`.
     * **Recovery-Logik:** Prüfe vor jedem Inkrement, ob `time.time() - _last_failure_time.get(iid, 0) > 300`. Falls ja, setze den Counter zurück (Self-Healing nach 5 Minuten).
   * Bei 3 aufeinanderfolgenden Fehlern (innerhalb von 5 Minuten): Setze `quarantined = True` im RAM für die laufende Session und überspringe die Instanz mit Log-Warnung. (Nicht DB-persistieren).

2. **Strukturierte Fehlerobjekte (P14-03.1):**
   * Definiere in `base_plugin.py` ein `TypedDict` (`ServiceErrorLog`) mit den Pflichtfeldern: `timestamp`, `plugin_id`, `instance_id`, `symbol`, `timeframe`, `bar_time`, `exception`, `traceback`.
   * Nutze dieses Dict ausschließlich für das Logging in `PluginExecutor` und `ServiceSetEvaluator`, um maschinelle Auswertung zu ermöglichen.


#### Schritt 3: Verkürzter Live-Lookback & Indikator-Feature-Store-Lesepfad

1. Öffne `analytics/background_workers/live_analyzer.py`:
* Optimiere `_process_plugin_bars()`: Setze den `lookback_bars`-Parameter bei laufenden Bar-Close-Evaluierungen gezielt auf `limit = 2` (1 unvollständige, 1 frisch geschlossene Kerze) gegen das gepufferte `shared_state`-Raster.


2. Öffne `chart/indicators/grid_liquidity.py` (`GridLiquidityIndicator`):
* Ergänze in `calculate()` einen primären DB-Lesepfad: Lade gepufferte Daten aus `feature_store.feature_data` (DuckDB), sofern aktuelle Daten und passendes `schema_version` vorhanden sind.
* Nutze Heavy-Berechnung über `FeatureBuilder` nur als Fallback, wenn `feature_store` leer ist.
* Architektur-Constraint wahren: Stelle sicher, dass `update_live_candle()` weiterhin KEINE Pipeline ausführt, sondern performant auf gecachte Daten zugreift.



#### Schritt 4: Headless Validierung

1. Erstelle und führe aus: `test/check_p14_s3_resilience.py`:
* Erzeuge einen Test mit:
a) Service mit defekter Parameter-Validierung.
b) Service mit fehlerhafter `depends_on` Reference (`instance_id`).
c) Service, der 3x nacheinander abstürzt (Prüfe RAM-Quarantäne und State-Fallback).
d) Verifikation, dass `GridLiquidityIndicator` Daten korrekt aus `feature_store.feature_data` liest.
* Verifiziere, dass das Gesamtsystem stabil bleibt und unabhängige Services weiterlaufen.



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



---

### Kapitel 4.5 [P14-05]: Papierkorb- & Historien-System (Soft-Delete & Deterministische Snapshots)

#### A. Konzept & Datenmodell

Schutz vor versehentlichem Löschen oder Überschreiben von Service-Sets.

1. **Soft-Delete (`analytics/engine/service_set_repository.py`):**

* Verschieben gelöschter Service-Sets in die Tabelle `service_sets_trash` mit `deleted_at`-Zeitstempel.



2. **Deterministische Snapshot-Historie:**

* Ein automatischer Snapshot wird in `service_set_history` **ausschließlich dann** angelegt, wenn ein bereits in der DB existierendes Service-Set erfolgreich überschrieben wird. Bei reinen Neuanlagen oder Schreibfehlern entsteht kein Snapshot.

3. **UI-Integration (`service_win.py`):**

* "Papierkorb"-Dialog zur Einsicht und Wiederherstellung gelöschter Sets.



4. **Scope von Papierkorb & Historie:**
Der Papierkorb und die Snapshot-Historie werden primär für **Service-Sets** eingeführt. Über das generische `NamedItemAdapter`-Protokoll ist das System jedoch so strukturiert, dass es in einer späteren Phase schrittweise auf Indikator-Presets erweitert werden kann.



---

#### B. Schritt-für-Schritt AI-Anleitung (Kopierblock P14-05)

### AI-Auftrag: Implementierung P14-05 (Papierkorb & Snapshot-Historie)

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
git add -A && git commit -m "backup: pre P14-05" && git tag -f phase14_step5

#### Schritt 1: Datenbank-Tabellen & Repository-Anpassung

1. Öffne `analytics/engine/service_set_repository.py`:
* Ergänze in `_init_db()`:
```sql
CREATE TABLE IF NOT EXISTS service_sets_trash (
    set_id VARCHAR PRIMARY KEY,
    display_name VARCHAR,
    definition JSON,
    deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS service_set_history (
    history_id VARCHAR PRIMARY KEY,
    set_id VARCHAR,
    version VARCHAR,
    definition JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

```




2. Implementiere `delete_set(set_id, soft_delete=True)`:
* Bei `soft_delete=True`: Kopiere den Datensatz nach `service_sets_trash` und lösche ihn aus `service_sets`.


3. Implementiere `restore_set_from_trash(set_id)` und `list_trash()`.
4. Ergänze in `save_set()`: Prüfe, ob das Set bereits in `service_sets` existiert. **Nur bei bestehenden Sets**: Erstelle unmittelbar vor dem Überschreiben einen Snapshot-Eintrag in `service_set_history`.

#### Schritt 2: Headless Validierung

1. Erstelle und führe aus: `test/check_p14_s5_trash.py`:
* Erstelle ein Set und speichere es zum ersten Mal (Verifiziere: KEIN Eintrag in `service_set_history`).
* Überschreibe das existierende Set (Verifiziere: Genau 1 Snapshot in `service_set_history`).
* Führe `delete_set()` aus und verifiziere, dass es in `list_sets()` fehlt, aber in `list_trash()` vorhanden ist.
* Rufe `restore_set_from_trash()` auf und verifiziere die vollständige Wiederherstellung.



---

## 5. Phase 14 Standard JSON-Schema

Das erweiterte JSON-Schema definiert exakt die Struktur für Service-Sets inklusive Metadaten, Schema-Versionen und Instanz-Abhängigkeiten:

```json
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

```

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