# Phase 21: Fachliche Feinabstimmung Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 21)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase21_step1`, `phase21_step1` usw.).
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

