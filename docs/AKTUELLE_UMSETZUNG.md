# Phase 17: Services und Analytics-Finalisierung

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 17)

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

> **Hinweis (07.08.2026, UMGESETZT):** Die PK-Migration wurde durchgeführt – der `feature_store` hat jetzt den 4-Spalten-PK `(symbol, timeframe, bar_time, feature_id)` mit `feature_id VARCHAR NOT NULL` (Sentinel `'native'` für klassische Feature-Builder-Rows; verifiziert, 677.713 Zeilen verlustfrei migriert, Backup `data/backup_analytics_20260807.duckdb`). Details in Kapitel 7.1.


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

2. **Backend-Integrationstest in `test/test.py`:**
* Prüfe Registrierung über `PluginRegistry().get("srv_swing_structure")` (definiert in `analytics/features/feature_builder.py`).
* Prüfe Baumaufbau in `ServiceSelectorModel().build_tree()` (definiert in `analytics/engine/service_selector_model.py`).

3. **Keine GUI-/UI-Tests ausführen (Harte Regel 4).**

---

## 6. Konsistenzprüfung & Entscheidungen (07.08.2026, 17:44) – 17.01 Review

> **Implementierungs-Log (Review, kein Coding):** Am 07.08.2026 wurde Kapitel 17.01 gegen den realen Quellcode und `data/analytics.duckdb` geprüft (Schema-Abfragen, Write-/Lese-Pfade, `base_plugin.py`, bestehende Service-Muster `srv_grid_lines`/`srv_proximity`, DuckDB-Fähigkeiten). Ergebnis: **Kapitel ist inhaltlich stimmig, aber §2.5 (PK) ist ein Migrations-Ziel und die Service-Snippets in §3 weichen in 4 Punkten von den Laufzeit-Konventionen ab.** Die folgenden Entscheidungen sind **verbindlich** für die Umsetzung; es wurde kein Code geändert.

### E-1 (BLOCKER): `feature_store`-PK-Migration auf `(symbol, timeframe, bar_time, feature_id)`

* **Befund:** Ist-PK = `(symbol, timeframe, bar_time)`; `feature_id` ist NULLABLE. Damit kann heute **max. 1 Service je Bar** gespeichert werden (letzter Writer gewinnt). `data/analytics.duckdb`: 677.713 Zeilen – `srv_proximity` 593.627, `srv_grid_lines` 81.086, native Rows ohne feature_id 3.000.
* **Befund (DuckDB 1.5.5):** `ALTER TABLE ... DROP PRIMARY KEY` wird **nicht** unterstützt (ParserError, verifiziert). Einzig praktikables Verfahren ist **Table-Rewrite + RENAME** (verifiziert in `test/check_pk_migration.py`).
* **Migrations-Schritt 17.01.0 (verbindliche Reihenfolge):**
  1. Backup: Git-Tag `phase17_step0` + Kopie von `data/analytics.duckdb` nach `data/backup_analytics_20260807.duckdb`.
  2. Sentinel für native Alt-Rows: `UPDATE feature_store SET feature_id = 'native' WHERE feature_id IS NULL;`
  3. `CREATE TABLE feature_store_new` mit **identischer Spaltenliste** (alle 30 Spalten) + `feature_id VARCHAR NOT NULL` + `PRIMARY KEY (symbol, timeframe, bar_time, feature_id)`.
  4. `INSERT INTO feature_store_new (…) SELECT … FROM feature_store;` (Spalten 1:1, feature_id bereits durch Schritt 2 gesetzt).
  5. `DROP TABLE feature_store;` + `ALTER TABLE feature_store_new RENAME TO feature_store;`
  6. **Write-Pfade in `analytics/features/feature_builder.py` umstellen** (sonst BinderException nach Migration):
     * `store_plugin_payload()`: `ON CONFLICT (symbol, timeframe, bar_time)` → `ON CONFLICT (symbol, timeframe, bar_time, feature_id)`.
     * `store_features()` (nativer Pfad): Insert-Spalten um `feature_id` erweitern (Wert `'native'` je Zeile) und Konfliktziel auf 4 Spalten.
  7. **Reader-Exclusions für den Sentinel `'native'`** (sonst erscheint er in UI-Listen): `feature_store_reader.get_available_features()` und `fetch_last_execution_dates()` um `AND feature_id != 'native'` ergänzen (`statistics_repository.get_available_sets()` filtert bereits über `feature_data IS NOT NULL` – native Rows bleiben dort automatisch außen vor).
