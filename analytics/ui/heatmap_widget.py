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
from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import (
    QUERY_HEATMAP_GENERIC,
    QUERY_DAILY_OHLC,
)
from analytics.engine.feature_store_reader import (
    DOW_LABELS,
    DOW_WEEK_LABELS,
    HEATMAP_AGGREGATIONS,
    HEATMAP_DIMENSIONS,
    HOURS_PER_DAY,
)
from analytics.ui.common import CheckableComboBox

# E7: Konfluenz-Farbskala (0 = weiss/transparent, 1-2 = gelb/cyan,
# 3-4 = orange, 5+ = dunkelrot) – Positionen 0..1 (Levels 0..5).
_CONFLUENCE_COLORS = [
    "#ffffff", "#ffff00", "#00ffff", "#ff8c00", "#ff6600", "#8b0000",
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

# 20.02.01 (User-Meldung 2): LWC-v5-adaptierte Datums-Skala.
# Zielabstand zwischen zwei Tick-Labels in Pixel (Lightweight Charts:
# 5*(fontSize+4)/8 * (tickMarkMaxCharacterLength || 8) mit fontSize 12 =>
# 5*16/8*8 = 80 px). Die Tick-Auswahl haelt diesen Abstand ein: Zoom-In
# => feinere Variante, Zoom-Out => groebere Variante (keine Ueberlappung,
# keine Riesensprünge). Weight-Hierarchie wie LWC v5:
#   70 = Jahreswechsel (Label: '2026'), 60 = Monatswechsel ('Feb 26'),
#   55 = Wochenanfang Mo (ISO-Woche '08.25'), 50 = Tageswechsel
#   ('Mo. 07.08.25'), 30 = Stundenmarke ('14:00'), 20 = Minutenmarke ('14:23').
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
      - date:  5 Format-Stufen je Zoom (Jahr/Monat/Tag/Stunde/Minute,
               20.02.01 E1)
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
        Skala geclampt. `date`/kategorial bleiben unbegrenzt (daten- bzw.
        listenbasiert).
        """
        lo = float(minVal)
        hi = float(maxVal)
        if self._dim == "hour":
            lo = max(lo, 0.0)
            hi = min(hi, float(HOURS_PER_DAY))
        elif self._dim == "dow":
            lo = max(lo, 1.0)
            hi = min(hi, 1.0 + float(len(DOW_WEEK_LABELS)))
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
            # 20.02.01 (User-Meldung 2): Per-Tick-Format nach der
            # LWC-v5-Weight-Hierarchie (nicht mehr nach Spacing):
            #   - Jahreswechsel (1.1.)  -> '2026'      (Weight 70)
            #   - Monatswechsel (1. des Monats) -> 'Feb 26' (Weight 60)
            #   - Wochenanfang Mo       -> '08.25'     (ISO-Woche, Weight 55)
            #   - sonstiger Tag         -> 'Mo. 07.08.25' (Weight 50)
            #   - Stundenmarke          -> '14:00'     (Weight 30)
            #   - Minutenmarke          -> '14:23'     (Weight 20)
            # Wanduhr-Garantie via UTC-Darstellung der (Wanduhr-encoded)
            # Epoch (Invariante 7, KEIN Berlin-Offset). Monats-/Wochen-
            # marken eines groben Zooms tragen ihre eigene Beschriftung
            # (Jahreszahl/Feb/Mrz/...), feine Marken die Uhrzeit.
            dt = datetime.fromtimestamp(v, tz=dt_timezone.utc)
            if dt.hour != 0 or dt.minute != 0 or dt.second != 0:
                if dt.minute == 0 and dt.second == 0:
                    return f"{dt.hour:02d}:00"   # Stundenmarke
                return f"{dt.hour:02d}:{dt.minute:02d}"  # Minutenmarke
            weekday = DOW_LABELS[(dt.weekday() + 1) % 7]
            if dt.month == 1 and dt.day == 1:
                return str(dt.year)               # Jahreswechsel
            if dt.day == 1:
                return f"{_MONTHS_SHORT[dt.month - 1]} {dt.year % 100:02d}"
            if dt.weekday() == 0:
                iso = dt.isocalendar()
                return f"{iso[1]:02d}.{dt.year % 100:02d}"  # ISO-Woche
            return f"{weekday}. {dt.day:02d}.{dt.month:02d}.{dt.year % 100:02d}"
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
        return str(int(round(v)))


class HeatmapWidget(QWidget):
    """Generische 2D-Heatmap mit Confluence-Matrix, Zoom & Candle-Overlay."""

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
        self._combo_field.setMaximumWidth(460)
        # Popup-Dropdown an den laengsten Eintrag anpassen (vollstaendige
        # '{Service} / {Key}'-Texte sichtbar statt Ellipsis).
        self._combo_field.setSizeAdjustPolicy(QComboBox.AdjustToContents)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("X-Achse:"))
        ctrl.addWidget(self._combo_x)
        ctrl.addWidget(QLabel("Y-Achse:"))
        ctrl.addWidget(self._combo_y)
        ctrl.addWidget(QLabel("Aggregation:"))
        ctrl.addWidget(self._combo_agg)
        ctrl.addWidget(QLabel("Feld:"))
        ctrl.addWidget(self._combo_field)
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
        ctrl2.addWidget(self._label_info)
        ctrl2.addStretch(1)

        # --- Plot: Heatmap + Kerzen-Overlay im SELBEN Canvas (Bugfix 1) ---
        self._plot_hm = pg.PlotWidget()
        self._plot_hm.setBackground("w")
        # Dynamische Achsen (Bugfix 5+6): Ticks je Zoom-Level.
        self._axis_x = _HeatmapAxis("bottom")
        self._axis_y = _HeatmapAxis("left")
        self._plot_hm.plotItem.setAxisItems(
            {"bottom": self._axis_x, "left": self._axis_y})
        self._image = pg.ImageItem()
        self._plot_hm.addItem(self._image)
        self._cmap_viridis = pg.colormap.get(_VIRIDIS)
        self._cmap_confluence = pg.ColorMap(
            pos=_CONFLUENCE_POS, color=_CONFLUENCE_COLORS)
        self._image.setColorMap(self._cmap_viridis)
        self._colorbar = pg.ColorBarItem(
            colorMap=self._cmap_viridis, values=(0.0, 1.0))
        self._colorbar.setImageItem(self._image)

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
        # 20.04-Timing-Fix (D): Nach restore_workspace()/_apply_profile()
        # emittiert der ViewModel `params_restored` – die Combos werden dann
        # explizit aus den restaurierten Params synchronisiert (sonst kann
        # der erste Daten-Payload bzw. _apply_config die restaurierten
        # Aggregations-/Feld-Werte ueberschreiben). Defensiv per hasattr
        # (Test-Mocks ohne Signal). _sync_from_params() blockt Signale und
        # stoesst keinen Query an (kein Loop).
        if hasattr(view_model, "params_restored"):
            view_model.params_restored.connect(self._sync_from_params)
        self._sync_from_params()

    def is_candle_projection_enabled(self) -> bool:
        """True, wenn das Kerzen-Overlay aktiviert ist (E9)."""
        return self._chk_candle.isChecked()

    def request_data(self) -> None:
        """Fordert generische Heatmap (+ Tages-Ohlc bei Overlay) an."""
        if self._view_model is None:
            return
        self._view_model.request_heatmap_generic()
        if self._chk_candle.isChecked():
            self._view_model.request_daily_ohlc()

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
            field = str(p.get("heatmap_field") or "")
            if field:
                # 20.03.02: Index ueber den Key-Teil des userData suchen
                # ('{service_id}|{key}'); unbekanntes Feld als checkbares
                # Item anlegen (Restore-Fallback).
                fidx = self._find_field_index(field)
                if fidx < 0:
                    self._combo_field.add_checkable_item(field, field,
                                                         checked=True)
                    fidx = self._combo_field.count() - 1
                self._combo_field.blockSignals(True)
                self._combo_field.setCurrentIndex(fidx)
                self._combo_field.blockSignals(False)
            self._chk_candle.setChecked(bool(
                p.get("candle_projection_enabled")))
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
        # 10.08.2026 (Bugfix Runde 7, Bug 1): 'Datum' darf auf der X- ODER
        # Y-Achse liegen - X=date zeichnet vertikale Candles (Preis rechts),
        # Y=date horizontale Candles (Preis unten).
        date_on_x = x_dim == "date"
        can_overlay = (x_dim == "date" or y_dim == "date")
        self._chk_candle.setEnabled(can_overlay)
        if can_overlay:
            self._chk_candle.setToolTip(
                "Tages-Ohlc ueber der Heatmap (gleicher Canvas), "
                "Datum auf X- oder Y-Achse (Bugfix 1).")
        else:
            self._chk_candle.setToolTip(
                "Kerzen-Overlay nur mit 'Datum' auf der X- oder Y-Achse "
                "verfuegbar.")
        # 10.08.2026 (Bugfix Runde 7, Bug 1): Der Overlay-Link folgt der
        # DATE-Achse - X=date koppelt die Preis-VB an die X-Achse, Y=date
        # an die Y-Achse. Ohne Overlay werden beide Links entfernt.
        link = can_overlay and self._chk_candle.isChecked()
        linked_x = self._price_vb.linkedView(pg.ViewBox.XAxis)
        linked_y = self._price_vb.linkedView(pg.ViewBox.YAxis)
        if link and date_on_x and linked_x is None:
            self._price_vb.setXLink(self._plot_hm.plotItem.vb)
        if link and not date_on_x and linked_y is None:
            self._price_vb.setYLink(self._plot_hm.plotItem.vb)
        if link and date_on_x and linked_y is not None:
            self._price_vb.setYLink(None)
        if link and not date_on_x and linked_x is not None:
            self._price_vb.setXLink(None)
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
        # Overlay nur bei X=date (E9) – sonst ausschalten.
        if (self._combo_x.currentData() != "date"
                and self._combo_y.currentData() != "date"
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
            self._view_model.request_daily_ohlc()
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
            self._render_generic(data)
        elif kind == QUERY_DAILY_OHLC:
            self._render_overlay(data)

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
            self._image.setImage(matrix, levels=_CONFLUENCE_LEVELS)
            self._colorbar.setLevels(_CONFLUENCE_LEVELS)
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

        # ImageItem exakt auf die natuerlichen Koordinaten mappen (Bugfix 3):
        # date-Spalten = Tage (zentriert auf Mitternacht), hour/dow =
        # ganzzahlige Werte (feste Skalen, E3/E5), kategorial = Indizes.
        # Nichts wird ueber die Tagesgrenze hinaus gezeichnet (Punkt 3).
        self._x_min, self._x_max = self._axis_bounds(self._x_axis, x_dim)
        self._y_min, self._y_max = self._axis_bounds(self._y_axis, y_dim)
        self._image.setRect(QRectF(
            self._x_min, self._y_min,
            self._x_max - self._x_min, self._y_max - self._y_min))

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

        # Bugfix 1/2: Bei aktivem Overlay den Tages-Ohlc-Snapshot laden.
        if self._chk_candle.isChecked() and self._view_model is not None:
            self._view_model.request_daily_ohlc()

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
                return f"{name} / {str(key)}"
        return str(key)

    def _sync_combos_from_payload(self, data: Dict[str, Any]) -> None:
        """Synchronisiert die Combos mit dem tatsaechlichen Payload."""
        if self._view_model is None:
            return
        metrics = [str(m) for m in (data.get("metrics") or [])]
        keys = [m for m in metrics if m not in ("count", "confluence_count")]
        # 20.02.01 (User-Meldung 3b): Key -> Services, die ihn liefern
        # (Repository `field_sources`); Anzeige '{Service} / {Key}'.
        field_sources = data.get("field_sources") or {}
        # 20.03.03 (Q2): Quellen je Key fuer die ALL-Expansion merken.
        self._field_sources = {
            str(k): [str(s) for s in (v or [])]
            for k, v in field_sources.items()
        }
        # 10.08.2026 (Bugfix Runde 7, Bug 3): Die restaurierten
        # VM-Params (Workspace/Profil) GEWINNEN gegen einen Stale-Payload
        # (Query lief VOR dem Restore mit Default-Params). Der Daten-Payload
        # bestaetigt nur noch die tatsaechlich verwendeten Werte.
        agg = (str(self._view_model.params.get("heatmap_agg") or "")
               or str(data.get("agg") or "")
               or str(self._combo_agg.currentData() or ""))
        # 20.03.02: userData = '{service_id}|{key}' – fuer den Vergleich mit
        # den Payload-Keys nur den Key-Teil verwenden.
        prev_field = (str(self._view_model.params.get("heatmap_field") or "")
                      or str(data.get("field") or "")
                      or self._field_key(self._combo_field.currentData()))
        self._syncing = True
        try:
            self._combo_field.blockSignals(True)
            self._combo_field.clear()
            # 20.03.03 (Q1/Q4/Q5): 2-stufige Struktur – gemeinsame Keys
            # (2+ Quellen) als Sammel-Eintrag 'Alle Services / {Key}' an der
            # Spitze (initial angehakt), dann je Quelle ein EINDEUTIGER
            # Eintrag '{Service-Name} / {Key}'. Sektions-Header sind
            # deaktivierte Trennzeilen. Der rohe Key entfaellt bei bekannten
            # Quellen (100 % Eindeutigkeit).
            shared = sorted(k for k in keys
                            if len(self._field_sources.get(k) or []) >= 2)
            # 10.08.2026 (Bugfix Runde 7, Bug 4/5): Die initialen CheckStates
            # folgen dem aktiven feature_ids-Filter (ServicePicker) - nur
            # Services aus dem Filter erscheinen angehakt. Das 'Feld'-
            # Dropdown ist damit ein read-only Spiegel der Datenquellen-
            # Auswahl (Single Source of Truth = Picker; das Write-Back der
            # Feld-Haken wurde entfernt, siehe __init__).
            active_ids = {str(f).strip().lower() for f in
                          (self._view_model.params.get("feature_ids") or [])}
            no_filter = not active_ids
            if shared:
                self._combo_field.add_header_item(
                    "🌐 Gleiche Parameter (alle aktiven Services):")
                for k in shared:
                    src = self._field_sources.get(k) or []
                    self._combo_field.add_checkable_item(
                        f"Alle Services / {k}", f"ALL|{k}",
                        checked=no_filter or all(
                            s.lower() in active_ids for s in src))
            if keys:
                self._combo_field.add_header_item("🔌 Einzelservices:")
            for k in sorted(keys):
                sids = self._field_sources.get(k) or []
                if len(sids) == 1:
                    # Eindeutiger Service: Einzel-Eintrag nur angehakt, wenn
                    # der Service im aktiven Filter liegt (oder kein Filter).
                    self._combo_field.add_checkable_item(
                        self._field_label(k, sids), f"{sids[0]}|{k}",
                        checked=no_filter or sids[0].lower() in active_ids)
                elif not sids:
                    # Legacy ohne field_sources (roher Key, defensiv).
                    self._combo_field.add_checkable_item(k, k, checked=True)
                else:
                    # Shared Key: je Quelle ein Einzel-Eintrag, initial NICHT
                    # angehakt (der Sammel-Eintrag deckt die Quellen ab, Q5).
                    all_active = all(s.lower() in active_ids
                                       for s in sids)
                    for sid in sids:
                        self._combo_field.add_checkable_item(
                            self._field_label(k, [sid]), f"{sid}|{k}",
                            checked=no_filter
                            or (sid.lower() in active_ids
                                and not all_active))
            if prev_field in keys:
                self._combo_field.setCurrentIndex(
                    self._find_field_index(prev_field))
            elif keys:
                # 20.03.03 (Q4): Index 0 kann ein Header sein -> ersten
                # auswaehlbaren Eintrag waehlen.
                self._combo_field.setCurrentIndex(self._first_field_index())
            # 20.04-Q8-Fix (User-Bugreport 09.08.2026, Option 'No Data'):
            # Neue Plugin-Varianten (Clones/Presets) ohne feature_store-Daten
            # sofort als deaktivierte Hinweis-Eintraege zeigen ('(No Data)'),
            # damit der Anwender nach dem Duplizieren ein sichtbares Ergebnis
            # hat, bevor der erste Scan/LiveRun Daten liefert.
            no_data = []
            try:
                no_data = self._view_model.resolve_no_data_variants(
                    str(data.get("symbol") or ""),
                    str(data.get("timeframe") or ""))
            except Exception:
                no_data = []
            if no_data:
                self._combo_field.add_header_item(
                    "🕓 Noch ohne Daten (erster Scan ausstehend):")
                for nd in no_data:
                    self._combo_field.add_disabled_item(
                        f"{nd.get('display_name') or nd.get('plugin_id')} "
                        f"({nd.get('preset_name')}) – (No Data)")
            self._combo_field.blockSignals(False)
            self._set_combo_data(
                self._combo_x, str(data.get("x_dim") or "date"))
            self._set_combo_data(
                self._combo_y, str(data.get("y_dim") or "hour"))
            self._set_combo_data(self._combo_agg, str(agg or "count"))
        finally:
            self._syncing = False
        self._update_controls()
        # E6: Wert-Aggregation mit noch leerem Feld -> ersten Key uebernehmen
        # und Konfiguration nachreichen (einmaliger Query-Loop). 20.03.03:
        # Vergleich ueber den KEY-Teil (params haelt den reinen Key, das
        # userData traegt '{service_id}|{key}' bzw. 'ALL|{key}').
        vm_field = str(self._view_model.params.get("heatmap_field") or "")
        if (agg in _VALUE_AGGS and self._combo_field.currentData()
                and vm_field != self._field_key(
                    self._combo_field.currentData())):
            # 10.08.2026 (Bugfix Runde 7, Bug 3): Ein restaurierter
            # heatmap_field (Workspace/Profil) darf NICHT durch einen
            # Payload-Fallback ueberschrieben werden. Nur wenn das VM-Feld
            # leer oder im aktuellen Datensatz nicht verfuegbar ist, wird
            # der erste verfuegbare Key uebernommen.
            if vm_field and vm_field in keys:
                fidx = self._find_field_index(vm_field)
                if fidx >= 0:
                    self._combo_field.setCurrentIndex(fidx)
            else:
                self._apply_config()

    def _render_overlay(self, data: Dict[str, Any]) -> None:
        """Zeichnet Tages-Ohlc ueber die Heatmap (selbes Canvas, Bugfix 1).

        Die Candles liegen in der Preis-ViewBox. 10.08.2026 (Bugfix Runde 7,
        Bug 1): 'Datum' darf auf der X- ODER Y-Achse liegen - X=date zeichnet
        vertikale Candles (Preis auf der rechten Achse), Y=date horizontale
        Candles (Preis auf der unteren Preis-Achse). Die Spalten der
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
        # Spalten-Index je Wanduhr-Tag (Mitternachts-Epoch).
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
            col = epoch_to_col.get(t)
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
        # Candles: x = Mitternachts-Epoch (X=date) bzw. y = Mitternachts-
        # Epoch (Y=date), Breite/Hoehe in Tages-Sekunden.
        for t, o, h, l, c in candles:
            up = c >= o
            color = pg.mkColor(0, 180, 0, 140) if up \
                else pg.mkColor(220, 30, 30, 140)
            if date_on_x:
                # Vertikale Candles (Preis auf der rechten Achse).
                wick = pg.BarGraphItem(
                    x=[float(t)], width=_DAY_SECONDS * 0.12,
                    y0=l, height=max(h - l, 1e-9), brush=color, pen=color)
                body = pg.BarGraphItem(
                    x=[float(t)], width=_DAY_SECONDS * 0.7,
                    y0=min(o, c),
                    height=max(max(o, c) - min(o, c), 1e-9),
                    brush=color, pen=color)
            else:
                # Horizontale Candles (Preis auf der unteren Achse).
                wick = pg.BarGraphItem(
                    x0=l, width=max(h - l, 1e-9),
                    y0=float(t) - _DAY_SECONDS * 0.06,
                    height=_DAY_SECONDS * 0.12, brush=color, pen=color)
                body = pg.BarGraphItem(
                    x0=min(o, c), width=max(max(o, c) - min(o, c), 1e-9),
                    y0=float(t) - _DAY_SECONDS * 0.35,
                    height=_DAY_SECONDS * 0.7, brush=color, pen=color)
            self._price_vb.addItem(wick)
            self._price_vb.addItem(body)
            self._candle_items.extend((wick, body))
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
