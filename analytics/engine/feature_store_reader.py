# analytics/engine/feature_store_reader.py
"""
feature_store_reader.py - FeatureStoreReader (Phase 15.03).

Reiner Lese-Zugriff auf die `feature_store`-Tabelle in `analytics.duckdb`
(Invariante 4 / MVVM: DuckDB -> FeatureStoreReader -> AnalyticsRepository
-> ViewModel -> UI). Der Reader fuehrt KEINE Berechnungen aus und schreibt
NIE in die DB – er kapselt ausschliesslich lesende DuckDB-Abfragen.

Datenmodell feature_store (Hybrid-Schema, Phasen 12+; 19.02-Cleanup):
    symbol, timeframe, bar_time TIMESTAMPTZ, created_at, feature_id,
    plugin_version, feature_data JSON (FeatureStorePayload des Plugins)

19.02 (Cleanup): Die Legacy-Native-Spalten ema_diff/rsi_14/atr_normalized
sind entfernt. Scatter-/Verteilungs-/Heatmap-Achsen und Tabellen-Spalten
werden rein dynamisch aus den JSON-Keys von `feature_data` abgeleitet
(`available_feature_keys()`); es gibt KEINE nativen Spalten mehr.

Wanduhr-Garantie (Invariante 7, 15.03-Spez: Heatmap X/Y):
    Die gespeicherten bar_time-Werte sind Berlin-Wanduhr-encoded (MT5
    liefert Wanduhr-Epochs, die 1:1 als UTC-Darstellung in die DB
    geschrieben werden; EXTRACT('epoch' FROM bar_time) liefert exakt diese
    Wanduhr-Epochs). Fuer Wochentag/Stunde (Heatmap) wird DAHER die
    UTC-Forcierung `bar_time AT TIME ZONE 'UTC'` verwendet – OHNE sie
    rechnet DuckDB in die System-Lokalzeit um (Berlin +2h/+1h) und die
    Heatmap waere um den Offset verschoben (DST-bruchig, Invariante 7).

E-3 (schema_version-Pflichtfeld): Alte feature_store-Rows ohne
`schema_version` in feature_data erhalten beim Lesen den Default `"1.0.0"` –
die DB-Zeile bleibt unveraendert (Lesen ist rein).
"""

import os
import threading
import time
from datetime import datetime as _dt_datetime
from datetime import timezone as _dt_timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from db_service import DbPool, _parse_json_field
from analytics.engine.feature_store_reader_meta import FeatureStoreMetaMixin
from analytics.engine.feature_store_reader_filter import FeatureStoreFilterMixin
from analytics.engine.feature_store_reader_query import FeatureStoreQueryMixin
from analytics.engine.feature_store_reader_heatmap import FeatureStoreHeatmapMixin
from analytics.engine.feature_store_reader_ohlcv import FeatureStoreOhlcvMixin
from analytics.engine.feature_store_reader_plugin import FeatureStorePluginMixin

from analytics.engine.feature_store_reader_constants import (
    BASE_DIR,
    CANONICAL_TIMEFRAME_ORDER,
    DAILY_OHLC_MAX_DAYS,
    DAYS_PER_WEEK,
    DB_ANALYTICS,
    DB_MARKET,
    DIM_MAPPINGS,
    DOW_LABELS,
    DOW_WEEK_LABELS,
    HEATMAP_AGGREGATIONS,
    HEATMAP_DIMENSIONS,
    HOURS_PER_DAY,
    MAX_HEATMAP_CELLS,
    OHLCV_SNAPSHOT_LIMIT,
    SCHEMA_VERSION_DEFAULT,
    SENTINEL_NATIVE,
    TF_SECONDS,
    canonical_tf_sort,
)


class FeatureStoreReader(
    FeatureStoreMetaMixin, FeatureStoreFilterMixin, FeatureStoreQueryMixin,
    FeatureStoreHeatmapMixin, FeatureStoreOhlcvMixin, FeatureStorePluginMixin,
):
    """Kapselt rein lesend DuckDB-Abfragen auf den feature_store."""

    def __init__(self, db_path: str = DB_ANALYTICS) -> None:
        self.db_path = db_path
        # Runde 15 (Ultra-Low-Latency, Performance-Fix 3): In-Memory-Cache
        # der STABILEN Metadaten (feature_data-JSON-Keys je Service,
        # instance_hash-Fakten). Schlüssel = (symbol.lower(), timeframe.lower()).
        # Die Metadaten aendern sich nur bei store_plugin_payload()-Writes –
        # die bestehende `feature_cache_last_invalidated`-Mechanik
        # (feature_builder.py, Invariante 13) markiert solche Writes. Ohne
        # den Cache scannen `available_feature_keys`/`feature_keys_by_service`/
        # `available_instance_hashes`/`plugin_ids_with_hashes` den Store
        # mehrmals pro Update (bis zu 6 Voll-Scans -> Dropdown-Verzoegerung).
        # Thread-Lock, weil der Reader von Worker-Threads gemeinsam genutzt
        # wird (MVVM: ein Repository/Reader pro ViewModel).
        self._meta_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._meta_lock = threading.Lock()
