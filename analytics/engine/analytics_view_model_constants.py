"""
analytics/engine/analytics_view_model_constants.py - Modul-Konstanten des AnalyticsViewModel

23.07 God-File-Split (15.08.2026): Aus analytics/engine/analytics_view_model.py
ausgelagert, KEINE Logik-Aenderung. Die Hauptdatei re-exportiert alle Namen,
damit die Mixins UND __init__ (DEBOUNCE_MS/DEFAULT_BINS/DEFAULT_LIMIT) und
set_data_tf (_ALL_QUERIES) sie ohne Zirkularimport nutzen koennen.
"""

from analytics.engine.analytics_worker import (
    QUERY_TABLE,
    QUERY_HEATMAP,
    QUERY_HEATMAP_GENERIC,
    QUERY_SCATTER,
    QUERY_DISTRIBUTION,
    QUERY_FEATURES,
)

# QTimer-Debounce (15.03-Spezifikation: 200-300 ms) gegen SQL-Feuer.
DEBOUNCE_MS = 250

# Default-Parameter (Anfangs-Parametrisierung der Analytics-Ansichten).
DEFAULT_BINS = 20
DEFAULT_LIMIT = 5000

# 21.03.12 (MTF-FC auf Analytics): Alle Haupt-Queries, die beim data_tf-
# Wechsel neu angestossen werden (OHLCV/DAILY_OHLC sind on-demand und
# folgen keinem Filterwechsel - identisch zur refresh_all()-Liste).
_ALL_QUERIES = (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                QUERY_SCATTER, QUERY_DISTRIBUTION, QUERY_FEATURES)
