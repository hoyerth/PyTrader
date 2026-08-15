# Phase 21: Fachliche Feinabstimmung Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 21)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase10_step1`, `phase21_step1` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `../../test`.
3. **Codebase-Formatierung:** Exakt **4 Leerzeichen** Einrückung (PEP8-Standard) und **exakt 1 Leerzeile** Spacing zwischen Methoden und Funktionsblöcken. Kein Umformatieren unbeteiligter Altbestand-Dateien.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`. `MasterTree`-Selektionen übergeben aufgelöste `feature_ids` sowie `instance_hashes` direkt an `view_model.set_feature_ids(ids, hashes)`.
5. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db/db_pool.py`) – eine Verbindung pro Thread und DB-Datei. Die Fassade `../../db_service.py` bleibt als Re-Export-Wrapper für bestehende Caller erhalten.
7. **Tree-Persistenz & Kategorisierung:** 
   - Service-Kategorien werden primär im Code/Plugin über `metadata["category"]` (Slash-separierter Ordnerpfad) deklariert.
   - Ordner-Kategorien für Service-Sets werden im `category`-Feld der `ServiceSetDefinition` / des `save_set()`-Payloads persistiert.
   - Parameter-Varianten (Clones/Presets) werden transparent über `indicator_presets` und `instance_hash` im FeatureStore geführt.
8. **Wanduhr-Garantie (Invariante 7):** MT5-Epochs sind bereits Berlin-Wanduhr-encoded. SQL-Extraktionen (Heatmap, DOW, Hour, Date) nutzen strikt `bar_time AT TIME ZONE 'UTC'`, um eine fehlerhafte automatische Umrechnung durch DuckDB in Lokalzeiten zu unterbinden.
9. **Concurrency-Guard & Timer-Pausierung:** Solange im ServiceWindow intensive Service-Berechnungen laufen (`ServiceRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
10. **Isolierter Test-Workspace & Cleanup:** Neue Test-Skripte und temporäre `*.duckdb`-Dateien gehören strikt nach `../../test`. Nach Abschluss jedes Phasenkapitels wird `../../test` aufgeräumt – es verbleibt nur der Test-Harness `../../test/test.py`.
11. **Open/Closed-Principle & Code-Preserving:** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden; bestehende Kern-Klassen bleiben geschützt.
12. **Naming Conventions & PineScript-Input-Zone:** 
    - Services in `../../analytics/features/definitions` nutzen strikt das Präfix `srv_` (`plugin_id = "srv_..."`).
    - Indikatoren in `../../chart/indicators` nutzen strikt das Präfix `ind_` (`indicator_id = "ind_..."`).
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

### Schritt 1: Backend- & SQL-Filter-Fix (`../../analytics/engine/feature_store_reader.py`)

> **Status: BEREITS UMGESETZT** in Phase 20 (Runde 16/16c, 11.08.2026) – keine neue Arbeit, nur Verifikation im 21.01-Test.

* **1.1 Mischauswahlsicherer SQL-Filter (`_apply_feature_filter`) – erledigt:**
`_apply_feature_filter` nutzt bereits die Disjunktion (Stand Runde 10/16):

# (LOWER(TRIM(feature_id)) IN (ids) AND (instance_hash IS NULL OR LOWER(TRIM(instance_hash)) IN (hashes)))

Der Guard greift nur noch bei Varianten MIT Hash (`if active_hashes and h_s and ...`); hash-lose Standalone-Services passieren die Varianten-Einschränkung immer.

* **1.2 Entkopplung der Standalone-NoData-Prüfung (`resolve_no_data_variants`) – erledigt:**
Der alte Guard `if not active_hashes:` um den Standalone-Block ist entfernt. Runde 16 (11.08.2026): Standalone-Services (`h_s=""`) werden von einer aktiven Hash-Auswahl anderer Services nicht mehr verworfen und erscheinen korrekt als `(No Data)`, solange der feature_store keine Rows ihrer plugin_id besitzt.


### Schritt 2: Colormap-Rendering Fix (`../../analytics/ui/heatmap_widget.py`)

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


### Schritt 3: ViewModel-Erweiterung & Smart-Presets (`../../analytics/engine/analytics_view_model.py`)

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


### Schritt 4: UI-Layout & Header-Redesign (`../../analytics/ui/analytics_win.py` / `heatmap_page.py`)

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

## 📊 4. Akzeptanzkriterien für die Headless-Validierung (`../../test/test.py`)

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

* **11.08.2026 – 21.01 Umsetzung (Coding, E1–E6):** Alle 7 Dateien umgesetzt und per `../../test/test.py` verifiziert (Sektion 39, 31 Checks AK1–AK7/Presets/Namensgenerator/Widget/Page – alle PASS; keine neuen Fehler gegenüber der 25er-Baseline aus Teil 1/25/32/35/36/37/20.03). Änderungen: `feature_store_reader.py` (`fetch_generic_heatmap` + `all_timeframes`, Guard ohne TF-Freigabe), `analytics_repository.py` / `analytics_worker.py` (Parameter-Durchreichung, QUERY ohne `LOWER(timeframe)=` bei `all_timeframes=True`), `analytics_view_model.py` (`heatmap_all_timeframes`, `apply_smart_preset_*`, `generate_profile_name_suggestion()` deutsch inkl. Fallbacks `(Alle Services)`/`ALLE`, Persistenz unter `charts.heatmap.all_timeframes`), `heatmap_widget.py` (Signal `preset_clicked` + 4 Preset-Buttons in `ctrl`), `heatmap_page.py` (generischer Modus als Standard-Ansicht), `analytics_win.py` (Header-Redesign E5: `combo_profile` dehnbar/editierbar, Namens-/Beschreibungs-Felder in separatem Speicher-Dialog, `_resolve_save_name`-Helfer gegen '?'-Verlust, Auto-Name im Neu-Dialog). Test 35 Z2b/Z2c an E5-Kontrakt angepasst (kein Header-Namensfeld mehr; `_resolve_save_name` direkt getestet).

* **11.08.2026 – Bugfix-Runde 21.01 User-Meldungen 1–7 (Coding, Commit `28249a2`):** Meldung 1 (Profil-Neu-Dialog breit, QDialog min. 560 px, `combo_profile` min. 560 px), Meldung 2 (Ansicht-Dropdown = Generisch + 4 Presets, „Wochentag × Stunde“ entfernt, Legacy-`standard`→`generic`-Mapping), Meldung 3 (Bedien-Controls bleiben bei jedem Preset-Wechsel sichtbar, Stack immer Seite 1, `_apply_selected_preset()`), Meldung 4/6 (Stale-Combo-Fix: Preset-Handler synchronisieren Combos via `_sync_from_params()`/`_update_controls()`), Meldung 5 (Kerzen-Overlay nur bei X=date, Restore-Guard `heatmap_x_dim == "date"`), Meldung 7 (Confluence-Levels daten-gebunden `(vmin, vmax)` statt fest `(0, 5)`). Verifikation: `test/check_heatmap_2101.py` (10/10 OK, headless). **Noch nicht vom Anwender als funktionierend bestätigt** – die Screenshot-Kritik (E7–E10) schließt direkt an.
* **11.08.2026 – Heatmap-Darstellung Screenshot-Kritik (Analyse, KEIN Coding):** Anweisung des Anwenders: „Bugfixing – 4 Preset-Buttons entfernen (jetzt im Dropdown) / Kritik prüfen + Fix erstellen / erst Meinung + Doku, dann warten auf Befehl“. Analyse-Ergebnisse: **(1)** Y-Streifen = reale Transposition (`axisOrder='col-major'`, empirisch via `test/check_orientation_2101.py`: `width()==2/height()==3` bei 2×3-Matrix) → Fix E8 `axisOrder='row-major'`. **(2)** Homogene X-Achse = Symptom der Transposition, kein SQL-Fehler (E9). **(3)** „Farbe = Y-Position“ = visuelle Täuschung, Farben daten-gebunden (E10). **Fixes E7 (Buttons entfernen) + E8 (`axisOrder='row-major'`) wurden vom Anwender freigegeben und umgesetzt – Umsetzung + Verifikation siehe nächster Log-Eintrag.**
* **11.08.2026 – E7/E8 Umsetzung (Coding):** Anweisung „continue“ nach Freigabe. **E7:** Die 4 Preset-Buttons im `HeatmapWidget` (`_btn_preset_confluence/session/intensity/timeframe`) samt Handlern `_on_preset_*` und Signal-Verbindungen ENTFERNT – die Smart-Presets laufen ausschließlich über das „Ansicht“-Dropdown der `HeatmapPage` (`_apply_selected_preset`). Das Signal `preset_clicked` bleibt als Vertrag, wird aber nicht mehr emittiert; die Page konsumiert es nicht mehr (`attach_view_model`-Verbindung + `_on_preset_clicked` entfernt). **E8:** `self._image.setOpts(axisOrder='row-major')` – behebt die Transposition der `(rows=Services, cols=Zeiten)`-Matrix (pyqtgraph-Default `col-major` rendert transponiert → die N dünnen Y-Streifen der Kritik). Verifikation (headless, venv): `test/check_heatmap_2101.py` 12/12 OK (inkl. neuer E7/E8-Checks), `test/check_orientation_2101.py` `width()==3/height()==2` statt vorher `2/3`, `py_compile` aller geänderten Dateien OK, `../../test/test.py` Sektion 39 (j1/j2 E7/E8, k1 Page konsumiert Signal nicht mehr) angepasst. Offener Verifikationspunkt geklärt: kategoriale Y-Achsen-Ticks (Services) liegen nach row-major exakt auf den Zeilen-Mitten (0,1,2 ↔ Zellen [-0.5..2.5]). **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „doku“, 11.08.2026).
* **11.08.2026 – Bugfix-Runde 2 Heatmap-Darstellung (Coding, 5 Bugs, nur `../../analytics/ui/heatmap_widget.py`, +231/−57):** (1) Kategoriales Achsen-Clamping – Ticks außerhalb `0..n−1` entfallen (`_clamped_scale_bounds`, `_format` → leere Strings). (2) Schwellwert-Legende (`pg.LegendItem` oben rechts) + `0`-Confluence-Farbe Grau `#d9d9d9`. (3) Fadenkreuz (`_cross_x`/`_cross_y` als `pg.InfiniteLine`, zValue 20) + `_on_mouse_moved` + `_update_cell_info`. (4) Datumsformate 1:1 JS-Konvention (`TT.MM.JJ` / `HH:MM`). (5) Adaptives Overlay: `QUERY_OHLCV` statt Daily-Query, `_TF_SECONDS`-Map, `_bar_interval_seconds()`. Verifikation: `test/check_heatmap_2101.py` 20/20 + Smoke-Test 7/7 (headless, venv). **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „doku“, 11.08.2026).
* **11.08.2026 – Bugfix-Runde 3 Heatmap-Darstellung (Coding, 4 Punkte, User „doku alles und setze deine Vorschläge um“):** E11 (Overlay batched: 3 `pg.BarGraphItem`, numpy), E12 (senkrechte Teiler je Dateneinheit, Variante a: `_grid_lines` als `PlotCurveItem(connect="pairs")` + `_update_grid_lines()`), E13 (Tages-Marken `Mo. 12.06.26`), E14 (Zelleninfo-Zeitzeile `Zeit: Mo. 12.06.26 14:00 · Zelle(row,col) = Wert`). Nachgereicht: `bar_sec = self._bar_interval_seconds()` im batched-Overlay-Block (der Runde-2-Patch hatte die Zeile zusammen mit dem alten Loop ersetzt). Verifikation: `test/check_heatmap_2101.py` 22/22 OK (headless, venv), `py_compile` von `heatmap_widget.py` + `test.py` OK. **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „doku“, 11.08.2026).

* **11.08.2026 – Bugfix-/Spez-Analyse 21.01 + 21.01b (Analyse, KEIN Coding, Anweisung „bugfix mode – prüfe, Ergebnisse als Textblock, kein Coding“):** Vier User-Meldungen geprüft und headless verifiziert (Wegwerf-DB in `../../test`, danach wieder entfernt): **(1) Fadenkreuz-Zelleninfo** funktioniert mechanisch (row/col-Mapping ohne Flip, Wanduhr-Konvertierung), hat aber einen echten off-by-one-day-Bug: Tageszellen sind mittags-zentriert (`_axis_bounds`: `lo−12 h … hi+12 h`) → Cursor 12:00–24:00 zeigt den Wert der Folgetag-Zelle; außerhalb des Datenbereichs bleibt das alte Label stehen. **(2) Mehrzeilen-Umbruch** am `/` ist machbar – pyqtgraph 0.14 misst/rendert `\n`-Tick-Labels korrekt. **(3) „Datum im Baum bleibt stehen“ auf neuem TF:** DB-Schicht korrekt (PK `(symbol, timeframe, bar_time, feature_id)` trennt TFs; `fetch_last_execution_dates` liefert sofort das neue Datum) – Root Cause in `run_worker.py`: `event_bus.service_set_changed` wird NUR bei vollem Erfolg emittiert; alle Fehlerpfade (`no_data_tfs`, `no_payload_tfs`, Exception im Single-TF-Zweig) überspringen den Refresh, obwohl Rows geschrieben wurden. **(4) Service-Picker** hat keinen TF-Selektor (nur `ServiceWindow.combo_tf`, U15-E); Heatmap-Preset „Service-Timeframe“ sortiert die TFs alphabetisch statt nach Dauer. Spez-Bausteine `fetch_service_tf_status`, `TfStatusBadgeBar`, `../../serviceui/common_widgets.py`, per-TF-Worker-Signale existieren nicht. Entscheidungen E15–E18 (§5) dokumentiert – **Umsetzung erst nach explizitem Befehl**.

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

### Schritt 1: DB-Status-Methode (`../../analytics/engine/feature_store_reader.py`)

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

### Schritt 2: Mini-Pill-Strip Widget (`../../serviceui/common_widgets.py` – NEUE Datei)

* **2.1 `TfStatusBadgeBar`-Klasse erstellen:**
* `QWidget` mit `QHBoxLayout` (Spacing 2, Margins 0).
* Ein `QLabel` je TF (feste Größe ~28 × 16 px, Font 9 pt bold, `border-radius: 3px`).
* `update_status(tf_status_map: Dict[str, Dict[str, Any]])`: färbt Badges grün/grau (E18b: dynamische TF-Liste aus dem Status-Map, sortiert nach `TF_SECONDS_MAP`) und setzt den `setToolTip()` (z. B. `M1: 10.000 Einträge\nZuletzt: 11.08.26 20:15`).
* `set_running(tf)`/`set_error(tf)`: Blau-Blinken (QTimer) bzw. Rot (Schritt 3.2).

### Schritt 3: Multi-TF-Ausführung Toolbar (`../../serviceui/service_win.py` / `service_selector_dialog.py`)

* **3.1 ComboBox `combo_run_tf`:** `[ Aktueller TF ]` + `[ 🌐 Alle Timeframes ]`. Im `ServiceWindow` ist das bestehende `combo_tf` (U15-E, Index 0 = `ALL_TIMEFRAMES`) die Grundlage; der `ServiceSelectorDialog` erhält zusätzlich eine TF-Zeile (E18d).
* **3.2 Per-TF-Fortschrittssignale im `ServiceRunWorker`:** neue Signale `tf_started(str)` / `tf_finished(str, int, bool)` – der Orchestrator setzt das jeweilige Badge auf „berechnet gerade“ (blau blinkend) bzw. grün (Rows geschrieben) / rot (Fehler).

### Schritt 4: UI-Integration & Event-Update

* **4.1 Einbettung:** `TfStatusBadgeBar` als Spalten-Widget in `MasterTree`/`ServiceWindow` sowie in den `ServiceSelectorDialog` (E18d).
* **4.2 Signal-Kopplung:** Badges nach jedem `run_finished`/`run_failed` aktualisieren. **Voraussetzung ist E17** (EventBus-Refresh auch bei Teilerfolg/Fehler), damit der Status nach jedem Run korrekt neu gelesen wird.

---

## 📊 3. Akzeptanzkriterien für die Headless-Validierung (`../../test/test.py`)

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
  * **21.01b Schritt 2 (NEUE Datei `../../serviceui/common_widgets.py`):** Widget `TfStatusBadgeBar` (QHBoxLayout, Spacing 2, QLabel je TF 28×16 px, 9 pt bold, Radius 3 px; `update_status(map)`, `set_running(tf|None)`, `set_error(tf)`, `clear_error`, `clear`; Tooltip `M1: 99.063 Eintraege\nZuletzt: 11.08.26 20:15`; Farben: idle/running/error/hint).
  * **21.01b Schritt 3+4 (Einbettung + Kopplung):**
    * `service_win.py`: `TfStatusBadgeBar` am Kopf der Parameter-/Status-Spalte; Worker-Signale `tf_started`/`tf_finished` gekoppelt (`_on_tf_started`/`_on_tf_finished`), nach `run_finished`/`run_failed` Refresh via `_refresh_badge_bar()`; `_on_master_selection_details` lädt die Pills für die geklickte Zeile (`_resolve_badge_plugin`). Run nutzt weiterhin das bestehende `combo_tf` (Index 0 = `ALL_TIMEFRAMES`).
    * `service_selector_dialog.py`: NEUE TF-Zeile `combo_run_tf` (Sentinel `ALL_TIMEFRAMES` + TFs aufsteigend) + `TfStatusBadgeBar` im Parameter-Panel; MasterTree-Run-Aktionen (`run_service/set/plugin/category_requested`) verdrahtet (User-Entscheid: Run im Picker voll funktional) – Bestätigungsdialog, `_plugin_config` (17.01.04-Muster), `ServiceRunWorker` mit `_run_symbol()` (Parent `combo_symbol`) und `_run_timeframe()`; Pill-Strip-Kopplung identisch zum ServiceWindow.
    * `analytics_win.py`: `TfStatusBadgeBar` NEBEN der Datenquellen-Combo (Filter-Zeile); `_refresh_badge_bar()` zeigt die TFs der ERSTEN aktiven Datenquelle (`feature_ids[0]`), Sync über `_sync_service_filter_button`.
  * **Verifikation (headless, KEIN UI-/Regressionstest):** `py_compile` auf allen 7 geänderten Dateien (OK); `test/check_2101b.py` 18/18 PASS (DB-Status-Query, Badge-Mapping inkl. Tooltip/running/error/laufender TF ohne DB-Eintrag, Multi-TF-Loop sortiert nach `TF_SECONDS_MAP`, Sentinel, Worker-Signale, E17-Code-Inspection, Modul-Import-Smoke).
* **11.08.2026 – Bugfix Varianten-Kollision Runde 4 + 5 (Coding, Commits `6910b46` + `3d67539`):** User-Meldung „Kontextmenü auf eine Variante → wird bei allen Varianten ausgeführt/angezeigt" + „Data only löschen muss das letzte Ausführungsdatum im Baum wieder auf null reseten (wie frisch angelegt)".
  * **Runde 4 (`6910b46`, Root Cause: Hash-Kollision):** `generate_instance_hash(plugin_id, params, preset_name)` – Preset-Hashes jetzt INKL. `preset_name` (Backward-Compat ohne). Presets mit identischen Params aber unterschiedlichen Namen (z. B. `srv_trend_breakout`: `ffffffff`/`ggsegerttt`, vorher beide `3399e1bc`; `srv_trend_hma_pivot`: 3× `2d9f343a`) erhalten UNTERSCHIEDLICHE Hashes → der Kontextmenü-Run-Filter matcht GENAU EINE Variante. feature_store-PK idempotent migriert auf `(symbol, timeframe, bar_time, feature_id, instance_hash)` (Table-Rewrite + `ALTER ADD PRIMARY KEY`, `COALESCE(NULL→'')`, auf `../../data/analytics.duckdb` ausgeführt, 2,33 Mio. Rows erhalten); Writer nutzen adaptiven `_feature_store_conflict_target(con)` (5-/4-Spalten je PK); Reader `_apply_feature_filter`: `instance_hash=''` bleibt bei Varianten-Filtern immer enthalten. MasterTree-Label-Kosmetik (`srv_`-Präfix abgeschnitten, Fallback `(nie)`).
  * **Runde 5 (`3d67539`, die zwei verbliebenen User-Punkte):**
    * **Bug 1 („bei allen Varianten ANGEZEIGT"):** Der Run-Filter matchte seit Runde 4 korrekt genau 1 Variante – der Anzeige-Leak war der **Legacy-Fallback im `ServiceSelectorModel`** (`per_hash.get(new) or per_hash.get(legacy)`): Alt-Rows unter dem kollidierenden Params-only-Hash (Pool) wurden an ALLEN Varianten als Ausführungsdatum angezeigt. Fix: Fallback + `_preset_hash_aliases` VOLLSTÄNDIG entfernt – `_load_plugin_presets`, `last_execution_date_for_hash`, `last_execution_datetime_for_hash` lesen NUR den EIGENEN Preset-Hash; nie gelaufene Varianten zeigen `--.--.--` („nie" wie frisch angelegt).
    * **Bug 2 („Data only löschen resetet das Datum nicht"):** `purge_instance_data(instance_hash)` löschte nur Rows unter dem NEUEN Hash; die Alt-Daten (z. B. 676 689 Rows von `srv_swing_volume_profile` unter dem Legacy-Hash) blieben liegen und das Datum blieb über den Fallback stehen. Fix: Signatur erweitert auf `purge_instance_data(instance_hash, plugin_id="", params=None)` – löscht zusätzlich die LEGACY-Pool-Rows der Variante (`feature_id = plugin_id AND instance_hash = generate_instance_hash(plugin_id, params)`); alle 6 Call-Sites erweitert (`service_win.py`: `_on_data_only_purge`/`_delete_complete_set_instance`/`_delete_complete_preset`; `service_selector_dialog.py`: `_on_data_only_purge`/`_on_delete_complete` ×2 – jeweils mit params-Lookup via Set-Config bzw. `_find_preset_for_hash`).
  * **Verifikation (headless, KEIN UI-/Regressionstest):** `py_compile` aller 4 geänderten Module; `test/check_variant_hash_fix.py` 18/18 (inkl. neuer Checks 3b „kein Legacy-Fallback" deterministisch via Fake-Reader, 3c/3d „Legacy-Purge mit/ohne params"), `test/check_variant_run.py` 11/11 (Test 5 self-contained: Store-Write mit Preset-Hash → Datum nur für DIESEN Hash), `test/check_2004_purge.py` 8/8 (Schema auf 5-Spalten-PK/`''`-Sentinel aktualisiert), `test/check_2101b.py` 18/18. Live-Check: alle Varianten zeigen „nie" trotz 676k Legacy-Rows im Store. **Vom Anwender als funktionierend bestätigt** (Freigabe per Anweisung „continue", 11.08.2026).


---
# 21.02 – DB Bloat Analysis & Maintenance (VACUUM)

## 🎯 1. Kern-Anforderungen

1. **Bloat-Analyse:** Startup-Anzeige auf `MainWindow` unter Optionen-Button via `PRAGMA database_size`.
2. **DB-Pflege beim App-Exit:** `../../main.py` `closeEvent` führt für jede DB-Datei `CHECKPOINT;` **gefolgt von** `VACUUM;` aus (WAL-Flush, konsistenter Zustand – keine Datei-Verkleinerung).
3. **Kompaktierung (Button):** Button `[ 🧹 DB Service ]` in `PropertiesWindow` führt die **`COPY FROM DATABASE`-Kompaktierung** aus (echte Verkleinerung, Bloat entfernen). **Nicht** `VACUUM`-Button.
4. **Concurrency-Guard:** Kompaktierung sperren, solange `_sync_pause_count > 0` (laufende Scans/Worker) – Zugriff über **EventBus-Zähler** (konsistent zu Phase 16, nicht `self.parent()`).

---

## 🛠️ 2. Schritt-für-Schritt Umsetzungsanleitung

### Schritt 1: Core Engine (`../../db/db_utils.py`)

Füge folgende Funktionen in `../../db/db_utils.py` ein (**korrigierte Fassung, Stand 12.08.2026** – F1: `res[2]/res[4]`, F2: CHECKPOINT+VACUUM, `copy_database`-Helper):

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

### Schritt 2: Startup Status (`../../main.py`)
Beim App-Start in `../../main.py` aufrufen und UI-Label unter Optionen-Button befüllen (absoluter Pfad via `BASE_DIR`):

# main.py
from db.db_utils import get_db_fragmentation_info

info = get_db_fragmentation_info(str(BASE_DIR / "data" / "analytics.duckdb"))
# UI-Label setzen (label_db_status – in ui/main_win.ui ergänzen oder per Code erzeugen)
self.label_db_status.setText(f"DB Status: {info['pct']}% fragmentiert ({info['bloat_mb']} MB frei)")

---

### Schritt 3: UI, Concurrency-Guard & Kompaktierung (`../../properties_win.py`)
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

## 📊 3. Akzeptanzkriterien (`../../test/test.py`)
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
| Schritt 1 | `get_db_fragmentation_info()` / `execute_db_vacuum()` in `../../db/db_utils.py` | ❌ nicht vorhanden (`db_utils.py`: nur `_ensure_epoch`/`_parse_json_field`) |
| Schritt 2 | Startup-Aufruf `../../main.py` + `label_db_status` | ❌ nicht vorhanden; Label existiert auch nicht in `../../ui/main_win.ui` |
| Schritt 3 | VACUUM-Button in `../../properties_win.py` + Guard | ❌ nicht vorhanden |
| AK 1–2 | Headless-Tests | ❌ nicht verifizierbar (Code fehlt) |

✅ Vorhanden als Grundlage: `_sync_pause_count` in `main.py:166` (Phase-16-EventBus-Guard, Signale `service_run_started`/`service_run_finished`).

### 4.3 Befunde der Konsistenz-/Korrektheits-Prüfung
- **K1 (Guard wirkungslos):** `PersistentWindow.__init__` übergibt **kein Qt-Parent** (`super().__init__()` ohne parent, Logik-Parent nur für `state_manager`) → `self.parent()` ist `None` → `getattr(self.parent(), "_sync_pause_count", 0)` greift **nie** (immer Default 0).
- **K2 (Label fehlt):** `label_db_status` existiert nicht in `../../ui/main_win.ui` (dort nur `status_label`); kein dedizierter Platz „unter dem Optionen-Button".
- **F1 (falscher PRAGMA-Spalten-Index):** `PRAGMA database_size` (DuckDB 1.5.5) liefert: `0 database_name, 1 database_size (VARCHAR), 2 block_size, 3 total_blocks, 4 used_blocks, 5 free_blocks, 6 wal_size, 7 memory_usage, 8 memory_limit`. Der Snippet nutzt `res[1], res[3]` = **`database_size` (String!)** + **`total_blocks`** → falsch.
- **F2 (VACUUM wirkungslos, empirisch belegt):** `INSERT 500k → DELETE → VACUUM;` sowie `CHECKPOINT;` ändern die Dateigröße **nicht** (0 % Reduktion); `PRAGMA database_size` vor/nach identisch. DuckDB 1.5.5 besitzt **kein echtes VACUUM** wie SQLite – das Ziel „Bloat reduzieren" ist mit `VACUUM;` nicht erreichbar. AK2 („verringert/konsolidiert Blöcke") ist damit nicht erfüllbar.

### 4.4 Entscheidungen (12.08.2026)
| Punkt | Entscheidung |
|---|---|
| **F1** (PRAGMA-Index) | ✅ **Bestätigt:** Korrektur auf `block_size, used_blocks = res[2], res[4]` |
| **K1** (Concurrency-Guard) | ✅ **Bestätigt:** Guard über `EventBus`-Zähler (konsistent zu Phase 16) statt `self.parent()` |
| **K2** (Status-Label) | ✅ **Bestätigt:** `label_db_status` wird ergänzt (in `../../ui/main_win.ui` oder per Code – Detail bei Umsetzung) |
| **F2** (VACUUM-Ziel) | ✅ **Entschieden:** Zweistufige Lösung – **CHECKPOINT + VACUUM beim App-Exit** (reguläre Pflege) + **COPY FROM DATABASE-Methode** (echte Kompaktierung). Siehe 4.6 |
| Umsetzung allgemein | ⏸️ **Zurückgestellt:** Kein Coding jetzt |

### 4.5 Ergänzungen (bei späterer Umsetzung zu beachten)
- `../../db/db_utils.py`: `import os` (für `get_db_fragmentation_info`) und `from pathlib import Path` (für `copy_database`) im Snippet ergänzt; `DbPool`-Import ist innerhalb des `db`-Pakets zulässig (Basis-Schicht E4 bleibt sonst ohne Projekt-Import).
- ✅ **Markdown-Artefakte `[cite: 1]` im Kapitel bereinigt** (12.08.2026, Abschnitte 2/3).
- ✅ **Umsetzungsplan nachgezogen** (12.08.2026): Schritt 1–3 + AK entsprechen jetzt der F2-Lösung (CHECKPOINT+VACUUM, COPY FROM DATABASE, EventBus-Guard, `res[2]/res[4]`).
- AK2-Formulierung folgt der F2-Lösung (siehe 4.6): `CHECKPOINT`/`VACUUM` allein verkleinern die Datei nicht – die **Kompaktierung** leistet `COPY FROM DATABASE`.

### 4.6 Lösungsweg F2: DB-Pflege beim App-Exit + Kompaktierung per COPY FROM DATABASE

**Beschluss (12.08.2026):** Die DB-Pflege wird zweistufig umgesetzt. Empirisch belegt (DuckDB 1.5.5): `VACUUM;` und `CHECKPOINT;` verkleinern die Datei **nicht** (0 % Reduktion, `PRAGMA database_size` unverändert). Die tatsächliche Kompaktierung leistet die **`COPY FROM DATABASE`-Methode**.

#### Stufe 1 – Beim Verlassen der App (regulär, `../../main.py` `closeEvent`)
Beim App-Exit wird für jede DuckDB-Datei ausgeführt:
```sql
CHECKPOINT;   -- WAL in Hauptdatei flushen (konsistenter Zustand)
VACUUM;       -- formale Defragmentierung (in DuckDB 1.5.5 ohne Dateigrößen-Effekt)
```
* Zweck: WAL wird aufgeräumt, die Datei in einen sauberen Zustand versetzt (kein WAL-Replay beim nächsten Start).
* Aufruf über `execute_db_vacuum(db_path)`-Erweiterung in `../../db/db_utils.py` (führt `CHECKPOINT;` **gefolgt von** `VACUUM;` aus).
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
* **⚠️ Windows File-Locking:** Der Datei-Ersatz (alte Datei löschen/umbenennen) funktioniert **nur**, wenn **alle offenen DbPool-Verbindungen** zu dieser DB geschlossen sind – sonst wirft Windows `PermissionError` (Datei in Verwendung). Ablauf: (1) `copy_database()` ausführen, (2) **DbPool-Verbindung schliessen/leeren** (Methode in `../../db/db_pool.py`), (3) alte Datei löschen, (4) kompakte Datei umbenennen, (5) DB neu öffnen. Kein laufender Scan/Worker darf zugreifen (Guard `_sync_pause_count == 0`).
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

**Ursache:** `../../chart/indicators/utils/ma_template.py`: `_sma_values`, `_wma_values`,
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
| `../../chart/indicators/utils/ma_template.py` | 4x Warmup-Guard (Serie < period -> NaN) |
| `../../analytics/features/feature_builder.py` | `purge_instance_data(..., purge_legacy=False)` |
| `../../serviceui/service_win.py` | `_purge_legacy_allowed` + purge_legacy + Progress-Reset |
| `../../serviceui/service_selector_dialog.py` | `_purge_legacy_allowed` + Progress-Bar + Reset |
| `../../analytics/ui/heatmap_widget.py` | `_format_heatmap_value` (2 NK), `_bar_interval_seconds(data_tf)`, Overlay-TF-Label |
| `../../test` | `check_hma_pivot_bug.py`, `check_purge_legacy.py`, `check_heatmap_format.py`, `check_overlay_tf_precedence.py` |

**Nicht angefasst:** 21.02-Working-Tree-Dateien (`../../db/db_utils.py`, `../../db/db_pool.py`,
`../../config/event_bus.py`, `../../main.py`, `../../properties_win.py`, `../../ui/main_win.ui`).

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
| `../../analytics/engine/feature_store_reader.py` | `fetch_service_tf_status(plugin_id, instance_hash=None)` - Varianten-Filter |
| `../../serviceui/service_win.py` | Progress-Bar determinate (Init + Reset); `_resolve_badge_scope` + `_refresh_badge_bar(pid, hash)` |
| `../../serviceui/service_selector_dialog.py` | Progress-Bar determinate (Init + Reset); `_resolve_badge_scope` + `_refresh_badge_bar(pid, hash)` |

**Nicht angefasst:** 21.02-Working-Tree-Dateien (`../../db/db_utils.py`, `../../db/db_pool.py`,
`../../config/event_bus.py`, `../../main.py`, `../../properties_win.py`, `../../ui/main_win.ui`).

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

* **View-Templates (Presets):** Speichern und Laden von kompletten Filter-Konfigurationen. Das `MtfFilterBarWidget` nutzt den bestehenden `SchemaMigrator` (`../../analytics/engine/schema_migrator.py`), um gespeicherte Preset-JSONs in-memory zu validieren und abwärtskompatibel um neue TFs/Session-Keys zu erweitern (Payload-Key `mtf_fc_schema_version = "1.0.0"`).
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

## 📊 7. Headless-Validierung (`../../test/test.py`)

Folgende Tests verifizieren das System in `../../test/test.py` ohne GUI-Ausführung:

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
6. **21.03.10:** Integrationstests laufen erst, wenn alle Bausteine stehen; danach Cleanup von `../../test` (Grundsatz 10).

---

# 21.03.01 – MTF-FC Data Provider & `shared_state`-Namespace (Schicht 2)

## 🎯 Ziel

Bereitstellung des dedizierten, isolierten Namespace `PluginContext.shared_state["mtf_fc"]` (Spezifikation §5) sowie des Datenzugriffs-Moduls mit Cache-Versionierung und Partitioned Reads. Grundlage für alle weiteren Schritte (Boundary, Kaskade, Guards, UI).

## 📁 Dateien

- **Neu:** `../../analytics/engine/mtf_fc_state.py` – Default-Factory/Struktur des `shared_state["mtf_fc"]`-Namespaces.
- **Neu:** `../../analytics/engine/mtf_fc_provider.py` – Cache-Versionierung `(symbol, timeframe, partition)` + `source_max_timestamp`, `get_earliest_timestamp(symbol, timeframe)`, gekapselte Reads über `fetch_daily_ohlc` / `fetch_ohlcv_snapshot` (read-only, DbPool).
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

- `../../test/test.py`: Namespace-Default-Struktur (alle Keys aus §5 vorhanden), `get_earliest_timestamp("SILVER", "M1")` ≈ 2013-06-05 (reale DB), Cache-Eintrag bildet `(symbol, timeframe, partition)` korrekt ab, stale-Erkennung bei veraltetem `source_max_timestamp`.

---

# 21.03.02 – Boundary Policy & Historien-Detection

## 🎯 Ziel

Präzise Ermittlung der M1-Verfügbarkeitsgrenze und Umsetzung der Boundary Policy (`coverage_status = "native" | "fallback"`, `source_tf`) gemäß §3.2 Ebene 1 und §4 Säule 1.3.

## 📁 Dateien

- **Neu:** `../../analytics/engine/mtf_fc_boundary.py` – Boundary-Evaluierung (reine Logik, kein UI-Import).
- **Geändert:** `../../test/test.py` (Test 3).

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

- **Neu:** `../../analytics/engine/mtf_fc_cascade.py` – reine Logik, keinerlei UI-Import (Grundsatz 4/11).
- **Geändert:** `../../test/test.py` (Test 1 + 2).

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

- **Neu:** `../../analytics/engine/mtf_fc_confluence.py` – Score-Berechnung (reine Logik).
- **Geändert:** `../../test/test.py` (Test 5).

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

- **Neu:** `../../analytics/engine/mtf_fc_guards.py` – Prioritaäts-Kette (reine Logik).
- **Geändert:** `../../test/test.py` (Test 4).

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

