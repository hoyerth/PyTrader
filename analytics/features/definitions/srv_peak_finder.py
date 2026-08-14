# analytics/features/definitions/srv_peak_finder.py
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

_PEAK_FINDER_SCHEMA: Dict[str, ParameterSchema] = {
    "sl_offset_pct": {
        "type": "float", "default": 0.15, "min": 0.0, "max": 10.0,
        "step": 0.01, "description": "SL-Puffer über/unter Peak (%)",
    },
    # 22.01b (User-Anweisung 4a): Viewback-Fenster des Peak Finders. Der
    # SL-Punkt wandert dem Kurs entlang (Rolling-Window): Records neuer
    # Peaks ersetzen aeltere Signale innerhalb des Fensters (Supersession),
    # Records aelter als viewback_bars bleiben persistent.
    "viewback_bars": {
        "type": "int", "default": 3, "min": 1, "max": 10000,
        "step": 1, "description": "Viewback: Bars zurueckschauen fuer lokales Hoch/Tief",
    },
}


class PeakFinderService(PluginFeature):
    """Vektorisierte Peak-Tracking & SL-Berechnung (Hist-Batch, stateless).

    22.01b: Rolling-Window statt kumulativem Maximum/Minimum. Records
    werden NUR an Bars mit Peak-Aenderung erzeugt (neuer Peak ODER Expiry
    des alten Extremums) - der SL-Punkt wandert dem Kurs entlang. Aeltere
    Records innerhalb des Viewbacks werden entfernt (`delete_bar_times` im
    Payload); Records aelter als viewback_bars bleiben persistent.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_peak_finder"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, str]:
        return {
            "category": "Swing Points/Peak Grabber",
            "display_name": "Peak Finder",
            "indicator_name": "Ind_Peak",
            "indicator_id": "ind_peak",
            "description": "Running Highs/Lows samt SL-Offset (Batch, stateless)",
            "author": "PyTrader AI",
            "tags": ["peak", "swing", "stop-loss"],
            "condition_rules": [
                "peak_high = max(high) ueber Rolling-Window viewback_bars",
                "peak_low  = min(low)  ueber Rolling-Window viewback_bars",
                "sl_high = peak_high * (1 + sl_offset_pct/100)",
                "sl_low  = peak_low  * (1 - sl_offset_pct/100)",
                "Records NUR an Peak-Aenderungen (neuer Peak ODER Expiry)",
                "Aeltere Records innerhalb viewback_bars werden entfernt; aeltere bleiben persistent",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": True,
            "batch": True,
            "live": False,            # Live läuft im Indikator (PeakGrabberLiveState)
            "feature_store": True,
            "render": False,          # P16.01: Styling baut der Indikator
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        return {k: dict(v) for k, v in _PEAK_FINDER_SCHEMA.items()}

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        if df is None or df.empty:
            return {"feature_store_payload": {}}
        p = self.validate_params(params)
        highs = df["high"].to_numpy(dtype=np.float64)
        lows = df["low"].to_numpy(dtype=np.float64)
        times = df["time"].to_numpy()
        vb = max(1, int(p.get("viewback_bars") or 3))

        # ------------------------------------------------------------ 22.01b
        # Rolling-Window-Extrema (monotone Deques, O(n)). Der SL-Punkt
        # wandert dem Kurs entlang: neuer Peak ODER Expiry des alten
        # Extremums -> `changed[i]` True -> Record.
        from collections import deque
        n = len(df)
        peak_highs = np.empty(n, dtype=np.float64)
        peak_lows = np.empty(n, dtype=np.float64)
        win_h: "deque" = deque()  # (bar_idx, high), vorn = Maximum
        win_l: "deque" = deque()  # (bar_idx, low),  vorn = Minimum
        changed = np.zeros(n, dtype=bool)
        for i in range(n):
            h = float(highs[i])
            l = float(lows[i])
            while win_h and win_h[0][0] <= i - vb:
                win_h.popleft()
            while win_l and win_l[0][0] <= i - vb:
                win_l.popleft()
            while win_h and win_h[-1][1] <= h:
                win_h.pop()
            win_h.append((i, h))
            while win_l and win_l[-1][1] >= l:
                win_l.pop()
            win_l.append((i, l))
            peak_highs[i] = win_h[0][1]
            peak_lows[i] = win_l[0][1]
            if i > 0 and (peak_highs[i] != peak_highs[i - 1]
                          or peak_lows[i] != peak_lows[i - 1]):
                changed[i] = True

        f_h = 1.0 + (float(p["sl_offset_pct"]) / 100.0)
        f_l = 1.0 - (float(p["sl_offset_pct"]) / 100.0)
        sl_highs = peak_highs * f_h
        sl_lows = peak_lows * f_l

        # Records NUR an Peak-Aenderungen. Supersession: erzeugt ein neuer
        # Record eine Aenderung, werden aeltere Records innerhalb des
        # Viewbacks entfernt (delete_bar_times); Records aelter als
        # viewback_bars bleiben persistent (Survivors).
        records: List[Dict[str, Any]] = []
        delete_bar_times: List[int] = []
        survivors: "list" = []  # [(bar_idx, record)]
        for i in range(n):
            if i != 0 and not changed[i]:
                continue
            rec = {
                "bar_time": int(times[i]),
                "peak_high": float(peak_highs[i]),
                "peak_low": float(peak_lows[i]),
                "sl_high": float(sl_highs[i]),
                "sl_low": float(sl_lows[i]),
            }
            cutoff = i - vb  # Records mit bar_idx > cutoff liegen im Viewback
            kept: "list" = []
            for (bi, r) in survivors:
                if bi > cutoff:
                    delete_bar_times.append(int(times[bi]))
                else:
                    kept.append((bi, r))
            kept.append((i, rec))
            survivors = kept
        records = [r for (_bi, r) in survivors]

        # Window-Tail (letzte vb Bars) fuer den Live-Bootstrap (Paritaet
        # Batch -> Live: der Live-Tracker startet mit exakt diesem Fenster).
        tail = [(i, float(highs[i]), float(lows[i]))
                for i in range(max(0, n - vb), n)]

        # Shared-State fuer nachgelagerte srv_peak_grabber (depends_on):
        if context is not None and context.instance_id:
            context.shared_state[context.instance_id] = {
                "peak_highs": peak_highs,
                "peak_lows": peak_lows,
                "sl_highs": sl_highs,
                "sl_lows": sl_lows,
                "records": records,
                "window_tail": tail,
            }
        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                # 22.01b: Supersedierte SL-Punkte (Viewback) - der Store
                # loescht diese bar_times VOR dem Upsert (store_plugin_payload).
                "delete_bar_times": delete_bar_times,
                "metadata": {"schema_version": "1.0.0"},
            },
        }
