# PROJEKT-ÜBERSICHT: PyTrader — Rest (automatisch ergaenzt)

> Teil-Export (sachbezogen). Vollständiger Export: export_Full.md
> Dateien in dieser Datei: 8

## 1. ORDNERSTRUKTUR
```
PyTrader/
    analytics/
        engine/
            mtf_fc_boundary.py
            mtf_fc_cascade.py
            mtf_fc_confluence.py
            mtf_fc_guards.py
            mtf_fc_partition.py
            mtf_fc_provider.py
            mtf_fc_state.py
            mtf_fc_templates.py
```

## 2. QUELLCODE

### DATEI: analytics/engine/mtf_fc_boundary.py
```py
# analytics/engine/mtf_fc_boundary.py
"""
MTF-FC v4 (Kapitel 21.03.02) – Boundary Policy & Historien-Detection.

Praezise Ermittlung der M1-Verfuegbarkeitsgrenze und Umsetzung der
Boundary Policy (`coverage_status = "native" | "fallback"`, `source_tf`)
gem. §3.2 Ebene 1 und §4 Säule 1.3.

Regeln:
  * `from_ts >= m1_available_from`  -> `coverage_status = "native"`,
    `source_tf = "M1"`.
  * `from_ts <  m1_available_from`  -> `coverage_status = "fallback"`,
    `source_tf` = naechst-hoherer Timeframe, der fuer den Zeitraum Daten
    besitzt (Kandidaten M5, M15, H1, H4, D1; Default H1).
  * **Hartverbot:** Eine hoehere Aggregationsstufe darf niemals als M1
    deklariert werden ($H1 \\to M1$ strikt verboten) – `source_tf` ist immer
    der tatsaechlich verwendete TF.

Reine Logik (kein UI-Import, Grundsatz 4/11). Alle Zeiten sind Wanduhr-Epochs
(Invariante 7).
"""

from typing import Any, Dict, Optional

from analytics.engine.mtf_fc_provider import MtfFcProvider

#: Aufsteigend nach Granularitaet – der naechst-hoherer TF mit Daten.
FALLBACK_TF_CANDIDATES = ("M5", "M15", "H1", "H4", "D1")
#: Default-Fallback, wenn kein Kandidat Daten besitzt (Basis-Aggregation).
DEFAULT_FALLBACK_TF = "H1"

SECONDS_PER_DAY = 86400


def format_available_date(epoch: Optional[int]) -> str:
    """Formatiert die M1-Verfuegbarkeitsgrenze als `DD.MM.JJJJ` (Wanduhr).

    Wanduhr-Garantie (Invariante 7): Die Epoch ist Wanduhr-encoded, daher
    liefert die UTC-Darstellung exakt das Wanduhr-Datum.
    """
    if epoch is None:
        return "unbekannt"
    from datetime import datetime as _dt
    from datetime import timezone as _utc
    d = _dt.fromtimestamp(int(epoch), tz=_utc.utc)
    return f"{d.day:02d}.{d.month:02d}.{d.year:04d}"


class MtfFcBoundary:
    """Boundary-Evaluierung auf Basis des MtfFcProvider (reine Logik)."""

    def __init__(self, provider: Optional[MtfFcProvider] = None) -> None:
        self.provider = provider or MtfFcProvider()

    def resolve_boundary(self, symbol: str) -> Dict[str, Any]:
        """Ermittelt die Historien-Grenze des Symbols.

        Returns:
            {"m1_available_from": Optional[int] (Wanduhr-Epoch),
             "coverage_status": "native",
             "source_tf": "M1"}
        """
        m1_from = self.provider.get_earliest_timestamp(symbol, "M1")
        return {
            "m1_available_from": m1_from,
            "coverage_status": "native" if m1_from is not None else "fallback",
            "source_tf": "M1" if m1_from is not None else DEFAULT_FALLBACK_TF,
        }

    def evaluate_coverage(self, symbol: str, from_ts: Optional[int]) -> Dict[str, Any]:
        """Bewertet die Datenabdeckung fuer einen angefragten Zeitfenster-Start.

        Args:
            symbol: Symbol (z. B. "SILVER").
            from_ts: Linke Viewport-Kante als Wanduhr-Epoch (Optional).

        Returns:
            {"coverage_status": "native" | "fallback",
             "source_tf": "M1" | naechst-hoherer TF,
             "m1_available_from": Optional[int]}
        """
        boundary = self.resolve_boundary(symbol)
        m1_from = boundary["m1_available_from"]

        # Defensiv: keine M1-Daten bekannt -> Fallback auf DEFAULT_FALLBACK_TF.
        if m1_from is None:
            return {
                "coverage_status": "fallback",
                "source_tf": self._find_fallback_source(symbol, from_ts),
                "m1_available_from": None,
            }

        # from_ts unbekannt -> native (Standard-Annahme: Daten vorhanden).
        if from_ts is None:
            return {
                "coverage_status": "native",
                "source_tf": "M1",
                "m1_available_from": m1_from,
            }

        if from_ts >= m1_from:
            return {
                "coverage_status": "native",
                "source_tf": "M1",
                "m1_available_from": m1_from,
            }

        # Zoom vor die M1-Grenze -> Fallback auf naechst-hoherer TF mit Daten.
        return {
            "coverage_status": "fallback",
            "source_tf": self._find_fallback_source(symbol, from_ts),
            "m1_available_from": m1_from,
        }

    def _find_fallback_source(self, symbol: str, from_ts: Optional[int]) -> str:
        """Naechst-hoherer TF, dessen Daten die linke Kante abdecken.

        Es gewinnt der erste Kandidat (feinster zuerst), dessen aeltester Bar
        <= from_ts liegt (d. h. der Zeitraum ist abgedeckt). Liefert kein
        Kandidat Daten, wird DEFAULT_FALLBACK_TF verwendet.
        """
        for tf in FALLBACK_TF_CANDIDATES:
            earliest = self.provider.get_earliest_timestamp(symbol, tf)
            if earliest is None:
                continue
            if from_ts is None or earliest <= from_ts:
                return tf
        return DEFAULT_FALLBACK_TF

```

