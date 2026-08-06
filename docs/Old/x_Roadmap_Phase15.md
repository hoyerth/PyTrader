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

## 3. Implementierungs-Log

### 3.1 Schritt 1 – Backup (Commit `0aaba70`, Tag `phase15_s2_backup`)

Die vom Anwender neu aufgesetzte `docs/AKTUELLE_UMSETZUNG.md` (15.02-Spezifikation, alte 15.03-Inhalte nach `docs/Old/x_Roadmap_Phase15.md` archiviert) wurde als Arbeitsstand gesichert. Tag `phase15_s2_backup` gesetzt.

### 3.2 Schritt 2 – ServiceSelectorModel & ServiceSelectorWidget

**`analytics/engine/service_selector_model.py` (NEU):** Zentrales, lesendes Datenmodell (`ServiceSelectorModel`, QObject mit `data_changed`-Signal):
* Quellen: `ServiceSetRepository.list_sets()`, `PluginRegistry`, `StateManager.load_all_instances()` (Live-Status „aktiv im Chart" via `indicators_state[*]['active']`).
* `build_tree()` liefert die deterministische 3-Gruppen-Hierarchie (📁 Service-Sets / ⚡ Standalone Services / 📦 Alle verfügbaren Plugins) inkl. Status-Badges.
* `badge_for(plugin_id)`: `📌 Indikator: <Name>` (capabilities.chart) + `🟢 Aktiv in Chart` / `⚪ Inaktiv in Chart`.
* Hört auf `EventBus.service_set_changed` → `refresh()` (Live-Sync in allen Fenstern, Invariante 5).
* Reines Lesemodell – kein SQL, kein Schreiben (Invariante 4).

**`serviceui/service_selector_widget.py` (NEU):** `ServiceSelectorWidget` mit Modus-Umschaltung:
* Modus A (`SELECT_ONLY`): kompakte Set-/Service-Combos, emittiert `selection_changed(set_id, service_id)`.
* Modus B (`FULL_EDIT`): MasterTree + ServiceToolbar (2-Spalten-Hierarchie + Aktions-Buttons).

### 3.3 Schritt 3 – Sub-Widgets

* **`serviceui/master_tree.py` (NEU):** `MasterTree` – 2-Spalten-`QTreeWidget` (Spalte 0: Hierarchie, Spalte 1: Status-Badges), befüllt aus dem Modell, `selection_changed(set_id, service_id)`, `current_selection()`/`current_set_id()`/`current_service_id()`, Auswahl-Restore nach Refresh.
* **`serviceui/toolbar.py` (NEU):** `ServiceToolbar` – `[➕ Service]` (Popup-Plugin-Auswahl → `add_service_requested(plugin_id)`), `[▲]/[▼]`, `[🗑️ Entfernen]`, `[🔄 Plugins]`. Reine Signal-Emitter (SRP, kein SQL).
* **`serviceui/status_panel.py` (NEU):** `StatusPanel` – Laufzeit/Fortschritt/Log (Auto-Scroll), reines Anzeige-Widget.
* **`serviceui/parameter_panel.py` (NEU):** `ParameterPanel` – scrollbares Parameter-Formular (`ContentScrollMixin` + Wiederverwendung der Control-Builder aus `ServiceParamColumnsMixin`), `set_service(instance_id, plugin_id, config)`, `params_changed(instance_id, params)`.

### 3.4 Schritt 4 – `service_win.py` Refactoring (Orchestrator)

* **`serviceui/service_win.py` (Anpassung):** Fensteraufbau um einen `QSplitter` (horizontal) erweitert: links bestehender Set-Editor + dynamische Service-Spalten, rechts `ServiceSelectorWidget` (Modus `FULL_EDIT`) + `ParameterPanel`. Bestehende Scanner-/Set-/Evaluator-Logik bleibt unverändert (Verbotsregel).
* **Fenstergröße 1280 x 800:** Single Source of Truth ist die `ui/service_win.ui`-Geometrie (vom QUiLoader angewendet) – kein fixer `resize()`-Aufruf im Code, damit der 5.4-Content-Reflow (`resize_to_clamped_content`) die Größe weiterhin inhalt-/bildschirmbasiert anpassen kann.
* **`serviceui/__init__.py`:** Export der neuen Sub-Widgets (`MasterTree`, `ServiceToolbar`, `StatusPanel`, `ParameterPanel`, `ServiceSelectorWidget`).

### 3.5 Schritt 5 – Action-Handler & EventBus-Sync

* Toolbar-Aktionen auf die bestehenden Set-Methoden gekoppelt: `[➕]` → Popup → `add_instance()`, `[▲]/[▼]` → `move_order_item(±1)`, `[🗑️]` → `remove_instance()` (P14-04-Sperrprüfung), `[🔄]` → `reload_plugins()`.
* MasterTree-Auswahl synchronisiert Set-Combo, Instanz-Liste und `ParameterPanel` (bidirektional, Live-Edit fließt in `collect_set_definition()`).
* **EventBus-Sync:** `service_set_changed` wird bei jeder Struktur-/Parameter-Änderung emittiert:
  * `set_item_adapter.py`: nach `_item_save_as()` (speichern) und `_item_delete_current()` (löschen).
  * `trash_dialog.py`: nach `restore_set_from_trash()` (wiederherstellen).
  * `service_win.py`: nach `add_instance()`, `move_order_item()`, `remove_instance()`.

### 3.6 Schritt 6 – Headless-Test

**`test/check_p15_s2_service_tree.py` (NEU, Test-DB in `test/`):** Prüft ServiceSelectorModel (Grunddaten, Hierarchie, Standalone-Abgrenzung, Live-Status „Aktiv im Chart" via StateManager, EventBus-Reaktivität), ServiceSelectorWidget Modus `SELECT_ONLY` (Combos + `selection_changed`) und Modus `FULL_EDIT` (MasterTree-Gruppen, Badge-Spalte, `current_selection()`) sowie Set-Updates/Umsortieren.

**Ergebnis: 31/31 Checks PASS** (Exit 0). Zusätzlich verifiziert:
* `check_p13_service_win_geometry.py`: ServiceWindow konstruiert mit neuem QSplitter-Aufbau; alle 5.4-Dynamik-Checks (Spalten, Expert-Aufklappen, Scroll-Range, add_instance) bestehen. **Einzige verbleibende Meldung:** vorbestehend aus 15.01 (`setFixedWidth(32)` des ★-Favoriten-Buttons), nicht durch 15.02 verursacht.
* `python -m py_compile` auf allen neuen/geänderten Dateien (Exit 0).

### 3.7 Schritt 7 – Bugfixing: Access-Violation-Schutz & Geometrie-Persistenz (Commit `7ac0581`)

**Fehler 0 – App-Crash bei wildem Klicken auf Services (Exit-Code `0xC0000005`, Access Violation):**
Ursache: `data_changed`/`setCurrentItem`-Klick löst `_populate()` → `clear()` aus; `currentItem()` zeigte auf ein bereits C++-seitig zerstörtes `QTreeWidgetItem` → `.data()`-Zugriff crasht hart. Zusätzlich: `clear()` im `ParameterPanel` stieß beim `TypeError` (`'QWidgetItem' object is not callable`) auf ein Absturz-Kandidat-Problem.

Fixes (4 Dateien):
* **`scrollable_content.py`:** `resize_to_clamped_content()` – **Persistenz-Fix**, Fenster wird nie unter die aktuelle (User-/wiederhergestellte) Größe geschrumpft, nur vergrößert (bis Bildschirm). `_apply_reflow_size()` – try/except gegen Feuern nach Fenster-Schließen.
* **`serviceui/master_tree.py`:** `shiboken6.isValid()`-Guards (Fallback-Def) in `_safe_current_selection()`/`current_selection()`/`_emit_selection()`/`_restore_selection()` (setCurrentItem unter `blockSignals` + try/finally) und im `TreeItemIterator` (Init/`_collect`/`__next__`).
* **`serviceui/parameter_panel.py`:** `clear()` entfernt Form-Zeilen-Widgets jetzt explizit (`takeRow` → `fieldItem`/`labelItem` als **Attribute** der `TakeRowResult` – nicht Methoden –, `setParent(None)` + `deleteLater()`), Experten-Gruppe inklusive. `_emit_params_changed()`/`_reflow()` mit try/except.
* **`serviceui/service_win.py`:** `_qt_valid`-Import; isValid-Guards in `_on_master_selection()`, `_sync_param_panel()`, `_on_param_panel_changed()`; try/except in `_set_ctrl_value()`.

**Fehler 1 – Letzte Fensterposition/-größe wurde nicht persistiert:**
Ursache: `resize_to_clamped_content()` (ContentScrollMixin) schrumpfte nach `restore_state()` das Fenster wieder auf Inhalt/Screen-Größe → `save_state()` speicherte falsche Geometrie. Fix: Nur-wachsen-Logik (siehe oben).

**Validierung (`test/test.py`, offscreen, Test-DBs in `test/`):**
* Teil 1 Persistenz (P1–P5): Position wiederhergestellt (150,120), Höhe nicht unter 400 geschrumpft, User-Höhe 450 bleibt erhalten, `save_state()` speichert User-Position/-Höhe → **alle PASS**.
* Teil 2 Klick-Sturm (K1/K2): 40 schnelle Service-Klicks (`setCurrentItem` + `_on_master_selection`) ohne Absturz, Fenster bleibt lebendig → **alle PASS**.
* `python -m py_compile` auf allen geänderten Dateien (Exit 0).

**Hinweis Test-Artefakt:** Der frühere K2-Fail lag nicht an der App, sondern am `pump()`-Helper: `QApplication.quit()` setzt den Quit-Flag und versteckt auf der offscreen-Plattform alle Top-Level-Fenster (`isVisible() → False`). Fix im Test: `QEventLoop`-Muster statt `QApplication.quit()`.

### 3.8 Schritt 8 – Bugfixing: Fenster-Historie (Service/Analytics) & Chart-Circles

**Fehler A – ServiceWindow wurde nicht aus der Fenster-Historie wiederhergestellt & letzte Position nicht gespeichert:**
Ursache: `serviceui/service_win.py` war mit `@register_persistent_window(auto_restore=False)` registriert → `restore_all_windows()` (main.py) übersprang es beim App-Start. Zusätzlich war `_keep_history_on_close` nicht gesetzt (Default `False`) → `PersistentWindow.closeEvent()` rief nach `save_state()` sofort `delete_instance()` → die Geometrie wurde gespeichert und wieder gelöscht („letzte Position wird nicht saved/restored").

Fix (Runde 2): `@register_persistent_window()` (auto_restore=True) – das Fenster wird beim App-Start wiederhergestellt, wenn es beim Beenden offen war.

**Fehler B – Im Chart werden keine Proximity-Circles mehr angezeigt:**
Ursache: Seit U15-A3 (Commit `2e3d8d4`, „Pipeline-Fallback entfernt") kamen die Circles ausschließlich aus dem feature_store (`feature_id='proximity'`). Der Store ist aber leer, solange keine aktiven Batch-Presets (`is_active_batch=True`) existieren → LiveAnalyzer/HistoricalScanner schreiben keine Proximity-Payloads → `read_proximity_from_feature_store()` liefert `[]` → keine Circles. Der Chart berechnete die Circles in seiner internen Service-Pipeline zwar, verwarf sie aber ungenutzt.

Fix (Runde 2) in `chart/indicators/grid_liquidity.py` (`calculate()`): PRIMÄR feature_store lesen (U15-A3-Lesepfad bleibt); ist der Store leer, greift der definierte Fallback auf die pipeline-berechneten `hit_circles` des Proximity-Service (`prox_crp.hit_circles`, Parität zu U15-A2). Beide Pfade nutzen dieselbe `_colorize()`-Farb-Logik (in_window + use_time_filter → `circle_color_std`, sonst `circle_color_active`); `show_circles=False` wird in beiden Pfaden respektiert.

**Fehler C – Analytics- & ServiceWindow poppten trotz manuellem Schliessen beim Neustart wieder auf:**
Ursache: Durch den Runde-2-Fix (und den vorbestehenden 15.03-Fix bei AnalyticsWindow) war `_keep_history_on_close = True` gesetzt → manuell geschlossene Fenster blieben in `window_instances`/`instance_states` → `restore_all_windows()` stellte sie wieder her.

Fix (Runde 3) – **History-Semantik wie `chart_win`**:
* `serviceui/service_win.py`: `_keep_history_on_close = True` entfernt (Default `False`); `@register_persistent_window()` (auto_restore=True) bleibt.
* `analytics/ui/analytics_win.py`: `_keep_history_on_close = True` entfernt (Default `False`); `@register_persistent_window()` (auto_restore=True) bleibt.

Ergebnis-Semantik (identisch zu `chart_win`):
| Szenario | Ergebnis |
| --- | --- |
| Fenster offen, App beendet | `save_state()` im App-CloseEvent → Eintrag bleibt → **Restore beim Start** (Position/Größe) |
| Fenster manuell geschlossen, dann App beendet | `closeEvent` → `delete_instance()` → **kein Auto-Restore beim Start** |

**Validierung (`test/test.py`, offscreen, vollständig auf Temp-DBs isoliert – läuft auch bei offener App, DuckDB-Single-Writer):**
* Teil 1 Persistenz (P1–P5), Teil 2 Klick-Sturm (K1/K2) → alle PASS (Regressions-Schutz aus Schritt 7).
* Teil 3 Fenster-Historie (H1–H9): auto_restore aktiv; `_keep_history_on_close` ist False; nach `close()` sind Geometrie- UND Instanz-Eintrag entfernt (kein Auto-Restore); Neustart-Simulation für offene Fenster stellt (333,222)/600 wieder her; AnalyticsWindow identisch.
* Teil 4 Chart-Circles (C1–C5): feature_store leer → Pipeline-Fallback liefert 600 `hit_circles` mit Farbe + time/price; `show_circles=False` → keine Circles.
* `python -m py_compile` auf allen geänderten Dateien (Exit 0).

**Hinweis Test-Isolation:** Der Test patcht die `__init__`-Methoden von `ServiceSetRepository`/`StateManager` direkt (Modul-Patches würden durch In-Funktion-Imports überschrieben) und leitet `get_symbol_repository()` auf eine Temp-DB um – so läuft er unabhängig von der geöffneten App (die echten `data/*.duckdb`-Dateien sind durch deren Prozess gesperrt).

### 3.9 Schritt 9 – MasterTree-Layout-Bugfixes (5 Punkte) & Alt-Plugin `grid_liquidity` entfernt (04.08.2026)

**A) MasterTree – 5 Layout-/Bedien-Bugfixes (`serviceui/master_tree.py`):**
1. **Ebene 0 startet ganz links an der Linie der umschließenden Box:** `rootIsDecorated=False` + KEINE Icons/Spacer auf Top-Level-Knoten; die Einrückung der Untereinträge kommt ausschließlich aus `setIndentation(LEVEL_INDENT)` (20 px je Ebene). Vorher schob ein Spacer-Icon alle Zeilen nach rechts.
2. **Eingeklappt → `> ` vor dem Namen** (Knoten mit Kindern, noch nicht aufgeklappt).
3. **Ausgeklappt → `⌄ ` vor dem Namen** (Knoten mit Kindern, aufgeklappt). Das Symbol folgt dem IST-Zustand via `itemExpanded`/`itemCollapsed` → `_refresh_expand_label` (unter `blockSignals` explizit für Top-Level nach `_populate()`). `drawBranches` bleibt als bewusst leerer Override (keine nativen Branch-Dreiecke).
4. **Einfacher Mausklick togglet auf/zu:** `mousePressEvent` klappt bei Klick auf die GESAMTE Zeile eines Knotens mit Kindern um (zusätzlich Selektion bei selektierbaren Knoten); `setExpandsOnDoubleClick(False)` – Doppelklick togglet nicht mehr.
5. **Info-Symbol in der Status-Spalte ist ASCII `'i'`:** `BADGE_TRUNCATE_ICON = "i"` statt Unicode `🛈` (U+1F6C8) – das Emoji rendert in den Qt-Fonts unter Windows nicht zuverlässig (tofu-Box). Lange Badges (> `MAX_BADGE_CELL_CHARS` = 24) werden auf `'i'` gekürzt; der Indikator-Name steht im Tooltip der Spalte 1.

**B) Badge-Konvention auf echten Indikator-Namen umgestellt (`indicator_name`):**
* `analytics/engine/service_selector_model.py`: `badge_for()` liefert `📌 im <Indikator> | 🟢 aktiv in <Indikator>` bzw. `⚪ inaktiv in <Indikator>`; `get_indicator_display_name()` bevorzugt `metadata['indicator_name']` (z. B. `GridLiquidityIndicator`), Fallback `display_name`/`plugin_id`.
* `analytics/features/definitions/grid_lines_service.py` & `proximity_service.py`: Metadaten-Feld `indicator_name: "GridLiquidityIndicator"` ergänzt.
* `serviceui/master_tree.py` `_apply_badge()`: Tooltip der Status-Spalte unterscheidet `aktiv <Indikator>` (aktuell im Chart aktiv) vs. `im <Indikator>` (nur Abhängigkeit).

**C) Alt-Plugin `analytics/features/definitions/grid_liquidity.py` entfernt (archiviert):**
* `chart/indicators/grid_liquidity.py` ist jetzt vollständig self-contained: `_GRID_LIQUIDITY_SCHEMA`/`_GRID_LIQUIDITY_ORDER`, Properties `plugin_id`/`parameter_schema`/`parameter_order`/`base_parameter_schema`/`full_parameter_schema()`, statisches `default_params` – kein `PluginRegistry`-Import mehr.
* `indicator_dialog._get_plugin()` nutzt für `grid_liquidity` Branch 1 (Indikator ist das Plugin) – alle `self.plugin.*`-Zugriffe bleiben kompatibel.
* Produktions-Aufrufer sind robust gegen fehlende Plugins (KeyError-Handling): `service_set_repository`, `live_analyzer`, `service_win`, `parameter_panel`, `param_columns`, `indicator_dialog`.
* **Migration angewendet** (`python test/migrate_grid_liquidity.py --apply`): keine Alt-Referenzen in `service_sets`/`service_sets_trash`/`service_set_history`/`indicator_presets`/`feature_store`.
* **Archivierung:** `analytics/features/definitions/grid_liquidity.py` → `.backup_grid_liquidity/analytics/features/definitions/grid_liquidity.py` (aus dem Discovery-Pfad entfernt; Original bleibt erhalten). Ordner `.backup_*/` ist jetzt in `.gitignore`.
* `PluginRegistry` findet final nur noch `grid_lines` + `proximity`; `get('grid_liquidity')` wirft `KeyError` (erwartet). `test/check_phase14_regression.py` P14-02a-Schwelle `>= 3` → `>= 2`.

**Validierung (alle headless, grün):**
* `test/check_p15_s2_service_tree.py`: F5 → `'i'`-Badge, F5c/F5d → `⌄` (expandiert) / `>` (zugeklappt), F5e Blatt ohne Symbol, F5f–F5j Layout, G1/G2 – **alle PASS**.
* `test/test.py`: T9a (zustandsabhängiger Marker), T9b/T10 (Einfach-Klick-Toggle), T11 (kein Icon), T4/T5 (`'i'`-Badge) – **alle PASS**.
* `test/check_phase14_regression.py` (P14-02d: `grid_liquidity` NICHT mehr registriert), `test/check_plugin_batch_services.py`, `test/check_plugin_executor.py`, `test/check_p14_s2_discovery.py`, `test/check_grid_parity.py`, `test/check_p13_s1.py` – **alle PASS**.
* `python -m py_compile` auf allen geänderten Dateien (Exit 0); Import-Smoke-Test der Produktionsmodule (Chart, Service-UI, Dialoge, Repository) erfolgreich.

### 3.10 Schritt 10 – Restarbeiten: Service-`grid_liquidity`-Altlasten & verwaiste `grid`-Keys aus DBs entfernt (05.08.2026)

**A) Verifikation: Service `grid_liquidity` gehört zum ausgemusterten Alt-Indikator:**
* `analytics/features/definitions/grid_liquidity.py` ist seit Schritt 9 archiviert (`.backup_grid_liquidity/`, aus dem Discovery-Pfad entfernt). `PluginRegistry` findet final nur noch `grid_lines` + `proximity` → der Service erscheint **nicht mehr im ServiceTree**; `get('grid_liquidity')` wirft `KeyError` (erwartet).
* **Fehlende Restarbeiten identifiziert:** Die in Schritt 9 dokumentierte Migration (`test/migrate_grid_liquidity.py`) hatte die PERSISTIERTEN falschen Relationen in `app_data.duckdb` nur teilweise abgedeckt. Kategorisierung per DB-Scan (`test/_probe_*`, temporär):
  1. **`indicator_presets`:** Alt-Preset `('grid_liquidity', 'SILVER:M1 Test')` mit ALTER Service-Plugin-Struktur (`logic_params`/`display_params`/`set_id`) – kein gültiges Preset des neuen self-contained Indikators (der speichert flache Schema-Params).
  2. **`symbol_tf_states` (7) + `instance_states` (1):** `grid_liquidity`-Sub-States mit alter Struktur (`preset='SILVER:M1 Test'`, `set_id` aus dem gelöschten Alt-Preset) – würden den neuen Indikator mit unverständlichen Parametern restaurieren.
  3. **`symbol_tf_states` (11) + `instance_states` (1):** verwaiste `indicators_state`-Keys `'grid'` des am 04.08.2026 entfernten Alt-Indikators `chart/indicators/grid.py` (alle `active=false`; `chart_win.py` popt den Key zur Laufzeit bereits per U15-B4 – DB-Bereinigung ist reine Hygiene).

