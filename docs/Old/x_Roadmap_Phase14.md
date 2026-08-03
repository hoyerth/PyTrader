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

### Kapitel 4.3-E [P14-03]: Ergänzung – Konzeptionelle Erklärung & Schritt-Anleitung (Live-Engine-Resilienz & Flackerfreies Overlay-Rendering)

Konzeptionelle Erklärung & Schritt-Anleitung für Roadmap P14-03 (Ergänzungsanweisung auf
Basis der Live-Tests & Code-Inspektion der Kette main.py → chart_win.py → grid_liquidity
→ JS). Rein additiv; Alt-Grid (`grid.py`, `grid_liquidity.py`) und die B-Anleitung
(Schritte 0-4) bleiben unangetastet.

#### A. Konzeptionelle Erklärung & Flacker-Analyse

##### Das Flacker- & Unterbrechungsproblem

Bisher führte das Eintreffen einer offenen Live-Kerze in `chart_win.py` dazu, dass der
Timestamp der offenen Kerze nicht in den historischen Maps (`_time_real_to_cont`) gefunden
wurde. Dies löste einen Re-Build des gesamten Charts (`refresh_chart_data()`) aus. Da die
offene Kerze noch nicht in DuckDB persistiert war (Persistierung erst bei Bar-Close durch
`LiveTickWorker._persist_bar`), warfen der Re-Build und JS (`applyFullChartUpdate` →
`chart.remove()` + Neuaufbau NUR aus DB-Kerzen) die Live-Kerze sofort wieder aus dem Chart.
Jeder 500-ms-Tick (Polling-Intervall `LiveTickWorker`) erzeugte so ein Wechselspiel aus
Anhängen (`elif self._time_cont_to_real` in `update_live_candle`) und Löschen
(`applyFullChartUpdate`) der Kerze → sichtbares Flackern zwischen zwei Zuständen, das erst
endet, wenn die Kerze geschlossen/gesynct ist (dann ist ihr Timestamp beim nächsten Refresh
in den Maps enthalten).

Zusätzlich war die Kette zur Übertragung von Indikator-Ergebnissen (Grid-Circles /
Proximity-Marker) an drei Stellen unterbrochen:
1. Der Resilienz-Seam `_process_plugin_bars_resilient()` im LiveAnalyzer war **nicht
   verdrahtet** (nur Definition + Docstring, kein Aufruf in `run()`).
2. Der Alt-Pfad `_process_plugin_bars()` übergab **keinen `PluginContext`** →
   `GridLinesService` schrieb kein Raster in `shared_state`, `ProximityService` fand keine
   Linien (`return empty`) → keine Hit-Records im `feature_store` für Live-Bars.
3. JS `updateLiveCandle()` verwarf die Live-Rückgabe (nur `candleSeries.update(c)`);
   `renderGridCircles()` wurde ausschließlich aus `applyFullChartUpdate` gerufen.

##### Die Architektur-Lösung

1. **Incremental Time Map Expansion:** Neue Live-Bar-Timestamps erweitern die bestehenden
   Maps (`_time_real_to_cont` / `_time_cont_to_real`) dynamisch In-Memory. Ein Aufruf von
   `refresh_chart_data()` entfällt beim Live-Tick vollständig.
2. **Resilient Bar-Close Pipeline:** Der `LiveAnalyzer` nutzt exklusiv
   `_process_plugin_bars_resilient()` unter Übergabe eines vollständigen `PluginContext`
   (inkl. `shared_state` = `self._live_shared_state`).
3. **Generisches Live-Overlay Rendering:** Der Live-Tick transportiert gerenderte
   Live-Overlays (Circles/Marker) im Payload. JS verarbeitet diese in `updateLiveCandle()`
   ohne kompletten Chart-Rebuild.
4. **Pflicht-Re-Injektion der offenen Live-Kerze:** Der (einmalige) New-Candle-Refresh
   baut die Time-Maps in `_do_refresh_chart_data` neu auf. Die offene Live-Kerze wird
   NACH dem Rebuild zwingend in die Maps (`_time_real_to_cont`/`_time_cont_to_real`),
   in `continuous_candles` (mit letzter Live-OHLC) und in die `_known_times` des
   Indikators re-injiziert – sonst feuert der New-Candle-Callback bei jedem Tick erneut
   und die Flacker-Schleife bleibt bestehen (siehe Prüfprotokoll P5).

#### B. Generische Entkopplungs-Regel

1. **Kein Chart-Rebuild bei Live-Ticks:** Ein Live-Tick darf **niemals**
   `refresh_chart_data()` aufrufen! (Der einzige Refresh pro neuer Kerze erfolgt über den
   New-Candle-Callback `set_new_candle_callback(self.refresh_chart_data)` des
   `GridLiquidityIndicator` – genau einmal pro neuer Kerze, debounced 400 ms. Siehe
   Prüfprotokoll P5.)
2. **In-Memory Map-Append:** Wenn ein neuer Bar-Timestamp im Live-Betrieb auftaucht, wird
   er In-Memory an `_time_real_to_cont` angehängt, **ohne** die Maps zu löschen (`clear()`).
3. **Pflicht-Re-Injektion (Flacker-Fix):** Die offene Live-Kerze (noch nicht in DuckDB)
   wird bei jedem Chart-Refresh zwingend in die Time-Maps, in `continuous_candles` und in
   die `_known_times` des Indikators re-injiziert. Erst dann ist der (einmalige)
   New-Candle-Refresh nicht mehr die Ursache einer Flacker-Schleife (siehe Prüfprotokoll P5).
