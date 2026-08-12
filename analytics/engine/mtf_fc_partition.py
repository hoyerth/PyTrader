# analytics/engine/mtf_fc_partition.py
"""
MTF-FC v4 (Kapitel 21.03.06) – Event-Partitionierung & Cache-Invalidierung.

Partitionierte RAM-Cache-Invalidierung:
  $affected\\_partition = partition(symbol, timeframe, t_{event})$

Nachtraeglich eingehende Ticks invalidieren ausschliesslich die RAM-Partition
ihrer eigenen Event-Zeit $t_{event}$ – nie den gesamten Cache (§4 Säule 2.3).

Integration mit der Cache-Versionierung (21.03.01): Nach einer Invalidierung
wird `cache_generation` im Namespace inkrementiert.

Reine Logik (kein UI-Import, Grundsatz 4/11). Alle Zeiten sind Wanduhr-Epochs
(Invariante 7).
"""

from typing import Any, Dict, Optional, Tuple

from analytics.engine.mtf_fc_provider import MtfFcProvider


def partition(symbol: str, timeframe: str, ts: int) -> Tuple[str, str, str]:
    """Partitions-Schluessel der Event-Zeit: `(symbol, timeframe, datum)`.

    Das Datum ist das Wanduhr-Datum (`YYYY-MM-DD`) der Event-Zeit
    (Invariante 7) – gleiche Kalendertage teilen sich eine RAM-Partition.
    """
    return MtfFcProvider.partition_of_event(symbol, timeframe, ts)


def invalidate_partition(
    cache: Dict[Tuple[str, str, str], Dict[str, Any]],
    symbol: str,
    timeframe: str,
    t_event: int,
    namespace: Optional[Dict[str, Any]] = None,
) -> bool:
    """Entfernt ausschliesslich die Partition der Event-Zeit aus dem Cache.

    Args:
        cache: Der RAM-Partitions-Cache (`shared_state["mtf_fc"]["ram_cache"]`).
        symbol/timeframe: Betroffenes Symbol/TF.
        t_event: Event-Zeit (Wanduhr-Epoch) des nachtraeglichen Ticks.
        namespace: Optionaler MTF-FC-Namespace – bei Erfolg wird hier
            `cache_generation` inkrementiert (21.03.06 Schritt 3).

    Returns:
        True, wenn genau ein Partitions-Eintrag entfernt wurde; False, wenn
        die Partition nicht (oder nicht mehr) existiert.
    """
    key = partition(symbol, timeframe, t_event)
    if not isinstance(cache, dict) or key not in cache:
        return False
    del cache[key]
    if isinstance(namespace, dict):
        namespace["cache_generation"] = int(namespace.get("cache_generation", 0)) + 1
    return True


def invalidate_partition_via_provider(
    provider: MtfFcProvider,
    context: Any,
    symbol: str,
    timeframe: str,
    t_event: int,
) -> bool:
    """Komfort-Wrapper: Invalidierung direkt ueber den Provider/Namespace."""
    ns = provider.read_namespace(context)
    cache = ns.setdefault("ram_cache", {})
    return invalidate_partition(cache, symbol, timeframe, t_event, ns)
