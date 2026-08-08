# analytics/ui/table_page.py
"""
table_page.py - Tabellen-Seite der Analytics-UI (Phase 15.03 / 19.01).

Zeigt die rohen Feature-Store-Zeilen (Tabelle) und koppelt einen
Doppelklick an 'Jump-to-Chart' (Variante 2): open_chart_at_bar(symbol, tf,
bar_time) wird aufgerufen und das Chart-Fenster in den Vordergrund geholt.

MVVM (Invariante 4): Die Page ist reine UI – Rendering + Event-Handling.
Die Daten kommen ueber `data_ready(QUERY_TABLE, data)` vom ViewModel
(Async-Worker); es gibt KEIN SQL in dieser Klasse.

19.01 (Step 2) – Multi-Service-Darstellung:
- Spalte 1 = **Service** (feature_id bzw. via injiziertem `name_resolver`
  aufgeloester Anzeigename, E3/IoC – kein SQL, keine Modell-Kopplung).
- Standard-Spaltenreihenfolge: [Zeit (Wanduhr), Service, ema_diff, rsi_14,
  atr_normalized, ...JSON-Union-Keys alphabetisch] (E4).
- **Chronologisch ABSTEIGEND** nach bar_time (E2): Die Page sortiert die
  erhaltenen Rows deterministisch (stabil); die QTableWidget-Interaktions-
  sortierung bleibt deaktiviert, damit die Service-Mischung korrekt bleibt.
  Der `FeatureStoreReader` (ASC-Vertrag) bleibt unveraendert.
- JSON-Union: Vereinigung aller `feature_data`-Keys ueber die geladenen
  Rows; fehlende Werte bei abweichenden Services -> "-".
"""

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import QUERY_TABLE
from analytics.ui.common import format_wanduhr_time, make_overlay_stack

# Basis-Spalten (19.01): Reihenfolge laut Kapitel
# [Zeitstempel, Service, ema_diff, rsi_14, atr_normalized, ...Union-Keys].
_BASE_COLUMNS = [
    ("Zeit (Wanduhr)", 150),
    ("Service", 160),
    ("ema_diff", 90),
    ("rsi_14", 80),
    ("atr_normalized", 100),
]
# Feste Breite der dynamischen JSON-Union-Spalten (feature_data-Keys).
_EXTRA_COLUMN_WIDTH = 110
# Native Feature-Spalten (indiziert in _BASE_COLUMNS ab Spalte 2).
_NATIVE_KEYS = ("ema_diff", "rsi_14", "atr_normalized")
# Spalten-Indizes der Basis-Spalten (fuer Jump-to-Chart / Zeit-UserRole).
_COL_TIME = 0
_COL_SERVICE = 1


