# chart/chart_win.py
# ==============================================================================
# chart/chart_win.py - Exakter Restore für Fensterposition, Leerraum & Zoom
# ==============================================================================

import json
import math
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chart.indicators.base_indicator import BaseIndicator

file_path = Path(__file__).resolve()
project_root = file_path.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PySide6.QtCore import QFile, QIODevice, QObject, QThread, QTimer, QUrl, Signal, Slot, Qt, QEvent
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from chart.chart_basics import BUTTON_PRIMARY_STYLE, COMBOBOX_STYLE, HTML_TEMPLATE
    from chart.indicators.grid import GridIndicator
    from chart.indicator_dialog import IndicatorSettingsDialog
except ImportError:
    from chart_basics import BUTTON_PRIMARY_STYLE, COMBOBOX_STYLE, HTML_TEMPLATE
    from indicators.grid import GridIndicator
    from indicator_dialog import IndicatorSettingsDialog

try:
    from state_manager import StateManager
except ImportError:
    from state_manager import StateManager

from db_service import MarketDataRepository, _parse_json_field, TF_SECONDS_MAP

from chart.overlays.signal_overlay import SignalOverlay
from analytics.background_workers.live_analyzer import fill_gaps_for_pair


def find_null_fields(obj, path=""):
    """Sucht rekursiv nach None/null in Dictionaries und Listen."""
    nulls = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            if v is None:
                nulls.append(new_path)
            else:
                nulls.extend(find_null_fields(v, new_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            new_path = f"{path}[{idx}]"
            nulls.extend(find_null_fields(item, new_path))
    return nulls


def _clean_nan(obj):
    """Entfernt rekursiv alle NaN/Inf-Werte aus Dicts/Listen, damit json.dumps(allow_nan=False) nicht fehlschlaegt."""
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items() if not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))}
    elif isinstance(obj, list):
        return [_clean_nan(item) for item in obj if not (isinstance(item, float) and (math.isnan(item) or math.isinf(item)))]
    return obj


class WebEngineConsolePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        print(f"🌐 [JS Console L{lineNumber}]: {message}")


class ChartBridge(QObject):
    rangeChanged = Signal(float, float)
    priceRangeChanged = Signal(float, float)
    measurementChanged = Signal(str)

    @Slot(float, float)
    def onRangeChanged(self, f, t): self.rangeChanged.emit(f, t)

    @Slot(float, float)
    def onPriceRangeChanged(self, f, t): self.priceRangeChanged.emit(f, t)

    @Slot(str)
    def onMeasurementChanged(self, m): self.measurementChanged.emit(m)


class ChartDataSerializer(QThread):
    """Serialisiert Chart-Update-Pakete im Hintergrund-Thread (JSON-Encoding)."""
    serialized = Signal(str)  # fertiges JSON

    def __init__(self, update_package: dict, parent=None):
        super().__init__(parent)
        self.update_package = update_package

    def run(self):
        try:
            payload = json.dumps(self.update_package, allow_nan=False)
            self.serialized.emit(payload)
        except (ValueError, TypeError) as e:
            print(f"⚠️ [Serializer] JSON-Fehler: {e}")
            self.serialized.emit("")


class GridDataSerializer(QThread):
    """Serialisiert Grid-Linien/Circles im Hintergrund-Thread."""
    done = Signal(str, str)

    def __init__(self, lines: list, circles: list, parent=None):
        super().__init__(parent)
        self.lines = lines
        self.circles = circles

    def run(self):
        try:
            lj = json.dumps(self.lines, allow_nan=False)
            cj = json.dumps(self.circles, allow_nan=False)
            self.done.emit(lj, cj)
        except (ValueError, TypeError) as e:
            print(f"⚠️ [GridSerializer] JSON-Fehler: {e}")
            self.done.emit("", "")


