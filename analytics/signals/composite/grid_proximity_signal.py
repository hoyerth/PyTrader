# analytics/signals/composite/grid_proximity_signal.py
"""
Composite Signal: Grid Proximity Signal (Phase 11)
Verknuepft multidimensionale Features aus dem feature_store:
  - Y-Achse: grid_dist_pct (Preisabstand zum naechsten Grid-Level)
  - X-Achse: is_time_window_active (Zeitfenster-Filter)
  - Volatilitaet: atr_normalized / regime_volatility (Markt-Regime)

Signal-Logik:
  Buy  (confidence > 0.5): Preis nahe Grid-Level + aktives Zeitfenster + niedrige Vola
  Sell (confidence < -0.5): Preis fern von Grid-Level + aktives Zeitfenster + hohe Vola
  Neutral (confidence = 0.0): Zeitfenster geschlossen oder keine klare Signallage
"""

from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np
from analytics.engine.base_definition import SignalDefinition


class GridProximitySignal(SignalDefinition):
    """
    Composite Signal: Grid-Proximity mit multidimensionaler Verknuepfung.
    Nutzt feature_store-Spalten: grid_dist_pct, is_time_window_active,
    atr_normalized, regime_volatility.
    """

    @property
    def signal_id(self) -> str:
        return "grid_proximity_v1"

    @property
    def display_name(self) -> str:
        return "Grid Proximity (Composite)"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "proximity_threshold_pct": 0.1,       # max. Abstand in % zum Level fuer "nahe"
            "confidence_high": 0.8,                 # Confidence bei starkem Signal
            "confidence_low": 0.3,                  # Confidence bei schwachem Signal
            "vola_regime_threshold": 1.2,           # regime_volatility >= x = "hohe Vola"
            "atr_filter_enabled": True,             # ATR-Filter aktivieren
            "atr_percentile": 0.7,                  # ATR-Perzentil-Schwelle (0-1)
            "time_window_must": True,               # Nur Signale in aktiven Zeitfenstern
            "min_bars_since_pivot": 3,              # Mindestbars seit letztem Pivot-Hit
            "use_regime_filter": True,              # Regime-Filter aktivieren
        }

    @property
    def param_descriptions(self) -> Dict[str, str]:
        return {
            "proximity_threshold_pct": "Max. Abstand in % vom naechsten Grid-Level",
            "confidence_high": "Confidence bei starkem Signal (Level-Touch im Fenster)",
            "confidence_low": "Confidence bei schwachem Signal (Level-nahe, normale Vola)",
            "vola_regime_threshold": "Schwelle fuer 'hohe Volatilitaet' (regime_volatility)",
            "atr_filter_enabled": "ATR-Filter fuer Ausbruchsbestaetigung aktiv",
            "atr_percentile": "ATR-Perzentil-Schwelle (0-1)",
            "time_window_must": "Nur Signale in aktiven Zeitfenstern (is_time_window_active=1)",
            "min_bars_since_pivot": "Mindestbars seit letztem Pivot-Hit",
            "use_regime_filter": "Regime-Filter (Trend/Volatility) aktivieren",
        }

    @property
    def live_op(self) -> bool:
        return True  # Dynamisch: wird bei Chart-Aufruf aktualisiert

    @property
    def required_features(self) -> List[str]:
        return [
            "grid_dist_pct",
            "grid_nearest_level",
            "is_time_window_active",
            "atr_normalized",
            "regime_volatility",
            "regime_trend_score",
        ]

    def evaluate(
        self,
        df_features: pd.DataFrame,
        params: Optional[Dict[str, Any]] = None,
    ) -> pd.Series:
        """
        Berechnet Confidence-Score [0.0, 1.0] basierend auf Grid-Proximity.

        Args:
            df_features: DataFrame mit Feature-Spalten aus feature_store.
                         Benoetigt: grid_dist_pct, is_time_window_active,
                         atr_normalized, regime_volatility, regime_trend_score
            params: Ueberschreibt default_params

        Returns:
            pd.Series mit Confidence-Werten [0.0, 1.0]
        """
        p = {**self.default_params, **(params or {})}
        prox_threshold = float(p["proximity_threshold_pct"])
        conf_high = float(p["confidence_high"])
        conf_low = float(p["confidence_low"])
        vola_thresh = float(p["vola_regime_threshold"])
        atr_enabled = bool(p["atr_filter_enabled"])
        atr_pctile = float(p["atr_percentile"])
        time_must = bool(p["time_window_must"])
        min_bars = int(p["min_bars_since_pivot"])
        use_regime = bool(p["use_regime_filter"])

        n = len(df_features)
        confidence = np.zeros(n, dtype=float)

        if n < 2:
            return pd.Series(confidence, index=df_features.index)

        # --- Feature-Spalten extrahieren (mit Fallback auf NaN) ---
        dist_pct = df_features.get("grid_dist_pct", pd.Series(np.nan, index=df_features.index)).values.astype(float)
        nearest_level = df_features.get("grid_nearest_level", pd.Series(np.nan, index=df_features.index)).values.astype(float)
        time_active = df_features.get("is_time_window_active", pd.Series(1, index=df_features.index)).values.astype(int)
        atr_norm = df_features.get("atr_normalized", pd.Series(np.nan, index=df_features.index)).values.astype(float)
        regime_vol = df_features.get("regime_volatility", pd.Series(1.0, index=df_features.index)).values.astype(float)
        regime_score = df_features.get("regime_trend_score", pd.Series(0.0, index=df_features.index)).values.astype(float)

        # close fuer Level-Berechnung (Fallback wenn keine grid_dist_pct)
        close = df_features.get("close", pd.Series(np.nan, index=df_features.index)).values.astype(float)

        # --- Hilfsvektoren ---
        # Ist das Zeitfenster aktiv?
        window_ok = time_active == 1 if time_must else np.ones(n, dtype=bool)

        # Ist der Preis nahe einem Grid-Level?
        # dist_pct < threshold bedeutet "nahe dran"
        # NaN-Werte als "nicht nahe" behandeln
        is_near = np.where(np.isfinite(dist_pct), dist_pct < prox_threshold, False)

        # Ist der Preis genau AUF einem Level? (dist_pct extrem klein)
        is_on_level = np.where(np.isfinite(dist_pct), dist_pct < prox_threshold * 0.1, False)

        # Volatilitaets-Regime
        low_vola = np.where(np.isfinite(regime_vol), regime_vol < vola_thresh, True)
        high_vola = np.where(np.isfinite(regime_vol), regime_vol >= vola_thresh, False)

        # ATR-Perzentil (dynamische Schwelle)
        if atr_enabled:
            atr_valid = atr_norm[np.isfinite(atr_norm)]
            if len(atr_valid) > 10:
                atr_threshold = np.percentile(atr_valid, atr_pctile * 100)
                atr_high = atr_norm >= atr_threshold
                atr_low = atr_norm < atr_threshold
            else:
                atr_high = np.zeros(n, dtype=bool)
                atr_low = np.ones(n, dtype=bool)
        else:
            atr_high = np.ones(n, dtype=bool)
            atr_low = np.ones(n, dtype=bool)

        # --- Signallogik vektorisiert ---
        for i in range(n):
            if not window_ok[i]:
                # Zeitfenster geschlossen -> neutral
                confidence[i] = 0.0
                continue

            if np.isnan(dist_pct[i]) or np.isnan(nearest_level[i]):
                # Keine Grid-Daten verfuegbar -> neutral
                confidence[i] = 0.0
                continue

            # === Starkes Signal: Level-Touch (direkt auf Level) ===
            if is_on_level[i]:
                if use_regime and regime_score[i] > 0.3:
                    # Level-Touch im Aufwaertstrend -> Bestaetigung
                    confidence[i] = conf_high * 1.0
                elif use_regime and regime_score[i] < -0.3:
                    # Level-Touch im Abwaertstrend -> Abschwaechung
                    confidence[i] = conf_high * 0.7
                else:
                    # Neutraler Trend -> mittel
                    confidence[i] = conf_high * 0.85

                # Vola-Boost: Level-Touch mit hoher Vola = staerkeres Signal
                if high_vola[i] and atr_high[i]:
                    confidence[i] = min(1.0, confidence[i] * 1.2)

            # === Mittleres Signal: Preis nahe Level ===
            elif is_near[i]:
                base = conf_low
                # Vola-Boost: Bei niedriger Vola ist Level-Naehe relevanter
                if low_vola[i]:
                    base *= 1.3
                # Trend-Boost: In Trendrichtung
                if use_regime and regime_score[i] > 0.3:
                    base *= 1.2
                confidence[i] = min(conf_high, base)

            # === Schwaches Signal: Weit weg vom Level ===
            else:
                # Nur wenn Regime stark genug fuer "Ablehnung"
                if use_regime and abs(regime_score[i]) > 0.6:
                    confidence[i] = 0.1  # Sehr niedrig, aber nicht 0
                else:
                    confidence[i] = 0.0

        # --- Glatttung: min_bars_since_pivot ---
        # Nach einem starken Signal (confidence > 0.5) keine neuen Signale
        # fuer min_bars Bars
        if min_bars > 0:
            for i in range(1, n):
                lookback_start = max(0, i - min_bars)
                lookback = confidence[lookback_start:i]
                if np.any(lookback > 0.5):
                    # Nur ueberschreiben wenn aktuelles Signal schwaecher
                    if confidence[i] > 0.0 and confidence[i] < 0.5:
                        confidence[i] = 0.0

        return pd.Series(confidence, index=df_features.index)
