# Phase 21: Fachliche Feinabstimmung Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 21)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase10_step1`, `phase21_step1` usw.).
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
| **E15** | Fadenkreuz-Zelleninfo (X=date, b1→a): Datum = Tag der Zelle unter dem Fadenkreuz (`self._x_axis[col]`, E14-konform „echte Tag-Epoch des Tracks"), Zeit = exakte Cursor-HH:MM aus der Roh-Epoch (Wanduhr-UTC, Invariante 7). Behebt den off-by-one-day-Bug (Zellen sind mittags-zentriert `[Tag−12 h, Tag+12 h)` → Cursor 12:00–24:00 zeigte den Wert der Folgetag-Zelle). Zusätzlich: Label wird auch außerhalb des Datenbereichs aktualisiert (leeres Zeit-Segment statt stehengebliebenem Alt-Label). |
| **E16** | Mehrzeilige Achsen-Beschriftung (b2): Kategoriale Labels (service_id/timeframe/symbol) werden in `_HeatmapAxis._format` an JEDEM `/` umgebrochen (`\n` je Segment) – das letzte Segment (Service-Name) bleibt am besten lesbar („größte Aussagekraft“). KEINE Zeilenzahl-Kappung (beliebig viele Segmente). Gilt für X- und Y-Achse (User-Kontext: Y). pyqtgraph 0.14 vermisst/rendert `\n`-Tick-Labels korrekt (headless verifiziert). |
| **E17** | Service-Run Refresh-/Fehlerverhalten (b3 = AI-Empfehlungen): (a) `event_bus.service_set_changed` wird AUCH bei `run_failed`/Teilerfolg emittiert (mindestens wenn Feature-Rows geschrieben wurden) → Baum-Datum aktualisiert sich auch auf neuen TFs zuverlässig. (b) Einzel-Service-Fehler im Set-Run (0 Records trotz Daten / Exception) werden geloggt und die übrigen Services laufen WEITER (analog Multi-TF-Pfad) statt Gesamt-Abbruch – insbesondere auf neuen TFs. |
| **E18** | TF-Umfang & Einbettung (b4): (b) Pill-Strip zeigt ALLE TFs mit feature_store-Daten (nicht nur die 6 Spez-TFs M1..D1), sortiert aufsteigend nach Dauer (`TF_SECONDS_MAP`). (c) „Alle Timeframes“-Run nutzt ALLE TFs, die als Kerzen verfügbar sind (OHLCV-Daten des aktiven Symbols in market_data). (d) Einbettung an BEIDEN Orten: ServiceWindow (`combo_tf` existiert bereits, U15-E) UND ServicePicker/`ServiceSelectorDialog` (+ Datenquellen-Combo des AnalyticsWindow). |

---

## 📝 6. Implementierungs-Log

* **11.08.2026 – Doku-Update 21.01 (Korrektur & Entscheidungen):** Kapitel 21.01 präzisiert – Schritt 1.1/1.2 als bereits in Phase 20 (Runde 16/16c) umgesetzt markiert; Schritt 2.1 auf Ist-API (`self._image` / `setColorMap` / `_CONFLUENCE_LEVELS`) korrigiert; Schritt 3.1 auf E1 (`all_timeframes`), 3.2 auf E3 (deutscher Namensgenerator inkl. Fallbacks), Schritt 4 auf E4–E6 (Platzierung im `HeatmapWidget`, Standard-Ansicht generisch, Speicher-Dialog) korrigiert; Entscheidungen E1–E6 in Sektion 5 dokumentiert; Akzeptanzkriterien 5–7 ergänzt. Reine Doku – **kein Coding**.

* **11.08.2026 – 21.01 Umsetzung (Coding, E1–E6):** Alle 7 Dateien umgesetzt und per `test/test.py` verifiziert (Sektion 39, 31 Checks AK1–AK7/Presets/Namensgenerator/Widget/Page – alle PASS; keine neuen Fehler gegenüber der 25er-Baseline aus Teil 1/25/32/35/36/37/20.03). Änderungen: `feature_store_reader.py` (`fetch_generic_heatmap` + `all_timeframes`, Guard ohne TF-Freigabe), `analytics_repository.py` / `analytics_worker.py` (Parameter-Durchreichung, QUERY ohne `LOWER(timeframe)=` bei `all_timeframes=True`), `analytics_view_model.py` (`heatmap_all_timeframes`, `apply_smart_preset_*`, `generate_profile_name_suggestion()` deutsch inkl. Fallbacks `(Alle Services)`/`ALLE`, Persistenz unter `charts.heatmap.all_timeframes`), `heatmap_widget.py` (Signal `preset_clicked` + 4 Preset-Buttons in `ctrl`), `heatmap_page.py` (generischer Modus als Standard-Ansicht), `analytics_win.py` (Header-Redesign E5: `combo_profile` dehnbar/editierbar, Namens-/Beschreibungs-Felder in separatem Speicher-Dialog, `_resolve_save_name`-Helfer gegen '?'-Verlust, Auto-Name im Neu-Dialog). Test 35 Z2b/Z2c an E5-Kontrakt angepasst (kein Header-Namensfeld mehr; `_resolve_save_name` direkt getestet).

* **11.08.2026 – Bugfix-Runde 21.01 User-Meldungen 1–7 (Coding, Commit `28249a2`):** Meldung 1 (Profil-Neu-Dialog breit, QDialog min. 560 px, `combo_profile` min. 560 px), Meldung 2 (Ansicht-Dropdown = Generisch + 4 Presets, „Wochentag × Stunde“ entfernt, Legacy-`standard`→`generic`-Mapping), Meldung 3 (Bedien-Controls bleiben bei jedem Preset-Wechsel sichtbar, Stack immer Seite 1, `_apply_selected_preset()`), Meldung 4/6 (Stale-Combo-Fix: Preset-Handler synchronisieren Combos via `_sync_from_params()`/`_update_controls()`), Meldung 5 (Kerzen-Overlay nur bei X=date, Restore-Guard `heatmap_x_dim == "date"`), Meldung 7 (Confluence-Levels daten-gebunden `(vmin, vmax)` statt fest `(0, 5)`). Verifikation: `test/check_heatmap_2101.py` (10/10 OK, headless). **Noch nicht vom Anwender als funktionierend bestätigt** – die Screenshot-Kritik (E7–E10) schließt direkt an.
* **11.08.2026 – Heatmap-Darstellung Screenshot-Kritik (Analyse, KEIN Coding):** Anweisung des Anwenders: „Bugfixing – 4 Preset-Buttons entfernen (jetzt im Dropdown) / Kritik prüfen + Fix erstellen / erst Meinung + Doku, dann warten auf Befehl“. Analyse-Ergebnisse: **(1)** Y-Streifen = reale Transposition (`axisOrder='col-major'`, empirisch via `test/check_orientation_2101.py`: `width()==2/height()==3` bei 2×3-Matrix) → Fix E8 `axisOrder='row-major'`. **(2)** Homogene X-Achse = Symptom der Transposition, kein SQL-Fehler (E9). **(3)** „Farbe = Y-Position“ = visuelle Täuschung, Farben daten-gebunden (E10). **Fixes E7 (Buttons entfernen) + E8 (`axisOrder='row-major'`) wurden vom Anwender freigegeben und umgesetzt – Umsetzung + Verifikation siehe nächster Log-Eintrag.**
* **11.08.2026 – E7/E8 Umsetzung (Coding):** Anweisung „continue“ nach Freigabe. **E7:** Die 4 Preset-Buttons im `HeatmapWidget` (`_btn_preset_confluence/session/intensity/timeframe`) samt Handlern `_on_preset_*` und Signal-Verbindungen ENTFERNT – die Smart-Presets laufen ausschließlich über das „Ansicht“-Dropdown der `HeatmapPage` (`_apply_selected_preset`). Das Signal `preset_clicked` bleibt als Vertrag, wird aber nicht mehr emittiert; die Page konsumiert es nicht mehr (`attach_view_model`-Verbindung + `_on_preset_clicked` entfernt). **E8:** `self._image.setOpts(axisOrder='row-major')` – behebt die Transposition der `(rows=Services, cols=Zeiten)`-Matrix (pyqtgraph-Default `col-major` rendert transponiert → die N dünnen Y-Streifen der Kritik). Verifikation (headless, venv): `test/check_heatmap_2101.py` 12/12 OK (inkl. neuer E7/E8-Checks), `test/check_orientation_2101.py` `width()==3/height()==2` statt vorher `2/3`, `py_compile` aller geänderten Dateien OK, `test/test.py` Sektion 39 (j1/j2 E7/E8, k1 Page konsumiert Signal nicht mehr) angepasst. Offener Verifikationspunkt geklärt: kategoriale Y-Achsen-Ticks (Services) liegen nach row-major exakt auf den Zeilen-Mitten (0,1,2 ↔ Zellen [-0.5..2.5]). **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „doku“, 11.08.2026).
* **11.08.2026 – Bugfix-Runde 2 Heatmap-Darstellung (Coding, 5 Bugs, nur `analytics/ui/heatmap_widget.py`, +231/−57):** (1) Kategoriales Achsen-Clamping – Ticks außerhalb `0..n−1` entfallen (`_clamped_scale_bounds`, `_format` → leere Strings). (2) Schwellwert-Legende (`pg.LegendItem` oben rechts) + `0`-Confluence-Farbe Grau `#d9d9d9`. (3) Fadenkreuz (`_cross_x`/`_cross_y` als `pg.InfiniteLine`, zValue 20) + `_on_mouse_moved` + `_update_cell_info`. (4) Datumsformate 1:1 JS-Konvention (`TT.MM.JJ` / `HH:MM`). (5) Adaptives Overlay: `QUERY_OHLCV` statt Daily-Query, `_TF_SECONDS`-Map, `_bar_interval_seconds()`. Verifikation: `test/check_heatmap_2101.py` 20/20 + Smoke-Test 7/7 (headless, venv). **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „doku“, 11.08.2026).
* **11.08.2026 – Bugfix-Runde 3 Heatmap-Darstellung (Coding, 4 Punkte, User „doku alles und setze deine Vorschläge um“):** E11 (Overlay batched: 3 `pg.BarGraphItem`, numpy), E12 (senkrechte Teiler je Dateneinheit, Variante a: `_grid_lines` als `PlotCurveItem(connect="pairs")` + `_update_grid_lines()`), E13 (Tages-Marken `Mo. 12.06.26`), E14 (Zelleninfo-Zeitzeile `Zeit: Mo. 12.06.26 14:00 · Zelle(row,col) = Wert`). Nachgereicht: `bar_sec = self._bar_interval_seconds()` im batched-Overlay-Block (der Runde-2-Patch hatte die Zeile zusammen mit dem alten Loop ersetzt). Verifikation: `test/check_heatmap_2101.py` 22/22 OK (headless, venv), `py_compile` von `heatmap_widget.py` + `test.py` OK. **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „doku“, 11.08.2026).

* **11.08.2026 – Bugfix-/Spez-Analyse 21.01 + 21.01b (Analyse, KEIN Coding, Anweisung „bugfix mode – prüfe, Ergebnisse als Textblock, kein Coding“):** Vier User-Meldungen geprüft und headless verifiziert (Wegwerf-DB in `test/`, danach wieder entfernt): **(1) Fadenkreuz-Zelleninfo** funktioniert mechanisch (row/col-Mapping ohne Flip, Wanduhr-Konvertierung), hat aber einen echten off-by-one-day-Bug: Tageszellen sind mittags-zentriert (`_axis_bounds`: `lo−12 h … hi+12 h`) → Cursor 12:00–24:00 zeigt den Wert der Folgetag-Zelle; außerhalb des Datenbereichs bleibt das alte Label stehen. **(2) Mehrzeilen-Umbruch** am `/` ist machbar – pyqtgraph 0.14 misst/rendert `\n`-Tick-Labels korrekt. **(3) „Datum im Baum bleibt stehen“ auf neuem TF:** DB-Schicht korrekt (PK `(symbol, timeframe, bar_time, feature_id)` trennt TFs; `fetch_last_execution_dates` liefert sofort das neue Datum) – Root Cause in `run_worker.py`: `event_bus.service_set_changed` wird NUR bei vollem Erfolg emittiert; alle Fehlerpfade (`no_data_tfs`, `no_payload_tfs`, Exception im Single-TF-Zweig) überspringen den Refresh, obwohl Rows geschrieben wurden. **(4) Service-Picker** hat keinen TF-Selektor (nur `ServiceWindow.combo_tf`, U15-E); Heatmap-Preset „Service-Timeframe“ sortiert die TFs alphabetisch statt nach Dauer. Spez-Bausteine `fetch_service_tf_status`, `TfStatusBadgeBar`, `serviceui/common_widgets.py`, per-TF-Worker-Signale existieren nicht. Entscheidungen E15–E18 (§5) dokumentiert – **Umsetzung erst nach explizitem Befehl**.

