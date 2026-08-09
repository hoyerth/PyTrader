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

# Phase 20.03: Generatives Filter- & Sortiersystem (Cross-View Filtering Engine)

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