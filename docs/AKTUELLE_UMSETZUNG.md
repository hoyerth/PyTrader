# Phase 15: Service UI, Symbol-Verwaltung & Analytics Engine

## 1. Übersicht & Zielsetzung

Ziel von **Phase 15** ist die Weiterentwicklung der Service-UI (`service_win.py`), die Bereitstellung einer zentralen Symbol- und Favoritenverwaltung, der systematische Abbau von Alt-Pfaden sowie der Aufbau einer hochperformanten, entkoppelten Analytics-Engine auf Basis der Plugin- und Service-Architektur (Phasen 12–14).

* **15.01 Symbol-Auswahl & Favoriten:** Broker-Fetch via MT5, Persistierung in `app_data.duckdb`, Favoriten-Dropdowns & nicht-modales `SymbolsWindow`.
* **15.02 Service-UI Refactoring & Master-Tree:** Modularisierung der gewachsenen `service_win.py` in Orchestrator + Sub-Widgets (`MasterTree`, `ParameterPanel`, `Toolbar`), Einführung von `ServiceTreeModel`, 2-Spalten-TreeWidget mit Indikator-Live-Status (`📌` / `🟢`) & Buttons für Struktur-Aktionen.
* **15.03 Analytics Engine & UI:** Ersetzung von `../../statistic_win.py` durch `AnalyticsWindow` (`analytics/ui/analytics_win.py`), Entkopplung via MVVM (`AnalyticsViewModel`, `AnalyticsRepository`, `FeatureStoreReader`), `pyqtgraph`-Visualisierungen (Tabelle, Heatmap, Scatter, Verteilung), Profil-CRUD mit Explicit Save (`*`) & `schema_version` im Profil-JSON, Entkopplung über einen zentralen `EventBus`.

---

## 2. Allgemeine Grundsätze & Architektur-Invarianten

2. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase15_step1`, `phase15_step2` usw.).
3. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte in `test`.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
5. **Zentraler `EventBus`:** Fenster kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db_service.py`).
7. **Wanduhr-Garantie:** Achsen und Zeitfilter formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.

### Entscheidungs-Protokoll Phase 15 (Beschluss 04.08.2026)

| # | Thema | Entscheidung |
| --- | --- | --- |
| E-1 | Legacy-Alias `../../analytics/statistics_repository.py` | Bleibt bis auf Weiteres unverändert bestehen; kompletter Ersatz erst in einer späteren Phase |
| E-2 | Persistenz `win_statistics` | Fenstergeometrie & Instanz-Zustände werden beim Ersetzen nach `win_analytics` migriert |
| E-3 | `schema_version` Pflichtfeld | Pflichtfeld im `FeatureStorePayload`; alte `feature_store`-Rows erhalten beim Lesen den Default `"1.0"` |
| E-4 | Schutzregel Grid-Liquidity | Schutz für `../../chart/indicators/grid_liquidity.py` aufgehoben; Anpassungen erlaubt, wenn der Fallback-Abbau sie erfordert |
| E-5 | Zeilenzahl `service_win.py` | Doku-Korrektur: 864 Zeilen (statt 1.400) |
| E-6 | Pfad-Konvention | Dateien werden einheitlich vom Projekt-Root referenziert (ohne `../..`) |

---

# 15.03 Analytics Engine & UI

## 1. SPEZIFIKATION (15.03)

