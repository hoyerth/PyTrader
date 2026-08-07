# analytics/features/definitions/srv_swing_momentum.py
# ==============================================================================
# DEFINITION: srv_swing_momentum
# ==============================================================================
# NAME:        Swing Momentum Service
# KATEGORIE:   Swing Points/Dynamik & Filter
# BESCHREIBUNG: Wendepunkts-Erkennung über MA-Hysteresen, Steigungswechsel & Chande-Kroll
# ==============================================================================
"""
Service: SwingMomentum (Phase 17.01) – Naming Convention 16.08.01: srv_

Erfasst Richtungswechsel ueber Glättungs-Hysteresen (alle 12 MA-Typen des
MA-Templates 16.04), Steigungswechsel und Trailing-Stops (Chande Kroll).
Reiner Datenlieferant fuer die Analytics-UI und spaetere ML-Pipelines –
KEINE Chart-Visualisierung in diesem Kapitel (17.01, §1).

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt des tatsaechlichen Extremums.
  * confirmation_bar_time: Zeitpunkt, an dem das Signal kausal feststand
                           (bar_time der aktuellen Kerze).
  * confirmation_lag_bars: dynamische Differenz in Bars
                           (params['period'] bzw. Modus-Verzoegerung).
  * Kerzen am Serienanfang ohne ausreichenden Lookback/Lookahead erhalten
    calculation_status = 'INSUFFICIENT_DATA' und is_swing_* = False.

Persistenz: feature_store_payload mit feature_id='srv_swing_momentum'
(Datenvertrag 17.01 §4). Seit 17.01 (E-1, PK-Migration) koennen mehrere
Services konfliktfrei auf derselben Kerze gespeichert werden.

Capabilities (E-5, 07.08.2026): chart=False, batch=True, live=False,
feature_store=True, render=False.
metadata['category'] = 'Swing Points/Dynamik & Filter' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_SWING_MOMENTUM_SCHEMA` direkt unter diesem Header.
`parameter_schema` gibt eine flache Kopie zurueck (M1).
E-2 (07.08.2026): type-Werte als Strings.
"""

from typing import Any, Dict, List, Optional, Tuple

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
# `parameter_schema` gibt eine flache Kopie zurueck (M1).
# E-2 (07.08.2026): type-Werte als Strings.
# ---------------------------------------------------------------------------
_SWING_MOMENTUM_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "MA_Peak_Hysteresis",
        "options": [
            "MA_Peak_Hysteresis", "MA_Slope_Change", "Chande_Kroll_Ratchet",
        ],
        "description": "Algorithmus-Modus für Momentum-Swings",
    },
    "ma_type": {
        "type": "str",
        "default": "EHMA",
        "options": [
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA",
        ],
        "description": "Gleitender Durchschnittstyp (MA-Template 16.04)",
        "visible_when": {"mode": ["MA_Peak_Hysteresis", "MA_Slope_Change"]},
    },
    "period": {
        "type": "int", "default": 14, "min": 2,
        "description": "Berechnungsperiode für Glättungs-MA",
        "visible_when": {"mode": ["MA_Peak_Hysteresis", "MA_Slope_Change"]},
    },
    "piv_maxMaMovePct": {
        "type": "float", "default": 0.2, "min": 0.01,
        "description": "Erforderliche Gegenbewegung in % für MA Peak Pivot (gültig für alle ma_type-Optionen)",
        "visible_when": {"mode": "MA_Peak_Hysteresis"},
    },
    "chande_lookback": {
        "type": "int", "default": 10, "min": 1,
        "description": "Lookback-Periode für Highest-High/Lowest-Low im Chande_Kroll_Ratchet Modus",
        "visible_when": {"mode": "Chande_Kroll_Ratchet"},
    },
    "x_atr": {
        "type": "float", "default": 3.0, "min": 0.5,
        "description": "ATR-Multiplikator für Chande Kroll Stops",
        "visible_when": {"mode": "Chande_Kroll_Ratchet"},
    },
}


# ---------------------------------------------------------------------------
# Modul-Helfer (17.01.02: echte Swing-Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-ATR (EMA-alpha 1/period, adjust=False) ueber OHLCV.

    Liefert NaN fuer Bars ohne ausreichende Historie (min_periods=period) –
    diese Bars werden als INSUFFICIENT_DATA markiert (Chande_Kroll_Ratchet).
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / max(1, period), min_periods=max(1, period),
                  adjust=False).mean()


