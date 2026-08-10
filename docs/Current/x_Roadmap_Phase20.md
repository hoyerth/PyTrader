# Phase 20: Speichermodel & Heatmap

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 20)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase20_step1`, `phase20_step2` usw.).
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

# Phase 20.01: Analytics UI Dual-Layer, Workspace-Restore & Fault-Tolerant Resolver

## 1. Architektur-Regeln
* **Code-Style:** Exakt 4 Leerzeichen Einrückung, 1 Leerzeile zwischen Methoden.
* **Testing:** Headless via `py_compile` & `test/test.py` (UI-Exec STRIKT VERBOTEN).
* **Entkopplung:** MVVM & IoC. Kein SQL in UI, ViewModel/Repository-Brücke nutzen.

---

## 2. DB-Schicht & Repositories

### `window_state_repository.py` & `state_manager.py`
- Additive Spalte `workspace_state JSON` in `instance_states` (`ALTER TABLE IF NOT EXISTS`).
- `save_workspace_state(instance_id: str, state: dict)` -> Upsert `workspace_state`.
- `get_workspace_state(instance_id: str) -> Optional[dict]` -> Liest `workspace_state`.

### `analytics_profile_repository.py`
- `SCHEMA_VERSION_DEFAULT = 2`.
- In `_row_to_profile()`: Wenn Payload `schema_version == 1`, nutze `_migrate_v1_to_v2(payload)`.

---

## 3. Core-Logik & ViewModel

### `analytics/engine/service_selector_model.py`
- Methode `resolve_valid_feature_ids(feature_ids: List[str]) -> Tuple[List[str], List[str]]`:
  - Prüft `feature_ids` gegen `PluginRegistry`.
  - Returns `(valid_ids, missing_ids)`.

### `analytics/engine/analytics_view_model.py`
- Additiv Signal: `missing_services_detected = Signal(list)`.
- Methode `_migrate_v1_to_v2(payload: dict) -> dict`:
  - Wandelt altes flaches Dict verlustfrei in Sections (`sources`, `table`, `charts`, `styling`).
- In `_apply_profile()`:
  1. `_migrate_v1_to_v2()` ausführen.
  2. `resolve_valid_feature_ids()` rufen.
  3. `set_feature_ids(valid_ids)` setzen.
  4. `missing_services_detected.emit(missing_ids)` feuern.

---

## 4. UI-Integration (`analytics/ui/analytics_win.py`)

### Workspace-Persistence
- Klasse behält `_keep_history_on_close = True`.
- `_save_workspace()`: Liest `vm.params` + UI-Layout, ruft `state_manager.save_workspace_state("win_analytics", payload)`.
- `_restore_workspace()`: Liest `state_manager.get_workspace_state("win_analytics")` beim Start & wendet Parameter an.
- `closeEvent(event)`: Ruft `_save_workspace()` auf, dann `super().closeEvent(event)`.

### Graceful Degradation / Feedback
- UI verbindet `vm.missing_services_detected` -> `_on_missing_services(missing)`.
- `label_missing_warning`: Zeigt `⚠️ X Services nicht mehr verfügbar` (setVisible=True).
- Bei manueller Datenquellen-Änderung oder `save_profile()` -> Warn-Label auf `setVisible(False)`.

---

## 5. Verification Checklist (`test/test.py`)
- [ ] DB: `workspace_state` Spalten-Anlage idempotent.
- [ ] Schema: Payload-Migration v1 -> v2 verlustfrei.
- [ ] Resolver: Fehlende IDs werden isoliert gefiltert, bestehende geladen.
- [ ] Workspace: `save_workspace_state` / `get_workspace_state` Roundtrip erfolgreich.

---

## 6. Review & Entscheidungen (09.08.2026, vor Implementierung)

> **Zweck dieses Kapitels:** Konsistenzprüfung des Phase-20.01-Plans gegen den Ist-Code,
> Entscheidungen (E1–E7) und die daraus resultierenden Plan-Anpassungen. Es gilt als
> verbindliche Ergänzung/Präzisierung der Kapitel 1–5 – **keine Bestandsstruktur wurde
> überschrieben** (ausschließlich additiv).

### 6.1 Konsistenz- & Vollständigkeitsprüfung (Plan vs. Ist-Code)

**A) Noch nicht implementiert – Plan-Ziele sind gültig und additiv anzulegen:**
- `workspace_state`-Spalte: existiert nirgends (geprüft: `state_manager._init_db()`,
  `db/schema_initializer.py`, `window_state_repository.py`). → neu.
- `save_workspace_state` / `get_workspace_state`: nicht vorhanden. → neu.
- `resolve_valid_feature_ids()`: fehlt in `analytics/engine/service_selector_model.py`. → neu.
- Signal `missing_services_detected`: fehlt in `analytics/engine/analytics_view_model.py`. → neu.
- `label_missing_warning` / `_on_missing_services`: fehlen in `analytics/ui/analytics_win.py`. → neu.
- `_save_workspace` / `_restore_workspace`: fehlen. → neu.

**B) Inkonsistenzen & Lücken (geprüft gegen Ist-Code):**

- **B1 – `_keep_history_on_close`-Widerspruch (kritisch):** Plan sagt „Klasse behält
  `_keep_history_on_close = True`“. Ist-Code: `persistent_win.py` deklariert den
  Klassen-Default `False`; `AnalyticsWindow` setzt KEIN eigenes Klassen-Attribut; der
  Klassen-Kommentar (Bugfix 04.08.2026) hält EXPLIZIT an `False` fest (Semantik wie
  `chart_win`). **Kritische Wechselwirkung:** `PersistentWindow.closeEvent()` ruft bei
  `False` + manuellem Schließen `delete_instance()` → löscht die `instance_states`-Zeile
  inkl. der dort geplanten `workspace_state`-Spalte → Workspace-Restore wäre unmöglich.
  → **E1.**
- **B2 – Migrations-Duplikation:** Der Plan verlangt `_migrate_v1_to_v2` sowohl in
  `_row_to_profile()` (Repo) als auch als ViewModel-Methode → doppelte
  Implementierung/DRY-Verletzung. → **E2.**
- **B3 – `SCHEMA_VERSION_DEFAULT = 2` unvollständig:** `_current_payload()`
  (analytics_view_model.py) und `_ensure_schema_version()` (Repo) schreiben heute das
  FLACHE v1-Format. Ohne Anpassung entstünden neue Profile mit `schema_version: 2` bei
  v1-Struktur → inkonsistente Rows. → **E3/E4.**
- **B4 – `set_feature_ids()` in `_apply_profile()`:** würde Dirty-Flag setzen UND einen
  zusätzlichen Refresh triggern (danach folgt ohnehin `refresh_all()`) → Doppel-Refresh +
  fälschliches `*`-Flag beim Profilwechsel. → **E5.**
- **B5 – Registry-Zugriff im ViewModel fehlt:** `_apply_profile()` (VM) hat keinen Zugriff
  auf `ServiceSelectorModel`/`PluginRegistry`; der Plan spezifiziert keine Injektion. → **E5.**
- **B6 – Bestehende Tests brechen:** `test/test.py` Teil 33 (R2a: flacher Payload-Zugriff,
  R2b: `schema_version == 1`) und Teil 35 (Z1e: `table_row_height` im flachen Payload)
  müssen auf das v2-Sectioned-Schema umgestellt werden – in der Plan-Checklist nicht
  enthalten. → **E7.**
- **B7 – `native`-Sentinel:** Der `feature_store` enthält native Rows
  (`feature_id='native'`, Grid-Levels). `'native'` ist KEIN Plugin; ein reiner
  Registry-Resolver markiert es als „missing“. Der `ServiceSelectorDialog` emittiert
  ausschließlich `plugin_ids` (nie `'native'`) → Filterung ist korrekt und gewollt
  (Graceful Degradation). Kein Handlungsbedarf, Verhalten wird dokumentiert. → **E5.**
- **B8 – NOT-NULL-Zwang von `instance_states`:** `symbol`/`timeframe` sind `NOT NULL`.
  Ein reiner `workspace_state`-Column-Upsert schlägt fehl, wenn noch keine Row existiert
  (Reihenfolge im `closeEvent`: `_save_workspace()` VOR `super().closeEvent()`).
  → **E6.**

**C) Zukunftssicherheit (positiv bestätigt):**
- Registry-basierter Resolver: neue Plugins automatisch gültig; entfernte Plugins →
  Warnhinweis statt stiller Fehlfilter.
- Sectioned-v2-Payload: neue UI-Settings lassen sich unter neuen Sektionen ergänzen,
  ohne einen Schema-Bump zu erzwingen.
- Workspace-Mechanismus generisch über `instance_id` (`save_workspace_state(instance_id,
  state)`) → später auf beliebige Fenster übertragbar (z. B. `win_service`).

### 6.2 Entscheidungen

- **E1 – `_keep_history_on_close = True` explizit setzen (Plan-Stand, B1):**
  `AnalyticsWindow` deklariert `_keep_history_on_close = True` als Klassen-Attribut; der
  widersprüchliche Kommentar (Bugfix 04.08.2026) wird angepasst. Begründung: Nur so
  überlebt `workspace_state` in `instance_states` das manuelle Schließen. Trade-off
  (bewusst akzeptiert): ein manuell geschlossenes Analytics-Fenster wird beim nächsten
  App-Start wiederhergestellt (`auto_restore=True` ist bereits gesetzt) – Analytics ist
  ein Dashboard-Fenster, kein Wegwerf-Fenster.
- **E2 – Migration ausschließlich im Repository (Single Source of Truth, B2):**
  `AnalyticsProfileRepository._migrate_v1_to_v2(payload) -> dict` (statisch) – aufgerufen
  in `_row_to_profile()` (Lese-Seite) und in `_ensure_schema_version()` (Schreib-Seite).
  Das ViewModel erhält IMMER bereits migrierte v2-Payloads und bekommt KEINE eigene
  `_migrate_v1_to_v2`-Methode (Plan-Präzisierung). `_apply_profile()` flacht v2-Sections
  verlustfrei auf `_params` ab; der vorhandene `feature_id`→`feature_ids`-Shim bleibt als
  defensiver Fallback erhalten.
- **E3 – v2-Payload-Schema (sectioned, verlustfrei, B3):**
  ```
  schema_version: 2
  sources:  symbol, timeframe, feature_ids
  charts:   heatmap_metric, scatter_x, scatter_y, distribution_column, bins
  table:    limit, table_column_widths, table_row_height, table_sort_column, table_sort_order
  styling:  {}  (Reserve für zukünftige visuelle Settings)
  ```
  Unbekannte/extra v1-Keys bleiben auf Top-Level erhalten (verlustfrei). `_current_payload()`
  baut die Sektionen aus `_params`; `_apply_profile()` liest Sektionen + Top-Level-Reste
  (bekannte Keys werden gemergt, unbekannte ignoriert).
- **E4 – Schreib-Seite migriert ebenfalls (B3):** `_ensure_schema_version()` führt bei
  `create_profile`/`update_profile` mit v1-Flat-Payload vor dem Speichern
  `_migrate_v1_to_v2()` aus → keine neuen v1-Rows.
- **E5 – Resolver + Injektion (B4/B5/B7):**
  - `ServiceSelectorModel.resolve_valid_feature_ids(feature_ids) -> (valid, missing)`
    nutzt `get_plugin()` (case-insensitiv); `'native'` gilt als fehlend (B7).
  - `AnalyticsViewModel.__init__` erhält `selector_model: Optional[ServiceSelectorModel] =
    None` (lazy Default `ServiceSelectorModel(parent=self)`).
  - In `_apply_profile()` nach Migration/Flatten: `valid, missing =
    resolve_valid_feature_ids(...)`; die validen IDs werden DIREKT in
    `self._params["feature_ids"]` geschrieben (kein `set_feature_ids` → kein Dirty, kein
    Doppel-Refresh, B4); `missing_services_detected.emit(missing)` feuern. Der
    abschließende `refresh_all()` bleibt unverändert.
- **E6 – `save_workspace_state` NOT-NULL-konform (B8):** Signatur
  `save_workspace_state(instance_id: str, state: dict) -> None` (wie geplant); die
  Implementierung im `WindowStateRepository` liest zuerst bestehende `symbol`/`timeframe`
  der Row (Fallback `''`/`'M1'`) und schreibt per
  `INSERT ... ON CONFLICT (instance_id) DO UPDATE SET workspace_state = ...,
  updated_at = ...`. `StateManager` delegiert als Fassade (Muster 15.04).
  Workspace-Payload: `{"params": vm.params, "layout": {"page_index":
  sidebar.currentRow()}}`.
- **E7 – Workspace-Anwendung über ViewModel + Test-Anpassungen (B6):** Die UI
  (`_restore_workspace`) liest nur `get_workspace_state(...)`; das ANWENDEN läuft über
  eine neue VM-Methode `vm.restore_workspace(payload)` (params + `layout.page_index`,
  kein Dirty, gleicher Resolver-Pfad wie E5, Emit von `missing_services_detected`).
  Reihenfolge im `_initial_load()`: `restore_state()` (Historie, t=0) → `load_profiles()`
  (aktives Profil) → `restore_workspace()` (letzter Sitzungszustand gewinnt).

### 6.3 Angepasste Verification Checklist (`test/test.py`, neue Teil 36)

- [ ] Bestandstests umgestellt: Teil 33 R2a/R2b (Sections + `schema_version == 2`),
      Teil 35 Z1e (`payload["table"]["table_row_height"]`).
- [ ] DB: `workspace_state`-Spalte idempotent (ALTER) auf Temp-DB in `test/`.
- [ ] Roundtrip `save_workspace_state`/`get_workspace_state` – auch ohne vorherige
      `instance_states`-Row (NOT-NULL-Fallback E6).
- [ ] Schema: v1→v2 verlustfrei (Sektionen + unbekannte Top-Level-Keys erhalten).
- [ ] `_ensure_schema_version` migriert v1-Flat-Payloads beim Schreiben (E4).
- [ ] Resolver: gültige/fehlende IDs isoliert; `'native'` → missing (E5/B7).
- [ ] `_apply_profile`: v2-Payload → flache `_params`, KEIN Dirty-Flag, KEIN Doppel-Refresh.
- [ ] `restore_workspace`: params + page_index angewendet, kein Dirty (E7).
- [ ] Klassen-Check: `AnalyticsWindow._keep_history_on_close is True` (E1, statisch).

### 6.4 Umsetzungs-Log (09.08.2026, 20.01)

> **Status: vollständig umgesetzt & headless validiert** (Teil 36 = 25/25 PASS;
> betroffene Bestandstests Teil 33 R2a/R2b + Teil 35 Z1e auf v2-Schema umgestellt).

**Implementiert (additiv, kein Bestandscode überschrieben):**

- `state_manager.py`:
  - `instance_states` um Spalte `workspace_state JSON` erweitert (CREATE + idempotentes
    `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
  - Fassaden-Methoden `save_workspace_state(instance_id, state)` und
    `get_workspace_state(instance_id)` (Delegation an das WindowStateRepository,
    Muster 15.04).
