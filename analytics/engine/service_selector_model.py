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

from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, Signal

from config.event_bus import event_bus
from analytics.engine.service_models import generate_instance_hash


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
        # 10.08.2026 (Varianten-Ausfuehrungsdatum): Datum der letzten
        # Ausfuehrung je (feature_id, instance_hash) – Grundlage der
        # MasterTree-Varianten-Anzeige '<Preset> (DD.MM.JJ)'. Quelle:
        # FeatureStoreReader.fetch_last_execution_dates_by_hash().
        self._last_execution_dates_by_hash: Dict[str, Dict[str, str]] = {}
        # 11.08.2026 (Bugfix Runde 16, Dropdown-Anzeige): Datum+Uhrzeit der
        # letzten Ausfuehrung je (feature_id, instance_hash) – Grundlage der
        # Feld-Dropdown-Anzeige '{Name} / {Preset} / DD.MM.JJ HH:MM'.
        # Quelle: FeatureStoreReader.fetch_last_execution_datetimes_by_hash().
        self._last_execution_datetimes_by_hash: Dict[str, Dict[str, str]] = {}
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
        # 20.04 (Q7): Presets/Clones je Plugin (plugin_id.lower() -> Liste
        # von {"preset_name", "params", "instance_hash", "is_archived",
        # "doc_log"}). Quelle: indicator_presets
        # (StateManager.list_plugin_presets). Nur
        # Plugins MIT Presets erscheinen als Parent-Knoten mit Clone-Kindern
        # im MasterTree (Services-Gruppe); Plugins ohne Presets bleiben
        # flache Blaetter (Zero-Regression). Wird in refresh() geladen.
        self._plugin_presets: Dict[str, List[Dict[str, Any]]] = {}

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
        # 10.08.2026 (Varianten-Ausfuehrungsdatum): Datum der letzten
        # Ausfuehrung je (feature_id, instance_hash) – Grundlage der
        # MasterTree-Varianten-Anzeige '<Preset> (DD.MM.JJ)'. Wird NACH den
        # Plugin-Ausfuehrungsdaten gelesen, damit _load_plugin_presets() die
        # Hash-Daten je Clone mitgeben kann.
        self._last_execution_dates_by_hash = self._load_last_execution_dates_by_hash()
        # 11.08.2026 (Bugfix Runde 16, Dropdown-Anzeige): Datum+Uhrzeit der
        # letzten Ausfuehrung je (feature_id, instance_hash) – Grundlage der
        # Feld-Dropdown-Anzeige '{Name} / {Preset} / DD.MM.JJ HH:MM'.
        self._last_execution_datetimes_by_hash = (
            self._load_last_execution_datetimes_by_hash())
        # 18.01.03 (E1): Kategorie-Overrides (plugin_category_<pid>) laden –
        # einmalig pro Refresh, damit _category_parts() ohne DB-Zugriff
        # auswertet (Baum-Aufbau bleibt rein lesend aus dem RAM).
        self._plugin_category_overrides = self._load_plugin_category_overrides()
        # 18.01.03 (E3-revidiert): Persistierte benutzererzeugte Ordner je
        # Gruppe laden (tree_folders_<group>); build_tree() mischt sie in
        # die Gruppen-Kinder ein (leere Ordner bleiben ueber Refreshs).
        self._empty_folder_paths = self._load_empty_folders()
        # 20.04 (Q7): Presets/Clones je Plugin laden (indicator_presets via
        # StateManager) – Grundlage der Parent-Child-Clone-Ansicht.
        self._plugin_presets = self._load_plugin_presets()
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

    def _load_plugin_presets(self) -> Dict[str, List[Dict[str, Any]]]:
        """Laedt die Presets/Clones aller Plugins (20.04, Q7).

        Quelle: indicator_presets (StateManager.list_plugin_presets,
        plugin_id-Verknuepfung). Der instance_hash wird fuer jedes Preset
        deterministisch aus `generate_instance_hash(plugin_id, params)`
        berechnet (Q2/Q4: ohne lookback, Typ-Sanitizer + sort_keys). Ein
        Preset gilt als archiviert, wenn `is_active_batch = False` (Q7:
        Archivierung eines Presets => is_active_batch = False; die Scans
        isolieren diese Presets). Rueckgabe: plugin_id.lower() -> Liste
        von {"preset_name", "params", "instance_hash", "is_archived",
        "doc_log"}.
        Defensiv: Fake-/Alt-StateManager ohne list_plugin_presets liefern
        leere Dicts (kein Baum-Rendering, keine Regression in Tests).
        """
        result: Dict[str, List[Dict[str, Any]]] = {}
        try:
            for pid in sorted(self.get_plugins().keys()):
                raw = self.state_manager.list_plugin_presets(pid)
                if not raw:
                    continue
                clones: List[Dict[str, Any]] = []
                for p in raw or []:
                    if not isinstance(p, dict):
                        continue
                    params = p.get("params") or {}
                    instance_hash = generate_instance_hash(pid, params)
                    per_hash = self._last_execution_dates_by_hash.get(
                        str(pid).lower(), {}) or {}
                    clones.append({
                        "preset_name": str(p.get("preset_name") or "Default"),
                        "params": params,
                        "instance_hash": instance_hash,
                        "is_archived": not bool(p.get("is_active_batch")),
                        "doc_log": str(p.get("doc_log") or ""),
                        # 10.08.2026: Datum der letzten Ausfuehrung dieser
                        # Parameter-Variante (Feature-Store, Spalte
                        # instance_hash) – fuer die MasterTree-Anzeige
                        # '<Preset> (DD.MM.JJ)'. Fallback '--.--.--'.
                        "last_execution": per_hash.get(
                            instance_hash, "--.--.--"),
                    })
                if clones:
                    result[str(pid).lower()] = clones
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Plugin-Presets nicht lesbar: {e}")
        return result

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

    def last_execution_date_for_hash(
        self, plugin_id: str, instance_hash: str
    ) -> str:
        """Datum der letzten Ausfuehrung einer Parameter-Variante.

        10.08.2026 (Varianten-Ausfuehrungsdatum): Varianten/Clones haben
        EIGENE Feature-Store-Rows (Spalte instance_hash). Formatiert als
        'DD.MM.JJ' – Fallback '--.--.--' ohne Eintraege (bzw. ohne
        instance_hash). Rueckgabewert ohne Klammern (MasterTree-Wrapper).
        """
        if not plugin_id or not instance_hash:
            return "--.--.--"
        per_hash = self._last_execution_dates_by_hash.get(
            str(plugin_id).lower(), {}) or {}
        return per_hash.get(str(instance_hash), "--.--.--")

    def _load_last_execution_dates_by_hash(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """Liest die Varianten-Ausfuehrungsdaten je (feature_id, hash).

        10.08.2026: Delegate an den FeatureStoreReader
        (fetch_last_execution_dates_by_hash). Defensiv: Fehler -> leer
        (Clones zeigen dann den Fallback '(--.--.--)').
        """
        try:
            raw = self.feature_store_reader.fetch_last_execution_dates_by_hash() or {}
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Varianten-Ausfuehrungsdaten "
                  f"nicht lesbar: {e}")
            return {}
        return {str(k).lower(): v for k, v in raw.items()}

    def _load_last_execution_datetimes_by_hash(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """Liest die Varianten-Ausfuehrungsdaten je (feature_id, hash) mit Uhrzeit.

        11.08.2026 (Bugfix Runde 16, Dropdown-Anzeige): Delegate an den
        FeatureStoreReader (fetch_last_execution_datetimes_by_hash) - die
        Feld-Dropdown-Anzeige '{Name} / {Preset} / DD.MM.JJ HH:MM' braucht
        Datum+Uhrzeit der letzten Ausfuehrung. Defensiv: Fehler -> leer
        (Eintraege zeigen dann keinen Datums-Anhang).
        """
        try:
            raw = self.feature_store_reader.fetch_last_execution_datetimes_by_hash() or {}
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Varianten-Ausfuehrungsdaten "
                  f"(Datum+Uhrzeit) nicht lesbar: {e}")
            return {}
        return {str(k).lower(): v for k, v in raw.items()}

    def last_execution_datetime_for_hash(
        self, plugin_id: str, instance_hash: str
    ) -> str:
        """Datum+Uhrzeit der letzten Ausfuehrung einer Parameter-Variante.

        11.08.2026 (Bugfix Runde 16, Dropdown-Anzeige): Format 'DD.MM.JJ HH:MM'
        (z. B. '23.04.26 22:14') - Fallback '--.--.-- --:--' ohne Eintraege
        (bzw. ohne instance_hash). Rein lesend aus dem Refresh-Zustand.
        """
        if not plugin_id or not instance_hash:
            return "--.--.-- --:--"
        per_hash = self._last_execution_datetimes_by_hash.get(
            str(plugin_id).lower(), {}) or {}
        return per_hash.get(str(instance_hash), "--.--.-- --:--")

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
    # 18.01.02 (E6): Die Baum-Konstruktions-/Aufloesungslogik ist in
    # `analytics/engine/tree_builder.py` ausgelagert (reine Modul-Funktionen,
    # keine Zirkularitaet). Dieses Modell bleibt die oeffentliche API und
    # delegiert hierher (dünne Wrapper).

    @staticmethod
    def _cat_key(label: str) -> str:
        """Case-insensitiver Sortier-/Vergleichsschluessel eines Ordners.

        Delegation an tree_builder._cat_key (18.01.02 E6).
        """
        from analytics.engine.tree_builder import _cat_key as _tb_cat_key
        return _tb_cat_key(label)

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
        from analytics.engine.tree_builder import category_plugin_ids
        return category_plugin_ids(self.get_plugins(),
                                   self._plugin_category_overrides,
                                   category_path)

    def category_set_ids(self, category_path: str) -> List[str]:
        """Alle set_ids unter einem Kategorie-Pfad (rekursiv, 18.01.03).

        Liefert deterministisch (Set-Reihenfolge = display_name) alle Sets,
        deren `category`-Pfad mit `category_path` beginnt – d.h. auch Sets in
        UNTER-Ordnern (z.B. Pfad 'Swing Points' liefert auch Sets aus
        'Swing Points/Geometrie'). Pfad-Format: slash-separiert OHNE
        '📁 '-Praefixe, case-insensitiv. Analog `category_plugin_ids` fuer
        die Sets-Gruppe.
        """
        from analytics.engine.tree_builder import category_set_ids
        return category_set_ids(self._sets, category_path)

    def plugin_category_path(self, plugin_id: str) -> str:
        """Aktueller Kategorie-Pfad eines Plugins (lesend, 18.01.03).

        Liefert den voll aufgeloesten Pfad (Override -> metadata['category'])
        slash-separiert OHNE '📁 '-Praefix (z.B. 'Swing Points/Geometrie');
        leer = Root-Ebene. Grundlage fuer die Ordner-Verschiebung und
        Rename-String-Replace im Orchestrator.
        """
        from analytics.engine.tree_builder import plugin_category_path
        plugin = self.get_plugin(plugin_id)
        return plugin_category_path(plugin_id, plugin,
                                    self._plugin_category_overrides)

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
        from analytics.engine.tree_builder import category_service_plugin_ids
        return category_service_plugin_ids(group, self._sets,
                                           self.get_plugins(),
                                           self._plugin_category_overrides,
                                           category_path)

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
        alphabetisch, 16.08 K8). Die Baum-Logik selbst ist seit 18.01.02 (E6)
        in `analytics/engine/tree_builder.build_tree` ausgelagert – dieses
        Modell berechnet lediglich die Badges/Ausfuehrungsdaten und delegiert.
        """
        from analytics.engine.tree_builder import build_tree as _tb_build_tree
        plugins = self.get_plugins()
        badges: Dict[str, str] = {pid: self.badge_for(pid) for pid in plugins}
        last_executions: Dict[str, str] = {
            pid: self.last_execution_date(pid) for pid in plugins}
        # 20.04 (Q7): Presets/Clones je Plugin durchreichen – Plugins MIT
        # Presets werden als Parent-Knoten mit Clone-Kindern gerendert,
        # archivierte Clones (is_archived) in den '📁 Archiv'-Ordner.
        return _tb_build_tree(self._sets, plugins,
                              self._plugin_category_overrides,
                              self._empty_folder_paths,
                              badges, last_executions,
                              presets=self._plugin_presets)

    def plugin_presets(self) -> Dict[str, List[Dict[str, Any]]]:
        """Presets/Clones je Plugin (20.04, Q7) – lesend fuer Widgets/Tests.

        Liefert plugin_id.lower() -> Liste von {"preset_name", "params",
        "instance_hash", "is_archived", "doc_log"} (Quelle:
        indicator_presets). Wird in refresh() aktualisiert; leere Dicts
        bei Fake-/Alt-StateManagern.
        """
        return dict(self._plugin_presets)

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

    # ------------------------------------------------------------------
    # 20.01 (E5): Fault-Tolerant Resolver fuer persistierte feature_ids
    # ------------------------------------------------------------------
    def resolve_valid_feature_ids(
        self, feature_ids: List[str]
    ) -> Tuple[List[str], List[str]]:
        """Prueft feature_ids gegen die PluginRegistry (Phase 20.01, E5).

        Wird vom AnalyticsViewModel beim Profil-/Workspace-Restore genutzt,
        um entfernte/umbenannte Plugins (fehlende feature_ids) zu isolieren:
        die validen IDs bleiben aktiv, die fehlenden werden gemeldet
        (missing_services_detected -> Warn-Label, Graceful Degradation).

        Returns:
            (valid_ids, missing_ids): gueltige Plugin-IDs (case-insensitiv,
            dedupliziert, Reihenfolge erhalten) und nicht (mehr) registrierte
            IDs. `'native'` ist der Feature-Store-Sentinel des nativen
            Feature-Builder-Pfads (kein Plugin) und gilt als fehlend (B7) –
            der ServiceSelectorDialog emittiert ausschliesslich plugin_ids.
        """
        valid: List[str] = []
        missing: List[str] = []
        seen: Set[str] = set()
        for fid in feature_ids or []:
            key = str(fid or "").strip()
            if not key or key.lower() in seen:
                continue
            seen.add(key.lower())
            if self.get_plugin(key) is not None:
                valid.append(key)
            else:
                missing.append(key)
        return valid, missing
