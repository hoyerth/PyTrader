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

# 20.02 Generische 2D-Heatmap-Engine, Confluence-Matrix, Candle-Overlay & Dual-Axis-Zoom

## 1. Concept & Invariants
- **MVVM Decoupling**: SQL matrix aggregation in `FeatureStoreReader`, state in `AnalyticsViewModel`, passive rendering in View.
- **Confluence Clustering**: Measures spatial-temporal signal density/overlap across active Services (0 = White/Transparent to N = Dark Red).
- **Standalone Field**: Candle-Overlay operates on local chart field context, completely isolated from global header dropdowns.
- **Full Lifecycle Integration**: Auto-persists into active profile (Schema v2.1) on profile change, window close (`closeEvent`), or app exit.

## 2. Core DB Layer (`analytics/engine/feature_store_reader.py`)
- **Dimension Mapping Whitelist (`DIM_MAPPINGS`)**:
  - `date`: `CAST(bar_time AS DATE)`
  - `dow`: `EXTRACT(DOW FROM bar_time AT TIME ZONE 'UTC')::INTEGER`
  - `hour`: `EXTRACT(HOUR FROM bar_time AT TIME ZONE 'UTC')::INTEGER`
  - `dow_hour`: `EXTRACT(DOW FROM bar_time AT TIME ZONE 'UTC')::INTEGER || '_' || EXTRACT(HOUR FROM bar_time AT TIME ZONE 'UTC')::INTEGER`
  - `timeframe`: `LOWER(timeframe)`, `service_id`: `LOWER(feature_id)`, `symbol`: `LOWER(symbol)`
- **`fetch_generic_heatmap(...)`**:
  - **Signature**: `fetch_generic_heatmap(symbol, timeframe, x_dim, y_dim, field_source, target_field, aggregation, feature_ids=None)`
  - **Aggregations**: `COUNT`, `AVG`, `SUM`, `MIN`, `MAX`, `HIT_RATE`, `CONFLUENCE_COUNT` (`COUNT(DISTINCT feature_id)`).
  - **Return**: `{"matrix": List[List[float]], "x_labels": List[str], "y_labels": List[str], "min_val": float, "max_val": float}`

## 3. ViewModel Layer (`analytics/engine/analytics_view_model.py`)
- **State Parameters (`_params`)**: `heatmap_x_dim` ("date"), `heatmap_y_dim` ("hour"), `heatmap_field` ("confluence"), `heatmap_agg` ("CONFLUENCE_COUNT"), `candle_projection_enabled` (False), `zoom_x_range` ([0.0, 1.0]), `zoom_y_range` ([0.0, 1.0]), `selected_feature_ids` (List[str]).
- **Methods**: `set_heatmap_config()`, `set_heatmap_zoom()`, `set_candle_projection()`, `serialize_state()` (for profile/snapshot persistence).

## 4. UI Layer & Dual-Axis Zoom
- **`chk_candle_projection`**: Toggles semi-transparent OHLCV overlay from `market_data.duckdb`. Enabled only on temporal X-dimensions (`date`, `dow`, `hour`, `dow_hour`).
- **`slider_zoom_x` & `slider_zoom_y`**: Real-time viewport bounds scaling without DB requeries; syncs Heatmap cells and projected Candlesticks.

---

# Implementation Step-by-Step Guide

### Step 1: SQL Matrix Engine (`analytics/engine/feature_store_reader.py`)
1. Add `DIM_MAPPINGS` dict covering `date`, `dow`, `hour`, `dow_hour`, `timeframe`, `service_id`, `symbol`.
2. Implement `fetch_generic_heatmap(...)` with SQL `GROUP BY x_val, y_val` using DuckDB JSON extract (`feature_data->>'target_field'`) or `COUNT(DISTINCT feature_id)` for `CONFLUENCE_COUNT`.
3. Format output as dense N x M pivot matrix with bounds (`min_val`, `max_val`).

### Step 2: ViewModel Logic & State Management (`analytics/engine/analytics_view_model.py`)
1. Extend `_params` dictionary with Heatmap configuration keys, zoom ranges, and selection filters.
2. Implement `set_heatmap_config(x_dim, y_dim, field, agg)`, `set_heatmap_zoom(x_range, y_range)`, and `set_candle_projection(enabled)` to trigger async data refresh.
3. Update `export_profile_payload()` and `import_profile_payload()` to read/write under `charts.heatmap` (Schema v2.1).

### Step 3: Heatmap & Confluence Rendering (`analytics/gui/heatmap_widget.py`)
1. Implement color-map scaling (0 = White/Transparent, 1-2 = Yellow/Cyan, 3-4 = Orange, 5+ = Dark Red).
2. Render matrix cells using `PyQtGraph` ImageItem/GraphicsLayout.
3. Bind `slider_zoom_x` and `slider_zoom_y` to update `setXRange`/`setYRange` in real time.

### Step 4: Candle-Overlay & Viewport Sync (`analytics/gui/heatmap_widget.py`)
1. Add `chk_candle_projection` control and connect to ViewModel.
2. Fetch corresponding OHLCV bars from local field context upon activation.
3. Overlay semi-transparent Candlesticks (Alpha 0.3-0.5) linked to Heatmap viewport bounds.

### Step 5: Profile Persistence & Lifecycle Wiring (`analytics/analytics_window.py`)
1. Connect `closeEvent` and `QApplication.aboutToQuit` to trigger automatic `save_last_snapshot()`.
2. Ensure Profile load/save cycle correctly restores and applies `charts.heatmap` settings.
3. Validate via headless tests (`py_compile` and `test/test.py`).

---

## 5. Review 09.08.2026: Konsistenz-, Vollständigkeits- & Korrektheits-Analyse

**Grundlage:** Abgleich des Kapitels 20.02 gegen den verbindlichen Ist-Code
(kein `docs/x_Exports.md`). Geprüfte Dateien: `analytics/engine/feature_store_reader.py`,
`analytics/engine/analytics_repository.py`, `analytics/engine/analytics_view_model.py`,
`analytics/engine/analytics_worker.py`, `analytics/ui/heatmap_page.py`,
`analytics/ui/analytics_win.py`, `analytics_profile_repository.py`,
`analytics/features/feature_builder.py` (OHLCV-Quelle).

### 5.1 Ist-Code-Abgleich (Befunde)

