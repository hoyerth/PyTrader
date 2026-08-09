# Phase 19: Analytics-Finalisierung

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 19)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase19_step1`, `phase19_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Codebase-Formatierung:** Exakt **4 Leerzeichen** Einrückung (PEP8-Standard) und **exakt 1 Leerzeile** Spacing zwischen Methoden und Funktionsblöcken. Kein Umformatieren unbeteiligter Altbestand-Dateien.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`. `MasterTree`-Selektionen übergeben aufgelöste `feature_ids` direkt an `view_model.set_feature_ids()`.
5. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`db/db_pool.py`) – eine Verbindung pro Thread und DB-Datei. Die Fassade `db_service.py` bleibt als Re-Export-Wrapper für bestehende Caller erhalten.
7. **Tree-Persistenz & Kollisionsschutz (18.01.03):** 
   - Standalone-Service-Parameter nutzen exklusiv `plugin_params_<id>`.
   - Ordner-Kategorie-Overrides für Plugins nutzen exklusiv `plugin_category_<id>`.
   - Ordner-Kategorien für Service-Sets werden additiv im `category`-Feld der `ServiceSetDefinition` / des `save_set()`-Payloads persistiert.
8. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
9. **Concurrency-Guard & Timer-Pausierung:** Solange im ServiceWindow intensive Service-Berechnungen laufen (`ServiceRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
10. **Isolierter Test-Workspace & Cleanup:** Neue Test-Skripte und temporäre `*.duckdb`-Dateien gehören strikt nach `test/`. Nach Abschluss jedes Phasenkapitels wird `test/` aufgeräumt – es verbleibt nur der Test-Harness `test/test.py`.
11. **Open/Closed-Principle & Code-Preserving:** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden; bestehende Kern-Klassen bleiben geschützt.
12. **Naming Conventions & PineScript-Input-Zone:** 
    - Services in `analytics/features/definitions/` nutzen strikt das Präfix `srv_` (`plugin_id = "srv_..."`).
    - Indikatoren in `chart/indicators/` nutzen strikt das Präfix `ind_` (`indicator_id = "ind_..."`).
    - Füllwörter (`service`, `plugin`, `indicator`) entfallen im Dateinamen.
    - Das `parameter_schema` liegt direkt am Dateianfang unter dem Header-Docstring.
    - Jedes Service-Plugin deklariert `metadata["category"]` für die dynamische Kategorie-Ordner-Struktur im MasterTree.


---

# 20.03 Service-Output-Schema & Resultatfelder-Dokumentation im Service-Picker

## 1. Architektur & Standards (E1, E4, E5)
- **Modul-Konstante & Property (E1)**: Definition als private Modul-Konstante (z. B. `_GRID_OUTPUT_SCHEMA`) am Dateianfang des Plugins. Export über Property `@property def output_schema(self) -> Dict[str, Dict[str, Any]]: return {k: dict(v) for k, v in _GRID_OUTPUT_SCHEMA.items()}`.
- **Basisklasse (`base_plugin.py`)**: `@property def output_schema(self) -> Dict[str, Dict[str, Any]]: return {}` als abwärtskompatibler Default.
- **JSON-Scope (E4)**: `bar_time` NICHT im `output_schema` deklarieren (ist native DB-Spalte, kein JSON-Key).
- **Typen (E5)**: Freie String-Typen unterstützen (z. B. `"bool"`, `"float"`, `"list[float]"`).

## 2. Abdeckung Core-Plugins (E6)
Befüllung der Modul-Konstante `_*_OUTPUT_SCHEMA` in allen 8 aktiven Services unter `analytics/features/definitions/`:
- `srv_grid_lines.py`, `srv_proximity.py`, `srv_swing_structure.py`, `srv_swing_momentum.py`, `srv_swing_volume_profile.py`, `srv_trend_breakout.py`, `srv_trend_hma_pivot.py`, `srv_trend_regime.py`.

## 3. UI-Anzeige im Parameter-Panel (E2, E7) (`serviceui/param_columns.py`)
- **Verortung (E7)**: Integration in `_update_service_info_label` / `_build_service_column` unterhalb der allgemeinen Beschreibung.
- **Gruppierung/Filter (E2)**:
  - **Haupt-Resultatfelder**: Standardmäßig eingerückt anzeigen (`└── 🔹 {field_name} ({type}): {description}`).
  - **Technische Felder** (mit `"technical": True` im Schema, z. B. `calculation_status`, `confirmation_lag_bars`): In kompakter, kleinerer Schrift oder ausklappbarem Unterblock `🔧 System-Metrik` platzieren.
