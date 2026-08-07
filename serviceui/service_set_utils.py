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
    PluginRegistry abgeleitet (srv_grid_lines, srv_proximity, ...),
    NICHT hartkodiert auf einen Indikator-Namen.
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
    (Indikator-Basisservices wie srv_grid_lines/srv_proximity bleiben funktionsfähig).
    Beim Löschversuch wird der Name des verwendeten Sets angezeigt.
    """
    names: List[str] = []
    for s in sets or []:
        services = s.get("services") or {}
        if any((cfg or {}).get("plugin_id") == plugin_id
               for cfg in services.values()):
            names.append(str(s.get("display_name") or s.get("set_id") or "?"))
    return names


def prepare_worker_definition(
    definition: Dict[str, Any],
    lookback_limit: int,
) -> Dict[str, Any]:
    """Bereitet eine ServiceSetDefinition für die gezielte Worker-Ausführung
    auf (serviceui/run_worker.py; der historische ServiceSetRunWorker bzw.
    set_run_worker.py wurde am 05.08.2026 mit der Phase-13-Box entfernt). Die
    übergebene Definition bleibt unverändert – es wird eine Kopie zurückgegeben.

    05.08.2026 (Bugfix Service-Run, zwei Korrekturen):

    1. Implizite Abhängigkeiten (depends_on): Services OHNE expliziten
       `depends_on`-Eintrag, deren Plugin `dependencies` deklariert
       (z.B. srv_proximity -> ['srv_grid_lines']), erhalten die nächstliegende
       VORHERIGE Instanz in execution_order mit passender plugin_id als
       depends_on. Dadurch liest der ProximityService seine Linienliste
       aus shared_state[depends_on[0]] (vorher: 'fertig (kein
       Feature-Store-Payload)' bei UI-angelegten Sets, die kein depends_on
       speichern). Explizit gesetzte Werte werden NIE überschrieben
       (Indikator-intern grid_1 -> prox_1 bleibt unverändert).

    2. Lookback-Override: Jede Service-Instanz läuft mit `lookback_limit`
       (Scanner-Candles (max) aus den App-Optionen, AppSettings.
       scanner_candle_limit) als Scan-Fenster – damit verwenden ALLE
       Services dieselbe Datenbasis wie der Historical Scanner (vorher:
       gespeicherter Service-lookback, z.B. 1000 Feature-Rows bei
       srv_grid_lines).
    """
    import copy as _copy
    from analytics.features.feature_builder import PluginRegistry

    order = list(definition.get("execution_order") or [])
    services = dict(definition.get("services") or {})
    out = dict(definition)
    out["execution_order"] = order
    out["services"] = services
    if not order or not services:
        return out

    try:
        lb = int(lookback_limit)
        if lb < 1:
            lb = 1
    except (TypeError, ValueError):
        lb = 1

    registry = PluginRegistry()
    resolved = _copy.deepcopy(services)
    position = {iid: idx for idx, iid in enumerate(order)}

    for iid in order:
        cfg = resolved.get(iid)
        if not isinstance(cfg, dict):
            continue

        # 1) Implizite depends_on-Auflösung (nur wenn NICHT explizit gesetzt)
        if not cfg.get("depends_on"):
            pid = str(cfg.get("plugin_id") or iid)
            upstream: List[str] = []
            try:
                plugin = registry.get(pid)
                upstream = list(getattr(plugin, "dependencies", None) or [])
            except (KeyError, AttributeError):
                upstream = []
            if upstream:
                for prev_iid in reversed(order[:position.get(iid, 0)]):
                    prev_cfg = resolved.get(prev_iid)
                    if not isinstance(prev_cfg, dict):
                        continue
                    if str(prev_cfg.get("plugin_id") or prev_iid) in upstream:
                        cfg["depends_on"] = [prev_iid]
                        break

        # 2) Lookback-Override (Scanner-Candles (max) für alle Services)
        cfg["lookback"] = lb

    out["services"] = resolved
    return out