| # | Kapitel-Angabe 20.02 | Ist-Code (verbindlich) | Befund |
|---|----------------------|------------------------|--------|
| A1 | `analytics/gui/heatmap_widget.py` (§3/§4) | `analytics/ui/heatmap_page.py` (`HeatmapPage`, pyqtgraph `ImageItem`, viridis, Jump-to-Chart). Verzeichnis `analytics/gui/` existiert **nicht**. | **Pfadfehler** → E1 |
| A2 | `analytics/analytics_window.py` (§5) | `analytics/ui/analytics_win.py` (`AnalyticsWindow`, `PersistentWindow`, `INSTANCE_ID="win_analytics"`). | **Pfadfehler** → E1 |
| A3 | `DIM_MAPPINGS` + `fetch_generic_heatmap(...)` (§2) | existiert nicht. Ist: `fetch_heatmap(symbol, timeframe, metric, feature_id, feature_ids, limit)` mit **festen** Achsen DOW×Stunde (7×24), Metrik `"count"` \| numerischer JSON-Key (AVG via `TRY_CAST`). | **Neuimplementierung** (additiv) → E1 |
| A4 | VM-`_params` `heatmap_x_dim/y_dim/field/agg`, `candle_projection_enabled`, `zoom_x_range/y_range`, `selected_feature_ids` (§3) | existieren nicht. Ist-`_params` nur `heatmap_metric` + `feature_ids` (Liste). | **Neuimplementierung** (additiv); `selected_feature_ids` ist Redundanz zu `feature_ids` → E10 |
| A5 | `set_heatmap_config/set_heatmap_zoom/set_candle_projection/serialize_state()` (§3) | existieren nicht. Ist: `set_heatmap_metric()`; Persistenz via `_current_payload()` / `_apply_profile()` (+ `_flatten_payload`). | Methoden neu; `serialize_state()` = `_current_payload()`-Erweiterung |
| A6 | `export_profile_payload()` / `import_profile_payload()` (§5 Schritt 2) | existieren nicht. Ist: `_current_payload()` (v2, sectioned) / `_apply_profile()`. | Namenskorrektur → E1 |
| A7 | `chk_candle_projection`, `slider_zoom_x/y` (§4) | existieren nicht (HeatmapPage: nur Metrik-Combo + Doppelklick-Jump-to-Chart). | **Neuimplementierung** → E1/E8/E9 |
| A8 | "Auto-persists into active profile ... on profile change, window close, app exit" (§1) | Profil = **Option B – Explicit Save** (Persistenz NUR auf explizites `save_profile()`); automatisch persistiert wird nur der Workspace im `closeEvent` (`_save_workspace()`, 20.01 E1). | **Widerspruch** → E2 |
| A9 | "Schema v2.1" (§1) | `SCHEMA_VERSION_DEFAULT = 2` (`analytics_profile_repository.py`); es existiert KEINE v2.1. | Kein Bump nötig → E3 |
| A10 | `DIM_MAPPINGS["date"] = CAST(bar_time AS DATE)` (§2) | Wanduhr-Garantie (Invariante 7): `bar_time` ist Berlin-Wanduhr-encoded; DuckDB rechnet TIMESTAMPTZ in die Session-TZ (Berlin +1/+2h) um. | **DST-fragil**: Wanduhr 23:00–23:59 (Sommer) → Folgetag 01:00 → falsches Datum → E4 |
| A11 | `dow`/`hour`/`dow_hour` mit `bar_time AT TIME ZONE 'UTC'` (§2) | exakt das Muster von `fetch_heatmap()` / `fetch_recent_bar_time_for_cell()`. | **konsistent** ✓ |
| A12 | `feature_ids`-Filter (`WHERE feature_id IN (...)`) | `_apply_feature_filter()` (15.03-E) vorhanden. | **konsistent** ✓ |
| A13 | Aggregationen COUNT/AVG/SUM/MIN/MAX/CONFLUENCE_COUNT (§2) | COUNT + AVG-JSON-Muster (`TRY_CAST`) vorhanden; SUM/MIN/MAX/CONFLUENCE_COUNT neu. `HIT_RATE` undefiniert (kein Schwellwert spezifiziert). | Lücke → E5 |
| A14 | "Candle-Overlay ... local chart field context, isolated from global header dropdowns" (§1/§4) | OHLCV-Quelle: `market_data.duckdb`/`ohlcv_bars` (Muster `FeatureBuilder.load_ohlcv()`: Spalten `time, open, high, low, close, tick_volume`). Das Analytics-Fenster hat KEINEN lokalen Chart-Feld-Kontext (nur globale Header-Dropdowns Symbol/TF). | Interpretations-/Präzisierungsbedarf → E9 |

### 5.2 Entscheidungen (E1–E10)

- **E1 – Additive Implementierung & korrigierte Pfade:** Alle Ergänzungen erfolgen additiv
  (Open/Closed, Code-Preserving). Bestehende `fetch_heatmap()`/`get_heatmap()`/`HeatmapPage`
  bleiben unangetastet. Dateien: `analytics/engine/feature_store_reader.py` (additiv),
  `analytics/engine/analytics_repository.py` (additiv), `analytics/engine/analytics_view_model.py`
  (additiv), `analytics/engine/analytics_worker.py` (**neuer Query-Kind `QUERY_HEATMAP_GENERIC`**,
  bestehender `QUERY_HEATMAP` bleibt unverändert → kein Regressionsrisiko), neue UI-Datei
  **`analytics/ui/heatmap_widget.py`** (Korrektur: nicht `analytics/gui/`), Lifecycle in
  `analytics/ui/analytics_win.py`. Methodenbenennung wie Kapitel (`set_heatmap_config()` usw.)
  statt der nicht existenten `export/import_profile_payload()`.
- **E2 – Persistenz-Semantik (Kapitel-Korrektur):** Es gibt KEIN Auto-Save ins aktive Profil
  (Option B – Explicit Save bleibt verbindlich). Die Heatmap-Config wird
  (a) bei `save_profile()` additiv unter `charts.heatmap` persistiert und
  (b) automatisch über den bestehenden Workspace-Mechanismus gesichert (`closeEvent` →
  `_save_workspace()` → `instance_states.workspace_state`, 20.01 E1). Ein separater
  `QApplication.aboutToQuit`-Hook ist **nicht** nötig – der App-Exit wird bereits durch das
  `closeEvent` der Top-Level-Fenster abgedeckt (Ist-Verhalten 20.01).
- **E3 – Kein Schema-Bump auf v2.1:** `schema_version: 2` bleibt. Die Sektion
  `charts.heatmap` ist additiv (bestehende v2-Sektionen sind dafür ausgelegt, 20.01 E3:
  "neue UI-Settings lassen sich additiv ergänzen, kein Schema-Bump nötig").
  Die `_flatten_payload`-Lücke (verschachteltes `charts.heatmap`-Dict wird NICHT automatisch
  auf flache `_params` abgebildet) wird durch explizite Auflösung in `_apply_profile()` /
  `restore_workspace()` geschlossen.
- **E4 – `date`-Mapping Wanduhr-sicher:** `DIM_MAPPINGS["date"] =
  CAST(bar_time AT TIME ZONE 'UTC' AS DATE)` (konsistent zu dow/hour, Invariante 7).
- **E5 – Aggregationen & HIT_RATE:** COUNT, AVG, SUM, MIN, MAX (JSON-Werte via `TRY_CAST`,
  Muster `fetch_heatmap`), CONFLUENCE_COUNT = `COUNT(DISTINCT feature_id)`. **HIT_RATE
  entfällt in V1** (ohne definierten Schwellwert nicht spezifizierbar); bei Bedarf später
  mit explizitem Schwellwert-Parameter nachrüsten.
- **E6 – Feld-Terminologie:** `field` = numerischer `feature_data`-JSON-Key. `heatmap_field
  = "confluence"` ist KEIN JSON-Key, sondern wählt die CONFLUENCE_COUNT-Aggregation.
  Bei AVG/SUM/MIN/MAX ist `field` Pflicht (JSON-Key); bei COUNT/CONFLUENCE_COUNT wird
  `field` ignoriert.
- **E7 – Farbskala:** Konfluenz (CONFLUENCE_COUNT) → diskrete Stufen laut Kapitel
  (0 = weiß/transparent, 1–2 = gelb/cyan, 3–4 = orange, 5+ = dunkelrot);
  Wert-Metriken (count/avg/...) → kontinuierliche viridis-Skala (Ist-Verhalten beibehalten).
  Colormap-Umschaltung abhängig von `agg`.
- **E8 – Dual-Axis-Zoom:** Slider nur aktiv bei Dimensionen mit vielen diskreten Werten
  (v. a. X=`date`); bei dow (7) / hour (24) / timeframe / service_id deaktiviert.
  `zoom_x_range`/`zoom_y_range` als [0.0, 1.0]-normalisierte Viewport-Anteile, geclampt
  (0 ≤ lo < hi ≤ 1), rein client-seitig via `setXRange`/`setYRange` (kein DB-Requery);
  Persistenz im Profil (`charts.heatmap.zoom_*`) und Workspace.