- **Neu:** `../../analytics/engine/mtf_fc_partition.py` – Partitionierung + Invalidierung (reine Logik).
- **Geändert:** `../../test/test.py` (Test 6).

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

- **Neu:** `../../chart/widgets/mtf_filter_bar.py` – `MtfFilterBarWidget` (QWidget, reines Event-Handling/Rendering).
- **Neu:** `../../analytics/engine/mtf_fc_templates.py` – View-Template-Persistenz via `SchemaMigrator` (Payload-Key `mtf_fc_schema_version = "1.0.0"`, in-memory, abwärtskompatibel).
- **Geändert:** `../../chart/chart_win.py` (Integration der Filterleiste), `../../analytics/ui/analytics_win.py` (Tabellen-Sortierung, falls betroffen).

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
- **Geändert:** `../../chart/js/04_live_updates.js` (optionaler Hook-Aufruf, Muster `06_two_tier.js`), `../../chart/chart_win.py` (Kaskaden-Umschaltung + `tf_combo`-Sync), `../../chart/chart_basics.py` (`JS_FILES`-Liste erweitern).

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
- **Geändert:** `../../chart/chart_win.py` (Guard-Override-Trigger über 21.03.05), `../../chart/js/03_chart_rendering.js` (Ghost-Pfeil am Viewport-Rand), `../../chart/chart_basics.py` (`JS_FILES`).

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

Service-Failure-Degradation-Integrationstest (§7 Test 7) sowie Gesamtlauf aller Tests und Cleanup von `../../test` (Grundsatz 10).

## 📁 Dateien

- **Geändert:** `../../test/test.py` (Test 7).

## 🛠️ Umsetzungsschritte

1. Test 7 (Service-Failure-Degradation): drei aufeinanderfolgende Fehler von Service A → RAM-Quarantäne; Service B läuft weiter; Service C meldet `dependency_failed`; der alte `shared_state` bleibt erhalten; `reset()` hebt die Quarantäne auf. Basis: bestehendes `execute_set_resilient()` in `set_evaluator.py` – kein Umbau der Engine nötig.
2. Alle 7 Tests aus §7 in `../../test/test.py` ausführen (headless, kein `QApplication.exec()`, Grundsatz 2).
3. Cleanup: temporäre Test-Skripte und `*.duckdb`-Dateien aus `../../test` entfernen – es verbleibt nur der Harness `../../test/test.py` (Grundsatz 10).
4. Implementierungs-Log: Einträge je 21.03.xx in `../AKTUELLE_UMSETZUNG.md` nach Bestätigung des Anwenders (Taxonomie 21.03, Format MD).

## ✅ Headless-Verifikation

- Gesamtlauf `../../test/test.py` (alle Checks PASS); `../../test`-Inhalt = nur `test.py`.

---

# 21.03.11 – Buglist-Auswertung & Fix-Plan (12.08.2026, Stand: Analyse)

> Vom Anwender gemeldete Buglist (6 Punkte). Analyse-Ergebnisse gegen den Code,
> **noch keine Umsetzung** (nur Doku, kein Coding). Verifikation teilweise headless
> (Strukturcheck der Filterleiste), UI-Nachprüfung durch den Anwender.

## 📋 Bug 1 – Heatmap-Legende: korrekte Operator-Beschriftung

**Meldung:** Legende muss korrekt mit `=`, `>`, `<`, `>=` oder `<=` beschriftet sein.
**Klarstellung:** Die **Heatmap-Legende** (`../../analytics/ui/heatmap_widget.py`, `_update_legend`).

**Befund (Code):** Die diskrete Confluence-Legende beschriftet die Farbfelder aktuell
nur mit Zahlen (`0`, `1`, …, `4`, `5+`); die kontinuierliche Viridis-Legende mit
Rohwerten. Keine Operator-Semantik.

**Fix-Plan:** Confluence-Modus je ganzzahligem Treffer-Wert `c` → Label `= 0`, `= 1`,
…, `= 4`; letztes Feld `≥ 5`. Viridis-Modus: Intervall-Labels (z. B. `≤ min+0.25span`,
`min+0.25span … min+0.5span`, …, `≥ min+0.75span`) – Formatierung über
`_format_heatmap_value`. Keine Logik-Änderung, nur Labels.

## 📋 Bug 2 – H1 + Zoom-In: kein Wechsel in kleinere Timeframes

**Meldung:** Bei H1-Auswahl wird beim Zoom-In nicht in kleinere TFs gebohrt, obwohl sie vorhanden sind.

**Befund (Code):** `../../analytics/engine/mtf_fc_cascade.py` (Band 2): `range_days < 2.0 d`
→ Kandidat `M5` (Zoom-In), darunter M1. Die Hysterese hält zwischen 2.0 d und 3.5 d
stabil. Zusätzlich greift der Transition Guard (`CROSSFADE_DURATION_MS = 250`), nach
einer Schaltung ist 250 ms lang keine weitere erlaubt. Logik headless verifiziert
(Tests 1+2 PASS).

**Fix-Plan (verifizieren im UI-Test):** Prüfen, ob der Wechsel unterhalb 2.0 d im
laufenden Chart wirklich ausbleibt. Mögliche Ursachen: `tf_combo`-Sync/Refresh-Race
nach `_mtf_fc_switch_tf`, Debounce (150 ms JS) oder Guard-Fenster. Falls reproduzierbar:
Flow nachziehen (kein Kaskaden-Logik-Fix nötig, da Engine headless grün).

## 📋 Bug 3 – „Alle TF ausführen" aktualisiert das Analytics-Hauptfenster nicht

**Meldung:** Wenn im Service „alle TF ausgeführt" wird, wird das Focus Widget nicht aktualisiert.
**Klarstellung:** **Analytics-Hauptfenster** (`../../analytics/ui/analytics_win.py`, Heatmap/Tabelle).

**Befund (Code):** `ServiceRunWorker` emittiert `event_bus.service_set_changed` genau
**einmal** nach Abschluss des Runs (`../../serviceui/run_worker.py`, `_emit_service_changed`).
Das `AnalyticsWindow` verbindet sich jedoch **nicht** auf `service_set_changed` (nur auf
`profile_changed`, `favorites_changed`). Das `ServiceSelectorModel` refreshed sich, die
Analytics-Queries aber nicht.

**Fix-Plan:** `AnalyticsWindow.__init__`: `event_bus.service_set_changed.connect(...)` →
debounced `self._vm.refresh_all()` (Bestehender VM-Pfad, kein neues SQL). Damit wird die
Heatmap/Tabelle nach jedem abgeschlossenen Service-Run automatisch neu geladen.

## 📋 Bug 4 – TF M15: X-Achse zeigt weiterhin 12h-Blöcke

**Meldung:** Bei M15 (statt H1) ist je Block auf der Achse immer noch 12-Stunden-x-teiler; sollte angepasst werden.

**Befund (Code):** `../../chart/js/04_live_updates.js` (`tickMarkFormatter`) ist **TF-unabhängig**
– er formatiert nur (`TT.MM.JJ` vs. `HH:MM`). Die Tick-Dichte bestimmt LWC v5 aus der
Viewport-Breite, nicht aus dem gewählten TF. Es gibt keine TF-spezifische Achsen-Granularität.

**Fix-Plan:** TF-abhängige Achsen-Skalierung: je `currentTfInSeconds` Ziel-Abstand der
Ticks (z. B. M15 → 15-min-Marken, H1 → 1h-Marken) im `tickMarkFormatter` bzw. via
`timeScale().applyOptions()`; Format bleibt Wanduhr (Invariante 7). Reine JS-Erweiterung
in `04_live_updates.js` (Additiv, kein Kern-Umbau).

## 📋 Bug 5 – Heatmap-Zoom-Slider X/Y korrelieren nicht mit Maus-Zoom

**Meldung:** Die Zoom-Slider an der Heatmap (einer für X, einer für Y) sollten mit dem Maus-Zoom korrelieren und verbunden sein.

**Befund (Code):** `../../analytics/ui/heatmap_widget.py` hat X/Y-Slider
(`_slider_zoom_x`/`_slider_zoom_y`, 5..100). Die Verdrahtung ist **einseitig**:
Slider-Änderung → `_on_zoom_x/y_changed` → `_set_zoom_range` → `_apply_x/y_range`
(`setXRange`/`setYRange`). Es gibt **keinen** `sigRangeChanged`-Hook der Plot-ViewBox
→ Maus-Zoom (Mausrad) bewegt die Slider nicht.

**Fix-Plan:** Zwei-Wege-Sync: `self._plot_hm.plotItem.vb.sigRangeChanged` → Slider via
`_set_zoom_slider` aktualisieren (blockSignals + `_syncing`-Guard gegen Endlos-Schleife).
Richtungskonvention (rechts = Zoom-In, links = Zoom-Out) beibehalten. ViewModel-Params
`zoom_x_range`/`zoom_y_range` bleiben die Quelle.

## 📋 Bug 6 – Filterleiste (Data-TF, Chart-TF, Range-Picker) nicht sichtbar

**Meldung:** Source-Data-TF, Chart-Overlay-TF und Range-Picker sind definitiv NICHT
sichtbar; weitere Elemente vermutlich ebenfalls nicht nutzbar. Der Range-Picker ist wichtig
(nicht immer alle Jahre sehen).

**Befund (Code + headless Strukturcheck):** Die `MtfFilterBarWidget` wird in
`../../chart/chart_win.py` (Zeile ~486-490) an `verticalLayout_toolbar` angehängt – Strukturcheck
offscreen bestätigt: Layout gefunden, 2→3 Items, Einfügen OK. **Ursache der Nicht-Sichtbarkeit:**
`sizeHint` der Leiste = **w 2248 px** (bei 1200 px Fensterbreite) → die Zeile läuft über,
wird abgeschnitten/geclippt, die Controls sind nicht erreichbar.

Zusätzlich fehlen in `chart_win.py` die Signal-Verdrahtungen:
- `sort_mode_changed` → **nicht verbunden**
- `sessions_changed` → **nicht verbunden**
- `template_applied` → **nicht verbunden**
(nur `data_tf_changed`, `chart_tf_changed`, `range_changed`, `guard_override_requested`).

**Fix-Plan:**
1. `MtfFilterBarWidget` kompakt umbauen (kleinere Controls, kürzere Labels, ggf.
   zwei Zeilen/Flow) – Ziel: `sizeHint`-Breite ≤ ~1100 px, sichtbar bei 1200 px Fenster.
2. Fehlende Signal-Verdrahtung in `chart_win.py` nachrüsten (Sortierung an den
   Analytics-/Tabellen-Kontext, Sessions an den Chart, Template-Anwendung).
3. Range-Picker wirkt bereits (`_on_mtf_fc_range_changed` → `_mtfFcApplyRange`) –
   nach Sichtbarkeits-Fix benutzbar.

---

# Implementierungs-Log 21.03 (MTF-FC v4) – 12.08.2026

> Taxonomie 21.03, Format MD. Einträge je umgesetztem Schritt nach Anwender-Bestätigung. Headless-Validierung ohne UI-Ausführung (Grundsatz 2).

## 21.03.01 – Data Provider & `shared_state`-Namespace (12.08.2026 17:11)

- **Umgesetzt:** `../../analytics/engine/mtf_fc_state.py` (Namespace-Factory `default_mtf_fc_state()`, `ensure_mtf_fc_namespace()` – alle Keys aus §5), `../../analytics/engine/mtf_fc_provider.py` (`MtfFcProvider` mit `get_earliest_timestamp`/`get_latest_timestamp` via MIN/MAX `"time"`, Cache-Key `(symbol, timeframe, partition)`, `is_cache_valid`, `read_namespace`/`write_namespace`, `clear_partition`).
- **Verifikation:** Namespace-Default-Struktur (alle §5-Keys), `get_earliest_timestamp("SILVER", "M1")` ≈ 2013-06-05 (reale DB, Wanduhr), Cache-Stale-Erkennung bei veraltetem `source_max_timestamp` – Test 1-Teilblock in `../../test/test.py` PASS.
- **Commit:** `4217e71`

## 21.03.02 – Boundary Policy & Historien-Detection (12.08.2026 17:11)

- **Umgesetzt:** `../../analytics/engine/mtf_fc_boundary.py` (`MtfFcBoundary` mit `resolve_boundary`, `evaluate_coverage` native/fallback, `format_available_date` als `DD.MM.JJJJ`, Wanduhr-Formatierung ohne Berlin-Offset, Fallback-Kandidaten M5/M15/H1/H4/D1). Regel: höhere Aggregationsstufe wird nie als M1 deklariert.
- **Verifikation:** Test 3 (Daten vor M1-Grenze → `fallback`/`source_tf = "H1"`, nach Grenze → `"native"`) PASS.
- **Commit:** `4217e71`

## 21.03.03 – Hysterese-Kaskaden-Engine (12.08.2026 17:11)

- **Umgesetzt:** `../../analytics/engine/mtf_fc_cascade.py` – Schwellwerte (M1/M5→H1 bei 3.5 d, H1→M5 bei <2.0 d, H1→H4 bei >10 d, H4→D1 bei >35 d, D1→H4 bei <28 d), `CROSSFADE_DURATION_MS = 250`, `evaluate_cascade`, `transition_guard_ok`, `apply_transition`, Telemetrie `(trigger, from_tf, to_tf, range_days)`.
- **Verifikation:** Test 1 (Hysterese-Boundary 1.99/2.01/3.49/3.51 d) + Test 2 (20-fach Anti-Oszillation im Fenster [1.9 d, 3.6 d]) PASS.
- **Commit:** `4217e71`

## 21.03.04 – Confluence-Gewichtung & Normalisierung (12.08.2026 17:11)

- **Umgesetzt:** `../../analytics/engine/mtf_fc_confluence.py` – Gewichte (D1=3.0, H4=2.5, H1=2.0, M15/M30=1.5, M5=1.2, M1=1.0), `min_max_normalize` mit Constant-Matrix-Policy (flache Matrix → 0.5, keine Division durch Null), `volatility_ratio` mit Clamp 0.2–5.0 und Deaktivierung bei ATR ≤ 1e-6.
- **Verifikation:** Test 5 (flache Matrix → 0.5; W-D1-Übermacht vor Min-Max) PASS.
- **Commit:** `4217e71`

## 21.03.05 – State-Machine & Prioritäts-Kette (Guards & Override) (12.08.2026 17:11)

- **Umgesetzt:** `../../analytics/engine/mtf_fc_guards.py` – `apply_priority_chain` (Ebene 1 Hard Data Availability Guard → Ebene 2 Temporary User Override → Ebene 3 Fixed Data-TF Guard → Ebene 4 Auto Cascade → Ebene 5 Visual Preference), `start_override`/`reset_override` mit Transaktions-Semantik (`previous_data_tf`, `target_tf`, `reason`), `override_badge_text`, Inkongruenz-Warnung `WARNING_INCONGRUENT`.
- **Verifikation:** Test 4 (M15-Fix + D1-Geister-Marker-Klick → `previous_data_tf = "M15"`, Reset stellt exakt wieder her) PASS.
- **Commit:** `4217e71`

## 21.03.06 – Event-Partitionierung & Cache-Invalidierung (12.08.2026 17:11)

- **Umgesetzt:** `../../analytics/engine/mtf_fc_partition.py` – `partition`, `invalidate_partition` (+ `cache_generation`-Inkrement), `invalidate_partition_via_provider`; Integration mit Provider-Cache-Versionierung (21.03.01).
- **Verifikation:** Test 6 (historischer Tick t = vor 5 Tagen → exakt die betroffene Zeit-Partition wird invalidiert, alle übrigen bleiben) PASS.
- **Commit:** `4217e71`

## 21.03.07 – MtfFilterBarWidget & Control-Panel (UI) (12.08.2026 17:16)

- **Umgesetzt:** `../../chart/widgets/mtf_filter_bar.py` (`MtfFilterBarWidget`, MVVM – keine SQL/DB in UI): Source-Data-TF (`multi`/Fixiert), Chart-Overlay-TF (Auto/Manuell), Range-Picker (24h/7d/30d/YTD/benutzerdefiniert), Sortierung, Sessions (London/NY/Tokio), Presets; Signale für Data-TF/Range/TF-Wechsel. `../../analytics/engine/mtf_fc_templates.py` (`create_template`, `migrate_template` mit SchemaMigrator-Semantik, Payload-Key `mtf_fc_schema_version = "1.0.0"`, `MtfFcTemplateStore` in-memory).
- **Verifikation:** `py_compile` aller Dateien; Code-Inspektion (kein SQL in UI, EventBus-Entkopplung); Template-Migration headless (T7v1/v2) PASS.
- **Commit:** `4425bc9`

## 21.03.08 – Chart-Integration: Kaskade, Puls-Breadcrumb & Historien-Anzeige (12.08.2026 17:16)

- **Umgesetzt:** `chart/js/07_mtf_fc.js` (Zoom-Hook `pyBridge.onViewportChanged`, `_mtfFcApplyRange`, Puls-Breadcrumb, Boundary-UI), `../../chart/js/04_live_updates.js` (optionale Hooks `_onMtfFcFullUpdate`/`_onMtfFcVisibleRangeChanged`), `../../chart/chart_basics.py` (`JS_FILES` erweitert), `../../chart/chart_win.py` (`ChartBridge.viewportChanged`, MTF-FC-Init, `_on_mtf_fc_viewport_changed`, `_on_mtf_fc_range_changed`, `_mtf_fc_switch_tf`, `mtfFcState` im Update-Payload).
- **Verifikation:** `node --check` auf allen JS-Dateien; `py_compile`; Code-Inspektion.
- **Commit:** `4425bc9`

## 21.03.09 – Interaktives Layering: TF-Badges & Geister-Marker (12.08.2026 17:16)

- **Umgesetzt:** `chart/js/08_mtf_layers.js` (TF-Badges `onBadgeClick`, Geister-Marker `onGhostMarkerClick`, Reset-Badge, `animateToGhostLevel`), `../../chart/chart_win.py` (`badgeClicked`, `ghostMarkerClicked`, `guardOverrideReset`, `_push_mtf_fc_override_ui`, Handler `_on_mtf_fc_badge_clicked`, `_on_mtf_fc_ghost_marker_clicked`, `_on_mtf_fc_guard_reset`).
- **Verifikation:** `node --check`; `py_compile`; Code-Inspektion (Guard-Override-Trigger über 21.03.05, Reset stellt `previous_data_tf` wieder her).
- **Commit:** `4425bc9`

## 21.03.10 – Abschluss: Integrationstest & Cleanup (12.08.2026 17:20)

- **Umgesetzt:** Test 7 (Service-Failure-Degradation) standalone verifiziert und als Tests 1–7 (inkl. T7v1/v2 Template-Migration) in `../../test/test.py` integriert; Gesamtlauf ausgeführt; Cleanup temporärer Skripte (`check_mtf_fc.py`, `check_mtf_fc_test7.py`, `check_mtf_fc_ui.py`, `test_output_stderr.txt`) – verbleibt nur der Harness `../../test/test.py` (Grundsatz 10).
- **Verifikation:** `py_compile test/test.py` EXIT 0; Gesamtlauf: **alle 21.03 MTF-FC-Checks PASS** (T1a–T7.7, T7v1/v2). 26 vorbestehende FAILs (Fenster-/Reflow-, JSON-Feld-Auflösung, `instance_hash`-Binder in den 20.03-Analytics-Tests) sind Bestandszustand und nicht durch MTF-FC verursacht – der 21.03-Block ist vollständig grün. Keine neuen Quell-Commits nötig (Code bereits in `4217e71`/`4425bc9`, `../../test` gitignored).
- **Commit:** – (nur Doku)

## 21.03.11 – Buglist-Auswertung & Fix-Plan (12.08.2026, Analyse)

- **Umgesetzt:** **Nur Doku/Analyse (kein Coding).** Die vom Anwender gemeldete Buglist (6 Punkte) wurde gegen den Code ausgewertet; Fix-Pläne in `../AKTUELLE_UMSETZUNG.md` (Kapitel 21.03.11) dokumentiert. Zusätzlich eine beschädigte Zeile in der Doku (Zeile 107, „Steuerungselemente:6) definiti") bereinigt.
- **Befunde (Kurzfassung):**
  - **Bug 1:** Heatmap-Legende (`_update_legend`) ohne Operator-Labels (`0..5+`) → Fix: `= 0..= 4`, `≥ 5`; Viridis-Intervall-Labels.
  - **Bug 2:** Kaskaden-Logik headless grün (Zoom-In < 2.0 d → M5); UI-Nachprüfung nötig (Flow-Race vermutet).
  - **Bug 3:** `AnalyticsWindow` verbindet sich NICHT auf `event_bus.service_set_changed` (vom Worker einmalig nach Run emittiert) → Fix: EventBus-Anbindung + debounced `refresh_all()`.
  - **Bug 4:** `tickMarkFormatter` TF-unabhängig → Fix: TF-spezifische Achsen-Ticks in `04_live_updates.js`.
  - **Bug 5:** Heatmap-Zoom-Slider einseitig (Slider→Range); kein `sigRangeChanged`-Hook → Fix: Zwei-Wege-Sync mit `_syncing`-Guard.
  - **Bug 6:** Filterleiste wird eingefügt, aber `sizeHint` w=2248 px (verifiziert, offscreen Strukturcheck) → Überlauf/Clipping; 3 Signale unverdrahtet → Fix: kompakter Umbau + Verdrahtung.
- **Verifikation:** `test/check_filterbar_layout.py` (temporär, offscreen, danach gelöscht): `verticalLayout_toolbar` gefunden, Items 2→3, `MtfFilterBarWidget` sizeHint w=2248 px – Ursache für Bug 6 bestätigt. Keine Code-Änderungen.
- **Commit:** – (nur Doku)

## 21.03.11 - Bug-Fix-Umsetzung (12.08.2026, nach Anwender-Bestätigung)

> Die vom Anwender gemeldete Buglist (6 Punkte) wurde umgesetzt. Nach der
> reinen Analyse (`eb78ee4`) wurden alle Fixes implementiert und headless
> verifiziert (Grundsatz 2, keine UI-Ausführung).

### Bug 4 - TF-spezifische X-Achsen-Ticks (M15/H1) - FERTIG

- **Neu:** `chart/js/09_mtf_axis.js` - Overlay-Layer `#mtf-axis-layer` rendert TF-alignierte
  Tick-Labels (M15 → 15/30-min-Marken, H1 → 1h-Marken), `MTF_AXIS_STEPS`,
  `MTF_AXIS_MIN_LABEL_PX = 90`, nur Intraday (TF < 86400 s), Tagesgrenzen (00:00) an LWC;
  API `mtfAxisSetTf`/`mtfAxisClear`; Hooks `_onMtfAxisFullUpdate`/`_onMtfAxisVisibleRangeChanged`;
  `window._mtfAxisActive`-Flag.
- **Geändert:** `../../chart/js/04_live_updates.js` (`tickMarkFormatter` gibt bei aktivem Overlay
  Intraday-Labels ab, 2 optionale Hooks), `../../chart/chart_basics.py` (`JS_FILES` um `09_mtf_axis.js`).
- **Verifikation:** `../../test/check_mtf_axis.js` (permanent, 14/14 PASS); `node --check` alle 9 JS;
  HTML-Template-Checks PASS. Wichtig: `window.TF_SECONDS_MAP` ist `const` (kein window-Property).

### Bug 2 - H1 + Zoom-In: kein Wechsel in kleinere TFs - FERTIG

- **Geändert:** `../../chart/chart_win.py` - Viewport-Transfer-Bug behoben: Bei pending
  MTF-FC-Epochs wird `_resolve_epoch_logical_range` statt alter Bar-Offsets verwendet
  (Binärsuche auf `_time_cont_to_real`, geklemmt). `chart_tf_mode == "fix"` unterbindet
  die Auto-Kaskade (`_on_mtf_fc_viewport_changed`-Guard). Neuer State
  `_mtf_fc_pending_epochs`, gesetzt durch `_mtf_fc_switch_tf` aus `_mtf_fc_last_viewport`.
- **Verifikation:** `py_compile`; Engine-H1-Zoom-In-Checks PASS; JS-Trigger-Checks PASS;
  Epoch-Range-Checks 8/8 PASS.

### Bug 3 - "Alle TF ausführen" aktualisiert Analytics-Fenster nicht - FERTIG

- **Geändert:** `../../analytics/ui/analytics_win.py` -
  `event_bus.service_set_changed.connect(self._on_service_set_changed)` + debounced `refresh_all()`.
- **Verifikation:** `py_compile`; Code-Inspektion (EventBus-Entkopplung, Grundsatz 2/5).

### Bug 1 + Bug 5 - Heatmap-Legende & Zoom-Slider-Sync - FERTIG

- **Geändert:** `../../analytics/ui/heatmap_widget.py` - `sigXRangeChanged`/`sigYRangeChanged`
  → `_sync_slider_from_range()` mit `_syncing`-Guard (Bug 5, Zwei-Wege-Sync);
  Confluence-Legende mit `=`/`>=`-Operatoren (Bug 1).
- **Verifikation:** `py_compile`; Code-Inspektion.

### Bug 6 - Filterleiste nicht sichtbar / Sortierung wirkungslos - FERTIG

- **Befund:** (1) 1-Zeilen-Layout zu breit (sizeHint 1281 px) → Fenster wurde auf ~1220 px
  aufgezwungen, Range (x 837+) und Sortierung (x 1173+, Ende > Fenster) rechts abgeschnitten;
  (2) `sort_mode_changed` speicherte nur im Namespace - die Analytics-Tabelle hatte keinerlei
  Verbindung (Konzept-Lücke).
- **Geändert:** `../../chart/widgets/mtf_filter_bar.py` - ZWEI-ZEILEN-Layout (row1: Data-TF/
  Chart-TF/Range/Sort, row2: Sessions/Templates) → sizeHint 699 px, alle Controls sichtbar
  bei `resize(1000,700)`. `../../config/event_bus.py` - neues Signal `mtf_fc_sort_changed(str)`.
  `../../chart/chart_win.py` - `_on_mtf_fc_sort_mode_changed` emittiert zusätzlich auf dem
  EventBus (Entkopplung, kein Fenster-Know-how). `../../analytics/ui/analytics_win.py` - Slot
  `_on_mtf_fc_sort_changed` → `table_page.set_external_sort_mode()`. `../../analytics/ui/table_page.py` -
  `set_external_sort_mode()`/`_apply_external_sort()`/`_find_dynamic_header()`,
  `_SortableValueItem` (numerische JSON-Union-Sortierung: 10.2 > 9.5 korrekt statt lexikografisch),
  Anwendung nach jedem Befüllen (Vorrang vor Profil-Sortierung, kein User-Setting/Dirty-Flag).
- **Sortier-Semantik:** `Datum 🠇` → Zeit absteigend (UserRole-Epoch);
  `Signal 🠇` → Header-Substring (signal/stärke/score/conf/wert) numerisch
  absteigend; `TF 🠅` → timeframe aufsteigend; Fallback (keine Spalte) → Zeit.
- **Verifikation:** `../../test/check_mtf_sort_binding.py` (permanent, 21/21 PASS: EventBus, alle 3
  Modi, Numerik, Fallback, Refresh-Persistenz, kein User-Setting, Row-Mapping intakt);
  `../../test/check_filterbar_visible.py` (permanent): sizeHint 699 px, Range/Sort sichtbar innerhalb
  990 px fb bei 1000 px Fenster; `py_compile` aller geänderten Dateien PASS.
  DPI-Artefakt geklärt: `devicePixelRatio` = 1.0, aber `mapTo`-global-x ≈ 2× intern
  (offscreen-Render-Artefakt) - logische Koordinaten maßgeblich.

- **Commit:** `5194107`

---

# 21.03.12 - Architektur-Korrektur: MTF-FC-Ziel = Analytics (nicht Chart) (12.08.2026, Stand: Analyse & Entscheidung)

> **Anwender-Feststellung (12.08.2026):** Kapitel 21.03 (MTF-FC) ist **ausschliesslich** fuer das
> `AnalyticsWindow` (`analytics_win.py`) gedacht und macht zusaetzlich im `ServiceWindow`
> (`service_win.py`) Sinn - **niemals im Chart-Fenster**, das bereits vollstaendig und perfekt
> implementiert ist. Die bisherige Umsetzung (Commits `4425bc9`, `5194107`) hat das Widget
> fehlerhaft in `../../chart/chart_win.py` verbaut.
>
> **Stand:** Nur Doku/Analyse (kein Coding). Wartet auf den expliziten Startschuss des Anwenders.

## ?? 1. Befund (Code-verifiziert)

1. **21.03 ist umgesetzt, aber im falschen Fenster:** Das `MtfFilterBarWidget`, die Engine-Module
   (`mtf_fc_*`) und die JS-Layer (`07_mtf_fc.js`, `08_mtf_layers.js`, `09_mtf_axis.js`) wurden in
   das Chart-Fenster integriert statt in das Analytics-Fenster.
2. **Fehlende Imports in `../../chart/chart_win.py`:** Die MTF-FC-Klassen werden ohne Import referenziert
   (`MtfFcProvider`, `MtfFcBoundary`, `default_mtf_fc_state`, `MtfFilterBarWidget`,
   `evaluate_cascade`, `apply_transition`) - `NameError` beim Oeffnen eines Chart-Fensters
   (Z. 337/338/340/495/1800/1812). `import chart.chart_win` bestaetigt: alle Namen fehlen im Modul.
3. **Revert-Ziel verifiziert:** `../../chart/chart_win.py` ist zwischen `4217e71` (Stand vor 21.03) und
   HEAD **+416/-2** - ausschliesslich 21.03-Adds + Bug-2-Refactor (Cascade-Viewport). Ein Revert
   auf `4217e71` ist verlustfrei (kein Nicht-21.03-Verlust).
4. **JS-Hooks additiv:** `../../chart/js/04_live_updates.js` enthaelt nur optionale, guarded Hooks
   (`try { if (window._onMtfFc... ) }`) - ausschliesslich 21.03, sauber zuruecknehmbar.
5. **Widget ist chart-frei:** `../../chart/widgets/mtf_filter_bar.py` importiert nur `analytics.engine.*` -
   architektonisch problemlos nach `analytics_win` verschiebbar. Die Ablage unter `../../chart/widgets`
   war der einzige Fehlgriff.

## ?? 2. Entscheidung 6(a) - Semantik-Vertrag fuer Analytics (fixiert)

> Zu klären war: Woher nimmt `chart_tf` im Analytics-Kontext den konkreten Timeframe, wenn
> `chart_tf_changed` nur `'auto' | 'fix'` emittiert? **Entscheidung des Anwenders: 6(a).**

- **`data_tf` (Analysequelle / Filter):** Steuert `WHERE timeframe IN (...)`. `Multi` =
  `all_timeframes=True` (21.01 E1, bereits implementiert in Reader/Worker), `Fixiert auf [M15]` =
  `timeframe='M15'`.
- **`chart_tf` (Anzeige-/Aggregations-Ebene):** `Auto` = Granularitaet dynamisch an den Range
  anpassen (neue Reader-Logik, Zeit-Bucketing); `Fix` = **eigenes zweites TF-Dropdown**
  (Aggregations-TF, unabhaengig von `data_tf`). Das bestehende `chart_tf`-Combo liefert nur
  `'auto'|'fix'` - der konkrete TF kommt aus dem **neuen separaten Aggregations-TF-Dropdown**.
- **Range:** Presets (`24h`/`7d`/`30d`/`YTD`) relativ zum **letzten Datenpunkt** (`MAX(bar_time)`
  der feature_store-Daten) statt `time.time()` (im Chart ok, im Analytics koennten die letzten
  Signale Tage alt sein -> leere Ergebnisse).
- **Sort:** bestehende EventBus-Kette (`event_bus.mtf_fc_sort_changed` ->
  `table_page.set_external_sort_mode`) - kein neuer Code.
- **Nicht verdrahten im Analytics:** Guard-Override/Geister-Marker/Session-Farbbalken
  (chart-spezifisch, 21.03.09). Sessions: Prio 2 (kein Session-Konzept im `feature_store_reader`).
- **Templates:** Persistenz via `AnalyticsProfileRepository` (neue Sektion, z. B. `filters`);
  `MtfFcTemplateStore` ist aktuell nur in-memory.
- **TF-Liste:** `DATA_TF_OPTIONS` (6 Eintraege: Multi/M1/M5/M15/H1/H4) vs. Analytics-`TIMEFRAMES`
  (11: M1..MN1) - fuer Analytics konfigurierbar erweitern.

## ?? 3. Umsetzungsplan (abgeschlossen)

1. **[x] Chart-Revert (1 Vorgang):** (umgesetzt, Commit `85a0c7c`)
   ```
   git checkout 4217e71 -- chart/chart_win.py chart/chart_basics.py chart/js/04_live_updates.js
   git rm chart/js/07_mtf_fc.js chart/js/08_mtf_layers.js chart/js/09_mtf_axis.js
   ```
   Nicht anfassen: `mtf_filter_bar.py`, `mtf_fc_*`, `event_bus.py`, `analytics_win.py`,
   `table_page.py`, `heatmap_widget.py`.
2. **[x] Analytics-Integration:** (umgesetzt, Commit `eae1d7b`) `MtfFilterBarWidget` in `analytics_win._build_ui()` (Filter-Zeile),
   Signal-Verdrahtung (data_tf/chart_tf/range/template -> VM), `AnalyticsViewModel`-Parameter
   (`data_tf`, `chart_tf`/`agg_tf`, `range_from`, `range_to`), `analytics_repository`-Option
   `from_ts`/`to_ts`, Aggregations-TF-Dropdown fuer `Fix` (6a).
3. **[-] service_win (eigener Schritt, reduziert):** (entfaellt - `service_win.py` enthaelt keine MTF-FC-Integration) nur `data_tf` (Multi <-> `ALLE Timeframes`-Sentinel,
   U15-E) + optional Range; keine Sort/Sessions/Templates.
4. **[x] Doku:** (dieses Kapitel) 21.03-Kapitel in `../AKTUELLE_UMSETZUNG.md` auf Analytics-Ziel ausrichten.

## ?? 4. Verifikation (headless, Grundsatz 2)

- `py_compile` aller geaenderten Dateien; `import chart.chart_win` (kein GUI-Start);
  `node --check` fuer die JS-Ruecknahme; Logik-/DB-Tests in `../../test/test.py`.
- Keine UI-/Regressionstests (harte Regel).

## ?? 5. Umsetzung durchgefuehrt (12.08.2026, abgeschlossen)

> Nach dem Startschuss des Anwenders wurde die Architektur-Korrektur umgesetzt:
> Kapitel 21.03 ist vollstaendig auf das Analytics-Ziel ausgerichtet (der
> Chart-Revert lief in 21.03.11-Fix als Commit `85a0c7c`).

1. **Chart-Revert (Commit `85a0c7c`):** `../../chart/chart_win.py`, `../../chart/chart_basics.py`
   und `../../chart/js/04_live_updates.js` wurden auf `4217e71` zurueckgesetzt; die JS-Layer
   `07_mtf_fc.js`/`08_mtf_layers.js`/`09_mtf_axis.js` wurden entfernt (`git rm`). Damit
   sind die fehlenden Imports (NameError beim Chart-Oeffnen) und alle 21.03-Hooks aus
   dem Chart entfernt.
2. **Analytics-Integration (Commit `eae1d7b`):** `MtfFilterBarWidget` in
   `analytics_win._build_ui()` (Filter-Zeile, 11 Analytics-TFs statt 6 Chart-Defaults),
   Signal-Verdrahtung (data_tf/agg_tf/range/sort -> VM bzw. EventBus),
   `AnalyticsViewModel`-Parameter (`data_tf`, `agg_tf`, `range_from`, `range_to`,
   `all_timeframes`), Zeitfilter `from_ts`/`to_ts` in `FeatureStoreReader`/
   `AnalyticsRepository`/`AnalyticsWorker`, Aggregations-TF-Dropdown mit `bucket_tf`
   fuer die generische Heatmap (Entscheidung 6a), `now_provider` = `MAX(bar_time)`
   statt `time.time()`.