**B) Bereinigung (`python test/migrate_grid_liquidity.py --apply`, headless):**
* `indicator_presets`: Alt-Preset `'SILVER:M1 Test'` **gelöscht** (falsche Relation zum neuen Plugin-Grid-Indikator).
* `symbol_tf_states` / `instance_states`: **7+1 falsche `grid_liquidity`-Relationen** (alte Struktur) und **11+1 verwaiste `grid`-Keys** aus den `indicators_state`-JSONs **entfernt**.
* **`test/migrate_grid_liquidity.py` erweitert** (bleibt erhalten, `test/` gitignored):
  * Abschnitt 3b: Alt-Presets mit `indicator_id='grid_liquidity'` UND alter Service-Plugin-Struktur werden erkannt und gelöscht; gültige flache Presets bleiben unangetastet.
  * Abschnitt 5: falsche `grid_liquidity`-Relationen (alte Struktur) in `instance_states`/`symbol_tf_states` werden aus dem JSON entfernt.
  * Abschnitt 6: verwaiste `'grid'`-Keys (U15-B4) werden aus dem JSON entfernt.
  * Dry-Run/`--apply`-Logik & Exit-Code konsistent (0 = keine Alt-Referenzen mehr).
* **Kommentar-Polish** (nur Doku, keine Logik): Beispiel `(z.B. 'grid_liquidity')` → `(z.B. 'grid_lines')` in `db_service.py`, `state_manager.py`, `analytics/features/plugins/base_plugin.py`.
* **Stale Bytecode entfernt:** `analytics/features/definitions/__pycache__/grid_liquidity.cpython-314.pyc`, `chart/indicators/__pycache__/grid.cpython-314.pyc`.

**Validierung (alle headless, grün):**
* `python test/migrate_grid_liquidity.py` (Dry-Run): **exit 0** – Abschnitte 1–6 melden keine Alt-Referenzen mehr (vor Apply: 9 falsche Relationen + 12 verwaiste `grid`-Keys gefunden; nach Apply: 0).
* `PluginRegistry`-Smoke: `sorted(plugins.keys()) == ['grid_lines', 'proximity']`; `GridLiquidityIndicator.service_plugin_ids == ['grid_lines', 'proximity']`.
* DB-Bestandskontrolle: keine `feature_id='grid_liquidity'` in `feature_store`; `service_sets`/`trash`/`history` ohne `grid_liquidity`-Referenzen; keine verwaisten `grid`-Keys in `symbol_tf_states`/`instance_states`.
* `python -m py_compile` auf allen geänderten Dateien (Exit 0).

### 3.11 Schritt 11 – Bugfix: MasterTree-Tooltip-Aktiv-Logik & Set-Badge (05.08.2026)

**Bug 1 – Tooltip zeigte `'im <Indikator>'` auch für aktiv im Chart laufende Services:**
Ursache: `_apply_badge()` prüfte `is_active_in_chart(plugin_id)` ausschließlich gegen die Plugin-ID (`grid_lines`/`proximity`). Aktiv im Chart sind aber die `indicators_state`-Keys des INDIKATORS (`grid_liquidity`), nicht die Plugin-ID – dadurch griff die Tooltip-Variante a) (`aktiv <Indikator>`) für Services nie.

Fixes (4 Dateien):
* **`analytics/engine/service_selector_model.py`:** Neue Lese-Methoden `get_indicator_id()` (metadata-Fallback `plugin_id`), `belongs_to_indicator()`, `get_set_indicator_names()`, `is_set_active()`; `is_active_in_chart()` prüft zusätzlich den zugehörigen Indikator (metadata `indicator_id`) – dadurch ist ein Service auch dann „aktiv im Chart", wenn sein Indikator (z. B. `GridLiquidityIndicator`) läuft.
* **`analytics/features/definitions/grid_lines_service.py` & `proximity_service.py`:** Metadaten-Feld `indicator_id: "grid_liquidity"` ergänzt (bereits vorhandenes `indicator_name` bleibt).
* **`serviceui/master_tree.py` `_apply_badge()`:** ODER-Logik „aktiv \<Indikator\>" / „im \<Indikator\>" auf Indikator-Basis; Tooltip wird auf Spalte 0 UND Spalte 1 gesetzt.

**Bug 2 – Service-Sets mit Indikator-Zugehörigkeit zeigten kein Status-Symbol:**
Fix: Neue `_apply_set_badge()` – Set-Knoten mit Indikator-Zugehörigkeit zeigen in Spalte 1 das Info-Zeichen (`'i'`) mit derselben Tooltip-Namenslogik wie Services; mehrere Indikatoren werden mit `' + '` verknüpft.

**Validierung (`test/check_p15_s2_service_tree.py`, erweitert C5–C9/F5k/F5l, headless):** 49/49 Checks PASS – inkl. Aktiv-Prüfung via Indikator-ID (`grid_liquidity`), `belongs_to_indicator`, Set-Indikator-Namen und Set-Aktiv-Status.

### 3.12 Schritt 12 – Info-Button im MasterTree statt Box-Button (05.08.2026)

**Anforderung (5 Punkte, vom Anwender entschieden):** `btn_info_service` aus der Box „Service-Sets (Phase 13)" entfernen; stattdessen pro Zeile im MasterTree (Spalte 1) ein echter Info-Button `"ℹ"` auf Icon-Breite; Status-Spalte auf Button-Breite verkleinert und weiterhin ganz rechts (Spalte 0 = Stretch); Klick öffnet den Beschreibungs-Dialog mit **erster Zeile = bisheriger Tooltip-Text** (`aktiv/im <Indikator>`), dann Leerzeile, dann Beschreibungstext. Button auf ALLEN Service-/Plugin-/Set-Zeilen; **gelbe Färbung** (`#FFD700`) bei Indikator-Relation, sonst neutral; **Badge-Text entfällt** aus Spalte 1, Tooltip bleibt unverändert.

**Umsetzung (6 Dateien):**
* **`serviceui/master_tree.py`:** Neues Signal `info_requested(set_id, service_id, plugin_id)`; `_attach_item_buttons()` hängt nach jedem `_populate()` einen kompakten `QPushButton("ℹ")` (20×20, `border:none`, gelb `#FFD700` bei vorhandenem Indikator-Tooltip, sonst neutral `#666666`) an alle Service-/Set-/Plugin-Zeilen (Gruppen bewusst ohne Button). `_apply_badge()`/`_apply_set_badge()` setzen KEINEN Badge-Text mehr (Zelle leer); Tooltip-Logik unverändert. Spalte 1 `Fixed` + `resizeSection(1, INFO_BUTTON_WIDTH=24)` (vorher `BADGE_COLUMN_WIDTH=36`, bleibt als Test-Referenz). Neue Konstanten `INFO_BUTTON_TEXT/SIZE/WIDTH/COLOR_*`.
* **`serviceui/service_selector_widget.py`:** `info_requested` des MasterTree wird re-emittiert (neues Widget-Signal).
* **`serviceui/service_win.py`:** Neuer Slot `_on_tree_info_requested(set_id, service_id, plugin_id)` (Verdrahtung in `_wire_selector_toolbar()`); Helfer `_resolve_info_plugin()`/`_info_header_tooltip()`/`_info_set_tooltip()`. Öffnet je Zeilentyp: Service → `from_plugin(Instanz+Config)`, Plugin → `from_plugin()`, Set → `from_set()`. Alter `_show_service_info()` bleibt erhalten (Guard über `btn_info_service` ist nach UI-Entfernung `None` → kein Crash).
* **`analytics/engine/description_dialog.py`:** Neuer `header_line`-Parameter (fette erste Zeile + Leerzeile vor dem Beschreibungstext) in `__init__`/`_render_html`/`from_plugin`; neue Klassenmethode `from_set()` (Set-Name, Set-Beschreibung, Service-Liste in `execution_order`).
* **`ui/service_win.ui`:** `btn_info_service`-Block („ℹ Info" + Tooltip) aus `layout_order_buttons` entfernt.

**Validierung (headless, grün):**
* `test/check_p15_s2_service_tree.py`: F5–F5s auf Button-Präsenz umgestellt (nur-Icon/Icon-Breite, Tooltip unverändert, Set-Button, Button auf ALLEN Zeilen, gelb bei Indikator-Relation + neutral bei injiziertem Plain-Plugin, Spalte auf `INFO_BUTTON_WIDTH`, `info_requested`-Emission für Service/Set/Plugin); neu H1–H4 (`from_set`/`from_plugin` rendern `header_line`) – **alle PASS** (3× stabil).
* `test/test.py`: T4/T5 auf Info-Button-Checks umgestellt, T8b (Spaltenbreite) + T12 (`info_requested` Set-Zeile) neu; **Flakiness-Fix T9b/T10**: manuelle `QMouseEvent`-Synthetic-Clicks sind auf dem offscreen-Platform-Fenster timing-flaky (nachgewiesen: `itemAt`/`setExpanded` korrekt, `mousePressEvent` byte-identisch zu HEAD → vorbestehend) → Umstellung auf `QTest.mouseClick` → **5/5 Läufe stabil**.
* `python -m py_compile` auf allen geänderten Dateien (Exit 0); UI-XML parst fehlerfrei.

### 3.13 Schritt 13 – U15-D2: Toolbar-Refactoring & MasterTree-Kontextmenü (05.08.2026)

**Anforderung (3 Punkte, vom Anwender entschieden – Punkt 3 „grid_lines-Alt-Rumpf-Bereinigung" wurde abgewählt, da `analytics/features/definitions/grid_lines_service.py` der AKTIVE Service ist; obsolet war nur das bereits in Schritt 9/10 archivierte `grid_liquidity.py`):**

**A) Toolbar-Refactoring (`serviceui/toolbar.py`):**
* Plugins-Button `btn_reload` und Signal `reload_plugins_requested` **entfernt** – der Hot-Reload bleibt über den UI-Button `btn_reload_plugins` (`service_win.ui`) erreichbar.
* Order-Buttons heißen jetzt `Order ▲` / `Order ▼` (statt `▲`/`▼`) und sind ohne Service-in-Set-Auswahl deaktiviert (`set_order_enabled(bool)`).
* Bifunktionaler `btn_add`: `[➕ Set]` (neues leeres Set anlegen, `add_set_requested`), `[➕ Service]` (Plugin-Popup, `request_add_popup`), `[➕]` deaktiviert – gesteuert über `set_add_mode("set"/"service"/"none")`.
* Bifunktionaler `btn_remove`: `[🗑️ Set löschen]` (Papierkorb, P14-05), `[➖ Service entfernen]` (P14-04-Sperrprüfung), `[🗑️]` deaktiviert – gesteuert über `set_remove_mode("set"/"service"/"none")`.
* `set_actions_enabled()` ist durch die Modus-Methoden ersetzt; neues Signal `add_set_requested = Signal()`.

**B) MasterTree-Kontextmenü (`serviceui/master_tree.py`, strikt entkoppelt):**
* `CustomContextMenu` + `_show_context_menu(pos)`: dynamisch je Knotentyp, Aktionen emittieren AUSSCHLIESSLICH Signale (kein ServiceWindow-Import in der UI-Klasse, IoC):
  * Gruppe 📁 (sets) → `create_set_requested` ('Neues Set anlegen').
  * Set-Knoten → `rename_set_requested(set_id)`, `add_set_service_requested(set_id)`, `delete_set_requested(set_id)`.
  * Service-Knoten → `move_service_requested(set_id, service_id, delta)` (Order ▲/-1, ▼/+1), `remove_service_requested(set_id, service_id)`, 'Service-Info anzeigen' über das bestehende `info_requested`.
  * Außerhalb eines Sets (Plugin-Zeilen, ⚡-/📦-Gruppen): Order/Entfernen/Umbenennen ausgegraut (`_add_outside_set_actions`, `setEnabled(False)`); 'Service-Info anzeigen' bleibt bei Plugin-Zeilen aktiv.
