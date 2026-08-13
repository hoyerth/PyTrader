# serviceui/common_widgets.py
"""
Service-UI: Gemeinsame Widgets (Phase 21.01b, 11.08.2026).

Enthaelt:
  * TfStatusBadgeBar – kleine Pill-Badges je Timeframe mit Status-Info
    (Daten vorhanden / laeuft / Fehler) fuer den MasterTree/ServicePicker
    und das ServiceWindow. Reines Anzeige-Widget ohne Geschaeftslogik
    (SRP): Der Orchestrator versorgt es ueber `update_status`, `set_running`
    und `set_error` mit Werten; die Daten selbst kommen aus
    FeatureStoreReader.fetch_service_tf_status() (21.01b Schritt 1).
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

# ---------------------------------------------------------------------------
# Farb-Schema (dunkles UI; konsistent mit den uebrigen Service-Panels)
# ---------------------------------------------------------------------------
_STYLE_IDLE = ("background-color: #3a3a46; color: #cfd2dc; "
               "border-radius: 3px; border: 1px solid #4a4a58;")
_STYLE_RUNNING = ("background-color: #2f6fb2; color: #ffffff; "
                  "border-radius: 3px; border: 1px solid #5a9bdc;")
_STYLE_ERROR = ("background-color: #b04343; color: #ffffff; "
                "border-radius: 3px; border: 1px solid #d07070;")
_STYLE_HINT = ("background-color: #2c3e2c; color: #9fcf9f; "
               "border-radius: 3px; border: 1px solid #4a7a4a;")

# 13.08.2026 (Punkt 3, F3): Kanonische TF-Reihenfolge (fein -> grob) fuer
# die Pill-Badges. Die Reader-Rueckgabe (fetch_service_tf_status) ist seit
# 13.08.2026 bereits kanonisch sortiert; diese Sortierung sichert das
# Widget zusaetzlich DEFENSIV gegen unsortierte Alt-Daten/Test-Aufrufer ab.
_TF_CANONICAL_ORDER = [
    "M1", "M2", "M5", "M10", "M15", "M30",
    "H1", "H4", "D1", "W1", "MN1",
]


def _sort_tfs_canonical(tfs: list) -> list:
    """Kanonische TF-Reihenfolge (unbekannte TFs am Ende, alphabetisch)."""
    order = {tf: i for i, tf in enumerate(_TF_CANONICAL_ORDER)}
    return sorted(
        (str(t) for t in (tfs or [])
        if t is not None and str(t).strip()),
        key=lambda tf: (order.get(str(tf).upper(), 10 ** 6), str(tf)),
    )


class TfStatusBadgeBar(QWidget):
    """Pill-Badges je Timeframe eines Services (21.01b, Schritt 2).

    Jedes Badge ist ein kleines QLabel (Default ~28x16 px, 9 pt fett,
    Eckenradius 3 px) mit dem Timeframe-Kuerzel. Der Tooltip zeigt die
    Detail-Info aus dem feature_store:
        'M1: 99.000 Eintraege\nZuletzt: 11.08.26 20:15'

    Zustands-Wechsel:
        update_status(map)  – Badges aus dem DB-Status (TF -> {count, last_run})
                              neu aufbauen/aktualisieren (ohne TF-Eintrag
                              bleibt nur das Kuerzel sichtbar).
        set_running(tf|None)– TF waehrend eines Runs blau hervorheben.
        set_error(tf)       – TF nach einem Fehler rot markieren.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._labels: Dict[str, QLabel] = {}
        self._status: Dict[str, Dict[str, Any]] = {}
        self._running: Optional[str] = None
        self._errors: set = set()

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(2)
        self._lay.addStretch(1)  # Badges links buendig, Rest dehnbar

    # ------------------------------------------------------------------
    # Datenversorgung
    # ------------------------------------------------------------------
    def update_status(self, status_map: Dict[str, Dict[str, Any]]) -> None:
        """Baut die TF-Badges aus `fetch_service_tf_status()` auf.

        `status_map`: TF (upper) -> {'count': int, 'last_run': str}. TFs,
        die in der DB existieren, bekommen einen Tooltip; TFs, die
        uebergeben werden, aber nicht in `status_map` stehen, werden mit
        leerem Tooltip (keine Daten) angezeigt.
        """
        self._status = dict(status_map or {})
        # Sichtbare TFs: DB-TFs + aktuell laufende/fehlerhafte TFs (auch
        # ohne DB-Eintrag, z.B. beim ERSTEN Run eines noch leeren Stores).
        known_tfs: list = list(self._status.keys())
        if self._running and self._running not in known_tfs:
            known_tfs.append(self._running)
        for extra in self._errors:
            if extra not in known_tfs:
                known_tfs.append(extra)
        # 13.08.2026 (Punkt 3, F3): Kanonische TF-Reihenfolge (fein -> grob).
        self._rebuild(_sort_tfs_canonical(known_tfs))

    def _rebuild(self, tfs: list) -> None:
        """Erzeugt/entfernt Badge-Labels so, dass `tfs` angezeigt werden."""
        # 13.08.2026 (Punkt 3, F3): Defensive kanonische Sortierung - das
        # Widget rendert TFs unabhaengig von der Aufrufer-Reihenfolge
        # korrekt (fein -> grob).
        tfs = _sort_tfs_canonical(tfs)
        wanted = set(tfs)
        # Entfernen nicht mehr benoetigter Badges
        for tf in list(self._labels.keys()):
            if tf not in wanted:
                lbl = self._labels.pop(tf)
                self._lay.removeWidget(lbl)
                lbl.deleteLater()
        # Fehlende Badges anlegen (vor dem Stretch)
        idx = self._lay.count() - 1  # Stretch ist das letzte Element
        if idx < 0:
            idx = 0
        for tf in tfs:
            if tf in self._labels:
                continue
            lbl = QLabel(str(tf), self)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(28, 16)
            font = lbl.font()
            font.setPointSize(9)
            font.setBold(True)
            lbl.setFont(font)
            self._lay.insertWidget(idx, lbl)
            self._labels[tf] = lbl
            idx += 1
        self._refresh_styles()

    # ------------------------------------------------------------------
    # Zustands-Wechsel
    # ------------------------------------------------------------------
    def set_running(self, tf: Optional[str]) -> None:
        """Hebt den laufenden Timeframe blau hervor (None = nichts laeuft)."""
        self._running = tf
        self._refresh_styles()

    def set_error(self, tf: str) -> None:
        """Markiert einen Timeframe als fehlgeschlagen (rot)."""
        self._errors.add(tf)
        self._refresh_styles()

    def clear_error(self, tf: str) -> None:
        """Entfernt die Fehler-Markierung eines Timeframes."""
        self._errors.discard(tf)
        self._refresh_styles()

    def clear(self) -> None:
        """Leert alle Badges und Zustaende."""
        self._status = {}
        self._running = None
        self._errors.clear()
        self._rebuild([])

    # ------------------------------------------------------------------
    # Interna
    # ------------------------------------------------------------------
    def _refresh_styles(self) -> None:
        """Wendet die aktuelle QSS-Farbe je Badge an und setzt Tooltips."""
        for tf, lbl in self._labels.items():
            if tf == self._running:
                lbl.setStyleSheet(_STYLE_RUNNING)
            elif tf in self._errors:
                lbl.setStyleSheet(_STYLE_ERROR)
            elif tf in self._status:
                lbl.setStyleSheet(_STYLE_IDLE)
            else:
                lbl.setStyleSheet(_STYLE_HINT)
            info = self._status.get(tf)
            if info and info.get("count"):
                count = int(info.get("count") or 0)
                last_run = str(info.get("last_run") or "")
                tip = (f"{tf}: {count:,} Eintraege".replace(",", ".")
                       if count else f"{tf}: keine Eintraege")
                if last_run:
                    tip += f"\nZuletzt: {last_run}"
                lbl.setToolTip(tip)
            else:
                lbl.setToolTip(f"{tf}: keine Daten")
