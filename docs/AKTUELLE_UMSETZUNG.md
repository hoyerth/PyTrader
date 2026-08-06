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
 - **Git:** Commit `2579410` (mit der 15.03-E-NACHZUG-Umsetzung, 11 Dateien).

 ### 06.08.2026 – Bugfix-Runde 2 Datenquellen-Dialog (Punkte 1–6)

 **User-Anweisung (6 Punkte):**
 1. Parameter-Box zeigt nur die Parameter **eines einzigen Sets/Services**
    (abhängig vom letzten Mausklick) – soll ALLE angehakten Services zeigen.
 2. Box zeigt nie alle geklickten Service-Parameter – es zählt der
    **Zeilen-Klick**, nicht die **Checkbox**.
 3. Beim manuellen Vergrößern behält der Tree seine **feste Default-Breite**;
    nur die Parameter-Box wächst mit (bzw. schrumpft bis Minimum =
    2 Service-Parameter nebeneinander).
 4. Breite des Trees ist **fix**.
 5. Limit-Feld ist **reine Texteingabe** (keine Up/Down-Pfeile); Default =
    Statistik-Signale aus den App-Optionen.
 6. Bei Set-Auswahl: Parameter der enthaltenen Services **nebeneinander**,
    wie im `service_win`.

 **Ursache Punkte 1/2/6 (gefunden & behoben):**
 - `serviceui/master_tree.py` `_on_item_changed` verarbeitete **jedes**
   `itemChanged`-Signal – auch das vom Zeilen-Klick (Auf-/Zuklappen via
   `_refresh_expand_label`) ausgelöste Text-Refresh – und entfernte dabei
   fälschlich die Haken (bzw. ließ nur den zuletzt geklickten Eintrag stehen).
 - **Fix:** `_on_item_changed` verarbeitet nur **echte Checkbox-Wechsel**:
   Vergleich `state == expected` aus `_checked_items` (Service-/Plugin-Zeile)
   bzw. neuer `_derive_set_state()` (Set-Zeile). Der Zeilen-Klick ändert die
   Haken nicht mehr; das Panel zeigt alle angehakten Set-Services
   nebeneinander (service_win-Muster, Punkt 6).

 **Umsetzung (06.08.2026, ausgeführt):**
 - `serviceui/master_tree.py` (Punkte 1/2/6):
   * `_on_item_changed` nur noch bei Checkbox-Zustandswechsel
     (`_derive_set_state()` für Set-Knoten, erwarteter Zustand aus
     `_checked_items` für Blätter); `_refresh_expand_label`-bedingte
     Text-Refreshes werden ignoriert.
   * `_apply_set_state` behält die Tri-State-Logik (alle/nur Teil-Services).
 - `serviceui/service_selector_dialog.py` (Punkte 3/4):
   * `TREE_DEFAULT_WIDTH = 300`; `self.selector.setFixedWidth(TREE_DEFAULT_WIDTH)`
     + `body.addWidget(self.selector, 0)` → Tree bleibt exakt fix, der
     5-Anteil des Body-Stretch wächst allein der Parameter-Box zu.
   * `_apply_panel_size`: `setFixedWidth` → `setMinimumWidth` (Panel wächst
     mit dem Fenster, schrumpft aber nie unter 2-Spalten-Minimum);
     `_panel_fixed_width` → `_panel_min_width`; `_fit_dialog_width` und
     Geometrie-Restore darauf abgestimmt.
 - `analytics/ui/analytics_win.py` (Punkt 5):
   * `QSpinBox` → `QLineEdit` (`edit_limit`) – keine Up/Down-Pfeile mehr.
   * Default im `__init__` aus `state_manager.get_app_settings()`
     (`statistics_signal_limit`, 10.000) → `_default_limit`;
     `_wire_controls` setzt `self._vm.set_limit(self._default_limit)`.
   * Neuer Slot `_on_limit_text_changed` (int-Parsing, leere/ungültige
     Eingabe → kein Update); `edit_limit.textChanged` verdrahtet.
   * `_on_active_profile_changed` synchronisiert `edit_limit` aus `vm.params`
     beim Profilwechsel; `QSpinBox`-Import entfernt.
 - **Verifikation:** `test/check_p15_s3_analytics.py` erweitert um C1–C8
   (Zeilen-Klick entfernt keine Haken; Panel zeigt alle Set-Services; Tree
   fix; Vergrößern → Panel wächst; Verkleinern → 2-Spalten-Minimum; QLineEdit
   ohne Pfeile; Default 10.000; Texteingabe → ViewModel) → **60/60 PASS**.
   B6/B7 angepasst (`resize(1400, 444)` – Größe wird auf Tree+Minimum geklemmt).
   Regression `check_p15_s2_service_tree.py`, `check_p15_s4_infra.py`,
   `check_service_run_fixes.py` OK. `py_compile` auf allen geänderten
   Dateien. Keine UI-/Regressionstests (harte Regel).
 - **Git:** Commit `b62d3ed`.

 ### 06.08.2026 – Bugfix-Runde 3 Datenquellen-Dialog (Punkte 1–7 + Stretch-Nachtrag)

 **User-Anweisung (7 Punkte):**
 1. **NICHT** alle gewählten Services in der Parameter-Box anzeigen.
 2. Die Wahl, welche Services angezeigt werden, hängt **NICHT von den
    Checkboxen** ab.
 3. Die Wahl der angezeigten Parameter hängt vom **einfachen Mausklick im
    Baum** ab (Mausklick beliebig in einer Tree-Zeile).
 4. Mausklick auf eine **Set-Zeile** → die Services des Sets werden in der
    Parameter-Box angezeigt.
 5. Mausklick auf eine **Service-Zeile in einem Set** → ebenfalls die
    Services des Sets.
 6. Mausklick auf eine **Service-Zeile unter ⚡ Standalone / 📦 Plugins** →
    nur dieser eine Service.
 7. Alle anderen Zeilen → **KEIN Service** in der Parameter-Box (analog zur
    Implementierung im `service_win`).
 **Nachtrag (User):** Die einzelnen Service-Rahmen sollen in der
 Parameter-Box **nicht gestreckt** werden, sondern ihre **Default-Breite**
 behalten.

 **Umsetzung (06.08.2026, ausgeführt):**
 - `serviceui/master_tree.py`:
   * Neues Signal **`selection_details(node_type, set_id, service_id,
     plugin_id)`** – Klick-Scope der geklickten Zeile.
   * `mousePressEvent` emittiert es bei **JEDEM** Mausklick auf eine gültige
     Zeile (auch Checkbox-Zone / Expand-Toggle, unabhängig von der Qt-
     Selektion – ein Klick auf eine bereits selektierte Zeile feuert sonst
     kein `itemSelectionChanged`). Neue Methode `_emit_selection_details`
     (liest die Rollen der Zeile; Plugin-Zeilen ohne set_id, Gruppen nur
     node_type).
 - `serviceui/service_selector_dialog.py`:
   * **`checked_changed`-Verbindung entfernt** – das Read-Only-Panel ist
     vollständig klick-basiert (Checkboxen bestimmen weiterhin nur den
     Analytics-Filter `feature_ids`).
   * Neu `_on_tree_selection_details(...)` + `_entries_for_scope(...)`:
     Set-Zeile ODER Service-in-Set → ALLE Services des Sets (Punkt 4+5,
     service_win-Muster `_on_master_selection`); Plugin-Zeile → NUR dieser
     Service (Punkt 6); sonst leer (Punkt 7).
   * `_last_scope` bleibt über Modell-Refreshes erhalten
     (`_on_model_data_changed` zieht das Panel mit dem zuletzt geklickten
     Scope nach); `_on_clear_filters` leert das Panel.
   * **Stretch-Nachtrag:** `_rebuild_param_panel` hängt abschließend
     `param_box_layout.addStretch(1)` an (in beiden Zweigen) – ohne den
     Stretch verteilt `QHBoxLayout` den freien Platz beim Vergrößern
     gleichmäßig auf alle Spalten (Stretch-Faktor 0 = Ueberschuss-
     Verteilung); der Stretch (Faktor 1) absorbiert ihn → die Service-
     Rahmen behalten ihre Default-Breite (sizeHint), linksbündig.
 - **Verifikation:** `test/check_p15_s3_analytics.py` umgestellt/erweitert
   (D5/D8/C2 klick-basiert mit echter `QMouseEvent`-Simulation auf die
   Zeile; neu C9–C13: Service-in-Set → alle Set-Services, Plugin-Zeile →
   nur dieser, Gruppe → leer, Checkbox-Wechsel ändert Panel NICHT, Klick
   ändert feature_ids NICHT; neu C14: Rahmen behalten Default-Breite nach
   Vergrößern; `_panel_widgets()`-Helper filtert Stretch-Items) → **66/66
   PASS**. Regression `check_p15_s2_service_tree.py`, `check_p15_s4_infra.py`
   OK. `py_compile` auf allen geänderten Dateien. Keine UI-/
   Regressionstests (harte Regel).
 - **Git:** Commit folgt (siehe unten).