# 21.01b Analytics – Multi-TF Execution & Status Pill-Strip

## 🎯 1. Ziel & UX-Anforderungen

1. **Multi-TF Execution im Service Picker / Window:**
* Dropdown/Action-Button in der Filterleiste: `[ Aktueller TF (H1) ]` vs. `[ 🌐 Alle Timeframes ]`.
* Klick stößt die Batch-Berechnung im `ServiceRunWorker` schrittweise über alle TFs an (bestehende `ALL_TIMEFRAMES`-Mechanik, U15-E).
* **E18c:** „Alle Timeframes“ = ALLE TFs, die als Kerzen verfügbar sind (OHLCV-Daten des aktiven Symbols in market_data).

2. **Kompaktes Status-Widget (`TfStatusBadgeBar` / Pill-Strip):**
* Bemaßung: ca. 170 × 16 px (extrem platzsparend).
* Feste Platzierung: Parameter/Status-Spalte des `ServiceWindow` / `MasterTree` sowie neben der Datenquellen-Combo des `AnalyticsWindow` – **E18d: BEIDE Orte** (ServiceWindow UND ServicePicker).
* Badges: ein Label je TF – Umfang = **E18b: ALLE TFs mit feature_store-Daten**, sortiert aufsteigend nach Dauer (`TF_SECONDS_MAP`, deckungsgleich mit `_refresh_timeframe_combo` des ServiceWindow).

3. **Farb-Codierung:**
* Dunkelgrau (⚪): Noch nie berechnet (0 Rows).
* Grün (✅): Berechnet & aktuell (>0 Rows im `feature_store`).
* Rot (❌): Fehler / Abbruch.
* Blau blinkend (🔄): Berechnet gerade im Hintergrund (per-TF-Signal des Workers, Schritt 3.2).

4. **Detail-Tooltip (Mouse-Over):**
* Hover über ein Badge zeigt exakte Zeilenzahl & Zeitstempel der letzten Ausführung (`DD.MM.JJ HH:MM`).

---

## 🛠️ 2. Schritt-für-Schritt Umsetzungsanleitung für die IDE

### Schritt 1: DB-Status-Methode (`analytics/engine/feature_store_reader.py`)

* **1.1 Aggregierten Status abfragen (`fetch_service_tf_status`):** Liefere in EINER leichten SQL-Abfrage Zeilenzahl und `created_at` aller TFs für ein `plugin_id`:

```python
def fetch_service_tf_status(self, plugin_id: str) -> Dict[str, Dict[str, Any]]:
    con = self._get_connection()
    try:
        rows = con.execute("""
            SELECT LOWER(timeframe), COUNT(*), MAX(created_at)
            FROM feature_store
            WHERE LOWER(TRIM(feature_id)) = LOWER(TRIM(?))
            GROUP BY LOWER(timeframe)
        """, [plugin_id]).fetchall()
        return {r[0].upper(): {"count": r[1], "last_run": r[2].strftime("%d.%m.%y %H:%M") if r[2] else ""} for r in rows}
    except Exception:
        return {}
```

* **1.2 Verfügbare TFs (E18b/E18c):** Pill-Strip-Umfang (TFs mit feature_store-Daten) und Run-Umfang (TFs mit OHLCV-Kerzen) werden über die bestehenden Reader-/DbPool-Lesepfade ermittelt (kein neuer Schreibpfad).

### Schritt 2: Mini-Pill-Strip Widget (`serviceui/common_widgets.py` – NEUE Datei)

* **2.1 `TfStatusBadgeBar`-Klasse erstellen:**
* `QWidget` mit `QHBoxLayout` (Spacing 2, Margins 0).
* Ein `QLabel` je TF (feste Größe ~28 × 16 px, Font 9 pt bold, `border-radius: 3px`).
* `update_status(tf_status_map: Dict[str, Dict[str, Any]])`: färbt Badges grün/grau (E18b: dynamische TF-Liste aus dem Status-Map, sortiert nach `TF_SECONDS_MAP`) und setzt den `setToolTip()` (z. B. `M1: 10.000 Einträge\nZuletzt: 11.08.26 20:15`).
* `set_running(tf)`/`set_error(tf)`: Blau-Blinken (QTimer) bzw. Rot (Schritt 3.2).

### Schritt 3: Multi-TF-Ausführung Toolbar (`serviceui/service_win.py` / `service_selector_dialog.py`)

* **3.1 ComboBox `combo_run_tf`:** `[ Aktueller TF ]` + `[ 🌐 Alle Timeframes ]`. Im `ServiceWindow` ist das bestehende `combo_tf` (U15-E, Index 0 = `ALL_TIMEFRAMES`) die Grundlage; der `ServiceSelectorDialog` erhält zusätzlich eine TF-Zeile (E18d).
* **3.2 Per-TF-Fortschrittssignale im `ServiceRunWorker`:** neue Signale `tf_started(str)` / `tf_finished(str, int, bool)` – der Orchestrator setzt das jeweilige Badge auf „berechnet gerade“ (blau blinkend) bzw. grün (Rows geschrieben) / rot (Fehler).

### Schritt 4: UI-Integration & Event-Update

* **4.1 Einbettung:** `TfStatusBadgeBar` als Spalten-Widget in `MasterTree`/`ServiceWindow` sowie in den `ServiceSelectorDialog` (E18d).
* **4.2 Signal-Kopplung:** Badges nach jedem `run_finished`/`run_failed` aktualisieren. **Voraussetzung ist E17** (EventBus-Refresh auch bei Teilerfolg/Fehler), damit der Status nach jedem Run korrekt neu gelesen wird.

---

## 📊 3. Akzeptanzkriterien für die Headless-Validierung (`test/test.py`)

1. **DB-Status-Query-Test:** `fetch_service_tf_status("srv_proximity")` liefert korrektes Dict für alle TFs mit `count` und `last_run`.
2. **Badge-Mapping-Test:** `TfStatusBadgeBar.update_status()` setzt für vorhandene TFs korrekte Tooltip-Texte und Stylesheet-Farben.
3. **Multi-TF-Loop-Test:** Bei Auswahl „Alle Timeframes“ startet der Run-Worker alle als Kerzen verfügbaren TFs nacheinander (E18c).
4. **EventBus-Teilerfolg-Test (E17):** Nach einem Run mit ≥1 geschriebener Feature-Row wird `service_set_changed` auch bei späterem Fehler eines Einzel-Services emittiert (Baum-Datum aktualisiert sich).

---

## 📝 4. Implementierungs-Log

* **11.08.2026 – Doku-Update 21.01b (Entscheidungen & Aktualisierungen):** Neues Kapitel für Multi-TF-Execution & Status-Pill-Strip angelegt (ultrakompakte Spezifikation des Anwenders). User-Entscheidungen b1–b4 in 21.01 §5 (E15–E18) dokumentiert; Umsetzungsanleitung (Schritt 1–4) und Akzeptanzkriterien (4 Checks) auf den entschiedenen Stand aktualisiert: E15 (Fadenkreuz: Datum = Zell-Tag, Zeit = exakte Cursor-HH:MM), E16 (Umbruch an jedem `/` ohne Kappung), E17 (EventBus-Refresh auch bei Teilerfolg/Fehler + Einzel-Service-Fehler loggen statt Gesamt-Abbruch), E18 (Pill-Strip = alle TFs mit Daten, Run = alle als Kerzen verfügbaren TFs, Einbettung in ServiceWindow UND ServicePicker). Reine Doku – **kein Coding**; Umsetzung erst nach explizitem Befehl.
* **11.08.2026 – UMSETZUNG 21.01b + E15–E18 (Anweisung „umsetzung aller schritte“):**
  * **E17 (run_worker.py):** EventBus-Sync `service_set_changed` wird jetzt über `_emit_service_changed()` AUCH auf Fehler-/Teilerfolgspfaden emittiert (vor den `run_failed`-Returns im Single-TF-Zweig, nach der Teil-Ausführung und im äußeren `except`). Einzel-Service-Fehler im Set-Run laufen resilient weiter (`execute_set_resilient` statt Fail-Fast-`execute_set`, Fallback für fremde Evaluator-Instanzen) – `last_errors`/`last_skipped` werden geloggt. Neue per-TF-Signale `tf_started(str)`/`tf_finished(str, int, bool)` werden je Timeframe emittiert. `_resolve_timeframes()` sortiert die Multi-TF-Liste jetzt stabil AUFSTEIGEND nach Dauer (M1..MN1, E18c, konsistent zu Combo/Pill-Strip).
  * **E15 (heatmap_widget.py, `_update_cell_info`):** Datum = Tag der Zelle unter dem Fadenkreuz (`self._x_axis[col]`, Mitternacht der Wanduhr) statt nackter Cursor-Roh-Epoch → behebt den off-by-one-day-Bug (Zellen mittags-zentriert). Zeit = exakte Cursor-HH:MM aus der Roh-Epoch (Wanduhr-UTC, KEIN Berlin-Offset). Label wird IMMER aktualisiert – außerhalb des Datenbereichs „Zelle ausserhalb des Datenbereichs“, bei ungültigem Wert „n/a“.
  * **E16 (heatmap_widget.py, `_HeatmapAxis._format`):** Kategoriale Labels (service_id/timeframe/symbol) werden an JEDEM `/` mit `
` umgebrochen (keine Kappung), gilt für X- und Y-Achse.
  * **21.01b Schritt 1 (`feature_store_reader.py`):** Neue Methode `fetch_service_tf_status(plugin_id)` – SQL `SELECT LOWER(TRIM(timeframe)), COUNT(*), MAX(created_at) … GROUP BY LOWER(TRIM(timeframe))`, case-insensitiv/whitespace-tolerant, Rückgabe `Dict TF(upper) -> {'count': int, 'last_run': 'DD.MM.JJ HH:MM'}`.
  * **21.01b Schritt 2 (NEUE Datei `serviceui/common_widgets.py`):** Widget `TfStatusBadgeBar` (QHBoxLayout, Spacing 2, QLabel je TF 28×16 px, 9 pt bold, Radius 3 px; `update_status(map)`, `set_running(tf|None)`, `set_error(tf)`, `clear_error`, `clear`; Tooltip `M1: 99.063 Eintraege\nZuletzt: 11.08.26 20:15`; Farben: idle/running/error/hint).
  * **21.01b Schritt 3+4 (Einbettung + Kopplung):**
    * `service_win.py`: `TfStatusBadgeBar` am Kopf der Parameter-/Status-Spalte; Worker-Signale `tf_started`/`tf_finished` gekoppelt (`_on_tf_started`/`_on_tf_finished`), nach `run_finished`/`run_failed` Refresh via `_refresh_badge_bar()`; `_on_master_selection_details` lädt die Pills für die geklickte Zeile (`_resolve_badge_plugin`). Run nutzt weiterhin das bestehende `combo_tf` (Index 0 = `ALL_TIMEFRAMES`).
    * `service_selector_dialog.py`: NEUE TF-Zeile `combo_run_tf` (Sentinel `ALL_TIMEFRAMES` + TFs aufsteigend) + `TfStatusBadgeBar` im Parameter-Panel; MasterTree-Run-Aktionen (`run_service/set/plugin/category_requested`) verdrahtet (User-Entscheid: Run im Picker voll funktional) – Bestätigungsdialog, `_plugin_config` (17.01.04-Muster), `ServiceRunWorker` mit `_run_symbol()` (Parent `combo_symbol`) und `_run_timeframe()`; Pill-Strip-Kopplung identisch zum ServiceWindow.
    * `analytics_win.py`: `TfStatusBadgeBar` NEBEN der Datenquellen-Combo (Filter-Zeile); `_refresh_badge_bar()` zeigt die TFs der ERSTEN aktiven Datenquelle (`feature_ids[0]`), Sync über `_sync_service_filter_button`.
  * **Verifikation (headless, KEIN UI-/Regressionstest):** `py_compile` auf allen 7 geänderten Dateien (OK); `test/check_2101b.py` 18/18 PASS (DB-Status-Query, Badge-Mapping inkl. Tooltip/running/error/laufender TF ohne DB-Eintrag, Multi-TF-Loop sortiert nach `TF_SECONDS_MAP`, Sentinel, Worker-Signale, E17-Code-Inspection, Modul-Import-Smoke).