--------------------------------------------------

### DATEI: analytics/engine/mtf_fc_cascade.py
```py
# analytics/engine/mtf_fc_cascade.py
"""
MTF-FC v4 (Kapitel 21.03.03) – Hysterese-Kaskaden-Engine (Auto Cascade).

Zoom-Kaskade mit Haupt-Stufen M1 → M5 → H1 → H4 → D1, Zoom-Baendern,
Hysterese-Schwellwerten, Transition Guard und Telemetrie (§4 Säule 2).

Zoom-Baender (Auto):
  * Band 1 (< 2.0 d):            M1 ↔ M5
  * Band 2 (2.0 d – 10.0 d):     M15 ↔ H1 (Fein-Stufe M15)
  * Band 3 (10.0 d – 35.0 d):    H4
  * Band 4 (> 35.0 d):           D1

Hysterese (stabiler Zustand zwischen den Band-Grenzen verhindert Oszillation):
  * M1/M5 → H1  bei Zoom-Out ab  3.5 d   (ZOOM_OUT_THRESHOLD_M1)
  * H1   → M5   bei Zoom-In  unter 2.0 d (ZOOM_IN_THRESHOLD_M1)
  * H1   → H4   bei Zoom-Out ab  10.0 d  (ZOOM_OUT_THRESHOLD_H4)
  * H4   → H1   bei Zoom-In  unter 10.0 d
  * H4   → D1   bei Zoom-Out ab  35.0 d  (ZOOM_OUT_THRESHOLD_H1)
  * D1   → H4   bei Zoom-In  unter 28.0 d (ZOOM_IN_THRESHOLD_H1)

Transition Guard: Ein Umschalten erfolgt erst, wenn
`now() - transition_started_at >= CROSSFADE_DURATION_MS / 1000.0`.
Jedes Kaskaden-Event emittiert ein strukturiertes Telemetrie-Log
(trigger, from_tf, to_tf, range_days).

Reine Logik (kein UI-Import, Grundsatz 4/11). Alle Zeiten sind Wanduhr-Epochs
(Invariante 7). `now` ist injizierbar (Testbarkeit, Test 2).
"""

from typing import Any, Dict, Optional

SECONDS_PER_DAY = 86400.0

# ---------------------------------------------------------------------------
# Schwellwerte (konfigurierbar, Test 1)
# ---------------------------------------------------------------------------
ZOOM_OUT_THRESHOLD_M1 = 3.5   # Tage – M1/M5 → H1 (Zoom-Out)
ZOOM_IN_THRESHOLD_M1 = 2.0    # Tage – H1 → M1/M5 (Zoom-In)
ZOOM_OUT_THRESHOLD_H4 = 10.0  # Tage – H1 → H4 (Grenze Band 2→3)
ZOOM_OUT_THRESHOLD_H1 = 35.0  # Tage – H4 → D1 (Zoom-Out)
ZOOM_IN_THRESHOLD_H1 = 28.0   # Tage – D1 → H4 (Zoom-In)
CROSSFADE_DURATION_MS = 250.0  # UI-Parameter (Transition Guard)

#: Haupt-Stufen der Auto-Kaskade (praegnante Stufen gegen visuelles Flackern).
MAIN_STEPS = ("M1", "M5", "H1", "H4", "D1")

#: Granularitaets-Rang fuer Vergleichsoperationen (kleiner = feiner).
TF_RANK = {"M1": 1, "M5": 2, "M10": 3, "M15": 4, "M30": 5, "H1": 6, "H4": 7, "D1": 8}

#: Fein-Stufen innerhalb der Baender (manuell erzwingbar, nicht verboten).
BAND_FINE_STEPS = ("M15", "M30", "H2")


def range_days_of(viewport_from_ts: Optional[int], viewport_to_ts: Optional[int]) -> float:
    """Zeitfenster-Breite in Tagen (Wanduhr-Epochs). Unbekannte Werte -> 0.0."""
    if not viewport_from_ts or not viewport_to_ts:
        return 0.0
    return max(0.0, (int(viewport_to_ts) - int(viewport_from_ts)) / SECONDS_PER_DAY)


def _telemetry(trigger: str, from_tf: Optional[str], to_tf: Optional[str], range_days: float) -> Dict[str, Any]:
    """Strukturiertes Telemetrie-Log eines Kaskaden-Events (§4 Säule 2.2)."""
    return {"trigger": trigger, "from_tf": from_tf, "to_tf": to_tf, "range_days": range_days}


def evaluate_cascade(
    viewport_from_ts: Optional[int],
    viewport_to_ts: Optional[int],
    current_tf: str,
    cascade_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Bewertet die Kaskade fuer die aktuelle Viewport-Breite.

    Args:
        viewport_from_ts/to_ts: Viewport-Kanten als Wanduhr-Epochs.
        current_tf: Aktueller Chart-Timeframe (z. B. "M5").
        cascade_state: Optionaler Kaskaden-State (wird NICHT mutiert).

    Returns:
        {"current_tf": str, "candidate_tf": str|None,
         "direction": "zoom_in"|"zoom_out"|None, "range_days": float,
         "telemetry": Dict|None}
    """
    state = cascade_state or {}
    current = current_tf or state.get("current_tf") or "M5"
    range_days = range_days_of(viewport_from_ts, viewport_to_ts)
    candidate = current
    direction = None
    telemetry = None

    rank = TF_RANK.get(current, TF_RANK["M5"])

    if current in ("M1", "M5") or rank <= TF_RANK["M5"]:
        # Band 1 + Band 2-Untergrenze: Zoom-Out erst ab 3.5 d, Zoom-In Fein-
        # Stufe M1 unter 2.0 d. Zwischen 2.0 d und 3.5 d stabil (Hysterese).
        if range_days >= ZOOM_OUT_THRESHOLD_M1:
            candidate, direction = "H1", "zoom_out"
        elif current == "M5" and range_days < ZOOM_IN_THRESHOLD_M1:
            candidate, direction = "M1", "zoom_in"
        else:
            candidate, direction = current, None

    elif current in ("H1", "M15", "M30") or TF_RANK["M5"] < rank < TF_RANK["H4"]:
        # Band 2: Zoom-Out ab 10.0 d -> H4; Zoom-In unter 2.0 d -> M5.
        if range_days > ZOOM_OUT_THRESHOLD_H4:
            candidate, direction = "H4", "zoom_out"
        elif range_days < ZOOM_IN_THRESHOLD_M1:
            candidate, direction = "M5", "zoom_in"
        else:
            candidate, direction = current, None

    elif current in ("H4", "H2") or TF_RANK["H4"] <= rank < TF_RANK["D1"]:
        # Band 3: Zoom-Out ab 35.0 d -> D1; Zoom-In unter 10.0 d -> H1.
        if range_days > ZOOM_OUT_THRESHOLD_H1:
            candidate, direction = "D1", "zoom_out"
        elif range_days < ZOOM_OUT_THRESHOLD_H4:
            candidate, direction = "H1", "zoom_in"
        else:
            candidate, direction = current, None

    elif current == "D1" or rank >= TF_RANK["D1"]:
        # Band 4: Zoom-In unter 28.0 d -> H4.
        if range_days < ZOOM_IN_THRESHOLD_H1:
            candidate, direction = "H4", "zoom_in"
        else:
            candidate, direction = current, None

    if direction is not None:
        telemetry = _telemetry(direction, current, candidate, range_days)

    return {
        "current_tf": current,
        "candidate_tf": candidate if candidate != current else None,
        "direction": direction,
        "range_days": range_days,
        "telemetry": telemetry,
    }


def transition_guard_ok(cascade_state: Dict[str, Any], now: Optional[float] = None) -> bool:
    """Transition Guard (§4 Säule 2.2): Umschalten erst nach CROSSFADE-Zeit.

    True, wenn seit `transition_started_at` mindestens
    `CROSSFADE_DURATION_MS / 1000.0` Sekunden vergangen sind (oder der State
    noch nie eine Transition gestartet hat).
    """
    if now is None:
        import time
        now = time.time()
    started = float(cascade_state.get("transition_started_at") or 0.0)
    if started <= 0.0:
        return True
    return (now - started) >= (CROSSFADE_DURATION_MS / 1000.0)


def apply_transition(
    cascade_state: Dict[str, Any],
    candidate_tf: str,
    direction: str,
    range_days: float,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Wendet eine bestaetigte Transition auf den Kaskaden-State an.

    Setzt `current_tf`, `last_transition_at` (= jetzt) und startet die naechste
    Guard-Periode via `transition_started_at`. Rueckgabe: Telemetrie-Log.
    """
    if now is None:
        import time
        now = time.time()
    from_tf = cascade_state.get("current_tf")
    cascade_state["current_tf"] = candidate_tf
    cascade_state["candidate_tf"] = None
    cascade_state["direction"] = None
    cascade_state["range_days"] = range_days
    cascade_state["last_transition_at"] = float(now)
    cascade_state["transition_started_at"] = float(now)
    return _telemetry(direction, from_tf, candidate_tf, range_days)

```

