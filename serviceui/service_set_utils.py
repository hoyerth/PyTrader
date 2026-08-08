# serviceui/service_set_utils.py
"""
Service-UI: Wiederverwendbare Helfer für das Service-Fenster.

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert –
Verhalten unverändert.
"""

from typing import Any, Dict, List, Optional


# 18.01.03 (E1): Separater global_settings-Key fuer den Kategorie-Override
# eines Standalone-Plugins (NICHT plugin_params_<id> – das bleibt exklusiv
# dem Parameter-Preset vorbehalten; siehe Entscheidung E1 im Prüfprotokoll).
PLUGIN_CATEGORY_KEY = "plugin_category_{}"


def set_set_category(set_repo, set_id: str, category_path: str) -> bool:
    """Setzt den Kategorie-Pfad eines Service-Sets (18.01.03, E2).

    Laedt die Definition FRISCH aus der DB (kein Cache), setzt das
    `category`-Feld ("" = Root-Ebene) und persistiert additiv via
    save_set(). record_snapshot=False – ein Ordner-Verschieben ist eine
    interne Struktur-Verwaltung (wie die P14-04 Bestands-Migration) und
    erzeugt KEINE Snapshot-Historie (Invariante 9).

    Returns:
        True bei Erfolg (Set existierte und wurde gespeichert).
    """
    set_id = str(set_id or "").strip()
    if not set_id or set_repo is None:
        return False
    try:
        definition = set_repo.get_set(set_id)
    except Exception as e:
        print(f"WARN [service_set_utils] Set '{set_id}' nicht ladbar: {e}")
        return False
    if not definition:
        return False
    definition["category"] = str(category_path or "").strip()
    try:
        set_repo.save_set(definition, record_snapshot=False)
    except Exception as e:
        print(f"WARN [service_set_utils] Kategorie fuer Set '{set_id}' "
              f"nicht gespeichert: {e}")
        return False
    return True


def set_plugin_category(state_manager, plugin_id: str,
                        category_path: str) -> bool:
    """Setzt den Kategorie-Override eines Plugins (18.01.03, E1).

    Persistiert den Slash-Pfad unter `plugin_category_<plugin_id>` in
    global_settings ("" = Root-Ebene hebt metadata['category'] auf). Der
    Override hat VORRANG vor metadata['category'] (Modell _category_parts).
    Das bestehende `plugin_params_<id>` bleibt unangetastet.

    Returns:
        True bei Erfolg (plugin_id vorhanden und gespeichert).
    """
    plugin_id = str(plugin_id or "").strip()
    if not plugin_id or state_manager is None:
        return False
    try:
        state_manager.save_global_value(
            PLUGIN_CATEGORY_KEY.format(plugin_id),
            str(category_path or "").strip())
    except Exception as e:
        print(f"WARN [service_set_utils] Kategorie fuer Plugin '{plugin_id}' "
              f"nicht gespeichert: {e}")
        return False
    return True


def _replace_prefix(path: str, old_path: str, new_path: str) -> str:
    """Ersetzt das Pfad-Praefix old_path in path durch new_path.

    Nur echte Ordner-Grenzen zaehlen: 'A/B' ersetzt 'A' UND 'A/C' (unter
    'A'), aber NICHT 'AB'. Liefert path unveraendert, wenn old_path nicht
    Praefix ist.
    """
    if path == old_path:
        return new_path
    if path.startswith(old_path + "/"):
        return new_path + path[len(old_path):]
    return path


def rename_category(model, set_repo, state_manager, group: str,
                    old_path: str, new_path: str) -> int:
    """Benennt/verschiebt einen Kategorie-Ordner (String-Replace, 18.01.03).

    Fuehrt fuer ALLE Kinder des Ordners ein Pfad-Update durch:
      * group == 'sets'     -> jedes Set mit category-Praefix old_path wird
                               via set_set_category() neu gespeichert.
      * group == 'plugins'  -> jedes Plugin mit aufgeloestem Pfad-Praefix
                               old_path erhaelt einen Kategorie-Override auf
                               den neuen Pfad (plugin_category_<id>). Auch
                               Plugins, deren Kategorie bisher aus
                               metadata['category'] stammte, werden dadurch
                               dauerhaft umgezogen (Override gewinnt).
    Der Aufrufer emittiert danach `event_bus.service_set_changed`.

    Returns:
        Anzahl der betroffenen Elemente (Sets bzw. Plugins).
    """
    old_path = str(old_path or "").strip().strip("/")
    new_path = str(new_path or "").strip().strip("/")
    if not old_path or old_path == new_path:
        return 0
    group = str(group or "").strip()
    count = 0
    try:
        if group == "sets":
            for s in (model.get_sets() if model is not None else []) or []:
                cat = str(s.get("category") or "").strip()
                if not cat:
                    continue
                updated = _replace_prefix(cat, old_path, new_path)
                if updated != cat and set_set_category(
                        set_repo, str(s.get("set_id") or ""), updated):
                    count += 1
        else:
            plugins = (model.get_plugins() if model is not None else {}) or {}
            for pid in sorted(plugins.keys()):
                current = (model.plugin_category_path(pid)
                           if model is not None else "")
                if not current:
                    continue
                updated = _replace_prefix(current, old_path, new_path)
                if updated != current and set_plugin_category(
                        state_manager, pid, updated):
                    count += 1
    except Exception as e:
        print(f"WARN [service_set_utils] Ordner-Rename '{old_path}' -> "
              f"'{new_path}' fehlgeschlagen: {e}")
    return count


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