def _epoch_int(value: Any) -> Optional[int]:
    """Wandelt einen bar_time-Wert in die Wanduhr-Epoch (int) um (oder None).

    Defensiv: fetch_rows() liefert bereits int-Epochs; dieser Helfer schuetzt
    vor Alt-Rows/ungueltigen Werten beim Sortieren und im UserRole.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class TablePage(QWidget):
    """Feature-Store-Tabelle mit Jump-to-Chart (Doppelklick)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None
        self._navigation_handler: Optional[Callable[[str, str, int], None]] = None
        # 19.01 (E3): Injizierbarer Namensaufloeser (feature_ids -> Namen).
        # Default: feature_id selbst anzeigen (kein UI->Modell-Zwang).
        self._name_resolver: Callable[[List[str]], List[str]] = lambda ids: list(ids)
        # Roh-Rows der aktuellen Anzeige (fuer Jump-to-Chart, unabhaengig
        # von Tabellen-Spalten-Positionen).
        self._current_rows: List[Dict[str, Any]] = []

        self._header = QLabel("Feature-Store-Tabelle")
        self._table = QTableWidget(0, len(_BASE_COLUMNS))
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setHorizontalHeaderLabels([c[0] for c in _BASE_COLUMNS])
        header = self._table.horizontalHeader()
        # Fix 15.03 (TF-Wechsel-Haenger): KEIN ResizeToContents! Der Modus
        # berechnet bei JEDEM setItem die optimale Breite ueber ALLE Zeilen
        # (O(n^2)) – bei 5000 Zeilen blockiert das den Main-Thread minuten-
        # lang. Stattdessen FIXE Spaltenbreiten aus _BASE_COLUMNS
        # (deterministisch schnell, unabhaengig von der Zeilenanzahl).
        header.setStretchLastSection(False)
        for i, (_, width) in enumerate(_BASE_COLUMNS):
            header.setSectionResizeMode(i, QHeaderView.Fixed)
            self._table.setColumnWidth(i, width)
        # 19.01 (E2): Interaktions-Sortierung bleibt DEAKTIVIERT – die Page
        # zeichnet deterministisch ABSTEIGEND nach bar_time (Service-Mischung
        # bleibt chronologisch korrekt; kein haengender O(n^2)-Sort).
        self._table.setSortingEnabled(False)

        content = QWidget(self)
        lay = QVBoxLayout(content)
        lay.addWidget(self._header)
        lay.addWidget(self._table)
        self._stack = make_overlay_stack(content)
        self.setLayout(self._stack)

        self._table.itemDoubleClicked.connect(self._on_double_clicked)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (vom AnalyticsWindow gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        """Verbindet die Page mit dem AnalyticsViewModel (data_ready)."""
        self._view_model = view_model
        view_model.data_ready.connect(self.on_data_ready)

    def set_navigation_handler(
        self, fn: Callable[[str, str, int], None]
    ) -> None:
        """Setzt den Jump-to-Chart-Handler (open_chart_at_bar)."""
        self._navigation_handler = fn

    def set_name_resolver(
        self, fn: Callable[[List[str]], List[str]]
    ) -> None:
        """Setzt den Service-Namensaufloeser (19.01 E3, IoC).

        `fn` bildet feature_ids (plugin_ids) auf Anzeigenamen ab (z. B.
        `ServiceSelectorModel.resolve_display_names`). Default: die
        feature_id selbst anzeigen. Kein SQL / keine Modell-Kopplung.
        """
        if callable(fn):
            self._name_resolver = fn

    def request_data(self) -> None:
        """Fordert die Tabellen-Daten ueber das ViewModel an."""
        if self._view_model is not None:
            self._view_model.request_table()

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind != QUERY_TABLE:
            return
        if not self.isVisible():
            # Fix 15.03 (TF-Wechsel-Haenger): Die Tabelle wird NUR gerendert,
            # wenn sie die aktive/ sichtbare Seite ist. data_ready feuert bei
            # jedem TF-Wechsel fuer ALLE Seiten; ein versteckter 5000-Zeilen-
            # Render (ResizeToContents + Sortierung) wuerde den Main-Thread
            # blockieren. Beim Aktivieren der Seite fordert _on_page_changed
            # die Daten erneut an (request_data -> frischer Query).
            return
        rows = data.get("rows") or []
        self._populate(rows)
        self._stack.setCurrentIndex(0 if rows else 1)

    def _populate(self, rows: List[Dict[str, Any]]) -> None:
        """Baut die Multi-Service-Tabelle (19.01 Step 2).

        Sortiert ABSTEIGEND nach bar_time (E2), bildet die JSON-Union der
        feature_data-Keys (E4) und zeigt die Service-Spalte mit aufgeloesten
        Anzeigenamen (E3). Fehlende Werte bei abweichenden Services -> "-".
        """
        # E2: Chronologisch absteigend (deterministisch, stabil). Rows ohne
        # time landen dank `or 0` am Ende der absteigenden Anzeige.
        sorted_rows = sorted(
            (r for r in rows if isinstance(r, dict)),
            key=lambda r: _epoch_int(r.get("time")) or 0,
            reverse=True,
        )
        self._current_rows = sorted_rows

        # E4: Union aller feature_data-JSON-Keys (alphabetisch).
        extra_keys = sorted(self._union_feature_keys(sorted_rows))

        # Dynamischer Spaltenaufbau: Basis + Union-Keys.
        headers = [c[0] for c in _BASE_COLUMNS] + list(extra_keys)
        widths = ([c[1] for c in _BASE_COLUMNS]
                  + [_EXTRA_COLUMN_WIDTH] * len(extra_keys))
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        for i, w in enumerate(widths):
            header.setSectionResizeMode(i, QHeaderView.Fixed)
            self._table.setColumnWidth(i, w)

        # E3: Anzeigenamen einmalig fuer die vorliegenden Rows aufloesen.
        service_names = self._resolve_names(sorted_rows)
        extra_start = len(_BASE_COLUMNS)

        self._table.setUpdatesEnabled(False)
        self._table.setRowCount(len(sorted_rows))
        for r, row in enumerate(sorted_rows):
            # Zeit: Wanduhr-Formatierung (Invariante 7) + Roh-Epoch im
            # UserRole fuer Jump-to-Chart.
            epoch = _epoch_int(row.get("time"))
            time_item = QTableWidgetItem(format_wanduhr_time(epoch))
            if epoch is not None:
                time_item.setData(Qt.UserRole, epoch)
            self._table.setItem(r, _COL_TIME, time_item)
            # Spalte 1 = Service (feature_id bzw. Anzeigename, E3).
            self._table.setItem(r, _COL_SERVICE,
                                QTableWidgetItem(service_names[r] or "-"))
            # Native Feature-Spalten (ema_diff, rsi_14, atr_normalized).
            for ci, key in enumerate(_NATIVE_KEYS, start=2):
                v = row.get(key)
                if isinstance(v, (int, float)):
                    self._table.setItem(r, ci, QTableWidgetItem(f"{v:.4f}"))
                else:
                    self._table.setItem(r, ci, QTableWidgetItem("-"))
            # JSON-Union-Spalten: Wert aus feature_data, sonst "-".
            fd = row.get("feature_data")
            if not isinstance(fd, dict):
                fd = {}
            for ci, key in enumerate(extra_keys, start=extra_start):
                v = fd.get(key)
                if v is None:
                    self._table.setItem(r, ci, QTableWidgetItem("-"))
                elif isinstance(v, (int, float)):
                    self._table.setItem(r, ci, QTableWidgetItem(f"{v:.4g}"))
                else:
                    self._table.setItem(r, ci, QTableWidgetItem(str(v)))
        self._table.setUpdatesEnabled(True)

    # ------------------------------------------------------------------
    # 19.01 Step 2: Helfer (JSON-Union, Namensaufloesung)
    # ------------------------------------------------------------------
    @staticmethod
    def _union_feature_keys(rows: List[Dict[str, Any]]) -> set:
        """Union aller feature_data-JSON-Keys (19.01 E4).

        Keys, die mit Basis-/Pflicht-Spalten (Zeit, Service) oder nativen
        Spalten (ema_diff, rsi_14, atr_normalized) kollidieren, werden
        ignoriert (keine Duplikat-Header); leere/Whitespace-Keys ebenfalls.
        """
        base = {c[0] for c in _BASE_COLUMNS} | set(_NATIVE_KEYS)
        keys: set = set()
        for row in rows:
            fd = row.get("feature_data")
            if not isinstance(fd, dict):
                continue
            for k in fd.keys():
                s = str(k).strip()
                if s and s not in base:
                    keys.add(s)
        return keys

    def _resolve_names(self, rows: List[Dict[str, Any]]) -> List[str]:
        """Loest die Service-Anzeigenamen der Rows einmalig auf (19.01 E3).

        Baut die deduplizierte feature_id-Liste (Reihenfolge des ersten
        Auftretens), ruft den injizierten `name_resolver` EINMAL auf und
        bildet die Namen auf die Rows ab. Rows ohne feature_id -> "-".
        Defensiv: Fehler im Resolver / abweichende Laenge -> feature_id.
        """
        unique: List[str] = []
        index: Dict[str, int] = {}
        for row in rows:
            fid = row.get("feature_id")
            key = str(fid) if fid else ""
            if key not in index:
                index[key] = len(unique)
                unique.append(key)
        try:
            resolved = self._name_resolver(unique)
        except Exception:
            resolved = unique
        by_id = dict(zip(unique, resolved))
        out: List[str] = []
        for row in rows:
            fid = row.get("feature_id")
            key = str(fid) if fid else ""
            out.append(by_id.get(key, key) if key else "-")
        return out

    # ------------------------------------------------------------------
    # Jump-to-Chart (Variante 2)
    # ------------------------------------------------------------------
    def _on_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if row < 0 or self._navigation_handler is None:
            return
        if row >= len(self._current_rows):
            return
        # 19.01: Symbol/TF/Zeit kommen aus der Roh-Row (nicht aus festen
        # Spaltenpositionen – die Spalten sind jetzt dynamisch).
        row_data = self._current_rows[row]
        symbol = row_data.get("symbol")
        tf = row_data.get("timeframe")
        bar_time = row_data.get("time")
        if not symbol or not tf or bar_time is None:
            return
        try:
            bar_time = int(bar_time)
        except (TypeError, ValueError):
            return
        self._navigation_handler(str(symbol), str(tf), bar_time)