* Neues Signal `group_activated(group)`: wird im `mousePressEvent` bei Klick auf einen (nicht selektierbaren) Gruppen-Knoten emittiert – die Toolbar braucht es, weil Gruppen-Knoten kein `selection_changed` feuern (kein `ItemIsSelectable`-Flag).

**C) `serviceui/service_win.py` (Orchestrator):**
* `QInputDialog` importiert (für den Namensdialog beim Umbenennen).
* `_wire_selector_toolbar()` neu verdrahtet: `reload_plugins_requested`-Referenz entfernt; `add_set_requested` + alle 7 Kontextmenü-Signale auf neue Handler gelegt (DRY: Toolbar- und Kontextmenü-Aktionen teilen dieselben Handler).
* `_on_master_selection` ruft jetzt `_update_toolbar_actions(set_id, service_id)` auf (bifunktionaler Toolbar-Zustand nach jeder Baum-Auswahl).
* Neue Handler (`_current_tree_selection`, `_update_toolbar_actions`, `_on_group_activated`, `_on_toolbar_remove`, `_on_add_set`, `_on_rename_set`, `_on_add_set_service`, `_on_delete_set`, `_select_service_in_editor`, `_on_move_service`, `_on_remove_service`):
  * `_on_add_set`/`_on_rename_set` laufen bewusst DIREKT über `set_repo.save_set()` – der `NamedItemAdapter._item_save_as()` verweigert leere `execution_order`, leere Sets wären sonst weder anleg- noch umbenennbar.
  * `_on_delete_set` lädt das Set in den Editor und ruft das bestehende `delete_set()` auf (P14-04-E-Sperre 'letztes Set' + Papierkorb-Rückfrage greifen dort zentral).
  * `_on_move_service`/`_on_remove_service` selektieren die Instanz im Editor (`_select_service_in_editor`) und reusen `move_order_item(delta)` bzw. `remove_instance()` (inkl. P14-04-Sperrprüfung).

**Validierung (headless, grün):**
* `python -m py_compile` auf `serviceui/toolbar.py`, `serviceui/master_tree.py`, `serviceui/service_win.py` (Exit 0).
* Import-Smoke: `MasterTree`/`ServiceToolbar`/`ServiceWindow` mit allen neuen Signalen & Methoden vorhanden; `btn_reload`/`reload_plugins_requested`/`set_actions_enabled` vollständig entfernt (keine Rest-Referenzen im Produktionscode; `reload_plugins_requested` nur noch als Doku-Kommentar).
* Projektweite Suche: keine Test-Abhängigkeiten auf das entfernte Toolbar-API.
### 3.14 Schritt 14 - Bugfix Runde 3: Rechtsklick-Toggle, Papierkorb-Kontextmenue & ParameterPanel entfernt (05.08.2026)

**Anforderung (4 Punkte, vom Anwender entschieden):**

**A) Rechtsklick expandiert/kollabiert Knoten (serviceui/master_tree.py):**
* _show_context_menu() togglet vor dem Menueaufbau bei Knoten mit Kindern (childCount() > 0) item.setExpanded(not item.isExpanded()) - Konsistenz mit dem Linksklick (Schritt 9, Punkt 4), damit das Kontextmenue immer auf dem sichtbaren Knoten steht (isValid-Guard bleibt).

**B) Loeschen in den Papierkorb (bereits vorhanden, keine Aenderung):**
* delete_set() → ServiceSetRepository.delete_set(soft_delete=True) verschiebt das Set nach service_sets_trash; ServiceSetTrashDialog (tn_trash_sets) bietet Wiederherstellen + endgueltiges Loeschen (P14-05).

**C) Kontextmenue \'Papierkorb loeschen...\' mit doppelter Sicherheitsabfrage (2 Dateien):**
* serviceui/master_tree.py: Neues Signal purge_trash_requested = Signal(); Menueeintrag \'Papierkorb loeschen...\' bei Set- UND Service-Knoten (alle Lambdas mit _=False, Shiboken-bool-Schutz).
* serviceui/service_win.py: Neuer Slot _on_purge_trash() - leere-Pruefung ueber set_repo.list_trash(), dann DOPPELTE QMessageBox.question-Abfrage (P14-05, Vorgang nicht umkehrbar), set_repo.purge_trash() + event_bus.service_set_changed.emit(); verdrahtet via 	ree.purge_trash_requested.connect(self._on_purge_trash) in _wire_selector_toolbar().

**D) ParameterPanel komplett entfernt (Code + Relationen, 3 Aenderungen):**
* serviceui/service_win.py (Patch via 	est/_apply_fix_round3_sw.py): ParameterPanel-Import, param_panel-Erzeugung/Layout (right_layout), _on_symbol_changed-Block, params_changed-Verdrahtung, _sync_param_panel()-Aufrufe in _on_master_selection/_clear_set_editor/load_set_into_editor/_sync_list_selection sowie die Methoden _sync_param_panel/_on_param_panel_changed/_set_ctrl_value KOMPLETT entfernt. Wichtig: Das End-Slice der Methoden-Entfernung zeigt auf die U15-D2-Sektion (Toolbar-Zustand & Kontextmenue-Handler) - die Handler _on_remove_service & Co. liegen NACH diesem Marker und bleiben erhalten (erster Versuch mit der 15.01-Sektion als End-Slice entfernte faelschlich _on_remove_service). Zusaetzlich 2 veraltete Kommentar-/Docstring-Erwaehungen bereinigt.
* serviceui/__init__.py: ParameterPanel-Import, __all__-Export und Dokuzeile entfernt (
ew_set_dialog.py in der Doku ergaenzt).
* serviceui/parameter_panel.py → .backup_parameter_panel/serviceui/parameter_panel.py archiviert (Konvention wie .backup_grid_liquidity, aus dem Discovery-Pfad entfernt; Original bleibt erhalten).
* **Keine DB-Tabelle:** ParameterPanel ist reine UI - nichts in DuckDB zu loeschen.

**Validierung (headless, gruen):**
* python -m py_compile auf service_win.py, master_tree.py, __init__.py, service_selector_widget.py, 
ew_set_dialog.py, param_columns.py, 	rash_dialog.py (Exit 0).
* Import-Smoke: serviceui, service_win, master_tree (Signal purge_trash_requested vorhanden), selector/widget/dialog/toolbar/status - OK; ParameterPanel nicht mehr in __all__.
* Projektweite Rest-Referenz-Suche (ParameterPanel|param_panel|_sync_param_panel|_on_param_panel_changed|_set_ctrl_value im Produktionscode): **0 Treffer**.
* Verifikation _on_purge_trash: set_repo.list_trash()/purge_trash() und event_bus vorhanden; Kontextmenue-Toggle (count 2), Papierkorb-Eintraege (count 2, Set- + Service-Knoten) bestaetigt.

### 3.15 Schritt 15 – MasterTree-Ausführungsdatum & Kontextmenü-Ausführung (05.08.2026)

**Anforderung (3 Punkte, vom Anwender entschieden):** Alle CRUD-/Steuer-Buttons oberhalb des MasterTrees entfernen (UI + Event-Verbindungen) → MasterTree hat die volle vertikale Höhe der linken Spalte. Ausführungsdatum hinter dem Service-Namen (`Service_Name (DD.MM.JJ)`, z.B. `prox_1 (05.08.26)`), gelesen aus `analytics.duckdb`/`feature_store` (`MAX(created_at)` je `feature_id`), Fallback `(--.--.--)`. Kontextmenü-Run-Aktionen (`[▶️ Diesen Service ausführen]` bei Service-Knoten, `[▶️ Alle Services ausführen]` bei Set-Knoten) mit `QMessageBox.question`-Bestätigung (Set/Service + aktuelles Symbol/Timeframe) – **kein globaler Massen-Scan** (HistoricalScanner bewusst vermieden), sondern gezielter Run des selektierten `instance_id`/Sets für das aktive Symbol/Timeframe in einem QThread (OHLCV → `PluginExecutor`-Pipeline → `store_plugin_payload` → `event_bus.service_set_changed.emit()` → Modell-Refresh → Datum live im Baum ohne Neustart). Tree-Label ohne `[plugin_id]` (entspricht exakt dem Aufgaben-Beispiel). Single-Run inkl. Upstream-Abhängigkeiten (frühere Services der `execution_order`, damit `proximity` seine Linien aus `grid_1` via `depends_on` erhält).

**A) CRUD-Buttons entfernt (3 Dateien):**
* `serviceui/service_selector_widget.py`: Toolbar-Import entfernt; `_build_full_edit()` baut nur noch den MasterTree (`self.toolbar = None` bleibt als Attribut für Abwärtskompatibilität); MasterTree füllt die gesamte Höhe der linken Spalte.
* `serviceui/service_win.py`: `_wire_selector_toolbar()` neu – ohne Toolbar-Verdrahtung (nur noch `selection_changed`, `info_requested`, 7 Kontextmenü-Signale + die 2 neuen Run-Signale); `_show_toolbar_add_popup()`, `_update_toolbar_actions()`, `_on_group_activated()`, `_on_toolbar_remove()`, `_current_tree_selection()` entfernt; `_on_master_selection`-Toolbar-Call entfernt. `group_activated` bleibt als Signal im MasterTree erhalten (potenzielle Aufrufer, keine Toolbar-Verwendung mehr).

**B) Ausführungsdatum (4 Dateien):**
* `analytics/engine/feature_store_reader.py`: Neue rein lesende Methode `fetch_last_execution_dates() -> Dict[str, str]` – `SELECT feature_id, MAX(created_at) FROM feature_store GROUP BY feature_id`, formatiert `DD.MM.JJ`, defensiv (Fehler → leer).
* `analytics/features/feature_builder.py`: `store_plugin_payload()` setzt bei `ON CONFLICT DO UPDATE` zusätzlich `created_at = current_timestamp` – der Zeitstempel spiegelt die LETZTE Ausführung (nicht den Erst-Schreibzeitpunkt).
* `analytics/engine/service_selector_model.py`: Neuer Parameter `feature_store_reader` (Default echte Instanz); `refresh()` liest zusätzlich `_last_execution_dates`; `last_execution_date(plugin_id)` → `DD.MM.JJ` / `(--.--.--)` (case-insensitiv); `build_tree()` liefert je Service `"last_execution"`.
* `serviceui/master_tree.py`: `_build_set_item` – Service-Label `f"{instance_id} ({last_exec})"` (ohne `[plugin_id]`).

**C) Kontextmenü-Ausführung (2 Dateien + NEU `serviceui/run_worker.py`):**
* `serviceui/master_tree.py`: Neue Signale `run_service_requested = Signal(str, str)` (set_id, instance_id) und `run_set_requested = Signal(str)` (set_id); Kontextmenü: Set-Knoten `'▶️ Alle Services ausführen'` (erste Aktion), Service-Knoten `'▶️ Diesen Service ausführen'` (erste Aktion); beide strikt entkoppelt (Lambda-Emits, `_=False`-Guard).
* **`serviceui/run_worker.py` (NEU):** `ServiceRunWorker(QThread)` – Signale `log_message(str)`, `run_finished(str, int)` (scope_id, gespeicherte Rows), `run_failed(str, str)`. `_build_scope_definition()`: Set-Run = volle Definition; Single-Run = selektierter Service + alle Upstream-Services (`order[:idx+1]`), damit `depends_on`/`shared_state` gültig bleiben. `run()`: `FeatureBuilder.load_ohlcv` (Limit aus `StateManager`-Settings) → `prepare_plugin_df` → `PluginContext(mode="batch")` → `evaluator.execute_set()` → für jeden non-leeren `feature_store_payload` `fb.store_plugin_payload(symbol, timeframe, payload)` → `event_bus.service_set_changed.emit()` → `run_finished`.
* `serviceui/service_win.py`: `_run_worker`-Attribut; `_start_run_worker(scope_id, set_definition, instance_id)` (laufender-Worker-Guard, Symbol/Timeframe aus den Combos, Signal-Verdrahtung); `_on_run_service`/`_on_run_set` (Set via `set_repo.get_set` laden, Validierung, `QMessageBox.question` mit Set-/Service-Name + Symbol/Timeframe + Hinweis auf den feature_store-Schreibpfad); `_on_run_worker_finished`/`_on_run_worker_failed` (Log); `closeEvent` wartet zusätzlich auf `_run_worker`.
* `serviceui/__init__.py`: `ServiceRunWorker` exportiert (Import + `__all__`), Dokuzeilen aktualisiert.

**Validierung (headless, grün):**
* `python -m py_compile` auf allen 8 geänderten + `run_worker.py` (Exit 0); Import-Smoke `serviceui`/`run_worker`/`service_selector_model`/`feature_store_reader` erfolgreich; `MasterTree.run_service_requested`/`run_set_requested` vorhanden.
* Projektweite Suche: keine Rest-Referenzen auf `_update_toolbar_actions`, `_on_group_activated`, `_on_toolbar_remove`, `_show_toolbar_add_popup`, `selector.toolbar`-Methoden im Produktionscode (Attribut nur noch `None`).
* `test/check_p15_s2_service_tree.py` statisch aktualisiert (neue Test-DB `p15_s2_execdate_test.duckdb` in `test/`, J1–J7 für Ausführungsdatum, Fallback, Tree-Labels `prox_1 (05.08.26)`/`grid_1 (--.--.--)` und Run-Signal-Emission) – wie immer nicht ausgeführt (Regel: keine Regressionstests ohne explizite Anforderung).

### 3.16 Schritt 16 – Loose-Ends-Cleanup: ServiceToolbar archiviert & `group_activated` entfernt (05.08.2026)

**Anlass (vom Anwender entschieden):** Nach Schritt 15 (CRUD-Buttons entfernt, alle Struktur-Aktionen via Kontextmenü) war die Aktions-Toolbar toter Produktionscode – kein Widget nutzte sie mehr. Bereinigung nach der Projekt-Konvention (`.backup_*/`-Archivierung wie `.backup_grid_liquidity` und `.backup_parameter_panel`):

**A) `serviceui/toolbar.py` archiviert → `.backup_service_toolbar/serviceui/toolbar.py`:**
* `git mv` (Datei bleibt im Repo-Historie; `.backup_service_toolbar/` ist gitignored, Zeile 231 `.backup_*/`).
* `serviceui/__init__.py`: `from serviceui.toolbar import ServiceToolbar` + `"ServiceToolbar"` aus `__all__` entfernt; Paket-Docstring aktualisiert (Hinweis auf Archivierung, alle Struktur-Aktionen laufen über das MasterTree-Kontextmenü).

**B) `group_activated`-Signal aus `serviceui/master_tree.py` entfernt:**
* Deklaration (`group_activated = Signal(str)`), der Emit im `mousePressEvent` (Gruppen-Knoten-Klick) sowie alle Docstring-Erwähnungen (Modul-Doc, mousePressEvent-Doc) gelöscht – nach dem Toolbar-Abbau (Schritt 13/15) hat kein Consumer das Signal mehr verbunden.

**C) `service_selector_widget.py`: `toolbar`-Attribut komplett entfernt:**
* `self.toolbar = None` aus `__init__`, `set_mode()` und `_build_full_edit()` gelöscht (auch die Abwärtskompatibilitäts-Attribut bleibt nicht – kein Produktions-/Test-Code referenziert es mehr); `set_mode`-Docstring (`Tree+Toolbar` → `MasterTree`).