- `window_state_repository.py`:
  - `save_workspace_state()` (E6, NOT-NULL-konform: liest bestehende
    symbol/timeframe der Row, Fallback `''`/`'M1'`; ON CONFLICT aktualisiert nur
    `workspace_state` + `updated_at`).
  - `get_workspace_state()` -> Optional[dict] (JSON geparst).
- `analytics_profile_repository.py`:
  - `SCHEMA_VERSION_DEFAULT = 2`; Sektions-Schema v2 (sources/charts/table/styling, E3).
  - `_migrate_v1_to_v2(payload)` (statisch, verlustfrei: bekannte Keys in Sektionen,
    `feature_id` -> `feature_ids`, unbekannte Top-Level-Keys bleiben erhalten).
  - `_row_to_profile()` migriert beim Lesen (E2, Single Source of Truth im Repo);
    `_ensure_schema_version()` migriert beim Schreiben (E4) -> keine neuen v1-Rows.
- `analytics/engine/service_selector_model.py`:
  - `resolve_valid_feature_ids(feature_ids) -> (valid, missing)` (E5, case-insensitiv,
    dedupliziert; `'native'`-Sentinel gilt als missing, B7).
- `analytics/engine/analytics_view_model.py`:
  - Additives Signal `missing_services_detected = Signal(list)`.
  - `selector_model`-Injektion (lazy Default); `_resolve_feature_ids()` / `_flatten_payload()`.
  - `_apply_profile()`: flacht v2-Sections verlustfrei, Resolver isoliert fehlende
    Services, Direkt-Write in `_params` (kein `set_feature_ids` -> kein Dirty, kein
    Doppel-Refresh, B4), Emit `missing_services_detected`.
  - `_current_payload()` baut das v2-Sectioned-Payload (E3).
  - `restore_workspace(payload)` (E7: params + layout, kein Dirty, Resolver-Pfad,
    refresh_all) + Property `workspace_layout`.
- `analytics/ui/analytics_win.py`:
  - `_keep_history_on_close = True` (E1, Dashboard-Fenster-Semantik; Kommentar des
    Bugfix 04.08.2026 angepasst).
  - Selector-Modell wird VOR dem VM erzeugt und injiziert (E5).
  - `label_missing_warning` + `_on_missing_services()` (Graceful Degradation); wird bei
    manueller Datenquellen-Aenderung und `save_profile()` versteckt.
  - `_save_workspace()` / `_restore_workspace()` (Payload `{"params", "layout"}`);
    `closeEvent()` ruft `_save_workspace()`; `_initial_load()` ruft nach `load_profiles()`
    `_restore_workspace()` (E7-Reihenfolge: Historie -> Profil -> Workspace).

**Validierung (headless, `test/test.py`):**
- Neuer Teil 36: W1a/b Spalte idempotent, W2a-e Roundtrip + NOT-NULL-Fallback,
  W3a-e v1->v2 verlustfrei, W4a Schreib-Migration, W5a-c Resolver (inkl. `native`),
  W6a-e `_apply_profile` (kein Dirty/Doppel-Refresh, Emit), W7a-e `restore_workspace`,
  W8 Klassen-Check E1 – **25/25 PASS**.
- Bestandstests angepasst: Teil 33 R2a/R2b (v2-Section `table`, `schema_version == 2`),
  Teil 35 Z1e (`payload["table"]["table_row_height"]`) – PASS.
- H8 (Teil 3) auf E1-Semantik umgestellt (`keep_history=True`) – PASS.
- `py_compile` auf allen geänderten Dateien OK.

**Bekannte, VORBESTEHENDE und unabhängige Test-Fehlschläge (nicht durch 20.01 verursacht,
 bewusst unangetastet):** P2/P5/H7 (Offscreen-Screen 800×800, Test verlangt Breite
 >= 1000/1300), H3/H4/H5 (veraltete Tests erwarten `ServiceWindow._keep_history_on_close
 == True`; Code hat unverändert `False`).


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

---

## 5.11 Bugfix-Log 09.08.2026: Feld-Dropdown (Service-Name direkt) + Zoom-Richtung + feature_ids-Filter + Achsen-Label 'Datum/Zeit'

**Kontext:** Vier User-Meldungen nach Commit `cedaa27` (20.02.01 E1–E8 /
5.10). Alle Fixes sind point-fix/additiv – bestehende Strukturen
(Standard-Modus `HeatmapPage`, LWC-Datums-Skala, E8-Achsen-Labels)
blieben unangetastet.

