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
