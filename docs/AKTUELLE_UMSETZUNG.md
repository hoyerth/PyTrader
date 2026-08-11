# Phase 21: Fachliche Feinabstimmung Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 21)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase21_step1`, `phase21_step1` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Codebase-Formatierung:** Exakt **4 Leerzeichen** Einrückung (PEP8-Standard) und **exakt 1 Leerzeile** Spacing zwischen Methoden und Funktionsblöcken. Kein Umformatieren unbeteiligter Altbestand-Dateien.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`. `MasterTree`-Selektionen übergeben aufgelöste `feature_ids` sowie `instance_hashes` direkt an `view_model.set_feature_ids(ids, hashes)`.
5. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`db/db_pool.py`) – eine Verbindung pro Thread und DB-Datei. Die Fassade `db_service.py` bleibt als Re-Export-Wrapper für bestehende Caller erhalten.
7. **Tree-Persistenz & Kategorisierung:** 
   - Service-Kategorien werden primär im Code/Plugin über `metadata["category"]` (Slash-separierter Ordnerpfad) deklariert.
   - Ordner-Kategorien für Service-Sets werden im `category`-Feld der `ServiceSetDefinition` / des `save_set()`-Payloads persistiert.
   - Parameter-Varianten (Clones/Presets) werden transparent über `indicator_presets` und `instance_hash` im FeatureStore geführt.
8. **Wanduhr-Garantie (Invariante 7):** MT5-Epochs sind bereits Berlin-Wanduhr-encoded. SQL-Extraktionen (Heatmap, DOW, Hour, Date) nutzen strikt `bar_time AT TIME ZONE 'UTC'`, um eine fehlerhafte automatische Umrechnung durch DuckDB in Lokalzeiten zu unterbinden.
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

# 21.01 Analytics – Refactor & Smart Presets

## 🎯 1. Ziel & Fachliche Kern-Anforderungen

1. **Time-Series Confluence Profile (Hauptansicht):**
* Echtes 2D-Heatmap-Farbraster (Option A): X = `date` (kontinuierlich), Y = `service_id`, Z (Farbe) = `confluence_count` (Treffer-Häufigkeit).

2. **Freies Customizing:**
* Anwender kann X-, Y-Achsen und Aggregationen jederzeit frei verstellen, ohne in No-Data-Sackgassen zu laufen.

3. **Smart Presets:**
* Toolbar-Buttons zur 1-Klick-Belegung der Achsen/Aggregationen für typische Fragestellungen.

4. **Profil-Persistenz & Auto-Namensgenerator:**
* Klick auf `[➕ Neues Profil]` generiert automatisch sprechende Namen – **deutsch** (E3, z. B. `SILVER M1 - Confluence Zeitachse (3 Services)`).
* Speichern erfolgt via Explicit Save (Option B, Dirty-Flag `*`).

5. **Ergonomie Header & Layout:**
* Breites, dehnbares Profil-Combo/Eingabefeld.
* Status-Label und Buttons (`[➕ Neu]`, `[💾 Speichern]`, `[🗑️ Löschen]`) streng rechtsbündig.

6. **Mischbetrieb- & Rendering-Fixes:**
* SQL-Filter-Fix für Standalone-Services neben Hash-Varianten.
* TF-Freigabe für Timeframe-Matrizen.
* Werte-gebundene Colormap (Z-Werte 0..N statt Achsen-Koordinaten).

---

## 🚀 2. Die 4 Smart-Presets für die Heatmap

| Preset-Button | X-Achse | Y-Achse | Aggregation / Feld | Zweck |
| --- | --- | --- | --- | --- |
| **`[⚡ Signal-Confluence]`** *(Hauptansicht)* | `date` (Fortlaufend)

 | `service_id`<br> | `confluence_count`<br> | Chronologische Lichtsäulen zeitgleicher Signale

 |
| **`[🕒 Session-Hotspots]`** | `dow` (Mo–Fr)

 | `hour` (00–23h Wanduhr)

 | `confluence_count`<br> | Tageszeit-/Wochentag-Muster im Handelsverlauf

 |
| **`[📏 Wert-Intensität]`** | `date` (Standard) **oder** `dow` (E2)<br> | `hour`<br> | `avg` / `max` + Num-Key

 | Ausprägung von Messwerten (z. B. `distance_pip`, `atr`)

 |
| **`[📊 Service-Timeframe]`** | `timeframe` (Alle TFs)

 | `service_id`<br> | `count`<br> | Verteilung der Services über Zeitebenen

 |

