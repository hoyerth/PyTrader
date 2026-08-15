"""
chart/chart_win_symboltf.py - Symbol-/Timeframe-/Live-Methoden des Chart-Fensters (Live-Candle, Symbol-Dropdown, Slots, State)

23.03 God-File-Split (15.08.2026): Aus chart/chart_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt die Methoden der PyTraderChartWindow
als Mixin (Klasse ChartSymbolTfMixin).
"""

import json
from datetime import datetime

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QApplication

from db_service import TF_SECONDS_MAP, _parse_json_field
from repositories.symbol_repository import SymbolRepository
from serviceui.symbols_win import SymbolsWindow

class ChartSymbolTfMixin:

    def update_live_candle(self, c: Dict[str, Any]) -> None:
        if not c or self._is_loading_data: return
        t_sec = TF_SECONDS_MAP.get(str(self.current_tf).upper(), 60)

        # Sichere Typprüfung für das time-Feld
        time_val = c.get("time", 0)
        if isinstance(time_val, datetime):
            raw_t = int(time_val.timestamp())
        elif isinstance(time_val, (int, float)):
            raw_t = int(time_val)
        else:
            raw_t = 0

        c_copy = dict(c)
        # Symbol/TF mitliefern – der JS-Guard in updateLiveCandle() verwirft
        # verspaetete Ticks, die nach einem schnellen Symbol/TF-Wechsel eintreffen.
        c_copy["symbol"] = self.current_symbol
        c_copy["timeframe"] = self.current_tf
        rounded_t = raw_t - (raw_t % t_sec)

        # Auf kontinuierliche Zeit mappen (kein Leerraum im Chart)
        if rounded_t in self._time_real_to_cont:
            c_copy["time"] = self._time_real_to_cont[rounded_t]
        elif self._time_cont_to_real:
            # Neue Candle: an letzte kont. Zeit anhängen – OHNE refresh_chart_data()
            # (P14-03-E: Kein Chart-Rebuild bei Live-Ticks! Der einmalige Refresh
            # pro neuer Kerze erfolgt über den New-Candle-Callback des Indikators.)
            last_cont = max(self._time_cont_to_real.keys())
            c_copy["time"] = last_cont + t_sec
            self._time_cont_to_real[c_copy["time"]] = rounded_t
            self._time_real_to_cont[rounded_t] = c_copy["time"]
            # P14-03-E: Live-Kerzen-State für die Pflicht-Re-Injektion merken.
            self._live_bar_time = rounded_t
            self._live_candle_cont = dict(c_copy)
        else:
            c_copy["time"] = rounded_t

        # P14-03-E (Flacker-Fix): Live-Kerzen-State bei JEDEM Tick der offenen
        # Bar aktualisieren (nicht nur beim ersten Tick). Die Pflicht-Re-Injektion
        # im Rebuild nutzt sonst den OHLC-Stand des ERSTEN Ticks – der Rebuild
        # zeichnete kurzzeitig eine veraltete/leere Erst-Tick-Kerze ("dünne
        # Linie") statt der aktuellen offenen Kerze.
        if self._live_bar_time is not None and rounded_t == self._live_bar_time:
            self._live_candle_cont = dict(c_copy)

        # P14-03-E (D.1c): Overlays ALLER aktiven Indikatoren generisch über den
        # get_live_overlays()-Hook einsammeln (Open/Closed – kein Sonderfall pro Plugin).
        overlays: List[Dict[str, Any]] = []
        for ind_id, plugin in self.indicators.items():
            st = self.indicators_state.get(ind_id, {})
            if not st.get("active"):
                continue
            getter = getattr(plugin, "get_live_overlays", None)
            if not callable(getter):
                continue
            try:
                ov = getter(dict(c_copy, time=rounded_t)) or []
            except Exception:
                continue
            for item in ov:
                item = dict(item)
                t = item.get("time")
                if t is not None:
                    try:
                        item["time"] = self._time_real_to_cont.get(int(t), int(t))
                    except (TypeError, ValueError):
                        pass
                overlays.append(item)
        c_copy["overlays"] = overlays

        try:
            self.web_view.page().runJavaScript(f"if(window.updateLiveCandle) updateLiveCandle('{json.dumps(c_copy, allow_nan=False)}');")
        except (ValueError, TypeError) as e:
            print(f"⚠️ [JSON] NaN in Live-Candle: {e}")
        except (RuntimeError, AttributeError):
            pass

    def _update_window_title(self) -> None:
        """Aktualisiert den Fenstertitel mit den aktuellen Symbol/TF-Werten."""
        self.setWindowTitle(f"PyTrader Chart - {self.current_symbol} [{self.current_tf}] ({self.instance_id})")

    # --- Phase 15 15.01: Symbol- & Favoriten-Verwaltung ---

    @Slot()
    def open_symbols_window(self) -> None:
        """Oeffnet das nicht-modale SymbolsWindow (Singleton-Verhalten).

        Analog zu open_service_window in main.py: Existiert bereits eine
        sichtbare Instanz, wird sie in den Vordergrund geholt statt neu
        geoeffnet (PersistentWindow.get_existing_instance()).
        """
        existing = SymbolsWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = SymbolsWindow(self)  # parent=self nur fuer state_manager-Zugriff
        win.show()

    def _refresh_symbol_combo(self) -> None:
        """Befuellt die Symbol-ComboBox aus den Favoriten (Favoriten zuerst).

        Wird beim Start und bei jedem `EventBus.favorites_changed`-Event
        aufgerufen (Verbindung im __init__). Das aktuell angezeigte Symbol
        bleibt immer in der Liste (auch wenn es kein Favorit mehr ist), damit
        der Chart beim Favoriten-Wechsel nicht ungewollt auf ein anderes
        Symbol springt. Signale sind waehrend des Umbaus blockiert.
        """
        if not self.symbol_combo:
            return
        favorites = self._symbol_repo.get_favorite_symbols()
        if not favorites:
            favorites = list(SymbolRepository.DEFAULT_SYMBOLS)
        current = self.symbol_combo.currentText() or self.current_symbol
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        for sym in favorites:
            self.symbol_combo.addItem(sym)
        if current and current not in favorites:
            self.symbol_combo.addItem(current)
        idx = self.symbol_combo.findText(current)
        self.symbol_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.symbol_combo.blockSignals(False)

    def on_symbol_changed(self, s):
        if s and s != self.current_symbol:
            self.save_state()
            self.current_symbol = s
            self._update_window_title()
            self.df_data = None
            pair_st = self.state_manager.get_symbol_tf_state(self.current_symbol, self.current_tf)
            if pair_st:
                self.visible_from = pair_st.get("visible_range_from")
                self.visible_to = pair_st.get("visible_range_to")
                self.visible_price_from = pair_st.get("visible_price_from")
                self.visible_price_to = pair_st.get("visible_price_to")
                # Mess-State des neuen Symbol:TF laden (logische Indizes passen
                # nur zum eigenen Candle-Set; sonst None -> Box wird geleert)
                self.measurement_state = pair_st.get("measurement_state")
                if pair_st.get("indicators_state"):
                    ind_st = pair_st.get("indicators_state")
                    loaded_ind = _parse_json_field(ind_st) or {}
                    # Phase 16: Legacy-Key 'grid_liquidity' normalisieren.
                    loaded_ind = self._normalize_indicators_state(loaded_ind)
                    # Merge statt ersetzen, damit Grid-Fallback erhalten bleibt
                    self.indicators_state.update(loaded_ind)
                    # Phase 15 (U15-B4): Alt-'grid'-Eintraege beim Symbol/TF-
                    # Wechsel ebenfalls ignorieren/bereinigen (keine Registry-
                    # Instanz mehr, erhaelt kein Set).
                    self.indicators_state.pop("grid", None)
                    # Fehlende Default-Parameter nachtragen
                    for ind_id, ind_plugin in self.indicators.items():
                        if ind_id in self.indicators_state:
                            existing = self.indicators_state[ind_id].get("params", {})
                            merged = dict(ind_plugin.default_params)
                            merged.update(existing)
                            self.indicators_state[ind_id]["params"] = merged
            else:
                self.visible_from = self.visible_to = None
                self.visible_price_from = self.visible_price_to = None
                self.measurement_state = None

            # Phase 15: Alt-Signal-Trigger (fill_gaps_for_pair) entfernt –
            # keine signal_results-Writes mehr, keine Signal-Marker.
            # 22.01f: PK-Button aus dem (gemergten) indicators_state des neuen
            # Symbol:TF synchronisieren - der Chart rendert ind_peak nur, wenn
            # Button UND State uebereinstimmen (Bugfix "Linien trotz aus").
            self._sync_peak_button_from_state()
            # 22.01g (Bugfix 5): Bar-Gate zuruecksetzen (neuer Symbol-Kontext).
            self._last_grabber_bar_key = None
            self.refresh_chart_data()

    def on_tf_changed(self, t):
        if t and t != self.current_tf:
            self.save_state()
            self.current_tf = t
            self._update_window_title()
            self.df_data = None
            pair_st = self.state_manager.get_symbol_tf_state(self.current_symbol, self.current_tf)
            if pair_st:
                self.visible_from = pair_st.get("visible_range_from")
                self.visible_to = pair_st.get("visible_range_to")
                self.visible_price_from = pair_st.get("visible_price_from")
                self.visible_price_to = pair_st.get("visible_price_to")
                # Mess-State des neuen Symbol:TF laden (logische Indizes passen
                # nur zum eigenen Candle-Set; sonst None -> Box wird geleert)
                self.measurement_state = pair_st.get("measurement_state")
                if pair_st.get("indicators_state"):
                    ind_st = pair_st.get("indicators_state")
                    loaded_ind = _parse_json_field(ind_st) or {}
                    # Phase 16: Legacy-Key 'grid_liquidity' normalisieren.
                    loaded_ind = self._normalize_indicators_state(loaded_ind)
                    # Merge statt ersetzen, damit Grid-Fallback erhalten bleibt
                    self.indicators_state.update(loaded_ind)
                    # Phase 15 (U15-B4): Alt-'grid'-Eintraege beim Symbol/TF-
                    # Wechsel ebenfalls ignorieren/bereinigen (keine Registry-
                    # Instanz mehr, erhaelt kein Set).
                    self.indicators_state.pop("grid", None)
                    # Fehlende Default-Parameter nachtragen
                    for ind_id, ind_plugin in self.indicators.items():
                        if ind_id in self.indicators_state:
                            existing = self.indicators_state[ind_id].get("params", {})
                            merged = dict(ind_plugin.default_params)
                            merged.update(existing)
                            self.indicators_state[ind_id]["params"] = merged
            else:
                self.visible_from = self.visible_to = None
                self.visible_price_from = self.visible_price_to = None
                self.measurement_state = None

            # Phase 15: Alt-Signal-Trigger (fill_gaps_for_pair) entfernt –
            # keine signal_results-Writes mehr, keine Signal-Marker.
            # 22.01f: PK-Button aus dem (gemergten) indicators_state des neuen
            # Symbol:TF synchronisieren - der Chart rendert ind_peak nur, wenn
            # Button UND State uebereinstimmen (Bugfix "Linien trotz aus").
            self._sync_peak_button_from_state()
            # 22.01g (Bugfix 5): Bar-Gate zuruecksetzen (neuer TF-Kontext).
            self._last_grabber_bar_key = None
            self.refresh_chart_data()
    def fit_chart(self):
        try:
            self.visible_from = self.visible_to = None
            self.visible_price_from = self.visible_price_to = None
            self.save_state()
            self.web_view.page().runJavaScript("if(window.fitChartContent) fitChartContent();")
        except (RuntimeError, AttributeError):
            pass

    def handle_range_changed(self, f, t, total=0):
        """Phase 16.07 (D10): Speichert den Viewport OFFSETBASIERT relativ
        zum rechten Rand (Chunk-Koordinaten, umbruchfest).

        Da im Hintergrund ständig neue Ticks / Chunks hinzukommen, verändern
        sich absolute Bar-Indizes. `visible_from`/`visible_to` werden daher
        als Abstand vom rechten Rand des JS-Datenfensters persistiert
        (visible_from > visible_to) – beim Restore wird daraus die logische
        Range des aktuellen Fensters zurückgerechnet
        (_resolve_visible_logical_range).
        """
        if not self._is_loading_data:
            total = int(total or 0)
            if total > 0:
                self.visible_from = total - int(f)
                self.visible_to = total - int(t)
            else:
                self.visible_from, self.visible_to = f, t
            self.save_state()

    def handle_price_range_changed(self, f, t):
        if not self._is_loading_data:
            self.visible_price_from, self.visible_price_to = f, t
            self.save_state()

    def handle_measurement_changed(self, m):
        if not self._is_loading_data:
            self.measurement_state = json.loads(m) if m else None
            self.save_state()

    def save_state(self):
        if not self.state_manager or self._is_loading_data: return
        self.state_manager.save_instance_state(self.instance_id, self.current_symbol, self.current_tf,
                                               self.visible_from, self.visible_to, self.visible_price_from,
                                               self.visible_price_to, self.indicators_state, self.measurement_state)
        self.state_manager.save_symbol_tf_state(self.current_symbol, self.current_tf, self.visible_from,
                                                self.visible_to, self.visible_price_from, self.visible_price_to,
                                                self.indicators_state, self.measurement_state)
        p, s = self.pos(), self.size()
        self.state_manager.save_window_geometry(self.instance_id, p.x(), p.y(), s.width(), s.height(),
                                                self.isMaximized())

    def closeEvent(self, event):
        self.save_state()
        if self.state_manager:
            app = QApplication.instance()
            if not getattr(app, "_is_quitting", False) and self.instance_id != "win_main":
                self.state_manager.delete_instance(self.instance_id)
        self.closed_signal.emit(self.instance_id)
        event.accept()
