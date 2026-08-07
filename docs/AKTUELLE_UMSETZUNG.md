# Phase 16: Architektur Servive/Indikator - Feinarbeit Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 16)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase16_step1`, `phase16_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
4. **Zentraler `EventBus`:** Fenster und Worker communicaten schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
5. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db_service.py`) – eine Verbindung pro Thread und DB-Datei.
6. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
7. **Concurrency-Guard & Timer-Pausierung (Ergänzung 1):** Solange im ServiceWindow intensive Service-Berechnungen laufen (`SetRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
8. **Isolierter Test-Workspace (Ergänzung 2):** Alle neuen Test-Python-Dateien und temporären Test-Datenbanken (`*.duckdb`) müssen strikt im Unterordner `test/` erzeugt, gelesen und abgelegt werden – niemals im Projekt-Root oder im `data/`-Ordner.
9. **Open/Closed-Principle & Code-Preserving (Ergänzung 3):** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden und bestehende Kern-Klassen bleiben geschützt.
10. **Test-Cleanup (Ergänzung 4, Entscheidung 06.08.2026):** Tests werden NICHT aufbewahrt. Nach Abschluss jedes Phasenkapitels wird der Ordner `test/` aufgeräumt – es bleibt ausschließlich die Datei `test/test.py` (dauerhafter Test-Harness) bestehen. Alle temporären Check-Skripte (`check_*.py`/`*.js`), einmaligen Migrations-/Bereinigungsskripte, Test-Datenbanken (`*.duckdb`) und generierten Dateien (`tmp_*.json` u. Ä.) werden entfernt. Die Verifikation eines Kapitels erfolgt daher VOR der Bereinigung; danach existieren die Prüfskripte nicht mehr.

---

# 16.08.01 Nachtrag Bereinigung: Naming Conventions (`srv_` & `ind_`)

## 1. Zielsetzung & Naming-Regeln
Vereinheitlichung aller Dateinamen, Klassen-Identifier, Plugin-IDs und Datenbank-Einträge für Services und Indikatoren nach strikter Naming Convention.

1. **Services (Plugins/Features):**
   * **Präfix:** `srv_`
   * **Regel:** Wörter wie `service`, `plugin` oder `feature` **entfallen** vollständig aus Dateinamen und Identifiern.
   * **Beispiel:** `grid_lines_service.py` -> `srv_grid_lines.py` | `plugin_id = "grid_lines"` -> `plugin_id = "srv_grid_lines"`
2. **Indikatoren:**
   * **Präfix:** `ind_`
   * **Regel:** Wörter wie `indicator` oder `ind` (doppelt) **entfallen** vollständig aus Dateinamen und Identifiern.
   * **Beispiel:** `fixed_grid_proximity.py` -> `ind_fixed_grid_proximity.py` | `indicator_id = "fixed_grid_proximity"` -> `indicator_id = "ind_fixed_grid_proximity"`
---

## 2. Zuordnung der Dateinamen & Identifier (Refactoring Matrix)

### A. Services (`analytics/features/definitions/`)
| Alter Dateiname | Neuer Dateiname | Alte `plugin_id` | Neue `plugin_id` |
| :--- | :--- | :--- | :--- |
| `grid_lines_service.py` | `srv_grid_lines.py` | `grid_lines` | `srv_grid_lines` |
| `proximity_service.py` | `srv_proximity.py` | `proximity` | `srv_proximity` |
| `grid_levels.py` | `srv_grid_levels.py` | `grid_levels` | `srv_grid_levels` |
| `ema_diff.py` | `srv_ema_diff.py` | `ema_diff` | `srv_ema_diff` |
| `atr_normalized.py` | `srv_atr_normalized.py` | `atr_normalized` | `srv_atr_normalized` |

### B. Indikatoren (`chart/indicators/`)
| Alter Dateiname | Neuer Dateiname | Alte `indicator_id` | Neue `indicator_id` |
| :--- | :--- | :--- | :--- |
| `fixed_grid_proximity.py` | `ind_fixed_grid_proximity.py` | `fixed_grid_proximity` / `grid_liquidity` | `ind_fixed_grid_proximity` |
| `multi_ma.py` | `ind_multi_ma.py` | `multi_ma` | `ind_multi_ma` |

---

