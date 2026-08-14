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
