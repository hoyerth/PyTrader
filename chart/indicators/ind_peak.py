# chart/indicators/ind_peak.py (Teil 1: Live-State-Machine)
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
    """O(1) Live-Peak-Tracker (Scalar-State, Parität zu compute_batch)."""

    def __init__(self, cfg: PeakConfig) -> None:
        self.cfg = cfg
        self.cur_high_price: float = np.nan
        self.cur_high_idx: int = -1
        self.cur_high_sl: float = np.nan
        self.cur_low_price: float = np.nan
        self.cur_low_idx: int = -1
        self.cur_low_sl: float = np.nan

    def reset(self) -> None:
        self.cur_high_price = np.nan
        self.cur_high_idx = -1
        self.cur_high_sl = np.nan
        self.cur_low_price = np.nan
        self.cur_low_idx = -1
        self.cur_low_sl = np.nan

    def set_state(self, high: float, high_idx: int, low: float,
                  low_idx: int) -> None:
        """B4: Übernahme der Batch-Endwerte (bootstrap_history)."""
        self.cur_high_price = float(high)
        self.cur_high_idx = int(high_idx)
        self.cur_high_sl = float(high) * self.cfg.sl_factor_high()
        self.cur_low_price = float(low)
        self.cur_low_idx = int(low_idx)
        self.cur_low_sl = float(low) * self.cfg.sl_factor_low()

    def update_scalar(self, bar_idx: int, high: float,
                      low: float) -> Tuple[bool, bool]:
        is_new_h = False
        is_new_l = False
        if np.isnan(self.cur_high_price) or high > self.cur_high_price:
            self.cur_high_price = high
            self.cur_high_idx = bar_idx
            self.cur_high_sl = high * self.cfg.sl_factor_high()
            is_new_h = True
        if np.isnan(self.cur_low_price) or low < self.cur_low_price:
            self.cur_low_price = low
            self.cur_low_idx = bar_idx
            self.cur_low_sl = low * self.cfg.sl_factor_low()
            is_new_l = True
        return is_new_h, is_new_l


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

        is_new_h, is_new_l = self.finder.update_scalar(bar_idx, high, low)

        gate = self.is_btn_active and (
            is_yellow_window if self.cfg.require_proximity_window else True
        )
        if not gate:
            return events

        # --- Short Side (Peak = laufendes High) --------------------------
        if is_new_h and not np.isnan(prev_h_price):
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
        elif self.state_short == GrabberState.ARMED:
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

        # --- Long Side (Peak = laufendes Low) ----------------------------
        if is_new_l and not np.isnan(prev_l_price):
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
        elif self.state_long == GrabberState.ARMED:
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
    """Peak-Grabber-Indikator: SL-Linien + Trigger-Marker (Hist & Live)."""

    def __init__(self) -> None:
        super().__init__()
        self._symbol: Optional[str] = None
        self._timeframe: Optional[str] = None
        self._settings: Any = None
        self._on_new_candle: Optional[Callable[[], None]] = None
        self._executor = PluginExecutor()
        self._evaluator = ServiceSetEvaluator(self._executor)
        self._last_params: Dict[str, Any] = {}

        # Live-Komponenten (ring buffer, Zero-GC, B5)
        self._buffer_size: int = 2000
        self._head: int = 0
        self._buf_time = np.zeros(self._buffer_size, dtype=np.int64)
        self._buf_sl_high = np.full(self._buffer_size, np.nan, dtype=np.float64)
        self._buf_sl_low = np.full(self._buffer_size, np.nan, dtype=np.float64)
        self._filled: int = 0
        self._known_times: set = set()  # New-Candle-Erkennung (gerundete Zeit)

        self._live_state: Optional[PeakGrabberLiveState] = None

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
        if self._live_state is not None:
            self._live_state.set_button_active(active)

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
                    "params": {"sl_offset_pct": params.get("sl_offset_pct", 0.15)},
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
        empty = {"lines": [], "markers": [], "status_info": {}}
        if df is None or df.empty:
            return empty
        try:
            p = dict(params or {})
            self._last_params = dict(p)
            context = PluginContext(
                symbol=self._symbol or "",
                timeframe=self._timeframe or "",
                mode="chart",
                settings=self._get_app_settings(),
            )
            definition = self._build_set_definition(p)
            results = self._evaluator.execute_set(definition, df, context)

            # SL-Linien aus srv_peak_finder (sl_high/sl_low je Bar)
            finder_recs = ((results.get("peak_1") or {}).get(
                "feature_store_payload") or {}).get("records") or []
            grabber_recs = ((results.get("grab_1") or {}).get(
                "feature_store_payload") or {}).get("records") or []
            stats = ((results.get("grab_1") or {}).get(
                "feature_store_payload") or {}).get("metadata") or {}

            lines: List[Dict[str, Any]] = []
            if p.get("show_sl_high", True):
                lines.append({
                    "id": "sl_high",
                    "data": [{"time": int(r["bar_time"]),
                              "value": float(r["sl_high"]),
                              "color": p.get("sl_high_color", "#EF5350")}
                             for r in finder_recs],
                    "width": 1, "style": "solid", "title": "SL High",
                })
            if p.get("show_sl_low", True):
                lines.append({
                    "id": "sl_low",
                    "data": [{"time": int(r["bar_time"]),
                              "value": float(r["sl_low"]),
                              "color": p.get("sl_low_color", "#26A69A")}
                             for r in finder_recs],
                    "width": 1, "style": "solid", "title": "SL Low",
                })

            markers: List[Dict[str, Any]] = []
            if p.get("show_signals", True):
                for r in grabber_recs:
                    sig = int(r["signal"])
                    if sig in (1, -1):  # Trigger
                        markers.append({
                            "time": int(r["bar_time"]),
                            "position": "aboveBar" if sig == 1 else "belowBar",
                            "color": "#26A69A" if sig == 1 else "#EF5350",
                            "shape": "arrowUp" if sig == 1 else "arrowDown",
                            "size": 2,
                            "text": "BUY" if sig == 1 else "SELL",
                            "priority": 8,
                        })
                    elif p.get("show_updates", False):  # Update
                        markers.append({
                            "time": int(r["bar_time"]),
                            "position": "aboveBar" if sig == 2 else "belowBar",
                            "color": "#90A4AE",
                            "shape": "circle",
                            "size": 1,
                            "text": "upd",
                            "priority": 5,
                        })

            # Bootstrap des Live-States (B4): Batch-Endwerte übernehmen.
            self._bootstrap_live_state(finder_recs, p)

            return {
                "lines": lines,
                "markers": markers,
                "status_info": {
                    "is_btn_active": bool(
                        self._live_state and self._live_state.is_btn_active),
                    "trigger_count": int((stats.get("statistics") or {}).get(
                        "trigger_count", 0)),
                },
            }
        except Exception as e:
            print(f"[IndPeak] Service-Pipeline fehlgeschlagen: {e}")
            return empty

    def _bootstrap_live_state(self, finder_recs: List[Dict[str, Any]],
                              p: Dict[str, Any]) -> None:
        """B4: übernimmt die letzten Batch-Peaks in den Live-Scalar-State."""
        if not finder_recs:
            return
        last = finder_recs[-1]
        peak_cfg = PeakConfig(sl_offset_pct=float(
            p.get("sl_offset_pct", 0.15)))
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
        # Ringpuffer mit History-SL füllen (nur die letzten buffer_size).
        n = min(len(finder_recs), self._buffer_size)
        self._filled = 0
        self._head = 0
        for r in finder_recs[-n:]:
            self._push(int(r["bar_time"]),
                       float(r["sl_high"]), float(r["sl_low"]))
        last_high = float(last["peak_high"])
        last_low = float(last["peak_low"])
        self._live_state.finder.set_state(
            last_high, len(finder_recs) - 1, last_low, len(finder_recs) - 1)

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
        if rounded not in self._known_times:
            self._known_times.add(rounded)
            if self._on_new_candle is not None:
                try:
                    self._on_new_candle()
                except Exception:
                    pass

        bar_idx = max(self._filled, self._live_state.finder.cur_high_idx + 1)
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
        Signal (Gate offen)."""
        try:
            from analytics.engine.feature_store_reader import FeatureStoreReader
            reader = FeatureStoreReader(db_path=None)
            rec = reader.latest_proximity_record(
                self._symbol or "", self._timeframe or "", int(ts))
            if rec:
                fd = rec.get("feature_data") or {}
                return bool(fd.get("in_time_window") and (fd.get("levels_hit") or []))
        except Exception:
            pass
        return True

    # ---------------------------------------------------- Overlay-Hooks (P14-03)
    def get_live_overlays(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Live-SL-Punkte als generische Overlays (kind='circle')."""
        self.update_live_candle(candle)
        if self._live_state is None:
            return []
        overlays = []
        if not np.isnan(self._live_state.finder.cur_high_sl):
            overlays.append({
                "kind": "circle", "layer": self.indicator_id,
                "time": int(candle.get("time", 0)),
                "price": float(self._live_state.finder.cur_high_sl),
                "color": self._last_params.get("sl_high_color", "#EF5350"),
                "priority": 10,
            })
        if not np.isnan(self._live_state.finder.cur_low_sl):
            overlays.append({
                "kind": "circle", "layer": self.indicator_id,
                "time": int(candle.get("time", 0)),
                "price": float(self._live_state.finder.cur_low_sl),
                "color": self._last_params.get("sl_low_color", "#26A69A"),
                "priority": 10,
            })
        return overlays

    def remember_live_time(self, ts: int) -> None:
        try:
            self._known_times.add(int(ts))
        except (TypeError, ValueError):
            pass
