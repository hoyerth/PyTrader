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
