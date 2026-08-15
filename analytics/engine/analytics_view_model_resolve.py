"""
analytics_view_model_resolve.py - Properties & Service-Aufloesung (params, profile, Zeit-Aufloesung, Labels, Hashes)

23.07 God-File-Split (15.08.2026): Aus analytics/engine/analytics_view_model.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der AnalyticsViewModel-
Klasse als Mixin (Klasse AnalyticsViewModelResolveMixin).
"""

from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
)

from analytics.engine.analytics_worker import (
    MAX_LOOKBACK_LIMIT,
)

from analytics.engine.analytics_view_model_constants import (
    DEFAULT_BINS,
    DEFAULT_LIMIT,
)

class AnalyticsViewModelResolveMixin:

    # ------------------------------------------------------------------
    # Jump-to-Chart-Resolution (15.03 Schritt 5, Variante 2)
    # ------------------------------------------------------------------
    def resolve_latest_bar_time(
        self, symbol: str, timeframe: str
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch fuer 'Jump-to-Chart' (oder None).

        Schnelle Punktabfrage (PK-Index) fuer Klick-auf-Punkt aus dem
        Scatter – delegiert lesend an das AnalyticsRepository (kein SQL
        im ViewModel).
        """
        return self._repo.get_latest_bar_time(
            symbol, timeframe,
            feature_ids=self._params.get("feature_ids"),
        )

    def resolve_recent_bar_time_for_cell(
        self, symbol: str, timeframe: str, dow: int, hour: int
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch einer (dow, hour)-Zelle (oder None).

        Jump-to-Chart aus der Heatmap (Doppelklick auf eine Zelle) –
        delegiert lesend an das AnalyticsRepository.
        """
        return self._repo.get_recent_bar_time_for_cell(
            symbol, timeframe, dow, hour,
            feature_ids=self._params.get("feature_ids"),
        )

    # ------------------------------------------------------------------
    # Clamping (Typ- & Werte-Sicherheit)
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp_bins(value: Any) -> int:
        try:
            return max(2, int(value))
        except (TypeError, ValueError):
            return DEFAULT_BINS

    @staticmethod
    def _clamp_limit(value: Any) -> int:
        if value is None:
            return DEFAULT_LIMIT
        try:
            return max(1, min(int(value), MAX_LOOKBACK_LIMIT))
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    # ------------------------------------------------------------------
    # Lesende Zugriffe fuer UI-Pages
    # ------------------------------------------------------------------
    @property
    def params(self) -> Dict[str, Any]:
        """Kopie der aktuellen Ansichtsparameter (fuer UI-Kontrolle)."""
        return dict(self._params)

    @property
    def active_profile(self) -> Optional[Dict[str, Any]]:
        """Kopie des aktiven Profils (oder None)."""
        return dict(self._active_profile) if self._active_profile else None

    @property
    def profiles(self) -> List[Dict[str, Any]]:
        """Kopie der Profil-Liste (deterministisch nach Name sortiert)."""
        return [dict(p) for p in self._profiles]

    @property
    def is_dirty(self) -> bool:
        """True, wenn ungespeicherte Parametertrends vorliegen ('*')."""
        return self._dirty

    @property
    def workspace_layout(self) -> Dict[str, Any]:
        """UI-Layout-Anteil des zuletzt restaurierten Workspace (20.01, E7).

        Z. B. {"page_index": n} – wird von der UI nach `restore_workspace()`
        abgefragt (kein `_params`-Key).
        """
        return dict(self._workspace_layout)

    @property
    def restore_generation(self) -> int:
        """Generations-Token des letzten Restores (Runde 8, Stale-Guard).

        Wird bei jedem restore_workspace()/_apply_profile() erhoeht und vom
        Worker in jedes Ergebnis-Dict gespiegelt (`data["restore_"]`
        generation). Die UI vergleicht den Payload-Wert mit diesem Token und
        verwirft Payloads aelterer Generation (Queries, die VOR dem Restore
        gestartet wurden, ueberschreiben den synchron restaurierten Zustand
        nicht mehr).
        """
        return self._restore_generation

    def heatmap_metrics(self, symbol: str, timeframe: str) -> List[str]:
        """Verfuegbare Heatmap-Metriken fuer ein Symbol/Timeframe (19.02).

        "count" + numerische feature_data-JSON-Keys (dynamisch). Defensiv:
        ohne Daten/bei Fehler -> ["count"].
        """
        try:
            return self._repo.available_heatmap_metrics(
                str(symbol or ""), str(timeframe or ""))
        except Exception:
            return ["count"]

    def available_feature_columns(
        self, symbol: str, timeframe: str
    ) -> List[str]:
        """Numerische feature_data-JSON-Keys (Scatter-/Verteilungs-Dropdown).

        19.02 (Cleanup): Ersetzt die entfernten nativen Spalten. Defensiv:
        Fehler/leere Daten -> [].
        """
        try:
            return self._repo.available_feature_columns(
                str(symbol or ""), str(timeframe or ""))
        except Exception:
            return []

    # ------------------------------------------------------------------
    # 20.02.01 (E8): Lesbares Service-Label fuer die service_id-Dimension
    # ------------------------------------------------------------------
    def resolve_service_label(self, plugin_id: str) -> str:
        """Lesbares Service-Label '{Kategorie} / {Name}' (20.02.01, E8).

        Formatiert eine `service_id`-Dimension der generischen Heatmap:
        das `srv_`-Prefix entfaellt (metadata['display_name'], z. B.
        'Trend Breakout'), der Kategorie-Pfad (plugin_category_path,
        Slash -> ' / ') wird vorangestellt (z. B.
        'Swing Points / Trend Breakout'). Unbekannte/entfernte IDs ->
        Rohwert (defensiv). Lazy `_selector_model` (Muster
        `_resolve_feature_ids`), rein lesend, kein SQL.
        """
        key = str(plugin_id or "").strip()
        if not key:
            return ""
        # 21.03.20-Bugfix 3: Die service_id-Dimension traegt seit dem
        # Modus-Split '{service_id}::{source_mode}' (leerer Suffix =
        # Service ohne source_mode). Den Modus abspalten und als
        # ' / {Modus}' anhaengen (nur bei nicht-leerem Wert).
        mode_suffix = ""
        if "::" in key:
            key, mode_suffix = key.split("::", 1)
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            plugin = model.get_plugin(key)
            if plugin is None:
                label = key
            else:
                meta = getattr(plugin, "metadata", {}) or {}
                name = str(meta.get("display_name") or key)
                if name.lower().startswith("srv_"):
                    name = name[4:]
                category = str(model.plugin_category_path(key) or "")
                label = f"{category} / {name}" if category else name
            if mode_suffix:
                label = f"{label} / {mode_suffix}"
            return label
        except Exception:
            return key + (f" / {mode_suffix}" if mode_suffix else "")

    def resolve_service_display_name(self, plugin_id: str,
                                     preset_name: Optional[str] = None,
                                     exec_date: Optional[str] = None) -> str:
        """Service-Name OHNE Kategorie-Pfad, direkt aus dem Service-Objekt.

        09.08.2026 (User-Meldung 'Feld'-Dropdown): Der Name wird DIREKT aus
        dem Service-Objekt abgeleitet – aus dessen `plugin_id` (der
        Identitaet des Objekts): `srv_`-Prefix entfaellt, Unterstriche
        werden zu Leerzeichen, Worte title-case ('srv_swing_momentum' ->
        'Swing Momentum'). Damit steht der KORREKTE Service-Name im
        'Feld'-Dropdown der generischen Heatmap; `metadata['display_name']`
        ist nicht zuverlaessig (z. B. 'Swing Momentum Service' mit
        'Service'-Suffix, das wie ein MasterTree-Pfad-Bestandteil wirkt).
        Kein Kategorie-Pfad. Unbekannte/entfernte IDs -> lesbarer Pretty-
        Fallback (defensiv). Rein lesend, kein SQL.

        20.04 (Q2, §4): Optionaler `preset_name` ergaenzt das Label um
        ' ({Preset_Name})' – Anzeige-Format '{Service} ({Preset}) /
        {Parameter}' fuer Parameter-Varianten (Clones). Ohne preset_name
        bleibt das Label unveraendert (Zero-Regression).

        Runde 16 (Bugfix 1, 11.08.2026): Format-Vereinheitlichung auf
        '{Name} / {Preset} / {Datum}' (Schraegstrich statt Klammern;
        'Default' als Platzhalter-Preset wird uebersprungen). Optionaler
        `exec_date` haengt Datum+Uhrzeit der letzten Ausfuehrung an
        ('DD.MM.JJ HH:MM') - Grundlage der Feld-Dropdown-Anzeige.
        """
        key = str(plugin_id or "").strip()
        if not key or key.lower() in ("none", "native") \
                or key.lower().startswith("native_"):
            # 09.08.2026 (User-Meldung Feld-Dropdown, Root Cause 3) +
            # 20.03.02 (F3): Leere/fehlende/Native-Keys liefern einen
            # lesbaren Sammel-Namen statt eines Leerstrings (kein leerer
            # Prefix vor Feld-Eintraegen). `native`/`native_*` werden wie
            # `none` auf 'Allgemein' gemappt (benutzerfreundlich).
            return "Allgemein"
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            plugin = model.get_plugin(key)
            if plugin is None:
                # 09.08.2026 (Root Cause 3): Unbekannte/abgewaehlte Keys
                # (z. B. Native-Rows) -> lesbarer Pretty-Fallback statt
                # Rohwert/Leerstring ('native' -> 'Native').
                pretty = (key.replace("src_", "").replace("srv_", "")
                          .replace("ind_", "").replace("_", " ").title())
                return pretty or key
            pid = str(getattr(plugin, "plugin_id", None) or key)
            name = pid
            for prefix in ("src_", "srv_", "ind_"):
                if name.lower().startswith(prefix):
                    name = name[len(prefix):]
                    break
            pretty = name.replace("_", " ").title()
            if not pretty:
                pretty = key
            # Runde 16 (Bugfix 1): Preset-Name + Ausfuehrungsdatum per
            # Schraegstrich anhaengen ('{Name} / {Preset} / DD.MM.JJ HH:MM').
            # 'Default' ist ein Platzhalter-Preset (Standalone-Services) und
            # wird uebersprungen.
            preset = str(preset_name or "").strip()
            if preset and preset.lower() != "default":
                pretty = f"{pretty} / {preset}"
            exec_d = str(exec_date or "").strip()
            if exec_d:
                pretty = f"{pretty} / {exec_d}"
            return pretty
        except Exception:
            return key

    def checked_variant(
        self, plugin_id: str
    ) -> Optional[Dict[str, str]]:
        """Aktuell gecheckte Variante eines Services inkl. Ausfuehrungsdatum.

        Runde 16 (Bugfix 1, 11.08.2026): Grundlage der Feld-Dropdown-
        Anzeige '{Name} / {Preset} / DD.MM.JJ HH:MM' - das Dropdown haengt
        an Feld-Eintraege die im ServicePicker gecheckte Variante (Preset)
        und das Datum+Uhrzeit ihrer letzten Ausfuehrung an.

        Auswahl-Semantik (identisch zum Reader/Snapshot):
          * Ist `instance_hashes` aktiv (Varianten-Einschraenkung), gewinnt
            die gecheckte Variante (exakter Hash-Match).
          * Ohne Hash-Auswahl zaehlt die ERSTE aktive (nicht archivierte)
            Variante des Services - ist der Service ein reiner Standalone
            (keine Presets), bleibt das Ergebnis None (kein Preset-Anhang).
          * Datum+Uhrzeit: Varianten mit Hash ueber
            `last_execution_datetime_for_hash` ('DD.MM.JJ HH:MM'), hash-lose
            Services ueber `last_execution_date` (nur Datum). Ohne Eintraege
            liefern beide den '--...'-Fallback (die Anzeige laesst ihn aus).

        Returns:
            {"preset_name", "instance_hash", "exec_datetime"} oder None
            (unbekannter Service / keine Presets / Fehler - defensiv).
        """
        key = str(plugin_id or "").strip()
        if not key:
            return None
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            active_hashes = {str(h).strip().lower()
                             for h in (self._params.get("instance_hashes")
                                       or [])}
            clones = (model.plugin_presets() or {}).get(key.lower()) or []
            chosen = None
            if active_hashes:
                for c in clones:
                    if not isinstance(c, dict):
                        continue
                    h = str(c.get("instance_hash") or "").strip()
                    if h and h.lower() in active_hashes:
                        chosen = c
                        break
            else:
                for c in clones:
                    if isinstance(c, dict) and not c.get("is_archived"):
                        chosen = c
                        break
                if chosen is None and clones:
                    chosen = clones[0]
            if chosen is None or not isinstance(chosen, dict):
                return None
            h = str(chosen.get("instance_hash") or "").strip()
            if h:
                exec_date = model.last_execution_datetime_for_hash(key, h)
            else:
                exec_date = model.last_execution_date(key)
            return {
                "preset_name": str(chosen.get("preset_name") or "Default"),
                "instance_hash": h,
                "exec_datetime": exec_date,
            }
        except Exception:
            return None

    def service_execution_datetime(self, plugin_id: str) -> str:
        """Datum+Uhrzeit der letzten Ausfuehrung eines Services.

        Runde 16c (Bugfix 1, 11.08.2026, User-Meldung): Das Feld-Dropdown
        haengt an Services OHNE Varianten (Standalone, z. B.
        srv_trend_breakout - kein Preset/keine Set-Instanz) das
        Ausfuehrungsdatum an ('{Name} / {Key} / DD.MM.JJ HH:MM', z. B.
        '23.04.26 22:14'). Rein lesend ueber das ServiceSelectorModel
        (`last_execution_datetime`); Fallback '--.--.-- --:--' ohne
        Eintraege oder bei Fehlern (defensiv).
        """
        key = str(plugin_id or "").strip()
        if not key:
            return "--.--.-- --:--"
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            return model.last_execution_datetime(key)
        except Exception:
            return "--.--.-- --:--"

    def resolve_instance_hashes(self,
                                hashes: Iterable[str]) -> List[str]:
        """Loest instance_hash-Werte transparent auf plugin_ids auf (20.04, Q2).

        Quelle: Plugin-Presets/Clones des `ServiceSelectorModel`
        (`plugin_presets()`, in refresh() aus indicator_presets geladen) –
        die Zuordnung Hash -> plugin_id ist dort deterministisch ueber
        `generate_instance_hash` abgelegt. Rueckgabe: deduplizierte
        plugin_ids (Reihenfolge erhalten, case-insensitiv). Hashes ohne
        Treffer werden verworfen (defensiv). Der Filter bleibt dadurch auf
        `WHERE feature_id IN (plugin_ids)` – die Varianten-Aufloesung
        passiert transparent im ViewModel (kein SQL, rein lesend).

        Beispiel: `resolve_instance_hashes(["a91f3b"])` -> ["srv_swing_pivot"].
        """
        wanted = {str(h or "").strip()
                  for h in (hashes or []) if str(h or "").strip()}
        if not wanted:
            return []
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        result: List[str] = []
        seen: Set[str] = set()
        try:
            presets = model.plugin_presets() or {}
            for pid, clones in presets.items():
                if not clones or not isinstance(clones, list):
                    continue
                for clone in clones:
                    if not isinstance(clone, dict):
                        continue
                    h = str(clone.get("instance_hash") or "").strip()
                    if not h or h not in wanted:
                        continue
                    if str(pid).lower() not in seen:
                        seen.add(str(pid).lower())
                        result.append(str(pid))
                    # Ein plugin_id pro Hash genuegt (dedupliziert).
                    wanted.discard(h)
        except Exception:
            pass
        return result

    def _no_data_presets_snapshot(self) -> Dict[str, Any]:
        """Serialisiert die Preset-Modell-Daten fuer die No-Data-Auswertung.

        Runde 11 (Bug 4, B4-1): Die '(No Data)'-Auswertung laeuft im
        QUERY_FEATURES-Worker (Repo, Worker-Thread) - dort ist das
        ServiceSelectorModel nicht verfuegbar. Der ViewModel reicht eine
        reine Daten-Snapshot (in-memory, KEIN SQL) ueber die Query-Params:
            {"presets": {pid: [{"preset_name", "instance_hash",
                                "is_archived"}]},
             "sets": [{"services": {instance_id: {"plugin_id", "params",
                                                   "is_archived"}}}],
             "standalone": [plugin_id der registrierten Plugins ohne
                            Presets und ohne Set-Instanz (hash-lose
                            Variante, 15c)],
             "display_names": {"{pid}|{pname}": "Anzeigename"},
             "active_hashes": [instance_hash der im Picker gecheckten
                               Varianten (leer = keine Einschraenkung)]}
        Der Reader kombiniert den Snapshot mit den DB-Fakten
        (available_instance_hashes / feature_keys_by_service) im Worker-
        Thread und liefert `no_data_variants` als Payload-Attribut (B4-2).

        Runde 13 (Bugfix Dropdown-NoData): `active_hashes` macht den Payload
        VARIANTEN-GENAU - der Reader `resolve_no_data_variants()` liefert
        damit nur noch die im ServicePicker gecheckten Varianten als
        '(No Data)' (nicht-gecheckte Instanzen derselben plugin_id erscheinen
        nicht mehr; das Dropdown zeigt nicht mehr die erste Variante).

        Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026): Reine
        Standalone-Services (registrierte Plugins OHNE Presets/Clones UND
        OHNE Set-Instanz, z. B. srv_trend_breakout) wurden nie in den
        Snapshot aufgenommen - der Reader konnte sie daher nie als
        '(No Data)' markieren, obwohl der feature_store noch keine Rows
        ihrer plugin_id besitzt. Die neue Snapshot-Sektion `standalone`
        listet genau diese Plugins als hash-lose Variante (preset_name
        'Default'); der Reader prueft sie gegen `pids_with_data`.
        """
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        presets: Dict[str, Any] = {}
        sets: List[Any] = []
        display_names: Dict[str, str] = {}
        # Runde 15c (Bugfix Standalone): Registrierte Plugins ohne Presets
        # und ohne Set-Instanz als hash-lose '(No Data)'-Kandidaten.
        standalone: List[str] = []
        # Runde 12 (Punkt 4): Nur GE CHECKTE Services in den Snapshot
        # aufnehmen (feature_ids-Filter; leer = kein Filter = alle). Nicht
        # angehakte Services duerfen keine '(No Data)'-Hinweise liefern.
        active_ids = {str(f).strip().lower()
                      for f in (self._params.get("feature_ids") or [])}
        # Runde 13c (Bugfix Dropdown-NoData, Kernwunsch): Leerer Filter
        # (feature_ids=[]) = KEINE '(No Data)'-Eintraege. Ohne aktive
        # Datenquellen-Auswahl wuerde der Snapshot ALLE Services enthalten
        # und der Reader jede NoData-Variante im Feld-Dropdown anzeigen
        # (der Button 'Aktive Filter entfernen' verspricht 'zeigt danach
        # wieder alle Features' – ohne NoData-Rauschen).
        if not active_ids:
            return {"presets": {}, "sets": [], "display_names": {},
                    "active_hashes": []}
        # Runde 13 (Bugfix Dropdown-NoData): Varianten-Einschraenkung mit
        # an den Reader geben - die '(No Data)'-Auswertung wird damit
        # variantengenau (nur im Picker gecheckte Varianten im Payload).
        active_hashes = {str(h).strip().lower()
                         for h in (self._params.get("instance_hashes") or [])}
        try:
            for pid, clones in (model.plugin_presets() or {}).items():
                pid_s = str(pid)
                if active_ids and pid_s.strip().lower() not in active_ids:
                    continue
                clone_list: List[Dict[str, Any]] = []
                for c in clones or []:
                    if not isinstance(c, dict):
                        continue
                    h_s = str(c.get("instance_hash") or "").strip().lower()
                    # Runde 13b (Bugfix Dropdown-NoData): Harte Varianten-
                    # Einschraenkung - sind Hashes gecheckt (active_hashes
                    # nicht leer), duerfen NUR diese Varianten in den
                    # Snapshot (bewusst OHNE `h_s and`-Guard: eine hash-lose
                    # Variante ist bei aktiver Einschraenkung nie Teil der
                    # Auswahl und darf kein '(No Data)' liefern - sonst
                    # erscheinen ungecheckte Instanzen weiterhin).
                    if active_hashes and h_s not in active_hashes:
                        continue
                    pname = str(c.get("preset_name") or "Default")
                    clone_list.append({
                        "preset_name": pname,
                        "instance_hash": str(c.get("instance_hash") or ""),
                        "is_archived": bool(c.get("is_archived")),
                    })
                    display_names[f"{pid_s}|{pname}"] = \
                        self.resolve_service_display_name(pid_s, pname)
                if clone_list:
                    presets[pid_s] = clone_list
            for s in model.get_sets() or []:
                if not isinstance(s, dict):
                    continue
                services = s.get("services")
                if not isinstance(services, dict):
                    continue
                if active_ids:
                    services = {
                        k: svc for k, svc in services.items()
                        if isinstance(svc, dict)
                        and str(svc.get("plugin_id") or "").strip().lower()
                        in active_ids}
                if services:
                    sets.append({"services": services})
            # Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026):
            # Registrierte Plugins, die weder Presets/Clones noch eine
            # Set-Instanz besitzen (z. B. srv_trend_breakout), sind reine
            # Standalone-Services. Als hash-lose Variante (preset_name
            # 'Default') geprueft, erscheinen sie im Feld-Dropdown, sobald
            # der feature_store noch keine Rows ihrer plugin_id besitzt.
            # Beim Vorhandensein von Daten (pids_with_data) bleibt der
            # NoData-Hinweis aus (Reader-Semantik). Ausgeschlossen sind
            # Plugins mit Presets oder Set-Instanzen (dort laeuft die
            # bestehende Preset-/Set-Auswertung).
            # Runde 16 (Bugfix Mischbetrieb, User-Meldung 5/6, 11.08.2026):
            # Der Runde-15c-Guard `if not active_hashes:` ist ENTFERNT - er
            # schloss die Standalone-Sektion aus, sobald eine Hash-Auswahl
            # aktiv war (Mischbetrieb Service + Version). Standalone-
            # Services werden UEBER `feature_ids` gecheckt, NICHT ueber
            # Hashes - eine aktive Varianten-Einschraenkung darf sie daher
            # nicht aus der NoData-Auswertung verwerfen.
            try:
                all_presets = model.plugin_presets() or {}
                preset_keys = {str(k).strip().lower()
                               for k in all_presets}
                set_pids: Set[str] = set()
                for _s in model.get_sets() or []:
                    _services = (_s.get("services")
                                 if isinstance(_s, dict) else None)
                    if not isinstance(_services, dict):
                        continue
                    for _svc in _services.values():
                        if isinstance(_svc, dict) and str(
                                _svc.get("plugin_id") or "").strip():
                            set_pids.add(
                                str(_svc["plugin_id"]).strip().lower())
                for _pid in (model.get_plugins() or {}).keys():
                    _pid_l = str(_pid).strip().lower()
                    if not _pid_l:
                        continue
                    if active_ids and _pid_l not in active_ids:
                        continue
                    if _pid_l in preset_keys or _pid_l in set_pids:
                        continue
                    standalone.append(_pid)
                    display_names[f"{_pid}|Default"] = \
                        self.resolve_service_display_name(_pid)
            except Exception:
                pass
        except Exception:
            pass
        return {
            "presets": presets,
            "sets": sets,
            "standalone": standalone,
            "display_names": display_names,
            "active_hashes": sorted(active_hashes),
        }

    @property
    def max_lookback_limit(self) -> int:
        """Max-Lookback-Cap (UI-Slider-Maximum)."""
        return MAX_LOOKBACK_LIMIT

    def available_timeframes(self, symbol: str) -> List[str]:
        """Timeframes mit Feature-Store-Daten fuer ein Symbol (TF-Ausgrauung).

        Delegiert lesend an das AnalyticsRepository (kein SQL im ViewModel).
        Bei Fehlern wird eine leere Liste geliefert; die UI kann dann alle
        Timeframes aktiv lassen (Fallback).
        """
        try:
            return self._repo.available_timeframes(str(symbol or ""))
        except Exception:
            return []
