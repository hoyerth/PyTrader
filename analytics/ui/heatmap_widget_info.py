"""
heatmap_widget_info.py - Info-Zeile, Maus-Tracking, Zell-Info, Legende, Offset

23.09 God-File-Split (15.08.2026): Aus analytics/ui/heatmap_widget.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der HeatmapWidget-
Klasse als Mixin (Klasse HeatmapWidgetInfoMixin).
"""

import math

from datetime import (
    datetime,
    timezone as dt_timezone,
)

from typing import (
    Any,
    List,
    Optional,
)

import pyqtgraph as pg

def _format_heatmap_value(val: Any) -> str:
    """Formatiert einen Heatmap-Zahlenwert OHNE Exponential-Notation.

    Bugfix 12.08.2026 (User-Meldung 'EXP-Wert in der Legende'):
    `f'{val:.2g}'` wechselt ab 100 in wissenschaftliche Notation
    ('1.2e+02'); `f'{v:g}'` ab 1e6 ('1e+06'). Ganzzahlige Werte
    (z. B. COUNT-Zaehler je Zelle/Bucket) werden in deutscher
    Tausender-Schreibweise ausgegeben ('4.380'), Bruchwerte (z. B.
    AVG/SUM/MIN/MAX) als Dezimalzahl ohne Nullen ('0.25', '62.5').
    """
    try:
        fval = float(val)
    except (TypeError, ValueError):
        return str(val)
    if not math.isfinite(fval):
        return str(val)
    if fval == int(fval) and abs(fval) < 1e15:
        return f"{int(fval):,}".replace(",", ".")
    return f"{fval:.2f}".rstrip("0").rstrip(".")


def _format_legend_value(val: Any, span: float) -> str:
    """Formatiert einen Legenden-Schwellwert mit adaptiver Genauigkeit.

    12.08.2026 (Bug 5): Bei kleinen Werte-Spannen kollabierten die
    Quartil-Schwellen der Legende unter der .2f-Rundung zu identischen
    Labels ('0.01 - 0.01' war unsinnig). Die Nachkommastellen-Zahl wird
    aus der Spanne abgeleitet, sodass die 25-%-Schritte (span/4) der
    Viridis-Legende GARANTIERT unterscheidbar bleiben. Ganzzahlige
    Schwellen ohne Nachkommastellen werden als Integer ausgegeben
    ('25'), Bruchwerte ohne Nullen ('0.0125', '0.02').
    """
    try:
        fval = float(val)
    except (TypeError, ValueError):
        return str(val)
    if not math.isfinite(fval):
        return str(val)
    if span is None or span <= 0:
        decimals = 2
    else:
        step = span / 4.0
        if step >= 1.0:
            decimals = 0
        else:
            decimals = int(math.ceil(-math.log10(step))) + 1
            decimals = max(0, min(decimals, 6))
    return f"{fval:.{decimals}f}".rstrip("0").rstrip(".")


