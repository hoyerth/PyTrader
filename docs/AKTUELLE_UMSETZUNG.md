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
| E-3 | `schema_version` Pflichtfeld | Pflichtfeld im `FeatureStorePayload`; alte `feature_store`-Rows erhalten beim Lesen den Default `"1.0.0"` (harmonisiert am 06.08.2026) |
| E-4 | Schutzregel Grid-Liquidity | Schutz für `../../chart/indicators/grid_liquidity.py` aufgehoben; Anpassungen erlaubt, wenn der Fallback-Abbau sie erfordert |
| E-5 | Zeilenzahl `service_win.py` | Doku-Korrektur: 864 Zeilen (statt 1.400) |
| E-6 | Pfad-Konvention | Dateien werden einheitlich vom Projekt-Root referenziert (ohne `../..`) |

---

 # TASK: Phase 15.03-E – Wiederverwendbare Service-Auswahl im AnalyticsWindow (Multi-Select & Popover)

Bitte ersetze die alten Analytics-Dropdowns durch die Wiederverwendung des bestehenden `ServiceSelectorWidget` im Popover/Dialog-Modus:

---

### 1. Erstellung `ServiceSelectorDialog` (`serviceui/service_selector_dialog.py`)
1. **Wiederverwendung des bestehenden Widgets:**
   - Erstelle eine Dialog/Popover-Klasse `ServiceSelectorDialog(QDialog)`, die das bereits existierende `ServiceSelectorWidget` einbettet (DRY-Prinzip).
   - Konfiguriere das `ServiceSelectorWidget` im Modus `SELECT_MULTI`:
     * **Links:** `MasterTree` mit **Checkboxes (`[x]`)** an allen Set- und Service-Knoten.
     * **Rechts:** `ParameterPanel` im Read-Only-Modus (`setEnabled(False)`).
2. **Aktions-Zeile unten im Dialog:**
   - `[ 🗑️ Aktive Filter entfernen ]`: Zeigt modale Sicherheitsabfrage (`QMessageBox.question`), setzt alle Checkboxes zurück und emittiert eine leere Auswahl.
   - `[ 💾 Anwenden & Schließen ]`: Emittiert das Signal `services_selected(display_names, feature_ids)`.
     * `display_names`: Liste der lesbaren Namen für die Button-Anzeige (z.B. `["Mein Scalper", "RSI"]`).
     * `feature_ids`: Liste der technischen IDs für die SQL-Abfrage (z.B. `["prox_1", "rsi_14"]`).

---

### 2. Einbindung in `AnalyticsWindow` (`analytics/ui/analytics_win.py`)
1. **Entfernen alter Dropdowns:**
   - Lösche alle verbliebenen Alt-Dropdowns für Services/Sets aus `analytics_win.py` und den Subseiten.
2. **Top-Bar Button (Die Anzeige):**
   - Platziere in der Top-Bar den Button: `[ 🛠️ Datenquellen: Keiner ausgewählt ▾ ]`.
   - Klick auf den Button öffnet den `ServiceSelectorDialog`.
   - Wenn der Dialog `services_selected` emittiert, wird der Button-Text mit den `display_names` aktualisiert (z. B. `[ 🛠️ Datenquellen: Mein Scalper, RSI ▾ ]`).
3. **ViewModel-Anbindung (Die Logik):**
   - Verdrahte das Signal mit `AnalyticsViewModel.set_feature_ids(feature_ids)`.
   - Das ViewModel reicht diese IDs an den `FeatureStoreReader` weiter, der die Charts via SQL-Query (`WHERE feature_id IN (...)`) filtert.
   - Der Dialog hört auf `event_bus.service_set_changed` und hält den Baum automatisch aktuell.

---

### 3. Headless Verification (`test/check_p15_s3_analytics.py`)
- Testet ohne GUI-Start (offscreen/Temp-DB):
  1. `AnalyticsViewModel.set_feature_ids(["prox_1", "rsi_14"])` setzt die Multi-Auswahl.
  2. `FeatureStoreReader.fetch_rows(..., feature_ids=[...])` filtert per `WHERE feature_id IN (...)`.
  3. Dialog-Filter-Zurücksetzung setzt `feature_ids = []` sauber zurück.

