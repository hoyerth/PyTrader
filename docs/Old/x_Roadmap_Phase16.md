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

---

## 16.01.02 ⚠️ Nachgelagerte Arbeiten 

> **Hinweis:** Diese optionalen Bereinigungs- und Pflegearbeiten dürfen erst nach expliziter Anforderung und Prüfung nach Abschluss der Schritte 1–4 durchgeführt werden.

### 1. Code- & Parameter-Bereinigung
* **Backend-Services (`grid_lines_service.py`, `proximity_service.py`):**
  * Finale Entfernung ungenutzter Rendering-Keys (`lines`, `hit_circles`, `show_lines`, `line_color`, `show_circles`, `circle_color_std`, `circle_color_active`) aus den Rückgabe-Dictionaries von `calculate()`.

### 2. DB- & Preset-Bereinigung (`app_data.duckdb`)
* **Service-Sets & Presets (`indicator_presets`, `service_sets`):**
  * *Automatischer Puffer:* Der `SchemaMigrator` filtert veraltete UI-Keys beim Laden transparent im Arbeitsspeicher heraus (kein Handlungsbedarf für den Betrieb).
  * *Endgültige Bereinigung:* **DURCHGEFÜHRT (06.08.2026, Entscheidung Benutzer).** Einmaliges Skript `test/cleanup_p16_legacy_rendering_keys.py` hat die veralteten Rendering-Keys (`show_lines`, `line_color`, `show_circles`, `circle_color_std`, `circle_color_active`, `hit_circles`, `lines`) rekursiv aus den JSON-Payloads von `service_sets`, `service_sets_trash` und `indicator_presets` entfernt. Betroffen war 1 Zeile (Set „test", `grid_lines`-params: `show_lines` + `line_color`). `service_set_history` bleibt als unveränderliches Snapshot-Protokoll unangetastet.

### 3. Verifikation & Test-Cleanup
* **Isolierter Test-Check (VOR der Bereinigung):**
  * `test/check_p16_s1_decoupling.py`: 31/31 Checks PASS – `feature_store_payload` frei von Canvas-Objekten, `FixedGridProximityIndicator` baut das `chart_render_payload` korrekt.
  * Statische Syntaxprüfung via `python -m py_compile` (5 Dateien): OK.
  * Read-only-DB-Check nach der Bereinigung: keine Legacy-Keys mehr in `service_sets`/`service_sets_trash`/`indicator_presets` (exakte Key-Prüfung).
* **Test-Cleanup (Ergänzung 4):** Nach Abschluss von 16.01.02 wurde der Ordner `test/` aufgeräumt – alle Check-/Migrations-/Temp-Dateien entfernt, verbleibend: `test/test.py`.

### 4. Prüfstand 16.01.02 (abgeschlossen 06.08.2026)
* **Punkt 1 – Code- & Parameter-Bereinigung: UMGESETZT (P16.01, Commit `1632787`).**
  * `grid_lines_service.calculate()` liefert ausschließlich `feature_store_payload` – keine Rendering-Keys mehr (`lines`, `hit_circles`, `show_lines`, `line_color`). `show_lines`/`line_color` sind weder in `parameter_order`/`param_labels` noch in `parameter_schema`.
  * `proximity_service.calculate()` liefert ausschließlich `feature_store_payload` – keine Rendering-Keys mehr (`hit_circles`, `show_circles`, `circle_color_std`, `circle_color_active`); `status_info` liegt als Feature-Daten in `metadata["statistics"]`.
  * Die Keys existieren nur noch dort, wo sie architektonisch hingehören: im Indikator-Schema `chart/indicators/fixed_grid_proximity.py` (UI-Styling) sowie in Kommentaren/Docstrings (Dokumentation der Entkopplung).
* **Punkt 2 – DB- & Preset-Bereinigung: ABGESCHLOSSEN (finale Bereinigung durchgeführt).**
  * *Automatischer Puffer:* `analytics/engine/schema_migrator.py` entfernt veraltete Keys transparent im Speicher (verifiziert durch Code-Inspektion).
  * *Finale Bereinigung:* Einmaliges Skript (`test/cleanup_p16_legacy_rendering_keys.py`, danach gemäß Ergänzung 4 entfernt) bereinigte 1 Zeile – Set „test" (`grid_lines`-params: `show_lines` + `line_color`). Read-only-Verifikation danach: exakte Key-Prüfung über `service_sets`/`service_sets_trash`/`indicator_presets` → KEINE Legacy-Keys mehr.
* **Punkt 3 – Verifikation & Test-Cleanup: ABGESCHLOSSEN.**
  * `test/check_p16_s1_decoupling.py`: 31/31 Checks PASS (G1–G11, P1–P10, I1–I16; I14–I16 liefen über den Rohdaten-Fallback, da `data/analytics.duckdb` während des Checks von der laufenden App gelockt war).
  * `python -m py_compile` der 5 betroffenen Dateien (`grid_lines_service.py`, `proximity_service.py`, `schema_migrator.py`, `service_set_repository.py`, `fixed_grid_proximity.py`): OK.
  * Test-Cleanup gemäß Entscheidung (Ergänzung 4): `test/` aufgeräumt, verbleibend `test/test.py`.

---

## 16.02 Refactoring: ColorButton → StylePickerWidget

> **Anweisung (IDE-AI):** Umbenennung `ColorButton` → `StylePickerWidget` – die
> Komponente bündelt künftig Farbe, Linienstärke (px), Linienart (solid/dashed/
> dotted/dashdotted) und Sichtbarkeit zentral.

### 1. Ziel & Konzept
* Der bisherige `ColorButton` (`chart/widgets/color_button.py`, Phase 13 5.5,
  reiner Farbwähler mit Alpha) wird zum generischen **`StylePickerWidget`**
  ausgebaut und umbenannt.
* Das neue Widget erbt von `QWidget` und kapselt intern:
  1. `QCheckBox` (Sichtbarkeit `show`),
  2. kleinen Farb-Button (`color` via `QColorDialog`, optional Alpha),
  3. `QSpinBox` (Linienstärke `width`, 1–10),
  4. `QComboBox` (Linienart `style`: solid/dashed/dotted/dashdotted).

### 2. Umsetzung (06.08.2026)
* **Schritt 1 (Datei & Klasse):** `chart/widgets/color_button.py` → **`chart/widgets/style_picker_widget.py`**; Klasse `ColorButton(QPushButton)` → **`StylePickerWidget(QWidget)`**; alte Datei entfernt.
* **Neuer Datentyp `LineStyle`** (`@dataclass`, in der Widget-Datei): Felder `show: bool = True`, `color: str = "#2196F3"`, `width: int = 1`, `style: str = "solid"`.
* **Schritt 2 (Imports):**
  * `chart/widgets/__init__.py`: `from .style_picker_widget import LineStyle, StylePickerWidget`; `__all__` aktualisiert (ColorButton entfernt).
  * `chart/indicator_dialog.py`: Import + 4 Verwendungsstellen umgestellt (siehe unten).
  * Keine Designer/UI-Referenzen vorhanden (Projekt-Suche).
* **Schritt 3 (Schnittstelle):**
  * `get_style() -> LineStyle` (frische Instanz, kein Aliasing).
  * `set_style(style: LineStyle)` (programmatisch, emittiert KEIN Signal).
  * `set_color(str)` – reiner Farb-Restore (behält show/width/style).
  * Signal `style_changed = Signal(object)` – emittiert das aktuelle `LineStyle`.
  * Farb-Logik (Parität zum Alt-ColorButton): Hex `#RRGGBB` bei Alpha=255, sonst `rgba(r,g,b,a)`; `QColorDialog.ShowAlphaChannel` bei `enable_alpha=True`.
* **Dialog-Integration (Entscheidung Benutzer, Option 1):** Das volle Composite wird gerendert; der `indicator_dialog` liest/schreibt **nur den Farbanteil**:
  * `create_schema_control()` (p_type=="color"): `StylePickerWidget(style=LineStyle(color=str(val)), enable_alpha=allow_alpha)`; `ctrl.style_changed.connect(...)`.
  * `_ctrl_value()`: `ctrl.get_style().color`.
  * `collect_params_from_ui()`: `ctrl.get_style().color`.
  * `update_ui_from_params()`: `ctrl.set_color(val)`.

### 3. Verifikation (Schritt 4, headless)
* `python -m py_compile chart/widgets/style_picker_widget.py` → **OK**.
* `python -m py_compile chart/indicator_dialog.py` → **OK**.
* `python -m py_compile chart/widgets/__init__.py` → **OK**.
* Import-Smoke-Test (offscreen, kein `exec()`): `chart.widgets` + `chart.indicator_dialog` importierbar; `LineStyle`-Defaults/custom korrekt; `__all__` aktualisiert → **OK**.

### 4. Hinweise & offene Punkte
* **Style-Werte lowercase vs. Indikator:** Das Widget liefert `solid/dashed/dotted/dashdotted` (Anweisung). Der Indikator-Pfad (`fixed_grid_proximity.py`) nutzt noch `"Solid"` (capitalized) – eine Vereinheitlichung erfolgt bei der späteren Indikator-Anbindung (separates Kapitel).
* **Kompaktheit:** Das Composite ersetzt das bisherige 60×24-Button-Widget; im `QFormLayout`-Kontext wird eine ganze Zeile beansprucht (bewusste Design-Entscheidung, Option 1).

## Implementierungs-Log

- **16.01.02 – Nachgelagerte Arbeiten (Prüfstand, Entscheidungen & Abschluss)**
  - Datum/Uhrzeit: 06.08.2026 14:43 / 14:50 (MD)
  - Entscheidungen Benutzer:
    1. **Finale DB-Bereinigung** durchführen (nicht nur Puffer).
    2. **Tests werden nicht aufbewahrt** – nach Abschluss jedes Phasenkapitels wird der Ordner `test/` aufgeräumt (nur `test/test.py` bleibt) → als neue Architektur-Invariante 10 (Ergänzung 4) dokumentiert.
  - Umgesetzt:
    * Prüfung der drei Punkte von 16.01.02 gegen den Ist-Stand (Code-Inspektion, Tests, DB-Zugriff).
    * Punkt 1 als bereits durch P16.01 umgesetzt bestätigt (kein Code-Aufwand mehr).
    * Punkt 2: Einmaliges Skript `test/cleanup_p16_legacy_rendering_keys.py` → finale DB-Bereinigung (1 Zeile: Set „test", `grid_lines`-params `show_lines`/`line_color` entfernt); Read-only-Verifikation: exakte Key-Prüfung über `service_sets`/`service_sets_trash`/`indicator_presets` → KEINE Legacy-Keys mehr.
    * Punkt 3: Verifikation ausgeführt (31/31 PASS + py_compile OK); danach `test/`-Cleanup gemäß Entscheidung 2 (25 Dateien entfernt, nur `test.py` verbleibt).
  - Validierung: `test/check_p16_s1_decoupling.py` (31/31 PASS); `python -m py_compile` (5 Dateien OK); DB-Read-only-Check (keine Legacy-Keys).
  - Abgeschlossen: 16.01.02 vollständig erledigt (Code, DB, Verifikation, Test-Cleanup, Doku).

- **16.02 – Refactoring ColorButton → StylePickerWidget**
  - Datum/Uhrzeit: 06.08.2026 (MD)
  - Entscheidung Benutzer (Option 1): Das volle Composite wird gerendert; der Dialog liest/schreibt nur den Farbanteil via `get_style()`/`set_color()`.
  - Umgesetzt:
    * `chart/widgets/style_picker_widget.py` neu (Klasse `StylePickerWidget(QWidget)` + `LineStyle`-Dataclass; API `get_style`/`set_style`/`set_color`, Signal `style_changed`; Farb-Logik in Parität zum Alt-ColorButton inkl. Alpha).
    * `chart/widgets/color_button.py` entfernt; `chart/widgets/__init__.py` auf `LineStyle`/`StylePickerWidget` umgestellt.
    * `chart/indicator_dialog.py`: Import + 4 Verwendungsstellen (create_schema_control, _ctrl_value, collect_params_from_ui, update_ui_from_params) auf die neue API umgestellt.
  - Validierung: `py_compile` (3 Dateien OK); Import-Smoke-Test `chart.widgets` + `chart.indicator_dialog` (OK).
  - Offen: Style-Werte-Vereinheitlichung mit dem Indikator-Pfad ("Solid" vs. "solid") bei der späteren Indikator-Anbindung (16.02 Hinweis 4).


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


---

# Phase 16.04 - Generisches MA Template Modul

Erstelle ein generisches, wiederverwendbares Moving-Average-Helper-Modul unter `chart/indicators/utils/ma_template.py`.
Das Modul ist KEIN Analytics-Plugin und schreibt KEINE Daten in den Feature Store. Es dient als reine Utility-Klasse für Indikatoren.

---

### Schritt 1: Dateistruktur anlegen
Erstelle die Datei `chart/indicators/utils/ma_template.py` (inkl. `__init__.py` im `utils`-Ordner, falls nicht vorhanden).

### Schritt 2: Kerntypen & Parameter-Schema definieren
* Definiere `MAType = Literal["SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA", "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"]`.
* Erstelle eine statische Methode `get_ma_parameter_schema()`, die Standard-Parameter für Indikatoren bereitstellt:
  * `ma_type` (Enum/Choice, Default: `"EHMA"`)
  * `period` (int, min: 1, default: 4)
  * `smooth_type` (Enum/Choice, Default: `"EHMA"`)
  * `alpha_factor` (float, min: 0.1, default: 2.0)
  * `dual_color` (bool, default: False)
  * `bull_color` (color, default: `"#2196F3"` wenn dual_color=False, `"#26A69A"` wenn dual_color=True)
  * `bear_color` (color, default: `"#EF5350"`)

### Schritt 3: Vektorisierte Mathematik-Engine implementieren
Implementiere die Klasse `MATemplateEngine` mit folgenden Methoden:

1. `crop_dataframe(df: pd.DataFrame, max_limit: int) -> pd.DataFrame`:
   * Schneidet den DataFrame auf `df.tail(max_limit)` zu.
2. `calculate_ma(source: pd.Series, ma_type: MAType, period: int, alpha_factor: float, volume: Optional[pd.Series] = None) -> pd.Series`:
   * Implementiere alle 12 MA-Typen vektorisiert via NumPy/Pandas.
   * Für `VWMA`: Nutze `volume` (z. B. `df['tick_volume']`). Falls `volume` fehlt/Null ist, Fallback auf `SMA`.
   * 
   | Name | Methode / Logik | Parameter |
   | --- | --- | --- |
   | **Alpha-Smoothed MA Engine** | Berechnung universeller Moving-Average-Linien inklusive optionaler Rekursiv-Glättung. Der Basistyp berechnet die Primär-Serie aus der ausgewählten MA-Familie (`SMA`, `EMA`, `WMA`, `DEMA`, `TEMA`, `HMA`, `EHMA`, `ZLEMA`, `RMA`, `KAMA`, `ALMA`, `VWMA`). Bei aktivierter Glättung (`smoothing > 1`) wird eine zweifach verschachtelte EMA-Filterung mit dynamischem Alpha-Gewichtungsfaktor ($\alpha = \frac{\text{alpha}}{\text{len} + 1}$) angewendet ($EMA_{\text{smooth}}$). Volumengewichtete Typen (`VWMA`) verarbeiten zusätzlich `tick_volume`. | `len` (Int, Def: 4), `ma_type` (Enum: SMA, EMA, WMA, DEMA, TEMA, HMA, EHMA, ZLEMA, RMA, KAMA, ALMA, VWMA, Def: EHMA), `smoothing` (Int, Def: 10), `alpha` (Float, Def: 2.0) |3. `build_color_series(ma_series: pd.Series, dual_color: bool, bull_color: str, bear_color: str) -> List[str]`:
   * Vergleiche $t$ vs. $t-1$.
   * Wenn `dual_color==False`: Verwende durchgehend `bull_color`.
   * Wenn `dual_color==True`: $ma_t \ge ma_{t-1} \rightarrow$ `bull_color`, sonst `bear_color`.
4. `build_chart_payload(time_series: pd.Series, ma_series: pd.Series, colors: List[str]) -> List[Dict[str, Any]]`:
   * Formatiere das Array direkt als LWC-kompatibles Objekt-Array: `[{"time": ts, "value": val, "color": col}, ...]`.
5. * mathematische Zuordnung
# 1. Standard / Unweighted:
# - SMA:   ta.sma(src, len)
# - EMA:   ta.ema(src, len)
# - WMA:   ta.wma(src, len)
# - RMA:   ta.rma(src, len) (Wilder's Smoothing, EMA mit alpha = 1/len)

# 2. Advanced / Zero-Lag / Adaptive:
# - DEMA:  2 * EMA1 - EMA2
# - TEMA:  3 * (EMA1 - EMA2) + EMA3
# - ZLEMA: EMA(src + (src - src[lag]), len) mit lag = (len - 1) // 2
# - KAMA:  Kaufman Adaptive Moving Average (Efficiency Ratio basierte Glättung)
# - ALMA:  Arnaud Legoux Moving Average (Gauß'sche Verteilung mit offset & sigma)

# 3. Hull-Familie:
# - HMA:   WMA(2 * WMA(src, len // 2) - WMA(src, len), sqrt(len))
# - EHMA:  EMA(2 * EMA(src, len // 2) - EMA(src, len), sqrt(len))

# 4. Volumengewichtet:
# - VWMA:  SMA(src * volume, len) / SMA(volume, len)

# 5. Optionale Alpha-EMA-Glättung (auf alle Typen anwendbar, falls smoothing > 1):
# alpha_calc = alpha / (len + 1)
# hma_ema(src, len, smoothing, alpha) =
#     alpha_calc * EMA(src, smoothing) + (1 - alpha_calc) * EMA(hma_ema[t-1], smoothing)


### Schritt 4: Backend-Logiktest erstellen
* Erstelle die Testdatei `test/test_ma_template.py` (keine GUI/PySide6!).
* Teste:
  * Korrekte Längenberechnung aller 12 MA-Typen.
  * Korrekten Farbumschlag ($t$ vs. $t-1$) bei `dual_color=True` und `dual_color=False`.
  * Funktion von `VWMA` mit `tick_volume` aus `market_data.duckdb`.
* Führe den statischen Syntax-Check aus: `python -m py_compile chart/indicators/utils/ma_template.py`.

---

## Konsistenz-Check, Entscheidungen & Ergänzungen (06.08.2026, Doku-Analyse)

> **Status:** ✅ UMGESETZT, COMMITTET & CLEANED UP (06.08.2026). Spezifikation analysiert, Projekt-Ist-Stand verifiziert, Implementierung abgeschlossen (Invariante-1-Backup/Tag `phase16_step4` auf Commit `edc823d`, Umsetzungs-Commit `092cc57`). Verifikation headless über `test/test_ma_template.py` (61/61 Checks PASS, inkl. VWMA-DB-Test gegen echte `market_data.duckdb`). Test-Cleanup gemäß Invariante 10 ausgeführt – `test/` enthält wieder ausschließlich `test/test.py`.

### A. Konsistenz-Check (verifiziert am Ist-Stand des Projekts)

1. **Zielverzeichnis existiert noch nicht:** `chart/indicators/utils/` ist nicht vorhanden (Ist: nur `base_indicator.py`, `fixed_grid_proximity.py`, `__init__.py`). → Wird additiv angelegt (`utils/__init__.py` + `ma_template.py`); `chart/indicators/__init__.py` bleibt bewusst exportfrei (bestehender Kommentar, kein harter Import). ✅ Open/Closed-konform (Invariante 9).
2. **Schema-Konvention ist kompatibel:** Das Projekt nutzt `{"type": "float|int|bool|choice|color", "default", "min"/"max"/"step", "options", "description", "style_type"}` (verifiziert an `_FIXED_GRID_PROXIMITY_SCHEMA` in `chart/indicators/fixed_grid_proximity.py` und am Renderer in `chart/indicator_dialog.py`, Zeilen ~510–576). → „Enum/Choice" wird als `"type": "choice"` mit `"options": list(MAType)` abgebildet; `bull_color`/`bear_color` als `"type": "color", "style_type": "line"`. ✅
3. **LWC-v5-Payload-Vertrag passt:** `[{"time": ts, "value": val, "color": col}, ...]` ist LWC-v5-konform (LineSeries unterstützt Pro-Punkt-`color`). `time` = epoch-Sekunden (Wanduhr-encoded, int) – exakt die Konvention der `hit_circles.bar_time` (`fixed_grid_proximity.py`). Invariante 6 (Wanduhr ohne Berlin-Offset) wird dadurch geerbt. ✅
4. **NaN-Handling ist zwingend im Template:** `chart_win.py` strippt NaN/Inf global via `_clean_nan()` (Zeilen 76–81) vor `json.dumps(allow_nan=False)`. Die Warmup-NaNs der MAs (erste `period-1` Werte) werden aber bereits im Template gefiltert (siehe Ergänzung 3), damit der Payload deterministisch sauber ist. ✅ (Ergänzung)
5. **Volumen-Vertrag passt:** `tick_volume` ist exakt die Spalte aus `FeatureBuilder.load_ohlcv()` / `market_data.duckdb`. → `VWMA`-Aufruf `volume=df["tick_volume"]` ist projektkonform. ✅
6. **Runtime vorhanden:** `.venv` = numpy 2.5.1 / pandas 3.0.5. → Alle 12 Typen sind vektorisierbar; RMA via `ewm(alpha=1/period, adjust=False)`, KAMA rekursiv über NumPy-Array (ER-basiert), ALMA/HMA/WMA via Rolling/Convolve. ✅
7. **Testdatei & Test-Cleanup sind vereinbar:** `test/test_ma_template.py` wird als temporäres Verifikationsskript erzeugt und nach Kapitelabschluss gemäß Invariante 10 entfernt (dauerhaft bleibt nur `test/test.py`). Die Verifikation erfolgt VOR der Bereinigung – konsistent mit dem dokumentierten Ablauf. ✅

### B. Entscheidungen (aus der Anleitung abgeleitet)

- **E1:** Das Modul ist eine reine Utility – **kein** Analytics-Plugin, **kein** Feature-Store-Write (deckt sich mit der P16.01-Philosophie: Services liefern Rohdaten, Darstellung erfolgt additiv im Indikator).
- **E2:** `MAType` = TradingView-konformer 12er-Satz in exakter Reihenfolge: SMA, EMA, WMA, DEMA, TEMA, HMA, EHMA, ZLEMA, RMA, KAMA, ALMA, VWMA.
- **E3:** Defaults: `ma_type="EHMA"`, `period=4`, `alpha_factor=2.0`, `smooth_type="EHMA"`, `dual_color=False`, `bear_color="#EF5350"`.
- **E4:** Alpha-MAs (EHMA, DEMA, TEMA) verwenden den dynamischen Decay $\alpha = \frac{\text{alpha\_factor}}{\text{period} + 1}$ (statt fixer Standardfaktoren).
- **E5:** VWMA ohne gültiges Volumen → Fallback auf SMA.
- **E6:** dual_color-Semantik: Vergleich $t$ vs. $t-1$; `dual_color=False` → durchgehend `bull_color`; `dual_color=True` → $ma_t \ge ma_{t-1}$ = `bull_color`, sonst `bear_color`.
- **E7:** `bull_color`-Default ist bedingt (siehe Ergänzung 2) – `#2196F3` bei `dual_color=False`, `#26A69A` bei `dual_color=True`.

### C. Ergänzungen der Doku (präzisierte Verträge für die Umsetzung)

1. **`smooth_type`-Vertrag (Offenpunkt aus Schritt 2/3):** Das Schema führt `smooth_type` (Default `"EHMA"`), Schritt 3 spezifiziert aber nur den α-Pfad. **Präzisierung:** `smooth_type` ist ein Schema-Vertrag für spätere MA-Indikatoren und wird von `MATemplateEngine` in 16.04 **noch nicht konsumiert** (reine Forward-Compatibility). EHMA wird als $\text{EMA}(\text{HMA}(src, len), len)$ mit α aus E4 implementiert.
2. **Bedingter `bull_color`-Default:** Ein statisches Schema kann den dual_color-abhängigen Default nicht ausdrücken. **Vertrag:** `get_ma_parameter_schema()` liefert `"default": "#2196F3"`; der Konsument wendet `"#26A69A"` an, wenn `dual_color=True` UND `bull_color` nicht vom User gesetzt wurde (leer/None). `build_color_series()` erhält die final aufgelösten Farben als Parameter.
3. **`build_chart_payload`-Vertrag:** Zeilen mit NaN/None in `time` oder `value` werden übersprungen (Warmup); `time` = int epoch-Sekunden (Wanduhr), `value` = float, `color` = String. Ein Längen-Mismatch (`len(colors) < len(ma_series)`) wird defensiv toleriert (fehlende Farbe → Default bull_color).
4. **KAMA/ALMA/RMA-Details:** KAMA nutzt `period` als ER-Periode (Default 10) mit Standard fast `2/(2+1)` und slow `2/(30+1)`; `alpha_factor` entfällt bei KAMA. ALMA nutzt TradingView-Defaults (Offset 0.85, Sigma = `period/6`). RMA = Wilder: `ewm(alpha=1/period, adjust=False)`.
5. **VWMA-Nullschutz:** Volumen wird mit `fillna(0)` normalisiert; ist die rollierende Volumen-Summe eines Fensters ≤ 0, fällt dieses Fenster auf den SMA-Wert zurück (kein Division-by-Zero).
6. **Testabdeckung `test/test_ma_template.py`:** Längen-/Paritätsprüfung aller 12 Typen gegen eine einfache Referenzimplementierung (defensive Formeln), Farbumschlag (E6), `VWMA` mit `tick_volume` aus `market_data.duckdb` (read-only via `DbPool`, nur Lesen – keine Schreibzugriffe auf `data/`), NaN-Filter von `build_chart_payload`, VWMA-Fallback (E5), Warmup-Länge = `period-1`.

---

## Implementierungs-Log Phase 16.04 (06.08.2026 21:09)

**Schritt 1–3 – Modul erstellt (`chart/indicators/utils/ma_template.py` + `utils/__init__.py`):**
* `MAType`-Literal + `MA_TYPES`-Tuple (12er-Satz, E2), `MATemplateEngine` (stateless, ohne Engine-Abhängigkeiten).
* `get_ma_parameter_schema()` – 7 Parameter in Projekt-Schema-Konvention (`choice`/`int`/`float`/`bool`/`color`, `style_type`), Defaults nach E3.
* `resolve_bull_color()` – bedingter bull-Default (E7/Ergänzung 2): Schema `#2196F3`, dual=True + ungesetzt → `#26A69A`.
* `crop_dataframe()` – `df.tail(max_limit)`, `calculate_ma()` – alle 12 Typen vektorisiert (SMA/WMA/HMA/ALMA/VWMA via np.convolve, EMA/RMA/DEMA/TEMA/EHMA via pandas ewm, KAMA ER-basiert mit kompakter Schleife, ZLEMA mit lag), α-Pfad nach E4.
* `build_color_series()` – dual_color-Semantik (E6), NaN-Vergleich = bull. `build_chart_payload()` – LWC-v5-Array, NaN/Inf-Skip (Warmup), Mismatch-Toleranz (Ergänzung 3).
* **Bugfix-Faltung:** `np.convolve` wendet Gewichte rückwärts an – `_wma_values` nutzt daher absteigende Gewichte `[p..1]`, `_alma_values` faltet `weights[::-1]` (Parität zur Referenzschleife).
* **pandas-3.0-Kompatibilität:** `ewm(...).to_numpy()` liefert read-only Arrays → `_ema_alpha/_ema_span/_rma` liefern beschreibbare Kopien (wichtig für ZLEMA-Warmup-Overwrite).

**Schritt 4 – Backend-Logiktest (`test/test_ma_template.py`, temporär):**
* **61/61 Checks PASS** – Schema-Defaults & resolve_bull_color (S1–S12), Länge/Warmup aller 12 Typen (L1/L2, typspezifisch tolerant: EWM-Typen seeden ab Index 0), volle Parität aller 12 Typen gegen defensive Referenzimplementierung (P1, period=10), VWMA mit echten `tick_volume`-Daten aus `market_data.duckdb` (D1–D3, weicht vom SMA ab), VWMA-Fallback exakt SMA (E5), Null-Volumen-SMA-Fallback (E5b), Farbumschlag (C1–C3), Payload-Vertrag (Q1–Q5), crop/Edge-Cases (R1–R4).
* Verifikation: `python -m py_compile` auf Modul + `utils/__init__.py` + Test → OK; Import-Smoke `chart.indicators.utils.ma_template` → OK.

**Cleanup (Invariante 10) – AUSGEFÜHRT (06.08.2026):** `test/test_ma_template.py` wurde nach bestätigter Verifikation (61/61 PASS, VOR der Bereinigung) entfernt. `test/` enthält wieder ausschließlich `test/test.py` (dauerhafter Test-Harness). Das Kapitel Phase 16.04 ist damit vollständig abgeschlossen.

---
# 16.05 Prework: Generische Render-Engine für LWC v5 (Frontend Refactoring)

## 1. Konzept & Zielsetzung (Ultrakompakt)
* **Problem:** `chart/js/03_chart_rendering.js` enthält hartcodierte Branches (z. B. `indid == "indfixedgridproximity"`) und spezifische Canvas-Functions (`renderGridLines`, `renderGridCircles`)[cite: 1, 4].
* **Lösung:** Entfernung aller Indikator-spezifischen `if/else`-Branches. Einführung des generischen Grafik-Primitivs `renderLineSeries()` für unbegrenzte, hochperformante Linien-Drawings (MAs, Bänder, Trends) in Lightweight Charts v5[cite: 1].

---

## 2. IDE-AI Anweisung 

Führe ein Refactoring der Chart-Rendering-Engine durch, um hartcodierte Indikator-IDs zu entfernen und die generische Aufruf-Pipeline für Grafik-Primitive (`lines`, `markers`) zu etablieren.

### Schritt 1: Python Bridge-Pass-Through bereinigen (`chart/chart_win.py`)
* Entferne alle hartcodierten Fallunterscheidungen nach `indicator_id` (z. B. `if ind_id == "indfixedgridproximity"`) beim Aufruf von `runJavaScript`[cite: 1, 4].
* Leite das von den Indikatoren generierte `chart_render_payload` (Dict mit Keys `"lines"`, `"hit_circles"` / `"markers"`) **1:1 als generisches JSON-Objekt** an die JS-Funktion `applyChartRenderPayload(payload)` weiter[cite: 1].

---

### Schritt 2: Generische Render-Pipeline in JS erstellen (`chart/js/03_chart_rendering.js`)

1. **Neue Haupt-Schnittstelle `applyChartRenderPayload(payload)` erstellen:**
   * Empfängt das JSON-Payload und verteilt die Sub-Arrays an die jeweiligen Grafik-Primitive[cite: 1]:
     * `payload.lines` $\rightarrow$ ruft `renderLineSeries(payload.lines)` auf[cite: 1].
     * `payload.hit_circles` / `payload.markers` $\rightarrow$ ruft `renderMarkers(payload.hit_circles)` auf[cite: 1].

2. **Generischen Linien-Renderer `renderLineSeries(linesArray)` implementieren:**
   * Vergewissere dich, dass pro Eintrag im `linesArray` (`{ id, data, color, width, style }`) dynamisch eine LWC v5 `LineSeries` angelegt oder per `setData()` aktualisiert wird[cite: 1].
   * Verwalte aktive LineSeries in einer JS-Registry (`_activeLineSeries[id]`), damit inaktive/gelöschte MAs/Linien bei Payloaded-Updates sauber per `chart.removeSeries()` entfernt werden[cite: 1].

3. **Legacy-Cleanup:**
   * Binde die bisherigen Grid-Linien und Circles als Unterfälle in die generische Schnittstelle ein[cite: 1].
   * Lösche hartcodierte String-Checks auf alte Indikator-Namen[cite: 1, 4].

---
### ⚠️ Wichtiger Fix für VWMA: Volumendaten in `fetch_historical_candles` selektieren

**Problem:** `MarketDataRepository.fetch_historical_candles()` in `db_service.py` selektiert aktuell nur `open, high, low, close`. Das im DataFrame fehlende `tick_volume` führt beim `VWMA` zu einem Fallback.

**Anpassung in `db_service.py` (`MarketDataRepository`):**
1. Erweitere die SQL-Abfrage in `fetch_historical_candles()` um `tick_volume`:
   SELECT EXTRACT('epoch' FROM "time")::BIGINT AS time_epoch,
          open, high, low, close, tick_volume 
   FROM ohlcv_bars ...
---
### Schritt 3: Verifikation & System-Check (Ohne GUI)
* Führe den Node.js Syntax-Check auf allen geänderten JS-Dateien aus:
  * `node --check chart/js/01_core.js`[cite: 1]
  * `node --check chart/js/03_chart_rendering.js`[cite: 1]
* Führe das bestehende Test-Skript aus: `python test/check_html_template.py`[cite: 1].

--- 

# Phase 16.05 - Multi MA Indikator

Erstelle den Multi-MA-Indikator unter `chart/indicators/multi_ma.py`.
Der Indikator erbt von `BaseIndicator` und nutzt die `MATemplateEngine` aus Phase 16.04 (`chart/indicators/utils/ma_template.py`).

Entscheidungen
 - D1: Additiver Integrationspfad – Registry-Eintrag + 2 Branches in chart_win + neuer Button btn_indicator_ma (Text "MA") in chart_win.ui (Muster btn_indicator_grid_liquidity)
 - D4: Kontrastfarben MA2–8: Blau/Orange/Violett/Gelb/Rot/Cyan/Blaugrau (MA1 teal #26A69A bleibt Führung)
 - D5: maX_smooth_type bleibt Forward-Compat-Vertrag (nicht konsumiert, wie 16.04)
 - D6: calculate() → {"maLines": [...]}; build_chart_render_payload(df, params) als eigene Methode
 - D7: Defaults: MA1 EHMA/4/alpha 2.0/dual=False, MA2–8 EMA/10·X/alpha 2.0, alle show=False (außer MA1)

---

### 1. Parameter-Schema & Identität
* **`indicator_id`**: `"ind_moving_averages"`
* **`display_name`**: `"Multi Moving Average (8x)"`
* **`parameter_schema`**:
  * **MA 1 (Spezial-Führungslinie mit DualColor):**
    * `show_ma1` (bool, default: True)
    * `ma1_type` (Enum, default: `"EHMA"`)
    * `ma1_period` (int, min: 1, default: 4)
    * `ma1_smooth_type` (Enum, default: `"EHMA"`)
    * `ma1_alpha` (float, min: 0.1, default: 2.0)
    * `ma1_dual_color` (bool, default: False)  <-- NUR FÜR MA 1!
    * `ma1_bull_color` (color, default: `"#26A69A"`)
    * `ma1_bear_color` (color, default: `"#EF5350"`)
  * **MA 2 bis MA 8 (Standardschleife $X = 2..8$):**
    * `show_maX` (bool, default: False für MA2..8)
    * `maX_type` (Enum, default: `"EMA"`)
    * `maX_period` (int, min: 1, default: 10 * X)
    * `maX_smooth_type` (Enum, default: `"EMA"`)
    * `maX_alpha` (float, min: 0.1, default: 2.0)
    * `maX_color` (color, default: individuelle Kontrastfarben)  <-- Keine dual_color / bear_color Schalter!

---

### 2. Logik & Payload-Erzeugung (`build_chart_render_payload`)
1. **Daten-Zuschnitt:** Schneide den OHLCV-DataFrame auf `AppSettings.chart_candle_limit` zu[cite: 4].
2. **Schleife über alle 8 MAs:**
   * Prüfe `show_maX`. Wenn `False`, überspringe die Linie.
   * Berechne die MA-Series über `MATemplateEngine.calculate_ma(...)`.
   * **Farb-Zuweisung:**
     * Für **MA 1**: Nutze `MATemplateEngine.build_color_series(...)` basierend auf `ma1_dual_color`, `ma1_bull_color` und `ma1_bear_color`.
     * Für **MA 2..8**: Erzeuge eine einfarbige Farbliste mit `maX_color`.
   * Formatiere die Linie als LWC-kompatibles Objekt-Array.
3. **Rückgabe:** Gib das `chart_render_payload` mit allen aktiven Linien-Daten an das Frontend ab[cite: 1].

---
### ⚠️ Wichtiger Hinweis zur Frontend-Schnittstelle (Prework-Anpassung)
Durch das **16.05 Prework** ist die Chart-Rendering-Engine (`03_chart_rendering.js`) vollständig entkoppelt:
* Es gibt **keine** Indikator-spezifischen JS-Aufrufe mehr (`if ind_id == ...`)[cite: 1, 4].
* Der Indikator übergibt sein `chart_render_payload` direkt an die generische Pipeline `applyChartRenderPayload(payload)`[cite: 1].

### Erzeugungs-Regel für `chart_render_payload` im Multi-MA Indikator:
Jeder aktive MA (1–8) muss als eigener Linien-Eintrag im `lines`-Array des Payloads geliefert werden[cite: 1]:

# Beispiel-Struktur des generierten chart_render_payload:
{
    "lines": [
        {
            "id": "ma1",                      # Eindeutige ID pro Linie
            "data": [                        # LWC-kompatible Datenpunkte
                {"time": 1770000000, "value": 24.50, "color": "#26A69A"},
                {"time": 1770000060, "value": 24.52, "color": "#EF5350"}
            ],
            "width": 2,                      # Strichstärke
            "style": "solid"                 # Linienstil
        },
        {
            "id": "ma2",
            "data": [ ... ],                 # Farbwerte aus ma2_color
            "width": 1,
            "style": "solid"
        }
        # Weitere aktive MAs (3..8)...
    ]
}

### ⚠️ Wichtige Hinweise zur Frontend-Schnittstelle & Zeit-Mapping (Prework-Anpassung)

1. **Generische Render-Engine (Prework):**
   * Die Chart-Engine (`03_chart_rendering.js`) ist vollständig entkoppelt – keine Indikator-spezifischen JS-Aufrufe mehr (`if ind_id == ...`)[cite: 1, 4].
   * Der Indikator übergibt sein `chart_render_payload` direkt an die generische Pipeline `applyChartRenderPayload(payload)`.

2. **Zeit-Mapping (`real → kontinuierlich`):**
   * Die Datenpunkte im Payload müssen exakt auf die kontinuierliche Zeitachse des Charts gemappt sein (`timeRealToCont`), damit die MA-Linien lückenlos und deckungsgleich auf den Candles liegen[cite: 1].
   * Das JS-Frontend nutzt `resolveRealTime(ts)`[cite: 1], um sicherzustellen, dass jeder Datenpunkt exakt einem realen Candle-Zeitstempel zugeordnet ist[cite: 1].

### Erzeugungs-Regel für `chart_render_payload` im Multi-MA Indikator:
Jeder aktive MA (1–8) wird als eigener Linien-Eintrag im `lines`-Array des Payloads geliefert[cite: 1]:

# Beispiel-Struktur des generierten chart_render_payload:
{
    "lines": [
        {
            "id": "ma1",                      # Eindeutige ID pro Linie
            "data": [                        # LWC-kompatible Datenpunkte (gemappte Wanduhr-Epochs)
                {"time": 1770000000, "value": 24.50, "color": "#26A69A"},
                {"time": 1770000060, "value": 24.52, "color": "#EF5350"}
            ],
            "width": 2,                      # Strichstärke
            "style": "solid"                 # Linienstil
        },
        {
            "id": "ma2",
            "data": [ ... ],                 # Farbwerte aus ma2_color
            "width": 1,
            "style": "solid"
        }
        # Weitere aktive MAs (3..8)...
    ]
}
---

### 3. Persistenz & System-Integration
* Das Fenster- und Preset-System speichert/lädt alle Parameter automatisch über den `StateManager` (`indicator_presets`)[cite: 4].
* Registriere den Indikator ordnungsgemäß, sodass er im Chart-Fenster-Dialog auswählbar ist[cite: 1, 4].

---

### 4. Verifikation (Backend ohne GUI)
* Erstelle die Testdatei `test/test_multi_ma_indicator.py` (keine GUI/PySide6!).
* Prüfe:
  * Korrekte Generierung des Payloads für MA 1 mit `dual_color=True` vs. `dual_color=False`.
  * Einwandfreie Abarbeitung aller 8 MAs (Sichtbarkeit an/aus).
* Führe den statischen Syntax-Check aus: `python -m py_compile chart/indicators/multi_ma.py`.
* 
---

---

# Phase 16.05 – Konsistenz-Check, Entscheidungen & Ergänzungen (06.08.2026, Doku-Analyse)

> **Status:** Spezifikation analysiert, Projekt-Ist-Stand verifiziert, **Entscheidungen F1–F4 beschlossen (Benutzer-Freigabe 06.08.2026)**. Implementierung erfolgt erst auf ausdrücklichen Startbefehl. Vor der Umsetzung wird gemäß Invariante 1 ein Git-Commit/Tag gesetzt (Vorschlag: `phase16_step5`). **Prework-Anweisung (Generische Render-Engine) eingearbeitet – siehe unten.**

## 16.05 Prework – Konsistenz-Check (Generische Render-Engine, verifiziert am Ist-Stand)

### P-A. Ist-Stand-Verifikation

1. **Problemstellung bestätigt:** `chart/chart_win.py` enthält **zwei hartcodierte** `if ind_id == "ind_fixed_grid_proximity"`-Branches (Z.~607 in `render_indicators()`, Z.~772 in `_do_refresh_chart_data()`); `_apply_grid_render()` ruft `renderGridLines`/`renderGridCircles` direkt per `runJavaScript` auf (Z.~678-682). `chart/js/03_chart_rendering.js` hat nur die spezifischen `renderGridLines` (Preislinien) / `renderGridCircles` (Marker) – **kein** generisches Zeitreihen-Primitiv. ✅ (Refactoring-Bedarf real)
2. **`applyChartRenderPayload`/`renderLineSeries`/`renderMarkers` existieren NOCH NICHT** in `03_chart_rendering.js` – werden additiv neu erstellt. ✅ (Anweisung konsistent)
3. **`resolveRealTime(ts)` existiert** in `chart/js/02_time_utils.js` (Z.~87), inkl. `toReal`/`toCont`/`_rebuildTimeMaps`. ✅ (Prework-Referenz korrekt)
4. **`fetch_historical_candles` selektiert KEIN `tick_volume`** (`db_service.py`, Z.~558: nur `time_epoch, open, high, low, close`). → Prework-VWMA-Fix ist real und erforderlich. ⚠️
5. **Node.js verfügbar:** `node v24.18.0` → `node --check` auf JS-Dateien ausführbar. ✅
6. **`test/check_html_template.py` existiert NICHT mehr** (Invariante-10-Cleanup in 16.04). Prework Schritt 3 referenziert eine entfernte Datei. ⚠️ (Offene Frage F2)

### P-B. Entscheidungen Prework (aus der Anleitung abgeleitet)

- **P-D1 – Payload-Durchleitung 1:1:** `chart_win.py` baut pro Refresh/Re-Render das **generische Payload-Dict** `{"lines": [...], "hit_circles": [...]}` (aggregiert über alle aktiven Indikatoren) und reicht es per `applyChartRenderPayload(payload)` an JS. Die hartcodierten `if ind_id == ...`-Branches entfallen; der Indikator-spezifische Kreis-Mapping-Schritt (`_time_real_to_cont`) wird generisch über alle `hit_circles`-Zeiten aller Indikatoren angewendet.
- **P-D2 – JS-Dispatcher:** `applyChartRenderPayload(payload)` routet `payload.price_lines → renderPriceLines(price_lines)` (Preislinien, F1), `payload.lines → renderLineSeries(lines)` (LineSeries-Registry), `payload.hit_circles → renderMarkers(hit_circles)`. `renderLineSeries` pflegt eine Registry `_activeLineSeries[id]` (incrementelles `setData`, `removeSeries` für verschwundene IDs). `renderMarkers` übernimmt die bestehende inkrementelle Circle-Logik (`renderGridCircles` wird Unterfall/Refactoring).
- **P-D3 – Legacy-Unterfälle:** Die bestehenden Grid-Preislinien (`createPriceLine`, Felder `price/color/width/style/is_custom`) und Circles werden in die generische Pipeline eingebunden (Legacy-Cleanup gemäß Anweisung) – Preislinien unter dem neuen Key `price_lines` (F1), Circles unter `hit_circles` (unverändert).
- **P-D4 – VWMA-Fix (revidiert D3 aus 16.05-Analyse):** `fetch_historical_candles` wird um `tick_volume` erweitert. `df_data` erhält damit die Spalte `tick_volume` → der Multi-MA-Indikator kann `VWMA` mit echten Volumendaten rechnen (`volume=df["tick_volume"]`). Der frühere D3 („VWMA→SMA-Fallback") wird **obsolet** – der Template-Fallback bleibt als Defensivschutz (NaN/Null-Volumen), ist aber nicht mehr der Regelpfad.

### P-C. Ergänzungen der Doku (präzisierte Verträge für Prework-Umsetzung)

1. **`lines`/`price_lines`-Trennung (F1-Beschluss, ersetzt Feld-Dispatch):** Der frühere Vorschlag „Dispatch über `data` vs. `price` im selben `lines`-Array" ist **durch die Benutzerentscheidung F1 überholt**: Grid-Preislinien erhalten einen **eigenen `price_lines`-Key**, Multi-MA-LineSeries den `lines`-Key. Kein Feld-Dispatch, kein `kind`-Feld nötig. Routing in `applyChartRenderPayload`: `payload.price_lines → renderPriceLines()`, `payload.lines → renderLineSeries()`, `payload.hit_circles → renderMarkers()`. (Details siehe Abschnitt „Entscheidungen F1–F4".)
2. **Merging über alle Indikatoren:** chart_win aggregiert die Payloads **aller aktiven** Indikatoren in ein einziges `{"lines": [...], "price_lines": [...], "hit_circles": [...]}`. Kollisionen sind ausgeschlossen: Grid-Indikator liefert `price_lines` + `hit_circles`; Multi-MA liefert `lines` (LineSeries mit `id: "ma1".."ma8"`). Die JS-Registry ist id-basiert → inkrementelles Update über beide Pfade hinweg.
3. **Serializer-Umbau (F4-Beschluss):** `GridDataSerializer`/`_serialize_and_render_grid` werden auf das generische Payload-JSON umgestellt – **Threading-Muster exakt beibehalten** (QThread + done-Signal + Generations-Guard), nur das Payload-Format ändert sich (`done = Signal(str, int)` mit payload_json statt getrennte lines_json/circles_json). Der `update_package`-Pfad (`_do_refresh_chart_data`) erhält ein `chartRenderPayload`-Feld (analog `gridLines`/`gridCircles`), `applyFullChartUpdate` ersetzt Schritt 5+6 durch einen `applyChartRenderPayload`-Aufruf.
4. **Live-Overlay-Pfad unberührt:** `get_live_overlays` + `applyLiveOverlays` (04_live_updates.js) bleiben (bereits generisch über `kind`). Multi-MA liefert keine Live-Overlays (Basis-Default `[]`).
5. **Kein `btn_indicator_ma`-Sonderpfad mehr nötig:** Durch die generische Pipeline entfällt der frühere D1-Teil „2 Branches + renderMALines + Serializer". Die Registrierung (`self.indicators`-Dict) und der Button (`ui/chart_win.ui`, Text „MA") bleiben wie in D1. `D6` wird angepasst: `calculate()` → `{"lines": [...]}` (statt `{"maLines": [...]}`), jede Linie `{id, data, width, style, title}`; `build_chart_render_payload(df, params)` bleibt eigene Methode.

### A. Konsistenz-Check (verifiziert am Ist-Stand des Projekts)

1. **Basis vorhanden:** `MATemplateEngine` aus P16.04 (`chart/indicators/utils/ma_template.py`) existiert und ist committet (`092cc57`) – `calculate_ma` (12 Typen, α-Pfad E4, VWMA-SMA-Fallback E5), `build_color_series` (dual_color-Semantik E6), `build_chart_payload` (LWC-v5-Array `[{time, value, color}]`), `crop_dataframe` (tail), `get_ma_parameter_schema` + `resolve_bull_color`. ✅
2. **`AppSettings.chart_candle_limit` existiert** (`config/app_settings.py`, Default 3000). `chart_win` lädt OHLCV bereits mit `limit=self.settings.chart_candle_limit`; `df_data` (pd.DataFrame aus clean_candles) enthält Spalten `time/open/high/low/close` mit **echten Wanduhr-Epochs** (`fetch_historical_candles`, `db_service.py`). ✅
3. **BaseIndicator-Vertrag erfüllbar:** `indicator_id`, `display_name`, `default_params` (Properties) + `calculate(df, params)` (abstract) müssen implementiert werden. Der Dialog erkennt selbst-contained-Indikatoren über `parameter_schema` + `plugin_id` (Branch 1, `indicator_dialog._get_plugin`) – exakt das Muster von `FixedGridProximityIndicator` (`parameter_schema`, `parameter_order`, `base_parameter_schema`, `default_params`, `param_options`, `param_labels`, `param_layout`, `plugin_id`). ✅
4. **LWC-v5-Payload passt:** `build_chart_payload` liefert `[{time, value, color}]` – direkt als `LineSeries.setData()` verwendbar (Pro-Punkt-`color`, v5-konform). Zeit = reale Wanduhr-Epochs, müssen aber vor dem JS-Render auf **kontinuierliche Zeiten** gemappt werden (wie `grid_circles` via `self._time_real_to_cont`). ⚠️ (Ergänzung 1)
5. **KEIN generischer Time-Series-Renderer im JS:** `renderGridLines` zeichnet **horizontale Preislinien** (`createPriceLine`), `renderGridCircles` unsichtbare LineSeries mit Markern – **kein** Pfad für Zeitreihen-Linien (MA). Der bestehende `ind_id == "ind_fixed_grid_proximity"`-Branch in `chart_win` (`render_indicators()` ~Z.595 und `_do_refresh_chart_data()` ~Z.770, jeweils hartcodiert) ist die aktuelle Integrationsstelle. → Additive JS-Renderfunktion + additive chart_win-Branches nötig (Open/Closed, Invariante 9). ⚠️ (Ergänzung 2)
6. **`df_data` enthält KEIN `tick_volume`:** `fetch_historical_candles` selektiert nur `time/open/high/low/close`. VWMA im Multi-MA hat damit keinen Volumen-Input aus dem Chart-DF → Entscheidung D3. ⚠️
7. **Registrierung/Button:** chart_win-Registry (`self.indicators` Dict, Z.~187) + UI-Button `btn_indicator_grid_liquidity` in `ui/chart_win.ui` (Z.~178, 28×28, EventFilter Rechtsklick→Einstellungen) sind der etablierte Muster-Pfad. Für MA-Button additiv erweiterbar. ✅ (Ergänzung 3)
8. **Preset-Persistenz generisch:** `StateManager.indicator_presets` + `_PresetItemAdapter` (indicator_dialog) greifen automatisch, sobald der Indikator in Registry + Dialog erreichbar ist. Kein Sonderfall nötig. ✅
9. **`smooth_type`-Vertrag (aus P16.04, Ergänzung 1):** `maX_smooth_type` ist Schema-Vertrag (Forward-Compatibility) und wird von `MATemplateEngine.calculate_ma` **nicht konsumiert** – die Berechnung läuft über `maX_type`. Wird für 16.05 identisch übernommen (Entscheidung D5). ✅
10. **`test/test.py` unberührt:** Der permanente Harness konstruiert kein `ChartWindow` – die Registry-Erweiterung bricht keine bestehenden Checks. ✅

### B. Entscheidungen (aus der Anleitung abgeleitet)

- **D1 – Integrationspfad (additiv, Invariante 9):** `chart_win.py` erhält **einen** neuen Registry-Eintrag `"ind_moving_averages": MultiMovingAverageIndicator()` und **zwei additive** Branches:
  * `render_indicators()`: `elif ind_id == "ind_moving_averages"` → MA-Linien aus `calculate()` über neue `_serialize_and_render_ma_lines()` an JS.
  * `_do_refresh_chart_data()`: `maLines`-Feld im `update_package` sammeln (analog `gridLines`/`gridCircles`), damit MA-Linien auch nach Voll-Rebuild erhalten bleiben.
  * `ui/chart_win.ui`: neuer Button `btn_indicator_ma` (additive XML-Elemente) + Verdrahtung in chart_win (toggle/settings/eventFilter/Style) – exakt das Muster von `btn_indicator_grid_liquidity`.
- **D2 – JS-Renderer (additiv):** Neue Funktion `renderMALines(maLines)` + `clearMALines()` in `chart/js/03_chart_rendering.js` (incrementelles Upsert je MA-Linie per `setData`, analog `renderGridCircles` – kein removeSeries/addSeries für unveränderte Linien). Aufruf in `applyFullChartUpdate` als neuer Schritt (nach Schritt 6). `maLines`-Format: `[{id, title, color, data: [{time, value, color}]}]` – `data` direkt LWC-`LineSeries.setData`-Input (Zeiten vorher in chart_win real→kontinuierlich gemappt).
- **D3 – VWMA ohne `tick_volume`:** `df_data` hat kein Volumen. **Entscheidung:** VWMA fällt auf SMA zurück (E5-Fallback des Templates, dokumentiert). Ein separates Volumen-Nachladen via DB ist eine spätere optionale Erweiterung (read-only via `DbPool` + `set_context`), **kein** Bestandteil von 16.05 (kein Kern-Eingriff in `fetch_historical_candles`).
- **D4 – Kontrastfarben MA2..8 (individuelle Defaults):** `maX_color`-Defaults (TradingView-kontrastreich, MA1 teal `#26A69A` bleibt Führungslinie):
  * MA2 `#2962FF` (Blau), MA3 `#FF6D00` (Orange), MA4 `#AB47BC` (Violett), MA5 `#FDD835` (Gelb), MA6 `#FF5252` (Rot), MA7 `#00E5FF` (Cyan), MA8 `#B0BEC5` (Blaugrau).
- **D5 – `smooth_type` nicht konsumiert:** Schema enthält `maX_smooth_type` (Forward-Compatibility, P16.04-Ergänzung 1), `calculate` nutzt nur `maX_type`.
- **D6 – `chart_render_payload`-Schlüssel:** `calculate()` liefert `{"maLines": [...]}` (additiv, kollisionsfrei zu `lines`/`hit_circles`). `build_chart_render_payload(df, params)` wird als eigene Methode implementiert (analog fixed_grid_proximity), `calculate()` ruft sie intern auf.
- **D7 – Defaults:** MA1 `show=True`, `ma1_type="EHMA"`, `ma1_period=4`, `ma1_alpha=2.0`, `ma1_dual_color=False`, `ma1_bull_color="#26A69A"`, `ma1_bear_color="#EF5350"`; MA2..8 `show=False`, `maX_type="EMA"`, `maX_period=10*X`, `maX_alpha=2.0`, Farben nach D4.

### C. Ergänzungen der Doku (präzisierte Verträge für die Umsetzung)

1. **Zeit-Mapping real→kontinuierlich:** MA-Linien-Zeiten sind reale Wanduhr-Epochs. Vor der JS-Übergabe werden sie via `self._time_real_to_cont.get(ts, ts)` gemappt (gleicher Mechanismus wie `hit_circles`). Ohne Mapping lägen die Linien an falschen x-Positionen (kontinuierliche Skala).
2. **Zwei Render-Pfade konsistent halten:** `render_indicators()` (Param-/Toggle-Änderungen ohne Voll-Rebuild) UND `update_package.maLines` (Voll-Rebuild) müssen dieselben Daten liefern – beide Pfade nutzen dieselbe Sammel-Methode im chart_win, damit kein Doppel-Pflege-Problem entsteht.
3. **Schema-Erzeugung programmatisch:** Das 56+-Param-Schema (8 MAs × 7 Keys) wird in einer Schleife `for x in range(1, 9)` generiert (MA1 mit `dual_color`/`bull`/`bear`, MA2..8 mit `maX_color`), nicht manuell ausgeschrieben – Fehlerquelle minimieren. `param_labels`/`param_layout` analog generisch (Gruppen „MA 1 (Führung)" und „MA 2..8").
4. **NaN-Handling:** `build_chart_payload` (P16.04) skippt Warmup-NaNs bereits – jede MA-Linie beginnt dadurch deterministisch bei ihrem ersten definierten Wert. Kein zusätzliches Cleanup im Indikator nötig.
5. **`set_context`/`set_settings` implementieren:** Wie `FixedGridProximityIndicator` (duck-typed via `hasattr` in chart_win) – `set_context(symbol, timeframe)` und `set_settings(settings)` (Injection der AppSettings, sonst lazy aus StateManager). Wird für D3 (späteres Volumen-Nachladen) und den `chart_candle_limit`-Zugriff vorbereitet.
6. **Testabdeckung (F2-Beschluss, gezielter Logik-Test in `test/test.py` – permanente Harness statt temporärer `test/test_multi_ma_indicator.py`):** Schema-Vollständigkeit (56 Parameter, Defaults MA1/MA2..8), Payload MA1 `dual_color=True` vs `False` (Farbumschlag korrekt), alle 8 MAs einzeln + kombiniert (show an/aus), `crop_dataframe` auf `chart_candle_limit`, LWC-Konformität (`time` int, `value` float, `color` str), VWMA mit `tick_volume` aus `df_data` (F3), `py_compile` auf `multi_ma.py` + Import-Smoke. Prework-Logik (Payload-Aggregation, Key-Routing `lines`/`price_lines`/`hit_circles`, tick_volume-Spalte) wird als gezielter Logik-Test in `test/test.py` abgedeckt.

---

## Entscheidungen F1–F4 – BESCHLOSSEN (Benutzer-Freigabe 06.08.2026)

> Verbindliche Vorgaben für die Umsetzung von 16.05 Prework + Multi-MA. Alle offenen Fragen sind damit beantwortet.

### F1 – Eigener `price_lines`-Key (beschlossen)

**Entscheidung:** Grid-Preislinien erhalten einen eigenen `price_lines`-Key; der `lines`-Key ist ausschließlich für Zeitreihen-LineSeries (Multi-MA) reserviert.

**Konsequenzen (verbindlich):**
1. **Generisches Payload-Schema:** `{"lines": [...], "price_lines": [...], "hit_circles": [...]}`.
   * `price_lines` = horizontale Preislinien (Grid-Legacy, Felder `price/color/width/style/is_custom`) → `candleSeries.createPriceLine(...)`.
   * `lines` = Zeitreihen-LineSeries (Multi-MA, `{id, data, width, style, title}`) → LWC-`LineSeries` via `_activeLineSeries[id]`.
   * `hit_circles` = Marker (Grid-Legacy, unverändert).
2. **`fixed_grid_proximity.py`:** `build_chart_render_payload()` und `calculate()` liefern den Grid-Render-Payload künftig mit **`price_lines`** statt `lines` (zusätzlich `hit_circles` + `status_info`). `_cached_grid_lines`-Logik (Live-Overlays) bleibt unverändert.
3. **chart_win:** aggregiert die Payloads aller aktiven Indikatoren generisch (Keys `lines`/`price_lines`/`hit_circles` gemerged) – keine Indikator-spezifischen Branches mehr.
4. **JS-Dispatcher `applyChartRenderPayload(payload)`:** `payload.price_lines → renderPriceLines()`, `payload.lines → renderLineSeries()`, `payload.hit_circles → renderMarkers()`. **Kein Feld-Dispatch, kein `kind`-Feld.**

### F2 – Verifikation ohne eigenständige Check-Skripte (beschlossen)

**Entscheidung:** Verifikation ausschließlich über `node --check` (geänderte JS-Dateien) + `python -m py_compile` (geänderte Python-Dateien) + **gezielter Logik-Test in `test/test.py`** (permanenter Harness).

**Konsequenzen (verbindlich):**
1. `test/check_html_template.py` wird **nicht** neu angelegt (Prework Schritt 3 entfällt in dieser Form).
2. **16.05 Schritt 4 (Multi-MA):** Die geforderte `test/test_multi_ma_indicator.py` wird **nicht** als eigene Datei angelegt – die Tests laufen als gezielte Logik-Tests in `test/test.py` (Benutzerentscheidung F2 hebt die Schritt-4-Formulierung auf; Invariante 10 wird dadurch strikt eingehalten, kein Cleanup-Schritt nötig).
3. Prework-Logik (Payload-Aggregation, Key-Routing, tick_volume-Spalte) wird in `test/test.py` als gezielter Logik-Test abgedeckt.

### F3 – `tick_volume` NaN → 0 (beschlossen)

**Entscheidung:** Normalisierung NaN/None → 0; die Candle bleibt gültig.

**Konsequenzen (verbindlich):**
1. `fetch_historical_candles()` selektiert `tick_volume` (ohne `IS NOT NULL`-Filter; WHERE-Bedingung prüft weiterhin nur OHLC).
2. NaN/None-`tick_volume` verwirft die Candle **nicht**; die Normalisierung auf 0 erfolgt beim Aufbau von `clean_candles`/`df_data` (damit `json.dumps(allow_nan=False)` nie an `tick_volume` scheitert).
3. Die VWMA-Engine normalisiert zusätzlich intern NaN→0 (P16.04 Ergänzung 5) – Doppel-Absicherung.
4. Multi-MA nutzt `df["tick_volume"]` (mit `fillna(0)`-Garantie aus Punkt 2) für `VWMA`.

### F4 – Threading-Muster exakt beibehalten (beschlossen)

**Entscheidung:** `GridDataSerializer` (QThread + done-Signal + Generations-Guard) bleibt unverändert; **nur das Payload-Format** wird angepasst.

**Konsequenzen (verbindlich):**
1. `GridDataSerializer.done = Signal(str, int)` (payload_json, gridGen) statt getrennter `lines_json`/`circles_json`.
2. `_serialize_and_render_grid(payload: dict)` serialisiert das aggregierte generische Payload-Dict als **ein** JSON.
3. `_apply_grid_render(payload_json, grid_gen)` verwirft veraltete Generationen (unverändert) und ruft `applyChartRenderPayload(payload_json)` auf.
4. Kein Ersatz durch `ChartDataSerializer`; kein neues Threading-Muster.

---

## Umsetzungs-Reihenfolge (verbindlich, auf Startbefehl)

1. **Git-Backup/Tag `phase16_step5`** (Invariante 1).
2. **Prework Schritt 1 + VWMA-Fix:** `db_service.py` (`tick_volume` in `fetch_historical_candles`) + `chart_win.py` (generische Payload-Aggregation, hartcodierte Branches entfernen, Serializer-Payload-Format F4).
3. **Prework Schritt 2 (JS):** `03_chart_rendering.js` – `applyChartRenderPayload`, `renderLineSeries` (Registry), `renderPriceLines`, `renderMarkers`, Legacy-Cleanup (`renderGridLines`/`renderGridCircles` als Unterfälle/Aliasse); `04_live_updates.js` – `applyFullChartUpdate` Schritt 5+6 durch `applyChartRenderPayload` ersetzen.
4. **Prework Schritt 3 (F2):** `node --check` auf allen geänderten JS-Dateien + `py_compile` auf geänderten Python-Dateien + gezielter Logik-Test in `test/test.py`.
5. **16.05 Multi-MA:** `chart/indicators/multi_ma.py` (Schema programmatisch, `build_chart_render_payload` → `{"lines": [...]}` mit `id: "ma1".."ma8"`, `calculate()`), Registrierung in chart_win, Button `btn_indicator_ma` in `chart_win.ui` (D1).
6. **16.05 Verifikation (F2):** gezielter Logik-Test in `test/test.py` + `py_compile` + Import-Smoke.

---

# Phase 16.05 – Implementierungs-Log: Indikator-Dialog Bugfix Multi-MA (06.08.2026)

> **Status:** Umsetzung **abgeschlossen** (Commit `6cecb11`, nach Benutzer-Freigabe im Bugfixing-Modus). Die drei Anwenderanforderungen am Multi-MA-Prop-Fenster sind behoben und per gezieltem Logik-Test in `test/test.py` (Teil 10, D1–D6) verifiziert. Git-Backup vor der Umsetzung: `6cecb11`; Vor-Kapitel: Prework + Multi-MA (Commits `16a5838`, `ba60361`, `370031f`).

## Ausgangslage (Bugfixing-Modus, 3 Anwenderanforderungen)

1. **„in diesem indikator gibt es keine services – dazu alles ausblenden":** Das Prop-Fenster des Multi-MA zeigte trotz `service_plugin_ids=[]` die komplette Service-UI (`Service-Parameter`, `Service-Set Aktionen`, `Experten-Optionen`).
2. **„ma_farbe hat eine checkbox, das ist nicht richtig ... bitte entfernen":** Farb-Parameter wurden als `StylePickerWidget`-Composite gerendert – inklusive der „sichtbar"-Checkbox. Sie hat keine Funktion (die Sichtbarkeit steuert ausschließlich `show_maX`) und war vom Benutzer nicht definiert.
3. **„für jeden ma fehlen parameter: a. die länge, b. der ma type, c. der glättungstyp, d. der alpha wert":** Die Nicht-Darstellungs-Parameter (`maX_type`/`maX_period`/`maX_smooth_type`/`maX_alpha`) wurden im Plugin-Pfad von `_init_plugin_ui` über `_is_visual_key()` gefiltert und erschienen **nirgends** – die Service-Parameter-Box rendert nur Service-Seiten.

## Ursachenanalyse (Ist-Stand)

- `indicator_dialog._init_plugin_ui` baute `indi_group` („Anzeige & Farben") nur aus `_is_visual_key()`-Keys (`show_*` / `color`) und danach **immer** die drei Service-Boxen – unabhängig davon, ob der Indikator Services deklariert.
- `_is_visual_key` ordnet alle `color`-Keys als visuell ein → sie landen im `StylePickerWidget`-Composite (mit „sichtbar"-Checkbox). Das Composite ist für Grid-Farben (Linienstil/-stärke) korrekt, für reine MA-Farben nicht.
- Die Nicht-Darstellungs-Parameter des Multi-MA hatten im Plugin-Pfad **keinen** Render-Ort.

## Umsetzung (Commit `6cecb11`)

1. **Service-UI ausblenden (Anforderung 1):** `_init_plugin_ui` prüft `self._indicator_service_ids()`. Ohne Services wird die neue Methode `_init_plugin_ui_params_only(main_layout)` aufgerufen: rendert **alle** Parameter direkt, gruppiert nach `param_layout` (Multi-MA: „MA 1 (Führung)" … „MA 8"), plus Preset-Verwaltung rechts. Die drei Service-Boxen entfallen komplett. **Additiv:** Der Service-Pfad für Grid-Indikatoren bleibt unverändert.
2. **Reiner Farbwähler (Anforderung 2):** `StylePickerWidget` erhält den Konstruktor-Parameter `color_only` (nur der Farb-Button wird gerendert; keine „sichtbar"-Checkbox, keine Linienart/-stärke) + Property `color_only`. Die Multi-MA-Farbparameter (`ma1_bull_color`/`ma1_bear_color`/`ma2..8_color`) deklarieren `"color_only": True`; `create_schema_control` rendert sie als reinen Farbwähler. Die drei Round-Trip-Pfade (`_build_preset_payload`, `collect_params_from_ui`, `update_ui_from_params`) überspringen für `color_only` die Geschwister-Keys (`maX_style`/`maX_width`).
3. **Fehlende MA-Parameter (Anforderung 3):** Durch `_init_plugin_ui_params_only` erscheinen jetzt `maX_type` (Choice), `maX_period`/Länge (SpinBox), `maX_smooth_type` (Choice) und `maX_alpha` (DoubleSpinBox) mit den Defaults (D7): MA1 `EHMA/4/EHMA/2.0`, MA2..8 `EMA/10·X/EMA/2.0`.
4. **None-Vorbelegung der Service-Attribute in `__init__`:** `combo_service_set`, `combo_service_sel`, `stack_service_forms`, `edit_set_name`, `edit_set_description`, `group_expert` werden mit `None` initialisiert → alle bestehenden `if self.<attr>:`-Guards (z. B. `_build_preset_payload`, `on_preset_selected`, `refresh_service_set_list`) werden None-sicher, ohne den Service-Pfad zu verändern.

## Verifikation (F2, gezielter Logik-Test in `test/test.py` Teil 10)

- **D1:** `_get_plugin` liefert den Indikator selbst; `_indicator_service_ids()` leer. ✅
- **D2:** Keine Service-UI (`combo_service_set`/`edit_set_name`/`group_expert` sind `None`). ✅
- **D3:** Alle 50 Parameter in `param_controls`; `maX_type`/`maX_smooth_type` = ComboBox, `maX_period` = SpinBox, `maX_alpha` = DoubleSpinBox; Defaults MA1/MA2 korrekt. ✅
- **D4:** Farb-Controls = `StylePickerWidget` mit `color_only=True`. ✅
- **D5:** Preset-Payload: `logic_params` enthält `maX_type/period/smooth_type/alpha`; `display_params` enthält `show_maX` + Farben; keine Sibling-Keys (`maX_style`/`maX_width`). ✅
- **D6 (Kontrolle):** Grid-Indikator (mit Services) behält die Service-UI unverändert. ✅
- **Zusätzlich:** `python -m py_compile` auf allen 4 geänderten Dateien erfolgreich. Die 6 vorbestehenden Fehlschläge (P2/P5/H3–H5/H7, ServiceWindow) sind unverändert und **nicht** durch diese Änderung verursacht.
- **Datumskorrektur:** Die Code-Kommentare trugen zunächst fälschlich „08.08.2026" – auf das tatsächliche Datum **06.08.2026** korrigiert (nachgelagerter Commit).

---

# Phase 16.05 – Implementierungs-Log: Multi-MA Prop-Fenster Layout (06.08.2026)

> **Status:** Umsetzung **abgeschlossen** (Commit `d3e7f7e`, nach Benutzer-Freigabe im Bugfixing-Modus). Die vier Layout-Anforderungen am Multi-MA-Prop-Fenster sind behoben und per gezieltem Logik-Test in `test/test.py` (Teil 10, D7) verifiziert. Vorheriger Commit: `6cecb11`/`6566945` (Dialog-Bugfix + Doku).

## Anwenderanforderungen (Bugfixing-Modus, 4 Layout-Punkte)

1. **Preset-Box ganz oben links.**
2. **Darunter immer zwei MA-Boxen nebeneinander** (1-2, 3-4, 5-6, 7-8).
3. **Das Fenster ist immer nur etwas breiter als die zwei MA-Boxen nebeneinander.**
4. **Das Fenster ist genauso hoch wie der untere Rand der MA-Boxen 7 und 8.**

## Ausgangslage (Ist-Stand)

- `_init_plugin_ui_params_only` baute eine linke Spalte (`QVBoxLayout`) mit allen Parameter-Boxen untereinander und platzierte die Preset-Box rechts daneben (rechte Spalte). Der Schließen-Button hing am Ende von `init_ui` (unterhalb des Inhalts).
- **Problem 1/2:** Die MA-Boxen standen untereinander (eine Spalte), nicht paarweise nebeneinander.
- **Problem 3:** Die Preset-Box war **508px breit** und stand in einer eigenen Grid-Spalte – dadurch wurde die Gesamtbreite auf ~800px aufgebläht (die zwei MA-Boxen brauchen nur ~684px). Gemessen: Fenster 800px vs. MA-Boxen 684px.
- **Problem 4:** Der Schließen-Button unterhalb der Boxen + `_build_preset_group` rechts verlängerten das Fenster unter den unteren Rand von MA7/MA8.

## Umsetzung (Commit `d3e7f7e`)

`_init_plugin_ui_params_only` wurde auf ein **kompaktes `QGridLayout`** umgestellt:

1. **Zeile 0 – Preset oben links + Schließen oben rechts:** Eine `QHBoxLayout`-Zeile, die über **beide** Spalten spannt (`addLayout(top_row, 0, 0, 1, 2, Qt.AlignTop)`): Preset-Box links, `addStretch(1)`, Schließen-Button rechts. Der Button sitzt damit oben rechts (Anforderung 1) – kein separates Element unterhalb mehr.
2. **MA-Boxen in 2er-Zeilen:** Die Parameter-Boxen werden zunächst gesammelt (`rendered_groups`) und dann **paarweise** ins Grid gesetzt (`for i in range(0, len, 2)` → Zeile 1: MA1+MA2, Zeile 2: MA3+MA4, Zeile 3: MA5+MA6, Zeile 4: MA7+MA8). Anforderung 2.
3. **Breite nur „etwas breiter" als 2 MA-Boxen:** Weil die Top-Zeile über beide Spalten spannt und `addStretch(1)` den Restplatz aufnimmt, verbreitert die 508px-Preset-Box das Grid **nicht** mehr. Die Spaltenbreiten bestimmen die MA-Boxen (`setColumnStretch(0/1, 1)` gleichmäßig). **Gemessen:** Fenster 712px vs. zwei MA-Boxen 684px (nur Fensterrahmen) – vorher 800px. Anforderung 3.
4. **Höhe = unterer Rand MA7/MA8:** Nichts unterhalb der letzten Boxen-Zeile; `init_ui` fügt den Schließen-Button nur noch an, wenn er nicht bereits im Plugin-Grid platziert wurde (`_close_placed_in_plugin_ui`-Guard). Das `ContentScrollMixin` klemmt die Fenstergröße exakt auf den Inhalt → Fensterhöhe = unterer Rand von MA7/MA8. Anforderung 4.

## Verifikation (F2, gezielter Logik-Test in `test/test.py` Teil 10, D7)

- **D7 Grid-Layout gefunden:** `_init_plugin_ui_params_only` erzeugt ein `QGridLayout` im Inhalt. ✅
- **D7 Preset oben links + Schließen oben rechts** (Zeile 0, HBox span 2). ✅
- **D7 Kein separater Button unterhalb** (nur das Grid im Inhalt). ✅
- **D7 MA-Boxen 2er-Zeilen:** Zeile 1 = MA 1 (Führung)+MA 2, Zeile 2 = MA 3+MA 4, Zeile 3 = MA 5+MA 6, Zeile 4 = MA 7+MA 8. ✅
- **D7 Nichts unterhalb MA7/MA8** (Grid-Zeile 5 leer). ✅
- **Geometrie-Messung (offscreen):** Fensterbreite 712px ≈ 2 MA-Boxen (684px) + Rahmen; Inhalt endet am unteren Rand 937px (MA7/MA8). ✅
- **Zusätzlich:** `python -m py_compile` auf `chart/indicator_dialog.py` + `test/test.py` erfolgreich. Die 6 vorbestehenden Fehlschläge (P2/P5/H3–H5/H7, ServiceWindow) sind unverändert und **nicht** durch diese Änderung verursacht.

---

# Phase 16 Refactoring (07.08.2026) – Alpha-EMA-Glättung & UI-Matrix (Analyse, noch KEINE Implementierung)

> **Status:** 🔍 ANALYSE ABGESCHLOSSEN – **noch keine Implementierung**. Wartet auf den ausdrücklichen Startbefehl des Benutzers (Invariante 1: Git-Backup/Tag vor Umsetzung). Doku-Ergänzung auf Anforderung C (Benutzer 07.08.2026).

## Refactoring-Auftrag (Benutzer, 07.08.2026)

**Phase 16.04 (MA-Template):**
1. Parameter `smooth type` entfernen.
2. MA- und Glättungslogik basiert auf EMA und ist neu definiert im Konzept („Alpha-Smoothed MA Engine", 16.04 Schritt 3/5).

**Phase 16.05 (Multi-MA):**
5. Glättungslogik gehört in das MA-Template (`ma_template.py`), **nicht** in 16.05.
6. Es gibt keinen Parameter `smooth type` mehr → `maX_smooth_type` entfernen.
7. Inputfeld „Glättungstyp" entfernen.
8. Anzeige-Matrix ändern: Zeile 1 = MA1, MA2, btn Schließen; Zeile 2 = MA3, MA4, MA5; Zeile 3 = MA6, MA7, MA8 → Fenstergröße so anpassen, dass alle MA-Boxen ohne Scrolling sichtbar sind.

## A. Konsistenz-Check (verifiziert am Ist-Stand, 07.08.2026)

1. **Konzept-Quelle (verbindlich):** 16.04 Schritt 3, Tabelle „Alpha-Smoothed MA Engine": Parameter `len` (Int, Def 4), `ma_type` (12er-Enum, Def EHMA), `smoothing` (Int, Def **10**), `alpha` (Float, Def 2.0). Glättung: „Bei aktivierter Glättung (`smoothing > 1`) wird eine zweifach verschachtelte EMA-Filterung mit dynamischem Alpha-Gewichtungsfaktor α = alpha/(len+1) angewendet". Schritt 5-Formel `hma_ema = alpha_calc * EMA(src, smoothing) + (1 - alpha_calc) * hma_ema[t-1]` ist als **`EMA(EMA(base_ma, smoothing), alpha=alpha_calc)`** zu lesen (die Schreibweise `EMA(hma_ema[t-1])` ist eine Formel-Schwäche für den rekursiven Wert selbst; EMA über eine Konstante = Konstante).
2. **`smooth_type` in 16.04:** `get_ma_parameter_schema()` führt `smooth_type` (Choice, 13 Optionen inkl. „ - no Smoothing") + `smooth_length`. Die Konzept-Tabelle kennt nur `smoothing` (int) → Entfernen von `smooth_type` ist konsistent. ⚠️ Der 07.08.2026-Fix („- no Smoothing"-Option, `smooth_length`) wird damit überholt: „keine Glättung" = `smoothing <= 1`.
3. **Glättung aktuell falsch im 16.05 verortet:** `multi_ma.build_chart_render_payload()` führt den zweiten MA-Pass inline mit `maX_smooth_type` aus (beliebige MA-Typen) – entspricht **nicht** der Konzept-Glättung (immer EMA-basiert, zweifach verschachtelt). → Glättung in die Engine (`MATemplateEngine.calculate_ma(..., smoothing=...)`) verschieben (16.05.5). ✅
4. **EHMA-Diskrepanz (vorbestehend):** Konzept Schritt 3 (Hull-Familie) definiert `EHMA = EMA(2*EMA(src, len//2) − EMA(src, len), sqrt(len))`; die aktuelle Implementierung nutzt `EHMA = EMA_alpha(HMA(src, len), len)` (TradingView-Konvention, E4/Ergänzung 1). ⚠️ Offen: beibehalten oder konzept-konform umstellen? (siehe B.4)
5. **Kein weiterer Konsument:** `smooth_type`/`smooth_length` werden nur von `multi_ma.py`, `ma_template.py` (Schema) und `test/test.py` referenziert – `chart_win.py`/JS sind unberührt. Rename `maX_smooth_length` → `maX_smoothing` ist ohne Fremdeffekt möglich (gespeicherte Presets tragen Alt-Keys, die `calculate` ignoriert). ✅
6. **UI-Matrix aktuell 2-spaltig:** `_init_plugin_ui_params_only` rendert 2er-Zeilen (1-2, 3-4, 5-6, 7-8) + Schließen oben rechts. Neue Vorgabe: 3er-Matrix (Zeile 1: MA1, MA2, Schließen; Zeile 2: MA3-5; Zeile 3: MA6-8). `ContentScrollMixin` klemmt das Fenster auf min(Inhalt, Bildschirm); „ohne Scrolling" erfordert Inhalt ≤ Bildschirm (Maße siehe C.8). ✅

## B. Neue Verträge (16.04 – Template)

- **Schema** (`get_ma_parameter_schema`, 7 Keys statt 8): `ma_type`, `period`, `smoothing` (int, min 0, max 500, Def 10 laut Konzept), `alpha_factor`, `dual_color`, `bull_color`, `bear_color`. **`smooth_type` entfällt ersatzlos.**
- **Engine:** `calculate_ma(source, ma_type, period, alpha_factor=2.0, volume=None, smoothing=1)`:
  * Basis-Serie wie bisher (12 Typen, VWMA-SMA-Fallback E5).
  * `smoothing > 1` (aktiv): `alpha_calc = alpha_factor / (period + 1)`; `ema_first = EMA(base, span=smoothing)`; `base = EMA(ema_first, alpha=alpha_calc)` – vektorisiert via pandas `ewm(adjust=False)`.
  * `smoothing <= 1`: keine Glättung (Basis-Serie unverändert).
- **Docstring/Ergänzungen:** „ - no Smoothing"-Option und `smooth_length`-Vertrag entfernen; Alpha-EMA-Glättung als verbindlichen Engine-Vertrag dokumentieren (E4-α übernimmt dabei die Glättungs-Rolle für alle Typen).

## C. Neue Verträge (16.05 – Multi-MA)

- **Schema (50 Parameter statt 58):** `maX_smooth_type` entfernt; `maX_smooth_length` → **`maX_smoothing`** (int, min 0, max 500). MA1: show/type/period/smoothing/alpha/dual/bull/bear (8 Keys); MA2..8: show/type/period/smoothing/alpha/color (6 Keys). `parameter_order`/`param_labels`/`param_layout` analog (Label weiterhin „MA X Smooth"). `_NO_SMOOTHING`/`_is_no_smoothing` entfallen.
- **Berechnung (16.05.5):** Inline-Zweitpass in `build_chart_render_payload()` entfällt; Aufruf `MATemplateEngine.calculate_ma(close, ma_type, period, alpha_factor=alpha, volume=volume, smoothing=smoothing)`. Linien-Titel: `MA1 EHMA 4 | S 10` (nur Länge, kein Typ mehr).
- **UI (16.05.7/8):** „Glättungstyp"-Combo entfällt automatisch (Key entfernt). `_init_plugin_ui_params_only` → 3-Spalten-Grid:
  * Zeile 0: Preset-Box (span 3).
  * Zeile 1: MA1, MA2, btn Schließen (AlignTop).
  * Zeile 2: MA3, MA4, MA5.
  * Zeile 3: MA6, MA7, MA8.
  * Fenster: min(Inhalt, Bildschirm); Breite ≈ 3 × ~300px ≈ 900px; Höhe ≈ Preset + 3 Boxen-Reihen (MA1 ~8 Zeilen, MA2..8 ~6 Zeilen) → passt ohne Scrolling auf ≥1080p; auf 768p-Höhe ggf. knapp (Klemme bleibt, Scrollbar nur im Extremfall).
- **Tests (`test/test.py`):** Schema 50, kein `smooth_type`, `maX_smoothing`-Default, M7 auf Alpha-EMA-Referenz (`EMA(EMA(SMA4, span=10), alpha=0.4)`), Layout-D7 auf 3er-Matrix umstellen.

## D. Offene Fragen (B) – Entscheidung vor der Umsetzung

1. **Parameter-Name:** `maX_smoothing` (konzept-konform) statt `maX_smooth_length`? *(Empfehlung: ja)*
2. **Default `smoothing`:** 10 (Konzept, Glättung aktiv) oder 0/1 („keine Glättung" als Default, bisherige Philosophie)? *(Empfehlung: 10 laut Konzept)*
3. **„Keine Glättung" ohne Choice:** `smoothing <= 1` ersetzt die frühere „- no Smoothing"-Option – OK?
4. **EHMA-Formel:** aktuelle TradingView-Formel (E4) beibehalten oder Konzept-Formel (Hull-EMA-Kombination) übernehmen? *(Empfehlung: beibehalten, etablierter E4-Vertrag)*
5. **Layout-Detail:** Preset bleibt Zeile 0 (span 3)? Schließen-Button in Zeile 1 rechts neben MA2 (AlignTop)?
6. **`alpha`-Rolle:** `maX_alpha` speist künftig auch die Glättung (`alpha_calc = alpha/(period+1)`) für **alle** Typen – bei nicht-Alpha-MAs wird `alpha` damit bei aktivem Smoothing nicht mehr ignoriert. OK?

## E. Umsetzungs-Reihenfolge (Vorschlag, auf Startbefehl)

1. Git-Backup/Tag (Invariante 1).
2. **16.04:** `ma_template.py` – Schema (smooth_type raus, `smoothing` rein), `calculate_ma` um `smoothing`-Pass erweitern, Docstring.
3. **16.05:** `multi_ma.py` – Schema/Order/Labels/Layout (50 Params, `maX_smoothing`), Berechnung über Template-Smoothing, Titel ohne Typ.
4. **16.05 UI:** `indicator_dialog.py` `_init_plugin_ui_params_only` → 3er-Matrix + Schließen in Zeile 1.
5. **Verifikation (F2):** `py_compile` + gezielter Logik-Test in `test/test.py`.
---

## Implementierungs-Log Phase 16.04/16.05 (07.08.2026, Vertrag B & C)

> **Status:** UMGESETZT, COMMITTET (Vertraege B/C gemaess Benutzer-Entscheidungen D1-D6). Umsetzungs-Commits: `c0cb4ca` (16.04), `bf85acb` (16.05), `51af231` (16.05 UI). Verifikation headless ueber `test/test.py` (M1-M8, D1-D7 PASS; nur vorbestehende ServiceWindow-Geometrie-Fails P2/P5/H3-H5/H7, unabhaengig von dieser Umsetzung).

### Benutzer-Entscheidungen (bestaetigt 07.08.2026)
- **D1:** Parameter-Name `maX_smoothing` (PineScript-Taxonomie).
- **D2:** Default `smoothing` = 10; `smoothing <= 1` = Bypass (ersetzt "- no Smoothing"-Option ersatzlos).
- **D3:** EHMA: TradingView-Formel `EMA(HMA(src, len), len)` beibehalten (Code unveraendert; Konzept-Doku-Z.71 war ungenaue Doku, kein Code).
- **D4:** Layout = 3-Spalten-Grid (Preset Zeile 0 span 3; Zeile 1: MA1, MA2, Schliessen; Zeile 2: MA3-5; Zeile 3: MA6-8), ~900px, Screen-Klemme via `ContentScrollMixin`.
- **D5:** `alpha`-Rolle: `alpha_calc = alpha/(period+1)` universell auf die Glaettungs-EMA bei `smoothing > 1` - ueber alle 12 MA-Typen.

### Umgesetzt

**16.04 `ma_template.py` (Commit `c0cb4ca`, Vertrag B):**
- Schema 7 Keys: `ma_type`, `period`, `smoothing` (int, Def 10, min 0, max 500), `alpha_factor`, `dual_color`, `bull_color`, `bear_color`. `smooth_type`/`smooth_length` ersatzlos entfernt.
- `calculate_ma(source, ma_type, period, alpha_factor=2.0, volume=None, smoothing=1)`: bei `smoothing > 1` `ema_first = EMA(base, span=smoothing)`; `base = EMA(ema_first, alpha=alpha_calc)` mit `alpha_calc = alpha_factor/(period+1)`.

**16.05 `multi_ma.py` (Commit `bf85acb`, Vertrag C):**
- Schema 50 Parameter (MA1 8, MA2..8 je 6): `maX_smooth_type`/`maX_smooth_length` entfernt -> `maX_smoothing` (int, min 0, max 500, Def 10). `_NO_SMOOTHING`/`_is_no_smoothing` entfernt.
- Berechnung: Inline-Zweitpass raus -> `calculate_ma(..., smoothing=smoothing)`; Titel `| S {smoothing}` (nur Laenge).

**16.05 UI `indicator_dialog.py` (Commit `51af231`, Vertrag C):**
- `_init_plugin_ui_params_only`: 3-Spalten-Grid. Zeile 0 Preset-Box span 3; Zeile 1 = MA1 (Sp.0) + MA2 (Sp.1) + Schliessen-Button (Sp.2); Zeile 2 = MA3/MA4/MA5; Zeile 3 = MA6/MA7/MA8; Zeile 4 leer -> kompaktes Fenster (~900px). `setColumnStretch(0/1/2, 1)`.

### Verifikation (F2)
- `python -m py_compile` auf allen 3 geaenderten Dateien: OK.
- `test/test.py`: M1/M2/M3/M4/M5/M6/M7/M8, D1-D7 (inkl. neue D7-3-Spalten-Checks) alle PASS. Keine Rest-Code-Referenzen auf Alt-Keys (nur historische Docstring-Kommentare).
- Test-Cleanup gemaess Invariante 10: `test/` bleibt mit `test/test.py` (dauerhafter Harness), keine neuen temporaeren Check-Skripte.

---

## Bugfix-Log Phase 16.05 (07.08.2026, nach Benutzer-Freigabe)

> **Status:** ✅ FIX BESTÄTIGT & COMMITTET (Commit `1f42371`, nach manueller Freigabe durch den Benutzer). Betrifft `chart/indicator_dialog.py` (`_init_plugin_ui_params_only`), Layout des Multi-MA-Prop-Fensters.

### Anwender-Anforderungen (Bugfix)
1. **Preset-Box so breit bis zum Ende von MA2** (nicht mehr über alle 3 Spalten).
2. **Schließen-Button rechts mittig neben der Preset-Box** (nicht mehr rechts neben MA2 in Zeile 1).

### Umgesetzt
- **Preset-Box:** `content_grid.addWidget(self._build_preset_group(), 0, 0, 1, 2, Qt.AlignTop)` – span von 3 auf **2** reduziert → endet exakt über dem rechten Rand von MA2 (Spalten 0–1).
- **Schließen-Button:** von `(1, 2, Qt.AlignTop)` nach `(0, 2, Qt.AlignCenter)` verschoben → rechts daneben, **vertikal zentriert** zur Preset-Box.
- Kommentare/Docstring in `_init_plugin_ui_params_only` und `init_ui`-Guard entsprechend aktualisiert.

### Verifikation (F2)
- `python -m py_compile chart/indicator_dialog.py`: OK.
- `test/test.py` Teil 10 D7 (aktualisiert): „Preset-Box Zeile 0 Spalten 0-1 (span 2, bis MA2-Ende)", „Schliessen-Button Zeile 0 Spalte 2 (rechts mittig neben Preset)" – alle PASS. MA-Grid (MA1/2, MA3/4/5, MA6/7/8) und Zeile-4-leer-Check unverändert PASS.
- Die 6 vorbestehenden ServiceWindow-Fails (P2/P5/H3–H5/H7, offscreen 800×800) sind unverändert und **nicht** durch diesen Fix verursacht.

---
# 16.06 Refactoring StylePickerWidget & Indikator-Integration

## 1. Konzept StylePickerWidget (Unified Style Picker)
* **Ziel:** Zusammenführung von Farbauswahl, Transparenz und Zeichnungsparametern (Linienstärke, Linienstil, Darstellungsmodus) in einer einzigen kompakten UI-Komponente mit typsicherem Schnittstellenvertrag.
* **UI-Aufbau des Popover-Dialogs (`StylePickerDialog`):**
  1. **Oberer Bereich:** Bisheriger ColorPicker (Farbfeld, Palette, RGBA/Hex-Eingabe, Transparenz-Slider).
  2. **Trennlinie (`QFrame.HLine`):** Visuelle Abgrenzung.
  3. **Unterer Bereich (Neue Zeichnungsparameter):**
     * **Linienstärke / Stärke:** `width` (SpinBox: 1–5 px)
     * **Linienstil:** `style` (ComboBox: `solid` [Durchgezogen], `dashed` [Gestrichelt], `dotted` [Gepunktet])
     * **Darstellungsmodus:** `draw_mode` (ComboBox: `line` [Linie], `histogram` [Histogramm], `circles` [Kreise ●], `blocks` [Blöcke / HA])
* **Button-Vorschau im Haupt-Dialog:** Nach der Transition ist im Hauptformular des Indikators nur noch ein kompaktes Farbkästchen mit Vorschau-Text (z. B. `● 2px Solid`) sichtbar. Klick auf das Kästchen öffnet den erweiterten Dialog.

---

## 2. Datenvertrag & Persistenz (Presethandling & Window State)
* **Data Contract (`LineStyleModel` in `chart/overlays/style_models.py`):**

  @dataclass
  class LineStyleModel:
      color: str = "#2196F3"
      width: int = 2
      style: str = "solid"       # "solid" | "dashed" | "dotted"
      draw_mode: str = "line"    # "line" | "histogram" | "circles" | "blocks"
      transparency: int = 0      # 0..100 %

      def to_dict(self) -> dict: ...
      @classmethod
      def from_dict(cls, data: dict) -> "LineStyleModel": ...



* **Persistenz-Invariante:** All-in-one Dict in den Indikator-Parametern (z. B. `"ma1_style": {...}`).
* **Rückwärtskompatibilität & Auto-Migration:**
* Wenn im gespeicherten Preset/Window-State ein Alt-Format vorliegt (z. B. `"ma1_color": "#FF0000"`, `"ma1_width": 2`), wandelt `from_dict()` dies automatisch fehlerfrei in ein valides `LineStyleModel` um.
* Dadurch bleiben bestehende `indicator_presets` und `instance_states` in `app_data.duckdb` ohne Schema-Bruch voll funktionsfähig.

---

## 3. Transition der vorbestehenden Indikatoren

* **Betroffene Indikatoren:** `MultiMA` (`multi_ma.py`) und `FixedGridProximity` (`fixed_grid_proximity.py`).
* **Vorher:** Separate Input-Felder für Farben, Linienstärken und Kreis-Optionen verstreut im Dialog.
* **Nachher:**
* Zusammenfassung aller Stil-Parameter pro Linie/Signal in ein `StylePickerWidget`.
* Ein einziges Farbkästchen pro Element im Einstellungs-Dialog.
* Linienstärken, gestrichelte Stile und Kreis-Darstellungen (`circles` für Proximity-Hits) werden vollständig über das Unter-Panel des Pickers gesteuert.

---

## 4. Schritt-für-Schritt-Anleitung für die IDE-AI

### Schritt 1: Data Model in `chart/overlays/style_models.py` erweitern

* Erstelle/Erweitere `LineStyleModel` mit den Feldern `color`, `width`, `style`, `draw_mode`, `transparency`.
* Implementiere `to_dict()` und `from_dict()` inkl. Fallback für flache Alt-Keys (`color`, `width`, `lineWidth`, etc.).

### Schritt 2: Popover-Dialog & Widget in `chart/widgets/style_picker_widget.py` umbauen

* **Dialog (`StylePickerDialog`):**
* Integriere den bestehenden Farb-/Transparenz-Picker im oberen Bereich.
* Füge ein `QFrame(FrameShape.HLine)` als Trennlinie ein.
* Füge Formularzeilen für `width` (QSpinBox 1-5), `style` (QComboBox) und `draw_mode` (QComboBox) unter der Trennlinie hinzu.


* **Widget (`StylePickerWidget`):**
* Reduziere die Anzeige im Indikator-Dialog auf einen kompakten Button (Farbkästchen + Stärke/Stil-Text).
* Klick-Event öffnet `StylePickerDialog(exec)`.
* Emittiere `style_changed(LineStyleModel)` bei Übernahme.

### Schritt 3: Migration `chart/indicator_dialog.py`

* Ersetze isolierte `ColorPicker`-Aufforderungen und verstreute Linienstärke-/Stil-SpinBoxes durch `StylePickerWidget`.
* Pass die Getter/Setter an, sodass Stil-Daten als kompaktes Dict (`<item>_style`) geladen und im Preset/State gespeichert werden.

### Schritt 4: Transition `chart/indicators/multi_ma.py` & `chart/indicators/fixed_grid_proximity.py`

* **`multi_ma.py`:** Verbinde `ma1_style` .. `ma3_style` direkt mit den LWC-Render-Payloads (`color`, `lineWidth`, `lineStyle`).
* **`fixed_grid_proximity.py`:** Führe Linien- und Kreis-Formate (Farbe, Proximity-Circles `●`, Linienstärken) in die jeweiligen `LineStyleModel`-Strukturen zusammen.

### Schritt 5: Verifikation (Backend & Tests)

* Führe isolierte Logik- & Parametertests in `test/test.py` aus (Syntax-Check via `py_compile`, Serialization/Deserialization-Test von `LineStyleModel` und Preset-Read/Write).
* **UI-Regel:** Keinen GUI-Test starten; Verifikation erfolgt per Code-Inspektion und statischer Analyse.

---

## 5. Implementierungs-Log & Entscheidungen 16.06 (Stand 07.08.2026)

**Hinweis:** Die Ist-Umsetzung weicht in der Struktur von der Planung (Kapitel 1–4) ab. Die Planung bleibt als Konzeptdokument erhalten; verbindlich für Code und Persistenz ist der hier dokumentierte Ist-Stand (Entscheidungen E1–E6).

### E1: `LineStyleModel` → generische Style-Verträge `LineStyle`/`MarkerStyle` (P16.03)
* Die geplante Klasse `LineStyleModel` (color/width/style/draw_mode/transparency) wurde NICHT eingeführt.
* Stattdessen leben in `chart/overlays/style_models.py` die Dataclasses **`LineStyle`** (`show/color/width/style`, LINE_STYLES: solid/dashed/dotted/dashdotted) und **`MarkerStyle`** (`show/color/shape/size`, MARKER_SHAPES: circle/square/arrowUp/arrowDown) mit `to_js_dict()` (LWC-v5-Bridge, lowercase) und `to_dict()/from_dict()` (JSON-Persistenz, tolerant, Default-Fallback).
* `draw_mode` (line/histogram/circles/blocks) wurde **verworfen** – der `circles`-Fall wird über `MarkerStyle` (shape/size) abgebildet, der `line`-Fall über `LineStyle`. histogram/blocks sind ungenutzt.
* Transparenz wird nicht als eigenes Feld, sondern als `rgba(r,g,b,a)`-Farbstring geführt (Alpha=255 → `#RRGGBB`); die Steuerung erfolgt über den `QColorDialog` (`ShowAlphaChannel`).

### E2: `StylePickerDialog`-Popover → Inline-Composite `StylePickerWidget`
* Der geplante Popover-Dialog (Farbbereich oben, Trennlinie, Zeichnungsparameter unten, kompakte Button-Vorschau `● 2px Solid`) wurde NICHT umgesetzt.
* `chart/widgets/style_picker_widget.py` rendert stattdessen ein **Inline-Composite** direkt in der Form-Zeile: `QCheckBox` (sichtbar) + Farb-Button (Swatch) + `QSpinBox` (width 1–10 / size 1–20) + `QComboBox` (style/shape). Parameter `style_type` ("line"/"marker") und `color_only` wählen den Modus.
* Signal `style_changed(object)` emittiert das aktuelle Style-Objekt; `get_style()` liefert eine frische Instanz, `set_style()/set_color()` emittieren bewusst kein Signal.

### E3: Persistenz über Sibling-Keys statt All-in-one-Dict
* Statt `"ma1_style": {...}` wird das **flache Format** mit Sibling-Keys persistiert (Konvention: `color` im Key → `style`/`width` bei line, `shape`/`size` bei marker).
* `indicator_dialog._style_sibling_keys()` leitet die Geschwister-Keys her; `_build_preset_payload()`, `collect_params_from_ui()` und `update_ui_from_params()` schreiben/lesen sie round-trip-fest (Old-Presets ohne Sibling-Keys fallen auf Defaults zurück → keine Auto-Migration nötig).
* `_jsonify_style_objects()` ist die defensive Absicherung, falls ein Style-Vertrag direkt im Preset-Payload landet.

### E4: Multi-MA → volle LineStyle-Picker (Phase 16.06, 07.08.2026)
* **Anwenderanweisung (07.08.2026):** „Multi-MA soll auch auf den neuen StylePicker angewendet werden."
* **Umsetzung:** `ma1_bull_color` und `maX_color` (MA2..8) werden als **volle LineStyle-Picker** gerendert (Farbe + Breite 1–10 px + Linienart solid/dashed/dotted/dashdotted) statt als `color_only`-Farbwähler. Sichtbarkeit steuert weiterhin `show_maX` (daher `show_visibility=False` — keine doppelte „sichtbar"-Checkbox im Dialog).
* **Sibling-Defaults:** Die Picker-Breite/-Art wird über Sibling-Keys persistiert (Konvention `color`→`style`/`width`): `ma1_bull_style`/`ma1_bull_width` (gelten für die gesamte MA1-Linie, auch bear-Segmente) bzw. `maX_style`/`maX_width`. Diese 16 Keys sind im Schema als Default-Params enthalten (MA1 Breite 2/solid, MA2..8 Breite 1/solid), aber **nicht** in `parameter_order` → keine eigenen Controls (Schema-Gesamt: 66 Keys = 50 UI + 16 Sibling-Defaults).
* `ma1_bear_color` bleibt **`color_only=True`** (nur die Fall-Farbe; Breite/Art übernimmt der bull-Picker).
* **Render:** `build_chart_render_payload` liest `ma1_bull_width`/`ma1_bull_style` bzw. `maX_width`/`maX_style` mit Fallback auf die Konstanten (`_MA1_WIDTH=2`, `_MA_WIDTH=1`, `_LINE_STYLE="solid"`) → Old-Presets ohne Sibling-Keys bleiben kompatibel.

### E5: FixedGridProximity → Einzelfelder entfernt, Bedienung nur über StylePicker (Phase 16.06, 07.08.2026)
* **Anwenderanweisung (07.08.2026):** „Die Einzelfelder für lines und circles sollen im StylePicker bedient werden → entferne die vorhandenen Elemente."
* **Umsetzung:** Die separaten Schema-/Label-Deklarationen **`line_style`, `line_width`, `circle_shape_std`, `circle_shape_active`, `circle_size_std`, `circle_size_active` wurden ENTFERNT**. Linienart/-stärke und Marker-Form/-Größe werden ausschließlich über den StylePicker bedient und als Sibling-Keys persistiert (Konvention `color`→`style`/`width` bzw. `shape`/`size`).
* `line_color` = LineStyle-Picker, `circle_color_std`/`circle_color_active` = MarkerStyle-Picker, jeweils **`show_visibility=False`** (Sichtbarkeit steuern `show_lines`/`show_circles` → die doppelte „sichtbar"-Checkbox aus E6-Beobachtung entfällt).
* `_build_style_objects()`/`build_chart_render_payload()` lesen die Sibling-Keys weiterhin tolerant mit Default-Fallback (solid/1, circle/6) → **alte Presets und instance_states bleiben voll funktionsfähig** (Roundtrip über den Picker bleibt erhalten).
* **JS-Bridge:** `renderMarkers` (chart/js/03_chart_rendering.js) übernimmt shape/size aus dem Payload.

### E6: Verifikation 16.06 (07.08.2026)
* Syntax-Check `python -m py_compile` auf `style_models.py`, `style_picker_widget.py`, `indicator_dialog.py`, `multi_ma.py`, `fixed_grid_proximity.py` → EXIT=0.
* `test/test.py` (headless, venv): alle 16.06-Checks PASS — M1 (Schema 66, Sibling-Defaults), D3 (50 gerenderte UI-Params), D4 (volle Picker ohne Checkbox, bear color_only, Picker-Defaults), D5 (Sibling-Keys in display_params), Teil 11 G1–G5 (Einzelfeld-Schema entfernt, Picker-Typen/`show_visibility`, Sibling-Roundtrip, Render-Anwendung, Old-Preset-Fallback).
* Zusätzliches Verifikations-Skript `test/check_stylepicker_16_06.py` (headless): A1/A2 (Multi-MA-Picker zeigen Spin+Combo sichtbar, Defaults w2/solid + w1/solid), B1–B4 (FixedGridProximity-Picker korrekt, KEINE Alt-Einzelfelder gerendert/persistiert, Schema ohne Alt-Keys), C1 (WindowCloseButtonHint für beide Dialoge gesetzt) — alle PASS.
* **Fenster-X-Fix (Punkt 4, empirisch belegt):** `IndicatorSettingsDialog` hatte `windowFlags()=12291` = Dialog|TitleHint|SystemMenuHint **OHNE WindowCloseButtonHint** → kein X in der Titelleiste. Ein `OR` mit `Qt.WindowCloseButtonHint` wird von Qt/PySide6 wieder verworfen (bleibt 12291); einzig das **explizite Setzen** `Qt.Dialog | WindowTitleHint | WindowSystemMenuHint | WindowCloseButtonHint` setzt das X zuverlässig (flags=134230019, Close=True). Gilt generisch für ALLE Indikator-Prop-Fenster (eine zentrale Stelle in `indicator_dialog.__init__`).
* **Befund zu „Alt-Felder noch sichtbar" (Punkte 1+2):** Die Alt-Felder (`line_style`/`line_width`/`circle_shape_*`/`circle_size_*`) existieren im Quellcode nachweislich NICHT mehr (Schema + Labels entfernt, Suche im gesamten Projekt ohne Treffer außerhalb `.venv`/Konstanten). Der beschriebene Anzeige-Zustand entspricht exakt dem ALTEN Code-Stand → die getestete App-Instanz lief noch mit dem zuvor geladenen Code. **Die App muss neu gestartet werden** (Python lädt Module nur beim Start; ggf. `__pycache__` leeren und sicherstellen, dass die Run-Config den `.venv`-Interpreter nutzt).
* **Vorbestehende, NICHT von 16.06 verursachte Test-Fails** in Teil 1/3 des Harness (ServiceWindow): P2/P5/H3/H4/H5/H7 — Test-Erwartung `_keep_history_on_close == True` vs. Code `service_win.py:92 _keep_history_on_close = False` (Kommentar „NEU") plus offscreen-Größen-Checks (≥1300px). Betrifft `serviceui/service_win.py` (unverändert).
* Keine UI-Tests ausgeführt (Regel 4); Working Tree nach Review: 5 geänderte Dateien (`chart/indicator_dialog.py`, `chart/indicators/fixed_grid_proximity.py`, `chart/indicators/multi_ma.py`, `chart/widgets/style_picker_widget.py`, `docs/AKTUELLE_UMSETZUNG.md`). `test/test.py` und `test/check_stylepicker_16_06.py` sind per `.gitignore` nicht versioniert.

---

# Refactoring-Anweisung: Popover StylePickerDialog & Cleanup (16.06.01)

## 1. Problemstellung & Soll-Zustand
* **Problem:** Die aktuelle Umsetzung (E2/E4/E5) verwendet ein Inline-Composite-Layout (Farbe, SpinBox und ComboBoxen nebeneinander direkt in der Formularzeile des Einstellungs-Dialogs)[cite: 2]. Dadurch bleibt das Hauptformular der Indikatoren überladen.
* **Soll-Zustand:** 
  1. Im Einstellungs-Dialog des Indikators darf pro Element **ausschließlich ein einziger kompakter Button** (Farbkästchen + Vorschau-Text `● 2px Solid` / `● Circle`) zu sehen sein.
  2. Erst bei Klick auf diesen Button öffnet sich ein modal/popover **`StylePickerDialog`**.
  3. Der `StylePickerDialog` ist vertikal zweigeteilt:
     * **Oberer Bereich:** Farbwähler + Transparenz-Slider (`QColorDialog` / Color-Grid).
     * **Trennlinie:** Visuelle `QFrame` Horizontallinie (`QFrame.HLine`).
     * **Unterer Bereich:** Zusätzliche Zeichnungsparameter (Linienstärke 1–10 px / Markergröße 1–20 px, Linienstil `solid`/`dashed`/`dotted`/`dashdotted` bzw. Markerform `circle`/`square`/`arrowUp`/`arrowDown`).

---

## 2. Anpassung in `chart/widgets/style_picker_widget.py`

### A. Umbau `StylePickerDialog` (Dialog)
* Erstelle eine eigenständige `QDialog`-Klasse `StylePickerDialog` (Modal).
* **Layout:** `QVBoxLayout`
  1. **Top:** Einbetten der bisherigen Farbauswahl & Transparenz-Steuerung.
  2. **Separator:** `line = QFrame(); line.setFrameShape(QFrame.HLine); line.setFrameShadow(QFrame.Sunken)`
  3. **Bottom (FormLayout):**
     * Bei `style_type == "line"`: SpinBox für `width` (1–10), ComboBox für `style` (`solid`, `dashed`, `dotted`, `dashdotted`).
     * Bei `style_type == "marker"`: SpinBox für `size` (1–20), ComboBox für `shape` (`circle`, `square`, `arrowUp`, `arrowDown`).
  4. **Buttons:** `[Abbrechen]` und `[Übernehmen]` (Ok / Cancel Button-Box).

### B. Umbau `StylePickerWidget` (Inline-Button)
* Entferne alle direkt sichtbaren SpinBoxen, ComboBoxen und CheckBoxes aus dem Layout des `StylePickerWidget`.
* Das Widget besteht **ausschließlich aus einem `QPushButton`** (Farb-Swatch + Vorschau-Text).
* **Klick-Event (`clicked`):** Instanziiert `StylePickerDialog`, übergibt das aktuelle `LineStyle`/`MarkerStyle`-Objekt, führt `.exec()` aus und übernimmt bei Erfolg das geänderte Style-Objekt. Emittiere `style_changed(object)`.

---

## 3. Bereinigung Indikator-Dialoge & Parameterschemata

### A. `chart/indicator_dialog.py`
* Stelle sicher, dass die Formularzeilen für Farbfelder nur noch die kompakte `StylePickerWidget`-Schaltfläche rendern.
* Stelle sicher, dass `_style_sibling_keys()` beim Speichern/Laden die Sibling-Keys (`*_width`, `*_style`, `*_size`, `*_shape`) weiterhin fehlerfrei liest und schreibt[cite: 2].

### B. `chart/indicators/fixed_grid_proximity.py` & `chart/indicators/multi_ma.py`
* Keine separaten Einzelfelder (Linienstärke, Linienstile, Markergrößen) direkt im Formular rendern[cite: 2].
* Alle visuellen Einstellungen laufen exklusiv über den Popover-`StylePickerDialog`[cite: 2].

---

## 4. Anweisung für die IDE-AI (Ausführung & Verifikation)

1. **Bugfixing-Modus beachten:** Nutze gezielte Snippets und mache nur minimale, strukturelle Korrekturen[cite: 1, 2].
2. **Statischer Check (keine UI-Tests):** Führe nach den Anpassungen ausschließlich den Syntax-Check durch[cite: 1]:

   python -m py_compile chart/widgets/style_picker_widget.py chart/indicator_dialog.py chart/indicators/multi_ma.py chart/indicators/fixed_grid_proximity.py


3. **Führe KEINE GUI-/UI-Tests aus** (Harte Projektregel 4).

---

## 5. Präzisierung der Dialog-Interna & API-Garantie (Kritisch)

* **Farbbereich (`StylePickerDialog` Top):** Baue ein kompaktes Custom-Widget (Palette-Grid + Transparenz-Slider 0-100% + QColorDialog-Modal-Button als Fallback). Kein QColorDialog(Qt.Widget) verwenden.
* **`color_only`-Handling:** Ist `color_only=True`, schalte die `QFrame.HLine`-Trennlinie und den unteren Formularbereich im Dialog auf `setVisible(False)` und verkleinere den Dialog.
* **Schnittstellen-Invariante:** `StylePickerWidget` MUSS folgende API 1:1 bereitstellen:
  - Methods: `get_style()`, `set_style(obj)`, `set_color(color_str)`
  - Props: `style_type` ("line"|"marker"), `color_only` (bool), `show_visibility` (bool)
  - Signal: `style_changed(object)`
  - Innerer Zugriff `ctrl.get_style().color` muss garantiert funktionieren!

---

## 6. Implementierungs-Log 16.06.01 (Stand 07.08.2026)

### E7: Popover StylePickerDialog & Button-Only-Cleanup umgesetzt (16.06.01)
* **Umsetzung (Refactoring-Anweisung 16.06.01, Kapitel 1–5):**
  * **`chart/widgets/style_picker_widget.py` neu strukturiert:**
    * **`StylePickerDialog`** (modal, `QDialog`): vertikal zweigeteilt –
      oberer Bereich = kompaktes Custom-Color-Grid (TradingView-Palette mit
      16 Farben + Hex/RGB-Eingabefeld + Transparenz-Slider 0–100% +
      `[Anpassen...]`-Fallback auf `QColorDialog.getColor()`; bewusst KEIN
      `QColorDialog(Qt.Widget)`-Trick, Entscheidung 1), darunter
      `QFrame.HLine`-Trennlinie (Sunken), unterer Bereich = `QFormLayout`
      mit width 1–10 / size 1–20 (QSpinBox) und style `LINE_STYLES` /
      shape `MARKER_SHAPES` (QComboBox), abschließend `QDialogButtonBox`
      `[Abbrechen]` / `[Übernehmen]`.
    * **`color_only=True`:** Trennlinie + unterer Bereich werden per
      `setVisible(False)` ausgeblendet und der Dialog via `adjustSize()` auf
      die reine Farbwahl verkleinert (Entscheidung 2).
    * **`StylePickerWidget` = Button-Only:** Layout besteht ausschließlich aus
      einem `QPushButton` (Farb-Swatch-Icon 16×16 + Vorschau-Text `● 2px Solid`
      bzw. `● Circle`). Klick → `StylePickerDialog.exec()`; bei
      `[Übernehmen]` wird das geänderte Style-Objekt übernommen und
      `style_changed` emittiert. Das Inline-Composite (QCheckBox + Swatch +
      QSpinBox + QComboBox in der Formularzeile) ist entfernt.
  * **API-Invariante (Entscheidung 3) 1:1 erfüllt:** `get_style()` /
    `set_style(obj)` / `set_color(color_str)` / `color()`, Properties
    `style_type` ("line"|"marker"), `color_only` (bool), `show_visibility`
    (bool), Signal `style_changed(object)`. Innerer Zugriff
    `ctrl.get_style().color` funktioniert garantiert.
  * **`show_visibility=True`:** Der Dialog zeigt im unteren Bereich eine
    `sichtbar`-Checkbox (ersetzt die frühere Inline-Checkbox); `get_style()`
    liefert dann deren Zustand als `show`. Bei `show_visibility=False`
    bleibt `show` unverändert (separater `show_*`-Param steuert die
    Sichtbarkeit).
  * `chart/widgets/__init__.py`: `StylePickerDialog` additiv re-exportiert
    (Kapitel 3, Regel 9: keine Bestandscode-Änderungen).
  * `chart/indicator_dialog.py`, `multi_ma.py`, `fixed_grid_proximity.py`:
    **keine Änderungen nötig** – die Fassade ist unverändert, der
    Sibling-Roundtrip (`_style_sibling_keys`/`_build_preset_payload`/
    `collect_params_from_ui`/`update_ui_from_params`) und die Schemata
    bleiben intakt.
* **Verifikation (headless, kein GUI-Start; Regel 4/4.5):**
  * `python -m py_compile` auf `style_picker_widget.py`, `widgets/__init__.py`,
    `indicator_dialog.py`, `multi_ma.py`, `fixed_grid_proximity.py`,
    `style_models.py` → EXIT=0.
  * `test/check_stylepicker_16_06.py` (headless, venv, UTF-8): A1–A4
    (Button-Only ohne Inline-Composite, API-Invariante, Defaults MA1 w2/solid
    + MA2 w1/solid, Vorschau `● 2px Solid`), B1–B4 (Line-/Marker-Picker
    Button-Only, KEINE Alt-Einzelfelder gerendert/persistiert, Schema ohne
    Alt-Keys), C1–C7 (Dialog zweigeteilt, Spin-Ranges 1–10/1–20 + Combos,
    color_only kompakt via `setVisible(False)`, `get_style()` nach
    Übernahme, Farbbereich vollständig, `set_style`/`set_color`, `style_changed`-
    Emission via Auto-Accept ohne GUI), D1 (WindowCloseButtonHint für beide
    Dialoge) — alle PASS (EXIT=0).
  * `test/test.py` (headless, venv): alle 16.06-Checks weiterhin PASS
    (D4 volle Picker ohne Checkbox/`ma1_bear_color` color_only/Picker-Defaults,
    D5 Sibling-Keys in display_params, Teil 11 G1–G5). Einzige Fails:
    vorbestehende ServiceWindow-Checks P2/P5/H3/H4/H5/H7 (dokumentiert in E6;
    betrifft `serviceui/service_win.py`, unverändert).
* Keine UI-Tests ausgeführt (Regel 4); Working Tree nach Umsetzung:
  `chart/widgets/style_picker_widget.py`, `chart/widgets/__init__.py`,
  `docs/AKTUELLE_UMSETZUNG.md` (`test/check_stylepicker_16_06.py` ist per
  `.gitignore` nicht versioniert).



---

# Kapitel 16.07: Two-Tier Caching & Dynamic Range Management

## 1. Executive Summary & Zielsetzung
Zweistufige Datenarchitektur (**Two-Tier Caching**), die das Laden und Berechnen historischer Marktdaten (OHLCV) und Indikator-Overlays beim Scrollen in die Vergangenheit entkoppelt. Sie kombiniert minimale JS-Render-Last im Chart (Tier 1) mit einem erweiterten RAM-Datenpuffer im Python-Backend (Tier 2), um nahtloses, latenzfreies Scrollen ohne Performance-Einbußen zu gewährleisten.

---

## 2. Die Zwei-Stufen-Architektur (Two-Tier Concept)

* **Tier 1: Frontend Render Window (JS / LWC v5)**
  * **Umfang:** Hält strikt nur das aktive Darstellungsfenster (z. B. $N = \text{chart\_candle\_limit} \approx 1.000$ Kerzen) im DOM/Canvas.
  * **Aufgabe:** Gewährleistet flüssiges Rendering mit 60 FPS ohne Memory-Leaks.
  * **Verhalten:** Erhält synchrone, bereits berechnete Gesamt-Pakete (OHLCV-Candles + fertige Indikator-Payloads) direkt von Python per JS-Bridge.

* **Tier 2: Backend Memory Buffer (Python / `MATemplateEngine` & FeatureBuilder)**
  * **Umfang:** Puffert ein erweitertes Historien-Fenster im RAM (z. B. $M = N \cdot 10 \approx 10.000$ Kerzen).
  * **Aufgabe:** Führt Indikator-Berechnungen durch und bedient Nachlade-Anfragen des Frontends verzögerungsfrei (0 ms I/O-Latenz).
  * **Storage Fallback:** Lädt asynchron Blöcke aus `market_data.duckdb` (`ohlcv_bars`) nach, sobald der Tier-2-RAM-Puffer nach links erschöpft ist.

---

## 3. Dynamisches Nachladen, Warmup & Range Management

[ DuckDB Storage ] ──(Async Chunk)──> [ Tier 2: RAM Buffer (10.000) ] ──(Sliding View)──> [ Tier 1: JS Canvas (1.000) ]
│                                       │
[DB-Lookback]                           [Warmup Vorlauf]



1. **Sliding Window Shift (Tier 1 ↔ Tier 2):**
   * Das Frontend überwacht den Scroll-Rand via `visibleLogicalRangeChanged`.
   * Nähert sich die Viewport-Position dem linken Rand ($< 100$ verbleibende Kerzen im Canvas), fordert JS per Bridge den nächsten Daten-Ausschnitt aus dem Tier-2-RAM-Puffer an.
   * Der sichtbare Bereich in JS wird unter Beibehaltung der `visibleLogicalRange` nahtlos aktualisiert, ohne dass der Chart springt.

2. **Backend Chunk Fetch (Tier 2 ↔ DuckDB):**
   * Erreicht der Tier-1-Viewport die $20\%$-Grenze des Tier-2-RAM-Puffers, stößt Python im Hintergrund (QThread) das Nachladen des nächsten Chunks aus `market_data.duckdb` an.
   * DB-Fetches werden bei schnellem Scrollen debounced (300 ms).

3. **Lookback / Warmup Buffer (Mathematische Nahtstellen-Garantie):**
   * Zur Vermeidung von Indikator-Verzerrungen (z. B. bei rekursiven Alpha-EMAs / EHMA / Smoothed MA) liest Tier 2 aus DuckDB immer eine erweiterte Historie aus:
     $$\text{Warmup-Vorlauf} = \text{period} \cdot 4 + \text{smoothing} \cdot 3$$
   * Dieser reine Warmup-Vorlauf wird für die mathematische Einschwingphase genutzt und danach verworfen; nur valide Indikator-Punkte fließen in den Tier-2-Puffer und an Tier 1.

4. **Live-Tick-Entkopplung bei Historien-Ansicht:**
   * Befindet sich der Anwender in der Historie (nicht am rechten Rand), aktualisieren eingehende Live-Ticks den Tier-2-Puffer im Hintergrund, verändern jedoch nicht den aktiven Historien-Viewport in Tier 1.

---

# 16.08 Meta-Ordner im MasterTree (Dynamic Category Trees)

## 1. Executive Summary & Zielsetzung
Dynamische Verschachtelung von Service-Plugins und Standalone-Services im 2-Spalten-MasterTree (`ServiceSelectorWidget`) basierend auf dem Metadaten-Feld `"category"` der Plugins (z. B. `category: "Swing Points/Fraktale"`)[cite: 1]. Ermöglicht freie, beliebig tiefe Ordnerstrukturen ohne manuelle DB-Persistenz oder UI-Hardcoding (Open/Closed Principle)[cite: 1].

---

## 2. Metadaten-Spezifikation (Plugin-Ebene)
Jedes `PluginFeature` unter `analytics/features/definitions/` (bzw. `custom_plugins/`) kann in seinem `metadata`-Dict einen Slash-separierten Kategorienpfad deklarieren[cite: 1]:


# Beispiel: analytics/features/definitions/supertrend.py
metadata = {
    "display_name": "Supertrend (ATR Stop)",
    "category": "Trend Services/Volatilität & Bänder",  # <-- Dynamischer Pfad
    "description": "Dynamischer Trailing Stop auf ATR-Basis",
}

* **Fallback:** Fehlt das Feld `category` oder ist es leer, wird das Plugin direkt in der jeweiligen Hauptgruppe (`⚡ Standalone Services` bzw. `📦 Alle verfügbaren Plugins`) auf oberster Ebene einsortiert.

---

## 3. Anpassungs-Anleitung für die IDE-AI

### Schritt 1: `ServiceSelectorModel.build_tree()` in `analytics/engine/service_selector_model.py` anpassen

Erweitere die Baum-Aufbaulogik für die Gruppen `GROUP_STANDALONE` und `GROUP_PLUGINS` um eine Pfad-Knoten-Helper-Funktion (z. B. `_insert_into_category_tree`):

1. **Pfad-Parsing:**
* Lese `category = plugin.metadata.get("category", "")` aus.


* Ist `category` vorhanden, spalte den String am Slasher: `parts = [p.strip() for p in category.split("/") if p.strip()]`.


2. **Rekursive Knoten-Erzeugung:**
* Traverse/Erstelle Ordnerknoten entlang der Pfad-Teile `parts`.
* Ein Ordnerknoten besitzt das Format:

{
    "group": "category_node",
    "label": "📁 Ordnername",
    "children": [...]
}


3. **Einsortierung:**
* Platziere das finale Plugin-Node-Dict (mit `plugin_id`, `badge`, `last_execution`) im tiefsten Zielordner.

---

### Schritt 2: MasterTree UI-Rendering in `serviceui/master_tree.py` absichern

Stelle sicher, dass der `MasterTree` Category-Nodes (`group == "category_node"`) korrekt als nicht-auswählbare, aufklappbare Ordner mit Icon (`📁`) darstellt:

* Ordnerknoten erhalten das Ordner-Icon `📁` und sind expandierbar.
* Die Mehrfachauswahl / Checkbox-Logik ignoriert Ordnerknoten oder reicht den Check-Zustand kaskadierend an die Kind-Elemente weiter.

---

## 4. Verifikation (Backend & Tests)

1. **Statischer Check (Keine UI-Tests, Harte Regel 4):**
python -m py_compile analytics/engine/service_selector_model.py serviceui/master_tree.py

2. **Isolierter Logik-Test in `test/test.py`:**
* Teste `ServiceSelectorModel().build_tree()` mit gemockten Plugins, die geschachtelte Kategorien (`"A/B/C"`) besitzen.
* Assert: Die erzeugte Baumstruktur enthält die entsprechenden Ordnerknoten und Kinder in deterministischer Reihenfolge.

---

# Kapitel 16.08 – Review & Finale Entscheidungen (07.08.2026, kritische Prüfung gegen Ist-Code)

> **Status:** Kapitel 16.08 ist ein **Konzept/Plan**, keine Umsetzung. Der Ist-Code wurde kritisch geprüft (service_selector_model.py, master_tree.py, base_plugin.py, feature_builder.py). Die Entscheidungen **K1–K10 sind final** (Anwender-Review, 07.08.2026) und verbindlich für die Umsetzung. **Coding startet erst nach ausdrücklichem Startbefehl des Anwenders.**

## 1. Konsistenz mit dem Ist-Code (Abweichungen)

1. **`category` existiert bereits als Metadaten-Feld – aber mit Default `"General"`:**
   `PluginMetadata` (`analytics/features/plugins/base_plugin.py:157`) enthält schon das Feld `category`; `PluginFeature.metadata` (Zeile 209) liefert als **Default `"General"`**. Die Ist-Plugins setzen `"Grid"` (grid_lines_service.py / proximity_service.py). **Abweichung zum Kapitel:** Das Kapitel sagt „Fehlt `category` oder ist es leer → oberste Ebene". Mit dem Ist-Default würden Plugins ohne explizite Kategorie in einen Ordner `📁 General` einsortiert – nicht auf oberster Ebene. Der Fallback muss den Default `"General"` (und leere Strings) als „keine Kategorie" behandeln.
2. **`build_tree()` liefert heute FLACHE Kinder:** `standalone_nodes`/`plugin_nodes` (`service_selector_model.py:439/451`) sind flache Listen aus `{plugin_id, badge, last_execution}`. Es gibt **keine** Ordner-/Verschachtelungsstruktur, keinen Pfad-Parser, keinen Kategorie-Lookup. Das Kapitel-Knotenformat `{"group": "category_node", "label": "...", "children": [...]}` ist neu – `build_tree` muss es erzeugen (additiv, Bestandsverhalten bleibt für `GROUP_SETS`).
3. **`MasterTree._build_child_item` kennt nur 3 Gruppen:** Der Dispatch (`master_tree.py:348–354`) behandelt `GROUP_SETS`/`GROUP_STANDALONE`/`GROUP_PLUGINS` und gibt sonst `None`. `category_node`-Kinder würden verworfen. Für Ordner braucht es **Rekursion** (`_build_child_item` ruft sich für `children` selbst auf) + einen neuen Node-Typ.
4. **Kein `TYPE_CATEGORY`:** Es existieren `TYPE_GROUP`/`TYPE_SET`/`TYPE_SERVICE`/`TYPE_PLUGIN` (`master_tree.py:95–98`). Ordnerknoten benötigen einen eigenen Typ, damit Selektion, Info-Buttons, Checkboxen und Kontextmenü sie korrekt behandeln (oder bewusst ignorieren).
5. **Kapitel sagt `custom_plugins/` – Ist-Pfad ist `data/custom_plugins/`:** Der `PluginLoader` (`feature_builder.py`) scannt `DATA_DIR / "custom_plugins"`. Das Kapitel muss den Pfad präzisieren.
6. **Nur `PluginFeature`-Subklassen erscheinen im Tree:** `ATRNormalizedFeature`, `EMADiffFeature`, `GridLevelsFeature` sind `BaseFeature` (kein `PluginFeature`) und werden vom Loader **nicht** entdeckt. Das Kapitel impliziert korrekt „Jedes `PluginFeature`" – es sind aktuell nur `grid_lines` und `proximity` (plus Custom). Kein Handlungsbedarf, aber als Randbedingung dokumentiert.
7. **Verifikations-Test braucht einen Registry-Stub:** `ServiceSelectorModel.__init__` akzeptiert `registry=` (`service_selector_model.py:41–49`); `get_plugins()` liest `self.registry.plugins`, `get_plugin()` ruft `registry.get()`. Für den gemockten Plugin-Test muss ein **Duck-Typ-Stub** mit `.plugins`-Dict und `.get()` übergeben werden – nicht `PluginRegistry()` selbst.

## 2. Vollständigkeit – fehlende Aspekte

1. **Sortierregel für Ordner:** Das Kapitel fordert „deterministische Reihenfolge", definiert aber keine Sortierung. Festzulegen: Ordner alphabetisch, innerhalb eines Ordners wieder Ordner → Blätter (alphabetisch, case-insensitiv).
2. **Leere Ordner:** Ein deklarierter Kategorienpfad ohne Plugin-Kinder (z. B. nach Plugin-Entfernung) darf **keinen** leeren Ordner erzeugen – Ordner nur mit ≥ 1 Kind.
3. **Ordner-Kollision Ordner/Blatt:** Was, wenn ein Ordner (`📁 Grid`) und ein Blatt-Plugin dieselbe Anzeige-Ebene teilen? `_insert_into_category_tree` muss Ordner- und Blatt-Knoten auf derselben Ebene mischen können (deterministisch: Ordner zuerst, dann Blätter).
4. **Checkbox-/Multi-Select-Verhalten:** Das Kapitel lässt offen („ignoriert ODER kaskadierend"). Festzulegen: Ordnerknoten sind **nicht anhakbar** (kein `ItemIsUserCheckable`); die bestehende Plugin-Key-Logik (`TYPE_PLUGIN`, "", plugin_id) bleibt unverändert gültig – auch für Plugins innerhalb von Ordnern.
5. **Info-Buttons (Spalte 1):** Ordnerknoten dürfen **keinen** Info-Button tragen. `_attach_item_buttons` (`master_tree.py:479–533`) hängt Buttons nur an `TYPE_SERVICE/TYPE_SET/TYPE_PLUGIN` – Ordner werden automatisch übersprungen (kein Eingriff nötig, aber als Absicherung dokumentieren).
6. **Kontextmenü:** `_show_context_menu` (`master_tree.py:887`) behandelt Gruppe/Set/Service/Plugin. Ordnerknoten: **kein Kontextmenü** (oder nur ausgegraute Struktur-Aktionen) – kein `run_service_requested`/`info_requested` auf Ordnern.
7. **Selektion/Restore:** `current_selection()`/`_restore_selection()`/`_emit_selection_details()` behandeln `TYPE_SERVICE/TYPE_SET` (bzw. `TYPE_PLUGIN` für details). Ordnerknoten liefern nur `node_type` (set_id/service_id/plugin_id leer) → vorhandene Default-Pfade greifen automatisch (kein Crash-Risiko), muss aber im Test abgesichert werden.
8. **`badge`/`last_execution` in Ordnern:** Ordnerknoten haben **keine** Badges/Datum – nur die Plugin-Blätter tragen sie. Die bestehende `_build_plugin_item`-Logik bleibt pro Blatt unverändert.

## 3. Finale Entscheidungen K1–K10 (verbindlich für die Umsetzung)

### K1: Kategorie-Quelle & Fallback → `metadata.get("category")` mit Default-„General"-Behandlung
* Lese `category = str((plugin.metadata or {}).get("category") or "").strip()`.
* **Fallback (oberste Ebene):** `category` ist leer ODER `"General"` (Ist-Default aus `base_plugin.py:209`). Damit bleiben Plugins ohne explizite Kategorie auf der obersten Ebene der Hauptgruppe – exakt wie das Kapitel es verlangt, ohne Änderung des Base-Defaults.
* **Pfad-Parsing:** `parts = [p.strip() for p in category.split("/") if p.strip()]` (wie im Kapitel).

### K2: `build_tree()`-Struktur → Ordner-Dicts verschachtelt, additiv
* `GROUP_STANDALONE`/`GROUP_PLUGINS`: Kinder sind eine **Mischung** aus Blatt-Dicts (`{plugin_id, badge, last_execution}` – unverändert) und Ordner-Dicts (`{"group": "category_node", "label": "📁 <Name>", "children": [...]}` – rekursiv).
* `GROUP_SETS` bleibt unverändert (keine Kategorien für Set-Services).

### K3: Rekursion im MasterTree → `_build_child_item` rekursiv + `TYPE_CATEGORY`
* Neuer Node-Typ `TYPE_CATEGORY = "category"`.
* `_build_child_item`: erkennt Ordner-Dicts an `group == "category_node"` (oder `"children" in child`), erzeugt einen nicht-auswählbaren, expandierbaren Ordner-Knoten (📁 im Label, `~Qt.ItemIsSelectable`, kein `ROLE_PLUGIN_ID`) und ruft sich rekursiv für `children` auf.
* Plugin-Blätter innerhalb von Ordnern nutzen unverändert `_build_plugin_item`.

### K4: Checkbox/Multi-Select → Ordner nicht anhakbar
* Ordnerknoten erhalten **kein** `ItemIsUserCheckable`.
* `_on_item_changed` (Zeile 601): `TYPE_CATEGORY` wird von der Verarbeitung ausgenommen (Guard `node_type not in (TYPE_SET, TYPE_SERVICE, TYPE_PLUGIN)` reicht aus – `TYPE_CATEGORY` fällt durch).
* Plugin-Kinder in Ordnern: bestehende `(TYPE_PLUGIN, "", pid)`-Keys funktionieren unverändert (checked_services/checked_feature_ids/set_checked_feature_ids).

### K5: Info-Buttons → Ordner ohne Button
* `_attach_item_buttons` bleibt unverändert (skip für `TYPE_CATEGORY` automatisch). Absicherung: Test, dass ein Ordner-Knoten `itemWidget(item, 1) is None` liefert.

### K6: Kontextmenü → Ordner ohne Aktionen
* `_show_context_menu`: `TYPE_CATEGORY` erhält **kein** eigenes Menü (leere/Ausgrau-Struktur). Kein `run_service`/`info`/`move`/`remove` auf Ordnern.

### K7: Selektion/Restore → vorhandene Defaults
* `TYPE_CATEGORY` wird in `current_selection`/`_restore_selection`/`_emit_selection_details` nicht speziell behandelt → Default-Pfade liefern `{"set_id":"", "service_id":""}` bzw. nur `node_type`. Test absichern.

### K8: Sortierregel → Ordner vor Blättern, alphabetisch
* Je Ebene: **Ordner zuerst** (alphabetisch, case-insensitiv), danach **Blätter** (alphabetisch, case-insensitiv). Deterministisch über die bestehenden `sorted(...)`-Muster.
* Innerhalb eines Ordners gilt dieselbe Regel rekursiv.

### K9: Keine leeren Ordner
* `_insert_into_category_tree` erzeugt Ordner nur, wenn mindestens ein Plugin-Blatt (oder Unterordner) eingefügt wird. Leere Kategorienpfade erzeugen keine Knoten.

### K10: Verifikation (Kapitel-Erweiterung)
* `py_compile` auf `analytics/engine/service_selector_model.py` + `serviceui/master_tree.py`.
* Logik-Test in `test/test.py` (Teil 13, P16.08) mit **Duck-Typ-Registry-Stub** (`plugins`-Dict + `get()`):
  1. Plugin mit `category="A/B/C"` → Ordner A → B → C, Blatt im tiefsten Ordner.
  2. Plugin ohne/leerer/`"General"`-category → oberste Ebene (K1).
  3. Ordner-vor-Blatt-Sortierung + case-insensitiv (K8).
  4. Kein leerer Ordner bei Kategorie ohne Kinder (K9).
  5. MasterTree (offscreen): Ordner nicht auswählbar, kein Info-Button, Checkbox-Modus ignoriert Ordner; Plugin-Blatt in Ordner bleibt `checked_services`-fähig (K3/K4/K5/K7).
* Keine UI-Tests / keine Regressionstests (Regel 4).

> **Zusammenfassung (Anwender-Urteil):** Das Konzept 16.08 ist schlüssig und vollständig kompatibel mit dem Open/Closed-Prinzip. Kritisch zu prüfen war der **Ist-Default `"General"`** (K1), die **flache `build_tree()`-Struktur** (K2) und die **fehlende Rekursion im MasterTree** (K3). Alle offenen Detailfragen (Checkbox, Kontextmenü, Sortierung, leere Ordner, Verifikation) sind in K4–K10 final entschieden.
>
> **Kein Coding:** Die Entscheidungen sind dokumentiert. Eine Umsetzung von 16.08 erfolgt erst nach ausdrücklichem Startbefehl des Anwenders. *(Inzwischen erfolgt – siehe unten: Implementierungs-Log 16.08, 07.08.2026.)*

---
# Kapitel 16.08 – Implementierungs-Log (07.08.2026, 15:42 Uhr)

> **Status:** Kapitel 16.08 ist **umgesetzt** (K1–K10, siehe Review oben). Implementierungs-Log gemäß Regel 0c – Datum/Uhrzeit 07.08.2026 15:42 Uhr. Verifikation headless (Regel 4: keine UI-Tests, keine Regressionstests) über `test/test.py` Teil 13 (P16.08) sowie `py_compile` auf allen geänderten Dateien.

## 1. Umgesetzte Architektur (Ist-Stand)

* **Metadaten-Quelle (K1):** `metadata.get("category")` der Plugins (Slash-separierter Pfad). **Fallback:** leere Kategorie ODER der Ist-Default `"General"` (`base_plugin.py`) → Plugin bleibt auf der obersten Ebene der Hauptgruppe. Die Ist-Plugins `grid_lines`/`proximity` tragen `category="Grid"` → erscheinen seit 16.08 in einem `📁 Grid`-Ordner.
* **Baumstruktur (K2):** `build_tree()` erzeugt für die Gruppen `⚡ Standalone Services` / `📦 Alle verfügbaren Plugins` eine Mischung aus flachen Blatt-Dicts (`{plugin_id, badge, last_execution}` – unverändert) und verschachtelten Ordner-Dicts `{"group": "category_node", "label": "📁 <Name>", "children": [...]}` (rekursiv). `GROUP_SETS` bleibt unverändert.
* **MasterTree (K3):** Neuer Knotentyp `TYPE_CATEGORY`; `_build_child_item` ist jetzt rekursiv. Ordner sind nicht auswählbar, expandierbar, ohne Info-Button (K5), ohne Kontextmenü (K6) und im Checkbox-Modus nicht anhakbar (K4).

## 2. Umsetzung K1–K10 im Detail

* **K1:** `_category_parts(plugin)` – liest `metadata['category']`, zerlegt am Slash, `""`/`"General"` → `[]` (oberste Ebene).
* **K2:** `_insert_into_category_tree(nodes, parts, leaf)` – rekursive Ordner-Erzeugung entlang des Pfads; Ordner-Dicts im K2-Format.
* **K3:** `_build_child_item` erkennt `group == GROUP_CATEGORY` → `_build_category_item` (rekursiv, nicht auswählbar); Plugin-Blätter in Ordnern nutzen weiterhin `_build_plugin_item` (Badge/Datum unverändert).
* **K4:** Ordnerknoten erhalten `& ~(ItemIsSelectable | ItemIsUserCheckable)` – Qt setzt `ItemIsUserCheckable` standardmäßig (nach Testlauf behoben). `_on_item_changed`/`_sync_checked_from_tree`/`set_checked_feature_ids`/`clear_checks` verarbeiten `TYPE_CATEGORY` automatisch nicht (Guard auf SERVICE/SET/PLUGIN); Plugin-Kinder in Ordnern bleiben `checked_services`-fähig.
* **K5:** `_attach_item_buttons` überspringt `TYPE_CATEGORY` automatisch (kein Info-Button auf Ordnern) – per Test abgesichert.
* **K6:** `_show_context_menu` early-return für `TYPE_CATEGORY` (kein Menü, kein run/info/move/remove auf Ordnern).
* **K7:** `current_selection`/`_restore_selection`/`_emit_selection_details` liefern für Ordner den Default (`{"set_id":"","service_id":""}` bzw. nur `node_type`) – per Test abgesichert.
* **K8:** `_sort_category_nodes` – je Ebene Ordner zuerst (alphabetisch, case-insensitiv via `_cat_key`), dann Blätter; rekursiv in Unterordnern.
* **K9:** Ordner entstehen nur durch tatsächliche Blatt-Einfügung (`_insert_into_category_tree`) → keine leeren Ordner.
* **K10:** `py_compile` + `test/test.py` Teil 13 (P16.08) mit Duck-Typ-Registry-Stub.

## 3. Geänderte Dateien

| Datei | Änderung |
|---|---|
| `analytics/engine/service_selector_model.py` | `GROUP_CATEGORY`, `_cat_key`, `_category_parts`, `_insert_into_category_tree`, `_sort_category_nodes`, `_category_nodes`; `build_tree()`-Kinder via `_category_nodes` (additiv, Sets unverändert) |
| `serviceui/master_tree.py` | `TYPE_CATEGORY`, rekursiver `_build_child_item`, `_build_category_item`, Kontextmenü-Guard |
| `test/test.py` | Teil 13 (P16.08, T1–T5); Teil 5 an 16.08 angepasst (Plugin-Blätter rekursiv statt direkte Gruppen-Kinder – `grid_lines`/`proximity` liegen jetzt in `📁 Grid`) |

## 4. Verifikation (headless, 07.08.2026)

* `py_compile` auf `service_selector_model.py`/`master_tree.py`/`test.py` → EXIT=0.
* `test/test.py` (offscreen, venv, UTF-8): **Teil 13 (P16.08) alle 14 Checks PASS** – T1 verschachtelte Kategorie A/B/C (Ordner-Labels `📁 A/B/C`, Blatt im tiefsten Ordner, Blatt-Dict unverändert), T2 `General`-Fallback → oberste Ebene, T3 Ordner-vor-Blatt alphabetisch (abc/Grid/Trend, Blatt `middle`), T4 keine leeren Ordner, T5 MasterTree offscreen (Ordner nicht auswählbar, kein Info-Button, nicht anhakbar, Plugin-Blatt `checked_services`-fähig, Ordner-Selektion → Default).
* Teile 1–12 unverändert grün; weiterhin exakt **6 vorbestehende ServiceWindow-Fails** (P2/P5/H3/H4/H5/H7 – dokumentiert in E6, betrifft `serviceui/service_win.py` unverändert).
* Keine UI-Tests / keine Regressionstests ausgeführt (Regel 4).


---

# 16.09 - Swing Point Services
**rein auf MT5-OHLCV-/Tick-Volumendaten** basieren, voll **service-fähig** in PyTrader sind und ihre Ergebnisse als `feature_store_payload` für den Analyzer bereitstellen können.

### 1. Fraktale & Bar-Strukturen

| Name | Methode / Logik | Parameter |
| --- | --- | --- |
| Name | Methode / Logik | Parameter |
| --- | --- | --- |
| **HMA / Multi-MA Peak-Toleranz Pivot** | Wendepunkt-Identifikation auf einer geglätteten MA-Linie (nutzt das `MA-Template 16.04` mit allen 12 MA-Typen). Ein fortlaufender Extremwert ($piv\_pendingExtremeValue$) wird erst dann als offizielles Pivot High / Low bestätigt und im `feature_store` geschrieben (`is_swing_high`, `is_swing_low`), wenn die geglättete MA-Linie den Extremwert in Gegenrichtung um einen definierten Prozentabstand (`piv_maxHmaMovePct`) durchbricht (Hysterese-Filterung). | `piv_len` (Int, Def: 4), `hma_type` (Enum: SMA, EMA, WMA, DEMA, TEMA, HMA, EHMA, ZLEMA, RMA, KAMA, ALMA, VWMA, Def: EHMA), `hma_smoothing` (Int, Def: 10), `hma_alpha` (Float, Def: 2.0), `piv_maxHmaMovePct` (Float, Def: 0.2) || **Pivot High/Low (Williams)** | Identifiziert Hoch/Tief, wenn $N$ Nachbar-Kerzen links/rechts niedrigere Hochs bzw. höhere Tiefs haben. | `left_bars` (Int, Def: 2), `right_bars` (Int, Def: 2) |
| **ZigZag (Bar-Count)** | Extremwert-Suche mit fester Anzahl von Bestätigungskerzen vor/nach Richtungswechsel. | `depth` (Int, Def: 12), `deviation` (Int, Def: 5), `backstep` (Int, Def: 3) |
| **Period Extrema (PDH/PWH)** | Extrahiert Höchst-/Tiefstkurse fester Zeitabschnitte (Vortag, Vorwoche, Vormonat). | `period` (Enum: D1, W1, MN1), `extend_session` (Bool) |
| **Gann Mechanical Swings** | Richtungswechsel erfordert $N$ aufeinanderfolgende Höhere Hochs / Tiefere Tiefs. | `consecutive_bars` (Int, Def: 2) |

---

### 2. Volatilitäts- & Dynamik-Filter

| Name | Methode / Logik | Parameter |
| --- | --- | --- |
| **ZigZag (ATR-Dynamik)** | Wendepunkt wird erst nach einer Kursabweichung um ein Vielfaches der ATR bestätigt. | `atr_period` (Int, Def: 14), `atr_mult` (Float, Def: 2.0) |
| **ZigZag (%-Abweichung)** | Wendepunkt wird erst nach einer prozentualen Kursänderung vom letzten Extremwert fixiert. | `change_pct` (Float, Def: 0.5) |
| **Smoothed MA Slope Change** | Erkennt Wendepunkte durch Vorzeichenwechsel der Steigung geglätteter MAs ($t$ vs. $t-1$). | `ma_type` (Enum, Def: EHMA), `period` (Int, Def: 20), `slope_thresh` (Float) |
| **Chande Kroll Swings** | Ausbruch über/unter dynamische ATR-Trailing-Stops signalisiert neuen Swing. | `p_atr` (Int, Def: 10), `x_atr` (Float, Def: 3.0), `p_stop` (Int, Def: 20) |

---

### 3. Volumen & Preis-Grid (MT5 Tick-Volumen)

| Name | Methode / Logik | Parameter |
| --- | --- | --- |
| **Grid Proximity Swings** | Preisnähe & Rejection an festen Preis-Muster-Linien (z. B. 0.50 Steps) im Zeitfenster. | `grid_step` (Float, Def: 0.5), `proximity_thresh` (Float), `time_window` (Int) |
| **Multi-Period Volume Profile & LVN Swings** | Volumengewichtete Profil-Analyse über flexible Zeiträume (X Bars, Sessions, $N$ Kalendertage/Wochen/Monate, benutzerdefinierte Datumsbereiche mit Ausnahmeregeln). Ermittelt pro aggregiertem Volumenblock ($>\text{volume\_thresh\_pct}$) eigene POC-, VAH- und VAL-Level. Zusätzlich werden **Low Volume Nodes (LVNs)** als Rejection-Knoten und potenzielle Swing Points/Wendepunkte identifiziert. | `time_mode` (Enum: Bars/Sessions/Days/Weeks/Months/Custom), `period_val` (Int, Def: 1), `exclude_rules` (List: OffHours/Holidays), `volume_thresh_pct` (Float, Def: 5.0), `value_area_pct` (Float, Def: 0.70), `lvn_sensitivity` (Float, Def: 0.20) |
| **Anchored VWAP Swings** | Wendepunkte an den Standardabweichungs-Bändern eines ab Pivots verankerten VWAPs. | `anchor_event` (Enum: SessionStart/NewHigh), `stdev_mult` (Float, Def: 2.0) |

---

### 4. Datenvertrag im Feature Store (Analyzer-Konsum)

Alle diese Services schreiben im selben einheitlichen Schema in den `feature_store` (`analytics.duckdb`):

* **Standard-Payload (`feature_data JSON`):**
* `is_swing_high`: Bool
* `is_swing_low`: Bool
* `swing_price`: Float (Preis des Wendepunkts)
* `swing_strength` / `distance`: Float (Stärke des Swings in ATR, % oder Punkten)
---

# 16.10 Trend Services

**Rein auf MT5-OHLCV-/Tick-Volumendaten** basierende, voll **service-fähige** Trend- und Reversal-Erkennungsalgorithmen in PyTrader, die ihre Ergebnisse als `feature_store_payload` für den Analyzer und Chart bereitstellen.

### 1. Trend- & Reversal-Services

| Name | Methode / Logik | Parameter |
| --- | --- | --- |
| **HMA Peak-Toleranz Pivot** | Wendepunkt- und Trendwechsel-Erkennung auf geglätteter EHMA/HMA. Trendwechsel erfordert das Durchbrechen des letzten Extremwerts ($piv\_pendingExtremeValue$) um einen Prozent-Abstand (`piv_maxHmaMovePct`). | `piv_len` (Int, Def: 4), `hma_type` (Enum: SMA..VWMA, Def: EHMA), `hma_smoothing` (Int, Def: 10), `hma_alpha` (Float, Def: 2.0), `piv_maxHmaMovePct` (Float, Def: 0.2) |
| **Supertrend (ATR Trailing Stop)** | Dynamische Trend-Kanal-Grenzen basierend auf $Median \pm (Mult \cdot ATR)$. Ein Trendwechsel wird bei Schlusskurs-Durchbruch der Trailing-Linie signalisiert. | `atr_period` (Int, Def: 10), `atr_mult` (Float, Def: 3.0) |
| **Linear Regression Slope & $R^2$** | Ermittlung der Ausgleichsgerade über $N$ Bars. Trennt Trend- vs. Range-Phasen anhand des Bestimmtheitsmaßes ($R^2 > 0.6$ = starker Trend). | `length` (Int, Def: 20), `r2_threshold` (Float, Def: 0.6) |
| **ADX & Directional Movement (DMI)** | Glättung von $+\text{DI}$ und $-\text{DI}$ zur Quantifizierung von Richtungsdynamik und Trendstärke ($ADX > 25$ = echtes Trend-Regime). | `di_period` (Int, Def: 14), `adx_smooth` (Int, Def: 14), `adx_threshold` (Float, Def: 25.0) |
| **Donchian / Keltner Breakout** | Trendausbruchs-Erkennung beim Verlassen von $N$-Bar-Extrema oder ATR-Bändern um geglättete Durchschnitte. | `period` (Int, Def: 20), `atr_mult` (Float, Def: 2.0), `ma_type` (Enum, Def: EMA) |
| **Chande Kroll Ratchet** | Dynamische Trailing-Stops auf Basis von High/Low-Extrema und Volatilität zur Trendfolgesteuerung mit adaptivem Risikomanagement. | `p_atr` (Int, Def: 10), `x_atr` (Float, Def: 3.0), `p_stop` (Int, Def: 20) |
| **Smoothed MA Slope Change** | Mathematische Richtungs- & Steigungsmessung geglätteter Durchschnitte ($MA_t - MA_{t-1}$) zur rauschfreien Trendbestimmung. | `period` (Int, Def: 20), `ma_type` (Enum, Def: EHMA), `slope_thresh` (Float, Def: 0.0) |
| **Z-Score Mean Distance** | Quantifiziert die Abweichung des Preises vom Mittelwert in Standardabweichungen ($Z = \frac{P - MA}{\sigma}$). Signalisiert Reversals bei Extremlagen ($|Z| > 2.0$). | `period` (Int, Def: 20), `z_thresh` (Float, Def: 2.0), `ma_type` (Enum, Def: SMA) |

---

### 2. Datenvertrag im Feature Store (Analyzer- & Chart-Konsum)

Alle Trend-Services schreiben in demselben einheitlichen Schema in den `feature_store` (`analytics.duckdb`):

* **Standard-Payload (`feature_data JSON`):**
  * `is_trend_up`: Bool (True bei aktivem Aufwärtstrend)
  * `is_trend_down`: Bool (True bei aktivem Abwärtstrend)
  * `trend_strength`: Float (Quantifizierte Trendstärke: z. B. $R^2$, ADX-Wert, Slope oder ATR-Abstand)
  * `swing_price`: Float (Preis des auslösenden Wendepunkts / Trailing-Stops)