* **Verifikation:** Test in `test/test.py`: (a) 2 Services auf derselben Bar koexistieren nach Migration (4-Spalten-Upsert), (b) 3-Spalten-`ON CONFLICT` wirft nach Migration BinderException, (c) `feature_id != 'native'`-Filter liefert keine Sentinel-IDs.

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

* `py_compile` zusätzlich auf `analytics/features/feature_builder.py` und `analytics/engine/feature_store_reader.py` (geänderte Pfade aus E-1).
* Test in `test/test.py`: Koexistenz zweier Swing-Services auf derselben Bar (PK-Migration), `PluginRegistry().get(...)` für alle 3 IDs, `build_tree()` enthält die Kategorien `Swing Points/Geometrie`, `Swing Points/Dynamik & Filter`, `Swing Points/Volumen & Grid`.
* Test-Cleanup nach Abschluss des Kapitels (Invariante 10): nur `test/test.py` bleibt bestehen; `test/check_pk_migration.py` wird als Referenz für E-1 während der Umsetzung vorgehalten und danach entfernt.

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
* **Backup:** `data/backup_analytics_20260807.duckdb` (98,8 MB) + Git-Tag `phase17_step0` (Review-Commit).
* **`db_service.py`** (`check_and_init_databases`): Basis-`CREATE TABLE IF NOT EXISTS feature_store` auf 4-Spalten-PK + `feature_id VARCHAR NOT NULL DEFAULT 'native'` aktualisiert (No-op für die migrierte DB, korrektes Schema für neue DBs). Die alten `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`-Statements bleiben als idempotente No-ops erhalten.
* **`analytics/features/feature_builder.py`** (Write-Pfade):
  * `store_features()` (nativer Pfad): setzt `feature_id='native'` je Zeile, Insert-/Select-Spalten + `ON CONFLICT (symbol, timeframe, bar_time, feature_id)`.
  * `store_plugin_payload()`: `ON CONFLICT (symbol, timeframe, bar_time, feature_id)`.
* **`analytics/engine/feature_store_reader.py`** (Sentinel-Exclusions):
  * Neue Konstante `SENTINEL_NATIVE = "native"`.
  * `fetch_last_execution_dates()` und `get_available_features()` schließen `feature_id != 'native'` aus (Sentinel erscheint nicht in MasterTree/UI-Listen).
  * `statistics_repository.get_available_sets()` benötigte keine Änderung (filtert bereits über `feature_data IS NOT NULL`).

### 7.2 E-2..E-6 – Die 3 Swing-Services (NEU, Scaffold)

* **Neue Dateien** in `analytics/features/definitions/` (alle registriert, verifiziert):
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

* `py_compile` PASS auf: `srv_swing_structure.py`, `srv_swing_momentum.py`, `srv_swing_volume_profile.py`, `feature_builder.py`, `feature_store_reader.py`, `db_service.py`, `test/test.py`.
* `test/test.py` **Teil 14 (8/8 PASS)**:
  * T1: `PluginRegistry().get(...)` für alle 3 IDs.
  * T2: `build_tree()` enthält die Kategorien `Swing Points/Geometrie`, `Swing Points/Dynamik & Filter`, `Swing Points/Volumen & Grid` (Pfad-basiert, Ordner rekursiv).
  * T3: Zwei Services koexistieren auf derselben Bar (4-Spalten-Upsert auf Test-DB).
  * T4: 3-Spalten-`ON CONFLICT` wirft nach Migration `BinderException` (Negativtest).
  * `check_and_init_databases()` läuft mit der migrierten DB fehlerfrei (Schema/Constraint-Verifikation).
* Vorbestehende Harness-FAILURES (P2/P5/H3/H4/H5/H7/T5 – Fenster-Geometrie/Info-Button aus früheren Teilen) sind unabhängig von 17.01 (keine berührten Komponenten; kein Regressionstest gemäß Harte Regel 4).

### 7.5 Test-Cleanup (Invariante 10, ausstehend bis Kapitelabschluss)