- **E9 – Candle-Overlay (Kapitel-Korrektur):** Quelle = `market_data.duckdb`/`ohlcv_bars`
  über eine neue read-only Repository-Methode `get_ohlcv_snapshot(symbol, timeframe, limit)`
  (delegierend auf eine neue Reader-Methode; kein SQL in der UI). **Overlay nur bei
  X-Dimension `date`** (kontinuierliche Zeitachse – pro X-Spalte = OHLCV-Gruppe des Tages,
  Alpha 0.3–0.5); bei dow/hour/dow_hour semantisch nicht definierbar → `chk_candle_projection`
  dort deaktiviert (Präzisierung der Kapitel-Angabe "temporal X-dimensions"). Der Snapshot
  wird bei Aktivierung aus dem aktuellen (symbol, timeframe)-Filter erzeugt (keine Reaktion
  auf globale Dropdown-Events = "isolated from global header dropdowns").
- **E10 – Keine Parameter-Duplikation:** `selected_feature_ids` entfällt – der bestehende
  `feature_ids`-Parameter wird unverändert als Datenquellen-Filter übernommen.

### 5.3 Vollständigkeits-Lücken (im Kapitel fehlend, ergänzt)

1. **Worker-/Repository-Dispatch:** Kapitel nennt nur Reader + ViewModel + UI. Ergänzt:
   neuer Query-Kind `QUERY_HEATMAP_GENERIC` in `analytics_worker.py` + `get_generic_heatmap()`
   in `analytics_repository.py` (inkl. `metrics`-Liste im Payload, Muster `get_heatmap()`).
2. **Payload-Vertrag:** generisches Payload liefert `matrix` (dense), `x_labels`, `y_labels`,
   `min_val`, `max_val`, `x_dim/y_dim/agg/field`, `metrics`, `symbol`, `timeframe` –
   UI-Combo-/Slider-Sync aus dem Payload (Muster `get_heatmap()`).
3. **Leerzellen:** count/COUNT → 0.0, AVG/SUM/MIN/MAX → NaN (bestehendes Muster
   `fetch_heatmap`); Rendering ignoriert NaN (Ist-Verhalten).
4. **Limit-Cap:** generische Abfrage nutzt `cap_lookback_limit()` (MAX_LOOKBACK_LIMIT 50.000).
5. **Pivot-Begrenzung:** max. Zellenzahl defensiv deckeln (z. B. 50.000 Zellen;
   date×hour ≈ 366×24 = 8.784 – unkritisch; date×dow_hour ≈ 366×168 = 61.488 – kritisch,
   daher für `dow_hour` auf vorhandene Kombinationen beschränken oder cap).
6. **`_flatten_payload`-Lücke:** `charts.heatmap` (verschachteltes Dict) wird vom bestehenden
   `_flatten_payload()` NICHT auf `_params`-Keys abgebildet → explizite Auflösung
   (`charts.heatmap.*` → `heatmap_x_dim`, `heatmap_y_dim`, `heatmap_field`, `heatmap_agg`,
   `candle_projection_enabled`, `zoom_x_range`, `zoom_y_range`) in `_apply_profile()` /
   `restore_workspace()`.
7. **Bezeichnungen:** Label-Formatierung für `date`-Achse (z. B. `DD.MM.`) und `dow_hour`
   (z. B. `Mo_14`) spezifizieren; Wiederverwendung von `DOW_LABELS`/`HOURS_PER_DAY`.

### 5.4 Korrigierte Implementierungs-Schrittliste (verbindlich ab 09.08.2026)

1. **Schritt 1 (SQL-Matrix-Engine):** additiv in `analytics/engine/feature_store_reader.py`
   – `DIM_MAPPINGS` (date/dow/hour/dow_hour/timeframe/service_id/symbol; E4 beachten) +
   `fetch_generic_heatmap(symbol, timeframe, x_dim, y_dim, field, agg, feature_ids, limit)`
   mit Pivot-Ausgabe und `min_val`/`max_val`.
2. **Schritt 2 (Repository/Worker/ViewModel):**
   `analytics_repository.py` → `get_generic_heatmap()` (Payload inkl. `metrics`);
   `analytics_worker.py` → `QUERY_HEATMAP_GENERIC`-Dispatch;
   `analytics_view_model.py` → `_params`-Keys (E10: ohne `selected_feature_ids`),
   `set_heatmap_config()/set_heatmap_zoom()/set_candle_projection()`,
   `_current_payload()`-Erweiterung (`charts.heatmap`, E2/E3), Auflösung in
   `_apply_profile()`/`restore_workspace()` (Lücke 5.3-6).
3. **Schritt 3 (Heatmap/Confluence-Rendering):** NEUE Datei `analytics/ui/heatmap_widget.py`
   – diskrete Konfluenz-Skala (E7), viridis für Wert-Metriken, Einbettung als Modus in die
   bestehende `analytics/ui/heatmap_page.py` (additiv, Dow×Hour bleibt Standard-Modus),
   Slider-Bindung an `setXRange`/`setYRange` (E8).
4. **Schritt 4 (Candle-Overlay):** `get_ohlcv_snapshot()` (E9), `chk_candle_projection`
   nur bei X=`date` aktiv, semi-transparente Candles an die Heatmap-Spalten gebunden.
5. **Schritt 5 (Lifecycle):** `analytics/ui/analytics_win.py` – Erweiterung von
   `_save_workspace()`/`_restore_workspace()` um die Heatmap-Config; KEIN
   `aboutToQuit`/`save_last_snapshot`-Neu-Hook (E2); Validierung headless via
   `py_compile` + `test/test.py` (Logik-/DB-Tests, keine UI-Tests).

---

## 5.5 Umsetzungs-Log 09.08.2026 (Kapitel 20.02 umgesetzt)

**Umgesetzte Dateien (additiv, Open/Closed – Bestandscode unveraendert):**

| Datei | Änderung |
|-------|----------|
| `analytics/engine/feature_store_reader.py` | + `DB_MARKET`, `DIM_MAPPINGS`, `HEATMAP_DIMENSIONS`, `HEATMAP_AGGREGATIONS`, `MAX_HEATMAP_CELLS`, `OHLCV_SNAPSHOT_LIMIT`, `_format_dim_value()`, `fetch_generic_heatmap()`, `_empty_generic_heatmap()`, `fetch_ohlcv_snapshot()` |
| `analytics/engine/analytics_repository.py` | + `get_generic_heatmap()` (inkl. `metrics` + defensives `field`-Fallback), `get_ohlcv_snapshot()` |
| `analytics/engine/analytics_worker.py` | + `QUERY_HEATMAP_GENERIC`, `QUERY_OHLCV` + Dispatch |
| `analytics/engine/analytics_view_model.py` | + `_params`: `heatmap_x_dim/y_dim/field/agg`, `candle_projection_enabled`, `zoom_x_range/y_range`; + `request_heatmap_generic()`, `request_ohlcv_snapshot()`, `set_heatmap_config()`, `set_heatmap_zoom()`, `set_candle_projection()`, `_clamp_zoom()`, `_apply_heatmap_section()`; `refresh_all()` + `QUERY_HEATMAP_GENERIC`; `_current_payload()` + `charts.heatmap`; `_current_params()`-Zweige |
| `analytics/ui/heatmap_widget.py` | **NEU:** `HeatmapWidget` – generische Heatmap (dims/agg/field), diskrete Konfluenz-Skala (E7), viridis für Wert-Metriken, Zoom-Slider (E8), Preis-Strip (E9) |
| `analytics/ui/heatmap_page.py` | + Modus-Combo (`standard` \| `generic`), `QStackedWidget`, `mode_id`/`set_mode()`, `request_data()` modus-abhängig |
| `analytics/ui/analytics_win.py` | `_save_workspace()` + `layout.heatmap_mode`; `_restore_workspace()` wendet `heatmap_mode` an |
| `test/test.py` | + Tests 37 a1–j2 (Reader/Repository/Worker/ViewModel, headless, temporäre DuckDBs in `test/`) |

