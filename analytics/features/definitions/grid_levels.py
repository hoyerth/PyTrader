# analytics/features/definitions/grid_levels.py
"""
Feature: Grid-Levels (Y-Achse) + Zeitfenster-Flags (X-Achse) – Phase 11

Berechnet vektorisiert fuer jede Bar die Liq-Line / Grid-Level Logik des
Grid-Systems (Paritaetsfunktionen in `grid_math.py`, Phase 15 U15-B3 –
eingefrorene Referenz-Kopien des am 04.08.2026 entfernten Alt-Indikators
chart/indicators/grid.py) und stellt sie als Feature-Spalten fuer den
feature_store bereit:

    grid_nearest_level      naechstes Grid-Level zum close (Preis)
    grid_dist_abs           absoluter Preisabstand |close - nearest_level|
    grid_dist_pct           prozentualer Abstand (dist_abs / close * 100)
    is_time_window_active   1 wenn die Bar im Zeitfenster liegt (Minute 0/30
                            +/- time_window_mins, native UTC), sonst 0

Das Modul ist bewusst gekapselt und unabhaengig vom Chart-Indikator. Es bildet
nur die Berechnungslogik ab (kein Rendering, kein DB-Zugriff). Die Konsistenz
wird durch dieselben Kernfunktionen sichergestellt (vektorisierte Varianten
der Skalar-Funktionen in `grid_math.py`):

    build_grid_levels()  <->  grid_math.build_grid_levels() (center +- i*step + custom)
    in_window_around()   <->  grid_math.f_in_window_around() (Minute 0/30 +- span)

Parameter (params-Dict):
    step_size          float, Schrittweite des Grids (Default 0.5, prox_stepSize)
    steps_around       int,   Anzahl Level ober-/unterhalb des Zentrums (Default 4,
                              prox_stepsAround)
    custom_levels      list[float], zusaetzliche Fix-Level (Default [], nur > 0
                              werden verwendet, prox_level1..6)
    time_window_mins   int,   Halbbreite des Zeitfensters in Minuten (Default 5,
                              prox_timeWindowMins)
    use_time_filter    bool,  False => is_time_window_active ist immer 1
                              (Default True, prox_useTimeFilter)
"""

from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from analytics.features.base_feature import BaseFeature

# Spaltennamen, wie sie im feature_store (analytics.duckdb) erwartet werden.
GRID_COLUMNS = [
    "grid_nearest_level",
    "grid_dist_abs",
    "grid_dist_pct",
    "is_time_window_active",
]


def build_grid_levels(
    center: float,
    step_size: float,
    steps_around: int,
    custom_levels: Optional[List[float]] = None,
) -> List[float]:
    """
    Erzeugt die sortierte Grid-Level-Liste (absteigend) fuer ein Zentrum.

    Identische Logik wie grid_math.build_grid_levels() (Referenz-Snapshot):
      center = round(price / step) * step
      levels = center + i*step  fuer i in [-steps_around, steps_around]
      + zusaetzliche custom_levels (nur > 0)
    """
    if step_size <= 0:
        base = {round(float(center), 6)}
    else:
        inv_step = 1.0 / step_size
        center_r = round(float(center) * inv_step) / inv_step
        base = {round(center_r + i * step_size, 6) for i in range(-steps_around, steps_around + 1)}

    for lvl in (custom_levels or []):
        v = float(lvl)
        if v > 0.0:
            base.add(round(v, 6))

    return sorted(base, reverse=True)


def in_window_around(
    minute_val: np.ndarray,
    center: int,
    span: int,
) -> np.ndarray:
    """
    Vektorisierte Version von grid_math.f_in_window_around():
    Liefert True fuer Minuten, die im Fenster center +/- span liegen
    (mit Wrap-Around ueber 0/59).
    """
    minute_val = np.asarray(minute_val, dtype=int)
    lower = center - span
    upper = center + span
    if lower < 0:
        return (minute_val >= (60 + lower)) | (minute_val <= upper)
    elif upper > 59:
        return (minute_val >= lower) | (minute_val <= (upper - 60))
    else:
        return (lower <= minute_val) & (minute_val <= upper)