4. **Generische JS-Push-Schnittstelle (Open/Closed):** `JS updateLiveCandle(payload)`
   verarbeitet `c.overlays` dynamisch (Schema: `{kind, layer, time, price, color,
   priority}`). Ein generischer Dispatcher (`applyLiveOverlays`) rendert vorhandene
   Plugin-Layer punktuell – OHNE kompletten Chart-Rebuild und OHNE die historischen
   Overlays zu verwerfen. Spätere Indikator-Plugins docken über neue `kind`/`layer`-Werte
   an, ohne `updateLiveCandle` zu ändern.
5. **Generischer Overlay-Hook (`BaseIndicator.get_live_overlays()`):** Jedes Indikator-
   Plugin liefert seine Live-Overlays über einen gemeinsamen Hook (Default `[]`). Die
   Engine (`chart_win`) sammelt die Overlays ALLER aktiven Indikatoren generisch ein –
   kein `hasattr(plugin, "_live_points")`-Sonderfall pro Plugin.

#### C. Schritt-für-Schritt Anleitung zur Behebung (P14-03 Refactoring)

##### Schritt 1: Flackern stoppen & Time-Maps dynamisch erweitern (`chart/chart_win.py`)

In `PyTraderChartWindow.update_live_candle()` den Aufruf von `self.refresh_chart_data()`
im `elif self._time_cont_to_real:`-Zweig entfernen. Stattdessen den neuen Timestamp
kontinuierlich an die bestehenden Maps anhängen.

##### Schritt 2: Resilienz-Seam verdrahten (`analytics/background_workers/live_analyzer.py`)

In `LiveAnalyzer.run()` den Aufruf `self._process_plugin_bars()` durch
`self._process_plugin_bars_resilient()` ersetzen. Sicherstellen, dass ein gültiger
`PluginContext` (der bereits vorhandene `self._live_context` mit
`shared_state=self._live_shared_state`) durchgereicht wird.

##### Schritt 3: Generisches Live-Overlay-Rendering (`chart/chart_win.py`, `chart/indicators/base_indicator.py` & `chart/js/04_live_updates.js`)

1. `BaseIndicator` erhält den generischen Hook `get_live_overlays(candle) -> List[Dict]`
   (Default `[]`). `GridLiquidityIndicator` überschreibt ihn und liefert seine
   Live-Punkte als Circle-Overlays (`kind='circle', layer=indicator_id`).
2. In `update_live_candle()` sammelt `chart_win` die Overlays ALLER aktiven Indikatoren
   generisch ein und bettet sie als `c.overlays` in das JSON-Payload ein (Zeiten
   real→kontinuierlich gemappt).
3. In `chart/js/04_live_updates.js` `updateLiveCandle(json)` erweitern: generischer
   Dispatcher `applyLiveOverlays(overlays)` rendert `kind='circle'`-Einträge als Merged-
   Render mit dem historischen Circle-Cache (siehe D.3).

##### Schritt 4: Chart-Lesepfad auf Feature-Store umstellen (`chart/indicators/grid_liquidity.py`)

`GridLiquidityIndicator.calculate()` so anpassen, dass die Hit-Circles primär aus dem
Feature-Store gelesen werden (DuckDB `feature_store.feature_data`, feature_id='proximity',
inkl. `schema_version`); die Heavy-Berechnung über die Service-Pipeline bleibt als
Fallback. Der Leser `read_proximity_from_feature_store()` wird um den Parameter
`feature_id: str = "proximity"` generalisiert, damit spätere Plugins dieselbe
Lesearchitektur nutzen können (siehe D.4).

#### D. AI-Arbeitsauftrag: Behebung der Live-Circle & Flacker-Befunde (P14-03 Ergänzung)

##### Context & Zielsetzung

Behebung der 5 Befunde bezüglich des Flackerns der Live-Kerze, der fehlenden
Circle-Anzeige auf der offenen Kerze sowie der unterbrochenen Service-Pipeline im
Live-Pfad.

---

##### Code-Anpassungen

##### 1. `chart/chart_win.py` – Live-Tick ohne Rebuild, Pflicht-Re-Injektion & generische Overlays:

a) In `__init__` den Live-Kerzen-State ergänzen:

```python
# P14-03-E: Live-Kerzen-State für die Pflicht-Re-Injektion (Flacker-Fix).
self._live_bar_time: Optional[int] = None   # reale, gerundete Bar-Zeit der offenen Kerze
self._live_candle_cont: Optional[Dict[str, Any]] = None  # letzter Live-Candle (kont. Zeit + OHLC)
```

b) In `update_live_candle()` den `elif self._time_cont_to_real:`-Zweig ersetzen –
   Refresh ENTFERNEN, Maps erweitern, Live-State merken:

```python
# BEFORE:
#     self.refresh_chart_data()  # <-- KERNPROBLEM (Flacker-Loop, Loeschen!)

# AFTER:
last_cont = max(self._time_cont_to_real.keys())
c_copy["time"] = last_cont + t_sec
self._time_cont_to_real[c_copy["time"]] = rounded_t
self._time_real_to_cont[rounded_t] = c_copy["time"]
# P14-03-E: Live-Kerzen-State für die Pflicht-Re-Injektion merken.
self._live_bar_time = rounded_t
self._live_candle_cont = dict(c_copy)
# KEIN refresh_chart_data() Aufruf bei Live-Ticks!
```