---

## 🛠️ 3. Schritt-für-Schritt Umsetzungsanleitung für die IDE

### Schritt 1: Backend- & SQL-Filter-Fix (`analytics/engine/feature_store_reader.py`)

> **Status: BEREITS UMGESETZT** in Phase 20 (Runde 16/16c, 11.08.2026) – keine neue Arbeit, nur Verifikation im 21.01-Test.

* **1.1 Mischauswahlsicherer SQL-Filter (`_apply_feature_filter`) – erledigt:**
`_apply_feature_filter` nutzt bereits die Disjunktion (Stand Runde 10/16):

# (LOWER(TRIM(feature_id)) IN (ids) AND (instance_hash IS NULL OR LOWER(TRIM(instance_hash)) IN (hashes)))

Der Guard greift nur noch bei Varianten MIT Hash (`if active_hashes and h_s and ...`); hash-lose Standalone-Services passieren die Varianten-Einschränkung immer.

* **1.2 Entkopplung der Standalone-NoData-Prüfung (`resolve_no_data_variants`) – erledigt:**
Der alte Guard `if not active_hashes:` um den Standalone-Block ist entfernt. Runde 16 (11.08.2026): Standalone-Services (`h_s=""`) werden von einer aktiven Hash-Auswahl anderer Services nicht mehr verworfen und erscheinen korrekt als `(No Data)`, solange der feature_store keine Rows ihrer plugin_id besitzt.


### Schritt 2: Colormap-Rendering Fix (`analytics/ui/heatmap_widget.py`)

* **2.1 Werte-gebundene Farb-Lookup-Table (LUT) – Ist-API beachten:**
Das `ImageItem` heißt im Widget **`self._image`** (nicht `self.image_item`) und nutzt **`setColorMap`** (nicht `lut=`) mit den bestehenden `_CONFLUENCE_LEVELS = (0.0, 5.0)`. Colormap streng an die min/max-Spannweite der Daten binden:

# Colormap über den Wertebereich min_val .. max_val legen (Z-Aktivität):
# Z=0 (No Data/0 Hits) -> Transparent/Dunkel
# Z>=1 -> Farbskala (Violett -> Grün -> Rot/Gelb) [Confluence-Modus]
self._image.setColorMap(self._cmap_confluence)
self._image.setImage(matrix, levels=_CONFLUENCE_LEVELS)
self._colorbar.setLevels(_CONFLUENCE_LEVELS)
# Wert-Aggregationen (avg/sum/min/max) -> viridis (kontinuierlich):
self._image.setColorMap(self._cmap_viridis)
self._image.setImage(matrix, levels=(vmin, vmax))


### Schritt 3: ViewModel-Erweiterung & Smart-Presets (`analytics/engine/analytics_view_model.py`)

* **3.1 Preset-Methoden im ViewModel bereitstellen:**
* Implementiere Helfer wie `apply_smart_preset_confluence()`, `apply_smart_preset_session()`, `apply_smart_preset_intensity()`, `apply_smart_preset_timeframe()`.
* **E1 (Entscheidung 11.08.2026):** Bei Presets mit `x_dim="timeframe"` oder `y_dim="timeframe"` wird **NICHT** `timeframe=""` übergeben – das bricht mit der aktuellen API ab (`fetch_generic_heatmap` / `get_generic_heatmap`: Guard `if not symbol or not timeframe:` → leere Matrix). Stattdessen wird ein optionaler Parameter **`all_timeframes: bool = False`** additiv durch Reader → Repository → ViewModel → Worker gereicht; bei `all_timeframes=True` entfällt die WHERE-Bedingung `LOWER(timeframe) = LOWER(?)`, sodass DuckDB alle Zeitebenen (`M1`..`D1`) liest (EINE Query).

* **3.2 Auto-Namensgenerator für neue Profile – E3:**
Erstelle `generate_profile_name_suggestion() -> str` – **Sprache DEUTSCH**:

# Formel: [Symbol] [Timeframe] - [Modus/Metrik] ([Kontext])
# Bsp: "SILVER M1 - Confluence Zeitachse (3 Services)"
# Kontext-Klammer: Anzahl der selektierten Services (feature_ids aus set_feature_ids);
#                  bei 0 Auswahlen -> "(Alle Services)" statt "(0 Services)"
# Fallback fehlendes Symbol/Timeframe: Platzhalter "ALLE"
#                  (z. B. "ALLE M1 - Confluence Zeitachse (3 Services)")


