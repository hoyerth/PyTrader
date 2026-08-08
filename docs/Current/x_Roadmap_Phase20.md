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

# 20.01 Analytics UI: Dual-Layer Persistenz, Auto-Restore & Fault-Tolerant Profile Resolver

## 1. Regeln & Invarianten

* **Einrückung:** Exakt **4 Leerzeichen** (Codebase-Standard).
* **Spacing:** Exakt **1 Leerzeile** zwischen Methoden/Funktionen.
* **UI-Tests:** **STRIKT VERBOTEN** (Prüfung rein headless via `py_compile` & `test/test.py`).
* **Architektur:** Dual-Layer Persistenz (Layer 1: Auto-Restore Workspace, Layer 2: Explicit-Save Profil), Fault-Tolerant Resolution bei gelöschten Services, MVVM, IoC.

---

## 2. Architektur & Datenfluss (Textblock-Schema)

[AnalyticsWindow.closeEvent()] ──(Auto-Save Workspace)──► [WindowStateRepository (win_analytics)]
                                                            │ (Auto-Restore bei Fensteröffnung)
                                                            ▼
[AnalyticsProfile (Explicit Save)] ◄──(Save/Load)───► [AnalyticsProfileRepository (app_data.duckdb)]
        │
        └──(Profile Load)──► [ServiceSelectorModel.resolve_valid_feature_ids()]
                                  │
                                  ├── Valid IDs    ──► [AnalyticsViewModel.set_feature_ids()]
                                  └── Missing IDs  ──► Status-Msg: "⚠️ X Services übersprungen (gelöscht)"

---

## 3. Zwei-Schichten-Persistenzmodell (Dual-Layer)

### Layer 1: Workspace Auto-Restore (`WindowStateRepository` / `state_manager`)

* **Verhalten:** Beim Schließen von `AnalyticsWindow` (`closeEvent`) wird der *exakt letzte physische Arbeitsstand* automatisch unter der Instanz `win_analytics` gesichert.
* **Umfang:** Fenstergeometrie, aktives `profile_id`, Symbol, Timeframe, temporäre UI-Zustände.
* **Nutzen:** Beim Wiederöffnen startet die Analytics-UI exakt an der verlassenen Stelle, ohne dass zuvor manuell gespeichert werden musste.

### Layer 2: Profile Snapshot (`AnalyticsProfileRepository`)

* **Verhalten:** Strukturierter Section-Payload (Schema v2) für benannte Analyse-Dashboards.
* **Explicit Save:** Speicherung/Aktualisierung erfolgt ausschließlich durch expliziten Klick auf `[💾 Save]` oder *„Neues Profil“*.
* **Dirty-Flag:** Ändern von Filtern, Farbschemata, Tabellen-Layouts oder Datenquellen markiert das ViewModel als dirty (`*` im Titel/Combo).

---

## 4. Modulares Profile-Payload-Schema (v2)

{
  "schema_version": "2.0.0",
  "sources": {
    "feature_ids": ["srv_grid_lines", "srv_proximity"],
    "set_id": null
  },
  "table": {
    "column_widths": { "Zeitstempel": 140, "Service": 180, "step_size": 90 },
    "sort_col_name": "Zeitstempel",
    "sort_order": 1,
    "row_height": 24
  },
  "charts": {
    "heatmap_metric": "count",
    "scatter_x": "ema_diff",
    "scatter_y": "rsi_14",
    "distribution_column": "atr_normalized"
  },
  "styling": {
    "legends_enabled": true,
    "color_theme": "default"
  }
}


---

## 5. Graceful Degradation & Fault-Tolerant Resolver

1. **Service Resolution:** Beim Laden eines Profils prüft der `ServiceSelectorModel.resolve_valid_feature_ids()` alle gespeicherten `feature_ids` gegen die aktuell in der `PluginRegistry` vorhandenen Plugins.
2. **Graceful Skip:** Nicht mehr auffindbare Services (gelöscht/entfernt) wandern in eine `missing_ids`-Liste. Nur noch gültige Services (`valid_ids`) werden an das `AnalyticsViewModel` zur Datenabfrage übergeben. Das restliche Dashboard lädt voll funktionsfähig.
3. **Non-Destructive Alert:**
* Die Filterleiste zeigt eine dezente Warnung (`⚠️ X Services im Profil nicht mehr verfügbar`).
* Das Datenbank-Profil bleibt unberührt, bis der Anwender nach Anpassung explizit `[💾 Save]` betätigt.

4. **v1-Backward-Compatibility:** Das `AnalyticsViewModel` wandelt veraltete v1-Payloads (flache Dictionaries) beim Einlesen automatisch und verlustfrei in das v2-Sektionen-Schema um.
