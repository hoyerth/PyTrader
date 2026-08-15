"""
chart/chart_win_render.py - Render-/Serializer-Methoden des Chart-Fensters (Render-Payload, Grid-Serialisierung)

23.03 God-File-Split (15.08.2026): Aus chart/chart_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt die Methoden der PyTraderChartWindow
als Mixin (Klasse ChartRenderMixin).
"""

from typing import Dict, Optional

from chart.chart_win_workers import GridDataSerializer

class ChartRenderMixin:

    def _collect_render_payload(self, time_from: Optional[int] = None,
                                time_to: Optional[int] = None) -> Dict[str, list]:
        """P16.05 (Prework Schritt 1, F1/P-C2): Sammelt das generische
        Render-Payload über ALLE aktiven Indikatoren.

        Aggregiert die Keys `lines` (Zeitreihen-LineSeries, z. B. Multi-MA),
        `price_lines` (horizontale Grid-Preislinien) und `hit_circles`
        (Marker) zu einem einzigen Dict. Keine Indikator-spezifischen
        Branches mehr (Open/Closed, Invariante 9). Circle- und Linien-Zeiten
        (reale Wanduhr-Epochs) werden generisch auf kontinuierliche Zeiten
        gemappt (P-D1 / Ergänzung 1: `_time_real_to_cont.get(ts, ts)`).

        Phase 16.07 (D1/D5): `time_from`/`time_to` (reale Wanduhr-Epochs,
        inklusiv) grenzen den Render-Payload auf ein Zeitfenster ein:
        * render_indicators(): Tier-1-Fenster [self._js_window_first_real,
          self._js_window_last_real] – verhindert, dass Linien/Circles über
          die sichtbaren Kerzen hinausragen (Two-Tier, D1).
        * Chunk-Delta: [neue linke Kante, Fenster-Rechtskante].
        None = keine Filterung (Bestandsverhalten, P16.05-Tests).
        """
        payload: Dict[str, list] = {
            "lines": [], "price_lines": [], "hit_circles": [],
        }
        if self.df_data is None or self.df_data.empty:
            return payload

        for ind_id, plugin in self.indicators.items():
            st = self.indicators_state.get(ind_id, {})
            if not st.get("active"):
                continue
            try:
                # Kontext setzen (Symbol/TF fuer DB-basierte Indikatoren)
                if hasattr(plugin, "set_context"):
                    plugin.set_context(self.current_symbol, self.current_tf)
                # 5.4 Schritt 2: Parameter aus set_id (Logik) + display_params
                # (Darstellung) auflösen – Legacy voller params bleibt erhalten.
                res = plugin.calculate(
                    self.df_data, self._resolve_indicator_params(ind_id, st))
            except (RuntimeError, AttributeError):
                continue
            if not isinstance(res, dict):
                continue
            for key in ("lines", "price_lines", "hit_circles"):
                items = res.get(key)
                if not items:
                    continue
                # Zeit-Mapping real→kontinuierlich (nur Zeitreihen-Keys;
                # price_lines sind horizontale Preislinien ohne Zeit).
                if key in ("lines", "hit_circles") and self._time_real_to_cont:
                    if key == "lines":
                        # LineSeries-Format: {id, data:[{time, value, color}]}
                        # – die Zeit steckt in den Datenpunkten (data).
                        # 22.01e (Performance-Fix): Series, deren Datenpunkte
                        # nach dem Zeitfenster-Filter vollstaendig ausserhalb
                        # liegen, werden VERWORFEN (nicht an JS gesendet) –
                        # vorher ging z. B. jede ind_peak-Strich-Serie (auch
                        # leere) als addSeries an LWC -> tausende Series.
                        filtered_items = []
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            keep_pts = []
                            for pt in (item.get("data") or []):
                                if not isinstance(pt, dict):
                                    continue
                                pt_t = pt.get("time")
                                if pt_t is None:
                                    continue
                                try:
                                    pt_t = int(pt_t)
                                except (TypeError, ValueError):
                                    continue
                                # Phase 16.07: Zeitfenster-Filter (real,
                                # inklusiv) – Warmup-Punkte (D6, verworfen)
                                # und Punkte ausserhalb des Fensters fallen weg.
                                if time_from is not None and pt_t < time_from:
                                    continue
                                if time_to is not None and pt_t > time_to:
                                    continue
                                pt["time"] = self._time_real_to_cont.get(pt_t, pt_t)
                                keep_pts.append(pt)
                            item["data"] = keep_pts
                            if keep_pts:
                                filtered_items.append(item)
                        items = filtered_items
                    else:
                        # Marker-Format: {time, price, ...} – Zeit auf oberster
                        # Ebene des Items (Circle).
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            gc_t = item.get("time")
                            if gc_t is None:
                                continue
                            try:
                                gc_t = int(gc_t)
                            except (TypeError, ValueError):
                                continue
                            if time_from is not None and gc_t < time_from:
                                continue
                            if time_to is not None and gc_t > time_to:
                                continue
                            item["time"] = self._time_real_to_cont.get(gc_t, gc_t)
                payload[key].extend(items)
        return payload

    def render_indicators(self):
        """Rendert alle aktiven Indikatoren via JS-Bridge.

        P16.05 (Prework Schritt 1): Generische Pipeline statt Indikator-
        Branches – das aggregierte Render-Payload wird 1:1 per
        applyChartRenderPayload an JS durchgereicht (P-D1, F1).

        Phase 16.07 (D1): Das Payload wird auf das Tier-1-Fenster
        [self._js_window_first_real, self._js_window_last_real] begrenzt,
        damit Linien/Circles nicht über die sichtbaren Kerzen hinausragen
        (Two-Tier; die Berechnung selbst läuft über den vollen Tier-2-Puffer).
        """
        if self.df_data is None or self.df_data.empty:
            return

        # 22.01h (Bugfix "Objekte vor vorhandenen Kerzen"): Die Tier-1-Fenster-
        # Bounds sind die Filter-Grenze gegen LWC-Phantom-Slots. Sind sie None
        # (Toggle/Param-Aenderung VOR dem ersten vollstaendigen Refresh), geht
        # der komplette historische Record-Bestand ungefiltert an JS (Objekte
        # vor den aeltesten Kerzen). Defensiv aus dem Datenpuffer ableiten.
        if (self._js_window_first_real is None
                or self._js_window_last_real is None):
            self._derive_js_window_bounds_from_buffer()
        payload = self._collect_render_payload(
            time_from=self._js_window_first_real,
            time_to=self._js_window_last_real)

        # P14-03-E (Flacker-Fix): calculate() resettet die _known_times der
        # Indikatoren – die offene Live-Bar generisch wieder einfügen, damit
        # der New-Candle-Callback nicht erneut feuert (Flacker-Zyklus).
        self._reinject_live_bar_to_indicators()

        # JSON-Encoding im Hintergrund (F4: Threading-Muster exakt beibehalten)
        self._serialize_and_render_grid(payload)

    def _derive_js_window_bounds_from_buffer(self) -> None:
        """22.01h (Bugfix "Objekte vor vorhandenen Kerzen"): Leitet die
        Tier-1-Fenster-Bounds (reale Wanduhr-Epochs) defensiv aus dem
        Datenpuffer ab - NUR wenn sie noch nicht gesetzt sind (idempotent).

        Fallback, wenn die Bounds noch nicht aus einem vollstaendigen Refresh
        gesetzt wurden (z. B. Indikator-Toggle / Parameter-Aenderung direkt
        nach dem Start oder nach einem Symbol/TF-Wechsel). Ohne diese Bounds
        haette der _collect_render_payload-Zeitfenster-Filter keine Grenze und
        historische Records (z. B. 2013 auf H1/D1 aus Service-Laeufen mit
        vollem Historien-Scan) wuerden als LWC-Phantom-Slots weit links der
        sichtbaren Kerzen erscheinen (Objekte vor 2024).
        """
        if (self._js_window_first_real is not None
                and self._js_window_last_real is not None):
            return
        n_win = min(self.chart_buffer.TIER1_WINDOW, len(self.chart_buffer.candles))
        if n_win > 0:
            if self._js_window_first_real is None:
                self._js_window_first_real = int(
                    self.chart_buffer.candles[-n_win]["time"])
            if self._js_window_last_real is None:
                self._js_window_last_real = self.chart_buffer.last_real

    def _reinject_live_bar_to_indicators(self) -> None:
        """P14-03-E (Flacker-Fix): Fügt die offene Live-Bar-Zeit generisch in
        die _known_times ALLER Indikatoren mit remember_live_time()-Hook wieder
        ein. Wird NACH JEDEM calculate()-Aufruf ausgeführt – calculate() setzt
        die _known_times aus den DB-Bars zurück (die offene Live-Bar ist noch
        nicht in DuckDB) und ohne diese Re-Injektion feuert der New-Candle-
        Callback des Indikators bei jedem Live-Tick erneut (500ms-Flacker-
        Zyklus Live-Plot <-> Chart-Rebuild). Generisch über den Base-Hook
        (Open/Closed), kein Plugin-Sonderfall."""
        if self._live_bar_time is None:
            return
        for plugin in self.indicators.values():
            rt = getattr(plugin, "remember_live_time", None)
            if not callable(rt):
                continue
            try:
                rt(self._live_bar_time)
            except Exception:
                continue

    def _serialize_and_render_grid(self, payload: dict) -> None:
        """Serialisiert das aggregierte Indikator-Render-Payload im
        Hintergrund-Thread und rendert es.

        P16.05 (F4-Beschluss): Threading-Muster exakt beibehalten (QThread +
        done-Signal + Generations-Guard) – nur das Payload-Format ist
        generisch (EIN payload_json statt getrennter lines/circles).
        Alter Thread wird vor Neustart sauber beendet.
        Generations-Guard: jede Render-Anforderung bekommt eine steigende ID;
        veraltete Ergebnisse (langsamer Thread) werden verworfen."""
        # Alten Serializer cleanen falls noch aktiv
        if self._grid_serializer is not None:
            try:
                self._grid_serializer.done.disconnect(self._apply_grid_render)
            except (RuntimeError, TypeError):
                pass
            if self._grid_serializer.isRunning():
                self._grid_serializer.quit()
                self._grid_serializer.wait(500)
            self._grid_serializer = None

        self._grid_generation += 1
        grid_gen = self._grid_generation
        self._grid_serializer = GridDataSerializer(payload, grid_gen)
        self._grid_serializer.done.connect(self._apply_grid_render)
        self._grid_serializer.start()

    def _apply_grid_render(self, payload_json: str, grid_gen: int) -> None:
        """Übergibt das serialisierte Render-Payload an JS (GUI-Thread).

        P16.05 (F4-Beschluss): Generations-Guard unverändert; geroutet wird
        über die generische JS-Pipeline `applyChartRenderPayload(payload)`
        (P-D1/F1: price_lines→renderPriceLines, lines→renderLineSeries,
        hit_circles→renderMarkers). Verwirft veraltete Ergebnisse, falls
        inzwischen ein neuerer Render lief."""
        if grid_gen < self._grid_generation:
            print(f"⚠️ [GridRender] Veraltetes Ergebnis verworfen (gen={grid_gen} < {self._grid_generation})")
            return
        if not payload_json:
            return
        try:
            self.web_view.page().runJavaScript(
                f"if(window.applyChartRenderPayload) applyChartRenderPayload({payload_json});")
        except (RuntimeError, AttributeError):
            pass
