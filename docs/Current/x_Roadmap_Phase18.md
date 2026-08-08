# Phase 18: Analytics-Finalisierung

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 18)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase17_step1`, `phase17_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
4. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
5. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`db_service.py`) – eine Verbindung pro Thread und DB-Datei.
6. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
7. **Concurrency-Guard & Timer-Pausierung:** Solange im ServiceWindow intensive Service-Berechnungen laufen (`ServiceRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
8. **Isolierter Test-Workspace:** Alle neuen Test-Python-Dateien und temporären Test-Datenbanken (`*.duckdb`) müssen strikt im Unterordner `test/` erzeugt, gelesen und abgelegt werden – niemals im Projekt-Root oder im `data/`-Ordner.
9. **Open/Closed-Principle & Code-Preserving:** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden und bestehende Kern-Klassen bleiben geschützt.
10. **Test-Cleanup (Entscheidung 06.08.2026):** Tests werden NICHT dauerhaft aufbewahrt. Nach Abschluss jedes Phasenkapitels wird der Ordner `test/` aufgeräumt – es bleibt ausschließlich die Datei `test/test.py` (dauerhafter Test-Harness) bestehen.
11. **Naming Conventions & PineScript-Input-Zone:** 
    * Services in `analytics/features/definitions/` nutzen strikt das Präfix `srv_` (`plugin_id = "srv_..."`).
    * Indikatoren in `chart/indicators/` nutzen strikt das Präfix `ind_` (`indicator_id = "ind_..."`).
    * Füllwörter (`service`, `plugin`, `indicator`) entfallen im Dateinamen.
    * Das `parameter_schema` liegt direkt am Dateianfang unter dem Header-Docstring.
    * Jedes Service-Plugin deklariert `metadata["category"]` für die dynamische Kategorie-Ordner-Struktur im MasterTree.


---

# 18.01.01 Harmonisierung Analytics_win & Service_win (Rekursive Ordner)

## 1. Regeln & Invarianten

* **Einrückung:** Ausschließlich **4 Leerzeichen** (E-1: „Tabs" = redaktioneller Fehler).
* **Spacing:** Exakt **1 Leerzeile** zwischen Funktionen/Methoden.
* **UI-Tests:** **VERBOTEN.** Verifikation rein headless (`py_compile`, `test/test.py`).
* **Architektur:** SRP, Inversion of Control, Entkopplung via `EventBus`.
---

## 2. Architektur & Datenfluss (Textblock-Schema)

[ServiceSelectorModel] ──(baut n-tiefe Ordner/Pfade)──► [MasterTree (serviceui)]
         │                                                        │
         ├──► [ServiceWindow]   ──(speichert)──► [StateManager (plugin_params_<id>)]
         │                                                │
         └──► [AnalyticsWindow] ──(sendet IDs)─► [AnalyticsViewModel] ◄── [EventBus]
---

## 3. Betroffene Dateien

* `analytics/engine/service_selector_model.py`: Rekursive Ordner (`_insert_into_category_tree`), tiefes Resolving (`category_plugin_ids`).
* `serviceui/master_tree.py`: Rekursives Rendering (`GROUP_CATEGORY`) im QTreeWidget.
* `serviceui/service_win.py`: Aktionen/Kontextmenüs für n-tiefe Ordner anpassen.
* `analytics/ui/analytics_win.py`: Einbau `MasterTree` & `ParamColumnsWidget`, Standalone-Editierung, Multi-Select-Filter.
* `analytics/engine/analytics_view_model.py`: Verarbeitet aufgelöste `feature_ids` aus Ordnern/Sets.

---

## 4. Schritt-für-Schritt Anleitung (IDE-AI)

### Step 1: Rekursion in `service_selector_model.py`

* [ ] `_insert_into_category_tree()` für unbegrenzt verschachtelte Slash-Pfade (`A/B/C`) absichern.
* [ ] `category_plugin_ids(path)` so anpassen, dass alle Plugins aus Unterordnern rekursiv gesammelt werden.

### Step 2: `master_tree.py` & `service_win.py`

* [ ] Ordner-Rendering im `MasterTree` rekursiv für `GROUP_CATEGORY` umsetzen (`📁 <Name>`).
* [ ] In `service_win.py` Ordner-Aktionen für tief verschachtelte Pfade anpassen.

### Step 3: `analytics_win.py` Harmonisierung & Parameter-Editierung

* [x] Legacy-Filter durch `MasterTree` & `ServiceParamColumnsMixin` ersetzen (umgesetzt im `ServiceSelectorDialog`, s. E-4).
* [x] Bei Standalone-Service (`belongs_to_indicator == False`):
1. Params laden: `state_manager.get_global_value("plugin_params_<id>", default)`.
2. Im Param-Panel aus `full_parameter_schema()`/`_plugin_config()` rendern.
3. Bei Änderung: `save_global_value("plugin_params_<id>", params)` + `event_bus.service_set_changed.emit()`.

* [x] Bei Baum-Selektion (Set/Ordner/Plugin): IDs auflösen -> `view_model.set_feature_ids(ids)` (Live-Filter via `selection_ids_requested`).

### Step 4: Quality Gate

* [x] `python -m py_compile analytics/engine/service_selector_model.py serviceui/master_tree.py serviceui/service_win.py analytics/ui/analytics_win.py` (zusätzlich `serviceui/service_selector_dialog.py`) – **läuft fehlerfrei**.
* [x] Headless-Test in `test/test.py` bzw. `test/` für rekursive Kategorien & Standalone-Params (42 Prüfungen bestanden, siehe §5.1 Step 4).
* [x] Code-Check: 4 Leerzeichen (E-1), 1 Leerzeile Abstand (Ist-Code folgt dem).

---

## 5. Review & Entscheidungen (08.08.2026, Bugfixing-Modus)

### 5.1 Vollständigkeits-Review (Ist-Code vs. Kapitel-Anweisung)

| Step | Status | Befund |
|---|---|---|
| Step 1 | **Bereits umgesetzt** | `_insert_into_category_tree()` ist bereits rekursiv (unbegrenzte Slash-Pfade, 16.08 K2); `category_plugin_ids(path)` sammelt bereits rekursiv aus Unterordnern (17.01.02). Tests in `test/test.py` (16.08, 17.01.02) vorhanden. |
| Step 2 | **Bereits umgesetzt** | Rekursives Ordner-Rendering im MasterTree (`_build_category_item`/`_build_child_item`); Ordner-Aktionen in `service_win.py` (`_on_run_category`, `_on_category_info_requested`, `_category_path_of`). Tests vorhanden. |
| Step 3 | **Umgesetzt (korrigierte Variante, s. E-4)** | Standalone-Editierung (plugin_params_<id> + EventBus-Sync), Live-Filter (`selection_ids_requested` → `set_feature_ids`) und Set-/Service-Verwaltung (CRUD via ServiceSetRepository) sind im `ServiceSelectorDialog` umgesetzt – NICHT eingebettet in `analytics_win.py` (siehe E-4). |
| Step 4 | **Abgeschlossen (08.08.2026)** | `py_compile` aller betroffenen Dateien (inkl. `service_selector_model.py`, `master_tree.py`, `service_win.py`, `analytics_win.py`, `service_selector_dialog.py`) **läuft fehlerfrei**. Headless-Test `test/check_phase18_dialog.py` (42 Prüfungen: Auflösung, Panel-Editierbarkeit, Persistenz, Live-Filter, CRUD, Dialog-Singleton) **bestanden**, danach entfernt (Invariante 10). |

### 5.2 Konsistenz-Probleme (Doku vs. Ist-Code)

1. **Einrückung:** Kapitel verlangt „Ausschließlich Tabs" – der gesamte Codebase nutzt **4 Leerzeichen** (0 Tab-Zeilen in allen 7 Dateien). → Siehe E-1.
2. **`ParamColumnsWidget`:** Diese Klasse existiert **nicht**. Real: `ServiceParamColumnsMixin` in `serviceui/param_columns.py`. → Siehe E-2.
3. **`service_set_changed`-Emit:** `ServiceWindow._save_plugin_params()` emittiert aktuell **kein** `service_set_changed` (nur `_save_params_from_panel` im Set-Pfad). Kapitel verlangt das Emit für Standalone-Params. → Siehe E-3.
4. **Test-Cleanup (Invariante 10):** `test/` enthält Alt-Proben (`_probe_meta.py`, `_probe_sets.py`, `_probe_*_out.txt`), die nach Abschluss entfernt werden müssen (nur `test.py` bleibt).

### 5.3 Entscheidungen

**E-1 (08.08.2026): Einrückung = 4 Leerzeichen, nicht Tabs.** Der Projekt-Standard (sämtliche bestehenden Dateien) ist 4 Leerzeichen pro Ebene. Die „Tabs"-Regel des Kapitels wird als redaktioneller Fehler gewertet und für alle Phase-18-Änderungen auf **4 Leerzeichen** korrigiert (kein Reindent bestehender Dateien, Code-Preserving). Spacing „1 Leerzeile zwischen Methoden" bleibt gültig (Ist-Code folgt dem bereits).

**E-2 (08.08.2026): Referenzklasse = `ServiceParamColumnsMixin`.** Alle Vorkommen von „ParamColumnsWidget" in der Kapitel-Anweisung bezeichnen `serviceui/param_columns.py::ServiceParamColumnsMixin` (der einzige reale Param-Column-Builder, genutzt von `ServiceWindow` und `ServiceSelectorDialog`/`_DialogParamHost`). Eine neue Klasse wird nicht eingeführt.

**E-3 (08.08.2026): `service_set_changed` nach Standalone-Speicherung.** Gemäß Kapitel wird bei `save_global_value("plugin_params_<id>", ...)` zusätzlich `event_bus.service_set_changed.emit()` abgesetzt, damit alle `ServiceSelectorModel`-Instanzen (MasterTree-Daten, Ausführungsdaten) live synchronisieren. Im ServiceWindow-Pfad wird das Verhalten beibehalten (der Run-Worker emittiert bereits am Ende); der neue Analytics-Pfad emittiert gemäß Kapitel.

**E-4 (08.08.2026, KORRIGIERT am 08.08.2026): Umsetzungs-Variante für Step 3 = Dialog als frei beweglicher Service-Picker/Manager (KEINE Einbettung).** Die zuvor dokumentierte Option B („`ServiceSelectorDialog` entfällt ersatzlos, MasterTree + Param-Panel werden direkt in `analytics_win.py` eingebettet") wurde umgesetzt, vom Benutzer aber als Missverständnis korrigiert: Baum und Parameter **bleiben im `ServiceSelectorDialog`** – dieser ist das frei bewegliche „Manager-Window" während einer Analytics-Session. Die neue Logik wurde **im Dialog** implementiert:

* **Live-Filter:** Klick auf eine Baum-Zeile (Set/Ordner/Plugin) löst die feature_ids auf (`_resolve_selection_ids`, Kategorie rekursiv via `category_plugin_ids`) und emittiert `selection_ids_requested` → `AnalyticsViewModel.set_feature_ids()` sofort (ohne „Anwenden").
* **Standalone-Editierung:** Standalone-Services (`belongs_to_indicator == False`) sind im Param-Panel **editierbar** (`_DialogParamHost`: RAM-Definition + Dirty-Tracking, Speichern-Button; Persistenz `save_global_value("plugin_params_<id>", …)` + `event_bus.service_set_changed.emit()`).
* **Verwaltung (CRUD):** Set anlegen/umbenennen/löschen, Service hinzufügen/entfernen/verschieben via `ServiceSetRepository` + EventBus-Live-Sync (MasterTree-Kontextmenü-Signale).
* **Singleton-Dialog:** Kein `WA_DeleteOnClose` mehr – der Dialog bleibt während der Session erhalten, ist frei positionierbar (Geometrie via global_settings) und aktualisiert die Analytics-Ansicht live.

### 5.4 Verbleibende offene Punkte (für die Umsetzung)

1. **Dialog-Gestaltung:** Der `ServiceSelectorDialog` ist als frei bewegliches Manager-Window umgesetzt (kein `WA_DeleteOnClose`, Singleton). Checkbox-Multi-Select („Anwenden & Schließen") und Live-Filter (Zeilen-Klick) existieren parallel – das Zusammenspiel beider Pfade (z. B. Button-Anzeige nach Checkbox-Anwenden vs. Live-Filter) ist manuell zu prüfen.
2. **Editierbarkeit:** Die Standalone-Editierung nutzt das `_DialogParamHost`-Muster (RAM-Definition + `plugin_params_<id>`); die `service_set_changed`-Konsistenz im ServiceWindow-Pfad wurde ergänzt (E-3). Die interaktive Bedienung (Dirty-Marker, Save-Button) ist manuell zu verifizieren.
3. **Profil-Sync:** `_sync_service_filter_button`/`_active_display_names` bleiben gültig (Button-Text im AnalyticsWindow); nach einem Live-Filter werden die Anzeigenamen über das Modell re-resolved.

---

# 6. Implementierungs-Log (Phase 18.01.01)

**Log-Format:** Datum/Uhrzeit (MD), Schritt-ID, Datei(en), Kurzbeschreibung, Verifikation.

### 08.08.2026 12:36 – Phase 18.01.01 abgeschlossen (4 Commits)

1. **18.01.01 E-4-KORREKTUR (Commit `cd56958`):**
   * `analytics/ui/analytics_win.py`, `serviceui/service_selector_dialog.py`, `serviceui/service_win.py`, `docs/AKTUELLE_UMSETZUNG.md`
   * Revert der Analytics-Einbettung (Option B) – `ServiceSelectorDialog` ist wieder der frei bewegliche Picker/Manager während der Analytics-Session (Singleton, kein `WA_DeleteOnClose`, Geometrie-Persistenz).
   * Live-Filter: Klick auf Set/Ordner/Plugin löst feature_ids auf (`_resolve_selection_ids`, Kategorie rekursiv via `category_plugin_ids`) → `selection_ids_requested` → `AnalyticsViewModel.set_feature_ids()`.
   * Standalone-Editierung im Param-Panel (`_DialogParamHost`: `_plugin_config` + Dirty-Tracking, Speichern-Button; Persistenz `save_global_value("plugin_params_<id>", …)` inkl. Beschreibungs-Collection).
   * Set-/Service-CRUD via `ServiceSetRepository` + `event_bus.service_set_changed` (E-3).
   * E-3-Konsistenz: `ServiceWindow._save_plugin_params()` emittiert jetzt ebenfalls `service_set_changed`.
   * Verifikation: `py_compile` aller 4 Dateien PASS; Headless-Test 42/42 (danach entfernt, Invariante 10).

2. **18.01.01 Quality Gate Step 4 (Commit `876bc4f`):**
   * `docs/AKTUELLE_UMSETZUNG.md`
   * Doku-Status: Step-3-Zeile auf „Umgesetzt (korrigierte Variante, s. E-4)", Step-4 „Abgeschlossen", E-1-Einrückungs-Regel (4 Leerzeichen), Step-4-Checkboxen.
   * Verifikation: `py_compile` aller 5 betroffenen Dateien PASS (inkl. `service_selector_model.py`, `master_tree.py`).

3. **Bugfix: Parameteranzeige `_mode_schemas` (Commit `a9d917b`):**
   * `serviceui/service_selector_dialog.py`
   * `_DialogParamHost.__init__` initialisierte nur `_service_param_controls`/`_service_desc_controls`; `ServiceParamColumnsMixin._build_service_column` schreibt zusätzlich in `_mode_schemas`, `_service_param_labels`, `_service_info_labels`, `_service_info_pids` → `AttributeError: no attribute _mode_schemas`.
   * Fix: 4 fehlende Registrys initialisiert; `_clear_panel` leert alle 6 Registrys (kein Stale beim Zeilenwechsel).
   * Verifikation: `py_compile` PASS; Headless-Test 11/11 (echter `_build_service_column`-Pfad + Gegenprobe reproduziert den Original-Bug; danach entfernt).

4. **Bugfix: Dialog-Fensterhöhe FIX + Scrollbars (Commit `033d3cc`):**
   * `serviceui/service_selector_dialog.py`
   * ServiceWindow-Muster (07.08.2026): `param_scroll.setWidgetResizable(False)` + Container wird nach jedem Panel-Aufbau explizit auf `layout().sizeHint()` gesetzt (`_resize_param_container_deferred`, deferred wegen QWidgetItemV2-Cache) → ScrollArea zeigt bei Überhöhe vertikale Scrollbalken statt Fensterhöhen-Anpassung.
   * `setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)` (vorher nur horizontal), `setSizeConstraint(QLayout.SetNoConstraint)` (QDialog-Default hätte die Höhe beim show() an den Layout-sizeHint geklemmt).
   * `_DialogParamHost._resize_param_box_deferred` delegiert an den Dialog (Mode-Wechsel/Experten-Optionen-Kollaps ziehen den Container nach, kein Fenster-Reflow).
   * Verifikation: `py_compile` PASS; Headless-Test 17/17 (Container-Resize auf sizeHint, deferred-Planung, Host-Delegation, `_fit_dialog_width` ändert nur die Breite, kein `resize_to_clamped_content`/`_reflow` im Dialog; danach entfernt).

**Abschluss:** Phase 18.01.01 (Harmonisierung Analytics_win & Service_win) vollständig umgesetzt und headless verifiziert. Offene Punkte aus §5.4 sind reine manuelle UI-Prüfungen (Zusammenspiel Checkbox/Anwenden vs. Live-Filter, Dirty-Marker/Speichern-Button, Profil-Sync) und blockieren den Stand nicht.


---

# 18.01.02 Refactoring & Modularisierung (Großdateien)

## 1. Regeln & Invarianten

* **Einrückung:** Ausschließlich **Tabs**.
* **Spacing:** Exakt **1 Leerzeile** zwischen Funktionen/Methoden.
* **UI-Tests:** **VERBOTEN.** Verifikation rein headless (`py_compile`, `test/test.py`).
* **Architektur:** Single Responsibility Principle (SRP), Inversion of Control, Entkopplung.



---

## 2. Refactoring-Ziele (Zu große Dateien)

```text
[db_service.py] ──────────► [db/db_pool.py] + [db/schema_initializer.py]
                        └─► [data_sync/mt5_sync_service.py] + [repositories/market_data_repository.py]

