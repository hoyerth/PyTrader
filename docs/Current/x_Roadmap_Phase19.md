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

* [ ] Platziere ein `QLabel` (`label_status_msg`) direkt neben/hinter dem Limit-Input-Feld (`spin_limit`).
* [ ] Verbinde den Event-Handler für `view_model.data_ready(kind, data)`:
* Falls `data.get("total", 0) == 0`:
* Setze `label_status_msg.setText("⚠️ Keine Daten vorhanden")` (Farbton: dezent gelb/orange).
* Blende leere Zustände auf den Unterseiten (`table_page`, `heatmap_page`, `scatter_page`, `distribution_page`) sauber aus/zurück.

* Falls `data.get("total", 0) > 0`:
* Setze `label_status_msg.setText(f"✅ {total} Einträge")` oder leere den Text.

#### Step 2: Multi-Service Spaltenaufbereitung (`table_page.py`)

* [ ] Erweitere das Layout der `TablePage`:
1. Füge als **Spalte 1** das Feld **`Service`** ein (Anzeige der `feature_id` bzw. des via `service_selector_model.resolve_display_names()` aufgelösten Namens).
2. Standard-Spaltenreihenfolge festlegen: `[Zeitstempel, Service, ema_diff, rsi_14, atr_normalized, ...]`.
3. Bei Zusatzfeldern aus `feature_data`: Bilde die Union aller JSON-Keys über die geladenen Rows; fülle fehlende Werte bei abweichenden Services mit `"-"`.
4. Erzwinge eine chronologisch absteigende Sortierung nach `bar_time`, damit Signale verschiedener Services zeitlich korrekt gemischt dargestellt werden.

#### Step 3: Quality Gate & Verifikation

* [ ] Syntax-Check via Terminal ausführen:
`python -m py_compile analytics/ui/analytics_win.py analytics/ui/table_page.py analytics/engine/analytics_view_model.py`

* [ ] Headless-Test in `test/test.py` für `AnalyticsViewModel`-Abfragen ausführen:
* Testfall A: Abfrage für ungescannte Symbole/Services liefert `total == 0`.
* Testfall B: Multi-`feature_ids`-Abfrage liefert gemischte Ergebnissätze.