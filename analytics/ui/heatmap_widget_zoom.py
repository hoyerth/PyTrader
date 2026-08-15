"""
heatmap_widget_zoom.py - Zoom-Slider X/Y, Range-Apply, Achsen-Bounds, Range-Sync

23.09 God-File-Split (15.08.2026): Aus analytics/ui/heatmap_widget.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der HeatmapWidget-
Klasse als Mixin (Klasse HeatmapWidgetZoomMixin).
"""

from typing import (
    Any,
    Dict,
    List,
)

from analytics.engine.feature_store_reader import (
    DOW_WEEK_LABELS,
    HOURS_PER_DAY,
)

from analytics.ui.heatmap_widget_constants import (
    _HALF_DAY,
)

class HeatmapWidgetZoomMixin:

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

    # ------------------------------------------------------------------
    # 21.03.11 (Bug 5): Zoom-Slider Zwei-Wege-Sync (Maus-Zoom -> Slider)
    # ------------------------------------------------------------------
    def _on_heatmap_x_range_changed(self, _vb, xrange) -> None:
        """Aktualisiert den X-Zoom-Slider nach Maus-Zoom auf der X-Achse."""
        if getattr(self, "_syncing", False) or self._view_model is None:
            return
        self._sync_slider_from_range(
            self._slider_zoom_x, xrange,
            self._x_min, self._x_max, "zoom_x_range")

    def _on_heatmap_y_range_changed(self, _vb, yrange) -> None:
        """Aktualisiert den Y-Zoom-Slider nach Maus-Zoom auf der Y-Achse."""
        if getattr(self, "_syncing", False) or self._view_model is None:
            return
        self._sync_slider_from_range(
            self._slider_zoom_y, yrange,
            self._y_min, self._y_max, "zoom_y_range")

    def _sync_slider_from_range(self, slider, vrange, vmin, vmax, key) -> None:
        """Setzt Slider + VM-Params aus einem ViewBox-Range (Bug 5).

        Rechnet den sichtbaren Achsen-Anteil [lo, hi] aus dem Range in den
        normalisierten [0,1]-Bereich um und stellt den Slider invers ein.
        Kein DB-Requery (set_heatmap_zoom ist rein client-seitig).
        """
        span = float(vmax) - float(vmin)
        if span <= 0:
            return
        try:
            lo = (float(vrange[0]) - float(vmin)) / span
            hi = (float(vrange[1]) - float(vmin)) / span
        except (TypeError, ValueError, IndexError):
            return
        lo = max(0.0, min(1.0, lo))
        hi = max(0.0, min(1.0, hi))
        if hi <= lo:
            return
        self._set_zoom_slider(slider, [lo, hi])
        # VM-Params aktualisieren (Persistenz) - Endlos-Schleifen-Guard via
        # _syncing (set_heatmap_zoom emittiert kein ViewBox-Range-Event).
        try:
            if getattr(self, "_syncing", False) or self._view_model is None:
                return
            self._syncing = True
            zx = list(self._view_model.params.get("zoom_x_range") or [0.0, 1.0])
            zy = list(self._view_model.params.get("zoom_y_range") or [0.0, 1.0])
            if key == "zoom_x_range":
                zx = [lo, hi]
            else:
                zy = [lo, hi]
            self._view_model.set_heatmap_zoom(zx, zy)
        except Exception:
            pass
        finally:
            self._syncing = False