**D) `service_win.py`: veraltete Kommentare bereinigt** (keine Logik):
* Kommentar `# MasterTree + Aktions-Toolbar (Modus B / FULL_EDIT)` → `# MasterTree im Modus B / FULL_EDIT (seit 05.08.2026 ohne Toolbar)`.
* Kommentar `# Neues Set im MasterTree selektieren -> Toolbar [➕ Service]-Modus` → `# Neues Set im MasterTree selektieren (Editor-Sync via selection_changed)`.
* Methodennamen `_wire_selector_toolbar()` / `_toolbar_add_service()` bleiben als historische Namen erhalten (kein Consumer außerhalb; Umbenennung hätte historische Doku-Einträge 3.13–3.15 verfälscht).

**E) `test/check_p15_s2_service_tree.py` (statisch):** F2-Check von `full.toolbar is None` auf `not hasattr(full, "toolbar")` umgestellt (Attribut existiert nicht mehr); Docstring-Zeile F aktualisiert.

**Validierung (headless, grün):**
* `python -m py_compile` auf allen geänderten Dateien (`__init__.py`, `master_tree.py`, `service_selector_widget.py`, `service_win.py`, `test/check_p15_s2_service_tree.py`; Exit 0).
* Import-Smoke: `serviceui` importierbar; `ServiceToolbar` NICHT mehr in `__all__`; `ServiceRunWorker` bleibt; `MasterTree` ohne `group_activated`, mit `run_service_requested`/`run_set_requested`/`info_requested`.
* Projektweite Produktions-Referenz-Suche (ohne `docs/`, ohne `test/`): `group_activated`, `from serviceui.toolbar`, `self.toolbar`, `selector.toolbar` → **0 Treffer**; `ServiceToolbar` nur noch in der archivierten `.backup_service_toolbar/`-Datei und im `__init__`-Docstring (historischer Hinweis).
* Zeilenenden: `service_selector_widget.py` auf CRLF normalisiert (gemischt CRLF/LF nach Edits), alle übrigen Dateien blieben LF – git-Diff minimal und sauber.

### 3.17 Schritt 17 – Ausführungsdatum-Fixes: Legacy-Migration, Worker-Persistenz, Standalone-Datum (05.08.2026)

**Anlass (vom Anwender entschieden – Punkte 1, 2 und 4 aus der Fehleranalyse; Punkt 3 „(kein Feature-Store-Payload)" ist erwartetes Verhalten und wurde NICHT verändert):**

**A) Punkt 1 – „Keine Datumsangaben, obwohl Daten in der DB" (Ursache gefunden & behoben):**
* **Root Cause (per DB-Probe verifiziert):** ALLE 673.235 `feature_store`-Zeilen in `analytics.duckdb` waren Legacy-Rows der alten Monolith-Pipeline (`FeatureBuilder.build()`) mit `feature_id = NULL`, `plugin_version = NULL`, `feature_data = NULL` – die Abfrage `WHERE feature_id IS NOT NULL` fand dadurch NICHTS → Baum zeigte überall `(--.--.--)`, obwohl 673.235 Zeilen existierten.
* **`analytics/engine/feature_store_reader.py` (robustifiziert):** `fetch_last_execution_dates()` normalisiert jetzt `LOWER(TRIM(feature_id))` (Case-insensitiv + Whitespace-tolerant, Punkt 1-Kandidat 3), überspringt defensiv NULL/leere `feature_id` und NULL `created_at` (Kandidat 2).
* **NEU `test/migrate_legacy_feature_store.py` (Migration, Dry-Run + `--apply`):** Legacy-Zeilen mit befüllten Grid-Spalten (`grid_nearest_level`/`grid_dist_abs`/`grid_dist_pct`) tragen exakt die Proximity-Semantik (Abstand des Preises zu Grid-Linien) → werden auf `feature_id='proximity'`, `plugin_version='legacy'` migriert. `created_at` bleibt unverändert (echtes Legacy-Datum). `feature_data` bleibt NULL → der Chart-Lesepfad (`read_proximity_from_feature_store` filtert `feature_data IS NOT NULL` + `is_hit`) ignoriert die migrierten Zeilen weiterhin (KEINE Änderung im Chart-Rendering).
* **Angewendet:** **670.235 Zeilen → `feature_id='proximity'`**; 3.000 reine atr-Rows ohne Grid-Daten bleiben bewusst NULL (keine Proximity-Semantik, Exit-Code-Semantik des Skripts entsprechend: 0 = keine migrierbaren Grid-Zeilen mehr).
* **Verifiziert:** `fetch_last_execution_dates()` → `{'proximity': '02.08.26'}`; `feature_data IS NOT NULL` bei proximity weiterhin 0.

**B) Punkt 2 – „Nach Ausführen eines Services wird das Datum nicht aktualisiert" (ServiceSetRunWorker):**
* **`serviceui/set_run_worker.py`:** Der `ServiceSetRunWorker` (btn_execute_set-Pfad) persistiert jetzt die erzeugten `feature_store_payloads` ZWINGEND via `FeatureBuilder.store_plugin_payload()` in `analytics.duckdb` (Log je Service: „N Feature-Row(s) gespeichert" / „kein Feature-Store-Payload") und emittiert danach `event_bus.service_set_changed` → `ServiceSelectorModel.refresh()` liest das neue `MAX(created_at)` und der Baum aktualisiert das Datum `(DD.MM.JJ)` live ohne Neustart. `grid_lines` liefert bewusst keinen `feature_store_payload` (reines Chart-Overlay, Punkt 3) – nur Services mit non-leeren `records` (z.B. `proximity`) schreiben Zeilen.
* Der Kontextmenü-Worker `ServiceRunWorker` (Schritt 15) hatte die Persistenz+Emit-Logik bereits.

**C) Punkt 4 – Datum für Standalone Services & Plugins:**
* **`analytics/engine/service_selector_model.py`:** `build_tree()` liefert `"last_execution": self.last_execution_date(pid)` jetzt auch für die ⚡-Standalone-Gruppe und die 📦-Plugin-Gruppe (vorher nur in Service-Sets).
* **`serviceui/master_tree.py`:** `_build_plugin_item()` hängt das Datum an den Plugin-Namen (`proximity (02.08.26)`); Modul-Docstring ergänzt.

**D) Fallback-Konsistenz (doppelte Klammern behoben):** `last_execution_date()` liefert den Fallback als `--.--.--` OHNE Klammern; die Klammern setzt ausschließlich der MasterTree-Label-Aufbau (`Service_Name (DD.MM.JJ)` / `Service_Name (--.--.--)`) – vorher entstand `grid_1 ((--.--.--))`.

**E) `test/check_p15_s2_service_tree.py` (aktualisiert, gezielt ausgeführt):** J2 auf `--.--.--`-Fallback korrigiert; neue Checks J8/J9: Plugin-Zeile `proximity (DD.MM.JJ)` und `grid_lines (--.--.--)` (Standalone nutzt denselben `_build_plugin_item`-Pfad).

**Validierung (headless, grün):**
* **`test/check_p15_s2_service_tree.py` gezielt ausgeführt** (offscreen, Test-DBs in `test/`): **ALLE PRÜFUNGEN BESTANDEN** (inkl. J1–J9: Datum, Fallback, Set-Service-Labels, Plugin-Labels, Run-Signale).
* Echte DB-Verifikation: `fetch_last_execution_dates()` → `{'proximity': '02.08.26'}`; 670.235 proximity / 0 grid_lines / 3.000 NULL (atr-only); 0 proximity-Rows mit `feature_data` (Chart-Lesepfad unbeeinflusst).
* `python -m py_compile` auf allen geänderten Dateien (Exit 0); EventBus-Import in beiden Workern erfolgreich; `data/analytics.duckdb` ist gitignored (DB-Änderung wird über das Migrationsskript + Doku nachvollzogen).
* `docs/x_Exports.md` wurde vom Anwender selbst export-aktualisiert und bleibt wie immer unangetastet (nicht Bestandteil dieses Commits).

### 3.18 Schritt 18 – U15-E: Timeframe-Control & Multi-TF-Ausführung (05.08.2026)

**Anforderung (3 Teile, vom Anwender übergeben):**

1. **`analytics/features/definitions/grid_lines_service.py`** → echter FeatureStore-Payload mit `feature_id="grid_lines"`, `plugin_version` und Records je Bar (`bar_time`, `grid_nearest_level`, `grid_step`, `upper_level`, `lower_level`).
2. **`serviceui/service_win.py`** → neues Timeframe-Control `combo_tf` in der Filterleiste (neben dem Symbol-Dropdown) mit `'ALLE Timeframes'` (Index 0, Sentinel) + allen `get_timeframes()`-Werten (MN1..M1); Persistenz via `restore_state()`/`save_state()`.
3. **`serviceui/run_worker.py`** → Multi-TF-Loop: spezifischer Timeframe → einmal ausführen; `'ALLE Timeframes'` → ALLE Timeframes nacheinander (OHLCV laden, Abhängigkeiten auflösen, ausführen, je Timeframe speichern); `event_bus.service_set_changed` NUR EINMAL am Ende.

**Entscheidungen (Anwender-Frage 3; Fragen 1+2 wurden abgewählt → konservativ entschieden):** Die Kontextmenü-Run-Aktionen (`_start_run_worker`, `_on_run_service`, `_on_run_set`) lesen jetzt `combo_tf` (Filterleiste) statt `combo_tf_set`; `btn_execute_set`/`execute_set` (Set-Editor) bleibt unverändert auf `combo_tf_set`. Default-Auswahl `M1`. `upper_level = center + step_size`, `lower_level = center - step_size` (center = `f_round_to_custom_step(close, step_size)` = `grid_nearest_level`).

**A) `analytics/features/definitions/grid_lines_service.py` (1 Datei):**
* `capabilities["feature_store"] = True` (vorher `False` – GridLines rendert UND schreibt jetzt).
* `calculate()` erzeugt pro Bar einen Record `{bar_time (epoch), grid_nearest_level=center, grid_step=step_size, upper_level=round(center+step,6), lower_level=round(center-step,6)}` und liefert `feature_store_payload` mit `feature_id=self.plugin_id` (`"grid_lines"`), `plugin_version=self.version` (`"1.0.0"`) und `metadata{schema_version:"1.0.0", step_size}` – unabhängig von `show_lines` (das nur die Render-Darstellung steuert). `chart_render_payload` (lines/hit_circles) und `shared_state`-Namespace bleiben unverändert.

**B) `ui/service_win.ui` + `serviceui/service_win.py` (Filterleisten-Control):**
* **`ui/service_win.ui`:** In `layout_symbol` (zwischen `combo_symbol` und dem Spacer) `label_tf_filter` + `combo_tf` eingefügt (minWidth 150, Tooltip erklärt den Multi-TF-Modus, Default-Item `'ALLE Timeframes'`).
* **`serviceui/service_win.py`:**
  * Neues Attribut `self.combo_tf` (`findChild(QComboBox, "combo_tf")`).
  * `_refresh_timeframe_combo()`: füllt `'ALLE Timeframes'` (Index 0, Sentinel `ALL_TIMEFRAMES`) + `get_timeframes()`-Keys (Fallback `TF_SECONDS_MAP`, letzter Fallback Basisliste); aktuelle Auswahl bleibt erhalten, Default `M1`; blockSignals-geschützt. Aufruf im `__init__` nach `_refresh_symbol_combo()`.
  * `combo_tf.currentTextChanged` → `save_state` (sofortiges Persistieren wie bei `combo_symbol`).
  * `get_persistent_timeframe()` liest jetzt `combo_tf` (inkl. Sentinel 1:1 – `'ALLE Timeframes'` ist eine reguläre, persistierbare Auswahl); Fallback `"H1"`.
  * `_apply_persistent_filters()` stellt zusätzlich `combo_tf` wieder her (`findText`, inkl. Sentinel).
  * `_start_run_worker`, `_on_run_service`, `_on_run_set`: Timeframe aus `combo_tf` statt `combo_tf_set` (die `QMessageBox.question`-Bestätigungen zeigen den gewählten Timeframe bzw. den Multi-TF-Modus).

**C) `serviceui/run_worker.py` (Multi-TF-Worker):**
* Neue Konstante `ALL_TIMEFRAMES = "ALLE Timeframes"` (Sentinel).
* `_resolve_timeframes()`: spezifischer TF → `[tf]`; `ALL_TIMEFRAMES` → `list(get_timeframes().keys())` (Fallback `TF_SECONDS_MAP`, letzter Fallback Basisliste MN1..M1).
* `_execute_timeframe(fb, settings, definition, scope_label, tf)`: OHLCV laden → `prepare_plugin_df` → `PluginContext(symbol, tf, mode="batch")` → `evaluator.execute_set()` → non-leere `feature_store_payloads` via `fb.store_plugin_payload(symbol, tf, payload)` (Timeframe im Schreibpfad); liefert Anzahl geschriebener Rows, überspringt leere OHLCV-Daten mit Log.
* `run()`: Loop über die aufgelösten Timeframes; im Multi-TF-Modus bricht ein fehlgeschlagener Timeframe die Gesamt-Ausführung NICHT ab (Fehler wird geloggt, Rest läuft weiter); Summe der Rows in `run_finished`; `event_bus.service_set_changed.emit()` NUR EINMAL nach Abschluss aller Timeframes. Single-TF ohne Daten → `run_failed` (bisheriges Verhalten unverändert).

**Validierung (headless, grün):**
* `python -m py_compile` auf `serviceui/service_win.py`, `serviceui/run_worker.py` (Exit 0); `ui/service_win.ui` parst als XML (Exit 0).
* `test/test.py` Teil 6 (U1–U13) + Teil 6.4 (U14–U18), offscreen auf Test-DBs isoliert, **ALLE PRÜFUNGEN BESTANDEN**: `combo_tf` existiert in der Filterleiste, Index 0 = Sentinel, alle Timeframes enthalten, Default `M1`; Persistenz/Restore des Sentinel-Modus (`get_persistent_timeframe`/`save_state`/`restore_state`); `_resolve_timeframes()` Single vs. ALL (Reihenfolge = `get_timeframes()`); Multi-TF-`run()`-Schleife mit Fake-FeatureBuilder/-Evaluator (M1+H1 gespeichert, M30 ohne Daten übersprungen, Rows summiert, genau 1× `run_finished`, kein `run_failed`; Single-TF mit Daten → `run_finished`, Single-TF ohne Daten → `run_failed`); Grid-Level-Mathematik (close 30.1 / step 0.5 → center 30.0, upper 30.5, lower 29.5).
* Zeilenenden: `.ui` auf LF normalisiert (Repo-Konvention für `*.ui`); git-Diff minimal (25 Insertions im `.ui`).

### 3.19 Schritt 19 – Service-Run-Bugfixes: depends_on-Auflösung & Scanner-Candles-Lookback (05.08.2026)

**Anforderung (2 Bugs, vom Anwender übergeben):**

1. **"ausführen service proximity" → Log "fertig (kein Feature-Store-Payload)"**: UI-angelegte Service-Sets speichern KEIN `depends_on`; `ProximityService.calculate()` liest die Linienliste aber ausschließlich aus `context.shared_state[depends_on[0]]` → leerer Payload. Der Indikator-interne Pfad (`_build_set_definition` in `chart/indicators/grid_liquidity.py`) setzt `depends_on` korrekt, die UI-Pfade (`_build_new_set_definition`, `add_instance`, `collect_set_definition` in `serviceui/service_win.py`) nicht.
2. **"grid_lines: 1000 Feature-Row(s) gespeichert" → sollen Scanner-Candles (max) aus den App-Optionen als max Lookback für alle Services verwendet werden**: Die Worker luden OHLCV mit `limit=feature_builder_limit` (3000) und die Services liefen mit ihrem gespeicherten `lookback` (z. B. 1000).

**Entscheidungen:** (a) Die implizite Abhängigkeit wird anhand der Plugin-Deklaration `PluginFeature.dependencies` aufgelöst (nächste VORHERIGE Instanz in `execution_order` mit passender plugin_id) – explizit gesetzte `depends_on` (Indikator-intern `grid_1` → `prox_1`) bleiben unverändert. Kein Hardcoding von Set-IDs/Instanz-Namen in zentralen Repositories (OOP-Regel: keine `if name == ...`-Checks). (b) `scanner_candle_limit` (Properties-Fenster "Scanner Candles (max)", `config/app_settings.py`, Default 100.000) ist die Datenbasis für ALLE Services (gleiche Datenmenge wie der Historical Scanner); die Service-`lookback`-Werte werden beim Worker-Run überschrieben.