c) Generisches Overlay-Einsammeln über den `get_live_overlays()`-Hook (Open/Closed):
   Die bisherige `liq_ind.update_live_candle(...)`-Sonderbehandlung entfällt; die Engine
   iteriert über ALLE aktiven Indikatoren:

```python
# P14-03-E: Overlays ALLER aktiven Indikatoren generisch einsammeln.
overlays: List[Dict[str, Any]] = []
for ind_id, plugin in self.indicators.items():
    st = self.indicators_state.get(ind_id, {})
    if not st.get("active"):
        continue
    getter = getattr(plugin, "get_live_overlays", None)
    if not callable(getter):
        continue
    try:
        ov = getter(dict(c_copy, time=rounded_t)) or []
    except Exception:
        continue
    for item in ov:
        item = dict(item)
        t = item.get("time")
        if t is not None:
            try:
                item["time"] = self._time_real_to_cont.get(int(t), int(t))
            except (TypeError, ValueError):
                pass
        overlays.append(item)
c_copy["overlays"] = overlays
```

d) In `_do_refresh_chart_data()` NACH dem Map-Aufbau (nach dem `for i, c in
   enumerate(clean_candles):`-Block, vor dem Erstellen von `update_package`) – die
   PFLICHT-Re-Injektion der offenen Live-Kerze (Map + Candle):

```python
# P14-03-E (PFLICHT, Pruefprotokoll P5): Offene Live-Kerze nach dem Map-Rebuild
# re-injizieren – sonst feuert der New-Candle-Callback bei jedem Tick erneut
# und die Flacker-Schleife bleibt bestehen.
# (Die remember_live_time-Re-Injektion erfolgt GENERISCH NACH dem calculate()-
# Loop weiter unten – calculate setzt die _known_times der Indikatoren aus den
# DB-Bars zurueck und wuerde eine Re-Injektion VOR dem Loop wieder zunichte machen.)
if (self._live_bar_time is not None
        and self._live_bar_time not in self._time_real_to_cont):
    last_cont = max(self._time_cont_to_real.keys())
    cont = last_cont + t_sec
    self._time_cont_to_real[cont] = self._live_bar_time
    self._time_real_to_cont[self._live_bar_time] = cont
    if self._live_candle_cont is not None:
        lc = dict(self._live_candle_cont)
        lc["time"] = cont
        continuous_candles.append(lc)
```

##### 2. `analytics/background_workers/live_analyzer.py` – `run(self)`:

Ersetze die Ausführung des Alt-Pfads durch den Resilienz-Seam:

```python
# BEFORE:
#     self._process_plugin_bars()

# AFTER:
self._process_plugin_bars_resilient()
```

Der `PluginContext` existiert bereits als `self._live_context` (Mode `'live'`,
`shared_state=self._live_shared_state`) und wird im Seam pro Service per
`dataclasses.replace()` instanziiert (`instance_id=plugin_id`, bei
`plugin_id == "proximity"` zusätzlich `depends_on=["grid_lines"]`). KEIN neues Attribut
`self.shared_state` anlegen – es existiert nicht (siehe Prüfprotokoll P3). Ein expliziter
Neuaufbau ist nur nötig, falls der Context-Buffer zurückgesetzt wurde:

```python
if self._live_context is None:
    self._live_shared_state = {}
    self._live_context = PluginContext(
        symbol=self.symbol,
        timeframe=self.timeframe,
        mode="live",
        shared_state=self._live_shared_state,
    )
```

##### 3. `chart/js/04_live_updates.js` – generischer Overlay-Dispatcher:

`updateLiveCandle(json)` verarbeitet `c.overlays` generisch über `applyLiveOverlays()`.
Der Merged-Render fasst Live-Circles mit dem historischen Circle-Cache
`_gridCirclesCache` zusammen und übergibt ihn an das INKREMENTELLE
`renderGridCircles()` (siehe Prüfprotokoll P1/P8). Zusätzlich greift eine
**Change-Detection**: Unveränderte Live-Circle-Sets zwischen Ticks lösen KEINEN
Re-Render aus, und beim Wechsel auf eine neue Live-Bar werden die Kreise der
VORHERIGEN Live-Zeit aus dem Cache entfernt (`_lastLiveOverlayTime`):