**Umsetzungs-Nachtraege (Präzisierungen der Review-Entscheidungen E1–E10):**

1. **`dow_hour`-Encoding (E4-Nachtrag):** Statt des Kapitel-Literals
   `|| '_' ||` (String-Konkatenation, lexikografisch falsch sortiert) wird
   `DOW*24+HOUR` als INTEGER encodiert – natuerliche Sortierreihenfolge
   (Mo_00..So_23), Dekodierung in `_format_dim_value()`.
2. **Candle-Overlay (E9-Präzisierung):** Der Preis-Strip wird als separates
   Plot-Fenster UNTER der Heatmap gerendert (Tages-Ohlc je Datums-Spalte,
   Alpha 0.3–0.5), horizontal mit der Heatmap synchronisiert (Zoom X wirkt
   auf beide). Aktiv nur bei X-Dimension `date` (beliebige Y-Dimension).
   Quell-Daten: `market_data.duckdb`/`ohlcv_bars` (read-only via
   `fetch_ohlcv_snapshot()`, Wanduhr-Epochs).
3. **Dual-Axis-Zoom (E8-Präzisierung):** EIN Faktor-Slider pro Achse
   (Viewport-Skalierung, zentriert; Slider-Wert = sichtbarer Anteil in %),
   normalisiert `[lo, hi]` gespeichert. Aktiv nur bei `date`-Achsen
   (`_ZOOMABLE_DIMS`); rein client-seitig (kein DB-Requery).
4. **Lookback im Reader-CTE:** `fetch_generic_heatmap()` wendet `limit` im
   CTE auf die NEUESTEN `limit` Bars an (ORDER BY bar_time DESC) – konsistent
   zum Limit der Analytics-Tabelle (Default 5000).
5. **Kein `selected_feature_ids` (E10):** `feature_ids` bleibt der einzige
   Datenquellen-Filter.
6. **Kein Auto-Save ins Profil (E2):** Persistenz der Heatmap-Config nur via
   `save_profile()` (`charts.heatmap`) und automatisch über den Workspace
   (`closeEvent` → `_save_workspace()`, inkl. `heatmap_mode`).

**Validierung (headless, 09.08.2026):**
- `py_compile` auf allen 7 geänderten Python-Dateien + `test/test.py`: PASS.
- `test/test.py`: **30 neue Checks 37 a1–j2 alle PASS** (Matrix-Form/-Werte,
  Confluence, AVG-JSON-Key, dow_hour-Labels, feature_ids-Filter, ValueError,
  Repository-Fallbacks, OHLCV-Snapshot inkl. Wanduhr-Epoch, VM-Params,
  Payload-`charts.heatmap`, Profil-Roundtrip via `_apply_heatmap_section`,
  Worker-Dispatch).
- **6 vorbestehende Fehlschläge** (P2/P5/H3–H7, Fenstergeometrie-Tests des
  Harness-Kopfes, Zeilen 133–223) sind Umgebungs-/offscreen-bedingt und
  unabhängig von dieser Umsetzung (kein Kontakt zu geänderten Dateien).
- UI (HeatmapPage/HeatmapWidget) wurde nur als offscreen-Instanziierung
  geprüft (kein GUI-Start, keine UI-Tests gemäß harter Regel).
- Manueller Funktionstest der GUI erfolgt durch den Anwender.

---

## 5.6 Bugfix-Log 08./09.08.2026 (Analytics – manuell vom Anwender bestätigt)

**Kontext:** Drei User-Meldungen nach Umsetzung von Kapitel 20.02
(Generische 2D-Heatmap-Engine). Alle Fixes sind additiv/point-fix –
bestehende Strukturen und Logik blieben unverändert.

### Bugfix A (08.08.2026, Commit `90f78dd`): Keine Anzeige ausgewählter Services + Tree aufgeklappt

| # | Symptom | Ursache | Fix |
|---|---------|---------|-----|
| A1 | Analytics-Tabelle zeigt keine Einträge, obwohl Services im MasterTree angehakt sind | `_apply_feature_filter` (analytics/engine/analytics_view_model.py) filterte case-sensitiv und nicht whitespace-tolerant – `feature_id`-Vergleich schlug bei Groß-/Kleinschreibung fehl | Filter case-insensitiv + whitespace-tolerant: `LOWER(TRIM(feature_id))`; VM-Setter refreshen auch `QUERY_HEATMAP_GENERIC`/`QUERY_OHLCV` |
| A2 | MasterTree-Knoten (Set/Service/Plugin) bleiben nach Anhaken aufgeklappt / kollabieren ungewollt | fehlende Expansion der Vorfahren beim Setzen der Checkboxen | `master_tree.py`: neue `_expand_ancestors()` in `set_checked_feature_ids` + `_on_item_changed` |

**Validierung:** `test/check_bugfix_0808.py` 9/9 PASS; `test/test.py` Block 38 (9 Checks) ergänzt.

### Bugfix B (09.08.2026, Commit `3e7c220`): Seiten-Navigation zeigt immer nur die Tabelle

| # | Symptom | Ursache | Fix |
|---|---------|---------|-----|
| B1 | Egal welcher Menüeintrag im Analytics-Fenster (Tabelle/Heatmap/Verteilung/Scatter) – sichtbar blieb immer die Tabelle | Alt-Bug seit Phase 15.03: `AnalyticsWindow._on_page_changed` rief nur `page.request_data()` auf, **ohne** `self.pages_stack.setCurrentIndex(row)` – der Stack blieb dauerhaft auf Index 0 | `_on_page_changed` (analytics/ui/analytics_win.py): `self.pages_stack.setCurrentIndex(row)` VOR `request_data()`; ungültige Rows bleiben ohne Crash |

**Validierung:** `test/check_page_nav.py` 7/7 PASS (Stack folgt Row 1/3/0/2, ungültige Row kein Crash, `request_data` je Page genau 1x).

### Bugfix C (09.08.2026, Commit `3e7c220`): Traceback in der Heatmap-Candle-Projektion

| # | Symptom | Ursache | Fix |
|---|---------|---------|-----|
| C1 | Beim Aktivieren der Candle-Projektion im Heatmap-Modus: `Exception: must specify either y1 or height` | `pg.BarGraphItem` kennt KEIN `top=`/`bottom=` – die pyqtgraph-API verlangt `y0` + `height` | `_render_overlay` (analytics/ui/heatmap_widget.py): Docht = `y0=l, height=max(h-l, 1e-9)`, Körper = `y0=min(o,c), height=max(max(o,c)-min(o,c), 1e-9)` |

**Validierung:** `py_compile` OK; offscreen-Smoke-Test `BarGraphItem(x=[0.5], width=0.12, y0=9.5, height=1.0)` PASS (kein GUI-Start, keine UI-Tests gemäß harter Regel).

---

# 20.02.01 Heatmap-UI-Präzision: Datumsskala, feste Zeitachsen, Overlay-Zoom-Lock & Service-Anzeige

## 1. Kapitel-Vorgabe (User-Anweisung, 09.08.2026)