| # | Symptom | Ursache | Fix |
|---|---------|---------|-----|
| F1 | Feld-Dropdown zeigt Service-Namen mit unzuverlässigem `metadata['display_name']` (z. B. 'Swing Momentum Service' mit 'Service'-Suffix) | `_field_label` nutzte `resolve_service_label` (Kategorie-Pfad) bzw. `metadata['display_name']` | Neuer ViewModel-Resolver **`resolve_service_display_name(plugin_id)`** (Name DIREKT aus dem Service-Objekt/`plugin_id`: `srv_`-Prefix weg, `_`→Leerzeichen, Title-Case → 'Swing Momentum'; unbekannt → Pretty-Fallback 'Unbekannter Service', 'native' → 'Native', leer → 'Allgemein') → `_field_label` liefert `'{Name} / {Key}'` (z. B. 'Grid Lines / open') |
| F2 | Geteilter Key mehrerer Services (z. B. 'price' von Swing-Services) zeigte irreführende 'Pfad'-Kette ('Swing Momentum Service / Swing Volume Profile Service / price') | `_field_label` verketterte alle Service-Namen bei mehreren `service_ids` | Liefern MEHRERE Services denselben Key → Prefix entfällt KOMPLETT (nur Roh-Key 'price'). EIN Service → `'{Name} / {Key}'`. Unbekannt → Roh-Key (defensiv) |
| Z1 | Zoom-Slider-Richtung war vertauscht (rechts = Zoom-Out) | `_set_zoom_range`: `f = value / 100` (100 = volle Achse) | Richtung getauscht – **rechts = Zoom-In, links = Zoom-Out**: `_set_zoom_range` `f = (105 - value) / 100` (5 → volle Achse, 100 → max. Vergrößerung zentriert 0.5); `_set_zoom_slider` inverse Umrechnung `105 - span*100`; Initialwert 5 statt 100; Tooltip aktualisiert |
| F3 | Abgewählte Services (z. B. Grid deaktiviert) erschienen weiterhin im Feld-Dropdown (Root Cause 2) | `feature_keys_by_service`/`field_sources`/`metrics` ignorierten die selektierten `feature_ids` | Reader `feature_keys_by_service()` neue Parameter `feature_id`/`feature_ids` + `_apply_feature_filter`; Repository `get_generic_heatmap()` übergibt Filter und begrenzt `metrics`/`field_sources` auf selektierte Services (`avail_filtered`, Fallback ungefiltert bei leer) – Dropdown reagiert über die bestehende Kette (set_feature_ids → Refresh → `_sync_combos_from_payload`) |
| D1 | Datums-Achse zeigte 'Datum (EXP)' bzw. 'Datum (x1e+09)' als Beschriftung | pyqtgraph `setLabel(text)` mit `units=None` → leere Einheit → Default-SI-Ranges `((0.,1.), (1e9, inf))`; die date-Epochs (~1.7e9) fallen in (1e9, inf) → `autoSIPrefixScale = 1e-9` → Suffix `(x1e+09)` angehängt. Die Ticks werden ohnehin von `tickStrings` formatiert (Scale ignoriert) – das Suffix war irreführend | `_HeatmapAxis.__init__`: **`enableAutoSIPrefix(False)`** (unterdrückt das EXP-Suffix für X- und Y-Achse); Label der date-Achse jetzt **'Datum/Zeit'** (`_render_generic`, X und Y; `_DIM_LABELS`-Dropdown bleibt 'Datum') |

**Betroffene Dateien:**
- `analytics/engine/feature_store_reader.py` – `feature_keys_by_service()`:
  neue `feature_id`/`feature_ids`-Parameter + `_apply_feature_filter`
- `analytics/engine/analytics_repository.py` – `get_generic_heatmap()`:
  feature_ids-Filter für `metrics`/`field_sources` (`avail_filtered`,
  Fallback ungefiltert bei leer)
- `analytics/engine/analytics_view_model.py` – `resolve_service_display_name()`
  (Service-Name direkt aus `plugin_id`, Pretty-Fallbacks)
- `analytics/ui/heatmap_widget.py` – `_field_label` (1 Service → Name;
  mehrere Services → Roh-Key), Zoom-Richtung (`_set_zoom_range`/
  `_set_zoom_slider`/Initialwert/Tooltip), date-Label 'Datum/Zeit' +
  `enableAutoSIPrefix(False)` in `_HeatmapAxis`

**Validierung (headless, keine UI-Tests):**
- `py_compile` auf allen 4 geänderten Python-Dateien: PASS.
- `test/check_heatmap_bugfix.py`: **alle PASS** – `resolve_service_display_name`
  ('Grid Lines'/'Proximity'/'Swing Momentum'/'Swing Volume Profile'/
  Unbekannt→'Unbekannter Service'/'native'→'Native'/leer→'Allgemein'),
  `_field_label` bei geteiltem Key = Roh-Key (kein 'Pfad'), Feld-Combo ohne
  Kategorie-Pfad, Combo-DATA = Roh-Key, feature_keys_by_service gefiltert
  (nur srv_proximity + dessen Keys), `field_sources`/`metrics` gefiltert
  (keine Grid-only-Keys), ohne Filter unverändert (kein Bruch),
  Zoom-Slider 5→[0,1] / 100→[0.475,0.525] / 55→Mitte, Initialwert 5,
  rechts = Zoom-In (span schrumpft), `_HeatmapAxis.autoSIPrefix` deaktiviert,
  X=date → labelText 'Datum/Zeit' + labelString ohne '(x1e…)/(x…',
  Y=date-Regression ebenfalls 'Datum/Zeit', hour-Achse 'Tageszeit (UTC+X)'
  ohne EXP.
- `test/test.py`: unverändert (kein Kontakt zu dieser Umsetzung).
- Manueller Funktionstest der GUI erfolgt durch den Anwender.


---

# 20.03 Service-Output-Schema & Resultatfelder-Dokumentation im Service-Picker

## 1. Architektur & Standards (E1, E4, E5)
- **Modul-Konstante & Property (E1)**: Definition als private Modul-Konstante (z. B. `_GRID_OUTPUT_SCHEMA`) am Dateianfang des Plugins. Export über Property `@property def output_schema(self) -> Dict[str, Dict[str, Any]]: return {k: dict(v) for k, v in _GRID_OUTPUT_SCHEMA.items()}`.
- **Basisklasse (`base_plugin.py`)**: `@property def output_schema(self) -> Dict[str, Dict[str, Any]]: return {}` als abwärtskompatibler Default.
- **JSON-Scope (E4)**: `bar_time` NICHT im `output_schema` deklarieren (ist native DB-Spalte, kein JSON-Key).
- **Typen (E5)**: Freie String-Typen unterstützen (z. B. `"bool"`, `"float"`, `"list[float]"`).

## 2. Abdeckung Core-Plugins (E6)
Befüllung der Modul-Konstante `_*_OUTPUT_SCHEMA` in allen 8 aktiven Services unter `analytics/features/definitions/`:
- `srv_grid_lines.py`, `srv_proximity.py`, `srv_swing_structure.py`, `srv_swing_momentum.py`, `srv_swing_volume_profile.py`, `srv_trend_breakout.py`, `srv_trend_hma_pivot.py`, `srv_trend_regime.py`.

## 3. UI-Anzeige im Parameter-Panel (E2, E7) (`serviceui/param_columns.py`)
- **Verortung (E7)**: Integration in `_update_service_info_label` / `_build_service_column` unterhalb der allgemeinen Beschreibung.
- **Gruppierung/Filter (E2)**:
  - **Haupt-Resultatfelder**: Standardmäßig eingerückt anzeigen (`└── 🔹 {field_name} ({type}): {description}`).
  - **Technische Felder** (mit `"technical": True` im Schema, z. B. `calculation_status`, `confirmation_lag_bars`): In kompakter, kleinerer Schrift oder ausklappbarem Unterblock `🔧 System-Metrik` platzieren.
- **Read-Only**: Strikte schreibgeschützte Formatierung.

## 4. Implementation Steps
1. **Base-Plugin (`analytics/features/plugins/base_plugin.py`)**: Add `@property def output_schema`.
2. **Plugins (`analytics/features/definitions/srv_*.py`)**: Define `_*_OUTPUT_SCHEMA` & property across all 8 plugins.
3. **UI (`serviceui/param_columns.py`)**: Render `output_schema` indented below description text field.
4. **Validation (`test/test.py`)**: Headless Test verifying `output_schema` retrieval for all registered plugins + `py_compile`.


---

# 20.03.01 Bugfix: Output-Schema-Sektion + Info-Button im Tree (09.08.2026, 18:20)

## 1. Ausgangslage (User-Meldungen)
1. **Ergebnisparameter gehören NICHT ins Beschreibungsfeld** – die 20.03-Resultatfelder
   wurden zunächst im Read-only-Info-Label unter dem individuellen Beschreibungsfeld
   gerendert; gewünscht ist eine eigene Sektion.
2. **Erste Zeile im allgemeinen Beschreibungsfeld nicht mehr sichtbar** – das lange
   Output-HTML im Info-Label verstärkte den Qt-Quirk (`setHtml` setzt den Cursor ans
   Dokument-Ende, Qt wrappt später um → Scroll nach unten). Alt-Fix 17.01.06
   (`_scroll_textedit_top`, synchron + deferred + nach Box-Resize) ist intakt.
3. **i-Button im Tree geht nicht mehr** – `INFO_BUTTON_TEXT = "ℹ"` (U+2139) rendert
   unter Windows-Qt bei fehlendem Font als Tofu-Box → Button unsichtbar
   (vgl. Alt-Bugfix 04.08.2026 Punkt 5: Unicode-Badge `🛈` → ASCII `'i'`).
4. **Vorgabe (User)**: Je Ergebnisparameter Name + i-Button daneben, der die
   Beschreibung in einem Fenster zeigt.

