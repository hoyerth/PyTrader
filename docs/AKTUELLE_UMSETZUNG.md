# Phase 15: Service UI, Symbol-Verwaltung & Analytics Engine

## 1. Übersicht & Zielsetzung

Ziel von **Phase 15** ist die Weiterentwicklung der Service-UI (`service_win.py`), die Bereitstellung einer zentralen Symbol- und Favoritenverwaltung, der systematische Abbau von Alt-Pfaden sowie der Aufbau einer hochperformanten, entkoppelten Analytics-Engine auf Basis der Plugin- und Service-Architektur (Phasen 12–14).

* **15.01 Symbol-Auswahl & Favoriten:** Broker-Fetch via MT5, Persistierung in `app_data.duckdb`, Favoriten-Dropdowns & nicht-modales `SymbolsWindow`.
* **15.02 Service-UI Refactoring & Master-Tree:** Modularisierung der gewachsenen `service_win.py` in Orchestrator + Sub-Widgets (`MasterTree`, `ParameterPanel`, `Toolbar`), Einführung von `ServiceTreeModel`, 2-Spalten-TreeWidget mit Indikator-Live-Status (`📌` / `🟢`) & Buttons für Struktur-Aktionen.
* **15.03 Analytics Engine & UI:** Ersetzung von `../../statistic_win.py` durch `AnalyticsWindow` (`analytics/ui/analytics_win.py`), Entkopplung via MVVM (`AnalyticsViewModel`, `AnalyticsRepository`, `FeatureStoreReader`), `pyqtgraph`-Visualisierungen (Tabelle, Heatmap, Scatter, Verteilung), Profil-CRUD mit Explicit Save (`*`) & `schema_version` im Profil-JSON, Entkopplung über einen zentralen `EventBus`.

---

## 2. Allgemeine Grundsätze & Architektur-Invarianten

2. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase15_step1`, `phase15_step2` usw.).
3. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte in `test`.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
5. **Zentraler `EventBus`:** Fenster kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db_service.py`).
7. **Wanduhr-Garantie:** Achsen und Zeitfilter formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.

### Entscheidungs-Protokoll Phase 15 (Beschluss 04.08.2026)

| # | Thema | Entscheidung |
| --- | --- | --- |
| E-1 | Legacy-Alias `../../analytics/statistics_repository.py` | Bleibt bis auf Weiteres unverändert bestehen; kompletter Ersatz erst in einer späteren Phase |
| E-2 | Persistenz `win_statistics` | Fenstergeometrie & Instanz-Zustände werden beim Ersetzen nach `win_analytics` migriert |
| E-3 | `schema_version` Pflichtfeld | Pflichtfeld im `FeatureStorePayload`; alte `feature_store`-Rows erhalten beim Lesen den Default `"1.0"` |
| E-4 | Schutzregel Grid-Liquidity | Schutz für `../../chart/indicators/grid_liquidity.py` aufgehoben; Anpassungen erlaubt, wenn der Fallback-Abbau sie erfordert |
| E-5 | Zeilenzahl `service_win.py` | Doku-Korrektur: 864 Zeilen (statt 1.400) |
| E-6 | Pfad-Konvention | Dateien werden einheitlich vom Projekt-Root referenziert (ohne `../..`) |

---

# 15.02 Service-UI Refactoring, Master-Tree & Generischer ServiceSelector

## 1. SPEZIFIKATION (15.02)

* **Modularisierung (`service_win.py` als Orchestrator):** Zerlegung der gewachsenen `service_win.py` (864 Zeilen, E-5) in entkoppelte, wiederverwendbare Sub-Komponenten:
* `serviceui/master_tree.py`: 2-Spalten `QTreeWidget` für die hierarchische Darstellung.
* `serviceui/parameter_panel.py`: Parameter-Formular mit `ContentScrollMixin`.
* `serviceui/toolbar.py`: Aktions-Buttons (`[➕ Service]`, `[▲]`, `[▼]`, `[🗑️ Entfernen]`).
* `serviceui/status_panel.py`: Status- und Log-Anzeigen.
* `serviceui/service_selector_widget.py`: Generisches Auswahl-Widget (wiederverwendbar).
* **Generische Service- & Set-Auswahl (`ServiceSelectorModel` & `ServiceSelectorWidget`):**
* **`ServiceSelectorModel` (`analytics/engine/service_selector_model.py`):** Zentrales, lesendes Datenmodell. Lädt Sets und Services aus `ServiceSetRepository` und `PluginRegistry`. Hört auf `EventBus.service_set_changed` für automatische Live-Aktualisierung in allen Fenstern.
* **`ServiceSelectorWidget` (`serviceui/service_selector_widget.py`):** Konfigurierbares PySide6-Widget mit zwei Betriebsmodi:
* **Modus A (`SELECT_ONLY`):** Kompaktes Popover/Dropdown-Auswahl-Widget für schwellenfreie Wiederverwendung in Analytics (15.03), Backtester oder Charts. Emittiert `selection_changed(set_id, service_id)`.
* **Modus B (`FULL_EDIT`):** Vollständiges Master-Tree-Widget mit Aktions-Toolbar für `service_win.py` (Erstellen, Umsortieren, Löschen).
* **2-Spalten-MasterTree Visualisierung (Modus B):**
* *Spalte 0:* Hierarchische Knoten (📁 Service-Sets, ⚡ Standalone Services, 📦 Alle verfügbaren Plugins).
* *Spalte 1:* Kompakte Status-Badges (`📌 Indikator: <Name> | 🟢 Aktiv in Chart` oder `⚪ Inaktiv in Chart`).
* **Deterministische Bedienung ("Tree + Buttons"):**
* Klick auf `[➕ Service hinzufügen]` $\rightarrow$ Popup-Auswahl des Plugins $\rightarrow$ Hinzufügen ins aktive Set via `ServiceSetRepository.save_set()`.
* Buttons `[▲]` / `[▼]` ändern die `execution_order` im Set.
* Button `[🗑️]` führt P14-04 Sperr-Prüfung durch (Warnung bei aktiven Indikatoren).

---

## 2. SCHRITT-FÜR-SCHRITT ANLEITUNG (15.02)

1. **Backup:** Git Commit `phase15_s2_backup`.

2. **Generisches Datenmodell & Selector-Widget erstellen:**
* `analytics/engine/service_selector_model.py`: Aufbereitung der Hierarchie & Live-Status-Badging aus `ServiceSetRepository` und `StateManager`.
* `serviceui/service_selector_widget.py`: Erstellung des wiederverwendbaren Widgets mit Modus-Umschaltung (`SELECT_ONLY` vs. `FULL_EDIT`).

3. **Sub-Widgets für `service_win.py` erstellen:**
* `serviceui/master_tree.py` (nutzt `ServiceSelectorWidget` im Modus `FULL_EDIT`).
* `serviceui/parameter_panel.py`, `serviceui/toolbar.py`, `serviceui/status_panel.py` erstellen.

4. **`service_win.py` Refactoring:**
* Fenstergröße auf `1280 x 800` anpassen.
* Umbau auf `QSplitter` mit Zusammensetzung der Sub-Widgets als schlanker Orchestrator.

5. **Action-Handler & EventBus-Sync:**
* Aktions-Buttons in `toolbar.py` mit `ServiceSetRepository` koppeln.
* Bei jeder Struktur- oder Parameter-Änderung `EventBus.service_set_changed` emittieren, um alle lauschenden `ServiceSelectorModel`-Instanzen projektweit automatisch zu aktualisieren.

6. **Headless-Test (`test/check_p15_s2_service_tree.py`):**
* Prüft `ServiceSelectorModel` im Modus `SELECT_ONLY` und `FULL_EDIT` ohne GUI.
* Prüft Indikator-Status-Badges, Set-Updates, Umsortieren & EventBus-Reaktivität.

---

## 3. Implementierungs-Log

### 3.1 Schritt 1 – Backup (Commit `0aaba70`, Tag `phase15_s2_backup`)

Die vom Anwender neu aufgesetzte `docs/AKTUELLE_UMSETZUNG.md` (15.02-Spezifikation, alte 15.03-Inhalte nach `docs/Old/x_Roadmap_Phase15.md` archiviert) wurde als Arbeitsstand gesichert. Tag `phase15_s2_backup` gesetzt.

### 3.2 Schritt 2 – ServiceSelectorModel & ServiceSelectorWidget

