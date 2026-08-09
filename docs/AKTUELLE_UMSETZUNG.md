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