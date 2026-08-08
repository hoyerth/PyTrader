# Phase 17: Services und Analytics-Finalisierung

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 17)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase17_step1`, `phase17_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `../../test`.
3. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
4. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
5. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db_service.py`) – eine Verbindung pro Thread und DB-Datei.
6. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
7. **Concurrency-Guard & Timer-Pausierung:** Solange im ServiceWindow intensive Service-Berechnungen laufen (`ServiceRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
8. **Isolierter Test-Workspace:** Alle neuen Test-Python-Dateien und temporären Test-Datenbanken (`*.duckdb`) müssen strikt im Unterordner `../../test` erzeugt, gelesen und abgelegt werden – niemals im Projekt-Root oder im `../../data`-Ordner.
9. **Open/Closed-Principle & Code-Preserving:** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden und bestehende Kern-Klassen bleiben geschützt.
10. **Test-Cleanup (Entscheidung 06.08.2026):** Tests werden NICHT dauerhaft aufbewahrt. Nach Abschluss jedes Phasenkapitels wird der Ordner `../../test` aufgeräumt – es bleibt ausschließlich die Datei `../../test/test.py` (dauerhafter Test-Harness) bestehen.
11. **Naming Conventions & PineScript-Input-Zone:** 
    * Services in `../../analytics/features/definitions` nutzen strikt das Präfix `srv_` (`plugin_id = "srv_..."`).
    * Indikatoren in `../../chart/indicators` nutzen strikt das Präfix `ind_` (`indicator_id = "ind_..."`).
    * Füllwörter (`service`, `plugin`, `indicator`) entfallen im Dateinamen.
    * Das `parameter_schema` liegt direkt am Dateianfang unter dem Header-Docstring.
    * Jedes Service-Plugin deklariert `metadata["category"]` für die dynamische Kategorie-Ordner-Struktur im MasterTree.
---

# 17.01 Grouped Swing Services (Feature Store Architecture)

## 1. Executive Summary & Strategie

Konsolidierung aller Swing-, Wendepunkt- und Volumenstruktur-Verfahren in **3 hochperformante Core-Services**:

1. `srv_swing_structure` (Klassische & Geometrische Preis-Swings)
2. `srv_swing_momentum` (Dynamik-, MA-Hysterese- & Trailing-Swings)
3. `srv_swing_volume_profile` (Profil-, LVN-, Grid- & Anchored-VWAP-Swings)

**Hauptzweck:** Reine Datenlieferanten für die **Analytics-UI** und spätere **Machine-Learning-Pipelines (XGBoost/LightGBM)**. Eine direkte Chart-Visualisierung ist **nicht** Bestandteil dieses Kapitels. Dedizierte Chart-Indikatoren (`ind_...`) werden erst nach statistischer Validierung der erzeugten Features entwickelt.

---

## 2. Invarianten, Causal Timestamps & PineScript-Standard

1. **Präfix & Pfad:** `analytics/features/definitions/srv_*.py` mit `plugin_id = "srv_<name>"` (ohne Wörter wie *service* oder *plugin*).
2. **PineScript-Input-Zone:** `parameter_schema` steht **direkt als erstes Attribut auf Klassenebene** unter dem Header-Docstring (vor `plugin_id` / `metadata`).
3. **MasterTree-Kategorie:** Deklaration von `metadata["category"]` für den rekursiven Baumaufbau.
4. **Causal Timestamping (Kein Look-ahead Bias für ML):**
* `event_bar_time`: Zeitpunkt (Epoch) des tatsächlichen Extremums.
* `confirmation_bar_time`: Zeitpunkt (Epoch), an dem das Signal mathematisch/kausal feststand (`bar_time` der aktuellen Kerze).
* `confirmation_lag_bars`: Dynamisch berechnete Differenz in Bars (`params["right_bars"]` bzw. Modus-Verzögerung).
* Kerzen am Serienanfang ohne ausreichenden Lookback/Lookahead erhalten `calculation_status = "INSUFFICIENT_DATA"` und `is_swing_* = False`


5. **Primary Key & DB-Persistenz:** Zur konfliktfreien Speicherung mehrerer Services auf derselben Kerze ist der Primary Key im `feature_store` exakt `(symbol, timeframe, bar_time, feature_id)`.

> **Hinweis (07.08.2026, UMGESETZT):** Die PK-Migration wurde durchgeführt – der `feature_store` hat jetzt den 4-Spalten-PK `(symbol, timeframe, bar_time, feature_id)` mit `feature_id VARCHAR NOT NULL` (Sentinel `'native'` für klassische Feature-Builder-Rows; verifiziert, 677.713 Zeilen verlustfrei migriert, Backup `../../data/backup_analytics_20260807.duckdb`). Details in Kapitel 7.1.


---

## 3. Die 3 Konsolidierten Swing Services

### A. `srv_swing_structure.py` (Geometrische & Preis-Swings)

* **Verwendungszweck:** Erfasst lokale Extrema über Fraktale, Pivots, Gann Swings, Period Extrema (PDH/PWH) und ZigZag.
* **MasterTree:** `category: "Swing Points/Geometrie"`

# ==============================================================================
# DEFINITION: srv_swing_structure
# ==============================================================================
# NAME:        Swing Structure Service
# KATEGORIE:   Swing Points/Geometrie
# BESCHREIBUNG: Extrahierte Swing Highs/Lows über Fraktale, Pivots, Gann & ZigZag
# ==============================================================================

import pandas as pd
from typing import Dict, Any
from analytics.features.plugins.base_plugin import PluginFeature

class SrvSwingStructure(PluginFeature):
    # INPUT-PARAMETER & DEFAULTS (PINESCRIPT-ZONE - KLASSENANFANG)
    parameter_schema = {
        "mode": {
            "type": str,
            "default": "Williams_Fractal",
            "options": ["Williams_Fractal", "Standard_Pivot", "Gann_Mechanical", "ZigZag_ATR", "ZigZag_Pct", "Period_Extrema"],
            "description": "Erkennungs-Modus für Strukturswings"
        },
        "left_bars": {
            "type": int,
            "default": 2,
            "min": 1,
            "description": "Anzahl erforderlicher Kerzen links mit niedrigeren Hochs / höheren Tiefs"
        },
        "right_bars": {
            "type": int,
            "default": 2,
            "min": 1,
            "description": "Anzahl Bestätigungskerzen rechts (bestimmt dynamisch confirmation_lag_bars)"
        },
        "atr_period": {"type": int, "default": 14, "min": 1, "description": "ATR-Periode für ZigZag_ATR"},
        "atr_mult": {"type": float, "default": 2.0, "min": 0.1, "description": "ATR-Multiplikator für ZigZag_ATR"},
        "change_pct": {"type": float, "default": 0.5, "min": 0.05, "description": "Mindestprozentbewegung für ZigZag_Pct"},
        "period_extrema_type": {
            "type": str,
            "default": "PREVIOUS_CLOSED",
            "options": ["PREVIOUS_CLOSED", "CURRENT_DEVELOPING"],
            "description": "PREVIOUS_CLOSED (z. B. PDH/PWH final) oder CURRENT_DEVELOPING"
        }
    }

    plugin_id = "srv_swing_structure"
    plugin_version = "1.0.0"
    
    metadata = {
        "display_name": "Swing Structure Service",
        "category": "Swing Points/Geometrie",
        "description": "Erfasst Fraktal-, Pivot-, Gann- und ZigZag-Extrema für die Struktur-Analyse"
    }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any], context=None):
        pass


---

### B. `srv_swing_momentum.py` (Dynamik- & MA-Hysterese Swings)

* **Verwendungszweck:** Erfasst Richtungswechsel über Glättungs-Hysteresen (alle 12 MA-Typen), Steigungswechsel und Trailing-Stops.
* **MasterTree:** `category: "Swing Points/Dynamik & Filter"`

# ==============================================================================
# DEFINITION: srv_swing_momentum
# ==============================================================================
# NAME:        Swing Momentum Service
# KATEGORIE:   Swing Points/Dynamik & Filter
# BESCHREIBUNG: Wendepunkts-Erkennung über MA-Hysteresen, Steigungswechsel & Chande-Kroll
# ==============================================================================

import pandas as pd
from typing import Dict, Any
from analytics.features.plugins.base_plugin import PluginFeature

class SrvSwingMomentum(PluginFeature):
    # INPUT-PARAMETER & DEFAULTS (PINESCRIPT-ZONE - KLASSENANFANG)
    parameter_schema = {
        "mode": {
            "type": str,
            "default": "MA_Peak_Hysteresis",
            "options": ["MA_Peak_Hysteresis", "MA_Slope_Change", "Chande_Kroll_Ratchet"],
            "description": "Algorithmus-Modus für Momentum-Swings"
        },
        "ma_type": {
            "type": str,
            "default": "EHMA",
            "options": ["SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA", "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"],
            "description": "Gleitender Durchschnittstyp (MA-Template 16.04)"
        },
        "period": {"type": int, "default": 14, "min": 2, "description": "Berechnungsperiode für Glättungs-MA"},
        "piv_maxMaMovePct": {
            "type": float,
            "default": 0.2,
            "min": 0.01,
            "description": "Erforderliche Gegenbewegung in % für MA Peak Pivot (gültig für alle ma_type-Optionen)"
        },
        "chande_lookback": {
            "type": int,
            "default": 10,
            "min": 1,
            "description": "Lookback-Periode für Highest-High/Lowest-Low im Chande_Kroll_Ratchet Modus"
        },
        "x_atr": {"type": float, "default": 3.0, "min": 0.5, "description": "ATR-Multiplikator für Chande Kroll Stops"}
    }

    plugin_id = "srv_swing_momentum"
    plugin_version = "1.0.0"
    
    metadata = {
        "display_name": "Swing Momentum Service",
        "category": "Swing Points/Dynamik & Filter",
        "description": "Dynamische Momentum-Swings via MA-Hysterese, Steigung & Chande Kroll"
    }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any], context=None):
        pass


---

### C. `srv_swing_volume_profile.py` (Volumen-, Grid- & VWAP-Swings)

* **Verwendungszweck:** Berechnet POC/VAH/VAL, Low Volume Nodes (LVNs), Raster-Annäherungen und Anchored VWAP Bänder.
* **MasterTree:** `category: "Swing Points/Volumen & Grid"`

# ==============================================================================
# DEFINITION: srv_swing_volume_profile
# ==============================================================================
# NAME:        Swing Volume Profile Service
# KATEGORIE:   Swing Points/Volumen & Grid
# BESCHREIBUNG: Berechnet POC/VAH/VAL, LVN-Rejections, Grid-Proximity und Anchored VWAP
# ==============================================================================

import pandas as pd
from typing import Dict, Any
from analytics.features.plugins.base_plugin import PluginFeature

class SrvSwingVolumeProfile(PluginFeature):
    # INPUT-PARAMETER & DEFAULTS (PINESCRIPT-ZONE - KLASSENANFANG)
    parameter_schema = {
        "mode": {
            "type": str,
            "default": "Volume_Profile",
            "options": ["Volume_Profile", "Grid_Proximity", "Anchored_VWAP"],
            "description": "Haupt-Berechnungsmodus"
        },
        "profile_period": {
            "type": str,
            "default": "Sessions",
            "options": ["Bars", "Sessions", "Days", "Weeks", "Months"],
            "description": "Profil-Zeitraum (nur aktiv bei mode == 'Volume_Profile')"
        },
        "period_val": {"type": int, "default": 1, "min": 1, "description": "Multiplier für profile_period"},
        "volume_source": {
            "type": str,
            "default": "tick_volume",
            "options": ["tick_volume", "real_volume"],
            "description": "Volumenquelle aus MT5 (standardmäßig tick_volume)"
        },
        "volume_thresh_pct": {"type": float, "default": 5.0, "min": 0.5, "description": "Mindestvolumenanteil in % für Cluster"},
        "value_area_pct": {"type": float, "default": 0.70, "min": 0.1, "max": 1.0, "description": "Value Area Abdeckung (0.70 = 70%)"},
        "lvn_sensitivity": {"type": float, "default": 0.20, "min": 0.05, "description": "Schwellwert für Low Volume Nodes"},
        "grid_step": {"type": float, "default": 0.5, "min": 0.01, "description": "Rasterabstand (nur bei mode == 'Grid_Proximity')"},
        "vwap_anchor": {
            "type": str,
            "default": "Session_Start",
            "options": ["Session_Start", "Week_Start", "Month_Start"],
            "description": "Ankerpunkt (nur bei mode == 'Anchored_VWAP')"
        },
        "vwap_band_mult": {"type": float, "default": 2.0, "min": 0.1, "description": "StDev-Multiplikator für VWAP-Bänder"}
    }

    plugin_id = "srv_swing_volume_profile"
    plugin_version = "1.0.0"
    
    metadata = {
        "display_name": "Swing Volume Profile Service",
        "category": "Swing Points/Volumen & Grid",
        "description": "Volumengewichtetes Profil mit POC/VAH/VAL, LVNs, Grid & Anchored VWAP"
    }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any], context=None):
        pass


---

## 4. Verbindlicher Feature-Store-Datenvertrag (`analytics.duckdb`)

Jeder Service schreibt seine Ergebnisse strukturiert in das JSON-Feld `feature_data`.

### 4.1 Gemeinsamer Basisvertrag (Trägt jeder Record):


{
  "result_type": "SWING | LEVEL | ZONE | REJECTION | VWAP",
  "source_mode": "Williams_Fractal | MA_Peak_Hysteresis | Volume_Profile | ...",
  "calculation_status": "OK | INSUFFICIENT_DATA | MISSING_MTF_CONTEXT",
  
  "is_swing_high": false,
  "is_swing_low": false,
  "is_rejection": false,
  
  "event_bar_time": 1770000000,
  "confirmation_bar_time": 1770000120,
  "confirmation_lag_bars": 2,
  "confirmation_type": "FRACTAL | PIVOT | CAUSAL | SESSION_CLOSE | NONE",
  
  "price": 28.50,
  "strength_value": 2.1,
  "strength_type": "ATR_MULTIPLE | PERCENT | PRICE_DISTANCE | VOLUME_RATIO | NORMALIZED"
}


### 4.2 Modus-Spezifische Zusatzfelder:

* **Bei `srv_swing_volume_profile` (Volume_Profile):**
* `volume_source`: `"tick_volume" | "real_volume"`
* `poc_price`: `float` | `null`
* `vah_price`: `float` | `null`
* `val_price`: `float` | `null`
* `lvn_price`: `float` | `null`
* `is_lvn_swing`: `bool`


* **Bei `srv_swing_volume_profile` (Grid_Proximity):**
* `grid_price`: `float`


* **Bei `srv_swing_volume_profile` (Anchored_VWAP):**
* `vwap_price`: `float`
* `vwap_upper`: `float`
* `vwap_lower`: `float`

---

## 5. Verifikation & Harte Regeln

1. **Statischer Syntax-Check (keine UI-Tests):**

python -m py_compile analytics/features/definitions/srv_swing_structure.py analytics/features/definitions/srv_swing_momentum.py analytics/features/definitions/srv_swing_volume_profile.py

