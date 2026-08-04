# analytics/engine/analytics_worker.py
"""
analytics_worker.py - AnalyticsAsyncWorker (Phase 15.03 Schritt 4).

Asynchroner DuckDB-Query-Worker (QThread) fuer die Analytics-UI.

Entkopplung (Invariante 4 / MVVM):
    DuckDB -> FeatureStoreReader/AnalyticsRepository -> AnalyticsAsyncWorker
    -> AnalyticsViewModel -> UI-Pages

Der Worker fuehrt EINE einzelne Datenabfrage (Tabelle, Heatmap, Scatter,
Verteilung, Metadaten) in einem separaten QThread aus, damit die GUI nicht
blockiert (Analogie: ServiceSetRunWorker / LiveAnalyzer). Die DB-Zugriffe
laufen ueber `AnalyticsRepository`/`FeatureStoreReader` – beide nutzen den
Thread-local `DbPool` (eine Connection pro Thread & DB-Datei,
Thread-Safety-Invariante 6); der Worker-Thread erhaelt dadurch automatisch
seine eigene Connection und blockiert nie den App-Hauptthread.

Max-Lookback-Cap (15.03-Spezifikation): `MAX_LOOKBACK_LIMIT = 50_000`
deckelt alle limit-Parameter hart nach oben – gegen SQL-Feuer / UI-Freeze.

Signale (werden vom Worker-Thread emittiert; Qt stellt die Queued
Connection zum ViewModel im Hauptthread her):
    finished_ok = Signal(str, dict)   – query_kind, Ergebnis-Dict
    failed      = Signal(str, str)    – query_kind, Fehlermeldung

Der Worker ist EINWEG (eine Abfrage pro Instanz). Das ViewModel erzeugt pro
Abfrage eine neue Instanz; die Qt-Elternschaft (parent) haelt die Instanz
am Leben und `worker.finished.connect(worker.deleteLater)` raeumt auf.

Abfrage-Typen (query_kind, Single Source of Truth fuer Worker & ViewModel):
    QUERY_TABLE        – rohe Feature-Zeilen (Tabellen-Seite)
    QUERY_HEATMAP      – 2D-Matrix Wochentag x Tagesstunde (Berlin Wanduhr)
    QUERY_SCATTER      – X/Y-Paare zweier nativer Spalten
    QUERY_DISTRIBUTION – Histogramm (bins/counts)
    QUERY_FEATURES     – Metadaten (Plugin-IDs, Spalten, Zeilenzahl)
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import QThread, Signal

# Abfrage-Typen (query_kind).
QUERY_TABLE = "table"
QUERY_HEATMAP = "heatmap"
QUERY_SCATTER = "scatter"
QUERY_DISTRIBUTION = "distribution"
QUERY_FEATURES = "features"

# Max-Lookback-Cap (15.03-Spezifikation): Keine Abfrage darf mehr als
# 50.000 Zeilen anfordern.
MAX_LOOKBACK_LIMIT = 50_000


def cap_lookback_limit(value: Optional[int]) -> Optional[int]:
    """Deckelt einen limit-Wert hart auf MAX_LOOKBACK_LIMIT.

    None (Repo-Default) bleibt None; ungueltige Werte -> None.
    """
    if value is None:
        return None
    try:
        return max(1, min(int(value), MAX_LOOKBACK_LIMIT))
    except (TypeError, ValueError):
        return None


class AnalyticsAsyncWorker(QThread):
    """Fuehrt eine einzelne Analytics-Datenabfrage im Hintergrund aus.

    EINWEG-Worker: Eine Abfrage pro Instanz. Das ViewModel erzeugt bei
    Bedarf neue Instanzen und verbindet finished_ok/failed.
    """

    finished_ok = Signal(str, dict)  # query_kind, Ergebnis-Dict
    failed = Signal(str, str)        # query_kind, Fehlermeldung

    def __init__(
        self,
        repository: Any,
        query_kind: str,
        params: Optional[Dict[str, Any]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._query_kind = query_kind
        self._params = dict(params or {})
        self._cancelled = False

    def cancel(self) -> None:
        """Bricht die Abfrage ab (Ergebnis-Signale werden unterdrueckt)."""
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        if self._cancelled:
            return
        try:
            result = self._execute()
        except Exception as e:
            if not self._cancelled:
                self.failed.emit(self._query_kind, str(e))
            return
        if not self._cancelled:
            self.finished_ok.emit(self._query_kind, result)

    # ------------------------------------------------------------------
    # Dispatch auf die Repository-Methoden (lesend, kein SQL hier)
    # ------------------------------------------------------------------
    def _execute(self) -> Dict[str, Any]:
        repo = self._repository
        p = self._params
        symbol = str(p.get("symbol", "") or "")
        timeframe = str(p.get("timeframe", "") or "")
        feature_id = p.get("feature_id")

        if self._query_kind == QUERY_TABLE:
            return repo.get_table(
                symbol, timeframe,
                feature_id=feature_id,
                limit=cap_lookback_limit(p.get("limit")),
            )
        if self._query_kind == QUERY_HEATMAP:
            return repo.get_heatmap(
                symbol, timeframe,
                metric=str(p.get("metric", "count") or "count"),
                feature_id=feature_id,
            )
        if self._query_kind == QUERY_SCATTER:
            return repo.get_scatter(
                symbol, timeframe,
                x_column=str(p.get("x_column", "ema_diff") or "ema_diff"),
                y_column=str(p.get("y_column", "rsi_14") or "rsi_14"),
                feature_id=feature_id,
                limit=cap_lookback_limit(p.get("limit")),
            )
        if self._query_kind == QUERY_DISTRIBUTION:
            return repo.get_distribution(
                symbol, timeframe,
                column=str(p.get("column", "atr_normalized") or "atr_normalized"),
                bins=p.get("bins", 20),
                feature_id=feature_id,
                limit=cap_lookback_limit(p.get("limit")),
            )
        if self._query_kind == QUERY_FEATURES:
            return repo.get_available_features(symbol, timeframe)

        raise ValueError(
            f"[AnalyticsAsyncWorker] Unbekannte Abfrage '{self._query_kind}' – "
            f"erlaubt: {QUERY_TABLE}, {QUERY_HEATMAP}, {QUERY_SCATTER}, "
            f"{QUERY_DISTRIBUTION}, {QUERY_FEATURES}."
        )