**`analytics/engine/service_selector_model.py` (NEU):** Zentrales, lesendes Datenmodell (`ServiceSelectorModel`, QObject mit `data_changed`-Signal):
* Quellen: `ServiceSetRepository.list_sets()`, `PluginRegistry`, `StateManager.load_all_instances()` (Live-Status „aktiv im Chart" via `indicators_state[*]['active']`).
* `build_tree()` liefert die deterministische 3-Gruppen-Hierarchie (📁 Service-Sets / ⚡ Standalone Services / 📦 Alle verfügbaren Plugins) inkl. Status-Badges.
* `badge_for(plugin_id)`: `📌 Indikator: <Name>` (capabilities.chart) + `🟢 Aktiv in Chart` / `⚪ Inaktiv in Chart`.
* Hört auf `EventBus.service_set_changed` → `refresh()` (Live-Sync in allen Fenstern, Invariante 5).
* Reines Lesemodell – kein SQL, kein Schreiben (Invariante 4).

**`serviceui/service_selector_widget.py` (NEU):** `ServiceSelectorWidget` mit Modus-Umschaltung:
* Modus A (`SELECT_ONLY`): kompakte Set-/Service-Combos, emittiert `selection_changed(set_id, service_id)`.
* Modus B (`FULL_EDIT`): MasterTree + ServiceToolbar (2-Spalten-Hierarchie + Aktions-Buttons).

### 3.3 Schritt 3 – Sub-Widgets

* **`serviceui/master_tree.py` (NEU):** `MasterTree` – 2-Spalten-`QTreeWidget` (Spalte 0: Hierarchie, Spalte 1: Status-Badges), befüllt aus dem Modell, `selection_changed(set_id, service_id)`, `current_selection()`/`current_set_id()`/`current_service_id()`, Auswahl-Restore nach Refresh.
* **`serviceui/toolbar.py` (NEU):** `ServiceToolbar` – `[➕ Service]` (Popup-Plugin-Auswahl → `add_service_requested(plugin_id)`), `[▲]/[▼]`, `[🗑️ Entfernen]`, `[🔄 Plugins]`. Reine Signal-Emitter (SRP, kein SQL).
* **`serviceui/status_panel.py` (NEU):** `StatusPanel` – Laufzeit/Fortschritt/Log (Auto-Scroll), reines Anzeige-Widget.
* **`serviceui/parameter_panel.py` (NEU):** `ParameterPanel` – scrollbares Parameter-Formular (`ContentScrollMixin` + Wiederverwendung der Control-Builder aus `ServiceParamColumnsMixin`), `set_service(instance_id, plugin_id, config)`, `params_changed(instance_id, params)`.

### 3.4 Schritt 4 – `service_win.py` Refactoring (Orchestrator)

* **`serviceui/service_win.py` (Anpassung):** Fensteraufbau um einen `QSplitter` (horizontal) erweitert: links bestehender Set-Editor + dynamische Service-Spalten, rechts `ServiceSelectorWidget` (Modus `FULL_EDIT`) + `ParameterPanel`. Bestehende Scanner-/Set-/Evaluator-Logik bleibt unverändert (Verbotsregel).
* **Fenstergröße 1280 x 800:** Single Source of Truth ist die `ui/service_win.ui`-Geometrie (vom QUiLoader angewendet) – kein fixer `resize()`-Aufruf im Code, damit der 5.4-Content-Reflow (`resize_to_clamped_content`) die Größe weiterhin inhalt-/bildschirmbasiert anpassen kann.
* **`serviceui/__init__.py`:** Export der neuen Sub-Widgets (`MasterTree`, `ServiceToolbar`, `StatusPanel`, `ParameterPanel`, `ServiceSelectorWidget`).

### 3.5 Schritt 5 – Action-Handler & EventBus-Sync

* Toolbar-Aktionen auf die bestehenden Set-Methoden gekoppelt: `[➕]` → Popup → `add_instance()`, `[▲]/[▼]` → `move_order_item(±1)`, `[🗑️]` → `remove_instance()` (P14-04-Sperrprüfung), `[🔄]` → `reload_plugins()`.
* MasterTree-Auswahl synchronisiert Set-Combo, Instanz-Liste und `ParameterPanel` (bidirektional, Live-Edit fließt in `collect_set_definition()`).
* **EventBus-Sync:** `service_set_changed` wird bei jeder Struktur-/Parameter-Änderung emittiert:
  * `set_item_adapter.py`: nach `_item_save_as()` (speichern) und `_item_delete_current()` (löschen).
  * `trash_dialog.py`: nach `restore_set_from_trash()` (wiederherstellen).
  * `service_win.py`: nach `add_instance()`, `move_order_item()`, `remove_instance()`.

### 3.6 Schritt 6 – Headless-Test

**`test/check_p15_s2_service_tree.py` (NEU, Test-DB in `test/`):** Prüft ServiceSelectorModel (Grunddaten, Hierarchie, Standalone-Abgrenzung, Live-Status „Aktiv im Chart" via StateManager, EventBus-Reaktivität), ServiceSelectorWidget Modus `SELECT_ONLY` (Combos + `selection_changed`) und Modus `FULL_EDIT` (MasterTree-Gruppen, Badge-Spalte, `current_selection()`) sowie Set-Updates/Umsortieren.

**Ergebnis: 31/31 Checks PASS** (Exit 0). Zusätzlich verifiziert:
* `check_p13_service_win_geometry.py`: ServiceWindow konstruiert mit neuem QSplitter-Aufbau; alle 5.4-Dynamik-Checks (Spalten, Expert-Aufklappen, Scroll-Range, add_instance) bestehen. **Einzige verbleibende Meldung:** vorbestehend aus 15.01 (`setFixedWidth(32)` des ★-Favoriten-Buttons), nicht durch 15.02 verursacht.
* `python -m py_compile` auf allen neuen/geänderten Dateien (Exit 0).

### 3.7 Schritt 7 – Bugfixing: Access-Violation-Schutz & Geometrie-Persistenz (Commit `7ac0581`)

**Fehler 0 – App-Crash bei wildem Klicken auf Services (Exit-Code `0xC0000005`, Access Violation):**
Ursache: `data_changed`/`setCurrentItem`-Klick löst `_populate()` → `clear()` aus; `currentItem()` zeigte auf ein bereits C++-seitig zerstörtes `QTreeWidgetItem` → `.data()`-Zugriff crasht hart. Zusätzlich: `clear()` im `ParameterPanel` stieß beim `TypeError` (`'QWidgetItem' object is not callable`) auf ein Absturz-Kandidat-Problem.

Fixes (4 Dateien):
* **`scrollable_content.py`:** `resize_to_clamped_content()` – **Persistenz-Fix**, Fenster wird nie unter die aktuelle (User-/wiederhergestellte) Größe geschrumpft, nur vergrößert (bis Bildschirm). `_apply_reflow_size()` – try/except gegen Feuern nach Fenster-Schließen.
* **`serviceui/master_tree.py`:** `shiboken6.isValid()`-Guards (Fallback-Def) in `_safe_current_selection()`/`current_selection()`/`_emit_selection()`/`_restore_selection()` (setCurrentItem unter `blockSignals` + try/finally) und im `TreeItemIterator` (Init/`_collect`/`__next__`).
* **`serviceui/parameter_panel.py`:** `clear()` entfernt Form-Zeilen-Widgets jetzt explizit (`takeRow` → `fieldItem`/`labelItem` als **Attribute** der `TakeRowResult` – nicht Methoden –, `setParent(None)` + `deleteLater()`), Experten-Gruppe inklusive. `_emit_params_changed()`/`_reflow()` mit try/except.
* **`serviceui/service_win.py`:** `_qt_valid`-Import; isValid-Guards in `_on_master_selection()`, `_sync_param_panel()`, `_on_param_panel_changed()`; try/except in `_set_ctrl_value()`.

**Fehler 1 – Letzte Fensterposition/-größe wurde nicht persistiert:**
Ursache: `resize_to_clamped_content()` (ContentScrollMixin) schrumpfte nach `restore_state()` das Fenster wieder auf Inhalt/Screen-Größe → `save_state()` speicherte falsche Geometrie. Fix: Nur-wachsen-Logik (siehe oben).

**Validierung (`test/test.py`, offscreen, Test-DBs in `test/`):**
* Teil 1 Persistenz (P1–P5): Position wiederhergestellt (150,120), Höhe nicht unter 400 geschrumpft, User-Höhe 450 bleibt erhalten, `save_state()` speichert User-Position/-Höhe → **alle PASS**.
* Teil 2 Klick-Sturm (K1/K2): 40 schnelle Service-Klicks (`setCurrentItem` + `_on_master_selection`) ohne Absturz, Fenster bleibt lebendig → **alle PASS**.
* `python -m py_compile` auf allen geänderten Dateien (Exit 0).

**Hinweis Test-Artefakt:** Der frühere K2-Fail lag nicht an der App, sondern am `pump()`-Helper: `QApplication.quit()` setzt den Quit-Flag und versteckt auf der offscreen-Plattform alle Top-Level-Fenster (`isVisible() → False`). Fix im Test: `QEventLoop`-Muster statt `QApplication.quit()`.

### 3.8 Schritt 8 – Bugfixing: Fenster-Historie (Service/Analytics) & Chart-Circles

**Fehler A – ServiceWindow wurde nicht aus der Fenster-Historie wiederhergestellt & letzte Position nicht gespeichert:**
Ursache: `serviceui/service_win.py` war mit `@register_persistent_window(auto_restore=False)` registriert → `restore_all_windows()` (main.py) übersprang es beim App-Start. Zusätzlich war `_keep_history_on_close` nicht gesetzt (Default `False`) → `PersistentWindow.closeEvent()` rief nach `save_state()` sofort `delete_instance()` → die Geometrie wurde gespeichert und wieder gelöscht („letzte Position wird nicht saved/restored").

Fix (Runde 2): `@register_persistent_window()` (auto_restore=True) – das Fenster wird beim App-Start wiederhergestellt, wenn es beim Beenden offen war.

**Fehler B – Im Chart werden keine Proximity-Circles mehr angezeigt:**
Ursache: Seit U15-A3 (Commit `2e3d8d4`, „Pipeline-Fallback entfernt") kamen die Circles ausschließlich aus dem feature_store (`feature_id='proximity'`). Der Store ist aber leer, solange keine aktiven Batch-Presets (`is_active_batch=True`) existieren → LiveAnalyzer/HistoricalScanner schreiben keine Proximity-Payloads → `read_proximity_from_feature_store()` liefert `[]` → keine Circles. Der Chart berechnete die Circles in seiner internen Service-Pipeline zwar, verwarf sie aber ungenutzt.

Fix (Runde 2) in `chart/indicators/grid_liquidity.py` (`calculate()`): PRIMÄR feature_store lesen (U15-A3-Lesepfad bleibt); ist der Store leer, greift der definierte Fallback auf die pipeline-berechneten `hit_circles` des Proximity-Service (`prox_crp.hit_circles`, Parität zu U15-A2). Beide Pfade nutzen dieselbe `_colorize()`-Farb-Logik (in_window + use_time_filter → `circle_color_std`, sonst `circle_color_active`); `show_circles=False` wird in beiden Pfaden respektiert.

**Fehler C – Analytics- & ServiceWindow poppten trotz manuellem Schliessen beim Neustart wieder auf:**
Ursache: Durch den Runde-2-Fix (und den vorbestehenden 15.03-Fix bei AnalyticsWindow) war `_keep_history_on_close = True` gesetzt → manuell geschlossene Fenster blieben in `window_instances`/`instance_states` → `restore_all_windows()` stellte sie wieder her.

Fix (Runde 3) – **History-Semantik wie `chart_win`**:
* `serviceui/service_win.py`: `_keep_history_on_close = True` entfernt (Default `False`); `@register_persistent_window()` (auto_restore=True) bleibt.
* `analytics/ui/analytics_win.py`: `_keep_history_on_close = True` entfernt (Default `False`); `@register_persistent_window()` (auto_restore=True) bleibt.

Ergebnis-Semantik (identisch zu `chart_win`):
| Szenario | Ergebnis |
| --- | --- |
| Fenster offen, App beendet | `save_state()` im App-CloseEvent → Eintrag bleibt → **Restore beim Start** (Position/Größe) |
| Fenster manuell geschlossen, dann App beendet | `closeEvent` → `delete_instance()` → **kein Auto-Restore beim Start** |

**Validierung (`test/test.py`, offscreen, vollständig auf Temp-DBs isoliert – läuft auch bei offener App, DuckDB-Single-Writer):**
* Teil 1 Persistenz (P1–P5), Teil 2 Klick-Sturm (K1/K2) → alle PASS (Regressions-Schutz aus Schritt 7).
* Teil 3 Fenster-Historie (H1–H9): auto_restore aktiv; `_keep_history_on_close` ist False; nach `close()` sind Geometrie- UND Instanz-Eintrag entfernt (kein Auto-Restore); Neustart-Simulation für offene Fenster stellt (333,222)/600 wieder her; AnalyticsWindow identisch.
* Teil 4 Chart-Circles (C1–C5): feature_store leer → Pipeline-Fallback liefert 600 `hit_circles` mit Farbe + time/price; `show_circles=False` → keine Circles.
* `python -m py_compile` auf allen geänderten Dateien (Exit 0).

**Hinweis Test-Isolation:** Der Test patcht die `__init__`-Methoden von `ServiceSetRepository`/`StateManager` direkt (Modul-Patches würden durch In-Funktion-Imports überschrieben) und leitet `get_symbol_repository()` auf eine Temp-DB um – so läuft er unabhängig von der geöffneten App (die echten `data/*.duckdb`-Dateien sind durch deren Prozess gesperrt).

### 3.9 Schritt 9 – MasterTree-Layout-Bugfixes (5 Punkte) & Alt-Plugin `grid_liquidity` entfernt (04.08.2026)

**A) MasterTree – 5 Layout-/Bedien-Bugfixes (`serviceui/master_tree.py`):**
1. **Ebene 0 startet ganz links an der Linie der umschließenden Box:** `rootIsDecorated=False` + KEINE Icons/Spacer auf Top-Level-Knoten; die Einrückung der Untereinträge kommt ausschließlich aus `setIndentation(LEVEL_INDENT)` (20 px je Ebene). Vorher schob ein Spacer-Icon alle Zeilen nach rechts.
2. **Eingeklappt → `> ` vor dem Namen** (Knoten mit Kindern, noch nicht aufgeklappt).
3. **Ausgeklappt → `⌄ ` vor dem Namen** (Knoten mit Kindern, aufgeklappt). Das Symbol folgt dem IST-Zustand via `itemExpanded`/`itemCollapsed` → `_refresh_expand_label` (unter `blockSignals` explizit für Top-Level nach `_populate()`). `drawBranches` bleibt als bewusst leerer Override (keine nativen Branch-Dreiecke).
4. **Einfacher Mausklick togglet auf/zu:** `mousePressEvent` klappt bei Klick auf die GESAMTE Zeile eines Knotens mit Kindern um (zusätzlich Selektion bei selektierbaren Knoten); `setExpandsOnDoubleClick(False)` – Doppelklick togglet nicht mehr.
5. **Info-Symbol in der Status-Spalte ist ASCII `'i'`:** `BADGE_TRUNCATE_ICON = "i"` statt Unicode `🛈` (U+1F6C8) – das Emoji rendert in den Qt-Fonts unter Windows nicht zuverlässig (tofu-Box). Lange Badges (> `MAX_BADGE_CELL_CHARS` = 24) werden auf `'i'` gekürzt; der Indikator-Name steht im Tooltip der Spalte 1.

**B) Badge-Konvention auf echten Indikator-Namen umgestellt (`indicator_name`):**
* `analytics/engine/service_selector_model.py`: `badge_for()` liefert `📌 im <Indikator> | 🟢 aktiv in <Indikator>` bzw. `⚪ inaktiv in <Indikator>`; `get_indicator_display_name()` bevorzugt `metadata['indicator_name']` (z. B. `GridLiquidityIndicator`), Fallback `display_name`/`plugin_id`.
* `analytics/features/definitions/grid_lines_service.py` & `proximity_service.py`: Metadaten-Feld `indicator_name: "GridLiquidityIndicator"` ergänzt.
* `serviceui/master_tree.py` `_apply_badge()`: Tooltip der Status-Spalte unterscheidet `aktiv <Indikator>` (aktuell im Chart aktiv) vs. `im <Indikator>` (nur Abhängigkeit).

**C) Alt-Plugin `analytics/features/definitions/grid_liquidity.py` entfernt (archiviert):**
* `chart/indicators/grid_liquidity.py` ist jetzt vollständig self-contained: `_GRID_LIQUIDITY_SCHEMA`/`_GRID_LIQUIDITY_ORDER`, Properties `plugin_id`/`parameter_schema`/`parameter_order`/`base_parameter_schema`/`full_parameter_schema()`, statisches `default_params` – kein `PluginRegistry`-Import mehr.
* `indicator_dialog._get_plugin()` nutzt für `grid_liquidity` Branch 1 (Indikator ist das Plugin) – alle `self.plugin.*`-Zugriffe bleiben kompatibel.
* Produktions-Aufrufer sind robust gegen fehlende Plugins (KeyError-Handling): `service_set_repository`, `live_analyzer`, `service_win`, `parameter_panel`, `param_columns`, `indicator_dialog`.
* **Migration angewendet** (`python test/migrate_grid_liquidity.py --apply`): keine Alt-Referenzen in `service_sets`/`service_sets_trash`/`service_set_history`/`indicator_presets`/`feature_store`.
* **Archivierung:** `analytics/features/definitions/grid_liquidity.py` → `.backup_grid_liquidity/analytics/features/definitions/grid_liquidity.py` (aus dem Discovery-Pfad entfernt; Original bleibt erhalten). Ordner `.backup_*/` ist jetzt in `.gitignore`.
* `PluginRegistry` findet final nur noch `grid_lines` + `proximity`; `get('grid_liquidity')` wirft `KeyError` (erwartet). `test/check_phase14_regression.py` P14-02a-Schwelle `>= 3` → `>= 2`.

**Validierung (alle headless, grün):**
* `test/check_p15_s2_service_tree.py`: F5 → `'i'`-Badge, F5c/F5d → `⌄` (expandiert) / `>` (zugeklappt), F5e Blatt ohne Symbol, F5f–F5j Layout, G1/G2 – **alle PASS**.
* `test/test.py`: T9a (zustandsabhängiger Marker), T9b/T10 (Einfach-Klick-Toggle), T11 (kein Icon), T4/T5 (`'i'`-Badge) – **alle PASS**.
* `test/check_phase14_regression.py` (P14-02d: `grid_liquidity` NICHT mehr registriert), `test/check_plugin_batch_services.py`, `test/check_plugin_executor.py`, `test/check_p14_s2_discovery.py`, `test/check_grid_parity.py`, `test/check_p13_s1.py` – **alle PASS**.
* `python -m py_compile` auf allen geänderten Dateien (Exit 0); Import-Smoke-Test der Produktionsmodule (Chart, Service-UI, Dialoge, Repository) erfolgreich.

### 3.10 Schritt 10 – Restarbeiten: Service-`grid_liquidity`-Altlasten & verwaiste `grid`-Keys aus DBs entfernt (05.08.2026)

**A) Verifikation: Service `grid_liquidity` gehört zum ausgemusterten Alt-Indikator:**
* `analytics/features/definitions/grid_liquidity.py` ist seit Schritt 9 archiviert (`.backup_grid_liquidity/`, aus dem Discovery-Pfad entfernt). `PluginRegistry` findet final nur noch `grid_lines` + `proximity` → der Service erscheint **nicht mehr im ServiceTree**; `get('grid_liquidity')` wirft `KeyError` (erwartet).
* **Fehlende Restarbeiten identifiziert:** Die in Schritt 9 dokumentierte Migration (`test/migrate_grid_liquidity.py`) hatte die PERSISTIERTEN falschen Relationen in `app_data.duckdb` nur teilweise abgedeckt. Kategorisierung per DB-Scan (`test/_probe_*`, temporär):
  1. **`indicator_presets`:** Alt-Preset `('grid_liquidity', 'SILVER:M1 Test')` mit ALTER Service-Plugin-Struktur (`logic_params`/`display_params`/`set_id`) – kein gültiges Preset des neuen self-contained Indikators (der speichert flache Schema-Params).
  2. **`symbol_tf_states` (7) + `instance_states` (1):** `grid_liquidity`-Sub-States mit alter Struktur (`preset='SILVER:M1 Test'`, `set_id` aus dem gelöschten Alt-Preset) – würden den neuen Indikator mit unverständlichen Parametern restaurieren.
  3. **`symbol_tf_states` (11) + `instance_states` (1):** verwaiste `indicators_state`-Keys `'grid'` des am 04.08.2026 entfernten Alt-Indikators `chart/indicators/grid.py` (alle `active=false`; `chart_win.py` popt den Key zur Laufzeit bereits per U15-B4 – DB-Bereinigung ist reine Hygiene).

