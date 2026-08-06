# Phase 16: Architektur Servive/Indikator - Feinarbeit Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 16)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase16_step1`, `phase16_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
4. **Zentraler `EventBus`:** Fenster und Worker communicaten schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
5. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db_service.py`) – eine Verbindung pro Thread und DB-Datei.
6. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
7. **Concurrency-Guard & Timer-Pausierung (Ergänzung 1):** Solange im ServiceWindow intensive Service-Berechnungen laufen (`SetRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
8. **Isolierter Test-Workspace (Ergänzung 2):** Alle neuen Test-Python-Dateien und temporären Test-Datenbanken (`*.duckdb`) müssen strikt im Unterordner `test/` erzeugt, gelesen und abgelegt werden – niemals im Projekt-Root oder im `data/`-Ordner.
9. **Open/Closed-Principle & Code-Preserving (Ergänzung 3):** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden und bestehende Kern-Klassen bleiben geschützt.
10. **Test-Cleanup (Ergänzung 4, Entscheidung 06.08.2026):** Tests werden NICHT aufbewahrt. Nach Abschluss jedes Phasenkapitels wird der Ordner `test/` aufgeräumt – es bleibt ausschließlich die Datei `test/test.py` (dauerhafter Test-Harness) bestehen. Alle temporären Check-Skripte (`check_*.py`/`*.js`), einmaligen Migrations-/Bereinigungsskripte, Test-Datenbanken (`*.duckdb`) und generierten Dateien (`tmp_*.json` u. Ä.) werden entfernt. Die Verifikation eines Kapitels erfolgt daher VOR der Bereinigung; danach existieren die Prüfskripte nicht mehr.

---

## 15.03 Prüfstand – Analytics Engine & UI (Ist-Analyse 06.08.2026)

> **Status:** Vollständig umgesetzt & committet (Commits `bf92298`, `2579410`, `b62d3ed`, `14ff6d9`; Spezifikation & Detail-Log archiviert in `docs/Old/x_Roadmap_Phase15.md`).

### Konsistenz-Check (alle Bausteine im Ist-Stand vorhanden)
* **Profil-Repository:** `analytics_profile_repository.py` – CRUD, `schema_version`-Pflichtfeld (Default 1, explizite Version gewinnt, Alt-Row-Default), genau EIN aktives Profil.
* **Reader & Repository:** `analytics/engine/feature_store_reader.py` (fetch_rows/columns/heatmap, E-3 schema_version-Default, Wanduhr-Forcierung `bar_time AT TIME ZONE 'UTC'`) + `analytics/engine/analytics_repository.py` (get_table/heatmap/scatter/distribution + get_latest_bar_time/get_recent_bar_time_for_cell).
* **Worker & ViewModel:** `analytics_worker.py` (5 Query-Kinds, `MAX_LOOKBACK_LIMIT=50_000`, `cap_lookback_limit`) + `analytics_view_model.py` (Debounce-QTimer 250 ms, Dirty-Flag Option B, EventBus `profile_changed`, Clamping).
* **UI:** `analytics/ui/analytics_win.py` (`PersistentWindow`, `win_analytics`, 1280×800, Top-Bar CRUD, Sidebar, Progress-Busy, Jump-to-Chart Variante 2, E-2-Migration) + 5 Pages (Tabelle/Heatmap/Scatter/Verteilung/Equity mit `No Data`-Overlay).
* **main.py:** `StatisticWindow` → `AnalyticsWindow` ersetzt; `statistic_win.py` + `analytics/statistics_repository.py` bleiben als Legacy (E-1).
* **15.03-E Datenquellen-Dialog:** `serviceui/service_selector_dialog.py` (Multi-Select, Checkbox-MasterTree, `feature_ids`=plugin_ids), `master_tree.py` (Klick-Scope `selection_details`, Checkbox-Tri-State), ViewModel `set_feature_ids`, Reader IN-Clause. Inkl. Bugfix-Runden 1–3 (Horizontallayout, 2-Spalten-Minimum, exakte Fensterkante, Geometrie-Persistenz, History-Bug, Zeilen-Klick-Logik).
* **Verifikation (headless):** `py_compile` auf 17 betroffenen Dateien → OK; keine toten Referenzen auf entfernte Funktionen (`combo_feature`/Popover nur noch in Kommentaren).

