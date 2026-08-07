# analytics/features/definitions/srv_trend_breakout.py
# ==============================================================================
# DEFINITION: srv_trend_breakout
# ==============================================================================
# NAME:        Trend Breakout Service
# KATEGORIE:   Trend & Reversal/Breakout & Kanal
# BESCHREIBUNG: Trendfolgende Trailing-Stops & Kanal-Breakouts via Supertrend & Donchian/Keltner
# ==============================================================================
"""
Service: TrendBreakout (Phase 17.02) - Naming Convention 16.08.01: srv_

Erkennt Trendwechsel und Ausbrueche ueber dynamische ATR-Trailings und
Bänder (Supertrend ATR, Donchian/Keltner-Kanaele). Reiner Datenlieferant
fuer die Analytics-UI und spaetere ML-Pipelines - KEINE Chart-Visualisierung
in diesem Kapitel (17.02, §1).

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt der betrachteten Kerze (Bar-Close-Signal).
  * confirmation_bar_time: identisch zu event_bar_time (confirmation_lag_bars
                           = 0).
  * Kerzen am Serienanfang ohne ausreichenden Lookback (Kanal-/ATR-Warmup)
    erhalten calculation_status = 'INSUFFICIENT_DATA' und is_trend_* = False.

Datenvertrag (17.02 §3): result_type TREND|BREAKOUT, 1 Record pro Bar,
flache Records (nur bar_time + feature_data-Inhalte; symbol/timeframe/
feature_id setzt store_plugin_payload selbst).

Capabilities (E-5, 07.08.2026): chart=False, batch=True, live=False,
feature_store=True, render=False.
metadata['category'] = 'Trend & Reversal/Breakout & Kanal' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Modul-Konstante
`_TREND_BREAKOUT_SCHEMA` direkt unter diesem Header. `parameter_schema`
gibt eine flache Kopie zurueck (M1). `visible_when` (17.01.05): Conditional
Visibility beim Mode-Wechsel.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 17.01): Single Source of Truth fuer das
# Prop-Fenster. E-2: type-Werte als Strings. E-4: `visible_when`-Deklarationen.
# ---------------------------------------------------------------------------
_TREND_BREAKOUT_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "Supertrend_ATR",
        "options": ["Supertrend_ATR", "Donchian_Keltner_Breakout"],
        "description": "Breakout-Algorithmus",
    },
    "channel_type": {
        "type": "str",
        "default": "Donchian",
        "options": ["Donchian", "Keltner"],
        "description": "Kanal-Typ bei mode == 'Donchian_Keltner_Breakout'",
        "visible_when": {"mode": "Donchian_Keltner_Breakout"},
    },
    "atr_period": {
        "type": "int", "default": 10, "min": 1,
        "description": "ATR-Periode fuer Supertrend / Keltner",
    },
    "atr_mult": {
        "type": "float", "default": 3.0, "min": 0.1,
        "description": "ATR-Multiplikator fuer Bänder/Trailing",
    },
    "period": {
        "type": "int", "default": 20, "min": 2,
        "description": "Donchian/Keltner Kanal-Periode",
        "visible_when": {"mode": "Donchian_Keltner_Breakout"},
    },
    "ma_type": {
        "type": "str",
        "default": "EMA",
        "options": [
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA",
        ],
        "description": "MA-Typ fuer Keltner Baseline",
        "visible_when": {"mode": "Donchian_Keltner_Breakout"},
    },
}


# ---------------------------------------------------------------------------
# Modul-Helfer (17.02: direkte, vollstaendige Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-ATR (EMA-alpha 1/period, adjust=False) ueber OHLCV."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _supertrend(df: pd.DataFrame, atr_period: int, atr_mult: float
                ) -> pd.DataFrame:
    """Supertrend (ATR-Trailing) vektorisiert mit sequenzieller
    final-Band-Regel (wie im Ist-Stand des Projekts).

    basic_upper/lower = (high+low)/2 +- atr_mult * ATR.
    final_upper/lower: klemmt das Band in Trendrichtung (kein Ueberspringen
    beim Wechsel). supertrend = final_upper (downtrend) | final_lower (uptrend).
    """
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    close = df["close"].astype(float).to_numpy()
    atr = _atr_series(df, atr_period).to_numpy(dtype=float)

    n = len(df)
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + atr_mult * atr
    basic_lower = hl2 - atr_mult * atr

    final_upper = np.empty(n)
    final_lower = np.empty(n)
    supertrend = np.empty(n)
    direction = np.zeros(n, dtype=bool)  # True = uptrend

    for i in range(n):
        if i == 0:
            final_upper[i] = basic_upper[i]
            final_lower[i] = basic_lower[i]
            direction[i] = close[i] > final_upper[i]
        else:
            # final_upper: nur nach oben ziehen, wenn vorher nicht drunter.
            prev_close = close[i - 1]
            if prev_close <= final_upper[i - 1]:
                final_upper[i] = min(basic_upper[i], final_upper[i - 1])
            else:
                final_upper[i] = basic_upper[i]
            if prev_close >= final_lower[i - 1]:
                final_lower[i] = max(basic_lower[i], final_lower[i - 1])
            else:
                final_lower[i] = basic_lower[i]
            # Richtung beibehalten, bis der Schlusskurs die Linie durchbricht.
            if direction[i - 1]:
                if close[i] < final_lower[i]:
                    direction[i] = False
                else:
                    direction[i] = True
            else:
                if close[i] > final_upper[i]:
                    direction[i] = True
                else:
                    direction[i] = False

        supertrend[i] = final_lower[i] if direction[i] else final_upper[i]

    return pd.DataFrame({
        "supertrend_line": supertrend,
        "direction": direction,
        "atr": atr,
    }, index=df.index)


def _donchian_keltner(df: pd.DataFrame, channel_type: str, period: int,
                      ma_type: str, atr_period: int, atr_mult: float
                      ) -> pd.DataFrame:
    """Donchian- oder Keltner-Kanal vektorisiert (upper/lower/middle)."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    if channel_type == "Keltner":
        # MA-Serie (Template 16.04, alle 12 Typen; VWMA nutzt tick_volume).
        try:
            from chart.indicators.utils.ma_template import MATemplateEngine
        except Exception:
            MATemplateEngine = None  # type: ignore
        if MATemplateEngine is not None and ma_type in (
                "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
                "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"):
            volume = df["tick_volume"] if "tick_volume" in df.columns else None
            middle = MATemplateEngine.calculate_ma(
                close, ma_type, period, volume=volume)
        else:
            middle = close.rolling(period, min_periods=1).mean()
        atr = _atr_series(df, atr_period)
        upper = middle + atr_mult * atr
        lower = middle - atr_mult * atr
    else:  # Donchian
        # Kausaler Kanal: NUR abgeschlossene Bars (shift(1)) - ein Close
        # bricht die letzten N Bars DURCH. Ohne shift waere upper >= aktuelle
        # high > close immer, ein Breakout-Signal nie moeglich (Bugfix
        # waehrend der Tests, 17.02 Umsetzung).
        upper = high.shift(1).rolling(period, min_periods=period).max()
        lower = low.shift(1).rolling(period, min_periods=period).min()
        middle = (upper + lower) / 2.0

    return pd.DataFrame({
        "upper_band": upper,
        "lower_band": lower,
        "middle_band": middle,
    })


