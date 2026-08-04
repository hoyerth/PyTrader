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
