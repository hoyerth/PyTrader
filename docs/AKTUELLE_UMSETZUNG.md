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

# 19.01 Analytics UI: Status-Feedback, Empty-State & Multi-Service Table Handling

### 1. Architektur & Datenfluss

[AnalyticsWindow] ──(ViewModel `data_ready`)──► Status-Check (total == 0?)
        │
        ├── Ist Total == 0 ──► label_status_msg: "⚠️ Keine Daten vorhanden"
        │                      Pages -> clear_data() / Empty State
        │
        └── Multi-Select   ──► TablePage: Spalte 1 = "Service" (feature_id/display_name)
                               + Chronologische Sortierung + JSON-Union-Key-Spalten

---

### 2. Betroffene Dateien

* `analytics/ui/analytics_win.py`: Status-Message (`label_status_msg`) hinter Limit-Feld einbauen, Auswertung von `data_ready(kind, data)`.
* `analytics/ui/table_page.py`: Multi-Service-Darstellung anpassen (Spalte 1 = Service, dynamische JSON-Spalten-Union, chronologische Sortierung).
* `analytics/engine/analytics_view_model.py`: Bereitstellung typisierter Datenströme bei Einzel- und Multi-`feature_ids`.

---

### 3. Schritt-für-Schritt Anleitung (IDE-AI)

#### Step 1: Status-Message im Filterbereich (`analytics_win.py`)

* [x] Platziere ein `QLabel` (`label_status_msg`) direkt neben/hinter dem Limit-Input-Feld (`spin_limit`).
* [x] Verbinde den Event-Handler für `view_model.data_ready(kind, data)`:
* Falls `data.get("total", 0) == 0`:
* Setze `label_status_msg.setText("⚠️ Keine Daten vorhanden")` (Farbton: dezent gelb/orange).
* Blende leere Zustände auf den Unterseiten (`table_page`, `heatmap_page`, `scatter_page`, `distribution_page`) sauber aus/zurück.

* Falls `data.get("total", 0) > 0`:
* Setze `label_status_msg.setText(f"✅ {total} Einträge")` oder leere den Text.

#### Step 2: Multi-Service Spaltenaufbereitung (`table_page.py`)

* [x] Erweitere das Layout der `TablePage`:
1. Füge als **Spalte 1** das Feld **`Service`** ein (Anzeige der `feature_id` bzw. des via `service_selector_model.resolve_display_names()` aufgelösten Namens).
2. Standard-Spaltenreihenfolge festlegen: `[Zeitstempel, Service, ema_diff, rsi_14, atr_normalized, ...]`.
3. Bei Zusatzfeldern aus `feature_data`: Bilde die Union aller JSON-Keys über die geladenen Rows; fülle fehlende Werte bei abweichenden Services mit `"-"`.
4. Erzwinge eine chronologisch absteigende Sortierung nach `bar_time`, damit Signale verschiedener Services zeitlich korrekt gemischt dargestellt werden.

#### Step 3: Quality Gate & Verifikation

* [x] Syntax-Check via Terminal ausführen:
`python -m py_compile analytics/ui/analytics_win.py analytics/ui/table_page.py analytics/engine/analytics_view_model.py`

* [x] Headless-Test in `test/test.py` für `AnalyticsViewModel`-Abfragen ausführen:
* Testfall A: Abfrage für ungescannte Symbole/Services liefert `total == 0`.
* Testfall B: Multi-`feature_ids`-Abfrage liefert gemischte Ergebnissätze.

---

## Prüfprotokoll 19.01 (08.08.2026 15:46) – Konsistenz, Vollständigkeit & Entscheidungen

### Konsistenz-Prüfung

* **Inhalte deckungsgleich:** Das Kapitel 19.01 in `docs/AKTUELLE_UMSETZUNG.md` ist
  **identisch** mit der uncommitteten Ergänzung in `docs/Current/x_Roadmap_Phase19.md`
  (Architektur, betroffene Dateien, Steps 1–3). Keine Widersprüche, kein Doku-Drift.
