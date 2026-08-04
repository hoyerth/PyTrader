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
* 
---

# 15.02 Service-UI Refactoring, Master-Tree & Generischer ServiceSelector

## 1. SPEZIFIKATION (15.02)

* **Modularisierung (`service_win.py` als Orchestrator):** Zerlegung der gewachsenen `service_win.py` (864 Zeilen, E-5) in entkoppelte, wiederverwendbare Sub-Komponenten:
* `serviceui/master_tree.py`: 2-Spalten `QTreeWidget` für die hierarchische Darstellung.
* `serviceui/parameter_panel.py`: Parameter-Formular mit `ContentScrollMixin`.
* `serviceui/toolbar.py`: Aktions-Buttons (`[➕ Service]`, `[▲]`, `[▼]`, `[🗑️ Entfernen]`).
* `serviceui/status_panel.py`: Status- und Log-Anzeigen.
* `serviceui/service_selector_widget.py`: Generisches Auswahl-Widget (wiederverwendbar).
* **Generische Service- & Set-Auswahl (`ServiceSelectorModel` & `ServiceSelectorWidget`):**
* **`ServiceSelectorModel` (`analytics/engine/service_selector_model.py`):** Zentrales, lesendes Datenmodell. Lädt Sets und Services aus `ServiceSetRepository` und `PluginRegistry`. Hört auf `EventBus.service_set_changed` für automatische Live-Aktualisierung in allen Fenstern.
* **`ServiceSelectorWidget` (`serviceui/service_selector_widget.py`):** Konfigurierbares PySide6-Widget mit zwei Betriebsmodi:
* **Modus A (`SELECT_ONLY`):** Kompaktes Popover/Dropdown-Auswahl-Widget für schwellenfreie Wiederverwendung in Analytics (15.03), Backtester oder Charts. Emittiert `selection_changed(set_id, service_id)`.
* **Modus B (`FULL_EDIT`):** Vollständiges Master-Tree-Widget mit Aktions-Toolbar für `service_win.py` (Erstellen, Umsortieren, Löschen).
* **2-Spalten-MasterTree Visualisierung (Modus B):**
* *Spalte 0:* Hierarchische Knoten (📁 Service-Sets, ⚡ Standalone Services, 📦 Alle verfügbaren Plugins).
* *Spalte 1:* Kompakte Status-Badges (`📌 Indikator: <Name> | 🟢 Aktiv in Chart` oder `⚪ Inaktiv in Chart`).
* **Deterministische Bedienung ("Tree + Buttons"):**
* Klick auf `[➕ Service hinzufügen]` $\rightarrow$ Popup-Auswahl des Plugins $\rightarrow$ Hinzufügen ins aktive Set via `ServiceSetRepository.save_set()`.
* Buttons `[▲]` / `[▼]` ändern die `execution_order` im Set.
* Button `[🗑️]` führt P14-04 Sperr-Prüfung durch (Warnung bei aktiven Indikatoren).

---

## 2. SCHRITT-FÜR-SCHRITT ANLEITUNG (15.02)

1. **Backup:** Git Commit `phase15_s2_backup`.

2. **Generisches Datenmodell & Selector-Widget erstellen:**
* `analytics/engine/service_selector_model.py`: Aufbereitung der Hierarchie & Live-Status-Badging aus `ServiceSetRepository` und `StateManager`.
* `serviceui/service_selector_widget.py`: Erstellung des wiederverwendbaren Widgets mit Modus-Umschaltung (`SELECT_ONLY` vs. `FULL_EDIT`).

3. **Sub-Widgets für `service_win.py` erstellen:**
* `serviceui/master_tree.py` (nutzt `ServiceSelectorWidget` im Modus `FULL_EDIT`).
* `serviceui/parameter_panel.py`, `serviceui/toolbar.py`, `serviceui/status_panel.py` erstellen.

4. **`service_win.py` Refactoring:**
* Fenstergröße auf `1280 x 800` anpassen.
* Umbau auf `QSplitter` mit Zusammensetzung der Sub-Widgets als schlanker Orchestrator.

5. **Action-Handler & EventBus-Sync:**
* Aktions-Buttons in `toolbar.py` mit `ServiceSetRepository` koppeln.
* Bei jeder Struktur- oder Parameter-Änderung `EventBus.service_set_changed` emittieren, um alle lauschenden `ServiceSelectorModel`-Instanzen projektweit automatisch zu aktualisieren.

6. **Headless-Test (`test/check_p15_s2_service_tree.py`):**
* Prüft `ServiceSelectorModel` im Modus `SELECT_ONLY` und `FULL_EDIT` ohne GUI.
* Prüft Indikator-Status-Badges, Set-Updates, Umsortieren & EventBus-Reaktivität.

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