2. **Backend-Integrationstest in `../../test/test.py`:**
* Prüfe Registrierung über `PluginRegistry().get("srv_swing_structure")` (definiert in `../../analytics/features/feature_builder.py`).
* Prüfe Baumaufbau in `ServiceSelectorModel().build_tree()` (definiert in `../../analytics/engine/service_selector_model.py`).

3. **Keine GUI-/UI-Tests ausführen (Harte Regel 4).**

---

## 6. Konsistenzprüfung & Entscheidungen (07.08.2026, 17:44) – 17.01 Review

> **Implementierungs-Log (Review, kein Coding):** Am 07.08.2026 wurde Kapitel 17.01 gegen den realen Quellcode und `../../data/analytics.duckdb` geprüft (Schema-Abfragen, Write-/Lese-Pfade, `base_plugin.py`, bestehende Service-Muster `srv_grid_lines`/`srv_proximity`, DuckDB-Fähigkeiten). Ergebnis: **Kapitel ist inhaltlich stimmig, aber §2.5 (PK) ist ein Migrations-Ziel und die Service-Snippets in §3 weichen in 4 Punkten von den Laufzeit-Konventionen ab.** Die folgenden Entscheidungen sind **verbindlich** für die Umsetzung; es wurde kein Code geändert.

### E-1 (BLOCKER): `feature_store`-PK-Migration auf `(symbol, timeframe, bar_time, feature_id)`

* **Befund:** Ist-PK = `(symbol, timeframe, bar_time)`; `feature_id` ist NULLABLE. Damit kann heute **max. 1 Service je Bar** gespeichert werden (letzter Writer gewinnt). `../../data/analytics.duckdb`: 677.713 Zeilen – `srv_proximity` 593.627, `srv_grid_lines` 81.086, native Rows ohne feature_id 3.000.
* **Befund (DuckDB 1.5.5):** `ALTER TABLE ... DROP PRIMARY KEY` wird **nicht** unterstützt (ParserError, verifiziert). Einzig praktikables Verfahren ist **Table-Rewrite + RENAME** (verifiziert in `test/check_pk_migration.py`).
* **Migrations-Schritt 17.01.0 (verbindliche Reihenfolge):**
  1. Backup: Git-Tag `phase17_step0` + Kopie von `../../data/analytics.duckdb` nach `../../data/backup_analytics_20260807.duckdb`.
  2. Sentinel für native Alt-Rows: `UPDATE feature_store SET feature_id = 'native' WHERE feature_id IS NULL;`
  3. `CREATE TABLE feature_store_new` mit **identischer Spaltenliste** (alle 30 Spalten) + `feature_id VARCHAR NOT NULL` + `PRIMARY KEY (symbol, timeframe, bar_time, feature_id)`.
  4. `INSERT INTO feature_store_new (…) SELECT … FROM feature_store;` (Spalten 1:1, feature_id bereits durch Schritt 2 gesetzt).
  5. `DROP TABLE feature_store;` + `ALTER TABLE feature_store_new RENAME TO feature_store;`
  6. **Write-Pfade in `../../analytics/features/feature_builder.py` umstellen** (sonst BinderException nach Migration):
     * `store_plugin_payload()`: `ON CONFLICT (symbol, timeframe, bar_time)` → `ON CONFLICT (symbol, timeframe, bar_time, feature_id)`.
     * `store_features()` (nativer Pfad): Insert-Spalten um `feature_id` erweitern (Wert `'native'` je Zeile) und Konfliktziel auf 4 Spalten.
  7. **Reader-Exclusions für den Sentinel `'native'`** (sonst erscheint er in UI-Listen): `feature_store_reader.get_available_features()` und `fetch_last_execution_dates()` um `AND feature_id != 'native'` ergänzen (`statistics_repository.get_available_sets()` filtert bereits über `feature_data IS NOT NULL` – native Rows bleiben dort automatisch außen vor).
* **Verifikation:** Test in `../../test/test.py`: (a) 2 Services auf derselben Bar koexistieren nach Migration (4-Spalten-Upsert), (b) 3-Spalten-`ON CONFLICT` wirft nach Migration BinderException, (c) `feature_id != 'native'`-Filter liefert keine Sentinel-IDs.

### E-2: `parameter_schema` – String-Typen statt Klassen

* **Befund (verifiziert):** Die Snippets in §3 verwenden `"type": str/int/float` (Klassen). `base_plugin.validate_params()` prüft aber `p_type == "float"` **string-vergleichend** → Klassen-Typen werden **nicht** konvertiert (`validate_params({'atr_mult': '2.5'})` liefert den String `'2.5'`). Bestehende Services (`_GRID_LINES_SCHEMA`, `_PROXIMITY_SCHEMA`) verwenden korrekt `"type": "float"`.
* **Entscheidung:** Alle `type`-Werte in den 3 Services als **Strings** `"float" | "int" | "bool" | "str"` deklarieren (Konvention `ParameterSchema`/`base_plugin.py`).

### E-3: `parameter_schema` – Modul-Konstante + flache Kopie (M1)

* **Befund:** Klassenattribut-Dict im Snippet = geteiltes mutable Dict (Verletzung der M1-Regel „kein geteiltes mutable Dict über Instanzen", dokumentiert in `srv_grid_lines.py`/`srv_proximity.py`).
* **Entscheidung:** PineScript-Input-Zone bleibt am Dateianfang, aber als **Modul-Konstante** `_SWING_STRUCTURE_SCHEMA` / `_SWING_MOMENTUM_SCHEMA` / `_SWING_VOLUME_PROFILE_SCHEMA`; `parameter_schema` als Property, die `{k: dict(v) for k, v in _SCHEMA.items()}` zurückgibt (exakt das bestehende Muster).

### E-4: `plugin_version` entfällt; `version`-Property bleibt (Basis-Default)

* **Befund:** `plugin_version = "1.0.0"` im Snippet ist toter Ballast – die Basisklasse liefert `version` (= `"1.0.0"`), und die Payloads bauen mit `self.version` (`store_plugin_payload` liest `payload["plugin_version"]`).
* **Entscheidung:** Snippets korrigieren: `version` als Property (nur überschreiben, falls abweichend), `plugin_version`-Attribut **streichen**. `plugin_id` als Property im bestehenden Stil (`@property def plugin_id`) ODER Klassenattribut ist zulässig (funktioniert, verifiziert), Konvention ist die Property.

### E-5: `capabilities` explizit deklarieren (reine Datenlieferanten)

* **Befund:** Snippets definieren kein `capabilities` → es würden die Basis-Defaults `chart=True, live=True, render=True` erben; der MasterTree zeigte dann irreführend „📌 im \<Service>" obwohl §1 explizit „keine Chart-Visualisierung in diesem Kapitel" fordert.
* **Entscheidung:** Alle 3 Services deklarieren explizit:
  `capabilities = {"chart": False, "batch": True, "live": False, "feature_store": True, "render": False}`
  (analog `srv_grid_lines`/`srv_proximity`, zusätzlich `chart=False`, da noch kein Indikator existiert). `indicator_name`/`indicator_id` in `metadata` entfallen bis zur Indikator-Phase (Open/Closed: dann neue `ind_...`-Datei).

### E-6: `metadata` vollständig (Vollschema analog bestehender Services)

* **Befund:** Snippet-`metadata` enthält nur `display_name`/`category`/`description`; die Basis-Defaults (`author`, `tags`, `description_long`, `condition_rules`, `api_version`) greifen bei Klassenattribut-Override nicht.
* **Entscheidung:** Alle 3 Services liefern das Vollschema (Keys analog `srv_grid_lines`/`srv_proximity`), inkl. `description_long` und `condition_rules` je Modus.

### E-7: `schema_version`-Pflichtfeld im Datenvertrag (§4 ergänzen)

* **Befund:** `base_plugin.py` (Phase 15 U15-A1, Invariante 5): `schema_version` ist **Pflichtfeld** für alle Plugins mit `feature_store=True`; der Reader (`feature_store_reader._normalize_feature_data`) setzt nur den Default für Alt-Rows. §4 spezifiziert es nicht.
* **Entscheidung:** §4.1 ergänzen: Jeder `feature_store_payload.metadata` trägt `"schema_version": "1.0.0"` (SemVer major.minor.patch, exakt wie `srv_grid_lines`/`srv_proximity`). Optionales Feld `statistics` (P16.01 `status_info`-Semantik) wird als erlaubt deklariert, ist aber kein Pflichtfeld.

### E-8: Verifikation §5 erweitern

* `py_compile` zusätzlich auf `../../analytics/features/feature_builder.py` und `../../analytics/engine/feature_store_reader.py` (geänderte Pfade aus E-1).
* Test in `../../test/test.py`: Koexistenz zweier Swing-Services auf derselben Bar (PK-Migration), `PluginRegistry().get(...)` für alle 3 IDs, `build_tree()` enthält die Kategorien `Swing Points/Geometrie`, `Swing Points/Dynamik & Filter`, `Swing Points/Volumen & Grid`.
* Test-Cleanup nach Abschluss des Kapitels (Invariante 10): nur `../../test/test.py` bleibt bestehen; `test/check_pk_migration.py` wird als Referenz für E-1 während der Umsetzung vorgehalten und danach entfernt.

### Ergebnis der Prüfung (sonstige Bereiche)

* §1, §2 (1–4), §3-Kategorien, §4-Vertragsfelder und §5-Prüfpunkte sind **konsistent** mit `base_plugin.py`, `PluginLoader` (Dateinamen-unabhängige Discovery), `PluginRegistry`, `ServiceSelectorModel._category_parts` (Slash-Pfade) und den bestehenden Service-Mustern.
* Lese-Pfade (`feature_store_reader`, `statistics_repository`, `analytics_repository`) filtern über `feature_id`/`bar_time` und bleiben nach E-1 funktionsfähig – einzige Anpassung sind die Sentinel-Exclusions (E-1.7).
* Klassenname `SrvSwingStructure` funktioniert (Discovery über `issubclass(PluginFeature)`, `inspect.isabstract`); optional wäre `SwingStructureService` (Muster `GridLinesService`/`ProximityService`) – keine Pflichtänderung.

---

## 7. Implementierungs-Log 17.01 (07.08.2026, 18:45) – Umsetzung E-1..E-8

> **Implementierungs-Log (Coding):** Alle Entscheidungen E-1..E-8 aus Kapitel 6 wurden am 07.08.2026 umgesetzt und headless verifiziert. Es wurden NUR additive Anpassungen vorgenommen; auskommentierter/alter Code blieb erhalten.

### 7.1 E-1 (BLOCKER) – PK-Migration `feature_store` (UMGESETZT)

* **Migration ausgeführt** via `test/migrate_pk.py` (dynamischer Spaltenaufbau aus der DB, Table-Rewrite + RENAME, da DuckDB 1.5.5 kein `DROP PRIMARY KEY` kann):
  * Sentinel: 3.000 native Alt-Rows → `feature_id='native'`.
  * Kopiert: **677.713 Zeilen** (Verlustfrei, Spalten 1:1).
  * Neuer PK: `PRIMARY KEY(symbol, timeframe, bar_time, feature_id)`; `feature_id VARCHAR NOT NULL` (verifiziert via `duckdb_constraints()`).
  * Positivtest im Skript: 4-Spalten-Upsert (2 Services auf derselben Bar) erfolgreich.
* **Backup:** `../../data/backup_analytics_20260807.duckdb` (98,8 MB) + Git-Tag `phase17_step0` (Review-Commit).
* **`../../db_service.py`** (`check_and_init_databases`): Basis-`CREATE TABLE IF NOT EXISTS feature_store` auf 4-Spalten-PK + `feature_id VARCHAR NOT NULL DEFAULT 'native'` aktualisiert (No-op für die migrierte DB, korrektes Schema für neue DBs). Die alten `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`-Statements bleiben als idempotente No-ops erhalten.
* **`../../analytics/features/feature_builder.py`** (Write-Pfade):
  * `store_features()` (nativer Pfad): setzt `feature_id='native'` je Zeile, Insert-/Select-Spalten + `ON CONFLICT (symbol, timeframe, bar_time, feature_id)`.
  * `store_plugin_payload()`: `ON CONFLICT (symbol, timeframe, bar_time, feature_id)`.
* **`../../analytics/engine/feature_store_reader.py`** (Sentinel-Exclusions):
  * Neue Konstante `SENTINEL_NATIVE = "native"`.
  * `fetch_last_execution_dates()` und `get_available_features()` schließen `feature_id != 'native'` aus (Sentinel erscheint nicht in MasterTree/UI-Listen).
  * `statistics_repository.get_available_sets()` benötigte keine Änderung (filtert bereits über `feature_data IS NOT NULL`).

### 7.2 E-2..E-6 – Die 3 Swing-Services (NEU, Scaffold)

* **Neue Dateien** in `../../analytics/features/definitions` (alle registriert, verifiziert):
  * `srv_swing_structure.py` – `SrvSwingStructure`, `category: "Swing Points/Geometrie"`.
  * `srv_swing_momentum.py` – `SrvSwingMomentum`, `category: "Swing Points/Dynamik & Filter"`.
  * `srv_swing_volume_profile.py` – `SrvSwingVolumeProfile`, `category: "Swing Points/Volumen & Grid"`.
* **E-2:** `type`-Werte als Strings (`"int"`, `"float"`, `"str"`) → `validate_params()` konvertiert korrekt.
* **E-3:** PineScript-Input-Zone als Modul-Konstante (`_SWING_STRUCTURE_SCHEMA` etc.); `parameter_schema` liefert eine flache Kopie (`{k: dict(v) ...}`, M1-konform).
* **E-4:** `plugin_version`-Attribut entfällt; `version`-Property (`"1.0.0"`). `plugin_id` als Property.
* **E-5:** `capabilities = {"chart": False, "batch": True, "live": False, "feature_store": True, "render": False}` – keine irreführenden „📌 im …"-Badges.
* **E-6:** `metadata` mit Vollschema (author, tags, `description_long`, `condition_rules` je Modus, `api_version`).
* **`calculate()`:** Scaffold – validiert Parameter und liefert strukturell korrekten `feature_store_payload` mit `schema_version` (E-7), `records=[]` (0 persistierte Zeilen). Die konkreten Swing-Algorithmen (Williams-Fraktal, ZigZag, Volume Profile …) werden in einem Folge-Schritt nach statistischer Validierung der Feature-Store-Grundlage umgesetzt (entspricht dem Kapitel-Fokus auf Architektur/Invarianten).

### 7.3 E-7 – `schema_version` im Datenvertrag

* In §4.1 dokumentiert und in allen 3 Services als `metadata["schema_version"] = "1.0.0"` gesetzt (Pflichtfeld U15-A1/Invariante 5; Reader-Default `SCHEMA_VERSION_DEFAULT` deckungsgleich).

### 7.4 E-8 – Verifikation (headless, keine UI-Tests)

* `py_compile` PASS auf: `srv_swing_structure.py`, `srv_swing_momentum.py`, `srv_swing_volume_profile.py`, `feature_builder.py`, `feature_store_reader.py`, `../../db_service.py`, `../../test/test.py`.
* `../../test/test.py` **Teil 14 (8/8 PASS)**:
  * T1: `PluginRegistry().get(...)` für alle 3 IDs.
  * T2: `build_tree()` enthält die Kategorien `Swing Points/Geometrie`, `Swing Points/Dynamik & Filter`, `Swing Points/Volumen & Grid` (Pfad-basiert, Ordner rekursiv).
  * T3: Zwei Services koexistieren auf derselben Bar (4-Spalten-Upsert auf Test-DB).
  * T4: 3-Spalten-`ON CONFLICT` wirft nach Migration `BinderException` (Negativtest).
  * `check_and_init_databases()` läuft mit der migrierten DB fehlerfrei (Schema/Constraint-Verifikation).
* Vorbestehende Harness-FAILURES (P2/P5/H3/H4/H5/H7/T5 – Fenster-Geometrie/Info-Button aus früheren Teilen) sind unabhängig von 17.01 (keine berührten Komponenten; kein Regressionstest gemäß Harte Regel 4).

### 7.5 Test-Cleanup (Invariante 10, DURCHGEFUEHRT am 07.08.2026)

* **Durchgefuehrt** (Kapitel 17.01 + 17.01.01 abgeschlossen): Der Ordner `../../test`
  enthaelt ausschliesslich `../../test/test.py` (dauerhafter Harness, inkl. Teile 13-15).
* Entfernt: `check_pk_migration.py` (E-1-Referenz), `migrate_pk.py`,
  `check_init_compat.py`, `check_stylepicker_16_06.py`, `_insert_part14.py`,
  `_fix_part14.py`, `_fix_part14b.py`, `_insert_part15.py`, `_fix_part15_t5.py`,
  `_inspect_tree_lines.py`, `_append_doc_part8.py`, `_commit_msg_step3.txt`,
  `_tree_lines_out.txt`, Laufprotokolle (`_part15_run.txt`, `_baseline_run.txt`,
  `_verify_run.txt`), `__pycache__`.
* Verifiziert nach Cleanup: `py_compile test/test.py` PASS; Testlauf identisch
  zur Baseline (17.01/17.01.01 T1-T4 PASS, nur die 6 bekannten, unbeteiligten
  Harness-FAILURES P2/P5/H3/H4/H5/H7).

---

# 17.01.01 MasterTree Refactoring: Cleanup Standalone & Root Node Rename

## 1. Zielsetzung & Anpassungen
1. **Entfernung der Redundanz:** Die Gruppe `⚡ Standalone Services` (`GROUP_STANDALONE`) entfällt ersatzlos, da alle Plugins über `metadata["category"]` bereits sauber in Ordner einsortiert werden[cite: 1, 2].
2. **Kompakte Root-Label:**
   * `"📁 Service-Sets"` ➔ **`"📁 Sets"`**[cite: 1, 2]
   * `"📦 Alle verfügbaren Plugins"` / `"Alle verfügbaren Services"` ➔ **`"📦 Services"`**[cite: 1, 2]

---

## 2. Code-Anpassungen in `../../analytics/engine/service_selector_model.py`

### Schritt 1: Konstanten & Hilfsmethoden bereinigen
* Entferne die Konstante `GROUP_STANDALONE = "standalone"`[cite: 1, 2].
* Entferne die Methode `get_standalone_plugin_ids()` vollständig (keine Aufrufe mehr vorhanden)[cite: 1, 2].

### Schritt 2: `build_tree()` auf 2 Root-Knoten reduzieren
Passe `build_tree()` so an, dass nur noch zwei schlanke Gruppen erzeugt werden[cite: 1, 2]:

# In ServiceSelectorModel.build_tree():

# 1. Sets-Gruppe mit neuem Root-Label
set_nodes = [...]  # (bestehende Set-Erzeugung bleibt unverändert)

# 2. Kategorisierte Services-Gruppe
plugin_nodes = self._category_nodes(sorted(self.get_plugins().keys()))

return [
    {
        "group": self.GROUP_SETS, 
        "label": "📁 Sets", 
        "children": set_nodes
    },
    {
        "group": self.GROUP_PLUGINS, 
        "label": "📦 Services", 
        "children": plugin_nodes
    },
]


---

## 3. UI-Absicherung (`../../serviceui/master_tree.py`)

Falls im `MasterTree` oder im `ServiceSelectorWidget` noch explizite String- oder Group-Checks auf `"standalone"` oder den alten Label-Text existieren, entferne diese bzw. passe sie auf `self.GROUP_PLUGINS` (`"plugins"`) und `"📁 Sets"` / `"📦 Services"` an.

---

## 4. Verifikation (Harte Regeln)

1. **Statischer Syntax-Check:**

python -m py_compile analytics/engine/service_selector_model.py serviceui/master_tree.py


2. **Isolierter Baum-Test in `../../test/test.py`:**
* Lade `ServiceSelectorModel().build_tree()`.
* **Assert:** Der Baum enthält exakt **2 Root-Elemente** mit den Labels `"📁 Sets"` und `"📦 Services"`.
* **Assert:** Kein Element besitzt mehr die Gruppe `"standalone"`.

3. **Keine GUI-Tests ausführen (Rule 4).**



---

# 8. Implementierungs-Log 17.01.01 (07.08.2026, ~19:40) - MasterTree Refactoring UMGESETZT

**Ziel:** Die ehemalige Root-Gruppe `⚡ Standalone Services` (`GROUP_STANDALONE`)
entfaellt ersatzlos; der MasterTree besitzt danach genau **2 Root-Gruppen**:
`📁 Sets` und `📦 Services` (Root-Label-Rename von
`📦 Alle verfuegbaren Plugins`). Alle Plugins werden ausschliesslich ueber
`metadata["category"]` in Kategorie-Ordner einsortiert (K1/K2, 16.08).

## 8.1 Aenderungen in `../../analytics/engine/service_selector_model.py`

* **Konstante `GROUP_STANDALONE = "standalone"` entfernt** (ersatzlos; Kommentar
  an der Gruppen-Konstanten-Stelle dokumentiert die Entscheidung).
* **Hilfsmethode `get_standalone_plugin_ids()` entfernt** (keine Aufrufer mehr).
* **`build_tree()`** liefert nur noch 2 Root-Dicts:
  1. `{"group": GROUP_SETS, "label": "📁 Sets", "children": set_nodes}`
  2. `{"group": GROUP_PLUGINS, "label": "📦 Services", "children": plugin_nodes}`
  – `plugin_nodes` weiterhin via `_category_nodes(sorted(plugins.keys()))`
  (Kategorie-Ordner + flache Blaetter, sortiert nach K8).
* Docstring der Methode aktualisiert (2-Gruppen-Kontrakt).

## 8.2 Aenderungen in `../../serviceui/master_tree.py`

* **`_build_child_item()`:** Bedingung
  `if group in (self.model.GROUP_STANDALONE, self.model.GROUP_PLUGINS):`
  ersetzt durch `if group == self.model.GROUP_PLUGINS:` (die Standalone-Gruppe
  existiert nicht mehr; Plugin-Zeilen kommen nur noch aus `GROUP_PLUGINS`).
* **Header-Docstring (Spalte 0):** `⚡ Standalone Services` entfernt,
  Plugin-Gruppe als `📦 Alle verfuegbaren Services (kategorisierte Ordner)`
  beschrieben.
* `_populate()` und Kontextmenue-Logik sind generisch ueber `build_tree()` –
  keine weiteren Anpassungen noetig.

## 8.3 Verifikation (headless, keine UI-Tests)

* **Syntax:** `py_compile` auf beiden Dateien – PASS.
* **`../../test/test.py` Teil 15 (NEU, 4 Checks):**
  * T1) `GROUP_STANDALONE` existiert nicht mehr – PASS.
  * T2) build_tree liefert genau 2 Root-Gruppen mit Labels
    `📁 Sets` / `📦 Services` – PASS.
  * T3) Keine Gruppe `"standalone"` in build_tree – PASS.
  * T4) Swing-Services (Teil 14) in der Hauptgruppe: Kategorie-Ordner
    `Swing Points/...` + flache Blaetter koexistieren, keine leeren Ordner – PASS.
