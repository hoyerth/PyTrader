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
from symbol_repository import SymbolRepository, get_symbol_repository
from serviceui.symbols_win import SymbolsWindow


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
    """QWebChannel-Bridge zwischen JS (LWC v5) und Python (GUI-Thread).

    Phase 16.07 (D3/D4/D10): Additiv erweitert um
      * rangeChanged(f, t, totalBars) – totalBars für D10-Offset-Restore
      * olderDataRequested(from_time_epoch, count, request_id, window_right_epoch)
        – JS fordert ältere Daten an (zeitbasiert, Wanduhr-Epoch, D4)
      * jumpToLiveRequested – D9 „Live"-Button (Rücksprung ans Live-Ende)
    """
    rangeChanged = Signal(float, float, float)
    priceRangeChanged = Signal(float, float)
    measurementChanged = Signal(str)
    olderDataRequested = Signal(int, int, int, int)
    jumpToLiveRequested = Signal()

    @Slot(float, float, float)
    def onRangeChanged(self, f, t, total): self.rangeChanged.emit(f, t, total)

    @Slot(float, float)
    def onPriceRangeChanged(self, f, t): self.priceRangeChanged.emit(f, t)

    @Slot(str)
    def onMeasurementChanged(self, m): self.measurementChanged.emit(m)

    @Slot(int, int, int, int)
    def onRequestOlderData(self, from_time_epoch, count, request_id, window_right_epoch):
        self.olderDataRequested.emit(from_time_epoch, count, request_id, window_right_epoch)

    @Slot()
    def onJumpToLive(self): self.jumpToLiveRequested.emit()


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
    """Serialisiert das aggregierte Indikator-Render-Payload im Hintergrund-Thread.

    P16.05 (F4-Beschluss): Threading-Muster exakt beibehalten (QThread +
    done-Signal + Generations-Guard), nur das Payload-Format ist generisch:
    done liefert EIN payload_json (das komplette aggregierte Render-Payload
    {"lines", "price_lines", "hit_circles"}) statt getrennter lines/circles.
    """
    done = Signal(str, int)  # payload_json, gridGen

    def __init__(self, payload: dict, grid_gen: int, parent=None):
        super().__init__(parent)
        self.payload = payload
        self.grid_gen = grid_gen

    def run(self):
        try:
            pj = json.dumps(self.payload, allow_nan=False)
            self.done.emit(pj, self.grid_gen)
        except (ValueError, TypeError) as e:
            print(f"⚠️ [GridSerializer] JSON-Fehler: {e}")
            self.done.emit("", self.grid_gen)


