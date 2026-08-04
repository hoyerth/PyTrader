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

# 15.01 Symbol-Auswahl und Favoriten

## 1. SPEZIFIKATION (15.01)

* **Broker-Fetch & Persistenz:** Liest Symbole live via `mt5.symbols_get()` und speichert sie per Upsert in `app_data.duckdb` (Tabelle `broker_symbols` mit Spalten `symbol`, `path`, `is_favorite`, `updated_at`). Bei MT5-Ausfall erfolgt ein automatischer Fallback auf die DB-Tabelle.
* **Symbol-Repository (`symbol_repository.py`):** Kapselt den Lese-/Schreibzugriff für Symbole und Favoriten entkoppelt aus `../../state_manager.py`.
* **Favoriten-Dropdowns:** Dropdowns in `ServiceWindow` und `AnalyticsWindow` zeigen nur `is_favorite == True` Symbole an.
* **Auswahlfenster `SymbolsWindow` (`serviceui/symbols_win.py`):** Erbt von `PersistentWindow` (`win_symbols`), nicht-modal.
* *Search-LineEdit:* Live-Filter mit `scrollToItem` zum ersten Treffer.
* *2-Spalten-Table:* Spalte 0: Symbol, Spalte 1: `★` (Favoriten-Toggle per Klick).
* *EventBus:* Emittiert bei Änderung `EventBus.favorites_changed`.


## 2. SCHRITT-FÜR-SCHRITT ANLEITUNG (15.01)

1. **Backup:** Git Commit `phase15_s1_backup`.
2. **Repository & DB (`../../db_service.py` & `symbol_repository.py`):**
* Tabelle `broker_symbols` in `../../db_service.py` anlegen (Standard-Defaults: SILVER, GOLD, BTCUSD).
* `symbol_repository.py` erstellen: Implementierung von `get_symbols()`, `get_favorite_symbols()`, `toggle_favorite()`.

3. **UI `SymbolsWindow` (`serviceui/symbols_win.py`):**
* Erstellen als `PersistentWindow` mit Suche, 2-Spalten-Tabelle & ESC-Handler.
* Klick in Spalte 1 ruft `SymbolRepository.toggle_favorite()` auf und triggert `EventBus.favorites_changed`.

4. **Integration in UI-Dropdowns:**
* Button `btn_symbol_fav` (`★`) neben Symbol-ComboBox in `ServiceWindow` und `AnalyticsWindow` einbauen.
* `EventBus.favorites_changed` an Neu-Befüllung der ComboBoxen koppeln.


5. **Headless-Test (`test/check_p15_s1_symbols.py`):** Validierung von DB-Persistenz, Fallback & Favoriten-Toggle ohne GUI.