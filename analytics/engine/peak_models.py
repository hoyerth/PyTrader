# analytics/engine/peak_models.py
"""
Dataclasses, Enums & Configs des Peak-Grabbers (22.01).

Kollokation im Engine-Paket neben `service_models.py`. Die Modelle sind
bewusst von UI und DB entkoppelt (MVVM, Praeambel 4):

  * `SignalDirection`  – BUY/SELL-Richtung eines Grabber-Records.
  * `GrabberState`     – Zustands-Enum der State-Machine (IDLE/ARMED/
                         TRIGGERED/INVALIDATED) – Paritaet zwischen
                         Kernel (§3) und Live-State (§5).
  * `PeakConfig`       – SL-Offset des Peak-Finders (sl_factor_*).
  * `PeakGrabberConfig`– Trigger-/Invalidations-Parameter der State-Machine.
                         `take_profit_r` / `max_hold_bars` sind RESERVIERTE
                         Felder (Frage 4) fuer das spaetere Outcome-Modul
                         (analytics/engine/peak_outcome.py, NICHT 22.01).
  * `GrabberResultRecord` – 18-Felder-Persistenz-Vertrag (B1) exakt passend
                         zur DDL `grabber_test_results` (§2.3) und zum
                         Repository-INSERT (§7).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class GrabberState(int, Enum):
    IDLE = 0
    ARMED = 1
    TRIGGERED = 2
    INVALIDATED = 3


@dataclass(frozen=True)
class PeakConfig:
    sl_offset_pct: float = 0.15  # SL-Puffer über/unter Peak (%)

    def sl_factor_high(self) -> float:
        return 1.0 + (self.sl_offset_pct / 100.0)

    def sl_factor_low(self) -> float:
        return 1.0 - (self.sl_offset_pct / 100.0)


@dataclass(frozen=True)
class PeakGrabberConfig:
    reversal_pct: float = 0.30           # z% Reversal für Trigger
    min_hold_bars: int = 3               # Min. Bars Haltedauer des Peaks
    invalidation_bars: int = 5           # x Bars Beobachtungsfenster
    invalidation_threshold_pct: float = 0.10  # y% Toleranz vor Hard-Invalidation
    require_proximity_window: bool = True     # Verknüpfung mit Yellow Window
    take_profit_r: Optional[float] = None     # RESERVIERT (Frage 4): TP in R für späteres Outcome-Modul (None = kein TP)
    max_hold_bars: int = 100                  # RESERVIERT (Frage 4): Timeout für späteres Outcome-Modul


@dataclass
class GrabberResultRecord:
    signal_id: str
    run_id: str
    timestamp: datetime
    symbol: str
    timeframe: str
    direction: SignalDirection
    entry_price: float
    sl_price: float
    peak_price: float
    peak_bar_index: int
    is_update: bool                       # True bei <= y% Aktualisierung
    reversal_pct: float
    is_yellow_window: bool
    gate_source: str                      # GATE_/SERIES_ + UPDATE/TRIGGER
    outcome_status: str = "PENDING"
    pnl_r_multiple: Optional[float] = None
    max_favorable_exc: Optional[float] = None
    max_adverse_exc: Optional[float] = None