**A) `analytics/features/definitions/proximity_service.py`:** Neue Property `dependencies` → `["grid_lines"]` (deklarative Upstream-Semantik über den bestehenden `PluginFeature.dependencies`-Vertrag; dient hier als Info für die Worker-Auflösung).

**B) `serviceui/service_set_utils.py`:** Neue Funktion `prepare_worker_definition(definition, lookback_limit)` (arbeitet auf einer Kopie, Original bleibt unverändert):
* Fehlende `depends_on` automatisch auflösen: Service ohne `depends_on`, dessen Plugin `dependencies` deklariert (z. B. proximity → `['grid_lines']`), erhält die nächstliegende VORHERIGE Instanz in `execution_order` mit passender `plugin_id` als `depends_on`. Explizite Werte werden NIE überschrieben.
* Lookback-Override: jede Service-Instanz läuft mit `lookback_limit` (= `scanner_candle_limit`).

**C) `serviceui/run_worker.py` + `serviceui/set_run_worker.py`:** Beide Worker rufen `prepare_worker_definition(definition, settings.scanner_candle_limit)` vor `evaluator.execute_set()` auf und laden OHLCV mit `limit=settings.scanner_candle_limit` statt `feature_builder_limit`.

**D) Folge-Fix 1 (vorbestehend, durch Runde-1-Verifikation sichtbar geworden): `chart/indicators/grid_liquidity.py`** – `_colorize()` ergänzt jetzt `priority=10`: der Pipeline-Fallback (`prox_crp.hit_circles` aus dem ProximityService) lieferte Kreise OHNE `priority` (nur time/price/in_window); der Feature-Store-Lesepfad und die Live-Punkte setzten `priority=10` bereits. Beide Pfade sind damit konsistent (ChartCircle-Vertrag, `base_plugin.py`).

**E) Folge-Fix 2 (vorbestehend): `chart/indicator_dialog.py`** – `meta = dict(getattr(plugin, "metadata", None) or {})` statt `dict(plugin.metadata or {})`: `_get_plugin()` Branch 1 kann einen Indikator liefern, der `parameter_schema`+`plugin_id` implementiert, ohne `PluginFeature` zu sein (z. B. `GridLiquidityIndicator`, ein `BaseIndicator`) → kein `metadata`-Attribut. Der getattr-Guard verhindert den `AttributeError` im Experten-Optionen-Bereich.

**Zusätzlich committete Vorrunden-Änderungen (derselbe Arbeitsstrom, 05.08.2026):**
* `analytics/features/feature_builder.py`: `store_plugin_payload()` setzt `created_at = now()` statt `current_timestamp` im `ON CONFLICT DO UPDATE SET` (DuckDB 1.5.5 bindet lowercase `current_timestamp` dort als SPALTENREFERENZ → Binder Error; verifiziert in `test/check_current_timestamp.py`).
* `serviceui/service_win.py` `_refresh_timeframe_combo()`: Timeframes AUFSTEIGEND nach Dauer sortiert (M1..MN1 via `TF_SECONDS_MAP`, kürzeste zuerst) – identische Reihenfolge wie im chart_win; Fallback-Liste auf alle 11 Timeframes erweitert.
* `ui/service_win.ui` `combo_tf_set`: M2, M10, W1, MN1 ergänzt (alle 11 Timeframes).

**Validierung (headless, grün):**
* `python -m py_compile` auf allen geänderten Dateien (Exit 0).
* **Neu `test/check_service_run_fixes.py`** (headless, in `test/`): ProximityService.dependencies == `['grid_lines']`; `prepare_worker_definition()` löst implizites `depends_on` auf (UI-Set ohne depends_on → proximity erhält `['grid_lines']`), überschreibt Lookback auf `scanner_candle_limit`, lässt explizites depends_on unangetastet; End-to-End-Evaluator liefert proximity-Feature-Rows mit `metadata.depends_on`; Code-Inspektion: beide Worker nutzen `scanner_candle_limit` + `prepare_worker_definition`. **ALLE CHECKS BESTANDEN.**
* `test/test.py` (designierte Verifikation, offscreen isoliert, inkl. Worker-Loop U14–U18): **ALLE PRÜFUNGEN BESTANDEN**.
* `test/check_p13_proximity_cleanup.py` (vorher FAIL durch vorbestehenden `priority`-Crash, jetzt nach Folge-Fix 1+2 EXIT 0): **ALLE CHECKS BESTANDEN** – inkl. Prop-Fenster-Headless (kein `AttributeError: metadata`).
* `test/check_plugin_batch_services.py`, `test/check_p13_s3.py`: **ALLE CHECKS BESTANDEN** (Scanner-/Evaluator-Pfad unverändert grün).
* `docs/x_Exports.md` wurde vom Anwender selbst export-aktualisiert und bleibt wie immer unangetastet (nicht Bestandteil dieses Commits).

### 3.20 Schritt 20 – P16: Service-Beschreibungs-Editor, Numpy-Vektorisierung & Sync-Guard (05.08.2026, Commit `1ae1a0e`)

**Anlass (vom Anwender übergeben – „Service-Beschreibungs-Editor & Vektorisierung & Sync-Guard"):**

**A) Modaler Beschreibungs-Editor (`analytics/engine/description_dialog.py` + `serviceui/param_columns.py` + `serviceui/service_win.py`):**
* **NEU `ServiceDescriptionEditDialog`** (modales QTextEdit-Fenster, Phase 16): reines UI-Widget mit `save_requested(str)`-Signal (IoC – kein Repo-/EventBus-Zugriff im Dialog). Kopfzeile aus `header_line` (z. B. `aktiv/im <Indikator>`) + Instanz-/Plugin-ID.
* MasterTree-Info-Button öffnet für **Service- und Set-Zeilen** den Editor (editierbar); **Plugin-/Standalone-Zeilen bleiben bewusst Read-Only** (`ServiceDescriptionDialog`, keine Plugin-Beschreibungen im Service Window – Phase-16-Design).
* Stift-Icon (`✏️`) im Parameter-Panel (`serviceui/param_columns.py`) öffnet denselben Editor für die Instanz-Beschreibung.
* Persistenz: `_save_instance_description()` / `_save_set_description()` schreiben ausschließlich in `definition['services'][iid]['description']` bzw. `definition['description']` (via `ServiceSetRepository.save_set()` + `event_bus.service_set_changed`); Editor-Spalte + Tooltip werden live aktualisiert.

**B) Numpy-Vektorisierung der Service-Berechnungen (`grid_lines_service.py`, `proximity_service.py`):**
* O(n·m)-Double-Loops durch Broadcasting/Maskierung ersetzt (inkl. vektorisiertes `_bar_utc_minutes`).
* Gemessen: 10k Lookback-Bars – Proximity ~25 ms, grid_lines ~12 ms (vorher mehrere Sekunden).
* Exakte Output-Parität zur Alt-Loop (Paritätstest in `test/test.py`, V1–V9).

**C) Concurrency-Guard gegen den 45s-Hintergrund-Sync (`config/event_bus.py`, `main.py`, `serviceui/service_win.py`):**
* Neue EventBus-Signale `service_run_started` / `service_run_finished`.
* `ServiceWindow._begin_sync_guard()` / `_end_sync_guard()` (Referenzzähler, Übergang 0→1 bzw. 1→0) blocken den `sync_timer` in `main.py`, während `SetRunWorker`/`ServiceRunWorker`/`HistoricalScanner` laufen.

**Validierung (headless, grün):**
* `test/test.py` Teil 7: D1–D3 (Editor + save_requested), S1–S8 (Sync-Guard), V1–V11 (Vektorisierungs-Parität + Performance < 1 s bei 10k Bars) – **ALLE PRÜFUNGEN BESTANDEN**.

### 3.21 Schritt 21 – Performance-Fix: Bulk-Insert statt `executemany` in `store_plugin_payload` (05.08.2026)

**Anlass (vom Anwender übergeben – „ausführen Service grid_lines auf D1 dauert viel zu lang"):** Die numpy-Vektorisierung aus Schritt 20 (P16) war aktiv und schnell (grid_lines 10k ≈ 9 ms, 100k ≈ 102 ms) – der eigentliche Engpass lag im DB-Schreibpfad.

**Ursache:** `FeatureBuilder.store_plugin_payload()` schrieb pro Bar einen einzelnen parameterisierten INSERT via `con.executemany(...)` → O(n) Round-Trips. Gemessen: **8.000 D1-Bars ≈ 20 s**, **100.000 Bars ≈ mehrere Minuten** (allein der Schreibpfad).

**Fix (`analytics/features/feature_builder.py`):** Ersetzt durch Bulk-DataFrame-Insert (`con.register("df_temp", df)` + `INSERT … SELECT … FROM df_temp ON CONFLICT … DO UPDATE`), identische Upsert-Semantik (`feature_id`/`plugin_version`/`feature_data`/`created_at = now()`).

**Messwerte nach Fix:**
| Bars | vorher | nachher |
| --- | --- | --- |
| 8.000 (D1) | ~20 s | **~104 ms** (~190×) |
| 100.000 (M1) | mehrere Minuten | **~675 ms** (~380×) |

**Validierung (headless, grün):**
* `python -m py_compile analytics/features/feature_builder.py` (Exit 0).
* `test/test.py` (designierte Verifikation, offscreen auf Test-DBs isoliert): **ALLE PRÜFUNGEN BESTANDEN** (inkl. V1–V11 Paritäts-/Performance-Checks, D1–D3 Editor, S1–S8 Sync-Guard).
* **Hinweis (Betrieb):** Während der Verifikation hängengebliebene Offscreen-Dialog-Prozesse hielten die DuckDB-Locks (`IO Error: … wird von einem anderen Prozess verwendet` – App-Start fehlgeschlagen). Nach Beenden der hängenden Prozesse (PID 1864/30332) waren `app_data`/`analytics`/`market_data.duckdb` wieder lesbar und der App-Start funktionierte. Künftige Dialog-Verifikationen patchen `QDialog.exec` (sofortiger Return), damit sich keine modalen Dialoge im Offscreen-Modus aufhängen.
* `docs/x_Exports.md` wurde vom Anwender selbst export-aktualisiert und bleibt wie immer unangetastet (nicht Bestandteil dieses Commits).

### 3.22 Schritt 22 - Bugfix: Plugin-/Standalone-Info-Button nutzt denselben Beschreibungs-Editor wie Einzel-Services (05.08.2026, Commit `0ab1bde`)

**Anlass (vom Anwender übergeben - "info button hinter Services in Plugin oder standalone: noch die alte Methode, bitte genau so umstellen wie bei den einzelservices in den sets"):** Der Info-Button (Spalte 1 des MasterTree) auf Plugin-Zeilen in den Gruppen ⚡ Standalone Services und 📦 Alle verfügbaren Plugins öffnete noch den alten Read-Only-Dialog (`ServiceDescriptionDialog`), während die Einzel-Services in den Sets bereits den neuen editierbaren `ServiceDescriptionEditDialog` nutzten (P16 3.20 hatte Plugin-Zeilen bewusst ausgenommen - Read-Only-Design, keine Plugin-Beschreibungen im Service Window).

**Fix (`serviceui/service_win.py`, `_on_tree_info_requested` Fall 2):**
* Plugin-/Standalone-Zeilen öffnen jetzt **denselben `ServiceDescriptionEditDialog`** wie die Einzel-Services der Sets (gleicher Titel "Service-Beschreibung bearbeiten", gleiche `header_line`-Logik via `_info_header_tooltip`).
* Der Editor wird mit der **Plugin-Metadaten-Beschreibung** vorbefüllt (`metadata['description']`).
* **Kein `save_requested`-Anschluss:** Ein Plugin ohne Instanz/Set hat kein Persistenz-Ziel (persistierbar sind nur Instanz- und Set-Beschreibung) - Speichern/Abbrechen schließen den Dialog konsistent, es wird nichts geschrieben.
* Docstring entsprechend aktualisiert (Plugin-Zeile als editierbar dokumentiert).

**Validierung (headless, grün):**
* `python -m py_compile serviceui/service_win.py` (Exit 0).
* Import `ServiceDescriptionDialog` bleibt gültig (weiterhin in `_show_service_info` für die markierte Instanz der execution_order-Liste genutzt).
* Manueller UI-Test durch den Anwender: ℹ-Button auf Standalone-/Plugin-Zeile → Editor-Dialog erscheint (gleiches Verhalten wie Einzel-Services).
* `docs/x_Exports.md` bleibt unangetastet (Nutzer-Export, nicht Bestandteil des Commits).


### 3.23 Schritt 23 - Papierkorb-Integration & Kontextmenue-Verknuepfung im ServiceWindow (05.08.2026)

**Anlass (vom Anwender uebergeben - 'Papierkorb-Integration & Kontextmenue-Verknuepfung im ServiceWindow (Phase 15)'):** Die Papierkorb-Funktionalitaet (P14-05 Soft-Delete) war bereits vorhanden (Button in `layout_set_actions`, Dialog als `QListWidget`), wurde aber um drei Punkte erweitert: (1) Button-Platzierung in der oberen Aktionsleiste, (2) Anzeige/Sortierung/Buttons im `TrashDialog`, (3) Kontextmenue-Eintrag im `MasterTree`. In der Folge-Runde (Bugfixing-Modus) wurden zusaetzlich die doppelte Nachfrage beim Set-Loeschen (kein zweites Mal noetig, da Papierkorb), die Gleichheits-Pruefung der beiden Loesch-Buttons und die Datumsspalte im Papierkorb behandelt.

**Entscheidungen:**
* **Button 'Endgueltig Loeschen' vs. 'Papierkorb leeren':** NICHT identisch - `_purge_selected()` loescht NUR das selektierte Set (`purge_trash_set(set_id)`), `_purge_all()` loescht ALLE (`purge_trash()`). Beide bleiben erhalten; nur im 1-Zeilen-Fall wirken sie gleich. Button 'Endgueltig Loeschen' wurde auf Wunsch in **'Loeschen'** umbenannt.
* **Loesch-Nachfrage im Tree:** Da Service-Sets soft-deleted werden (Papierkorb), genuegt EINE Nachfrage ('Set in den Papierkorb verschieben'). Die zweite Rueckfrage aus der generischen Preset-Mechanik entfaellt.
* **Datumsformat:** `E. DD.MM.JJ HH:MM` (z.B. `Sa. 04.07.26 14:34`), eigene Spalte 'Geloescht am' GANZ VORN; Sortierung ABSTEIGEND (neueste zuerst).

**A) `ui/service_win.ui` + `serviceui/service_win.py` (Button-Platzierung):**
* `ui/service_win.ui`: `btn_trash_sets` aus `layout_set_actions` (neben Speichern/Loeschen) **entfernt** und in `layout_symbol` **direkt rechts neben `check_new_scan`** (`[New Scan]`) eingefuegt; Text **'🗑️ Papierkorb'** (Tooltip P14-05 unveraendert). Die bestehende Verdrahtung `btn_trash_sets.clicked -> show_trash_dialog()` (modales `exec_()`, Esc/X schliessen nativ) greift unveraendert.

**B) `serviceui/trash_dialog.py` (Anzeige, Datum, Buttons, EventBus):**
* **QTableWidget statt QListWidget:** Spalte 0 (ganz vorn) 'Geloescht am' (Format `E. DD.MM.JJ HH:MM` via `_format_deleted_at()`), Spalte 1 nur der Name des geloeschten Objekts (Datums-Anhang hinter dem Namen entfernt). Zeilenauswahl (SelectRows/SingleSelection, NoEditTriggers), Spalte 0 ResizeToContents, Spalte 1 Stretch.
* **Sortierung:** `_reload()` sortiert die `list_trash()`-Daten ABSTEIGEND nach `deleted_at` (neueste zuerst) ueber `_deleted_at_sort_key()` (robust fuer datetime / ISO-Strings mit/ohne Z / None / unparsebare Werte -> `datetime.min`).
* Button **'Endgueltig Loeschen' -> 'Loeschen'** (Wunsch Anwender).
* **EventBus-Emit nach endgueltigem Loeschen (`purge_trash_set`) UND Leeren (`purge_trash`)** ergaenzt -> MasterTree + Dropdowns synchronisieren live (Restore-Emit war bereits vorhanden). Doppelte Sicherheitsabfrage fuer beide Loesch-Aktionen bleibt unveraendert (P14-05).

