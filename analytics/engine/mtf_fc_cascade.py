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