* **Ersetzung `../../statistic_win.py`:** Vollständiger Austausch durch `AnalyticsWindow` (`analytics/ui/analytics_win.py`).
* **Persistenz-Migration (E-2):** Beim Ersetzen werden Fenstergeometrie & Instanz-Zustände von `win_statistics` nach `win_analytics` migriert (über `window_state_repository.py`, siehe 15.04).
* **Legacy-Alias (E-1):** Das bestehende `../../analytics/statistics_repository.py` (aktuell von `../../statistic_win.py` genutzt) bleibt vorerst unverändert bestehen; ein kompletter Ersatz durch `FeatureStoreReader`/`AnalyticsRepository` ist erst in einer späteren Phase vorgesehen.
* **Ablage & Modularisierung der UI (`analytics/ui/`):**
* `analytics_win.py`: Hauptfenster (`PersistentWindow`, `win_analytics`, `1280 x 800`, nicht-modal).
* Sub-Pages: `table_page.py`, `heatmap_page.py`, `scatter_page.py`, `distribution_page.py`, `equity_page.py`.
* **MVVM & Repository-Architektur:**
* `FeatureStoreReader`: Kapselt rein lesend DuckDB-Abfragen auf `feature_store`.
* `AnalyticsRepository`: Bietet High-Level Datenmethoden (`get_heatmap()`, `get_distribution()`, `get_scatter()`, `get_table()`).
* `AnalyticsViewModel`: Vermittelt zwischen Repository, Async-Worker und UI-Pages.
* **Profil-Management & Explicit Save:**
* Tabelle `analytics_profiles` in `app_data.duckdb` (inkl. `schema_version: 1` im Payload-JSON).
* **Option B (Explicit Save):** Slider-/Parametertrends setzen Dirty-Flag (`*` im Titel/Combo); Speichern erst bei Klick auf `[💾 Save]`.
* **Plotting & Performance (`pyqtgraph`):**
* Heatmap: 2D-Matrix (X: Wochentage, Y: Tagesstunden Berlin Wanduhr).
* QTimer-Debounce (200–300 ms) auf allen UI-Slidern gegen SQL-Feuer.
* Max-Lookback-Cap (max. 50.000 Kerzen) & Async-Worker mit Progress-Spinner / "No Data"-Overlay.
* **Jump-to-Chart (Variante 2):** Jeder Klick auf Signale in Tabelle, Heatmap oder Scatter ruft `open_chart_at_bar(symbol, tf, bar_time)` auf und bringt das Chart-Fenster in den Vordergrund.

## 2. SCHRITT-FÜR-SCHRITT ANLEITUNG (15.03)

1. **Backup:** Git Commit `phase15_s3_backup`.
2. **Profile-Repository & Schema (`analytics_profile_repository.py`):**
* Anlegen der Tabelle `analytics_profiles` in `app_data.duckdb` mit `schema_version` im JSON.
* Implementieren der CRUD-Operationen.

3. **Reader & Analytics-Repository:**
* `analytics/engine/feature_store_reader.py`: Reines Auslesen des `feature_store`.
* `analytics/engine/analytics_repository.py`: Methoden für Heatmap-, Scatter- und Verteilungs-Matrizen.

4. **ViewModel & Worker:**
* `analytics/engine/analytics_worker.py`: Async Worker für DuckDB-Queries.
* `analytics/engine/analytics_view_model.py`: Verwaltung des aktiven Profils, Dirty-States (`*`) & Debouncing.

5. **UI-Pages & `analytics_win.py`:**
* Erstellung der Einzelseiten in `analytics/ui/` (`table_page.py`, `heatmap_page.py`, `scatter_page.py`, `distribution_page.py`, `equity_page.py`).
* `analytics_win.py` als `PersistentWindow` mit Top-Bar CRUD & Sidebar-Navigation aufbauen.
* Klick-Events in Plots/Tabellen an `open_chart_at_bar()` koppeln.
* Alt-Fenster `../../statistic_win.py` in `../../main.py` durch `AnalyticsWindow` ersetzen.
* Bestehende `win_statistics`-Persistenz migrieren (E-2): Fenstergeometrie & Instanz-Zustände nach `win_analytics` übernehmen (via `window_state_repository.py`).

6. **Headless-Test (`test/check_p15_s3_analytics.py`):** Validierung von Profiles-CRUD, SQL-Aggregationen, Reader & ViewModel ohne GUI.

---

## 3. Implementierungs-Log

### 3.1 Schritt 1 – Backup (Commit `7862134`, Tag `phase15_s3_backup`)