class HeatmapWidgetInfoMixin:

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
        """Zeigt genaue Datum/Zeit + Matrix-Wert am Fadenkreuz (Bug 4).

        E15 (11.08.2026, Bugfix 1): Das DATUM ist der TAG DER ZELLE unter
        dem Fadenkreuz (self._x_axis[col], Mitternacht der Wanduhr). Die
        Zellen sind mittags-zentriert [Tag-12h, Tag+12h) – die nackte
        Cursor-Roh-Epoch wuerde sonst bei Vormittags-Zeiten (0:00-11:59)
        off-by-one-day liefern. Die ZEIT ist die exakte Cursor-HH:MM aus
        der Roh-Epoch (Wanduhr-UTC, KEIN Berlin-Offset). Das Label wird
        ausserdem IMMER aktualisiert (auch ausserhalb des Datenbereichs),
        damit kein veralteter Zellwert stehen bleibt.
        """
        if self._n_rows <= 0 or self._n_cols <= 0:
            return
        img = getattr(self._image, "image", None)
        if img is None or img.size == 0:
            return
        sx = (self._x_max - self._x_min) or 1.0
        sy = (self._y_max - self._y_min) or 1.0
        col = int((x - self._x_min) / sx * self._n_cols)
        row = int((y - self._y_min) / sy * self._n_rows)
        in_bounds = (0 <= col < self._n_cols and 0 <= row < self._n_rows)
        time_txt = ""
        if str(self._combo_x.currentData() or "date") == "date":
            try:
                day_ts = float(self._x_axis[col]) if (
                    0 <= col < len(self._x_axis)) else float(x)
                d_day = datetime.fromtimestamp(day_ts, tz=dt_timezone.utc)
                d_time = datetime.fromtimestamp(float(x), tz=dt_timezone.utc)
                days = ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So.")
                time_txt = (f"{days[d_day.weekday()]} {d_day.day:02d}."
                            f"{d_day.month:02d}.{d_day.year % 100:02d} "
                            f"{d_time.hour:02d}:{d_time.minute:02d}  →  ")
            except (TypeError, ValueError, OverflowError, OSError):
                time_txt = ""
        if not in_bounds:
            self._label_info.setText(
                f"{time_txt}Zelle ausserhalb des Datenbereichs")
            return
        try:
            v = float(img[row, col])
        except (TypeError, ValueError, IndexError):
            self._label_info.setText(f"{time_txt}Zelle({row},{col}) = n/a")
            return
        self._label_info.setText(f"{time_txt}Zelle({row},{col}) = {_format_heatmap_value(v)}")

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
                # 21.03.11 (Bug 1): Operator-korrekte Beschriftung
                # (= Treffer-Wert, >=" fuer alles darueber).
                label = "= {}".format(c) if c < 5 else ">= 5"
                self._add_legend_swatch(color, label)
        else:
            # 12.08.2026 (Bug 5): Viridis als OPERATOR-Intervalle. Die
            # Schwellen v25/v50/v75/vmax werden mit adaptiver Genauigkeit
            # formatiert (_format_legend_value, Spannen-abhaengige Nach-
            # kommastellen), damit sie bei kleinen Spannen (z. B. vmin=0.01,
            # vmax=0.02) NICHT zusammenfallen ('0.01 - 0.01' war unsinnig).
            # Die Labels sind eindeutige Operator-Angaben (`<`, `<=`,
            # `>=`) statt Bindestrich-Bereichen.
            span = vmax - vmin
            v25 = vmin + 0.25 * span
            v50 = vmin + 0.50 * span
            v75 = vmin + 0.75 * span
            fmt = lambda v: _format_legend_value(v, span)
            # 13.08.2026 (Punkt 2, F2): Viridis-Operatoren VOR der Zahl,
            # kein 'x' mehr - eindeutige Schwellen-Angaben
            # (<= v25, >= v25, >= v50, >= v75, >= vmax).
            self._add_legend_swatch(cmap.map(0.0, mode="qcolor"),
                                    "<= {}".format(fmt(v25)))
            self._add_legend_swatch(cmap.map(0.25, mode="qcolor"),
                                    ">= {}".format(fmt(v25)))
            self._add_legend_swatch(cmap.map(0.5, mode="qcolor"),
                                    ">= {}".format(fmt(v50)))
            self._add_legend_swatch(cmap.map(0.75, mode="qcolor"),
                                    ">= {}".format(fmt(v75)))
            self._add_legend_swatch(cmap.map(1.0, mode="qcolor"),
                                    ">= {}".format(fmt(vmax)))
        self._legend.show()

    def _add_legend_swatch(self, color, label: str) -> None:
        """Fuegt ein Farbfeld + Label zur Legende hinzu (Bugfix 2)."""
        item = pg.PlotDataItem(
            [0], [0], pen=None,
            symbol="s", symbolSize=10,
            symbolBrush=pg.mkColor(color), symbolPen=pg.mkPen(None))
        self._legend.addItem(item, str(label))