3. **service_win:** entfaellt - das `ServiceWindow` enthaelt keine MTF-FC-Integration
   (kein `MtfFilterBarWidget`, keine MTF-FC-Signale); es gibt nichts zu reduzieren.
4. **Doku:** 21.03-Kapitel auf das Analytics-Ziel ausgerichtet (dieses Kapitel).

- **Commit:** `85a0c7c` (Chart-Revert), `eae1d7b` (Analytics-Integration)

---

# Implementierungs-Log 21.03 (MTF-FC v4) - 12.08.2026 (Fortsetzung)

## 21.03.12 - Chart-Revert: MTF-FC aus dem Chart entfernt (12.08.2026)

- **Umgesetzt:** `git checkout 4217e71 -- chart/chart_win.py chart/chart_basics.py chart/js/04_live_updates.js`
  + `git rm chart/js/07_mtf_fc.js chart/js/08_mtf_layers.js chart/js/09_mtf_axis.js`.
  Damit sind die fehlenden MTF-FC-Imports (`MtfFcProvider`, `MtfFcBoundary`,
  `default_mtf_fc_state`, `MtfFilterBarWidget`, `evaluate_cascade`, `apply_transition`)
  und alle 21.03-JS-Hooks vollstaendig aus dem Chart entfernt (Revert-Ziel `4217e71`,
  fuer die 3 Ziel-Dateien identisch mit `69ae3a6`).
- **Verifikation:** Code-Suche in `../../chart/chart_win.py`/`../../chart/chart_basics.py`:
  keine `MtfFilterBarWidget`-/`mtf_fc`-Referenzen und keine Verweise auf die entfernten
  JS-Dateien mehr; `git status` zeigt die geloeschten JS-Dateien.
- **Commit:** `85a0c7c`

## 21.03.13 - Analytics-Integration: Filterleiste + Zeitfilter + Aggregations-TF (12.08.2026 20:06)

- **Umgesetzt:** Vollstaendige Umsetzung der Entscheidung 6a im Analytics-Fenster:
  * `../../chart/widgets/mtf_filter_bar.py`: eigenes Aggregations-TF-Dropdown (`agg_tf`,
    unabhaengig von `data_tf`), konfigurierbare TF-Listen (`data_tf_options`/
    `agg_tf_options`), injizierbarer `now_provider`, `apply_external_state()` und
    `set_chart_mode()` fuer den Profil-/Workspace-Restore, `_on_range_changed` nutzt
    den `now_provider` (Fallback `time.time()`).
  * `../../analytics/engine/analytics_view_model.py`: MTF-FC-Parameter `data_tf`/`agg_tf`/
    `range_preset`/`range_from`/`range_to`/`all_timeframes`; `set_data_tf` (multi ->
    `all_timeframes=True`, fixiert -> `timeframe`-Uebernahme), `set_agg_tf` -> `bucket_tf`
    in `_current_params`, `set_range`/`clear_range`, `latest_data_epoch` (MAX(bar_time));
    Persistenz ueber `_current_payload` (Sektion `sources`).
  * `../../analytics/engine/feature_store_reader.py`: `from_ts`/`to_ts`-Zeitfilter
    (`bar_time BETWEEN`, Wanduhr-Epochs) in fetch_rows/fetch_columns/fetch_heatmap/
    fetch_generic_heatmap; `bucket_tf`-date-Bucketing (FLOOR(EXTRACT(epoch)/secs)*secs)
    fuer die generische Heatmap; `_axis_coords`-/`_format_dim_value`-tz-Fixes.
  * `../../analytics/engine/analytics_repository.py` + `analytics_worker.py`: `from_ts`/
    `to_ts`/`bucket_tf` an alle Methoden durchgereicht.
  * `../../analytics/ui/analytics_win.py`: `mtf_bar` in `_build_ui`, Signal-Verdrahtung
    (data_tf/agg_tf/range/sort -> VM/EventBus), `_sync_mtf_bar_from_params` nach
    Profil-/Workspace-Restore, TF-Listen `MTF_DATA_TF_OPTIONS`/`MTF_AGG_TF_OPTIONS`
    (11 TFs M1..MN1).
  * `../../analytics/engine/mtf_fc_templates.py`: `agg_tf` in `_TEMPLATE_KNOWN_KEYS` +
    `_TEMPLATE_DEFAULTS` ergaenzt (View-Templates in-memory, wie im Chart).
- **Verifikation:** `py_compile` aller 7 geaenderten Dateien EXIT 0;
  `../../test/check_analytics_mtffc.py` (13 Checks: Zeitfilter, Bucketing, VM-Durchreichung)
  13/13 PASS; `../../test/check_analytics_mtffc_win.py` (22 Checks: Widget-VM-Integration,
  apply_external_state, Payload-Persistenz, Restore) 22/22 PASS; `../../test/test.py`
  Teil 21.03.12 T1-T10 PASS (26 vorbestehende FAILs in Test-32/36/37/20.03/Geometrie
  sind Bestandszustand: Test-DB-Fixtures ohne `instance_hash`-Spalte bzw. Qt-offscreen-
  Geometrie - nicht durch MTF-FC verursacht).
- **Commit:** `eae1d7b`

## 21.03.14 - Entscheidungen: 3 Anpassungswuensche (Range-Picker, Preset-Rueckbau, Kursluecken) (12.08.2026 20:42, Stand: Analyse & Entscheidung, KEIN Coding)

> **Anwender-Vorgabe (12.08.2026):** Drei Anpassungswuensche an der MTF-FC-Filterleiste
> (`MtfFilterBarWidget` im AnalyticsWindow) bzw. an der Heatmap-Darstellung wurden
> analysiert. Stand: Nur Analyse + Entscheidungs-Doku (kein Coding). Umsetzung erst
> nach explizitem Startschuss des Anwenders (Schritt 5).

### Wunsch 1 - "Benutzerdefiniert"-Range: Von-/Bis-Felder mit Date/Time-Picker (BESTAETIGT)

- **Entscheidung:** Bei benutzerdefiniertem Range werden ZWEI Eingabeboxen "Von" / "Bis"
  mit Date/Time-Picker-Widget (`QDateTimeEdit` mit `setCalendarPopup(True)`) angezeigt.
- **Zeitkonvention:** Bedienung als **Berlin-Wanduhr** (MT5-Epochs sind Wanduhr-encoded,
  Invariante 7) - die Konvertierung muss die Wanduhr-Konvention explizit abbilden
  (kein stiller OS-TZ-Offset wie bei Qt-Default).
- **Vorbelegung:** Beim Wechsel auf "Benutzerdefiniert" werden die Picker mit dem
  aktuellen Zeitraum (letzter gewaehlter Preset; Basis = letzter Datenpunkt
  `MAX(bar_time)` des `now_provider`, nicht `time.time()`) vorbelegt, nicht leer.
- **Validierung:** `from_ts <= to_ts` muss sichergestellt werden (Clamp/Swap oder
  UI-Warnung) - sonst liefert `bar_time BETWEEN f AND t` still leere Ergebnisse.
- **Backend-Status (bereits vorhanden):** `AnalyticsViewModel.set_range(from_ts, to_ts,
  preset)` + `FeatureStoreReader._apply_time_range` (`bar_time BETWEEN`, Wanduhr-Epochs)
  existieren; es fehlen nur UI + Restore. Aktuell wird der Eintrag "Benutzerdefiniert"
  in `_on_range_changed`/`apply_external_state` (mtf_filter_bar.py) uebersprungen.
- **UI-Platz:** Zwei Picker muessen platzsparend eingebaut werden (Bug-6-Hintergrund:
  sizeHint der Leiste darf nicht aufbrechen; ggf. Zeile 2).

### Wunsch 2 - Zusaetzliche Preset-Buttons rueckbauen + `sort_mode` ins Profil (BESTAETIGT)

- **Entscheidung:** Die zusaetzlichen View-Template-Steuerelemente des
  `MtfFilterBarWidget` ("Preset"-Namensfeld + 💾/📂-Buttons + Template-Combo, Zeile 2)
  werden ENTFERNT. Die Filter-Konfiguration laeuft ausschliesslich ueber das
  vorhandene Profil-Management (`AnalyticsProfileRepository`, Sektion `sources` im
  Profil-Payload, Option-B-Explicit-Save).
- **Begruendung:** `data_tf`/`agg_tf`/`range_preset`/`range_from`/`range_to` werden
  bereits pro Profil persistiert (`_current_payload`); `MtfFcTemplateStore` ist nur
  in-memory (Sitzungs-Scope) und ueberlebt keinen App-Neustart.
- **Ergaenzung:** `sort_mode` wird ZUSAETZLICH in den Profil-Payload aufgenommen
  (Sektion `sources`) - bisher laeuft die Sortierung nur ueber
  `event_bus.mtf_fc_sort_changed` -> `table_page.set_external_sort_mode` (in-memory).
  Ohne die Aufnahme ginge die Sortier-Auswahl nach dem Template-Rueckbau verloren.
- **Sessions:** Die Session-Checkboxen (London/New York/Tokio) werden NICHT entfernt -
  sie koennen zukuenftig wieder wichtig werden (bleiben im Analytics zunaechst
  unverdrahtet/angezeigt).
- **Hinweis:** `../../analytics/engine/mtf_fc_templates.py` wird nach dem Rueckbau toter
  Code (bleibt gemaess Code-Preserving-Regel erhalten, wird aber nicht mehr aufgerufen).

### Wunsch 3 - Durchgehende Kerzen- & Signalchart ohne Kursluecken (NICHT UMZUSETZEN)

- **Entscheidung:** Wird **NICHT umgesetzt** und es wird **keine Doku** dazu gefuehrt
  (kein Umsetzungs-Kapitel, kein Implementierungs-Log-Eintrag ueber eine Umsetzung).
- **Begruendung:** Architektur-Eingriff (kategoriales Heatmap-Grid vs. kontinuierliche
  Slot-Achse) bzw. neue Chart-Komponente; der Anwender hat den Wunsch nach Rueckfrage
  zurueckgezogen. Die bestehende Luecken-Darstellung (echte Bar-Epochs, Wochenend-/
  Handelspausen-Luecken) bleibt unveraendert.

---

- **Status:** Analyse + Entscheidungs-Doku abgeschlossen. KEIN Coding (wird nicht
  angefasst). Umsetzung der Schritte (1) und (2) erst nach explizitem Startschuss.
- **Commit:** `b00fd60`

---

# 21.03.14 - Umsetzung: Benutzerdefinierter Range + Preset-Rueckbau + sort_mode-Profilsierung (12.08.2026, nach Anwender-Startschuss)

> Nach dem Startschuss des Anwenders ("umsetzung 1. und 2.") wurden die
> Entscheidungen aus dem 21.03.14-Entscheidungs-Kapitel umgesetzt. Wunsch 3
> (durchgehende Kerzen-/Signalchart) bleibt - wie entschieden - unumgesetzt
> und undokumentiert.

## Umsetzung Wunsch 1 - Benutzerdefinierter Range mit Von-/Bis-Date/Time-Pickern (FERTIG)

- **Geaendert:** `../../chart/widgets/mtf_filter_bar.py` - In Zeile 2 (Session-Filter-Zeile)
  ersetzt ein `_custom_panel` (QWidget) die rueckgebauten View-Template-Controls:
  * Zwei `QDateTimeEdit`-Picker "Von:" / "Bis:" mit `setCalendarPopup(True)` und
    Anzeigeformat `dd.MM.yyyy HH:mm` (max. 150 px breit, platzsparend, sizeHint
    der Leiste bleibt klein).
  * Panel nur sichtbar, wenn der Range-Combo auf "Benutzerdefiniert" steht
    (`_show_custom_pickers`/`_hide_custom_pickers`).
  * **Wanduhr-Konvention (Invariante 7):** `_epoch_to_qdt`/`_qdt_to_epoch` bilden
    die (bereits Berlin-Wanduhr-encoded) Epochs direkt auf die QDateTime-FELDER ab
    (UTC-Darstellung der Epoch = Wanduhr, kein stiller OS-TZ-Offset).
  * **Vorbelegung:** Beim Wechsel auf "Benutzerdefiniert" werden die Picker mit dem
    letzten emittierten Zeitraum vorbelegt (`_last_range`); Basis = `now_provider`
    (letzter Datenpunkt `MAX(bar_time)` statt `time.time()`), Fallback 7 Tage.
  * **Validierung:** `_emit_custom_range` stellt `from_ts <= to_ts` sicher (Swap der
    Werte + Picker-Nachziehen, blockSignals gegen Signal-Loop).
  * `apply_external_state` um `range_from`/`range_to` erweitert: Restore eines
    gespeicherten benutzerdefinierten Zeitraums (Profil-/Workspace-Restore).
  * `_on_custom_range_changed` ohne `isVisible()`-Guard: Alle programmatischen
    Picker-Sets laufen ueber `_set_custom_pickers` (blockSignals) - der Guard war
    redundant und verpasste User-Edits, solange der Widget-Baum noch nicht sichtbar
    war (Restore vor Fenster-Shown).

## Umsetzung Wunsch 2 - Preset-Buttons rueckgebaut + `sort_mode` im Profil (FERTIG)

- **Geaendert:** `../../chart/widgets/mtf_filter_bar.py` - View-Template-Steuerelemente
  entfernt (Namens-`QLineEdit`, 💾/📂-Buttons, Template-`QComboBox`, Signal
  `template_applied`, Methoden `refresh_templates`/`_save_template`/`_load_template`/
  `_on_template_selected`/`_apply_template`); `template_store`-Parameter aus
  `__init__` entfernt; ungenutzter `QPushButton`-Import entfernt.
  `../../analytics/engine/mtf_fc_templates.py` bleibt gemaess Code-Preserving-Regel
  erhalten, wird aber nicht mehr aufgerufen (toter Code).
- **Geaendert:** `../../analytics/engine/analytics_view_model.py` - Default-Param
  `"sort_mode": "date"`; neue Methode `set_sort_mode(mode)` ('date'|'signal'|'tf',
  validiert, nur Dirty-Markierung - reiner UI-Zustand ohne Query-Refresh);
  `_current_payload` persistiert `sort_mode` additiv in der Sektion `sources`.
- **Geaendert:** `../../analytics/ui/analytics_win.py` - `_wire_controls` verbindet
  `mtf_bar.sort_mode_changed` zusaetzlich mit `_vm.set_sort_mode` (Profil-Persistenz;
  die EventBus-Kette zur TablePage bleibt); `_sync_mtf_bar_from_params` reicht
  `range_from`/`range_to`/`sort_mode` an `apply_external_state` weiter.
- **Sessions:** bleiben erhalten (unverdrahtet angezeigt), wie entschieden.

## Verifikation (headless, Grundsatz 2 - keine UI-/Regressionstests)

- `py_compile` aller 3 geaenderten Dateien EXIT 0.
- **Neu:** `../../test/check_custom_range_sortmode.py` (permanent, 42/42 PASS):
  * Teil A: Wanduhr-Konvertierung - QDateTime-Felder = UTC-Darstellung der Epoch,
    12:00-Epoch zeigt Stunde 12 (kein +2h-Shift), Round-Trip exakt.
  * Teil B: Custom-Panel - Combo-Wechsel blendet Picker ein, Vorbelegung aus
    letztem Range, Picker-Aenderung emittiert neu, Swap-Validierung (from<=to,
    Picker nachgezogen), Preset-Wechsel versteckt Panel, Custom-Werte ueberleben
    den Wechsel.
  * Teil C: Restore via `apply_external_state(range_preset="Benutzerdefiniert",
    range_from, range_to)` - Picker + Signal + Combo korrekt; None-Fallback ohne
    Crash (Default now-7d..now).
  * Teil D: `set_sort_mode` - Persistenz, Case-Normalisierung, Ungueltig->'date',
    Payload sources.sort_mode, `_restore_params_from_payload`.
  * Teil E: `apply_external_state(sort_mode=...)` setzt Combo + emittiert Signal.
  * Teil F: Integrationspfad Filterleiste -> VM - Custom-Range und sort_mode via
    Signale im VM, Payload-Roundtrip, Restore in ein neues Widget.
  * Teil G: AnalyticsWindow-Quelltext-Inspektion - sort_mode-Verdrahtung,
    EventBus-Kette, `_sync_mtf_bar_from_params` reicht range_from/to/sort_mode,
    keine View-Template-Reste im Widget.
- `../../test/check_analytics_mtffc_win.py` 22/22 PASS, `../../test/check_analytics_mtffc.py`
  13/13 PASS, `../../test/check_mtf_sort_binding.py` 21/21 PASS,
  `../../test/check_filterbar_visible.py` (sizeHint/sizeHint-Layout) PASS.
- `../../test/test.py`: Baseline-Vergleich per `git stash` - dieselben 26 vorbestehenden
  FAILs (Fenster-/Reflow-Geometrie, JSON-Feld-Aufloesung, instance_hash-Binder der
  20.03-Tests, Qt-offscreen-Artefakte) mit und ohne die Aenderung; die 21.03.14-
  Aenderung fuegt KEINE neuen FAILs hinzu.

- **Commit:** `1ed270c`

## 21.03.15 - Bug-Runde 5 Bugs: Range-Presets 90d/Year, Feld-Dropdown, Session-Zeile (FERTIG)

Umsetzung der 5 gemeldeten Bugs mit den Benutzer-Entscheidungen (21.03.15):
Bug 3 -> 'Year' (365-Tage-Fenster) statt 'YTD' + neues Preset '90d'; Bug 4 ->
Custom-Panel komplett entfernt (Sessions in Zeile 1 rechts neben Sort).

### Bug 1 - Heatmap 'Feld'-Dropdown schreibt wieder feature_ids (FIX)
- **Geaendert:** `../../analytics/ui/heatmap_widget.py` - die seit 10.08.2026
  (Runde 7) auskommentierte Verbindung `_combo_field.selection_changed ->
  _on_field_selection_changed` ist WIEDER AKTIV. Check/Uncheck im
  'Feld'-Dropdown schreibt `feature_ids` ueber den bestehenden
  ServicePicker-Pfad (`_reconcile_sammel_checks` -> `_checked_field_service_ids`
  -> `set_feature_ids`), damit ServicePicker-Auswahl und Feld-Dropdown
  konsistent bleiben. Docstring von `_on_field_selection_changed` aktualisiert.

### Bug 2 - Feld-Dropdown: bei leerem Filter NUR erster Parameter (FIX)
- **Geaendert:** `../../analytics/ui/heatmap_widget.py` - `_rebuild_field_dropdown`
  haengte bei leerem `feature_ids`-Filter JEDE Checkbox an (`no_filter=True`).
  Neu: lokaler Helper `_chk(match)` - im `no_filter`-Modus wird genau der
  ERSTE Parameter (erster Checkable-Eintrag) angehakt, alle weiteren leer
  (fuer AVG/SUM/MIN/MAX ist genau EIN aktives Hauptfeld sinnvoll). Bei
  aktivem Filter unveraendert (nur passende Haken).

### Bug 3 - Range-Presets: 'YTD' -> 'Year' (365 Tage) + '90d' (FIX)
- **Geaendert:** `../../chart/widgets/mtf_filter_bar.py` - `RANGE_PRESETS` =
  `["24h", "7d", "30d", "90d", "Year"]`; `_on_range_changed` rechnet
  `90d = 90*86400` und `Year = 365*86400` (kein Jahresbeginn-Fenster mehr,
  wie entschieden). `_ytd_epoch_offset` entfernt, ToolTip aktualisiert.
- **Migration:** Alt-Profile mit `'YTD'` -> `'Year'` und `'Benutzerdefiniert'`
  -> `'7d'` werden an 3 Stellen abgebildet: Widget `apply_external_state`
  (defensiv vor `setCurrentText`), VM `set_range` und VM
  `_restore_params_from_payload` (Restore-Pfad). Dadurch ueberleben
  gespeicherte Profile den Preset-Umbau.

### Bug 4 - Custom-Panel entfernt, Sessions in Zeile 1 (FIX)
- **Geaendert:** `../../chart/widgets/mtf_filter_bar.py` - das benutzerdefinierte
  Von-/Bis-Panel (QDateTimeEdit-Picker, Zeile 2) ist KOMPLETT entfernt:
  Imports (`QDateTime`/`QDateTimeEdit`), State-Vars (`_last_range`,
  `_custom_from`, `_custom_to`), Methoden (`_apply_custom_range_state`,
  `_default_custom_range`, `_set_custom_pickers`, `_show_custom_pickers`,
  `_hide_custom_pickers`, `_on_custom_range_changed`, `_emit_custom_range`,
  `_epoch_to_qdt`, `_qdt_to_epoch`), `apply_external_state`-Parameter
  `range_from`/`range_to` und der `"Benutzerdefiniert"`-Zweig. Die
  Session-Checkboxen stehen jetzt in ZEILE 1 rechts neben der Sortierung
  (eine Zeile, sizeHint 1152x26).
- **Geaendert:** `../../analytics/ui/analytics_win.py` - `_sync_mtf_bar_from_params`
  ruft `apply_external_state` ohne `range_from`/`range_to`.
- **Geaendert:** `../../analytics/engine/analytics_view_model.py` - Docstring von
  `set_range` aktualisiert ('7d'/'90d'/'Year'); `range_from`/`range_to`
  bleiben als effektiver Zeitfilter in den Params/Payload erhalten.
- **Geaendert:** `../../analytics/engine/mtf_fc_templates.py` - `custom_range` aus
  `_TEMPLATE_KNOWN_KEYS`/`_TEMPLATE_DEFAULTS` entfernt; neue Helper-Funktion
  `_normalize_obsolete` entfernt `custom_range` auch aus Alt-Templates mit
  bereits aktueller Schema-Version und mappt `YTD`/`Benutzerdefiniert`.

### Bug 5 - Viridis-Legende: Intervalle ohne ueberlappende Kanten (FIX)
- **Geaendert:** `../../analytics/ui/heatmap_widget.py` - `_update_legend`
  (Viridis-Zweig): die alten Labels `<= v25 / v25-v50 / v50-v75 / v75-vmax /
  >= v75` ueberlappten an v50/v75/vmax. Neu halboffene Intervalle [a,b):
  `< v25`, `v25-v50`, `v50-v75`, `v75-vmax`, `>= vmax` - jede Schwelle
  gehoert exakt zu EINEM Intervall.

### Verifikation (headless, Grundsatz 2 - keine UI-/Regressionstests)
- `py_compile` aller geaenderten Dateien EXIT 0 (mtf_filter_bar.py,
  analytics_win.py, analytics_view_model.py, heatmap_widget.py,
  mtf_fc_templates.py).
- **Neu/umgebaut:** `../../test/check_custom_range_sortmode.py` (permanent,
  47/47 PASS):
  * Teil A: Preset-Satz 24h/7d/30d/90d/Year, Sekunden exakt (90d/Year),
    'YTD'/'Benutzerdefiniert' entfallen, kein `_custom_panel`/`_dt_from`.
  * Teil B: `apply_external_state` migriert 'YTD'->'Year' und
    'Benutzerdefiniert'->'7d'; Signatur ohne range_from/range_to.
  * Teil C: VM-Migration `set_range` + `_restore_params_from_payload`.
  * Teil D: Session-Checkboxen (Bug 4) - London/New York/Tokio,
    `sessions_changed` emittiert korrekt.
  * Teil E-H: sort_mode-Persistenz (21.03.14 erhalten), Integrationspfad,
    AnalyticsWindow-Quelltext-Inspektion (kein range_from/to mehr, kein
    Custom-Picker-Code).
- **Neu:** `../../test/check_heatmap_field_checks.py` (permanent, 4/4 PASS):
  * Bug 1: `selection_changed` -> `set_feature_ids` (Verbindung aktiv).
  * Bug 2: no_filter -> genau EIN Haken (erster Parameter); aktiver Filter
    -> passende Haken.
- Unveraendert gruen: `../../test/check_analytics_mtffc_win.py` 22/22,
  `../../test/check_analytics_mtffc.py` 13/13, `../../test/check_mtf_sort_binding.py`
  21/21; `../../test/check_filterbar_visible.py` (Diagnose) zeigt die neue
  EIN-Zeilen-Leiste (sizeHint 1152x26, alle Controls sichtbar).
- `../../test/test.py` referenziert keine entfernten APIs (kein Custom-Panel/
  YTD-Code); die MTF-FC-Kette bleibt unveraendert.

- **Commit:** 22e2b66

## 21.03.16 - Option A Feld-Dropdown (Parameter-Ebene, Bug 1/2) + Viridis-Legende (Bug 5) (12.08.2026 23:20, FERTIG)

> Nach dem Anwender-Startschuss wurde Option A (echte Parameter-Filterung) umgesetzt.
> Der User hatte die 3 Bugs (Feld-Dropdown wirkt nicht / wird nicht restored,
> falsche Vorbelegung bei Aggregations-Wechsel, unsinnige Legenden-Wertebereiche)
> als zu 100% weiterbestehend gemeldet. Entscheidung: Bug 1/2 = Parameter-Ebene
> wirklich filtern (Option A), Bug 5 = Operator-Labels + adaptive Genauigkeit.

### Kern-Architektur (Option A): (Service|Parameter)-Paare statt Service-IDs
- Die Checkboxen im 'Feld'-Dropdown repr?sentieren `{service_id}|{key}`-Paare
  (bisher wurden daraus NUR Service-IDs abgeleitet und auf Service-Ebene
  gefiltert - Abw?hlen eines Parameters bei 2 Parametern eines Services
  ?nderte nichts, weil die Service-Menge gleich blieb; Bug 1).
- **Neu:** `field_selection` (Liste `"{service_id}|{key}"`) wird als
  effektive Paar-Auswahl persistiert (Profil/Workspace) und beim
  Aggregations-/Restore-Wechsel EXAKT wieder hergestellt (Bug 2: keine
  'alle Parameter'-Vorbelegung mehr).
- **Reader-Filter:** `_apply_field_pair_filter()` erweitert die WHERE-Clause
  der generischen Heatmap um eine OR-Bedingung je Paar
  (`LOWER(TRIM(feature_id)) = ? AND json_extract_string(feature_data,
  '$.key') IS NOT NULL`) - An/Abw?hlen eines Parameters ?ndert die Grafik
  wirklich (nur Rows, deren feature_data den gew?hlten JSON-Key des
  jeweiligen Services tr?gt). Identifier-unsichere Keys werden defensiv
  ?bersprungen (kein SQL-Injection-Risiko, Muster `_is_json_key_identifier`).
- **DuckDB-Arrow-Bug (v1.5.5):** `feature_data->>'key'` kollidiert in
  Kombination mit `LOWER(TRIM(feature_id))`-Equalities mit einem
  Optimizer-Bug (versucht die JSON-Spalte auf numerisch/BOOL zu casten und
  wirft f?r nicht-matchende Zeilen). `json_extract_string(feature_data,
  '$.key')` liefert identische NULL-Semantik und ist auf JSON- UND
  VARCHAR-Spalten stabil.

### Bug 1 - Feld-Dropdown: An/Abw?hlen wirkt auf Grafik + wird restored (FIX)
- **Ge?ndert:** `../../analytics/ui/heatmap_widget.py` - `_on_field_selection_changed`
  ruft jetzt `set_field_selection(pairs)` (statt nur `set_feature_ids(ids)`).
  Neue Helfer `_checked_field_pairs()` (ALL|key-Expansion ?ber
  `_field_sources`) und `_sync_field_selection_to_vm()` (materialisiert die
  effektive Paar-Auswahl am Ende jedes Rebuilds).
- **Ge?ndert:** `../../analytics/engine/analytics_view_model.py` - neue Methode
  `set_field_selection(field_pairs, update_ids=True)`:
  * `update_ids=True` (User-Interaktion): `feature_ids` werden aus den
    Paaren abgeleitet (Dropdown/Picker konsistent; Abw?hlen des letzten
    Parameters entfernt den Service aus dem Picker).
  * `update_ids=False` (programmatischer Sync): `feature_ids` bleiben
    UNANGETASTET - der ServicePicker ist die Service-Quelle; Services ohne
    numerische Feld-Keys fallen dadurch nie aus der Auswahl.
  * Refresh auch bei UNVER?NDERTER Service-Menge, wenn sich die
    Parameter-Auswahl ge?ndert hat (Bug 1).
- **Persistenz:** `field_selection` wird in `_current_payload`/Restore-Pfaden
  via `_normalize_field_pairs` normalisiert (Alt-Payloads ohne Key = leer =
  kein Paar-Filter, Verhalten wie bisher).
- **Ge?ndert:** `../../analytics/engine/analytics_worker.py` /
  `../../analytics/engine/analytics_repository.py` /
  `../../analytics/engine/feature_store_reader.py` - `field_pairs`-Param
  durchgereicht bis `fetch_generic_heatmap` + Filter-Anwendung.

### Bug 2 - Aggregations-Wechsel: EXAKTE Vorbelegung statt 'alle Parameter' (FIX)
- **Ge?ndert:** `../../analytics/ui/heatmap_widget.py` - `_rebuild_field_dropdown`:
  EXPLIZITE `field_selection` gewinnt (sel_map; Rebuild stellt die
  gew?hlten Paare exakt wieder her). Ohne explizite Auswahl greift die
  DEFAULT-Vorbelegung: je AKTIVEM Service genau der ERSTE Parameter
  (sortierte Key-Reihenfolge), bei leerem Filter (alle Features) nur der
  erste Eintrag insgesamt (Verhalten wie bisher). Der fr?here 21.03.15-Fix
  (`_chk` im no_filter-Modus) wurde durch die generalisierte Logik ersetzt.
- Explizit-Pfad-Guard: Paare INAKTIVER Services (nicht in feature_ids)
  werden nicht angehakt und beim Sync beschnitten.

### Bug 5 - Viridis-Legende: Operator-Labels + adaptive Genauigkeit (FIX)
- **Ge?ndert:** `../../analytics/ui/heatmap_widget.py` - neuer Helper
  `_format_legend_value(val, span)`: Nachkommastellen-Zahl wird aus der
  Spanne abgeleitet (25-%-Schritte `span/4` GARANTIERT unterscheidbar;
  kleine Spannen vmin=0.01/vmax=0.02 -> 0.0125/0.015/0.0175/0.02 statt
  kollabierter '0.01 - 0.01'). `_update_legend` (Viridis-Zweig) nutzt
  eindeutige Operator-Labels: `< v25`, `v25 ? x < v50`, `v50 ? x < v75`,
  `v75 ? x ? vmax`, `? vmax` (statt Bindestrich-Intervallen).

### Verifikation (headless, Grundsatz 2 - keine UI-/Regressionstests)
- `py_compile` aller 5 ge?nderten Dateien EXIT 0 (analytics_view_model.py,
  analytics_worker.py, analytics_repository.py, feature_store_reader.py,
  heatmap_widget.py).
- **Neu:** `../../test/check_field_selection.py` (permanent, 19/19 PASS):
  Default-Vorbelegung (leerer Filter / erster Parameter je aktivem
  Service), EXPLIZITE Restaurierung nach Aggregations-Wechsel, ALL-
  Expansion in `_checked_field_pairs`, `set_field_selection`-Pfade
  (update_ids=True/False), Sync-Guards (inaktive Paare, Services ohne
  Keys bleiben in feature_ids), `_format_legend_value`.
- **Neu:** `../../test/check_field_pairs_db.py` (permanent, 5/5 PASS, temp.
  duckdb in test/ und danach gel?scht): Paar-Filter greift in echter
  DuckDB-Query (COUNT/AVG, feature_ids orthogonal, unsichere Keys
  defensiv).
- Bestehende Tests unver?ndert gr?n (Spot-Check): `../../test/check_heatmap_field_checks.py`
  (4/4, Service-Pfad bleibt ?ber den Fallback `hasattr(set_field_selection)`
  kompatibel), `../../test/check_custom_range_sortmode.py` (47/47).

- **Commit:** `33c33ce`

---

# 21.03.20 – Analytics Modus-Filter für Multi-Modus-Services (UI Enhancement)

---

## 🎯 1. Problemstellung & Ursachenanalyse

| Symptom / Problem | Technische Ursache im Quellcode |
| --- | --- |
| **Vermischung unterschiedlicher Berechnungsverfahren** | Services wie `srv_swing_structure` oder `srv_swing_momentum` besitzen einen `mode`-Parameter mit völlig unterschiedlichen Logiken und Messskalen (z. B. `Williams_Fractal` vs. `ZigZag_ATR` oder `MA_Peak_Hysteresis` vs. `Chande_Kroll_Ratchet`). In `analytics_win.py` / `heatmap_widget.py` fehlte bisher ein Filter-Dropdown für `source_mode`. Dadurch wurden die Ergebnisse verschiedener Modi desselben Services in einer Heatmap-Matrix/Tabelle vermischt und verfälscht. |

**Prämisse (Code-verifiziert, 13.08.2026):** Das Feld `source_mode` wird top-level in **jedes** `feature_data`-JSON-Record geschrieben – verifiziert in 6 Services:
`../../analytics/features/definitions/srv_swing_structure.py` (Z. 631, Modi u. a. `Williams_Fractal`, `Standard_Pivot`, `Gann_Mechanical`, `ZigZag_ATR`, `ZigZag_Pct`, `Period_Extrema`), `srv_swing_momentum.py` (Z. 541/564, Modi u. a. `MA_Peak_Hysteresis`, `MA_Slope_Change`, `Chande_Kroll_Ratchet`), sowie `srv_swing_volume_profile.py`, `srv_trend_breakout.py`, `srv_trend_hma_pivot.py`, `srv_trend_regime.py`. Der `mode`-Parameter liegt in `parameter_schema["mode"]["options"]` der jeweiligen Service-Definition.

---

## ✅ 2. Fixierte Entscheidungen des Anwenders (13.08.2026)

> Die Anforderung wurde auf Integrität, Korrektheit, Vollständigkeit und fachliche
> Sinnhaftigkeit geprüft. Die offenen Punkte wurden vom Anwender wie folgt entschieden:

1. **Scope = GLOBAL:** Der `service_mode`-Filter wirkt auf **alle** Analytics-Datenquellen:
   * Legacy-Heatmap (`fetch_heatmap`, Dow×Stunde),
   * generische Heatmap (`fetch_generic_heatmap`),
   * Tabelle (`fetch_rows`),
   * Scatter (`fetch_columns`),
   * Verteilung (`fetch_columns`).
   Die Refresh-Liste von `set_service_mode` umfasst daher `QUERY_FEATURES`, `QUERY_TABLE`, `QUERY_HEATMAP`, `QUERY_HEATMAP_GENERIC`, `QUERY_SCATTER` und `QUERY_DISTRIBUTION` (analog zu `set_range`/`set_feature_ids`).
2. **Dropdown-Quelle = DYNAMISCH (Performance-Lösung):** Um keinen teuren Extra-Scan pro UI-Event auszulösen, wird die `SELECT DISTINCT`-Abfrage für `source_mode` **direkt in den leichten `QUERY_FEATURES`-Metadaten-Scan im `FeatureStoreReader` integriert**, der ohnehin im Worker-Thread gecacht läuft. Kein separater DB-Roundtrip für das Dropdown.
3. **Nur SQL-Filterung (keine Kaskadierung auf das 'Feld'-Dropdown):** Das 'Feld'-Dropdown bleibt unverändert. Die Mode-Auswahl filtert ausschließlich die SQL-WHERE-Bedingung. Ergebnis: Wenn ein angehakter Parameter (`field_pairs`) vom gewählten Modus nicht produziert wird, liefern die betroffenen Zellen/Zeilen leer (0/NaN) – korrekt, keine Fehlermeldung, kein verfälschter Mix.
4. **Leerer-Modus-Fall = Dropdown ausgrauen/deaktivieren:** Wenn die aktive Service-Auswahl (`feature_ids`/`instance_hashes`) keinen einzigen Service enthält, der `source_mode` in seine Records schreibt, wird `_combo_mode_filter` **deaktiviert (disabled)** und auf `[ Alle Modi ]` zurückgesetzt. Bei `feature_ids = []` (kein Filter = alle Services) gilt das Dropdown als aktiv, sobald im Datenbestand mindestens ein Service `source_mode` schreibt.
5. **Threading-Kette = VOLLSTÄNDIG (ja):** `service_mode` wird vollständig durchgereicht:
   `AnalyticsViewModel._current_params()` → `AnalyticsAsyncWorker._execute()` → `AnalyticsRepository.get_table()/get_heatmap()/get_generic_heatmap()/get_scatter()/get_distribution()` → `FeatureStoreReader.fetch_rows()/fetch_columns()/fetch_heatmap()/fetch_generic_heatmap()`.