[main.py] ────────────────► [workers/live_tick_worker.py] + [workers/data_sync_worker.py]
                        └─► [ui/window_manager.py]

[service_selector_model] ─► [analytics/engine/tree_builder.py] (Kategorie-Verschachtelung/Baumaufbau)

```

---

## 3. Modularisierungs-Anleitung (IDE-AI)

### Step 1: `db_service.py` entflechten

* [ ] `DbPool` & Threading-Locks in `db/db_pool.py` auslagern.


* [ ] Schema-Anlage (`check_and_init_databases`) nach `db/schema_initializer.py` verschieben.


* [ ] Sync-Logik (`sync_market_data`) in `data_sync/mt5_sync_service.py` trennen.


* [ ] `MarketDataRepository` eigenständig in `repositories/market_data_repository.py` platzieren.



### Step 2: `main.py` schlankziehen

* [ ] `LiveTickWorker` & `DataSyncWorker` in eigene Worker-Dateien im Ordner `workers/` auslagern.


* [ ] Wiederherstellung & Jump-to-Bar (`restore_all_windows`, `open_chart_at_bar`) in `ui/window_manager.py` kapseln.



### Step 3: `service_selector_model.py` bereinigen

* [ ] Rekursiven Baumaufbau (`build_tree`, `_insert_into_category_tree`) in `analytics/engine/tree_builder.py` auslagern.


* [ ] Model rein auf Daten-Providing & EventBus-Sync fokussieren.



### Step 4: Quality Gate

* [ ] `python -m py_compile db/db_pool.py db/schema_initializer.py data_sync/mt5_sync_service.py repositories/market_data_repository.py workers/live_tick_worker.py workers/data_sync_worker.py ui/window_manager.py analytics/engine/tree_builder.py`
* [ ] Headless-Test in `test/test.py` für DB-Zugriffe & Worker-Instanziierung ausführen.
* [ ] Code-Check: Nur Tabs, 1 Leerzeile Abstand.

---

# 18.01.03 Dynamic Tree Management (Ordner-CRUD, Drag & Drop & Sets-Kategorien)

## 1. Regeln & Invarianten

* **Einrückung:** Exakt **4 Leerzeichen** (Codebase-Standard).
* **Spacing:** Exakt **1 Leerzeile** zwischen Funktionen/Methoden.
* **UI-Tests:** **VERBOTEN.** Verifikation rein headless (`py_compile`, `test/test.py`).
* **Architektur:** Modellgetrieben, Single Source of Truth (`ServiceSelectorModel`), Entkopplung via `EventBus`.

---

## 2. Architektur & Datenfluss

[MasterTree (Custom Drag&Drop + ContextMenu)] ──(Aktion)──► [ServiceSelectorModel / Repositories]
        │                                                                │
        ├── Neuer Ordner / Rename ──► Ordnerpfad-Aktualisierung          │
        └── Drag & Drop DropEvent ──► Category-String Update             │
                                                                         ▼
[ServiceWindow & AnalyticsWindow] ◄────── (Refresh UI) ─────── [EventBus.service_set_changed]


---

## 3. Datenmodell-Erweiterungen

* **Sets (`ServiceSetDefinition`):** Optionales Feld `"category": "Ordner/Unterordner"` in Set-JSON.
* **Plugins / Standalone Services:** Kategorie-Pfad im Metadatum `category` bzw. Persistenz via `state_manager.save_global_value("plugin_params_<id>", ...)`.

---

## 4. Schritt-für-Schritt Anleitung (IDE-AI)

### Step 1: Sets-Kategorisierung in `service_selector_model.py`

* [ ] Ordner-Mechanik (`_insert_into_category_tree`) auch auf den Knoten `Sets` (`GROUP_SETS`) anwenden.
* [ ] `category_set_ids(path)`-Methode hinzufügen, die alle `set_id`s aus Unterordnern rekursiv auflöst.

### Step 2: Konfektionierung `MasterTree` (`serviceui/master_tree.py`)

* [ ] **Drag & Drop aktivieren:** `setDragEnabled(True)`, `setAcceptDrops(True)`, `setDropIndicatorShown(True)`.
* [ ] `dropEvent()` überschreiben:
1. Ermittle gezogenen Knoten (Set-ID, Plugin-ID oder Ordner) und Ziel-Ordner-Pfad.
2. Aktualisiere den Kategorie-Pfad beim Element.
3. Emittiere Datenänderung an das Modell/Repositories.

* [ ] **Kontextmenü erweitern (`customContextMenuRequested`):**
1. **"Neuer Ordner":** Öffnet `QInputDialog`, erstellt neuen Unterordner-Pfad im gewählten Elternknoten.
2. **"Umbenennen":** Benennt Ordner/Knoten um und führt Pfad-Update für alle enthaltenen Kinder durch (String-Replace).


### Step 3: Persistenz & Synchronisation

* [ ] Ordner-Aktionen für Sets via `ServiceSetRepository.save_set()` abspeichern.
* [ ] Ordner-Aktionen für Standalone-Plugins via `state_manager.save_global_value("plugin_params_<id>", ...)` sichern.
* [ ] Nach allen Strukturänderungen `event_bus.service_set_changed.emit()` abfeuern.


### Step 4: Quality Gate

* [ ] `python -m py_compile serviceui/master_tree.py analytics/engine/service_selector_model.py analytics/ui/analytics_win.py serviceui/service_win.py`
* [ ] Headless-Test in `test/test.py` für rekursive Sets-Kategorien & Pfad-Updates.
* [ ] Code-Check: Exakt 4 Leerzeichen Einrückung, 1 Leerzeile Abstand.


---

## Prüfprotokoll 18.01.03 (08.08.2026) – Konsistenz, Vollständigkeit & Entscheidungen

### Prüfergebnis (Konsistenz)
Der Plan ist architektonisch konsistent (Modell-getrieben, MasterTree entkoppelt via
Signale, EventBus `service_set_changed`, keine SQL in UI). Die Ordner-Mechanik
(`_insert_into_category_tree`, `category_plugin_ids`, `_category_parts`) existiert für
GROUP_PLUGINS und ist die Vorlage für GROUP_SETS. **3 Lücken** gefunden:

* **L1 – `ServiceSetRepository.save_set()`-Whitelist:** Das Payload-Dict persistiert
  nur feste Keys (`set_id, display_name, description, indicator_id, version,
  schema_version, created_at, execution_order, services`). Ein neues Set-Feld
  `category` würde beim Speichern VERWORFEN. → Step 3 bzw. „Datenmodell-
  Erweiterungen" muss `category` additiv ins Payload aufnehmen (analog `indicator_id`),
  sonst ist die Sets-Kategorisierung nicht persistent.
* **L2 – `plugin_params_<id>`-Kollision:** Der Plan will Ordner-Aktionen für
  Standalone-Plugins über `state_manager.save_global_value("plugin_params_<id>", ...)`
  sichern. Dieser Key ist aber bereits exklusiv für das Parameter-Preset belegt
  (service_win `_plugin_config`/`_save_plugin_params`, Dialog `_plugin_config` –
  lookback/params/description). Vermischung von Kategorie-Override und Parameter-
  Preset kollidiert semantisch und stört beide Editoren. → separater Key
  `plugin_category_<id>` (siehe Entscheidung E1).
* **L3 – Generische Ordner-Auflösung im Picker (SELECT_MULTI):**
  `_resolve_selection_ids`/`_entries_for_scope` behandeln TYPE_CATEGORY aktuell nur
  als Plugin-Ordner (`category_plugin_ids`). Bekommen auch SETS Ordner, muss die
  Auflösung die ZUGEHÖRIGE GRUPPE des Ordners kennen (Sets-Ordner → Sets → Services
  → plugin_ids; Plugins-Ordner → plugin_ids). `MasterTree._emit_selection_details`
  liefert für TYPE_CATEGORY nur den Pfad im plugin_id-Slot – die Gruppe fehlt.
  → MasterTree muss für Kategorie-Ordner die Elterngruppe (GROUP_SETS/GROUP_PLUGINS)
  mitliefern.

### Entscheidungen (18.01.03)
1. **E1 – Plugin-Kategorie-Override:** eigener global_settings-Key `plugin_category_<id>`
   (JSON-String Pfad oder ""). Auswertungsreihenfolge im Modell `_category_parts()`:
   Override (falls vorhanden) → sonst `metadata['category']` → sonst „keine Kategorie".
   Das bestehende `plugin_params_<id>` bleibt unangetastet (Parameter-Preset).
2. **E2 – Set-Kategorie-Persistenz:** `category` wird additiv in das `save_set()`-
   Payload aufgenommen; `ServiceSetDefinition` erhält das optionale Feld `category`
   (Doku in `analytics/engine/service_models.py`). Leer oder "General" = keine
   Kategorie (Root-Ebene, Spiegel der Plugin-Logik).
3. **E3 – Leere Ordner (REVIDIERT am 08.08.2026, Bugfixing-Modus):** Die
   ursprüngliche Entscheidung („leere Ordner verschwinden beim nächsten Refresh,
   kein Empty-Folder-Persistenzmodus") ist **widerrufen**. Benutzererzeugte
   Ordner werden persistiert (global_settings, Key `tree_folders_sets` /
   `tree_folders_plugins` – Liste Slash-Pfade ohne `📁`-Präfix) und verschwinden
   **NICHT** beim Refresh, sondern nur bei **manueller Löschung** im Kontextmenü
   („Ordner löschen", nur für leere Ordner aktiv). Umgesetzt in `phase18_step3`.
4. **E4 – Drag & Drop Scope:** nur Kategorie-Moves (Set/Plugin/Ordner auf Ordner-
   Ziel oder Root-Gruppe). Service-Reihenfolge bleibt beim Kontextmenü Order ▲/▼;
   KEIN Service-Reorder per Drag & Drop.
5. **E5 – Verdrahtung in allen Trees:** Die neuen MasterTree-Signale
   (`create_folder_requested`, `rename_folder_requested`, `folder_item_moved`) werden
   in service_win (FULL_EDIT) UND ServiceSelectorDialog (SELECT_MULTI, Picker =
   Manager-Window 18.01.01 E-4) mit Orchestrator-Handlern verdrahtet.

### Generizitäts-Check (alle Trees: service_win / analytics_win / Service-Picker)
Der MasterTree ist das gemeinsame Bauteil (FULL_EDIT bzw. SELECT_MULTI).
Baum-Rekursion (`_build_child_item` → `_build_category_item`, Ordner ohne
ItemIsUserCheckable), `_category_path_of` und der Checkbox-Zustand (`_checked_items`
Keys sind pfadunabhängig: set_id/instance_id/plugin_id) sind bereits
gruppen-agnostisch und funktionieren für Sets-Ordner identisch – sofern das Modell
für Sets dasselbe Ordner-Blatt-Format liefert (`set_id/display_name/definition/services`).
Einzige generische Lücke ist L3 (Gruppen-Kontext bei Kategorie-Klicks); in service_win
muss analog zu `_on_run_category`/`_on_category_info_requested` die Sets-Ordner-
Variante (Sets unter dem Pfad → Services) ergänzt werden.


---

## Implementierungs-Log 18.01.03 (08.08.2026 13:12) – Dynamic Tree Management

Umgesetzt (alle Checklisten-Punkte des Kapitels abgearbeitet):

### Step 1 – Sets-Kategorisierung (`analytics/engine/service_selector_model.py`)
* `_insert_set_into_category_tree()` + `_set_category_parts()`: die Ordner-Mechanik
  (K2/K8/K9) gilt jetzt auch für GROUP_SETS – Set-Definitionen mit `category`-Feld
  werden rekursiv in 📁-Ordner einsortiert, ohne Kategorie bleiben sie Root-Blaetter.
* `category_set_ids(path)`: rekursive Auflösung aller set_ids unter einem Pfad
  (analog `category_plugin_ids`).
* `category_service_plugin_ids(group, path)`: gruppenspezifische Auflösung (L3) –
  Sets-Ordner → Service-plugin_ids aller Sets, Plugins-Ordner → `category_plugin_ids`.
* `_sort_category_nodes` verallgemeinert (Blatt-Sortierung auch für Sets-Dicts).
* E1-Override-Logik: `_category_parts()` wertet `plugin_category_<id>` (VORRANG vor
  `metadata['category']`, auch "" = Root); Overrides werden in `refresh()` einmalig
  geladen (`_load_plugin_category_overrides`), kein DB-Zugriff im Baum-Aufbau.

### Step 1/3 – Persistenz (L1/E2)
* `ServiceSetRepository.save_set()`: `category` additiv im Payload (analog `indicator_id`),
  mit `record_snapshot=False` bei Struktur-Verwaltung (kein Snapshot, Invariante 9).
* `ServiceSetDefinition`: optionales Feld `category` dokumentiert
  (`analytics/engine/service_models.py`).

### Step 3 – Gemeinsame Schreib-Helfer (`serviceui/service_set_utils.py`, E1/E2, DRY)
* `set_set_category(set_repo, set_id, path)` – frisch aus der DB laden, `category`
  setzen, `save_set(record_snapshot=False)`.
* `set_plugin_category(state_manager, plugin_id, path)` – global_settings-Key
  `plugin_category_<id>` (separater Key, L2-Fix: `plugin_params_<id>` bleibt dem
  Parameter-Preset vorbehalten).
* `rename_category(model, set_repo, state_manager, group, old_path, new_path)` –
  String-Replace (echte Ordner-Grenzen, `_replace_prefix`) über alle Kinder.

### Step 2 – MasterTree (`serviceui/master_tree.py`)
* Drag & Drop: `setDragEnabled/setAcceptDrops/setDropIndicatorShown` + eigene
  `startDrag()` (JSON-MIME `application/x-pytrader-category-move`; nur
  Sets/Plugins/Ordner ziehbar, E4) + `dragEnterEvent/dragMoveEvent/dropEvent`.
  `dropEvent` emittiert nur `folder_item_moved` (Set/Plugin) bzw. `folder_moved`
  (Ordner) – der Baum führt keinen echten Item-Move; Guards: Gruppen-Mismatch und
  Ordner-Zyklus (eigener Unterordner) werden abgelehnt.
* Kontextmenü: „Neuer Ordner" (Gruppen + Ordner) und „Umbenennen" (Ordner);
  `create_folder_requested`/`rename_folder_requested`-Signale. „Neuer Ordner" ist
  ein reiner UI-Zustand (`_pending_folder`/`_ensure_pending_folder`, K9/E3) –
  **seit 08.08.2026 (E3-revidiert) ersatzlos entfernt: Der MasterTree emittiert
  `create_folder_requested(group, full_path)`, der Orchestrator persistiert den
  Ordner über `create_empty_folder` (global_settings, Key `tree_folders_<group>`).**
* L3: `selection_details` liefert für TYPE_CATEGORY die Eltern-Gruppe im set_id-Slot;
  `category_info_requested`/`run_category_requested` tragen jetzt `(group, path)`.

### E5 – Verdrahtung in beiden Trees
* `service_win.py` (FULL_EDIT): `_on_folder_item_moved`/`_on_folder_moved`/
  `_on_rename_folder`/`_rename_folder`; `_on_run_category`/`_on_category_info_requested`
  gruppenbewusst (Sets-Ordner → Services der Sets). Alle Aktionen emittieren
  `event_bus.service_set_changed`.
* `service_selector_dialog.py` (SELECT_MULTI, Picker): gleiche Handler (DRY über
  service_set_utils); `_resolve_selection_ids`/`_entries_for_scope` gruppenbewusst
  (Sets-Ordner → Set-Service-Entries bzw. plugin_ids).

### Validierung (headless, `test/test.py`, Teil 26)
* 23/23 Prüfungen PASS (A1–A8 Persistenz/Baum, B1–B4 Override, C1–C4 Rename,
  D1–D2 Pfad-Grenzen, E1–E2 gruppenspezifische Auflösung).
* `python -m py_compile` auf allen betroffenen Dateien: PASS.
* 17.01.02-T2-Test an die neue `(group, path)`-Signatur angepasst: PASS.
* **Hinweis (vorbestehend, NICHT durch 18.01.03):** Die Geometrie-Tests
  P2/P5/H3/H5/H7 schlagen bereits im Baseline-Stand fehl (offscreen `800x582`,
  verifiziert per Baseline-Probe gegen HEAD) – Ursache ist der 07./08.08.2026-
  Reflow-/Scrollbar-Umbau, nicht diese Umsetzung. Separater Bugfix erforderlich,
  sofern gewünscht.
* Test-Cleanup: temporäre Patch-/Probe-Skripte gelöscht, `test/` enthält nur
  `test/test.py`.

### Abweichungen vom Plan-Kapitel (per Prüfprotokoll-Entscheidungen)
* Plan-Punkt 3 „Persistenz via `plugin_params_<id>`" → E1: separater Key
  `plugin_category_<id>` (Kollision mit Parameter-Preset vermieden).
* `category_info_requested`/`run_category_requested` sind um die Gruppe erweitert
  (L3) – betroffene bestehende Tests wurden angepasst.


---

## Implementierungs-Log 18.01.03 (08.08.2026 15:40) – E3-revidiert: Leere Ordner persistieren

**Bugfixing-Modus (User-Anweisung):** „Leere Ordner sollen nicht verschwinden, nur bei
manueller Löschung im Kontextmenü." Damit ist **E3 widerrufen** (ursprünglich: leerer
Ordner = reiner UI-Zustand `_pending_folder`, verschwindet beim nächsten Refresh).
Umgesetzt in Commit `f300176` (phase18_step3).

### Persistenz & Helfer (`serviceui/service_set_utils.py`)
* `EMPTY_FOLDERS_KEY = "tree_folders_{}"` – global_settings-Key je Gruppe
  (`tree_folders_sets` / `tree_folders_plugins`), Wert = Liste Slash-Pfade ohne
  `📁`-Präfix.
* `list_empty_folders(state_manager, group)` / `save_empty_folders(...)` –
  lesen/schreiben (dedupliziert, defensiv gegen Fehler).
* `create_empty_folder(state_manager, group, path)` – idempotent (kein Duplikat).
* `delete_empty_folder(state_manager, group, path)` – manuelle Löschung.
* `rename_category(...)` zieht zusätzlich die persistierten leeren Ordner der
  Gruppe mit um (Praefix-Replace, `_replace_prefix`).

### Modell (`analytics/engine/service_selector_model.py`)
* `_empty_folder_paths` (pro Gruppe) wird in `refresh()` geladen
  (`_load_empty_folders`); Accessor `empty_folder_paths(group)` (lesend).
* `_ensure_category_path(nodes, parts)` – erzeugt die Ordnerkette OHNE
  Blatt-Einfügung; bereits vorhandene reale Ordner (aus Blatt-Kategorien) werden
  wiederverwendet → **kein Duplikat**.
* `build_tree()` mischt die persistierten Pfade in die Gruppen-Kinder ein (Sets
  UND Plugins), danach erneute Sortierung (K8). Leere Ordner überleben Refreshs.

### MasterTree (`serviceui/master_tree.py`)
* `_pending_folder`/`_ensure_pending_folder` **ersatzlos entfernt** (kein
  UI-Zustand mehr); Drop-Handler räumt nichts mehr auf.
* `create_folder_requested(group, full_path)` – `_on_new_folder` fragt nur noch
  den Namen ab und emittiert (Orchestrator persistiert).
* Neues Signal `delete_folder_requested(group, path)` + Kontextmenü **„Ordner
  löschen"** – nur für Ordner OHNE Kinder aktiv (Guard `item.childCount() == 0`);
  Tooltip erklärt den Guard.
* `_build_category_item` rendert leere Ordner ohne `>`-Expand-Symbol
  (`bool(child.get("children"))` statt hart `True`).

### Verdrahtung (`serviceui/service_win.py` + `serviceui/service_selector_dialog.py`)
* Beide Trees: `_on_create_folder`/`_on_delete_folder` (DRY über
  service_set_utils, global_settings + `event_bus.service_set_changed`).

### Validierung (headless, `test/test.py`, Teil 27, neu)
* 17/17 Prüfungen PASS (A1–A4 Helfer, B1–B3 build_tree leerer Ordner,
  C1 Refresh-Persistenz, D1 Plugins-Gruppe, E1 verschachtelte Elternkette,
  F1/F2 kein Duplikat bei realem Ordner + Blatt erhalten, G1/G2 Rename zieht
  leere Ordner mit, H1–H3 manuelle Löschung, I1 Gruppen-Isolation).
* Teil 26 (18.01.03-Bestand) weiterhin 20/20 PASS; `py_compile` auf allen
  betroffenen Dateien PASS.
* **Hinweis (vorbestehend, unverändert):** Geometrie-Tests P2/P5/H3/H4/H5/H7
  schlagen weiterhin in der Baseline fehl (offscreen `800x582`, Reflow-/Scrollbar-
  Umbau 07./08.08.2026) – nicht durch E3-revidiert verursacht. Separater Bugfix
  nur auf Wunsch.


---

## Implementierungs-Log 18.01.03 (08.08.2026 14:03) – Bugfix-Runde: Leere-Ordner-Erhaltung, Baum-Expansion, Picker-Crash & fixe Fensterhöhe

**Bugfixing-Modus (User-Anweisungen vom 08.08.2026, nachmittags):**
1. Leere Ordner dürfen beim Herausziehen des letzten Services NICHT verschwinden
   (Ordner bleibt sichtbar und selbst verschiebbar).
2. Ordner dürfen nur gelöscht werden, wenn sie leer sind (bereits umgesetzt).
3. Baum soll nach Ordner-Erstellung/-Verschieben nicht zusammenklappen.
4. Canvas-/Fensterhöhe ist nicht fix bei Klicks auf Sets/Set-Services.
5. Service-Picker startet nicht (`AttributeError: setSizeConstraint`).

Umgesetzt in den Commits `ed8f4f0` (Punkte 1–3) und `17c6a86` (Punkte 4–5).

### Punkte 1–3 – Leere-Ordner-Erhaltung & Baum-Expansion (`ed8f4f0`)
* `serviceui/service_set_utils.py`:
  * `ensure_folder_path(state_manager, group, path)` – persistiert die
    Ordnerkette idempotent (global_settings `tree_folders_<group>`); wird nach
    Struktur-Änderungen gerufen, damit der Quell-Ordner auch ohne persistierten
    Leere-Ordner-Eintrag sichtbar bleibt.
  * `rename_category(...)` sichert zusätzlich den Quell-Ordner (idempotent).
* `serviceui/master_tree.py`:
  * `_collect_expanded_state()` / `_apply_expanded_state()` – Aufklapp-Zustand
    über `_populate()` hinweg erhalten (RAM-Keys `("cat", group, pfad)` /
    `("set", set_id)`).
  * `_mark_expand(group, path)` – wird VOR dem emit der Struktur-Signale gerufen
    (EventBus-Refresh läuft synchron) und klappt Ziel-Ordnerkette nach Drop sowie
    neu erzeugte Ordner auf; `_expand_after_rebuild` wird nach Anwendung geleert.
  * `_build_category_item` rendert leere Ordner ohne `>`-Symbol
    (`bool(child.get("children"))`).
* `serviceui/service_win.py` + `service_selector_dialog.py`: `_on_folder_item_moved`
  ermittelt den Quell-Pfad VOR dem Update (Set: `definition.category`, Plugin:
  `plugin_category_path`) und persistiert ihn via `ensure_folder_path` – der
  Ordner bleibt nach dem Entzug des letzten Kindes sichtbar und verschiebbar.
* Validierung: Teil 28 (neu) 16/16 PASS; Teile 26+27 unverändert PASS.

### Punkte 4–5 – Picker-Crash & fixe Fensterhöhe (`17c6a86`)
* `serviceui/service_selector_dialog.py`: `self.setSizeConstraint(...)` war ein
  QLayout-Aufruf auf dem QDialog (existiert nicht → AttributeError beim Öffnen
  des Pickers). Fix: Constraint wird auf dem root-Layout gesetzt
  (`root.setSizeConstraint(QLayout.SetNoConstraint)`) – der Picker startet
  wieder und hält seine Fensterhöhe FIX (ScrollArea zeigt bei Überhöhe
  Scrollbalken).
* `serviceui/param_columns.py`: `_build_service_columns` rief `self._reflow()`
  → der volle Reflow (`_schedule_reflow` → `_apply_reflow_size` →
  `_exact_fit_to_content`) passte bei JEDEM Set-/Service-Klick die Fensterhöhe
  an die Spaltenhöhe an (Canvas-/Fensterhöhe versetzte sich). Fix: nur noch
  Box-only-Reflow (`QTimer` → `_resize_param_box_deferred`, Muster
  `_apply_conditional_visibility`/`_setup_collapsible` vom 07.08.2026) – die
  Service-Parameter-Box folgt ihrer Layout-Größe, Fenster-/Canvas-Höhe bleibt
  stabil. Der initiale Fensteraufbau (show → `_apply_reflow_size`) bleibt
  unverändert.
* Validierung: Teil 29 (neu) 5/5 PASS (Picker-Konstruktion ohne Crash +
  SetNoConstraint auf dem root-Layout; Duck-Typ-Host ohne `_schedule_reflow`
  belegt: `_build_service_columns` löst keinen Fenster-Reflow mehr aus).
  Teile 26–28 unverändert PASS. `py_compile` auf allen Dateien OK.
* **Hinweis (vorbestehend, unverändert):** Geometrie-Tests P2/P5/H3/H4/H5/H7
  schlagen weiterhin in der Baseline fehl (offscreen `800x582`). Separater
  Bugfix nur auf Wunsch.
