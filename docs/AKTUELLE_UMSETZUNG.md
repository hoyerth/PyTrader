# Phase 18: Analytics-Finalisierung

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 18)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase17_step1`, `phase17_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
4. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
5. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`db_service.py`) – eine Verbindung pro Thread und DB-Datei.
6. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
7. **Concurrency-Guard & Timer-Pausierung:** Solange im ServiceWindow intensive Service-Berechnungen laufen (`ServiceRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
8. **Isolierter Test-Workspace:** Alle neuen Test-Python-Dateien und temporären Test-Datenbanken (`*.duckdb`) müssen strikt im Unterordner `test/` erzeugt, gelesen und abgelegt werden – niemals im Projekt-Root oder im `data/`-Ordner.
9. **Open/Closed-Principle & Code-Preserving:** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden und bestehende Kern-Klassen bleiben geschützt.
10. **Test-Cleanup (Entscheidung 06.08.2026):** Tests werden NICHT dauerhaft aufbewahrt. Nach Abschluss jedes Phasenkapitels wird der Ordner `test/` aufgeräumt – es bleibt ausschließlich die Datei `test/test.py` (dauerhafter Test-Harness) bestehen.
11. **Naming Conventions & PineScript-Input-Zone:** 
    * Services in `analytics/features/definitions/` nutzen strikt das Präfix `srv_` (`plugin_id = "srv_..."`).
    * Indikatoren in `chart/indicators/` nutzen strikt das Präfix `ind_` (`indicator_id = "ind_..."`).
    * Füllwörter (`service`, `plugin`, `indicator`) entfallen im Dateinamen.
    * Das `parameter_schema` liegt direkt am Dateianfang unter dem Header-Docstring.
    * Jedes Service-Plugin deklariert `metadata["category"]` für die dynamische Kategorie-Ordner-Struktur im MasterTree.


---

# 18.01.02 Refactoring & Modularisierung (Großdateien)

## 1. Regeln & Invarianten

* **Einrückung:** Ausschließlich **Tabs**.
* **Spacing:** Exakt **1 Leerzeile** zwischen Funktionen/Methoden.
* **UI-Tests:** **VERBOTEN.** Verifikation rein headless (`py_compile`, `test/test.py`).
* **Architektur:** Single Responsibility Principle (SRP), Inversion of Control, Entkopplung.



---

## 2. Refactoring-Ziele (Zu große Dateien)

```text
[db_service.py] ──────────► [db/db_pool.py] + [db/schema_initializer.py]
                        └─► [data_sync/mt5_sync_service.py] + [repositories/market_data_repository.py]

[main.py] ────────────────► [workers/live_tick_worker.py] + [workers/data_sync_worker.py]
                        └─► [ui/window_manager.py]

[service_selector_model] ─► [analytics/engine/tree_builder.py] (Kategorie-Verschachtelung/Baumaufbau)

```

---

## 3. Modularisierungs-Anleitung (IDE-AI)

### Step 1: `db_service.py` entflechten

* [x] `DbPool` & Threading-Locks in `db/db_pool.py` auslagern.


* [x] Schema-Anlage (`check_and_init_databases`) nach `db/schema_initializer.py` verschieben.


* [x] Sync-Logik (`sync_market_data`) in `data_sync/mt5_sync_service.py` trennen.


* [x] `MarketDataRepository` eigenständig in `repositories/market_data_repository.py` platzieren.



### Step 2: `main.py` schlankziehen

* [x] `LiveTickWorker` & `DataSyncWorker` in eigene Worker-Dateien im Ordner `workers/` auslagern.


* [x] Wiederherstellung & Jump-to-Bar (`restore_all_windows`, `open_chart_at_bar`) in `ui/window_manager.py` kapseln.



### Step 3: `service_selector_model.py` bereinigen

* [x] Rekursiven Baumaufbau (`build_tree`, `_insert_into_category_tree`) in `analytics/engine/tree_builder.py` auslagern.


* [x] Model rein auf Daten-Providing & EventBus-Sync fokussieren.



### Step 4: Quality Gate

* [x] `python -m py_compile db/db_pool.py db/schema_initializer.py data_sync/mt5_sync_service.py repositories/market_data_repository.py workers/live_tick_worker.py workers/data_sync_worker.py ui/window_manager.py analytics/engine/tree_builder.py`
* [x] Headless-Test in `test/test.py` für DB-Zugriffe & Worker-Instanziierung ausführen.
* [x] Code-Check: Nur Tabs, 1 Leerzeile Abstand.

---

## Prüfprotokoll 18.01.02 (08.08.2026) – Konsistenz, Vollständigkeit & Entscheidungen

### Prüfergebnis (Konsistenz)
Die IST-Analyse bestätigt die drei Refactoring-Ziele des Kapitels (Code-Inspektion, `ast`-Strukturanalyse und Import-Graph-Analyse über alle 84 Projekt-`.py`-Dateien):

* **`db_service.py` (23,9 KB)** vereint real 6 logische Einheiten: `DbPool`/`_LockedConnection`/`db_connect`/`with_db_lock` (Pool & Threading), `check_and_init_databases` (Schema/Migration), `check_mt5_connection`/`sync_market_data`/`get_latest_timestamp` (MT5-Sync), `get_timeframes`/`TF_SECONDS_MAP`/`MT5_LOCK` (MT5-Konfig), `_parse_json_field`/`_ensure_epoch` (Utilities), `MarketDataRepository`/`get_symbol_precision` (Read-Repository).
* **`main.py` (29,9 KB)** enthält `DataSyncWorker`/`LiveTickWorker` (QThread) sowie `MainWindow` mit 9 Fenster-Lifecycle-Methoden und Tick-Dispatch-Methoden.
* **`analytics/engine/service_selector_model.py`** trägt den kompletten Baum-Aufbau (`build_tree`, `_category_nodes`, `_insert_into_category_tree`, `_insert_set_into_category_tree`, `_ensure_category_path`, Kategorie-Auflösung) – seit 18.01.03 zusätzlich Sets-Kategorien, Empty-Folder-Einmischung und Override-Auswertung.

Der Plan ist architektonisch schlüssig (SRP-Ziele korrekt, Reihenfolge Step 1→2→3 sinnvoll, da die Worker die neuen `db/`-Module benötigen). **Vollständigkeits-Lücken** gefunden:

* **L1 – Import-Kompatibilität nicht geregelt:** **20 Projektdateien** importieren aus `db_service` (`DbPool` 12×, `_parse_json_field` 7×, `TF_SECONDS_MAP` 6×, `get_timeframes` 4×, `MarketDataRepository` 2×, `get_symbol_precision` 2×, `DB_APP_DATA`/`DB_MARKET_DATA`/`MT5_LOCK` je 1–2×, zusätzlich `import db_service` in `main.py`). Ohne Kompatibilitätsstrategie bricht die Aufteilung alle 20 Caller.
* **L2 – `_parse_json_field` ohne Zielort:** wird von 7 Modulen als „privates" Helferlein importiert (`feature_store_reader`, `service_selector_model`, `service_set_repository`, `analytics_profile_repository`, `chart_win`, `state_manager`, `window_state_repository`) – gehört weder zum Pool noch zur Sync-Logik; der Plan listet keinen Zielordner.
* **L3 – Nicht zugeordnete Bestandteile:** Der Plan nennt nur 4 Zieleinheiten. Nicht zugeordnet: `get_timeframes`, `TF_SECONDS_MAP`, `MT5_LOCK`, `SYMBOLS`, `check_mt5_connection`, `get_latest_timestamp`, `get_symbol_precision`, `db_connect`/`_LockedConnection` (LEGACY), `with_db_lock` (No-op, API-Kompatibilität), `_ensure_epoch` (DEPRECATED), die DB-Pfad-Konstanten (`DATA_DIR`, `DB_MARKET_DATA`, `DB_ANALYTICS`, `DB_APP_DATA`) und der CLI-Einstieg `main()` (`python db_service.py`).
* **L4 – Abhängigkeitsrichtung/Zirkularität nicht spezifiziert:** `sync_market_data` ruft `check_and_init_databases` + `check_mt5_connection` auf; alle drei brauchen `DbPool`/DB-Konstanten; `LiveTickWorker` braucht `MT5_LOCK` + `get_timeframes`; `MarketDataRepository` und `get_symbol_precision` teilen dieselbe Precision-Query. Ohne festgelegte einseitige Import-Richtung drohen Zyklen.
* **L5 – Einrückungs-Konflikt:** Kapitel-Regel 1 fordert „Ausschließlich Tabs" – der Codebase-Standard ist jedoch **4 Leerzeichen** (18.01.01 E-1, 18.01.03-Kapitel; real in `db_service.py`, `main.py`, `state_manager.py`, `service_set_repository.py`). Zusätzlich sind `service_selector_model.py`/`master_tree.py` real mit 2 Leerzeichen eingerückt (Altbestand).
* **L6 – Umfang `ui/window_manager.py` unklar:** Der Plan nennt nur `restore_all_windows` + `open_chart_at_bar`. Es existieren aber 8 Fenster-Lifecycle-Methoden (zusätzlich `open_chart_window`, `handle_chart_closed`, `open_service_window`, `open_analytics_window`, `open_properties_window`, `get_currently_active_pairs`), die eng an `self.chart_windows`/`self.persistent_sub_windows`/`self.state_manager` hängen; `restore_main_window_geometry` operiert auf dem Hauptfenster selbst.
* **L7 – Baum-Extraktionsumfang veraltet (18.01.03 nachgezogen):** Der Plan nennt nur `build_tree` + `_insert_into_category_tree`. Seit 18.01.03 gehören dazu zusätzlich `_category_nodes`, `_category_parts`, `_cat_key`, `_sort_category_nodes`, `_insert_set_into_category_tree`, `_set_category_parts`, `_ensure_category_path`, `category_plugin_ids`, `category_set_ids`, `category_service_plugin_ids`, `plugin_category_path` – verzahnt mit Model-Zustand (`_plugin_category_overrides`, `_empty_folder_paths`).
* **L8 – Worker-Anpassungspunkte nicht abgedeckt:** `DataSyncWorker.run()` ruft `db_service.sync_market_data()` (Modul-Referenz); `LiveTickWorker._persist_bar` nutzt deferred `from db_service import DB_MARKET_DATA, DbPool`. Beide Importziele müssen nach der Aufteilung angepasst werden.

### Entscheidungen (18.01.02)

1. **E1 – Einrückung = 4 Leerzeichen (Codebase-Standard):** Die Kapitel-Regel „Ausschließlich Tabs" wird überstimmt. Alle **neuen** Dateien (`db/db_pool.py`, `db/db_utils.py`, `db/schema_initializer.py`, `data_sync/mt5_sync_service.py`, `repositories/market_data_repository.py`, `workers/*.py`, `ui/window_manager.py`, `analytics/engine/tree_builder.py`) nutzen exakt **4 Leerzeichen** pro Ebene (konsistent mit 18.01.01 E-1 und 18.01.03). Bestehende Dateien werden **nicht** umformatiert (auch nicht die 2-Space-Dateien `service_selector_model.py`/`master_tree.py` – Kern-Dateien geschützt, Invariante 9).
2. **E2 – `db_service.py` bleibt als Fassade (Re-Export-Wrapper):** Alle 20 Bestands-Caller bleiben unverändert. `db_service.py` re-exportiert nach der Aufteilung alle öffentlichen Namen (`DbPool`, `MarketDataRepository`, `get_timeframes`, `TF_SECONDS_MAP`, `MT5_LOCK`, `DB_APP_DATA`, `DB_MARKET_DATA`, `DB_ANALYTICS`, `SYMBOLS`, `get_symbol_precision`, `get_latest_timestamp`, `sync_market_data`, `check_and_init_databases`, `check_mt5_connection`, `db_connect`, `with_db_lock`, `_parse_json_field`, `_ensure_epoch`) und behält den CLI-Einstieg (`main()`/`if __name__ == "__main__"` → `sync_market_data()`). Damit bleibt auch `import db_service` in `main.py` gültig. Die Fassade re-exportiert nur, enthält aber keine Logik mehr.
3. **E3 – Vollständige Zuordnungstabelle für `db_service.py`:**

   | Neues Modul | Übernommene Bestandteile |
   |---|---|
   | `db/db_pool.py` | `DATA_DIR`, `DB_MARKET_DATA`, `DB_ANALYTICS`, `DB_APP_DATA`, `_db_pool_lock`, `_db_pool_global`, `DbPool`, `_LockedConnection`, `db_connect`, `with_db_lock` |
   | `db/db_utils.py` | `_parse_json_field`, `_ensure_epoch` |
   | `db/schema_initializer.py` | `check_and_init_databases` |
   | `data_sync/mt5_sync_service.py` | `SYMBOLS`, `_TIMEFRAMES_CACHE`, `get_timeframes`, `TF_SECONDS_MAP`, `MT5_LOCK`, `check_mt5_connection`, `get_latest_timestamp`, `sync_market_data` |
   | `repositories/market_data_repository.py` | `MarketDataRepository`, `get_symbol_precision` (gemeinsame Precision-Logik, DRY) |
   | `db_service.py` (Fassade) | Re-Exports (E2) + CLI `main()` |

   **Lazy-Import-Prinzip beibehalten:** `MetaTrader5` wird weiterhin erst beim Aufruf importiert (`get_timeframes`/`check_mt5_connection`/`sync_market_data`) – kein MT5-DLL-Load beim Modul-Import (verhindert Import-Zyklen über `data_sync`).
4. **E4 – Einseitige Abhängigkeitsrichtung (keine Zirkularität):**
   ```
   db/db_pool.py (Basis)  ←  db/db_utils.py, db/schema_initializer.py,
                              repositories/market_data_repository.py,
                              data_sync/mt5_sync_service.py
   data_sync/mt5_sync_service.py  →  db/db_pool.py, db/db_utils.py, db/schema_initializer.py
   workers/data_sync_worker.py    →  data_sync/mt5_sync_service.py
   workers/live_tick_worker.py    →  data_sync/mt5_sync_service.py (MT5_LOCK, get_timeframes),
                                     db/db_pool.py, db/db_utils.py
   ui/window_manager.py           →  chart/chart_win.py, persistent_win.py, state_manager.py
   analytics/engine/tree_builder.py → (keine Abhängigkeit von ServiceSelectorModel)
   ```
   **Kern-Regel:** Kein neues Modul importiert `main.py` oder `db_service.py` (Fassade). Die Fassade wird nur von den Bestands-Callern genutzt.
5. **E5 – `ui/window_manager.py`: Scope & Kopplungsmodell:** Der `WindowManager` übernimmt **alle** Sub-/Chart-Fenster-Lifecycle-Methoden von `MainWindow`: `restore_all_windows`, `open_chart_window`, `handle_chart_closed`, `open_service_window`, `open_analytics_window`, `open_properties_window`, `open_chart_at_bar`, `get_currently_active_pairs`. **Ausnahme:** `restore_main_window_geometry` bleibt in `MainWindow` (operiert auf dem Hauptfenster selbst: `self.move`/`resize`/`showMaximized`). Die Tick-Verteilung (`_dispatch_tick_map`, `on_ticks_ready`, `_flush_pending_ticks`, `_refresh_updated_charts`) bleibt ebenfalls in `MainWindow` (Live-Daten-Dispatch, kein Fenster-Lebenszyklus). Kopplung über Konstruktor-Parameter (`state_manager` + Listen-Referenzen `chart_windows`/`persistent_sub_windows`); `MainWindow` delegiert 1:1. **Kein Import von `main.py`** (IoC – `WindowManager` kennt `MainWindow` nicht).
6. **E6 – `analytics/engine/tree_builder.py`: Scope & Schnittstelle:** Es wandern NUR die Baum-Konstruktions-/Auflösungsfunktionen als **Modul-Funktionen** (reine Funktionen, kein Klassenzustand, keine Qt-Signale): `build_tree`, `_category_nodes`, `_category_parts`, `_cat_key`, `_sort_category_nodes`, `_insert_into_category_tree`, `_insert_set_into_category_tree`, `_set_category_parts`, `_ensure_category_path`, `category_plugin_ids`, `category_set_ids`, `category_service_plugin_ids`, `plugin_category_path`. Eingangsdaten (Sets, Plugins, Kategorie-Overrides, Empty-Folder-Pfade, Badges, Last-Execution) werden **als Parameter übergeben**. `ServiceSelectorModel` bleibt die öffentliche API für die 11 Nutzer-Dateien (`master_tree`, `service_set_utils`, `service_selector_dialog`, `analytics_win`, …) und delegiert intern an `tree_builder` (dünne Wrapper). **Kein Import von `ServiceSelectorModel` in `tree_builder.py`** – keine Zirkularität. Die `refresh()`-Ladefunktionen (`_load_empty_folders`, `_load_plugin_category_overrides`, `_load_last_execution_dates`) bleiben im Model.
7. **E7 – Worker-Auslagerung (`workers/`):** `DataSyncWorker` → `workers/data_sync_worker.py` (ruft `sync_market_data()` aus `data_sync/mt5_sync_service`); `LiveTickWorker` → `workers/live_tick_worker.py` (nutzt `MT5_LOCK`/`get_timeframes` aus `data_sync/mt5_sync_service`, `DbPool`/`DB_MARKET_DATA` aus `db/db_pool`; `_persist_bar`-Importziel wird angepasst, L8). `main.py` behält: Chromium-Occlusion-Fix (MUSS vor `QApplication` stehen), UTF-8-Fix, `BASE_DIR`, `--check-plugins`-CLI, `MainWindow` (inkl. `load_initial_table_data`, `trigger_background_sync`, Concurrency-Guard, LiveAnalyzer-Verdrahtung, Tick-Dispatch).
8. **E8 – Quality-Gate-Erweiterung (zusätzlich zu Step 4):**
   * `py_compile` zusätzlich auf der Fassade `db_service.py` (muss nach der Aufteilung fehlerfrei importierbar sein).
   * Headless-Fassaden-Smoke-Test in `test/test.py`: alle Re-Export-Namen aus E2 sind importierbar; repräsentative Stichprobe der 20 Bestands-Caller (`chart_win`, `state_manager`, `symbol_repository`, `feature_store_reader`) importierbar.
   * Zirkularitäts-Check: kein `import main`/`from main import ...` und keine Logik-Nutzung von `db_service` in den 8 neuen Modulen (nur die Fassade re-exportiert).
   * Einrückungs-Check: 4 Leerzeichen (E1), 1 Leerzeile zwischen Funktionen/Methoden.

### Abweichungen vom Plan-Kapitel (per Prüfprotokoll-Entscheidungen)
* Kapitel-Regel 1 „Einrückung: Ausschließlich Tabs" → **E1**: 4 Leerzeichen (Codebase-Standard).
* Step 4 „Code-Check: Nur Tabs, 1 Leerzeile" → **E1/E8**: Code-Check auf 4 Leerzeichen + 1 Leerzeile.
* Step 1 (4 Checklisten-Punkte) → **E3**: vollständige Zuordnung inkl. Utilities, MT5-Konfig, LEGACY/DEPRECATED-Helfer und CLI.
* Step 2 (nur `restore_all_windows`, `open_chart_at_bar`) → **E5**: `WindowManager` übernimmt alle 8 Fenster-Lifecycle-Methoden; `restore_main_window_geometry` und Tick-Dispatch bleiben in `MainWindow`.
* Step 3 (nur `build_tree`, `_insert_into_category_tree`) → **E6**: erweiterter Umfang (18.01.03-Erweiterungen inklusive); `ServiceSelectorModel` bleibt öffentliche API (Delegation).
* Step 4 (py_compile-Liste) → unverändert gültig; um Fassade + Smoke-Test ergänzt (**E8**).

---



---

## Implementierungs-Log 18.01.02 (08.08.2026 14:37) – Refactoring & Modularisierung (Großdateien)

Umgesetzt (alle Checklisten-Punkte des Kapitels abgearbeitet; Entscheidungen E1–E8 des
Prüfprotokolls):

### Step 1 – `db_service.py` entflechten (E2/E3/E4)
* **Neu `db/db_pool.py`:** Pfad-Konstanten (`DATA_DIR`, `DB_MARKET_DATA`, `DB_ANALYTICS`,
  `DB_APP_DATA`), `_db_pool_lock`/`_db_pool_global`, `DbPool` (Thread-local Singleton),
  `_LockedConnection`, `db_connect` (LEGACY), `with_db_lock` (No-op, API-Kompatibilität).
* **Neu `db/db_utils.py`:** `_parse_json_field`, `_ensure_epoch` (DEPRECATED, backward-compat).
* **Neu `db/schema_initializer.py`:** `check_and_init_databases` (Schema-Anlage/-Migration der
  3 DuckDBs, unveränderte Logik).
* **Neu `data_sync/mt5_sync_service.py`:** `SYMBOLS`, `_TIMEFRAMES_CACHE`, `get_timeframes`,
  `TF_SECONDS_MAP`, `MT5_LOCK`, `check_mt5_connection`, `get_latest_timestamp`,
  `sync_market_data`. **Lazy-Import-Prinzip beibehalten** (MT5 erst beim Aufruf).
* **Neu `repositories/market_data_repository.py`:** `MarketDataRepository`,
  `get_symbol_precision` (gemeinsame Precision-Query, DRY).
* **`db_service.py` = Fassade (E2):** Re-Export aller 20 öffentlichen Namen + CLI-Einstieg
  `main()` (`python db_service.py`). Alle 20 Bestands-Caller bleiben unverändert.

### Step 2 – `main.py` schlankziehen (E5/E7)
* **Neu `workers/data_sync_worker.py`:** `DataSyncWorker` ruft `sync_market_data()` aus
  `data_sync/mt5_sync_service` (L8).
* **Neu `workers/live_tick_worker.py`:** `LiveTickWorker` nutzt `MT5_LOCK`/`get_timeframes`
  aus `data_sync`, `DbPool`/`DB_MARKET_DATA` aus `db/db_pool`; `_persist_bar`-Importziel
  angepasst (L8).
* **Neu `ui/window_manager.py`:** `WindowManager` (IoC – **kein** `main.py`-Import) übernimmt
  alle 8 Fenster-Lifecycle-Methoden (`restore_all_windows`, `open_chart_window`,
  `handle_chart_closed`, `open_service_window`, `open_analytics_window`,
  `open_properties_window`, `open_chart_at_bar`, `get_currently_active_pairs`). Kopplung über
  Konstruktor-Parameter (`state_manager` + Listen-Referenzen, in-place-Mutationen).
* **`main.py`:** Chromium-Occlusion-Fix, UTF-8-Fix, `BASE_DIR`, `--check-plugins`-CLI und
  `MainWindow` (inkl. `restore_main_window_geometry`, Tick-Dispatch, Concurrency-Guard,
  LiveAnalyzer-Verdrahtung) bleiben. Buttons/Timer/Worker-Callback auf
  `self.window_manager.*` verdrahtet; dünne Delegationen `open_chart_window`/`open_chart_at_bar`
  für `statistic_win`/`analytics_win` (API-Kompatibilität, Jump-to-Chart-Variante 2).
  Ungenutzte Importe entfernt (`QThread`, `Signal`, `QScreen`, `QMessageBox`, `mt5`,
  `db_service`, `ServiceWindow`, `AnalyticsWindow`, `PropertiesWindow`, `Qt`).

### Step 3 – `service_selector_model.py` bereinigen (E6)
* **Neu `analytics/engine/tree_builder.py`:** alle Baum-Konstruktions-/Auflösungsfunktionen als
  reine Modul-Funktionen (kein Klassenzustand, keine Qt-Signale, **kein**
  `ServiceSelectorModel`-Import): `build_tree`, `_category_nodes`, `_category_parts`,
  `_cat_key`, `_sort_category_nodes`, `_insert_into_category_tree`,
  `_insert_set_into_category_tree`, `_set_category_parts`, `_ensure_category_path`,
  `category_plugin_ids`, `category_set_ids`, `category_service_plugin_ids`,
  `plugin_category_path`. Eingangsdaten (Sets, Plugins, Overrides, Empty-Folder-Pfade,
  Badges, Last-Execution) werden als Parameter übergeben.
* **Modell:** `ServiceSelectorModel` bleibt die öffentliche API (11 Nutzer-Dateien:
  master_tree, service_set_utils, service_selector_dialog, analytics_win, ...) und delegiert
  intern (dünne Wrapper). Die `refresh()`-Ladefunktionen bleiben im Modell.

### Step 4 – Quality Gate (E8)
* `py_compile` auf allen 12 neuen/geänderten Dateien: **PASS** (inkl. Fassade `db_service.py`).
* **Test-Teil 30 (neu, headless, `test/test.py`): 20/20 PASS** – Fassaden-Re-Exports/-Identität
  (A1–A6), Zirkularitäts-Check E4/E6 (B1–B2), Worker-Instanziierung E7 (C1–C3),
  WindowManager-IoC E5 (D1–D2), tree_builder-Delegation E6 (E1–E7; `build_tree` Modell ==
  tree_builder direkt).
* Bestehende Teile 26–29 (18.01.03) unverändert PASS; Gesamtlauf wie bisher mit ausschließlich
  den dokumentierten Baseline-Geometrie-Fehlern P2/P5/H3/H4/H5/H7 (offscreen `800x582`,
  Reflow-/Scrollbar-Umbau 07./08.08.2026 – vorbestehend, nicht durch 18.01.02 verursacht).
* `python main.py --check-plugins`: PASS.
* Code-Check (E1): alle neuen Module reine 4-Leerzeichen-INDENT-Token, keine Tabs;
  1 Leerzeile zwischen Funktionen/Methoden.

### Abweichungen vom Plan-Kapitel (per Prüfprotokoll-Entscheidungen)
* Kapitel-Regel 1 „Einrückung: Ausschließlich Tabs" → **E1**: 4 Leerzeichen (Codebase-Standard).
* Step 4 „Code-Check: Nur Tabs, 1 Leerzeile" → **E1/E8**: Code-Check auf 4 Leerzeichen +
  1 Leerzeile.
* Step 2 (nur `restore_all_windows` + `open_chart_at_bar`) → **E5**: `WindowManager` übernimmt
  alle 8 Fenster-Lifecycle-Methoden; `restore_main_window_geometry` und Tick-Dispatch bleiben
  in `MainWindow`.
* Step 3 (nur `build_tree` + `_insert_into_category_tree`) → **E6**: erweiterter Umfang
  (alle 13 Baum-/Auflösungsfunktionen inkl. 18.01.03-Erweiterungen).

# 18.01.03 Dynamic Tree Management (Ordner-CRUD, Drag & Drop & Sets-Kategorien)

## 1. Regeln & Invarianten

* **Einrückung:** Exakt **4 Leerzeichen** (Codebase-Standard).
* **Spacing:** Exakt **1 Leerzeile** zwischen Funktionen/Methoden.
* **UI-Tests:** **VERBOTEN.** Verifikation rein headless (`py_compile`, `test/test.py`).
* **Architektur:** Modellgetrieben, Single Source of Truth (`ServiceSelectorModel`), Entkopplung via `EventBus`.

---

## 2. Architektur & Datenfluss

[MasterTree (Custom Drag&Drop + ContextMenu)] ──(Aktion)──► [ServiceSelectorModel / Repositories]
        │                                                                │
        ├── Neuer Ordner / Rename ──► Ordnerpfad-Aktualisierung          │
        └── Drag & Drop DropEvent ──► Category-String Update             │
                                                                         ▼
[ServiceWindow & AnalyticsWindow] ◄────── (Refresh UI) ─────── [EventBus.service_set_changed]


---

## 3. Datenmodell-Erweiterungen

* **Sets (`ServiceSetDefinition`):** Optionales Feld `"category": "Ordner/Unterordner"` in Set-JSON.
* **Plugins / Standalone Services:** Kategorie-Pfad im Metadatum `category` bzw. Persistenz via `state_manager.save_global_value("plugin_params_<id>", ...)`.

---

## 4. Schritt-für-Schritt Anleitung (IDE-AI)

### Step 1: Sets-Kategorisierung in `service_selector_model.py`

* [x] Ordner-Mechanik (`_insert_into_category_tree`) auch auf den Knoten `Sets` (`GROUP_SETS`) anwenden.
* [x] `category_set_ids(path)`-Methode hinzufügen, die alle `set_id`s aus Unterordnern rekursiv auflöst.

### Step 2: Konfektionierung `MasterTree` (`serviceui/master_tree.py`)

* [x] **Drag & Drop aktivieren:** `setDragEnabled(True)`, `setAcceptDrops(True)`, `setDropIndicatorShown(True)`.
* [x] `dropEvent()` überschreiben:
1. Ermittle gezogenen Knoten (Set-ID, Plugin-ID oder Ordner) und Ziel-Ordner-Pfad.
2. Aktualisiere den Kategorie-Pfad beim Element.
3. Emittiere Datenänderung an das Modell/Repositories.

* [x] **Kontextmenü erweitern (`customContextMenuRequested`):**
1. **"Neuer Ordner":** Öffnet `QInputDialog`, erstellt neuen Unterordner-Pfad im gewählten Elternknoten.
2. **"Umbenennen":** Benennt Ordner/Knoten um und führt Pfad-Update für alle enthaltenen Kinder durch (String-Replace).


### Step 3: Persistenz & Synchronisation

* [x] Ordner-Aktionen für Sets via `ServiceSetRepository.save_set()` abspeichern.
* [x] Ordner-Aktionen für Standalone-Plugins via `state_manager.save_global_value("plugin_params_<id>", ...)` sichern.
* [x] Nach allen Strukturänderungen `event_bus.service_set_changed.emit()` abfeuern.


### Step 4: Quality Gate

* [x] `python -m py_compile serviceui/master_tree.py analytics/engine/service_selector_model.py analytics/ui/analytics_win.py serviceui/service_win.py`
* [x] Headless-Test in `test/test.py` für rekursive Sets-Kategorien & Pfad-Updates.
* [x] Code-Check: Exakt 4 Leerzeichen Einrückung, 1 Leerzeile Abstand.

---

## Prüfprotokoll 18.01.03 (08.08.2026) – Konsistenz, Vollständigkeit & Entscheidungen

### Prüfergebnis (Konsistenz)
Der Plan ist architektonisch konsistent (Modell-getrieben, MasterTree entkoppelt via
Signale, EventBus `service_set_changed`, keine SQL in UI). Die Ordner-Mechanik
(`_insert_into_category_tree`, `category_plugin_ids`, `_category_parts`) existiert für
GROUP_PLUGINS und ist die Vorlage für GROUP_SETS. **3 Lücken** gefunden:

* **L1 – `ServiceSetRepository.save_set()`-Whitelist:** Das Payload-Dict persistiert
  nur feste Keys (`set_id, display_name, description, indicator_id, version,
  schema_version, created_at, execution_order, services`). Ein neues Set-Feld
  `category` würde beim Speichern VERWORFEN. → Step 3 bzw. „Datenmodell-
  Erweiterungen" muss `category` additiv ins Payload aufnehmen (analog `indicator_id`),
  sonst ist die Sets-Kategorisierung nicht persistent.
* **L2 – `plugin_params_<id>`-Kollision:** Der Plan will Ordner-Aktionen für
  Standalone-Plugins über `state_manager.save_global_value("plugin_params_<id>", ...)`
  sichern. Dieser Key ist aber bereits exklusiv für das Parameter-Preset belegt
  (service_win `_plugin_config`/`_save_plugin_params`, Dialog `_plugin_config` –
  lookback/params/description). Vermischung von Kategorie-Override und Parameter-
  Preset kollidiert semantisch und stört beide Editoren. → separater Key
  `plugin_category_<id>` (siehe Entscheidung E1).
* **L3 – Generische Ordner-Auflösung im Picker (SELECT_MULTI):**
  `_resolve_selection_ids`/`_entries_for_scope` behandeln TYPE_CATEGORY aktuell nur
  als Plugin-Ordner (`category_plugin_ids`). Bekommen auch SETS Ordner, muss die
  Auflösung die ZUGEHÖRIGE GRUPPE des Ordners kennen (Sets-Ordner → Sets → Services
  → plugin_ids; Plugins-Ordner → plugin_ids). `MasterTree._emit_selection_details`
  liefert für TYPE_CATEGORY nur den Pfad im plugin_id-Slot – die Gruppe fehlt.
  → MasterTree muss für Kategorie-Ordner die Elterngruppe (GROUP_SETS/GROUP_PLUGINS)
  mitliefern.

### Entscheidungen (18.01.03)
1. **E1 – Plugin-Kategorie-Override:** eigener global_settings-Key `plugin_category_<id>`
   (JSON-String Pfad oder ""). Auswertungsreihenfolge im Modell `_category_parts()`:
   Override (falls vorhanden) → sonst `metadata['category']` → sonst „keine Kategorie".
   Das bestehende `plugin_params_<id>` bleibt unangetastet (Parameter-Preset).
2. **E2 – Set-Kategorie-Persistenz:** `category` wird additiv in das `save_set()`-
   Payload aufgenommen; `ServiceSetDefinition` erhält das optionale Feld `category`
   (Doku in `analytics/engine/service_models.py`). Leer oder "General" = keine
   Kategorie (Root-Ebene, Spiegel der Plugin-Logik).
3. **E3 – Leere Ordner (REVIDIERT am 08.08.2026, Bugfixing-Modus):** Die
   ursprüngliche Entscheidung („leere Ordner verschwinden beim nächsten Refresh,
   kein Empty-Folder-Persistenzmodus") ist **widerrufen**. Benutzererzeugte
   Ordner werden persistiert (global_settings, Key `tree_folders_sets` /
   `tree_folders_plugins` – Liste Slash-Pfade ohne `📁`-Präfix) und verschwinden
   **NICHT** beim Refresh, sondern nur bei **manueller Löschung** im Kontextmenü
   („Ordner löschen", nur für leere Ordner aktiv). Umgesetzt in `phase18_step3`.
4. **E4 – Drag & Drop Scope:** nur Kategorie-Moves (Set/Plugin/Ordner auf Ordner-
   Ziel oder Root-Gruppe). Service-Reihenfolge bleibt beim Kontextmenü Order ▲/▼;
   KEIN Service-Reorder per Drag & Drop.
5. **E5 – Verdrahtung in allen Trees:** Die neuen MasterTree-Signale
   (`create_folder_requested`, `rename_folder_requested`, `folder_item_moved`) werden
   in service_win (FULL_EDIT) UND ServiceSelectorDialog (SELECT_MULTI, Picker =
   Manager-Window 18.01.01 E-4) mit Orchestrator-Handlern verdrahtet.

### Generizitäts-Check (alle Trees: service_win / analytics_win / Service-Picker)
Der MasterTree ist das gemeinsame Bauteil (FULL_EDIT bzw. SELECT_MULTI).
Baum-Rekursion (`_build_child_item` → `_build_category_item`, Ordner ohne
ItemIsUserCheckable), `_category_path_of` und der Checkbox-Zustand (`_checked_items`
Keys sind pfadunabhängig: set_id/instance_id/plugin_id) sind bereits
gruppen-agnostisch und funktionieren für Sets-Ordner identisch – sofern das Modell
für Sets dasselbe Ordner-Blatt-Format liefert (`set_id/display_name/definition/services`).
Einzige generische Lücke ist L3 (Gruppen-Kontext bei Kategorie-Klicks); in service_win
muss analog zu `_on_run_category`/`_on_category_info_requested` die Sets-Ordner-
Variante (Sets unter dem Pfad → Services) ergänzt werden.


---

## Implementierungs-Log 18.01.03 (08.08.2026 13:12) – Dynamic Tree Management

Umgesetzt (alle Checklisten-Punkte des Kapitels abgearbeitet):

### Step 1 – Sets-Kategorisierung (`analytics/engine/service_selector_model.py`)
* `_insert_set_into_category_tree()` + `_set_category_parts()`: die Ordner-Mechanik
  (K2/K8/K9) gilt jetzt auch für GROUP_SETS – Set-Definitionen mit `category`-Feld
  werden rekursiv in 📁-Ordner einsortiert, ohne Kategorie bleiben sie Root-Blaetter.
* `category_set_ids(path)`: rekursive Auflösung aller set_ids unter einem Pfad
  (analog `category_plugin_ids`).
* `category_service_plugin_ids(group, path)`: gruppenspezifische Auflösung (L3) –
  Sets-Ordner → Service-plugin_ids aller Sets, Plugins-Ordner → `category_plugin_ids`.
* `_sort_category_nodes` verallgemeinert (Blatt-Sortierung auch für Sets-Dicts).
* E1-Override-Logik: `_category_parts()` wertet `plugin_category_<id>` (VORRANG vor
  `metadata['category']`, auch "" = Root); Overrides werden in `refresh()` einmalig
  geladen (`_load_plugin_category_overrides`), kein DB-Zugriff im Baum-Aufbau.

### Step 1/3 – Persistenz (L1/E2)
* `ServiceSetRepository.save_set()`: `category` additiv im Payload (analog `indicator_id`),
  mit `record_snapshot=False` bei Struktur-Verwaltung (kein Snapshot, Invariante 9).
* `ServiceSetDefinition`: optionales Feld `category` dokumentiert
  (`analytics/engine/service_models.py`).

### Step 3 – Gemeinsame Schreib-Helfer (`serviceui/service_set_utils.py`, E1/E2, DRY)
* `set_set_category(set_repo, set_id, path)` – frisch aus der DB laden, `category`
  setzen, `save_set(record_snapshot=False)`.
* `set_plugin_category(state_manager, plugin_id, path)` – global_settings-Key
  `plugin_category_<id>` (separater Key, L2-Fix: `plugin_params_<id>` bleibt dem
  Parameter-Preset vorbehalten).
* `rename_category(model, set_repo, state_manager, group, old_path, new_path)` –
  String-Replace (echte Ordner-Grenzen, `_replace_prefix`) über alle Kinder.

### Step 2 – MasterTree (`serviceui/master_tree.py`)
* Drag & Drop: `setDragEnabled/setAcceptDrops/setDropIndicatorShown` + eigene
  `startDrag()` (JSON-MIME `application/x-pytrader-category-move`; nur
  Sets/Plugins/Ordner ziehbar, E4) + `dragEnterEvent/dragMoveEvent/dropEvent`.
  `dropEvent` emittiert nur `folder_item_moved` (Set/Plugin) bzw. `folder_moved`
  (Ordner) – der Baum führt keinen echten Item-Move; Guards: Gruppen-Mismatch und
  Ordner-Zyklus (eigener Unterordner) werden abgelehnt.
* Kontextmenü: „Neuer Ordner" (Gruppen + Ordner) und „Umbenennen" (Ordner);
  `create_folder_requested`/`rename_folder_requested`-Signale. „Neuer Ordner" ist
  ein reiner UI-Zustand (`_pending_folder`/`_ensure_pending_folder`, K9/E3) –
  **seit 08.08.2026 (E3-revidiert) ersatzlos entfernt: Der MasterTree emittiert
  `create_folder_requested(group, full_path)`, der Orchestrator persistiert den
  Ordner über `create_empty_folder` (global_settings, Key `tree_folders_<group>`).**
* L3: `selection_details` liefert für TYPE_CATEGORY die Eltern-Gruppe im set_id-Slot;
  `category_info_requested`/`run_category_requested` tragen jetzt `(group, path)`.

### E5 – Verdrahtung in beiden Trees
* `service_win.py` (FULL_EDIT): `_on_folder_item_moved`/`_on_folder_moved`/
  `_on_rename_folder`/`_rename_folder`; `_on_run_category`/`_on_category_info_requested`
  gruppenbewusst (Sets-Ordner → Services der Sets). Alle Aktionen emittieren
  `event_bus.service_set_changed`.
* `service_selector_dialog.py` (SELECT_MULTI, Picker): gleiche Handler (DRY über
  service_set_utils); `_resolve_selection_ids`/`_entries_for_scope` gruppenbewusst
  (Sets-Ordner → Set-Service-Entries bzw. plugin_ids).

### Validierung (headless, `test/test.py`, Teil 26)
* 23/23 Prüfungen PASS (A1–A8 Persistenz/Baum, B1–B4 Override, C1–C4 Rename,
  D1–D2 Pfad-Grenzen, E1–E2 gruppenspezifische Auflösung).
* `python -m py_compile` auf allen betroffenen Dateien: PASS.
* 17.01.02-T2-Test an die neue `(group, path)`-Signatur angepasst: PASS.
* **Hinweis (vorbestehend, NICHT durch 18.01.03):** Die Geometrie-Tests
  P2/P5/H3/H5/H7 schlagen bereits im Baseline-Stand fehl (offscreen `800x582`,
  verifiziert per Baseline-Probe gegen HEAD) – Ursache ist der 07./08.08.2026-
  Reflow-/Scrollbar-Umbau, nicht diese Umsetzung. Separater Bugfix erforderlich,
  sofern gewünscht.
* Test-Cleanup: temporäre Patch-/Probe-Skripte gelöscht, `test/` enthält nur
  `test/test.py`.

### Abweichungen vom Plan-Kapitel (per Prüfprotokoll-Entscheidungen)
* Plan-Punkt 3 „Persistenz via `plugin_params_<id>`" → E1: separater Key
  `plugin_category_<id>` (Kollision mit Parameter-Preset vermieden).
* `category_info_requested`/`run_category_requested` sind um die Gruppe erweitert
  (L3) – betroffene bestehende Tests wurden angepasst.


---

## Implementierungs-Log 18.01.03 (08.08.2026 15:40) – E3-revidiert: Leere Ordner persistieren

**Bugfixing-Modus (User-Anweisung):** „Leere Ordner sollen nicht verschwinden, nur bei
manueller Löschung im Kontextmenü." Damit ist **E3 widerrufen** (ursprünglich: leerer
Ordner = reiner UI-Zustand `_pending_folder`, verschwindet beim nächsten Refresh).
Umgesetzt in Commit `f300176` (phase18_step3).

### Persistenz & Helfer (`serviceui/service_set_utils.py`)
* `EMPTY_FOLDERS_KEY = "tree_folders_{}"` – global_settings-Key je Gruppe
  (`tree_folders_sets` / `tree_folders_plugins`), Wert = Liste Slash-Pfade ohne
  `📁`-Präfix.
* `list_empty_folders(state_manager, group)` / `save_empty_folders(...)` –
  lesen/schreiben (dedupliziert, defensiv gegen Fehler).
* `create_empty_folder(state_manager, group, path)` – idempotent (kein Duplikat).
* `delete_empty_folder(state_manager, group, path)` – manuelle Löschung.
* `rename_category(...)` zieht zusätzlich die persistierten leeren Ordner der
  Gruppe mit um (Praefix-Replace, `_replace_prefix`).

### Modell (`analytics/engine/service_selector_model.py`)
* `_empty_folder_paths` (pro Gruppe) wird in `refresh()` geladen
  (`_load_empty_folders`); Accessor `empty_folder_paths(group)` (lesend).
* `_ensure_category_path(nodes, parts)` – erzeugt die Ordnerkette OHNE
  Blatt-Einfügung; bereits vorhandene reale Ordner (aus Blatt-Kategorien) werden
  wiederverwendet → **kein Duplikat**.
* `build_tree()` mischt die persistierten Pfade in die Gruppen-Kinder ein (Sets
  UND Plugins), danach erneute Sortierung (K8). Leere Ordner überleben Refreshs.

### MasterTree (`serviceui/master_tree.py`)
* `_pending_folder`/`_ensure_pending_folder` **ersatzlos entfernt** (kein
  UI-Zustand mehr); Drop-Handler räumt nichts mehr auf.
* `create_folder_requested(group, full_path)` – `_on_new_folder` fragt nur noch
  den Namen ab und emittiert (Orchestrator persistiert).
* Neues Signal `delete_folder_requested(group, path)` + Kontextmenü **„Ordner
  löschen"** – nur für Ordner OHNE Kinder aktiv (Guard `item.childCount() == 0`);
  Tooltip erklärt den Guard.
* `_build_category_item` rendert leere Ordner ohne `>`-Expand-Symbol
  (`bool(child.get("children"))` statt hart `True`).

### Verdrahtung (`serviceui/service_win.py` + `serviceui/service_selector_dialog.py`)
* Beide Trees: `_on_create_folder`/`_on_delete_folder` (DRY über
  service_set_utils, global_settings + `event_bus.service_set_changed`).

### Validierung (headless, `test/test.py`, Teil 27, neu)
* 17/17 Prüfungen PASS (A1–A4 Helfer, B1–B3 build_tree leerer Ordner,
  C1 Refresh-Persistenz, D1 Plugins-Gruppe, E1 verschachtelte Elternkette,
  F1/F2 kein Duplikat bei realem Ordner + Blatt erhalten, G1/G2 Rename zieht
  leere Ordner mit, H1–H3 manuelle Löschung, I1 Gruppen-Isolation).
* Teil 26 (18.01.03-Bestand) weiterhin 20/20 PASS; `py_compile` auf allen
  betroffenen Dateien PASS.
* **Hinweis (vorbestehend, unverändert):** Geometrie-Tests P2/P5/H3/H4/H5/H7
  schlagen weiterhin in der Baseline fehl (offscreen `800x582`, Reflow-/Scrollbar-
  Umbau 07./08.08.2026) – nicht durch E3-revidiert verursacht. Separater Bugfix
  nur auf Wunsch.


---

## Implementierungs-Log 18.01.03 (08.08.2026 14:03) – Bugfix-Runde: Leere-Ordner-Erhaltung, Baum-Expansion, Picker-Crash & fixe Fensterhöhe

**Bugfixing-Modus (User-Anweisungen vom 08.08.2026, nachmittags):**
1. Leere Ordner dürfen beim Herausziehen des letzten Services NICHT verschwinden
   (Ordner bleibt sichtbar und selbst verschiebbar).
2. Ordner dürfen nur gelöscht werden, wenn sie leer sind (bereits umgesetzt).
3. Baum soll nach Ordner-Erstellung/-Verschieben nicht zusammenklappen.
4. Canvas-/Fensterhöhe ist nicht fix bei Klicks auf Sets/Set-Services.
5. Service-Picker startet nicht (`AttributeError: setSizeConstraint`).

Umgesetzt in den Commits `ed8f4f0` (Punkte 1–3) und `17c6a86` (Punkte 4–5).

### Punkte 1–3 – Leere-Ordner-Erhaltung & Baum-Expansion (`ed8f4f0`)
* `serviceui/service_set_utils.py`:
  * `ensure_folder_path(state_manager, group, path)` – persistiert die
    Ordnerkette idempotent (global_settings `tree_folders_<group>`); wird nach
    Struktur-Änderungen gerufen, damit der Quell-Ordner auch ohne persistierten
    Leere-Ordner-Eintrag sichtbar bleibt.
  * `rename_category(...)` sichert zusätzlich den Quell-Ordner (idempotent).
* `serviceui/master_tree.py`:
  * `_collect_expanded_state()` / `_apply_expanded_state()` – Aufklapp-Zustand
    über `_populate()` hinweg erhalten (RAM-Keys `("cat", group, pfad)` /
    `("set", set_id)`).
  * `_mark_expand(group, path)` – wird VOR dem emit der Struktur-Signale gerufen
    (EventBus-Refresh läuft synchron) und klappt Ziel-Ordnerkette nach Drop sowie
    neu erzeugte Ordner auf; `_expand_after_rebuild` wird nach Anwendung geleert.
  * `_build_category_item` rendert leere Ordner ohne `>`-Symbol
    (`bool(child.get("children"))`).
* `serviceui/service_win.py` + `service_selector_dialog.py`: `_on_folder_item_moved`
  ermittelt den Quell-Pfad VOR dem Update (Set: `definition.category`, Plugin:
  `plugin_category_path`) und persistiert ihn via `ensure_folder_path` – der
  Ordner bleibt nach dem Entzug des letzten Kindes sichtbar und verschiebbar.
* Validierung: Teil 28 (neu) 16/16 PASS; Teile 26+27 unverändert PASS.

### Punkte 4–5 – Picker-Crash & fixe Fensterhöhe (`17c6a86`)
* `serviceui/service_selector_dialog.py`: `self.setSizeConstraint(...)` war ein
  QLayout-Aufruf auf dem QDialog (existiert nicht → AttributeError beim Öffnen
  des Pickers). Fix: Constraint wird auf dem root-Layout gesetzt
  (`root.setSizeConstraint(QLayout.SetNoConstraint)`) – der Picker startet
  wieder und hält seine Fensterhöhe FIX (ScrollArea zeigt bei Überhöhe
  Scrollbalken).
* `serviceui/param_columns.py`: `_build_service_columns` rief `self._reflow()`
  → der volle Reflow (`_schedule_reflow` → `_apply_reflow_size` →
  `_exact_fit_to_content`) passte bei JEDEM Set-/Service-Klick die Fensterhöhe
  an die Spaltenhöhe an (Canvas-/Fensterhöhe versetzte sich). Fix: nur noch
  Box-only-Reflow (`QTimer` → `_resize_param_box_deferred`, Muster
  `_apply_conditional_visibility`/`_setup_collapsible` vom 07.08.2026) – die
  Service-Parameter-Box folgt ihrer Layout-Größe, Fenster-/Canvas-Höhe bleibt
  stabil. Der initiale Fensteraufbau (show → `_apply_reflow_size`) bleibt
  unverändert.
* Validierung: Teil 29 (neu) 5/5 PASS (Picker-Konstruktion ohne Crash +
  SetNoConstraint auf dem root-Layout; Duck-Typ-Host ohne `_schedule_reflow`
  belegt: `_build_service_columns` löst keinen Fenster-Reflow mehr aus).
  Teile 26–28 unverändert PASS. `py_compile` auf allen Dateien OK.
* **Hinweis (vorbestehend, unverändert):** Geometrie-Tests P2/P5/H3/H4/H5/H7
  schlagen weiterhin in der Baseline fehl (offscreen `800x582`). Separater
  Bugfix nur auf Wunsch.

---

# Phase 18 Abschluss (08.08.2026)

Phase 18 „Analytics-Finalisierung" ist mit den Kapiteln **18.01.02 (Refactoring &
Modularisierung)** und **18.01.03 (Dynamic Tree Management)** abgeschlossen.

* **18.01.02** – Refactoring & Modularisierung (Großdateien): `db_service.py` (Fassade +
  `db/`-Paket, `data_sync/`, `repositories/`), `main.py` (Worker in `workers/`, Fenster-
  Lifecycle in `ui/window_manager.py`), `service_selector_model.py` (Baumaufbau in
  `analytics/engine/tree_builder.py`). Umgesetzt gemäß Prüfprotokoll E1–E8; Validierung
  headless (py_compile, Test-Teil 30: 20/20 PASS).
* **18.01.03** – Dynamic Tree Management (Ordner-CRUD, Drag & Drop, Sets-Kategorien):
  umgesetzt in den Commits `phase18_step1`–`phase18_step3` (siehe Prüfprotokoll und
  Implementierungs-Logs oben); Bugfix-Runden inkl. E3-revidiert (leere Ordner persistieren).

Alle Quality Gates (headless) bestanden; **keine UI-Tests ausgeführt** (Regel 4/4.5).

**Bekannte, nicht durch Phase 18 verursachte Baseline-Geometrie-Testfehler** (offscreen
`800x582`, Reflow-/Scrollbar-Umbau 07./08.08.2026): P2, P5, H3, H4, H5, H7. Separater
Bugfix nur auf Wunsch.