**C) `serviceui/master_tree.py` + `serviceui/service_win.py` (Kontextmenue):**
* Neues Signal `open_trash_requested = Signal()` im `MasterTree`.
* Gruppen-Kontextmenue **'📁 Service-Sets'**: nach 'Neues Set anlegen' (mit Separator) neuer Eintrag **'🗑️ Papierkorb öffnen...'** -> emittiert `open_trash_requested`.
* `_wire_selector_toolbar()`: `tree.open_trash_requested -> self.show_trash_dialog()` - dieselbe Methode wie der Aktionsleisten-Button.

**D) `chart/widgets/named_item_actions.py` + `serviceui/service_win.py` (eine Nachfrage statt zwei):**
* `delete_named_item(adapter, confirm: bool = True)`: neuer Parameter - `confirm=False` ueberspringt die Rueckfrage. Default `True` unveraendert (Presets im `indicator_dialog.py` behalten ihre Rueckfrage).
* `ServiceWindow.delete_set()` ruft `delete_named_item(self._set_adapter, confirm=False)` - es bleibt NUR die erste Nachfrage ('Set in den Papierkorb verschieben', Soft-Delete).

**Validierung (headless, gruen):**
* `python -m py_compile` auf `chart/widgets/named_item_actions.py`, `serviceui/master_tree.py`, `serviceui/service_win.py`, `serviceui/trash_dialog.py` (Exit 0); `ui/service_win.ui` parst als XML (Exit 0).
* Isolierte Logik-Checks in `test/` (temporaere Skripte, danach geloescht): `_format_deleted_at` (datetime/ISO/None/Rohwert -> `Sa. 04.07.26 14:34`, `Mo. 06.07.26 14:34`, leerer String, Rohwert), `_deleted_at_sort_key` (absteigend: neueste zuerst, None/unparsebar = aelteste, stabile Reihenfolge) - **ALLE PASS**.
* Keine UI-Tests (Regel). Keine externen Referenzen auf das alte `trash_list`-Attribut (findstr-Check).
* `docs/x_Exports.md` wurde vom Anwender selbst export-aktualisiert und bleibt wie immer unangetastet (nicht Bestandteil dieses Commits).

### 3.24 Schritt 24 - ParameterPanel Dirty-State ('*') + Speichern & Direct-Run Integration (05.08.2026)

**Umsetzung (Phase 15 Dirty-State):** Parameter-Aenderungen in den dynamischen Service-Spalten markieren die Service-Instanz im MasterTree als ungespeichert ('*' am Knoten, Format `Service_Name* (DD.MM.JJ)`) und aktivieren eine Aktionsleiste unter der Parameter-Box mit `[💾 Speichern]` und `[▶️ Speichern & Ausführen]`.

**A) `serviceui/param_columns.py` (Dirty-Tracking):**
* `_connect_param_change(ctrl, iid, key)`: verbindet das Aenderungs-Signal jedes Parameter-Controls (QCheckBox -> `toggled`, QSpinBox/QDoubleSpinBox -> `valueChanged`, QComboBox -> `currentTextChanged`, QLineEdit -> `textChanged`) mit `_on_param_changed`.
* `_on_param_changed(iid, key)`: aktualisiert die RAM-`_current_set_definition` (lookback -> Instanz-Ebene, alle anderen -> `params`) und ruft `_mark_service_dirty(iid)`.
* `_mark_service_dirty(iid)`: delegiert an `service_selector.master_tree.set_instance_dirty(iid, True)`.
* Auch die Instanz-Beschreibung (desc_edit) markiert dirty (`textChanged`).

**B) `serviceui/master_tree.py` (Dirty-Marker):**
* `_dirty_instance_ids` (RAM-Set) + `set_instance_dirty()` / `clear_dirty_markers()` / `_apply_dirty_label()` (Format `Service_Name* (DD.MM.JJ)`, Ausfuehrungsdatum bleibt erhalten).
* Re-Apply nach `_populate()` (Baum-Neuaufbau via `data_changed` verliert die Sternchen nicht).

**C) `serviceui/service_win.py` (Aktionsleiste & Handler):**
* `_param_action_row` (QHBoxLayout) mit `btn_save_params` + `btn_save_run_params` am Ende des `editor_layout` (unter `widget_service_columns`).
* `_save_params_from_panel()`: `collect_set_definition()` -> `set_repo.save_set()` -> `_clear_dirty_markers()` -> EventBus `service_set_changed` (ohne Neuberechnung).
* `_save_and_run_from_panel()`: speichert zusaetzlich und stoesst nach Bestaetigungsabfrage (Symbol/Timeframe aus der Filterleiste, inkl. Sentinel 'ALLE Timeframes') den gezielten `ServiceRunWorker` an (`_start_run_worker`, kein Massen-Scan).
* `_clear_dirty_markers()` zentral; wird auch nach Instanz-/Set-Beschreibungs-Speicherung und beim Set-Wechsel (`_clear_set_editor`/`load_set_into_editor`) aufgerufen.

**Bugfix-Runde (Anwender-Feedback, 3 Punkte):** (1) keine sichtbare Markierung, (2) Buttons unsichtbar, (3) Buttons muessen direkt unter der Parameter-Box liegen.

**Root-Cause (Kern-Bug):** In `_build_service_columns()` (`param_columns.py`) war ein Reinsert-Ueberbleibsel aus dem Alt-Layout (vor dem 15.02-Splitter-Refactoring, Commit `afe4483`) aktiv: `top_row.removeWidget(widget_service_columns) + top_row.addWidget(...)`. Das verschob die Parameter-Box bei JEDEM Spaltenaufbau AUS dem Editor-Panel in die `top_row` NEBEN den Splitter - die Speichern-Buttons lagen dadurch isoliert am Panel-Ende (NICHT unter der Parameter-Box).

**Fix:** Der Reinsert laeuft jetzt in das `_editor_panel` (frisches QWidgetItem gegen den Qt-6.11-QWidgetItemV2-Cache, gleicher Mechanismus wie zuvor) - die Box wird unmittelbar vor der `_param_action_row` eingefuegt (defensiv: erst aus der `top_row` entfernen, falls sie durch fruehere Builds dort gelandet ist). Der Dirty-Flow selbst war korrekt (RAM-Update + Tree-Label), nur die sichtbare Zuordnung stimmte nicht.

**Validierung (headless, gruen):**
* `python -m py_compile` auf `serviceui/param_columns.py`, `serviceui/master_tree.py`, `serviceui/service_win.py` (Exit 0).
* Echte `ServiceWindow`-Instanz (offscreen, Test-DB in `test/`): Parameter-Box jetzt im Editor-Panel `(0, 403)` ueber den Buttons (vorher `(989, 63)` = top_row neben dem Splitter); `btn_save_params.isVisible() == True`; Button direkt unter der Param-Box (`True`); End-to-End Dirty-Flow (echte QDoubleSpinBox-Aenderung -> RAM `params['visit_pct']: 1.05` + Tree-Label `prox_1*`) PASS.
* MasterTree-Dirty-Marker-Isolationscheck: `prox_1 (05.08.26)` -> dirty -> `prox_1* (05.08.26)` -> nach `_populate()` erhalten -> nach Clean -> `prox_1 (05.08.26)` - ALLE PASS.
* Temporaere Testdateien (`tmp_check_*.py`, `tmp_app_data.duckdb`) danach geloescht (Regel: Tests nur in `test/`).
* Keine UI-Tests (Regel). Manuelle UI-Verifikation durch den Anwender.
* `docs/x_Exports.md` bleibt unangetastet (Nutzer-Export, nicht Bestandteil dieses Commits).


### 3.25 Schritt 25 - Layout-Runde 2: Drei-Spalten-Splitter & Button-Sichtbarkeit (05.08.2026)

**Anlass (vom Anwender uebergeben - 6-Punkte-Bugfix fuer das ServiceWindow-Layout, danach 3-Punkte-Runde zur Button-Sichtbarkeit):** Nach der Dirty-State-Aktionsleiste (3.24) meldete der Anwender sechs Layout-Probleme: (1) text_log klebt am unteren Bildschirmrand (waechst unbegrenzt), (2) die beiden Service-Parameter-Spalten bekommen zu wenig Breite, (3) die Status-Zeile muss unter der hoechsten Box liegen, (4) der MasterTree braucht eine Mindest-Breite mit nativem Scrollbalken, (5) die Parameter-Box soll max. Hoehe/Breite mit Scrollbalken haben, (6) die Speichern-Buttons der Parameter-Spalte muessen IMMER sichtbar sein. In der Folge-Runde (Bugfixing-Modus) wurde die Sichtbarkeit praezisiert: Die Buttons sind NUR bei manueller Parameter-Aenderung (Dirty) sichtbar - initial versteckt, bei Aenderung eingeblendet, nach Speichern/Set-Wechsel ausgeblendet.

**Entscheidungen:**
* **DREI-SPALTEN-Splitter statt zwei:** Spalte 1 = Set-Editor-Box (Service-Sets), Spalte 2 = MasterTree (Service tree), Spalte 3 = Service-Parameter-Box + feste Aktions-Leiste. Die Status-Zeile bleibt im central_layout direkt UNTER dem Splitter (= unter der hoechsten Box, Punkt 3).
* **Kein Reinsert mehr:** Der in 3.24 reparierte Reinsert (`_build_service_columns` -> Editor-Panel) entfaellt vollstaendig - die Parameter-Box liegt seit dieser Runde FEST in einer ContentScrollArea der rechten Splitter-Spalte und wird nie mehr verschoben (Qt-6.11-QWidgetItemV2-Cache wird stattdessen ueber `updateGeometry()` invalidiert).
* **QSplitter-fixiert-Sizes-Quirk:** Der QSplitter fixiert die Spaltengroessen beim addWidget (VOR dem Spaltenaufbau) und aktualisiert sie nicht, wenn die sizeHints danach wachsen. Daher setzt der deferred Spaltenaufbau die Param-Spalte NACH dem Aufbau explizit auf ihre aktuelle Layout-Breite (`splitter.setSizes(hints)`) - nur so passen 2 Service-Spalten ohne horizontalen Scroll.

**A) `serviceui/service_win.py` (Orchestrator, 3-Spalten-Splitter):**
* **Punkt 1:** `self.text_log.setMaximumHeight(120)` (~5 Zeilen) - das QTextEdit scrollt intern, kein Bildschirmrand-Kleben mehr.
* **Spalte 1 (`_editor_panel`):** nur noch `group_service_sets`; `setMinimumWidth(380)`, `setMaximumWidth(700)`.
* **Spalte 2 (`right_panel`):** `ServiceSelectorWidget` (MODE_FULL_EDIT) wie bisher; `master_tree.setMinimumWidth(400)` + `setMaximumWidth(560)` (Punkt 4 - eingerueckte Texte lesbar, native Scrollbalken bei Ueberlauf).
* **Spalte 3 (`_param_panel`, min 320):** `_param_scroll` (ContentScrollArea, `widgetResizable=False`, max. Hoehe 620 / max. Breite 1000) mit `widget_service_columns`; DARUNTER fest (ausserhalb der ScrollArea, Punkt 0) die `_param_action_row` mit [Speichern] / [Speichern & Ausfuehren].
* **Splitter:** `Stretch (0:2, 1:3, 2:2)`, alle `setCollapsible(False)` (keine Spalte unter Mindestgroesse).

**B) `serviceui/param_columns.py` (Spaltenaufbau + deferred Resize, Punkt 5):**
* `_build_service_columns`: KEIN Reinsert mehr; nach dem Spaltenaufbau nur `updateGeometry()` auf Box und Scroll.
* `_reflow()`: stoesst zusaetzlich `QTimer.singleShot(0, self._resize_param_box_deferred)` an.
* `_resize_param_box_deferred` (neu): sendet zuerst die DeferredDelete-Events (sonst liest `layout().sizeHint()` den veralteten 18x18-QWidgetItemV2-sizeHint der gerade geleerten Alt-Spalten -> Box wuerde schrumpfen), dann `box.resize(box.layout().sizeHint())`, `scroll.updateGeometry()` und `splitter.setSizes(hints)` aus den aktuellen sizeHint-Breiten der 3 Spalten (Qt-Quirk-Fix, damit 2 Service-Spalten ohne hscroll passen; bei mehr Spalten scrollt die ScrollArea).

**C) Button-Sichtbarkeit (Punkt 2/3 der Folge-Runde):**
* `btn_save_params` / `btn_save_run_params` initial `setVisible(False)`.
* `_mark_service_dirty` (param_columns) blendet beide ein via `self._set_param_actions_visible(True)` (try/except-guarded).
* `_clear_dirty_markers` blendet beide aus (`_set_param_actions_visible(False)`).
* `_on_master_selection` (MasterTree-Klick) und `_on_order_item_clicked` (Ausfuehrungs-Liste) blenden die Buttons beim Set-/Service-Wechsel aus.
* `_set_param_actions_visible(visible)` (neu, Orchestrator): setVisible auf beide Buttons, try/except gegen RuntimeError/AttributeError.

**Validierung (headless, gruen):**
* `python -m py_compile` auf `serviceui/service_win.py` und `serviceui/param_columns.py` (Exit 0).
* Echte `ServiceWindow`-Instanz (offscreen, Test-DB in `test/`): 1920-FakeScreen -> Splitter-Hints [700, 403, 961], Param-Spalte 961px, Box 948px, hscroll=0; 3 Services -> hscroll=418 aktiv (ScrollArea scrollt). Button-Test (`tmp_btn_visibility.py`, 11/11 PASS): initial unsichtbar -> nach Param-Aenderung sichtbar + '*' am Knoten -> nach Set-Wechsel unsichtbar -> wieder sichtbar (prox_2 dirty) -> nach Service-Klick unsichtbar -> maxW=1000.
* Temporaere Testdateien (`tmp_btn_visibility.py`, `tmp_app_data.duckdb`, `tmp_layout_audit.py`) danach geloescht (Regel: Tests nur in `test/`).
* Keine UI-Tests (Regel). Manuelle UI-Verifikation durch den Anwender.
* `docs/x_Exports.md` bleibt unangetastet (Nutzer-Export, nicht Bestandteil dieses Commits).


### 3.26 Schritt 26 - Phase-13-Box-Bereinigung, 2-Spalten-Splitter & Layout-Bugfixes; New-Scan-Alt-Verdrahtung entfernt (05.08.2026, Commit `7f3d224`)

**Anlass (vom Anwender uebergeben - zwei Aufgaben gemeinsam umgesetzt):** (1) Die Phase-13-Box (`group_service_sets`-Set-Editor-Spalte) wird aus dem ServiceWindow entfernt - die rechte Splitter-Spalte zeigt seitdem nur noch MasterTree + Parameter-Box (2-Spalten-Layout). Hot-Reload-Button `btn_reload_plugins` entfaellt bewusst; `execute_set`/`combo_tf_set`/`ServiceSetRunWorker` werden entfernt (Kontextmenue-Run ist alleiniger Ausfuehrungspfad). (2) Zwei Layout-Bugfixes: die Parameter-Box soll zwei Services ohne horizontalen Scrollbalken anzeigen (Bugfix 1) und die Fensterbreite soll etwas mehr sein als Tree- + Box-Breite zusammen (Bugfix 2). Dazu wird die Alt-Verdrahtung des globalen `HistoricalScanner` (Button `btn_start_scan`, Checkbox `check_new_scan`, Status-Zeile mit Laufzeit/Fortschritt) ersatzlos entfernt - die Ausfuehrung erfolgt nur noch ueber das MasterTree-Kontextmenue.

