# analytics/engine/mtf_fc_boundary.py
"""
MTF-FC v4 (Kapitel 21.03.02) – Boundary Policy & Historien-Detection.

Praezise Ermittlung der M1-Verfuegbarkeitsgrenze und Umsetzung der
Boundary Policy (`coverage_status = "native" | "fallback"`, `source_tf`)
gem. §3.2 Ebene 1 und §4 Säule 1.3.

Regeln:
  * `from_ts >= m1_available_from`  -> `coverage_status = "native"`,
    `source_tf = "M1"`.
  * `from_ts <  m1_available_from`  -> `coverage_status = "fallback"`,
    `source_tf` = naechst-hoherer Timeframe, der fuer den Zeitraum Daten
    besitzt (Kandidaten M5, M15, H1, H4, D1; Default H1).
  * **Hartverbot:** Eine hoehere Aggregationsstufe darf niemals als M1
    deklariert werden ($H1 \\to M1$ strikt verboten) – `source_tf` ist immer
    der tatsaechlich verwendete TF.

Reine Logik (kein UI-Import, Grundsatz 4/11). Alle Zeiten sind Wanduhr-Epochs
(Invariante 7).
"""

from typing import Any, Dict, Optional

from analytics.engine.mtf_fc_provider import MtfFcProvider

#: Aufsteigend nach Granularitaet – der naechst-hoherer TF mit Daten.
FALLBACK_TF_CANDIDATES = ("M5", "M15", "H1", "H4", "D1")
#: Default-Fallback, wenn kein Kandidat Daten besitzt (Basis-Aggregation).
DEFAULT_FALLBACK_TF = "H1"

SECONDS_PER_DAY = 86400


def format_available_date(epoch: Optional[int]) -> str:
    """Formatiert die M1-Verfuegbarkeitsgrenze als `DD.MM.JJJJ` (Wanduhr).

    Wanduhr-Garantie (Invariante 7): Die Epoch ist Wanduhr-encoded, daher
    liefert die UTC-Darstellung exakt das Wanduhr-Datum.
    """
    if epoch is None:
        return "unbekannt"
    from datetime import datetime as _dt
    from datetime import timezone as _utc
    d = _dt.fromtimestamp(int(epoch), tz=_utc.utc)
    return f"{d.day:02d}.{d.month:02d}.{d.year:04d}"


class MtfFcBoundary:
    """Boundary-Evaluierung auf Basis des MtfFcProvider (reine Logik)."""

    def __init__(self, provider: Optional[MtfFcProvider] = None) -> None:
        self.provider = provider or MtfFcProvider()

    def resolve_boundary(self, symbol: str) -> Dict[str, Any]:
        """Ermittelt die Historien-Grenze des Symbols.

        Returns:
            {"m1_available_from": Optional[int] (Wanduhr-Epoch),
             "coverage_status": "native",
             "source_tf": "M1"}
        """
        m1_from = self.provider.get_earliest_timestamp(symbol, "M1")
        return {
            "m1_available_from": m1_from,
            "coverage_status": "native" if m1_from is not None else "fallback",
            "source_tf": "M1" if m1_from is not None else DEFAULT_FALLBACK_TF,
        }

    def evaluate_coverage(self, symbol: str, from_ts: Optional[int]) -> Dict[str, Any]:
        """Bewertet die Datenabdeckung fuer einen angefragten Zeitfenster-Start.

        Args:
            symbol: Symbol (z. B. "SILVER").
            from_ts: Linke Viewport-Kante als Wanduhr-Epoch (Optional).

        Returns:
            {"coverage_status": "native" | "fallback",
             "source_tf": "M1" | naechst-hoherer TF,
             "m1_available_from": Optional[int]}
        """
        boundary = self.resolve_boundary(symbol)
        m1_from = boundary["m1_available_from"]

        # Defensiv: keine M1-Daten bekannt -> Fallback auf DEFAULT_FALLBACK_TF.
        if m1_from is None:
            return {
                "coverage_status": "fallback",
                "source_tf": self._find_fallback_source(symbol, from_ts),
                "m1_available_from": None,
            }

        # from_ts unbekannt -> native (Standard-Annahme: Daten vorhanden).
        if from_ts is None:
            return {
                "coverage_status": "native",
                "source_tf": "M1",
                "m1_available_from": m1_from,
            }

        if from_ts >= m1_from:
            return {
                "coverage_status": "native",
                "source_tf": "M1",
                "m1_available_from": m1_from,
            }

        # Zoom vor die M1-Grenze -> Fallback auf naechst-hoherer TF mit Daten.
        return {
            "coverage_status": "fallback",
            "source_tf": self._find_fallback_source(symbol, from_ts),
            "m1_available_from": m1_from,
        }

    def _find_fallback_source(self, symbol: str, from_ts: Optional[int]) -> str:
        """Naechst-hoherer TF, dessen Daten die linke Kante abdecken.

        Es gewinnt der erste Kandidat (feinster zuerst), dessen aeltester Bar
        <= from_ts liegt (d. h. der Zeitraum ist abgedeckt). Liefert kein
        Kandidat Daten, wird DEFAULT_FALLBACK_TF verwendet.
        """
        for tf in FALLBACK_TF_CANDIDATES:
            earliest = self.provider.get_earliest_timestamp(symbol, tf)
            if earliest is None:
                continue
            if from_ts is None or earliest <= from_ts:
                return tf
        return DEFAULT_FALLBACK_TF