--------------------------------------------------

### DATEI: analytics/engine/mtf_fc_confluence.py
```py
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

```

--------------------------------------------------

### DATEI: analytics/engine/mtf_fc_guards.py
```py
# analytics/engine/mtf_fc_guards.py
"""
MTF-FC v4 (Kapitel 21.03.05) – State-Machine & Prioritaets-Kette (Guards).

Umsetzung der Zustandstabelle (§3.1) und der Prioritaets-Kette (§3.2):

  Ebene 1 – Hard Data Availability Guard: Fehlen M1-Daten vor der Daten-
            Grenze, erzwingt das System `coverage_status = "fallback"` mit
            dem naechst-hoherer TF (21.03.02). H1→M1 ist strikt verboten.
  Ebene 2 – Temporary User Override (Geister-Marker Klick): Transaktions-
            Semantik mit `previous_data_tf` und Reset-Rueckstellung.
  Ebene 3 – Fixed Data-TF Guard: Chart-TF schaltet nie hoeher als das
            fixierte Data-TF; D1-Upgrade gesperrt.
  Ebene 4 – Auto Cascade (21.03.03).
  Ebene 5 – Visual Rendering Preference (Farbschemata/Labels, UI).

Reine Logik (kein UI-Import, Grundsatz 4/11).
"""

from typing import Any, Dict, Optional

from analytics.engine.mtf_fc_cascade import TF_RANK, evaluate_cascade

#: Repraesentation des freien (Multi-)Zustands des Data-TF.
MULTI_DATA_TF = "multi"

#: Inkongruenz-Warnung bei manuellem D1-Wunsch bei fixiertem M15-Data-TF.
WARNING_INCONGRUENT = (
    "D1-Kerzen nicht möglich, da Data-TF auf M15 fixiert. Kerzen auf M15 gesetzt."
)

#: Badge-Text des Temporary Override (UI-Anzeige, 21.03.09).
OVERRIDE_BADGE_TEMPLATE = "🌐 Data-TF temporär gelockert auf {target_tf} | Reset"


def _tf_rank(tf: Optional[str]) -> int:
    """Granularitaets-Rang eines Timeframes (unbekannt -> sehr fein = 1)."""
    if not tf:
        return 1
    return TF_RANK.get(str(tf).upper(), 1)


def apply_priority_chain(
    data_tf: str,
    requested_chart_tf: str,
    cascade_state: Optional[Dict[str, Any]] = None,
    override: Optional[Dict[str, Any]] = None,
    boundary: Optional[Dict[str, Any]] = None,
    viewport_range: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wendet die Prioritaets-Kette an und liefert den effektiven Chart-TF.

    Args:
        data_tf: Data-TF aus dem Filter (z. B. "M15", "multi").
        requested_chart_tf: Vom Nutzer gewuenschter Chart-TF (oder "auto").
        cascade_state: Kaskaden-State (21.03.03).
        override: Temporary User Override (Ebene 2).
        boundary: Boundary-Bewertung (21.03.02, Ebene 1).
        viewport_range: {"from_ts", "to_ts"} fuer die Auto-Kaskade.

    Returns:
        {"effective_tf": str, "guard": str|None, "warning": str|None,
         "source_tf": str|None}
    """
    cascade_state = cascade_state or {}
    override = override or {}
    boundary = boundary or {}
    viewport_range = viewport_range or {}
    result: Dict[str, Any] = {
        "effective_tf": requested_chart_tf or "M5",
        "guard": None,
        "warning": None,
        "source_tf": None,
    }

    # --- Ebene 2: Temporary User Override gewinnt vor dem Fixed-Guard -------
    if override.get("active") and override.get("target_tf"):
        result["effective_tf"] = str(override["target_tf"])
        result["guard"] = "temporary_override"
        return result

    # --- Ebene 1: Hard Data Availability Guard ------------------------------
    coverage = boundary.get("coverage_status")
    source_tf = boundary.get("source_tf") or "M1"
    if coverage == "fallback":
        # Fallback-TF ist der tatsaechlich verwendete TF (nie als M1 deklariert).
        result["effective_tf"] = source_tf
        result["guard"] = "data_availability"
        result["source_tf"] = source_tf
        return result

    # --- Ebene 3: Fixed Data-TF Guard ---------------------------------------
    if data_tf and str(data_tf).lower() != MULTI_DATA_TF:
        data_rank = _tf_rank(data_tf)
        chart_tf = requested_chart_tf or "auto"
        if str(chart_tf).lower() != "auto":
            if _tf_rank(chart_tf) > data_rank:
                result["effective_tf"] = str(data_tf)
                result["guard"] = "fixed_data_tf"
                if str(chart_tf).upper() == "D1" and str(data_tf).upper() in ("M1", "M5", "M15"):
                    result["warning"] = WARNING_INCONGRUENT
                return result

    # --- Ebene 4: Auto Cascade ----------------------------------------------
    if str(requested_chart_tf).lower() in ("auto", ""):
        from_ts = viewport_range.get("from_ts")
        to_ts = viewport_range.get("to_ts")
        current = cascade_state.get("current_tf") or "M5"
        cascade = evaluate_cascade(from_ts, to_ts, current, cascade_state)
        result["effective_tf"] = cascade.get("candidate_tf") or current
        result["guard"] = "auto_cascade" if cascade.get("candidate_tf") else None
        return result

    # --- Sonst: unveraenderter Wunsch-TF ------------------------------------
    result["effective_tf"] = requested_chart_tf
    return result


# ---------------------------------------------------------------------------
# Temporary User Override (Ebene 2) – Transaktions-Semantik
# ---------------------------------------------------------------------------
def start_override(
    override: Dict[str, Any],
    previous_data_tf: str,
    target_tf: str,
    reason: str = "ghost_marker_click",
) -> Dict[str, Any]:
    """Startet den Temporary Override (Transaktions-Semantik).

    Setzt `active=True`, `previous_data_tf` (fuer Reset), `target_tf`
    und `reason`. Rueckgabe: der mutierte Override-Dict.
    """
    override["active"] = True
    override["previous_data_tf"] = previous_data_tf
    override["target_tf"] = target_tf
    override["reason"] = reason
    return override


def reset_override(override: Dict[str, Any]) -> str:
    """Setzt den Override zurueck und stellt `previous_data_tf` wieder her.

    Rueckgabe: der wiederhergestellte Data-TF (z. B. "M15").
    """
    restored = override.get("previous_data_tf")
    override["active"] = False
    override["previous_data_tf"] = None
    override["target_tf"] = None
    override["reason"] = None
    return restored or "multi"


def override_badge_text(override: Dict[str, Any]) -> Optional[str]:
    """Badge-Text `[ 🌐 Data-TF temporär gelockert auf X | Reset ]`."""
    if not override.get("active"):
        return None
    target = override.get("target_tf") or "?"
    return OVERRIDE_BADGE_TEMPLATE.format(target_tf=target)

```

