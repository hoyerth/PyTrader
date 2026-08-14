# PROJEKT-ÜBERSICHT: PyTrader — Chart-Fenster & Lightweight Charts

> Teil-Export (sachbezogen). Vollständiger Export: export_Full.md
> Dateien in dieser Datei: 24

## 1. ORDNERSTRUKTUR
```
PyTrader/
    chart/
        __init__.py
        chart_basics.py
        chart_win.py
        indicator_dialog.py
        indicators/
            __init__.py
            base_indicator.py
            ind_fixed_grid_proximity.py
            ind_moving_averages.py
            ind_peak.py
            utils/
                __init__.py
                chart_data_buffer.py
                ma_template.py
        js/
            01_core.js
            02_time_utils.js
            03_chart_rendering.js
            04_live_updates.js
            05_measurement.js
            06_two_tier.js
        overlays/
            __init__.py
            style_models.py
        widgets/
            __init__.py
            mtf_filter_bar.py
            named_item_actions.py
            style_picker_widget.py
```

## 2. QUELLCODE

### DATEI: chart/__init__.py
```py
# chart/__init__.py
from .chart_basics import BUTTON_PRIMARY_STYLE, COMBOBOX_STYLE, HTML_TEMPLATE, build_html_template
from .chart_win import PyTraderChartWindow

__all__ = [
    "PyTraderChartWindow",
    "HTML_TEMPLATE",
    "build_html_template",
    "COMBOBOX_STYLE",
    "BUTTON_PRIMARY_STYLE",
]
```

--------------------------------------------------

### DATEI: chart/chart_basics.py
```py
# chart/chart_basics.py
"""
chart/chart_basics.py - TradingView Lightweight Charts v5 HTML-Template
Lädt JS-Module aus chart/js/ und baut das finale HTML dynamisch zusammen.
"""

from pathlib import Path
from typing import Dict, List, TypeAlias

OHLCVRecord: TypeAlias = Dict[str, float | int]
CandleDataList: TypeAlias = List[OHLCVRecord]

COMBOBOX_STYLE = """
	QComboBox { background-color: #2b313e; color: white; border: 1px solid #3d4450; border-radius: 4px; padding: 3px 8px; font-weight: bold; }
	QComboBox::drop-down { border: none; }
	QComboBox QAbstractItemView { background-color: #1e222d; color: white; selection-background-color: #3d4450; }
"""

BUTTON_PRIMARY_STYLE = "background-color: #2b5c8f; color: white; font-weight: bold;"

CSS_STYLE = """
	html, body { margin: 0; padding: 0; width: 100%; height: 100%; background-color: #131722; overflow: hidden; font-family: sans-serif; user-select: none; }
	#chart-container { width: 100%; height: 100%; position: relative; }
	#measurement-region { display: none; position: absolute; background: rgba(41, 98, 255, 0.15); border: 1px dashed #2962FF; pointer-events: none; z-index: 999; }
	#measurement-box { display: none; position: absolute; background: #1e222d; border: 1px solid #2962FF; border-radius: 6px; padding: 8px 12px; color: #d1d4dc; font-size: 12px; pointer-events: none; z-index: 1000; line-height: 1.5; white-space: nowrap; }
	#price-badge { display: none; position: absolute; right: 2px; background: #2962FF; color: white; font-size: 11px; font-weight: bold; padding: 2px 6px; border-radius: 3px; pointer-events: none; z-index: 1000; will-change: transform, top; }
	#countdown-badge { display: none; position: absolute; right: 62px; background: #1e222d; border: 1px solid #2962FF; color: #2962FF; font-size: 11px; font-weight: bold; padding: 2px 6px; border-radius: 3px; pointer-events: none; z-index: 1000; will-change: transform, top; }
	#live-button { display: none; position: absolute; top: 4px; right: 4px; background: #2962FF; color: white; border: none; border-radius: 4px; font-size: 11px; font-weight: bold; padding: 3px 10px; cursor: pointer; z-index: 1001; }
	#live-button:hover { background: #1e4fcc; }
"""

JS_DIR = Path(__file__).resolve().parent / "js"

JS_FILES = [
    "01_core.js",
    "02_time_utils.js",
    "03_chart_rendering.js",
    "04_live_updates.js",
    "05_measurement.js",
    # Phase 16.07 (Two-Tier Caching): Sliding-Window-, Nachlade- und
    # Live-Button-Logik (D1/D3/D4/D7/D8/D9/D10). Muss NACH 04 geladen
    # werden (hängt sich über optionale Hooks in 04 ein).
    "06_two_tier.js",
]


def _load_js_modules() -> str:
    """Lädt alle JS-Dateien aus chart/js/ in der definierten Reihenfolge."""
    parts: list[str] = []
    for filename in JS_FILES:
        filepath = JS_DIR / filename
        try:
            content = filepath.read_text(encoding="utf-8")
            parts.append(f"// --- {filename} ---\n{content}")
        except FileNotFoundError:
            print(f"⚠️ [chart_basics] JS-Datei nicht gefunden: {filepath}")
    return "\n\n".join(parts)


def _build_html_template() -> str:
    """Baut das finale HTML aus CSS, CDN-Links und den JS-Modulen zusammen."""
    js_code = _load_js_modules()
    return f"""<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<style>{CSS_STYLE}</style>
	<script crossorigin="anonymous" src="https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"></script>
	<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
</head>
<body>
	<div id="chart-container">
		<div id="measurement-region"></div>
		<div id="measurement-box"></div>
		<div id="price-badge"></div>
		<div id="countdown-badge"></div>
		<button id="live-button" title="Zurück zum Live-Ende">● Live</button>
	</div>
	<script>
{js_code}
	</script>
</body>
</html>"""


def build_html_template() -> str:
    """Baut das HTML-Template FRISCH aus den aktuellen JS-Dateien auf der Platte.

    WICHTIG (Developer-Erfahrung): JS-Aenderungen in chart/js/ greifen sofort
    bei jedem neuen Chart-Fenster – OHNE vollstaendigen App-Neustart.
    Dafuer wird bei jedem Aufruf neu von der Platte gelesen (kein Modul-Cache).
    """
    return _build_html_template()


# Abwaertskompatibilitaet: Konstante fuer Tests (check_html_template.py).
HTML_TEMPLATE = _build_html_template()

```

--------------------------------------------------

### DATEI: chart/chart_win.py
```py
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
        # 22.01f: Der ind_peak-Einstellungs-Dialog setzt active=True - PK-Button
        # und Plugin-Zustand synchron halten, damit Button und Zeichnung
        # konsistent sind (Bugfix "Linien trotz ausgeschalteter Indikatoren").
        if ind_id == "ind_peak":
            self._sync_peak_button_from_state()
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
            # 22.01f: PK-Button aus dem (gemergten) indicators_state des neuen
            # Symbol:TF synchronisieren - der Chart rendert ind_peak nur, wenn
            # Button UND State uebereinstimmen (Bugfix "Linien trotz aus").
            self._sync_peak_button_from_state()
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
            # 22.01f: PK-Button aus dem (gemergten) indicators_state des neuen
            # Symbol:TF synchronisieren - der Chart rendert ind_peak nur, wenn
            # Button UND State uebereinstimmen (Bugfix "Linien trotz aus").
            self._sync_peak_button_from_state()
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
```

--------------------------------------------------

### DATEI: chart/indicator_dialog.py
```py
"""
chart/indicator_dialog.py - Dynamic Universal Settings Dialog with Inline Layout Support & Strict Type Validation

Phase 13 Schritt 5 (additiv): Plugin-Prop-Fenster mit Expert-Modus & Service-Sets.
- Plugin-basierte Indikatoren (erkennbar an parameter_schema / plugin_id) erhalten
  ein NEUES Layout: reine Indi-Props (Sichtbarkeit, Farben) oberhalb einer
  Trennlinie (QFrame.HLine), darunter die Service-Props mit Set-Auswahl
  (ServiceSetRepository.list_sets()), QStackedWidget (eine Formular-Seite pro
  Service) und einem ausklappbaren Expert-Bereich (QGroupBox checkable) mit
  Plugin-Metadaten (description, author, version).
- min/max/step werden exakt aus dem ParameterSchema auf QDoubleSpinBox/QSpinBox
  übertragen; Reihenfolge + Labels kommen aus parameter_order/param_labels der
  Plugin-/Service-Definition (NICHT mehr aus dem Chart-Adapter).
- Set-Aktionen: Name vergeben / Speichern / Ausführen (ServiceSetEvaluator im
  Hintergrund-Thread) / Löschen (zwingend mit QMessageBox-Gegenfrage).
- Alt-Indikatoren ohne Plugin (z.B. 'grid') behalten das bisherige Layout.

Phase 13 Schritt 5 Punkt 4 (VERBINDLICH): Vollständig dynamische Fenster- &
Box-Größen – KEINE fixen Pixelwerte. Höhe/Breite des Fensters und aller Boxen
ergeben sich ausschließlich aus dem Inhalt: Haupt-Layout mit
setSizeConstraint(QLayout.SetFixedSize), SizePolicies Maximum/Preferred,
QStackedWidget-Höhe folgt der AKTUELLEN Service-Seite (_ServiceStack),
kollabierbarer Expert-Bereich mit adjustSize() (4.2–4.7 Implementierungsanweisung).

"""

from typing import Any, Dict, Callable, List, Optional
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtWidgets import (
	QApplication,
	QCheckBox,
	QComboBox,
	QDialog,
	QDoubleSpinBox,
	QFormLayout,
	QFrame,
	QGridLayout,
	QGroupBox,
	QHBoxLayout,
	QInputDialog,
	QLabel,
	QLineEdit,
	QMessageBox,
	QPushButton,
	QSizePolicy,
	QSpinBox,
	QStackedWidget,
	QWidget,
	QVBoxLayout,
)

from chart.indicators.base_indicator import BaseIndicator
from chart.overlays.style_models import LINE_STYLES, LineStyle, MarkerStyle, MARKER_SHAPES
from chart.widgets.style_picker_widget import StylePickerWidget
from chart.widgets.named_item_actions import NamedItemAdapter, NamedItemActionsMixin
from analytics.engine.description_dialog import ServiceDescriptionDialog
from state_manager import StateManager
from scrollable_content import ContentScrollMixin


class DialogServiceSetRunWorker(QThread):
	"""Phase 13 Schritt 5: Führt ein Service-Set im Hintergrund aus (Prop-Fenster).

	Lädt OHLCV (Symbol/Timeframe) und ruft ServiceSetEvaluator.execute_set()
	in einem separaten Thread auf, damit der Dialog nicht blockiert.
	"""

	run_finished = Signal(str, int)  # set_id, Anzahl erfolgreicher Services
	run_failed = Signal(str, str)    # set_id, Fehlermeldung

	def __init__(self, evaluator, symbol: str, timeframe: str,
	             set_definition: Dict[str, Any], parent=None) -> None:
		super().__init__(parent)
		self.evaluator = evaluator
		self.symbol = symbol
		self.timeframe = timeframe
		self.set_definition = set_definition

	def run(self) -> None:
		try:
			from analytics.features.feature_builder import FeatureBuilder, prepare_plugin_df
			from analytics.features.plugins.base_plugin import PluginContext
			from state_manager import StateManager

			settings = StateManager().get_app_settings()
			fb = FeatureBuilder()
			df = fb.load_ohlcv(self.symbol, self.timeframe, limit=settings.feature_builder_limit)
			if df is None or df.empty:
				self.run_failed.emit(
					self.set_definition.get("set_id", ""),
					f"Keine OHLCV-Daten fuer {self.symbol} {self.timeframe}.",
				)
				return

			df_plugin = prepare_plugin_df(df)
			context = PluginContext(
				symbol=self.symbol,
				timeframe=self.timeframe,
				mode="batch",
				timestamp=int(df_plugin["time"].iloc[-1]) if len(df_plugin) else None,
				settings=settings,
			)
			results = self.evaluator.execute_set(self.set_definition, df_plugin, context=context)
			self.run_finished.emit(self.set_definition.get("set_id", ""), len(results))
		except Exception as e:
			self.run_failed.emit(self.set_definition.get("set_id", ""), str(e))


class _ServiceStack(QStackedWidget):
	"""QStackedWidget mit dynamischer H�he anhand der AKTUELLEN Seite (Punkt 4).

	Der Standard-QStackedWidget liefert als sizeHint das MAXIMUM aller Seiten.
	Damit bliebe die Box 'Service-Parameter' so hoch wie die h�chste Service-
	Seite, auch wenn eine k�rzere Seite sichtbar ist (leerer Raum). Diese
	Variante richtet die H�he exakt nach der aktuell sichtbaren Seite aus -
	die Box endet immer unter dem letzten Parameter der aktiven Seite.
	"""

	def sizeHint(self) -> QSize:
		w = self.currentWidget()
		if w is not None:
			return w.sizeHint()
		return super().sizeHint()

	def minimumSizeHint(self) -> QSize:
		w = self.currentWidget()
		if w is not None:
			return w.minimumSizeHint()
		return super().minimumSizeHint()

	def setCurrentIndex(self, index: int) -> None:
		super().setCurrentIndex(index)
		# Eltern-Layouts informieren, dass sich die Höhe (sizeHint) geändert hat –
		# auch bei nicht angezeigtem Dialog. Sonst bleibt die Höhe der Box
		# 'Service-Parameter' auf der höchsten/alten Seite stehen.
		self.updateGeometry()


def _jsonify_style_objects(obj: Any) -> Any:
	"""P16.03 Schritt 4: Konvertiert LineStyle/MarkerStyle-Objekte rekursiv
	via .to_dict() in JSON-kompatible Dicts (vor save_indicator_preset).

	Der aktuelle Preset-Payload (_build_preset_payload) enthält nur primitive
	Werte (Farb-Strings, shape/size/style/width-Geschwister-Keys) – dieser
	Helfer ist eine DEFENSIVE Absicherung: Sollte jemals ein Style-Vertrag
	(Dataclass) direkt im Payload landen (z. B. durch ein zukünftiges
	Control), schlägt json.dumps in state_manager.save_indicator_preset
	nicht fehl, sondern speichert den JSON-Standard
	(show/color/width/style bzw. show/color/shape/size).
	"""
	if isinstance(obj, (LineStyle, MarkerStyle)):
		return obj.to_dict()
	if isinstance(obj, dict):
		return {k: _jsonify_style_objects(v) for k, v in obj.items()}
	if isinstance(obj, (list, tuple)):
		return [_jsonify_style_objects(v) for v in obj]
	return obj


class _PresetItemAdapter(NamedItemAdapter):
	"""Adapter für die PRESET-Sammlung (Referenz-Mechanik) im Prop-Fenster.

	Phase 13 Schritt 8: Die _item_*-Protokoll-Methoden liegen NICHT auf der
	Dialog-Klasse (zwei Callback-Sätze – Presets + Service-Sets – würden sich
	dort sonst gegenseitig überschreiben), sondern in je einem Adapter. Dieser
	Adapter kapselt die Preset-Verwaltung des Indikator-Prop-Fensters.
	"""

	def __init__(self, dlg: "IndicatorSettingsDialog") -> None:
		self.dlg = dlg

	def _item_scope_label(self) -> str:
		return "Preset"

	def _item_current_name(self) -> str:
		return self.dlg.current_preset_name

	def _item_current_id(self) -> Optional[str]:
		return None  # Presets werden über ihren Namen identifiziert

	def _item_auto_name(self) -> str:
		return ""  # Presets: leerer Name → Abbruch mit Hinweis

	def _item_list_names(self) -> List[str]:
		return self.dlg.state_manager.list_indicator_presets(
			self.dlg.indicator.indicator_id)

	def _item_exists(self, name: str) -> bool:
		return name in self._item_list_names()

	def _item_save_as(self, name: str) -> str:
		"""Speichert das Preset unter 'name' (getrenntes Dict {set_id, display_params})."""
		payload = self.dlg._build_preset_payload()
		# P16.03 Schritt 4: Style-Objekte vor dem JSON-Speichern via .to_dict()
		# in JSON-kompatible Dicts konvertieren (defensive Absicherung gegen
		# TypeError in state_manager.save_indicator_preset -> json.dumps).
		payload = _jsonify_style_objects(payload)
		self.dlg.state_manager.save_indicator_preset(
			self.dlg.indicator.indicator_id, name, payload)
		return name

	def _item_delete_current(self) -> bool:
		try:
			self.dlg.state_manager.delete_indicator_preset(
				self.dlg.indicator.indicator_id, self.dlg.current_preset_name)
			return True
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Preset löschen fehlgeschlagen: {e}")
			return False

	def _item_select(self, name_or_id: Optional[str] = None) -> None:
		"""Setzt die Preset-Auswahl nach Speichern (name) bzw. Löschen (None).

		Nach dem Löschen wird das nächstverfügbare Preset GELADEN (on_preset_
		selected), damit die UI-Parameter auf den nächsten Stand wechseln –
		identisches Verhalten zur bisherigen delete_current_preset()-Logik.
		"""
		if name_or_id is not None:
			self.dlg.current_preset_name = name_or_id
			self.dlg.refresh_preset_list()
			self.dlg.on_params_changed_callback(
				self.dlg._build_preset_payload(), self.dlg.current_preset_name)
			return
		remaining = [p for p in self._item_list_names()
		             if p != self._item_reserved_name()]
		nxt = remaining[0] if remaining else (self._item_reserved_name() or "")
		self.dlg.current_preset_name = nxt
		self.dlg.refresh_preset_list()
		self.dlg.on_preset_selected(nxt)

	def _item_reserved_name(self) -> Optional[str]:
		# Anwender-Anweisung 06.08.2026: 'Default' ist wie jedes andere Preset
		# überschreibbar (und löschbar) – KEIN geschützter Name mehr.
		return None


class _ServiceSetItemAdapter(NamedItemAdapter):
	"""Adapter für die SERVICE-SET-Sammlung im Indikator-Prop-Fenster.

	Phase 13 Schritt 8: identische Mechanik wie die Preset-Verwaltung, aber
	auf Service-Sets gemünzt (ServiceSetRepository statt StateManager). Die
	_item_*-Methoden greifen auf den Dialog (self.dlg) zu.
	"""

	def __init__(self, dlg: "IndicatorSettingsDialog") -> None:
		self.dlg = dlg

	def _item_scope_label(self) -> str:
		return "Service-Set"

	def _item_current_name(self) -> str:
		return self.dlg.edit_set_name.text().strip() if self.dlg.edit_set_name else ""

	def _item_current_id(self) -> Optional[str]:
		return self.dlg._current_set_id

	def _item_auto_name(self) -> str:
		"""Auto-Name aus den instance_ids (Roadmap: leerer Name → Auto-Name)."""
		try:
			from analytics.engine.service_set_repository import ServiceSetRepository
			definition = self.dlg.collect_set_definition()
			definition["display_name"] = ""
			return ServiceSetRepository._default_display_name(definition)
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Auto-Name fehlgeschlagen: {e}")
			return ""

	def _item_list_names(self) -> List[str]:
		return [s.get("display_name") or "" for s in self.dlg._indicator_sets()]

	def _item_exists(self, name: str) -> bool:
		"""True, wenn ein ANDERES Set bereits diesen Namen trägt."""
		current = self._item_current_id()
		return any(
			(s.get("display_name") or "") == name and s.get("set_id") != current
			for s in self.dlg._indicator_sets()
		)

	def _item_save_as(self, name: str) -> Optional[str]:
		"""Speichert das Set unter 'name'; liefert die set_id zurück.

		Analog Preset: Existiert bereits ein ANDERES Set mit diesem Namen und
		hat der Nutzer das Überschreiben bestätigt, wird DESSEN set_id
		übernommen (Name identifiziert das Set, kein Duplikat).
		"""
		definition = self.dlg.collect_set_definition()
		if not definition.get("execution_order") or not definition.get("services"):
			QMessageBox.information(self.dlg, "Speichern",
			                        "Keine Service-Parameter vorhanden.")
			return None
		definition["display_name"] = name
		existing = next(
			(s for s in self.dlg._indicator_sets()
			 if (s.get("display_name") or "") == name
			 and s.get("set_id") != self._item_current_id()),
			None,
		)
		if existing:
			definition["set_id"] = existing["set_id"]
		set_id = self.dlg.set_repo.save_set(definition)
		print(f"💾 [IndicatorDialog] Service-Set gespeichert: {set_id}")
		return set_id

	def _item_delete_current(self) -> bool:
		set_id = self._item_current_id()
		if not set_id:
			return False
		return self.dlg.set_repo.delete_set(set_id)

	def _item_select(self, set_id: Optional[str] = None) -> None:
		"""Setzt die Set-Auswahl nach Speichern (set_id) bzw. Löschen (None)."""
		self.dlg._current_set_id = None  # Neuauswahl erzwingen (sonst bleibt Alt-Selektion)
		self.dlg.refresh_service_set_list()
		if set_id:
			idx = self.dlg.combo_service_set.findData(set_id)
			if idx >= 0:
				self.dlg.combo_service_set.setCurrentIndex(idx)

	def _item_reserved_name(self) -> Optional[str]:
		return None  # Service-Sets haben kein geschütztes 'Default'-Set


class IndicatorSettingsDialog(ContentScrollMixin, NamedItemActionsMixin, QDialog):

	# Gemeinsamer Geometrie-Key fuer ALLE Indikator-Einstellungsdialoge
	# (gilt damit automatisch fuer alle Indikatoren, aktuelle & zukuenftige).
	DIALOG_GEOMETRY_KEY = "indicator_settings"

	def __init__(
		self,
		indicator: BaseIndicator,
		current_params: Dict[str, Any],
		current_preset_name: str,
		state_manager: StateManager,
		on_params_changed_callback: Callable[[Dict[str, Any], str], None],
		parent=None,
		symbol: str = "SILVER",
		timeframe: str = "H1",
		service_set_repo: Optional[Any] = None,
		current_set_id: Optional[str] = None,
		logic_params: Optional[Dict[str, Any]] = None,
	) -> None:
		super().__init__(parent)

		self.indicator = indicator
		self.params = dict(current_params)
		self.current_preset_name = current_preset_name
		self.state_manager = state_manager
		self.on_params_changed_callback = on_params_changed_callback

		# Phase 13 Schritt 5: Service-Set-Verwaltung (lazy)
		self.symbol = symbol
		self.timeframe = timeframe
		# USER-REQ (P14-03): Preisskala-Praezision je Symbol fuer die 6
		# Custom-Level-Eingabefelder (prox_level1..6). Lazy + gecacht.
		self._symbol_precision: Optional[int] = None
		self._set_repo = service_set_repo
		self._set_evaluator = None
		self._set_run_worker: Optional[DialogServiceSetRunWorker] = None
		# 5.5 Fix (Bugfix #3): Beim Restore/Neuaufbau das zuletzt gewaehlte
		# Service-Set vorbelegen, damit die Set-Combo und die Service-Logik
		# beim Oeffnen des Fensters wiederhergestellt werden.
		self._current_set_id: Optional[str] = current_set_id or None
		self._current_set_definition: Optional[Dict[str, Any]] = None
		self._set_param_controls: Dict[str, QWidget] = {}
		# Phase 14 P14-01: Beschreibungs-Eingabefelder der Service-Instanzen
		self._set_desc_controls: Dict[str, QWidget] = {}
		# 5.5 Fix: Live-Overlay der Service-Parameter (logic_params). Wird beim
		# Oeffnen vom Chart-Window getrennt uebergeben (st['logic_params']),
		# beim Preset-Laden ersetzt und nach dem Set-Logik-Merge in
		# _on_service_set_changed wieder angewendet, damit die zuletzt vom
		# Dialog gemeldeten Werte (grid_step, prox_levels, ...) beim Restore
		# und beim Set-Wechsel NICHT von den gespeicherten Set-Werten
		# ueberschrieben werden.
		self._preset_logic_params: Dict[str, Any] = dict(logic_params or {})

		# Bugfix (06.08.2026): Indikatoren OHNE deklarierte Services (z.B.
		# Multi-MA) erzeugen die Service-UI-Attribute NICHT mehr (siehe
		# _init_plugin_ui -> _init_plugin_ui_params_only). Die None-
		# Vorbelegung macht die bestehenden 'if self.<attr>:'-Guards (z.B.
		# in _build_preset_payload, on_preset_selected, refresh_service_set_
		# list) None-sicher - ohne jede Aenderung an der Service-Pfad-Logik.
		self.combo_service_set: Optional[QComboBox] = None
		self.combo_service_sel: Optional[QComboBox] = None
		self.stack_service_forms: Optional[QWidget] = None
		self.edit_set_name: Optional[QLineEdit] = None
		self.edit_set_description: Optional[QLineEdit] = None
		self.group_expert: Optional[QGroupBox] = None

		# Phase 13 Schritt 8: EIN NamedItemAdapter pro Sammlung (Presets +
		# Service-Sets). Die _item_*-Protokoll-Methoden liegen NICHT auf der
		# Dialog-Klasse, sondern in den Adaptern – zwei Callback-Sätze auf
		# derselben Klasse würden sich sonst gegenseitig überschreiben.
		self._preset_adapter = _PresetItemAdapter(self)
		self._set_adapter = _ServiceSetItemAdapter(self)

		# Plugin-Kontext (nur im Plugin-Modus gesetzt)
		self.plugin = None
		self.plugin_schema: Dict[str, Any] = {}
		self.plugin_order: List[str] = []
		self.plugin_labels: Dict[str, str] = {}

		self.setWindowTitle(f"Einstellungen - {self.indicator.display_name}")
		# Phase 16.06 (07.08.2026): Fenster-Flags - der '?'-Button (ContextHelp)
		# entfaellt; das Window-X (Schliessen) wird GARANTIERT gesetzt.
		# Empirisch (PySide6/Windows): Ein QDialog mit Parent liefert
		# windowFlags()=Dialog|TitleHint|SystemMenuHint (OHNE CloseButtonHint)
		# und ein OR mit Qt.WindowCloseButtonHint wird von Qt wieder verworfen
		# (bleibt 12291 -> kein X). Einzig das EXPLIZITE Setzen aller Hints
		# setzt das X zuverlaessig (flags=134230019, Close=True). Diese eine
		# zentrale Stelle gilt generisch fuer ALLE Indikator-Prop-Fenster.
		self.setWindowFlags(
			Qt.Dialog
			| Qt.WindowTitleHint
			| Qt.WindowSystemMenuHint
			| Qt.WindowCloseButtonHint
		)

		self.param_controls: Dict[str, QWidget] = {}
		# Phase 13 Schritt 5 Punkt 4: Fenster & Boxen sind vollständig dynamisch –
		# KEINE fixen Pixelwerte für Höhe/Breite. Die Größe ergibt sich allein aus
		# dem Inhalt (setSizeConstraint(SetFixedSize) am Ende von init_ui).
		# Während des UI-Aufbaus wird self.adjustSize() übersprungen.
		self._ui_ready = False
		self.init_ui()

		# Nicht-modaler Dialog: letzte Position/Groesse wiederherstellen
		self._restore_geometry()

	# -------------------------------------------------------------------------
	# Phase 13 Schritt 5: Plugin-Erkennung & Schema-Zugriff
	# -------------------------------------------------------------------------

	def _get_plugin(self) -> Optional[Any]:
		"""Liefert das PluginFeature-Objekt (Schema/Metadaten) oder None (Legacy).

		Erkennung: (1) der Indikator IST ein PluginFeature (parameter_schema +
		plugin_id), oder (2) der Indikator hat eine plugin_id/_plugin_id, ueber
		die das Plugin aus der PluginRegistry geladen wird.
		"""
		if hasattr(self.indicator, "parameter_schema") and hasattr(self.indicator, "plugin_id"):
			return self.indicator
		pid = getattr(self.indicator, "_plugin_id", None) or getattr(self.indicator, "plugin_id", None)
		if pid:
			try:
				from analytics.features.feature_builder import PluginRegistry
				return PluginRegistry().get(pid)
			except Exception:
				return None
		return None

	# -------------------------------------------------------------------------
	# Service-Set-Repository (lazy – echte DB nur bei Nutzung)
	# -------------------------------------------------------------------------

	@property
	def set_repo(self) -> Any:
		if self._set_repo is None:
			from analytics.engine.service_set_repository import ServiceSetRepository
			self._set_repo = ServiceSetRepository()
		return self._set_repo

	@property
	def set_evaluator(self) -> Any:
		if self._set_evaluator is None:
			from analytics.engine.set_evaluator import ServiceSetEvaluator
			self._set_evaluator = ServiceSetEvaluator()
		return self._set_evaluator

	# -------------------------------------------------------------------------
	# Schema-basierte Control-Erzeugung (Phase 13 Schritt 5)
	# -------------------------------------------------------------------------

	@staticmethod
	def _decimal_places(value: Any) -> int:
		"""Nachkommastellen eines float (fuer QDoubleSpinBox.setDecimals).

		5.5 Fix (Bugfix #2): Floats erhalten MINDESTENS 2 Nachkommastellen.
		Damit lassen auch Felder ohne explizites step (z.B. Custom-Level
		prox_level1-6 mit Default 0.0) Nachkommastellen zu - vorher ergab
		_decimal_places(0.0) == 0 und die SpinBox hatte keine Dezimalstellen.
		"""
		if not isinstance(value, float) or value != value:  # NaN-Schutz
			return 4
		s = f"{value:.10f}".rstrip("0")
		if "." in s:
			return max(2, len(s.split(".")[1]))
		return 2

	def _get_symbol_precision(self) -> int:
		"""USER-REQ: Preisskala-Praezision (fix je Symbol) fuer die 6
		Custom-Level-Eingabefelder. Lazy ermittelt (db_service.get_symbol_
		precision) und fuer die Dialog-Instanz gecacht – kein DB-Zugriff bei
		jedem Control-Neuaufbau."""
		if self._symbol_precision is None:
			try:
				from db_service import get_symbol_precision
				self._symbol_precision = get_symbol_precision(
					self.symbol, self.timeframe)
			except Exception:
				self._symbol_precision = 2
		return self._symbol_precision

	@staticmethod
	def _is_visual_key(key: str) -> bool:
		"""Konvention fuer reine Indi-Props: Sichtbarkeit (show_*) + Farben (color)."""
		if key.startswith("show_"):
			return True
		if "color" in key.lower():
			return True
		return False

	@staticmethod
	def _style_sibling_keys(key: str, style_type: str) -> tuple:
		"""P16.03-Bugfix: Leitet die Geschwister-Keys eines StylePickerWidget-
		Params her (Konvention: 'color' im Key -> 'shape'/'size' bei marker,
		'style'/'width' bei line). Liefert (None, None), wenn keine Konvention
		passt. Die Marker-Form/-Groesse wird NICHT als separates Control
		gerendert (der StylePickerWidget zeigt sie bereits), sondern ueber
		diese Geschwister-Params persistiert (nicht in parameter_order)."""
		if "color" not in key:
			return None, None
		if style_type == "marker":
			return key.replace("color", "shape"), key.replace("color", "size")
		return key.replace("color", "style"), key.replace("color", "width")

	@staticmethod
	def _human(key: str) -> str:
		return key.replace("_", " ").title()

	def create_schema_control(self, key: str, val: Any, spec: Dict[str, Any]) -> QWidget:
		"""Erzeugt ein Eingabe-Widget exakt aus dem ParameterSchema.

		min/max/step werden 1:1 auf QDoubleSpinBox/QSpinBox uebertragen.
		"""
		p_type = spec.get("type")

		if p_type == "float":
			spin = QDoubleSpinBox()
			spin.setRange(float(spec.get("min", -1e9)), float(spec.get("max", 1e9)))
			step = spec.get("step")
			decimals = self._decimal_places(step) if step is not None else self._decimal_places(spec.get("default"))
			# USER-REQ: Custom-Levels (prox_level1..6) nutzen die Preisskala-
			# Praezision (fix je Symbol). MUSS vor setValue geschehen, sonst
			# rundet QDoubleSpinBox den Wert auf die Schema-Default-Digits.
			if key.startswith("prox_level"):
				decimals = self._get_symbol_precision()
			spin.setDecimals(min(6, max(0, decimals)))
			spin.setSingleStep(float(step) if step is not None else 0.01)
			try:
				spin.setValue(float(val))
			except (TypeError, ValueError):
				spin.setValue(float(spec.get("default", 0.0)))
			spin.editingFinished.connect(self.on_param_control_changed)
			return spin

		if p_type == "int":
			spin = QSpinBox()
			spin.setRange(int(spec.get("min", -100000)), int(spec.get("max", 100000)))
			spin.setSingleStep(int(spec.get("step", 1)))
			try:
				spin.setValue(int(val))
			except (TypeError, ValueError):
				spin.setValue(int(spec.get("default", 0)))
			spin.editingFinished.connect(self.on_param_control_changed)
			return spin

		if p_type == "bool":
			chk = QCheckBox()
			chk.setChecked(bool(val))
			chk.toggled.connect(self.on_param_control_changed)
			return chk

		if p_type == "choice":
			combo = QComboBox()
			options = [str(o) for o in (spec.get("options") or [])]
			combo.addItems(options)
			combo.setCurrentText(str(val))
			combo.currentTextChanged.connect(self.on_param_control_changed)
			return combo

		if p_type == "color":
			# 5.5 Feintuning + Phase 16 (06.08.2026): Farbparameter werden als
			# StylePickerWidget gerendert – das komplette Composite (Sichtbarkeit,
			# Farbe, Stärke, Linienart). Der Dialog liest/schreibt NUR den
			# Farbanteil via get_style()/set_color() (Refactoring-Anweisung
			# ColorButton -> StylePickerWidget, Entscheidung: vollwertiges
			# Composite, Dialog nutzt nur den Farbanteil).
			# allow_alpha aus dem Schema (Default True) schaltet den
			# Transparenz-Slider im QColorDialog (ShowAlphaChannel) frei.
			# Der Farb-Button liefert '#RRGGBB' (Alpha=255) bzw. 'rgba(r,g,b,a)'
			# (Teil-Transparenz) – 1:1 kompatibel mit TradingView v5 / CSS.
			allow_alpha = bool(spec.get("allow_alpha", True))
			# P16.03-Bugfix (06.08.2026): style_type aus der Schema-Spec
			# (Default 'line'). Circle-Farbparameter (circle_color_std/_active)
			# deklarieren "style_type": "marker" -> das Prop-Fenster zeigt
			# den MARKER-Modus (Markergröße + Form) statt Linienmodus. Der
			# passende Style-Typ wird übergeben, damit die Initialfarbe beim
			# marker-Modus nicht verloren geht (Typ-Mismatch im Widget würde
			# sonst auf die Default-Farbe zurueckfallen).
			style_type = str(spec.get("style_type", "line"))
			# Phase 16.06 (07.08.2026): Die interne 'sichtbar'-Checkbox des
			# StylePickerWidget kann per Schema-Flag 'show_visibility' (Default
			# True) ausgeblendet werden - fuer Parameter, deren Sichtbarkeit ein
			# separater 'show_*'-Param steuert (Multi-MA: show_maX,
			# FixedGridProximity: show_lines/show_circles). Damit entfaellt die
			# doppelte Sichtbarkeits-Steuerung im Dialog (get_style() liefert
			# dann show=True; die Persistenz bleibt unveraendert: color +
			# Sibling-Keys style/width bzw. shape/size).
			show_visibility = bool(spec.get("show_visibility", True))
			# Bugfix (06.08.2026): Reiner Farbwaehler (color_only im Schema,
			# z.B. Multi-MA ma1_bear_color) - KEIN StylePickerWidget-Composite.
			# Diese Farb-Parameter besitzen keine Geschwister-Keys
			# (style/width bzw. shape/size) und keine eigene
			# Sichtbarkeits-Checkbox (die steuert show_maX).
			if bool(spec.get("color_only", False)):
				if style_type == "marker":
					style_obj = MarkerStyle(color=str(val))
				else:
					style_obj = LineStyle(color=str(val))
				ctrl = StylePickerWidget(
					style=style_obj, enable_alpha=allow_alpha,
					style_type=style_type, color_only=True,
					show_visibility=show_visibility)
				ctrl.style_changed.connect(self.on_param_control_changed)
				return ctrl
			if style_type == "marker":
				# P16.03-Bugfix: Marker-Form/-Groesse aus den Geschwister-Params
				# vorbelegen (Konvention 'color' -> 'shape'/'size'), damit das
				# Widget beim Oeffnen die gespeicherte Form/Groesse zeigt.
				shape_key, size_key = self._style_sibling_keys(key, "marker")
				shape_val = "circle"
				if shape_key and shape_key in self.params:
					shape_val = str(self.params.get(shape_key) or "circle")
					if shape_val not in MARKER_SHAPES:
						shape_val = "circle"
				size_val = 6
				if size_key and size_key in self.params:
					try:
						size_val = int(self.params.get(size_key))
					except (TypeError, ValueError):
						size_val = 6
				style_obj = MarkerStyle(color=str(val), shape=shape_val, size=size_val)
			else:
				# P16.03-Bugfix: Linienart/-staerke aus den Geschwister-Params
				# vorbelegen (Konvention 'color' -> 'style'/'width'), damit das
				# Widget beim Oeffnen die gespeicherte Linienart/-staerke zeigt.
				style_key, width_key = self._style_sibling_keys(key, "line")
				style_val = "solid"
				if style_key and style_key in self.params:
					style_val = str(self.params.get(style_key) or "solid")
					if style_val not in LINE_STYLES:
						style_val = "solid"
				width_val = 1
				if width_key and width_key in self.params:
					try:
						width_val = int(self.params.get(width_key))
					except (TypeError, ValueError):
						width_val = 1
				style_obj = LineStyle(color=str(val), style=style_val, width=width_val)
			ctrl = StylePickerWidget(style=style_obj, enable_alpha=allow_alpha, style_type=style_type, show_visibility=show_visibility)
			ctrl.style_changed.connect(self.on_param_control_changed)
			return ctrl

		# str / sonstiges
		txt = QLineEdit()
		txt.setText(str(val))
		txt.editingFinished.connect(self.on_param_control_changed)
		return txt

	def _ctrl_value(self, ctrl: QWidget) -> Any:
		"""Liest den aktuellen Wert eines Controls typsicher aus."""
		if isinstance(ctrl, QCheckBox):
			return ctrl.isChecked()
		if isinstance(ctrl, QSpinBox):
			return ctrl.value()
		if isinstance(ctrl, QDoubleSpinBox):
			return ctrl.value()
		if isinstance(ctrl, QComboBox):
			return ctrl.currentText()
		if isinstance(ctrl, StylePickerWidget):
			return ctrl.get_style().color
		return ctrl.text()

	# -------------------------------------------------------------------------
	# UI-Aufbau
	# -------------------------------------------------------------------------

	def init_ui(self) -> None:
		# 5.4 User-Anforderung (Scrollbar für das gesamte Fenster,
		# ContentScrollMixin): Das Fenster ist scrollbar, wenn der Inhalt
		# höher/breiter als der Bildschirm ist; sonst exakt auf Inhaltgröße.
		# Alles wird in ein Inhalt-Widget gepackt, das von einer
		# ContentScrollArea umschlossen wird; die Fenstergröße wird auf den
		# Bildschirm geklemmt (setMaximumSize). KEIN SetFixedSize auf dem
		# Inhalt-Layout: QLayout.SetFixedSize würde das Inhalt-Widget auf die
		# ERSTE Größe fixieren (setFixedSize) und späteres Wachstum (Service-
		# Seiten, aufgeklappte Experten-Optionen) blockieren; die Klemme würde
		# zudem das Screen-Cap überschreiben. resize_to_clamped_content() setzt
		# das Inhalt-Widget in jedem Reflow explizit auf die Layout-Größe.
		outer = QVBoxLayout(self)
		outer.setContentsMargins(0, 0, 0, 0)

		self._content_widget = QWidget()
		content_layout = QVBoxLayout(self._content_widget)
		content_layout.setSpacing(6)
		content_layout.setAlignment(Qt.AlignTop)

		plugin = self._get_plugin()
		if plugin is not None:
			self._init_plugin_ui(content_layout, plugin)
		else:
			self._init_legacy_ui(content_layout)
			# Preset-Verwaltung (Legacy: unten, im eigenen Rahmen)
			content_layout.addWidget(self._build_preset_group())

		# Bugfix (06.08.2026): _init_plugin_ui_params_only platziert den
		# Schließen-Button bereits im Plugin-Grid (Zeile 0, Spalte 2, rechts
		# mittig neben der Preset-Box) - hier NUR anfügen, wenn er nicht
		# schon im Plugin-Grid sitzt (sonst
		# Doppel-Button).
		if not getattr(self, "_close_placed_in_plugin_ui", False):
			btn_close = QPushButton("Schließen")
			btn_close.clicked.connect(self.accept)
			content_layout.addWidget(btn_close)

		# ScrollArea umschließt den Inhalt (natürliche Größe); das Fenster wird
		# auf den Bildschirm geklemmt (Scrollbars bei Überlänge, sonst exakt
		# Inhaltgröße – ohne fixe Pixelwerte).
		self.install_content_scroll(self._content_widget, parent_layout=outer)

		self._ui_ready = True
		self._reflow()

	def _init_legacy_ui(self, main_layout: QVBoxLayout) -> None:
		"""Bisheriges Layout fuer Alt-Indikatoren ohne Plugin-Schema (z.B. 'grid')."""
		form_layout = QFormLayout()
		layout_schema = self.indicator.param_layout

		if not layout_schema:
			layout_schema = list(self.params.keys())

		for item in layout_schema:
			if isinstance(item, str):
				key = item
				if key in self.params:
					label_text = self.indicator.param_labels.get(key, key.replace("_", " ").title())
					ctrl = self.create_control_widget(key, self.params[key])
					self.param_controls[key] = ctrl
					form_layout.addRow(label_text, ctrl)

			elif isinstance(item, tuple) and len(item) == 2:
				row_label, keys = item
				row_layout = QHBoxLayout()
				row_layout.setSpacing(6)

				for i, key in enumerate(keys):
					if key in self.params:
						# Sub-Label nur ab 2. Key, da row_label den ersten abdeckt
						if i > 0:
							sub_label = self.indicator.param_labels.get(key, "")
							if sub_label:
								row_layout.addWidget(QLabel(sub_label))
						ctrl = self.create_control_widget(key, self.params[key])
						self.param_controls[key] = ctrl
						row_layout.addWidget(ctrl)

				form_layout.addRow(row_label, row_layout)

		main_layout.addLayout(form_layout)

	def _init_plugin_ui(self, main_layout: QVBoxLayout, plugin: Any) -> None:
		"""Phase 13 Schritt 5: Plugin-Prop-Fenster mit Expert-Modus & Service-Sets.

		Was in den Expert-Bereich kommt, wird an den Parametern der
		Service-Definition angegeben (expert: True im parameter_schema der
		Definition, die ganz oben in der Datei steht). Der lookback ist ein
		Basis-Parameter (base_parameter_schema der Basisklasse) und erscheint
		dadurch automatisch für JEDES Plugin im Expert-Bereich.
		"""
		self.plugin = plugin
		base_schema = dict(getattr(plugin, "base_parameter_schema", None) or {})
		full_schema = dict(base_schema)
		full_schema.update(dict(plugin.parameter_schema or {}))
		self.plugin_schema = full_schema
		self.plugin_order = list(getattr(plugin, "parameter_order", None) or plugin.parameter_schema.keys())
		for key in base_schema:
			if key not in self.plugin_order:
				self.plugin_order.append(key)
		self.plugin_labels = dict(getattr(plugin, "param_labels", None) or {})
		for key, spec in base_schema.items():
			self.plugin_labels.setdefault(key, spec.get("description") or self._human(key))

		# Bugfix (06.08.2026): Plugin-Indikator OHNE deklarierte Services
		# (service_plugin_ids leer, z.B. Multi-MA 'ind_moving_averages').
		# Anwenderanforderung: "in diesem indikator gibt es keine services -
		# dazu alles ausblenden". Alle Service-Boxen ('Service-Parameter',
		# 'Service-Set Aktionen', 'Experten-Optionen') entfallen KOMPLETT;
		# der selbst-contained Indikator rendert stattdessen ALLE Parameter
		# direkt (param_layout-gruppiert, inkl. der vorher fehlenden
		# maX_type/maX_period/maX_smooth_type/maX_alpha).
		has_services = bool(self._indicator_service_ids())
		if not has_services:
			self._init_plugin_ui_params_only(main_layout)
			return

		# --- 1) Grid: Indi-Props + Service-Parameter links; rechts daneben auf
		# gleicher Höhe 'Service-Set Aktionen' (darunter 'Experten-Optionen') ---
		# Zeile 0: 'Anzeige & Farben' (links) + Preset-Rahmen (rechts oben).
		# Zeile 1: 'Service-Parameter' (links) + 'Service-Set Aktionen' mit der
		# 'Experten-Optionen'-Box direkt darunter (rechts) – die drei
		# Service-Boxen gehören thematisch zusammen und stehen daher auf
		# gleicher Höhe (gleiche Grid-Zeile, AlignTop).
		content_grid = QGridLayout()
		content_grid.setSpacing(6)
		left_col = QVBoxLayout()
		left_col.setAlignment(Qt.AlignTop)

		# --- 1a) Reine Indi-Props (Sichtbarkeit, Farben) oberhalb der Trennlinie ---
		indi_keys = [k for k in self.plugin_order if self._is_visual_key(k)]
		if indi_keys:
			indi_group = QGroupBox("Anzeige & Farben")
			# Horizontal Expanding -> füllt die Spaltenbreite (identisch mit der
			# Breite der Box 'Service-Parameter'); vertikal Maximum (Inhalt-Höhe).
			indi_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
			indi_form = QFormLayout(indi_group)
			for key in indi_keys:
				spec = self.plugin_schema.get(key, {})
				cval = self.params.get(key, spec.get("default"))
				ctrl = self.create_schema_control(key, cval, spec)
				self.param_controls[key] = ctrl
				indi_form.addRow(self.plugin_labels.get(key, self._human(key)), ctrl)
			left_col.addWidget(indi_group)

			# --- 1b) Trennlinie ---
			line = QFrame()
			line.setFrameShape(QFrame.HLine)
			line.setFrameShadow(QFrame.Sunken)
			left_col.addWidget(line)

		content_grid.addLayout(left_col, 0, 0, Qt.AlignTop)

		# --- 1c) Service-Parameter-Box (links, Zeile 1) ---
		svc_group = QGroupBox("Service-Parameter")
		# 4.2.4: Vertikale Size-Policy = Maximum -> Die Box endet dynamisch
		# unter dem letzten Parameter (z.B. Level 6) und waechst beim
		# Vergroessern des Fensters NICHT mit (bleibt auf Inhalt-Hoehe).
		svc_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
		svc_layout = QVBoxLayout(svc_group)

		set_row = QHBoxLayout()
		set_row.addWidget(QLabel("Service-Set:"))
		self.combo_service_set = QComboBox()
		self.combo_service_set.currentIndexChanged.connect(self._on_service_set_changed)
		set_row.addWidget(self.combo_service_set)
		svc_layout.addLayout(set_row)

		svc_row = QHBoxLayout()
		svc_row.addWidget(QLabel("Service:"))
		self.combo_service_sel = QComboBox()
		self.combo_service_sel.currentIndexChanged.connect(self._on_service_selected)
		svc_row.addWidget(self.combo_service_sel)
		# USER-REQ: Info-Button kompakt (nur Icon 'i'), Tooltip kurz.
		self.btn_info_service = QPushButton("ℹ")
		self.btn_info_service.setToolTip("Beschreibung des Services")
		self.btn_info_service.setFixedSize(28, 28)
		self.btn_info_service.clicked.connect(self._show_service_info)
		svc_row.addWidget(self.btn_info_service)
		svc_layout.addLayout(svc_row)

		self.stack_service_forms = _ServiceStack()
		# 4.4: Das QStackedWidget nutzt Maximum (vertikal), damit die Box
		# 'Service-Parameter' exakt unter dem letzten Parameter der AKTUELL
		# sichtbaren Service-Seite endet (kein leerer Raum durch hoechste Seite).
		self.stack_service_forms.setSizePolicy(
			QSizePolicy.Expanding, QSizePolicy.Maximum)
		svc_layout.addWidget(self.stack_service_forms)

		content_grid.addWidget(svc_group, 1, 0, Qt.AlignTop)

		# --- 1d) Rechte Spalte Zeile 0: Preset-Rahmen (rechts oben) ---
		right_top = QVBoxLayout()
		right_top.setAlignment(Qt.AlignTop)
		right_top.addWidget(self._build_preset_group(), 0, Qt.AlignTop)
		content_grid.addLayout(right_top, 0, 1, Qt.AlignTop)

		# --- 1e) Rechte Spalte Zeile 1: Service-Set Aktionen + Experten-Optionen ---
		# Direkt auf Höhe der 'Service-Parameter'-Box (gleiche Grid-Zeile 1),
		# die Expert-Box unmittelbar darunter – thematisch zusammengehörig.
		right_bottom = QVBoxLayout()
		right_bottom.setAlignment(Qt.AlignTop)

		# Set-Aktionen: Name / Speichern / Ausführen / Löschen
		act_group = QGroupBox("Service-Set Aktionen")
		# Horizontal Expanding -> füllt die rechte Spaltenbreite (wie Preset);
		# vertikal Maximum -> bleibt auf Inhalt-Höhe (Punkt 4).
		act_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
		act_layout = QVBoxLayout(act_group)

		name_row = QHBoxLayout()
		name_row.addWidget(QLabel("Name:"))
		self.edit_set_name = QLineEdit()
		name_row.addWidget(self.edit_set_name)
		act_layout.addLayout(name_row)

		# Phase 14 P14-01: Set-Beschreibung unter dem Set-Namen
		desc_row = QHBoxLayout()
		desc_row.addWidget(QLabel("Beschreibung:"))
		self.edit_set_description = QLineEdit()
		self.edit_set_description.setPlaceholderText(
			"Ausführliche Set-/Strategie-Beschreibung (optional)")
		self.edit_set_description.setToolTip(
			"Individuelle Anmerkung für dieses Service-Set (Phase 14 P14-01).")
		desc_row.addWidget(self.edit_set_description)
		act_layout.addLayout(desc_row)

		btn_row = QHBoxLayout()
		self.btn_new_service_set = QPushButton("✨ Neu")
		self.btn_new_service_set.clicked.connect(self.create_new_service_set)
		btn_row.addWidget(self.btn_new_service_set)
		self.btn_save_set = QPushButton("💾 Set speichern")
		self.btn_save_set.clicked.connect(self.save_service_set)
		btn_row.addWidget(self.btn_save_set)
		# USER-REQ: Set-ausführen-Button kompakt (nur Icon ▶, Tooltip statt Text)
		self.btn_execute_set = QPushButton("▶")
		self.btn_execute_set.setToolTip("Set ausführen")
		self.btn_execute_set.setFixedSize(28, 28)
		self.btn_execute_set.clicked.connect(self.execute_service_set)
		btn_row.addWidget(self.btn_execute_set)
		self.btn_delete_set = QPushButton("❌ Set löschen")
		self.btn_delete_set.clicked.connect(self.delete_service_set)
		btn_row.addWidget(self.btn_delete_set)
		act_layout.addLayout(btn_row)

		right_bottom.addWidget(act_group, 0, Qt.AlignTop)

		# Expert-Bereich (ausklappbar) mit Plugin-Metadaten
		self.group_expert = QGroupBox("Experten-Optionen")
		self.group_expert.setCheckable(True)
		self.group_expert.setChecked(False)
		# Horizontal Expanding -> füllt die rechte Spaltenbreite; vertikal
		# Maximum -> kollabiert beim Zuklappen auf die Titelzeile (Punkt 4).
		self.group_expert.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
		expert_layout = QVBoxLayout(self.group_expert)

		# Bugfix 05.08.2026: `metadata` ist eine PluginFeature-Property – der
		# Plugin-Pfad (Branch 1 in _get_plugin) kann aber auch einen Indikator
		# liefern, der parameter_schema+plugin_id implementiert (z.B.
		# Ind_FixedGridProximity), ohne PluginFeature zu sein (kein metadata).
		# getattr-Guard: PluginFeature unveraendert, Indikator ohne metadata
		# erhaelt leere Metadaten statt AttributeError.
		meta = dict(getattr(plugin, "metadata", None) or {})
		meta_text = (
			f"<b>{meta.get('display_name', plugin.plugin_id)}</b> "
			f"v{getattr(plugin, 'version', '1.0.0')}<br>"
			f"{meta.get('description', '')}<br>"
			f"Autor: {meta.get('author', '')}"
		)
		meta_label = QLabel(meta_text)
		meta_label.setWordWrap(True)
		expert_layout.addWidget(meta_label)

		expert_form = QFormLayout()
		expert_keys = [
			k for k in self.plugin_order
			if self.plugin_schema.get(k, {}).get("expert")
		]
		for key in expert_keys:
			spec = self.plugin_schema.get(key, {})
			cval = self.params.get(key, spec.get("default"))
			ctrl = self.create_schema_control(key, cval, spec)
			self.param_controls[key] = ctrl
			expert_form.addRow(self.plugin_labels.get(key, self._human(key)), ctrl)
		expert_layout.addLayout(expert_form)

		# 4.4: Ausklappbarer Sub-Bereich – beim Abwählen werden die Kinder
		# ausgeblendet und das Fenster nahtlos auf die neue Höhe verkleinert.
		self._setup_collapsible(self.group_expert)

		right_bottom.addWidget(self.group_expert, 0, Qt.AlignTop)

		content_grid.addLayout(right_bottom, 1, 1, Qt.AlignTop)

		# Linke Spalte bekommt beim manuellen Aufziehen den zusätzlichen Raum
		# (beide linken Boxen wachsen horizontal mit, gleiche Breite).
		content_grid.setColumnStretch(0, 1)
		main_layout.addLayout(content_grid)

		# Initiale Set-Liste befüllen (list_sets() als Quelle, Roadmap §5.2)
		self.refresh_service_set_list()

	def _init_plugin_ui_params_only(self, main_layout: QVBoxLayout) -> None:
		"""Bugfix (06.08.2026): Plugin-Indikator OHNE deklarierte Services.

		Rendert ALLE Parameter direkt - gruppiert nach `param_layout` (z.B.
		Multi-MA: 'MA 1 (Führung)' .. 'MA 8'), sonst flach. Die Service-Boxen
		('Service-Parameter', 'Service-Set Aktionen', 'Experten-Optionen')
		entfallen komplett (Anwenderanforderung, siehe _init_plugin_ui). Die
		Preset-Verwaltung bleibt erhalten (Speichern/Laden der Parameter).
		Damit erscheinen auch die vorher fehlenden Nicht-Darstellungs-Parameter
		(maX_type/maX_period/maX_smoothing/maX_alpha) im Prop-Fenster.

		Layout (Vertrag C, 07.08.2026, Anwenderanforderungen):
		  * Zeile 0: Preset-Box ganz oben links, so breit wie MA1+MA2
		    (Spalten 0-1, span 2); rechts daneben (Spalte 2) vertikal
		    zentriert der Schließen-Button.
		  * Zeile 1: die ersten zwei Parameter-Boxen nebeneinander (MA1/MA2).
		  * Danach: je 3 Parameter-Boxen pro Zeile (Multi-MA: Zeile 2 =
		    MA3/MA4/MA5, Zeile 3 = MA6/MA7/MA8).
		  * Nichts unterhalb der letzten Boxen-Zeile -> das Fenster endet
		    exakt am unteren Rand der letzten Boxen.
		  * Das kompakte 3-Spalten-Grid ergibt ~900px Breite (ContentScroll-
		    Mixin klemmt die Groesse auf den Inhalt bzw. den Bildschirm).
		"""
		content_grid = QGridLayout()
		content_grid.setSpacing(6)

		# --- Zeile 0: Preset-Box oben links (Spalten 0-1, span 2 = bis zum
		# Ende von MA2); rechts daneben in Spalte 2 vertikal zentriert der
		# Schließen-Button (rechts mittig neben der Preset-Box). ---
		self._close_placed_in_plugin_ui = True
		content_grid.addWidget(
			self._build_preset_group(), 0, 0, 1, 2, Qt.AlignTop)

		layout_schema = getattr(self.plugin, "param_layout", None)
		groups: List[Any] = []
		if isinstance(layout_schema, list) and layout_schema \
				and isinstance(layout_schema[0], (tuple, list)):
			groups = list(layout_schema)
		else:
			groups = [("Parameter", list(self.plugin_order))]

		# Parameter-Boxen bauen (gefiltert: noch nicht gerendert, nicht expert).
		rendered_groups: List[QGroupBox] = []
		for title, keys in groups:
			# Nur noch nicht gerenderte, nicht-expert Keys dieser Gruppe.
			grp_keys = [
				k for k in keys
				if k not in self.param_controls
				and not self.plugin_schema.get(k, {}).get("expert")
			]
			if not grp_keys:
				continue
			group = QGroupBox(str(title))
			# Horizontal Expanding -> füllt die Spaltenbreite (wie die
			# 'Anzeige & Farben'-Box im Service-Pfad); vertikal Maximum.
			group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
			form = QFormLayout(group)
			for key in grp_keys:
				spec = self.plugin_schema.get(key, {})
				cval = self.params.get(key, spec.get("default"))
				ctrl = self.create_schema_control(key, cval, spec)
				self.param_controls[key] = ctrl
				form.addRow(self.plugin_labels.get(key, self._human(key)), ctrl)
			rendered_groups.append(group)

		# Nicht in param_layout enthaltene Keys flach nachtragen (Schutz).
		remaining = [
			k for k in self.plugin_order
			if k not in self.param_controls
			and not self.plugin_schema.get(k, {}).get("expert")
		]
		if remaining:
			group = QGroupBox("Weitere Parameter")
			group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
			form = QFormLayout(group)
			for key in remaining:
				spec = self.plugin_schema.get(key, {})
				cval = self.params.get(key, spec.get("default"))
				ctrl = self.create_schema_control(key, cval, spec)
				self.param_controls[key] = ctrl
				form.addRow(self.plugin_labels.get(key, self._human(key)), ctrl)
			rendered_groups.append(group)

		# --- 3-Spalten-Grid (Vertrag C, Bugfix 07.08.2026) ---
		# Zeile 1: Gruppe 1 (Spalte 0) + Gruppe 2 (Spalte 1) nebeneinander
		# (MA1/MA2). Ab Gruppe 3 folgen je 3 Boxen pro Zeile (Zeile 2:
		# G3/G4/G5, Zeile 3: G6/G7/G8). Der Schliessen-Button sitzt in
		# Zeile 0 Spalte 2 (rechts mittig neben der Preset-Box).
		btn_close = QPushButton("Schließen")
		btn_close.clicked.connect(self.accept)
		if rendered_groups:
			content_grid.addWidget(rendered_groups[0], 1, 0, Qt.AlignTop)
			if len(rendered_groups) > 1:
				content_grid.addWidget(rendered_groups[1], 1, 1, Qt.AlignTop)
			content_grid.addWidget(btn_close, 0, 2, Qt.AlignCenter)
			for i in range(2, len(rendered_groups)):
				g = i - 2
				content_grid.addWidget(
					rendered_groups[i], g // 3 + 2, g % 3, Qt.AlignTop)

		# Alle 3 Spalten wachsen beim Aufziehen gleichmaessig; die Breite
		# ergibt sich aus den drei Boxen nebeneinander ("~900px", Vertrag C).
		content_grid.setColumnStretch(0, 1)
		content_grid.setColumnStretch(1, 1)
		content_grid.setColumnStretch(2, 1)
		main_layout.addLayout(content_grid)

	# -------------------------------------------------------------------------
	# Service-Set-UI (Phase 13 Schritt 5)
	# -------------------------------------------------------------------------

	def _setup_collapsible(self, group: QGroupBox) -> None:
		"""Macht eine ausklappbare QGroupBox wirklich kollabierbar (Punkt 4).

		Beim Abwählen werden die Kinder ausgeblendet und self.adjustSize()
		verkleinert das Prop-Fenster nahtlos auf die neue Inhalt-Höhe; beim
		Aufklappen wird es entsprechend vergrößert (4.4 Implementierungsanweisung).
		"""
		def _toggle(checked: bool) -> None:
			for child in group.findChildren(QWidget):
				child.setVisible(checked)
			if self._ui_ready:
				self._reflow()
		group.toggled.connect(_toggle)
		# Initialzustand anwenden (ausgeklappt/versteckt)
		_toggle(group.isChecked())

	def _reflow(self) -> None:
		"""Erzwingt die Neuberechnung des Layouts (dynamische Größe, Punkt 4).

		Bei einem nicht angezeigten Dialog werden Show-Events nicht zugestellt,
		wodurch das Haupt-Layout sonst seinen alten sizeHint behält. Durch
		explizites invalidate() wird die Gesamthöhe immer frisch berechnet.

		5.4 User-Anforderung: Die Fenstergröße wird DEFERRED auf
		min(Inhalt, Bildschirm) gesetzt (ContentScrollMixin._schedule_reflow):
		Beim Stack-Neuaufbau sind die alten Seiten per deleteLater() noch im
		Widget-Baum; bis sie zerstört sind, liefern die Layout-Caches einen
		veralteten sizeHint. _apply_reflow_size zerstört sie erst und misst
		dann den konsistenten Inhalt.
		"""
		self._schedule_reflow()

	# -------------------------------------------------------------------------
	# Indikator-Services (Phase 13 Schritt 6-Korrektur): die Services, die der
	# aktive Plugin-Indikator intern ausführt (z.B. srv_grid_lines + srv_proximity beim
	# Ind_FixedGridProximity-Indikator). grid_liquidity (Altbestand) ist nur Schema-
	# Quelle und KEIN Service des Indikators.
	# -------------------------------------------------------------------------

	def _indicator_service_ids(self) -> List[str]:
		"""Service-Plugin-IDs, die der aktive Indikator intern ausführt.

		Leer, wenn der Indikator keine deklariert → Fallback auf die Services
		des gewählten Sets (Alt-Verhalten).
		"""
		if self.indicator is None:
			return []
		ids = getattr(self.indicator, "service_plugin_ids", None)
		if isinstance(ids, (list, tuple)):
			return [str(x) for x in ids]
		return []

	def _service_items(self) -> List[Dict[str, Any]]:
		"""Anzuzeigende Services im Prop-Fenster: [{instance_id, plugin_id}].

		Bevorzugt die vom Indikator deklarierten Service-IDs (z.B. srv_grid_lines +
		srv_proximity). Existiert ein Service mit dieser plugin_id im gewählten Set,
		wird dessen instance_id (z.B. grid_1) übernommen; sonst plugin_id.
		Ohne Indikator-Deklaration: die Services des gewählten Sets.
		Phase 14 P14-01: Fallback auf das aktive Plugin als Service, wenn weder
		Set-Services noch deklarierte Services existieren (konsistent zur
		Service-Erzeugung in collect_set_definition).
		"""
		svc_ids = self._indicator_service_ids()
		definition = self._current_set_definition
		services = ((definition or {}).get("services") or {}) if definition else {}
		if not svc_ids:
			items = [
				{"instance_id": iid,
				 "plugin_id": (services.get(iid) or {}).get("plugin_id") or "?"}
				for iid in ((definition or {}).get("execution_order") or [])
			]
		else:
			items = []
			for pid in svc_ids:
				iid = next(
					(i for i in ((definition or {}).get("execution_order") or [])
					 if (services.get(i) or {}).get("plugin_id") == pid),
					None,
				)
				items.append({"instance_id": iid or pid, "plugin_id": pid})
		if not items and self.plugin is not None:
			items = [{"instance_id": self.plugin.plugin_id,
			          "plugin_id": self.plugin.plugin_id}]
		return items

	def _service_cfg(self, plugin_id: str) -> Dict[str, Any]:
		"""Konfiguration eines Service (lookback+params): aus dem gewählten Set,
		falls ein Service mit plugin_id existiert, sonst Defaults aus der
		Registry."""
		definition = self._current_set_definition
		services = ((definition or {}).get("services") or {}) if definition else {}
		for i in ((definition or {}).get("execution_order") or []):
			cfg = services.get(i) or {}
			if cfg.get("plugin_id") == plugin_id:
				return dict(cfg)
		try:
			from analytics.features.feature_builder import PluginRegistry
			sp = PluginRegistry().get(plugin_id)
			return {"plugin_id": plugin_id, "lookback": 1000,
			        "params": dict(getattr(sp, "default_params", None) or {})}
		except Exception:
			return {"plugin_id": plugin_id, "lookback": 1000, "params": {}}

	def refresh_service_set_list(self) -> None:
		"""Befüllt das Set-Dropdown aus ServiceSetRepository.list_sets()."""
		if not self.combo_service_set:
			return
		current = self.combo_service_set.currentData()
		# 5.5 Fix (Bugfix #3): Beim Oeffnen/Restore das uebergebene Set
		# vorbelegen, wenn noch keine Auswahl besteht (current leer).
		prefer = current or self._current_set_id

		self.combo_service_set.blockSignals(True)
		self.combo_service_set.clear()
		self.combo_service_set.addItem("- kein Set -", "")
		for s in self._indicator_sets():
			label = s.get("display_name") or s.get("set_id") or "Unbenannt"
			self.combo_service_set.addItem(label, s.get("set_id"))
		if prefer:
			idx = self.combo_service_set.findData(prefer)
			if idx >= 0:
				self.combo_service_set.setCurrentIndex(idx)
		self.combo_service_set.blockSignals(False)
		self._on_service_set_changed()

	def _indicator_sets(self) -> List[Dict[str, Any]]:
		"""22.01b (14.08.2026, User-Anweisung 2): Indikator-gebundene Set-Auswahl.

		Strenger Filter fuer das Prop-Fenster: nur Sets, deren
		`indicator_id == self.indicator.indicator_id` ODER die ausschliesslich
		Plugins dieses Indikators enthalten (alle service plugin_ids ⊆
		indicator.service_plugin_ids). Freie Sets und Sets anderer Indikatoren
		bleiben im globalen service_win sichtbar, NICHT hier (Konsequenz fuer
		analytics_win: bleibt ungefiltert - die Analytics-Engine liest Daten
		direkt aus dem feature_store, indikator-unabhaengig).
		"""
		try:
			all_sets = self.set_repo.list_sets()
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Set-Liste nicht ladbar: {e}")
			return []
		ind_id = str(getattr(self.indicator, "indicator_id", "") or "")
		own_plugins = {
			str(p) for p in (getattr(self.indicator, "service_plugin_ids", None) or [])
		}
		if not ind_id and not own_plugins:
			return []  # Indikator ohne Service-Zuordnung -> keine Sets anbieten
		out: List[Dict[str, Any]] = []
		for s in all_sets:
			if str(s.get("indicator_id") or "") == ind_id:
				out.append(s)
				continue
			svcs = s.get("services") or {}
			pids = [str((cfg or {}).get("plugin_id") or "")
			        for cfg in svcs.values() if isinstance(cfg, dict)]
			pids = [p for p in pids if p]
			if pids and all(p in own_plugins for p in pids):
				out.append(s)
		return out

	def _on_service_set_changed(self) -> None:
		"""Lädt das gewählte Set in den Editor + baut die Service-Seiten neu."""
		set_id = self.combo_service_set.currentData() if self.combo_service_set else ""
		self._current_set_id = set_id or None
		self._current_set_definition = None

		if set_id:
			definition = self.set_repo.get_set(set_id)
			if definition:
				self._current_set_definition = definition
				if self.edit_set_name:
					self.edit_set_name.setText(definition.get("display_name") or "")
				if self.edit_set_description:
					self.edit_set_description.setText(definition.get("description") or "")
		else:
			if self.edit_set_name:
				self.edit_set_name.clear()
			if self.edit_set_description:
				self.edit_set_description.clear()

		if self.combo_service_sel:
			self.combo_service_sel.blockSignals(True)
			self.combo_service_sel.clear()
			for item in self._service_items():
				self.combo_service_sel.addItem(
					f"{item['instance_id']} [{item['plugin_id']}]",
					item['instance_id'])
			self.combo_service_sel.blockSignals(False)

		# 5.4 Schritt 2: Die Berechnungslogik des gewählten Sets in self.params
		# mergen, damit Seite 0 (Service-Props des aktiven Plugins) die aktuellen
		# Logik-Werte zeigt. Die Darstellung (Farben, Sichtbarkeiten) bleibt
		# unberührt – sie lebt getrennt in display_params.
		self.params.update(self._resolve_set_logic_params())
		# 5.5 Fix (Bugfix #1+#3): Die zuletzt im Dialog gemeldeten Service-
		# Parameter (Live-Overlay / logic_params aus geladenem Preset) wieder
		# ueber die Set-Logik legen - so bleiben Aenderungen an grid_step,
		# prox_levels, ... beim Set-Wechsel UND beim Restore erhalten.
		self.params.update(self._preset_logic_params)
		self._rebuild_service_stack()

	def _on_service_selected(self, index: int) -> None:
		"""Wechselt die QStackedWidget-Seite (Seite i = Service i).

		Phase 14 P14-01: Es gibt keine separate Plugin-Live-Seite mehr –
		Seite 0 ist der erste Service (Parität zum service_win).
		"""
		if not self.stack_service_forms:
			return
		self.stack_service_forms.setCurrentIndex(max(0, index))
		# 4.4: Fenster/Box auf die neue Service-Seite nachziehen (dynamische Höhe)
		if self._ui_ready:
			self._reflow()

	# -------------------------------------------------------------------------
	# Phase 14 P14-01: Tooltips & Info-Dialog für Service-Instanzen
	# -------------------------------------------------------------------------

	def _build_tooltip(self, instance_id: str, config: Dict[str, Any]) -> str:
		"""Baut einen Rich-Text-Tooltip (HTML) für eine Service-Instanz.

		Angezeigt werden instance_id, Plugin-ID und – falls vorhanden – die
		individuelle Instanz-Beschreibung (ServiceInstanceConfig.description).
		"""
		lines = [f"<b>{instance_id}</b>", f"Plugin: {config.get('plugin_id', '?')}"]
		desc = config.get("description")
		if desc:
			lines.append(f"<i>{desc}</i>")
		return "<br>".join(lines)

	def _show_service_info(self) -> None:
		"""Öffnet den ServiceDescriptionDialog für die markierte Service-Instanz.

		Die Selektion kommt aus combo_service_sel (instance_id als UserData);
		Plugin-Objekt und Instanz-Config werden aus der Registry bzw. dem
		gewählten Set aufgelöst.
		"""
		if not self.combo_service_sel or self.plugin is None:
			return
		iid = self.combo_service_sel.currentData()
		if not iid:
			return
		cfg: Dict[str, Any] = {}
		if self._current_set_definition:
			cfg = dict((self._current_set_definition.get("services") or {}).get(iid, {}))
		# Live-Beschreibung aus dem Eingabefeld übernehmen (falls vorhanden)
		desc_ctrl = self._set_desc_controls.get(str(iid))
		if desc_ctrl is not None:
			cfg["description"] = desc_ctrl.text().strip()
		pid = cfg.get("plugin_id") or iid
		plugin = None
		try:
			from analytics.features.feature_builder import PluginRegistry
			plugin = PluginRegistry().get(pid)
		except KeyError:
			QMessageBox.warning(self, "Plugin nicht gefunden",
			                    f"Plugin '{pid}' ist nicht registriert.")
			return
		dlg = ServiceDescriptionDialog.from_plugin(
			plugin, instance_id=str(iid), config=cfg, parent=self)
		dlg.exec()

	def _rebuild_service_stack(self) -> None:
		"""Baut das QStackedWidget neu: EINE Seite pro Service aus dem
		Service-Modell – Parität zu den Service-Spalten im service_win.

		Phase 14 P14-01: Es werden NUR die im Service-Modell gespeicherten
		Parameter des jeweiligen Service angezeigt (cfg['params'] + lookback +
		description). Die frühere 'Seite 0' mit den Plugin-Live-Parametern aus
		self.params entfällt – sie zeigte Werte, die NICHT im Modell stehen.
		Rein visuelle Keys (show_*/color) werden ausgeblendet (wie service_win).
		"""
		if not self.stack_service_forms:
			return
		stack = self.stack_service_forms
		while stack.count():
			w = stack.widget(0)
			stack.removeWidget(w)
			w.deleteLater()
		self._set_param_controls = {}
		self._set_desc_controls = {}

		# Seiten fuer die anzuzeigenden Services (Indikator-Services, sonst
		# Services des gewählten Sets) – pro Service eine Seite
		for item in self._service_items():
			iid = item["instance_id"]
			pid = item["plugin_id"]
			cfg = self._service_cfg(pid)
			page = QWidget()
			vl = QVBoxLayout(page)
			# Phase 14 P14-01: Individuelle Instanz-Beschreibung (bearbeitbar) –
			# wird in ServiceInstanceConfig.description gespeichert und im
			# Info-Dialog (ServiceDescriptionDialog) angezeigt.
			desc_row = QHBoxLayout()
			desc_row.addWidget(QLabel("Beschreibung:"))
			desc_edit = QLineEdit()
			desc_edit.setPlaceholderText("Individuelle Anmerkung für diese Instanz (optional)")
			desc_edit.setText(str(cfg.get("description") or ""))
			self._set_desc_controls[iid] = desc_edit
			desc_row.addWidget(desc_edit)
			vl.addLayout(desc_row)
			pf = QFormLayout()
			vl.addLayout(pf)
			try:
				from analytics.features.feature_builder import PluginRegistry
				sp = PluginRegistry().get(pid)
				sp_base = dict(getattr(sp, "base_parameter_schema", None) or {})
				sp_schema = dict(sp_base)
				sp_schema.update(dict(sp.parameter_schema or {}))
				sp_labels = dict(getattr(sp, "param_labels", None) or {})
				for key, spec in sp_base.items():
					sp_labels.setdefault(key, spec.get("description") or self._human(key))
				sp_order = list(getattr(sp, "parameter_order", None) or sp.parameter_schema.keys())
				for key in sp_base:
					if key not in sp_order:
						sp_order.append(key)
				sp_params = dict(cfg.get("params") or {})
				# Normale (Nicht-Expert-, Nicht-Darstellungs-)Parameter –
				# NUR die im Service-Modell gespeicherten (wie service_win).
				for key in sp_order:
					spec = sp_schema.get(key, {})
					if spec.get("expert") or self._is_visual_key(key):
						continue
					cval = sp_params.get(key, spec.get("default"))
					# USER-REQ: P14-01 Nachtrag - Alt-Sets speichern die 6
					# Custom-Levels als Aggregat custom_levels (Liste/String)
					# statt als Einzelparameter prox_level1..6. Damit die 6
					# Level-Felder diese Werte trotzdem anzeigen, werden leere
					# Felder aus dem Aggregat vorbefüllt.
					if key.startswith("prox_level") and not cval:
						try:
							from analytics.features.definitions.srv_grid_lines import map_custom_levels_to_prox_levels
							cval = map_custom_levels_to_prox_levels(sp_params).get(key, cval)
						except Exception:
							pass
					ctrl = self.create_schema_control(key, cval, spec)
					self._set_param_controls[f"{iid}:{key}"] = ctrl
					# USER-REQ: Set bei Aenderung automatisch ausfuehren
					self._connect_service_param_commit(ctrl)
					pf.addRow(sp_labels.get(key, self._human(key)), ctrl)
				# Expert-Unterbereich je Service (lookback + expert-Parameter)
				expert_keys = [k for k in sp_order if sp_schema.get(k, {}).get("expert")]
				if expert_keys:
					exp_grp = QGroupBox("Experten-Optionen")
					exp_grp.setCheckable(True)
					exp_grp.setChecked(False)
					ef = QFormLayout(exp_grp)
					for key in expert_keys:
						spec = sp_schema.get(key, {})
						if key == "lookback":
							# lookback ist die Service-Instanz-Einstellung
							# (ServiceInstanceConfig.lookback), nicht ein
							# Plugin-param.
							cval = cfg.get("lookback", spec.get("default"))
						else:
							cval = sp_params.get(key, spec.get("default"))
						ctrl = self.create_schema_control(key, cval, spec)
						self._set_param_controls[f"{iid}:{key}"] = ctrl
						# USER-REQ: Set bei Aenderung automatisch ausfuehren
						self._connect_service_param_commit(ctrl)
						ef.addRow(sp_labels.get(key, self._human(key)), ctrl)
					vl.addWidget(exp_grp)
					# 4.4: Auch der Service-Expert-Bereich ist ausklappbar
					# (Kinder ein-/ausblenden + adjustSize auf dem Dialog).
					self._setup_collapsible(exp_grp)
			except Exception:
				pf.addRow(QLabel(f"Plugin '{pid}' nicht gefunden."))
			stack.addWidget(page)

		# Phase 14 P14-01: Stack-Seite mit der Combo-Auswahl synchronisieren
		# (Seite 0 = erster Service; keine separate Plugin-Seite mehr).
		if self.combo_service_sel is not None:
			combo_idx = self.combo_service_sel.currentIndex()
		else:
			combo_idx = 0
		if stack.count():
			stack.setCurrentIndex(max(0, min(combo_idx, stack.count() - 1)))
		# 4.4: Fenster/Box auf die neue Stack-Seite nachziehen (dynamische Höhe)
		if self._ui_ready:
			self._reflow()

	def _resolve_set_logic_params(self) -> Dict[str, Any]:
		"""5.4 Schritt 2: Berechnungslogik des gewählten Service-Sets.

		Liefert lookback + params des Service im Set, dessen plugin_id zum
		aktiven Plugin passt (sonst erster Service). Leer, wenn kein Set
		gewählt ist oder das Set keine Services hat. Die Darstellung (Farben,
		Sichtbarkeiten) bleibt davon unberührt – sie lebt in display_params.
		"""
		if self.plugin is None:
			return {}
		set_id = self.combo_service_set.currentData() if self.combo_service_set else ""
		if not set_id:
			return {}
		try:
			definition = self.set_repo.get_set(set_id)
			services = (definition or {}).get("services") or {}
			order = (definition or {}).get("execution_order") or []
			# Alle Services des Sets mergen, die zum Indikator gehören (das
			# aktive Plugin selbst ODER deklarierte Indikator-Services wie
			# srv_grid_lines + srv_proximity). Fremde Services werden nicht eingemischt.
			svc_ids = self._indicator_service_ids()
			merged: Dict[str, Any] = {}
			merged_lookback: Optional[int] = None
			for iid in order:
				s = services.get(iid) or {}
				sid = s.get("plugin_id")
				if not (sid == self.plugin.plugin_id or sid in svc_ids):
					continue
				if s.get("lookback") is not None:
					merged_lookback = int(s["lookback"])
				merged.update(dict(s.get("params") or {}))
			if not merged and order:
				# Fallback (Alt): erster Service des Sets
				s = services.get(order[0]) or {}
				if s.get("lookback") is not None:
					merged_lookback = int(s["lookback"])
				merged.update(dict(s.get("params") or {}))
			if merged_lookback is not None:
				merged["lookback"] = merged_lookback
			return merged
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Service-Set '{set_id}' nicht ladbar: {e}")
			return {}

	def _collect_logic_params(self) -> Dict[str, Any]:
		"""5.5 Fix: Live-Service-Parameter (logic_params) aus den Controls.

		Alle Nicht-Darstellungs-Keys aus self.param_controls (Box
		'Service-Parameter' + Expert-Optionen des aktiven Plugins) - also
		grid_step, proximity_threshold, prox_levels, lookback usw. Diese
		ueberlagern im Chart die Basis-Logik des Service-Sets (Live-Overlay).
		USER-REQ: Zusaetzlich werden die aktuellen Werte der Service-Seiten
		(_set_param_controls) als Live-Overlay gemeldet, damit Aenderungen an
		Service-Parametern SOFORT im Chart sichtbar werden (on_param_control_
		changed feuert bei editingFinished ueber create_schema_control).
		"""
		logic: Dict[str, Any] = {}
		for key, ctrl in self.param_controls.items():
			if not self._is_visual_key(key):
				logic[key] = self._ctrl_value(ctrl)
		for fkey, ctrl in self._set_param_controls.items():
			iid, key = fkey.split(":", 1)
			if self._is_visual_key(key) or key == "lookback":
				continue  # Darstellung + Instanz-Setting (lookback) nicht in die Logik
			logic[key] = self._ctrl_value(ctrl)
		return logic

	def _build_preset_payload(self) -> Dict[str, Any]:
		"""5.4 Schritt 2 + 5.5 Fix: Getrenntes Rückgabe-Dictionary (Logik vs. Darstellung).

		Plugin-Modus: set_id (gewähltes Service-Set) + logic_params (Live-
		Service-Parameter aus der Box 'Service-Parameter' + Expert-Optionen)
		+ display_params (nur reine Darstellung: Sichtbarkeit, Farben). Die
		Basis-Berechnungslogik lebt im Service-Set (service_sets-Tabelle);
		logic_params ueberlagert sie als Live-Overlay, damit Aenderungen an
		grid_step / prox_levels / lookback SOFORT auf dem Chart erscheinen.
		Legacy (Alt-Indikator ohne Plugin): volle params (kein Set).
		"""
		if self.plugin is None:
			return dict(self.collect_params_from_ui())
		set_id = self.combo_service_set.currentData() if self.combo_service_set else ""
		display: Dict[str, Any] = {}
		for key, ctrl in self.param_controls.items():
			if self._is_visual_key(key):
				display[key] = self._ctrl_value(ctrl)
				# P16.03-Bugfix: Form/Groesse bzw. Linienart/-staerke in
				# display_params aufnehmen (Konvention 'color' -> 'shape'/'size'
				# bzw. 'style'/'width'), damit Presets die Auswahl im
				# StylePickerWidget round-trippen. Bugfix (06.08.2026):
				# color_only-Waehler (Multi-MA) haben KEINE Geschwister-Keys
				# und werden uebersprungen.
				if isinstance(ctrl, StylePickerWidget):
					if getattr(ctrl, "color_only", False):
						continue
					style_obj = ctrl.get_style()
					if isinstance(style_obj, MarkerStyle):
						shape_key, size_key = self._style_sibling_keys(key, "marker")
						if shape_key:
							display[shape_key] = style_obj.shape
						if size_key:
							display[size_key] = style_obj.size
					elif isinstance(style_obj, LineStyle):
						style_key, width_key = self._style_sibling_keys(key, "line")
						if style_key:
							display[style_key] = style_obj.style
						if width_key:
							display[width_key] = style_obj.width
		return {"set_id": set_id or "", "logic_params": self._collect_logic_params(),
		        "display_params": display}

	# -------------------------------------------------------------------------
	# Set-Aktionen (Phase 13 Schritt 5)
	# -------------------------------------------------------------------------

	def collect_set_definition(self) -> Dict[str, Any]:
		"""Baut die ServiceSetDefinition aus Set + Editor zusammen."""
		if self._current_set_definition:
			definition = dict(self._current_set_definition)
			services = dict(definition.get("services") or {})
		else:
			definition = {"set_id": "", "display_name": "", "execution_order": [], "services": {}}
			services = {}

		if self.edit_set_name:
			definition["display_name"] = self.edit_set_name.text().strip()
		if self.edit_set_description:
			definition["description"] = self.edit_set_description.text().strip()

		# Kein Set geladen → die Indikator-Services (z.B. srv_grid_lines + srv_proximity)
		# als neue Services, sonst das aktive Plugin (instance_id = plugin_id).
		if not definition.get("execution_order") and self.plugin is not None:
			svc_ids = self._indicator_service_ids()
			if svc_ids:
				for sid in svc_ids:
					try:
						from analytics.features.feature_builder import PluginRegistry
						base = dict(getattr(PluginRegistry().get(sid), "default_params", None) or {})
					except Exception:
						base = {}
					params = dict(base)
					lookback = int(params.pop("lookback", 1000) or 1000) if "lookback" in params else 1000
					for fkey, ctrl in self._set_param_controls.items():
						iid, key = fkey.split(":", 1)
						if iid != sid:
							continue
						if key == "lookback":
							lookback = int(self._ctrl_value(ctrl))
						else:
							params[key] = self._ctrl_value(ctrl)
					services[sid] = {"plugin_id": sid, "lookback": lookback, "params": params}
				definition["execution_order"] = list(svc_ids)
			else:
				pid = self.plugin.plugin_id
				params: Dict[str, Any] = {}
				lookback: int = 1000
				# Phase 14 P14-01: Der Plugin-als-Service-Editor liegt jetzt in
				# den Service-Seiten (_set_param_controls), nicht mehr auf einer
				# separaten Plugin-Live-Seite (param_controls / self.params).
				for fkey, ctrl in self._set_param_controls.items():
					c_iid, key = fkey.split(":", 1)
					if c_iid != pid:
						continue
					if key == "lookback":
						lookback = int(self._ctrl_value(ctrl))
					else:
						params[key] = self._ctrl_value(ctrl)
				services[pid] = {"plugin_id": pid, "lookback": lookback, "params": params}
				definition["execution_order"] = [pid]

		# Service-Params aus den Set-Formular-Seiten übernehmen.
		# lookback ist die Service-Instanz-Einstellung (ServiceInstanceConfig.
		# lookback) und wird NICHT in params geschrieben.
		for fkey, ctrl in self._set_param_controls.items():
			iid, pkey = fkey.split(":", 1)
			existing_cfg = services.get(iid) or {}
			pid = (existing_cfg.get("plugin_id")
			       or (iid if iid in self._indicator_service_ids()
			           else (self.plugin.plugin_id if self.plugin else iid)))
			cfg = services.setdefault(iid, {"plugin_id": pid, "params": {}})
			if pkey == "lookback":
				cfg["lookback"] = int(self._ctrl_value(ctrl))
			else:
				cfg.setdefault("params", {})[pkey] = self._ctrl_value(ctrl)

		# Phase 14 P14-01: Instanz-Beschreibung aus den Service-Seiten
		# übernehmen (ServiceInstanceConfig.description – gehört NICHT in params).
		for iid, ctrl in self._set_desc_controls.items():
			existing_cfg = services.get(iid) or {}
			pid = (existing_cfg.get("plugin_id")
			       or (iid if iid in self._indicator_service_ids()
			           else (self.plugin.plugin_id if self.plugin else iid)))
			cfg = services.setdefault(iid, {"plugin_id": pid, "params": {}})
			cfg["description"] = ctrl.text().strip()

		definition["services"] = services
		return definition

	def _generate_default_service_set_name(self) -> str:
		"""Generiert einen vorgegebenen Namen aus Indikator-Name und Symbol.

		Bugfix: Vorschlag im Format '<Indikator-Name>-<Symbol>-', getrennt
		durch Bindestriche OHNE Leerzeichen (z. B. 'Ind_FixedGridProximity-BTCUSD-').
		Als Vorgabe wird NUR der Indikator-Name genommen (display_name, ohne
		'(Plugin)'-Suffix) – NICHT die Service-Namen (plugin.metadata
		enthaelt z. B. 'Ind_FixedGridProximity' und faellt als Quelle
		weg). Fallback auf plugin_id bzw. 'Set'; Symbol aus dem Dialog-
		Kontext, Fallback 'DEFAULT'.
		"""
		indicator_name: str = ""
		dn = getattr(self.indicator, "display_name", None)
		if dn and str(dn).strip():
			indicator_name = str(dn).strip()
		# Nachgestelltes '(Plugin)'-Suffix entfernen (reiner Indikator-Name).
		if indicator_name.endswith(")"):
			import re
			indicator_name = re.sub(r"\s*\([^)]*\)\s*$", "", indicator_name).strip()
		if not indicator_name and self.plugin is not None:
			indicator_name = str(getattr(self.plugin, "plugin_id", "") or "").strip()
		if not indicator_name:
			indicator_name = "Set"
		symbol = str(getattr(self, "symbol", None) or "DEFAULT").strip() or "DEFAULT"
		return f"{indicator_name}-{symbol}-"

	def create_new_service_set(self) -> None:
		"""Setzt den Editor zurück, um ein völlig neues Service-Set anzulegen,
		und belegt das Namensfeld mit einem dynamischen Vorschlag vor.

		5.6 + 5.6.5: Parität zur Preset-Verwaltung – „Neu / Leeren“ leert die
		Set-Auswahl („- kein Set -“), setzt _current_set_id/_current_set_definition
		auf None und baut den Service-Stack auf den Default-Zustand (Indikator-
		Services mit Default-Params) zurück. Das Namensfeld wird danach mit
		'<Indikator-Name> - <Symbol>' vorbelegt und der Text für die direkte
		Bearbeitung markiert (selectAll + Fokus). Die Service-Parameter des
		aktiven Plugins (Live-Overlay) bleiben als Ausgangsbasis erhalten.
		"""
		self._current_set_id = None
		self._current_set_definition = None
		if self.edit_set_name:
			self.edit_set_name.clear()
		if self.edit_set_description:
			self.edit_set_description.clear()
		if self.combo_service_set:
			self.combo_service_set.blockSignals(True)
			self.combo_service_set.setCurrentIndex(0)  # "- kein Set -"
			self.combo_service_set.blockSignals(False)
		# _on_service_set_changed leert Namensfeld, baut combo_service_sel +
		# Service-Stack neu und setzt self.params auf die Indikator-Default-Logik.
		self._on_service_set_changed()
		# 5.6.5: Namensfeld mit dynamischem Vorschlag vorbelegen + markieren.
		default_name = self._generate_default_service_set_name()
		if self.edit_set_name:
			self.edit_set_name.setText(default_name)
			self.edit_set_name.selectAll()
			self.edit_set_name.setFocus()
		if self._ui_ready:
			self._reflow()

	def save_service_set(self) -> None:
		"""Speichert das aktive Set – analog zur Preset-Verwaltung (generisch).

		Namensdialog (vorbelegt), leerer Name → Auto-Name aus instance_ids
		(z.B. 'grid_1 + prox_1'), Überschreiben-Rückfrage bei doppeltem Namen.
		Implementierung: NamedItemActionsMixin.save_named_item() mit dem
		Service-Set-Adapter (_ServiceSetItemAdapter).
		"""
		self.save_named_item(
			self._set_adapter,
			dialog_title="Service-Set speichern",
			prompt="Name für das Service-Set:",
		)

	def delete_service_set(self) -> None:
		"""Löscht das gewählte Set – analog zur Preset-Verwaltung (generisch).

		Rückfrage (QMessageBox.question), danach wird das nächstverfügbare Set
		ausgewählt. Implementierung: NamedItemActionsMixin.delete_named_item()
		mit dem Service-Set-Adapter.
		"""
		self.delete_named_item(self._set_adapter)

	# -------------------------------------------------------------------------
	# USER-REQ: Automatische Set-Ausfuehrung bei Service-Parameter-Aenderung
	# -------------------------------------------------------------------------

	def _connect_service_param_commit(self, ctrl: QWidget) -> None:
		"""Verbindet ein Service-Parameter-Control mit der Auto-Ausfuehrung.

		USER-REQ: Bei Verlassen des Eingabefeldes (editingFinished bei
		SpinBox/LineEdit) bzw. sofortiger Aenderung (Checkbox/Combo) wird das
		Set automatisch ausgefuehrt, damit die Aenderung sofort im Chart
		sichtbar wird. on_param_control_changed (in create_schema_control
		verbunden) meldet die Werte bereits als Live-Overlay an den Chart;
		diese Methode ergaenzt nur den Auto-Run.
		"""
		if isinstance(ctrl, (QSpinBox, QDoubleSpinBox, QLineEdit)):
			ctrl.editingFinished.connect(self._on_service_param_commit)
		elif isinstance(ctrl, QCheckBox):
			ctrl.toggled.connect(self._on_service_param_commit)
		elif isinstance(ctrl, QComboBox):
			ctrl.currentTextChanged.connect(self._on_service_param_commit)

	def _on_service_param_commit(self, *args: Any) -> None:
		"""Fuehrt das Set nach einer Service-Parameter-Aenderung aus."""
		self.execute_service_set()

	def execute_service_set(self) -> None:
		"""Startet den ServiceSetEvaluator für das aktive Set (Hintergrund-Thread)."""
		definition = self.collect_set_definition()
		if not definition.get("execution_order") or not definition.get("services"):
			return
		if self._set_run_worker and self._set_run_worker.isRunning():
			print("⚠️ [IndicatorDialog] Set-Ausführung läuft bereits.")
			return
		self._set_run_worker = DialogServiceSetRunWorker(
			self.set_evaluator, self.symbol, self.timeframe, definition, parent=self,
		)
		self._set_run_worker.run_finished.connect(self._on_set_run_finished)
		self._set_run_worker.run_failed.connect(self._on_set_run_failed)
		self._set_run_worker.start()

	def _on_set_run_finished(self, set_id: str, count: int) -> None:
		print(f"✅ [IndicatorDialog] Set-Ausführung abgeschlossen: {count} Services.")

	def _on_set_run_failed(self, set_id: str, error: str) -> None:
		QMessageBox.warning(self, "Set-Ausführung fehlgeschlagen", str(error))

	# -------------------------------------------------------------------------
	# Legacy-Helfer (für Alt-Indikatoren)
	# -------------------------------------------------------------------------

	def create_control_widget(self, key: str, val: Any) -> QWidget:
		if key in self.indicator.param_options:
			combo = QComboBox()
			options = [str(opt) for opt in self.indicator.param_options[key]]
			combo.addItems(options)
			combo.setCurrentText(str(val))
			combo.currentTextChanged.connect(self.on_param_control_changed)
			return combo

		elif isinstance(val, bool):
			chk = QCheckBox()
			chk.setChecked(val)
			chk.toggled.connect(self.on_param_control_changed)
			return chk

		elif isinstance(val, int):
			spin = QSpinBox()
			spin.setRange(-100000, 100000)
			spin.setValue(val)
			spin.editingFinished.connect(self.on_param_control_changed)
			return spin

		elif isinstance(val, float):
			spin_f = QDoubleSpinBox()
			spin_f.setRange(-100000.0, 100000.0)
			spin_f.setDecimals(4)
			spin_f.setSingleStep(0.01)
			spin_f.setValue(val)
			spin_f.editingFinished.connect(self.on_param_control_changed)
			return spin_f

		else:
			txt = QLineEdit()
			txt.setText(str(val))
			txt.editingFinished.connect(self.on_param_control_changed)
			return txt

	# -------------------------------------------------------------------------
	# Geometrie-Persistenz & Presets (unverändert für beide Modi)
	# -------------------------------------------------------------------------

	def _restore_geometry(self) -> None:
		"""Stellt die letzte POSITION des nicht-modalen Dialogs wieder her.

		Phase 13 Schritt 5 Punkt 4: Die Größe wird NICHT wiederhergestellt –
		das Prop-Fenster ist vollständig dynamisch (Inhalt bestimmt Höhe/Breite,
		keine fixen Pixelwerte, kein leerer Raum unter dem Preset-Block).
		"""
		try:
			geom = self.state_manager.get_dialog_geometry(self.DIALOG_GEOMETRY_KEY)
			if not geom:
				return

			pos_x = geom.get("pos_x")
			pos_y = geom.get("pos_y")

			# Position validieren (Bildschirm-Bounds; sonst zuruecksetzen)
			if pos_x is not None and pos_y is not None:
				screen = QApplication.primaryScreen().availableGeometry()
				if pos_x < screen.x() - 100 or pos_x > screen.right() or \
				   pos_y < screen.y() - 100 or pos_y > screen.bottom():
					pos_x = pos_y = None
				else:
					self.move(pos_x, pos_y)
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Geometrie-Restore fehlgeschlagen: {e}")

	def _save_geometry(self) -> None:
		"""Speichert die aktuelle Position/Groesse des Dialogs.

		Punkt 4: Wiederhergestellt wird nur die Position (siehe
		_restore_geometry) – die Größe ist dynamisch (Inhalt bestimmt Höhe/Breite).
		"""
		try:
			p = self.pos()
			s = self.size()
			self.state_manager.save_dialog_geometry(
				self.DIALOG_GEOMETRY_KEY, p.x(), p.y(), s.width(), s.height()
			)
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Geometrie-Save fehlgeschlagen: {e}")

	def done(self, r: int) -> None:
		"""Wird bei jedem Schliessen aufgerufen (accept/reject/Esc/X) ->
		Geometrie vor dem Schliessen speichern."""
		self._save_geometry()
		if self._set_run_worker and self._set_run_worker.isRunning():
			self._set_run_worker.wait(2000)
		super().done(r)

	# -------------------------------------------------------------------------
	# Preset-Verwaltung (Phase 13 Schritt 5 Punkt 4: im eigenen Rahmen)
	# -------------------------------------------------------------------------

	def _build_preset_group(self) -> QGroupBox:
		"""Baut die Preset-Verwaltungsbox (Rahmen um die Preset-Auswahl).

		Im Plugin-Modus wird sie direkt rechts oben neben 'Anzeige & Farben'
		platziert; im Legacy-Modus unten (bisherige Position). Die Box wächst
		nicht mit dem Fenster mit (Punkt 4: dynamische Größen).
		"""
		preset_group = QGroupBox("Preset")
		preset_layout = QHBoxLayout(preset_group)
		preset_layout.addWidget(QLabel("Preset:"))

		self.combo_presets = QComboBox()
		self.refresh_preset_list()
		self.combo_presets.currentTextChanged.connect(self.on_preset_selected)
		preset_layout.addWidget(self.combo_presets)

		btn_save_preset = QPushButton("💾 Speichern")
		btn_save_preset.clicked.connect(self.save_current_preset)
		preset_layout.addWidget(btn_save_preset)

		btn_delete_preset = QPushButton("❌ Löschen")
		btn_delete_preset.clicked.connect(self.delete_current_preset)
		preset_layout.addWidget(btn_delete_preset)

		preset_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
		return preset_group

	def refresh_preset_list(self) -> None:
		self.combo_presets.blockSignals(True)
		self.combo_presets.clear()
		presets = self.state_manager.list_indicator_presets(self.indicator.indicator_id)
		self.combo_presets.addItems(presets)

		if self.current_preset_name in presets:
			self.combo_presets.setCurrentText(self.current_preset_name)
		else:
			self.combo_presets.setCurrentText("Default")

		self.combo_presets.blockSignals(False)

	def collect_params_from_ui(self) -> Dict[str, Any]:
		# Mit default_params starten, damit Keys ohne UI-Control erhalten bleiben
		new_params = dict(self.indicator.default_params)

		for key, ctrl in self.param_controls.items():
			if isinstance(ctrl, QCheckBox):
				new_params[key] = ctrl.isChecked()
			elif isinstance(ctrl, QSpinBox):
				new_params[key] = ctrl.value()
			elif isinstance(ctrl, QDoubleSpinBox):
				new_params[key] = ctrl.value()
			elif isinstance(ctrl, QComboBox):
				raw_val = ctrl.currentText()
				default_val = self.indicator.default_params.get(key)

				# Typsicheres Casten anhand des Ursprungstyps im Indikator
				if isinstance(default_val, bool):
					new_params[key] = raw_val.lower() in ("true", "1", "yes")
				elif isinstance(default_val, int):
					try:
						new_params[key] = int(raw_val)
					except ValueError:
						new_params[key] = default_val
				elif isinstance(default_val, float):
					try:
						new_params[key] = float(raw_val)
					except ValueError:
						new_params[key] = default_val
				else:
					new_params[key] = raw_val
			elif isinstance(ctrl, StylePickerWidget):
				style_obj = ctrl.get_style()
				new_params[key] = style_obj.color
				# Bugfix (06.08.2026): color_only-Waehler (Multi-MA) haben
				# keine Geschwister-Keys -> Sibling-Schreiben ueberspringen.
				if getattr(ctrl, "color_only", False):
					continue
				# P16.03-Bugfix: Form/Groesse bzw. Linienart/-staerke in die
				# Geschwister-Keys schreiben (Konvention 'color' ->
				# 'shape'/'size' bzw. 'style'/'width'), damit die Auswahl im
				# Widget persistiert und der Indikator sie in den Payload gibt.
				if isinstance(style_obj, MarkerStyle):
					shape_key, size_key = self._style_sibling_keys(key, "marker")
					if shape_key:
						new_params[shape_key] = style_obj.shape
					if size_key:
						new_params[size_key] = style_obj.size
				elif isinstance(style_obj, LineStyle):
					style_key, width_key = self._style_sibling_keys(key, "line")
					if style_key:
						new_params[style_key] = style_obj.style
					if width_key:
						new_params[width_key] = style_obj.width
			elif isinstance(ctrl, QLineEdit):
				new_params[key] = ctrl.text()
		return new_params

	def update_ui_from_params(self, params_dict: Dict[str, Any]) -> None:
		for key, val in params_dict.items():
			if key in self.param_controls:
				ctrl = self.param_controls[key]
				ctrl.blockSignals(True)

				if isinstance(ctrl, QCheckBox) and isinstance(val, bool):
					ctrl.setChecked(val)
				elif isinstance(ctrl, (QSpinBox, QDoubleSpinBox)) and isinstance(val, (int, float)):
					ctrl.setValue(val)
				elif isinstance(ctrl, QComboBox):
					ctrl.setCurrentText(str(val))
				elif isinstance(ctrl, StylePickerWidget) and isinstance(val, str):
					ctrl.set_color(val)
					# Bugfix (06.08.2026): color_only-Waehler (Multi-MA) haben
					# keine Geschwister-Keys -> Restore-Schritt ueberspringen.
					if getattr(ctrl, "color_only", False):
						continue
					# P16.03-Bugfix: Form/Groesse bzw. Linienart/-staerke aus
					# den Geschwister-Params zurueckspielen (sonst zeigt das
					# Widget beim Restore die Defaults, obwohl der Chart die
					# gespeicherte Form nutzt).
					style_obj = ctrl.get_style()
					if isinstance(style_obj, MarkerStyle):
						shape_key, size_key = self._style_sibling_keys(key, "marker")
						if shape_key and shape_key in params_dict:
							shp = str(params_dict.get(shape_key) or "circle")
							if shp in MARKER_SHAPES:
								style_obj.shape = shp
						if size_key and size_key in params_dict:
							try:
								style_obj.size = int(params_dict.get(size_key))
							except (TypeError, ValueError):
								pass
						ctrl.set_style(style_obj)
					elif isinstance(style_obj, LineStyle):
						style_key, width_key = self._style_sibling_keys(key, "line")
						if style_key and style_key in params_dict:
							stl = str(params_dict.get(style_key) or "solid")
							if stl in LINE_STYLES:
								style_obj.style = stl
						if width_key and width_key in params_dict:
							try:
								style_obj.width = int(params_dict.get(width_key))
							except (TypeError, ValueError):
								pass
						ctrl.set_style(style_obj)
				elif isinstance(ctrl, QLineEdit) and isinstance(val, str):
					ctrl.setText(val)

				ctrl.blockSignals(False)

	def on_param_control_changed(self) -> None:
		self.params = self.collect_params_from_ui()
		# 5.5 Fix: Das Live-Overlay (logic_params) bei jeder Aenderung
		# mitfuehren, damit Set-Wechsel/Restore im Dialog den aktuellen
		# Stand der Service-Parameter beibehalten (Bugfix #1+#3).
		if self.plugin is not None:
			self._preset_logic_params = self._collect_logic_params()
		# 5.4 Schritt 2: Getrenntes Dict {set_id, display_params} an das
		# Chart-Window – die Berechnungslogik lebt im Service-Set.
		self.on_params_changed_callback(self._build_preset_payload(), self.current_preset_name)

	def on_preset_selected(self, preset_name: str) -> None:
		if not preset_name:
			return

		self.current_preset_name = preset_name

		if preset_name == "Default":
			self.params = dict(self.indicator.default_params)
		else:
			loaded = self.state_manager.get_indicator_preset(self.indicator.indicator_id, preset_name)
			if loaded:
				if (self.plugin is not None and isinstance(loaded, dict)
						and "display_params" in loaded):
					# 5.4 Schritt 2: Decoupled Preset (set_id + display_params).
					# Darstellung übernehmen, Set-Auswahl setzen (löst
					# _on_service_set_changed → mergt die Logik in self.params).
					# 5.5 Fix (Bugfix #3): Auch logic_params aus dem Preset
					# laden - das sind die zuletzt gemeldeten Service-Werte
					# (Live-Overlay), die beim Restore erhalten bleiben muessen.
					display = dict(loaded.get("display_params") or {})
					self._preset_logic_params = dict(loaded.get("logic_params") or {})
					set_id = loaded.get("set_id") or ""
					merged = dict(self.indicator.default_params)
					merged.update(self._preset_logic_params)
					merged.update(display)
					self.params = merged
					if self.combo_service_set:
						idx = self.combo_service_set.findData(set_id)
						self.combo_service_set.setCurrentIndex(idx if idx >= 0 else 0)
				else:
					# Legacy-Preset: volle params
					self.params = loaded

		self.update_ui_from_params(self.params)
		self.on_params_changed_callback(self._build_preset_payload(), self.current_preset_name)

	def save_current_preset(self) -> None:
		"""Speichert das aktive Preset (generische Preset-Mechanik).

		Implementierung: NamedItemActionsMixin.save_named_item() mit dem
		Preset-Adapter (_PresetItemAdapter) – Namensdialog, Überschreiben-
		Rückfrage bei doppeltem Namen. 'Default' ist überschreibbar
		(Anwender-Anweisung 06.08.2026).
		"""
		self.params = self.collect_params_from_ui()
		self.save_named_item(
			self._preset_adapter,
			dialog_title="Preset speichern",
			prompt="Name für das Parameter-Set:",
		)

	def delete_current_preset(self) -> None:
		"""Löscht das aktive Preset (generische Preset-Mechanik).

		Implementierung: NamedItemActionsMixin.delete_named_item() mit dem
		Preset-Adapter – Rückfrage, danach nächstverfügbares Preset laden.
		'Default' ist löschbar (Anwender-Anweisung 06.08.2026).
		"""
		self.delete_named_item(self._preset_adapter)

```

--------------------------------------------------

### DATEI: chart/indicators/__init__.py
```py
# ==============================================================================
# chart/indicators/__init__.py
# ==============================================================================
# Phase 15: Alt-Indikator 'grid' (grid.py) entfernt. Verbleibende Indikatoren
# werden direkt über ihre Module importiert (z. B. chart_win.py importiert
# chart.indicators.ind_fixed_grid_proximity.FixedGridProximityIndicator bzw.
# chart.indicators.ind_moving_averages.MultiMovingAverageIndicator).
# Naming Convention 16.08.01: Dateiname = indicator_id (ind_-Präfix).
# Keine Exporte im Paket-__init__ – keine harten Imports erforderlich.
```

--------------------------------------------------

### DATEI: chart/indicators/base_indicator.py
```py
"""
chart/indicators/base_indicator.py - Base Class for all PyTrader Indicators
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import pandas as pd


class BaseIndicator(ABC):

	def __init__(self) -> None:
		pass

	@property
	@abstractmethod
	def indicator_id(self) -> str:
		"""Eindeutige ID des Indikators (z. B. 'grid')."""
		pass

	@property
	@abstractmethod
	def display_name(self) -> str:
		"""Anzeigename für UI & Button-Tooltips."""
		pass

	@property
	@abstractmethod
	def default_params(self) -> Dict[str, Any]:
		"""Standard-Parameter mit Werten."""
		pass

	@property
	def param_options(self) -> Dict[str, List[Any]]:
		"""Optional: Dropdown-Optionen für bestimmte Schlüssel."""
		return {}

	@property
	def param_labels(self) -> Dict[str, str]:
		"""Optional: Benutzerdefinierte Label für Parameter (key → Anzeigename)."""
		return {}

	@property
	def param_layout(self) -> Optional[List[Any]]:
		"""Optional: Layout-Struktur für mehrspaltige Parameter-Zeilen."""
		return None

	@abstractmethod
	def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
		"""Führt die mathematische Berechnung auf dem DataFrame aus und liefert Zeichnungsdaten zurück."""
		pass

	def get_live_overlays(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""P14-03-E: Liefert die Live-Overlays des Plugins als Liste von Overlay-Items
		{kind, layer, time, price, color, priority, ...}. Basis-Default: [].
		Plugin-Klassen überschreiben diesen Hook (Open/Closed), damit die Engine
		(chart_win) die Overlays ALLER aktiven Indikatoren generisch einsammelt –
		kein Indikator-spezifischer Sonderfall pro Plugin."""
		return []

	def remember_live_time(self, ts: int) -> None:
		"""P14-03-E (Flacker-Fix): Merkt eine offene Live-Bar-Zeit (gerundete
		Epoch), damit der New-Candle-Erkennung des Plugins nach einem
		calculate()-Rebuild die Live-Bar nicht als "neue Kerze" erscheint und der
		debounced Refresh nicht erneut feuert. Basis-Default: no-op.
		Plugin-Klassen mit New-Candle-Callback überschreiben diesen Hook
		(Open/Closed), damit die Engine (chart_win) die Re-Injektion generisch
		über ALLE Indikatoren ausführen kann – kein Indikator-Sonderfall."""
		pass
```

--------------------------------------------------

### DATEI: chart/indicators/ind_fixed_grid_proximity.py
```py
# chart/indicators/ind_fixed_grid_proximity.py
"""
NEUER Grid-Indikator mit Service-Pipeline (Phase 13 Schritt 6).

Der Indikator ist jetzt der VISUELLE ADAPTER über die neuen Services
srv_grid_lines + srv_proximity (analytics/features/definitions/):

  * Historical-Run: Er instanziiert intern eine ServiceSetDefinition
    (grid_1 → srv_grid_lines, prox_1 → srv_proximity, Reihenfolge + depends_on) und
    führt sie über den ServiceSetEvaluator aus. Die Linien (Parität zu
    chart/indicators/grid.py) werden THREAD-SICHER in self._cached_grid_lines
    zwischengespeichert (atomare Zuweisung unter Lock).
  * Live-Ticks (update_live_candle): Die Pipeline wird NICHT aufgerufen. Es
    wird ausschließlich die mathematische Differenz zwischen dem Live-Tick und
    den gecachten Linien berechnet (prozentuale visit%-Semantik), um
    Live-Punkte zu setzen. Ein neuer Close (gerundete Time nicht in
    self._known_times) stößt NUR einen debounced Refresh an – nicht jeder Tick.

SELF-CONTAINED (Bugfix 04.08.2026): Das UI-Schema (grid_step /
proximity_threshold / prox_level1-6 / Farben) ist direkt in diesem Modul
hinterlegt (_FIXED_GRID_PROXIMITY_SCHEMA) – der Indikator ist dadurch die eigene
Single Source of Truth für das Prop-Fenster (parameter_schema/plugin_id) und
hängt NICHT mehr am entfernten Alt-Plugin 'grid_liquidity'
(analytics/features/definitions/grid_liquidity.py, archiviert). Die Services
srv_grid_lines + srv_proximity (srv_grid_lines.py / srv_proximity.py) bleiben
die einzigen Service-Plugins dieses Indikators.
"""

import threading
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from db_service import TF_SECONDS_MAP
from chart.overlays.style_models import (
    LINE_STYLES,
    MARKER_SHAPES,
    LineStyle,
    MarkerStyle,
)
from .base_indicator import BaseIndicator
from analytics.features.feature_builder import PluginExecutor
from analytics.features.plugins.base_plugin import PluginContext
from analytics.engine.set_evaluator import ServiceSetEvaluator


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if value is None:
        return default
    return bool(value)


def _marker_shape(value: Any, default: str = "circle") -> str:
    """P16.03-Bugfix: Validiert einen Marker-Shape-Wert gegen MARKER_SHAPES
    (tolerant: ungueltige Werte fallen auf den Default zurueck)."""
    s = str(value or default)
    return s if s in MARKER_SHAPES else default


def _marker_size(value: Any, default: int = 6) -> int:
    """P16.03-Bugfix: Validiert/klammert eine Markergroesse auf 1..20 px."""
    try:
        return max(1, min(20, int(value)))
    except (TypeError, ValueError):
        return default


def _line_style(value: Any, default: str = "solid") -> str:
    """P16.03-Bugfix: Validiert einen Linienart-Wert gegen LINE_STYLES
    (tolerant: ungueltige Werte fallen auf den Default zurueck)."""
    s = str(value or default)
    return s if s in LINE_STYLES else default


def _line_width(value: Any, default: int = 1) -> int:
    """P16.03-Bugfix: Validiert/klammert eine Linienstaerke auf 1..10 px."""
    try:
        return max(1, min(10, int(value)))
    except (TypeError, ValueError):
        return default


def _f_in_window_around(minute_val: int, center: int, span: int) -> bool:
    """Native UTC-Zeitfenster-Logik (identisch zu grid.py / srv_proximity)."""
    lower = center - span
    upper = center + span
    if lower < 0:
        return minute_val >= (60 + lower) or minute_val <= upper
    elif upper > 59:
        return minute_val >= lower or minute_val <= (upper - 60)
    else:
        return lower <= minute_val <= upper


# ---------------------------------------------------------------------------
# Self-contained UI-Schema (Bugfix 04.08.2026): Single Source of Truth fürs
# Prop-Fenster. Die Werte entsprechen exakt dem archivierten Alt-Plugin
# 'grid_liquidity' (analytics/features/definitions/grid_liquidity.py) –
# Reihenfolge: Indi-Props (Sichtbarkeit, Farben) zuerst, darunter die
# Service-Props, expert-Felder am Ende. Der Indikator liefert damit
# parameter_schema/parameter_order direkt (plugin_id='ind_fixed_grid_proximity') und
# benötigt KEINEN PluginRegistry-Zugriff mehr.
# ---------------------------------------------------------------------------
_FIXED_GRID_PROXIMITY_SCHEMA: Dict[str, Dict[str, Any]] = {
    "grid_step": {"type": "float", "default": 0.50, "min": 0.01, "max": 100.0, "step": 0.05, "description": "Rasterabstand"},
    "proximity_threshold": {"type": "float", "default": 0.05, "min": 0.001, "max": 10.0, "step": 0.005, "description": "Toleranzschwelle"},
    "use_time_filter": {"type": "bool", "default": True, "description": "Time Filter aktiv (Zeitfenster um ganze/halbe Stunde)"},
    "time_window_mins": {"type": "int", "default": 5, "min": 0, "max": 30, "step": 1, "description": "Time Filter Minuten (0 oder 30 um ganze/halbe Stunde)"},
    "line_color": {"type": "color", "default": "#2196F3", "description": "Farbe Grid-Linien", "style_type": "line", "show_visibility": False},
    # Phase 16.06 (07.08.2026): Die Einzelfeld-Deklarationen line_style /
    # line_width wurden ENTFERNT - Linienart/-staerke werden ausschliesslich
    # ueber den LineStyle-Picker (Sibling-Keys, Konvention 'color' ->
    # 'style'/'width' in indicator_dialog) bedient und persistiert.
    # Current-Presets ohne diese Keys fallen in _build_style_objects auf die
    # Defaults zurueck (solid / 1 px). show_visibility=False: die interne
    # 'sichtbar'-Checkbox des Pickers entfaellt - Sichtbarkeit steuert der
    # separate Param show_lines.
    "circle_color_std": {"type": "color", "default": "#FFEB3B", "description": "Farbe Standard-Hit (im Zeitfenster)", "style_type": "marker", "show_visibility": False},
    "circle_color_active": {"type": "color", "default": "#E91E63", "description": "Farbe Hit in Aktivitätsfenster", "style_type": "marker", "show_visibility": False},
    # Phase 16.06 (07.08.2026): Die Einzelfeld-Deklarationen circle_shape_* /
    # circle_size_* wurden ENTFERNT - Marker-Form/-Groesse werden
    # ausschliesslich ueber den MarkerStyle-Picker (Sibling-Keys, Konvention
    # 'color' -> 'shape'/'size') bedient und persistiert. Current-Presets ohne
    # diese Keys fallen in _build_style_objects auf die Defaults zurueck
    # (circle / 6 px).
    "show_lines": {"type": "bool", "default": True, "description": "Grid-Linien anzeigen"},
    "show_circles": {"type": "bool", "default": True, "description": "Hits anzeigen"},
    "prox_level1": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 1"},
    "prox_level2": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 2"},
    "prox_level3": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 3"},
    "prox_level4": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 4"},
    "prox_level5": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 5"},
    "prox_level6": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 6"},
}

_FIXED_GRID_PROXIMITY_ORDER: List[str] = [
    # Reine Indi-Props (oberhalb der Trennlinie)
    "show_lines", "show_circles",
    "line_color", "circle_color_std", "circle_color_active",
    # Service-Props (Berechnung)
    "grid_step", "proximity_threshold",
    "use_time_filter", "time_window_mins",
    # Expert-Felder (Custom Levels, ausklappbar)
    "prox_level1", "prox_level2", "prox_level3",
    "prox_level4", "prox_level5", "prox_level6",
]


class FixedGridProximityIndicator(BaseIndicator):

    def __init__(self) -> None:
        super().__init__()
        self._symbol: Optional[str] = None
        self._timeframe: Optional[str] = None
        self._settings: Any = None
        self._executor: PluginExecutor = PluginExecutor()
        self._evaluator: ServiceSetEvaluator = ServiceSetEvaluator(self._executor)
        self._plugin_id: str = "ind_fixed_grid_proximity"

        # --- Thread-sicherer Cache (Phase 13 Schritt 6) ----------------------
        self._cache_lock = threading.Lock()
        self._cached_grid_lines: List[Dict[str, Any]] = []
        self._live_points: List[Dict[str, Any]] = []
        self._known_times: set = set()
        self._last_params: Dict[str, Any] = {}
        self._on_new_candle: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------ Basis
    @property
    def indicator_id(self) -> str:
        return "ind_fixed_grid_proximity"

    @property
    def display_name(self) -> str:
        return "Ind_FixedGridProximity"

    # --- Self-contained Plugin-Schnittstelle (Bugfix 04.08.2026) -------------
    # Der Indikator ist jetzt die eigene Single Source of Truth fürs Prop-
    # Fenster (parameter_schema/parameter_order/plugin_id). Damit erkennt
    # IndicatorDialog._get_plugin() den Indikator direkt als "Plugin" (Branch
    # 1) und baut die schema-basierte UI OHNE PluginRegistry-Zugriff auf –
    # das Alt-Plugin 'grid_liquidity' ist entfernt.
    @property
    def plugin_id(self) -> str:
        return "ind_fixed_grid_proximity"

    @property
    def parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        """UI-Schema (Indi-Props + Service-Props + Custom-Levels), exakt wie
        im archivierten Alt-Plugin 'grid_liquidity'."""
        return {k: dict(v) for k, v in _FIXED_GRID_PROXIMITY_SCHEMA.items()}

    @property
    def parameter_order(self) -> List[str]:
        """Darstellungs-Reihenfolge der Props im Prop-Fenster."""
        return list(_FIXED_GRID_PROXIMITY_ORDER)

    @property
    def base_parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        """Basis-Parameter (lookback) – identisch zur Plugin-Basisklasse,
        damit der Expert-Bereich des Prop-Fensters den lookback zeigt."""
        return {
            "lookback": {
                "type": "int", "default": 1000, "min": 100, "max": 100000,
                "step": 50, "description": "Lookback (Scan-Fenster)",
                "expert": True,
            },
        }

    def full_parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        """Vollständiges Schema: Basis-Parameter (lookback) + Indikator-Schema."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    @property
    def default_params(self) -> Dict[str, Any]:
        """Standard-Parameter aus dem self-contained Schema (inkl. lookback) –
        KEIN PluginRegistry-Zugriff mehr (Bugfix 04.08.2026)."""
        return {
            k: v["default"]
            for k, v in self.full_parameter_schema().items()
            if "default" in v
        }

    @property
    def service_plugin_ids(self) -> List[str]:
        """Die Service-Plugin-IDs, die dieser Indikator intern ausführt (Schritt 6):
        srv_grid_lines + srv_proximity. Der Alt-Service 'grid_liquidity'
        existiert nicht mehr (Bugfix 04.08.2026) – KEIN Service dieses
        Indikators."""
        return ["srv_grid_lines", "srv_proximity"]

    @property
    def param_options(self) -> Dict[str, List[Any]]:
        return {}

    @property
    def param_labels(self) -> Dict[str, str]:
        # Phase 16.06 (07.08.2026): Die Labels line_style/line_width/
        # circle_shape_*/circle_size_* wurden entfernt - diese Einzelfelder
        # existieren nicht mehr als Schema/Controls, sie werden ausschliesslich
        # ueber den StylePicker bedient (Sibling-Keys).
        return {
            "lookback": "Lookback (Scan-Fenster)",
            "grid_step": "Rasterabstand",
            "proximity_threshold": "Toleranz",
            "use_time_filter": "Time Filter aktiv",
            "time_window_mins": "Time Filter Minuten (0/30)",
            "line_color": "Linien-Farbe",
            "circle_color_std": "Std-Hit-Farbe (im Fenster)",
            "circle_color_active": "Aktiv-Hit-Farbe (ausserhalb)",
            "show_lines": "Linien anzeigen",
            "show_circles": "Circles anzeigen",
            "prox_level1": "Level 1",
            "prox_level2": "Level 2",
            "prox_level3": "Level 3",
            "prox_level4": "Level 4",
            "prox_level5": "Level 5",
            "prox_level6": "Level 6",
        }

    @property
    def param_layout(self) -> Optional[List[Any]]:
        return [
            ("Raster & Toleranz", ["grid_step", "proximity_threshold"]),
            ("Time Filter", ["use_time_filter", "time_window_mins"]),
            ("Farben", ["line_color", "circle_color_std", "circle_color_active"]),
            ("Anzeige", ["show_lines", "show_circles"]),
            ("Custom Levels 1-3", ["prox_level1", "prox_level2", "prox_level3"]),
            ("Custom Levels 4-6", ["prox_level4", "prox_level5", "prox_level6"]),
        ]

    # ------------------------------------------------------------ Kontext-API
    def set_context(self, symbol: str, timeframe: str) -> None:
        self._symbol = symbol
        self._timeframe = timeframe

    def set_settings(self, settings: Any) -> None:
        """Injiziert AppSettings (Kopie) – sonst lazy aus dem StateManager."""
        self._settings = settings

    def set_new_candle_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Debounced Refresh-Callback (chart_win.refresh_chart_data). Wird bei
        einem neuen Close genau EINMAL aufgerufen (Cache-Neuaufbau)."""
        self._on_new_candle = callback

    # ------------------------------------------------------------- Cache-API
    def _set_cached_lines(self, lines: List[Dict[str, Any]]) -> None:
        """Thread-sichere atomare Zuweisung: ersetzt die Liste als GANZES
        (neue Liste, niemals in-place-Mutation) unter Lock."""
        with self._cache_lock:
            self._cached_grid_lines = list(lines)

    def _get_cached_lines(self) -> List[Dict[str, Any]]:
        """Liefert eine flache Kopie der gecachten Linien (Lock-geschützt)."""
        with self._cache_lock:
            return list(self._cached_grid_lines)

    # ------------------------------------------------- P14-03: Lesepfad (additiv)
    def read_proximity_from_feature_store(
        self,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
        db_path: Optional[str] = None,
        feature_id: str = "srv_proximity",
    ) -> List[Dict[str, Any]]:
        """P14-03 (Live-Entkopplung A.1.3 / Schritt 3.2): PRIMÄRER
        DB-Lesepfad des Indikators – liest fertige Proximity-Hits aus dem
        feature_store (JSON-Feld feature_data, feature_id='srv_proximity', inkl.
        schema_version) beim Chart-Re-Render/Refresh OHNE synchrone
        Service-Pipeline (Invariante 10).

        P14-03-E (Schritt 4, generisch): `feature_id` ist parametrisiert
        (Standard 'srv_proximity'), damit spätere Indikator-Plugins denselben
        Lesepfad über die eigene feature_id nutzen können (Open/Closed).

        Der Indikator führt hier KEINE Berechnungen aus; er liest ausschließlich
        vorberechnete Daten aus DuckDB. Liefert die Hit-Kreise des Proximity-
        Service ({time, price, in_window}) oder [] bei fehlenden Daten/Fehlern –
        leere Ergebnisse sind der definierte Zustand (U15-A3: der frühere
        Pipeline-Fallback in calculate() wurde entfernt).

        U15-A2 (Farb-Semantik): Die gelieferten Kreise enthalten KEINE Farbe –
        der Aufrufer (calculate) wendet die circle_color_std/_active-Färbung
        additiv aus dem Indikator-Schema an (in_window + use_time_filter).

        Args:
            symbol: Symbol-Name
            timeframe: Timeframe
            limit: Maximale Anzahl Bars (Default 1000)
            db_path: Optionaler DB-Pfad (für Tests) – Default analytics.duckdb
            feature_id: Feature-ID im feature_store (Default 'srv_proximity')
        """
        if not symbol or not timeframe:
            return []
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent.parent.parent
                          / "data" / "analytics.duckdb")
        if limit is None:
            limit = 1000
        try:
            from db_service import DbPool
            con = DbPool.get(db_path)
            rows = con.execute("""
                SELECT EXTRACT('epoch' FROM bar_time)::BIGINT AS time_epoch,
                       feature_data
                FROM (
                    SELECT bar_time, feature_data
                    FROM feature_store
                    WHERE symbol = ? AND timeframe = ? AND feature_id = ?
                      AND feature_data IS NOT NULL
                    ORDER BY bar_time DESC
                    LIMIT ?
                )
                ORDER BY bar_time ASC
            """, [symbol, timeframe, feature_id, limit]).fetchall()
        except Exception as e:
            print(f"WARN [FixedGridProximityIndicator] feature_store-Lesepfad "
                  f"fehlgeschlagen: {e}")
            return []

        circles: List[Dict[str, Any]] = []
        for row in rows:
            time_sec = row[0]
            if time_sec is None or time_sec <= 0:
                continue
            data = row[1] or {}
            if isinstance(data, str):
                try:
                    import json as _json
                    data = _json.loads(data) or {}
                except (ValueError, TypeError):
                    data = {}
            if not data.get("is_hit"):
                continue
            # feature_data enthält levels_hit (Preise der getroffenen Levels)
            # – je Level ein Hit-Kreis (Farbe setzt der Aufrufer über das
            # in_window-Flag, wie bei der Live-Pipeline).
            in_window = bool(data.get("in_time_window"))
            for lvl in (data.get("levels_hit") or []):
                try:
                    circles.append({
                        "time": time_sec,
                        "price": float(lvl),
                        "in_window": in_window,
                        "priority": 10,
                    })
                except (TypeError, ValueError):
                    continue
        return circles

    # -------------------------------------------------------------- Berechnung
    def _get_app_settings(self) -> Any:
        if self._settings is not None:
            return self._settings
        try:
            from state_manager import StateManager
            return StateManager().get_app_settings()
        except Exception:
            return None

    @staticmethod
    def _extract_custom_levels(params: Dict[str, Any]) -> List[float]:
        """prox_level1..6 (nur > 0) ODER custom_levels (Liste/String)."""
        levels: List[float] = []
        for i in range(1, 7):
            v = params.get(f"prox_level{i}")
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0.0:
                levels.append(round(fv, 6))
        if levels:
            return levels
        raw = params.get("custom_levels")
        if isinstance(raw, (list, tuple)):
            return [round(float(x), 6) for x in raw if float(x) > 0.0]
        if isinstance(raw, str) and raw.strip():
            parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
            return [round(float(x), 6) for x in parts if float(x) > 0.0]
        return []

    def _build_set_definition(self, params: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        """Interne ServiceSetDefinition für den Historical-Run (Schritt 6):
        grid_1 → srv_grid_lines, prox_1 → srv_proximity (depends_on grid_1)."""
        lookback = int(params.get("lookback") or len(df))
        if lookback < 1:
            lookback = 1
        step_size = float(params.get("step_size", params.get("grid_step", 0.5)))
        steps_around = int(params.get("steps_around", 4))
        visit_pct = float(params.get("visit_pct", params.get("proximity_threshold", 0.05)))
        time_window_mins = int(params.get("time_window_mins", 5))
        use_time_filter = _as_bool(params.get("use_time_filter"), True)
        custom_levels = self._extract_custom_levels(params)

        return {
            "set_id": "ind_fixed_grid_proximity_internal",
            "display_name": "Ind_FixedGridProximity (intern)",
            "execution_order": ["grid_1", "prox_1"],
            "services": {
                "grid_1": {
                    "plugin_id": "srv_grid_lines",
                    "lookback": lookback,
                    "params": {
                        "step_size": step_size,
                        "steps_around": steps_around,
                        "custom_levels": custom_levels,
                    },
                },
                "prox_1": {
                    "plugin_id": "srv_proximity",
                    "lookback": lookback,
                    "depends_on": ["grid_1"],
                    "params": {
                        "visit_pct": visit_pct,
                        "time_window_mins": time_window_mins,
                        "use_time_filter": use_time_filter,
                    },
                },
            },
        }

    def _compute_known_times(self, df: pd.DataFrame) -> set:
        """Rundet alle Bar-Zeiten auf den Timeframe (gerundete Time) – dieselbe
        Erkennung wie chart_win (rounded_t nicht in _time_real_to_cont)."""
        t_sec = TF_SECONDS_MAP.get(str(self._timeframe or "").upper(), 60)
        out: set = set()
        for t in df["time"]:
            try:
                ti = int(t)
            except (TypeError, ValueError):
                continue
            out.add(ti - (ti % t_sec))
        return out

    # ------------------------------------------------- P16.01: Render-Payload
    def _build_style_objects(
        self, ui_params: Dict[str, Any]
    ) -> tuple:
        """P16.03 (Schritt 3): Baut die generischen Style-Vertraege aus den
        Indikator-UI-Params (P16.01-konform – die Services selbst haben seit
        P16.01 KEINE Style-UI-Params mehr, das komplette Render-Styling liegt
        ausschliesslich im Indikator).

        Abbildung der UI-Params auf die Style-Vertraege:
          * `grid_style`     (LineStyle):    show_lines / line_color
          * `std_marker`     (MarkerStyle):  show_circles / circle_color_std
          * `active_marker`  (MarkerStyle):  show_circles / circle_color_active

        width/style kommen seit dem P16.03-Bugfix (06.08.2026) aus den
        Geschwister-UI-Params (Konvention 'color' -> 'style'/'width'):
        line_style (choice, LINE_STYLES) und line_width (int 1..10).
        Ebenso shape/size der Marker aus circle_shape_* (choice,
        MARKER_SHAPES) und circle_size_* (int 1..20). Fehlen die Params
        (Current-Presets), fallen sie auf die P16.03-Defaults zurueck
        (LineStyle: width 1, style 'solid'; MarkerStyle: shape 'circle',
        size 6).

        Returns:
            (grid_style, std_marker, active_marker) – frische Instanzen.
        """
        grid_style = LineStyle(
            show=_as_bool(ui_params.get("show_lines"), True),
            color=str(ui_params.get("line_color") or "").strip(),
            width=_line_width(ui_params.get("line_width"), 1),
            style=_line_style(ui_params.get("line_style"), "solid"),
        )
        std_marker = MarkerStyle(
            show=_as_bool(ui_params.get("show_circles"), True),
            color=str(ui_params.get("circle_color_std") or "#FFEB3B"),
            shape=_marker_shape(ui_params.get("circle_shape_std"), "circle"),
            size=_marker_size(ui_params.get("circle_size_std"), 6),
        )
        active_marker = MarkerStyle(
            show=_as_bool(ui_params.get("show_circles"), True),
            color=str(ui_params.get("circle_color_active") or "#E91E63"),
            shape=_marker_shape(ui_params.get("circle_shape_active"), "circle"),
            size=_marker_size(ui_params.get("circle_size_active"), 6),
        )
        return grid_style, std_marker, active_marker

    def build_chart_render_payload(
        self,
        raw_features: Dict[str, Any],
        ui_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """P16.01 (Architektur-Entkopplung): Baut den chart_render_payload aus
        den ROHDATEN der Services – die Services selbst liefern KEINE Farben,
        Sichtbarkeits-Flags oder Zeichen-Objekte mehr (E1–E5).

        P16.03 (Schritt 3 + Bugfix 06.08.2026): Das Styling wird ueber die
        generischen Style-Vertraege abgebildet – `LineStyle` (Grid-Linien)
        bzw. `MarkerStyle` (Std-/Aktiv-Hit) werden aus den UI-Params gebaut
        (_build_style_objects) und via .to_js_dict() in den Payload uebersetzt
        (lowercase style-Werte, LWC-v5-Konvention; shape/size fuer die
        Marker). Die JS-Bridge uebernimmt shape/size aus dem Payload
        (renderGridCircles) – das style-Feld der Lines bleibt ignoriert
        (hardcoded LineStyle.Solid in renderGridLines).

        raw_features:
          * "grid_levels":        reine Level-Liste [{price}, ...] aus
                                  context.shared_state["grid_1"] (E2)
          * "proximity_records":  feature_store_records des Proximity-Service
                                  ({levels_hit, is_hit, in_time_window, ...},
                                  E3)
          * "status_info":        {"in_time_window", "active_hits"} aus
                                  metadata["statistics"] (E4)

        ui_params: Indikator-Parameter (show_lines / line_color /
        show_circles / circle_color_std / circle_color_active /
        use_time_filter).

        Liefert {"price_lines", "hit_circles", "status_info"} für den JS-Bridge
        (chart_win._serialize_and_render_grid) – Parität zum Alt-Grid.
        P16.05 (F1-Beschluss): Die Preislinien liegen unter dem Key
        "price_lines" (eigener Key für horizontale Grid-Preislinien); der
        "lines"-Key ist ausschließlich für Zeitreihen-LineSeries (Multi-MA)
        reserviert.
        * price_lines: {price, color, width, style:'solid', is_custom}
          (leere line_color = Paritäts-Styling des Alt-Grid:
          rgba(33,150,243,0.9) für Custom-Levels, rgba(33,150,243,0.5) für
          Normal-Levels; width/style seit P16.03-Bugfix aus line_width/
          line_style – User-Einstellung, Default 1/solid).
        * hit_circles: {time, price, in_window, color, shape, size, priority:10}
          circle_color_std/shape/size wenn in_window=True (bzw. Time-Filter
          inaktiv), circle_color_active/_shape/_size sonst (E1/E3).
        * status_info: 1:1 aus raw_features["status_info"] (E4).
        """
        lines: List[Dict[str, Any]] = []
        # P16.03: Grid-Linien-Style aus dem generischen Style-Vertrag
        # (LineStyle.to_js_dict -> lowercase style, LWC-v5-Konvention).
        grid_style, std_marker, active_marker = self._build_style_objects(ui_params)
        if grid_style.show:
            line_color = grid_style.color
            custom_levels = self._extract_custom_levels(ui_params)
            # P16.03-Bugfix: width/style aus dem LineStyle-Vertrag (User-
            # Einstellung im StylePickerWidget) - vorher wurde die width vom
            # Paritaets-Styling (custom=1/normal=3) ueberschrieben und der
            # style war immer 'solid'. Die color-Paritaet (leere line_color ->
            # custom/normal unterschiedliche Transparenz) bleibt bestehen.
            js_line = grid_style.to_js_dict()
            js_line_style = js_line["style"]
            js_line_width = js_line["width"]
            for lvl_item in (raw_features.get("grid_levels") or []):
                if not isinstance(lvl_item, dict):
                    continue
                try:
                    lvl = float(lvl_item.get("price"))
                except (TypeError, ValueError):
                    continue
                is_custom = any(
                    abs(lvl - c_lvl) < 0.0001 for c_lvl in custom_levels)
                if line_color:
                    color = line_color
                else:
                    # Paritäts-Styling: Custom-Levels kräftiger + dünner (★)
                    color = ("rgba(33, 150, 243, 0.9)" if is_custom
                             else "rgba(33, 150, 243, 0.5)")
                lines.append({
                    "price": lvl,
                    "color": color,
                    "width": js_line_width,
                    "style": js_line_style,
                    "is_custom": is_custom,
                })

        use_time_filter = _as_bool(ui_params.get("use_time_filter"), True)
        # P16.03-Bugfix: Hit-Marker-Styling aus den generischen Style-Vertraegen
        # (MarkerStyle.to_js_dict -> LWC-v5-kompatible color/shape/size).
        js_std = std_marker.to_js_dict()
        js_active = active_marker.to_js_dict()
        circle_std = js_std["color"]
        circle_active = js_active["color"]
        hit_circles: List[Dict[str, Any]] = []
        if std_marker.show and active_marker.show:
            for rec in (raw_features.get("proximity_records") or []):
                if not rec.get("is_hit"):
                    continue
                in_window = bool(rec.get("in_time_window"))
                is_active = bool(use_time_filter and not in_window)
                color = circle_active if is_active else circle_std
                shape = js_active["shape"] if is_active else js_std["shape"]
                size = js_active["size"] if is_active else js_std["size"]
                try:
                    bar_time = int(rec.get("bar_time"))
                except (TypeError, ValueError):
                    continue
                for lvl in (rec.get("levels_hit") or []):
                    try:
                        hit_circles.append({
                            "time": bar_time,
                            "price": float(lvl),
                            "in_window": in_window,
                            "color": color,
                            "shape": shape,
                            "size": size,
                            "priority": 10,
                        })
                    except (TypeError, ValueError):
                        continue

        status_info = raw_features.get("status_info") or {}
        return {
            "price_lines": lines,
            "hit_circles": hit_circles,
            "status_info": {
                "in_time_window": bool(
                    status_info.get("in_time_window", False)),
                "active_hits": list(status_info.get("active_hits") or []),
            },
        }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
        """Führt die Service-Pipeline (srv_grid_lines + srv_proximity) für den
        Historical-Run aus, cached die Linien thread-sicher und liefert den
        Render-Payload (Parität zu grid.py).

        Phase 16 (P16.01, Architektur-Entkopplung): Der Render-Payload wird
        AUSSCHLIESSLICH von build_chart_render_payload() aus den ROHDATEN der
        Services gebaut (shared_state["grid_1"]-Levels + feature_store_records
        + metadata["statistics"]) – die Services selbst liefern keine Farben
        oder Zeichen-Objekte mehr.

        Invariante 10 (Chart-Entkopplung, Phase 15 U15-A2/A3) – Lese-Kette:
          1. Proximity-Hit-Circles werden PRIMÄR aus dem feature_store
             gelesen (read_proximity_from_feature_store) – der Chart führt
             KEINE Proximity-Berechnung aus, er liest vorberechnete Daten
             aus DuckDB. Ist der Store leer (noch kein Batch-Lauf
             geschrieben), greift der definierte P16.01-Fallback auf die aus
             den Rohdaten gebauten Circles (build_chart_render_payload).
          Die Grid-LINIEN (Live-Tick-Cache) kommen unabhängig davon immer
          aus der Pipeline (GridLinesService) – sie sind kein DB-Output.
        """
        empty_result: Dict[str, Any] = {
            "price_lines": [],
            "hit_circles": [],
            "status_info": {"in_time_window": False, "active_hits": []},
        }
        if df is None or df.empty:
            return empty_result

        try:
            p = dict(params or {})
            self._last_params = dict(p)

            context = PluginContext(
                symbol=self._symbol or "",
                timeframe=self._timeframe or "",
                mode="chart",
                settings=self._get_app_settings(),
            )
            definition = self._build_set_definition(p, df)
            results = self._evaluator.execute_set(definition, df, context)

            # --- P16.01: Render-Payload aus ROHDATEN bauen ------------------
            # grid_levels = reine Level-Liste aus shared_state["grid_1"] (E2),
            # proximity_records = feature_store_records aus results["prox_1"]
            # (E3), status_info = metadata["statistics"] (E4). Der Indikator
            # (build_chart_render_payload) übernimmt das komplette Styling –
            # die Services liefern KEINEN chart_render_payload mehr (E5).
            prox_fsp = (results.get("prox_1") or {}).get(
                "feature_store_payload") or {}
            grid_levels = context.shared_state.get("grid_1") or []
            raw_features: Dict[str, Any] = {
                "grid_levels": (
                    grid_levels if isinstance(grid_levels, list) else []
                ),
                "proximity_records": prox_fsp.get("records") or [],
                "status_info": (prox_fsp.get("metadata") or {}).get(
                    "statistics") or {},
            }
            render_payload = self.build_chart_render_payload(raw_features, p)
            lines = render_payload.get("price_lines") or []

            # U15-A2 (Farb-Semantik) mit Bugfix 04.08.2026 (Circles wieder
            # sichtbar): PRIMÄR werden die Proximity-Hits aus dem feature_store
            # gelesen (read_proximity_from_feature_store – U15-A3-Lesepfad).
            # Ist der Store leer (noch kein Batch-Lauf mit aktivem
            # proximity-Preset geschrieben), greift der DEFINIERTE FALLBACK
            # auf die aus den Rohdaten gebauten Circles
            # (render_payload.hit_circles, P16.01) – der Chart führt die
            # Pipeline intern ohnehin aus und verwirft die Treffer sonst
            # ungenutzt. Beide Pfade liefern time/price/in_window; die Farbe
            # wird additiv aus dem Indikator-Schema angewendet:
            #   in_window + use_time_filter → circle_color_std, sonst _active.
            cached_circles = self.read_proximity_from_feature_store(
                self._symbol or "", self._timeframe or ""
            )
            circle_std = str(p.get("circle_color_std") or "#FFEB3B")
            circle_active = str(p.get("circle_color_active") or "#E91E63")
            shape_std = _marker_shape(p.get("circle_shape_std"), "circle")
            shape_active = _marker_shape(p.get("circle_shape_active"), "circle")
            size_std = _marker_size(p.get("circle_size_std"), 6)
            size_active = _marker_size(p.get("circle_size_active"), 6)
            use_time_filter = _as_bool(p.get("use_time_filter"), True)

            def _colorize(c: Dict[str, Any]) -> Dict[str, Any]:
                # Bugfix 05.08.2026: priority=10 ergänzen – der Feature-Store-
                # Lesepfad (read_proximity_from_feature_store) und die Live-
                # Punkte (update_live_candle) setzen priority=10. Der P16.01-
                # Fallback (render_payload.hit_circles aus
                # build_chart_render_payload) setzt priority=10 bereits selbst.
                # Durch das additive Setzen sind BEIDE Pfade konsistent
                # (ChartCircle-Vertrag, base_plugin.py).
                # P16.03-Bugfix: Auch shape/size additiv setzen – der
                # Feature-Store-Lesepfad liefert die Kreise ohne Form/Groesse.
                is_active = bool(use_time_filter and not bool(c.get("in_window", True)))
                return dict(
                    c,
                    color=(circle_active if is_active else circle_std),
                    shape=(shape_active if is_active else shape_std),
                    size=(size_active if is_active else size_std),
                    priority=10,
                )

            if cached_circles:
                circles = [_colorize(c) for c in cached_circles]
            else:
                circles = render_payload.get("hit_circles") or []
            status = dict(render_payload.get("status_info")
                          or empty_result["status_info"])

            self._set_cached_lines(lines)
            self._known_times = self._compute_known_times(df)
            self._live_points = []

            return {
                "price_lines": lines,
                "hit_circles": circles,
                "status_info": status,
            }
        except Exception as e:
            print(f"⚠️ [FixedGridProximityIndicator] Service-Pipeline fehlgeschlagen: {e}")
            return empty_result

    def update_live_candle(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Live-Tick-Verarbeitung OHNE Pipeline (Phase 13 Schritt 6):
        berechnet ausschließlich die mathematische Differenz zwischen dem
        Live-Tick und self._cached_grid_lines (prozentuale visit%-Semantik),
        um Live-Punkte zu setzen. Ein neuer Close wird über self._known_times
        erkannt und löst genau EINEN debounced Refresh aus (Cache-Neuaufbau),
        nicht bei jedem Tick.

        Args:
            candle: Live-Candle/Quote mit 'time' (epoch-Sekunden, auf den
                    Timeframe gerundet) und 'close' (bzw. 'price').

        Returns:
            Liste der Live-Punkte [{time, price, color}, ...] – zusätzlich in
            self._live_points (atomare Zuweisung).
        """
        if not candle:
            return []
        cached_lines = self._get_cached_lines()
        if not cached_lines:
            return []

        try:
            ts = int(candle.get("time", 0))
            if ts <= 0:
                return []
        except (TypeError, ValueError):
            return []

        t_sec = TF_SECONDS_MAP.get(str(self._timeframe or "").upper(), 60)
        rounded = ts - (ts % t_sec)

        # Neue Candle → NUR ein debounced Cache-Neuaufbau (nicht jeder Tick).
        if rounded not in self._known_times:
            self._known_times.add(rounded)
            if self._on_new_candle is not None:
                try:
                    self._on_new_candle()
                except Exception as e:
                    print(f"⚠️ [FixedGridProximityIndicator] Cache-Neuaufbau fehlgeschlagen: {e}")

        try:
            price = float(candle.get("close", candle.get("price", 0.0)))
        except (TypeError, ValueError):
            return []

        p = self._last_params or {}
        visit_pct = float(p.get("visit_pct", p.get("proximity_threshold", 0.05)))
        use_time_filter = _as_bool(p.get("use_time_filter"), True)
        time_window_mins = int(p.get("time_window_mins", 5))
        circle_std = str(p.get("circle_color_std") or "#FFEB3B")
        circle_active = str(p.get("circle_color_active") or "#E91E63")
        shape_std = _marker_shape(p.get("circle_shape_std"), "circle")
        shape_active = _marker_shape(p.get("circle_shape_active"), "circle")
        size_std = _marker_size(p.get("circle_size_std"), 6)
        size_active = _marker_size(p.get("circle_size_active"), 6)

        row_m = datetime.fromtimestamp(rounded, tz=dt_timezone.utc).minute
        row_in_time = (
            _f_in_window_around(row_m, 0, time_window_mins)
            or _f_in_window_around(row_m, 30, time_window_mins)
        )
        is_active = bool(use_time_filter and not row_in_time)
        color = circle_active if is_active else circle_std
        shape = shape_active if is_active else shape_std
        size = size_active if is_active else size_std

        points: List[Dict[str, Any]] = []
        for line in cached_lines:
            lvl = line.get("price")
            if lvl is None:
                continue
            try:
                lvl = float(lvl)
            except (TypeError, ValueError):
                continue
            visit_min = lvl * (1.0 - visit_pct / 100.0)
            visit_max = lvl * (1.0 + visit_pct / 100.0)
            if visit_min <= price <= visit_max:
                points.append({"time": rounded, "price": lvl, "color": color,
                               "shape": shape, "size": size, "priority": 10})

        self._live_points = list(points)  # atomare Zuweisung
        return points

    # -------------------------------------------------- P14-03-E: Live-Overlays
    def get_live_overlays(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """P14-03-E (Open/Closed-Hook): Liefert die Live-Overlays des Plugins als
        generische Overlay-Items {kind='circle', layer=indicator_id, time, price,
        color, priority}. Basis ist update_live_candle() (mathematische Differenz
        Live-Tick vs. gecachte Liq-Lines) – keine Pipeline pro Tick."""
        pts = self.update_live_candle(candle)
        return [dict(p, kind="circle", layer=self.indicator_id) for p in pts]

    def remember_live_time(self, ts: int) -> None:
        """P14-03-E: Merkt eine offene Live-Bar-Zeit im _known_times-Set, damit der
        New-Candle-Callback über den Refresh hinweg NICHT erneut feuert (Flacker-Fix)."""
        try:
            self._known_times.add(int(ts))
        except (TypeError, ValueError):
            pass

```

--------------------------------------------------

### DATEI: chart/indicators/ind_moving_averages.py
```py
# chart/indicators/ind_moving_averages.py
"""
Phase 16.05 – Multi-MA-Indikator (8x Moving Averages)
======================================================
Naming Convention 16.08.01: Dateiname = indicator_id `ind_moving_averages`.

Selbst-contained Indikator (BaseIndicator) für den Chart: zeichnet bis zu
8 Moving Averages als LWC-v5-LineSeries über die GENERISCHE Render-Pipeline
(Prework, 16.05) – KEIN Indikator-spezifischer JS-/chart_win-Branch mehr.

  * Nutzt die `MATemplateEngine` aus Phase 16.04
    (chart/indicators/utils/ma_template.py) für die Berechnung (12 MA-Typen,
    vektorisiert), Farb-Serien (dual_color-Semantik) und den LWC-v5-Payload.
  * `calculate()` liefert den generischen Render-Payload
    `{"lines": [{"id": "ma1".."ma8", "data": [{time, value, color}],
                 "width", "style", "title"}, ...]}` (Entscheidung D6,
    P-C5: `lines` statt `maLines` – der `lines`-Key ist ausschließlich für
    Zeitreihen-LineSeries reserviert, F1-Beschluss).
  * Das Parameter-Schema (50 Parameter: MA1 8 Keys, MA2..8 je 6 Keys) wird
    PROGRAMMATISCH in einer Schleife `for x in range(1, 9)` erzeugt
    (Ergänzung C3), nicht manuell ausgeschrieben. `maX_smoothing` (Vertrag C,
    16.05): int-Glättungslänge (min 0, max 500, Default 10 laut Konzept) –
    der EMA-Doppelpass läuft über `MATemplateEngine.calculate_ma(..., 
    smoothing=smoothing)`. `smoothing <= 1` = keine Glättung (die frühere
    Option " - no Smoothing" sowie `maX_smooth_type` sind damit überholt
    und ersatzlos entfernt).
  * Defaults (Entscheidung D7): MA1 `EHMA/4/alpha 2.0/dual_color=False`,
    MA2..8 `EMA/10*X/alpha 2.0`, alle `show=False` außer MA1.
  * Kontrastfarben (Entscheidung D4): MA1 teal #26A69A (Führungslinie),
    MA2 #2962FF, MA3 #FF6D00, MA4 #AB47BC, MA5 #FDD835, MA6 #FF5252,
    MA7 #00E5FF, MA8 #B0BEC5.
  * VWMA (P-D4/F3): nutzt `df["tick_volume"]` aus `fetch_historical_candles`
    (None/NaN -> 0 normalisiert). Fehlt die Spalte oder ist das Volumen
    Null, greift der Engine-interne E5-Fallback (SMA).

Keine Analytics-/Feature-Store-Schreibzugriffe (reine Darstellung, P16.01).
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from .base_indicator import BaseIndicator
from .utils.ma_template import MATemplateEngine, MA_TYPES, resolve_bull_color
from chart.overlays.style_models import LINE_STYLES

# ---------------------------------------------------------------------------
# Konstanten & Defaults (Entscheidungen D4/D7)
# ---------------------------------------------------------------------------
_INDICATOR_ID: str = "ind_moving_averages"
_DISPLAY_NAME: str = "Multi Moving Average (8x)"

# Kontrastfarben MA1..MA8 (D4) – MA1 teal bleibt Führungslinie.
_MA_COLORS: Dict[int, str] = {
    1: "#26A69A",   # teal (Führung)
    2: "#2962FF",   # Blau
    3: "#FF6D00",   # Orange
    4: "#AB47BC",   # Violett
    5: "#FDD835",   # Gelb
    6: "#FF5252",   # Rot
    7: "#00E5FF",   # Cyan
    8: "#B0BEC5",   # Blaugrau
}
_MA1_BEAR_COLOR: str = "#EF5350"

# Strichstärke: MA1 (Führungslinie) kräftiger, MA2..8 dünner.
_MA1_WIDTH: int = 2
_MA_WIDTH: int = 1
_LINE_STYLE: str = "solid"

# Glättung (Vertrag C, 16.05): Default 10 laut Konzept (16.04 Schritt 3).
# smoothing <= 1 = keine Glättung (Bypass in MATemplateEngine.calculate_ma).
_MA_SMOOTHING_DEFAULT: int = 10


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if value is None:
        return default
    return bool(value)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _line_style(value: Any, default: str = "solid") -> str:
    """Phase 16.06 (07.08.2026): Validiert eine Linienart gegen LINE_STYLES
    (tolerant: ungueltige Werte fallen auf den Default zurueck)."""
    s = str(value or default)
    return s if s in LINE_STYLES else default


class MultiMovingAverageIndicator(BaseIndicator):
    """Multi-MA-Indikator (8 MAs) – generische `lines`-LineSeries via
    MATemplateEngine (Phase 16.04)."""

    def __init__(self) -> None:
        super().__init__()
        self._symbol: Optional[str] = None
        self._timeframe: Optional[str] = None
        self._settings: Any = None
        self._plugin_id: str = _INDICATOR_ID
        # Phase 16.07 (Two-Tier, D6): Datenfenster-Grösse für die Tier-2-
        # Berechnung (Buffergrösse M + Warmup). None = Fallback auf
        # chart_candle_limit (Bestandsverhalten / Tests, z. B. P16.05 M4).
        self._data_window_size: Optional[int] = None

    # ------------------------------------------------------------- Identität
    @property
    def indicator_id(self) -> str:
        return _INDICATOR_ID

    @property
    def display_name(self) -> str:
        return _DISPLAY_NAME

    @property
    def plugin_id(self) -> str:
        """Selbst-contained Plugin-Schnittstelle (Branch 1 in
        indicator_dialog._get_plugin: parameter_schema + plugin_id)."""
        return _INDICATOR_ID

    @property
    def service_plugin_ids(self) -> List[str]:
        """Keine Services – reiner Darstellungs-Indikator."""
        return []

    # ----------------------------------------------------- Parameter-Schema
    @staticmethod
    def _build_schema() -> Dict[str, Dict[str, Any]]:
        """Programmatische Schema-Erzeugung (Ergänzung C3): 8 MAs, 50 Keys.

        MA1 (Führung, mit DualColor): show_ma1, ma1_type, ma1_period,
        ma1_smoothing, ma1_alpha, ma1_dual_color, ma1_bull_color,
        ma1_bear_color.
        MA2..8 (Standard): show_maX, maX_type, maX_period,
        maX_smoothing, maX_alpha, maX_color (kein dual_color/bear_color).
        """
        schema: Dict[str, Dict[str, Any]] = {}
        for x in range(1, 9):
            prefix = f"ma{x}"
            schema[f"show_{prefix}"] = {
                "type": "bool",
                "default": (x == 1),  # D7: nur MA1 sichtbar
                "description": f"MA {x} anzeigen",
            }
            schema[f"{prefix}_type"] = {
                "type": "choice",
                "options": list(MA_TYPES),
                "default": ("EHMA" if x == 1 else "EMA"),  # D7
                "description": f"MA {x} Typ",
            }
            schema[f"{prefix}_period"] = {
                "type": "int",
                "default": (4 if x == 1 else 10 * x),  # D7
                "min": 1,
                "max": 500,
                "step": 1,
                "description": f"MA {x} Periode",
            }
            schema[f"{prefix}_smoothing"] = {
                "type": "int",
                # Vertrag C (16.05): int-Glättungslänge, EMA-Doppelpass in der
                # Engine (MATemplateEngine.calculate_ma, smoothing=...).
                # smoothing <= 1 = keine Glättung.
                "default": _MA_SMOOTHING_DEFAULT,
                "min": 0,
                "max": 500,
                "step": 1,
                "description": f"MA {x} Glättung (zweiter EMA-Pass über die MA-Serie; <= 1 = keine Glättung)",
            }
            schema[f"{prefix}_alpha"] = {
                "type": "float",
                "default": 2.0,
                "min": 0.1,
                "max": 10.0,
                "step": 0.1,
                "description": f"MA {x} Decay-Faktor (Alpha-MAs)",
            }
            if x == 1:
                # MA1: NUR DualColor-Schalter + bull/bear (Spezial-Führung).
                schema["ma1_dual_color"] = {
                    "type": "bool",
                    "default": False,  # D7
                    "description": "MA 1 Auf/Ab-Färbung",
                }
                schema["ma1_bull_color"] = {
                    "type": "color",
                    "default": _MA_COLORS[1],
                    "description": "MA 1 Farbe steigend",
                    "style_type": "line",
                    # Phase 16.06 (07.08.2026): VOLLER LineStyle-Picker
                    # (Farbe + Breite + Linienart) statt color_only-Farbwaehler.
                    # Breite/Art der bull-Farbe gelten fuer die gesamte MA1-
                    # Linie (auch bear-Segmente). Die Sichtbarkeit steuert
                    # weiterhin show_ma1 (daher show_visibility=False -> keine
                    # doppelte 'sichtbar'-Checkbox im Dialog).
                    "show_visibility": False,
                }
                # Phase 16.06 (07.08.2026): Sibling-Defaults des MA1-LineStyle-
                # Pickers (Konvention 'color' -> 'style'/'width' in
                # indicator_dialog). NICHT in parameter_order -> keine eigenen
                # Controls. Sie liefern die Default-Params (Breite 2 / solid),
                # damit der Picker und der Render konsistent initialisieren.
                schema["ma1_bull_width"] = {
                    "type": "int", "default": _MA1_WIDTH, "min": 1, "max": 10,
                    "step": 1, "description": "MA 1 Linienstärke (px)",
                }
                schema["ma1_bull_style"] = {
                    "type": "choice", "options": list(LINE_STYLES),
                    "default": _LINE_STYLE, "description": "MA 1 Linienart",
                }
                schema["ma1_bear_color"] = {
                    "type": "color",
                    "default": _MA1_BEAR_COLOR,
                    "description": "MA 1 Farbe fallend (dual_color)",
                    "style_type": "line",
                    # Nur Farbe (color_only): Breite/Art der MA1-Linie steuert
                    # der bull-Picker (ma1_bull_style/ma1_bull_width).
                    "color_only": True,
                }
            else:
                # MA2..8: einfarbig (kein dual_color/bear_color). Voller
                # LineStyle-Picker (Phase 16.06) - Farbe/Breite/Linienart ueber
                # die Sibling-Keys maX_width/maX_style (NICHT in parameter_order
                # -> keine eigenen Controls, der Picker bedient sie direkt).
                schema[f"{prefix}_color"] = {
                    "type": "color",
                    "default": _MA_COLORS[x],
                    "description": f"MA {x} Farbe",
                    "style_type": "line",
                    "show_visibility": False,
                }
                schema[f"{prefix}_width"] = {
                    "type": "int", "default": _MA_WIDTH, "min": 1, "max": 10,
                    "step": 1, "description": f"MA {x} Linienstärke (px)",
                }
                schema[f"{prefix}_style"] = {
                    "type": "choice", "options": list(LINE_STYLES),
                    "default": _LINE_STYLE, "description": f"MA {x} Linienart",
                }
        return schema

    @property
    def parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self._build_schema().items()}

    @property
    def parameter_order(self) -> List[str]:
        """Darstellungs-Reihenfolge: MA1-Gruppe, dann MA2..8."""
        order: List[str] = []
        for x in range(1, 9):
            order.append(f"show_ma{x}")
            order.append(f"ma{x}_type")
            order.append(f"ma{x}_period")
            order.append(f"ma{x}_smoothing")
            order.append(f"ma{x}_alpha")
            if x == 1:
                order.extend(["ma1_dual_color", "ma1_bull_color", "ma1_bear_color"])
            else:
                order.append(f"ma{x}_color")
        return order

    @property
    def base_parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        """Kein lookback nötig – reiner Darstellungs-Indikator über alle
        Candles des Charts (keine Service-Pipeline)."""
        return {}

    def full_parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            k: v["default"]
            for k, v in self.full_parameter_schema().items()
            if "default" in v
        }

    @property
    def param_options(self) -> Dict[str, List[Any]]:
        return {}

    @property
    def param_labels(self) -> Dict[str, str]:
        labels: Dict[str, str] = {}
        for x in range(1, 9):
            labels[f"show_ma{x}"] = f"MA {x} anzeigen"
            labels[f"ma{x}_type"] = f"MA {x} Typ"
            labels[f"ma{x}_period"] = f"MA {x} Periode"
            # Vertrag C (16.05): maX_smoothing mit Label 'Smooth'
            # (Anwenderanforderung).
            labels[f"ma{x}_smoothing"] = f"MA {x} Smooth"
            labels[f"ma{x}_alpha"] = f"MA {x} Decay-Faktor"
            if x == 1:
                labels["ma1_dual_color"] = "MA 1 Auf/Ab-Färbung"
                labels["ma1_bull_color"] = "MA 1 Farbe steigend"
                labels["ma1_bear_color"] = "MA 1 Farbe fallend"
            else:
                labels[f"ma{x}_color"] = f"MA {x} Farbe"
        return labels

    @property
    def param_layout(self) -> Optional[List[Any]]:
        """Gruppen: 'MA 1 (Führung)' + 'MA 2'..'MA 8' (Ergänzung C3)."""
        layout: List[Any] = []
        for x in range(1, 9):
            keys = [
                f"show_ma{x}", f"ma{x}_type", f"ma{x}_period",
                f"ma{x}_smoothing", f"ma{x}_alpha",
            ]
            if x == 1:
                keys.extend(["ma1_dual_color", "ma1_bull_color", "ma1_bear_color"])
                title = "MA 1 (Führung)"
            else:
                keys.append(f"ma{x}_color")
                title = f"MA {x}"
            layout.append((title, keys))
        return layout

    # ------------------------------------------------------------- Kontext
    def set_context(self, symbol: str, timeframe: str) -> None:
        self._symbol = symbol
        self._timeframe = timeframe

    def set_settings(self, settings: Any) -> None:
        """Injiziert AppSettings (Kopie) – sonst lazy aus dem StateManager."""
        self._settings = settings

    def set_data_window_size(self, n: Optional[int]) -> None:
        """Phase 16.07 (D6): Setzt die Datenfenster-Grösse für die Tier-2-
        Berechnung (Buffergrösse M + Warmup-Vorlauf, verworfen).

        Der ChartWindow ruft diese Methode nach jedem Buffer-Load/Merge auf,
        damit die MA-Berechnung über den VOLLEN Tier-2-Puffer läuft (D5:
        vollständige vektorisierte Neuberechnung auf M) statt über den alten
        chart_candle_limit-Zuschnitt (3000). None = Fallback auf
        chart_candle_limit (Bestandsverhalten, Tests).
        """
        self._data_window_size = int(n) if n else None

    def _get_app_settings(self) -> Any:
        if self._settings is not None:
            return self._settings
        try:
            from state_manager import StateManager
            return StateManager().get_app_settings()
        except Exception:
            return None

    def _get_candle_limit(self) -> int:
        """Datenfenster-Limit für die Berechnung.

        Phase 16.07 (D6): Wenn `set_data_window_size()` gesetzt wurde
        (Tier-2-Buffergrösse M + Warmup), wird DIESES Limit verwendet –
        die MA-Berechnung läuft dann über den vollen Puffer (D5).
        Sonst Fallback auf chart_candle_limit (Default 3000,
        Bestandsverhalten / Tests, z. B. P16.05 M4).
        """
        if getattr(self, "_data_window_size", None):
            return max(int(self._data_window_size), 1)
        try:
            settings = self._get_app_settings()
            limit = int(getattr(settings, "chart_candle_limit", 3000))
            return max(limit, 1)
        except Exception:
            return 3000

    # ------------------------------------------------------------ Berechnung
    def build_chart_render_payload(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
    ) -> Dict[str, List[Any]]:
        """Baut den generischen Render-Payload (alle aktiven MAs).

        Args:
            df: OHLCV-DataFrame mit Spalten time/open/high/low/close (und
                optional tick_volume für VWMA, P-D4/F3) – reale
                Wanduhr-Epochs. Wird auf AppSettings.chart_candle_limit
                zugeschnitten (crop_dataframe).
            params: Indikator-Parameter (show_maX / maX_type / maX_period /
                maX_smoothing (Vertrag C: EMA-Doppelpass in der Engine,
                smoothing <= 1 = keine Glättung) / maX_alpha /
                ma1_dual_color / ma1_bull_color / ma1_bear_color /
                maX_color).

        Returns:
            {"lines": [{id, data, width, style, title}, ...]} – data ist
            direkt LWC-v5-setData-Input ([{time, value, color}] mit
            Pro-Punkt-color für dual_color-MA1, P16.04 build_chart_payload).
            Zeiten sind reale Wanduhr-Epochs; das Mapping real→kontinuierlich
            übernimmt chart_win._collect_render_payload generisch
            (Ergänzung C1).
        """
        lines: List[Dict[str, Any]] = []
        if df is None or df.empty:
            return {"lines": lines}

        # Daten-Zuschnitt (Ergänzung C3 / Spezifikation Punkt 2.1).
        df_crop = MATemplateEngine.crop_dataframe(df, self._get_candle_limit())
        if df_crop is None or df_crop.empty:
            return {"lines": lines}
        if "close" not in df_crop.columns:
            return {"lines": lines}

        close: pd.Series = df_crop["close"]
        volume: Optional[pd.Series] = None
        if "tick_volume" in df_crop.columns:
            volume = df_crop["tick_volume"]

        for x in range(1, 9):
            prefix = f"ma{x}"
            if not _as_bool(params.get(f"show_{prefix}"), x == 1):
                continue
            ma_type = str(params.get(f"{prefix}_type") or ("EHMA" if x == 1 else "EMA"))
            period = _as_int(params.get(f"{prefix}_period"), 4 if x == 1 else 10 * x)
            alpha = _as_float(params.get(f"{prefix}_alpha"), 2.0)
            smoothing = _as_int(
                params.get(f"{prefix}_smoothing"), _MA_SMOOTHING_DEFAULT
            )

            # Berechnung + optionale Alpha-EMA-Glättung (Vertrag C, 16.05):
            # der EMA-Doppelpass läuft in der Engine (smoothing=...), KEIN
            # Inline-Zweitpass mehr. smoothing <= 1 = keine Glättung.
            ma_series = MATemplateEngine.calculate_ma(
                close, ma_type, period, alpha_factor=alpha, volume=volume,
                smoothing=smoothing,
            )
            smoothing_active = smoothing > 1

            if x == 1:
                # MA1: dual_color-Semantik (E6) – bull/bear aus den Params.
                dual_color = _as_bool(params.get("ma1_dual_color"), False)
                bull_color = resolve_bull_color(
                    dual_color, params.get("ma1_bull_color"),
                    default=_MA_COLORS[1],
                )
                bear_color = str(params.get("ma1_bear_color") or _MA1_BEAR_COLOR)
                colors = MATemplateEngine.build_color_series(
                    ma_series, dual_color, bull_color, bear_color
                )
                # Phase 16.06 (07.08.2026): Breite/Linienart aus dem
                # LineStyle-Picker (Sibling-Keys ma1_bull_style/ma1_bull_width,
                # vom StylePickerWidget an ma1_bull_color gebunden) - Fallback
                # auf die Konstanten (Current-Presets ohne Sibling-Keys).
                width = _as_int(params.get("ma1_bull_width"), _MA1_WIDTH)
                line_style = _line_style(params.get("ma1_bull_style"), _LINE_STYLE)
                title = f"MA1 {str(ma_type).upper()} {period}"
            else:
                # MA2..8: einfarbige Farbliste (maX_color).
                color = str(params.get(f"{prefix}_color") or _MA_COLORS[x])
                n = len(ma_series)
                colors = [color] * n
                # Phase 16.06 (07.08.2026): Breite/Linienart aus dem
                # LineStyle-Picker (Sibling-Keys maX_style/maX_width) -
                # Fallback auf die Konstanten.
                width = _as_int(params.get(f"{prefix}_width"), _MA_WIDTH)
                line_style = _line_style(params.get(f"{prefix}_style"), _LINE_STYLE)
                title = f"MA{x} {str(ma_type).upper()} {period}"

            # Aktive Glättung im Linien-Titel sichtbar machen (Chart-Legende).
            # Vertrag C: nur die Länge, kein Typ mehr (' | S 10').
            if smoothing_active:
                title += f" | S {smoothing}"

            data = MATemplateEngine.build_chart_payload(
                df_crop["time"], ma_series, colors
            )
            lines.append({
                "id": prefix,
                "data": data,
                "width": width,
                "style": line_style,
                "title": title,
            })
        return {"lines": lines}

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
        """Berechnet alle aktiven MAs und liefert den generischen
        Render-Payload {"lines": [...]} (D6/P-C5)."""
        if df is None or df.empty:
            return {"lines": []}
        return self.build_chart_render_payload(df, params)

```

--------------------------------------------------

### DATEI: chart/indicators/ind_peak.py
```py
# chart/indicators/ind_peak.py (Teil 1: Live-State-Machine)
from collections import deque
import numpy as np
from datetime import datetime
from typing import List, Optional, Tuple

from analytics.engine.peak_models import (
    GrabberResultRecord,
    GrabberState,
    PeakConfig,
    PeakGrabberConfig,
    SignalDirection,
)


class PeakFinderLive:
    """Live-Peak-Tracker mit Rolling-Window (viewback_bars).

    22.01b (User-Anweisung 4a): Paritaet zum Batch-Service. cur_high/
    cur_low sind die Extrema des gleitenden Fensters (letzte viewback_bars
    Bars). update_scalar() meldet is_new_h/is_new_l genau dann, wenn sich
    das Fenster-Extremum aendert (neuer Peak ODER Expiry des alten
    Extremums) - der SL-Punkt wandert also dem Kurs entlang. Die
    Richtungs-Flags h_dir/l_dir (+1/-1) unterscheiden beides, damit der
    Grabber Expiry-Events unterdruecken kann (22.01b/4b Grabber-Rework).
    """

    def __init__(self, cfg: PeakConfig) -> None:
        self.cfg = cfg
        self._win_h: "deque" = deque()  # (bar_idx, high), vorn = Maximum
        self._win_l: "deque" = deque()  # (bar_idx, low),  vorn = Minimum
        self.cur_high_price: float = np.nan
        self.cur_high_idx: int = -1
        self.cur_high_sl: float = np.nan
        self.cur_low_price: float = np.nan
        self.cur_low_idx: int = -1
        self.cur_low_sl: float = np.nan

    def _viewback(self) -> int:
        return max(1, int(getattr(self.cfg, "viewback_bars", 3) or 3))

    def reset(self) -> None:
        self._win_h.clear()
        self._win_l.clear()
        self.cur_high_price = np.nan
        self.cur_high_idx = -1
        self.cur_high_sl = np.nan
        self.cur_low_price = np.nan
        self.cur_low_idx = -1
        self.cur_low_sl = np.nan

    def seed_window(self, entries) -> None:
        """B4 (22.01b): befuellt das Fenster aus dem Batch-Window-Tail
        ([(bar_idx, high, low), ...]) - Paritaet Batch -> Live."""
        self._win_h.clear()
        self._win_l.clear()
        for (idx, h, l) in (entries or []):
            idx = int(idx)
            h = float(h)
            l = float(l)
            while self._win_h and self._win_h[-1][1] <= h:
                self._win_h.pop()
            self._win_h.append((idx, h))
            while self._win_l and self._win_l[-1][1] >= l:
                self._win_l.pop()
            self._win_l.append((idx, l))
        if self._win_h:
            self.cur_high_price = float(self._win_h[0][1])
            self.cur_high_idx = int(self._win_h[0][0])
            self.cur_high_sl = self.cur_high_price * self.cfg.sl_factor_high()
        if self._win_l:
            self.cur_low_price = float(self._win_l[0][1])
            self.cur_low_idx = int(self._win_l[0][0])
            self.cur_low_sl = self.cur_low_price * self.cfg.sl_factor_low()

    def set_state(self, high: float, high_idx: int, low: float,
                  low_idx: int) -> None:
        """B4 (Fallback ohne Window-Tail): Einzelpunkt-Bootstrap aus den
        Batch-Endwerten (der letzte Record ist dann das Fenster-Extremum)."""
        self.seed_window([(high_idx, high, low)])

    def update_scalar(self, bar_idx: int, high: float,
                      low: float) -> Tuple[bool, bool, int, int]:
        vb = self._viewback()
        # Expiry: alte Fenster-Eintraege ausserhalb des Rolling-Windows
        while self._win_h and self._win_h[0][0] <= bar_idx - vb:
            self._win_h.popleft()
        while self._win_l and self._win_l[0][0] <= bar_idx - vb:
            self._win_l.popleft()
        # Insert (monotone Deques)
        while self._win_h and self._win_h[-1][1] <= high:
            self._win_h.pop()
        self._win_h.append((bar_idx, high))
        while self._win_l and self._win_l[-1][1] >= low:
            self._win_l.pop()
        self._win_l.append((bar_idx, low))
        new_h = float(self._win_h[0][1])
        new_l = float(self._win_l[0][1])

        prev_h = self.cur_high_price
        prev_l = self.cur_low_price
        is_new_h = np.isnan(prev_h) or new_h != prev_h
        is_new_l = np.isnan(prev_l) or new_l != prev_l
        # 22.01b/4b (Grabber-Rework): Richtungs-Flags unterscheiden einen
        # ECHTEN neuen Peak (h_dir=+1 Hoch steigt / l_dir=-1 Tief faellt)
        # von einer Expiry (h_dir=-1 / l_dir=+1: das alte Extremum verlaesst
        # das Rolling-Fenster). Der Grabber loest nur bei echten neuen Peaks
        # Events aus; Expiry aktualisiert die SL-Referenz stumm.
        h_dir = 0
        l_dir = 0
        if is_new_h:
            self.cur_high_price = new_h
            self.cur_high_idx = int(self._win_h[0][0])
            self.cur_high_sl = new_h * self.cfg.sl_factor_high()
            if not np.isnan(prev_h):
                h_dir = 1 if new_h > prev_h else -1
        if is_new_l:
            self.cur_low_price = new_l
            self.cur_low_idx = int(self._win_l[0][0])
            self.cur_low_sl = new_l * self.cfg.sl_factor_low()
            if not np.isnan(prev_l):
                l_dir = -1 if new_l < prev_l else 1
        return is_new_h, is_new_l, h_dir, l_dir


class PeakGrabberLiveState:
    """Live-State-Machine (Parität zum Kernel §3.1, B2/B3/B6).

    Kein Plugin – wird ausschließlich vom Indikator ind_peak getrieben.
    """

    def __init__(self, cfg: PeakGrabberConfig, finder: PeakFinderLive,
                 symbol: str, timeframe: str) -> None:
        self.cfg = cfg
        self.finder = finder
        self.symbol = symbol
        self.tf = timeframe
        self.run_id: str = "LIVE"
        self.is_btn_active: bool = False
        self.state_short: GrabberState = GrabberState.IDLE
        self.state_long: GrabberState = GrabberState.IDLE

    def set_button_active(self, active: bool) -> None:
        self.is_btn_active = bool(active)
        if not active:
            self.state_short = GrabberState.IDLE
            self.state_long = GrabberState.IDLE

    def process_tick_or_bar(
        self,
        bar_idx: int,
        high: float,
        low: float,
        close: float,
        ts: datetime,
        is_yellow_window: bool,
    ) -> List[GrabberResultRecord]:
        events: List[GrabberResultRecord] = []

        # B3: VOR update_scalar den vorherigen Peak-Stand sichern
        # (Alter des VORHERIGEN Peaks, Parität zur Kernel-Semantik).
        prev_h_price = self.finder.cur_high_price
        prev_h_idx = self.finder.cur_high_idx
        prev_l_price = self.finder.cur_low_price
        prev_l_idx = self.finder.cur_low_idx

        is_new_h, is_new_l, h_dir, l_dir = self.finder.update_scalar(
            bar_idx, high, low)

        gate = self.is_btn_active and (
            is_yellow_window if self.cfg.require_proximity_window else True
        )
        if not gate:
            return events

        # --- Short Side (Peak = laufendes Hoch) --------------------------
        # 22.01b/4b (Grabber-Rework): NUR ein ECHTER neuer Fenster-Peak
        # (h_dir > 0: Fenster-Hoch steigt) loest die Arm-/Update-/
        # Invalidate-Logik aus. Expiry (h_dir < 0: der alte Peak verlaesst
        # das Rolling-Fenster, das Fenster-Hoch faellt) aktualisiert die
        # SL-Referenz in update_scalar stumm - KEIN Event (Kernel-Paritaet,
        # der kumulative Kernel kennt keine Expiry).
        if h_dir > 0 and not np.isnan(prev_h_price):
            bars_h = bar_idx - prev_h_idx
            breach_pct = ((high - prev_h_price) / prev_h_price) * 100.0
            if bars_h <= self.cfg.invalidation_bars:
                if breach_pct <= self.cfg.invalidation_threshold_pct:
                    self.state_short = GrabberState.ARMED
                    events.append(self._build_record(
                        ts, SignalDirection.SELL, close,
                        self.finder.cur_high_sl, self.finder.cur_high_price,
                        bar_idx, True, 0.0, is_yellow_window,
                        "GATE_UPDATE"))
                else:
                    self.state_short = GrabberState.INVALIDATED
            else:
                self.state_short = GrabberState.ARMED
        if self.state_short == GrabberState.ARMED:
            bars_h = bar_idx - self.finder.cur_high_idx
            rev = (((self.finder.cur_high_price - close)
                    / self.finder.cur_high_price) * 100.0
                   if self.finder.cur_high_price > 0.0 else 0.0)
            if rev >= self.cfg.reversal_pct and bars_h >= self.cfg.min_hold_bars:
                self.state_short = GrabberState.TRIGGERED
                events.append(self._build_record(
                    ts, SignalDirection.SELL, close,
                    self.finder.cur_high_sl, self.finder.cur_high_price,
                    bar_idx, False, rev, is_yellow_window, "GATE_TRIGGER"))

        # --- Long Side (Peak = laufendes Tief) ---------------------------
        # Analog: NUR ein ECHTER neuer Fenster-Peak (l_dir < 0: Fenster-Tief
        # faellt) loest die Logik aus; Expiry (l_dir > 0: Fenster-Tief
        # steigt) bleibt stumm.
        if l_dir < 0 and not np.isnan(prev_l_price):
            bars_l = bar_idx - prev_l_idx
            breach_pct = ((prev_l_price - low) / prev_l_price) * 100.0
            if bars_l <= self.cfg.invalidation_bars:
                if breach_pct <= self.cfg.invalidation_threshold_pct:
                    self.state_long = GrabberState.ARMED
                    events.append(self._build_record(
                        ts, SignalDirection.BUY, close,
                        self.finder.cur_low_sl, self.finder.cur_low_price,
                        bar_idx, True, 0.0, is_yellow_window,
                        "GATE_UPDATE"))
                else:
                    self.state_long = GrabberState.INVALIDATED
            else:
                self.state_long = GrabberState.ARMED
        if self.state_long == GrabberState.ARMED:
            bars_l = bar_idx - self.finder.cur_low_idx
            rev = (((close - self.finder.cur_low_price)
                    / self.finder.cur_low_price) * 100.0
                   if self.finder.cur_low_price > 0.0 else 0.0)
            if rev >= self.cfg.reversal_pct and bars_l >= self.cfg.min_hold_bars:
                self.state_long = GrabberState.TRIGGERED
                events.append(self._build_record(
                    ts, SignalDirection.BUY, close,
                    self.finder.cur_low_sl, self.finder.cur_low_price,
                    bar_idx, False, rev, is_yellow_window, "GATE_TRIGGER"))

        return events

    def _build_record(self, ts: datetime, direction: SignalDirection,
                      entry: float, sl: float, peak: float, idx: int,
                      upd: bool, rev: float, yellow: bool,
                      src: str) -> GrabberResultRecord:
        import uuid
        return GrabberResultRecord(
            signal_id=str(uuid.uuid4()),
            run_id=self.run_id,
            timestamp=ts,
            symbol=self.symbol,
            timeframe=self.tf,
            direction=direction,
            entry_price=entry,
            sl_price=sl,
            peak_price=peak,
            peak_bar_index=idx,
            is_update=upd,
            reversal_pct=rev,
            is_yellow_window=yellow,
            gate_source=src,
        )


# chart/indicators/ind_peak.py (Teil 2: Indikator, BaseIndicator)
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from chart.indicators.base_indicator import BaseIndicator
from analytics.engine.peak_models import (
    GrabberResultRecord,
    PeakConfig,
    PeakGrabberConfig,
)
from analytics.features.feature_builder import PluginExecutor
from analytics.features.plugins.base_plugin import PluginContext
from analytics.engine.set_evaluator import ServiceSetEvaluator

_PEAK_SCHEMA: Dict[str, Dict[str, Any]] = {
    "sl_offset_pct": {"type": "float", "default": 0.15, "min": 0.0, "max": 10.0, "step": 0.01, "description": "SL-Puffer über/unter Peak (%)"},
    # 22.01b (User-Anweisung 4a): Viewback-Fenster des Peak Finders - der
    # SL-Punkt wandert dem Kurs entlang; aeltere Signale innerhalb des
    # Fensters werden entfernt, aeltere bleiben persistent.
    "viewback_bars": {"type": "int", "default": 3, "min": 1, "max": 10000, "step": 1, "description": "Viewback: Bars zurueckschauen fuer lokales Hoch/Tief"},
    "reversal_pct": {"type": "float", "default": 0.30, "min": 0.01, "max": 10.0, "step": 0.01, "description": "Reversal % für Trigger (z)"},
    "min_hold_bars": {"type": "int", "default": 3, "min": 1, "max": 1000, "step": 1, "description": "Min. Bars Haltedauer des Peaks"},
    "invalidation_bars": {"type": "int", "default": 5, "min": 1, "max": 10000, "step": 1, "description": "Beobachtungsfenster x (Bars)"},
    "invalidation_threshold_pct": {"type": "float", "default": 0.10, "min": 0.0, "max": 10.0, "step": 0.01, "description": "Toleranz y% vor Hard-Invalidation"},
    "require_proximity_window": {"type": "bool", "default": True, "description": "Nur im Yellow Window triggern"},
    "show_sl_high": {"type": "bool", "default": True, "description": "SL-High-Linie anzeigen"},
    "show_sl_low": {"type": "bool", "default": True, "description": "SL-Low-Linie anzeigen"},
    "show_signals": {"type": "bool", "default": True, "description": "Trigger-Marker anzeigen"},
    "show_updates": {"type": "bool", "default": False, "description": "Update-Marker anzeigen"},
    "sl_high_color": {"type": "color", "default": "#EF5350", "description": "Farbe SL-High-Linie", "style_type": "line", "show_visibility": False},
    "sl_low_color": {"type": "color", "default": "#26A69A", "description": "Farbe SL-Low-Linie", "style_type": "line", "show_visibility": False},
}


class IndPeak(BaseIndicator):
    """Peak-Grabber-Indikator: SL-Linien + Trigger-Marker (Hist & Live).

    22.01d: Zeichnet AUSSCHLIESSLICH persistierte Service-Daten aus dem
    feature_store (keine In-Memory-Berechnung). `reader` ist optional
    injizierbar (Tests mit Test-DB; Default = FeatureStoreReader()).
    """

    def __init__(self, reader: Any = None) -> None:
        super().__init__()
        self._symbol: Optional[str] = None
        self._timeframe: Optional[str] = None
        self._settings: Any = None
        self._on_new_candle: Optional[Callable[[], None]] = None
        self._executor = PluginExecutor()
        self._evaluator = ServiceSetEvaluator(self._executor)
        self._last_params: Dict[str, Any] = {}
        # 22.01d: Injizierbarer Store-Reader (Tests) - None = Default.
        self._reader: Any = reader

        # Live-Komponenten (ring buffer, Zero-GC, B5)
        self._buffer_size: int = 2000
        self._head: int = 0
        self._buf_time = np.zeros(self._buffer_size, dtype=np.int64)
        self._buf_sl_high = np.full(self._buffer_size, np.nan, dtype=np.float64)
        self._buf_sl_low = np.full(self._buffer_size, np.nan, dtype=np.float64)
        self._filled: int = 0
        self._known_times: set = set()  # New-Candle-Erkennung (gerundete Zeit)
        # 22.01b: Live-Bar-Zaehler (Rolling-Window-Expiry pro BAR statt pro
        # Tick). Basis = letzter Batch-Bar-Index; wird bei jeder neuen
        # Live-Candle (gerundete Zeit wechselt) um 1 erhoeht.
        self._live_bar_base: int = 0
        self._live_bar_idx: Optional[int] = None
        self._last_live_rounded: Optional[int] = None

        self._live_state: Optional[PeakGrabberLiveState] = None
        # 22.01d (User-Anweisung 3): Letzter Live-Trigger (Orderpunkt) -
        # wird als Dreieck ueber/unter der Bar gezeichnet (statt der alten
        # SL-Kreise). Kein Kreis-Rendering mehr.
        self._last_live_trigger: Optional[GrabberResultRecord] = None
        self._last_live_trigger_ts: int = 0
        # 22.01d: Button-Zustand ueberlebt den Live-State-Reset (leerer
        # Store vor Servicelauf); wird beim naechsten Bootstrap uebertragen.
        self._btn_active: bool = False
        # 22.01e (Performance-Fix): Yellow-Flag-Cache - die srv_proximity-
        # Abfrage laeuft pro NEUER Candle (gerundete Zeit wechselt), nicht
        # bei jedem Tick (vorher: DB-Query/FeatureStoreReader-Instanz pro
        # Tick -> UI-Thread-Last, Maus-Panning blockiert).
        self._yellow_rounded: Optional[int] = None
        self._yellow_value: bool = True

    # ------------------------------------------------------------- Identität
    @property
    def indicator_id(self) -> str:
        return "ind_peak"

    @property
    def display_name(self) -> str:
        return "Ind_Peak (Peak Grabber)"

    @property
    def plugin_id(self) -> str:
        return "ind_peak"

    @property
    def service_plugin_ids(self) -> List[str]:
        return ["srv_peak_finder", "srv_peak_grabber"]

    @property
    def parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in _PEAK_SCHEMA.items()}

    @property
    def parameter_order(self) -> List[str]:
        return list(_PEAK_SCHEMA.keys())

    @property
    def default_params(self) -> Dict[str, Any]:
        return {k: v["default"] for k, v in _PEAK_SCHEMA.items() if "default" in v}

    # ------------------------------------------------------------- Kontext
    def set_context(self, symbol: str, timeframe: str) -> None:
        self._symbol = symbol
        self._timeframe = timeframe

    def set_settings(self, settings: Any) -> None:
        self._settings = settings

    def set_new_candle_callback(self, callback: Optional[Callable[[], None]]) -> None:
        self._on_new_candle = callback

    # ------------------------------------------------------------- Live-Hook
    def set_button_active(self, active: bool) -> None:
        """Wird von chart_win generisch über event_bus.grabber_toggle gerufen."""
        self._btn_active = bool(active)
        if self._live_state is not None:
            self._live_state.set_button_active(active)
        if not active:
            # 22.01d: Deaktivieren raeumt den Live-Trigger-Marker auf
            # (keine Zeichnung bei deaktiviertem Grabber, User-Anweisung 1).
            self._last_live_trigger = None
            self._last_live_trigger_ts = 0

    # ------------------------------------------------ Ringpuffer (B5, Zero-GC)
    def _push(self, ts: int, sl_high: float, sl_low: float) -> None:
        idx = self._head % self._buffer_size
        self._buf_time[idx] = int(ts)
        self._buf_sl_high[idx] = float(sl_high)
        self._buf_sl_low[idx] = float(sl_low)
        self._head += 1
        if self._filled < self._buffer_size:
            self._filled += 1

    def _ordered_buffers(self):
        start = max(0, self._head - self._filled)
        out_t = np.empty(self._filled, dtype=np.int64)
        out_h = np.empty(self._filled, dtype=np.float64)
        out_l = np.empty(self._filled, dtype=np.float64)
        for k in range(self._filled):
            src = (start + k) % self._buffer_size
            out_t[k] = self._buf_time[src]
            out_h[k] = self._buf_sl_high[src]
            out_l[k] = self._buf_sl_low[src]
        return out_t, out_h, out_l

    # ------------------------------------------------------------ Berechnung
    def _get_app_settings(self) -> Any:
        if self._settings is not None:
            return self._settings
        try:
            from state_manager import StateManager
            return StateManager().get_app_settings()
        except Exception:
            return None

    def _build_set_definition(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Frage 3: Set mit grid_1 → prox_1 (Zone-Hits in shared_state) →
        peak_1 → grab_1. Der Service srv_peak_grabber leitet is_yellow_window
        selbst her (Fallback True ohne Proximity-Signal)."""
        return {
            "set_id": "ind_peak_internal",
            "display_name": "Ind_Peak (intern)",
            "execution_order": ["grid_1", "prox_1", "peak_1", "grab_1"],
            "services": {
                "grid_1": {
                    "plugin_id": "srv_grid_lines",
                    "lookback": int(params.get("lookback") or 1000),
                    "params": {
                        "step_size": params.get("grid_step", 0.5),
                        "steps_around": params.get("steps_around", 4),
                    },
                },
                "prox_1": {
                    "plugin_id": "srv_proximity",
                    "lookback": int(params.get("lookback") or 1000),
                    "depends_on": ["grid_1"],
                    "params": {
                        # Frage 3: festes Zeitfenster ±5 min um :00/:30
                        "visit_pct": params.get("proximity_threshold", 0.05),
                        "time_window_mins": 5,
                        "use_time_filter": True,
                    },
                },
                "peak_1": {
                    "plugin_id": "srv_peak_finder",
                    "lookback": int(params.get("lookback") or 1000),
                    "params": {
                        "sl_offset_pct": params.get("sl_offset_pct", 0.15),
                        # 22.01b: Viewback-Fenster (Rolling-Window) - gehoert
                        # in den PEAK FINDER (nicht in den Grabber).
                        "viewback_bars": params.get("viewback_bars", 3),
                    },
                },
                "grab_1": {
                    "plugin_id": "srv_peak_grabber",
                    "lookback": int(params.get("lookback") or 1000),
                    "depends_on": ["peak_1", "prox_1"],
                    "params": {
                        "reversal_pct": params.get("reversal_pct", 0.30),
                        "min_hold_bars": params.get("min_hold_bars", 3),
                        "invalidation_bars": params.get("invalidation_bars", 5),
                        "invalidation_threshold_pct": params.get(
                            "invalidation_threshold_pct", 0.10),
                        "require_proximity_window": params.get(
                            "require_proximity_window", True),
                        "sl_offset_pct": params.get("sl_offset_pct", 0.15),
                    },
                },
            },
        }

    def calculate(self, df: pd.DataFrame,
                  params: Dict[str, Any]) -> Dict[str, Any]:
        """22.01d (User-Anweisungen 1-3): Zeichnet AUSSCHLIESSLICH
        persistierte Service-Daten aus dem feature_store - KEINE In-Memory-
        Berechnung mehr (keine Fantasie-Linien vor dem Servicelauf).

        * srv_peak_finder-Records  -> waagerechte SL-Striche je Peak-Bar
          (2 Punkte ueber die Barbreite, NIE miteinander verbunden).
        * srv_peak_grabber-Records -> Trigger-Dreiecke (hit_circles-Format)
          ueber/unter der Bar (arrowDown=SELL / arrowUp=BUY).
        * Keine Daten (vor Servicelauf) -> leeres Ergebnis + Live-State-
          Reset (keine Zeichnung, keine Alt-Zustaende).
        """
        empty = {"lines": [], "price_lines": [], "hit_circles": [],
                 "status_info": {}}
        if df is None or df.empty:
            return empty
        try:
            p = dict(params or {})
            self._last_params = dict(p)
            symbol = str(self._symbol or "")
            timeframe = str(self._timeframe or "")
            if not symbol or not timeframe:
                return empty

            # NUR aus dem feature_store lesen (read-only, keine Berechnung).
            # 22.01e (Performance-Fix): Records auf das df-Fenster begrenzen
            # (up_to_epoch = letzte df-Bar) - aeltere Records werden im
            # Render-Payload ohnehin verworfen, spart DB-Last/JSON-Parsing.
            try:
                if self._reader is not None:
                    reader = self._reader
                else:
                    from analytics.engine.feature_store_reader import FeatureStoreReader
                    reader = FeatureStoreReader()
                up_to = int(max(df["time"]))
                finder_recs = reader.fetch_plugin_records(
                    symbol, timeframe, "srv_peak_finder", up_to_epoch=up_to)
                grabber_recs = reader.fetch_plugin_records(
                    symbol, timeframe, "srv_peak_grabber", up_to_epoch=up_to)
            except Exception as e:
                print(f"[IndPeak] Feature-Store-Lesen fehlgeschlagen: {e}")
                return empty

            # User-Anweisung 1: vor Servicelauf keine Daten -> keine Zeichnung.
            if not finder_recs:
                self._reset_live_state()
                return empty

            # Zeit der jeweils naechsten Bar (Strich-Endpunkt; die naechste
            # Bar ist in der Zeit-Map -> kein Phantom-Slot). Nur die ALLER-
            # LETZTE df-Bar hat keinen Nachfolger -> dort nur 1 Punkt
            # (Punkt statt Strich, Edge-Case offene Live-Bar).
            from db_service import TF_SECONDS_MAP
            tf_sec = TF_SECONDS_MAP.get(timeframe.upper(), 60)
            times = df["time"].tolist()
            next_time: Dict[int, int] = {}
            for i in range(len(times) - 1):
                try:
                    next_time[int(times[i])] = int(times[i + 1])
                except (TypeError, ValueError):
                    continue
            times_int: List[int] = []
            for t in times:
                try:
                    times_int.append(int(t))
                except (TypeError, ValueError):
                    continue

            def _next_bar_after(t: int) -> Optional[int]:
                """Naechste echte df-Bar-Zeit nach t (oder None). Wird als
                Luecken-Zeit genutzt -> immer eine echte Bar-Zeit, daher kein
                Phantom-Slot in der Timescale (22.01-Lektion)."""
                lo, hi = 0, len(times_int)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if times_int[mid] <= t:
                        lo = mid + 1
                    else:
                        hi = mid
                return times_int[lo] if lo < len(times_int) else None

            # 22.01e (Performance-Fix, User-Anweisung 2): Die SL-Striche als
            # ZWEI Sammel-Series (sl_high/sl_low) statt einer separaten
            # LineSeries pro Record. Vorher erzeugte calculate() bei jedem
            # Rebuild bis zu tausende LWC-Series (addSeries je Strich) ->
            # Chart-Aufbau dauert ewig, Skalen blockieren, Maus-Panning
            # haengt. Zwischen zwei Strichen wird ein Luecken-Marker
            # {time, value: None} eingefuegt (LWC-null = Luecke) -> die
            # Striche bleiben NIE verbunden, die Serie ist trotzdem EINE.
            lines: List[Dict[str, Any]] = []

            def _stroke_series(records, key: str, color: str,
                               line_id: str, title: str) -> List[Dict[str, Any]]:
                data: List[Dict[str, Any]] = []
                for i, r in enumerate(records):
                    try:
                        t0 = int(r["bar_time"])
                        v = float(r[key])
                    except (TypeError, ValueError, KeyError):
                        continue
                    t1 = next_time.get(t0)
                    # Start des naechsten Strichs (fuer Luecken-Kollision).
                    t_next: Optional[int] = None
                    if i + 1 < len(records):
                        try:
                            t_next = int(records[i + 1]["bar_time"])
                        except (TypeError, ValueError, KeyError):
                            pass
                    if t1 is None or t1 == t_next:
                        # Letzte Bar oder direkt benachbarter naechster Strich:
                        # nur 1 Punkt (kein doppelter Zeitstempel; minimale
                        # Verbindung im seltenen Nachbar-Fall akzeptiert).
                        data.append({"time": t0, "value": v, "color": color})
                        continue
                    data.append({"time": t0, "value": v, "color": color})
                    data.append({"time": t1, "value": v, "color": color})
                    gap_t = _next_bar_after(t1)
                    if gap_t is not None and (t_next is None
                                              or gap_t < t_next):
                        data.append({"time": gap_t, "value": None})
                return [{
                    "id": line_id, "data": data,
                    "width": 1, "style": "solid", "title": title,
                }]

            if p.get("show_sl_high", True):
                lines.extend(_stroke_series(
                    finder_recs, "sl_high", p.get("sl_high_color", "#EF5350"),
                    "sl_high", "SL High"))
            if p.get("show_sl_low", True):
                lines.extend(_stroke_series(
                    finder_recs, "sl_low", p.get("sl_low_color", "#26A69A"),
                    "sl_low", "SL Low"))

            # Trigger-Dreiecke aus srv_peak_grabber (hit_circles-Format, damit
            # die generische Render-Pipeline sie zeichnet - User-Anweisung 3:
            # KEINE Kreise, Orderpunkt = Dreieck ueber/unter der Bar).
            hit_circles: List[Dict[str, Any]] = []
            if p.get("show_signals", True):
                for r in grabber_recs:
                    sig = int(r.get("signal") or 0)
                    if sig == 1:  # BUY_TRIGGER -> Dreieck unter der Bar
                        hit_circles.append({
                            "time": int(r["bar_time"]),
                            "price": float(r.get("peak_low") or 0.0),
                            "color": "#26A69A",
                            "shape": "arrowUp",
                            "size": 2,
                            "priority": 8,
                        })
                    elif sig == -1:  # SELL_TRIGGER -> Dreieck ueber der Bar
                        hit_circles.append({
                            "time": int(r["bar_time"]),
                            "price": float(r.get("peak_high") or 0.0),
                            "color": "#EF5350",
                            "shape": "arrowDown",
                            "size": 2,
                            "priority": 8,
                        })
                    elif p.get("show_updates", False):
                        hit_circles.append({
                            "time": int(r["bar_time"]),
                            "price": float(r.get("peak_high")
                                           or r.get("peak_low") or 0.0),
                            "color": "#90A4AE",
                            "shape": "circle",
                            "size": 1,
                            "priority": 5,
                        })

            # Bootstrap des Live-States aus den persistierten Finder-Records
            # (Fallback: der letzte Record ist das aktuelle Fenster-Extremum).
            self._bootstrap_live_state(finder_recs, p)

            return {
                "lines": lines,
                "hit_circles": hit_circles,
                "status_info": {
                    "is_btn_active": bool(
                        self._live_state and self._live_state.is_btn_active),
                    "trigger_count": len(hit_circles),
                },
            }
        except Exception as e:
            print(f"[IndPeak] Feature-Store-Pfad fehlgeschlagen: {e}")
            return empty

    def _reset_live_state(self) -> None:
        """22.01d: Setzt den Live-State zurueck (keine Daten / deaktiviert).

        Raeumt Live-Trigger, Bar-Zaehler und Ringpuffer - danach zeichnet
        und triggert der Indikator nichts mehr (User-Anweisung 1)."""
        self._live_state = None
        self._last_live_trigger = None
        self._last_live_trigger_ts = 0
        self._live_bar_idx = None
        self._last_live_rounded = None
        self._filled = 0
        self._head = 0
        # 22.01e: Yellow-Flag-Cache ebenfalls zuruecksetzen (neue Bar-Basis).
        self._yellow_rounded = None
        self._yellow_value = True

    def _bootstrap_live_state(self, finder_recs: List[Dict[str, Any]],
                              p: Dict[str, Any],
                              window_tail: Optional[List] = None) -> None:
        """B4: übernimmt die letzten Batch-Peaks in den Live-Rolling-State.

        22.01b: Bevorzugt wird das Rolling-Window-Tail des Finders
        (window_tail = [(bar_idx, high, low), ...] der letzten viewback
        Bars) via seed_window() uebernommen - exakte Paritaet Batch -> Live.
        Fallback (Alt/Tests): Einzelpunkt-Bootstrap aus dem letzten Record.
        """
        if not finder_recs and not window_tail:
            return
        last = finder_recs[-1] if finder_recs else None
        peak_cfg = PeakConfig(
            sl_offset_pct=float(p.get("sl_offset_pct", 0.15)),
            viewback_bars=int(p.get("viewback_bars", 3)),
        )
        if self._live_state is None:
            finder_live = PeakFinderLive(peak_cfg)
            self._live_state = PeakGrabberLiveState(
                PeakGrabberConfig(
                    reversal_pct=float(p.get("reversal_pct", 0.30)),
                    min_hold_bars=int(p.get("min_hold_bars", 3)),
                    invalidation_bars=int(p.get("invalidation_bars", 5)),
                    invalidation_threshold_pct=float(p.get(
                        "invalidation_threshold_pct", 0.10)),
                    require_proximity_window=bool(p.get(
                        "require_proximity_window", True)),
                ),
                finder_live,
                self._symbol or "",
                self._timeframe or "",
            )
        # 22.01d: Button-Zustand uebertragen (ueberlebt den Reset bei
        # leerem Store; der User muss den Grabber nicht neu aktivieren).
        self._live_state.set_button_active(self._btn_active)
        if window_tail:
            self._live_state.finder.seed_window(window_tail)
            self._live_bar_base = int(window_tail[-1][0])
        elif last is not None:
            # Fallback: der letzte Record ist das aktuelle Fenster-Extremum.
            self._live_state.finder.set_state(
                float(last["peak_high"]), len(finder_recs) - 1,
                float(last["peak_low"]), len(finder_recs) - 1)
            self._live_bar_base = max(0, len(finder_recs) - 1)
        # 22.01b: Live-Bar-Zaehler zuruecksetzen (naechste Live-Candle startet
        # bei base+1 bzw. base, je nachdem ob die Batch-Endbar bereits die
        # offene Bar enthaelt - selbsterklaerend nach wenigen Bars).
        self._live_bar_idx = None
        self._last_live_rounded = None
        # Ringpuffer mit History-SL füllen (nur die letzten buffer_size).
        if finder_recs:
            n = min(len(finder_recs), self._buffer_size)
            self._filled = 0
            self._head = 0
            for r in finder_recs[-n:]:
                self._push(int(r["bar_time"]),
                           float(r["sl_high"]), float(r["sl_low"]))

    # ----------------------------------------------------- Live-Tick-Pfad
    def update_live_candle(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Live: O(1) Tick-Update auf den letzten Ringpuffer-Slot + Yellow-
        Flag der aktuellen Bar. Neue Candle → genau EIN debounced Refresh."""
        if not candle or self._live_state is None:
            return []
        try:
            ts = int(candle.get("time", 0))
            high = float(candle.get("high", candle.get("price", 0.0)))
            low = float(candle.get("low", high))
            close = float(candle.get("close", candle.get("price", 0.0)))
        except (TypeError, ValueError):
            return []

        # Yellow-Flag aktuell (letzter srv_proximity-Record, FeatureStoreReader)
        yellow = self._is_current_bar_yellow(ts)
        # New-Candle-Erkennung (gerundete Zeit, Muster ind_fixed_grid_proximity)
        from db_service import TF_SECONDS_MAP
        t_sec = TF_SECONDS_MAP.get(str(self._timeframe or "").upper(), 60)
        rounded = ts - (ts % t_sec)
        # 22.01b: Live-Bar-Zaehler - genau EINE Index-Erhoehung pro neuer
        # Candle (Rolling-Window-Expiry des Finders muss BAR-basiert sein,
        # nicht Tick-basiert; Ticks derselben Bar teilen sich den bar_idx).
        if rounded != self._last_live_rounded:
            if self._last_live_rounded is not None:
                if self._live_bar_idx is None:
                    self._live_bar_idx = self._live_bar_base + 1
                else:
                    self._live_bar_idx += 1
            self._last_live_rounded = rounded
        if rounded not in self._known_times:
            self._known_times.add(rounded)
            if self._on_new_candle is not None:
                try:
                    self._on_new_candle()
                except Exception:
                    pass

        if self._live_bar_idx is None:
            bar_idx = self._live_bar_base + 1
            self._live_bar_idx = bar_idx
        else:
            bar_idx = self._live_bar_idx
        records = self._live_state.process_tick_or_bar(
            bar_idx, high, low, close,
            pd.Timestamp(ts, unit="s").to_pydatetime(),  # B7
            yellow)
        # Live-SL-Punkt in den Ringpuffer (In-Place, letzter Slot).
        self._push(ts, self._live_state.finder.cur_high_sl,
                   self._live_state.finder.cur_low_sl)

        if records:
            # Persistenz + UI-Modal über den EventBus (Präambel 4, IoC)
            try:
                from config.event_bus import event_bus
                for rec in records:
                    event_bus.grabber_event.emit(rec)
            except Exception:
                pass
        return records

    def _is_current_bar_yellow(self, ts: int) -> bool:
        """Frage 3 (Live): Zone-Hit ∧ Zeitfenster der aktuellen Bar aus dem
        letzten srv_proximity-Record; **Fallback `True`** ohne Proximity-
        Signal (Gate offen).

        22.01e (Performance-Fix): Die Abfrage laeuft pro NEUER Candle
        (gerundete Zeit wechselt) und wird gecacht - bei jedem Tick derselben
        Bar wird der Cache-Wert zurueckgegeben (vorher: neue Reader-Instanz +
        DB-Query pro Tick -> UI-Thread-Last, Maus-Panning blockiert).
        """
        try:
            from db_service import TF_SECONDS_MAP
            t_sec = TF_SECONDS_MAP.get(str(self._timeframe or "").upper(), 60)
            rounded = int(ts) - (int(ts) % t_sec)
            if rounded == self._yellow_rounded:
                return self._yellow_value
            from analytics.engine.feature_store_reader import FeatureStoreReader
            reader = FeatureStoreReader()
            rec = reader.latest_proximity_record(
                self._symbol or "", self._timeframe or "", int(ts))
            if rec:
                fd = rec.get("feature_data") or {}
                val = bool(fd.get("in_time_window")
                           and (fd.get("levels_hit") or []))
            else:
                val = True
            self._yellow_rounded = rounded
            self._yellow_value = val
            return val
        except Exception:
            pass
        return True

    # ---------------------------------------------------- Overlay-Hooks (P14-03)
    def get_live_overlays(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """22.01d (User-Anweisung 3): KEINE SL-Kreise mehr.

        Der Live-Grabber zeichnet nur den letzten Orderpunkt (Trigger) als
        Dreieck ueber/unter der aktuellen Bar (arrowDown=SELL / arrowUp=BUY).
        Proximity-Circles und Grid-Lines sind reine Berechnungshilfen und
        werden nie gezeichnet. Deaktivierter Grabber -> leere Overlays.
        """
        records = self.update_live_candle(candle)
        if self._live_state is None or not self._live_state.is_btn_active:
            return []
        for rec in records:
            if rec.is_update:
                continue
            self._last_live_trigger = rec
            try:
                self._last_live_trigger_ts = int(rec.timestamp.timestamp())
            except Exception:
                self._last_live_trigger_ts = int(candle.get("time", 0))
        trig = self._last_live_trigger
        if trig is None:
            return []
        ts = self._last_live_trigger_ts or int(candle.get("time", 0))
        if trig.direction == SignalDirection.SELL:
            return [{
                "kind": "circle", "layer": self.indicator_id,
                "time": ts,
                "price": float(trig.peak_price),
                "color": "#EF5350", "shape": "arrowDown",
                "size": 2, "priority": 10,
            }]
        return [{
            "kind": "circle", "layer": self.indicator_id,
            "time": ts,
            "price": float(trig.peak_price),
            "color": "#26A69A", "shape": "arrowUp",
            "size": 2, "priority": 10,
        }]

    def remember_live_time(self, ts: int) -> None:
        try:
            self._known_times.add(int(ts))
        except (TypeError, ValueError):
            pass

```

--------------------------------------------------

### DATEI: chart/indicators/utils/__init__.py
```py
# ==============================================================================
# chart/indicators/utils/__init__.py
# ==============================================================================
# Phase 16.04: Reine Utility-Helfer für Indikatoren (keine Analytics-Plugins,
# keine Feature-Store-Schreibzugriffe). Exportfrei – Module werden direkt
# importiert (z. B. chart.indicators.utils.ma_template.MATemplateEngine),
# analog zum exportfreien chart/indicators/__init__.py (Phase 15).

```

--------------------------------------------------

### DATEI: chart/indicators/utils/chart_data_buffer.py
```py
# chart/indicators/utils/chart_data_buffer.py
"""
Phase 16.07 – ChartDataBuffer (Two-Tier Caching, Tier-2-RAM-Puffer)
====================================================================

Eigene Engine-Klasse (D2, SRP – Rule 2.3) für den Tier-2-Datenpuffer der
Two-Tier-Architektur. `PyTraderChartWindow` (PySide6-UI) hält nur eine
**Referenz** auf dieses Backend-Puffer-Objekt; schwere DataFrames und die
Zeit-Map-Verwaltung leben ausschliesslich hier.

Konzepte (verbindliche Entscheidungen D1–D10, docs/AKTUELLE_UMSETZUNG.md):
  * **M = 10.000** served Kerzen im RAM (D2). Rechte Kante = Live-Ende.
  * **N = 1.000** = Tier-1-Fenster-/Chunk-Grösse (D1).
  * **Warmup (D6):** Reiner Lese-Vorlauf `period*4 + smoothing*3` NUR für
    Gleitdurchschnitts-Indikatoren. Die Warmup-Kerzen liegen als
    `_warmup_candles` links vom served Bereich und werden ausschliesslich
    für die DataFrame-Berechnung genutzt (danach verworfen – sie werden
    NIE an JS gesendet, NIE als Tier-1-Candles geführt).
  * **Kontinuierliche Zeit (Wanduhr):** `time_cont_to_real`/`time_real_to_cont`
    werden IN-PLACE gepflegt (ChartWindow hält gültige Referenzen).
    Beim Prepend neuer (älterer) Kerzen bleiben die cont-Zeiten der
    BESTEHENDEN Kerzen unverändert (neuer Block erhält cont-Zeiten
    unterhalb des bisherigen Minimums) – dadurch ist der JS-Ausschnitt
    inkrementell ergänzbar, ohne dass die Chart-Zeitskala springt.
  * **serve_older():** RAM-Serve mit 0 ms I/O-Latenz (D3/D4) – solange der
    Puffer nach links reicht. None = Puffer erschöpft.
  * **merge_older():** DB-Fetch-Ergebnis (Chunk) wird vorne eingefügt;
    überschreitet der Puffer die Kapazität M, werden die rechtesten
    (neuesten) Kerzen abgeworfen (Sliding Window) und ihre Map-Einträge
    entfernt.
  * **has_more_history (D8):** Stop-Flag bei 0 neuen Zeilen (DB-Ende) –
    kein Endlos-Loop.

Reine Backend-Engine (kein UI-Import), abhängig nur von `db_service`
(MarketDataRepository) und `pandas` – kompatibel mit Rule 2.3 (SRP).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from db_service import MarketDataRepository, TF_SECONDS_MAP


class ChartDataBuffer:
    """Tier-2-RAM-Datenpuffer für historische OHLCV-Kerzen (Wanduhr-Epochs).

    Stateful Backend-Engine – ein Objekt pro Chart-Fenster (Referenz aus der
    UI-Klasse, D2). Enthält KEINE Qt-/UI-Abhängigkeiten und ist headless
    testbar (test/test.py).
    """

    # --- Verbindliche Grössen (D1/D2) -------------------------------------
    TIER2_CAPACITY: int = 10000   # M: served Kerzen im RAM (Faktor 10)
    TIER1_WINDOW: int = 1000      # N: Tier-1-Fenster-/Chunk-Grösse

    def __init__(self, market_repo: Optional[MarketDataRepository] = None) -> None:
        self.market_repo: MarketDataRepository = market_repo or MarketDataRepository()
        self.symbol: Optional[str] = None
        self.timeframe: Optional[str] = None
        self.tf_seconds: int = 60
        self.precision: int = 2

        # Served (sichtbare) Kerzen – reale Wanduhr-Epochs, aufsteigend.
        self.candles: List[Dict[str, Any]] = []
        # Reiner Lese-Vorlauf (D6) – NUR für die DataFrame-Berechnung,
        # wird NIE an JS gesendet / als Tier-1-Candle geführt.
        self._warmup_candles: List[Dict[str, Any]] = []
        # DataFrame über Warmup + served (Indikator-Berechnung, D5).
        self.df: Optional[pd.DataFrame] = None

        self.has_more_history: bool = True
        self.warmup_needed: int = 0

        # Kontinuierliche Zeit-Maps (Wanduhr-Epochs). Werden IN-PLACE
        # gepflegt, damit externe Referenzen (ChartWindow) dauerhaft gültig
        # bleiben.
        self.time_cont_to_real: Dict[int, int] = {}
        self.time_real_to_cont: Dict[int, int] = {}

    # ------------------------------------------------------------------
    # Defensive Candle-Sanitisierung (analog Bestandscode in chart_win)
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize_candles(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Entfernt NaN/Inf/None aus OHLC und normalisiert tick_volume.

        Doppel-Absicherung zur Normalisierung in fetch_historical_candles,
        damit json.dumps(allow_nan=False) nie scheitert und df-Spalten
        (tick_volume fuer VWMA, P16.05 F3) sauber sind. NaN/None in
        tick_volume -> 0, die Candle bleibt gueltig.
        """
        import math
        out: List[Dict[str, Any]] = []
        for c in candles or []:
            try:
                t = int(c.get("time"))
            except (TypeError, ValueError):
                continue
            try:
                o = float(c.get("open"))
                h = float(c.get("high"))
                lo = float(c.get("low"))
                cl = float(c.get("close"))
            except (TypeError, ValueError):
                continue
            if (math.isnan(o) or math.isnan(h) or math.isnan(lo) or math.isnan(cl)):
                continue
            tv_raw = c.get("tick_volume")
            if tv_raw is None:
                tv = 0.0
            else:
                try:
                    tv = float(tv_raw)
                except (TypeError, ValueError):
                    tv = 0.0
                if math.isnan(tv):
                    tv = 0.0
            out.append({
                "time": t, "open": o, "high": h, "low": lo,
                "close": cl, "tick_volume": tv,
            })
        return out

    # ------------------------------------------------------------------
    # Initial-Load (vollständiger Reset)
    # ------------------------------------------------------------------
    def load_initial(self, symbol: str, timeframe: str,
                     warmup: int = 0, limit: Optional[int] = None) -> None:
        """Lädt die letzten `M + warmup` Kerzen aus DuckDB in den Puffer.

        - `self.candles` (served): die letzten `M` Kerzen.
        - `self._warmup_candles`: der ältere Vorlauf (D6, verworfen).
        - `has_more_history`: False, wenn die DB kürzer als das
          angeforderte Limit ist (DB-Anfang erreicht).
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.tf_seconds = TF_SECONDS_MAP.get(str(timeframe).upper(), 60)
        self.warmup_needed = max(int(warmup or 0), 0)
        limit = int(limit or self.TIER2_CAPACITY)
        fetch_limit = limit + self.warmup_needed

        candles, precision = self.market_repo.fetch_historical_candles(
            symbol, timeframe, limit=fetch_limit)
        candles = self._sanitize_candles(candles)
        self.precision = precision
        self.has_more_history = len(candles) >= fetch_limit

        if not candles:
            self.candles = []
            self._warmup_candles = []
            self.df = None
            self.time_cont_to_real.clear()
            self.time_real_to_cont.clear()
            return

        if self.warmup_needed > 0 and len(candles) > limit:
            self._warmup_candles = candles[:self.warmup_needed]
            self.candles = candles[self.warmup_needed:]
        else:
            warmup_take = min(self.warmup_needed, max(0, len(candles) - limit))
            self._warmup_candles = candles[:warmup_take]
            self.candles = candles[warmup_take:]

        # served auf Kapazität kappen (rechte Kante = Live-Ende behalten)
        if len(self.candles) > limit:
            self.candles = self.candles[-limit:]

        self._rebuild_maps()
        self._rebuild_df()

    # ------------------------------------------------------------------
    # RAM-Serve (D3/D4: 0 ms I/O-Latenz)
    # ------------------------------------------------------------------
    def serve_older(self, from_epoch: int, count: int) -> Optional[Tuple[List[Dict[str, Any]], int, bool]]:
        """Bedient bis zu `count` Kerzen, die ÄLTER als `from_epoch` sind,
        direkt aus dem RAM-Puffer.

        Returns:
            (new_cont_candles, window_right_epoch, has_more) – oder None,
            wenn der Puffer nach links erschöpft ist (DB-Fetch nötig, D7).
        """
        if not self.candles or from_epoch is None:
            return None
        if int(from_epoch) <= self.candles[0]["time"]:
            return None
        eligible = [c for c in self.candles if c["time"] < int(from_epoch)]
        selected = eligible[-count:]
        if not selected:
            return None
        new_candles: List[Dict[str, Any]] = []
        for c in selected:
            real = int(c["time"])
            cont = self.time_real_to_cont.get(real)
            if cont is None:
                continue
            cc = dict(c)
            cc["time"] = cont
            new_candles.append(cc)
        if not new_candles:
            return None
        window_right = self.candles[-1]["time"] if self.candles else 0
        # has_more=True: die Erschöpfung (DB-Ende) wird erst beim nächsten
        # Request / beim DB-Merge detektiert (D8, selbstkorrigierend).
        return new_candles, int(window_right), True

    # ------------------------------------------------------------------
    # DB-Merge (Sliding Window, D7/D8)
    # ------------------------------------------------------------------
    def merge_older(self, fetched: List[Dict[str, Any]],
                    serve_count: Optional[int] = None,
                    warmup: Optional[int] = None) -> Tuple[List[Dict[str, Any]], int, bool]:
        """Fügt ein DB-Fetch-Ergebnis (Chunk, aufsteigend, ALLE jünger als
        die bisher älteste served Kerze) vorne in den Puffer ein.

        - `serve_count` Kerzen werden served (JS bekommt sie); der ältere
          Rest (bis `warmup`) wird als reiner Lese-Vorlauf übernommen (D6).
        - Überschreitet der Puffer die Kapazität M, werden die rechtesten
          Kerzen abgeworfen und ihre Map-Einträge entfernt (Sliding Window).
        - Liefert 0 neue Kerzen bei DB-Ende -> `has_more_history=False` (D8).

        Returns:
            (new_cont_candles, window_right_epoch, has_more)
        """
        serve_count = int(serve_count or self.TIER1_WINDOW)
        warmup = max(int(warmup or 0), 0)

        if not fetched:
            self.has_more_history = False
            return [], int(self.candles[-1]["time"]) if self.candles else 0, False

        fetched = self._sanitize_candles(fetched)
        if not fetched:
            self.has_more_history = False
            return [], int(self.candles[-1]["time"]) if self.candles else 0, False

        prev_oldest = self.candles[0]["time"] if self.candles else None
        if prev_oldest is not None:
            fetched = [c for c in fetched if c["time"] < prev_oldest]
        if not fetched:
            # Alles bereits im Puffer (doppelter Request) – keine Erschöpfung.
            return [], int(self.candles[-1]["time"]) if self.candles else 0, self.has_more_history

        if len(fetched) <= serve_count:
            served = fetched
            new_warmup: List[Dict[str, Any]] = []
        else:
            served = fetched[-serve_count:]
            new_warmup = fetched[:-serve_count][-warmup:] if warmup > 0 else []

        k = len(served)
        min_cont = min(self.time_cont_to_real.keys()) if self.time_cont_to_real else 0
        new_cont_candles: List[Dict[str, Any]] = []
        for j, c in enumerate(served):
            cont = min_cont - (k - j) * self.tf_seconds
            real = int(c["time"])
            self.time_cont_to_real[cont] = real
            self.time_real_to_cont[real] = cont
            cc = dict(c)
            cc["time"] = cont
            new_cont_candles.append(cc)

        self.candles = served + self.candles

        # Kapazitäts-Grenze M: rechteste (neueste) Überschuss-Kerzen abwerfen
        if len(self.candles) > self.TIER2_CAPACITY:
            drop = self.candles[self.TIER2_CAPACITY:]
            self.candles = self.candles[:self.TIER2_CAPACITY]
            for dc in drop:
                real = int(dc["time"])
                old_cont = self.time_real_to_cont.pop(real, None)
                if old_cont is not None:
                    self.time_cont_to_real.pop(old_cont, None)

        # D6: Warmup-Vorlauf ersetzen (nur für Berechnung, verworfen).
        self._warmup_candles = new_warmup
        self.has_more_history = len(fetched) >= (serve_count + warmup)
        self._rebuild_df()

        window_right = int(self.candles[-1]["time"]) if self.candles else 0
        return new_cont_candles, window_right, self.has_more_history

    # ------------------------------------------------------------------
    # Tier-1-Zugriff (D1)
    # ------------------------------------------------------------------
    def window_candles(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Liefert die letzten `count` served Kerzen kont-zeit-gemappt
        (Tier-1-Fenster, D1: N=1000)."""
        count = int(count or self.TIER1_WINDOW)
        if not self.candles:
            return []
        selected = self.candles[-count:]
        out: List[Dict[str, Any]] = []
        for c in selected:
            real = int(c["time"])
            cont = self.time_real_to_cont.get(real)
            if cont is None:
                continue
            cc = dict(c)
            cc["time"] = cont
            out.append(cc)
        return out

    @property
    def first_real(self) -> Optional[int]:
        """Reale Wanduhr-Epoch der ältesten served Kerze (JS-Fenster-Linkskante)."""
        return int(self.candles[0]["time"]) if self.candles else None

    @property
    def last_real(self) -> Optional[int]:
        """Reale Wanduhr-Epoch der jüngsten served Kerze (rechte Kante / Live-Ende)."""
        return int(self.candles[-1]["time"]) if self.candles else None

    # ------------------------------------------------------------------
    # Interne Helfer
    # ------------------------------------------------------------------
    def _rebuild_maps(self) -> None:
        """Baut beide cont-Zeit-Maps aus den served Kerzen NEU auf (IN-PLACE).

        Kontinuierliche Zeit = base_time + i*tf_sec (indexbasiert, lückenlos).
        base_time = reale Zeit der ältesten served Kerze (Wanduhr-Konvention:
        MT5/Epochs sind bereits Berlin-Wanduhr-encoded, kein Offset – vgl.
        02_time_utils.js / check_broker_tz.py).
        """
        self.time_cont_to_real.clear()
        self.time_real_to_cont.clear()
        candles = self.candles
        if not candles:
            return
        base = candles[0]["time"]
        for i, c in enumerate(candles):
            cont = base + i * self.tf_seconds
            real = int(c["time"])
            self.time_cont_to_real[cont] = real
            self.time_real_to_cont[real] = cont

    def _rebuild_df(self) -> None:
        """Baut `self.df` aus Warmup-Vorlauf + served Kerzen neu auf (D5)."""
        combined = list(self._warmup_candles) + list(self.candles)
        if not combined:
            self.df = None
            return
        self.df = pd.DataFrame(combined)

```

--------------------------------------------------

### DATEI: chart/indicators/utils/ma_template.py
```py
# chart/indicators/utils/ma_template.py
"""
Phase 16.04 – Generisches MA-Template-Modul
============================================

Wiederverwendbare Moving-Average-Utility für Chart-Indikatoren.

WICHTIG (Entscheidungen 06.08.2026, Doku-Analyse 16.04):
  * KEIN Analytics-Plugin, KEINE Feature-Store-Schreibzugriffe – reine
    Utility-Klasse (P16.01-Philosophie: Darstellung additiv im Indikator).
  * MAType = TradingView-konformer 12er-Satz in exakter Reihenfolge
    (E2): SMA, EMA, WMA, DEMA, TEMA, HMA, EHMA, ZLEMA, RMA, KAMA, ALMA, VWMA.
  * Defaults (E3): ma_type="EHMA", period=4, alpha_factor=2.0,
    smoothing=10, dual_color=False, bull_color="#2196F3",
    bear_color="#EF5350".
  * Alpha-MAs (E4): DEMA, TEMA, EHMA verwenden den dynamischen Decay-Faktor
    alpha = alpha_factor / (period + 1).
  * VWMA (E5): ohne gültiges Volumen (fehlend/Null) Fallback auf SMA.
  * smoothing (Vertrag B, 16.04 Schritt 5): optionaler zweiter EMA-Pass
    über die Basis-MA-Serie (auf alle 12 Typen anwendbar). smoothing > 1 =
    aktiv (ema_first = EMA(base, span=smoothing); base = EMA(ema_first,
    alpha=alpha_calc) mit alpha_calc = alpha_factor / (period + 1));
    smoothing <= 1 = keine Glättung (Basis-Serie unverändert).
  * bull_color-Default bedingt (E7/Ergänzung 2): Schema liefert "#2196F3";
    der Konsument wendet "#26A69A" an, wenn dual_color=True UND bull_color
    nicht vom User gesetzt wurde (leer/None).
  * NaN-Handling (Ergänzung 3): build_chart_payload überspringt Zeilen mit
    NaN/None in time oder value (Warmup period-1); Längen-Mismatch bei colors
    wird defensiv toleriert (Fallback = bull_color).

Alle 12 MA-Typen sind vektorisiert via NumPy/Pandas (numpy 2.5.1 /
pandas 3.0.5 in .venv). KAMA ist inhärent rekursiv (ER-basiert) und läuft
über eine kompakte Python-Schleife auf dem NumPy-Array; alle anderen Typen
über rolling/ewm/convolve.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Kerntypen & Konstanten
# ---------------------------------------------------------------------------

MAType = Literal[
    "SMA",
    "EMA",
    "WMA",
    "DEMA",
    "TEMA",
    "HMA",
    "EHMA",
    "ZLEMA",
    "RMA",
    "KAMA",
    "ALMA",
    "VWMA",
]

MA_TYPES: tuple = (
    "SMA",
    "EMA",
    "WMA",
    "DEMA",
    "TEMA",
    "HMA",
    "EHMA",
    "ZLEMA",
    "RMA",
    "KAMA",
    "ALMA",
    "VWMA",
)

# Standardfarben (E3/E7)
_DEFAULT_BULL_COLOR: str = "#2196F3"
_DEFAULT_BULL_COLOR_DUAL: str = "#26A69A"
_DEFAULT_BEAR_COLOR: str = "#EF5350"

# KAMA-Standardkonstanten (Ergänzung 4): period = ER-Periode; fast/slow
# fest nach Kaufman (2/3 bzw. 2/31).
_KAMA_FAST_ALPHA: float = 2.0 / (2.0 + 1.0)
_KAMA_SLOW_ALPHA: float = 2.0 / (30.0 + 1.0)

# ALMA-Defaults (Ergänzung 4, TradingView): Offset 0.85, Sigma = period/6.
_ALMA_OFFSET: float = 0.85


def resolve_bull_color(
    dual_color: bool,
    bull_color: Optional[str] = None,
    default: str = _DEFAULT_BULL_COLOR,
) -> str:
    """Ergänzung 2 (E7): Löst den bedingten bull_color-Default auf.

    Schema-Default ist "#2196F3". Bei dual_color=True UND nicht gesetztem
    (leer/None) User-Wert wird der dual-freundliche Default "#26A69A"
    angewendet. Leerstring/whitespace wird wie "nicht gesetzt" behandelt.
    """
    if bull_color is not None and str(bull_color).strip():
        return str(bull_color).strip()
    if dual_color:
        return _DEFAULT_BULL_COLOR_DUAL
    return default


# ---------------------------------------------------------------------------
# Vektorisierte Kern-Bausteine (NumPy)
# ---------------------------------------------------------------------------


def _sma_values(values: np.ndarray, period: int) -> np.ndarray:
    """SMA über rollierende Fenster (konstanter Gewichtsvektor).

    Bugfix 12.08.2026 (srv_trend_hma_pivot / LiveAnalyzer): Ist die Serie
    KÜRZER als `period`, liefert `np.convolve(..., mode="valid")` ein Array
    der Länge `period-n+1`, während `result[period-1:]` leer ist -> ValueError
    "could not broadcast input array from shape (k,) into shape (0,)". Guard:
    kurze Serien -> komplett NaN (Warmup-Vertrag, kein Crash).
    """
    if period <= 1:
        return values.astype(float, copy=True)
    if len(values) < period:
        return np.full(len(values), np.nan, dtype=float)
    window = np.ones(period, dtype=float)
    conv = np.convolve(values, window, mode="valid") / float(period)
    result = np.full(len(values), np.nan, dtype=float)
    result[period - 1:] = conv
    return result


def _wma_values(values: np.ndarray, period: int) -> np.ndarray:
    """WMA (linear gewichtet, jüngster Wert = höchstes Gewicht) via Faltung.

    np.convolve wendet die Gewichte rückwärts an (v[0] trifft den ältesten
    Wert). Daher wird der Gewichtsvektor absteigend angelegt ([p, p-1, .., 1]),
    damit der jüngste Wert das höchste Gewicht p erhält. result[t] ist am
    Fensterende positioniert (Warmup = period-1 NaNs).
    """
    if period <= 1:
        return values.astype(float, copy=True)
    if len(values) < period:
        return np.full(len(values), np.nan, dtype=float)
    weights = np.arange(period, 0, -1, dtype=float)
    conv = np.convolve(values, weights, mode="valid") / weights.sum()
    result = np.full(len(values), np.nan, dtype=float)
    result[period - 1:] = conv
    return result


def _ema_alpha_values(values: np.ndarray, alpha: float) -> np.ndarray:
    """EMA mit explizitem Decay-Faktor alpha (E4).

    Nutzt pandas ewm(alpha=alpha, adjust=False) – vektorisiert und exakt.
    """
    return np.array(
        pd.Series(values).ewm(alpha=alpha, adjust=False).mean().to_numpy(),
        dtype=float,
        copy=True,
    )


def _ema_span_values(values: np.ndarray, period: int) -> np.ndarray:
    """Standard-EMA (span=period) für Nicht-Alpha-MAs (EMA, ZLEMA)."""
    return np.array(
        pd.Series(values).ewm(span=period, adjust=False).mean().to_numpy(),
        dtype=float,
        copy=True,
    )


def _rma_values(values: np.ndarray, period: int) -> np.ndarray:
    """RMA (Wilder): ewm(alpha=1/period, adjust=False) (Ergänzung 4)."""
    if period <= 1:
        return values.astype(float, copy=True)
    return np.array(
        pd.Series(values).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy(),
        dtype=float,
        copy=True,
    )


def _hma_values(values: np.ndarray, period: int) -> np.ndarray:
    """HMA (Hull): WMA(2*WMA(half) - WMA(len), sqrt(len)).

    sqrt(len) wird auf eine ungerade Ganzzahl gerundet (min 1).
    """
    if period <= 1:
        return values.astype(float, copy=True)
    half = max(period // 2, 1)
    sqrt_period = max(int(np.sqrt(period)), 1)
    if sqrt_period % 2 == 0:
        sqrt_period += 1
    inner = 2.0 * _wma_values(values, half) - _wma_values(values, period)
    return _wma_values(inner, sqrt_period)


def _dema_values(values: np.ndarray, period: int, alpha: float) -> np.ndarray:
    """DEMA: 2*EMA_alpha - EMA_alpha(EMA_alpha) (E4)."""
    ema1 = _ema_alpha_values(values, alpha)
    return 2.0 * ema1 - _ema_alpha_values(ema1, alpha)


def _tema_values(values: np.ndarray, period: int, alpha: float) -> np.ndarray:
    """TEMA: 3*E1 - 3*E2 + E3 (E4)."""
    ema1 = _ema_alpha_values(values, alpha)
    ema2 = _ema_alpha_values(ema1, alpha)
    ema3 = _ema_alpha_values(ema2, alpha)
    return 3.0 * ema1 - 3.0 * ema2 + ema3


def _ehma_values(values: np.ndarray, period: int, alpha: float) -> np.ndarray:
    """EHMA: EMA_alpha(HMA(src, len), len) (Ergänzung 1, E4)."""
    return _ema_alpha_values(_hma_values(values, period), alpha)


def _zlema_values(values: np.ndarray, period: int) -> np.ndarray:
    """ZLEMA: EMA(xt, len) mit xt = src + (src - src[lag]), lag=(len-1)/2."""
    if period <= 1:
        return values.astype(float, copy=True)
    lag = int((period - 1) / 2)
    if lag < 1:
        lag = 1
    shifted = np.empty_like(values, dtype=float)
    shifted[:lag] = np.nan
    shifted[lag:] = values[:-lag]
    xt = values + (values - shifted)
    result = _ema_span_values(xt, period)
    # Warmup: xt ist erst ab Index lag definiert; die EMA läuft über die
    # NaN-Periode ohnehin erst ab period-1 vollständig auf. Defensiv werden
    # die ersten period-1 Werte als NaN markiert (Warmup-Vertrag).
    result[: max(period - 1, 0)] = np.nan
    return result


def _kama_values(values: np.ndarray, period: int) -> np.ndarray:
    """KAMA (Kaufman Adaptive MA), ER-basiert (Ergänzung 4).

    - period dient als ER-Periode (Change vs. Volatilität, Default 10).
    - alpha_factor entfällt bei KAMA.
    - Seed = values[length] (erster Wert mit definierter ER).
    - Inhärent rekursiv -> kompakte Python-Schleife über das NumPy-Array.
    """
    length = max(int(period), 1)
    n = len(values)
    result = np.full(n, np.nan, dtype=float)
    if n <= length:
        return result

    diff = np.abs(np.diff(values))  # len n-1
    # vol[i-length] = Summe der letzten `length` Bar-Diffs bis Index i
    vol = np.convolve(diff, np.ones(length, dtype=float), mode="valid")  # len n-length
    change = np.abs(values[length:] - values[:-length])  # len n-length
    er = np.divide(
        change, vol, out=np.zeros_like(change, dtype=float), where=vol > 0.0
    )
    sc = np.square(er * (_KAMA_FAST_ALPHA - _KAMA_SLOW_ALPHA) + _KAMA_SLOW_ALPHA)

    m = n - length
    kama = np.empty(m, dtype=float)
    prev = float(values[length])
    kama[0] = prev
    for i in range(1, m):
        val = float(values[length + i])
        prev = prev + sc[i] * (val - prev)
        kama[i] = prev
    result[length:] = kama
    return result


def _alma_values(values: np.ndarray, period: int) -> np.ndarray:
    """ALMA (Arnaud Legoux MA) mit TradingView-Defaults (Ergänzung 4).

    Gewichte werden über np.convolve angewendet – wegen der rückwärtigen
    Faltungs-Orientierung (v[0] trifft den ältesten Wert) wird weights[::-1]
    gefaltet, damit weights[0] auf den ältesten und weights[period-1] auf den
    jüngsten Wert des Fensters wirken (identisch zur Referenzschleife).
    """
    if period <= 1:
        return values.astype(float, copy=True)
    if len(values) < period:
        return np.full(len(values), np.nan, dtype=float)
    offset = (period - 1) * _ALMA_OFFSET
    sigma = period / 6.0
    m = np.arange(period, dtype=float) - offset
    weights = np.exp(-(m * m) / (2.0 * sigma * sigma))
    weights = weights / weights.sum()
    conv = np.convolve(values, weights[::-1], mode="valid")
    result = np.full(len(values), np.nan, dtype=float)
    result[period - 1:] = conv
    return result


def _vwma_values(
    values: np.ndarray, volume: np.ndarray, period: int
) -> np.ndarray:
    """VWMA: sum(price*volume) / sum(volume) über das Fenster.

    Null-/NaN-Volumen wird mit 0 normalisiert (Ergänzung 5). Ist die
    rollierende Volumen-Summe eines Fensters <= 0, fällt dieses Fenster auf
    den SMA-Wert zurück (kein Division-by-Zero).
    """
    if period <= 1:
        return values.astype(float, copy=True)
    if len(values) < period:
        return np.full(len(values), np.nan, dtype=float)
    vol = np.where(np.isnan(volume), 0.0, volume)
    pv = values * vol
    pv_sum = np.convolve(pv, np.ones(period, dtype=float), mode="valid")
    vol_sum = np.convolve(vol, np.ones(period, dtype=float), mode="valid")
    sma_tail = _sma_values(values, period)[period - 1:]
    valid = vol_sum > 0.0
    wv = np.full(len(vol_sum), np.nan, dtype=float)
    wv[valid] = pv_sum[valid] / vol_sum[valid]
    wv[~valid] = sma_tail[~valid]
    result = np.full(len(values), np.nan, dtype=float)
    result[period - 1:] = wv
    return result


# ---------------------------------------------------------------------------
# Öffentliche Klasse
# ---------------------------------------------------------------------------


class MATemplateEngine:
    """Vektorisierte Moving-Average-Utility für Indikatoren (Phase 16.04).

    Rein stateless – alle Methoden sind abhängigkeitsfrei und können direkt
    aus Indikator-Plugins heraus genutzt werden (Open/Closed, additiv).
    """

    # ------------------------------------------------------------ Schema-API
    @staticmethod
    def get_ma_parameter_schema() -> Dict[str, Dict[str, Any]]:
        """Standard-Parameter-Schema für MA-basierte Indikatoren.

        Konvention exakt wie im Projekt üblich (vgl. _FIXED_GRID_PROXIMITY_SCHEMA
        in chart/indicators/ind_fixed_grid_proximity.py und dem Schema-Renderer in
        chart/indicator_dialog.py): {"type": "...", "default": ...,
        "min"/"max"/"step", "options", "description", "style_type"}.

        Hinweis (E7/Ergänzung 2): bull_color-Default ist "#2196F3" – der
        dual_color-abhängige Default "#26A69A" wird zur Laufzeit über
        resolve_bull_color() aufgelöst.
        """
        return {
            "ma_type": {
                "type": "choice",
                "options": list(MA_TYPES),
                "default": "EHMA",
                "description": "Moving-Average-Typ",
            },
            "period": {
                "type": "int",
                "default": 4,
                "min": 1,
                "max": 500,
                "step": 1,
                "description": "MA-Periode",
            },
            "smoothing": {
                "type": "int",
                "default": 10,
                "min": 0,
                "max": 500,
                "step": 1,
                "description": "Glättung (zweiter EMA-Pass über die MA-Serie; <= 1 = keine Glättung)",
            },
            "alpha_factor": {
                "type": "float",
                "default": 2.0,
                "min": 0.1,
                "max": 10.0,
                "step": 0.1,
                "description": "Decay-Faktor für Alpha-MAs (EHMA/DEMA/TEMA)",
            },
            "dual_color": {
                "type": "bool",
                "default": False,
                "description": "Auf/Ab-Färbung aktiv (t vs. t-1)",
            },
            "bull_color": {
                "type": "color",
                "default": _DEFAULT_BULL_COLOR,
                "description": "Farbe steigender MA (dual_color=False durchgehend)",
                "style_type": "line",
            },
            "bear_color": {
                "type": "color",
                "default": _DEFAULT_BEAR_COLOR,
                "description": "Farbe fallender MA (dual_color=True)",
                "style_type": "line",
            },
        }

    # ------------------------------------------------------------ Berechnung
    @staticmethod
    def crop_dataframe(df: pd.DataFrame, max_limit: int) -> pd.DataFrame:
        """Schneidet den DataFrame auf die letzten `max_limit` Zeilen zu."""
        if df is None or max_limit is None:
            return df
        if len(df) <= max_limit:
            return df
        return df.tail(int(max_limit))

    @classmethod
    def calculate_ma(
        cls,
        source: pd.Series,
        ma_type: MAType,
        period: int,
        alpha_factor: float = 2.0,
        volume: Optional[pd.Series] = None,
        smoothing: int = 1,
    ) -> pd.Series:
        """Berechnet einen der 12 MA-Typen vektorisiert (Vertrag B).

        Args:
            source: Preis-Serie (z. B. df['close']).
            ma_type: Einer der 12 MA-Typen (MAType).
            period: MA-Periode (min 1).
            alpha_factor: Decay-Faktor für Alpha-MAs (E4); entfällt bei KAMA.
            volume: Volumen-Serie für VWMA (z. B. df['tick_volume']). Fehlt
                    sie oder ist sie Null/NaN, fällt VWMA auf SMA zurück (E5).
            smoothing: Optionale Alpha-EMA-Glättung (Vertrag B, 16.04 Schritt
                    5) auf die Basis-MA-Serie (alle 12 Typen anwendbar):
                      * smoothing > 1 (aktiv): ema_first = EMA(base,
                        span=smoothing); base = EMA(ema_first, alpha=alpha_calc)
                        mit alpha_calc = alpha_factor / (period + 1).
                      * smoothing <= 1: keine Glättung (Basis-Serie
                        unverändert, Default).

        Returns:
            pd.Series mit demselben Index wie `source`; die ersten
            `period - 1` Werte sind NaN (Warmup).
        """
        if source is None:
            return pd.Series(dtype=float)
        src = pd.to_numeric(source, errors="coerce")
        period_int = max(int(period), 1)
        values = src.to_numpy(dtype=float, na_value=np.nan)
        n = len(values)
        if n == 0:
            return pd.Series(index=src.index, dtype=float)

        alpha = float(alpha_factor) / (period_int + 1.0)

        key = str(ma_type or "").strip().upper()
        if key == "SMA":
            result = _sma_values(values, period_int)
        elif key == "EMA":
            result = _ema_span_values(values, period_int)
        elif key == "WMA":
            result = _wma_values(values, period_int)
        elif key == "DEMA":
            result = _dema_values(values, period_int, alpha)
        elif key == "TEMA":
            result = _tema_values(values, period_int, alpha)
        elif key == "HMA":
            result = _hma_values(values, period_int)
        elif key == "EHMA":
            result = _ehma_values(values, period_int, alpha)
        elif key == "ZLEMA":
            result = _zlema_values(values, period_int)
        elif key == "RMA":
            result = _rma_values(values, period_int)
        elif key == "KAMA":
            result = _kama_values(values, period_int)
        elif key == "ALMA":
            result = _alma_values(values, period_int)
        elif key == "VWMA":
            if volume is None or len(volume) != n:
                result = _sma_values(values, period_int)  # E5-Fallback
            else:
                vol = pd.to_numeric(volume, errors="coerce").to_numpy(
                    dtype=float, na_value=np.nan
                )
                result = _vwma_values(values, vol, period_int)
        else:
            raise ValueError(
                f"Unbekannter MA-Typ '{ma_type}'. Gültig: {MA_TYPES}"
            )

        # Optionale Alpha-EMA-Glättung (Vertrag B, 16.04 Schritt 5):
        # zweifach verschachtelte EMA-Filterung auf die Basis-MA-Serie.
        # smoothing > 1 = aktiv; smoothing <= 1 = keine Glättung.
        smoothing_int = max(int(smoothing or 0), 0)
        if smoothing_int > 1:
            ema_first = _ema_span_values(result, smoothing_int)
            result = _ema_alpha_values(ema_first, alpha)

        return pd.Series(result, index=src.index, dtype=float)

    # ------------------------------------------------------------ Darstellung
    @staticmethod
    def build_color_series(
        ma_series: pd.Series,
        dual_color: bool,
        bull_color: str,
        bear_color: str,
    ) -> List[str]:
        """Färbt die MA-Serie gemäß dual_color-Semantik (E6).

        - dual_color=False: durchgehend bull_color.
        - dual_color=True: ma_t >= ma_{t-1} -> bull_color, sonst bear_color.
        - NaN-Vergleiche (Warmup) gelten als bull_color (defensiv).
        - Index 0 hat keinen Vorgänger -> bull_color.
        """
        n = len(ma_series)
        if n == 0:
            return []
        if not dual_color:
            return [str(bull_color)] * n
        values = pd.to_numeric(ma_series, errors="coerce").to_numpy(
            dtype=float, na_value=np.nan
        )
        diff = np.diff(values)  # len n-1; NaN propagiert
        is_up = np.ones(n, dtype=bool)
        finite = ~np.isnan(diff)
        is_up[1:] = np.where(finite, diff >= 0.0, True)
        return np.where(is_up, str(bull_color), str(bear_color)).tolist()

    @staticmethod
    def build_chart_payload(
        time_series: pd.Series,
        ma_series: pd.Series,
        colors: List[str],
    ) -> List[Dict[str, Any]]:
        """Baut ein LWC-v5-kompatibles Objekt-Array (Ergänzung 3).

        Vertrag:
          * [{"time": int(epoch-Sekunden, Wanduhr), "value": float,
             "color": str}, ...]
          * Zeilen mit NaN/None in time oder value werden übersprungen
            (Warmup period-1).
          * Längen-Mismatch (len(colors) < len(ma_series)) wird defensiv
            toleriert: fehlende Farbe fällt auf bull_color zurück.
        """
        payload: List[Dict[str, Any]] = []
        n = len(ma_series)
        if n == 0:
            return payload
        times = time_series.to_numpy()
        values = pd.to_numeric(ma_series, errors="coerce").to_numpy(
            dtype=float, na_value=np.nan
        )
        default_color = str(colors[0]) if colors else _DEFAULT_BULL_COLOR
        for i in range(n):
            try:
                ts = int(times[i])
            except (TypeError, ValueError):
                continue
            v = values[i]
            if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
                continue
            color = str(colors[i]) if i < len(colors) and colors[i] else default_color
            payload.append({"time": ts, "value": float(v), "color": color})
        return payload

```

--------------------------------------------------

### DATEI: chart/js/01_core.js
```js
// chart/js/01_core.js
// Kern-Variablen, WebChannel-Bridge, Fenster-Fokus-Event & Fehlerbehandlung

window.onerror = function(m, s, l, c, e) {
    if (m === "Script error." && !s) return true;
    console.error(`[JS ERROR] ${m} | L${l}:${c}`);
    return true;
};

let chart = null, candleSeries = null, pyBridge = null, isUpdatingChart = false;
let currentTfInSeconds = 3600, lastClosePrice = null, activeTimer = null, countdownTimer = null;
let rawCandleData = [], currentSymbol = null, currentTimeframe = null;
let gridPriceLines = [], dayLinesSeries = [];
// Proximity-Circles: je Level-Preis eine unsichtbare LineSeries (Datenpunkte
// exakt auf dem Level) + SeriesMarkers-Plugin -> Circles liegen auf den
// Liq-Lines statt auf der Bar (native Engine-Positionierung, kein CSS-Overlay).
let _circleSeries = [], _circleMarkerPlugins = [];
// P14-03-E: Circle-Cache für Merged-Render (historische + Live-Circles).
// Wird in applyFullChartUpdate() aus data.chartRenderPayload.hit_circles
// (P16.05) befüllt; applyLiveOverlays() ersetzt nur die Live-Zeit-Einträge
// und rendert den Cache neu.
let _gridCirclesCache = [];
// P14-03-E (Flacker-Fix): Level-Registry für INKREMENTELLES Circle-Rendering.
// renderGridCircles() aktualisiert nur veränderte Level per setData/setMarkers,
// statt alle Serien via removeSeries/addSeries zu entfernen und neu aufzubauen –
// dieser Full-Layer-Rebuild pro Live-Tick (sobald die Proximity-Bedingung erfüllt
// war) verursachte das Live-Flackern. Schluessel = String(c.price).
let _circleLevelSeries = {};
// P16.05 (Prework Schritt 2, P-D2): Registry für Zeitreihen-LineSeries
// (z. B. Multi-MA). renderLineSeries() pflegt je Linie eine LWC-LineSeries
// unter `_activeLineSeries[id]` – incrementelles setData für vorhandene IDs,
// chart.removeSeries() für verschwundene IDs (kein Full-Layer-Rebuild).
let _activeLineSeries = {};
// P14-03-E (Flacker-Fix): Change-Detection für Live-Circles. Identische Circle-
// Sets zwischen Ticks (gleiche Level-Hits, gleiche Farbe) lösen KEINEN Re-Render
// aus – sonst re-rendert jeder Tick mit erfüllter Bedingung den ganzen Layer.
let _lastLiveCirclesJson = '[]';
// P14-03-E (Flacker-Fix): Live-Zeit der letzten Live-Overlay-Anwendung. Beim
// Wechsel auf eine neue Live-Bar werden auch die Kreise der VORHERIGEN Live-Zeit
// aus dem Cache entfernt (sonst bleiben veraltete Live-Kreise der Vor-Bar bis zum
// Refresh sichtbar). Wird in applyFullChartUpdate auf null zurückgesetzt.
let _lastLiveOverlayTime = null;
let currentPriceLine = null, resizeTimeout = null;
let currentPrecision = 2;
let pendingRange = null;
let _updateId = 0;
let _lastAppliedUpdateId = 0; // höchste akzeptierte updateId (Race-Guard)
let _continuousTimeMap = {};  // { cont_time: real_epoch } für tickMarkFormatter
let _continuousKeys = [];     // sortierte cont-Schlüssel für resolveRealTime()

let isWindowActive = true;
let lastRenderedPrice = null;
let lastRenderedTop = null;
let lastFormattedPriceStr = "";
let lastFormattedTimeStr = "";

const TF_SECONDS_MAP = { 'M1': 60, 'M2': 120, 'M5': 300, 'M10': 600, 'M15': 900, 'M30': 1800, 'H1': 3600, 'H4': 14400, 'D1': 86400, 'W1': 604800, 'MN1': 2592000 };
// HINWEIS: TF_SECONDS_MAP wird bei jedem applyFullChartUpdate durch die von
// Python mitgelieferte tfSecondsMap (Single Source of Truth) überschrieben.
// Diese lokale Map ist nur der Offline-/Start-Default (Abwärtskompatibilität).

// HINWEIS: resolveRealTime()/toReal()/toCont()/_rebuildTimeMaps() sind nach
// 02_time_utils.js verschoben – das ist die EINZIGE Zeit-Mapping-Schnittstelle.

if (typeof qt !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function(channel) {
        pyBridge = channel.objects.pyBridge;
    });
}

window.addEventListener('focus', () => { isWindowActive = true; if(lastClosePrice !== null) updateCountdownDisplay(); });
window.addEventListener('blur', () => { isWindowActive = false; });
document.addEventListener('visibilitychange', () => {
    isWindowActive = !document.hidden;
    if (isWindowActive && lastClosePrice !== null) updateCountdownDisplay();
});

```

--------------------------------------------------

### DATEI: chart/js/02_time_utils.js
```js
// chart/js/02_time_utils.js
// Zeit-Formatierung für die Chart-Achsen (Wanduhrzeit direkt aus dem Epoch) +
// ZENTRALE Zeit-Konstanten & Zeit-Mapping-Helper (Single Source of Truth).
//
// WICHTIG (empirisch verifiziert via test/check_broker_tz.py, DB-Abgleich &
// Live-Messung an MT5):
// - MT5 liefert Zeiten als BERLIN-WANDUHR-encoded Epochs: Bei echter UTC 10:00
//   ist tick.time bereits die Zahl "12:00" (diff = +7200s). Der User hat recht.
// - sync_market_data() schreibt die Roh-Epochs via
//   pd.to_datetime(..., unit="s", utc=True) 1:1 in die DB; EXTRACT(EPOCH) und
//   fetch_historical_candles() geben exakt diese Roh-Epochs an den Chart.
// => Eine zusätzliche Berlin-Offset-Umrechnung (+2h/+1h) wäre DOPPELT und
//    würde alle Achsen-Labels 2h zu spät anzeigen.
// => getBerlinParts formatiert den Epoch direkt über die UTC-Getter; der Wert
//    IST bereits die gewünschte Wanduhrzeit. Das ist automatisch DST-robust
//    (keine Saison-Logik nötig): Im Winter liefert der Broker CET-encoded
//    Werte, die ebenfalls direkt korrekt dargestellt werden.

// =============================================================================
// ZENTRALE ZEIT-KONSTANTEN (keine magischen Zahlen im restlichen Code)
// =============================================================================
const SECONDS_PER_DAY = 86400;
const WEEKEND_GAP_SECONDS = 43200;   // >12h Lücke ohne Kerzen = Wochenend-Gap
const MIN_SEPARATOR_SPACING_SECONDS = 21600; // Mindestabstand zweier Trennlinien

function getBerlinParts(t) {
    var weekdays = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
    var pad = function(n) { return String(n).padStart(2, '0'); };
    
    // Ungueltige Eingaben abfangen (verhindert NaN-Ausgabe & Endlosschleifen)
    if (typeof t !== 'number' || !isFinite(t)) {
        return { weekday: '', day: '--', month: '--', year: '----', hour: '--', minute: '--', rawDayOfWeek: -1 };
    }
    
    // Roh-Epoch = bereits Berliner Wanduhrzeit => direkt via UTC-Getter lesen.
    var bd = new Date(t * 1000);
    
    return {
        weekday: weekdays[bd.getUTCDay()],
        day: pad(bd.getUTCDate()),
        month: pad(bd.getUTCMonth() + 1),
        year: String(bd.getUTCFullYear()),
        hour: pad(bd.getUTCHours()),
        minute: pad(bd.getUTCMinutes()),
        rawDayOfWeek: bd.getUTCDay()
    };
}

function formatDT(t) { 
    var p = getBerlinParts(t); 
    return p.weekday + ' ' + p.day + '.' + p.month + '.' + p.year.slice(-2) + ' ' + p.hour + ':' + p.minute; 
}

// =============================================================================
// ZEIT-MAPPING (kontinuierliche Fake-Zeit <-> echte epoch)
// -----------------------------------------------------------------------------
// Die Charts arbeiten auf kontinuierlicher Zeit (base_time + i*tf_sec), damit
// keinerlei Lücken/Whitespace entstehen. Die _continuousTimeMap (cont->real)
// wird aus Python mitgeliefert (data.timeMap). Diese Funktionen sind die
// EINZIGE Schnittstelle zum Zeit-Mapping – kein roher Map-Zugriff im Rest.
//
// INVARIANTE: Das Mapping ist bijektiv (jede Candle hat genau eine cont-Zeit
// und genau eine real-Epoch) und monoton steigend (cont & real wachsen
// gemeinsam). Verletzungen erzeugen Fake-Labels an Tagesgrenzen.
// =============================================================================
let _realToContMap = {};  // { real_epoch: cont_time } – invers zu _continuousTimeMap

function _rebuildTimeMaps(timeMap) {
    // Setzt beide Maps aus der von Python gelieferten cont->real Map.
    _continuousTimeMap = timeMap || {};
    _continuousKeys = Object.keys(_continuousTimeMap).map(Number).sort(function(a, b) { return a - b; });
    _realToContMap = {};
    for (var i = 0; i < _continuousKeys.length; i++) {
        var contKey = _continuousKeys[i];
        _realToContMap[_continuousTimeMap[contKey]] = contKey;
    }
}

// =============================================================================
// resolveRealTime(): kontinuierliche (Fake-)Zeit -> echte epoch
// WICHTIG: Bei unbekannten Werten (Padding-Ticks ausserhalb des Datensatzes)
// NIE die Fake-Zeit selbst zurueckgeben – sonst zeigt die Zeitachse
// irrefuehrende Labels (z. B. "30.7.26 23:58" an der Tagesgrenze, weil die
// Fake-Zeit der 00:59-Candle als Realzeit formatiert wird).
// Stattdessen wird der naechstgelegene bekannte Zeitpunkt verwendet.
// =============================================================================
function resolveRealTime(ts) {
    if (ts === null || ts === undefined || typeof ts !== 'number' || !isFinite(ts)) return ts;
    var direct = _continuousTimeMap[ts];
    if (direct !== undefined) return direct;
    if (_continuousKeys.length === 0) return ts;
    var n = _continuousKeys.length;
    if (ts <= _continuousKeys[0]) return _continuousTimeMap[_continuousKeys[0]];
    if (ts >= _continuousKeys[n - 1]) return _continuousTimeMap[_continuousKeys[n - 1]];
    var lo = 0, hi = n - 1;
    while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (_continuousKeys[mid] === ts) return _continuousTimeMap[_continuousKeys[mid]];
        if (_continuousKeys[mid] < ts) lo = mid + 1; else hi = mid - 1;
    }
    // hi = letzter Key < ts, lo = erster Key > ts
    var a = _continuousKeys[hi], b = _continuousKeys[lo];
    return (ts - a <= b - ts) ? _continuousTimeMap[a] : _continuousTimeMap[b];
}

// Alias mit sprechendem Namen – überall verwenden, wo echte Zeit gebraucht wird.
function toReal(ts) { return resolveRealTime(ts); }

// echte epoch -> kontinuierliche Zeit (inverse Zuordnung).
// Liefert undefined, wenn die real-Epoch nicht im Datensatz liegt.
function toCont(realEpoch) { return _realToContMap[realEpoch]; }

```

--------------------------------------------------

### DATEI: chart/js/03_chart_rendering.js
```js
// chart/js/03_chart_rendering.js
// Chart-Initialisierung (leer – chart wird via applyFullChartUpdate aus Python erstellt),
// Tages-Separatoren, Grid-Linien/Marker & Range-Steuerung

function clearGridLines() {
    if (!candleSeries) return;
    gridPriceLines.forEach(function(l) { try { candleSeries.removePriceLine(l); } catch(e){} });
    gridPriceLines = [];
}

// P16.03-Bugfix: Python-Linienart (lowercase: solid/dashed/dotted/dashdotted)
// auf LWC-v5-LineStyle mappen. 'dashdotted' -> LargeDashed (beste Naeherung).
function _lwcLineStyle(styleName) {
    switch ((styleName || 'solid').toLowerCase()) {
        case 'dashed': return LightweightCharts.LineStyle.Dashed;
        case 'dotted': return LightweightCharts.LineStyle.Dotted;
        case 'dashdotted': return LightweightCharts.LineStyle.LargeDashed;
        case 'solid':
        default: return LightweightCharts.LineStyle.Solid;
    }
}

// P16.05 (Prework Schritt 2, F1/P-D2/P-D3): Generisches Preislinien-Primitiv.
// Zeichnet horizontale Preislinien (Grid-Legacy) via candleSeries.createPriceLine.
// Legacy-Alias renderGridLines() bleibt für Abwärtskompatibilität (P-D3).
function renderPriceLines(lines) {
    clearGridLines();
    if (!candleSeries || !lines) return;
    var data = (typeof lines === 'string') ? JSON.parse(lines) : lines;
    (data || []).forEach(function(l) {
        if (l && typeof l.price === 'number' && !isNaN(l.price)) {
            var pl = candleSeries.createPriceLine({
                price: l.price, color: l.color, lineWidth: l.width,
                lineStyle: _lwcLineStyle(l.style), axisLabelVisible: true,
                title: l.is_custom ? '\u2605' : ''
            });
            gridPriceLines.push(pl);
        }
    });
}
function renderGridLines(lines) { renderPriceLines(lines); }

// NOTE: Die Proximity-Circles werden auf der ZUGEHOERIGEN LIQ-LINE geplottet:
// Je Level-Preis wird eine UNSICHTBARE LineSeries erzeugt (lineVisible:false,
// autoscaleInfoProvider:null, rechte Preisskala), deren Datenpunkte exakt auf
// dem Level-Preis liegen. Die Circle-Marker (Standard-Marker der Engine, shape
// 'circle') haengen an dieser Serie -> die Engine positioniert sie direkt auf
// der Liq-Line. Das folgt Zoom/Scroll/Resize nativ (kein CSS-Overlay, kein
// Redraw-Bug).
function clearGridCircles() {
    for (var i = 0; i < _circleSeries.length; i++) {
        try { chart.removeSeries(_circleSeries[i]); } catch(e) {}
    }
    _circleSeries = [];
    _circleMarkerPlugins = [];
    _circleLevelSeries = {};
}

// P14-03-E (Flacker-Fix): renderGridCircles() ist jetzt INKREMENTELL. Bestehende
// Level-Serien werden per setData/setMarkers in-place aktualisiert; nur ver-
// schwundene Level werden entfernt, nur neue erzeugt. Kein removeSeries/addSeries
// für unveränderte Level => kein Full-Layer-Rebuild pro Live-Tick (bisher rief
// jede applyLiveOverlays renderGridCircles -> clearGridCircles auf, das ALLE
// Circle-Serien wegwarf und neu aufbaute = Flackern bei erfüllter Proximity).
// P16.05 (Prework Schritt 2, P-D2/P-D3): Generisches Marker-Primitiv.
// Übernimmt die bestehende inkrementelle Circle-Logik (je Level-Preis eine
// unsichtbare LineSeries + SeriesMarkers-Plugin). renderGridCircles() bleibt
// als Legacy-Alias für den Live-Overlay-Pfad (P-C4) erhalten (P-D3).
function renderMarkers(circles) {
    if (!chart || !circles) return;
    var data = (typeof circles === 'string') ? JSON.parse(circles) : circles;
    if (!data || data.length === 0) {
        clearGridCircles();
        return;
    }

    // Nach Level-Preis gruppieren: LWC-Serien brauchen eindeutige Zeiten,
    // daher je Level eine Serie (im selben Level gibt es max. 1 Treffer/Bar).
    var byLevel = {};
    for (var i = 0; i < data.length; i++) {
        var c = data[i];
        if (!c || typeof c.time !== 'number' || isNaN(c.time) ||
            typeof c.price !== 'number' || isNaN(c.price)) continue;
        var key = String(c.price);
        if (!byLevel[key]) byLevel[key] = [];
        byLevel[key].push(c);
    }

    // 1) Level entfernen, die im neuen Satz nicht mehr existieren – OHNE den
    //    Rest anzutasten.
    for (var oldKey in _circleLevelSeries) {
        if (!byLevel[oldKey]) {
            var gone = _circleLevelSeries[oldKey];
            try { if (gone.series) chart.removeSeries(gone.series); } catch(e) {}
            var gidx = _circleSeries.indexOf(gone.series);
            if (gidx >= 0) _circleSeries.splice(gidx, 1);
            if (gone.plugin) {
                var pidx = _circleMarkerPlugins.indexOf(gone.plugin);
                if (pidx >= 0) _circleMarkerPlugins.splice(pidx, 1);
            }
            delete _circleLevelSeries[oldKey];
        }
    }

    // 2) Upsert pro Level: existierende Serie in-place aktualisieren.
    var keys = Object.keys(byLevel);
    for (var j = 0; j < keys.length; j++) {
        var levelCircles = byLevel[keys[j]];
        // LWC v5: Markers und Serie brauchen NACH ZEIT SORTIERTE Daten.
        levelCircles.sort(function(a, b) { return a.time - b.time; });

        var sd = [];
        var markers = [];
        for (var k = 0; k < levelCircles.length; k++) {
            var cc = levelCircles[k];
            // Datenpunkt exakt auf dem Level-Preis -> Marker der Engine
            // erscheint auf der zugehoerigen Liq-Line.
            sd.push({ time: cc.time, value: cc.price });
            markers.push({
                time: cc.time,
                position: 'inBar',
                color: cc.color || '#E91E63',
                // P16.03-Bugfix: Form/Groesse aus dem Python-Payload uebernehmen
                // (vorher hart 'circle'/1) - die Auswahl im StylePickerWidget
                // (circle/square/arrowUp/arrowDown) wirkt damit endlich.
                shape: cc.shape || 'circle',
                size: (cc.size && cc.size > 0) ? cc.size : 1,
                priority: 10
            });
        }

        var key = keys[j];
        var existing = _circleLevelSeries[key];
        if (existing) {
            // Inkrementell: Serie/Plugin existiert bereits -> nur Daten ersetzen
            // (kein removeSeries/addSeries -> kein Flackern).
            try { existing.series.setData(sd); } catch(e) { continue; }
            if (existing.plugin) {
                try { existing.plugin.setMarkers(markers); } catch(e) { continue; }
            }
        } else {
            var series = null;
            try {
                series = chart.addSeries(LightweightCharts.LineSeries, {
                    lineVisible: false,
                    pointMarkersVisible: false,
                    lastValueVisible: false,
                    priceLineVisible: false,
                    crosshairMarkerVisible: false,
                    color: 'rgba(0,0,0,0)',
                    priceScaleId: 'right',
                    autoscaleInfoProvider: function() { return null; }
                });
            } catch(e) { continue; }

            var plugin = null;
            try {
                plugin = LightweightCharts.createSeriesMarkers(series, []);
            } catch(e) { plugin = null; }

            _circleLevelSeries[key] = { series: series, plugin: plugin };
            _circleSeries.push(series);
            if (plugin) _circleMarkerPlugins.push(plugin);

            try { series.setData(sd); } catch(e) { continue; }
            if (plugin) {
                try { plugin.setMarkers(markers); } catch(e) {}
            }
        }
    }
}
function renderGridCircles(circles) { renderMarkers(circles); }

// P16.05 (Prework Schritt 2, P-D2): Generisches Zeitreihen-Linien-Primitiv.
// Pflegt eine Registry `_activeLineSeries[id]`: vorhandene LineSeries werden
// per setData() in-place aktualisiert (incrementell, kein Flackern), IDs, die
// im neuen Payload nicht mehr vorkommen, werden per chart.removeSeries()
// entfernt. `data` ist direkt LWC-v5-setData-Input ([{time, value, color}]
// mit optionalem Pro-Punkt-color – v5-konform, P16.04 build_chart_payload).
function renderLineSeries(linesArray) {
    if (!chart || !linesArray) return;
    var data = (typeof linesArray === 'string') ? JSON.parse(linesArray) : linesArray;
    if (!data || data.length === 0) {
        // Kein Linien-Eintrag -> alle aktiven Zeitreihen-Serien entfernen.
        for (var lid in _activeLineSeries) {
            if (Object.prototype.hasOwnProperty.call(_activeLineSeries, lid)) {
                try { if (_activeLineSeries[lid]) chart.removeSeries(_activeLineSeries[lid]); } catch(e) {}
            }
        }
        _activeLineSeries = {};
        return;
    }

    // 1) IDs entfernen, die im neuen Satz nicht mehr existieren.
    var newIds = {};
    for (var n = 0; n < data.length; n++) {
        var l0 = data[n];
        if (l0 && l0.id) newIds[l0.id] = true;
    }
    for (var oldId in _activeLineSeries) {
        if (Object.prototype.hasOwnProperty.call(_activeLineSeries, oldId) && !newIds[oldId]) {
            try { if (_activeLineSeries[oldId]) chart.removeSeries(_activeLineSeries[oldId]); } catch(e) {}
            delete _activeLineSeries[oldId];
        }
    }

    // 2) Upsert pro Linie.
    for (var m = 0; m < data.length; m++) {
        var line = data[m];
        if (!line || !line.id || !line.data) continue;
        var series = _activeLineSeries[line.id];
        if (!series) {
            try {
                series = chart.addSeries(LightweightCharts.LineSeries, {
                    lineWidth: (line.width && line.width > 0) ? line.width : 1,
                    lineStyle: _lwcLineStyle(line.style),
                    color: line.color || '#26A69A',
                    lastValueVisible: false,
                    priceLineVisible: false,
                    crosshairMarkerVisible: false,
                    priceScaleId: 'right'
                });
                _activeLineSeries[line.id] = series;
            } catch(e) { continue; }
        }
        // Daten ersetzen (inkl. optionaler Pro-Punkt-Farbe für dual_color-MAs).
        try { series.setData(line.data); } catch(e) { continue; }
        // Style-Änderungen (width/style/color) nachziehen.
        try {
            series.applyOptions({
                lineWidth: (line.width && line.width > 0) ? line.width : 1,
                lineStyle: _lwcLineStyle(line.style),
                color: line.color || '#26A69A'
            });
        } catch(e) {}
    }
}

// P16.05 (Prework Schritt 2, P-D1/F1): Generische Render-Pipeline – die
// Haupt-Schnittstelle, die das aggregierte Indikator-Payload 1:1 an die
// Grafik-Primitive routet:
//   payload.price_lines -> renderPriceLines() (horizontale Preislinien)
//   payload.lines       -> renderLineSeries() (Zeitreihen-LineSeries)
//   payload.hit_circles -> renderMarkers()    (Marker/Circles)
// Keys werden nur geroutet, wenn sie im Payload vorhanden sind (leere Arrays
// clearen den jeweiligen Layer). Kein Feld-Dispatch, kein kind-Feld (F1).
function applyChartRenderPayload(payload) {
    if (!chart || !candleSeries) return;
    var p = (typeof payload === 'string') ? JSON.parse(payload) : (payload || {});
    if (Object.prototype.hasOwnProperty.call(p, 'price_lines')) {
        try { renderPriceLines(p.price_lines || []); } catch(e) {
            console.warn('[applyChartRenderPayload] price_lines fehlgeschlagen:', e.message || e);
        }
    }
    if (Object.prototype.hasOwnProperty.call(p, 'lines')) {
        try { renderLineSeries(p.lines || []); } catch(e) {
            console.warn('[applyChartRenderPayload] lines fehlgeschlagen:', e.message || e);
        }
    }
    if (Object.prototype.hasOwnProperty.call(p, 'hit_circles')) {
        try { renderMarkers(p.hit_circles || []); } catch(e) {
            console.warn('[applyChartRenderPayload] hit_circles fehlgeschlagen:', e.message || e);
        }
    }
}

function applyRange(rangeFrom, rangeTo, priceFrom, priceTo) {
    if (!chart) return;
    var timeScale = chart.timeScale();
    var priceScale = chart.priceScale('right');

    if (rangeFrom && rangeTo && rangeFrom !== rangeTo) {
        try {
            timeScale.setVisibleLogicalRange({ from: Number(rangeFrom), to: Number(rangeTo) });
        } catch(e) {
            console.warn("[applyRange] Failed to set logical range:", e);
            try { timeScale.fitContent(); } catch(e2) {}
        }
    } else {
        try { timeScale.fitContent(); } catch(e) {}
    }

    if (priceFrom !== undefined && priceTo !== undefined && priceFrom !== priceTo) {
        try { priceScale.setVisibleRange({ from: Number(priceFrom), to: Number(priceTo) }); } catch(e) {}
    }
}

// =============================================================================
// Tages-Separatoren – GEKAPSELTES MODUL (DaySeparator)
// -----------------------------------------------------------------------------
// API:
//   DaySeparator.render(candleData)   – Trennlinien aus Candle-Daten berechnen
//                                       und als CSS-Overlay zeichnen (0:00 der
//                                       ersten Kerze des neuen Tages)
//   DaySeparator.updatePositions()    – Positionen nach Scroll/Zoom/Resize neu
//                                       berechnen (rein additiv, keine Änderung
//                                       der Zeitskala)
//   DaySeparator.clear()              – alle Trennlinien entfernen
//
// Warum gekapselt: Zukünftige Chart-Änderungen (linke Preisskala, Pane-Layout,
// Zeitachse) berühren nur dieses Modul – der Rest des Codes kennt nur die API.
//
// Früher: LineSeries mit 2 Extrem-Punkten (-1000/1000000). Bei LWC v5 rendert
// eine fast senkrechte 2-Punkt-Linie den Dash NICHT zuverlässig (fällt auf
// Solid zurück – deshalb war die Linie "durchgezogen").
// Heute: rein additives CSS-Overlay (border-left: dashed). Garantiert
// gestrichelt, keine Änderung der Zeitskala, keine Phantom-Index-Slots.
// =============================================================================
var DaySeparator = (function() {
    var container = null;      // Overlay-Div über dem Chart-Pane
    var times = [];            // kontinuierliche Zeiten der Trennlinien (0:00)
    var lines = [];            // erzeugte Div-Elemente

    // Breite einer eventuellen linken Preisskala (aktuell keine im Chart,
    // aber robust vorbereitet – C3)
    function _leftPriceWidth() {
        try {
            var leftPS = chart.priceScale('left');
            if (!leftPS) return 0;
            var opts = leftPS.options();
            if (opts && opts.visible) {
                return leftPS.width() || 0;
            }
        } catch(e) {}
        return 0;
    }

    function _ensureContainer() {
        var host = document.getElementById('chart-container');
        if (!host) return null;
        if (!container) {
            container = document.createElement('div');
            container.style.position = 'absolute';
            container.style.top = '0';
            container.style.left = '0';
            container.style.pointerEvents = 'none';
            container.style.zIndex = '100';
            host.appendChild(container);
        }
        return container;
    }

    function clear() {
        if (container) container.innerHTML = '';
        times = [];
        lines = [];
    }

    // Kernlogik: Tageswechsel-Erkennung (pure Funktion, separat testbar)
    function computeDaySeparatorTimes(candleData) {
        var result = [];
        if (!candleData || candleData.length === 0) return result;
        var lastLineTime = 0;
        for (var i = 1; i < candleData.length; i++) {
            var prevTime = candleData[i - 1].time;
            var currTime = candleData[i].time;

            // Echte epoch für Wanduhr-Tag-Berechnung verwenden (toReal statt
            // rohem Map-Zugriff -> nie Fake-Zeiten bei fehlendem Mapping).
            // Die Roh-Epochs sind bereits Berlin-Wanduhr-encoded, daher ergibt
            // Math.floor(real/SECONDS_PER_DAY) den Wanduhr-Tag (Wechsel 00:00).
            var prevReal = toReal(prevTime);
            var currReal = toReal(currTime);

            var prevUtcDay = Math.floor(prevReal / SECONDS_PER_DAY);
            var currUtcDay = Math.floor(currReal / SECONDS_PER_DAY);

            var isUtcDayChange = (currUtcDay !== prevUtcDay);
            var isWeekendGap = (currReal - prevReal > WEEKEND_GAP_SECONDS);
            var isTooCloseToPrevious = (lastLineTime > 0 && (currTime - lastLineTime) < MIN_SEPARATOR_SPACING_SECONDS);

            if ((isUtcDayChange || isWeekendGap) && !isTooCloseToPrevious) {
                lastLineTime = currTime;
                // 0:00 des neuen Tages = Zeit der ersten Kerze des neuen Tages
                result.push(currTime);
            }
        }
        return result;
    }

    function render(candleData) {
        if (!chart) return;
        clear();
        if (currentTfInSeconds >= SECONDS_PER_DAY || !candleData || candleData.length === 0) return;

        times = computeDaySeparatorTimes(candleData);

        var sepContainer = _ensureContainer();
        if (!sepContainer) return;
        for (var j = 0; j < times.length; j++) {
            var div = document.createElement('div');
            div.style.position = 'absolute';
            div.style.top = '0';
            div.style.bottom = '0';
            div.style.width = '0';
            div.style.borderLeft = '1px dashed rgba(33, 150, 243, 0.55)';
            div.style.pointerEvents = 'none';
            sepContainer.appendChild(div);
            lines.push(div);
        }
        updatePositions();
    }

    // Positionen nach Scroll/Zoom/Resize neu berechnen.
    // - x = timeToCoordinate (relativ zum Chart-Pane) + linke Preisskala-Breite
    // - Offscreen-Zeiten (null von timeToCoordinate) werden ausgeblendet (C4)
    function updatePositions() {
        if (!chart || !container) return;
        try {
            var host = document.getElementById('chart-container');
            var leftW = _leftPriceWidth();
            var width = host ? host.clientWidth : 800;
            var height = host ? host.clientHeight : 600;
            var tsHeight = 0;
            try { tsHeight = chart.timeScale().height() || 0; } catch(e) { tsHeight = 0; }

            container.style.left = leftW + 'px';
            container.style.top = '0px';
            container.style.width = Math.max(0, width - leftW) + 'px';
            container.style.height = Math.max(0, height - tsHeight) + 'px';

            for (var i = 0; i < times.length && i < lines.length; i++) {
                var x = null;
                try { x = chart.timeScale().timeToCoordinate(times[i]); } catch(e) { x = null; }
                if (x === null || x === undefined || isNaN(x)) {
                    lines[i].style.display = 'none';
                } else {
                    lines[i].style.display = 'block';
                    lines[i].style.left = (x + leftW) + 'px';
                }
            }
        } catch(e) {
            console.warn('[DaySeparator.updatePositions] Error:', e);
        }
    }

    return {
        render: render,
        updatePositions: updatePositions,
        clear: clear,
        computeDaySeparatorTimes: computeDaySeparatorTimes
    };
})();

```

--------------------------------------------------

### DATEI: chart/js/04_live_updates.js
```js
// chart/js/04_live_updates.js
// Live-Tick-Updates, Countdown-Badge, Price-Badge, Range-Sync & Resize-Handling

function syncRanges() {
    if (!chart || !pyBridge || isUpdatingChart) return;
    try {
        var lr = chart.timeScale().getVisibleLogicalRange();
        if (lr && lr.from !== null && lr.to !== null && !isNaN(lr.from) && !isNaN(lr.to)) {
            // P16.07 (D10): Gesamt-Kerzenzahl mitliefern, damit Python den
            // Viewport offsetbasiert (Abstand vom rechten Rand) persistieren kann.
            pyBridge.onRangeChanged(Math.floor(lr.from), Math.floor(lr.to), rawCandleData.length);
        }
        var pr = chart.priceScale('right').getVisibleRange();
        if (pr && pr.from !== null && pr.to !== null && !isNaN(pr.from) && !isNaN(pr.to)) {
            pyBridge.onPriceRangeChanged(pr.from, pr.to);
        }
    } catch(e) {}
}

function updateCountdownDisplay() {
    if (isUpdatingChart || !candleSeries || !chart || lastClosePrice === null || lastClosePrice === undefined) return;
    if (!isWindowActive || document.hidden) return;

    try {
        var priceBadge = document.getElementById('price-badge');
        var countdownBadge = document.getElementById('countdown-badge');
        if (!priceBadge || !countdownBadge) return;

        var showCountdown = (currentTfInSeconds > 0 && currentTfInSeconds < 86400);

        // PriceLine auf der candleSeries
        if (!currentPriceLine) {
            currentPriceLine = candleSeries.createPriceLine({
                price: lastClosePrice,
                color: '#2962FF',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dotted,
                axisLabelVisible: false,
                title: ''
            });
            lastRenderedPrice = lastClosePrice;
        } else if (lastRenderedPrice !== lastClosePrice) {
            currentPriceLine.applyOptions({ price: lastClosePrice, title: '' });
            lastRenderedPrice = lastClosePrice;
        }

        var y = candleSeries.priceToCoordinate(lastClosePrice);
        if (y !== null && !isNaN(y)) {
            var formattedPrice = lastClosePrice.toFixed(currentPrecision);
            var topPos = (y - 9) + 'px';

            if (lastFormattedPriceStr !== formattedPrice) {
                priceBadge.innerText = formattedPrice;
                lastFormattedPriceStr = formattedPrice;
            }
            if (lastRenderedTop !== topPos) {
                priceBadge.style.top = topPos;
                countdownBadge.style.top = topPos;
                lastRenderedTop = topPos;
            }
            if (priceBadge.style.display !== 'block') {
                priceBadge.style.display = 'block';
            }

            if (showCountdown) {
                var now = Math.floor(Date.now() / 1000);
                var rem = currentTfInSeconds - (now % currentTfInSeconds);
                var formattedTime = String(Math.floor(rem/60)).padStart(2,'0') + ':' + String(rem%60).padStart(2,'0');
                if (lastFormattedTimeStr !== formattedTime) {
                    countdownBadge.innerText = formattedTime;
                    lastFormattedTimeStr = formattedTime;
                }
                var priceWidth = priceBadge.offsetWidth || 50;
                var rightPos = (priceWidth + 8) + 'px';
                if (countdownBadge.style.right !== rightPos) {
                    countdownBadge.style.right = rightPos;
                }
                if (countdownBadge.style.display !== 'block') {
                    countdownBadge.style.display = 'block';
                }
            } else {
                if (countdownBadge.style.display !== 'none') countdownBadge.style.display = 'none';
            }
        } else {
            if (priceBadge.style.display !== 'none') priceBadge.style.display = 'none';
            if (countdownBadge.style.display !== 'none') countdownBadge.style.display = 'none';
        }
    } catch(e) {
        var p = document.getElementById('price-badge');
        var c = document.getElementById('countdown-badge');
        if (p && p.style.display !== 'none') p.style.display = 'none';
        if (c && c.style.display !== 'none') c.style.display = 'none';
    }
}

function updateLiveCandle(json) {
    if (!candleSeries || isUpdatingChart) return;
    try {
        var c = JSON.parse(json);
        if (!c || typeof c.time !== 'number' || isNaN(c.time)) return;
        // Race-Guard: Live-Tick nur anwenden, wenn Symbol/TF noch zum Chart passen.
        // Verhindert, dass ein verspaeteter Tick vom alten Symbol/TF nach einem
        // schnellen Wechsel an den falschen Chart angehaengt wird.
        if (c.symbol !== undefined && c.symbol !== null && c.symbol !== currentSymbol) return;
        if (c.timeframe !== undefined && c.timeframe !== null && c.timeframe !== currentTimeframe) return;
        if (c.open === null || c.high === null || c.low === null || c.close === null) return;
        if (rawCandleData.length > 0 && c.time < rawCandleData[rawCandleData.length-1].time) return;
        // P16.07 (D9): Befindet sich der Viewport in der Historie (nicht am
        // Live-Ende), wird der Tick unterdrückt (stummer Tier-2-Update) –
        // der Scroll-Fokus zuckt nicht. Der „Live"-Button springt zurück.
        if (window._isHistoryView && window._isHistoryView()) return;
        candleSeries.update(c);
        lastClosePrice = c.close;
        updateCountdownDisplay();

                // P14-03-E (D.3): GENERISCHES LIVE-OVERLAY RENDERING – Dispatcher routet
        // je kind (Open/Closed), ohne kompletten Chart-Rebuild und ohne die
        // historischen Overlays zu verwerfen. 22.01c (Bugfix 1): IMMER aufrufen
        // (auch mit leerem Satz), damit alte Live-Circles aus dem Cache fallen,
        // sobald ein Overlay-Serie deaktiviert wird (z. B. Grabber-Button aus
        // -> keine Peak-SL-Kreise mehr sichtbar).
        applyLiveOverlays(c.overlays || []);
    } catch(e) {}
}

// P14-03-E: Generischer Overlay-Dispatcher. Spätere Indikator-Plugins docken
// über neue kind/layer-Werte an, ohne updateLiveCandle zu ändern.
function applyLiveOverlays(overlays) {
    if (typeof renderGridCircles !== 'function') return;
    var circles = [];
    for (var i = 0; i < (overlays || []).length; i++) {
        var o = overlays[i];
        if (o && o.kind === 'circle' && typeof o.time === 'number' &&
            typeof o.price === 'number' && !isNaN(o.time) && !isNaN(o.price)) {
            circles.push(o);
        }
    }
    // P14-03-E (Flacker-Fix): Change-Detection – wenn sich der Live-Circle-Satz
    // gegenüber dem letzten Tick NICHT geändert hat (gleiche Level-Hits, gleiche
    // Farben), wird kein Re-Render ausgelöst. Identische Sichtbarkeit, aber kein
    // Canvas-Rebuild -> behebt das Tick-Flackern bei erfüllter Proximity.
    // 22.01c: Auch der LEERE Satz wird erfasst – der erste leere Aufruf nach
    // aktiven Overlays räumt die alten Live-Circles auf, weitere bleiben stumm.
    var nowJson = JSON.stringify(circles);
    if (nowJson === _lastLiveCirclesJson) return;
    _lastLiveCirclesJson = nowJson;

    // Merged-Render: nur die Live-Zeit ersetzen, historische Circles behalten.
    // 22.01c: Kein Live-Circle mehr -> alte Live-Zeit (falls bekannt) entfernen.
    var liveTime = (circles.length > 0) ? circles[0].time : _lastLiveOverlayTime;
    if (liveTime === null) {
        renderGridCircles(_gridCirclesCache);
        return;
    }
    // P14-03-E: Bei neuer Live-Bar zusätzlich die Kreise der VORHERIGEN Live-Zeit
    // entfernen (sonst bleiben veraltete Live-Kreise der Vor-Bar im Cache hängen).
    if (_lastLiveOverlayTime !== null && _lastLiveOverlayTime !== liveTime) {
        _gridCirclesCache = _gridCirclesCache.filter(function(x) { return x.time !== _lastLiveOverlayTime; });
    }
    _lastLiveOverlayTime = liveTime;
    _gridCirclesCache = _gridCirclesCache.filter(function(x) { return x.time !== liveTime; });
    for (var j = 0; j < circles.length; j++) { _gridCirclesCache.push(circles[j]); }
    renderGridCircles(_gridCirclesCache);
}

function fitChartContent() { if(chart) chart.timeScale().fitContent(); }

// =============================================================================
// RESIZE-HANDLING
// =============================================================================
function handleResize() {
    if (!chart) return;
    var container = document.getElementById('chart-container');
    if (!container) return;
    var w = container.clientWidth;
    var h = container.clientHeight;
    if (w > 0 && h > 0) {
        chart.resize(w, h);
        try { DaySeparator.updatePositions(); } catch(e) {}
        try { Measurement.updatePositions(); } catch(e) {}
    }
}

var _resizeObserver = null;
function setupResizeObserver() {
    var container = document.getElementById('chart-container');
    if (!container) return;
    if (_resizeObserver) _resizeObserver.disconnect();
    _resizeObserver = new ResizeObserver(function() { handleResize(); });
    _resizeObserver.observe(container);
}

// =============================================================================
// applyFullChartUpdate – Hauptfunktion
// =============================================================================
function applyFullChartUpdate(data) {
    // =========================================================================
    // RACE-GUARD: Python sendet eine monotone updateId mit jedem Refresh.
    // Veraltete Payloads (z. B. langsamer Serializer-Thread aus einem frueheren
    // Symbol/TF-Stand) werden sofort verworfen, bevor sie den Chart anfassen.
    // =========================================================================
    var myId = ++_updateId;
    var updateId = (data && typeof data.updateId === 'number') ? data.updateId : myId;

    if (updateId < _lastAppliedUpdateId) {
        console.warn('[applyFullChartUpdate] Veraltetes Update verworfen (id=' + updateId + ' < letzte=' + _lastAppliedUpdateId + ')');
        isUpdatingChart = false;
        return;
    }
    _lastAppliedUpdateId = updateId;

    try {
        isUpdatingChart = true;

        // TimeMap speichern (kontinuierliche Zeit -> echte epoch)
        // Zentral via _rebuildTimeMaps: baut auch die inverse real->cont Map auf.
        _rebuildTimeMaps(data.timeMap || {});

        // TF_SECONDS_MAP: Python ist die Single Source of Truth (tfSecondsMap im
        // Payload). Die lokale Map in 01_core.js ist nur der Offline-Default.
        if (data.tfSecondsMap && typeof data.tfSecondsMap === 'object') {
            for (var tfKey in data.tfSecondsMap) {
                if (Object.prototype.hasOwnProperty.call(data.tfSecondsMap, tfKey)) {
                    TF_SECONDS_MAP[tfKey] = data.tfSecondsMap[tfKey];
                }
            }
        }

        currentSymbol = data.symbol;
        currentTimeframe = data.timeframe;
        if (data.timeframe && TF_SECONDS_MAP[data.timeframe]) {
            currentTfInSeconds = TF_SECONDS_MAP[data.timeframe];
        }

        var candles = (typeof data.candles === 'string') ? JSON.parse(data.candles) : (data.candles || []);

        var validCandles = candles.filter(function(c) {
            return c &&
                typeof c.time === 'number' && !isNaN(c.time) && c.time > 0 &&
                typeof c.open === 'number' && !isNaN(c.open) && c.open > 0 &&
                typeof c.high === 'number' && !isNaN(c.high) && c.high > 0 &&
                typeof c.low === 'number' && !isNaN(c.low) && c.low > 0 &&
                typeof c.close === 'number' && !isNaN(c.close) && c.close > 0;
        });

        if (validCandles.length === 0) {
            console.warn('[applyFullChartUpdate] Keine gueltigen Candles');
            if (chart) chart.timeScale().fitContent();
            isUpdatingChart = false;
            return;
        }

        // Alte Resourcen entfernen
        try { clearGridCircles(); } catch(e) {}
        try { clearGridLines(); } catch(e) {}
        if (currentPriceLine) {
            try { if (candleSeries) candleSeries.removePriceLine(currentPriceLine); } catch(e) {}
            currentPriceLine = null;
        }
        if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }

        if (_resizeObserver) {
            try { _resizeObserver.disconnect(); } catch(e) {}
            _resizeObserver = null;
        }

        try {
            if (chart) chart.remove();
        } catch(e) {
            console.warn('[applyFullChartUpdate] chart.remove() fehlgeschlagen:', e.message || e);
        }
        chart = null;
        candleSeries = null;
        dayLinesSeries = [];
        gridPriceLines = [];
        _circleSeries = [];
        _circleMarkerPlugins = [];
        _circleLevelSeries = {};
        // P16.05 (Prework Schritt 2): LineSeries-Registry nach Chart-Rebuild
        // leeren (die alten Serien haengen am entfernten chart-Objekt).
        _activeLineSeries = {};
        try { DaySeparator.clear(); } catch(e) {}

        var container = document.getElementById('chart-container');
        if (!container) {
            isUpdatingChart = false;
            return;
        }
        try { container.querySelectorAll('table, canvas').forEach(function(el) { el.remove(); }); } catch(e) {}

        var isDailyOrHigher = (currentTfInSeconds >= 86400);

        // Schritt 1: Chart erstellen
        try {
            chart = LightweightCharts.createChart(container, {
                width: container.clientWidth || 800,
                height: container.clientHeight || 600,
                layout: { background: { type: 'solid', color: '#131722' }, textColor: '#d1d4dc' },
                grid: { vertLines: { visible: false }, horzLines: { visible: false } },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                rightPriceScale: { borderColor: '#2B2B43' },
                timeScale: { 
                    borderColor: '#2B2B43', 
                    timeVisible: !isDailyOrHigher,
                    secondsVisible: false,
                    fixRightEdge: false,
                    fixLeftEdge: false,
                    shiftVisibleRangeOnNewBar: false,
                    tickMarkFormatter: function(time, tickMarkType) {
                        // time ist kontinuierlich (Fake-Zeit). Real-Epoch via toReal()
                        // (zentraler Helper statt raw-Map-Zugriff -> kein Fake-Label).
                        var realTime = toReal(time);
                        var p = getBerlinParts(realTime);
                        if (isDailyOrHigher || tickMarkType <= 2) {
                            return p.day + '.' + p.month + '.' + p.year.slice(-2);
                        }
                        return p.hour + ':' + p.minute;
                    }
                },
                localization: { locale: 'de-DE', timeFormatter: function(t) { 
                    // t ist bei Zeit-basierten Serien ein UTCTimestamp (Zahl),
                    // NICHT ein Objekt mit .time – sonst laeuft formatDT ins Leere.
                    var ts = (t !== null && typeof t === 'object') ? t.time : t;
                    return formatDT(toReal(ts)); 
                } }
            });
        } catch(e) {
            console.error('[applyFullChartUpdate] Schritt 1 (createChart) fehlgeschlagen:', e.message || e);
            isUpdatingChart = false;
            return;
        }

        try { setupResizeObserver(); } catch(e) {}

        var precision = (data.precision !== undefined && data.precision !== null) ? data.precision : currentPrecision;
        currentPrecision = precision;
        var minMove = (typeof precision === 'number' && precision > 0 && precision < 10) 
            ? 1 / Math.pow(10, precision) 
            : 0.01;

        // Schritt 2: CandlestickSeries
        try {
            candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
                upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
                wickUpColor: '#26a69a', wickDownColor: '#ef5350', priceLineVisible: false, lastValueVisible: false,
                priceFormat: { type: 'price', precision: precision, minMove: minMove }
            });
            if (!candleSeries) throw new Error('candleSeries ist null');
        } catch(e) {
            console.error('[applyFullChartUpdate] Schritt 2 (addSeries) fehlgeschlagen:', e.message || e);
            isUpdatingChart = false;
            return;
        }

        // Schritt 3: setData
        try {
            candleSeries.setData(validCandles);
        } catch(e) {
            console.error('[applyFullChartUpdate] Schritt 3 (setData) fehlgeschlagen:', e.message || e);
            isUpdatingChart = false;
            return;
        }
        rawCandleData = validCandles;
        lastClosePrice = validCandles[validCandles.length - 1].close;
        // P16.07 (Two-Tier): State-Reset für Nachlade-/Live-System
        // (hasMoreHistory D8, _atLiveEdge D9, Request-Serial D4, Live-Button).
        try { if (window._onFullChartUpdateApplied) window._onFullChartUpdateApplied(data); } catch(e) {}
        // P16.05 (P-C3): Circle-Cache für Merged-Render aus dem generischen
        // Render-Payload (chartRenderPayload.hit_circles) statt gridCircles.
        var renderPayload = (typeof data.chartRenderPayload === 'string')
            ? JSON.parse(data.chartRenderPayload) : (data.chartRenderPayload || {});
        _gridCirclesCache = (renderPayload.hit_circles || []).slice();
        // P14-03-E (Flacker-Fix): Live-Circle-Change-Detection nach Full-Update
        // zurücksetzen – der erste Tick nach dem Refresh rendert wieder.
        _lastLiveCirclesJson = '[]';
        _lastLiveOverlayTime = null;

        // Schritt 4: TimeScale Subscription
        try {
            chart.timeScale().subscribeVisibleLogicalRangeChange(function() { 
                if(!isUpdatingChart) {
                    try { syncRanges(); } catch(e) {}
                    try { updateCountdownDisplay(); } catch(e) {}
                    try { DaySeparator.updatePositions(); } catch(e) {}
                    try { Measurement.updatePositions(); } catch(e) {}
                    // P16.07 (D7/D9): Live-Ende-Detektion + Nachlade-Trigger
                    // (< 100 Kerzen links, debounced) via Two-Tier-Modul.
                    try { if (window._onVisibleRangeChanged) window._onVisibleRangeChanged(); } catch(e) {}
                }
            });

            // C2: auch bei reinen Größenänderungen der Zeitskala (z. B. wenn
            // der rechte Preisbereich sich ändert) die Trennlinien neu setzen.
            chart.timeScale().subscribeSizeChange(function() {
                if (!isUpdatingChart) {
                    try { DaySeparator.updatePositions(); } catch(e) {}
                    try { Measurement.updatePositions(); } catch(e) {}
                }
            });
        } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 4 (subscribe) fehlgeschlagen:', e.message || e);
        }

        // Countdown-Timer (1s Intervall)
        if (countdownTimer) clearInterval(countdownTimer);
        countdownTimer = setInterval(function() {
            try { updateCountdownDisplay(); } catch(e) {}
        }, 1000);

        // P16.05 (P-C3): Schritt 5+6 – generische Render-Pipeline statt
        // getrennter renderGridLines/renderGridCircles. Das aggregierte
        // Indikator-Payload (chartRenderPayload) wird 1:1 an
        // applyChartRenderPayload geroutet (price_lines→renderPriceLines,
        // lines→renderLineSeries, hit_circles→renderMarkers).
        try { if (data.chartRenderPayload) applyChartRenderPayload(data.chartRenderPayload); } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 5+6 (chartRenderPayload) fehlgeschlagen:', e.message || e);
        }

        // Schritt 7: Range
        try {
            if (data.rangeFrom !== undefined && data.rangeTo !== undefined &&
                data.rangeFrom !== null && data.rangeTo !== null &&
                data.rangeFrom !== data.rangeTo) {
                pendingRange = { rangeFrom: data.rangeFrom, rangeTo: data.rangeTo, priceFrom: data.priceFrom, priceTo: data.priceTo };
                applyRange(data.rangeFrom, data.rangeTo, data.priceFrom, data.priceTo);
            } else {
                if (chart) chart.timeScale().fitContent();
            }
        } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 7 (applyRange) fehlgeschlagen:', e.message || e);
        }

        // Schritt 8: Day Separators (gekapseltes Modul, CSS-Overlay)
        try { DaySeparator.render(rawCandleData); } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 8 (daySeparators) fehlgeschlagen:', e.message || e);
        }

        // Schritt 9: Measurement-State wiederherstellen (Messbox nach Refresh
        // bzw. Fenster-Neustart). Ohne State im Payload wird die Box geleert.
        try {
            if (window.Measurement) {
                if (data.measurementState) {
                    Measurement.restore(data.measurementState);
                } else {
                    Measurement.clear();
                }
            }
        } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 9 (measurement) fehlgeschlagen:', e.message || e);
        }

        // Fertig – isUpdatingChart freigeben + initialen sync
        isUpdatingChart = false;
        try { syncRanges(); } catch(e) {}
        try { updateCountdownDisplay(); } catch(e) {}

    } catch(e) {
        console.error('[applyFullChartUpdate] GLOBAL Error:', e.message || e);
        isUpdatingChart = false;
    }
}

```

--------------------------------------------------

### DATEI: chart/js/05_measurement.js
```js
// chart/js/05_measurement.js
// Messfunktion: Strg + linke Maustaste zieht eine Box auf,
// die Messwerte (Preisdiff, Zeitdiff, Start/Ende) werden live angezeigt.
// Die Box ist NUR eine temporaere Anzeige: Nach dem Loslassen bleibt sie
// stehen, verschwindet aber beim naechsten normalen Klick (linke Maustaste
// ohne Strg) auf den Chart. Escape loescht sie ebenfalls.//
// WICHTIG (Reintegration des alten Mess-Codes in die neue Modul-Struktur):
//  - Bedienung wie im alten Code: STRG + linke Maustaste (e.ctrlKey).
//  - Koordinaten-Umrechnung wie im alten Code: candleSeries.coordinateToPrice(y)
//    und candleSeries.priceToCoordinate(price). Der Weg über
//    chart.priceScale('right').coordinateToPrice() ist in LWC v5 NICHT
//    verfügbar (IPriceScaleApi hat nur applyOptions/options/width/
//    setVisibleRange/getVisibleRange/setAutoScale) – dadurch lieferte die
//    Umrechnung immer null (keine Messwerte, keine stehenbleibende Box).
//  - Zeitachse: chart.timeScale().coordinateToLogical(x)/logicalToCoordinate(l)
//    (vorhanden in v5).
//
// Design:
//  - Die Box wird als reines CSS-Overlay gezeichnet (#measurement-region +
//    #measurement-box) – konsistent zum DaySeparator-Modul und robust gegen
//    Chart-Rebuilds.
//  - Der Messzustand wird als logische Indizes + Preise gespeichert (nicht
//    als Pixel), damit die Box bei Scroll/Zoom/Resize folgt (updatePositions).
//  - Der Zustand geht an Python via pyBridge.onMeasurementChanged(JSON) und
//    wird beim nächsten Chart-Refresh wiederhergestellt (applyFullChartUpdate
//    -> Measurement.restore).
//  - Escape loescht die Messung (sendet '' an Python -> State = None).
//
// Koordinaten-Hinweis (LWC v5):
//  - timeScale().coordinateToLogical(x) / logicalToCoordinate(logical) arbeiten
//    relativ zur linken Pane-Kante. Da der Chart KEINE linke Preisskala hat,
//    ist Pane-X == Container-X.
//  - candleSeries.coordinateToPrice(y) / priceToCoordinate(price) arbeiten
//    relativ zur OBERKANTE des Pane (Zeitskala unten ausgenommen).
//    Das Pane beginnt oben bei Container-Y 0.
//  - Die Zeitskala unten wird beim Umrechnen ausgenommen (Pane-Bounds).
//
// Die internen Helfer (computeMeasurementData, formatDuration, formatMeasurementText,
// contTimeAtLogical) sind pure Funktionen und separat testbar.

var Measurement = (function() {

    // ---- Zustand ----------------------------------------------------------
    // state: { from: { logical, price }, to: { logical, price } } oder null
    var state = null;
    var dragging = false;
    var draft = null; // { x1, y1, x2, y2 } in Container-Pixeln (während Drag)

    // ---- kleine Helfer ----------------------------------------------------
    function _hide(el) { if (el && el.style.display !== 'none') el.style.display = 'none'; }
    function _show(el) { if (el && el.style.display !== 'block') el.style.display = 'block'; }
    function _round(x, decimals) {
        if (typeof x !== 'number' || !isFinite(x)) return x;
        var f = Math.pow(10, decimals);
        return Math.round(x * f) / f;
    }

    // ---- Pure Funktionen (testbar) ----------------------------------------

    // logischer Index (float) -> kontinuierliche Zeit (Interpolation über die
    // sortierten cont-Schlüssel; außerhalb des Datensatzes wird geclampt).
    function contTimeAtLogical(logical) {
        if (typeof logical !== 'number' || !isFinite(logical)) return null;
        if (!_continuousKeys || _continuousKeys.length === 0) return null;
        var last = _continuousKeys.length - 1;
        if (logical <= 0) return _continuousKeys[0];
        if (logical >= last) return _continuousKeys[last];
        var f = Math.floor(logical);
        var c = Math.ceil(logical);
        if (f === c) return _continuousKeys[f];
        return _continuousKeys[f] + (logical - f) * (_continuousKeys[c] - _continuousKeys[f]);
    }

    function computeMeasurementData(fromLogical, fromPrice, toLogical, toPrice) {
        var fromCont = contTimeAtLogical(fromLogical);
        var toCont = contTimeAtLogical(toLogical);
        var deltaPrice = toPrice - fromPrice;
        var pct = (fromPrice && fromPrice !== 0) ? (deltaPrice / fromPrice * 100) : 0;
        return {
            from: {
                logical: fromLogical,
                price: fromPrice,
                contTime: fromCont,
                realTime: (fromCont !== null) ? toReal(fromCont) : null
            },
            to: {
                logical: toLogical,
                price: toPrice,
                contTime: toCont,
                realTime: (toCont !== null) ? toReal(toCont) : null
            },
            deltaLogical: toLogical - fromLogical,
            deltaPrice: deltaPrice,
            pctChange: pct,
            candleCount: Math.round(Math.abs(toLogical - fromLogical)),
            durationSeconds: Math.abs(toLogical - fromLogical) * (currentTfInSeconds || 0)
        };
    }

    // Format Dauer als DD:HH:MM (Tage:Stunden:Minuten, jeweils 2-stellig) –
    // Sekunden werden NICHT angezeigt.
    function formatDuration(seconds) {
        seconds = Math.max(0, Math.round(seconds || 0));
        var d = Math.floor(seconds / SECONDS_PER_DAY);
        var h = Math.floor((seconds % SECONDS_PER_DAY) / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        function p(n) { return String(n).padStart(2, '0'); }
        return p(d) + ':' + p(h) + ':' + p(m);
    }

    function formatMeasurementText(data) {
        var prec = currentPrecision;
        var dp = data.deltaPrice;
        var dpStr = (dp >= 0 ? '+' : '') + dp.toFixed(prec);
        var pctStr = (data.pctChange >= 0 ? '+' : '') + data.pctChange.toFixed(2) + '%';
        var fromT = (data.from.realTime !== null && data.from.realTime !== undefined) ? formatDT(data.from.realTime) : '--';
        var toT = (data.to.realTime !== null && data.to.realTime !== undefined) ? formatDT(data.to.realTime) : '--';
        var lines = [];
        // 1) Δ Preis: zuerst Prozentwert, die exakte Differenz in Klammern
        lines.push('Δ Preis: ' + pctStr + '  (' + dpStr + ')');
        // 2) Δ Zeit: Anzahl Bars + Dauer im Format DD:HH:MM (ohne Sekunden)
        lines.push('Δ Zeit:  ' + data.candleCount + ' Bars · ' + formatDuration(data.durationSeconds));
        // 3) Start/Ende: Preis (auf Symbol-Nachkommastellen begrenzt) + Zeit
        lines.push('Start:   ' + data.from.price.toFixed(prec) + '  ' + fromT);
        lines.push('Ende:    ' + data.to.price.toFixed(prec) + '  ' + toT);
        return lines.join('\n');
    }

    // ---- LWC-Koordinaten-Helfer ------------------------------------------

    function _paneBounds() {
        var host = document.getElementById('chart-container');
        var w = host ? host.clientWidth : 0;
        var h = host ? host.clientHeight : 0;
        var tsH = 0;
        try { tsH = chart.timeScale().height() || 0; } catch(e) { tsH = 0; }
        return { left: 0, top: 0, width: Math.max(0, w), height: Math.max(0, h - tsH) };
    }

    // Pixel -> logischer Index + Preis (y wird auf den Pane-Bereich geclampt,
    // damit Klicks in der Zeitskala unten nicht zu null führen).
    // WICHTIG: Preis-Umrechnung NUR über die Serie (ISeriesApi), wie im alten
    // Code – priceScale('right') kann das in LWC v5 NICHT (siehe Kopf).
    function _toLogicalPrice(x, y) {
        if (!chart || !candleSeries) return { logical: null, price: null };
        var bounds = _paneBounds();
        if (y < bounds.top) y = bounds.top;
        if (y > bounds.top + bounds.height) y = bounds.top + bounds.height;
        var logical = null, price = null;
        try { logical = chart.timeScale().coordinateToLogical(x); } catch(e) { logical = null; }
        try { price = candleSeries.coordinateToPrice(y); } catch(e) { price = null; }
        return { logical: logical, price: price };
    }

    function _toPixel(logical, price) {
        if (!chart || !candleSeries) return { x: 0, y: 0 };
        var x = 0, y = 0;
        try {
            var v = chart.timeScale().logicalToCoordinate(logical);
            if (v !== null && isFinite(v)) x = v;
        } catch(e) {}
        try {
            var v2 = candleSeries.priceToCoordinate(price);
            if (v2 !== null && isFinite(v2)) y = v2;
        } catch(e) {}
        return { x: x, y: y };
    }

    // ---- Rendering ---------------------------------------------------------

    function render() {
        var region = document.getElementById('measurement-region');
        var box = document.getElementById('measurement-box');
        if (!region || !box) return;
        if (!chart || !candleSeries || isUpdatingChart) { _hide(region); _hide(box); return; }

        var pts = null;
        if (dragging && draft) {
            pts = { x1: draft.x1, y1: draft.y1, x2: draft.x2, y2: draft.y2 };
        } else if (state) {
            var p1 = _toPixel(state.from.logical, state.from.price);
            var p2 = _toPixel(state.to.logical, state.to.price);
            pts = { x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y };
        }

        if (!pts) { _hide(region); _hide(box); return; }

        var left = Math.min(pts.x1, pts.x2);
        var top = Math.min(pts.y1, pts.y2);
        var width = Math.abs(pts.x2 - pts.x1);
        var height = Math.abs(pts.y2 - pts.y1);

        region.style.display = 'block';
        region.style.left = left + 'px';
        region.style.top = top + 'px';
        region.style.width = Math.max(width, 1) + 'px';
        region.style.height = Math.max(height, 1) + 'px';

        var fromLP = _toLogicalPrice(pts.x1, pts.y1);
        var toLP = _toLogicalPrice(pts.x2, pts.y2);
        if (fromLP.logical === null || fromLP.price === null || toLP.logical === null || toLP.price === null) {
            _hide(box);
            return;
        }
        var data = computeMeasurementData(fromLP.logical, fromLP.price, toLP.logical, toLP.price);
        var text = formatMeasurementText(data);
        if (box.innerText !== text) box.innerText = text;
        _show(box);

        // Info-Box neben dem Endpunkt (Mauszeiger) positionieren – wie im alten
        // Code, aber im Container geclampt, damit sie nie aus dem Chart läuft.
        var host = document.getElementById('chart-container');
        var hostW = host ? host.clientWidth : 0;
        var hostH = host ? host.clientHeight : 0;
        var boxW = box.offsetWidth || 200;
        var boxH = box.offsetHeight || 70;
        var bx = pts.x2 + 15;
        var by = pts.y2 + 15;
        if (bx + boxW > hostW) bx = Math.max(2, pts.x2 - boxW - 15);
        if (by + boxH > hostH) by = Math.max(2, pts.y2 - boxH - 15);
        box.style.left = bx + 'px';
        box.style.top = by + 'px';
    }

    // ---- Python-Sync --------------------------------------------------------

    function _syncToPython() {
        if (!pyBridge) return;
        try {
            var payload = '';
            if (state) {
                payload = JSON.stringify({
                    from: { logical: _round(state.from.logical, 4), price: state.from.price },
                    to: { logical: _round(state.to.logical, 4), price: state.to.price }
                });
            }
            pyBridge.onMeasurementChanged(payload);
        } catch(e) {
            console.warn('[Measurement] pyBridge sync fehlgeschlagen:', e.message || e);
        }
    }

    // ---- Event-Handler -------------------------------------------------------

    function _containerRect() {
        var host = document.getElementById('chart-container');
        return host ? host.getBoundingClientRect() : { left: 0, top: 0 };
    }

    function onMouseDown(e) {
        if (!chart || !candleSeries || isUpdatingChart) return;
        // Nur Strg + linke Maustaste startet eine Messung
        if (e.ctrlKey && e.button === 0) {
            e.preventDefault();
            e.stopPropagation();
            var rect = _containerRect();
            var x = e.clientX - rect.left;
            var y = e.clientY - rect.top;
            dragging = true;
            draft = { x1: x, y1: y, x2: x, y2: y };
            render();
            return;
        }
        // Temporäre Messanzeige: Ein normaler Klick (linke Maustaste ohne Strg)
        // auf den Chart schliesst die Messbox. Die Box selbst hat pointer-events:
        // none, daher landen alle Klicks auf dem Chart – die Messung ist damit
        // genau "bis zur nächsten Aktion" sichtbar. Strg-Klicks (neue Messung)
        // werden oben bereits behandelt.
        if (e.button === 0 && state) {
            state = null;
            draft = null;
            dragging = false;
            render();
            _syncToPython();
        }
    }

    function onMouseMove(e) {
        if (!dragging || !draft) return;
        e.preventDefault();
        var rect = _containerRect();
        draft.x2 = e.clientX - rect.left;
        draft.y2 = e.clientY - rect.top;
        render();
    }

    function onMouseUp(e) {
        if (!dragging) return;
        e.preventDefault();
        dragging = false;
        if (draft) {
            var fromLP = _toLogicalPrice(draft.x1, draft.y1);
            var toLP = _toLogicalPrice(draft.x2, draft.y2);
            if (fromLP.logical !== null && fromLP.price !== null && toLP.logical !== null && toLP.price !== null) {
                state = {
                    from: { logical: fromLP.logical, price: fromLP.price },
                    to: { logical: toLP.logical, price: toLP.price }
                };
            }
            draft = null;
        }
        render();
        _syncToPython();
    }

    function onKeyDown(e) {
        if (e.key === 'Escape' || e.keyCode === 27) {
            state = null;
            draft = null;
            dragging = false;
            render();
            _syncToPython();
        }
    }

    function _bind() {
        var host = document.getElementById('chart-container');
        if (!host) return;
        host.removeEventListener('mousedown', onMouseDown, true);
        host.addEventListener('mousedown', onMouseDown, true);
        window.removeEventListener('mousemove', onMouseMove);
        window.addEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
        window.addEventListener('mouseup', onMouseUp);
        window.removeEventListener('keydown', onKeyDown);
        window.addEventListener('keydown', onKeyDown);
    }

    // ---- Öffentliche API -----------------------------------------------------

    function restore(jsonState) {
        try {
            var s = (typeof jsonState === 'string') ? JSON.parse(jsonState) : jsonState;
            if (s && s.from && s.to &&
                typeof s.from.logical === 'number' && typeof s.from.price === 'number' &&
                typeof s.to.logical === 'number' && typeof s.to.price === 'number') {
                state = {
                    from: { logical: s.from.logical, price: s.from.price },
                    to: { logical: s.to.logical, price: s.to.price }
                };
            } else {
                state = null;
            }
        } catch(e) {
            state = null;
        }
        render();
    }

    function updatePositions() {
        // Bei Scroll/Zoom/Resize: Box neu aus logischen Koordinaten berechnen
        if (!state) return;
        if (!chart || !candleSeries || isUpdatingChart) return;
        render();
    }

    function clear() {
        state = null;
        draft = null;
        dragging = false;
        var region = document.getElementById('measurement-region');
        var box = document.getElementById('measurement-box');
        _hide(region);
        _hide(box);
    }

    function hasState() {
        return state !== null;
    }

    // Initial binden (DOM ist beim Skriptende bereits fertig – Skript steht am Body-Ende)
    try { _bind(); } catch(e) {}

    return {
        render: render,
        restore: restore,
        updatePositions: updatePositions,
        clear: clear,
        hasState: hasState,
        // pure Funktionen für Tests exportieren
        computeMeasurementData: computeMeasurementData,
        formatDuration: formatDuration,
        formatMeasurementText: formatMeasurementText,
        contTimeAtLogical: contTimeAtLogical,
        _state: function() { return state; },
        _setStateForTest: function(s) { state = s; },
        _syncToPython: _syncToPython
    };
})();

```

--------------------------------------------------

### DATEI: chart/js/06_two_tier.js
```js
// chart/js/06_two_tier.js
// Phase 16.07 – Two-Tier Caching & Dynamic Range Management (JS-Tier)
//
// D1/D3/D4/D5/D7/D8/D9/D10 – Sliding Window auf der JS-Seite:
//   * Tier-1-Fenster N = 1000 (initial + Chunk-Grösse), linke Kante wird
//     beim Scrollen dynamisch erweitert (kein Full-Chart-Rebuild).
//   * Trigger (D7): < 100 verbleibende Kerzen links im Canvas -> Request an
//     Python (pyBridge.onRequestOlderData), debounced mit 300 ms.
//   * Antwort (D4): applyOlderDataChunk(payload) mit updateId (Request-Serial,
//     Race-Guard), candles (Prepend), timeMapDelta, chartRenderPayloadDelta,
//     windowRightEpoch (Sliding-Window-Kante), hasMoreHistory (D8).
//   * Die Candles werden vorne angehängt (setData, KEIN chart.remove()/
//     createChart), die logische Range um +k verschoben -> Viewport bleibt
//     stabil (kein Sprung).
//   * Linien/Marker (D5): Python sendet das VOLLSTÄNDIG neu berechnete
//     Render-Payload für das aktuelle Fenster; JS ersetzt per renderLineSeries
//     / renderMarkers (bestehende inkrementelle Serien-Registry, kein
//     Full-Layer-Rebuild).
//   * Live-Ticks (D9): Befindet sich der Viewport nicht am rechten Rand
//     (_atLiveEdge == false), wird updateLiveCandle() in 04_live_updates.js
//     unterdrückt (stummer Tier-2-Update); ein dezenter „Live"-Button springt
//     bei Klick ans Live-Ende (Python-Full-Refresh via onJumpToLive).
//   * D10: syncRanges liefert zusätzlich die Gesamt-Kerzenzahl, damit Python
//     den Viewport offsetbasiert (Abstand vom rechten Rand) persistieren kann.
//
// Dieses Modul wird NACH 04_live_updates.js geladen (chart_basics.JS_FILES)
// und hängt sich über optionale Hooks in 04 ein:
//   window._onFullChartUpdateApplied(data) – State-Reset nach Full-Update
//   window._onVisibleRangeChanged()        – Range-Änderung (Live-Detektion +
//                                            Nachlade-Trigger)
//   window._isHistoryView()                – Live-Tick-Suppression (D9)

// =============================================================================
// Konstanten (D1/D7)
// =============================================================================
const TIER1_WINDOW = 1000;        // N: Tier-1-Fenster-/Chunk-Grösse (D1)
const LEFT_EDGE_THRESHOLD = 100;  // D7: < 100 verbleibende Kerzen im Canvas
const OLDER_REQUEST_DEBOUNCE_MS = 300; // D7: JS-Debounce

// =============================================================================
// Zustand (durch applyFullChartUpdate via Hook zurückgesetzt)
// =============================================================================
let _hasMoreHistory = true;       // D8: Stop-Flag (kein Endlos-Loop)
let _atLiveEdge = true;           // D9: Viewport am rechten Rand (Live)
let _requestSerial = 0;           // monoton steigendes Request-Serial (D4)
let _pendingRequestSerial = 0;    // letztes an Python gesendetes Serial
let _olderRequestTimer = null;    // JS-Debounce-Timer (D7)

// =============================================================================
// Live-Button (D9) – dezenter Overlay-Button, nur in der Historie sichtbar
// =============================================================================
function _updateLiveButton() {
    var btn = document.getElementById('live-button');
    if (!btn) return;
    btn.style.display = _atLiveEdge ? 'none' : 'block';
}

var _liveButtonEl = document.getElementById('live-button');
if (_liveButtonEl) {
    _liveButtonEl.addEventListener('click', function() {
        try {
            if (pyBridge && pyBridge.onJumpToLive) pyBridge.onJumpToLive();
        } catch(e) {}
    });
}

// =============================================================================
// Hook: Full-Update angewendet (04_live_updates.js ruft optional auf)
// =============================================================================
function _onFullChartUpdateApplied(data) {
    _hasMoreHistory = (data && data.hasMoreHistory !== false);
    _atLiveEdge = true;
    _requestSerial = 0;
    _pendingRequestSerial = 0;
    if (_olderRequestTimer) { clearTimeout(_olderRequestTimer); _olderRequestTimer = null; }
    _updateLiveButton();
}

// =============================================================================
// Hook: sichtbare logische Range geändert (04_live_updates.js ruft optional auf)
// =============================================================================
function _onVisibleRangeChanged() {
    try {
        var lr = chart.timeScale().getVisibleLogicalRange();
        if (lr && lr.from !== null && lr.to !== null && !isNaN(lr.from) && !isNaN(lr.to)) {
            // D9: Live-Ende, wenn die rechte Viewport-Kante nahe dem Datenende liegt.
            _atLiveEdge = (rawCandleData.length > 0 && lr.to >= rawCandleData.length - 5);
            _updateLiveButton();
        }
    } catch(e) {}
    _maybeRequestOlderData();
}

// =============================================================================
// D7: Nachlade-Trigger (debounced, < 100 Kerzen links im Canvas)
// =============================================================================
function _maybeRequestOlderData() {
    if (!pyBridge || !chart || !rawCandleData || rawCandleData.length === 0) return;
    if (!_hasMoreHistory) return;   // D8: Stop-Flag
    if (isUpdatingChart) return;
    try {
        var lr = chart.timeScale().getVisibleLogicalRange();
        if (!lr || lr.from === null || isNaN(lr.from)) return;
        if (lr.from > LEFT_EDGE_THRESHOLD) return;

        var leftReal = toReal(rawCandleData[0].time);
        var rightReal = toReal(rawCandleData[rawCandleData.length - 1].time);

        // Debounce (300 ms): nur der letzte Request innerhalb des Fensters.
        if (_olderRequestTimer) clearTimeout(_olderRequestTimer);
        _pendingRequestSerial = ++_requestSerial;
        var serial = _pendingRequestSerial;
        var fromEpoch = leftReal;
        var count = TIER1_WINDOW;
        var winRight = rightReal;
        _olderRequestTimer = setTimeout(function() {
            _olderRequestTimer = null;
            try {
                if (pyBridge && pyBridge.onRequestOlderData) {
                    pyBridge.onRequestOlderData(fromEpoch, count, serial, winRight);
                }
            } catch(e) {}
        }, OLDER_REQUEST_DEBOUNCE_MS);
    } catch(e) {}
}

// =============================================================================
// D4: Chunk-Antwort aus Python – inkrementelles Prepend (Sliding Window)
// =============================================================================
function applyOlderDataChunk(payload) {
    if (!payload || typeof payload !== 'object') return;
    // Race-Guard 1 (D4): nur der NEUESTE Request wird angewendet (doppelte
    // Requests bei schnellem Scrollen / verspätete Antworten).
    if (typeof payload.updateId === 'number' && payload.updateId !== _pendingRequestSerial) {
        console.warn('[TwoTier] Veraltete Chunk-Antwort verworfen (id=' + payload.updateId + ' != ' + _pendingRequestSerial + ')');
        return;
    }
    // Race-Guard 2: Chunk aus einem früheren Symbol/TF-Stand verwerfen.
    if (payload.symbol !== undefined && payload.symbol !== null && payload.symbol !== currentSymbol) return;
    if (payload.timeframe !== undefined && payload.timeframe !== null && payload.timeframe !== currentTimeframe) return;

    var newCandles = payload.candles || [];
    var k = newCandles.length;
    _hasMoreHistory = (payload.hasMoreHistory !== false);  // D8
    if (k === 0) {
        // Keine ältere Geschichte mehr (DB-Ende) – Stop-Flag gesetzt.
        return;
    }

    try {
        // Aktuelle logische Range VOR dem Prepend merken (Viewport-Stabilität).
        var lr = null;
        try { lr = chart.timeScale().getVisibleLogicalRange(); } catch(e) {}

        // TimeMap erweitern: nur NEUE Einträge (bestehende cont-Zeiten bleiben
        // unverändert, daher bleibt der Chart-Zeitstrahl konsistent).
        var delta = payload.timeMapDelta || {};
        for (var key in delta) {
            if (Object.prototype.hasOwnProperty.call(delta, key)) {
                var cKey = Number(key);
                _continuousTimeMap[cKey] = delta[key];
                _realToContMap[delta[key]] = cKey;
            }
        }
        _continuousKeys = Object.keys(_continuousTimeMap).map(Number).sort(function(a, b) { return a - b; });

        // Candles vorne anhängen (aufsteigend, kontinuierliche Zeit).
        rawCandleData = newCandles.concat(rawCandleData);

        // Sliding Window (D2): Rechte Kante ggf. kürzen, falls der Tier-2-
        // Puffer nach links geschoben wurde (windowRightEpoch < bisheriges
        // Fenster-Ende). Sonst bleibt das Live-Ende erhalten.
        if (payload.windowRightEpoch && payload.windowRightEpoch > 0) {
            var rightCont = toCont(payload.windowRightEpoch);
            if (rightCont !== undefined && rawCandleData.length) {
                var lastCont = rawCandleData[rawCandleData.length - 1].time;
                if (lastCont > rightCont) {
                    var keepIdx = 0;
                    for (var i = 0; i < rawCandleData.length; i++) {
                        if (rawCandleData[i].time <= rightCont) keepIdx = i + 1;
                    }
                    var dropped = rawCandleData.slice(keepIdx);
                    rawCandleData = rawCandleData.slice(0, keepIdx);
                    for (var d = 0; d < dropped.length; d++) {
                        var dCont = dropped[d].time;
                        var dReal = _continuousTimeMap[dCont];
                        if (dReal !== undefined) {
                            delete _continuousTimeMap[dCont];
                            delete _realToContMap[dReal];
                        }
                    }
                    _continuousKeys = Object.keys(_continuousTimeMap).map(Number).sort(function(a, b) { return a - b; });
                }
            }
        }

        // Candle-Serie ersetzen – KEIN chart.remove()/createChart (kein Sprung).
        candleSeries.setData(rawCandleData);

        // D5: Render-Delta anwenden – Python sendet das VOLLSTÄNDIG neu
        // berechnete Fenster-Payload; JS ersetzt Linien/Marker nahtlos über
        // die bestehenden inkrementellen Serien-Registrys.
        var rp = payload.chartRenderPayloadDelta || {};
        if (rp.lines) {
            try { renderLineSeries(rp.lines); } catch(e) {
                console.warn('[TwoTier] lines fehlgeschlagen:', e.message || e);
            }
        }
        if (rp.hit_circles) {
            _gridCirclesCache = rp.hit_circles.slice();
            _lastLiveCirclesJson = '[]';
            try { renderMarkers(_gridCirclesCache); } catch(e) {
                console.warn('[TwoTier] hit_circles fehlgeschlagen:', e.message || e);
            }
        }

        // DaySeparator neu berechnen (Tagesgrenzen im vorderen Bereich).
        try { DaySeparator.render(rawCandleData); } catch(e) {}

        // Viewport stabil halten: logische Range um k nach rechts verschieben
        // (die bestehenden Kerzen sind durch das Prepend um k Indizes gerutscht).
        if (lr && lr.from !== null && lr.to !== null && !isNaN(lr.from) && !isNaN(lr.to)) {
            var newFrom = lr.from + k;
            var newTo = lr.to + k;
            if (newTo > rawCandleData.length - 1) newTo = rawCandleData.length - 1;
            if (newFrom > newTo) newFrom = newTo;
            if (newFrom < 0) newFrom = 0;
            try { chart.timeScale().setVisibleLogicalRange({ from: newFrom, to: newTo }); } catch(e) {}
        }

        // Nun in der Historie (nicht am Live-Ende) – D9: Ticks stumm.
        _atLiveEdge = false;
        _updateLiveButton();

        try { syncRanges(); } catch(e) {}
    } catch(e) {
        console.error('[TwoTier] applyOlderDataChunk Error:', e.message || e);
    }
}

// =============================================================================
// D9: Live-Tick-Suppression – 04_live_updates.js fragt optional ab
// =============================================================================
function _isHistoryView() {
    return _atLiveEdge === false;
}

```

--------------------------------------------------

### DATEI: chart/overlays/__init__.py
```py
# chart/overlays/__init__.py
# Phase 16 P16.03 (06.08.2026): Generische Zeichnungsobjekte & Style-Vertraege.
#
# LineStyle / MarkerStyle kapseln Styling-Attribute (Farbe, Dicke, Stil, Form,
# Sichtbarkeit) und konvertieren sich via .to_js_dict() direkt fuer das
# Canvas-Frontend sowie via .to_dict()/.from_dict() fuer die JSON-Persistenz
# (indicator_presets im StateManager).
from .style_models import (
    LINE_STYLES,
    MARKER_SHAPES,
    LineStyle,
    MarkerStyle,
)

__all__ = [
    "LINE_STYLES",
    "MARKER_SHAPES",
    "LineStyle",
    "MarkerStyle",
]

```

--------------------------------------------------

### DATEI: chart/overlays/style_models.py
```py
# chart/overlays/style_models.py
# Phase 16 P16.03 (06.08.2026): Generische Style-Vertraege (Dataclasses).
#
# Visuelle Attribute (Farbe, Dicke, Stil, Form) werden nicht mehr als flache
# Einzelparameter (line_color, line_width, ...) durch das System gereicht,
# sondern in typisierten Styling-Klassen gebuendelt:
#
#   * LineStyle   - Linien: show / color / width / style
#   * MarkerStyle - Punkte (Hit-Circles u. a.): show / color / shape / size
#
# Konvertierungen:
#   * to_js_dict()  - direkt fuer die JS-Bridge (TradingView Lightweight
#                     Charts v5): style-Werte lowercase (solid/dashed/dotted/
#                     dashdotted), shape-Werte LWC-kompatibel
#                     (circle/square/arrowUp/arrowDown).
#   * to_dict()     - JSON-kompatibles Dict (Preset-Persistenz im
#                     StateManager / indicator_presets).
#   * from_dict()   - Rueck-Konvertierung (tolerant gegen fehlende Felder:
#                     Defaults werden ergaenzt).
#
# Farb-Logik (Paritaet zum ColorButton / StylePickerWidget):
#   - Alpha == 255 -> '#RRGGBB' (Hex, Grossbuchstaben, volle Deckkraft).
#   - Alpha < 255  -> 'rgba(r, g, b, a)' mit a als Float (0..1) -
#                     1:1 kompatibel mit TradingView Lightweight Charts v5
#                     (WebEngine) und HTML/CSS.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Konvertierungs-Helfer
# ---------------------------------------------------------------------------

def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if value is None:
        return default
    return bool(value)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value)


# ---------------------------------------------------------------------------
# LineStyle
# ---------------------------------------------------------------------------

#: Gueltige Linienarten (lowercase, JS-Bridge-Konvention).
LINE_STYLES: List[str] = ["solid", "dashed", "dotted", "dashdotted"]


@dataclass
class LineStyle:
    """Stil-Definition fuer Linien: Sichtbarkeit, Farbe, Staerke, Linienart.

    Attributes:
        show:  bool  – Linie sichtbar (QCheckBox).
        color: str   – '#RRGGBB' (Alpha=255) oder 'rgba(r,g,b,a)' (Teil-Transparenz).
        width: int   – Linienstaerke in px (1–10, QSpinBox).
        style: str   – 'solid' | 'dashed' | 'dotted' | 'dashdotted' (QComboBox).
    """

    show: bool = True
    color: str = "#2196F3"
    width: int = 1
    style: str = "solid"

    # -- JS-Bridge -----------------------------------------------------------
    def to_js_dict(self) -> Dict[str, Any]:
        """JS-Bridge-Darstellung (LWC v5): lowercase style-Werte."""
        return {
            "show": bool(self.show),
            "color": str(self.color),
            "width": int(self.width),
            "style": str(self.style) if str(self.style) in LINE_STYLES else "solid",
        }

    # -- JSON-Persistenz -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """JSON-kompatibles Dict (Presets im StateManager)."""
        return self.to_js_dict()

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LineStyle":
        """Erzeugt eine LineStyle aus einem (JSON-)Dict – tolerant: fehlende
        Felder erhalten ihre Defaults, ungueltige style-Werte fallen auf
        'solid' zurueck. None -> Default-Instanz.
        """
        if not isinstance(data, dict):
            return cls()
        style = _as_str(data.get("style"), "solid")
        if style not in LINE_STYLES:
            style = "solid"
        return cls(
            show=_as_bool(data.get("show"), True),
            color=_as_str(data.get("color"), "#2196F3"),
            width=_as_int(data.get("width"), 1),
            style=style,
        )


# ---------------------------------------------------------------------------
# MarkerStyle
# ---------------------------------------------------------------------------

#: Gueltige Marker-Formen (LWC v5-kompatibel fuer die JS-Bridge).
MARKER_SHAPES: List[str] = ["circle", "square", "arrowUp", "arrowDown"]


@dataclass
class MarkerStyle:
    """Stil-Definition fuer Marker/Punkte: Sichtbarkeit, Farbe, Form, Groesse.

    Attributes:
        show:  bool  – Marker sichtbar (QCheckBox).
        color: str   – '#RRGGBB' (Alpha=255) oder 'rgba(r,g,b,a)' (Teil-Transparenz).
        shape: str   – 'circle' | 'square' | 'arrowUp' | 'arrowDown' (QComboBox).
        size:  int   – Markergroesse in px (QSpinBox).
    """

    show: bool = True
    color: str = "#FFEB3B"
    shape: str = "circle"
    size: int = 6

    # -- JS-Bridge -----------------------------------------------------------
    def to_js_dict(self) -> Dict[str, Any]:
        """JS-Bridge-Darstellung (LWC v5): shape-Werte LWC-kompatibel."""
        return {
            "show": bool(self.show),
            "color": str(self.color),
            "shape": str(self.shape) if str(self.shape) in MARKER_SHAPES else "circle",
            "size": int(self.size),
        }

    # -- JSON-Persistenz -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """JSON-kompatibles Dict (Presets im StateManager)."""
        return self.to_js_dict()

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MarkerStyle":
        """Erzeugt eine MarkerStyle aus einem (JSON-)Dict – tolerant: fehlende
        Felder erhalten ihre Defaults, ungueltige shape-Werte fallen auf
        'circle' zurueck. None -> Default-Instanz.
        """
        if not isinstance(data, dict):
            return cls()
        shape = _as_str(data.get("shape"), "circle")
        if shape not in MARKER_SHAPES:
            shape = "circle"
        return cls(
            show=_as_bool(data.get("show"), True),
            color=_as_str(data.get("color"), "#FFEB3B"),
            shape=shape,
            size=_as_int(data.get("size"), 6),
        )

```

--------------------------------------------------

### DATEI: chart/widgets/__init__.py
```py
# chart/widgets/__init__.py
# Wiederverwendbare kompakte UI-Widgets (Phase 13 Kapitel 5.5 + Schritt 9).
#
# HINWEIS: Bewusst MINIMAL gehalten – hier werden KEINE schweren Module
# importiert (kein chart_win, keine Indikatoren). StylePickerWidget ist ein
# eigenständiges PySide6-Widget und kann von indicator_dialog.py,
# serviceui/service_win.py und Tests ohne Circular-Import-Risiko eingebunden werden.
# NamedItemActionsMixin ist ein reines Qt-Mixin (nur QInputDialog/QMessageBox)
# und ebenfalls import-schwerelos.
#
# Phase 16 (06.08.2026): ColorButton wurde durch das generische
# StylePickerWidget ersetzt (Farbe + Stärke + Stil + Sichtbarkeit).
#
# Phase 16 P16.03 (06.08.2026): Die Style-Vertraege LineStyle/MarkerStyle
# leben seitdem zentral in `chart/overlays/style_models.py` und werden hier
# re-exportiert (rueckwaertskompatibler Importweg). StylePickerWidget selbst
# importiert sie bereits direkt aus den overlays.
from chart.overlays.style_models import LineStyle, MarkerStyle
from .style_picker_widget import StylePickerDialog, StylePickerWidget
from .named_item_actions import NamedItemActionsMixin, NamedItemAdapter

__all__ = ["LineStyle", "MarkerStyle", "StylePickerDialog", "StylePickerWidget", "NamedItemActionsMixin", "NamedItemAdapter"]

```

--------------------------------------------------

### DATEI: chart/widgets/mtf_filter_bar.py
```py
# chart/widgets/mtf_filter_bar.py
"""
MTF-FC v4 (Kapitel 21.03.07) – MtfFilterBarWidget & Control-Panel.

Filterleiste mit Source-Data-TF, Chart-Overlay-TF, Aggregations-TF,
Range-Picker (Presets 24h/7d/30d/90d/Year, 21.03.15), Tabellen-
Sortierung und Session-Filter (§4 Säule 1). 21.03.14 (Wunsch 2): Die
zusaetzlichen View-Template-Buttons wurden rueckgebaut – die Filter-
Konfiguration laeuft ueber das vorhandene Profil-Management (`sort_mode`
wird ebenfalls persistiert). 21.03.15 (Bug 3/4): 'YTD' wurde in 'Year'
umbenannt (365-Tage-Fenster) + '90d' ergaenzt; der benutzerdefinierte
Von-/Bis-Zeitraum entfaellt, die Session-Checkboxen stehen in Zeile 1
rechts neben der Sortierung (eine Zeile, keine Zeile 2 mehr).

MVVM (Grundsatz 4): KEINE SQL-Queries, KEINE DB-Connects in der UI.
Der Zustand wird ausschliesslich über den `MtfFcProvider` im isolierten
Namespace `shared_state["mtf_fc"]` gelesen/geschrieben. Die Kommunikation
mit Orchestratoren läuft über Signale (keine direkten Fenster-Referenzen,
Grundsatz 2/5).

Das Widget ist bewusst zustandsarm: Es rendert die Steuerungselemente und
emittiert Signale; die eigentliche Verarbeitung (Boundary, Kaskade, Guards)
liegt in den Engine-Modulen (21.03.02-21.03.05).
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.mtf_fc_provider import MtfFcProvider

#: Data-TF-Auswahl (Multi + fixierte Timeframes). 21.03.11 (Bug 6):
#: Labels kompakt, damit die Leiste in 1200-px-Fenster passt (sizeHint war
#: w=2248 px -> Uberlauf/Clipping, Controls unsichtbar).
DATA_TF_OPTIONS = ["🌐 Multi", "🔒 M1", "🔒 M5", "🔒 M15", "🔒 H1", "🔒 H4"]

#: Chart-Overlay-TF (Auto-Kaskade vs. manuell fix).
CHART_TF_OPTIONS = ["⚡ Auto", "🔒 Fix"]

#: Aggregations-TF (21.03.12, Entscheidung 6a): '⚡ Auto' = Granularitaet
#: dynamisch an den Range anpassen; '🔒 [TF]' = Daten starr auf diesem
#: TF-Raster zusammenfassen. Konfigurierbar via `agg_tf_options`.
AGG_TF_OPTIONS = ["⚡ Auto", "🔒 M1", "🔒 M5", "🔒 M15", "🔒 H1", "🔒 H4", "🔒 D1"]

#: Range-Presets (21.03.15, Bug 3): '90d' ergaenzt; 'YTD' (seit
#: Jahresbeginn) wurde auf 'Year' (letzte 365 Tage) umbenannt.
RANGE_PRESETS = ["24h", "7d", "30d", "90d", "Year"]

#: Tabellen-Sortierung.
SORT_MODES = ["Datum 🠇", "Signal 🠇", "TF 🠅"]

#: Session-Filter (Farbbalken im M1/M5-Zoom, 21.03.08).
SESSION_OPTIONS = ["London", "New York", "Tokio"]

_STRIP_PREFIX = ("🌐 ", "🔒 ", "⚡ ", "🠇", "🠅", " (Multi)", " (Kaskade)", " Manuell Fix")


def _parse_data_tf(text: str) -> str:
    """Konvertiert ein Data-TF-Dropdown-Label in den Wert ('multi' | 'M15')."""
    for prefix in ("🌐 ", "🔒 "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    stripped = text.strip()
    if not stripped or stripped.lower() in ("multi", "alle timeframes",
                                            "alle tf", "alle timeframes (multi)"):
        return "multi"
    return stripped


def _data_tf_label(data_tf: str) -> str:
    """Erzeugt das kompakte Data-TF-Dropdown-Label aus dem Wert."""
    return "🌐 Multi" if str(data_tf).lower() == "multi" else f"🔒 {data_tf}"


def _parse_chart_tf(text: str) -> str:
    """Konvertiert ein Chart-TF-Dropdown-Label in 'auto' oder fixierten TF."""
    if text.startswith("⚡"):
        return "auto"
    return "fix"


class MtfFilterBarWidget(QWidget):
    """Filterleiste des MTF-FC-Systems (QWidget, reines Event-Handling).

    Signale (Entkopplung über den Aufrufer, kein Fenster-Know-how):
      * `data_tf_changed(str)`     – 'multi' oder fixierter TF (z. B. 'M15').
      * `chart_tf_changed(str)`    – 'auto' (Kaskade) oder 'fix'.
      * `agg_tf_changed(str)`      – 'auto' oder konkreter Aggregations-TF
                                     (21.03.12, Entscheidung 6a).
      * `range_changed(str, int, int)` – Preset-Name, from_ts, to_ts.
      * `sort_mode_changed(str)`   – 'date' | 'signal' | 'tf'.
      * `sessions_changed(list)`   – aktive Sessions (z. B. ['london']).
      * `guard_override_requested(str, str)` – target_tf, reason (21.03.05).
    """

    data_tf_changed = Signal(str)
    chart_tf_changed = Signal(str)
    agg_tf_changed = Signal(str)
    range_changed = Signal(str, int, int)
    sort_mode_changed = Signal(str)
    sessions_changed = Signal(list)
    guard_override_requested = Signal(str, str)

    def __init__(
        self,
        provider: Optional[MtfFcProvider] = None,
        parent: Optional[QWidget] = None,
        # 21.03.12 (Analytics-Integration): Die TF-Listen sind konfigurierbar
        # (Analytics hat 11 TFs M1..MN1 statt der 6 Chart-Defaults) und der
        # Range-Referenzpunkt kann injiziert werden (`now_provider` – im
        # Analytics der letzte Datenpunkt MAX(bar_time) statt time.time()).
        data_tf_options: Optional[List[str]] = None,
        agg_tf_options: Optional[List[str]] = None,
        now_provider: Optional[Callable[[], int]] = None,
    ) -> None:
        super().__init__(parent)
        # Provider ist die EINZIGE Brücke zum shared_state-Namespace (MVVM).
        self._provider = provider or MtfFcProvider()
        self._sessions: List[str] = []
        self._data_tf_options = (
            list(data_tf_options) if data_tf_options else list(DATA_TF_OPTIONS))
        self._agg_tf_options = (
            list(agg_tf_options) if agg_tf_options else list(AGG_TF_OPTIONS))
        self._now_provider = now_provider or _now_epoch
        self._build_ui()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # 21.03.11 (Bug 6, 2. Fix): Kompakte EIN-Zeilen-Leiste. Der
        # 1-Zeilen-Umbau (max. Breiten) war noch zu breit: sizeHint=1281,
        # minimumSizeHint=1209 -> das Fenster wird auf ~1220 px aufgezwungen,
        # Range (x 837+) und Sortierung (x 1173+, Ende > Fenster) waren rechts
        # abgeschnitten/unsichtbar. Seit 21.03.15 (Bug 4) liegen Data/Chart/
        # Agg/Range/Sort/Sessions in EINER Zeile (die fruehere Zeile 2 mit
        # dem benutzerdefinierten Von-/Bis-Panel ist entfallen); die Combos
        # sind kompakt, die Session-Checkboxen schmal.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)

        # --- Zeile 1: Data / Chart / Agg / Range / Sort / Sessions ------
        row1 = QHBoxLayout()
        row1.setSpacing(4)

        row1.addWidget(QLabel("Data:"))
        self._data_tf_combo = QComboBox()
        self._data_tf_combo.addItems(self._data_tf_options)
        self._data_tf_combo.setMaximumWidth(105)
        self._data_tf_combo.setToolTip(
            "Source-Data-TF: 🌐 alle Timeframes (Multi) vs. 🔒 fixiert auf einen TF")
        self._data_tf_combo.currentTextChanged.connect(self._on_data_tf_changed)
        row1.addWidget(self._data_tf_combo)

        row1.addSpacing(6)
        row1.addWidget(QLabel("Chart:"))
        self._chart_tf_combo = QComboBox()
        self._chart_tf_combo.addItems(CHART_TF_OPTIONS)
        self._chart_tf_combo.setMaximumWidth(85)
        self._chart_tf_combo.setToolTip(
            "Chart-Overlay-TF: ⚡ Auto (Kaskade) vs. 🔒 manuell fixiert")
        self._chart_tf_combo.currentTextChanged.connect(self._on_chart_tf_changed)
        row1.addWidget(self._chart_tf_combo)

        # 21.03.12 (Entscheidung 6a): Aggregations-TF-Dropdown – nur bei
        # '🔒 Fix' aktiv; bei '⚡ Auto' deaktiviert und auf 'Auto' gesetzt.
        row1.addSpacing(6)
        row1.addWidget(QLabel("Agg:"))
        self._agg_tf_combo = QComboBox()
        self._agg_tf_combo.addItems(self._agg_tf_options)
        self._agg_tf_combo.setMaximumWidth(95)
        self._agg_tf_combo.setToolTip(
            "Aggregations-TF (21.03.12, 6a): ⚡ Auto = Granularitaet dynamisch "
            "an den Zeitraum anpassen; 🔒 Fix = Daten starr auf diesem TF-Raster "
            "zusammenfassen (eigenes Dropdown, unabhaengig von Data-TF).")
        self._agg_tf_combo.currentTextChanged.connect(self._on_agg_tf_changed)
        self._agg_tf_combo.setEnabled(False)
        row1.addWidget(self._agg_tf_combo)

        row1.addSpacing(6)
        row1.addWidget(QLabel("Range:"))
        self._range_combo = QComboBox()
        self._range_combo.addItems(RANGE_PRESETS)
        self._range_combo.setMaximumWidth(100)
        self._range_combo.setToolTip(
            "Zeitfenster-Preset (24h/7d/30d/90d/Year) – filtert den anzuzeigenden Zeitraum")
        self._range_combo.currentTextChanged.connect(self._on_range_changed)
        row1.addWidget(self._range_combo)

        row1.addSpacing(6)
        row1.addWidget(QLabel("Sort:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(SORT_MODES)
        self._sort_combo.setMaximumWidth(95)
        self._sort_combo.setToolTip(
            "Tabellen-Sortierung: Datum, Signal-Stärke oder Timeframe")
        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)
        row1.addWidget(self._sort_combo)

        # 21.03.15 (Bug 4): Session-Filter rechts neben der Sortierung in
        # Zeile 1 (die fruehere Zeile 2 mit dem benutzerdefinierten
        # Von-/Bis-Panel ist entfallen - Platzgewinn, eine Zeile).
        row1.addSpacing(6)
        self._session_checks: Dict[str, QCheckBox] = {}
        for session in SESSION_OPTIONS:
            cb = QCheckBox(session)
            cb.setToolTip("Session-Farbbalken im M1/M5-Zoom (UTC-Epochs)")
            cb.stateChanged.connect(self._on_sessions_changed)
            self._session_checks[session.lower()] = cb
            row1.addWidget(cb)

        row1.addStretch(1)
        outer.addLayout(row1)

    # ------------------------------------------------------------------
    # Public API (State-Sync über Provider, kein SQL)
    # ------------------------------------------------------------------
    def apply_namespace_state(self, context: Any) -> None:
        """Synchronisiert die Widgets aus dem MTF-FC-Namespace des Contexts.

        Wird z. B. nach `applyFullChartUpdate` aufgerufen, damit die
        Filterleiste die aktiven Werte (Data-TF, Chart-TF) anzeigt.
        """
        ns = self._provider.read_namespace(context)
        data_tf = str(ns.get("active_data_tf") or "M15")
        chart_tf = str(ns.get("active_chart_tf") or "M5")

        self._data_tf_combo.blockSignals(True)
        self._data_tf_combo.setCurrentText(_data_tf_label(data_tf))
        self._data_tf_combo.blockSignals(False)

        # 'auto' wird im Chart über die Kaskade bestimmt; bei fixiertem
        # aktiven Chart-TF bleibt die Auswahl auf '⚡ Auto (Kaskade)'.
        self._chart_tf_combo.blockSignals(True)
        self._chart_tf_combo.setCurrentText(CHART_TF_OPTIONS[0])
        self._chart_tf_combo.blockSignals(False)

    def current_data_tf(self) -> str:
        """Aktiver Source-Data-TF ('multi' oder z. B. 'M15')."""
        return _parse_data_tf(self._data_tf_combo.currentText())

    def current_chart_tf(self) -> str:
        """Aktiver Chart-Overlay-TF ('auto' oder 'fix')."""
        return _parse_chart_tf(self._chart_tf_combo.currentText())

    def current_agg_tf(self) -> str:
        """Aktiver Aggregations-TF ('auto' oder konkreter TF, z. B. 'H1')."""
        text = self._agg_tf_combo.currentText()
        for prefix in ("⚡ ", "🔒 "):
            if text.startswith(prefix):
                text = text[len(prefix):]
        stripped = text.strip()
        if not stripped or stripped.lower() in ("auto", "kaskade"):
            return "auto"
        return stripped

    def current_sort_mode(self) -> str:
        """Aktive Sortierung ('date' | 'signal' | 'tf')."""
        text = self._sort_combo.currentText()
        if text.startswith("Signal"):
            return "signal"
        if text.startswith("TF"):
            return "tf"
        return "date"

    # 13.08.2026 (Punkt 3, Teil 2, Bugfix Profile): Oeffentliche Lesemethoden
    # fuer den aktuellen Range-Zustand. Werden vom AnalyticsWindow beim
    # Profil-Speichern genutzt, um den ANGEZEIGTEN Filterleisten-Stand explizit
    # in die VM-Params zu uebernehmen (defensiver Sync vor save_profile()).
    def current_range_preset(self) -> str:
        """Aktiver Range-Preset-Name (z. B. '7d')."""
        return self._range_combo.currentText()

    def current_range_epochs(self) -> Tuple[int, int]:
        """Wanduhr-Epochs (from_ts, to_ts) fuer den aktuellen Preset.

        Gleiche Logik wie `_on_range_changed`: Referenzpunkt ist der
        injizierte `now_provider` (im Analytics der letzte Datenpunkt
        MAX(bar_time)), defensiv time.time(). None/leerer Preset -> 24h.
        """
        preset = self.current_range_preset()
        try:
            now = int(self._now_provider())
        except (TypeError, ValueError):
            now = int(_now_epoch())
        seconds = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400,
                   "90d": 90 * 86400, "Year": 365 * 86400}.get(
                       preset, 86400)
        return now - seconds, now

    # 21.03.12 (Analytics-Integration): Externe Filterwerte anwenden (z. B.
    # Profil-/Workspace-Restore des AnalyticsWindow). Setzt die Combos mit
    # blockSignals und emittiert die Signale danach EXPLIZIT. None = Eintrag
    # unveraendert lassen.
    # 21.03.14 (Wunsch 2): `sort_mode` stellt die Tabellen-Sortierung nach
    # Profil-/Workspace-Restore wieder her (die View-Template-Buttons wurden
    # rueckgebaut). 21.03.15 (Bug 3): Alt-Profile mit 'YTD'/'Benutzerdefiniert'
    # werden auf den neuen Preset-Satz (90d/Year, kein Custom-Panel) gemappt.
    def apply_external_state(
        self,
        data_tf: Optional[str] = None,
        agg_tf: Optional[str] = None,
        range_preset: Optional[str] = None,
        sort_mode: Optional[str] = None,
    ) -> None:
        """Wendet externe Filterwerte auf die Combos an (in-memory)."""
        if data_tf is not None:
            self._data_tf_combo.blockSignals(True)
            self._data_tf_combo.setCurrentText(_data_tf_label(data_tf))
            self._data_tf_combo.blockSignals(False)
            self.data_tf_changed.emit(self.current_data_tf())
        if agg_tf is not None:
            self._agg_tf_combo.blockSignals(True)
            if str(agg_tf).strip().lower() == "auto":
                self._agg_tf_combo.setCurrentText("⚡ Auto")
            else:
                self._agg_tf_combo.setCurrentText(_data_tf_label(agg_tf))
            self._agg_tf_combo.blockSignals(False)
            self.agg_tf_changed.emit(self.current_agg_tf())
        if sort_mode is not None:
            self._sort_combo.blockSignals(True)
            self._sort_combo.setCurrentText(
                {"date": SORT_MODES[0], "signal": SORT_MODES[1],
                 "tf": SORT_MODES[2]}.get(str(sort_mode), SORT_MODES[0]))
            self._sort_combo.blockSignals(False)
            self.sort_mode_changed.emit(self.current_sort_mode())
        if range_preset is not None:
            preset = str(range_preset).strip() or None
            if preset is not None:
                # 21.03.15 (Bug 3): Alt-Profile (YTD/Custom-Panel) auf den
                # neuen Preset-Satz abbilden, damit setCurrentText greift.
                if preset == "YTD":
                    preset = "Year"
                elif preset == "Benutzerdefiniert":
                    preset = "7d"
                self._range_combo.blockSignals(True)
                self._range_combo.setCurrentText(preset)
                self._range_combo.blockSignals(False)
                self._on_range_changed(preset)

    def set_chart_mode(self, mode: str) -> None:
        """Setzt den Chart-Modus ('auto'|'fix') – externer Kontext (Analytics).

        'fix' aktiviert das Aggregations-TF-Dropdown (Entscheidung 6a) und
        stellt einen konkreten Agg-TF sicher; 'auto' deaktiviert es (dynamische
        Granularitaet). Loeuft ueber die bestehende _on_chart_tf_changed-Logik
        (Enable/Disable + Vorbelegung) und emittiert chart_tf_changed +
        agg_tf_changed.
        """
        mode = "fix" if str(mode).strip().lower() == "fix" else "auto"
        self._chart_tf_combo.setCurrentText(
            CHART_TF_OPTIONS[1] if mode == "fix" else CHART_TF_OPTIONS[0])

    def active_sessions(self) -> List[str]:
        """Aktive Session-Filter (klein geschrieben)."""
        return [s for s, cb in self._session_checks.items() if cb.isChecked()]

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_data_tf_changed(self, _text: str) -> None:
        self.data_tf_changed.emit(self.current_data_tf())

    def _on_chart_tf_changed(self, _text: str) -> None:
        """Aktiviert/deaktiviert das Aggregations-TF-Dropdown (Entscheidung 6a).

        '⚡ Auto'  -> Agg-Combo deaktiviert und auf 'Auto' gesetzt (Granularitaet
                     wird dynamisch aus dem Zeitraum abgeleitet).
        '🔒 Fix'   -> Agg-Combo aktiv; ist noch kein konkreter TF gewaehlt,
                     wird der erste fixierte Eintrag vorbelegt (damit 'Fix'
                     IMMER einen konkreten Aggregations-TF liefert).
        """
        mode = self.current_chart_tf()
        self._agg_tf_combo.blockSignals(True)
        if mode == "auto":
            self._agg_tf_combo.setCurrentText("⚡ Auto")
            self._agg_tf_combo.setEnabled(False)
        else:
            if self.current_agg_tf() == "auto":
                for opt in self._agg_tf_options:
                    if not opt.startswith("⚡"):
                        self._agg_tf_combo.setCurrentText(opt)
                        break
            self._agg_tf_combo.setEnabled(True)
        self._agg_tf_combo.blockSignals(False)
        self.chart_tf_changed.emit(mode)
        self.agg_tf_changed.emit(self.current_agg_tf())

    def _on_agg_tf_changed(self, _text: str) -> None:
        self.agg_tf_changed.emit(self.current_agg_tf())

    def _on_range_changed(self, preset: str) -> None:
        """Range-Combo-Wechsel: Preset-Zeitraum emittieren.

        21.03.12 (Analytics): Referenzpunkt injizierbar – im Analytics der
        letzte Datenpunkt (MAX(bar_time)) statt time.time(), damit Presets
        relativ zum letzten Signal und nicht zur Wanduhr rechnen. Defensiv:
        None/Fehler (z. B. noch kein Symbol/Timeframe gewaehlt) -> time.time().
        21.03.15 (Bug 3): Preset-Satz 24h/7d/30d/90d/Year; 'Year' = letzte
        365 Tage (kein Jahresbeginn-Fenster mehr). Das benutzerdefinierte
        Von-/Bis-Panel ist entfallen. 13.08.2026 (Punkt 3): Die Epoch-
        Berechnung wurde in `current_range_epochs()` extrahiert (wird auch
        vom Profil-Save-Sync des AnalyticsWindow genutzt).
        """
        f, t = self.current_range_epochs()
        self.range_changed.emit(preset, f, t)

    def _on_sort_changed(self, _text: str) -> None:
        self.sort_mode_changed.emit(self.current_sort_mode())

    def _on_sessions_changed(self, _state: int) -> None:
        self._sessions = self.active_sessions()
        self.sessions_changed.emit(list(self._sessions))

    # ------------------------------------------------------------------
    # Guard-Override (Ebene 2, 21.03.05) – Klick auf Reset-Badge
    # ------------------------------------------------------------------
    def request_guard_override(self, target_tf: str, reason: str = "ghost_marker_click") -> None:
        """Leitet einen Geister-Marker-Klick an die State-Machine weiter."""
        self.guard_override_requested.emit(target_tf, reason)


def _now_epoch() -> int:
    """Aktuelle Wanduhr-Epoch (Sekunden)."""
    import time
    return int(time.time())

```

--------------------------------------------------

### DATEI: chart/widgets/named_item_actions.py
```py
# chart/widgets/named_item_actions.py
"""
Generische Neu-/Speichern-/Löschen-Logik für benannte Sammlungen
(Presets, Service-Sets) – analog zur Preset-Verwaltung im Prop-Fenster.

Warum: Die Service-Set-Verwaltung (Indikator-Prop-Fenster + Service-Fenster)
soll identisch zur bewährten Preset-Mechanik im Indikator-Prop-Fenster
funktionieren. Statt die Dialog-Logik an mehreren Stellen zu duplizieren,
liegt sie hier ZENTRAL im NamedItemActionsMixin; die Aufrufer liefern nur
noch einen NamedItemAdapter mit den _item_*-Protokoll-Methoden.

Mechanik (identisch zur Preset-Verwaltung):
  * SPEICHERN (save_named_item(adapter, ...)):
      - Namensdialog (QInputDialog.getText), vorbelegt mit dem aktuellen Namen.
      - Leerer Name  → Auto-Name, falls der Adapter einen liefert
        (_item_auto_name, z.B. 'grid_1 + prox_1'), sonst Abbruch mit Hinweis.
      - Geschützter Name (z.B. 'Default') → Ablehnung.
      - Name bereits vergeben → Überschreiben-Rückfrage (QMessageBox.question).
      - Danach speichern (_item_save_as, liefert die neue ID) und die Auswahl
        auf das gespeicherte Element setzen (_item_select(id)).
  * LÖSCHEN (delete_named_item(adapter)):
      - Geschützter Name → Ablehnung.
      - Rückfrage (QMessageBox.question, Default = Nein).
      - Danach löschen (_item_delete_current) und das nächstverfügbare Element
        auswählen (_item_select(None)).

Die UI-Interaktion (Dialoge, Rückfragen, Ablauf) ist damit exakt einmal
implementiert und für Presets UND Service-Sets identisch.

Hinweis (Adapter-Design): Ein Dialog/Window kann MEHRERE benannte Sammlungen
verwalten (z.B. Presets + Service-Sets im Indikator-Prop-Fenster). Die
_item_*-Callbacks dürfen daher NICHT auf der Dialog-Klasse selbst liegen –
zwei Callback-Sätze würden sich sonst gegenseitig überschreiben (gleiche
Methodennamen). Stattdessen implementiert pro Sammlung EIN NamedItemAdapter
die _item_*-Methoden und wird beim Aufruf an das Mixin übergeben.
"""

from typing import Any, List, Optional

from PySide6.QtWidgets import QInputDialog, QMessageBox


class NamedItemAdapter:
    """Protokoll/Basisklasse für EINE benannte Sammlung (Presets / Service-Sets).

    Ein Adapter kapselt die Sammlungsspezifik (Namen, Listen, Persistenz,
    Auswahl) und greift dazu auf das Host-Widget (Dialog/Fenster) zu – der
    Host hält dafür eine Referenz auf den Adapter (z.B. self._set_adapter).
    """

    def _item_scope_label(self) -> str:
        """Anzeigename der Sammlung, z.B. 'Service-Set' / 'Preset'."""
        raise NotImplementedError

    def _item_current_name(self) -> str:
        """Aktueller Name des bearbeiteten Elements (Editor/Combo)."""
        raise NotImplementedError

    def _item_current_id(self) -> Optional[str]:
        """Aktuelle ID des bearbeiteten Elements (oder None bei neu)."""
        raise NotImplementedError

    def _item_auto_name(self) -> str:
        """Auto-Name bei leerem Namensfeld (z.B. 'grid_1 + prox_1').

        Leerer String → der Mixin bricht mit einem Hinweis ab (Preset-
        Verhalten). Service-Sets liefern hier den Default-Name aus den
        instance_ids (Roadmap: 'leerer Name → Auto-Name').
        """
        return ""

    def _item_list_names(self) -> List[str]:
        """Alle vorhandenen Namen der Sammlung."""
        raise NotImplementedError

    def _item_exists(self, name: str) -> bool:
        """True, wenn 'name' bereits von einem ANDEREN Element vergeben ist."""
        raise NotImplementedError

    def _item_save_as(self, name: str) -> Optional[Any]:
        """Speichert das Element unter 'name' und liefert die neue ID zurück.

        None → Speichern wurde abgebrochen (z.B. ungültige Sammlung); der
        Mixin überspringt dann die Auswahl-Aktualisierung.
        """
        raise NotImplementedError

    def _item_delete_current(self) -> bool:
        """Löscht das aktuelle Element; liefert True bei Erfolg."""
        raise NotImplementedError

    def _item_select(self, name_or_id: Optional[Any] = None) -> None:
        """Setzt die Auswahl: nach dem Speichern auf das neue Element,
        nach dem Löschen (name_or_id=None) auf das nächstverfügbare."""
        raise NotImplementedError

    def _item_reserved_name(self) -> Optional[str]:
        """Geschützter Name (z.B. 'Default' für Presets) oder None."""
        return None


class NamedItemActionsMixin:
    """Mixin für benannte Sammlungen (Presets / Service-Sets).

    Liefert save_named_item(adapter)/delete_named_item(adapter) mit der
    Preset-Mechanik; der Adapter (NamedItemAdapter) kapselt die
    Sammlungsspezifik. Die UI-Interaktion ist damit exakt einmal implementiert.
    """

    # ------------------------------------------------------------------
    # Preset-analoge Mechanik (ZENTRAL – für Presets und Service-Sets)
    # ------------------------------------------------------------------
    def save_named_item(self, adapter: NamedItemAdapter,
                        dialog_title: Optional[str] = None,
                        prompt: Optional[str] = None) -> None:
        """Speichert ein Element analog zur Preset-Verwaltung.

        Ablauf: Namensdialog → Auto-Name bei leerem Feld → Schutz des
        reservierten Namens → Überschreiben-Rückfrage bei doppeltem Namen →
        speichern (adapter._item_save_as) → Auswahl aktualisieren
        (adapter._item_select).
        """
        scope = adapter._item_scope_label()
        title = dialog_title or f"{scope} speichern"
        label = prompt or f"Name für das {scope}:"
        current = adapter._item_current_name()

        name, ok = QInputDialog.getText(self, title, label, text=current)
        if not ok:
            return  # Benutzer abgebrochen

        clean = name.strip()
        if not clean:
            auto = adapter._item_auto_name()
            if not auto:
                QMessageBox.warning(self, "Fehler",
                                    "Der Name darf nicht leer sein.")
                return
            clean = auto

        reserved = adapter._item_reserved_name()
        if reserved and clean.lower() == reserved.lower():
            QMessageBox.warning(
                self, "Fehler",
                f"Der Name '{reserved}' ist geschützt und kann nicht "
                f"überschrieben werden.",
            )
            return

        if adapter._item_exists(clean):
            reply = QMessageBox.question(
                self, "Überschreiben bestätigen",
                f"{scope} '{clean}' existiert bereits.\n"
                f"Möchtest du es überschreiben?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        new_id = adapter._item_save_as(clean)
        if new_id is not None:
            adapter._item_select(new_id)

    def delete_named_item(self, adapter: NamedItemAdapter,
                          confirm: bool = True) -> None:
        """Löscht das aktuelle Element analog zur Preset-Verwaltung.

        Ablauf: Schutz des reservierten Namens → (optional) Rückfrage →
        löschen (adapter._item_delete_current) → nächstes Element auswählen
        (adapter._item_select(None)).

        Bugfix 05.08.2026 (Papierkorb): Service-Sets werden soft-deleted –
        der Aufrufer (ServiceWindow.delete_set) fragt bereits einmal nach
        ('Set in den Papierkorb verschieben') und ruft diese Methode mit
        confirm=False auf, damit KEINE zweite Rückfrage erscheint. Die
        Preset-Verwaltung (ohne Papierkorb) behält confirm=True (Default).
        """
        scope = adapter._item_scope_label()
        current = adapter._item_current_name()
        if not current:
            return

        reserved = adapter._item_reserved_name()
        if reserved and current == reserved:
            QMessageBox.warning(self, "Fehler",
                                f"'{reserved}' kann nicht gelöscht werden.")
            return

        if confirm:
            reply = QMessageBox.question(
                self, "Löschen bestätigen",
                f"Möchtest du {scope} '{current}' wirklich löschen?\n"
                f"Dies kann nicht rückgängig gemacht werden.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        adapter._item_delete_current()
        adapter._item_select(None)

```

--------------------------------------------------

### DATEI: chart/widgets/style_picker_widget.py
```py
# chart/widgets/style_picker_widget.py
# Phase 16 (06.08.2026): Generischer Stil-Waehler - ersetzt ColorButton
# (chart/widgets/color_button.py).
#
# Phase 16.06.01 (07.08.2026): Popover StylePickerDialog & Button-Only-Cleanup.
# Das bisherige Inline-Composite (QCheckBox + Farb-Button + QSpinBox +
# QComboBox direkt in der Formularzeile) wurde entfernt: Das StylePickerWidget
# besteht jetzt AUSSCHLIESSLICH aus einem kompakten QPushButton (Farb-Swatch
# als Icon + Vorschau-Text, z.B. '● 2px Solid' bzw. '● Circle'). Erst ein
# Klick oeffnet den modalen StylePickerDialog (exec):
#   * Oberer Bereich: kompaktes Custom-Color-Grid (TradingView-Palette +
#     Hex/RGB-Eingabe + Transparenz-Slider 0-100% + [Anpassen...]-Fallback
#     auf QColorDialog.getColor()). KEIN QColorDialog(Qt.Widget).
#   * QFrame.HLine-Trennlinie.
#   * Unterer Bereich (QFormLayout): Zeichnungsparameter (style_type='line':
#     Linienstaerke 1-10 px + Linienart solid/dashed/dotted/dashdotted;
#     style_type='marker': Markergroesse 1-20 px + Markerform
#     circle/square/arrowUp/arrowDown). Optional 'sichtbar'-Checkbox, wenn
#     show_visibility=True.
#   * QDialogButtonBox [Abbrechen] / [Übernehmen].
# Bei color_only=True werden Trennlinie und unterer Bereich per
# setVisible(False) ausgeblendet und der Dialog auf die reine Farbwahl
# verkleinert.
#
# SCHNITTSTELLEN-INVARIANTE (Refactoring-Anweisung 16.06.01, Kapitel 5):
# Die Fassade von StylePickerWidget bleibt 1:1 erhalten, damit
# indicator_dialog.py (get_style/set_style/set_color, style_type/color_only/
# show_visibility, Signal style_changed, innerer Zugriff
# ctrl.get_style().color) unveraendert weiterlaeuft:
#   * Methoden: get_style(), set_style(obj), set_color(color_str), color()
#   * Properties: style_type ("line"|"marker"), color_only (bool),
#     show_visibility (bool)
#   * Signal: style_changed(object) - emittiert bei Uebernahme im Dialog das
#     aktualisierte LineStyle- bzw. MarkerStyle-Objekt.
#
# Die Style-Vertraege LineStyle/MarkerStyle leben zentral in
# `chart/overlays/style_models.py` (to_js_dict / to_dict / from_dict).
#
# Farb-Logik (Paritaet zum Alt-ColorButton / Inline-Composite):
#   - Alpha == 255 -> '#RRGGBB' (Hex, Grossbuchstaben, volle Deckkraft).
#   - Alpha < 255  -> 'rgba(r, g, b, a)' mit a als Float (0..1) -
#                     1:1 kompatibel mit TradingView Lightweight Charts v5
#                     (WebEngine) und HTML/CSS.

from typing import Optional, Union

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chart.overlays.style_models import (
    LINE_STYLES,
    MARKER_SHAPES,
    LineStyle,
    MarkerStyle,
)


# ---------------------------------------------------------------------------
# Modul-Helfer (Palette + Farb-Konvertierung)
# ---------------------------------------------------------------------------

#: Kompakte Schnell-Auswahl-Palette (TradingView-Standardfarben).
_PALETTE_COLORS: list = [
    "#2962FF", "#089981", "#FF6D00", "#F23645",
    "#B47157", "#FF9800", "#FFEB3B", "#787B86",
    "#E91E63", "#9C27B0", "#3F51B5", "#009688",
    "#4CAF50", "#FF5722", "#795548", "#607D8B",
]


def _format_color(color: QColor) -> str:
    """Farb-String aus einem QColor (Paritaet zum Alt-ColorButton):
    Alpha == 255 -> '#RRGGBB' (Hex, Grossbuchstaben), sonst
    'rgba(r, g, b, a)' mit a als Float (0..1, LWC-v5-kompatibel).
    """
    if not color.isValid():
        return "#000000"
    if color.alpha() < 255:
        a = round(color.alpha() / 255.0, 2)
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {a})"
    return color.name().upper()


def _parse_color(color_str: str) -> Optional[QColor]:
    """Parst Hex- oder rgba(...)-Strings in ein QColor (oder None)."""
    s = (color_str or "").strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith("rgba("):
        try:
            inner = s[s.index("(") + 1:s.rindex(")")]
            parts = [p.strip() for p in inner.split(",")]
            if len(parts) != 4:
                return None
            r = int(round(float(parts[0])))
            g = int(round(float(parts[1])))
            b = int(round(float(parts[2])))
            a_frac = float(parts[3])
        except (ValueError, TypeError):
            return None
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        alpha = max(0, min(255, int(round(a_frac * 255))))
        return QColor(r, g, b, alpha)
    c = QColor(s)
    return c if c.isValid() else None


# ---------------------------------------------------------------------------
# StylePickerDialog (modaler Popover)
# ---------------------------------------------------------------------------

class StylePickerDialog(QDialog):
    """Modaler Popover-Dialog fuer den StylePicker (Phase 16.06.01).

    Vertikal zweigeteilt:
      1. **Oberer Bereich:** kompaktes Custom-Color-Grid (Palette-Schnellwahl
         + Hex/RGB-Eingabefeld + Transparenz-Slider 0-100% +
         [Anpassen...]-Fallback auf QColorDialog.getColor()).
      2. **Trennlinie:** QFrame.HLine (Sunken).
      3. **Unterer Bereich (QFormLayout):** Zeichnungsparameter.
         * style_type='line':  Linienstaerke (QSpinBox 1-10 px) + Linienart
           (QComboBox: solid/dashed/dotted/dashdotted).
         * style_type='marker': Markergroesse (QSpinBox 1-20 px) +
           Markerform (QComboBox: circle/square/arrowUp/arrowDown).
         * Optional 'sichtbar'-Checkbox, wenn show_visibility=True.
      4. **Buttons:** QDialogButtonBox [Abbrechen] / [Übernehmen].

    Bei color_only=True werden Trennlinie und unterer Bereich per
    setVisible(False) ausgeblendet und der Dialog auf die reine Farbwahl
    verkleinert (adjustSize).

    get_style() liefert nach Uebernahme (accept) ein frisches
    LineStyle-/MarkerStyle-Objekt mit allen uebernommenen Werten.
    """

    def __init__(
        self,
        style: Optional[Union[LineStyle, MarkerStyle]] = None,
        style_type: str = "line",
        color_only: bool = False,
        enable_alpha: bool = True,
        show_visibility: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._style_type: str = "marker" if style_type == "marker" else "line"
        self._color_only: bool = bool(color_only)
        self._enable_alpha: bool = bool(enable_alpha)
        self._show_visibility: bool = bool(show_visibility)

        # Arbeitskopie des Style-Objekts (Typ passend zum Modus).
        if self._style_type == "marker":
            self._style: MarkerStyle = (
                style if isinstance(style, MarkerStyle) else MarkerStyle()
            )
        else:
            self._style: LineStyle = (
                style if isinstance(style, LineStyle) else LineStyle()
            )
        self._color: QColor = QColor()

        self.setWindowTitle("Farbe & Stil" if not self._color_only else "Farbe")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # --- Oberer Bereich: Farbe -----------------------------------------
        layout.addLayout(self._build_color_area())

        # --- Trennlinie ----------------------------------------------------
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.HLine)
        self._separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(self._separator)

        # --- Unterer Bereich: Zeichnungsparameter --------------------------
        self._params_widget = self._build_params_widget()
        layout.addWidget(self._params_widget)

        # --- Buttons -------------------------------------------------------
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = self._button_box.button(QDialogButtonBox.Ok)
        cancel_btn = self._button_box.button(QDialogButtonBox.Cancel)
        ok_btn.setText("Übernehmen")
        cancel_btn.setText("Abbrechen")
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

        # --- Initialwerte aus dem uebergebenen Style ------------------------
        self._apply_style_to_ui(self._style)
        self._set_color_internal(self._style.color)

        # --- color_only: Trennlinie + unterer Bereich ausblenden, kompakt ---
        if self._color_only:
            self._separator.setVisible(False)
            self._params_widget.setVisible(False)
        self.adjustSize()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------

    def _build_color_area(self) -> QVBoxLayout:
        """Oberer Farbbereich: Palette-Grid + Hex/RGB-Eingabe + Alpha-Slider.

        Bewusst KEIN QColorDialog(Qt.Widget)-Trick: Der native Dialog zeigt
        unter Windows 11 / Qt 6 Rendering-Macken und einen grossen Footprint.
        Der [Anpassen...]-Button oeffnet QColorDialog.getColor() nur als
        modalen Fallback.
        """
        area = QVBoxLayout()
        area.setSpacing(6)

        # 1) Palette-Grid (TradingView-Schnellwahl, Quick-Click)
        grid = QGridLayout()
        grid.setSpacing(3)
        for i, hex_color in enumerate(_PALETTE_COLORS):
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(hex_color)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {hex_color}; "
                f"border: 1px solid #555555; border-radius: 3px; }}")
            btn.clicked.connect(
                lambda _=False, c=hex_color: self._set_color_internal(c))
            grid.addWidget(btn, i // 8, i % 8)
        area.addLayout(grid)

        # 2) Vorschau-Swatch + Hex/RGB-Eingabe + [Anpassen...]
        row = QHBoxLayout()
        row.setSpacing(6)
        self._preview = QLabel()
        self._preview.setObjectName("StylePickerPreview")
        self._preview.setFixedSize(40, 24)
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setToolTip("Aktuelle Farbe")
        row.addWidget(self._preview)

        self._hex_edit = QLineEdit()
        self._hex_edit.setPlaceholderText("#RRGGBB / rgb(r,g,b)")
        self._hex_edit.setToolTip("Exakter Farbcode (Hex oder rgb/rgba)")
        self._hex_edit.editingFinished.connect(self._on_hex_edited)
        row.addWidget(self._hex_edit, 1)

        self._custom_btn = QPushButton("Anpassen...")
        self._custom_btn.setToolTip("System-Farbpalette öffnen (QColorDialog)")
        self._custom_btn.clicked.connect(self._open_custom_color_dialog)
        row.addWidget(self._custom_btn)
        area.addLayout(row)

        # 3) Transparenz-Slider (0-100 %)
        self._alpha_container = QWidget()
        alpha_layout = QHBoxLayout(self._alpha_container)
        alpha_layout.setContentsMargins(0, 0, 0, 0)
        alpha_layout.setSpacing(6)
        alpha_layout.addWidget(QLabel("Transparenz:"))
        self._alpha_slider = QSlider(Qt.Horizontal)
        self._alpha_slider.setRange(0, 100)
        self._alpha_slider.setToolTip(
            "Transparenz (0% = deckend, 100% = unsichtbar)")
        self._alpha_slider.valueChanged.connect(self._on_alpha_changed)
        alpha_layout.addWidget(self._alpha_slider, 1)
        self._alpha_label = QLabel("0%")
        self._alpha_label.setFixedWidth(36)
        alpha_layout.addWidget(self._alpha_label)
        # enable_alpha=False: Slider ausblenden (Schema-Flag 'allow_alpha').
        self._alpha_container.setVisible(self._enable_alpha)
        area.addWidget(self._alpha_container)

        return area

    def _build_params_widget(self) -> QWidget:
        """Unterer Bereich: Zeichnungsparameter (width|size + style|shape).

        Optional eine 'sichtbar'-Checkbox (show_visibility=True), wenn die
        Sichtbarkeit nicht ueber einen separaten 'show_*'-Parameter laeuft.
        """
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        self._show_check = QCheckBox("sichtbar")
        self._show_check.setToolTip(
            "Element anzeigen" if self._style_type == "line"
            else "Marker anzeigen")
        if self._show_visibility:
            form.addRow("", self._show_check)

        self._param_spin = QSpinBox()
        if self._style_type == "marker":
            self._param_spin.setRange(1, 20)
            self._param_spin.setSuffix(" px")
            self._param_spin.setToolTip("Markergröße in Pixel")
            form.addRow("Markergröße:", self._param_spin)
        else:
            self._param_spin.setRange(1, 10)
            self._param_spin.setSuffix(" px")
            self._param_spin.setToolTip("Linienstärke in Pixel")
            form.addRow("Linienstärke:", self._param_spin)

        self._param_combo = QComboBox()
        if self._style_type == "marker":
            self._param_combo.addItems(list(MARKER_SHAPES))
            self._param_combo.setToolTip("Marker-Form")
            form.addRow("Markerform:", self._param_combo)
        else:
            self._param_combo.addItems(list(LINE_STYLES))
            self._param_combo.setToolTip("Linienart")
            form.addRow("Linienart:", self._param_combo)

        return w

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    def get_style(self) -> Union[LineStyle, MarkerStyle]:
        """Liefert den aktuell im Dialog eingestellten Stil als NEUES Objekt.

        Beruecksichtigt Farbe (inkl. Transparenz), width|size und style|shape
        sowie - falls show_visibility=True - den Zustand der
        'sichtbar'-Checkbox.
        """
        show = (self._show_check.isChecked()
                if self._show_visibility else bool(self._style.show))
        if self._style_type == "marker":
            return MarkerStyle(
                show=show,
                color=self._color_str(),
                shape=str(self._param_combo.currentText()),
                size=int(self._param_spin.value()),
            )
        return LineStyle(
            show=show,
            color=self._color_str(),
            width=int(self._param_spin.value()),
            style=str(self._param_combo.currentText()),
        )

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _apply_style_to_ui(
        self, style: Union[LineStyle, MarkerStyle]
    ) -> None:
        """Uebernimmt ein Style-Objekt in die Dialog-Controls."""
        if self._style_type == "marker" and isinstance(style, MarkerStyle):
            self._show_check.setChecked(bool(style.show))
            self._param_spin.setValue(int(style.size))
            self._param_combo.setCurrentText(
                style.shape if style.shape in MARKER_SHAPES else "circle")
        elif self._style_type == "line" and isinstance(style, LineStyle):
            self._show_check.setChecked(bool(style.show))
            self._param_spin.setValue(int(style.width))
            self._param_combo.setCurrentText(
                style.style if style.style in LINE_STYLES else "solid")

    def _set_color_internal(self, color_str: str) -> None:
        """Setzt die Farbe aus einem Hex-/rgba()-String (ungueltig -> ignoriert)."""
        parsed = _parse_color(color_str)
        if parsed is not None:
            self._set_color_qcolor(parsed)

    def _set_color_qcolor(self, color: QColor) -> None:
        """Uebernimmt ein QColor in Hex-Feld, Alpha-Slider und Vorschau."""
        self._color = QColor(color)
        self._hex_edit.blockSignals(True)
        self._hex_edit.setText(_format_color(self._color))
        self._hex_edit.blockSignals(False)
        transparency = 100 - int(round(self._color.alpha() * 100 / 255))
        self._alpha_slider.blockSignals(True)
        self._alpha_slider.setValue(transparency)
        self._alpha_slider.blockSignals(False)
        self._alpha_label.setText(f"{transparency}%")
        self._update_preview()

    def _color_str(self) -> str:
        """Aktuelle Dialog-Farbe als String (hex/rgba, Paritaet)."""
        return _format_color(getattr(self, "_color", QColor()))

    def _update_preview(self) -> None:
        """Setzt das Vorschau-Swatch auf die aktuelle Farbe inkl. Deckkraft."""
        c = self._color if self._color.isValid() else QColor("#000000")
        self._preview.setStyleSheet(
            "QLabel#StylePickerPreview { background-color: "
            f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha() / 255.0}); "
            "border: 1px solid #555555; border-radius: 3px; }"
        )

    def _on_hex_edited(self) -> None:
        """Hex/RGB-Eingabe: gueltiger Farbcode wird uebernommen."""
        parsed = _parse_color(self._hex_edit.text())
        if parsed is not None:
            self._set_color_qcolor(parsed)

    def _on_alpha_changed(self, value: int) -> None:
        """Transparenz-Slider (0-100%) -> Alpha-Kanal (255-0)."""
        self._alpha_label.setText(f"{value}%")
        c = QColor(self._color)
        c.setAlpha(int(round((100 - value) * 255 / 100)))
        self._set_color_qcolor(c)

    def _open_custom_color_dialog(self) -> None:
        """Fallback: modaler QColorDialog.getColor() (optional mit Alpha)."""
        options = QColorDialog.ColorDialogOption(0)
        if self._enable_alpha:
            options |= QColorDialog.ColorDialogOption.ShowAlphaChannel
        chosen = QColorDialog.getColor(
            self._color, self, "Farbe anpassen", options)
        if chosen.isValid():
            self._set_color_qcolor(chosen)


# ---------------------------------------------------------------------------
# StylePickerWidget (Button-Only)
# ---------------------------------------------------------------------------

class StylePickerWidget(QWidget):
    """Kombinierter Stil-Waehler – kompakter Button (Phase 16.06.01).

    Das Widget besteht ausschliesslich aus einem QPushButton (Farb-Swatch als
    Icon + Vorschau-Text, z.B. '● 2px Solid' bzw. '● Circle'). Ein Klick
    oeffnet den modalen StylePickerDialog (exec); bei Uebernahme wird das
    geaenderte LineStyle-/MarkerStyle-Objekt uebernommen und style_changed
    emittiert.

    SCHNITTSTELLEN-INVARIANTE (16.06.01): Die Fassade bleibt 1:1 gegenueber
    dem frueheren Inline-Composite erhalten (indicator_dialog.py haengt daran):
      * get_style()/set_style()/set_color()/color()
      * Properties style_type, color_only, show_visibility
      * Signal style_changed(object)
    """

    style_changed = Signal(object)

    # Kompakter Button: Swatch-Icon (16x16) + Vorschau-Text.
    _SWATCH_W = 16
    _SWATCH_H = 16

    def __init__(
        self,
        style: Optional[Union[LineStyle, MarkerStyle]] = None,
        enable_alpha: bool = True,
        parent=None,
        style_type: str = "line",
        color_only: bool = False,
        show_visibility: bool = True,
    ) -> None:
        super().__init__(parent)
        self._enable_alpha: bool = bool(enable_alpha)
        # color_only: Reiner Farbwaehler - der Dialog zeigt dann NUR den
        # Farbbereich (Trennlinie + Zeichnungsparameter werden ausgeblendet).
        self._color_only: bool = bool(color_only)
        # show_visibility: Wenn die Sichtbarkeit ueber einen separaten
        # 'show_*'-Parameter laeuft (Multi-MA: show_maX, FixedGridProximity:
        # show_lines/show_circles), zeigt der Dialog KEINE 'sichtbar'-
        # Checkbox (get_style() liefert dann show=True aus dem Style-Objekt).
        self._show_visibility: bool = bool(show_visibility)
        # style_type: "line" (LineStyle) | "marker" (MarkerStyle)
        self._style_type: str = "marker" if style_type == "marker" else "line"
        if self._style_type == "marker":
            self._style: MarkerStyle = (
                style if isinstance(style, MarkerStyle) else MarkerStyle()
            )
        else:
            self._style: LineStyle = (
                style if isinstance(style, LineStyle) else LineStyle()
            )
        self._color: QColor = QColor()

        # --- Einziger sichtbarer Bestandteil: der kompakte Button ------------
        self._btn = QPushButton()
        self._btn.setObjectName("StylePickerSwatch")
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setToolTip(
            "Stil festlegen (Farbe, Stärke, Art)" if not self._color_only
            else "Farbe auswählen (inkl. Transparenz)")
        self._btn.setStyleSheet(
            "QPushButton#StylePickerSwatch { border: 1px solid #555555; "
            "border-radius: 3px; padding: 2px 8px; }"
        )
        self._btn.clicked.connect(self._open_picker_dialog)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._btn)
        layout.addStretch(1)

        self._set_color_internal(self._style.color)
        self._update_swatch()

    # ------------------------------------------------------------------
    # Oeffentliche API (Invariante 16.06.01)
    # ------------------------------------------------------------------

    @property
    def style_type(self) -> str:
        """Aktueller Widget-Modus: 'line' (LineStyle) oder 'marker' (MarkerStyle)."""
        return self._style_type

    @property
    def color_only(self) -> bool:
        """True = reiner Farbwaehler (Dialog zeigt nur den Farbbereich).

        Der Dialog nutzt dieses Flag, um die Geschwister-Keys (style/width
        bzw. shape/size) beim Persistieren zu UEBERSPRINGEN - ein reiner
        Farb-Parameter besitzt keine solchen Geschwister.
        """
        return self._color_only

    @property
    def show_visibility(self) -> bool:
        """True = Dialog zeigt eine 'sichtbar'-Checkbox (Default).

        False = keine Checkbox; get_style() liefert dann show=True, weil die
        Sichtbarkeit ein separater 'show_*'-Parameter steuert (Multi-MA:
        show_maX, FixedGridProximity: show_lines/show_circles).
        """
        return self._show_visibility

    def get_style(self) -> Union[LineStyle, MarkerStyle]:
        """Liefert den aktuellen Stil als NEUES Style-Objekt (LineStyle bei
        style_type='line', MarkerStyle bei style_type='marker').

        Es wird eine frische Instanz zurueckgegeben, damit externe Aenderungen
        den internen Zustand nicht unbeabsichtigt mutieren.
        """
        if self._style_type == "marker":
            return MarkerStyle(
                show=bool(self._style.show),
                color=self._color_button_value(),
                shape=str(self._style.shape),
                size=int(self._style.size),
            )
        return LineStyle(
            show=bool(self._style.show),
            color=self._color_button_value(),
            width=int(self._style.width),
            style=str(self._style.style),
        )

    def set_style(self, style: Union[LineStyle, MarkerStyle]) -> None:
        """Setzt den Stil aus einem Style-Objekt und aktualisiert die Vorschau.

        Akzeptiert LineStyle und MarkerStyle. Emittiert bewusst KEIN
        style_changed (programmatisches Setzen).
        """
        if style is None:
            return
        self._style = style
        self._set_color_internal(style.color)
        self._update_swatch()

    def set_color(self, color_str: str) -> None:
        """Setzt ausschliesslich die Farbe (behaelt show/width|size/style|shape).

        Wird vom indicator_dialog-Restore-Pfad genutzt, der aus einem
        Farb-Parameter ('type: color') nur den Farbanteil zurueckliest und
        wiederherstellt. Emittiert KEIN style_changed.
        """
        self._set_color_internal(color_str)

    def color(self) -> str:
        """Kompatibilitaets-Shim: aktuelle Farbe als String (hex/rgba)."""
        return self._color_button_value()

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _open_picker_dialog(self) -> None:
        """Oeffnet den modalen StylePickerDialog (exec) und uebernimmt das
        geaenderte Style-Objekt bei 'Übernehmen'. Emittiert style_changed."""
        dlg = StylePickerDialog(
            self.get_style(), style_type=self._style_type,
            color_only=self._color_only, enable_alpha=self._enable_alpha,
            show_visibility=self._show_visibility, parent=self)
        if dlg.exec() == QDialog.Accepted:
            new_style = dlg.get_style()
            self._style = new_style
            self._set_color_internal(new_style.color)
            self._update_swatch()
            self.style_changed.emit(new_style)

    def _color_button_value(self) -> str:
        """Farb-String aus dem internen QColor (Paritaet zum Alt-ColorButton)."""
        return _format_color(getattr(self, "_color", QColor()))

    def _set_color_internal(self, color_str: str) -> None:
        """Parst einen Hex-/rgba()-String und aktualisiert Swatch + Zustand.

        Ungueltige Eingaben werden ignoriert (bisherige Farbe bleibt erhalten).
        """
        parsed = _parse_color(color_str)
        if parsed is not None:
            self._color = parsed
            self._update_swatch()

    def _make_swatch_icon(self) -> QIcon:
        """Farb-Swatch-Icon (16x16) in der aktuellen Farbe inkl. Deckkraft."""
        c = self._color if self._color.isValid() else QColor("#000000")
        pm = QPixmap(self._SWATCH_W, self._SWATCH_H)
        pm.fill(QColor(c.red(), c.green(), c.blue(), c.alpha()))
        return QIcon(pm)

    def _preview_text(self) -> str:
        """Vorschau-Text des Buttons: '● 2px Solid' bzw. '● Circle'."""
        if self._style_type == "marker":
            return f"● {self._style.shape.capitalize()}"
        return f"● {int(self._style.width)}px {self._style.style.capitalize()}"

    def _update_swatch(self) -> None:
        """Setzt Swatch-Icon + Vorschau-Text des Buttons auf den aktuellen Stil."""
        self._btn.setIcon(self._make_swatch_icon())
        self._btn.setText(self._preview_text())

```

--------------------------------------------------

