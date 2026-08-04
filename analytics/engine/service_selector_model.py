# analytics/engine/service_selector_model.py
"""
Phase 15 15.02 – ServiceSelectorModel (zentrales, lesendes Datenmodell).

Bereitet die Service-/Set-Hierarchie fuer das 2-Spalten-MasterTree und die
generische Service-Auswahl (ServiceSelectorWidget) auf. Quellen:

  * `ServiceSetRepository.list_sets()`       – gespeicherte Service-Sets
  * `PluginRegistry`                          – alle verfuegbaren Plugins
  * `StateManager.load_all_instances()`       – Live-Status "aktiv im Chart"
    (indicators_state[*]['active'] == True)

Der Model hoert auf `EventBus.service_set_changed` und aktualisiert sich
automatisch in allen Fenstern (Invariante 5: schwellenfreie Entkopplung).

Reines Lesemodell – es schreibt NIE in die DB. UI-Klassen zeigen ausschliesslich
diese aufbereiteten Daten an (Invariante 4: kein SQL in UI).

Verwendete Badge-Konvention (Spalte 1 des MasterTree):
  * `📌 Indikator: <Name>`   – Plugin mit capabilities['chart'] == True
  * `🟢 Aktiv in Chart`      – Indikator ist in mind. einem Chart-Fenster aktiv
  * `⚪ Inaktiv in Chart`    – Indikator ist nirgends aktiv / kein Chart-Pflicht
"""

from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import QObject, Signal

from config.event_bus import event_bus


