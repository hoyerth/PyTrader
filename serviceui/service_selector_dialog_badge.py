"""
service_selector_dialog_badge.py - Badge-Bar, TF-Events, Model-Data-Changed, Entries-fuer-Scope

23.08 God-File-Split (15.08.2026): Aus serviceui/service_selector_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceSelectorDialog-
Klasse als Mixin (Klasse ServiceSelectorDialogBadgeMixin).
"""

from typing import (
    Dict,
    List,
    Optional,
    Tuple,
)

from analytics.engine.feature_store_reader import (
    FeatureStoreReader,
)

from analytics.engine.service_models import (
    generate_instance_hash,
)

from serviceui.master_tree import (
    TYPE_CATEGORY,
    TYPE_CLONE,
    TYPE_PLUGIN,
    TYPE_SERVICE,
    TYPE_SET,
)

class ServiceSelectorDialogBadgeMixin:

    def closeEvent(self, event) -> None:
        """12.08.2026 (WAL-Korruption beim App-Exit): Laufenden
        ServiceRunWorker sauber stoppen, bevor der Dialog schliesst."""
        worker = getattr(self, "_run_worker", None)
        if worker is not None and worker.isRunning():
            worker.stop()
            worker.wait(5000)
        super().closeEvent(event)

    def _on_tf_started(self, tf: str) -> None:
        """Hebt den gerade laufenden Timeframe im Pill-Strip blau hervor."""
        self.badge_bar.set_running(tf)
        self.badge_bar.clear_error(tf)

    def _on_tf_finished(self, tf: str, stored: int, had_data: bool) -> None:
        """TF fertig: ohne OHLCV-Daten/Fehler rot markieren, sonst neutral."""
        if had_data:
            self.badge_bar.clear_error(tf)
        else:
            self.badge_bar.set_error(tf)
        self.badge_bar.set_running(None)

    def _resolve_badge_scope(self, node_type: str, set_id: str,
                             service_id: str,
                             plugin_id: str) -> Tuple[Optional[str],
                                                      Optional[str]]:
        """Ermittelt (plugin_id, instance_hash) fuer den Pill-Strip.

        12.08.2026 (User-Meldung 'Data only loeschen'): Der Pill-Strip wird
        VARIANTEN-GENAU geladen. Clone-Knoten tragen den instance_hash im
        service_id-Slot (MasterTree._emit_selection_details, 20.04 Q7);
        Set-/Service-Zeilen liefern den Hash der ersten Instanz aus der
        Set-Definition (cfg['instance_hash'], sonst Params-only-Hash).
        """
        if plugin_id:
            h = str(service_id) if node_type == TYPE_CLONE else None
            return str(plugin_id), (h or None)
        if node_type == TYPE_SERVICE:
            if set_id and service_id:
                cfg = self.model.find_service(set_id, service_id) or {}
                pid = str(cfg.get("plugin_id") or service_id)
                h = str(cfg.get("instance_hash") or "") or None
                if not h and pid:
                    try:
                        h = generate_instance_hash(
                            pid, cfg.get("params") or {})
                    except Exception:
                        h = None
                return pid, h
            return (str(service_id) if service_id else None), None
        if node_type == TYPE_SET and set_id:
            definition = self.model.find_set(set_id) or {}
            order = list(definition.get("execution_order") or [])
            services = dict(definition.get("services") or {})
            for iid in order:
                cfg = services.get(iid) or {}
                pid = str(cfg.get("plugin_id") or iid)
                if pid:
                    h = str(cfg.get("instance_hash") or "") or None
                    if not h:
                        try:
                            h = generate_instance_hash(
                                pid, cfg.get("params") or {})
                        except Exception:
                            h = None
                    return pid, h
        return None, None

    def _refresh_badge_bar(self, plugin_id: Optional[str] = None,
                           instance_hash: Optional[str] = None) -> None:
        """Laedt die TF-Status-Pills fuer den angegebenen Service neu
        (FeatureStoreReader.fetch_service_tf_status).

        12.08.2026 (User-Meldung 'Data only loeschen'): Mit `instance_hash`
        wird der Pill-Strip VARIANTEN-GENAU geladen (nur die TFs dieser
        Variante); ohne Hash bleibt das service-weite Verhalten erhalten."""
        if plugin_id:
            self._badge_plugin_id = plugin_id
        if instance_hash:
            self._badge_instance_hash = instance_hash
        pid = self._badge_plugin_id
        if not pid:
            self.badge_bar.clear()
            return
        h = self._badge_instance_hash or None
        try:
            status = FeatureStoreReader().fetch_service_tf_status(pid, h)
        except Exception:
            status = {}
        self.badge_bar.update_status(status)

    def _on_model_data_changed(self) -> None:
        """Modell-Refresh (EventBus -> data_changed): Panel neu aufbauen.

        Nach einem Baum-Neuaufbau (neues Set, Ausfuehrungsdatum, ...) wird
        das Panel mit dem zuletzt GEKLICKTEN Scope nachgezogen; ohne Scope
        (noch nichts angeklickt) bleibt das Panel leer.
        """
        scope = getattr(self, "_last_scope", None)
        if scope:
            self._on_tree_selection_details(*scope)
        else:
            self._rebuild_param_panel([])

    def _entries_for_scope(self, node_type: str, set_id: str, service_id: str,
                           plugin_id: str) -> List[Dict[str, str]]:
        """Panel-Entries fuer die geklickte Tree-Zeile (service_win-Muster).

        Returns:
            Liste von {"node_type", "set_id", "instance_id", "plugin_id"} –
            leer fuer Zeilen ohne Parameter-Anzeige (Gruppen, leere Auswahl).
            Kategorie-Ordner (18.01.01, E-4) liefern die Elemente des Pfads
            rekursiv; 18.01.03 (L3) unterscheidet dabei ueber die im set_id-
            Slot mitgelieferte Gruppe: Sets-Ordner -> Set-Service-Entries
            aller Sets unter dem Pfad, Plugins-Ordner -> Plugin-Entries
            (category_plugin_ids).
        """
        if node_type == TYPE_CATEGORY:
            if str(set_id or "") == str(self.model.GROUP_SETS):
                entries: List[Dict[str, str]] = []
                for set_id_under in self.model.category_set_ids(
                        plugin_id or ""):
                    definition = self.model.find_set(set_id_under) or {}
                    services = definition.get("services") or {}
                    order = definition.get("execution_order") \
                        or list(services.keys())
                    for iid in order:
                        cfg = services.get(iid) or {}
                        if not isinstance(cfg, dict):
                            continue
                        entries.append({
                            "node_type": TYPE_SERVICE,
                            "set_id": str(set_id_under),
                            "instance_id": str(iid),
                            "plugin_id": str(cfg.get("plugin_id") or iid),
                        })
                return entries
            entries: List[Dict[str, str]] = []
            for pid in self.model.category_plugin_ids(plugin_id or ""):
                entries.append({
                    "node_type": TYPE_PLUGIN,
                    "set_id": "",
                    "instance_id": "",
                    "plugin_id": pid,
                })
            return entries
        if node_type in (TYPE_PLUGIN, TYPE_CLONE) and plugin_id:
            # 20.04 (Q7): Clone-Zeilen zeigen wie Plugin-Zeilen den
            # Standalone-Service (feature_id = plugin_id des Parents).
            # 10.08.2026 (Bugfix, Varianten-Params): Zusaetzlich werden die
            # presetspezifischen Parameter (indicator_presets) mitgegeben -
            # das Panel zeigt die EIGENEN Parameter der Variante (service_id
            # traegt hier den instance_hash, MasterTree._emit_selection_-
            # details), nicht die globalen Standalone-Params.
            if node_type == TYPE_CLONE:
                preset = self._find_preset_for_hash(
                    plugin_id, service_id)
                if preset is not None:
                    return [{
                        "node_type": TYPE_PLUGIN,
                        "set_id": "",
                        "instance_id": "",
                        "plugin_id": str(plugin_id),
                        "preset_params": dict(preset.get("params") or {}),
                        "preset": preset,
                    }]
            return [{
                "node_type": TYPE_PLUGIN,
                "set_id": "",
                "instance_id": "",
                "plugin_id": str(plugin_id),
            }]
        if node_type in (TYPE_SET, TYPE_SERVICE) and set_id:
            definition = self.model.find_set(set_id) or {}
            services = definition.get("services") or {}
            order = definition.get("execution_order") or list(services.keys())
            entries: List[Dict[str, str]] = []
            for iid in order:
                cfg = services.get(iid) or {}
                if not isinstance(cfg, dict):
                    continue
                entries.append({
                    "node_type": TYPE_SERVICE,
                    "set_id": str(set_id),
                    "instance_id": str(iid),
                    "plugin_id": str(cfg.get("plugin_id") or iid),
                })
            return entries
        return []