- **Read-Only**: Strikte schreibgeschützte Formatierung.

## 4. Implementation Steps
1. **Base-Plugin (`analytics/features/plugins/base_plugin.py`)**: Add `@property def output_schema`.
2. **Plugins (`analytics/features/definitions/srv_*.py`)**: Define `_*_OUTPUT_SCHEMA` & property across all 8 plugins.
3. **UI (`serviceui/param_columns.py`)**: Render `output_schema` indented below description text field.
4. **Validation (`test/test.py`)**: Headless Test verifying `output_schema` retrieval for all registered plugins + `py_compile`.


---

# 20.03.01 Bugfix: Output-Schema-Sektion + Info-Button im Tree (09.08.2026, 18:20)

## 1. Ausgangslage (User-Meldungen)
1. **Ergebnisparameter gehören NICHT ins Beschreibungsfeld** – die 20.03-Resultatfelder
   wurden zunächst im Read-only-Info-Label unter dem individuellen Beschreibungsfeld
   gerendert; gewünscht ist eine eigene Sektion.
2. **Erste Zeile im allgemeinen Beschreibungsfeld nicht mehr sichtbar** – das lange
   Output-HTML im Info-Label verstärkte den Qt-Quirk (`setHtml` setzt den Cursor ans
   Dokument-Ende, Qt wrappt später um → Scroll nach unten). Alt-Fix 17.01.06
   (`_scroll_textedit_top`, synchron + deferred + nach Box-Resize) ist intakt.
3. **i-Button im Tree geht nicht mehr** – `INFO_BUTTON_TEXT = "ℹ"` (U+2139) rendert
   unter Windows-Qt bei fehlendem Font als Tofu-Box → Button unsichtbar
   (vgl. Alt-Bugfix 04.08.2026 Punkt 5: Unicode-Badge `🛈` → ASCII `'i'`).
4. **Vorgabe (User)**: Je Ergebnisparameter Name + i-Button daneben, der die
   Beschreibung in einem Fenster zeigt.

## 2. Umsetzung (Commit `1f40783`, Tag `20.03_bugfix`)
- **`serviceui/param_columns.py`**:
  - Output-Schema-Block aus `_update_service_info_label` entfernt (Punkt 1).
  - Neue Sektion **UNTER** dem Info-Label in `_build_service_column`: Header
    `📊 Resultatfelder (Output-Schema):`, je Haupt-Resultatfeld eine Zeile
    (`🔹 name (type)`) mit 16-px-`i`-Button → `_show_output_field_info`
    (modaler `QDialog` mit Name/Typ/Beschreibung/Service-Referenz).
    Technische Felder (`technical: True`) kompakt in dezentem Block
    `🔧 System-Metrik: …` (Semikolon-getrennt, ohne Beschreibung).
  - Neues State-Dict `self._service_output_schemas[iid]` (Reset in
    `_clear_service_columns`); `QDialog`-Import ergänzt.
- **`serviceui/master_tree.py`**: `INFO_BUTTON_TEXT` von `"ℹ"` (U+2139) zurück auf
  ASCII `"i"` (Punkt 3) – inkl. Begründungskommentar.

## 3. Validierung (headless, keine UI)
- `py_compile` auf beiden geänderten Dateien: OK.
- `test/check_output_schema.py`: ALL CHECKS PASSED (8 Services, Main/Tech-Split).
- Neuer Testblock `20.03-Bugfix` in `test/test.py`: `INFO_BUTTON_TEXT` = ASCII `'i'`
  (kein U+2139) + Main/Tech-Split vollständig + alle Tech-Felder tragen eine
  Beschreibung – alle PASS.
- Hinweis: Die 6 bestehenden Fehlschläge (P2/P5/H3–H7, Fenster-Persistenz-Geometrie)
  sind VORBESTEHEND und betreffen nicht die geänderten Codepfade
  (nur `master_tree.py`/`param_columns.py` wurden modifiziert).

