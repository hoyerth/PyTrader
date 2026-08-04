# serviceui/service_set_utils.py
"""
Service-UI: Wiederverwendbare Helfer für das Service-Fenster.

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert –
Verhalten unverändert.
"""

from typing import Any, Dict, List


def _available_plugin_ids() -> str:
    """Alle registrierten Plugin-IDs (sortiert, kommasepariert).

    Phase 13 Schritt 6-Korrektur: Die Verfügbarkeit wird dynamisch aus der
    PluginRegistry abgeleitet (grid_lines, proximity, grid_liquidity, ...),
    NICHT hartkodiert auf 'grid_liquidity'.
    """
    try:
        from analytics.features.feature_builder import PluginRegistry
        return ", ".join(sorted(PluginRegistry().plugins.keys()))
    except Exception:
        return "?"


def _sets_using_plugin(plugin_id: str, sets: List[Dict[str, Any]]) -> List[str]:
    """P14-04-E: Namen aller Service-Sets, die einen Service mit dieser
    plugin_id enthalten.

    Basis der Service-Sperre: Einzel-Services, die in einem gespeicherten
    Service-Set vorkommen, dürfen im Service-Fenster nicht entfernt werden
    (Indikator-Basisservices wie grid_lines/proximity bleiben funktionsfähig).
    Beim Löschversuch wird der Name des verwendeten Sets angezeigt.
    """
    names: List[str] = []
    for s in sets or []:
        services = s.get("services") or {}
        if any((cfg or {}).get("plugin_id") == plugin_id
               for cfg in services.values()):
            names.append(str(s.get("display_name") or s.get("set_id") or "?"))
    return names