**B) Bereinigung (`python test/migrate_grid_liquidity.py --apply`, headless):**
* `indicator_presets`: Alt-Preset `'SILVER:M1 Test'` **gelöscht** (falsche Relation zum neuen Plugin-Grid-Indikator).
* `symbol_tf_states` / `instance_states`: **7+1 falsche `grid_liquidity`-Relationen** (alte Struktur) und **11+1 verwaiste `grid`-Keys** aus den `indicators_state`-JSONs **entfernt**.
* **`test/migrate_grid_liquidity.py` erweitert** (bleibt erhalten, `test/` gitignored):
  * Abschnitt 3b: Alt-Presets mit `indicator_id='grid_liquidity'` UND alter Service-Plugin-Struktur werden erkannt und gelöscht; gültige flache Presets bleiben unangetastet.
  * Abschnitt 5: falsche `grid_liquidity`-Relationen (alte Struktur) in `instance_states`/`symbol_tf_states` werden aus dem JSON entfernt.
  * Abschnitt 6: verwaiste `'grid'`-Keys (U15-B4) werden aus dem JSON entfernt.
  * Dry-Run/`--apply`-Logik & Exit-Code konsistent (0 = keine Alt-Referenzen mehr).
* **Kommentar-Polish** (nur Doku, keine Logik): Beispiel `(z.B. 'grid_liquidity')` → `(z.B. 'grid_lines')` in `db_service.py`, `state_manager.py`, `analytics/features/plugins/base_plugin.py`.
* **Stale Bytecode entfernt:** `analytics/features/definitions/__pycache__/grid_liquidity.cpython-314.pyc`, `chart/indicators/__pycache__/grid.cpython-314.pyc`.