### 06.08.2026 – Phase 16: Rollen- und Namens-Klarheit Grid-Indikator (Ind_FixedGridProximity)

**Entscheidungen (vorab, User):**
- .backup_grid_liquidity/ (Alt-Datei nalytics/features/definitions/grid_liquidity.py) wird vollständig gelöscht – keine Verwechslung beim Plugin-Loader.
- Vollständige Umbenennung (Nutzer-Entscheidung): indicator_id grid_liquidity → ind_fixed_grid_proximity inkl. Migration für gespeicherte Window-States/Presets, Klassen-/Modul-Rename (GridLiquidityIndicator → FixedGridProximityIndicator, grid_liquidity.py → ixed_grid_proximity.py).
- Rollen-Trennung: proximity = nur mathematische Abstandsberechnung; grid_lines = nur Raster-Generierung; Ind_FixedGridProximity = Indikator-Name (UI-Container).

**Umsetzung (06.08.2026, ausgeführt):**
- **Gelöscht:** .backup_grid_liquidity/ (gitignored, Alt-Ablage).
- **Umbenannt:** chart/indicators/grid_liquidity.py → chart/indicators/fixed_grid_proximity.py; Klasse GridLiquidityIndicator → FixedGridProximityIndicator; indicator_id/plugin_id/_plugin_id grid_liquidity → ind_fixed_grid_proximity; display_name → Ind_FixedGridProximity; interne Schema-Konstanten _GRID_LIQUIDITY_SCHEMA/_ORDER → _FIXED_GRID_PROXIMITY_SCHEMA/_ORDER; interne set_id grid_liquidity_internal → ind_fixed_grid_proximity_internal.
- **Geändert:** grid_lines_service.py + proximity_service.py – metadata['indicator_name'] → Ind_FixedGridProximity, metadata['indicator_id'] → ind_fixed_grid_proximity (MasterTree-Badges/Tooltips).
- **Geändert:** chart_win.py – Import/Registry-Key ind_fixed_grid_proximity, Methoden-/Kommentar-Rename, **Runtime-Normalisierung** _normalize_indicators_state() (Legacy-Key grid_liquidity → neu) an allen Load-Pfaden (__init__, on_symbol_changed, on_tf_changed).
- **Geändert:** state_manager.py – idempotente **DB-Migration** in _init_db(): indicator_presets.indicator_id UPDATE + indicators_state-JSON-Remap in instance_states/symbol_tf_states.
- **Geändert:** service_selector_model.py (Import/Instantierung/Referenzen), indicator_dialog.py, master_tree.py, service_set_utils.py, grid_math.py, description_dialog.py, chart/indicators/__init__.py (Kommentare/Referenzen).
- **Tests:** 	est/check_p16_rename_migration.py (neu, M1–M6 PASS), check_p15_s4_infra.py (PASS), check_p15_s2_service_tree.py (PASS, A5b/C4-Assertions an Substring-Logik angepasst), check_service_run_fixes.py (PASS), 	est/test.py Teil 4 (C1–C5 PASS; Teil-1/3-Geometrie-Fehler vorbestehend/unabhängig).
- **Verifikation:** py_compile auf allen geänderten Dateien; keine UI-/Regressionstests (harte Regel).
- **Git:** Commit folgt nach Freigabe (nicht ohne expliziten Startschuss).

### 06.08.2026 – Phase 16 NACHZUG: Alte Tests entfernt + Commit/Push

**Umsetzung (06.08.2026, ausgeführt):**
- **Gelöscht:** `test/migrate_grid_liquidity.py` – obsoletes, einmaliges
  Migrations-/Verifikationsskript fuer das Alt-Plugin 'grid_liquidity'
  (referenzierte entfernte/umbenannte Pfade). Die Migration laeuft seit
  Phase 16 idempotent in `StateManager._init_db()` und ist durch
  `test/check_p16_rename_migration.py` abgedeckt.
- **Geändert:** `test/check_chart_data.py` – veraltete
  feature_store-Query (`feature_id='grid_liquidity'`) auf die aktive
  Plugin-ID `grid_lines` umgestellt.
- **Geändert:** `test/check_p15_s2_service_tree.py` – Kommentar-Referenz
  auf Phase-16-Rename aktualisiert.
- **Verifikation:** py_compile + gezielte Backend-Checks (keine UI-/
  Regressionstests, harte Regel).
- **Git:** Commit + Push (siehe unten, Commit-Kennung wird nach Ausfuehrung ergänzt).

