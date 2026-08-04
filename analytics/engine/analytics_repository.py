# analytics/engine/analytics_repository.py
"""
analytics_repository.py - AnalyticsRepository (Phase 15.03).

High-Level-Datenmethoden fuer die Analytics-UI (AnalyticsWindow).
Delegiert lesend an den `FeatureStoreReader` (reiner Lese-Pfad auf den
feature_store, Invariante 4 / MVVM) und bereitet die Rohdaten in die von
den UI-Pages benoetigten Strukturen auf:

    get_table()         – rohe Feature-Zeilen fuer die Tabellen-Seite
    get_heatmap()       – 2D-Matrix (X: Wochentage, Y: Tagesstunden
                          Berlin Wanduhr, Invariante 7)
    get_scatter()       – X/Y-Paare zweier nativer Spalten
    get_distribution()  – Histogramm (bins/counts) einer nativen Spalte

Das Repository ist rein lesend (kein SQL in UI, keine Schreiboperationen) –
die Profil-Persistenz (Option B / Explicit Save) liegt separat im
`AnalyticsProfileRepository` (Schritt 2).

E-1: Das Alt-Repository `analytics/statistics_repository.py` bleibt bis auf
Weiteres unveraendert bestehen (genutzt vom Legacy-StatisticWindow); dieses
Repository ist der Ersatz fuer die neue Analytics-UI (15.03).
"""

from typing import Any, Dict, List, Optional

import numpy as np

from analytics.engine.feature_store_reader import (
    FeatureStoreReader,
    NATIVE_COLUMNS,
    DOW_LABELS,
    HOURS_PER_DAY,
    DAYS_PER_WEEK,
)

# Vertraglich unterstuetzte Metriken fuer die Heatmap (count + native Spalten).
HEATMAP_METRICS = ("count",) + NATIVE_COLUMNS