### Schritt 4: UI-Layout & Header-Redesign (`analytics/ui/analytics_win.py` / `heatmap_page.py`)

* **4.1 Ergonomischer Profile-Header (Rechtsbündig) – E5:**
* `combo_profile` auf `setSizePolicy(Expanding, Fixed)`, `setMinimumWidth(350)` und `setEditable(True)` setzen (breites, dehnbares Combo-/Eingabefeld).
* Einen `addStretch(1)` einfügen; `label_dirty` (wird um Text-Botschaften erweitert, **kein neues `label_profile_message`**), `btn_profile_new`, `btn_profile_save`, `btn_profile_delete` rechtsbündig anordnen.
* Die Namens-/Beschreibungs-Edit-Felder wandern aus dem Header in den separaten Speicher-Dialog (E5).

* **4.2 Smart-Preset-Buttons im `HeatmapWidget` (E4/E6):**
* Füge die Quick-Action Buttons DIREKT in die `ctrl`/`ctrl2`-Layout-Zeilen des `HeatmapWidget` ein (Ist-Zustand – es gibt keine `QToolBar`), NICHT in den AnalyticsWindow-Header: `[⚡ Signal-Confluence]`, `[🕒 Session-Hotspots]`, `[📏 Wert-Intensität]`, `[📊 Service-Timeframe]` (Icons 1:1, E6) – verbunden mit den ViewModel-Preset-Methoden.
* **E4:** Preset setzt NUR die Konfiguration (`set_heatmap_config`) + Dirty-Flag `*` (Option B, kein Auto-Save). Der Preset-Klick schaltet die Heatmap-Ansicht automatisch auf `"generic"` (`combo_mode`) – der generische Modus wird damit die **neue Standard-Ansicht** der Heatmap (Default-Auswahl im `combo_mode`).

* **4.3 Dialog für `[➕ Neues Profil]` / `[💾 Speichern]` (E5):**
* Der separate Speicher-Dialog enthält Name- und Beschreibungs-Feld.
* Beim Klick auf Neu wird das Namensfeld mit `generate_profile_name_suggestion()` vorausgefüllt; beim Klick auf Speichern mit dem aktuellen Profilnamen.

---

## 📊 4. Akzeptanzkriterien für die Headless-Validierung (`test/test.py`)

1. **Mischfilter-Test:** Kombinierter Query aus Hash-Variante + Standalone-Service liefert beide Datensätze korrekt zurück.
2. **NoData-Test:** Ein ungeflashtes Plugin erscheint trotz gecheckter Hashes anderer Services im NoData-Ergebnis.
3. **Namensgenerator-Test:** `generate_profile_name_suggestion()` liefert für gegebene Params den exakten Erwartungs-String – **deutsch inkl. Fallbacks (E3)**.
4. **Heatmap-Matrix-Test:** `get_generic_heatmap` mit `x_dim="timeframe"` liefert bei Freigabe alle verfügbaren TFs in den Achsen-Labels.
5. **Preset-Test (E4/E6):** `apply_smart_preset_*` setzt die Heatmap-Config + Dirty-Flag `*` (kein Auto-Save) und meldet den Wechsel in den generischen Modus.
6. **Namensgenerator-Fallbacks (E3):** 0 Auswahlen → `(Alle Services)`; fehlendes Symbol/TF → Platzhalter `ALLE`.
7. **TF-Matrix-Test (E1):** `all_timeframes=True` liefert alle Zeitebenen (`M1`..`D1`) bei `x_dim="timeframe"` in den Achsen-Labels.

---

## 🧭 5. Entscheidungen (User-Entscheidungen, 11.08.2026)

