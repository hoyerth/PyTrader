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
   * Für Alpha-MAs (`EHMA`, `DEMA`, `TEMA`): Verfahre über den dynamischen Decay-Faktor $\alpha = \frac{\text{alpha\_factor}}{\text{period} + 1}$.
3. `build_color_series(ma_series: pd.Series, dual_color: bool, bull_color: str, bear_color: str) -> List[str]`:
   * Vergleiche $t$ vs. $t-1$.
   * Wenn `dual_color==False`: Verwende durchgehend `bull_color`.
   * Wenn `dual_color==True`: $ma_t \ge ma_{t-1} \rightarrow$ `bull_color`, sonst `bear_color`.
4. `build_chart_payload(time_series: pd.Series, ma_series: pd.Series, colors: List[str]) -> List[Dict[str, Any]]`:
   * Formatiere das Array direkt als LWC-kompatibles Objekt-Array: `[{"time": ts, "value": val, "color": col}, ...]`.

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

# Phase 16.05 - Multi MA Indikator

Erstelle den Multi-MA-Indikator unter `chart/indicators/multi_ma.py`.
Der Indikator erbt von `BaseIndicator` und nutzt die `MATemplateEngine` aus Phase 16.04 (`chart/indicators/utils/ma_template.py`).

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

---

# Kapitel 16.06: Two-Tier Caching & Dynamic Range Management

## 1. Executive Summary & Zielsetzung
Zweistufige Datenarchitektur (**Two-Tier Caching**), die das Laden und Berechnen historischer Indikator-Daten beim Scrollen in die Vergangenheit entkoppelt[cite: 1, 4]. Sie kombiniert minimale JS-Render-Last im Chart (Tier 1) mit einem erweiterten RAM-Datenpuffer im Python-Backend (Tier 2), um nahtloses, latenzfreies Scrollen ohne Performance-Einbußen zu gewährleisten[cite: 1, 4].

## 2. Die Zwei-Stufen-Architektur (Two-Tier Concept)

* **Tier 1: Frontend Render Window (JS / LWC v5)**
  * **Umfang:** Hält strikt nur das aktive Darstellungsfenster (z. B. $N = \text{chart\_candle\_limit} \approx 1.000$ Kerzen) im DOM/Canvas[cite: 4].
  * **Aufgabe:** Gewährleistet ein flüssiges Rendering mit 60 FPS[cite: 1]. 
  * **Verhalten:** Erhält finale, bereits berechnete Daten-Pakete (Candles & MA-Werte) direkt von Python[cite: 1].

* **Tier 2: Backend Memory Buffer (Python / `MATemplateEngine`)**
  * **Umfang:** Puffert ein erweitertes Historien-Fenster im RAM (z. B. $M = N \cdot 10 \approx 10.000$ Kerzen)[cite: 4].
  * **Aufgabe:** Führt Indikator-Berechnungen durch und bedient Nachlade-Anfragen des Frontends verzögerungsfrei (0 ms I/O-Latenz)[cite: 1, 4].
  * **Storage Fallback:** Greift auf `market_data.duckdb` (`ohlcv_bars`) erst zu, wenn der Tier-2-RAM-Puffer an seine Grenzen stößt[cite: 4].

## 3. Dynamisches Nachladen & Warmup-Buffering


```
[ DuckDB Storage ] ──(Chunk Fetch)──> [ Tier 2: RAM Buffer (10.000) ] ──(Sliding View)──> [ Tier 1: JS Canvas (1.000) ]
│
[ Warmup / Lookback ]

```

* **Sliding Window Shift:**
  * Das Frontend überwacht den Scroll-Rand via `visibleLogicalRangeChanged`[cite: 1].
  * Nähert sich die Viewport-Position dem linken Rand (z. B. $< 100$ verbleibende Kerzen), fordert JS bei Python per Bridge Daten nach[cite: 1].
* **Lookback / Warmup Buffer:**
  * Zur Vermeidung von MA-Berechnungsverzerrungen an Block-Rändern rechnet Tier 2 immer über ein erweitertes Fenster ($T_{\text{left}} - \text{Period} \cdot 3$ bis $T_{\text{right}}$).
  * Der reine Warmup-Vorlauf wird verworfen; nur mathematisch valide MA-Punkte werden an Tier 1 übergeben.
* **Debounced I/O & Memory Cap:**
  * DB-Fetches aus DuckDB werden bei schnellem Wischen debounced (300 ms)[cite: 4].
  * Tier 2 verwaltet einen Ringpuffer; alte Kerzen am rechten Ende (Zukunft) werden bei zu hohem RAM-Bedarf verworfen und bei Bedarf aus der DB nachgeladen[cite: 4].

---

# 16.07 - Swing Point Services
**rein auf MT5-OHLCV-/Tick-Volumendaten** basieren, voll **service-fähig** in PyTrader sind und ihre Ergebnisse als `feature_store_payload` für den Analyzer bereitstellen können.

### 1. Fraktale & Bar-Strukturen

| Name | Methode / Logik | Parameter |
| --- | --- | --- |
| **Pivot High/Low (Williams)** | Identifiziert Hoch/Tief, wenn $N$ Nachbar-Kerzen links/rechts niedrigere Hochs bzw. höhere Tiefs haben. | `left_bars` (Int, Def: 2), `right_bars` (Int, Def: 2) |
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
| **Session Volume Profile** | Identifiziert POC, VAH und VAL basierend auf Historiendaten & MT5 `tick_volume`. | `session_type` (Enum: Daily/Weekly), `value_area_pct` (Float, Def: 0.70) |
| **Anchored VWAP Swings** | Wendepunkte an den Standardabweichungs-Bändern eines ab Pivots verankerten VWAPs. | `anchor_event` (Enum: SessionStart/NewHigh), `stdev_mult` (Float, Def: 2.0) |

---

### 4. Datenvertrag im Feature Store (Analyzer-Konsum)

Alle diese Services schreiben im selben einheitlichen Schema in den `feature_store` (`analytics.duckdb`):

* **Standard-Payload (`feature_data JSON`):**
* `is_swing_high`: Bool
* `is_swing_low`: Bool
* `swing_price`: Float (Preis des Wendepunkts)
* `swing_strength` / `distance`: Float (Stärke des Swings in ATR, % oder Punkten)