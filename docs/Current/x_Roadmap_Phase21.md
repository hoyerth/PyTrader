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

# Phase 21.03: Generatives Filter- & Sortiersystem (Cross-View Filtering Engine)

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