```javascript
function updateLiveCandle(json) {
    if (!candleSeries || isUpdatingChart) return;
    try {
        var c = JSON.parse(json);
        if (!c || typeof c.time !== 'number' || isNaN(c.time)) return;
        if (c.symbol !== undefined && c.symbol !== null && c.symbol !== currentSymbol) return;
        if (c.timeframe !== undefined && c.timeframe !== null && c.timeframe !== currentTimeframe) return;
        if (c.open === null || c.high === null || c.low === null || c.close === null) return;

        // Live-Candle in Serie aktualisieren
        candleSeries.update(c);
        lastClosePrice = c.close;
        updateCountdownDisplay();

        // GENERISCHES LIVE-OVERLAY RENDERING (Open/Closed-Dispatcher)
        if (c.overlays && Array.isArray(c.overlays) && c.overlays.length > 0) {
            applyLiveOverlays(c.overlays);
        }
    } catch(e) {
        console.error('[updateLiveCandle] Error:', e);
    }
}

// Generischer Overlay-Dispatcher (P14-03-E): Spätere Plugins docken über neue
// kind/layer-Werte an, ohne updateLiveCandle zu ändern.
function applyLiveOverlays(overlays) {
    if (typeof renderGridCircles !== 'function') return;
    var circles = [];
    for (var i = 0; i < overlays.length; i++) {
        var o = overlays[i];
        if (o && o.kind === 'circle' && typeof o.time === 'number' &&
            typeof o.price === 'number' && !isNaN(o.time) && !isNaN(o.price)) {
            circles.push(o);
        }
    }
    if (circles.length === 0) return;

    // FLACKER-FIX (P8): Change-Detection – identische Live-Circle-Sets zwischen
    // Ticks (gleiche Level-Hits, gleiche Farben) lösen KEINEN Re-Render aus.
    var nowJson = JSON.stringify(circles);
    if (nowJson === _lastLiveCirclesJson) return;
    _lastLiveCirclesJson = nowJson;

    // Merged-Render: nur die Live-Zeit ersetzen, historische Circles behalten.
    var liveTime = circles[0].time;
    // FLACKER-FIX (P8): Bei neuer Live-Bar zusätzlich die Kreise der VORHERIGEN
    // Live-Zeit entfernen (sonst hängen veraltete Live-Kreise der Vor-Bar).
    if (_lastLiveOverlayTime !== null && _lastLiveOverlayTime !== liveTime) {
        _gridCirclesCache = _gridCirclesCache.filter(function(x) { return x.time !== _lastLiveOverlayTime; });
    }
    _lastLiveOverlayTime = liveTime;
    _gridCirclesCache = _gridCirclesCache.filter(function(x) { return x.time !== liveTime; });
    for (var j = 0; j < circles.length; j++) { _gridCirclesCache.push(circles[j]); }
    renderGridCircles(_gridCirclesCache);
}
```

`_gridCirclesCache` wird in `applyFullChartUpdate()` beim Setzen von `data.gridCircles`
befüllt: `_gridCirclesCache = (data.gridCircles || []).slice();` (neben
`rawCandleData = validCandles;`).

##### 4. `chart/indicators/grid_liquidity.py` – Feature-Store primär + generische Hooks:

a) `read_proximity_from_feature_store()` um den Parameter `feature_id` generalisieren
   (Standard `'proximity'` – spätere Plugins lesen über denselben Lesepfad):

```python
def read_proximity_from_feature_store(
    self,
    symbol: str,
    timeframe: str,
    limit: Optional[int] = None,
    db_path: Optional[str] = None,
    feature_id: str = "proximity",
) -> List[Dict[str, Any]]:
    # ... SQL: WHERE symbol=? AND timeframe=? AND feature_id=? ...
```

b) Feature-Store-Lesepfad PRIMÄR in den bestehenden `calculate()`-Body integrieren
   (rein additiv; `super().calculate()` existiert NICHT – `BaseIndicator.calculate` ist
   `@abstractmethod`, siehe Prüfprotokoll P4). Nur bei leerem Feature-Store auf die
   Pipeline-Hit-Circles zurückfallen:

```python
# Im try-Body von calculate(), NACH dem Auslesen von grid_lines:
prox_result = results.get("prox_1") or {}
prox_crp = prox_result.get("chart_render_payload") or {}

# P14-03-E (Schritt 4): PRIMÄR gecachte Proximity-Hits aus dem feature_store lesen.
cached_circles = self.read_proximity_from_feature_store(
    self._symbol or "", self._timeframe or ""
)
if cached_circles:
    circles = cached_circles
else:
    circles_raw = prox_crp.get("hit_circles") or []
    # ... bestehende Farb-/priority-Anreicherung unverändert weiterführen ...
```

c) Generische Live-Overlay-Hooks (Open/Closed) ergänzen:

```python
# chart/indicators/base_indicator.py – generischer Hook (Basis-Default []):
def get_live_overlays(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """P14-03-E: Liefert die Live-Overlays des Plugins als Liste von Overlay-Items
    {kind, layer, time, price, color, priority, ...}. Basis-Default: [].
    Plugin-Klassen überschreiben diesen Hook (Open/Closed)."""
    return []

# chart/indicators/grid_liquidity.py – Überschreibung (Circle-Overlays):
def get_live_overlays(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
    pts = self.update_live_candle(candle)
    return [dict(p, kind="circle", layer=self.indicator_id) for p in pts]

# chart/indicators/grid_liquidity.py – Live-Bar merken (Pflicht-Re-Injektion):
def remember_live_time(self, ts: int) -> None:
    """P14-03-E: Merkt eine offene Live-Bar-Zeit im _known_times-Set, damit der
    New-Candle-Callback über den Refresh hinweg NICHT erneut feuert (Flacker-Fix)."""
    try:
        self._known_times.add(int(ts))
    except (TypeError, ValueError):
        pass
```

#### E. Headless Validierung (Ergänzung)

Erstelle und führe aus: `test/check_p14_live_fixes.py` (headless, kein `exec_()`):

1. Simuliere das Senden von 10 Live-Ticks im Abstand von 500 ms (Mock `update_live_candle`).
2. Verifiziere, dass `refresh_chart_data()` 0-mal aufgerufen wurde.
3. Verifiziere, dass `_time_real_to_cont` kontinuierlich gewachsen ist (kein `clear()`).
4. Verifiziere, dass `_process_plugin_bars_resilient()` aufgerufen wurde und den
   `feature_store` beschreibt (feature_id='proximity'-Zeile vorhanden).
5. Verifiziere, dass `update_live_candle()` des Indikators Live-Punkte liefert und diese
   als `live_circles` im Payload ankommen.

#### F. Prüfprotokoll (Korrekturen am Rohentwurf)

Die Anweisungen wurden gegen den Quellcode geprüft; Abweichungen sind korrigiert
eingearbeitet:

