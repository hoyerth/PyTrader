# analytics/features/definitions/grid_math.py
"""
Phase 15 (U15-B3): Eigenständige Paritäts-Mathematik für Grid-Services.

Die Funktionen sind die eingefrorenen Referenz-Kopien der ehemaligen
Alt-Implementierung `chart/indicators/grid.py` (am 04.08.2026 entfernt).
Sie dienen als SINGLE SOURCE OF TRUTH für die Grid-Parität:

* `f_round_to_custom_step` – Rundung auf das nächste Vielfache von step.
* `build_grid_levels`      – Level-Array (Center ± steps_around × step + Custom).
* `f_in_window_around`     – natives UTC-Zeitfenster (Minute 0/30 ± span, Wrap-Around).
* `f_strip_trailing_zeros` – '%.6f' ohne nachgestellte Nullen (Level-Strings).

Die Services (srv_grid_lines.py, srv_proximity.py) importieren diese
Funktionen und garantieren damit identisches Verhalten zum historischen
Alt-Indikator, ohne auf das gelöschte Modul zu verweisen.

HINWEIS: Der Indikator-Adapter (chart/indicators/ind_fixed_grid_proximity.py) behält seine
private Kopie (`_f_in_window_around`) unverändert – sie wird nicht umgestellt.
Das Alt-Plugin analytics/features/definitions/grid_liquidity.py wurde am
04.08.2026 archiviert/entfernt (Schema ist im Indikator selbst hinterlegt).
"""

from typing import List, Optional


def f_round_to_custom_step(price: float, step: float) -> float:
    """Rundet price auf das nächste Vielfache von step.

    Exakte Parität zur ehemaligen chart/indicators/grid.py.
    """
    if step <= 0:
        return price
    inv_step = 1.0 / step
    return round(price * inv_step) / inv_step


def build_grid_levels(
    last_close: float,
    step_size: float,
    steps_around: int,
    custom_levels: Optional[List[float]] = None,
) -> List[float]:
    """Sortierte Level-Liste (absteigend) – exakte Parität zum Alt-Grid.

    grid.py (historisch):
      center_price = f_round_to_custom_step(last_close, step_size)
      grid_levels  = {round(center_price + i*step_size, 6)
                      | i in range(-steps_around, steps_around+1)}
      + {round(c_lvl, 6) | c_lvl in custom_levels, c_lvl > 0.0}
    """
    center_price = f_round_to_custom_step(last_close, step_size)
    grid_levels: set = set()
    for i in range(-steps_around, steps_around + 1):
        grid_levels.add(round(center_price + (i * step_size), 6))
    for c_lvl in (custom_levels or []):
        v = float(c_lvl)
        if v > 0.0:
            grid_levels.add(round(v, 6))
    return sorted(list(grid_levels), reverse=True)


def f_in_window_around(minute_val: int, center: int, span: int) -> bool:
    """Native UTC-Zeitfenster-Logik – exakte Parität zum Alt-Grid.

    True, wenn minute_val im Fenster center ± span liegt (mit Wrap-Around
    über 0/59). Zentren: 0 (ganze Stunde) und 30 (halbe Stunde).
    """
    lower = center - span
    upper = center + span
    if lower < 0:
        return minute_val >= (60 + lower) or minute_val <= upper
    elif upper > 59:
        return minute_val >= lower or minute_val <= (upper - 60)
    else:
        return lower <= minute_val <= upper


def f_strip_trailing_zeros(val: float) -> str:
    """'%.6f' ohne nachgestellte Nullen – exakte Parität zum Alt-Grid."""
    s = f"{val:.6f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s