* **11.08.2026 – Bugfix Varianten-Kollision Runde 4 + 5 (Coding, Commits `6910b46` + `3d67539`):** User-Meldung „Kontextmenü auf eine Variante → wird bei allen Varianten ausgeführt/angezeigt" + „Data only löschen muss das letzte Ausführungsdatum im Baum wieder auf null reseten (wie frisch angelegt)".
  * **Runde 4 (`6910b46`, Root Cause: Hash-Kollision):** `generate_instance_hash(plugin_id, params, preset_name)` – Preset-Hashes jetzt INKL. `preset_name` (Backward-Compat ohne). Presets mit identischen Params aber unterschiedlichen Namen (z. B. `srv_trend_breakout`: `ffffffff`/`ggsegerttt`, vorher beide `3399e1bc`; `srv_trend_hma_pivot`: 3× `2d9f343a`) erhalten UNTERSCHIEDLICHE Hashes → der Kontextmenü-Run-Filter matcht GENAU EINE Variante. feature_store-PK idempotent migriert auf `(symbol, timeframe, bar_time, feature_id, instance_hash)` (Table-Rewrite + `ALTER ADD PRIMARY KEY`, `COALESCE(NULL→'')`, auf `data/analytics.duckdb` ausgeführt, 2,33 Mio. Rows erhalten); Writer nutzen adaptiven `_feature_store_conflict_target(con)` (5-/4-Spalten je PK); Reader `_apply_feature_filter`: `instance_hash=''` bleibt bei Varianten-Filtern immer enthalten. MasterTree-Label-Kosmetik (`srv_`-Präfix abgeschnitten, Fallback `(nie)`).
  * **Runde 5 (`3d67539`, die zwei verbliebenen User-Punkte):**
    * **Bug 1 („bei allen Varianten ANGEZEIGT"):** Der Run-Filter matchte seit Runde 4 korrekt genau 1 Variante – der Anzeige-Leak war der **Legacy-Fallback im `ServiceSelectorModel`** (`per_hash.get(new) or per_hash.get(legacy)`): Alt-Rows unter dem kollidierenden Params-only-Hash (Pool) wurden an ALLEN Varianten als Ausführungsdatum angezeigt. Fix: Fallback + `_preset_hash_aliases` VOLLSTÄNDIG entfernt – `_load_plugin_presets`, `last_execution_date_for_hash`, `last_execution_datetime_for_hash` lesen NUR den EIGENEN Preset-Hash; nie gelaufene Varianten zeigen `--.--.--` („nie" wie frisch angelegt).
    * **Bug 2 („Data only löschen resetet das Datum nicht"):** `purge_instance_data(instance_hash)` löschte nur Rows unter dem NEUEN Hash; die Alt-Daten (z. B. 676 689 Rows von `srv_swing_volume_profile` unter dem Legacy-Hash) blieben liegen und das Datum blieb über den Fallback stehen. Fix: Signatur erweitert auf `purge_instance_data(instance_hash, plugin_id="", params=None)` – löscht zusätzlich die LEGACY-Pool-Rows der Variante (`feature_id = plugin_id AND instance_hash = generate_instance_hash(plugin_id, params)`); alle 6 Call-Sites erweitert (`service_win.py`: `_on_data_only_purge`/`_delete_complete_set_instance`/`_delete_complete_preset`; `service_selector_dialog.py`: `_on_data_only_purge`/`_on_delete_complete` ×2 – jeweils mit params-Lookup via Set-Config bzw. `_find_preset_for_hash`).
  * **Verifikation (headless, KEIN UI-/Regressionstest):** `py_compile` aller 4 geänderten Module; `test/check_variant_hash_fix.py` 18/18 (inkl. neuer Checks 3b „kein Legacy-Fallback" deterministisch via Fake-Reader, 3c/3d „Legacy-Purge mit/ohne params"), `test/check_variant_run.py` 11/11 (Test 5 self-contained: Store-Write mit Preset-Hash → Datum nur für DIESEN Hash), `test/check_2004_purge.py` 8/8 (Schema auf 5-Spalten-PK/`''`-Sentinel aktualisiert), `test/check_2101b.py` 18/18. Live-Check: alle Varianten zeigen „nie" trotz 676k Legacy-Rows im Store. **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „continue", 11.08.2026).


---
# 21.02 – DB Bloat Analysis & Maintenance (VACUUM)

## 🎯 1. Kern-Anforderungen

1. **Bloat-Analyse:** Startup-Anzeige auf `MainWindow` unter Optionen-Button via `PRAGMA database_size`.
2. **DB-Pflege beim App-Exit:** `main.py` `closeEvent` führt für jede DB-Datei `CHECKPOINT;` **gefolgt von** `VACUUM;` aus (WAL-Flush, konsistenter Zustand – keine Datei-Verkleinerung).
3. **Kompaktierung (Button):** Button `[ 🧹 DB Service ]` in `PropertiesWindow` führt die **`COPY FROM DATABASE`-Kompaktierung** aus (echte Verkleinerung, Bloat entfernen). **Nicht** `VACUUM`-Button.
4. **Concurrency-Guard:** Kompaktierung sperren, solange `_sync_pause_count > 0` (laufende Scans/Worker) – Zugriff über **EventBus-Zähler** (konsistent zu Phase 16, nicht `self.parent()`).

---

## 🛠️ 2. Schritt-für-Schritt Umsetzungsanleitung

### Schritt 1: Core Engine (`db/db_utils.py`)

Füge folgende Funktionen in `db/db_utils.py` ein (**korrigierte Fassung, Stand 12.08.2026** – F1: `res[2]/res[4]`, F2: CHECKPOINT+VACUUM, `copy_database`-Helper):

# db/db_utils.py
import os
from pathlib import Path
from db.db_pool import DbPool

def get_db_fragmentation_info(db_path: str) -> dict:
    if not os.path.exists(db_path):
        return {"pct": 0, "bloat_mb": 0, "size_mb": 0}
    file_bytes = os.path.getsize(db_path)
    try:
        con = DbPool.get(db_path)
        res = con.execute("PRAGMA database_size;").fetchone()
        # Spalten: 0 database_name, 1 database_size, 2 block_size,
        #          3 total_blocks, 4 used_blocks, 5 free_blocks, ...
        block_size, used_blocks = (res[2], res[4]) if res else (262144, 0)
        netto_bytes = used_blocks * block_size
        bloat_bytes = max(0, file_bytes - netto_bytes)
        return {
            "pct": round((bloat_bytes / file_bytes * 100), 1) if file_bytes else 0,
            "bloat_mb": round(bloat_bytes / (1024 * 1024), 1),
            "size_mb": round(file_bytes / (1024 * 1024), 1)
        }
    except Exception:
        return {"pct": 0, "bloat_mb": 0, "size_mb": round(file_bytes / (1024 * 1024), 1)}

def execute_db_vacuum(db_path: str) -> None:
    """DB-Pflege beim App-Exit (Stufe 1): CHECKPOINT gefolgt von VACUUM.

    CHECKPOINT flusht die WAL in die Hauptdatei (konsistenter Zustand);
    VACUUM ist in DuckDB ohne Dateigrößen-Effekt (Kompaktierung siehe
    copy_database).
    """
    con = DbPool.get(db_path)
    con.execute("CHECKPOINT;")
    con.execute("VACUUM;")

def copy_database(src_db_path: str, dst_db_path: str) -> None:
    """Kompaktierung (Stufe 2): COPY FROM DATABASE in frische, minimale Datei.

    Katalogname der Quelle = Datei-Basename ohne .duckdb (ggf. gequotet).
    dst_db_path sollte ein absoluter Pfad sein (BASE_DIR-basiert).
    """
    con = DbPool.get(src_db_path)
    src_catalog = Path(src_db_path).stem  # z. B. 'analytics'
    con.execute(f"ATTACH '{dst_db_path}' AS new_db")
    con.execute(f'COPY FROM DATABASE "{src_catalog}" TO new_db')
    con.execute("DETACH new_db")

---

### Schritt 2: Startup Status (`main.py`)
Beim App-Start in `main.py` aufrufen und UI-Label unter Optionen-Button befüllen (absoluter Pfad via `BASE_DIR`):

# main.py
from db.db_utils import get_db_fragmentation_info

info = get_db_fragmentation_info(str(BASE_DIR / "data" / "analytics.duckdb"))
# UI-Label setzen (label_db_status – in ui/main_win.ui ergänzen oder per Code erzeugen)
self.label_db_status.setText(f"DB Status: {info['pct']}% fragmentiert ({info['bloat_mb']} MB frei)")

---

### Schritt 3: UI, Concurrency-Guard & Kompaktierung (`properties_win.py`)
Button `[ 🧹 DB Service ]` in `PropertiesWindow` für die **Kompaktierung** (COPY FROM DATABASE) einbauen. Guard über den **EventBus-Zähler** (konsistent zu Phase 16; NICHT `self.parent()`, da `PersistentWindow` kein Qt-Parent hat):

# properties_win.py
from pathlib import Path
from config.event_bus import event_bus
from db.db_utils import copy_database

BASE_DIR = Path(__file__).resolve().parent

def _on_btn_vacuum_clicked(self) -> None:
    # Concurrency-Guard über EventBus-Zähler (MainWindow aktualisiert ihn
    # in service_run_started/finished; Eigentum: Phase-16-Referenzzähler)
    if getattr(event_bus, "sync_pause_count", 0) > 0:
        print("⚠️ DB-Service gesperrt: Scans/Worker laufen aktuell.")
        return

    # Kompaktierung analytics + market_data (absolute Pfade, BASE_DIR)
    copy_database(str(BASE_DIR / "data" / "analytics.duckdb"),
                  str(BASE_DIR / "data" / "analytics_compacted.duckdb"))
    copy_database(str(BASE_DIR / "data" / "market_data.duckdb"),
                  str(BASE_DIR / "data" / "market_data_compacted.duckdb"))
    # Datei-Ersatz NUR bei geschlossenen DbPool-Verbindungen (Windows File-Lock!)
    # → Verbindungen schliessen/neu öffnen (DbPool-Methode), alte Datei löschen,
    #   kompakte Datei umbenennen, DB erneut öffnen.
    print("✅ DB-Kompaktierung erfolgreich ausgeführt.")

---

## 📊 3. Akzeptanzkriterien (`test/test.py`)
1. `get_db_fragmentation_info()` liefert Prozent-, Bloat- und Größen-MB-Werte ohne Exception zurück.
2. `execute_db_vacuum()` (CHECKPOINT + VACUUM) schließt fehlerfrei ab und erzeugt eine konsistente Datei (kein WAL-Replay beim nächsten Öffnen).
3. `copy_database(src, dst)`-Helper (Kompaktierung): Kopie ist kleiner als die Bloat-Datei und enthält Schema + Daten vollständig (headless-Test wie `test/check_copy_database.py`).

---

## 📝 4. Prüfung & Entscheidungen (12.08.2026)

> Implementierungs-Log: Konsistenz-/Korrektheits-/Vollständigkeits-Prüfung von Kap. 21.02 gegen den Code-Stand (Commit `bfaf971`). **Kein Coding** – reine Doku der Befunde und getroffenen Entscheidungen.

### 4.1 Status
- Kap. 21.02 ist eine **Spezifikation/Umsetzungsanleitung** – die Umsetzung ist **offen** (kein Code vorhanden).
- **Beschluss (12.08.2026):** Kein Coding jetzt; Umsetzung erst nach expliziter Anweisung. Die Prüf-/Arbeitsmethode (headless-Verifikation + Doku-Log) wird weiterhin ausgearbeitet.

### 4.2 Vollständigkeit (Code-Befund)
| Schritt | Doku-Vorgabe | Stand |
|---|---|---|
| Schritt 1 | `get_db_fragmentation_info()` / `execute_db_vacuum()` in `db/db_utils.py` | ❌ nicht vorhanden (`db_utils.py`: nur `_ensure_epoch`/`_parse_json_field`) |
| Schritt 2 | Startup-Aufruf `main.py` + `label_db_status` | ❌ nicht vorhanden; Label existiert auch nicht in `ui/main_win.ui` |
| Schritt 3 | VACUUM-Button in `properties_win.py` + Guard | ❌ nicht vorhanden |
| AK 1–2 | Headless-Tests | ❌ nicht verifizierbar (Code fehlt) |

✅ Vorhanden als Grundlage: `_sync_pause_count` in `main.py:166` (Phase-16-EventBus-Guard, Signale `service_run_started`/`service_run_finished`).

### 4.3 Befunde der Konsistenz-/Korrektheits-Prüfung
- **K1 (Guard wirkungslos):** `PersistentWindow.__init__` übergibt **kein Qt-Parent** (`super().__init__()` ohne parent, Logik-Parent nur für `state_manager`) → `self.parent()` ist `None` → `getattr(self.parent(), "_sync_pause_count", 0)` greift **nie** (immer Default 0).
- **K2 (Label fehlt):** `label_db_status` existiert nicht in `ui/main_win.ui` (dort nur `status_label`); kein dedizierter Platz „unter dem Optionen-Button".
- **F1 (falscher PRAGMA-Spalten-Index):** `PRAGMA database_size` (DuckDB 1.5.5) liefert: `0 database_name, 1 database_size (VARCHAR), 2 block_size, 3 total_blocks, 4 used_blocks, 5 free_blocks, 6 wal_size, 7 memory_usage, 8 memory_limit`. Der Snippet nutzt `res[1], res[3]` = **`database_size` (String!)** + **`total_blocks`** → falsch.
- **F2 (VACUUM wirkungslos, empirisch belegt):** `INSERT 500k → DELETE → VACUUM;` sowie `CHECKPOINT;` ändern die Dateigröße **nicht** (0 % Reduktion); `PRAGMA database_size` vor/nach identisch. DuckDB 1.5.5 besitzt **kein echtes VACUUM** wie SQLite – das Ziel „Bloat reduzieren" ist mit `VACUUM;` nicht erreichbar. AK2 („verringert/konsolidiert Blöcke") ist damit nicht erfüllbar.