* **`../../test/test.py` Teil 13/14 angepasst:** `P16.08 T5` erwartete 4 Ordner-
  Knoten (plugin_a mit Kategorie A/B in BEIDEN Gruppen). Da die Standalone-
  Gruppe entfaellt, erscheint plugin_a nur noch einmal -> Erwartung auf
  **2 Ordner-Knoten** korrigiert (Kommentar aktualisiert). Alle P16.08 T1..T5
  und 17.01 T1..T4 weiterhin PASS.
* **Verbleibende 6 Harness-FAILURES** (unbeteiligt, PersistentWindow-Position/
  -Groesse, vor 17.01 bereits vorhanden): P2, P5, H3, H4, H5, H7.

## 8.4 Test-Cleanup (DURCHGEFUEHRT, Invariante 10)

* Test-Cleanup durchgefuehrt (siehe 7.5): `../../test` enthaelt nur noch
  `../../test/test.py`. Kapitel 17.01 + 17.01.01 sind damit abgeschlossen.
* Naechste Kapitel (Roadmap): 17.02 Trend Services.


---

# 9. Implementierungs-Log 17.01.02 (07.08.2026) - Services-Gruppen-Funktionalitaet + Swing-Erkennung UMGESETZT

**Ziel:** Die User-Meldungen aus der Testrunde zu 17.01 (E-1..E-8) aufloesen:
(1) Kategorie-Ordner im MasterTree waren nur Deko – jetzt Info-Button +
Run-Aktionen (Teil 1); (2) "Service ausfuehren" lieferte keine Ergebnisse
("srv_swing_structure: fertig (kein Feature-Store-Payload), Fertig: 0
Feature-Row(s) im feature_store") – Ursache war der Scaffold aus 17.01
(records=[]); die echte Swing-Erkennung ist jetzt implementiert (Teil 2).

---

## 9.1 Teil 1 – Services-Gruppen-Funktionalitaet (commit a8b8563, phase17_step5)

### Aenderungen in `../../analytics/engine/service_selector_model.py`
* **NEU `category_plugin_ids(path)`:** Liefert rekursiv alle Plugin-IDs unter
  einem Kategorie-Pfad (Praefix-Matching, case-insensitiv, deterministisch
  sortiert). Grundlage fuer "Alle Services ausfuehren" eines Ordners.

### Aenderungen in `../../serviceui/master_tree.py`
* **3 neue Signale:** `run_plugin_requested(plugin_id)`,
  `run_category_requested(path)`, `category_info_requested(path)`.
* **NEU `_category_path_of(item)`:** Voller Kategorie-Pfad aus der Parent-Kette
  (z. B. `Swing Points/Geometrie`).
* **Info-Button auch auf Kategorie-Ordnern** (bisher nur Set-Zeilen) ->
  emittiert `category_info_requested`.
* **Kontextmenue erweitert:**
  * Ordner-Knoten: `Alle Services ausfuehren` (run_category_requested) +
    `Ordner-Info anzeigen`.
  * Plugin-Zeilen: `Diesen Service ausfuehren` (run_plugin_requested) +
    `Service-Info anzeigen`.

### Aenderungen in `../../serviceui/service_win.py`
* **Handler:** `_on_run_plugin` (Mini-Definition, Single-Run),
  `_on_run_category` (Ad-hoc-Definition, Set-Run aller Services im Ordner),
  `_on_category_info_requested` (Read-Only-Kategorie-Info).
* Alle mit Sicherheitsabfrage (Symbol/Timeframe) + `ServiceRunWorker`
  (FeatureStore-Persistenz + EventBus-Sync, wie der bestehende Set-Run).

---

## 9.2 Teil 2 – Echte Swing-Erkennung in `srv_swing_structure.py` (Bugfix "0 Feature-Row(s)")

### Problem
Der Scaffold aus 17.01 (E-1..E-8) lieferte `records=[]` in `calculate()`.
Daher: `srv_swing_structure: fertig (kein Feature-Store-Payload)` und
`Fertig: 0 Feature-Row(s) im feature_store` – fuer SILVER in keinem Timeframe.

### Umsetzung (Modul-Helfer + `calculate()` ersetzt)
* **Modul-Helfer (neu, vor der Klasse):**
  * `_atr_series(df, period)` – Wilder-ATR (EWM alpha 1/period, adjust=False).
  * `_detect_fractal(df, left, right)` – Williams-Fraktal / Standard-Pivot
    (lokale Extrema mit kausaler Bestaetigung nach `right` Bars).
  * `_detect_gann(df, left, right)` – Fenster-Extremum + Schlusskurs-Reversal.
  * `_detect_zigzag(df, threshold_for)` – klassischer ZigZag (alternierend),
    Umkehr-Schwelle als Callable (ATR- bzw. Prozent-Variante).
  * `_detect_period_extrema(df, extrema_type)` – PDH/PWH: `CURRENT_DEVELOPING`
    (laufende Tages-Extrema, CAUSAL) / `PREVIOUS_CLOSED`
    (Vortages-Level-Touch, SESSION_CLOSE).
* **`calculate()`:** Erkennung je `params['mode']` (6 Modi) + dichter
  Record-Satz **1 Record pro Bar** (Datenvertrag 17.01 §4):
  `bar_time, result_type="SWING", source_mode, calculation_status,
  is_swing_high, is_swing_low, is_rejection=False, event_bar_time,
  confirmation_bar_time, confirmation_lag_bars, confirmation_type, price,
  strength_value, strength_type`.
* **Kausale Zeitstempel:** `event_bar_time` = tatsaechliches Extremum,
  `confirmation_bar_time` = kausale Feststellung (>= event); Serienanfang
  (ohne Lookback/Lookahead) => `calculation_status='INSUFFICIENT_DATA'`.
* **Payload-metadata:** `schema_version="1.0.0"` (E-7-Pflichtfeld),
  `source_mode`, `total_swing_highs`, `total_swing_lows`, `bars`.

### Waehrend des Testens gefundene & behobene Bugs
1. **`pd.to_datetime(...)` liefert `DatetimeIndex`** – `.dt.date` existiert dort
   nicht (AttributeError in `_detect_period_extrema`); Zugriff jetzt ueber
   `.date` (ndarray aus `datetime.date`).
2. **PREVIOUS_CLOSED-Kausalitaet invertiert:** `confirmation_bar_time` lag VOR
   `event_bar_time`. Refactor: `swing_meta` traegt jetzt
   `(event_idx, conf_idx, lag, price)`; fuer PREVIOUS_CLOSED ist
   event = Vortages-Extremum-Bar, confirmation = die beruehrende Bar selbst
   (lag = Abstand event->confirmation).

### Verifikation (headless, keine UI-Tests)
* **Syntax:** `py_compile` auf `srv_swing_structure.py` und `../../test/test.py` – PASS.
* **`../../test/test.py` Teil 17 (NEU, 62 Checks):** 7 Modi-Konfigurationen
  (Williams_Fractal, Standard_Pivot, Gann_Mechanical, ZigZag_ATR,
  ZigZag_Pct, Period_Extrema/CURRENT_DEVELOPING, Period_Extrema/PREVIOUS_CLOSED)
  auf 864 synthetischen M5-Bars (3 Tage, Sinus + Wobble):
  * records dicht (`len(records) == 864`), Swing-Highs > 0, Swing-Lows > 0.
  * Kausale Zeitstempel (confirmation >= event) fuer ALLE Modi.
  * `schema_version == "1.0.0"`; Metadata totals == Summen der Flags.
  * Start-INSUFFICIENT_DATA fuer Lookback-Modi + Period_Extrema.
  * **T2: `store_plugin_payload` auf Test-DuckDB (`test/test_p17_swing.duckdb`,
    wird nach dem Test geloescht):** Rows == 864, `feature_data` ist JSON mit
    `result_type == "SWING"`.
* **Verbleibende 6 Harness-FAILURES** (unbeteiligt, PersistentWindow-Position/
  -Groesse, vor 17.01 bereits vorhanden): P2, P5, H3, H4, H5, H7.

## 9.3 Test-Cleanup
* `../../test` enthaelt wieder nur `../../test/test.py` (temporaere Helfer/Logs/Test-DB
  entfernt). Kapitel 17.01.02 ist damit abgeschlossen.
* Naechste Kapitel (Roadmap): 17.02 Trend Services.

## 9.4 Teil 3 (07.08.2026, 2. Bugfix-Runde) - srv_swing_momentum + srv_swing_volume_profile + Worker-Meldung

### Problem (User-Meldungen)
1. `srv_swing_momentum`: "FEHLER bei Ausfuehrung - Keine OHLCV-Daten fuer SILVER H1"
2. `srv_swing_volume_profile`: identische Fehlermeldung
3. `srv_swing_structure` funktionierte (56.751 Rows) -> Daten waren vorhanden.

**Root Cause:** Beide Services waren noch **Scaffold** aus 17.01 (records=[]).
Der `ServiceRunWorker` meldete bei `stored == 0` pauschal `Keine OHLCV-Daten`,
obwohl die Quelle gefuellt war. Zwei Fixes: echte Erkennung in beiden Services
+ Meldungs-Differenzierung im Worker.

### Aenderungen in `../../analytics/features/definitions/srv_swing_momentum.py`
* **Scaffold ersetzt** durch echte Erkennung, 3 Modi (Datenvertrag 17.01 §4,
  dichte Record-Reihe, kausale Zeitstempel, INSUFFICIENT_DATA am Start):
  * `MA_Peak_Hysteresis`: MA-Serie ueber `MATemplateEngine.calculate_ma`
    (alle 12 Typen, VWMA nutzt tick_volume); Pivot erst bei Gegenbewegung
    >= `piv_maxMaMovePct` % (strength PERCENT).
  * `MA_Slope_Change`: Vorzeichenwechsel der MA-Steigung (strength NORMALIZED).
  * `Chande_Kroll_Ratchet`: Trailing-Stop = Highest-High/Lowest-Low ueber
    `chande_lookback` +- `x_atr` x ATR (strength ATR_MULTIPLE).
* Modul-Helfer: `_atr_series`, `_detect_ma_hysteresis`, `_detect_ma_slope`,
  `_detect_chande_kroll`.
* **Bugfix waehrend Tests:** Warmup-NaN (z. B. SMA/WMA/HMA/EHMA/ZLEMA/KAMA/
  ALMA/VWMA) liess die Hysterese dauerhaft auf NaN haengen -> 0 Swings.
  Fix: erstes finites MA-Extremum als Startpunkt.

### Aenderungen in `../../analytics/features/definitions/srv_swing_volume_profile.py`
* **Scaffold ersetzt** durch echte Erkennung, 3 Modi (Zusatzfelder §4.2):
  * `Volume_Profile`: entwickelndes Profil je `profile_period` (Bars/Sessions/
    Days/Weeks/Months) mit POC/VAH/VAL, LVN-Detektion (`lvn_sensitivity`),
    `is_lvn_swing`; Felder volume_source/poc_price/vah_price/val_price/
    lvn_price/is_lvn_swing.
  * `Grid_Proximity`: naechstes Rasterlevel (`grid_step`) + Level-Crossings;
    Feld grid_price.
  * `Anchored_VWAP`: VWAP ab Session/Week/Month-Start +- vwap_band_mult x
    StDev; Felder vwap_price/vwap_upper/vwap_lower; event=Anker-Bar.
* Modul-Helfer: `_volume_series`, `_profile_for`, `_group_ids`, `_anchored_vwap`.
* **Hinweis:** 'Sessions' wird ohne Session-Kalender als Kalendertag (24h)
  behandelt (Batch-Datenlieferant, dokumentiert im Header).
* **Bugfix waehrend Tests:** `DatetimeIndex` hat kein `.dt` (identisch zu
  srv_swing_structure) -> Formatierung direkt via `.strftime`.

### Aenderungen in `../../serviceui/run_worker.py`
* `_execute_timeframe` liefert jetzt `(stored, had_data)`.
* Single-TF-Fehler werden differenziert (17.01.02 Bugfix):
  * Quelle leer -> weiterhin `Keine OHLCV-Daten fuer ...` (bestehender Test
    U18 bleibt gruen).
  * Daten vorhanden, aber 0 Records -> praezise
    `Kein Feature-Store-Payload erzeugt fuer ... (Service lieferte 0 Records
    - Daten waren vorhanden)`.

### Verifikation (headless, keine UI-Tests)
* **Syntax:** `py_compile` auf den 3 Dateien + `../../test/test.py` – PASS.
* **`../../test/test.py` Teil 18 (NEU, 62 Checks):**
  * T1) momentum: 3 Modi dicht (864/864), Highs/Lows > 0, kausal, schema;
    alle 12 MA-Typen liefern Swings (> 0); Start-INSUFFICIENT_DATA.
  * T2) volume_profile: 3 Modi dicht + kausal + schema; Felder §4.2 je Modus;
    VA-Grenzen konsistent (vah >= poc >= val); VWAP upper >= vwap >= lower.
  * T3) `store_plugin_payload` auf Test-DuckDB: beide feature_ids mit
    konfliktfreiem 4-Spalten-PK (864 Rows je Feature auf derselben Bar).
  * T4) Worker-Meldung: Daten + 0 Records -> `Kein Feature-Store-Payload`
    (nicht `Keine OHLCV-Daten`).
