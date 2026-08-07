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