## 4. Folge-Bugfixes (09.08.2026, 2. Runde, Commit `f071b10` + `b772c93`)
Zwei User-Meldungen nach dem ersten Commit – beide betrafen den Service-Selector-
Dialog (`service_selector_dialog.py`), dessen `_DialogParamHost` den Mixin nur als
Plain-Object (kein QWidget) hostet:

1. **`f071b10` – 'Parameteranzeige nicht verfügbar: _DialogParamHost object has
   no attribute _service_output_schemas'**:
   - Ursache: Der Dialog ruft `_build_service_column` DIREKT auf (ohne
     `_clear_service_columns`, das das Dict normalerweise anlegt); der Host-
     `__init__` initialisierte alle Mixin-Registrys, aber nicht das seit dem
     Output-Schema-Umbau neue `_service_output_schemas`.
   - Fix: `self._service_output_schemas: Dict[str, Any] = {}` im `__init__` von
     `_DialogParamHost` ergänzt (analog `_mode_schemas`, 08.08.2026).
   - Neuer headless Regressions-Test `test/check_dialog_host.py` (Host-Spaltenbau
     inkl. Resultatfelder-Header/System-Metrik/i-Buttons): PASS.

2. **`b772c93` – 'QDialog.__init__ called with wrong argument types' beim
   i-Button der Ergebnisparameter**:
   - Ursache: `_show_output_field_info` erzeugte `QDialog(self)` – `self` ist im
     Dialog-Kontext der `_DialogParamHost` (kein QWidget) → TypeError.
   - Fix: Eltern-Widget robust aufgelöst: `self` falls QWidget, sonst
     `self._dialog` (echtes Dialog-Fenster des Hosts), sonst `None`.
   - `test/check_dialog_host.py` erweitert (mockt `QDialog.exec`, prüft
     Eltern-Auflösung + None-Fallback): ALL PASS.


---

# 20.03.02 Multi-Select Resultatparameter, Dynamic Checkable ComboBox & Info-Fixes (09.08.2026, 20:15; Entscheidungen F1–F7 bestätigt 20:21)

## 1. Regeln & Invarianten
* **Code-Style:** Exakt **4 Leerzeichen** Einrückung, **1 Leerzeile** zwischen
  Methoden/Funktionen (PEP8, Phase-19-Invariante 3).
* **Testing:** **STRIKT HEADLESS** via `py_compile` & `test/test.py`
  (`QApplication.exec()` STRIKT VERBOTEN – Phase-19-Invariante 2). Alle neuen
  Test-Skripte/Test-DBs gehören nach `test/` (Invariante 10).
* **Entkopplung:** MVVM & IoC (Invariante 4/5). Kein SQL in UI; strikter
  Lese-Pfad über `AnalyticsRepository` / `FeatureStoreReader`.
* **Open/Closed (Invariante 11):** Nur additive Ergänzungen; keine
  Umformatierung unbeteiligter Dateien.

## 2. Problemstellung & Ziel
1. **Dropdown-Fixes (größtenteils VORHANDEN, s. §3):** Strikte Filterung der
   Ergebnisfelder nach im Picker tatsächlich aktivierten `feature_ids`.
2. **Multi-Select & Pop-up (NEU):** `CheckableComboBox` mit offen bleibendem
   Pop-up bei Checkbox-Klick und Anzeige `{Service-Name} / {Parameter}`.
3. **Info-Button UI-Umbau (Neuer Req):** Einzelanzeigen der Resultatparameter
   im ServicePicker entfernen. Stattdessen hinter der Gruppenüberschrift
   *"Resultatfelder"* ein einzelner **(i)-Info-Button**, der bei Klick alle
   Ergebnisparameter der gewählten Service-Instanz kompakt in einem Info-Window
   zeigt.
4. **Wiederherstellung Bugfix 1 (Erste Zeile Beschreibungsfeld):**
   `header_line` in `ServiceDescriptionDialog` / `ServiceDescriptionEditDialog`
   – **ist bereits intakt** (Bestandsaufnahme §3, Punkt 5).
5. **Wiederherstellung Bugfix 2 ((i)-Button im MasterTree):**
   Signalverbindung `info_requested` / `category_info_requested` – im
   ServiceWindow intakt; **Lücke im ServiceSelectorDialog (ServicePicker)**.

## 3. Bestandsaufnahme (Vollständigkeitsprüfung gegen HEAD `5c40272`)

