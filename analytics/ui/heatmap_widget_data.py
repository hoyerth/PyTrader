"""
heatmap_widget_data.py - Daten-Anfrage/-Empfang, Render-Generic, No-Data

23.09 God-File-Split (15.08.2026): Aus analytics/ui/heatmap_widget.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der HeatmapWidget-
Klasse als Mixin (Klasse HeatmapWidgetDataMixin).
"""

from datetime import (
    datetime,
)

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import numpy as np

from PySide6.QtCore import (
    QRectF,
)

from analytics.engine.analytics_worker import (
    QUERY_HEATMAP_GENERIC,
    QUERY_DAILY_OHLC,
    QUERY_FEATURES,
    QUERY_OHLCV,
)

from analytics.ui.heatmap_widget_constants import (
    _DIM_LABELS,
    _VIRIDIS,
)

class HeatmapWidgetDataMixin:

    def request_data(self) -> None:
        """Fordert generische Heatmap (+ OHLCV-Overlay bei Overlay) an.

        21.01 (Bugfix 5, 11.08.2026): Das Overlay laedt den OHLCV-Snapshot
        IM HEATMAP-TIMEFRAME (adaptiv fuer alle TFs) statt der festen
        Tages-Aggregation (fetch_daily_ohlc).

        Runde 15 (Ultra-Low-Latency, Fix 1): QUERY_FEATURES wird VOR der
        Grafik in die Puffer-Queue gelegt – der leichte Metadaten-Pfad
        (Reader-Cache, KEIN Heatmap-Pivot) fuellt das 'Feld'-Dropdown und
        die '(No Data)'-Hinweise, waehrend die teure Pivot-Aggregation
        danach in einem separaten Worker laeuft. Das Dropdown blockiert
        damit nicht mehr mehrere Sekunden auf der Grafik.
        """
        if self._view_model is None:
            return
        self._view_model.request_features()
        self._view_model.request_heatmap_generic()
        # Runde 12 (Option A): Zusaetzlich kommen die No-Data-Varianten im
        # QUERY_HEATMAP_GENERIC-Payload (Konsistenz nach dem Render).
        # 21.01 (Bugfix 5): Overlay-Bars im Heatmap-TF (OHLCV-Snapshot).
        if self._chk_candle.isChecked():
            self._view_model.request_ohlcv_snapshot()

    # ------------------------------------------------------------------
    # MVVM-Anbindung (von der HeatmapPage gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        self._view_model = view_model
        view_model.data_ready.connect(self._on_data_ready)
        # Runde 11 (Architektur, A3): KEINE direkte params_restored-
        # Verbindung mehr - das AnalyticsWindow orchestriert den Seiten-Sync
        # zentral via _sync_all_pages_from_params() (genau EIN Durchgang
        # nach dem VM-Param-Setzen). _sync_from_params() wird vom Window
        # explizit aufgerufen (heatmap_page._generic). Die Initial-Sync
        # unten (self._sync_from_params()) bleibt fuer den Attach-Zeitpunkt.

        # Runde 8 (Bugfix 4): feature_ids-Aenderungen (ServicePicker
        # Check/Uncheck) -> das 'Feld'-Dropdown wird SOFORT synchron neu
        # abgeleitet (kein Debounce/Query-Round-Trip). Defensiv per hasattr
        # (Test-Mocks ohne Signal).
        if hasattr(view_model, "feature_ids_changed"):
            view_model.feature_ids_changed.connect(
                self._on_feature_ids_changed)
        # Runde 11 (Bug 4, B4-2): Fehlerzustand des No-Data-Checks
        # (QUERY_FEATURES) -> 'Pruefung fehlgeschlagen'-Hinweis im
        # Feld-Dropdown (Payload-Vertrag; vorher verschluckte Fehler).
        if hasattr(view_model, "query_failed"):
            view_model.query_failed.connect(self._on_query_failed)
        self._sync_from_params()

    def is_candle_projection_enabled(self) -> bool:
        """True, wenn das Kerzen-Overlay aktiviert ist (E9)."""
        return self._chk_candle.isChecked()

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def _on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind == QUERY_HEATMAP_GENERIC:
            # Runde 12 (Option A): No-Data-Varianten aus dem HEATMAP-Payload
            # uebernehmen (Generation-Guard) VOR dem Render - die
            # '(No Data)'-Items erscheinen im selben Durchlauf wie die Grafik.
            self._cache_no_data_from_payload(data)
            self._render_generic(data)
        elif kind in (QUERY_DAILY_OHLC, QUERY_OHLCV):
            # 21.01 (Bugfix 5): QUERY_OHLCV liefert die Bars im Heatmap-TF
            # (adaptives Overlay); QUERY_DAILY_OHLC bleibt als
            # Kompatibilitaets-Pfad erhalten.
            self._render_overlay(data)
        elif kind == QUERY_FEATURES:
            # Runde 11 (Bug 4, B4-3): Kompatibilitaets-Pfad (z. B. der
            # refresh_all() der Initial-Ladung stoesst QUERY_FEATURES an).
            self._on_features_ready(data)

    def _cache_no_data_from_payload(self, data: Dict[str, Any]) -> bool:
        """Uebernimmt no_data_variants aus einem Payload (Generation-Guard).

        Runde 12 (Option A): Gemeinsamer Cache-Pfad fuer den
        QUERY_HEATMAP_GENERIC-Payload (No-Data im selben Datenfluss) und
        den QUERY_FEATURES-Kompatibilitaets-Payload. Returns False, wenn
        kein No-Data-Anteil im Payload ist (dann bleibt der Cache
        unveraendert) oder der Payload stale ist (aeltere Generation).
        """
        if self._view_model is None:
            return False
        vm = self._view_model
        payload_gen = data.get("restore_generation")
        if (payload_gen is not None
                and str(payload_gen) != str(
                    getattr(vm, "restore_generation", 0))):
            return False  # Stale-Payload (Query lief VOR dem letzten Restore)
        if "no_data_variants" not in data:
            return False  # Payload ohne No-Data-Anteil (z. B. Alt-Payload)
        variants = data.get("no_data_variants")
        self._no_data_variants = (
            [dict(v) for v in variants] if isinstance(variants, list)
            else [])
        self._no_data_variants_error = bool(
            data.get("no_data_variants_error"))
        return True

    def _on_features_ready(self, data: Dict[str, Any]) -> None:
        """Uebernimmt die No-Data-Varianten aus einem QUERY_FEATURES-Payload.

        Runde 11 (Bug 4, B4-2/B4-3): Payload-Vertrag `no_data_variants`
        IMMER vorhanden; `no_data_variants_error` markiert einen
        fehlgeschlagenen Check. Stale-Payloads werden verworfen
        (Generation-Guard). Danach wird das 'Feld'-Dropdown aus dem Cache
        neu abgeleitet (die '(No Data)'-Items erscheinen/verschwinden).

        Runde 15 (Fix 1, Ultra-Low-Latency): Der QUERY_FEATURES-Payload
        traegt jetzt zusaetzlich `metrics`/`field_sources` (Feld-Metadaten,
        Repository `_field_metadata`) – das 'Feld'-Dropdown wird damit
        BEREITS aus dem leichten Metadaten-Query gefuellt (KEIN Warten auf
        die teure Heatmap-Pivot-Aggregation).
        """
        if not self._cache_no_data_from_payload(data):
            return
        # Runde 15 (Fix 1): Feld-Metadaten aus dem Leicht-Payload uebernehmen
        # (falls vorhanden) – sonst bleibt der bestehende Widget-Cache.
        keys = [str(m) for m in (data.get("metrics") or [])
                if m not in ("count", "confluence_count")]
        field_sources = data.get("field_sources")
        if keys or field_sources:
            self._rebuild_field_dropdown(
                keys,
                field_sources if isinstance(field_sources, dict) else {})
        else:
            self._rebuild_field_dropdown(self._field_keys, self._field_sources)
        # 21.03.20 (Analytics Modus-Filter): Modus-Dropdown aus dem
        # LEICHTEN QUERY_FEATURES-Payload befuellen (`source_modes`
        # + `has_source_mode_services`; Entscheidung 2: kein Extra-
        # Roundtrip, Worker-Thread + Reader-Cache).
        self._sync_mode_filter_from_payload(data)

    def _on_query_failed(self, kind: str, _error: str) -> None:
        """Runde 11 (Bug 4, B4-2): Fehlerzustand des No-Data-Checks.

        Schlaegt die QUERY_FEATURES-Abfrage fehl (kein Payload), zeigt das
        Feld-Dropdown den 'Pruefung fehlgeschlagen'-Hinweis statt stumm zu
        bleiben (verschluckte Fehler, User-Analyse Punkt 2).
        """
        if kind == QUERY_FEATURES:
            self._no_data_variants = []
            self._no_data_variants_error = True
            self._rebuild_field_dropdown(self._field_keys,
                                         self._field_sources)

    def _render_generic(self, data: Dict[str, Any]) -> None:
        matrix = np.asarray(data.get("matrix") or [], dtype=float)
        x_dim = str(data.get("x_dim")
                    or self._combo_x.currentData() or "date")
        y_dim = str(data.get("y_dim")
                    or self._combo_y.currentData() or "hour")
        # Natuerliche Achsen-Koordinaten (Bugfix 3: Reader liefert sie).
        x_axis = data.get("x_axis") or []
        y_axis = data.get("y_axis") or []
        self._x_dates = []
        if x_dim == "date":
            for v in (data.get("x_values") or []):
                try:
                    self._x_dates.append(
                        datetime.fromisoformat(str(v)).date())
                except (TypeError, ValueError):
                    self._x_dates.append(None)
        # Combos/Slider aus dem Payload synchronisieren (tatsaechlich
        # verwendete Werte; Repository-Fallbacks z. B. fuer `field`).
        self._sync_combos_from_payload(data)
        agg = str(data.get("agg") or "count")

        # 21.03.20-Bugfix 4: Achsen-Labels VOR dem Leer-Check konfigurieren -
        # auch bei 'Keine Daten' (gewaehlter Modus ohne DB-Rows) muss die
        # Service-Beschriftung (inkl. ' / {Modus}') auf der Achse
        # aktualisiert werden (vorher blieb der alte Zustand stehen).
        x_labels = data.get("x_labels") or []
        y_labels = data.get("y_labels") or []
        if x_dim == "service_id" and self._view_model is not None:
            x_labels = [self._view_model.resolve_service_label(str(l))
                        for l in x_labels]
        if y_dim == "service_id" and self._view_model is not None:
            y_labels = [self._view_model.resolve_service_label(str(l))
                        for l in y_labels]
        self._axis_x.configure(x_dim, x_labels)
        self._axis_y.configure(y_dim, y_labels)

        if matrix.size == 0:
            self._n_cols = self._n_rows = 0
            self._x_axis = []
            self._y_axis = []
            self._image.clear()
            # 21.03.20-Bugfix 4: 'Keine Daten'-Hinweis mit Modus-Kontext
            # (erklaert, dass der gewaehlte Modus keine DB-Rows hat).
            _mode_txt = str(self._combo_mode_filter.currentData() or "all")
            self._label_info.setText(
                "Keine Daten"
                + (f" fuer Modus '{_mode_txt}'" if _mode_txt != "all" else ""))
            self._legend.hide()  # 21.01 Bugfix 2: keine Legende ohne Daten
            self._grid_lines.setData([], [])  # 21.01 R3: keine Teiler
            self._clear_overlay()
            return

        self._n_cols = int(matrix.shape[1])
        self._n_rows = int(matrix.shape[0])
        self._x_axis = [float(v) for v in (x_axis or
                                           list(range(self._n_cols)))]
        self._y_axis = [float(v) for v in (y_axis or
                                           list(range(self._n_rows)))]

        # E7: Colormap abhaengig von der Aggregation.
        if agg == "confluence_count":
            if self._colormap_mode != "confluence":
                self._image.setColorMap(self._cmap_confluence)
                try:
                    self._colorbar.setColorMap(self._cmap_confluence)
                except Exception:
                    pass
                self._colormap_mode = "confluence"
            # 21.01 (User-Meldung 7, 11.08.2026): Die festen Levels
            # (0.0, 5.0) passten nicht zu echten Daten (Max ~1) - die
            # Farbgraduierung blieb stumpf (fast nur Weiss/Gelb). Die
            # Levels werden jetzt DATEN-GEBUNDEN gesetzt: 0 (keine
            # Konfluenz) = weiss, vmax = staerkste Farbe (dunkelrot).
            finite = matrix[np.isfinite(matrix)]
            if finite.size:
                vmax = float(finite.max())
                vmin = min(0.0, float(finite.min()))
            else:
                vmin, vmax = 0.0, 1.0
            if vmax <= vmin:
                vmax = vmin + 1.0
            self._image.setImage(matrix, levels=(vmin, vmax))
            self._colorbar.setLevels((vmin, vmax))
        else:
            if self._colormap_mode != _VIRIDIS:
                self._image.setColorMap(self._cmap_viridis)
                try:
                    self._colorbar.setColorMap(self._cmap_viridis)
                except Exception:
                    pass
                self._colormap_mode = _VIRIDIS
            finite = matrix[np.isfinite(matrix)]
            if finite.size:
                vmin = float(finite.min())
                vmax = float(finite.max())
                if vmin == vmax:
                    vmax = vmin + 1.0
            else:
                vmin, vmax = 0.0, 1.0
            self._image.setImage(matrix, levels=(vmin, vmax))
            self._colorbar.setLevels((vmin, vmax))

        # 21.01 (Bugfix 2): Diskrete Schwellwert-Legende (oben rechts)
        # an die aktuelle Colormap/Levels anpassen.
        self._update_legend()

        # ImageItem exakt auf die natuerlichen Koordinaten mappen (Bugfix 3):
        # date-Spalten = Tage (zentriert auf Mitternacht), hour/dow =
        # ganzzahlige Werte (feste Skalen, E3/E5), kategorial = Indizes.
        # Nichts wird ueber die Tagesgrenze hinaus gezeichnet (Punkt 3).
        self._x_min, self._x_max = self._axis_bounds(self._x_axis, x_dim)
        self._y_min, self._y_max = self._axis_bounds(self._y_axis, y_dim)
        self._image.setRect(QRectF(
            self._x_min, self._y_min,
            self._x_max - self._x_min, self._y_max - self._y_min))

        # 21.01 (Bugfix-Runde 3, Entscheidung 2a): Senkrechte Teiler je
        # Dateneinheit (TF-Bar-Intervall) an der X-Achse (date).
        self._update_grid_lines()

        # 20.02.01 (E4): Achsen-Label der Tageszeit mit UTC-Offset –
        # DST-robust aus dem neuesten Datumswert der Daten abgeleitet
        # (kein Berlin-Offset, Invariante 7; die Epochs sind Wanduhr-encoded).
        offset_epoch: Optional[float] = None
        if x_dim == "date" and self._x_axis:
            offset_epoch = self._x_axis[-1]
        elif y_dim == "date" and self._y_axis:
            offset_epoch = self._y_axis[-1]
        offset_text = self._utc_offset_text(offset_epoch)
        label_x = _DIM_LABELS.get(x_dim, x_dim)
        label_y = _DIM_LABELS.get(y_dim, y_dim)
        # 09.08.2026 (User-Meldung): Die date-Achse heisst 'Datum/Zeit'
        # (ohne pyqtgraph-EXP-Suffix – das unterdrueckt _HeatmapAxis via
        # enableAutoSIPrefix(False), s. o.).
        if x_dim == "date":
            label_x = "Datum/Zeit"
        if y_dim == "date":
            label_y = "Datum/Zeit"
        if x_dim == "hour":
            label_x = f"{label_x} ({offset_text})"
        if y_dim == "hour":
            label_y = f"{label_y} ({offset_text})"
        self._plot_hm.setLabel("bottom", label_x)
        self._plot_hm.setLabel("left", label_y)

        self._apply_x_range()
        self._apply_y_range()
        self._label_info.setText(f"{self._n_rows} x {self._n_cols}")

        # Bugfix 1/2 + 21.01 Bugfix 5: Bei aktivem Overlay den OHLCV-
        # Snapshot IM HEATMAP-TIMEFRAME laden (adaptiv fuer alle TFs).
        if self._chk_candle.isChecked() and self._view_model is not None:
            self._view_model.request_ohlcv_snapshot()

    def _render_no_data_items(self) -> None:
        """Rendert die No-Data-Hinweise aus dem Payload-Cache (B4-2/B4-5).

        Runde 11 (Bug 4): Die '(No Data)'-Varianten kommen vom
        QUERY_FEATURES-Worker (`no_data_variants` im Payload) - kein
        synchroner DB-Zugriff mehr. Die Anzeige unterscheidet:
          * Payload ausstehend (self._no_data_variants is None) -> nichts
          * Payload-Fehler   -> '⚠️ No-Data-Prüfung ...' (deaktiviert)
          * Erfolg + Liste   -> '(No Data)'-Abschnitt (deaktivierte Items)

        Runde 13 (Bugfix Dropdown-NoData): Der Payload ist seit dem
        Reader-Hash-Filter bereits VARIANTEN-GENAU - `no_data_variants`
        enthaelt nur noch die im ServicePicker gecheckten Varianten
        (und nur Services aus `feature_ids`). Die Widget-seitigen Filter
        (active_ids/active_hashes) sind damit redundant, bleiben aber
        DEFENSIV aktiv (schuetzt z. B. gegen Alt-Payloads vom
        QUERY_FEATURES-Kompatibilitaetspfad ohne Hash-Filter). Die
        gewaehlte Variante ist in Runde 13 immer Teil des Abschnitts -
        die B4-5-Inline-Ergaenzung greift nur noch bei Defensiv-Luecken.

        Runde 13c (Kernwunsch): Bei leerem feature_ids-Filter (leer =
        kein Filter = alle Features) wird KEIN '(No Data)'-Abschnitt UND
        kein No-Data-Fehlerhinweis gerendert - der Button 'Aktive Filter
        entfernen' zeigt danach wieder alle Features ohne NoData-Rauschen
        (der VM-Snapshot liefert bei leerem Filter bereits keine
        Varianten; dieser Guard schuetzt zusaetzlich gegen Alt-/
        Stale-Payloads).
        """
        if self._view_model is None:
            return
        p = self._view_model.params
        # Runde 12 (Punkt 4) + Runde 13c (Kernwunsch): Nur Services im
        # aktiven feature_ids-Filter duerfen NoData-Hinweise liefern.
        # Leerer Filter (leer = kein Filter = alle Features) -> KEINE
        # Hinweise (auch kein Fehler-/Loading-Hinweis), damit der Button
        # 'Aktive Filter entfernen' alle Features ohne NoData-Rauschen
        # zeigt.
        active_ids = {str(f).strip().lower()
                      for f in (p.get("feature_ids") or [])}
        if not active_ids:
            return
        if self._no_data_variants_error:
            self._combo_field.add_disabled_item(
                "⚠️ No-Data-Prüfung konnte nicht durchgeführt werden")
            return
        if self._no_data_variants is None:
            return  # Loading: Payload steht noch aus (kein Hinweis noetig)
        # Runde 13: `instance_hashes` ist seit dem MasterTree-Fix auch fuer
        # Set-Instanz-Varianten (TYPE_SERVICE) gefuellt. Der Reader filtert
        # den Payload bereits danach - hier defensiv gegen Alt-Payloads.
        active_hashes = {str(h).strip().lower()
                         for h in (p.get("instance_hashes") or [])}
        variants = [dict(v) for v in self._no_data_variants]
        filtered = variants
        if active_ids:
            filtered = [v for v in filtered
                        if str(v.get("plugin_id") or "").strip().lower()
                        in active_ids]
        # Runde 16 (Bugfix Mischbetrieb, User-Meldung 5/6, 11.08.2026):
        # Hash-lose Varianten (Standalone-Services wie srv_trend_breakout
        # und NULL-Hash-Alt-Bestand) werden UEBER `feature_ids` gecheckt -
        # eine aktive Hash-Auswahl darf sie nicht aus dem '(No Data)'-
        # Abschnitt werfen (sonst verschwinden Services im Mischbetrieb
        # aus dem Feld-Dropdown, obwohl sie gecheckt sind).
        if active_hashes:
            filtered = [v for v in filtered
                        if not str(v.get("instance_hash") or "").strip()
                        or str(v.get("instance_hash") or "").strip().lower()
                        in active_hashes]
        if not filtered and self._selected_no_data_variant(variants) is None:
            return
        self._combo_field.add_header_item(
            "🕓 Noch ohne Daten (erster Scan ausstehend):")
        rendered: set = set()
        for nd in filtered:
            rendered.add((str(nd.get("plugin_id") or "").strip().lower(),
                          str(nd.get("instance_hash") or "").strip().lower()))
            # Runde 11 (B4-2): display_name enthaelt den Preset bereits
            # (resolve_service_display_name/Reader-Fallback) - keine
            # doppelte '(preset)'-Ergaenzung im Item-Text.
            self._combo_field.add_disabled_item(
                f"{nd.get('display_name') or nd.get('plugin_id')} – (No Data)")
        # B4-5 (Runde 13): Die gewaehlte Variante bleibt zusaetzlich inline
        # sichtbar (ausgegraut) - defensiv: nur wenn die Widget-Filter sie
        # wider Erwarten nicht im Abschnitt haetten (Reader-Hash-Filter
        # und Widget-Filter koennen nicht divergieren, solange beide auf
        # `instance_hashes` basieren).
        sel = self._selected_no_data_variant(variants)
        if sel is not None:
            key = (str(sel.get("plugin_id") or "").strip().lower(),
                   str(sel.get("instance_hash") or "").strip().lower())
            if key not in rendered:
                self._combo_field.add_disabled_item(
                    f"→ {sel.get('display_name') or sel.get('plugin_id')} – (No Data)")

    def _selected_no_data_variant(
        self, variants: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """No-Data-Variante des aktuell gewaehlten Feld-Items (oder None).

        Runde 12 (Punkt 3): Das Feld-Item-userData traegt '{service_id}|{key}'
        (ein Feld-Item repraesentiert einen SERVICE, nicht eine Variante) -
        die GEWAEHLTE Variante wird ueber den aktiven instance_hashes-Filter
        des ServicePickers identifiziert: Liefert der Service mehrere
        No-Data-Varianten, gewinnt die gecheckte Variante (exakter Hash-
        Match) statt immer der ersten. Runde 12 (Punkt 4): Services, die
        NICHT im aktiven feature_ids-Filter liegen, werden ignoriert
        (None - keine Inline-Markierung fuer nicht gecheckte Services).

        Runde 13 (Bugfix Dropdown-NoData): Der Payload (`no_data_variants`)
        ist seit dem Reader-Hash-Filter bereits VARIANTEN-GENAU - er enthaelt
        nur noch die im ServicePicker gecheckten Varianten. Die ausgewaehlte
        No-Data-Variante des aktuellen Feld-Services ist damit EINDEUTIG
        bestimmt (hoechstens eine Variante pro Service uebrig). Der alte
        'erste Variante des Services'-Fallback ist ersatzlos entfernt: Er
        zeigte bei aktiver Varianten-Einschraenkung faelschlich die ERSTE
        Variante (V1), obwohl eine andere (V2) gecheckt und V1 gar nicht
        aktiv war - die Runde-12b-Einschraenkung (kein Fallback bei nicht
        leerem instance_hashes) war unvollstaendig, weil `instance_hashes`
        fuer Set-Instanz-Varianten bis Runde 13 leer blieb.

        Runde 13c (Bug 1-Absicherung): Falls ein Payload aus einem Alt-/
        Kompatibilitaetspfad doch mehrere No-Data-Varianten desselben
        Services enthaelt, gewinnt DEFENSIV die im ServicePicker gecheckte
        Variante (instance_hash in `instance_hashes`) statt der ersten
        Liste. Erst ohne Hash-Match faellt die Auswahl auf den ersten
        Service-Treffer zurueck (hash-lose Variante/kein Filter).
        """
        if not variants:
            return None
        if self._view_model is None:
            return None
        p = self._view_model.params
        data = self._combo_field.currentData()
        sid = None
        if isinstance(data, str) and "|" in data:
            sid = data.split("|", 1)[0].strip().lower()
        if not sid:
            return None
        # Punkt 4: Nur Services im aktiven feature_ids-Filter (leer = alle).
        active_ids = {str(f).strip().lower()
                      for f in (p.get("feature_ids") or [])}
        if active_ids and sid not in active_ids:
            return None
        # Runde 13: Der Payload ist bereits variantengefiltert (Reader-
        # Hash-Filter auf active_hashes). Die No-Data-Variante des aktuellen
        # Feld-Services im Payload IST die ausgewaehlte - kein Fallback auf
        # die 'erste Variante' mehr (die gecheckte Variante gewinnt, weil
        # nur sie im Payload steht).
        #
        # Runde 13c (Bug 1-Absicherung): Bei mehreren No-Data-Varianten
        # desselben Services gewinnt DEFENSIV die im ServicePicker gecheckte
        # Variante (instance_hash in active_hashes) statt der ersten Liste
        # - falls der Payload aus einem Alt-/Kompatibilitaetspfad doch
        # mehrere Varianten enthaelt. Erst wenn kein Hash-Match vorliegt
        # (hash-lose Variante/kein Filter), faellt die Auswahl auf den
        # ersten Service-Treffer zurueck.
        p_hashes = {str(h).strip().lower()
                    for h in (p.get("instance_hashes") or [])}
        if p_hashes:
            for v in variants:
                if (str(v.get("plugin_id") or "").strip().lower() == sid
                        and str(v.get("instance_hash") or "").strip().lower()
                        in p_hashes):
                    return v
        for v in variants:
            if str(v.get("plugin_id") or "").strip().lower() == sid:
                return v
        return None