* **Datenverträge passen zum Ist-Code:** Alle im Kapitel referenzierten Verträge existieren
  bereits in der Codebase:
  * `AnalyticsRepository.get_table()` liefert `{"rows": [...], "total": len(rows)}` →
    Datenbasis für den `total == 0`-Status-Check ist vorhanden.
  * `FeatureStoreReader.fetch_rows()` liefert pro Row `time`, `symbol`, `timeframe`,
    `feature_id`, `plugin_version`, `ema_diff/rsi_14/atr_normalized` und geparstes
    `feature_data` (inkl. `schema_version`-Default) → JSON-Union-Spalten sind möglich.
  * `ServiceSelectorModel.resolve_display_names(ids)` existiert und wird bereits im
    AnalyticsWindow (Button-Text-Sync, Zeile 390) genutzt.
  * Multi-Select ist vollständig verdrahtet: `AnalyticsViewModel.set_feature_ids()`
    → `WHERE feature_id IN (...)` im Reader; `ServiceSelectorDialog` + Button-Sync aktiv.

### Vollständigkeit (Ist-Zustand vs. Kapitel)

| Step | Anforderung | Ist-Zustand |
|---|---|---|
| 1 | `QLabel label_status_msg` hinter `spin_limit`/`edit_limit` | **OFFEN** – kein `label_status_msg` in `analytics_win.py` |
| 1 | `data_ready(kind, data)`-Handler im AnalyticsWindow | **OFFEN** – nur Pages verbinden sich via `attach_view_model` |
| 1 | Status-Text `⚠️ Keine Daten vorhanden` / `✅ {n} Einträge` | **OFFEN** – nicht implementiert |
| 1 | Leere Zustände auf den Unterseiten sauber aus-/einblenden | **VORHANDEN** – Overlay-Stack in `table_page`, `heatmap_page`, `scatter_page`, `distribution_page` blendet bei leeren Daten bereits auf Empty-Index um |
| 2 | Spalte 1 = `Service` (feature_id/display_name) | **OFFEN** – fixe Spalten `[Zeit, Symbol, TF, Feature, Version, ema_diff, rsi_14, atr_normalized]` |
| 2 | Standard-Reihenfolge `[Zeitstempel, Service, ema_diff, ...]` | **OFFEN** |
| 2 | JSON-Union aller `feature_data`-Keys, Fehlwerte `"-"` | **OFFEN** – `feature_data` wird nicht dargestellt |
| 2 | Chronologisch absteigende Sortierung nach `bar_time` | **OFFEN** – Reader liefert ASC (`ORDER BY bar_time ASC`), Page nutzt ungezwungene QTableWidget-Sortierung |
| 3 | `py_compile` der 3 Dateien | **OFFEN** – nicht gelaufen (keine Änderung) |
| 3 | Headless-Tests A (total==0) & B (Multi-Mix) in `test/test.py` | **OFFEN** – keine 19.01-Testfälle vorhanden |

### Befunde (Lücken)

* **L1 – Status-Message fehlt komplett:** `analytics_win.py` besitzt weder
  `label_status_msg` noch einen `data_ready`-Handler; der Status-Check (Step 1) ist
  vollständig offen. Der Window-taugliche Anschluss ist `_wire_view_model()` /
  Filter-Zeile (`filt.addWidget(self.edit_limit)`).
* **L2 – Multi-Service-Darstellung fehlt:** `table_page.py` ist auf die fixen
  Alt-Spalten eingestellt; `feature_data` (JSON) wird verworfen. Step 2 ist offen.
* **L3 – Qualitäts-Gate fehlt:** Keine 19.01-spezifischen Tests in `test/test.py`
  (Testfall A/B); `py_compile` nicht ausgeführt (folgt mit der Umsetzung).
* **L4 – Sortier-Kontrakt:** `fetch_rows()` liefert deterministisch `ASC`
  (bestehender Reader-Vertrag, von bestehenden Tests/Callern genutzt). Die
  absteigend-chronologische Darstellung darf den Reader NICHT ändern – sie muss in
  der Page (Rendering) erfolgen.
