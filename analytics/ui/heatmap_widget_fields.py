"""
heatmap_widget_fields.py - Feld-Auswahl/-Dropdown, Checked-Pairs, VM-Sync

23.09 God-File-Split (15.08.2026): Aus analytics/ui/heatmap_widget.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der HeatmapWidget-
Klasse als Mixin (Klasse HeatmapWidgetFieldMixin).
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
)

from PySide6.QtCore import (
    Qt,
)

from analytics.ui.heatmap_widget_constants import (
    _VALUE_AGGS,
)

class HeatmapWidgetFieldMixin:

    @staticmethod
    def _field_key(ud: Any) -> str:
        """Extrahiert den JSON-Key aus einem userData-Wert (20.03.02).

        'srv_proximity|visit_pct' -> 'visit_pct'; reine Keys bleiben.
        """
        s = str(ud or "")
        return s.split("|", 1)[1] if "|" in s else s

    def _find_field_index(self, key: str) -> int:
        """Item-Index im 'Feld'-Dropdown, dessen Key-Teil == `key` ist.

        20.03.02: Das userData traegt '{service_id}|{key}' – findData(key)
        wuerde den reinen Key nicht finden. Gibt -1 zurueck, wenn keiner
        passt (Restore-Fallback erzeugt dann ein neues Item). 20.03.03: Bei
        gemeinsamen Keys (2+ Quellen) findet die Methode zuerst den
        Sammel-Eintrag ('ALL|key' -> Key-Teil == key).
        """
        for i in range(self._combo_field.count()):
            if self._field_key(self._combo_field.itemData(i)) == key:
                return i
        return -1

    def _first_field_index(self) -> int:
        """Erster auswaehlbarer (nicht-Header) Item-Index im Feld-Dropdown
        (20.03.03, Q4).

        Sektions-Header haben `Qt.NoItemFlags` und duerfen nicht als
        Current-Item gewaehlt werden – Index 0 kann ein Header sein.
        """
        for i in range(self._combo_field.count()):
            item = self._combo_field.model().item(i)
            if item is not None and (item.flags() & Qt.ItemIsEnabled):
                return i
        return 0

    # ------------------------------------------------------------------
    # 20.03.02 (F1c/F2): Multi-Select im 'Feld'-Dropdown -> Datenquellen-
    # Filter `feature_ids` (KEINE Signatur-Aenderung von set_heatmap_config;
    # die Aggregation nutzt GENAU EIN aktives Hauptfeld).
    # ------------------------------------------------------------------
    def _on_field_selection_changed(self, _checked: List[str]) -> None:
        """CheckState-Wechsel im 'Feld'-Dropdown -> feature_ids-Filter.

        21.03.15 (Bug 1): Die Verbindung selection_changed -> dieser
        Handler ist WIEDER aktiv (siehe __init__) - Check/Uncheck im
        'Feld'-Dropdown schreibt feature_ids ueber den ServicePicker-
        Pfad, damit ServicePicker-Auswahl und Feld-Dropdown konsistent
        bleiben (Single Source of Truth = ServicePicker + Dropdown).

        Die angehakten Items bestimmen die Datenquellen (`set_feature_ids`);
        `set_feature_ids` stoesst den Debounce-Refresh der generischen
        Heatmap (und der uebrigen Analytics-Seiten) an. Leere Auswahl =
        leerer Filter (alle Features, ViewModel-Semantik 15.03-E).

        20.03.03 (Q5): Vor der Filterableitung wird die XOR-Regel angewendet –
        Sammel- ('ALL|key') und Einzel-Eintraege ('srv_x|key') desselben Keys
        schliessen sich gegenseitig aus (keine Doppel-Haken).
        """
        if self._syncing or self._view_model is None:
            return
        # 13.08.2026 (Punkt 4, F4): Vor der Reconciliation das AKTIVE Feld
        # merken - wird es abgehakt, wechselt die Aggregations-/Anzeige-
        # auswahl implizit auf das naechste angehakte Feld (genau EIN Feld
        # wird aggregiert/angezeigt; die angehakten Paare bestimmen die
        # Verfuegbarkeit).
        prev_ud = str(self._combo_field.currentData() or "")
        self._reconcile_sammel_checks()
        new_ud = str(self._combo_field.currentData() or "")
        # 12.08.2026 (Option A, Bug 1/2): Die angehakten Items bestimmen die
        # (Service|Parameter)-Paare (`set_field_selection`) - An/Abwaehlen
        # eines Parameters aendert die Grafik auch bei unveraenderter
        # Service-Menge. Leere Auswahl = kein Paar-Filter (alle Features,
        # ViewModel-Semantik 15.03-E). Alt-/Test-ViewModel ohne
        # Parameter-Ebene fallen auf den Service-Pfad zurueck.
        pairs = self._checked_field_pairs()
        if hasattr(self._view_model, "set_field_selection"):
            self._view_model.set_field_selection(pairs)
        else:
            ids = self._checked_field_service_ids()
            self._view_model.set_feature_ids(ids)
        # P4 (F4): Das aktive Feld wurde abgehakt -> die Auswahl ist auf das
        # naechste angehakte Feld nachgezogen (_sync_field_current_after_-
        # checks in _reconcile_sammel_checks, blockSignals) -> die
        # Konfiguration/der Refresh wird hier explizit nachgezogen, damit
        # das neue Feld auch aggregiert/angezeigt wird.
        if new_ud and new_ud != prev_ud:
            self._apply_config()

    def _reconcile_sammel_checks(self) -> None:
        """XOR-Reconciliation (20.03.03, Q5): Sammel- und Einzel-Eintraege
        desselben Keys schliessen sich gegenseitig aus.

        Grundlage ist der ZULETZT geklickte Eintrag (`last_click_index`):
        - Klick auf `ALL|key` (Sammel)  -> Einzel-Eintraege von `key` abwaehlen.
        - Klick auf `srv_x|key` (Einzel) -> Sammel-Eintrag `ALL|key` abwaehlen.
        Programmatische Wechsel (kein Klick, Index -1) loesen nichts auf.
        Danach wird der Current-Index auf ein angehaktes/auswaehlbares Item
        nachgezogen.
        """
        last_idx = self._combo_field.last_click_index()
        if last_idx < 0:
            self._sync_field_current_after_checks()
            return
        item = self._combo_field.model().item(last_idx)
        if item is None or not (item.flags() & Qt.ItemIsEnabled):
            return
        ud = str(item.data(Qt.UserRole) or "")
        checked = [str(u or "") for u in self._combo_field.checked_data()]
        if ud.startswith("ALL|"):
            # Sammel gewinnt: alle Einzel-Eintraege desselben Keys abwaehlen.
            key = ud.split("|", 1)[1]
            wanted = [u for u in checked
                      if not (u.endswith(f"|{key}") and not u.startswith("ALL|"))]
            if wanted != checked:
                self._combo_field.set_checked_data(wanted)
        elif "|" in ud:
            # Einzel gewinnt: Sammel-Eintrag desselben Keys abwaehlen.
            all_ud = f"ALL|{self._field_key(ud)}"
            if all_ud in checked:
                self._combo_field.set_checked_data(
                    [u for u in checked if u != all_ud])
        self._sync_field_current_after_checks()

    def _sync_field_current_after_checks(self) -> None:
        """Stellt sicher, dass der aktuelle Feld-Index auf einem anhakbaren
        Item mit aktivem CheckState steht (20.03.03, Q5).

        Nach der XOR-Reconciliation kann der Index auf einem abgewaehlten
        oder deaktivierten (Header-)Item stehen – dann wird er (blockiert)
        auf das erste angehakte, sonst erste auswaehlbare Item nachgezogen.
        """
        idx = self._combo_field.currentIndex()
        item = self._combo_field.model().item(idx)
        if (item is not None and (item.flags() & Qt.ItemIsEnabled)
                and item.checkState() == Qt.Checked):
            return
        new_idx = -1
        for i in range(self._combo_field.count()):
            it = self._combo_field.model().item(i)
            if it is None or not (it.flags() & Qt.ItemIsEnabled):
                continue
            if it.checkState() == Qt.Checked:
                new_idx = i
                break
        if new_idx < 0:
            for i in range(self._combo_field.count()):
                it = self._combo_field.model().item(i)
                if it is not None and (it.flags() & Qt.ItemIsEnabled):
                    new_idx = i
                    break
        if 0 <= new_idx != idx:
            self._combo_field.blockSignals(True)
            self._combo_field.setCurrentIndex(new_idx)
            self._combo_field.blockSignals(False)

    def _checked_field_service_ids(self) -> List[str]:
        """Service-IDs der angehakten Feld-Items (20.03.03, Q2).

        - `ALL|<key>` (Sammel-Eintrag) wird ueber `self._field_sources[key]`
          auf ALLE Quellen-Services des Keys expandiert (Confluence).
        - `{service_id}|<key>` liefert genau seine service_id.
        Items ohne `|` (roher Legacy-Key) tragen keinen eindeutigen Service
        und bleiben aussen vor (die Quellen der Einzel-Keys decken den
        Filter ab). Dedupliziert, in Item-Reihenfolge.
        """
        ids: List[str] = []
        for ud in self._combo_field.checked_data():
            s = str(ud or "")
            if s.startswith("ALL|"):
                key = s.split("|", 1)[1]
                for sid in (self._field_sources.get(key) or []):
                    if sid and sid not in ids:
                        ids.append(sid)
            elif "|" in s:
                sid = s.split("|", 1)[0]
                if sid and sid not in ids:
                    ids.append(sid)
        return ids

    def _checked_field_pairs(self) -> List[str]:
        """(Service|Parameter)-Paare der angehakten Feld-Items (12.08.2026).

        Option A (Bug 1/2): Grundlage des Parameter-Filters
        (`set_field_selection`). `ALL|<key>` expandiert ueber
        `self._field_sources[key]` auf ALLE Quellen-Services des Keys,
        `{service_id}|<key>` liefert genau das Paar. Roh-Keys ohne `|`
        (Legacy) bleiben aussen vor (tragen keine Service-Zuordnung).
        Dedupliziert, in Item-Reihenfolge.
        """
        pairs: List[str] = []
        for ud in self._combo_field.checked_data():
            s = str(ud or "")
            if s.startswith("ALL|"):
                key = s.split("|", 1)[1]
                for sid in (self._field_sources.get(key) or []):
                    if sid and f"{sid}|{key}" not in pairs:
                        pairs.append(f"{sid}|{key}")
            elif "|" in s:
                sid, key = s.split("|", 1)
                if sid and f"{sid}|{key}" not in pairs:
                    pairs.append(f"{sid}|{key}")
        return pairs

    def _sync_field_selection_to_vm(self) -> None:
        """Spiegelt die effektive Paar-Auswahl in den ViewModel (12.08.2026).

        Wird am Ende jedes `_rebuild_field_dropdown()` gerufen: Die
        effektiven (Service|Parameter)-Paare (aus der Dropdown-Auswahl)
        werden via `set_field_selection` persistiert, damit a) die
        DEFAULT-Vorbelegung (erster Parameter je aktivem Service) auch die
        Query steuert (Bug 2) und b) verwaiste/entfernte Paare automatisch
        bereinigt werden. Nur bei aktivem Service-Filter (feature_ids nicht
        leer) - ohne Filter (alle Features) bleibt field_selection None und
        die Heatmap zeigt weiterhin alle Features ohne Paar-Filter.
        Idempotent via set_field_selection (kein Refresh bei Gleichstand).
        """
        if self._view_model is None:
            return
        p = self._view_model.params
        if not (p.get("feature_ids") or []):
            return
        if not hasattr(self._view_model, "set_field_selection"):
            return
        pairs = self._checked_field_pairs()
        # update_ids=False: feature_ids (ServicePicker) bleibt die
        # Service-Quelle - der Sync verkleinert die Service-Auswahl nie.
        self._view_model.set_field_selection(pairs, update_ids=False)

    def _rebuild_field_dropdown(
        self,
        keys: List[str],
        field_sources: Dict[str, List[str]],
        payload_agg: Optional[str] = None,
        payload_field: Optional[str] = None,
    ) -> None:
        """Baut das 'Feld'-Dropdown aus Feld-Metadaten + VM-Params (Runde 8).

        Single Source of Truth:
          * Items      -> `keys`/`field_sources` (Payload-Metadaten bzw.
                          Widget-Cache `self._field_keys/_field_sources`)
          * Haken      -> `feature_ids` (ServicePicker, aktiver Filter)
          * Current    -> `heatmap_field` (Restore/Workspace gewinnt)

        SYNCHRON (kein Query-Round-Trip): wird aus dem Datenpfad
        (_sync_combos_from_payload) UND dem VM-Pfad (_sync_from_params /
        _on_feature_ids_changed) gerufen. Ein restaurierter
        Ergebnisparameter (Bug 3) bleibt dadurch auch ohne frischen Payload
        sichtbar; ein Check/Uncheck im ServicePicker (Bug 4) aktualisiert
        das Dropdown sofort. Die Runde-7-Prioritaet (VM-Params gewinnen
        gegen einen Stale-Payload) wird hier zentral angewendet.
        """
        if self._view_model is None:
            return
        p = self._view_model.params
        # Cache aktualisieren (Payload-Metadaten bzw. uebergebene Werte).
        self._field_keys = [str(k) for k in (keys or [])]
        self._field_sources = {
            str(k): [str(s) for s in (v or [])]
            for k, v in (field_sources or {}).items()
        }
        # Agg/Feld: restaurierte VM-Params gewinnen; erst wenn der VM leer
        # ist, zaehlen Payload-Fallback bzw. aktueller Combo-Wert (Runde 7).
        agg = (str(p.get("heatmap_agg") or "") or str(payload_agg or "")
               or str(self._combo_agg.currentData() or ""))
        prev_field = (str(p.get("heatmap_field") or "")
                      or str(payload_field or "")
                      or self._field_key(self._combo_field.currentData()))
        active_ids = {str(f).strip().lower()
                      for f in (p.get("feature_ids") or [])}
        # 12.08.2026 (Option A, Bug 1/2): EXPLIZITE (Service|Parameter)-
        # Auswahl (`field_selection`) gewinnt - sie wird bei Check/Uncheck
        # persistiert und beim Aggregations-/Restore-Wechsel EXAKT wieder
        # hergestellt (Bug 2: keine 'alle Parameter'-Vorbelegung mehr; Bug 1:
        # An/Abwaehlen eines Parameters aendert die Grafik). Ohne explizite
        # Auswahl greift die DEFAULT-Vorbelegung: bei aktivem Service-Filter
        # wird je aktivem Service genau der ERSTE Parameter angehakt (fuer
        # AVG/SUM/MIN/MAX ist genau EIN aktives Hauptfeld sinnvoll), bei
        # leerem Filter (alle Features) nur der erste Eintrag insgesamt
        # (Verhalten wie bisher).
        sel_pairs = [str(x) for x in (p.get("field_selection") or [])]
        sel_map: Dict[str, Set[str]] = {}
        for _sp in sel_pairs:
            if "|" in _sp:
                _sid, _k = _sp.split("|", 1)
                sel_map.setdefault(_k, set()).add(_sid.strip().lower())
        explicit = bool(sel_pairs)
        no_filter = not active_ids
        # Default-Vorbelegung: erster Parameter je aktivem Service
        # (sortierte Key-Reihenfolge aus self._field_keys).
        first_key_by_service: Dict[str, str] = {}
        if not explicit and not no_filter:
            for k in sorted(self._field_keys):
                for sid in self._field_sources.get(k) or []:
                    sid_l = sid.strip().lower()
                    if (sid_l in active_ids
                            and sid_l not in first_key_by_service):
                        first_key_by_service[sid_l] = k
        # no_filter-Semantik: genau der ERSTE Eintrag insgesamt wird
        # vorbelegt (first_done); alle weiteren folgen `match`.
        first_done = [no_filter and not explicit]

        def _chk(match: bool) -> bool:
            if first_done[0]:
                first_done[0] = False
                return True
            return match

        def _chk_pair(sid: str, key: str) -> bool:
            """Check-Vorgabe fuer einen '{sid}|{key}'-Einzel-Eintrag."""
            sid_l = str(sid).strip().lower()
            if explicit:
                # Nur AKTIVE Services: ein Paar eines im ServicePicker
                # abgewaehlten Services darf nicht angehakt bleiben.
                return (sid_l in active_ids
                        and sid_l in sel_map.get(key, ()))
            return first_key_by_service.get(sid_l) == key

        def _chk_all(key: str, src: List[str]) -> bool:
            """Check-Vorgabe fuer den 'ALL|<key>'-Sammel-Eintrag."""
            if explicit:
                return all(str(s).strip().lower() in active_ids
                           and str(s).strip().lower() in sel_map.get(key, ())
                           for s in src)
            return all(first_key_by_service.get(str(s).strip().lower())
                       == key for s in src)

        try:
            self._combo_field.blockSignals(True)
            self._combo_field.clear()
            shared = sorted(k for k in self._field_keys
                            if len(self._field_sources.get(k) or []) >= 2)
            if shared:
                self._combo_field.add_header_item(
                    "🌐 Gleiche Parameter (alle aktiven Services):")
                for k in shared:
                    src = self._field_sources.get(k) or []
                    self._combo_field.add_checkable_item(
                        f"Alle Services / {k}", f"ALL|{k}",
                        checked=_chk(_chk_all(k, src)))
            if self._field_keys:
                self._combo_field.add_header_item("🔌 Einzelservices:")
            for k in sorted(self._field_keys):
                sids = self._field_sources.get(k) or []
                if len(sids) == 1:
                    # Eindeutiger Service: nur angehakt, wenn das
                    # (Service|Parameter)-Paar aktiv ist (Default: erster
                    # Parameter; explizit: field_selection).
                    self._combo_field.add_checkable_item(
                        self._field_label(k, sids), f"{sids[0]}|{k}",
                        checked=_chk(_chk_pair(sids[0], k)))
                elif not sids:
                    # Legacy ohne field_sources (roher Key, defensiv).
                    self._combo_field.add_checkable_item(k, k,
                                                         checked=_chk(False))
                else:
                    # Shared Key: je Quelle ein Einzel-Eintrag; der Sammel-
                    # Eintrag deckt die Quellen ab (Q5/XOR), daher nur
                    # anhaken, solange NICHT alle Quellen des Keys aktiv.
                    all_checked = _chk_all(k, sids)
                    for sid in sids:
                        self._combo_field.add_checkable_item(
                            self._field_label(k, [sid]), f"{sid}|{k}",
                            checked=_chk(_chk_pair(sid, k)
                                         and not all_checked))
            if prev_field in self._field_keys:
                self._combo_field.setCurrentIndex(
                    self._find_field_index(prev_field))
            elif self._field_keys:
                # 20.03.03 (Q4): Index 0 kann ein Header sein -> ersten
                # auswaehlbaren Eintrag waehlen.
                self._combo_field.setCurrentIndex(self._first_field_index())
            elif prev_field:
                # Kein Payload/Cache (Restore vor dem ersten Datenpaket):
                # Roh-Item anlegen, damit der restaurierte Wert sichtbar
                # und ausgewaehlt bleibt (Muster _sync_from_params).
                self._combo_field.add_checkable_item(
                    prev_field, prev_field, checked=True)
                self._combo_field.setCurrentIndex(
                    self._combo_field.count() - 1)
            # Runde 11 (Bug 4, B4-1): '(No Data)'-Hinweise kommen jetzt als
            # Payload-Attribut `no_data_variants` vom QUERY_FEATURES-Worker
            # (Cache self._no_data_variants) - KEIN synchroner DB-Zugriff
            # mehr im UI-Hauptthread. Die Anzeige unterscheidet Loading/
            # Erfolg/Fehler und filtert nach aktiven instance_hashes (B4-5).
            self._render_no_data_items()
        finally:
            self._combo_field.blockSignals(False)
        self._update_controls()
        # E6: Wert-Aggregation mit leerem/abweichendem Feld -> restauriertes
        # Feld gewinnt (falls im Datensatz verfuegbar), sonst ersten Key
        # uebernehmen und Konfiguration nachreichen (einmaliger Query-Loop).
        vm_field = str(p.get("heatmap_field") or "")
        if (agg in _VALUE_AGGS and self._combo_field.currentData()
                and vm_field != self._field_key(
                    self._combo_field.currentData())):
            if vm_field and vm_field in self._field_keys:
                fidx = self._find_field_index(vm_field)
                if fidx >= 0:
                    self._combo_field.setCurrentIndex(fidx)
            else:
                self._apply_config()
        # 12.08.2026 (Option A, Bug 1/2): Effektive Paar-Auswahl in den VM
        # spiegeln (Default-Vorbelegung materialisieren / verwaiste Paare
        # bereinigen). Idempotent; kein Refresh bei Gleichstand.
        self._sync_field_selection_to_vm()
