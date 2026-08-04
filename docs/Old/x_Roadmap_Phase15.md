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

### 3.8 Nachtrag 3 – MT5-Symbol-Fetch nur beim App-Start + Pipeline-Fallback entfernt (User-Anweisung 04.08.2026)

**Zwei User-Anweisungen (04.08.2026):**

**(a) „laden aller Symbole nur bei app start, es gibt sonst verzögerungen"** – der MT5-Live-Fetch wurde aus dem `SymbolsWindow` entfernt:
* **`serviceui/symbols_win.py`:** `_load_symbols()` liest jetzt **ausschließlich die gespeicherte Liste** (`SymbolRepository.get_symbols()`, DB). Der bisherige Aufruf von `sync_from_broker_with_status()` (Live-Fetch bei jedem Öffnen, 15.01-Nachtrag) ist entfernt. Das Status-Log (`log_text`/`_log`) – das nur für die MT5-Sync-Meldungen existierte – wurde mit entfernt (leeres Log hätte keine Funktion mehr). Kein MT5-Zugriff beim Öffnen → keine Verzögerungen.
* **`main.py`:** Der MT5-Symbol-Fetch wird jetzt **einmalig beim App-Start** ausgeführt (direkt nach `check_mt5_connection()`, MT5 ist dort bereits initialisiert → schnell): `get_symbol_repository().sync_from_broker_with_status()` mit Konsolen-Log `[Symbol-Sync]` (live/fallback + Fehlermeldung).
* **`symbol_repository.py`:** Docstrings aktualisiert (`sync_from_broker_with_status()` ist jetzt der App-Start-Sync, nicht mehr das Fenster-Öffnen). Die Methode selbst bleibt unverändert.

**(b) „Fallback ausbauen, es gibt dafür keinen grund mehr"** – der Pipeline-Fallback im `GridLiquidityIndicator` wurde entfernt:
* **`chart/indicators/grid_liquidity.py` (`calculate()`):** Der `else`-Zweig (Definierter Fallback U15-A2: Circles aus der synchron ausgeführten Service-Pipeline bei leerem `feature_store` inkl. Warnung `⚠️ ... Pipeline-Fallback`) ist **entfernt**. Die Circles kommen jetzt **ausschließlich** aus `read_proximity_from_feature_store()` (Farb-Semantik additiv aus dem Indikator-Schema bleibt). **Bei leerem Store → `circles = []`** (kein Rendern, kein Warn-Print).
* **Linien-Pipeline bleibt erhalten:** Die Grid-LINIEN (Live-Tick-Cache) kommen weiterhin immer aus der Pipeline (`GridLinesService`) – sie sind kein DB-Output und waren nie Teil des entfernten Fallbacks. `status_info` kommt weiterhin aus dem Proximity-`chart_render_payload` der (für die Linien ohnehin laufenden) Pipeline.
* Docstrings (`calculate()`, `read_proximity_from_feature_store`) auf den neuen Zustand (U15-A3) aktualisiert.

**Validierung:** `py_compile` auf allen geänderten Dateien (Exit 0), `test/check_p15_s1_symbols.py` weiterhin **30/30 PASS** (Repository-API unverändert – der Test prüft Logik/DB, nicht das Fenster), Import-Smoke-Test (`main`, `symbols_win`, `grid_liquidity` importierbar). Keine UI-/Regressionstests (Regel 4).

### 3.9 Nachtrag 4 – ★-Favoriten-Button & Favoriten-Dropdown im Statistik-Fenster (User-Notiz 04.08.2026)

**Problem (handschriftliche User-Notiz in der Roadmap):** „auch hier in der Kopzeile die Symbolauswahl mit Favoriten-Button einbauen" – nach Chart-Fenster (3.7) und Service-Fenster (3.4) fehlte der ★-Favoriten-Button im `StatisticWindow` (`statistic_win.py`, `win_statistics`).

**Lösung (additiv, `statistic_win.py`):**
* **`btn_symbol_fav` (`★`)** wird programmatisch in `horizontalLayout_filter` (Kopfzeile) direkt rechts neben `combo_symbol_filter` eingefügt (keine `.ui`-Änderung; 28×28 px, gleiche Optik wie Chart/Service).
* Klick öffnet das nicht-modale `SymbolsWindow` (Singleton via `get_existing_instance()`, identisch zu Chart/Service).
* **Favoriten-Dropdown:** `_refresh_symbol_combo()` befüllt `combo_symbol` mit **`ALLE` + Favoriten** (`get_favorite_symbols()`, Fallback auf `DEFAULT_SYMBOLS`). `ALLE` bleibt erster Eintrag (Standard-/Default-Filter der Statistik, `get_summary("ALLE")`). Die **aktuelle Auswahl bleibt in der Liste** (auch wenn sie kein Favorit mehr ist), damit der Filter nicht ungewollt umspringt. Signale sind beim Umbau blockiert (kein Refresh-Explosion durch `_on_filter_changed`).
* **EventBus-Kopplung:** `event_bus.favorites_changed` → `_refresh_symbol_combo()` (beim Start + bei jeder Favoriten-Änderung).
* **Keine zirkulären Importe:** `statistic_win` importiert `config.event_bus`, `symbol_repository`, `serviceui.symbols_win` – keines davon importiert `statistic_win`.

**Validierung:** `py_compile` (Exit 0) + Import-Smoke-Test (`statistic_win`, `main` importierbar). Keine UI-/Regressionstests (Regel 4).

### 3.10 Offene Punkte / nächste Schritte

* **15.02:** Service-UI-Refactoring & Master-Tree (nächste Phase).
* **15.03:** `AnalyticsWindow` – dort wird die Favoriten-Dropdown-Kopplung (Punkt 3.4) und der `EventBus`-Empfang ergänzt.
* Der ★-Button in `AnalyticsWindow` folgt ebenfalls in 15.03 (Fenster existiert noch nicht).

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

# 15.04 Infrastructure & EventBus

## 1. SPEZIFIKATION (15.04)

* **`event_bus.py`:** Erstellen eines zentralen Signal-Hubs als Singleton im Core-Paket.
* **Repositories Spaltung (`../../state_manager.py` Cleanup):**
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
* `window_state_repository.py` aus `../../state_manager.py` herauslösen.
* `../../state_manager.py` als dünne Fassade für Abwärtskompatibilität beibehalten.

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
| `../../serviceui/service_win.py` | **Refactoring** | Schlanker Orchestrator mit `QSplitter` (1280x800)

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
| `../../main.py` | **Anpassung** | Ersetzung von `StatisticWindow` durch `AnalyticsWindow`<br> |
| `../../statistic_win.py` | **Entfernt** | Altes Statistik-Fenster wird vollständig durch `AnalyticsWindow` ersetzt

 |
| `../../analytics/statistics_repository.py` | **bleibt (Legacy-Alias)** | Bleibt bis auf Weiteres unverändert (E-1); Ersatz durch `FeatureStoreReader`/`AnalyticsRepository` erst in späterer Phase

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
5. **Legacy-Ersatz `../../analytics/statistics_repository.py`:** Der Legacy-Alias (E-1) wird in einer späteren Phase vollständig durch `FeatureStoreReader`/`AnalyticsRepository` ersetzt.