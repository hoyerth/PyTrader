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
from typing import Any, Dict, List, Optional, Set

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
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

from analytics.ui.heatmap_widget_constants import (
    _AGG_LABELS,
    _CONFLUENCE_COLORS,
    _CONFLUENCE_LEVELS,
    _CONFLUENCE_POS,
    _DATE_TARGET_PX,
    _DAY_SECONDS,
    _DIM_LABELS,
    _HALF_DAY,
    _MONTHS_SHORT,
    _MONTH_SECONDS,
    _PRICE_LIKE_KEY_HINTS,
    _TF_SECONDS,
    _VALUE_AGGS,
    _VIRIDIS,
    _YEAR_SECONDS,
)
from analytics.ui.heatmap_widget_axis import _HeatmapAxis
from analytics.ui.heatmap_widget_controls import HeatmapWidgetControlsMixin
from analytics.ui.heatmap_widget_fields import HeatmapWidgetFieldMixin
from analytics.ui.heatmap_widget_zoom import HeatmapWidgetZoomMixin
from analytics.ui.heatmap_widget_data import HeatmapWidgetDataMixin
from analytics.ui.heatmap_widget_overlay import HeatmapWidgetOverlayMixin
from analytics.ui.heatmap_widget_info import HeatmapWidgetInfoMixin


