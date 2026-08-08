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

## 5. Review & Entscheidungen (08.08.2026, Bugfixing-Modus)

### 5.1 Vollständigkeits-Review (Ist-Code vs. Kapitel-Anweisung)

| Step | Status | Befund |
|---|---|---|
| Step 1 | **Bereits umgesetzt** | `_insert_into_category_tree()` ist bereits rekursiv (unbegrenzte Slash-Pfade, 16.08 K2); `category_plugin_ids(path)` sammelt bereits rekursiv aus Unterordnern (17.01.02). Tests in `test/test.py` (16.08, 17.01.02) vorhanden. |
| Step 2 | **Bereits umgesetzt** | Rekursives Ordner-Rendering im MasterTree (`_build_category_item`/`_build_child_item`); Ordner-Aktionen in `service_win.py` (`_on_run_category`, `_on_category_info_requested`, `_category_path_of`). Tests vorhanden. |
| Step 3 | **Teilweise** | `ServiceSelectorDialog` (Checkbox-MasterTree + Read-Only-Param-Panel) existiert; **Standalone-Editierung fehlt** (Panel ist `setEnabled(False)`), **direkte Baum-Selektion → `set_feature_ids` fehlt** (nur Checkbox-Multi-Select + Apply). |
| Step 4 | Offen | `py_compile` aller 7 betroffenen Dateien **läuft fehlerfrei** (verifiziert). Headless-Tests für rekursive Kategorien existieren; für Standalone-Params im Analytics-Kontext fehlen. |

### 5.2 Konsistenz-Probleme (Doku vs. Ist-Code)

1. **Einrückung:** Kapitel verlangt „Ausschließlich Tabs" – der gesamte Codebase nutzt **4 Leerzeichen** (0 Tab-Zeilen in allen 7 Dateien). → Siehe E-1.
2. **`ParamColumnsWidget`:** Diese Klasse existiert **nicht**. Real: `ServiceParamColumnsMixin` in `serviceui/param_columns.py`. → Siehe E-2.
3. **`service_set_changed`-Emit:** `ServiceWindow._save_plugin_params()` emittiert aktuell **kein** `service_set_changed` (nur `_save_params_from_panel` im Set-Pfad). Kapitel verlangt das Emit für Standalone-Params. → Siehe E-3.
4. **Test-Cleanup (Invariante 10):** `test/` enthält Alt-Proben (`_probe_meta.py`, `_probe_sets.py`, `_probe_*_out.txt`), die nach Abschluss entfernt werden müssen (nur `test.py` bleibt).

### 5.3 Entscheidungen

**E-1 (08.08.2026): Einrückung = 4 Leerzeichen, nicht Tabs.** Der Projekt-Standard (sämtliche bestehenden Dateien) ist 4 Leerzeichen pro Ebene. Die „Tabs"-Regel des Kapitels wird als redaktioneller Fehler gewertet und für alle Phase-18-Änderungen auf **4 Leerzeichen** korrigiert (kein Reindent bestehender Dateien, Code-Preserving). Spacing „1 Leerzeile zwischen Methoden" bleibt gültig (Ist-Code folgt dem bereits).

**E-2 (08.08.2026): Referenzklasse = `ServiceParamColumnsMixin`.** Alle Vorkommen von „ParamColumnsWidget" in der Kapitel-Anweisung bezeichnen `serviceui/param_columns.py::ServiceParamColumnsMixin` (der einzige reale Param-Column-Builder, genutzt von `ServiceWindow` und `ServiceSelectorDialog`/`_DialogParamHost`). Eine neue Klasse wird nicht eingeführt.

**E-3 (08.08.2026): `service_set_changed` nach Standalone-Speicherung.** Gemäß Kapitel wird bei `save_global_value("plugin_params_<id>", ...)` zusätzlich `event_bus.service_set_changed.emit()` abgesetzt, damit alle `ServiceSelectorModel`-Instanzen (MasterTree-Daten, Ausführungsdaten) live synchronisieren. Im ServiceWindow-Pfad wird das Verhalten beibehalten (der Run-Worker emittiert bereits am Ende); der neue Analytics-Pfad emittiert gemäß Kapitel.

**E-4 (08.08.2026): Umsetzungs-Variante für Step 3 = Option B (vollständige Harmonisierung).** Der `ServiceSelectorDialog` entfällt ersatzlos; `MasterTree` (Multi-Select, Checkbox-Modus) und ein editierbares Param-Panel (`ServiceParamColumnsMixin`) werden **direkt in `analytics_win.py` eingebettet** (Filterbereich). Datenfluss: Baum-Selektion (Set/Ordner/Plugin) löst IDs auf → `view_model.set_feature_ids(ids)`; Standalone-Services (`belongs_to_indicator == False`) laden/speichern ihre Params über `state_manager.plugin_params_<id>`.

### 5.4 Verbleibende offene Punkte (für die Umsetzung)

1. **Layout:** Wie wird der MasterTree im AnalyticsWindow platziert (linke Spalte neben Sidebar, oberhalb des Filterbereichs, o. Ä.)? → Entscheidung während Coding, minimale Eingriffe in bestehendes Layout (Code-Preserving).
2. **Read-Only → Editierbar:** Das bestehende `_DialogParamHost`-Muster (No-op-Speicherpfade) wird durch einen echten Analytics-Host ersetzt; die Editier-Pfade folgen `ServiceWindow._load_plugin_editor`/`_save_plugin_params`.
3. **Profil-Sync:** `_sync_service_filter_button`/`_active_display_names`-Logik muss auf den eingebetteten Baum umgestellt werden (Button-Text entfällt).