# 15.03-E Ergänzungskapitel: Generische Service-/Set-Auswahl (SELECT_ONLY) in Analytics

## 1. SPEZIFIKATION (15.03-E)

* **Integration `ServiceSelectorWidget` (Modus `SELECT_ONLY`):**
* Einbindung des in 15.02 erstellten `ServiceSelectorWidget` im lesenden Modus (`SELECT_ONLY`) direkt in die Top-Bar von `AnalyticsWindow` (`analytics/ui/analytics_win.py`).

* Bietet ein kompaktes Dropdown/Popover zur Selektion des aktiven **Service-Sets** oder **Einzel-Services**.

* *Top-Bar Layout:* `[ Profile: ▾ Profile_Name ]` `|` `[ Set/Service: ▾ Scalper_Grid_v1 ]` `|` `Symbol: [ SILVER ▾ ] [★]` `TF: [ M1 ▾ ]` `[ Refresh 🔄 ]`.

* **Datenfluss & SQL-Filterung:**
* Das Signal `selection_changed(set_id, service_id)` des Widgets wird an das `AnalyticsViewModel` gekoppelt.

* `FeatureStoreReader` und `AnalyticsRepository` nutzen die ausgewählte `set_id` / `service_id` als obligatorischen Filter in den SQL-Queries (`WHERE set_id = ?` bzw. `WHERE service_id = ?`) für alle Unterseiten (`table_page`, `heatmap_page`, `scatter_page`, `distribution_page`).

* **EventBus-Reaktivität:**
* Das im `ServiceSelectorWidget` hinterlegte `ServiceSelectorModel` reagiert automatisch auf `EventBus.service_set_changed`.
* Wird im `ServiceWindow` ein Set erstellt, geändert oder gelöscht, aktualisiert sich das Auswahl-Dropdown im Analytics-Fenster ohne Neustart im laufenden Betrieb.

---

## 2. SCHRITT-FÜR-SCHRITT ANLEITUNG (15.03-E)

1. **Top-Bar Erweiterung in `analytics/ui/analytics_win.py`:**
* Instanziierung von `ServiceSelectorWidget(mode=SelectorMode.SELECT_ONLY)`.
* Plazierung in der oberen `QHBoxLayout`-Aktionsleiste zwischen Profil-Aktionen und Symbol-Auswahl.

2. **Kopplung an `AnalyticsViewModel` & `FeatureStoreReader`:**
* Verbinden des Signals `selection_changed` mit `AnalyticsViewModel.set_active_service_filter(set_id, service_id)`.
* Anpassung der Abfragemethoden in `analytics/engine/feature_store_reader.py` (`get_heatmap_data`, `get_scatter_data`, `get_distribution_data`, `get_table_data`), sodass der `set_id`/`service_id`-Filter an die DuckDB-SQL-Queries übergeben wird.

3. **Profil-Synchronisation:**
* Beim Laden oder Speichern eines Analytics-Profils via `analytics_profile_repository.py` wird das aktuell gewählte Set (`"service_sets": [...]`) automatisch im `ServiceSelectorWidget` selektiert bzw. ausgelesen.

4. **Headless-Test Erweiterung (`test/check_p15_s3_analytics.py`):**
* Verifizierung, dass `FeatureStoreReader` bei Angabe einer `set_id` ausschließlich korrespondierende Eintragsdaten aus `feature_store` zurückliefert.
* Verifizierung der Signalverarbeitung von `selection_changed` im `AnalyticsViewModel` ohne GUI-Ausführung.

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

- default symbols entfernen - Vorgabe Favoriten sind SILVER, GOLD

1. **Exporte:** Export von gefilterten Daten und Matrizen als CSV, Excel oder PNG/SVG-Grafik.
2. **Multi-Symbol und Multi-Timeframe:** Gezielter Vergleich mehrerer Symbole/Timeframes nebeneinander in einer Matrix oder Kurve.
3. **Massentests & Parameter-Optimierung:** Automatische Parameter-Sweeps über verschiedene Zeiträume, Service-Parameter und ML-Variablen.
4. **Aktive ML-Inferenz:** In Phase 15 wird ML noch nicht aktiv eingebunden; die bestehenden Profil-Strukturen (`"ml_models"` im JSON-Payload) bleiben rein vorbereitend vorhanden.
5. **Legacy-Ersatz `../../analytics/statistics_repository.py`:** Der Legacy-Alias (E-1) wird in einer späteren Phase vollständig durch `FeatureStoreReader`/`AnalyticsRepository` ersetzt.
6. **VectorBT: ** Einsatz prüfen für Massentests und Matrix-Analysen - Als Engine im analytics_worker.py für blitzschnelle N-Bar Outcomes, Heatmaps & Indikator-Sweeps.