Arbeitsstand vor der 15.03-Umsetzung als Git-Commit gesichert: `docs/AKTUELLE_UMSETZUNG.md` wurde vom Anwender neu aufgesetzt (15.01-Sektion + bisheriges Implementierungs-Log entfernt, dafür 15.03-Spezifikation aufgenommen); die alten Nachtrag-Texte wurden nach `docs/Old/x_Roadmap_Phase15.md` archiviert. Tag `phase15_s3_backup` gesetzt.

### 3.2 Schritt 2 – Analytics-Profile-Repository & Schema

**`db_service.py` (Anpassung):** In `check_and_init_databases()` (Block `con_app`, `app_data.duckdb`) wird die Tabelle **`analytics_profiles`** additiv/idempotent angelegt:
* `profile_id VARCHAR PRIMARY KEY`, `name VARCHAR NOT NULL`, `description VARCHAR`, `payload JSON`, `is_active BOOLEAN DEFAULT FALSE`, `created_at/updated_at TIMESTAMP DEFAULT current_timestamp`.
* Bestehende Daten bleiben unangetastet (Verbotsregel).

**`analytics_profile_repository.py` (NEU, Projekt-Root – konsistent zu `symbol_repository.py`):** `AnalyticsProfileRepository` kapselt den kompletten Zugriff (kein SQL in UI, Invariante 4):
* `create_profile(name, payload, description)` – legt an, liefert `profile_id` (uuid4-hex); ergänzt den Payload **additiv um das Pflichtfeld `schema_version` (Default 1)** – eine explizit mitgegebene `schema_version` gewinnt.
* `get_profile(profile_id)` / `get_profile_by_name(name)` (case-insensitive) – lesen den Payload via `_parse_json_field`; **Alt-Rows ohne `schema_version` erhalten beim Lesen den Default 1** (analog E-3).
* `list_profiles()` – alle Profile, deterministisch nach Name sortiert.
* `update_profile(profile_id, name?, description?, payload?)` – nur übergebene Felder (additiv); Payload behält sein `schema_version`-Pflichtfeld.
* `delete_profile(profile_id)` – hartes Löschen (bool).
* `set_active(profile_id)` / `get_active_profile()` – **genau EIN aktives Profil** (Grundlage für Option B / Explicit Save).
* `count()` – Anzahl.
* `get_analytics_profile_repository()` – app-weite Standard-Instanz (lazy).

DuckDB-Hinweis: Die `JSON`-Spalte wird beim Lesen mit `_parse_json_field` (str→dict) aufgelöst; beim Schreiben wird `json.dumps(payload)` verwendet (identisches Muster wie `service_set_repository.py`).

**Headless-Test (`test/check_p15_s3_profiles.py`, NEU):** Test-DB in `test/p15_s3_profiles_test.duckdb` (Regel: keine Test-DBs im Root/`data`), kein `QApplication.exec()`.

**Ergebnis: 30/30 Checks PASS** (Exit 0):

| Bereich | Checks | Inhalt |
| --- | --- | --- |
| A DB-Schema | A1–A2 | Tabelle angelegt, `_ensure_table()` idempotent |
| B CRUD | B1–B16 | create/get/get_by_name/list/update/delete/count; case-insensitive, additiv |
| C Aktives Profil | C1–C6 | genau EIN aktives Profil, get_active_profile |
| D Schema-Konvention | D1–D4 | `schema_version`-Pflichtfeld (Default 1), explizite Version gewinnt, Alt-Row-Default |

Zusätzlich: `py_compile` auf `analytics_profile_repository.py`, `db_service.py` und dem Test (Exit 0); bestehender Test `test/check_p15_s1_symbols.py` weiterhin **30/30 PASS** (db_service-Änderung additiv). Keine UI-/Regressionstests (Regel 4).

### 3.3 Schritt 3 – FeatureStoreReader & AnalyticsRepository

