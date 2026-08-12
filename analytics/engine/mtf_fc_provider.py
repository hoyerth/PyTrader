# analytics/engine/mtf_fc_provider.py
"""
MTF-FC v4 (Kapitel 21.03.01) – Data Provider & Cache-Versionierung (Schicht 2).

Der Provider kapselt den gesamten Lese-Zugriff auf die Market-Daten
(`ohlcv_bars` in `data/market_data.duckdb`, read-only via DbPool) und den
Namespace `PluginContext.shared_state["mtf_fc"]`.

Verantwortlichkeiten:
  * `get_earliest_timestamp(symbol, timeframe)` – MIN("time") je Symbol/TF
    (Wanduhr-Epoch, Invariante 7; defensiv None bei Fehler/leerer DB).
  * `get_latest_timestamp(symbol, timeframe)`  – MAX("time") je Symbol/TF
    (Basis der Cache-Versionierung).
  * Cache-Versionierung `(symbol, timeframe, partition)`: Ein Eintrag traegt
    `source_max_timestamp`; er ist nur gueltig, wenn diese Quellgrenze <= dem
    aktuellen DB-Maximum liegt (sonst stale -> Partitions-Invalidierung, 21.03.06).
  * Namespace-Schreibzugriff ausschliesslich ueber den Provider
    (`read_namespace(context)` / `write_namespace(context, **changes)`).

Wanduhr-Garantie (Invariante 7): Alle Zeiten sind Wanduhr-Epochs
(Berlin-Wanduhr-encoded, 1:1 aus der DB gelesen) – keine Offset-Umrechnung.

Open/Closed (Grundsatz 11): Kein Bestandsmodul wird veraendert; die
Lese-Muster folgen FeatureStoreReader.fetch_ohlcv_snapshot / _epoch_of().
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from analytics.features.plugins.base_plugin import PluginContext
from analytics.engine.mtf_fc_state import ensure_mtf_fc_namespace

# Projekt-Root = 3 Ebenen ueber dieser Datei (engine/ -> analytics/ -> Root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_MARKET = str(BASE_DIR / "data" / "market_data.duckdb")

#: Kompakte Partitions-Kodierung: Wanduhr-Datum (UTC) der Event-Zeit.
from datetime import datetime as _dt_datetime
from datetime import timezone as _dt_timezone


def _epoch_to_partition(ts: int) -> str:
    """Partitions-Schluessel einer Event-Zeit: Wanduhr-Datum `YYYY-MM-DD`.

    Wanduhr-Garantie (Invariante 7): Die Epoch ist Wanduhr-encoded, daher
    liefert die UTC-Darstellung exakt das Wanduhr-Datum der Event-Zeit.
    """
    return _dt_datetime.fromtimestamp(int(ts), tz=_dt_timezone.utc).strftime("%Y-%m-%d")


class MtfFcProvider:
    """Datenzugriff + Namespace-Verwaltung fuer das MTF-FC-System.

    Args:
        market_db_path: Testbarkeit (Seam) – Default `data/market_data.duckdb`.
        pool: DbPool-Klasse/Objekt mit `get(db_path)`-API (Default `DbPool`).
    """

    def __init__(self, market_db_path: Optional[str] = None, pool: Any = None) -> None:
        self.market_db_path = market_db_path or DB_MARKET
        if pool is None:
            from db.db_pool import DbPool
            pool = DbPool
        self._pool = pool

    # ------------------------------------------------------------------
    # Roh-Zeitgrenzen (Wanduhr-Epochs)
    # ------------------------------------------------------------------
    def get_earliest_timestamp(self, symbol: str, timeframe: str) -> Optional[int]:
        """Aeltester Bar-Zeitpunkt des Symbols im Timeframe (Wanduhr-Epoch).

        Defensiv: `None` bei leerer DB, unbekanntem Symbol/TF oder Fehler.
        """
        return self._query_bound("MIN", symbol, timeframe)

    def get_latest_timestamp(self, symbol: str, timeframe: str) -> Optional[int]:
        """Neuester Bar-Zeitpunkt des Symbols im Timeframe (Wanduhr-Epoch).

        Defensiv: `None` bei leerer DB, unbekanntem Symbol/TF oder Fehler.
        """
        return self._query_bound("MAX", symbol, timeframe)

    def _query_bound(self, agg: str, symbol: str, timeframe: str) -> Optional[int]:
        if not symbol or not timeframe:
            return None
        try:
            con = self._pool.get(self.market_db_path)
            row = con.execute(
                f'SELECT {agg}("time") FROM ohlcv_bars '
                'WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?) '
                'AND "time" IS NOT NULL',
                [symbol, timeframe],
            ).fetchone()
            value = row[0] if row else None
            if value is None:
                return None
            if hasattr(value, "timestamp"):  # datetime-Objekt -> Wanduhr-Epoch
                return int(value.timestamp())
            return int(value)
        except Exception as e:
            print(f"WARN [MtfFcProvider] {agg}('time') fehlgeschlagen "
                  f"(symbol={symbol}, tf={timeframe}): {e}")
            return None

    # ------------------------------------------------------------------
    # Cache-Versionierung (21.03.01 Schritt 3 + 21.03.06)
    # ------------------------------------------------------------------
    @staticmethod
    def cache_key(symbol: str, timeframe: str, partition: str) -> Tuple[str, str, str]:
        """Stabiler Cache-Schluessel `(symbol, timeframe, partition)`."""
        return (symbol.upper(), timeframe.upper(), partition)

    @staticmethod
    def partition_of_event(symbol: str, timeframe: str, ts: int) -> Tuple[str, str, str]:
        """Partitions-Schluessel einer Event-Zeit inkl. Symbol/TF.

        $affected\\_partition = partition(symbol, timeframe, t_{event})$ –
        die Partition einer nachtraeglich eingehenden Event-Zeit. Rein
        deterministisch aus der Wanduhr-Epoch (Invariante 7).
        """
        return MtfFcProvider.cache_key(symbol, timeframe, _epoch_to_partition(ts))

    def is_cache_valid(
        self,
        cache: Dict[Tuple[str, str, str], Dict[str, Any]],
        symbol: str,
        timeframe: str,
        partition: str,
    ) -> bool:
        """True, wenn der Cache-Eintrag nicht stale ist.

        Ein Eintrag ist genau dann gueltig, wenn sein `source_max_timestamp`
        kleiner/gleich dem aktuellen DB-Maximum des Symbols/TF liegt. Ist die
        Quelle gewachsen (neuer Bar nachgeladen), ist der Eintrag stale.
        Fehlt der Eintrag oder das DB-Maximum, ist er ungueltig.
        """
        key = self.cache_key(symbol, timeframe, partition)
        entry = cache.get(key)
        if not isinstance(entry, dict):
            return False
        source_max = entry.get("source_max_timestamp")
        if not isinstance(source_max, (int, float)):
            return False
        db_max = self.get_latest_timestamp(symbol, timeframe)
        if db_max is None:
            return False
        return float(source_max) <= float(db_max)

    # ------------------------------------------------------------------
    # Namespace-Zugriff (einzige Schreib-Schnittstelle, 21.03.01 Schritt 4)
    # ------------------------------------------------------------------
    def read_namespace(self, context: PluginContext) -> Dict[str, Any]:
        """Liefert den `mtf_fc`-Namespace des Contexts (ggf. initialisiert)."""
        if context is None:
            context = PluginContext(mode="batch")
        return ensure_mtf_fc_namespace(context.shared_state)

    def write_namespace(self, context: PluginContext, **changes: Any) -> Dict[str, Any]:
        """Schreibt Aenderungen in den `mtf_fc`-Namespace (additiv, flach).

        Es werden nur die uebergebenen Keys aktualisiert – nicht betroffene
        Teil-Dicts bleiben unangetastet. Rueckgabe: der aktualisierte Namespace.
        """
        ns = self.read_namespace(context)
        ns.update(changes)
        return ns

    def clear_partition(
        self,
        context: PluginContext,
        symbol: str,
        timeframe: str,
        partition: str,
    ) -> bool:
        """Entfernt exakt einen Partitions-Eintrag aus dem RAM-Cache.

        (21.03.06) Erhoeht bei Erfolg `cache_generation` im Namespace.
        Rueckgabe: True, wenn ein Eintrag entfernt wurde.
        """
        ns = self.read_namespace(context)
        cache = ns.setdefault("ram_cache", {})
        key = self.cache_key(symbol, timeframe, partition)
        if key in cache:
            del cache[key]
            ns["cache_generation"] = int(ns.get("cache_generation", 0)) + 1
            return True
        return False
