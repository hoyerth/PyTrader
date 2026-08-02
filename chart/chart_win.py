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
    from chart.chart_basics import BUTTON_PRIMARY_STYLE, COMBOBOX_STYLE, build_html_template
    from chart.indicators.grid import GridIndicator
    from chart.indicators.grid_liquidity import GridLiquidityIndicator
    from chart.indicator_dialog import IndicatorSettingsDialog
except ImportError:
    from chart_basics import BUTTON_PRIMARY_STYLE, COMBOBOX_STYLE, build_html_template
    from indicators.grid import GridIndicator
    from indicators.grid_liquidity import GridLiquidityIndicator
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
    serialized = Signal(str, int)  # fertiges JSON, updateId

    def __init__(self, update_package: dict, update_id: int, parent=None):
        super().__init__(parent)
        self.update_package = update_package
        self.update_id = update_id

    def run(self):
        try:
            payload = json.dumps(self.update_package, allow_nan=False)
            self.serialized.emit(payload, self.update_id)
        except (ValueError, TypeError) as e:
            print(f"⚠️ [Serializer] JSON-Fehler: {e}")
            self.serialized.emit("", self.update_id)


class GridDataSerializer(QThread):
    """Serialisiert Grid-Linien/Circles im Hintergrund-Thread."""
    done = Signal(str, str, int)  # lines_json, circles_json, gridGen

    def __init__(self, lines: list, circles: list, grid_gen: int, parent=None):
        super().__init__(parent)
        self.lines = lines
        self.circles = circles
        self.grid_gen = grid_gen

    def run(self):
        try:
            lj = json.dumps(self.lines, allow_nan=False)
            cj = json.dumps(self.circles, allow_nan=False)
            self.done.emit(lj, cj, self.grid_gen)
        except (ValueError, TypeError) as e:
            print(f"⚠️ [GridSerializer] JSON-Fehler: {e}")
            self.done.emit("", "", self.grid_gen)


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
        # Alt-Indikator 'grid' (hardcoded, unverändert) + neuer Plugin-Indikator
        # 'grid_liquidity' (Phase 12) – beide laufen parallel.
        self.indicators: Dict[str, BaseIndicator] = {
            "grid": GridIndicator(),
            "grid_liquidity": GridLiquidityIndicator(),
        }
        # Phase 13 Schritt 6: Neuer Close im grid_liquidity-Indikator → NUR ein
        # debounced Refresh (Cache-Neuaufbau), nicht bei jedem Tick.
        liq_ind = self.indicators.get("grid_liquidity")
        if liq_ind is not None and hasattr(liq_ind, "set_new_candle_callback"):
            liq_ind.set_new_candle_callback(self.refresh_chart_data)
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
        # Generations-Guard: monoton steigende Update-IDs für Chart- und Grid-Refresh.
        # Veraltete Serializer-Ergebnisse (langsamer Thread aus einem frueheren
        # Symbol/TF-Stand) werden in _apply_chart_update/_apply_grid_render verworfen.
        self._update_generation: int = 0
        self._grid_generation: int = 0

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

            # Mess-State (Messbox) aus dem Instanz-State laden (JSON-String)
            ms_raw = matched_inst.get("measurement_state")
            if ms_raw is not None and not isinstance(ms_raw, (int, float)):
                self.measurement_state = _parse_json_field(ms_raw) or None

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
                # Mess-State aus dem Symbol:TF-Fallback laden (falls kein Instanz-State)
                if self.measurement_state is None and pair_st.get("measurement_state"):
                    self.measurement_state = pair_st.get("measurement_state")

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

        self._update_window_title()
        self.resize(1000, 700)

        self.symbol_combo = self.ui_widget.findChild(QComboBox, "combo_symbol")
        self.tf_combo = self.ui_widget.findChild(QComboBox, "combo_tf")
        self.btn_reset = self.ui_widget.findChild(QPushButton, "btn_reset_chart")
        self.btn_indicator = self.ui_widget.findChild(QPushButton, "btn_indicator_grid")
        self.btn_indicator_liquidity = self.ui_widget.findChild(QPushButton, "btn_indicator_grid_liquidity")
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
        # Alt-Grid-Button (btn_indicator_grid) → Indikator 'grid'
        if self.btn_indicator:
            self.btn_indicator.setCheckable(True)
            self.btn_indicator.clicked.connect(self.toggle_grid_lines)
            self.btn_indicator.installEventFilter(self)
        # Plugin-Grid-Button (btn_indicator_grid_liquidity) → Indikator 'grid_liquidity'
        if self.btn_indicator_liquidity:
            self.btn_indicator_liquidity.setCheckable(True)
            self.btn_indicator_liquidity.clicked.connect(self.toggle_grid_liquidity_lines)
            self.btn_indicator_liquidity.installEventFilter(self)
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
        self.web_view.setHtml(build_html_template(), QUrl("https://localhost"))
        self.web_view.loadFinished.connect(self._on_page_loaded)

    def _auto_init_signal_set(self) -> None:
        """Nicht mehr verwendet - Testsignal ist deaktiviert."""
        pass

    def eventFilter(self, watched, event):
        # Rechtsklick auf den Alt-Grid-Button → Einstellungen für 'grid'
        if (self.btn_indicator is not None and watched == self.btn_indicator
                and event.type() == QEvent.MouseButtonPress and event.button() == Qt.RightButton):
            self._toggle_settings_dialog("grid")
            return True
        # Rechtsklick auf den Plugin-Grid-Button → Einstellungen für 'grid_liquidity'
        if (self.btn_indicator_liquidity is not None and watched == self.btn_indicator_liquidity
                and event.type() == QEvent.MouseButtonPress and event.button() == Qt.RightButton):
            self._toggle_settings_dialog("grid_liquidity")
            return True
        return super().eventFilter(watched, event)

    def _toggle_settings_dialog(self, ind_id: str) -> None:
        """Wenn der Einstellungs-Dialog offen ist, schliessen; sonst für den
        jeweiligen Indikator (alt 'grid' / Plugin 'grid_liquidity') öffnen."""
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.close()
            self._settings_dialog = None
        else:
            self._open_indicator_settings(ind_id)

    def _get_indicator_plugin(self, ind_id: str) -> Optional[BaseIndicator]:
        """Gibt die Indikator-Instanz zur ID zurück (oder None)."""
        return self.indicators.get(ind_id)

    def update_indicator_button_style(self):
        """Aktualisiert die Färbung beider Indikator-Buttons (Alt 'grid' +
        Plugin 'grid_liquidity') entsprechend ihres An/Aus-Zustands."""
        self._apply_indicator_button_style(self.btn_indicator, "grid")
        self._apply_indicator_button_style(self.btn_indicator_liquidity, "grid_liquidity")

    def _apply_indicator_button_style(self, button: Optional[QPushButton], ind_id: str) -> None:
        """Setzt die Button-Farbe je nach Aktiv-Zustand des Indikators."""
        if button is None:
            return
        is_active = self.indicators_state.get(ind_id, {}).get("active", False)
        color = "#2e7d32" if is_active else "#37474f"
        button.setStyleSheet(
            f"background-color: {color}; color: white; font-weight: bold; border-radius: 4px; padding: 3px 10px;")

    def toggle_grid_lines(self):
        """Schaltet den ALTEN Grid-Indikator ('grid') an/aus."""
        self._toggle_indicator("grid")

    def toggle_grid_liquidity_lines(self):
        """Schaltet den NEUEN Plugin-Indikator ('grid_liquidity') an/aus."""
        self._toggle_indicator("grid_liquidity")

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

        NEUES Format (Plugin, z.B. grid_liquidity): indicators_state speichert
        set_id + display_params (+ optional logic_params als Live-Overlay aus
        dem Indikator-Dialog). Die Berechnungslogik (grid_step,
        proximity_threshold, lookback, ...) kommt LIVE aus dem Service-Set
        (ServiceSetRepository.get_set(set_id)), sofern ein Set gewählt ist;
        die Darstellung (Farben, Sichtbarkeiten) aus display_params.
        logic_params überlagern die Set-Logik, damit Änderungen an den
        Service-Parametern im Dialog SOFORT auf dem Chart erscheinen.

        LEGACY (z.B. Alt-Indikator 'grid' / alter DB-Stand ohne set_id):
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
        Legacy (Alt-Indikator 'grid' / voller params-Dict) wird unverändert
        gespeichert (Abwärtskompatibilität).
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
                # 5.4 Schritt 2: Parameter aus set_id (Logik) + display_params
                # (Darstellung) auflösen – Legacy voller params bleibt erhalten.
                res = plugin.calculate(self.df_data, self._resolve_indicator_params(ind_id, st))
                # Grid-spezifische Render-Logik (Alt 'grid' + Plugin 'grid_liquidity')
                if ind_id in ("grid", "grid_liquidity"):
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
        self._grid_serializer = GridDataSerializer(lines, circles, grid_gen)
        self._grid_serializer.done.connect(self._apply_grid_render)
        self._grid_serializer.start()

    def _apply_grid_render(self, lines_json: str, circles_json: str, grid_gen: int) -> None:
        """Übergibt serialisierte Grid-Daten an JS (wird im GUI-Thread aufgerufen).
        Verwirft veraltete Ergebnisse, falls inzwischen ein neuerer Render lief.
        Nach dem Grid-Render werden die Signal-Marker IMMER neu gesetzt –
        so können aktive Signale (EMA, Grid-Proximity) durch den Grid-Render
        nie verdrängt werden (Marker-Cache-Robustheit)."""
        if grid_gen < self._grid_generation:
            print(f"⚠️ [GridRender] Veraltetes Ergebnis verworfen (gen={grid_gen} < {self._grid_generation})")
            return
        if not lines_json and not circles_json:
            return
        try:
            if lines_json:
                self.web_view.page().runJavaScript(
                    f"if(window.renderGridLines) renderGridLines('{lines_json}');")
            if circles_json:
                self.web_view.page().runJavaScript(
                    f"if(window.renderGridCircles) renderGridCircles('{circles_json}');")
            # Signale nach dem Grid-Render wiederherstellen (falls aktiv).
            # Guard in _update_signal_markers_only verhindert Arbeit während
            # eines laufenden Chart-Refreshes.
            try:
                self._update_signal_markers_only()
            except Exception as e:
                print(f"⚠️ [GridRender] Signal-Marker-Update fehlgeschlagen: {e}")
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
                if st.get("active") and ind_id in ("grid", "grid_liquidity"):
                    if hasattr(plugin, "set_context"):
                        plugin.set_context(self.current_symbol, self.current_tf)
                    # 5.4 Schritt 2: Logik aus set_id + Darstellung aus
                    # display_params auflösen (Legacy volle params bleibt).
                    res = plugin.calculate(self.df_data, self._resolve_indicator_params(ind_id, st))
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
            "measurementState": self.measurement_state,
            "timeMap": self._time_cont_to_real,
            # TF_SECONDS_MAP: Python ist die Single Source of Truth. JS nutzt
            # diesen Payload, statt sich auf seine eingebettete Offline-Map zu
            # verlassen (kein Duplikat-Pflege-Problem mehr).
            "tfSecondsMap": TF_SECONDS_MAP,
        }

        # Generations-Guard: monotone Update-ID für Race-Schutz im JS.
        # WICHTIG: Wird VOR dem Serializer-Start inkrementiert, damit jeder
        # Refresh eine eindeutig hoehere ID als der vorherige erhaelt.
        self._update_generation += 1
        update_id = self._update_generation
        update_package["updateId"] = update_id

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

        self._chart_serializer = ChartDataSerializer(update_package, update_id)
        self._chart_serializer.serialized.connect(self._apply_chart_update)
        self._chart_serializer.start()

    def _apply_chart_update(self, payload: str, update_id: int) -> None:
        """Empfängt fertiges JSON aus dem Serializer-Thread und prüft es auf nulls.
        Generations-Guard: veraltete Payloads (langsamer Thread aus einem
        frueheren Symbol/TF-Stand) werden verworfen, bevor sie JS erreichen."""
        # Veraltetes Update verwerfen – ein neuerer Refresh hat bereits begonnen
        if update_id < self._update_generation:
            print(f"⚠️ [ChartUpdate] Veraltetes Update verworfen (id={update_id} < {self._update_generation})")
            return
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
        # Symbol/TF mitliefern – der JS-Guard in updateLiveCandle() verwirft
        # verspaetete Ticks, die nach einem schnellen Symbol/TF-Wechsel eintreffen.
        c_copy["symbol"] = self.current_symbol
        c_copy["timeframe"] = self.current_tf
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
            # Phase 13 Schritt 6: Neue Candle → NUR ein debounced Refresh, der
            # den Linien-Cache des grid_liquidity-Indikators einmal neu aufbaut
            # (nicht bei jedem Tick).
            self.refresh_chart_data()
        else:
            c_copy["time"] = rounded_t

        # Phase 13 Schritt 6: Live-Ticks an den grid_liquidity-Indikator
        # delegieren – er berechnet die mathematische Differenz Live-Tick vs.
        # gecachte Liq-Lines (KEINE Pipeline pro Tick) und setzt Live-Punkte.
        liq_ind = self.indicators.get("grid_liquidity")
        if (liq_ind is not None and hasattr(liq_ind, "update_live_candle")
                and self.indicators_state.get("grid_liquidity", {}).get("active")):
            try:
                liq_ind.update_live_candle(dict(c_copy, time=rounded_t))
            except Exception as e:
                print(f"⚠️ [GridLiquidity] Live-Update fehlgeschlagen: {e}")

        try:
            self.web_view.page().runJavaScript(f"if(window.updateLiveCandle) updateLiveCandle('{json.dumps(c_copy, allow_nan=False)}');")
        except (ValueError, TypeError) as e:
            print(f"⚠️ [JSON] NaN in Live-Candle: {e}")
        except (RuntimeError, AttributeError):
            pass

    def _update_window_title(self) -> None:
        """Aktualisiert den Fenstertitel mit den aktuellen Symbol/TF-Werten."""
        self.setWindowTitle(f"PyTrader Chart - {self.current_symbol} [{self.current_tf}] ({self.instance_id})")

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
                self.measurement_state = None

            # Chart-Trigger: Luecken fuer live_op=True Signale fuellen
            fill_gaps_for_pair(self.current_symbol, self.current_tf, self.settings.feature_builder_limit)
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
                self.measurement_state = None

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

        HINWEIS: Bewusst KEIN _is_loading_data-Guard mehr. Der Grid-Render
        (_apply_grid_render) ruft diese Funktion direkt nach dem Grid-Render
        auf – waehrend eines laufenden Chart-Refreshes wuerde der Guard das
        Signal-Update blockieren und die EMA-Marker waeren weg (Bug).
        Die JS-seitige Marker-Kombination (Caches + _applyAllMarkers) ist
        race-sicher, weil alle JS-Aufrufe sequenziell im Page-Thread laufen.
        """
        if not self._page_loaded or self.df_data is None or self.df_data.empty:
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
        Ermoeglicht Unterscheidung verschiedener Signal-Typen im Chart.
        priority (int): Stapel-Reihenfolge bei gleicher Kerze in JS
        (niedriger = näher an der Kerze, höher = weiter oben)."""
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
                m["priority"] = 5
            elif source_id == "grid_proximity_v1":
                # Grid-Proximity: Kreise oberhalb
                m["position"] = "aboveBar"
                m["shape"] = "circle"
                m["color"] = "#7B1FA2"  # Lila
                m["priority"] = 10
            elif source_id == "ema_atr_set_v1":
                # EMA/ATR: Quadrate oberhalb
                m["position"] = "aboveBar"
                m["shape"] = "square"
                m["color"] = "#FF9800"  # Orange
                m["priority"] = 4
            # Fuer neue Signalquellen hier einen eigenen Zweig ergaenzen.
            # Ohne priority-Zweig gilt der JS-Default (0 = nahe an der Kerze).
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