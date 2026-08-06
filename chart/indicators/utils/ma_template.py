# chart/indicators/utils/ma_template.py
"""
Phase 16.04 – Generisches MA-Template-Modul
============================================

Wiederverwendbare Moving-Average-Utility für Chart-Indikatoren.

WICHTIG (Entscheidungen 06.08.2026, Doku-Analyse 16.04):
  * KEIN Analytics-Plugin, KEINE Feature-Store-Schreibzugriffe – reine
    Utility-Klasse (P16.01-Philosophie: Darstellung additiv im Indikator).
  * MAType = TradingView-konformer 12er-Satz in exakter Reihenfolge
    (E2): SMA, EMA, WMA, DEMA, TEMA, HMA, EHMA, ZLEMA, RMA, KAMA, ALMA, VWMA.
  * Defaults (E3): ma_type="EHMA", period=4, alpha_factor=2.0,
    smooth_type="EHMA", dual_color=False, bull_color="#2196F3",
    bear_color="#EF5350".
  * Alpha-MAs (E4): DEMA, TEMA, EHMA verwenden den dynamischen Decay-Faktor
    alpha = alpha_factor / (period + 1).
  * VWMA (E5): ohne gültiges Volumen (fehlend/Null) Fallback auf SMA.
  * smooth_type (Ergänzung 1): reiner Schema-Vertrag für spätere
    MA-Indikatoren – wird von der Engine hier NICHT konsumiert
    (Forward-Compatibility). EHMA = EMA_alpha(HMA(src, len), len).
  * bull_color-Default bedingt (E7/Ergänzung 2): Schema liefert "#2196F3";
    der Konsument wendet "#26A69A" an, wenn dual_color=True UND bull_color
    nicht vom User gesetzt wurde (leer/None).
  * NaN-Handling (Ergänzung 3): build_chart_payload überspringt Zeilen mit
    NaN/None in time oder value (Warmup period-1); Längen-Mismatch bei colors
    wird defensiv toleriert (Fallback = bull_color).

Alle 12 MA-Typen sind vektorisiert via NumPy/Pandas (numpy 2.5.1 /
pandas 3.0.5 in .venv). KAMA ist inhärent rekursiv (ER-basiert) und läuft
über eine kompakte Python-Schleife auf dem NumPy-Array; alle anderen Typen
über rolling/ewm/convolve.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Kerntypen & Konstanten
# ---------------------------------------------------------------------------

MAType = Literal[
    "SMA",
    "EMA",
    "WMA",
    "DEMA",
    "TEMA",
    "HMA",
    "EHMA",
    "ZLEMA",
    "RMA",
    "KAMA",
    "ALMA",
    "VWMA",
]

MA_TYPES: tuple = (
    "SMA",
    "EMA",
    "WMA",
    "DEMA",
    "TEMA",
    "HMA",
    "EHMA",
    "ZLEMA",
    "RMA",
    "KAMA",
    "ALMA",
    "VWMA",
)

# Standardfarben (E3/E7)
_DEFAULT_BULL_COLOR: str = "#2196F3"
_DEFAULT_BULL_COLOR_DUAL: str = "#26A69A"
_DEFAULT_BEAR_COLOR: str = "#EF5350"

# KAMA-Standardkonstanten (Ergänzung 4): period = ER-Periode; fast/slow
# fest nach Kaufman (2/3 bzw. 2/31).
_KAMA_FAST_ALPHA: float = 2.0 / (2.0 + 1.0)
_KAMA_SLOW_ALPHA: float = 2.0 / (30.0 + 1.0)

# ALMA-Defaults (Ergänzung 4, TradingView): Offset 0.85, Sigma = period/6.
_ALMA_OFFSET: float = 0.85


def resolve_bull_color(
    dual_color: bool,
    bull_color: Optional[str] = None,
    default: str = _DEFAULT_BULL_COLOR,
) -> str:
    """Ergänzung 2 (E7): Löst den bedingten bull_color-Default auf.

    Schema-Default ist "#2196F3". Bei dual_color=True UND nicht gesetztem
    (leer/None) User-Wert wird der dual-freundliche Default "#26A69A"
    angewendet. Leerstring/whitespace wird wie "nicht gesetzt" behandelt.
    """
    if bull_color is not None and str(bull_color).strip():
        return str(bull_color).strip()
    if dual_color:
        return _DEFAULT_BULL_COLOR_DUAL
    return default


# ---------------------------------------------------------------------------
# Vektorisierte Kern-Bausteine (NumPy)
# ---------------------------------------------------------------------------


def _sma_values(values: np.ndarray, period: int) -> np.ndarray:
    """SMA über rollierende Fenster (konstanter Gewichtsvektor)."""
    if period <= 1:
        return values.astype(float, copy=True)
    window = np.ones(period, dtype=float)
    conv = np.convolve(values, window, mode="valid") / float(period)
    result = np.full(len(values), np.nan, dtype=float)
    result[period - 1:] = conv
    return result


def _wma_values(values: np.ndarray, period: int) -> np.ndarray:
    """WMA (linear gewichtet, jüngster Wert = höchstes Gewicht) via Faltung.

    np.convolve wendet die Gewichte rückwärts an (v[0] trifft den ältesten
    Wert). Daher wird der Gewichtsvektor absteigend angelegt ([p, p-1, .., 1]),
    damit der jüngste Wert das höchste Gewicht p erhält. result[t] ist am
    Fensterende positioniert (Warmup = period-1 NaNs).
    """
    if period <= 1:
        return values.astype(float, copy=True)
    weights = np.arange(period, 0, -1, dtype=float)
    conv = np.convolve(values, weights, mode="valid") / weights.sum()
    result = np.full(len(values), np.nan, dtype=float)
    result[period - 1:] = conv
    return result


def _ema_alpha_values(values: np.ndarray, alpha: float) -> np.ndarray:
    """EMA mit explizitem Decay-Faktor alpha (E4).

    Nutzt pandas ewm(alpha=alpha, adjust=False) – vektorisiert und exakt.
    """
    return np.array(
        pd.Series(values).ewm(alpha=alpha, adjust=False).mean().to_numpy(),
        dtype=float,
        copy=True,
    )


def _ema_span_values(values: np.ndarray, period: int) -> np.ndarray:
    """Standard-EMA (span=period) für Nicht-Alpha-MAs (EMA, ZLEMA)."""
    return np.array(
        pd.Series(values).ewm(span=period, adjust=False).mean().to_numpy(),
        dtype=float,
        copy=True,
    )


def _rma_values(values: np.ndarray, period: int) -> np.ndarray:
    """RMA (Wilder): ewm(alpha=1/period, adjust=False) (Ergänzung 4)."""
    if period <= 1:
        return values.astype(float, copy=True)
    return np.array(
        pd.Series(values).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy(),
        dtype=float,
        copy=True,
    )


def _hma_values(values: np.ndarray, period: int) -> np.ndarray:
    """HMA (Hull): WMA(2*WMA(half) - WMA(len), sqrt(len)).

    sqrt(len) wird auf eine ungerade Ganzzahl gerundet (min 1).
    """
    if period <= 1:
        return values.astype(float, copy=True)
    half = max(period // 2, 1)
    sqrt_period = max(int(np.sqrt(period)), 1)
    if sqrt_period % 2 == 0:
        sqrt_period += 1
    inner = 2.0 * _wma_values(values, half) - _wma_values(values, period)
    return _wma_values(inner, sqrt_period)


def _dema_values(values: np.ndarray, period: int, alpha: float) -> np.ndarray:
    """DEMA: 2*EMA_alpha - EMA_alpha(EMA_alpha) (E4)."""
    ema1 = _ema_alpha_values(values, alpha)
    return 2.0 * ema1 - _ema_alpha_values(ema1, alpha)


def _tema_values(values: np.ndarray, period: int, alpha: float) -> np.ndarray:
    """TEMA: 3*E1 - 3*E2 + E3 (E4)."""
    ema1 = _ema_alpha_values(values, alpha)
    ema2 = _ema_alpha_values(ema1, alpha)
    ema3 = _ema_alpha_values(ema2, alpha)
    return 3.0 * ema1 - 3.0 * ema2 + ema3


def _ehma_values(values: np.ndarray, period: int, alpha: float) -> np.ndarray:
    """EHMA: EMA_alpha(HMA(src, len), len) (Ergänzung 1, E4)."""
    return _ema_alpha_values(_hma_values(values, period), alpha)


def _zlema_values(values: np.ndarray, period: int) -> np.ndarray:
    """ZLEMA: EMA(xt, len) mit xt = src + (src - src[lag]), lag=(len-1)/2."""
    if period <= 1:
        return values.astype(float, copy=True)
    lag = int((period - 1) / 2)
    if lag < 1:
        lag = 1
    shifted = np.empty_like(values, dtype=float)
    shifted[:lag] = np.nan
    shifted[lag:] = values[:-lag]
    xt = values + (values - shifted)
    result = _ema_span_values(xt, period)
    # Warmup: xt ist erst ab Index lag definiert; die EMA läuft über die
    # NaN-Periode ohnehin erst ab period-1 vollständig auf. Defensiv werden
    # die ersten period-1 Werte als NaN markiert (Warmup-Vertrag).
    result[: max(period - 1, 0)] = np.nan
    return result


def _kama_values(values: np.ndarray, period: int) -> np.ndarray:
    """KAMA (Kaufman Adaptive MA), ER-basiert (Ergänzung 4).

    - period dient als ER-Periode (Change vs. Volatilität, Default 10).
    - alpha_factor entfällt bei KAMA.
    - Seed = values[length] (erster Wert mit definierter ER).
    - Inhärent rekursiv -> kompakte Python-Schleife über das NumPy-Array.
    """
    length = max(int(period), 1)
    n = len(values)
    result = np.full(n, np.nan, dtype=float)
    if n <= length:
        return result

    diff = np.abs(np.diff(values))  # len n-1
    # vol[i-length] = Summe der letzten `length` Bar-Diffs bis Index i
    vol = np.convolve(diff, np.ones(length, dtype=float), mode="valid")  # len n-length
    change = np.abs(values[length:] - values[:-length])  # len n-length
    er = np.divide(
        change, vol, out=np.zeros_like(change, dtype=float), where=vol > 0.0
    )
    sc = np.square(er * (_KAMA_FAST_ALPHA - _KAMA_SLOW_ALPHA) + _KAMA_SLOW_ALPHA)

    m = n - length
    kama = np.empty(m, dtype=float)
    prev = float(values[length])
    kama[0] = prev
    for i in range(1, m):
        val = float(values[length + i])
        prev = prev + sc[i] * (val - prev)
        kama[i] = prev
    result[length:] = kama
    return result


def _alma_values(values: np.ndarray, period: int) -> np.ndarray:
    """ALMA (Arnaud Legoux MA) mit TradingView-Defaults (Ergänzung 4).

    Gewichte werden über np.convolve angewendet – wegen der rückwärtigen
    Faltungs-Orientierung (v[0] trifft den ältesten Wert) wird weights[::-1]
    gefaltet, damit weights[0] auf den ältesten und weights[period-1] auf den
    jüngsten Wert des Fensters wirken (identisch zur Referenzschleife).
    """
    if period <= 1:
        return values.astype(float, copy=True)
    offset = (period - 1) * _ALMA_OFFSET
    sigma = period / 6.0
    m = np.arange(period, dtype=float) - offset
    weights = np.exp(-(m * m) / (2.0 * sigma * sigma))
    weights = weights / weights.sum()
    conv = np.convolve(values, weights[::-1], mode="valid")
    result = np.full(len(values), np.nan, dtype=float)
    result[period - 1:] = conv
    return result


def _vwma_values(
    values: np.ndarray, volume: np.ndarray, period: int
) -> np.ndarray:
    """VWMA: sum(price*volume) / sum(volume) über das Fenster.

    Null-/NaN-Volumen wird mit 0 normalisiert (Ergänzung 5). Ist die
    rollierende Volumen-Summe eines Fensters <= 0, fällt dieses Fenster auf
    den SMA-Wert zurück (kein Division-by-Zero).
    """
    if period <= 1:
        return values.astype(float, copy=True)
    vol = np.where(np.isnan(volume), 0.0, volume)
    pv = values * vol
    pv_sum = np.convolve(pv, np.ones(period, dtype=float), mode="valid")
    vol_sum = np.convolve(vol, np.ones(period, dtype=float), mode="valid")
    sma_tail = _sma_values(values, period)[period - 1:]
    valid = vol_sum > 0.0
    wv = np.full(len(vol_sum), np.nan, dtype=float)
    wv[valid] = pv_sum[valid] / vol_sum[valid]
    wv[~valid] = sma_tail[~valid]
    result = np.full(len(values), np.nan, dtype=float)
    result[period - 1:] = wv
    return result


# ---------------------------------------------------------------------------
# Öffentliche Klasse
# ---------------------------------------------------------------------------


class MATemplateEngine:
    """Vektorisierte Moving-Average-Utility für Indikatoren (Phase 16.04).

    Rein stateless – alle Methoden sind abhängigkeitsfrei und können direkt
    aus Indikator-Plugins heraus genutzt werden (Open/Closed, additiv).
    """

    # ------------------------------------------------------------ Schema-API
    @staticmethod
    def get_ma_parameter_schema() -> Dict[str, Dict[str, Any]]:
        """Standard-Parameter-Schema für MA-basierte Indikatoren.

        Konvention exakt wie im Projekt üblich (vgl. _FIXED_GRID_PROXIMITY_SCHEMA
        in chart/indicators/fixed_grid_proximity.py und dem Schema-Renderer in
        chart/indicator_dialog.py): {"type": "...", "default": ...,
        "min"/"max"/"step", "options", "description", "style_type"}.

        Hinweis (E7/Ergänzung 2): bull_color-Default ist "#2196F3" – der
        dual_color-abhängige Default "#26A69A" wird zur Laufzeit über
        resolve_bull_color() aufgelöst.
        """
        return {
            "ma_type": {
                "type": "choice",
                "options": list(MA_TYPES),
                "default": "EHMA",
                "description": "Moving-Average-Typ",
            },
            "period": {
                "type": "int",
                "default": 4,
                "min": 1,
                "max": 500,
                "step": 1,
                "description": "MA-Periode",
            },
            "smooth_type": {
                "type": "choice",
                "options": list(MA_TYPES),
                "default": "EHMA",
                "description": "Smoothing-Typ (Forward-Compatibility, 16.04 noch nicht konsumiert)",
            },
            "alpha_factor": {
                "type": "float",
                "default": 2.0,
                "min": 0.1,
                "max": 10.0,
                "step": 0.1,
                "description": "Decay-Faktor für Alpha-MAs (EHMA/DEMA/TEMA)",
            },
            "dual_color": {
                "type": "bool",
                "default": False,
                "description": "Auf/Ab-Färbung aktiv (t vs. t-1)",
            },
            "bull_color": {
                "type": "color",
                "default": _DEFAULT_BULL_COLOR,
                "description": "Farbe steigender MA (dual_color=False durchgehend)",
                "style_type": "line",
            },
            "bear_color": {
                "type": "color",
                "default": _DEFAULT_BEAR_COLOR,
                "description": "Farbe fallender MA (dual_color=True)",
                "style_type": "line",
            },
        }

    # ------------------------------------------------------------ Berechnung
    @staticmethod
    def crop_dataframe(df: pd.DataFrame, max_limit: int) -> pd.DataFrame:
        """Schneidet den DataFrame auf die letzten `max_limit` Zeilen zu."""
        if df is None or max_limit is None:
            return df
        if len(df) <= max_limit:
            return df
        return df.tail(int(max_limit))

    @classmethod
    def calculate_ma(
        cls,
        source: pd.Series,
        ma_type: MAType,
        period: int,
        alpha_factor: float = 2.0,
        volume: Optional[pd.Series] = None,
    ) -> pd.Series:
        """Berechnet einen der 12 MA-Typen vektorisiert.

        Args:
            source: Preis-Serie (z. B. df['close']).
            ma_type: Einer der 12 MA-Typen (MAType).
            period: MA-Periode (min 1).
            alpha_factor: Decay-Faktor für Alpha-MAs (E4); entfällt bei KAMA.
            volume: Volumen-Serie für VWMA (z. B. df['tick_volume']). Fehlt
                    sie oder ist sie Null/NaN, fällt VWMA auf SMA zurück (E5).

        Returns:
            pd.Series mit demselben Index wie `source`; die ersten
            `period - 1` Werte sind NaN (Warmup).
        """
        if source is None:
            return pd.Series(dtype=float)
        src = pd.to_numeric(source, errors="coerce")
        period_int = max(int(period), 1)
        values = src.to_numpy(dtype=float, na_value=np.nan)
        n = len(values)
        if n == 0:
            return pd.Series(index=src.index, dtype=float)

        alpha = float(alpha_factor) / (period_int + 1.0)

        key = str(ma_type or "").strip().upper()
        if key == "SMA":
            result = _sma_values(values, period_int)
        elif key == "EMA":
            result = _ema_span_values(values, period_int)
        elif key == "WMA":
            result = _wma_values(values, period_int)
        elif key == "DEMA":
            result = _dema_values(values, period_int, alpha)
        elif key == "TEMA":
            result = _tema_values(values, period_int, alpha)
        elif key == "HMA":
            result = _hma_values(values, period_int)
        elif key == "EHMA":
            result = _ehma_values(values, period_int, alpha)
        elif key == "ZLEMA":
            result = _zlema_values(values, period_int)
        elif key == "RMA":
            result = _rma_values(values, period_int)
        elif key == "KAMA":
            result = _kama_values(values, period_int)
        elif key == "ALMA":
            result = _alma_values(values, period_int)
        elif key == "VWMA":
            if volume is None or len(volume) != n:
                result = _sma_values(values, period_int)  # E5-Fallback
            else:
                vol = pd.to_numeric(volume, errors="coerce").to_numpy(
                    dtype=float, na_value=np.nan
                )
                result = _vwma_values(values, vol, period_int)
        else:
            raise ValueError(
                f"Unbekannter MA-Typ '{ma_type}'. Gültig: {MA_TYPES}"
            )

        return pd.Series(result, index=src.index, dtype=float)

    # ------------------------------------------------------------ Darstellung
    @staticmethod
    def build_color_series(
        ma_series: pd.Series,
        dual_color: bool,
        bull_color: str,
        bear_color: str,
    ) -> List[str]:
        """Färbt die MA-Serie gemäß dual_color-Semantik (E6).

        - dual_color=False: durchgehend bull_color.
        - dual_color=True: ma_t >= ma_{t-1} -> bull_color, sonst bear_color.
        - NaN-Vergleiche (Warmup) gelten als bull_color (defensiv).
        - Index 0 hat keinen Vorgänger -> bull_color.
        """
        n = len(ma_series)
        if n == 0:
            return []
        if not dual_color:
            return [str(bull_color)] * n
        values = pd.to_numeric(ma_series, errors="coerce").to_numpy(
            dtype=float, na_value=np.nan
        )
        diff = np.diff(values)  # len n-1; NaN propagiert
        is_up = np.ones(n, dtype=bool)
        finite = ~np.isnan(diff)
        is_up[1:] = np.where(finite, diff >= 0.0, True)
        return np.where(is_up, str(bull_color), str(bear_color)).tolist()

    @staticmethod
    def build_chart_payload(
        time_series: pd.Series,
        ma_series: pd.Series,
        colors: List[str],
    ) -> List[Dict[str, Any]]:
        """Baut ein LWC-v5-kompatibles Objekt-Array (Ergänzung 3).

        Vertrag:
          * [{"time": int(epoch-Sekunden, Wanduhr), "value": float,
             "color": str}, ...]
          * Zeilen mit NaN/None in time oder value werden übersprungen
            (Warmup period-1).
          * Längen-Mismatch (len(colors) < len(ma_series)) wird defensiv
            toleriert: fehlende Farbe fällt auf bull_color zurück.
        """
        payload: List[Dict[str, Any]] = []
        n = len(ma_series)
        if n == 0:
            return payload
        times = time_series.to_numpy()
        values = pd.to_numeric(ma_series, errors="coerce").to_numpy(
            dtype=float, na_value=np.nan
        )
        default_color = str(colors[0]) if colors else _DEFAULT_BULL_COLOR
        for i in range(n):
            try:
                ts = int(times[i])
            except (TypeError, ValueError):
                continue
            v = values[i]
            if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
                continue
            color = str(colors[i]) if i < len(colors) and colors[i] else default_color
            payload.append({"time": ts, "value": float(v), "color": color})
        return payload