**Entscheidungen:**
* **2-Spalten-Splitter statt 3-Spalten:** Der Set-Editor (`group_service_sets`) entfaellt als Spalte; der Splitter haelt nur noch MasterTree (links) | Parameter-Box (rechts). Die rechte Spalte zeigt weiterhin ALLE Services des Sets (Lazy-Load, `param_columns.py` bleibt bestehen - Option A der Rueckfrage).
* **Hot-Reload-Button entfaellt:** `btn_reload_plugins` wird nicht ersetzt; Plugin-Reload bleibt Entwickler-Thema.
* **EIN Ausfuehrungspfad:** `execute_set`/`combo_tf_set`/`ServiceSetRunWorker` werden entfernt; der Kontextmenue-Run (`ServiceRunWorker` + `combo_tf` inkl. "ALLE Timeframes") ist alleiniger Weg.
* **New-Scan ersatzlos entfernt (Option B):** `check_new_scan`, `btn_start_scan` und die Status-Zeile (`label_elapsed`/`progress_bar`) entfallen komplett; `HistoricalScanner` wird nicht mehr im ServiceWindow instanziiert. Die Scanner-Klasse selbst (`scanner/historical_scanner.py`) und `serviceui/status_panel.py` (separate, ungenutzte Komponente) bleiben unangetastet.

**A) Phase-13-Box-Bereinigung (`service_win.py`, `ui/service_win.ui`, `__init__.py`, Loeschungen):**
* Geloescht: `.backup_service_toolbar/`, `.backup_parameter_panel/`, `serviceui/set_item_adapter.py`, `serviceui/set_run_worker.py` sowie die Legacy-Tests `check_p13_s4.py`, `check_p13_ui_plugins.py`, `check_p13_s5.py`, `check_p13_s56.py`, `check_p13_service_win_geometry.py`, `check_p14_precision_levels.py`, `check_p14_prop_ui.py`.
* `service_win.py`: `_on_master_selection` laedt das Set direkt (`set_repo.get_set` -> `load_set_into_editor`); Kontextmenue exklusiv (`_on_move_service`/`_on_remove_service`/`_on_add_set_service`/`_on_delete_set` auf DB-Definition, P14-04-E-Sperre + P14-05-Papierkorb erhalten); neue Helfer `_add_service_to_set()`/`_next_instance_id()`.
* `param_columns.py`: `combo_tf_set` -> `combo_tf`; `_update_service_tooltip` entfernt.
* `ui/service_win.ui`: `group_service_sets`-Block (299 Zeilen) entfernt.
* `__init__.py`: Exports bereinigt (`ServiceSetRunWorker`/`ServiceSetItemAdapter` raus).

**B) Layout-Bugfixes (Bugfix 1+2):**
* Bugfix 1 (`service_win.py`): `_param_panel.setMinimumWidth(320)` -> `960` (Default etwas breiter als zwei Service-Spalten = 942 px gemessen) -> zwei Services passen ohne horizontalen Scrollbalken.
* Bugfix 2 (`ui/service_win.ui`): Fenster-Geometrie `1280` -> `1400` Breite (etwas mehr als Tree-Minimum 400 + Box 960 + Splitter-Handle + Layout-Margins).
* Stale-Bug (`param_columns.py`): `_resize_param_box_deferred` pruefte `splitter.count() == 3` (Alt-Layout) -> auf `== 2` korrigiert; erst dadurch greift der deferred `setSizes` nach dem Spaltenaufbau wieder (vorher behielt der Splitter veraltete Groessen [521, 817]).

**C) New-Scan-Alt-Verdrahtung entfernt (`service_win.py`, `ui/service_win.ui`):**
* `HistoricalScanner`-Import, `self.scanner`, `_elapsed_timer`/`_elapsed_seconds`, die Controls `check_new_scan`/`btn_start`/`label_elapsed`/`progress_bar`, die Methoden `start_scan`/`on_progress`/`on_finished`/`_update_elapsed`, die `btn_start.clicked`-Verdrahtung und der closeEvent-Scanner-Code ersatzlos entfernt.
* `indexOf(self.btn_start)` -> festes `idx = 1` (Splitter-Einfuegeposition nach `layout_symbol`).
* Imports bereinigt (`QCheckBox`, `QLabel`, `QProgressBar` raus).
* `ui/service_win.ui`: `check_new_scan`, `btn_start_scan`, `layout_status` (Laufzeit/Fortschritt) entfernt; Placeholder "Scan-Log..." -> "Log...".

**Validierung (headless, gruen):**
* `python -m py_compile` auf `serviceui/service_win.py`, `serviceui/param_columns.py`, `serviceui/__init__.py` (Exit 0); `ui/service_win.ui` parsebar; Import-Smoke via venv-Python OK.
* Echte `ServiceWindow`-Instanz (offscreen, Test-DB in `test/`, 1920-FakeScreen): Mess-Skript (`tmp_measure_param_width.py`) -> hscroll max 121 -> **0** (2 Services ohne Scrollbalken), `_param_panel` width/min 960, Splitter-Sizes **[400, 960]** (statt stale [521, 817]), Fenster 1386 px (etwas mehr als 400+960+Handle+Margins).
* Keine verbleibenden Verweise auf entfernte Elemente (nur legitime Kommentare/Tests); `main.py` unberuehrt (greift auf keine entfernten Methoden zu).
* Temporaere Testdateien (`tmp_measure_param_width.py`, `tmp_diff.txt`) danach geloescht (Regel: Tests nur in `test/`).
* Keine UI-Tests (Regel). Manuelle UI-Verifikation durch den Anwender.
* `docs/x_Exports.md` bleibt unangetastet (Nutzer-Export, nicht Bestandteil dieses Commits).


### 3.27 Schritt 27 - Kleinere Einstellungen: Position-Persistenz, doppelte Standard-Hoehe, Exact-Fit an Inhalt (05.08.2026)

**Anlass (vom Anwender uebergeben - 5 Punkte):** (1) Die Fensterposition wird nicht mehr saved & restored. (2) Die Default-Hoehe von Tree und Parameter-Box soll verdoppelt werden. (3) Die Fenster-Hoehe soll exakt unter dem Log-Fenster enden. (4) Die Fenster-Breite soll exakt hinter dem rechten Ende der Parameter-Box enden. (5) Die Log-Hoehe soll auf 4 Zeilen begrenzt werden - die Log-Breite soll genauso breit sein wie der Tree.

**Entscheidungen (AskQuestion, Option 1):** Die Fenster-GROESSE wird kuenftig IMMER exakt an den Inhalt angepasst (auch SCHRUMPFEND) - NUR die POSITION wird gespeichert und wiederhergestellt. Ein fester Groessenwert wuerde das exakte Anpassen an Tree/Log/Box (Punkte 3+4) unterlaufen. Zusaetzlich: auto_restore=False + _keep_history_on_close=True - die Position bleibt auch bei MANUELLEM Schliessen (X) erhalten, aber das Fenster poppt beim App-Start NICHT ungefragt wieder auf (nur ueber den Service-Button oeffnen).

**A) `serviceui/service_win.py`:**
* **Punkt 1 (Position):** `@register_persistent_window(auto_restore=False)`; neue Klassen-Attribute `_keep_history_on_close = True` und `_exact_fit_to_content = True`. Eigene `save_state()`/`restore_state()`-Overrides: speichern/wiederherstellen NUR `pos()` (move), KEINE resize() - die Groesse folgt dem Inhalt-Reflow. Symbol/Timeframe-Restore bleibt erhalten. Nach dem Oeffnen wird zusaetzlich `QTimer.singleShot(0, self._apply_reflow_size)` geplant (Initial-Exact-Fit).
* **Punkt 2 (doppelte Hoehe):** `_param_scroll.setMaximumHeight(620 -> 1240)`; neues `_apply_reflow_size()`-Override setzt die Splitter-Mindest-Hoehe auf `2x` seiner natuerlichen Hoehe (nach setMinimumHeight werden die Layout-Caches erneut invalidiert - Qt-6.11-Quirk, sonst uebernimmt der vertikale Layout-sizeHint das neue Minimum nicht).
* **Punkt 3 (Fenster-Hoehe endet unter dem Log):** Das Log (text_log) wandert in die LINKE Splitter-Spalte UNTER den MasterTree (`right_layout.addWidget(self.text_log, 0)`) - das Fenster endet dadurch unten exakt an der Log-Unterkante.
* **Punkt 5 (Log):** Log-Hoehe font-basiert auf 4 Zeilen begrenzt (`fontMetrics().lineSpacing() * 4 + 12` statt der bisherigen fixen 120px); durch die Platzierung in der linken Spalte entspricht die Log-Breite exakt der Tree-Breite.

**B) `scrollable_content.py` (Exact-Fit):**
* `resize_to_clamped_content()`: mit `getattr(self, '_exact_fit_to_content', False)` wird das Fenster IMMER exakt auf `min(Inhalt, Bildschirm)` gesetzt - auch SCHRUMPFEND. Bisher galt "nur wachsen, nie schrumpfen". Alle anderen Mixin-Nutzer (z. B. `IndicatorSettingsDialog` in chart/indicator_dialog.py) behalten das bisherige Verhalten (Default False).

**Validierung (headless, gruen):**
* `python -m py_compile` auf `serviceui/service_win.py`, `scrollable_content.py` (Exit 0); UI-XML parsebar; Import-Smoke via venv-Python OK (ServiceWindow auto_restore=False / keep_history=True / exact_fit=True; IndicatorSettingsDialog exact_fit default False).
* Echte `ServiceWindow`-Instanz (offscreen, Test-DB in `test/`, 1920-FakeScreen): Splitter-Hoehe 379 -> **758** (2x, min=758), Log-Hoehe **68px = 4 Zeilen**, Log-Breite **400px = Tree-Breite**, Log-/Box-Unterkanten alle 757 = Fenster-Unterkante (Punkt 3), Fenster 1386x808 (Breite = exakt Box-Rand, Punkt 4; Hoehe = Inhalt + Frame).
* Position-Persistenz-Test (`tmp_geo_verify.py`): 7/7 PASS - Position restauriert (113,206), Groesse NICHT restauriert (exakt Inhalt statt 500x300), save_state speichert Position (250,300), Eintrag BLEIBT nach manuellem close() (keep_history=True), Wiedereroeffnung an (250,300).
* `test/test.py` an die neue Semantik angepasst (Teil 1 P2/P3/P5, Teil 3 H2-H5/H7 - lokal in test/, nicht getrackt).
* Temporaere Testdateien (`tmp_geo_verify.py`, `tmp_measure_h.py`, `tmp_debug_resize.py`, `tmp_qttest.py` u. a.) danach geloescht (Regel: Tests nur in `test/`).
* Keine UI-Tests (Regel). Manuelle UI-Verifikation durch den Anwender.
* `docs/x_Exports.md` bleibt unangetastet (Nutzer-Export, nicht Bestandteil dieses Commits).

### 3.28 Schritt 28 - Bugfixing: ServiceWindow Save & Restore (Fenster-Historie) + Test-Ordner aufgeraeumt (05.08.2026)

**Anlass (vom Anwender uebergeben, Bugfixing-Modus - 2 Aufgaben):**

1. **Das ServiceWindow ist nicht in der Fenster-Historie mit Save & Restore:** Wenn die App abgebrochen und neu gestartet wird, wird das service_win nicht wiederhergestellt.
2. **Ordner /test aufraeumen:** alles weg, was aktuell nicht genutzt wird.

**A) Task 1 - ServiceWindow auto_restore=True (1 Datei + Test):**

* **Ursache:** serviceui/service_win.py war seit Schritt 3.27 mit @register_persistent_window(auto_restore=False) registriert. 
estore_all_windows() in main.py prüft PersistentWindow.should_auto_restore(inst_id) und uebersprang win_service dadurch beim App-Start (Log: "Ueberspringe win_service (ServiceWindow): auto_restore=False"). Der Save-Pfad war bereits intakt (_keep_history_on_close=True haelt den Geometrie-/Instanz-Eintrag in window_instances/instance_states), nur der Restore-Gate blockierte.
* **Fix (serviceui/service_win.py):** Registrierung auf @register_persistent_window() (auto_restore=True) umgestellt - Semantik identisch zu AnalyticsWindow/PropertiesWindow/chart_win: War das Fenster beim Beenden offen, wird es beim naechsten Start automatisch wiederhergestellt (inkl. Position via 
estore_state()/save_state()-Override + Symbol/Timeframe-Filter). _keep_history_on_close=True bleibt erhalten (Position wird auch nach manuellem Schliessen mit X behalten und beim naechsten Oeffnen ueber den Service-Button wiederhergestellt).
* **	est/test.py angepasst:** Check H2 von should_auto_restore('win_service') == False auf == True umgestellt (Auto-Restore beim App-Start); Docstrings von Teil 3 aktualisiert.

**B) Task 2 - Test-Ordner bereinigt (75 Dateien + __pycache__ entfernt):**

**Behalten (19 Dateien):**
* 	est.py (designierte Haupt-Verifikation, offscreen, Test-DBs isoliert)
* Standard-Verifikations-Suite (M1-Zeitachse & Chart): check_time_utils.js, check_resolve_realtime.js, check_m1_consistency.py, check_m1_midnight.py, check_mt5_m1_boundary.py, check_chart_data.py, simulate_chart_mapping.py, 	est_db_lock.py, check_app_state.py, uild_cont_map.py + 	mp_cont_map.json
* Im Produktionscode referenziert: check_broker_tz.py (chart/js/02_time_utils.js), check_html_template.py (chart/chart_basics.py), check_current_timestamp.py (analytics/features/feature_builder.py)
* Aktive Phasen-15/16-Checks: check_p15_s2_service_tree.py, check_service_run_fixes.py
* Migrations-Tools: migrate_grid_liquidity.py, migrate_legacy_feature_store.py

**Entfernt (75):** alle obsoleten Phasen-Checks (P12-P15: check_analytics_*, check_p13_*, check_p14_*, check_p15_s1_*, check_p15_s3_*, check_grid_*, check_tf_*, check_phase14_regression, check_performance_p14, check_plugin_*, check_dialog_geometry, check_fixes_1503, check_generation_guard, check_duckdb_write_contention, check_statistics_repo, check_table_render_fix u. a.), grid_ref.py (eingefrorene Alt-Referenz), die JS-Legacy-Checks (check_marker_layers.js, check_measurement.js, check_p14_grid_incremental.js, check_race_guard.js, check_time_constants.js) und **alle 15 Test-DuckDBs** (ll11_app/sym, nalytics_test, p14_*, phase14_*, 	f_*) sowie 	est/__pycache__.

**Validierung (headless, gruen):**
* python -m py_compile auf serviceui/service_win.py + allen 17 behaltenen Test-.py (Exit 0).
* 
ode --check auf den behaltenen JS-Checks + Ausfuehrung: check_time_utils.js ("ALLE TESTS OK"), check_resolve_realtime.js ("RESULT: PASS").
* 	est/test.py (offscreen, Test-DBs in 	est/): **H1/H2/H3 PASS** (auto_restore aktiv + should_auto_restore True), H4-H6 (Position-Persistenz) PASS. Die 3 verbleibenden Meldungen P2/P5/H7 sind vorbestehende Offscreen-Umgebungs-Artefakte (Test-Screen 800x800 vs. erwartete Inhaltsbreite >= 1300) und unabhaengig von diesem Fix.
* Keine UI-Tests (Regel). Manuelle UI-Verifikation durch den Anwender (App beenden mit offenem ServiceWindow -> Neustart -> ServiceWindow erscheint wieder).
* docs/x_Exports.md bleibt unangetastet (Nutzer-Export, nicht Bestandteil dieses Commits).


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

