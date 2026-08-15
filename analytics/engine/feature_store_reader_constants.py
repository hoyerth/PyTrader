"""
analytics/engine/feature_store_reader_constants.py - Konstanten + canonical_tf_sort

23.05 God-File-Split (15.08.2026): Aus analytics/engine/feature_store_reader.py
ausgelagert, KEINE Logik-Aenderung. Die Hauptdatei re-exportiert alle Namen,
damit externe Importe (TF_SECONDS, DOW_LABELS, ...) unveraendert funktionieren.
canonical_tf_sort steht hier, weil er von Mixin-Methoden (fetch_service_tf_status,
get_available_timeframes) genutzt wird und sonst einen Zirkularimport erzeugen
wuerde (feature_store_reader importiert die Mixins).
"""

from pathlib import Path
from typing import List

# Projekt-Root = 2 Ebenen ueber dieser Datei (engine/ -> analytics/ -> Root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")
# 20.02 (E9, Candle-Overlay): OHLCV-Quelle fuer den Preis-Strip – read-only
# via DbPool, analog FeatureBuilder.load_ohlcv() (Spalten time/open/high/
# low/close/tick_volume).
DB_MARKET = str(BASE_DIR / "data" / "market_data.duckdb")

# E-3 (Phase 15.04, harmonisiert): schema_version-Default fuer Alt-Rows ohne
# Pflichtfeld. 15.04 vereinheitlicht den Default auf "1.0.0" (dreistellig,
# Semantic Versioning major.minor.patch) – identisch zum Plugin-Vertrag
# (srv_grid_lines/srv_proximity/metadata) und zur base_plugin-Spezifikation.
# Zuvor stand hier "1.0" (zweistellig) – Reader-Default und Plugin-Vertrag
# sind seit 15.04 deckungsgleich.
SCHEMA_VERSION_DEFAULT = "1.0.0"

# 17.01 (E-1, 07.08.2026): Sentinel feature_id fuer native Feature-Builder-Rows
# (ohne Plugin). Seit der PK-Migration (symbol, timeframe, bar_time,
# feature_id) tragen sie feature_id='native' und werden in allen UI-Listen
# (feature_ids / letzte Ausfuehrung) ausgeblendet.
SENTINEL_NATIVE = "native"

# 19.02 (Cleanup): NATIVE_COLUMNS ENTFERNT – die Legacy-Spalten ema_diff/
# rsi_14/atr_normalized existieren nicht mehr im Neuschema. Achsen und
# Metriken (Scatter/Verteilung/Heatmap) werden rein dynamisch aus den
# feature_data-JSON-Keys abgeleitet (available_feature_keys()).

# Heatmap-Achsen (15.03-Spezifikation): X = Wochentage, Y = Tagesstunden
# Berlin Wanduhr. Matrix: rows = Stunde (0-23), cols = DOW (0=Sonntag..6).
DOW_LABELS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"]
# 20.02.01 (E5): Wochentag-Skala strikt Montag-Freitag (DuckDB Mo=1..Fr=5).
DOW_WEEK_LABELS = ("Mo", "Di", "Mi", "Do", "Fr")
HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7

# 20.02 (Generische 2D-Heatmap-Engine, Kapitel 20.02 §2 / Review E4-E6):
# DIM_MAPPINGS – Whitelist fuer die SQL-Dimensionen von fetch_generic_heatmap().
# Wanduhr-Garantie (Invariante 7): dow/hour/date nutzen die
# UTC-Forcierung `bar_time AT TIME ZONE 'UTC'` (die gespeicherten Werte sind
# Wanduhr-encoded; die UTC-Darstellung IST die Wanduhr-Zeit). E4: `date` wird
# WIE dow/hour mit der UTC-Forcierung extrahiert – das Kapitel-Literal
# `CAST(bar_time AS DATE)` waere DST-fragil (Session-TZ Berlin +1/+2h).
# 20.02.01 (E6): `dow_hour` ist ersatzlos entfernt (Kapitel-Vorgabe) – die
# Kombination ist ueber die Dimensionen `dow` (Mo-Fr) und `hour` (Tageszeit)
# abbildbar; Alt-Profil-/Workspace-Werte werden im ViewModel per Sanitizer
# auf "hour" abgebildet.
DIM_MAPPINGS = {
    "date": "CAST(bar_time AT TIME ZONE 'UTC' AS DATE)",
    "dow": "EXTRACT(DOW FROM bar_time AT TIME ZONE 'UTC')::INTEGER",
    "hour": "EXTRACT(HOUR FROM bar_time AT TIME ZONE 'UTC')::INTEGER",
    "timeframe": "LOWER(timeframe)",
    # 21.03.20-Bugfix 3: Die Service-Achse splittet je
    # (feature_id, source_mode)-Kombination - ein Multi-Modus-Service
    # (z. B. Swing Momentum mit 3 Modi) belegt bei \"alle Modi\" drei
    # Achsenpunkte. Services ohne source_mode erhalten den leeren
    # Modus-Suffix (\"srv_x::\"); das Widget/VM-Resolver zeigt nur bei
    # nicht-leerem Modus \"Service / Modus\" an. Der Modus-Filter
    # (service_mode) schraenkt die Rows VOR der Aggregation ein -
    # bei konkretem Modus bleibt genau ein Achsenpunkt je Service.
    "service_id": (
        "LOWER(feature_id) || '::' || COALESCE("
        "json_extract_string(feature_data, '$.source_mode'), '')"
    ),
    "symbol": "LOWER(symbol)",
}