class OlderDataWorker(QThread):
    """Phase 16.07 (D7): Holt den nächsten DB-Chunk (ältere Kerzen) im
    Hintergrund-Thread – der GUI-Thread bleibt reaktionsfähig.

    Führt NUR den reinen Lese-Fetch aus (MarketDataRepository,
    before_epoch-Pfad). Die Puffer-Merge und das Delta-Payload werden im
    GUI-Thread erledigt (Buffer/Indikator-Zustand ist nicht thread-safe).

    Generations-Guard über request_id: Veraltete Worker-Ergebnisse (schneller
    Wechsel / neuerer Request) werden in _on_older_db_fetched verworfen.
    """
    done = Signal(int, list, bool)  # request_id, candles, success

    def __init__(self, repo, symbol, timeframe, before_epoch, count, request_id, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.symbol = symbol
        self.timeframe = timeframe
        self.before_epoch = before_epoch
        self.count = count
        self.request_id = request_id

    def run(self):
        try:
            candles, _precision = self.repo.fetch_historical_candles(
                self.symbol, self.timeframe, limit=self.count,
                before_epoch=self.before_epoch)
            self.done.emit(self.request_id, candles, True)
        except Exception as e:
            print(f"⚠️ [OlderDataWorker] DB-Fetch-Fehler: {e}")
            self.done.emit(self.request_id, [], False)


class PyTraderChartWindow(QMainWindow):
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

    # 22.01c (Bugfix 3): Live-Trigger (grabber_event, vom Peak-Indikator via
    # ind_peak.update_live_candle emittiert) -> Order-Vorschau im CHART.
    # Lazy Singleton: mehrere Trigger kurz nacheinander aktualisieren denselben
    # Dialog (kein Doppel-Fenster, kein Crash - das erste Fenster bleibt offen).
    # MVVM: keine Order-Platzierung und kein SQL hier (Persistenz uebernimmt der
    # Grabber-Konsument vor dem Emit).
    def _on_grabber_event(self, record: object) -> None:
        if OrderPreviewDialog is None:
            return
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
        self.save_state()
        self.render_indicators()

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

        payload = self._collect_render_payload(
            time_from=self._js_window_first_real,
            time_to=self._js_window_last_real)

        # P14-03-E (Flacker-Fix): calculate() resettet die _known_times der
        # Indikatoren – die offene Live-Bar generisch wieder einfügen, damit
        # der New-Candle-Callback nicht erneut feuert (Flacker-Zyklus).
        self._reinject_live_bar_to_indicators()

        # JSON-Encoding im Hintergrund (F4: Threading-Muster exakt beibehalten)
        self._serialize_and_render_grid(payload)

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

    def refresh_chart_data(self) -> None:
        """Debounced: Startet Chart-Refresh mit 400ms Verzögerung.
        Bei schnellen Mehrfach-Aufrufen wird nur der letzte ausgeführt."""
        if not self._page_loaded:
            QTimer.singleShot(200, self.refresh_chart_data)
            return
        self._debounce_timer.start()

    def _do_refresh_chart_data(self) -> None:
        """Führt den tatsächlichen Chart-Refresh aus (nur via Debounce-Timer).

        Phase 16.07 (Two-Tier, D1/D2/D5/D6/D8/D10):
          * Tier 2: `ChartDataBuffer.load_initial()` lädt M + Warmup aus
            DuckDB (D2: M=10000; D6: reiner Lese-Vorlauf für MAs).
          * Tier 1: JS erhält das letzte Tier-1-Fenster (D1: N=1000).
          * Indikator-Berechnung läuft über den vollen Tier-2-Puffer (D5),
            das Render-Payload wird auf das Tier-1-Fenster begrenzt.
          * `hasMoreHistory` (D8) und `rangeFrom/rangeTo` (D10, offsetbasiert
            relativ zum rechten Rand) gehen in den Payload.
        """
        if self._is_loading_data:
            self._debounce_timer.start()
            return

        self._set_loading(True)

        print(f"📊 Lade Chart-Daten (Two-Tier): {self.current_symbol} {self.current_tf}")

        # D6: Warmup-Vorlauf (period*4 + smoothing*3) nur für aktive
        # Gleitdurchschnitts-Indikatoren; Grid/Proximity => 0.
        warmup = self._compute_warmup()

        # Tier 2: RAM-Puffer (M + Warmup) aus DuckDB füllen (D2/D6).
        self.chart_buffer.load_initial(
            self.current_symbol, self.current_tf, warmup=warmup,
            limit=self.chart_buffer.TIER2_CAPACITY)
        # D6: Datenfenster-Grösse (M + Warmup) an den MA-Indikator melden,
        # damit die Berechnung über den vollen Tier-2-Puffer läuft (D5).
        self._apply_data_window_size()
        self.df_data = self.chart_buffer.df

        # Tier-1-Fenster (D1: letzte N Kerzen) mit kontinuierlichen Zeiten.
        continuous_candles = self.chart_buffer.window_candles(
            self.chart_buffer.TIER1_WINDOW)
        precision = self.chart_buffer.precision
        print(f"   → Tier2={len(self.chart_buffer.candles)} (warmup={warmup}), "
              f"Tier1={len(continuous_candles)} Candles, precision={precision}")

        # JS-Fenster-Bounds (reale Wanduhr-Epochs) für Render-Payload-Filter.
        n_win = min(self.chart_buffer.TIER1_WINDOW, len(self.chart_buffer.candles))
        self._js_window_first_real = (
            int(self.chart_buffer.candles[-n_win]["time"]) if n_win > 0 else None)
        self._js_window_last_real = self.chart_buffer.last_real

        # P14-03-E (PFLICHT, Pruefprotokoll P5): Offene Live-Kerze nach dem
        # Map-Rebuild (load_initial hat die Maps IN-PLACE neu aufgebaut)
        # re-injizieren – sonst feuert der New-Candle-Callback bei jedem Tick
        # erneut und die Flacker-Schleife bleibt bestehen.
        t_sec = self.chart_buffer.tf_seconds
        if (self._live_bar_time is not None
                and self._live_bar_time not in self._time_real_to_cont):
            last_cont = max(self._time_cont_to_real.keys()) if self._time_cont_to_real else 0
            cont = last_cont + t_sec
            self._time_cont_to_real[cont] = self._live_bar_time
            self._time_real_to_cont[self._live_bar_time] = cont
            if self._live_candle_cont is not None:
                lc = dict(self._live_candle_cont)
                lc["time"] = cont
                continuous_candles.append(lc)

        # P16.05 (Prework Schritt 1): Generische Payload-Aggregation über
        # ALLE aktiven Indikatoren (P-D1/F1/P-C2). Phase 16.07 (D1): auf das
        # Tier-1-Fenster begrenzt (die Berechnung lief über den vollen Puffer).
        render_payload = self._collect_render_payload(
            time_from=self._js_window_first_real,
            time_to=self._js_window_last_real)

        # P14-03-E (Flacker-Fix, generisch): plugin.calculate() setzt die
        # _known_times der Indikatoren auf die DB-Bars zurück – die offene
        # Live-Bar (noch nicht in DuckDB) geht dabei verloren. Würde sie nicht
        # DANACH wieder eingefügt, feuert der New-Candle-Callback bei jedem
        # Live-Tick (500ms) erneut und der Chart flackert im Wechsel
        # Live-Plot <-> Chart-Rebuild (alte/leere Kerze). Re-Injektion über
        # ALLE Indikatoren mit remember_live_time()-Hook (Open/Closed, kein
        # Plugin-Sonderfall).
        self._reinject_live_bar_to_indicators()

        update_package = {
            "symbol": self.current_symbol,
            "timeframe": self.current_tf,
            "candles": continuous_candles,
            "precision": precision,
            # P16.05 (P-C3/F4): chartRenderPayload (analog gridLines/
            # gridCircles) – applyFullChartUpdate ruft die generische
            # JS-Pipeline applyChartRenderPayload(chartRenderPayload) auf.
            "chartRenderPayload": render_payload,
            "measurementState": self.measurement_state,
            "timeMap": self._time_cont_to_real,
            # TF_SECONDS_MAP: Python ist die Single Source of Truth. JS nutzt
            # diesen Payload, statt sich auf seine eingebettete Offline-Map zu
            # verlassen (kein Duplikat-Pflege-Problem mehr).
            "tfSecondsMap": TF_SECONDS_MAP,
            # D8: Stop-Flag – JS stellt am linken Rand keine weiteren
            # Nachlade-Requests, wenn die DB keine ältere Geschichte mehr hat.
            "hasMoreHistory": self.chart_buffer.has_more_history,
        }

        # Generations-Guard: monotone Update-ID für Race-Schutz im JS.
        # WICHTIG: Wird VOR dem Serializer-Start inkrementiert, damit jeder
        # Refresh eine eindeutig hoehere ID als der vorherige erhaelt.
        self._update_generation += 1
        update_id = self._update_generation
        update_package["updateId"] = update_id

        # D10: Restore offsetbasiert relativ zum rechten Rand (Chunk-
        # Koordinaten, umbruchfest) – in logische Indizes übersetzen.
        range_from, range_to = self._resolve_visible_logical_range(
            len(continuous_candles))
        if range_from is not None and range_to is not None:
            update_package["rangeFrom"] = range_from
            update_package["rangeTo"] = range_to

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

    # ======================================================================
    # Phase 16.07 – Two-Tier Caching (D1–D10)
    # ======================================================================

    def _compute_warmup(self) -> int:
        """D6: Warmup-Vorlauf = period*4 + smoothing*3 – NUR für aktive
        Gleitdurchschnitts-Indikatoren (Multi-MA). Grid-/Proximity-
        Indikatoren brauchen keinen Vorlauf (Warmup = 0).

        Der Vorlauf ist ein REINER LESE-Vorlauf (verworfen; der NaN-Vertrag
        period−1 bleibt unverändert) – er stellt sicher, dass die MA-Werte an
        der linken Tier-1-Kante voll eingeschwungen sind."""
        warmup = 0
        st = self.indicators_state.get("ind_moving_averages", {})
        if not st.get("active"):
            return 0
        try:
            params = self._resolve_indicator_params("ind_moving_averages", st)
        except Exception:
            return 0
        for x in range(1, 9):
            show = params.get(f"show_ma{x}")
            if x == 1:
                if show in (False, 0, "false", "False"):
                    continue
            else:
                if not show or show in (False, 0, "false", "False"):
                    continue
            try:
                period = int(params.get(f"ma{x}_period") or 0)
            except (TypeError, ValueError):
                period = 0
            try:
                smoothing = int(params.get(f"ma{x}_smoothing") or 0)
            except (TypeError, ValueError):
                smoothing = 0
            warmup = max(warmup, period * 4 + smoothing * 3)
        return warmup

    def _apply_data_window_size(self) -> None:
        """D6: Meldet die Tier-2-Datenfenster-Grösse (M + Warmup) an den
        Multi-MA-Indikator, damit die Berechnung über den VOLLEN Puffer läuft
        (D5) statt über den alten chart_candle_limit-Zuschnitt (3000)."""
        ind = self.indicators.get("ind_moving_averages")
        setter = getattr(ind, "set_data_window_size", None)
        if not callable(setter):
            return
        size = len(self.chart_buffer.df) if self.chart_buffer.df is not None else None
        try:
            setter(size)
        except Exception:
            pass

    def _resolve_visible_logical_range(self, total: int):
        """D10: Übersetzt die persistierten visible_from/visible_to in
        logische Indizes des aktuellen Tier-1-Fensters.

        NEUES Format (16.07): Offsets relativ zum rechten Rand (Chunk-
        Koordinaten, umbruchfest) – erkennbar an `visible_from > visible_to`
        (logisches from < to, daher ist der Abstand-von-rechts von from
        grösser als der von to).
        ALTES Format (Bestand): absolute logische Indizes (from < to) – wird
        auf das aktuelle Fenster geklemmt (Abwärtskompatibilität).

        Returns:
            (range_from, range_to) als ints oder (None, None).
        """
        if self.visible_from is None or self.visible_to is None:
            return None, None
        if not total or total <= 0:
            return None, None
        vf, vt = int(self.visible_from), int(self.visible_to)
        if vf > vt:
            # Neues Offset-Format: Abstand vom rechten Rand.
            f = max(0, total - vf)
            t = min(total - 1, total - vt)
            if t < f:
                f, t = total - 1, total - 1
            return f, t
        # Alt-Format: absolute Indizes -> klemmen.
        f = max(0, min(vf, total - 1))
        t = max(f + 1, min(vt, total))
        return f, t

    def _on_jump_to_live(self) -> None:
        """D9: „Live"-Button in JS -> vollständiger Refresh. Der Tier-2-Puffer
        wird aus DuckDB neu geladen, das Fenster springt ans Live-Ende."""
        if self._is_loading_data:
            return
        self.refresh_chart_data()

    def _on_older_data_requested(self, from_time_epoch: int, count: int,
                                 request_id: int, window_right_epoch: int) -> None:
        """D3/D4/D7: JS fordert ältere Daten an (zeitbasiert, Wanduhr-Epoch).

        Debounce (300 ms, D7): Nur der letzte Request innerhalb des
        Debounce-Fensters wird ausgeführt (schnelles Wischen erzeugt viele
        Range-Events). `request_id` = JS-seitiges Serial (Race-Guard)."""
        if self._is_loading_data:
            return
        self._older_request_serial = int(request_id)
        self._pending_older = (
            int(from_time_epoch), int(count), int(request_id),
            int(window_right_epoch or 0))
        self._older_debounce_timer.start()

    def _do_older_data_load(self) -> None:
        """Führt den debounced Nachlade-Request aus (GUI-Thread).

        Priorität 1: RAM-Serve aus dem Tier-2-Puffer (0 ms I/O, D3/D4).
        Priorität 2: Puffer nach links erschöpft -> DB-Chunk im
        OlderDataWorker (D7, Hintergrund-Thread), danach merge + serve.
        """
        if not self._pending_older:
            return
        from_epoch, count, request_id, _wr = self._pending_older
        self._pending_older = None
        if self._is_loading_data:
            return

        # Priorität 1: RAM-Serve (Tier 2 -> Tier 1, keine DB-I/O).
        result = self.chart_buffer.serve_older(from_epoch, count)
        if result is not None:
            new_candles, window_right, has_more = result
            first_cont = int(new_candles[0]["time"])
            self._js_window_first_real = self._time_cont_to_real.get(
                first_cont, first_cont)
            self._send_older_chunk(new_candles, window_right, has_more, request_id)
            return

        # Priorität 2: Puffer erschöpft -> DB-Chunk (D7).
        self._last_older_count = int(count)
        self._last_older_warmup = self._compute_warmup()
        if self._older_worker is not None and self._older_worker.isRunning():
            # Ein alter Fetch läuft noch – abbrechen (neuer Request gewinnt).
            try:
                self._older_worker.done.disconnect(self._on_older_db_fetched)
            except (RuntimeError, TypeError):
                pass
            self._older_worker.quit()
            self._older_worker.wait(300)
        worker = OlderDataWorker(
            self.market_repo, self.current_symbol, self.current_tf,
            from_epoch, self._last_older_count + self._last_older_warmup,
            request_id, self)
        self._older_worker = worker
        worker.done.connect(self._on_older_db_fetched)
        worker.start()

    def _on_older_db_fetched(self, request_id: int, fetched: list, success: bool) -> None:
        """Merge + Serve nach DB-Fetch (GUI-Thread).

        Generations-Guard über request_id (D7): Veraltete Worker-Ergebnisse
        (inzwischen neuerer Request / Symbol/TF-Wechsel) werden verworfen."""
        worker = self._older_worker
        self._older_worker = None
        if not success or request_id != self._older_request_serial:
            return
        if self._is_loading_data:
            return
        new_candles, window_right, has_more = self.chart_buffer.merge_older(
            fetched, serve_count=self._last_older_count,
            warmup=self._last_older_warmup)
        self._apply_data_window_size()
        self.df_data = self.chart_buffer.df
        if new_candles:
            first_cont = int(new_candles[0]["time"])
            self._js_window_first_real = self._time_cont_to_real.get(
                first_cont, first_cont)
        # D10/Right-Edge-Sync: Nach evtl. Capacity-Trim ist die Puffer-Rechts-
        # kante die neue JS-Fenster-Rechtskante (JS kürzt in applyOlderDataChunk).
        if window_right:
            self._js_window_last_real = int(window_right)
        self._send_older_chunk(new_candles, window_right, has_more, request_id)

    def _send_older_chunk(self, new_candles: List[Dict[str, Any]],
                          window_right: int, has_more: bool, request_id: int) -> None:
        """Baut das Delta-Payload (D4) und sendet es an JS.

        Vertrag: {updateId, symbol, timeframe, candles, timeMapDelta,
        windowRightEpoch, hasMoreHistory, chartRenderPayloadDelta}.

        `chartRenderPayloadDelta.lines/hit_circles` = vollständig neu
        berechnetes Render-Payload über den vollen Tier-2-Puffer (D5),
        begrenzt auf das aktuelle Tier-1-Fenster [neue linke Kante, rechte
        Kante] – JS ersetzt die Linien/Marker damit nahtlos (kein Seam)."""
        if not new_candles:
            # DB-Ende / keine neuen Daten -> nur Stop-Flag senden (D8).
            payload = {
                "updateId": int(request_id),
                "symbol": self.current_symbol,
                "timeframe": self.current_tf,
                "candles": [],
                "timeMapDelta": {},
                "windowRightEpoch": int(window_right or 0),
                "hasMoreHistory": False,
                "chartRenderPayloadDelta": {"lines": [], "hit_circles": []},
            }
            self._send_older_json(payload)
            return

        first_cont = int(new_candles[0]["time"])
        window_left_real = self._time_cont_to_real.get(first_cont, first_cont)
        window_right_real = int(window_right or self._js_window_last_real or 0)

        render_payload = self._collect_render_payload(
            time_from=window_left_real, time_to=window_right_real)

        # P14-03-E (Flacker-Fix): Live-Bar-Re-Injektion nach dem calculate()-Loop.
        self._reinject_live_bar_to_indicators()

        # timeMapDelta: NUR die neuen (geprependeten) cont->real Einträge –
        # die bestehenden Kerzen behalten ihre cont-Zeiten (JS erweitert nur).
        time_map_delta: Dict[int, int] = {}
        for c in new_candles:
            cont = int(c["time"])
            real = self._time_cont_to_real.get(cont)
            if real is not None:
                time_map_delta[cont] = real

        payload = {
            "updateId": int(request_id),
            "symbol": self.current_symbol,
            "timeframe": self.current_tf,
            "candles": new_candles,
            "timeMapDelta": time_map_delta,
            "windowRightEpoch": window_right_real,
            "hasMoreHistory": bool(has_more),
            "chartRenderPayloadDelta": {
                "lines": render_payload.get("lines") or [],
                "hit_circles": render_payload.get("hit_circles") or [],
            },
        }
        self._send_older_json(_clean_nan(payload))

    def _send_older_json(self, payload: dict) -> None:
        """Serialisiert und sendet ein Chunk-Payload an JS (mit Fehler-Schutz)."""
        try:
            payload_json = json.dumps(payload, allow_nan=False)
        except (ValueError, TypeError) as e:
            print(f"⚠️ [OlderData] JSON-Fehler: {e}")
            return
        try:
            self.web_view.page().runJavaScript(
                f"if(window.applyOlderDataChunk) applyOlderDataChunk({payload_json});")
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
                    # Phase 15 (U15-B4): Alt-'grid'-Einträge beim Symbol/TF-
                    # Wechsel ebenfalls ignorieren/bereinigen (keine Registry-
                    # Instanz mehr, erhält kein Set).
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
                    # Phase 15 (U15-B4): Alt-'grid'-Einträge beim Symbol/TF-
                    # Wechsel ebenfalls ignorieren/bereinigen (keine Registry-
                    # Instanz mehr, erhält kein Set).
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PyTraderChartWindow()
    window.show()
    sys.exit(app.exec())