def _detect_ma_hysteresis(ma: np.ndarray,
                          change_pct: float,
                          ) -> Tuple[np.ndarray, np.ndarray,
                                     Dict[int, Tuple[int, str, float]]]:
    """MA-Peak-Hysterese: alternierend wird ein laufendes MA-Extremum
    mitgefuehrt; erst wenn sich das MA um >= `change_pct` % gegen das
    Extremum bewegt, ist der Pivot bestaetigt (kausal am aktuellen Bar).

    Rueckgabe: (is_swing_high, is_swing_low, pivot_info) –
    pivot_info {ext_idx: (conf_idx, 'high'|'low', move_pct)}.
    """
    n = len(ma)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    pivot_info: Dict[int, Tuple[int, str, float]] = {}
    if n < 2:
        return is_high, is_low, pivot_info
    direction = 1  # 1 = auf der Jagd nach Swing-High, -1 = Swing-Low
    ext_idx = -1
    ext_price = np.nan
    for i in range(1, n):
        cur = float(ma[i])
        if not np.isfinite(cur):
            continue
        # Warmup-NaN (MA-Typen ohne Fruehwert) ueberspringen: erstes finites
        # MA-Extremum als Startpunkt setzen (17.01.02 Bugfix – sonst bleibt
        # der Zustand dauerhaft auf NaN haengen -> 0 Swings).
        if not np.isfinite(ext_price):
            ext_idx, ext_price = i, cur
            continue
        if direction == 1:
            if cur > ext_price:
                ext_idx, ext_price = i, cur
            elif abs(ext_price) > 0.0 and (ext_price - cur) / abs(ext_price) * 100.0 >= change_pct:
                is_high[ext_idx] = True
                pivot_info[ext_idx] = (i, "high",
                                       (ext_price - cur) / abs(ext_price) * 100.0)
                direction = -1
                ext_idx, ext_price = i, cur
        else:
            if cur < ext_price:
                ext_idx, ext_price = i, cur
            elif abs(ext_price) > 0.0 and (cur - ext_price) / abs(ext_price) * 100.0 >= change_pct:
                is_low[ext_idx] = True
                pivot_info[ext_idx] = (i, "low",
                                       (cur - ext_price) / abs(ext_price) * 100.0)
                direction = 1
                ext_idx, ext_price = i, cur
    return is_high, is_low, pivot_info


def _detect_ma_slope(ma: np.ndarray,
                     ) -> Tuple[np.ndarray, np.ndarray,
                                Dict[int, Tuple[int, str, float]]]:
    """MA-Steigungswechsel: Swing-High, wenn die MA-Steigung von positiv auf
    <= 0 dreht (MA-Peak), Swing-Low beim Uebergang von negativ auf >= 0.
    Event = letzte Bar des alten Vorzeichens (Peak/Tief), Confirmation =
    aktuelle Bar (kausal)."""
    n = len(ma)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    pivot_info: Dict[int, Tuple[int, str, float]] = {}
    if n < 3:
        return is_high, is_low, pivot_info
    slope = np.diff(ma)
    for i in range(1, n):
        if not np.isfinite(ma[i]) or not np.isfinite(ma[i - 1]):
            continue
        if i - 1 >= 1 and np.isfinite(slope[i - 2]):
            if slope[i - 2] > 0 and slope[i - 1] <= 0:
                is_high[i - 1] = True
                pivot_info[i - 1] = (i, "high", float(slope[i - 1]))
            elif slope[i - 2] < 0 and slope[i - 1] >= 0:
                is_low[i - 1] = True
                pivot_info[i - 1] = (i, "low", abs(float(slope[i - 1])))
    return is_high, is_low, pivot_info


def _detect_chande_kroll(df: pd.DataFrame, lookback: int, x_atr: float,
                         atr: np.ndarray,
                         ) -> Tuple[np.ndarray, np.ndarray,
                                    Dict[int, Tuple[int, str, float]]]:
    """Chande-Kroll-Ratchet: Trailing-Stop = Highest-High/Lowest-Low ueber
    `lookback` ± x_atr × ATR. Verlassen des Stopps durch den Schlusskurs
    bestaetigt das vorherige Extremum (kausal am aktuellen Bar)."""
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    pivot_info: Dict[int, Tuple[int, str, float]] = {}
    if n < 2:
        return is_high, is_low, pivot_info
    s_hi = pd.Series(hi).rolling(lookback, min_periods=1).max().to_numpy()
    s_lo = pd.Series(lo).rolling(lookback, min_periods=1).min().to_numpy()
    direction = 1  # 1 = Aufwaerts-Ratchet (Swing-Highs), -1 = Abwaerts
    for i in range(1, n):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        if direction == 1:
            stop = s_hi[i] - x_atr * a
            if close[i] < stop:
                j0 = max(0, i - lookback + 1)
                ext_idx = j0 + int(np.argmax(hi[j0:i + 1]))
                is_high[ext_idx] = True
                pivot_info[ext_idx] = (i, "high", s_hi[i] - stop)
                direction = -1
        else:
            stop = s_lo[i] + x_atr * a
            if close[i] > stop:
                j0 = max(0, i - lookback + 1)
                ext_idx = j0 + int(np.argmin(lo[j0:i + 1]))
                is_low[ext_idx] = True
                pivot_info[ext_idx] = (i, "low", stop - s_lo[i])
                direction = 1
    return is_high, is_low, pivot_info