# 20.02: Verfuegbare Dimensionen / Aggregationen (UI-Combos, E1/E5).
# 20.02.01 (E6): `dow_hour` entfernt.
HEATMAP_DIMENSIONS = (
    "date", "dow", "hour", "timeframe", "service_id", "symbol",
)
HEATMAP_AGGREGATIONS = (
    "count", "confluence_count", "avg", "sum", "min", "max",
)

# 20.02 (Luecke 5.3-5): Defensiver Pivot-Deckel – die dichte Matrix wird
# begrenzt (date×dow_hour waere 366×168 = 61.488 Zellen).
MAX_HEATMAP_CELLS = 50_000

# 20.02 (E9): Default-Lookback des OHLCV-Snapshots fuer das Candle-Overlay
# (analog DEFAULT_LIMIT 5000 der Analytics-Tabelle; M1 ≈ 3,5 Tage).
OHLCV_SNAPSHOT_LIMIT = 5000

# 20.02-Bugfix (09.08.2026, Punkt 2/User-Meldung): Der kuenstliche
# Limit-Lookback (5000) schnitt die Heatmap-Daten ab (sichtbar waren nur die
# letzten ~4 Tage bei M1). Die generische Heatmap laedt seither ALLE
# verfuegbaren Daten (limit=None, Pivot-Deckel MAX_HEATMAP_CELLS begrenzt die
# Matrix). Das Candle-Overlay aggregiert Tages-Ohlc SQL-seitig ueber bis zu
# DAILY_OHLC_MAX_DAYS Tage (deckt den gesamten Heatmap-Zeitraum ab).
DAILY_OHLC_MAX_DAYS = 4000

# 21.03.12 (MTF-FC auf Analytics, Entscheidung 6a): Aggregations-TF ->
# Bucket-Sekunden fuer das date-Raster der generischen Heatmap (`agg_tf`
# fixiert auf einen konkreten TF, z. B. 'M15'/'H1'). 'auto' bedeutet KEIN
# Bucketing (Granularitaet dynamisch, bisheriges Verhalten).
TF_SECONDS = {
    "M1": 60, "M2": 120, "M5": 300, "M10": 600, "M15": 900,
    "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400,
    "W1": 604800, "MN1": 2592000,
}

# 13.08.2026 (Punkt 3, F3): Kanonische TF-Reihenfolge (fein -> grob) fuer
# Pill-Strips (TfStatusBadgeBar), TF-Dropdowns und Verfuegbarkeitslisten.
# Reihenfolge entspricht der broker-ueblichen Skala M1..MN1 inkl. M2/M10
# (vorher lieferte `ORDER BY timeframe` die ALPHABETISCHE Reihenfolge:
# D1, H1, H4, M1, M10, M15, M30, M5, MN1, W1 - falsch im UI).
CANONICAL_TIMEFRAME_ORDER = [
    "M1", "M2", "M5", "M10", "M15", "M30",
    "H1", "H4", "D1", "W1", "MN1",
]


def canonical_tf_sort(tfs) -> List[str]:
    """Sortiert Timeframe-Strings kanonisch fein -> grob (13.08.2026, F3).

    Bekannte TFs folgen CANONICAL_TIMEFRAME_ORDER; unbekannte TFs
    (z. B. neue Broker-TFs) landen deterministisch am Ende. Defensiv
    gegen None/leer (ruft beide Stellen: fetch_service_tf_status und
    get_available_timeframes).
    """
    order = {tf: i for i, tf in enumerate(CANONICAL_TIMEFRAME_ORDER)}
    return sorted(
        (str(t).strip().upper() for t in (tfs or [])
         if t is not None and str(t).strip()),
        key=lambda tf: (order.get(tf, 10 ** 6), tf),
    )

