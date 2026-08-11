# analytics/ui/heatmap_widget.py
"""
heatmap_widget.py - Generische 2D-Heatmap-Engine mit Confluence-Matrix,
Candle-Overlay & Dual-Axis-Zoom (Phase 20.02).

Additiv zur bestehenden HeatmapPage (Dow x Stunde, Standard-Modus): Dieses
Widget rendert die generische 2D-Matrix (freie Dimensionen + Aggregationen)
und das Kerzen-Overlay. MVVM (Invariante 4): KEIN SQL – die Daten kommen
ueber `data_ready(QUERY_HEATMAP_GENERIC | QUERY_DAILY_OHLC, data)` vom
ViewModel (Async-Worker).

Entscheidungen (Review 09.08.2026, E7-E9):
- E7: CONFLUENCE_COUNT -> diskrete Farbskala (0 = weiss, 1-2 = gelb/cyan,
  3-4 = orange, 5+ = dunkelrot); Wert-Aggregationen -> viridis (kontinuierlich).
- E8: Zoom = EIN Faktor-Slider pro Achse (Viewport-Skalierung, zentriert),
  normalisiert [0,1] (zoom_x_range/zoom_y_range), rein client-seitig via
  setXRange/setYRange (kein DB-Requery).
- E9: Candle-Overlay = Tages-Ohlc UEBER der Heatmap im SELBEN Canvas
  (rechte Preis-Achse, ViewBox-Link an die X-Achse), horizontal synchronisiert.

Bugfix 09.08.2026 (User-Meldungen 1-6):
1) Das Kerzen-Overlay ist KEIN separates Fenster mehr – die Tages-Candles
   liegen im selben PlotWidget ueber der Heatmap (rechte Preis-Achse).
2) Die generische Heatmap laedt ALLE verfuegbaren Daten (kein 5000er-
   Limit-Lookback mehr, ViewModel; Pivot-Deckel MAX_HEATMAP_CELLS begrenzt
   die Matrix). Das Overlay nutzt `QUERY_DAILY_OHLC` (SQL-seitig pro Tag
   aggregiert) und deckt damit den gesamten Heatmap-Zeitraum ab.
3) Die Achsen tragen die NATUERLICHEN Werte (date -> Mitternachts-Epochs,
   hour/dow -> Ganzzahlen, dow 1..5 Mo-Fr, kategorial -> Indizes); das
   ImageItem wird per setRect exakt auf diesen Bereich gemappt – nichts wird
   mehr ueber die Tagesgrenze hinaus gezeichnet.
4) Achsen-Zuordnung ist explizit (x_dim -> X, y_dim -> Y), kein Vertauschen
   mehr moeglich.
5) Dynamische X-Ticks je Zoom-Level: date -> Jahre/Monate/Tage -> Stunden ->
   Minuten (bis zur Minute, wie Chartfenster/TradingView) – 20.02.01 E1:
   5 Format-Stufen (YYYY / TT.MM.JJ / DDD TT.MM.JJ / DDD TT.MM.JJ HH:00 /
   DDD TT.MM.JJ HH:mm), Wanduhr-Garantie via UTC-Darstellung.
6) Dasselbe Prinzip gilt fuer die Y-Achse und alle Massstaebe (hour, dow,
   kategorial): je Zoom-Level werden mehr Zwischenwerte angezeigt.

20.02.01 (E2-E8, 09.08.2026): "Stunde" -> "Tageszeit" (E2, feste Skala
00:00-23:59, E3); Achsen-Label mit UTC-Offset (E4); `dow` strikt
Montag-Freitag (E5); `dow_hour` ersatzlos entfernt (E6); Overlay-Zoom-Lock
exklusiv bei X=date (E7); service_id-Achsen-Labels via ViewModel-Resolver
'{Kategorie} / {Name}' (E8).

20.02.01 (User-Meldungen 1-3, 09.08.2026): (1) Tageszeit-Achse bleibt beim
Rauszoomen auf die feste Skala 00:00-23:59 begrenzt (keine -/+ Werte
ausserhalb; tickValues-Clamping, kein `% 24`-Wrap mehr); (2) Wochentag-Achse
ebenso strikt Mo-Fr (1..6, halboffene Grenze); (3) 'Feld'-Dropdown deutlich
laenger (320-460 px) und jeder Eintrag traegt den Service-Namen, aus dem der
Wert stammt ('{Service} / {Key}', `srv_`-Prefix entfaellt, via
ViewModel-Resolver + Repository-`field_sources`). User-Meldung 3c (09.08.2026):
vor jedem Feld-Eintrag steht NUR der Service-NAME ohne Kategorie-Pfad
(`resolve_service_display_name`, z. B. 'Grid Lines / open' statt
'Swing Points / Grid Lines / open'); die E8-Achsen-Labels der
service_id-Dimension behalten weiterhin '{Kategorie} / {Name}'.

09.08.2026 (User-Meldungen Feld-Dropdown + Zoom-Richtung):
- Feld-Dropdown: Der Service-Name wird DIREKT aus dem Service-Objekt
  abgeleitet (`resolve_service_display_name` aus `plugin_id`, z. B.
  'Swing Momentum' statt des unzuverlaessigen metadata['display_name']
  'Swing Momentum Service'). Liefern MEHRERE Services denselben Key,
  entfaellt der Prefix KOMPLETT ('price' statt 'Swing Momentum Service /
  Swing Volume Profile Service / price' – die verkettete Namen zeigten
  einen irrefuehrenden MasterTree-'Pfad').
- Zoom-Slider X/Y: Richtung getauscht – rechts = Zoom-In, links = Zoom-Out
  (Slider-Wert 5 = volle Achse, 100 = maximale Vergroesserung;
  `_set_zoom_range`/`_set_zoom_slider` invers umgerechnet).
- Achse 'Datum': Beschriftung lautet 'Datum/Zeit' – OHNE das
  pyqtgraph-EXP-Suffix ('Datum (x1e+09)'). Ursache: `setLabel(text)`
  mit units=None erzeugt eine leere Einheit; die date-Epochs (~1.7e9)
  fallen in den SI-Bereich (1e9, inf) und pyqtgraph haengt '(x1e+09)'
  an. `_HeatmapAxis.enableAutoSIPrefix(False)` unterdrueckt das
  Suffix (die Ticks werden ohnehin von tickStrings formatiert).

20.02.01 (User-Meldung 2 - Datums-Skala LWC-v5, 09.08.2026): Die date-Achse
nutzt die Tick-Logik von Lightweight Charts v5 (aus dem LWC-JS extrahiert):
Der Mindestabstand zweier Labels betraegt ~80 px (`_DATE_TARGET_PX`) –
Zoom-In wechselt zur naechst feineren Variante (Stunden/Minuten), Zoom-Out
zur naechst groeberen (Jahr/Monat/Woche/Tag); keine Ueberlappung, keine
Riesensprünge. Weight-Hierarchie (LWC `Q_`): 70 Jahreswechsel ('2026'),
60 Monatswechsel ('Feb 26'), 55 Wochenanfang Mo (ISO '08.25'),
50 Tag ('Mo. 07.08.25'), 30 Stunde ('14:00'), 20 Minute ('14:23').
pyqtgraph uebergibt an `tickValues` die ACHSEN-LAENGE in Pixeln (3. Param)
– daraus wird der Mindestabstand in Sekunden berechnet.
"""

import math
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import (
    QUERY_HEATMAP_GENERIC,
    QUERY_DAILY_OHLC,
    QUERY_FEATURES,
    QUERY_OHLCV,
)
from analytics.engine.feature_store_reader import (
    DOW_WEEK_LABELS,
    HEATMAP_AGGREGATIONS,
    HEATMAP_DIMENSIONS,
    HOURS_PER_DAY,
)
from analytics.ui.common import CheckableComboBox

# E7: Konfluenz-Farbskala (0 = grau, 1-2 = gelb/cyan, 3-4 = orange,
# 5+ = dunkelrot) – Positionen 0..1 (Levels 0..5).
# 21.01 (Bugfix 2, 11.08.2026): 0 = HELLGRAU statt Weiss – weisse
# 0-Treffer-Zellen waren auf dem weissen Plot-Hintergrund unsichtbar.
_CONFLUENCE_COLORS = [
    "#d9d9d9", "#ffff00", "#00ffff", "#ff8c00", "#ff6600", "#8b0000",
]
_CONFLUENCE_POS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
_CONFLUENCE_LEVELS = (0.0, 5.0)
_VIRIDIS = "viridis"

# E6: Wert-Aggregationen benoetigen einen numerischen feature_data-JSON-Key.
_VALUE_AGGS = ("avg", "sum", "min", "max")

# Tag in Sekunden (Wanduhr-Epoch-Basis fuer date-Achse).
_DAY_SECONDS = 86400
_HALF_DAY = 43200.0
# 20.02.01 (E1): Stufen-Schwellen des Datums-Formatters (Monat/Jahr).
_MONTH_SECONDS = 2_592_000
_YEAR_SECONDS = 31_536_000
# 21.01 (Bugfix 5, 11.08.2026): Timeframe -> Sekunden fuer das adaptive
# Candle-Overlay (OHLCV im Original-TF statt Tages-Aggregation).
_TF_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800,
}

# 20.02.01 (User-Meldung 2): LWC-v5-adaptierte Datums-Skala.
# Zielabstand zwischen zwei Tick-Labels in Pixel (Lightweight Charts:
# 5*(fontSize+4)/8 * (tickMarkMaxCharacterLength || 8) mit fontSize 12 =>
# 5*16/8*8 = 80 px). Die Tick-Auswahl haelt diesen Abstand ein: Zoom-In
# => feinere Variante, Zoom-Out => groebere Variante (keine Ueberlappung,
# keine Riesensprünge). Weight-Hierarchie wie LWC v5:
#   70 = Jahreswechsel, 60 = Monatswechsel, 55 = Wochenanfang Mo,
#   50 = Tageswechsel, 30 = Stundenmarke, 20 = Minutenmarke.
# 21.01 (Bugfix 4): Die LABELS folgen seitdem 1:1 der App-JS
# (TT.MM.JJ fuer Tages-Marken, HH:MM fuer Sub-Tag-Marken) - die alte
# 5-Format-Beschriftung ('2026'/'Feb 26'/'08.25'/'Di. 03.02.26') ist
# ersetzt, weil sie von der Chartfenster-Anzeige abwich.
_DATE_TARGET_PX = 80.0
_MONTHS_SHORT = ("Jan", "Feb", "Mrz", "Apr", "Mai", "Jun",
                 "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")

_DIM_LABELS = {
    "date": "Datum",
    "dow": "Wochentag",
    # 20.02.01 (E2): "Stunde" -> "Tageszeit" (feste Skala 00:00-23:59, E3).
    "hour": "Tageszeit",
    "timeframe": "Timeframe",
    "service_id": "Service",
    "symbol": "Symbol",
}
_AGG_LABELS = {
    "count": "Anzahl (COUNT)",
    "confluence_count": "Konfluenz (COUNT DISTINCT)",
    "avg": "Mittelwert (AVG)",
    "sum": "Summe (SUM)",
    "min": "Minimum (MIN)",
    "max": "Maximum (MAX)",
}


# ---------------------------------------------------------------------------
# Dynamische Achse (Bugfix 09.08.2026, Punkte 3/5/6)
# ---------------------------------------------------------------------------
def _pick_time_step(span: float, max_ticks: int) -> float:
    """Waelt einen 'sauberen' Zeit-Schritt (Sekunden) fuer den Bereich."""
    if span <= 0:
        return 0.0
    min_step = span / max(1, max_ticks)
    # 1s, 5s, 15s, 30s, 1m, 5m, 15m, 30m, 1h, 2h, 3h, 6h, 12h,
    # 1d, 2d, 1w, 2w, 1M, 3M, 6M, 1J
    steps = (1, 5, 15, 30, 60, 300, 900, 1800, 3600, 7200, 10800, 21600,
             43200, 86400, 172800, 604800, 1209600, 2592000, 7776000,
             15552000, 31536000)
    for s in steps:
        if s >= min_step:
            return float(s)
    return float(steps[-1])


def _time_ticks(min_val: float, max_val: float, step: float) -> List[float]:
    """Ganzzahlige Tick-Positionen (Vielfache von `step`) im Bereich."""
    if step <= 0:
        return []
    start = int(math.ceil(min_val / step)) * step
    out: List[float] = []
    v = start
    while v <= max_val + 1e-9:
        out.append(float(v))
        v += step
    return out


def _nice_int_step(span: float, max_ticks: int) -> float:
    """Waelt einen ganzzahligen Tick-Schritt (1,2,3,6,12,24,...) fuer den Bereich."""
    if span <= 0:
        return 1.0
    raw = span / max(1, max_ticks)
    for s in (1, 2, 3, 6, 12, 24, 48, 72, 168, 336, 730, 1460, 2920):
        if s >= raw:
            return float(s)
    return float(math.ceil(raw))