class GridLevelsFeature(BaseFeature):
    """Vektorisierte Grid-Level-Berechnung fuer den feature_store."""

    @property
    def name(self) -> str:
        return "grid_levels"

    @property
    def description(self) -> str:
        return (
            "Naechstes Grid-Level zum close (Y-Achse), Preisabstaende "
            "(abs/pct) und Zeitfenster-Flag (is_time_window_active, X-Achse)"
        )

    @property
    def column_names(self) -> List[str]:
        return list(GRID_COLUMNS)

    def _calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
        n = len(df)
        if n == 0:
            return pd.DataFrame({c: [] for c in GRID_COLUMNS})

        # --- Parameter (Defaults konsistent zu grid_math.py) ---
        step_size = float(params.get("step_size", 0.5))
        steps_around = int(params.get("steps_around", 4))
        time_window_mins = int(params.get("time_window_mins", 5))

        use_time_filter_raw = params.get("use_time_filter", True)
        if isinstance(use_time_filter_raw, str):
            use_time_filter = use_time_filter_raw.lower() in ("true", "1", "yes")
        else:
            use_time_filter = bool(use_time_filter_raw)

        custom_levels_raw = params.get("custom_levels", [])
        valid_custom = [float(x) for x in custom_levels_raw if float(x) > 0.0]

        close = df["close"].to_numpy(dtype=float)

        # --- Grid-Level-Matrix vektorisiert aufbauen ---
        # Zentrum pro Bar = naechstes Vielfaches von step_size zum close
        if step_size > 0:
            centers = np.round(close / step_size) * step_size
            offsets = np.arange(-steps_around, steps_around + 1) * step_size
            levels = centers[:, None] + offsets[None, :]
        else:
            centers = close.copy()
            levels = centers[:, None]

        if valid_custom:
            custom_arr = np.full((n, len(valid_custom)), np.array(valid_custom, dtype=float)[None, :])
            levels = np.concatenate([levels, custom_arr], axis=1)

        # --- Naechstes Level & Abstaende ---
        diff = np.abs(levels - close[:, None])
        nearest_idx = np.argmin(diff, axis=1)
        nearest_level = levels[np.arange(n), nearest_idx]
        dist_abs = diff[np.arange(n), nearest_idx]

        with np.errstate(divide="ignore", invalid="ignore"):
            dist_pct = np.where(close != 0.0, dist_abs / close * 100.0, np.nan)

        # --- Zeitfenster-Flags (native UTC-Minute der Bar) ---
        minutes = self._bar_utc_minutes(df)
        full_win = in_window_around(minutes, 0, time_window_mins)
        half_win = in_window_around(minutes, 30, time_window_mins)
        in_window = full_win | half_win
        if not use_time_filter:
            in_window = np.ones(n, dtype=bool)

        return pd.DataFrame(
            {
                "grid_nearest_level": nearest_level,
                "grid_dist_abs": dist_abs,
                "grid_dist_pct": dist_pct,
                "is_time_window_active": in_window.astype(int),
            },
            index=df.index,
        )

    @staticmethod
    def _bar_utc_minutes(df: pd.DataFrame) -> np.ndarray:
        """
        Liefert die UTC-Minute (0-59) jeder Bar.

        Unterstuetzt:
          - 'bar_time' als tz-aware pandas datetime (feature_builder load_ohlcv)
          - 'bar_time' als naive datetime/str (wird als UTC interpretiert)
          - 'time' als Unix-Epoch-Integer (grid_math.py-Stil)
        """
        n = len(df)
        if "bar_time" in df.columns:
            t = pd.to_datetime(df["bar_time"])
            if t.dt.tz is not None:
                return t.dt.tz_convert("UTC").dt.minute.to_numpy(dtype=int)
            return t.dt.minute.to_numpy(dtype=int)
        elif "time" in df.columns:
            t = pd.to_datetime(df["time"], unit="s", utc=True)
            return t.dt.minute.to_numpy(dtype=int)
        return np.zeros(n, dtype=int)
