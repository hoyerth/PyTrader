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
                             z.B. 'Ind_FixedGridProximity' – KEIN Service-Name)
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
    Plugin-Indikator (Ind_FixedGridProximity); weitere Indikatoren werden
    hier Open/Closed ergaenzt (Registry-Prinzip).
    """
    result: List[Dict[str, Any]] = []
    try:
        from chart.indicators.ind_fixed_grid_proximity import FixedGridProximityIndicator
        ind = FixedGridProximityIndicator()
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
    # 17.01.01: GROUP_STANDALONE entfällt ersatzlos – alle Plugins werden über
    # metadata["category"] in Ordner einsortiert (2 Root-Gruppen: sets, plugins).
    GROUP_SETS = "sets"
    GROUP_PLUGINS = "plugins"
    # 16.08 (K2): Kategorie-Ordner-Knoten (Dynamic Category Trees).
    # Ein Ordner-Dict besitzt das Format:
    #   {"group": GROUP_CATEGORY, "label": "📁 <Name>", "children": [...]}
    GROUP_CATEGORY = "category_node"

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
        # 18.01.03 (E1): Kategorie-Overrides je Plugin (global_settings,
        # Key 'plugin_category_<pid>'). Ein gesetzter Override UEBERSCHREIBT
        # metadata['category'] (auch "" = Root-Ebene); ohne Override gilt das
        # metadata-Feld. Wird in refresh() einmalig geladen und von
        # _category_parts() ausgewertet (kein DB-Zugriff im Baum-Aufbau).
        self._plugin_category_overrides: Dict[str, str] = {}
        # 18.01.03 (E3-revidiert, 08.08.2026): Persistierte benutzererzeugte
        # (ggf. leere) Ordner je Gruppe (global_settings, Key
        # 'tree_folders_<group>'). Wird in refresh() geladen und in
        # build_tree() in die Gruppen-Kinder eingemischt – leere Ordner
        # verschwinden damit NICHT beim Refresh, sondern nur bei manueller
        # Loeschung (Kontextmenue 'Ordner löschen').
        self._empty_folder_paths: Dict[str, List[str]] = {}

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
        # 18.01.03 (E1): Kategorie-Overrides (plugin_category_<pid>) laden –
        # einmalig pro Refresh, damit _category_parts() ohne DB-Zugriff
        # auswertet (Baum-Aufbau bleibt rein lesend aus dem RAM).
        self._plugin_category_overrides = self._load_plugin_category_overrides()
        # 18.01.03 (E3-revidiert): Persistierte benutzererzeugte Ordner je
        # Gruppe laden (tree_folders_<group>); build_tree() mischt sie in
        # die Gruppen-Kinder ein (leere Ordner bleiben ueber Refreshs).
        self._empty_folder_paths = self._load_empty_folders()
        self.data_changed.emit()

    def _load_empty_folders(self) -> Dict[str, List[str]]:
        """Liest die persistierten benutzererzeugten Ordner je Gruppe.

        Quelle: global_settings (Key 'tree_folders_<group>' aus
        service_set_utils, 18.01.03 E3-revidiert). Liefert pro Gruppe eine
        deduplizierte Liste Slash-Pfade OHNE '📁 '-Praefix (z.B.
        ['Swing Points', 'Swing Points/Geometrie']). Defensiv: Fehler -> leer.
        """
        try:
            from serviceui.service_set_utils import EMPTY_FOLDERS_KEY
        except Exception:
            EMPTY_FOLDERS_KEY = "tree_folders_{}"
        result: Dict[str, List[str]] = {}
        for group in (self.GROUP_SETS, self.GROUP_PLUGINS):
            paths: List[str] = []
            try:
                raw = self.state_manager.get_global_value(
                    EMPTY_FOLDERS_KEY.format(group), [])
                if isinstance(raw, list):
                    for p in raw:
                        p = str(p or "").strip().strip("/")
                        if p and p not in paths:
                            paths.append(p)
            except Exception as e:
                print(f"WARN [ServiceSelectorModel] Leere-Ordner der Gruppe "
                      f"'{group}' nicht lesbar: {e}")
            result[group] = paths
        return result

    def empty_folder_paths(self, group: str) -> List[str]:
        """Persistierte benutzererzeugte Ordner-Pfade einer Gruppe (lesend).

        Gruppe 'sets' oder 'plugins' (GROUP_SETS/GROUP_PLUGINS); unbekannte
        Gruppen -> [] (defensiv). Rein lesend aus dem Refresh-Zustand.
        """
        return list(self._empty_folder_paths.get(str(group or ""), []) or [])

    def _load_plugin_category_overrides(self) -> Dict[str, str]:
        """Liest die Kategorie-Overrides aller Plugins aus global_settings.

        Key-Format: 'plugin_category_<plugin_id>' (18.01.03, E1) – Wert ist
        der Slash-Pfad ("" = Root-Ebene) oder ein leerer Eintrag bei fehlendem
        Override (dann gilt metadata['category']). Defensiv: Fehler -> leer.
        """
        overrides: Dict[str, str] = {}
        try:
            for pid in sorted(self.get_plugins().keys()):
                raw = self.state_manager.get_global_value(
                    f"plugin_category_{pid}", None)
                if isinstance(raw, str):
                    overrides[str(pid).lower()] = raw
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Kategorie-Overrides nicht "
                  f"lesbar: {e}")
        return overrides

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
        # 'srv_proximity' – Registry-IDs sind case-insensitiv).
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

        Services (srv_grid_lines/srv_proximity) laufen IN einem Indikator
        (Ind_FixedGridProximity -> 'ind_fixed_grid_proximity'); aktiv im Chart sind
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
        gesetzt (z.B. Ind_FixedGridProximity fuer srv_grid_lines/srv_proximity).
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
        'Ind_FixedGridProximity'); Fallback metadata['display_name']
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
        Indikators ('ind_fixed_grid_proximity'), nicht die Plugin-ID selbst. Dadurch
        greift die Tooltip-Variante a) ('aktiv <Indikator>') auch fuer
        Services wie srv_grid_lines/srv_proximity.
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
        z.B. 'Ind_FixedGridProximity') – Service-Namen erscheinen hier bewusst
        NICHT:

            "📌 im Ind_FixedGridProximity | 🟢 aktiv in Ind_FixedGridProximity"
            "📌 im Ind_FixedGridProximity | ⚪ inaktiv in Ind_FixedGridProximity"
            "⚪ inaktiv in Ind_FixedGridProximity"   (kein Chart-Indikator)
            "🟢 aktiv in Ind_FixedGridProximity"     (kein Chart-Indikator, aktiv)
        """
        parts: List[str] = []
        name = self.get_indicator_display_name(plugin_id)
        if self.is_chart_indicator(plugin_id):
            parts.append(f"📌 im {name}")
        parts.append(f"🟢 aktiv in {name}" if self.is_active_in_chart(plugin_id)
                     else f"⚪ inaktiv in {name}")
        return " | ".join(parts)

    # ------------------------------------------------------------------
    # 16.08 (K1/K2/K8/K9): Kategorie-Ordner (Dynamic Category Trees)
    # ------------------------------------------------------------------

    @staticmethod
    def _cat_key(label: str) -> str:
        """Case-insensitiver Sortier-/Vergleichsschluessel eines Ordners.

        Entfernt das '📁 '-Praefix des Ordnerlabels (K2-Format), damit
        Sortierung (K8) und Pfad-Lookup stabil auf dem reinen Namen laufen.
        """
        s = str(label or "").strip()
        if s.startswith("📁"):
            s = s[len("📁"):].lstrip()
        return s.lower()

    def _category_parts(self, plugin_id: str,
                        plugin: Optional[Any]) -> List[str]:
        """Kategorienpfad eines Plugins (K1, 16.08 / 18.01.03 E1).

        18.01.03 (E1): Ein gesetzter Kategorie-Override (global_settings,
        Key 'plugin_category_<plugin_id>', Quelle des Drag & Drop) hat
        VORRANG vor `metadata['category']` – auch ein leerer String "" hebt
        die metadata-Kategorie auf (Root-Ebene). Ohne Override gilt das
        metadata-Feld wie bisher. Leer ODER der Ist-Default `"General"`
        (base_plugin.py) gelten als "keine Kategorie" -> das Plugin bleibt
        auf der obersten Ebene der Hauptgruppe.
        """
        category = ""
        if plugin_id:
            override = self._plugin_category_overrides.get(
                str(plugin_id).lower())
            if override is not None:
                category = str(override or "").strip()
        if not category:
            try:
                meta = getattr(plugin, "metadata", None) or {}
                category = str(meta.get("category") or "").strip()
            except Exception:
                category = ""
        if not category or category.lower() == "general":
            return []
        return [p.strip() for p in category.split("/") if p.strip()]

    def _insert_into_category_tree(self, nodes: List[Dict[str, Any]],
                                   parts: List[str],
                                   leaf: Dict[str, Any]) -> None:
        """Fuegt ein Plugin-Blatt rekursiv in die Ordnerstruktur ein (K2).

        Erzeugt fehlende Ordner entlang des Pfads. Ordner entstehen NUR
        durch eine tatsaechliche Blatt-Einfuegung -> keine leeren Ordner
        (K9). Ordner-Label folgt dem K2-Format '📁 <Name>'.
        """
        if not parts:
            nodes.append(leaf)
            return
        key = self._cat_key(parts[0])
        folder = None
        for n in nodes:
            if (n.get("group") == self.GROUP_CATEGORY
                    and self._cat_key(n.get("label")) == key):
                folder = n
                break
        if folder is None:
            folder = {"group": self.GROUP_CATEGORY,
                      "label": f"📁 {parts[0]}", "children": []}
            nodes.append(folder)
        self._insert_into_category_tree(folder["children"], parts[1:], leaf)

    def _sort_category_nodes(self,
                             nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sortiert eine Ordner-Ebene (K8, 16.08 / 18.01.03).

        Deterministisch: Ordner zuerst, dann Blaetter; jeweils alphabetisch
        (case-insensitiv). Innerhalb der Ordner rekursiv dieselbe Regel.
        Blaetter koennen seit 18.01.03 sowohl Plugin-Dicts ({plugin_id, ...})
        als auch Sets-Dicts ({set_id, display_name, ...}) sein – als
        Sortiername gilt plugin_id, sonst display_name/set_id.
        """
        def sort_key(n: Dict[str, Any]) -> tuple:
            is_folder = n.get("group") == self.GROUP_CATEGORY
            if is_folder:
                name = self._cat_key(n.get("label"))
            else:
                name = str(n.get("plugin_id")
                           or n.get("display_name")
                           or n.get("set_id") or "").lower()
            return (0 if is_folder else 1, name)

        result = sorted(nodes, key=sort_key)
        for n in result:
            if n.get("group") == self.GROUP_CATEGORY:
                n["children"] = self._sort_category_nodes(n.get("children") or [])
        return result

    def category_plugin_ids(self, category_path: str) -> List[str]:
        """Alle Plugin-IDs unter einem Kategorie-Pfad (rekursiv, 17.01.02).

        Liefert deterministisch (alphabetisch) alle Plugins, deren
        `metadata['category']`-Pfad mit `category_path` beginnt – d.h. auch
        Plugins in UNTER-Ordnern (z.B. Pfad 'Swing Points' liefert auch
        Plugins aus 'Swing Points/Geometrie'). Pfad-Format: slash-separiert
        OHNE '📁 '-Praefixe (z.B. 'Swing Points/Geometrie'), case-insensitiv.

        Grundlage fuer:
          * Kontextmenue '▶️ Alle Services ausführen' auf Ordner-Knoten
            (run_category_requested).
          * Info-Button auf Ordner-Knoten (category_info_requested).
        """
        target = [p.strip().lower() for p in str(category_path or "").split("/")
                  if p.strip()]
        if not target:
            return []
        plugins = self.get_plugins()
        result: List[str] = []
        for pid in sorted(plugins.keys()):
            parts = [p.lower() for p in self._category_parts(pid,
                                                             plugins.get(pid))]
            if len(parts) >= len(target) and parts[:len(target)] == target:
                result.append(pid)
        return result

    def _set_category_parts(self, definition: Dict[str, Any]) -> List[str]:
        """Kategorienpfad eines Service-Sets (18.01.03, E2).

        Lese das optionale Feld `category` der Set-Definition (Slash-Pfad,
        z.B. 'Swing Points/Geometrie'). Leer ODER der Ist-Default "General"
        gelten als "keine Kategorie" -> das Set bleibt auf der obersten
        Ebene der Sets-Gruppe (Spiegel der Plugin-Logik K1).
        """
        category = str((definition or {}).get("category") or "").strip()
        if not category or category.lower() == "general":
            return []
        return [p.strip() for p in category.split("/") if p.strip()]

    def _insert_set_into_category_tree(self, nodes: List[Dict[str, Any]],
                                       parts: List[str],
                                       leaf: Dict[str, Any]) -> None:
        """Fuegt ein Set-Blatt rekursiv in die Ordnerstruktur ein (18.01.03).

        Analoge Mechanik zu `_insert_into_category_tree` (K2), aber fuer
        Sets-Blatt-Dicts ({set_id, display_name, definition, services}).
        Ordner entstehen NUR durch eine tatsaechliche Blatt-Einfuegung ->
        keine leeren Ordner (K9).
        """
        if not parts:
            nodes.append(leaf)
            return
        key = self._cat_key(parts[0])
        folder = None
        for n in nodes:
            if (n.get("group") == self.GROUP_CATEGORY
                    and self._cat_key(n.get("label")) == key):
                folder = n
                break
        if folder is None:
            folder = {"group": self.GROUP_CATEGORY,
                      "label": f"📁 {parts[0]}", "children": []}
            nodes.append(folder)
        self._insert_set_into_category_tree(folder["children"], parts[1:],
                                            leaf)

    def _ensure_category_path(self, nodes: List[Dict[str, Any]],
                              parts: List[str]) -> None:
        """Stellt sicher, dass die Ordnerkette fuer `parts` existiert
        (18.01.03, E3-revidiert).

        Erzeugt fehlende Ordner entlang des Pfads OHNE Blatt-Einfuegung
        (K2-Format '📁 <Name>', children leer). Dient der Einmischung
        persistierter benutzererzeugter (ggf. leerer) Ordner in build_tree():
        Ein bereits vorhandener Ordner (aus echten Blatt-Kategorien) wird
        wiederverwendet – kein Duplikat, keine Kinder-Aenderung.
        """
        if not parts:
            return
        key = self._cat_key(parts[0])
        folder = None
        for n in nodes:
            if (n.get("group") == self.GROUP_CATEGORY
                    and self._cat_key(n.get("label")) == key):
                folder = n
                break
        if folder is None:
            folder = {"group": self.GROUP_CATEGORY,
                      "label": f"📁 {parts[0]}", "children": []}
            nodes.append(folder)
        self._ensure_category_path(folder["children"], parts[1:])

    def category_set_ids(self, category_path: str) -> List[str]:
        """Alle set_ids unter einem Kategorie-Pfad (rekursiv, 18.01.03).

        Liefert deterministisch (Set-Reihenfolge = display_name) alle Sets,
        deren `category`-Pfad mit `category_path` beginnt – d.h. auch Sets in
        UNTER-Ordnern (z.B. Pfad 'Swing Points' liefert auch Sets aus
        'Swing Points/Geometrie'). Pfad-Format: slash-separiert OHNE
        '📁 '-Praefixe, case-insensitiv. Analog `category_plugin_ids` fuer
        die Sets-Gruppe.
        """
        target = [p.strip().lower() for p in str(category_path or "").split("/")
                  if p.strip()]
        if not target:
            return []
        result: List[str] = []
        for s in sorted(self._sets, key=lambda x: str(
                x.get("display_name") or x.get("set_id") or "").lower()):
            parts = [p.lower() for p in self._set_category_parts(s)]
            if len(parts) >= len(target) and parts[:len(target)] == target:
                result.append(str(s.get("set_id") or ""))
        return result

    def plugin_category_path(self, plugin_id: str) -> str:
        """Aktueller Kategorie-Pfad eines Plugins (lesend, 18.01.03).

        Liefert den voll aufgeloesten Pfad (Override -> metadata['category'])
        slash-separiert OHNE '📁 '-Praefix (z.B. 'Swing Points/Geometrie');
        leer = Root-Ebene. Grundlage fuer die Ordner-Verschiebung und
        Rename-String-Replace im Orchestrator.
        """
        if not plugin_id:
            return ""
        plugin = self.get_plugin(plugin_id)
        parts = self._category_parts(plugin_id, plugin) if plugin else []
        return "/".join(parts)

    def category_service_plugin_ids(self, group: str,
                                    category_path: str) -> List[str]:
        """Alle plugin_ids unter einem Kategorie-Ordner (rekursiv, 18.01.03).

        Gruppenspezifische Aufloesung (L3):
          * group == GROUP_SETS    -> Sets unter dem Pfad
            (category_set_ids), dann alle plugin_ids ihrer Services
            (execution_order, dedupliziert, deterministisch).
          * group == GROUP_PLUGINS -> Plugins unter dem Pfad
            (category_plugin_ids).
        Leerer Pfad/leere Gruppe -> [] (defensiv). Wird von den Run-/Info-
        Aktionen des ServiceWindow und der Picker-Aufloesung genutzt.
        """
        if str(group or "") == str(self.GROUP_SETS):
            ids: List[str] = []
            for set_id in self.category_set_ids(category_path):
                definition = self.find_set(set_id) or {}
                services = definition.get("services") or {}
                order = definition.get("execution_order") \
                    or list(services.keys())
                for iid in order:
                    cfg = services.get(iid) or {}
                    pid = str(cfg.get("plugin_id") or iid)
                    if pid and pid not in ids:
                        ids.append(pid)
            return ids
        return self.category_plugin_ids(category_path)

    def _category_nodes(self, plugin_ids: List[str]) -> List[Dict[str, Any]]:
        """Baut die (ggf. verschachtelte) Kinderliste einer Plugin-Gruppe.

        Plugins mit Kategorienpfad werden in 📁-Ordner einsortiert; Plugins
        ohne Kategorie (bzw. Default 'General') bleiben auf oberster Ebene
        (K1). Blatt-Dicts unveraendert ({plugin_id, badge, last_execution}).
        Sortierung pro Ebene: Ordner vor Blaettern, alphabetisch (K8).
        """
        plugins = self.get_plugins()
        root: List[Dict[str, Any]] = []
        for pid in plugin_ids:
            plugin = plugins.get(pid)
            parts = self._category_parts(pid, plugin)
            leaf = {
                "plugin_id": pid,
                "badge": self.badge_for(pid),
                "last_execution": self.last_execution_date(pid),
            }
            self._insert_into_category_tree(root, parts, leaf)
        return self._sort_category_nodes(root)

    def build_tree(self) -> List[Dict[str, Any]]:
        """Baut die vollstaendige Hierarchie fuer das 2-Spalten-MasterTree.

        17.01.01: NUR noch 2 Root-Gruppen – die ehemalige Gruppe
        '⚡ Standalone Services' (GROUP_STANDALONE) entfaellt ersatzlos, da
        alle Plugins ueber metadata['category'] in Ordner einsortiert werden.
        Root-Label kompakt: '📁 Sets' und '📦 Services'.

        Rueckgabe (pro Gruppe ein Dict):
            [{"group": "sets", "label": "📁 Sets", "children": [
                 {"set_id": ..., "display_name": ..., "definition": {...},
                  "services": [{"instance_id": ..., "plugin_id": ...,
                                "badge": ...}, ...]}, ...]},
             {"group": "plugins", "label": "📦 Services",
              "children": [Blatt- und/oder Ordner-Knoten ...]}]

        Deterministisch sortiert (Sets nach display_name; Plugins/Ordner
        alphabetisch, 16.08 K8). Seit 16.08 (K2) sind die Kinder der
        Plugin-Gruppen eine Mischung aus flachen Blatt-Dicts
        ({plugin_id, badge, last_execution}) und verschachtelten
        Ordner-Dicts ({"group": GROUP_CATEGORY, "label": "📁 <Name>",
        "children": [...]} – rekursiv), gesteuert ueber das Metadaten-Feld
        `category` der Plugins (K1). Seit 18.01.03 gilt dieselbe Ordner-
        Mechanik auch fuer die Sets-Gruppe: Set-Definitionen mit dem
        optionalen Feld `category` werden in identische Ordner-Dicts
        einsortiert (K2/K8/K9 analog), Sets ohne Kategorie bleiben flache
        Blaetter auf oberster Ebene. Seit 18.01.03 (E3-revidiert) werden
        zusaetzlich benutzererzeugte (ggf. leere) Ordner aus global_settings
        (Key 'tree_folders_<group>') in die Gruppen-Kinder eingemischt –
        leere Ordner bleiben dadurch ueber Refreshs erhalten und
        verschwinden NUR bei manueller Loeschung im Kontextmenue.
        """
        sets = sorted(self._sets,
                      key=lambda s: str(s.get("display_name") or s.get("set_id") or "").lower())
        # 18.01.03: Sets-Kategorien (Dynamic Category Trees fuer GROUP_SETS).
        # Set-Definitionen mit `category`-Pfad werden in 📁-Ordner einsortiert
        # (rekursiv, gleiche K2/K8/K9-Regeln wie die Plugins); ohne Kategorie
        # bleiben sie flache Blaetter auf oberster Ebene. Der MasterTree
        # baut daraus identische Ordner-Knoten wie bei den Plugins
        # (gruppen-agnostische Rekursion).
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
            self._insert_set_into_category_tree(
                set_nodes, self._set_category_parts(s), {
                    "set_id": s.get("set_id"),
                    "display_name": s.get("display_name") or s.get("set_id") or "Unbenannt",
                    "definition": s,
                    "services": service_nodes,
                })
        set_nodes = self._sort_category_nodes(set_nodes)

        # 16.08 (K2/K8) + 17.01.01: EINE kategorisierte Services-Gruppe –
        # Plugins mit `category`-Metadatum werden in 📁-Ordner verschachtelt
        # (K1), ohne Kategorie bleiben sie flache Blaetter auf oberster Ebene.
        # Die fruehere Standalone-Gruppe (separate Knoten) ist entfallen.
        plugin_nodes = self._category_nodes(sorted(self.get_plugins().keys()))

        # 18.01.03 (E3-revidiert): Persistierte benutzererzeugte (ggf. leere)
        # Ordner in die Gruppen-Kinder einmischen – leere Ordner verschwinden
        # damit NICHT beim Refresh, sondern nur bei manueller Loeschung
        # (Kontextmenue 'Ordner löschen'). Bereits vorhandene Ordner (aus
        # echten Blatt-Kategorien) werden wiederverwendet (kein Duplikat).
        for group, nodes in ((self.GROUP_SETS, set_nodes),
                             (self.GROUP_PLUGINS, plugin_nodes)):
            for path in self._empty_folder_paths.get(group, []) or []:
                parts = [p.strip() for p in str(path or "").split("/")
                         if p.strip()]
                if parts:
                    self._ensure_category_path(nodes, parts)
        set_nodes = self._sort_category_nodes(set_nodes)
        plugin_nodes = self._sort_category_nodes(plugin_nodes)

        return [
            {"group": self.GROUP_SETS, "label": "📁 Sets",
             "children": set_nodes},
            {"group": self.GROUP_PLUGINS, "label": "📦 Services",
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
