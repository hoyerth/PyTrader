# analytics/features/feature_builder.py
"""
Feature Builder – Lädt OHLCV aus market_data.duckdb, berechnet Features
(ema_diff, atr_normalized, grid_levels) vektorisiert und schreibt sie per
Bulk-Upsert in analytics.duckdb.

Stabiler Basis-Stand + Phase-11-Erweiterung: grid_levels (Y-Achsen-Grid-Levels
und X-Achsen-Zeitfenster-Flags), gekapselt in analytics/features/definitions/.
"""

from typing import Any, Dict, List, Optional, Tuple
import importlib
import inspect
import json
import pkgutil
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analytics.features.base_feature import BaseFeature
from analytics.features.definitions.ema_diff import EMADiffFeature
from analytics.features.definitions.atr_normalized import ATRNormalizedFeature
from analytics.features.definitions.grid_levels import GridLevelsFeature
from analytics.features.plugins.base_plugin import (
    PluginFeature,
    FeatureCalculateResult,
    PluginContext,
    ServiceErrorLog,
)
from state_manager import StateManager
from db_service import DbPool

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DB_MARKET = str(DATA_DIR / "market_data.duckdb")
DB_ANALYTICS = str(DATA_DIR / "analytics.duckdb")


def _timestamp_to_epoch(value: Any) -> int:
    """Konvertiert pandas Timestamp / datetime in epoch-Sekunden (int).
    Int/Float-Werte (bereits epoch-Sekunden) werden unveraendert uebernommen."""
    if hasattr(value, "to_pydatetime"):
        return int(value.to_pydatetime().timestamp())
    if hasattr(value, "timestamp"):
        return int(value.timestamp())
    return int(value)


