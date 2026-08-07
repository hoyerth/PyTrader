# analytics/features/definitions/srv_swing_structure.py
# ==============================================================================
# DEFINITION: srv_swing_structure
# ==============================================================================
# NAME:        Swing Structure Service
# KATEGORIE:   Swing Points/Geometrie
# BESCHREIBUNG: Extrahierte Swing Highs/Lows über Fraktale, Pivots, Gann & ZigZag
# ==============================================================================
"""
Service: SwingStructure (Phase 17.01) – Naming Convention 16.08.01: srv_

Erfasst lokale Extrema ueber Fraktale, Pivots, Gann Swings, Period Extrema
(PDH/PWH) und ZigZag. Reiner Datenlieferant fuer die Analytics-UI und
spaetere ML-Pipelines (XGBoost/LightGBM) – KEINE Chart-Visualisierung in
diesem Kapitel (17.01, §1); dedizierte Chart-Indikatoren (ind_...) folgen
erst nach statistischer Validierung der erzeugten Features.

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt (Epoch) des tatsaechlichen Extremums.
  * confirmation_bar_time: Zeitpunkt, an dem das Signal mathematisch/kausal
                           feststand (bar_time der aktuellen Kerze).
  * confirmation_lag_bars: dynamisch berechnete Differenz in Bars
                           (params['right_bars'] bzw. Modus-Verzoegerung).
  * Kerzen am Serienanfang ohne ausreichenden Lookback/Lookahead erhalten
    calculation_status = 'INSUFFICIENT_DATA' und is_swing_* = False.

Persistenz: feature_store_payload mit feature_id='srv_swing_structure'
(Datenvertrag 17.01 §4). Seit 17.01 (E-1, PK-Migration) koennen mehrere
Services konfliktfrei auf derselben Kerze gespeichert werden
(PK (symbol, timeframe, bar_time, feature_id)).

Capabilities (E-5, 07.08.2026): chart=False (kein Indikator in diesem
Kapitel), batch=True, live=False, feature_store=True, render=False.
metadata['category'] = 'Swing Points/Geometrie' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_SWING_STRUCTURE_SCHEMA` direkt unter diesem Header
(siehe dort) und sind wie in PineScript am Dateianfang anpassbar.
`parameter_schema` gibt eine flache Kopie zurueck (M1: kein geteiltes
mutable Dict ueber Instanzen).
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 17.01): Single Source of Truth fuer das
# Prop-Fenster. Inputs/Defaults stehen hier direkt am Dateianfang.
# `parameter_schema` gibt eine flache Kopie zurueck (M1).
# E-2 (07.08.2026): type-Werte als Strings ("int"/"float"/"str") – die
# Basisklasse (base_plugin.validate_params) vergleicht string-basiert.
# ---------------------------------------------------------------------------
_SWING_STRUCTURE_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "Williams_Fractal",
        "options": [
            "Williams_Fractal", "Standard_Pivot", "Gann_Mechanical",
            "ZigZag_ATR", "ZigZag_Pct", "Period_Extrema",
        ],
        "description": "Erkennungs-Modus für Strukturswings",
    },
    "left_bars": {
        "type": "int", "default": 2, "min": 1,
        "description": "Anzahl erforderlicher Kerzen links mit niedrigeren Hochs / höheren Tiefs",
    },
    "right_bars": {
        "type": "int", "default": 2, "min": 1,
        "description": "Anzahl Bestätigungskerzen rechts (bestimmt dynamisch confirmation_lag_bars)",
    },
    "atr_period": {
        "type": "int", "default": 14, "min": 1,
        "description": "ATR-Periode für ZigZag_ATR",
    },
    "atr_mult": {
        "type": "float", "default": 2.0, "min": 0.1,
        "description": "ATR-Multiplikator für ZigZag_ATR",
    },
    "change_pct": {
        "type": "float", "default": 0.5, "min": 0.05,
        "description": "Mindestprozentbewegung für ZigZag_Pct",
    },
    "period_extrema_type": {
        "type": "str",
        "default": "PREVIOUS_CLOSED",
        "options": ["PREVIOUS_CLOSED", "CURRENT_DEVELOPING"],
        "description": "PREVIOUS_CLOSED (z. B. PDH/PWH final) oder CURRENT_DEVELOPING",
    },
}


class SrvSwingStructure(PluginFeature):
    """Geometrische & Preis-Swings (Fraktale, Pivots, Gann, ZigZag).

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) – keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_swing_structure"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Swing Points/Geometrie",
            "display_name": "Swing Structure Service",
            "description": "Erfasst Fraktal-, Pivot-, Gann- und ZigZag-Extrema für die Struktur-Analyse",
            "author": "PyTrader AI",
            "tags": ["swing", "fractal", "pivot", "zigzag", "structure"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) für "
                                "die Analytics-UI und ML-Pipelines. Erkennt "
                                "lokale Extrema über Williams-Fraktale, "
                                "Standard-Pivots, Gann-Mechanik, ZigZag "
                                "(ATR/Prozent) und Period-Extrema (PDH/PWH). "
                                "Keine Chart-Visualisierung in Kapitel 17.01.",
            "condition_rules": [
                "Williams_Fractal: high[i] > high[i±k] / low[i] < low[i±k] für k in 1..left/right_bars",
                "Standard_Pivot: lokales Extremum mit links/rechts tieferen Hochs bzw. höheren Tiefs",
                "Gann_Mechanical: mechanische Swing-Bestätigung über links/rechts-Zählung",
                "ZigZag_ATR: Richtungswechsel erst bei |move| >= atr_mult × ATR(atr_period)",
                "ZigZag_Pct: Richtungswechsel erst bei |move| >= change_pct %",
                "Period_Extrema: PDH/PWH (PREVIOUS_CLOSED) bzw. laufende Periode (CURRENT_DEVELOPING)",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": False,   # E-5: kein Indikator in Kapitel 17.01
            "batch": True,
            "live": False,
            "feature_store": True,
            "render": False,  # E-5: reine Datenlieferanten
        }

    # --- Single Source of Truth fürs Prop-Fenster (17.01 §2.2, PineScript-Zone)
    @property
    def parameter_order(self) -> List[str]:
        return list(_SWING_STRUCTURE_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Erkennungs-Modus",
            "left_bars": "Kerzen links",
            "right_bars": "Kerzen rechts (Bestätigung)",
            "atr_period": "ATR-Periode (ZigZag_ATR)",
            "atr_mult": "ATR-Multiplikator (ZigZag_ATR)",
            "change_pct": "Mindestbewegung % (ZigZag_Pct)",
            "period_extrema_type": "Period-Extrema-Typ",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_SWING_STRUCTURE_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _SWING_STRUCTURE_SCHEMA.items()}

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Struktur-Swings (Fraktale/Pivots/Gann/ZigZag).

        Kapitel 17.01 etabliert Architektur, Datenvertrag (§4) und kausale
        Zeitstempel (§2.4). Die konkreten Swing-Algorithmen (je Modus) werden
        nach statistischer Validierung der Feature-Store-Grundlage umgesetzt.
        Dieser Scaffold validiert die Parameter und liefert einen strukturell
        korrekten feature_store_payload (schema_version-Pflichtfeld, E-7) mit
        leerem Record-Satz – store_plugin_payload() persistiert dann 0 Zeilen.
        """
        empty: FeatureCalculateResult = {"feature_store_payload": {}}
        if df is None or df.empty:
            return empty

        p = self.validate_params(params)
        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": [],
                "metadata": {
                    # E-7 / base_plugin (U15-A1, Invariante 5): schema_version
                    # ist Pflichtfeld fuer alle feature_store=True-Plugins.
                    "schema_version": "1.0.0",
                    "source_mode": p.get("mode"),
                },
            },
        }