--------------------------------------------------

### DATEI: analytics/engine/mtf_fc_partition.py
```py
# analytics/engine/mtf_fc_partition.py
"""
MTF-FC v4 (Kapitel 21.03.06) – Event-Partitionierung & Cache-Invalidierung.

Partitionierte RAM-Cache-Invalidierung:
  $affected\\_partition = partition(symbol, timeframe, t_{event})$

Nachtraeglich eingehende Ticks invalidieren ausschliesslich die RAM-Partition
ihrer eigenen Event-Zeit $t_{event}$ – nie den gesamten Cache (§4 Säule 2.3).

Integration mit der Cache-Versionierung (21.03.01): Nach einer Invalidierung
wird `cache_generation` im Namespace inkrementiert.

Reine Logik (kein UI-Import, Grundsatz 4/11). Alle Zeiten sind Wanduhr-Epochs
(Invariante 7).
"""

from typing import Any, Dict, Optional, Tuple

from analytics.engine.mtf_fc_provider import MtfFcProvider


def partition(symbol: str, timeframe: str, ts: int) -> Tuple[str, str, str]:
    """Partitions-Schluessel der Event-Zeit: `(symbol, timeframe, datum)`.

    Das Datum ist das Wanduhr-Datum (`YYYY-MM-DD`) der Event-Zeit
    (Invariante 7) – gleiche Kalendertage teilen sich eine RAM-Partition.
    """
    return MtfFcProvider.partition_of_event(symbol, timeframe, ts)


def invalidate_partition(
    cache: Dict[Tuple[str, str, str], Dict[str, Any]],
    symbol: str,
    timeframe: str,
    t_event: int,
    namespace: Optional[Dict[str, Any]] = None,
) -> bool:
    """Entfernt ausschliesslich die Partition der Event-Zeit aus dem Cache.

    Args:
        cache: Der RAM-Partitions-Cache (`shared_state["mtf_fc"]["ram_cache"]`).
        symbol/timeframe: Betroffenes Symbol/TF.
        t_event: Event-Zeit (Wanduhr-Epoch) des nachtraeglichen Ticks.
        namespace: Optionaler MTF-FC-Namespace – bei Erfolg wird hier
            `cache_generation` inkrementiert (21.03.06 Schritt 3).

    Returns:
        True, wenn genau ein Partitions-Eintrag entfernt wurde; False, wenn
        die Partition nicht (oder nicht mehr) existiert.
    """
    key = partition(symbol, timeframe, t_event)
    if not isinstance(cache, dict) or key not in cache:
        return False
    del cache[key]
    if isinstance(namespace, dict):
        namespace["cache_generation"] = int(namespace.get("cache_generation", 0)) + 1
    return True


def invalidate_partition_via_provider(
    provider: MtfFcProvider,
    context: Any,
    symbol: str,
    timeframe: str,
    t_event: int,
) -> bool:
    """Komfort-Wrapper: Invalidierung direkt ueber den Provider/Namespace."""
    ns = provider.read_namespace(context)
    cache = ns.setdefault("ram_cache", {})
    return invalidate_partition(cache, symbol, timeframe, t_event, ns)

```