### 4.4 Entscheidungen (12.08.2026)
| Punkt | Entscheidung |
|---|---|
| **F1** (PRAGMA-Index) | ✅ **Bestätigt:** Korrektur auf `block_size, used_blocks = res[2], res[4]` |
| **K1** (Concurrency-Guard) | ✅ **Bestätigt:** Guard über `EventBus`-Zähler (konsistent zu Phase 16) statt `self.parent()` |
| **K2** (Status-Label) | ✅ **Bestätigt:** `label_db_status` wird ergänzt (in `ui/main_win.ui` oder per Code – Detail bei Umsetzung) |
| **F2** (VACUUM-Ziel) | ✅ **Entschieden:** Zweistufige Lösung – **CHECKPOINT + VACUUM beim App-Exit** (reguläre Pflege) + **COPY FROM DATABASE-Methode** (echte Kompaktierung). Siehe 4.6 |
| Umsetzung allgemein | ⏸️ **Zurückgestellt:** Kein Coding jetzt |

### 4.5 Ergänzungen (bei späterer Umsetzung zu beachten)
- `db/db_utils.py`: `import os` (für `get_db_fragmentation_info`) und `from pathlib import Path` (für `copy_database`) im Snippet ergänzt; `DbPool`-Import ist innerhalb des `db`-Pakets zulässig (Basis-Schicht E4 bleibt sonst ohne Projekt-Import).
- ✅ **Markdown-Artefakte `[cite: 1]` im Kapitel bereinigt** (12.08.2026, Abschnitte 2/3).
- ✅ **Umsetzungsplan nachgezogen** (12.08.2026): Schritt 1–3 + AK entsprechen jetzt der F2-Lösung (CHECKPOINT+VACUUM, COPY FROM DATABASE, EventBus-Guard, `res[2]/res[4]`).
- AK2-Formulierung folgt der F2-Lösung (siehe 4.6): `CHECKPOINT`/`VACUUM` allein verkleinern die Datei nicht – die **Kompaktierung** leistet `COPY FROM DATABASE`.

### 4.6 Lösungsweg F2: DB-Pflege beim App-Exit + Kompaktierung per COPY FROM DATABASE

**Beschluss (12.08.2026):** Die DB-Pflege wird zweistufig umgesetzt. Empirisch belegt (DuckDB 1.5.5): `VACUUM;` und `CHECKPOINT;` verkleinern die Datei **nicht** (0 % Reduktion, `PRAGMA database_size` unverändert). Die tatsächliche Kompaktierung leistet die **`COPY FROM DATABASE`-Methode**.

#### Stufe 1 – Beim Verlassen der App (regulär, `main.py` `closeEvent`)
Beim App-Exit wird für jede DuckDB-Datei ausgeführt:
```sql
CHECKPOINT;   -- WAL in Hauptdatei flushen (konsistenter Zustand)
VACUUM;       -- formale Defragmentierung (in DuckDB 1.5.5 ohne Dateigrößen-Effekt)
```
* Zweck: WAL wird aufgeräumt, die Datei in einen sauberen Zustand versetzt (kein WAL-Replay beim nächsten Start).
* Aufruf über `execute_db_vacuum(db_path)`-Erweiterung in `db/db_utils.py` (führt `CHECKPOINT;` **gefolgt von** `VACUUM;` aus).
* Gilt für `analytics.duckdb` und `market_data.duckdb` (bei Bedarf auch `app_data.duckdb`).
* **Keine UI-Blockade:** App-Exit läuft, wenn keine Scans/Worker mehr aktiv sind (Referenzzähler `_sync_pause_count == 0`).

#### Stufe 2 – Kompaktierung (Variante A: `COPY FROM DATABASE`, DuckDB ≥ 0.9.0)
Für eine echte Verkleinerung (Bloat entfernen) wird die Datenbank in eine frische, minimale Datei übertragen:

```sql
-- 1. Neue, leere Datenbank-Datei anheften (absoluter Pfad, BASE_DIR-basiert!)
ATTACH 'C:/Pfad/zum/Projekt/data/analytics_compacted.duckdb' AS new_db;

-- 2. Alle Daten/Schema/Indizes in die neue DB kopieren (lückenlose Datei)
--    WICHTIG: korrekte DuckDB-Syntax = COPY FROM DATABASE <src> TO <dst>
COPY FROM DATABASE analytics TO new_db;

-- 3. Neue DB wieder trennen
DETACH new_db;
```

* Danach wird im Dateisystem die alte `analytics.duckdb` durch die kompakte `analytics_compacted.duckdb` ersetzt (Löschen/Umbenennen).
* **Katalogname:** entspricht dem Datei-Basename ohne `.duckdb` (z. B. `analytics` für `analytics.duckdb`, `market_data` für `market_data.duckdb`). Bei Sonderzeichen (führender Unterstrich o. Ä.) ist der Katalogname in doppelte Anführungszeichen zu setzen: `COPY FROM DATABASE "_copy_src" TO new_db`.
* **⚠️ Windows File-Locking:** Der Datei-Ersatz (alte Datei löschen/umbenennen) funktioniert **nur**, wenn **alle offenen DbPool-Verbindungen** zu dieser DB geschlossen sind – sonst wirft Windows `PermissionError` (Datei in Verwendung). Ablauf: (1) `copy_database()` ausführen, (2) **DbPool-Verbindung schliessen/leeren** (Methode in `db/db_pool.py`), (3) alte Datei löschen, (4) kompakte Datei umbenennen, (5) DB neu öffnen. Kein laufender Scan/Worker darf zugreifen (Guard `_sync_pause_count == 0`).
* **⚠️ Absoluter Pfad:** `ATTACH`/`copy_database` immer mit **absolutem Pfad** (`BASE_DIR / "data" / ...`) aufrufen – relative Pfade hängen vom CWD ab (Desktop-Start vs. IDE unterscheidet sich).
* **Empirisch verifiziert** (headless, `test/check_copy_database.py`, nur Test-Dateien): Reduktion **85,4 %** gegen Bloat (Testfall mit vollständig gelöschten Daten); Schema, Tabellen, Constraints und Daten werden **vollständig** übertragen (PASS). Die reale Reduktion hängt vom tatsächlichen Bloat ab.
* **Guard:** Kompaktierung nur bei `_sync_pause_count == 0` (keine laufenden Scans/Worker); sinnvoller Einstieg: der `[ 🧹 DB Service ]`-Button in `PropertiesWindow` (nur Kompaktierung; App-Exit macht CHECKPOINT+VACUUM).

#### Akzeptanzkriterien (angepasst an F2-Lösung)
1. `get_db_fragmentation_info()` liefert Prozent-, Bloat- und Größen-MB-Werte ohne Exception zurück.
2. `execute_db_vacuum()` (CHECKPOINT + VACUUM) schließt fehlerfrei ab und erzeugt eine konsistente Datei (kein WAL-Replay beim nächsten Öffnen).
3. `copy_database(src, dst)`-Helper (Kompaktierung): Kopie ist kleiner als die Bloat-Datei und enthält Schema + Daten vollständig (headless-Test wie `test/check_copy_database.py`).




---

# 21.02.1 – Bugfix-Runde 12.08.2026 (Service-UI & Heatmap)  [ehem. Kap. 21.03]

> Implementierungs-Log (Commit `271a81b`, 12.08.2026): 5 neue User-Meldungen
> aus dem Bugfixing-Modus (Fortschrittsbalken, Data-Only-Loeschen,
> Heatmap-Legende, Overlay-Balken) + Crash `srv_trend_hma_pivot`.
> Verifikation headless (keine UI): `test/check_hma_pivot_bug.py`,
> `test/check_purge_legacy.py` (5/5), `test/check_heatmap_format.py`,
> `test/check_overlay_tf_precedence.py` - alle PASS.

## ?? 1. Punkt 0 - `srv_trend_hma_pivot` LiveAnalyzer-Crash (Broadcast-Fehler)

**Meldung:** `ValueError: could not broadcast input array from shape (4,) into shape (0,)`
bei `SILVER/M1` im LiveAnalyzer (`df_short = df_plugin.tail(2)` -> 1-2 Bars).

**Ursache:** `chart/indicators/utils/ma_template.py`: `_sma_values`, `_wma_values`,
`_alma_values`, `_vwma_values` nutzen `np.convolve(..., "valid")` + Zuweisung
`result[period-1:] = conv`. Ist die Serie kuerzer als `period`, liefert convolve
ein Array der Laenge `period-n+1` (z. B. 4), waehrend `result[period-1:]` leer
ist -> Broadcast-Fehler.

**Fix:** Guard `if len(values) < period: return np.full(len(values), np.nan)`
in allen 4 Funktionen (Warmup-Vertrag: kurze Serien = NaN, kein Crash).

**Verifikation:** `py_compile` OK; `test/check_hma_pivot_bug.py` - n=2/3/4/5/10
OK; alle 12 MA-Typen mit n=2 OK; EHMA n=100 finite ab Index 9.

## ?? 2. Punkt 1 - "Data only loeschen" loeschte ALLE Varianten

**Meldung:** "Data only loeschen" entfernte die Daten ALLER Varianten
(DB-Befund: `srv_swing_volume_profile` mit 3 Presets; UI-Varianten-Hashes
69141755/8c21542a/7341c563, Legacy-Pools 4eec2b02/7d636c36/074ec5bb).

**Ursache:** `purge_instance_data` (feature_builder.py) loeschte IMMER auch den
Params-only-Legacy-Pool (`generate_instance_hash(plugin_id, params)` ohne
preset_name). Teilen sich Varianten denselben Params-only-Hash (identische
Params), gehoert der Pool ALLEN - der Purge einer einzelnen Variante entfernte
damit die Daten der uebrigen.

**Fix (Runde 6):**
1. `feature_builder.py`: Signatur `purge_instance_data(..., purge_legacy=False)`.
   Legacy-Purge laeuft NUR noch auf explizite Anforderung.
2. `service_win.py` + `service_selector_dialog.py`: neuer Helper
   `_purge_legacy_allowed(plugin_id, params)` - zaehlt aktive Varianten
   (Presets + Set-Instanzen) mit identischem Params-only-Hash. `owners == 1`
   => Pool eindeutig => Legacy-Purge erlaubt; `owners > 1` => Pool geteilt
   => bleibt unangetastet.

**Teil 2 ("M1 wird immer noch angezeigt"):** Die Badge-Bar liest
`fetch_service_tf_status` (feature_store_reader.py:1327) nach `feature_id`
(SERVICE-weit, nicht varianten-scoped). Nach Purge einer Variante verbleiben
die M1-Rows der uebrigen Varianten -> M1-Pill bleibt korrekt sichtbar. Erst
wenn ALLE Varianten gepurged sind (jede mit eindeutigem Legacy-Pool), loescht
sich M1. **Verifiziert** (test/_tmp_verify_badge.py, read-only): erwartetes
Verhalten.

**Verifikation:** `test/check_purge_legacy.py` (5/5): Default-False schuetzt
geteilte Pools, purge_legacy=True loescht eindeutige Pools, Altsignatur
kompatibel.

## ?? 3. Punkt 2 - Fortschrittsbalken fehlt

**2a ("nicht bei alle services ausfuehren"):** `ServiceSelectorDialog` (Picker)
verband KEIN `service_progress`-Signal und hatte keinen QProgressBar.

**Fix:** Progress-Zeile (progress_label + QProgressBar, Muster service_win)
unter der badge_bar im Panel-Layout; `service_progress`-Verbindung im
`_start_run_worker`; neue Slots `_on_service_progress` / `_reset_run_progress`;
Reset bei Start/Ende/Fehler (finished + failed).

**2b ("nicht loeschen"):** Nach 'Data Only Loeschen' / Voll-Loeschung blieb ein
veralteter Balkenzustand stehen.

**Fix:** `_reset_run_progress()` in service_win nach erfolgreichem Purge
(`_on_data_only_purge`, `_delete_complete_set_instance`, `_delete_complete_preset`).

## ?? 4. Punkt 3 - Heatmap-Legende auf 2 Nachkommastellen begrenzen

**Fix:** `_format_heatmap_value` (heatmap_widget.py): Bruchwerte mit
`f"{fval:.2f}"` statt `f"{fval:.6f}"` (gerundet, Nullen gestrippt).
Ganzzahlen unveraendert (deutsche Tausender-Trennung '4.380').

