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

### Schritt 1: Style-Verträge erstellen (`chart/overlays/style_models.py`)
* Erstelle Dataclasses `LineStyle` (`color`, `width`, `style`, `show`) und `MarkerStyle` (`color`, `shape`, `size`, `show`).
* Implementiere `.to_js_dict()` (für JS-Bridge) und `.to_dict()` / `.from_dict()` (für JSON-Preset-Persistenz im `StateManager`).

### Schritt 2: StylePickerWidget ausbauen (`chart/widgets/style_picker_widget.py`)
* Umbenennung/Ausbau des alten Farb-Buttons zu `StylePickerWidget`.
* Integration von `QCheckBox` (show), `ColorButton` (color), `QSpinBox` (width/size) und `QComboBox` (style/shape).
* Implementiere `get_style()` / `set_style()` für `LineStyle` und `MarkerStyle`.

### Schritt 3: Services & Indikatoren auf Style-Objekte umstellen
* **`grid_lines_service.py`:** Ersetze Einzel-UI-Params im `parameter_schema` durch ein zentrales `LineStyle`-Objekt.
* **`proximity_service.py`:** Ersetze Einzel-Params im `parameter_schema` durch zwei `MarkerStyle`-Objekte (`marker_std_style` für Hit im Zeitfenster, `marker_active_style` für Hit außerhalb).
* **`fixed_grid_proximity.py` & `indicator_dialog.py`:** 
  * Binde `StylePickerWidget` für Style-Felder im Einstellungs-Dialog dynamisch ein.
  * Nutze `.to_js_dict()` in `build_chart_render_payload()` zur Generierung der Canvas-Grafiken.

### Schritt 4: Preset-Mechanismus & Migration absichern
* In `chart/indicator_dialog.py`: Konvertiere Style-Objekte vor `state_manager.save_indicator_preset()` via `.to_dict()` in JSON-kompatible Dicts.
* In `analytics/engine/schema_migrator.py`: Stelle sicher, dass Alt-Presets ohne Style-Objekte transparent auf die neuen Schema-Defaults migriert werden.

### Schritt 5: Headless-Verifikation
* Statische Syntaxprüfung via `python -m py_compile` auf allen geänderten Dateien.
* Erstelle Test-Datei `test/check_p16_s3_style_objects.py`:
  * Prüfe `to_js_dict()` & `to_dict()` / `from_dict()` Konvertierung.
  * Prüfe JSON-Serialisierung im `StateManager` ohne `TypeError`.

## Implementierungs-Log

- **15.03 Pruefstand (Ist-Analyse)**
  - Datum/Uhrzeit: 06.08.2026 (MD)
  - Umgesetzt: Konsistenz-Analyse der 15.03-Bausteine (Profile-Repo, Reader/Repo, Worker/ViewModel, AnalyticsWindow + 5 Pages, main.py-Ersatz, E-1/E-2, 15.03-E ServiceSelectorDialog) gegen die Spezifikation; py_compile auf 17 Dateien (OK); Suche nach toten Referenzen (keine).
  - Ergebnis: 15.03 vollständig umgesetzt und committet (bf92298, 2579410, b62d3ed, 14ff6d9). Keine Code-Aenderungen erforderlich.
  - Offen/Entscheidung Benutzer: (1) E-2-Migration auf WindowStateRepository nachziehen? (2) 15.03-Regressionstests entfernt - ausreichend? (3) P16.03-Konzept: LineStyle/MarkerStyle in chart/overlays/style_models.py harmonisieren.


---

## 16.04 Generische MA Linien

MAType = Literal[
    "SMA",    # Simple
    "EMA",    # Exponential
    "WMA",    # Weighted
    "DEMA",   # Double Exponential
    "TEMA",   # Triple Exponential
    "HMA",    # Hull
    "EHMA",   # Exponential Hull
    "ZLEMA",  # Zero Lag
    "RMA",    # Wilder's Smoothing (Running)
    "KAMA",   # Kaufman Adaptive
    "ALMA",   # Arnaud Legoux
    "VWMA"    # Volume Weighted
]

- Vektorisierung mit numpy wenn sinnvoll
- sinnvolle, verschiedene Farben als default (nicht grün/rot)
- für erstes Linienobjekt : checkbox ob Farben aufsteigend/absteigend? Vorgaben grün/rot -> unchecked andere Farben als vorgabe


### Logik-Zusammenfassung: Geglättete Alpha-MAs

Das Konzept kombiniert klassische Moving-Average-Typen mit einer dynamischen **Alpha-Skalierung** und einer optionalen **Vor-/Nachglättung**:

* **Alpha-Skalierter Basis-EMA (`hma_ema`):**
Calculates an adjusted decay factor $\alpha = \frac{\text{AlphaFactor}}{\text{Period} + 1}$. The input source is optionally smoothed first (`smoothing`), then processed recursively via $\alpha$, and finally smoothed a second time.
* **Glättungs-Varianten (DEMA, TEMA, EHMA):**
* **DEMA / TEMA:** Multi-stage cascaded calculation of the base Alpha-EMA ($e_1, e_2, e_3$) to aggressively suppress lag.
* **EHMA (Exponential Hull):** Calculates a $2 \cdot \text{AlphaEMA}(\frac{\text{Period}}{2}) - \text{AlphaEMA}(\text{Period})$ differential and applies a final Alpha-EMA smoothing over $\sqrt{\frac{\text{Period}}{2}}$.


* **Signal-Generierung & Farbumschlag:**
Der finale MA-Wert wird mit seinem Vorwert ($t-1$) verglichen. Steigende Werte kennzeichnen Bullish-Zustände (z. B. grün), fallende Werte Bearish-Zustände (z. B. rot).

---

## 16.05  MA Indikator (8 frei belegbare MA Linien mit)