---

## 🏗️ 3. Fachliches Konzept & Lösungsarchitektur

1. **Einbau `_combo_mode_filter` in `HeatmapWidget`:**
* **Platzierung:** In der zweiten Steuerzeile (`ctrl2`) von `HeatmapWidget` direkt zwischen **Aggregation** (`_combo_agg`, `COUNT`, `AVG` ...) und **Feld** (`_combo_field`, Ergebnis-Parameter).
* **Inhalt:** `[ Alle Modi ]` (Item-Data `"all"`) sowie alle dynamisch ermittelten `source_mode`-Werte der aktuellen Datenlage.
* **Platz-Budget:** Bug-6-Hintergrund beachten – Label + Combo (min. 150 px) müssen in `ctrl2` platzsparend bleiben (sizeHint der Steuerzeile darf nicht aufbrechen).

2. **SQL-Filterung über `source_mode` (GLOBAL):**
Der `FeatureStoreReader` erweitert die SQL-WHERE-Bedingung aller 4 Daten-Pfade bei gewähltem Modus um:

AND LOWER(json_extract_string(feature_data, '$.source_mode')) = LOWER(?)

* **Muster-Konsistenz (21.03.16):** `json_extract_string` statt `feature_data->>'source_mode'` – der DuckDB-Arrow-Operator (v1.5.5) kollidiert in Kombination mit LOWER/TRIM-Equalities mit einem Optimizer-Bug (Cast-Versuch der JSON-Spalte auf numerisch/BOOL). `json_extract_string` liefert identische NULL-Semantik und ist auf JSON- UND VARCHAR-Spalten stabil.
* **Case-Toleranz:** `LOWER` auf beiden Seiten; ungewöhnliche Schreibweisen (z. B. `ma_peak_hysteresis` vs. `MA_Peak_Hysteresis`) matchen zuverlässig.

3. **Dynamische Modus-Liste ohne Extra-Scan (Performance-Lösung):**
* Der `QUERY_FEATURES`-Leichtpfad (bestehender Feld-Metadaten-Scan im `FeatureStoreReader`, läuft im Worker-Thread und wird gecacht) liefert additiv ein Payload-Attribut `source_modes: [...]` (distinct, case-original, leer = keine Modi vorhanden) sowie ein Flag `has_source_mode_services: bool`.
* SQL: `SELECT DISTINCT json_extract_string(feature_data, '$.source_mode') ... WHERE <gleiche Filter wie Metadaten-Scan> AND json_extract_string(feature_data, '$.source_mode') IS NOT NULL` (Wanduhr/Zeitfilter unkritisch – Metadaten-Scan ist ohnehin zeitlich ungefiltert).
* Das HeatmapWidget befüllt `_combo_mode_filter` aus diesem Attribut (blockSignals, `_syncing`-Guard) – kein separater DB-Zugriff im UI-Thread (Grundsatz 4/MVVM).

4. **Keine Kaskadierung auf das 'Feld'-Dropdown (Entscheidung 3):** `_rebuild_field_dropdown` bleibt unverändert; die `field_pairs`-Logik (21.03.16) und der Mode-Filter wirken unabhängig voneinander als UND-Bedingungen.

5. **ViewModel- & Profil-Persistenz:**
Der gewählte `service_mode` wird im `AnalyticsViewModel` (`_params`, Default `"all"`) verwaltet und additiv in der `sources`-Sektion des Profil-Payloads persistiert/restauriert (Muster `sort_mode`, 21.03.14). Der Restore erfolgt automatisch über die generische Key-Schleife in `_restore_params_from_payload` (Replace-Semantik, B3-2).

---

## 🛠️ 4. Schritt-für-Schritt Umsetzungsanleitung für die IDE

### Schritt 1: ViewModel-Erweiterung (`../../analytics/engine/analytics_view_model.py`)

1. **Parameter `service_mode` hinzufügen:** In `_params` den Default `"all"` hinterlegen:

# analytics/engine/analytics_view_model.py
self._params["service_mode"] = "all"

2. **Setter-Methode `set_service_mode` implementieren (GLOBALER Refresh):**

# analytics/engine/analytics_view_model.py
def set_service_mode(self, mode: str) -> None:
    """Setzt den Modus-Filter (z. B. 'MA_Peak_Hysteresis' oder 'all').

    Global: Der Filter wirkt auf Tabelle, beide Heatmaps, Scatter und
    Verteilung (Entscheidung 1). QUERY_FEATURES wird mitrefreshed, damit
    die dynamische Modus-Liste / das Deaktivierungs-Flag (has_source_mode_
    services) synchron zur Auswahl bleibt.
    """
    mode = str(mode or "all").strip()
    if mode == self._params.get("service_mode"):
        return
    self._params["service_mode"] = mode
    self._mark_dirty()
    self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                   QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                   QUERY_DISTRIBUTION))

3. **In `_current_params()` durchreichen – für ALLE Query-Kinds (global):**

# analytics/engine/analytics_view_model.py (in _current_params, Basis-Dict)
base["service_mode"] = p.get("service_mode", "all")

4. **Persistenz (`_current_payload`), Sektion `sources` – additiv:**

# analytics/engine/analytics_view_model.py (in _current_payload, sources)
"service_mode": p.get("service_mode"),

   (Restore läuft automatisch über `_restore_params_from_payload`, sobald der Key im Payload steht – kein Sonderfall.)

### Schritt 2: Reader-SQL-Filterung (`../../analytics/engine/feature_store_reader.py`)

1. **SQL-Helper für `source_mode` hinzufügen:**

# analytics/engine/feature_store_reader.py
@staticmethod
def _apply_mode_filter(service_mode: Optional[str], conditions: List[str], params: List[Any]) -> None:
    if not service_mode or str(service_mode).lower() in ("all", "alle", ""):
        return
    conditions.append("LOWER(json_extract_string(feature_data, '$.source_mode')) = LOWER(?)")
    params.append(str(service_mode).strip())

2. **In ALLEN 4 Daten-Pfaden aufrufen (global, Entscheidung 1):**

# analytics/engine/feature_store_reader.py (in fetch_rows / fetch_columns /
# fetch_heatmap / fetch_generic_heatmap, jeweils nach _apply_field_pair_filter/
# _apply_time_range)
self._apply_mode_filter(service_mode, conditions, params)

   Dafür bekommen alle 4 Methoden einen neuen Parameter `service_mode: Optional[str] = None`.

3. **Dynamischer Modus-Scan (Performance-Lösung, Entscheidung 2) – im `QUERY_FEATURES`-Leichtpfad:**

# analytics/engine/feature_store_reader.py
def fetch_available_source_modes(self, symbol, timeframe, feature_ids=None,
                                 instance_hashes=None) -> Dict[str, Any]:
    """DISTINCT source_mode-Werte (case-original) + Has-Flag für das
    Modus-Dropdown. Kein separater DB-Roundtrip: wird im bestehenden
    QUERY_FEATURES-Metadaten-Scan (Worker-Thread, gecacht) mitgeliefert.
    """
    # SELECT DISTINCT json_extract_string(feature_data, '$.source_mode')
    #   FROM feature_store
    #  WHERE <feature_ids/instance_hashes-Filter wie _apply_feature_filter>
    #    AND json_extract_string(feature_data, '$.source_mode') IS NOT NULL
    # return {"source_modes": [...], "has_source_mode_services": bool}

   Integration: `AnalyticsRepository` (QUERY_FEATURES-Pfad bzw. `_field_metadata`) ruft den Scan auf und hängt `source_modes` + `has_source_mode_services` an den Payload. Leere Liste = kein Service mit `source_mode` → UI deaktiviert das Dropdown (Entscheidung 4).

### Schritt 3: Worker- & Repository-Durchreichung (Threading-Kette, Entscheidung 5)

1. **`../../analytics/engine/analytics_worker.py` (`_execute`):** `service_mode = p.get("service_mode")` einmalig lesen und an **alle 5** Repo-Methoden übergeben:
   `get_table(..., service_mode=service_mode)`, `get_heatmap(...)`, `get_generic_heatmap(...)`, `get_scatter(...)`, `get_distribution(...)`.
2. **`../../analytics/engine/analytics_repository.py`:** Alle 5 Methoden erhalten `service_mode: Optional[str] = None` und reichen ihn an den Reader durch. Der `QUERY_FEATURES`-Pfad liefert zusätzlich `source_modes`/`has_source_mode_services` aus Schritt 2.3.

### Schritt 4: UI-Integration (`../../analytics/ui/heatmap_widget.py`)

1. **Dropdown in `__init__` anlegen und im Layout platzieren:**

# analytics/ui/heatmap_widget.py
self._combo_mode_filter = QComboBox()
self._combo_mode_filter.setMinimumWidth(150)
self._combo_mode_filter.addItem("Alle Modi", "all")
self._combo_mode_filter.setEnabled(False)  # bis zum ersten Payload mit Modi

# In Layout ctrl2 zwischen _combo_agg und _combo_field einfügen:
ctrl2.addWidget(QLabel("Modus:"))
ctrl2.addWidget(self._combo_mode_filter)

2. **Event-Verbindung & Sync:**

# analytics/ui/heatmap_widget.py
self._combo_mode_filter.currentIndexChanged.connect(self._on_mode_filter_changed)

def _on_mode_filter_changed(self) -> None:
    if self._syncing or self._view_model is None:
        return
    mode = str(self._combo_mode_filter.currentData() or "all")
    self._view_model.set_service_mode(mode)

3. **Dynamische Befüllung + Deaktivierung aus dem Payload (Entscheidungen 2 + 4):**
   Bei eingehendem Payload (in der bestehenden `_apply_payload`-Kette, analog `_rebuild_field_dropdown`):
   * `source_modes` aus dem Payload lesen; Combo unter `blockSignals`/`_syncing` neu befüllen (`[ Alle Modi ]` + Modi, Item-Data = case-originaler Wert).
   * `has_source_mode_services == False` → `_combo_mode_filter.setEnabled(False)` und auf `"all"` zurücksetzen (kein stiller Filter); sonst `setEnabled(True)`.
   * Restore: In der VM-Sync-Methode (Muster `_sync_controls_from_vm` bzw. `_on_params_restored`) wird der Combo-Index aus `vm.params["service_mode"]` gesetzt (blockSignals) – Profil-/Workspace-Restore.
   * Entfernen veralteter Modi (nicht mehr im Payload) bei jedem Rebuild – keine verwaisten Auswahlwerte.

### Schritt 5: Keine Änderungen (bewusst)

* **Keine Kaskadierung auf `_rebuild_field_dropdown`** (Entscheidung 3 – nur SQL-Filterung).
* **`../../analytics/ui/analytics_win.py`:** nur falls der Profil-/Workspace-Restore den Combo-Zustand außerhalb der VM-Params synchronisieren muss (Muster `_sync_mtf_bar_from_params`) – voraussichtlich nicht nötig, da das HeatmapWidget die Combo direkt aus `vm.params` restauriert.

---

## 📊 5. Akzeptanzkriterien für die Validierung (`../../test/test.py`)

1. **Modus-Filter-SQL-Test (global):** `fetch_generic_heatmap(..., service_mode="MA_Peak_Hysteresis")` UND `fetch_rows`/`fetch_columns`/`fetch_heatmap` erzeugen in der SQL-WHERE-Klausel den Ausdruck `LOWER(json_extract_string(feature_data, '$.source_mode')) = LOWER(?)` mit Parameter `'MA_Peak_Hysteresis'` und filtern abweichende Modi aus (`"all"`/None/leer = kein Filter).
2. **ViewModel-State-Test:** `set_service_mode("ZigZag_ATR")` setzt das Dirty-Flag, aktualisiert `_params["service_mode"]` und stößt die Datenabfragen neu an – Refresh-Liste enthält `QUERY_FEATURES`, `QUERY_TABLE`, `QUERY_HEATMAP`, `QUERY_HEATMAP_GENERIC`, `QUERY_SCATTER`, `QUERY_DISTRIBUTION` (global, Entscheidung 1).
3. **Threading-Ketten-Test:** `_current_params` → Worker → alle 5 Repo-Methoden → alle 4 Reader-Pfade – `service_mode` erreicht jede Query (Entscheidung 5).
4. **Metadaten-Scan-Test (Performance-Lösung):** `QUERY_FEATURES`-Payload enthält `source_modes` (distinct, case-original, ohne NULL) und `has_source_mode_services`; der Scan wird **ohne** separaten Roundtrip im bestehenden Metadaten-Scan-Pfad geliefert (Entscheidung 2).
5. **Deaktivierungs-Test (Entscheidung 4):** `feature_ids` ausschließlich mit Services ohne `source_mode` (z. B. `srv_grid_lines`) → `has_source_mode_services == False` → Combo disabled + auf `"all"` zurückgesetzt; mit `source_mode`-Service → enabled.
6. **Persistenz-Test:** `sources.service_mode` im Profil-Payload-Roundtrip; `_restore_params_from_payload` stellt `"all"`-Default bzw. gespeicherten Modus korrekt wieder her.
7. **Leerer-Modus-Ergebnis-Test:** Gewählter Modus, der in den aktiven Services nicht vorkommt → leere Matrix/Tabelle (0/NaN), kein Crash, keine Fehlermeldung.

## 📁 6. Dateien (Übersicht)

| Datei | Art | Inhalt |
| --- | --- | --- |
| `../../analytics/engine/analytics_view_model.py` | geändert | `service_mode`-Param + Setter (globaler Refresh) + `_current_params` + `_current_payload` (sources) |
| `../../analytics/engine/analytics_worker.py` | geändert | Durchreichung `service_mode` an alle 5 Repo-Methoden |
| `../../analytics/engine/analytics_repository.py` | geändert | `service_mode`-Parameter an 5 Methoden; `source_modes`/`has_source_mode_services` im QUERY_FEATURES-Pfad |
| `../../analytics/engine/feature_store_reader.py` | geändert | `_apply_mode_filter` + `service_mode`-Param an 4 Reader-Pfade + `fetch_available_source_modes` |
| `../../analytics/ui/heatmap_widget.py` | geändert | `_combo_mode_filter` (Layout, Signal, Payload-Befüllung, Deaktivierung, Restore) |
| `../../analytics/ui/analytics_win.py` | ggf. geändert | nur falls Restore den Combo außerhalb der VM-Params braucht (voraussichtlich nicht) |

## ✅ Verifikations-Rahmen (Grundsatz 2)

- Headless: `py_compile` aller geänderten Dateien; Logik-/DB-Tests in `../../test` (temporäre `*.duckdb` nur in `../../test`, danach Cleanup).
- Keine UI-/Regressionstests (harte Regel). UI-Verhalten (Dropdown-Sichtbarkeit/Deaktivierung) per Code-Inspektion + manueller Anwender-Prüfung.
- Implementierungs-Log: Eintrag 21.03.20 in `../AKTUELLE_UMSETZUNG.md` nach Anwender-Bestätigung.



---

# Implementierungs-Log 21.03.20 - Analytics Modus-Filter (13.08.2026 10:41)

- **Umgesetzt (Entscheidungen 1-5):**
  - `../../analytics/engine/analytics_view_model.py`: `_params["service_mode"] = "all"` Default, `set_service_mode(mode)` mit globalem Refresh (QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC, QUERY_SCATTER, QUERY_DISTRIBUTION; idempotent), `_current_params` Basis-Dict `service_mode` fuer ALLE Query-Kinds, `_current_payload` sources-Sektion `service_mode` (Restore ueber generische Key-Schleife).
  - `../../analytics/engine/feature_store_reader.py`: `_apply_mode_filter` (json_extract_string + LOWER, `"all"`/None/leer = kein Filter) an allen 4 Daten-Pfaden (`fetch_rows`/`fetch_columns`/`fetch_heatmap`/`fetch_generic_heatmap`); `service_mode`-Parameter an alle 4 Signaturen; `_feature_meta_base` sammelt additiv `source_modes_by_service` (gleicher gecachter Basis-Scan, kein Extra-Roundtrip); neue Methode `fetch_available_source_modes(symbol, timeframe, feature_id, feature_ids, instance_hashes) -> (source_modes, has_source_mode_services)` mit feature_ids-/Hash-Filter (Muster `feature_keys_by_service`).
  - `../../analytics/engine/analytics_worker.py`: `service_mode = p.get("service_mode")` einmalig lesen, Durchreichung an alle 5 Repo-Methoden (`get_table`/`get_heatmap`/`get_generic_heatmap`/`get_scatter`/`get_distribution`).
  - `../../analytics/engine/analytics_repository.py`: `service_mode`-Parameter an alle 5 Methoden + Reader-Durchreichung; `get_available_features` liefert im QUERY_FEATURES-Leichtpfad `source_modes` + `has_source_mode_services` (defensiv leere Liste/False bei Fehler).
  - `../../analytics/ui/heatmap_widget.py`: `_combo_mode_filter` (QComboBox, `[ Alle Modi ]` = data "all", min 150 px) in ctrl2 zwischen Aggregation und Feld; Signal `currentIndexChanged` -> `_on_mode_filter_changed` -> `vm.set_service_mode`; `_sync_mode_filter_from_payload` (blockSignals/_syncing, Stale-Guard via restore_generation) befuellt die Items aus `source_modes` (case-original), deaktiviert + resettet auf `"all"` bei `has_source_mode_services == False`, Restore aus `vm.params["service_mode"]`; `_sync_from_params` restauriert die Auswahl.
- **Verifikation (headless, keine UI):**
  - `py_compile` aller 5 geaenderten Quelldateien + 4 neuen Testdateien OK.
  - `../../test/check_mode_filter_db.py` (26 Checks): `fetch_available_source_modes` (distinct/sortiert, feature_ids-Filter, has-Flag), alle 4 Reader-Filter-Pfade (rows/columns/heatmap/generic), Repo-Payload (`source_modes`/`has_source_mode_services`), `get_table`/`get_heatmap`/`get_scatter`/`get_distribution`-Durchreichung - ALLE PASS.
  - `../../test/check_mode_filter_worker.py` (6 Checks): Dispatch-Kette _execute -> alle 5 Repo-Methoden - PASS.
  - `../../test/check_mode_filter_vm.py` (11 Checks): Default, Idempotenz, globaler Refresh, Dirty-Flag, `_current_params` fuer 6 Kinds, `_current_payload` sources - PASS.
  - `../../test/check_mode_filter_widget.py` (10 Checks): Items, enabled/disabled (Entscheidung 4), Reset auf all, `_on_mode_filter_changed`, Stale-Guard - PASS.
  - Bestehende Tests gruen: `check_analytics_mtffc.py` (13), `check_analytics_mtffc_win.py` (22), `check_field_pairs_db.py` (5), `check_field_selection.py` (19), `check_heatmap_field_checks.py`, `check_mtf_sort_binding.py` (21). `check_custom_range_sortmode.py` NICHT lauffaehig (externe DB-Sperre data/app_data.duckdb durch laufende App - unabhaengig von dieser Umsetzung).
- **Commit:** ceb2351
# Implementierungs-Log 21.03.20 - Bugfixing Runde: Layout / Modus-Dropdown / Service-Achse (13.08.2026)

- **Bug 1 (Layout, Mauszeiger-Werteanzeige):** `../../analytics/ui/heatmap_widget.py` - `_label_info` (Werteanzeige) liegt jetzt VOR `_combo_field` in ctrl2 (Spacing 6), `_combo_field` behaelt Stretch 1 (wachst bis Canvas-Ende). Verifiziert: `../../test/check_bugfix_2132_layout.py` PASS (info=15, field=17, stretch=1).
- **Bug 2 (Modus-Dropdown zeigte nur DB-geschriebene Modi):** `../../analytics/engine/analytics_repository.py` - neue `_registry_source_modes()` (classmethod) liest `parameter_schema["mode"]["options"]` der aktiven Services (PluginRegistry-Singleton, in-Memory) und merged per `dict.fromkeys`-UNION in `source_modes` (DB-Modi zuerst, dann Registry-Modi sortiert); `has_source_mode_services = bool(has_sm or registry_modes)`; `Set`-Import ergaenzt.
- **Bug 3 (Service-Achse mit Modus-Suffix):**
  - `../../analytics/engine/feature_store_reader.py`: `DIM_MAPPINGS["service_id"]` = `LOWER(feature_id) || '::' || COALESCE(json_extract_string(feature_data, '$.source_mode'), '')` (source_mode case-original); `fetch_generic_heatmap` neuer Parameter `extra_service_modes: Optional[List[str]] = None` ergaenzt fehlende `{feature_id}::{mode}`-Kombinationen als Achsenpunkte (nur service_id-Dimension, leere Zellen = fill).
  - `../../analytics/engine/analytics_repository.py`: neue `_registry_service_mode_pairs()` (liefert `{plugin_id_lower}::{mode}`), `_registry_source_modes` darauf refactored; `get_generic_heatmap` reicht `extra_service_modes` durch NUR bei `service_mode` in ("", "all", "alle").
  - `../../analytics/engine/analytics_view_model.py`: `resolve_service_label` parst `::`-Suffix, haengt `' / {Modus}'` nur bei nicht-leerem Modus an (auch im Exception-Fallback).
  - Verifiziert: `../../test/check_bugfix_2132.py` (8 PASS: 3 Achsenpunkte, grid leerer Suffix, 4 Matrix-Spalten, Modus-Filter begrenzt auf 1), `../../test/check_bugfix_2132_label.py` (5 PASS).
- **Verifikation (headless, keine UI):**
  - `py_compile` aller 4 geaenderten Quelldateien + Testdatei OK.
  - `../../test/check_mode_filter_db.py` (25 Checks, inkl. 3 neuer Registry-Payload-Checks), `../../test/check_bugfix_2132.py` (8), `../../test/check_bugfix_2132_label.py` (5), `../../test/check_bugfix_2132_layout.py`, `../../test/check_mode_filter_worker.py` (6), `../../test/check_mode_filter_vm.py` (11), `../../test/check_mode_filter_widget.py` (10) - ALLE PASS.
  - `../../test/check_mode_filter_db.py`: Payload-Erwartung von exakt auf "enthaelt" umgestellt (Bugfix 2 liefert zusaetzlich Registry-Modi der realen Plugins).
  - Temporaere Patch-Skripte (`test/_fix_bug*.py`) nach Verifikation geloescht.
- **Commit:** ce534c5
# Implementierungs-Log 21.03.20 - Bugfixing Runde 2: Layout / Modus-Parameter / Achsen / OSError (13.08.2026)

- **Bug 1 (Layout, Werteanzeige ueber dem Feld-Dropdown):** `../../analytics/ui/heatmap_widget.py` - `ctrl2` ist jetzt ein 2-zeiliges QGridLayout: Zeile 0 traegt `_label_info` EINE ZEILE UEBER der Steuerleiste, linksbuendig in derselben Spalte wie `_combo_field` (Spalte des 'Feld:'-Labels). `_combo_field` (Stretch 1) waechst weiterhin bis zum Canvas-Ende.
- **Bug 2 (Layout, Dropdown-Tausch):** Modus-Dropdown (`_combo_mode_filter`) steht jetzt VOR der Aggregation (`_combo_agg`). Verifiziert: `../../test/check_bugfix_2132_layout.py` (8 PASS, Grid-Semantik: info=(0,12) field=(1,12) gleiche Spalte, mode=(1,8) agg=(1,10)).
- **Bug 3 (Modus-spezifische Ergebnis-Parameter im Feld-Dropdown):**
  - `../../analytics/engine/feature_store_reader.py`: `_feature_meta_base` sammelt zusaetzlich `keys_by_service_mode` (JSON-Keys je (Service, source_mode), ROW-GENAU statt bucket-weit - bucket aggregiert ueber alle Modi); `feature_keys_by_service` erhaelt `service_mode`-Parameter und liefert nur die Keys der Rows mit diesem Modus (numeric_only weiter aktiv).
  - `../../analytics/engine/analytics_repository.py`: `_field_metadata` erhaelt `service_mode` + reicht ihn an `feature_keys_by_service` durch; bei gewaehltem, aber noch nicht berechnetem Modus (leere modus-gefilterte Keys) Fallback auf die nicht-technischen `output_schema`-Keys der selektierten Services (neuer Helper `_registry_output_keys`, Muster `_registry_service_mode_pairs`); `get_available_features` erhaelt `service_mode` und reicht ihn in die Feld-Metadaten.
  - `../../analytics/engine/analytics_worker.py`: QUERY_FEATURES reicht `service_mode` an `get_available_features`.
- **Bug 4 (MA_Slope_Change / 'Keine Daten vorhanden'):** Achsen-Labels (`resolve_service_label` inkl. ' / {Modus}') werden in `_render_generic` jetzt VOR dem Leer-Check konfiguriert - Beschriftung + Achseneintrag aktualisieren sich auch bei leerer Matrix (vorher blieb der alte Zustand stehen). 'Keine Daten'-Meldung nennt den gewaehlten Modus ('Keine Daten fuer Modus 'X''). DB-Abgleich (read-only): `source_mode LIKE %MA_Slope_Change%` = 0 Zeilen im gesamten Store - das Dropdown zeigt Registry-Modi (alle moeglichen), obwohl tatsaechlich nur MA_Peak_Hysteresis (hash 489c5ece) berechnet wurde. Die 'Keine Daten'-Meldung ist fachlich korrekt; die Ursache liegt in der Ausfuehrung/Persistenz des Modus, nicht in der Anzeige.
- **Bug 5 (OSError 22 beim Mausfahren):** `_lwc_date_ticks` clampt `lo`/`hi` auf >= 0 (Date-Epochs sind Wanduhr-Sekunden seit 1970; negative Werte aus dem zusammengefallenen Auto-Range nach 'Keine Daten' [-0.5, 0.5] wuerden `fromtimestamp(-86400)` ausloesen); `_date_marks` umschliesst `datetime.fromtimestamp` mit `(OSError, ValueError, OverflowError)` und ueberspringt ungueltige Marken; `_update_cell_info` faengt zusaetzlich `OSError` ab.
- **Verifikation (headless, keine UI):**
  - `py_compile` aller 4 geaenderten Quelldateien OK.
  - `../../test/check_bugfix_2132b.py` (17 Checks): keys_by_service_mode row-genau (Peak/Slope getrennt), feature_keys_by_service mit service_mode (numeric_only), _field_metadata modus-gefiltert, output_schema-Fallback fuer unbekannten Modus, get_available_features-Durchreichung, _date_marks ohne OSError bei negativen Epochs - ALLE PASS.
  - `../../test/check_bugfix_2132_layout.py` (8 Checks, umgestellt auf QGridLayout-Semantik), `../../test/check_bugfix_2132.py` (8), `../../test/check_bugfix_2132_label.py` (5), `../../test/check_mode_filter_db.py` (25), `../../test/check_mode_filter_worker.py` (6), `../../test/check_mode_filter_vm.py` (11), `../../test/check_mode_filter_widget.py` (10) - ALLE PASS.
- **Commit:** f71690f

# Implementierungs-Log 21.03.20 - Analyse & Entscheidungen Punkte 1-8 (F1-F8) (13.08.2026)

- **Stand:** Analyse & Entscheidungen, KEIN Coding (Anwender-Anweisung: nur Textblock + Doku + Commit). Die eigentliche Umsetzung erfolgt erst nach explizitem Startschuss.

- **Punkt 1 - MA_Slope_Change: a) Achse, b) Parameter-Dropdown**
  - **F1 (final):** Achsenpunkte generell erscheinen (fuer alle Modi, nicht nur gespeicherte).
  - **1a-Ursache (verifiziert):** `get_generic_heatmap` (analytics/engine/analytics_repository.py) setzt `extra_service_modes` NUR bei `service_mode in ("", "all", "alle")` - bei konkretem Modus bleibt `x_values=[]` → Achsenpunkt fehlt.
  - **1a-Loesung:** Bei konkretem Modus die Registry-Paare (`_registry_service_mode_pairs`) dieses Modus ergaenzen (analog All-Modus, aber modus-gefiltert).
  - **1b-Ursache (echter Code-Fehler aus Bugfixing Runde 2):** `get_generic_heatmap` ruft `_field_metadata(...)` OHNE `service_mode`; nur `get_available_features` reicht ihn durch. → Das QUERY_HEATMAP_GENERIC-Payload ueberschreibt die modus-gefilterte Feld-Liste aus QUERY_FEATURES.
  - **1b-Loesung:** `service_mode` an `_field_metadata` durchreichen.

- **Punkt 2 - Legende**
  - **F2 (final):** Confluence so anzeigen, wie es ueblich und semantisch richtig ist → Confluence bleibt `= 0` … `= 4`, `>= 5` (aktueller Zustand ist OK). NUR Viridis aendern: Operatoren VOR Zahl, kein `x` → `<= v25`, `>= v25`, `>= v50`, `>= v75`, `>= vmax`.
  - **Stelle:** `_update_legend` (analytics/ui/heatmap_widget.py).

- **Punkt 3 - Timeframes sortiert (fein→grob)**
  - **F3 (final):** inkl. M10 zwischen M5 und M15; Positionen: a) analytics_win oben (Pill-Strip zwischen Datenquellen und Limit), b) Service-Picker unter Run Timeframe, c) service_win ueber Parameter-Box.
  - **Verifiziert:** `combo_tf` in analytics_win ist bereits kanonisch (M1,M2,M5,M10,M15,M30,H1,H4,D1,W1,MN1). Unsorted sind die TF-Pill-Strips (alle 3 nutzen `FeatureStoreReader.fetch_service_tf_status(pid)` → Dict ohne ORDER → `TfStatusBadgeBar.update_status`). Zusaetzlich sortiert `get_available_timeframes` (feature_store_reader.py) `ORDER BY timeframe` = alphabetisch.
  - **Loesung:** Kanonische TF-Reihenfolge definieren (M1,M2,M5,M10,M15,M30,H1,H4,D1,W1,MN1); `fetch_service_tf_status` sortiert zurueckgeben (fixt a+b+c), zusaetzlich defensiv in `TfStatusBadgeBar._rebuild` sortieren; `get_available_timeframes` kanonisch sortieren.

- **Punkt 4 - Feld-Dropdown Check/Uncheck wirkt nicht**
  - **F4 (final):** Genau ein angehaktes Feld → die angehakten Paare bestimmen die Verfuegbarkeit/Aggregation; genau EIN angehaktes Feld wird aggregiert/angezeigt. Zweite Runde (mehrere Services und Modi - Darstellung insgesamt und mit Aggregationen) folgt spaeter; jetzt nur die Grundlage schaffen.
  - **Verifiziert:** Verbindung `selection_changed → _on_field_selection_changed → vm.set_field_selection` ist AKTIV. Problem: `srv_swing_momentum` schreibt dichte Records (alle Keys immer vorhanden) → Paar-Filter `key IS NOT NULL` wirkungslos.
  - **Loesung:** Angehakte Paare steuern die Aggregations-/Anzeige-Optionen (nur angehakte Felder als Optionen; Abhaken des aktiven Felds → Wechsel auf naechstes). Restore vorhanden (`_rebuild_field_dropdown` → `sel_map`).

- **Punkt 5 - Unsinnig hohe Legendenwerte**
  - **F5 (final):** NUR fuer preisartige Felder deaktivieren → SUM fuer preisartige Felder (price etc.) sperren/deaktivieren, fuer Signal-Felder (strength_value) erlauben. Keine DB-Ausgabe.
  - **Verifiziert:** SUM ueber price bei SILVER ≈ 5×30=150 pro 5-Min, ~43k pro Tag. DB derzeit gesperrt durch laufende App.

- **Punkt 6 - MasterTree: Modus in Namen**
  - **F6 (final):** a) Format `swing_momentum [MA_Peak_Hysteresis] (13.08.26)`; b) Clones mit echtem Datum (Hash ist seit 10.08.2026 schon aus dem Label entfernt - nur der Modus fehlt); c) auch im Tooltip.
  - **Stellen:** master_tree.py Plugin-Zeile (~Z. 645), Clone-Zeile (~Z. 674, hat params + last_execution), Set-Service-Zeile (~Z. 573) + Tooltips.
  - **Loesung:** Helper `_mode_suffix(plugin_id, params)`: nur bei >1 Option im `parameter_schema["mode"]["options"]` → `" [{mode}]"` anhaengen.

- **Punkt 7 - Ausfuehrung: Modus aus Parameterbox**
  - **F7 (final):** Variante a (nur gewaehlter Modus), implizites Uebernehmen der Parameterbox-Werte beim Run.
  - **Verifiziert (Wurzel von Bug 4):** Zwei Run-Pfade: service_win `collect_set_definition()` liest LIVE alle Controls (korrekt); Picker/MasterTree (`_on_run_service`/`_on_run_set` = `set_repo.get_set`, `_on_run_plugin` = `variant_run_entries`/`_plugin_config` = default_params → erster Mode-Eintrag) nutzt die GESPEICHERTE Definition → Parameterbox-Aenderungen ohne Speichern gehen verloren. Erklaert, warum MA_Slope_Change nie in der DB landete.
  - **Loesung:** Picker-Run uebernimmt die aktuellen Parameterbox-Werte (inkl. Modus) implizit vor der Ausfuehrung.

- **Punkt 8 (neu) - Dropdown Modi → Einzelservices-Parameter**
  - **Identischer Root Cause wie 1b** (`get_generic_heatmap` → `_field_metadata` ohne service_mode). Loesung = Fix 1b.

- **Fix-Zuordnung (Code-Stellen, fuer die spaetere Umsetzung):**
  | Punkt | Stelle |
  |---|---|
  | 1a | `get_generic_heatmap` (analytics/engine/analytics_repository.py): extra_service_modes bei konkretem Modus |
  | 1b+8 | `get_generic_heatmap` → `_field_metadata`: service_mode durchreichen |
  | 2 | `_update_legend` (analytics/ui/heatmap_widget.py): Viridis-Operatoren `<=`/`>=`, x entfaellt; Confluence unveraendert |
  | 3 | `fetch_service_tf_status` + `get_available_timeframes` (feature_store_reader.py), `TfStatusBadgeBar._rebuild` |
  | 4 | `_rebuild_field_dropdown`/Feld-Metadaten: genau ein angehaktes Feld aggregieren |
  | 5 | Aggregations-UI: SUM nur fuer preisartige Felder sperren |
  | 6 | master_tree.py (3 Label-Builder + Tooltips) |
  | 7 | service_selector_dialog `_on_run_*`: implizites Uebernehmen |

- **Kein Coding:** Es wurden keine Quelldateien geaendert (nur dieses Doku-Log). Die Umsetzung erfolgt nach explizitem Anwender-Startschuss.
- **Commit:** Doku-Log (einziger Content dieses Commits)

# Implementierungs-Log 21.03.20 - Umsetzung Punkte 1-8 (F1-F8) (13.08.2026)

- **Stand:** Umgesetzt nach Anwender-Startschuss; Analyse & Entscheidungen siehe voriger Eintrag (F1-F8).

- **Punkt 1 - MA_Slope_Change: a) Achse, b) Parameter-Dropdown (F1):**
  - `../../analytics/engine/analytics_repository.py` `get_generic_heatmap`: `extra_service_modes` wird jetzt AUCH bei konkretem Modus-Filter ergaenzt - die Registry-Paare werden auf den gewaehlten Modus gefiltert (`p.rsplit("::",1)[1].lower() == mode_key`). Vorher blieb die service_id-Achse bei konkretem Modus auf die DB-geschriebenen Kombinationen begrenzt (MA_Slope_Change erzeugte keinen Achsenpunkt).
  - **P1b+P8:** `service_mode` wird jetzt an `_field_metadata` DURCHgereicht - vorher fehlte er im QUERY_HEATMAP_GENERIC-Payload und ueberschrieb damit die modus-gefilterte Feld-Liste aus QUERY_FEATURES (Parameter-Box zeigte die falschen/ungefilterten Keys). Identischer Root Cause wie Punkt 8.

