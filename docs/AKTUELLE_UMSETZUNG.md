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