class SrvSwingMomentum(PluginFeature):
    """Dynamik- & MA-Hysterese-Swings.

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) – keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_swing_momentum"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Swing Points/Dynamik & Filter",
            "display_name": "Swing Momentum Service",
            "description": "Dynamische Momentum-Swings via MA-Hysterese, Steigung & Chande Kroll",
            "author": "PyTrader AI",
            "tags": ["swing", "momentum", "ma", "hysteresis", "chande-kroll"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) für "
                                "die Analytics-UI und ML-Pipelines. Erkennt "
                                "Richtungswechsel über MA-Peak-Hysterese (alle "
                                "12 MA-Typen des Templates 16.04), "
                                "MA-Steigungswechsel und Chande-Kroll-Ratchet "
                                "(ATR-Stopps). Keine Chart-Visualisierung in "
                                "Kapitel 17.01.",
            "condition_rules": [
                "MA_Peak_Hysteresis: Pivot erst bei Gegenbewegung >= piv_maxMaMovePct %",
                "MA_Slope_Change: Richtungswechsel der MA-Steigung (Vorzeichen des Differentials)",
                "Chande_Kroll_Ratchet: Stopps = Highest-High/Lowest-Low über chande_lookback ± x_atr × ATR",
                "alle 12 MA-Typen: SMA/EMA/WMA/DEMA/TEMA/HMA/EHMA/ZLEMA/RMA/KAMA/ALMA/VWMA",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": False,   # E-5: kein Indikator in Kapitel 17.01
            "batch": True,
            "live": False,
            "feature_store": True,
            "render": False,  # E-5: reine Datenlieferanten
        }

    # --- Single Source of Truth fürs Prop-Fenster (17.01 §2.2, PineScript-Zone)
    @property
    def parameter_order(self) -> List[str]:
        return list(_SWING_MOMENTUM_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Algorithmus-Modus",
            "ma_type": "Gleitender Durchschnittstyp",
            "period": "Berechnungsperiode",
            "piv_maxMaMovePct": "Gegenbewegung % (MA Peak Pivot)",
            "chande_lookback": "Lookback (Chande Kroll)",
            "x_atr": "ATR-Multiplikator (Chande Kroll Stops)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_SWING_MOMENTUM_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _SWING_MOMENTUM_SCHEMA.items()}

    # 2. SCHEMA-EXPOSURE FÜR DIE UI (07.08.2026, Bugfix): Die Spalten-UI
    # (serviceui/param_columns.py & ServiceSelectorWidget) liest Parameter-
    # Definitionen über `default_params` / `full_parameter_schema()`. Diese
    # expliziten Overrides stellen das Schema unabhängig von der jeweiligen
    # parameter_schema-Definition (Property/Klassen-Attribut) bereit und
    # erhalten den Basisklassen-Vertrag (Basis-Parameter wie lookback + 
    # plugin-spezifische Parameter, vgl. base_plugin.PluginFeature).
    @property
    def default_params(self) -> Dict[str, Any]:
        """Extrahiert die Default-Werte aus dem parameter_schema für die Engine."""
        return {k: v.get("default") for k, v in self.parameter_schema.items()
                if "default" in v}

    def full_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Liefert das vollständige Schema (Basis + plugin-spezifisch) inkl.
        Min/Max/Typ für die UI-Spalten (Basisklassen-Vertrag)."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Momentum-Swings (MA-Hysterese, Steigung, Chande Kroll).

        17.01.02 (Bugfix-Runde): Echte Erkennung ersetzt den Scaffold
        (vorher records=[], daher '0 Feature-Row(s)' im Store + irrefuehrende
        Meldung 'Keine OHLCV-Daten' im ServiceRunWorker).

        Datenvertrag (17.01 §4): JEDER Bar entspricht genau EIN Record
        (dichte Label-Reihe). Swing-Bars tragen is_swing_high/is_swing_low
        sowie kausale Zeitstempel. Bars am Serienanfang ohne ausreichenden
        Lookback (MA-/ATR-Warmup) erhalten calculation_status=
        'INSUFFICIENT_DATA' (is_swing_* = False).

        Modi (params['mode']):
          * MA_Peak_Hysteresis: MA (alle 12 Typen, Template 16.04) – Pivot
            erst bei Gegenbewegung >= piv_maxMaMovePct % (strength PERCENT).
          * MA_Slope_Change: Vorzeichenwechsel der MA-Steigung (strength
            NORMALIZED, |Steigung|).
          * Chande_Kroll_Ratchet: Trailing-Stop = Highest-High/Lowest-Low
            ueber chande_lookback ± x_atr × ATR (strength ATR_MULTIPLE).
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
        mode = str(p.get("mode") or "MA_Peak_Hysteresis")
        ma_type = str(p.get("ma_type") or "EHMA")
        period = int(p.get("period") or 14)
        move_pct = float(p.get("piv_maxMaMovePct") or 0.2)
        chande_lookback = int(p.get("chande_lookback") or 10)
        x_atr = float(p.get("x_atr") or 3.0)

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)
        atr = _atr_series(work, period).to_numpy(dtype=float)

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

        is_high = np.zeros(n, dtype=bool)
        is_low = np.zeros(n, dtype=bool)
        # Kausale Bestaetigung je Swing-Bar: {idx: (conf_idx, lag, price)}
        swing_meta: Dict[int, Tuple[int, int, float]] = {}
        status = np.full(n, "OK", dtype=object)
        strength = np.zeros(n, dtype=float)
        strength_type = "NORMALIZED"
        conf_type = "CAUSAL"

        # MA-Warmup-Bars ohne Wert -> INSUFFICIENT_DATA.
        ma_nan = ~np.isfinite(ma)
        if ma_nan.any():
            status[ma_nan] = "INSUFFICIENT_DATA"

        if mode == "MA_Peak_Hysteresis":
            is_high, is_low, pivot_info = _detect_ma_hysteresis(ma, move_pct)
            strength_type = "PERCENT"
            for idx, (conf_idx, kind, move) in pivot_info.items():
                price = float(ma[idx])
                swing_meta[idx] = (conf_idx, conf_idx - idx, price)
                strength[idx] = move

        elif mode == "MA_Slope_Change":
            is_high, is_low, pivot_info = _detect_ma_slope(ma)
            for idx, (conf_idx, _kind, move) in pivot_info.items():
                price = float(ma[idx])
                swing_meta[idx] = (conf_idx, conf_idx - idx, price)
                strength[idx] = move

        elif mode == "Chande_Kroll_Ratchet":
            atr_nan = ~np.isfinite(atr)
            if atr_nan.any():
                status[atr_nan] = "INSUFFICIENT_DATA"
            is_high, is_low, pivot_info = _detect_chande_kroll(
                work, chande_lookback, x_atr, atr)
            strength_type = "ATR_MULTIPLE"
            for idx, (conf_idx, kind, move) in pivot_info.items():
                price = float(work["high"].iloc[idx] if kind == "high"
                              else work["low"].iloc[idx])
                swing_meta[idx] = (conf_idx, conf_idx - idx, price)
                strength[idx] = move / atr[idx] if np.isfinite(atr[idx]) and atr[idx] > 0 else 0.0

        else:
            # Unbekannter Modus: defensiv leer (kein Crash, 0 Rows).
            return empty

        # --- Records bauen (dicht: 1 Record pro Bar, 17.01 §4) ----------------
        records: List[Dict[str, Any]] = []
        total_high = int(is_high.sum())
        total_low = int(is_low.sum())
        for i in range(n):
            is_sh = bool(is_high[i])
            is_sl = bool(is_low[i])
            conf_idx, lag, price = swing_meta.get(i, (i, 0, 0.0))
            conf_idx = min(max(conf_idx, 0), n - 1)
            if not (is_sh or is_sl):
                price = float(close[i])
            records.append({
                "bar_time": int(times[i]),
                "result_type": "SWING",
                "source_mode": mode,
                "calculation_status": str(status[i]),
                "is_swing_high": is_sh,
                "is_swing_low": is_sl,
                "is_rejection": False,
                "event_bar_time": int(times[i]),
                "confirmation_bar_time": int(times[conf_idx]),
                "confirmation_lag_bars": int(lag),
                "confirmation_type": conf_type,
                "price": float(price),
                "strength_value": float(strength[i]),
                "strength_type": strength_type,
            })

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
                    "total_swing_highs": total_high,
                    "total_swing_lows": total_low,
                    "bars": n,
                },
            },
        }
