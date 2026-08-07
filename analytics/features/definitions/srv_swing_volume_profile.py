# analytics/features/definitions/srv_swing_volume_profile.py
# ==============================================================================
# DEFINITION: srv_swing_volume_profile
# ==============================================================================
# NAME:        Swing Volume Profile Service
# KATEGORIE:   Swing Points/Volumen & Grid
# BESCHREIBUNG: Berechnet POC/VAH/VAL, LVN-Rejections, Grid-Proximity und Anchored VWAP
# ==============================================================================
"""
Service: SwingVolumeProfile (Phase 17.01) – Naming Convention 16.08.01: srv_

Berechnet POC/VAH/VAL, Low Volume Nodes (LVNs), Raster-Annäherungen
(Grid_Proximity) und Anchored VWAP Bänder. Reiner Datenlieferant fuer die
Analytics-UI und spaetere ML-Pipelines – KEINE Chart-Visualisierung in
diesem Kapitel (17.01, §1).

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt des tatsaechlichen Extremums (z. B.
                           Session_Start beim Anchored VWAP).
  * confirmation_bar_time: Zeitpunkt, an dem das Signal kausal feststand
                           (SESSION_CLOSE bei finalen Profilen).
  * confirmation_lag_bars: dynamische Differenz in Bars (Modus-Verzoegerung).
  * Profile am Serienanfang ohne ausreichenden Lookback erhalten
    calculation_status = 'INSUFFICIENT_DATA' bzw. 'MISSING_MTF_CONTEXT'.

Persistenz: feature_store_payload mit feature_id='srv_swing_volume_profile'
(Datenvertrag 17.01 §4, modus-spezifische Zusatzfelder §4.2). Seit 17.01
(E-1, PK-Migration) koennen mehrere Services konfliktfrei auf derselben
Kerze gespeichert werden.

Capabilities (E-5, 07.08.2026): chart=False, batch=True, live=False,
feature_store=True, render=False.
metadata['category'] = 'Swing Points/Volumen & Grid' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_SWING_VOLUME_PROFILE_SCHEMA` direkt unter diesem Header.
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
_SWING_VOLUME_PROFILE_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "Volume_Profile",
        "options": ["Volume_Profile", "Grid_Proximity", "Anchored_VWAP"],
        "description": "Haupt-Berechnungsmodus",
    },
    "profile_period": {
        "type": "str",
        "default": "Sessions",
        "options": ["Bars", "Sessions", "Days", "Weeks", "Months"],
        "description": "Profil-Zeitraum (nur aktiv bei mode == 'Volume_Profile')",
    },
    "period_val": {
        "type": "int", "default": 1, "min": 1,
        "description": "Multiplier für profile_period",
    },
    "volume_source": {
        "type": "str",
        "default": "tick_volume",
        "options": ["tick_volume", "real_volume"],
        "description": "Volumenquelle aus MT5 (standardmäßig tick_volume)",
    },
    "volume_thresh_pct": {
        "type": "float", "default": 5.0, "min": 0.5,
        "description": "Mindestvolumenanteil in % für Cluster",
    },
    "value_area_pct": {
        "type": "float", "default": 0.70, "min": 0.1, "max": 1.0,
        "description": "Value Area Abdeckung (0.70 = 70%)",
    },
    "lvn_sensitivity": {
        "type": "float", "default": 0.20, "min": 0.05,
        "description": "Schwellwert für Low Volume Nodes",
    },
    "grid_step": {
        "type": "float", "default": 0.5, "min": 0.01,
        "description": "Rasterabstand (nur bei mode == 'Grid_Proximity')",
    },
    "vwap_anchor": {
        "type": "str",
        "default": "Session_Start",
        "options": ["Session_Start", "Week_Start", "Month_Start"],
        "description": "Ankerpunkt (nur bei mode == 'Anchored_VWAP')",
    },
    "vwap_band_mult": {
        "type": "float", "default": 2.0, "min": 0.1,
        "description": "StDev-Multiplikator für VWAP-Bänder",
    },
}


class SrvSwingVolumeProfile(PluginFeature):
    """Volumen-, Grid- & VWAP-Swings.

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) – keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_swing_volume_profile"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Swing Points/Volumen & Grid",
            "display_name": "Swing Volume Profile Service",
            "description": "Volumengewichtetes Profil mit POC/VAH/VAL, LVNs, Grid & Anchored VWAP",
            "author": "PyTrader AI",
            "tags": ["swing", "volume", "profile", "lvn", "vwap", "grid"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) für "
                                "die Analytics-UI und ML-Pipelines. Berechnet "
                                "POC/VAH/VAL und Low Volume Nodes (LVNs) je "
                                "Profil, Raster-Annäherungen (Grid_Proximity) "
                                "und Anchored-VWAP-Bänder. Keine "
                                "Chart-Visualisierung in Kapitel 17.01.",
            "condition_rules": [
                "Volume_Profile: POC/VAH/VAL über value_area_pct, Cluster ab volume_thresh_pct, LVNs ab lvn_sensitivity",
                "Grid_Proximity: Abstand des Preises zum naechsten Rasterlevel (grid_step)",
                "Anchored_VWAP: VWAP ab Session/Week/Month_Start ± vwap_band_mult × StDev",
                "volume_source: tick_volume (Standard) oder real_volume",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA/MISSING_MTF_CONTEXT",
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
        return list(_SWING_VOLUME_PROFILE_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Haupt-Berechnungsmodus",
            "profile_period": "Profil-Zeitraum (Volume_Profile)",
            "period_val": "Multiplier (Profil-Zeitraum)",
            "volume_source": "Volumenquelle",
            "volume_thresh_pct": "Mindestvolumenanteil % (Cluster)",
            "value_area_pct": "Value Area Abdeckung",
            "lvn_sensitivity": "LVN-Schwellwert",
            "grid_step": "Rasterabstand (Grid_Proximity)",
            "vwap_anchor": "VWAP-Ankerpunkt",
            "vwap_band_mult": "VWAP-Band-Multiplikator",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_SWING_VOLUME_PROFILE_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _SWING_VOLUME_PROFILE_SCHEMA.items()}

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Volume-Profile/Grid/VWAP-Swings.

        Kapitel 17.01 etabliert Architektur, Datenvertrag (§4, modus-
        spezifische Felder §4.2) und kausale Zeitstempel (§2.4). Die
        konkreten Algorithmen (je Modus) werden nach statistischer
        Validierung der Feature-Store-Grundlage umgesetzt. Dieser Scaffold
        validiert die Parameter und liefert einen strukturell korrekten
        feature_store_payload (schema_version-Pflichtfeld, E-7) mit leerem
        Record-Satz – store_plugin_payload() persistiert dann 0 Zeilen.
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