1. **Präzision Skala "Datum"** – dynamischer Zoom-Formatter für die X-Achse bei `date`:
   - > 1 Jahr: `YYYY` / `MMM YYYY`
   - 1 Monat–1 Jahr: `DD.MM.YY`
   - 1 Tag–1 Monat: `DDD DD.MM.YY`
   - 2 Std–1 Tag: `DDD DD.MM.YY HH:00`
   - < 2 Std: `DDD DD.MM.YY HH:mm`
   - Wanduhr-Garantie: `datetime.fromtimestamp(ts, tz=timezone.utc)` (kein Berlin-Offset).
2. **Feste Skalen & Umbenennung:**
   - `"Stunde"` → `"Tageszeit"` (UI + Code).
   - Harter Range 00:00–23:59 für Tageszeit; Achsen-Label mit UTC-Offset (z. B. `Tageszeit (UTC+2)`).
   - `"Wochentag"`-Range strikt Montag–Freitag.
   - **`dow_hour` ersatzlos aus UI-Dropdowns & `DIM_MAPPINGS` entfernen.**
3. **Candle-Overlay Zoom-Lock:** Exklusiv bei X=`date`; bei anderen X-Dimensionen automatisch
   ausblenden & Zoom-Sync entkoppeln.
4. **UI Service-Anzeige:** `srv_`-Prefix strippen (`srv_trend_breakout` → `Trend Breakout`),
   Format `{Kategorie} / {Service_Name}`, Mindestbreite erhöhen.

## 2. Analyse 09.08.2026: Ist-Code-Abgleich

**Grundlage:** Abgleich der Kapitel-Vorgabe 20.02.01 gegen den verbindlichen Ist-Code
(kein `docs/x_Exports.md`, keine `docs/Current`). Geprüfte Dateien:
`analytics/engine/feature_store_reader.py`, `analytics/engine/analytics_view_model.py`,
`analytics/ui/heatmap_widget.py`, `analytics/ui/heatmap_page.py`,
`analytics/engine/service_selector_model.py`, `serviceui/service_selector_dialog.py`,
`analytics/ui/analytics_win.py`.

### 2.1 Befunde

| # | Kapitel-Vorgabe 20.02.01 | Ist-Code (verbindlich) | Befund |
|---|--------------------------|------------------------|--------|
| B1 | Dynamischer Zoom-Formatter `date` mit 5 Stufen | `_HeatmapAxis._format` (heatmap_widget.py): nur 3 Stufen – ≥1d `%d.%m.%y`, ≥1h `%d.%m. %H:%M`, <1h `%H:%M`. Wanduhr via `datetime.fromtimestamp(v, tz=dt_timezone.utc)` ✓ | **Abweichung** → E1 |
| B2 | `"Stunde"` → `"Tageszeit"` (UI + Code) | `_DIM_LABELS["hour"] = "Stunde"` (heatmap_widget.py, generisches Widget). Legacy-Standard-HeatmapPage nutzt "Stunde (Berlin Wanduhr)" (Dow×Stunde, 15.03) | Abweichung im generischen Widget → E2 |
| B3 | Harter Range Tageszeit 00:00–23:59 | `_axis_bounds("hour")`: `lo-0.5 .. hi+0.5` (datenabhängig, z. B. -0.5..23.5) | **Abweichung** → E3 |
| B4 | Achsen-Label mit UTC-Offset (`Tageszeit (UTC+2)`) | `setLabel` nutzt `_DIM_LABELS` ohne Offset-Angabe | fehlt → E4 |
| B5 | `Wochentag` strikt Montag–Freitag | `dow` = `EXTRACT(DOW ...)` 0..6 (So..Sa), Labels via `DOW_LABELS`; `_axis_bounds` datenabhängig (-0.5..6.5) | **Abweichung** → E5 |
| B6 | `dow_hour` ersatzlos entfernen | Reader: `DIM_MAPPINGS`, `HEATMAP_DIMENSIONS`, `_format_dim_value`, `_axis_coords`; Widget: `_DIM_LABELS`, `_HeatmapAxis._format`, `_axis_bounds`; VM: Persistenz-Pfade `_apply_heatmap_section`/`restore_workspace` | → E6 |
| B7 | Overlay-Zoom-Lock (X=`date` exklusiv, Sync entkoppeln) | Checkbox bereits exklusiv bei X=`date` (`_update_controls`/`_on_config_changed` auto-uncheck). Aber: `_price_vb.setXLink(plotItem.vb)` bleibt dauerhaft gelinkt (auch bei X≠date) | teils umgesetzt → E7 |
| B8 | Service-Anzeige: `srv_`-Prefix strippen, `{Kategorie} / {Service_Name}`, Mindestbreite | Es existiert **KEIN** Service-Dropdown in heatmap_page.py (Service-Auswahl = `ServiceSelectorDialog`/MasterTree, 15.03-E; Kategorien dort bereits über 📁-Ordner-Hierarchie). In der generischen Heatmap ist `service_id` eine X/Y-Dimension – Achsen-Labels = rohe plugin_ids (`_format_dim_value` → `str(value)`) | Interpretationsklärung → E8 |

### 2.2 Entscheidungen (E1–E8)

- **E1 – Datums-Formatter auf 5 Stufen:** `_HeatmapAxis._format` für `date` auf die
  Kapitel-Stufen umstellen – Schwellen: `spacing >= 31536000` → `%Y` (Jahresskala),
  `>= 2592000` → `%d.%m.%y`, `>= 86400` → `DDD %d.%m.%y`, `>= 7200` → `DDD %d.%m.%y %H:00`,
  sonst → `DDD %d.%m.%y %H:%M`. `DDD` = deutscher Wochentag **locale-unabhängig** über
  `DOW_LABELS[(dt.weekday() + 1) % 7]` (konsistent zur App; `strftime("%a")` wäre
  locale-abhängig). `_pick_time_step`-Schrittliste bleibt unverändert (1M = 2592000,
  1J = 31536000 bereits enthalten).
- **E2 – Umbenennung nur im generischen Widget:** `_DIM_LABELS["hour"] = "Tageszeit"`
  (Combos + Achsen-Label des HeatmapWidget). Die Legacy-Standard-HeatmapPage
  (Dow×Stunde, "Stunde (Berlin Wanduhr)") bleibt unverändert (Open/Closed, additive
  20.02-Philosophie; kein Refactoring des 15.03-Bestands).
- **E3 – Feste Skala Tageszeit:** `_axis_bounds` liefert bei `dim == "hour"` **konstant**
  `(0.0, 24.0)` – unabhängig vom Datenbereich (stabile Vergleichbarkeit zwischen Symbol/
  Timeframe). Zellen halboffen `[h, h+1)`, Ticks bei ganzzahligen Stunden (`HH:00`-Labels).
  Zoom-Slider funktionieren weiterhin (normalisierte Viewport-Anteile auf der festen Skala).
- **E4 – UTC-Offset-Label:** Offset aus dem NEUESTEN Datumswert der Achse (`x_axis[-1]`)
  via `datetime.fromtimestamp(ts, tz=ZoneInfo("Europe/Berlin")).utcoffset()` → volle
  Stunden; Label `Tageszeit (UTC+2)` bzw. `Tageszeit (UTC+1)` – DST-robust (Offset folgt
  dem Datum der Daten). `zoneinfo` aus der stdlib (Python 3.9+), kein neues Paket.