- **Punkt 2 - Legende (F2):** `_update_legend` (analytics/ui/heatmap_widget.py): Viridis-Labels auf `<= v25`, `>= v25`, `>= v50`, `>= v75`, `>= vmax` umgestellt (Operator VOR der Zahl, kein `x`). Confluence bleibt `= 0`...`= 4`, `>= 5` (unveraendert).

- **Punkt 3 - Timeframes sortiert fein->grob (F3):**
  - `../../analytics/engine/feature_store_reader.py`: neue Konstante `CANONICAL_TIMEFRAME_ORDER` (M1,M2,M5,M10,M15,M30,H1,H4,D1,W1,MN1) + Helfer `canonical_tf_sort()` (unbekannte TFs deterministisch am Ende, None/leer defensiv). `fetch_service_tf_status` UND `get_available_timeframes` liefern kanonisch sortiert statt `ORDER BY timeframe` (alphabetisch: D1,H1,H4,M1,...).
  - `../../serviceui/common_widgets.py` (`TfStatusBadgeBar`): zusaetzliche DEFENSIVE kanonische Sortierung in `update_status`/`_rebuild` (`_sort_tfs_canonical`) - deckt die Pill-Strips aller drei Fenster (AnalyticsWindow, ServicePicker, ServiceWindow) ab.

- **Punkt 4 - Feld-Dropdown genau ein angehaktes Feld (F4):** `_on_field_selection_changed` (heatmap_widget.py): das AKTIVE Feld wird vor der XOR-Reconciliation gemerkt; wird es abgehakt, zieht `_sync_field_current_after_checks` die Auswahl auf das naechste angehakte Feld nach und `_apply_config()` wird explizit nachgezogen (Refresh der Aggregations-/Anzeige-Auswahl).

- **Punkt 5 - Unsinnig hohe Legendenwerte (F5):** Neue Helfer `_is_price_like_key()` + `_PRICE_LIKE_KEY_HINTS` (price, *price, reference_price, vwap_lower, atr_value, lower_band, lower_level, prox_level*) in heatmap_widget.py. `_update_controls`: das SUM-Item des Aggregations-Dropdowns wird fuer preisartige Felder DEAKTIVIERT; ist SUM gerade aktiv und das Feld preisartig, wird implizit auf AVG gewechselt. Signal-Felder (strength_value) bleiben erlaubt.

