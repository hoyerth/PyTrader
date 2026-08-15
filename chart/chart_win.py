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

from PySide6.QtCore import QFile, QIODevice, QTimer, QUrl, Signal, Slot, Qt, QEvent
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from chart.chart_basics import BUTTON_PRIMARY_STYLE, COMBOBOX_STYLE, build_html_template
    from chart.indicators.ind_fixed_grid_proximity import FixedGridProximityIndicator
    from chart.indicators.ind_moving_averages import MultiMovingAverageIndicator
    from chart.indicators.ind_peak import IndPeak
    from chart.indicator_dialog import IndicatorSettingsDialog
except ImportError:
    from chart_basics import BUTTON_PRIMARY_STYLE, COMBOBOX_STYLE, build_html_template
    from indicators.ind_fixed_grid_proximity import FixedGridProximityIndicator
    from indicators.ind_moving_averages import MultiMovingAverageIndicator
    from indicators.ind_peak import IndPeak
    from indicator_dialog import IndicatorSettingsDialog

# 22.01c (Bugfix 3): Order-Vorschau gehoert ins CHART-Fenster (Live-Kontext),
# nicht ins Analytics. Der Dialog ist ein schlankes Modal ohne Order/SQL (MVVM).
try:
    from analytics.ui.order_preview_dialog import OrderPreviewDialog
except ImportError:
    OrderPreviewDialog = None

# Phase 16.07 (D2): Tier-2-RAM-Puffer als eigene Engine-Klasse (SRP – Rule 2.3).
# Die UI-Klasse haelt nur eine Referenz auf das Backend-Puffer-Objekt.
try:
    from chart.indicators.utils.chart_data_buffer import ChartDataBuffer
except ImportError:
    from indicators.utils.chart_data_buffer import ChartDataBuffer

try:
    from state_manager import StateManager
except ImportError:
    from state_manager import StateManager

from db_service import MarketDataRepository, _parse_json_field, TF_SECONDS_MAP

# Phase 15 15.01: Symbol- & Favoriten-Verwaltung im Chart-Fenster
# (★-Button oeffnet das SymbolsWindow; Favoriten-Dropdown via EventBus).
from config.event_bus import event_bus
from repositories.symbol_repository import SymbolRepository, get_symbol_repository
from serviceui.symbols_win import SymbolsWindow
from chart.chart_win_workers import ChartBridge, ChartDataSerializer, GridDataSerializer, OlderDataWorker, WebEngineConsolePage
from chart.chart_win_indicators import ChartIndicatorMixin
from chart.chart_win_render import ChartRenderMixin
from chart.chart_win_refresh import ChartRefreshMixin
from chart.chart_win_twotier import ChartTwoTierMixin
from chart.chart_win_symboltf import ChartSymbolTfMixin