* Dauerhaft: `test/test.py` (inkl. Teil 14).
* Temporär (verbleiben bis zur Abnahme des Kapitels, werden danach entfernt): `test/check_pk_migration.py` (Referenz für E-1), `test/migrate_pk.py`, `test/check_init_compat.py`, `test/_insert_part14.py`, `test/_fix_part14.py`, `test/_fix_part14b.py`.

---

# 17.01.01 MasterTree Refactoring: Cleanup Standalone & Root Node Rename

## 1. Zielsetzung & Anpassungen
1. **Entfernung der Redundanz:** Die Gruppe `⚡ Standalone Services` (`GROUP_STANDALONE`) entfällt ersatzlos, da alle Plugins über `metadata["category"]` bereits sauber in Ordner einsortiert werden[cite: 1, 2].
2. **Kompakte Root-Label:**
   * `"📁 Service-Sets"` ➔ **`"📁 Sets"`**[cite: 1, 2]
   * `"📦 Alle verfügbaren Plugins"` / `"Alle verfügbaren Services"` ➔ **`"📦 Services"`**[cite: 1, 2]

---

## 2. Code-Anpassungen in `analytics/engine/service_selector_model.py`

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

## 3. UI-Absicherung (`serviceui/master_tree.py`)

Falls im `MasterTree` oder im `ServiceSelectorWidget` noch explizite String- oder Group-Checks auf `"standalone"` oder den alten Label-Text existieren, entferne diese bzw. passe sie auf `self.GROUP_PLUGINS` (`"plugins"`) und `"📁 Sets"` / `"📦 Services"` an.

---

## 4. Verifikation (Harte Regeln)

1. **Statischer Syntax-Check:**

python -m py_compile analytics/engine/service_selector_model.py serviceui/master_tree.py


2. **Isolierter Baum-Test in `test/test.py`:**
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

## 8.1 Aenderungen in `analytics/engine/service_selector_model.py`

* **Konstante `GROUP_STANDALONE = "standalone"` entfernt** (ersatzlos; Kommentar
  an der Gruppen-Konstanten-Stelle dokumentiert die Entscheidung).
* **Hilfsmethode `get_standalone_plugin_ids()` entfernt** (keine Aufrufer mehr).
* **`build_tree()`** liefert nur noch 2 Root-Dicts:
  1. `{"group": GROUP_SETS, "label": "📁 Sets", "children": set_nodes}`
  2. `{"group": GROUP_PLUGINS, "label": "📦 Services", "children": plugin_nodes}`
  – `plugin_nodes` weiterhin via `_category_nodes(sorted(plugins.keys()))`
  (Kategorie-Ordner + flache Blaetter, sortiert nach K8).
* Docstring der Methode aktualisiert (2-Gruppen-Kontrakt).

## 8.2 Aenderungen in `serviceui/master_tree.py`

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
* **`test/test.py` Teil 15 (NEU, 4 Checks):**
  * T1) `GROUP_STANDALONE` existiert nicht mehr – PASS.
  * T2) build_tree liefert genau 2 Root-Gruppen mit Labels
    `📁 Sets` / `📦 Services` – PASS.
  * T3) Keine Gruppe `"standalone"` in build_tree – PASS.
  * T4) Swing-Services (Teil 14) in der Hauptgruppe: Kategorie-Ordner
    `Swing Points/...` + flache Blaetter koexistieren, keine leeren Ordner – PASS.
* **`test/test.py` Teil 13/14 angepasst:** `P16.08 T5` erwartete 4 Ordner-
  Knoten (plugin_a mit Kategorie A/B in BEIDEN Gruppen). Da die Standalone-
  Gruppe entfaellt, erscheint plugin_a nur noch einmal -> Erwartung auf
  **2 Ordner-Knoten** korrigiert (Kommentar aktualisiert). Alle P16.08 T1..T5
  und 17.01 T1..T4 weiterhin PASS.
* **Verbleibende 6 Harness-FAILURES** (unbeteiligt, PersistentWindow-Position/
  -Groesse, vor 17.01 bereits vorhanden): P2, P5, H3, H4, H5, H7.

## 8.4 Offen

* 7.5 Test-Cleanup (Invariante 10) weiterhin bis Kapitel-Abnahme offen;
  temporaere Helfer in `test/` (`_insert_part15.py`, `_fix_part15_t5.py`,
  `_inspect_tree_lines.py`, `_tree_lines_out.txt`) werden beim Cleanup entfernt.