* **DB-Investigations-Query (SILVER H1, data/analytics.duckdb):**
  srv_swing_momentum 56.751 Bars (1.070/1.070), srv_swing_structure 56.751
  (7.527/7.793), srv_swing_volume_profile 56.751 (19.325/4.947). Die Asymmetrie
  des Volume-Profile-Services ist bedingt durch `close >= vah` als
  Swing-High-Definition bei vorwiegend oberhalb der VA liegenden Schluessen
  (Default-Modus) – statistisch zu beobachten (17.02).
* **Verbleibende 6 Harness-FAILURES** (unbeteiligt): P2, P5, H3, H4, H5, H7.

## 9.5 Test-Cleanup (2. Runde)
* `../../test` enthaelt wieder nur `../../test/test.py` (temporaere Helfer/Logs/Test-DBs
  entfernt). Kapitel 17.01.02 ist mit allen 3 Swing-Services abgeschlossen.
* Naechste Kapitel (Roadmap): 17.02 Trend Services.


---

# 10. Implementierungs-Log 17.01.03 (07.08.2026) - Bugfix-Runde 2: i-Button Plugin-Zeilen + Datum letzter Run UMGESETZT (commit b7eb3c2, phase17_step8)

**Ziel:** Zwei User-Meldungen aus der Testrunde zu 17.01.02 aufloesen:
(a) Der i-Button auf Einzelservice-Zeilen unter `?? Services` oeffnete den
Info-/Beschreibungsdialog nie; (b) das Datum des letzten Runs blieb im
MasterTree dauerhaft `--.--.--`, obwohl Services erfolgreich gelaufen waren.

---

## 10.1 Bug a) - i-Button bei Einzelservices unter "Services" oeffnete keinen Dialog

### Ursache
`_resolve_info_plugin()` in `../../serviceui/service_win.py` (@1825) nutzte
`PluginRegistry()` ohne Import - `NameError` zur Laufzeit. Der umgebende
`except (RuntimeError, AttributeError)` im Signal-Handler
`_on_tree_info_requested()` (@1739) fing den `NameError` nicht (gehoert zur
Klasse `Exception`, nicht zu den aufgelisteten Ausnahmen), daher wurde der
`ServiceDescriptionEditDialog` nie erzeugt. Headless-Probe reproduzierte den
exakten `NameError`.

### Fix
* `../../serviceui/service_win.py`: **Lokaler Import**
  `from analytics.features.feature_builder import PluginRegistry`
  in `_resolve_info_plugin()` ergaenzt (konsistent zu den uebrigen
  Verwendungsstellen in der Datei; keine weiteren Aenderungen).

### Verifikation (headless, keine UI-Tests)
* `../../test/test.py` **Teil 19 T1 (NEU):** `_on_tree_info_requested("", "",
  "srv_grid_lines")` mit gefaketem `ServiceDescriptionEditDialog.exec`
  (kein Modal-Loop) -> Dialog wird genau 1x mit Titel
  `Service-Beschreibung bearbeiten` aufgerufen (kein NameError); zusaetzlich
  liefert `_resolve_info_plugin()` das Plugin korrekt zurueck. PASS.

---

## 10.2 Bug b) - Datum letzter Run blieb nach Multi-Service-Run `--.--.--`

### Root Cause (bewiesen mit realen DB-Daten)
Die PK-Migration (17.01 E-1, `test/migrate_pk.py` - nicht im Repo) entfernte
den `created_at`-Spalten-DEFAULT der `feature_store`-Tabelle (real in
`../../data/analytics.duckdb`: `column_default = None`). `store_plugin_payload()`
setzte `created_at = now()` **nur im ON CONFLICT-Zweig**; bei NEUEN Rows blieb
`created_at = NULL`. Beleg real: `srv_swing_momentum` = 56.751 Rows,
0x mit `created_at` (nicht NULL). `fetch_last_execution_dates()` ueberspringt
NULL-Werte -> `MAX(created_at)` fehlt -> `ServiceSelectorModel.refresh()`
liefert kein Datum -> MasterTree zeigt `--.--.--`. Betroffen waren exakt
Services, die erstmals oder ueber einen Kategorie-Ordner ausgefuehrt wurden.

### Fix 1 - `../../analytics/features/feature_builder.py` (`store_plugin_payload` @606)
* `created_at = now()` wird jetzt **explizit als Spalte** im INSERT/SELECT
  mitgefuehrt, damit auch NEUE Rows einen gueltigen `created_at`-Wert erhalten
  (robust fuer alle DB-Staende, auch ohne Spalten-DEFAULT).
* ON CONFLICT-Zweig (Update mit `created_at = now()`) unveraendert.

### Fix 2 - `../../db_service.py` (`check_and_init_databases` @187)
* **Idempotente Reparatur** des verlorenen Spalten-DEFAULTs direkt nach den
  ADD COLUMN-Statements (@261):
  `ALTER TABLE feature_store ALTER created_at SET DEFAULT current_timestamp`
  in `try/except` mit WARN-Log. Laueft beim App-Start (`main.py:238`) und
  stellt den Default auf allen Bestands-Datenbanken wieder her.

### Verifikation (headless, keine UI-Tests)
* `../../test/test.py` **Teil 19 T2 (NEU, 5 Checks):**
  * Test-DB `test/test_p19_created_at.duckdb` mit `created_at TIMESTAMP`
    OHNE Default (migrierter Zustand, wird vom Test selbst erzeugt/geloescht).
  * Fix 2: `ALTER ... SET DEFAULT current_timestamp` repariert - Pruefung
    `column_default` == `current_timestamp`. PASS.
  * Fix 1: `store_plugin_payload()` schreibt 1 Row (neuer PK-Konflikt-freier
    Datensatz). PASS.
  * `FeatureStoreReader.fetch_last_execution_dates()` liefert fuer den
    Service ein Datum (created_at gesetzt). PASS.
  * `created_at` in der DB ist nicht NULL. PASS.
* **DB-Layer / Cross-Thread / kompletter UI-Pfad** (ServiceWindow +
  `event_bus.service_set_changed` -> `refresh()` -> `data_changed` ->
  `_populate()` -> Labels aktualisiert): alle headless PASS.
* **Gesamtlauf `../../test/test.py`:** 339 PASS; unveraenderte 6 vorbestehende
  Harness-FAILURES (P2, P5, H3, H4, H5, H7 - PersistentWindow-Position/
  -Groesse, offscreen-bedingt, unabhaengig von diesen Fixes; H3 erwartet
  `_keep_history_on_close == True`, seit History-Bugfix 06.08.2026 absichtlich
  `False`).

---

## 10.3 Status & Test-Cleanup (3. Runde)
* **Commit `b7eb3c2`** (phase17_step8) enthaelt die 3 Fix-Dateien
  (`feature_builder.py`, `../../db_service.py`, `service_win.py`) - gepusht.
* `../../test/test.py` bleibt der einzige Test-Harness in `../../test` (Teil 19
  ergaenzt, lauffaehig); temporaere Helfer (z. B. `test/_ins19.py`) und
  Test-DBs (`test_p19_created_at.duckdb`) wurden entfernt bzw. werden vom
  Test selbst aufgeraeumt (Invariante 10).
* **Doku-Freigabe:** Dieser Eintrag wurde erst nach erfolgreichem manuellem
  Funktionstest des Anwenders erstellt (Regel C: Doku nach Freigabe).
* Naechste Kapitel (Roadmap): 17.02 Trend Services.

---

# 11. Implementierungs-Log 17.01.04 (07.08.2026) - Dynamic Parameter Schema Exposure fuer die 3 Swing-Services UMGESETZT

**Ziel:** Die Spalten-UI (`../../serviceui/param_columns.py` / `ServiceSelectorWidget`)
liest Parameter-Definitionen ueber `plugin.full_parameter_schema()` bzw.
`plugin.default_params`. Damit die Swing-Services ihr `parameter_schema`
unabhaengig von der jeweiligen Definitions-Art (Property ODER Klassen-Attribut)
zuverlaessig ueber die Basisklassen-Methoden bereitstellen, wurden die
Schema-Exposure-Eigenschaften explizit in allen 3 Service-Klassen verankert.

---

## 11.1 Befund (Pruefung der Anweisung gegen den Ist-Code)

* **Kein akuter UI-Bug:** Alle 3 Services (`srv_swing_structure.py`,
  `srv_swing_momentum.py`, `srv_swing_volume_profile.py`) definieren
  `parameter_schema` bereits als **Property** (flache Kopie der Modul-Konstante
  `_SWING_*_SCHEMA`, M1-konform). `full_parameter_schema()` und
  `default_params` funktionieren damit bereits ueber die Basisklasse
  (`base_plugin.PluginFeature`) – der in der Aufgabe beschriebene Leer-Spalten-
  Fall (parameter_schema als reines Klassen-Attribut ohne Basisklassen-Anbindung)
  existiert im Ist-Stand nicht (verifiziert per Registry-Lauf).
