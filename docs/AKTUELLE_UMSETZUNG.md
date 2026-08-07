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
2. **Headless-Validierung:** Keine GUI/UI-Tests (`no QApplication.exec()`). Tests erfolgen rein headless über PyTest / den Harness `test/test.py`.
3. **Dateipfad & Präfix:** Strikte Ablage unter `analytics/features/definitions/srv_trend_*.py` mit `plugin_id = "srv_trend_*"`.
4. **PineScript-Input-Zone (E-2/E-3):** Schema als Modul-Konstante am Dateianfang, Typen als **Strings** (`"int"`, `"float"`, `"str"`, `"bool"`). Property `parameter_schema` liefert eine flache Kopie (`{k: dict(v) ...}`).
5. **UI-Exposure (17.01.04):** Alle Klassen implementieren explizit `@property def default_params` und `def full_parameter_schema()` (Verbindung von `base_parameter_schema` und `parameter_schema`).
6. **Capabilities (E-5):** Explizit `capabilities = {"chart": False, "batch": True, "live": False, "feature_store": True, "render": False}`.
7. **Causal Timestamps:** `event_bar_time` (Zeitpunkt des Extremums/Breakouts), `confirmation_bar_time` (Kausale Bestätigungs-Bar $\ge$ event), `confirmation_lag_bars` (Bar-Abstand).
8. **Datenbank-PK & Write-Pfad (E-1):** Verträglichkeit mit dem 4-Spalten-PK `(symbol, timeframe, bar_time, feature_id)` via `ON CONFLICT (symbol, timeframe, bar_time, feature_id)`.
9. **Schema-Version (E-7):** Payload-Metadata und Records enthalten zwingend `"schema_version": "1.0.0"`.
10. **Test-Cleanup (Invariante 10):** Temporäre Test-Datenbanken (`*.duckdb`) und Hilfsskripte in `test/` werden nach dem Testlauf gelöscht. Nur `test/test.py` bleibt als permanenter Harness bestehen.

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

1. Erstelle die 3 Dateien unter `analytics/features/definitions/`:
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

### Schritt 4: Harness-Integration in `test/test.py` (Teil 22)

Ergänze `test/test.py` um **Teil 22 (Trend Services Validation)**:

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

Nach erfolgreichem Testlauf werden temporäre Test-Datenbanken (`*.duckdb`) und temporäre Helfer-Skripte im Ordner `test/` gelöscht. Nur die erweiterte `test/test.py` bleibt als dauerhafter Harness bestehen.


