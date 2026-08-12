# analytics/engine/mtf_fc_confluence.py
"""
MTF-FC v4 (Kapitel 21.03.04) – Confluence-Gewichtung & Normalisierung.

Gewichtete Confluence-Scores mit vollstaendigem Gewichtungs-Schema,
Min-Max-Normalisierung, Constant-Matrix-Policy und Volatilitaets-Adaption
(§4 Säule 1.4).

Formel:
  $Score_j = \\sum (W_{TF} \\cdot Signal_{TF})$ – un-normalisiert.
  Die Gewichte fliessen un-normalisiert in die Summe und werden anschliessend
  durch Min-Max-Skalierung auf das Farb-Intervall [0.0, 1.0] abgebildet.

Constant-Matrix-Policy (Min-Max-Fix):
  Ist max_score == min_score, gilt normalized_score = 0.5
  (verhindert Divisionen durch Null).

Volatilitaets-Adaption (Toggle) mit Clamp-Protection:
  ratio = clamp(ATR_TF / ATR_Current, 0.2, 5.0)
  Bei ATR_Current <= 1e-6 wird die Anpassung deaktiviert (ratio = 1.0).

Reine Logik (kein UI-Import, Grundsatz 4/11).
"""

from typing import Dict, List, Optional

#: Vollstaendiges Gewichtungs-Schema (W_TF).
WEIGHTS: Dict[str, float] = {
    "D1": 3.0,
    "H4": 2.5,
    "H1": 2.0,
    "M30": 1.5,
    "M15": 1.5,
    "M5": 1.2,
    "M1": 1.0,
}

#: Clamp-Grenzen der Volatilitaets-Adaption.
VOLATILITY_CLAMP_MIN = 0.2
VOLATILITY_CLAMP_MAX = 5.0
#: ATR-Grenze: darunter wird die Anpassung deaktiviert (ratio = 1.0).
ATR_EPSILON = 1e-6

#: Wert der Constant-Matrix-Policy (flache Matrix).
CONSTANT_MATRIX_VALUE = 0.5


def weight_of(timeframe: str) -> float:
    """Gewicht des Timeframes (Default 1.0 fuer unbekannte TFs)."""
    return WEIGHTS.get(str(timeframe).upper(), 1.0)


def compute_scores(signals: Dict[str, float]) -> Dict[str, float]:
    """Rohe gewichtete Scores je Timeframe: $W_{TF} \\cdot Signal_{TF}$.

    Args:
        signals: Dict Timeframe -> Signalstaerke (typ. 0.0..1.0).

    Returns:
        Dict Timeframe -> roher Score (un-normalisiert).
    """
    scores: Dict[str, float] = {}
    for tf, signal in (signals or {}).items():
        try:
            value = float(signal)
        except (TypeError, ValueError):
            value = 0.0
        scores[str(tf).upper()] = weight_of(tf) * value
    return scores


def aggregate_score(signals: Dict[str, float]) -> float:
    """Gesamter Confluence-Score $\\sum (W_{TF} \\cdot Signal_{TF})$."""
    return float(sum(compute_scores(signals).values()))


def min_max_normalize(scores: List[float]) -> List[float]:
    """Min-Max-Skalierung auf [0.0, 1.0] mit Constant-Matrix-Policy.

    Ist max == min (flache Matrix), liefert jeder Eintrag 0.5
    (keine Division durch Null).
    """
    if not scores:
        return []
    lo, hi = float(min(scores)), float(max(scores))
    if hi - lo <= 1e-12:
        return [CONSTANT_MATRIX_VALUE] * len(scores)
    return [(float(s) - lo) / (hi - lo) for s in scores]


def normalize_named_scores(scores: Dict[str, float]) -> Dict[str, float]:
    """Min-Max-Normalisierung fuer ein benanntes Score-Dict (Order erhalten)."""
    keys = list((scores or {}).keys())
    values = [float(scores[k]) for k in keys]
    normed = min_max_normalize(values)
    return {k: normed[i] for i, k in enumerate(keys)}


def volatility_ratio(
    atr_tf: Optional[float],
    atr_current: Optional[float],
) -> float:
    """Volatilitaets-Verhaeltnis mit Clamp-Protection.

    ratio = clamp(ATR_TF / ATR_Current, 0.2, 5.0).
    Bei fehlendem oder ATR_Current <= 1e-6 wird 1.0 zurueckgegeben
    (Anpassung deaktiviert).
    """
    if atr_current is None or atr_tf is None:
        return 1.0
    try:
        current = float(atr_current)
        tf = float(atr_tf)
    except (TypeError, ValueError):
        return 1.0
    if current <= ATR_EPSILON:
        return 1.0
    ratio = tf / current
    return max(VOLATILITY_CLAMP_MIN, min(VOLATILITY_CLAMP_MAX, ratio))


def adaptive_score(
    signals: Dict[str, float],
    atr_tf: Dict[str, Optional[float]],
    atr_current: Optional[float],
) -> Dict[str, float]:
    """Volatilitaets-adaptive gewichtete Scores je Timeframe.

    Jeder rohe Score wird mit dem Volatilitaets-Ratio seines Timeframes
    multipliziert (Toggle in der UI aktiviert diese Adaption).
    """
    ratio_cur = volatility_ratio(1.0, atr_current)  # Normierungsbasis
    result: Dict[str, float] = {}
    for tf, raw in compute_scores(signals).items():
        ratio = volatility_ratio(atr_tf.get(tf), atr_current)
        result[tf] = raw * (ratio / ratio_cur) if ratio_cur else raw
    return result
