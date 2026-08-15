"""
master_tree_build.py - Baum-Aufbau, Build-Items, Labels, Modus-Suffix, Badges

23.06 God-File-Split (15.08.2026): Aus serviceui/master_tree.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der MasterTree-
Klasse als Mixin (Klasse MasterTreeBuildMixin).
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from PySide6.QtCore import (
    Qt,
)

from PySide6.QtWidgets import (
    QTreeWidgetItem,
)

from analytics.engine.service_models import (
    generate_instance_hash,
)

from serviceui.master_tree_constants import (
    ROLE_ARCHIVED,
    ROLE_INSTANCE_HASH,
    ROLE_INSTANCE_ID,
    ROLE_NODE_TYPE,
    ROLE_PLUGIN_ID,
    ROLE_PRESET_NAME,
    ROLE_SET_ID,
    TYPE_CATEGORY,
    TYPE_CLONE,
    TYPE_GROUP,
    TYPE_PLUGIN,
    TYPE_SERVICE,
    TYPE_SET,
    TreeItemIterator,
    _expandable_label,
    isValid,
)

class MasterTreeBuildMixin:

    # -------------------------------------------------------------------------
    # Befuellung aus dem Modell
    # -------------------------------------------------------------------------

    def _populate(self) -> None:
        """Baut den Baum aus model.build_tree() neu auf (deterministisch)."""
        current = self._safe_current_selection()
        # 18.01.03 (Bugfix 08.08.2026): Expansion-Zustand VOR dem Neuaufbau
        # sichern – der Baum soll nach Ordner-Erstellung/-Verschiebung NICHT
        # zusammenklappen (_collect_expanded_state liest den IST-Baum).
        expanded = self._collect_expanded_state()
        self.blockSignals(True)
        self.clear()
        try:
            for group in self.model.build_tree():
                children = group.get("children", [])
                label = _expandable_label(str(group.get("label", "")),
                                          bool(children), False)
                group_item = QTreeWidgetItem([label])
                group_item.setData(0, ROLE_NODE_TYPE, TYPE_GROUP)
                group_item.setData(0, ROLE_SET_ID, group.get("group", ""))
                group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
                for child in children:
                    item = self._build_child_item(group.get("group"), child)
                    if item is not None:
                        group_item.addChild(item)
                self.addTopLevelItem(group_item)
                group_item.setExpanded(True)
        except Exception as e:
            print(f"WARN [MasterTree] Baum-Aufbau fehlgeschlagen: {e}")
        # 18.01.03 (Bugfix 08.08.2026): Expansion unter blockSignals
        # wiederherstellen (keine Signal-Seiteneffekte; die '>'/'⌄'-Labels
        # refresht der anschliessende Label-Block explizit).
        self._apply_expanded_state(expanded)
        self.blockSignals(False)
        # Bugfix 04.08.2026 (Punkt 2/3): unter blockSignals feuern die
        # itemExpanded/itemCollapsed-Signale nicht – die Labels der
        # Top-Level-Knoten werden hier explizit auf den IST-Zustand gebracht
        # ('⌄' wenn expandiert, '>' wenn zugeklappt).
        try:
            for i in range(self.topLevelItemCount()):
                item = self.topLevelItem(i)
                if item is not None and isValid(item):
                    self._refresh_expand_label(item)
        except (RuntimeError, AttributeError):
            pass
        # Aktuelle Auswahl nach Refresh wiederherstellen (falls noch vorhanden)
        try:
            self._restore_selection(current)
        except Exception as e:
            print(f"WARN [MasterTree] Auswahl-Restore fehlgeschlagen: {e}")
        # Bugfix 05.08.2026: Info-Buttons (Spalte 1) NACH dem vollstaendigen
        # Baum-Aufbau anhaengen – setItemWidget() verlangt, dass das Item
        # bereits Teil des TreeWidgets ist (sonst kein sichtbarer Button).
        self._attach_item_buttons()
        # 15.03-E (Multi-Select): _checked_items mit dem IST-Baum abgleichen
        # (stale Keys geloeschter Services/Plugins entfernen).
        self._sync_checked_from_tree()
        # Phase 15 (Dirty-State): Sternchen-Markierungen ungespeicherter
        # Parameter-Aenderungen nach einem Neuaufbau wieder anwenden
        # (data_changed -> _populate wuerde sie sonst verlieren). Waehrend
        # dessen ist die Checkbox-Verarbeitung gesperrt (die Text-Aenderung
        # wuerde sonst ein spurious checked_changed emittieren).
        self._updating_checks = True
        try:
            for iid in list(getattr(self, "_dirty_instance_ids", set())):
                self._apply_dirty_label(iid, True)
        finally:
            self._updating_checks = False
        # 18.01.03 (E3-revidiert): Leere Ordner kommen jetzt aus dem Modell
        # (build_tree mischt die persistierten tree_folders_<group>-Pfade
        # ein) – ein separater UI-Zustand ist nicht mehr noetig.
        pass
        # Runde 9 (Bug 1): Pending-Haken aus set_checked_feature_ids (wurde
        # auf einem noch leeren Baum aufgerufen, z.B. Picker-Oeffnen vor dem
        # ersten data_changed) jetzt auf den fertigen Baum anwenden. Emittiert
        # KEIN checked_changed (Bug-5-Fix), damit der Restore-Filter nicht
        # ueberschrieben wird.
        pending = getattr(self, "_pending_feature_ids", None)
        if pending is not None:
            pending_hashes = getattr(self, "_pending_instance_hashes", None)
            self._pending_feature_ids = None
            self._pending_instance_hashes = None
            self.set_checked_feature_ids(pending, pending_hashes)

    def _safe_current_selection(self) -> Dict[str, str]:
        """Liess die aktuelle Auswahl defensiv (isValid-Guard gegen zerstoerte
        Items, z.B. nach einem zwischenzeitlichen clear())."""
        try:
            item = self.currentItem()
            if item is None or not isValid(item):
                return {"set_id": "", "service_id": ""}
            node_type = item.data(0, ROLE_NODE_TYPE)
            set_id = str(item.data(0, ROLE_SET_ID) or "")
            if node_type == TYPE_SERVICE:
                return {"set_id": set_id,
                        "service_id": str(item.data(0, ROLE_INSTANCE_ID) or "")}
            if node_type == TYPE_SET:
                return {"set_id": set_id, "service_id": ""}
            return {"set_id": "", "service_id": ""}
        except (RuntimeError, AttributeError):
            return {"set_id": "", "service_id": ""}

    def _build_child_item(self, group: str,
                          child: Dict[str, Any]) -> Optional[QTreeWidgetItem]:
        """Erzeugt das Kind-Item fuer einen Knoten der Gruppe `group`.

        16.08 (K2/K3): Ordner-Knoten (group == GROUP_CATEGORY) werden
        rekursiv aufgebaut; Plugin-Blaetter in Ordnern nutzen weiterhin
        _build_plugin_item (Badge/Ausfuehrungsdatum unveraendert). Die
        Original-Gruppe (standalone/plugins) wird durch die Rekursion
        durchgereicht, damit ROLE_SET_ID der Blaetter stabil bleibt.
        """
        if isinstance(child, dict) and child.get("group") == self.model.GROUP_CATEGORY:
            return self._build_category_item(child, group)
        if group == self.model.GROUP_SETS:
            return self._build_set_item(child)
        # 17.01.01: GROUP_STANDALONE entfaellt ersatzlos – Plugin-Zeilen
        # existieren nur noch in GROUP_PLUGINS (Kategorien-Ordner inklusive).
        if group == self.model.GROUP_PLUGINS:
            return self._build_plugin_item(child, group)
        return None

    def _build_category_item(self, child: Dict[str, Any],
                             group: str) -> QTreeWidgetItem:
        """Erzeugt einen Ordner-Knoten (K3, 16.08).

        Nicht auswaehlbar, expandierbar, '📁 <Name>' im Label (aus dem
        Modell, K2-Format); Kinder rekursiv ueber _build_child_item.
        Ordner tragen KEINEN Info-Button (K5 – _attach_item_buttons
        ueberspringt TYPE_CATEGORY automatisch), keine Badges/Datum (K2)
        und sind im Checkbox-Modus nicht anhakbar (K4 – kein
        ItemIsUserCheckable). Die Selektion liefert fuer Ordner den
        Default-Pfad zurueck (K7).
        """
        label = _expandable_label(str(child.get("label") or "?"),
                                  bool(child.get("children")), False)
        cat_item = QTreeWidgetItem([label, ""])
        cat_item.setData(0, ROLE_NODE_TYPE, TYPE_CATEGORY)
        cat_item.setData(0, ROLE_SET_ID, str(child.get("label") or ""))
        # K3/K4: nicht auswaehlbar UND nicht anhakbar – Qt setzt
        # ItemIsUserCheckable standardmaessig, daher beide Flags entfernen.
        cat_item.setFlags(cat_item.flags()
                          & ~(Qt.ItemIsSelectable | Qt.ItemIsUserCheckable))
        for sub in child.get("children") or []:
            item = self._build_child_item(group, sub)
            if item is not None:
                cat_item.addChild(item)
        return cat_item

    def _build_set_item(self, child: Dict[str, Any]) -> QTreeWidgetItem:
        services = child.get("services", [])
        name = _expandable_label(str(child.get("display_name") or "Unbenannt"),
                                 bool(services), False)
        set_item = QTreeWidgetItem([name, ""])
        set_item.setData(0, ROLE_NODE_TYPE, TYPE_SET)
        set_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
        set_item.setToolTip(0, f"Service-Set: {child.get('set_id') or '?'}")
        # 20.04 (Q6): Archivierte Sets (is_archived=True) sind non-checkable
        # (Archive Safety) – sie liegen im '📁 Archiv'-Ordner der Sets-Gruppe.
        archived_set = bool(child.get("archived"))
        if archived_set:
            set_item.setData(0, ROLE_ARCHIVED, True)
        # 15.03-E (Multi-Select): Set-Knoten anhakbar – der Tri-State wird
        # NACH dem Anhaengen der Service-Kinder aus deren Zustaenden
        # abgeleitet (_apply_set_state).
        if self._checkable and not archived_set:
            set_item.setFlags(set_item.flags() | Qt.ItemIsUserCheckable)
        # Bugfix 05.08.2026: Gehoert das Set einem Indikator, traegt der
        # Info-Button (Spalte 1) den Tooltip 'aktiv/im <Indikator>' (siehe
        # _apply_set_badge und _attach_item_buttons).
        self._apply_set_badge(set_item, child.get("definition") or child)
        for svc in services:
            # Keine fuehrenden Leerzeichen im Text: die Einrueckung der
            # Untereintraege kommt aus setIndentation(LEVEL_INDENT).
            # 05.08.2026 (Ausfuehrungsdatum): Das Datum der letzten
            # Ausfuehrung (DD.MM.JJ, aus dem feature_store) haengt direkt am
            # Service-Namen: 'prox_1 (05.08.26)' – ohne Eintrag '(--.--.--)'.
            plugin_id = svc.get("plugin_id") or ""
            # 13.08.2026 (Runde 3): last_execution traegt seit dem
            # Datetime-Umbau 'DD.MM.JJ HH:MM' (Alt-Bestand 'DD.MM.JJ');
            # der gemeinsame Normalisierer wandelt Fallbacks in 'nie'.
            last_exec = self._fmt_last_exec(svc.get("last_execution"))
            # Runde 13b (Bugfix Dropdown-NoData): Set-Instanzen werden beim
            # regularen Hinzufuegen OHNE instance_hash in der Set-Definition
            # gespeichert (nur _duplicate_set_instance persistiert ihn) -
            # daraus blieb `instance_hashes` fuer Set-Instanzen leer und die
            # '(No Data)'-Varianten-Einschraenkung des Readers griff nicht
            # (Dropdown zeigte die erste/falsche Variante und ungecheckte
            # Instanzen). Hier wird der fehlende Hash on-the-fly aus den
            # Params berechnet (identisch zum Reader-Set-Pfad
            # generate_instance_hash(pid, params)) - heilt Alt-Bestand ohne
            # DB-Migration. (Block hierher vorgezogen, damit der Modus-
            # Suffix den Hash fuer die Store-Aufloesung nutzen kann.)
            svc_hash = str(svc.get("instance_hash") or "")
            if not svc_hash and self.model is not None:
                try:
                    cfg = self.model.find_service(
                        str(child.get("set_id") or ""),
                        str(svc.get("instance_id") or "")) or {}
                    svc_hash = generate_instance_hash(
                        str(cfg.get("plugin_id") or plugin_id),
                        cfg.get("params") or {}) or ""
                except Exception:
                    svc_hash = ""
            # 13.08.2026 (Runde 3, neue Benennung): Service OHNE
            # Varianten zeigt den AKTUELLEN Modus mit einem
            # Minuszeichen dahinter (Format 'swing_momentum -
            # MA_Peak_Hysteresis (13.08.26 10:48)' - die fruehere
            # Doppel-Anzeige '[Modus] Modus' entfaellt).
            mode = self._current_mode(plugin_id, svc.get("params"), svc_hash)
            mode_sfx = f" - {mode}" if mode else ""
            svc_label = f"{svc.get('instance_id')}{mode_sfx} ({last_exec})"
            # 20.04 (Q6): Einzeln archivierte Instanzen tragen im Archiv
            # eine Kennzeichnung (is_archived=True -> non-checkable).
            svc_archived = bool(svc.get("is_archived"))
            if svc_archived:
                svc_label = f"🔹 {svc_label}"
            svc_item = QTreeWidgetItem([svc_label, ""])
            svc_item.setData(0, ROLE_NODE_TYPE, TYPE_SERVICE)
            svc_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
            svc_item.setData(0, ROLE_INSTANCE_ID, svc.get("instance_id") or "")
            svc_item.setData(0, ROLE_PLUGIN_ID, plugin_id)
            svc_item.setData(0, ROLE_INSTANCE_HASH, svc_hash)
            if svc_archived or archived_set:
                svc_item.setData(0, ROLE_ARCHIVED, True)
            # 15.03-E (Multi-Select): Service-Knoten anhakbar – Zustand aus
            # _checked_items re-applizieren (bleibt ueber Neuaufbauten erhalten).
            if self._checkable and not svc_archived and not archived_set:
                svc_item.setFlags(svc_item.flags() | Qt.ItemIsUserCheckable)
                key = (TYPE_SERVICE,
                       str(child.get("set_id") or ""),
                       str(svc.get("instance_id") or ""),
                       svc_hash)
                state = (Qt.Checked if key in self._checked_items
                         else Qt.Unchecked)
                svc_item.setData(0, Qt.CheckStateRole, state)
            self._apply_badge(
                svc_item, plugin_id, svc.get("badge") or "",
                params=svc.get("params"))
            set_item.addChild(svc_item)
        if self._checkable:
            self._apply_set_state(set_item)
        return set_item

    @staticmethod
    def _mode_suffix(plugin_id: str,
                     params: Optional[Dict[str, Any]] = None) -> str:
        """'[{Modus}]'-Suffix fuer MasterTree-Labels (13.08.2026, Punkt 6, F6).

        Nur fuer Multi-Modus-Services: parameter_schema['mode']['options']
        enthaelt MEHR ALS EINEN Eintrag (z. B. srv_swing_momentum mit
        MA_Peak_Hysteresis/MA_Slope_Change/Chande_Kroll_Ratchet). Ein-
        Modus-Services bleiben ohne Suffix (kein Rauschen im Baum). Der
        Modus kommt aus den params der Instanz (Clone/Set-Service) bzw.
        aus dem Schema-Default (flache Plugin-Zeile ohne eigene params).
        Rein lesend (PluginRegistry-Singleton), Fehler defensiv leer.
        """
        try:
            from analytics.features.feature_builder import PluginRegistry
            reg = PluginRegistry()
            plugins = getattr(reg, "plugins", None) or {}
            pid_l = str(plugin_id or "").strip().lower()
            plugin = None
            for k, v in plugins.items():
                if str(k).strip().lower() == pid_l:
                    plugin = v
                    break
            if plugin is None:
                return ""
            schema = getattr(plugin, "parameter_schema", None) or {}
            mode_cfg = schema.get("mode") or {}
            options = [str(o).strip() for o in (mode_cfg.get("options") or [])
                       if str(o).strip()]
            if len(options) <= 1:
                return ""
            mode = ""
            if isinstance(params, dict):
                mode = str(params.get("mode") or "").strip()
            if not mode:
                mode = str(mode_cfg.get("default") or "").strip()
            return f" [{mode}]" if mode else ""
        except Exception:
            return ""

    def _current_mode(
        self,
        plugin_id: str,
        params: Optional[Dict[str, Any]] = None,
        instance_hash: Optional[str] = None,
    ) -> str:
        """AKTUELLER Modus eines Multi-Modus-Services (13.08.2026, R3).

        Aufloesung in Reihenfolge: params['mode'] -> Feature-Store je
        instance_hash (source_mode der letzten Ausfuehrung) ->
        Plugin-Fallback (erster bekannter Store-Modus) -> Schema-Default.
        Ein-Modus-Services / Services ohne Modus-Schema liefern '' (kein
        Suffix, kein Rauschen im Baum). Die Formatierung (dash/bracket)
        uebernimmt der Aufrufer. Rein lesend, Fehler defensiv.
        """
        try:
            base = self._mode_suffix(plugin_id, params)
            if not base:
                return ""
            mode = ""
            if isinstance(params, dict):
                mode = str(params.get("mode") or "").strip()
            if not mode and instance_hash and self.model is not None:
                try:
                    mode = str(
                        self.model.source_mode_for_hash(plugin_id, instance_hash)
                        or "").strip()
                except Exception:
                    mode = ""
            # Flache Standalone-Services (ohne Clones) tragen im Tree keinen
            # instance_hash - hier faellt die Aufloesung auf den Plugin-Fallback
            # zurueck (erster bekannter Store-Modus des Plugins).
            if not mode and not instance_hash and self.model is not None:
                try:
                    mode = str(
                        self.model.source_mode_for_plugin(plugin_id)
                        or "").strip()
                except Exception:
                    mode = ""
            if not mode:
                # Fallback: der Schema-Default gilt als aktueller Modus,
                # solange weder Config noch Store einen echten liefern
                # (z. B. nie gelaufene Variante).
                mode = str(base).strip(" []")
            return mode
        except Exception:
            return ""

    @staticmethod
    def _fmt_last_exec(value: Any) -> str:
        """Normalisiert den Ausfuehrungszeitpunkt eines Baum-Knotens.

        Akzeptiert 'DD.MM.JJ' (Alt-Bestand) und 'DD.MM.JJ HH:MM' (neu);
        leere Werte und die Fallbacks '--.--.--' / '--.--.-- --:--' werden
        zu 'nie' (kein '(Datum)'-Anhang).
        """
        value = str(value or "").strip()
        if value and value not in ("--.--.--", "--.--.-- --:--"):
            return value
        return "nie"

    def update_mode_label(self, instance_id: str, plugin_id: str,
                          mode: str,
                          instance_hash: Optional[str] = None) -> None:
        """13.08.2026 (Punkt 2, Live-Update): Modus-Suffix der Zeilen
        sofort auf den neuen Modus setzen (ohne Baum-Neuaufbau).

        Betrifft Set-Service-Zeilen (instance_id), die GEWAEHLTE Clone-
        Zeile (instance_hash) und flache Standalone-Plugin-Zeilen
        (plugin_id). Der '(Datum)'-Anhang und ein '*' (Dirty) bleiben
        erhalten. Plugin-Parents MIT Clones bleiben unveraendert (sie
        zeigen nur den Schema-Default des Templates).
        """
        mode = str(mode or "").strip()
        if not mode:
            return
        # Ein-Modus-Services / Services ohne Modus-Schema: kein Suffix.
        if not self._mode_suffix(plugin_id, None):
            return
        pid_l = str(plugin_id or "").strip().lower()
        hash_l = str(instance_hash or "")
        # Bei Clone-/Plugin-Bearbeitung ist instance_id == plugin_id (das
        # Panel nutzt die Plugin-ID als iid); bei Set-Services sind sie
        # verschieden - darueber wird der Zeilen-Scope bestimmt.
        plugin_scope = (str(instance_id or "").strip().lower() == pid_l)
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                ntype = item.data(0, ROLE_NODE_TYPE)
                if plugin_scope:
                    if ntype == TYPE_CLONE:
                        if str(item.data(0, ROLE_PLUGIN_ID) or ""
                               ).strip().lower() != pid_l:
                            continue
                        if hash_l and str(item.data(0, ROLE_INSTANCE_HASH)
                                          or "") != hash_l:
                            continue
                    elif ntype == TYPE_PLUGIN:
                        # Nur flache Blatt-Zeilen (Standalone ohne Clones);
                        # Template-Parents behalten ihren Default-Suffix.
                        if item.childCount() > 0:
                            continue
                        if str(item.data(0, ROLE_PLUGIN_ID) or ""
                               ).strip().lower() != pid_l:
                            continue
                    else:
                        continue
                else:
                    if ntype != TYPE_SERVICE:
                        continue
                    if str(item.data(0, ROLE_INSTANCE_ID) or "") != str(
                            instance_id or ""):
                        continue
                style = "bracket" if ntype == TYPE_CLONE else "dash"
                self._set_label_mode(item, mode, style)
        except (RuntimeError, AttributeError):
            pass

    @staticmethod
    def _set_label_mode(item, mode: str, style: str = "dash") -> None:
        """Setzt den AKTUELLEN Modus im Label neu (13.08.2026, Runde 3).

        style='dash'    (Service/Standalone): 'name - Modus (Datum)' -
                        ersetzt den Modus hinter dem Minuszeichen.
        style='bracket' (Variante/Clone): 'name [servicename] Modus
                        (Datum)' - ersetzt den Modus hinter der Klammer;
                        der Klammer-Wert (Servicename) bleibt erhalten.
        '(Datum)'/' (nie)' und '*' (Dirty) bleiben erhalten; Preset-Namen
        mit Klammern (z. B. 'Default (Kopie)') werden nicht zerstoert
        (das Datum wird am ENDE gesucht).
        """
        try:
            import re
            text = item.text(0) or ""
            # Trailing '(Datum)'/' (nie)' abtrennen (am Ende - Preset-
            # Klammern im Namen bleiben unberuehrt).
            m = re.search(r"\s*\(([^()]*)\)\s*$", text)
            date_part = ""
            if m:
                date_part = f" ({m.group(1)})"
                text = text[:m.start()].rstrip()
            star = ""
            if text.endswith("*"):
                star = "*"
                text = text[:-1].rstrip()
            if style == "bracket":
                bm = re.search(r"\[([^\]]*)\]", text)
                bracket_val = bm.group(1) if bm else ""
                # ' [servicename] Modus' entfernen (Klammer + ein Modus-
                # Token dahinter), die Klammer wird neu eingefuegt.
                stripped = re.sub(r"\s*\[[^\]]*\]\s*[^()\s]+$", "",
                                  text).rstrip()
                if bracket_val:
                    mode_sfx = f" [{bracket_val}] {mode}"
                else:
                    mode_sfx = f" [{mode}]"
            else:
                # ' - Modus' entfernen und neu anfuegen (dash-Format).
                stripped = re.sub(r"\s*-\s+[^()\s]+$", "", text).rstrip()
                mode_sfx = f" - {mode}"
            item.setText(0, f"{stripped}{mode_sfx}{star}{date_part}")
        except (RuntimeError, AttributeError):
            pass

    def _build_plugin_item(self, child: Dict[str, Any],
                           group: str) -> QTreeWidgetItem:
        pid = child.get("plugin_id") or ""
        # Keine fuehrenden Leerzeichen: Einrueckung via setIndentation().
        # 05.08.2026 (Punkt 4): Das Datum der letzten Ausfuehrung (DD.MM.JJ,
        # aus dem feature_store) haengt auch an Standalone-/Plugin-Zeilen:
        # 'srv_proximity (02.08.26)' – ohne Eintrag '(--.--.--)'.
        last_exec = self._fmt_last_exec(child.get("last_execution"))
        clones = child.get("clones") or []
        archived_parent = bool(child.get("archived"))
        # 10.08.2026 (Varianten-Ausfuehrungsdatum): Hat ein Plugin Varianten
        # (Clones), haengt das Datum der letzten Ausfuehrung an der Variante
        # (Clone-Zeile) – der Parent-Knoten zeigt nur noch die Plugin-ID
        # (kein Ausfuehrungsdatum mehr im Knoten darueber).
        # 11.08.2026 (Bugfix, Kosmetik): 'srv_'-Praefix der Plugin-ID wird
        # im Label abgeschnitten (Konsistenz zur Sets-Gruppe mit
        # instance_ids; ROLE_PLUGIN_ID bleibt die echte plugin_id).
        display_pid = pid[4:] if pid.startswith("srv_") else pid
        # 13.08.2026 (Runde 3c, neue Benennung):
        #  - Flache Standalone-Services (ohne Clones): 'name - Modus
        #    (Datum)' (Minuszeichen statt Doppel-Modus).
        #  - Plugin-Parents MIT Clones (Ordnername): NUR der
        #    Servicename - der Modus kann je Variante unterschiedlich
        #    sein und steht an den Clone-Zeilen darunter.
        if clones:
            plugin_label = display_pid
        else:
            mode = self._current_mode(pid, None, "")
            mode_sfx = f" - {mode}" if mode else ""
            plugin_label = f"{display_pid}{mode_sfx} ({last_exec})"
        plugin_item = QTreeWidgetItem([plugin_label, ""])
        plugin_item.setData(0, ROLE_NODE_TYPE, TYPE_PLUGIN)
        plugin_item.setData(0, ROLE_SET_ID, group)
        plugin_item.setData(0, ROLE_PLUGIN_ID, pid)
        if archived_parent:
            plugin_item.setData(0, ROLE_ARCHIVED, True)
        # 20.04 (Q7): Plugins MIT Clones sind Template-Parents (nicht direkt
        # ausfuehrbar) – KEINE Checkbox am Plugin-Knoten; die Clones tragen
        # die Haken. Plugins OHNE Clones bleiben anhakbare flache Blaetter
        # (Bestandsverhalten, feature_id des Feature-Store = plugin_id).
        if clones:
            plugin_item.setFlags(
                plugin_item.flags() & ~Qt.ItemIsUserCheckable)
        elif self._checkable:
            plugin_item.setFlags(
                plugin_item.flags() | Qt.ItemIsUserCheckable)
            key = (TYPE_PLUGIN, "", pid)
            state = (Qt.Checked if key in self._checked_items
                     else Qt.Unchecked)
            plugin_item.setData(0, Qt.CheckStateRole, state)
        self._apply_badge(plugin_item, pid, child.get("badge") or "")
        for clone in clones:
            plugin_item.addChild(self._build_clone_item(clone, pid))
        return plugin_item

    def _build_clone_item(self, clone: Dict[str, Any],
                          plugin_id: str) -> QTreeWidgetItem:
        """Erzeugt ein Clone-/Preset-Kind unter einem Plugin-Parent (20.04).

        Label-Format (Doku §3): aktive Clones `🟢 <Preset> (#<hash>)`,
        archivierte Clones `🔹 <Preset> (#<hash>)`. Aktive Clones sind im
        Checkbox-Modus anhakbar; ARCHIVIERTE Clones sind non-checkable
        (Archive Safety, Q6) und emittieren keine IDs an Scans/Analytics.
        """
        preset_name = str(clone.get("preset_name") or "Default")
        instance_hash = str(clone.get("instance_hash") or "")
        archived = bool(clone.get("is_archived"))
        # 10.08.2026 (Bugfix, Varianten-Ausfuehrungsdatum): Die ID (#hash)
        # entfaellt aus dem Label – stattdessen haengt das Datum der letzten
        # Ausfuehrung dieser Variante direkt am Varianten-Namen:
        # '🟢 <Preset> (DD.MM.JJ)' (ohne Eintrag '(--.--.--)').
        last_exec = self._fmt_last_exec(clone.get("last_execution"))
        prefix = "🔹" if archived else "🟢"
        # 13.08.2026 (Punkt 6, F6): Modus-Suffix an der Variante
        # (Format '🟢 <Preset> [MA_Peak_Hysteresis] (13.08.26)') - die ID
        # (#hash) ist seit 10.08.2026 bereits aus dem Label entfernt.
        # 13.08.2026 (Runde 3, neue Benennung): Die Variante zeigt den
        # SERVICENAMEN in eckigen Klammern (ohne srv_-Praefix), dahinter
        # den AKTUELLEN Modus:
        # '🟢 <Preset> [swing_volume_profile] Volume_Profile (13.08.26 10:48)'.
        mode = self._current_mode(plugin_id, clone.get("params"),
                                  instance_hash)
        display_pid = (plugin_id[4:]
                       if plugin_id.startswith("srv_") else plugin_id)
        mode_sfx = f" [{display_pid}] {mode}" if mode else ""
        clone_item = QTreeWidgetItem(
            [f"{prefix} {preset_name}{mode_sfx} ({last_exec})", ""])
        clone_item.setData(0, ROLE_NODE_TYPE, TYPE_CLONE)
        clone_item.setData(0, ROLE_PLUGIN_ID, plugin_id)
        clone_item.setData(0, ROLE_INSTANCE_HASH, instance_hash)
        clone_item.setData(0, ROLE_PRESET_NAME, preset_name)
        if archived:
            clone_item.setData(0, ROLE_ARCHIVED, True)
        # Tooltip: Plugin/Preset + Modus + Parameter + Doc-Log (F6c).
        tooltip = f"Plugin: {plugin_id}\nPreset: {preset_name}"
        if mode_sfx:
            tooltip += f"\nModus:{mode_sfx}"
        params = clone.get("params") or {}
        if isinstance(params, dict) and params:
            try:
                tooltip += "\n" + ", ".join(
                    f"{k}={v}" for k, v in list(params.items())[:8])
            except Exception:
                pass
        doc_log = str(clone.get("doc_log") or "").strip()
        if doc_log:
            tooltip += f"\n📝 {doc_log}"
        clone_item.setToolTip(0, tooltip)
        # Checkbox nur fuer AKTIVE Clones im Checkbox-Modus (Q6).
        if self._checkable and not archived:
            clone_item.setFlags(
                clone_item.flags() | Qt.ItemIsUserCheckable)
            key = (TYPE_CLONE, plugin_id, instance_hash)
            state = (Qt.Checked if key in self._checked_items
                     else Qt.Unchecked)
            clone_item.setData(0, Qt.CheckStateRole, state)
        elif archived:
            # QTreeWidgetItem traegt ItemIsUserCheckable per Default – bei
            # ARCHIVIERTEN Clones explizit entfernen (Archive Safety, Q6).
            clone_item.setFlags(
                clone_item.flags() & ~Qt.ItemIsUserCheckable)
        return clone_item

    def _apply_badge(self, item: QTreeWidgetItem, plugin_id: str,
                     badge: str,
                     params: Optional[Dict[str, Any]] = None) -> None:
        """Setzt die Darstellung eines Service-/Plugin-Items (Spalte 0/1).

        * Spalte 1: KEIN Badge-Text mehr (Bugfix 05.08.2026) – den Platz
          nimmt der echte Info-Button ein (siehe _attach_item_buttons).
        * Tooltip (Bugfix 05.08.2026): ODER-Logik auf Indikator-Basis –
          a) Service wird aktiv von einem Indikator verwendet
             -> 'aktiv <Indikator>'
          b) sonst, wenn der Service zu einem Indikator gehoert
             -> 'im <Indikator>'
          Die Aktiv-Pruefung beruecksichtigt den ZUGEHOERIGEN Indikator
          (metadata['indicator_id']), nicht nur die Plugin-ID selbst –
          dadurch greift Variante a) auch fuer Services (srv_grid_lines/
          srv_proximity), die IN einem aktiven Indikator (Ind_FixedGridProximity)
          laufen. Der Tooltip wird auf Spalte 0 UND Spalte 1 gesetzt
          (Spalte 1 uebernimmt ihn der Info-Button).
        """
        # Badge-Text entfaellt in Spalte 1 (Info-Button statt Text-Badge).
        item.setText(1, "")
        if self.model.belongs_to_indicator(plugin_id):
            name = self.model.get_indicator_display_name(plugin_id)
            tooltip = (f"aktiv {name}" if self.model.is_active_in_chart(plugin_id)
                       else f"im {name}")
        else:
            tooltip = ""
        # 13.08.2026 (Punkt 6, F6c): Modus auch im Tooltip (falls die
        # Instanz-Params verfuegbar sind - Set-Service-/Clone-Zeile).
        mode_sfx = self._mode_suffix(plugin_id, params)
        if mode_sfx:
            tooltip = (f"{tooltip}\nModus:{mode_sfx}"
                       if tooltip else f"Modus:{mode_sfx}")
        item.setToolTip(0, tooltip)
        item.setToolTip(1, tooltip)

    def _apply_set_badge(self, item: QTreeWidgetItem,
                         definition: Dict[str, Any]) -> None:
        """Set-Badge (Bugfix 05.08.2026): gehoert ein Service-Set einem
        Indikator, traegt der Info-Button (Spalte 1) die Tooltip-Namenslogik
        aus _apply_badge ('aktiv <Indikator>' / 'im <Indikator>'). Mehrere
        Indikatoren im Set werden mit ' + ' verknuepft. Ohne Indikator-
        Zugehoerigkeit bleibt Spalte 1 leer (neutraler Button, kein Tooltip).
        Spalte 0 behaelt den 'Service-Set: <set_id>'-Tooltip (siehe
        _build_set_item) – der Set-Bezug bleibt erhalten.
        """
        names = self.model.get_set_indicator_names(definition or {})
        if not names:
            item.setToolTip(1, "")
            return
        label = " + ".join(names)
        tooltip = (f"aktiv {label}" if self.model.is_set_active(definition or {})
                   else f"im {label}")
        item.setToolTip(1, tooltip)

    def _category_path_of(self, item) -> str:
        """Voller Kategorie-Pfad eines Ordner-Items (17.01.02).

        Sammelt die Ordner-Labels von der Wurzel bis zum Item und verkettet
        sie slash-separiert OHNE '📁 '-Praefix (z.B. 'Swing Points/Geometrie').
        Liefert '' fuer Nicht-Ordner-Items oder leere Ketten. Das Format
        entspricht exakt `ServiceSelectorModel.category_plugin_ids()`.
        """
        parts: List[str] = []
        node = item
        hops = 0
        while node is not None and isValid(node) and hops < 64:
            if node.data(0, ROLE_NODE_TYPE) == TYPE_CATEGORY:
                label = str(node.data(0, ROLE_SET_ID) or "").strip()
                if label.startswith("📁"):
                    label = label[len("📁"):].lstrip()
                if label:
                    parts.append(label)
            node = node.parent()
            hops += 1
        return "/".join(reversed(parts))

    # -------------------------------------------------------------------------
    # 18.01.03 (Dynamic Tree Management): Kategorie-Drag&Drop + Ordner-CRUD
    # -------------------------------------------------------------------------

    def _group_of(self, item) -> str:
        """Eltern-GRUPPE eines Items ('sets' / 'plugins', 18.01.03, L3).

        Wandert vom Item zur Top-Level-Gruppe (TYPE_GROUP) und liefert deren
        ROLE_SET_ID (GROUP_SETS/GROUP_PLUGINS). Leer, wenn keine Gruppe
        gefunden wird (defensiv).
        """
        node = item
        hops = 0
        while node is not None and isValid(node) and hops < 64:
            if node.data(0, ROLE_NODE_TYPE) == TYPE_GROUP:
                return str(node.data(0, ROLE_SET_ID) or "")
            node = node.parent()
            hops += 1
        return ""