**`analytics/engine/feature_store_reader.py` (NEU):** `FeatureStoreReader` – reiner Lese-Zugriff auf den `feature_store` (Invariante 4 / MVVM: DuckDB → Reader → Repository → ViewModel → UI). Keine Berechnungen, kein Schreiben:
* `fetch_rows(symbol, timeframe, feature_id?, limit?)` – Zeilen als Dicts (time als **Wanduhr-Epoch** int, native Spalten, `feature_data` geparst).
* `fetch_columns(symbol, timeframe, columns, feature_id?, limit?)` – nur native Spalten (non-null) für Scatter/Histogramm.
* `fetch_heatmap(symbol, timeframe, metric?, feature_id?)` – 2D-Matrix (rows=Stunde 0–23, cols=DOW 0=So..6=Sa); `metric`: `"count"` (0 für leere Zellen) oder native Spalte (`AVG`, nan für leere Zellen); unerlaubte Metrik → `ValueError`.
* `get_available_features(symbol, timeframe)` – verfügbare Plugin-IDs, native Spalten, Zeilenzahl.
* **E-3:** Alt-Rows ohne `schema_version` in `feature_data` erhalten beim Lesen den Default `"1.0"` (DB bleibt unverändert).
* **Wanduhr-Garantie (Invariante 7):** Für die Heatmap wird `EXTRACT(DOW/HOUR FROM bar_time AT TIME ZONE 'UTC')` verwendet. **Umsetzungs-Erkenntnis:** DuckDB rechnet `EXTRACT(HOUR FROM TIMESTAMPTZ)` ohne Forcierung in die **System-Lokalzeit** um (Berlin +2h/+1h, DST-bruchig; an Tagesgrenzen verschiebt sich sogar der Wochentag). Da die gespeicherten Werte Berlin-Wanduhr-encoded sind (die UTC-Darstellung IST die Wanduhr-Zeit), liefert die UTC-Forcierung exakt die Wanduhr-Stunde/-Tag.

**`analytics/engine/analytics_repository.py` (NEU):** `AnalyticsRepository` – High-Level-Datenmethoden (delegiert lesend an den Reader):
* `get_table(symbol, timeframe, feature_id?, limit?)` → `{"rows", "total"}`.
* `get_heatmap(symbol, timeframe, metric?, feature_id?)` → 2D-Matrix (X: Wochentage, Y: Tagesstunden Berlin Wanduhr) + Labels.
* `get_scatter(symbol, timeframe, x_column?, y_column?)` → `{"points": [{x, y}], ...}` (nur finite Werte; unerlaubte Spalten → `ValueError`).
* `get_distribution(symbol, timeframe, column?, bins?)` → Histogramm `{"bins", "counts", ...}` via `numpy.histogram` (NaN/Inf gefiltert).
* `get_available_features()`, `available_heatmap_metrics()`, `native_columns`.
* E-1: Das Alt-Repository `analytics/statistics_repository.py` bleibt unverändert bestehen (Legacy-StatisticWindow).

**Headless-Test (`test/check_p15_s3_reader_repo.py`, NEU):** Test-DB in `test/p15_s3_reader_test.duckdb` (Regel: keine Test-DBs im Root/`data`), Wanduhr-encoded Testdaten (inkl. Tagesgrenze Fr 23:00).

**Ergebnis: 39/39 Checks PASS** (Exit 0):

| Bereich | Checks | Inhalt |
| --- | --- | --- |
| A fetch_rows | A1–A11 | Zeilen/epoch/schema_version-Default (E-3)/feature_id-Filter/limit/leere Filter |
| B fetch_heatmap | B1–B14 | 24×7-Matrix, count/avg an korrekter Zelle, leere Zellen, **Tagesgrenze Wanduhr** (Fr 23:00 → HOUR=23, DOW=5; ohne UTC-Forcierung wäre Sa 01:00), feature_id-Filter, ValueError |
| C AnalyticsRepository | C1–C9 | get_table/get_scatter/get_distribution, ValueError bei unerlaubten Spalten, Metadaten |

Zusätzlich: `py_compile` auf Reader, Repository und Test (Exit 0). Keine UI-/Regressionstests (Regel 4).

### 3.4 Schritt 4 – Analytics-ViewModel & Async-Worker