* **L5 – `total`-Semantik (Limit-Cap):** `get_table()["total"]` ist `len(rows)`
  **nach** `LIMIT`, nicht die Gesamttrefferzahl. Testfall A (ungescannt → 0) ist
  davon unberührt, der Text bei `total > 0` ist aber als „angezeigte Einträge" zu
  verstehen (ggf. Formulierung „✅ {n} Einträge" mit Platzhalter für die Anzeige-Limit).

### Entscheidungen (19.01)

1. **E1 – Status-Message nutzt bestehenden `total`-Vertrag:** `label_status_msg`
   zeigt `data["total"]` aus `QUERY_TABLE` (LIMIT-gekappte Zeilenzahl). Text:
   `total == 0` → `"⚠️ Keine Daten vorhanden"` (dezent orange, z. B. `#b7950b`),
   `total > 0` → `"✅ {total} Einträge"`. **Kein** zusätzlicher COUNT-Query
   (bleibt lesend/leichtgewichtig, MVVM-Invariante 4).
2. **E2 – Sortierung in der Page, nicht im Reader:** `TablePage._populate()`
   sortiert die erhaltenen Rows nach `bar_time` **absteigend** (deterministisch,
   stabil) und zeichnet in dieser Reihenfolge; die QTableWidget-Interaktions-
   sortierung bleibt deaktiviert (`setSortingEnabled(False)`), damit die
   Service-Mischung chronologisch korrekt bleibt. `FeatureStoreReader` unverändert
   (L4-Fix).
3. **E3 – Service-Namensauflösung IoC-konform:** Die `TablePage` erhält eine
   injizierte `name_resolver: Callable[[List[str]], List[str]]` (Default: `feature_id`
   selbst). Das `AnalyticsWindow` verknüpft sie in `_wire_view_model()` mit
   `self._selector_model.resolve_display_names` → kein SQL und keine direkte
   Modell-Kopplung in der Page (Invariante 4 / Open-Closed).
4. **E4 – JSON-Union ohne Kollision:** Union aller `feature_data`-Keys über die
   geladenen Rows; fehlende Werte → `"-"`. Keys, die mit nativen Spalten
   (`ema_diff`, `rsi_14`, `atr_normalized`) oder Pflichtspalten kollidieren, werden
   ignoriert (defensiv, keine Duplikat-Header). Spaltenreihenfolge:
   `[Zeit, Service, native Spalten..., Union-Keys alphabetisch]`.
5. **E5 – Status/Empty-State-Verschmelzung:** Die vorbestehenden Overlay-Empty-
   States der Pages bleiben unangetastet (bereits erfüllt); der neue
   `label_status_msg` ist eine **ergänzende** Kopfzeilen-Info und ersetzt keinen
   Page-Zustand.

### Status

* **Umsetzung abgeschlossen (08.08.2026, Implementierungs-Log unten).**

---

## Implementierungs-Log 19.01 (08.08.2026 16:35) – Status-Feedback, Empty-State & Multi-Service Table

Umgesetzt (alle Checklisten-Punkte des Kapitels abgearbeitet; Entscheidungen E1–E5
des Prüfprotokolls 19.01 als verbindliche Spezifikation):

### Step 1 – Status-Message im Filterbereich (`analytics/engine/analytics_win.py`)

* `label_status_msg` (QLabel, dezent orange `#b7950b`, fett) direkt hinter dem
  Limit-Feld (`edit_limit`) in der Filter-Zeile eingebaut.
* `_on_data_ready(kind, data)`-Handler verbunden (`vm.data_ready` in
  `_wire_view_model`): wertet ausschließlich `QUERY_TABLE` aus (E1, kein
  zusätzlicher COUNT-Query). `total == 0` → `"⚠️ Keine Daten vorhanden"`,
  `total > 0` → `"✅ {n} Einträge"` (LIMIT-gekappte Zeilenzahl, L5).
* Empty-States der Unterseiten (Overlay-Stacks) waren bereits vorhanden (E5) –
  unverändert gelassen.

### Step 2 – Multi-Service Spaltenaufbereitung (`analytics/ui/table_page.py`)

* **Spalte 1 = Service** (E3): Injizierbarer `name_resolver` (Default = feature_id
  selbst); das AnalyticsWindow verknüpft `ServiceSelectorModel.resolve_display_names`
  IoC-konform (kein SQL, keine Modell-Kopplung in der Page).
* Standard-Spaltenreihenfolge `[Zeit (Wanduhr), Service, ema_diff, rsi_14,
  atr_normalized, ...JSON-Union-Keys alphabetisch]`; dynamischer Spaltenaufbau
  pro Abfrage.
* **JSON-Union** (E4): Vereinigung aller `feature_data`-Keys über die geladenen
  Rows; Kollisionen mit Basis-/nativen Spalten ignoriert; fehlende Werte → `"-"`.
* **Chronologisch ABSTEIGEND** (E2): `_populate()` sortiert die Rows deterministisch
  (stabil) nach `bar_time`; `setSortingEnabled(False)` bleibt dauerhaft deaktiviert
  (Service-Mischung korrekt, kein O(n^2)-Interaktions-Sort). `FeatureStoreReader`
  unverändert (ASC-Vertrag, L4).
* `_on_double_clicked` (Jump-to-Chart) liest Symbol/TF/Zeit jetzt aus der Roh-Row
  (`_current_rows`) statt aus festen Spaltenpositionen (dynamische Spalten).

### Step 3 – Quality Gate & Verifikation (headless, kein UI)

* `python -m py_compile analytics/ui/analytics_win.py analytics/ui/table_page.py
  analytics/engine/analytics_view_model.py` → **PASS** (exit 0).
* `test/test.py` (Teil 31, neu): 11 Prüfungen **PASS** –
  * Testfall A (`31 A1`): ungescanntes Symbol → `total == 0`.
  * Testfall B (`31 B1–B3`): Multi-`feature_ids` → 4 gemischte Rows
    (`srv_a`+`srv_b`), Einzel-Filter `srv_a` → nur 2 srv_a-Rows.
  * TablePage (`31 C1–C5`): absteigende Sortierung, Spalte-1-Anzeigename,
    JSON-Union-Spalten (`grid_step`, `lookback`, `schema_version`),
    Fehlwert `"-"` bei abweichendem Service.
* Gesamtlauf `test/test.py`: **559 PASS / 6 FAIL** – die 6 Fehler sind die
  dokumentierten **Baseline-Vorbefunde** P2/P5/H3/H4/H5/H7 (Geometrie-Tests,
  offscreen `800x582`, Reflow-/Scrollbar-Umbau 07./08.08.2026) – nicht durch
  19.01 verursacht, ohne 19.01-Änderungen identisch.
* Test-Workspace aufgeräumt (Invariante 10): nur `test/test.py` verbleibt.

### Abweichungen vom Plan-Kapitel (per Prüfprotokoll-Entscheidungen)

* Plan-Punkt „Spalte 1 = `feature_id`/`display_name`" → E3: injizierter
  `name_resolver` statt direkter Modell-Referenz.
* Plan-Punkt „chronologisch absteigende Sortierung" → E2: Sortierung in der Page
  (Reader-Sortierung bleibt ASC, L4).
* Plan-Punkt „Farbton dezent gelb/orange" → E1: `#b7950b` (QSS auf
  `label_status_msg`).