--------------------------------------------------

### DATEI: analytics/engine/mtf_fc_provider.py
```py
# analytics/engine/mtf_fc_provider.py
"""
MTF-FC v4 (Kapitel 21.03.01) – Data Provider & Cache-Versionierung (Schicht 2).

Der Provider kapselt den gesamten Lese-Zugriff auf die Market-Daten
(`ohlcv_bars` in `data/market_data.duckdb`, read-only via DbPool) und den
Namespace `PluginContext.shared_state["mtf_fc"]`.

Verantwortlichkeiten:
  * `get_earliest_timestamp(symbol, timeframe)` – MIN("time") je Symbol/TF
    (Wanduhr-Epoch, Invariante 7; defensiv None bei Fehler/leerer DB).
  * `get_latest_timestamp(symbol, timeframe)`  – MAX("time") je Symbol/TF
    (Basis der Cache-Versionierung).
  * Cache-Versionierung `(symbol, timeframe, partition)`: Ein Eintrag traegt
    `source_max_timestamp`; er ist nur gueltig, wenn diese Quellgrenze <= dem
    aktuellen DB-Maximum liegt (sonst stale -> Partitions-Invalidierung, 21.03.06).
  * Namespace-Schreibzugriff ausschliesslich ueber den Provider
    (`read_namespace(context)` / `write_namespace(context, **changes)`).

Wanduhr-Garantie (Invariante 7): Alle Zeiten sind Wanduhr-Epochs
(Berlin-Wanduhr-encoded, 1:1 aus der DB gelesen) – keine Offset-Umrechnung.

Open/Closed (Grundsatz 11): Kein Bestandsmodul wird veraendert; die
Lese-Muster folgen FeatureStoreReader.fetch_ohlcv_snapshot / _epoch_of().
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from analytics.features.plugins.base_plugin import PluginContext
from analytics.engine.mtf_fc_state import ensure_mtf_fc_namespace

# Projekt-Root = 3 Ebenen ueber dieser Datei (engine/ -> analytics/ -> Root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_MARKET = str(BASE_DIR / "data" / "market_data.duckdb")

#: Kompakte Partitions-Kodierung: Wanduhr-Datum (UTC) der Event-Zeit.
from datetime import datetime as _dt_datetime
from datetime import timezone as _dt_timezone


def _epoch_to_partition(ts: int) -> str:
    """Partitions-Schluessel einer Event-Zeit: Wanduhr-Datum `YYYY-MM-DD`.

    Wanduhr-Garantie (Invariante 7): Die Epoch ist Wanduhr-encoded, daher
    liefert die UTC-Darstellung exakt das Wanduhr-Datum der Event-Zeit.
    """
    return _dt_datetime.fromtimestamp(int(ts), tz=_dt_timezone.utc).strftime("%Y-%m-%d")


class MtfFcProvider:
    """Datenzugriff + Namespace-Verwaltung fuer das MTF-FC-System.

    Args:
        market_db_path: Testbarkeit (Seam) – Default `data/market_data.duckdb`.
        pool: DbPool-Klasse/Objekt mit `get(db_path)`-API (Default `DbPool`).
    """

    def __init__(self, market_db_path: Optional[str] = None, pool: Any = None) -> None:
        self.market_db_path = market_db_path or DB_MARKET
        if pool is None:
            from db.db_pool import DbPool
            pool = DbPool
        self._pool = pool

    # ------------------------------------------------------------------
    # Roh-Zeitgrenzen (Wanduhr-Epochs)
    # ------------------------------------------------------------------
    def get_earliest_timestamp(self, symbol: str, timeframe: str) -> Optional[int]:
        """Aeltester Bar-Zeitpunkt des Symbols im Timeframe (Wanduhr-Epoch).

        Defensiv: `None` bei leerer DB, unbekanntem Symbol/TF oder Fehler.
        """
        return self._query_bound("MIN", symbol, timeframe)

    def get_latest_timestamp(self, symbol: str, timeframe: str) -> Optional[int]:
        """Neuester Bar-Zeitpunkt des Symbols im Timeframe (Wanduhr-Epoch).

        Defensiv: `None` bei leerer DB, unbekanntem Symbol/TF oder Fehler.
        """
        return self._query_bound("MAX", symbol, timeframe)

    def _query_bound(self, agg: str, symbol: str, timeframe: str) -> Optional[int]:
        if not symbol or not timeframe:
            return None
        try:
            con = self._pool.get(self.market_db_path)
            row = con.execute(
                f'SELECT {agg}("time") FROM ohlcv_bars '
                'WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?) '
                'AND "time" IS NOT NULL',
                [symbol, timeframe],
            ).fetchone()
            value = row[0] if row else None
            if value is None:
                return None
            if hasattr(value, "timestamp"):  # datetime-Objekt -> Wanduhr-Epoch
                return int(value.timestamp())
            return int(value)
        except Exception as e:
            print(f"WARN [MtfFcProvider] {agg}('time') fehlgeschlagen "
                  f"(symbol={symbol}, tf={timeframe}): {e}")
            return None

    # ------------------------------------------------------------------
    # Cache-Versionierung (21.03.01 Schritt 3 + 21.03.06)
    # ------------------------------------------------------------------
    @staticmethod
    def cache_key(symbol: str, timeframe: str, partition: str) -> Tuple[str, str, str]:
        """Stabiler Cache-Schluessel `(symbol, timeframe, partition)`."""
        return (symbol.upper(), timeframe.upper(), partition)

    @staticmethod
    def partition_of_event(symbol: str, timeframe: str, ts: int) -> Tuple[str, str, str]:
        """Partitions-Schluessel einer Event-Zeit inkl. Symbol/TF.

        $affected\\_partition = partition(symbol, timeframe, t_{event})$ –
        die Partition einer nachtraeglich eingehenden Event-Zeit. Rein
        deterministisch aus der Wanduhr-Epoch (Invariante 7).
        """
        return MtfFcProvider.cache_key(symbol, timeframe, _epoch_to_partition(ts))

    def is_cache_valid(
        self,
        cache: Dict[Tuple[str, str, str], Dict[str, Any]],
        symbol: str,
        timeframe: str,
        partition: str,
    ) -> bool:
        """True, wenn der Cache-Eintrag nicht stale ist.

        Ein Eintrag ist genau dann gueltig, wenn sein `source_max_timestamp`
        kleiner/gleich dem aktuellen DB-Maximum des Symbols/TF liegt. Ist die
        Quelle gewachsen (neuer Bar nachgeladen), ist der Eintrag stale.
        Fehlt der Eintrag oder das DB-Maximum, ist er ungueltig.
        """
        key = self.cache_key(symbol, timeframe, partition)
        entry = cache.get(key)
        if not isinstance(entry, dict):
            return False
        source_max = entry.get("source_max_timestamp")
        if not isinstance(source_max, (int, float)):
            return False
        db_max = self.get_latest_timestamp(symbol, timeframe)
        if db_max is None:
            return False
        return float(source_max) <= float(db_max)

    # ------------------------------------------------------------------
    # Namespace-Zugriff (einzige Schreib-Schnittstelle, 21.03.01 Schritt 4)
    # ------------------------------------------------------------------
    def read_namespace(self, context: PluginContext) -> Dict[str, Any]:
        """Liefert den `mtf_fc`-Namespace des Contexts (ggf. initialisiert)."""
        if context is None:
            context = PluginContext(mode="batch")
        return ensure_mtf_fc_namespace(context.shared_state)

    def write_namespace(self, context: PluginContext, **changes: Any) -> Dict[str, Any]:
        """Schreibt Aenderungen in den `mtf_fc`-Namespace (additiv, flach).

        Es werden nur die uebergebenen Keys aktualisiert – nicht betroffene
        Teil-Dicts bleiben unangetastet. Rueckgabe: der aktualisierte Namespace.
        """
        ns = self.read_namespace(context)
        ns.update(changes)
        return ns

    def clear_partition(
        self,
        context: PluginContext,
        symbol: str,
        timeframe: str,
        partition: str,
    ) -> bool:
        """Entfernt exakt einen Partitions-Eintrag aus dem RAM-Cache.

        (21.03.06) Erhoeht bei Erfolg `cache_generation` im Namespace.
        Rueckgabe: True, wenn ein Eintrag entfernt wurde.
        """
        ns = self.read_namespace(context)
        cache = ns.setdefault("ram_cache", {})
        key = self.cache_key(symbol, timeframe, partition)
        if key in cache:
            del cache[key]
            ns["cache_generation"] = int(ns.get("cache_generation", 0)) + 1
            return True
        return False

```