| ID | Entscheidung |
| --- | --- |
| **E1** | TF-Matrix `[📊 Service-Timeframe]`: Neuer optionaler Parameter `all_timeframes: bool = False` durch Reader → Repository → ViewModel → Worker. Bei `all_timeframes=True` entfällt die WHERE-Bedingung `LOWER(timeframe) = LOWER(?)` – EINE Query über alle Zeitebenen. `timeframe=""` als Mechanik ist **verworfen** (bricht mit aktuellem Guard ab). |
| **E2** | Wert-Intensität `[📏 Wert-Intensität]`: X unterstützt `date` **und** `dow` (Wochentag). Preset belegt X standardmäßig mit `date`; `dow` bleibt über die freie X-Achsen-Wahl erreichbar (kein Ausschluss). |
| **E3** | Namensgenerator: Sprache **DEUTSCH** (z. B. `SILVER M1 - Confluence Zeitachse (3 Services)`). Kontext-Klammer = Anzahl selektierter Services; bei 0 Auswahlen `(Alle Services)`. Fehlendes Symbol/TF → Platzhalter `ALLE`. |
| **E4** | Preset-Verhalten: setzt NUR Konfiguration + Dirty-Flag `*` (Option B, kein Auto-Save). Preset-Klick wechselt automatisch in den **generischen Modus** – dieser wird neue Standard-Ansicht der Heatmap. Platzierung der Buttons: direkt in `ctrl`/`ctrl2` des `HeatmapWidget` (keine QToolBar). |
| **E5** | Header: `combo_profile` dehnbar (`Expanding`, min. 350 px, editierbar); Namens-/Beschreibungs-Felder im separaten Speicher-Dialog; `label_dirty` wird um Text-Botschaften erweitert (kein neues Label); `label_dirty` + Buttons rechtsbündig. |
| **E6** | Icons 1:1 übernehmen: `[➕ Neu]`, `[💾 Speichern]`, `[🗑️ Löschen]`, `[⚡ Signal-Confluence]`, `[🕒 Session-Hotspots]`, `[📏 Wert-Intensität]`, `[📊 Service-Timeframe]`. |
| **E7** | User-Anweisung (11.08.2026): Die **4 Preset-Buttons im `HeatmapWidget` werden ENTFERNT** – die Smart-Presets sind ab jetzt ausschließlich über das „Ansicht“-Dropdown der `HeatmapPage` erreichbar (`preset_confluence`/`preset_session`/`preset_intensity`/`preset_timeframe`). Die zugehörigen Handler `_on_preset_*` und die `preset_clicked`-Emit-Aufrufe im Widget entfallen; das Signal selbst darf bleiben (wird aber von der Page nicht mehr konsumiert). |
| **E8** | Screenshot-Analyse (Kritik-Punkt 1, empirisch bestätigt): pyqtgraph `ImageItem` rendert mit Default `axisOrder='col-major'` die `(rows=Services, cols=Zeiten)`-Matrix **transponiert** (Beweis: `width()==2, height()==3` bei einer 2×3-Matrix → Services in X, Zeiten als N dünne Y-Streifen). Fix: `self._image.setOpts(axisOrder='row-major')` im `HeatmapWidget`. |
| **E9** | Kritik-Punkt 2 („X-Achse homogen“): **kein SQL-Fehler** – `DIM_MAPPINGS["date"] = "CAST(bar_time AT TIME ZONE 'UTC' AS DATE)"` (1 Spalte/Tag) ist Design E4. Die Homogenität ist Folge der Transposition E8 (ein Service quer gestreckt). Der Kritik-Vorschlag (volle `bar_time`-Granularität) ist **verworfen** (Pivot-Explosion: zehntausende Spalten bei M1, Pivot-Deckel greift, Achse unlesbar). Eine feinere Zeitauflösung wäre eine separate Design-Entscheidung. |
| **E10** | Kritik-Punkt 3 („Farbe = Y-Position“): **visuelle Täuschung durch E8, kein Code-Bug** – die Farben sind daten-gebunden (Levels `(vmin, vmax)` seit Meldung-7-Fix). Optionale Verbesserung (kein Pflicht-Fix): Confluence-LUT feiner stufen (pro Trefferzahl) für bessere Unterscheidung bei 0..3 Werten. |
| **E11** | Overlay-Rendering NumPy-vektorisiert (User-Freigabe 11.08.2026, „doku alles und setze um“): statt 2 Qt-Items je Bar (bei 5000 Bars = 10.000 Einzel-Items → Pan/Zoom-Ruckeln) nur noch **3 batched `pg.BarGraphItem`** (Wick + Bull-Körper + Bear-Körper) mit numpy-Arrays für alle Bars. `_candle_items = [wick, body_bull, body_bear]` (3 Einträge). |
| **E12** | Senkrechte Teiler je Dateneinheit (Bug 2, Variante a – User-Entscheidung): `pyqtgraph.GridItem` verworfen (in v0.14 nur `setTickSpacing` = feste Skalen); stattdessen `_grid_lines = pg.PlotCurveItem(connect="pairs")` (zValue 5) + neue Methode `_update_grid_lines()` (Bar-Intervall des Heatmap-TFs via `_bar_interval_seconds()`, Dichte-Cap 2000 Linien, `np.arange` ab `floor(lo/bar_sec)*bar_sec`). Aufruf nach `setRect` in `_render_generic`, Leeren bei „Keine Daten“. |
| **E13** | Tages-Marken-Format der X-Achse (X=date): `Mo. 12.06.26` (deutscher Kurz-Wochentag + `TT.MM.JJ`, 1:1 Chart-Konvention); days-Tupel `("Mo.", …, "So.")`, `dt.weekday()` (0 = Mo). |
| **E14** | Zelleninfo am Fadenkreuz (X=date): zusätzliche Zeitzeile `Zeit: Mo. 12.06.26 14:00 · Zelle(row,col) = Wert` – Datum aus der echten Tag-Epoch des Tracks, HH:MM aus dem Sub-Tag-Wert. |