### Status

* **Alle Steps 1–3 abgeschlossen und headless verifiziert.** Keine UI-/Regressionstests
  ausgeführt (Regel 4); Baseline-Vorbefunde P2/P5/H3/H4/H5/H7 sind dokumentiert.

---

# 19.02 Analytics-Finalisierung: Cleanup Legacy-Native-Spalten & kleinere Tabellen-Schrift

### 1. Ziel & Architektur

Die Analytics-UI (15.03/19.01) stützte Achsen, Metriken und Tabellen-Spalten noch auf
**native DB-Spalten** (`ema_diff`, `rsi_14`, `atr_normalized`) – ein Relikt des
vor-Plugin-Zeitalters. Seit Phase 12 persistieren Services ihre Werte ausschließlich im
`feature_data`-JSON (`store_plugin_payload`). 19.02 entfernt die Legacy-Spalten aus dem
Datenfluss (lesend) und dem Neuschema (schreibend):

```
feature_store.feature_data (JSON) ──► FeatureStoreReader.available_feature_keys() ──►
AnalyticsRepository (get_scatter/get_distribution/get_heatmap, dynamische Defaults) ──►
ViewModel (heatmap_metrics/available_feature_columns) ──► UI-Combos (dynamisch)
```

Zusätzlich wird die TablePage-Schrift auf **9 pt** reduziert (mehr Zeilen/Spalten sichtbar
bei gleicher Fenstergröße, Task 1).

### 2. Betroffene Dateien

* `analytics/features/feature_builder.py` + `analytics/features/definitions/__init__.py`:
  nur noch `grid_levels` (EMA-Diff/ATR-Normalized archiviert, nicht mehr importiert).
* `analytics/engine/feature_store_reader.py`: `NATIVE_COLUMNS` entfernt; neue
  `available_feature_keys()` (DISTINCT-JSON-Struktur-Analyse), `fetch_columns()` und
  `fetch_heatmap()` lesen JSON-Keys; `fetch_rows()` ohne Legacy-Spalten.
