"""
chart/chart_win_indicators.py - Indikator-/Grabber-Methoden des Chart-Fensters (Settings, Grabber, Peak-Button, Toggle)

23.03 God-File-Split (15.08.2026): Aus chart/chart_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt die Methoden der PyTraderChartWindow
als Mixin (Klasse ChartIndicatorMixin).
"""

from typing import Any, Dict, Optional

from PySide6.QtWidgets import QPushButton

from chart.indicators.base_indicator import BaseIndicator
from chart.indicator_dialog import IndicatorSettingsDialog
from config.event_bus import event_bus

# 22.01c (Bugfix 3): Order-Vorschau gehoert ins CHART-Fenster (Live-Kontext),
# nicht ins Analytics. Der Dialog ist ein schlankes Modal ohne Order/SQL (MVVM).
try:
    from analytics.ui.order_preview_dialog import OrderPreviewDialog
except ImportError:
    OrderPreviewDialog = None

class ChartIndicatorMixin:

    def _toggle_settings_dialog(self, ind_id: str) -> None:
        """Wenn der Einstellungs-Dialog offen ist, schliessen; sonst für den
        jeweiligen Indikator ('ind_fixed_grid_proximity') öffnen."""
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.close()
            self._settings_dialog = None
        else:
            self._open_indicator_settings(ind_id)

    def _get_indicator_plugin(self, ind_id: str) -> Optional[BaseIndicator]:
        """Gibt die Indikator-Instanz zur ID zurück (oder None)."""
        return self.indicators.get(ind_id)

    def update_indicator_button_style(self):
        """Aktualisiert die Färbung aller Plugin-Indikator-Buttons
        entsprechend ihres An/Aus-Zustands."""
        for button, ind_id in (
            (self.btn_indicator_liquidity, "ind_fixed_grid_proximity"),
            (self.btn_indicator_ma, "ind_moving_averages"),
            # 22.01: Peak-Grabber-Button (eigene Akzentfarbe §9.5 §2C).
            (self.btn_peak_grabber, "ind_peak"),
        ):
            self._apply_indicator_button_style(button, ind_id)

    def _apply_indicator_button_style(self, button: Optional[QPushButton], ind_id: str) -> None:
        """Setzt die Button-Farbe je nach Aktiv-Zustand des Indikators."""
        if button is None:
            return
        # 22.01 (§9.5 §2C): Der Peak-Grabber-Button nutzt eine eigene
        # Akzentfarbe (#e65100) statt des Indikator-Gruen (#2e7d32).
        if ind_id == "ind_peak":
            self._apply_peak_grabber_button_style()
            return
        is_active = self.indicators_state.get(ind_id, {}).get("active", False)
        color = "#2e7d32" if is_active else "#37474f"
        button.setStyleSheet(
            f"background-color: {color}; color: white; font-weight: bold; border-radius: 4px; padding: 3px 10px;")

    # 22.01 (§9.3): Reicht den Grabber-Zustand (active) an alle
    # Indikatoren mit set_button_active weiter (Open/Closed - neue
    # Indikatoren brauchen keinen chart_win-Branch). symbol/timeframe
    # des Payloads dienen optional der Kontext-Pruefung.
    def _on_grabber_toggle(self, payload: Dict[str, Any]) -> None:
        active = bool((payload or {}).get("active", False))
        # 9.5: Eigener ChartButton bleibt synchron (blockSignals gegen
        # Rekursion, da der Button selbst grabber_toggle emittiert).
        if self.btn_peak_grabber is not None and self.btn_peak_grabber.isChecked() != active:
            self.btn_peak_grabber.blockSignals(True)
            self.btn_peak_grabber.setChecked(active)
            self.btn_peak_grabber.blockSignals(False)
            self._apply_peak_grabber_button_style()
        # _get_active_plugins() existiert nicht -> self.indicators.
        for plugin in self.indicators.values():
            setter = getattr(plugin, "set_button_active", None)
            if callable(setter):
                try:
                    setter(active)
                except Exception as e:
                    print(f"WARN [chart_win] set_button_active fehlgeschlagen: {e}")

        # 22.01f (Bugfix): indicators_state['ind_peak']['active'] ist die
        # Single Source of Truth fuer das RENDERING (_collect_render_payload
        # ruft ind_peak.calculate() nur bei active=True auf). Der Grabber-
        # Button war davon entkoppelt (eigener toggled-Pfad), daher wurden
        # SL-Linien/Marker gezeichnet, obwohl der PK-Button AUS war (DB sagte
        # active=true, Button sagte false). Hier wird der State nachgezogen,
        # persistiert und der Chart neu gerendert - Button und Zeichnung sind
        # damit immer konsistent.
        st = self.indicators_state.setdefault("ind_peak", {
            "active": False, "preset": "Default", "params": {}
        })
        if bool(st.get("active")) != active:
            st["active"] = active
            self.save_state()
            if self.df_data is not None and not self.df_data.empty:
                self.render_indicators()

        # 22.01c (Bugfix 3): Live-Trigger (grabber_event, vom Peak-Indikator via
    # ind_peak.update_live_candle emittiert) -> Order-Vorschau im CHART.
    # Lazy Singleton: mehrere Trigger kurz nacheinander aktualisieren denselben
    # Dialog (kein Doppel-Fenster, kein Crash - das erste Fenster bleibt offen).
    # MVVM: keine Order-Platzierung und kein SQL hier (Persistenz uebernimmt der
    # Grabber-Konsument vor dem Emit).
    # 22.01g (Bugfix 5): NUR EIN Orderfenster pro BAR - mehrere Trigger/
    # Updates derselben Bar (Live-Ticks) werden unterdrueckt. Ohne das Gate
    # oeffnete der Dialog bei jedem M5-Tick hintereinander (Orderfenster-
    # Flut, Grafikeinfrieren durch Event-Storm).
    def _on_grabber_event(self, record: object) -> None:
        if OrderPreviewDialog is None:
            return
        try:
            ts = int(record.timestamp.timestamp())
        except (AttributeError, TypeError, ValueError):
            ts = 0
        if ts:
            from db_service import TF_SECONDS_MAP
            t_sec = TF_SECONDS_MAP.get(str(self.current_tf or "").upper(), 60)
            bar_key = ts - (ts % t_sec)
            if getattr(self, "_last_grabber_bar_key", None) == bar_key:
                return  # gleiche Bar -> kein weiteres Fenster
            self._last_grabber_bar_key = bar_key
        if not hasattr(self, "_order_preview") or self._order_preview is None:
            self._order_preview = OrderPreviewDialog(self)
        try:
            self._order_preview.show_record(record)
        except Exception as e:
            print(f"WARN [chart_win] Order-Vorschau fehlgeschlagen: {e}")

    # 22.01 (§9.5 §2B): ChartButton -> EventBus. Gleicher Payload wie
    # AnalyticsWindow-Button (§9.2); chart_win subscribed selbst (§9.3)
    # -> generischer Routing-Pfad. Kein Loop: set_button_active
    # emittiert nicht zurueck.
    def _on_peak_grabber_toggled(self, active: bool) -> None:
        event_bus.grabber_toggle.emit({
            "active": bool(active),
            "symbol": str(self.current_symbol or ""),
            "timeframe": str(self.current_tf or ""),
        })
        self._apply_peak_grabber_button_style()

    # 22.01 (§9.5 §2C): Eigene Styling-Methode + eigene Akzentfarbe
    # (Grabber-Modus != Indikator-An/Aus), Zustand sofort sichtbar.
    def _apply_peak_grabber_button_style(self) -> None:
        if self.btn_peak_grabber is None:
            return
        active = self.btn_peak_grabber.isChecked()
        color = "#e65100" if active else "#37474f"  # tiefes Orange = aktiv
        self.btn_peak_grabber.setStyleSheet(
            f"background-color: {color}; color: white; font-weight: bold; "
            f"border-radius: 4px; padding: 3px 10px;")

    # 22.01f (Bugfix "Linien trotz ausgeschalteter Indikatoren"): Synchronisiert
    # den PK-Button und den Plugin-Button-Zustand (IndPeak._btn_active) aus
    # indicators_state. indicators_state['ind_peak']['active'] ist die Single
    # Source of Truth fuer das RENDERING (_collect_render_payload). Vorher war
    # der Button davon entkoppelt (eigener toggled-Pfad): Die DB sagte
    # active=true, der Button zeigte false -> SL-Linien/Marker wurden
    # gezeichnet, obwohl der Grabber optisch AUS war.
    def _sync_peak_button_from_state(self) -> None:
        st = self.indicators_state.get("ind_peak") or {}
        active = bool(st.get("active", False))
        if self.btn_peak_grabber is not None and self.btn_peak_grabber.isChecked() != active:
            self.btn_peak_grabber.blockSignals(True)
            self.btn_peak_grabber.setChecked(active)
            self.btn_peak_grabber.blockSignals(False)
        plugin = self.indicators.get("ind_peak")
        setter = getattr(plugin, "set_button_active", None)
        if callable(setter):
            try:
                setter(active)
            except Exception:
                pass
        self._apply_peak_grabber_button_style()

    def toggle_fixed_grid_proximity_lines(self):
        """Schaltet den Plugin-Indikator ('Ind_FixedGridProximity') an/aus."""
        self._toggle_indicator("ind_fixed_grid_proximity")

    def toggle_moving_averages(self):
        """Phase 16.05 (D1): Schaltet den Multi-MA-Indikator
        ('ind_moving_averages') an/aus."""
        self._toggle_indicator("ind_moving_averages")

    def _toggle_indicator(self, ind_id: str) -> None:
        """Schaltet einen Indikator an/aus."""
        plugin = self._get_indicator_plugin(ind_id)
        if plugin is None:
            return
        st = self.indicators_state.setdefault(ind_id, {
            "active": False, "preset": "Default", "params": dict(plugin.default_params)
        })
        st["active"] = not st["active"]
        self.update_indicator_button_style()
        self.save_state()
        self.render_indicators()

    def _open_indicator_settings(self, ind_id: str) -> None:
        """Öffnet den Einstellungs-Dialog für einen Indikator."""
        plugin = self._get_indicator_plugin(ind_id)
        if plugin is None:
            return
        st = self.indicators_state.setdefault(ind_id, {
            "active": False, "preset": "Default", "params": dict(plugin.default_params)
        })
        # 5.4 Schritt 2: Dem Dialog die AUFGELÖSTEN Parameter übergeben
        # (Logik aus dem Service-Set + Darstellung), damit Seite 0 die
        # aktuellen Berechnungswerte zeigt. Beim Zurückmelden liefert der
        # Dialog nur set_id + display_params (Decoupling).
        dialog = IndicatorSettingsDialog(
            plugin, self._resolve_indicator_params(ind_id, st), st["preset"],
            self.state_manager,
            lambda p, pr: self._on_indicator_params_updated(ind_id, p, pr), self,
            symbol=self.current_symbol, timeframe=self.current_tf,
            # 5.5 Fix (Bugfix #3): Zuletzt gewaehltes Service-Set + Live-
            # Overlay (logic_params) mitgeben, damit der Dialog beim
            # Restore/Neuaufbau die Set-Combo vorbelegt und die Service-
            # Parameter (Set-Logik + Overlay) korrekt wiederherstellt.
            current_set_id=st.get("set_id") or None,
            logic_params=st.get("logic_params") or None)
        self._settings_dialog = dialog
        dialog.finished.connect(lambda: self._on_settings_closed(dialog))
        dialog.show()

    def _on_settings_closed(self, dialog):
        if self._settings_dialog is dialog:
            self._settings_dialog = None

    def _get_service_set_repo(self) -> Any:
        """Lazy-Repository für Service-Sets (5.4 Schritt 2).

        Einmalig pro Fenster instanziiert; im Test kann ein temporäres
        Repository (Temp-DB) injiziert werden (self._service_set_repo)."""
        if getattr(self, "_service_set_repo", None) is None:
            from analytics.engine.service_set_repository import ServiceSetRepository
            self._service_set_repo = ServiceSetRepository()
        return self._service_set_repo

    def _resolve_indicator_params(self, ind_id: str, st: Dict[str, Any]) -> Dict[str, Any]:
        """5.4 Schritt 2 + 5.5 Fix: Volles Parameter-Dict für plugin.calculate().

        NEUES Format (Plugin, z.B. ind_fixed_grid_proximity): indicators_state speichert
        set_id + display_params (+ optional logic_params als Live-Overlay aus
        dem Indikator-Dialog). Die Berechnungslogik (grid_step,
        proximity_threshold, lookback, ...) kommt LIVE aus dem Service-Set
        (ServiceSetRepository.get_set(set_id)), sofern ein Set gewählt ist;
        die Darstellung (Farben, Sichtbarkeiten) aus display_params.
        logic_params überlagern die Set-Logik, damit Änderungen an den
        Service-Parametern im Dialog SOFORT auf dem Chart erscheinen.

        LEGACY (alter DB-Stand ohne set_id):
        volle params werden unverändert durchgereicht (Abwärtskompatibilität).

        Fix: Ohne set_id werden display_params + logic_params ebenfalls
        gemergt – vorher gingen reine Farb-/Sichtbarkeits-Änderungen ohne
        gewähltes Service-Set verloren (Early-Return gab nur params zurück).
        """
        st = st or {}
        set_id = st.get("set_id")

        merged: Dict[str, Any] = dict(st.get("params") or {})
        if set_id:
            try:
                definition = self._get_service_set_repo().get_set(set_id)
                services = (definition or {}).get("services") or {}
                order = (definition or {}).get("execution_order") or []
                # Service mit passendem plugin_id bevorzugen, sonst erster Service.
                cfg: Optional[Dict[str, Any]] = None
                for iid in order:
                    s = services.get(iid) or {}
                    if s.get("plugin_id") == ind_id:
                        cfg = s
                        break
                if cfg is None and order:
                    cfg = services.get(order[0]) or {}
                if cfg:
                    if cfg.get("lookback") is not None:
                        merged["lookback"] = int(cfg["lookback"])
                    merged.update(dict(cfg.get("params") or {}))
            except Exception as e:
                print(f"⚠️ [ChartWin] Service-Set '{set_id}' nicht ladbar: {e}")
        # 5.5 Fix: Live-Overlay aus dem Dialog (geänderte Service-Parameter)
        merged.update(dict(st.get("logic_params") or {}))
        # Darstellung (Farben, Sichtbarkeit) überlagert die Logik
        merged.update(dict(st.get("display_params") or {}))
        return merged

    def _on_indicator_params_updated(self, ind_id: str, payload: Dict[str, Any], preset: str) -> None:
        """Callback wenn ein Indikator-Parameter geändert wurde.

        5.4 Schritt 2: Der Indikator-Dialog liefert im Plugin-Modus ein
        GETRENNTES Dict {set_id, display_params} – die Berechnungslogik lebt im
        Service-Set, die Darstellung (Farben, Sichtbarkeiten) im Chart-State.
        Legacy (voller params-Dict ohne set_id) wird unverändert gespeichert
        (Abwärtskompatibilität).

        Anwender-Anweisung 06.08.2026: Das Preset 'Default' ist GENAU WIE
        JEDES ANDERE PRESET ÜBERSCHREIBBAR – Änderungen unter 'Default'
        (Parameter-Änderungen im Dialog, Preset-Auswahl) werden regulär in
        indicators_state geschrieben und persistiert. Beim nächsten Öffnen
        zeigt der Dialog die überschriebenen Default-Werte.
        """
        if isinstance(payload, dict) and ("set_id" in payload or "display_params" in payload):
            self.indicators_state[ind_id] = {
                "active": True,
                "preset": preset,
                "set_id": payload.get("set_id") or "",
                # 5.5 Fix: Service-Parameter (grid_step, prox_levels, ...) als
                # Live-Overlay mitgeben, damit Änderungen an der Berechnungslogik
                # im Dialog SOFORT auf dem Chart erscheinen.
                "logic_params": dict(payload.get("logic_params") or {}),
                "display_params": dict(payload.get("display_params") or {}),
            }
        else:
            self.indicators_state[ind_id] = {
                "active": True,
                "preset": preset,
                "params": dict(payload or {}),
            }
        # 22.01f: Der ind_peak-Einstellungs-Dialog setzt active=True - PK-Button
        # und Plugin-Zustand synchron halten, damit Button und Zeichnung
        # konsistent sind (Bugfix "Linien trotz ausgeschalteter Indikatoren").
        if ind_id == "ind_peak":
            self._sync_peak_button_from_state()
        self.save_state()
        self.render_indicators()
