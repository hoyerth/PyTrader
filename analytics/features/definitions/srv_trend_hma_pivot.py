# analytics/features/definitions/srv_trend_hma_pivot.py
# ==============================================================================
# DEFINITION: srv_trend_hma_pivot
# ==============================================================================
# NAME:        HMA Peak-Toleranz Pivot Service
# KATEGORIE:   Trend & Reversal/Hysteresis & Pivots
# BESCHREIBUNG: Trendwechsel-Erkennung auf geglaetteter EHMA/HMA mit Prozent-Hysterese
# ==============================================================================
"""
Service: TrendHmaPivot (Phase 17.02) - Naming Convention 16.08.01: srv_

Spezialisierter Trendwechsel-Detektor auf Basis von HMA/EHMA-Extrema und
prozentualer Hysterese (PineScript-Logik `piv_pendingExtremeValue`).
Reiner Datenlieferant fuer die Analytics-UI und spaetere ML-Pipelines -
KEINE Chart-Visualisierung in diesem Kapitel (17.02, §1).

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt der betrachteten Kerze (Bar-Close-Signal).
  * confirmation_bar_time: identisch zu event_bar_time (confirmation_lag_bars
                           = 0; Bar-Close-Signal der geglaetteten MA).
  * Kerzen am Serienanfang ohne ausreichenden MA-Warmup erhalten
    calculation_status = 'INSUFFICIENT_DATA' und is_trend_* = False.

Datenvertrag (17.02 §3): result_type TREND|REVERSAL, 1 Record pro Bar,
flache Records (nur bar_time + feature_data-Inhalte; symbol/timeframe/
feature_id setzt store_plugin_payload selbst).

Capabilities (E-5, 07.08.2026): chart=False, batch=True, live=False,
feature_store=True, render=False.
metadata['category'] = 'Trend & Reversal/Hysteresis & Pivots' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Modul-Konstante
`_TREND_HMA_PIVOT_SCHEMA` direkt unter diesem Header. `parameter_schema`
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
_TREND_HMA_PIVOT_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "HMA_Peak_Toleranz",
        "options": ["HMA_Peak_Toleranz"],
        "description": "HMA Pivot Hysteresis Modus",
    },
    "piv_len": {
        "type": "int", "default": 4, "min": 1,
        "description": "Pivot-Lookback/Glaettung",
        "visible_when": {"mode": "HMA_Peak_Toleranz"},
    },
    "hma_type": {
        "type": "str",
        "default": "EHMA",
        "options": [
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA",
        ],
        "description": "Gleitender Durchschnittstyp (EHMA/HMA)",
        "visible_when": {"mode": "HMA_Peak_Toleranz"},
    },
    "hma_smoothing": {
        "type": "int", "default": 10, "min": 2,
        "description": "Hauptperiode des MA",
        "visible_when": {"mode": "HMA_Peak_Toleranz"},
    },
    "piv_maxHmaMovePct": {
        "type": "float", "default": 0.2, "min": 0.01,
        "description": "Erforderlicher prozentualer Mindestabstand vom Peak fuer Trendwechsel",
        "visible_when": {"mode": "HMA_Peak_Toleranz"},
    },
}

# ---------------------------------------------------------------------------
# OUTPUT-SCHEMA (20.03): Resultatfelder je feature_data-Record (Datenvertrag
# 17.02 §3, §3.2). `bar_time` ist eine native DB-Spalte und wird NICHT
# deklariert (E4). `type` sind freie Strings (E5). `technical: True` ->
# kompakte Anzeige im Unterblock `🔧 System-Metrik` (E2).
# ---------------------------------------------------------------------------
_TREND_HMA_PIVOT_OUTPUT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "result_type": {
        "type": "str",
        "description": "Klassifikation des Records ('REVERSAL' bei Trendwechsel, sonst 'TREND')",
        "technical": True,
    },
    "source_mode": {
        "type": "str",
        "description": "Aktiver Algorithmus (immer 'HMA_Peak_Toleranz')",
        "technical": True,
    },
    "calculation_status": {
        "type": "str",
        "description": "Berechnungsstatus ('OK' | 'INSUFFICIENT_DATA')",
        "technical": True,
    },
    "is_trend_up": {
        "type": "bool",
        "description": "True, wenn MA das Pending-Low um piv_maxHmaMovePct % nach oben durchbrochen hat",
    },
    "is_trend_down": {
        "type": "bool",
        "description": "True, wenn MA das Pending-High um piv_maxHmaMovePct % nach unten durchbrochen hat",
    },
    "is_reversal_up": {
        "type": "bool",
        "description": "Reversal-Up-Flag (is_trend_up und nicht is_trend_down)",
    },
    "is_reversal_down": {
        "type": "bool",
        "description": "Reversal-Down-Flag (is_trend_down und nicht is_trend_up)",
    },
    "event_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch der Bar (Bar-Close-Signal, event == confirmation)",
        "technical": True,
    },
    "confirmation_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch der Bestätigung (identisch zu event_bar_time)",
        "technical": True,
    },
    "confirmation_lag_bars": {
        "type": "int",
        "description": "Bestätigungs-Verzögerung (immer 0, Bar-Close-Signal)",
        "technical": True,
    },
    "confirmation_type": {
        "type": "str",
        "description": "Bestätigungsart (immer 'BAR_CLOSE')",
        "technical": True,
    },
    "trend_strength": {
        "type": "float",
        "description": "Signalstärke (PERCENT: prozentuale Distanz des Close vom Pending-Extremwert)",
    },
    "strength_type": {
        "type": "str",
        "description": "Stärke-Maßstab (immer 'PERCENT')",
        "technical": True,
    },
    "reference_price": {
        "type": "float",
        "description": "Close-Preis der Bar (Referenzpreis)",
    },
    "ma_value": {
        "type": "float",
        "description": "Geglätteter MA-Wert der Bar (EHMA/HMA) – nullbar",
    },
    "pending_extreme_value": {
        "type": "float",
        "description": "Letzter extremer MA-Wert (piv_pendingExtremeValue) – nullbar",
    },
}

# ---------------------------------------------------------------------------
# Modul-Helfer (17.02: direkte, vollstaendige Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _ma_series(df: pd.DataFrame, ma_type: str, period: int) -> pd.Series:
    """MA-Serie (Template 16.04, alle 12 Typen; VWMA nutzt tick_volume).

    Lokaler Import (E-3, 17.02 Review): `chart.indicators.utils.ma_template`
    - der Pfad `analytics.features.helpers.ma_template` existiert nicht.
    """
    try:
        from chart.indicators.utils.ma_template import MATemplateEngine
    except Exception:
        MATemplateEngine = None  # type: ignore
    close = df["close"].astype(float)
    if MATemplateEngine is not None and ma_type in (
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"):
        volume = df["tick_volume"] if "tick_volume" in df.columns else None
        return MATemplateEngine.calculate_ma(close, ma_type, period,
                                             volume=volume)
    # Fallback: einfacher SMA (defensiv, kein Crash).
    return close.rolling(period, min_periods=1).mean()


def _hma_peak_toleranz(ma: np.ndarray, piv_len: int, move_pct: float
                       ) -> pd.DataFrame:
    """PineScript-Hysterese-Logik auf der geglaetteten MA-Serie.

    Haelt den letzten extremen MA-Wert (`piv_pendingExtremeValue`) als
    gleitendes Extremum ueber ein `piv_len`-Fenster (Rolling min/max,
    min_periods=1, NaN-robust: keine NaN-Verseuchung durch den MA-Warmup).
    Ein Trendwechsel wird erst signalisiert, wenn der MA den Extremwert um
    `move_pct` % durchbricht (verhindert Fehlsignale in Seitwaertsphasen):

      * TrendUp:   MA > PendingLow  * (1 + move_pct/100)
      * TrendDown: MA < PendingHigh * (1 - move_pct/100)

    Liefert je Bar is_trend_up/is_trend_down und die Extremwerte
    (pending_extreme_value) fuer den Datenvertrag (§3.2).
    """
    n = len(ma)
    series = pd.Series(ma)
    # Rolling-Extrema ueber piv_len Fenster (inkl. aktueller Bar);
    # NaN im Warmup werden uebersprungen (skipna) - kein Infekt.
    roll_low = series.rolling(piv_len, min_periods=1).min().to_numpy(dtype=float)
    roll_high = series.rolling(piv_len, min_periods=1).max().to_numpy(dtype=float)

    is_up = np.zeros(n, dtype=bool)
    is_down = np.zeros(n, dtype=bool)
    pending_low = np.full(n, np.nan)
    pending_high = np.full(n, np.nan)
    pending_val = np.full(n, np.nan)
    trend_up = False

    for i in range(n):
        if not np.isfinite(ma[i]) or not np.isfinite(roll_low[i]):
            trend_up = False
            continue
        pending_low[i] = roll_low[i]
        pending_high[i] = roll_high[i]

        # Trendwechsel mit Hysterese.
        if trend_up:
            if ma[i] < pending_high[i] * (1.0 - move_pct / 100.0):
                trend_up = False
                is_down[i] = True
            else:
                is_up[i] = True
        else:
            if ma[i] > pending_low[i] * (1.0 + move_pct / 100.0):
                trend_up = True
                is_up[i] = True
            else:
                is_down[i] = False

        pending_val[i] = pending_high[i] if trend_up else pending_low[i]

    return pd.DataFrame({
        "is_trend_up": is_up,
        "is_trend_down": is_down,
        "pending_extreme": pending_val,
        "ma_value": ma,
    })


class SrvTrendHmaPivot(PluginFeature):
    """HMA/EHMA Peak-Toleranz & Pivot-Trendwechsel.

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) - keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_trend_hma_pivot"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Trend & Reversal/Hysteresis & Pivots",
            "display_name": "HMA Peak Pivot Service",
            "description": "Erkennt Trendwechsel auf geglaetteten EHMA/HMA-Linien unter Beruecksichtigung einer Prozent-Hysterese.",
            "author": "PyTrader AI",
            "tags": ["trend", "hma", "ehma", "pivot", "hysteresis"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) fuer "
                                "die Analytics-UI und ML-Pipelines. Haelt den "
                                "letzten extremen MA-Wert "
                                "(piv_pendingExtremeValue). Ein Trendwechsel "
                                "wird erst signalisiert, wenn der MA den "
                                "Extremwert um piv_maxHmaMovePct % durchbricht. "
                                "Verhindert Fehlsignale in Seitwaertsphasen. "
                                "Keine Chart-Visualisierung in Kapitel 17.02.",
            "condition_rules": [
                "HMA_Peak_Toleranz: TrendUp = MA > PendingLow * (1 + MovePct/100)",
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
        return list(_TREND_HMA_PIVOT_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Pivot-Modus",
            "piv_len": "Pivot-Lookback",
            "hma_type": "MA-Typ (EHMA/HMA)",
            "hma_smoothing": "Hauptperiode des MA",
            "piv_maxHmaMovePct": "Mindestabstand % vom Peak",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_TREND_HMA_PIVOT_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _TREND_HMA_PIVOT_SCHEMA.items()}

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): flache Kopie der Modul-Konstante
        `_TREND_HMA_PIVOT_OUTPUT_SCHEMA` (PineScript-Input-Zone, M1: kein
        geteiltes mutable Dict)."""
        return {k: dict(v) for k, v in _TREND_HMA_PIVOT_OUTPUT_SCHEMA.items()}

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
        """Berechnet HMA/EHMA-Peak-Toleranz-Trendwechsel.

        Datenvertrag (17.02 §3): 1 Record pro Bar (dichte Label-Reihe).
        Trend-Bars tragen is_trend_up/is_trend_down=True sowie kausale
        Zeitstempel (event/confirmation_bar_time, confirmation_lag_bars=0).
        Bars am Serienanfang ohne MA-Warmup erhalten
        calculation_status='INSUFFICIENT_DATA'.

        Modi (params['mode']):
          * HMA_Peak_Toleranz: Hysterese gegen letztes MA-Extremum
            (piv_maxHmaMovePct % Durchbruch => Trendwechsel).
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
        mode = str(p.get("mode") or "HMA_Peak_Toleranz")
        piv_len = int(p.get("piv_len") or 4)
        hma_type = str(p.get("hma_type") or "EHMA")
        hma_smoothing = int(p.get("hma_smoothing") or 10)
        move_pct = float(p.get("piv_maxHmaMovePct") or 0.2)

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)

        is_trend_up = np.zeros(n, dtype=bool)
        is_trend_down = np.zeros(n, dtype=bool)
        status = np.full(n, "OK", dtype=object)
        strength = np.zeros(n, dtype=float)
        strength_type = "PERCENT"
        conf_type = "BAR_CLOSE"
        extra: Dict[str, np.ndarray] = {}

        if mode == "HMA_Peak_Toleranz":
            ma = _ma_series(work, hma_type, hma_smoothing).to_numpy(dtype=float)
            res = _hma_peak_toleranz(ma, piv_len, move_pct)
            is_trend_up = res["is_trend_up"].to_numpy(dtype=bool)
            is_trend_down = res["is_trend_down"].to_numpy(dtype=bool)
            pending = res["pending_extreme"].to_numpy(dtype=float)
            ma_nan = ~np.isfinite(ma)
            status[ma_nan] = "INSUFFICIENT_DATA"
            # Staerke: Prozent-Distanz vom Pending-Extremwert.
            with np.errstate(divide="ignore", invalid="ignore"):
                pct = np.where(
                    (np.isfinite(pending)) & (pending != 0),
                    np.abs(close - pending) / np.abs(pending) * 100.0,
                    0.0)
            strength = np.where(np.isfinite(pct), pct, 0.0)
            extra["ma_value"] = np.where(np.isfinite(ma), ma, np.nan)
            extra["pending_extreme_value"] = np.where(
                np.isfinite(pending), pending, np.nan)

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
                "result_type": "REVERSAL" if (is_trend_up[i] or is_trend_down[i])
                else "TREND",
                "source_mode": mode,
                "calculation_status": str(status[i]),
                "is_trend_up": bool(is_trend_up[i]),
                "is_trend_down": bool(is_trend_down[i]),
                "is_reversal_up": bool(is_trend_up[i] and not is_trend_down[i]),
                "is_reversal_down": bool(is_trend_down[i] and not is_trend_up[i]),
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