## 3. Schritt-für-Schritt-Anleitung für die IDE-AI

### Schritt 1: Physikalische Dateien umbenennen
Benenne die Dateien in `analytics/features/definitions/` und `chart/indicators/` gemäß Tabelle in Abschnitt 2 um. Aktualisiere die jeweiligen `__init__.py`-Dateien in den beiden Ordnern mit den neuen Modulimporten.

### Schritt 2: In-Code-Identifier & Metadaten anpassen
1. In allen umbenannten `srv_*.py`-Dateien:
   * Setze `plugin_id = "srv_<name>"` (z. B. `srv_grid_lines`).
   * Falls `dependencies` angegeben sind, passe diese ebenfalls an (z. B. `dependencies = ["srv_grid_lines"]`).
2. In allen umbenannten `ind_*.py`-Dateien:
   * Setze `indicator_id = "ind_<name>"` (z. B. `ind_fixed_grid_proximity`).
   * Passe `service_plugin_ids` an (z. B. `service_plugin_ids = ["srv_grid_lines", "srv_proximity"]`).
3. Passe alle Code-Imports im Projekt an (`FeatureBuilder`, `LiveAnalyzer`, `HistoricalScanner`, `ServiceSelectorModel`, Tests).

### Schritt 3: Datenbank-Migration (`app_data.duckdb` & `analytics.duckdb`)
Füge in `state_manager.py` (`_init_db()`) eine idempotente Schema-Migration ein, um bestehende Presets, Window-States und Feature-Store-Einträge bruchfrei auf die neuen Präfixe umzustellen:


# In StateManager._init_db():
renames_plugins = {
    "grid_lines": "srv_grid_lines",
    "proximity": "srv_proximity",
    "grid_levels": "srv_grid_levels",
    "ema_diff": "srv_ema_diff",
    "atr_normalized": "srv_atr_normalized",
}
renames_indicators = {
    "fixed_grid_proximity": "ind_fixed_grid_proximity",
    "grid_liquidity": "ind_fixed_grid_proximity",
    "multi_ma": "ind_multi_ma",
}

# 1. indicator_presets mappen
for old_id, new_id in renames_indicators.items():
    con.execute("UPDATE indicator_presets SET indicator_id = ? WHERE indicator_id = ?", [new_id, old_id])

for old_id, new_id in renames_plugins.items():
    con.execute("UPDATE indicator_presets SET plugin_id = ? WHERE plugin_id = ?", [new_id, old_id])

# 2. analytics.duckdb -> feature_store.feature_id mappen
con_analytics = DbPool.get(DB_ANALYTICS)
for old_id, new_id in renames_plugins.items():
    con_analytics.execute("UPDATE feature_store SET feature_id = ? WHERE feature_id = ?", [new_id, old_id])

### Schritt 4: Header-Standardisierung

Stelle sicher, dass in allen umbenannten Dateien ganz oben ein einheitlicher Kommentar-Header vorhanden ist:


# ==============================================================================
# DEFINITION: [srv_grid_lines / ind_fixed_grid_proximity]
# ==============================================================================
# NAME:        [z. B. Grid Lines Service]
# KATEGORIE:   [z. B. Swing Points/Preis-Grid]
# BESCHREIBUNG: [Kurze Beschreibung]
#
# PARAMETER:
#   - step_size (float, Def: 0.5): Schrittweite der Grid-Rasterlinien
# ==============================================================================


## 4. Verifikation (Harte Projekt-Regeln)

1. **Statischer Check (Keine UI-Tests):**

python -m py_compile analytics/features/definitions/srv_*.py chart/indicators/ind_*.py state_manager.py

2. **Backend-/DB-Test in `test/test.py`:**
* Teste das Laden von Plugins über `PluginRegistry().get("srv_grid_lines")`.
* Teste das Laden von Indikator-Presets mit den neuen `ind_`-Präfixen.
* **Rule 4:** Keine GUI starten; Verifikation erfolgt per Terminal/py_compile.

---

# Kapitel 16.08.01 – Review & Finale Entscheidungen (07.08.2026, kritische Prüfung gegen Ist-Code)

