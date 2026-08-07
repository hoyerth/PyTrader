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
