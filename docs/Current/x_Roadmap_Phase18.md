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

# 18.01.01 Harmonisierung Analytics_win & Service_win (Rekursive Ordner)

## 1. Regeln & Invarianten

* **Einrückung:** Ausschließlich **Tabs**.
* **Spacing:** Exakt **1 Leerzeile** zwischen Funktionen/Methoden.
* **UI-Tests:** **VERBOTEN.** Verifikation rein headless (`py_compile`, `test/test.py`).
* **Architektur:** SRP, Inversion of Control, Entkopplung via `EventBus`.

---

## 2. Architektur & Datenfluss (Textblock-Schema)

[ServiceSelectorModel] ──(baut n-tiefe Ordner/Pfade)──► [MasterTree (serviceui)]
         │                                                        │
         ├──► [ServiceWindow]   ──(speichert)──► [StateManager (plugin_params_<id>)]
         │                                                │
         └──► [AnalyticsWindow] ──(sendet IDs)─► [AnalyticsViewModel] ◄── [EventBus]

---

## 3. Betroffene Dateien

* `analytics/engine/service_selector_model.py`: Rekursive Ordner (`_insert_into_category_tree`), tiefes Resolving (`category_plugin_ids`).
* `serviceui/master_tree.py`: Rekursives Rendering (`GROUP_CATEGORY`) im QTreeWidget.
* `serviceui/service_win.py`: Aktionen/Kontextmenüs für n-tiefe Ordner anpassen.
* `analytics/ui/analytics_win.py`: Einbau `MasterTree` & `ParamColumnsWidget`, Standalone-Editierung, Multi-Select-Filter.
* `analytics/engine/analytics_view_model.py`: Verarbeitet aufgelöste `feature_ids` aus Ordnern/Sets.

---

## 4. Schritt-für-Schritt Anleitung (IDE-AI)

### Step 1: Rekursion in `service_selector_model.py`

* [ ] `_insert_into_category_tree()` für unbegrenzt verschachtelte Slash-Pfade (`A/B/C`) absichern.
* [ ] `category_plugin_ids(path)` so anpassen, dass alle Plugins aus Unterordnern rekursiv gesammelt werden.

### Step 2: `master_tree.py` & `service_win.py`

* [ ] Ordner-Rendering im `MasterTree` rekursiv für `GROUP_CATEGORY` umsetzen (`📁 <Name>`).
* [ ] In `service_win.py` Ordner-Aktionen für tief verschachtelte Pfade anpassen.

### Step 3: `analytics_win.py` Harmonisierung & Parameter-Editierung

* [ ] Legacy-Filter durch `MasterTree` & `ParamColumnsWidget` ersetzen.
* [ ] Bei Standalone-Service (`belongs_to_indicator == False`):
1. Params laden: `state_manager.get_global_value("plugin_params_<id>", default)`.
2. Im `ParamColumnsWidget` aus `full_parameter_schema()` rendern.
3. Bei Änderung: `save_global_value("plugin_params_<id>", params)` + `event_bus.service_set_changed.emit()`.

* [ ] Bei Baum-Selektion (Set/Ordner/Plugin): IDs auflösen -> `view_model.set_feature_ids(ids)`.

### Step 4: Quality Gate

* [ ] `python -m py_compile analytics/engine/service_selector_model.py serviceui/master_tree.py serviceui/service_win.py analytics/ui/analytics_win.py`
* [ ] Headless-Test in `test/test.py` für rekursive Kategorien & Standalone-Params.
* [ ] Code-Check: Nur Tabs, 1 Leerzeile Abstand.

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

* [ ] `DbPool` & Threading-Locks in `db/db_pool.py` auslagern.


* [ ] Schema-Anlage (`check_and_init_databases`) nach `db/schema_initializer.py` verschieben.


* [ ] Sync-Logik (`sync_market_data`) in `data_sync/mt5_sync_service.py` trennen.


* [ ] `MarketDataRepository` eigenständig in `repositories/market_data_repository.py` platzieren.



### Step 2: `main.py` schlankziehen

* [ ] `LiveTickWorker` & `DataSyncWorker` in eigene Worker-Dateien im Ordner `workers/` auslagern.


* [ ] Wiederherstellung & Jump-to-Bar (`restore_all_windows`, `open_chart_at_bar`) in `ui/window_manager.py` kapseln.



### Step 3: `service_selector_model.py` bereinigen

* [ ] Rekursiven Baumaufbau (`build_tree`, `_insert_into_category_tree`) in `analytics/engine/tree_builder.py` auslagern.


* [ ] Model rein auf Daten-Providing & EventBus-Sync fokussieren.



### Step 4: Quality Gate

* [ ] `python -m py_compile db/db_pool.py db/schema_initializer.py data_sync/mt5_sync_service.py repositories/market_data_repository.py workers/live_tick_worker.py workers/data_sync_worker.py ui/window_manager.py analytics/engine/tree_builder.py`
* [ ] Headless-Test in `test/test.py` für DB-Zugriffe & Worker-Instanziierung ausführen.
* [ ] Code-Check: Nur Tabs, 1 Leerzeile Abstand.

---

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

* [ ] Ordner-Mechanik (`_insert_into_category_tree`) auch auf den Knoten `Sets` (`GROUP_SETS`) anwenden.
* [ ] `category_set_ids(path)`-Methode hinzufügen, die alle `set_id`s aus Unterordnern rekursiv auflöst.

### Step 2: Konfektionierung `MasterTree` (`serviceui/master_tree.py`)

* [ ] **Drag & Drop aktivieren:** `setDragEnabled(True)`, `setAcceptDrops(True)`, `setDropIndicatorShown(True)`.
* [ ] `dropEvent()` überschreiben:
1. Ermittle gezogenen Knoten (Set-ID, Plugin-ID oder Ordner) und Ziel-Ordner-Pfad.
2. Aktualisiere den Kategorie-Pfad beim Element.
3. Emittiere Datenänderung an das Modell/Repositories.

* [ ] **Kontextmenü erweitern (`customContextMenuRequested`):**
1. **"Neuer Ordner":** Öffnet `QInputDialog`, erstellt neuen Unterordner-Pfad im gewählten Elternknoten.
2. **"Umbenennen":** Benennt Ordner/Knoten um und führt Pfad-Update für alle enthaltenen Kinder durch (String-Replace).


### Step 3: Persistenz & Synchronisation

* [ ] Ordner-Aktionen für Sets via `ServiceSetRepository.save_set()` abspeichern.
* [ ] Ordner-Aktionen für Standalone-Plugins via `state_manager.save_global_value("plugin_params_<id>", ...)` sichern.
* [ ] Nach allen Strukturänderungen `event_bus.service_set_changed.emit()` abfeuern.


### Step 4: Quality Gate

* [ ] `python -m py_compile serviceui/master_tree.py analytics/engine/service_selector_model.py analytics/ui/analytics_win.py serviceui/service_win.py`
* [ ] Headless-Test in `test/test.py` für rekursive Sets-Kategorien & Pfad-Updates.
* [ ] Code-Check: Exakt 4 Leerzeichen Einrückung, 1 Leerzeile Abstand.