> **Status:** Kapitel 16.08.01 ist ein **Konzept/Plan**, keine Umsetzung. Der Ist-Code wurde kritisch geprüft (Ist-Dateien, PluginRegistry, FeatureBuilder, StateManager, chart_win, serviceui). Es wurden **4 kritische Inkonsistenzen** (N1–N4) und **5 Konkretisierungen** (N5–N9) gefunden. Die Entscheidungen **N1–N9 sind final** (Anwender-Review, 07.08.2026) und verbindlich für die Umsetzung. **Coding startet erst nach ausdrücklichem Startbefehl des Anwenders.**

## 1. Kritische Inkonsistenzen der Matrix (N1–N4)

### N1: `grid_levels` / `ema_diff` / `atr_normalized` sind KEINE Plugin-Services → NICHT umbenennen
* **Ist-Befund:** Diese drei Dateien erben von **`BaseFeature`** (`analytics/features/base_feature.py`), NICHT von `PluginFeature`. Sie besitzen **kein `plugin_id`-Property** und werden **nicht** über die `PluginRegistry` geladen (der `PluginLoader` entdeckt ausschließlich `PluginFeature`-Subklassen). Stattdessen registriert sie `FeatureBuilder.features` (`feature_builder.py:449–453`).
* **DB-Vertrag:** Ihre `name`-Werte sind **feste Spaltennamen** des `feature_store`: `ema_diff DOUBLE`, `atr_normalized DOUBLE` (`db_service.py:237/239`) sowie `GRID_COLUMNS` für `grid_levels`. `FeatureStoreReader.NATIVE_COLUMNS = ("ema_diff", "rsi_14", "atr_normalized")` (`feature_store_reader.py:50`).
* **Entscheidung:** Diese drei Dateien werden **NICHT** auf `srv_*` umbenannt und ihre `name`-Properties bleiben unverändert (DB-Schema-Invariante). Die Matrix-Tabelle A wird auf die **zwei echten Plugin-Services** (`grid_lines_service`, `proximity_service`) reduziert. Ein Datei-Rename ohne Identifier-Wechsel wäre reine Kosmetik, bräche aber Imports (`feature_builder.py:26–28`, `definitions/__init__.py`) ohne fachlichen Nutzen → unterbleibt.

### N2: `fixed_grid_proximity` – die `indicator_id` ist BEREITS `ind_fixed_grid_proximity`
* **Ist-Befund:** `fixed_grid_proximity.py` nutzt bereits `indicator_id`/`plugin_id` = `"ind_fixed_grid_proximity"` (Zeilen 161/174/188). Die Phase-16-Migration `grid_liquidity → ind_fixed_grid_proximity` ist bereits in `state_manager.py:118–151` und `chart_win.py:212–224` umgesetzt.
* **Entscheidung:** Für diesen Indikator ist nur noch der **Dateiname** `fixed_grid_proximity.py → ind_fixed_grid_proximity.py` nötig (plus Imports in `chart_win.py:37/42` und `indicators/__init__.py`). Kein Identifier-Wechsel, keine DB-Migration.

### N3: `multi_ma` – Ist-ID ist `ind_moving_averages`, NICHT `multi_ma`/`ind_multi_ma`
* **Ist-Befund:** `multi_ma.py` definiert `_INDICATOR_ID = "ind_moving_averages"` (Zeile 48) und ist in `chart_win.py` (8×), `indicator_dialog.py` sowie `test/test.py` etabliert. Die Matrix-Angabe „alte `indicator_id` = `multi_ma`" existiert im Ist-Code **nicht**.
* **Entscheidung:** Die ID **`ind_moving_averages`** bleibt (ist bereits `ind_`-präfixiert und konform). Nur der **Dateiname** wird `multi_ma.py → ind_moving_averages.py` umbenannt (Dateiname = Identifier). Eine zusätzliche Migration auf `ind_multi_ma` würde alle 8 `chart_win`-Referenzen + Presets + Tests brechen → unterbleibt.

### N4: DB-Migration muss `service_sets`-JSON mitmigrieren
* **Ist-Befund:** `ServiceSetRepository` persistiert vollständige `ServiceSetDefinition`-JSONs (mit `plugin_id` je `services`-Instanz) in `service_sets`, `service_sets_trash`, `service_set_history` (`service_set_repository.py:236–268`). Die Anleitung in Schritt 3 migriert nur `indicator_presets` + `feature_store` – **gespeicherte Sets blieben mit alten `plugin_id`-Referenzen zurück** und würden ins Leere zeigen (Service-Sperre `_sets_using_plugin` fände sie nicht mehr).
* **Entscheidung:** Die Migration wird **additiv** um `service_sets`/`service_sets_trash`/`service_set_history` erweitert (JSON-`services[].plugin_id` mappen, idempotent).

