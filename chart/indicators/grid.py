# chart/indicators/grid.py
"""
Grid & Proximity Indicator Plugin
Restaurierter, stabiler Stand ohne Zeitzonen-Offsets (basierend auf Agents2.md)
"""

import math
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from pathlib import Path

from .base_indicator import BaseIndicator
from db_service import DbPool

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")


def f_round_to_custom_step(price: float, step: float) -> float:
    if step <= 0:
        return price
    inv_step = 1.0 / step
    return round(price * inv_step) / inv_step


def f_strip_trailing_zeros(val: float) -> str:
    s = f"{val:.6f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def f_in_window_around(minute_val: int, center: int, span: int) -> bool:
    lower = center - span
    upper = center + span
    if lower < 0:
        return minute_val >= (60 + lower) or minute_val <= upper
    elif upper > 59:
        return minute_val >= lower or minute_val <= (upper - 60)
    else:
        return lower <= minute_val <= upper


class GridIndicator(BaseIndicator):

    def __init__(self) -> None:
        super().__init__()
        self._symbol: Optional[str] = None
        self._timeframe: Optional[str] = None

    def set_context(self, symbol: str, timeframe: str) -> None:
        self._symbol = symbol
        self._timeframe = timeframe

    @property
    def indicator_id(self) -> str:
        return "grid"

    @property
    def display_name(self) -> str:
        return "Grid & Proximity Liq Lines"

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "prox_enableMaster": True,
            "prox_level1": 0.0,
            "prox_level2": 0.0,
            "prox_level3": 0.0,
            "prox_level4": 0.0,
            "prox_level5": 0.0,
            "prox_level6": 0.0,
            "prox_visitPct": 0.05,
            "prox_stepsAround": 4,
            "prox_stepSize": 0.5,
            "prox_useTimeFilter": True,
            "prox_timeWindowMins": 5,
            "prox_showLines": True,
            "prox_showCircles": True,
        }

    @property
    def param_options(self) -> Dict[str, List[Any]]:
        return {}

    @property
    def param_layout(self) -> Optional[List[Any]]:
        return [
            "prox_enableMaster",
            ("Zusatz-Levels 1 - 3", ["prox_level1", "prox_level2", "prox_level3"]),
            ("Zusatz-Levels 4 - 6", ["prox_level4", "prox_level5", "prox_level6"]),
            "prox_visitPct",
            ("Grid (Steps / Size $)", ["prox_stepsAround", "prox_stepSize"]),
            ("Time Filter (Aktiv / Mins)", ["prox_useTimeFilter", "prox_timeWindowMins"]),
            "prox_showLines",
            "prox_showCircles",
        ]

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
        if df.empty or not params.get("prox_enableMaster", True):
            return {
                "lines": [],
                "hit_circles": [],
                "status_info": {"in_time_window": False, "active_hits": []},
            }

        step_size = float(params.get("prox_stepSize", 0.5))
        steps_around = int(params.get("prox_stepsAround", 4))
        visit_pct = float(params.get("prox_visitPct", 0.05))

        use_time_filter_raw = params.get("prox_useTimeFilter", True)
        if isinstance(use_time_filter_raw, str):
            use_time_filter = use_time_filter_raw.lower() in ("true", "1", "yes")
        else:
            use_time_filter = bool(use_time_filter_raw)

        time_window_mins = int(params.get("prox_timeWindowMins", 5))

        show_lines_raw = params.get("prox_showLines", True)
        show_lines = show_lines_raw.lower() in ("true", "1", "yes") if isinstance(show_lines_raw, str) else bool(
            show_lines_raw)

        show_circles_raw = params.get("prox_showCircles", True)
        show_circles = show_circles_raw.lower() in ("true", "1", "yes") if isinstance(show_circles_raw, str) else bool(
            show_circles_raw)

        custom_levels = [
            float(params.get("prox_level1", 0.0)),
            float(params.get("prox_level2", 0.0)),
            float(params.get("prox_level3", 0.0)),
            float(params.get("prox_level4", 0.0)),
            float(params.get("prox_level5", 0.0)),
            float(params.get("prox_level6", 0.0)),
        ]
        valid_custom_levels = [lvl for lvl in custom_levels if lvl > 0.0]

        last_row = df.iloc[-1]
        last_close = float(last_row["close"])

        # 1. GRID LEVEL ARRAY ZUSAMMENSTELLEN
        center_price = f_round_to_custom_step(last_close, step_size)
        grid_levels = set()

        for i in range(-steps_around, steps_around + 1):
            grid_levels.add(round(center_price + (i * step_size), 6))

        for c_lvl in valid_custom_levels:
            grid_levels.add(round(c_lvl, 6))

        sorted_levels = sorted(list(grid_levels), reverse=True)

        # 2. ZEITFENSTER-FILTER (REINES NATIVE UTC DER KERZENZEIT)
        if "time" in df.columns:
            last_ts = int(last_row["time"])
            m = datetime.fromtimestamp(last_ts, tz=dt_timezone.utc).minute
        else:
            m = datetime.now(dt_timezone.utc).minute

        full_win = f_in_window_around(m, 0, time_window_mins)
        half_win = f_in_window_around(m, 30, time_window_mins)
        in_time_window_raw = full_win or half_win
        in_time_window = in_time_window_raw if use_time_filter else True

        # 3. PROXIMITY & HIT LOGIK ÜBER HISTORIE
        hit_circles = []
        active_hits = []

        tracked_levels = sorted_levels if show_lines else []

        for idx, row in df.iterrows():
            time_val = int(row["time"])
            c_high = float(row["high"])
            c_low = float(row["low"])

            # Native UTC-Minute ohne künstlichen Offset
            row_m = datetime.fromtimestamp(time_val, tz=dt_timezone.utc).minute
            row_in_time = (
                (f_in_window_around(row_m, 0, time_window_mins) or f_in_window_around(row_m, 30, time_window_mins))
                if use_time_filter
                else True
            )

            circle_color = "#FFEB3B" if row_in_time else "#E91E63" if use_time_filter else "#E91E63"

            for lvl in tracked_levels:
                visit_min = lvl * (1.0 - visit_pct / 100.0)
                visit_max = lvl * (1.0 + visit_pct / 100.0)

                touch_high = visit_min <= c_high <= visit_max
                touch_low = visit_min <= c_low <= visit_max
                pierce = c_low <= lvl and c_high >= lvl

                near = touch_high or touch_low or pierce

                if near:
                    if show_circles:
                        hit_circles.append({
                            "time": time_val,
                            "price": lvl,
                            "color": circle_color,
                        })
                    if idx == df.index[-1]:
                        active_hits.append(f_strip_trailing_zeros(lvl))

        # 4. LINES PAYLOAD
        lines_payload = []
        if show_lines:
            for lvl in sorted_levels:
                is_custom = any(abs(lvl - c_lvl) < 0.0001 for c_lvl in valid_custom_levels)

                lines_payload.append({
                    "price": lvl,
                    "color": "rgba(33, 150, 243, 0.9)" if is_custom else "rgba(33, 150, 243, 0.5)",
                    "width": 1 if is_custom else 3,
                    "style": "Solid",
                    "is_custom": is_custom,
                })

        return {
            "lines": lines_payload,
            "hit_circles": hit_circles,
            "status_info": {
                "in_time_window": in_time_window,
                "active_hits": active_hits,
            },
        }

    @staticmethod
    def _get_custom_levels(params: Dict[str, Any]) -> List[float]:
        levels = []
        for i in range(1, 7):
            try:
                v = float(params.get(f"custom_level_{i}", 0.0))
                if v > 0:
                    levels.append(round(v, 6))
            except (ValueError, TypeError):
                pass
        return levels

    def _get_level_at_time(self, con, ts: int) -> Optional[float]:
        try:
            dt = datetime.fromtimestamp(ts, tz=dt_timezone.utc)
            row = con.execute("""
                SELECT grid_nearest_level
                FROM feature_store
                WHERE symbol = ? AND timeframe = ? AND bar_time = ?
                  AND grid_nearest_level IS NOT NULL AND grid_nearest_level > 0
            """, [self._symbol, self._timeframe, dt]).fetchone()
            if row and row[0] is not None:
                v = float(row[0])
                if not math.isnan(v) and v > 0:
                    return v
        except Exception:
            pass
        return None