--------------------------------------------------

### DATEI: analytics/engine/mtf_fc_state.py
```py
# analytics/engine/mtf_fc_state.py
"""
MTF-FC v4 (Kapitel 21.03.01) – Default-Factory & Struktur des isolierten
Namespace `PluginContext.shared_state["mtf_fc"]`.

Der Namespace ist der Single Source of Truth fuer alle MTF-FC-Komponenten
(Data Provider, Boundary Policy, Hysterese-Kaskade, Confluence, Guards,
Partitionierung, UI). Er wird ausschliesslich ueber den MtfFcProvider
(read_namespace/write_namespace) gelesen und geschrieben – kein UI-Direktzugriff
(Open/Closed, MVVM, Grundsatz 4/11).

Wanduhr-Garantie (Invariante 7): Alle Zeiten in diesem Namespace sind
Wanduhr-Epochs (Berlin-Wanduhr-encoded), keine Offset-Umrechnung.
"""

from typing import Any, Dict


#: Schema-Version des Namespace (Semantic Versioning, fuer spaetere Migration).
MTF_FC_SCHEMA_VERSION = "1.0.0"


def default_cascade_state() -> Dict[str, Any]:
    """Default-Zustand der Hysterese-Kaskade (§4 Säule 2, 21.03.03)."""
    return {
        "current_tf": "M5",
        "candidate_tf": None,
        "direction": None,          # "zoom_in" | "zoom_out" | None
        "transition_started_at": 0.0,
        "last_transition_at": 0.0,
        "range_days": 0.0,
    }


def default_history_boundaries() -> Dict[str, Any]:
    """Default der Historien-Grenzen (§3.2 Ebene 1, 21.03.02)."""
    return {
        "m1_available_from": None,  # Optional[int] Wanduhr-Epoch
        "coverage_status": "native",  # "native" | "fallback"
        "source_tf": "M1",
    }


def default_guard_override() -> Dict[str, Any]:
    """Default des Temporary User Override (§3.2 Ebene 2, 21.03.05)."""
    return {
        "active": False,
        "previous_data_tf": None,   # z. B. "M15"
        "target_tf": None,          # z. B. "D1"
        "reason": None,             # z. B. "ghost_marker_click"
    }


def default_mtf_fc_state() -> Dict[str, Any]:
    """Default-Struktur des kompletten Namespace `shared_state["mtf_fc"]`.

    Exakt die Keys aus §5 der Spezifikation – als tiefe, unabhaengige Kopie
    (keine geteilten Referenzen zwischen mehreren Contexts/Namespaces).
    """
    return {
        "active_data_tf": "M15",
        "active_chart_tf": "M5",
        "viewport_range": {"from_ts": None, "to_ts": None},
        "cascade_state": default_cascade_state(),
        "history_boundaries": default_history_boundaries(),
        "cache_generation": 0,
        "temporary_guard_override": default_guard_override(),
        # 21.03.01: RAM-Partitions-Cache (nicht in DuckDB persistiert).
        # Schlüssel: (symbol, timeframe, partition) -> {"source_max_timestamp": int}
        "ram_cache": {},
        "schema_version": MTF_FC_SCHEMA_VERSION,
    }


def ensure_mtf_fc_namespace(shared_state: Dict[str, Any]) -> Dict[str, Any]:
    """Stellt sicher, dass der `mtf_fc`-Namespace existiert und alle
    Default-Keys enthaelt (additiv, abwaertskompatibel).

    Args:
        shared_state: `PluginContext.shared_state` (Dict des Contexts).

    Returns:
        Der (ggf. neu angelegte bzw. vervollstaendigte) `mtf_fc`-Eintrag.
    """
    ns = shared_state.get("mtf_fc")
    if not isinstance(ns, dict):
        ns = default_mtf_fc_state()
        shared_state["mtf_fc"] = ns
    defaults = default_mtf_fc_state()
    for key, value in defaults.items():
        if key not in ns or ns[key] is None:
            ns[key] = value
    return ns

```