| Schritt | Datei | Status | Befund |
|---|---|---|---|
| 2 | `analytics/engine/feature_store_reader.py` | ✅ VORHANDEN | `feature_keys_by_service()` nimmt `feature_ids` (Z. 430) und wendet `_apply_feature_filter` an (Z. 462). Commit `4648399`. |
| 3 | `analytics/engine/analytics_repository.py` | ✅ VORHANDEN | `get_generic_heatmap()` baut `field_sources` + `avail_filtered` strikt über `feature_ids` (Z. 150–176). Commit `4648399`. |
| 4 | `analytics/engine/analytics_view_model.py` | 🟡 DELTA | Leer/`"none"` → `"Allgemein"`, Title-Case-Fallback ✅. **`"native"` → `"Native"` (Plan: `"Allgemein"`)** – Erweiterung offen (F3). |
| 5 | `analytics/engine/description_dialog.py` | ✅ VORHANDEN | `_render_html()` rendert `header_line` fett + `<p>&nbsp;</p>` (Z. 285–290); `ServiceDescriptionEditDialog` ebenso. |
| 6 | `serviceui/master_tree.py` + `service_selector_widget.py` | 🟡 DELTA | Emit + Re-Emit vorhanden (ASCII `"i"`). **`service_selector_dialog.py` verbindet `info_requested` NICHT** → i-Button im ServicePicker wirkungslos. |
| 6b | `serviceui/param_columns.py` | 🔴 NEU | UI-Umbau Resultatfelder (einzelner `btn_output_params_info` statt Per-Zeile-i-Buttons) – betrifft auch `_DialogParamHost`. |
| 1 | `analytics/ui/common.py` | 🔴 NEU | `CheckableComboBox` fehlt vollständig. |
| 7 | `analytics/ui/heatmap_widget.py` | 🟡 KORRIGIERT | **`combo_field` liegt in `heatmap_widget.py` (Z. 496), NICHT in `heatmap_page.py`** – Plan-Verortung angepasst. |
| 7b | `analytics/engine/analytics_view_model.py` | ✅ ENTSCHIEDEN | `set_heatmap_config()` bleibt Einzel-Feld (`field: str`); Multi-Select steuert `feature_ids` (F1c/F2, §6). |

## 4. Architektur & Datenfluss

```text
[ServicePicker / ServiceSelectorDialog] ──(EventBus: service_set_changed)──► [AnalyticsViewModel]
  │                                                                             │
  ├── (i) "Resultatfelder" ──► [ServiceDescriptionDialog (read-only)]          │
  │                                                                             │
[CheckableComboBox (Multi-Select)] ──(checked → feature_ids: List[str])────────┘
       │                               (Filter: WHERE feature_id IN (...))
       │
       ▼
[AnalyticsViewModel.set_heatmap_config(field: str)] ──► [FeatureStoreReader]
       │                    (GENAU EIN aktives Hauptfeld, F1c/F2)
       └──(heatmap_field: str) + feature_ids-Filter
                ▼
        [DuckDB Multi-Field-Aggregation / Render]
```

## 5. Schritt-für-Schritt Umsetzung (inkl. Entscheidungen)

### Schritt 1: `analytics/ui/common.py` – `CheckableComboBox` (NEU)
* `class CheckableComboBox(QComboBox)`: `setEditable(True)`,
  `lineEdit().setReadOnly(True)`, LineEdit-Placeholder (z. B. `"Felder wählen…"`).
* **Pop-up offen halten:** `eventFilter` auf `lineEdit()`/`view()` – Mausklick in
  die Checkbox-Spalte ruft **nicht** `hidePopup()` auf (Qt überschreibt sonst
  den Standard; Pattern: `QComboBox` mit `QStandardItemModel` +
  `Qt.ItemIsUserCheckable`, analog `master_tree.py` Checkbox-Muster).
* API: `add_checkable_item(display_text, user_data, checked=False)`,
  `checked_data() -> List[str]` (nur angehakte `user_data`-Keys in
  Item-Reihenfolge), Signal `selection_changed(list)` (emittiert bei jedem
  CheckState-Wechsel; blockierbar über `_syncing`-Flag, Muster `heatmap_widget`).
* Headless instanziierbar (kein `exec()` im Konstruktor).

### Schritt 2 + 3: Reader/Repository-Filterung
**Bereits umgesetzt (Commit `4648399`) – kein Handlungsbedarf**, nur
Regressions-Absicherung in `test/test.py` (Filter-Check).

