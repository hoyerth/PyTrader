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