- **E5 – Wochentag strikt Mo–Fr:** SQL-Filter in `fetch_generic_heatmap`: wenn
  `x_dim == "dow"` bzw. `y_dim == "dow"` → zusätzliche WHERE-Bedingung
  `EXTRACT(DOW FROM bar_time AT TIME ZONE 'UTC')::INTEGER BETWEEN 1 AND 5`
  (DuckDB: Mo = 1 … Fr = 5). Neue Mapping-Konstante `DOW_WEEK_LABELS = ("Mo", "Di", "Mi",
  "Do", "Fr")`; `_format_dim_value("dow", v)` für v ∈ 1..5 → `DOW_WEEK_LABELS[v-1]`
  (Alt-Werte 0/6 defensiv → `str(v)`). `_axis_bounds("dow")` konstant `(1.0, 6.0)`.
  `DOW_LABELS` (7 Tage, So..Sa) bleibt für die Legacy-Standard-Heatmap unverändert.
- **E6 – `dow_hour` ersatzlos entfernen:** Entfernen aus `DIM_MAPPINGS`,
  `HEATMAP_DIMENSIONS`, `_format_dim_value`, `_axis_coords` (Reader) sowie `_DIM_LABELS`,
  `_HeatmapAxis._format`, `_axis_bounds` (Widget) + betroffene Docstrings.
  **Persistenz-Sanitizer:** `_apply_heatmap_section` + `restore_workspace` +
  `set_heatmap_config` (ViewModel) mappen `"dow_hour"` defensiv auf `"hour"` – sonst würde
  `_set_combo_data` (additives Hinzufügen unbekannter Werte) die entfernte Dimension in
  Alt-Profilen/Workspaces wieder in die Combo aufnehmen. Tests anpassen:
  `test/test.py` Block 37 d1/d2 (dow_hour) und `test/check_heatmap_bugfix.py`
  (dow_hour-Achsen) auf die neue feste Skala (`dow`/`hour`) umstellen.
- **E7 – Overlay-Zoom-Lock vervollständigen:** Bei X ≠ `date` →
  `_clear_overlay()` + `_price_vb.setXLink(None)` (Entkopplung der Zoom-Sync) + Checkbox
  deaktiviert (bereits vorhanden); bei X = `date` → `setXLink(plotItem.vb)` wieder linken.
  Damit ist die Preis-ViewBox bei nicht anwendbaren X-Dimensionen vollständig entkoppelt
  (keine Viewport-Mitnahme, kein Rest-Rendering).
- **E8 – Service-Anzeige (Interpretation von Punkt 4):** Punkt 4 bezieht sich auf die
  `service_id`-Dimension der generischen Heatmap (ein separates Service-Dropdown existiert
  in heatmap_page.py nicht; der ServiceSelectorDialog bildet Kategorien bereits über die
  📁-Ordner-Hierarchie ab). Umsetzung MVVM-konform: ViewModel erhält
  `resolve_service_label(plugin_id) -> str` (lazy `_selector_model`, Muster
  `_resolve_feature_ids`): plugin.metadata → `display_name` (Service-Name, z. B.
  "Trend Breakout") + `category`-Pfad (`plugin_category_path`, Slash → " / ", z. B.
  "Swing Points / Trend Breakout"). Das HeatmapWidget formatiert die kategorialen
  Achsen-Labels für `service_id` über den Resolver; `_combo_x`/`_combo_y` erhalten eine
  erhöhte `setMinimumWidth(...)`. Fallback: unbekannte/entfernte IDs → Rohwert.

### 2.3 Betroffene Dateien (geplant)

| Datei | Änderung |
|-------|----------|
| `analytics/engine/feature_store_reader.py` | `dow_hour` entfernen (DIM_MAPPINGS/HEATMAP_DIMENSIONS/_format_dim_value/_axis_coords/Docstrings); Mo–Fr-Filter für `dow` in `fetch_generic_heatmap`; `DOW_WEEK_LABELS` |
| `analytics/ui/heatmap_widget.py` | Datums-Formatter 5 Stufen (E1); `_DIM_LABELS["hour"]="Tageszeit"` (E2); feste Skalen hour `[0,24)` / dow `[1,6)` (E3/E5); UTC-Offset-Label (E4); `dow_hour` entfernen (E6); Overlay-Zoom-Lock via `setXLink` (E7); Service-Label-Resolver + Combo-Mindestbreite (E8) |
| `analytics/engine/analytics_view_model.py` | `_sanitize_dim()` (dow_hour → hour) in `_apply_heatmap_section`/`restore_workspace`/`set_heatmap_config` (E6); `resolve_service_label()` (lazy `_selector_model`, E8) |
| `test/test.py` | Block 37 d1/d2 (dow_hour) → neue feste Skalen-Checks |
| `test/check_heatmap_bugfix.py` | dow_hour-Checks ersetzen/anpassen |

### 2.4 Validierung (headless, nach Freigabe)

- `py_compile` auf den geänderten Python-Dateien.
- `test/test.py` Block 37 (angepasst) + isolierter Check in `test/`.
- Keine UI-Tests (harte Regel 4); manueller Funktionstest der GUI durch den Anwender.

---

## 5.7 Umsetzungs-Log 09.08.2026 (Kapitel 20.02.01 – umgesetzt)

**Status:** Analyse + Entscheidungen (E1–E8) abgeschlossen; Umsetzung erfolgt
und manuell vom Anwender bestätigt. Die E1–E8-Änderungen und die
User-Meldungen 1–3 (Abschnitt 5.9) wurden zusammen committet (Commit `86f0527`).

| E | Entscheidung | Umsetzung |
|---|--------------|-----------|
| E1 | Datums-Formatter 5 Stufen | `_HeatmapAxis._format` (`date`): Schwellen 1J/1M/1T/2h/`<2h` → `YYYY` / `TT.MM.JJ` / `DDD TT.MM.JJ` / `DDD TT.MM.JJ HH:00` / `DDD TT.MM.JJ HH:mm`; DDD locale-unabhängig via `DOW_LABELS[(weekday + 1) % 7]`; Wanduhr via UTC-Darstellung (kein Berlin-Offset) |
| E2 | "Stunde" → "Tageszeit" | `_DIM_LABELS["hour"] = "Tageszeit"` (nur generisches Widget; Legacy-HeatmapPage Dow×Stunde unverändert) |
| E3 | Feste Skala Tageszeit | `_axis_bounds("hour")` konstant `(0.0, 24.0)` (Zellen halboffen `[h, h+1)`, 00:00–23:59) |
| E4 | UTC-Offset-Label | `_utc_offset_text()`: Offset aus dem neuesten Datums-Epoch der Achse (bzw. Systemzeit) → `Tageszeit (UTC+2)` / `(UTC+1)`, DST-robust |
| E5 | Wochentag strikt Mo–Fr | SQL-Filter in `fetch_generic_heatmap` (`EXTRACT(DOW ...) BETWEEN 1 AND 5`); neue `DOW_WEEK_LABELS`; `_format_dim_value`/`_format` Mo–Fr; `_axis_bounds("dow")` konstant `(1.0, 6.0)` |
| E6 | `dow_hour` ersatzlos entfernt | Reader (`DIM_MAPPINGS`/`HEATMAP_DIMENSIONS`/`_format_dim_value`/`_axis_coords`) + Widget (`_DIM_LABELS`/`_format`/`_axis_bounds`); VM-Sanitizer `_sanitize_dim()` in `set_heatmap_config`/`_apply_heatmap_section`/`_apply_profile`/`restore_workspace` (Alt-Payloads → "hour") |
| E7 | Overlay-Zoom-Lock | `_update_controls`: `setXLink` NUR bei X=date + Overlay an; sonst `setXLink(None)` (Preis-ViewBox vollständig entkoppelt) |
| E8 | Service-Anzeige | `resolve_service_label()` im ViewModel (`{Kategorie} / {Name}`, `srv_`-Prefix entfällt, lazy `_selector_model`); `service_id`-Achsen-Labels via Resolver; X/Y-Combo-Mindestbreite 160 px |