### Schritt 4: `resolve_service_display_name()` – natives Handling (DELTA, F3 ✅)
* **Entscheidung F3:** `"native"` und `native_*`-Keys werden wie leere/`"none"`-
  Keys auf `"Allgemein"` gemappt (benutzerfreundlich, konsistent zu Root
  Cause 3). Fallback-Zweig: Leer / `"none"` / `"native"` / `"native_*"`
  → `"Allgemein"`.
* Unregistrierte `srv_`/`ind_`-Keys → Title-Case (bereits vorhanden, bleibt).

### Schritt 5: `header_line` (Bugfix 1)
**Bereits intakt** – keine Änderung; nur Test-Absicherung.

### Schritt 6: `master_tree.py` / `service_selector_widget.py` / `service_selector_dialog.py`
* **Bugfix 2 DELTA (ServicePicker):** Im `service_selector_dialog.py` das
  Signal `info_requested` (und `category_info_requested`) des eingebetteten
  `ServiceSelectorWidget` mit dem Dialog verbinden.
* **Dialog-Entkopplung (F4 ✅):**
  * **ServiceWindow** (`service_win.py`): `i`-Button öffnet WEITERHIN den
    editierbaren `ServiceDescriptionEditDialog` (Instanz-Notizen; Bestand,
    keine Änderung).
  * **ServicePicker** (`service_selector_dialog.py`): zeigt Read-Only
    `ServiceDescriptionDialog.from_plugin()` bzw. `from_set()`.
* **Header-Format (F5 ✅):** Badge-Header strikt vereinheitlicht
  (gilt für `_info_header_tooltip`, `_info_set_tooltip` und den
  Info-Dialog-`header_line`):
  * Service aktiv im Indikator: `📌 im <Indikator> | 🟢 aktiv in <Indikator>`
  * Service inaktiv: `📌 im <Indikator> | ⚪ inaktiv`
  * Mehrere Indikatoren (Sets): `📌 im <I1> + <I2> | 🟢 aktiv in <I1> + <I2>`
    bzw. `⚪ inaktiv` – Namenslogik analog `_apply_set_badge`.
* **UI-Umbau Resultatfelder (`param_columns.py` `_build_service_column`):**
  * Per-Zeile-`i`-Buttons der Haupt-Resultatfelder entfernen (20.03.01-Muster).
  * Direkt hinter dem Label `📊 Resultatfelder:` einen kompakten
    `QPushButton` `btn_output_params_info` (Text/Icon `(i)`) platzieren.
  * Klick → kompaktes Info-Window mit **allen** Output-Parametern der
    gewählten Service-Instanz inkl. Typ + Beschreibung + Service-Referenz.
  * **System-Metriken (F6 ✅):** Felder mit `"technical": True` werden
    UNTERHALB der Haupt-Resultatfelder in einer separaten, kleineren Sektion
    `🔧 System-Metriken` gerendert (Semikolon-getrennt, dezenter Block).
  * `_DialogParamHost`-Kompatibilität (Eltern-Auflösung `self`/`self._dialog`,
    Bugfix `b772c93`) beibehalten; `_service_output_schemas` bleibt.

### Schritt 7: `analytics/ui/heatmap_widget.py` (KORRIGIERTE Verortung + F1c/F2/F7 ✅)
* `_combo_field` (Z. 496) durch `CheckableComboBox` ersetzen.
* **Multi-Select-Semantik (F1c/F2):** Die Multi-Auswahl steuert
  AUSSCHLIESSLICH den Datenquellen-Filter `feature_ids: List[str]`
  (→ `view_model.set_feature_ids(...)`, Filter-Pfad `feature_keys_by_service`
  / `fetch_generic_heatmap`). Die Aggregation verarbeitet GENAU EIN aktives
  Hauptfeld.
* **Keine Signatur-Änderung (F2):** `set_heatmap_config(x_dim, y_dim, field,
  agg)` bleibt unverändert – `field: str` (heatmap_field) ist das eine aktive
  Hauptfeld. KEINE Erweiterung auf `fields: List[str]`.
* Bei `data_ready`/`_sync_combos_from_payload` (Z. 1040): Befüllen via
  `field_sources` mit `{Service-Name} / {Parameter}`,
  `userData="{service_id}|{param_key}"` (Mehrfach-Key: `{key}`-Fallback, Muster
  `_field_label`).