* **Praeventiver Fix:** Die expliziten Overrides machen den Vertrag
  selbst-dokumentierend und robust gegen spaetere Refactorings (z. B.
  Umstellung auf Klassen-Attribut-Schema wie in den §3-Snippets).
* **Basisklassen-Vertrag bewahrt:** Die exakt vorgeschlagene Variante
  `full_parameter_schema() -> self.parameter_schema` wuerde den Basis-Parameter
  `lookback` aus dem vollstaendigen Schema verwerfen. `SchemaMigrator.
  migrate_instance_config()` (`../../analytics/engine/schema_migrator.py`) verlaesst
  sich jedoch auf `lookback` im Voll-Schema. Daher wird die **Basisklassen-
  Semantik** beibehalten: `full_parameter_schema()` = `base_parameter_schema`
  (lookback) + `parameter_schema` (Plugin). `default_params` liefert die
  Plugin-Defaults (bewusst OHNE lookback, da lookback eine Instanz-
  Einstellung `cfg['lookback']` ist und nie in `params` geschrieben wird,
  vgl. `param_columns._on_param_changed` / `service_win.collect_set_definition`).

## 11.2 Aenderungen in den 3 Service-Klassen

* **`../../analytics/features/definitions/srv_swing_structure.py`** (`SrvSwingStructure`),
  **`srv_swing_momentum.py`** (`SrvSwingMomentum`),
  **`srv_swing_volume_profile.py`** (`SrvSwingVolumeProfile`):
  jeweils direkt unter der `parameter_schema`-Property ergaenzt:
  * `@property def default_params` – extrahiert die Defaults aus
    `parameter_schema` (`{k: v.get("default") for k, v in ... if "default" in v}`).
  * `def full_parameter_schema()` – liefert das vollstaendige Schema
    (Basis-Parameter wie `lookback` + plugin-spezifisch) inkl. Min/Max/Typ
    fuer die UI-Spalten (Basisklassen-Vertrag, `dict(self.base_parameter_schema)`
    gemerged mit `dict(self.parameter_schema or {})`).
* Kommentarblock `# 2. SCHEMA-EXPOSURE FÜR DIE UI (07.08.2026, Bugfix)`
  dokumentiert Zweck und Vertrag in jeder Klasse.

## 11.3 Verifikation (headless, keine UI-Tests)

* **Syntax:** `python -m py_compile` auf den 3 Service-Dateien + `../../test/test.py` – PASS.
* **`../../test/test.py` Teil 20 (NEU, 12 Checks, alle PASS):** fuer alle 3 Services:
  * T1) `full_parameter_schema()` nicht leer.
  * T2) `default_params` befuellt (`left_bars` / `period` / `grid_step`).
  * T3) `lookback` im `full_parameter_schema()` enthalten (Basisklassen-Vertrag,
    `SchemaMigrator`-Kompatibilitaet).
  * T4) `lookback` NICHT in `default_params` (Instanz-Einstellung, gehoert
    nicht in `params`).
* **Isolierter Registry-Check:** `PluginRegistry().get(...)` fuer alle 3 IDs
  mit den Assertions aus der Aufgaben-Verifikation – PASS.
* **Gesamtlauf `../../test/test.py`:** 351 PASS; unveraenderte 6 vorbestehende
  Harness-FAILURES (P2, P5, H3, H4, H5, H7 - PersistentWindow-Position/
  -Groesse, offscreen-bedingt, dokumentierte Baseline) – keine neuen Fehler.
* **Test-Cleanup (Invariante 10):** temporaeres Helfer-Skript
  (`test/_fix_part20_comments.py`) entfernt; `../../test` enthaelt wieder nur
  `../../test/test.py` (Teil 20 ergaenzt).
* Naechste Kapitel (Roadmap): 17.02 Trend Services.

---

# 12. Implementierungs-Log 17.01.05 (07.08.2026) - Bugfix: Standalone-Plugin-Editor im ServiceWindow (Parameter anzeigen/editieren/speichern unter "Services") UMGESETZT

**Ziel:** User-Meldung aus der Testrunde aufloesen: Ein Klick auf einen
Service unter dem Knoten "Services" (auch in Kategorie-Ordnern wie
`Swing Points/Geometrie`) zeigte **keine Parameter** in der rechten
Parameter-Spalte. Anforderungen:
a) Parameter in der Box anzeigen,
b) voll editierbar inkl. Speichern,
c) Edit-/Speichern-Buttons nur bei Wert-Aenderung sichtbar (wie bei "Sets").

---

## 12.1 Root Cause

* `MasterTree` emittiert bei einem Klick auf eine Plugin-Zeile
  `selection_changed("", "")` (leere IDs – Plugin-Zeilen haben kein Set) UND
  `selection_details(node_type, set_id, service_id, plugin_id)`.
* `_on_master_selection()` im ServiceWindow leerte bei leerem `set_id` sofort
  den Editor (`_clear_set_editor()`).
* Das `selection_details`-Signal (traegt die `plugin_id`) war im ServiceWindow
  **nicht verdrahtet** (nur im `ServiceSelectorDialog`). Dadurch ging die
  Plugin-Auswahl verloren und die Parameter-Spalte blieb leer.

## 12.2 Aenderungen

### `../../state_manager.py` (additiv, +29 Zeilen)
* **NEU `save_global_value(key, value)`** – persistiert einen beliebigen
  JSON-faehigen Wert unter `key` in `global_settings` (INSERT ... ON CONFLICT).
* **NEU `get_global_value(key, default=None)`** – liest den Wert (oder `default`).
* Verwendet fuer die Standalone-Plugin-Parameter des ServiceWindows
  (Key `plugin_params_<plugin_id>`): Parameter + lookback + Beschreibung eines
  Plugins ohne Set werden hier persistiert (NICHT in Service-Sets).

### `../../serviceui/service_win.py` (additiv, +203 Zeilen)
* **NEU Feld `_current_plugin_editing: Optional[str] = None`** – haelt die
  `plugin_id`, sofern gerade ein Standalone-Plugin im Editor geladen ist.
* **`_wire_selector_toolbar()`:** `tree.selection_details` jetzt mit
  `_on_master_selection_details` verdrahtet (vorher nur im Dialog).
* **`_on_master_selection()`:** Guard – bei leerem `set_id` wird der
  Plugin-Editor NICHT geleert, wenn `_current_plugin_editing` gesetzt ist
  (sonst ueberschreibt die leere `selection_changed` den gerade geladenen
  Plugin-Editor).
* **NEU `_on_master_selection_details(node_type, set_id, service_id, plugin_id)`:**
  Slot fuer das `selection_details`-Signal. Bei `node_type == "plugin"` wird
  `_load_plugin_editor(plugin_id)` aufgerufen; jede andere Zeile beendet den
  Plugin-Modus.
* **NEU `_plugin_config(plugin_id)`** – baut eine `ServiceInstanceConfig`:
  Registry-Defaults (params/lookback/version) gemerged mit gespeicherten
  Werten aus `global_settings` (`plugin_params_<pid>`: lookback, params,
  optionale description).
* **NEU `_load_plugin_editor(plugin_id)`** – baut eine Ad-hoc-Definition
  (nur dieser eine Service) und zeigt sie editierbar in der rechten Spalte
  (`load_set_into_editor`). Unbekanntes Plugin -> Log + Editor leeren.
* **NEU `_save_plugin_params() -> bool`** – persistiert die aktuellen
  Editor-Werte via `collect_set_definition()` nach `global_settings`
  (Key `plugin_params_<pid>`), entfernt die Dirty-Marker.
* **`_save_params_from_panel()`:** Plugin-Modus -> `_save_plugin_params()`
  statt `ServiceSetRepository.save_set`.
* **`_save_and_run_from_panel()`:** Plugin-Modus -> speichert und startet NUR
  den einen Service (Bestätigungsdialog wie beim Set-Run).
* **`_on_run_plugin()` / `_on_run_category()`:** nutzen jetzt
  `self._plugin_config(pid)` (gespeicherte Werte statt leerer Config).
* **`_clear_set_editor()`:** setzt `_current_plugin_editing = None`.
* **`_save_instance_description()`:** Plugin-Modus -> `_save_plugin_params()`.

### Dirty-State / Buttons (bestehender Mechanismus, keine neue Logik)
* Die Speichern-Buttons (`btn_save_params` / `btn_save_run_params`) werden
  weiterhin nur bei einer manuellen Parameter-Aenderung eingeblendet
  (`_mark_service_dirty` -> `_set_param_actions_visible(True)`) und nach dem
  Speichern wieder ausgeblendet (`_clear_dirty_markers`).

## 12.3 Verifikation (headless, keine UI-Tests)

* **Syntax:** `python -m py_compile` auf `../../serviceui/service_win.py`,
  `../../state_manager.py`, `../../test/test.py` – PASS.
* **`../../test/test.py` Teil 21 (NEU, 19 Checks, alle PASS):**
  * T1-T3) `_plugin_config` Defaults (params befuellt, lookback=1000, version).
  * T4) Plugin-Zeile `srv_swing_structure` im MasterTree gefunden
    (Kategorie-Ordner, rekursive Suche).
  * T5-T7) Klick-Simulation (`_emit_selection_details`) -> `_current_plugin_editing`
    gesetzt, Editor geladen (execution_order = nur das Plugin), Parameter-
    Spalten aufgebaut.
  * T8) **Guard:** `_on_master_selection("", "")` leert den Plugin-Editor NICHT.
  * T9-T11) Parameter aendern (User-Pfad) -> Dirty-State, Speichern-Buttons
    sichtbar.
  * T12-T15) `_save_plugin_params()` -> `global_settings` (`plugin_params_<pid>`),
    gespeicherte Werte in `_plugin_config` gemerged.
  * T16-T17) `_save_and_run_from_panel` im Plugin-Modus (QMessageBox gefaket):
    speichert + startet Worker mit `plugin_id` und gespeicherten Werten.
  * T18) `_on_run_plugin` nutzt gespeicherte Params.
  * T19) Nicht-Plugin-Zeile beendet den Plugin-Modus.
* **Gesamtlauf `../../test/test.py`:** 370 PASS; unveraenderte 6 vorbestehende
  Harness-FAILURES (P2, P5, H3, H4, H5, H7 - PersistentWindow-Position/
  -Groesse, offscreen-bedingt, dokumentierte Baseline) – keine neuen Fehler.
* **Test-Cleanup (Invariante 10):** temporaere Helfer
  (`test/_tmp_insert21.py`, `test/_part21_block.txt`) entfernt; `../../test`
  enthaelt wieder nur `../../test/test.py` (Teil 21 ergaenzt).
* **Doku-Freigabe:** Dieser Eintrag wurde erst nach erfolgreichem manuellem
  Funktionstest des Anwenders erstellt (Regel C: Doku nach Freigabe).
* Naechste Kapitel (Roadmap): 17.02 Trend Services.

---

# 13. Implementierungs-Log 17.01.05 (07.08.2026) - UI-Dropdown + Conditional Visibility + Read-only Info-Label im ServiceWindow UMGESETZT

**Ziel:** Die Parameter-Spalte des ServiceWindows fuer die Swing-Services
benutzerfreundlich ausbauen:
a) `options`-Schema-Felder (z. B. `mode`, `ma_type`, `vwap_anchor`) als
   **Dropdown (QComboBox)** statt QLineEdit anzeigen,
b) Parameter mit `visible_when`-Deklaration **modus-abhaengig ein-/ausblenden**
   (nur die fuer den gewaehlten Algorithmus relevanten Parameter zeigen),
c) eine **Read-only-Beschreibung** unter den Parametern anzeigen (display_name
   + description_long + aktueller Algorithmus + Algo-Beschreibung), die beim
   Mode-Wechsel live aktualisiert wird und bei langem Text sauber scrollt
   (behebt den „Text ab zweiter Zeile abgeschnitten"-Bug).

---

## 13.1 Aenderungen in `../../serviceui/param_columns.py`

### UI-Dropdown (QComboBox) fuer `options`-Schema-Felder
* **`_create_param_control()`:** Rendert jetzt **VOR** der Datentyp-Pruefung
  eine `QComboBox`, wenn `spec.get("options")` eine Liste/Tupel ist
  (`combo.addItems([str(o) for o in options])`). Dadurch erscheinen
  `type="str"` + `options`-Felder der Swing-Services (z. B. `mode`,
  `ma_type`) als Dropdown statt als unbequemes QLineEdit (vorher fiel nur
  `type=="choice"` in die Dropdown-Branch).

### Conditional Visibility (`visible_when`)
* **NEU `_apply_conditional_visibility(iid)`:** Blendet Parameter, deren
  Schema-Eintrag `visible_when` traegt (z. B. `{"mode": ["ZigZag_ATR"]}`),
  modus-abhaengig ein/aus: passt der aktuelle Mode des i-ten Services zur
  deklarierten Mode-Liste -> Parameter sichtbar (Control + zugehoeriges
  Label), sonst ausgeblendet. Parameter OHNE `visible_when` bleiben immer
  sichtbar.
* **`_build_service_column()`:** Verdrahtet den `mode`-Combo via
  `currentTextChanged -> _apply_conditional_visibility(iid)`; das
  Voll-Schema des Services wird in `_mode_schemas[iid]` gespeichert.
  Labels werden in `_service_param_labels[(iid, key)]` referenziert.
* **`_clear_service_columns()`:** Setzt `_mode_schemas` und
  `_service_param_labels` zurueck (keine Alt-Referenzen beim naechsten Laden).
* **`visible_when`-Deklarationen in den 3 Swing-Services** (PineScript-Zone
  des `parameter_schema`, additiv):
  * `srv_swing_structure.py`: `atr_period`/`atr_mult` -> nur `ZigZag_ATR`,
    `change_pct` -> nur `ZigZag_Pct`, `left_bars`/`right_bars` -> nur
    Williams_Fractal/Standard_Pivot/Gann_Mechanical.
  * `srv_swing_momentum.py`: `piv_maxMaMovePct` -> nur `MA_Peak_Hysteresis`,
    `chande_lookback`/`x_atr` -> nur `Chande_Kroll_Ratchet`.
  * `srv_swing_volume_profile.py`: `profile_period`/`period_val`/
    `volume_source`/`volume_thresh_pct`/`value_area_pct`/`lvn_sensitivity`
    -> nur `Volume_Profile`, `grid_step` -> nur `Grid_Proximity`,
    `vwap_anchor`/`vwap_band_mult` -> nur `Anchored_VWAP`.

### Read-only Info-Label (QTextEdit + Scrollbar + Scroll-Top-Fix)
* **`_build_service_column()`:** Die Beschreibung wird jetzt als **read-only
  `QTextEdit`** gerendert (vorher QLabel): `setFrameShape(QTextEdit.NoFrame)`,
  transparenter Hintergrund via Stylesheet, `setWordWrapMode(
  QTextOption.WrapAtWordBoundaryOrAnywhere)`, horizontale Scrollbar aus,
  vertikale `ScrollBarAsNeeded`, Hoehe auf ~3 Zeilen gedeckelt
  (`setMaximumHeight`), damit die Spalte kompakt bleibt.
* **NEU `_update_service_info_label(iid)`:** Baut die HTML-Beschreibung aus
  dem `_mode_schemas[iid]`-Eintrag (display_name + description_long +
  aktueller `mode`-Algorithmus + Algo-Beschreibung) und setzt sie via
  `setHtml`. Wird beim Mode-Wechsel live aktualisiert.
* **NEU `_scroll_textedit_top(editor)`:** Scrollt die Read-Only-QTextEdit HART
  nach oben (Cursor -> Dokument-Anfang via
  `QTextCursor.MoveOperation.Start`, danach Scrollbar erst auf Maximum und
  dann auf 0, abschliessend `ensureCursorVisible`).
* **Root Cause der urspruenglichen „ab zweiter Zeile"-Bugs:** `setHtml`
  setzt den Cursor intern ans Dokument-Ende; Qt wrappt das Dokument erst in
  einer spaeteren Event-Loop-Runde um und scrollt dann zum Cursor.
  `_resize_param_box_deferred` resizete die Box danach -> der Reset verpuffte.
  Fix: `_scroll_textedit_top` wird (1) synchron nach `setHtml`, (2) deferred
  via `QTimer.singleShot(0)` und (3) nach dem finalen Box-Resize in
  `_resize_param_box_deferred` aufgerufen.
* **Imports ergaenzt:** `QTextEdit` (QtWidgets), `QTextOption`/`QTextCursor`
  (QtGui).
* **Verifikation (Real-Window-Reproduktion, headless):** nach Laden und
  Mode-Wechsel `sb value: 0` / `cursorRect y=4` (vorher 17/-13).

## 13.2 Verifikation (headless, keine UI-Tests)

* **Syntax:** `python -m py_compile` auf `../../serviceui/param_columns.py`, den
  3 Swing-Services + `../../test/test.py` – PASS.
* **`../../test/test.py` Teil 22 (NEU, 17 Checks, alle PASS):**
  * T1-T2) Fuer alle 3 Swing-Services: `options` als Liste vorhanden und
    `visible_when`-Deklarationen im `full_parameter_schema()`.
  * T3) `_create_param_control("mode", ...)` liefert eine `QComboBox`
    (auch bei `type=="str"` + `options`).
  * T4-T5) Plugin-Editor: mode-Control ist QComboBox und enthaelt alle
    Algo-Optionen.
  * T6-T7) Default `Williams_Fractal`: `left_bars` sichtbar,
    `atr_period` ausgeblendet.
  * T8-T10) Mode-Wechsel via `currentTextChanged` -> `ZigZag_ATR`:
    `atr_period` sichtbar, `left_bars`/`change_pct` ausgeblendet.
  * T11-T12) Mode `Period_Extrema`: `period_extrema_type` sichtbar,
    `atr_period` ausgeblendet.
  * T13) `collect_set_definition()` liefert den geaenderten mode
    (editierbar/speicherbar).