def prepare_plugin_df(df: pd.DataFrame) -> pd.DataFrame:
    """Bereitet einen OHLCV-DataFrame fuer Plugin-Aufrufe vor.
    Plugin-Vertrag (base_plugin.py): der Input-DataFrame enthaelt eine
    'time'-Spalte mit epoch-Sekunden (int). load_ohlcv() liefert stattdessen
    'bar_time' (datetime) – diese wird hier passend umgewandelt."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if "bar_time" in out.columns and "time" not in out.columns:
        out["time"] = out["bar_time"].apply(_timestamp_to_epoch)
    return out


def _to_utc_datetime(value: Any):
    """Konvertiert epoch-Sekunden / pandas Timestamp / datetime in ein
    timezone-aware datetime (UTC), passend zur TIMESTAMPTZ-Spalte im Store."""
    if isinstance(value, bool):
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return value


# ==============================================================================
# P14-03: Strukturierte Fehlerobjekte & In-Memory-Cache-Invalidierung
# ------------------------------------------------------------------------------
# Architektur-Invariante 8: Logging verwendet strukturierte Fehlerobjekte
# (timestamp, plugin, instance, symbol, timeframe, bar, exception, traceback).
# Architektur-Invariante 13: store_plugin_payload() invalidiert den
# In-Memory-Cache für (symbol, timeframe).
# ==============================================================================
@dataclass
class PluginExecutionErrorInfo:
    """Strukturiertes Fehlerobjekt eines fehlgeschlagenen Plugin-Aufrufs.

    Wird von PluginExecutor bei jeder Exception der Ausführungskette erzeugt
    (stage: resolve / dependency / validate_params / calculate) und als
    .info am PluginExecutionError mitgereicht. Der ServiceSetEvaluator nutzt
    es für Skip-Logic, State-Fallback und Session-Quarantäne.
    """
    timestamp: float
    plugin_id: str
    instance_id: Optional[str]
    symbol: str
    timeframe: str
    bar_time: Optional[int]
    stage: str
    exception_type: str
    exception_message: str
    traceback: str

    def to_service_error_log(self) -> ServiceErrorLog:
        """P14-03 (Schritt 2.2): Liefert das strukturierte Fehlerobjekt als
        ServiceErrorLog-TypedDict (Pflichtfelder laut Anleitung) für die
        maschinelle Auswertung des Loggings in PluginExecutor /
        ServiceSetEvaluator."""
        return ServiceErrorLog(
            timestamp=self.timestamp,
            plugin_id=self.plugin_id,
            instance_id=self.instance_id,
            symbol=self.symbol,
            timeframe=self.timeframe,
            bar_time=self.bar_time,
            exception=f"{self.exception_type}: {self.exception_message}",
            traceback=self.traceback,
        )


class PluginExecutionError(Exception):
    """Getypter Ausführungsfehler mit strukturiertem Fehlerobjekt (.info)."""

    def __init__(self, info: PluginExecutionErrorInfo):
        self.info = info
        super().__init__(info.exception_message)


_feature_cache_lock = threading.Lock()
_feature_cache_invalidated: Dict[Tuple[str, str], float] = {}


def invalidate_feature_cache(symbol: str, timeframe: str) -> None:
    """P14-03 (Invariante 13): Meldet die Invalidation des In-Memory-Caches
    für (symbol, timeframe). Wird bei jedem store_plugin_payload() aufgerufen,
    damit veraltete Zustände (z. B. in EvaluationContext.shared_state) nicht
    über einen Refresh hinweg weiterleben."""
    with _feature_cache_lock:
        _feature_cache_invalidated[
            (str(symbol).lower(), str(timeframe).lower())
        ] = time.time()


def feature_cache_last_invalidated(symbol: str, timeframe: str) -> Optional[float]:
    """Letzter Invalidation-Zeitpunkt für (symbol, timeframe) oder None."""
    with _feature_cache_lock:
        return _feature_cache_invalidated.get(
            (str(symbol).lower(), str(timeframe).lower())
        )


class PluginLoader:
    """Class-Finder scannt Verzeichnisse rein nach Subklassen von PluginFeature (Dateiname-unabhängig).

    P14-02 (additiv): Automatische, rekursive Discovery über
    pkgutil.walk_packages() + importlib.import_module() für
    analytics/features/definitions/ (Core) und data/custom_plugins/ (Custom).
    - data/custom_plugins/ wird automatisch angelegt (os.makedirs).
    - Eindeutigkeit der plugin_id strikt case-insensitiv (plugin_id.lower()).
    - Core Protection Rule: Custom-Plugins mit bereits belegter ID werden
      verworfen (WARN-Log).
    - Abstrakte Klassen werden ignoriert; Import-/Instanzierungsfehler einzelner
      Module werden isoliert abgefangen (kein App-Absturz).
    """

    def __init__(self, definitions_path: Optional[Path] = None,
                 custom_plugins_path: Optional[Path] = None):
        self.definitions_path = definitions_path or Path(__file__).parent / "definitions"
        self.custom_plugins_path = custom_plugins_path or DATA_DIR / "custom_plugins"
        # P14-02: Namen der zuletzt erfolgreich geladenen Custom-Plugin-Module
        # (fuer gezieltes importlib.reload in PluginRegistry.reload()).
        self.loaded_custom_modules: List[str] = []

    def _ensure_custom_dir(self) -> None:
        """Legt data/custom_plugins/ an, falls es noch nicht existiert (P14-02)."""
        try:
            self.custom_plugins_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"WARN [PluginLoader] Ordner {self.custom_plugins_path} nicht erstellbar: {e}")

    def _scan_dir(self, plugins: Dict[str, PluginFeature], path: Path,
                  package_prefix: str, is_custom: bool) -> None:
        """Scannt ein Verzeichnis rekursiv nach PluginFeature-Subklassen (P14-02).

        is_custom=True: Module werden in loaded_custom_modules registriert und
        eine bereits belegte plugin_id (Core Protection Rule) fuehrt zum
        Ueberspringen mit WARN-Log.
        """
        if not path.exists():
            return
        for mod_info in pkgutil.walk_packages([str(path)]):
            module_name = mod_info.name
            full_module_name = f"{package_prefix}.{module_name}"
            try:
                module = importlib.import_module(full_module_name)
            except Exception as e:
                print(f"WARN [PluginLoader] Modul {full_module_name} nicht ladbar: {e}")
                continue
            if is_custom and full_module_name not in self.loaded_custom_modules:
                self.loaded_custom_modules.append(full_module_name)
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if inspect.isabstract(obj):
                    continue  # abstrakte Basisklassen ignorieren
                if issubclass(obj, PluginFeature) and obj is not PluginFeature:
                    try:
                        instance = obj()
                    except Exception as e:
                        print(f"WARN [PluginLoader] Instanzierung {_name} ({full_module_name}) fehlgeschlagen: {e}")
                        continue
                    pid = str(instance.plugin_id)
                    pid_key = pid.lower()
                    if is_custom and pid_key in plugins:
                        print(f"WARN: Custom plugin skipped: plugin_id '{pid}' already registered")
                        continue
                    plugins[pid_key] = instance

    def discover_plugins(self) -> Dict[str, PluginFeature]:
        """Entdeckt Core-Plugins (zuerst) und Custom-Plugins (danach), case-insensitiv.

        P14-02: data/custom_plugins/ wird automatisch angelegt; fuer den Import
        der Custom-Module ('custom_plugins.<mod>') wird data/ in sys.path
        aufgenommen, falls noetig (namespace package).
        """
        plugins: Dict[str, PluginFeature] = {}
        self.loaded_custom_modules = []
        self._ensure_custom_dir()
        # Core zuerst (analytics/features/definitions/)
        self._scan_dir(plugins, self.definitions_path,
                       "analytics.features.definitions", is_custom=False)
        # Custom danach (data/custom_plugins/) - data/ in sys.path sicherstellen
        try:
            data_dir = str(DATA_DIR)
            if data_dir not in sys.path:
                sys.path.insert(0, data_dir)
        except Exception:
            pass
        self._scan_dir(plugins, self.custom_plugins_path, "custom_plugins", is_custom=True)
        return plugins

    def find_custom_conflicts(self) -> List[Dict[str, str]]:
        """Kapitel 7.3 AKTUELLE_UMSETZUNG (Core Protection Rule, --check-plugins).

        Scannt die Core-Definitions und anschliessend die Custom-Plugins –
        exakt wie discover_plugins() – und liefert alle Custom-Plugin-IDs, die
        mit einer bereits registrierten Core-Plugin-ID kollidieren. Die
        eigentliche Registry verwirft solche Custom-Plugins bereits beim Laden
        (WARN-Log); dieser Check macht die Kollisionen fuer den Deployment-
        Check (`python main.py --check-plugins`) sichtbar und pruefbar.

        Returns:
            Liste von Dicts {"plugin_id", "custom_module"} – leer, wenn die
            Core Protection Rule vollstaendig greift.
        """
        conflicts: List[Dict[str, str]] = []
        core: Dict[str, PluginFeature] = {}
        self._scan_dir(core, self.definitions_path,
                       "analytics.features.definitions", is_custom=False)
        if not self.custom_plugins_path.exists():
            return conflicts
        # data/ in sys.path sicherstellen (namespace package custom_plugins)
        try:
            data_dir = str(DATA_DIR)
            if data_dir not in sys.path:
                sys.path.insert(0, data_dir)
        except Exception:
            pass
        for mod_info in pkgutil.walk_packages([str(self.custom_plugins_path)]):
            full_module_name = f"custom_plugins.{mod_info.name}"
            try:
                module = importlib.import_module(full_module_name)
            except Exception as e:
                print(f"WARN [PluginLoader] Modul {full_module_name} nicht "
                      f"ladbar: {e}")
                continue
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if inspect.isabstract(obj):
                    continue
                if issubclass(obj, PluginFeature) and obj is not PluginFeature:
                    try:
                        instance = obj()
                    except Exception as e:
                        print(f"WARN [PluginLoader] Instanzierung {_name} "
                              f"({full_module_name}) fehlgeschlagen: {e}")
                        continue
                    pid = str(instance.plugin_id)
                    if pid.lower() in core:
                        conflicts.append({
                            "plugin_id": pid,
                            "custom_module": full_module_name,
                        })
        return conflicts


class PluginRegistry:
    """Zentraler Singleton-Katalog für entdeckte Plugins (P14-02: thread-sicher)."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # P14-02: Reentrant Lock fuer Schreib-/Lesezugriffe (Thread-Safety)
            cls._instance._lock = threading.RLock()
            cls._instance.loader = PluginLoader()
            cls._instance.plugins = cls._instance.loader.discover_plugins()
        return cls._instance

    def reload(self):
        """Expliziter Reload nur beim Start oder per Button (thread-sicher).

        P14-02: Unter dem RLock werden zuerst die geladenen Custom-Plugin-Module
        gezielt neu importiert (importlib.reload), danach die Registry ueber
        discover_plugins() neu aufgebaut. Bereits laufende Service-Instanzen
        behalten ihre bisherigen Objekt-Referenzen (Hot-Reload-Semantik); neue
        Instanziierungen nutzen die neuen Klassen.
        """
        with self._lock:
            # 1. Custom-Module gezielt neu laden (Datei geloescht/fehlerhaft ->
            #    Modul aus sys.modules entfernen)
            for mod_name in list(self.loader.loaded_custom_modules):
                try:
                    if mod_name in sys.modules:
                        importlib.reload(sys.modules[mod_name])
                except Exception as e:
                    sys.modules.pop(mod_name, None)
                    print(f"WARN [PluginRegistry] Custom-Modul {mod_name} nicht reloadbar: {e}")
            # 2. Registry neu aufbauen
            self.plugins = self.loader.discover_plugins()

    def get(self, plugin_id: str) -> PluginFeature:
        """Case-insensitiver Zugriff (P14-02): plugin_id.lower()."""
        key = plugin_id.lower()
        if key not in self.plugins:
            raise KeyError(f"Plugin '{plugin_id}' nicht gefunden.")
        return self.plugins[key]