## 2. Umsetzung (Commit `1f40783`, Tag `20.03_bugfix`)
- **`serviceui/param_columns.py`**:
  - Output-Schema-Block aus `_update_service_info_label` entfernt (Punkt 1).
  - Neue Sektion **UNTER** dem Info-Label in `_build_service_column`: Header
    `📊 Resultatfelder (Output-Schema):`, je Haupt-Resultatfeld eine Zeile
    (`🔹 name (type)`) mit 16-px-`i`-Button → `_show_output_field_info`
    (modaler `QDialog` mit Name/Typ/Beschreibung/Service-Referenz).
    Technische Felder (`technical: True`) kompakt in dezentem Block
    `🔧 System-Metrik: …` (Semikolon-getrennt, ohne Beschreibung).
  - Neues State-Dict `self._service_output_schemas[iid]` (Reset in
    `_clear_service_columns`); `QDialog`-Import ergänzt.
- **`serviceui/master_tree.py`**: `INFO_BUTTON_TEXT` von `"ℹ"` (U+2139) zurück auf
  ASCII `"i"` (Punkt 3) – inkl. Begründungskommentar.

## 3. Validierung (headless, keine UI)
- `py_compile` auf beiden geänderten Dateien: OK.
- `test/check_output_schema.py`: ALL CHECKS PASSED (8 Services, Main/Tech-Split).
- Neuer Testblock `20.03-Bugfix` in `test/test.py`: `INFO_BUTTON_TEXT` = ASCII `'i'`
  (kein U+2139) + Main/Tech-Split vollständig + alle Tech-Felder tragen eine
  Beschreibung – alle PASS.
- Hinweis: Die 6 bestehenden Fehlschläge (P2/P5/H3–H7, Fenster-Persistenz-Geometrie)
  sind VORBESTEHEND und betreffen nicht die geänderten Codepfade
  (nur `master_tree.py`/`param_columns.py` wurden modifiziert).

## 4. Folge-Bugfixes (09.08.2026, 2. Runde, Commit `f071b10` + `b772c93`)
Zwei User-Meldungen nach dem ersten Commit – beide betrafen den Service-Selector-
Dialog (`service_selector_dialog.py`), dessen `_DialogParamHost` den Mixin nur als
Plain-Object (kein QWidget) hostet:

1. **`f071b10` – 'Parameteranzeige nicht verfügbar: _DialogParamHost object has
   no attribute _service_output_schemas'**:
   - Ursache: Der Dialog ruft `_build_service_column` DIREKT auf (ohne
     `_clear_service_columns`, das das Dict normalerweise anlegt); der Host-
     `__init__` initialisierte alle Mixin-Registrys, aber nicht das seit dem
     Output-Schema-Umbau neue `_service_output_schemas`.
   - Fix: `self._service_output_schemas: Dict[str, Any] = {}` im `__init__` von
     `_DialogParamHost` ergänzt (analog `_mode_schemas`, 08.08.2026).
   - Neuer headless Regressions-Test `test/check_dialog_host.py` (Host-Spaltenbau
     inkl. Resultatfelder-Header/System-Metrik/i-Buttons): PASS.

2. **`b772c93` – 'QDialog.__init__ called with wrong argument types' beim
   i-Button der Ergebnisparameter**:
   - Ursache: `_show_output_field_info` erzeugte `QDialog(self)` – `self` ist im
     Dialog-Kontext der `_DialogParamHost` (kein QWidget) → TypeError.
   - Fix: Eltern-Widget robust aufgelöst: `self` falls QWidget, sonst
     `self._dialog` (echtes Dialog-Fenster des Hosts), sonst `None`.
   - `test/check_dialog_host.py` erweitert (mockt `QDialog.exec`, prüft
     Eltern-Auflösung + None-Fallback): ALL PASS.


---

# 20.03.02 Multi-Select Resultatparameter, Dynamic Checkable ComboBox & Info-Fixes (09.08.2026, 20:15; Entscheidungen F1–F7 bestätigt 20:21)

## 1. Regeln & Invarianten
* **Code-Style:** Exakt **4 Leerzeichen** Einrückung, **1 Leerzeile** zwischen
  Methoden/Funktionen (PEP8, Phase-19-Invariante 3).
* **Testing:** **STRIKT HEADLESS** via `py_compile` & `test/test.py`
  (`QApplication.exec()` STRIKT VERBOTEN – Phase-19-Invariante 2). Alle neuen
  Test-Skripte/Test-DBs gehören nach `test/` (Invariante 10).
* **Entkopplung:** MVVM & IoC (Invariante 4/5). Kein SQL in UI; strikter
  Lese-Pfad über `AnalyticsRepository` / `FeatureStoreReader`.
* **Open/Closed (Invariante 11):** Nur additive Ergänzungen; keine
  Umformatierung unbeteiligter Dateien.

## 2. Problemstellung & Ziel
1. **Dropdown-Fixes (größtenteils VORHANDEN, s. §3):** Strikte Filterung der
   Ergebnisfelder nach im Picker tatsächlich aktivierten `feature_ids`.
2. **Multi-Select & Pop-up (NEU):** `CheckableComboBox` mit offen bleibendem
   Pop-up bei Checkbox-Klick und Anzeige `{Service-Name} / {Parameter}`.
3. **Info-Button UI-Umbau (Neuer Req):** Einzelanzeigen der Resultatparameter
   im ServicePicker entfernen. Stattdessen hinter der Gruppenüberschrift
   *"Resultatfelder"* ein einzelner **(i)-Info-Button**, der bei Klick alle
   Ergebnisparameter der gewählten Service-Instanz kompakt in einem Info-Window
   zeigt.
4. **Wiederherstellung Bugfix 1 (Erste Zeile Beschreibungsfeld):**
   `header_line` in `ServiceDescriptionDialog` / `ServiceDescriptionEditDialog`
   – **ist bereits intakt** (Bestandsaufnahme §3, Punkt 5).
5. **Wiederherstellung Bugfix 2 ((i)-Button im MasterTree):**
   Signalverbindung `info_requested` / `category_info_requested` – im
   ServiceWindow intakt; **Lücke im ServiceSelectorDialog (ServicePicker)**.

## 3. Bestandsaufnahme (Vollständigkeitsprüfung gegen HEAD `5c40272`)

| Schritt | Datei | Status | Befund |
|---|---|---|---|
| 2 | `analytics/engine/feature_store_reader.py` | ✅ VORHANDEN | `feature_keys_by_service()` nimmt `feature_ids` (Z. 430) und wendet `_apply_feature_filter` an (Z. 462). Commit `4648399`. |
| 3 | `analytics/engine/analytics_repository.py` | ✅ VORHANDEN | `get_generic_heatmap()` baut `field_sources` + `avail_filtered` strikt über `feature_ids` (Z. 150–176). Commit `4648399`. |
| 4 | `analytics/engine/analytics_view_model.py` | 🟡 DELTA | Leer/`"none"` → `"Allgemein"`, Title-Case-Fallback ✅. **`"native"` → `"Native"` (Plan: `"Allgemein"`)** – Erweiterung offen (F3). |
| 5 | `analytics/engine/description_dialog.py` | ✅ VORHANDEN | `_render_html()` rendert `header_line` fett + `<p>&nbsp;</p>` (Z. 285–290); `ServiceDescriptionEditDialog` ebenso. |
| 6 | `serviceui/master_tree.py` + `service_selector_widget.py` | 🟡 DELTA | Emit + Re-Emit vorhanden (ASCII `"i"`). **`service_selector_dialog.py` verbindet `info_requested` NICHT** → i-Button im ServicePicker wirkungslos. |
| 6b | `serviceui/param_columns.py` | 🔴 NEU | UI-Umbau Resultatfelder (einzelner `btn_output_params_info` statt Per-Zeile-i-Buttons) – betrifft auch `_DialogParamHost`. |
| 1 | `analytics/ui/common.py` | 🔴 NEU | `CheckableComboBox` fehlt vollständig. |
| 7 | `analytics/ui/heatmap_widget.py` | 🟡 KORRIGIERT | **`combo_field` liegt in `heatmap_widget.py` (Z. 496), NICHT in `heatmap_page.py`** – Plan-Verortung angepasst. |
| 7b | `analytics/engine/analytics_view_model.py` | ✅ ENTSCHIEDEN | `set_heatmap_config()` bleibt Einzel-Feld (`field: str`); Multi-Select steuert `feature_ids` (F1c/F2, §6). |

## 4. Architektur & Datenfluss

```text
[ServicePicker / ServiceSelectorDialog] ──(EventBus: service_set_changed)──► [AnalyticsViewModel]
  │                                                                             │
  ├── (i) "Resultatfelder" ──► [ServiceDescriptionDialog (read-only)]          │
  │                                                                             │
[CheckableComboBox (Multi-Select)] ──(checked → feature_ids: List[str])────────┘
       │                               (Filter: WHERE feature_id IN (...))
       │
       ▼
[AnalyticsViewModel.set_heatmap_config(field: str)] ──► [FeatureStoreReader]
       │                    (GENAU EIN aktives Hauptfeld, F1c/F2)
       └──(heatmap_field: str) + feature_ids-Filter
                ▼
        [DuckDB Multi-Field-Aggregation / Render]
```

## 5. Schritt-für-Schritt Umsetzung (inkl. Entscheidungen)

### Schritt 1: `analytics/ui/common.py` – `CheckableComboBox` (NEU)
* `class CheckableComboBox(QComboBox)`: `setEditable(True)`,
  `lineEdit().setReadOnly(True)`, LineEdit-Placeholder (z. B. `"Felder wählen…"`).
* **Pop-up offen halten:** `eventFilter` auf `lineEdit()`/`view()` – Mausklick in
  die Checkbox-Spalte ruft **nicht** `hidePopup()` auf (Qt überschreibt sonst
  den Standard; Pattern: `QComboBox` mit `QStandardItemModel` +
  `Qt.ItemIsUserCheckable`, analog `master_tree.py` Checkbox-Muster).