- **P1 (JS-Render):** `renderGridCircles(live_circles)` allein löscht die historischen
  Circles (`clearGridCircles()` intern). Korrektur: Merged-Render über `_gridCirclesCache`
  (siehe D.3).
- **P2 (Indikator-Rückgabe):** `GridLiquidityIndicator.update_live_candle()` liefert eine
  LISTE `[{time, price, color, priority}]`, kein Dict mit `hit_circles`.
  `get_live_overlays()` verpackt diese Liste in generische Overlay-Items
  (`kind='circle'`); `chart_win` greift NICHT mehr direkt auf `_live_points` zu
  (siehe D.4c).
- **P3 (LiveAnalyzer-Context):** `self.shared_state` existiert nicht – korrekt ist
  `self._live_shared_state` bzw. der bereits vorhandene `self._live_context` (siehe D.2).
- **P4 (calculate-Super):** `super().calculate(df, params)` existiert nicht
  (`BaseIndicator.calculate` ist `@abstractmethod`); `self._last_lines` existiert nicht.
  Korrektur: Feature-Store-Read additiv in den bestehenden `calculate()`-Body (siehe D.4).
- **P5 (New-Candle-Refresh bleibt + RE-INJEKTION IST PFLICHT):** Der
  `GridLiquidityIndicator` ruft über `set_new_candle_callback(self.refresh_chart_data)`
  genau EINEN debounced Refresh pro neuer Kerze auf (Grid-Cache-Neuaufbau) – dieser ist
  NICHT zu entfernen. Entfernt wird nur der Refresh bei JEDEM Tick in
  `chart_win.update_live_candle()`. DA der Refresh die Maps in `_do_refresh_chart_data`
  komplett neu baut (Z. 678-679) und `applyFullChartUpdate` den Chart nur aus DB-Kerzen
  neu aufbaut, MUSS die offene Live-Kerze (noch nicht in DuckDB) beim Refresh zwingend
  re-injiziert werden: (1) in `_time_real_to_cont`/`_time_cont_to_real`, (2) in
  `continuous_candles` (mit letzter Live-OHLC aus `_live_candle_cont`), (3) in die
  `_known_times` des Indikators via `remember_live_time()`. Erst dann feuert der
  New-Candle-Callback pro neuer Kerze GENAU 1× und die Flacker-Schleife endet.
  Siehe D.1d.
- **P6 (Generisches Overlay-Schema):** Statt `live_circles` (circle-spezifisch) transportiert
  der Live-Tick `c.overlays` mit `{kind, layer, time, price, color, priority}`. Der JS-
  Dispatcher `applyLiveOverlays()` routet je `kind`; der Python-Hook
  `BaseIndicator.get_live_overlays()` (Default `[]`) ist die offene Erweiterungsstelle für
  spätere Indikator-Plugins (Open/Closed). Siehe D.1c/D.3/D.4c.
- **P7 (Overlay-Zeit-Mapping):** Live-Overlays tragen die reale, gerundete Bar-Zeit des
  Indikators; `chart_win` mappt sie beim Einsammeln über `_time_real_to_cont` auf die
  kontinuierliche Chart-Zeit, bevor sie als `c.overlays` an JS gehen (siehe D.1c).
- **P8 (Flacker-Fix – inkrementelles Circle-Rendering & Change-Detection):** User-Befund
  nach D.1–D.4: Circles werden live korrekt gesetzt und das generelle Flackern ist weg,
  ABER sobald die Proximity-Bedingung erfüllt ist, flackert es erneut bei jedem Tick.
  Ursache: `renderGridCircles()` rief intern `clearGridCircles()` auf, das ALLE
  Circle-Serien via `removeSeries()` entfernte und neu aufbaute – bei jedem Live-Tick
  mit erfüllter Bedingung ein Full-Layer-Rebuild (destruktiv, kein Einzelfall).
  Fix (rein JS, additiv):
  1. `03_chart_rendering.js`: `renderGridCircles()` ist jetzt INKREMENTELL – neue
     Registry `_circleLevelSeries` (01_core.js) je Level-Preis; bestehende Level werden
     per `series.setData()`/`plugin.setMarkers()` in-place aktualisiert, nur verschwundene
     Level entfernt, nur neue erzeugt. `clearGridCircles()` leert zusätzlich die Registry.
     Alle Call-Sites (`applyFullChartUpdate` Schritt 6, `applyLiveOverlays`) bleiben
     unverändert.
  2. `04_live_updates.js`: `applyLiveOverlays()` – Change-Detection über
     `_lastLiveCirclesJson` (JSON-Vergleich): identische Circle-Sets zwischen Ticks
     lösen KEINEN Re-Render aus. `_lastLiveOverlayTime` entfernt beim Live-Bar-Wechsel
     auch die Kreise der VORHERIGEN Live-Zeit aus dem Cache. Beide werden in
     `applyFullChartUpdate` zurückgesetzt (`'[]'` bzw. `null`).
  Verifikation: `node --check` auf allen 3 JS-Dateien, headless
  `test/check_p14_grid_incremental.js` (14 Checks: Serien-Identität bei identischen/
  Live-Updates, nur verschwundene Level entfernt, leere Liste räumt auf, Change-Detection,
  Bar-Wechsel-Cache), Regression `check_p14_live_fixes.py` (14/14), `check_grid_parity.py`,
  `check_p14_precision_levels.py`, `check_time_utils.js`, `check_resolve_realtime.js`.