---

## 📝 6. Implementierungs-Log

* **11.08.2026 – Doku-Update 21.01 (Korrektur & Entscheidungen):** Kapitel 21.01 präzisiert – Schritt 1.1/1.2 als bereits in Phase 20 (Runde 16/16c) umgesetzt markiert; Schritt 2.1 auf Ist-API (`self._image` / `setColorMap` / `_CONFLUENCE_LEVELS`) korrigiert; Schritt 3.1 auf E1 (`all_timeframes`), 3.2 auf E3 (deutscher Namensgenerator inkl. Fallbacks), Schritt 4 auf E4–E6 (Platzierung im `HeatmapWidget`, Standard-Ansicht generisch, Speicher-Dialog) korrigiert; Entscheidungen E1–E6 in Sektion 5 dokumentiert; Akzeptanzkriterien 5–7 ergänzt. Reine Doku – **kein Coding**.

* **11.08.2026 – 21.01 Umsetzung (Coding, E1–E6):** Alle 7 Dateien umgesetzt und per `test/test.py` verifiziert (Sektion 39, 31 Checks AK1–AK7/Presets/Namensgenerator/Widget/Page – alle PASS; keine neuen Fehler gegenüber der 25er-Baseline aus Teil 1/25/32/35/36/37/20.03). Änderungen: `feature_store_reader.py` (`fetch_generic_heatmap` + `all_timeframes`, Guard ohne TF-Freigabe), `analytics_repository.py` / `analytics_worker.py` (Parameter-Durchreichung, QUERY ohne `LOWER(timeframe)=` bei `all_timeframes=True`), `analytics_view_model.py` (`heatmap_all_timeframes`, `apply_smart_preset_*`, `generate_profile_name_suggestion()` deutsch inkl. Fallbacks `(Alle Services)`/`ALLE`, Persistenz unter `charts.heatmap.all_timeframes`), `heatmap_widget.py` (Signal `preset_clicked` + 4 Preset-Buttons in `ctrl`), `heatmap_page.py` (generischer Modus als Standard-Ansicht), `analytics_win.py` (Header-Redesign E5: `combo_profile` dehnbar/editierbar, Namens-/Beschreibungs-Felder in separatem Speicher-Dialog, `_resolve_save_name`-Helfer gegen '?'-Verlust, Auto-Name im Neu-Dialog). Test 35 Z2b/Z2c an E5-Kontrakt angepasst (kein Header-Namensfeld mehr; `_resolve_save_name` direkt getestet).