**Verifikation:** `test/check_heatmap_format.py` - 62.5567 -> '62.56',
0.005 -> '0.01', 4380 -> '4.380', Nicht-Numerisch unveraendert (ALL PASS).

## ?? 5. Punkt 4 - Anzeigebalken ca. 18 Stunden breit (Swing Momentum AVG)

**Befund (empirisch):** Die "18h-Balken" sind die Candle-Overlay-Koerper im
D1-Timeframe: `bar_sec * 0.7` = 86400 * 0.7 = 60480s = **16,8h** (~70 % der
Tages-Spalte). `_bar_interval_seconds` las den TF nur aus
`params["timeframe"]` - ohne sichtbare Anzeige, welcher TF die Breite
bestimmt.

**Fix:**
1. `_bar_interval_seconds(data_tf)` bevorzugt den **Daten-TF des OHLCV-
   Payloads** (Kerzenbreite folgt der Datenbasis, Race-/Divergenz-sicher).
2. Neues Label `_label_overlay_tf` in der Steuerzeile zeigt den Overlay-TF
   live an (z. B. 'Overlay: D1' / 'Overlay: H1') - beantwortet "welcher TF
   wird angelegt / wo sehen".

**Verifikation:** `test/check_overlay_tf_precedence.py` - data_tf hat Vorrang
(D1->86400, M1->60), Fallback 3600s, D1-Koerper 16,80h (ALL PASS).

## ?? 6. Geaenderte Dateien (Commit `271a81b`)

| Datei | Aenderung |
|---|---|
| `chart/indicators/utils/ma_template.py` | 4x Warmup-Guard (Serie < period -> NaN) |
| `analytics/features/feature_builder.py` | `purge_instance_data(..., purge_legacy=False)` |
| `serviceui/service_win.py` | `_purge_legacy_allowed` + purge_legacy + Progress-Reset |
| `serviceui/service_selector_dialog.py` | `_purge_legacy_allowed` + Progress-Bar + Reset |
| `analytics/ui/heatmap_widget.py` | `_format_heatmap_value` (2 NK), `_bar_interval_seconds(data_tf)`, Overlay-TF-Label |
| `test/` | `check_hma_pivot_bug.py`, `check_purge_legacy.py`, `check_heatmap_format.py`, `check_overlay_tf_precedence.py` |

**Nicht angefasst:** 21.02-Working-Tree-Dateien (`db/db_utils.py`, `db/db_pool.py`,
`config/event_bus.py`, `main.py`, `properties_win.py`, `ui/main_win.ui`).

---

# 21.02.2 – Bugfix-Runde 12.08.2026 (Fortschrittsbalken & TF-Badges)  [ehem. Kap. 21.04]

> Implementierungs-Log (Commit `ef81fb0`, 12.08.2026): 2 neue User-Meldungen
> aus dem Bugfixing-Modus (Folge-Runde zu 21.02.1):
>   1) "Fortschrittsbalken laeuft dauerhaft -> Fehler?"
>   2) "Data only loeschen: nur in einer Variante alles geloescht (Datum nie),
>      aber alle TF wird immer noch angezeigt; Fehler bei Kopie 99 (swing volume)"
> Verifikation headless (keine UI): `py_compile` (3 Dateien),
> `test/check_2101b.py` (18/18 PASS), read-only-DB-Check gegen die reale
> `analytics.duckdb` (Varianten-Hashes von `srv_swing_volume_profile`).

## ?? 1. Punkt 1 - Fortschrittsbalken laeuft dauerhaft

**Meldung:** Der Fortschrittsbalken unter dem MasterTree laeuft dauerhaft
(kein Fehler, aber endlose Animation).

**Ursache:** `QProgressBar.setMaximum(0)` startet eine **indeterminate
Busy-Animation**, die nie endet. In `service_win.py` (Init Zeile ~255) und
`service_selector_dialog.py` (Init Zeile ~453) sowie nach jedem
`_reset_run_progress()` (`bar.setMaximum(0)`) wurde damit eine Endlos-Animation
angestossen - unabhaengig von laufenden Service-Runs.

**Fix (beide Dateien):**
1. **Init:** `setMaximum(0)` ersetzt durch `setRange(0, 1)` + `setValue(0)`
   (determinate leere Range statt Busy-Loop).
2. **`_reset_run_progress()`:** `setMaximum(0)` ersetzt durch
   `setRange(0, 1)` + `setValue(0)`.
3. `_on_service_progress` setzt beim Run weiterhin die echte Range
   (`setMaximum(max(total, 1))`) - unveraendert.

Damit ist der Balken ausserhalb von Runs ruhig (leer) und zeigt nur waehrend
eines echten Service-Runs Fortschritt an.

**Verifikation:** `py_compile` OK; keine `setMaximum(0)`-Aufrufe mehr im Code
(nur Kommentar-Hinweise in den neuen Kommentaren).

## ?? 2. Punkt 2 - "Data only loeschen": TF-Pills bleiben sichtbar

**Meldung:** Nach "Data only loeschen" einer Variante (Kopie 99 von
`srv_swing_volume_profile`) wurde das Datum korrekt auf "nie" gesetzt
(Purge OK), aber ALLE TF-Pills werden weiterhin angezeigt.

**Befund (DB, read-only):** Der Pill-Strip wurde SERVICE-weit geladen:
`fetch_service_tf_status` (feature_store_reader.py:1327) gruppierte nur nach
`feature_id`, NICHT nach `instance_hash`. Die Variante 8c21542a (Kopie 99)
war nach dem Purge aus der DB entfernt, aber die uebrigen Varianten
(69141755 "Default (Kopie)", 7341c563 "srv_swing 34566") besassen weiterhin
je ~100k Rows pro TF -> die Pills blieben korrekt (aber verwirrend) sichtbar.
Antwort auf die User-Frage: Die TFs wurden bisher NICHT je Variante einzeln
angezeigt.

**Fix (Varianten-Scope):**
1. `feature_store_reader.py`: `fetch_service_tf_status(plugin_id,
   instance_hash=None)` - optionaler Hash filtert die Rows exakt auf GENAU
   diese Variante (`AND LOWER(TRIM(instance_hash)) = LOWER(TRIM(?))`).
   Ohne Hash bleibt das service-weite Verhalten erhalten (Alt-Caller
   kompatibel: `analytics_win.py`, `check_2101b.py`).
2. `service_win.py` + `service_selector_dialog.py`: `_resolve_badge_plugin`
   umbenannt zu `_resolve_badge_scope` (liefert Tuple
   `(plugin_id, instance_hash)`):
   * Clone-Knoten: instance_hash aus dem `service_id`-Slot
     (MasterTree._emit_selection_details, 20.04 Q7).
   * Set-/Service-Zeilen: `cfg['instance_hash']` aus der Set-Definition,
     sonst `generate_instance_hash(plugin_id, params)` (Params-only).
   * Plugin/Standalone: Hash = None (service-weit, wie bisher).
3. `_refresh_badge_bar(plugin_id, instance_hash=None)` merkt sich den Hash
   (`_badge_instance_hash`) und uebergibt ihn an den Reader.

**Effekt:** Nach "Data only loeschen" einer Variante verschwinden ihre TF-Pills
sofort; die Pills der uebrigen Varianten zeigen nur noch deren eigene Daten.

**Verifikation (read-only, reale DB):**
* `fetch_service_tf_status(PID)` -> 9 TFs (D1..M5), Summe = alle Varianten.
* `fetch_service_tf_status(PID, "69141755")` -> 9 TFs, Summe < service-weit
  (nur eigene ~100k/TF).
* `fetch_service_tf_status(PID, "8c21542a")` -> **{}** (purged, korrekt leer).
* `fetch_service_tf_status(PID, "does_not_exist")` -> {} ; leere Parameter -> {}.
* `test/check_2101b.py` -> 18/18 PASS (Alt-Signatur kompatibel).

## ?? 3. Geaenderte Dateien (Commit `ef81fb0`)

| Datei | Aenderung |
|---|---|
| `analytics/engine/feature_store_reader.py` | `fetch_service_tf_status(plugin_id, instance_hash=None)` - Varianten-Filter |
| `serviceui/service_win.py` | Progress-Bar determinate (Init + Reset); `_resolve_badge_scope` + `_refresh_badge_bar(pid, hash)` |
| `serviceui/service_selector_dialog.py` | Progress-Bar determinate (Init + Reset); `_resolve_badge_scope` + `_refresh_badge_bar(pid, hash)` |

**Nicht angefasst:** 21.02-Working-Tree-Dateien (`db/db_utils.py`, `db/db_pool.py`,
`config/event_bus.py`, `main.py`, `properties_win.py`, `ui/main_win.ui`).

---

# 21.03 – Multi-Timeframe Focus & Context (MTF-FC v4)

---

## 🎯 1. Zielstellung & System-Anforderungen

Das MTF-FC-System bietet eine mathematisch und visuell konsistente Multi-Timeframe-Analyse für PyTrader. Es löst Inkongruenzen zwischen Kerzen- und Service-Timeframes, verhindert UI-Flackern beim Zoomen, schützt vor Datenverlusten bei engem Zoom-Fokus und führt den Benutzer transparent durch unvollständige Datenhistorien.

* **Hinweis:** „MTF-FC v4“ ist eine interne Revisionsbezeichnung der Spezifikation (iterativer Entwurfsprozess v1 → v2 → v3 → v4). Es fehlen keine früheren Quellcode-Kapitel; das Modul ordnet sich als Kapitel 21.03 nahtlos nach der DB-Maintenance (21.02) in die Dokumentationsstruktur ein.

---

## 🏗️ 2. Schichten-Architektur & System-Schnittstellen

Das System trennt strikt zwischen drei Funktionsschichten:

┌────────────────────────────────────────────────────────────────────────────────────────┐
│  SCHICHT 3: UI- / Chart-Orchestrierung (Frontend & PyLWC)                              │
│  - MtfFilterBarWidget (Data-TF, Chart-TF, Range, View-Templates, Confluence-Slider)   │
│  - Hysterese-Engine (Range-Monitoring, Breadcrumb-Puls)                                │
│  - Interaktive Badges, Geister-Marker & Temporary Guard Override                       │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼ (Lese-Pfade & EventBus)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  SCHICHT 2: MTF-FC Data Provider & Partition Manager (Middleware)                    │
│  - Namespace-Isolierung: shared_state["mtf_fc"] (Active TF, Boundaries, Generation)     │
│  - Cache-Versionierung: (symbol, timeframe, partition) + source_max_timestamp          │
│  - Partitioned DuckDB-Reads (fetch_daily_ohlc, fetch_ohlcv_snapshot)                    │
│  - Precision-Aware Boundary Policy (Native vs. Fallback Flags)                         │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼ (Feature Calculate & Pipeline)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  SCHICHT 1: Backend- & Analytics-Engine (Core Infrastructure)                         │
│  - ServiceSetEvaluator (execute_set_resilient() vs. execute_set() Fail-Fast)           │
│  - PluginExecutor & PluginContext.shared_state                                         │
│  - LiveAnalyzer (tail(2)-Evaluation & RAM-State-Buffer)                                │
│  - SchemaMigrator (Transparente In-Memory-Migration & Rollback-Schutz)                 │
└────────────────────────────────────────────────────────────────────────────────────────┘


---

## 🚦 3. Formale State-Machine & Prioritäts-Kette

### 3.1 Zustandstabelle (Data-TF vs. Chart-TF)

| Data-TF (Filter) | Kaskade (Auto) | Resultierendes Chart-TF | System-Verhalten / Guard-Aktion |
| --- | --- | --- | --- |
| **🌐 Multi (M1..D1)** | ⚡ Auto | **Dynamisch (M1..D1)** | Standard. Kaskade wählt TF vollautomatisch nach Zoom-Level. |
| **🔒 Fixiert auf M15** | ⚡ Auto | **$\le$ M15 (M1, M5, M15)** | **Guard aktiv:** Chart-TF schaltet nie höher als M15. Kaskade nach unten erlaubt. |
| **🔒 Fixiert auf H4** | ⚡ Auto | **$\le$ H4 (M1..H4)** | **Guard aktiv:** Schaltet bei Zoom-Out maximal bis H4. D1-Upgrade gesperrt. |
| **🔒 Fixiert auf M15** | 🔒 Manuell D1 | **M15 (Forced)** | **Inkongruenz-Warnung:** *"D1-Kerzen nicht möglich, da Data-TF auf M15 fixiert. Kerzen auf M15 gesetzt."* |
| **Jeder Fix-State** | 📍 Klick Geister-Marker (D1) | **D1 (Temporär)** | **Guard Override:** Temporary Unlock mit Reset-Badge `[ 🌐 Data-TF gelockert ]`. |

### 3.2 Prioritäts-Kette (Konflikt-Hierarchie)

Trifft die Steuerung auf widersprüchliche Eingaben oder Beschränkungen, entscheidet folgende Kette (Ebene 1 gewinnt immer):