* `analytics/engine/analytics_repository.py`: `HEATMAP_METRICS`/`NATIVE_COLUMNS` entfernt;
  dynamische Key-Auflösung, `metrics`-Feld, Fallback `"count"`.
* `analytics/engine/analytics_view_model.py` + `analytics/engine/analytics_worker.py`:
  Legacy-Defaults entfernt (leere Strings → Repo-Default), dynamische Auflösung.
* `analytics/ui/table_page.py`: Schrift ≤ 9 pt (Task 1), Basis-Spalten nur
  `[Zeit (Wanduhr), Service]` + JSON-Union.
* `analytics/ui/scatter_page.py`, `distribution_page.py`, `heatmap_page.py`: dynamische
  Achsen-/Spalten-/Metrik-Combos (prefill + `on_data_ready`-Sync).
* `db/schema_initializer.py`: Neuschema des `feature_store` ohne
  `ema_diff/rsi_14/atr_normalized` (Alt-DBs bleiben via Additiv-Pfad unangetastet).

### 3. Schritt-für-Schritt Anleitung (IDE-AI)

#### Step 1: Feature-Builder & Definitionen (`feature_builder.py`, `definitions/__init__.py`)

* [x] `EMADiffFeature`/`ATRNormalizedFeature`-Imports entfernt; `self.features` =
      nur noch `{"grid_levels": GridLevelsFeature()}`.
* [x] `definitions/__init__.py` exportiert nur noch `GridLevelsFeature`; die Dateien
      `ema_diff.py`/`atr_normalized.py` bleiben als Code-Archiv auf Platte (kein
      Import, keine Registrierung – `PluginLoader` scannt nur `PluginFeature`-Subklassen).

#### Step 2: Reader & Repository (`feature_store_reader.py`, `analytics_repository.py`, `analytics_view_model.py`, `analytics_worker.py`)

* [x] `NATIVE_COLUMNS`/`HEATMAP_METRICS`-Konstanten entfernt; `fetch_rows()` liest nur
      `bar_time/symbol/timeframe/feature_id/plugin_version/feature_data`.
* [x] Neu: `available_feature_keys(symbol, tf, numeric_only=False)` (Union über
      DISTINCT-JSON-Strukturen, `schema_version` ausgeschlossen, bool/str/null-Typisierung,
      Regex-Guard `_is_json_key_identifier()`).
* [x] `fetch_columns()` extrahiert numerische JSON-Keys (bool → ausgelassen);
      `fetch_heatmap()` nutzt `AVG(TRY_CAST(feature_data->>'key' AS DOUBLE))`.
* [x] Repository-Defaults: `x_column`/`y_column`/`column` optional (None → erste zwei
      numerische Keys bzw. erster numerischer Key); `get_heatmap` liefert `metrics` und
      fällt bei unbekannter Metrik auf `"count"` zurück.
* [x] ViewModel: Defaults `""` (statt `ema_diff`/`rsi_14`/`atr_normalized`);
      `native_columns`-Property ersetzt durch `available_feature_columns(symbol, tf)`
      und `heatmap_metrics(symbol, tf)` (defensiv); Worker reicht `None` durch.

#### Step 3: UI-Pages (`table_page.py`, `scatter_page.py`, `distribution_page.py`, `heatmap_page.py`)

* [x] **Task 1 (Schrift):** TablePage-Tabelle + Header auf **9 pt** (Header fett);
      `_TABLE_FONT_PT = 9`.
* [x] `_BASE_COLUMNS` = nur `[("Zeit (Wanduhr)", 130), ("Service", 150)]`; Legacy-
      Spalten-Renderblock entfernt; `_EXTRA_COLUMN_WIDTH = 95`.
* [x] Scatter/Distribution/Heatmap: dynamische Combos (`_set_columns`/`_set_metrics`),
      Prefill bei `attach_view_model`, Sync in `on_data_ready` aus `data["columns"]`
      bzw. `data["metrics"]` (kein Query-Loop durch blockierte Signale).

#### Step 4: Schema (`db/schema_initializer.py`)

* [x] `CREATE TABLE IF NOT EXISTS feature_store` im Neuschema **ohne**
      `ema_diff/rsi_14/atr_normalized`; bestehende DB-Dateien bleiben über den
      Additiv-Pfad (ALTER TABLE ADD COLUMN IF NOT EXISTS) unangetastet.