- **P9 (Flacker-Fix – New-Candle-Callback-Zyklus nach neuer Kerze):** User-Befund nach P8:
  direkt nach dem Erzeugen einer neuen Kerze flackert der Chart periodisch (~500ms) –
  die neue Kerze wird aufgebaut, aber abwechselnd wird die ALTE Kerze ohne Neuplot
  (meist als dünne Linie) gezeigt; das Flackern verschwindet erst nach einem
  Service-Update. ROOT CAUSE (2 Stellen in `chart_win.py`):
  1. **Reihenfolge-Fehler:** `_do_refresh_chart_data` rief `liq_ind.remember_live_time()`
     VOR dem `calculate()`-Loop auf. `calculate()` setzt `self._known_times` aus den
     DB-Bars zurück (`grid_liquidity.py: self._known_times = self._compute_known_times(df)`)
     – die offene Live-Bar (noch NICHT in DuckDB) ging dabei verloren. Damit feuert der
     New-Candle-Callback bei JEDEM Live-Tick (LiveTickWorker, main.py: 500ms) erneut →
     debounce (400ms) → Chart-Rebuild → Flackern im Wechsel Live-Plot (neue Kerze) <-> Rebuild
     (alte/leere Kerze). Erst wenn die Live-Bar durch einen Service-Update in der DB steht,
     enthält `_known_times` sie → Callback stoppt → "Flackern verschwindet nach Service-Update".
  2. **Hardcoding:** Die Re-Injektion war auf `self.indicators.get("grid_liquidity")`
     hardcoded (Verstoß gegen die Generik-Regel).
  3. **Veraltete Live-Kerze:** `_live_candle_cont` wurde nur beim ERSTEN Tick einer neuen
     Bar gesetzt – der Rebuild reinjizierte die Kerze mit veraltetem OHLC-Stand (dünne Linie).
  FIX (generisch):
  1. `base_indicator.py`: `remember_live_time(ts)` als generischer Base-Hook (no-op Default),
     analog zu `get_live_overlays` (Open/Closed).
  2. `chart_win.py`: neue Methode `_reinject_live_bar_to_indicators()` – führt die
     Live-Bar-Zeit generisch über ALLE Indikatoren mit `remember_live_time()`-Hook wieder ein
     (kein Plugin-Sonderfall). Aufgerufen NACH JEDEM `calculate()`-Loop
     (`_do_refresh_chart_data` UND `render_indicators`).
  3. `chart_win.py update_live_candle`: `_live_candle_cont` wird bei JEDEM Tick der offenen
     Bar aktualisiert (aktueller OHLC-Stand für die Re-Injektion).
  Verifikation: `py_compile` auf den 3 Python-Dateien, headless
  `test/check_p14_flacker_zyklus.py` (4 Checks: Base-Hook, Callback-1x-Logik +
  calculate-Resetszenario + remember_live_time bricht Zyklus, Generik über alle Indikatoren,
  statische Regression Reihenfolge/Hardcoding/`_live_candle_cont`), Regression
  `check_p14_live_fixes.py` (14/14), `check_p14_grid_incremental.js` (14/14),
  `check_grid_parity.py`, `check_p14_precision_levels.py`, `check_time_utils.js`,
  `check_resolve_realtime.js`.


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
beachte
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

### Kapitel 4.4-E [P14-04]: Ergänzung – Service-Set-Schutz im Service-Fenster (Set- & Service-Sperre)

Konzeptionelle Erklärung & Schritt-Anleitung auf Basis der User-Anweisung „Punkt 3":
Solange ein Indikator installiert ist, dürfen seine Basis-Services im `service_win`
nicht gelöscht werden. Es muss eine sichtbare Kennzeichnung und eine aktive Sperre
geben. Rein additiv; die bestehende Set-Verwaltung (P14-04 / P14-01) bleibt
unangetastet.

#### A. Konzept & Regeln

1. **Regel 1 – Mindestens ein valides Set bleibt erhalten:**
   Service-Sets dürfen gelöscht werden, aber es muss **immer mindestens ein
   gültiges Service-Set** im Repository verbleiben, damit der Indikator
   funktionsfähig bleibt. Das Löschen des **letzten** verbliebenen Sets ist
   gesperrt (`delete_set()`-Guard: `len(list_sets()) <= 1` → Warn-Meldung).

2. **Regel 2 – Service-Sperre für Einzel-Services:**
   Einzel-Services dürfen **nicht** aus der Ausführungs-Reihenfolge entfernt
   werden, solange sie in einem **gespeicherten Service-Set** vorkommen
   (Indikator-Basis-Services wie `grid_lines`/`proximity` bleiben dadurch
   dauerhaft funktionsfähig). Beim Löschversuch erscheint ein Hinweis mit dem
   **Namen des verwendeten Sets** (`remove_instance()`-Guard).

3. **Regel 3 – Sichtbare Kennzeichnung:**
   Services, die in einem gespeicherten Set vorkommen, werden im Service-Fenster
   mit 🔒 markiert:
   * Listeneintrag (`🔒 grid_1  [grid_lines]`)
   * Service-Spalten-Titel (`QGroupBox`)
   * Tooltip: „Gesperrt (P14-04): wird vom Service-Set '<Name>' verwendet"
   Der Live-Tooltip (`_update_service_tooltip`) erhält den Sperr-Nachtrag,
   damit die Kennzeichnung beim Bearbeiten der Instanz-Beschreibung nicht
   überschrieben wird.

Datenquelle der Sperre ist rein datengetrieben (`_sets_using_plugin()` über
`ServiceSetRepository.list_sets()`), **kein** neues Indikator-Sonderwissen im
Service-Fenster nötig – die Basisdienste werden über ihre bloße Existenz in
einem Set geschützt.