**Validierung (headless):** `py_compile` auf allen geänderten Dateien; die
E1–E8-Checks sind in `test/check_heatmap_bugfix.py` integriert (feste Skalen,
Mo–Fr-Labels, 5-Stufen-Datumsformat, UTC-Offset, `dow_hour`-Sanitizer via
`_axis_bounds`, Overlay-Zoom-Lock); Details in Abschnitt 5.9.
---

## 5.8 Bugfix-Log 09.08.2026: Heatmap-Umbau (User-Meldungen 1–6) + WAL-Guard

**Kontext:** Sechs User-Meldungen nach Umsetzung von Kapitel 20.02
(generische 2D-Heatmap). Alle Fixes sind point-fix/additiv –
bestehende Strukturen (Standard-Modus `HeatmapPage` Dow×Stunde,
`fetch_ohlcv_snapshot`/`QUERY_OHLCV`) blieben unangetastet.
Commit: `01229b1`.

### Entscheidungen (H1–H7)

| # | Entscheidung | Detail |
|---|--------------|--------|
| H1 | **Overlay im selben Canvas** (Punkt 1) | Kerzen-Overlay ist KEIN separates PlotWidget mehr (`_plot_px` entfernt). Zweite Y-Achse "Preis" rechts im selben `PlotWidget`; eigene `ViewBox` `_price_vb` teilt per `setXLink` die X-Achse mit der Heatmap und zeichnet per `setZValue(10)` über dem ImageItem. Neuer Query-Kind `QUERY_DAILY_OHLC` |
| H2 | **Alle Daten statt 5000er-Lookback** (Punkt 2) | `QUERY_HEATMAP_GENERIC` setzt im ViewModel KEIN `limit` mehr (`limit=None`). Der bisherige 5000er-Lookback schnitt die Heatmap auf ~4 Tage (M1) ab. Matrix-Begrenzung übernimmt der bestehende Pivot-Deckel `MAX_HEATMAP_CELLS` (50.000) |
| H3 | **Tages-Ohlc SQL-seitig** (Punkte 1+2) | Neues `fetch_daily_ohlc()` im Reader: aggregiert `ohlcv_bars` pro Wanduhr-Tag in SQL (`GROUP BY CAST("time" AT TIME ZONE 'UTC' AS DATE)`, `FIRST(open)/MAX(high)/MIN(low)/LAST(close)`) – kein Laden aller Bars + Python-Gruppierung (> 1 Mio. Bars bei M1). Default `DAILY_OHLC_MAX_DAYS = 4000`. `fetch_ohlcv_snapshot()` bleibt unverändert (Alt-Aufrufer/Tests) |
| H4 | **Natürliche Achsen-Werte** (Punkte 3+4) | Reader liefert neue `x_axis`/`y_axis` im generischen Payload: `date` → Wanduhr-Mitternachts-Epochs (Sekunden), `hour`/`dow`/`dow_hour` → Ganzzahlen (0–23 bzw. 0–167), kategorial → Indizes. `ImageItem` wird per `setRect` exakt auf den Bereich gemappt (date: ± halber Tag um Mitternacht; ganzzahlig: ±0,5; kategorial: −0,5..n−0,5) → nichts wird über die Tagesgrenze gezeichnet; Achsen-Zuordnung explizit (x_dim→X, y_dim→Y), kein Vertauschen |
| H5 | **Dynamische Achsen-Ticks** (Punkte 5+6) | Neue `_HeatmapAxis(pg.AxisItem)` mit `configure(dim, labels)` + überschriebenen `tickValues`/`tickStrings`. `date`: Schrittwahl via `_pick_time_step()` (1s…1J) → je Zoom-Level Tage → Stunden → Minuten (TradingView-Stil); Formatierung nach Spacing (`TT.MM.JJ` / `TT.MM. HH:MM` / `HH:MM`). `hour`/`dow`/`dow_hour`: ganzzahlige Schritte (`_nice_int_step`) → mehr Zwischenwerte beim Zoom. Kategorial: Labels aus Payload |
| H6 | **Zoom für alle Maßstäbe** (Punkt 6) | `_ZOOMABLE_DIMS` (nur `date`) entfernt – Zoom-Slider X/Y sind immer aktiv und wirken auf alle Dimensionen. `_apply_x_range`/`_apply_y_range` rechnen mit natürlichen `_x_min/_x_max`-Bounds statt Zell-Indizes |
| H7 | **WAL-Guard** (Start-Abbruch, Zusatz) | `DbPool._open_with_wal_recovery()`: bei `duckdb.InternalException` mit "Failure while replaying WAL" wird die korrupte WAL unter `*.duckdb.wal.corrupt_<Zeitstempel>` weggesichert und der Connect erneut versucht (wiederkehrendes Start-Problem unter Windows nach hartem Beenden). `.gitignore` um `*.duckdb.wal.corrupt_*` erweitert |

### Bewusst NICHT geändert
- `fetch_ohlcv_snapshot()` / `QUERY_OHLCV` (Alt-Aufrufer/Tests)
- `HeatmapPage`-Standard-Modus (Dow×Stunde) unangetastet
- `docs/x_Exports.md` (nicht committet)

### Validierung (headless, keine UI-Tests)
- `py_compile` auf allen 8 geänderten Dateien: PASS
- `test/check_heatmap_bugfix.py`: **34/34 PASS** (Reader x_axis/y_axis inkl. Mitternachts-Epochs + Tagesabständen, `fetch_daily_ohlc` mit Wanduhr-Mitternacht + OHLC-Konsistenz, `limit=None` → alle Daten/2083 Tage, Worker-Dispatch `QUERY_DAILY_OHLC`, Axis-Ticks date 100T/3h/90s → 1T/1h/30s + Format TT.MM.JJ/HH:MM, hour/dow_hour/kategorial-Ticks, Widget-Offscreen: Overlay im selben Canvas, X-Bounds = Epochs ± halber Tag, Y-Bounds = −0,5..1,5, Cleanup)
- `test/test.py` Blöcke 37/38: alle PASS (nur 6 bekannte offscreen-Geometrie-Fehler P2/P5/H3–H5/H7, unabhängig von dieser Umsetzung)
- Manueller Funktionstest der GUI erfolgt durch den Anwender.

---

## 5.9 Bugfix-Log 09.08.2026: User-Meldungen 1–3 (Skalen-Begrenzung + Feld-Dropdown)

**Kontext:** Drei User-Meldungen nach Umsetzung von Kapitel 20.02.01 (E1–E8).
Commit: `86f0527`. Alle Fixes sind point-fix/additiv – bestehende Strukturen
(Standard-Modus `HeatmapPage`, `fetch_ohlcv_snapshot`/`QUERY_OHLCV`) blieben
unangetastet.