class ServiceSelectorModel(QObject):
    """Zentrales, lesendes Datenmodell der Service-Hierarchie (Phase 15.02).

    Signals:
        data_changed: wird nach jedem Refresh emittiert (Set-/Status-Aenderung
                      oder Plugin-Reload) – Widgets abonnieren es und bauen
                      ihren Baum/die Combos neu auf.
    """

    data_changed = Signal()

    #: Gruppen-Kennungen der Hierarchie (build_tree)
    GROUP_SETS = "sets"
    GROUP_STANDALONE = "standalone"
    GROUP_PLUGINS = "plugins"

    def __init__(self, set_repo=None, state_manager=None, registry=None,
                 parent: Optional[QObject] = None) -> None:
        """Erstellt das Modell.

        Args:
            set_repo:      ServiceSetRepository (Default: echte Instanz).
            state_manager: StateManager (Default: echte Instanz) – Quelle fuer
                           den Live-Status "aktiv im Chart".
            registry:      PluginRegistry (Default: echte Instanz) – Quelle der
                           verfuegbaren Plugins.
            parent:        Qt-Parent (optional).
        """
        super().__init__(parent)
        from analytics.engine.service_set_repository import ServiceSetRepository
        from analytics.features.feature_builder import PluginRegistry
        from state_manager import StateManager

        self.set_repo = set_repo or ServiceSetRepository()
        self.state_manager = state_manager or StateManager()
        self.registry = registry or PluginRegistry()

        self._sets: List[Dict[str, Any]] = []
        self._active_indicator_ids: Set[str] = set()

        # Initialbefuellung + Live-Sync (schwellenfrei via EventBus)
        self.refresh()
        event_bus.service_set_changed.connect(self.refresh)

    # -------------------------------------------------------------------------
    # Refresh & Status-Ermittlung
    # -------------------------------------------------------------------------

    def refresh(self) -> None:
        """Laedt Sets, Plugins und den Live-Status neu und informiert alle
        lauschenden Widgets (data_changed)."""
        try:
            self._sets = self.set_repo.list_sets()
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] list_sets() fehlgeschlagen: {e}")
            self._sets = []
        self._active_indicator_ids = self._collect_active_indicator_ids()
        self.data_changed.emit()

    def _collect_active_indicator_ids(self) -> Set[str]:
        """Sammelt alle indicator_ids/plugin_ids, die in offenen Chart-
        Fenstern aktiv sind (indicators_state[..]['active'] == True).

        Quelle: StateManager.load_all_instances() – pro Fenster-Instanz wird
        das indicators_state-JSON ausgewertet. Defensiv gegen fehlende/leere
        Eintraege und JSON-Strings (DuckDB liefert die JSON-Spalte teils als
        String).
        """
        active: Set[str] = set()
        try:
            for inst in self.state_manager.load_all_instances() or []:
                ind_state = self._as_dict(inst.get("indicators_state"))
                if not ind_state:
                    continue
                for ind_id, st in ind_state.items():
                    if isinstance(st, dict) and st.get("active"):
                        active.add(str(ind_id))
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Aktiv-Status nicht lesbar: {e}")
        return active

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        """Wandelt einen Wert defensiv in ein Dict um (JSON-String oder dict)."""
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                from db_service import _parse_json_field
                parsed = _parse_json_field(value)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    # -------------------------------------------------------------------------
    # Lese-API (fuer Widgets & Tests)
    # -------------------------------------------------------------------------

    def get_sets(self) -> List[Dict[str, Any]]:
        """Alle gespeicherten Service-Sets (volle Definitionen)."""
        return list(self._sets)

    def get_plugins(self) -> Dict[str, Any]:
        """Alle registrierten Plugins (plugin_id.lower() -> PluginFeature)."""
        return dict(getattr(self.registry, "plugins", {}) or {})

    def get_plugin(self, plugin_id: str) -> Optional[Any]:
        """Plugin aus der Registry (case-insensitiv) oder None."""
        try:
            return self.registry.get(plugin_id)
        except (KeyError, AttributeError):
            return None

    def is_chart_indicator(self, plugin_id: str) -> bool:
        """True, wenn das Plugin als Chart-Indikator verfuegbar ist
        (capabilities['chart'] == True)."""
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return False
        try:
            return bool((plugin.capabilities or {}).get("chart", False))
        except Exception:
            return False

    def get_indicator_display_name(self, plugin_id: str) -> str:
        """Anzeige-Name fuer das 📌-Badge (metadata['display_name'])."""
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return plugin_id
        try:
            return str((plugin.metadata or {}).get("display_name") or plugin_id)
        except Exception:
            return plugin_id

    def is_active_in_chart(self, plugin_id: str) -> bool:
        """True, wenn das Plugin in mind. einem Chart-Fenster aktiv ist."""
        key = str(plugin_id).lower()
        return any(pid.lower() == key for pid in self._active_indicator_ids)

    def badge_for(self, plugin_id: str) -> str:
        """Kompaktes Status-Badge (Spalte 1 des MasterTree).

        Beispiele:
            "📌 Indikator: Grid Liquidity | 🟢 Aktiv in Chart"
            "📌 Indikator: Grid Liquidity | ⚪ Inaktiv in Chart"
            "⚪ Inaktiv in Chart"            (kein Chart-Indikator, nicht aktiv)
            "🟢 Aktiv in Chart"              (kein Chart-Indikator, aber aktiv)
        """
        parts: List[str] = []
        if self.is_chart_indicator(plugin_id):
            parts.append(f"📌 Indikator: {self.get_indicator_display_name(plugin_id)}")
        parts.append("🟢 Aktiv in Chart" if self.is_active_in_chart(plugin_id)
                     else "⚪ Inaktiv in Chart")
        return " | ".join(parts)

    def get_standalone_plugin_ids(self) -> List[str]:
        """Plugin-IDs, die in KEINEM gespeicherten Service-Set vorkommen
        (⚡ Standalone Services – frei verfuegbare Plugins)."""
        used: Set[str] = set()
        for s in self._sets:
            services = s.get("services") or {}
            for cfg in services.values():
                if isinstance(cfg, dict) and cfg.get("plugin_id"):
                    used.add(str(cfg["plugin_id"]).lower())
        return sorted(
            pid for pid in self.get_plugins().keys()
            if pid.lower() not in used
        )

    def build_tree(self) -> List[Dict[str, Any]]:
        """Baut die vollstaendige Hierarchie fuer das 2-Spalten-MasterTree.

        Rueckgabe (pro Gruppe ein Dict):
            [{"group": "sets", "label": "📁 Service-Sets", "children": [
                 {"set_id": ..., "display_name": ..., "definition": {...},
                  "services": [{"instance_id": ..., "plugin_id": ...,
                                "badge": ...}, ...]}, ...]},
             {"group": "standalone", "label": "⚡ Standalone Services",
              "children": [{"plugin_id": ..., "badge": ...}, ...]},
             {"group": "plugins", "label": "📦 Alle verfügbaren Plugins",
              "children": [{"plugin_id": ..., "badge": ...}, ...]}]

        Deterministisch sortiert (Sets nach display_name, Plugins alphabetisch).
        """
        sets = sorted(self._sets,
                      key=lambda s: str(s.get("display_name") or s.get("set_id") or "").lower())
        set_nodes: List[Dict[str, Any]] = []
        for s in sets:
            services = s.get("services") or {}
            order = s.get("execution_order") or []
            service_nodes: List[Dict[str, Any]] = []
            for iid in order:
                cfg = services.get(iid) or {}
                pid = str(cfg.get("plugin_id") or iid)
                service_nodes.append({
                    "instance_id": iid,
                    "plugin_id": pid,
                    "badge": self.badge_for(pid),
                })
            set_nodes.append({
                "set_id": s.get("set_id"),
                "display_name": s.get("display_name") or s.get("set_id") or "Unbenannt",
                "definition": s,
                "services": service_nodes,
            })

        standalone_nodes = [
            {"plugin_id": pid, "badge": self.badge_for(pid)}
            for pid in self.get_standalone_plugin_ids()
        ]

        plugin_nodes = [
            {"plugin_id": pid, "badge": self.badge_for(pid)}
            for pid in sorted(self.get_plugins().keys())
        ]

        return [
            {"group": self.GROUP_SETS, "label": "📁 Service-Sets",
             "children": set_nodes},
            {"group": self.GROUP_STANDALONE, "label": "⚡ Standalone Services",
             "children": standalone_nodes},
            {"group": self.GROUP_PLUGINS, "label": "📦 Alle verfügbaren Plugins",
             "children": plugin_nodes},
        ]

    def find_set(self, set_id: str) -> Optional[Dict[str, Any]]:
        """Liefert die Set-Definition zur set_id (oder None)."""
        for s in self._sets:
            if s.get("set_id") == set_id:
                return s
        return None

    def find_service(self, set_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
        """Liefert die Service-Konfiguration (instance_id) eines Sets (oder None)."""
        s = self.find_set(set_id)
        if not s:
            return None
        return (s.get("services") or {}).get(instance_id)
