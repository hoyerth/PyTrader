"""
analytics/ui/heatmap_widget_constants.py - Modul-Konstanten der HeatmapWidget-Engine

23.09 God-File-Split (15.08.2026): Aus analytics/ui/heatmap_widget.py
ausgelagert, KEINE Logik-Aenderung. Die Hauptdatei re-exportiert alle Namen,
damit __init__ (_CONFLUENCE_COLORS, _CONFLUENCE_POS, _VIRIDIS, _DIM_LABELS,
_AGG_LABELS) und die Mixin-Methoden sie ohne Zirkularimport nutzen koennen.
"""

# E7: Konfluenz-Farbskala (0 = grau, 1-2 = gelb/cyan, 3-4 = orange,
# 5+ = dunkelrot) – Positionen 0..1 (Levels 0..5).
# 21.01 (Bugfix 2, 11.08.2026): 0 = HELLGRAU statt Weiss – weisse
# 0-Treffer-Zellen waren auf dem weissen Plot-Hintergrund unsichtbar.
_CONFLUENCE_COLORS = [
    "#d9d9d9", "#ffff00", "#00ffff", "#ff8c00", "#ff6600", "#8b0000",
]
_CONFLUENCE_POS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
_CONFLUENCE_LEVELS = (0.0, 5.0)
_VIRIDIS = "viridis"

# E6: Wert-Aggregationen benoetigen einen numerischen feature_data-JSON-Key.
_VALUE_AGGS = ("avg", "sum", "min", "max")

# 13.08.2026 (Punkt 5, F5): Preisartige feature_data-Keys - SUM ueber
# Preise erzeugt unsinnig hohe Legendenwerte (z. B. SILVER ~43k/Tag bei
# 5-Min-Summen) und wird fuer diese Felder deaktiviert. Signal-Felder
# (strength_value) bleiben erlaubt. Abgleich mit den Output-Schemata der
# srv_*-Plugins (price, reference_price, poc_price, vah_price, val_price,
# lvn_price, grid_price, vwap_price, vwap_lower, atr_value, lower_band,
# lower_level, prox_level1..6).
_PRICE_LIKE_KEY_HINTS = (
    "price",      # Preisfelder (price, *price, reference_price)
    "vwap_lower",  # VWAP-Band-Unterkante
    "atr_value",  # ATR-Magnitude (Punkte)
    "band",       # lower_band (Trend-Breakout)
    "level",      # lower_level / prox_level* (Grid-Level)
)



# Tag in Sekunden (Wanduhr-Epoch-Basis fuer date-Achse).
_DAY_SECONDS = 86400
_HALF_DAY = 43200.0
# 20.02.01 (E1): Stufen-Schwellen des Datums-Formatters (Monat/Jahr).
_MONTH_SECONDS = 2_592_000
_YEAR_SECONDS = 31_536_000
# 21.01 (Bugfix 5, 11.08.2026): Timeframe -> Sekunden fuer das adaptive
# Candle-Overlay (OHLCV im Original-TF statt Tages-Aggregation).
_TF_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800,
}

# 20.02.01 (User-Meldung 2): LWC-v5-adaptierte Datums-Skala.
# Zielabstand zwischen zwei Tick-Labels in Pixel (Lightweight Charts:
# 5*(fontSize+4)/8 * (tickMarkMaxCharacterLength || 8) mit fontSize 12 =>
# 5*16/8*8 = 80 px). Die Tick-Auswahl haelt diesen Abstand ein: Zoom-In
# => feinere Variante, Zoom-Out => groebere Variante (keine Ueberlappung,
# keine Riesensprünge). Weight-Hierarchie wie LWC v5:
#   70 = Jahreswechsel, 60 = Monatswechsel, 55 = Wochenanfang Mo,
#   50 = Tageswechsel, 30 = Stundenmarke, 20 = Minutenmarke.
# 21.01 (Bugfix 4): Die LABELS folgen seitdem 1:1 der App-JS
# (TT.MM.JJ fuer Tages-Marken, HH:MM fuer Sub-Tag-Marken) - die alte
# 5-Format-Beschriftung ('2026'/'Feb 26'/'08.25'/'Di. 03.02.26') ist
# ersetzt, weil sie von der Chartfenster-Anzeige abwich.
_DATE_TARGET_PX = 80.0
_MONTHS_SHORT = ("Jan", "Feb", "Mrz", "Apr", "Mai", "Jun",
                 "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")

_DIM_LABELS = {
    "date": "Datum",
    "dow": "Wochentag",
    # 20.02.01 (E2): "Stunde" -> "Tageszeit" (feste Skala 00:00-23:59, E3).
    "hour": "Tageszeit",
    "timeframe": "Timeframe",
    "service_id": "Service",
    "symbol": "Symbol",
}
_AGG_LABELS = {
    "count": "Anzahl (COUNT)",
    "confluence_count": "Konfluenz (COUNT DISTINCT)",
    "avg": "Mittelwert (AVG)",
    "sum": "Summe (SUM)",
    "min": "Minimum (MIN)",
    "max": "Maximum (MAX)",
}