* API: `add_checkable_item(display_text, user_data, checked=False)`,
  `checked_data() -> List[str]` (nur angehakte `user_data`-Keys in
  Item-Reihenfolge), Signal `selection_changed(list)` (emittiert bei jedem
  CheckState-Wechsel; blockierbar über `_syncing`-Flag, Muster `heatmap_widget`).
* Headless instanziierbar (kein `exec()` im Konstruktor).

### Schritt 2 + 3: Reader/Repository-Filterung
**Bereits umgesetzt (Commit `4648399`) – kein Handlungsbedarf**, nur
Regressions-Absicherung in `test/test.py` (Filter-Check).

### Schritt 4: `resolve_service_display_name()` – natives Handling (DELTA, F3 ✅)
* **Entscheidung F3:** `"native"` und `native_*`-Keys werden wie leere/`"none"`-
  Keys auf `"Allgemein"` gemappt (benutzerfreundlich, konsistent zu Root
  Cause 3). Fallback-Zweig: Leer / `"none"` / `"native"` / `"native_*"`
  → `"Allgemein"`.
* Unregistrierte `srv_`/`ind_`-Keys → Title-Case (bereits vorhanden, bleibt).

### Schritt 5: `header_line` (Bugfix 1)
**Bereits intakt** – keine Änderung; nur Test-Absicherung.

### Schritt 6: `master_tree.py` / `service_selector_widget.py` / `service_selector_dialog.py`
* **Bugfix 2 DELTA (ServicePicker):** Im `service_selector_dialog.py` das
  Signal `info_requested` (und `category_info_requested`) des eingebetteten
  `ServiceSelectorWidget` mit dem Dialog verbinden.
* **Dialog-Entkopplung (F4 ✅):**
  * **ServiceWindow** (`service_win.py`): `i`-Button öffnet WEITERHIN den
    editierbaren `ServiceDescriptionEditDialog` (Instanz-Notizen; Bestand,
    keine Änderung).
  * **ServicePicker** (`service_selector_dialog.py`): zeigt Read-Only
    `ServiceDescriptionDialog.from_plugin()` bzw. `from_set()`.
* **Header-Format (F5 ✅):** Badge-Header strikt vereinheitlicht
  (gilt für `_info_header_tooltip`, `_info_set_tooltip` und den
  Info-Dialog-`header_line`):
  * Service aktiv im Indikator: `📌 im <Indikator> | 🟢 aktiv in <Indikator>`
  * Service inaktiv: `📌 im <Indikator> | ⚪ inaktiv`
  * Mehrere Indikatoren (Sets): `📌 im <I1> + <I2> | 🟢 aktiv in <I1> + <I2>`
    bzw. `⚪ inaktiv` – Namenslogik analog `_apply_set_badge`.
* **UI-Umbau Resultatfelder (`param_columns.py` `_build_service_column`):**
  * Per-Zeile-`i`-Buttons der Haupt-Resultatfelder entfernen (20.03.01-Muster).
  * Direkt hinter dem Label `📊 Resultatfelder:` einen kompakten
    `QPushButton` `btn_output_params_info` (Text/Icon `(i)`) platzieren.
  * Klick → kompaktes Info-Window mit **allen** Output-Parametern der
    gewählten Service-Instanz inkl. Typ + Beschreibung + Service-Referenz.
  * **System-Metriken (F6 ✅):** Felder mit `"technical": True` werden
    UNTERHALB der Haupt-Resultatfelder in einer separaten, kleineren Sektion
    `🔧 System-Metriken` gerendert (Semikolon-getrennt, dezenter Block).
  * `_DialogParamHost`-Kompatibilität (Eltern-Auflösung `self`/`self._dialog`,
    Bugfix `b772c93`) beibehalten; `_service_output_schemas` bleibt.

### Schritt 7: `analytics/ui/heatmap_widget.py` (KORRIGIERTE Verortung + F1c/F2/F7 ✅)
* `_combo_field` (Z. 496) durch `CheckableComboBox` ersetzen.
* **Multi-Select-Semantik (F1c/F2):** Die Multi-Auswahl steuert
  AUSSCHLIESSLICH den Datenquellen-Filter `feature_ids: List[str]`
  (→ `view_model.set_feature_ids(...)`, Filter-Pfad `feature_keys_by_service`
  / `fetch_generic_heatmap`). Die Aggregation verarbeitet GENAU EIN aktives
  Hauptfeld.
* **Keine Signatur-Änderung (F2):** `set_heatmap_config(x_dim, y_dim, field,
  agg)` bleibt unverändert – `field: str` (heatmap_field) ist das eine aktive
  Hauptfeld. KEINE Erweiterung auf `fields: List[str]`.
* Bei `data_ready`/`_sync_combos_from_payload` (Z. 1040): Befüllen via
  `field_sources` mit `{Service-Name} / {Parameter}`,
  `userData="{service_id}|{param_key}"` (Mehrfach-Key: `{key}`-Fallback, Muster
  `_field_label`).
* `_syncing`-Guard und `_apply_config`/`request_data`-Loop beibehalten.
* **UI-Behavior (F7):** Die Feld-Auswahl (`CheckableComboBox`) bleibt bei
  Aggregationen `COUNT` und `CONFLUENCE_COUNT` strikt deaktiviert
  (`setEnabled(False)`, bestehendes `_update_controls`-Muster).

## 6. Entscheidungen (F1–F7, bestätigt durch Anwender am 09.08.2026)

| ID | Entscheidung (verbindlich) |
|---|---|
| F1 | **Multi-Select = Quellen-Filter (c):** Multi-Auswahl im Dropdown steuert ausschließlich den Datenquellen-Filter `feature_ids: List[str]`. |
| F2 | **Keine Signatur-Erweiterung:** `set_heatmap_config(x_dim, y_dim, field, agg)` bleibt unverändert; die Aggregation (`heatmap_field: str`) verarbeitet genau ein aktives Hauptfeld. |
| F3 | **`native`-Fallback:** `resolve_service_display_name("native")` und `native_*`-Keys → `"Allgemein"`. |
| F4 | **Dialog-Entkopplung:** ServiceWindow → editierbarer `ServiceDescriptionEditDialog` (Bestand); ServicePicker → Read-Only `from_plugin()`/`from_set()`. |
| F5 | **Header-Format vereinheitlicht:** `📌 im <Indikator> | 🟢 aktiv in <Indikator>` bzw. `📌 im <Indikator> | ⚪ inaktiv` (Sets: Namen mit ` + ` verknüpft). |
| F6 | **System-Metriken:** `technical: True`-Felder unterhalb der Haupt-Resultatfelder in separater, kleinerer Sektion `🔧 System-Metriken`. |
| F7 | **UI-Behavior:** Feld-Auswahl bei `COUNT`/`CONFLUENCE_COUNT` strikt deaktiviert (`setEnabled(False)`). |

## 7. Verification Checklist (`test/test.py`, headless)

- [x] **Syntax-Check:** `py_compile` auf allen geänderten Dateien
      (`common.py`, `analytics_view_model.py`, `param_columns.py`,
      `service_selector_widget.py`, `service_selector_dialog.py`,
      `service_win.py`, `heatmap_widget.py`, `test/check_dialog_host.py`,
      `test/test.py`) – OK. Unveränderte Dateien (`feature_store_reader.py`,
      `analytics_repository.py`, `description_dialog.py`, `master_tree.py`)
      wurden nicht angefasst.
- [x] **Filter-Check (F1):** `feature_keys_by_service(feature_ids=['srv_a'])`
      liefert KEINE `srv_b`-Keys (und umgekehrt) – headless verifiziert
      (test.py-Checks `m`/`n`, isoliertes Skript analog zum 37er-Block).
      Multi-Select-Mapping (angehakte Items → `feature_ids`) per
      Code-Inspektion abgesichert.
- [x] **Naming- & Header-Check (F3/F5):** `resolve_service_display_name('native')`
      und `resolve_service_display_name('native_foo')` liefern `"Allgemein"`
      (Checks `d`–`f`); `_info_header_line`/`_info_set_header_line` liefern
      das vereinheitlichte Format `📌 im … | 🟢 aktiv in …` / `⚪ inaktiv`
      (Checks `i`–`k`). `ServiceDescriptionDialog`-`header_line`-Rendering
      (Zeile 1, fett + Leerzeile) ist Bestand (Commit `4648399`) und durch
      die Phase-16-Tests `D1`/`D2` + Code-Inspektion abgesichert.
- [x] **Widget-Check:** `CheckableComboBox` instanziiert headless ohne
      Qt-Exec-Freeze; `checked_data()` liefert nur angehakte `userData`-Keys,
      `set_checked_data()` wechselt CheckStates (Checks `a`–`c`).
      Pop-up-Offenhalten (EventFilter unterdrückt `hidePopup()` bei
      Checkbox-Klick) ist per Code-Inspektion abgesichert (nicht headless
      simulierbar).