class _HeatmapAxis(pg.AxisItem):
    """Achse mit dynamischen Ticks je Zoom-Level (Bugfix 09.08.2026).

    Die Achse traegt NATUERLICHE Werte (date -> Wanduhr-Epochs,
    hour/dow -> Ganzzahlen, kategorial -> Indizes) und formatiert die
    Tick-Beschriftung abhaengig vom sichtbaren Bereich:
      - date:  2 Formate je Zoom (TT.MM.JJ / HH:MM), 21.01 Bugfix 4 –
               1:1 mit der App-JS (Lightweight Charts tickMarkFormatter)
      - hour/dow: ganzzahlige Schritte, beim Zoom mehr Zwischenwerte
      - kategorial: Labels aus der zugehoerigen Liste
    """

    def __init__(self, orientation: str, **kwargs) -> None:
        super().__init__(orientation, **kwargs)
        self._dim: Optional[str] = None
        self._labels: List[str] = []
        # 09.08.2026 (User-Meldung): Kein automatisches SI-Prefix an das
        # Achsen-Label haengen. pyqtgraph wuerde bei date-Epochs (~1.7e9)
        # `setLabel(text)` (units=None -> leere Einheit) in den SI-Bereich
        # (1e9, inf) einsortieren und 'Datum (x1e+09)' anzeigen (das
        # 'EXP' in Klammern). Die Ticks werden ohnehin von tickStrings
        # mit echten Werten formatiert (Scale wird ignoriert) – das
        # Suffix waere also irrefuehrend.
        self.enableAutoSIPrefix(False)

    def configure(self, dim: str, labels: List[str]) -> None:
        """Setzt Dimension + Label-Liste (kategoriale Achsen)."""
        self._dim = str(dim or "")
        self._labels = list(labels or [])

    # ------------------------------------------------------------------
    def _clamped_scale_bounds(self, minVal, maxVal):
        """Clampt den sichtbaren Bereich auf die feste Skala (Meldungen 1+2).

        `hour` (Tageszeit) und `dow` (Wochentag) haben FESTE Skalen
        (0..24 bzw. 1..6, siehe `_axis_bounds`). Beim Rauszoomen (Mausrad)
        ragt der sichtbare Viewport ueber die Skala hinaus – die Ticks
        duerfen DANN nicht ausserhalb liegen (keine -/+ Werte ausserhalb
        00:00-23:59 bzw. Mo-Fr). Der Tick-Bereich wird daher auf die
        Skala geclampt. `date` bleibt unbegrenzt (datenbasiert); seit
        21.01 Bugfix 1 werden auch kategoriale Achsen (service_id/
        timeframe/symbol) auf 0..n-1 geclampt (keine Gespenster-Ticks
        -1/+2 ausserhalb des festen Wertebereichs, User-Meldung).
        """
        lo = float(minVal)
        hi = float(maxVal)
        if self._dim == "hour":
            lo = max(lo, 0.0)
            hi = min(hi, float(HOURS_PER_DAY))
        elif self._dim == "dow":
            lo = max(lo, 1.0)
            hi = min(hi, 1.0 + float(len(DOW_WEEK_LABELS)))
        elif self._dim not in ("date",):
            # 21.01 (Bugfix 1): Kategoriale Achsen haben einen FESTEN
            # Wertebereich 0..n-1 (n = Anzahl Labels). Beim Rauszoomen
            # (Mausrad) ragt der Viewport ueber die Skala hinaus - die
            # Ticks duerfen DANN nicht ausserhalb liegen.
            n = len(self._labels)
            lo = max(lo, -0.5)
            hi = min(hi, float(max(0, n)) - 0.5)
        return lo, hi

    def tickValues(self, minVal, maxVal, maxTicks=5):
        if not self._dim:
            return super().tickValues(minVal, maxVal, maxTicks)
        if self._dim == "date":
            # 20.02.01 (User-Meldung 2): LWC-v5-adaptierte Datums-Skala.
            # pyqtgraph uebergibt als dritten Parameter die ACHSEN-LAENGE in
            # Pixel (nicht die Tick-Anzahl!). Die Tick-Auswahl haelt den
            # Zielabstand _DATE_TARGET_PX ein: Zoom-In => feinere Variante,
            # Zoom-Out => groebere Variante; Jahr/Monat/Woche/Tag/Stunde/
            # Minute koexistieren als Hierarchie (per-Tick-Format in _format).
            return self._lwc_date_ticks(float(minVal), float(maxVal),
                                        float(maxTicks or 0))
        # 20.02.01 (User-Meldungen 1+2): hour/dow auf die feste Skala
        # geclampt – beim Rauszoomen bleibt der Bereich VOR/NACH der
        # Tagesstunden (bzw. der 5 Wochentage) leer. Das rechte Skalenende
        # (24 h bzw. Samstag 6) wird als halboffene Grenze ausgeschlossen,
        # damit kein Duplikat-Label ("00:00" an Position 24) entsteht.
        lo, hi = self._clamped_scale_bounds(minVal, maxVal)
        if hi <= lo:
            return []
        span = hi - lo
        step = _nice_int_step(span, int(maxTicks))
        start = int(math.ceil(lo / step)) * step
        values: List[float] = []
        v = float(start)
        while v < hi - 1e-9:
            values.append(v)
            v += step
        return [(step, values)]

    # ------------------------------------------------------------------
    # 20.02.01 (User-Meldung 2): LWC-v5-Datums-Ticks (Jahr/Monat/Woche/Tag/
    # Stunde/Minute-Hierarchie, Mindestabstand in Pixel)
    # ------------------------------------------------------------------
    def _lwc_date_ticks(self, lo: float, hi: float, axis_px: float):
        """Erzeugt die Datums-Ticks nach der LWC-v5-Selektionslogik.

        Der dritte Parameter von `tickValues` ist bei pyqtgraph die
        ACHSEN-LAENGE in Pixeln. Der Mindestabstand zweier Ticks in
        Sekunden ergibt sich aus `_DATE_TARGET_PX * span / axis_px` –
        dadurch bleiben die Labels ~80 px auseinander: Zoom-In => feinere
        Variante (Stunden/Minuten), Zoom-Out => groebere Variante (nur
        Jahr/Monat/Woche/Tag). Die Auswahl bevorzugt hoehere Weights
        (LWC `Q_`): Jahres-/Monatsmarken werden immer gesetzt, feinere
        Marken fuellen die Luecken.
        """
        span = hi - lo
        if span <= 0:
            return []
        if axis_px <= 0 or not math.isfinite(axis_px):
            axis_px = 800.0
        min_gap_sec = _DATE_TARGET_PX * span / axis_px
        min_gap_sec = max(1.0, min_gap_sec)
        marks = self._date_marks(lo, hi, min_gap_sec)
        epochs = self._select_date_marks(marks, min_gap_sec)
        if not epochs:
            return []
        return [(min_gap_sec, epochs)]

    def _date_marks(self, lo: float, hi: float,
                    min_gap_sec: float) -> List[tuple]:
        """Kandidaten-Marken der Datums-Achse (Epoch, Weight).

        Tages-Marken (Mitternacht, Wanduhr-UTC) mit Weight nach Datum:
        70 = 1. Januar (Jahreswechsel), 60 = 1. des Monats (Monatswechsel),
        55 = Montag (ISO-Wochenanfang), 50 = sonstiger Tag. Bei engem
        Zoom zusaetzlich Stunden-Marken (30) und Minuten-Marken (20) –
        die Generierung ist ueber die sichtbare Spanne begrenzt
        (Minuten nur bei < 2 Tagen, Stunden nur bei < 60 Tagen), damit
        die Kandidatenanzahl klein bleibt.
        """
        marks: List[tuple] = []
        d0 = int(math.floor(lo / _DAY_SECONDS)) * _DAY_SECONDS
        d1 = int(math.floor(hi / _DAY_SECONDS)) * _DAY_SECONDS
        d = d0
        while d <= d1:
            dt = datetime.fromtimestamp(d, tz=dt_timezone.utc)
            if dt.month == 1 and dt.day == 1:
                w = 70
            elif dt.day == 1:
                w = 60
            elif dt.weekday() == 0:
                w = 55
            else:
                w = 50
            marks.append((d, w))
            d += _DAY_SECONDS
        if min_gap_sec < _DAY_SECONDS and (hi - lo) <= 60 * _DAY_SECONDS:
            h0 = int(math.floor(lo / 3600.0)) * 3600
            h1 = int(math.floor(hi / 3600.0)) * 3600
            h = h0
            while h <= h1:
                if h % _DAY_SECONDS != 0:  # Mitternacht = Tages-Marke
                    marks.append((h, 30))
                h += 3600
        if min_gap_sec < 3600.0 and (hi - lo) <= 2 * _DAY_SECONDS:
            m0 = int(math.floor(lo / 60.0)) * 60
            m1 = int(math.floor(hi / 60.0)) * 60
            m = m0
            while m <= m1:
                if m % 3600 != 0:  # Stunde = Stunden-Marke
                    marks.append((m, 20))
                m += 60
        marks.sort(key=lambda x: x[0])
        return marks

    @staticmethod
    def _select_date_marks(marks: List[tuple],
                           min_gap_sec: float) -> List[float]:
        """LWC-v5-Selektion (Q_): Weight absteigend, Mindestabstand.

        Hoehere Weights (Jahr/Monat) werden bevorzugt gesetzt; feinere
        Marken werden nur uebernommen, wenn sie mindestens `min_gap_sec`
        von den bereits gewaehlten Marken entfernt sind. Ergebnis: die
        gewohnte Hierarchie (Jahreszahl + Monatswechsel + Tage) mit
        garantierter Mindest-Pixeldistanz (keine Ueberlappung, keine
        Riesensprünge).
        """
        by_weight: Dict[int, List[float]] = {}
        for epoch, weight in marks:
            by_weight.setdefault(int(weight), []).append(float(epoch))
        selected: List[float] = []
        for weight in sorted(by_weight.keys(), reverse=True):
            s = selected
            out: List[float] = []
            r = 0
            e = len(s)
            a = float("inf")
            o = float("-inf")
            for idx in by_weight[weight]:
                while r < e and s[r] < idx:
                    out.append(s[r])
                    o = s[r]
                    r += 1
                if r < e:
                    a = s[r]
                if a - idx >= min_gap_sec and idx - o >= min_gap_sec:
                    out.append(idx)
                    o = idx
            while r < e:
                out.append(s[r])
                r += 1
            selected = out
        return selected

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            out.append(self._format(float(v), float(spacing)))
        return out

    # ------------------------------------------------------------------
    def _format(self, v: float, spacing: float) -> str:
        if self._dim == "date":
            # 21.01 (Bugfix 4 + Runde 3, 11.08.2026): Datums-Format:
            #   - Tages-/Monats-/Jahres-Marken (Mitternacht) -> 'Mo. 12.06.26'
            #     (Runde 3: Wochentag + Datum, User-Wunsch wie chart_win)
            #   - Stunden-/Minuten-Marken (Sub-Tag)          -> 'HH:MM'
            # Die urspruengliche 5-Format-Weight-Hierarchie (Jahreszahl
            # '2026', Monatskuerzel 'Feb 26', ISO-Woche '08.25') ist ersetzt.
            # Wanduhr-Garantie via UTC-Darstellung der (Wanduhr-encoded)
            # Epoch (Invariante 7, KEIN Berlin-Offset). `weekday()`:
            # 0=Mo..6=So -> Index in die deutschen Wochentage.
            dt = datetime.fromtimestamp(v, tz=dt_timezone.utc)
            if dt.hour != 0 or dt.minute != 0 or dt.second != 0:
                return f"{dt.hour:02d}:{dt.minute:02d}"  # Sub-Tag '14:30'
            days = ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So.")
            return (f"{days[dt.weekday()]} {dt.day:02d}.{dt.month:02d}."
                    f"{dt.year % 100:02d}")
        if self._dim == "hour":
            # 20.02.01 (User-Meldung 1): KEIN `% 24`-Wrap mehr – Werte
            # ausserhalb der festen Skala 00:00-23:59 werden leer gelassen
            # (das tickValues-Clamping verhindert sie bereits; defensiv).
            vv = int(round(v))
            if 0 <= vv < HOURS_PER_DAY:
                return f"{vv:02d}:00"
            return ""
        if self._dim == "dow":
            idx = int(round(v))
            if 1 <= idx <= len(DOW_WEEK_LABELS):
                return DOW_WEEK_LABELS[idx - 1]
            return ""
        # Kategorial (timeframe/service_id/symbol): Labels aus der Liste.
        idx = int(round(v))
        if 0 <= idx < len(self._labels):
            return str(self._labels[idx])
        # 21.01 (Bugfix 1): Ausserhalb des festen Wertebereichs -> leer
        # (das tickValues-Clamping verhindert sie bereits; defensiv).
        return ""


