# analytics/features/definitions/srv_swing_structure.py
# ==============================================================================
# DEFINITION: srv_swing_structure
# ==============================================================================
# NAME:        Swing Structure Service
# KATEGORIE:   Swing Points/Geometrie
# BESCHREIBUNG: Extrahierte Swing Highs/Lows über Fraktale, Pivots, Gann & ZigZag
# ==============================================================================
"""
Service: SwingStructure (Phase 17.01) – Naming Convention 16.08.01: srv_

Erfasst lokale Extrema ueber Fraktale, Pivots, Gann Swings, Period Extrema
(PDH/PWH) und ZigZag. Reiner Datenlieferant fuer die Analytics-UI und
spaetere ML-Pipelines (XGBoost/LightGBM) – KEINE Chart-Visualisierung in
diesem Kapitel (17.01, §1); dedizierte Chart-Indikatoren (ind_...) folgen
erst nach statistischer Validierung der erzeugten Features.

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt (Epoch) des tatsaechlichen Extremums.
  * confirmation_bar_time: Zeitpunkt, an dem das Signal mathematisch/kausal
                           feststand (bar_time der aktuellen Kerze).
  * confirmation_lag_bars: dynamisch berechnete Differenz in Bars
                           (params['right_bars'] bzw. Modus-Verzoegerung).
  * Kerzen am Serienanfang ohne ausreichenden Lookback/Lookahead erhalten
    calculation_status = 'INSUFFICIENT_DATA' und is_swing_* = False.

Persistenz: feature_store_payload mit feature_id='srv_swing_structure'
(Datenvertrag 17.01 §4). Seit 17.01 (E-1, PK-Migration) koennen mehrere
Services konfliktfrei auf derselben Kerze gespeichert werden
(PK (symbol, timeframe, bar_time, feature_id)).

Capabilities (E-5, 07.08.2026): chart=False (kein Indikator in diesem
Kapitel), batch=True, live=False, feature_store=True, render=False.
metadata['category'] = 'Swing Points/Geometrie' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_SWING_STRUCTURE_SCHEMA` direkt unter diesem Header
(siehe dort) und sind wie in PineScript am Dateianfang anpassbar.
`parameter_schema` gibt eine flache Kopie zurueck (M1: kein geteiltes
mutable Dict ueber Instanzen).
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

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
# E-2 (07.08.2026): type-Werte als Strings ("int"/"float"/"str") – die
# Basisklasse (base_plugin.validate_params) vergleicht string-basiert.
# ---------------------------------------------------------------------------
_SWING_STRUCTURE_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "Williams_Fractal",
        "options": [
            "Williams_Fractal", "Standard_Pivot", "Gann_Mechanical",
            "ZigZag_ATR", "ZigZag_Pct", "Period_Extrema",
        ],
        "description": "Erkennungs-Modus für Strukturswings",
    },
    "left_bars": {
        "type": "int", "default": 2, "min": 1,
        "description": "Anzahl erforderlicher Kerzen links mit niedrigeren Hochs / höheren Tiefs",
        "visible_when": {"mode": ["Williams_Fractal", "Standard_Pivot", "Gann_Mechanical"]},
    },
    "right_bars": {
        "type": "int", "default": 2, "min": 1,
        "description": "Anzahl Bestätigungskerzen rechts (bestimmt dynamisch confirmation_lag_bars)",
        "visible_when": {"mode": ["Williams_Fractal", "Standard_Pivot", "Gann_Mechanical"]},
    },
    "atr_period": {
        "type": "int", "default": 14, "min": 1,
        "description": "ATR-Periode für ZigZag_ATR",
        "visible_when": {"mode": "ZigZag_ATR"},
    },
    "atr_mult": {
        "type": "float", "default": 2.0, "min": 0.1,
        "description": "ATR-Multiplikator für ZigZag_ATR",
        "visible_when": {"mode": "ZigZag_ATR"},
    },
    "change_pct": {
        "type": "float", "default": 0.5, "min": 0.05,
        "description": "Mindestprozentbewegung für ZigZag_Pct",
        "visible_when": {"mode": "ZigZag_Pct"},
    },
    "period_extrema_type": {
        "type": "str",
        "default": "PREVIOUS_CLOSED",
        "options": ["PREVIOUS_CLOSED", "CURRENT_DEVELOPING"],
        "description": "PREVIOUS_CLOSED (z. B. PDH/PWH final) oder CURRENT_DEVELOPING",
        "visible_when": {"mode": "Period_Extrema"},
    },
}


# ---------------------------------------------------------------------------
# Modul-Helfer (17.01.02: echte Swing-Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-ATR (EMA-alpha 1/period, adjust=False) ueber OHLCV.

    Liefert NaN fuer Bars ohne ausreichende Historie (min_periods=period) –
    diese Bars werden als INSUFFICIENT_DATA markiert (ZigZag_ATR).
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


def _detect_fractal(df: pd.DataFrame, left: int, right: int,
                    ) -> Tuple[np.ndarray, np.ndarray]:
    """Williams-Fraktal / Standard-Pivot: lokale Extrema mit links/rechts
    tieferen Hochs bzw. hoeheren Tiefs (kausale Bestaetigung nach `right`
    Bars). Liefert (is_swing_high, is_swing_low) als bool-Arrays."""
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        if hi[i] > hi[i - left:i].max() and hi[i] > hi[i + 1:i + right + 1].max():
            is_high[i] = True
        if lo[i] < lo[i - left:i].min() and lo[i] < lo[i + 1:i + right + 1].min():
            is_low[i] = True
    return is_high, is_low


def _detect_gann(df: pd.DataFrame, left: int, right: int,
                 ) -> Tuple[np.ndarray, np.ndarray]:
    """Gann_Mechanical: mechanische Swing-Bestaetigung – das Extremum ist
    zugleich Fenster-Extremum UND der Schlusskurs `right` Bars spaeter liegt
    gegen die Extremum-Richtung (Reversal bestaetigt)."""
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        if (hi[i] >= hi[i - left:i + right + 1].max()
                and close[i + right] < hi[i]):
            is_high[i] = True
        if (lo[i] <= lo[i - left:i + right + 1].min()
                and close[i + right] > lo[i]):
            is_low[i] = True
    return is_high, is_low


def _detect_zigzag(df: pd.DataFrame, threshold_for: Callable[[int, float], Optional[float]],
                   ) -> Tuple[np.ndarray, np.ndarray, Dict[int, Tuple[int, str, float]]]:
    """Klassischer ZigZag (alternierende Swings).

    `threshold_for(i, ext_price)` liefert die aktuelle Umkehr-Schwelle
    (oder None, wenn keine Umkehr moeglich ist – z.B. ATR noch NaN).
    Rueckgabe: (is_swing_high, is_swing_low, pivot_info) – pivot_info
    {ext_idx: (conf_idx, 'high'|'low', move_amount)} fuer die kausale
    Bestaetigung (confirmation_bar_time = times[conf_idx]).
    """
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    pivot_info: Dict[int, Tuple[int, str, float]] = {}
    if n < 2:
        return is_high, is_low, pivot_info
    direction = 1  # 1 = aufsteigend (Swing-Highs), -1 = absteigend (Swing-Lows)
    ext_idx = 0
    ext_price = hi[0]
    for i in range(1, n):
        if direction == 1:
            if hi[i] > ext_price:
                ext_idx, ext_price = i, hi[i]
            else:
                th = threshold_for(i, ext_price)
                if th is not None and (ext_price - lo[i]) >= th:
                    is_high[ext_idx] = True
                    pivot_info[ext_idx] = (i, "high", ext_price - lo[i])
                    direction = -1
                    ext_idx, ext_price = i, lo[i]
        else:
            if lo[i] < ext_price:
                ext_idx, ext_price = i, lo[i]
            else:
                th = threshold_for(i, ext_price)
                if th is not None and (hi[i] - ext_price) >= th:
                    is_low[ext_idx] = True
                    pivot_info[ext_idx] = (i, "low", hi[i] - ext_price)
                    direction = 1
                    ext_idx, ext_price = i, hi[i]
    return is_high, is_low, pivot_info


def _detect_period_extrema(df: pd.DataFrame, extrema_type: str,
                           ) -> Tuple[np.ndarray, np.ndarray, Dict[int, Tuple[int, int, int, float, float]]]:
    """Period-Extrema (PDH/PWH).

    * CURRENT_DEVELOPING: Flag an jeder Bar, die ein NEUES laufendes
      Tages-Hoch/Tief setzt (event == confirmation, lag 0, CAUSAL).
    * PREVIOUS_CLOSED: Flag an jeder Bar, die das Hoch/Tief der VORHERIGEN
      (abgeschlossenen) Periode beruehrt (event = Vortages-Extremum-Bar,
      confirmation = die beruehrende Bar selbst, SESSION_CLOSE).
    Rueckgabe: (is_swing_high, is_swing_low, ext_info) – ext_info
    {bar_idx: (event_idx, conf_idx, lag, price_high, price_low)} fuer die
    kausale Bestaetigung der geflaggten Bars.
    """
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    times = df["time"].to_numpy(dtype=np.int64)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    ext_info: Dict[int, Tuple[int, int, int, float, float]] = {}
    if n == 0:
        return is_high, is_low, ext_info
    # pd.to_datetime(...) liefert einen DatetimeIndex (kein Series) -> .dt
    # existiert dort nicht; der Zugriff erfolgt ueber .date (ndarray aus
    # datetime.date-Objekten, 17.01.02 Bugfix).
    days = pd.to_datetime(times, unit="s", utc=True).date
    day_str = [str(d) for d in days]

    if extrema_type == "CURRENT_DEVELOPING":
        cur_day: Optional[str] = None
        day_high = -np.inf
        day_low = np.inf
        for i in range(n):
            d = day_str[i]
            if d != cur_day:
                cur_day, day_high, day_low = d, -np.inf, np.inf
            if hi[i] > day_high:
                day_high = hi[i]
                is_high[i] = True
                ext_info[i] = (i, i, 0, hi[i], 0.0)
            if lo[i] < day_low:
                day_low = lo[i]
                is_low[i] = True
                ext_info[i] = (i, i, 0, hi[i], lo[i])
        return is_high, is_low, ext_info

    # PREVIOUS_CLOSED: Tages-Extrema (Preis + Index + letzte Bar) sammeln
    day_hl: Dict[str, Dict[str, Any]] = {}
    for i in range(n):
        d = day_str[i]
        entry = day_hl.setdefault(d, {
            "high": -np.inf, "low": np.inf,
            "high_idx": i, "low_idx": i, "last_idx": i,
        })
        if hi[i] > entry["high"]:
            entry["high"], entry["high_idx"] = hi[i], i
        if lo[i] < entry["low"]:
            entry["low"], entry["low_idx"] = lo[i], i
        entry["last_idx"] = i
    day_order = list(day_hl.keys())
    for k in range(1, len(day_order)):
        prev = day_hl[day_order[k - 1]]
        cur_d = day_order[k]
        for i in range(n):
            if day_str[i] != cur_d:
                continue
            if hi[i] >= prev["high"]:
                is_high[i] = True
                # event = Vortages-Extremum-Bar, confirmation = beruehrende Bar
                ext_info[i] = (prev["high_idx"], i, i - prev["high_idx"],
                               prev["high"], prev["low"])
            if lo[i] <= prev["low"]:
                is_low[i] = True
                ext_info[i] = (prev["low_idx"], i, i - prev["low_idx"],
                               prev["high"], prev["low"])
    return is_high, is_low, ext_info


class SrvSwingStructure(PluginFeature):
    """Geometrische & Preis-Swings (Fraktale, Pivots, Gann, ZigZag).

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) – keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_swing_structure"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Swing Points/Geometrie",
            "display_name": "Swing Structure Service",
            "description": "Erfasst Fraktal-, Pivot-, Gann- und ZigZag-Extrema für die Struktur-Analyse",
            "author": "PyTrader AI",
            "tags": ["swing", "fractal", "pivot", "zigzag", "structure"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) für "
                                "die Analytics-UI und ML-Pipelines. Erkennt "
                                "lokale Extrema über Williams-Fraktale, "
                                "Standard-Pivots, Gann-Mechanik, ZigZag "
                                "(ATR/Prozent) und Period-Extrema (PDH/PWH). "
                                "Keine Chart-Visualisierung in Kapitel 17.01.",
            "condition_rules": [
                "Williams_Fractal: high[i] > high[i±k] / low[i] < low[i±k] für k in 1..left/right_bars",
                "Standard_Pivot: lokales Extremum mit links/rechts tieferen Hochs bzw. höheren Tiefs",
                "Gann_Mechanical: mechanische Swing-Bestätigung über links/rechts-Zählung",
                "ZigZag_ATR: Richtungswechsel erst bei |move| >= atr_mult × ATR(atr_period)",
                "ZigZag_Pct: Richtungswechsel erst bei |move| >= change_pct %",
                "Period_Extrema: PDH/PWH (PREVIOUS_CLOSED) bzw. laufende Periode (CURRENT_DEVELOPING)",
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
        return list(_SWING_STRUCTURE_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Erkennungs-Modus",
            "left_bars": "Kerzen links",
            "right_bars": "Kerzen rechts (Bestätigung)",
            "atr_period": "ATR-Periode (ZigZag_ATR)",
            "atr_mult": "ATR-Multiplikator (ZigZag_ATR)",
            "change_pct": "Mindestbewegung % (ZigZag_Pct)",
            "period_extrema_type": "Period-Extrema-Typ",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_SWING_STRUCTURE_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _SWING_STRUCTURE_SCHEMA.items()}

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
        """Berechnet Struktur-Swings (Fraktale/Pivots/Gann/ZigZag/Period).

        17.01.02 (Bugfix-Runde): Die echte Swing-Erkennung ersetzt den
        Scaffold (vorher records=[], daher '0 Feature-Row(s)' im Store).

        Datenvertrag (17.01 §4): JEDER Bar entspricht genau EIN Record
        (dichte Label-Reihe fuer ML/Analytics). Swing-Bars tragen
        is_swing_high/is_swing_low=True sowie kausale Zeitstempel
        (event/confirmation_bar_time, confirmation_lag_bars). Bars am
        Serienanfang ohne ausreichenden Lookback/Lookahead erhalten
        calculation_status='INSUFFICIENT_DATA' (is_swing_* = False).

        Modi (params['mode']):
          * Williams_Fractal: lokale Extrema mit links/rechts tieferen Hochs
            bzw. hoeheren Tiefs (left/right_bars), Bestaetigung nach right_bars.
          * Standard_Pivot: identische Extremum-Logik (Pivot = Fraktal mit
            konfigurierbaren Fenstern).
          * Gann_Mechanical: Fenster-Extremum + Schlusskurs-Reversal
            (`right` Bars spaeter) gegen die Extremum-Richtung.
          * ZigZag_ATR: Richtungswechsel erst bei |move| >= atr_mult × ATR.
          * ZigZag_Pct: Richtungswechsel erst bei |move| >= change_pct %.
          * Period_Extrema: PDH/PWH (PREVIOUS_CLOSED = Vortages-Level-Touch)
            bzw. laufende Periode (CURRENT_DEVELOPING = neue Tages-Extrema).
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
        mode = str(p.get("mode") or "Williams_Fractal")
        left = int(p.get("left_bars") or 2)
        right = int(p.get("right_bars") or 2)
        atr_period = int(p.get("atr_period") or 14)
        atr_mult = float(p.get("atr_mult") or 2.0)
        change_pct = float(p.get("change_pct") or 0.5)
        extrema_type = str(p.get("period_extrema_type") or "PREVIOUS_CLOSED")

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)
        atr = _atr_series(work, atr_period).to_numpy(dtype=float)

        is_high = np.zeros(n, dtype=bool)
        is_low = np.zeros(n, dtype=bool)
        # Kausale Bestaetigung je Swing-Bar: {idx: (event_idx, conf_idx,
        # lag, price)} – event = tatsaechliches Extremum, conf = kausale
        # Feststellung (fuer PREVIOUS_CLOSED liegt event VOR der Flag-Bar).
        swing_meta: Dict[int, Tuple[int, int, int, float]] = {}
        status = np.full(n, "OK", dtype=object)
        strength = np.zeros(n, dtype=float)
        strength_type = "NORMALIZED"
        conf_type = "PIVOT"

        if mode in ("Williams_Fractal", "Standard_Pivot"):
            is_high, is_low = _detect_fractal(work, left, right)
            status[:left] = "INSUFFICIENT_DATA"
            status[n - right:] = "INSUFFICIENT_DATA"
            conf_type = "FRACTAL" if mode == "Williams_Fractal" else "PIVOT"
            for i in range(n):
                if not (is_high[i] or is_low[i]):
                    continue
                conf = min(i + right, n - 1)
                price = float(work["high"].iloc[i] if is_high[i]
                              else work["low"].iloc[i])
                swing_meta[i] = (i, conf, right, price)
                if np.isfinite(atr[i]) and atr[i] > 0:
                    strength[i] = abs(
                        price - (float(work["low"].iloc[i])
                                 if is_high[i] else float(work["high"].iloc[i]))
                    ) / atr[i]
                    strength_type = "ATR_MULTIPLE"

        elif mode == "Gann_Mechanical":
            is_high, is_low = _detect_gann(work, left, right)
            status[:left] = "INSUFFICIENT_DATA"
            status[n - right:] = "INSUFFICIENT_DATA"
            conf_type = "PIVOT"
            for i in range(n):
                if not (is_high[i] or is_low[i]):
                    continue
                conf = min(i + right, n - 1)
                price = float(work["high"].iloc[i] if is_high[i]
                              else work["low"].iloc[i])
                swing_meta[i] = (i, conf, right, price)
                if np.isfinite(atr[i]) and atr[i] > 0:
                    strength[i] = abs(
                        price - (float(work["low"].iloc[i])
                                 if is_high[i] else float(work["high"].iloc[i]))
                    ) / atr[i]
                    strength_type = "ATR_MULTIPLE"

        elif mode == "ZigZag_ATR":
            def _thr_atr(i: int, _ext_price: float) -> Optional[float]:
                if not np.isfinite(atr[i]):
                    return None
                return atr_mult * atr[i]

            is_high, is_low, pivot_info = _detect_zigzag(work, _thr_atr)
            status[~np.isfinite(atr)] = "INSUFFICIENT_DATA"
            conf_type = "CAUSAL"
            strength_type = "ATR_MULTIPLE"
            for idx, (conf_idx, kind, move) in pivot_info.items():
                price = float(work["high"].iloc[idx] if kind == "high"
                              else work["low"].iloc[idx])
                swing_meta[idx] = (idx, conf_idx, conf_idx - idx, price)
                strength[idx] = move / atr[idx] if np.isfinite(atr[idx]) and atr[idx] > 0 else 0.0

        elif mode == "ZigZag_Pct":
            def _thr_pct(_i: int, ext_price: float) -> Optional[float]:
                return abs(ext_price) * change_pct / 100.0

            is_high, is_low, pivot_info = _detect_zigzag(work, _thr_pct)
            conf_type = "CAUSAL"
            strength_type = "PERCENT"
            for idx, (conf_idx, kind, move) in pivot_info.items():
                price = float(work["high"].iloc[idx] if kind == "high"
                              else work["low"].iloc[idx])
                swing_meta[idx] = (idx, conf_idx, conf_idx - idx, price)
                strength[idx] = (move / price * 100.0) if price else 0.0

        elif mode == "Period_Extrema":
            is_high, is_low, ext_info = _detect_period_extrema(work, extrema_type)
            status[0] = "INSUFFICIENT_DATA"  # erste Bar ohne Vortag/Historie
            conf_type = "CAUSAL" if extrema_type == "CURRENT_DEVELOPING" \
                else "SESSION_CLOSE"
            strength_type = "PRICE_DISTANCE"
            for idx, (event_idx, conf_idx, lag, price_high, price_low) in ext_info.items():
                price = float(price_high if is_high[idx] else price_low)
                swing_meta[idx] = (event_idx, conf_idx, lag, price)
                strength[idx] = abs(
                    float(work["high"].iloc[idx] if is_high[idx]
                          else work["low"].iloc[idx]) - price)

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
            event_idx, conf_idx, lag, price = swing_meta.get(i, (i, i, 0, 0.0))
            event_idx = min(max(event_idx, 0), n - 1)
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
                "event_bar_time": int(times[event_idx]),
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
