# analytics/features/definitions/srv_swing_momentum.py
# ==============================================================================
# DEFINITION: srv_swing_momentum
# ==============================================================================
# NAME:        Swing Momentum Service
# KATEGORIE:   Swing Points/Dynamik & Filter
# BESCHREIBUNG: Wendepunkts-Erkennung über MA-Hysteresen, Steigungswechsel & Chande-Kroll
# ==============================================================================
"""
Service: SwingMomentum (Phase 17.01) – Naming Convention 16.08.01: srv_

Erfasst Richtungswechsel ueber Glättungs-Hysteresen (alle 12 MA-Typen des
MA-Templates 16.04), Steigungswechsel und Trailing-Stops (Chande Kroll).
Reiner Datenlieferant fuer die Analytics-UI und spaetere ML-Pipelines –
KEINE Chart-Visualisierung in diesem Kapitel (17.01, §1).

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt des tatsaechlichen Extremums.
  * confirmation_bar_time: Zeitpunkt, an dem das Signal kausal feststand.
  * confirmation_lag_bars: dynamische Differenz in Bars
                           (params['period'] bzw. Modus-Verzoegerung).
  * Kerzen am Serienanfang ohne ausreichenden Lookback/Lookahead erhalten
    calculation_status = 'INSUFFICIENT_DATA' und is_swing_* = False.

Persistenz: feature_store_payload mit feature_id='srv_swing_momentum'
(Datenvertrag 17.01 §4). Seit 17.01 (E-1, PK-Migration) koennen mehrere
Services konfliktfrei auf derselben Kerze gespeichert werden.

Capabilities (E-5, 07.08.2026): chart=False, batch=True, live=False,
feature_store=True, render=False.
metadata['category'] = 'Swing Points/Dynamik & Filter' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_SWING_MOMENTUM_SCHEMA` direkt unter diesem Header.
`parameter_schema` gibt eine flache Kopie zurueck (M1).
E-2 (07.08.2026): type-Werte als Strings.
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
# E-2 (07.08.2026): type-Werte als Strings.
# ---------------------------------------------------------------------------
_SWING_MOMENTUM_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "MA_Peak_Hysteresis",
        "options": [
            "MA_Peak_Hysteresis", "MA_Slope_Change", "Chande_Kroll_Ratchet",
        ],
        "description": "Algorithmus-Modus für Momentum-Swings",
    },
    "ma_type": {
        "type": "str",
        "default": "EHMA",
        "options": [
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA",
        ],
        "description": "Gleitender Durchschnittstyp (MA-Template 16.04)",
    },
    "period": {
        "type": "int", "default": 14, "min": 2,
        "description": "Berechnungsperiode für Glättungs-MA",
    },
    "piv_maxMaMovePct": {
        "type": "float", "default": 0.2, "min": 0.01,
        "description": "Erforderliche Gegenbewegung in % für MA Peak Pivot (gültig für alle ma_type-Optionen)",
    },
    "chande_lookback": {
        "type": "int", "default": 10, "min": 1,
        "description": "Lookback-Periode für Highest-High/Lowest-Low im Chande_Kroll_Ratchet Modus",
    },
    "x_atr": {
        "type": "float", "default": 3.0, "min": 0.5,
        "description": "ATR-Multiplikator für Chande Kroll Stops",
    },
}


class SrvSwingMomentum(PluginFeature):
    """Dynamik- & MA-Hysterese-Swings.

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) – keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_swing_momentum"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Swing Points/Dynamik & Filter",
            "display_name": "Swing Momentum Service",
            "description": "Dynamische Momentum-Swings via MA-Hysterese, Steigung & Chande Kroll",
            "author": "PyTrader AI",
            "tags": ["swing", "momentum", "ma", "hysteresis", "chande-kroll"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) für "
                                "die Analytics-UI und ML-Pipelines. Erkennt "
                                "Richtungswechsel über MA-Peak-Hysterese (alle "
                                "12 MA-Typen des Templates 16.04), "
                                "MA-Steigungswechsel und Chande-Kroll-Ratchet "
                                "(ATR-Stopps). Keine Chart-Visualisierung in "
                                "Kapitel 17.01.",
            "condition_rules": [
                "MA_Peak_Hysteresis: Pivot erst bei Gegenbewegung >= piv_maxMaMovePct %",
                "MA_Slope_Change: Richtungswechsel der MA-Steigung (Vorzeichen des Differentials)",
                "Chande_Kroll_Ratchet: Stopps = Highest-High/Lowest-Low über chande_lookback ± x_atr × ATR",
                "alle 12 MA-Typen: SMA/EMA/WMA/DEMA/TEMA/HMA/EHMA/ZLEMA/RMA/KAMA/ALMA/VWMA",
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
        return list(_SWING_MOMENTUM_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Algorithmus-Modus",
            "ma_type": "Gleitender Durchschnittstyp",
            "period": "Berechnungsperiode",
            "piv_maxMaMovePct": "Gegenbewegung % (MA Peak Pivot)",
            "chande_lookback": "Lookback (Chande Kroll)",
            "x_atr": "ATR-Multiplikator (Chande Kroll Stops)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_SWING_MOMENTUM_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _SWING_MOMENTUM_SCHEMA.items()}

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Momentum-Swings (MA-Hysterese, Steigung, Chande Kroll).

        Kapitel 17.01 etabliert Architektur, Datenvertrag (§4) und kausale
        Zeitstempel (§2.4). Die konkreten Algorithmen (je Modus) werden nach
        statistischer Validierung der Feature-Store-Grundlage umgesetzt.
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
