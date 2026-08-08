# workers/live_tick_worker.py
"""
workers/live_tick_worker.py - Kontinuierliches MT5-Tick-Polling & Bar-Close.

Ausgelagert aus main.py im Rahmen von 18.01.02 (E7). Der Worker pollt
MT5-Ticks fuer die aktuell aktiven Symbol/Timeframe-Paare, erkennt
Bar-Close-Events, schreibt abgeschlossene Kerzen in market_data.duckdb und
emittiert Live-Candle-Updates an die Charts. Keine UI-Logik (SRP).
"""

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Set, Tuple

import MetaTrader5 as mt5
from PySide6.QtCore import QThread, Signal

from data_sync.mt5_sync_service import MT5_LOCK, get_timeframes
from db.db_pool import DB_MARKET_DATA, DbPool


class LiveTickWorker(QThread):
    """Kontinuierliche MT5-Tick-Polling-Schleife mit Bar-Close-Erkennung."""

    ticks_ready = Signal(str)

    def __init__(self, get_active_pairs_callback: Callable[[], Set[Tuple[str, str]]]) -> None:
        super().__init__()
        self.get_active_pairs: Callable[[], Set[Tuple[str, str]]] = get_active_pairs_callback
        self._running: bool = True
        self._last_bar_times: Dict[str, int] = {}  # Für Bar-Close-Erkennung
        self._last_bar_data: Dict[str, Dict[str, Any]] = {}  # OHLCV der letzten abgeschlossenen Kerze

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        """Kontinuierliche Polling-Schleife für MT5-Ticks mit try/finally Freigabe.
        Erkennt Bar-Close-Events und schreibt abgeschlossene Kerzen in market_data.duckdb."""
        try:
            with MT5_LOCK:
                if not mt5.initialize():
                    # MT5 ist möglicherweise bereits von MainWindow initialisiert
                    print("⚠️ [LiveTickWorker] mt5.initialize() war False, versuche trotzdem weiter...")

            while self._running:
                active_pairs: Set[Tuple[str, str]] = self.get_active_pairs()
                if not active_pairs:
                    self.msleep(200)
                    continue

                results: Dict[str, Dict[str, float | int]] = {}
                try:
                    for symbol, tf_str in active_pairs:
                        mt5_tf: Optional[int] = get_timeframes().get(tf_str)
                        if mt5_tf is None:
                            continue

                        with MT5_LOCK:
                            tick = mt5.symbol_info_tick(symbol)
                            rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, 1)

                        if tick and rates is not None and len(rates) > 0:
                            rate = rates[0]
                            key: str = f"{symbol}|{tf_str}"
                            current_bar_time = int(rate['time'])

                            # Bar-Close erkennen: neue Bar-Time != letzte Bar-Time
                            last_bar = self._last_bar_times.get(key, 0)
                            if last_bar > 0 and current_bar_time > last_bar:
                                # Alte (abgeschlossene) Kerze aus dem Zwischenspeicher in DB schreiben
                                last_data = self._last_bar_data.get(key)
                                if last_data:
                                    self._persist_bar(symbol, tf_str, last_bar, last_data)

                            # Aktuelle Kerze zwischenspeichern (wird beim nächsten Bar-Close persistiert)
                            self._last_bar_times[key] = current_bar_time
                            self._last_bar_data[key] = {
                                'open': float(rate[1]),  # open
                                'high': float(rate[2]),  # high
                                'low': float(rate[3]),   # low
                                'close': float(rate[4]), # close
                                'tick_volume': int(rate[5]) if len(rate) > 5 else 0,
                                'spread': int(rate[6]) if len(rate) > 6 else 0,
                                'real_volume': int(rate[7]) if len(rate) > 7 else 0,
                            }

                            # JEDEN Tick an die Charts senden (für Live-Candle-Updates)
                            results[key] = {
                                "time": current_bar_time,
                                "open": float(rate['open']),
                                "high": max(float(rate['high']), float(tick.bid)),
                                "low": min(float(rate['low']), float(tick.bid)),
                                "close": float(tick.bid)
                            }
                except Exception as e:
                    print(f"⚠️ [LiveTickWorker] Fehler in Poll-Schleife: {e}")

                if results:
                    self.ticks_ready.emit(json.dumps(results))

                self.msleep(500)

        finally:
            with MT5_LOCK:
                try:
                    mt5.shutdown()
                except Exception:
                    pass

    def _persist_bar(self, symbol: str, tf_str: str, bar_time: int, bar_data: Dict[str, Any]) -> None:
        """Schreibt eine abgeschlossene Kerze per INSERT OR REPLACE in market_data.duckdb."""
        try:
            con = DbPool.get(DB_MARKET_DATA)
            con.execute("""
                INSERT OR REPLACE INTO ohlcv_bars (symbol, timeframe, time, open, high, low, close, tick_volume, spread, real_volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                symbol,
                tf_str,
                datetime.fromtimestamp(bar_time, tz=timezone.utc),
                bar_data['open'],
                bar_data['high'],
                bar_data['low'],
                bar_data['close'],
                bar_data['tick_volume'],
                bar_data['spread'],
                bar_data['real_volume'],
            ])
        except Exception as e:
            print(f"⚠️ [LiveTickWorker] Fehler beim Persistieren von {symbol} {tf_str} @ {bar_time}: {e}")