1. **Ebene 1 – Hard Data Availability Guard:** Fehlen M1-Daten vor der tatsächlichen Daten-Grenze des Symbols (z. B. für frisch angelegte Symbole oder nach einem partiellen History-Purge), erzwingt das System `coverage_status = "fallback"` mit nächst-höherem TF (z. B. H1). Die Grenze wird dynamisch ermittelt: `m1_available_from = get_earliest_timestamp(symbol, "M1")` (reale SILVER-Daten: M1-Historie ab 2013-06-05). Die Boundary-Policy greift exakt an dem Punkt, an dem das älteste M1-Bar des gewählten Symbols liegt. Eine höhere Aggregationsstufe darf niemals als M1 deklariert werden ($H1 \to M1$ ist strikt verboten).
2. **Ebene 2 – Temporary User Override (Geister-Marker Klick):** Klickt der Nutzer bei fixiertem `Data-TF = M15` auf einen D1-Geister-Marker, greift die Transaktions-Semantik:
* `override.active = True`
* `override.previous_data_tf = "M15"`
* `override.target_tf = "D1"`
* Das `Data-TF` wird gelockert und ein Badge `[ 🌐 Data-TF temporär gelockert auf D1 | Reset ]` erscheint. Klick auf *Reset* stellt exakt `previous_data_tf` wieder her.

3. **Ebene 3 – Fixed Data-TF Guard:** Ohne temporären Override erzwingt ein auf M15 fixiertes `Data-TF`, dass das `Chart-TF` maximal M15 oder feiner ist.

4. **Ebene 4 – Auto Cascade:** Standard-Hysterese schaltet den Chart-TF basierend auf der Viewport-Breite.

5. **Ebene 5 – Visual Rendering Preference:** Benutzerdefinierte Farbschemas und Labels.

---

## 🧱 4. Die 3 Architektur-Säulen

### Säule 1: MtfFilterBarWidget & Control-Panel

1. **Steuerungselemente:**
* **Source-Data-TF:** `🌐 Alle Timeframes` (Multi) vs. `🔒 Fixiert auf [TF]`.

* **Chart-Overlay-TF:** `⚡ Auto (Kaskade)` vs. `🔒 Manuell Fix`.

* **Range-Picker:** Presets (`24h`, `7d`, `30d`, `YTD`) & Benutzerdefiniert.

* **View-Templates (Presets):** Speichern und Laden von kompletten Filter-Konfigurationen. Das `MtfFilterBarWidget` nutzt den bestehenden `SchemaMigrator` (`analytics/engine/schema_migrator.py`), um gespeicherte Preset-JSONs in-memory zu validieren und abwärtskompatibel um neue TFs/Session-Keys zu erweitern (Payload-Key `mtf_fc_schema_version = "1.0.0"`).
* **Tabellen-Sortierung:** Dropdown für `[ Datum 🠇 ]`, `[ Signal-Stärke 🠇 ]`, `[ TF 🠅 ]`.

2. **Session-Filter & DST-Normalisierung:**
* Handelssessions (London, New York, Tokio) als Farbbalken im M1/M5-Zoom.
* **DST-Invariante:** Alle Session-Grenzen werden strikt in **UTC-Epochs** berechnet und erst beim Rendern formatiert (Invariante 7).

3. **Transparente Historien-Anzeige & Boundary Policy:**
* Anzeigeelement: `ℹ️ M1 verfügbar ab DD.MM.JJJJ`.
* **Boundary Policy:** Zoomt der Nutzer vor die Verfügbarkeitsgrenze, zeigt der Chart nahtlos H1-Kerzen mit dem Flag `coverage_status = "fallback"` und der Schraffur *"Keine M1-Rohdaten für diesen Zeitraum"* (keine Lücke, kein Absturz).

4. **Confluence-Gewichtung & Normalisierung:**
* **Formel:** $Score_j = \sum (W_{TF} \cdot Signal_{TF})$ mit vollständigem Gewichtungs-Schema:
  * $W_{\text{D1}} = 3.0$
  * $W_{\text{H4}} = 2.5$
  * $W_{\text{H1}} = 2.0$
  * $W_{\text{M15/M30}} = 1.5$
  * $W_{\text{M5}} = 1.2$
  * $W_{\text{M1}} = 1.0$
* Die Gewichte fließen **un-normalisiert** in die Summe ein und werden anschließend durch die **Constant-Matrix-Policy / Min-Max-Skalierung** auf das Farb-Intervall $[0.0, 1.0]$ abgebildet.
* **Constant-Matrix-Policy (Min-Max-Fix):** Ist $\text{max\_score} == \text{min\_score}$, gilt $\text{normalized\_score} = 0.5$ (verhindert Divisionen durch Null).
* **Volatilitäts-Adaption (Toggle) mit Clamp-Protection:**

$$ratio = \text{clamp}\left(\frac{\text{ATR}_{\text{TF}}}{\text{ATR}_{\text{Current}}}, \, 0.2, \, 5.0\right)$$

Bei $\text{ATR}_{\text{Current}} \le 10^{-6}$ wird die Anpassung deaktiviert ($ratio = 1.0$).

### Säule 2: Smart PyLWC-Zoom-Kaskade & Performance

1. **Hysterese-Schaltlogik & Parameter:**
* **Haupt-Stufen der Auto-Kaskade:** M1 → M5 → H1 → H4 → D1 (prägnante Stufen gegen visuelles Dauer-Flackern und unnötige Cache-Sprünge bei kleineren Zoom-Bewegungen).
* **Zoom-Bänder (Auto):**
  * **Band 1 ($< 2.0$ Tage):** Umschaltung M1 ↔ M5
  * **Band 2 ($2.0$ bis $10.0$ Tage):** Umschaltung M15 ↔ H1 (Fein-Stufe M15)
  * **Band 3 ($10.0$ bis $35.0$ Tage):** H4
  * **Band 4 ($> 35.0$ Tage):** D1
* **Schwellwerte (Hysterese zwischen den Bändern):**
  * `ZOOM_OUT_THRESHOLD_M1` = $3.5\text{ Tage}$ ($84.0\text{ h}$) — M1/M5 → H1 (Zoom-Out)
  * `ZOOM_IN_THRESHOLD_M1` = $2.0\text{ Tage}$ ($48.0\text{ h}$) — H1 → M1/M5 (Zoom-In)
  * `ZOOM_OUT_THRESHOLD_H4` = $10.0\text{ Tage}$ — H1 → H4 (Grenze Band 2→3)
  * `ZOOM_OUT_THRESHOLD_H1` = $35.0\text{ Tage}$ — H4 → D1 (Zoom-Out)
  * `ZOOM_IN_THRESHOLD_H1` = $28.0\text{ Tage}$ — D1 → H4 (Zoom-In)
* `CROSSFADE_DURATION_MS` = $250\text{ ms}$ (UI-Parameter)
* **Manueller Modus (`Chart-TF` = 🔒 Fix):** Erlaubt das Erzwingen *jeder* beliebigen Zwischenstufe (z. B. M30 oder H2) – M15/M30/H2 sind nicht verboten, sondern dienen als Fein-Stufen innerhalb der Bänder.

Zoom-Out (Zeitfenster vergrößern):
   M1/M5 ───( > 3,5 Tage )───> H1 ───( > 10,0 Tage )───> H4 ───( > 35 Tage )───> D1

Zoom-In (Zeitfenster verkleinern):
   D1   ───( < 28 Tage )───> H4  ───( < 10,0 Tage )───> H1  ───( < 2,0 Tage )───> M1/M5


2. **Transition Guard & Telemetrie:**
* Ein Umschalten erfolgt erst, wenn $\text{now}() - transition\_started\_at \ge \frac{CROSSFADE\_DURATION\_MS}{1000.0}$.
* Jedes Kaskaden-Event emittiert ein strukturiertes Telemetrie-Log (`trigger`, `from_tf`, `to_tf`, `range_days`).
* **Puls-Breadcrumb:** Transparenter Badge oben rechts im Canvas (`[ ⚡ Kerzen: M5 ]`), der bei Umschaltung kurz hellblau aufleuchtet.


3. **RAM-Caching & Event-basierte Invalidierung:**
* Nutzt vorgepufferte Tages- und Stunden-Snapshots: `fetch_daily_ohlc` = echte SQL-Aggregation über das Wanduhr-Datum (Tages-Ohlc); „Stunden-Snapshot“ = direkte H1-Roh-Bar-Abfrage via `fetch_ohlcv_snapshot(symbol, "H1", limit)` (read-only auf `ohlcv_bars` in `market_data.duckdb`).
* **Event-Partitionierung bei Late-Arriving Ticks:**

$$affected\_partition = partition(symbol, timeframe, t_{\text{event}})$$

Nachträglich eingehende Ticks invalidieren ausschließlich die RAM-Partition ihrer eigenen Event-Zeit $t_{\text{event}}$, nicht den gesamten Cache.

### Säule 3: Interaktives Layering & Geister-Marker

1. **Interaktive TF-Badges:**
* Klick auf ein Badge (`[ H4-Swing ]`) filtert die aktuelle Ansicht synchron auf diesen Timeframe.
* Strg + Klick ermöglicht Multi-Select.

2. **Geister-Marker (Off-Screen Level):**
* Übergeordnete Level (z. B. D1-Widerstand) außerhalb des Zoom-Blicks werden am Rand des Viewports als verblasster Pfeil gerendert: `▲ D1-Widerstand (27.85)`.
* Klick löst den Guard-Override nach Ebene 2 aus und animiert den Viewport sanft zum Ziel-Level.

---

## 💾 5. Data-Provider & `shared_state`-Spezifikation

Das System nutzt einen dedizierten, isolierten Namespace unter `PluginContext.shared_state["mtf_fc"]`:

shared_state["mtf_fc"] = {
    "active_data_tf": "M15",
    "active_chart_tf": "M5",
    "viewport_range": {"from_ts": 1785500000, "to_ts": 1785972000},  # ~5,4 Tage
    "cascade_state": {
        "current_tf": "M5",
        "candidate_tf": "H1",
        "direction": "zoom_out",
        "transition_started_at": 1785971900.5,
        "last_transition_at": 1785970000.0,
        "range_days": 5.4,  # > 3.5 Tage (auslösender Zoom-Out-Bereich)
    },
    "history_boundaries": {
        "m1_available_from": get_earliest_timestamp("SILVER", "M1"),  # dynamisch (real: 2013-06-05)
        "coverage_status": "fallback",    # "native" | "fallback"
        "source_tf": "H1",
    },
    "cache_generation": 42,
    "temporary_guard_override": {
        "active": True,
        "previous_data_tf": "M15",
        "target_tf": "D1",
        "reason": "ghost_marker_click",
    }
}


---

## 🧼 6. Fehler-Differenzierung & Resilienz-Mapping

Das System differenziert strikt zwischen fünf Fehlerklassen und verknüpft sie mit der bestehenden Backend-Resilienz (`ServiceSetEvaluator`):

                      ┌────────────────────────────────────────┐
                      │   Eingehender Fehler / Abweichung      │
                      └───────────────────┬────────────────────┘
                                          │
        ┌─────────────────┬───────────────┼───────────────┬────────────────┐
        ▼                 ▼               ▼               ▼                ▼
 [ DATA_MISSING ]  [ CACHE_STALE ] [ CACHE_CORRUPT ] [ SERVICE_FAILED ] [ NO_SOURCE ]
        │                 │               │               │                │
        ▼                 ▼               ▼               ▼                ▼
 Boundary-Policy    Kaskade invalid   Cache verwerfen   Bestehender State-   UI-Degraded-
 (Umschaltung auf   & Partial Re-     & DB-Rebuild      Fallback des        State mit Lade-
 nächstes TF mit    Load über         anstoßen          ServiceSet-         Hinweis &
 Fallback-Badge)    Event-Time-                         Evaluators          Retry-Button
                    Partition                           (RAM-Quarantäne)

---

## 📊 7. Headless-Validierung (`test/test.py`)

Folgende Tests verifizieren das System in `test/test.py` ohne GUI-Ausführung:

1. **Hysterese-Boundary-Test:**
* Testet exakt die Schwellwerte: $1.99\text{ d} \to M1$, $2.01\text{ d} \to$ kein Wechsel, $3.49\text{ d} \to$ kein Wechsel, $3.51\text{ d} \to H1$.


2. **20-fach Anti-Oszillations-Test:**
* Oszilliert den Viewport 20-mal im Fenster $[1.9\text{ d}, 3.6\text{ d}]$ und verifiziert, dass `transition_started_at` fehlerfreies Schalten garantiert.


3. **M1-Historien-Boundary-Test:**
* Prüft Daten vor der dynamischen M1-Grenze des Symbols (`get_earliest_timestamp(symbol, "M1")`) auf `coverage_status = "fallback"` und `source_tf = "H1"`.