**Validierung (alle headless, grün):**
* `python test/migrate_grid_liquidity.py` (Dry-Run): **exit 0** – Abschnitte 1–6 melden keine Alt-Referenzen mehr (vor Apply: 9 falsche Relationen + 12 verwaiste `grid`-Keys gefunden; nach Apply: 0).
* `PluginRegistry`-Smoke: `sorted(plugins.keys()) == ['grid_lines', 'proximity']`; `GridLiquidityIndicator.service_plugin_ids == ['grid_lines', 'proximity']`.
* DB-Bestandskontrolle: keine `feature_id='grid_liquidity'` in `feature_store`; `service_sets`/`trash`/`history` ohne `grid_liquidity`-Referenzen; keine verwaisten `grid`-Keys in `symbol_tf_states`/`instance_states`.
* `python -m py_compile` auf allen geänderten Dateien (Exit 0).

### 3.11 Schritt 11 – Bugfix: MasterTree-Tooltip-Aktiv-Logik & Set-Badge (05.08.2026)

**Bug 1 – Tooltip zeigte `'im <Indikator>'` auch für aktiv im Chart laufende Services:**
Ursache: `_apply_badge()` prüfte `is_active_in_chart(plugin_id)` ausschließlich gegen die Plugin-ID (`grid_lines`/`proximity`). Aktiv im Chart sind aber die `indicators_state`-Keys des INDIKATORS (`grid_liquidity`), nicht die Plugin-ID – dadurch griff die Tooltip-Variante a) (`aktiv <Indikator>`) für Services nie.

Fixes (4 Dateien):
* **`analytics/engine/service_selector_model.py`:** Neue Lese-Methoden `get_indicator_id()` (metadata-Fallback `plugin_id`), `belongs_to_indicator()`, `get_set_indicator_names()`, `is_set_active()`; `is_active_in_chart()` prüft zusätzlich den zugehörigen Indikator (metadata `indicator_id`) – dadurch ist ein Service auch dann „aktiv im Chart", wenn sein Indikator (z. B. `GridLiquidityIndicator`) läuft.
* **`analytics/features/definitions/grid_lines_service.py` & `proximity_service.py`:** Metadaten-Feld `indicator_id: "grid_liquidity"` ergänzt (bereits vorhandenes `indicator_name` bleibt).
* **`serviceui/master_tree.py` `_apply_badge()`:** ODER-Logik „aktiv \<Indikator\>" / „im \<Indikator\>" auf Indikator-Basis; Tooltip wird auf Spalte 0 UND Spalte 1 gesetzt.

**Bug 2 – Service-Sets mit Indikator-Zugehörigkeit zeigten kein Status-Symbol:**
Fix: Neue `_apply_set_badge()` – Set-Knoten mit Indikator-Zugehörigkeit zeigen in Spalte 1 das Info-Zeichen (`'i'`) mit derselben Tooltip-Namenslogik wie Services; mehrere Indikatoren werden mit `' + '` verknüpft.

**Validierung (`test/check_p15_s2_service_tree.py`, erweitert C5–C9/F5k/F5l, headless):** 49/49 Checks PASS – inkl. Aktiv-Prüfung via Indikator-ID (`grid_liquidity`), `belongs_to_indicator`, Set-Indikator-Namen und Set-Aktiv-Status.

### 3.12 Schritt 12 – Info-Button im MasterTree statt Box-Button (05.08.2026)

**Anforderung (5 Punkte, vom Anwender entschieden):** `btn_info_service` aus der Box „Service-Sets (Phase 13)" entfernen; stattdessen pro Zeile im MasterTree (Spalte 1) ein echter Info-Button `"ℹ"` auf Icon-Breite; Status-Spalte auf Button-Breite verkleinert und weiterhin ganz rechts (Spalte 0 = Stretch); Klick öffnet den Beschreibungs-Dialog mit **erster Zeile = bisheriger Tooltip-Text** (`aktiv/im <Indikator>`), dann Leerzeile, dann Beschreibungstext. Button auf ALLEN Service-/Plugin-/Set-Zeilen; **gelbe Färbung** (`#FFD700`) bei Indikator-Relation, sonst neutral; **Badge-Text entfällt** aus Spalte 1, Tooltip bleibt unverändert.

