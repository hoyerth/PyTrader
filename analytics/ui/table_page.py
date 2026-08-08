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
- Standard-Spaltenreihenfolge: [Zeit (Wanduhr), Service,
  ...JSON-Union-Keys alphabetisch] (E4).
- **Chronologisch ABSTEIGEND** nach bar_time (E2): Die Page sortiert die
  erhaltenen Rows deterministisch (stabil); die QTableWidget-Interaktions-
  sortierung bleibt deaktiviert, damit die Service-Mischung korrekt bleibt.
  Der `FeatureStoreReader` (ASC-Vertrag) bleibt unveraendert.
- JSON-Union: Vereinigung aller `feature_data`-Keys ueber die geladenen
  Rows; fehlende Werte bei abweichenden Services -> "-".

19.02 (Cleanup + Schrift):
- Legacy-Native-Spalten ema_diff/rsi_14/atr_normalized sind ENTFERNT –
  die Tabelle zeigt nur noch Zeit + Service + dynamische JSON-Union.
- Kleinere Schrift (9 pt): bei gleicher Fenstergroesse sind mehr Zeilen
  (Zeilenhoehe folgt der Schrift) und mehr Spalten (schmalere Spalten)
  sichtbar.

19.03 (Resizing, In-Memory-Sorting & Profil-Persistenz):
- Interaktives Resizing: Spaltenbreiten und Zeilenhoehen sind per
  QHeaderView.Interactive frei anpassbar (Step 1).
- In-Memory-Sortierung: QTableWidget-Sortierung wird NACH dem Befuellen
  aktiviert (O(n^2)-Schutz); die Zeitspalte sortiert numerisch ueber die
  Roh-Epoch (_SortableTimeItem, E2/E3). 19.01-E2 (deterministisch
  absteigende Roh-Liste `_current_rows`) bleibt fuer Jump-to-Chart unveraendert.
- Profil-Persistenz (Option B – Explicit Save): User-Aenderungen emittieren
  `table_settings_changed` (Breiten {Name: Breite}, Zeilenhoehe, Sortierung);
  das AnalyticsWindow reicht sie an `AnalyticsViewModel.set_table_settings()`
  (nur Dirty, kein Query-Refresh). Beim Befuellen werden die gespeicherten
  Settings wiederhergestellt (E1/E8/E9); Signale sind waehrenddessen blockiert
  (E4).
- Jump-to-Chart-Row-Mapping (E7): Der `_current_rows`-Einfuege-Index liegt im
  UserRole+1 des Zeit-Items – unabhaengig von der Anzeige-Sortierung.

19.04 (Paging, Bugfix 08.08.2026):
- Paging wieder eingebaut (Legacy-Muster aus statistic_win.py): Vor/Zurueck-
  Buttons + Seitenlabel unter der Tabelle. Die geladenen `_current_rows`
  (bis zum Limit aus analytics_win) werden in Seiten der Groesse
  `statistics_page_size` (AppSettings, via `set_page_size()` injiziert)
  aufgeteilt; `_current_rows` haelt weiterhin ALLE Zeilen (Jump-to-Chart/
  Seitenwechsel). Nach Daten-Update springt die Anzeige auf Seite 0.
- Beim Seitenwechsel bleibt die aktive User-Sortierung erhalten (nur die
  Anzeige-Seite wird neu gerendert, Roh-Liste unveraendert).
