# analytics/engine/service_selector_model.py
"""
Phase 15 15.02 – ServiceSelectorModel (zentrales, lesendes Datenmodell).

Bereitet die Service-/Set-Hierarchie fuer das 2-Spalten-MasterTree und die
generische Service-Auswahl (ServiceSelectorWidget) auf. Quellen:

  * `ServiceSetRepository.list_sets()`       – gespeicherte Service-Sets
  * `PluginRegistry`                          – alle verfuegbaren Plugins
  * `StateManager.load_all_instances()`       – Live-Status "aktiv im Chart"
    (indicators_state[*]['active'] == True)
  * `FeatureStoreReader.fetch_last_execution_dates()` – Datum der letzten
    Ausfuehrung je feature_id (MAX(created_at) in analytics.duckdb/
    feature_store) fuer die MasterTree-Anzeige 'Service_Name (DD.MM.JJ)'

Der Model hoert auf `EventBus.service_set_changed` und aktualisiert sich
automatisch in allen Fenstern (Invariante 5: schwellenfreie Entkopplung).

Reines Lesemodell – es schreibt NIE in die DB. UI-Klassen zeigen ausschliesslich
diese aufbereiteten Daten an (Invariante 4: kein SQL in UI).

Verwendete Badge-Konvention (Spalte 1 des MasterTree):
  * `📌 im <Indikator>`     – Plugin mit capabilities['chart'] == True
                             (bezieht sich auf den echten Indikator-Namen,
                             z.B. 'GridLiquidityIndicator' – KEIN Service-Name)
  * `🟢 aktiv in <Indikator>` – Indikator ist in mind. einem Chart-Fenster aktiv
  * `⚪ inaktiv in <Indikator>` – Indikator ist nirgends aktiv / kein Chart-Pflicht
"""

from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import QObject, Signal

from config.event_bus import event_bus


def list_indicators() -> List[Dict[str, Any]]:
    """Alle verfuegbaren Indikatoren (deterministisch).

    Liefert pro Indikator: {"indicator_id", "display_name",
    "service_plugin_ids"} – Grundlage der Indikator-Auswahl beim Anlegen
    neuer Service-Sets (Bugfix 05.08.2026). Aktuell existiert genau ein
    Plugin-Indikator (GridLiquidityIndicator); weitere Indikatoren werden
    hier Open/Closed ergaenzt (Registry-Prinzip).
    """
    result: List[Dict[str, Any]] = []
    try:
        from chart.indicators.grid_liquidity import GridLiquidityIndicator
        ind = GridLiquidityIndicator()
        svc_ids = list(getattr(ind, "service_plugin_ids", []) or [])
        # Konsistenter Anzeigename: bevorzugt metadata['indicator_name'] des
        # ersten Indikator-Services (identisch zur Tree-Badge-Logik in
        # get_indicator_display_name); Fallback ind.display_name/indicator_id.
        display = str(getattr(ind, "display_name", "")
                      or getattr(ind, "indicator_id", ""))
        try:
            if svc_ids:
                from analytics.features.feature_builder import PluginRegistry
                meta = getattr(PluginRegistry().get(svc_ids[0]),
                               "metadata", {}) or {}
                if meta.get("indicator_name"):
                    display = str(meta["indicator_name"])
        except Exception:
            pass
        result.append({
            "indicator_id": str(getattr(ind, "indicator_id", "")),
            "display_name": display,
            "service_plugin_ids": svc_ids,
        })
    except Exception:
        pass
    return result


