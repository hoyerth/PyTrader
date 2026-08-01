# analytics/features/feature_builder.py
"""
Feature Builder – Lädt OHLCV aus market_data.duckdb, berechnet Features
(ema_diff, atr_normalized, grid_levels) vektorisiert und schreibt sie per
Bulk-Upsert in analytics.duckdb.

Stabiler Basis-Stand + Phase-11-Erweiterung: grid_levels (Y-Achsen-Grid-Levels
und X-Achsen-Zeitfenster-Flags), gekapselt in analytics/features/definitions/.
"""

from typing import Dict, List, Optional
import importlib
import inspect
import pkgutil
from pathlib import Path

import pandas as pd

from analytics.features.base_feature import BaseFeature
from analytics.features.definitions.ema_diff import EMADiffFeature
from analytics.features.definitions.atr_normalized import ATRNormalizedFeature
from analytics.features.definitions.grid_levels import GridLevelsFeature
from analytics.features.plugins.base_plugin import PluginFeature, FeatureCalculateResult
from state_manager import StateManager
from db_service import DbPool

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DB_MARKET = str(DATA_DIR / "market_data.duckdb")
DB_ANALYTICS = str(DATA_DIR / "analytics.duckdb")


class PluginLoader:
    """Class-Finder scannt Verzeichnisse rein nach Subklassen von PluginFeature (Dateiname-unabhängig)."""

    def __init__(self, definitions_path: Optional[Path] = None):
        self.definitions_path = definitions_path or Path(__file__).parent / "definitions"

    def discover_plugins(self) -> Dict[str, PluginFeature]:
        plugins = {}
        if not self.definitions_path.exists():
            return plugins

        for _, module_name, is_pkg in pkgutil.iter_modules([str(self.definitions_path)]):
            if is_pkg:
                continue
            full_module_name = f"analytics.features.definitions.{module_name}"
            try:
                module = importlib.import_module(full_module_name)
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, PluginFeature) and obj is not PluginFeature:
                        instance = obj()
                        plugins[instance.plugin_id] = instance
            except Exception as e:
                print(f"⚠️ [PluginLoader] Fehler in Modul {module_name}: {e}")
        return plugins


class PluginRegistry:
    """Zentraler Singleton-Katalog für entdeckte Plugins."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.loader = PluginLoader()
            cls._instance.plugins = cls._instance.loader.discover_plugins()
        return cls._instance

    def reload(self):
        """Expliziter Reload nur beim Start oder per Button (thread-sicher)."""
        self.plugins = self.loader.discover_plugins()

    def get(self, plugin_id: str) -> PluginFeature:
        if plugin_id not in self.plugins:
            raise KeyError(f"Plugin '{plugin_id}' nicht gefunden.")
        return self.plugins[plugin_id]


class PluginExecutor:
    """Zentrale Schicht für Ausführung, Validierung, Dependency-Ordering & Logging."""

    def __init__(self, registry: Optional[PluginRegistry] = None):
        self.registry = registry or PluginRegistry()

    def execute(self, plugin_id: str, df: pd.DataFrame, params: Dict[str, any]) -> FeatureCalculateResult:
        plugin = self.registry.get(plugin_id)

        # 1. Dependency Resolution (falls Abhängigkeiten angegeben sind)
        for dep_id in plugin.dependencies:
            dep_plugin = self.registry.get(dep_id)
            dep_plugin.calculate(df, dep_plugin.default_params)

        # 2. Parametervalidierung
        validated_params = plugin.validate_params(params)

        # 3. Stateless Execution
        return plugin.calculate(df, validated_params)


class FeatureBuilder:
    """Orchestriert die Feature-Berechnung und persistiert sie im feature_store."""

    def __init__(self) -> None:
        # Basis-Stand (EMADiff + ATRNormalized) + Phase 11: Grid-Levels
        self.features: Dict[str, BaseFeature] = {
            "ema_diff": EMADiffFeature(),
            "atr_normalized": ATRNormalizedFeature(),
            "grid_levels": GridLevelsFeature(),
        }
        # Spaltenname -> Feature-Modul-Name. Erlaubt calculate_features() auch
        # Spaltennamen aus signal.required_features (z. B. 'grid_dist_pct')
        # statt nur Modul-Namen zu uebernehmen.
        self._column_to_feature: Dict[str, str] = {}
        for fname, feat in self.features.items():
            for col in feat.column_names:
                self._column_to_feature[col] = fname
            self._column_to_feature.setdefault(fname, fname)
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
            # Spaltenname -> Feature-Modul aufloesen (z. B. 'grid_dist_pct' -> 'grid_levels')
            resolved = self._column_to_feature.get(name, name)
            feature = self.features.get(resolved)
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
