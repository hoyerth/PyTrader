# analytics/features/definitions/grabber_kernel.py
import numpy as np

try:
    from numba import njit
except ImportError:  # Fallback: pure NumPy (gleiche Semantik, langsamer)

    def njit(func=None, **kwargs):
        if func is None:  # @njit(...)-Form (z. B. @njit(fastmath=True))
            return lambda f: f
        return func


@njit(fastmath=True)
def run_grabber_kernel(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    is_yellow_window: np.ndarray,
    reversal_pct: float,
    min_hold_bars: int,
    inval_bars: int,
    inval_thresh_pct: float,
    sl_offset_pct: float,
    require_prox: bool,
    gate_active: bool,
):
    """Serieller Backtest-Kernel (Zero-GC, native Geschwindigkeit).

    Signale: 0: Keins, 1: BUY_TRIGGER, 2: BUY_UPDATE, -1: SELL_TRIGGER,
    -2: SELL_UPDATE. Zustände: 0 IDLE, 1 ARMED, 2 TRIGGERED, 3 INVALIDATED.
    Startzustand IDLE (B2); Bar 0 = Bootstrap ohne Event.
    """
    n = len(highs)
    signals = np.zeros(n, dtype=np.int8)
    sl_prices = np.full(n, np.nan, dtype=np.float64)
    peak_prices = np.full(n, np.nan, dtype=np.float64)

    sl_factor_h = 1.0 + (sl_offset_pct / 100.0)
    sl_factor_l = 1.0 - (sl_offset_pct / 100.0)

    peak_h = highs[0]          # Bootstrap: kein Event (First-Peak-Skip, B2)
    peak_h_idx = 0
    state_short = 0            # IDLE

    peak_l = lows[0]           # Bootstrap
    peak_l_idx = 0
    state_long = 0             # IDLE

    for i in range(1, n):
        h = highs[i]
        l = lows[i]
        c = closes[i]
        yw = is_yellow_window[i]
        gate = gate_active and (yw if require_prox else True)

        # --- SHORT LOGIK (Peak = laufendes High) --------------------------
        if h > peak_h:
            prev_h = peak_h
            bars_h = i - peak_h_idx       # B2/B3: Alter des VORHERIGEN Peaks
            peak_h = h
            peak_h_idx = i
            if gate:
                breach_pct = ((h - prev_h) / prev_h) * 100.0 if prev_h > 0.0 else 0.0
                if bars_h <= inval_bars:
                    if breach_pct <= inval_thresh_pct:
                        state_short = 1   # ARMED / UPDATE
                        signals[i] = -2
                        sl_prices[i] = peak_h * sl_factor_h
                        peak_prices[i] = peak_h
                    else:
                        state_short = 3   # INVALIDATED
                else:
                    state_short = 1       # frischer Peak nach langer Ruhe
        elif gate and state_short == 1:   # ARMED: Reversal-Pruefung
            bars_h = i - peak_h_idx       # Alter des AKTUELLEN Peaks
            rev_pct = ((peak_h - c) / peak_h) * 100.0 if peak_h > 0.0 else 0.0
            if rev_pct >= reversal_pct and bars_h >= min_hold_bars:
                state_short = 2           # TRIGGERED
                signals[i] = -1
                sl_prices[i] = peak_h * sl_factor_h
                peak_prices[i] = peak_h

        # --- LONG LOGIK (Peak = laufendes Low) ----------------------------
        if l < peak_l:
            prev_l = peak_l
            bars_l = i - peak_l_idx       # Alter des VORHERIGEN Peaks
            peak_l = l
            peak_l_idx = i
            if gate:
                breach_pct = ((prev_l - l) / prev_l) * 100.0 if prev_l > 0.0 else 0.0
                if bars_l <= inval_bars:
                    if breach_pct <= inval_thresh_pct:
                        state_long = 1    # ARMED / UPDATE
                        signals[i] = 2
                        sl_prices[i] = peak_l * sl_factor_l
                        peak_prices[i] = peak_l
                    else:
                        state_long = 3    # INVALIDATED
                else:
                    state_long = 1        # frischer Peak nach langer Ruhe
        elif gate and state_long == 1:    # ARMED: Reversal-Pruefung
            bars_l = i - peak_l_idx       # Alter des AKTUELLEN Peaks
            rev_pct = ((c - peak_l) / peak_l) * 100.0 if peak_l > 0.0 else 0.0
            if rev_pct >= reversal_pct and bars_l >= min_hold_bars:
                state_long = 2            # TRIGGERED
                signals[i] = 1
                sl_prices[i] = peak_l * sl_factor_l
                peak_prices[i] = peak_l

    return signals, sl_prices, peak_prices