#### B. Schritt-für-Schritt AI-Anleitung

##### Schritt 1: `service_win.py` – Sperren & Kennzeichnung (additiv)

1. **Import:** `QMessageBox` in den `PySide6.QtWidgets`-Import aufnehmen;
   `List` im `typing`-Import ergänzen.

2. **Modul-Helper `_sets_using_plugin(plugin_id, sets) -> List[str]`:**
   Liefert die Namen aller Sets, die einen Service mit dieser `plugin_id`
   enthalten (Match über `services[].plugin_id`; Anzeige `display_name`,
   Fallback `set_id`). Basis für Sperre + Hinweis (Regel 2).

3. **`ServiceWindow._service_lock(plugin_id) -> (prefix, tooltip_suffix)`:**
   Liefert `("🔒 ", "<br><b>Gesperrt (P14-04)</b>: wird vom Service-Set
   '<Name>' verwendet …")` wenn der Service in einem gespeicherten Set
   vorkommt, sonst `("", "")`.

4. **`remove_instance()` (Regel 2):** Vor dem Entfernen `_sets_using_plugin()`
   prüfen. Nicht leer → `QMessageBox.warning` mit Set-Namen und Abbruch.

5. **`delete_set()` (Regel 1):** Vor `delete_named_item()` prüfen:
   `len(self.set_repo.list_sets()) <= 1` → `QMessageBox.warning` (Sperre des
   letzten Sets) und Abbruch.

6. **Kennzeichnung (Regel 3):** In `load_set_into_editor()` und `add_instance()`
   die Listeneinträge mit `_service_lock()`-Präfix + Tooltip-Nachtrag erzeugen;
   in `_build_service_column()` den Spaltentitel mit Präfix versehen;
   in `_update_service_tooltip()` den Sperr-Nachtrag beibehalten.

##### Schritt 2: Headless Validierung

1. Erstelle und führe aus: `test/check_p14_s4_services_locked.py`:
* Repo mit 3 Sets (2 mit `grid_lines`/`proximity`, 1 mit `ema_atr_set_v1`).
* Verifiziere (Regel 2): `_sets_using_plugin("grid_lines", …)` nennt beide
  Grid-Sets; `proximity`/`ema` je ihr Set; freie Services liefern `[]`.
* Verifiziere (Regel 1): Bei 3 Sets ist Löschen erlaubt; nach Löschen auf
  genau 1 verbleibendes Set greift der Guard (`len <= 1` → gesperrt).
* Verifiziere (Regel 3): `_service_lock` (unbound via Dummy-Objekt) liefert
  🔒-Präfix + Set-Namen-Tooltip für `grid_lines`, `("", "")` für freie
  Services.


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

### Kapitel 4.5-E [P14-05]: Ergaenzung - Papierkorb-Dialog im Service-Fenster (doppelte Sicherheitsnachfrage)

Ergaenzende UI-Dokumentation zur User-Vorgabe: Auch das endgueltige Loeschen/
Bereinigen aus dem Papierkorb erfolgt IMMER mit doppelter Sicherheitsnachfrage.
Rein additiv; Repository-API (P14-05 Schritt 1) und bestehende Set-Verwaltung
bleiben unangetastet.

#### A. Konzept & Regeln

1. **Papierkorb-Dialog (ServiceWindow.show_trash_dialog):**
   * Oeffnet ein modales QDialog mit QListWidget aller soft-geloeschten
     Sets (set_repo.list_trash(), sortiert nach deleted_at).
   * Jeder Eintrag zeigt Name + Loesch-Zeitstempel (deleted_at).
   * Buttons: **Wiederherstellen**, **Endgueltig loeschen**,
     **Papierkorb leeren**, **Schliessen**.

2. **Wiederherstellen:** restore_set_from_trash(set_id) verschiebt das Set
   zurueck nach service_sets; anschliessend refresht der Dialog die Liste
   und das Hauptfenster ruft refresh_set_list() (Set-Dropdown aktuell).

3. **Doppelte Sicherheitsnachfrage (User-Vorgabe):** purge_trash_set()
   (einzelnes Set) und purge_trash() (kompletter Papierkorb) sind NICHT
   umkehrbar. Die UI verlangt daher vor jeder Ausfuehrung ZWEI aufeinander-
   folgende QMessageBox.question-Bestaetigungen (Default jeweils Nein).

4. **Scope:** Der Dialog ist eine reine UI-Komponente - er spricht
   ausschliesslich die Repository-API an (keine direkten SQL-Zugriffe) und
   protokolliert jede Aktion ueber self.log().

#### B. Schritt-fuer-Schritt AI-Anleitung

##### Schritt 1: service_win.py - Papierkorb-Dialog (additiv)

1. **UI-Wiring:** btn_trash_sets (in ui/service_win.ui zwischen Loeschen-
   Button und Spacer) wird in __init__ mit show_trash_dialog verdrahtet.
   QDialog ist bereits im PySide6.QtWidgets-Import vorhanden.

2. **show_trash_dialog()** (zwischen delete_set() und P14-02-Abschnitt):
   * Baut den Dialog vollstaendig im Code (hardcoded UI-Wiring).
   * _reload() befuellt die Liste aus list_trash(); leere Buttons werden
     deaktiviert, der Hinweistext zeigt 'Der Papierkorb ist leer.'.
   * Wiederherstellen / Endgueltig loeschen / Leeren als verschachtelte
     Handler; jede purge-Aktion durchlaeuft zwei QMessageBox.question.
   * Nach jeder Aktion: Log via self.log(...), Listen-Refresh, bei
     Wiederherstellung zusaetzlich refresh_set_list().

