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

---

# 17.02 Review & Entscheidungen (07.08.2026) - Konsistenzpruefung gegen den Ist-Code

> **Implementierungs-Log (Review, kein Coding):** Am 07.08.2026 wurde das
> Kapitel "17.02 Trend Services" (frische Doku, Commit `494335e x` - das
> Dokument enthaelt neben den Phase-17-Grundsaetzen NUR noch die 17.02-
> Spezifikation) gegen den realen Quellcode geprueft:
> `analytics/features/plugins/base_plugin.py`, `analytics/features/feature_builder.py`,
> `analytics/features/definitions/srv_swing_*.py`, `test/test.py`.
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
* **`test/test.py`:** Die Teile **22 und 23 existieren bereits** (17.01.05,
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
  `test/test.py`; Gesamtlauf `test/test.py` mit erwarteten 6 vorbestehenden
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

**Verifikation:** `test/test.py` Teil 25 (T1–T9): Box waechst/schrumpft mit
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

**Fix (`serviceui/param_columns.py`, 2 Stellen):**
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

**Verifikation:** `test/test.py` Teil 25 (T1–T15) alle PASS; Gesamtlauf mit
exakt den 6 vorbestehenden Harness-FAILURES (P2, P5, H3, H4, H5, H7 –
PersistentWindow-Position/-Groesse, offscreen-bedingt, dokumentierte
Baseline). Test-Cleanup gem. Invariante 10 (temporaere Helfer entfernt).

  erforderlich).