4. **State-Machine & Guard-Override-Test:**
* Fixiert `Data-TF = M15`, simuliert Klick auf D1-Geister-Marker, prüft `previous_data_tf = M15` sowie die korrekte Wiederherstellung nach `Reset`.


5. **Constant-Matrix & Weight-Effect-Test:**
* Prüft, dass eine flache Matrix den Wert $0.5$ liefert und dass $W_{\text{D1}}=3.0$ vor der Min-Max-Skalierung die proportionale Übermacht behält.


6. **Late-Arriving Tick Partition-Test:**
* Injiziert einen historischen Tick ($t_{\text{event}} = \text{vor 5 Tagen}$) und verifiziert, dass exakt die betroffene Zeit-Partition invalidiert wird.


7. **Service-Failure-Degradation-Integrationstest:**
* Validiert, dass drei aufeinanderfolgende Fehler von Service A zur RAM-Quarantäne führen, Service B weiterläuft, Service C `dependency_failed` meldet, der alte `shared_state` erhalten bleibt und `reset()` die Quarantäne aufhebt.

---

## 📋 8. Umsetzungsplan (Übersicht & Reihenfolge)

Der Umsetzungsplan folgt der Schichten-Architektur **bottom-up** (Schicht 2 → Schicht 3) und ist strikt nach Abhängigkeiten gereiht: Jeder Schritt baut auf den vorhergehenden auf und ist einzeln headless verifizierbar (Grundsatz 2). Die bestehenden Schicht-1-Bausteine (`ServiceSetEvaluator.execute_set_resilient()`, `PluginContext.shared_state`, `LiveAnalyzer` tail(2), `SchemaMigrator`) werden **nicht verändert**, sondern konsumiert (Grundsatz 11, Open/Closed).

| Schritt | Kapitel | Inhalt | Baut auf | Verifikation (§7) |
|---|---|---|---|---|
| 1 | 21.03.01 | MTF-FC Data Provider & `shared_state`-Namespace (Schicht 2) | – | Namespace-/DB-Smoke |
| 2 | 21.03.02 | Boundary Policy & Historien-Detection | 21.03.01 | Test 3 |
| 3 | 21.03.03 | Hysterese-Kaskaden-Engine (Auto Cascade) | 21.03.01 | Test 1 + 2 |
| 4 | 21.03.04 | Confluence-Gewichtung & Normalisierung | 21.03.01 | Test 5 |
| 5 | 21.03.05 | State-Machine & Prioritäts-Kette (Guards & Override) | 21.03.01, 21.03.02 | Test 4 |
| 6 | 21.03.06 | Event-Partitionierung & Cache-Invalidierung | 21.03.01 | Test 6 |
| 7 | 21.03.07 | MtfFilterBarWidget & Control-Panel (UI) | 21.03.01, 21.03.02, 21.03.05 | py_compile + Inspektion |
| 8 | 21.03.08 | Chart-Integration: Kaskade, Puls-Breadcrumb, Historien-Anzeige | 21.03.03, 21.03.07 | node --check + py_compile + Inspektion |
| 9 | 21.03.09 | Interaktives Layering: TF-Badges & Geister-Marker | 21.03.05, 21.03.08 | node --check + py_compile + Inspektion |
| 10 | 21.03.10 | Abschluss: Integrationstest & Cleanup | 21.03.01–21.03.09 | Test 7 + Gesamtlauf |

### Begründung der Reihenfolge

1. **21.03.01 → 21.03.02:** Die Boundary-Policy liest die Daten-Grenzen aus dem Data Provider (`get_earliest_timestamp`) – ohne Provider keine Boundary.
2. **21.03.03–21.03.06:** Pure-Logik-Engines (Kaskade, Confluence, Guards, Partitionierung) hängen nur am State/Provider und sind headless vollständig testbar, bevor UI entsteht.
3. **21.03.07:** Das Control-Panel konsumiert State, Boundary und SchemaMigrator (kein SQL in UI, MVVM-Grundsatz 4).
4. **21.03.08:** Die Kaskaden-Anbindung an PyLWC braucht die Engine (21.03.03) und das Panel (21.03.07).
5. **21.03.09:** Badges/Geister-Marker brauchen die State-Machine (21.03.05) und das Chart-Rendering (21.03.08).
6. **21.03.10:** Integrationstests laufen erst, wenn alle Bausteine stehen; danach Cleanup von `test/` (Grundsatz 10).

---

# 21.03.01 – MTF-FC Data Provider & `shared_state`-Namespace (Schicht 2)

## 🎯 Ziel

Bereitstellung des dedizierten, isolierten Namespace `PluginContext.shared_state["mtf_fc"]` (Spezifikation §5) sowie des Datenzugriffs-Moduls mit Cache-Versionierung und Partitioned Reads. Grundlage für alle weiteren Schritte (Boundary, Kaskade, Guards, UI).

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_state.py` – Default-Factory/Struktur des `shared_state["mtf_fc"]`-Namespaces.
- **Neu:** `analytics/engine/mtf_fc_provider.py` – Cache-Versionierung `(symbol, timeframe, partition)` + `source_max_timestamp`, `get_earliest_timestamp(symbol, timeframe)`, gekapselte Reads über `fetch_daily_ohlc` / `fetch_ohlcv_snapshot` (read-only, DbPool).
- **Geändert:** keine Bestands-Kernklassen (Grundsatz 11).

## 🛠️ Umsetzungsschritte

1. `MtfFcState` als Default-Dict mit exakt den Keys aus §5:
   - `active_data_tf`, `active_chart_tf`, `viewport_range` (`from_ts`, `to_ts`)
   - `cascade_state` (`current_tf`, `candidate_tf`, `direction`, `transition_started_at`, `last_transition_at`, `range_days`)
   - `history_boundaries` (`m1_available_from`, `coverage_status`, `source_tf`)
   - `cache_generation`, `temporary_guard_override` (`active`, `previous_data_tf`, `target_tf`, `reason`).
2. `get_earliest_timestamp(symbol, timeframe)`: `SELECT MIN("time")` über `ohlcv_bars` in `market_data.duckdb`, Wanduhr-Epoch (Invariante 7, Muster `_epoch_of()` aus `feature_store_reader.py`). Defensiv `None` bei Fehler/leerer DB.
3. Cache-Versionierung: Schlüssel `(symbol, timeframe, partition)`; ein Eintrag trägt `source_max_timestamp`. Gültig nur, wenn `source_max_timestamp` ≤ aktuelles DB-Maximum (sonst stale).
4. Namespace-Schreibzugriff ausschließlich über den Provider (`read_namespace(context)` / `write_namespace(context, **changes)`) – keine UI-Direktzugriffe auf `shared_state`.
5. Wanduhr-Garantie: alle Zeiten als Wanduhr-Epochs, keine Berlin-Offset-Umrechnung (Invariante 7).

## ✅ Headless-Verifikation

- `test/test.py`: Namespace-Default-Struktur (alle Keys aus §5 vorhanden), `get_earliest_timestamp("SILVER", "M1")` ≈ 2013-06-05 (reale DB), Cache-Eintrag bildet `(symbol, timeframe, partition)` korrekt ab, stale-Erkennung bei veraltetem `source_max_timestamp`.

---

# 21.03.02 – Boundary Policy & Historien-Detection

## 🎯 Ziel

Präzise Ermittlung der M1-Verfügbarkeitsgrenze und Umsetzung der Boundary Policy (`coverage_status = "native" | "fallback"`, `source_tf`) gemäß §3.2 Ebene 1 und §4 Säule 1.3.

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_boundary.py` – Boundary-Evaluierung (reine Logik, kein UI-Import).
- **Geändert:** `test/test.py` (Test 3).

## 🛠️ Umsetzungsschritte

1. `resolve_boundary(symbol)` → `history_boundaries["m1_available_from"] = get_earliest_timestamp(symbol, "M1")` (aus 21.03.01).
2. `evaluate_coverage(symbol, from_ts)`:
   - `from_ts ≥ m1_available_from` → `coverage_status = "native"`, `source_tf = "M1"`.
   - `from_ts < m1_available_from` → `coverage_status = "fallback"`, `source_tf` = nächst-höherer TF mit Daten (z. B. H1).
   - **Regel:** Eine höhere Aggregationsstufe darf niemals als M1 deklariert werden ($H1 \to M1$ strikt verboten).
3. Anzeige-Datum: `m1_available_from` als `DD.MM.JJJJ` formatieren (Wanduhr, Invariante 7) – Grundlage für das UI-Element `ℹ️ M1 verfügbar ab DD.MM.JJJJ` (Umsetzung in 21.03.08).

## ✅ Headless-Verifikation

- Test 3: Daten vor der dynamischen M1-Grenze → `coverage_status = "fallback"` und `source_tf = "H1"`; Daten nach der Grenze → `"native"`.

---

# 21.03.03 – Hysterese-Kaskaden-Engine (Auto Cascade)

## 🎯 Ziel

Zoom-Kaskade mit Haupt-Stufen M1 → M5 → H1 → H4 → D1, Zoom-Bändern, Hysterese-Schwellwerten, Transition Guard und Telemetrie (§4 Säule 2).

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_cascade.py` – reine Logik, keinerlei UI-Import (Grundsatz 4/11).
- **Geändert:** `test/test.py` (Test 1 + 2).

## 🛠️ Umsetzungsschritte

1. Konstanten (Schwellwerte):
   - `ZOOM_OUT_THRESHOLD_M1 = 3.5` Tage (84.0 h) — M1/M5 → H1 (Zoom-Out)
   - `ZOOM_IN_THRESHOLD_M1 = 2.0` Tage (48.0 h) — H1 → M1/M5 (Zoom-In)
   - `ZOOM_OUT_THRESHOLD_H4 = 10.0` Tage — H1 → H4 (Grenze Band 2→3)
   - `ZOOM_OUT_THRESHOLD_H1 = 35.0` Tage — H4 → D1 (Zoom-Out)
   - `ZOOM_IN_THRESHOLD_H1 = 28.0` Tage — D1 → H4 (Zoom-In)
   - `CROSSFADE_DURATION_MS = 250`.
2. Zoom-Bänder (Auto): Band 1 (< 2.0 d, M1↔M5), Band 2 (2.0–10.0 d, M15↔H1), Band 3 (10.0–35.0 d, H4), Band 4 (> 35.0 d, D1).
3. `evaluate_cascade(viewport_from_ts, viewport_to_ts, current_tf, state)` → `candidate_tf`, `direction` (`zoom_in`/`zoom_out`), `range_days`.
4. Transition Guard: Umschalten erst, wenn $\text{now}() - transition\_started\_at \ge \frac{CROSSFADE\_DURATION\_MS}{1000.0}$; nach Umschaltung `last_transition_at` aktualisieren.
5. Telemetrie-Log je Kaskaden-Event: `(trigger, from_tf, to_tf, range_days)`.
6. Hysterese: Zwischen 2.0 d und 3.5 d ist der Zustand stabil (kein Wechsel) – verhindert Oszillation.

## ✅ Headless-Verifikation

- Test 1 (Hysterese-Boundary): 1.99 d → M1, 2.01 d → kein Wechsel, 3.49 d → kein Wechsel, 3.51 d → H1.
- Test 2 (Anti-Oszillation): 20× Oszillation im Fenster [1.9 d, 3.6 d] → `transition_started_at` garantiert fehlerfreies Schalten.

---

# 21.03.04 – Confluence-Gewichtung & Normalisierung

## 🎯 Ziel

Gewichtete Confluence-Scores mit vollständigem Gewichtungs-Schema, Min-Max-Normalisierung, Constant-Matrix-Policy und Volatilitäts-Adaption (§4 Säule 1.4).

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_confluence.py` – Score-Berechnung (reine Logik).
- **Geändert:** `test/test.py` (Test 5).

## 🛠️ Umsetzungsschritte

1. Gewichte: $W_{\text{D1}} = 3.0$, $W_{\text{H4}} = 2.5$, $W_{\text{H1}} = 2.0$, $W_{\text{M15/M30}} = 1.5$, $W_{\text{M5}} = 1.2$, $W_{\text{M1}} = 1.0$.
2. $Score_j = \sum (W_{TF} \cdot Signal_{TF})$ – un-normalisiert.
3. Min-Max-Skalierung auf $[0.0, 1.0]$; **Constant-Matrix-Policy:** $\text{max\_score} == \text{min\_score}$ → $\text{normalized\_score} = 0.5$ (keine Division durch Null).
4. Volatilitäts-Adaption (Toggle): $ratio = \text{clamp}(\frac{\text{ATR}_{\text{TF}}}{\text{ATR}_{\text{Current}}}, 0.2, 5.0)$; bei $\text{ATR}_{\text{Current}} \le 10^{-6}$ → $ratio = 1.0$ (deaktiviert).

## ✅ Headless-Verifikation