def indicator_display_name(indicator_id: str) -> str:
    """Anzeigename eines Indikators (id -> Name); ohne Treffer die id."""
    if not indicator_id:
        return ""
    for info in list_indicators():
        if info["indicator_id"] == indicator_id:
            return info["display_name"] or indicator_id
    return indicator_id


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
                 feature_store_reader=None,
                 parent: Optional[QObject] = None) -> None:
        """Erstellt das Modell.

        Args:
            set_repo:      ServiceSetRepository (Default: echte Instanz).
            state_manager: StateManager (Default: echte Instanz) – Quelle fuer
                           den Live-Status "aktiv im Chart".
            registry:      PluginRegistry (Default: echte Instanz) – Quelle der
                           verfuegbaren Plugins.
            feature_store_reader: FeatureStoreReader (Default: echte Instanz) –
                           rein lesende Quelle fuer das 'Datum der letzten
                           Ausfuehrung' (MAX(created_at) je feature_id in
                           analytics.duckdb/feature_store – MasterTree-Anzeige
                           'Service_Name (DD.MM.JJ)').
            parent:        Qt-Parent (optional).
        """
        super().__init__(parent)
        from analytics.engine.service_set_repository import ServiceSetRepository
        from analytics.features.feature_builder import PluginRegistry
        from analytics.engine.feature_store_reader import FeatureStoreReader
        from state_manager import StateManager

        self.set_repo = set_repo or ServiceSetRepository()
        self.state_manager = state_manager or StateManager()
        self.registry = registry or PluginRegistry()
        self.feature_store_reader = feature_store_reader or FeatureStoreReader()

        self._sets: List[Dict[str, Any]] = []
        self._active_indicator_ids: Set[str] = set()
        # 05.08.2026: Datum der letzten Ausfuehrung je feature_id (DD.MM.JJ)
        self._last_execution_dates: Dict[str, str] = {}

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
        # 05.08.2026: Datum der letzten Ausfuehrung je feature_id (DD.MM.JJ) –
        # wird nach jedem Service-Run (ServiceRunWorker -> EventBus) neu
        # gelesen, damit der MasterTree das Datum live aktualisiert.
        self._last_execution_dates = self._load_last_execution_dates()
        self.data_changed.emit()

    def _load_last_execution_dates(self) -> Dict[str, str]:
        """Liest das Datum der letzten Ausfuehrung je feature_id aus dem
        feature_store (rein lesend ueber den FeatureStoreReader, Invariante
        4: kein SQL im Modell). Defensiv: Fehler -> leer (Baum zeigt dann
        den Fallback '(--.--.--)')."""
        try:
            raw = self.feature_store_reader.fetch_last_execution_dates() or {}
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Ausfuehrungsdaten nicht "
                  f"lesbar: {e}")
            return {}
        # Case-insensitive Zuordnung (feature_id ist die Plugin-ID, z.B.
        # 'proximity' – Registry-IDs sind case-insensitiv).
        return {str(k).lower(): v for k, v in raw.items()}

    def last_execution_date(self, plugin_id: str) -> str:
        """Formatiertes Datum der letzten Ausfuehrung eines Services
        ('DD.MM.JJ', z.B. '05.08.26') – Fallback '--.--.--' ohne Eintraege.

        Der Zeitstempel stammt aus MAX(created_at) des feature_store fuer
        die feature_id (Plugin-ID) des Services. store_plugin_payload()
        aktualisiert created_at bei jedem Upsert, sodass der Wert die
        LETZTE Ausfuehrung widerspiegelt.

        Achtung (05.08.2026, Punkt 1): Der Rueckgabewert enthaelt BEWUSST
        KEINE Klammern – der MasterTree umschliesst ihn beim Label-Aufbau
        ('Service_Name (DD.MM.JJ)' / 'Service_Name (--.--.--)'), damit der
        Fallback nicht doppelt geklammert wird.
        """
        if not plugin_id:
            return "--.--.--"
        return self._last_execution_dates.get(
            str(plugin_id).lower(), "--.--.--")

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

    def get_indicator_id(self, plugin_id: str) -> str:
        """Indikator-ID, in der das Plugin laeuft (metadata['indicator_id']).

        Services (grid_lines/proximity) laufen IN einem Indikator
        (GridLiquidityIndicator -> 'grid_liquidity'); aktiv im Chart sind
        die indicators_state-Keys des Indikators, nicht die Plugin-ID.
        Ohne Angabe faellt die Methode auf die plugin_id selbst zurueck.
        """
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return plugin_id
        try:
            meta = plugin.metadata or {}
            return str(meta.get("indicator_id") or plugin_id)
        except Exception:
            return plugin_id

    def belongs_to_indicator(self, plugin_id: str) -> bool:
        """True, wenn das Plugin explizit einem Indikator zugeordnet ist.

        Signal: metadata['indicator_id'] ODER metadata['indicator_name'] sind
        gesetzt (z.B. GridLiquidityIndicator fuer grid_lines/proximity).
        """
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return False
        try:
            meta = plugin.metadata or {}
            return bool(meta.get("indicator_id") or meta.get("indicator_name"))
        except Exception:
            return False

    def get_indicator_display_name(self, plugin_id: str) -> str:
        """Anzeige-Name des Indikators zu einer Plugin-ID.

        Bevorzugt metadata['indicator_name'] (echter Indikatorname, z.B.
        'GridLiquidityIndicator'); Fallback metadata['display_name']
        (Service-Name) bzw. plugin_id.
        """
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return plugin_id
        try:
            meta = plugin.metadata or {}
            return str(meta.get("indicator_name")
                       or meta.get("display_name") or plugin_id)
        except Exception:
            return plugin_id

    def is_active_in_chart(self, plugin_id: str) -> bool:
        """True, wenn das Plugin in mind. einem Chart-Fenster aktiv ist.

        Bugfix 05.08.2026: Beruecksichtigt zusaetzlich den ZUGEHOERIGEN
        Indikator (metadata['indicator_id']). Services laufen IN einem
        Indikator – aktiv im Chart sind die indicators_state-Keys des
        Indikators ('grid_liquidity'), nicht die Plugin-ID selbst. Dadurch
        greift die Tooltip-Variante a) ('aktiv <Indikator>') auch fuer
        Services wie grid_lines/proximity.
        """
        key = str(plugin_id).lower()
        if any(pid.lower() == key for pid in self._active_indicator_ids):
            return True
        ind_id = self.get_indicator_id(plugin_id)
        if ind_id and ind_id.lower() != key:
            return any(pid.lower() == ind_id.lower()
                       for pid in self._active_indicator_ids)
        return False

    def get_set_indicator_names(self, definition: Dict[str, Any]) -> List[str]:
        """Distinkte Indikator-Namen eines Service-Sets.

        Bugfix 05.08.2026: Ein explizit zugewiesenes Feld `indicator_id` in
        der Set-Definition (Anlage-Dialog) wird zuerst ausgewertet; zusaetz-
        lich liefern Services mit Indikator-Zugehoerigkeit (in execution_
        order-Reihenfolge) weitere Indikatoren. Leer, wenn das Set keinem
        Indikator gehoert.
        """
        names: List[str] = []
        explicit = str(definition.get("indicator_id") or "")
        if explicit:
            nm = indicator_display_name(explicit)
            if nm and nm not in names:
                names.append(nm)
        services = definition.get("services") or {}
        order = definition.get("execution_order") or list(services.keys())
        for iid in order:
            cfg = services.get(iid) or {}
            if not isinstance(cfg, dict):
                continue
            pid = str(cfg.get("plugin_id") or iid)
            if not self.belongs_to_indicator(pid):
                continue
            nm = self.get_indicator_display_name(pid)
            if nm and nm not in names:
                names.append(nm)
        return names

    def is_set_active(self, definition: Dict[str, Any]) -> bool:
        """True, wenn mindestens ein Service des Sets aktuell aktiv in einem
        Chart verwendet wird (der zugehoerige Indikator ist aktiv)."""
        services = definition.get("services") or {}
        for cfg in services.values():
            if isinstance(cfg, dict) and cfg.get("plugin_id"):
                if self.is_active_in_chart(str(cfg["plugin_id"])):
                    return True
        return False

    def badge_for(self, plugin_id: str) -> str:
        """Kompaktes Status-Badge (Spalte 1 des MasterTree).

        Die Badges referenzieren den INDIKATOR-Namen (metadata['indicator_name'],
        z.B. 'GridLiquidityIndicator') – Service-Namen erscheinen hier bewusst
        NICHT:

            "📌 im GridLiquidityIndicator | 🟢 aktiv in GridLiquidityIndicator"
            "📌 im GridLiquidityIndicator | ⚪ inaktiv in GridLiquidityIndicator"
            "⚪ inaktiv in GridLiquidityIndicator"   (kein Chart-Indikator)
            "🟢 aktiv in GridLiquidityIndicator"     (kein Chart-Indikator, aktiv)
        """
        parts: List[str] = []
        name = self.get_indicator_display_name(plugin_id)
        if self.is_chart_indicator(plugin_id):
            parts.append(f"📌 im {name}")
        parts.append(f"🟢 aktiv in {name}" if self.is_active_in_chart(plugin_id)
                     else f"⚪ inaktiv in {name}")
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
                    # 05.08.2026: Datum der letzten Ausfuehrung (DD.MM.JJ) –
                    # MasterTree haengt es direkt an den Service-Namen an.
                    "last_execution": self.last_execution_date(pid),
                })
            set_nodes.append({
                "set_id": s.get("set_id"),
                "display_name": s.get("display_name") or s.get("set_id") or "Unbenannt",
                "definition": s,
                "services": service_nodes,
            })

        standalone_nodes = [
            {
                "plugin_id": pid,
                "badge": self.badge_for(pid),
                # 05.08.2026 (Punkt 4): Datum der letzten Ausfuehrung auch fuer
                # Standalone-Services – der MasterTree zeigt es hinter dem
                # Plugin-Namen an (gleiche Semantik wie bei Set-Services).
                "last_execution": self.last_execution_date(pid),
            }
            for pid in self.get_standalone_plugin_ids()
        ]

        plugin_nodes = [
            {
                "plugin_id": pid,
                "badge": self.badge_for(pid),
                # 05.08.2026 (Punkt 4): Datum der letzten Ausfuehrung auch in
                # der 'Alle verfügbaren Plugins'-Gruppe (gleiche Semantik).
                "last_execution": self.last_execution_date(pid),
            }
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

    # ------------------------------------------------------------------
    # 15.03-E (Multi-Select): Anzeigenamen zu feature_ids (Reverse-Mapping)
    # ------------------------------------------------------------------
    def resolve_display_names(self, feature_ids) -> List[str]:
        """Leitbare Anzeigenamen zu plugin_ids (Fallback: die id selbst).

        Wird vom AnalyticsWindow genutzt, wenn nach einem Profilwechsel nur
        die persistierten feature_ids (plugin_ids) vorliegen, aber keine
        display_names (der Dialog wurde nicht geoeffnet). Matcht Set-Services
        deterministisch (erster Treffer in Set-Reihenfolge) und liefert
        '<Set-Anzeigename>/<instance_id>'; ohne Treffer die plugin_id.
        """
        names: List[str] = []
        for fid in feature_ids or []:
            target = str(fid).strip().lower()
            if not target:
                continue
            found: Optional[str] = None
            for s in self._sets:
                services = s.get("services") or {}
                for iid, cfg in services.items():
                    if not isinstance(cfg, dict):
                        continue
                    pid = str(cfg.get("plugin_id") or iid).strip().lower()
                    if pid == target:
                        set_name = s.get("display_name") or s.get("set_id") or "?"
                        found = f"{set_name}/{iid}"
                        break
                if found:
                    break
            names.append(found if found else str(fid))
        return names
