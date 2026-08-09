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

