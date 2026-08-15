"""
heatmap_widget_controls.py - Steuer-/Config-Sync, Combos, Slider, Config/Modus-Sync

23.09 God-File-Split (15.08.2026): Aus analytics/ui/heatmap_widget.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der HeatmapWidget-
Klasse als Mixin (Klasse HeatmapWidgetControlsMixin).
"""

from typing import (
    Any,
    Dict,
)

import pyqtgraph as pg

from PySide6.QtWidgets import (
    QComboBox,
    QSlider,
)

from analytics.ui.heatmap_widget_constants import (
    _PRICE_LIKE_KEY_HINTS,
    _VALUE_AGGS,
)

def _is_price_like_key(key: str) -> bool:
    """True fuer preisartige feature_data-Keys (13.08.2026, F5)."""
    k = str(key or "").lower()
    return any(h in k for h in _PRICE_LIKE_KEY_HINTS) if k else False


class HeatmapWidgetControlsMixin:

    # ------------------------------------------------------------------
    # Sync aus den ViewModel-_params (Profil/Workspace-Restore)
    # ------------------------------------------------------------------
    def _sync_from_params(self) -> None:
        if self._view_model is None:
            return
        p = self._view_model.params
        self._syncing = True
        try:
            self._set_combo_data(
                self._combo_x, str(p.get("heatmap_x_dim") or "date"))
            self._set_combo_data(
                self._combo_y, str(p.get("heatmap_y_dim") or "hour"))
            self._set_combo_data(
                self._combo_agg,
                str(p.get("heatmap_agg") or "confluence_count"))
            # 21.03.20 (Analytics Modus-Filter): Modus-Auswahl aus
            # den VM-Params wiederherstellen (Profil-/Workspace-
            # Restore; unbekannte Werte werden additiv ergaenzt).
            self._set_combo_data(
                self._combo_mode_filter,
                str(p.get("service_mode") or "all"))
            # Runde 8 (Bugfix 3): Das 'Feld'-Dropdown wird aus den gecachten
            # Feld-Metadaten (self._field_keys/self._field_sources) + den
            # aktuellen VM-Params SYNCHRON neu abgeleitet (Items, Haken,
            # Current). Ein restaurierter heatmap_field bleibt dadurch auch
            # ohne frischen Daten-Payload sichtbar (Fallback-Roh-Item, wenn
            # noch keine Payload-Metadaten vorliegen).
            self._rebuild_field_dropdown(self._field_keys,
                                         self._field_sources)
            # 21.01 (User-Meldung 5, 11.08.2026): Das Kerzen-Overlay wird
            # NUR wiederhergestellt, wenn die X-Achse = 'date' ist. Bei
            # Y=date/anderen Achsen bleibt die Checkbox aus (verhindert
            # ein ungewolltes Dirty-Setzen via _update_controls beim
            # Profil-/Workspace-Restore).
            self._chk_candle.setChecked(bool(
                p.get("candle_projection_enabled"))
                and str(p.get("heatmap_x_dim") or "date") == "date")
            self._set_zoom_slider(self._slider_zoom_x,
                                  p.get("zoom_x_range") or [0.0, 1.0])
            self._set_zoom_slider(self._slider_zoom_y,
                                  p.get("zoom_y_range") or [0.0, 1.0])
        finally:
            self._syncing = False
        self._update_controls()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        """Setzt die Combo auf `value` (fuegt unbekannte Werte additiv hinzu)."""
        combo.blockSignals(True)
        try:
            idx = combo.findData(value)
            if idx < 0:
                combo.addItem(str(value), value)
                idx = combo.count() - 1
            combo.setCurrentIndex(idx)
        finally:
            combo.blockSignals(False)

    @staticmethod
    def _set_zoom_slider(slider: QSlider, zrange: Any) -> None:
        """Stellt den Zoom-Slider aus einem [lo, hi]-Bereich ein (E8).

        09.08.2026 (User-Meldung 2): Inverse Umrechnung zu `_set_zoom_range`
        – volle Achse (span 1.0) => Slider 5 (links), maximale Vergroesserung
        (span 0.05) => Slider 100 (rechts).
        """
        try:
            lo, hi = float(zrange[0]), float(zrange[1])
        except (TypeError, ValueError, IndexError):
            lo, hi = 0.0, 1.0
        if hi <= lo:
            lo, hi = 0.0, 1.0
        value = int(round(105.0 - (hi - lo) * 100.0))
        slider.blockSignals(True)
        slider.setValue(max(slider.minimum(), min(slider.maximum(), value)))
        slider.blockSignals(False)

    def _update_controls(self) -> None:
        """Aktiviert/Deaktiviert Feld-Combo und Overlay (E6/E9).

        Bugfix 09.08.2026 (Punkt 6): Die Zoom-Slider gelten fuer ALLE
        Dimensionen/Massstaebe (nicht nur date) – je Zoom-Level werden
        dynamisch mehr Zwischenwerte auf den Achsen angezeigt.
        """
        if self._view_model is None:
            return
        x_dim = str(self._combo_x.currentData() or "")
        y_dim = str(self._combo_y.currentData() or "")
        agg = str(self._combo_agg.currentData() or "")
        self._slider_zoom_x.setEnabled(True)
        self._slider_zoom_y.setEnabled(True)
        is_value_agg = agg in _VALUE_AGGS
        # 13.08.2026 (Punkt 5, F5): SUM fuer preisartige Felder sperren
        # (unsinnig hohe Legendenwerte); Signal-Felder (strength_value)
        # bleiben erlaubt. Ist SUM gerade aktiv und das Feld preisartig,
        # wird implizit auf AVG gewechselt (VM-Config + Refresh idempotent).
        active_field = self._field_key(self._combo_field.currentData())
        # 13.08.2026 (Punkt 5, F5): Modul-Funktion (kein self.) - die
        # Helfer ist als reine Funktion definiert (SRP, kein Widget-Zustand).
        price_like = _is_price_like_key(active_field)
        sum_idx = self._combo_agg.findData("sum")
        if sum_idx >= 0:
            _sum_item = self._combo_agg.model().item(sum_idx)
            if _sum_item is not None:
                _sum_item.setEnabled(not price_like)
        if price_like and agg == "sum":
            self._set_combo_data(self._combo_agg, "avg")
            agg = "avg"
            is_value_agg = True
            self._apply_config()
        self._combo_field.setEnabled(is_value_agg)
        if is_value_agg:
            self._combo_field.setToolTip(
                "Numerischer feature_data-JSON-Key (Feld) fuer AVG/SUM/MIN/MAX.")
        else:
            self._combo_field.setToolTip(
                "Nur fuer AVG/SUM/MIN/MAX relevant (E6); COUNT/CONFLUENCE "
                "ignorieren das Feld.")
        # 21.01 (User-Meldung 5, 11.08.2026): Das Kerzen-Overlay ist NUR
        # bei X-Achse = 'date' aktivierbar (Y=date/vertikale Anordnungen
        # sind keine offiziellen Ansichten mehr). Bei Y=date wird die
        # Checkbox hier deaktiviert und zurueckgesetzt (Restore-Fall).
        date_on_x = x_dim == "date"
        can_overlay = date_on_x
        self._chk_candle.setEnabled(can_overlay)
        if can_overlay:
            self._chk_candle.setToolTip(
                "Tages-Ohlc ueber der Heatmap (gleicher Canvas), "
                "Datum auf der X-Achse.")
        else:
            self._chk_candle.setToolTip(
                "Kerzen-Overlay nur mit 'Datum' auf der X-Achse "
                "verfuegbar.")
            # Meldung 5: Reste eines Overlays entfernen (loest
            # _on_candle_toggled(False) aus -> set_candle_projection(False)
            # + _clear_overlay im ViewModel/Widget).
            if self._chk_candle.isChecked():
                self._chk_candle.setChecked(False)
        # Meldung 5: Der Overlay-Link folgt NUR noch der X-Achse (date).
        # Ohne Overlay werden beide Links entfernt.
        link = can_overlay and self._chk_candle.isChecked()
        linked_x = self._price_vb.linkedView(pg.ViewBox.XAxis)
        linked_y = self._price_vb.linkedView(pg.ViewBox.YAxis)
        if link and linked_x is None:
            self._price_vb.setXLink(self._plot_hm.plotItem.vb)
        if link and linked_y is not None:
            self._price_vb.setYLink(None)
        if not link:
            if linked_x is not None:
                self._price_vb.setXLink(None)
            if linked_y is not None:
                self._price_vb.setYLink(None)

    # ------------------------------------------------------------------
    # Konfiguration -> ViewModel (Debounce -> Worker)
    # ------------------------------------------------------------------
    def _on_config_changed(self, *args) -> None:
        if self._syncing or self._view_model is None:
            return
        # Identische Achsen vermeiden (degenerierte Diagonal-Matrix).
        if self._combo_x.currentData() == self._combo_y.currentData():
            self._syncing = True
            try:
                fallback = ("hour" if self._combo_x.currentData() != "hour"
                            else "dow")
                self._set_combo_data(self._combo_y, fallback)
            finally:
                self._syncing = False
        # Overlay nur bei X=date (E9 / 21.01 User-Meldung 5) – sonst
        # ausschalten (Y=date ist keine offizielle Overlay-Ansicht mehr).
        if (self._combo_x.currentData() != "date"
                and self._chk_candle.isChecked()):
            self._chk_candle.setChecked(False)
        self._update_controls()
        self._apply_config()
        self.request_data()

    def _on_agg_changed(self, *args) -> None:
        if self._syncing or self._view_model is None:
            return
        self._update_controls()
        self._apply_config()
        self.request_data()

    def _on_mode_filter_changed(self, *args) -> None:
        """21.03.20: Modus-Filter-Aenderung -> ViewModel (global).

        `set_service_mode` stoesst intern den Refresh von
        QUERY_FEATURES + allen Datenquellen an (Tabelle, beide
        Heatmaps, Scatter, Verteilung - Entscheidung 1). Der
        _syncing-Guard verhindert Endlos-Schleifen.
        """
        if self._syncing or self._view_model is None:
            return
        mode = str(self._combo_mode_filter.currentData() or "all")
        self._view_model.set_service_mode(mode)

    def _apply_config(self) -> None:
        self._view_model.set_heatmap_config(
            x_dim=str(self._combo_x.currentData() or "date"),
            y_dim=str(self._combo_y.currentData() or "hour"),
            # 20.03.02 (F2): Aus dem '{service_id}|{key}'-userData nur den
            # JSON-Key extrahieren (heatmap_field bleibt ein reiner Key).
            field=self._field_key(self._combo_field.currentData()),
            agg=str(self._combo_agg.currentData() or "confluence_count"),
        )

    def _sync_combos_from_payload(self, data: Dict[str, Any]) -> None:
        """Synchronisiert die Combos mit dem tatsaechlichen Payload."""
        if self._view_model is None:
            return
        vm = self._view_model
        metrics = [str(m) for m in (data.get("metrics") or [])]
        keys = [m for m in metrics if m not in ("count", "confluence_count")]
        # 20.02.01 (User-Meldung 3b): Key -> Services, die ihn liefern
        # (Repository `field_sources`); Anzeige '{Service} / {Key}'.
        field_sources = data.get("field_sources") or {}
        # Runde 8 (Bugfix 3): Stale-Payload-Guard. Der Worker spiegelt die
        # Generation der Query-Params ins Ergebnis-Dict - Queries, die VOR
        # dem letzten restore_workspace()/_apply_profile() gestartet wurden,
        # tragen eine aeltere Generation. Deren Feld-Metadaten duerfen den
        # synchron restaurierten Zustand NICHT ueberschreiben (die x/y/agg-
        # Combos werden trotzdem mit VM-Prioritaet bestaetigt).
        payload_gen = data.get("restore_generation")
        stale = (payload_gen is not None
                 and str(payload_gen) != str(
                     getattr(vm, "restore_generation", 0)))
        # Runde 11 (Architektur, A5): Die x/y/agg-Combos werden NICHT mehr
        # aus dem Payload synchronisiert - die Controls sind Single Source
        # of Truth (Restore-/User-Auswahl gewinnt, kein Ueberschreiben).
        self._syncing = True
        try:
            if not stale:
                # Feld-Metadaten uebernehmen + 'Feld'-Dropdown synchron neu
                # ableiten (Items/Haken/Current; Runde 8, Bug 3/4). Bei
                # stale Payloads bleibt der Zustand aus _sync_from_params
                # unveraendert.
                self._rebuild_field_dropdown(
                    keys, field_sources,
                    payload_agg=str(data.get("agg") or ""),
                    payload_field=str(data.get("field") or ""))
            # Runde 11 (Bug 4, B4-1): '(No Data)'-Hinweise rendert
            # _rebuild_field_dropdown() zentral aus dem Payload-Cache
            # (self._no_data_variants aus QUERY_FEATURES).
        finally:
            self._syncing = False
        self._update_controls()

    def _sync_mode_filter_from_payload(self, data: Dict[str, Any]) -> None:
        """Befuellt das Modus-Dropdown aus dem QUERY_FEATURES-Payload.

        21.03.20 (Entscheidung 2/4): `source_modes` (distinct, case-original)
        fuellt die Items (itemData = Modus-Wert). `has_source_mode_services
        == False` deaktiviert die Combo und setzt den Filter auf "all"
        zurueck (kein aktiver Service schreibt source_mode). Stale-Payloads
        werden verworfen (Generation-Guard, Muster _sync_combos_from_payload).
        """
        if self._view_model is None:
            return
        vm = self._view_model
        payload_gen = data.get("restore_generation")
        if (payload_gen is not None
                and str(payload_gen) != str(
                    getattr(vm, "restore_generation", 0))):
            return  # Stale-Payload (Query lief VOR dem letzten Restore)
        modes = [str(m) for m in (data.get("source_modes") or [])]
        has_sm = bool(data.get("has_source_mode_services"))
        self._syncing = True
        try:
            self._combo_mode_filter.blockSignals(True)
            self._combo_mode_filter.clear()
            self._combo_mode_filter.addItem("[Alle Modi]", "all")
            for m in modes:
                if str(m).strip():
                    self._combo_mode_filter.addItem(
                        str(m).strip(), str(m).strip())
            # Deaktivierung: Combo aus + Filter auf "all" zuruecksetzen
            # (idempotent - set_service_mode("all") refresh-t nur bei
            # tatsaechlicher Aenderung).
            if not has_sm:
                self._combo_mode_filter.setEnabled(False)
                if str(vm.params.get("service_mode") or "all") != "all":
                    vm.set_service_mode("all")
            else:
                self._combo_mode_filter.setEnabled(True)
            # Auswahl aus den VM-Params wiederherstellen (Restore gewinnt).
            self._set_combo_data(
                self._combo_mode_filter,
                str(vm.params.get("service_mode") or "all"))
        finally:
            self._combo_mode_filter.blockSignals(False)
            self._syncing = False

    def _on_feature_ids_changed(self) -> None:
        """Synchrones Neu-Ableiten des Feld-Dropdowns bei Check/Uncheck.

        Runde 8 (Bugfix 4): `set_feature_ids()` emittiert
        feature_ids_changed, sobald der ServicePicker-Haken geaendert wird -
        Items/Haken/Current werden SOFORT aus den gecachten Feld-Metadaten
        und den aktuellen feature_ids neu abgeleitet (Single Source of
        Truth = Picker; kein Debounce/Query-Round-Trip noetig).
        """
        if self._syncing or self._view_model is None:
            return
        self._syncing = True
        try:
            self._rebuild_field_dropdown(self._field_keys,
                                         self._field_sources)
        finally:
            self._syncing = False
