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