* **`../../test/test.py` Teil 23 (NEU, 12 Checks, alle PASS):**
  * T1) Info-Anzeige je Instanz vorhanden (QTextEdit).
  * T2-T4) Label enthaelt display_name + description_long + aktuellen
    Algorithmus (mode).
  * T5-T6) Mode-Wechsel aktualisiert Label (Period_Extrema inkl.
    PDH/PWH-Algo-Beschreibung; Williams_Fractal verschwunden).
  * T7-T8) Anzeige sichtbar und read-only.
  * T9) vertikale Scrollbar Policy `AsNeeded`.
  * T9b) Scrollbar initial ganz oben (value == 0).
  * T9c) nach Mode-Wechsel weiterhin ganz oben (value == 0) – kein Sprung
    ans Dokument-Ende.
  * T10) Info-Anzeige auch fuer `srv_swing_momentum`.
* **Gesamtlauf `../../test/test.py`:** 399 PASS; unveraenderte 6 vorbestehende
  Harness-FAILURES (P2, P5, H3, H4, H5, H7 - PersistentWindow-Position/
  -Groesse, offscreen-bedingt, dokumentierte Baseline) – keine neuen Fehler.
* **Test-Cleanup (Invariante 10):** temporaere Helfer/Test-DBs entfernt;
  `../../test` enthaelt wieder nur `../../test/test.py` (Teile 22 + 23 ergaenzt).
* Naechste Kapitel (Roadmap): 17.02 Trend Services.


---

# 17.02 Trend Services (Überarbeitetes Gesamtkonzept & Anleitung)

**Rein auf MT5-OHLCV-/Tick-Volumendaten** basierende, voll **service-fähige** Trend-, Kanal- und Reversal-Erkennungsalgorithmen in PyTrader, die ihre Ergebnisse als `feature_store_payload` für den Analyzer, den Feature Store und den Chart bereitstellen.

---

## 1. Executive Summary & Architektur-Invarianten

Konsolidierung aller Trend-, Kanal- und Regimemessungs-Verfahren in **3 hochperformante Core-Services**:

1. `srv_trend_regime` (Statistische Trendstärke & Regimes: LinReg $R^2$/Slope, ADX/DMI, Z-Score)
2. `srv_trend_breakout` (Volatilitäts- & Kanal-Breakouts: Supertrend ATR, Donchian/Keltner)
3. `srv_trend_hma_pivot` (Geglättete HMA/EHMA Peak-Toleranz & Pivot-Trendwechsel)

### Invarianten aus Phase 17 & 17.01

1. **Git-Workflow:** Vor jedem Schritt Branch/Commit erstellen und exakten Tag setzen (`git checkout -b phase17_02` $\rightarrow$ `git commit -m "..."` $\rightarrow$ `git tag phase17_02_step1`).
2. **Headless-Validierung:** Keine GUI/UI-Tests (`no QApplication.exec()`). Tests erfolgen rein headless über PyTest / den Harness `../../test/test.py`.
3. **Dateipfad & Präfix:** Strikte Ablage unter `analytics/features/definitions/srv_trend_*.py` mit `plugin_id = "srv_trend_*"`.
4. **PineScript-Input-Zone (E-2/E-3):** Schema als Modul-Konstante am Dateianfang, Typen als **Strings** (`"int"`, `"float"`, `"str"`, `"bool"`). Property `parameter_schema` liefert eine flache Kopie (`{k: dict(v) ...}`).
5. **UI-Exposure (17.01.04):** Alle Klassen implementieren explizit `@property def default_params` und `def full_parameter_schema()` (Verbindung von `base_parameter_schema` und `parameter_schema`).
6. **Capabilities (E-5):** Explizit `capabilities = {"chart": False, "batch": True, "live": False, "feature_store": True, "render": False}`.
7. **Causal Timestamps:** `event_bar_time` (Zeitpunkt des Extremums/Breakouts), `confirmation_bar_time` (Kausale Bestätigungs-Bar $\ge$ event), `confirmation_lag_bars` (Bar-Abstand).
8. **Datenbank-PK & Write-Pfad (E-1):** Verträglichkeit mit dem 4-Spalten-PK `(symbol, timeframe, bar_time, feature_id)` via `ON CONFLICT (symbol, timeframe, bar_time, feature_id)`.
9. **Schema-Version (E-7):** Payload-Metadata und Records enthalten zwingend `"schema_version": "1.0.0"`.
10. **Test-Cleanup (Invariante 10):** Temporäre Test-Datenbanken (`*.duckdb`) und Hilfsskripte in `../../test` werden nach dem Testlauf gelöscht. Nur `../../test/test.py` bleibt als permanenter Harness bestehen.

---

## 2. Die 3 Konsolidierten Trend-Services (Python-Code-Skeletons)

### A. `srv_trend_regime.py`

* **Verwendungszweck:** Quantifiziert statistische Trend-Regimes, Trendstärken und Mittelwertabweichungen.
* **MasterTree:** `category: "Trend & Reversal/Regime & Stärke"`

```python
# ==============================================================================
# DEFINITION: srv_trend_regime
# ==============================================================================
# NAME:        Trend Regime Service
# KATEGORIE:   Trend & Reversal/Regime & Stärke
# BESCHREIBUNG: Statistische Trendstärke- und Regime-Analyse via LinReg (R²), ADX/DMI & Z-Score
# ==============================================================================

import pandas as pd
import numpy as np
from typing import Dict, Any
from analytics.features.plugins.base_plugin import PluginFeature

_TREND_REGIME_SCHEMA = {
    "mode": {
        "type": "str",
        "default": "Linear_Regression_Slope",
        "options": ["Linear_Regression_Slope", "ADX_DMI", "ZScore_Mean_Distance"],
        "description": "Algorithmus-Modus zur Trend-Regime-Bestimmung"
    },
    "period": {"type": "int", "default": 20, "min": 2, "description": "Berechnungsperiode für Regressions-/Statistik-Fenster"},
    "r2_threshold": {"type": "float", "default": 0.6, "min": 0.0, "max": 1.0, "description": "Mindest-R² für etablierten Trend (LinReg)"},
    "di_period": {"type": "int", "default": 14, "min": 1, "description": "DMI-Periode (nur bei mode == 'ADX_DMI')"},
    "adx_smooth": {"type": "int", "default": 14, "min": 1, "description": "ADX-Glättung (nur bei mode == 'ADX_DMI')"},
    "adx_threshold": {"type": "float", "default": 25.0, "min": 1.0, "description": "ADX-Schwellwert für Trend-Regime"},
    "z_thresh": {"type": "float", "default": 2.0, "min": 0.1, "description": "Z-Score Extremwert-Schwelle für Reversals"},
    "ma_type": {
        "type": "str",
        "default": "SMA",
        "options": ["SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA", "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"],
        "description": "Gleitender Durchschnitt für Z-Score Baseline"
    }
}

class SrvTrendRegime(PluginFeature):
    @property
    def parameter_schema(self) -> Dict[str, Any]:
        return {k: dict(v) for k, v in _TREND_REGIME_SCHEMA.items()}

    @property
    def default_params(self) -> Dict[str, Any]:
        return {k: v.get("default") for k, v in self.parameter_schema.items() if "default" in v}

    def full_parameter_schema(self) -> Dict[str, Any]:
        res = dict(self.base_parameter_schema or {})
        res.update(dict(self.parameter_schema or {}))
        return res

    @property
    def plugin_id(self) -> str:
        return "srv_trend_regime"

    @property
    def version(self) -> str:
        return "1.0.0"

    capabilities = {"chart": False, "batch": True, "live": False, "feature_store": True, "render": False}

    metadata = {
        "display_name": "Trend Regime Service",
        "category": "Trend & Reversal/Regime & Stärke",
        "description": "Quantifiziert Trendstärke und Regimes über LinReg Slope/R², ADX/DMI und Z-Score Mean Distance.",
        "description_long": "Analysiert Trendphasen und Reversals. LinReg misst Steigung und Bestimmtheitsmaß R². ADX/DMI misst Richtungsdynamik. Z-Score misst die Standardabweichung vom Mittelwert für Übertreibungen.",
        "author": "PyTrader Core Team",
        "tags": ["trend", "regime", "linreg", "adx", "zscore"],
        "condition_rules": {
            "Linear_Regression_Slope": "TrendUp = Slope > 0 and R² >= r2_threshold",
            "ADX_DMI": "TrendUp = +DI > -DI and ADX >= adx_threshold",
            "ZScore_Mean_Distance": "ReversalUp = Z-Score <= -z_thresh (Überverkauft)"
        },
        "api_version": "1.0.0",
        "schema_version": "1.0.0"
    }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any], context=None) -> Dict[str, Any]:
        pass

```

---

### B. `srv_trend_breakout.py`

* **Verwendungszweck:** Erkennt Trendwechsel und Ausbrüche über dynamische ATR-Trailings und Bänder.
* **MasterTree:** `category: "Trend & Reversal/Breakout & Kanal"`

```python
# ==============================================================================
# DEFINITION: srv_trend_breakout
# ==============================================================================
# NAME:        Trend Breakout Service
# KATEGORIE:   Trend & Reversal/Breakout & Kanal
# BESCHREIBUNG: Trendfolgende Trailing-Stops & Kanal-Breakouts via Supertrend & Donchian/Keltner
# ==============================================================================

import pandas as pd
import numpy as np
from typing import Dict, Any
from analytics.features.plugins.base_plugin import PluginFeature

_TREND_BREAKOUT_SCHEMA = {
    "mode": {
        "type": "str",
        "default": "Supertrend_ATR",
        "options": ["Supertrend_ATR", "Donchian_Keltner_Breakout"],
        "description": "Breakout-Algorithmus"
    },
    "channel_type": {
        "type": "str",
        "default": "Donchian",
        "options": ["Donchian", "Keltner"],
        "description": "Kanal-Typ bei mode == 'Donchian_Keltner_Breakout'"
    },
    "atr_period": {"type": "int", "default": 10, "min": 1, "description": "ATR-Periode für Supertrend / Keltner"},
    "atr_mult": {"type": "float", "default": 3.0, "min": 0.1, "description": "ATR-Multiplikator für Bänder/Trailing"},
    "period": {"type": "int", "default": 20, "min": 2, "description": "Donchian/Keltner Kanal-Periode"},
    "ma_type": {
        "type": "str",
        "default": "EMA",
        "options": ["SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA", "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"],
        "description": "MA-Typ für Keltner Baseline"
    }
}

class SrvTrendBreakout(PluginFeature):
    @property
    def parameter_schema(self) -> Dict[str, Any]:
        return {k: dict(v) for k, v in _TREND_BREAKOUT_SCHEMA.items()}

    @property
    def default_params(self) -> Dict[str, Any]:
        return {k: v.get("default") for k, v in self.parameter_schema.items() if "default" in v}

    def full_parameter_schema(self) -> Dict[str, Any]:
        res = dict(self.base_parameter_schema or {})
        res.update(dict(self.parameter_schema or {}))
        return res

    @property
    def plugin_id(self) -> str:
        return "srv_trend_breakout"

    @property
    def version(self) -> str:
        return "1.0.0"

    capabilities = {"chart": False, "batch": True, "live": False, "feature_store": True, "render": False}

    metadata = {
        "display_name": "Trend Breakout Service",
        "category": "Trend & Reversal/Breakout & Kanal",
        "description": "Erfasst Trend-Ausbrüche und Trailing-Stops über Supertrend ATR und Donchian/Keltner-Kanäle.",
        "description_long": "Liefert kausale Trendwechsel-Signale. Supertrend schaltet bei Schlusskurs-Durchbruch des Median+-ATR-Bandes um. Donchian/Keltner signalisiert Ausbrüche aus N-Bar Extrema oder Volatilitätsbändern.",
        "author": "PyTrader Core Team",
        "tags": ["trend", "breakout", "supertrend", "donchian", "keltner"],
        "condition_rules": {
            "Supertrend_ATR": "TrendUp = Close > Supertrend_Line",
            "Donchian_Keltner_Breakout": "TrendUp = Close > Upper_Channel_Band"
        },
        "api_version": "1.0.0",
        "schema_version": "1.0.0"
    }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any], context=None) -> Dict[str, Any]:
        pass

```