class PluginExecutor:
    """Zentrale Schicht für Ausführung, Validierung, Dependency-Ordering & Logging.

    P14-03 (Ganzheitliche Fehlerkapselung): Sämtliche Exceptions der
    Ausführungskette eines Plugins – Plugin-Auflösung (resolve), interne
    Dependency-Aufrufe (dependency), validate_params() und calculate() –
    werden isoliert abgefangen, in ein strukturiertes Fehlerobjekt
    (PluginExecutionErrorInfo, Invariante 8) umgewandelt, geloggt und als
    PluginExecutionError weitergereicht. Der ServiceSetEvaluator entscheidet
    darüber mit Skip-Logic / Dependency-Skip / Quarantäne.
    """

    def __init__(self, registry: Optional[PluginRegistry] = None):
        self.registry = registry or PluginRegistry()

    @staticmethod
    def _call_calculate(
        plugin: PluginFeature,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Ruft plugin.calculate() auf – mit Context, falls das Plugin ihn
        unterstützt. Plugins mit der alten Phase-12-Signatur calculate(df, params)
        bleiben kompatibel (context ist Optional, Rückwärtskompatibilität)."""
        sig = inspect.signature(plugin.calculate)
        if "context" in sig.parameters:
            return plugin.calculate(df, params, context=context)
        return plugin.calculate(df, params)

    @staticmethod
    def _build_error(
        plugin_id: str,
        context: Optional[PluginContext],
        exc: Exception,
        stage: str,
    ) -> "PluginExecutionError":
        """Baut aus einer Exception das strukturierte Fehlerobjekt (P14-03)."""
        symbol = getattr(context, "symbol", "") or ""
        timeframe = getattr(context, "timeframe", "") or ""
        instance_id = getattr(context, "instance_id", None)
        bar_time = getattr(context, "timestamp", None)
        info = PluginExecutionErrorInfo(
            timestamp=time.time(),
            plugin_id=plugin_id,
            instance_id=instance_id,
            symbol=str(symbol),
            timeframe=str(timeframe),
            bar_time=bar_time,
            stage=stage,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            traceback=traceback.format_exc(),
        )
        # P14-03 (Schritt 2.2): Logging über das strukturierte
        # ServiceErrorLog-TypedDict (maschinelle Auswertung).
        log: ServiceErrorLog = info.to_service_error_log()
        print(
            f"WARN [PluginExecutor] {stage} fehlgeschlagen: plugin='{log['plugin_id']}' "
            f"instance='{log['instance_id']}' {log['symbol']}/{log['timeframe']} – "
            f"{log['exception']}"
        )
        return PluginExecutionError(info)

    def execute(
        self,
        plugin_id: str,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        # 0. Plugin-Auflösung (Registry) – Fehler werden strukturiert gekapselt.
        try:
            plugin = self.registry.get(plugin_id)
        except Exception as e:
            raise self._build_error(plugin_id, context, e, "resolve") from e

        # 1. Dependency Resolution (falls Abhängigkeiten angegeben sind) –
        #    Context wird auch an Abhängigkeiten durchgereicht. Fehler in
        #    Dependency-Aufrufen werden unter der Dependency-plugin_id gekapselt.
        for dep_id in plugin.dependencies:
            try:
                dep_plugin = self.registry.get(dep_id)
                self._call_calculate(dep_plugin, df, dep_plugin.default_params, context)
            except PluginExecutionError:
                raise
            except Exception as e:
                raise self._build_error(dep_id, context, e, "dependency") from e

        # 2. Parametervalidierung
        try:
            validated_params = plugin.validate_params(params)
        except Exception as e:
            raise self._build_error(plugin_id, context, e, "validate_params") from e

        # 3. Stateless Execution – Context (inkl. shared_state) wird durchgereicht,
        #    damit Services den shared_state erreichen (Schritt 3 Evaluator).
        try:
            return self._call_calculate(plugin, df, validated_params, context)
        except Exception as e:
            raise self._build_error(plugin_id, context, e, "calculate") from e


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

    def store_plugin_payload(
        self,
        symbol: str,
        timeframe: str,
        payload: Dict[str, Any],
        con: Optional = None,
    ) -> int:
        """
        Schreibt den feature_store_payload eines Plugins (Phase 12 Hybrid-Schema)
        in analytics.duckdb.

        Setzt/aktualisiert NUR die Plugin-Spalten (feature_id, plugin_version,
        feature_data); native Feature-Spalten bleiben unberuehrt. Dadurch ist
        der Plugin-Pfad parallel zum Alt-Pfad betreibbar (derselbe (symbol,
        timeframe, bar_time)-Schluessel kann beide Informationsarten tragen).

        payload: {"feature_id", "plugin_version", "records": [{bar_time, ...}]}
        """
        records = payload.get("records") or []
        if not records:
            return 0

        feature_id = payload.get("feature_id")
        plugin_version = payload.get("plugin_version", "1.0.0")

        own_connection = False
        if con is None:
            con = DbPool.get(DB_ANALYTICS)
        else:
            own_connection = True

        try:
            rows = []
            for rec in records:
                if not isinstance(rec, dict) or "bar_time" not in rec:
                    continue
                dt_val = _to_utc_datetime(rec["bar_time"])
                data = {k: v for k, v in rec.items() if k != "bar_time"}
                rows.append((symbol, timeframe, dt_val, feature_id, plugin_version, json.dumps(data)))
            if not rows:
                return 0

            # Bugfix 05.08.2026: `now()` statt `current_timestamp` im
            # ON CONFLICT DO UPDATE SET – DuckDB 1.5.5 bindet das (lowercase)
            # Keyword dort als SPALTENREFERENZ der feature_store-Tabelle und
            # wirft 'Binder Error: Table "feature_store" does not have a column
            # named "current_timestamp"'. `now()` (Funktionsaufruf) wird
            # korrekt als Zeitfunktion aufgeloest (verifiziert in
            # test/check_current_timestamp.py).
            con.executemany("""
                INSERT INTO feature_store (symbol, timeframe, bar_time, feature_id, plugin_version, feature_data)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol, timeframe, bar_time) DO UPDATE SET
                    feature_id = EXCLUDED.feature_id,
                    plugin_version = EXCLUDED.plugin_version,
                    feature_data = EXCLUDED.feature_data,
                    created_at = now()
            """, rows)
            # P14-03 (Invariante 13): In-Memory-Cache für (symbol, timeframe)
            # explizit invalidieren (veraltete shared_state-Zustände vermeiden).
            invalidate_feature_cache(symbol, timeframe)
            return len(rows)
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