### Offene Punkte / Entscheidungen (zur Freigabe)
1. **E-2-Migration (Kapselung):** `migrate_statistics_persistence()` in `analytics_win.py` nutzt weiterhin das StateManager-Interface, obwohl `window_state_repository.py` seit 15.04 existiert (Kommentar verweist auf „folgt in 15.04"). → Nachziehen oder bewusst belassen?
2. **15.03-Regressionstests:** Die 15.03-Checks (`check_p15_s3_*.py`, 30/30/39/39/49/49/66/66) wurden gemäß Test-Cleanup-Invariante 10 entfernt; `test/test.py` deckt nur noch Basis-Fälle ab (H8/H9, ServiceSelectorModel). → Ausreichend?
3. **P16.03-Konzept vs. 16.02-Umsetzung:** ~~P16.03 Schritt 1 sieht `chart/overlays/style_models.py` mit `LineStyle`+`MarkerStyle` (inkl. `to_js_dict`/`to_dict`/`from_dict`) vor; aktuell ist `LineStyle` eine Dataclass in `chart/widgets/style_picker_widget.py` (ohne MarkerStyle/Serializer).~~ → **GELÖST (06.08.2026):** Durch P16.03-Schritt 1+2 harmonisiert – `LineStyle`/`MarkerStyle` liegen jetzt zentral in `chart/overlays/style_models.py`, `chart/widgets/__init__.py` re-exportiert beide (rückwärtskompatibler Importweg). Siehe Implementierungs-Log P16.03.

---

# P16.03 - Generische Zeichnungsobjekte & Style-Verträge

## 1. Konzept-Idee
Visuelle Attribute (Farbe, Dicke, Stil, Form) werden nicht mehr als flache Einzelparameter (`line_color`, `line_width`, ...) durch das System gereicht, sondern in **typisierten Styling-Klassen (Dataclasses)** gebündelt.
* **Style-Verträge (`chart/overlays/style_models.py`):** `LineStyle` und `MarkerStyle` kapseln Styling-Attribute und konvertieren sich via `.to_js_dict()` direkt für das Canvas-Frontend.
* **UI-Control (`StylePickerWidget`):** Ein generisches Widget (`chart/widgets/style_picker_widget.py`) steuert Farbe, Dicke, Stil und Sichtbarkeit.
* **Preset-Integration:** `to_dict()` und `from_dict()` sichern die nahtlose JSON-Serialisierung im `StateManager` (`indicator_presets`).

## 2. Schritt-für-Schritt Anleitung

### Schritt 1: Style-Verträge erstellen (`chart/overlays/style_models.py`) — ✅ UMGESETZT
* Dataclasses `LineStyle` (`show`/`color`/`width`/`style`) und `MarkerStyle` (`show`/`color`/`shape`/`size`) in `chart/overlays/style_models.py`; Helfer `_as_bool`/`_as_int`/`_as_str`; Konstanten `LINE_STYLES` (solid/dashed/dotted/dashdotted) und `MARKER_SHAPES` (circle/square/arrowUp/arrowDown, LWC v5-kompatibel).
* `.to_js_dict()` (JS-Bridge), `.to_dict()` (JSON) und `from_dict()` (tolerant: fehlende/ungültige Felder → Defaults, `None` → Default-Instanz) implementiert.
* `chart/overlays/__init__.py` exportiert `LINE_STYLES`, `MARKER_SHAPES`, `LineStyle`, `MarkerStyle`.

### Schritt 2: StylePickerWidget ausbauen (`chart/widgets/style_picker_widget.py`) — ✅ UMGESETZT
* Widget nutzt jetzt die Style-Verträge aus `chart/overlays/style_models.py` (keine lokale `LineStyle`-Dataclass mehr).
* Neuer Konstruktor-Parameter `style_type: str = "line"` (`"line"` → `LineStyle`/width 1–10, `"marker"` → `MarkerStyle`/size 1–20); Property `style_type`.
* Composite: `QCheckBox` (show) + Farb-Button + `QSpinBox` (width/size) + `QComboBox` (style/shape); `get_style()`/`set_style()` für beide Typen (Typ-Mismatch defensiv toleriert); `set_color()`/`color()`-Shim für den Dialog-Restore-Pfad.
* Import-Harmonisierung: `chart/widgets/__init__.py` re-exportiert `LineStyle`/`MarkerStyle` aus den overlays; `chart/indicator_dialog.py` importiert `LineStyle` aus `chart.overlays.style_models` und `StylePickerWidget` aus `chart.widgets.style_picker_widget`.

### Schritt 3: Services & Indikatoren auf Style-Objekte umstellen — ✅ UMGESETZT (P16.01-KONFORM)
> **Wichtige Erkenntnis (06.08.2026):** Der ursprüngliche Schritt-3-Plan kollidiert mit **P16.01**. Seit P16.01 (E1/E5) sind `grid_lines_service.py` und `proximity_service.py` `render=False` und liefern **keinen** `chart_render_payload` mehr – ihre `parameter_schema` enthalten **keine** Style-UI-Params mehr (`show_lines`/`line_color`/`circle_color_*` wurden aus den Services entfernt). Das komplette Render-Styling liegt ausschließlich im Indikator `chart/indicators/fixed_grid_proximity.py` (`build_chart_render_payload()`).
* **P16.01-konforme Umsetzung:** Style-Objekte kommen **im Indikator** zum Einsatz, nicht in den Services:
  * `fixed_grid_proximity.py`: Neuer additiver Helfer `_build_style_objects(ui_params)` baut `LineStyle` (Grid-Linien: show_lines/line_color) + zwei `MarkerStyle` (Std-/Aktiv-Hit: show_circles/circle_color_std/_active); `build_chart_render_payload()` übersetzt sie via `.to_js_dict()` in den Payload (lowercase style, LWC-v5-Konvention). Paritäts-Styling (custom: rgba(33,150,243,0.9)/width 1, normal: rgba(33,150,243,0.5)/width 3) und in_window-Farb-Semantik bleiben unverändert.
  * **JS-Bridge-Sicherheit:** `renderGridLines` ignoriert das `style`-Feld (hardcoded `LineStyle.Solid`), `renderGridCircles` nutzt `shape:'circle'`/`size:1` fest – der Payload-Vertrag (`lines`/`hit_circles`) bleibt identisch. Kein anderer Consumer des `style`-Feldes im Projekt.
  * `indicator_dialog.py`: `StylePickerWidget` bereits seit 16.02 für die Farb-Parameter (`type: color`) dynamisch eingebunden (Dialog liest/schreibt nur den Farbanteil – Entscheidung Benutzer 16.02). Das Schema hat keine width/style-UI-Params → kein weiterer Ausbau nötig.

### Schritt 4: Preset-Mechanismus & Migration absichern — ✅ UMGESETZT
* **`chart/indicator_dialog.py`:** Neuer modul-level Helfer `_jsonify_style_objects(obj)` – konvertiert `LineStyle`/`MarkerStyle`-Objekte rekursiv via `.to_dict()` in JSON-kompatible Dicts (auch verschachtelt in Dicts/Listen). Angewendet in `_PresetItemAdapter._item_save_as` VOR `state_manager.save_indicator_preset()` – defensive Absicherung gegen `TypeError` in `json.dumps`, falls je ein Style-Vertrag direkt im Payload landet. Der aktuelle Payload (`_build_preset_payload`) enthält nur primitive Werte (Farb-Strings + shape/size/style/width-Geschwister-Keys) – der Helfer ist damit reine Absicherung, kein Verhaltenswechsel.
* **`analytics/engine/schema_migrator.py`:** **Verifiziert, keine Änderung nötig** – die generische `migrate_instance_config` ergänzt Alt-Instanz-Konfigurationen (Version `0.0.0`, ohne Style-Keys) bereits transparent mit den Schema-Defaults, entfernt veraltete Keys und hebt die Version an (Original bleibt unverändert – Rollback-Schutz). Für Alt-**Indikator-Presets** migriert die bestehende Dialog-Architektur lazy: `collect_params_from_ui()` startet mit `default_params` (enthält alle Style-Keys), `_build_style_objects({})` fällt bei fehlenden Keys auf die Schema-Defaults zurück (solid/1 bzw. circle/6). Alt-Presets ohne Style-Keys zeigen damit überall Defaults und werden beim nächsten Speichern vollständig.
* **Status:** Umgesetzt (letzter Schritt des Kapitels P16.03).

### Schritt 5: Headless-Verifikation — ✅ UMGESETZT
* `py_compile` auf `chart/overlays/style_models.py`, `chart/overlays/__init__.py`, `chart/widgets/style_picker_widget.py`, `chart/widgets/__init__.py`, `chart/indicator_dialog.py`, `chart/indicators/fixed_grid_proximity.py` → OK.
* `test/check_p16_s3_style_objects.py` (offscreen, kein `exec_`): **47/47 Checks PASS** – 31 Basis-Checks (Defaults, Roundtrip, Toleranz, js_dict LWC-v5, Konstanten, Re-Export-Identität, Widget line+marker, Signal-Semantik, indicator_dialog-Import) + 16 Schritt-3-Checks (`_build_style_objects`-Abbildung, lowercase style, Paritäts-Styling inkl. Custom-Level, line_color/show_lines, in_window-Farb-Semantik, priority=10, show_circles).
* Import-Smoke-Tests (`chart.widgets`, `chart.overlays`, `chart.indicator_dialog`, `chart.indicators.fixed_grid_proximity`) → OK.


---

## Implementierungs-Log

- **P16.03 Schritt 4 (Preset-Mechanismus & Migration absichern)**
  - Datum/Uhrzeit: 06.08.2026 (MD)
  - Umgesetzt: `chart/indicator_dialog.py` – neuer modul-level Helfer `_jsonify_style_objects(obj)` (rekursiv `LineStyle`/`MarkerStyle` → `.to_dict()`, auch in verschachtelten Dicts/Listen; Primitive unverändert) + Anwendung in `_PresetItemAdapter._item_save_as` VOR `state_manager.save_indicator_preset()` (defensive Absicherung gegen `json.dumps`-TypeError; der aktuelle Payload enthält nur primitive Werte – kein Verhaltenswechsel). `analytics/engine/schema_migrator.py` – verifiziert, keine Änderung nötig: `migrate_instance_config` ergänzt Alt-Instanz-Konfigurationen (Version 0.0.0) ohne Style-Keys transparent mit Schema-Defaults (Rollback-Schutz intakt); Alt-Indikator-Presets migrieren lazy über die Dialog-Architektur (`collect_params_from_ui` startet mit `default_params`, `_build_style_objects({})` → Schema-Defaults solid/1 bzw. circle/6).
  - Verifikation (headless): py_compile `chart/indicator_dialog.py` (OK); Import-Smoke (`chart.indicator_dialog`, `chart.chart_win`, `analytics.engine.schema_migrator`, `chart.overlays.style_models`) OK; `test/check_p16_s3_step4_presets.py` (NEU) **17/17 PASS** (A: `_jsonify_style_objects` inkl. verschachtelt + `json.dumps`-Lauf; B: Alt-Preset-Lazy-Migration – `default_params` enthält alle Style-Keys, `_build_style_objects({})` → Default-Objekte; C: SchemaMigrator mit Alt-Instanz – fehlende Style-Keys ergänzt, vorhandene bleiben, Version angehoben, Original unverändert). Bestehender `test/check_p16_s3_style_objects.py` weiterhin ALL PASSED.
  - Abschluss: Kapitel P16.03 damit vollständig (Schritte 1–5). Laut Invariante 10 wurde der Ordner `test/` nach Kapitelabschluss aufgeräumt (alle `check_*.py` entfernt, nur `test/test.py` bleibt). Doku-Finalisierung + Commit erfolgen mit der Freigabe des Anwenders (Bugfix-Streams siehe Log unten).

- **Bugfix-Stream P16.03 (Default-Preset überschreibbar + Style-Verdrahtung)**
  - Datum/Uhrzeit: 06.08.2026 (MD), Anwender-Freigabe für Doku/Commit/Push
  - **Anwender-Anweisung „Default soll überschrieben werden können":** Zunächst (fälschlich) als „Default unveränderlich" umgesetzt (ephemeres `_default_overlay` in `chart_win.py` + `_effective_indicator_state`). Nach expliziter Anweisung vollständig ZURÜCKGEBAUT:
    * `chart/chart_win.py`: `_default_overlay`-Init, Overlay-Pop in `_open_indicator_settings`, Overlay-Clear in `_on_settings_closed`, Default-Branch in `_on_indicator_params_updated` und Helfer `_effective_indicator_state` entfernt → `_on_indicator_params_updated` schreibt für `preset='Default'` wieder REGULÄR in `indicators_state` (wird persistiert, beim nächsten Öffnen zeigt der Dialog die überschriebenen Werte). Alle 5 Render-/State-Lesestellen wieder auf direkten `indicators_state.get(ind_id, {})`-Zugriff.
    * `chart/indicator_dialog.py`: `_PresetItemAdapter._item_reserved_name()` → `None` („Default" nicht mehr geschützt → 💾 Speichern unter „Default" und ❌ Löschen möglich); Docstrings von `save_current_preset`/`delete_current_preset` aktualisiert.
    * Randverhalten (bewusst): Combo-Auswahl „Default" im offenen Dialog lädt weiterhin die Werkseinstellungen (Plugin-`default_params`) → „Reset auf Default"-Pfad.
  - **P16.03-Bugfixes 1–3 (Style-Verdrahtung, vor der Doku-Freigabe umgesetzt):**
    * Bugfix 1: `style_type: "marker"` im Schema für `circle_color_std/_active` + durchgereichter MarkerStyle-Typ in `create_schema_control` (Circle-Anzeige im Prop-Fenster).
    * Bugfix 2: Vollständige shape/size-Verdrahtung (Hidden-Schema-Params `circle_shape_std/_active` + `circle_size_std/_active`, Helfer `_marker_shape`/`_marker_size`, Payload-Hit-Circles tragen shape/size, `_colorize` additiv, `update_live_candle`-Live-Punkte, JS `renderGridCircles` nutzt `cc.shape`/`cc.size`, Dialog-Roundtrip via `_style_sibling_keys`). `fixed_grid_proximity.py` auf reines LF normalisiert.
    * Bugfix 3: Linienart/-stärke (Hidden-Schema-Params `line_style`/`line_width`, Helfer `_line_style`/`_line_width`, Payload-Lines mit User-width/style, JS `_lwcLineStyle()`-Mapping, Dialog-LineStyle-Zweige).
  - Verifikation (headless): py_compile (`chart_win.py`, `indicator_dialog.py`, `fixed_grid_proximity.py`) OK; `node --check` `chart/js/03_chart_rendering.js` OK; `test/check_default_overwrite.py` (NEU, ersetzt den alten Overlay-Test) **13/13 PASS**; bestehende `check_p16_s3_style_objects.py` + `check_p16_s3_step4_presets.py` weiterhin ALL PASSED; keine Rest-Referenzen auf `_default_overlay`/`_effective_indicator_state`. Danach gemäß Invariante 10 entfernt.

- **P16.03 Schritt 3 (Indikator-Anbindung, P16.01-konform)**
  - Datum/Uhrzeit: 06.08.2026 17:10 (MD)
  - Umgesetzt: `chart/indicators/fixed_grid_proximity.py` – neuer additiver Helfer `_build_style_objects(ui_params)` (LineStyle für Grid-Linien, 2× MarkerStyle für Std-/Aktiv-Hit); `build_chart_render_payload()` übersetzt die Style-Verträge via `.to_js_dict()` in den Payload (lowercase `style:'solid'` statt bisher `'Solid'`). Paritäts-Styling (custom: rgba(33,150,243,0.9)/width 1, normal: rgba(33,150,243,0.5)/width 3), in_window-Farb-Semantik, priority=10 und show-Flags unverändert. Verifiziert: JS-Bridge ignoriert `style` (renderGridLines hardcoded `LineStyle.Solid`), kein weiterer Consumer des Feldes im Projekt.
  - Verifikation (headless): py_compile auf `fixed_grid_proximity.py` (OK); Import-Smoke-Test OK; gezielter Logik-Test (Defaults, Custom-Level, line_color, show-Flags, in_window-Farben, `_build_style_objects`-Typen) PASS; `test/check_p16_s3_style_objects.py` auf 47/47 Checks erweitert (16 neue Schritt-3-Checks) – ALL PASSED.
  - Hinweis: Beim Edit kam es durch gemischte CRLF/LF-Zeilenenden im File zu zwei fehlerhaften Whitespace-Ersetzungen (`return out`/`out.add`-Einrückung) – per Byte-Level-Skript korrigiert und per py_compile + Indent-Inspektion verifiziert (L427 indent=12, L428 indent=8).
  - Offen/Entscheidung Benutzer: Schritt 4 (Preset-Mechanismus & Migration in `indicator_dialog.py`/`schema_migrator.py`) – letzter Schritt des Kapitels. Danach Test-Cleanup (Invariante 10) + Doku-Finalisierung + Commit.

- **P16.03 Schritt 1+2+5 (Style-Verträge, StylePickerWidget, Verifikation)**
  - Datum/Uhrzeit: 06.08.2026 16:36 (MD)
  - Umgesetzt: `chart/overlays/style_models.py` (NEU – `LineStyle`/`MarkerStyle` als Dataclasses mit `to_js_dict`/`to_dict`/`from_dict`, Konstanten `LINE_STYLES`/`MARKER_SHAPES`); `chart/overlays/__init__.py` (Export); `chart/widgets/style_picker_widget.py` auf Style-Verträge umgestellt + `style_type`-Param (`line`/`marker`) inkl. Marker-Modus; `chart/widgets/__init__.py` re-exportiert `LineStyle`/`MarkerStyle` aus den overlays (rückwärtskompatibel); `chart/indicator_dialog.py` Import-Harmonisierung (`LineStyle` jetzt aus `chart.overlays.style_models`).
  - Abweichung dokumentiert: Schritt 3 wird **P16.01-konform** umgesetzt – `grid_lines_service.py`/`proximity_service.py` haben seit P16.01 (render=False) keine Style-UI-Params mehr; Style-Objekte kommen stattdessen im Indikator `fixed_grid_proximity.py` (`build_chart_render_payload`) zum Einsatz. Indikator-Anbindung steht aus (nächster Schritt nach Freigabe).
  - Verifikation (headless): py_compile auf 5 Dateien (OK); `test/check_p16_s3_style_objects.py` 31/31 PASS (Defaults, Roundtrip, Toleranz, js_dict LWC-v5, Re-Export-Identität, Widget line+marker, Signal-Semantik); Import-Smoke-Tests OK. QFontDatabase-Warnung im offscreen-Modus harmlos.
  - Offen/Entscheidung Benutzer: Schritt 3 (Indikator-Anbindung) + Schritt 4 (Preset/Migration) umsetzen? `test/check_p16_s3_style_objects.py` wird gemäß Invariante 10 nach Kapitelabschluss entfernt.

- **15.03 Pruefstand (Ist-Analyse)**
  - Datum/Uhrzeit: 06.08.2026 (MD)
  - Umgesetzt: Konsistenz-Analyse der 15.03-Bausteine (Profile-Repo, Reader/Repo, Worker/ViewModel, AnalyticsWindow + 5 Pages, main.py-Ersatz, E-1/E-2, 15.03-E ServiceSelectorDialog) gegen die Spezifikation; py_compile auf 17 Dateien (OK); Suche nach toten Referenzen (keine).
  - Ergebnis: 15.03 vollständig umgesetzt und committet (bf92298, 2579410, b62d3ed, 14ff6d9). Keine Code-Aenderungen erforderlich.
  - Offen/Entscheidung Benutzer: (1) E-2-Migration auf WindowStateRepository nachziehen? (2) 15.03-Regressionstests entfernt - ausreichend? (3) P16.03-Konzept: LineStyle/MarkerStyle in chart/overlays/style_models.py harmonisieren.