| # | Symptom | Ursache | Fix |
|---|---------|---------|-----|
| M1 | Tageszeit-Skala nicht begrenzt: beim Rauszoomen erscheinen -/+ Werte außerhalb 00:00–23:59 | `_HeatmapAxis.tickValues` erzeugte Ticks über den GESAMTEN sichtbaren Bereich (auch außerhalb der festen Skala); `_format("hour")` nutzte `% 24` → z. B. -1 wurde als "23:00" angezeigt | `_clamped_scale_bounds()`: Tick-Bereich auf `[0, 24)` geclampt; rechtes Skalenende halboffene Grenze (kein Duplikat-Label "00:00" an Position 24); `_format` lässt Werte außerhalb der Skala leer (kein `% 24`-Wrap mehr) |
| M2 | Wochentag-Skala nicht begrenzt: -/+ Werte außerhalb Mo–Fr | wie M1 für `dow` (feste Skala `[1, 6)`) | gleiches Clamping; `dow._format` außerhalb 1..5 → "" |
| M3a | "Feld"-Dropdown zu kurz | `setMinimumWidth(140)` | `setMinimumWidth(320)` + `setMaximumWidth(460)` + `AdjustToContents` (Popup zeigt vollen '{Service} / {Key}'-Text statt Ellipsis) |
| M3b | Feld-Dropdown zeigt nur JSON-Keys ohne Service-Zuordnung | `metrics`-Liste (Repository) enthielt nur die Keys; keine Key→Service-Zuordnung | Reader `feature_keys_by_service()` (Key→Services je feature_id, numerisch, Typ-Logik wie `available_feature_keys`); Repository `field_sources` (`{Key: [service_id...]}`) im generischen Payload (leere Legacy-`feature_id` ignoriert); Widget `_field_label()` → `'{Kategorie} / {Name} / {Key}'` via `resolve_service_label` (`srv_`-Prefix entfällt); Combo-`data` bleibt der Roh-Key (Query-Vertrag unverändert) |

**Validierung (headless, keine UI-Tests):**
- `py_compile` auf allen 4 geänderten Dateien: PASS.
- `test/check_heatmap_bugfix.py`: **59/59 PASS** – DB-Tests auf **synthetische
  DuckDBs in `test/`** umgestellt (`tmp_hm_*.duckdb`), da die echten
  `data/*.duckdb` bei laufender App exklusiv gesperrt sind (Windows-Lock).
  Neue Checks: Meldung 1 (hour-Ticks in `[0, 24)` bei Rauszoom, kein
  24er-Duplikat, `_format(-1/24)` leer, Teilbereich unverändert), Meldung 2
  (dow-Ticks in `[1, 6)`, `_format(0/6)` leer), Meldung 3 (Combo ≥ 320 px,
  `feature_keys_by_service`, `field_sources` inkl. geteiltem Key → beide
  Services, `_field_label` ohne `srv_`, Combo-Text `'{Name} / {Key}'`,
  Combo-DATA = Roh-Key).
- `test/test.py`: unverändert (kein Kontakt zu dieser Umsetzung; 6 bekannte
  offscreen-Geometrie-Fehler P2/P5/H3–H5/H7 unabhängig).
- Manueller Funktionstest der GUI erfolgt durch den Anwender.

---

## 5.10 Bugfix-Log 09.08.2026: Datums-Skala LWC-v5 (Meldung 2) + Feld-Dropdown ohne Kategorie-Pfad (Meldung 3c)

**Kontext:** Drei neue User-Meldungen nach Commit `86f0527` (20.02.01 E1–E8).
Commit: nach manueller Freigabe. Alle Fixes sind point-fix/additiv –
bestehende Strukturen blieben unangetastet.

| # | Symptom | Ursache | Fix |
|---|---------|---------|-----|
| M2a | Zoom-In: Datums-Beschriftungen überlagern sich | Die date-Achse nutzte `_pick_time_step`/`_time_ticks` (feste Schrittliste) – bei engen Zooms wurden zu viele Labels gezeichnet (kein Mindestabstand) | **LWC-v5-adaptierte Tick-Selektion** (`_lwc_date_ticks`/`_date_marks`/`_select_date_marks`): Mindestabstand `_DATE_TARGET_PX = 80 px` (LWC-Formel `5*(fontSize+4)/8 * (tickMarkMaxCharacterLength||8)` bei fontSize 12). pyqtgraph übergibt an `tickValues` die **Achsen-Länge in Pixeln** (3. Param) → `min_gap_sec = 80 * span / axis_px`. Gewichtete Auswahl (LWC `Q_`): 70 Jahreswechsel → 60 Monatswechsel → 55 Wochenanfang Mo → 50 Tag → 30 Stunde → 20 Minute; feinere Marken nur, wenn ≥ min_gap von den gewählten entfernt |
| M2b | Zoom-Out: Datums-Beschriftungen stehen zu weit auseinander | wie M2a (Schrittliste griff nicht bei groben Zooms) | gleiche LWC-Selektion: Zoom-Out → automatisch gröbere Variante (Jahr/Monat/Woche/Tag statt Stunden/Minuten), keine Riesensprünge |
| M2c | Datums-Formate nicht wie gewünscht (Jahre '2026', Monate 'Jan 26', Wochen '08.25', Tage 'Mo. 07.08.25', Stunden '14:00', Minuten '14:23') | `_format` entschied **nach Spacing** (5 Stufen E1) | `_format` entscheidet jetzt **per Tick** anhand der LWC-Weight-Hierarchie: 1.1. → `'2026'` (Weight 70), 1. des Monats → `'Feb 26'` (60), Montag → ISO-Woche `'08.25'` (55), sonstiger Tag → `'Mo. 07.08.25'` (50, DOW_LABELS locale-unabhängig), volle Stunde → `'14:00'` (30), Minute → `'14:23'` (20). Wanduhr-Garantie via UTC-Darstellung (kein Berlin-Offset). Monatsnamen `_MONTHS_SHORT` (Jan…Dez) |
| M3c | Feld-Dropdown zeigt Kategorie-Pfad '{Kategorie} / {Name} / {Key}' (z. B. 'Grid / Grid Lines / open') | `_field_label` nutzte `resolve_service_label` (E8-Resolver mit Kategorie-Pfad) | Neuer ViewModel-Resolver `resolve_service_display_name(plugin_id)` (nur `display_name`, `srv_`-Prefix entfällt, **ohne** Kategorie-Pfad) → `_field_label` liefert `'{Name} / {Key}'` (z. B. 'Grid Lines / open'). Die **E8-Achsen-Labels** der service_id-Dimension behalten weiterhin `{Kategorie} / {Name}` (`resolve_service_label` unverändert) |

**Betroffene Dateien:**
- `analytics/ui/heatmap_widget.py` – LWC-Datums-Skala (`_DATE_TARGET_PX`,
  `_MONTHS_SHORT`, `_lwc_date_ticks`, `_date_marks`, `_select_date_marks`,
  Per-Tick-`_format`), `_field_label` → `resolve_service_display_name`
- `analytics/engine/analytics_view_model.py` – neuer Resolver
  `resolve_service_display_name()` (lazy `_selector_model`, Muster
  `resolve_service_label`)

**Validierung (headless, keine UI-Tests):**
- `py_compile` auf beiden geänderten Python-Dateien: PASS.
- `test/check_heatmap_bugfix.py`: **alle PASS** – alte Spacing-Format-Checks
  durch Per-Tick-Formate ersetzt (Jahr/Monat/ISO-Woche/Tag/Stunde/Minute),
  neue LWC-Selektions-Checks: Jahres-Zoom → min_gap 36,5 d + nur Tagesmarken
  (7 Ticks), 2-Tage-Zoom → min_gap 4,8 h + Stunden-Ticks, 3h-Zoom →
  Minuten-Ticks, Zoom-In (mehr Pixel) → mehr Ticks (5→17), Zoom-Out
  (größere Spanne) → weniger Ticks (9→7), alle Tick-Abstände ≥ min_gap
  (keine Überlappung), `_select_date_marks` bevorzugt Jahres-/Monatsmarken;
  Meldung 3c: `_field_label` = 'Grid Lines / open' (ohne Kategorie),
  `resolve_service_display_name` = 'Grid Lines'/'Proximity',
  E8-`resolve_service_label` = 'Grid / Grid Lines' (Kategorie bleibt),
  Feld-Combo-Text ohne 'Grid / '-Pfad, Combo-DATA = Roh-Key.
- Manueller Funktionstest der GUI erfolgt durch den Anwender.