**`analytics/engine/analytics_worker.py` (NEU):** `AnalyticsAsyncWorker` (QThread, EINWEG-Worker – eine Abfrage pro Instanz) fuer asynchrone DuckDB-Queries (15.03-Spez: „Async-Worker mit Progress-Spinner / No Data-Overlay"). Analogie: `ServiceSetRunWorker`/`LiveAnalyzer`.
* `QUERY_TABLE/QUERY_HEATMAP/QUERY_SCATTER/QUERY_DISTRIBUTION/QUERY_FEATURES` – query_kind-Konstanten (Single Source of Truth fuer Worker & ViewModel).
* Dispatch auf `AnalyticsRepository`-Methoden (lesend, kein SQL im Worker; Invariante 4).
* Thread-Safety: Der Worker-Thread erhaelt ueber den Thread-local `DbPool` automatisch seine eigene DB-Connection (Invariante 6), blockiert nie den Hauptthread.
* **Max-Lookback-Cap (15.03-Spez):** `MAX_LOOKBACK_LIMIT = 50_000` + `cap_lookback_limit()` deckeln alle limit-Parameter hart (None bleibt None/Repo-Default, Werte < 1 → 1).
* Signale `finished_ok(str, dict)` / `failed(str, str)` (vom Worker-Thread; Qt Queued Connection zum ViewModel). `cancel()` unterdrueckt Ergebnis-Signale.

**`analytics/engine/analytics_view_model.py` (NEU):** `AnalyticsViewModel` (QObject) – MVVM-Vermittler zwischen Repository, Async-Worker und UI-Pages (kein SQL, kein UI; nur Qt-Core).
* **Datenfluss:** UI ruft `request_*()`/`set_*()` auf → ViewModel puffert Parameter → **Debounce-QTimer (250 ms, 15.03-Spez 200–300 ms)** → `AnalyticsAsyncWorker` → `data_ready(query_kind, data)`. Parameternaenderungen feuern die betroffenen Abfragen automatisch nach (symbol/timeframe/feature_id → alle; heatmap_metric → Heatmap; scatter_x/y → Scatter; column/bins → Verteilung; limit → Tabelle/Scatter/Verteilung).
* **Progress-Spinner:** `busy_changed(bool)` True beim Worker-Start, False wenn die Warteschlange leer ist; mehrere gepufferte Kinds werden sequenziell abgearbeitet (`_pending_kinds`-Queue).
* **Profil-Verwaltung (Option B – Explicit Save):** `create_profile` (sofort aktiv, genau EIN aktives), `save_profile` (persistiert aktuelle Parameter in den Payload inkl. `schema_version`), `update_profile` (Name/Beschreibung additiv), `delete_profile`, `set_active_profile`/`load_profiles`; **Dirty-Flag** `dirty_changed(bool)` nur bei vorhandenem aktivem Profil (Slider-/Parametertrends → `*` im Titel/Combo; Save setzt zurueck).
* **EventBus (Invariante 5):** Profilwechsel (create/save/activate/update) emittiert `event_bus.profile_changed(name)`.
* **Clamping:** `set_bins` (≥ 2), `set_limit` (1…`MAX_LOOKBACK_LIMIT`); `_apply_profile` uebernimmt Profil-Parameter typ-sicher und loest `refresh_all()` aus.
* Properties fuer UI-Dropdowns: `heatmap_metrics`, `native_columns`, `max_lookback_limit`, `params`, `active_profile`, `profiles`, `is_dirty`.
* `shutdown()` stoppt Debounce + laufenden Worker (Fenster schliessen).

**Headless-Test (`test/check_p15_s3_worker_vm.py`, NEU):** Test-DBs in `test/` (`p15_s3_worker_analytics.duckdb`, `p15_s3_worker_app.duckdb`); asynchroner Datenfluss nur mit `QCoreApplication` + `processEvents()` (KEIN GUI, kein `exec()`).

**Ergebnis: 49/49 Checks PASS** (Exit 0):

| Bereich | Checks | Inhalt |
| --- | --- | --- |
| A Worker-Dispatch & Cap | A1–A9 | Dispatch aller 5 Kinds (RecordingRepo-Stub), **limit-Cap 100.000→50.000**, None/negativ, `cap_lookback_limit`, unbekannter Kind → failed |
| B Worker + echtes Repo | B1–B5 | get_table/heatmap/scatter/distribution/features via `run()` mit Test-DB |
| C ViewModel Profil & Dirty | C1–C23 | create→aktiv + EventBus, Payload mit `schema_version`, Duplikat→ValueError, Dirty→Save→Dirty False, set_active/delete, limit-Cap, Properties |
| D ViewModel asynchron | D1–D7 | Debounce+Worker-Thread → data_ready aller 5 Kinds, Heatmap-Daten, `busy_changed` True/False, keine query_failed |

Zusätzlich: `py_compile` auf Worker, ViewModel und Test (Exit 0); bestehende Tests `check_p15_s3_profiles.py` (30/30) und `check_p15_s3_reader_repo.py` (39/39) weiterhin PASS (reine Additions, keine Bestandsdatei veraendert). Keine UI-/Regressionstests (Regel 4).

### 3.5 Schritt 5 – UI-Pages, `analytics_win.py` & `main.py`-Ersatz

**`analytics/ui/` (NEU, Ordner):**
* `common.py` – gemeinsame UI-Helfer: `format_wanduhr_time(epoch)` (**Wanduhr-Formatierung Invariante 7:** `fromtimestamp(epoch, tz=utc)` ohne Berlin-Offset, DST-robust) und `make_overlay_stack()` („No Data"-Overlay via `QStackedLayout`, Index 0 = Inhalt / 1 = Overlay).
* `table_page.py` – `TablePage`: Feature-Store-Tabelle (Zeit-Wanduhr, Symbol, TF, Feature, Version, ema_diff/rsi_14/atr_normalized), Doppelklick → **Jump-to-Chart** (Variante 2, `open_chart_at_bar`).
* `heatmap_page.py` – `HeatmapPage`: pyqtgraph `ImageItem` (24×7, X: Wochentage, Y: Tagesstunden Berlin Wanduhr) + `ColorBarItem` (viridis), Metrik-Dropdown (count/native Spalten); **Doppelklick auf eine Zelle** → neuester Bar der (dow, hour)-Zelle (Aufloesung über den ViewModel).
* `scatter_page.py` – `ScatterPage`: pyqtgraph `ScatterPlotItem` (X/Y-Dropdowns aus `native_columns`); **Klick auf einen Punkt** → neuester Bar des Symbol/TF.
* `distribution_page.py` – `DistributionPage`: pyqtgraph `BarGraphItem`-Histogramm, Spalten-Dropdown + **bins-Slider (2–100, Debounce über den ViewModel-QTimer 250 ms)**.
* `equity_page.py` – `EquityPage`: Platzhalter mit dauerhaftem „No Data"-Overlay („Equity-Analyse: noch keine Daten vorhanden (geplant für eine spätere Phase)"); Plot-Bereich reserviert, keine Datenabfrage (noch kein query_kind).

**`analytics/ui/analytics_win.py` (NEU):** `AnalyticsWindow` – `PersistentWindow`, `INSTANCE_ID = "win_analytics"`, **1280 × 800**, nicht-modal, `@register_persistent_window()` (Auto-Restore beim App-Start).
* **Top-Bar CRUD (Option B – Explicit Save):** Profil-Combo („– kein Profil –" bei leer), Name-/Beschreibungs-Edit, Buttons `Neu` (QInputDialog), `💾 Save` (update name/desc + `save_profile`), `Löschen` (QMessageBox-Rückfrage); **Dirty-Flag `*`** im Fenstertitel + Status-Label; indeterminierter **Progress-Busy-Bar** (`busy_changed`).
* **Filter-Zeile:** Symbol-Combo (Favoriten + ★-SymbolsWindow, `EventBus.favorites_changed`), Timeframe-Combo (M1…D1), Feature-Combo („Alle" + `feature_ids` aus `QUERY_FEATURES`), **Limit-SpinBox (1…`MAX_LOOKBACK_LIMIT`)**.
* **Sidebar-Navigation:** `QListWidget` (Tabelle/Heatmap/Scatter/Verteilung/Equity) + `QStackedWidget`; Seitenwechsel ruft `request_data()` der aktiven Page.
* **MVVM-Wiring:** `AnalyticsViewModel` (parent=self), `data_ready` → Pages + Feature-Combo, `query_failed` → Log, Jump-to-Chart-Handler/Resolver an die Pages.
* **E-2-Migration:** `migrate_statistics_persistence(state_manager)` kopiert **Fenstergeometrie + Instanz-Zustand** von `win_statistics` nach `win_analytics` (nur wenn `win_analytics` noch leer; Alt-Einträge werden entfernt; idempotent). Hinweis: Die Kapselung in `window_state_repository.py` folgt in 15.04 (E-2); bis dahin nutzt die Migration das StateManager-Interface.
* `closeEvent()` ruft `vm.shutdown()` (Debounce + Worker stoppen).

**`main.py` (Anpassung):** `from statistic_win import StatisticWindow` → `from analytics.ui.analytics_win import AnalyticsWindow`; `open_statistic_window()` → `open_analytics_window()` (Singleton, `AnalyticsWindow.get_existing_instance()`); `btn_statistics`-Button öffnet nun das AnalyticsWindow. `restore_all_windows()` stellt `win_analytics` über die Klassen-Registry wieder her (Alt `win_statistics` wird nicht mehr registriert und per E-2 bereinigt). `statistic_win.py` bleibt als ungenutzte Legacy-Datei liegen (E-1).

### 3.6 Schritt 6 – Headless-Gesamttest

**`test/check_p15_s3_analytics.py` (NEU):** Gesamt-Validierung der Analytics-Engine (KEINE UI, KEIN `QApplication.exec()`; nur `QCoreApplication` + `processEvents()`). Test-DBs in `test/` (`p15_s3_analytics_test.duckdb`, `p15_s3_analytics_app.duckdb`, `p15_s3_migration_test.duckdb`).

**Ergebnis: 40/40 Checks PASS** (Exit 0):

| Bereich | Checks | Inhalt |
| --- | --- | --- |
| A Profiles-CRUD | A1–A10 | create/get/get_by_name/list/update/delete, schema_version-Pflichtfeld + Alt-Row-Default, genau EIN aktives Profil |
| B SQL-Aggregationen | B1–B14 | fetch_rows, Heatmap 24×7 (Wanduhr-Tagesgrenze), Scatter, Verteilung; **NEU:** `get_latest_bar_time`, `get_recent_bar_time_for_cell` (Tagesgrenze Fr 23:00, ungültige Zelle → None, feature_id-Filter) |
| C ViewModel | C1–C7 | create→aktiv, Dirty→Save→Dirty False, Payload mit schema_version, Jump-to-Chart-Resolution (latest/cell) |
| D E-2-Migration | D1–D9 | Geometrie + Instanz-Zustand kopiert, win_statistics entfernt, **Idempotenz** (2. Aufruf → False), kein Overwrite bestehender win_analytics-Geometrie |

Zusätzlich: `py_compile` auf allen neuen UI-Dateien, `analytics_win.py`, `main.py` und dem Test (Exit 0); `import main` erfolgreich (Import-Kette `analytics.ui.analytics_win` inkl. pyqtgraph-Import ohne QApplication); bestehende Tests `check_p15_s3_profiles.py` (30/30), `check_p15_s3_reader_repo.py` (39/39) und `check_p15_s3_worker_vm.py` (49/49) weiterhin PASS (additive Reader-/Repo-/VM-Methoden). **Gesamt 158 gezielte Checks PASS.** Keine UI-/Regressionstests (Regel 4) – UI-Änderungen durch Code-Inspektion + py_compile abgesichert.