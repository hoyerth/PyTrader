"""
analytics_view_model_heatmap.py - Heatmap-Config, Smart-Presets, Zoom/Projektion, Spalten/Bins/Limit/Settings

23.07 God-File-Split (15.08.2026): Aus analytics/engine/analytics_view_model.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der AnalyticsViewModel-
Klasse als Mixin (Klasse AnalyticsViewModelHeatmapMixin).
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from analytics.engine.analytics_worker import (
    QUERY_TABLE,
    QUERY_HEATMAP,
    QUERY_HEATMAP_GENERIC,
    QUERY_SCATTER,
    QUERY_DISTRIBUTION,
)

class AnalyticsViewModelHeatmapMixin:

    def set_heatmap_metric(self, metric: str) -> None:
        self._set_param("heatmap_metric", str(metric or "count"),
                        (QUERY_HEATMAP,))

    # ------------------------------------------------------------------
    # 20.02: Generische 2D-Heatmap – Konfiguration/Zoom/Overlay (additiv)
    # ------------------------------------------------------------------
    def set_heatmap_config(
        self, x_dim: str, y_dim: str, field: str, agg: str
    ) -> None:
        """Setzt die Konfiguration der generischen Heatmap (20.02, E1).

        x_dim/y_dim aus DIM_MAPPINGS (case-insensitiv), `agg` eine der
        HEATMAP_AGGREGATIONS, `field` der numerische feature_data-JSON-Key
        (E6: nur bei AVG/SUM/MIN/MAX relevant; COUNT/CONFLUENCE_COUNT
        ignorieren ihn). 20.02.01 (E6): `dow_hour` wird per Sanitizer auf
        "hour" abgebildet. Ohne Aenderung idempotent (kein Refresh).
        """
        x_dim = self._sanitize_dim(x_dim or "date")
        y_dim = self._sanitize_dim(y_dim or "hour")
        agg = str(agg or "confluence_count").lower()
        field = str(field or "")
        changed = (x_dim != self._params.get("heatmap_x_dim")
                   or y_dim != self._params.get("heatmap_y_dim")
                   or agg != self._params.get("heatmap_agg")
                   or field != self._params.get("heatmap_field"))
        if not changed:
            return
        self._params["heatmap_x_dim"] = x_dim
        self._params["heatmap_y_dim"] = y_dim
        self._params["heatmap_agg"] = agg
        self._params["heatmap_field"] = field
        self._mark_dirty()
        self._refresh((QUERY_HEATMAP_GENERIC,))

    # ------------------------------------------------------------------
    # 21.01: Smart-Presets (E4, 11.08.2026)
    # ------------------------------------------------------------------
    def _set_heatmap_all_timeframes(self, enabled: bool) -> None:
        """Setzt die TF-Freigabe der generischen Heatmap (21.01, E1).

        Idempotent ohne Aenderung; Dirty-Flag + Refresh nur bei echtem
        Wechsel (Muster set_heatmap_config).
        """
        enabled = bool(enabled)
        if enabled == self._params.get("heatmap_all_timeframes"):
            return
        self._params["heatmap_all_timeframes"] = enabled
        self._mark_dirty()
        self._refresh((QUERY_HEATMAP_GENERIC,))

    def apply_smart_preset_confluence(self) -> None:
        """`[⚡ Signal-Confluence]`: X=date, Y=service_id, count(DISTINCT fid).

        Chronologische Lichtsaeulen zeitgleicher Signale (Hauptansicht).
        Konfiguration + Dirty-Flag (Option B), KEIN Auto-Save (E4).
        21.03.21 (Hotspot-Orchestrierung): Der Preset setzt den
        Modus-Filter auf `"all"` zurueck - Confluence/Hotspots sind
        die Haeufung ueber ALLE Modi hinweg (Kapitel §3.2-Standard).
        Idempotent: `set_service_mode("all")` ist ein early-return,
        wenn kein Modus-Filter aktiv ist.
        """
        self._set_heatmap_all_timeframes(False)
        self.set_service_mode("all")
        self.set_heatmap_config("date", "service_id", "", "confluence_count")

    def apply_smart_preset_session(self) -> None:
        """`[🕒 Session-Hotspots]`: X=dow (Mo-Fr), Y=hour, count(DISTINCT fid).

        Tageszeit-/Wochentag-Muster im Handelsverlauf (Wanduhr, E5-Phase 20).
        Konfiguration + Dirty-Flag (Option B), KEIN Auto-Save (E4).
        """
        self._set_heatmap_all_timeframes(False)
        self.set_heatmap_config("dow", "hour", "", "confluence_count")

    def apply_smart_preset_intensity(self, x_dim: str = "date") -> None:
        """`[📏 Wert-Intensität]`: X=date (Standard) oder dow (E2), Y=hour.

        Auspraegung von Messwerten (z. B. distance_pip, atr) – AVG/Max ueber
        den ersten verfuegbaren numerischen feature_data-JSON-Key (Repo-
        Fallback, wenn keiner existiert). `x_dim` akzeptiert "date" (Default)
        oder "dow" (E2). Konfiguration + Dirty-Flag (Option B), KEIN
        Auto-Save (E4).
        """
        x_key = "dow" if str(x_dim or "").strip().lower() == "dow" else "date"
        # Erster verfuegbarer numerischer Key (Muster Repo-E6-Fallback) –
        # bei leeren Daten bleibt field="" (Repo faellt defensiv zurueck).
        try:
            avail = self._repo.available_feature_columns(
                str(self._params.get("symbol") or ""),
                str(self._params.get("timeframe") or "M1"))
            field = avail[0] if avail else ""
        except Exception:
            field = ""
        self._set_heatmap_all_timeframes(False)
        self.set_heatmap_config(x_key, "hour", field, "avg")

    def apply_smart_preset_timeframe(self) -> None:
        """`[📊 Service-Timeframe]`: X=timeframe (ALLE TFs), Y=service_id.

        Verteilung der Services ueber Zeitebenen (E1: `all_timeframes=True`
        entfaellt die TF-WHERE-Bedingung – alle M1..D1 in EINER Query).
        Konfiguration + Dirty-Flag (Option B), KEIN Auto-Save (E4).
        """
        self._set_heatmap_all_timeframes(True)
        self.set_heatmap_config("timeframe", "service_id", "", "count")

    # ------------------------------------------------------------------
    # 21.01 (E3): Auto-Namensgenerator fuer neue Profile (DEUTSCH)
    # ------------------------------------------------------------------
    def generate_profile_name_suggestion(self) -> str:
        """Sprechender Profilname – Formel `[Symbol] [TF] - [Modus] ([Kontext])`.

        E3 (11.08.2026): Sprache DEUTSCH, z. B.
        `SILVER M1 - Confluence Zeitachse (3 Services)`.
        * Kontext-Klammer = Anzahl der selektierten Services (feature_ids);
          bei 0 Auswahlen `(Alle Services)` statt `(0 Services)`.
        * Fehlendes Symbol/Timeframe -> Platzhalter `ALLE`
          (z. B. `ALLE M1 - Confluence Zeitachse (3 Services)`).
        * Modus-Ableitung aus der AKTUELLEN Heatmap-Konfiguration
          (Confluence/Session/Intensitaet/TF-Matrix) – der Vorschlag passt
          zum eingestellten Ansichts-Szenario.
        """
        symbol = str(self._params.get("symbol") or "").strip() or "ALLE"
        timeframe = str(self._params.get("timeframe") or "").strip() or "ALLE"
        x_dim = str(self._params.get("heatmap_x_dim") or "").lower()
        y_dim = str(self._params.get("heatmap_y_dim") or "").lower()
        agg = str(self._params.get("heatmap_agg") or "").lower()
        if x_dim == "timeframe":
            mode = "Service-Zeitebenen"
        elif x_dim == "dow" and y_dim == "hour":
            mode = "Session-Hotspots"
        elif agg in ("avg", "sum", "min", "max"):
            mode = "Wert-Intensität"
        else:
            mode = "Confluence Zeitachse"
        n = len(self._params.get("feature_ids") or [])
        context = f"{n} Services" if n > 0 else "Alle Services"
        return f"{symbol} {timeframe} - {mode} ({context})"

    def set_heatmap_zoom(self, x_range, y_range) -> None:
        """Setzt die normalisierten Viewport-Anteile [0,1] (20.02, E8).

        Rein client-seitig (die UI wendet die Bereiche direkt per
        setXRange/setYRange an) – KEIN DB-Requery. Die Werte werden geclampt
        (0 ≤ lo < hi ≤ 1) und fuer die Persistenz (Profil/Workspace)
        markiert (Option B – Explicit Save).
        """
        x_clamped = self._clamp_zoom(x_range)
        y_clamped = self._clamp_zoom(y_range)
        if (x_clamped == self._params.get("zoom_x_range")
                and y_clamped == self._params.get("zoom_y_range")):
            return
        self._params["zoom_x_range"] = x_clamped
        self._params["zoom_y_range"] = y_clamped
        self._mark_dirty()

    def set_candle_projection(self, enabled: bool) -> None:
        """Schaltet das Candle-Overlay (Preis-Strip) an/aus (20.02, E9).

        Reiner UI-Zustand ohne DB-Abfrage (der OHLCV-Snapshot wird von der
        HeatmapPage on-demand angefordert); nur Dirty-Markierung fuer die
        Profil-Persistenz.
        """
        enabled = bool(enabled)
        if enabled == self._params.get("candle_projection_enabled"):
            return
        self._params["candle_projection_enabled"] = enabled
        self._mark_dirty()

    @staticmethod
    def _clamp_zoom(value) -> List[float]:
        """Clampt einen Zoom-Bereich auf [0.0, 1.0] mit lo < hi (E8)."""
        try:
            lo, hi = float(value[0]), float(value[1])
        except (TypeError, ValueError, IndexError):
            return [0.0, 1.0]
        lo = max(0.0, min(1.0, lo))
        hi = max(0.0, min(1.0, hi))
        return [lo, hi] if hi > lo else [0.0, 1.0]

    @staticmethod
    def _sanitize_dim(value) -> str:
        """Bereinigt eine Heatmap-Dimension (20.02.01, E6).

        `dow_hour` ist ersatzlos aus DIM_MAPPINGS/HEATMAP_DIMENSIONS entfernt.
        Alt-Profil-/Workspace-/Config-Werte mit `dow_hour` werden auf die
        gueltige Dimension "hour" (Tageszeit) abgebildet – sonst wuerde
        `_set_combo_data` (additives Hinzufuegen unbekannter Werte) die
        entfernte Dimension wieder in die UI-Combos aufnehmen.
        """
        dim = str(value or "").lower()
        return "hour" if dim == "dow_hour" else dim

    def set_scatter_columns(self, x_column: str, y_column: str) -> None:
        # 19.02 (Cleanup): Leere Werte = Repo-Default (erste numerische
        # feature_data-JSON-Keys). Keine Legacy-Spalten-Fallbacks mehr.
        self._set_param("scatter_x", str(x_column or ""),
                        (QUERY_SCATTER,))
        self._set_param("scatter_y", str(y_column or ""),
                        (QUERY_SCATTER,))

    def set_distribution_column(self, column: str) -> None:
        self._set_param("distribution_column",
                        str(column or ""),
                        (QUERY_DISTRIBUTION,))

    def set_bins(self, bins: int) -> None:
        new_bins = self._clamp_bins(bins)
        if new_bins != self._params["bins"]:
            self._params["bins"] = new_bins
            self._mark_dirty()
            self._refresh((QUERY_DISTRIBUTION,))

    def set_limit(self, limit: int) -> None:
        new_limit = self._clamp_limit(limit)
        if new_limit != self._params["limit"]:
            self._params["limit"] = new_limit
            self._mark_dirty()
            self._refresh((QUERY_TABLE, QUERY_SCATTER, QUERY_DISTRIBUTION))

    def set_table_settings(
        self,
        widths: Optional[Dict[str, Any]] = None,
        row_height: int = 0,
        sort_column: int = 0,
        sort_order: int = 1,
    ) -> None:
        """Uebernimmt TablePage-Settings (19.03 E6, ohne Query-Refresh).

        Spaltenbreiten {Spaltenname: Breite} (E5), **globale Zeilenhoehe**
        (E9/19.06: ein Wert fuer die GESAMTE Tabelle – das Ziehen einer
        Zeile setzt alle Zeilen live auf diese Hoehe), Sortier-Spalte und
        -Richtung (E8). Reine UI-Zustaende der TablePage: KEIN `_refresh`/
        Debounce/Worker und keine DB-Abfrage – nur die Dirty-Markierung fuer
        die Profil-Persistenz (Option B – Explicit Save). Typ-/Werte-
        normalisiert; ohne tatsaechliche Aenderung idempotent (kein
        unnötiges Dirty-Flag bei Drag-Ereignissen).
        """
        norm_widths: Dict[str, int] = {}
        for k, v in (widths or {}).items():
            try:
                w = int(v)
            except (TypeError, ValueError):
                continue
            if w > 0:
                norm_widths[str(k)] = w
        try:
            rh = max(0, int(row_height))
        except (TypeError, ValueError):
            rh = 0
        try:
            sc = max(0, int(sort_column))
        except (TypeError, ValueError):
            sc = 0
        try:
            so_raw = int(sort_order)
        except (TypeError, ValueError):
            so_raw = 1
        so = so_raw if so_raw in (0, 1) else 1

        if (norm_widths == self._params.get("table_column_widths")
                and rh == self._params.get("table_row_height")
                and sc == self._params.get("table_sort_column")
                and so == self._params.get("table_sort_order")):
            return
        self._params["table_column_widths"] = norm_widths
        self._params["table_row_height"] = rh
        self._params["table_sort_column"] = sc
        self._params["table_sort_order"] = so
        self._mark_dirty()
