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

---

## 3. Implementierungs-Log

### 3.1 Schritt 1 – Backup (Commit `afb2e9c`, Tag `phase15_s1_backup`)

Arbeitsstand vor der 15.01-Umsetzung als Git-Commit gesichert (inkl. Doku-Reorganisation: `docs/AKTUELLE_UMSETZUNG.md` aufgesetzt, Roadmap nach `docs/Old/` archiviert). Tag `phase15_s1_backup` gesetzt.

### 3.2 Schritt 2 – EventBus, DB-Tabelle & SymbolRepository

**`config/event_bus.py` (NEU):** Zentraler `EventBus`-Signal-Hub (Singleton, `QObject`) mit den minimalen Phase-15-Signalen `favorites_changed`, `profile_changed(str)`, `service_set_changed`. Modul-Level-Instanz `event_bus` für `from config.event_bus import event_bus`. Fenster-Entkopplung (Invariante 5) ist damit schwellenfrei nutzbar.

**`db_service.py` (Anpassung):** In `check_and_init_databases()` (Block `con_app`, `app_data.duckdb`) wird die Tabelle `broker_symbols` angelegt (`symbol VARCHAR PRIMARY KEY`, `path VARCHAR`, `is_favorite BOOLEAN DEFAULT FALSE`, `updated_at TIMESTAMP DEFAULT current_timestamp`). Die Standard-Defaults **SILVER / GOLD / BTCUSD** werden als Favoriten vorbelegt (`ON CONFLICT DO NOTHING` – additiv, keine Bestandsdaten-Beschädigung).

**`symbol_repository.py` (NEU):** `SymbolRepository` kapselt den kompletten Lese-/Schreibzugriff (kein SQL in UI):
* `get_symbols()` – alle Symbole (sortiert, inkl. `path`/`is_favorite`/`updated_at`).
* `get_favorite_symbols()` – nur Favoriten.
* `get_symbol(symbol)` – Einzelsymbol (case-insensitive).
* `toggle_favorite(symbol)` – kippt das Flag, liefert den neuen Zustand (unbekanntes Symbol wird als Favorit angelegt).
* `upsert_from_broker(pairs)` – Broker-Upsert (Favoriten-Flags bleiben unangetastet).
* `sync_from_broker()` – MT5-Live-Fetch (`mt5.symbols_get()`, lazy import) mit **automatischem DB-Fallback** bei MT5-Ausfall (`initialize()==False` / Exception).
* `ensure_defaults()` – idempotente Defaults-Vorbelegung.
* `get_symbol_repository()` – app-weite Standard-Instanz (lazy).

DuckDB-Hinweis (Umsetzungs-Erkenntnis): In `ON CONFLICT ... DO UPDATE SET updated_at = ...` wird `CURRENT_TIMESTAMP` als **Spaltenname** geparst; korrekt ist `updated_at = DEFAULT` (nutzt den Spalten-Default) bzw. `now()`.

### 3.3 Schritt 3 – SymbolsWindow (`serviceui/symbols_win.py`)

Nicht-modales `SymbolsWindow` (`PersistentWindow`, `INSTANCE_ID = "win_symbols"`, `@register_persistent_window(auto_restore=False)`):
* Suche (`QLineEdit`) mit Live-Filter und `scrollToItem` zum ersten Treffer (Spalte 0).
* 2-Spalten-Tabelle (`QTableWidget`): Spalte 0 Symbol, Spalte 1 `★`/`☆`-Favoriten-Toggle per Klick.
* Klick in Spalte 1 → `SymbolRepository.toggle_favorite()` + `event_bus.favorites_changed.emit()`.
* ESC schließt das Fenster (Standard-`PersistentWindow`-Verhalten).
* Kein SQL in der UI (SRP/Invariante 4).

### 3.4 Schritt 4 – Integration in ServiceWindow-Dropdowns

`serviceui/service_win.py` (Anpassung):
* **`btn_symbol_fav` (`★`)** wird programmatisch in das `layout_symbol`-Layout rechts neben `combo_symbol` eingefügt (keine `.ui`-Datei-Änderung nötig) und öffnet das `SymbolsWindow` (Singleton-Verhalten via `get_existing_instance()`).
* **Favoriten-Dropdown:** `_refresh_symbol_combo()` befüllt `combo_symbol` nur aus `get_favorite_symbols()` (Fallback auf `DEFAULT_SYMBOLS` bei leerer Favoriten-Liste; aktuelle Auswahl bleibt erhalten).
* **EventBus-Kopplung:** `event_bus.favorites_changed` → `_refresh_symbol_combo()` (beim Start + bei jeder Favoriten-Änderung).

> Hinweis: `AnalyticsWindow` existiert noch nicht (15.03) – der `EventBus` + `SymbolRepository` sind dafür vorbereitet, die Kopplung wird in 15.03 ergänzt.

### 3.5 Schritt 5 – Headless-Validierung (`test/check_p15_s1_symbols.py`)

Test-DB in `test/p15_s1_symbols_test.duckdb` (Regel: keine Test-DBs im Root/`data`), kein `QApplication.exec()`.

**Ergebnis: 30/30 Checks PASS** (Exit 0):