class PyTraderChartWindow(QMainWindow, ChartIndicatorMixin, ChartRenderMixin, ChartRefreshMixin, ChartTwoTierMixin, ChartSymbolTfMixin):
    closed_signal = Signal(str)

    # Phase 16 (06.08.2026): Rollen- und Namens-Klarheit - Indikator
    # 'grid_liquidity' wurde in 'ind_fixed_grid_proximity' umbenannt
    # (indicators_state-Key). Persistierte Alt-Keys (Legacy-DB-Stand)
    # werden beim Laden idempotent auf den neuen Key gemappt.
    _LEGACY_IND_ID = "grid_liquidity"
    _NEW_IND_ID = "ind_fixed_grid_proximity"

    @staticmethod
    def _normalize_indicators_state(ind_state):
        """Mappt den Legacy-Indikator-Key 'grid_liquidity' (alter DB-Stand)
        auf 'ind_fixed_grid_proximity' (Phase 16). Idempotent."""
        if not isinstance(ind_state, dict):
            return ind_state
        if PyTraderChartWindow._LEGACY_IND_ID in ind_state:
            ind_state.setdefault(PyTraderChartWindow._NEW_IND_ID,
                                ind_state.pop(PyTraderChartWindow._LEGACY_IND_ID))
        return ind_state


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
        # Phase 16.07 (D2): Tier-2-RAM-Puffer als eigene Engine-Klasse (SRP –
        # Rule 2.3). Die UI-Klasse haelt NUR eine Referenz; schwere DataFrames
        # und die Zeit-Maps leben ausschliesslich im Buffer.
        self.chart_buffer: ChartDataBuffer = ChartDataBuffer(market_repo=self.market_repo)
        self._is_loading_data = False
        self.df_data = None

        # Generische Indikator-Registry: indicator_id -> BaseIndicator.
        # Phase 16: Alt-Indikator 'grid_liquidity' entfernt; der Plugin-
        # Indikator 'Ind_FixedGridProximity' (ind_fixed_grid_proximity) bleibt.
        # Phase 16.05 (D1): Multi-MA-Indikator 'ind_moving_averages' additiv.
        self.indicators: Dict[str, BaseIndicator] = {
            "ind_fixed_grid_proximity": FixedGridProximityIndicator(),
            "ind_moving_averages": MultiMovingAverageIndicator(),
            # 22.01: Peak-Grabber (live) - set_button_active-Hook via
            # grabber_toggle (IoC, §9.3).
            "ind_peak": IndPeak(),
        }
        # Phase 13 Schritt 6: Neuer Close im Ind_FixedGridProximity-Indikator → NUR ein
        # debounced Refresh (Cache-Neuaufbau), nicht bei jedem Tick.
        liq_ind = self.indicators.get("ind_fixed_grid_proximity")
        if liq_ind is not None and hasattr(liq_ind, "set_new_candle_callback"):
            liq_ind.set_new_candle_callback(self.refresh_chart_data)
        self._settings_dialog: Optional[QDialog] = None
        self._page_loaded: bool = False

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
        # Mapping: kontinuierliche Zeit -> originale epoch (für JS tickMarkFormatter).
        # Phase 16.07 (D2): Referenzen auf die Buffer-Maps – der Buffer pflegt
        # sie IN-PLACE (clear/update), damit diese Referenzen dauerhaft gültig
        # bleiben (auch update_live_candle ergänzt live Einträge direkt).
        self._time_cont_to_real: Dict[int, int] = self.chart_buffer.time_cont_to_real
        self._time_real_to_cont: Dict[int, int] = self.chart_buffer.time_real_to_cont
        # P14-03-E: Live-Kerzen-State für die Pflicht-Re-Injektion (Flacker-Fix).
        self._live_bar_time: Optional[int] = None   # reale, gerundete Bar-Zeit der offenen Kerze
        self._live_candle_cont: Optional[Dict[str, Any]] = None  # letzter Live-Candle (kont. Zeit + OHLC)
        # Generations-Guard: monoton steigende Update-IDs für Chart- und Grid-Refresh.
        # Veraltete Serializer-Ergebnisse (langsamer Thread aus einem frueheren
        # Symbol/TF-Stand) werden in _apply_chart_update/_apply_grid_render verworfen.
        self._update_generation: int = 0
        self._grid_generation: int = 0

        # Phase 16.07 (D7): Debounce für JS-Nachlade-Requests (300 ms, JS und
        # Python debouncen – geteilte Verantwortung). Der DuckDB-I/O-Fetch
        # laeuft zusätzlich im OlderDataWorker (Hintergrund-Thread).
        self._older_debounce_timer: QTimer = QTimer(self)
        self._older_debounce_timer.setSingleShot(True)
        self._older_debounce_timer.setInterval(300)
        self._older_debounce_timer.timeout.connect(self._do_older_data_load)
        self._older_worker: Optional[OlderDataWorker] = None
        # JS-Request-Tracking (D4/D7): request_id = JS-Seitiges Serial; nur
        # der neueste Request wird ausgeführt/angewendet (Race-Guard).
        self._older_request_serial: int = 0
        self._pending_older: Optional[Tuple[int, int, int, int]] = None
        # JS-Fenster-Bounds (reale Wanduhr-Epochs) für den Render-Payload-
        # Filter (Tier-1-Fenster, D1) bei render_indicators und Chunk-Deltas.
        self._js_window_first_real: Optional[int] = None
        self._js_window_last_real: Optional[int] = None

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
                # Phase 16: Legacy-Key 'grid_liquidity' normalisieren.
                self.indicators_state = self._normalize_indicators_state(
                    self.indicators_state)

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
                    # Phase 16: Legacy-Key 'grid_liquidity' normalisieren.
                    self.indicators_state = self._normalize_indicators_state(
                        self.indicators_state)
                # Mess-State aus dem Symbol:TF-Fallback laden (falls kein Instanz-State)
                if self.measurement_state is None and pair_st.get("measurement_state"):
                    self.measurement_state = pair_st.get("measurement_state")

        # Sicherstellen, dass indicators_state ein dict ist
        if not isinstance(self.indicators_state, dict):
            self.indicators_state = {}

        # Phase 15 (U15-B4): Alt-Indikator 'grid' entfernt – persistierte
        # indicators_state['grid']-Einträge werden ignoriert/bereinigt (keine
        # Registry-Instanz mehr; der Legacy-Pfad in _resolve_indicator_params()
        # bleibt für Abwärtskompatibilität bestehen, erhält aber kein Set).
        self.indicators_state.pop("grid", None)

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
        self.btn_indicator_liquidity = self.ui_widget.findChild(QPushButton, "btn_indicator_grid_liquidity")
        # Phase 16.05 (D1): Multi-MA-Button (btn_indicator_ma, Text "MA").
        self.btn_indicator_ma = self.ui_widget.findChild(QPushButton, "btn_indicator_ma")
        # 22.01 (14.08.2026): Peak-Grabber-Button (btn_peak_grabber, Text "PK").
        self.btn_peak_grabber = self.ui_widget.findChild(QPushButton, "btn_peak_grabber")
        self.chart_container = self.ui_widget.findChild(QWidget, "web_container")

        if self.symbol_combo:
            self.symbol_combo.setCurrentText(str(self.current_symbol) if self.current_symbol is not None else "SILVER")
            self.symbol_combo.currentTextChanged.connect(self.on_symbol_changed)
        # Phase 15 15.01: Favoriten-Symbol-Verwaltung im Chart-Fenster.
        # ★-Button rechts neben der Symbol-ComboBox oeffnet das nicht-modale
        # SymbolsWindow (Favoriten verwalten). Das Symbol-Dropdown wird bei
        # Favoriten-Aenderungen ueber den EventBus neu befuellt (Favoriten
        # zuerst); das aktuell angezeigte Symbol bleibt immer auswaehlbar,
        # damit der Chart beim Favoriten-Wechsel nicht ungewollt umspringt.
        self._symbol_repo: SymbolRepository = get_symbol_repository()
        self.btn_symbol_fav: QPushButton = QPushButton("★", self.ui_widget)
        self.btn_symbol_fav.setObjectName("btn_symbol_fav")
        self.btn_symbol_fav.setToolTip(
            "Favoriten verwalten – oeffnet das Symbol-Fenster. "
            "Das Symbol-Dropdown zeigt Favoriten zuerst.")
        self.btn_symbol_fav.setFixedSize(28, 28)
        row1_layout = self.ui_widget.findChild(QHBoxLayout, "horizontalLayout_row1")
        if row1_layout is not None and self.symbol_combo is not None:
            idx = row1_layout.indexOf(self.symbol_combo)
            row1_layout.insertWidget(idx + 1, self.btn_symbol_fav)
        self.btn_symbol_fav.clicked.connect(self.open_symbols_window)
        # EventBus: Favoriten-Aenderungen -> ComboBox neu befuellen
        event_bus.favorites_changed.connect(self._refresh_symbol_combo)
        self._refresh_symbol_combo()
        if self.tf_combo:
            self.tf_combo.setCurrentText(str(self.current_tf) if self.current_tf is not None else "H1")
            self.tf_combo.currentTextChanged.connect(self.on_tf_changed)
        if self.btn_reset:
            self.btn_reset.clicked.connect(self.fit_chart)
        # Plugin-Grid-Button (btn_indicator_grid_liquidity) → Indikator 'ind_fixed_grid_proximity'
        if self.btn_indicator_liquidity:
            self.btn_indicator_liquidity.setCheckable(True)
            self.btn_indicator_liquidity.clicked.connect(self.toggle_fixed_grid_proximity_lines)
            self.btn_indicator_liquidity.installEventFilter(self)
        # Phase 16.05 (D1): Multi-MA-Button (btn_indicator_ma) → Indikator
        # 'ind_moving_averages' (Muster btn_indicator_grid_liquidity).
        if self.btn_indicator_ma:
            self.btn_indicator_ma.setCheckable(True)
            self.btn_indicator_ma.clicked.connect(self.toggle_moving_averages)
            self.btn_indicator_ma.installEventFilter(self)
        # 22.01 (14.08.2026): Peak-Grabber-Button (btn_peak_grabber, §9.5).
        # Eigener aufrufender Button im ChartWindow - emittiert denselben
        # grabber_toggle-Payload wie der AnalyticsWindow-Button (§9.2).
        if self.btn_peak_grabber is not None:
            self.btn_peak_grabber.setCheckable(True)
            self.btn_peak_grabber.toggled.connect(self._on_peak_grabber_toggled)
            self.btn_peak_grabber.installEventFilter(self)  # Rechtsklick -> Einstellungen
            self._apply_peak_grabber_button_style()
        # 22.01 (§9.3): Subscription auf grabber_toggle - generisches Routing
        # an alle Indikatoren mit set_button_active-Hook (IoC, kein
        # Indikator-Sonderfall, kein `if ind_id == ...`-Branch).
        event_bus.grabber_toggle.connect(self._on_grabber_toggle)
        # 22.01c (Bugfix 3): grabber_event (Live-Trigger des Peak-Indikators)
        # wird im CHART-Fenster konsumiert -> Order-Vorschau. Analytics ist
        # kein Konsument mehr (dort fehlt der Live-Kontext).
        if OrderPreviewDialog is not None:
            event_bus.grabber_event.connect(self._on_grabber_event)
        self.update_indicator_button_style()
        # 22.01f: PK-Button + Plugin-Zustand aus dem geladenen indicators_state
        # synchronisieren - sonst zeigt der Button false, waehrend die DB
        # ind_peak.active=true hat und SL-Linien/Marker gezeichnet werden.
        self._sync_peak_button_from_state()

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
        # Phase 16.07 (D3/D4/D9): JS fordert ältere Daten an bzw. springt ans
        # Live-Ende („Live"-Button).
        self.bridge.olderDataRequested.connect(self._on_older_data_requested)
        self.bridge.jumpToLiveRequested.connect(self._on_jump_to_live)
        self.channel = QWebChannel()
        self.channel.registerObject("pyBridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        self.web_view.setHtml(build_html_template(), QUrl("https://localhost"))
        self.web_view.loadFinished.connect(self._on_page_loaded)

    def eventFilter(self, watched, event):
        # Rechtsklick auf Plugin-Indikator-Buttons → Einstellungen.
        # Phase 16.05 (D1): MA-Button additiv (btn_indicator_ma).
        if (event.type() == QEvent.MouseButtonPress and event.button() == Qt.RightButton):
            for button, ind_id in (
                (self.btn_indicator_liquidity, "ind_fixed_grid_proximity"),
                (self.btn_indicator_ma, "ind_moving_averages"),
                # 22.01: Peak-Grabber-Button -> ind_peak-Einstellungen.
                (self.btn_peak_grabber, "ind_peak"),
            ):
                if button is not None and watched == button:
                    self._toggle_settings_dialog(ind_id)
                    return True
        return super().eventFilter(watched, event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PyTraderChartWindow()
    window.show()
    sys.exit(app.exec())