class HeatmapWidget(
    QWidget,
    HeatmapWidgetControlsMixin, HeatmapWidgetFieldMixin,
    HeatmapWidgetZoomMixin, HeatmapWidgetDataMixin,
    HeatmapWidgetOverlayMixin, HeatmapWidgetInfoMixin,
):
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
        # 13.08.2026 (Punkt 1): X-/Y-Achse kompakter (160->110), damit die
        # Zoom-X-/Zoom-Y-Slider in Zeile 1 wieder sichtbar bleiben.
        self._combo_x.setMinimumWidth(110)
        for d in HEATMAP_DIMENSIONS:
            self._combo_x.addItem(_DIM_LABELS.get(d, d), d)
        self._combo_y = QComboBox()
        self._combo_y.setMinimumWidth(110)
        for d in HEATMAP_DIMENSIONS:
            self._combo_y.addItem(_DIM_LABELS.get(d, d), d)
        self._combo_agg = QComboBox()
        for a in HEATMAP_AGGREGATIONS:
            self._combo_agg.addItem(_AGG_LABELS.get(a, a), a)
        # 21.03.20 (Analytics Modus-Filter): Modus-Dropdown fuer
        # Multi-Modus-Services (srv_swing_*/srv_trend_* schreiben
        # `source_mode` top-level in jedes feature_data-Record).
        # Wird aus dem QUERY_FEATURES-Payload befuellt
        # (`source_modes` + `has_source_mode_services`);
        # "[Alle Modi]" (data "all") = kein Filter. Deaktiviert,
        # wenn KEIN aktiver Service source_mode schreibt.
        self._combo_mode_filter = QComboBox()
        self._combo_mode_filter.addItem("[Alle Modi]", "all")
        self._combo_mode_filter.setMinimumWidth(150)
        self._combo_mode_filter.setSizeAdjustPolicy(
            QComboBox.AdjustToContents)
        self._combo_mode_filter.setToolTip(
            "Modus-Filter: grenzt die Daten auf einen source_mode "
            "der Multi-Modus-Services ein (global fuer Tabelle, "
            "Heatmaps, Scatter, Verteilung).")
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

        # 13.08.2026 (Punkt 5): Layout-Restrukturierung - der bisherige
        # 1-Zeiler (ctrl: X-Achse/Y-Achse) und das 2-zeilige QGridLayout
        # (ctrl2) werden durch zwei buendige Zeilen (row1/row2, Aufbau
        # weiter unten nach der Widget-Erzeugung) ersetzt - alle Controls
        # bleiben unveraendert erhalten.

        # --- Steuerung (Zeile 2: Overlay + Zoom) ---
        self._chk_candle = QCheckBox("Kerzen-Overlay")
        # 12.08.2026 (User-Meldung 4, 'Anzeigebalken ca. 18h breit'):
        # TF-Anzeige des Kerzen-Overlays - der Nutzer sieht, welcher
        # Timeframe die Kerzenbreite bestimmt (z. B. 'D1' -> 16,8h-Kerzen).
        self._label_overlay_tf = QLabel("")
        self._label_overlay_tf.setStyleSheet(
            "color: #808080; font-size: 11px;")
        self._label_overlay_tf.setToolTip(
            "Timeframe des Kerzen-Overlays - bestimmt die Kerzenbreite "
            "(bar_sec * 0.7). Wird aus den OHLCV-Overlay-Daten gelesen.")
        self._slider_zoom_x = QSlider(Qt.Horizontal)
        self._slider_zoom_y = QSlider(Qt.Horizontal)
        self._label_info = QLabel("")
        self._label_info.setStyleSheet("color: #808080;")
        for s in (self._slider_zoom_x, self._slider_zoom_y):
            s.setRange(5, 100)
            # 13.08.2026 (Punkt 1): Mindestbreite + Expanding - die Slider
            # werden sonst in der vollen Zeile 1 auf 0 gedrueckt/unsichtbar.
            s.setMinimumWidth(70)
            s.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            # 09.08.2026 (User-Meldung 2): Richtung getauscht – rechts
            # (hoher Wert) = Zoom-In, links (niedriger Wert) = Zoom-Out.
            # 5 = volle Achse (links), 100 = maximale Vergroesserung (rechts).
            s.setValue(5)
            s.setEnabled(False)
            s.setToolTip("Viewport-Zoom (zentriert): rechts = Zoom-In, "
                         "links = Zoom-Out.")

        # 13.08.2026 (Punkt 5): Zwei klare, buendige Steuer-Zeilen.
        # Zeile 1: [x] Kerzen-Overlay | X-Achse | Y-Achse | Zoom X | Zoom Y |
        #          Modus | Aggregation (gleiche Controls wie bisher).
        # Zeile 2: 'Ergebnisparameter:' (Feld-Dropdown, CheckableComboBox)
        #          stretcht bis zum Canvas-Ende (Expanding + Stretch 1).
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(self._chk_candle)
        row1.addWidget(self._label_overlay_tf)
        row1.addSpacing(8)
        row1.addWidget(QLabel("X-Achse:"))
        row1.addWidget(self._combo_x)
        row1.addWidget(QLabel("Y-Achse:"))
        row1.addWidget(self._combo_y)
        row1.addSpacing(8)
        row1.addWidget(QLabel("Zoom X:"))
        row1.addWidget(self._slider_zoom_x)
        row1.addWidget(QLabel("Zoom Y:"))
        row1.addWidget(self._slider_zoom_y)
        row1.addSpacing(8)
        row1.addWidget(QLabel("Modus:"))
        row1.addWidget(self._combo_mode_filter)
        row1.addWidget(QLabel("Aggregation:"))
        row1.addWidget(self._combo_agg)
        row1.addStretch(1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(QLabel("Ergebnisparameter:"))
        row2.addWidget(self._combo_field, 1)
        row2.addWidget(self._label_info)

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

        # 21.03.11 (Bug 5): Zwei-Wege-Sync der Zoom-Slider - Maus-Zoom
        # (Mausrad/Drag) auf der Heatmap-ViewBox muss die X-/Y-Slider
        # mitbewegen (bisher nur einseitig Slider -> Range). Die Handler
        # aktualisieren Slider + VM-Params (blockSignals/_syncing-Guard
        # verhindern Endlos-Schleifen).
        self._plot_hm.plotItem.vb.sigXRangeChanged.connect(
            self._on_heatmap_x_range_changed)
        self._plot_hm.plotItem.vb.sigYRangeChanged.connect(
            self._on_heatmap_y_range_changed)

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
        lay.addLayout(row1)
        lay.addLayout(row2)
        lay.addWidget(self._plot_hm, 1)

        # --- Signale ---
        self._combo_x.currentIndexChanged.connect(self._on_config_changed)
        self._combo_y.currentIndexChanged.connect(self._on_config_changed)
        self._combo_agg.currentIndexChanged.connect(self._on_agg_changed)
        # 21.03.20 (Analytics Modus-Filter): Aenderung im Modus-
        # Dropdown -> globaler ViewModel-Refresh (alle Datenquellen).
        self._combo_mode_filter.currentIndexChanged.connect(
            self._on_mode_filter_changed)
        self._combo_field.currentIndexChanged.connect(self._on_config_changed)
        # 20.03.02 (F1c): CheckState-Wechsel im 'Feld'-Dropdown -> Filter.
        # 21.03.15 (Bug 1): Die Verbindung ist WIEDER AKTIV - Check/Uncheck
        # im 'Feld'-Dropdown schreibt feature_ids ueber den bestehenden
        # ServicePicker-Pfad (`_on_field_selection_changed` ->
        # `_reconcile_sammel_checks` -> `_checked_field_service_ids` ->
        # `set_feature_ids`), damit ServicePicker-Auswahl und Feld-Dropdown
        # konsistent bleiben.
        self._combo_field.selection_changed.connect(
            self._on_field_selection_changed)
        self._chk_candle.toggled.connect(self._on_candle_toggled)
        self._slider_zoom_x.valueChanged.connect(self._on_zoom_x_changed)
        self._slider_zoom_y.valueChanged.connect(self._on_zoom_y_changed)
