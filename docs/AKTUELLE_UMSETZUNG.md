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