class HeatmapWidget(QWidget):
    """Generische 2D-Heatmap mit Confluence-Matrix, Zoom & Candle-Overlay."""

    # 21.01 (E7, 11.08.2026): Das Signal bleibt als Vertrag erhalten, wird
    # aber NICHT mehr emittiert – die Smart-Presets laufen ausschliesslich
    # ueber das 'Ansicht'-Dropdown der HeatmapPage (keine Preset-Buttons).
    preset_clicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None
        self._n_cols = 0
        self._n_rows = 0
        self._x_axis: List[float] = []      # natuerliche X-Koordinaten je Spalte
        self._y_axis: List[float] = []      # natuerliche Y-Koordinaten je Zeile
        self._x_dates: List[Any] = []       # Datum je Spalte (nur X=date)
        self._x_min = -0.5
        self._x_max = 0.5
        self._y_min = -0.5
        self._y_max = 0.5
        self._candle_items: List[Any] = []
        self._colormap_mode = _VIRIDIS
        self._syncing = False
        # 20.03.03 (Q2): Key -> aktive Quellen-Services aus dem Payload
        # (`field_sources`) fuer die ALL-Expansion der Sammel-Eintraege.
        self._field_sources: Dict[str, List[str]] = {}
        # Runde 8 (Bugfix 3/4, 10.08.2026): Cache der zuletzt verfuegbaren
        # Feld-Keys (Payload-Metadaten) - Grundlage des SYNCHRONEN
        # Feld-Dropdown-Rebuilds (_rebuild_field_dropdown) ohne
        # Query-Round-Trip. Wird bei jedem Daten-Payload aktualisiert;
        # _sync_from_params/feature_ids_changed bauen daraus Items/Haken.
        self._field_keys: List[str] = []
        # Runde 11 (Bug 4, B4-2): Cache der No-Data-Varianten aus dem
        # QUERY_FEATURES-Payload. None = noch kein Payload (Loading);
        # [] = Erfolg ohne Varianten; Liste = Erfolg mit Varianten.
        # `_no_data_variants_error` markiert einen fehlgeschlagenen
        # No-Data-Check (Payload-Vertrag B4-2, 'Pruefung fehlgeschlagen').
        self._no_data_variants: Optional[List[Dict[str, Any]]] = None
        self._no_data_variants_error: bool = False

        # --- Steuerung (Zeile 1: Dimensionen/Aggregation/Feld) ---
        self._combo_x = QComboBox()
        # 20.02.01 (E8): Mindestbreite erhoeht (laengere Achsen-Beschriftungen).
        self._combo_x.setMinimumWidth(160)
        for d in HEATMAP_DIMENSIONS:
            self._combo_x.addItem(_DIM_LABELS.get(d, d), d)
        self._combo_y = QComboBox()
        self._combo_y.setMinimumWidth(160)
        for d in HEATMAP_DIMENSIONS:
            self._combo_y.addItem(_DIM_LABELS.get(d, d), d)
        self._combo_agg = QComboBox()
        for a in HEATMAP_AGGREGATIONS:
            self._combo_agg.addItem(_AGG_LABELS.get(a, a), a)
        # 20.03.02 (F1c/F7): 'Feld' ist ein CheckableComboBox – die
        # Multi-Auswahl steuert den Datenquellen-Filter `feature_ids`, die
        # Aggregation nutzt genau EIN aktives Hauptfeld (currentData). Bei
        # COUNT/CONFLUENCE_COUNT bleibt die Auswahl deaktiviert (F7,
        # _update_controls).
        self._combo_field = CheckableComboBox()
        # 20.02.01 (User-Meldung 3a): 'Feld' deutlich laenger (Eintraege
        # tragen seit Meldung 3b den Service-Prefix '{Service} / {Key}').
        self._combo_field.setMinimumWidth(320)
        # Runde 16 (Bugfix 3, 11.08.2026): Kein MaximumWidth mehr - das
        # Feld-Dropdown darf in der Zoom-Y-Zeile bis zum Canvas-Ende
        # wachsen (Expanding-Policy + Layout-Stretch).
        self._combo_field.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Popup-Dropdown an den laengsten Eintrag anpassen (vollstaendige
        # '{Service} / {Key}'-Texte sichtbar statt Ellipsis).
        self._combo_field.setSizeAdjustPolicy(QComboBox.AdjustToContents)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("X-Achse:"))
        ctrl.addWidget(self._combo_x)
        ctrl.addWidget(QLabel("Y-Achse:"))
        ctrl.addWidget(self._combo_y)
        # 21.01 (E7, 11.08.2026): Die 4 Smart-Preset-Buttons wurden
        # ENTFERNT – die Presets sind ausschliesslich ueber das
        # 'Ansicht'-Dropdown der HeatmapPage erreichbar (heatmap_page.py,
        # _combo_mode / _apply_selected_preset).
        ctrl.addStretch(1)

        # --- Steuerung (Zeile 2: Overlay + Zoom) ---
        self._chk_candle = QCheckBox("Kerzen-Overlay")
        self._slider_zoom_x = QSlider(Qt.Horizontal)
        self._slider_zoom_y = QSlider(Qt.Horizontal)
        self._label_info = QLabel("")
        self._label_info.setStyleSheet("color: #808080;")
        for s in (self._slider_zoom_x, self._slider_zoom_y):
            s.setRange(5, 100)
            # 09.08.2026 (User-Meldung 2): Richtung getauscht – rechts
            # (hoher Wert) = Zoom-In, links (niedriger Wert) = Zoom-Out.
            # 5 = volle Achse (links), 100 = maximale Vergroesserung (rechts).
            s.setValue(5)
            s.setEnabled(False)
            s.setToolTip("Viewport-Zoom (zentriert): rechts = Zoom-In, "
                         "links = Zoom-Out.")

        ctrl2 = QHBoxLayout()
        ctrl2.addWidget(self._chk_candle)
        ctrl2.addWidget(QLabel("Zoom X:"))
        ctrl2.addWidget(self._slider_zoom_x)
        ctrl2.addWidget(QLabel("Zoom Y:"))
        ctrl2.addWidget(self._slider_zoom_y)
        # Runde 16 (Bugfix 2/3, 11.08.2026): Aggregation + Feld sind aus
        # Zeile 1 in die Zoom-Y-Zeile gewandert (rechts neben Zoom Y, mit
        # Abstand; 'Feld' stretcht bis zum Canvas-Ende).
        ctrl2.addSpacing(15)
        ctrl2.addWidget(QLabel("Aggregation:"))
        ctrl2.addWidget(self._combo_agg)
        ctrl2.addSpacing(10)
        ctrl2.addWidget(QLabel("Feld:"))
        ctrl2.addWidget(self._combo_field, 1)
        ctrl2.addWidget(self._label_info)

        # --- Plot: Heatmap + Kerzen-Overlay im SELBEN Canvas (Bugfix 1) ---
        self._plot_hm = pg.PlotWidget()
        self._plot_hm.setBackground("w")
        # Dynamische Achsen (Bugfix 5+6): Ticks je Zoom-Level.
        self._axis_x = _HeatmapAxis("bottom")
        self._axis_y = _HeatmapAxis("left")
        self._plot_hm.plotItem.setAxisItems(
            {"bottom": self._axis_x, "left": self._axis_y})
        self._image = pg.ImageItem()
        # 21.01 (E8, 11.08.2026): pyqtgraph rendert ImageItem-Daten per
        # Default TRANSPONIERT (axisOrder='col-major') – die (rows=Services,
        # cols=Zeiten)-Matrix erschien dadurch als N duenne Y-Streifen
        # (Screenshot-Kritik Punkt 1). row-major legt die Daten 1:1 auf die
        # Zellen (Zeile = Y-Zeile = Service, Spalte = X = Zeitpunkt).
        self._image.setOpts(axisOrder="row-major")
        self._plot_hm.addItem(self._image)
        self._cmap_viridis = pg.colormap.get(_VIRIDIS)
        self._cmap_confluence = pg.ColorMap(
            pos=_CONFLUENCE_POS, color=_CONFLUENCE_COLORS)
        self._image.setColorMap(self._cmap_viridis)
        self._colorbar = pg.ColorBarItem(
            colorMap=self._cmap_viridis, values=(0.0, 1.0))
        self._colorbar.setImageItem(self._image)

        # 21.01 (Bugfix 2, 11.08.2026): Diskrete Schwellwert-Legende oben
        # rechts auf der Grafik (User: 'welche Farbe bedeutet was?'; spaeter
        # konfigurierbar). Wird in _update_legend je Aggregation befuellt.
        self._legend = pg.LegendItem(
            offset=(-10, 10), labelTextColor="k",
            pen=pg.mkPen("#b0b0b0"), brush=pg.mkBrush(255, 255, 255, 210))
        self._legend.setParentItem(self._plot_hm.plotItem)
        self._legend.hide()
        # 21.01 (Bugfix 3, 11.08.2026): Fadenkreuz wie im Chartfenster
        # (LWC-Crosshair) - zwei gestrichelte InfiniteLine, folgen dem
        # Mauszeiger ueber der Heatmap (sigMouseMoved).
        self._cross_x = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen("#808080", width=1, style=Qt.DashLine))
        self._cross_y = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen("#808080", width=1, style=Qt.DashLine))
        self._cross_x.setZValue(20)
        self._cross_y.setZValue(20)
        self._cross_x.setVisible(False)
        self._cross_y.setVisible(False)
        self._plot_hm.addItem(self._cross_x, ignoreBounds=True)
        self._plot_hm.addItem(self._cross_y, ignoreBounds=True)
        self._plot_hm.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # 21.01 (Bugfix-Runde 3, Entscheidung 2a, 11.08.2026): Senkrechte
        # Teiler je Dateneinheit (Bar-Intervall des TFs, z. B. H1 -> jede
        # Stunde). Als EIN PlotCurveItem mit connect='pairs' (schnell),
        # ueber der Heatmap aber unter dem Candle-Overlay (price_vb 10).
        self._grid_lines = pg.PlotCurveItem(
            connect="pairs", pen=pg.mkPen("#c0c0c0", width=1))
        self._grid_lines.setZValue(5)
        self._grid_lines.setVisible(False)
        self._plot_hm.addItem(self._grid_lines)

        # Kerzen-Overlay: zweite Y-Achse (Preis) rechts im selben Canvas,
        # ViewBox teilt die X-Achse mit der Heatmap (Bugfix 1).
        self._plot_hm.showAxis("right")
        self._plot_hm.getAxis("right").setLabel("Preis")
        self._price_vb = pg.ViewBox()
        self._plot_hm.scene().addItem(self._price_vb)
        self._plot_hm.getAxis("right").linkToView(self._price_vb)
        self._price_vb.setXLink(self._plot_hm.plotItem.vb)
        self._price_vb.setZValue(10)  # ueber der Heatmap zeichnen
        self._price_vb.setVisible(False)
        self._plot_hm.getAxis("right").setVisible(False)
        # 10.08.2026 (Bugfix Runde 7, Bug 1): Zweite untere Preis-Achse fuer
        # horizontale Candles, wenn 'Datum' auf der Y-Achse liegt (die
        # regulare untere Achse traegt dann die X-Dimension).
        self._price_axis_bottom = pg.AxisItem("bottom",
                                              parent=self._plot_hm.plotItem)
        self._price_axis_bottom.setLabel("Preis")
        self._plot_hm.plotItem.layout.addItem(self._price_axis_bottom, 4, 1)
        self._price_axis_bottom.linkToView(self._price_vb)
        self._price_axis_bottom.setVisible(False)
        self._plot_hm.plotItem.vb.sigResized.connect(self._update_price_view)

        lay = QVBoxLayout(self)
        lay.addLayout(ctrl)
        lay.addLayout(ctrl2)
        lay.addWidget(self._plot_hm, 1)

        # --- Signale ---
        self._combo_x.currentIndexChanged.connect(self._on_config_changed)
        self._combo_y.currentIndexChanged.connect(self._on_config_changed)
        self._combo_agg.currentIndexChanged.connect(self._on_agg_changed)
        self._combo_field.currentIndexChanged.connect(self._on_config_changed)
        # 20.03.02 (F1c): CheckState-Wechsel im 'Feld'-Dropdown -> Filter.
        # 10.08.2026 (Bugfix Runde 7, Bug 4/5): Die Verbindung ist ENTFERNT -
        # das 'Feld'-Dropdown schreibt KEIN feature_ids mehr (kein
        # Ueberschreiben der ServicePicker-Auswahl bzw. des Restores). Die
        # Haken spiegeln den aktiven Filter (_sync_combos_from_payload); die
        # Feld-Auswahl (Current-Item) steuert heatmap_field weiterhin ueber
        # currentIndexChanged -> _on_config_changed.
        # self._combo_field.selection_changed.connect(
        #     self._on_field_selection_changed)
        self._chk_candle.toggled.connect(self._on_candle_toggled)
        self._slider_zoom_x.valueChanged.connect(self._on_zoom_x_changed)
        self._slider_zoom_y.valueChanged.connect(self._on_zoom_y_changed)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (von der HeatmapPage gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        self._view_model = view_model
        view_model.data_ready.connect(self._on_data_ready)
        # Runde 11 (Architektur, A3): KEINE direkte params_restored-
        # Verbindung mehr - das AnalyticsWindow orchestriert den Seiten-Sync
        # zentral via _sync_all_pages_from_params() (genau EIN Durchgang
        # nach dem VM-Param-Setzen). _sync_from_params() wird vom Window
        # explizit aufgerufen (heatmap_page._generic). Die Initial-Sync
        # unten (self._sync_from_params()) bleibt fuer den Attach-Zeitpunkt.

        # Runde 8 (Bugfix 4): feature_ids-Aenderungen (ServicePicker
        # Check/Uncheck) -> das 'Feld'-Dropdown wird SOFORT synchron neu
        # abgeleitet (kein Debounce/Query-Round-Trip). Defensiv per hasattr
        # (Test-Mocks ohne Signal).
        if hasattr(view_model, "feature_ids_changed"):
            view_model.feature_ids_changed.connect(
                self._on_feature_ids_changed)
        # Runde 11 (Bug 4, B4-2): Fehlerzustand des No-Data-Checks
        # (QUERY_FEATURES) -> 'Pruefung fehlgeschlagen'-Hinweis im
        # Feld-Dropdown (Payload-Vertrag; vorher verschluckte Fehler).
        if hasattr(view_model, "query_failed"):
            view_model.query_failed.connect(self._on_query_failed)
        self._sync_from_params()

    def is_candle_projection_enabled(self) -> bool:
        """True, wenn das Kerzen-Overlay aktiviert ist (E9)."""
        return self._chk_candle.isChecked()

    def request_data(self) -> None:
        """Fordert generische Heatmap (+ OHLCV-Overlay bei Overlay) an.

        21.01 (Bugfix 5, 11.08.2026): Das Overlay laedt den OHLCV-Snapshot
        IM HEATMAP-TIMEFRAME (adaptiv fuer alle TFs) statt der festen
        Tages-Aggregation (fetch_daily_ohlc).

        Runde 15 (Ultra-Low-Latency, Fix 1): QUERY_FEATURES wird VOR der
        Grafik in die Puffer-Queue gelegt – der leichte Metadaten-Pfad
        (Reader-Cache, KEIN Heatmap-Pivot) fuellt das 'Feld'-Dropdown und
        die '(No Data)'-Hinweise, waehrend die teure Pivot-Aggregation
        danach in einem separaten Worker laeuft. Das Dropdown blockiert
        damit nicht mehr mehrere Sekunden auf der Grafik.
        """
        if self._view_model is None:
            return
        self._view_model.request_features()
        self._view_model.request_heatmap_generic()
        # Runde 12 (Option A): Zusaetzlich kommen die No-Data-Varianten im
        # QUERY_HEATMAP_GENERIC-Payload (Konsistenz nach dem Render).
        # 21.01 (Bugfix 5): Overlay-Bars im Heatmap-TF (OHLCV-Snapshot).
        if self._chk_candle.isChecked():
            self._view_model.request_ohlcv_snapshot()

    # ------------------------------------------------------------------
    # Sync aus den ViewModel-_params (Profil/Workspace-Restore)
    # ------------------------------------------------------------------
    def _sync_from_params(self) -> None:
        if self._view_model is None:
            return
        p = self._view_model.params
        self._syncing = True
        try:
            self._set_combo_data(
                self._combo_x, str(p.get("heatmap_x_dim") or "date"))
            self._set_combo_data(
                self._combo_y, str(p.get("heatmap_y_dim") or "hour"))
            self._set_combo_data(
                self._combo_agg,
                str(p.get("heatmap_agg") or "confluence_count"))
            # Runde 8 (Bugfix 3): Das 'Feld'-Dropdown wird aus den gecachten
            # Feld-Metadaten (self._field_keys/self._field_sources) + den
            # aktuellen VM-Params SYNCHRON neu abgeleitet (Items, Haken,
            # Current). Ein restaurierter heatmap_field bleibt dadurch auch
            # ohne frischen Daten-Payload sichtbar (Fallback-Roh-Item, wenn
            # noch keine Payload-Metadaten vorliegen).
            self._rebuild_field_dropdown(self._field_keys,
                                         self._field_sources)
            # 21.01 (User-Meldung 5, 11.08.2026): Das Kerzen-Overlay wird
            # NUR wiederhergestellt, wenn die X-Achse = 'date' ist. Bei
            # Y=date/anderen Achsen bleibt die Checkbox aus (verhindert
            # ein ungewolltes Dirty-Setzen via _update_controls beim
            # Profil-/Workspace-Restore).
            self._chk_candle.setChecked(bool(
                p.get("candle_projection_enabled"))
                and str(p.get("heatmap_x_dim") or "date") == "date")
            self._set_zoom_slider(self._slider_zoom_x,
                                  p.get("zoom_x_range") or [0.0, 1.0])
            self._set_zoom_slider(self._slider_zoom_y,
                                  p.get("zoom_y_range") or [0.0, 1.0])
        finally:
            self._syncing = False
        self._update_controls()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        """Setzt die Combo auf `value` (fuegt unbekannte Werte additiv hinzu)."""
        combo.blockSignals(True)
        try:
            idx = combo.findData(value)
            if idx < 0:
                combo.addItem(str(value), value)
                idx = combo.count() - 1
            combo.setCurrentIndex(idx)
        finally:
            combo.blockSignals(False)

    @staticmethod
    def _set_zoom_slider(slider: QSlider, zrange: Any) -> None:
        """Stellt den Zoom-Slider aus einem [lo, hi]-Bereich ein (E8).

        09.08.2026 (User-Meldung 2): Inverse Umrechnung zu `_set_zoom_range`
        – volle Achse (span 1.0) => Slider 5 (links), maximale Vergroesserung
        (span 0.05) => Slider 100 (rechts).
        """
        try:
            lo, hi = float(zrange[0]), float(zrange[1])
        except (TypeError, ValueError, IndexError):
            lo, hi = 0.0, 1.0
        if hi <= lo:
            lo, hi = 0.0, 1.0
        value = int(round(105.0 - (hi - lo) * 100.0))
        slider.blockSignals(True)
        slider.setValue(max(slider.minimum(), min(slider.maximum(), value)))
        slider.blockSignals(False)

    def _update_controls(self) -> None:
        """Aktiviert/Deaktiviert Feld-Combo und Overlay (E6/E9).

        Bugfix 09.08.2026 (Punkt 6): Die Zoom-Slider gelten fuer ALLE
        Dimensionen/Massstaebe (nicht nur date) – je Zoom-Level werden
        dynamisch mehr Zwischenwerte auf den Achsen angezeigt.
        """
        if self._view_model is None:
            return
        x_dim = str(self._combo_x.currentData() or "")
        y_dim = str(self._combo_y.currentData() or "")
        agg = str(self._combo_agg.currentData() or "")
        self._slider_zoom_x.setEnabled(True)
        self._slider_zoom_y.setEnabled(True)
        is_value_agg = agg in _VALUE_AGGS
        self._combo_field.setEnabled(is_value_agg)
        if is_value_agg:
            self._combo_field.setToolTip(
                "Numerischer feature_data-JSON-Key (Feld) fuer AVG/SUM/MIN/MAX.")
        else:
            self._combo_field.setToolTip(
                "Nur fuer AVG/SUM/MIN/MAX relevant (E6); COUNT/CONFLUENCE "
                "ignorieren das Feld.")
        # 21.01 (User-Meldung 5, 11.08.2026): Das Kerzen-Overlay ist NUR
        # bei X-Achse = 'date' aktivierbar (Y=date/vertikale Anordnungen
        # sind keine offiziellen Ansichten mehr). Bei Y=date wird die
        # Checkbox hier deaktiviert und zurueckgesetzt (Restore-Fall).
        date_on_x = x_dim == "date"
        can_overlay = date_on_x
        self._chk_candle.setEnabled(can_overlay)
        if can_overlay:
            self._chk_candle.setToolTip(
                "Tages-Ohlc ueber der Heatmap (gleicher Canvas), "
                "Datum auf der X-Achse.")
        else:
            self._chk_candle.setToolTip(
                "Kerzen-Overlay nur mit 'Datum' auf der X-Achse "
                "verfuegbar.")
            # Meldung 5: Reste eines Overlays entfernen (loest
            # _on_candle_toggled(False) aus -> set_candle_projection(False)
            # + _clear_overlay im ViewModel/Widget).
            if self._chk_candle.isChecked():
                self._chk_candle.setChecked(False)
        # Meldung 5: Der Overlay-Link folgt NUR noch der X-Achse (date).
        # Ohne Overlay werden beide Links entfernt.
        link = can_overlay and self._chk_candle.isChecked()
        linked_x = self._price_vb.linkedView(pg.ViewBox.XAxis)
        linked_y = self._price_vb.linkedView(pg.ViewBox.YAxis)
        if link and linked_x is None:
            self._price_vb.setXLink(self._plot_hm.plotItem.vb)
        if link and linked_y is not None:
            self._price_vb.setYLink(None)
        if not link:
            if linked_x is not None:
                self._price_vb.setXLink(None)
            if linked_y is not None:
                self._price_vb.setYLink(None)

    # ------------------------------------------------------------------
    # Konfiguration -> ViewModel (Debounce -> Worker)
    # ------------------------------------------------------------------
    def _on_config_changed(self, *args) -> None:
        if self._syncing or self._view_model is None:
            return
        # Identische Achsen vermeiden (degenerierte Diagonal-Matrix).
        if self._combo_x.currentData() == self._combo_y.currentData():
            self._syncing = True
            try:
                fallback = ("hour" if self._combo_x.currentData() != "hour"
                            else "dow")
                self._set_combo_data(self._combo_y, fallback)
            finally:
                self._syncing = False
        # Overlay nur bei X=date (E9 / 21.01 User-Meldung 5) – sonst
        # ausschalten (Y=date ist keine offizielle Overlay-Ansicht mehr).
        if (self._combo_x.currentData() != "date"
                and self._chk_candle.isChecked()):
            self._chk_candle.setChecked(False)
        self._update_controls()
        self._apply_config()
        self.request_data()

    def _on_agg_changed(self, *args) -> None:
        if self._syncing or self._view_model is None:
            return
        self._update_controls()
        self._apply_config()
        self.request_data()

    def _apply_config(self) -> None:
        self._view_model.set_heatmap_config(
            x_dim=str(self._combo_x.currentData() or "date"),
            y_dim=str(self._combo_y.currentData() or "hour"),
            # 20.03.02 (F2): Aus dem '{service_id}|{key}'-userData nur den
            # JSON-Key extrahieren (heatmap_field bleibt ein reiner Key).
            field=self._field_key(self._combo_field.currentData()),
            agg=str(self._combo_agg.currentData() or "confluence_count"),
        )

    @staticmethod
    def _field_key(ud: Any) -> str:
        """Extrahiert den JSON-Key aus einem userData-Wert (20.03.02).

        'srv_proximity|visit_pct' -> 'visit_pct'; reine Keys bleiben.
        """
        s = str(ud or "")
        return s.split("|", 1)[1] if "|" in s else s

    def _find_field_index(self, key: str) -> int:
        """Item-Index im 'Feld'-Dropdown, dessen Key-Teil == `key` ist.

        20.03.02: Das userData traegt '{service_id}|{key}' – findData(key)
        wuerde den reinen Key nicht finden. Gibt -1 zurueck, wenn keiner
        passt (Restore-Fallback erzeugt dann ein neues Item). 20.03.03: Bei
        gemeinsamen Keys (2+ Quellen) findet die Methode zuerst den
        Sammel-Eintrag ('ALL|key' -> Key-Teil == key).
        """
        for i in range(self._combo_field.count()):
            if self._field_key(self._combo_field.itemData(i)) == key:
                return i
        return -1

    def _first_field_index(self) -> int:
        """Erster auswaehlbarer (nicht-Header) Item-Index im Feld-Dropdown
        (20.03.03, Q4).

        Sektions-Header haben `Qt.NoItemFlags` und duerfen nicht als
        Current-Item gewaehlt werden – Index 0 kann ein Header sein.
        """
        for i in range(self._combo_field.count()):
            item = self._combo_field.model().item(i)
            if item is not None and (item.flags() & Qt.ItemIsEnabled):
                return i
        return 0

    # ------------------------------------------------------------------
    # 20.03.02 (F1c/F2): Multi-Select im 'Feld'-Dropdown -> Datenquellen-
    # Filter `feature_ids` (KEINE Signatur-Aenderung von set_heatmap_config;
    # die Aggregation nutzt GENAU EIN aktives Hauptfeld).
    # ------------------------------------------------------------------
    def _on_field_selection_changed(self, _checked: List[str]) -> None:
        """CheckState-Wechsel im 'Feld'-Dropdown (nicht mehr verbunden).

        10.08.2026 (Bugfix Runde 7, Bug 4/5): Die Verbindung
        selection_changed -> dieser Handler wurde in __init__ entfernt - das
        'Feld'-Dropdown schreibt KEIN feature_ids mehr (Single Source of
        Truth = ServicePicker; kein Ueberschreiben des Restores). Der Handler
        bleibt als Bestandscode erhalten.
        -> feature_ids-Filter.

        Die angehakten Items bestimmen die Datenquellen (`set_feature_ids`);
        `set_feature_ids` stoesst den Debounce-Refresh der generischen
        Heatmap (und der uebrigen Analytics-Seiten) an. Leere Auswahl =
        leerer Filter (alle Features, ViewModel-Semantik 15.03-E).

        20.03.03 (Q5): Vor der Filterableitung wird die XOR-Regel angewendet –
        Sammel- ('ALL|key') und Einzel-Eintraege ('srv_x|key') desselben Keys
        schliessen sich gegenseitig aus (keine Doppel-Haken).
        """
        if self._syncing or self._view_model is None:
            return
        self._reconcile_sammel_checks()
        ids = self._checked_field_service_ids()
        self._view_model.set_feature_ids(ids)

    def _reconcile_sammel_checks(self) -> None:
        """XOR-Reconciliation (20.03.03, Q5): Sammel- und Einzel-Eintraege
        desselben Keys schliessen sich gegenseitig aus.

        Grundlage ist der ZULETZT geklickte Eintrag (`last_click_index`):
        - Klick auf `ALL|key` (Sammel)  -> Einzel-Eintraege von `key` abwaehlen.
        - Klick auf `srv_x|key` (Einzel) -> Sammel-Eintrag `ALL|key` abwaehlen.
        Programmatische Wechsel (kein Klick, Index -1) loesen nichts auf.
        Danach wird der Current-Index auf ein angehaktes/auswaehlbares Item
        nachgezogen.
        """
        last_idx = self._combo_field.last_click_index()
        if last_idx < 0:
            self._sync_field_current_after_checks()
            return
        item = self._combo_field.model().item(last_idx)
        if item is None or not (item.flags() & Qt.ItemIsEnabled):
            return
        ud = str(item.data(Qt.UserRole) or "")
        checked = [str(u or "") for u in self._combo_field.checked_data()]
        if ud.startswith("ALL|"):
            # Sammel gewinnt: alle Einzel-Eintraege desselben Keys abwaehlen.
            key = ud.split("|", 1)[1]
            wanted = [u for u in checked
                      if not (u.endswith(f"|{key}") and not u.startswith("ALL|"))]
            if wanted != checked:
                self._combo_field.set_checked_data(wanted)
        elif "|" in ud:
            # Einzel gewinnt: Sammel-Eintrag desselben Keys abwaehlen.
            all_ud = f"ALL|{self._field_key(ud)}"
            if all_ud in checked:
                self._combo_field.set_checked_data(
                    [u for u in checked if u != all_ud])
        self._sync_field_current_after_checks()

    def _sync_field_current_after_checks(self) -> None:
        """Stellt sicher, dass der aktuelle Feld-Index auf einem anhakbaren
        Item mit aktivem CheckState steht (20.03.03, Q5).

        Nach der XOR-Reconciliation kann der Index auf einem abgewaehlten
        oder deaktivierten (Header-)Item stehen – dann wird er (blockiert)
        auf das erste angehakte, sonst erste auswaehlbare Item nachgezogen.
        """
        idx = self._combo_field.currentIndex()
        item = self._combo_field.model().item(idx)
        if (item is not None and (item.flags() & Qt.ItemIsEnabled)
                and item.checkState() == Qt.Checked):
            return
        new_idx = -1
        for i in range(self._combo_field.count()):
            it = self._combo_field.model().item(i)
            if it is None or not (it.flags() & Qt.ItemIsEnabled):
                continue
            if it.checkState() == Qt.Checked:
                new_idx = i
                break
        if new_idx < 0:
            for i in range(self._combo_field.count()):
                it = self._combo_field.model().item(i)
                if it is not None and (it.flags() & Qt.ItemIsEnabled):
                    new_idx = i
                    break
        if 0 <= new_idx != idx:
            self._combo_field.blockSignals(True)
            self._combo_field.setCurrentIndex(new_idx)
            self._combo_field.blockSignals(False)

    def _checked_field_service_ids(self) -> List[str]:
        """Service-IDs der angehakten Feld-Items (20.03.03, Q2).

        - `ALL|<key>` (Sammel-Eintrag) wird ueber `self._field_sources[key]`
          auf ALLE Quellen-Services des Keys expandiert (Confluence).
        - `{service_id}|<key>` liefert genau seine service_id.
        Items ohne `|` (roher Legacy-Key) tragen keinen eindeutigen Service
        und bleiben aussen vor (die Quellen der Einzel-Keys decken den
        Filter ab). Dedupliziert, in Item-Reihenfolge.
        """
        ids: List[str] = []
        for ud in self._combo_field.checked_data():
            s = str(ud or "")
            if s.startswith("ALL|"):
                key = s.split("|", 1)[1]
                for sid in (self._field_sources.get(key) or []):
                    if sid and sid not in ids:
                        ids.append(sid)
            elif "|" in s:
                sid = s.split("|", 1)[0]
                if sid and sid not in ids:
                    ids.append(sid)
        return ids

    # ------------------------------------------------------------------
    # Candle-Overlay (Bugfix 1, im selben Canvas) + Zoom (E8)
    # ------------------------------------------------------------------
    def _on_candle_toggled(self, checked: bool) -> None:
        if self._syncing or self._view_model is None:
            return
        self._view_model.set_candle_projection(bool(checked))
        # 20.02.01 (E7): Link-Zustand an den Overlay-Zustand koppeln.
        self._update_controls()
        if checked:
            # 21.01 (Bugfix 5): OHLCV im Heatmap-TF (adaptiv) statt
            # Tages-Aggregation.
            self._view_model.request_ohlcv_snapshot()
        else:
            self._clear_overlay()

    def _on_zoom_x_changed(self, value: int) -> None:
        if self._syncing or self._view_model is None:
            return
        self._set_zoom_range("zoom_x_range", value)
        self._apply_x_range()

    def _on_zoom_y_changed(self, value: int) -> None:
        if self._syncing or self._view_model is None:
            return
        self._set_zoom_range("zoom_y_range", value)
        self._apply_y_range()

    def _set_zoom_range(self, key: str, value: int) -> None:
        """Berechnet [lo, hi] (zentriert) aus dem Slider-Wert (E8).

        09.08.2026 (User-Meldung 2): Richtung getauscht – rechts (hoher
        Slider-Wert) = Zoom-In, links (niedriger Wert) = Zoom-Out. Der
        Slider-Wert ist die Zoom-Stufe 5..100; der sichtbare Anteil
        `f = (105 - value) / 100` (5 => volle Achse, 100 => maximale
        Vergroesserung, zentriert auf 0.5).
        """
        f = (105.0 - value) / 100.0
        lo = max(0.0, 0.5 - f / 2.0)
        hi = min(1.0, 0.5 + f / 2.0)
        zx = list(self._view_model.params.get("zoom_x_range") or [0.0, 1.0])
        zy = list(self._view_model.params.get("zoom_y_range") or [0.0, 1.0])
        if key == "zoom_x_range":
            zx = [lo, hi]
        else:
            zy = [lo, hi]
        self._view_model.set_heatmap_zoom(zx, zy)

    @staticmethod
    def _zoom_lo_hi(params: Dict[str, Any], key: str) -> List[float]:
        try:
            lo, hi = params[key]
            lo, hi = float(lo), float(hi)
        except (TypeError, ValueError, IndexError, KeyError):
            lo, hi = 0.0, 1.0
        if hi <= lo:
            lo, hi = 0.0, 1.0
        return [lo, hi]

    def _apply_x_range(self) -> None:
        """Wendet zoom_x_range auf die Heatmap an (E8, natuerliche Werte)."""
        if self._view_model is None:
            return
        lo, hi = self._zoom_lo_hi(self._view_model.params, "zoom_x_range")
        span = self._x_max - self._x_min
        self._plot_hm.setXRange(
            self._x_min + lo * span, self._x_min + hi * span, padding=0)

    def _apply_y_range(self) -> None:
        """Wendet zoom_y_range auf die Heatmap an (E8, natuerliche Werte)."""
        if self._view_model is None:
            return
        lo, hi = self._zoom_lo_hi(self._view_model.params, "zoom_y_range")
        span = self._y_max - self._y_min
        self._plot_hm.setYRange(
            self._y_min + lo * span, self._y_min + hi * span, padding=0)

    def _update_price_view(self) -> None:
        """Synchronisiert die Preis-ViewBox-Geometrie mit der Heatmap.

        10.08.2026 (Bugfix Runde 7, Bug 1): Je nach gekoppelter Date-Achse
        (X oder Y) wird die passende Achse benachrichtigt.
        """
        vb = self._plot_hm.plotItem.vb
        self._price_vb.setGeometry(vb.sceneBoundingRect())
        if self._price_vb.linkedView(pg.ViewBox.XAxis) is not None:
            self._price_vb.linkedViewChanged(vb, self._price_vb.XAxis)
        if self._price_vb.linkedView(pg.ViewBox.YAxis) is not None:
            self._price_vb.linkedViewChanged(vb, self._price_vb.YAxis)

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def _on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind == QUERY_HEATMAP_GENERIC:
            # Runde 12 (Option A): No-Data-Varianten aus dem HEATMAP-Payload
            # uebernehmen (Generation-Guard) VOR dem Render - die
            # '(No Data)'-Items erscheinen im selben Durchlauf wie die Grafik.
            self._cache_no_data_from_payload(data)
            self._render_generic(data)
        elif kind in (QUERY_DAILY_OHLC, QUERY_OHLCV):
            # 21.01 (Bugfix 5): QUERY_OHLCV liefert die Bars im Heatmap-TF
            # (adaptives Overlay); QUERY_DAILY_OHLC bleibt als
            # Kompatibilitaets-Pfad erhalten.
            self._render_overlay(data)
        elif kind == QUERY_FEATURES:
            # Runde 11 (Bug 4, B4-3): Kompatibilitaets-Pfad (z. B. der
            # refresh_all() der Initial-Ladung stoesst QUERY_FEATURES an).
            self._on_features_ready(data)

    def _cache_no_data_from_payload(self, data: Dict[str, Any]) -> bool:
        """Uebernimmt no_data_variants aus einem Payload (Generation-Guard).

        Runde 12 (Option A): Gemeinsamer Cache-Pfad fuer den
        QUERY_HEATMAP_GENERIC-Payload (No-Data im selben Datenfluss) und
        den QUERY_FEATURES-Kompatibilitaets-Payload. Returns False, wenn
        kein No-Data-Anteil im Payload ist (dann bleibt der Cache
        unveraendert) oder der Payload stale ist (aeltere Generation).
        """
        if self._view_model is None:
            return False
        vm = self._view_model
        payload_gen = data.get("restore_generation")
        if (payload_gen is not None
                and str(payload_gen) != str(
                    getattr(vm, "restore_generation", 0))):
            return False  # Stale-Payload (Query lief VOR dem letzten Restore)
        if "no_data_variants" not in data:
            return False  # Payload ohne No-Data-Anteil (z. B. Alt-Payload)
        variants = data.get("no_data_variants")
        self._no_data_variants = (
            [dict(v) for v in variants] if isinstance(variants, list)
            else [])
        self._no_data_variants_error = bool(
            data.get("no_data_variants_error"))
        return True

    def _on_features_ready(self, data: Dict[str, Any]) -> None:
        """Uebernimmt die No-Data-Varianten aus einem QUERY_FEATURES-Payload.

        Runde 11 (Bug 4, B4-2/B4-3): Payload-Vertrag `no_data_variants`
        IMMER vorhanden; `no_data_variants_error` markiert einen
        fehlgeschlagenen Check. Stale-Payloads werden verworfen
        (Generation-Guard). Danach wird das 'Feld'-Dropdown aus dem Cache
        neu abgeleitet (die '(No Data)'-Items erscheinen/verschwinden).

        Runde 15 (Fix 1, Ultra-Low-Latency): Der QUERY_FEATURES-Payload
        traegt jetzt zusaetzlich `metrics`/`field_sources` (Feld-Metadaten,
        Repository `_field_metadata`) – das 'Feld'-Dropdown wird damit
        BEREITS aus dem leichten Metadaten-Query gefuellt (KEIN Warten auf
        die teure Heatmap-Pivot-Aggregation).
        """
        if not self._cache_no_data_from_payload(data):
            return
        # Runde 15 (Fix 1): Feld-Metadaten aus dem Leicht-Payload uebernehmen
        # (falls vorhanden) – sonst bleibt der bestehende Widget-Cache.
        keys = [str(m) for m in (data.get("metrics") or [])
                if m not in ("count", "confluence_count")]
        field_sources = data.get("field_sources")
        if keys or field_sources:
            self._rebuild_field_dropdown(
                keys,
                field_sources if isinstance(field_sources, dict) else {})
        else:
            self._rebuild_field_dropdown(self._field_keys, self._field_sources)

    def _on_query_failed(self, kind: str, _error: str) -> None:
        """Runde 11 (Bug 4, B4-2): Fehlerzustand des No-Data-Checks.

        Schlaegt die QUERY_FEATURES-Abfrage fehl (kein Payload), zeigt das
        Feld-Dropdown den 'Pruefung fehlgeschlagen'-Hinweis statt stumm zu
        bleiben (verschluckte Fehler, User-Analyse Punkt 2).
        """
        if kind == QUERY_FEATURES:
            self._no_data_variants = []
            self._no_data_variants_error = True
            self._rebuild_field_dropdown(self._field_keys,
                                         self._field_sources)

    def _render_generic(self, data: Dict[str, Any]) -> None:
        matrix = np.asarray(data.get("matrix") or [], dtype=float)
        x_dim = str(data.get("x_dim")
                    or self._combo_x.currentData() or "date")
        y_dim = str(data.get("y_dim")
                    or self._combo_y.currentData() or "hour")
        # Natuerliche Achsen-Koordinaten (Bugfix 3: Reader liefert sie).
        x_axis = data.get("x_axis") or []
        y_axis = data.get("y_axis") or []
        self._x_dates = []
        if x_dim == "date":
            for v in (data.get("x_values") or []):
                try:
                    self._x_dates.append(
                        datetime.fromisoformat(str(v)).date())
                except (TypeError, ValueError):
                    self._x_dates.append(None)
        # Combos/Slider aus dem Payload synchronisieren (tatsaechlich
        # verwendete Werte; Repository-Fallbacks z. B. fuer `field`).
        self._sync_combos_from_payload(data)
        agg = str(data.get("agg") or "count")

        if matrix.size == 0:
            self._n_cols = self._n_rows = 0
            self._x_axis = []
            self._y_axis = []
            self._image.clear()
            self._label_info.setText("Keine Daten")
            self._legend.hide()  # 21.01 Bugfix 2: keine Legende ohne Daten
            self._grid_lines.setData([], [])  # 21.01 R3: keine Teiler
            self._clear_overlay()
            return

        self._n_cols = int(matrix.shape[1])
        self._n_rows = int(matrix.shape[0])
        self._x_axis = [float(v) for v in (x_axis or
                                           list(range(self._n_cols)))]
        self._y_axis = [float(v) for v in (y_axis or
                                           list(range(self._n_rows)))]

        # E7: Colormap abhaengig von der Aggregation.
        if agg == "confluence_count":
            if self._colormap_mode != "confluence":
                self._image.setColorMap(self._cmap_confluence)
                try:
                    self._colorbar.setColorMap(self._cmap_confluence)
                except Exception:
                    pass
                self._colormap_mode = "confluence"
            # 21.01 (User-Meldung 7, 11.08.2026): Die festen Levels
            # (0.0, 5.0) passten nicht zu echten Daten (Max ~1) - die
            # Farbgraduierung blieb stumpf (fast nur Weiss/Gelb). Die
            # Levels werden jetzt DATEN-GEBUNDEN gesetzt: 0 (keine
            # Konfluenz) = weiss, vmax = staerkste Farbe (dunkelrot).
            finite = matrix[np.isfinite(matrix)]
            if finite.size:
                vmax = float(finite.max())
                vmin = min(0.0, float(finite.min()))
            else:
                vmin, vmax = 0.0, 1.0
            if vmax <= vmin:
                vmax = vmin + 1.0
            self._image.setImage(matrix, levels=(vmin, vmax))
            self._colorbar.setLevels((vmin, vmax))
        else:
            if self._colormap_mode != _VIRIDIS:
                self._image.setColorMap(self._cmap_viridis)
                try:
                    self._colorbar.setColorMap(self._cmap_viridis)
                except Exception:
                    pass
                self._colormap_mode = _VIRIDIS
            finite = matrix[np.isfinite(matrix)]
            if finite.size:
                vmin = float(finite.min())
                vmax = float(finite.max())
                if vmin == vmax:
                    vmax = vmin + 1.0
            else:
                vmin, vmax = 0.0, 1.0
            self._image.setImage(matrix, levels=(vmin, vmax))
            self._colorbar.setLevels((vmin, vmax))

        # 21.01 (Bugfix 2): Diskrete Schwellwert-Legende (oben rechts)
        # an die aktuelle Colormap/Levels anpassen.
        self._update_legend()

        # ImageItem exakt auf die natuerlichen Koordinaten mappen (Bugfix 3):
        # date-Spalten = Tage (zentriert auf Mitternacht), hour/dow =
        # ganzzahlige Werte (feste Skalen, E3/E5), kategorial = Indizes.
        # Nichts wird ueber die Tagesgrenze hinaus gezeichnet (Punkt 3).
        self._x_min, self._x_max = self._axis_bounds(self._x_axis, x_dim)
        self._y_min, self._y_max = self._axis_bounds(self._y_axis, y_dim)
        self._image.setRect(QRectF(
            self._x_min, self._y_min,
            self._x_max - self._x_min, self._y_max - self._y_min))

        # 21.01 (Bugfix-Runde 3, Entscheidung 2a): Senkrechte Teiler je
        # Dateneinheit (TF-Bar-Intervall) an der X-Achse (date).
        self._update_grid_lines()

        # 20.02.01 (E8): service_id-Achsen-Labels ueber den ViewModel-
        # Resolver ({Kategorie} / {Name}, `srv_`-Prefix entfaellt).
        x_labels = data.get("x_labels") or []
        y_labels = data.get("y_labels") or []
        if x_dim == "service_id" and self._view_model is not None:
            x_labels = [self._view_model.resolve_service_label(str(l))
                        for l in x_labels]
        if y_dim == "service_id" and self._view_model is not None:
            y_labels = [self._view_model.resolve_service_label(str(l))
                        for l in y_labels]
        # Dynamische Achsen konfigurieren (Bugfix 5+6).
        self._axis_x.configure(x_dim, x_labels)
        self._axis_y.configure(y_dim, y_labels)

        # 20.02.01 (E4): Achsen-Label der Tageszeit mit UTC-Offset –
        # DST-robust aus dem neuesten Datumswert der Daten abgeleitet
        # (kein Berlin-Offset, Invariante 7; die Epochs sind Wanduhr-encoded).
        offset_epoch: Optional[float] = None
        if x_dim == "date" and self._x_axis:
            offset_epoch = self._x_axis[-1]
        elif y_dim == "date" and self._y_axis:
            offset_epoch = self._y_axis[-1]
        offset_text = self._utc_offset_text(offset_epoch)
        label_x = _DIM_LABELS.get(x_dim, x_dim)
        label_y = _DIM_LABELS.get(y_dim, y_dim)
        # 09.08.2026 (User-Meldung): Die date-Achse heisst 'Datum/Zeit'
        # (ohne pyqtgraph-EXP-Suffix – das unterdrueckt _HeatmapAxis via
        # enableAutoSIPrefix(False), s. o.).
        if x_dim == "date":
            label_x = "Datum/Zeit"
        if y_dim == "date":
            label_y = "Datum/Zeit"
        if x_dim == "hour":
            label_x = f"{label_x} ({offset_text})"
        if y_dim == "hour":
            label_y = f"{label_y} ({offset_text})"
        self._plot_hm.setLabel("bottom", label_x)
        self._plot_hm.setLabel("left", label_y)

        self._apply_x_range()
        self._apply_y_range()
        self._label_info.setText(f"{self._n_rows} x {self._n_cols}")

        # Bugfix 1/2 + 21.01 Bugfix 5: Bei aktivem Overlay den OHLCV-
        # Snapshot IM HEATMAP-TIMEFRAME laden (adaptiv fuer alle TFs).
        if self._chk_candle.isChecked() and self._view_model is not None:
            self._view_model.request_ohlcv_snapshot()

    @staticmethod
    def _axis_bounds(axis: List[float], dim: str):
        """Koordinaten-Bereich [lo, hi] fuer eine Achse (natuerliche Werte).

        20.02.01 (E3/E5): `hour` und `dow` haben FESTE Skalen unabhaengig
        vom Datenbereich – Tageszeit 00:00-23:59 (halboffene Zellen
        [h, h+1), Range 0..24) und Wochentag strikt Montag-Freitag
        (Mo=1..Fr=5, Range 1..6). Das garantiert stabil vergleichbare
        Achsen zwischen Symbolen/Timeframes. `date` bleibt datenabhaengig
        (Mitternachts-Epochs +/- halber Tag), kategorial = Indizes 0..n-1.
        """
        if dim == "hour":
            return 0.0, float(HOURS_PER_DAY)
        if dim == "dow":
            return 1.0, 1.0 + float(len(DOW_WEEK_LABELS))
        if not axis:
            return -0.5, 0.5
        lo = float(min(axis))
        hi = float(max(axis))
        if dim == "date":
            # Zellen = Tage, zentriert auf Mitternacht (Wanduhr).
            return lo - _HALF_DAY, hi + _HALF_DAY
        # Kategorial (timeframe/service_id/symbol): Indizes 0..n-1.
        return -0.5, float(len(axis)) - 0.5

    def _utc_offset_text(self, epoch: Optional[float]) -> str:
        """UTC-Offset der Berliner Wanduhr als Label-Text (20.02.01, E4).

        Liefert z. B. 'UTC+2' (Sommer) bzw. 'UTC+1' (Winter) – DST-robust
        aus dem UHRZEITPUNKT abgeleitet: Bevorzugt der neueste Datums-
        Epoch der Daten (falls eine date-Achse vorhanden ist), sonst die
        aktuelle Systemzeit (der Rechner laeuft in der Berliner Zeitzone,
        vgl. Invariante 7). Die Wanduhr-Epochs werden UNABHAENGIG vom
        Offset formatiert (UTC-Darstellung) – der Offset dient nur der
        Information 'Tageszeit (UTC+X)'.
        """
        try:
            if epoch is not None and epoch > 0:
                ts = datetime.fromtimestamp(float(epoch))
            else:
                ts = datetime.now()
            offset = ts.astimezone().utcoffset()
            if offset is None:
                return "UTC"
            total = int(offset.total_seconds() // 3600)
            sign = "+" if total >= 0 else "-"
            return f"UTC{sign}{abs(total)}"
        except Exception:
            return "UTC"

    def _field_label(self, key: str, service_ids: List[str]) -> str:
        """Anzeige-Text eines Feld-Eintrags (Meldung 3b/c, 09.08.2026).

        Der Service-Name wird DIREKT aus dem Service-Objekt geholt
        (`resolve_service_display_name`, plugin_id-basiert, `srv_`-Prefix
        entfaellt -> 'Swing Momentum' statt 'Swing Momentum Service').
        Ist der Key EINDEUTIG einem Service zuzuordnen, steht dessen
        korrekter Name vor dem Key ('{Name} / {Key}', z. B.
        'Grid Lines / open'). Liefern MEHRERE Services denselben Key
        (z. B. 'price' von Swing-Services), entfaellt der Prefix KOMPLETT –
        sonst wuerde eine irrefuehrende 'Pfad'-Kette ('Swing Momentum
        Service / Swing Volume Profile Service / price') entstehen
        (User-Meldung, 09.08.2026: 'Pfad im Mastertree' = absoluter
        Quatsch). Ohne bekannte Quelle bleibt der Roh-Key (defensiv).
        """
        if (len(service_ids) == 1 and self._view_model is not None):
            name = self._view_model.resolve_service_display_name(
                str(service_ids[0]))
            if name:
                label = f"{name} / {str(key)}"
                # Runde 16 (Bugfix 1, 11.08.2026): Gecheckte Variante +
                # Datum der letzten Ausfuehrung an den Eintrag anhaengen
                # ('{Name} / {Key} / {Preset} / DD.MM.JJ HH:MM' - der
                # Service-Name ohne `srv_`-Praefix, Preset 'Default' wird
                # uebersprungen, Datum ohne Eintraege wird ausgelassen).
                # Defensiv via getattr: Fake-/Alt-ViewModels (z. B. in
                # Tests) ohne `checked_variant` ergeben keinen Anhang.
                variant = None
                _cv = getattr(self._view_model, "checked_variant", None)
                if callable(_cv):
                    try:
                        variant = _cv(str(service_ids[0]))
                    except Exception:
                        variant = None
                if variant:
                    preset = str(variant.get("preset_name") or "").strip()
                    if preset and preset.lower() != "default":
                        label = f"{label} / {preset}"
                    exec_date = str(
                        variant.get("exec_datetime") or "").strip()
                    if exec_date and not exec_date.startswith("--."):
                        label = f"{label} / {exec_date}"
                else:
                    # Runde 16c (Bugfix 1, 11.08.2026, User-Meldung):
                    # Services OHNE Varianten (Standalone, keine Presets)
                    # bekommen das Datum+Uhrzeit der letzten Ausfuehrung
                    # angehaengt ('{Name} / {Key} / DD.MM.JJ HH:MM', z. B.
                    # '23.04.26 22:14'), wenn vorhanden. Defensiv via
                    # getattr: Fake-/Alt-ViewModels ohne die Methode
                    # ergeben keinen Anhang.
                    _sd = getattr(self._view_model,
                                  "service_execution_datetime", None)
                    if callable(_sd):
                        try:
                            exec_date = str(
                                _sd(str(service_ids[0])) or "").strip()
                            if exec_date and not exec_date.startswith("--."):
                                label = f"{label} / {exec_date}"
                        except Exception:
                            pass
                return label
        return str(key)

    def _rebuild_field_dropdown(
        self,
        keys: List[str],
        field_sources: Dict[str, List[str]],
        payload_agg: Optional[str] = None,
        payload_field: Optional[str] = None,
    ) -> None:
        """Baut das 'Feld'-Dropdown aus Feld-Metadaten + VM-Params (Runde 8).

        Single Source of Truth:
          * Items      -> `keys`/`field_sources` (Payload-Metadaten bzw.
                          Widget-Cache `self._field_keys/_field_sources`)
          * Haken      -> `feature_ids` (ServicePicker, aktiver Filter)
          * Current    -> `heatmap_field` (Restore/Workspace gewinnt)

        SYNCHRON (kein Query-Round-Trip): wird aus dem Datenpfad
        (_sync_combos_from_payload) UND dem VM-Pfad (_sync_from_params /
        _on_feature_ids_changed) gerufen. Ein restaurierter
        Ergebnisparameter (Bug 3) bleibt dadurch auch ohne frischen Payload
        sichtbar; ein Check/Uncheck im ServicePicker (Bug 4) aktualisiert
        das Dropdown sofort. Die Runde-7-Prioritaet (VM-Params gewinnen
        gegen einen Stale-Payload) wird hier zentral angewendet.
        """
        if self._view_model is None:
            return
        p = self._view_model.params
        # Cache aktualisieren (Payload-Metadaten bzw. uebergebene Werte).
        self._field_keys = [str(k) for k in (keys or [])]
        self._field_sources = {
            str(k): [str(s) for s in (v or [])]
            for k, v in (field_sources or {}).items()
        }
        # Agg/Feld: restaurierte VM-Params gewinnen; erst wenn der VM leer
        # ist, zaehlen Payload-Fallback bzw. aktueller Combo-Wert (Runde 7).
        agg = (str(p.get("heatmap_agg") or "") or str(payload_agg or "")
               or str(self._combo_agg.currentData() or ""))
        prev_field = (str(p.get("heatmap_field") or "")
                      or str(payload_field or "")
                      or self._field_key(self._combo_field.currentData()))
        active_ids = {str(f).strip().lower()
                      for f in (p.get("feature_ids") or [])}
        no_filter = not active_ids
        try:
            self._combo_field.blockSignals(True)
            self._combo_field.clear()
            shared = sorted(k for k in self._field_keys
                            if len(self._field_sources.get(k) or []) >= 2)
            if shared:
                self._combo_field.add_header_item(
                    "🌐 Gleiche Parameter (alle aktiven Services):")
                for k in shared:
                    src = self._field_sources.get(k) or []
                    self._combo_field.add_checkable_item(
                        f"Alle Services / {k}", f"ALL|{k}",
                        checked=no_filter or all(
                            s.lower() in active_ids for s in src))
            if self._field_keys:
                self._combo_field.add_header_item("🔌 Einzelservices:")
            for k in sorted(self._field_keys):
                sids = self._field_sources.get(k) or []
                if len(sids) == 1:
                    # Eindeutiger Service: nur angehakt, wenn der Service im
                    # aktiven Filter liegt (oder kein Filter).
                    self._combo_field.add_checkable_item(
                        self._field_label(k, sids), f"{sids[0]}|{k}",
                        checked=no_filter or sids[0].lower() in active_ids)
                elif not sids:
                    # Legacy ohne field_sources (roher Key, defensiv).
                    self._combo_field.add_checkable_item(k, k, checked=True)
                else:
                    # Shared Key: je Quelle ein Einzel-Eintrag, initial NICHT
                    # angehakt (der Sammel-Eintrag deckt die Quellen ab, Q5).
                    all_active = all(s.lower() in active_ids for s in sids)
                    for sid in sids:
                        self._combo_field.add_checkable_item(
                            self._field_label(k, [sid]), f"{sid}|{k}",
                            checked=no_filter
                            or (sid.lower() in active_ids and not all_active))
            if prev_field in self._field_keys:
                self._combo_field.setCurrentIndex(
                    self._find_field_index(prev_field))
            elif self._field_keys:
                # 20.03.03 (Q4): Index 0 kann ein Header sein -> ersten
                # auswaehlbaren Eintrag waehlen.
                self._combo_field.setCurrentIndex(self._first_field_index())
            elif prev_field:
                # Kein Payload/Cache (Restore vor dem ersten Datenpaket):
                # Roh-Item anlegen, damit der restaurierte Wert sichtbar
                # und ausgewaehlt bleibt (Muster _sync_from_params).
                self._combo_field.add_checkable_item(
                    prev_field, prev_field, checked=True)
                self._combo_field.setCurrentIndex(
                    self._combo_field.count() - 1)
            # Runde 11 (Bug 4, B4-1): '(No Data)'-Hinweise kommen jetzt als
            # Payload-Attribut `no_data_variants` vom QUERY_FEATURES-Worker
            # (Cache self._no_data_variants) - KEIN synchroner DB-Zugriff
            # mehr im UI-Hauptthread. Die Anzeige unterscheidet Loading/
            # Erfolg/Fehler und filtert nach aktiven instance_hashes (B4-5).
            self._render_no_data_items()
        finally:
            self._combo_field.blockSignals(False)
        self._update_controls()
        # E6: Wert-Aggregation mit leerem/abweichendem Feld -> restauriertes
        # Feld gewinnt (falls im Datensatz verfuegbar), sonst ersten Key
        # uebernehmen und Konfiguration nachreichen (einmaliger Query-Loop).
        vm_field = str(p.get("heatmap_field") or "")
        if (agg in _VALUE_AGGS and self._combo_field.currentData()
                and vm_field != self._field_key(
                    self._combo_field.currentData())):
            if vm_field and vm_field in self._field_keys:
                fidx = self._find_field_index(vm_field)
                if fidx >= 0:
                    self._combo_field.setCurrentIndex(fidx)
            else:
                self._apply_config()

    def _render_no_data_items(self) -> None:
        """Rendert die No-Data-Hinweise aus dem Payload-Cache (B4-2/B4-5).

        Runde 11 (Bug 4): Die '(No Data)'-Varianten kommen vom
        QUERY_FEATURES-Worker (`no_data_variants` im Payload) - kein
        synchroner DB-Zugriff mehr. Die Anzeige unterscheidet:
          * Payload ausstehend (self._no_data_variants is None) -> nichts
          * Payload-Fehler   -> '⚠️ No-Data-Prüfung ...' (deaktiviert)
          * Erfolg + Liste   -> '(No Data)'-Abschnitt (deaktivierte Items)

        Runde 13 (Bugfix Dropdown-NoData): Der Payload ist seit dem
        Reader-Hash-Filter bereits VARIANTEN-GENAU - `no_data_variants`
        enthaelt nur noch die im ServicePicker gecheckten Varianten
        (und nur Services aus `feature_ids`). Die Widget-seitigen Filter
        (active_ids/active_hashes) sind damit redundant, bleiben aber
        DEFENSIV aktiv (schuetzt z. B. gegen Alt-Payloads vom
        QUERY_FEATURES-Kompatibilitaetspfad ohne Hash-Filter). Die
        gewaehlte Variante ist in Runde 13 immer Teil des Abschnitts -
        die B4-5-Inline-Ergaenzung greift nur noch bei Defensiv-Luecken.

        Runde 13c (Kernwunsch): Bei leerem feature_ids-Filter (leer =
        kein Filter = alle Features) wird KEIN '(No Data)'-Abschnitt UND
        kein No-Data-Fehlerhinweis gerendert - der Button 'Aktive Filter
        entfernen' zeigt danach wieder alle Features ohne NoData-Rauschen
        (der VM-Snapshot liefert bei leerem Filter bereits keine
        Varianten; dieser Guard schuetzt zusaetzlich gegen Alt-/
        Stale-Payloads).
        """
        if self._view_model is None:
            return
        p = self._view_model.params
        # Runde 12 (Punkt 4) + Runde 13c (Kernwunsch): Nur Services im
        # aktiven feature_ids-Filter duerfen NoData-Hinweise liefern.
        # Leerer Filter (leer = kein Filter = alle Features) -> KEINE
        # Hinweise (auch kein Fehler-/Loading-Hinweis), damit der Button
        # 'Aktive Filter entfernen' alle Features ohne NoData-Rauschen
        # zeigt.
        active_ids = {str(f).strip().lower()
                      for f in (p.get("feature_ids") or [])}
        if not active_ids:
            return
        if self._no_data_variants_error:
            self._combo_field.add_disabled_item(
                "⚠️ No-Data-Prüfung konnte nicht durchgeführt werden")
            return
        if self._no_data_variants is None:
            return  # Loading: Payload steht noch aus (kein Hinweis noetig)
        # Runde 13: `instance_hashes` ist seit dem MasterTree-Fix auch fuer
        # Set-Instanz-Varianten (TYPE_SERVICE) gefuellt. Der Reader filtert
        # den Payload bereits danach - hier defensiv gegen Alt-Payloads.
        active_hashes = {str(h).strip().lower()
                         for h in (p.get("instance_hashes") or [])}
        variants = [dict(v) for v in self._no_data_variants]
        filtered = variants
        if active_ids:
            filtered = [v for v in filtered
                        if str(v.get("plugin_id") or "").strip().lower()
                        in active_ids]
        # Runde 16 (Bugfix Mischbetrieb, User-Meldung 5/6, 11.08.2026):
        # Hash-lose Varianten (Standalone-Services wie srv_trend_breakout
        # und NULL-Hash-Alt-Bestand) werden UEBER `feature_ids` gecheckt -
        # eine aktive Hash-Auswahl darf sie nicht aus dem '(No Data)'-
        # Abschnitt werfen (sonst verschwinden Services im Mischbetrieb
        # aus dem Feld-Dropdown, obwohl sie gecheckt sind).
        if active_hashes:
            filtered = [v for v in filtered
                        if not str(v.get("instance_hash") or "").strip()
                        or str(v.get("instance_hash") or "").strip().lower()
                        in active_hashes]
        if not filtered and self._selected_no_data_variant(variants) is None:
            return
        self._combo_field.add_header_item(
            "🕓 Noch ohne Daten (erster Scan ausstehend):")
        rendered: set = set()
        for nd in filtered:
            rendered.add((str(nd.get("plugin_id") or "").strip().lower(),
                          str(nd.get("instance_hash") or "").strip().lower()))
            # Runde 11 (B4-2): display_name enthaelt den Preset bereits
            # (resolve_service_display_name/Reader-Fallback) - keine
            # doppelte '(preset)'-Ergaenzung im Item-Text.
            self._combo_field.add_disabled_item(
                f"{nd.get('display_name') or nd.get('plugin_id')} – (No Data)")
        # B4-5 (Runde 13): Die gewaehlte Variante bleibt zusaetzlich inline
        # sichtbar (ausgegraut) - defensiv: nur wenn die Widget-Filter sie
        # wider Erwarten nicht im Abschnitt haetten (Reader-Hash-Filter
        # und Widget-Filter koennen nicht divergieren, solange beide auf
        # `instance_hashes` basieren).
        sel = self._selected_no_data_variant(variants)
        if sel is not None:
            key = (str(sel.get("plugin_id") or "").strip().lower(),
                   str(sel.get("instance_hash") or "").strip().lower())
            if key not in rendered:
                self._combo_field.add_disabled_item(
                    f"→ {sel.get('display_name') or sel.get('plugin_id')} – (No Data)")

    def _selected_no_data_variant(
        self, variants: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """No-Data-Variante des aktuell gewaehlten Feld-Items (oder None).

        Runde 12 (Punkt 3): Das Feld-Item-userData traegt '{service_id}|{key}'
        (ein Feld-Item repraesentiert einen SERVICE, nicht eine Variante) -
        die GEWAEHLTE Variante wird ueber den aktiven instance_hashes-Filter
        des ServicePickers identifiziert: Liefert der Service mehrere
        No-Data-Varianten, gewinnt die gecheckte Variante (exakter Hash-
        Match) statt immer der ersten. Runde 12 (Punkt 4): Services, die
        NICHT im aktiven feature_ids-Filter liegen, werden ignoriert
        (None - keine Inline-Markierung fuer nicht gecheckte Services).

        Runde 13 (Bugfix Dropdown-NoData): Der Payload (`no_data_variants`)
        ist seit dem Reader-Hash-Filter bereits VARIANTEN-GENAU - er enthaelt
        nur noch die im ServicePicker gecheckten Varianten. Die ausgewaehlte
        No-Data-Variante des aktuellen Feld-Services ist damit EINDEUTIG
        bestimmt (hoechstens eine Variante pro Service uebrig). Der alte
        'erste Variante des Services'-Fallback ist ersatzlos entfernt: Er
        zeigte bei aktiver Varianten-Einschraenkung faelschlich die ERSTE
        Variante (V1), obwohl eine andere (V2) gecheckt und V1 gar nicht
        aktiv war - die Runde-12b-Einschraenkung (kein Fallback bei nicht
        leerem instance_hashes) war unvollstaendig, weil `instance_hashes`
        fuer Set-Instanz-Varianten bis Runde 13 leer blieb.

        Runde 13c (Bug 1-Absicherung): Falls ein Payload aus einem Alt-/
        Kompatibilitaetspfad doch mehrere No-Data-Varianten desselben
        Services enthaelt, gewinnt DEFENSIV die im ServicePicker gecheckte
        Variante (instance_hash in `instance_hashes`) statt der ersten
        Liste. Erst ohne Hash-Match faellt die Auswahl auf den ersten
        Service-Treffer zurueck (hash-lose Variante/kein Filter).
        """
        if not variants:
            return None
        if self._view_model is None:
            return None
        p = self._view_model.params
        data = self._combo_field.currentData()
        sid = None
        if isinstance(data, str) and "|" in data:
            sid = data.split("|", 1)[0].strip().lower()
        if not sid:
            return None
        # Punkt 4: Nur Services im aktiven feature_ids-Filter (leer = alle).
        active_ids = {str(f).strip().lower()
                      for f in (p.get("feature_ids") or [])}
        if active_ids and sid not in active_ids:
            return None
        # Runde 13: Der Payload ist bereits variantengefiltert (Reader-
        # Hash-Filter auf active_hashes). Die No-Data-Variante des aktuellen
        # Feld-Services im Payload IST die ausgewaehlte - kein Fallback auf
        # die 'erste Variante' mehr (die gecheckte Variante gewinnt, weil
        # nur sie im Payload steht).
        #
        # Runde 13c (Bug 1-Absicherung): Bei mehreren No-Data-Varianten
        # desselben Services gewinnt DEFENSIV die im ServicePicker gecheckte
        # Variante (instance_hash in active_hashes) statt der ersten Liste
        # - falls der Payload aus einem Alt-/Kompatibilitaetspfad doch
        # mehrere Varianten enthaelt. Erst wenn kein Hash-Match vorliegt
        # (hash-lose Variante/kein Filter), faellt die Auswahl auf den
        # ersten Service-Treffer zurueck.
        p_hashes = {str(h).strip().lower()
                    for h in (p.get("instance_hashes") or [])}
        if p_hashes:
            for v in variants:
                if (str(v.get("plugin_id") or "").strip().lower() == sid
                        and str(v.get("instance_hash") or "").strip().lower()
                        in p_hashes):
                    return v
        for v in variants:
            if str(v.get("plugin_id") or "").strip().lower() == sid:
                return v
        return None

    def _on_feature_ids_changed(self) -> None:
        """Synchrones Neu-Ableiten des Feld-Dropdowns bei Check/Uncheck.

        Runde 8 (Bugfix 4): `set_feature_ids()` emittiert
        feature_ids_changed, sobald der ServicePicker-Haken geaendert wird -
        Items/Haken/Current werden SOFORT aus den gecachten Feld-Metadaten
        und den aktuellen feature_ids neu abgeleitet (Single Source of
        Truth = Picker; kein Debounce/Query-Round-Trip noetig).
        """
        if self._syncing or self._view_model is None:
            return
        self._syncing = True
        try:
            self._rebuild_field_dropdown(self._field_keys,
                                         self._field_sources)
        finally:
            self._syncing = False

    def _sync_combos_from_payload(self, data: Dict[str, Any]) -> None:
        """Synchronisiert die Combos mit dem tatsaechlichen Payload."""
        if self._view_model is None:
            return
        vm = self._view_model
        metrics = [str(m) for m in (data.get("metrics") or [])]
        keys = [m for m in metrics if m not in ("count", "confluence_count")]
        # 20.02.01 (User-Meldung 3b): Key -> Services, die ihn liefern
        # (Repository `field_sources`); Anzeige '{Service} / {Key}'.
        field_sources = data.get("field_sources") or {}
        # Runde 8 (Bugfix 3): Stale-Payload-Guard. Der Worker spiegelt die
        # Generation der Query-Params ins Ergebnis-Dict - Queries, die VOR
        # dem letzten restore_workspace()/_apply_profile() gestartet wurden,
        # tragen eine aeltere Generation. Deren Feld-Metadaten duerfen den
        # synchron restaurierten Zustand NICHT ueberschreiben (die x/y/agg-
        # Combos werden trotzdem mit VM-Prioritaet bestaetigt).
        payload_gen = data.get("restore_generation")
        stale = (payload_gen is not None
                 and str(payload_gen) != str(
                     getattr(vm, "restore_generation", 0)))
        # Runde 11 (Architektur, A5): Die x/y/agg-Combos werden NICHT mehr
        # aus dem Payload synchronisiert - die Controls sind Single Source
        # of Truth (Restore-/User-Auswahl gewinnt, kein Ueberschreiben).
        self._syncing = True
        try:
            if not stale:
                # Feld-Metadaten uebernehmen + 'Feld'-Dropdown synchron neu
                # ableiten (Items/Haken/Current; Runde 8, Bug 3/4). Bei
                # stale Payloads bleibt der Zustand aus _sync_from_params
                # unveraendert.
                self._rebuild_field_dropdown(
                    keys, field_sources,
                    payload_agg=str(data.get("agg") or ""),
                    payload_field=str(data.get("field") or ""))
            # Runde 11 (Bug 4, B4-1): '(No Data)'-Hinweise rendert
            # _rebuild_field_dropdown() zentral aus dem Payload-Cache
            # (self._no_data_variants aus QUERY_FEATURES).
        finally:
            self._syncing = False
        self._update_controls()

    def _render_overlay(self, data: Dict[str, Any]) -> None:
        """Zeichnet OHLCV-Bars ueber die Heatmap (selbes Canvas, Bugfix 1).

        21.01 (Bugfix 5, 11.08.2026): Das Overlay nutzt die Bars IM
        HEATMAP-TIMEFRAME (OHLCV-Snapshot, adaptiv fuer alle TFs) statt der
        festen Tages-Aggregation. Die Candle-Breite folgt dem Bar-Intervall
        (_bar_interval_seconds). Bars werden ueber ihren Wanduhr-Tag
        (Mitternachts-Epoch) dem Heatmap-Zeitraum zugeordnet und an ihrer
        ECHTEN Bar-Zeit positioniert (H1-Kerzen liegen damit korrekt in der
        jeweiligen Tageszelle).

        Die Candles liegen in der Preis-ViewBox. 'Datum' liegt auf der
        X-Achse (Y=date ist keine offizielle Overlay-Ansicht mehr, der
        horizontale Zweig bleibt defensiv erhalten). Die Spalten der
        date-Achse sind Wanduhr-Mitternachts-Epochs. Alpha 0.3-0.5 (E9).
        """
        self._clear_overlay()
        bars = data.get("bars") or []
        x_dim = str(self._combo_x.currentData() or "date")
        y_dim = str(self._combo_y.currentData() or "hour")
        # 10.08.2026 (Bugfix Runde 7, Bug 1): 'Datum' darf auf X oder Y
        # liegen - die Candles werden in der Orientierung der Date-Achse
        # gezeichnet (vertikal bei X=date, horizontal bei Y=date).
        date_on_x = x_dim == "date"
        date_axis = self._x_axis if date_on_x else self._y_axis
        if not bars or not date_axis:
            return
        # Spalten-Index je Wanduhr-Tag (Mitternachts-Epoch) - dient als
        # Filter, dass die Bar im Heatmap-Zeitraum liegt. OHLCV-Bars tragen
        # ihre ECHTE Bar-Zeit (z. B. H1 14:00) - der Wanduhr-Tag wird per
        # UTC-Division auf Mitternacht zurueckgefuehrt (Bugfix 5).
        epoch_to_col = {int(round(e)): i for i, e in enumerate(date_axis)}
        candles: List[tuple] = []
        for b in bars:
            t = b.get("time")
            if t is None:
                continue
            try:
                t = int(t)
            except (TypeError, ValueError):
                continue
            day = int(t // _DAY_SECONDS) * _DAY_SECONDS
            col = epoch_to_col.get(day)
            if col is None:
                continue  # Tag nicht in der Heatmap (Ausschnitt)
            try:
                o = float(b["open"])
                c = float(b["close"])
                h = float(b["high"])
                l = float(b["low"])
            except (TypeError, ValueError, KeyError):
                continue
            if not (np.isfinite(o) and np.isfinite(c)
                    and np.isfinite(h) and np.isfinite(l)):
                continue
            candles.append((t, o, h, l, c))
        if not candles:
            return
        pmin = min(c[3] for c in candles)
        pmax = max(c[2] for c in candles)
        if pmin == pmax:
            pmin -= 1.0
            pmax += 1.0
        pad = (pmax - pmin) * 0.05
        if date_on_x:
            self._price_vb.setYRange(pmin - pad, pmax + pad, padding=0)
        else:
            self._price_vb.setXRange(pmin - pad, pmax + pad, padding=0)
        # 21.01 (Bugfix 5): Candle-Breite/Hoehe folgt dem Bar-Intervall
        # des Heatmap-TFs (z. B. 3600s bei H1, 86400s bei D1) statt fest
        # einem Tag. x = echte Bar-Epoch (X=date) bzw. y = Bar-Epoch
        # (Y=date, defensiver Zweig).
        # 21.01 (Bugfix-Runde 3, Bug 1, 11.08.2026): NumPy-vektorisiertes
        # Rendering - statt 2 Qt-Items JE BAR nur noch 3 batched Items
        # (Wick + Bull-Koerper + Bear-Koerper) fuer ALLE Bars (vorher bei
        # 5000 Bars = 10.000 Einzel-Items -> Pan/Zoom rueckelte). Die
        # Daten werden als numpy-Arrays an BarGraphItem uebergeben.
        bar_sec = self._bar_interval_seconds()
        times = np.asarray([c[0] for c in candles], dtype=np.float64)
        opens = np.asarray([c[1] for c in candles], dtype=np.float64)
        highs = np.asarray([c[2] for c in candles], dtype=np.float64)
        lows = np.asarray([c[3] for c in candles], dtype=np.float64)
        closes = np.asarray([c[4] for c in candles], dtype=np.float64)
        bull = closes >= opens
        bear = ~bull
        wick_color = pg.mkColor(128, 128, 128, 140)
        bull_color = pg.mkColor(0, 180, 0, 140)
        bear_color = pg.mkColor(220, 30, 30, 140)
        if date_on_x:
            # Vertikale Candles (Preis auf der rechten Achse).
            wick = pg.BarGraphItem(
                x=times, width=bar_sec * 0.12,
                y0=lows, height=np.maximum(highs - lows, 1e-9),
                brush=wick_color, pen=wick_color)
            body_bull = pg.BarGraphItem(
                x=times[bull], width=bar_sec * 0.7,
                y0=opens[bull],
                height=np.maximum(closes[bull] - opens[bull], 1e-9),
                brush=bull_color, pen=bull_color)
            body_bear = pg.BarGraphItem(
                x=times[bear], width=bar_sec * 0.7,
                y0=closes[bear],
                height=np.maximum(opens[bear] - closes[bear], 1e-9),
                brush=bear_color, pen=bear_color)
        else:
            # Horizontale Candles (Preis auf der unteren Achse, defensiv).
            wick = pg.BarGraphItem(
                x0=lows, width=np.maximum(highs - lows, 1e-9),
                y=times, height=bar_sec * 0.12,
                brush=wick_color, pen=wick_color)
            body_bull = pg.BarGraphItem(
                x0=opens[bull], width=np.maximum(
                    closes[bull] - opens[bull], 1e-9),
                y=times[bull], height=bar_sec * 0.7,
                brush=bull_color, pen=bull_color)
            body_bear = pg.BarGraphItem(
                x0=closes[bear], width=np.maximum(
                    opens[bear] - closes[bear], 1e-9),
                y=times[bear], height=bar_sec * 0.7,
                brush=bear_color, pen=bear_color)
        self._candle_items = [wick, body_bull, body_bear]
        for _item in self._candle_items:
            self._price_vb.addItem(_item)
        self._price_vb.setVisible(True)
        if date_on_x:
            self._plot_hm.getAxis("right").setVisible(True)
            self._price_axis_bottom.setVisible(False)
        else:
            self._price_axis_bottom.setVisible(True)
            self._plot_hm.getAxis("right").setVisible(False)
        self._update_price_view()

    def _clear_overlay(self) -> None:
        """Entfernt alle Kerzen-Items und versteckt die Preis-Achse."""
        for item in self._candle_items:
            try:
                self._price_vb.removeItem(item)
            except Exception:
                pass
        self._candle_items = []
        self._price_vb.setVisible(False)
        self._plot_hm.getAxis("right").setVisible(False)
        self._price_axis_bottom.setVisible(False)

    # ------------------------------------------------------------------
    # 21.01 Bugfix-Runde 3 (Entscheidung 2a): Senkrechte Teiler je
    # Dateneinheit (Bar-Intervall des Timeframes) an der X-Achse (date)
    # ------------------------------------------------------------------
    def _update_grid_lines(self) -> None:
        """Setzt die senkrechten Teiler je Dateneinheit (Bugfix 2a).

        Nur bei X=date. Der Abstand ist das Bar-Intervall des Heatmap-TFs
        (_bar_interval_seconds, z. B. H1 -> jede volle Stunde, D1 -> jede
        Tagesgrenze). Die Positionen sind daten-konsistent (Epochs sind
        Vielfache von 60s; Mitternachts-Epochs Vielfache von 86400s). Ein
        Dichte-Cap (max ~2000 Linien) verhindert ueberladene Raster bei
        sehr grossen Zeitraeumen (dann wird der Abstand skaliert).
        """
        x_dim = str(self._combo_x.currentData() or "date")
        if x_dim != "date" or not self._x_axis:
            self._grid_lines.setData([], [])
            self._grid_lines.setVisible(False)
            return
        bar_sec = self._bar_interval_seconds()
        lo = float(self._x_axis[0])
        hi = float(self._x_axis[-1]) + _DAY_SECONDS
        start = int(math.floor(lo / bar_sec)) * bar_sec
        step = 1
        max_lines = 2000
        while int((hi - lo) / (bar_sec * step)) > max_lines:
            step += 1
        positions = np.arange(start, hi, bar_sec * step)
        if positions.size == 0:
            self._grid_lines.setData([], [])
            self._grid_lines.setVisible(False)
            return
        y0, y1 = self._y_min, self._y_max
        n = positions.size
        xs = np.empty(n * 2, dtype=np.float64)
        xs[0::2] = positions
        xs[1::2] = positions
        ys = np.empty(n * 2, dtype=np.float64)
        ys[0::2] = y0
        ys[1::2] = y1
        self._grid_lines.setData(x=xs, y=ys, connect="pairs")
        self._grid_lines.setVisible(True)

    # ------------------------------------------------------------------
    # 21.01 Bugfix 5: Adaptives Overlay (OHLCV im Heatmap-Timeframe)
    # ------------------------------------------------------------------
    def _bar_interval_seconds(self) -> float:
        """Bar-Intervall des Heatmap-Timeframes in Sekunden (Bugfix 5).

        Liest `params["timeframe"]` des ViewModels (z. B. 'H1' -> 3600) und
        liefert einen Fallback (3600s), falls der TF unbekannt/leer ist.
        """
        tf = ""
        if self._view_model is not None:
            tf = str(self._view_model.params.get("timeframe") or "")
        return float(_TF_SECONDS.get(tf.strip().upper(), 3600.0))

    # ------------------------------------------------------------------
    # 21.01 Bugfix 3: Fadenkreuz + Zellwert-Info
    # ------------------------------------------------------------------
    def _on_mouse_moved(self, pos) -> None:
        """Bewegt das Fadenkreuz ueber die Heatmap (Bugfix 3).

        `pos` ist ein QPointF in SCENE-Koordinaten (pyqtgraph
        `sigMouseMoved`). Nur innerhalb des Plot-Viewports wird das Kreuz
        gezeigt; sonst versteckt (Maus ueber den Steuerleisten).
        """
        if self._view_model is None:
            return
        vb = self._plot_hm.plotItem.vb
        rect = vb.sceneBoundingRect()
        if rect is None or not rect.contains(pos):
            self._cross_x.setVisible(False)
            self._cross_y.setVisible(False)
            return
        try:
            p = vb.mapSceneToView(pos)
        except Exception:
            return
        self._cross_x.setPos(p.x())
        self._cross_y.setPos(p.y())
        self._cross_x.setVisible(True)
        self._cross_y.setVisible(True)
        self._update_cell_info(p.x(), p.y())

    def _update_cell_info(self, x: float, y: float) -> None:
        """Zeigt genaue Datum/Zeit + Matrix-Wert am Fadenkreuz (Bug 4)."""
        if self._n_rows <= 0 or self._n_cols <= 0:
            return
        img = getattr(self._image, "image", None)
        if img is None or img.size == 0:
            return
        sx = (self._x_max - self._x_min) or 1.0
        sy = (self._y_max - self._y_min) or 1.0
        col = int((x - self._x_min) / sx * self._n_cols)
        row = int((y - self._y_min) / sy * self._n_rows)
        if not (0 <= col < self._n_cols and 0 <= row < self._n_rows):
            return
        try:
            v = float(img[row, col])
        except (TypeError, ValueError, IndexError):
            return
        # 21.01 (Bugfix-Runde 3, Bug 4): Genaue Datum/Zeit am Fadenkreuz
        # (wie chart_win). Bei X=date wird die Cursor-Position als
        # Wanduhr-Zeit formatiert; der Zellwert folgt danach.
        time_txt = ""
        if str(self._combo_x.currentData() or "date") == "date":
            try:
                dt = datetime.fromtimestamp(float(x), tz=dt_timezone.utc)
                days = ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So.")
                time_txt = (f"{days[dt.weekday()]} {dt.day:02d}."
                            f"{dt.month:02d}.{dt.year % 100:02d} "
                            f"{dt.hour:02d}:{dt.minute:02d}  ·  ")
            except (TypeError, ValueError, OverflowError):
                time_txt = ""
        self._label_info.setText(f"{time_txt}Zelle({row},{col}) = {v:g}")

    # ------------------------------------------------------------------
    # 21.01 Bugfix 2: Diskrete Schwellwert-Legende (oben rechts)
    # ------------------------------------------------------------------
    def _update_legend(self) -> None:
        """Befuellt die Schwellwert-Legende je Colormap/Levels.

        Confluence (diskret): je ganzzahligem Treffer-Wert 0..5 ein Farbfeld
        mit der AKTUELL daten-gebundenen Farbe (Levels 0..vmax), '5+' fuer
        alles darueber. Wert-Aggregationen (viridis, kontinuierlich): 5
        Stichproben min..max mit den tatsaechlichen Werten als Label.
        """
        cmap = (self._cmap_confluence
                if self._colormap_mode == "confluence"
                else self._cmap_viridis)
        levels = getattr(self._image, "levels", None)
        if levels is None or len(levels) != 2:
            self._legend.hide()
            return
        vmin = float(levels[0])
        vmax = float(levels[1])
        if vmax <= vmin:
            vmax = vmin + 1.0
        self._legend.clear()
        if self._colormap_mode == "confluence":
            max_count = max(1, int(math.ceil(vmax)))
            for c in range(0, min(max_count, 5) + 1):
                frac = (c - vmin) / (vmax - vmin)
                frac = max(0.0, min(1.0, frac))
                color = cmap.map(frac, mode="qcolor")
                label = str(c) if c < 5 else "5+"
                self._add_legend_swatch(color, label)
        else:
            for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                val = vmin + frac * (vmax - vmin)
                color = cmap.map(frac, mode="qcolor")
                self._add_legend_swatch(color, f"{val:.2g}")
        self._legend.show()

    def _add_legend_swatch(self, color, label: str) -> None:
        """Fuegt ein Farbfeld + Label zur Legende hinzu (Bugfix 2)."""
        item = pg.PlotDataItem(
            [0], [0], pen=None,
            symbol="s", symbolSize=10,
            symbolBrush=pg.mkColor(color), symbolPen=pg.mkPen(None))
        self._legend.addItem(item, str(label))