**Umsetzung (6 Dateien):**
* **`serviceui/master_tree.py`:** Neues Signal `info_requested(set_id, service_id, plugin_id)`; `_attach_item_buttons()` hängt nach jedem `_populate()` einen kompakten `QPushButton("ℹ")` (20×20, `border:none`, gelb `#FFD700` bei vorhandenem Indikator-Tooltip, sonst neutral `#666666`) an alle Service-/Set-/Plugin-Zeilen (Gruppen bewusst ohne Button). `_apply_badge()`/`_apply_set_badge()` setzen KEINEN Badge-Text mehr (Zelle leer); Tooltip-Logik unverändert. Spalte 1 `Fixed` + `resizeSection(1, INFO_BUTTON_WIDTH=24)` (vorher `BADGE_COLUMN_WIDTH=36`, bleibt als Test-Referenz). Neue Konstanten `INFO_BUTTON_TEXT/SIZE/WIDTH/COLOR_*`.
* **`serviceui/service_selector_widget.py`:** `info_requested` des MasterTree wird re-emittiert (neues Widget-Signal).
* **`serviceui/service_win.py`:** Neuer Slot `_on_tree_info_requested(set_id, service_id, plugin_id)` (Verdrahtung in `_wire_selector_toolbar()`); Helfer `_resolve_info_plugin()`/`_info_header_tooltip()`/`_info_set_tooltip()`. Öffnet je Zeilentyp: Service → `from_plugin(Instanz+Config)`, Plugin → `from_plugin()`, Set → `from_set()`. Alter `_show_service_info()` bleibt erhalten (Guard über `btn_info_service` ist nach UI-Entfernung `None` → kein Crash).
* **`analytics/engine/description_dialog.py`:** Neuer `header_line`-Parameter (fette erste Zeile + Leerzeile vor dem Beschreibungstext) in `__init__`/`_render_html`/`from_plugin`; neue Klassenmethode `from_set()` (Set-Name, Set-Beschreibung, Service-Liste in `execution_order`).
* **`ui/service_win.ui`:** `btn_info_service`-Block („ℹ Info" + Tooltip) aus `layout_order_buttons` entfernt.

**Validierung (headless, grün):**
* `test/check_p15_s2_service_tree.py`: F5–F5s auf Button-Präsenz umgestellt (nur-Icon/Icon-Breite, Tooltip unverändert, Set-Button, Button auf ALLEN Zeilen, gelb bei Indikator-Relation + neutral bei injiziertem Plain-Plugin, Spalte auf `INFO_BUTTON_WIDTH`, `info_requested`-Emission für Service/Set/Plugin); neu H1–H4 (`from_set`/`from_plugin` rendern `header_line`) – **alle PASS** (3× stabil).
* `test/test.py`: T4/T5 auf Info-Button-Checks umgestellt, T8b (Spaltenbreite) + T12 (`info_requested` Set-Zeile) neu; **Flakiness-Fix T9b/T10**: manuelle `QMouseEvent`-Synthetic-Clicks sind auf dem offscreen-Platform-Fenster timing-flaky (nachgewiesen: `itemAt`/`setExpanded` korrekt, `mousePressEvent` byte-identisch zu HEAD → vorbestehend) → Umstellung auf `QTest.mouseClick` → **5/5 Läufe stabil**.
* `python -m py_compile` auf allen geänderten Dateien (Exit 0); UI-XML parst fehlerfrei.

### 3.13 Schritt 13 – U15-D2: Toolbar-Refactoring & MasterTree-Kontextmenü (05.08.2026)

**Anforderung (3 Punkte, vom Anwender entschieden – Punkt 3 „grid_lines-Alt-Rumpf-Bereinigung" wurde abgewählt, da `analytics/features/definitions/grid_lines_service.py` der AKTIVE Service ist; obsolet war nur das bereits in Schritt 9/10 archivierte `grid_liquidity.py`):**

**A) Toolbar-Refactoring (`serviceui/toolbar.py`):**
* Plugins-Button `btn_reload` und Signal `reload_plugins_requested` **entfernt** – der Hot-Reload bleibt über den UI-Button `btn_reload_plugins` (`service_win.ui`) erreichbar.
* Order-Buttons heißen jetzt `Order ▲` / `Order ▼` (statt `▲`/`▼`) und sind ohne Service-in-Set-Auswahl deaktiviert (`set_order_enabled(bool)`).
* Bifunktionaler `btn_add`: `[➕ Set]` (neues leeres Set anlegen, `add_set_requested`), `[➕ Service]` (Plugin-Popup, `request_add_popup`), `[➕]` deaktiviert – gesteuert über `set_add_mode("set"/"service"/"none")`.
* Bifunktionaler `btn_remove`: `[🗑️ Set löschen]` (Papierkorb, P14-05), `[➖ Service entfernen]` (P14-04-Sperrprüfung), `[🗑️]` deaktiviert – gesteuert über `set_remove_mode("set"/"service"/"none")`.
* `set_actions_enabled()` ist durch die Modus-Methoden ersetzt; neues Signal `add_set_requested = Signal()`.

**B) MasterTree-Kontextmenü (`serviceui/master_tree.py`, strikt entkoppelt):**
* `CustomContextMenu` + `_show_context_menu(pos)`: dynamisch je Knotentyp, Aktionen emittieren AUSSCHLIESSLICH Signale (kein ServiceWindow-Import in der UI-Klasse, IoC):
  * Gruppe 📁 (sets) → `create_set_requested` ('Neues Set anlegen').
  * Set-Knoten → `rename_set_requested(set_id)`, `add_set_service_requested(set_id)`, `delete_set_requested(set_id)`.
  * Service-Knoten → `move_service_requested(set_id, service_id, delta)` (Order ▲/-1, ▼/+1), `remove_service_requested(set_id, service_id)`, 'Service-Info anzeigen' über das bestehende `info_requested`.
  * Außerhalb eines Sets (Plugin-Zeilen, ⚡-/📦-Gruppen): Order/Entfernen/Umbenennen ausgegraut (`_add_outside_set_actions`, `setEnabled(False)`); 'Service-Info anzeigen' bleibt bei Plugin-Zeilen aktiv.
* Neues Signal `group_activated(group)`: wird im `mousePressEvent` bei Klick auf einen (nicht selektierbaren) Gruppen-Knoten emittiert – die Toolbar braucht es, weil Gruppen-Knoten kein `selection_changed` feuern (kein `ItemIsSelectable`-Flag).

**C) `serviceui/service_win.py` (Orchestrator):**
* `QInputDialog` importiert (für den Namensdialog beim Umbenennen).
* `_wire_selector_toolbar()` neu verdrahtet: `reload_plugins_requested`-Referenz entfernt; `add_set_requested` + alle 7 Kontextmenü-Signale auf neue Handler gelegt (DRY: Toolbar- und Kontextmenü-Aktionen teilen dieselben Handler).
* `_on_master_selection` ruft jetzt `_update_toolbar_actions(set_id, service_id)` auf (bifunktionaler Toolbar-Zustand nach jeder Baum-Auswahl).
* Neue Handler (`_current_tree_selection`, `_update_toolbar_actions`, `_on_group_activated`, `_on_toolbar_remove`, `_on_add_set`, `_on_rename_set`, `_on_add_set_service`, `_on_delete_set`, `_select_service_in_editor`, `_on_move_service`, `_on_remove_service`):
  * `_on_add_set`/`_on_rename_set` laufen bewusst DIREKT über `set_repo.save_set()` – der `NamedItemAdapter._item_save_as()` verweigert leere `execution_order`, leere Sets wären sonst weder anleg- noch umbenennbar.
  * `_on_delete_set` lädt das Set in den Editor und ruft das bestehende `delete_set()` auf (P14-04-E-Sperre 'letztes Set' + Papierkorb-Rückfrage greifen dort zentral).
  * `_on_move_service`/`_on_remove_service` selektieren die Instanz im Editor (`_select_service_in_editor`) und reusen `move_order_item(delta)` bzw. `remove_instance()` (inkl. P14-04-Sperrprüfung).

**Validierung (headless, grün):**
* `python -m py_compile` auf `serviceui/toolbar.py`, `serviceui/master_tree.py`, `serviceui/service_win.py` (Exit 0).
* Import-Smoke: `MasterTree`/`ServiceToolbar`/`ServiceWindow` mit allen neuen Signalen & Methoden vorhanden; `btn_reload`/`reload_plugins_requested`/`set_actions_enabled` vollständig entfernt (keine Rest-Referenzen im Produktionscode; `reload_plugins_requested` nur noch als Doku-Kommentar).
* Projektweite Suche: keine Test-Abhängigkeiten auf das entfernte Toolbar-API.
### 3.14 Schritt 14 - Bugfix Runde 3: Rechtsklick-Toggle, Papierkorb-Kontextmenue & ParameterPanel entfernt (05.08.2026)

**Anforderung (4 Punkte, vom Anwender entschieden):**

**A) Rechtsklick expandiert/kollabiert Knoten (serviceui/master_tree.py):**
* _show_context_menu() togglet vor dem Menueaufbau bei Knoten mit Kindern (childCount() > 0) item.setExpanded(not item.isExpanded()) - Konsistenz mit dem Linksklick (Schritt 9, Punkt 4), damit das Kontextmenue immer auf dem sichtbaren Knoten steht (isValid-Guard bleibt).

