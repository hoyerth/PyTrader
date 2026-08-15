"""
feature_store_reader_plugin.py - No-Data-Varianten, Proximity/Plugin-Records, exists

23.05 God-File-Split (15.08.2026): Aus analytics/engine/feature_store_reader.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der FeatureStoreReader
als Mixin (Klasse FeatureStorePluginMixin).
"""

import os

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

class FeatureStorePluginMixin:

    def resolve_no_data_variants(
        self,
        symbol: str,
        timeframe: str,
        presets_data: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Plugin-Varianten ohne feature_store-Daten (Runde 11, B4-1).

        Runde 11 (Bug 4): Die '(No Data)'-Auswertung wurde aus dem
        UI-Hauptthread in den QUERY_FEATURES-Worker verlagert. Der
        ViewModel liefert die Preset-Modell-Daten als Snapshot
        (`presets_data`: {"presets": {pid: [...]}, "sets": [...],
        "standalone": [pid...], "display_names": {"{pid}|{pname}": str},
        "active_hashes": [gecheckte Varianten-Hashes]}); diese Methode
        kombiniert sie mit den DB-Fakten (`available_instance_hashes` /
        `feature_keys_by_service`) im Worker-Thread.

        Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026): Die neue
        Snapshot-Sektion `standalone` listet registrierte Plugins ohne
        Presets und ohne Set-Instanz (z. B. srv_trend_breakout) als
        hash-lose Variante (preset_name 'Default'). Eine Standalone-Variante
        gilt als 'ohne Daten', wenn ihre plugin_id keine feature_store-Zeilen
        besitzt (`_has_data` prueft `pids_with_data` direkt - kein
        Hash-/Alt-Bestand-Fallback noetig). Dadurch erscheint ein
        registrierter, aber noch nie ausgeführter Service korrekt als
        '(No Data)' im Feld-Dropdown.

        Runde 13 (Bugfix Dropdown-NoData): `active_hashes` (nicht leer =
        Varianten-Einschraenkung) macht die Auswertung VARIANTEN-GENAU -
        es werden NUR die im ServicePicker gecheckten Varianten geliefert
        (nicht-gecheckte Instanzen derselben plugin_id erscheinen nicht
        mehr im '(No Data)'-Abschnitt; das Dropdown zeigt damit nicht mehr
        die erste Variante eines Services, wenn eine andere gecheckt ist).

        Runde 13c (Alt-Bestand): Eine Variante ohne Hash-Treffer zaehlt
        trotzdem als 'hat Daten', wenn die plugin_id ausschliesslich
        undifferenzierte Alt-Rows OHNE instance_hash besitzt
        (`plugin_ids_with_hashes`) � dieser Alt-Bestand gehoert der
        ORIGINAL-Variante (der ERSTEN aktiven Variante der plugin_id im
        Snapshot). Runde 14: Weitere Varianten derselben plugin_id werden
        NICHT vom Alt-Bestand abgedeckt - eine neu erzeugte zweite Variante
        ohne Daten muss als '(No Data)' erscheinen.

        Eine Variante gilt als 'ohne Daten', wenn ihr instance_hash KEINE
        Zeilen besitzt (oder - bei Varianten ohne Hash - ihr plugin_id keine
        feature_store-Zeilen liefert). Archivierte Presets sind bewusst
        unsichtbar (Q6/Q7).

        Returns:
            Liste von {"plugin_id", "preset_name", "instance_hash",
            "display_name"} - leer, wenn alle Varianten Daten besitzen
            (defensiv, rein lesend).
        """
        if not symbol or not timeframe:
            return []
        presets = (presets_data or {}).get("presets") or {}
        sets = (presets_data or {}).get("sets") or []
        display_names = (presets_data or {}).get("display_names") or {}
        # Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026):
        # Registrierte Plugins ohne Presets und ohne Set-Instanz
        # (z. B. srv_trend_breakout) - der ViewModel markiert sie ueber
        # die Snapshot-Sektion "standalone" als hash-lose Variante. Sie
        # gelten als '(No Data)', solange der feature_store keine Rows
        # ihrer plugin_id besitzt (Reader prueft `pids_with_data`).
        standalone = (presets_data or {}).get("standalone") or []
        # Runde 13 (Bugfix Dropdown-NoData): Varianten-Einschraenkung aus dem
        # Snapshot - leer = KEINE Einschraenkung (alle Varianten der aktiven
        # Services), nicht leer = nur die gecheckten Varianten.
        active_hashes = {str(h).strip().lower()
                         for h in ((presets_data or {}).get("active_hashes")
                                   or [])}
        try:
            available = self.available_instance_hashes(symbol, timeframe)
        except Exception:
            available = set()
        # Runde 13c (Bugfix Dropdown-NoData, Alt-Bestand): Plugin-IDs mit
        # eigenem instance_hash-Bestand (Varianten-Aufteilung). Liegt die
        # plugin_id NICHT in dieser Menge, stammt ihr gesamter Bestand aus
        # undifferenzierten Alt-Rows OHNE Hash (z. B. srv_proximity: alle
        # Rows instance_hash IS NULL) – dann deckt der Alt-Bestand jede
        # Variante des Services ab (kein '(No Data)'-Fehlalarm fuer
        # Varianten, deren berechneter Hash in keiner DB-Zeile steht).
        # WICHTIG: pids_with_hashes=None bei Fehler (z. B. Fake/Temp-DB
        # ohne Tabelle) - dann bleibt die Runde-10-Semantik konservativ
        # erhalten (kein Alt-Bestand-Fallback auf unbekannter Basis).
        try:
            pids_with_hashes = self.plugin_ids_with_hashes(symbol, timeframe)
        except Exception:
            pids_with_hashes = None
        # Runde 12 (Option A, Performance): Die teure feature_keys_by_service-
        # Abfrage (laedt feature_data-JSONs) wird auf die AKTIVEN plugin_ids
        # des Snapshots eingeschraenkt (Preset-Keys + Set-Instanz-Services) -
        # bei leerem Snapshot (keine aktiven Presets) genuegt eine leere
        # pids_with_data-Menge. Vorher scannte die Abfrage ALLE Zeilen des
        # Symbols (Hauptgrund fuer das langsame Dropdown-Update).
        active_pids: List[str] = []
        for _pid in (presets or {}).keys():
            active_pids.append(str(_pid))
        for _s in sets or []:
            _services = _s.get("services") if isinstance(_s, dict) else None
            if not isinstance(_services, dict):
                continue
            for _svc in _services.values():
                if isinstance(_svc, dict) and str(
                        _svc.get("plugin_id") or "").strip():
                    active_pids.append(str(_svc["plugin_id"]))
        # Runde 15c: Standalone-Services ebenfalls in die Abfrage-Scope
        # aufnehmen - `pids_with_data` muss deren Datenlage kennen, sonst
        # wuerde ein Standalone-Service MIT Rows faelschlich als '(No Data)'
        # geliefert (feature_keys_by_service scannt nur die aktiven pids).
        for _pid in standalone or []:
            _s = str(_pid or "").strip()
            if _s:
                active_pids.append(_s)
        active_pids = list(dict.fromkeys(active_pids))
        try:
            if active_pids:
                keys_by_service = self.feature_keys_by_service(
                    symbol, timeframe, feature_ids=active_pids)
            else:
                keys_by_service = {}
            pids_with_data = {str(k).strip().lower()
                              for k in (keys_by_service or {})}
        except Exception:
            pids_with_data = set()
        try:
            from analytics.engine.service_models import generate_instance_hash
        except Exception:
            generate_instance_hash = None
        # Runde 10 (Bug 2): available case-insensitiv indexieren (einmalig).
        available_low = {str(x).strip().lower()
                         for x in (available or set())}

        def _has_data(pid: str, h: str) -> bool:
            """True, wenn die Variante feature_store-Daten besitzt.

            Runde 10 (Bug 2): Differenzierung statt grobem
            pids_with_data-Fallback - eine benannte Variante mit eigenem
            instance_hash zaehlt NUR, wenn GENAU dieser Hash Zeilen
            besitzt. Der pids_with_data-Fallback gilt nur noch fuer
            Varianten OHNE Hash (NULL/Alt-Bestand).

            Runde 13c (Bugfix Dropdown-NoData, Alt-Bestand): Besitzt die
            plugin_id KEINERLEI hash-differenzierte Zeilen (`pids_with_hashes`
            leer), stammt ihr Bestand aus undifferenzierten Alt-Rows
            (instance_hash IS NULL, z. B. srv_proximity vor der
            feature_data-Migration). Dieser Alt-Bestand gehoert der
            plugin_id als Ganzes und deckt JEDE Variante ab - sonst wuerde
            z. B. die Set-Instanz 'srv_proximity' trotz 99K M1-Zeilen als
            '(No Data)' gemeldet, weil ihr berechneter Hash
            (generate_instance_hash) in keiner DB-Zeile steht. Der
            Fallback greift NUR, wenn die Hash-Bestands-Abfrage ERFOLGREICH
            war (pids_with_hashes ist None = Abfragefehler -> konservativ
            Runde-10-Semantik, kein Fallback).
            """
            if not pid:
                return True
            h_s = str(h or "").strip()
            if h_s:
                if h_s.lower() in available_low:
                    return True
                # Undifferenzierter Alt-Bestand (keine Hash-Zeilen der
                # plugin_id bekannt): die plugin-weiten Daten decken die
                # ORIGINAL-Variante ab (die ERSTE aktive Variante im
                # Snapshot - ihr gehoert der Alt-Bestand, der vor der
                # Hash-Aera von genau dieser Instanz geschrieben wurde).
                # Nur bei erfolgreicher Bestands-Abfrage. Runde 14: Der
                # Fallback gilt NICHT fuer weitere Varianten derselben
                # plugin_id - eine neu erzeugte zweite Variante (anderer
                # Hash, noch nie berechnet) hat KEINE Daten und muss als
                # '(No Data)' erscheinen.
                if (pids_with_hashes is not None
                        and str(pid).strip().lower() not in pids_with_hashes
                        and h_s == first_hash_by_pid.get(
                            str(pid).strip().lower(), "")):
                    return str(pid).strip().lower() in pids_with_data
                return False
            return str(pid).strip().lower() in pids_with_data

        # Runde 14 (Bugfix Dropdown-NoData, 2. Variante ohne Daten):
        # Bestimme die ERSTE aktive Variante je plugin_id im Snapshot
        # (Reihenfolge wie im ServicePicker: Presets/Clones zuerst, dann
        # Set-Instanzen). Nur dieser Original-Variante darf der
        # Alt-Bestand-Fallback (undifferenzierte NULL-Hash-Rows) zugeordnet
        # werden - der Bestand wurde vor der Hash-Aera von genau der
        # ersten/originalen Instanz geschrieben.
        first_hash_by_pid: Dict[str, str] = {}

        def _collect_first(pid: str, h: str) -> None:
            k = str(pid or "").strip().lower()
            if not k:
                return
            if k not in first_hash_by_pid:
                first_hash_by_pid[k] = str(h or "").strip()

        for _pid, _clones in presets.items():
            if not isinstance(_clones, list):
                continue
            for _clone in _clones:
                if not isinstance(_clone, dict) or _clone.get("is_archived"):
                    continue
                _collect_first(str(_pid),
                               str(_clone.get("instance_hash") or ""))
        for _s in sets or []:
            _services = _s.get("services") if isinstance(_s, dict) else None
            if not isinstance(_services, dict):
                continue
            for _svc in _services.values():
                if not isinstance(_svc, dict) or _svc.get("is_archived"):
                    continue
                _pid = str(_svc.get("plugin_id") or "").strip()
                if not _pid:
                    continue
                _h = ""
                if generate_instance_hash is not None:
                    _h = generate_instance_hash(_pid, _svc.get("params") or {})
                _collect_first(_pid, _h)

        out: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str]] = set()

        def _add(pid: str, pname: str, h: str) -> None:
            pid_s = str(pid or "").strip()
            if not pid_s:
                return
            h_s = str(h or "").strip()
            # Runde 13 (Bugfix Dropdown-NoData): Varianten-Einschraenkung -
            # ist eine Hash-Auswahl aktiv (active_hashes nicht leer), werden
            # NUR die gecheckten Varianten geliefert. Nicht-gecheckte
            # Instanzen derselben plugin_id erscheinen nicht mehr als
            # '(No Data)' (vorher wurde hier die ERSTE Variante des Services
            # angezeigt bzw. ungecheckte Instanzen mit aufgefuehrt).
            # Runde 16 (Bugfix Mischbetrieb, User-Meldung 5/6, 11.08.2026):
            # Der Guard greift nur noch bei Varianten MIT Hash (`h_s and`) -
            # hash-lose Varianten (Standalone-Services wie srv_trend_breakout
            # und NULL-Hash-Alt-Bestand) werden UEBER `feature_ids` gecheckt
            # und duerfen von einer aktiven Hash-Auswahl nicht verworfen
            # werden (sonst verschwinden Services im Mischbetrieb).
            if active_hashes and h_s and h_s.lower() not in active_hashes:
                return
            key = (pid_s.lower(), h_s)
            if key in seen:
                return
            seen.add(key)
            if _has_data(pid_s, h_s):
                return
            pname_s = str(pname or "Default")
            out.append({
                "plugin_id": pid_s,
                "preset_name": pname_s,
                "instance_hash": h_s,
                "display_name": str(
                    display_names.get(f"{pid_s}|{pname_s}")
                    or self._no_data_fallback_name(pid_s, pname_s)),
            })

        for pid, clones in presets.items():
            if not isinstance(clones, list):
                continue
            for clone in clones:
                if not isinstance(clone, dict):
                    continue
                if clone.get("is_archived"):
                    continue
                _add(str(pid),
                     str(clone.get("preset_name") or "Default"),
                     str(clone.get("instance_hash") or ""))
        # Runde 9 (Bug 2): Set-Instanz-Varianten ebenfalls erfassen.
        for s in sets or []:
            services = s.get("services") if isinstance(s, dict) else None
            if not isinstance(services, dict):
                continue
            for instance_id, svc in services.items():
                if not isinstance(svc, dict):
                    continue
                if svc.get("is_archived"):
                    continue
                pid = str(svc.get("plugin_id") or "").strip()
                if not pid:
                    continue
                if generate_instance_hash is not None:
                    h = generate_instance_hash(pid, svc.get("params") or {})
                else:
                    h = ""
                _add(pid, f"{pid} [{instance_id}]", h)
        # Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026): Reine
        # Standalone-Services als hash-lose Variante (preset_name 'Default')
        # erfassen - `_has_data(pid, "")` prueft direkt `pids_with_data`
        # (kein Hash-/Alt-Bestand-Fallback noetig). Ein Standalone-Service
        # ohne feature_store-Rows erscheint damit als '(No Data)' im
        # Feld-Dropdown; sobald Daten existieren, bleibt der Hinweis aus.
        for pid in standalone or []:
            _add(str(pid), "Default", "")
        return out

    @staticmethod
    def _no_data_fallback_name(pid: str, pname: str) -> str:
        """Lesbarer Fallback-Anzeigename (ohne Modell-Zugriff im Reader).

        Runde 11 (Bug 4, B4-1): Der Reader kennt das ServiceSelectorModel
        nicht - der ViewModel liefert die Anzeigenamen ueber den Snapshot
        (`display_names`); dieser Fallback greift nur bei fehlendem
        Snapshot-Eintrag (defensiv, identisch zur VM-Logik).
        """
        pretty = (pid.replace("srv_", "").replace("ind_", "")
                  .replace("_", " ").title())
        if not pretty:
            pretty = pid
        # Runde 16 (Bugfix 1, 11.08.2026): Anzeige-Format auf
        # '{Name} / {Preset}' umgestellt (identisch zum ViewModel-Format;
        # vorher '{Name} ({Preset})'). 'Default' wird als Platzhalter-
        # Preset uebersprungen (Standalone-Services ohne echten Preset).
        if pname and str(pname).strip().lower() != "default":
            return f"{pretty} / {str(pname).strip()}"
        return pretty

    # 22.01 (14.08.2026): Peak-Grabber (Frage 3, Live-Pfad). Lese-Helfer fuer
    # das Yellow-Flag der aktuellen Bar: liefert den letzten srv_proximity-
    # Record (bis `up_to_epoch`) mit geparstem feature_data (levels_hit /
    # in_time_window). Reine Lese-Methode (MVVM, Praeambel 4) – kein Schreib-
    # zugriff. Der Indikator ind_peak nutzt ihn in _is_current_bar_yellow();
    # fehlt der Record, greift der Fallback True (Gate offen, Frage 3).
    def latest_proximity_record(
        self,
        symbol: str,
        timeframe: str,
        up_to_epoch: int,
    ) -> Optional[Dict[str, Any]]:
        """Liefert den letzten srv_proximity-Record (feature_id='srv_proximity')
        bis zur Wanduhr-Epoch `up_to_epoch` oder None.

        Returns:
            {"time": Wanduhr-Epoch, "feature_data": geparstes JSON (inkl.
            schema_version-Default)} – oder None, wenn kein Record existiert.
        """
        if not symbol or not timeframe:
            return None
        try:
            up_to = int(up_to_epoch)
        except (TypeError, ValueError):
            return None
        con = self._get_connection()
        try:
            row = con.execute("""
                SELECT EXTRACT('epoch' FROM bar_time)::BIGINT, feature_data
                FROM feature_store
                WHERE LOWER(symbol) = LOWER(?)
                  AND LOWER(timeframe) = LOWER(?)
                  AND LOWER(TRIM(feature_id)) = 'srv_proximity'
                  AND EXTRACT('epoch' FROM bar_time)::BIGINT <= ?
                  AND feature_data IS NOT NULL
                ORDER BY bar_time DESC
                LIMIT 1
            """, [symbol, timeframe, up_to]).fetchone()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] latest_proximity_record "
                  f"fehlgeschlagen: {e}")
            return None
        if row is None or row[0] is None:
            return None
        return {
            "time": int(row[0]),
            "feature_data": self._normalize_feature_data(row[1]),
        }

    def fetch_plugin_records(
        self,
        symbol: str,
        timeframe: str,
        feature_id: str,
        limit: Optional[int] = None,
        up_to_epoch: Optional[int] = None,
        from_epoch: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """22.01d: Liefert die persistierten Records eines Plugin-Services
        (feature_data + bar_time) aufsteigend nach bar_time.

        Reine Lese-Methode (MVVM, Praeambel 4) - kein Schreibzugriff. Der
        Indikator ind_peak liest damit die srv_peak_finder/srv_peak_grabber-
        Daten AUSSCHLIESSLICH aus dem feature_store (keine In-Memory-
        Fantasie-Linien; User-Anweisung 1: vor Servicelauf keine Zeichnung).

        Args:
            up_to_epoch: optionale Zeitfenster-Obergrenze (Wanduhr-Epoch,
                inklusiv) - begrenzt die DB-Last auf den relevanten
                Chart-Bereich (Records jenseits der letzten df-Bar werden
                im Render-Payload ohnehin verworfen; Performance-Fix 22.01e).
            from_epoch: optionale Zeitfenster-Untergrenze (Wanduhr-Epoch,
                inklusiv) - analog; beide Filter werden als
                `EXTRACT('epoch' FROM bar_time)::BIGINT` auf die Spalte
                angewendet (identisch zu latest_proximity_record).

        Returns:
            Liste von Dicts, je Record = feature_data (geparstes JSON inkl.
            schema_version-Default) zzgl. `bar_time` (Wanduhr-Epoch, int).
        """
        if not symbol or not timeframe or not feature_id:
            return []
        if limit is None:
            limit = 20000
        conds = ["LOWER(symbol) = LOWER(?)",
                 "LOWER(timeframe) = LOWER(?)",
                 "LOWER(TRIM(feature_id)) = LOWER(?)",
                 "feature_data IS NOT NULL"]
        params = [symbol, timeframe, feature_id]
        try:
            if up_to_epoch is not None:
                conds.append(
                    "EXTRACT('epoch' FROM bar_time)::BIGINT <= ?")
                params.append(int(up_to_epoch))
            if from_epoch is not None:
                conds.append(
                    "EXTRACT('epoch' FROM bar_time)::BIGINT >= ?")
                params.append(int(from_epoch))
        except (TypeError, ValueError):
            return []
        params.append(limit)
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT EXTRACT('epoch' FROM bar_time)::BIGINT, feature_data
                FROM feature_store
                WHERE """ + " AND ".join(conds) + """
                ORDER BY bar_time ASC
                LIMIT ?
            """, params).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_plugin_records "
                  f"fehlgeschlagen: {e}")
            return []
        out: List[Dict[str, Any]] = []
        for r in rows:
            fd = self._normalize_feature_data(r[1])
            if not isinstance(fd, dict):
                continue
            rec = dict(fd)
            rec["bar_time"] = int(r[0])
            out.append(rec)
        return out

    def exists(self) -> bool:
        """True, wenn die analytics.duckdb-Datei existiert."""
        return os.path.exists(self.db_path)