---

### ⚠️ Richtlinien
- **Keine UI-Tests starten!** Verifikation ausschließlich über Headless-Checks in `test/` und `py_compile`.
- Erzeuge gezielte, saubere Code-Snippets/Patches.

---

 ## Implementierungs-Log (Taxonomie: Phase 15.03-E)

 ### 06.08.2026 – 15.03-E Popover-ServiceSelector im AnalyticsWindow

 **Entscheidungen (vorab, User):**
 - Popover ERSETZT das bestehende `combo_feature`-Dropdown – keine
   Doppelsteuerung von `AnalyticsViewModel.set_feature_id()`.
 - Minimal-invasiver Aufbau: `ServiceSelectorWidget` im Modus
   `MODE_SELECT_ONLY` (Set/Service-Combos) + Read-Only-Parameteranzeige über
   `ServiceParamColumnsMixin._build_service_column()` (deaktivierte QGroupBox).
   Kein neues Popover-Widget, kein MasterTree.

 **Korrekturen am Ursprungsentwurf (Ist-Analyse 06.08.2026):**
 - `SelectorMode.SELECT_ONLY` → real `ServiceSelectorWidget.MODE_SELECT_ONLY`.
 - `parameter_panel.set_service(...)` → real `_build_service_column(iid, pid, cfg)`
   (ParameterPanel-Klasse existiert nicht mehr).
 - feature_id-Auflösung ergänzt: `selection_changed` liefert set_id/service_id,
   die plugin_id wird via `model.find_service(...)` aufgelöst.
 - Warn-Text präzisiert: `set_feature_id(None)` zeigt ALLE Features (kein
   „leeres Raster").

  **Umsetzung (geplant):** [Hier nach Umsetzung ergänzen: Dateien, Änderungen,
   Test-Ergebnisse, Git-Commit/Tag.]

 **Umsetzung (06.08.2026, ausgeführt):**
 - **Geändert:** `analytics/ui/analytics_win.py`
   * `combo_feature`-Dropdown entfernt (Entscheidung: Popover ersetzt es);
     `_populate_feature_combo()`, `_on_feature_changed()`,
     `_on_vm_data_ready()` und der `QUERY_FEATURES`-Import entfallen.
   * `_initial_load()` fragt keine Feature-Metadaten mehr ab
     (`request_features()` entfernt – speiste nur das alte Dropdown).
   * Neuer Filter-Zeilen-Button `btn_service_filter`
     `[ Set/Service: ▾ Keiner ausgewählt ]` + Popover (`_build_service_popover`):
     `QFrame` mit `Qt.Popup`, oben `ServiceSelectorWidget` (MODE_SELECT_ONLY,
     Set-/Service-Combos), Mitte Read-Only-Parameteranzeige
     (`ServiceParamColumnsMixin._build_service_column()` in deaktivierter
     QGroupBox, `QScrollArea` max. 320 px), unten
     `[ 🗑️ Aktiven Service-Filter entfernen ]`.
   * Neue Methoden: `_toggle_service_popover`, `_restore_popover_selection`,
     `_clear_param_display`, `_build_readonly_param_display`,
     `_on_popover_selection_changed` (plugin_id-Auflösung via
     `model.find_service()` → `vm.set_feature_id(plugin_id)`),
     `_remove_service_filter` (Sicherheitsabfrage, korrigierter Hinweistext:
     „zeigt danach wieder alle Features"), `_sync_service_filter_button`.
   * Button-Text-Sync bei Profilwechsel (`active_profile_changed`) und über
     `event_bus.profile_changed`.
   * Neu: `_ReadOnlyServiceParamHost` (Minimal-Host des
     `ServiceParamColumnsMixin`; Read-Only, alle Editier-Pfade no-op).
   * `AnalyticsWindow.__init__` akzeptiert optional `selector_model`
     (injizierbar für Headless-Tests; Standard `ServiceSelectorModel(parent)`).
 - **Neu:** `test/check_p15_s3_e_popover.py` (headless, Temp-DBs unter `test/`):
   28/28 Prüfungen PASS (P1–P7, S1–S4, R1–R6, X1–X4, F1–F4, E1–E4).
  - **Verifikation:** `.venv\Scripts\python.exe -m py_compile` auf
   `analytics/ui/analytics_win.py` + Testdatei; Testlauf
   `test/check_p15_s3_e_popover.py` → „ALLE PRUEFUNGEN BESTANDEN (OK)".
   Keine UI-/Regressionstests (harte Regel).
 - **Git:** Commit + Tag `phase15_03e` (siehe unten).

 ### 06.08.2026 – 15.03-E NACHZUG: Popover ersetzt durch `ServiceSelectorDialog` (Multi-Select, Checkbox-MasterTree)

 **Entscheidungen (vorab, User):**
 - `feature_ids` = **plugin_ids** (DB-konform; `feature_store.feature_id` IST
   die plugin_id) – NICHT instance_ids wie im Anleitungs-Beispiel
   `["prox_1","rsi_14"]`.
 - Rechtes Panel = Read-Only-"Service-Parameter"-Box aus
   `ServiceParamColumnsMixin._build_service_column()` (deaktivierte QGroupBox
   je angehakten Service, gestapelt); alle angehakten Services inkl.
   ⚡ Standalone-/📦 Plugin-Zeilen.
 - Neue Testdatei `test/check_p15_s3_analytics.py`; die alte
   `check_p15_s3_e_popover.py` wird gelöscht.

 **Umsetzung (06.08.2026, ausgeführt):**
 - **Neu:** `serviceui/service_selector_dialog.py` – `ServiceSelectorDialog`
   (QDialog, `services_selected(display_names, feature_ids)`), links
   `ServiceSelectorWidget.MODE_SELECT_MULTI` (Checkbox-MasterTree), rechts
   Read-Only-Panel (`_DialogParamHost`, `setEnabled(False)`), unten
   `[ 🗑️ Aktive Filter entfernen ]` (Sicherheitsabfrage) +
   `[ 💾 Anwenden & Schließen ]`; lazy am AnalyticsWindow, `WA_DeleteOnClose`.
 - **Geändert:** `serviceui/master_tree.py` – Checkbox-Modus (`set_checkable`,
   Tri-State, `_checked_items`-Persistenz über `_populate`,
   `checked_changed`-Signal, `checked_services/checked_feature_ids/
   checked_display_names/clear_checks/set_checked_feature_ids`,
   `CHECKBOX_ZONE_WIDTH` im `mousePressEvent`, `_sync_checked_from_tree`,
   `_on_item_changed`, `_apply_set_state`).
 - **Geändert:** `serviceui/service_selector_widget.py` – neuer Modus
   `MODE_SELECT_MULTI` + `_build_select_multi()`.
 - **Geändert:** `analytics/engine/service_selector_model.py` –
   `resolve_display_names(feature_ids)` (Reverse-Mapping → SetName/instance_id).
 - **Geändert:** `analytics/engine/feature_store_reader.py` –
   `feature_ids`-Parameter (IN-Clause via `_apply_feature_filter`; Legacy
   `feature_id` bleibt) in `fetch_rows/fetch_columns/fetch_heatmap/
   fetch_latest_bar_time/fetch_recent_bar_time_for_cell`.
 - **Geändert:** `analytics/engine/analytics_repository.py` (get_table/
   get_heatmap/get_scatter/get_distribution/get_latest_bar_time/
   get_recent_bar_time_for_cell), `analytics_worker.py` (Durchreichung) und
   `analytics_view_model.py` (Param `feature_ids`, `set_feature_ids` + Alias,
   Profil-Migration Alt-`feature_id`-String → Liste, Jump-to-Chart nutzt
   `feature_ids`).
 - **Geändert:** `analytics/ui/analytics_win.py` – Popover/`_active_filter`/
   `_param_host` entfernt; Button `[ 🛠️ Datenquellen: … ▾ ]`, lazy-erzeugter
   Dialog, `_on_services_selected`, `_sync_service_filter_button` mit
   `resolve_display_names`.
 - **Verifikation:** `test/check_p15_s3_analytics.py` (headless, Temp-DBs
   unter `test/`) – **43/43 PASS**; Regression `check_p15_s2_service_tree.py`
   + `check_p15_s4_infra.py` OK. `py_compile` auf allen geänderten Dateien.
   Keine UI-/Regressionstests (harte Regel).
 - **Git:** noch nicht committet (folgt gemeinsam mit der Bugfix-Runde).

 ### 06.08.2026 – Bugfix-Runde Datenquellen-Dialog (Punkte 1–5)

 **User-Anweisung (5 Punkte):**
 1. Services im Parameter-Panel **horizontal nebeneinander** (statt vertikal).
 2. Panel-Default-Breite = Platz für **2 Parameter-Spalten**; bei mehr →
    horizontale Scrollbar.
 3. Fensterbreite endet **exakt an der rechten Kante der Parameter-Box**.
 4. Letzte Fensterposition/-größe von "Datenquellen auswählen" **persistieren
    & beim nächsten Öffnen restaurieren**.
 5. **History-Bug:** Beim Schließen + App schließen + Neustart wird das
    ServiceWindow fälschlich restauriert – soll in diesem Fall NICHT
    wiederhergestellt werden; nur die Position beim manuellen Öffnen.

 **Umsetzung (06.08.2026, ausgeführt):**
 - `serviceui/service_selector_dialog.py`:
   * `param_box_layout` → **QHBoxLayout** (Punkt 1).
   * `_apply_panel_size`: Panel-Breite = 1 Spalte bzw. Default **2 Spalten**
     (Spalten-SizeHints + Spacing + `PANEL_BUFFER`); Container-Minimum = volle
     Inhaltbreite → horizontale Scrollbar (`ScrollBarAsNeeded`) bei >2
     Spalten (Punkt 2).
   * Feste Breite auf dem **Panel-Widget** (`param_panel.setFixedWidth`), nicht
     nur der ScrollArea – sonst schnitt der 2/5-Body-Stretch das Panel ab
     (Overflow). `_fit_dialog_width` misst die rechte Panel-Kante und zieht
     das Fenster nach; `showEvent` + deferred Fit (Punkt 3).
   * `_restore_geometry`/`_save_geometry` + `done()`-Override, Key
     `service_selector` in `global_settings` (Muster
     `IndicatorSettingsDialog`) – Position **und** Größe (Punkt 4).
 - `serviceui/service_win.py`:
   * `_keep_history_on_close = False` → manuelles X löscht den
     `window_instances`-Eintrag (kein Auto-Restore nach Neustart).
   * `save_state()` schreibt zusätzlich
     `save_dialog_geometry("win_service", …)`; `restore_state()` nutzt den
     Fallback auf `get_dialog_geometry("win_service")` → Position überlebt
     das manuelle Schließen und wird beim erneuten Öffnen wiederhergestellt
     (Punkt 5). App-Beenden mit OFFENEM Fenster behält den Eintrag (gewollt).
 - **Verifikation:** `test/check_p15_s3_analytics.py` erweitert um B1–B7
   (QHBoxLayout, 2-Spalten-Default, Scrollbar-Bedingung, exakte Kante,
   Geometrie-Save/Restore) + H1–H5 (History-Fall: delete_instance → kein
   Auto-Restore, Position-Fallback) → **57/57 PASS**. Regression
   `check_p15_s2_service_tree.py`, `check_p15_s4_infra.py`,
   `check_service_run_fixes.py` OK. `py_compile` auf allen geänderten
   Dateien. Keine UI-/Regressionstests (harte Regel).
 - **Git:** Commit folgt (siehe unten).