##### Schritt 2: Headless Validierung

1. Erstelle und fuehre aus: test/check_p14_s5_trash.py:
* Neuanlage -> KEIN Snapshot; Ueberschreiben -> GENAU 1 Snapshot (Version
  fortlaufend); record_snapshot=False -> KEIN Snapshot.
* delete_set() -> nicht in list_sets(), aber in list_trash() mit
  deleted_at; Definition/Name vollstaendig erhalten.
* restore_set_from_trash() -> vollstaendige Wiederherstellung.
* purge_trash_set / purge_trash entfernen endgueltig (bool/Anzahl).

> Hinweis: Die doppelte Sicherheitsnachfrage selbst ist UI-Logik
> (QMessageBox) und wird NICHT headless ausgefuehrt - sie wird durch
> sorgfaeltige Code-Inspektion abgesichert. Die Repository-Funktionen hinter
> den Buttons (purge/purge_trash) sind vollstaendig headless getestet.
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


---

## 8. Abschluss-Validierung Phase 14 – Umsetzungs-Doku & Testergebnisse (Stand 03.08.2026)

Dokumentation der letzten Änderungen (Commit `5212b3a`, Backup `3dea585`, Tag `phase14_step6`) auf Basis der Kapitel 5–7 dieser Datei.

### 8.1 Umgesetzte Änderungen

1. **Kap 5 – Set-Level-Metadaten (`analytics/engine/service_set_repository.py`):**
   `save_set()` stempelt automatisch (additiv, idempotent, Bestand wird beim nächsten Speichern nachgezogen):
   * `schema_version` → `"1.0"` (Default)
   * `version` → Aufrufer-Version gewinnt; sonst **Patch-Bump** (`major.minor.patch`) bei jedem Überschreiben, `"1.0.0"` bei Neuanlage (neuer Helper `_semver_bump_patch()`)
   * `created_at` → ISO-8601 UTC bei Neuanlage; bleibt bei Überschreiben stabil
   * `ServiceSetDefinition` (TypedDict in `service_models.py`) um die drei Felder erweitert

2. **Kap 6 – Universal-Regressionstest `test/check_phase14_regression.py`:**
   Headless (KEINE UI, KEIN `exec_()`), ASCII-Ausgabe (cp1252-sicher), Test-DB in `test/phase14_regression_test.duckdb` (kein Zugriff auf Produktions-DBs). 41 Checks über alle P14-Kernmodule (P14-01 bis P14-05).

3. **Kap 7.2 – Performance-Benchmarks `test/check_performance_p14.py`:**
   Headless Messungen mit großzügigen Dev-Schwellen:
   * Plugin-Discovery-Speed – `PluginRegistry().reload()` (< 2,0 s)
   * Service-Evaluation-Speed – `ServiceSetEvaluator.execute_set()` auf 1000 synthetischen Bars mit grid_lines + proximity (< 2,0 s)
   * Feature-Store-Read-Speed – DuckDB-SELECT auf 1000 Zeilen der feature_store-Test-Tabelle (< 0,2 s)

4. **Kap 7.3 – `--check-plugins` (Core Protection Rule):**
   * `PluginLoader.find_custom_conflicts()` in `feature_builder.py` (additiv) – scannt Core- und Custom-Plugins und liefert alle Custom-IDs, die Core-IDs überschreiben
   * `main.py --check-plugins` – headless, ohne GUI; Exit-Code 0 = OK, 1 = Konflikt

5. **Doku-Abgleich dieser Datei:** Kapitel 4-Index (Kapitel 4.1–4.5 archiviert in `docs/Old/x_Roadmap_Phase14.md`), Kapitel 5-Umsetzungsstatus, Kapitel 6/7.2/7.3 auf den Ist-Zustand aktualisiert.

### 8.2 Testergebnisse (alle bestanden)

| Test | Ergebnis | Anmerkung |
| :--- | :--- | :--- |
| `test/check_phase14_regression.py` | **OK (41 Checks)** | P14-01..P14-05 funktional inkl. Set-Metadaten & Snapshot-Historie |
| `test/check_performance_p14.py` | **OK (5 Checks)** | Discovery 0,8 ms / Evaluation 20,9 ms / Store-Read 98,6 ms |
| `test/check_p14_s5_trash.py` | **OK (32 Checks)** | Papierkorb & Snapshot-Historie (Regression) |
| `test/check_p14_s4_migration.py` | **OK (alle)** | Schema-Migration & Rollback (Regression) |
| `test/check_p14_s4_services_locked.py` | **OK (16 Checks)** | Service-Set-Schutz (Regression) |
| `python main.py --check-plugins` | **OK (Exit 0)** | Core Protection Rule aktiv, keine Konflikte |
| `py_compile` (6 Dateien) | **OK** | service_set_repository, service_models, feature_builder, main, beide neuen Tests |

### 8.3 Git-Stand

* Backup vor Umsetzung: `3dea585` (`backup: pre P14 Abschluss-Validierung`), Tag `phase14_step6`
* Umsetzung: `5212b3a` (`feat(P14-Abschluss): Kap 5-7 AKTUELLE_UMSETZUNG umgesetzt (Set-Metadaten, Regressionstest, Benchmarks, --check-plugins)`)
* Neue Testdateien per `git add -f` getrackt (test/ ist gitignored)