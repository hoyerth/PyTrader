"""
analytics_view_model_profile.py - Profil-Verwaltung (CRUD, Apply/Restore, Workspace, EventBus-Emit)

23.07 God-File-Split (15.08.2026): Aus analytics/engine/analytics_view_model.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der AnalyticsViewModel-
Klasse als Mixin (Klasse AnalyticsViewModelProfileMixin).
"""

from typing import (
    Any,
    Dict,
    Optional,
)

from repositories.analytics_profile_repository import (
    SCHEMA_VERSION_DEFAULT,
)

from config.event_bus import (
    event_bus,
)

class AnalyticsViewModelProfileMixin:

    # ------------------------------------------------------------------
    # Profil-Verwaltung (CRUD + aktives Profil)
    # ------------------------------------------------------------------
    def load_profiles(self) -> None:
        """Laedt die Profil-Liste und wendet das aktive Profil an."""
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        active = self._profile_repo.get_active_profile()
        if active is not None:
            self._apply_profile(active, mark_dirty=False)
        elif self._active_profile is not None:
            self._active_profile = None
            self._dirty = False
            self.dirty_changed.emit(False)
            self.active_profile_changed.emit(None)

    def create_profile(
        self, name: str, description: str = ""
    ) -> Optional[str]:
        """Legt ein neues Profil mit den aktuellen Parametern an.

        Das neue Profil wird sofort aktiv (genau EIN aktives Profil).
        Raises ValueError bei doppeltem Namen.
        """
        name = (name or "").strip()
        if not name:
            return None
        if self._profile_repo.get_profile_by_name(name) is not None:
            raise ValueError(f"Profil '{name}' existiert bereits.")
        profile_id = self._profile_repo.create_profile(
            name, self._current_payload(), description
        )
        self._profile_repo.set_active(profile_id)
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        self._active_profile = self._profile_repo.get_profile(profile_id)
        self._dirty = False
        self.dirty_changed.emit(False)
        self.active_profile_changed.emit(dict(self._active_profile))
        self._emit_profile_changed(self._active_profile["name"])
        return profile_id

    def save_profile(self) -> bool:
        """Persistiert die aktuellen Parameter im aktiven Profil (Save).

        Returns:
            True, wenn ein aktives Profil existierte und gespeichert wurde.
        """
        if self._active_profile is None:
            return False
        profile_id = self._active_profile["profile_id"]
        ok = self._profile_repo.update_profile(
            profile_id, payload=self._current_payload()
        )
        if ok:
            self._active_profile = self._profile_repo.get_profile(profile_id)
            self._dirty = False
            self.dirty_changed.emit(False)
            self.profile_saved.emit(profile_id)
            self._emit_profile_changed(self._active_profile["name"])
        return ok

    def update_profile(
        self,
        profile_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Aktualisiert Name/Beschreibung eines Profils (additiv)."""
        ok = self._profile_repo.update_profile(
            profile_id, name=name, description=description
        )
        if ok:
            self._profiles = self._profile_repo.list_profiles()
            self.profiles_available.emit([dict(p) for p in self._profiles])
            if (self._active_profile is not None
                    and self._active_profile["profile_id"] == profile_id):
                self._active_profile = self._profile_repo.get_profile(profile_id)
                self.active_profile_changed.emit(dict(self._active_profile))
                self._emit_profile_changed(self._active_profile["name"])
        return ok

    def delete_profile(self, profile_id: str) -> bool:
        """Loescht ein Profil (hart). Aktives Profil wird zurueckgesetzt."""
        ok = self._profile_repo.delete_profile(profile_id)
        if not ok:
            return False
        was_active = (self._active_profile is not None
                      and self._active_profile["profile_id"] == profile_id)
        if was_active:
            self._active_profile = None
            self._dirty = False
            self.dirty_changed.emit(False)
            self.active_profile_changed.emit(None)
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        self.profile_deleted.emit(profile_id)
        return True

    def set_active_profile(self, profile_id: str) -> bool:
        """Setzt ein Profil als aktiv und wendet dessen Parameter an."""
        profile = self._profile_repo.get_profile(profile_id)
        if profile is None:
            return False
        self._profile_repo.set_active(profile_id)
        self._apply_profile(profile, mark_dirty=False)
        self.active_profile_changed.emit(dict(profile))
        self._emit_profile_changed(profile["name"])
        return True

    def _apply_profile(
        self, profile: Dict[str, Any], mark_dirty: bool = True
    ) -> None:
        """Uebernimmt die Profil-Parameter in die Ansicht (Explicit Save).

        20.01 (E2/E3/E5): Das Repository liefert beim Lesen bereits migrierte
        v2-Sectioned-Payloads – die flachen Sektionen werden hier auf die
        flachen `_params` abgebildet (keine VM-eigene Migration, Single
        Source of Truth im Repository). Fehlende Services (entfernte/
        umbenannte Plugins) werden per ServiceSelectorModel isoliert und via
        `missing_services_detected` gemeldet; die validen IDs werden DIREKT
        in `_params` geschrieben (kein `set_feature_ids`: kein Dirty-Flag,
        kein Doppel-Refresh, B4).
        """
        self._active_profile = dict(profile)
        payload = profile.get("payload") or {}
        flat = self._flatten_payload(payload)
        # 10.08.2026 (Punkte 3/4): UI-Layout (page_index/heatmap_mode) aus
        # dem Profil-Payload uebernehmen - die UI liest es ueber
        # workspace_layout (identischer Pfad wie restore_workspace).
        layout = payload.get("layout")
        if isinstance(layout, dict):
            self._workspace_layout.update(dict(layout))
        # Runde 11 (Bug 3, B3-2): Gemeinsamer Restore-Helper (Replace-
        # Semantik inkl. instance_hashes -> garantiert leer bei fehlendem
        # Payload-Key statt des alten Werts).
        self._restore_params_from_payload(flat)
        # 15.03-E (Profil-Migration): Alt-Payloads speicherten den Filter als
        # Einzelwert `feature_id` (String) – in `feature_ids` (Liste) wandeln.
        if "feature_ids" not in flat and flat.get("feature_id"):
            self._params["feature_ids"] = self._normalize_feature_ids(
                [flat["feature_id"]])
        # 20.02 (Luecke 5.3-6): `charts.heatmap` ist ein VERSCHACHTELTES Dict –
        # _flatten_payload() bildet es NICHT auf flache _params ab. Explizit
        # aufloesen (E3: additiv, kein Schema-Bump auf v2.1).
        self._apply_heatmap_section(flat.get("heatmap"))
        # 20.02.01 (E6): Alt-Payloads mit `dow_hour` (flach ODER via
        # charts.heatmap) auf die gueltige Dimension "hour" abbilden.
        for _hk in ("heatmap_x_dim", "heatmap_y_dim"):
            if self._params.get(_hk) == "dow_hour":
                self._params[_hk] = "hour"
        self._params["feature_ids"] = self._normalize_feature_ids(
            self._params.get("feature_ids"))
        # Runde 10 (Bug 1): instance_hashes genauso normalisieren.
        self._params["instance_hashes"] = self._normalize_instance_hashes(
            self._params.get("instance_hashes"))
        # 12.08.2026 (Option A): (Service|Parameter)-Auswahl des
        # 'Feld'-Dropdowns genauso normalisieren (Alt-Payloads ohne den
        # Key -> leer = kein Paar-Filter, Verhalten wie bisher).
        self._params["field_selection"] = self._normalize_field_pairs(
            self._params.get("field_selection"))
        # 20.01 (E5) + Runde 9 (Bug 1): Fehlende Services NUR melden -
        # die IDs bleiben im Filter (kein stilles Kuerzen des restaurierten
        # Filters; die DB liefert fuer unbekannte IDs keine Zeilen).
        if self._params["feature_ids"]:
            _, missing = self._resolve_feature_ids(self._params["feature_ids"])
            if missing:
                self.missing_services_detected.emit(list(missing))
        self._params["bins"] = self._clamp_bins(self._params.get("bins"))
        self._params["limit"] = self._clamp_limit(self._params.get("limit"))
        if not mark_dirty:
            self._dirty = False
            self.dirty_changed.emit(False)
        # Runde 8 (Bugfix 3): Generation erhoehen - die UI verwirft
        # Stale-Payloads aelterer Generation (Queries, die VOR diesem
        # Profilwechsel gestartet wurden).
        self._restore_generation += 1
        # Runde 10 (Bug 4): REIHENFOLGE - erst die UI-Combos synchronisieren
        # (params_restored), DANN die Daten anfordern. Runde 11 (A1): KEIN
        # refresh_all() mehr im Restore-Pfad - das AnalyticsWindow
        # orchestriert die Queries zentral (A6: Sync -> Query-Key-Pruefung
        # -> request_data). Ein expliziter User-Refresh (Button) darf
        # weiterhin refresh_all() nutzen.
        self.params_restored.emit()

    def _apply_heatmap_section(self, heat: Any) -> None:
        """Loest die verschachtelte `charts.heatmap`-Sektion auf (20.02).

        Luecke 5.3-6: `_flatten_payload()` bildet das verschachtelte Dict
        nicht auf die flachen `_params`-Keys ab – dieser Helfer uebernimmt
        die 20.02-Keys additiv (nur vorhandene/gueltige Werte; None bleibt
        unveraendert). Zoom-Bereiche werden geclampt (E8).
        """
        if not isinstance(heat, dict):
            return
        if heat.get("x_dim") is not None:
            self._params["heatmap_x_dim"] = self._sanitize_dim(heat["x_dim"])
        if heat.get("y_dim") is not None:
            self._params["heatmap_y_dim"] = self._sanitize_dim(heat["y_dim"])
        if heat.get("agg") is not None:
            self._params["heatmap_agg"] = str(heat["agg"]).lower()
        if heat.get("field") is not None:
            self._params["heatmap_field"] = str(heat["field"])
        # 21.01 (E1): TF-Freigabe aus dem Payload restaurieren.
        if heat.get("all_timeframes") is not None:
            self._params["heatmap_all_timeframes"] = bool(
                heat["all_timeframes"])
        if heat.get("candle_projection_enabled") is not None:
            self._params["candle_projection_enabled"] = bool(
                heat["candle_projection_enabled"])
        if isinstance(heat.get("zoom_x_range"), (list, tuple)):
            self._params["zoom_x_range"] = self._clamp_zoom(
                heat["zoom_x_range"])
        if isinstance(heat.get("zoom_y_range"), (list, tuple)):
            self._params["zoom_y_range"] = self._clamp_zoom(
                heat["zoom_y_range"])

    def _restore_params_from_payload(self, flat: Dict[str, Any]) -> None:
        """Uebernimmt flache Payload-Params per Replace-Semantik (B3-2).

        Runde 11 (Bug 3, B3-2): Gemeinsamer Restore-Pfad fuer
        `_apply_profile()` und `restore_workspace()`. Bekannte `_params`-Keys
        werden UEBERSCHRIEBEN, sofern der Payload einen nicht-None-Wert
        liefert (additiv, wie bisher). Der Varianten-Filter `instance_hashes`
        folgt echter Replace-Semantik: Fehlt der Key im Payload (Alt-Payloads
        ohne Varianten-Angabe), ist er garantiert leer ([]) statt des
        vorherigen Werts - ein gespeicherter Zustand OHNE Varianten-Ein-
        schraenkung darf nicht stillschweigend den alten Filter uebernehmen.
        Andere Keys (z. B. heatmap-Konfiguration, table-Settings) werden
        NICHT generell geleert - nur vorhandene Payload-Werte zaehlen
        (additiv, kein Datenverlust).
        """
        for key in list(self._params.keys()):
            if key in flat and flat[key] is not None:
                self._params[key] = flat[key]
        if "instance_hashes" not in flat or not flat.get("instance_hashes"):
            self._params["instance_hashes"] = []
        # 21.03.15 (Bug 3): Alt-Profile mit 'YTD'/'Benutzerdefiniert' auf den
        # neuen Range-Preset-Satz abbilden (das Custom-Panel ist entfallen).
        _preset = str(self._params.get("range_preset") or "").strip() or None
        if _preset == "YTD":
            self._params["range_preset"] = "Year"
        elif _preset == "Benutzerdefiniert":
            self._params["range_preset"] = "7d"

    def set_ui_layout(self, layout: Optional[Dict[str, Any]] = None) -> None:
        """Uebernimmt das aktuelle UI-Layout fuer die Profil-Persistenz.

        10.08.2026 (Punkte 3/4): Der ViewModel kennt keine UI-Widgets
        (MVVM-Invariante 4) - das AnalyticsWindow uebergibt page_index und
        heatmap_mode vor jedem save_profile()/create_profile(); die Werte
        wandern ueber _current_payload() (Sektion "layout") in den
        Profil-Payload und werden beim _apply_profile() in
        _workspace_layout restauriert (die UI liest sie dort ueber
        workspace_layout).
        """
        self._ui_layout = dict(layout or {})

    def _current_payload(self) -> Dict[str, Any]:
        """Profil-Payload aus den aktuellen Ansichtsparametern (v2, sectioned).

        20.01 (E3): Die v2-Sektionen sources/charts/table/styling gruppieren
        die bekannten Parameter; neue UI-Settings lassen sich spaeter additiv
        unter neuen Sektionen ergaenzen (kein Schema-Bump noetig).
        """
        p = self._params
        return {
            "schema_version": SCHEMA_VERSION_DEFAULT,
            "sources": {
                "symbol": p.get("symbol"),
                "timeframe": p.get("timeframe"),
                "feature_ids": list(p.get("feature_ids") or []),
                # Runde 11 (Bug 3, B3-1): Varianten-Einschraenkung im
                # Profil-Payload persistieren (Replace-Semantik beim
                # Restore: fehlt der Key -> garantiert leer, B3-2).
                "instance_hashes": list(p.get("instance_hashes") or []),
                # 21.03.12 (MTF-FC auf Analytics): Filterleisten-Zustand
                # (data_tf/agg_tf/range) im Profil persistieren - die
                # Analysequelle, die Aggregations-TF und der Zeitraum des
                # MtfFilterBarWidget werden beim Profilwechsel restauriert.
                # 21.03.14 (Wunsch 2): `sort_mode` kommt additiv hinzu
                # (nach dem Rueckbau der View-Template-Buttons).
                "data_tf": p.get("data_tf"),
                "agg_tf": p.get("agg_tf"),
                "range_preset": p.get("range_preset"),
                "range_from": p.get("range_from"),
                "range_to": p.get("range_to"),
                "all_timeframes": p.get("all_timeframes"),
                "sort_mode": p.get("sort_mode"),
                # 21.03.20 (Analytics Modus-Filter): source_mode-Filter
                # wird additiv in der sources-Sektion persistiert
                # (Restore ueber _restore_params_from_payload).
                "service_mode": p.get("service_mode"),
            },
            "charts": {
                "heatmap_metric": p.get("heatmap_metric"),
                "scatter_x": p.get("scatter_x"),
                "scatter_y": p.get("scatter_y"),
                "distribution_column": p.get("distribution_column"),
                "bins": p.get("bins"),
                # 20.02 (E2/E3): Generische Heatmap-Config additiv unter
                # charts.heatmap (kein Schema-Bump noetig; v2-Sektionen sind
                # fuer additive UI-Settings ausgelegt, 20.01 E3).
                "heatmap": {
                    "x_dim": p.get("heatmap_x_dim"),
                    "y_dim": p.get("heatmap_y_dim"),
                    "field": p.get("heatmap_field"),
                    "agg": p.get("heatmap_agg"),
                    # 21.01 (E1): TF-Freigabe additiv persistieren.
                    "all_timeframes": p.get("heatmap_all_timeframes"),
                    "candle_projection_enabled": p.get(
                        "candle_projection_enabled"),
                    "zoom_x_range": list(p.get("zoom_x_range")
                                         or [0.0, 1.0]),
                    "zoom_y_range": list(p.get("zoom_y_range")
                                         or [0.0, 1.0]),
                },
            },
            "table": {
                "limit": p.get("limit"),
                "table_column_widths": dict(
                    p.get("table_column_widths") or {}),
                "table_row_height": p.get("table_row_height"),
                "table_sort_column": p.get("table_sort_column"),
                "table_sort_order": p.get("table_sort_order"),
            },
            "styling": {},
            # 10.08.2026 (Punkte 3/4): UI-Layout-Anteil (page_index,
            # heatmap_mode) additiv - von der UI via set_ui_layout() gesetzt.
            "layout": dict(self._ui_layout or {}),
        }

    def restore_workspace(self, workspace: Dict[str, Any]) -> None:
        """Wendet den gespeicherten Fenster-Workspace an (20.01, E7).

        Uebernimmt die Workspace-Parameter (letzter Sitzungszustand gewinnt
        ueber das aktive Profil) verlustfrei in `_params` – OHNE Dirty-Flag
        und mit demselben Resolver-Pfad wie `_apply_profile` (fehlende
        Services werden isoliert und via `missing_services_detected`
        gemeldet). Der UI-Layout-Anteil (z. B. page_index) wird separat unter
        `workspace_layout` bereitgestellt (kein `_params`-Key). Danach
        `refresh_all()` (Daten fuer alle Seiten).

        Args:
            workspace: Payload aus `state_manager.get_workspace_state(...)`
                im Format {"params": {...}, "layout": {...}}.
        """
        if not isinstance(workspace, dict):
            return
        self._workspace_layout = dict(workspace.get("layout") or {})
        params = workspace.get("params")
        if not isinstance(params, dict):
            return
        # Runde 11 (Bug 3, B3-2): Gemeinsamer Restore-Helper (Replace-
        # Semantik inkl. instance_hashes -> garantiert leer bei fehlendem
        # Payload-Key statt des alten Werts).
        self._restore_params_from_payload(params)
        # 20.02.01 (E6): Alt-Workspaces mit `dow_hour` -> "hour" (Tageszeit).
        for _hk in ("heatmap_x_dim", "heatmap_y_dim"):
            if self._params.get(_hk) == "dow_hour":
                self._params[_hk] = "hour"
        # 20.04-Q8-Fix (User-Bugreport Punkt 1a): Auch die verschachtelte
        # `charts.heatmap`-Sektion des Workspace-Params restaurieren
        # (heatmap_agg/heatmap_field) – der flache Key-Loop uebernimmt die
        # flachen Keys, aber das verschachtelte Dict (wie im Profil-Payload)
        # muss explizit via _apply_heatmap_section aufgeloest werden.
        if isinstance(params.get("heatmap"), dict):
            self._apply_heatmap_section(params.get("heatmap"))
        self._params["feature_ids"] = self._normalize_feature_ids(
            self._params.get("feature_ids"))
        # Runde 10 (Bug 1): instance_hashes genauso normalisieren.
        self._params["instance_hashes"] = self._normalize_instance_hashes(
            self._params.get("instance_hashes"))
        # 12.08.2026 (Option A): (Service|Parameter)-Auswahl des
        # 'Feld'-Dropdowns genauso normalisieren (identisch zu
        # _apply_profile).
        self._params["field_selection"] = self._normalize_field_pairs(
            self._params.get("field_selection"))
        # Runde 9 (Bug 1): Fehlende Services NUR melden, NICHT aus dem
        # Filter entfernen - der Resolver wuerde sonst den restaurierten
        # Filter stillschweigend kuerzen (die DB liefert fuer unbekannte
        # IDs einfach keine Zeilen; Graceful Degradation ohne Datenverlust).
        if self._params["feature_ids"]:
            _, missing = self._resolve_feature_ids(self._params["feature_ids"])
            if missing:
                self.missing_services_detected.emit(list(missing))
        self._params["bins"] = self._clamp_bins(self._params.get("bins"))
        self._params["limit"] = self._clamp_limit(self._params.get("limit"))
        # Runde 8 (Bugfix 3): Generation erhoehen - die UI verwirft
        # Stale-Payloads aelterer Generation (Queries, die VOR diesem
        # Workspace-Restore gestartet wurden).
        self._restore_generation += 1
        # Runde 10 (Bug 4): REIHENFOLGE - erst die UI-Combos synchronisieren
        # (params_restored), DANN die Daten anfordern. Runde 11 (A1): KEIN
        # refresh_all() mehr im Restore-Pfad - das AnalyticsWindow
        # orchestriert die Queries zentral (A6: Sync -> Query-Key-Pruefung
        # -> request_data).
        self.params_restored.emit()

    @staticmethod
    def _emit_profile_changed(name: str) -> None:
        """Emittiert profile_changed auf dem zentralen EventBus."""
        event_bus.profile_changed.emit(name or "")
