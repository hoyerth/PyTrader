# analytics/features/definitions/srv_trend_regime.py
# ==============================================================================
# DEFINITION: srv_trend_regime
# ==============================================================================
# NAME:        Trend Regime Service
# KATEGORIE:   Trend & Reversal/Regime & Staerke
# BESCHREIBUNG: Statistische Trendstaerke- und Regime-Analyse via LinReg (R2), ADX/DMI & Z-Score
# ==============================================================================
"""
Service: TrendRegime (Phase 17.02) - Naming Convention 16.08.01: srv_

Quantifiziert statistische Trend-Regimes, Trendstaerken und
Mittelwertabweichungen. Reiner Datenlieferant fuer die Analytics-UI und
spaetere ML-Pipelines - KEINE Chart-Visualisierung in diesem Kapitel (17.02,
§1); dedizierte Chart-Indikatoren (ind_...) folgen erst nach statistischer
Validierung der erzeugten Features.

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt der betrachteten Kerze (Bar-Close-Signal).
  * confirmation_bar_time: identisch zu event_bar_time (Bar-Close-Signal,
                           confirmation_lag_bars = 0).
  * Kerzen am Serienanfang ohne ausreichenden Lookback erhalten
    calculation_status = 'INSUFFICIENT_DATA' und is_trend_* = False.

Datenvertrag (17.02 §3): result_type TREND|REVERSAL, 1 Record pro Bar,
flache Records (nur bar_time + feature_data-Inhalte; symbol/timeframe/
feature_id setzt store_plugin_payload selbst).

Capabilities (E-5, 07.08.2026): chart=False (kein Indikator), batch=True,
live=False, feature_store=True, render=False.
metadata['category'] = 'Trend & Reversal/Regime & Staerke' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_TREND_REGIME_SCHEMA` direkt unter diesem Header
(siehe dort) und sind wie in PineScript am Dateianfang anpassbar.
`parameter_schema` gibt eine flache Kopie zurueck (M1: kein geteiltes
mutable Dict ueber Instanzen). `visible_when` (17.01.05): Conditional
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
# Prop-Fenster. Inputs/Defaults stehen hier direkt am Dateianfang.
# E-2 (07.08.2026): type-Werte als Strings ("int"/"float"/"str").
# E-4 (17.02 Review): `visible_when`-Deklarationen fuer die Conditional
# Visibility (17.01.05).
# ---------------------------------------------------------------------------
_TREND_REGIME_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "Linear_Regression_Slope",
        "options": [
            "Linear_Regression_Slope", "ADX_DMI", "ZScore_Mean_Distance",
        ],
        "description": "Algorithmus-Modus zur Trend-Regime-Bestimmung",
    },
    "period": {
        "type": "int", "default": 20, "min": 2,
        "description": "Berechnungsperiode fuer Regressions-/Statistik-Fenster",
    },
    "r2_threshold": {
        "type": "float", "default": 0.6, "min": 0.0, "max": 1.0,
        "description": "Mindest-R2 fuer etablierten Trend (LinReg)",
        "visible_when": {"mode": "Linear_Regression_Slope"},
    },
    "di_period": {
        "type": "int", "default": 14, "min": 1,
        "description": "DMI-Periode (nur bei mode == 'ADX_DMI')",
        "visible_when": {"mode": "ADX_DMI"},
    },
    "adx_smooth": {
        "type": "int", "default": 14, "min": 1,
        "description": "ADX-Glaettung (nur bei mode == 'ADX_DMI')",
        "visible_when": {"mode": "ADX_DMI"},
    },
    "adx_threshold": {
        "type": "float", "default": 25.0, "min": 1.0,
        "description": "ADX-Schwellwert fuer Trend-Regime",
        "visible_when": {"mode": "ADX_DMI"},
    },
    "z_thresh": {
        "type": "float", "default": 2.0, "min": 0.1,
        "description": "Z-Score Extremwert-Schwelle fuer Reversals",
        "visible_when": {"mode": "ZScore_Mean_Distance"},
    },
    "ma_type": {
        "type": "str",
        "default": "SMA",
        "options": [
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA",
        ],
        "description": "Gleitender Durchschnitt fuer Z-Score Baseline",
        "visible_when": {"mode": "ZScore_Mean_Distance"},
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


def _rolling_slope_r2(series: pd.Series, period: int) -> pd.Series:
    """Vektorisierte rolling LinReg: Steigung und R2 je Fenster.

    slope = Sxy / Sxx,  r2 = Sxy^2 / (Sxx * Syy)
    x = arange(period) (konstant), Sxx = sum((x-xbar)^2).
    Liefert NaN fuer Fenster mit fehlenden Werten (Warmup).
    """
    x = np.arange(period, dtype=float)
    xm = x - x.mean()
    sxx = float((xm ** 2).sum())

    def _slope(w: np.ndarray) -> float:
        y = np.asarray(w, dtype=float)
        if np.isnan(y).any() or sxx == 0:
            return np.nan
        ym = y - y.mean()
        sxy = float((xm * ym).sum())
        return sxy / sxx

    def _r2(w: np.ndarray) -> float:
        y = np.asarray(w, dtype=float)
        if np.isnan(y).any() or sxx == 0:
            return np.nan
        ym = y - y.mean()
        sxy = float((xm * ym).sum())
        syy = float((ym ** 2).sum())
        if syy <= 0:
            return 0.0
        return (sxy ** 2) / (sxx * syy)

    roll = series.rolling(period, min_periods=period)
    slope = roll.apply(_slope, raw=True)
    r2 = roll.apply(_r2, raw=True)
    return pd.DataFrame({"slope": slope, "r2": r2})


def _adx_dmi(df: pd.DataFrame, di_period: int, adx_smooth: int
             ) -> pd.DataFrame:
    """ADX/DMI (Wilder) vektorisiert: +DI, -DI, ADX.

    +DM = high - prev_high (falls > 0 und > -(low - prev_low))
    -DM = prev_low - low   (falls > 0 und > high - prev_high)
    Glaettung: Wilder RMA (EWM alpha=1/period, adjust=False).
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(np.where(
        (up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index)
    minus_dm = pd.Series(np.where(
        (down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index)

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    alpha = 1.0 / max(di_period, 1)
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    alpha_adx = 1.0 / max(adx_smooth, 1)
    adx = dx.ewm(alpha=alpha_adx, adjust=False).mean()

    return pd.DataFrame({
        "plus_di": plus_di,
        "minus_di": minus_di,
        "adx": adx,
    })


def _zscore_series(df: pd.DataFrame, ma: np.ndarray, period: int
                   ) -> np.ndarray:
    """Z-Score = (close - MA) / rolling-std(close, period)."""
    close = df["close"].astype(float)
    std = close.rolling(period, min_periods=period).std(ddof=0).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (close.to_numpy() - ma) / std
    return np.where(np.isfinite(std) & (std > 0), z, np.nan)


class SrvTrendRegime(PluginFeature):
    """Statistische Trendstaerke- und Regime-Analyse.

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) - keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_trend_regime"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Trend & Reversal/Regime & Staerke",
            "display_name": "Trend Regime Service",
            "description": "Quantifiziert Trendstaerke und Regimes ueber LinReg Slope/R2, ADX/DMI und Z-Score Mean Distance.",
            "author": "PyTrader AI",
            "tags": ["trend", "regime", "linreg", "adx", "zscore"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) fuer "
                                "die Analytics-UI und ML-Pipelines. LinReg misst "
                                "Steigung und Bestimmtheitsmass R2. ADX/DMI misst "
                                "Richtungsdynamik. Z-Score misst die "
                                "Standardabweichung vom Mittelwert fuer "
                                "Uebertreibungen. Keine Chart-Visualisierung in "
                                "Kapitel 17.02.",
            "condition_rules": [
                "Linear_Regression_Slope: TrendUp = Slope > 0 and R2 >= r2_threshold",
                "ADX_DMI: TrendUp = +DI > -DI and ADX >= adx_threshold",
                "ZScore_Mean_Distance: ReversalUp = Z-Score <= -z_thresh (Ueberverkauft), ReversalDown = Z >= +z_thresh (Ueberkauft)",
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
        return list(_TREND_REGIME_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Algorithmus-Modus",
            "period": "Statistik-Fenster",
            "r2_threshold": "Mindest-R2 (LinReg)",
            "di_period": "DMI-Periode (ADX)",
            "adx_smooth": "ADX-Glaettung",
            "adx_threshold": "ADX-Schwellwert",
            "z_thresh": "Z-Score Schwelle",
            "ma_type": "MA-Typ (Z-Score Baseline)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_TREND_REGIME_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _TREND_REGIME_SCHEMA.items()}

    # 2. SCHEMA-EXPOSURE FUER DIE UI (17.01.04, Bugfix): Die Spalten-UI
    # (serviceui/param_columns.py & ServiceSelectorWidget) liest Parameter-
    # Definitionen ueber `default_params` / `full_parameter_schema()`. Diese
    # expliziten Overrides stellen das Schema unabhaengig von der jeweiligen
    # parameter_schema-Definition (Property/Klassen-Attribut) bereit und
    # erhalten den Basisklassen-Vertrag (Basis-Parameter wie lookback +
    # plugin-spezifische Parameter, vgl. base_plugin.PluginFeature).
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
        """Berechnet Trend-Regimes (LinReg/ADX/Z-Score).

        Datenvertrag (17.02 §3): JEDER Bar entspricht genau EIN Record
        (dichte Label-Reihe fuer ML/Analytics). Trend-Bars tragen
        is_trend_up/is_trend_down bzw. is_reversal_up/is_reversal_down=True
        sowie kausale Zeitstempel (event/confirmation_bar_time,
        confirmation_lag_bars = 0 fuer Bar-Close-Signale). Bars am
        Serienanfang ohne ausreichenden Lookback erhalten
        calculation_status='INSUFFICIENT_DATA'.

        Modi (params['mode']):
          * Linear_Regression_Slope: rolling LinReg auf close
            (Slope > 0 und R2 >= r2_threshold => TrendUp).
          * ADX_DMI: +DI > -DI und ADX >= adx_threshold => TrendUp.
          * ZScore_Mean_Distance: Z <= -z_thresh => ReversalUp,
            Z >= +z_thresh => ReversalDown (Uebertreibungen).
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
        mode = str(p.get("mode") or "Linear_Regression_Slope")
        period = int(p.get("period") or 20)
        r2_threshold = float(p.get("r2_threshold") or 0.6)
        di_period = int(p.get("di_period") or 14)
        adx_smooth = int(p.get("adx_smooth") or 14)
        adx_threshold = float(p.get("adx_threshold") or 25.0)
        z_thresh = float(p.get("z_thresh") or 2.0)
        ma_type = str(p.get("ma_type") or "SMA")

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)

        is_trend_up = np.zeros(n, dtype=bool)
        is_trend_down = np.zeros(n, dtype=bool)
        is_rev_up = np.zeros(n, dtype=bool)
        is_rev_down = np.zeros(n, dtype=bool)
        status = np.full(n, "OK", dtype=object)
        strength = np.zeros(n, dtype=float)
        strength_type = "R2_SCORE"
        conf_type = "BAR_CLOSE"
        extra: Dict[str, np.ndarray] = {}

        if mode == "Linear_Regression_Slope":
            lr = _rolling_slope_r2(work["close"], period)
            slope = lr["slope"].to_numpy(dtype=float)
            r2 = lr["r2"].to_numpy(dtype=float)
            nan = ~np.isfinite(slope) | ~np.isfinite(r2)
            status[nan] = "INSUFFICIENT_DATA"
            is_trend_up = (slope > 0) & (r2 >= r2_threshold)
            is_trend_down = (slope < 0) & (r2 >= r2_threshold)
            strength = np.where(np.isfinite(r2), r2, 0.0)
            strength_type = "R2_SCORE"
            extra["slope_value"] = np.where(np.isfinite(slope), slope, np.nan)
            extra["r2_score"] = np.where(np.isfinite(r2), r2, np.nan)

        elif mode == "ADX_DMI":
            dmi = _adx_dmi(work, di_period, adx_smooth)
            plus_di = dmi["plus_di"].to_numpy(dtype=float)
            minus_di = dmi["minus_di"].to_numpy(dtype=float)
            adx = dmi["adx"].to_numpy(dtype=float)
            nan = ~np.isfinite(adx)
            status[nan] = "INSUFFICIENT_DATA"
            is_trend_up = (plus_di > minus_di) & (adx >= adx_threshold)
            is_trend_down = (minus_di > plus_di) & (adx >= adx_threshold)
            strength = np.where(np.isfinite(adx), adx, 0.0)
            strength_type = "ADX_VALUE"
            extra["adx_value"] = np.where(np.isfinite(adx), adx, np.nan)
            extra["plus_di"] = np.where(np.isfinite(plus_di), plus_di, np.nan)
            extra["minus_di"] = np.where(np.isfinite(minus_di), minus_di, np.nan)

        elif mode == "ZScore_Mean_Distance":
            # MA-Serie (Template 16.04, alle 12 Typen; VWMA nutzt tick_volume).
            try:
                from chart.indicators.utils.ma_template import MATemplateEngine
            except Exception:
                MATemplateEngine = None  # type: ignore
            if MATemplateEngine is not None and ma_type in (
                    "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
                    "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"):
                volume = work["tick_volume"] if "tick_volume" in work.columns else None
                ma = MATemplateEngine.calculate_ma(
                    work["close"], ma_type, period, volume=volume,
                ).to_numpy(dtype=float)
            else:
                # Fallback: einfacher SMA (defensiv, kein Crash).
                ma = pd.Series(close).rolling(period, min_periods=1).mean().to_numpy()

            z = _zscore_series(work, ma, period)
            nan = ~np.isfinite(z)
            status[nan] = "INSUFFICIENT_DATA"
            is_rev_up = z <= -z_thresh
            is_rev_down = z >= z_thresh
            strength = np.where(np.isfinite(z), np.abs(z), 0.0)
            strength_type = "Z_SCORE"
            extra["z_score_value"] = np.where(np.isfinite(z), z, np.nan)
            extra["mean_baseline"] = np.where(np.isfinite(ma), ma, np.nan)

        else:
            # Unbekannter Modus: defensiv leer (kein Crash, 0 Rows).
            return empty

        # --- Records bauen (dicht: 1 Record pro Bar, 17.02 §3) --------------
        records: List[Dict[str, Any]] = []
        total_up = int(is_trend_up.sum())
        total_down = int(is_trend_down.sum())
        total_rev_up = int(is_rev_up.sum())
        total_rev_down = int(is_rev_down.sum())
        for i in range(n):
            rec: Dict[str, Any] = {
                "bar_time": int(times[i]),
                "result_type": "REVERSAL" if (is_rev_up[i] or is_rev_down[i])
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
                    "total_reversal_up": total_rev_up,
                    "total_reversal_down": total_rev_down,
                    "bars": n,
                },
            },
        }