* `_syncing`-Guard und `_apply_config`/`request_data`-Loop beibehalten.
* **UI-Behavior (F7):** Die Feld-Auswahl (`CheckableComboBox`) bleibt bei
  Aggregationen `COUNT` und `CONFLUENCE_COUNT` strikt deaktiviert
  (`setEnabled(False)`, bestehendes `_update_controls`-Muster).

## 6. Entscheidungen (F1–F7, bestätigt durch Anwender am 09.08.2026)

| ID | Entscheidung (verbindlich) |
|---|---|
| F1 | **Multi-Select = Quellen-Filter (c):** Multi-Auswahl im Dropdown steuert ausschließlich den Datenquellen-Filter `feature_ids: List[str]`. |
| F2 | **Keine Signatur-Erweiterung:** `set_heatmap_config(x_dim, y_dim, field, agg)` bleibt unverändert; die Aggregation (`heatmap_field: str`) verarbeitet genau ein aktives Hauptfeld. |
| F3 | **`native`-Fallback:** `resolve_service_display_name("native")` und `native_*`-Keys → `"Allgemein"`. |
| F4 | **Dialog-Entkopplung:** ServiceWindow → editierbarer `ServiceDescriptionEditDialog` (Bestand); ServicePicker → Read-Only `from_plugin()`/`from_set()`. |
| F5 | **Header-Format vereinheitlicht:** `📌 im <Indikator> | 🟢 aktiv in <Indikator>` bzw. `📌 im <Indikator> | ⚪ inaktiv` (Sets: Namen mit ` + ` verknüpft). |
| F6 | **System-Metriken:** `technical: True`-Felder unterhalb der Haupt-Resultatfelder in separater, kleinerer Sektion `🔧 System-Metriken`. |
| F7 | **UI-Behavior:** Feld-Auswahl bei `COUNT`/`CONFLUENCE_COUNT` strikt deaktiviert (`setEnabled(False)`). |

## 7. Verification Checklist (`test/test.py`, headless)

- [x] **Syntax-Check:** `py_compile` auf allen geänderten Dateien
      (`common.py`, `analytics_view_model.py`, `param_columns.py`,
      `service_selector_widget.py`, `service_selector_dialog.py`,
      `service_win.py`, `heatmap_widget.py`, `test/check_dialog_host.py`,
      `test/test.py`) – OK. Unveränderte Dateien (`feature_store_reader.py`,
      `analytics_repository.py`, `description_dialog.py`, `master_tree.py`)
      wurden nicht angefasst.
- [x] **Filter-Check (F1):** `feature_keys_by_service(feature_ids=['srv_a'])`
      liefert KEINE `srv_b`-Keys (und umgekehrt) – headless verifiziert
      (test.py-Checks `m`/`n`, isoliertes Skript analog zum 37er-Block).
      Multi-Select-Mapping (angehakte Items → `feature_ids`) per
      Code-Inspektion abgesichert.
- [x] **Naming- & Header-Check (F3/F5):** `resolve_service_display_name('native')`
      und `resolve_service_display_name('native_foo')` liefern `"Allgemein"`
      (Checks `d`–`f`); `_info_header_line`/`_info_set_header_line` liefern
      das vereinheitlichte Format `📌 im … | 🟢 aktiv in …` / `⚪ inaktiv`
      (Checks `i`–`k`). `ServiceDescriptionDialog`-`header_line`-Rendering
      (Zeile 1, fett + Leerzeile) ist Bestand (Commit `4648399`) und durch
      die Phase-16-Tests `D1`/`D2` + Code-Inspektion abgesichert.
- [x] **Widget-Check:** `CheckableComboBox` instanziiert headless ohne
      Qt-Exec-Freeze; `checked_data()` liefert nur angehakte `userData`-Keys,
      `set_checked_data()` wechselt CheckStates (Checks `a`–`c`).
      Pop-up-Offenhalten (EventFilter unterdrückt `hidePopup()` bei
      Checkbox-Klick) ist per Code-Inspektion abgesichert (nicht headless
      simulierbar).