#### Step 5: Quality Gate & Verifikation

* [x] `py_compile` aller 11 geänderten Produktivdateien → **PASS**.
* [x] Isolierter Check `test/_check_1902_isolated.py` (deterministische Temp-DB,
      22 Prüfungen R1–R5/S1–S2/D1/H1–H3/V1–V3/T1–T7/B1) → **PASS** (temporär,
      nach Abschluss entfernt).
* [x] `test/test.py` **Teil 32** (neu, 14 Prüfungen A1–A5/B1–B4/C1–C2/D1–D3) → **PASS**;
      Teil 31 (19.01) unverändert **PASS**.
* [x] Gesamtlauf `test/test.py`: **573 PASS / 6 FAIL** – die 6 Fehler sind identisch
      mit den dokumentierten Baseline-Vorbefunden P2/P5/H3/H4/H5/H7
      (Geometrie-Tests, offscreen `800x582`) – nicht durch 19.02 verursacht.

---

## Prüfprotokoll 19.02 (08.08.2026) – Datenanalyse, Konsistenz & Entscheidungen

### Datenanalyse (Ist-Zustand der realen DB)

* **Reale Datenbasis:** `data/analytics.duckdb`, **904.723 Rows** im `feature_store`.
* **Keine nativen Legacy-Werte im Gebrauch:** Die realen `feature_data`-JSONs enthalten
  ausschließlich Service-Keys, z. B.:
  * `srv_grid_lines`: `grid_nearest_level`, `grid_step`, `lower_level`, `upper_level`
    (sowie per Service-Vertrag `levels_...`-Strukturen).
  * `srv_proximity`: `visit_pct`, `is_hit`, `in_time_window`, `levels_hit` (u. a.);
    `is_swing_high`, `strength_value`-artige Keys je nach Service-Instanz.
  * `schema_version` ist Pflicht-Key (E-3, Default `"1.0.0"`).
* **NULL-`feature_data`:** `srv_proximity`-Rows haben z. T. NULL-`feature_data`
  (≈ 573k Rows). `_normalize_feature_data(NULL)` → `{"schema_version": "1.0.0"}`
  (rein lesend, DB-Zeile bleibt unverändert).
* **DuckDB-SQL:** `feature_data->>'key'` und `TRY_CAST` funktionieren zuverlässig;
  ein `json_keys`-UNNEST ist nicht direkt verfügbar → Key-Union wird über die
  **DISTINCT-JSON-Strukturen** abgefragt (performant und deterministisch).
* **Alt-DB-Kompatibilität:** Die echte DB trägt noch zusätzliche native Spalten
  (u. a. `pivot_*`, `session_*`, `regime_*` von früheren Service-Generationen). Diese
  bleiben unangetastet (Additiv-Pfad); der Reader greift seit 19.02 **nur noch** auf
  `feature_data` zu.

### Konsistenz-Prüfung

* **Verträge passen:** `store_plugin_payload()` (Schreibseite) persistiert ausschließlich
  `feature_data`-JSON – die 19.02-Leseseite (JSON-Keys) ist vertragskonform; es existiert
  **keine** Schreibseite mehr, die native Spalten befüllt.
* **Kein verwaister Legacy-Code:** Projektweite Suche nach `ema_diff`/`rsi_14`/
  `atr_normalized`/`NATIVE_COLUMNS`/`HEATMAP_METRICS`/`native_columns`/
  `EMADiffFeature`/`ATRNormalizedFeature` (ohne `test/`/`docs/`/`.venv`) → **0 Treffer**
  in Produktivdateien.
* **Kein Re-Import der Archive:** `ema_diff.py`/`atr_normalized.py` erben von
  `BaseFeature` (nicht `PluginFeature`) → der `PluginLoader` (scannt `definitions/` per
  `pkgutil.walk_packages` nach `PluginFeature`-Subklassen) registriert sie **nicht**.
  `FeatureBuilder.features` ist ein Dict-Literal (nur `grid_levels`).
* **Teil-31-Regression:** Die 19.01-Checks (31 A/B/C) sind spalten-agnostisch und
  bestehen unverändert (Temp-DB mit Legacy-Spalten ist für `fetch_rows` irrelevant).

### Entscheidungen (19.02)