---
 # TASK: Phase 15.03-E – Popover-ServiceSelector im AnalyticsWindow (ÜBERARBEITET 06.08.2026)

 > **Ist-Analyse 06.08.2026 (Code-konsistente Korrektur):**
 > Der Ursprungsentwurf referenzierte ein nicht existentes `SelectorMode`-Enum,
 > einen `MasterTree` im `SELECT_ONLY`-Modus und eine `ParameterPanel`-Klasse
 > (entfernt, `.backup_parameter_panel` leer). Real:
 > * `ServiceSelectorWidget.MODE_SELECT_ONLY` (String-Konstante) baut eine
 >   KOMPAKTE DROPDOWN-Zeile (Set-Combo + Service-Combo), KEINEN Tree.
 > * Parameter-Anzeige baut `ServiceParamColumnsMixin._build_service_column()`
 >   (eine QGroupBox-Spalte je Service) – es gibt keine `set_service()`-API.
 > * `AnalyticsWindow` hat BEREITS ein Feature-Filter-Dropdown (`combo_feature`).
 > **Entscheidung (User, 06.08.2026):** Das Popover ERSETZT `combo_feature` –
 > keine Doppelsteuerung von `AnalyticsViewModel.set_feature_id()`.

 Bitte binde das `ServiceSelectorWidget` (Modus `MODE_SELECT_ONLY`) als
 platzsparendes Top-Bar-Popover im `AnalyticsWindow` (`analytics/ui/analytics_win.py`)
 ein und ersetze das bestehende Feature-Filter-Dropdown:

 ---

 ### 1. Top-Bar Popover Button (ersetzt `combo_feature`)
 1. **Button-Platzierung (`analytics/ui/analytics_win.py`, Filter-Zeile):**
    - Ersetze das bestehende `combo_feature`-Dropdown durch einen Popover-Button:
      `[ Set/Service: ▾ Keiner ausgewählt ]`
    - Die bisherigen Slots `_on_feature_changed()` / `_populate_feature_combo()`
      entfallen (Redundanz, Entscheidung 06.08.2026). Die Verkabelung
      `combo_feature.currentIndexChanged → set_feature_id` wird durch das
      Popover übernommen.
 2. **Flyout/Popover-Widget:**
    - Klick auf den Button öffnet ein schwebendes Popover direkt unter dem Button.
    - Inhalt (manuell anpassbar – Variante „minimal-invasiv"):
      * **Oben:** `ServiceSelectorWidget` im Modus `MODE_SELECT_ONLY`
        (Set-/Service-Combos), Signale `selection_changed(set_id, service_id)`.
      * **Unten:** Read-Only-Parameteranzeige für den gewählten Service über
        `ServiceParamColumnsMixin._build_service_column(iid, pid, cfg)` in einem
        deaktivierten `QGroupBox`-Container (`setEnabled(False)`).
    - Alternativ (falls gewünscht): Read-Only-`MasterTree` statt Combos – dann
      muss ein neues Widget gebaut werden (nicht Teil dieses minimal-invasiven
      Tasks).
    - Enthält den Aktions-Button `[ 🗑️ Aktiven Service-Filter entfernen ]`.

 ---

 ### 2. Inspektion, Filter-Entfernung & Sicherheitsabfrage
 1. **Parameter-Inspektion im Popover:**
    - `selection_changed(set_id, service_id)` lädt die rechte Parameteranzeige:python
      cfg = self.model.find_service(setid, serviceid) or {}
      pid = cfg.get("pluginid") or serviceid
      box = self.buildservicecolumn(serviceid, pid, cfg)   # ServiceParamColumnsMixin
      box.setEnabled(False)                                    # Read-Only
      2. **feature_id-Auflösung (Lücke im Ursprungsentwurf):**
    - Das Widget-Signal liefert `set_id`/`service_id`, NICHT die `feature_id`.
    - Auflösung über das Modell: `plugin_id = model.find_service(set_id, service_id).get("plugin_id")`
    - Dann `AnalyticsViewModel.set_feature_id(plugin_id)` – der `feature_id` im
      Feature-Store IST die `plugin_id` (grid_lines / proximity).
 3. **Aktion "Service-Filter entfernen" + Sicherheitsabfrage:**
    - **Niemals automatisch alle Services vermischen!** (einzelner `feature_id`)
    - Vor dem Entfernen modale Abfrage (`QMessageBox.question`):
      > *"Möchtest du den aktiven Service-Filter wirklich entfernen? Die Anzeige
      > im Analytics-Fenster zeigt danach wieder alle Features."*
      (Korrektur: `set_feature_id(None)` entfernt den Filter → ALLE Feature-Rows
      sichtbar, kein „leeres Raster".)
    - Bei Bestätigung: `AnalyticsViewModel.set_feature_id(None)`, Popover
      schließen, Button-Text auf `[ Set/Service: ▾ Keiner ausgewählt ]`.
 4. **Button-Text & Profil-Persistenz:**
    - Der Button-Text zeigt den aktiven Filter: `[ Set/Service: ▾ <plugin_id> ]`
      bzw. `[ Set/Service: ▾ <set_id>/<service_id> ]` (manuell anpassbar).
    - `feature_id` wird über `AnalyticsViewModel._current_payload()` bereits im
      Profil-Payload persistiert (dict(self._params) inkl. feature_id) ✔.
    - Bei Profilwechsel übernimmt `_apply_profile()` die Profil-Parameter inkl.
      `feature_id` in den VM ✔ – der Button-Text muss danach synchronisiert
      werden (z. B. im `active_profile_changed`-Slot oder über
      `event_bus.profile_changed`).

 ---

 ### 3. EventBus-Integration
 - `event_bus.service_set_changed` → `ServiceSelectorModel.data_changed` →
   Popover-Refresh (besteht, ServiceSelectorWidget verbindet das Modell).
 - `event_bus.profile_changed` → Button-Text mit dem gespeicherten
   `feature_id`-Filter aktualisieren (NEU zu verdrahten im AnalyticsWindow).

 ---

 ### 4. Headless Verification (`test/check_p15_s3_e_popover.py` – NEU)
 - Testet ohne GUI-Start (offscreen/Temp-DB unter test/):
   1. `selection_changed(set_id, service_id)` → Auflösung der plugin_id →
      `AnalyticsViewModel.set_feature_id()` wird gerufen.
   2. `FeatureStoreReader.fetch_rows(..., feature_id=...)` filtert korrekt.
   3. Entfernen-Logik setzt `feature_id = None` zurück (Button-Text-Reset).
   4. `event_bus.service_set_changed` aktualisiert das `ServiceSelectorModel`.
   5. `combo_feature` existiert NICHT mehr (Ersetzungs-Entscheidung).

---

# TASK: Phase 15.04 – Infrastructure & EventBus Hardening

Bitte setze das Infrastruktur-Upgrading und das Cleanup der Repositories/Payloads gemäß den folgenden Spezifikationen um:

---

 ### 1. EventBus verifizieren statt ergänzen (config/event_bus.py) – STATUS: bereits umgesetzt

 ACHTUNG (Ist-Analyse 05.08.2026): Alle geforderten Core-Signale existieren
 bereits in `config/event_bus.py` – inkl. des Concurrency-Guards (Phase 16,
 getestet in test/test.py S1–S8). Dieser Abschnitt ist KEIN Implementierungs-
 auftrag mehr, sondern eine reine Bestands-Verifikation:

 - `favorites_changed = Signal()`
 - `profile_changed = Signal(str)`
 - `service_set_changed = Signal()`
 - `service_run_started = Signal()`   # Concurrency-Guard (Timer-Stop, main.py)
 - `service_run_finished = Signal()`  # Concurrency-Guard (Timer-Start, main.py)

 Erwartete Aktion:
 - KEINE Änderung an config/event_bus.py.
 - Verifikation nur über den Headless-Check (Abschnitt 4): prüft, dass alle
   5 Signale existieren und per connect/emit empfangen werden können.

---

### 2. WindowStateRepository herauslösen (window_state_repository.py) – UMGESETZT (06.08.2026)

 1. **Erstelle `window_state_repository.py` im Root:**
    - Kapselt die SQL-Zugriffe auf `window_instances`, `instance_states` UND
      `symbol_tf_states` aus `app_data.duckdb` (alle instanz-/fensterbezogenen
      Tabellen – nicht nur die zwei im Ursprungsentwurf genannten).
    - Nutzt zwingend `DbPool.get(db_path)` (Thread-local, lock-frei, wie
      StateManager) – KEINE eigene Connection-Verwaltung.
    - Methoden: `save_window_geometry()`, `get_window_geometry()`,
      `save_instance_state()`, `load_all_instances()`, `delete_instance()`,
      `get_next_instance_id()`, `save_symbol_tf_state()`,
      `get_symbol_tf_state()`, `delete_symbol_tf_state()`.
    - `load_all_instances()` reproduziert das Bestandsverhalten EXAKT
      (pandas-`.df()`-Leseart + String-Normalisierung von symbol/timeframe).
    - Das Repository ist REIN lesend/schreibend – die Schema-Anlage und
      -Migration (DDL in `_init_db()`) verbleibt im StateManager
      (keine Verantwortungs-Verdopplung).

 2. **`state_manager.py` zur additiven Fassade verschlanken (Verbotsregel):**
    - ALLE bestehenden Methoden bleiben mit identischen Signaturen erhalten
      (Rückwärtskompatibilität – keine Aufrufer-Änderung in main.py,
      persistent_win.py, chart_win.py, service_win.py, Analytics, Tests).
    - Die Instanz-/Fenster-Methoden delegieren intern an das neue
      WindowStateRepository; die DB-Pfad-Auflösung bleibt beim StateManager
      und wird an das Repository durchgereicht (Test-Isolation!).
    - NICHT umsetzen (falsche Prämisse im Ursprungsentwurf): „Delegiert
      Profil-Abfragen an AnalyticsProfileRepository und Symbol-Abfragen an
      SymbolRepository" – StateManager hat KEINE solchen Methoden; beide
      Repositories sind bereits eigenständig im Root vorhanden und werden
      direkt genutzt. Es gibt nichts zu delegieren.

 3. **Test-Isolation sicherstellen:**
    - `test/test.py` patcht `StateManager.__init__` auf eine Temp-DB. Diese
      Patch-Strategie wird auf das neue WindowStateRepository erweitert
      (gleiche Temp-DB), damit alle Fenster-/Repository-Checks weiterhin
      unabhängig von der laufenden App laufen (DuckDB-Single-Writer).

---

### 3. Schema-Version & FeatureStore-Payload – UMGESETZT (06.08.2026)

 1. **Pflichtfeld `schema_version` im Payload – BEREITS ERFÜLLT (nur verifiziert):**
    - `grid_lines_service.py` und `proximity_service.py` setzen bereits
      `"schema_version": "1.0.0"` in `feature_store_payload["metadata"]`.
    - KEINE Änderung an den Plugins nötig; verifiziert im Headless-Check
      (`test/check_p15_s4_infra.py`, V2/V3).

 2. **Alt-Data Default im Lesepfad – HARMONISIERT (1 konkrete Änderung):**
    - `feature_store_reader.py` nutzte `SCHEMA_VERSION_DEFAULT = "1.0"`
      (zweistellig) – die Spezifikation und die Plugins verwenden `"1.0.0"`
      (dreistellig). Seit 06.08.2026 ist der Default auf `"1.0.0"`
      vereinheitlicht (inkl. Docstring/Kommentar E-3 in `feature_store_reader.py`
      und diesem Dokument).
    - Verhalten bleibt additiv: `_normalize_feature_data()` ergänzt fehlende
      `schema_version` beim Lesen – die DB-Zeile wird NICHT überschrieben
      (verifiziert in V4–V7).

 3. **Konzeptionelle Lücke dokumentiert (abgeschlossen 06.08.2026):**
    - `store_plugin_payload()` persistiert NUR die Records in `feature_data`;
      das `metadata`-Dict inkl. `schema_version` wird NICHT in die DB
      geschrieben. Der Reader-Default greift daher beim Lesen immer.
    - **`schema_version` ist ein reiner In-Memory-Vertrag des
      `feature_store_payload`** (Plugin-Ausgabe → Evaluator → Indikator-Lesepfad).
      Die Persistenzschicht kennt sie nicht; die DB enthält die Records inkl.
      nativer Spalten, aber ohne das metadata-Payload. Dieser Umstand ist
      gewollt und wird bewusst nicht geändert – Abschnitt 3 ist damit
      vollständig abgeschlossen.

---

### 4. Headless Verifikation (test/check_p15_s4_infra.py) – UMGESETZT (06.08.2026)

 Erstellt: `test/check_p15_s4_infra.py` (offscreen, Temp-DBs unter test/ –
 Regel: Tests nur in test/). Prüft – angepasst an den Ist-Stand:

 1. **EventBus-Bestand (statt Implementierung):**
    - Alle 5 Signale existieren auf `event_bus` und sind per `connect` +
      `emit` empfängbar (favorites_changed, profile_changed(str),
      service_set_changed, service_run_started, service_run_finished).

 2. **WindowStateRepository (Temp-DB, Patch analog test/test.py):**
    - `save_window_geometry`/`get_window_geometry`-Roundtrip (inkl.
      is_maximized), `save_instance_state` + `load_all_instances`
      (String-Normalisierung), `delete_instance` (beide Tabellen),
      `get_next_instance_id` (win_1, win_2, ...), symbol_tf_state-Roundtrip.
    - Fassaden-Delegation: `StateManager` liefert über seine Bestands-Methoden
      identische Werte wie das Repository (gleiche DB).

 3. **schema_version (harmonisiert):**
    - `GridLinesService.calculate()` und `ProximityService.calculate()`
      (synthetischer OHLCV-DataFrame) liefern
      `payload["metadata"]["schema_version"] == "1.0.0"`.
    - `FeatureStoreReader._normalize_feature_data(None)` bzw. Alt-Row ohne
      Feld → `"1.0.0"` (Default); vorhandenes Feld bleibt unangetastet;
      DB-Zeile unverändert.

---

### ⚠️ Richtlinien
- **Keine UI-Tests starten!** Verifikation ausschließlich über den Headless-Check (`python test/check_p15_s4_infra.py`) und `py_compile`.
- Erzeuge gezielte, saubere Code-Snippets/Patches.

---

## Implementierungs-Log (Taxonomie: Phase 15.04)

### 06.08.2026 – 15.04 Infrastructure & EventBus Hardening (UMGESETZT)

**1) EventBus verifiziert (keine Änderung an `config/event_bus.py`):**
Alle 5 Signale (`favorites_changed`, `profile_changed(str)`,
`service_set_changed`, `service_run_started`, `service_run_finished`)
existieren und sind per connect/emit empfängbar (Check B1–B5 in
`test/check_p15_s4_infra.py`).

**2) `window_state_repository.py` im Root erstellt:**
- Kapselt alle instanz-/fensterbezogenen SQL-Zugriffe (`window_instances`,
  `instance_states`, `symbol_tf_states`) aus `app_data.duckdb`.
- Nutzt `DbPool.get(db_path)` (Thread-local, lock-frei) – keine eigene
  Connection-Verwaltung.
- 9 Methoden (save/get_window_geometry, save_instance_state,
  load_all_instances, delete_instance, get_next_instance_id,
  save/get/delete_symbol_tf_state). `load_all_instances()` reproduziert das
  Bestandsverhalten EXAKT (pandas-`.df()`-Leseart + String-Normalisierung).
- Schema-Anlage/-Migration bleibt im StateManager (keine DDL im Repository).

**3) `state_manager.py` als additive Fassade:**
- Alle Bestands-Methoden mit identischen Signaturen erhalten (Rückwärts-
  kompatibilität – keine Aufrufer-Änderung). Die 9 Instanz-/Fenster-Methoden
  delegieren intern an das WindowStateRepository.
- DB-Pfad-Auflösung bleibt beim StateManager und wird an das Repository
  durchgereicht (Test-Isolation). Patch-Strategie aus `test/test.py` auf
  WindowStateRepository erweitert (gleiche Temp-DB, Check I1/F7).

**4) `schema_version` harmonisiert:**
- `feature_store_reader.py`: `SCHEMA_VERSION_DEFAULT` von `"1.0"` auf
  `"1.0.0"` vereinheitlicht (E-3-Kommentare + Docstring aktualisiert).
- Reader-Default und Plugin-Vertrag (grid_lines/proximity, `metadata`) sind
  jetzt identisch. `_normalize_feature_data()` bleibt additiv – DB-Zeile wird
  nicht überschrieben.

**5) Headless-Verifikation (`test/check_p15_s4_infra.py`):**
- 33 Checks bestanden: EventBus (B1–B5), WindowStateRepository (W1–W13,
  I1), Fassaden-Delegation (F1–F7), schema_version (V1–V7).
- Zusätzlich `python test/test.py` ausgeführt: keine neuen Regressionen
  (die 3 vorbestehenden Breiten-Checks P2/P5/H7 scheitern auch ohne diese
  Änderung – offscreen-Screen 800×800 vs. Breiten-Annahme ≥ 1300 px).

**Git:** Tag `phase15_04_backup` vor der Umsetzung; Commit nach Freigabe.

---

