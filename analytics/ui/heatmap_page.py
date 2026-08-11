# analytics/ui/heatmap_page.py
"""
heatmap_page.py - Heatmap-Seite der Analytics-UI (Phase 15.03).

Zeigt die 2D-Matrix (X: Wochentage, Y: Tagesstunden Berlin Wanduhr,
Invariante 7) als pyqtgraph-ImageItem mit Farbskala. Ein Doppelklick auf
eine Zelle oeffnet das Chart an der neuesten Feature-Bar dieser Zelle
(Jump-to-Chart Variante 2, Aufloesung ueber den ViewModel).

MVVM (Invariante 4): Reine UI – Daten kommen ueber
`data_ready(QUERY_HEATMAP, data)` vom ViewModel (Async-Worker); es gibt
KEIN SQL in dieser Klasse.
"""

from typing import Any, Callable, Dict, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import QUERY_HEATMAP
from analytics.engine.feature_store_reader import (
    DOW_LABELS,
    DAYS_PER_WEEK,
    HOURS_PER_DAY,
)
from analytics.ui.common import make_overlay_stack
from analytics.ui.heatmap_widget import HeatmapWidget

# Farbverlauf (pyqtgraph-intern, 'viridis').
_HEATMAP_COLORMAP = "viridis"


class HeatmapPage(QWidget):
    """Heatmap Wochentag x Stunde (Berlin Wanduhr) mit Jump-to-Chart."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None
        self._navigation_handler: Optional[Callable[[str, str, int], None]] = None
        self._cell_resolver: Optional[Callable[[str, str, int, int], Optional[int]]] = None
        self._current_symbol = ""
        self._current_timeframe = "M1"

        # Metrik-Dropdown (19.02: count | numerische feature_data-JSON-Keys)
        self._combo_metric = QComboBox()
        self._label_info = QLabel("")

        # pyqtgraph-Plot + ImageItem + Farbskala
        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.setLabel("bottom", "Wochentag")
        self._plot.setLabel("left", "Stunde (Berlin Wanduhr)")
        self._image = pg.ImageItem()
        self._plot.addItem(self._image)
        self._colormap = pg.colormap.get(_HEATMAP_COLORMAP)
        self._image.setColorMap(self._colormap)
        self._colorbar = pg.ColorBarItem(colorMap=self._colormap, values=(0.0, 1.0))
        self._colorbar.setImageItem(self._image)
        # Achsen-Ticks: X = Wochentage, Y = Stunden (Wanduhr)
        self._plot.getAxis("bottom").setTicks(
            [[(i, DOW_LABELS[i]) for i in range(DAYS_PER_WEEK)]]
        )
        self._plot.getAxis("left").setTicks(
            [[(h, f"{h:02d}") for h in range(0, HOURS_PER_DAY, 3)]]
        )

        content = QWidget(self)
        lay = QVBoxLayout(content)

        # 21.01 (User-Meldung 2, 11.08.2026): Das "Ansicht"-Dropdown enthaelt
        # jetzt die 4 Smart-Presets; "Wochentag × Stunde" entfaellt (der
        # Standard-Modus bleibt als Legacy-Code fuer Restores erhalten, ist
        # aber KEIN Dropdown-Eintrag mehr). "Generisch" ist die Basis-Ansicht
        # (Index 0); jede Preset-Option wendet das Preset an (Meldung 3: die
        # Bedien-Controls des generischen Widgets bleiben dabei sichtbar).
        self._combo_mode = QComboBox()
        self._combo_mode.addItem("Generisch", "generic")
        self._combo_mode.addItem("⚡ Signal-Confluence", "preset_confluence")
        self._combo_mode.addItem("🕒 Session-Hotspots", "preset_session")
        self._combo_mode.addItem("📏 Wert-Intensität", "preset_intensity")
        self._combo_mode.addItem("📊 Service-Timeframe", "preset_timeframe")
        self._combo_mode.setCurrentIndex(0)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Ansicht:"))
        mode_row.addWidget(self._combo_mode)
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        # --- Standard-Modus (bestehende Struktur, unveraendert) ---
        self._standard_ui = QWidget(self)
        std_lay = QVBoxLayout(self._standard_ui)
        std_lay.setContentsMargins(0, 0, 0, 0)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Metrik:"))
        ctrl.addWidget(self._combo_metric)
        ctrl.addWidget(self._label_info)
        ctrl.addStretch(1)
        std_lay.addLayout(ctrl)
        std_lay.addWidget(self._plot)

        # --- Generischer Modus (20.02, E1/E7/E8/E9) ---
        self._generic = HeatmapWidget()

        self._stack_modes = QStackedWidget()
        self._stack_modes.addWidget(self._standard_ui)
        self._stack_modes.addWidget(self._generic)
        lay.addWidget(self._stack_modes)

        self._stack = make_overlay_stack(content)
        self.setLayout(self._stack)

        self._combo_metric.currentTextChanged.connect(self._on_metric_changed)
        self._plot.scene().sigMouseClicked.connect(self._on_plot_clicked)
        self._combo_mode.currentIndexChanged.connect(self._on_mode_changed)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (vom AnalyticsWindow gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        self._view_model = view_model
        # 20.02: Das generische Widget erhaelt denselben ViewModel und
        # verbindet eigene data_ready-Slots (QUERY_HEATMAP_GENERIC/
        # QUERY_DAILY_OHLC, Bugfix 09.08.2026).
        self._generic.attach_view_model(view_model)
        # 21.01 (E7, 11.08.2026): Die `preset_clicked`-Verbindung wurde
        # entfernt – das generische Widget hat keine Preset-Buttons mehr
        # (Smart-Presets laufen ausschliesslich ueber das Ansicht-Dropdown).
        params = view_model.params
        # 19.02 (Cleanup): Metriken = "count" + numerische feature_data-
        # JSON-Keys (dynamisch). Prefill fuer das aktuelle Symbol/Timeframe;
        # die Combo wird bei jedem Daten-Payload aktualisiert (on_data_ready).
        metrics = view_model.heatmap_metrics(
            params.get("symbol", ""), params.get("timeframe", "M1"))
        self._set_metrics(metrics, params.get("heatmap_metric"))
        view_model.data_ready.connect(self.on_data_ready)

    def set_navigation_handler(self, fn: Callable[[str, str, int], None]) -> None:
        self._navigation_handler = fn

    def set_cell_resolver(
        self, fn: Callable[[str, str, int, int], Optional[int]]
    ) -> None:
        """Setzt die Zell-Aufloesung (dow, hour -> neuester bar_time)."""
        self._cell_resolver = fn

    def request_data(self) -> None:
        if self._view_model is None:
            return
        # 21.01 (Meldung 2): Die Heatmap-Ansicht ist seit dem Entfall von
        # "Wochentag × Stunde" IMMER generisch – die Daten kommen immer
        # aus dem generischen Widget (+ OHLCV-Snapshot bei aktivem Overlay, E9).
        self._generic.request_data()

    # ------------------------------------------------------------------
    # 20.02: Ansichts-Modus (Workspace-Persistenz, E2)
    # ------------------------------------------------------------------
    @property
    def mode_id(self) -> str:
        """Aktueller Modus ("generic" | "preset_*") fuer die Workspace-Speicherung."""
        return str(self._combo_mode.currentData() or "generic")

    def set_mode(self, mode_id: str) -> None:
        """Stellt den Ansichts-Modus wieder her (Workspace/Profil-Restore).

        21.01 (Meldung 2): Legacy-Modi ("standard"/"wochentag") werden auf
        "generic" gemappt. Signale blockiert (kein Dirty/Query beim Restore);
        der Stack zeigt immer das generische Widget (Meldung 3).
        """
        mid = str(mode_id or "").lower()
        if mid in ("standard", "wochentag", "wochentag_x_stunde",
                   "wochentag x stunde"):
            mid = "generic"
        idx = self._combo_mode.findData(mid)
        if idx < 0:
            idx = 0
        if self._combo_mode.currentIndex() != idx:
            self._combo_mode.blockSignals(True)
            self._combo_mode.setCurrentIndex(idx)
            self._combo_mode.blockSignals(False)
        self._stack_modes.setCurrentIndex(1)

    def _on_mode_changed(self, _index: int) -> None:
        """Wechselt die Ansicht: Preset anwenden bzw. generisch laden.

        21.01 (Meldung 2+3): Die Bedien-Controls (generisches Widget)
        bleiben bei JEDEM Preset-Wechsel sichtbar (Stack zeigt immer
        Seite 1). Eine Preset-Option wendet das Smart-Preset an.
        """
        mid = str(self._combo_mode.currentData() or "generic")
        self._stack_modes.setCurrentIndex(1)
        if mid.startswith("preset_"):
            self._apply_selected_preset(mid)
        else:
            self.request_data()

    def _apply_selected_preset(self, mid: str) -> None:
        """Wendet das im Ansicht-Dropdown gewaehlte Smart-Preset an.

        Bugfix-Muster 21.01 (Meldung 4/6): Nach dem VM-Preset werden die
        Combos des generischen Widgets via _sync_from_params nachgezogen
        (keine STALE-Combos), danach wird neu gerendert.
        """
        if self._view_model is None:
            return
        fn = {
            "preset_confluence": self._view_model.apply_smart_preset_confluence,
            "preset_session": self._view_model.apply_smart_preset_session,
            "preset_intensity": self._view_model.apply_smart_preset_intensity,
            "preset_timeframe": self._view_model.apply_smart_preset_timeframe,
        }.get(mid)
        if fn is None:
            return
        fn()
        generic = getattr(self, "_generic", None)
        if generic is not None and hasattr(generic, "_sync_from_params"):
            generic._sync_from_params()
        self.request_data()

    # ------------------------------------------------------------------
    # 19.02: Dynamische Metrik-Combo ("count" + feature_data-JSON-Keys)
    # ------------------------------------------------------------------
    def _set_metrics(self, metrics, metric) -> None:
        """Fuellt die Metrik-Combo (19.02, dynamische JSON-Keys).

        Erhaelt die aktuelle Auswahl, wenn sie in `metrics` verfuegbar ist;
        sonst "count". Signale blockiert (kein Query-Loop).
        """
        items = [str(m) for m in (metrics or [])]
        sel = str(metric or "") if str(metric or "") in items else (
            "count" if "count" in items else (items[0] if items else ""))
        self._combo_metric.blockSignals(True)
        self._combo_metric.clear()
        for m in items:
            self._combo_metric.addItem(m, m)
        self._combo_metric.setCurrentIndex(
            self._combo_metric.findData(sel) if sel else -1)
        self._combo_metric.blockSignals(False)

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind != QUERY_HEATMAP:
            return
        self._current_symbol = str(data.get("symbol") or "")
        self._current_timeframe = str(data.get("timeframe") or "M1")
        # 19.02: Metrik-Combo mit den verfuegbaren Metriken aktualisieren und
        # auf die tatsaechlich verwendete Metrik synchronisieren.
        vm_params_metric = (self._view_model.params.get("heatmap_metric")
                            if self._view_model else "")
        self._set_metrics(
            data.get("metrics"),
            data.get("metric") or vm_params_metric,
        )
        matrix = np.asarray(data.get("matrix"), dtype=float)
        if matrix.size == 0:
            self._stack.setCurrentIndex(1)
            return
        self._render(matrix)
        self._stack.setCurrentIndex(0)

    def _render(self, matrix: np.ndarray) -> None:
        """Zeichnet die 24x7-Matrix (rows=Stunde, cols=DOW)."""
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
        self._plot.setXRange(-0.5, DAYS_PER_WEEK - 0.5, padding=0)
        self._plot.setYRange(-0.5, HOURS_PER_DAY - 0.5, padding=0)

    # ------------------------------------------------------------------
    # Jump-to-Chart (Variante 2): Doppelklick auf eine Zelle
    # ------------------------------------------------------------------
    def _on_plot_clicked(self, event) -> None:
        if not event.double() or self._cell_resolver is None \
                or self._navigation_handler is None:
            return
        vb = self._plot.plotItem.vb
        pos = vb.mapSceneToView(event.scenePos())
        dow = int(round(pos.x()))
        hour = int(round(pos.y()))
        if not (0 <= dow < DAYS_PER_WEEK and 0 <= hour < HOURS_PER_DAY):
            return
        bar_time = self._cell_resolver(
            self._current_symbol, self._current_timeframe, dow, hour
        )
        if bar_time is not None:
            self._navigation_handler(
                self._current_symbol, self._current_timeframe, int(bar_time)
            )

    # ------------------------------------------------------------------
    # Steuerung (Metrik -> ViewModel -> Debounce -> Worker)
    # ------------------------------------------------------------------
    def _on_metric_changed(self, metric: str) -> None:
        if self._view_model is not None and metric:
            self._view_model.set_heatmap_metric(metric)