| Bereich | Checks | Inhalt |
| --- | --- | --- |
| A DB-Persistenz & Defaults | A1–A4 | Tabelle angelegt, SILVER/GOLD/BTCUSD als Favoriten, `ensure_defaults()` idempotent |
| B Lese-API | B1–B3 | `get_symbols`/`get_favorite_symbols`/`get_symbol` (case-insensitive) |
| C Favoriten-Toggle | C1–C5 | Toggle liefert neuen Zustand; unbekanntes Symbol wird Favorit |
| D Broker-Upsert | D1–D5 | Neue Symbole + path, Favoriten-Flags unangetastet, keine Duplikate |
| E MT5-Fallback & Status | E1–E5 | offline/Exception/Import-Fehler → DB-Fallback + Fehlermeldung; online → Upsert + Status `"live"` |
| F EventBus | F1–F3 | `favorites_changed`, `profile_changed(payload)`, `service_set_changed` |

Zusätzlich: `py_compile` auf allen neuen/geänderten Dateien (Exit 0) und Import-Smoke-Test (event_bus, symbol_repository, symbols_win, service_win) erfolgreich.

### 3.6 Nachtrag – MT5-Sync beim Öffnen + Log-Meldung (User-Anweisung 04.08.2026)

**Problem:** Beim Öffnen des SymbolsWindow wurde die Symbol-Liste nur aus der DB gelesen (`get_symbols()`); ein Live-Fetch von MT5 fand nie statt. Zusätzlich schluckte `sync_from_broker()` MT5-Fehler still (stiller DB-Fallback ohne Meldung).

**Lösung (additiv):**
* **`symbol_repository.py`:** Neue Methode **`sync_from_broker_with_status()`** liefert `(symbols, status, error)`:
  * `status = "live"` bei erfolgreichem MT5-Fetch, `"fallback"` bei MT5-Ausfall.
  * `error` = konkrete Fehlermeldung (MT5-Import fehlgeschlagen / `initialize()==False` / `symbols_get()`-Fehler oder leer / Upsert-Fehler) bzw. `None` bei Erfolg.
  * `sync_from_broker()` bleibt als dünner Wrapper erhalten (Rückgabe unverändert – keine API-Brechung).
* **`serviceui/symbols_win.py`:** `_load_symbols()` ruft jetzt `sync_from_broker_with_status()` auf → **Live-Fetch bei jedem Öffnen**. Neues **Status-Log** (`QTextEdit`, unten im Fenster):
  * `[OK] N Symbole live von MT5 geladen.` bei Erfolg,
  * `[WARNUNG] MT5 nicht verfügbar – zeige DB-Stand (N Symbole). <Fehlermeldung>` bei MT5-Ausfall (automatischer DB-Fallback wie spezifiziert – aber sichtbar).
* **Test:** `test/check_p15_s1_symbols.py` um E1b (offline → fallback + Meldung), E3c (online → live + None), E4b (Exception → fallback + Meldung) und E5 (Import-Fehler → fallback + Meldung) erweitert (26 → **30 Checks**).
* **Offscreen-Smoke-Test** (Window-Instanziierung, kein `exec()`): SymbolsWindow baut mit Log-Bereich, lädt **632 Symbole live von MT5** und der Favoriten-Toggle emittiert `favorites_changed` – bestätigt den Live-Pfad in der realen Umgebung.

### 3.7 Nachtrag 2 – Favoriten-Button & Favoriten-Dropdown im Chart-Fenster (User-Anweisung 04.08.2026)

**Problem:** Der ★-Favoriten-Button fehlte im `PyTraderChartWindow` (nur ServiceWindow hatte ihn).

**Lösung (additiv, `chart/chart_win.py`):**
* **`btn_symbol_fav` (`★`)** wird programmatisch in `horizontalLayout_row1` direkt rechts neben `combo_symbol` eingefügt (keine `.ui`-Änderung; 28×28 px, gleiche Optik wie die anderen Toolbar-Buttons).
* Klick öffnet das nicht-modale `SymbolsWindow` (Singleton via `get_existing_instance()`, identisch zu ServiceWindow).
* **Favoriten-Dropdown:** `_refresh_symbol_combo()` befüllt `combo_symbol` mit `get_favorite_symbols()` (Fallback auf `DEFAULT_SYMBOLS`). Das **aktuell angezeigte Symbol bleibt immer in der Liste** (auch wenn es kein Favorit mehr ist), damit der Chart beim Favoriten-Wechsel nicht ungewollt auf ein anderes Symbol springt. Signale sind beim Umbau blockiert (kein ungewollter Chart-Refresh).
* **EventBus-Kopplung:** `event_bus.favorites_changed` → `_refresh_symbol_combo()` (beim Start + bei jeder Favoriten-Änderung).
* **Keine zirkulären Importe:** `chart_win` importiert `config.event_bus`, `symbol_repository`, `serviceui.symbols_win` – keines davon importiert `chart_win`.

**Validierung:**
* `py_compile` (Exit 0) + Import-Smoke-Test (`chart_win` + `main` importierbar).
* Offscreen-Smoke-Test (Window-Instanziierung, kein `exec()`): ★-Button vorhanden und rechts neben `combo_symbol` im `horizontalLayout_row1`; Combo zeigt Favoriten zuerst; aktuelles Symbol bleibt nach EventBus-Refresh erhalten; nicht-Favorit-Symbol bleibt in der Liste; `SymbolsWindow` wird geöffnet.
* `test/check_p15_s1_symbols.py` weiterhin 30/30 PASS (unverändert).

### 3.8 Offene Punkte / nächste Schritte

* **15.02:** Service-UI-Refactoring & Master-Tree (nächste Phase).
* **15.03:** `AnalyticsWindow` – dort wird die Favoriten-Dropdown-Kopplung (Punkt 3.4) und der `EventBus`-Empfang ergänzt.
* Der ★-Button in `AnalyticsWindow` folgt ebenfalls in 15.03 (Fenster existiert noch nicht).