"""

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import QUERY_TABLE
from analytics.ui.common import format_wanduhr_time, make_overlay_stack

# 19.02 (Cleanup): Basis-Spalten OHNE Legacy-Native-Spalten – nur Zeit +
# Service. Alle Feature-Werte kommen dynamisch aus feature_data (JSON-Union).
_BASE_COLUMNS = [
    ("Zeit (Wanduhr)", 130),
    ("Service", 150),
]
# Feste Breite der dynamischen JSON-Union-Spalten (feature_data-Keys).
_EXTRA_COLUMN_WIDTH = 95
# Spalten-Indizes der Basis-Spalten (fuer Jump-to-Chart / Zeit-UserRole).
_COL_TIME = 0
_COL_SERVICE = 1
# 19.02 (Task 1): Schriftgroesse der Tabelle (kleiner -> mehr Zeilen/Spalten).
_TABLE_FONT_PT = 9


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


class _SortableTimeItem(QTableWidgetItem):
    """Zeit-Spalten-Item mit numerischem Zeitvergleich (19.03 E2).

    QTableWidget sortiert standardmaessig nach `__lt__` (= text()-Vergleich).
    Das Wanduhr-Format ('Fr 31.07.26 00:01') ist lexikografisch NICHT
    chronologisch – diese Subklasse vergleicht die Roh-Epoch aus dem
    UserRole numerisch (Fallback auf die Text-Sortierung).
    """

    def __lt__(self, other) -> bool:
        if isinstance(other, QTableWidgetItem):
            try:
                a = self.data(Qt.UserRole)
                b = other.data(Qt.UserRole)
                if a is not None and b is not None:
                    return int(a) < int(b)
            except (TypeError, ValueError):
                pass
        return super().__lt__(other)


class TablePage(QWidget):
    """Feature-Store-Tabelle mit Jump-to-Chart (Doppelklick)."""

    # 19.03 (Step 1): UI-Change-Signal fuer Tabellen-Settings (Spaltenbreiten
    # {Name: Breite}, Zeilenhoehe, Sortier-Spalte/-Richtung). Wird vom
    # AnalyticsWindow an `AnalyticsViewModel.set_table_settings()` verdrahtet
    # (Profil-Persistenz, Option B – Explicit Save; E6: kein Query-Refresh).
    table_settings_changed = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None
        self._navigation_handler: Optional[Callable[[str, str, int], None]] = None
        # 19.01 (E3): Injizierbarer Namensaufloeser (feature_ids -> Namen).
        # Default: feature_id selbst anzeigen (kein UI->Modell-Zwang).
        self._name_resolver: Callable[[List[str]], List[str]] = lambda ids: list(ids)
        # Roh-Rows der aktuellen Anzeige (fuer Jump-to-Chart, unabhaengig
        # von Tabellen-Spalten-Positionen). 19.04 (Paging): haelt ALLE
        # geladenen Zeilen (bis Limit); angezeigt wird nur die aktuelle Seite.
        self._current_rows: List[Dict[str, Any]] = []
        # 19.04 (Paging): Zeilen pro Seite (via set_page_size aus den
        # AppSettings statistics_page_size injiziert; Default 100), aktuelle
        # Seite und Gesamtseitenzahl.
        self._page_size: int = 100
        self._current_page: int = 0
        self._total_pages: int = 1

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
        # lang. Stattdessen deterministische Startbreiten aus _BASE_COLUMNS
        # (setColumnWidth unten); der User kann sie seit 19.03 interaktiv
        # anpassen (QHeaderView.Interactive, Step 1).
        header.setStretchLastSection(False)
        # 19.03 (Step 1): Interaktives Resizing – Spaltenbreiten und
        # Zeilenhoehen sind frei anpassbar. Die FIXEN Defaults aus
        # _BASE_COLUMNS/_EXTRA_COLUMN_WIDTH bleiben als Startbreiten beim
        # ersten Befuellen erhalten (siehe _populate / _get_settings_widths).
        header.setSectionResizeMode(QHeaderView.Interactive)
        self._table.verticalHeader().setSectionResizeMode(
            QHeaderView.Interactive)
        for i, (_, width) in enumerate(_BASE_COLUMNS):
            self._table.setColumnWidth(i, width)
        # 19.01 (E2) + 19.03 (E3): Die Page zeichnet `_current_rows`
        # deterministisch ABSTEIGEND nach bar_time (Service-Mischung bleibt
        # chronologisch korrekt). Die QTableWidget-Interaktions-Sortierung
        # (setSortingEnabled(True)) wird seit 19.03 NACH dem Befuellen
        # aktiviert (sonst O(n^2)-Re-Sort bei jedem setItem) – sie sortiert
        # nur die ANZEIGE, nicht die Roh-Liste (E7-Row-Mapping).
        self._table.setSortingEnabled(False)
        # 19.02 (Task 1): Kleinere Schrift – mehr Zeilen (Zeilenhoehe folgt
        # der Schrift) und mehr Spalten sichtbar bei gleicher Fenstergroesse.
        table_font = QFont()
        table_font.setPointSize(_TABLE_FONT_PT)
        self._table.setFont(table_font)
        header_font = QFont(table_font)
        header_font.setBold(True)
        header.setFont(header_font)
        # 19.03 (Step 1): UI-Change-Signale – Breiten-/Zeilen-Resize und
        # Sortier-Indikator emittieren table_settings_changed (Persistenz).
        # Waehrend _populate sind die Header blockiert (E4), sodass nur echte
        # User-Aktionen emittieren.
        header.sectionResized.connect(self._on_header_section_resized)
        header.sortIndicatorChanged.connect(self._on_sort_indicator_changed)
        self._table.verticalHeader().sectionResized.connect(
            self._on_vertical_section_resized)

        content = QWidget(self)
        lay = QVBoxLayout(content)
        lay.addWidget(self._header)
        lay.addWidget(self._table)
        # 19.04 (Paging): Leiste mit Zurueck/Weiter + Seitenlabel unter der
        # Tabelle (Muster statistic_win.py: btn_prev_page/btn_next_page/
        # label_page_info). Zeigt die Seite und die Gesamtzahl der geladenen
        # Zeilen; Buttons werden je nach Position ein-/ausgegraut.
        self.btn_prev = QPushButton("◀ Zurück")
        self.btn_next = QPushButton("Weiter ▶")
        self.label_page = QLabel("Seite 1 / 1")
        page_bar = QWidget(self)
        page_lay = QHBoxLayout(page_bar)
        page_lay.setContentsMargins(0, 2, 0, 0)
        page_lay.setSpacing(6)
        page_lay.addWidget(self.btn_prev)
        page_lay.addWidget(self.label_page)
        page_lay.addWidget(self.btn_next)
        page_lay.addStretch(1)
        lay.addWidget(page_bar)
        self._stack = make_overlay_stack(content)
        self.setLayout(self._stack)

        self._table.itemDoubleClicked.connect(self._on_double_clicked)
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_next.clicked.connect(self._next_page)

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

    def set_page_size(self, page_size: int) -> None:
        """Setzt die Zeilen pro Seite (Paging, 19.04; IoC vom AnalyticsWindow).

        Der Wert kommt aus den AppSettings (`statistics_page_size`). Bei
        bereits geladenen Daten wird die aktuelle Seite neu gerendert (Seite
        wird auf 0 zurueckgesetzt).
        """
        try:
            ps = int(page_size)
        except (TypeError, ValueError):
            ps = 100
        if ps <= 0:
            ps = 100
        if ps == self._page_size:
            return
        self._page_size = ps
        if self._current_rows:
            self._current_page = 0
            self._render_current_page()

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
        default_widths = ([c[1] for c in _BASE_COLUMNS]
                          + [_EXTRA_COLUMN_WIDTH] * len(extra_keys))
        header = self._table.horizontalHeader()
        vheader = self._table.verticalHeader()

        # 19.03 (E3/E4): Signale waehrend des Befuellens blockieren – sonst
        # wuerden setColumnWidth/setSortingEnabled/sortItems als User-Aktion
        # interpretiert und ein ungewolltes Dirty-Flag/Persistieren ausloesen.
        # Die In-Memory-Sortierung wird erst NACH dem Befuellen aktiviert
        # (O(n^2)-Schutz: QTableWidget sortiert sonst bei JEDEM setItem).
        self._table.setUpdatesEnabled(False)
        blocked = (self._table, header, vheader)
        for w in blocked:
            w.blockSignals(True)
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        header.setStretchLastSection(False)
        # 19.03 (Step 1/E5): Interactive + gespeicherte Profil-Breiten
        # {Spaltenname: Breite} ueberschreiben die Defaults (fehlende neue
        # Union-Spalten -> _BASE_COLUMNS/_EXTRA_COLUMN_WIDTH).
        settings_widths = self._get_settings_widths()
        for i, name in enumerate(headers):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
            self._table.setColumnWidth(
                i, int(settings_widths.get(name, default_widths[i])))

        # 19.04 (Paging): Seite zuruecksetzen und nur die aktuelle Seite
        # rendern (Seitenaufbau in _render_current_page/_populate_rows;
        # Sortierung/Settings werden dort angewendet).
        self._current_page = 0
        self._render_current_page()
        self._table.setUpdatesEnabled(True)
        for w in blocked:
            w.blockSignals(False)

    # ------------------------------------------------------------------
    # 19.04: Paging (Muster statistic_win.py, Bugfix 08.08.2026)
    # ------------------------------------------------------------------
    def _prev_page(self) -> None:
        """Eine Seite zurueck (aktiviert sobald _current_page > 0)."""
        if self._current_page > 0:
            self._current_page -= 1
            self._render_current_page()

    def _next_page(self) -> None:
        """Eine Seite vor (aktiviert solange nicht auf der letzten Seite)."""
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._render_current_page()

    def _render_current_page(self) -> None:
        """Rendert die Zeilen der aktuellen Seite (19.04 Paging).

        `_current_rows` haelt ALLE geladenen Zeilen (bis Limit) – angezeigt
        wird nur der Ausschnitt `[current_page*page_size : +page_size]`.
        Die Signale sind waehrend des Neu-Befuellens blockiert (E4), damit
        setItem/sortItems nicht als User-Aktion (Dirty-Flag/Persistieren)
        gewertet werden. Nach dem Befuellen werden die Tabellen-Settings
        angewandt (Sortierung; bei aktiver User-Sortierung bleibt der
        Indikator erhalten).
        """
        page_size = self._page_size if self._page_size > 0 else 1
        total = len(self._current_rows)
        self._total_pages = max(1, (total + page_size - 1) // page_size)
        if self._current_page >= self._total_pages:
            self._current_page = max(0, self._total_pages - 1)
        start = self._current_page * page_size
        end = min(start + page_size, total)
        page_rows = self._current_rows[start:end]

        header = self._table.horizontalHeader()
        vheader = self._table.verticalHeader()
        blocked = (self._table, header, vheader)
        for w in blocked:
            w.blockSignals(True)
        try:
            self._table.setSortingEnabled(False)
            self._populate_rows(page_rows, start_offset=start)
            self._apply_table_settings()
        finally:
            for w in blocked:
                w.blockSignals(False)
        self._update_page_controls()

    def _populate_rows(
        self, rows: List[Dict[str, Any]], start_offset: int = 0
    ) -> None:
        """Befuellt die Tabellen-Zeilen einer Seite (19.04 Paging).

        Der UserRole+1 (E7, Jump-to-Chart-Row-Mapping) traegt den GLOBALEN
        `_current_rows`-Index (`start_offset + r`), damit ein Doppelklick
        unabhaengig von Seite und Anzeige-Sortierung die richtige Roh-Row
        trifft.
        """
        service_names = self._resolve_names(rows)
        extra_keys = sorted(self._union_feature_keys(self._current_rows))
        extra_start = len(_BASE_COLUMNS)

        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            global_r = start_offset + r
            # Zeit: Wanduhr-Formatierung (Invariante 7) + Roh-Epoch im
            # UserRole (numerische Sortierung, E2) + globaler Einfuege-Index
            # im UserRole+1 (Jump-to-Chart, E7).
            epoch = _epoch_int(row.get("time"))
            time_item = _SortableTimeItem(format_wanduhr_time(epoch))
            if epoch is not None:
                time_item.setData(Qt.UserRole, epoch)
            time_item.setData(Qt.UserRole + 1, global_r)
            self._table.setItem(r, _COL_TIME, time_item)
            # Spalte 1 = Service (feature_id bzw. Anzeigename, E3).
            self._table.setItem(r, _COL_SERVICE,
                                QTableWidgetItem(service_names[r] or "-"))
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

    def _update_page_controls(self) -> None:
        """Synchronisiert Seitenlabel + Button-Zustaende (19.04 Paging)."""
        total = len(self._current_rows)
        self.label_page.setText(
            f"Seite {self._current_page + 1} / {max(self._total_pages, 1)}"
            f"  ({total} Zeilen)")
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(
            self._current_page < self._total_pages - 1)

    # ------------------------------------------------------------------
    # 19.03: Tabellen-Settings (Resizing / Sortierung / Profil-Persistenz)
    # ------------------------------------------------------------------
    def _on_header_section_resized(self, *args) -> None:
        """Spaltenbreite geaendert (User) -> Settings emittieren (19.03)."""
        self._emit_table_settings()

    def _on_vertical_section_resized(self, *args) -> None:
        """Zeilenhoehe geaendert (User) -> Settings emittieren (19.03)."""
        self._emit_table_settings()

    def _on_sort_indicator_changed(self, *args) -> None:
        """Sortier-Indikator geaendert (User) -> Settings emittieren (19.03)."""
        self._emit_table_settings()

    def _emit_table_settings(self) -> None:
        """Emittiert den kompletten Tabellen-Zustand (19.03 E5/E9).

        Spaltenbreiten als {Header-Text: Breite} (E5 – robust gegenueber der
        dynamischen JSON-Union), Zeilenhoehe als Hoehe der ersten Zeile bzw.
        Default-Section-Size (E9, ein Wert fuer alle Zeilen), Sortier-Spalte
        und -Richtung als Qt-Werte (E8 – Validierung beim Anwenden).
        """
        widths: Dict[str, int] = {}
        header = self._table.horizontalHeader()
        for i in range(self._table.columnCount()):
            item = self._table.horizontalHeaderItem(i)
            if item is not None:
                widths[str(item.text())] = int(header.sectionSize(i))
        vheader = self._table.verticalHeader()
        row_height = int(vheader.defaultSectionSize())
        if self._table.rowCount() > 0:
            row_height = int(vheader.sectionSize(0))
        sort_col = int(header.sortIndicatorSection())
        if sort_col < 0:
            sort_col = 0
        # PySide6: sortIndicatorOrder() liefert den Qt.SortOrder-Enum (nicht
        # direkt int-konvertierbar) – robust ueber den Enum-Vergleich mappen.
        order = header.sortIndicatorOrder()
        self.table_settings_changed.emit({
            "column_widths": widths,
            "row_height": row_height,
            "sort_column": sort_col,
            "sort_order": 1 if order == Qt.DescendingOrder else 0,
        })

    def _get_settings_widths(self) -> Dict[str, int]:
        """Gespeicherte Spaltenbreiten aus dem ViewModel (19.03 E5).

        {Spaltenname: Breite} – robust gegenueber der dynamischen JSON-Union
        (fehlende neue Spalten fallen auf _BASE_COLUMNS/_EXTRA_COLUMN_WIDTH
        zurueck). Defensiv: ohne ViewModel/leer -> {}.
        """
        if self._view_model is None:
            return {}
        raw = self._view_model.params.get("table_column_widths") or {}
        out: Dict[str, int] = {}
        for k, v in raw.items():
            try:
                w = int(v)
            except (TypeError, ValueError):
                continue
            if w > 0:
                out[str(k)] = w
        return out

    def _apply_table_settings(self) -> None:
        """Wendet die gespeicherten Tabellen-Settings an (19.03 E3/E8/E9).

        Wird am Ende von _populate gerufen (Header-Signale sind blockiert):
        Zeilenhoehe (Default-Section-Size, E9) und Sortier-Spalte/-Richtung
        (validiert, E8). Spaltenbreiten uebernimmt bereits der Spaltenaufbau
        aus _get_settings_widths(). Ohne ViewModel (z. B. Headless-Tests)
        bleibt die Sortierung deaktiviert – Settings gibt es nicht.
        """
        if self._view_model is None:
            return
        params = self._view_model.params
        # Zeilenhoehe (E9): eine Default-Hoehe fuer alle Zeilen.
        try:
            row_height = int(params.get("table_row_height") or 0)
        except (TypeError, ValueError):
            row_height = 0
        if row_height > 0:
            self._table.verticalHeader().setDefaultSectionSize(row_height)
        # Sortierung (E8): Spalten-Index validieren, Order auf Qt-Werte klemmen.
        try:
            sort_col = int(params.get("table_sort_column") or 0)
        except (TypeError, ValueError):
            sort_col = 0
        try:
            sort_order = int(params.get("table_sort_order") or 1)
        except (TypeError, ValueError):
            sort_order = 1
        sort_order = (Qt.DescendingOrder if sort_order
                      else Qt.AscendingOrder)
        if not (0 <= sort_col < self._table.columnCount()):
            sort_col = 0
        self._table.setSortingEnabled(True)
        self._table.sortItems(sort_col, sort_order)

    # ------------------------------------------------------------------
    # 19.01 Step 2: Helfer (JSON-Union, Namensaufloesung)
    # ------------------------------------------------------------------
    @staticmethod
    def _union_feature_keys(rows: List[Dict[str, Any]]) -> set:
        """Union aller feature_data-JSON-Keys (19.01 E4 / 19.02).

        19.02: Es gibt keine nativen Spalten mehr – es werden nur noch die
        Basis-/Pflicht-Spalten (Zeit, Service) von der Union ausgenommen
        (keine Duplikat-Header); leere/Whitespace-Keys ebenfalls.
        """
        base = {c[0] for c in _BASE_COLUMNS}
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
        if item is None or self._navigation_handler is None:
            return
        # 19.03 (E7): Bei aktiver QTableWidget-Sortierung entspricht die
        # Anzeige-Zeile nicht mehr der _current_rows-Reihenfolge – der
        # Roh-Row-Index wird stattdessen aus dem UserRole+1 des Zeit-Items
        # aufgeloest (unabhaengig von der Anzeige-Sortierung).
        time_item = self._table.item(item.row(), _COL_TIME)
        if time_item is None:
            return
        row_index = time_item.data(Qt.UserRole + 1)
        if row_index is None:
            return
        try:
            row_index = int(row_index)
        except (TypeError, ValueError):
            return
        if not (0 <= row_index < len(self._current_rows)):
            return
        # 19.01: Symbol/TF/Zeit kommen aus der Roh-Row (nicht aus festen
        # Spaltenpositionen – die Spalten sind jetzt dynamisch).
        row_data = self._current_rows[row_index]
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