class SrvTrendBreakout(PluginFeature):
    """Trend-Ausbrueche & Trailing-Stops (Supertrend, Donchian/Keltner).

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) - keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_trend_breakout"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Trend & Reversal/Breakout & Kanal",
            "display_name": "Trend Breakout Service",
            "description": "Erfasst Trend-Ausbrueche und Trailing-Stops ueber Supertrend ATR und Donchian/Keltner-Kanaele.",
            "author": "PyTrader AI",
            "tags": ["trend", "breakout", "supertrend", "donchian", "keltner"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) fuer "
                                "die Analytics-UI und ML-Pipelines. Liefert "
                                "kausale Trendwechsel-Signale. Supertrend "
                                "schaltet bei Schlusskurs-Durchbruch des "
                                "Median+-ATR-Bandes um. Donchian/Keltner "
                                "signalisiert Ausbrueche aus N-Bar Extrema "
                                "oder Volatilitaetsbändern. Keine "
                                "Chart-Visualisierung in Kapitel 17.02.",
            "condition_rules": [
                "Supertrend_ATR: TrendUp = Close > Supertrend_Line",
                "Donchian_Keltner_Breakout: TrendUp = Close > Upper_Channel_Band",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": False,   # E-5: kein Indikator in Kapitel 17.02
            "batch": True,
            "live": False,
            "feature_store": True,
            "render": False,  # E-5: reine Datenlieferanten
        }

    # --- Single Source of Truth fuer's Prop-Fenster (17.01 §2.2, PineScript-Zone)
    @property
    def parameter_order(self) -> List[str]:
        return list(_TREND_BREAKOUT_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Breakout-Algorithmus",
            "channel_type": "Kanal-Typ (Donchian/Keltner)",
            "atr_period": "ATR-Periode",
            "atr_mult": "ATR-Multiplikator",
            "period": "Kanal-Periode",
            "ma_type": "MA-Typ (Keltner Baseline)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_TREND_BREAKOUT_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _TREND_BREAKOUT_SCHEMA.items()}

    # 2. SCHEMA-EXPOSURE FUER DIE UI (17.01.04, Bugfix): Siehe
    # srv_trend_regime.py - identischer Basisklassen-Vertrag.
    @property
    def default_params(self) -> Dict[str, Any]:
        """Extrahiert die Default-Werte aus dem parameter_schema fuer die Engine."""
        return {k: v.get("default") for k, v in self.parameter_schema.items()
                if "default" in v}

    def full_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Liefert das vollstaendige Schema (Basis + plugin-spezifisch) inkl.
        Min/Max/Typ fuer die UI-Spalten (Basisklassen-Vertrag)."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Trend-Breakouts (Supertrend/Donchian/Keltner).

        Datenvertrag (17.02 §3): 1 Record pro Bar (dichte Label-Reihe).
        Trend-Bars tragen is_trend_up/is_trend_down=True sowie kausale
        Zeitstempel (event/confirmation_bar_time, confirmation_lag_bars=0).
        Bars am Serienanfang ohne Kanal-/ATR-Historie erhalten
        calculation_status='INSUFFICIENT_DATA'.

        Modi (params['mode']):
          * Supertrend_ATR: ATR-Trailing; TrendUp = Close > Supertrend_Line.
          * Donchian_Keltner_Breakout: Donchian (N-Bar Extrema) oder Keltner
            (MA +- ATR-Multiplikator); TrendUp = Close > Upper_Channel_Band.
        """
        empty: FeatureCalculateResult = {"feature_store_payload": {}}
        if df is None or df.empty:
            return empty

        # Defensive Normalisierung: 'time'-Spalte (epoch) sicherstellen.
        work = df.copy()
        if "time" not in work.columns:
            if "bar_time" in work.columns:
                work["time"] = work["bar_time"].apply(
                    lambda v: int(v.timestamp())
                    if hasattr(v, "timestamp") else int(v))
            else:
                return empty

        p = self.validate_params(params)
        mode = str(p.get("mode") or "Supertrend_ATR")
        channel_type = str(p.get("channel_type") or "Donchian")
        atr_period = int(p.get("atr_period") or 10)
        atr_mult = float(p.get("atr_mult") or 3.0)
        period = int(p.get("period") or 20)
        ma_type = str(p.get("ma_type") or "EMA")

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)

        is_trend_up = np.zeros(n, dtype=bool)
        is_trend_down = np.zeros(n, dtype=bool)
        is_rev_up = np.zeros(n, dtype=bool)
        is_rev_down = np.zeros(n, dtype=bool)
        status = np.full(n, "OK", dtype=object)
        strength = np.zeros(n, dtype=float)
        strength_type = "ATR_DISTANCE"
        conf_type = "BAR_CLOSE"
        extra: Dict[str, np.ndarray] = {}

        if mode == "Supertrend_ATR":
            st = _supertrend(work, atr_period, atr_mult)
            line = st["supertrend_line"].to_numpy(dtype=float)
            atr = st["atr"].to_numpy(dtype=float)
            nan = ~np.isfinite(line) | ~np.isfinite(atr)
            status[nan] = "INSUFFICIENT_DATA"
            is_trend_up = close > line
            is_trend_down = close < line
            # Staerke: Distanz in ATR-Einheiten.
            strength = np.where(
                (np.isfinite(atr)) & (atr > 0),
                np.abs(close - line) / np.where(atr > 0, atr, np.nan),
                0.0)
            extra["supertrend_line"] = np.where(np.isfinite(line), line, np.nan)
            extra["atr_value"] = np.where(np.isfinite(atr), atr, np.nan)

        elif mode == "Donchian_Keltner_Breakout":
            ch = _donchian_keltner(work, channel_type, period, ma_type,
                                   atr_period, atr_mult)
            upper = ch["upper_band"].to_numpy(dtype=float)
            lower = ch["lower_band"].to_numpy(dtype=float)
            middle = ch["middle_band"].to_numpy(dtype=float)
            nan = ~np.isfinite(upper) | ~np.isfinite(lower)
            status[nan] = "INSUFFICIENT_DATA"
            is_trend_up = close > upper
            is_trend_down = close < lower
            spread = np.where(
                (np.isfinite(upper)) & (np.isfinite(lower)),
                (upper - lower) / 2.0, np.nan)
            strength = np.where(
                (np.isfinite(spread)) & (spread > 0),
                np.abs(close - middle) / np.where(spread > 0, spread, np.nan),
                0.0)
            strength_type = "ATR_DISTANCE"
            extra["upper_band"] = np.where(np.isfinite(upper), upper, np.nan)
            extra["lower_band"] = np.where(np.isfinite(lower), lower, np.nan)
            extra["middle_band"] = np.where(np.isfinite(middle), middle, np.nan)

        else:
            # Unbekannter Modus: defensiv leer (kein Crash, 0 Rows).
            return empty

        # --- Records bauen (dicht: 1 Record pro Bar, 17.02 §3) --------------
        records: List[Dict[str, Any]] = []
        total_up = int(is_trend_up.sum())
        total_down = int(is_trend_down.sum())
        for i in range(n):
            rec: Dict[str, Any] = {
                "bar_time": int(times[i]),
                "result_type": "BREAKOUT" if (is_trend_up[i] or is_trend_down[i])
                else "TREND",
                "source_mode": mode,
                "calculation_status": str(status[i]),
                "is_trend_up": bool(is_trend_up[i]),
                "is_trend_down": bool(is_trend_down[i]),
                "is_reversal_up": bool(is_rev_up[i]),
                "is_reversal_down": bool(is_rev_down[i]),
                # Bar-Close-Signal: event == confirmation (Lag 0).
                "event_bar_time": int(times[i]),
                "confirmation_bar_time": int(times[i]),
                "confirmation_lag_bars": 0,
                "confirmation_type": conf_type,
                "trend_strength": float(strength[i]),
                "strength_type": strength_type,
                "reference_price": float(close[i]),
            }
            for k, arr in extra.items():
                rec[k] = float(arr[i]) if np.isfinite(arr[i]) else None
            records.append(rec)

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {
                    # E-7 / base_plugin (U15-A1, Invariante 5): schema_version
                    # ist Pflichtfeld fuer alle feature_store=True-Plugins.
                    "schema_version": "1.0.0",
                    "source_mode": mode,
                    "total_trend_up": total_up,
                    "total_trend_down": total_down,
                    "bars": n,
                },
            },
        }