* **11.08.2026 – Bugfix-Runde 21.01 User-Meldungen 1–7 (Coding, Commit `28249a2`):** Meldung 1 (Profil-Neu-Dialog breit, QDialog min. 560 px, `combo_profile` min. 560 px), Meldung 2 (Ansicht-Dropdown = Generisch + 4 Presets, „Wochentag × Stunde“ entfernt, Legacy-`standard`→`generic`-Mapping), Meldung 3 (Bedien-Controls bleiben bei jedem Preset-Wechsel sichtbar, Stack immer Seite 1, `_apply_selected_preset()`), Meldung 4/6 (Stale-Combo-Fix: Preset-Handler synchronisieren Combos via `_sync_from_params()`/`_update_controls()`), Meldung 5 (Kerzen-Overlay nur bei X=date, Restore-Guard `heatmap_x_dim == "date"`), Meldung 7 (Confluence-Levels daten-gebunden `(vmin, vmax)` statt fest `(0, 5)`). Verifikation: `test/check_heatmap_2101.py` (10/10 OK, headless). **Noch nicht vom Anwender als funktionierend bestätigt** – die Screenshot-Kritik (E7–E10) schließt direkt an.
* **11.08.2026 – Heatmap-Darstellung Screenshot-Kritik (Analyse, KEIN Coding):** Anweisung des Anwenders: „Bugfixing – 4 Preset-Buttons entfernen (jetzt im Dropdown) / Kritik prüfen + Fix erstellen / erst Meinung + Doku, dann warten auf Befehl“. Analyse-Ergebnisse: **(1)** Y-Streifen = reale Transposition (`axisOrder='col-major'`, empirisch via `test/check_orientation_2101.py`: `width()==2/height()==3` bei 2×3-Matrix) → Fix E8 `axisOrder='row-major'`. **(2)** Homogene X-Achse = Symptom der Transposition, kein SQL-Fehler (E9). **(3)** „Farbe = Y-Position“ = visuelle Täuschung, Farben daten-gebunden (E10). **Fixes E7 (Buttons entfernen) + E8 (`axisOrder='row-major'`) wurden vom Anwender freigegeben und umgesetzt – Umsetzung + Verifikation siehe nächster Log-Eintrag.**
* **11.08.2026 – E7/E8 Umsetzung (Coding):** Anweisung „continue“ nach Freigabe. **E7:** Die 4 Preset-Buttons im `HeatmapWidget` (`_btn_preset_confluence/session/intensity/timeframe`) samt Handlern `_on_preset_*` und Signal-Verbindungen ENTFERNT – die Smart-Presets laufen ausschließlich über das „Ansicht“-Dropdown der `HeatmapPage` (`_apply_selected_preset`). Das Signal `preset_clicked` bleibt als Vertrag, wird aber nicht mehr emittiert; die Page konsumiert es nicht mehr (`attach_view_model`-Verbindung + `_on_preset_clicked` entfernt). **E8:** `self._image.setOpts(axisOrder='row-major')` – behebt die Transposition der `(rows=Services, cols=Zeiten)`-Matrix (pyqtgraph-Default `col-major` rendert transponiert → die N dünnen Y-Streifen der Kritik). Verifikation (headless, venv): `test/check_heatmap_2101.py` 12/12 OK (inkl. neuer E7/E8-Checks), `test/check_orientation_2101.py` `width()==3/height()==2` statt vorher `2/3`, `py_compile` aller geänderten Dateien OK, `test/test.py` Sektion 39 (j1/j2 E7/E8, k1 Page konsumiert Signal nicht mehr) angepasst. Offener Verifikationspunkt geklärt: kategoriale Y-Achsen-Ticks (Services) liegen nach row-major exakt auf den Zeilen-Mitten (0,1,2 ↔ Zellen [-0.5..2.5]). **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „doku“, 11.08.2026).
* **11.08.2026 – Bugfix-Runde 2 Heatmap-Darstellung (Coding, 5 Bugs, nur `analytics/ui/heatmap_widget.py`, +231/−57):** (1) Kategoriales Achsen-Clamping – Ticks außerhalb `0..n−1` entfallen (`_clamped_scale_bounds`, `_format` → leere Strings). (2) Schwellwert-Legende (`pg.LegendItem` oben rechts) + `0`-Confluence-Farbe Grau `#d9d9d9`. (3) Fadenkreuz (`_cross_x`/`_cross_y` als `pg.InfiniteLine`, zValue 20) + `_on_mouse_moved` + `_update_cell_info`. (4) Datumsformate 1:1 JS-Konvention (`TT.MM.JJ` / `HH:MM`). (5) Adaptives Overlay: `QUERY_OHLCV` statt Daily-Query, `_TF_SECONDS`-Map, `_bar_interval_seconds()`. Verifikation: `test/check_heatmap_2101.py` 20/20 + Smoke-Test 7/7 (headless, venv). **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „doku“, 11.08.2026).
* **11.08.2026 – Bugfix-Runde 3 Heatmap-Darstellung (Coding, 4 Punkte, User „doku alles und setze deine Vorschläge um“):** E11 (Overlay batched: 3 `pg.BarGraphItem`, numpy), E12 (senkrechte Teiler je Dateneinheit, Variante a: `_grid_lines` als `PlotCurveItem(connect="pairs")` + `_update_grid_lines()`), E13 (Tages-Marken `Mo. 12.06.26`), E14 (Zelleninfo-Zeitzeile `Zeit: Mo. 12.06.26 14:00 · Zelle(row,col) = Wert`). Nachgereicht: `bar_sec = self._bar_interval_seconds()` im batched-Overlay-Block (der Runde-2-Patch hatte die Zeile zusammen mit dem alten Loop ersetzt). Verifikation: `test/check_heatmap_2101.py` 22/22 OK (headless, venv), `py_compile` von `heatmap_widget.py` + `test.py` OK. **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „doku“, 11.08.2026).