**B) Loeschen in den Papierkorb (bereits vorhanden, keine Aenderung):**
* delete_set() → ServiceSetRepository.delete_set(soft_delete=True) verschiebt das Set nach service_sets_trash; ServiceSetTrashDialog (tn_trash_sets) bietet Wiederherstellen + endgueltiges Loeschen (P14-05).

**C) Kontextmenue \'Papierkorb loeschen...\' mit doppelter Sicherheitsabfrage (2 Dateien):**
* serviceui/master_tree.py: Neues Signal purge_trash_requested = Signal(); Menueeintrag \'Papierkorb loeschen...\' bei Set- UND Service-Knoten (alle Lambdas mit _=False, Shiboken-bool-Schutz).
* serviceui/service_win.py: Neuer Slot _on_purge_trash() - leere-Pruefung ueber set_repo.list_trash(), dann DOPPELTE QMessageBox.question-Abfrage (P14-05, Vorgang nicht umkehrbar), set_repo.purge_trash() + event_bus.service_set_changed.emit(); verdrahtet via 	ree.purge_trash_requested.connect(self._on_purge_trash) in _wire_selector_toolbar().

**D) ParameterPanel komplett entfernt (Code + Relationen, 3 Aenderungen):**
* serviceui/service_win.py (Patch via 	est/_apply_fix_round3_sw.py): ParameterPanel-Import, param_panel-Erzeugung/Layout (right_layout), _on_symbol_changed-Block, params_changed-Verdrahtung, _sync_param_panel()-Aufrufe in _on_master_selection/_clear_set_editor/load_set_into_editor/_sync_list_selection sowie die Methoden _sync_param_panel/_on_param_panel_changed/_set_ctrl_value KOMPLETT entfernt. Wichtig: Das End-Slice der Methoden-Entfernung zeigt auf die U15-D2-Sektion (Toolbar-Zustand & Kontextmenue-Handler) - die Handler _on_remove_service & Co. liegen NACH diesem Marker und bleiben erhalten (erster Versuch mit der 15.01-Sektion als End-Slice entfernte faelschlich _on_remove_service). Zusaetzlich 2 veraltete Kommentar-/Docstring-Erwaehungen bereinigt.
* serviceui/__init__.py: ParameterPanel-Import, __all__-Export und Dokuzeile entfernt (
ew_set_dialog.py in der Doku ergaenzt).
* serviceui/parameter_panel.py → .backup_parameter_panel/serviceui/parameter_panel.py archiviert (Konvention wie .backup_grid_liquidity, aus dem Discovery-Pfad entfernt; Original bleibt erhalten).
* **Keine DB-Tabelle:** ParameterPanel ist reine UI - nichts in DuckDB zu loeschen.

**Validierung (headless, gruen):**
* python -m py_compile auf service_win.py, master_tree.py, __init__.py, service_selector_widget.py, 
ew_set_dialog.py, param_columns.py, 	rash_dialog.py (Exit 0).
* Import-Smoke: serviceui, service_win, master_tree (Signal purge_trash_requested vorhanden), selector/widget/dialog/toolbar/status - OK; ParameterPanel nicht mehr in __all__.
* Projektweite Rest-Referenz-Suche (ParameterPanel|param_panel|_sync_param_panel|_on_param_panel_changed|_set_ctrl_value im Produktionscode): **0 Treffer**.
* Verifikation _on_purge_trash: set_repo.list_trash()/purge_trash() und event_bus vorhanden; Kontextmenue-Toggle (count 2), Papierkorb-Eintraege (count 2, Set- + Service-Knoten) bestaetigt.

### 3.15 Schritt 15 – MasterTree-Ausführungsdatum & Kontextmenü-Ausführung (05.08.2026)

**Anforderung (3 Punkte, vom Anwender entschieden):** Alle CRUD-/Steuer-Buttons oberhalb des MasterTrees entfernen (UI + Event-Verbindungen) → MasterTree hat die volle vertikale Höhe der linken Spalte. Ausführungsdatum hinter dem Service-Namen (`Service_Name (DD.MM.JJ)`, z.B. `prox_1 (05.08.26)`), gelesen aus `analytics.duckdb`/`feature_store` (`MAX(created_at)` je `feature_id`), Fallback `(--.--.--)`. Kontextmenü-Run-Aktionen (`[▶️ Diesen Service ausführen]` bei Service-Knoten, `[▶️ Alle Services ausführen]` bei Set-Knoten) mit `QMessageBox.question`-Bestätigung (Set/Service + aktuelles Symbol/Timeframe) – **kein globaler Massen-Scan** (HistoricalScanner bewusst vermieden), sondern gezielter Run des selektierten `instance_id`/Sets für das aktive Symbol/Timeframe in einem QThread (OHLCV → `PluginExecutor`-Pipeline → `store_plugin_payload` → `event_bus.service_set_changed.emit()` → Modell-Refresh → Datum live im Baum ohne Neustart). Tree-Label ohne `[plugin_id]` (entspricht exakt dem Aufgaben-Beispiel). Single-Run inkl. Upstream-Abhängigkeiten (frühere Services der `execution_order`, damit `proximity` seine Linien aus `grid_1` via `depends_on` erhält).

**A) CRUD-Buttons entfernt (3 Dateien):**
* `serviceui/service_selector_widget.py`: Toolbar-Import entfernt; `_build_full_edit()` baut nur noch den MasterTree (`self.toolbar = None` bleibt als Attribut für Abwärtskompatibilität); MasterTree füllt die gesamte Höhe der linken Spalte.
* `serviceui/service_win.py`: `_wire_selector_toolbar()` neu – ohne Toolbar-Verdrahtung (nur noch `selection_changed`, `info_requested`, 7 Kontextmenü-Signale + die 2 neuen Run-Signale); `_show_toolbar_add_popup()`, `_update_toolbar_actions()`, `_on_group_activated()`, `_on_toolbar_remove()`, `_current_tree_selection()` entfernt; `_on_master_selection`-Toolbar-Call entfernt. `group_activated` bleibt als Signal im MasterTree erhalten (potenzielle Aufrufer, keine Toolbar-Verwendung mehr).

**B) Ausführungsdatum (4 Dateien):**
* `analytics/engine/feature_store_reader.py`: Neue rein lesende Methode `fetch_last_execution_dates() -> Dict[str, str]` – `SELECT feature_id, MAX(created_at) FROM feature_store GROUP BY feature_id`, formatiert `DD.MM.JJ`, defensiv (Fehler → leer).
* `analytics/features/feature_builder.py`: `store_plugin_payload()` setzt bei `ON CONFLICT DO UPDATE` zusätzlich `created_at = current_timestamp` – der Zeitstempel spiegelt die LETZTE Ausführung (nicht den Erst-Schreibzeitpunkt).
* `analytics/engine/service_selector_model.py`: Neuer Parameter `feature_store_reader` (Default echte Instanz); `refresh()` liest zusätzlich `_last_execution_dates`; `last_execution_date(plugin_id)` → `DD.MM.JJ` / `(--.--.--)` (case-insensitiv); `build_tree()` liefert je Service `"last_execution"`.
* `serviceui/master_tree.py`: `_build_set_item` – Service-Label `f"{instance_id} ({last_exec})"` (ohne `[plugin_id]`).

**C) Kontextmenü-Ausführung (2 Dateien + NEU `serviceui/run_worker.py`):**
* `serviceui/master_tree.py`: Neue Signale `run_service_requested = Signal(str, str)` (set_id, instance_id) und `run_set_requested = Signal(str)` (set_id); Kontextmenü: Set-Knoten `'▶️ Alle Services ausführen'` (erste Aktion), Service-Knoten `'▶️ Diesen Service ausführen'` (erste Aktion); beide strikt entkoppelt (Lambda-Emits, `_=False`-Guard).
* **`serviceui/run_worker.py` (NEU):** `ServiceRunWorker(QThread)` – Signale `log_message(str)`, `run_finished(str, int)` (scope_id, gespeicherte Rows), `run_failed(str, str)`. `_build_scope_definition()`: Set-Run = volle Definition; Single-Run = selektierter Service + alle Upstream-Services (`order[:idx+1]`), damit `depends_on`/`shared_state` gültig bleiben. `run()`: `FeatureBuilder.load_ohlcv` (Limit aus `StateManager`-Settings) → `prepare_plugin_df` → `PluginContext(mode="batch")` → `evaluator.execute_set()` → für jeden non-leeren `feature_store_payload` `fb.store_plugin_payload(symbol, timeframe, payload)` → `event_bus.service_set_changed.emit()` → `run_finished`.
* `serviceui/service_win.py`: `_run_worker`-Attribut; `_start_run_worker(scope_id, set_definition, instance_id)` (laufender-Worker-Guard, Symbol/Timeframe aus den Combos, Signal-Verdrahtung); `_on_run_service`/`_on_run_set` (Set via `set_repo.get_set` laden, Validierung, `QMessageBox.question` mit Set-/Service-Name + Symbol/Timeframe + Hinweis auf den feature_store-Schreibpfad); `_on_run_worker_finished`/`_on_run_worker_failed` (Log); `closeEvent` wartet zusätzlich auf `_run_worker`.
* `serviceui/__init__.py`: `ServiceRunWorker` exportiert (Import + `__all__`), Dokuzeilen aktualisiert.