## 2. Konkretisierungen (N5–N9)

### N5: `srv_`-Umbenennung betrifft exakt 2 Services
| Datei | Neuer Name | `plugin_id` alt → neu | Weitere Anpassungen |
|---|---|---|---|
| `grid_lines_service.py` | `srv_grid_lines.py` | `grid_lines` → `srv_grid_lines` | `metadata["indicator_id"]` ist bereits `ind_fixed_grid_proximity` (konform, unverändert) |
| `proximity_service.py` | `srv_proximity.py` | `proximity` → `srv_proximity` | `dependencies = ["grid_lines"]` → `["srv_grid_lines"]` |

### N6: Abhängigkeits-/Referenzketten (Pflicht bei Umbenennung)
* `chart/indicators/fixed_grid_proximity.py`: `service_plugin_ids = ["grid_lines", "proximity"]` → `["srv_grid_lines", "srv_proximity"]`; interne Service-Defs (`"plugin_id": "grid_lines"` / `"proximity"`, Zeilen 449/458) → `srv_*`.
* `analytics/background_workers/live_analyzer.py:231–234`: harte Logik `if plugin_id == "proximity": depends_on=["grid_lines"]` → auf `srv_proximity`/`srv_grid_lines`.
* `analytics/engine/analytics_view_model.py:173`: `["grid_lines", "proximity"]` → `["srv_grid_lines", "srv_proximity"]`.
* `analytics/statistics_repository.py:4/11`: `feature_id='proximity'` → `srv_proximity`.
* `chart/indicator_dialog.py:1400`: Import `from analytics.features.definitions.grid_lines_service import map_custom_levels_to_prox_levels` → `srv_grid_lines`.
* `analytics/engine/service_models.py` (Docstring-Beispiele), `serviceui/service_set_utils.py`, `serviceui/master_tree.py`, `serviceui/run_worker.py`, `serviceui/service_win.py`, `serviceui/service_selector_dialog.py`, `analytics/engine/service_selector_model.py`, `db_service.py:248`, `state_manager.py:98` (Kommentare/Docstrings).

### N7: NICHT umbenennen (DB-/Schema-Invarianten)
* `feature_store`-Spalten `ema_diff`/`atr_normalized`/`rsi_14` (`db_service.py:237–239`), `FeatureStoreReader.NATIVE_COLUMNS`, `GRID_COLUMNS`, `analytics/ui/*`-Seiten-Referenzen → **bleiben exakt**.
* `metadata["indicator_id"] = "ind_fixed_grid_proximity"` in beiden Grid-Services → bereits konform.

### N8: `ind_`-Indikator-Matrix (korrigiert)
| Alter Dateiname | Neuer Dateiname | `indicator_id` |
|---|---|---|
| `fixed_grid_proximity.py` | `ind_fixed_grid_proximity.py` | bereits `ind_fixed_grid_proximity` (unverändert) |
| `multi_ma.py` | `ind_moving_averages.py` | `ind_moving_averages` (unverändert) |

### N9: Verifikation (headless, Regel 4)
* `py_compile` auf `srv_grid_lines.py`/`srv_proximity.py`/`ind_*.py`/`state_manager.py`/`chart_win.py`/`indicator_dialog.py`.
* `test/test.py`: Teil 14 (P16.08.01) – `PluginRegistry().get("srv_grid_lines")`, `srv_proximity` + `dependencies=["srv_grid_lines"]`, Indikator-Presets `ind_moving_averages`/`ind_fixed_grid_proximity`, `service_sets`-JSON-Migration (Duck-Typ-Stubs), `service_plugin_ids`-Auflösung.
* `node --check` nur bei JS-Berührung (hier nicht betroffen).
* Keine UI-Tests / keine Regressionstests (Regel 4).

> **Kein Coding:** Die Entscheidungen sind dokumentiert. Eine Umsetzung von 16.08.01 erfolgt erst nach ausdrücklichem Startbefehl des Anwenders.


