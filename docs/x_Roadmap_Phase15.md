# Phase 15: Service UI, Symbol-Verwaltung & Analytics Engine

## 1. Übersicht & Zielsetzung

Ziel von **Phase 15** ist die Weiterentwicklung der Service-UI (`service_win.py`), die Bereitstellung einer zentralen Symbol- und Favoritenverwaltung, der systematische Abbau von Alt-Pfaden sowie der Aufbau einer hochperformanten, entkoppelten Analytics-Engine auf Basis der Plugin- und Service-Architektur (Phasen 12–14).

* **15.01 Symbol-Auswahl & Favoriten:** Broker-Fetch via MT5, Persistierung in `app_data.duckdb`, Favoriten-Dropdowns & nicht-modales `SymbolsWindow`.
* **15.02 Service-UI Refactoring & Master-Tree:** Modularisierung der gewachsenen `service_win.py` in Orchestrator + Sub-Widgets (`MasterTree`, `ParameterPanel`, `Toolbar`), Einführung von `ServiceTreeModel`, 2-Spalten-TreeWidget mit Indikator-Live-Status (`📌` / `🟢`) & Buttons für Struktur-Aktionen.
* **15.03 Analytics Engine & UI:** Ersetzung von `statistic_win.py` durch `AnalyticsWindow` (`analytics/ui/analytics_win.py`), Entkopplung via MVVM (`AnalyticsViewModel`, `AnalyticsRepository`, `FeatureStoreReader`), `pyqtgraph`-Visualisierungen (Tabelle, Heatmap, Scatter, Verteilung), Profil-CRUD mit Explicit Save (`*`) & `schema_version` im Profil-JSON, Entkopplung über einen zentralen `EventBus`.

---

## 2. Allgemeine Grundsätze & Architektur-Invarianten

2. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase15_step1`, `phase15_step2` usw.).
3. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte in `test`.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
5. **Zentraler `EventBus`:** Fenster kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`db_service.py`).
7. **Wanduhr-Garantie:** Achsen und Zeitfilter formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.

### Entscheidungs-Protokoll Phase 15 (Beschluss 04.08.2026)

| # | Thema | Entscheidung |
| --- | --- | --- |
| E-1 | Legacy-Alias `analytics/statistics_repository.py` | Bleibt bis auf Weiteres unverändert bestehen; kompletter Ersatz erst in einer späteren Phase |
| E-2 | Persistenz `win_statistics` | Fenstergeometrie & Instanz-Zustände werden beim Ersetzen nach `win_analytics` migriert |
| E-3 | `schema_version` Pflichtfeld | Pflichtfeld im `FeatureStorePayload`; alte `feature_store`-Rows erhalten beim Lesen den Default `"1.0"` |
| E-4 | Schutzregel Grid-Liquidity | Schutz für `chart/indicators/grid_liquidity.py` aufgehoben; Anpassungen erlaubt, wenn der Fallback-Abbau sie erfordert |
| E-5 | Zeilenzahl `service_win.py` | Doku-Korrektur: 864 Zeilen (statt 1.400) |
| E-6 | Pfad-Konvention | Dateien werden einheitlich vom Projekt-Root referenziert (ohne `../`) |

---

# 15.01 Symbol-Auswahl und Favoriten

## 1. SPEZIFIKATION (15.01)

* **Broker-Fetch & Persistenz:** Liest Symbole live via `mt5.symbols_get()` und speichert sie per Upsert in `app_data.duckdb` (Tabelle `broker_symbols` mit Spalten `symbol`, `path`, `is_favorite`, `updated_at`). Bei MT5-Ausfall erfolgt ein automatischer Fallback auf die DB-Tabelle.
* **Symbol-Repository (`symbol_repository.py`):** Kapselt den Lese-/Schreibzugriff für Symbole und Favoriten entkoppelt aus `state_manager.py`.
* **Favoriten-Dropdowns:** Dropdowns in `ServiceWindow` und `AnalyticsWindow` zeigen nur `is_favorite == True` Symbole an.
* **Auswahlfenster `SymbolsWindow` (`serviceui/symbols_win.py`):** Erbt von `PersistentWindow` (`win_symbols`), nicht-modal.
* *Search-LineEdit:* Live-Filter mit `scrollToItem` zum ersten Treffer.
* *2-Spalten-Table:* Spalte 0: Symbol, Spalte 1: `★` (Favoriten-Toggle per Klick).
* *EventBus:* Emittiert bei Änderung `EventBus.favorites_changed`.


## 2. SCHRITT-FÜR-SCHRITT ANLEITUNG (15.01)

1. **Backup:** Git Commit `phase15_s1_backup`.
2. **Repository & DB (`db_service.py` & `symbol_repository.py`):**
* Tabelle `broker_symbols` in `db_service.py` anlegen (Standard-Defaults: SILVER, GOLD, BTCUSD).
* `symbol_repository.py` erstellen: Implementierung von `get_symbols()`, `get_favorite_symbols()`, `toggle_favorite()`.

3. **UI `SymbolsWindow` (`serviceui/symbols_win.py`):**
* Erstellen als `PersistentWindow` mit Suche, 2-Spalten-Tabelle & ESC-Handler.
* Klick in Spalte 1 ruft `SymbolRepository.toggle_favorite()` auf und triggert `EventBus.favorites_changed`.

4. **Integration in UI-Dropdowns:**
* Button `btn_symbol_fav` (`★`) neben Symbol-ComboBox in `ServiceWindow` und `AnalyticsWindow` einbauen.
* `EventBus.favorites_changed` an Neu-Befüllung der ComboBoxen koppeln.


5. **Headless-Test (`test/check_p15_s1_symbols.py`):** Validierung von DB-Persistenz, Fallback & Favoriten-Toggle ohne GUI.

---

# 15.02 Service-UI Refactoring & Master-Tree

## 1. SPEZIFIKATION (15.02)

* **Modularisierung (`service_win.py` als Orchestrator):** Zerlegung von `service_win.py` (864 Zeilen, E-5) in dedizierte Sub-Komponenten:
* `serviceui/master_tree.py`: 2-Spalten `QTreeWidget`.
* `serviceui/parameter_panel.py`: Parameter-Formular mit `ContentScrollMixin`.
* `serviceui/toolbar.py`: Aktions-Buttons (`[➕ Service]`, `[▲]`, `[▼]`, `[🗑️ Entfernen]`).
* `serviceui/status_panel.py`: Status- und Log-Anzeigen.
* **Tree-Architektur (`ServiceTreeModel`):** Entkoppeltes Datenmodell zwischen `ServiceSetRepository` und `MasterTree`.

* **2-Spalten-MasterTree Visualisierung:**
* *Spalte 0:* Hierarchische Knoten (📁 Service-Sets, ⚡ Standalone Services, 📦 Alle verfügbaren Plugins).
* *Spalte 1:* Kompakte Status-Badges (`📌 Indikator: <Name> | 🟢 Aktiv in Chart` oder `⚪ Inaktiv in Chart`).
* **Deterministische Bedienung ("Tree + Buttons"):**
* Klick auf `[➕ Service hinzufügen]` $\rightarrow$ Popup-Auswahl $\rightarrow$ Hinzufügen ins aktive Set via `ServiceSetRepository.save_set()`.
* Buttons `[▲]` / `[▼]` ändern `execution_order`.
* Button `[🗑️]` führt P14-04 Sperr-Prüfung durch.


## 2. SCHRITT-FÜR-SCHRITT ANLEITUNG (15.02)

1. **Backup:** Git Commit `phase15_s2_backup`.
2. **TreeModel & Sub-Widgets erstellen:**
* `serviceui/service_tree_model.py`: Aufbereitung der Hierarchie & Live-Status-Badging.
* `serviceui/master_tree.py`, `parameter_panel.py`, `toolbar.py`, `status_panel.py` erstellen.

3. **`service_win.py` Refactoring:**
* Fenstergröße auf `1280 x 800` anpassen.
* Umbau auf `QSplitter` mit Zusammensetzung der Sub-Widgets als schlanker Orchestrator.

4. **Action-Handler & Repository-Sync:**
* Buttons in `toolbar.py` koppeln mit `ServiceSetRepository` und `ServiceTreeModel`.
* Bei Set-Änderung `EventBus.service_set_changed` emittieren.

5. **Headless-Test (`test/check_p15_s2_service_tree.py`):** Testen von Tree-Model, Status-Badges & Set-Updates ohne GUI.

---

# 15.03 Analytics Engine & UI

## 1. SPEZIFIKATION (15.03)

* **Ersetzung `statistic_win.py`:** Vollständiger Austausch durch `AnalyticsWindow` (`analytics/ui/analytics_win.py`).
* **Persistenz-Migration (E-2):** Beim Ersetzen werden Fenstergeometrie & Instanz-Zustände von `win_statistics` nach `win_analytics` migriert (über `window_state_repository.py`, siehe 15.04).
* **Legacy-Alias (E-1):** Das bestehende `analytics/statistics_repository.py` (aktuell von `statistic_win.py` genutzt) bleibt vorerst unverändert bestehen; ein kompletter Ersatz durch `FeatureStoreReader`/`AnalyticsRepository` ist erst in einer späteren Phase vorgesehen.
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


* Alt-Fenster `statistic_win.py` in `main.py` durch `AnalyticsWindow` ersetzen.


* Bestehende `win_statistics`-Persistenz migrieren (E-2): Fenstergeometrie & Instanz-Zustände nach `win_analytics` übernehmen (via `window_state_repository.py`).




6. **Headless-Test (`test/check_p15_s3_analytics.py`):** Validierung von Profiles-CRUD, SQL-Aggregationen, Reader & ViewModel ohne GUI.



---

# 15.04 Infrastructure & EventBus

## 1. SPEZIFIKATION (15.04)

* **`event_bus.py`:** Erstellen eines zentralen Signal-Hubs als Singleton im Core-Paket.


* **Repositories Spaltung (`state_manager.py` Cleanup):**
* `analytics_profile_repository.py`: Profil-Persistenz.


* `symbol_repository.py`: Symbole & Favoriten.


* `window_state_repository.py`: Fenstergeometrien & Instanz-Zustände.




* **Legacy-Abbau & Schema-Invarianten:**
* `schema_version` als Pflichtfeld im `FeatureStorePayload`-TypedDict.


* Entfernen verbliebener Pipeline-Fallbacks in `grid_liquidity.calculate()` zugunsten des reinen `feature_store`-Lesepfads.





## 2. SCHRITT-FÜR-SCHRITT ANLEITUNG (15.04)

1. **Backup:** Git Commit `phase15_s4_backup`.
2. **`EventBus` bereitstellen (`config/event_bus.py`):**
* Signale definieren: `favorites_changed`, `profile_changed`, `service_set_changed`.


* Fenster-Verdrahtungen sukzessive auf den `EventBus` umstellen.




3. **Repositories auskoppeln:**
* `window_state_repository.py` aus `state_manager.py` herauslösen.


* `state_manager.py` als dünne Fassade für Abwärtskompatibilität beibehalten.




4. **Schema & Fallback Cleanup:**
* Strikten `schema_version`-Stempel erzwingen (E-3: Pflichtfeld; Alt-Rows ohne Stempel erhalten beim Lesen Default `"1.0"`).


* Fallback-Code in `grid_liquidity.py` bereinigen (E-4: Schutzregel aufgehoben, Anpassungen erlaubt wenn erforderlich).




5. **Headless-Test (`test/check_p15_s4_infra.py`):** Verifizierung von EventBus, Repositories und Schema-Stempeln ohne GUI.



---

## 3. DATEI-ÄNDERUNGSÜBERSICHT (PHASE 15 GESAMT)

| Datei | Status | Beschreibung |
| --- | --- | --- |
| `config/event_bus.py` | **NEU** | Zentraler Signal-Hub zur schwellenfreien Fenster-Entkopplung

 |
| `symbol_repository.py` | **NEU** | Ausgekoppeltes Repository für Broker-Symbole & Favoriten

 |
| `analytics_profile_repository.py` | **NEU** | Ausgekoppeltes Repository für Analytics-Profile CRUD

 |
| `window_state_repository.py` | **NEU** | Ausgekoppeltes Repository für Fenstergeometrien & Instanz-States

 |
| `serviceui/symbols_win.py` | **NEU** | Nicht-modales `SymbolsWindow` mit Suche & Favoriten-Toggle

 |
| `serviceui/service_win.py` | **Refactoring** | Schlanker Orchestrator mit `QSplitter` (1280x800)

 |
| `serviceui/master_tree.py` | **NEU** | 2-Spalten `QTreeWidget` mit Indikator-Live-Status (`📌` / `🟢`)

 |
| `serviceui/parameter_panel.py` | **NEU** | Inhaltsformular für Parameter mit `ContentScrollMixin`<br> |
| `serviceui/toolbar.py` | **NEU** | Aktions-Buttons für Struktur-Änderungen

 |
| `serviceui/status_panel.py` | **NEU** | Status- und Log-Komponente

 |
| `serviceui/service_tree_model.py` | **NEU** | Entkoppeltes Tree-Model zwischen Repository und UI

 |
| `analytics/engine/feature_store_reader.py` | **NEU** | Reines Lese-Interface für DuckDB `feature_store`<br> |
| `analytics/engine/analytics_repository.py` | **NEU** | High-Level Analytics-Datenmethoden (kein SQL in UI)

 |
| `analytics/engine/analytics_worker.py` | **NEU** | Async QThread-Worker für DuckDB SQL-Aggregationen

 |
| `analytics/engine/analytics_view_model.py` | **NEU** | ViewModel für State-, Profile- & Debounce-Verwaltung

 |
| `analytics/ui/analytics_win.py` | **NEU** | Hauptfenster für Analytics (Top-Bar CRUD, Splitter, Master-Stacked)

 |
| `analytics/ui/table_page.py` | **NEU** | Detail-Signal-Tabelle mit Jump-to-Chart

 |
| `analytics/ui/heatmap_page.py` | **NEU** | 2D-Session & Day Matrix Plot Widget

 |
| `analytics/ui/scatter_page.py` | **NEU** | Feature-Korrelations-Diagramm Widget

 |
| `analytics/ui/distribution_page.py` | **NEU** | Histogramm- & Verteilungs-Widget

 |
| `analytics/ui/equity_page.py` | **NEU** | Vorbereiteter Container für spätere Performance-Kurven

 |
| `main.py` | **Anpassung** | Ersetzung von `StatisticWindow` durch `AnalyticsWindow`<br> |
| `statistic_win.py` | **Entfernt** | Altes Statistik-Fenster wird vollständig durch `AnalyticsWindow` ersetzt

 |
| `analytics/statistics_repository.py` | **bleibt (Legacy-Alias)** | Bleibt bis auf Weiteres unverändert (E-1); Ersatz durch `FeatureStoreReader`/`AnalyticsRepository` erst in späterer Phase

 |
| `test/check_p15_s1_symbols.py` | **NEU** | Headless-Test für Symbol-Fetch, DB-Persistenz & Favoriten

 |
| `test/check_p15_s2_service_tree.py` | **NEU** | Headless-Test für TreeModel, Indikator-Status & Struct-Actions

 |
| `test/check_p15_s3_analytics.py` | **NEU** | Headless-Test für Profiles-CRUD, SQL-Queries & ViewModel

 |
| `test/check_p15_s4_infra.py` | **NEU** | Headless-Test für EventBus, Repositories & Schema-Cleanup

 |

---

## 4. NACHGELAGERTE ARBEITEN (ERST SPÄTER IMPLEMENTIERT)

Folgende Themen sind bewusst **nicht Bestandteil von Phase 15** und werden gesammelt in späteren Phasen umgesetzt:

1. **Exporte:** Export von gefilterten Daten und Matrizen als CSV, Excel oder PNG/SVG-Grafik.
2. **Multi-Symbol und Multi-Timeframe:** Gezielter Vergleich mehrerer Symbole/Timeframes nebeneinander in einer Matrix oder Kurve.
3. **Massentests & Parameter-Optimierung:** Automatische Parameter-Sweeps über verschiedene Zeiträume, Service-Parameter und ML-Variablen.
4. **Aktive ML-Inferenz:** In Phase 15 wird ML noch nicht aktiv eingebunden; die bestehenden Profil-Strukturen (`"ml_models"` im JSON-Payload) bleiben rein vorbereitend vorhanden.
5. **Legacy-Ersatz `analytics/statistics_repository.py`:** Der Legacy-Alias (E-1) wird in einer späteren Phase vollständig durch `FeatureStoreReader`/`AnalyticsRepository` ersetzt.