- **Punkt 6 - MasterTree: Modus im Namen + Tooltip (F6):** Neuer Helper `MasterTree._mode_suffix(plugin_id, params)` (nur bei >1 'mode'-Option im `parameter_schema`; Modus aus params bzw. Schema-Default; rein lesend, defensiv leer):
  - Set-Service-Zeile: `swing_momentum [MA_Peak_Hysteresis] (13.08.26)`
  - Plugin-Zeile (ohne Clones): `swing_momentum [MA_Peak_Hysteresis] (13.08.26)`
  - Clone-Zeile: `🟢 <Preset> [MA_Peak_Hysteresis] (13.08.26)` (ID/#hash bleibt entfernt)
  - `_apply_badge` erhaelt `params`-Parameter und zeigt den Modus zusaetzlich im Tooltip (F6c).

- **Punkt 7 - Ausfuehrung: Modus aus Parameterbox (F7, Wurzel von Bug 4):** Neue Methode `_merge_live_param_values(definition)` (serviceui/service_selector_dialog.py): liest die LIVE-Control-Werte der aktuellen Parameterbox (`_service_param_controls`/`_ctrl_value` von `_param_host`) und merged sie VOR dem Run in die Run-Definition (nur fuer diesen Run, KEINE Persistenz). Match: exakte instance_id (Set-Service/Standalone); bei Clone-Runs (instance_id = '<pid>#<hash>') per plugin_id, nur wenn genau EIN Service matcht (mehrdeutig = keine Uebernahme). Aufgerufen in `_on_run_service`, `_on_run_set` und `_on_run_plugin` - inkl. Modus (vorher lief der Picker-Run mit default_params -> erstem Mode-Eintrag; MA_Slope_Change landete nie im feature_store).

- **Verifikation (headless, keine UI):**
  - `py_compile` aller 6 geaenderten Quelldateien + Testdatei OK.
  - `../../test/check_punkte_1_8.py` (9 Checks): canonical_tf_sort, _sort_tfs_canonical, _is_price_like_key, Repo extra_service_modes konkret/all/None + service_mode-Durchreichung an _field_metadata (Mock-Reader), _mode_suffix (3-Modi/Default/Ein-Modus/unbekannt), P7-Merge in allen 3 Run-Pfaden, P4-/P2-Source-Checks - ALLE PASS.
  - Bestehende Tests gruen: `check_bugfix_2132.py` (8), `check_bugfix_2132b.py` (17), `check_bugfix_2132_label.py` (5), `check_bugfix_2132_layout.py` (8), `check_mode_filter_worker.py` (6), `check_mode_filter_vm.py` (11), `check_mode_filter_widget.py` (10), `check_mode_filter_db.py` (25).
  - P3 gegen echte DB (read-only): `fetch_service_tf_status('srv_swing_momentum')` liefert M1,M2,M5,M10,M15,M30,H1,H4,D1,W1,MN1 (kanonisch); `get_available_timeframes('SILVER')` ebenfalls.
- **Commit:** 9214f00

# Implementierungs-Log 21.03.20 - Bugfix 'Heatmap wird nicht gezeigt / nicht anklickbar' (13.08.2026)

- **User-Meldung (13.08.2026):** Die Heatmap wird nicht gezeigt und kann nicht angeklickt werden.

- **Root Cause 1 (Hauptursache, End-to-End verifiziert):** `HeatmapPage._stack_modes` (analytics/ui/heatmap_page.py) blieb nach dem Start auf Index 0 (Legacy-Standard-UI Wochentag x Stunde), obwohl das Ansicht-Dropdown 'Generisch' zeigt. `set_mode()`/`_on_mode_changed()` setzen zwar Seite 1, aber ohne Workspace-Restore mit `heatmap_mode` wurde dieser Initial-Switch nie ausgefuehrt -> das generische Widget wurde NIE dargestellt, seine Bedien-Controls (Feld-Dropdown, Aggregation, Modus-Filter, ...) waren nicht bedienbar ('nicht anklickbar').
- **Root Cause 2 (Zusatz-Risiko):** Der (unsichtbare) Standard-`QUERY_HEATMAP`-Zweig in `HeatmapPage.on_data_ready` konnte bei leerer Matrix den Seiten-Overlay-Stack auf Index 1 (No-Data-Meldung) schalten und damit das generische Widget verdecken.

- **Fix (analytics/ui/heatmap_page.py, 2 Stellen):**
  1. `__init__`: `self._stack_modes.setCurrentIndex(1)` direkt nach dem Stack-Aufbau - die Basis-Ansicht ist seit 21.01 IMMER das generische Widget (Stack Seite 1). Damit ist der Initial-Zustand korrekt, unabhaengig vom Workspace-Restore.
  2. `on_data_ready(QUERY_HEATMAP)`: Der Leer-Matrix-Zweig setzt den Overlay NICHT mehr auf Index 1 (die Standard-Ansicht ist nicht mehr sichtbar und darf die Seiten-Sichtbarkeit nicht mehr steuern) - nur noch `return`; der Render-Pfad mit `setCurrentIndex(0)` bleibt unveraendert.

- **Verifikation (headless, keine UI):**
  - `py_compile analytics/ui/heatmap_page.py` OK; CRLF-Zeilenenden erhalten (Datei ist 100 % CRLF, Fix per CRLF-erhaltendem Skript angewendet).
  - `../../test/check_heatmap_page_stack.py` (10 Checks, neu): Initial-Stack zeigt Generisch (Index 1), nach attach ebenfalls, Overlay bleibt auf Content (Index 0) auch bei leerem QUERY_HEATMAP-Payload, generisches Payload rendert - ALLE PASS.
  - `../../test/check_heatmap_e2e.py` (8 Checks, neu): echte temp-DuckDB + echter AnalyticsViewModel + echter Async-Worker - Stack Index 1 vor und nach Request, generisches Image (2x3), currentWidget = HeatmapWidget, Page-Overlay 0 - ALLE PASS.
  - Regression gruen: `../../test/check_heatmap_render.py` (12), `../../test/check_punkte_1_8.py` (9).
- **Commit:** 529ef6b

# Implementierungs-Log 13.08.2026 - Bugfixing Runde 1-3: Profile / Heatmap-Layout / MasterTree-Modus-Labels (13.08.2026)

## Runde 1 - 5 Punkte (Bugfixing-Modus)

- **1. Custom-Range:** entfaellt bewusst (bereits am 21.03.15 entfernt) - keine Aenderung.
- **2. Modus-Dropdown:** `../../analytics/engine/analytics_repository.py` `_registry_service_mode_pairs` zunaechst mit Guard bei leerer Auswahl. KORRIGIERT in Runde 3 (Guard an die richtige Stelle verschoben, s. u.).
- **3. Profile kaputt:** `../../analytics/ui/analytics_win.py` - `_wire_controls()` verdrahtet `combo_profile.currentIndexChanged -> _on_profile_selected` und `btn_profile_save.clicked -> _on_profile_save`; `_on_profile_save()` synchronisiert die Filterleiste defensiv (data_tf/agg_tf/sort_mode/range via `mtf_bar.current_range_*()`). `../../chart/widgets/mtf_filter_bar.py`: neue Methoden `current_range_preset()`/`current_range_epochs()`, `_on_range_changed` nutzt die Extraktion.
- **4. W1/MN1:** DB-Check zeigt Daten vorhanden (SILVER: W1=1377, MN1=318) - kein Code-Bug.
- **5. Heatmap-Layout:** `../../analytics/ui/heatmap_widget.py` - 2-zeiliges Layout (row1: Kerzen-Overlay/X/Y/ZoomX/ZoomY/Modus/Aggregation; row2: 'Ergebnisparameter:' + `_combo_field` stretch).

## Runde 2 - Kosmetik (13.08.2026)

- **Heatmap-Breiten:** `_combo_x`/`_combo_y` `setMinimumWidth(160->110)`; Zoom-Slider `setMinimumWidth(70)` + `Expanding`-Policy (sichtbar).
- **MasterTree Plugin-Parents:** `../../serviceui/master_tree.py` `_build_plugin_item` - `mode_sfx` jetzt auch an Plugin-Parents MIT Clones (`f"{display_pid}{mode_sfx}"`).

## Runde 3 - MasterTree: aktueller Modus in eckiger Klammer + dahinter (13.08.2026, final)

- **User-Anforderung:** In eckigen Klammern steht bei den Clones der Servicename (richtig), aber dahinter muss auch der Name des AKTUELLEN Modus stehen - zusaetzlich Live-Update im Tree bei Modus-Aenderung (Services + Clones).
- **Format-Entscheidung (final):** Die Klammer bleibt (Schema-Default/params-Modus = 'Servicename'-Bezug). Der aktuelle Modus haengt IMMER dahinter: `[Default] AktuellerModus`. Aufloesungs-Kette: `params.mode` -> `source_mode_for_hash` (Feature-Store, letzte Ausfuehrung je instance_hash) -> `source_mode_for_plugin` (flache Standalone-Plugins) -> Schema-Default (nie gelaufene Variante). Ein-Modus-Services bleiben ohne Suffix.
- **Aenderungen:**
  - `../../analytics/engine/feature_store_reader.py`: neue Methode `fetch_source_modes_by_hash()` -> `Dict[feature_id_lower, {instance_hash: source_mode}]` (arg_max(json_extract_string(feature_data, '$.source_mode'), bar_time) ueber alle Symbole/TFs, SENTINEL_NATIVE-Filter).
  - `../../analytics/engine/service_selector_model.py`: `_load_source_modes_by_hash()` in `refresh()`; neue Methoden `source_mode_for_hash(plugin_id, hash)` + `source_mode_for_plugin(plugin_id)`.
  - `../../serviceui/master_tree.py`: `_mode_suffix_resolved()` haengt den aktuellen Modus IMMER hinter der Klammer an; `update_mode_label(instance_id, plugin_id, mode, instance_hash)` live ohne Baum-Neuaufbau (Scope: Clone per Hash, Set-Service per instance_id, flaches Plugin per plugin_id; Template-Parents MIT Clones bleiben unveraendert); `_set_label_mode()` robustes Label-Rewrite (Preset-Klammern wie 'Default (Kopie)', '*'/Datum bleiben erhalten); `_build_set_item()` berechnet den Hash VOR dem Suffix (Store-Aufloesung); `_build_plugin_item()` nutzt fuer flache Plugins `_mode_suffix_resolved`.
  - `../../serviceui/param_columns.py`: `_update_tree_mode_label()` reicht den instance_hash des bearbeiteten Presets (`_current_preset_editing`) an `tree.update_mode_label` durch.
  - `../../analytics/engine/analytics_repository.py` (Guard-Korrektur Runde 1): Der 'kein Registry-Fallback bei leerer Auswahl'-Guard gehoert NICHT in `_registry_service_mode_pairs` (Heatmap-Achse braucht den Fallback fuer F1) - er sitzt jetzt korrekt in `_registry_source_modes` (Modus-Dropdown wird bei leerer Auswahl leer; die Achse behaelt den vollen Registry-Satz).
- **Verifikation (headless, keine UI):**
  - `../../test/check_tree_mode_fix2.py` (neu, 38 Checks): reale Clone-Labels (Klammer + aktueller Modus dahinter), Abweichungs-Fall (Fake-Model: `[Supertrend_ATR] Donchian_Keltner_Breakout`), `_set_label_mode` (6 Label-Varianten inkl. Dirty/Datum/Preset-Klammern), `update_mode_label`-Matching (Clone-Hash/alle-Clones-Fallback/Set-Service/flaches Plugin/Parent unveraendert) - ALLE PASS.
  - `../../test/check_punkte_1_8.py` (9 Checks): ALLE PASS (F1-Achse wieder gruen nach Guard-Korrektur).
  - `py_compile` aller 5 geaenderten Quelldateien OK.
  - Datenlage (read-only): 5 Multi-Modus-Services; alle aktuellen Store-Modi == Schema-Default (z. B. srv_trend_breakout -> Supertrend_ATR) - die Abweichungs-Anzeige greift, sobald eine Variante mit anderem Modus laeuft.
- **Commit:** 3797734 (Code + Doku Runde 1-3 gemeinsam committet)

## Abschluss-Commit (13.08.2026 18:35) - Agents.md-Regel & Export-Clones

- **Agents.md (eigene Regel-Ergaenzung des Benutzers):** Punkt 6.3 (Stopp-Punkte) praezisiert - kein Setzen/Umsetzen von CLI-Menuevorgaben; weitere Schritte NUR auf ausdruecklichen manuellen Prompt ("Niemals wird eine Menuevorgabe der CLI gesetzt und dann implementiert. Nur ausschliesslich durch manuellen prompt!!!!").
- **docs/Exports/* (6 Dateien):** Regenerierte Export-Clones (export_Full/analytics/chart_engine/project_docs/rest/service_engine) - enthalten den aktuellen Quellcode-Stand inkl. der Agents.md-Regel (export_project_docs). Kein offizieller Quellcode (System-Regel 0), nur Doku-Konsistenz.
- **Testdateien:** verbleiben lokal in test/ (gitignored, Projekt-Konvention) - keine Commits.
- **Offener Punkt (bewusst NICHT umgesetzt):** Clone-Modus-Anzeige fuer Varianten ohne params.mode greift auf den Schema-Default zurueck; die Abweichungs-Anzeige (Store-Modus) ist seit Runde 3 implementiert und greift bei naechster Variante mit anderem Modus automatisch.
- **Commit:** (dieser Abschluss-Commit)


# Implementierungs-Log 13.08.2026 - Runde 3 final: MasterTree-Benennung (F1-F5) + Grafikteiler-Persistenz (13.08.2026, nach Anwender-Freigabe)

## Runde 3 final - MasterTree: neue Benennung (F1-F5, User-Vorgaben)

- **F1 - Service ohne Varianten:** Doppel-Anzeige entfernt, Minuszeichen zwischen Service- und Modusname:
  `swing_momentum - MA_Peak_Hysteresis (13.08.26 10:48)` (vorher `swing_momentum [MA_Peak_Hysteresis] MA_Peak_Hysteresis (13.08.26)`).
- **F2 - Varianten/Clones:** Klammer = Servicename OHNE `srv_`-Praefix, dahinter der AKTUELLE Modus:
  `🟢 <Preset> [swing_volume_profile] Volume_Profile (12.08.26 12:17)` (vorher `[Volume_Profile] Volume_Profile` - Modus doppelt).
- **F3 - Plugin-Parent-Knoten (Ordner ueber den Varianten):** NUR der Servicename (ohne Modus - der Modus kann je Variante unterschiedlich sein und steht an den Clone-Zeilen):
  `swing_volume_profile` (Runde 3b: `- Modus`, Runde 3c: final nur Servicename).
- **F4 - Nie gelaufene Varianten:** Namensschema wird trotzdem ausgegeben, am Ende steht `(nie)`.
- **F5 - Letzte Ausfuehrung mit Uhrzeit:** `(DD.MM.JJ HH:MM)` (z. B. `(13.08.26 10:48)`); Fallback bleibt `(nie)`.
- **Bugfix 1c - Live-Update im Picker:** `param_columns.py` `_update_tree_mode_label` faellt auf `selector` zurueck (`_DialogParamHost` haelt den Selector unter `selector`, nicht `service_selector`) - Moduswechsel im ServiceSelectorDialog aktualisiert die Baumzeile SOFORT.

### Aenderungen (Runde 3 final)

- `../../serviceui/master_tree.py`:
  - `_mode_suffix_resolved()` ersetzt durch `_current_mode(plugin_id, params, instance_hash)` (liefert nur den aufgeloesten Modus; Formatierung uebernimmt der Aufrufer). Aufloesungs-Kette unveraendert: params.mode -> source_mode_for_hash -> source_mode_for_plugin -> Schema-Default.
  - Neuer Normalisierer `_fmt_last_exec(value)`: akzeptiert `DD.MM.JJ` (Alt-Bestand) und `DD.MM.JJ HH:MM` (neu); Fallbacks `--.--.--`/`--.--.-- --:--` -> `nie`.
  - `_build_set_item()`: Set-Service-Label `{instance_id} - {Modus} ({last_exec})` (dash).
  - `_build_plugin_item()`: flache Standalone `{name} - {Modus} ({last_exec})`; Plugin-Parents MIT Clones nur `{name}`.
  - `_build_clone_item()`: `{prefix} {preset_name} [{display_pid}] {Modus} ({last_exec})` (bracket, Klammer = Servicename ohne srv_).
  - `_set_label_mode(item, mode, style)`: style `dash`/`bracket` - Live-Update-Rewrite ersetzt nur den Modus hinter Minuszeichen bzw. hinter der Klammer (Klammerwert = Servicename bleibt erhalten); `(Datum)`/`*` bleiben erhalten.
  - `update_mode_label()`: reicht den Knotentyp als style durch (Clone -> bracket, sonst dash).
- `../../serviceui/param_columns.py`: `_update_tree_mode_label` - selector-Fallback fuer den Dialog-Host (Bugfix 1c).
- `../../analytics/engine/service_selector_model.py`:
  - `_load_plugin_presets()`: `last_execution` der Clones jetzt aus `_last_execution_datetimes_by_hash` (`DD.MM.JJ HH:MM`, Fallback `--.--.-- --:--`) statt nur Datum.
  - `build_tree()`: `last_execution_datetime(pid)` (`DD.MM.JJ HH:MM`) statt `last_execution_date(pid)` fuer alle Baum-Zeilen.

### Verifikation (headless, keine UI - Grundsatz 2)

- `../../test/check_tree_mode_fix2.py` (46 Checks): reale Clone-Labels (Klammer = Servicename ohne srv_, Modus dahinter), `_current_mode` (Store-Modus gewinnt/params-Vorrang/Ein-Modus leer), `_set_label_mode` (dash/bracket, Dirty *, Datum, Preset-Klammern), `update_mode_label`-Matching (Clone-Hash/Set-Service/flaches Plugin/Parent unveraendert) - ALLE PASS.
- `../../test/check_all_labels.py` / `check_clone_labels.py` / `check_tree_mode_fix.py`: rendern das neue Format auf echten Baum-Daten (z. B. `swing_momentum - MA_Peak_Hysteresis (13.08.26 10:48)`, `srv_swing 34566 [swing_volume_profile] Volume_Profile (12.08.26 12:17)`, Parents nur Servicename).
- `../../test/check_punkte_1_8.py` (9 Checks): ALLE PASS (keine Regression).
- `py_compile` aller geaenderten Quelldateien OK.

## Runde 3d - Grafikteiler Tree|Parameter: Persistenz (Workspace + Profil + Historie)

- **User-Anforderung:** Der vom Anwender zuletzt eingestellte Grafikteiler zwischen Tree und Parameter soll in der gesamten Historie gespeichert und restored werden - Workspace und Profil.
- **Format:** Splitter-Breiten als Liste (Tree, Panel) - Persistenz in `global_settings` (Key `splitter_<dialog_key>`), im Analytics-Workspace-Payload und im Profil-Payload (Key `service_picker_splitter`).

### Aenderungen (Runde 3d)

- `../../state_manager.py`: neue Methoden `save_splitter_state(dialog_key, sizes)` / `get_splitter_state(dialog_key)` (global_settings, JSON-Liste).
- `../../serviceui/service_selector_dialog.py` (ServicePicker Tree|Parameter):
  - Neues Signal `splitter_changed(int, int)` - wird bei jeder `splitterMoved`-Bewegung ans AnalyticsWindow gemeldet (Live-Tracking, `_on_splitter_moved`).
  - `_save_geometry()`: sichert die Splitter-Position zusaetzlich in global_settings (Historie); `_restore_geometry()`: stellt sie wieder her.
  - Neue Methoden `current_splitter_sizes()` / `set_splitter_sizes(sizes)` (defensiv: nur 2 positive Werte, Tree-Minimum 180px respektiert).
- `../../analytics/ui/analytics_win.py`:
  - `_picker_splitter` merkt die letzte Position live (`_on_picker_splitter_changed`).
  - `_current_ui_layout()`: `service_picker_splitter` im Profil-Payload (`set_ui_layout` -> `save_profile`/`create_profile`).
  - `_save_workspace()`: `service_picker_splitter` im Workspace-Payload (+ global_settings-Backup).
  - Restore: beim Oeffnen des Pickers wird `service_picker_splitter` aus `workspace_layout` angewendet; beim Profilwechsel wird ein offener Picker-Dialog sofort nachgezogen.
- `../../serviceui/service_win.py` (MasterTree|Param-Box): `save_state()` sichert `main_splitter.sizes()` in der Fenster-Historie; `restore_state()` stellt sie wieder her.

### Verifikation (headless, keine UI - Grundsatz 2)

- `../../test/check_splitter_persist.py` (17 Checks): StateManager-Roundtrip (Temp-DB in test/), Dialog-Methoden gemockt (set/current/on_moved inkl. Tree-Minimum + Invalid-Guards), AnalyticsWindow-Payload-Inspektion (service_picker_splitter in Profil- und Workspace-Payload, splitter_changed verdrahtet, Restore beim Oeffnen), ServiceWindow-Historie (save/get_splitter_state) - ALLE PASS.
- `../../test/check_tree_mode_fix2.py` (46 Checks): weiterhin ALLE PASS (keine Regression).
- `py_compile` aller 7 geaenderten Quelldateien OK.

## Commit (13.08.2026) - Runde 3 final + Grafikteiler-Persistenz

- **Geaenderte Dateien (7):** `../../analytics/engine/service_selector_model.py`, `../../analytics/ui/analytics_win.py`, `../../serviceui/master_tree.py`, `../../serviceui/param_columns.py`, `../../serviceui/service_selector_dialog.py`, `../../serviceui/service_win.py`, `../../state_manager.py`.
- **Testdateien:** verbleiben lokal in test/ (gitignored, Projekt-Konvention) - keine Commits.

---

# 21.03.21 – Confluence-Analyse & Hotspot-Orchestrierung (Multi-Service & Multi-Modus Häufung)

---

## 🎯 1. Zielstellung & Fachliche Motivation

Das Ziel dieser Erweiterung ist die optische Erkennung von **Signal-Häufungen (Hotspots / Lichtsäulen)** über verschiedene Services, Parameter-Varianten und Berechnungsmodi hinweg.

Bisherige Kennzahlen-Analysen (wie Mittelwerte oder Einzel-Filter) verkleinern die Ergebnismenge auf isolierte Werte und verdecken das eigentliche Confluence-Muster. Das Kapitel 21.03.21 spezifiziert die Entkopplung von Einzel-Wert-Analysen hin zu einer echten **Multi-Service-Überlappung**.

---

## 🔍 2. Problemstellung & Ursachenanalyse

| Problem in der Praxis | Technische Ursache im Bestand |
| --- | --- |
| **Einzel-Filter verzerren Häufung** | Strikte Filter auf genau *einen* Service oder *einen* Modus isolieren Datenpunkte und verhindern das Erkennen von Signal-Überschneidungen.

 |
| **Mittelwert-Aggregation (`AVG`) ungeeignet** | Ein Mittelwert über ein $5$-Minuten-Raster berechnet die durchschnittliche Stärke eines Ticks, zeigt aber nicht die *Anzahl* der zusammengelaufenen Indikatoren.

 |
| **Starres Feld-Dropdown** | Bei reinen Signal-Zählungen ist die Auswahl eines konkreten JSON-Feldes (z. B. `strength_value`) mathematisch irrelevant und verwirrt den Anwender.

 |

---

## 🏗️ 3. Architektur- & Bedienkonzept

### 3.1 Das 3-Ebenen-Bedienmodell für Confluence

┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. SERVICE PICKER: Multi-Select active                                                │
│    [x] srv_trend_breakout  [x] srv_swing_structure  [x] srv_proximity                  │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 2. HEATMAP-WIDGET STEUERZEILE                                                           │
│    [ Aggregation: Confluence (COUNT DISTINCT) ▾ ]  [ Modus: 🌐 Alle Modi (Confluence) ▾ ] │
│    [ Feld: (deaktiviert / alle Felder) ▾ ]                                             │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 3. VISUELLE HOTSPOT-HEATMAP (Diskrete Farbskala E7)                                     │
│    0 Services = Hellgrau  |  1 Service = Gelb  |  2 = Cyan  |  3–4 = Orange  |  5+ = Rot  │
└────────────────────────────────────────────────────────────────────────────────────────┘


### 3.2 Modus-Dropdown (`_combo_mode`) im Confluence-Kontext

* **Standard-Einstellung:** `🌐 Alle Modi (Confluence)` (`service_mode = "all"`).
* **Verhalten:** Das System filtert nicht auf einen einzelnen Berechnungsmodus (`source_mode`), sondern fasst alle im Service Picker gecheckten Services und deren aktive Modi in einer gemeinsamen Matrix zusammen.
* **Fokussierter Modus:** Eine konkrete Modus-Auswahl (z. B. `ZigZag_ATR`) erfolgt nur, wenn gezielt isolierte Modus-Überlappungen analysiert werden sollen.



### 3.3 Status des Feld-Dropdowns (`_combo_field`) bei Confluence

* **Regel:** Sobald als Aggregation **`confluence_count`** oder **`count`** gewählt ist, wird das Feld-Dropdown **deaktiviert (ausgegraut)**.
* **Begründung:** Bei Zählungen untersucht die Engine das Vorhandensein von Signalen (Rows/Services). Ein konkretes Datenfeld wird nur bei Wert-Aggregationen (`AVG`, `SUM`, `MIN`, `MAX`) benötigt.



---

## 🧮 4. Aggregations-Typen im Vergleich

Für die visuelle Darstellung von Häufungen werden drei spezifische Aggregations-Verfahren unterstützt:

### 1. Standard-Confluence (`confluence_count` / `COUNT DISTINCT`)

* **SQL:** `COUNT(DISTINCT feature_id)`
* **Bedeutung:** Zählt exakt, wie viele *unterschiedliche* Services/Plugins im Zeit-/Preis-Raster ein Signal geliefert haben.
* **Einsatz:** Primäre Standard-Analyse für Hotspots.

### 2. Gewichtete Confluence (`weighted_confluence`)

* **Formel:** $\text{Score} = \sum (W_{\text{Service}} \cdot \text{Signal})$ mit $W_{\text{D1}} = 3.0, W_{\text{H4}} = 2.0, W_{\text{M1}} = 1.0$.
* **Bedeutung:** Übergeordnete Makro-Signale wiegen schwerer als Mikro-Signale.
* **Einsatz:** Verhindert, dass reine M1-Rauschen-Häufungen dominieren.

### 3. Intensitäts-Confluence (`intensity_confluence`)

* **Formel:** $\text{Score} = \sum (\text{strength\_value}_{\text{Service\_i}})$.
* **Bedeutung:** Summiert die berechnete Signalstärke aller beteiligten Services.
* **Einsatz:** Unterscheidet zwischen schwachen Konsolidierungs-Hits und hoch-dynamischen Impuls-Überlappungen.


---

## 🛠️ 5. Schritt-für-Schritt Umsetzungsanleitung für die IDE

### Schritt 1: Reader-Erweiterung für `COUNT DISTINCT` (`../../analytics/engine/feature_store_reader.py`)

In `fetch_generic_heatmap()` die Aggregation für Confluence absichern:

# analytics/engine/feature_store_reader.py

if agg_key == "confluence_count":
    # Zählt die Anzahl unterschiedlicher Services pro Raster-Zelle
    agg_sql = "COUNT(DISTINCT feature_id) AS val"
elif agg_key == "count":
    agg_sql = "COUNT(*) AS val"

### Schritt 2: Deaktivierungs-Steuerung im UI-Widget (`../../analytics/ui/heatmap_widget.py`)

In `_update_controls()` des `HeatmapWidget` die Feld-Freigabe an die Aggregation koppeln[cite: 5]:

# analytics/ui/heatmap_widget.py

def _update_controls(self) -> None:
    agg = str(self._combo_agg.currentData() or "confluence_count")
    is_value_agg = agg in ("avg", "sum", "min", "max")
    
    # Feld-Dropdown nur aktivieren, wenn eine Wert-Aggregation gewählt ist
    self._combo_field.setEnabled(is_value_agg)
    if not is_value_agg:
        self._combo_field.setToolTip("Bei Confluence/Count-Aggregation nicht erforderlich.")


### Schritt 3: ViewModel-Anpassung für Multi-Modus-Freigabe (`../../analytics/engine/analytics_view_model.py`)

Sicherstellen, dass `service_mode = "all"` bei Confluence-Queries keine `source_mode`-Einschränkung in SQL einfügt[cite: 5]:

# analytics/engine/analytics_view_model.py

def apply_smart_preset_confluence(self) -> None:
    """Schaltet auf Multi-Service-Confluence um."""
    self.set_service_mode("all")  # Alle Modi einbeziehen
    self.set_heatmap_config("date", "service_id", "", "confluence_count")

---

## 📊 6. Akzeptanzkriterien für die Headless-Validierung (`../../test/test.py`)

1. **Confluence-Distinct-Test:** Bei 3 verschiedenen Services, die auf derselben Bar feuern, liefert `fetch_generic_heatmap(..., agg="confluence_count")` exakt den Wert $3.0$ für die Zelle[cite: 5].
2. **Multi-Modus-Inklusion-Test:** Bei `service_mode = "all"` enthält das SQL-Ergebnis Signale aus *allen* aktiven Modi der gewählten Services (kein Ausschluss einzelner Modi)[cite: 5].
3. **Control-State-Test:** Bei Auswahl von `agg = "confluence_count"` schaltet die UI `_combo_field` auf `enabled = False`[cite: 5].

---

# 21.03.21 – Entscheidungsprotokoll & Umsetzungs-Spezifikation (13.08.2026 20:06)

## 1. Review-Ergebnis (Kapitel vs. Ist-Stand)

| Kapitel-Abschnitt | Status im Bestand |
| --- | --- |
| §4.1 / §5 Schritt 1: `COUNT(DISTINCT feature_id)` | ✅ vorhanden (`../../analytics/engine/feature_store_reader.py` Z. 1283-1286, `HEATMAP_AGGREGATIONS` Z. 117) |
| §5 Schritt 2 / §3.3: Feld-Dropdown-Deaktivierung (F7) | ✅ vorhanden (`../../analytics/ui/heatmap_widget.py` `_update_controls` / `_VALUE_AGGS`) |
| §5 Schritt 3: `apply_smart_preset_confluence()` | ⚠️ vorhanden, aber OHNE `set_service_mode("all")` |
| §3.2 Modus-Dropdown Standard "all" | ✅ vorhanden als `_combo_mode_filter` / „[Alle Modi]" (data "all") |
| §4.2 `weighted_confluence` | ❌ nicht vorhanden |
| §4.3 `intensity_confluence` | ❌ nicht vorhanden (Datenbasis `strength_value` existiert in `srv_swing_*`) |
| E7-Farbskala | ⚠️ vorhanden, aber daten-gebunden (0..vmax, „Meldung 7") statt fest 0..5 |
| §6 AK1 (Distinct-Count) | ✅ test.py „37 b1" (2 Services → 2.0) |
| §6 AK2 (Modus-"all"-Inklusion) | ❌ kein Test vorhanden |
| §6 AK3 (Control-State) | ✅ test.py „20.03.02 o) F7" |

## 2. Entscheidungen (Benutzer-Freigabe + fachliche Bewertung)

1. **Vorgehen: Option (a)** – Bestand nutzen und ergänzen; keine Neu-Implementierung bereits vorhandener Funktionalität.
2. **`weighted_confluence`: NICHT umsetzen (zurückgestellt).** Fachliche Begründung: Der Confluence-Preset läuft mit `all_timeframes=False` (genau EIN Timeframe). Die TF-Gewichte (D1=3.0/H4=2.0/M1=1.0) wären damit konstant → `weighted_confluence` degeneriert zu `confluence_count × Konstante` und liefert keinerlei Zusatzinformation. Eine sinnvolle Umsetzung erfordert eine Multi-TF-Query (`all_timeframes=True`), was außerhalb des Scopes dieses Kapitels liegt (dort existiert bereits das Preset „Service-Timeframe" mit `count`).
3. **`intensity_confluence`: NICHT als eigene Aggregation.** Fachliche Begründung: Die Intensitäts-Analyse ist bereits vollständig über die bestehende Kombination „Aggregation = `SUM` + Feld = `strength_value`" abgedeckt (`srv_swing_momentum`, `srv_swing_structure`, `srv_swing_volume_profile` schreiben den Key). Eine eigene Aggregation wäre nur ein Alias mit fixem Feld, würde aber die §3.3-Feld-Logik brechen (bei Zählungen deaktiviert; bei einer Wert-Aggregation wäre ein implizit fixes Feld inkonsistent) und Services ohne `strength_value` (z. B. `srv_trend_breakout`, `srv_proximity`) still ausblenden → irreführend. Wert-Aggregationen nutzen ohnehin die Viridis-Skala (`heatmap_widget.py` Z. 1638ff), die für Summenwerte kalibriert ist; die diskrete E7-Konfluenz-Skala bleibt Zählungen vorbehalten.
4. **`apply_smart_preset_confluence()`: `set_service_mode("all")` ergänzen (JA).** Fachliche Begründung: Der Kern des Kapitels ist die Hotspot-Orchestrierung über ALLE Modi hinweg (§3.2-Standard = "all"). Hat der Nutzer vorher einen konkreten Modus gefiltert, muss der Preset diesen zurücksetzen, sonst zeigt „[? Signal-Confluence]" still nur den gefilterten Modus (widerspricht der Kapitel-Spezifikation).
5. **AK2-Test ergänzen (JA).** Fachliche Begründung: Die Modus-Inklusion bei `service_mode = "all"` ist das Kernverhalten von §3.2/§6 AK2 und aktuell ungetestet.
6. **E7-Farbskala: Verhalten beibehalten** (daten-gebundene Levels 0..vmax, „Meldung 7" vom 11.08.2026). Nur Kapiteltext wird an das Ist-Verhalten angepasst – die feste 0..5-Skala ist überholt.
7. **Naming: Anpassung an den IST-Stand** – `_combo_mode_filter` / „[Alle Modi]" (data "all") statt Kapitel-`_combo_mode` / „🌐 Alle Modi (Confluence)"; funktional gleichwertig.

## 3. Umsetzungs-Spezifikation (Coding – wird NUR auf manuellen Startbefehl ausgeführt)

### Schritt A: Preset-Reset des Modus-Filters (`../../analytics/engine/analytics_view_model.py`)
In `apply_smart_preset_confluence()` VOR `set_heatmap_config(...)` ergänzen:
- `self.set_service_mode("all")` – bereits idempotent (early-return bei aktuellem `"all"`); bei echter Änderung Dirty-Flag + Refresh von `QUERY_FEATURES` und allen Datenquellen (Tabelle, beide Heatmaps, Scatter, Verteilung).

### Schritt B: AK2-Headless-Test (`../../test/test.py`)
- Temporäre `analytics.duckdb` (im Unterordner `../../test`!) mit `feature_store`-Rows inkl. top-level `source_mode` (z. B. 2 Services × je 2 Modi = 4 Zeilen auf derselben Bar).
- `fetch_generic_heatmap(..., x_dim="date", y_dim="hour", agg="count", service_mode="all")` → Zellenwert exakt `4.0` (alle Modi inkludiert, kein `source_mode`-WHERE).
- `fetch_generic_heatmap(..., agg="count", service_mode="<Modus1>")` → Zellenwert exakt `2.0` (nur ein Modus je Service).
- Kein UI-Test (Regel 4), reiner Reader-Test.

## 4. Implementierungs-Log (Doku-Teil, erledigt)

- **13.08.2026 20:06:** Kapitel 21.03.21 gründlich gegen den Ist-Stand analysiert (Review-Tabelle); Entscheidungsprotokoll + Umsetzungs-Spezifikation (Schritt A/B) in `../AKTUELLE_UMSETZUNG.md` dokumentiert; Git-Commit `phase21_step1` gesetzt. **Kein Coding ausgeführt** – Umsetzung wartet auf den manuellen Startbefehl des Anwenders.
- **13.08.2026 20:35 (Umsetzung, manueller Startbefehl):**
  - **Schritt A:** `apply_smart_preset_confluence()` in `../../analytics/engine/analytics_view_model.py` setzt jetzt VOR der Heatmap-Konfiguration `set_service_mode("all")` – Confluence-Preset resetet den Modus-Filter auf „Alle Modi" (idempotent, early-return bei bereits `"all"`). Docstring ergänzt (21.03.21 Hotspot-Orchestrierung).
  - **Schritt B:** AK2-Headless-Test in `../../test/test.py` (Block „37 k1/k2"): Temp-`analytics.duckdb` im `../../test`-Ordner mit 2 Services × 2 Modi (`source_mode` top-level) auf derselben Bar → `service_mode="all"` liefert Zellwert `4.0`, `service_mode="ModeA"` liefert `2.0`.
  - **Validierung (headless, `.venv`):** `py_compile` beider Dateien OK; `../../test/test.py` → `[PASS] 37 k1` + `[PASS] 37 k2`. Übrige FAILs im Harness sind vorbestehende Schema-Diskrepanzen (Test-Tabellen ohne `instance_hash`-Spalte, „Binder Error") in unveränderten Code-Pfaden (Tests 32/36/20.03.02/20.03.03/39/37 e1/g1/g2/j1) – nicht durch diese Änderung verursacht.
  - Git-Commit `phase21_step2` (Umsetzung) gesetzt.

---

# 21.03.22 – Full Market-Data Sync Button (ServiceWindow)

## 🎯 Zielstellung & Fachliche Motivation
Für umfassende Analysen im `ServiceWindow` müssen alle in `market_data.duckdb` gespeicherten **Symbol:Timeframe-Paare** auf den neuesten Stand gebracht werden. Ein manueller Button in der Filter-/Symbol-Zeile (`layout_symbol`), **direkt links neben dem Papierkorb** (`btn_trash_sets`), stößt den vollständigen Sync aller lokal vorhandenen Paare an. Das rechte Ende des Papierkorb-Buttons schließt dabei bündig mit dem rechten Ende der Parameter-Box ab. Während dieses Vorgangs pausiert der automatische 45-Sekunden-Sync.

---

## ✅ Entscheidungen & Antworten auf IDE-Rückfragen (13.08.2026)

1. **Einbindung in `../../serviceui/service_win.py`:** Es existieren KEINE Methoden `_build_ui()` / `_wire_events()` – Layout-Aufbau (Zeilen 184–395) und Signal-Verdrahtung (ab Zeile 410) passieren direkt im `__init__`. **Positions-Korrektur (User-Feedback 13.08.2026):** Der Button wird im `top_row`-Block (NACH `self.top_row.addWidget(self.main_splitter)`, Zeile ~365) mit Parent `self.ui` erzeugt, aber NICHT in `top_row` platziert – die Einfügung erfolgt im `layout_symbol`-Block (neben `btn_symbol_fav`, Zeile ~468) **direkt vor `btn_trash_sets`** (`insertWidget(indexOf(btn_trash_sets), btn)`). Für die Rechtsbündigkeit wird der bestehende `horizontalSpacer` der `.ui` per `layout_symbol.setStretch(i, 1)` zum Stretch-Spacer gemacht, sodass Papierkorb + Sync-Button am rechten Fensterrand (= rechtes Ende der Parameter-Box) abschließen. Signal-Verdrahtung `clicked.connect(...)` im bestehenden Connect-Block ab Zeile 410.
2. **`sync_market_data(target_pairs=None)`:** Signatur `sync_market_data(target_pairs: Optional[Set[Tuple[str, str]]] = None)`. Bei übergebenem `target_pairs` (nicht `None`) wird **exakt über diese `(symbol, timeframe)`-Paare** iteriert; bei `None`/leer greift der **Fallback auf das bisherige Standard-Raster** (`SYMBOLS` × `get_timeframes()`). Der Delta-Sync-Abgleich mit `get_latest_timestamp(symbol, tf)` bleibt pro Paar voll erhalten (inkrementelles Laden).
3. **Signal & Typing:** `sync_completed = Signal(set)` wird übernommen (voll kompatibel mit `../../main.py`, das ein Set empfängt). `from typing import Optional, Set, Tuple` im `DataSyncWorker` ergänzen.
4. **DB-Zugriffsmuster im Repository:** Generell `DbPool.get(self.db_path)` nutzen (Thread-local, kein manuelles `close()`, konsistent mit `get_symbol_precision` und projektweiten Standards).
5. **Headless-Testbarkeit (Akzeptanzkriterium 2):** `sync_market_data` bzw. der `DataSyncWorker` wird im Test gemockt (Monkeypatching) – **kein echter MT5-Netzwerk-Sync**. Der Test verifiziert rein synchron die Signal-Emission (`service_run_started` vor Start, `service_run_finished` nach `sync_completed`) sowie die Button-Deaktivierung/Aktivierung.
6. **Formatierung:** Rechtsbündige Platzierung in `top_row` bestätigt; entbehrliche Casts (`str(r[0])`) entfallen zugunsten des Filters `if r[0] and r[1]`.

---

## 🛠️ Schritt-für-Schritt Umsetzungsanleitung für die IDE

### Schritt 1: Paar-Abfrage im Repository (`../../repositories/market_data_repository.py`)

Ergänze `../../repositories/market_data_repository.py` um die Abfrage aller gespeicherten Paare (Muster: `DbPool.get`, kein manuelles `close()`, Filter auf nicht-leere Werte statt Casts):

# repositories/market_data_repository.py

def get_all_stored_symbol_tf_pairs(self) -> Set[Tuple[str, str]]:
    """Liefert alle (symbol, timeframe)-Paare, für die bereits Daten in ohlcv_bars existieren."""
    from db_service import DbPool
    con = DbPool.get(self.db_path)
    try:
        rows = con.execute("""
            SELECT DISTINCT UPPER(symbol), UPPER(timeframe)
            FROM ohlcv_bars
            WHERE symbol IS NOT NULL AND timeframe IS NOT NULL
        """).fetchall()
        return {(r[0], r[1]) for r in rows if r[0] and r[1]}
    except Exception as e:
        print(f"WARN [MarketDataRepository] Pair-Abfrage fehlgeschlagen: {e}")
        return set()

---

### Schritt 2: `DataSyncWorker` erweitern (`../../workers/data_sync_worker.py`)

Erweitere den Konstruktor von `DataSyncWorker`, um ein optionales `pairs`-Set zu akzeptieren (Typing `Optional` ergänzen, Signal `Signal(set)`):

# workers/data_sync_worker.py

from typing import Optional, Set, Tuple
# ...
class DataSyncWorker(QThread):
    sync_completed = Signal(set)

    def __init__(self, pairs: Optional[Set[Tuple[str, str]]] = None, parent=None):
        super().__init__(parent)
        self.pairs = pairs

    def run(self):
        # Wenn pairs übergeben wurden, werden nur diese synchronisiert
        updated = sync_market_data(target_pairs=self.pairs)
        self.sync_completed.emit(updated)

---

### Schritt 2b: `sync_market_data(target_pairs=None)` erweitern (`../../data_sync/mt5_sync_service.py`)

- **Signatur:** `sync_market_data(target_pairs: Optional[Set[Tuple[str, str]]] = None)`
- **Logik:**
  - Ist `target_pairs` übergeben (nicht `None`), wird **exakt über diese `(symbol, timeframe)`-Paare** iteriert (statt über das Standard-Raster).
  - Ist `target_pairs` `None` (oder leer), greift der **Fallback auf das bisherige Standard-Raster** (`SYMBOLS` × `get_timeframes()`).
  - Der Delta-Sync-Abgleich mit `get_latest_timestamp(symbol, tf)` bleibt pro Paar voll erhalten (inkrementelles Laden).

---

### Schritt 3: Button & Einbindung in `../../serviceui/service_win.py`

In `../../serviceui/service_win.py` direkt im `__init__` (kein `_build_ui()`/`_wire_events()` – Aufbau und Verdrahtung passieren dort):

# serviceui/service_win.py (in __init__, top_row-Block NACH self.top_row.addWidget(self.main_splitter), Zeile ~365)
# Erzeugung mit Parent self.ui - PLATZIERT wird der Button weiter unten!

self.btn_sync_all_market = QPushButton("🔄 Sync Alle Daten", self.ui)
self.btn_sync_all_market.setToolTip(
    "Aktualisiert ALLE in market_data.duckdb gespeicherten Symbol:Timeframe-Paare aus MT5."
)
self._sync_worker = None

# serviceui/service_win.py (in __init__, layout_symbol-Block neben btn_symbol_fav, Zeile ~468)
# Einfuegung LINKS neben den Papierkorb + Stretch-Spacer fuer Rechtsbuendigkeit
# (Papierkorb-Ende = rechtes Ende der Parameter-Box):

if layout_symbol is not None and self.btn_trash_sets is not None:
    btn_sync = getattr(self, "btn_sync_all_market", None)
    if btn_sync is not None:
        for _i in range(layout_symbol.count()):
            _item = layout_symbol.itemAt(_i)
            if _item is not None and _item.spacerItem() is not None:
                layout_symbol.setStretch(_i, 1)
                break
        idx = layout_symbol.indexOf(self.btn_trash_sets)
        layout_symbol.insertWidget(idx, btn_sync)

# serviceui/service_win.py (in __init__, bestehender Connect-Block ab Zeile ~410)

self.btn_sync_all_market.clicked.connect(self._on_sync_all_market_clicked)


# Neue Handler-Methoden:
@Slot()
def _on_sync_all_market_clicked(self) -> None:
    """Startet den Full-Sync aller in market_data.duckdb vorhandenen Symbol:TF-Paare."""
    if hasattr(self, "_sync_worker") and self._sync_worker is not None and self._sync_worker.isRunning():
        return

    from repositories.market_data_repository import MarketDataRepository
    all_pairs = MarketDataRepository().get_all_stored_symbol_tf_pairs()

    if not all_pairs:
        return

    # 45s-Auto-Sync pausieren via Concurrency-Guard
    from config.event_bus import event_bus
    event_bus.service_run_started.emit()

    self.btn_sync_all_market.setEnabled(False)
    self.btn_sync_all_market.setText("⏳ Sync läuft...")

    from workers.data_sync_worker import DataSyncWorker
    self._sync_worker = DataSyncWorker(pairs=all_pairs, parent=self)
    self._sync_worker.sync_completed.connect(self._on_sync_all_completed)
    self._sync_worker.finished.connect(self._sync_worker.deleteLater)
    self._sync_worker.start()

@Slot(set)
def _on_sync_all_completed(self, updated_pairs) -> None:
    """Nach Abschluss des Full-Syncs: Auto-Sync fortsetzen & UI refreshen."""
    from config.event_bus import event_bus
    event_bus.service_run_finished.emit()

    self.btn_sync_all_market.setEnabled(True)
    self.btn_sync_all_market.setText("🔄 Sync Alle Daten")

    self._refresh_badge_bar()
    if hasattr(self, "service_selector"):
        self.service_selector.refresh()


---

## 📊 Akzeptanzkriterien für die Validierung (`../../test/test.py`)

1. **Pair-Query-Test:** `MarketDataRepository().get_all_stored_symbol_tf_pairs()` liefert alle in `ohlcv_bars` vertretenen Paare als Set von Tuples zurück.
2. **Signal-Emission-Test (headless via Mock):** `sync_market_data` bzw. der `DataSyncWorker` wird gemockt (Monkeypatching) – **kein echter MT5-Netzwerk-Sync**. Der Test verifiziert rein synchron, dass `event_bus.service_run_started` VOR dem Start des Workers und `event_bus.service_run_finished` NACH `sync_completed` emittiert wird.
3. **UI-State-Test (headless via Mock):** `btn_sync_all_market` schaltet während der Ausführung auf `enabled=False` und nach `sync_completed` wieder auf `enabled=True`.

---

## 📝 Implementierungs-Log

**13.08.2026 (Entscheidungen zu IDE-Rückfragen):** Kapitel 21.03.22 um den Abschnitt „Entscheidungen & Antworten auf IDE-Rückfragen" erweitert und die Schritte 1–3 sowie die Akzeptanzkriterien entsprechend präzisiert: (1) Einbindung direkt im `__init__` statt `_build_ui()`/`_wire_events()`; (2) `sync_market_data(target_pairs=None)` mit exakter Paar-Iteration und Fallback auf `SYMBOLS` × `get_timeframes()`; (3) `Signal(set)` + `Optional`-Import im `DataSyncWorker`; (4) DB-Muster `DbPool.get` ohne manuelles `close()`; (5) Headless-Test via Monkeypatch (kein echter MT5-Sync); (6) Casts entfallen, Filter `if r[0] and r[1]`. **Noch kein Coding – Umsetzung wartet auf manuellen Befehl.**

**13.08.2026 (Umsetzung & Validierung, phase21_step4):** Kapitel 21.03.22 vollständig umgesetzt:
- `../../repositories/market_data_repository.py`: `get_all_stored_symbol_tf_pairs()` ergänzt (`DbPool.get`-Muster, UPPER-normalisiert, NULL-Filter).
- `../../workers/data_sync_worker.py`: `DataSyncWorker(pairs=None)` + `sync_completed = Signal(set)`; reicht `target_pairs` an `sync_market_data()` durch.
- `../../data_sync/mt5_sync_service.py`: `sync_market_data(target_pairs=None)` – exakte Paar-Iteration (UPPER-normalisiert, unbekannte TFs gefiltert) mit Fallback auf `SYMBOLS` × `get_timeframes()`; Delta-Sync via `get_latest_timestamp` bleibt pro Paar erhalten.
- `../../serviceui/service_win.py`: `btn_sync_all_market` rechtsbündig in `top_row` (nach Splitter, Zeile ~365), `clicked`-Verdrahtung im Connect-Block (Zeile ~427), Handler `_on_sync_all_market_clicked`/`_on_sync_all_completed` (vor `_refresh_badge_bar`). Concurrency-Guard via `event_bus.service_run_started/finished`; UI-Refresh via `_refresh_badge_bar()` + `service_selector.refresh()`. Zwei Robustheits-Fixes während der Validierung: Guard nutzt `_qt_valid` (shiboken) gegen „Internal C++ object already deleted" nach `deleteLater`, und `_sync_worker` wird nach Abschluss auf `None` gesetzt.
- **Validierung (headless, `../../test/check_21322_full_sync.py` + Block in `../../test/test.py`, kein echter MT5-Sync):** T1 Pair-Query (UPPER + NULL-Filter), T2/T2b Worker-Param-Durchreichung (pairs/None), T2c/T2c2 `target_pairs`-Filter (D1 raus) + Fallback-Raster (6 Paare), T3a–T3e Signal-Emission (`service_run_started` vor Start, `service_run_finished` nach `sync_completed`) + Button-State (enabled/disabled/enabled). **Alle Checks PASS.** `py_compile` OK für alle 4 Dateien. Git-Tag: `phase21_step4`.

**13.08.2026 (Positions-Korrektur, User-Feedback, phase21_step5):** Der `btn_sync_all_market` sitzt nun **links neben dem Papierkorb** in der Filter-/Symbol-Zeile (`layout_symbol`) statt rechts in `top_row`:
- `../../serviceui/service_win.py`: Button-Erzeugung im `top_row`-Block mit Parent `self.ui` (kein `addStretch`/`addWidget` in `top_row` mehr); Einfügung im `layout_symbol`-Block via `insertWidget(indexOf(btn_trash_sets), btn)` – direkt vor den Papierkorb. Der bestehende `horizontalSpacer` der `.ui` wird per `layout_symbol.setStretch(i, 1)` zum Stretch-Spacer, damit Papierkorb + Sync-Button rechtsbündig mit dem rechten Ende der Parameter-Box abschließen.
- **Validierung:** Neue Checks T3f (Sync-Button direkt links neben Papierkorb: `indexOf(sync)+1 == indexOf(trash)`) und T3f2 (Stretch-Spacer vor der Gruppe, `stretch(i) >= 1`) in `../../test/check_21322_full_sync.py` + `../../test/test.py` – **alle 12 Checks PASS**, `py_compile` OK. Git-Tag: `phase21_step5`.

**14.08.2026 (Umsetzung & Validierung, phase22_step4 - phase22_step11):** Kapitel 22.01 (`ind_peak` & Peak-Grabber, PyTrader Engine) vollständig umgesetzt - alle Schritte 1-11 der Umsetzungsanleitung, headless validiert (keine UI-Tests, keine Regressionstests, Praeambel 2):
- **Schritt 1** (`d33c654`, Tag `phase22_step4`): `analytics/engine/peak_models.py` - Dataclasses/Enums (`PeakConfig`, `PeakGrabberConfig`, `GrabberResultRecord` 18-Feld-Vertrag, `SignalDirection`, `GrabberState`), `sl_factor_*`-Methoden, Outcome-PLatzhalter (Frage 4).
- **Schritt 2** (`3c4f902`, Tag `phase22_step5`): `db/schema_initializer.py` - additive, idempotente DDL `grabber_test_results` (18 Spalten, `outcome_status` DEFAULT 'PENDING', Outcome-Spalten NULL) + Index `idx_grabber_run`.
- **Schritt 3** (`e06ebf0`, Tag `phase22_step6`): `analytics/features/definitions/grabber_kernel.py` - Numba/NumPy-State-Machine (IDLE-Start B2, First-Peak-Skip, Guards B6, Zero-GC), Signale 0/1/2/-1/-2, Zustaende 0-3.
- **Schritte 4+5** (`b71090f`, Tag `phase22_step7`): `srv_peak_finder.py` + `srv_peak_grabber.py` - Plugin-Services mit `metadata["category"]="Swing Points/Peak Grabber"`, `depends_on`, `_derive_yellow_window` (Frage 3: Zone-Hit & Zeitfenster, Fallback True ohne Proximity-Signal).
- **Schritt 7** (`e661952`, Tag `phase22_step8`): `repositories/grabber_repository.py` - 18-Spalten-Batch-Upsert (DbPool, `ON CONFLICT` aktualisiert nur Outcome-Felder).
- **Schritt 8** (`12c82b6`, Tag `phase22_step9`): `chart/indicators/ind_peak.py` - `BaseIndicator`-API + `PeakFinderLive` + `PeakGrabberLiveState` + Ringpuffer (B5) + Bootstrap (B4); `latest_proximity_record`-Lese-Helfer additiv in `analytics/engine/feature_store_reader.py`.
- **Schritt 9** (`b45ca08`, Tag `phase22_step10`): UI-Integration (Frage 5) - `config/event_bus.py` Signale `grabber_toggle(dict)` + `grabber_event(object)`; `analytics/ui/order_preview_dialog.py` (schlankes PySide6-Modal, keine Order, kein SQL - MVVM); `analytics_win.py` Button `btn_grabber_peak` (checkable) + Handler (Payload mit realen Combo-Werten); `chart_win.py` `ind_peak`-Registry-Eintrag (additiv), `grabber_toggle`-Subscription mit generischem `set_button_active`-Routing (IoC, `self.indicators.values()`), eigener aufrufender Button `btn_peak_grabber` (gleicher Payload, `blockSignals`-Sync, eigene Akzentfarbe #e65100), eventFilter/Style-Tupel erweitert; `ui/chart_win.ui` Button `btn_peak_grabber` (28x28, Text "PK") nach `btn_indicator_ma`.
- **Schritt 10** (`4cf5597`, Tag `phase22_step11`): `analytics/engine/peak_backtest_runner.py` - `PeakBacktestRunner.run_series()` (grid_1 -> prox_1 -> peak_1 -> grab_1, `run_id = BT-<ts>`-Konvention, `pd.Timestamp(...).to_pydatetime()`, Outcome PENDING/NULL). Abweichung vom Spec-Snippet: `SignalDirection`-Enum statt Raw-String (`.value`-kompatibel mit OrderPreviewDialog).
- **Schritt 11 - Validierung (headless, `test/check_2201_peak_grabber.py` + Block in `test/test.py`):** T1 Schema (18 Spalten + Index + Default PENDING + NULL), T2 Repository-Roundtrip (18 Werte, Feld-Identitaet), T3 Kernel/Live-Paritaet (B2/B3), T4 First-Peak-Skip + IDLE-Start, T5 Div-by-Zero-Guard (B6), T6 Ringpuffer (B5), T7 Bootstrap (B4), T8 Outcome-Platzhalter (PENDING/NULL nach `run_series`), T9 Plugin-Discovery + BaseIndicator-API, T10 EventBus emit->Slot (headless, Signal-Proxy-Mock), T11 run_series-Persistenz + Yellow-Ableitung (Fallback True / Zone-Hit & Zeitfenster). **23/23 Checks PASS.** `py_compile` OK fuer alle neuen/geaenderten Dateien (15 Dateien); `chart_win.ui` XML-validiert. Alle Test-DBs unter `test/` (Regel: keine Test-DBs im Root/data).
- **Schritt 12 (dieser Eintrag, `phase22_step12`):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**Offen (bewusst, Frage 4):** Outcome-Modul (`peak_outcome.py`) - Exit-/Forward-Evaluation folgt als separates Auswertungs-Modul in einem spaeteren Kapitel (Schritt 6 entfaellt in 22.01).

**14.08.2026 (22.01b - User-Anweisungen 1-4a + 4b, `phase22_step13`):** Peak-Grabber-Feinabstimmung nach 22.01 - Anwenderanweisungen umgesetzt, headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Anweisung 1:** `analytics/ui/analytics_win.py` - Peak-Button `btn_grabber_peak` + Handler `_on_grabber_toggled` + Toggle-Bindung entfernt; `grabber_event`-Subscription bleibt als passiver Konsument (OrderPreviewDialog).
- **Anweisung 2:** `chart/indicator_dialog.py` - neue Methode `_indicator_sets()`: Prop-Fenster zeigt nur noch Sets mit `indicator_id == current.indicator_id` ODER Sets, die ausschliesslich Plugins aus `service_plugin_ids` des Indikators enthalten (strenger Filter). Angewendet in `refresh_service_set_list`, `_item_list_names`, `_item_exists`, `_item_save_as`. AnalyticsWindow bleibt global/ungefiltert.
- **Anweisung 3:** keine Anpassung noetig (`show_signals` existierte bereits im `_PEAK_SCHEMA`).
- **Anweisung 4a (Viewback-Parameter):** `analytics/engine/peak_models.py` (`PeakConfig.viewback_bars=3`); `analytics/features/definitions/srv_peak_finder.py` - Rolling-Window statt kumulativem Max/Min (monotone Deques, O(n)), Records NUR an Peak-Aenderungen (neuer Peak ODER Expiry), Supersession aelterer Records innerhalb viewback_bars (`delete_bar_times` im Payload), Records aelter als viewback bleiben persistent, `window_tail` im shared_state fuer Live-Bootstrap; `analytics/features/feature_builder.py` - `store_plugin_payload` loescht `delete_bar_times` VOR dem Upsert (Helfer `_delete_plugin_bar_times`, scoped auf symbol/timeframe/feature_id/instance_hash); `chart/indicators/ind_peak.py` - Schema + `_build_set_definition` (viewback_bars -> peak_1), `PeakFinderLive` auf Rolling-Window umgestellt, Bootstrap via `window_tail`, Live-Bar-Zaehler (`_live_bar_base`/`_live_bar_idx`/`_last_live_rounded`) fuer Expiry pro BAR statt pro Tick; `analytics/engine/peak_backtest_runner.py` - `viewback_bars` durchgereicht.
- **Anweisung 4b (Grabber-Rework, aufgeloeste Interim-Divergenz):** `chart/indicators/ind_peak.py` - `PeakFinderLive.update_scalar()` liefert zusaetzlich die Richtungs-Flags `h_dir`/`l_dir` (+1/-1: echter neuer Fenster-Peak vs. Expiry des alten Extremums); `PeakGrabberLiveState.process_tick_or_bar()` loest die Arm-/Update-/Invalidate-Logik NUR bei echten neuen Peaks aus (Hoch steigt / Tief faellt), Expiry aktualisiert die SL-Referenz stumm (KEIN Event), ARMED-Reversal-Check als separater `if`-Block. Damit keine spurious BUY_UPDATE-Events mehr an den Expiry-Bars 3/4 (strikte Kernel/Live-Paritaet zum kumulativen Kernel).
- **Validierung (headless, `test/`):** `check_2201_peak_grabber.py` **24/24 PASS** (T3 auf strikte Paritaet umgestellt, EXPIRY_BARS entfernt; neues T3b High-Expiry stumm), `check_2201_viewback.py` **11/11 PASS** (V4 auf 4er-Rueckgabe angepasst), `check_2201_parity.py`/`check_2201_calc.py`/`check_2201_runner.py`/`check_2201_reader.py`/`check_2201_schema.py` PASS, Bloecke 22.01 + 22.01b in `test/test.py` alle PASS, `py_compile` OK fuer alle geaenderten Dateien.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**14.08.2026 (22.01c - Bugfixing 1-4, `phase22_step14`):** Peak-Grabber-Bugfixing-Runde auf Basis der 4 User-Fragen, headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Bugfix 1 (Live-Overlay-Gating, "Peak-Linien trotz deaktiviertem Indikator"):** `chart/indicators/ind_peak.py` - `get_live_overlays()` zeichnet die Live-SL-Kreise NUR noch, wenn der Grabber-Modus aktiv ist (`_live_state.is_btn_active`, via `btn_peak_grabber`/`grabber_toggle`) UND die jeweilige Serie sichtbar ist (`show_sl_high`/`show_sl_low`). Vorher wurden die Kreise unabhaengig vom Toggle-Zustand bei jedem Tick gezeichnet, sobald `cur_*_sl != NaN` war; der Finder/die State-Machine laeuft weiter (nur das Zeichnen wird gegated). JS-Seite: `chart/js/04_live_updates.js` - `updateLiveCandle()` ruft `applyLiveOverlays(c.overlays || [])` IMMER auf (auch leer) und `applyLiveOverlays()` erfasst jetzt auch den LEEREN Satz in der Change-Detection: Der erste leere Aufruf entfernt die alten Live-Circles der letzten Live-Zeit aus `_gridCirclesCache` (danach stumm) - keine verwaisten Peak-Kreise mehr nach Deaktivierung.
- **Erkenntnis 2 (zwei getrennte Datenquellen, keine Code-Aenderung):** Der Chart berechnet die SL-Linien In-Memory ueber `ServiceSetEvaluator.execute_set()` (ind_peak.calculate); der Analytics-Service-Picker liest den persistierten `feature_store` aus `analytics.duckdb` (`fetch_service_tf_status`). Ohne HistoricalScanner/LiveAnalyzer-Lauf ist die DB leer -> "No Data" im Picker, waehrend der Chart die In-Memory-Rechnung zeigt. Konsistentes Soll-Verhalten (kein Render-Fehler), in der Doku festgehalten.
- **Bugfix 3 (Order-Vorschau in den Live-Chart verlagert):** `chart/chart_win.py` - `event_bus.grabber_event` wird jetzt im CHART-Fenster konsumiert: neuer Handler `_on_grabber_event` (Lazy-Singleton `OrderPreviewDialog`, `show_record()` aktualisiert denselben Dialog - mehrere Trigger kurz nacheinander erzeugen KEIN Doppel-Fenster/kein Crash, das erste Fenster bleibt offen); `analytics/ui/analytics_win.py` - `grabber_event`-Subscription + `_on_grabber_event` + `OrderPreviewDialog`-Import entfernt (Analytics ist kein Konsument mehr, dort fehlt der Live-Kontext). Der Trigger selbst war korrekt: `ind_peak.update_live_candle()` emittiert `grabber_event` gegated durch `is_btn_active` (Quelle = Peak-Indikator, wie vom User gefordert).
- **Erkenntnis 4 (Finder-Zeichnung korrekt, keine Code-Aenderung):** `srv_peak_finder` zeichnet exakt wie beschrieben: waagerechter Strich/Marker auf SL-Hoehe der Treffer-Bar (`sl_high = peak_high * (1 + sl_offset_pct/100)`), Supersession innerhalb `viewback_bars` (`delete_bar_times`), aeltere Records bleiben persistent. Eine 2-Punkt-Strich-Erweiterung (t ± halbe Barbreite) wurde verworfen, da `_time_real_to_cont` ein reines Dict-Mapping ist (keine Interpolation) und Zwischenzeiten ungemappt blieben.
- **Validierung (headless, `test/`):** neue `check_2201c_fixes.py` **8/8 PASS** (G1-G5 Overlay-Gating: is_btn_active=False -> leer, show_sl_high/low-Flags je Serie; O1-O2 OrderPreviewDialog-Lazy-Singleton: 2x show_record idempotent, Dialog bleibt offen), neue `check_2201c_overlay_clearing.js` (node, VM-Sandbox laedt die ECHTE `04_live_updates.js`) **4/4 PASS** (T1 Live-Zeit-Ersatz, T2 leeres Clearing, T3 Change-Detection stumm, T4 Live-Zeit-Wechsel verdraengt alte). Block 22.01c in `test/test.py` ergaenzt (importlib + node-Subprocess). `py_compile` OK fuer alle geaenderten Dateien (`chart/chart_win.py`, `chart/indicators/ind_peak.py`, `analytics/ui/analytics_win.py`, `test/test.py`, `test/check_2201c_fixes.py`), `node --check` OK fuer `chart/js/04_live_updates.js`.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**14.08.2026 (22.01d - User-Anweisungen 1-3, `phase22_step15`):** Peak-Grabber-Umbau - keine Zeichnung ohne Store-Daten (Anw. 1), SL-Striche NIE verbunden (Anw. 2), Trigger als Dreiecke statt Kreise (Anw. 3). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Anweisung 1 (keine Zeichnung bei deaktiviertem/leerem Indikator):** `chart/indicators/ind_peak.py` - `calculate()` liest AUSSCHLIESSLICH persistierte Service-Daten aus dem feature_store (keine In-Memory-Fantasie-Linien); leerer Store (vor Servicelauf) -> leeres Ergebnis + `_reset_live_state()` (raeumt Live-State, Live-Trigger, Bar-Zaehler, Ringpuffer); `_btn_active` ueberlebt den Reset und wird beim naechsten Bootstrap via `set_button_active` uebertragen (User muss den Grabber nicht neu aktivieren).
- **Anweisung 2 (Peak Finder - Striche NIE verbunden):** `chart/indicators/ind_peak.py` - `calculate()` erzeugt je Finder-Record eine SEPARATE LineSeries `sl_high_<t0>`/`sl_low_<t0>` mit 2 Punkten auf gleichem SL-Value (t0 -> Zeit der naechsten Bar aus der df-Zeit-Map, letzte df-Bar = 1 Punkt) - keine gemeinsame Sammel-Serie mehr (die vorher die Punkte ueber Stunden hinweg verband).
- **Anweisung 3 (Peak Grabber - KEINE Kreise, Orderpunkt = Dreieck):** `chart/indicators/ind_peak.py` - `get_live_overlays()` zeichnet nur noch den letzten Live-Trigger als Dreieck (arrowDown=SELL bei peak_high / arrowUp=BUY bei peak_low); Proximity-Circles & Grid-Lines sind reine Berechnungshilfen und werden nie gezeichnet; `calculate()` rendert srv_peak_grabber-Records als hit_circles-Dreiecke (arrowDown/arrowUp). Deaktivierter Grabber -> keine Overlays (raeumt Trigger beim Deaktivieren).
- **Neue Lesemethode:** `analytics/engine/feature_store_reader.py` - `fetch_plugin_records(symbol, timeframe, feature_id, limit=20000)` (read-only, feature_data-JSON + bar_time als Wanduhr-Epoch, aufsteigend sortiert).
- **Blocker-Analyse (Conn-Handling im Test):** `store_plugin_payload()` schliesst eine UEBERGEGEBENE Connection selbst (Bestandsverhalten `own_connection=True` bei `con != None`, dokumentiert in `test/test.py` Block 17/18/19/24) - KEIN Produktionsbug (kein Caller uebergibt con); der Test `check_2201d_fixes.py` oeffnet daher pro Store-Aufruf eine frische Wegwerf-Connection. Isoliert verifiziert: zwei parallele Connections zu derselben DuckDB-Datei ueberleben einander (Debugging-Skripte `tmp_conn_test3.py`, danach geloescht).
- **Validierung (headless, `test/`):** neue `check_2201d_fixes.py` **16/16 PASS** (G1-G6 get_live_overlays: deaktiviert leer / SELL arrowDown bei peak_price / BUY arrowUp / ohne Trigger leer / ohne Live-State leer / keine SL-Kreise; C1-C3 calculate: leerer Store -> leer + Live-State-Reset, Striche 2 Punkte gleicher Value NIE verbunden, Endpunkt = naechste Bar-Zeit 2060, keine Sammel-Serie 'sl_high', Trigger-Dreiecke arrowDown bei peak_high 102.0 / arrowUp bei peak_low 98.0; O1 OrderPreviewDialog 2x show_record idempotent). Block 22.01d in `test/test.py` ergaenzt (importlib-Muster 22.01c). `py_compile` OK fuer alle geaenderten Dateien (`chart/indicators/ind_peak.py`, `analytics/engine/feature_store_reader.py`, `test/test.py`, `test/check_2201d_fixes.py`). Test-DB `check_2201d.duckdb` in `test/` (Regel: keine Test-DBs im Root/data), wird vom Test selbst aufgeraeumt.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**14.08.2026 (22.01e - Performance-Fix chart_win: ewiger Chart-Aufbau + Maus-Pan blockiert, `phase22_step16`):** Bugfixing-Modus - User-Meldung "Grafik dauert ewig aufzubauen inkl. Skalen" + "Grafik laesst sich nicht mit Maus verschieben (Loops?)". Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Ursache (Kern):** `ind_peak.calculate()` (22.01d) erzeugte seit dem Store-Umbau **EINE LineSeries pro Finder-Record** (`sl_high_<t0>`/`sl_low_<t0>`). `renderLineSeries` (chart/js/03_chart_rendering.js) ruft pro Eintrag `chart.addSeries()` auf - bei 617 realen Records also **1.234 LWC-Series** pro Chart-Rebuild. Jede addSeries triggert Timescale/PriceScale-Neuberechnung -> Chart-Aufbau dauert ewig, LWC ist ueberlastet -> Maus-Panning/Interaktion blockiert.
- **Fix 1 (`chart/indicators/ind_peak.py`, User-Anweisung 2 bleibt erfuellt):** Die SL-Striche als **ZWEI Sammel-Series** (`sl_high`/`sl_low`) statt einer Serie pro Record. Zwischen zwei Strichen wird ein **Luecken-Marker `{time, value: None}`** eingefuegt (LWC-null = Luecke) -> die Striche sind NIE verbunden (keine Fantasie-Verbindung ueber Stunden). Die Luecken-Zeit ist immer die **naechste echte df-Bar-Zeit** (`_next_bar_after`, binaere Suche) - kein Phantom-Slot in der Timescale (22.01-Lektion). Edge: direkt benachbarte Records (Strich-Ende == naechster Strich-Start) -> 1-Punkt-Strich (selten, minimale Verbindung, keine doppelten Zeitstempel).
- **Fix 2 (`analytics/engine/feature_store_reader.py`):** `fetch_plugin_records()` um optionale Zeitfenster-Filter **`up_to_epoch`/`from_epoch`** erweitert (SQL `EXTRACT('epoch' FROM bar_time)::BIGINT <= ? / >= ?`); `ind_peak.calculate()` begrenzt die DB-Last auf das df-Fenster (`up_to = max(df.time)`) - Records jenseits der letzten Bar werden im Render-Payload ohnehin verworfen.
- **Fix 3 (`chart/chart_win.py`):** `_collect_render_payload()` verwirft LineSeries, deren Datenpunkte nach dem Zeitfenster-Filter (Tier-1) vollstaendig ausserhalb liegen (generisch, Open/Closed) - vorher gingen auch leere Series als addSeries an LWC.
- **Fix 4 (`chart/indicators/ind_peak.py`, Tick-Pfad):** `_is_current_bar_yellow()` - `FeatureStoreReader(db_path=None)` auf Default korrigiert (vorher warf `DbPool.get(None)` bei JEDEM Tick eine Exception -> stiller Fallback immer True, Yellow-Gate greift jetzt wirklich) + **Pro-Candle-Cache** (`_yellow_rounded`/`_yellow_value`: Query nur 1x pro neuer gerundeter Bar, nicht pro Tick); Cache-Reset in `_reset_live_state`.
- **Validierung (headless, `test/`):** `check_2201d_fixes.py` erweitert auf **19/19 PASS** (G1-G6, C1-C3, C4 up_to_epoch-Filter wirkt, C4b from+up_to kombiniert, C2e Performance-Fix: KEINE Serie pro Record, C2b/C2c/C2d auf 2-Sammel-Series-Semantik mit null-Luecken umgestellt; Test-df lueckenlos 1000..4000 im 60s-Raster). Performance-Smoke auf echter analytics.duckdb + 10k M1-Bars: `calculate()` **0.061s**, **2 LineSeries** (sl_high/sl_low je 761 Punkte inkl. 72 Luecken) statt 1.234 Series. `py_compile` OK fuer alle geaenderten Dateien. Kein JS geaendert (LWC unterstuetzt `value: null` nativ; `_clean_nan` laesst None durch -> JSON null).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).
**14.08.2026 (22.01f - Bugfix "Linien trotz ausgeschalteter Indikatoren", phase22_step17):** User-Meldung: SL-Linien/Marker werden gezeichnet, obwohl der PK-Button AUS ist. Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Ursache:** Der PK-Button (`btn_peak_grabber`) und der Plugin-Zustand (`IndPeak._btn_active`) waren von `indicators_state['ind_peak']['active']` entkoppelt. `_collect_render_payload()` rendert ind_peak NUR bei `active=True` - die DB (symbol_tf_states fuer SILVER H1/M1/M5/M10/M2, BTCUSD M1) sagte aber `active=true`, der Button zeigte false -> SL-Linien/Marker wurden gezeichnet, obwohl der Grabber optisch AUS war.
- **Fix (`chart/chart_win.py`, +57 Zeilen):** neue `_sync_peak_button_from_state()` (synchronisiert PK-Button + Plugin-`_btn_active` aus `indicators_state`); `_on_grabber_toggle()` zieht `indicators_state['ind_peak']['active']` nach (persistiert via `save_state` + rendert neu); Sync-Aufrufe in `__init__`, `on_symbol_changed`, `on_tf_changed`, `_on_indicator_params_updated`; CRLF normalisiert.
- **Validierung (headless, `test/`):** neue `check_2201f_state_sync.py` **21/21 PASS** (S1-S6: Start-Sync, State False->Button unchecked, State True->Button checked, save+render-Gate, Settings-Dialog sync, Idempotenz); `check_2201d_fixes.py` weiter **22/22 PASS**. `py_compile` OK fuer `chart/chart_win.py`.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**14.08.2026 (22.01g - Bugfixing 1-6 Peak-Grabber nach 22.01f, phase22_step18):** User-Meldung: (1) Skala veraendert sich bei On/Off-Toggle, (2) wild verbundene SL-Linien (nur sl_low), (3) Orderpunkt/Updates 30$ ueber der Bar, (4) H1/5M-Probleme, bei 5M gar keine Orderpunkte, (5) Orderfenster kommen auf 5M oft hintereinander, (6) Grafikeinfrieren. Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Bugfix 1 (Skala springt beim On/Off):** `chart/indicators/ind_peak.py` - SL-Serien (`sl_high`/`sl_low`) bekommen `no_autoscale: True`; `chart/js/03_chart_rendering.js` - `renderLineSeries()` setzt bei `line.no_autoscale` `autoscaleInfoProvider: function() { return null; }` -> die Serie nimmt NICHT an der Preisskalen-Autoscale teil, die Skala bleibt beim Toggle unveraendert (Indikator additiv).
- **Bugfix 2 (wild verbundene SL-Linien):** Ursache: LWC-v5-Default `LineType.Simple` verbindet `null`-Punkte hindurch -> zwei SL-Striche werden diagonal verbunden (nur sl_low auffaellig, weil sl_high-Records seltener sind). Fix (`chart/js/03_chart_rendering.js`): `renderLineSeries()` setzt `lineType: LightweightCharts.LineType.WithGaps` bei addSeries UND applyOptions -> `{time, value: null}` erzeugt eine ECHTE Luecke, die Striche bleiben isolierte waagerechte Segmente. Die Python-Daten waren korrekt (Test `check_sl_stroke_bug.py` beweist Gap-Punkte im Fenster).
- **Bugfix 3 (Orderpunkte 30$ ueber der Bar):** Ursache: Batch-Marker nutzten `peak_high`/`peak_low` (Rolling-Fenster-Extrema, bei SILVER oft >5$ daneben) statt des Bar-Preises. Fix (`chart/indicators/ind_peak.py`): `_order_price()` berechnet den Orderpunkt aus der TRIGGER-BAR (`bar_ohlc`-Map aus df) - SELL = Bar-High * (1 + sl_offset_pct/100), BUY = Bar-Low * (1 - sl_offset_pct/100); Fallback auf persistierte Peak-Preise. Live-Pfad: `get_live_overlays()` nutzt jetzt `entry_price` der Trigger-Bar * (1 +/- offset) statt `trig.peak_price` (Rolling-Extremum).
- **Bugfix 4 (5M keine Orderpunkte):** gleiche Ursache wie Bugfix 3 - die alten Marker-Preise (28-121) lagen ausserhalb der sichtbaren Skala; mit bar-basierten Preisen (~65) liegen sie direkt an der Bar (analytics.duckdb: 434 M5-Grabber-Records, Trigger {1:11, -1:119} existierten).
- **Bugfix 5 (Orderfenster-Flut):** `chart/chart_win.py` - `_on_grabber_event()` bekommt ein Bar-Gate (`_last_grabber_bar_key`, TF-gerundete Bar-Zeit): NUR EIN Orderfenster pro Bar, mehrere Trigger/Updates derselben Bar werden unterdrueckt; Reset bei Symbol-/TF-Wechsel.
- **Bugfix 6 (Grafikeinfrieren):** Folge von Bugfix 5 (Dialog-Storm bei jedem M5-Tick) + 22.01e-Series-Fix; mit dem Bar-Gate und WithGaps behoben (kein eigener Code, verifiziert).
- **Validierung (headless, `test/`):** neue `check_2201g_fixes.py` **16 PASS/0 FAIL** (no_autoscale-Flag, Gap-Punkte im Fenster, keine Diagonalen im Fenster - Filter wie `_collect_render_payload`); neue `check_2201g_live_marker.py` **14 PASS/0 FAIL** (Fake-Reader mit Grabber-Records IM df-Bereich: SELL/BUY/UPDATE-Marker an der Bar, nicht am Rolling-Extremum); `check_2201d_fixes.py` auf neue Bar-Semantik angepasst **22/22 PASS** (G2/G3/C3b/C3c pruefen jetzt Bar-Preis statt peak_high/peak_low); `check_2201f_state_sync.py` **21/21 PASS**; Live-Preis-Check (Sell 65*1.0015=65.0975 / Buy 64.5*0.9985=64.4032) und Bar-Gate-Logik OK; `node --check` OK fuer alle 6 JS-Dateien; HTML-Template-Check (WithGaps + no_autoscale eingebettet); `py_compile` OK fuer `chart/chart_win.py`, `chart/indicators/ind_peak.py`.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).


**14.08.2026 (22.01h - Bugfix "Objekte vor vorhandenen Kerzen" (LWC-Phantom-Slots), phase22_step19):** Bugfixing-Modus - User-Meldung: Chart-Objekte (SL-Striche/Marker) erscheinen weit links VOR den aeltesten Kerzen (z. B. 2013 auf H1/D1, obwohl die Kerzen erst 2024 beginnen). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Ursache:** Der Python-Filter `_collect_render_payload()` haengt an den Tier-1-Fenster-Bounds (`_js_window_first_real`/`_js_window_last_real`). In manchen Pfaden (Indikator-Toggle/Parameter-Aenderung VOR dem ersten vollstaendigen Refresh, direkt nach Start oder nach Symbol/TF-Wechsel) waren diese Bounds `None` -> der Zeitfenster-Filter hatte KEINE Grenze und der komplette historische Record-Bestand (persistiert aus frueheren Service-Laeufen mit vollem Historien-Scan, ohne Range-Cleanup) ging ungefiltert an JS -> LWC erzeugt fuer Zeiten weit ausserhalb des Kerzenbereichs leere Timescale-Slots (Phantom-Slots), die Objekte erscheinen vor den Kerzen.
- **Fix 1 (`chart/chart_win.py`):** Neuer Guard vor jedem `_collect_render_payload`-Aufruf: Sind die Fenster-Bounds `None`, werden sie defensiv aus dem Datenpuffer abgeleitet (`_derive_js_window_bounds_from_buffer()`, idempotent: setzt nur fehlende Bounds, `TIER1_WINDOW`-Begrenzung, `last_real`-Kante) -> der Filter hat IMMER eine Grenze, auch vor dem ersten vollstaendigen Refresh.
- **Fix 2 (`chart/indicators/ind_peak.py`):** `fetch_plugin_records()` fuer `srv_peak_finder`/`srv_peak_grabber` bekommt zusaetzlich `from_epoch = int(min(df["time"]))` (Untergrenze = aelteste df-Bar) -> db-seitiger Zuschnitt auf den darstellbaren Bereich; der Tier-1-Filter faengt zwar auch, der Zuschnitt reduziert zusaetzlich DB-Last/JSON-Parsing (22.01e-Muster erweitert).
- **Fix 3 (`chart/js/03_chart_rendering.js`):** Defense-in-Depth auf JS-Seite: neue Funktion `_overlayTimeBounds()` (Kerzen-Zeitbereich aus `rawCandleData`); `applyChartRenderPayload()` filtert `p.lines` und `p.hit_circles` VOR dem Rendering auf `[min, max]` -> Punkte ausserhalb des Kerzenbereichs (Raw-Epochs, Phantom-Slots) erreichen LWC gar nicht erst.
- **Validierung (headless, `test/`):** bestehende JS-Node-Harnesses (`diag_prod_repro.js`, `diag_lwc_crash.js`) decken den Guard ab; `node --check` OK fuer alle geaenderten JS-Dateien; `py_compile` OK fuer `chart/chart_win.py`, `chart/indicators/ind_peak.py`.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**14.08.2026 (22.01i - Bugfix "[JS ERROR] Uncaught Error: Value is null | L7:797" + veraltete TwoTier-Chunk-Antwort, phase22_step20):** Bugfixing-Modus - User-Meldung: `[JS ERROR] Uncaught Error: Value is null | L7:797` im Chart, zeitgleich `[TwoTier] Veraltete Chunk-Antwort verworfen (id=58 != 62)`. Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Root-Cause (zweifelsfrei verifiziert):** `L7:797` = `ensureNotNull(null)` in LWC-5.2.0-Dist. Exakter Stack (Test H in `test/diag_lwc_crash.js` reproduziert, identisch zur Produktion): `a (ensureNotNull)` -> `xt.Line [as Mh]` (SeriesBarColorer lineStyleFn) -> `Ce.xb`/`Ce.DM` (line-pane-view-base `_fillRawPoints`) -> Render-Zyklus. Mechanik: LWC v5 `setData` verlangt NACH ZEIT SORTIERTE Serien-Daten; `PlotList.setData` speichert die Reihen in Input-Reihenfolge, aber `PlotList.valueAt()` (SeriesColorer) binaersucht nach dem sortierten `row.index` -> unsortierte Input-Daten -> binaere Suche verfehlt -> `ensureNotNull(null)` -> "Value is null"-Crash beim Rendern der LineSeries.
- **Nicht die Ursache (ausgeschlossen):** trailing/leading `value: null` (WithGaps), Marker mit Raw-Epoch ausserhalb, doppelte Zeitstempel, Live-Pfad (`updateLiveCandle` fasst LineSeries nie an), Produktions-`_stroke_series` selbst (statisch monoton, `t1 == t_next`-Sonderfall vermeidet Duplikate; `test/diag_prod_repro.js` PASS mit exakter Produktions-Nachbildung), `fetch_plugin_records` sortiert `ORDER BY bar_time ASC` (feature_store_reader.py).
- **Wahrscheinlichster Produktions-Trigger:** Ein Record, dessen `bar_time` NICHT in `_time_real_to_cont` liegt (z. B. Mid-Bar-Zeitstempel oder Records aus frueheren Service-Laeufen mit vollem Scan), ueberlebt den Zeitfenster-Filter -> bleibt als RAW-Epoch (~1.7e9) zwischen kont-Zeiten (~1e6) -> UNSORTIERTE LineSeries-Daten -> Crash. Die Chunk-Ansicht zeigte denselben Fehler zeitgleich, da der Chunk-Pfad (`applyOlderDataChunk`) den `_overlayTimeBounds`-Guard (22.01h) NICHT hatte.
- **Fix 1 (`chart/js/03_chart_rendering.js`):** `renderLineSeries()` sortiert die Daten VOR `series.setData()` defensiv aufsteigend nach Zeit und entfernt Duplikate (letzter Wert gewinnt = exakt LWC-Row-Overwrite); ungueltige Punkte (`time` keine finite Zahl) werden gefiltert. Geschuetzt sind BEIDE Pfade (Full-Update + Chunk, da beide durch `renderLineSeries` laufen).
- **Fix 2 (`chart/js/06_two_tier.js`):** `applyOlderDataChunk()` bekommt den `_overlayTimeBounds()`-Guard (analog `applyChartRenderPayload`, 22.01h): `rp.lines`/`rp.hit_circles` werden vor dem Rendering auf den Kerzenbereich gefiltert -> Raw-Epochs/Phantom-Slots werden im Chunk-Delta verworfen.
- **Fix 3 (`chart/js/01_core.js`):** `window.onerror` loggt jetzt zusaetzlich den Stack (`[JS ERROR] Stack: ...`), damit beim naechsten Repro die exakte LWC-Call-Site sichtbar ist.
- **Validierung (headless, `test/`):** `node --check` OK fuer `01_core.js`, `03_chart_rendering.js`, `06_two_tier.js`. `test/diag_lwc_crash.js`: Tests A-G/I PASS; Test H (UNSORTIERTE Zeiten, SL-Strich-Muster) crasht auf ROHER LWC-`setData` = erwartete Negativ-Kontrolle (beweist: ohne Fix crasht exakt dieses Muster). `test/diag_prod_repro.js` erweitert um `scenarioUnsortedFix` **PASS**: unsortierte SL-Strich-Daten + Raw-Epoch mitten zwischen kont-Zeiten durch den ECHTEN `renderLineSeries` -> abgefangenes `setData`-Array aufsteigend sortiert + keine doppelten Zeitstempel (Monotonie-/Dedup-Check), kein Render-Crash; `applyOlderDataChunk` mit Raw-Epoch im Delta -> Guard filtert -> kein Crash. `py_compile` OK fuer geaenderte Python-Dateien.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**15.08.2026 (23.01 - Architektur-Map fuer Bugfix-Entkopplung, phase23_step1):** Grundlagen-Schritt fuer das Ziel, Bugfix-Zeit und Token-Kosten von ~1.000 s auf ~100 s zu senken (Wechsel auf DeepSeek-Flash-Routine-Bugfixes erst NACH der Entkopplung). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Ziel:** Jeder Bugfix-Prompt startet mit der Landkarte und liest nur noch die minimalen Datei-Sets statt ganzer God-Files -> weniger Token, schnellere Iteration.
- **Umgesetzt:** neue Datei `../Architektur_map.md` mit Teil A (Layering & Invarianten: DB -> Repositories -> Engine -> UI, EventBus, DbPool, Wanduhr-Garantie, `srv_`/`ind_`-Naming), Teil B (Domaenen-Karte aller 117 Py- + 6 JS-Dateien mit Zeilenzahlen und 1-Zeilen-Verantwortlichkeit), Teil C (Bug-Routing-Tabelle: 24 Symptom-Bereiche -> minimale Datei-Sets in Lese-Reihenfolge + Test-Validatoren), Teil D (Hotspots/Quer-Kopplungen & God-File-Split-Vorschlaege fuer Top-5), Teil E (Wartung der Karte). Basis: Analyse von 117 Py-Dateien / 44.105 Zeilen + 6 JS-Dateien / 1.684 Zeilen; 9 God-Files ~45 % des Codes (`service_win.py` 3.264, `master_tree.py` 2.511, `service_selector_dialog.py` 2.414, `heatmap_widget.py` 2.483, `feature_store_reader.py` 2.410, `indicator_dialog.py` 1.893, `analytics_view_model.py` 1.886, `chart_win.py` 1.630, `analytics_win.py` 1.500); Quer-Kopplungen erfasst (chart_win -> serviceui+analytics, analytics_win -> 3x serviceui, service_selector_model -> chart.indicators+serviceui, ind_peak -> analytics.engine, srv_trend_*/srv_swing_momentum -> chart, service_win -> alle Schichten); vorhandene Entkopplungs-Bausteine erfasst (EventBus `config/event_bus.py`, Plugin-Registry, Mixins `ServiceParamColumnsMixin`/`ContentScrollMixin`/`NamedItemActionsMixin`, JS-Hook-System, Repository-Muster).
- **Nutzen:** Typischer Fix = 1-3 Dateien a 200-400 Zeilen statt 3-5 Dateien a 800-3.000 Zeilen; die Karte macht die Lese-Reihenfolge deterministisch (gezieltes Erst-Lesen statt Volltext-Scan).
- **Naechste Schritte (nur auf Anweisung):** 23.02 Root-Orphans sortieren (`db_service.py`, `symbol_repository.py`, `window_state_repository.py`, `analytics_profile_repository.py` -> `repositories/`; `statistic_win.py`, `properties_win.py` -> `ui/`) - reine Ordnung, keine Logikaenderung; 23.03 God-File-Splits (Top-5, inkrementell).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Abschluss von Schritt 1 der Hauptanweisung (Architektur-Landkarte zuerst, dann inkrementelle God-File-Splits; Modellwechsel auf Flash erst NACH der Entkopplung).