---

### C. `srv_trend_hma_pivot.py`

* **Verwendungszweck:** Spezialisierter Trendwechsel-Detektor auf Basis von HMA/EHMA-Extrema und prozentualer Hysterese.
* **MasterTree:** `category: "Trend & Reversal/Hysteresis & Pivots"`

```python
# ==============================================================================
# DEFINITION: srv_trend_hma_pivot
# ==============================================================================
# NAME:        HMA Peak-Toleranz Pivot Service
# KATEGORIE:   Trend & Reversal/Hysteresis & Pivots
# BESCHREIBUNG: Trendwechsel-Erkennung auf geglätteter EHMA/HMA mit Prozent-Hysterese
# ==============================================================================

import pandas as pd
import numpy as np
from typing import Dict, Any
from analytics.features.plugins.base_plugin import PluginFeature

_TREND_HMA_PIVOT_SCHEMA = {
    "mode": {
        "type": "str",
        "default": "HMA_Peak_Toleranz",
        "options": ["HMA_Peak_Toleranz"],
        "description": "HMA Pivot Hysteresis Modus"
    },
    "piv_len": {"type": "int", "default": 4, "min": 1, "description": "Pivot-Lookback/Glättung"},
    "hma_type": {
        "type": "str",
        "default": "EHMA",
        "options": ["SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA", "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"],
        "description": "Gleitender Durchschnittstyp (EHMA/HMA)"
    },
    "hma_smoothing": {"type": "int", "default": 10, "min": 2, "description": "Hauptperiode des MA"},
    "piv_maxHmaMovePct": {"type": "float", "default": 0.2, "min": 0.01, "description": "Erforderlicher prozentualer Mindestabstand vom Peak für Trendwechsel"}
}

class SrvTrendHmaPivot(PluginFeature):
    @property
    def parameter_schema(self) -> Dict[str, Any]:
        return {k: dict(v) for k, v in _TREND_HMA_PIVOT_SCHEMA.items()}

    @property
    def default_params(self) -> Dict[str, Any]:
        return {k: v.get("default") for k, v in self.parameter_schema.items() if "default" in v}

    def full_parameter_schema(self) -> Dict[str, Any]:
        res = dict(self.base_parameter_schema or {})
        res.update(dict(self.parameter_schema or {}))
        return res

    @property
    def plugin_id(self) -> str:
        return "srv_trend_hma_pivot"

    @property
    def version(self) -> str:
        return "1.0.0"

    capabilities = {"chart": False, "batch": True, "live": False, "feature_store": True, "render": False}

    metadata = {
        "display_name": "HMA Peak Pivot Service",
        "category": "Trend & Reversal/Hysteresis & Pivots",
        "description": "Erkennt Trendwechsel auf geglätteten EHMA/HMA-Linien unter Berücksichtigung einer Prozent-Hysterese.",
        "description_long": "Hält den letzten extremen MA-Wert (piv_pendingExtremeValue). Ein Trendwechsel wird erst signalisiert, wenn der MA den Extremwert um piv_maxHmaMovePct % durchbricht. Verhindert Fehlsignale in Seitwärtsphasen.",
        "author": "PyTrader Core Team",
        "tags": ["trend", "hma", "ehma", "pivot", "hysteresis"],
        "condition_rules": {
            "HMA_Peak_Toleranz": "TrendUp = MA > PendingLow * (1 + MovePct/100)"
        },
        "api_version": "1.0.0",
        "schema_version": "1.0.0"
    }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any], context=None) -> Dict[str, Any]:
        pass

```

---

## 3. Datenvertrag im Feature Store (`analytics.duckdb`)

Jeder Service erzeugt eine strikt strukturierte Payload-Struktur. Die `calculate()`-Methode liefert das folgende Top-Level-Dictionary zurück:

### 3.1 Top-Level Payload-Struktur (`calculate()` Return)

```python
{
    "metadata": {
        "schema_version": "1.0.0",
        "plugin_id": "srv_trend_regime",
        "source_mode": "Linear_Regression_Slope",
        "total_trend_up": 412,
        "total_trend_down": 380,
        "bars": 1000
    },
    "records": [
        {
            "symbol": "EURUSD",               # String aus context oder df
            "timeframe": "H1",                 # String aus context oder df
            "bar_time": 1770000000,           # Epoch-Int der aktuellen Kerze (PK-Teil 3)
            "feature_id": "srv_trend_regime", # plugin_id (PK-Teil 4)
            "feature_data": {                 # JSON-Inhalt im Store
                "schema_version": "1.0.0",
                "result_type": "TREND",        # TREND | REVERSAL | BREAKOUT
                "source_mode": "Linear_Regression_Slope",
                "calculation_status": "OK",    # OK | INSUFFICIENT_DATA | ERROR
                
                "is_trend_up": True,
                "is_trend_down": False,
                "is_reversal_up": False,
                "is_reversal_down": False,
                
                "event_bar_time": 1770000000,
                "confirmation_bar_time": 1770000000,
                "confirmation_lag_bars": 0,
                "confirmation_type": "CAUSAL",  # CAUSAL | BAR_CLOSE
                
                "trend_strength": 0.82,
                "strength_type": "R2_SCORE",   # R2_SCORE | ADX_VALUE | SLOPE_ANGLE | Z_SCORE | ATR_DISTANCE
                "swing_price": 1.0850,
                
                # Modus-spezifische Zusatzfelder (optional, je nach mode)
                "r2_score": 0.82,
                "slope_value": 0.00015
            }
        }
    ]
}

```

### 3.2 Modus-Spezifische Zusatzfelder in `feature_data`

* **`srv_trend_regime` (LinReg):** `"slope_value": float`, `"r2_score": float`
* **`srv_trend_regime` (ADX/DMI):** `"adx_value": float`, `"plus_di": float`, `"minus_di": float`
* **`srv_trend_regime` (Z-Score):** `"z_score_value": float`, `"mean_baseline": float`
* **`srv_trend_breakout` (Supertrend):** `"supertrend_line": float`, `"atr_value": float`
* **`srv_trend_breakout` (Donchian/Keltner):** `"upper_band": float`, `"lower_band": float`, `"middle_band": float`
* **`srv_trend_hma_pivot`:** `"ma_value": float`, `"pending_extreme_value": float`

---

## 4. Schritt-für-Schritt Umsetzungsanleitung für das AI Agent Team

### Schritt 1: Git-Branch & Tag setzen

```bash
git checkout -b phase17_02
# Nach Erstellung der Dateien:
git add .
git commit -m "Phase 17.02: Trend-Services Grundgerüst angelegt"
git tag phase17_02_step1

```

### Schritt 2: Service-Dateien anlegen & Registrierung prüfen

1. Erstelle die 3 Dateien unter `../../analytics/features/definitions`:
* `srv_trend_regime.py`
* `srv_trend_breakout.py`
* `srv_trend_hma_pivot.py`


2. Füge die exakten Klassen-Definitionen inklusive Modul-Konstanten, Properties (`parameter_schema`, `default_params`, `full_parameter_schema`), `capabilities` und `metadata` ein.
3. Stelle sicher, dass `PluginRegistry().get("srv_trend_regime")` die Klassen findet (dynamischer Discovery-Scan).

### Schritt 3: Vektorisiertes `calculate()` & Robustheit implementieren

1. **Input-Validierung:** Der DataFrame `df` muss die Spalten `open`, `high`, `low`, `close`, `volume` und eine Epoch-Spalte `bar_time` (oder `time`/Index) enthalten.
2. **MA-Engine Nutzen:** Verwende für MA-Berechnungen `analytics.features.helpers.ma_template.MATemplateEngine.calculate_ma(df, ma_type, period)`.
3. **Vektorisierung:** Implementiere alle Berechnungen vollständig vektorisiert über Pandas/NumPy. Keine `for row in df.iterrows()`-Schleifen!
4. **Warmup & INSUFFICIENT_DATA:** Für alle Zeilen am Serienanfang (`index < warmup_period`), in denen Daten fehlen, gilt:
* `calculation_status = "INSUFFICIENT_DATA"`
* `is_trend_up = False`, `is_trend_down = False`, `is_reversal_up = False`, `is_reversal_down = False`


5. **Kausale Timestamps:**
* Für Bar-Close-Signale (Breakout, LinReg, ADX): `event_bar_time = bar_time`, `confirmation_bar_time = bar_time`, `confirmation_lag_bars = 0`.
* Für verspätete Extremwert-Signale (HMA Pivot): `event_bar_time = extreme_bar_time`, `confirmation_bar_time = bar_time`, `confirmation_lag_bars = current_idx - extreme_idx`.


6. **Fehlerbehandlung:** Wenn benötigte Spalten fehlen oder mathematische Fehler auftreten, setze `calculation_status = "ERROR"` und füge ein Feld `"error_message"` im Payload ein.

### Schritt 4: Harness-Integration in `../../test/test.py` (Teil 22)

Ergänze `../../test/test.py` um **Teil 22 (Trend Services Validation)**:

1. **Registry & Discovery Check:** Prüfe `PluginRegistry().get(...)` für alle 3 neuen Service-IDs.
2. **MasterTree Tree-Building Check:** Prüfe, dass `ServiceSelectorModel().build_tree()` die 3 neuen Kategorien unter `📦 Services` korrekt erzeugt:
* `Trend & Reversal/Regime & Stärke`
* `Trend & Reversal/Breakout & Kanal`
* `Trend & Reversal/Hysteresis & Pivots`


3. **Execution & Density Test:** Führe alle Modi auf synthetischen OHLCV-Daten aus.
* Assert: `len(records) == len(df)` (dichte Zeilenreihe, 1 Record pro Bar).
* Assert: `schema_version == "1.0.0"` sowohl in Metadata als auch in allen Records.
* Assert: Kausale Timestamps erfüllen `confirmation_bar_time >= event_bar_time`.
* Assert: Warmup-Zeilen besitzen `calculation_status == "INSUFFICIENT_DATA"`.


4. **4-Spalten-PK Store Test:** Speichere die Payloads in einer temporären Test-DuckDB (`test/test_p17_trend.duckdb`) über `FeatureBuilder.store_plugin_payload` und verifiziere den fehlerfreien 4-Spalten-Upsert `(symbol, timeframe, bar_time, feature_id)`.

### Schritt 5: Headless-Verifikation

```bash
python -m py_compile analytics/features/definitions/srv_trend_regime.py analytics/features/definitions/srv_trend_breakout.py analytics/features/definitions/srv_trend_hma_pivot.py
python test/test.py

```

### Schritt 6: Test-Cleanup (Invariante 10)

Nach erfolgreichem Testlauf werden temporäre Test-Datenbanken (`*.duckdb`) und temporäre Helfer-Skripte im Ordner `../../test` gelöscht. Nur die erweiterte `../../test/test.py` bleibt als dauerhafter Harness bestehen.

---

# 17.02 Review & Entscheidungen (07.08.2026) - Konsistenzpruefung gegen den Ist-Code

> **Implementierungs-Log (Review, kein Coding):** Am 07.08.2026 wurde das
> Kapitel "17.02 Trend Services" (frische Doku, Commit `494335e x` - das
> Dokument enthaelt neben den Phase-17-Grundsaetzen NUR noch die 17.02-
> Spezifikation) gegen den realen Quellcode geprueft:
> `../../analytics/features/plugins/base_plugin.py`, `../../analytics/features/feature_builder.py`,
> `analytics/features/definitions/srv_swing_*.py`, `../../test/test.py`.
> Die Codebasis ist seit dem letzten Stand unveraendert (keine Source-Commits
> ausser dem Doku-Commit `494335e x`).
>
> Ergebnis: Das Kapitel ist **inhaltlich stimmig** (3 Services, Kategorien,
> Datenvertrag, Invarianten), aber die Skeleton-Codes und die
> Umsetzungsanleitung weichen in mehreren Punkten von den Laufzeit-Konventionen
> ab (siehe Befunde B-1..B-8). **Es wurde kein Code geaendert**; die
> Entscheidungen E-1..E-8 sind **verbindlich** fuer die Umsetzung.

---

## 1. Verifizierte Ist-Konventionen (Basis des Reviews)

* **`base_plugin.py`:** `PluginMetadata.condition_rules` ist `List[str]`
  (Basis-Default `[]`, Zeile 167/216). `metadata` und `capabilities` sind in
  der Basisklasse **Properties**. `api_version`-Basis-Default: `"1"`.
  `full_parameter_schema()` existiert als Basisklassen-Methode (merged aus
  `base_parameter_schema` + `parameter_schema`); `base_parameter_schema`
  liefert `lookback` (expert). `default_params` der Basis nutzt
  `full_parameter_schema()` (inkl. lookback) - die 17.01.04-Overrides der
  Services liefern bewusst NUR Plugin-Defaults (ohne lookback).
* **`srv_swing_structure.py` (Ist-Muster):** `metadata` als Property mit
  `condition_rules` **als Liste von Strings**, `api_version: "1"`;
  `capabilities` als Property mit `PluginCapabilities`-Typ; explizite
  `parameter_order`- und `param_labels`-Properties; `parameter_schema` als
  flache Kopie der Modul-Konstante; `default_params`-Property +
  `full_parameter_schema()`-Methode; `calculate()` liefert
  **`FeatureCalculateResult`** (`{"feature_store_payload": {...}}`-Wrapper);
  `visible_when`-Deklarationen im Schema (17.01.05); Typ-Imports
  (`FeatureCalculateResult`, `PluginCapabilities`, `ParameterSchema`,
  `PluginContext`, `Optional`).
* **`srv_swing_momentum.py` (Ist):** MA-Berechnung ueber **lokalen Import**
  `from chart.indicators.utils.ma_template import MATemplateEngine`
  (try/except-Fallback). Der Pfad `analytics/features/helpers/...` existiert
  **nicht** (kein Ordner `analytics/features/helpers` im Projekt).
* **`feature_builder.py` (`store_plugin_payload(symbol, timeframe, payload,
  con)`, Zeile 606):** Records sind flach (`{bar_time, ...}`); **`symbol`,
  `timeframe`, `feature_id` setzt der Builder selbst** aus den
  Aufruf-Parametern bzw. dem Payload - sie duerfen NICHT in den Records
  stehen. Alles ausser `bar_time` wird per JSON in `feature_data` abgelegt.
* **`../../test/test.py`:** Die Teile **22 und 23 existieren bereits** (17.01.05,
  UI-Dropdown + Info-Label). `calculate()`-Ergebnisse werden ueber
  `res.get("feature_store_payload")` gelesen.
* **Git:** Die Arbeit liegt auf **`main`** (Commits b2a7206, 51401b3,
  494335e). Kein `phase17_02`-Branch vorhanden.

---

## 2. Befunde (Spezifikation vs. Ist-Code)

### B-1 Erfuellte Konventionen (konsistent, unveraendert uebernehmen)