- Test 5: flache Matrix liefert 0.5; $W_{\text{D1}}=3.0$ behält vor der Min-Max-Skalierung die proportionale Übermacht.

---

# 21.03.05 – State-Machine & Prioritäts-Kette (Guards & Override)

## 🎯 Ziel

Umsetzung der Zustandstabelle (§3.1) und der Prioritäts-Kette (§3.2): Hard Data Availability Guard, Temporary User Override, Fixed Data-TF Guard, Auto Cascade, Visual Preference.

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_guards.py` – Prioritaäts-Kette (reine Logik).
- **Geändert:** `test/test.py` (Test 4).

## 🛠️ Umsetzungsschritte

1. `apply_priority_chain(data_tf, requested_chart_tf, cascade_state, override)` → effektiver Chart-TF.
2. **Ebene 1 – Hard Data Availability Guard:** aus 21.03.02 (`evaluate_coverage`); bei `fallback` wird der nächst-höhere TF erzwungen.
3. **Ebene 2 – Temporary User Override (Geister-Marker Klick):** Transaktions-Semantik:
   - `override.active = True`, `override.previous_data_tf` (z. B. `"M15"`), `override.target_tf` (z. B. `"D1"`), `override.reason = "ghost_marker_click"`.
   - Badge `[ 🌐 Data-TF temporär gelockert auf D1 | Reset ]`; **Reset** stellt exakt `previous_data_tf` wieder her.
4. **Ebene 3 – Fixed Data-TF Guard:** ohne Override ist das Chart-TF ≤ Data-TF (z. B. M15-Fix → max. M15); D1-Upgrade gesperrt.
5. **Ebene 4 – Auto Cascade:** aus 21.03.03 (`evaluate_cascade`).
6. **Ebene 5 – Visual Rendering Preference:** Farbschemata/Labels (UI, 21.03.09).
7. Inkongruenz-Warnung: Manuelles D1 bei M15-Fix → *"D1-Kerzen nicht möglich, da Data-TF auf M15 fixiert. Kerzen auf M15 gesetzt."*

## ✅ Headless-Verifikation

- Test 4: Fixiert `Data-TF = M15`, simulierter Klick auf D1-Geister-Marker → `previous_data_tf = "M15"`; nach `Reset` korrekte Wiederherstellung.

---

# 21.03.06 – Event-Partitionierung & Cache-Invalidierung (Late-Arriving Ticks)

## 🎯 Ziel

Partitionierte RAM-Cache-Invalidierung: $affected\_partition = partition(symbol, timeframe, t_{event})$ – nachträglich eingehende Ticks invalidieren nur ihre eigene Zeit-Partition, nie den gesamten Cache (§4 Säule 2.3).

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_partition.py` – Partitionierung + Invalidierung (reine Logik).
- **Geändert:** `test/test.py` (Test 6).

## 🛠️ Umsetzungsschritte

1. `partition(symbol, timeframe, ts)` → Partitions-Schlüssel (z. B. Wanduhr-Datum der Event-Zeit, Invariante 7).
2. `invalidate_partition(cache, symbol, timeframe, t_event)`: entfernt ausschließlich den Eintrag der eigenen Event-Zeit-Partition; alle übrigen Partitions-Einträge bleiben unangetastet.
3. Integration mit der Cache-Versionierung aus 21.03.01: nach Invalidierung wird `cache_generation` inkrementiert.

## ✅ Headless-Verifikation

- Test 6: historischer Tick ($t_{event}$ = vor 5 Tagen) → exakt die betroffene Zeit-Partition wird invalidiert, alle anderen bleiben bestehen.

---

# 21.03.07 – MtfFilterBarWidget & Control-Panel (UI)

## 🎯 Ziel

Filterleiste mit Source-Data-TF, Chart-Overlay-TF, Range-Picker, View-Templates (über `SchemaMigrator`), Tabellen-Sortierung und Session-Filter (§4 Säule 1). MVVM: **keine SQL-Queries in der UI** (Grundsatz 4).

## 📁 Dateien

- **Neu:** `chart/widgets/mtf_filter_bar.py` – `MtfFilterBarWidget` (QWidget, reines Event-Handling/Rendering).
- **Neu:** `analytics/engine/mtf_fc_templates.py` – View-Template-Persistenz via `SchemaMigrator` (Payload-Key `mtf_fc_schema_version = "1.0.0"`, in-memory, abwärtskompatibel).
- **Geändert:** `chart/chart_win.py` (Integration der Filterleiste), `analytics/ui/analytics_win.py` (Tabellen-Sortierung, falls betroffen).

## 🛠️ Umsetzungsschritte

1. Steuerungselemente:
   - **Source-Data-TF:** `🌐 Alle Timeframes` (Multi) vs. `🔒 Fixiert auf [TF]`.
   - **Chart-Overlay-TF:** `⚡ Auto (Kaskade)` vs. `🔒 Manuell Fix`.
   - **Range-Picker:** Presets (`24h`, `7d`, `30d`, `YTD`) & Benutzerdefiniert.
   - **Tabellen-Sortierung:** Dropdown `[ Datum 🢇 ]`, `[ Signal-Stärke 🢇 ]`, `[ TF 🡅 ]`.
2. View-Templates: Speichern/Laden kompletter Filter-Konfigurationen über den bestehenden `SchemaMigrator` (migriert fehlende/veraltete TFs und Session-Keys in-memory; Rollback-Schutz bleibt).
3. Session-Filter & DST-Normalisierung: London/NY/Tokio als Farbbalken (nur M1/M5-Zoom); Session-Grenzen strikt als **UTC-Epochs** berechnet, Formatierung erst beim Rendern (Invariante 7).
4. EventBus-Anbindung (`favorites_changed`, `profile_changed`, `service_set_changed`) statt direkter Orchestrator-Referenzen (Grundsatz 5).
5. Zustand: UI liest/schreibt `shared_state["mtf_fc"]` ausschließlich über den Provider (21.03.01).

## ✅ Headless-Verifikation

- `py_compile` aller neuen/geänderten Dateien; Code-Inspektion (kein SQL, keine DB-Connects in der UI, EventBus-Entkopplung).

---

# 21.03.08 – Chart-Integration: Kaskade, Puls-Breadcrumb & Historien-Anzeige

## 🎯 Ziel

Anbindung der Kaskaden-Engine an die PyLWC-Zoom-Interaktion, Puls-Breadcrumb und transparente Historien-Anzeige mit Boundary Policy (§4 Säule 2.1/2.2 + Säule 1.3).

## 📁 Dateien

- **Neu:** `chart/js/07_mtf_fc.js` – Zoom-Hook auf `visibleRangeChanged`, Kaskaden-Trigger, Puls-Breadcrumb, Boundary-UI.
- **Geändert:** `chart/js/04_live_updates.js` (optionaler Hook-Aufruf, Muster `06_two_tier.js`), `chart/chart_win.py` (Kaskaden-Umschaltung + `tf_combo`-Sync), `chart/chart_basics.py` (`JS_FILES`-Liste erweitern).

## 🛠️ Umsetzungsschritte

1. JS-Hook: bei `visibleRangeChanged` wird `range_days` an Python übergeben (`pyBridge.onViewportChanged`); Python ruft `evaluate_cascade()` (21.03.03) auf und liefert `{current_tf, candidate_tf}` zurück.
2. `chart_win.py`: bei Kaskaden-Wechsel `current_tf` umschalten und `tf_combo` synchronisieren (Konsistenz mit bestehender TF-Auswahl, `on_tf_changed`); Transition Guard über `transition_started_at` (CROSSFADE 250 ms).
3. Puls-Breadcrumb: transparenter Badge `[ ⚡ Kerzen: M5 ]` oben rechts im Canvas; leuchtet bei Umschaltung kurz hellblau auf.
4. Boundary-UI: Anzeigeelement `ℹ️ M1 verfügbar ab DD.MM.JJJJ` (aus 21.03.02); bei `coverage_status = "fallback"` H1-Kerzen mit Schraffur *"Keine M1-Rohdaten für diesen Zeitraum"* (keine Lücke, kein Absturz).
5. Telemetrie: jedes Kaskaden-Event loggt `(trigger, from_tf, to_tf, range_days)`.

## ✅ Headless-Verifikation

- `node --check` auf neuen/geänderten JS-Dateien; `py_compile` auf Python-Dateien; Code-Inspektion (keine UI-Ausführung).

---

# 21.03.09 – Interaktives Layering: TF-Badges & Geister-Marker

## 🎯 Ziel

Interaktive TF-Badges (Klick = Filter, Strg+Klick = Multi-Select) und Geister-Marker mit Guard-Override und Viewport-Animation (§4 Säule 3).

## 📁 Dateien

- **Neu:** `chart/js/08_mtf_layers.js` – Badges, Geister-Marker, sanfte Viewport-Animation.
- **Geändert:** `chart/chart_win.py` (Guard-Override-Trigger über 21.03.05), `chart/js/03_chart_rendering.js` (Ghost-Pfeil am Viewport-Rand), `chart/chart_basics.py` (`JS_FILES`).

## 🛠️ Umsetzungsschritte

1. Interaktive TF-Badges (z. B. `[ H4-Swing ]`): Klick filtert die aktuelle Ansicht synchron auf diesen Timeframe; Strg+Klick = Multi-Select.
2. Geister-Marker (Off-Screen Level): übergeordnete Level außerhalb des Zoom-Blicks als verblasster Pfeil am Viewport-Rand: `▲ D1-Widerstand (27.85)`.
3. Klick auf einen Geister-Marker → Ebene-2-Guard-Override (21.03.05) auslösen und den Viewport sanft zum Ziel-Level animieren.
4. Reset-Badge `[ 🌐 Data-TF gelockert ]`: Klick auf *Reset* stellt `previous_data_tf` exakt wieder her und deaktiviert den Override.

## ✅ Headless-Verifikation

- `node --check` auf neuen/geänderten JS-Dateien; `py_compile` auf Python-Dateien; Code-Inspektion (kein SQL in UI, Entkopplung über EventBus).

---

# 21.03.10 – Abschluss: Integrationstest & Cleanup

## 🎯 Ziel

Service-Failure-Degradation-Integrationstest (§7 Test 7) sowie Gesamtlauf aller Tests und Cleanup von `test/` (Grundsatz 10).

## 📁 Dateien

- **Geändert:** `test/test.py` (Test 7).

## 🛠️ Umsetzungsschritte

1. Test 7 (Service-Failure-Degradation): drei aufeinanderfolgende Fehler von Service A → RAM-Quarantäne; Service B läuft weiter; Service C meldet `dependency_failed`; der alte `shared_state` bleibt erhalten; `reset()` hebt die Quarantäne auf. Basis: bestehendes `execute_set_resilient()` in `set_evaluator.py` – kein Umbau der Engine nötig.
2. Alle 7 Tests aus §7 in `test/test.py` ausführen (headless, kein `QApplication.exec()`, Grundsatz 2).
3. Cleanup: temporäre Test-Skripte und `*.duckdb`-Dateien aus `test/` entfernen – es verbleibt nur der Harness `test/test.py` (Grundsatz 10).
4. Implementierungs-Log: Einträge je 21.03.xx in `docs/AKTUELLE_UMSETZUNG.md` nach Bestätigung des Anwenders (Taxonomie 21.03, Format MD).

## ✅ Headless-Verifikation

- Gesamtlauf `test/test.py` (alle Checks PASS); `test/`-Inhalt = nur `test.py`.

---

# 21.04 Multi-DB Architecture & Data Management
## Strategy: Domain-Driven Split via DuckDB
Split storage into 4 isolated `.db` files to prevent file-locking, maximize IOPS, and isolate test data. Native cross-DB joins via `ATTACH DATABASE`.
## DB Schema Split
1. `master_config.db` (Lightweight): Mastertree hierarchy, service configs, parameter presets, instance hashes, archive text logs.
2. `market_data.db` (Static Read-Only): Raw OHLCV (M1-Daily), tick histories, L2 DOM snapshots.
3. `analytics_runs.db` (High-Volume Dynamic): Generated signals, sweep results, metrics, heatmap densities. Targeted by "Delete Data Only".
4. `ml_feature_store.db` (ML Optimized): Fractional diffs, Z-scores, Garman-Klass vols, trained probability matrices.
## Text Architecture: 20.05
                   [PyTrader Core / Execution Engine]
                                   │
      ┌────────────────┬───────────┴───────────┬────────────────┐
      ▼                ▼                       ▼                ▼
┌──────────────┐┌──────────────┐       ┌──────────────┐ ┌──────────────┐
│ market_data  ││master_config │       │analytics_runs│ │ml_feature_st │
│     .db      ││     .db      │       │     .db      │ │     .db      │
└──────────────┘└──────────────┘       └──────────────┘ └──────────────┘
 (OHLCV/Ticks)  (Tree/Configs/          (Signals/Sweeps/ (ML Features/
                 Archive Logs)           Data Clear)      Prob-Matrices)