1. **D1 – Dynamische Achsen aus JSON-Strukturen:** Scatter-/Verteilungs-/Heatmap-Achsen
   werden pro Symbol/Timeframe aus der Union der DISTINCT-`feature_data`-JSON-Strukturen
   abgeleitet (`available_feature_keys`). `schema_version` (Pflichtfeld) wird nie als
   Achse/Metrik angeboten.
2. **D2 – Typfilter:** `numeric_only=True` akzeptiert nur Keys, die in **allen**
   Vorkommen numerisch sind (int/float, kein bool/str/null) → Grundlage für
   Scatter-/Verteilungs-Achsen und Heatmap-Metriken. Bool/str-Keys bleiben in der
   Tabellen-JSON-Union sichtbar, aber nicht als Achse wählbar.
3. **D3 – NULL-`feature_data`:** wird beim Lesen auf `{"schema_version": "1.0.0"}`
   normalisiert (E-3-Vertrag, DB-Zeile unverändert); Rows ohne Wert in einer
   angefragten Achse werden ausgelassen (Scatter/Histogramm).
4. **D4 – Neuschema vs. Alt-DBs:** Das `feature_store`-Neuschema enthält keine
   Legacy-Spalten mehr. Bestehende DB-Dateien (mit `ema_diff`/`rsi_14`/`atr_normalized`
   und `pivot_*`/`session_*`/`regime_*`) werden **nicht** migriert/entfernt
   (Additiv-Pfad, Code-Preserving) – der Reader liest sie schlicht nicht mehr.
5. **D5 – Defensive Fallbacks:** unbekannte Heatmap-Metrik → `"count"`; leere
   Datenlage → leere Combos (UI füllt beim ersten Daten-Payload); Repo-Fehler →
   `["count"]` bzw. `[]` (keine UI-Hänger).
6. **D6 – Schrift 9 pt:** `_TABLE_FONT_PT = 9` für TablePage-Tabelle + Header (fett) –
   mehr Zeilen (Zeilenhöhe folgt der Schrift) und schmalere Spalten bei gleicher
   Fenstergröße; Basis-Spalten `[Zeit (Wanduhr), Service]` bleiben fix.

### Status

* **Alle Steps 1–5 abgeschlossen und headless verifiziert.** Keine UI-/Regressionstests
  ausgeführt (Regel 4); Baseline-Vorbefunde P2/P5/H3/H4/H5/H7 sind unverändert
  dokumentiert.

---

## Implementierungs-Log 19.02 (08.08.2026) – Cleanup Legacy-Native-Spalten & 9-pt-Schrift

Umgesetzt (Checklisten-Step 1–5 abgearbeitet; Entscheidungen D1–D6 des Prüfprotokolls
19.02 als verbindliche Spezifikation):

### Step 1 – Feature-Builder & Definitionen

* `feature_builder.py`: `EMADiffFeature`/`ATRNormalizedFeature`-Imports entfernt;
  `self.features` = nur `{"grid_levels": GridLevelsFeature()}` (Doku angepasst).
* `definitions/__init__.py`: exportiert nur noch `GridLevelsFeature`; die Dateien
  `ema_diff.py`/`atr_normalized.py` bleiben als Code-Archiv auf Platte (kein Import,
  keine Registrierung – D4, `PluginLoader`-Scan findet keine `PluginFeature`-Klasse).

### Step 2 – Reader, Repository, ViewModel, Worker

* `feature_store_reader.py`: `NATIVE_COLUMNS`-Konstante entfernt; `fetch_rows()` liest
  nur `bar_time/symbol/timeframe/feature_id/plugin_version/feature_data`. Neu:
  `available_feature_keys(symbol, tf, numeric_only=False)` (DISTINCT-JSON-Struktur-
  Union, `schema_version` ausgeschlossen, Typ-Klassifikation bool/num/str/null,
  Regex-Guard `_is_json_key_identifier()` für SQL-Einbettungen); `fetch_columns()`
  (JSON-Keys, bool → ausgelassen); `fetch_heatmap()` mit
  `AVG(TRY_CAST(feature_data->>'key' AS DOUBLE))`.
* `analytics_repository.py`: `HEATMAP_METRICS`/`NATIVE_COLUMNS` entfernt; `get_scatter`/
  `get_distribution` mit Optional-Defaults (None → erste zwei numerische Keys bzw.
  erster numerischer Key); `get_heatmap` mit `metrics`-Feld und Fallback `"count"`;
  neue `available_heatmap_metrics()`/`available_feature_columns()` (dynamisch, defensiv).