- [x] **Info-Umbau-Check (F6):** `_build_service_column` rendert genau EINEN
      `btn_output_params_info` (hinter „Resultatfelder"), keine Per-Zeile-i-
      Buttons mehr; `technical: True`-Felder als separate Sektion
      `🔧 System-Metriken` im Sammel-Info-Window; `_DialogParamHost`-
      Spaltenbau fehlerfrei (Regressions-`test/check_dialog_host.py`,
      16 Checks – ALLE PASS).
- [x] **Picker-i-Button (F4):** Signal-Re-Emission `category_info_requested`
      im `ServiceSelectorWidget` (beide Modi) + Verdrahtung
      `info_requested`/`category_info_requested` im `ServiceSelectorDialog`
      → Read-Only `ServiceDescriptionDialog.from_plugin()`/`from_set()`
      (Check `l` + Code-Inspektion der Slot-Verdrahtung); ServiceWindow-Pfad
      (Editier-Dialog) unverändert.
- [x] **F2/F7:** `set_heatmap_config`-Signatur unverändert (`field: str`,
      Check `g`); `_field_key` extrahiert den JSON-Key aus
      `"{service_id}|{key}"` (Check `h`); `COUNT`/`CONFLUENCE_COUNT` sind
      NICHT in `_VALUE_AGGS` → Feld-Combo wird deaktiviert (Check `o` +
      `_update_controls`-Inspektion).

## 8. Hinweise
* Die 6 vorbestehenden Fehlschläge in `test/test.py` (P2/P5/H3–H7,
  Fenster-Persistenz-Geometrie) sind NICHT Bestandteil dieser Phase.
* Entscheidungen F1–F7 sind vom Anwender am 09.08.2026, 20:21 bestätigt und
  in §6 verbindlich dokumentiert.

## 9. Implementierungs-Log (09.08.2026, ~20:55; Commit `1324d95`, Tag `20.03.02`)
* **`analytics/ui/common.py`** – `CheckableComboBox` (NEU, F1): `QComboBox` mit
  `QStandardItemModel`, Checkbox-Spalte, EventFilter hält Pop-up bei
  Checkbox-Klick offen; API `add_checkable_item(display_text, user_data,
  checked)`, `checked_data() -> List[str]`, `set_checked_data()`, Signal
  `selection_changed(list)`.
* **`analytics/engine/analytics_view_model.py`** – F3: `resolve_service_display_name`
  mappt `"native"`/`native_*`/`"none"`/leer → `"Allgemein"` (statt Title-Case-
  Fallback für `native`).
* **`serviceui/service_win.py`** – F5: Info-Badge-Header vereinheitlicht
  (`📌 im … | 🟢 aktiv in …` bzw. `⚪ inaktiv`, Sets mit ` + `).
* **`serviceui/service_selector_dialog.py`** – F4: Import + Verdrahtung
  `info_requested`/`category_info_requested` des eingebetteten Widgets;
  Slots `_on_info_requested`/`_on_category_info_requested` öffnen Read-Only
  `ServiceDescriptionDialog.from_plugin()`/`from_set()` mit
  `_info_header_line`/`_info_set_header_line`.
* **`serviceui/service_selector_widget.py`** – F4: neues Signal
  `category_info_requested` + Re-Emission in beiden Modi (Achtung: gemischte
  Line-Endings, nur per Python-Skript editierbar).
* **`serviceui/param_columns.py`** – F6: Per-Zeile-i-Buttons entfernt, EIN
  `btn_output_params_info` hinter `📊 Resultatfelder:`; neuer Slot
  `_show_output_params_info()` zeigt Hauptfelder + Sektion
  `🔧 System-Metriken` (`technical: True`); `_DialogParamHost`-Kompatibilität
  beibehalten.
* **`analytics/ui/heatmap_widget.py`** – F1c/F2/F7: `_combo_field` ist jetzt
  `CheckableComboBox`, userData `"{service_id}|{key}"`; Multi-Select →
  `set_feature_ids(...)` (Quellen-Filter); `set_heatmap_config`-Signatur
  unverändert; Feld-Combo bei `COUNT`/`CONFLUENCE_COUNT` deaktiviert.
* **Validierung:** `py_compile` auf allen geänderten Dateien OK; neuer
  20.03.02-Testblock in `test/test.py` (Checks `a`–`o`, 15 Stück);
  `test/check_dialog_host.py` (16 Checks); isolierte Verifikationsskripte
  (danach gelöscht, test/-Cleanup) – ALLE PASS. Kein Regressionstest, keine
  UI-Ausführung (Phase-19-Invariante 2).

---

# 20.03.03 Dropdown-Eindeutigkeit & Sammel-Auswahl (finale Spezifikation 20.03.02, 09.08.2026, ~21:15)

## 1. Regeln & Invarianten
* **Code-Style:** Exakt 4 Leerzeichen, 1 Leerzeile zwischen Methoden (PEP8,
  Phase-19-Invariante 3). Additive Aenderungen (Invariante 11).
* **Testing:** STRIKT HEADLESS via `py_compile` & `test/test.py`
  (`QApplication.exec()` VERBOTEN – Invariante 2); neue Test-Skripte/DBs nach
  `test/` (Invariante 10).

## 2. Problemstellung (User-Meldung 09.08.2026)
Im Feld-Dropdown der generischen Heatmap sind Namens-Kollisionen nicht sauber
aufgeloest: Liefern zwei aktive Services denselben Ergebnis-Key (z. B. `is_hit`),
gibt es bisher NUR EINEN Eintrag mit dem rohen Key (`_field_label` unterdrueckt
den Service-Prefix bei `len(sids) > 1` bewusst – „Pfad-Kette"-Meldung vom
09.08.). Der Anwender kann nicht zuordnen, welcher Service den Wert liefert.
Spezial-Parameter (`steps_around` vs. `volume_ratio`) sind unkritisch, aber ohne
durchgehendes Schema.

**Ziel (2-stufige Strukturierung):** Jeder Eintrag strikt `{Service-Name} /
{Parameter}` (100 % Eindeutigkeit) + deaktivierte Sektions-Header + Sammel-
Eintrag fuer gemeinsame Keys.

## 3. Entscheidungen (Q1-Q5, Anwender 09.08.2026)

| ID | Entscheidung (verbindlich) |
|---|---|
| Q1 | **Einzel-Eintraege bei Kollisionen:** pro Service EIN Eintrag `{Name} / {key}` (z. B. `Proximity / is_hit`, `Grid Lines / is_hit`). Der rohe Key entfaellt vollstaendig aus dem Dropdown. |
| Q2 | **Sammel-Eintrag `Alle Services / <key>`:** reiner UI-Komfort, userData `ALL|<key>`. Beim Anhaken sind alle Services aktiv, die den Key liefern (-> `feature_ids`). **KEIN `ALL|`-Format bis in die DB/Repository** – keine Aggregationslogik-Aenderung. |
| Q3 | **F1c/F2 strikt beibehalten:** GENAU EIN Hauptfeld (`field=_field_key(currentData())`); angehakte Checkboxen steuern NUR `feature_ids`. Kein Multi-Feld-Umbau im Repository. |
| Q4 | **Sektions-Header** (`🌐 Gleiche Parameter (alle aktiven Services):`, `🔌 Einzelservices:`) als deaktivierte, nicht-auswaehlbare Trennzeilen (`Qt.NoItemFlags`, grau + fett, userData `None`). |
| Q5 | **Initial-Zustand:** Sammel-Eintraege (shared Keys) + Einzel-Eintraege (unique Keys) angehakt; Einzel-Eintraege von shared Keys NICHT (keine Doppel-Haken). **XOR-Regel:** Sammel und Einzel desselben Keys schliessen sich gegenseitig aus. |

## 4. Datenfluss & Mapping (kein DB-Umbau)
```text
userData je Item:
  Sammel-Eintrag : 'ALL|<key>'                 (Label: 'Alle Services / <key>')
  Einzel-Eintrag : '{service_id}|<key>'        (Label: '{Name} / <key>')
  Sektions-Header: None                         (Qt.NoItemFlags, nicht checkbar)

checked_data() -> _checked_field_service_ids():
  - 'ALL|<key>'          -> expandieren ueber self._field_sources[key]
                            (alle Quellen-Services des Keys)
  - '{service_id}|<key>' -> service_id direkt
  (dedupliziert, sortiert) -> view_model.set_feature_ids(ids)

Hauptfeld (F2): field = _field_key(currentData())  ('ALL|is_hit' -> 'is_hit')
Aggregation:   unveraendert (GENAU EIN Key; feature_ids-Filter in DuckDB)
```
Die `CheckableComboBox.checked_data()` ueberspringt Header automatisch
(nicht-checkbare Items liefern Qt.Unchecked).

## 5. Schritt-fuer-Schritt Umsetzung

### Schritt 1: `analytics/ui/common.py` – `add_header_item()` (additiv)
```python
def add_header_item(self, display_text: str) -> None:
    """Fuegt eine deaktivierte, nicht-auswaehlbare Trenn-/Kopfzeile hinzu
    (20.03.03, Q4). userData = None (Header tauchen nie in checked_data() auf)."""
    item = QStandardItem(str(display_text))
    item.setData(None, Qt.UserRole)
    item.setFlags(Qt.NoItemFlags)          # nicht aktiv, nicht checkbar
    item.setEnabled(False)
    brush = QBrush(QColor(128, 128, 128))  # grau
    item.setForeground(brush)
    f = item.font(); f.setBold(True); item.setFont(f)
    self._model.appendRow(item)
```
(Import `QBrush`/`QColor` aus `PySide6.QtGui` ergaenzen.)

### Schritt 2: `analytics/ui/heatmap_widget.py` – Befuellung (`_sync_combos_from_payload`)
* `self._field_sources = data.get("field_sources") or {}` merken (Attribut fuer
  die ALL-Expansion; im `__init__` mit `{}` vorinitialisieren).
* `keys` in `shared` (2+ Quellen) und `unique` (genau 1 Quelle) gruppieren.
* Wenn `shared`: Header `🌐 Gleiche Parameter (alle aktiven Services):`, dann je
  shared Key: `add_checkable_item(f"Alle Services / {k}", f"ALL|{k}", checked=True)`.
* Header `🔌 Einzelservices:`, dann je Key (sortiert):
  * unique: je Service `add_checkable_item(f"{Name} / {k}", f"{sid}|{k}", checked=True)`
  * shared: je Service `add_checkable_item(f"{Name} / {k}", f"{sid}|{k}", checked=False)`
    (Sammel-Eintrag ist initial aktiv, Q5)
  * Legacy ohne `field_sources` (leere sids): roher Key `add_checkable_item(k, k, checked=True)`
* Current-Index: `_find_field_index(prev_field)` (findet bei shared Keys den
  Sammel-Eintrag zuerst); Fallback `_first_field_index()` (UEBERspringt Header,
  statt blind Index 0).

### Schritt 3: `heatmap_widget.py` – Filter-Mapping (`_checked_field_service_ids`)
```python
def _checked_field_service_ids(self) -> List[str]:
    ids: List[str] = []
    for ud in self._combo_field.checked_data():
        s = str(ud or "")
        if s.startswith("ALL|"):
            key = s.split("|", 1)[1]
            for sid in (self._field_sources.get(key) or []):
                if sid and sid not in ids:
                    ids.append(sid)
        elif "|" in s:
            sid = s.split("|", 1)[0]
            if sid and sid not in ids:
                ids.append(sid)
    return ids
```

### Schritt 4: `heatmap_widget.py` – XOR-Reconciliation (Q5)
* `_on_field_selection_changed`: vor `set_feature_ids` die neue Methode
  `_reconcile_sammel_checks()` aufrufen.
* `_reconcile_sammel_checks()`: sammelt angehakte `ALL|`-Keys und Einzel-Keys;
  Einzel-Eintraege eines angehakten Sammel-Keys abwaehlen, Sammel-Eintrag eines
  Keys mit angehakten Einzel-Eintraegen abwaehlen (`set_checked_data`, blockiert,
  kein Re-Emit).
* Danach Current-Index nachziehen: steht der Index auf einem abgewaehlten/Header-
  Item, auf das erste angehakte Item desselben Keys wechseln (blockSignals),
  sonst erstes angehaktes/erstes auswaehlbares Item.

### Schritt 5: `heatmap_widget.py` – E6-Loop-Fix (bestehender 20.03.02-Delta)
Zeile ~1152: `params.get("heatmap_field") != currentData()` ist seit dem
userData-Format `{service_id}|{key}` fehlerhaft (params haelt den reinen Key).
Vergleich auf `_field_key(self._combo_field.currentData())` umstellen (nur
Kosmetik: `set_heatmap_config` ist idempotent, aber der falsche Vergleich
loeste jedes Sync einen `_apply_config()`-Aufruf aus).

## 6. Verification Checklist (`test/test.py`, headless)

- [x] **Syntax-Check:** `py_compile` auf `common.py`, `heatmap_widget.py` (und
      `test/test.py`) – OK.
- [x] **Header-Check (Q4):** `add_header_item` fuegt ein Item mit `Qt.NoItemFlags`
      und `userData=None` hinzu; `checked_data()` ignoriert Header
      (20.03.03-Checks `a`/`b`).
- [x] **Label-Check (Q1):** shared Key erscheint als `Proximity / is_hit` UND
      `Grid Lines / is_hit` (pro Service); roher Key ist NICHT im Dropdown
      (20.03.03-Checks `c`/`d`; 28 isolierte Checks vor dem Einbau).
- [x] **Sammel-Expansion (Q2):** `_checked_field_service_ids()` mit angehakten
      `ALL|is_hit` -> alle Quellen-Services des Keys; Einzel-Eintrag ->
      genau seine service_id (20.03.03-Check `f`).
- [x] **XOR (Q5):** Klick auf Einzel-Eintrag enthaakt den Sammel-Eintrag und
      umgekehrt (Klick-Tracking `last_click_index`); kein Doppel-Haken-Zustand
      (20.03.03-Checks `g`/`h`).
- [x] **Initial (Q5):** Sammel (shared) + Einzel (unique) angehakt; Einzel von
      shared Keys NICHT (20.03.03-Check `e`).
- [x] **E6-Loop:** Vergleich laeuft ueber `_field_key(currentData())` – kein
      ueberfluessiger `config`-Call bei identischem Key (20.03.03-Check `i`).
- [x] **Regression:** `test/check_dialog_host.py` bleibt PASS (16 Checks,
      unveraenderte Pfade); 20.03.02-Checks `a`-`o` + `checked_data`/
      `set_checked_data`-API isoliert gruen (28 Checks).

## 7. Hinweise
* Entscheidungen Q1-Q5 vom Anwender am 09.08.2026 bestaetigt (siehe Antwort-
  Nachricht). Implementierungs-Log siehe §8.
* Keine UI-Tests, kein Regressionstest (Invariante 2).

## 8. Implementierungs-Log (09.08.2026, ~21:40; Commit `84f02df`, Tag `20.03.03`)
* **`analytics/ui/common.py`**:
  * `add_header_item()` (Q4): deaktivierte, graue, fette Trenn-/Kopfzeile
    (`Qt.NoItemFlags`, `userData=None`) – erscheint weder auswaehlbar noch in
    `checked_data()`.
  * Klick-Tracking (Q5): `_last_click_index` im EventFilter (Popup-Viewport)
    + Getter `last_click_index()` – Grundlage der XOR-Aufloesung (Sammel vs.
    Einzel); `-1` = programmatischer Wechsel (keine Aufloesung).
* **`analytics/ui/heatmap_widget.py`**:
  * `self._field_sources` (Key -> Quellen-Services) aus dem Payload gemerkt.
  * `_sync_combos_from_payload` (Q1/Q4/Q5): 2-stufige Struktur – Sektions-
    Header `🌐 Gleiche Parameter (alle aktiven Services):` + Sammel-Eintraege
    `Alle Services / {key}` (`ALL|key`, initial angehakt), dann
    `🔌 Einzelservices:` mit EINDEUTIGEN Eintraegen `{Name} / {key}` je Quelle
    (unique angehakt, shared-Einzel nicht). Roher Key entfaellt bei bekannten
    Quellen; Legacy ohne `field_sources` bleibt defensiv als roher Key.
  * `_checked_field_service_ids` (Q2): `ALL|key`-Expansion ueber
    `field_sources` (dedupliziert); Einzel-Eintrag -> genau seine `service_id`.
  * `_reconcile_sammel_checks` (Q5): XOR auf Klick-Tracking-Basis – Klick auf
    Einzel enthaakt den Sammel-Eintrag desselben Keys, Klick auf Sammel
    enthaakt die Einzel-Eintraege.
  * `_sync_field_current_after_checks`: Current-Index auf angehaktes/
    auswaehlbares Item nachziehen (Header werden uebersprungen).
  * `_first_field_index` (Q4): erster auswaehlbarer Index statt blind 0.
  * E6-Loop-Fix: Vergleich `params["heatmap_field"]` gegen
    `_field_key(currentData())` statt `currentData()` (behebt ueberfluessige
    `_apply_config()`-Aufrufe seit dem `{service_id}|{key}`-userData).
* **Validierung:** 28 isolierte Checks in `test/` (Q1-Q5, E6, Randfaelle,
  20.03.02-API-Regression) + `test/check_dialog_host.py` (16 Checks) – ALLE
  PASS; neuer 20.03.03-Testblock (9 Checks `a`-`i`) in `test/test.py`;
  Temp-Skripte geloescht (test/-Cleanup). Kein UI-Test, kein Regressionstest.


---

# 20.04 Parameter-Varianten, Instanziierung & Archivierung
## Concept: Parent-Child & Hash-ID (Model C)
- **Service/Set = Template**: Pure logic/code definition (non-executable).
- **Instance/Clone = Executable**: Combination of `Service_ID` + `Parameters` + `Timeframe/Symbol`. Assigned unique cryptographic `instance_hash`.
- **Mastertree UI**: Expandable Parent-Child hierarchy (`Service` -> `Parameter-Clones`).
## Archive System
- **Instance Archive**: Move specific failing parameter presets to Archive. Parent service remains active.
- **Complete Archive**: Move entire Service/Set with all child clones to Archive.
- **Doc Log**: Required large text field per archived node for negative knowledge logging.
- **Safety**: All selection checkboxes disabled inside Archive directory.
## Archive Maintenance Context Menu
- **Delete "Data Only"**: Clears historical signals/metrics from DB; keeps node structure, settings, and documentation text.
- **Delete "Complete"**: Double confirmation prompt. Irreversibly purges node, clones, settings, logs, and all DB records.
## Text Architecture: 20.04
[Mastertree (Active)]
 ├── 📁 [Swing Algos]
 │     └── ⚙️ [srv_swing_pivot]
 │           ├── 🟢 [Preset: M15_Fast] (hash: #a91f3b) [X]
 │           └── 🟢 [Preset: H1_Slow]  (hash: #b82e4c) [X]
[Archive (Checkboxes Disabled)]
 ├── 📁 [Invalid Sweeps]
 │     └── 🔴 [srv_breakout_v1] (Entire Service Archived)
 │           ├── 📝 Log: "85% false signals in chop markets"
 │           └── 🔹 [Preset: Default] (hash: #c73d5d)


---

# 20.05 Multi-DB Architecture & Data Management
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


---

# Phase 20.06: Generatives Filter- & Sortiersystem (Cross-View Filtering Engine)

## 1. Architektur & Invarianten
* **Code-Style:** Exakt 4 Leerzeichen Einrückung, 1 Leerzeile zwischen Methoden.
* **Testing:** Headless via `py_compile` & `test/test.py` (UI-Exec STRIKT VERBOTEN).
* **Entkopplung:** MVVM-Datenfluss via `AnalyticsViewModel`, dyn. SQL-Generation im `FeatureStoreReader`.

---

## 2. Kernkonzept: Generisches Rules-Based Filtering

Ein zentraler, dynamischer Filter-Builder erzeugt strukturierte Regelketten (Rules Tree / AST), die konsistent auf **alle** Analytics-Ansichten angewendet werden.

### A. Regel-Spezifikation
- **Ziel-Felder:** Jedes numerische, Boole’sche oder kategoriale Feld aus `feature_data` (JSON) sowie native DB-Spalten (`bar_time`, `feature_id`, `symbol`, `timeframe`).
- **Operatoren:** `=`, `!=`, `>`, `>=`, `<`, `<=`, `BETWEEN`, `IN`, `LIKE`, `IS_HIT`.
- **Verknüpfung:** `AND` / `OR` Logikblöcke.

### B. Wirkung auf die Ansichten (Cross-View Projection)
- `TablePage`: Zeilen-Filtering & Multi-Column-Sortierung.
- `HeatmapPage`: Vorauswahl/Filterung der Quell-Bars **vor** der Matrix-Aggregation.
- `ScatterPage`: Ausblenden gefilterter Datenpunkte im Scatter-Plot.
- `DistributionPage`: Dynamisches Re-Binning/Histogramm über den gefilterten Datensatz.

---

## 3. Datenfluss & Engine-Integration

```text
[AnalyticsWindow (Filter-UI / Rule-Editor)]
                 │
                 ▼
[AnalyticsViewModel.set_filter_rules(rules)] ──► [_mark_dirty()]
                 │
                 ▼ (AsyncWorker)
[FeatureStoreReader.build_dynamic_where(rules)]
                 │
                 ├── Generiert SQL: "WHERE feature_data->>'visit_pct' >= 0.05 AND ..."
                 │
                 └── Ausführung ──► Updates für Table / Heatmap / Scatter / Distribution

```

---

## 4. Profil-Payload Schema v2.1 (Sektion `filters`)

```json
{
  "schema_version": "2.1.0",
  "filters": {
    "logic": "AND",
    "rules": [
      { "field": "visit_pct", "op": ">=", "val": 0.05 },
      { "field": "is_hit", "op": "==", "val": true },
      { "field": "feature_id", "op": "IN", "val": ["srv_grid_lines", "srv_proximity"] }
    ],
    "sort": [
      { "field": "bar_time", "order": "DESC" },
      { "field": "visit_pct", "order": "ASC" }
    ]
  }
}

```

---

## 5. Verification Checklist (`test/test.py`)

* [ ] Safe SQL-Builder: Sichere Generierung von `WHERE`-Clauses aus Filter-Regeln (SQL-Injection-Schutz).
* [ ] Multi-View Cross-Check: Filterergebnis ist identisch über Table, Heatmap und Scatter.
* [ ] Empty-Rule Fallback: Leere Filter-Regeln liefern vollständigen Datensatz.
* [ ] Profil v2.1: Speicherung & Wiederherstellung der `filters`-Sektion im Payload.


---

# 20.07 Architektur-Konzept: Analytics-System (Abarbeitungs- & Event-Pipeline)

> **Status:** Konzeptualisiert & Freigegeben (Vermeidung von Event-Konflikten, Performance-Optimierung & Lückenloser Varianten-Persistenz)
> **Ziel:** Vollständige Entkopplung von UI-Controls, State-Management und Canvas-Rendering zur Beseitigung von Timing-Races, Mehrfach-Rebuilds und UI-Flackern.

---

## 1. Kern-Architektur: Die 3-Kapsel-Pipeline

Das Analytics-System trennt Datenfluss und Steuerung strikt in drei voneinander isolierte Event-Welten. Direkte Querbeziehungen (z. B. UI-Control löst direkt Canvas-Render aus) sind aufgehoben.

```
 ┌───────────────────────────────────────────────────────────┐
 │ 1. USER-INPUT-WELT (UI Controls & ServicePicker)          │
 │    - Nimmt Benutzer-Aktionen entgegen (Combos, Haken)     │
 │    - Ruft ausschließlich Setter im ViewModel auf          │
 └─────────────────────────────┬─────────────────────────────┘
                               │ (set_params, set_feature_ids)
                               ▼
 ┌───────────────────────────────────────────────────────────┐
 │ 2. SYSTEM-STATE-WELT (AnalyticsViewModel & Repositories)  │
 │    - Führt State, Normalisierung & Async-Worker           │
 │    - Feuert KEIN automatisches refresh_all() mehr         │
 └─────────────────────────────┬─────────────────────────────┘
                               │ (params_restored, QUERY_FEATURES)
                               ▼
 ┌───────────────────────────────────────────────────────────┐
 │ 3. RENDERING-WELT (Canvas & UI-Pages)                     │
 │    - Reiner Empfang von fertigen Payloads (Passive View)   │
 │    - Ausführung nur bei sichtbarem Tab (Lazy Rendering)   │
 └───────────────────────────────────────────────────────────┘

```

---

## 2. Deterministischer Zustandsautomat: „Erst Controls, dann Canvas“

Jeder Lade-, Restore-, Profilwechsel- oder Umschalt-Vorgang läuft nach einer garantierten, ununterbrechbaren 4-Phasen-Sequenz ab:

$$\text{VM-Params setzen} \xrightarrow{\text{Phase 1}} \text{Single-Pass UI-Control-Sync} \xrightarrow{\text{Phase 2}} \text{Gezielte Query (Sichtbare Seite)} \xrightarrow{\text{Phase 3}} \text{Canvas-Render (Lazy)}$$

### Ablauf-Regeln:

1. **Phase 1 (VM State):** ViewModel aktualisiert seine `_params` im Speicher. Es emittiert ausschließlich `params_restored` (kein automatisches `refresh_all()` mehr im ViewModel!).
2. **Phase 2 (Control-Sync):** Die Window-Ebene führt `_sync_all_pages_from_params()` genau **1×** aus.
* *Invariante:* Während des gesamten Setzens der Controls (Combos, Slider, Picker-Haken) werden Qt-Signale konsequent über `blockSignals(True)` stummgeschaltet, um Rückkopplungen ins ViewModel zu verhindern.


3. **Phase 3 (Gezielte Datenabfrage):** Erst wenn alle Controls 100 % konsistent sind, fordert das Window Daten via `request_data()` an – **ausschließlich für die aktuell sichtbare Seite**.
4. **Phase 4 (Canvas-Rendering):** `_sync_combos_from_payload` wird darauf reduziert, ausschließlich dynamische Feld-Metadaten und den Canvas-Render zu verarbeiten. Controls werden durch den Payload *niemals* überschrieben.

---

## 3. Lösungsbausteine für Bugs 3 & 4

### Bug 3: Varianten-Persistenz (Clones & `instance_hashes`)

* **Ursache:** `_current_payload()` hat `instance_hashes` im Profil-Payload ausgelassen. `_apply_profile()` und `restore_workspace()` haben bei fehlendem Key alte In-Memory-Hashes beibehalten.
* **Lösung:**
1. `_current_payload()` sichert `instance_hashes` explizit in der `sources`-Sektion ab.
2. `_apply_profile()` und `restore_workspace()` setzen `instance_hashes` garantiert auf `[]` zurück, wenn der Key im Payload fehlt (Alt-Profile/Workspaces).
3. `_save_workspace` speichert eine flache Kopie (`dict(self._vm.params)`) mit duplizierten Listen (`list(...)`), um Aliasing zu verhindern.



### Bug 4: Asynchrone "(No Data)"-Anzeige im Dropdown

* **Ursache:** `resolve_no_data_variants()` wurde synchron im UI-Hauptthread bei jedem Dropdown-Rebuild aufgerufen. Bei DB-Locks (z. B. durch Hintergrund-Scans) wurden Fehler verschluckt und der Hinweis-Block verschwand lautlos.
* **Lösung:**
1. **Anti-Pattern auflösen:** Die No-Data-Ermittlung wandert vollständig in den asynchronen `QUERY_FEATURES`-Worker (eigener Thread, eigene DB-Verbindung via `DbPool`).
2. **Payload-Rückgabe:** Das Repository liefert `no_data_variants` als Bestandteil des Feature-Payloads an das UI-Widget.
3. **Fallback & UX:** Bei Lade-Latenzen wird kurz ein "Lade..."-Status im Dropdown gezeigt. Tritt ein Fehler auf, wird auf Basis von `plugin_presets()` ein transparenter Fallback-Hinweis gerendert.
4. **Gezielte Anzeige:** Es werden nur die selektierten No-Data-Varianten (Schnittmenge mit aktiven `instance_hashes`) angezeigt oder direkt als deaktiviertes Item `(No Data)` im Dropdown geführt.



---

## 4. Implementierungs- & Abarbeitungsplan

| Schritt | Modul / Bereich | Beschreibung | Begründung |
| --- | --- | --- | --- |
| **1. Persistenz-Fix (Bug 3)** | `analytics_view_model.py`, `analytics_win.py` | Ergänzung von `instance_hashes` in `_current_payload()`, expliziter Hash-Reset in `_apply_profile()` + `restore_workspace()`, Beseitigung von Dict-Aliasing. | Erzeugt die verlässliche Daten- und State-Basis für alle weiteren Schritte. |
| **2. Asynchrone No-Data-Pipeline (Bug 4)** | `feature_store_reader.py`, `analytics_worker.py`, `heatmap_widget.py` | Verlagerung von `resolve_no_data_variants` in den `QUERY_FEATURES`-Worker. Entfernen der synchronen Hauptthread-DB-Queries aus `_rebuild_field_dropdown`. | Beseitigt die Ursache für UI-Hänger und verschwindende Dropdown-Items. |
| **3. Pipeline-Harmonisierung (Pkt. 1 & 2)** | `analytics_win.py`, `analytics_view_model.py`, Pages | Entfernen von `refresh_all()` aus VM-Restores. Einführung von `_sync_all_pages_from_params()` mit `blockSignals(True)`. Umstellung von `_on_page_changed` auf Erst-Sync-dann-Laden & Lazy-Canvas-Render. | Beseitigt Doppel-Passes, Flackern und Event-Schleifen. |
| **4. Verifikation (Headless)** | `test/check_round11.py` | Statische Syntax-Prüfung (`py_compile`), reine Backend-/Logik-Tests (Profil-/Workspace-Roundtrip mit Hashes, Async-Payload, Event-Order). **Keine GUI-Tests.** | Absicherung der Regelkonformität und Regressionsfreiheit. |