* E-2/E-3: Schema als Modul-Konstante (`_TREND_*_SCHEMA`), Typen als Strings,
  `parameter_schema`-Property mit flacher Kopie - korrekt in allen 3
  Skeletons.
* E-5: `capabilities` mit chart=False/batch/live/feature_store/render -
  korrekt.
* E-7: `schema_version: "1.0.0"` in Payload-`metadata` - korrekt.
* 17.01.04: `default_params`-Property + `full_parameter_schema()`-Methode
  (merge `base_parameter_schema` + `parameter_schema`) - korrekt.
* Datenvertrag: Kausale Timestamps (`event/confirmation_bar_time`,
  `confirmation_lag_bars`), `calculation_status` mit `INSUFFICIENT_DATA` am
  Serienanfang, 4-Spalten-PK via `store_plugin_payload` - korrekt und additiv
  zu 17.01 (`result_type` TREND|REVERSAL|BREAKOUT, `strength_type`
  R2_SCORE|ADX_VALUE|SLOPE_ANGLE|Z_SCORE|ATR_DISTANCE, `confirmation_type`
  CAUSAL|BAR_CLOSE sind neue, nicht-kollidierende Werte).
* MasterTree-Kategorien `Trend & Reversal/...` passen zur 2-Gruppen-Struktur
  (17.01.01: `📁 Sets` / `📦 Services`, Kategorie-Ordner via
  `metadata["category"]`).

### B-2 Skeleton-Details weichen ab (bei der Umsetzung korrigieren)

* **`condition_rules` als Dict** `{"Mode": "Regel"}` in allen 3 Skeletons -
  verletzt den `PluginMetadata`-Vertrag (`List[str]`, vgl. Ist-Services mit
  Listenform).
* **`metadata`/`capabilities` als Klassenattribut** statt Property - weicht
  vom Ist-Muster ab; die Basis-Defaults (z. B. generierter `display_name`)
  gehen verloren.
* **`api_version: "1.0.0"`** - Ist-Stand ist `"1"` (Basis-Default;
  `api_version` ist KEIN SemVer-Pflichtfeld wie `schema_version`).
* **Fehlende `parameter_order`/`param_labels`-Properties** - Ist-Services
  deklarieren sie als Single Source of Truth fuer das Prop-Fenster.
* **Fehlende Typ-Imports** - Skeletons importieren nur `PluginFeature`; fuer
  Typsicherheit (Projektregel 2.5) sind `FeatureCalculateResult`,
  `PluginCapabilities`, `ParameterSchema`, `PluginContext`, `Optional` noetig.
* **`calculate(self, df, params, context=None) -> Dict[str, Any]`** mit `pass`
  - muss `FeatureCalculateResult` liefern (Wrapper) und die volle
  `Optional[PluginContext]`-Signatur tragen.

### B-3 Datenvertrag §3.1 (korrigieren)

* **Records mit `symbol`/`timeframe`/`feature_id`:** `store_plugin_payload`
  setzt diese Spalten selbst aus den Aufruf-Parametern/Payload. Ein Record mit
  diesen Keys wuerde sie als JSON-Doppel in `feature_data` legen.
  Korrekt: Records tragen **nur `bar_time` + die `feature_data`-Inhalte
  flach** (exakt das 17.01-Muster).
* **Top-Level ohne `feature_store_payload`-Wrapper:** `calculate()` liefert
  `FeatureCalculateResult = {"feature_store_payload": {...}}` (Wrapper ist
  Pflicht, wird von Worker/Evaluator/Tests konsumiert).
* **Namensvorschlag `swing_price`:** im Trend-Kontext irrefuehrend -
  Umbenennung zu `reference_price` (optional, additiv, kein Pflichtfeld).
* `schema_version` im `feature_data` jedes Records ist zulaessig/gewuenscht
  (additiv; die 17.01-Services stempeln es im Payload-metadata, der
  Reader-Default `SCHEMA_VERSION_DEFAULT` ist deckungsgleich).

### B-4 MA-Engine-Pfad in §4 Schritt 3 (korrigieren)

* **`analytics.features.helpers.ma_template.MATemplateEngine` existiert
  nicht** (kein Ordner `analytics/features/helpers`, verifiziert).
* Ist-Pfad (srv_swing_momentum.py, Zeile 392):
  `chart.indicators.utils.ma_template.MATemplateEngine.calculate_ma(
  df, ma_type, period)` - **lokaler Import** in der Methode mit
  try/except.

### B-5 Test-Teil-Nummerierung (§4 Schritt 4)

* **"Teil 22" ist bereits belegt** (17.01.05, UI-Dropdown; Teil 23
  Read-only-Label). Der neue Trend-Teil wird **Teil 24** (naechste freie
  Nummer im Harness, verifiziert: kein `Teil 24` vorhanden).

### B-6 `visible_when` fehlt in den Skeletons (17.01.05-Konvention)

* Modus-spezifische Parameter (`di_period`/`adx_smooth`/`adx_threshold` nur
  bei `ADX_DMI`, `r2_threshold` nur bei `Linear_Regression_Slope`,
  `channel_type`/`ma_type`/`period` nur bei `Donchian_Keltner_Breakout`,
  `piv_len`/`hma_type`/`hma_smoothing`/`piv_maxHmaMovePct` bei
  `HMA_Peak_Toleranz`, `ma_type` nur beim Z-Score-Modus) erhalten
  `visible_when: {"mode": [...]}`-Deklarationen, damit die Conditional
  Visibility (17.01.05) beim Mode-Wechsel greift.

### B-7 Branch-Strategie (§4 Schritt 1)

* Die Anleitung fordert `git checkout -b phase17_02`. Die gesamte 17.01-
  Arbeit (inkl. 17.01.04/17.01.05) liegt auf **main**. Entscheidung:
  **main** (Kontinuitaet, keine verschachtelten Branches; Tags
  `phase17_02_step*` werden wie bisher auf main gesetzt). Ein separater
  Branch ist nur auf ausdrueckliche Einzelanweisung des Benutzers sinnvoll.

### B-8 Scaffold-Strategie (Skeletons mit `calculate() = pass`)

* 17.01 nutzte den Zweistufen-Weg (Scaffold mit korrektem Payload +
  records=[], danach echte Algorithmen in 17.01.02). Da das 17.01-Muster
  (dichte Record-Reihe, kausale Timestamps, Modul-Helfer) jetzt etabliert und
  im Harness erprobt ist, wird **direkt die vollstaendige Erkennung**
  implementiert (kein Scaffold-Zwischenschritt) - inkl. 3 Modi je Service.

---

## 3. Entscheidungen (verbindlich fuer die Umsetzung)

* **E-1 (Stil-Angleichung):** Alle 3 Trend-Services nach dem Ist-Muster von
  `srv_swing_structure.py`:
  * `metadata` als `@property def metadata(self) -> Dict[str, Any]` mit
    `condition_rules` als **Liste** von Strings; `api_version: "1"`; `author`
    konsistent ("PyTrader AI").
  * `capabilities` als `@property def capabilities(self) -> PluginCapabilities`.
  * `parameter_order`- und `param_labels`-Properties (PineScript-Zone).
  * Typ-Imports (`FeatureCalculateResult`, `PluginCapabilities`,
    `ParameterSchema`, `PluginContext`, `Optional`, `Any`, `Dict`, `List`).
  * `calculate(...) -> FeatureCalculateResult` mit
    `context: Optional[PluginContext] = None` und `feature_store_payload`-
    Wrapper (feature_id, plugin_version, metadata inkl. schema_version,
    records).
* **E-2 (Datenvertrag korrigieren):** §3.1 der 17.02-Spezifikation anpassen -
  Records ohne `symbol`/`timeframe`/`feature_id` (der Builder setzt sie),
  Top-Level mit `feature_store_payload`-Wrapper; Feld `swing_price` ->
  optional `reference_price`.
* **E-3 (MA-Pfad):** Anleitung §4 Schritt 3 korrigieren auf
  `chart.indicators.utils.ma_template.MATemplateEngine` (lokaler Import,
  try/except) - identisch zu `srv_swing_momentum.py`.
* **E-4 (visible_when):** Schema der 3 Services um `visible_when`-
  Deklarationen ergaenzen (B-6), damit die Conditional Visibility aus
  17.01.05 fuer die modus-spezifischen Parameter greift.
* **E-5 (Test-Teil):** Neuer Harness-Teil **24 (Trend Services Validation)** -
  nicht Teil 22. Pruefungen analog Teil 17/18: Registry-Discovery,
  `build_tree()` enthaelt die 3 Kategorien, dichte Records
  (`len(records) == len(df)`), `schema_version` in Metadata+Records,
  Kausalitaet (`confirmation_bar_time >= event_bar_time`),
  Warmup-INSUFFICIENT_DATA, 4-Spalten-PK-Store auf
  `test/test_p17_trend.duckdb` (wird nach dem Test geloescht, Invariante 10).
* **E-6 (Branch):** Umsetzung auf **main** (kein `phase17_02`-Branch);
  Commits + Tags `phase17_02_step*` wie bei 17.01.
* **E-7 (Direkte Erkennung statt Scaffold):** Vollstaendige `calculate()`-
  Implementierung in einem Schritt (B-8); kein Zwischen-Commit mit
  records=[].
* **E-8 (Verifikation):** `py_compile` auf den 3 neuen Dateien +
  `../../test/test.py`; Gesamtlauf `../../test/test.py` mit erwarteten 6 vorbestehenden
  Harness-FAILURES (P2, P5, H3, H4, H5, H7 - PersistentWindow-Position/
  -Groesse, offscreen-bedingt, dokumentierte Baseline). Test-Cleanup gem.
  Invariante 10.

---

## 4. Ergebnis

* Die 17.02-Spezifikation bleibt als verbindliche Anleitung erhalten; die
  Punkte B-2..B-5 sowie E-1..E-8 werden **bei der Umsetzung** als
  Korrekturen gegenueber dem Skeleton-Stand angewendet.
* **Kein Code geaendert** (Review pur). Dieser Eintrag ist die verbindliche
  Ergaenzung fuer die Umsetzung von 17.02.
* Naechster Schritt: Umsetzung von 17.02 (Startschuss des Benutzers
---

# Bugfix-Log 07.08.2026 (Service-Parameter-Box: Hoehe & Scroll-Verhalten)

> **Implementierungs-Log (Bugfixing-Modus, 07.08.2026):** Der Benutzer meldete
> zwei aufeinanderfolgende Probleme beim Wechsel des Algorithmus-Dropdowns
> (Conditional Visibility, 17.01.05) im ServiceWindow:

## Bugfix 1 (Commit `c61e14e`): Box-Hoehe folgt wechselnder Parameterzahl

**Symptom:** Nach der Auswahl eines Algorithmus im Dropdown wurde die Hoehe
der Box "Service-Parameter" nicht an die wechselnde Anzahl der Parameter
angepasst – falsch war dagegen die Anpassung der Hoehe der Einzelfelder
(gestreckte Parameterfelder).

**Ursache:** `_apply_conditional_visibility` blendete die modus-abhaengigen
Parameter zwar ein/aus, stiess danach aber KEIN `updateGeometry()`/`_reflow()`
an. Qt 6.11 cached den QWidgetItemV2-sizeHint – ohne Invalidierung blieb die
alte Box-Hoehe stehen und der QFormLayout verteilte die ueberschuessige Hoehe
auf die verbliebenen Zeilen (gestreckte Einzelfelder).

**Fix:** Nach dem Ein-/Ausblenden werden die Geometrie-Caches der betroffenen
Spalten + der Service-Parameter-Box invalidiert und ein deferred Reflow
angestossen (analog `_setup_collapsible`/`_build_service_columns`).

**Verifikation:** `../../test/test.py` Teil 25 (T1–T9): Box waechst/schrumpft mit
der Parameterzahl, Einzelfeld-Hoehen stabil, `py_compile` OK.

## Bugfix 2 (07.08.2026): KEIN Canvas-/Fenster-Versatz – Scrollbox statt Hoehen-Reflow

**User-Anweisung (wörtlich):**
1) Das Resizing ist ok fuer den Rahmen "Service-Parameter", ABER es soll nicht
   der gesamte Canvas fuer eine oder mehrere Service-Parameter-Boxen in der
   Hoehe versetzt werden, ebenso nicht die ganze Fensterhoehe.
2) Ist der Rahmen "Service-Parameter" zu hoch, soll der Canvas einfach eine
   Scrollbox aktivieren (so war das mal festgelegt).
3) Das gilt auch fuer den Tree: Der soll seine Hoehe nicht aufgrund von
   Service-Parametern anpassen, sondern selbst eine Scrollbar erhalten, falls
   es so viele Knoten gibt, dass sie nicht in die Box passen.

**Ursache (Bugfix-1-Nebenwirkung):** `_reflow()` -> `_schedule_reflow()` ->
`_apply_reflow_size()` -> `resize_to_clamped_content()` mit
`_exact_fit_to_content = True` (ServiceWindow) setzte die FENSTERHOEHE exakt
auf min(Inhalt, Bildschirm) – dadurch wurde der gesamte Canvas/die
Fensterhoehe bei jedem Mode-Wechsel versetzt.

**Fix (`../../serviceui/param_columns.py`, 2 Stellen):**
* `_apply_conditional_visibility` (Mode-Wechsel): `self._reflow()` ersetzt
  durch `QTimer.singleShot(0, self._resize_param_box_deferred)` – NUR die Box
  wird auf ihre Layout-Groesse gesetzt, kein Fenster-Reflow.
* `_setup_collapsible` (Experten-Optionen ein-/ausklappen): gleiche Umstellung.

**Ergebnis (deckt alle 3 Punkte ab):**
* Punkt 1: Fensterhoehe bleibt stabil – kein Canvas-/Fenster-Versatz beim
  Mode-Wechsel (Teil 25 T10/T11: Hoehe identisch vor/nach Wechsel).
* Punkt 2: Die `_param_scroll`-ContentScrollArea (`widgetResizable=False`,
  vertikale Scrollbar `AsNeeded`) aktiviert bei Ueberhoehe der Box einen
  vertikalen Scrollbalken (Teil 25 T12/T13/T13b/T15: Range > 0 bei Ueberhoehe).
* Punkt 3: Der MasterTree (links) behaelt seine Hoehe; er hat die native
  QTreeWidget-Scrollbar (`ScrollBarAsNeeded`) und scrollt bei vielen Knoten
  selbst (Teil 25 T14).

`_build_service_columns` (Set-Load/Initial-Fit) behaelt `_reflow()` bewusst
bei – nur die box-internen Hoehenaenderungen (Mode-Wechsel, Experten-
Optionen) loesen keinen Fenster-Reflow mehr aus.

**Verifikation:** `../../test/test.py` Teil 25 (T1–T15) alle PASS; Gesamtlauf mit
exakt den 6 vorbestehenden Harness-FAILURES (P2, P5, H3, H4, H5, H7 –
PersistentWindow-Position/-Groesse, offscreen-bedingt, dokumentierte
Baseline). Test-Cleanup gem. Invariante 10 (temporaere Helfer entfernt).

  erforderlich).