**15.08.2026 (23.02 - Root-Orphans sortiert: repositories/ & ui/, phase23_step2):** Reine Ordnung ohne Logikaenderung: 6 Root-Orphans in die Pakete verschoben. Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **git mv (History erhalten):** `symbol_repository.py`, `window_state_repository.py`, `analytics_profile_repository.py`, `db_service.py` -> `repositories/`; `statistic_win.py`, `properties_win.py` -> `ui/` (Commit `c164b68`, 17 Dateien, +113/-53).
- **Root-Shim `db_service.py`:** reiner Re-Export aus `repositories.db_service` (alle Namen inkl. `main()`); CLI-Einstieg `python db_service.py` (MT5-Sync) und test.py-Teil-30-Fassaden-Identitaetschecks bleiben gueltig. Es ist KEINE Logik im Shim.
- **Interne Pfade der verschobenen Dateien angepasst:** `window_state_repository` (`BASE_DIR` eine Ebene hoeher fuer `APP_DB_PATH`), `analytics_profile_repository` (importiert jetzt direkt aus `db.db_pool`/`db.db_utils`), `statistic_win` (UI-Pfad `BASE_DIR / "statistic_win.ui"`), `properties_win` (`db_path -> BASE_DIR.parent / data`).
- **13 Import-Stellen in 8 Importern aktualisiert:** `main.py`, `state_manager.py`, `analytics/ui/analytics_win.py`, `chart/chart_win.py`, `analytics/engine/analytics_view_model.py`, `serviceui/symbols_win.py`, `serviceui/service_win.py`, `ui/window_manager.py`; zusaetzlich interner Alt-Import in `ui/statistic_win.py` (im Scan gefunden) und `test/test.py` (4 Stellen inkl. Mehrzeilen-Import `_APR39`).
- **Paket-Docstrings aktualisiert:** `repositories/__init__.py` (neue Mitglieder, Invariante: kein Import von main.py/db_service.py bleibt erfuellt - Repos importieren direkt aus `db.db_pool`/`db.db_utils`) und `ui/__init__.py` (WindowManager + statistic_win + properties_win).
- **Validierung (headless, `test/`):** Alt-Import-Scan im gesamten Quellcode (ohne docs/): 0 Treffer; `py_compile` OK fuer alle 18 geaenderten Dateien; neuer gezielter Check `test/check_2302_migration.py` **30/30 PASS** (Zielpfade, Alt-Root-Entfernung, Shim-Export inkl. main, keine Alt-Importe, Repository-Invariante); Import-Smoke-Test mit `.venv`-Python: alle verschobenen Module + Shim importierbar (`get_symbol_repository`, `WindowStateRepository`, `AnalyticsProfileRepository`, `main` vorhanden).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**15.08.2026 (23.03 - God-File-Split #1: indicator_dialog.py, phase23_step3):** Erster God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** 5 Top-Level-Elemente (Z61-320: DialogServiceSetRunWorker, _ServiceStack, _jsonify_style_objects, _PresetItemAdapter, _ServiceSetItemAdapter) + IndicatorSettingsDialog (Z323-2127, 52 Methoden). Nur chart_win.py importiert IndicatorSettingsDialog; die 5 Helfer werden ausschliesslich intern genutzt -> sicherer Split ohne externen Caller.
- **Neue Datei chart/indicator_dialog_support.py (10.522 Bytes):** enthaelt die 5 Support-Klassen 1:1 (keine Logik-Aenderung). Deterministisch per test/build_2303_support.py aus den Original-Zeilen extrahiert, Block-Identitaet per AST/Text-Check verifiziert.
- **Hauptdatei chart/indicator_dialog.py (88.859 -> 78.744 Bytes, -10.115):** Imports getrimmt (QThread/Signal/QSize aus QtCore entfernt -> nur Qt; QStackedWidget aus QtWidgets entfernt; NamedItemAdapter aus named_item_actions-Import entfernt -> nur NamedItemActionsMixin) und der 260-Zeilen-Block durch einen Import ersetzt: from chart.indicator_dialog_support import (DialogServiceSetRunWorker, _ServiceStack, _jsonify_style_objects, _PresetItemAdapter, _ServiceSetItemAdapter).
- **Validierung (headless, test/):** py_compile OK fuer beide Dateien; AST-Check: Hauptdatei enthaelt nur noch IndicatorSettingsDialog (genau 1 Klasse), 0 Code-Referenzen auf entfernte Symbole (QStackedWidget/QSize/QThread/Signal/NamedItemAdapter); Import-Smoke mit .venv-Python: beide Module importierbar, alle 5 Support-Symbole aufloesbar; test/build_2303_remove_block.py bestaetigt Block-Identitaet 1:1 (9.856 Bytes).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).
**15.08.2026 (23.03 - God-File-Split #2: chart_win.py, phase23_step4):** Zweiter God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** chart_win.py (92.461 Bytes/1.815 Zeilen) ist ein God-File mit einer Klasse PyTraderChartWindow (Z215-1808, 1.594 Zeilen, ~55 Methoden) plus 7 Top-Level-Helfer. Die 5 Worker-/Serializer-/Bridge-Klassen (WebEngineConsolePage, ChartBridge, ChartDataSerializer, GridDataSerializer, OlderDataWorker, Z103-212) sind bereits top-level, werden aber ausschliesslich von der Window-Klasse genutzt (kein externer Caller im gesamten Quellcode) -> sicherer erster Split-Schritt ohne Logik-Eingriff in die Window-Klasse (konsistent mit Split #1-Muster).
- **Neue Datei chart/chart_win_workers.py (4.869 Bytes/124 Zeilen):** enthaelt die 5 Klassen 1:1 (keine Logik-Aenderung), Header nach Split #1-Muster, UTF-8 ohne BOM, LF. Deterministisch per test/build_2303_workers.py aus den Original-Zeilen extrahiert; Block-Identitaet (110 Zeilen/4.559 Bytes) textuell 1:1 verifiziert.
- **Hauptdatei chart/chart_win.py (92.461 -> 88.024 Bytes, -4.437):** nur 3 Aenderungen: (1) QtCore-Import bereinigt (QObject, QThread entfernt - wandern in die neue Datei), (2) QWebEngineCore-Import-Zeile entfernt, (3) Import 'from chart.chart_win_workers import ChartBridge, ChartDataSerializer, GridDataSerializer, OlderDataWorker, WebEngineConsolePage' nach dem symbols_win-Import eingefuegt. Line-Endings (CRLF/LF-Mischung) unveraendert erhalten.
- **Validierung (headless, test/):** py_compile OK fuer beide Dateien; AST-Check: chart_win.py enthaelt nur noch find_null_fields/_clean_nan/PyTraderChartWindow, neue Datei exakt die 5 Klassen; Import-Smoke mit .venv-Python: beide Module importierbar, alle 5 Referenzen in chart_win.py korrekt aufgeloest (Klassen aus chart.chart_win_workers); git diff: exakt 2 insertions/114 deletions, kein Kollateralschaden; Scan ueber alle Py-Dateien (ohne docs/): keine andere Datei referenziert die verschobenen Klassen.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).
**15.08.2026 (23.03 - God-File-Split #3: chart_win.py-Mixins, phase23_step5):** Dritter God-File-Split der Entkopplungs-Roadmap. Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** Die Window-Klasse PyTraderChartWindow (52 Methoden nach Split #2) wurde per AST-Scan in 5 thematische Gruppen zerlegt (INDICATOR 17, RENDER 6, REFRESH 8, TWOTIER 9, SYMBOLTF 12) plus Cross-Referenz-Analyse (Methoden-Callgraph + Modul-Globals pro Gruppe inkl. try/except-Importen). `_normalize_indicators_state` (referenziert PyTraderChartWindow._LEGACY_IND_ID/_NEW_IND_ID), `__init__` und `eventFilter` bleiben in der Hauptklasse (Zirkularimport-Vermeidung). `find_null_fields`/`_clean_nan` werden von REFRESH/TWOTIER genutzt -> nach chart/chart_win_workers.py verschoben.
- **5 neue Mixin-Dateien:** chart/chart_win_indicators.py (ChartIndicatorMixin, 17 Methoden), chart/chart_win_render.py (ChartRenderMixin, 6), chart/chart_win_refresh.py (ChartRefreshMixin, 8), chart/chart_win_twotier.py (ChartTwoTierMixin, 9), chart/chart_win_symboltf.py (ChartSymbolTfMixin, 12) - 1:1 extrahiert (keine Logik-Aenderung), deterministisch per test/build_2303_mixins.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen, @Slot() inklusive), Methoden-Identitaet per AST/Text-Check verifiziert.
- **Hauptdatei chart/chart_win.py (88.024 -> 22.026 Bytes, -65.998):** Basis erweitert auf `QMainWindow, ChartIndicatorMixin, ChartRenderMixin, ChartRefreshMixin, ChartTwoTierMixin, ChartSymbolTfMixin`; 5 Mixin-Importe ergaenzt; 52 Methoden + 2 Helfer entfernt. Verbleibende Mitglieder: closed_signal, _LEGACY_IND_ID/_NEW_IND_ID, _normalize_indicators_state, __init__, eventFilter. Line-Endings unveraendert.
- **chart/chart_win_workers.py erweitert (+31):** find_null_fields/_clean_nan (aus chart_win.py uebernommen, inkl. math-Import) + Docstring ergaenzt.
- **Validierung (headless, test/):** py_compile OK (6 Dateien); AST-Check: Hauptklasse exakt 6 Mitglieder, jede Mixin exakt 1 Klasse mit erwarteten Methoden; 52/52 Methoden byte-identisch; Import-Smoke mit .venv-Python: chart.chart_win + ui.window_manager importierbar, MRO korrekt (PyTraderChartWindow -> QMainWindow -> ... -> 5 Mixins -> object), alle 55 Methoden erreichbar; test/check_2303_selfcalls.py: alle self.X()-Calls aufloesbar (nur Qt-Basis-Methoden wie setWindowTitle/pos/size sind extern); Scan ueber alle Py-Dateien (ohne docs/): keine andere Datei referenziert die verschobenen Helfer.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).