class AnalyticsRepository:
    """High-Level-Datenzugriff fuer die Analytics-UI (lesend)."""

    def __init__(self, reader: Optional[FeatureStoreReader] = None) -> None:
        self.reader = reader or FeatureStoreReader()

    # ------------------------------------------------------------------
    # Tabelle
    # ------------------------------------------------------------------
    def get_table(
        self,
        symbol: str,
        timeframe: str,
        feature_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> Dict[str, Any]:
        """Rohe Feature-Zeilen fuer die Tabellen-Seite.

        Returns:
            {"rows": [FeatureStoreReader-Zeilen...], "total": n}
        """
        rows = self.reader.fetch_rows(symbol, timeframe, feature_id=feature_id,
                                      limit=limit)
        return {"rows": rows, "total": len(rows)}

    # ------------------------------------------------------------------
    # Heatmap (X: Wochentage, Y: Tagesstunden Berlin Wanduhr)
    # ------------------------------------------------------------------
    def get_heatmap(
        self,
        symbol: str,
        timeframe: str,
        metric: str = "count",
        feature_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """2D-Matrix (Wochentag x Tagesstunde) fuer die Heatmap-Seite.

        Wanduhr-Garantie (Invariante 7): Die Extraktion von Wochentag/Stunde
        erfolgt im Reader mit `bar_time AT TIME ZONE 'UTC'` (die gespeicherten
        Werte sind Berlin-Wanduhr-encoded – die UTC-Darstellung IST die
        Wanduhr-Zeit, kein Offset).

        Returns:
            {
              "matrix":   7x24 (rows=Stunde 0-23, cols=DOW 0=So..6=Sa),
              "x_labels": Wochentage, "y_labels": Stunden,
              "metric", "symbol", "timeframe",
            }
        """
        return self.reader.fetch_heatmap(
            symbol, timeframe, metric=metric, feature_id=feature_id
        )

    # ------------------------------------------------------------------
    # Scatter
    # ------------------------------------------------------------------
    def get_scatter(
        self,
        symbol: str,
        timeframe: str,
        x_column: str = "ema_diff",
        y_column: str = "rsi_14",
        feature_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> Dict[str, Any]:
        """X/Y-Paare zweier nativer Spalten fuer die Scatter-Seite.

        Zeilen mit NULL in einer der beiden Spalten werden ausgelassen.
        Unbekannte Spalten werden durch die Reader-Validierung abgefangen
        (nur native Spalten erlaubt).

        Returns:
            {"points": [{"x": float, "y": float}, ...],
             "x_label": x_column, "y_label": y_column,
             "symbol", "timeframe", "total": n}
        """
        if x_column not in NATIVE_COLUMNS or y_column not in NATIVE_COLUMNS:
            raise ValueError(
                f"[AnalyticsRepository] Unbekannte Scatter-Spalten "
                f"x='{x_column}', y='{y_column}' – erlaubt: {NATIVE_COLUMNS}."
            )
        rows = self.reader.fetch_columns(
            symbol, timeframe, [x_column, y_column],
            feature_id=feature_id, limit=limit,
        )
        points: List[Dict[str, float]] = []
        for r in rows:
            xv = r.get(x_column)
            yv = r.get(y_column)
            if xv is None or yv is None:
                continue
            if not (np.isfinite(xv) and np.isfinite(yv)):
                continue
            points.append({"x": xv, "y": yv})
        return {
            "points": points,
            "x_label": x_column,
            "y_label": y_column,
            "symbol": symbol,
            "timeframe": timeframe,
            "total": len(points),
        }

    # ------------------------------------------------------------------
    # Verteilung
    # ------------------------------------------------------------------
    def get_distribution(
        self,
        symbol: str,
        timeframe: str,
        column: str = "atr_normalized",
        bins: int = 20,
        feature_id: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> Dict[str, Any]:
        """Histogramm einer nativen Spalte fuer die Verteilungs-Seite.

        Berechnet bin-Edges + counts mit numpy.histogram (NaN-/Inf-Werte
        werden ausgelassen). Unbekannte Spalten werden abgefangen.

        Returns:
            {"bins": [edges...], "counts": [n...], "column": column,
             "symbol", "timeframe", "total": n}
        """
        if column not in NATIVE_COLUMNS:
            raise ValueError(
                f"[AnalyticsRepository] Unbekannte Verteilungs-Spalte "
                f"'{column}' – erlaubt: {NATIVE_COLUMNS}."
            )
        try:
            n_bins = max(2, int(bins))
        except (TypeError, ValueError):
            n_bins = 20

        rows = self.reader.fetch_columns(
            symbol, timeframe, [column], feature_id=feature_id, limit=limit,
        )
        values = [r[column] for r in rows if r.get(column) is not None]
        values = [v for v in values if np.isfinite(v)]
        if not values:
            return {
                "bins": [], "counts": [], "column": column,
                "symbol": symbol, "timeframe": timeframe, "total": 0,
            }

        counts, bin_edges = np.histogram(values, bins=n_bins)
        return {
            "bins": [float(e) for e in bin_edges],
            "counts": [int(c) for c in counts],
            "column": column,
            "symbol": symbol,
            "timeframe": timeframe,
            "total": len(values),
        }

    # ------------------------------------------------------------------
    # Metadaten
    # ------------------------------------------------------------------
    def get_available_features(
        self, symbol: str, timeframe: str
    ) -> Dict[str, Any]:
        """Verfuegbare Plugin-IDs, native Spalten und Zeilenzahl."""
        return self.reader.get_available_features(symbol, timeframe)

    def available_heatmap_metrics(self) -> List[str]:
        """Vertraglich unterstuetzte Heatmap-Metriken (fuer UI-Dropdowns)."""
        return list(HEATMAP_METRICS)

    @property
    def native_columns(self) -> List[str]:
        """Native Feature-Spalten (fuer Scatter-/Verteilungs-Dropdowns)."""
        return list(NATIVE_COLUMNS)