**Validierung (headless, grün):**
* `python -m py_compile` auf allen 8 geänderten + `run_worker.py` (Exit 0); Import-Smoke `serviceui`/`run_worker`/`service_selector_model`/`feature_store_reader` erfolgreich; `MasterTree.run_service_requested`/`run_set_requested` vorhanden.
* Projektweite Suche: keine Rest-Referenzen auf `_update_toolbar_actions`, `_on_group_activated`, `_on_toolbar_remove`, `_show_toolbar_add_popup`, `selector.toolbar`-Methoden im Produktionscode (Attribut nur noch `None`).
* `test/check_p15_s2_service_tree.py` statisch aktualisiert (neue Test-DB `p15_s2_execdate_test.duckdb` in `test/`, J1–J7 für Ausführungsdatum, Fallback, Tree-Labels `prox_1 (05.08.26)`/`grid_1 (--.--.--)` und Run-Signal-Emission) – wie immer nicht ausgeführt (Regel: keine Regressionstests ohne explizite Anforderung).

### 3.16 Schritt 16 – Loose-Ends-Cleanup: ServiceToolbar archiviert & `group_activated` entfernt (05.08.2026)

**Anlass (vom Anwender entschieden):** Nach Schritt 15 (CRUD-Buttons entfernt, alle Struktur-Aktionen via Kontextmenü) war die Aktions-Toolbar toter Produktionscode – kein Widget nutzte sie mehr. Bereinigung nach der Projekt-Konvention (`.backup_*/`-Archivierung wie `.backup_grid_liquidity` und `.backup_parameter_panel`):

**A) `serviceui/toolbar.py` archiviert → `.backup_service_toolbar/serviceui/toolbar.py`:**
* `git mv` (Datei bleibt im Repo-Historie; `.backup_service_toolbar/` ist gitignored, Zeile 231 `.backup_*/`).
* `serviceui/__init__.py`: `from serviceui.toolbar import ServiceToolbar` + `"ServiceToolbar"` aus `__all__` entfernt; Paket-Docstring aktualisiert (Hinweis auf Archivierung, alle Struktur-Aktionen laufen über das MasterTree-Kontextmenü).

**B) `group_activated`-Signal aus `serviceui/master_tree.py` entfernt:**
* Deklaration (`group_activated = Signal(str)`), der Emit im `mousePressEvent` (Gruppen-Knoten-Klick) sowie alle Docstring-Erwähnungen (Modul-Doc, mousePressEvent-Doc) gelöscht – nach dem Toolbar-Abbau (Schritt 13/15) hat kein Consumer das Signal mehr verbunden.

**C) `service_selector_widget.py`: `toolbar`-Attribut komplett entfernt:**
* `self.toolbar = None` aus `__init__`, `set_mode()` und `_build_full_edit()` gelöscht (auch die Abwärtskompatibilitäts-Attribut bleibt nicht – kein Produktions-/Test-Code referenziert es mehr); `set_mode`-Docstring (`Tree+Toolbar` → `MasterTree`).

**D) `service_win.py`: veraltete Kommentare bereinigt** (keine Logik):
* Kommentar `# MasterTree + Aktions-Toolbar (Modus B / FULL_EDIT)` → `# MasterTree im Modus B / FULL_EDIT (seit 05.08.2026 ohne Toolbar)`.
* Kommentar `# Neues Set im MasterTree selektieren -> Toolbar [➕ Service]-Modus` → `# Neues Set im MasterTree selektieren (Editor-Sync via selection_changed)`.
* Methodennamen `_wire_selector_toolbar()` / `_toolbar_add_service()` bleiben als historische Namen erhalten (kein Consumer außerhalb; Umbenennung hätte historische Doku-Einträge 3.13–3.15 verfälscht).

**E) `test/check_p15_s2_service_tree.py` (statisch):** F2-Check von `full.toolbar is None` auf `not hasattr(full, "toolbar")` umgestellt (Attribut existiert nicht mehr); Docstring-Zeile F aktualisiert.

**Validierung (headless, grün):**
* `python -m py_compile` auf allen geänderten Dateien (`__init__.py`, `master_tree.py`, `service_selector_widget.py`, `service_win.py`, `test/check_p15_s2_service_tree.py`; Exit 0).
* Import-Smoke: `serviceui` importierbar; `ServiceToolbar` NICHT mehr in `__all__`; `ServiceRunWorker` bleibt; `MasterTree` ohne `group_activated`, mit `run_service_requested`/`run_set_requested`/`info_requested`.
* Projektweite Produktions-Referenz-Suche (ohne `docs/`, ohne `test/`): `group_activated`, `from serviceui.toolbar`, `self.toolbar`, `selector.toolbar` → **0 Treffer**; `ServiceToolbar` nur noch in der archivierten `.backup_service_toolbar/`-Datei und im `__init__`-Docstring (historischer Hinweis).
* Zeilenenden: `service_selector_widget.py` auf CRLF normalisiert (gemischt CRLF/LF nach Edits), alle übrigen Dateien blieben LF – git-Diff minimal und sauber.

### 3.17 Schritt 17 – Ausführungsdatum-Fixes: Legacy-Migration, Worker-Persistenz, Standalone-Datum (05.08.2026)

**Anlass (vom Anwender entschieden – Punkte 1, 2 und 4 aus der Fehleranalyse; Punkt 3 „(kein Feature-Store-Payload)" ist erwartetes Verhalten und wurde NICHT verändert):**

**A) Punkt 1 – „Keine Datumsangaben, obwohl Daten in der DB" (Ursache gefunden & behoben):**
* **Root Cause (per DB-Probe verifiziert):** ALLE 673.235 `feature_store`-Zeilen in `analytics.duckdb` waren Legacy-Rows der alten Monolith-Pipeline (`FeatureBuilder.build()`) mit `feature_id = NULL`, `plugin_version = NULL`, `feature_data = NULL` – die Abfrage `WHERE feature_id IS NOT NULL` fand dadurch NICHTS → Baum zeigte überall `(--.--.--)`, obwohl 673.235 Zeilen existierten.
* **`analytics/engine/feature_store_reader.py` (robustifiziert):** `fetch_last_execution_dates()` normalisiert jetzt `LOWER(TRIM(feature_id))` (Case-insensitiv + Whitespace-tolerant, Punkt 1-Kandidat 3), überspringt defensiv NULL/leere `feature_id` und NULL `created_at` (Kandidat 2).
* **NEU `test/migrate_legacy_feature_store.py` (Migration, Dry-Run + `--apply`):** Legacy-Zeilen mit befüllten Grid-Spalten (`grid_nearest_level`/`grid_dist_abs`/`grid_dist_pct`) tragen exakt die Proximity-Semantik (Abstand des Preises zu Grid-Linien) → werden auf `feature_id='proximity'`, `plugin_version='legacy'` migriert. `created_at` bleibt unverändert (echtes Legacy-Datum). `feature_data` bleibt NULL → der Chart-Lesepfad (`read_proximity_from_feature_store` filtert `feature_data IS NOT NULL` + `is_hit`) ignoriert die migrierten Zeilen weiterhin (KEINE Änderung im Chart-Rendering).
* **Angewendet:** **670.235 Zeilen → `feature_id='proximity'`**; 3.000 reine atr-Rows ohne Grid-Daten bleiben bewusst NULL (keine Proximity-Semantik, Exit-Code-Semantik des Skripts entsprechend: 0 = keine migrierbaren Grid-Zeilen mehr).
* **Verifiziert:** `fetch_last_execution_dates()` → `{'proximity': '02.08.26'}`; `feature_data IS NOT NULL` bei proximity weiterhin 0.

**B) Punkt 2 – „Nach Ausführen eines Services wird das Datum nicht aktualisiert" (ServiceSetRunWorker):**
* **`serviceui/set_run_worker.py`:** Der `ServiceSetRunWorker` (btn_execute_set-Pfad) persistiert jetzt die erzeugten `feature_store_payloads` ZWINGEND via `FeatureBuilder.store_plugin_payload()` in `analytics.duckdb` (Log je Service: „N Feature-Row(s) gespeichert" / „kein Feature-Store-Payload") und emittiert danach `event_bus.service_set_changed` → `ServiceSelectorModel.refresh()` liest das neue `MAX(created_at)` und der Baum aktualisiert das Datum `(DD.MM.JJ)` live ohne Neustart. `grid_lines` liefert bewusst keinen `feature_store_payload` (reines Chart-Overlay, Punkt 3) – nur Services mit non-leeren `records` (z.B. `proximity`) schreiben Zeilen.
* Der Kontextmenü-Worker `ServiceRunWorker` (Schritt 15) hatte die Persistenz+Emit-Logik bereits.

