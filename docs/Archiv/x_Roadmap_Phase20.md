# Phase 20: Speichermodel & Heatmap

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 20)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase20_step1`, `phase20_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `../../test`.
3. **Codebase-Formatierung:** Exakt **4 Leerzeichen** Einrückung (PEP8-Standard) und **exakt 1 Leerzeile** Spacing zwischen Methoden und Funktionsblöcken. Kein Umformatieren unbeteiligter Altbestand-Dateien.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`. `MasterTree`-Selektionen übergeben aufgelöste `feature_ids` direkt an `view_model.set_feature_ids()`.
5. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db/db_pool.py`) – eine Verbindung pro Thread und DB-Datei. Die Fassade `../../db_service.py` bleibt als Re-Export-Wrapper für bestehende Caller erhalten.
7. **Tree-Persistenz & Kollisionsschutz (18.01.03):** 
   - Standalone-Service-Parameter nutzen exklusiv `plugin_params_<id>`.
   - Ordner-Kategorie-Overrides für Plugins nutzen exklusiv `plugin_category_<id>`.
   - Ordner-Kategorien für Service-Sets werden additiv im `category`-Feld der `ServiceSetDefinition` / des `save_set()`-Payloads persistiert.
8. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
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

# Phase 20.01: Analytics UI Dual-Layer, Workspace-Restore & Fault-Tolerant Resolver

## 1. Architektur-Regeln
* **Code-Style:** Exakt 4 Leerzeichen Einrückung, 1 Leerzeile zwischen Methoden.
* **Testing:** Headless via `py_compile` & `../../test/test.py` (UI-Exec STRIKT VERBOTEN).
* **Entkopplung:** MVVM & IoC. Kein SQL in UI, ViewModel/Repository-Brücke nutzen.

---

## 2. DB-Schicht & Repositories

### `../../window_state_repository.py` & `../../state_manager.py`
- Additive Spalte `workspace_state JSON` in `instance_states` (`ALTER TABLE IF NOT EXISTS`).
- `save_workspace_state(instance_id: str, state: dict)` -> Upsert `workspace_state`.
- `get_workspace_state(instance_id: str) -> Optional[dict]` -> Liest `workspace_state`.

### `../../analytics_profile_repository.py`
- `SCHEMA_VERSION_DEFAULT = 2`.
- In `_row_to_profile()`: Wenn Payload `schema_version == 1`, nutze `_migrate_v1_to_v2(payload)`.

---

## 3. Core-Logik & ViewModel

### `../../analytics/engine/service_selector_model.py`
- Methode `resolve_valid_feature_ids(feature_ids: List[str]) -> Tuple[List[str], List[str]]`:
  - Prüft `feature_ids` gegen `PluginRegistry`.
  - Returns `(valid_ids, missing_ids)`.

### `../../analytics/engine/analytics_view_model.py`
- Additiv Signal: `missing_services_detected = Signal(list)`.
- Methode `_migrate_v1_to_v2(payload: dict) -> dict`:
  - Wandelt altes flaches Dict verlustfrei in Sections (`sources`, `table`, `charts`, `styling`).
- In `_apply_profile()`:
  1. `_migrate_v1_to_v2()` ausführen.
  2. `resolve_valid_feature_ids()` rufen.
  3. `set_feature_ids(valid_ids)` setzen.
  4. `missing_services_detected.emit(missing_ids)` feuern.

---

## 4. UI-Integration (`../../analytics/ui/analytics_win.py`)

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

## 5. Verification Checklist (`../../test/test.py`)
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
  `../../db/schema_initializer.py`, `../../window_state_repository.py`). → neu.
- `save_workspace_state` / `get_workspace_state`: nicht vorhanden. → neu.
- `resolve_valid_feature_ids()`: fehlt in `../../analytics/engine/service_selector_model.py`. → neu.
- Signal `missing_services_detected`: fehlt in `../../analytics/engine/analytics_view_model.py`. → neu.
- `label_missing_warning` / `_on_missing_services`: fehlen in `../../analytics/ui/analytics_win.py`. → neu.
- `_save_workspace` / `_restore_workspace`: fehlen. → neu.

**B) Inkonsistenzen & Lücken (geprüft gegen Ist-Code):**

