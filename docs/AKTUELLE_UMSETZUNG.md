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