--------------------------------------------------

### DATEI: analytics/engine/mtf_fc_templates.py
```py
# analytics/engine/mtf_fc_templates.py
"""
MTF-FC v4 (Kapitel 21.03.07) – View-Template-Persistenz (Pure Logik).

Speichern/Laden kompletter Filter-Konfigurationen des MtfFilterBarWidget
über den bestehenden `SchemaMigrator` (`analytics/engine/schema_migrator.py`):
Gespeicherte Preset-JSONs werden IN-MEMORY validiert und abwärtskompatibel
um neue TFs/Session-Keys erweitert (Payload-Key `mtf_fc_schema_version =
"1.0.0"`). Rollback-Schutz: Eine fehlerhafte Migration wirft TemplateError,
der Aufrufer behält das Original.

Reine Logik (kein UI-Import, Grundsatz 4/11). Kein Persistenz-Medium wird
hier festgeschrieben – die UI/der Aufrufer entscheidet über die Ablage
(Default: in-memory Dict-Registry für die Sitzung).
"""

from typing import Any, Dict, Optional

from analytics.engine.schema_migrator import MigrationError, _needs_migration
from analytics.engine.mtf_fc_confluence import WEIGHTS

#: Aktuelle Template-Schema-Version (Payload-Key).
MTF_FC_SCHEMA_VERSION = "1.0.0"

#: Bekannte Template-Keys (Whitelist für die Migration).
_TEMPLATE_KNOWN_KEYS = (
    "mtf_fc_schema_version", "name", "data_tf", "chart_tf",
    "range_preset", "custom_range", "sort_mode", "session_filters",
    "confluence_weighting", "volatility_adaption", "view_templates_meta",
)

#: Defaults für fehlende/neue Keys (abwärtskompatible Erweiterung).
_TEMPLATE_DEFAULTS: Dict[str, Any] = {
    "data_tf": "multi",
    "chart_tf": "auto",
    "range_preset": "7d",
    "custom_range": {"from_ts": None, "to_ts": None},
    "sort_mode": "date",
    "session_filters": [],
    "confluence_weighting": dict(WEIGHTS),
    "volatility_adaption": False,
    "view_templates_meta": {"created": None, "updated": None},
}


class TemplateError(Exception):
    """Wird bei einer fehlgeschlagenen Template-Migration geworfen.

    Der Aufrufer behält dann das ORIGINAL-Template (Rollback-Schutz).
    """


def create_template(name: str, **filters: Any) -> Dict[str, Any]:
    """Erzeugt ein neues View-Template (Schema-Version + Defaults + Filters)."""
    template: Dict[str, Any] = {"mtf_fc_schema_version": MTF_FC_SCHEMA_VERSION}
    template.update(_TEMPLATE_DEFAULTS)
    template["name"] = name
    for key, value in filters.items():
        if key in _TEMPLATE_KNOWN_KEYS:
            template[key] = value
    return template


def migrate_template(raw: Any) -> Dict[str, Any]:
    """Validieret/migriert ein Template-JSON in-memory (SchemaMigrator-Semantik).

    Ablauf (analog `SchemaMigrator.migrate_instance_config`):
      1. Fehlende bekannte Keys werden mit ihren Defaults ergänzt.
      2. Unbekannte Keys (nicht in der Whitelist) werden entfernt.
      3. `mtf_fc_schema_version` wird auf die aktuelle Version angehoben.

    Raises:
        TemplateError: Bei nicht-Dict-Eingabe oder Migrationsfehler –
        der Aufrufer führt den Rollback auf das Original aus.
    """
    try:
        if not isinstance(raw, dict):
            raise TemplateError(
                f"Template ist kein JSON-Objekt: {type(raw).__name__}")
        result: Dict[str, Any] = dict(raw)
        current = str(result.get("mtf_fc_schema_version") or "0.0.0")

        if not _needs_migration(current, MTF_FC_SCHEMA_VERSION):
            # Nicht-migrationsbedürftig: trotzdem sicherstellen, dass alle
            # Pflicht-Keys existieren (defensive Ergänzung, non-destruktiv).
            for key, default in _TEMPLATE_DEFAULTS.items():
                result.setdefault(key, default)
            return result

        # 1) Fehlende Schema-Keys mit Defaults ergänzen.
        for key, default in _TEMPLATE_DEFAULTS.items():
            if key not in result:
                result[key] = default

        # 2) Unbekannte Keys entfernen (Whitelist = Single Source of Truth).
        for key in list(result.keys()):
            if key not in _TEMPLATE_KNOWN_KEYS:
                result.pop(key, None)

        # 3) Schema-Version anheben.
        result["mtf_fc_schema_version"] = MTF_FC_SCHEMA_VERSION
        return result
    except MigrationError:
        raise
    except TemplateError:
        raise
    except Exception as e:
        raise TemplateError(f"Template-Migration fehlgeschlagen: {e}") from e


class MtfFcTemplateStore:
    """In-memory Template-Registry (Sitzungs-Scope).

    Die Persistenz-Entscheidung (JSON-Datei, DB, Settings) trifft der
    Aufrufer – der Store hält lediglich eine flache Dict-Registry
    (name -> Template) und migriert beim Laden über `migrate_template`.
    """

    def __init__(self) -> None:
        self._templates: Dict[str, Dict[str, Any]] = {}

    def save(self, template: Dict[str, Any]) -> None:
        """Speichert ein (bereits migriertes) Template unter seinem Namen."""
        name = str(template.get("name") or "Unbenannt")
        self._templates[name] = dict(template)

    def load(self, name: str) -> Optional[Dict[str, Any]]:
        """Lädt und migriert ein Template (Rollback-Schutz bei Fehler)."""
        raw = self._templates.get(name)
        if raw is None:
            return None
        try:
            return migrate_template(raw)
        except TemplateError as e:
            print(f"WARN [MtfFcTemplateStore] Template '{name}' verworfen: {e}")
            return None

    def names(self) -> list:
        """Alle gespeicherten Template-Namen (sortiert)."""
        return sorted(self._templates.keys())

    def delete(self, name: str) -> bool:
        """Entfernt ein Template. Rueckgabe: True, wenn es existierte."""
        return self._templates.pop(name, None) is not None

```

--------------------------------------------------