- [x] **Info-Umbau-Check (F6):** `_build_service_column` rendert genau EINEN
      `btn_output_params_info` (hinter „Resultatfelder"), keine Per-Zeile-i-
      Buttons mehr; `technical: True`-Felder als separate Sektion
      `🔧 System-Metriken` im Sammel-Info-Window; `_DialogParamHost`-
      Spaltenbau fehlerfrei (Regressions-`test/check_dialog_host.py`,
      16 Checks – ALLE PASS).
- [x] **Picker-i-Button (F4):** Signal-Re-Emission `category_info_requested`
      im `ServiceSelectorWidget` (beide Modi) + Verdrahtung
      `info_requested`/`category_info_requested` im `ServiceSelectorDialog`
      → Read-Only `ServiceDescriptionDialog.from_plugin()`/`from_set()`
      (Check `l` + Code-Inspektion der Slot-Verdrahtung); ServiceWindow-Pfad
      (Editier-Dialog) unverändert.
- [x] **F2/F7:** `set_heatmap_config`-Signatur unverändert (`field: str`,
      Check `g`); `_field_key` extrahiert den JSON-Key aus
      `"{service_id}|{key}"` (Check `h`); `COUNT`/`CONFLUENCE_COUNT` sind
      NICHT in `_VALUE_AGGS` → Feld-Combo wird deaktiviert (Check `o` +
      `_update_controls`-Inspektion).

## 8. Hinweise
* Die 6 vorbestehenden Fehlschläge in `test/test.py` (P2/P5/H3–H7,
  Fenster-Persistenz-Geometrie) sind NICHT Bestandteil dieser Phase.
* Entscheidungen F1–F7 sind vom Anwender am 09.08.2026, 20:21 bestätigt und
  in §6 verbindlich dokumentiert.

## 9. Implementierungs-Log (09.08.2026, ~20:55; Commit `1324d95`, Tag `20.03.02`)
* **`analytics/ui/common.py`** – `CheckableComboBox` (NEU, F1): `QComboBox` mit
  `QStandardItemModel`, Checkbox-Spalte, EventFilter hält Pop-up bei
  Checkbox-Klick offen; API `add_checkable_item(display_text, user_data,
  checked)`, `checked_data() -> List[str]`, `set_checked_data()`, Signal
  `selection_changed(list)`.
* **`analytics/engine/analytics_view_model.py`** – F3: `resolve_service_display_name`
  mappt `"native"`/`native_*`/`"none"`/leer → `"Allgemein"` (statt Title-Case-
  Fallback für `native`).
* **`serviceui/service_win.py`** – F5: Info-Badge-Header vereinheitlicht
  (`📌 im … | 🟢 aktiv in …` bzw. `⚪ inaktiv`, Sets mit ` + `).
* **`serviceui/service_selector_dialog.py`** – F4: Import + Verdrahtung
  `info_requested`/`category_info_requested` des eingebetteten Widgets;
  Slots `_on_info_requested`/`_on_category_info_requested` öffnen Read-Only
  `ServiceDescriptionDialog.from_plugin()`/`from_set()` mit
  `_info_header_line`/`_info_set_header_line`.
* **`serviceui/service_selector_widget.py`** – F4: neues Signal
  `category_info_requested` + Re-Emission in beiden Modi (Achtung: gemischte
  Line-Endings, nur per Python-Skript editierbar).
* **`serviceui/param_columns.py`** – F6: Per-Zeile-i-Buttons entfernt, EIN
  `btn_output_params_info` hinter `📊 Resultatfelder:`; neuer Slot
  `_show_output_params_info()` zeigt Hauptfelder + Sektion
  `🔧 System-Metriken` (`technical: True`); `_DialogParamHost`-Kompatibilität
  beibehalten.
* **`analytics/ui/heatmap_widget.py`** – F1c/F2/F7: `_combo_field` ist jetzt
  `CheckableComboBox`, userData `"{service_id}|{key}"`; Multi-Select →
  `set_feature_ids(...)` (Quellen-Filter); `set_heatmap_config`-Signatur
  unverändert; Feld-Combo bei `COUNT`/`CONFLUENCE_COUNT` deaktiviert.
* **Validierung:** `py_compile` auf allen geänderten Dateien OK; neuer
  20.03.02-Testblock in `test/test.py` (Checks `a`–`o`, 15 Stück);
  `test/check_dialog_host.py` (16 Checks); isolierte Verifikationsskripte
  (danach gelöscht, test/-Cleanup) – ALLE PASS. Kein Regressionstest, keine
  UI-Ausführung (Phase-19-Invariante 2).