**C) Punkt 4 – Datum für Standalone Services & Plugins:**
* **`analytics/engine/service_selector_model.py`:** `build_tree()` liefert `"last_execution": self.last_execution_date(pid)` jetzt auch für die ⚡-Standalone-Gruppe und die 📦-Plugin-Gruppe (vorher nur in Service-Sets).
* **`serviceui/master_tree.py`:** `_build_plugin_item()` hängt das Datum an den Plugin-Namen (`proximity (02.08.26)`); Modul-Docstring ergänzt.

**D) Fallback-Konsistenz (doppelte Klammern behoben):** `last_execution_date()` liefert den Fallback als `--.--.--` OHNE Klammern; die Klammern setzt ausschließlich der MasterTree-Label-Aufbau (`Service_Name (DD.MM.JJ)` / `Service_Name (--.--.--)`) – vorher entstand `grid_1 ((--.--.--))`.

**E) `test/check_p15_s2_service_tree.py` (aktualisiert, gezielt ausgeführt):** J2 auf `--.--.--`-Fallback korrigiert; neue Checks J8/J9: Plugin-Zeile `proximity (DD.MM.JJ)` und `grid_lines (--.--.--)` (Standalone nutzt denselben `_build_plugin_item`-Pfad).

**Validierung (headless, grün):**
* **`test/check_p15_s2_service_tree.py` gezielt ausgeführt** (offscreen, Test-DBs in `test/`): **ALLE PRÜFUNGEN BESTANDEN** (inkl. J1–J9: Datum, Fallback, Set-Service-Labels, Plugin-Labels, Run-Signale).
* Echte DB-Verifikation: `fetch_last_execution_dates()` → `{'proximity': '02.08.26'}`; 670.235 proximity / 0 grid_lines / 3.000 NULL (atr-only); 0 proximity-Rows mit `feature_data` (Chart-Lesepfad unbeeinflusst).
* `python -m py_compile` auf allen geänderten Dateien (Exit 0); EventBus-Import in beiden Workern erfolgreich; `data/analytics.duckdb` ist gitignored (DB-Änderung wird über das Migrationsskript + Doku nachvollzogen).
* `docs/x_Exports.md` wurde vom Anwender selbst export-aktualisiert und bleibt wie immer unangetastet (nicht Bestandteil dieses Commits).

### 3.18 Schritt 18 – U15-E: Timeframe-Control & Multi-TF-Ausführung (05.08.2026)

**Anforderung (3 Teile, vom Anwender übergeben):**

1. **`analytics/features/definitions/grid_lines_service.py`** → echter FeatureStore-Payload mit `feature_id="grid_lines"`, `plugin_version` und Records je Bar (`bar_time`, `grid_nearest_level`, `grid_step`, `upper_level`, `lower_level`).
2. **`serviceui/service_win.py`** → neues Timeframe-Control `combo_tf` in der Filterleiste (neben dem Symbol-Dropdown) mit `'ALLE Timeframes'` (Index 0, Sentinel) + allen `get_timeframes()`-Werten (MN1..M1); Persistenz via `restore_state()`/`save_state()`.
3. **`serviceui/run_worker.py`** → Multi-TF-Loop: spezifischer Timeframe → einmal ausführen; `'ALLE Timeframes'` → ALLE Timeframes nacheinander (OHLCV laden, Abhängigkeiten auflösen, ausführen, je Timeframe speichern); `event_bus.service_set_changed` NUR EINMAL am Ende.

**Entscheidungen (Anwender-Frage 3; Fragen 1+2 wurden abgewählt → konservativ entschieden):** Die Kontextmenü-Run-Aktionen (`_start_run_worker`, `_on_run_service`, `_on_run_set`) lesen jetzt `combo_tf` (Filterleiste) statt `combo_tf_set`; `btn_execute_set`/`execute_set` (Set-Editor) bleibt unverändert auf `combo_tf_set`. Default-Auswahl `M1`. `upper_level = center + step_size`, `lower_level = center - step_size` (center = `f_round_to_custom_step(close, step_size)` = `grid_nearest_level`).

**A) `analytics/features/definitions/grid_lines_service.py` (1 Datei):**
* `capabilities["feature_store"] = True` (vorher `False` – GridLines rendert UND schreibt jetzt).
* `calculate()` erzeugt pro Bar einen Record `{bar_time (epoch), grid_nearest_level=center, grid_step=step_size, upper_level=round(center+step,6), lower_level=round(center-step,6)}` und liefert `feature_store_payload` mit `feature_id=self.plugin_id` (`"grid_lines"`), `plugin_version=self.version` (`"1.0.0"`) und `metadata{schema_version:"1.0.0", step_size}` – unabhängig von `show_lines` (das nur die Render-Darstellung steuert). `chart_render_payload` (lines/hit_circles) und `shared_state`-Namespace bleiben unverändert.

**B) `ui/service_win.ui` + `serviceui/service_win.py` (Filterleisten-Control):**
* **`ui/service_win.ui`:** In `layout_symbol` (zwischen `combo_symbol` und dem Spacer) `label_tf_filter` + `combo_tf` eingefügt (minWidth 150, Tooltip erklärt den Multi-TF-Modus, Default-Item `'ALLE Timeframes'`).
* **`serviceui/service_win.py`:**
  * Neues Attribut `self.combo_tf` (`findChild(QComboBox, "combo_tf")`).
  * `_refresh_timeframe_combo()`: füllt `'ALLE Timeframes'` (Index 0, Sentinel `ALL_TIMEFRAMES`) + `get_timeframes()`-Keys (Fallback `TF_SECONDS_MAP`, letzter Fallback Basisliste); aktuelle Auswahl bleibt erhalten, Default `M1`; blockSignals-geschützt. Aufruf im `__init__` nach `_refresh_symbol_combo()`.
  * `combo_tf.currentTextChanged` → `save_state` (sofortiges Persistieren wie bei `combo_symbol`).
  * `get_persistent_timeframe()` liest jetzt `combo_tf` (inkl. Sentinel 1:1 – `'ALLE Timeframes'` ist eine reguläre, persistierbare Auswahl); Fallback `"H1"`.
  * `_apply_persistent_filters()` stellt zusätzlich `combo_tf` wieder her (`findText`, inkl. Sentinel).
  * `_start_run_worker`, `_on_run_service`, `_on_run_set`: Timeframe aus `combo_tf` statt `combo_tf_set` (die `QMessageBox.question`-Bestätigungen zeigen den gewählten Timeframe bzw. den Multi-TF-Modus).

**C) `serviceui/run_worker.py` (Multi-TF-Worker):**
* Neue Konstante `ALL_TIMEFRAMES = "ALLE Timeframes"` (Sentinel).
* `_resolve_timeframes()`: spezifischer TF → `[tf]`; `ALL_TIMEFRAMES` → `list(get_timeframes().keys())` (Fallback `TF_SECONDS_MAP`, letzter Fallback Basisliste MN1..M1).
* `_execute_timeframe(fb, settings, definition, scope_label, tf)`: OHLCV laden → `prepare_plugin_df` → `PluginContext(symbol, tf, mode="batch")` → `evaluator.execute_set()` → non-leere `feature_store_payloads` via `fb.store_plugin_payload(symbol, tf, payload)` (Timeframe im Schreibpfad); liefert Anzahl geschriebener Rows, überspringt leere OHLCV-Daten mit Log.
* `run()`: Loop über die aufgelösten Timeframes; im Multi-TF-Modus bricht ein fehlgeschlagener Timeframe die Gesamt-Ausführung NICHT ab (Fehler wird geloggt, Rest läuft weiter); Summe der Rows in `run_finished`; `event_bus.service_set_changed.emit()` NUR EINMAL nach Abschluss aller Timeframes. Single-TF ohne Daten → `run_failed` (bisheriges Verhalten unverändert).

**Validierung (headless, grün):**
* `python -m py_compile` auf `serviceui/service_win.py`, `serviceui/run_worker.py` (Exit 0); `ui/service_win.ui` parst als XML (Exit 0).
* `test/test.py` Teil 6 (U1–U13) + Teil 6.4 (U14–U18), offscreen auf Test-DBs isoliert, **ALLE PRÜFUNGEN BESTANDEN**: `combo_tf` existiert in der Filterleiste, Index 0 = Sentinel, alle Timeframes enthalten, Default `M1`; Persistenz/Restore des Sentinel-Modus (`get_persistent_timeframe`/`save_state`/`restore_state`); `_resolve_timeframes()` Single vs. ALL (Reihenfolge = `get_timeframes()`); Multi-TF-`run()`-Schleife mit Fake-FeatureBuilder/-Evaluator (M1+H1 gespeichert, M30 ohne Daten übersprungen, Rows summiert, genau 1× `run_finished`, kein `run_failed`; Single-TF mit Daten → `run_finished`, Single-TF ohne Daten → `run_failed`); Grid-Level-Mathematik (close 30.1 / step 0.5 → center 30.0, upper 30.5, lower 29.5).
* Zeilenenden: `.ui` auf LF normalisiert (Repo-Konvention für `*.ui`); git-Diff minimal (25 Insertions im `.ui`).