* `analytics_view_model.py`: Defaults `scatter_x`/`scatter_y`/`distribution_column` = `""`
  (Repo-Default); `set_scatter_columns`/`set_distribution_column` ohne Legacy-Fallbacks;
  `native_columns`-Property ersetzt durch `available_feature_columns(symbol, tf)` und
  `heatmap_metrics(symbol, tf)` (defensiv).
* `analytics_worker.py`: `x_column`/`y_column`/`column` werden als `None` durchgereicht
  (Repo wählt Defaults, D1/D5).

### Step 3 – UI-Pages

* `table_page.py` (**Task 1 – Schrift**): `_TABLE_FONT_PT = 9` auf Tabelle + Header
  (Header fett, D6); `_BASE_COLUMNS` = nur `[Zeit (Wanduhr), Service]`; Legacy-Spalten-
  Renderblock entfernt; `_EXTRA_COLUMN_WIDTH = 95`; JSON-Union dynamisch
  (`_union_feature_keys` ohne native Kollisionen).
* `scatter_page.py`/`distribution_page.py`/`heatmap_page.py`: dynamische Achsen-/
  Spalten-/Metrik-Combos (`_set_columns`/`_set_metrics`), Prefill in `attach_view_model`
  über `available_feature_columns`/`heatmap_metrics`, Sync in `on_data_ready` aus
  `data["columns"]`/`data["metrics"]`/`x_label`/`y_label`/`column`/`metric`
  (Signale blockiert → kein Query-Loop).

### Step 4 – Schema

* `db/schema_initializer.py`: `feature_store`-Neuschema **ohne**
  `ema_diff/rsi_14/atr_normalized` (D4); bestehende DBs bleiben über den Additiv-Pfad
  unangetastet.

### Step 5 – Quality Gate & Verifikation (headless, kein UI)

* `py_compile` aller 11 geänderten Produktivdateien → **PASS** (exit 0).
* Temporärer Check `test/_check_1902_isolated.py` (deterministische Temp-DB, 22 Prüfungen):
  Reader R1–R5 (Key-Union, numeric_only, fetch_rows ohne Legacy, fetch_columns,
  get_available_features), Repository S1–S2/D1/H1–H3, ViewModel V1–V3, TablePage
  T1–T7 (Schrift ≤ 9 pt, Basis `[Zeit, Service]`, JSON-Union, absteigend, Spalte 1),
  Builder B1 → **alle PASS**. Nach Abschluss entfernt (Invariante 10).
* `test/test.py` **Teil 32** (neu, 14 Prüfungen): 32 A1–A5 (Reader-JSON), 32 B1–B4
  (Repository-Dynamik), 32 C1–C2 (ViewModel), 32 D1–D3 (TablePage) → **alle PASS**.
  Teil 31 (19.01, 11 Prüfungen) unverändert **PASS**.
* Gesamtlauf `test/test.py`: **573 PASS / 6 FAIL** – die 6 Fehler sind die
  dokumentierten **Baseline-Vorbefunde** P2/P5/H3/H4/H5/H7 (Geometrie-Tests,
  offscreen `800x582`) – ohne 19.02-Änderungen identisch, nicht durch 19.02 verursacht.
* Test-Workspace aufgeräumt (Invariante 10): nur `test/test.py` verbleibt.

### Abweichungen vom Plan-Kapitel (per Prüfprotokoll-Entscheidungen)

* Plan-Punkt „Native Spalten → dynamische JSON-Keys": realisiert als
  `available_feature_keys()` (DISTINCT-Strukturen statt `json_keys`-UNNEST, D1).
* Plan-Punkt „Heatmap-Metriken" → D5: unbekannte Metrik fällt auf `"count"` zurück
  (kein `ValueError`-Hänger in der UI).
* Plan-Punkt „Archiv-Dateien" → D4: `ema_diff.py`/`atr_normalized.py` bleiben auf
  Platte (Code-Preserving), werden aber weder importiert noch registriert.

### Status

* **Alle Steps 1–5 abgeschlossen und headless verifiziert.** Keine UI-/Regressionstests
  ausgeführt (Regel 4); Baseline-Vorbefunde P2/P5/H3/H4/H5/H7 sind unverändert
  dokumentiert.

