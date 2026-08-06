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

 # TASK: Phase 15.03-E – Popover-ServiceSelector im AnalyticsWindow (ÜBERARBEITET 06.08.2026)

 > **Ist-Analyse 06.08.2026 (Code-konsistente Korrektur):**
 > Der Ursprungsentwurf referenzierte ein nicht existentes `SelectorMode`-Enum,
 > einen `MasterTree` im `SELECT_ONLY`-Modus und eine `ParameterPanel`-Klasse
 > (entfernt, `.backup_parameter_panel` leer). Real:
 > * `ServiceSelectorWidget.MODE_SELECT_ONLY` (String-Konstante) baut eine
 >   KOMPAKTE DROPDOWN-Zeile (Set-Combo + Service-Combo), KEINEN Tree.
 > * Parameter-Anzeige baut `ServiceParamColumnsMixin._build_service_column()`
 >   (eine QGroupBox-Spalte je Service) – es gibt keine `set_service()`-API.
 > * `AnalyticsWindow` hat BEREITS ein Feature-Filter-Dropdown (`combo_feature`).
 > **Entscheidung (User, 06.08.2026):** Das Popover ERSETZT `combo_feature` –
 > keine Doppelsteuerung von `AnalyticsViewModel.set_feature_id()`.

 Bitte binde das `ServiceSelectorWidget` (Modus `MODE_SELECT_ONLY`) als
 platzsparendes Top-Bar-Popover im `AnalyticsWindow` (`analytics/ui/analytics_win.py`)
 ein und ersetze das bestehende Feature-Filter-Dropdown:

 ---

 ### 1. Top-Bar Popover Button (ersetzt `combo_feature`)
 1. **Button-Platzierung (`analytics/ui/analytics_win.py`, Filter-Zeile):**
    - Ersetze das bestehende `combo_feature`-Dropdown durch einen Popover-Button:
      `[ Set/Service: ▾ Keiner ausgewählt ]`
    - Die bisherigen Slots `_on_feature_changed()` / `_populate_feature_combo()`
      entfallen (Redundanz, Entscheidung 06.08.2026). Die Verkabelung
      `combo_feature.currentIndexChanged → set_feature_id` wird durch das
      Popover übernommen.
 2. **Flyout/Popover-Widget:**
    - Klick auf den Button öffnet ein schwebendes Popover direkt unter dem Button.
    - Inhalt (manuell anpassbar – Variante „minimal-invasiv"):
      * **Oben:** `ServiceSelectorWidget` im Modus `MODE_SELECT_ONLY`
        (Set-/Service-Combos), Signale `selection_changed(set_id, service_id)`.
      * **Unten:** Read-Only-Parameteranzeige für den gewählten Service über
        `ServiceParamColumnsMixin._build_service_column(iid, pid, cfg)` in einem
        deaktivierten `QGroupBox`-Container (`setEnabled(False)`).
    - Alternativ (falls gewünscht): Read-Only-`MasterTree` statt Combos – dann
      muss ein neues Widget gebaut werden (nicht Teil dieses minimal-invasiven
      Tasks).
    - Enthält den Aktions-Button `[ 🗑️ Aktiven Service-Filter entfernen ]`.

 ---

 ### 2. Inspektion, Filter-Entfernung & Sicherheitsabfrage
 1. **Parameter-Inspektion im Popover:**
    - `selection_changed(set_id, service_id)` lädt die rechte Parameteranzeige:python
      cfg = self.model.find_service(setid, serviceid) or {}
      pid = cfg.get("pluginid") or serviceid
      box = self.buildservicecolumn(serviceid, pid, cfg)   # ServiceParamColumnsMixin
      box.setEnabled(False)                                    # Read-Only
      2. **feature_id-Auflösung (Lücke im Ursprungsentwurf):**
    - Das Widget-Signal liefert `set_id`/`service_id`, NICHT die `feature_id`.
    - Auflösung über das Modell: `plugin_id = model.find_service(set_id, service_id).get("plugin_id")`
    - Dann `AnalyticsViewModel.set_feature_id(plugin_id)` – der `feature_id` im
      Feature-Store IST die `plugin_id` (grid_lines / proximity).
 3. **Aktion "Service-Filter entfernen" + Sicherheitsabfrage:**
    - **Niemals automatisch alle Services vermischen!** (einzelner `feature_id`)
    - Vor dem Entfernen modale Abfrage (`QMessageBox.question`):
      > *"Möchtest du den aktiven Service-Filter wirklich entfernen? Die Anzeige
      > im Analytics-Fenster zeigt danach wieder alle Features."*
      (Korrektur: `set_feature_id(None)` entfernt den Filter → ALLE Feature-Rows
      sichtbar, kein „leeres Raster".)
    - Bei Bestätigung: `AnalyticsViewModel.set_feature_id(None)`, Popover
      schließen, Button-Text auf `[ Set/Service: ▾ Keiner ausgewählt ]`.
 4. **Button-Text & Profil-Persistenz:**
    - Der Button-Text zeigt den aktiven Filter: `[ Set/Service: ▾ <plugin_id> ]`
      bzw. `[ Set/Service: ▾ <set_id>/<service_id> ]` (manuell anpassbar).
    - `feature_id` wird über `AnalyticsViewModel._current_payload()` bereits im
      Profil-Payload persistiert (dict(self._params) inkl. feature_id) ✔.
    - Bei Profilwechsel übernimmt `_apply_profile()` die Profil-Parameter inkl.
      `feature_id` in den VM ✔ – der Button-Text muss danach synchronisiert
      werden (z. B. im `active_profile_changed`-Slot oder über
      `event_bus.profile_changed`).

 ---

 ### 3. EventBus-Integration
 - `event_bus.service_set_changed` → `ServiceSelectorModel.data_changed` →
   Popover-Refresh (besteht, ServiceSelectorWidget verbindet das Modell).
 - `event_bus.profile_changed` → Button-Text mit dem gespeicherten
   `feature_id`-Filter aktualisieren (NEU zu verdrahten im AnalyticsWindow).

 ---

 ### 4. Headless Verification (`test/check_p15_s3_e_popover.py` – NEU)
 - Testet ohne GUI-Start (offscreen/Temp-DB unter test/):
   1. `selection_changed(set_id, service_id)` → Auflösung der plugin_id →
      `AnalyticsViewModel.set_feature_id()` wird gerufen.
   2. `FeatureStoreReader.fetch_rows(..., feature_id=...)` filtert korrekt.
   3. Entfernen-Logik setzt `feature_id = None` zurück (Button-Text-Reset).
   4. `event_bus.service_set_changed` aktualisiert das `ServiceSelectorModel`.
   5. `combo_feature` existiert NICHT mehr (Ersetzungs-Entscheidung).

 ---

 ### ⚠️ Richtlinien
 - **Keine UI-Tests starten!** Verifikation ausschließlich über Headless-Checks
   in `test/` und `py_compile`.
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