**15.08.2026 (23.04 - God-File-Split #4: service_win.py-Mixins, phase23_step6):** Vierter God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** service_win.py (172.339 Bytes/3.490 Zeilen) ist das groesste God-File des Projekts - eine Klasse ServiceWindow (Z89-3490, 93 Methoden), CRLF-Line-Endings. Importeure sind nur serviceui/__init__.py und ui/window_manager.py (+ Test-Dateien); kein Zirkularimport-Risiko in serviceui/. Methoden-Callgraph: 1 grosse Komponente (72 Methoden via __init__-Verdrahtung) -> thematische Gruppierung statt rein graph-basierter Zerlegung (Muster Split #3). `_qt_valid`-Guard (shiboken6) wird von Run-/Editor-Methoden genutzt -> in beide Mixins dupliziert. Restliche God-File-Kandidaten fuer spaetere Splits: master_tree (2.665), heatmap_widget (2.656), feature_store_reader (2.602), service_selector_dialog (2.560), analytics_view_model (2.051).
- **5 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** serviceui/service_win_run.py (ServiceRunMixin, 17 Methoden - Run-Worker, Sync-Guard, Fortschritt, TF-Status, Badges, Full-Sync; 23.480 Bytes), serviceui/service_win_tree.py (ServiceTreeMixin, 9 - MasterTree-Handler, Folder-Operationen, Kategorie-Info; 11.998), serviceui/service_win_editor.py (ServiceEditorMixin, 23 - Parameter-/Set-Editor, Save, Dirty-State, Set-Editor, Beschreibungen; 36.152), serviceui/service_win_sets.py (ServiceSetsMixin, 9 - Set-Verwaltung inkl. Papierkorb; 15.373), serviceui/service_win_presets.py (ServicePresetMixin, 18 - Presets/Varianten/Doc-Log, Purge, Duplicate; 36.841). Deterministisch per test/build_2304_swin.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching aus Modul-Importen; `_qt_valid`-Guard auto-eingefuegt wo noetig). Reihenfolge in jeder Mixin == Original-Quellreihenfolge (Fix im Build-Skript: `_toolbar_add_service` an Position 1 der editor-Gruppe, vor `_plugin_config`; vorher stand er an Position 13).
- **Hauptdatei serviceui/service_win.py (171.804 -> 52.795 Bytes, -119.009):** Klassendeklaration erweitert auf `ServiceWindow(ServiceParamColumnsMixin, ContentScrollMixin, NamedItemActionsMixin, ServiceRunMixin, ServiceTreeMixin, ServiceEditorMixin, ServiceSetsMixin, ServicePresetMixin, PersistentWindow)`; 5 Mixin-Importe nach dem new_set_dialog-Import eingefuegt; 76 Methoden entfernt. Verbleibende Mitglieder (5 Klassenvariablen + 17 Methoden): INSTANCE_ID, _keep_history_on_close, DIALOG_GEOMETRY_KEY, _exact_fit_to_content, _min_window_width, __init__, save_state, restore_state, _apply_reflow_size, resize_to_clamped_content, apply_screen_cap, get_persistent_symbol, get_persistent_timeframe, _apply_persistent_filters, _refresh_timeframe_combo, _on_symbol_changed, _wire_selector_toolbar, open_symbols_window, _refresh_symbol_combo, log, _on_log_context_menu, closeEvent. Line-Endings (CRLF) unveraendert erhalten; Original-Backup unter test/backup_service_win_pre_mixins_20260815_185123.py (172.339 Bytes).
- **Validierung (headless, test/):** py_compile OK (6 Dateien); AST-Check: Kern exakt 22 Mitglieder, jede Mixin exakt 1 Klasse mit erwarteten Methoden; 76/76 Methoden byte-identisch (normalisiert); test/check_2304_allorder.py: ALLE 5 Mixins in Original-Quellreihenfolge; Import-Smoke mit .venv-Python (test/smoke_2304_full.py): serviceui/__init__ + alle 5 Mixins + service_win + ui.window_manager importierbar, MRO korrekt (ServiceWindow -> 5 Mixins -> PersistentWindow -> QMainWindow), main.py importiert nur ui.window_manager; test/check_2304_selfcalls.py + test/check_2304_basemixins.py: alle externen self.X()-Calls in Basis-Mixins verifiziert (ContentScrollMixin/PersistentWindow/ServiceParamColumnsMixin); `_qt_valid`-Guards in run+editor (test/check_2304_localimports.py); alle gemeldeten refs sind lokale Variablen/Imports (test/check_2304_imports.py); test/check_2304_endings.py: CRLF beibehalten (946 CRLF, 0 LF-only, kein BOM).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.05 - God-File-Split #5: feature_store_reader.py-Mixins, phase23_step7):** Fuenfter God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** analytics/engine/feature_store_reader.py (122.318 Bytes/2.602 Zeilen) - eine Klasse FeatureStoreReader (Z173-2602, 46 Methoden), CRLF-Line-Endings, kein BOM. 17 Modul-Konstanten (Z46-154: BASE_DIR, DB_ANALYTICS, DB_MARKET, SCHEMA_VERSION_DEFAULT, SENTINEL_NATIVE, DOW_LABELS, DOW_WEEK_LABELS, HOURS_PER_DAY, DAYS_PER_WEEK, DIM_MAPPINGS, HEATMAP_DIMENSIONS, HEATMAP_AGGREGATIONS, MAX_HEATMAP_CELLS, OHLCV_SNAPSHOT_LIMIT, DAILY_OHLC_MAX_DAYS, TF_SECONDS, CANONICAL_TIMEFRAME_ORDER) + Modul-Funktion canonical_tf_sort (Z157-170, nur intern von fetch_service_tf_status/get_available_timeframes genutzt). KRITISCH: Die Konstanten werden extern importiert (analytics_view_model 7, heatmap_widget 5, analytics_worker 2, analytics_repository 1, heatmap_page 3, ind_peak TF_SECONDS, service_selector_dialog TF_SECONDS, service_win BASE_DIR+TF_SECONDS, mtf_fc_provider, feature_builder, common_widgets) -> Re-Export in Hauptdatei zwingend. Klassen-Nutzer: analytics_repository, analytics_view_model, analytics_worker, mtf_fc_provider, service_selector_model, analytics_win, table_page, ind_peak, common_widgets, service_selector_dialog, service_win, service_win_run, feature_builder. canonical_tf_sort MUSS in die Support-Datei (Mixin-Nutzung -> sonst Zirkularimport ueber die Mixins).
- **Neue Datei analytics/engine/feature_store_reader_constants.py (141 Zeilen):** 17 Konstanten (Z45-154 1:1) + canonical_tf_sort (Z157-170 1:1), eigener Docstring, Importe from pathlib import Path + from typing import List. Hauptdatei re-exportiert alle 18 Namen via from analytics.engine.feature_store_reader_constants import (...).
- **6 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** analytics/engine/feature_store_reader_meta.py (FeatureStoreMetaMixin, 8 Methoden - Meta-Cache, Connection, Epoch; 207 Zeilen), feature_store_reader_filter.py (FeatureStoreFilterMixin, 9 - Normalisierung, Filter, Formatierung; 305), feature_store_reader_query.py (FeatureStoreQueryMixin, 8 - Row-/Column-/Key-Fetch, Verfuegbarkeitslisten; 479), feature_store_reader_heatmap.py (FeatureStoreHeatmapMixin, 4 - Heatmap-Fetch klassisch+generisch; 492), feature_store_reader_ohlcv.py (FeatureStoreOhlcvMixin, 11 - OHLCV-Snapshots, Execution-Dates/Hashes, TF-Status; 637), feature_store_reader_plugin.py (FeatureStorePluginMixin, 5 - No-Data-Varianten, Proximity/Plugin-Records, exists; 464). Deterministisch per test/build_2305_fsr.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching; Support-Importe automatisch ergaenzt). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__: Klassendeklaration FeatureStoreReader(FeatureStoreMetaMixin, FeatureStoreFilterMixin, FeatureStoreQueryMixin, FeatureStoreHeatmapMixin, FeatureStoreOhlcvMixin, FeatureStorePluginMixin).
- **Hauptdatei analytics/engine/feature_store_reader.py (122.318 -> 4.219 Bytes, -118.099):** 45 Methoden entfernt, 17 Konstanten + canonical_tf_sort durch Re-Export-Import ersetzt (keine Doppel-Definition - lokale canonical_tf_sort-Definition entfernt), 6 Mixin-Importe nach db_service-Import eingefuegt. Verbleibend: Docstring, Importe, Re-Export, Klasse mit __init__ (db_path, Meta-Cache-Init).
- **Validierung (headless, test/):** build_2305_fsr.py (py_compile 8 Dateien OK; AST-Check Kern==["__init__"] + je Mixin exakt die vorgesehenen Methoden; alle 45 Methoden byte-identisch normalisiert; Konstanten-Block Z45-154 + canonical_tf_sort Z157-170 byte-identisch); check_2305_fsr_imports.py (Import-Smoke mit .venv-Python 3.14.5: Hauptdatei, alle 17 Konstanten + canonical_tf_sort via Re-Export, MRO = 6 Mixins, Instanz FeatureStoreReader(), 14 externe Nutzer importieren, direkter Import canonical_tf_sort/TF_SECONDS/DOW_LABELS funktioniert, TF_SECONDS["M15"]==900).
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B6: feature_store_reader 2.410 -> 93 Zeilen + 7 neue Dateien (constants 141, meta 207, filter 305, query 479, heatmap 492, ohlcv 637, plugin 464) mit 1-Zeilen-Verantwortlichkeit; Teil C Zeile 11: Routing auf Hauptdatei + Mixins (_query/_ohlcv/_heatmap/_filter) aktualisiert; Teil D2: Kandidat als GESPLITTET markiert; Stand-Header auf 23.05.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.06 - God-File-Split #6: master_tree.py-Mixins, phase23_step8):** Sechster God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2, nach feature_store_reader). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** serviceui/master_tree.py (138.623 Bytes/2.511 Zeilen) - eine Klasse MasterTree(QTreeWidget, Z116-2665, 58 Methoden), CRLF-Line-Endings, kein BOM. 25 Modul-Konstanten (Z83-182: MIME_CATEGORY_MOVE, ROLE_SET_ID, ROLE_SERVICE_ID, ROLE_INSTANCE_HASH, ROLE_IS_FOLDER, ROLE_KIND, TYPE_SET, TYPE_SERVICE, TYPE_FOLDER, TYPE_CATEGORY, CHECKBOX_ZONE_WIDTH, MAX_BADGE_CELL_CHARS, BADGE_TRUNCATE_ICON, INFO_BUTTON_WIDTH/HEIGHT/MARGIN, BADGE_COLUMN_WIDTH, BRANCH_ZONE_WIDTH, LEVEL_INDENT, ...) + Modul-Funktion isValid (try/except, Z185-194) + Modul-Funktion _expandable_label (Z195-199) + Klasse TreeItemIterator (Z2628-2665). KRITISCH: isValid/_expandable_label/TreeItemIterator werden von mehreren Mixins genutzt, TreeItemIterator zusaetzlich extern importiert (service_selector_dialog, service_selector_widget, service_win_editor, service_win_tree, serviceui/__init__.py) -> Re-Export in Hauptdatei zwingend. Statische Methoden im Original: _mode_suffix (Z651, importiert PluginRegistry aus feature_builder), _fmt_last_exec, _set_label_mode (Z810, import re).
- **Neue Datei serviceui/master_tree_constants.py (167 Zeilen/7.815 Bytes):** 25 Konstanten (Z83-182 1:1) + isValid (try/except 1:1) + _expandable_label (1:1) + TreeItemIterator (Z2628-2665 1:1). Importe: from PySide6.QtCore import Qt, from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, from typing import Optional. Hauptdatei re-exportiert alle 27 Namen via from serviceui.master_tree_constants import (...).
- **6 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** serviceui/master_tree_build.py (MasterTreeBuildMixin, 16 Methoden - Baumaufbau Sets/Kategorien/Plugins/Clones, Badges, Modus-Label; 717 Zeilen/35.904 Bytes), master_tree_dragdrop.py (MasterTreeDragDropMixin, 9 - Drag&Drop, Ordner-Anlage/Umbenennung; 275/11.643), master_tree_ui.py (MasterTreeUiMixin, 9 - Expanded-State, Item-Buttons, Dirty-Marker, Checkable; 298/13.797), master_tree_checks.py (MasterTreeChecksMixin, 10 - Checkbox-Sync, Set-Zustand, checked-Abfragen; 524/25.733), master_tree_events.py (MasterTreeEventsMixin, 6 - Kontextmenue, drawBranches, Mouse-Events, Auswahl-Events; 499/26.878), master_tree_selection.py (MasterTreeSelectionMixin, 8 - Selection-APIs, Restore, Select-by; 139/5.860). Deterministisch per test/build_2306_master.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching; Support-Importe automatisch ergaenzt). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__ + Signal-Deklarationen (Z201-306): Klassendeklaration MasterTree(QTreeWidget, MasterTreeBuildMixin, MasterTreeDragDropMixin, MasterTreeUiMixin, MasterTreeChecksMixin, MasterTreeEventsMixin, MasterTreeSelectionMixin).
- **Build-Fixes (test/build_2306_master.py):** (1) Verifikations-Bug isValid - Funktion liegt verschachtelt im except-Zweig, daher ast.walk statt Modul-Body; (2) _expandable_label-Slice-Bug - End-Index 195-83 -> 195-82; (3) Echter Fehler: TreeItemIterator (separate Klasse am Dateiende) wird von _collect_expanded_state (master_tree_ui.py) genutzt, Name-Matching konnte sie nicht aufloesen (NameError im Smoke-Test) -> TreeItemIterator wandert in master_tree_constants.py, Hauptdatei re-exportiert sie, damit externe Importe (service_win_editor u. a.) weiter funktionieren.
- **Hauptdatei serviceui/master_tree.py (138.623 -> 18.003 Bytes, -120.620):** 58 Methoden entfernt, 25 Konstanten + isValid + _expandable_label + TreeItemIterator durch Re-Export-Import ersetzt (keine Doppel-Definition), 6 Mixin-Importe eingefuegt. Verbleibend: Docstring, Importe (unveraendert), Re-Export, Klasse mit __init__ + allen Signal-Deklarationen (Klassenvariablen bleiben im Kern).
- **Validierung (headless, test/):** build_2306_master.py (py_compile 8 Dateien OK; AST-Check Kern==["__init__"] + je Mixin exakt die vorgesehenen Methoden; alle 58 Methoden byte-identisch normalisiert; Konstanten-Block Z83-195 + _expandable_label + TreeItemIterator Z2628-2665 byte-identisch); check_2306_master_imports.py (Import-Smoke mit .venv-Python 3.14.5: Hauptdatei + alle 27 Re-Export-Namen, Support-Datei direkt, MRO = MasterTree -> QTreeWidget -> Qt-Kette -> 6 Mixins, Offscreen-Instanz MasterTree(DummyModel()) -> __init__ inkl. _populate (leerer Baum) OK, TreeItemIterator leerer Baum, _expandable_label-Logik, alle 5 externen Nutzer importieren; QFontDatabase-Warnung = harmloser Hinweis).
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B8: master_tree 2.511 -> 318 Zeilen + 7 neue Dateien (constants 167, build 717, dragdrop 275, ui 298, checks 524, events 499, selection 139) mit 1-Zeilen-Verantwortlichkeit; Teil C Zeile 9: Routing auf Hauptdatei + Mixins (_build/_events/_selection/_dragdrop/_ui/_checks, Konstanten _constants) aktualisiert; Teil D2: Kandidat als GESPLITTET markiert; Stand-Header auf 23.06 (144 Py-Dateien / 49.759 Zeilen).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.07 - God-File-Split #7: analytics_view_model.py-Mixins, phase23_step9):** Siebter God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2, nach master_tree). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** analytics/engine/analytics_view_model.py (98.605 Bytes/1.886 Zeilen, LF-only, kein BOM) - eine Klasse AnalyticsViewModel(QObject, Z78-1881, 87 Methoden). 11 Signal-Assignments (Klassenvariablen: data_ready, query_failed, busy_changed, active_profile_changed, dirty_changed, profile_saved, profile_deleted, profiles_available, missing_services_detected, params_restored, feature_ids_changed) + 4 Modul-Konstanten (Z50-61: DEBOUNCE_MS, DEFAULT_BINS, DEFAULT_LIMIT, _ALL_QUERIES). 7 Properties (params, active_profile, profiles, is_dirty, workspace_layout, restore_generation, max_lookback_limit) + 10 Staticmethods (_normalize_field_pairs, _pairs_to_feature_ids, _normalize_feature_ids, _normalize_instance_hashes, _flatten_payload, _clamp_zoom, _sanitize_dim, _emit_profile_changed, _clamp_bins, _clamp_limit). Lokale Imports (ServiceSelectorModel in 7 Methoden: _resolve_feature_ids Z626, resolve_service_label Z1640, resolve_service_display_name Z1698, checked_variant Z1763, service_execution_datetime Z1818, resolve_instance_hashes Z1847, _no_data_presets_snapshot Z1910) bleiben lokal in den Methoden (kein Zirkularimport). Nur 1 externer Klassen-Import: analytics/ui/analytics_win.py; keine externen Konstanten-Importe.
- **Neue Datei analytics/engine/analytics_view_model_constants.py (30 Zeilen/1.159 Bytes):** 4 Konstanten (Z50-61 1:1). Importe: from analytics.engine.analytics_worker import (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC, QUERY_SCATTER, QUERY_DISTRIBUTION, QUERY_FEATURES). Hauptdatei re-exportiert alle 4 Namen via from analytics.engine.analytics_view_model_constants import (...).
- **6 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** analytics/engine/analytics_view_model_query.py (AnalyticsViewModelQueryMixin, 18 Methoden - Query-Orchestrierung, Refresh, Async-Worker-Management, Shutdown; 253 Zeilen/11.785 Bytes), _setters.py (AnalyticsViewModelSetterMixin, 9 - Symbol, Timeframes, Sort/Service-Modus, Range, Epoch; 180/8.052), _fields.py (AnalyticsViewModelFieldMixin, 9 - Feature-/Feld-Selektion & Normalisierung (field_pairs, feature_ids, hashes); 244/10.620), _heatmap.py (AnalyticsViewModelHeatmapMixin, 17 - Heatmap-Config, Smart-Presets, Zoom/Projektion, Spalten/Bins/Limit/Settings; 296/13.235), _profile.py (AnalyticsViewModelProfileMixin, 13 - Profil-CRUD, Apply/Restore, Workspace, EventBus-Emit; 427/21.809), _resolve.py (AnalyticsViewModelResolveMixin, 20 - Properties & Service-Aufloesung (Labels, Zeit, Hashes); 586/27.779). Deterministisch per test/build_2307_avm.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching; Support-Importe automatisch ergaenzt). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__ + 11 Signal-Deklarationen: Klassendeklaration AnalyticsViewModel(QObject, AnalyticsViewModelQueryMixin, AnalyticsViewModelSetterMixin, AnalyticsViewModelFieldMixin, AnalyticsViewModelHeatmapMixin, AnalyticsViewModelProfileMixin, AnalyticsViewModelResolveMixin).
- **Build-Fix (test/build_2307_avm.py):** Verifikations-Bug - Konstanten-Check suchte nach DEBOUNCE_MS statt dem Zeilen-Start-Kommentar `# QTimer-Debounce` (Original beginnt Z50 mit Kommentar; im Support liegt der Block NACH dem Import-Header) -> Check auf `# QTimer-Debounce` gefixt, Original per `git checkout` wiederhergestellt, Build erneut -> BUILD FERTIG gruen (py_compile 8 Dateien OK, AST-Check Kern==["__init__"], alle 86 Methoden byte-identisch, Konstanten-Block Z50-61 byte-identisch).
- **Hauptdatei analytics/engine/analytics_view_model.py (100.656 -> 11.607 Bytes, -89.049, 225 Zeilen):** 86 Methoden entfernt, 4 Konstanten durch Re-Export-Import ersetzt (keine Doppel-Definition), 6 Mixin-Importe nach dem event_bus-Import eingefuegt. Verbleibend: Docstring, Importe (unveraendert), Re-Export, Klasse mit __init__ + allen 11 Signal-Deklarationen (Klassenvariablen bleiben im Kern).
- **Validierung (headless, test/):** build_2307_avm.py (py_compile 8 Dateien OK; AST-Check Kern==["__init__"] + je Mixin exakt die vorgesehenen Methoden; alle 86 Methoden byte-identisch normalisiert; Konstanten-Block Z50-61 byte-identisch); check_2307_avm_imports.py (Import-Smoke mit .venv-Python: Hauptdatei + 4 Re-Export-Konstanten, Support-Datei direkt (Werte identisch: DEBOUNCE_MS=250, DEFAULT_BINS=20, DEFAULT_LIMIT=5000, _ALL_QUERIES=6), MRO = AnalyticsViewModel -> QObject -> ... -> 6 Mixins, 6 Mixin-Dateien einzeln importierbar, AST Kern __init__ + 11 Signale, externer Nutzer analytics_win importiert, Properties/Statics via MRO-Suche erhalten, Instanz-Methoden-Stichprobe via Mixins - SMOKE TEST PASS). Zusaetzlich beim Commit-Check: Constants-Datei auf Platte fehlerhaft vorgefunden (enthielt den Import-Header der Hauptdatei statt des Konstanten-Blocks -> Zirkularimport im Smoke); korrigiert auf den 1:1-Z50-61-Block (aus git HEAD extrahiert), Import-Smoke danach erneut PASS.
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B6: analytics_view_model 1.886 -> 225 Zeilen + 7 neue Dateien (constants 30, query 253, setters 180, fields 244, heatmap 296, profile 427, resolve 586) mit 1-Zeilen-Verantwortlichkeit; Teil C Zeilen 11-13: Routing auf Hauptdatei + Mixins (Zeile 11: _query/_setters/_fields/_resolve; Zeile 12: _profile; Zeile 13: _heatmap/_resolve) aktualisiert; Teil D2: Kandidat als GESPLITTET markiert; Stand-Header auf 23.07 (151 Py-Dateien / 49.949 Zeilen).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.08 - God-File-Split #8: service_selector_dialog.py-Mixins, phase23_step10):** Achter God-File-Split der Entkopplungs-Roadmap (Benutzer-Prioritaet nach master_tree + analytics_view_model). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** serviceui/service_selector_dialog.py (120.922 Bytes/2.561 Zeilen, CRLF (2560 CRLF, 0 LF-only), kein BOM) - 2 Klassen: _DialogParamHost (Z127-329, 8 Methoden, Basis ServiceParamColumnsMixin) + ServiceSelectorDialog (Z332-2560, 73 Methoden inkl. __init__ Z365-614, Basis QDialog). 4 Modul-Konstanten (Z112-124: DIALOG_GEOMETRY_KEY, PANEL_BUFFER, BODY_SPACING, TREE_DEFAULT_WIDTH) -> muessen in constants-Datei (genutzt von __init__ UND Mixin-Methoden Z2329/2331/2498/2528/2545/2550, sonst Zirkularimport). 4 Signal-Klassenvariablen bleiben im Kern (services_selected, selection_ids_requested, selection_hashes_requested, splitter_changed). _DialogParamHost wird von __init__ UND Mixin-Methoden (Z793, Z2232, Z2429) genutzt -> eigene host-Datei noetig (Hauptdatei re-exportiert, Muster master_tree_constants/indicator_dialog_support). Keine externen Importe von _DialogParamHost; einziger externer Klassen-Import: analytics/ui/analytics_win.py. Lokale Imports (PluginRegistry, FeatureBuilder, generate_instance_hash, master_tree-Typen, service_set_utils-Funktionen, QTimer, TF_SECONDS_MAP) bleiben in den Methoden.
- **Neue Datei serviceui/service_selector_dialog_constants.py (22 Zeilen/1.131 Bytes):** 4 Konstanten (Z112-124 1:1). Hauptdatei re-exportiert alle 4 Namen via from serviceui.service_selector_dialog_constants import (...).
- **Neue Datei serviceui/service_selector_dialog_host.py (217 Zeilen/10.215 Bytes):** _DialogParamHost (8 Methoden, Z127-329 1:1, eigene Importe: QPushButton, ServiceSelectorModel, event_bus, ServiceParamColumnsMixin); Hauptdatei re-exportiert _DialogParamHost.
- **6 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** serviceui/service_selector_dialog_selection.py (ServiceSelectorDialogSelectionMixin, 10 Methoden - Filter/Apply, Info-Dialoge (Service/Kategorie), Resolve-Info; 198 Zeilen/8.210 Bytes), _presets.py (ServiceSelectorDialogPresetMixin, 12 - Varianten/Presets (Speichern, Finden, Duplizieren, Umbenennen), Purge (legacy/data-only), Delete-Complete, Doc-Log, Instance-IDs; 468/19.983), _sets.py (ServiceSelectorDialogSetMixin, 13 - Set-/Ordner-CRUD (Anlegen, Umbenennen, Loeschen), Service hinzufuegen/entfernen/verschieben, Drag&Drop-Handler; 336/13.671), _run.py (ServiceSelectorDialogRunMixin, 18 - Checkbox-Filter, Tree-Selection-Details, Run-Symbol/Timeframe/Service/Set/Plugin/Kategorie, Run-Worker, TF-Combo, Live-Parameter-Merge, Fortschritt; 529/23.890), _badge.py (ServiceSelectorDialogBadgeMixin, 7 - closeEvent, TF-Start/Ende, Badge-Scope, Badge-Bar-Refresh, Modell-Refresh; 222/9.708), _panel.py (ServiceSelectorDialogPanelMixin, 12 - Param-Panel (Rebuild/Apply/Clear), Dialog-Fit/Resize, Splitter (Move/Sizes), Geometrie (Restore/Save), done; 388/17.794). Deterministisch per test/build_2308_ssd.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching; Support-Importe automatisch ergaenzt). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__ + 4 Signal-Deklarationen: Klassendeklaration ServiceSelectorDialog(QDialog, ServiceSelectorDialogSelectionMixin, ServiceSelectorDialogPresetMixin, ServiceSelectorDialogSetMixin, ServiceSelectorDialogRunMixin, ServiceSelectorDialogBadgeMixin, ServiceSelectorDialogPanelMixin).
- **Hauptdatei serviceui/service_selector_dialog.py (120.663 -> 22.375 Bytes, -98.288, 414 Zeilen, CRLF erhalten):** 72 Methoden entfernt, Konstanten-Block Z112-124 durch Re-Export-Import ersetzt (keine Doppel-Definition), Host-Block Z127-329 entfernt (per Text-Suche), 6 Mixin-Importe nach `from serviceui.service_set_utils import variant_run_entries` eingefuegt. Verbleibend: Docstring, Importe (unveraendert), Re-Exports (Konstanten + _DialogParamHost), Klasse mit __init__ + allen 4 Signal-Deklarationen (Klassenvariablen bleiben im Kern).
- **Validierung (headless, test/):** build_2308_ssd.py (py_compile 9 Dateien OK; AST-Check Kern==["__init__"] + je Mixin exakt die vorgesehenen Methoden (10/12/13/18/7/12); alle 72 Methoden byte-identisch normalisiert; Konstanten-Block Z112-124 byte-identisch; Host-Block Z127-329 byte-identisch; Line-Endings: alle 9 Dateien CRLF, kein BOM - BUILD FERTIG gruen); check_2308_ssd_imports.py (Import-Smoke mit .venv-Python: Hauptdatei + 4 Re-Export-Konstanten (Werte identisch: BODY_SPACING=8, DIALOG_GEOMETRY_KEY="service_selector", PANEL_BUFFER=24, TREE_DEFAULT_WIDTH=300) + Host-Re-Export, constants/host direkt, MRO = ServiceSelectorDialog -> QDialog -> ... -> 6 Mixins, 6 Mixin-Dateien einzeln importierbar, AST Kern __init__ + 4 Signale, externer Nutzer analytics_win importiert, Stichproben-Methoden aus allen 6 Mixins vorhanden, Kern ohne property/staticmethod - SMOKE TEST PASS).
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B8: service_selector_dialog 2.414 -> 414 Zeilen + 8 neue Dateien (constants 22, host 217, selection 198, presets 468, sets 336, run 529, badge 222, panel 388) mit 1-Zeilen-Verantwortlichkeit; Teil C neue Routing-Zeile 25 (Datenquellen-Picker: service_selector_dialog.py -> 6 Mixins -> host -> analytics_win); Teil D2: Kandidat als GESPLITTET markiert; Stand-Header auf 23.08 (159 Py-Dateien / 50.190 Zeilen, 6 JS / 1.837). Zusaetzlich verpasste Map-Updates der frueheren Splits nachgezogen (Teil E Punkt 1): Teil B4 chart_win 1.630 -> 399 + 6 Mixins (23.03), Teil B6 analytics_view_model 1.886 -> 225 + 7 Dateien (23.07), Teil B8 service_win 3.264 -> 946 + 5 Mixins (23.04) und master_tree 2.511 -> 318 + 7 Dateien (23.06), Teil C Zeilen 1-5 auf chart_win-Mixins zeigen, Teil D2 service_win + chart_win als GESPLITTET markiert, verbleibende Kandidaten neu ausgezaehlt (heatmap_widget 2.656, indicator_dialog 1.867).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.09 - God-File-Split #9: heatmap_widget.py-Mixins, phase23_step11):** Neunter God-File-Split der Entkopplungs-Roadmap (Benutzer-Prioritaet nach service_selector_dialog). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** analytics/ui/heatmap_widget.py (129.128 Bytes/2.656 Zeilen, LF-only (0 CRLF), kein BOM) - 2 Klassen: _HeatmapAxis (Z298-569, 9 Methoden) + HeatmapWidget (Z572-2656, 54 Methoden inkl. __init__ Z580-848, Basis QWidget). 15 Modul-Konstanten (Z122-202: _CONFLUENCE_COLORS, _CONFLUENCE_POS, _CONFLUENCE_LEVELS, _VIRIDIS, _VALUE_AGGS, _PRICE_LIKE_KEY_HINTS, _DAY_SECONDS, _HALF_DAY, _MONTH_SECONDS, _YEAR_SECONDS, _TF_SECONDS, _DATE_TARGET_PX, _MONTHS_SHORT, _DIM_LABELS, _AGG_LABELS) -> constants-Datei (genutzt von __init__ UND Mixin-Methoden). 6 Modul-Funktionen NACH den Konstanten (Z152-295): _is_price_like_key (nutzt _PRICE_LIKE_KEY_HINTS) -> controls, _pick_time_step/_time_ticks/_nice_int_step -> axis, _format_heatmap_value/_format_legend_value -> info. _HeatmapAxis nur in __init__ (Z731/732) genutzt -> eigene axis-Datei (kein Zirkularimport, Hauptdatei re-exportiert, Muster heatmap_widget_constants/service_selector_dialog_host). 1 Signal-Klassenvariable: preset_clicked (Z578) -> bleibt im Kern. 5 Staticmethods: _set_combo_data, _set_zoom_slider, _field_key, _zoom_lo_hi, _axis_bounds. Keine lokalen Imports in Methoden. Einziger direkter externer Nutzer: analytics/ui/heatmap_page.py (analytics_win nur indirekt via heatmap_page). Backup: test/backup_heatmap_widget_pre_mixins_20260815.py.
- **Neue Datei analytics/ui/heatmap_widget_constants.py (86 Zeilen/3.601 Bytes):** 15 Konstanten (Z122-202 1:1). Hauptdatei re-exportiert alle 15 Namen via from analytics.ui.heatmap_widget_constants import (...).
- **Neue Datei analytics/ui/heatmap_widget_axis.py (333 Zeilen/15.154 Bytes):** _HeatmapAxis (9 Methoden, Z298-569 1:1) + 3 Tick-Helper (Z205-245: _pick_time_step, _time_ticks, _nice_int_step).
- **6 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** analytics/ui/heatmap_widget_controls.py (HeatmapWidgetControlsMixin, 11 Methoden - Config-Sync, Combos, Slider, Modus-Sync; + _is_price_like_key; 344 Zeilen/15.765 Bytes), _fields.py (HeatmapWidgetFieldMixin, 10 - Feld-Auswahl/Dropdown, Checked-Pairs, VM-Sync; 432/20.959), _zoom.py (HeatmapWidgetZoomMixin, 10 - Zoom-Slider X/Y, Range-Apply, Achsen-Bounds; 167/6.574), _data.py (HeatmapWidgetDataMixin, 10 - Daten-Anfrage/-Empfang, Render-Generic, No-Data; 512/25.054), _overlay.py (HeatmapWidgetOverlayMixin, 6 - Candle-Overlay, Preis-View, Grid-Linien; 273/12.161), _info.py (HeatmapWidgetInfoMixin, 6 - Info-Zeile, Maus-Tracking, Zell-Info, Legende; + 2 Format-Helper Z248-295; 305/13.970). Deterministisch per test/build_2309_hmw.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching; Support-Importe automatisch ergaenzt). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__ + Signal preset_clicked: Klassendeklaration HeatmapWidget(QWidget, HeatmapWidgetControlsMixin, HeatmapWidgetFieldMixin, HeatmapWidgetZoomMixin, HeatmapWidgetDataMixin, HeatmapWidgetOverlayMixin, HeatmapWidgetInfoMixin).
- **Hauptdatei analytics/ui/heatmap_widget.py (129.015 -> 21.321 Bytes, -107.694, 424 Zeilen, LF-only erhalten):** 53 Methoden entfernt, Konstanten-Block Z122-202 durch Re-Export-Import ersetzt (keine Doppel-Definition), Axis-Block Z298-569 entfernt, 6 Modul-Funktionen entfernt (in die jeweiligen Mixin-/axis-Dateien). Verbleibend: Docstring, Importe (unveraendert), Re-Exports (15 Konstanten + _HeatmapAxis), Klasse mit __init__ + Signal-Deklaration preset_clicked (Klassenvariable bleibt im Kern).
- **Validierung (headless, test/):** build_2309_hmw.py (py_compile 9 Dateien OK; AST-Check Kern==["__init__"] + je Mixin exakt die vorgesehenen Methoden (11/10/10/10/6/6 = 53); alle 53 Methoden byte-identisch normalisiert; Konstanten-Block Z122-202 byte-identisch; Axis-Block Z298-569 byte-identisch; Line-Endings: alle 9 Dateien LF-only, kein BOM - BUILD FERTIG gruen); check_2309_hmw_imports.py (Import-Smoke mit .venv-Python: Hauptdatei + 15 Re-Export-Konstanten (Werte identisch) + _HeatmapAxis, constants/axis direkt, MRO = HeatmapWidget -> QWidget -> ... -> 6 Mixins, 6 Mixin-Dateien einzeln importierbar, AST Kern __init__ + preset_clicked, externe Nutzer heatmap_page + analytics_win importiert, Stichproben-Methoden aus allen 6 Mixins vorhanden, 5 Staticmethods via MRO + Dekorator-AST, Kern ohne property/staticmethod - SMOKE TEST PASS).
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B7: heatmap_widget 2.656 -> 424 Zeilen + 8 neue Dateien (constants 86, axis 333, controls 344, fields 432, zoom 167, data 512, overlay 273, info 305) mit 1-Zeilen-Verantwortlichkeit; Teil C Zeile 13 Routing auf Mixins zeigen (heatmap_widget.py (Kern) -> controls/fields/zoom/data/overlay/info + axis -> heatmap_page); Teil D2: Kandidat als GESPLITTET markiert (~~2.656~~ -> GESPLITTET (23.09, 15.08.2026) -> 6 Mixins + constants + axis); Stand-Header auf 23.09 (167 Py-Dateien / 50.410 Zeilen, 6 JS / 1.837).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.10 - God-File-Split #10: indicator_dialog.py-Mixins, phase23_step12):** Zehnter God-File-Split der Entkopplungs-Roadmap (Benutzer-Prioritaet: chart/indicator_dialog.py). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** chart/indicator_dialog.py (79.038 Bytes/1.867 Zeilen, LF-only (0 CRLF), kein BOM) - 1 Klasse IndicatorSettingsDialog (Z63-1867, 52 Methoden inkl. __init__ Z69-168, Basis ContentScrollMixin, NamedItemActionsMixin, QDialog). KEINE Modul-Konstanten und KEINE Modul-Funktionen auf Modulebene. 1 Klassen-Konstante DIALOG_GEOMETRY_KEY (Z67) -> bleibt im Kern (self-Zugriff via MRO aus _restore_geometry/_save_geometry in der geometry-Datei, kein Zirkularimport). 4 Staticmethods (_decimal_places, _is_visual_key, _style_sibling_keys, _human), 2 Properties (set_repo, set_evaluator) wandern mit ihren Methoden in die Mixins. Lokale Imports in 7 Methoden (PluginRegistry in _get_plugin/_service_cfg/_show_service_info/_rebuild_service_stack/collect_set_definition, ServiceSetRepository in set_repo, ServiceSetEvaluator in set_evaluator, get_symbol_precision in _get_symbol_precision, map_custom_levels_to_prox_levels in _rebuild_service_stack, import re in _generate_default_service_set_name) bleiben in den Methoden. Keine Signal-Klassenvariablen. Einzige externe Nutzer: chart/chart_win.py + chart/chart_win_indicators.py (nur Klassen-Import). Backup: test/backup_indicator_dialog_pre_mixins_20260815.py.
- **7 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** chart/indicator_dialog_plugin.py (IndicatorSettingsDialogPluginMixin, 3 Methoden - _get_plugin, set_repo, set_evaluator; 54 Zeilen/1.985 Bytes), _schema.py (IndicatorSettingsDialogSchemaMixin, 7 - _decimal_places, _get_symbol_precision, _is_visual_key, _style_sibling_keys, _human, create_schema_control, _ctrl_value; 249/9.782), _ui.py (IndicatorSettingsDialogUiMixin, 7 - init_ui, _init_legacy_ui, _init_plugin_ui, _init_plugin_ui_params_only, _setup_collapsible, _reflow, create_control_widget; 531/21.556), _sets.py (IndicatorSettingsDialogSetsMixin, 10 - _indicator_service_ids, _service_items, _service_cfg, refresh_service_set_list, _indicator_sets, _on_service_set_changed, _on_service_selected, _build_tooltip, _show_service_info, _rebuild_service_stack; 380/15.273), _run.py (IndicatorSettingsDialogRunMixin, 13 - _resolve_set_logic_params, _collect_logic_params, _build_preset_payload, collect_set_definition, _generate_default_service_set_name, create_new_service_set, save_service_set, delete_service_set, _connect_service_param_commit, _on_service_param_commit, execute_service_set, _on_set_run_finished, _on_set_run_failed; 364/15.243), _presets.py (IndicatorSettingsDialogPresetsMixin, 8 - _build_preset_group, refresh_preset_list, collect_params_from_ui, update_ui_from_params, on_param_control_changed, on_preset_selected, save_current_preset, delete_current_preset; 262/9.736), _geometry.py (IndicatorSettingsDialogGeometryMixin, 3 - _restore_geometry, _save_geometry, done; 66/2.360). Deterministisch per test/build_2310_idd.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__ + DIALOG_GEOMETRY_KEY: Klassendeklaration IndicatorSettingsDialog(ContentScrollMixin, NamedItemActionsMixin, QDialog, IndicatorSettingsDialogPluginMixin, IndicatorSettingsDialogSchemaMixin, IndicatorSettingsDialogUiMixin, IndicatorSettingsDialogSetsMixin, IndicatorSettingsDialogRunMixin, IndicatorSettingsDialogPresetsMixin, IndicatorSettingsDialogGeometryMixin).
- **Hauptdatei chart/indicator_dialog.py (78.744 -> 8.182 Bytes, -70.562, 181 Zeilen, LF-only erhalten):** 51 Methoden entfernt. Verbleibend: Docstring, Importe (unveraendert), 7 Mixin-Importe, Klasse mit __init__ + Klassen-Konstante DIALOG_GEOMETRY_KEY (Klassenvariable bleibt im Kern).
- **Validierung (headless, test/):** build_2310_idd.py (py_compile 8 Dateien OK; AST-Check Kern==["__init__"] + DIALOG_GEOMETRY_KEY-Assign; je Mixin exakt die vorgesehenen Methoden (3/7/7/10/13/8/3 = 51); alle 51 Methoden byte-identisch normalisiert; Basis-Reihenfolge 10 Basen (ContentScrollMixin, NamedItemActionsMixin, QDialog, 7 Mixins); Line-Endings: alle 8 Dateien LF-only, kein BOM - BUILD FERTIG gruen); check_2310_idd_imports.py (Import-Smoke mit .venv-Python: Hauptdatei + MRO (ContentScrollMixin vor QDialog, QDialog vor Mixins), 7 Mixin-Dateien einzeln importierbar, AST Kern __init__ + DIALOG_GEOMETRY_KEY, externer Nutzer chart_win_indicators importiert, Stichproben-Methoden aus allen 7 Mixins vorhanden, 4 Staticmethods + 2 Properties via getattr_static, Kern ohne property/staticmethod, alle 51 Methoden byte-identisch zu Backup - SMOKE TEST PASS).
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B4: indicator_dialog 1.893 -> 181 Zeilen + 7 neue Dateien (plugin 54, schema 249, ui 531, sets 380, run 364, presets 262, geometry 66) mit 1-Zeilen-Verantwortlichkeit; Teil C Zeile 10 Routing auf Mixins zeigen (indicator_dialog.py (Kern) -> plugin/schema/ui/sets/run/presets/geometry -> serviceui/param_columns.py); Teil D2: Kandidat als GESPLITTET markiert (~~1.867~~ -> GESPLITTET (23.10, 15.08.2026) -> 7 Mixins (Teil B4)); Stand-Header auf 23.10 (174 Py-Dateien / 50.623 Zeilen, 6 JS / 1.837).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).