- **B1 – `_keep_history_on_close`-Widerspruch (kritisch):** Plan sagt „Klasse behält
  `_keep_history_on_close = True`“. Ist-Code: `../../persistent_win.py` deklariert den
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
- **B6 – Bestehende Tests brechen:** `../../test/test.py` Teil 33 (R2a: flacher Payload-Zugriff,
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

### 6.3 Angepasste Verification Checklist (`../../test/test.py`, neue Teil 36)

- [ ] Bestandstests umgestellt: Teil 33 R2a/R2b (Sections + `schema_version == 2`),
      Teil 35 Z1e (`payload["table"]["table_row_height"]`).
- [ ] DB: `workspace_state`-Spalte idempotent (ALTER) auf Temp-DB in `../../test`.
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

- `../../state_manager.py`:
  - `instance_states` um Spalte `workspace_state JSON` erweitert (CREATE + idempotentes
    `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
  - Fassaden-Methoden `save_workspace_state(instance_id, state)` und
    `get_workspace_state(instance_id)` (Delegation an das WindowStateRepository,
    Muster 15.04).
- `../../window_state_repository.py`:
  - `save_workspace_state()` (E6, NOT-NULL-konform: liest bestehende
    symbol/timeframe der Row, Fallback `''`/`'M1'`; ON CONFLICT aktualisiert nur
    `workspace_state` + `updated_at`).
  - `get_workspace_state()` -> Optional[dict] (JSON geparst).
- `../../analytics_profile_repository.py`:
  - `SCHEMA_VERSION_DEFAULT = 2`; Sektions-Schema v2 (sources/charts/table/styling, E3).
  - `_migrate_v1_to_v2(payload)` (statisch, verlustfrei: bekannte Keys in Sektionen,
    `feature_id` -> `feature_ids`, unbekannte Top-Level-Keys bleiben erhalten).
  - `_row_to_profile()` migriert beim Lesen (E2, Single Source of Truth im Repo);
    `_ensure_schema_version()` migriert beim Schreiben (E4) -> keine neuen v1-Rows.
- `../../analytics/engine/service_selector_model.py`:
  - `resolve_valid_feature_ids(feature_ids) -> (valid, missing)` (E5, case-insensitiv,
    dedupliziert; `'native'`-Sentinel gilt als missing, B7).
- `../../analytics/engine/analytics_view_model.py`:
  - Additives Signal `missing_services_detected = Signal(list)`.
  - `selector_model`-Injektion (lazy Default); `_resolve_feature_ids()` / `_flatten_payload()`.
  - `_apply_profile()`: flacht v2-Sections verlustfrei, Resolver isoliert fehlende
    Services, Direkt-Write in `_params` (kein `set_feature_ids` -> kein Dirty, kein
    Doppel-Refresh, B4), Emit `missing_services_detected`.
  - `_current_payload()` baut das v2-Sectioned-Payload (E3).
  - `restore_workspace(payload)` (E7: params + layout, kein Dirty, Resolver-Pfad,
    refresh_all) + Property `workspace_layout`.
- `../../analytics/ui/analytics_win.py`:
  - `_keep_history_on_close = True` (E1, Dashboard-Fenster-Semantik; Kommentar des
    Bugfix 04.08.2026 angepasst).
  - Selector-Modell wird VOR dem VM erzeugt und injiziert (E5).
  - `label_missing_warning` + `_on_missing_services()` (Graceful Degradation); wird bei
    manueller Datenquellen-Aenderung und `save_profile()` versteckt.
  - `_save_workspace()` / `_restore_workspace()` (Payload `{"params", "layout"}`);
    `closeEvent()` ruft `_save_workspace()`; `_initial_load()` ruft nach `load_profiles()`
    `_restore_workspace()` (E7-Reihenfolge: Historie -> Profil -> Workspace).

**Validierung (headless, `../../test/test.py`):**
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

## 2. Core DB Layer (`../../analytics/engine/feature_store_reader.py`)
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

## 3. ViewModel Layer (`../../analytics/engine/analytics_view_model.py`)
- **State Parameters (`_params`)**: `heatmap_x_dim` ("date"), `heatmap_y_dim` ("hour"), `heatmap_field` ("confluence"), `heatmap_agg` ("CONFLUENCE_COUNT"), `candle_projection_enabled` (False), `zoom_x_range` ([0.0, 1.0]), `zoom_y_range` ([0.0, 1.0]), `selected_feature_ids` (List[str]).
- **Methods**: `set_heatmap_config()`, `set_heatmap_zoom()`, `set_candle_projection()`, `serialize_state()` (for profile/snapshot persistence).

## 4. UI Layer & Dual-Axis Zoom
- **`chk_candle_projection`**: Toggles semi-transparent OHLCV overlay from `market_data.duckdb`. Enabled only on temporal X-dimensions (`date`, `dow`, `hour`, `dow_hour`).
- **`slider_zoom_x` & `slider_zoom_y`**: Real-time viewport bounds scaling without DB requeries; syncs Heatmap cells and projected Candlesticks.

---

# Implementation Step-by-Step Guide

### Step 1: SQL Matrix Engine (`../../analytics/engine/feature_store_reader.py`)
1. Add `DIM_MAPPINGS` dict covering `date`, `dow`, `hour`, `dow_hour`, `timeframe`, `service_id`, `symbol`.
2. Implement `fetch_generic_heatmap(...)` with SQL `GROUP BY x_val, y_val` using DuckDB JSON extract (`feature_data->>'target_field'`) or `COUNT(DISTINCT feature_id)` for `CONFLUENCE_COUNT`.
3. Format output as dense N x M pivot matrix with bounds (`min_val`, `max_val`).

### Step 2: ViewModel Logic & State Management (`../../analytics/engine/analytics_view_model.py`)
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
3. Validate via headless tests (`py_compile` and `../../test/test.py`).

---

## 5. Review 09.08.2026: Konsistenz-, Vollständigkeits- & Korrektheits-Analyse

**Grundlage:** Abgleich des Kapitels 20.02 gegen den verbindlichen Ist-Code
(kein `../x_Exports.md`). Geprüfte Dateien: `../../analytics/engine/feature_store_reader.py`,
`../../analytics/engine/analytics_repository.py`, `../../analytics/engine/analytics_view_model.py`,
`../../analytics/engine/analytics_worker.py`, `../../analytics/ui/heatmap_page.py`,
`../../analytics/ui/analytics_win.py`, `../../analytics_profile_repository.py`,
`../../analytics/features/feature_builder.py` (OHLCV-Quelle).

### 5.1 Ist-Code-Abgleich (Befunde)

| # | Kapitel-Angabe 20.02 | Ist-Code (verbindlich) | Befund |
|---|----------------------|------------------------|--------|
| A1 | `analytics/gui/heatmap_widget.py` (§3/§4) | `../../analytics/ui/heatmap_page.py` (`HeatmapPage`, pyqtgraph `ImageItem`, viridis, Jump-to-Chart). Verzeichnis `analytics/gui/` existiert **nicht**. | **Pfadfehler** → E1 |
| A2 | `analytics/analytics_window.py` (§5) | `../../analytics/ui/analytics_win.py` (`AnalyticsWindow`, `PersistentWindow`, `INSTANCE_ID="win_analytics"`). | **Pfadfehler** → E1 |
| A3 | `DIM_MAPPINGS` + `fetch_generic_heatmap(...)` (§2) | existiert nicht. Ist: `fetch_heatmap(symbol, timeframe, metric, feature_id, feature_ids, limit)` mit **festen** Achsen DOW×Stunde (7×24), Metrik `"count"` \| numerischer JSON-Key (AVG via `TRY_CAST`). | **Neuimplementierung** (additiv) → E1 |
| A4 | VM-`_params` `heatmap_x_dim/y_dim/field/agg`, `candle_projection_enabled`, `zoom_x_range/y_range`, `selected_feature_ids` (§3) | existieren nicht. Ist-`_params` nur `heatmap_metric` + `feature_ids` (Liste). | **Neuimplementierung** (additiv); `selected_feature_ids` ist Redundanz zu `feature_ids` → E10 |
| A5 | `set_heatmap_config/set_heatmap_zoom/set_candle_projection/serialize_state()` (§3) | existieren nicht. Ist: `set_heatmap_metric()`; Persistenz via `_current_payload()` / `_apply_profile()` (+ `_flatten_payload`). | Methoden neu; `serialize_state()` = `_current_payload()`-Erweiterung |
| A6 | `export_profile_payload()` / `import_profile_payload()` (§5 Schritt 2) | existieren nicht. Ist: `_current_payload()` (v2, sectioned) / `_apply_profile()`. | Namenskorrektur → E1 |
| A7 | `chk_candle_projection`, `slider_zoom_x/y` (§4) | existieren nicht (HeatmapPage: nur Metrik-Combo + Doppelklick-Jump-to-Chart). | **Neuimplementierung** → E1/E8/E9 |
| A8 | "Auto-persists into active profile ... on profile change, window close, app exit" (§1) | Profil = **Option B – Explicit Save** (Persistenz NUR auf explizites `save_profile()`); automatisch persistiert wird nur der Workspace im `closeEvent` (`_save_workspace()`, 20.01 E1). | **Widerspruch** → E2 |
| A9 | "Schema v2.1" (§1) | `SCHEMA_VERSION_DEFAULT = 2` (`../../analytics_profile_repository.py`); es existiert KEINE v2.1. | Kein Bump nötig → E3 |
| A10 | `DIM_MAPPINGS["date"] = CAST(bar_time AS DATE)` (§2) | Wanduhr-Garantie (Invariante 7): `bar_time` ist Berlin-Wanduhr-encoded; DuckDB rechnet TIMESTAMPTZ in die Session-TZ (Berlin +1/+2h) um. | **DST-fragil**: Wanduhr 23:00–23:59 (Sommer) → Folgetag 01:00 → falsches Datum → E4 |
| A11 | `dow`/`hour`/`dow_hour` mit `bar_time AT TIME ZONE 'UTC'` (§2) | exakt das Muster von `fetch_heatmap()` / `fetch_recent_bar_time_for_cell()`. | **konsistent** ✓ |
| A12 | `feature_ids`-Filter (`WHERE feature_id IN (...)`) | `_apply_feature_filter()` (15.03-E) vorhanden. | **konsistent** ✓ |
| A13 | Aggregationen COUNT/AVG/SUM/MIN/MAX/CONFLUENCE_COUNT (§2) | COUNT + AVG-JSON-Muster (`TRY_CAST`) vorhanden; SUM/MIN/MAX/CONFLUENCE_COUNT neu. `HIT_RATE` undefiniert (kein Schwellwert spezifiziert). | Lücke → E5 |
| A14 | "Candle-Overlay ... local chart field context, isolated from global header dropdowns" (§1/§4) | OHLCV-Quelle: `market_data.duckdb`/`ohlcv_bars` (Muster `FeatureBuilder.load_ohlcv()`: Spalten `time, open, high, low, close, tick_volume`). Das Analytics-Fenster hat KEINEN lokalen Chart-Feld-Kontext (nur globale Header-Dropdowns Symbol/TF). | Interpretations-/Präzisierungsbedarf → E9 |

### 5.2 Entscheidungen (E1–E10)

- **E1 – Additive Implementierung & korrigierte Pfade:** Alle Ergänzungen erfolgen additiv
  (Open/Closed, Code-Preserving). Bestehende `fetch_heatmap()`/`get_heatmap()`/`HeatmapPage`
  bleiben unangetastet. Dateien: `../../analytics/engine/feature_store_reader.py` (additiv),
  `../../analytics/engine/analytics_repository.py` (additiv), `../../analytics/engine/analytics_view_model.py`
  (additiv), `../../analytics/engine/analytics_worker.py` (**neuer Query-Kind `QUERY_HEATMAP_GENERIC`**,
  bestehender `QUERY_HEATMAP` bleibt unverändert → kein Regressionsrisiko), neue UI-Datei
  **`../../analytics/ui/heatmap_widget.py`** (Korrektur: nicht `analytics/gui/`), Lifecycle in
  `../../analytics/ui/analytics_win.py`. Methodenbenennung wie Kapitel (`set_heatmap_config()` usw.)
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

1. **Schritt 1 (SQL-Matrix-Engine):** additiv in `../../analytics/engine/feature_store_reader.py`
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
3. **Schritt 3 (Heatmap/Confluence-Rendering):** NEUE Datei `../../analytics/ui/heatmap_widget.py`
   – diskrete Konfluenz-Skala (E7), viridis für Wert-Metriken, Einbettung als Modus in die
   bestehende `../../analytics/ui/heatmap_page.py` (additiv, Dow×Hour bleibt Standard-Modus),
   Slider-Bindung an `setXRange`/`setYRange` (E8).
4. **Schritt 4 (Candle-Overlay):** `get_ohlcv_snapshot()` (E9), `chk_candle_projection`
   nur bei X=`date` aktiv, semi-transparente Candles an die Heatmap-Spalten gebunden.
5. **Schritt 5 (Lifecycle):** `../../analytics/ui/analytics_win.py` – Erweiterung von
   `_save_workspace()`/`_restore_workspace()` um die Heatmap-Config; KEIN
   `aboutToQuit`/`save_last_snapshot`-Neu-Hook (E2); Validierung headless via
   `py_compile` + `../../test/test.py` (Logik-/DB-Tests, keine UI-Tests).

---

## 5.5 Umsetzungs-Log 09.08.2026 (Kapitel 20.02 umgesetzt)

**Umgesetzte Dateien (additiv, Open/Closed – Bestandscode unveraendert):**

| Datei | Änderung |
|-------|----------|
| `../../analytics/engine/feature_store_reader.py` | + `DB_MARKET`, `DIM_MAPPINGS`, `HEATMAP_DIMENSIONS`, `HEATMAP_AGGREGATIONS`, `MAX_HEATMAP_CELLS`, `OHLCV_SNAPSHOT_LIMIT`, `_format_dim_value()`, `fetch_generic_heatmap()`, `_empty_generic_heatmap()`, `fetch_ohlcv_snapshot()` |
| `../../analytics/engine/analytics_repository.py` | + `get_generic_heatmap()` (inkl. `metrics` + defensives `field`-Fallback), `get_ohlcv_snapshot()` |
| `../../analytics/engine/analytics_worker.py` | + `QUERY_HEATMAP_GENERIC`, `QUERY_OHLCV` + Dispatch |
| `../../analytics/engine/analytics_view_model.py` | + `_params`: `heatmap_x_dim/y_dim/field/agg`, `candle_projection_enabled`, `zoom_x_range/y_range`; + `request_heatmap_generic()`, `request_ohlcv_snapshot()`, `set_heatmap_config()`, `set_heatmap_zoom()`, `set_candle_projection()`, `_clamp_zoom()`, `_apply_heatmap_section()`; `refresh_all()` + `QUERY_HEATMAP_GENERIC`; `_current_payload()` + `charts.heatmap`; `_current_params()`-Zweige |
| `../../analytics/ui/heatmap_widget.py` | **NEU:** `HeatmapWidget` – generische Heatmap (dims/agg/field), diskrete Konfluenz-Skala (E7), viridis für Wert-Metriken, Zoom-Slider (E8), Preis-Strip (E9) |
| `../../analytics/ui/heatmap_page.py` | + Modus-Combo (`standard` \| `generic`), `QStackedWidget`, `mode_id`/`set_mode()`, `request_data()` modus-abhängig |
| `../../analytics/ui/analytics_win.py` | `_save_workspace()` + `layout.heatmap_mode`; `_restore_workspace()` wendet `heatmap_mode` an |
| `../../test/test.py` | + Tests 37 a1–j2 (Reader/Repository/Worker/ViewModel, headless, temporäre DuckDBs in `../../test`) |

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
- `py_compile` auf allen 7 geänderten Python-Dateien + `../../test/test.py`: PASS.
- `../../test/test.py`: **30 neue Checks 37 a1–j2 alle PASS** (Matrix-Form/-Werte,
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

**Validierung:** `../../test/check_bugfix_0808.py` 9/9 PASS; `../../test/test.py` Block 38 (9 Checks) ergänzt.

### Bugfix B (09.08.2026, Commit `3e7c220`): Seiten-Navigation zeigt immer nur die Tabelle

| # | Symptom | Ursache | Fix |
|---|---------|---------|-----|
| B1 | Egal welcher Menüeintrag im Analytics-Fenster (Tabelle/Heatmap/Verteilung/Scatter) – sichtbar blieb immer die Tabelle | Alt-Bug seit Phase 15.03: `AnalyticsWindow._on_page_changed` rief nur `page.request_data()` auf, **ohne** `self.pages_stack.setCurrentIndex(row)` – der Stack blieb dauerhaft auf Index 0 | `_on_page_changed` (analytics/ui/analytics_win.py): `self.pages_stack.setCurrentIndex(row)` VOR `request_data()`; ungültige Rows bleiben ohne Crash |

**Validierung:** `../../test/check_page_nav.py` 7/7 PASS (Stack folgt Row 1/3/0/2, ungültige Row kein Crash, `request_data` je Page genau 1x).

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
(kein `../x_Exports.md`, keine `../Current`). Geprüfte Dateien:
`../../analytics/engine/feature_store_reader.py`, `../../analytics/engine/analytics_view_model.py`,
`../../analytics/ui/heatmap_widget.py`, `../../analytics/ui/heatmap_page.py`,
`../../analytics/engine/service_selector_model.py`, `../../serviceui/service_selector_dialog.py`,
`../../analytics/ui/analytics_win.py`.

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
  `../../test/test.py` Block 37 d1/d2 (dow_hour) und `../../test/check_heatmap_bugfix.py`
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
| `../../analytics/engine/feature_store_reader.py` | `dow_hour` entfernen (DIM_MAPPINGS/HEATMAP_DIMENSIONS/_format_dim_value/_axis_coords/Docstrings); Mo–Fr-Filter für `dow` in `fetch_generic_heatmap`; `DOW_WEEK_LABELS` |
| `../../analytics/ui/heatmap_widget.py` | Datums-Formatter 5 Stufen (E1); `_DIM_LABELS["hour"]="Tageszeit"` (E2); feste Skalen hour `[0,24)` / dow `[1,6)` (E3/E5); UTC-Offset-Label (E4); `dow_hour` entfernen (E6); Overlay-Zoom-Lock via `setXLink` (E7); Service-Label-Resolver + Combo-Mindestbreite (E8) |
| `../../analytics/engine/analytics_view_model.py` | `_sanitize_dim()` (dow_hour → hour) in `_apply_heatmap_section`/`restore_workspace`/`set_heatmap_config` (E6); `resolve_service_label()` (lazy `_selector_model`, E8) |
| `../../test/test.py` | Block 37 d1/d2 (dow_hour) → neue feste Skalen-Checks |
| `../../test/check_heatmap_bugfix.py` | dow_hour-Checks ersetzen/anpassen |

### 2.4 Validierung (headless, nach Freigabe)

- `py_compile` auf den geänderten Python-Dateien.
- `../../test/test.py` Block 37 (angepasst) + isolierter Check in `../../test`.
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
E1–E8-Checks sind in `../../test/check_heatmap_bugfix.py` integriert (feste Skalen,
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
| H7 | **WAL-Guard** (Start-Abbruch, Zusatz) | `DbPool._open_with_wal_recovery()`: bei `duckdb.InternalException` mit "Failure while replaying WAL" wird die korrupte WAL unter `*.duckdb.wal.corrupt_<Zeitstempel>` weggesichert und der Connect erneut versucht (wiederkehrendes Start-Problem unter Windows nach hartem Beenden). `../../.gitignore` um `*.duckdb.wal.corrupt_*` erweitert |

### Bewusst NICHT geändert
- `fetch_ohlcv_snapshot()` / `QUERY_OHLCV` (Alt-Aufrufer/Tests)
- `HeatmapPage`-Standard-Modus (Dow×Stunde) unangetastet
- `../x_Exports.md` (nicht committet)

### Validierung (headless, keine UI-Tests)
- `py_compile` auf allen 8 geänderten Dateien: PASS
- `../../test/check_heatmap_bugfix.py`: **34/34 PASS** (Reader x_axis/y_axis inkl. Mitternachts-Epochs + Tagesabständen, `fetch_daily_ohlc` mit Wanduhr-Mitternacht + OHLC-Konsistenz, `limit=None` → alle Daten/2083 Tage, Worker-Dispatch `QUERY_DAILY_OHLC`, Axis-Ticks date 100T/3h/90s → 1T/1h/30s + Format TT.MM.JJ/HH:MM, hour/dow_hour/kategorial-Ticks, Widget-Offscreen: Overlay im selben Canvas, X-Bounds = Epochs ± halber Tag, Y-Bounds = −0,5..1,5, Cleanup)
- `../../test/test.py` Blöcke 37/38: alle PASS (nur 6 bekannte offscreen-Geometrie-Fehler P2/P5/H3–H5/H7, unabhängig von dieser Umsetzung)
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
- `../../test/check_heatmap_bugfix.py`: **59/59 PASS** – DB-Tests auf **synthetische
  DuckDBs in `../../test`** umgestellt (`tmp_hm_*.duckdb`), da die echten
  `data/*.duckdb` bei laufender App exklusiv gesperrt sind (Windows-Lock).
  Neue Checks: Meldung 1 (hour-Ticks in `[0, 24)` bei Rauszoom, kein
  24er-Duplikat, `_format(-1/24)` leer, Teilbereich unverändert), Meldung 2
  (dow-Ticks in `[1, 6)`, `_format(0/6)` leer), Meldung 3 (Combo ≥ 320 px,
  `feature_keys_by_service`, `field_sources` inkl. geteiltem Key → beide
  Services, `_field_label` ohne `srv_`, Combo-Text `'{Name} / {Key}'`,
  Combo-DATA = Roh-Key).
- `../../test/test.py`: unverändert (kein Kontakt zu dieser Umsetzung; 6 bekannte
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
- `../../analytics/ui/heatmap_widget.py` – LWC-Datums-Skala (`_DATE_TARGET_PX`,
  `_MONTHS_SHORT`, `_lwc_date_ticks`, `_date_marks`, `_select_date_marks`,
  Per-Tick-`_format`), `_field_label` → `resolve_service_display_name`
- `../../analytics/engine/analytics_view_model.py` – neuer Resolver
  `resolve_service_display_name()` (lazy `_selector_model`, Muster
  `resolve_service_label`)

**Validierung (headless, keine UI-Tests):**
- `py_compile` auf beiden geänderten Python-Dateien: PASS.
- `../../test/check_heatmap_bugfix.py`: **alle PASS** – alte Spacing-Format-Checks
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
- `../../analytics/engine/feature_store_reader.py` – `feature_keys_by_service()`:
  neue `feature_id`/`feature_ids`-Parameter + `_apply_feature_filter`
- `../../analytics/engine/analytics_repository.py` – `get_generic_heatmap()`:
  feature_ids-Filter für `metrics`/`field_sources` (`avail_filtered`,
  Fallback ungefiltert bei leer)
- `../../analytics/engine/analytics_view_model.py` – `resolve_service_display_name()`
  (Service-Name direkt aus `plugin_id`, Pretty-Fallbacks)
- `../../analytics/ui/heatmap_widget.py` – `_field_label` (1 Service → Name;
  mehrere Services → Roh-Key), Zoom-Richtung (`_set_zoom_range`/
  `_set_zoom_slider`/Initialwert/Tooltip), date-Label 'Datum/Zeit' +
  `enableAutoSIPrefix(False)` in `_HeatmapAxis`

**Validierung (headless, keine UI-Tests):**
- `py_compile` auf allen 4 geänderten Python-Dateien: PASS.
- `../../test/check_heatmap_bugfix.py`: **alle PASS** – `resolve_service_display_name`
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
- `../../test/test.py`: unverändert (kein Kontakt zu dieser Umsetzung).
- Manueller Funktionstest der GUI erfolgt durch den Anwender.


---

# 20.03 Service-Output-Schema & Resultatfelder-Dokumentation im Service-Picker

## 1. Architektur & Standards (E1, E4, E5)
- **Modul-Konstante & Property (E1)**: Definition als private Modul-Konstante (z. B. `_GRID_OUTPUT_SCHEMA`) am Dateianfang des Plugins. Export über Property `@property def output_schema(self) -> Dict[str, Dict[str, Any]]: return {k: dict(v) for k, v in _GRID_OUTPUT_SCHEMA.items()}`.
- **Basisklasse (`base_plugin.py`)**: `@property def output_schema(self) -> Dict[str, Dict[str, Any]]: return {}` als abwärtskompatibler Default.
- **JSON-Scope (E4)**: `bar_time` NICHT im `output_schema` deklarieren (ist native DB-Spalte, kein JSON-Key).
- **Typen (E5)**: Freie String-Typen unterstützen (z. B. `"bool"`, `"float"`, `"list[float]"`).

## 2. Abdeckung Core-Plugins (E6)
Befüllung der Modul-Konstante `_*_OUTPUT_SCHEMA` in allen 8 aktiven Services unter `../../analytics/features/definitions`:
- `srv_grid_lines.py`, `srv_proximity.py`, `srv_swing_structure.py`, `srv_swing_momentum.py`, `srv_swing_volume_profile.py`, `srv_trend_breakout.py`, `srv_trend_hma_pivot.py`, `srv_trend_regime.py`.

## 3. UI-Anzeige im Parameter-Panel (E2, E7) (`../../serviceui/param_columns.py`)
- **Verortung (E7)**: Integration in `_update_service_info_label` / `_build_service_column` unterhalb der allgemeinen Beschreibung.
- **Gruppierung/Filter (E2)**:
  - **Haupt-Resultatfelder**: Standardmäßig eingerückt anzeigen (`└── 🔹 {field_name} ({type}): {description}`).
  - **Technische Felder** (mit `"technical": True` im Schema, z. B. `calculation_status`, `confirmation_lag_bars`): In kompakter, kleinerer Schrift oder ausklappbarem Unterblock `🔧 System-Metrik` platzieren.
- **Read-Only**: Strikte schreibgeschützte Formatierung.

## 4. Implementation Steps
1. **Base-Plugin (`../../analytics/features/plugins/base_plugin.py`)**: Add `@property def output_schema`.
2. **Plugins (`analytics/features/definitions/srv_*.py`)**: Define `_*_OUTPUT_SCHEMA` & property across all 8 plugins.
3. **UI (`../../serviceui/param_columns.py`)**: Render `output_schema` indented below description text field.
4. **Validation (`../../test/test.py`)**: Headless Test verifying `output_schema` retrieval for all registered plugins + `py_compile`.


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
- **`../../serviceui/param_columns.py`**:
  - Output-Schema-Block aus `_update_service_info_label` entfernt (Punkt 1).
  - Neue Sektion **UNTER** dem Info-Label in `_build_service_column`: Header
    `📊 Resultatfelder (Output-Schema):`, je Haupt-Resultatfeld eine Zeile
    (`🔹 name (type)`) mit 16-px-`i`-Button → `_show_output_field_info`
    (modaler `QDialog` mit Name/Typ/Beschreibung/Service-Referenz).
    Technische Felder (`technical: True`) kompakt in dezentem Block
    `🔧 System-Metrik: …` (Semikolon-getrennt, ohne Beschreibung).
  - Neues State-Dict `self._service_output_schemas[iid]` (Reset in
    `_clear_service_columns`); `QDialog`-Import ergänzt.
- **`../../serviceui/master_tree.py`**: `INFO_BUTTON_TEXT` von `"ℹ"` (U+2139) zurück auf
  ASCII `"i"` (Punkt 3) – inkl. Begründungskommentar.

## 3. Validierung (headless, keine UI)
- `py_compile` auf beiden geänderten Dateien: OK.
- `../../test/check_output_schema.py`: ALL CHECKS PASSED (8 Services, Main/Tech-Split).
- Neuer Testblock `20.03-Bugfix` in `../../test/test.py`: `INFO_BUTTON_TEXT` = ASCII `'i'`
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
   - Neuer headless Regressions-Test `../../test/check_dialog_host.py` (Host-Spaltenbau
     inkl. Resultatfelder-Header/System-Metrik/i-Buttons): PASS.

2. **`b772c93` – 'QDialog.__init__ called with wrong argument types' beim
   i-Button der Ergebnisparameter**:
   - Ursache: `_show_output_field_info` erzeugte `QDialog(self)` – `self` ist im
     Dialog-Kontext der `_DialogParamHost` (kein QWidget) → TypeError.
   - Fix: Eltern-Widget robust aufgelöst: `self` falls QWidget, sonst
     `self._dialog` (echtes Dialog-Fenster des Hosts), sonst `None`.
   - `../../test/check_dialog_host.py` erweitert (mockt `QDialog.exec`, prüft
     Eltern-Auflösung + None-Fallback): ALL PASS.


---

# 20.03.02 Multi-Select Resultatparameter, Dynamic Checkable ComboBox & Info-Fixes (09.08.2026, 20:15; Entscheidungen F1–F7 bestätigt 20:21)

## 1. Regeln & Invarianten
* **Code-Style:** Exakt **4 Leerzeichen** Einrückung, **1 Leerzeile** zwischen
  Methoden/Funktionen (PEP8, Phase-19-Invariante 3).
* **Testing:** **STRIKT HEADLESS** via `py_compile` & `../../test/test.py`
  (`QApplication.exec()` STRIKT VERBOTEN – Phase-19-Invariante 2). Alle neuen
  Test-Skripte/Test-DBs gehören nach `../../test` (Invariante 10).
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
| 2 | `../../analytics/engine/feature_store_reader.py` | ✅ VORHANDEN | `feature_keys_by_service()` nimmt `feature_ids` (Z. 430) und wendet `_apply_feature_filter` an (Z. 462). Commit `4648399`. |
| 3 | `../../analytics/engine/analytics_repository.py` | ✅ VORHANDEN | `get_generic_heatmap()` baut `field_sources` + `avail_filtered` strikt über `feature_ids` (Z. 150–176). Commit `4648399`. |
| 4 | `../../analytics/engine/analytics_view_model.py` | 🟡 DELTA | Leer/`"none"` → `"Allgemein"`, Title-Case-Fallback ✅. **`"native"` → `"Native"` (Plan: `"Allgemein"`)** – Erweiterung offen (F3). |
| 5 | `../../analytics/engine/description_dialog.py` | ✅ VORHANDEN | `_render_html()` rendert `header_line` fett + `<p>&nbsp;</p>` (Z. 285–290); `ServiceDescriptionEditDialog` ebenso. |
| 6 | `../../serviceui/master_tree.py` + `service_selector_widget.py` | 🟡 DELTA | Emit + Re-Emit vorhanden (ASCII `"i"`). **`service_selector_dialog.py` verbindet `info_requested` NICHT** → i-Button im ServicePicker wirkungslos. |
| 6b | `../../serviceui/param_columns.py` | 🔴 NEU | UI-Umbau Resultatfelder (einzelner `btn_output_params_info` statt Per-Zeile-i-Buttons) – betrifft auch `_DialogParamHost`. |
| 1 | `../../analytics/ui/common.py` | 🔴 NEU | `CheckableComboBox` fehlt vollständig. |
| 7 | `../../analytics/ui/heatmap_widget.py` | 🟡 KORRIGIERT | **`combo_field` liegt in `heatmap_widget.py` (Z. 496), NICHT in `heatmap_page.py`** – Plan-Verortung angepasst. |
| 7b | `../../analytics/engine/analytics_view_model.py` | ✅ ENTSCHIEDEN | `set_heatmap_config()` bleibt Einzel-Feld (`field: str`); Multi-Select steuert `feature_ids` (F1c/F2, §6). |

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

### Schritt 1: `../../analytics/ui/common.py` – `CheckableComboBox` (NEU)
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
Regressions-Absicherung in `../../test/test.py` (Filter-Check).

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

### Schritt 7: `../../analytics/ui/heatmap_widget.py` (KORRIGIERTE Verortung + F1c/F2/F7 ✅)
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

## 7. Verification Checklist (`../../test/test.py`, headless)

- [x] **Syntax-Check:** `py_compile` auf allen geänderten Dateien
      (`common.py`, `analytics_view_model.py`, `param_columns.py`,
      `service_selector_widget.py`, `service_selector_dialog.py`,
      `service_win.py`, `heatmap_widget.py`, `../../test/check_dialog_host.py`,
      `../../test/test.py`) – OK. Unveränderte Dateien (`feature_store_reader.py`,
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
      Spaltenbau fehlerfrei (Regressions-`../../test/check_dialog_host.py`,
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
* Die 6 vorbestehenden Fehlschläge in `../../test/test.py` (P2/P5/H3–H7,
  Fenster-Persistenz-Geometrie) sind NICHT Bestandteil dieser Phase.
* Entscheidungen F1–F7 sind vom Anwender am 09.08.2026, 20:21 bestätigt und
  in §6 verbindlich dokumentiert.

## 9. Implementierungs-Log (09.08.2026, ~20:55; Commit `1324d95`, Tag `20.03.02`)
* **`../../analytics/ui/common.py`** – `CheckableComboBox` (NEU, F1): `QComboBox` mit
  `QStandardItemModel`, Checkbox-Spalte, EventFilter hält Pop-up bei
  Checkbox-Klick offen; API `add_checkable_item(display_text, user_data,
  checked)`, `checked_data() -> List[str]`, `set_checked_data()`, Signal
  `selection_changed(list)`.
* **`../../analytics/engine/analytics_view_model.py`** – F3: `resolve_service_display_name`
  mappt `"native"`/`native_*`/`"none"`/leer → `"Allgemein"` (statt Title-Case-
  Fallback für `native`).
* **`../../serviceui/service_win.py`** – F5: Info-Badge-Header vereinheitlicht
  (`📌 im … | 🟢 aktiv in …` bzw. `⚪ inaktiv`, Sets mit ` + `).
* **`../../serviceui/service_selector_dialog.py`** – F4: Import + Verdrahtung
  `info_requested`/`category_info_requested` des eingebetteten Widgets;
  Slots `_on_info_requested`/`_on_category_info_requested` öffnen Read-Only
  `ServiceDescriptionDialog.from_plugin()`/`from_set()` mit
  `_info_header_line`/`_info_set_header_line`.
* **`../../serviceui/service_selector_widget.py`** – F4: neues Signal
  `category_info_requested` + Re-Emission in beiden Modi (Achtung: gemischte
  Line-Endings, nur per Python-Skript editierbar).
* **`../../serviceui/param_columns.py`** – F6: Per-Zeile-i-Buttons entfernt, EIN
  `btn_output_params_info` hinter `📊 Resultatfelder:`; neuer Slot
  `_show_output_params_info()` zeigt Hauptfelder + Sektion
  `🔧 System-Metriken` (`technical: True`); `_DialogParamHost`-Kompatibilität
  beibehalten.
* **`../../analytics/ui/heatmap_widget.py`** – F1c/F2/F7: `_combo_field` ist jetzt
  `CheckableComboBox`, userData `"{service_id}|{key}"`; Multi-Select →
  `set_feature_ids(...)` (Quellen-Filter); `set_heatmap_config`-Signatur
  unverändert; Feld-Combo bei `COUNT`/`CONFLUENCE_COUNT` deaktiviert.
* **Validierung:** `py_compile` auf allen geänderten Dateien OK; neuer
  20.03.02-Testblock in `../../test/test.py` (Checks `a`–`o`, 15 Stück);
  `../../test/check_dialog_host.py` (16 Checks); isolierte Verifikationsskripte
  (danach gelöscht, test/-Cleanup) – ALLE PASS. Kein Regressionstest, keine
  UI-Ausführung (Phase-19-Invariante 2).

---

# 20.03.03 Dropdown-Eindeutigkeit & Sammel-Auswahl (finale Spezifikation 20.03.02, 09.08.2026, ~21:15)

## 1. Regeln & Invarianten
* **Code-Style:** Exakt 4 Leerzeichen, 1 Leerzeile zwischen Methoden (PEP8,
  Phase-19-Invariante 3). Additive Aenderungen (Invariante 11).
* **Testing:** STRIKT HEADLESS via `py_compile` & `../../test/test.py`
  (`QApplication.exec()` VERBOTEN – Invariante 2); neue Test-Skripte/DBs nach
  `../../test` (Invariante 10).

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

### Schritt 1: `../../analytics/ui/common.py` – `add_header_item()` (additiv)
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

### Schritt 2: `../../analytics/ui/heatmap_widget.py` – Befuellung (`_sync_combos_from_payload`)
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

## 6. Verification Checklist (`../../test/test.py`, headless)

- [x] **Syntax-Check:** `py_compile` auf `common.py`, `heatmap_widget.py` (und
      `../../test/test.py`) – OK.
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
- [x] **Regression:** `../../test/check_dialog_host.py` bleibt PASS (16 Checks,
      unveraenderte Pfade); 20.03.02-Checks `a`-`o` + `checked_data`/
      `set_checked_data`-API isoliert gruen (28 Checks).

## 7. Hinweise
* Entscheidungen Q1-Q5 vom Anwender am 09.08.2026 bestaetigt (siehe Antwort-
  Nachricht). Implementierungs-Log siehe §8.
* Keine UI-Tests, kein Regressionstest (Invariante 2).

## 8. Implementierungs-Log (09.08.2026, ~21:40; Commit `84f02df`, Tag `20.03.03`)
* **`../../analytics/ui/common.py`**:
  * `add_header_item()` (Q4): deaktivierte, graue, fette Trenn-/Kopfzeile
    (`Qt.NoItemFlags`, `userData=None`) – erscheint weder auswaehlbar noch in
    `checked_data()`.
  * Klick-Tracking (Q5): `_last_click_index` im EventFilter (Popup-Viewport)
    + Getter `last_click_index()` – Grundlage der XOR-Aufloesung (Sammel vs.
    Einzel); `-1` = programmatischer Wechsel (keine Aufloesung).
* **`../../analytics/ui/heatmap_widget.py`**:
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
* **Validierung:** 28 isolierte Checks in `../../test` (Q1-Q5, E6, Randfaelle,
  20.03.02-API-Regression) + `../../test/check_dialog_host.py` (16 Checks) – ALLE
  PASS; neuer 20.03.03-Testblock (9 Checks `a`-`i`) in `../../test/test.py`;
  Temp-Skripte geloescht (test/-Cleanup). Kein UI-Test, kein Regressionstest.


---

# Phase 20.04: Parameter-Varianten, Instanziierung, Hash-IDs & Archivierung

## 1. Architektur & Invarianten
* **Code-Style:** Exakt 4 Leerzeichen EinrÃ¼ckung, 1 Leerzeile zwischen Methoden.
* **Testing:** **STRIKT HEADLESS** via `py_compile` & `../../test/test.py` (`QApplication.exec()` STRIKT VERBOTEN).
* **Entkopplung:** MVVM & IoC. MasterTree im `ServiceWindow` gekoppelt via `EventBus` (20.02/20.03).
* **Datenbank-Konsistenz:** Single Source of Truth im `ServiceSetRepository` / `FeatureStoreReader`.

---

## 1a. VollstÃ¤ndigkeitsprÃ¼fung & Bestandsaufnahme (09.08.2026, Code-Inspektion)

Verifiziert gegen den tatsÃ¤chlichen Quellcode (keine UI-AusfÃ¼hrung):

| Befund | Status | Details |
|---|---|---|
| Referenzierte Dateien existieren | âœ… | `service_models.py` (`ServiceInstanceConfig` TypedDict, total=False), `tree_builder.py` (`build_tree`), `service_selector_model.py` (`ServiceSelectorModel.build_tree`, `resolve_display_names`, `resolve_valid_feature_ids`), `analytics_view_model.py` (`resolve_service_display_name`, `set_feature_ids`), `feature_store_reader.py`, `master_tree.py`, `feature_builder.py` (`store_plugin_payload`). |
| `indicator_presets` | âœ… | Existiert in `../../state_manager.py` (PK `indicator_id, preset_name` + `plugin_id`/`version`/`is_active_batch`). |
| `service_sets` | âœ… | `ServiceSetRepository` (PK `set_id`, JSON-Definition, Trash/History-Tabellen). |
| `feature_store`-Schema | âœ… | PK `(symbol, timeframe, bar_time, feature_id)`; `feature_id` = `plugin_id` (Sentinel `'native'`); `created_at` mit `now()` beim Upsert. **KEINE `instance_hash`-Spalte.** |
| MasterTree-Node-Typen | âœ… | `TYPE_PLUGIN` / `TYPE_SERVICE` â€“ heute **keine** Parent-Child-Hierarchie (Service â†’ Clones); Plugins sind flache BlÃ¤tter. |
| `ServiceDescriptionEditDialog` | âœ… | Arbeitet bereits mit `ServiceInstanceConfig.description`; `doc_log` analog ergÃ¤nzbar. |
| Schreib-/Lese-Trennung | âœ… | Lesen: `FeatureStoreReader` (read-only); Schreiben: `FeatureBuilder.store_plugin_payload` (aufgerufen von `run_worker.py`, `historical_scanner.py`, `live_analyzer.py`). |
| Lese-Pfad | âœ… | `_apply_feature_filter` (WHERE feature_id IN â€¦), `feature_keys_by_service`, `fetch_last_execution_dates`, `available_feature_keys`, `set_feature_ids`/`resolve_valid_feature_ids` arbeiten ALLE mit `plugin_id` als `feature_id`. |

**Gefundene LÃ¼cken/Konflikte im Kapitel (vor den Entscheidungen):**
1. `instance_hash` vs. `feature_id` â€“ unklar, wo der Hash im `feature_store` landet (fehlende Spalte).
2. `userData "{instance_hash_oder_id}|{key}"` kollidiert mit 20.03.02/03 (`{plugin_id}|{key}`, `ALL|{key}` + `field_sources`-Expansion).
3. Hash-Definition ohne `lookback`, obwohl Â§2 den Clone mit `lookback` beschreibt â†’ Kollisionsgefahr.
4. `json_sorted(params)` nicht definiert (numpy-Typen/None/verschachtelte Dicts).
5. `purge_instance_data` im `FeatureStoreReader` â†’ verletzt Read-only-Invariante.
6. Archiv-Persistenz und Archiv-Einheit undefiniert.
7. `indicator_presets` vs. Service-Instanzen (Geltungsbereich unklar).
8. Kein Varianten-Erzeugungspfad (Clone/Duplikat) definiert.
9. Hash-Ãœbergabe an den Writer (`store_plugin_payload`) fehlt.

---

## 1b. Entscheidungen Q1â€“Q9 (verbindlich, Anwender 09.08.2026)

| ID | Entscheidung |
|---|---|
| Q1 | **`feature_id` bleibt `plugin_id`; NEUE additive Spalte `instance_hash VARCHAR` in `feature_store`.** Zero-Regression: Lese-Pfad/Alt-Profile bleiben intakt. |
| Q2 | **Dropdown:** `userData` primÃ¤r `{plugin_id}|{key}`; `instance_hash` optional im Label. Das ViewModel lÃ¶st selektierte Hashes transparent auf `feature_ids` (plugin_ids) auf. Anzeige: `{Service} ({Preset-Name}) / {Parameter}`. |
| Q3 | **`lookback` BEWUSST NICHT im Hash** â€“ Ergebnis einer Kerze hÃ¤ngt nur von Algorithmus-Logik + `params` ab; `lookback` ist ein Laufzeit-Fenster (Performance) und kein Inhalts-IdentitÃ¤tsmerkmal. |
| Q4 | **Typ-Sanitizer vor dem Hashing:** Rekursive Umwandlung in native Python-Typen (`int`, `float`, `str`, `bool`), `None`-Handling, dann `json.dumps(params, sort_keys=True)` (kanonisch). |
| Q5 | **`purge_instance_data` in `../../analytics/features/feature_builder.py`** (Schreib-/Store-Kontext). `FeatureStoreReader` bleibt 100 % read-only. Kein neues Repository. |
| Q6 | **`is_archived: bool` in `ServiceInstanceConfig`** + dynamischer `ðŸ“ Archiv`-Ordner im `tree_builder` (`Qt.ItemIsUserCheckable = False`). Archiv-Einheit: einzelne Instanz/Clone ODER ganze Sets. |
| Q7 | **Geltungsbereich:** PrimÃ¤r Service-Instanzen (`service_sets` + `feature_store`), additiv `indicator_presets` (Archivierung â‡’ `is_active_batch = False`, aus Scans isoliert). Â§5B adressiert beide Stores. |
| Q8 | **Varianten-Erzeugung:** KontextmenÃ¼ `Als Variante duplizieren` (Service-Knoten) + Set-Editor `Service-Instanz clonen`. Neue `instance_id`, kopierte Params, Ã¶ffnet Parameter-Editor, berechnet neuen `instance_hash`. |
| Q9 | **Writer-Ãœbergabe:** `SetEvaluator` / `HistoricalScanner` / `LiveAnalyzer` Ã¼bergeben `instance_hash` an `store_plugin_payload` â†’ neue Spalte, damit Signal-/Metrik-Ergebnisse verschiedener Clones in DuckDB getrennt und einzeln auswertbar sind. |

---

## 2. Parent-Child Modell & Hash-ID (Model C)
* **Template (Parent):** Reines Code-Template (`PluginFeature` / `plugin_id`). Nicht direkt als Instanz ausfÃ¼hren[cite: 4].
* **Executable Clone (Child):** AusfÃ¼hrbare Instanz = `plugin_id` + `params` + `lookback`[cite: 4].
* **Deterministic Hash (`instance_hash`):**
  - Short-Hash (8-stellig, hex): `SHA256(plugin_id + json_sorted(sanitized_params))[:8]`[cite: 4].
  - **`lookback` BEWUSST NICHT im Hash (Q3):** Das Kerzen-Ergebnis hÃ¤ngt nur von
    Algorithmus-Logik + `params` ab; `lookback` ist ein Laufzeit-Fenster
    (Performance) und kein Inhalts-IdentitÃ¤tsmerkmal.
  - **Typ-Sanitizer vor dem Hashing (Q4):** Rekursive Umwandlung in native
    Python-Typen (`int`/`float`/`str`/`bool`, `None`-Handling, numpy â†’ Python)
    und erst dann `json.dumps(params, sort_keys=True)` als kanonische
    Serialisierung â€“ sonst `TypeError: Object of type int64 is not JSON
    serializable` und instabile Hashes bei verschachtelten Dicts.
  - Stabile Identifikation im `feature_store` fÃ¼r Multi-Varianten-Statistiken[cite: 4]
    (neue additive Spalte `instance_hash`, Q1).
* **Negativ-Wissen (`doc_log`):** Freitextfeld pro Instanz/Preset fÃ¼r Dokumentation von FehlschlÃ¤gen[cite: 4] (z. B. *"85% false signals in chop markets"*)[cite: 4].

---

## 3. MasterTree Hierarchie & Archiv-Logik

[MasterTree (Active)]
 â”œâ”€â”€ ðŸ“ [Swing Algos]
 â”‚     â””â”€â”€ âš™ï¸ [srv_swing_pivot]
 â”‚           â”œâ”€â”€ ðŸŸ¢ [M15_Fast] (hash: #a91f3b) [X]
 â”‚           â””â”€â”€ ðŸŸ¢ [H1_Slow]  (hash: #b82e4c) [X]
 â””â”€â”€ ðŸ“ [Archiv (Checkboxes Disabled)]
       â””â”€â”€ ðŸ”´ [srv_breakout_v1] (Archiviert)
             â”œâ”€â”€ ðŸ“ Doc Log: "85% false signals in chop markets"
             â””â”€â”€ ðŸ”¹ [Default] (hash: #c73d5d) [ ] (Disabled)


### Safety & Checkbox-Regel (Archive Safety)

* Knoten im Archiv-Ordner besitzen das Flag `Qt.ItemIsUserCheckable = False`.
* Checkboxen sind schreibgeschÃ¼tzt und ausgegraut. Archivierte Hashes/IDs werden vom `AnalyticsViewModel` und von Scans (`HistoricalScanner` / `LiveAnalyzer`) strikt ignoriert.

---

## 4. Multi-Select Dropdown Integration (Kopplung mit 20.03.02/20.03.03)

* **Label-Format:** `{Service-Name} ({Preset}) / {Parameter}` (z. B. `Swing Pivot (M15_Fast) / pivot_level`).
* **UserData-Key (Q2):** PrimÃ¤r `"{plugin_id}|{param_key}"` (kompatibel zu
  20.03.02/03 inkl. `ALL|{key}`-Sammel-EintrÃ¤gen und `field_sources`-Expansion).
  `instance_hash` ist **optional im Label** (`{Preset}`), NICHT im `userData`.
* **Hash-AuflÃ¶sung (Q2):** Das `AnalyticsViewModel` lÃ¶st selektierte Hashes
  transparent auf `feature_ids` (plugin_ids) auf â€“ der Filter bleibt
  `WHERE feature_id IN (â€¦)` auf `plugin_id`-Basis.
* **Multi-Clone-Vergleich:** Erlaubt den direkten Vergleich verschiedener Parameter-Varianten desselben Services in Heatmap, Scatter und Tabellen (getrennt Ã¼ber die `instance_hash`-Spalte im `feature_store`, Q9).

---

## 5. Wartung & KontextmenÃ¼-Aktionen (Archiv)

### A. "Delete Data Only" (Daten bereinigen)

* LÃ¶scht in `analytics.duckdb` alle `feature_store`-Rows mit `instance_hash = <hash>`
  (Q1: neue Spalte; `feature_id` bleibt `plugin_id` und wird NICHT gelÃ¶scht).
* Implementierung in `../../analytics/features/feature_builder.py`
  (`purge_instance_data(instance_hash)`, Q5) â€“ `FeatureStoreReader` bleibt 100 %
  read-only (MVVM-Invariante).
* BehÃ¤lt MasterTree-Struktur, Parameter-Settings und `doc_log` vollstÃ¤ndig bei.

### B. "Delete Complete" (VollstÃ¤ndige LÃ¶schung)

* Zweistufige Sicherheitsabfrage (*"MÃ¶chten Sie diese Instanz inkl. aller Notizen und DB-Daten unwiderruflich lÃ¶schen?"*).
* Entfernt Preset aus `service_sets` / `indicator_presets` UND lÃ¶scht alle zugehÃ¶rigen Rows im `feature_store`.

### C. "Doc Log bearbeiten" (Negativ-Wissen)

* Ã–ffnet `ServiceDescriptionEditDialog`. Speichert Freitext in `ServiceInstanceConfig.doc_log`.



---

## 6. Schritt-fÃ¼r-Schritt Implementierung

### Schritt 0: DB-Schema (`../../db/schema_initializer.py`) â€“ Q1
* Additive Spalte: `ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS instance_hash VARCHAR;`
  (idempotent, bestehende Rows bleiben unangetastet â€“ `feature_id` bleibt `plugin_id`).

### Schritt 1: Model-Erweiterung (`../../analytics/engine/service_models.py`)

* Erweitere `ServiceInstanceConfig` TypedDict um:
* `doc_log: Optional[str]`
* `instance_hash: Optional[str]`
* `is_archived: bool` (Q6, Default False)

### Schritt 2: Hash-Gen & Baumaufbau (`../../analytics/engine/tree_builder.py` & `service_selector_model.py`)

* `generate_instance_hash(plugin_id, params) -> str`: Erzeuge 8-stelligen SHA256-Short-Hash
  (Q3: ohne `lookback`; Q4: Typ-Sanitizer + `json.dumps(sort_keys=True)` kanonisch).
* Erweitere `build_tree()`: Rendere Parent-Child-Struktur (`Service` $\rightarrow$ `Clones/Presets`).

* FÃ¼r Knoten mit `is_archived=True` bzw. im Pfad `/Archiv`: Setze Checkboxen auf non-checkable
  (Q6: `Qt.ItemIsUserCheckable = False`); dynamischer Ordner `ðŸ“ Archiv` statt statischem Pfad.

### Schritt 3: Dropdown-Integration (`../../analytics/engine/analytics_view_model.py`)

* Erweitere `resolve_service_display_name()`:
* BerÃ¼cksichtige Preset-Namen: `{Service} ({Preset_Name})`.
* Mappe `native`/`none`/kein Prefix auf `"Allgemein"`.
* Neue Resolver-Methode `resolve_instance_hashes(hashes) -> feature_ids` (Q2):
  lÃ¶st selektierte `instance_hash`-Werte transparent auf `plugin_id`-Basis auf.

### Schritt 4: Wartungs-Aktionen (`../../analytics/features/feature_builder.py` & `../../serviceui/master_tree.py`)

* `FeatureBuilder.purge_instance_data(instance_hash)`: SQL
  `DELETE FROM feature_store WHERE instance_hash = ?` (Q5; NICHT im Reader).
* In `master_tree.py`: KontextmenÃ¼-Aktionen `Data Only LÃ¶schen`, `VollstÃ¤ndig LÃ¶schen`
  und `Doc Log bearbeiten` einbinden.
* **Varianten-Erzeugung (Q8):** KontextmenÃ¼ `Als Variante duplizieren` (Service-Knoten) +
  Set-Editor `Service-Instanz clonen` â†’ neue `instance_id`, kopierte Params,
  Parameter-Editor Ã¶ffnen, `instance_hash` neu berechnen.

### Schritt 5: Writer-Ãœbergabe (Q9) â€“ `SetEvaluator` / `HistoricalScanner` / `LiveAnalyzer`

* `store_plugin_payload` um optionalen Parameter `instance_hash` erweitern; der Aufrufer
  (`set_evaluator`/Scanner/LiveAnalyzer) Ã¼bergibt den Hash der ausgefÃ¼hrten Instanz.
* SQL-Upsert schreibt `instance_hash` in die neue Spalte (nur wenn gesetzt, sonst NULL).
* Archiv-Ignoranz: `HistoricalScanner`/`LiveAnalyzer` skippen Instanzen/Presets mit
  `is_archived=True` bzw. `is_active_batch=False` (Q6/Q7).

---

## 7. Verification Checklist (`../../test/test.py`) â€“ 20.04 VERIFIZIERT (09.08.2026)

* [x] **Hash-Check:** `generate_instance_hash(plugin_id, params)` â€“ deterministischer
      8-stelliger SHA256-Short-Hash, Typ-Sanitizer (numpy/None/verschachtelt),
      `sort_keys=True`, ohne `lookback` (Q3/Q4). GeprÃ¼ft in
      `../../test/check_2004_ctxmenu.py` (Q2/Q4) und `../../test/check_2004_tree.py` (Q4).
* [x] **Schema-Check (Q1):** `instance_hash`-Spalte additiv/idempotent
      (`schema_initializer.py`); bestehende Rows `NULL`, `feature_id` bleibt
      `plugin_id`. GeprÃ¼ft in `../../test/check_2004_schema.py` (7/7).
* [x] **Hash-AuflÃ¶sung (Q2):** `resolve_instance_hashes(hashes)` liefert
      deduplizierte `plugin_ids`; Filter weiter `feature_id IN (â€¦)`.
      GeprÃ¼ft in `../../test/check_2004_viewmodel.py` (7/7).
* [x] **Archive Safety (Q6):** Archivierte Knoten/Clones/Sets non-checkable;
      `run_worker` Ã¼berspringt archivierte Sets/Instanzen (Q6);
      `HistoricalScanner`/`LiveAnalyzer` filtern Ã¼ber `list_active_batch_presets`
      (is_active_batch=False). GeprÃ¼ft in `../../test/check_2004_tree.py` (13/13) und
      `../../test/check_2004_writers.py` (8/8).
* [x] **Data-Purge Check (Q5):** `FeatureBuilder.purge_instance_data(instance_hash)`
      lÃ¶scht nur Rows mit dem Hash; Struktur/`doc_log` bleiben intakt;
      `FeatureStoreReader` bleibt read-only. GeprÃ¼ft in
      `../../test/check_2004_purge.py` (8/8).
* [x] **Varianten-Erzeugung (Q8):** KontextmenÃ¼ `Als Variante duplizieren`
      (Service-/Clone-/Plugin-Zeile) erzeugt neue Instanz/Preset-Kopie,
      kopierte Params, neuen `instance_hash` (`_duplicate_set_instance` /
      `_duplicate_preset`). GeprÃ¼ft in `../../test/check_2004_ctxmenu.py` (34/34).
* [x] **Writer-Ãœbergabe (Q9):** `store_plugin_payload(..., instance_hash)` schreibt
      den Hash in die neue Spalte; run_worker/HistoricalScanner/LiveAnalyzer
      Ã¼bergeben ihn. Archiv-Presets (`is_active_batch=False`) werden von Scans
      ignoriert (Q7). GeprÃ¼ft in `../../test/check_2004_writers.py` (8/8) und
      `../../test/check_2004_purge.py` (COALESCE).
* [x] **Naming-Check:** Multi-Select Dropdown formatiert `{Service} ({Preset}) / {Parameter}`
      fehlerfrei (`resolve_service_display_name`, `../../test/check_2004_viewmodel.py`).


---

## 8. Implementierungs-Log (09.08.2026, ~22:08; Commit `b57244b`, Tag `20.04`)

**Phase 20.04 â€“ Parameter-Varianten, Instanz-Hashes & Archivierung** â€“ alle 9
Entscheidungen Q1â€“Q9 umgesetzt. Headless-Verifikation (keine UI-Tests):
`py_compile` aller geÃ¤nderten Dateien, `../../test/test.py` (964 PASS / 6 Baseline-
Geometrie-FAILs unverÃ¤ndert), temporÃ¤re Checks `test/check_2004_*.py`
(alle PASS; Cleanup nach Abschluss der Phase).

### Ã„nderungen je Datei

* **`../../analytics/engine/service_models.py`** (Schritt 1/2a):
  * `_sanitize_for_hash()` (rekursiv â†’ native Typen, Q4) +
    `generate_instance_hash(plugin_id, params)` (8-stelliger SHA256-Short-Hash,
    ohne `lookback` Q3, `sort_keys=True`).
  * `ServiceInstanceConfig` erweitert um `instance_hash`, `doc_log`, `is_archived`;
    `ServiceSetDefinition` um `is_archived` (Q6).

* **`../../db/schema_initializer.py`** (Schritt 0, Q1):
  * `ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS instance_hash VARCHAR`
    (additiv/idempotent; `feature_id` bleibt `plugin_id`).

* **`../../state_manager.py`** (Schritt 4b, Q7):
  * `indicator_presets` um Spalte `doc_log VARCHAR` erweitert (additiv).
  * `list_plugin_presets()` liefert zusÃ¤tzlich `doc_log`.
  * Neu: `set_plugin_preset_doc_log(indicator_id, preset_name, doc_log)`.
  * `save_indicator_preset()` akzeptiert optional `doc_log`.

* **`../../analytics/engine/service_selector_model.py`** (Schritt 2b/3, Q2/Q7):
  * `_plugin_presets` (plugin_id â†’ Clones aus `indicator_presets` via
    `StateManager.list_plugin_presets`), `_load_plugin_presets()` berechnet
    `instance_hash` + `is_archived = not is_active_batch`.
  * `build_tree()`/`plugin_presets()` reichen die Presets an den Baum durch.

* **`../../analytics/engine/tree_builder.py`** (Schritt 2b, Q6/Q7):
  * `ARCHIVE_LABEL = "ðŸ“ Archiv"`; Archiv-Ordner ans Sortier-Ende.
  * Plugins MIT Presets â†’ Parent-Knoten mit Clone-Kindern (`_clones_for`);
    archivierte Clones/Sets wandern in den `ðŸ“ Archiv`-Ordner.

* **`../../serviceui/master_tree.py`** (Schritt 2b/4b/5b, Q5/Q6/Q8):
  * Neue Rollen `ROLE_INSTANCE_HASH` (UserRole+4), `ROLE_ARCHIVED` (UserRole+5);
    neuer Knotentyp `TYPE_CLONE`.
  * `_build_clone_item`: `ðŸŸ¢/ðŸ”¹ <Preset> (#<hash>)`; aktive anhakbar, archivierte
    non-checkable; Tooltip mit Parametern + Doc-Log.
  * KontextmenÃ¼: 4 neue Signale (`data_only_purge_requested`,
    `delete_complete_requested`, `doc_log_requested`, `duplicate_variant_requested`)
    in den Branches TYPE_SERVICE / TYPE_CLONE / TYPE_PLUGIN; Archiv-Guards
    (archivierte Sets: Run/Umbenennen/HinzufÃ¼gen deaktiviert).

* **`../../serviceui/service_win.py`** (Schritt 4b, Q5/Q6/Q8):
  * 4 verbundene Handler + Helfer: `_on_data_only_purge`,
    `_on_delete_complete`, `_on_doc_log_requested`, `_on_duplicate_variant`,
    `_find_preset_for_hash`, `_next_preset_copy_name`, `_save_instance_doc_log`,
    `_save_plugin_doc_log`, `_delete_complete_set_instance`,
    `_delete_complete_preset`, `_duplicate_set_instance`, `_duplicate_preset`.
  * Data-Only-Purge â†’ `FeatureBuilder.purge_instance_data` (Q5); Voll-LÃ¶schen
    mit 2-stufiger Sicherheitsabfrage + P14-04-E-Sperre; Doc Log Ã¼ber
    `ServiceDescriptionEditDialog`.

* **`../../analytics/features/feature_builder.py`** (Schritt 4, Q5/Q9):
  * `store_plugin_payload(..., instance_hash=None)` schreibt den Hash in die
    neue Spalte; UPSERT erhÃ¤lt vorhandenen Hash via
    `COALESCE(EXCLUDED.instance_hash, feature_store.instance_hash)`.
  * Neu: `purge_instance_data(instance_hash) -> int` (Q5, FeatureBuilder,
    nicht im Reader).

* **`../../analytics/engine/analytics_view_model.py`** (Schritt 3, Q2):
  * `resolve_service_display_name(plugin_id, preset_name=None)` â†’
    `{Service} ({Preset})`; neu `resolve_instance_hashes(hashes)` â†’
    deduplizierte `plugin_ids`.

* **`../../serviceui/run_worker.py`** (Schritt 5/5b, Q6/Q9):
  * `instance_hash`-Ãœbergabe an `store_plugin_payload` (bevorzugt
    `cfg.instance_hash`, sonst `generate_instance_hash`).
  * Archiv-Guards: archivierte Sets/Instanzen werden mit Log +
    `run_finished(0)` Ã¼bersprungen.

* **`../../analytics/background_workers/historical_scanner.py`** und
  **`../../analytics/background_workers/live_analyzer.py`** (Schritt 5, Q7/Q9):
  * `instance_hash` aus `generate_instance_hash(plugin_id, preset.params)` an
    `store_plugin_payload` Ã¼bergeben; Archiv-Ignoranz via
    `list_active_batch_presets()` (is_active_batch=False ausgeschlossen).

* **`../../test/test.py`** (Test-Harness):
  * 5 `feature_store`-Temp-Tabellen um `instance_hash VARCHAR` ergÃ¤nzt;
    `_FakeFB.store_plugin_payload` um `instance_hash`-Kwarg erweitert.

### TemporÃ¤re Checks (nach Phasenabschluss Cleanup)

* `../../test/check_2004_schema.py` (7/7), `../../test/check_2004_tree.py` (13/13),
  `../../test/check_2004_viewmodel.py` (7/7), `../../test/check_2004_purge.py` (8/8),
  `../../test/check_2004_ctxmenu.py` (34/34), `../../test/check_2004_writers.py` (8/8).

---

## 8a. Implementierungs-Log â€“ Bugfix Q8 â€žAls Variante duplizieren zeigt kein Ergebnis" (09.08.2026, Commit `0a1baea`)

**Problem:** `Als Variante duplizieren` schrieb korrekt in die DB (Set-Instanz- und
Clone-Pfad verifiziert), lieferte aber KEIN sichtbares Ergebnis:

1. Der Parameter-Editor wurde nur bei bereits geladenem Set aktualisiert
   (Q8 verlangt â€žÃ¶ffnet Parameter-Editor").
2. Clones wurden als unsichtbares (kollabiertes) Child angelegt.
3. Namens-Bug: flaches Plugin â†’ Preset wurde `Default (Kopie)` statt `Default`
   benannt, weil `_next_preset_copy_name` auf `list_indicator_presets` zugriff,
   das den UI-Default â€žDefault" immer fabriziert.

### Ã„nderungen

* **`../../serviceui/master_tree.py`**:
  * Neu (public, nach `_restore_selection`): `select_instance(set_id, service_id)`
    und `select_clone(plugin_id, instance_hash)` plus gemeinsames
    `_select_by(predicate)` â€“ expandiert die Eltern-Kette (`_expand_ancestors`),
    selektiert unter `blockSignals` und scrollt in den sichtbaren Bereich.

* **`../../serviceui/service_win.py`**:
  * `_duplicate_set_instance`: lÃ¤dt das Ziel-Set IMMER in den Parameter-Editor
    (statt nur wenn `_current_set_id == set_id`) und selektiert die neue Instanz
    via `tree.select_instance(...)`.
  * `_duplicate_preset`: selektiert den neuen Clone via `tree.select_clone(...)`.
  * `_next_preset_copy_name(sm, plugin_id, base)`: Quelle jetzt
    `list_plugin_presets(plugin_id)` (nur echte Preset-Rows) statt
    `list_indicator_presets`; ist der Basis-Name noch GAR NICHT vergeben
    (flaches Plugin-Blatt), wird er direkt verwendet â€“ sonst
    `<base> (Kopie)`, `(Kopie 2)`, ...

### Verifikation (headless, keine UI-Tests)

* `../../test/check_2004_dupl3.py`: **8/8 PASS** (Set-Instanz-Pfad, Editor-Spalte,
  Baum-Selektion + Expansion, Clone-Pfad, Namens-Fix) â€“ danach Cleanup.
* `../../test/test.py`: 964 PASS / 6 FAIL (nur vorbestehende Geometrie-Baseline
  P2/P5/H3-H7, unverÃ¤ndert).
* `../../test/check_2004_ctxmenu.py` (34/34), `../../test/check_2004_writers.py` (8/8),
  `../../test/check_2004_purge.py` (8/8).
* `py_compile` + CRLF-Konsistenz (0 lone LF) aller geÃ¤nderten Dateien.
---

## 8b. Implementierungs-Log â€“ Bugfix â€žAggregation & Ergebnisparameter nicht in Fensterhistorie/Profil" (09.08.2026)

**Problem (User-Bugreport 09.08.2026, beobachtet unter â€žGenerisch"):** Nach
Fenster-Schliessen/Wiederherstellen UND bei Profilwechseln wurden die
Aggregation und die Konfiguration des Ergebnisparameter-Dropdowns (Feld) in
der generischen Heatmap NICHT wiederhergestellt. X-Achse, Y-Achse und der
Metrik-/Modus-Selektor blieben korrekt. Die Werte WURDEN gespeichert
(Workspace `instance_states.workspace_state` und Profil-Payload
`charts.heatmap` enthalten `heatmap_agg`/`heatmap_field` vollstÃ¤ndig) â€“ der
Restore-Verlust entstand in der UI-Sync-Schicht.

**Root Cause (Timing-Problem beim App-Start):**

1. `attach_view_model()` laeuft VOR `restore_workspace()`/`_apply_profile()` â€“
   die Combos werden beim Start mit Defaults/leerem Zustand befuellt.
2. Der Restore setzt NUR die VM-Params â€“ die UI-Combos werden nicht neu
   synchronisiert (kein `_sync_from_params()`-Aufruf nach dem Restore).
3. Der erste Daten-Payload ruft `_sync_combos_from_payload()`:
   * X-/Y-Achse und Aggregation werden aus dem Payload gesetzt â€“ der Payload
     reflektiert die restaurierten Params â†’ bleiben korrekt.
   * `prev_field` wurde aus `self._combo_field.currentData()` (leer beim
     Start) abgeleitet statt aus dem Payload-`field` â†’ fiel auf den ersten
     verfuegbaren Key (`is_hit` statt `visit_pct`).
   * Der E6-Loop (`_apply_config` bei AVG/SUM/MIN/MAX) ueberschrieb
     `heatmap_field` AKTIV mit dem falschen Key.
4. Dasselbe Divergenz-Muster bei der Aggregation: Ein veralteter/erster
   Payload (Initial-Query mit Default-Params) konnte die Aggregations-Combo
   auf `confluence_count` zurueckstellen; sobald der User danach ein Control
   anfasste, las `_apply_config` die Combo (falscher Wert) und ueberschrieb
   `params["heatmap_agg"]`.

**Loesung (Variante A + B + D, wie empfohlen):**

* **`../../analytics/ui/heatmap_widget.py`** â€“ `_sync_combos_from_payload()` (A+B):
  `agg` und `prev_field` bevorzugen jetzt primaer den Daten-Payload
  (`data.get("agg")` / `data.get("field")`), sekundaer die restaurierten
  VM-Params (`heatmap_agg`/`heatmap_field`) und erst am Ende den
  Combo-Zustand. Der E6-Loop laesst einen restaurierten Wert unangetastet.

* **`../../analytics/engine/analytics_view_model.py`** (D):
  Neues Signal `params_restored = Signal()` (MVVM-konform, kein UI-Import).
  Emission am Ende von `_apply_profile()` (deckt Profilwechsel +
  `load_profiles()`) und `restore_workspace()` (deckt Fenster-Schliessen/
  Wiederherstellen).

* **`../../analytics/ui/heatmap_widget.py`** â€“ `attach_view_model()` (D):
  Verbindet `params_restored` mit dem bereits vorhandenen
  `_sync_from_params()` (defensiv per `hasattr` fuer Test-Mocks). Dadurch
  stehen die UI-Combos sofort nach dem Restore synchron zu den
  VM-Parameters; Signale bleiben blockiert â†’ kein Query-Loop.

**Verifikation (headless, keine UI-Tests):**

* `../../test/check_2004_timing.py`: **3/3 PASS** (vorher 1/3 â€“ FAIL
  `heatmap_field='is_hit'` nach Payload + E6-`_apply_config`-Ueberschreiben).
* `../../test/check_2004_uiflow.py`: 6/6 PASS (User-Interaktion + Payload-Sync).
* D-Wiring-Check (headless): X/Y/Aggregations/Feld-Combos korrekt aus den
  restaurierten Params nach `params_restored`-Emission.
* `py_compile` + CRLF-Konsistenz (0 lone LF) beider geaenderten Dateien.

**Hinweis:** Die DB-abhaengigen Regressionstests (`test.py`-Baseline 964/6,
`check_2004_restore`/`snapshot`/`bugfix3`) waren zum Verifikationszeitpunkt
nicht ausfuehrbar, weil die laufende App `../../data/app_data.duckdb` haelt
(DB-Lock, rein umgebungsbedingt). Sie liefen in derselben Sitzung vor der
Umsetzung gruen und sind von dieser additiven Aenderung unberuehrt.
---

## 8c. Implementierungs-Log â€“ Bugfix Varianten-Anzeige/-Anlage/-Umbenennung (10.08.2026)

**Problem (User-Bugreport 10.08.2026, analytics_win / Service-Picker):** Drei
Schwaechen im MasterTree-Varianten-Konzept (20.04):

1. **Varianten-Anzeige:** Clone-Zeilen zeigten die technische ID (`#<hash>`)
   statt des letzten Ausfuehrungsdatums; der Plugin-Parent-Knoten trug
   zusaetzlich ein eigenes Ausfuehrungsdatum, das mit den Varianten-Daten
   verwechselbar war.
2. **Varianten-Anlage:** 'Als Variante duplizieren' vergab den Namen stumm
   ueber das Auto-Schema ('<base> (Kopie)') â€“ ein neuer Name MUSS vom User
   vergeben werden.
3. **Varianten-Rename:** Es fehlte eine 'Variante umbenennen'-Aktion im
   Kontextmenue (UPDATE auf den Primaerschluessel `(indicator_id,
   preset_name)`).

**Anforderungen (verbindlich, Anwender 10.08.2026):**

| # | Anforderung |
|---|---|
| V1 | Existiert eine Variante, haengt das letzte Ausfuehrungsdatum am Varianten-Namen (`<Preset> (DD.MM.JJ)`); die ID (`#hash`) entfaellt aus dem Label; der Plugin-Parent-Knoten zeigt KEIN Ausfuehrungsdatum mehr. |
| V2 | Beim Anlegen einer neuen Variante MUSS ein neuer Name eingegeben werden (kein stummes Auto-Naming). |
| V3 | Kontextmenue-Aktion 'Variante umbenennen' vorhanden. |

### Aenderungen je Datei

* **`../../analytics/engine/feature_store_reader.py`** (V1):
  * Neu (read-only, nach `fetch_last_execution_dates`):
    `fetch_last_execution_dates_by_hash() -> Dict[feature_id_lower,
    {instance_hash: 'DD.MM.JJ'}]` â€“ `MAX(created_at) GROUP BY
    feature_id + instance_hash` ueber alle Symbole/Timeframes. Rows ohne
    `instance_hash` und der Sentinel `'native'` werden uebersprungen;
    case-insensitiv/whitespace-tolerant wie die Plugin-Variante. Defensiv:
    Fehler/Tabelle fehlt -> `{}`.

* **`../../analytics/engine/service_selector_model.py`** (V1):
  * Neuer State `_last_execution_dates_by_hash` (`Dict[pid_lower,
    {hash: date}]`), geladen in `refresh()` NACH den Plugin-Daten
    (`_load_last_execution_dates_by_hash()` delegiert an den
    FeatureStoreReader; Fehler -> `{}`).
  * `_load_plugin_presets()`: jedes Clone-Dict erhaelt
    `last_execution` (per-Hash-Datum, Fallback `'--.--.--'`).
  * Neu (public): `last_execution_date_for_hash(plugin_id, instance_hash)`
    -> `'DD.MM.JJ'` oder `'--.--.--'`.

* **`../../serviceui/master_tree.py`** (V1/V3):
  * Neue Rolle `ROLE_PRESET_NAME` (UserRole+6) traegt den Anzeigenamen eines
    Clone-Knotens (fuer den Rename-Dialog ohne DB-Lookup).
  * `_build_plugin_item`: Hat das Plugin Clones, ist das Parent-Label nur die
    Plugin-ID (KEIN Datum); flache Blaetter behalten `pid (DD.MM.JJ)`.
  * `_build_clone_item`: Label `ðŸŸ¢/ðŸ”¹ <Preset> (DD.MM.JJ)` â€“ Hash entfaellt,
    Datum der letzten Ausfuehrung dieser Variante direkt am Namen.
  * Neues Signal `rename_variant_requested(plugin_id, instance_hash,
    new_name)`; `_on_rename_clone(item)` fragt den neuen Namen via
    `QInputDialog` ab (vorbelegt mit `ROLE_PRESET_NAME`) und emittiert das
    Signal. Kontextmenue-Branch TYPE_CLONE: Aktion 'Variante umbenennen'
    (bei archivierten deaktiviert).

* **`../../state_manager.py`** (V3):
  * Neu: `rename_indicator_preset(indicator_id, old_name, new_name)` â€“
    `UPDATE indicator_presets SET preset_name = ? WHERE indicator_id = ?
    AND preset_name = ?`. Alle weiteren Spalten bleiben unangetastet; der
    Aufrufer prueft vorher auf Kollisionen (Unique-Constraint).

* **`../../serviceui/service_win.py`** (V2/V3):
  * Verbindung `rename_variant_requested` -> neuer Handler `_on_rename_variant`
    (Kollisionspruefung via `list_plugin_presets`, Persistenz via
    `rename_indicator_preset`, Live-Sync via `event_bus.service_set_changed`).
  * `_duplicate_preset`: `QInputDialog` 'Name fuer die neue Variante (aus
    '<base>')' â€“ vorbelegt mit dem freien Kopiernamen; Leer-/Abbruch-Guard
    und Kollisionspruefung vor `save_indicator_preset`.

* **`../../serviceui/service_selector_dialog.py`** (V2/V3):
  * Gleiche Verkabelung fuer den Analytics-Datenquellen-Picker:
    `_on_rename_variant` (QMessageBox-basiert) + Namensdialog in
    `_duplicate_preset`.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_variant_bugfix.py`: **17/17 PASS** â€“ per-Hash-Daten (1a-1d),
  Clone-`last_execution` im Baum (2a-2c), MasterTree-Labels (3a-3e:
  Parent ohne Datum, Clone mit Datum ohne Hash, ROLE_PRESET_NAME, flaches
  Blatt-Regression, Archiv-Clone), `rename_indicator_preset`-Persistenz
  (4a-4d). Temp-Verzeichnisse danach entfernt.
* Real-Modell-Integration (offscreen): `ServiceSelectorModel` laedt Presets
  mit `last_execution` aus dem echten Feature-Store (z. B.
  `srv_swing_volume_profile` -> 'Default'/'Default (Kopie)' mit
  `exec=10.08.26`).
* `py_compile` + CRLF-Konsistenz (0 lone LF) aller geaenderten Dateien.

---

## 8d. Implementierungs-Log - Bugfix UI-Splitter/Dropdown/Save-Restore-Pipeline (10.08.2026)

**Problem (User-Bugreport 10.08.2026, Runden 2-4):** Sechs Punkte aus den
Analytics-UI-Bugfix-Runden nach 20.04 (Varianten-Params, Dropdown-Hitbox,
Splitter, Save-Collapse, Slider, Log-Hoehe) sowie vier Punkte der
Save/Restore-Pipeline (nested heatmap, Picker-Live-Filter, UI-Sync nach
Restore, Profil-Restore).

### Runde 2: Varianten-Params, Dropdown-Hitbox, UI-Splitter

* **Bug 1 (Varianten-Params):** Klick auf einen Clone-Knoten (Preset/
  Variante) lud die GLOBALEN Standalone-Parameter statt der
  presetspezifischen Params; Save schrieb in global_settings statt in das
  Preset (indicator_presets).
  * `../../serviceui/service_win.py`: `_current_preset_editing`,
    `_load_clone_editor()` (Clone-Klick -> presetparams laden), Save via
    `save_indicator_preset`.
  * `../../serviceui/service_selector_dialog.py`: `_entries_for_scope` liefert
    `preset_params` + `preset`; `_DialogParamHost._save_plugin_params`
    Preset-Branch (schreibt in indicator_presets statt
    plugin_params_<id>, is_active_batch/doc_log bleiben erhalten);
    `_current_preset_editing` im Host + Ruecksetz im Panel-Rebuild.

* **Bug 2 (CheckableComboBox-Hitbox):** Klick auf die LineEdit-Flaeche der
  CheckableComboBox oeffnete das Popup nicht (nur Pfeil/Rahmen).
  `../../analytics/ui/common.py`: `lineEdit().installEventFilter(self)`,
  Event-Filter (LineEdit-Klick togglet das Popup) +
  `mousePressEvent`-Override (Box/Rahmen togglet ebenfalls).

* **Bug 3 (UI-Splitter):** Tree/Sidebar waren starr fixiert
  (`setFixedWidth(300)` im Picker, `setFixedWidth(150)` im AnalyticsWindow).
  `service_selector_dialog.py`: `_splitter` (QSplitter, Tree links mit
  minWidth 180, Panel rechts, Stretch-Faktoren 0/1, nicht kollabierbar)
  statt `setFixedWidth`; `_fit_dialog_width` misst die rechte Kante
  splitter-relativ (Tree-Breite + Handle + Panel-Minimum).
  `../../analytics/ui/analytics_win.py`: `_body_splitter` (Sidebar minWidth 120 +
  Seiten-Stack, `setSizes([150, 1200])`).

### Runde 3: Save-Collapse, Slider, Log-Hoehe

* **Punkt 1 (Save klappt Knoten zu):** Nach einem Speichern (EventBus-
  Refresh) kollabierte jeder zugeklappte Plugin-Knoten mit Clones.
  `../../serviceui/master_tree.py`: `_collect_expanded_state`/`_apply_expanded_
  state` tracken jetzt auch `TYPE_PLUGIN`-Knoten MIT Kindern
  (`("plugin", plugin_id)`) - Expansion bleibt ueber Neuaufbauten erhalten.

* **Punkt 3 (Slider service_win):** Das ServiceWindow war mit
  `setMinimumWidth(960)` zu breit. `../../serviceui/service_win.py`:
  `setMinimumWidth(520)` statt 960, initiale Splitter-Sizes
  `main_splitter.setSizes([460, 820])`.
  `../../serviceui/param_columns.py`: Grow-only-`setSizes` (beim Panel-Rebuild
  waechst das Panel nur, der Tree bleibt an der User-Position).

* **Punkt 4 (Log-Hoehe):** Das Scroll-Log war zwei Zeilen zu hoch.
  `../../serviceui/service_win.py`: `lineSpacing() * 2 + 12` statt `* 4 + 12`.

### Runde 4: Save/Restore-Pipeline (4 Punkte)

**Analyse-Ergebnis:** Die Punkte 1 und 4 (nested heatmap-Dict aufloesen +
`params_restored` emittieren) waren bereits im ViewModel implementiert
(Commit `7ffc1f7` - `_apply_heatmap_section` in `restore_workspace()` UND
`_apply_profile()`, Emission `params_restored` in beiden Pfaden). Keine
Aenderung noetig - nur verifiziert.

* **Punkt 2 (ECHTER BUG - Check/Uncheck im ServicePicker):** Die
  `checked_changed`-Verbindung wurde in Bugfix-Runde 3 (06.08.2026)
  entfernt ("Punkte 1-7"), damit das Read-Only-Panel dem Klick folgt.
  Dadurch folgte aber AUCH der Live-Filter nicht mehr den Haken - die
  Resultatparameter-Dropdowns (heatmap field/agg) aktualisierten sich bei
  Checkbox-Aenderungen nicht. `../../serviceui/service_selector_dialog.py`:
  Verbindung `tree.checked_changed` -> neuer Handler `_on_checked_changed`,
  der `selection_ids_requested(checked_feature_ids())` emittiert ->
  AnalyticsWindow `_on_picker_ids_selected` -> `set_feature_ids()`.
  Das Read-Only-Panel bleibt klickgesteuert (Punkte 1-7 unveraendert).

* **Punkt 3 (UI-Sync nach Restore):** `heatmap_widget.py` verband
  `params_restored` -> `_sync_from_params` bereits, aber die
  Fenster-Ebene (AnalyticsWindow) hatte keine Verbindung.
  `../../analytics/ui/analytics_win.py`: `_wire_view_model()` verbindet
  `vm.params_restored` -> neuer Handler `_sync_ui_from_restored_params`
  (Sidebar-Seite via `workspace_layout.page_index` unter blockSignals,
  aktuelle Page falls `_sync_from_params` existiert, danach
  `_sync_profile_filters()` + `_sync_service_filter_button()`).

### Verifikation (headless, keine UI-Tests)

* `../../test/check_ui3_bugfix.py`: **19/19 PASS** (Save-Collapse-Fix
  TYPE_PLUGIN-Expansion, service_win-Slider 520/Grow-only, Log-Hoehe
  2 Zeilen).
* `../../test/check_variant_bugfix.py`: **17/17 PASS** (per-Hash-Daten,
  Clone-Labels, Rename-Persistenz - Runde 1).
* `../../test/check_variant_params_bugfix.py`: **29/29 PASS** (Varianten-Params,
  CheckableComboBox-Hitbox, QSplitter in Picker/AnalyticsWindow).
* `../../test/check_restore_pipeline_bugfix.py` (neu): **27/27 PASS** - P1/P4
  (nested heatmap + params_restored in restore_workspace/_apply_profile),
  P2 (Anhaken/Abhaken -> selection_ids_requested mit checked_feature_ids),
  P3 (params_restored -> Sidebar folgt page_index, Datenquellen-Button
  synchron).
* `../../test/check_2004_ctxmenu.py`: **34/34 PASS**, `../../test/check_2004_restore.py`:
  **4/4 PASS** (Regression Restore-Pipeline).
* `py_compile` aller geaenderten Dateien + CRLF-Konsistenz.
## 8e. Implementierungs-Log - Bugfix UI-Layout-Persistenz & Klick-Konflikt (10.08.2026)

**Problem (User-Bugreport 10.08.2026, Runden 5+6):** Fuenf Punkte aus den
Analytics-UI-Bugfix-Runden nach 20.04 (heatmap_mode im Profil, page_index
im Profil, Muster-/Live-Filter bei Plugin-Parent ohne Checkbox) sowie drei
Punkte der Restore-Pipeline (angehakte Services in Historie/Profil,
Check/Uncheck aktualisiert Dropdowns, ServicePicker-Waisenfenster).

### Runde 5: UI-Layout-Persistenz (3 Punkte)

* **Punkt 3 (heatmap_mode im Profil):** Der Ansichts-Modus der Heatmap-
  Seite (standard/delta) wurde beim Speichern eines Profils nicht
  persistiert und beim Restore nicht wiederhergestellt.
  `../../analytics/engine/analytics_view_model.py`: Neue Methode
  `set_ui_layout(layout)` (uebernimmt die UI-Layout-Sektion in
  `_workspace_layout`); `_current_payload()` erhaelt die Sektion
  `"layout"`; `_apply_profile()` legt sie in `_workspace_layout`.
  `../../analytics/ui/analytics_win.py`: Neue Methode `_current_ui_layout()`
  (liefert `page_index` + `heatmap_mode`); `set_ui_layout(...)` wird vor
  `save_profile()`/`create_profile()` aufgerufen; der Sync-Handler
  `_sync_ui_from_restored_params` setzt `heatmap_page.set_mode(...)`
  aus `workspace_layout.heatmap_mode` (Muster `_restore_workspace`).

* **Punkt 4 (page_index im Profil):** Die aktive Sidebar-Seite wurde im
  Profil nicht gespeichert/wiederhergestellt.
  Gleicher Mechanismus wie Punkt 3 (Sektion `"layout"` enthaelt
  `page_index`). Im Sync-Handler wird die Seite jetzt EXPLIZIT via
  `self.pages_stack.setCurrentIndex(page_index)` umgeschaltet
  (blockSignals unterdrueckt `currentRowChanged` -> `_on_page_changed`;
  ohne `setCurrentIndex` bliebe die alte Seite sichtbar).

* **Punkt 6 (Plugin-Parent ohne Checkbox):** Ein Plugin-Knoten OHNE
  Kinder (nur ein Plugin, keine Varianten) hatte keine Checkbox, konnte
  aber via Muster-/Live-Filter nicht mehr angesprochen werden.
  `../../serviceui/master_tree.py`: `childCount() == 0`-Guard in
  `set_checked_feature_ids` und `_sync_checked_items` - bei kinderlosen
  Plugin-Knoten wird das Item selbst statt der Kinder gesetzt (die
  `setCheckState`-Semantik mit `childCount()` schlug sonst fehl).

### Runde 6: Klick-Konflikt in der Restore-Pipeline (3 Punkte)

* **Bug 1+2 (GEMEINSAME ROOT CAUSE - Klick ueberschrieb Checkboxen):**
  Der ServicePicker hatte zwei konkurrierende Live-Filter-Pfade:
  (1) Checkbox-Pfad (seit Runde 4): `checked_changed` ->
  `_on_checked_changed` -> `selection_ids_requested(checked_feature_ids())`
  - korrekt. (2) Klick-Pfad: `master_tree.mousePressEvent` emittierte bei
  JEDEM Mausklick `selection_details` -> `_on_tree_selection_details`
  emittierte zusaetzlich `selection_ids_requested(ids)` mit dem
  Zeilen-Scope und ueberschrieb damit den angehakten Filter. Folge:
  Nach dem Anhaken von A+B genuegte ein Klick auf eine Zeile, und die
  Historie/das Profil speicherten den letzten Klick-Scope statt der Haken
  (Bug 1); die Ergebnisparameter-Dropdowns folgten dem Klick statt den
  Haken (Bug 2).
  `../../serviceui/service_selector_dialog.py`: Der Klick-Handler emittiert
  KEIN `selection_ids_requested` mehr (der Filter folgt ausschliesslich
  den Checkboxen); das Read-Only-Panel folgt weiterhin dem Klick
  (Punkte 1-7 unveraendert). `_resolve_selection_ids` bleibt als
  ungenutzter Bestandscode erhalten.

* **Bug 3 (ServicePicker-Waisenfenster):** Der ServicePicker-Singleton
  (`_service_dialog`, kein WA_DeleteOnClose) blieb beim Schliessen des
  AnalyticsWindow als frei bewegliches Waisenfenster haengen.
  `../../analytics/ui/analytics_win.py`: `closeEvent` schliesst
  `self._service_dialog.close()` vor `_save_workspace()`; das
  `destroyed`-Signal setzt die Referenz via `_on_service_dialog_destroyed`
  zurueck (RuntimeError/AttributeError abgefangen).

### Verifikation (headless, keine UI-Tests)

* `../../test/check_restore_pipeline_round2.py` (neu, Runde 5): **29/29 PASS** -
  Workspace- und Profil-Restore mit feature_ids, Layout-Sektion
  (heatmap_mode + page_index) in Profil-Payload und Restore, Plugin-Parent
  ohne Kinder setzt CheckState korrekt (Muster-/Live-Filter).
* `../../test/check_restore_pipeline_round3.py` (neu, Runde 6): **17/17 PASS** -
  Zeilen-Klick emittiert KEIN selection_ids_requested, Checkbox-Anhaken
  emittiert `[pid]`, Abhaken emittiert `[]`, Clone-Klick ohne Filter-Emit,
  destroyed-Mechanismus (Referenz auf None) + close()-Semantik ohne
  Waisenfenster, Quell-Marker fuer alle drei Fixes.
* Regressionen: `../../test/check_2004_ctxmenu.py` **34/34 PASS**,
  `../../test/check_variant_bugfix.py` **OK**, `../../test/check_ui3_bugfix.py`
  **19/19 PASS**.
* `py_compile` aller geaenderten Dateien + CRLF-Konsistenz.

---

## 8f. Implementierungs-Log - Bugfix Kerzen-Overlay, ServicePicker-Restore, Dropdown-Sync (10.08.2026)

**Problem (User-Bugreport 10.08.2026, Runde 7):** 5 Punkte - Kerzen-Overlay
nur bei Datum auf einer Achse, ServicePicker-Position nicht in Historie
gemerkt (restore fails), Ergebnisparameter-Dropdown nicht restored, Dropdown
nicht aktualisiert bei Check/Uncheck, Check/Uncheck nicht in Historie
gemerkt (restore fails). Der Runde-6-Fix (Klick-Pfad entfernt) war korrekt,
deckte die echten Ursachen aber nicht ab: Der Checkbox-Pfad und die
VM-Speicherkette funktionieren (headless verifiziert); die Wurzeln lagen in
der Heatmap-UI-Sync (Stale-Payloads), zwei konkurrierenden feature_ids-
Quellen (Picker vs. 'Feld'-Dropdown) und fehlender Picker-Open-Persistenz.

### Bug 1 (Kerzen-Overlay nur bei Datum auf einer Achse)

* `../../analytics/ui/heatmap_widget.py`: `_update_controls()` erlaubt das Overlay
  jetzt bei `date` auf der X- ODER Y-Achse (vorher hart `can_overlay =
  x_dim == "date"`). `_on_config_changed()` schaltet das Overlay nur noch
  aus, wenn `date` auf KEINER Achse liegt. `_render_overlay()` zeichnet
  vertikale Candles bei X=date (Preis auf der rechten Achse) und
  horizontale Candles bei Y=date (Preis auf einer NEUEN zweiten unteren
  Preis-Achse, `_price_axis_bottom` via `plotItem.layout.addItem(axis, 4,
  1)`); `pg.BarGraphItem` nutzt `x0`/`width` fuer horizontale Dochte/Bodies.
  Der Preis-ViewBox-Link folgt der Date-Achse (XLink vs. YLink),
  `_update_price_view()` benachrichtigt die passende Achse.

### Bug 2 (ServicePicker-Position/Restore)

* `../../analytics/ui/analytics_win.py`: `_save_workspace()` persistiert
  `layout.service_picker_open` (Dialog noch offen?); `closeEvent()` speichert
  den Workspace VOR dem Schliessen des Dialogs (der Zustand muss noch
  sichtbar sein). `_current_ui_layout()` persistiert den Picker-Offen-Zustand
  auch im Profil-Payload. `_restore_workspace()` und
  `_sync_ui_from_restored_params()` oeffnen den Picker nach dem Restore
  wieder - die Position stellt der Dialog selbst aus global_settings wieder
  her (Roundtrip war bereits korrekt, es fehlte nur das Wieder-Oeffnen).

### Bug 3 (Ergebnisparameter-Dropdown nicht restored)

* `../../analytics/ui/heatmap_widget.py` `_sync_combos_from_payload()`: Die
  Prioritaet wurde gedreht - die RESTAURIERTEN VM-Params (Workspace/Profil)
  gewinnen jetzt gegen einen Stale-Payload (Query lief VOR dem Restore mit
  Default-Params), der Payload bestaetigt nur noch die tatsaechlich
  verwendeten Werte (`agg`/`prev_field`). Der E6-Loop ueberschreibt
  `heatmap_field` nicht mehr, wenn ein gueltiger Restore-Wert im aktuellen
  Datensatz existiert (`_find_field_index`).

### Bug 4 (Dropdown nicht aktualisiert bei Check/Uncheck)

* Root Cause: ZWEI konkurrierende `feature_ids`-Quellen - ServicePicker-
  Checkboxen (`checked_changed` -> `selection_ids_requested`) UND das
  'Feld'-CheckableComboBox (`_on_field_selection_changed` ->
  `set_feature_ids`). Loesung (Single Source of Truth = Picker): Die
  `selection_changed`-Verbindung ist ENTFERNT (Bestandscode bleibt),
  `_sync_combos_from_payload()` leitet die initialen CheckStates aus dem
  aktiven `feature_ids`-Filter ab - nur Services aus dem Filter erscheinen
  angehakt; Shared-Keys nutzen die XOR-Regel (Sammel-Eintrag ALL|key deckt
  alle aktiven Quellen ab, sonst Einzel-Eintraege).

### Bug 5 (Check/Uncheck nicht in Historie gemerkt)

* Durch den Bug-4-Fix (kein feature_ids-Write-Back des Feld-Dropdowns) kann
  der Restore die gespeicherten `feature_ids` nicht mehr ueberschreiben; der
  Picker wird nach dem Restore wieder geoeffnet (Bug 2) und zeigt die
  restaurierten Haken.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_round7_fixes.py` (neu): **28/28 PASS** - Overlay X=date UND
  Y=date (Candles, Achsen-Sichtbarkeit, ViewBox-Link, Auto-Abschaltung ohne
  date-Achse), Stale-Payload kloppt VM-Params nicht (agg/field bleiben),
  Feld-Dropdown-CheckStates folgen feature_ids (srv_a / srv_a+srv_b /
  XOR-Sammel), kein feature_ids-Write-Back, Picker-Persistenz-Quell-Marker.
* `../../test/check_round7_picker_runtime.py` (neu): **PASS** - echtes
  AnalyticsWindow mit Temp-DBs: Picker open -> save -> restore -> wieder
  sichtbar.
* Regressionen: `../../test/check_restore_pipeline_round2.py` **29/29 PASS**,
  `../../test/check_restore_pipeline_round3.py` **17/17 PASS**,
  `../../test/check_2004_ctxmenu.py` **34/34 PASS**,
  `../../test/check_variant_bugfix.py` **OK**, `../../test/check_ui3_bugfix.py`
  **19/19 PASS**, `../../test/check_2004_timing.py` **3/3 PASS**.
* `py_compile` aller geaenderten Dateien + CRLF-Konsistenz.

---

## 8g. Implementierungs-Log - Bugfix Runde 8: Feld-Dropdown-Restore, synchroner Check/Uncheck-Sync, Picker-Feedback-Schleife (10.08.2026)

**Problem (User-Bugreport 10.08.2026, Runde 8):** Die Runde-7-Fixes
(Commit f39cbcb) waren korrekt, aber drei Bugs bestanden fort:
(1) Das Ergebnisparameter-Dropdown (Feld) wurde bei open/restore der
Analytics-Sicht nicht zuverlaessig restauriert (Restore-Pfad erzeugte nur
Roh-Items, der naechste Payload-Rebuild warf sie wieder weg - kein
synchroner Pfad 'Params geaendert -> UI neu abgeleitet').
(2) Das Feld-Dropdown wurde bei Check/Uncheck im ServicePicker nicht
aktualisiert (set_feature_ids() hatte KEIN Signal ans Widget; das Update
lief nur ueber Debounce + serielle Worker-Kette - langsam, fragil, stale).
(3) Check/Uncheck wurde nicht in die Historie gemerkt: Beim Oeffnen des
Pickers nach einem Restore ueberschrieb die Feedback-Schleife
(set_checked_feature_ids -> checked_changed -> selection_ids_requested ->
set_feature_ids) den restaurierten Filter - Plugin-Parents MIT Clones
(Template-Knoten, non-checkable) fielen aus checked_feature_ids() und
kuerzten den Filter.

### Loesung (generisch, Single Source of Truth)

* `../../analytics/engine/analytics_view_model.py`: Neues Signal
  `feature_ids_changed = Signal()` - `set_feature_ids()` emittiert es nach
  `_mark_dirty()`, vor `_refresh(...)`. Neues Generations-Token
  `_restore_generation: int` - wird in `_apply_profile()` und
  `restore_workspace()` erhoeht, in `_current_params()` als
  `"restore_generation"` mitgegeben. Neue Property `restore_generation`.
* `../../analytics/engine/analytics_worker.py`: Spiegelt das Generations-Token
  aus den Worker-Params ins Ergebnis-Dict
  (`result["restore_generation"]`, try/except-defensiv) - die UI kann
  damit Queries, die VOR dem letzten Restore/Profil gestartet wurden, als
  stale erkennen.
* `../../analytics/ui/heatmap_widget.py`: Neue zentrale Methode
  `_rebuild_field_dropdown(keys, field_sources, payload_agg, payload_field)`
  - Single Source of Truth fuer das 'Feld'-Dropdown: Items aus
  Feld-Metadaten-Cache (`_field_keys`/`_field_sources`), Haken aus
  `feature_ids` (XOR-Sammel-Regel, active_ids/no_filter), Current aus
  `heatmap_field` (Restore gewinnt), E6-Feld-Nachreichung, Fallback-
  Roh-Item bei leerem Cache. SYNCHRON aus dem Datenpfad
  (`_sync_combos_from_payload`) UND dem VM-Pfad (`_sync_from_params` /
  neuer `_on_feature_ids_changed`-Handler) gerufen. `_sync_combos_from_payload`
  enthaelt einen Stale-Guard: `restore_generation`-Mismatch => Feld- und
  Agg-/Field-Metadaten bleiben unveraendert (nur x/y/agg mit VM-Prioritaet
  bestaetigt). `attach_view_model()` verbindet `feature_ids_changed` mit
  `_on_feature_ids_changed` (hasattr-Guard).
* `../../serviceui/master_tree.py`: `set_checked_feature_ids()` emittiert KEIN
  `checked_changed` mehr (programmatisches Set beim Oeffnen des
  Picker-Dialogs darf keine Feedback-Schleife ausloesen: checked_changed
  -> selection_ids_requested -> set_feature_ids wuerde den restaurierten
  Filter ueberschreiben). Nur Nutzer-Aktionen (`_on_item_changed`) und
  `clear_checks()` emittieren weiterhin. Plugin-Parents MIT Clones werden
  beim Reverse-Mapping weiterhin uebersprungen, die Clone-Haken folgen
  aber der plugin_id - der Filter bleibt vollstaendig erhalten.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_round8_bug345.py` (neu): **20/20 PASS** - synchroner
  Feld-Rebuild bei Check/Uncheck (srv_a / srv_a+srv_b / srv_b, XOR-
  Sammelregel), Stale-Payload mit alter Generation kloppt restauriertes
  Feld/Agg nicht, frischer Payload (Gen == aktuell) uebernimmt Feld-
  Metadaten, set_checked_feature_ids emittiert KEIN checked_changed,
  Reverse-Mapping erhaelt Filter ueber Clone-Haken (Plugin-Parent mit
  Clones non-checkable, 2 Clone-Haken), clear_checks emittiert weiterhin.
* Regressionen: `../../test/check_round7_fixes.py` **28/28 PASS**,
  `../../test/check_round7_picker_runtime.py` **PASS**,
  `../../test/check_restore_pipeline_bugfix.py` **30/30 PASS** (P2-Testblock an
  die neue Semantik angepasst: programmatisches Set ohne Signal,
  Nutzeraktion via _on_item_changed), `../../test/check_restore_pipeline_round2.py`
  **29/29 PASS**, `../../test/check_restore_pipeline_round3.py` **19/19 PASS**
  (P1+2 analog angepasst), `../../test/check_bug345_chain.py` **15/15 PASS**,
  `../../test/check_bug345_stale_hook.py` **PASS**, `../../test/check_bugfix_0808.py`
  **PASS**.
* `py_compile` aller 4 geaenderten Dateien: EXIT=0.

---

## 8h. Implementierungs-Log - Bugfix Runde 9+10: Varianten-granularer ServicePicker-Filter, No-Data-Differenzierung, Restore-Reihenfolge (10.08.2026)

**Problem (User-Bugreport 10.08.2026, Runden 9+10):**
(1) Check/Uncheck im ServicePicker filterte nur plugin_id-granular - das
Uncheck EINER Variante (Clone) zeigte keinen Effekt, weil die
Varianten-Einschraenkung (instance_hashes) nicht durch die Kette
MasterTree -> Dialog -> Window -> ViewModel -> Worker -> Repo -> Reader-SQL
gereicht wurde.
(2) resolve_no_data_variants markierte Varianten faelschlich als
'(No Data)', wenn die Daten unter einem anderen/veralteten Hash oder ohne
Hash (NULL, Alt-Bestand) geschrieben wurden; Set-Instanz-Varianten fehlten
komplett.
(3) Restore-Reihenfolge: Queries starteten VOR der UI-Combo-Synchronisierung
(leere/alte Controls -> _current_params() None -> Queries uebersprungen).
(4) Deterministischer Initial-Load: leere Symbol-Combo fuehrte zu
set_symbol("") und uebersprungenen Initial-Queries.
(5) Geometrie-Restore pruefte nur gegen primaryScreen - Positionen auf
Monitor 2 fielen auf den Fallback zurueck.

### Loesung

* `../../serviceui/master_tree.py` + `../../serviceui/service_selector_dialog.py`:
  Neue `selection_hashes_requested`-Kette (Runde 10, Bug 1) - der Dialog
  liefert die instance_hashes der gecheckten Clone-Varianten; das Window
  reicht sie an `set_feature_ids(ids, hashes)`.
* `../../analytics/engine/analytics_view_model.py`: `instance_hashes` als
  `_params`-Key + `_normalize_instance_hashes()`; `set_feature_ids()` mit
  optionalem `instance_hashes`-Parameter (None = bestehende Einschraenkung
  behalten); `_current_params()` gibt die Hashes in die Query-Params.
* `../../analytics/engine/analytics_worker.py` + `analytics_repository.py`:
  reichen `instance_hashes` an alle 5 Daten-Repo-Methoden durch.
* `../../analytics/engine/feature_store_reader.py`: `_apply_feature_filter()`
  baut die Hash-Bedingung `(instance_hash IS NULL OR LOWER(TRIM(instance_hash))
  IN (...))`; `available_instance_hashes()` liefert die Hash-Menge mit
  feature_data. `resolve_no_data_variants` differenziert (Bug 2): benannte
  Variante zaehlt NUR mit exaktem Hash-Match, pids_with_data-Fallback nur
  fuer NULL-Hash-Bestand; Set-Instanz-Varianten werden ueber
  generate_instance_hash erfasst.
* `../../analytics/ui/heatmap_widget.py`: '(No Data)'-Hinweise zentral in
  `_rebuild_field_dropdown()` gerendert (deckt Cache-Rebuild-Pfad ab);
  Hash-Filter im Payload-Pfad.
* `../../analytics/engine/analytics_view_model.py` (Bug 4): REIHENFOLGE
  `params_restored.emit()` VOR `refresh_all()` in `_apply_profile()` UND
  `restore_workspace()`.
* `../../analytics/ui/analytics_win.py` (Bug 3): Deterministischer `_initial_load`
  - Symbol-Combo wird vor dem Restore gefuellt (idempotent), Non-Empty-
  Guards, dann load_profiles()/restore_workspace()/_on_page_changed()/
  refresh_all().
* `../../persistent_win.py` + `../../serviceui/service_selector_dialog.py` (Bug 5):
  Geometrie-Restore prueft gegen ALLE Screens (`QApplication.screens()`),
  nicht nur primaryScreen.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_round10.py` (neu): **34/34 PASS** - Varianten-Filter-Kette
  (MasterTree -> Dialog -> VM -> Worker -> Repo -> Reader-SQL),
  No-Data-Differenzierung (exakter Hash-Match), Restore-Reihenfolge,
  Multi-Screen-Geometrie.
* Regressionen: `../../test/check_round9.py` **19/19 PASS**, Restore-Pipeline
  30/30+29/29+19/19 PASS, bug345-Kette 15/15 PASS, stale_hook PASS,
  check_round7_fixes 28/28 PASS, check_round8_bug345 20/20 PASS,
  picker_runtime PASS, check_bugfix_0808 PASS.
* `py_compile` aller geaenderten Dateien: EXIT=0.

## 8i. Implementierungs-Log - Bugfix Runde 11: No-Data-Auswertung in den Worker verlagert, Persistenz/Aliasing, zentrale Restore-Orchestrierung (10.08.2026)

**Problem (User-Analyse 10.08.2026, Punkte 1-5):**
(1) Kein zentraler Zustands-Sync: 3+ Quellen setzten die Controls
(params_restored -> _sync_from_params direkt im HeatmapWidget UND
_sync_ui_from_restored_params im Window; _sync_combos_from_payload im
Payload-Pfad; feature_ids_changed -> _rebuild_field_dropdown) - bis zu 3
Control-Paesse pro Restore plus Hauptthread-DB-Zugriffe.
(2) Datenvertrag-Luecke: `instance_hashes` fehlte im Profil-Payload
(Workspace-Datei persistierte die ViewModel-Referenz -> Aliasing); die
No-Data-Pruefung lief synchron im UI-Hauptthread mit verschluckten Fehlern.
(3) Restore-Pfade stiessen selbst refresh_all() an (Query-Orchestrierung
an mehreren Stellen, redundante Re-Queries).

### Loesung

* **Bug 3 (Persistenz/Aliasing):**
  - B3-1: `_current_payload()` (VM) persistiert `sources.instance_hashes`.
  - B3-2: Gemeinsamer Restore-Helper `_restore_params_from_payload()`
    (VM) fuer `_apply_profile()` UND `restore_workspace()` - fehlt
    `instance_hashes` im Payload (Alt-Payloads), ist der Filter garantiert
    leer (Replace-Semantik statt stillem Alt-Wert); uebrige Keys additiv.
  - B3-3: `_save_workspace` (Window) kopiert die VM-Params via neuem
    `_snapshot_params()` (kein Aliasing mit den Live-Params).
* **Bug 4 (No-Data in den Worker):**
  - B4-1: Synchroner `resolve_no_data_variants()`-Aufruf aus dem
    UI-Hauptthread entfernt. Neue Kette: VM `_no_data_presets_snapshot()`
    (in-memory Preset-Modell-Daten) -> `_current_params(QUERY_FEATURES)`
    -> Worker -> Repo `get_available_features(presets_data=...)` ->
    Reader `resolve_no_data_variants()` (im Worker-Thread).
  - B4-2: Payload-Vertrag `no_data_variants` IMMER vorhanden (+
    `no_data_variants_error`); UI unterscheidet loading / Erfolg+[] /
    Erfolg+[x] / Fehler ('No-Data-Pruefung konnte nicht durchgefuehrt
    werden').
  - B4-3: Generation-Guard in `_on_features_ready` (Stale-Payloads
    aelterer Restore-Generation werden verworfen).
  - B4-5: `_render_no_data_items()` filtert nach aktiven instance_hashes;
    gewaehlte No-Data-Variante bleibt zusaetzlich inline sichtbar.
* **Architektur (A1-A6):**
  - A1: `refresh_all()` aus `_apply_profile()`/`restore_workspace()`
    entfernt (kein Query mehr aus dem VM-Restore-Pfad; das Window
    orchestriert).
  - A3: Zentraler `_sync_all_pages_from_params()` (Window, genau EIN
    Durchgang); die direkte `params_restored`-Verbindung des
    HeatmapWidgets (attach_view_model) entfaellt.
  - A5: `_sync_combos_from_payload` schreibt die x/y/agg-Combos nicht
    mehr (Payload darf Controls nie ueberschreiben).
  - A6: `_on_page_changed` mit Query-Key-Pruefung (row +
    restore_generation + `_params_signature`) - kein redundanter
    Re-Query nach Restore/Sync.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_round11.py` (neu): **35/35 PASS** - B3-1..B3-3
  (Payload-Roundtrip, Replace-Semantik, Aliasing), B4-1..B4-5
  (No-Data-Kette, Payload-Vertrag, Generation-Guard, Hash-Filter),
  A1-A6 (kein refresh_all im VM, zentraler Seiten-Sync genau 1x,
  Payload schreibt keine Controls, Query-Key-Pruefung).
* Regressionen (an neues Design angepasst): `../../test/check_round10.py`
  **34/34 PASS** (B4-Assertions auf A1-Vertrag: params_restored ohne
  refresh_all), `../../test/check_round9.py` **19/19 PASS**,
  `../../test/check_round7_fixes.py` **28/28 PASS** +
  `../../test/check_round8_bug345.py` **20/20 PASS** (Restore-Sync via
  `_sync_from_params()` statt params_restored-Verbindung, A3; Mock-VMs um
  request_features ergaenzt), Restore-Pipeline 30/30+29/29+19/19 PASS,
  bug345-Kette 15/15 PASS, stale_hook PASS, picker_runtime PASS,
  check_bugfix_0808 PASS.
* `py_compile` aller 6 geaenderten Dateien: EXIT=0.
* Commit `9bb52f4` (Runde 11), Commit `3a61790` (Runde 9+10).

---

## 8j. Implementierungs-Log - Bugfix Runde 13: Dropdown-NoData - variantengenauer Reader-Filter & instance_hashes fuer Set-Instanz-Varianten (10.08.2026)

**Problem (User-Meldung 10.08.2026, zwei seit langem bestehende Dropdown-Fehler im Analytics-NoData-Bereich):**
(1) Das '(No Data)'-Dropdown zeigte immer die ERSTE Variante eines Services,
auch wenn im ServicePicker eine andere Variante gecheckt war (falsche
Variante).
(2) Das '(No Data)'-Dropdown zeigte Services/Varianten an, die im
ServicePicker gar nicht gecheckt waren.

**Root Cause:** Die kanonische Datenstruktur 'gecheckte Variante' ist
`instance_hashes` im ViewModel. Diese wurde im MasterTree nur fuer
TYPE_CLONE-Knoten (Standalone-Presets) befuellt - Set-Instanz-Varianten
(TYPE_SERVICE) verloren ihren `instance_hash` in der Check-Sync-Kette:
- `_sync_checked_from_tree()` speicherte 3-Element-Keys
  `(TYPE_SERVICE, set_id, instance_id)` ohne Hash.
- `checked_services()` lieferte keinen Hash fuer TYPE_SERVICE.
- `checked_instance_hashes()` sammelte nur aus TYPE_CLONE.
-> `instance_hashes` blieb fuer Set-Instanzen leer: `_selected_no_data_
variant()` griff auf den 'erste Variante des Services'-Fallback zurueck
(Fehler 1), und `_render_no_data_items()` konnte ungecheckte Instanzen
nicht per Hash filtern (Fehler 2). Zusaetzlich filterte der
`presets_data`-Snapshot nur auf Plugin-Ebene.

### Loesung

* `../../serviceui/master_tree.py` (E1-E7): Check-Keys der Set-Instanz-Varianten
  (TYPE_SERVICE) sind jetzt 4-elementig - inkl. `instance_hash`
  (`_build_set_item`, Check-Handler, TYPE_SET-Branch,
  `_sync_checked_from_tree`). `checked_services()` liefert `instance_hash`
  fuer SERVICE/PLUGIN/CLONE (generisches Unpacking, abwaertskompatibel).
  `checked_instance_hashes()` sammelt Hashes ALLER gecheckten Varianten
  (vorher nur TYPE_CLONE). `set_checked_feature_ids()` wendet die
  Hash-Restriktion jetzt auch auf TYPE_SERVICE an (analog TYPE_CLONE) und
  fuegt den 4er-Key hinzu.
* `../../analytics/engine/analytics_view_model.py`: `_no_data_presets_snapshot()`
  berechnet `active_hashes` aus `_params["instance_hashes"]` und liefert
  sie als neuen Snapshot-Schluessel.
* `../../analytics/engine/feature_store_reader.py`: `resolve_no_data_variants()`
  liest `active_hashes` aus dem Snapshot und filtert in `_add()`
  variantengenau (`if active_hashes and h_s.lower() not in active_hashes:
  return`) - der Payload enthaelt nur noch die im ServicePicker gecheckten
  Varianten.
* `../../analytics/ui/heatmap_widget.py`: `_selected_no_data_variant()` - der
  'erste Variante des Services'-Fallback ist ersatzlos entfernt; es wird
  nur noch die (einzige) Variante des aktuellen Feld-Services aus dem
  variantengefilterten Payload zurueckgegeben. `_render_no_data_items()`
  haelt die Widget-Filter (feature_ids/instance_hashes) DEFENSIV aktiv
  (schuetzt gegen Alt-Payloads vom QUERY_FEATURES-Kompatibilitaetspfad
  ohne Hash-Filter).

### Verifikation (headless, keine UI-Tests)

* `test/_verify_mastertree.py` (neu): **9/9 PASS** - statische Checks der
  E1-E7-Ersetzungen in master_tree.py.
* `../../test/check_round12.py` (aktualisiert, Runde-13-Semantik): **23/23 PASS**
  - B3/B3b an den variantengenauen Payload angepasst (gecheckte Variante
  gewinnt statt erster Variante; Payload ohne srv_x-Variante -> kein
  V1-Fallback), neue C4/C5-Checks (Reader-`active_hashes`-Filter: nur
  gecheckte Variante h2 geliefert, ohne Einschraenkung alle; VM-Snapshot
  liefert `active_hashes`-Schluessel).
* Regressionen: `../../test/check_round11.py` **35/35 PASS** (B3-1..B3-3,
  B4-1..B4-5, A1-A6 unveraendert gruen).
* `py_compile` aller 4 geaenderten Dateien (System- + venv-Python): EXIT=0.
* Commit `8a72c8a` (Runde 13), Commit `993ad46` (Runde 12+12b).

---

## 8k. Implementierungs-Log - Runde 13b: MasterTree-On-the-fly-Hash & Hash-Persistenz (10.08.2026)

**Problem (aus Runde 13b-Analyse, 10.08.2026):** Die Runde-13-Entscheidung
(8j) lieferte `instance_hashes` fuer Set-Instanz-Varianten (TYPE_SERVICE),
aber zwei Luecken blieben offen:

1. **On-the-fly-Hash:** Set-Instanz-Varianten OHNE gespeicherten
   `instance_hash` (z. B. Altsets, deren `service_sets`-Definition noch
   keinen Hash traegt) bekamen keinen Hash zugewiesen - die
   Hash-Restriktion (`set_checked_feature_ids`) und
   `checked_instance_hashes()` konnten sie nicht erfassen. Damit fehlte
   eine stabile Varianten-Identitaet fuer den Reader-Filter.
2. **Hash-Persistenz:** Neue/gespeicherte Set-Instanzen persistierten den
   `instance_hash` nicht in der Set-Definition (`_add_service_to_set` und
   der Dialog-Add-Pfad schrieben die Instanz ohne Hash in `service_sets`) -
   die Hash-Identitaet ging beim naechsten Laden verloren.

### Loesung

* `../../serviceui/master_tree.py`:
  * `_build_set_item`: Set-Instanz ohne `instance_hash` erhaelt einen
    on-the-fly-Hash via `generate_instance_hash(plugin_id, params)`
    (deterministisch, Q3/Q4 - gleicher Hash wie der Writer).
  * `checked_instance_hashes()` und die Check-Sync-Kette nutzen diesen
    on-the-fly-Hash auch dann, wenn die Instanz keinen gespeicherten Hash
    traegt (Hash-Restriktion greift damit auch fuer Altsets).
* `../../serviceui/service_win.py`: `_add_service_to_set` persistiert den
  `instance_hash` der neuen Set-Instanz in die Set-Definition.
* `../../serviceui/service_selector_dialog.py`: Der Add-Pfad des
  Service-Pickers persistiert den `instance_hash` analog.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_round13b.py` (neu): **9/9 PASS** - T1/T2 (On-the-fly-Hash
  gesetzt / vorhandener Hash unveraendert), T3 (`checked_instance_hashes`
  liefert on-the-fly-Hash), T4 (Snapshot-Clones nur gecheckte Variante +
  `active_hashes`), T5 (Snapshot ohne active_hashes -> alle Clones),
  T6/T7 (Hash-Persistenz in `_add_service_to_set` und Dialog-Add-Pfad,
  Modul-Import `generate_instance_hash`).
* `test/_verify_mastertree.py` (aktualisiert): **ALL OK** - E1b
  (build_set_item on-the-fly-Hash), E7 (4er add service) u. a.
* `py_compile` aller 3 geaenderten Dateien: EXIT=0.

---

## 8l. Implementierungs-Log - Runde 13c: feature_data-Migration, Alt-Bestand-Fallback & Kernwunsch leeres Snapshot (10.08.2026)

**Problem (User-Freigabe 10.08.2026):** Die Runde-13-Fixes (8j) waren
korrekt, aber die zwei urspruenglichen Dropdown-Bugs bestanden empirisch
fort, weil der Reader die Datenlage anders beurteilte als die DB:

1. **Falsche Variante bei (No Data):** `srv_proximity` (6 Timeframes,
   ~593K Rows) und `native` (3000 Rows) hatten in `feature_store`
   **befuellte Alt-Spalten** (`ema_diff`, `atr_normalized`,
   `grid_nearest_level`, `grid_dist_abs`, `grid_dist_pct`,
   `is_time_window_active`), aber **`feature_data` = NULL**. Der Reader
   definiert 'hat Daten' aber ausschliesslich ueber `feature_data`
   (19.02-Kanon) - die Set-Instanz `proximity` (Hash `a392915e`) matchte
   nichts und wurde faelschlich als '(No Data)' gemeldet, obwohl 99K
   M1-Zeilen vorhanden waren.
2. **Phantom-Eintraege:** Bei leerem Filter ('kein Filter = alle') lieferte
   der leere `feature_ids`-Filter ALLE NoData-Varianten des
   Service-Modells in den Payload - ungecheckte Services erschienen
   trotz Runde-13-Filter im Dropdown.

### Loesung

* **Migration (Daten-Bestand):** `test/_migrate_feature_data.py` fuehrt
  `UPDATE feature_store SET feature_data = json_object(...)` (6 Keys +
  `schema_version`) fuer alle Rows mit `feature_data IS NULL` aus -
  Alt-Spalten-Bestand wird damit in den kanonischen JSON-Vertrag
  ueberfuehrt. Backup vor der Migration:
  `../../test/backup_analytics_before_fd_migration.duckdb`. Ergebnis:
  **573.468 srv_proximity + 3.000 native migriert; 0 Rows mit NULL.**
  Dry-Run vorab auf `test/_migrate_test_copy.duckdb` verifiziert.
* `../../analytics/engine/feature_store_reader.py`:
  * Neu (read-only): `plugin_ids_with_hashes(symbol, timeframe)` ->
    Set der plugin_ids mit mind. einer `instance_hash`-Zeile; faengt
    DB-Fehler intern ab und liefert `set()` (Invariante: rein lesend).
  * `resolve_no_data_variants()`: `_has_data`-Fallback fuer Alt-Bestand -
    liegt die plugin_id NICHT in `pids_with_hashes` (Bestands-Abfrage
    erfolgreich), stammt ihr gesamter Bestand aus undifferenzierten
    Alt-Rows ohne Hash und deckt JEDE Variante ab (`has_data=True`).
    `pids_with_hashes is None` (Abfragefehler) behaelt die konservative
    Runde-10-Semantik (kein Fallback auf unbekannter Basis).
* `../../analytics/engine/analytics_view_model.py`: `_no_data_presets_snapshot()`
  liefert bei leerem `feature_ids`-Filter sofort
  `{"presets": {}, "sets": [], "display_names": {}, "active_hashes": []}`
  (Kernwunsch: 'Aktive Filter entfernen' zeigt danach alle Features OHNE
  NoData-Rauschen).
* `../../analytics/ui/heatmap_widget.py`:
  * `_render_no_data_items()`: `active_ids`-Check ganz oben - bei leerem
    Filter wird weder der No-Data-Abschnitt noch der Fehler-/Loading-
    Hinweis gerendert (Guard gegen Alt-/Stale-Payloads).
  * `_selected_no_data_variant()` (Bug-1-Absicherung): Bei Payloads mit
    mehreren No-Data-Varianten desselben Services gewinnt DEFENSIV die
    im ServicePicker gecheckte Variante (instance_hash in
    `instance_hashes`); erst ohne Hash-Match faellt die Auswahl auf den
    ersten Service-Treffer zurueck.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_round13c.py` (neu): **20/20 PASS** - A: Migration (keine
  NULL-Rows mehr, JSON-Keys, Schema-Version), B: Reader-Fallback
  (Alt-Bestand deckt jede Variante ab; Abfragefehler -> konservativ),
  C: Kernwunsch (leerer Filter -> leeres Snapshot), D: UI-Logik
  (render-Guard, Hash-Match in `_selected_no_data_variant`).
* Regressionen:
  * `../../test/check_round11.py`: **35/35 PASS** (`_FakeReader` overridet
    `plugin_ids_with_hashes` -> `{"srv_a"}`; Widget-Tests 'frischer
    Payload'/'Fehlerzustand' mit aktivem Filter).
  * `../../test/check_round12.py`: **23/23 PASS** (A6 mit aktivem Filter,
    C1 auf Kernwunsch-Semantik umgestellt: leerer Filter -> leeres
    Snapshot statt 'alle Presets').
  * `../../test/check_round13b.py`: **9/9 PASS**, `test/_verify_mastertree.py`:
    **ALL OK**.
* `py_compile` aller 6 geaenderten Quelldateien + aller betroffenen
  Testdateien: EXIT=0.
* Cleanup: Diagnose-Skripte (`_diag_*.py`, `_dryrun_migration.py`) und
  `_migrate_test_copy.duckdb` entfernt; `_migrate_feature_data.py`
  (Migrationswerkzeug), `check_round13c.py` und das Backup bleiben in
  `../../test` (Testdateien gitignored).

---

## 8m. Implementierungs-Log - Bugfix Runde 14: Dropdown-NoData zeigt nichts mehr fuer zweite Variante ohne Daten (10.08.2026)

**Problem (User-Bugreport 10.08.2026, direkt nach Runde 13c):** Das
'(No Data)'-Dropdown zeigte GAR KEINE NoData-Anzeige mehr, obwohl eine
gecheckte Version (zweiter Eintrag) ohne Daten existierte.

**Root Cause:** Der Runde-13c-Alt-Bestand-Fallback in
`resolve_no_data_variants` war zu grob: Liegen die `feature_store`-Daten
einer plugin_id ausschliesslich als undifferenzierte Alt-Rows vor
(`instance_hash IS NULL`, z. B. `srv_proximity` mit 593K Rows), galt
**JEDE** Variante des Services als 'hat Daten'. Eine neu erzeugte zweite
Variante (anderer Hash, noch nie berechnet) wurde damit faelschlich als
datenreich eingestuft -> kein '(No Data)'-Eintrag, obwohl sie nie
gelaufen ist.

### Loesung

* `../../analytics/engine/feature_store_reader.py`:
  * Der Alt-Bestand-Fallback greift jetzt NUR fuer die ERSTE aktive
    Variante je plugin_id im Snapshot (`first_hash_by_pid`, Reihenfolge
    wie im ServicePicker: Presets/Clones zuerst, dann Set-Instanzen mit
    on-the-fly `generate_instance_hash`). Der undifferenzierte
    Alt-Bestand gehoert der Original-Instanz, die ihn vor der Hash-Aera
    geschrieben hat.
  * Weitere Varianten derselben plugin_id brauchen einen echten
    `instance_hash`-Treffer in `available_instance_hashes`, sonst
    erscheinen sie als '(No Data)'.
  * Docstrings praezisiert ('ORIGINAL-Variante' statt 'jede Variante').

### Verifikation (headless, keine UI-Tests)

* `../../test/check_round14.py` (neu, echte DB `../../data/analytics.duckdb`):
  **8/8 PASS** - V1 (Original, Hash `a392915e`) mit Alt-Bestand ->
  kein NoData; V2 (Kopie, anderer Hash, nie gelaufen) -> '(No Data)'
  (auch wenn nur V2 gecheckt); einzige Variante + Alt-Bestand -> kein
  NoData (Regression 13c); Fake-DB ohne Tabelle -> konservative
  Runde-10-Semantik (beide Varianten NoData).
* Regressionen: `../../test/check_round13c.py` **20/20 PASS**,
  `../../test/check_round12.py` **23/23 PASS**, `../../test/check_round11.py`
  **35/35 PASS**, `../../test/check_round13b.py` **9/9 PASS**,
  `test/_verify_mastertree.py` **ALL OK**.
* `py_compile`: EXIT=0.
* Cleanup: Diagnose-/Fix-Skripte (`_diag_round14*.py`,
  `_fix_reader_docstring.py`) entfernt; `check_round14.py` bleibt
  als Regressionstest (gitignored).

---

# 20.05 Architektur-Konzept: Ultra-Low-Latency Control & Rendering Pipeline

> **Status:** Umgesetzt und headless validiert (Runden 11–15c der Analytics-Pipeline, Stand 10.08.2026). Rein konzeptionelles Kapitel – kein Arbeitsschrittplan; die Umsetzung ist in den Runden 11–15c vollständig realisiert (Runde 15: Performance-Diagnose Dropdown – Metadaten-Cache & QUERY_FEATURES-Leichtpfad; Runden 15b/15c: Bugfix-Durchgänge Feld-Dropdown & Standalone-NoData, Kapitel 7/8).
> **Primäres Ziel:** Absolut latenzfreie Bedienung aller Steuerelemente (Aggregationen, Dropdown-Checklisten, Profil-Speicherung, Workspace-Mechanismus, ServicePicker-Haken) unabhängig von Datenbank-Ladezeiten und Grafik-Rendern.

Prämissen:

1. **Latenzfreie Control-Schicht (Optimistic UI):** Jede Benutzeraktion an Bedienelementen schlägt *sofort* im lokalen State (ViewModel) durch und wird *sofort* optisch dargestellt. Es gibt keine Blockaden durch DB-Abfragen im Hauptthread.
2. **Vollständige Erhaltung der Historie:** Die gesamte Speicher-/Restore-Logik für Fenster, Workspaces und Profile bleibt über das State-Management (`StateManager`, Repositories) lückenlos intakt.
3. **Isolierte Grafik-Welt:** Slider-Aktionen, Maus-Zooms oder Canvas-Neuaufbauten triggern *nur* die visuelle Darstellung (Rendering-Welt). Sie manipulieren niemals das State-Management oder die Event-Logik der Controls.
4. **Asynchrone Datennachführung:** Daten-Queries und Canvas-Renderings laufen asynchron über Worker-Threads. Sie „beobachten“ den aktuellen Control-State, blockieren ihn aber zu keinem Zeitpunkt.

> **Prämissen-Check (Codebasis, 10.08.2026):** Alle vier Prämissen sind in der Implementierung verifiziert: (1) `set_feature_ids()`/Picker-Haken schlagen sofort im VM-State durch und triggern nur den Debounce-Timer – kein Hauptthread-DB-Zugriff; (2) Profile (`_current_payload()` v2-sectioned inkl. `instance_hashes`) und Workspaces (`StateManager` → `WindowStateRepository.workspace_state`, `_keep_history_on_close=True`, `INSTANCE_ID="win_analytics"`) sind lückenlos persistent; (3) Grafik-Interaktionen (z. B. `set_heatmap_zoom()`) werden rein client-seitig angewandt – kein DB-Requery, keine Event-Logik der Controls; (4) alle Daten-Queries laufen über `AnalyticsAsyncWorker` (QThread) mit Debounce-Pufferung und DbPool-Connections.

---

## 1. Die entkoppelten Drei-Welten-Architektur

```
 ┌───────────────────────────────────────────────────────────┐
 │ 1. CONTROL- & INPUT-WELT (Latenzfrei, Sofort-Feedback)    │
 │    - Dropdowns, Checklisten, ServicePicker, Profile       │
 │    - Aktualisiert den lokalen VM-State in Mikrosekunden   │
 └─────────────────────────────┬─────────────────────────────┘
                               │ (Direktes State-Update & Sofort-Sync)
                               ▼
 ┌───────────────────────────────────────────────────────────┐
 │ 2. PERSISTENZ- & STATE-WELT (ViewModel & Repositories)    │
 │    - Verwaltet Profile, Workspaces, Instanzen (DuckDB)    │
 │    - Dispatcht asynchrone Background-Worker               │
 └─────────────────────────────┬─────────────────────────────┘
                               │ (Asynchrone Payloads & no_data_variants)
                               ▼
 ┌───────────────────────────────────────────────────────────┐
 │ 3. RENDERING-WELT (Canvas, Charts & UI-Pages)             │
 │    - Zeigt Daten an, verarbeitet Zooms & Maus-Aktionen     │
 │    - Völlig unabhängig von der Bedienbarkeit der Controls │
 └───────────────────────────────────────────────────────────┘

```

---

## 2. Die Regeln für latenzfreie Bedienelemente (Control-Logik)

* **Keine Hauptthread-DB-Abfragen beim Klick:** Methoden wie die No-Data-Auswertung oder komplexe Validierungen laufen *niemals* synchron im Hauptthread, wenn der Anwender eine Checkbox klickt oder ein Dropdown bedient. Sie wurden in die asynchronen Worker-Abfragen verlagert – `QUERY_FEATURES` für das Feature-Dropdown sowie `QUERY_HEATMAP_GENERIC` für die generische Heatmap (Runde 12, Option A: No-Data-Auswertung im selben Grafik-Payload, kein zweiter serieller Roundtrip).
* **Sofortige UI-Sync (Optimistic Local State):** Ein Klick im ServicePicker ändert *sofort* den internen Zustand im ViewModel und schaltet das Control um. Das ViewModel emittiert ein leichtgewichtiges Signal (`feature_ids_changed` oder `params_restored` mit blockierten Signalen via `blockSignals(True)`), damit verbundene Combos ohne Wartezeit aktualisiert werden.
* **Getrennte Grafik-Interaktionen:** Interagiert der Anwender mit dem Canvas (z. B. Zoom, Ausschnitt verschieben, Chart-Skalierung), verarbeitet die Rendering-Welt das *lokal*. Das ViewModel bekommt davon nichts mit, es sei denn, es handelt sich um eine finale Bereichs-Auswahl. Das verhindert das gegenseitige Aufschaukeln von Event-Schleifen.

---

## 3. Behebung der Persistenz- & Varianten-Lücken (Bugs 3 & 4)

### Bug 3: Lückenlose Varianten-Persistenz (Clones & `instance_hashes`)

* **Problem:** `instance_hashes` wurden im Profil-Payload (`_current_payload()`) vergessen, wodurch beim Laden von Profilen die feingranularen Clone-Auswahlfilter verloren gingen.
* **Umsetzung:**
1. `_current_payload()` sichert `instance_hashes` in der `sources`-Sektion ab.
2. `_apply_profile()` und `restore_workspace()` nutzen einen gemeinsamen Helfer (`_restore_params_from_payload`), der fehlende Keys in Alt-Profilen strikt auf `[]` zurücksetzt (kein Mitschleppen alter Hashes).
3. `_save_workspace` sichert Parameter als saubere flache Kopie (`dict(...)` mit `list(...)`), um jegliches Python-Dict-Aliasing auszuschließen.



### Bug 4: Asynchrone "(No Data)"-Erkennung ohne UI-Latenz

* **Problem:** Der Versuch, fehlende Datenvarianten synchron während des UI-Aufbaus im Hauptthread zu berechnen, führte zu UI-Hängern und verdeckten Fehlern.
* **Umsetzung (Runden 11–14):**
1. **Worker-Auslagerung (Runde 11, B4-1/B4-2):** Die Ermittlung von `no_data_variants` läuft ausschließlich im Worker-Thread (eigener Thread, eigene DB-Connection) – sowohl im `QUERY_FEATURES`-Pfad als auch im `QUERY_HEATMAP_GENERIC`-Pfad (Runde 12, Option A: Auswertung im selben Grafik-Payload, damit aktualisiert sich das Dropdown mit/knapp nach der Grafik statt erst nach einem zweiten seriellen Roundtrip).
2. **Snapshot-Übergabe:** Das ViewModel übergibt einen leichten, rein im RAM liegenden Preset-Snapshot (`_no_data_presets_snapshot()`) an die Query-Parameter; die DB-Fakten (`available_instance_hashes` / `feature_keys_by_service`) ermittelt der Reader im Worker-Thread.
3. **Varianten-Genauigkeit (Runde 13/13b):** Der Reader prüft über `active_hashes` *nur noch* die im ServicePicker tatsächlich aktivierten Varianten; bei aktiver Einschränkung liefert auch eine hash-lose Variante nie "(No Data)" – falsche "(No Data)"-Anzeigen oder das versehentliche Vorauswählen falscher Einträge im Dropdown sind damit physikalisch ausgeschlossen.
4. **Alt-Bestand & leerer Filter (Runde 13c/14):** Ein leerer Datenquellen-Filter (`feature_ids=[]`) erzeugt keinerlei "(No Data)"-Einträge (der Button „Aktive Filter entfernen“ zeigt danach wieder alle Features ohne Rauschen); undifferenzierte Alt-Rows ohne `instance_hash` decken ausschließlich die Original-Variante einer `plugin_id` ab (z. B. `srv_proximity`-Altbestand) – weitere Varianten derselben `plugin_id` erscheinen weiterhin korrekt als "(No Data)", bis der erste Scan lief.
5. **Standalone-Services (Runde 15c):** Registrierte Plugins ohne Presets/Clones UND ohne Set-Instanz (z. B. `srv_trend_breakout`) werden über die neue Snapshot-Sektion `standalone` als hash-lose Variante in die Auswertung aufgenommen – ein noch nie ausgeführter Standalone-Service erscheint damit korrekt als "(No Data)", bis der erste Scan Daten schreibt (siehe Kapitel 8).

---

## 4. Ergänzende Mechanismen der Latenzfreiheit (implementiert)

* **Debounce & Query-Pufferung:** Der ViewModel puffert angeforderte Queries in `_pending_kinds` und startet sie seriell über einen Single-Shot-`QTimer` (200–300 ms). Klick-Serien erzeugen keinen Query-Stau; ein laufender Worker wird durch den nächsten Start nie abgebrochen (Race-Guard `self._worker is worker` verwirft verspätete Ergebnisse alter Worker).
* **`restore_generation` (Stale-Payload-Schutz):** Bei jedem `restore_workspace()`/`_apply_profile()` erhöht der ViewModel ein Generations-Token, das über die Query-Params in die Worker wandert und im Ergebnis gespiegelt wird. Die UI verwirft Payloads älterer Generation – Queries, die VOR einem Restore gestartet wurden, überschreiben den synchron restaurierten Zustand nicht.
* **Query-Key-Deduplizierung:** Das AnalyticsWindow fordert Seitendaten nur an, wenn sich der Query-Key ändert (Seiten-Index + `restore_generation` + Params-Signatur) – identische Anforderungen lösen keinen redundanten Re-Query aus.
* **Zentraler UI-Sync statt `refresh_all()` im Restore:** Nach `params_restored` synchronisiert das AnalyticsWindow die Seiten-Combos in genau einem Durchgang mit `blockSignals(True)` (`_sync_ui_from_restored_params` → `_sync_all_pages_from_params` → `_request_current_page_data`). `refresh_all()` bleibt nur dem expliziten User-Refresh vorbehalten.
* **UI-Zustände ohne Query:** Reine UI-Settings (Tabellen-Spaltenbreiten, Zeilenhöhe, Sortierung, Zoom-Bereiche) markieren nur das Dirty-Flag bzw. werden client-seitig angewandt – kein DB-Requery, keine Worker-Runde.
* **`busy_changed` & `missing_services_detected`:** Laufende Queries zeigen einen Spinner; fehlende (entfernte/umbenannte) Services im Restore werden gemeldet, ohne den restaurierten Filter stillschweigend zu kürzen (Graceful Degradation).

## 5. Bekannte Grenzen (bewusst unverändert)

* **Entfernter synchroner Altbestand (Runde 15):** Die ViewModel-Methode `resolve_no_data_variants(symbol, timeframe)` (synchroner Reader-Zugriff im aufrufenden Thread, zuletzt `analytics_view_model.py` ~Z. 1413) wurde in Runde 15 **entfernt** – sie hatte seit Runde 11 keinen einzigen Aufrufer mehr (der produktive Pfad läuft vollständig über den Worker-Snapshot `presets_data`). Die Open/Closed-Regel schützt aktive Logik; toter Code ohne Aufrufer ist davon ausdrücklich ausgenommen. Verifiziert über `check_round9.py`/`check_round10.py` (19/19, 34/34), die vollständig auf dem Reader-/Worker-Pfad laufen.
* **Abgrenzung der Latenzgarantie:** Die Aussage „läuft niemals synchron im Hauptthread" gilt für den tatsächlich verdrahteten Pfad (Controls → VM → Debounce → Worker) als Code-Invariante – mit dem entfernten Altbestand existiert im Analytics-Pfad kein synchroner DB-Zugriff mehr.


---

## 6. Implementierungs-Log – Runde 15: Performance-Diagnose Dropdown (10.08.2026)

**Problem (User-Meldung, 10.08.2026):** Das Analytics-'Feld'-Dropdown und die '(No Data)'-Hinweise brauchten beim Öffnen mehrere Sekunden – die Feature-Metadaten wurden erst NACH der teuren Heatmap-Pivot-Aggregation sichtbar.

**Root-Cause-Analyse (4 Engpässe):**
1. **Root Cause 1:** `QUERY_FEATURES` war deaktiviert; das Feld-Dropdown wartete auf das Grafik-Payload (`QUERY_HEATMAP_GENERIC` inkl. Pivot-Aggregation).
2. **Root Cause 2:** `feature_keys_by_service` / `available_feature_keys` / `available_instance_hashes` / `plugin_ids_with_hashes` scannten den feature_store bis zu 6× pro Update (Voll-Scans inkl. feature_data-JSON-Parsing).
3. **Root Cause 3:** Kein Caching der stabilen Metadaten (ändern sich nur bei `store_plugin_payload()`).
4. **Root Cause 4:** `feature_keys_by_service` lief je Zyklus doppelt (Dropdown + No-Data-Auswertung).

### Lösung (Fixes 1–3)

* **Fix 3 (Metadaten-Cache, `feature_store_reader.py`):** Gemeinsamer Basis-Scan `_feature_meta_base(symbol, timeframe)` – **GENAU EIN** DuckDB-Zugriff für alle 4 Metadaten-Methoden. In-Memory-Cache (`_meta_cache` + `_meta_lock`, threadsicher für die gemeinsame Reader-Instanz) mit Invalidation via `feature_cache_last_invalidated` (feature_builder, Invariante 13 – wird bei jedem `store_plugin_payload()` aktualisiert); defensiver Notausgang `invalidate_meta_cache()`. Die `feature_ids`/`instance_hashes`-Filter laufen als Python-Filter auf dem Cache (Semantik identisch zur bisherigen SQL-IN-Clause: case-insensitiv, whitespace-tolerant, NULL-Hash-Pass-through – Runde-10/13c-Vertrag unverändert).
* **Fix 1 (QUERY_FEATURES-Leichtpfad, `analytics_repository.py` / `analytics_worker.py` / `heatmap_widget.py`):** Neuer Helfer `_field_metadata(symbol, timeframe, feature_ids, instance_hashes)` → `(metrics, field_sources)`, genutzt von `get_generic_heatmap` UND `get_available_features`. Der QUERY_FEATURES-Payload trägt jetzt `metrics` + `field_sources` – das Feld-Dropdown + '(No Data)' kommen ohne die teure Heatmap-Pivot-Aggregation. `heatmap_widget.request_data()` reaktiviert `request_features()` **vor** `request_heatmap_generic()`.
* **Fix 2 (durch Fix 3 abgedeckt):** Beide Aufrufer (`_field_metadata` / `resolve_no_data_variants`) teilen sich den gecachten Basis-Scan – keine doppelte Scan-Last mehr; kein Signatur-Umbau nötig.
* **Code-Cleanup (separat committet):** Toter synchroner VM-Code `resolve_no_data_variants` (`analytics_view_model.py`, seit Runde 11 ohne Aufrufer) entfernt – siehe §5.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_round15_perf.py` (neu): **27/27 PASS** – Basis-Scan = 1 DB-Zugriff für 4 Metadaten-Methoden, Zweitaufruf = 0 Zugriffe (Cache), Invalidation via `store_plugin_payload` (neuer Key sichtbar), Python-Filter-Semantik (case-insensitiv/whitespace, NULL-Hash-Pass-through, numeric_only-Trennung), No-Data-Semantik, QUERY_FEATURES-Leichtpfad (metrics/field_sources identisch zum Heatmap-Pfad), defensiver Notausgang.
* Regression: `check_round12.py` (23/23 – A5: `request_features()` vor `request_heatmap_generic()` in der Quelldatei), `check_round11.py` (35/35), `check_round9.py` (19/19), `check_round10.py` (34/34), `check_2004_bugfix3.py` (15/15), `check_round14.py` (8/8). `py_compile` aller geänderten Dateien OK.
* `check_round13c.py` war während der Verifikation **nicht ausführbar**: `../../data/analytics.duckdb` war von der laufenden App exklusiv gesperrt (PID 32608, IO-Error „File is already open") – der Test liest die echte DB und wird nach App-Ende nachgeholt.
* **Offen (manuell):** Funktions-/Latenztest des Dropdowns in der laufenden App durch den Anwender.

---

## 7. Implementierungs-Log – Runde 15b: Bugfix Feld-Dropdown (User-Meldung, 10.08.2026)

**Problem (User-Symptome, 10.08.2026):**
1. Check/Uncheck aus dem ServicePicker wird nicht im 'Feld'-Dropdown sichtbar.
2. Versionen (Parameter-Varianten) werden nicht mehr verarbeitet und angezeigt.
3. Services/Variationen mit NoData erscheinen nicht mit '(No Data)'.

**Root Cause (Runde-15-Regression):** `_field_metadata` rief `feature_keys_by_service` MIT `instance_hashes` auf. Bei einer gecheckten NoData-Variante (Hash ohne DB-Rows) war `by_service` leer → der ungefilterte Fallback `avail` zeigte ALLE Keys aller Services OHNE Service-Prefix und ignorierte die Datenquellen-Auswahl. Zusätzlich aktualisierte `set_feature_ids` den QUERY_FEATURES-Leichtpfad nicht (Cache blieb auf dem letzten Payload).

### Lösung (Fixes A/B)

* **Fix A (`analytics_repository.py`, `_field_metadata`):** Die Feld-Struktur folgt den **Services** (`feature_ids`), nicht den Varianten (`instance_hashes`) – eine gecheckte NoData-Variante blendet den aktiven Service nicht mehr aus der Feld-Metadaten aus. Der defensive Fallback `avail` (alle Keys) greift NUR ohne aktiven Filter (bei aktivem Filter ist eine leere `by_service`-Menge ein legitimes Ergebnis).
* **Fix B (`analytics_view_model.py`, `set_feature_ids`):** Refresht jetzt `(QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC, QUERY_SCATTER, QUERY_DISTRIBUTION)` mit **QUERY_FEATURES zuerst** – das Dropdown bekommt `field_sources`/`no_data_variants` für die aktuellen Filter (kein Warten auf den Grafik-Payload).

### Verifikation (headless, keine UI-Tests)

* `../../test/check_round15b.py` (neu): **10/10 PASS** – Feld-Scope folgt den aktiven Services (kein ungefilterter Fallback bei aktivem Filter), NoData-Variante gecheckt liefert trotzdem die Felder des aktiven Services, Dropdown zeigt Service-Prefix-Items + '(No Data)'-Item, `set_feature_ids` stellt QUERY_FEATURES in die Puffer-Queue (Reihenfolge).
* Regression: `check_round15_perf.py` (27/27), `check_round12.py` (23/23), `check_round11.py` (35/35), `check_round13c.py` (20/20), `check_round9.py` (19/19), `check_round10.py` (34/34), `check_2004_bugfix3.py` (15/15), `check_round14.py` (8/8). `py_compile` aller geänderten Dateien OK.
* **Offen (manuell):** Dropdown-Verhalten in der laufenden App durch den Anwender.

---

## 8. Implementierungs-Log – Runde 15c: Standalone-Services in der NoData-Auswertung (10.08.2026)

**Problem (User-Meldung, 10.08.2026):** Der Service `srv_trend_breakout` wird nicht im Dropdown erkannt und nicht in der noData-Sektion angezeigt.

**Diagnose (echte DB, `test/_diag_trend.py`):** `srv_trend_breakout` ist ein **Standalone-Service** – registriertes Plugin, das weder Presets/Clones (`plugin_presets()`) noch eine Set-Instanz (`get_sets()`) besitzt und noch keine feature_store-Rows geschrieben hat (DISTINCT feature_ids: `native`, `srv_grid_lines`, `srv_proximity`, `srv_swing_volume_profile`).

**Root Cause:** `_no_data_presets_snapshot()` sammelte NUR `model.plugin_presets()` (Clones) + `model.get_sets()` (Set-Instanzen). Reine Standalone-Services fielen komplett aus dem Snapshot → der Reader `resolve_no_data_variants()` konnte sie nie als '(No Data)' liefern.

### Lösung (Fixes A/B)

* **Fix A (`analytics_view_model.py`, `_no_data_presets_snapshot`):** Neue Snapshot-Sektion **`standalone`** – registrierte Plugins ohne Presets UND ohne Set-Instanz werden als hash-lose Variante (`preset_name 'Default'`) aufgenommen; `display_names["{pid}|Default"]` via `resolve_service_display_name` (→ 'Trend Breakout'). Ausgeschlossen sind Plugins mit Presets/Set-Instanzen (dort läuft die bestehende Preset-/Set-Auswertung) sowie – konsistent zu Runde 13b – alle Standalone-Einträge bei aktiver Varianten-Einschränkung (`instance_hashes`).
* **Fix B (`feature_store_reader.py`, `resolve_no_data_variants`):** Verarbeitet die `standalone`-Sektion als hash-lose Variante (`_add(pid, "Default", "")`) – `_has_data(pid, "")` prüft direkt `pids_with_data` (kein Hash-/Alt-Bestand-Fallback nötig). Die Standalone-pids fließen zusätzlich in `active_pids` (Scope von `feature_keys_by_service`), damit ein Standalone-Service MIT Rows nicht fälschlich als '(No Data)' erscheint.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_round15c.py` (neu): **19/19 PASS** (Temp-DB in `../../test`) – Standalone ohne Rows → NoData-Variante (`instance_hash` leer, `preset_name 'Default'`, display_name 'Trend Breakout'); Standalone MIT Rows → KEINE NoData-Markierung; Payload (`get_available_features`) enthält die Standalone-NoData; Widget rendert 'Trend Breakout – (No Data)' im Feld-Dropdown; VM-Snapshot nimmt Standalone auf (nicht bei Set-Instanz/leerem Filter/aktiver Hash-Einschränkung).
* **Echte DB (User-Szenario):** Snapshot `standalone=['srv_trend_breakout']`, `display_names['srv_trend_breakout|Default']='Trend Breakout'`, `no_data_variants` liefert `[{plugin_id: srv_trend_breakout, display_name: 'Trend Breakout', instance_hash: ''}]`.
* Regression: `check_round15b.py` (10/10), `check_round15_perf.py` (27/27), `check_round12.py` (23/23), `check_round11.py` (35/35), `check_round13c.py` (20/20), `check_round9.py` (19/19), `check_round10.py` (34/34), `check_2004_bugfix3.py` (15/15), `check_round14.py` (8/8). `py_compile` der geänderten Dateien OK.
* **Offen (manuell):** App-Test – `srv_trend_breakout` im ServicePicker checken → '(No Data)'-Hinweis im Feld-Dropdown; nach dem ersten Scan (Daten geschrieben) verschwindet der Hinweis.

---

## 9. Implementierungs-Log – Bugfix Runde 16: Mischbetrieb NoData & Dropdown-Anzeige (11.08.2026)

**Problem (User-Meldungen 0–6, 11.08.2026):**

1. Dropdown-Anzeige: Checkbox + ' ' + Service-Name (ohne `src_`-Präfix) + '/' + Versions-Name + '/ ' + Ausführungsdatum (z. B. `23.04.26 22:14`).
2. Position Aggregation: rechts neben Zoom Y mit Abstand.
3. Position Feld-Dropdown: rechts neben Aggregation in der Zoom-Y-Zeile, Länge bis zum rechten Canvas-Ende.
4. NoData-Anzeige von Versionen fehlt komplett – auch MEHRERE Versionen müssen möglich sein.
5. Mischbetrieb: sind NoData-Services UND Versionen gleichzeitig gecheckt, erscheinen die Services nicht (z. B. `srv_trend_breakout`).
6. Services-Dropdown: nicht alle Services sichtbar, wenn Services und Versionen gemischt gecheckt sind.

**Diagnose (echte DB + ServiceSelectorModel):** 
* S1 (nur Standalone `srv_trend_breakout` gecheckt): NoData erscheint korrekt.
* S2 (nur Version `Kopie 99`, Hash `7d636c36`, ohne Rows): NoData erscheint korrekt.
* S3 (MIX `srv_trend_breakout` + Version `Kopie 99`): **NUR die Version erscheint, `srv_trend_breakout` fehlt.**

**Root Cause (zentrale Routine):** Sobald eine `instance_hashes`-Auswahl aktiv ist, wird jede **hash-lose** Variante (Standalone-Services wie `srv_trend_breakout`/`srv_trend_regime` sowie NULL-Hash-Set-Instanzen) an DREI Stellen gleichzeitig weggefiltert:

1. `analytics_view_model.py` – `_no_data_presets_snapshot()`: `if not active_hashes:` schließt die `standalone`-Snapshot-Sektion komplett aus, sobald irgendein Hash gecheckt ist (Runde-15c-Entscheidung, per User-Meldung 5/6 revidiert).
2. `feature_store_reader.py` – `resolve_no_data_variants()._add()`: `if active_hashes and h_s.lower() not in active_hashes: return` verwirft hash-lose Varianten (`h_s == ""`).
3. `heatmap_widget.py` – `_render_no_data_items()`: `if active_hashes:` filtert hash-lose Varianten (`instance_hash == ""`) erneut aus.

**Bug 4** (gar keine NoData-Anzeige) ist derselbe Fall: Sind alle gecheckten Versionen mit Daten belegt UND zusätzlich ein Standalone-Service ohne Daten gecheckt, wird der Standalone-Service an allen 3 Stellen verworfen → Snapshot/Filter leer → `_render_no_data_items()` macht `early return` → **kein NoData-Abschnitt**.

### Lösung (Fixes 1–3, Bugs 4/5/6)

* **Fix 1 (`analytics_view_model.py`, `_no_data_presets_snapshot`):** Den `if not active_hashes:`-Guard um die `standalone`-Sektion entfernt – Standalone-Services werden IMMER (nur nach `active_ids` gefiltert) in den Snapshot aufgenommen. Die Annahme „hash-lose Variante ist nie Teil einer Hash-Auswahl" gilt für Standalone-Services NICHT: Sie werden über `feature_ids` gecheckt, nicht über Hashes.
* **Fix 2 (`feature_store_reader.py`, `resolve_no_data_variants()._add`):** Der Varianten-Guard greift nur noch bei Varianten MIT Hash: `if active_hashes and h_s and h_s.lower() not in active_hashes: return`. Hash-lose Varianten (Standalone/Alt-Bestand) passieren weiterhin.
* **Fix 3 (`heatmap_widget.py`, `_render_no_data_items`):** Derselbe Guard im defensiven Widget-Filter – hash-lose Varianten bleiben erhalten, nur hash-behaftete werden gegen `active_hashes` geprüft.

### Lösung (Fix 4, Bugs 2/3 – Layout)

* **Fix 4 (`heatmap_widget.py`, `__init__`):** Aggregation-Combo (+ Label) und Feld-Combo (+ Label) aus Zeile 1 (`ctrl`: X-/Y-Achse) in Zeile 2 (`ctrl2`: Overlay + Zoom) nach `_slider_zoom_y` verschoben: `addSpacing(15)` → Aggregation → `addSpacing(10)` → Feld. Das Feld-Dropdown erhält `QSizePolicy.Expanding` + `stretch=1` (reicht bis zum Canvas-Ende) und verliert sein `MaximumWidth(460)`-Limit. `QSizePolicy`-Import ergänzt.

### Lösung (Fix 5, Bug 1 – Anzeige-Format)

* **Fix 5a (`feature_store_reader.py`):** Neue Methode `fetch_last_execution_datetimes_by_hash()` – liefert je (feature_id, instance_hash) den neuesten Schreib-Zeitpunkt MIT Uhrzeit als `'DD.MM.JJ HH:MM'` (identische SQL-Basis wie `fetch_last_execution_dates_by_hash`).
* **Fix 5b (`service_selector_model.py`):** Neuer Cache `_last_execution_datetimes_by_hash` (in `refresh()` geladen) + Methode `last_execution_datetime_for_hash(plugin_id, instance_hash)` (Fallback `'--.--.-- --:--'`).
* **Fix 5c (`analytics_view_model.py`, `resolve_service_display_name`):** Neuer optionaler Parameter `exec_date`; Präfix-Strip um `src_` erweitert; Format umgestellt von `Name (Preset)` auf `Name / Preset / DD.MM.JJ HH:MM` (Preset `Default` und Datum-Fallback werden übersprungen). Neue Hilfsmethode `checked_variant(plugin_id)` liefert `{"preset_name", "instance_hash", "exec_datetime"}` der im Picker gecheckten Variante eines Services.
* **Fix 5d (`heatmap_widget.py`, `_field_label`):** Feld-Einträge tragen jetzt die gecheckte Variante + Ausführungsdatum: `Swing Volume Profile / key / Kopie 99 / 23.04.26 22:14` (Format `{Name} / {Key} / {Preset} / {Datum}`; Preset `Default` und Datum-Fallback entfallen). Aufruf defensiv via `getattr` (`checked_variant` optional) - Fake-/Alt-ViewModels in Tests ohne die Methode ergeben keinen Anhang.
* **Fix 5e (`feature_store_reader.py`, `_no_data_fallback_name`):** Fallback-Format auf `Name / Preset` umgestellt (Preset `Default` entfällt) – konsistent zur VM-Logik.

### Verifikation (headless, keine UI-Tests)

* `py_compile` aller geänderten Dateien.
* Regressionstests nur auf ausdrückliche Anweisung.
* **Offen (manuell):** App-Test – Mischcheck im ServicePicker, NoData-Abschnitt, Layout (Aggregation/Feld in Zoom-Y-Zeile), Dropdown-Format.


---

## 10. Implementierungs-Log - Bugfix Runde 16c: Ausfuehrungsdatum hinter Services ohne Varianten (11.08.2026)

**Problem (User-Meldung, 11.08.2026):** Im Feld-Dropdown soll auch hinter **Services ohne Versionen** (Standalone-Services wie `srv_trend_breakout` - kein Preset, keine Set-Instanz) das Ausfuehrungsdatum angezeigt werden: `Checkbox + ' ' + Service-Name (ohne `src_`-Praefix) + '/ ' + DD.MM.JJ HH:MM` (z. B. `23.04.26 22:14`), sofern vorhanden.

**Root Cause:** `checked_variant()` (Runde 16) liefert fuer Standalone-Services (keine Presets/Clones) konsequent `None` - der Anzeige-Anhang in `_field_label()` blieb leer. Das Ausfuehrungsdatum eines hash-losen Services lag zwar im Modell vor (`last_execution_date`, nur Datum ohne Uhrzeit), wurde aber nicht im Dropdown genutzt.

### Loesung (Fixes 1-4)

* **Fix 1 (`feature_store_reader.py`):** Neue Methode `fetch_last_execution_datetimes()` - neuester Schreib-Zeitpunkt je feature_id **MIT Uhrzeit** als `'DD.MM.JJ HH:MM'` (identische SQL-Basis wie `fetch_last_execution_dates`; MAX(created_at) GROUP BY feature_id ueber alle Symbole/Timeframes).
* **Fix 2 (`service_selector_model.py`):** Neuer Cache `_last_execution_datetimes` (in `refresh()` geladen) + Methode `last_execution_datetime(plugin_id)` (Fallback `'--.--.-- --:--'`).
* **Fix 3 (`analytics_view_model.py`):** Neue Methode `service_execution_datetime(plugin_id)` - Delegate an das Modell (rein lesend, defensiv).
* **Fix 4 (`heatmap_widget.py`, `_field_label`):** Else-Branch - liefert `checked_variant()` `None` (Service ohne Varianten), wird das Service-Datum+Uhrzeit angehaengt: `Trend Breakout / price / 10.08.26 14:03`. Aufruf defensiv via `getattr` (Fake-/Alt-ViewModels ohne die Methode ergeben keinen Anhang).

### Verifikation (headless, keine UI-Tests)

* `py_compile` aller geaenderten Dateien (EXIT=0).
* Echte DB (analytics.duckdb): Reader liefert 6 Services mit `'DD.MM.JJ HH:MM'` (Format-Check gruen); Modell-Cache + Fallback `--.--.-- --:--` korrekt; `_field_label("open", ["srv_grid_lines"])` -> `Grid Lines / open / 10.08.26 14:03`; `srv_trend_breakout` (keine Daten) -> `Trend Breakout / price` (ohne Datum); Fake-VM ohne neue Methode -> kein Crash.
* **Offen (manuell):** App-Test - Standalone-Service im Feld-Dropdown zeigt Ausfuehrungsdatum nach dem ersten Scan.

---

## 11. Abschluss Phase 20.05: Ultra-Low-Latency Control & Rendering Pipeline (11.08.2026)

Mit den Runden 16 (Mischbetrieb NoData & Dropdown-Anzeige) und 16c (Ausfuehrungsdatum hinter Services ohne Varianten) ist die **Phase 20.05 abgeschlossen** - alle User-Meldungen 0-6 der Runde 16 sowie die Nachmeldung zu Standalone-Daten sind umgesetzt, committet und headless verifiziert:

1. **Dropdown-Anzeige:** Checkbox + Service-Name (ohne `src_`/`srv_`/`ind_`-Praefix) + `{Preset}` (nur bei Versionen) + `/ DD.MM.JJ HH:MM` (Ausfuehrungsdatum, wenn vorhanden - fuer Versionen und Standalone-Services).
2. **Layout:** Aggregation rechts neben Zoom Y (mit Abstand), Feld-Dropdown rechts daneben bis zum Canvas-Ende (Expanding-Policy).
3. **NoData:** Versionen (auch mehrere) und Standalone-Services erscheinen korrekt - auch im Mischbetrieb (Fixes 1-3).
4. **Latenzfreiheit:** Alle 4 Praemissen der 20.05-Architektur bleiben erfuellt (kein synchroner DB-Zugriff im UI-Hauptthread; die neuen Datums-Lookups laufen ueber die gecachten Modell-Caches in `refresh()`).

**Abschliessender Stand (Commits `d70462d` + `8ecf2b3`):**
* `../../analytics/engine/analytics_view_model.py` - Fix 1 (Standalone-Guard), Fix 5c (`exec_date`, `src_`-Strip, `checked_variant`), Fix 3 (16c: `service_execution_datetime`)
* `../../analytics/engine/feature_store_reader.py` - Fix 2 (`and h_s`-Guard), Fix 5a (`fetch_last_execution_datetimes_by_hash`), Fix 5e (Fallback `Name / Preset`), Fix 1 (16c: `fetch_last_execution_datetimes`)
* `../../analytics/engine/service_selector_model.py` - Fix 5b (Cache + `last_execution_datetime_for_hash`), Fix 2 (16c: Cache + `last_execution_datetime`)
* `../../analytics/ui/heatmap_widget.py` - Fix 3 (Widget-Hash-Filter), Fix 4 (Layout Zoom-Y-Zeile), Fix 5d (`_field_label` defensiv), Fix 4 (16c: Standalone-Datum)

**Verbleibend (manuell durch den Anwender):** Funktionstest der UI (ServicePicker-Mischcheck, NoData-Abschnitt, Layout, Dropdown-Format inkl. Ausfuehrungsdatum).
---

## 12. Implementierungs-Log - Bugfix Runde 17b: Log-Hoehe 6 Zeilen & Maximize-Button aktiv (11.08.2026)

**Problem (User-Nachtrag nach Runde 17, 11.08.2026):**
1. Das Log-Fenster im ServiceWindow soll noch **2 Zeilen hoeher** (4 -> 6 Zeilen).
2. Der **Maximize-Button ist weiterhin ausgegraut** - trotz `resize_to_clamped_content`-Schutz aus Runde 17.

**Root Cause Maximize (Analyse 11.08.2026):** `apply_screen_cap()` in `../../scrollable_content.py` setzt `setMaximumSize(screen.size())`. Der exakt-fit-Reflow (`resize_to_clamped_content`) bringt das Fenster auf genau diese Groesse. Liegt `maximumSize == size` vor (z. B. Inhalt >= Screen oder kleinere Aufloesung als die .ui-Default-Geometrie), graut Windows den Maximize-Button aus (Fenster ist nicht mehr vergroesserbar).

### Loesung (Fixes 1-3)

* **Fix 1 (`../../serviceui/service_win.py`, Log-Hoehe):** `setMaximumHeight`/`setMinimumHeight` von `fm.lineSpacing() * 4 + 12` auf `* 6 + 12` erhoeht (User-Nachtrag: 2 Zeilen hoeher als die 4-Zeilen-Stufe).
* **Fix 2 (`../../serviceui/service_win.py`, `apply_screen_cap()`-Override):** ServiceWindow ueberschreibt die Basis-Methode und setzt das Maximum grosszuegig auf **2x Screen** (`QSize(screen.width() * 2, screen.height() * 2)`, `QSize`-Import ergaenzt). Der Maximize-Button bleibt damit IMMER aktiv (`max > size`). Das exakt-fit-Reflow klemmt weiterhin die DEFAULT-Groesse auf den Screen; der Anwender kann danach frei maximieren bzw. das Fenster groesser ziehen (Inhalt scrollt in der ContentScrollArea).
* **Fix 3 (`../../persistent_win.py`, `_fix_window_flags`):** Sichert zusaetzlich explizit `Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint` (Flags werden nur bei Bedarf neu gesetzt - `if wanted != flags:`) - fehlt der Maximize-Hint (z. B. durch QUiLoader/setWindowFlags-Fallstricke), ist der Maximize-Button ausgegraut.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_ui3_bugfix.py` (aktualisiert): **31/31 PASS** - B4: Log 6 Zeilen (`* 6 + 12` max/min, kein `* 4 + 12`); B6: `apply_screen_cap`-Override vorhanden, Maximum `screen.width() * 2`/`screen.height() * 2`, kein exakt-fit-`setMaximumSize(screen.size())`-Code, `Qt.WindowMaximizeButtonHint`/`Qt.WindowMinimizeButtonHint` in `../../persistent_win.py`, Guard `if wanted != flags:`.
* `../../test/check_r17b_construct.py` (neu, offscreen): **11/11 PASS** - echtes `ServiceWindow()` konstruiert: `maximumSize()` == 2x Screen, Maximize-/Minimize-Hint + `Qt.Window` gesetzt, Log min/max == `lineSpacing()*6+12`.
* `py_compile` der geaenderten Dateien (EXIT=0).
* **Offen (manuell):** App-Test - Maximize-Button klickbar, Log-Fenster 6 Zeilen hoch.

---

## 13. Implementierungs-Log - Bugfix Runde 17c: Maximize aktiv, Inhalt folgt Fenster, Param-Box waechst mit (11.08.2026)

**Problem (User-Meldungen 3/4/5, 11.08.2026):**
3. Der **Maximize-Button im service_win ist immer noch ausgegraut**.
4. Manuelles Grossziehen (Rahmen/Ecke) ohne Inhalt-Anpassung.
5. Die Parameter-Box soll sich der Fenstergroesse anpassen (ggf. auch die Hoehe des MasterTrees).

**Root Cause 3+4 (offscreen verifiziert, Commit `8e2841b`):** `_fix_window_flags()` rief `setWindowFlags()` DEFERRED NACH `win.show()` auf. `setWindowFlags()` auf einem SICHTBAREN Fenster bricht die Layout-Geometrie-Verwaltung des QMainWindow-Layouts - die ContentScrollArea 'friert' auf der alten Groesse ein und folgt dem manuellen Resize/Maximize nicht mehr (Ursache Meldung 4). Zusaetzlich war `self.ui` ein eingebettetes QMainWindow (Qt verlangt QMainWindow nur als Top-Level) - es wuchs ebenfalls nicht mit.

### Loesung (Fixes 1-4)

* **Fix 1 (`../../persistent_win.py`):** `_fix_window_flags()` wird jetzt im KONSTRUKTOR gerufen (Fenster unsichtbar -> `setWindowFlags` sicher); `restore_state` ruft es nur noch, wenn das Fenster unsichtbar ist. `MSWindowsFixedSizeDialogHint` wird explizit entfernt (deaktiviert den Maximize-Button). Nachtrag (Commit `289b634`): auch die Basis-`restore_state` setzt Flags nur noch bei unsichtbarem Fenster (Schutz fuer AnalyticsWindow/StatisticWindow).
* **Fix 2 (`../../ui/service_win.ui`):** Root von QMainWindow auf QWidget umgestellt (hatte nur ein centralwidget, keine menubar/statusbar) - Layout direkt im Root.
* **Fix 3 (`../../serviceui/service_win.py`):** `content_widget = self.ui` (kein `centralWidget()` mehr), `install_content_scroll` setzt die ScrollArea DIREKT als CentralWidget von `self`. `_exact_fit_to_content=False` (Inhalt folgt Fenster, nur wachsen). `content_scroll` + `param_scroll` auf `widgetResizable=True` (Inhalt waechst mit dem Fenster). Kein 1000x1240-Cap der Param-Box mehr. `restore_state` wendet die gespeicherte Fenster-Groesse an. `resize_to_clamped_content()`-Override resizet das Inhalt-Widget nicht mehr manuell (wuerde `widgetResizable` brechen) sondern fuehrt nur die Fenster-Groesse nach.
* **Fix 4 (`../../serviceui/param_columns.py`):** `box.resize` nur noch bei `widgetResizable=False` (ScrollArea uebernimmt die Streckung).

### Verifikation (headless, keine UI-Tests)

* `../../test/check_r17c_resize.py`: **19/19 PASS** (R1/D1-D4: widgetResizable True, kein 1000/1240-Cap, MSFixedSizeHint weg, MaxHint gesetzt, Inhalt waechst mit, Reflow schrumpft nicht).
* `../../test/check_ui3_bugfix.py`: **32/32 PASS**; `../../test/check_r17b_construct.py`: **11/11 PASS**; `py_compile` OK.
* **Offen (manuell):** App-Test Maximize-Button + Grossziehen.

---

## 14. Implementierungs-Log - Bugfix Runde 17d: ServiceWindow waechst mit dem Fenster, Maximize-Button sicher (11.08.2026)

**Problem (Fortsetzung nach Pause, User-Meldungen 3/4/5, 11.08.2026):** Der Maximize-Button blieb ausgegraut; das manuelle Grossziehen zeigte weiterhin keine Inhalt-Anpassung.

**Root Cause 4+5 (dynamisch verifiziert, Commit `4414fc5`):** `self.central_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)` in `service_win.py` HIELT die QBoxLayout-Verteilung an: Der QSplitter (MasterTree | Parameter-Box) blieb auf seiner Mindest-Hoehe stehen, obwohl das Fenster groesser gezogen/maximiert wurde (Extra-Raum blieb als Leerflaeche unter dem Splitter). Die Breite wuchs nur die Param-Box; in der Hoehe gar nichts.

### Loesung (Fixes 1-2)

* **Fix 1 (`../../serviceui/service_win.py`):** `setAlignment(AlignTop | AlignLeft)` auf dem `central_layout` ENTFERNT. Mit `widgetResizable=True` + `_exact_fit_to_content=False` folgt der Inhalt dem Fenster: Splitter, MasterTree (Hoehe!) und Param-Box (Breite + Hoehe) wachsen beim Grossziehen/Maximieren mit.
* **Fix 2 (`../../persistent_win.py`):** `_fix_window_flags()` auf int-basierte Flag-Arithmetik umgestellt (PySide6-Flag-Operatoren droppen Bits ausserhalb des Enum-Domains, z. B. `0x08000000` bei `& ~WindowType_Mask`). Typ wird explizit auf `Qt.Window` gesetzt (Dialog/Tool-Typen haben unter Windows keine Min/Max-Buttons) und der VOLLSTAENDIGE Standard-Button-Satz (Title, SystemMenu, Minimize, Maximize, Close) sichergestellt.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_r17d_resize.py` (neu): **18/18 PASS** - ECHTE Widget-Baum-Proben: Tree-Hoehe 634->1048, Param-Box 520x736->814x1150 bei +600x400, Maximize-Bleibt-Maximiert (Reflow wirft nicht aus dem Maximize-Zustand).
* `../../test/check_r17c_resize.py` (R3-Check auf neue Flag-Arithmetik angepasst): **19/19 PASS**.
* `../../test/check_r17b_construct.py` **11/11**, `../../test/check_ui3_bugfix.py` **31/31**, AnalyticsWindow/StatisticWindow mit vollem Button-Satz `0x800f001` konstruierbar, `py_compile` OK.
* **Offen (manuell):** App-Test Grossziehen/Maximieren des service_win.

---

## 15. Implementierungs-Log - Bugfix Runde 17d2: Maximize-Button deaktiviert - setMaximumSize entfernt (11.08.2026)

**Problem (User-Meldung 1, 11.08.2026):** Der Maximize-Button im service_win ist IMMER NOCH ausgegraut und nicht bedienbar - auch nach Runden 17b/c/d.

**Root Cause (Qt-Quelle `qwindowswindow.cpp`, `shouldShowMaximizeButton()`, Commit `77be253`):**

```cpp
return (flags & Qt::CustomizeWindowHint) || w->maximumSize() == QSize(QWINDOWSIZE_MAX, QWINDOWSIZE_MAX);
```

Windows zeigt/aktiviert den Maximize-Button NUR wenn `maximumSize() == QWINDOWSIZE_MAX` (**16777215**) ist (oder `Qt::CustomizeWindowHint` gesetzt ist). Das bisherige `setMaximumSize(screen.size())` (17b) bzw. `setMaximumSize(screen.size()*2)` (17c) war NIE gleich 16777215 -> Windows graute den Button weiterhin aus. Die '2x Screen'-Annahme von Runde 17b war falsch.

### Loesung (Fix 1)

* **Fix 1 (`../../serviceui/service_win.py`, `apply_screen_cap()`-Override):** `setMaximumSize` ENTFERNT. Das Fenster behaelt die Qt-Defaults (`max = 16777215 = QWINDOWSIZE_MAX`) -> Maximize-Button wieder aktiv. Die Screen-Klemme der DEFAULT-Groesse uebernimmt weiterhin `resize_to_clamped_content` (auf `availableGeometry`); ein OS-seitiges Maximum ist bei `widgetResizable=True` + `_exact_fit_to_content=False` nicht noetig.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_r17b_construct.py`: **11/11 PASS** (D1 prueft jetzt `max == 16777215`).
* `../../test/check_r17c_resize.py`: **19/19 PASS** (D3 prueft `max == 16777215`).
* `../../test/check_ui3_bugfix.py`: **32/32 PASS** (B6 prueft: KEIN `setMaximumSize`).
* `../../test/check_r17d_resize.py`: **19/19 PASS** (A4 prueft `max == 16777215`); `py_compile` OK.
* **Offen (manuell):** App-Test - Maximize-Button klickbar.

---

## 16. Implementierungs-Log - Bugfix Runde 17e: AnalyticsWindow-Historie intakt (11.08.2026)

**Problem (User-Meldung 2, 11.08.2026):** 'Fenster-Historie nicht mehr intakt - Analytics geschlossen, Anwendung geschlossen, bei Neustart ist Analytics wieder da.'

**Root Cause (Commit `d0eaa16`):** `AnalyticsWindow` hatte seit Phase 20.01 (E1) `_keep_history_on_close = True`. Der Fenster-Historie-Eintrag wurde beim MANUELLEN Schliessen (X) nicht geloescht -> `restore_all_windows` stellte das Fenster beim naechsten App-Start wieder her, obwohl der User es bewusst geschlossen hatte.

### Loesung (Fixes 1-5, `../../analytics/ui/analytics_win.py`)

* **Fix 1:** `_keep_history_on_close = False` - MANUELL geschlossenes Fenster wird aus der Historie entfernt (`delete_instance`) und beim Neustart NICHT wiederhergestellt (konsistent mit ServiceWindow).
* **Fix 2:** `DIALOG_GEOMETRY_KEY = "win_analytics"` + `save_state()`-Override: Position/Groesse zusaetzlich in `global_settings` (`save_dialog_geometry`) - ueberlebt das manuelle Schliessen (Muster ServiceWindow).
* **Fix 3:** `restore_state()`-Override: Fallback auf `get_dialog_geometry`, wenn kein `window_instances`-Eintrag mehr existiert (manuelles Wiederoeffnen).
* **Fix 4:** `_save_workspace()`: zusaetzliches Workspace-Backup in `global_settings` (`"analytics_workspace"`) - ueberlebt `delete_instance`.
* **Fix 5:** `_restore_workspace()`: Fallback auf das `global_settings`-Backup.

**Resultierendes Verhalten:** Offen beim App-Ende -> beim Start wiederhergestellt (auto_restore). Manuell geschlossen -> NICHT beim Start; Position + Workspace werden beim naechsten manuellen Oeffnen (Button) wiederhergestellt.

### Verifikation (headless, keine UI-Tests)

* `../../test/check_r17e_history.py` (neu, Temp-DB in `../../test`): **15/15 PASS** - D2: kein Eintrag nach manuellem Schliessen; D5: Geometrie-Fallback ueberlebt; D6/D7: Workspace-Backup + Restore-Fallback; D8: offen beim App-Ende -> Eintrag bleibt.
* `../../test/test.py`-Assertions H3/H4/H5/H8 + Teil 36 W8 an die neue Semantik angepasst (Runde 17/17e: `_keep_history_on_close=False`).
* `py_compile` OK; `check_r17d_resize.py` 19/19; `check_r17b_construct.py` 11/11.
* **Offen (manuell):** App-Test - Analytics schliessen -> App beenden -> Neustart: Analytics darf NICHT erscheinen; Position + Workspace beim manuellen Oeffnen wiederhergestellt.

---

## 17. Abschluss Phase 20: Analytics-Finalisierung (11.08.2026)

Mit den Bugfix-Runden 16, 16c, 17, 17b, 17c, 17d, 17d2 und 17e ist die **Phase 20 (Analytics-Finalisierung) abgeschlossen**. Alle offenen User-Meldungen der Runden 16-17e sind umgesetzt, committet und headless verifiziert:

1. **ServiceWindow-Bedienung (Runden 17-17d2):** Slider-Spielraum (Splitter-Minima + `_min_window_width=1100`), Log-Hoehe 6 Zeilen, Maximize-Button aktiv (`max == QWINDOWSIZE_MAX`, kein `setMaximumSize`), Inhalt folgt der Fenstergroesse (widgetResizable + kein AlignTop-AlignLeft) - MasterTree-Hoehe und Param-Box wachsen beim Grossziehen/Maximieren mit.
2. **Fenster-Historie (Runde 17e):** AnalyticsWindow wird beim MANUELLEN Schliessen aus der Historie entfernt und beim Neustart NICHT wiederhergestellt; Position + Workspace ueberleben via `global_settings`-Backup und werden beim manuellen Oeffnen wiederhergestellt.
3. **20.05-Architektur:** Alle vier Praemissen der Ultra-Low-Latency-Pipeline bleiben erfuellt (kein synchroner DB-Zugriff im UI-Hauptthread, lueckenlose Persistenz, isolierte Grafik-Welt, asynchrone Daten-Nachfuehrung).

**Abschliessender Stand (Commits `cb0412b`..`d0eaa16`):**
* `../../persistent_win.py` - Flags im Konstruktor, int-basierte Flag-Arithmetik, volle Button-Hints
* `../../scrollable_content.py` - Maximize-Schutz im Reflow, Inhalt folgt Fensterbreite
* `../../serviceui/service_win.py` - Slider-Spielraum, Log 6 Zeilen, `_exact_fit_to_content=False`, widgetResizable, kein AlignTop-AlignLeft, `apply_screen_cap` ohne `setMaximumSize`
* `../../serviceui/param_columns.py` - box.resize nur bei widgetResizable=False
* `../../ui/service_win.ui` - Root QWidget statt QMainWindow
* `../../analytics/ui/analytics_win.py` - `_keep_history_on_close=False`, Geometrie-/Workspace-Fallback, DIALOG_GEOMETRY_KEY

**Verbleibend (manuell durch den Anwender):** Funktionstest der UI (ServiceWindow Maximize/Grossziehen, AnalyticsWindow-Historie, Dropdown-/NoData-Anzeige). Offene Kapitel werden manuell in die naechste Phase uebernommen.


