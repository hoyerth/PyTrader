# analytics/features/feature_builder.py
"""
Feature Builder – Lädt OHLCV aus market_data.duckdb, berechnet Basis-Features
(ema_diff, atr_normalized) vektorisiert und schreibt sie per Bulk-Upsert in
analytics.duckdb.

Stabiler Basis-Stand ohne Phase-2.1-Zeitkontext-Erweiterungen.
"""

from typing import Dict, List, Optional
import pandas as pd
from pathlib import Path

from analytics.features.base_feature import BaseFeature
from analytics.features.definitions.ema_diff import EMADiffFeature
from analytics.features.definitions.atr_normalized import ATRNormalizedFeature
from state_manager import StateManager
from db_service import DbPool

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DB_MARKET = str(DATA_DIR / "market_data.duckdb")
DB_ANALYTICS = str(DATA_DIR / "analytics.duckdb")


class FeatureBuilder:
    """Orchestriert die Feature-Berechnung und persistiert sie im feature_store."""

    def __init__(self) -> None:
        # Rueckbau auf stabilen Basis-Stand (nur EMADiff + ATRNormalized)
        self.features: Dict[str, BaseFeature] = {
            "ema_diff": EMADiffFeature(),
            "atr_normalized": ATRNormalizedFeature(),
        }
        self._state_mgr = StateManager()
        self._settings = self._state_mgr.get_app_settings()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_available_features(self) -> List[str]:
        return list(self.features.keys())

    def load_ohlcv(self, symbol: str, timeframe: str, limit: Optional[int] = None) -> pd.DataFrame:
        """Laedt OHLCV-Daten aus market_data.duckdb (read-only via DbPool)."""
        if limit is None:
            limit = self._settings.feature_builder_limit
        con = DbPool.get(DB_MARKET)
        query = """
            SELECT "time" AS bar_time, open, high, low, close, tick_volume
            FROM ohlcv_bars
            WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
              AND "time" IS NOT NULL
              AND open IS NOT NULL
              AND high IS NOT NULL
              AND low IS NOT NULL
              AND close IS NOT NULL
            ORDER BY "time" DESC
            LIMIT ?
        """
        df = con.execute(query, [symbol, timeframe, limit]).df()
        return df.sort_values("bar_time").reset_index(drop=True)

    def calculate_features(
        self,
        df: pd.DataFrame,
        feature_names: Optional[List[str]] = None,
        params: Optional[Dict[str, Dict[str, any]]] = None
    ) -> pd.DataFrame:
        """
        Berechnet ausgewaehlte Features auf einem OHLCV-DataFrame.

        Args:
            df: OHLCV-DataFrame mit bar_time, open, high, low, close
            feature_names: Liste der Feature-Namen (None = alle)
            params: Dict mit Feature-spezifischen Parametern

        Returns:
            DataFrame mit bar_time + feature-Spalten
        """
        if feature_names is None:
            feature_names = list(self.features.keys())

        if params is None:
            params = {}

        result = df[["bar_time"]].copy()

        for name in feature_names:
            feature = self.features.get(name)
            if feature is None:
                print(f"  [FeatureBuilder] Unbekanntes Feature: {name}")
                continue

            feature_params = params.get(name, {})
            try:
                calculated = feature.calculate(df, feature_params)

                if isinstance(calculated, pd.DataFrame):
                    for col in calculated.columns:
                        result[col] = calculated[col].values
                else:
                    result[feature.name] = calculated.values

            except Exception as e:
                print(f"  [FeatureBuilder] Fehler bei {name}: {e}")
                for col in feature.column_names:
                    result[col] = None

        return result

    def store_features(
        self,
        symbol: str,
        timeframe: str,
        features_df: pd.DataFrame,
        con: Optional = None,
    ) -> int:
        """
        Schreibt berechnete Features per Bulk-Upsert in analytics.duckdb.

        Args:
            symbol: Symbol-Name
            timeframe: Timeframe-String
            features_df: DataFrame mit bar_time + feature-Spalten
            con: Optionale externe DB-Connection

        Returns:
            Anzahl der geschriebenen Zeilen
        """
        if features_df.empty:
            return 0

        df = features_df.copy()
        df["symbol"] = symbol
        df["timeframe"] = timeframe

        own_connection = False
        if con is None:
            con = DbPool.get(DB_ANALYTICS)
        else:
            own_connection = True

        try:
            con.register("df_temp", df)

            feature_cols = [c for c in df.columns if c not in ("bar_time", "symbol", "timeframe")]
            if not feature_cols:
                return 0

            insert_cols = ", ".join(['"symbol"', '"timeframe"', '"bar_time"'] + [f'"{c}"' for c in feature_cols])
            select_cols = ", ".join(['"symbol"', '"timeframe"', '"bar_time"'] + [f'"{c}"' for c in feature_cols])
            set_clause = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in feature_cols])

            sql = f"""
                INSERT INTO feature_store ({insert_cols})
                SELECT {select_cols}
                FROM df_temp
                ON CONFLICT (symbol, timeframe, bar_time) DO UPDATE SET
                    {set_clause}
            """
            con.execute(sql)
            con.unregister("df_temp")

            return len(df)
        finally:
            if own_connection:
                con.close()

    def build(
        self,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
        feature_names: Optional[List[str]] = None,
        params: Optional[Dict[str, Dict[str, any]]] = None,
    ) -> int:
        """
        Vollstaendiger Pipeline-Durchlauf: Laden -> Berechnen -> Speichern.

        Args:
            symbol: Symbol-Name
            timeframe: Timeframe-String
            limit: Maximale Anzahl Bars
            feature_names: Liste der Feature-Namen (None = alle)
            params: Feature-spezifische Parameter

        Returns:
            Anzahl der geschriebenen Zeilen
        """
        if limit is None:
            limit = self._settings.feature_builder_limit

        df_ohlcv = self.load_ohlcv(symbol, timeframe, limit)

        if df_ohlcv.empty:
            return 0

        features_df = self.calculate_features(df_ohlcv, feature_names, params)
        count = self.store_features(symbol, timeframe, features_df)
        return count