class PyTraderChartWindow(QMainWindow):
    closed_signal = Signal(str)

    def __init__(self, instance_id="win_1", symbol="SILVER", timeframe="H1", visible_from=None, visible_to=None,
                 state_manager=None):
        super().__init__()
        self.instance_id = instance_id
        self.current_symbol = symbol
        self.current_tf = timeframe
        self.visible_from = visible_from
        self.visible_to = visible_to
        self.visible_price_from = None
        self.visible_price_to = None
        self.measurement_state = None
        self.indicators_state = {}

        self.state_manager = state_manager or StateManager()
        self.settings = self.state_manager.get_app_settings()
        self.market_repo = MarketDataRepository()
        self._is_loading_data = False
        self.df_data = None

        # Generische Indikator-Registry: indicator_id -> BaseIndicator
        self.indicators: Dict[str, BaseIndicator] = {
            "grid": GridIndicator(),
        }
        self._settings_dialog: Optional[QDialog] = None
        self._page_loaded: bool = False

        self.signal_overlay = SignalOverlay()
        # Signal-Marker standardmaessig AUS, toggle via Button (📈)
        self._signals_enabled: bool = False
        self._grid_serializer: Optional[GridDataSerializer] = None
        self._chart_serializer: Optional[ChartDataSerializer] = None
        # Debounce-Timer für Chart-Refresh (verhindert Race-Conditions bei schnellen Wechseln)
        self._debounce_timer: QTimer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(400)
        self._debounce_timer.timeout.connect(self._safe_refresh_chart_data)
        # Watchdog: setzt _is_loading_data automatisch zurueck, falls ein Refresh haengt
        # (verhindert dauerhafte Blockade von TF-/Symbol-Wechsel)
        self._loading_watchdog: QTimer = QTimer(self)
        self._loading_watchdog.setSingleShot(True)
        self._loading_watchdog.setInterval(15000)
        self._loading_watchdog.timeout.connect(self._on_loading_watchdog)
        # Mapping: kontinuierliche Zeit -> originale epoch (für JS tickMarkFormatter)
        self._time_cont_to_real: Dict[int, int] = {}
        self._time_real_to_cont: Dict[int, int] = {}

                # 1. ZUERST versuchen, spezifischen Instanz-Status aus der DB zu laden
        saved_inst_st = self.state_manager.load_all_instances()
        matched_inst = next((i for i in saved_inst_st if i.get("instance_id") == self.instance_id), None)

        if matched_inst:
            raw_symbol = matched_inst.get("symbol")
            raw_tf = matched_inst.get("timeframe")
            self.current_symbol = str(raw_symbol) if raw_symbol is not None else self.current_symbol
            self.current_tf = str(raw_tf) if raw_tf is not None else self.current_tf
            if self.visible_from is None:
                self.visible_from = matched_inst.get("visible_range_from")
                self.visible_to = matched_inst.get("visible_range_to")
            self.visible_price_from = matched_inst.get("visible_price_from")
            self.visible_price_to = matched_inst.get("visible_price_to")

            ind_st = matched_inst.get("indicators_state")
            if ind_st is not None and not isinstance(ind_st, (int, float)):
                self.indicators_state = _parse_json_field(ind_st) or {}

        # 2. FALLBACK: Wenn keine Instanz da ist (z. B. neues manuelles Fenster), lade zuletzt gespeicherte Symbol:TF Combo
        if not isinstance(self.indicators_state, dict) or not self.indicators_state or self.visible_from is None:
            if not isinstance(self.indicators_state, dict):
                self.indicators_state = {}
            pair_st = self.state_manager.get_symbol_tf_state(self.current_symbol, self.current_tf)
            if pair_st:
                if self.visible_from is None:
                    self.visible_from = pair_st.get("visible_range_from")
                    self.visible_to = pair_st.get("visible_range_to")
                if self.visible_price_from is None:
                    self.visible_price_from = pair_st.get("visible_price_from")
                    self.visible_price_to = pair_st.get("visible_price_to")
                if pair_st.get("indicators_state") and not self.indicators_state:
                    ind_st_pair = pair_st.get("indicators_state")
                    if ind_st_pair is not None and not isinstance(ind_st_pair, (int, float)):
                        self.indicators_state = _parse_json_field(ind_st_pair) or {}

        # Sicherstellen, dass indicators_state ein dict ist
        if not isinstance(self.indicators_state, dict):
            self.indicators_state = {}

        # Standard-Indikator-Setups ergänzen falls unvollständig
        for ind_id, ind_plugin in self.indicators.items():
            if ind_id not in self.indicators_state:
                self.indicators_state[ind_id] = {
                    "active": False,
                    "preset": "Default",
                    "params": dict(ind_plugin.default_params)
                }
            else:
                # Fehlende Default-Parameter nachtragen (z. B. neue Farb-Parameter)
                existing_params = self.indicators_state[ind_id].get("params", {})
                merged = dict(ind_plugin.default_params)
                merged.update(existing_params)
                self.indicators_state[ind_id]["params"] = merged

        # UI Laden aus .ui
        base_dir = Path(__file__).resolve().parent.parent
        ui_file = QFile(str(base_dir / "ui" / "chart_win.ui"))
        if ui_file.open(QIODevice.ReadOnly):
            loader = QUiLoader()
            self.ui_widget = loader.load(ui_file)
            ui_file.close()
            self.setCentralWidget(self.ui_widget)
        else:
            self.ui_widget = QWidget(self)
            self.setCentralWidget(self.ui_widget)

        self.setWindowTitle(f"PyTrader Chart - {self.current_symbol} [{self.current_tf}] ({self.instance_id})")
        self.resize(1000, 700)

        self.symbol_combo = self.ui_widget.findChild(QComboBox, "combo_symbol")
        self.tf_combo = self.ui_widget.findChild(QComboBox, "combo_tf")
        self.btn_reset = self.ui_widget.findChild(QPushButton, "btn_reset_chart")
        self.btn_indicator = self.ui_widget.findChild(QPushButton, "btn_indicator_grid")
        self.btn_signal = self.ui_widget.findChild(QPushButton, "btn_signal_select")
        self.chart_container = self.ui_widget.findChild(QWidget, "web_container")

        if self.symbol_combo:
            self.symbol_combo.setCurrentText(str(self.current_symbol) if self.current_symbol is not None else "SILVER")
            self.symbol_combo.currentTextChanged.connect(self.on_symbol_changed)
        if self.tf_combo:
            self.tf_combo.setCurrentText(str(self.current_tf) if self.current_tf is not None else "H1")
            self.tf_combo.currentTextChanged.connect(self.on_tf_changed)
        if self.btn_reset:
            self.btn_reset.clicked.connect(self.fit_chart)
        if self.btn_indicator:
            self.btn_indicator.setCheckable(True)
            self.btn_indicator.clicked.connect(self.toggle_grid_lines)
            self.btn_indicator.installEventFilter(self)
            self.update_indicator_button_style()

        if self.btn_signal:
            self.btn_signal.setCheckable(True)
            self.btn_signal.clicked.connect(self.on_signal_button_clicked)

        self.web_view = QWebEngineView()
        self.web_view.setPage(WebEngineConsolePage(self.web_view))
        self.web_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        target = self.chart_container if self.chart_container else self.ui_widget
        layout = target.layout()
        if layout is None:
            layout = QVBoxLayout(target)
            layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.web_view, 1)

        self.bridge = ChartBridge()
        self.bridge.rangeChanged.connect(self.handle_range_changed)
        self.bridge.priceRangeChanged.connect(self.handle_price_range_changed)
        self.bridge.measurementChanged.connect(self.handle_measurement_changed)
        self.channel = QWebChannel()
        self.channel.registerObject("pyBridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        self.web_view.setHtml(HTML_TEMPLATE, QUrl("https://localhost"))
        self.web_view.loadFinished.connect(self._on_page_loaded)

    def _auto_init_signal_set(self) -> None:
        """Nicht mehr verwendet - Testsignal ist deaktiviert."""
        pass

    def eventFilter(self, watched, event):
        if self.btn_indicator is not None and watched == self.btn_indicator and event.type() == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
            # Wenn Dialog offen, schliessen; sonst öffnen
            if self._settings_dialog is not None and self._settings_dialog.isVisible():
                self._settings_dialog.close()
                self._settings_dialog = None
            else:
                self._open_indicator_settings("grid")
            return True
        return super().eventFilter(watched, event)

    def _get_indicator_plugin(self, ind_id: str) -> Optional[BaseIndicator]:
        """Gibt die Indikator-Instanz zur ID zurück (oder None)."""
        return self.indicators.get(ind_id)

    def update_indicator_button_style(self):
        if not self.btn_indicator: return
        is_active = self.indicators_state.get("grid", {}).get("active", False)
        color = "#2e7d32" if is_active else "#37474f"
        self.btn_indicator.setStyleSheet(
            f"background-color: {color}; color: white; font-weight: bold; border-radius: 4px; padding: 3px 10px;")

    def toggle_grid_lines(self):
        self._toggle_indicator("grid")

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
        dialog = IndicatorSettingsDialog(plugin, st["params"], st["preset"], self.state_manager,
                                         lambda p, pr: self._on_indicator_params_updated(ind_id, p, pr), self)
        self._settings_dialog = dialog
        dialog.finished.connect(lambda: self._on_settings_closed(dialog))
        dialog.show()

    def _on_settings_closed(self, dialog):
        if self._settings_dialog is dialog:
            self._settings_dialog = None

    def _on_page_loaded(self, ok: bool) -> None:
        if ok:
            self._page_loaded = True
            # Initialer Refresh direkt (ohne Debounce), danach nur noch via Debounce
            self._safe_refresh_chart_data()

    def _safe_refresh_chart_data(self) -> None:
        """Startet den Chart-Refresh mit Fehler-Schutz.
        Stellt sicher, dass _is_loading_data bei einem Fehler zurueckgesetzt wird –
        sonst bleibt der Chart dauerhaft blockiert (keine Charts, TF/Symbol-Wechsel tot)."""
        try:
            self._do_refresh_chart_data()
        except Exception as e:
            print(f"❌ [ChartRefresh] Fehler: {e}")
            self._set_loading(False)

    def _set_loading(self, loading: bool) -> None:
        """Setzt _is_loading_data und startet/stoppt den Watchdog konsistent."""
        self._is_loading_data = loading
        if loading:
            self._loading_watchdog.start()
        else:
            self._loading_watchdog.stop()

    def _on_loading_watchdog(self) -> None:
        """Watchdog-Timeout: Ein Chart-Refresh haengt zu lange (z. B. durch Fehler).
        Setzt das Flag zurueck, damit TF-/Symbol-Wechsel wieder funktionieren."""
        print(f"⚠️ [ChartRefresh] Watchdog: Refresh haengt ({self.current_symbol} {self.current_tf}), setze zurueck")
        self._is_loading_data = False

    def _on_indicator_params_updated(self, ind_id: str, params: Dict[str, Any], preset: str) -> None:
        """Callback wenn ein Indikator-Parameter geändert wurde."""
        self.indicators_state[ind_id] = {"active": True, "preset": preset, "params": params}
        self.save_state()
        self.render_indicators()

    def render_indicators(self):
        """Rendert alle aktiven Indikatoren via JS-Bridge."""
        if self.df_data is None or self.df_data.empty:
            return

        # Zuerst alle Indikator-Layer clearen
        try:
            self.web_view.page().runJavaScript("if(window.clearGridLines) clearGridLines();")
            self.web_view.page().runJavaScript("if(window.clearGridCircles) clearGridCircles();")
        except (RuntimeError, AttributeError):
            pass

        for ind_id, plugin in self.indicators.items():
            st = self.indicators_state.get(ind_id, {})
            if not st.get("active"):
                continue
            try:
                # Kontext setzen (Symbol/TF fuer DB-basierte Indikatoren)
                if hasattr(plugin, "set_context"):
                    plugin.set_context(self.current_symbol, self.current_tf)
                res = plugin.calculate(self.df_data, st.get("params", {}))
                # Grid-spezifische Render-Logik (aktuell der einzige Indikator)
                if ind_id == "grid":
                    lines = res.get("lines", [])
                    circles = res.get("hit_circles", [])
                    # Circle-Zeiten auf kontinuierlich mappen
                    if circles and self._time_real_to_cont:
                        for gc in circles:
                            gc_t = gc.get("time")
                            if gc_t is not None and int(gc_t) in self._time_real_to_cont:
                                gc["time"] = self._time_real_to_cont[int(gc_t)]
                    # JSON-Encoding im Hintergrund
                    self._serialize_and_render_grid(lines, circles)
            except (RuntimeError, AttributeError):
                pass

    def _serialize_and_render_grid(self, lines: list, circles: list) -> None:
        """Serialisiert Grid-Daten im Hintergrund-Thread und rendert sie.
        Alter Thread wird vor Neustart sauber beendet."""
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

        self._grid_serializer = GridDataSerializer(lines, circles)
        self._grid_serializer.done.connect(self._apply_grid_render)
        self._grid_serializer.start()

    def _apply_grid_render(self, lines_json: str, circles_json: str) -> None:
        """Übergibt serialisierte Grid-Daten an JS (wird im GUI-Thread aufgerufen)."""
        if not lines_json and not circles_json:
            return
        try:
            if lines_json:
                self.web_view.page().runJavaScript(
                    f"if(window.renderGridLines) renderGridLines('{lines_json}');")
            if circles_json:
                self.web_view.page().runJavaScript(
                    f"if(window.renderGridCircles) renderGridCircles('{circles_json}');")
        except (RuntimeError, AttributeError):
            pass

    def refresh_chart_data(self) -> None:
        """Debounced: Startet Chart-Refresh mit 400ms Verzögerung.
        Bei schnellen Mehrfach-Aufrufen wird nur der letzte ausgeführt."""
        if not self._page_loaded:
            QTimer.singleShot(200, self.refresh_chart_data)
            return
        self._debounce_timer.start()

    def _do_refresh_chart_data(self) -> None:
        """Führt den tatsächlichen Chart-Refresh aus (nur via Debounce-Timer)."""
        if self._is_loading_data:
            self._debounce_timer.start()
            return

        self._set_loading(True)

        print(f"📊 Lade Chart-Daten: {self.current_symbol} {self.current_tf}")
        candles, precision = self.market_repo.fetch_historical_candles(self.current_symbol, self.current_tf, limit=self.settings.chart_candle_limit)
        print(f"   → {len(candles)} Candles geladen, precision={precision}")

        # NaN-Werte aus den Candles entfernen
        clean_candles = []
        if candles:
            import math
            for c in candles:
                if (c.get("time") is not None and
                    c.get("open") is not None and
                    c.get("high") is not None and
                    c.get("low") is not None and
                    c.get("close") is not None):
                    if (not math.isnan(c["open"]) and
                        not math.isnan(c["high"]) and
                        not math.isnan(c["low"]) and
                        not math.isnan(c["close"])):
                        clean_candles.append(c)

            # ======================================================================
            # Kontinuierliche Candle-Zeiten (keinerlei Lücken/Whitespace im Chart)
            # Jede Candle bekommt: base_time + i * tf_sec
            # Mapping cont -> real für JS tickMarkFormatter.
            # ======================================================================
            t_sec = TF_SECONDS_MAP.get(str(self.current_tf).upper(), 60)
            self._time_cont_to_real = {}
            self._time_real_to_cont = {}
            continuous_candles = []
            if clean_candles:
                base_time = clean_candles[0]["time"]
                for i, c in enumerate(clean_candles):
                    cont_time = base_time + i * t_sec
                    real_time = int(c["time"])
                    self._time_cont_to_real[cont_time] = real_time
                    self._time_real_to_cont[real_time] = cont_time
                    dc = dict(c)
                    dc["time"] = cont_time
                    continuous_candles.append(dc)

            import pandas as pd
            self.df_data = pd.DataFrame(clean_candles)
        else:
            self.df_data = None
            continuous_candles = []

        grid_lines = []
        grid_circles = []

        if self.df_data is not None and not self.df_data.empty:
            for ind_id, plugin in self.indicators.items():
                st = self.indicators_state.get(ind_id, {})
                if st.get("active") and ind_id == "grid":
                    if hasattr(plugin, "set_context"):
                        plugin.set_context(self.current_symbol, self.current_tf)
                    res = plugin.calculate(self.df_data, st.get("params", {}))
                    grid_lines = res.get("lines", [])
                    grid_circles = res.get("hit_circles", [])
                    # Circle-Zeiten auf kontinuierlich mappen
                    if grid_circles and self._time_real_to_cont:
                        for gc in grid_circles:
                            gc_t = gc.get("time")
                            if gc_t is not None and int(gc_t) in self._time_real_to_cont:
                                gc["time"] = self._time_real_to_cont[int(gc_t)]

        update_package = {
            "symbol": self.current_symbol,
            "timeframe": self.current_tf,
            "candles": continuous_candles,
            "precision": precision,
            "gridLines": grid_lines,
            "gridCircles": grid_circles,
            "signalMarkers": self._get_signal_markers_for_update(),
            "timeMap": self._time_cont_to_real,
        }

        # Nur hinzufügen, wenn echte Werte da sind – nie null/0 übergeben (sonst "Value is null" in JS)
        if self.visible_from is not None and self.visible_to is not None:
            update_package["rangeFrom"] = int(self.visible_from)
            update_package["rangeTo"] = int(self.visible_to)

        if self.visible_price_from is not None and self.visible_price_to is not None:
            update_package["priceFrom"] = float(self.visible_price_from)
            update_package["priceTo"] = float(self.visible_price_to)

        # NaN/Inf-Werte aus dem gesamten Payload entfernen (sonst JSON-Fehler im Serializer)
        update_package = _clean_nan(update_package)

        # JSON-Encoding im Hintergrund-Thread, um GUI-Ruckler zu vermeiden
        # Alten Serializer cleanen falls noch aktiv
        if self._chart_serializer is not None:
            try:
                self._chart_serializer.serialized.disconnect(self._apply_chart_update)
            except (RuntimeError, TypeError):
                pass
            if self._chart_serializer.isRunning():
                self._chart_serializer.quit()
                self._chart_serializer.wait(500)
            self._chart_serializer = None

        self._chart_serializer = ChartDataSerializer(update_package)
        self._chart_serializer.serialized.connect(self._apply_chart_update)
        self._chart_serializer.start()

    def _apply_chart_update(self, payload: str) -> None:
        """Empfängt fertiges JSON aus dem Serializer-Thread und prüft es auf nulls."""
        if not payload:
            self._set_loading(False)
            return

        # ======================================================================
        # DEBUG-CHECK: Identifiziert das exakte null-Objekt in Python!
        # ======================================================================
        try:
            import json as _json
            data = _json.loads(payload)
            null_paths = find_null_fields(data)
            if null_paths:
                print(f"🚨 [NULL DETECTED in {self.current_symbol} {self.current_tf}] Gefundene null-Pfade:")
                for p in null_paths[:15]:  # Zeige die ersten 15 Treffer
                    print(f"   -> {p}")
        except Exception as debug_err:
            print(f"⚠️ [NullCheck] Fehler: {debug_err}")
        # ======================================================================

        try:
            if hasattr(self, "web_view") and self.web_view and self.web_view.page():
                self.web_view.page().runJavaScript(
                    f"if(window.applyFullChartUpdate) applyFullChartUpdate({payload});"
                )
        except (RuntimeError, AttributeError):
            pass
        finally:
            QTimer.singleShot(500, self._unlock_tracking)

    def _unlock_tracking(self):
        try:
            self._set_loading(False)
            self.update_indicator_button_style()
        except (RuntimeError, AttributeError):
            pass

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
        rounded_t = raw_t - (raw_t % t_sec)

        # Auf kontinuierliche Zeit mappen (kein Leerraum im Chart)
        if rounded_t in self._time_real_to_cont:
            c_copy["time"] = self._time_real_to_cont[rounded_t]
        elif self._time_cont_to_real:
            # Neue Candle: an letzte kont. Zeit anhängen
            last_cont = max(self._time_cont_to_real.keys())
            c_copy["time"] = last_cont + t_sec
            self._time_cont_to_real[c_copy["time"]] = rounded_t
            self._time_real_to_cont[rounded_t] = c_copy["time"]
        else:
            c_copy["time"] = rounded_t

        try:
            self.web_view.page().runJavaScript(f"if(window.updateLiveCandle) updateLiveCandle('{json.dumps(c_copy, allow_nan=False)}');")
        except (ValueError, TypeError) as e:
            print(f"⚠️ [JSON] NaN in Live-Candle: {e}")
        except (RuntimeError, AttributeError):
            pass

    def on_symbol_changed(self, s):
        if s and s != self.current_symbol:
            self.save_state()
            self.current_symbol = s
            self.df_data = None
            pair_st = self.state_manager.get_symbol_tf_state(self.current_symbol, self.current_tf)
            if pair_st:
                self.visible_from = pair_st.get("visible_range_from")
                self.visible_to = pair_st.get("visible_range_to")
                self.visible_price_from = pair_st.get("visible_price_from")
                self.visible_price_to = pair_st.get("visible_price_to")
                if pair_st.get("indicators_state"):
                    ind_st = pair_st.get("indicators_state")
                    loaded_ind = _parse_json_field(ind_st) or {}
                    # Merge statt ersetzen, damit Grid-Fallback erhalten bleibt
                    self.indicators_state.update(loaded_ind)
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

            # Chart-Trigger: Luecken fuer live_op=True Signale fuellen
            fill_gaps_for_pair(self.current_symbol, self.current_tf, self.settings.feature_builder_limit)
            self.refresh_chart_data()

    def on_tf_changed(self, t):
        if t and t != self.current_tf:
            self.save_state()
            self.current_tf = t
            self.df_data = None
            pair_st = self.state_manager.get_symbol_tf_state(self.current_symbol, self.current_tf)
            if pair_st:
                self.visible_from = pair_st.get("visible_range_from")
                self.visible_to = pair_st.get("visible_range_to")
                self.visible_price_from = pair_st.get("visible_price_from")
                self.visible_price_to = pair_st.get("visible_price_to")
                if pair_st.get("indicators_state"):
                    ind_st = pair_st.get("indicators_state")
                    loaded_ind = _parse_json_field(ind_st) or {}
                    # Merge statt ersetzen, damit Grid-Fallback erhalten bleibt
                    self.indicators_state.update(loaded_ind)
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

            # Chart-Trigger: Luecken fuer live_op=True Signale fuellen
            fill_gaps_for_pair(self.current_symbol, self.current_tf, self.settings.feature_builder_limit)
            self.refresh_chart_data()

    def on_signal_button_clicked(self):
        """Schaltet ALLE Signal-Marker an/aus (Grid Proximity + EMA-Signale).
        Testsignale (alternating_arrow_v1) bleiben deaktiviert.
        Aktualisiert NUR die Signal-Marker, ohne Chart-Neubau."""
        if not self.btn_signal:
            return

        self._signals_enabled = self.btn_signal.isChecked()
        status = "AN" if self._signals_enabled else "AUS"
        print(f"🔔 Signale: {status}")
        self._update_signal_markers_only()

    def _update_signal_markers_only(self) -> None:
        """Aktualisiert NUR die Signal-Marker im Chart, OHNE kompletten Chart-Neubau.
        Blockiert waerend _is_loading_data (Race-Condition-Schutz)."""
        if not self._page_loaded or self.df_data is None or self.df_data.empty or self._is_loading_data:
            return

        markers = self._get_signal_markers_for_update()
        markers_json = json.dumps(markers, allow_nan=False)

        # ======================================================================
        # DEBUG-CHECK für Marker-Updates
        # ======================================================================
        try:
            null_paths = find_null_fields(markers)
            if null_paths:
                print(f"🚨 [NULL MARKER in {self.current_symbol} {self.current_tf}] Gefundene null-Pfade:")
                for p in null_paths[:10]:
                    print(f"   -> markers{p}")
        except Exception:
            pass
        # ======================================================================

        try:
            self.web_view.page().runJavaScript(
                f"if(window.renderSignalMarkers) renderSignalMarkers({markers_json});"
            )
        except (RuntimeError, AttributeError) as e:
            print(f"⚠️ [SignalMarker] JS-Fehler: {e}")

    # ==============================================================================
    # Live-Signal Integration (wird von MainWindow.on_live_signal gerufen)
    # ==============================================================================

    def on_live_signal_received(self, symbol: str, timeframe: str, bar_time: int, confidence: float, source_id: str) -> None:
        """Wird vom MainWindow bei neuem Live-Signal gerufen.
        Aktualisiert NUR die Marker, kein Chart-Neubau.
        Blockiert waerend _is_loading_data (verhindert JS-Race-Condition)."""
        if symbol != self.current_symbol or timeframe != self.current_tf:
            return
        if self._is_loading_data or not self._page_loaded:
            return
        self._update_signal_markers_only()

    @staticmethod
    def _apply_marker_styles(markers: List[Dict[str, Any]], source_id: str) -> List[Dict[str, Any]]:
        """Wendet visuelle Stile auf Marker basierend auf source_id an.
        Ermoeglicht Unterscheidung verschiedener Signal-Typen im Chart."""
        for m in markers:
            if source_id == "alternating_arrow_v1":
                # Alternierende Pfeile: Buy=arrowUp (oben), Sell=arrowDown (unten)
                if m["time"] % 2 == 0:
                    m["position"] = "belowBar"
                    m["shape"] = "arrowUp"
                    m["color"] = "#26a69a"  # Gruen
                else:
                    m["position"] = "aboveBar"
                    m["shape"] = "arrowDown"
                    m["color"] = "#ef5350"  # Rot
            elif source_id == "grid_proximity_v1":
                # Grid-Proximity: Kreise oberhalb
                m["position"] = "aboveBar"
                m["shape"] = "circle"
                m["color"] = "#7B1FA2"  # Lila
            elif source_id == "ema_atr_set_v1":
                # EMA/ATR: Quadrate oberhalb
                m["position"] = "aboveBar"
                m["shape"] = "square"
                m["color"] = "#FF9800"  # Orange
        return markers

    def _get_signal_markers_for_update(self) -> List[Dict[str, Any]]:
        """Sammelt alle Signal-Marker fuer den Chart-Update-Payload.
        - Testsignal (alternating_arrow_v1): DEAKTIVIERT
        - Grid Proximity (grid_proximity_v1): nur wenn Signal-Button aktiv
        - EMA-Signale (ema_atr_set_v1): nur wenn Signal-Button aktiv
        Marker-Zeiten werden auf Candle-Grenzen gerundet (exakter Match mit candleSeries in LWC v5)."""
        if self.df_data is None or self.df_data.empty:
            return []

        t_sec = TF_SECONDS_MAP.get(str(self.current_tf).upper(), 60)

        # 1) Testsignal (alternating_arrow_v1) DEAKTIVIERT – keine automatischen Test-Signale
        markers: List[Dict[str, Any]] = []

        # 2) Grid Proximity + EMA-Signale NUR wenn der Signal-Button aktiv ist
        if self._signals_enabled:
            grid_markers = self._apply_marker_styles(
                self.signal_overlay.fetch_markers(
                    self.current_symbol, self.current_tf, "grid_proximity_v1"
                ),
                "grid_proximity_v1"
            )
            markers.extend(grid_markers)

            ema_markers = self._apply_marker_styles(
                self.signal_overlay.fetch_markers(
                    self.current_symbol, self.current_tf, "ema_atr_set_v1"
                ),
                "ema_atr_set_v1"
            )
            markers.extend(ema_markers)

        # Marker-Zeiten auf Candle-Grenzen runden + auf kontinuierliche Zeit mappen
        if markers:
            clean_markers = []
            for m in markers:
                mt = m.get("time")
                if mt is None:
                    continue
                # Auf Candle-Timeframe-Grenze runden (z.B. H1: 3600er-Schritte)
                rounded = int(mt) - (int(mt) % t_sec)
                # Nur behalten + auf kontinuierliche Zeit mappen
                if rounded in self._time_real_to_cont:
                    m["time"] = self._time_real_to_cont[rounded]
                    clean_markers.append(m)
            markers = clean_markers
            if markers:
                print(f"   → Marker: {len(markers)} (kont. zeit, z.B. {markers[0]['time']})")
            else:
                print(f"   → KEINE Marker nach Filter! real_times samples={list(self._time_real_to_cont.keys())[:3]}")

        return markers

    def fit_chart(self):
        try:
            self.visible_from = self.visible_to = None
            self.visible_price_from = self.visible_price_to = None
            self.save_state()
            self.web_view.page().runJavaScript("if(window.fitChartContent) fitChartContent();")
        except (RuntimeError, AttributeError):
            pass

    def handle_range_changed(self, f, t):
        if not self._is_loading_data:
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PyTraderChartWindow()
    window.show()
    sys.exit(app.exec())