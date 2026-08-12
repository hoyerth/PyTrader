# PROJEKT-ÜBERSICHT: PyTrader — Weitere Fenster, Worker & Konfiguration

> Teil-Export (sachbezogen). Vollständiger Export: export_Full.md
> Dateien in dieser Datei: 15

## 1. ORDNERSTRUKTUR
```
PyTrader/
    config/
        __init__.py
        app_settings.py
        base_state_model.py
        event_bus.py
    scrollable_content.py
    statistic_win.py
    ui/
        __init__.py
        chart_win.ui
        main_win.ui
        service_win.ui
        statistic_win.ui
        window_manager.py
    workers/
        __init__.py
        data_sync_worker.py
        live_tick_worker.py
```

## 2. QUELLCODE

### DATEI: scrollable_content.py
```py
# scrollable_content.py
"""
Gemeinsame Scroll- & Größendynamik für Inhaltsfenster (Phase 13 5.4).

Problem: Servicefenster und Indikator-Prop-Fenster leiten ihre Größe vollständig
aus dem Inhalt ab (KEINE fixen Pixelwerte). Wächst der Inhalt (z.B. viele
Service-Spalten, aufgeklappte Experten-Optionen) über die Bildschirmhöhe,
würde das Fenster den Bildschirm überragen – ohne Möglichkeit, an den Inhalt
heranzukommen.

Lösung (ContentScrollMixin):
* Der Inhalt behält seine natürliche Größe (QScrollArea.widgetResizable=False,
  Inhalt-Layout mit QLayout.SetFixedSize).
* Das Fenster wird auf den verfügbaren Bildschirmbereich geklemmt
  (setMaximumSize(screen)).
* Die ScrollArea zeigt Scrollbars, sobald der Inhalt den Viewport übersteigt.
* Solange der Inhalt kleiner als der Bildschirm ist, bleibt das Fenster exakt
  auf Inhaltgröße (kein leerer Raum, keine Scrollbars).

WICHTIG (Qt 6.11): QWidgetItemV2 cached den sizeHint eines Widgets beim ersten
Zugriff und aktualisiert ihn NICHT, wenn der Inhalt später wächst – selbst
layout.invalidate() hilft nicht. Daher müssen die Widget-Caches explizit per
updateGeometry() invalidiert werden (ruft invalidateSizeCache auf), bevor die
Layout-Caches geleert und das Fenster an den (geklemmten) Inhalt angepasst wird.
"""

from typing import Optional
from PySide6.QtCore import QCoreApplication, QEvent, QSize, QTimer
from PySide6.QtWidgets import (
    QApplication, QFrame, QLayout, QScrollArea, QWidget,
)


class ContentScrollArea(QScrollArea):
    """QScrollArea, deren sizeHint die Größe des Inhalts liefert.

    Eine Standard-QScrollArea liefert einen kleinen Default-sizeHint; ein
    Eltern-Layout (QMainWindowLayout / QVBoxLayout) würde das Fenster dadurch
    auf diese kleine Größe schrumpfen. Mit dem Inhalt als sizeHint wächst das
    Fenster korrekt mit dem Inhalt mit (dynamisch, keine fixen Pixelwerte).

    WICHTIG: minimumSizeHint() bewusst NICHT vom Inhalt ableiten, sondern das
    kleine Standard-Minimum der QScrollArea liefern. Das Eltern-Layout setzt
    das Fenster-Minimum aus der Summe der minimumSizeHints; ein Inhalts-basiertes
    Minimum würde das Fenster-Minimum größer machen als das Bildschirm-Cap
    (min > max -> Qt gibt dem Minimum Vorrang -> die Klemme versagt und das
    Fenster ragt über den Bildschirm). Mit dem kleinen Standard-Minimum kann
    das Fenster bis auf das Screen-Cap schrumpfen und die ScrollArea zeigt
    Scrollbars, sobald der Inhalt den Viewport übersteigt.
    """

    def sizeHint(self) -> QSize:
        if self.widget() is not None:
            return self.widget().sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        # Standard-QScrollArea: kleines Minimum (Viewport-basiert), damit das
        # Fenster schrumpfen kann und Scrollbars erscheinen.
        return super().minimumSizeHint()


class ContentScrollMixin:
    """Mixin: gesamtes Fenster scrollbar, wenn der Inhalt höher/breiter als
    der Bildschirm ist (Servicefenster + Indikator-Prop-Fenster, 5.4)."""

    #: Widget mit dem eigentlichen Inhalt (Layout mit SetFixedSize)
    _content_widget: Optional[QWidget] = None
    #: ScrollArea, die den Inhalt umschließt
    content_scroll: Optional[ContentScrollArea] = None

    # -------------------------------------------------------------------------
    # Installation
    # -------------------------------------------------------------------------

    def install_content_scroll(self, content_widget: QWidget,
                               install_to: Optional[QWidget] = None,
                               parent_layout: Optional[QLayout] = None) -> ContentScrollArea:
        """Umschließt content_widget mit einer ContentScrollArea und installiert sie.

        Args:
            content_widget: Inhalt (Layout mit SetFixedSize; behält natürliche
                            Größe). MUSS das Layout-Objekt über self referenzierbar
                            bleiben (self.content_size() liest es).
            install_to:     QMainWindow, dessen CentralWidget die ScrollArea wird
                            (Servicefenster-Fall).
            parent_layout:  Ziel-Layout, dem die ScrollArea hinzugefügt wird
                            (Dialog-Fall).
        """
        self._content_widget = content_widget
        self.content_scroll = ContentScrollArea()
        self.content_scroll.setWidgetResizable(False)  # Inhalt behält natürliche Größe
        self.content_scroll.setWidget(content_widget)
        self.content_scroll.setFrameShape(QFrame.NoFrame)
        if parent_layout is not None:
            parent_layout.addWidget(self.content_scroll)
        elif install_to is not None:
            install_to.setCentralWidget(self.content_scroll)
        self.apply_screen_cap()
        return self.content_scroll

    def apply_screen_cap(self) -> None:
        """Klemmt die maximale Fenstergröße auf den verfügbaren Bildschirmbereich."""
        screen = QApplication.primaryScreen().availableGeometry()
        self.setMaximumSize(screen.size())

    # -------------------------------------------------------------------------
    # Größenberechnung (dynamisch, ohne fixe Pixelwerte)
    # -------------------------------------------------------------------------

    def content_size(self) -> QSize:
        """Natürliche Inhaltsgröße (Fenstergröße ohne Rahmen)."""
        if self._content_widget is not None and self._content_widget.layout() is not None:
            return self._content_widget.layout().sizeHint()
        return self.sizeHint()

    def clamped_content_size(self) -> QSize:
        """Inhaltsgröße, auf den Bildschirm geklemmt (Fenstergröße ohne Rahmen)."""
        desired = self.content_size()
        screen = QApplication.primaryScreen().availableGeometry()
        return QSize(min(desired.width(), screen.width()),
                     min(desired.height(), screen.height()))

    def sizeHint(self) -> QSize:
        """Inhaltsbasierte Fenstergröße inkl. Rahmen, auf Bildschirm geklemmt.

        Das QMainWindowLayout cached die Größe des Central-Widgets beim ersten
        Layout-Durchlauf (Qt-Quirk) und meldet danach einen veralteten sizeHint,
        wenn die Inhalte (z.B. Service-Spalten) wachsen. Daher wird die
        Fenstergröße hier direkt aus dem Inhalt abgeleitet.
        """
        if self._content_widget is None:
            return super().sizeHint()
        content = self.clamped_content_size()
        frame = self.frameGeometry().size() - self.size()
        return QSize(content.width() + frame.width(),
                     content.height() + frame.height())

    # -------------------------------------------------------------------------
    # Reflow
    # -------------------------------------------------------------------------

    def _schedule_reflow(self) -> None:
        """Invalidiert die Layout-Caches und setzt die Fenstergröße DEFERRED.

        Während eines synchronen Umbaus (z.B. Service-Spalten per deleteLater()
        ersetzen, Stack-Seiten neu aufbauen) sind die alten Widgets noch im
        Widget-Baum – die Layout-Caches (QWidgetItemV2/QBoxLayout) liefern dann
        veraltete sizeHints (z.B. 18x18 für eine volle Spalten-Zeile). Ein
        sofortiges resize würde das Fenster fälschlich schrumpfen. Daher wird
        die Größenberechnung in die nächste Event-Loop-Runde verschoben
        (_apply_reflow_size zerstört die deleteLater-Widgets erst und misst
        dann den konsistenten Inhalt).
        """
        self._invalidate_content_caches()
        QTimer.singleShot(0, self._apply_reflow_size)

    def _apply_reflow_size(self) -> None:
        """Zerstört deleteLater-Widgets und setzt das Fenster auf
        min(Inhalt, Bildschirm) inkl. Rahmen.

        P15-Bugfix: try/except – der deferred QTimer kann feuern, nachdem das
        Fenster bereits geschlossen/zerstoert wurde (wildes Klicken + schnelles
        Schliessen); ein Zugriff wuerde sonst crashen (0xC0000005).
        """
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.resize_to_clamped_content()
        except (RuntimeError, AttributeError):
            pass

    def resize_to_clamped_content(self) -> None:
        """Setzt das Inhalt-Widget auf seine Layout-Größe und das Fenster auf
        min(Inhalt, Bildschirm) inkl. Rahmen.

        WICHTIG: Das Inhalt-Widget wird EXPLIZIT auf layout().sizeHint()
        gesetzt. QScrollArea (widgetResizable=False) resizet das Widget nicht;
        ein QLayout.SetFixedSize auf dem Inhalt-Layout würde das Widget auf die
        ERSTE Layout-Größe fixieren (setFixedSize) und späteres Wachstum
        (zusätzliche Service-Spalten, aufgeklappte Experten-Optionen)
        verhindern. Das manuelle resize() hält das Widget dagegen immer auf der
        aktuellen Layout-Größe.

        BUGFIX (Persistenz): Das FENSTER wird dabei NIE unter die aktuelle
        (User-/wiederhergestellte) Größe geschrumpft, sondern nur vergrößert,
        wenn der Inhalt mehr Platz braucht – maximal bis zum Bildschirm. Vorher
        überschrieb der Reflow nach restore_state() die persistierte Geometrie
        (Fenster schrumpfte auf Inhaltgröße), wodurch save_state() die falsche
        Größe speicherte und die letzte Fensterposition/-größe verloren ging.

        05.08.2026 (Kleinere Einstellungen): Mit `_exact_fit_to_content = True`
        (z. B. ServiceWindow) wird das Fenster IMMER exakt auf min(Inhalt,
        Bildschirm) gesetzt – auch SCHRUMPFEND. Die Fenstergröße folgt dann
        vollständig dem Inhalt (rechts = rechter Box-Rand, unten = Log-Unter-
        kante); NUR die Position wird persistiert (ServiceWindow-Override).
        Alle anderen Mixin-Nutzer (z. B. Indikator-Dialog) behalten das
        wachse-nie-schrumpfe-Verhalten.
        """
        if self._content_widget is not None and self._content_widget.layout() is not None:
            self._content_widget.resize(self._content_widget.layout().sizeHint())
        content = self.clamped_content_size()
        frame = self.frameGeometry().size() - self.size()
        desired = QSize(content.width() + frame.width(),
                        content.height() + frame.height())
        screen = QApplication.primaryScreen().availableGeometry()
        if getattr(self, '_exact_fit_to_content', False):
            # EXACT-FIT: Fenster exakt auf min(Inhalt, Bildschirm) – auch
            # schrumpfen, wenn der Inhalt kleiner wird (Punkte 3+4).
            new_w = min(desired.width(), screen.width())
            new_h = min(desired.height(), screen.height())
            # 11.08.2026 (Bugfix, Slider-Spielraum): Optionales
            # `_min_window_width` (z. B. ServiceWindow=1100) garantiert dem
            # QSplitter eine Mindest-Breite ueber der Minima-Summe
            # (Tree 400 + Panel 520 = 920) – der Slider bleibt damit IMMER
            # beweglich, auch wenn der Inhalt schmal ist. Screen-Klemme.
            min_w = getattr(self, '_min_window_width', 0) or 0
            if min_w:
                new_w = max(new_w, min(min_w, screen.width()))
        else:
            # Nur wachsen, nie schrumpfen (unter aktuelle Größe) + Screen-Klemme.
            current = self.size()
            new_w = min(max(desired.width(), current.width()), screen.width())
            new_h = min(max(desired.height(), current.height()), screen.height())
        # 11.08.2026 (Bugfix, Maximize): Ein MAXIMIERTES Fenster darf durch
        # den Reflow nicht auf die Inhaltsgroesse zurueckgesetzt werden
        # (der Maximize-Button wuerde sonst wirkungslos – das Fenster
        # springt nach jedem Reflow aus dem Maximize-Zustand zurueck).
        # Der Inhalt wird trotzdem angepasst (siehe unten).
        if not self.isMaximized():
            self.resize(new_w, new_h)
        # 11.08.2026 (Bugfix, Slider-Spielraum): Das Inhalt-Widget an die
        # aktuelle Fenstergroesse anpassen, damit ein QSplitter darin die
        # volle verfuegbare Breite nutzt (sonst klebt er an den SizeHints
        # und der Slider bleibt bei schmalem Inhalt fixiert). Nur aktiv,
        # wenn `_min_window_width` gesetzt ist (ServiceWindow) – alle
        # anderen Mixin-Nutzer behalten ihr bisheriges Verhalten.
        if getattr(self, '_min_window_width', 0) and self._content_widget is not None:
            f = self.frameGeometry().size() - self.size()
            w = max(self.width() - f.width(), 0)
            h = max(self.height() - f.height(), 0)
            if w and h:
                self._content_widget.resize(w, h)

    def _invalidate_content_caches(self) -> None:
        """Invalidiert QWidgetItemV2- und Layout-Caches entlang der Hierarchie.

        Qt 6.11: layout.invalidate() allein aktualisiert die gecachten
        QWidgetItemV2-sizeHints NICHT. updateGeometry() auf den betroffenen
        Widgets ruft invalidateSizeCache() auf und erzwingt die Neuberechnung.
        Die Rekursion läuft über alle Sub-Layouts (z.B. die obere Zeile mit
        'Service-Sets' + 'Service-Parameter') und deren Widgets.
        """
        if self._content_widget is None:
            return
        widget = self._content_widget

        def _invalidate(lay: QLayout) -> None:
            if lay is None:
                return
            lay.invalidate()
            for i in range(lay.count()):
                item = lay.itemAt(i)
                if item is None:
                    continue
                w = item.widget()
                if w is not None:
                    w.updateGeometry()
                    _invalidate(w.layout())
                else:
                    _invalidate(item.layout())

        widget.updateGeometry()
        _invalidate(widget.layout())

```

--------------------------------------------------

### DATEI: statistic_win.py
```py
# statistic_win.py
"""
Statistik-Fenster für PyTrader – Nicht-modale Analyse-Umgebung
mit dynamischer Filterung, Summary-Karten, Detail-Tabelle und Paging.
Mit automatischem State Persistence via PersistentWindow.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QFile, QIODevice, QTimer, Slot
from PySide6.QtGui import QColor
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QPushButton, QTableWidget, QTableWidgetItem, QWidget,
)

from analytics.statistics_repository import StatisticsRepository
from persistent_win import PersistentWindow, register_persistent_window
from state_manager import StateManager

# Phase 15 15.01-Nachtrag 4: Favoriten-Symbol-Verwaltung im Statistik-Fenster
# (★-Button oeffnet das SymbolsWindow; Symbol-Filter-Dropdown zeigt
# 'ALLE' + Favoriten, EventBus-Kopplung analog Chart-/ServiceWindow).
from config.event_bus import event_bus
from symbol_repository import SymbolRepository, get_symbol_repository
from serviceui.symbols_win import SymbolsWindow

BASE_DIR = Path(__file__).resolve().parent


@register_persistent_window()
class StatisticWindow(PersistentWindow):
    INSTANCE_ID = "win_statistics"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.repo = StatisticsRepository()
        self._state_mgr: StateManager = getattr(parent, 'state_manager', None) or StateManager()
        self.settings = self._state_mgr.get_app_settings()

        # Paging-State
        self._all_signals: List[Dict[str, Any]] = []
        self._current_page: int = 0
        self._total_pages: int = 0

        # UI laden
        ui_file = QFile(str(BASE_DIR / "ui" / "statistic_win.ui"))
        if ui_file.open(QIODevice.ReadOnly):
            loader = QUiLoader()
            self.ui = loader.load(ui_file)
            ui_file.close()
            self.setCentralWidget(self.ui)
        else:
            self.ui = QWidget(self)
            self.setCentralWidget(self.ui)

        self.setWindowTitle("PyTrader - Signal-Statistik")

        # Controls
        self.combo_symbol: QComboBox = self.ui.findChild(QComboBox, "combo_symbol_filter")
        self.combo_tf: QComboBox = self.ui.findChild(QComboBox, "combo_tf_filter")
        self.btn_refresh: QPushButton = self.ui.findChild(QPushButton, "btn_refresh_stats")

        self.label_total: QLabel = self.ui.findChild(QLabel, "label_total_signals")
        self.label_avg_conf: QLabel = self.ui.findChild(QLabel, "label_avg_confidence")
        self.label_win_rate: QLabel = self.ui.findChild(QLabel, "label_win_rate")
        self.label_best_tf: QLabel = self.ui.findChild(QLabel, "label_best_tf")

        self.table: QTableWidget = self.ui.findChild(QTableWidget, "table_signals")

        # Paging-Controls aus der UI
        self.btn_prev: QPushButton = self.ui.findChild(QPushButton, "btn_prev_page")
        self.btn_next: QPushButton = self.ui.findChild(QPushButton, "btn_next_page")
        self.label_page: QLabel = self.ui.findChild(QLabel, "label_page_info")

        # Events (nach restore_state, damit die gesetzten Filter keine refresh-Explosion auslösen)
        if self.combo_symbol:
            self.combo_symbol.currentTextChanged.connect(self._on_filter_changed)
        if self.combo_tf:
            self.combo_tf.currentTextChanged.connect(self._on_filter_changed)
        if self.btn_refresh:
            self.btn_refresh.clicked.connect(self.refresh)
        if self.btn_prev:
            self.btn_prev.clicked.connect(self._prev_page)
        if self.btn_next:
            self.btn_next.clicked.connect(self._next_page)
        if self.table:
            self.table.itemDoubleClicked.connect(self.on_item_double_clicked)

        # Phase 15 15.01-Nachtrag 4 (User-Notiz 04.08.2026): Favoriten-Symbol-
        # Verwaltung im Statistik-Fenster – ★-Button rechts neben der Symbol-
        # Filter-ComboBox oeffnet das nicht-modale SymbolsWindow (analog
        # Chart-/ServiceWindow). Das Symbol-Filter-Dropdown zeigt 'ALLE' +
        # Favoriten (Fallback auf Default-Symbole); die aktuelle Auswahl bleibt
        # erhalten, damit der Filter nicht ungewollt umspringt. EventBus-
        # Kopplung: Favoriten-Aenderungen -> Dropdown neu befuellen.
        self._symbol_repo: SymbolRepository = get_symbol_repository()
        self.btn_symbol_fav: QPushButton = QPushButton("★", self.ui)
        self.btn_symbol_fav.setObjectName("btn_symbol_fav")
        self.btn_symbol_fav.setToolTip(
            "Favoriten verwalten – oeffnet das Symbol-Fenster. "
            "Das Symbol-Filter-Dropdown zeigt 'ALLE' + Favoriten.")
        self.btn_symbol_fav.setFixedSize(28, 28)
        layout_filter = self.ui.findChild(QHBoxLayout, "horizontalLayout_filter")
        if layout_filter is not None and self.combo_symbol is not None:
            idx = layout_filter.indexOf(self.combo_symbol)
            layout_filter.insertWidget(idx + 1, self.btn_symbol_fav)
        self.btn_symbol_fav.clicked.connect(self.open_symbols_window)
        event_bus.favorites_changed.connect(self._refresh_symbol_combo)
        self._refresh_symbol_combo()

        # State asynchron wiederherstellen (nach show(), damit move/resize vom Window-Manager akzeptiert werden)
        QTimer.singleShot(0, self.restore_state)

        # Initial laden
        QTimer.singleShot(100, self.refresh)

    # --- PersistentWindow-Interface ---

    def get_persistent_symbol(self) -> str:
        return self.combo_symbol.currentText() if self.combo_symbol else "SILVER"

    def get_persistent_timeframe(self) -> str:
        return self.combo_tf.currentText() if self.combo_tf else "H1"

    def _apply_persistent_filters(self, symbol: str, timeframe: str) -> None:
        """Wird von PersistentWindow.restore_state() gerufen."""
        self._restore_filters(symbol, timeframe)

    def _on_filter_changed(self):
        """Speichert sofort bei Filter-Änderung und löst refresh aus."""
        self.save_state()
        self.refresh()

    def _restore_filters(self, symbol: Optional[str] = None, timeframe: Optional[str] = None):
        """Setzt Filter aus gespeicherten Werten (blockiert Signale)."""
        if self.combo_symbol:
            self.combo_symbol.blockSignals(True)
        if self.combo_tf:
            self.combo_tf.blockSignals(True)

        if symbol and self.combo_symbol:
            idx = self.combo_symbol.findText(symbol)
            if idx >= 0:
                self.combo_symbol.setCurrentIndex(idx)
        if timeframe and self.combo_tf:
            idx = self.combo_tf.findText(timeframe)
            if idx >= 0:
                self.combo_tf.setCurrentIndex(idx)

        if self.combo_symbol:
            self.combo_symbol.blockSignals(False)
        if self.combo_tf:
            self.combo_tf.blockSignals(False)

    # --- Phase 15 15.01-Nachtrag 4: Symbol- & Favoriten-Verwaltung ---

    @Slot()
    def open_symbols_window(self) -> None:
        """Oeffnet das nicht-modale SymbolsWindow (Singleton-Verhalten).

        Analog zu chart_win/service_win: Existiert bereits eine sichtbare
        Instanz, wird sie in den Vordergrund geholt statt neu geoeffnet
        (PersistentWindow.get_existing_instance()).
        """
        existing = SymbolsWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = SymbolsWindow(self)  # parent=self nur fuer state_manager-Zugriff
        win.show()

    def _refresh_symbol_combo(self) -> None:
        """Befuellt die Symbol-Filter-ComboBox: 'ALLE' + Favoriten.

        Wird beim Start und bei jedem `EventBus.favorites_changed`-Event
        aufgerufen (Verbindung im __init__). Fallback auf die Standard-
        Defaults (SILVER/GOLD/BTCUSD), falls keine Favoriten gesetzt sind.
        Die aktuelle Auswahl bleibt erhalten (auch wenn sie kein Favorit
        mehr ist), damit der Filter nicht ungewollt umspringt. Signale sind
        waehrend des Umbaus blockiert (kein Refresh-Explosion).
        """
        if not self.combo_symbol:
            return
        favorites = self._symbol_repo.get_favorite_symbols()
        if not favorites:
            favorites = list(SymbolRepository.DEFAULT_SYMBOLS)
        current = self.combo_symbol.currentText()
        self.combo_symbol.blockSignals(True)
        self.combo_symbol.clear()
        self.combo_symbol.addItem("ALLE")
        for sym in favorites:
            self.combo_symbol.addItem(sym)
        if current and current != "ALLE" and current not in favorites:
            self.combo_symbol.addItem(current)
        idx = self.combo_symbol.findText(current)
        self.combo_symbol.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_symbol.blockSignals(False)

    # --- Paging ---

    def _update_page_controls(self):
        if not self.btn_prev or not self.btn_next or not self.label_page:
            return
        self.label_page.setText(f"Seite {self._current_page + 1} / {max(self._total_pages, 1)}")
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page < self._total_pages - 1)

    @Slot()
    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._render_current_page()

    @Slot()
    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._render_current_page()

    def _render_current_page(self):
        page_size = self.settings.statistics_page_size
        start = self._current_page * page_size
        end = min(start + page_size, len(self._all_signals))
        page_signals = self._all_signals[start:end]
        self._populate_table(page_signals, start)
        self._update_page_controls()

    # --- Daten laden ---

    @Slot()
    def refresh(self):
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "ALLE"
        tf = self.combo_tf.currentText() if self.combo_tf else "ALLE"

        # Summary
        summary = self.repo.get_summary(symbol, tf)
        if self.label_total:
            self.label_total.setText(str(summary["total_signals"]))
        if self.label_avg_conf:
            self.label_avg_conf.setText(f"{summary['avg_confidence']:.2f}")
        if self.label_win_rate:
            self.label_win_rate.setText(f"{summary['win_rate']:.1f}%")
        if self.label_best_tf:
            self.label_best_tf.setText(summary["best_tf"])

        # Signale mit Paging
        self._all_signals = self.repo.fetch_signals(symbol, tf, limit=self.settings.statistics_signal_limit)
        self._total_pages = max(1, (len(self._all_signals) + self.settings.statistics_page_size - 1) // self.settings.statistics_page_size)
        self._current_page = 0
        self._render_current_page()

    def _populate_table(self, signals: List[Dict[str, Any]], row_offset: int = 0):
        if not self.table:
            return

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(signals))
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Time", "Symbol", "Timeframe", "Signal-Set", "Confidence", "Outcome"
        ])

        for row_idx, sig in enumerate(signals):
            global_row = row_offset + row_idx + 1
            self.table.setVerticalHeaderItem(row_idx, QTableWidgetItem(str(global_row)))

            dt = datetime.fromtimestamp(sig["time"])
            self.table.setItem(row_idx, 0, QTableWidgetItem(dt.strftime("%Y-%m-%d %H:%M")))
            self.table.setItem(row_idx, 1, QTableWidgetItem(sig["symbol"]))
            self.table.setItem(row_idx, 2, QTableWidgetItem(sig["timeframe"]))
            self.table.setItem(row_idx, 3, QTableWidgetItem(sig["source_id"]))

            conf_item = QTableWidgetItem(f"{sig['confidence']:.2f}")
            conf_item.setData(0, sig["confidence"])
            self.table.setItem(row_idx, 4, conf_item)

            outcome = sig.get("outcome", "N/A")
            outcome_item = QTableWidgetItem(outcome)
            if outcome == "Win":
                outcome_item.setForeground(QColor("#26a69a"))
            elif outcome == "Loss":
                outcome_item.setForeground(QColor("#ef5350"))
            self.table.setItem(row_idx, 5, outcome_item)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        self.table.setUpdatesEnabled(True)

    # --- Jump-to-Bar ---

    def on_item_double_clicked(self, item: QTableWidgetItem):
        row = item.row()
        if row < 0:
            return

        symbol_item = self.table.item(row, 1)
        tf_item = self.table.item(row, 2)
        time_item = self.table.item(row, 0)

        if not symbol_item or not tf_item or not time_item:
            return

        symbol = symbol_item.text()
        tf = tf_item.text()

        try:
            dt = datetime.strptime(time_item.text(), "%Y-%m-%d %H:%M")
            bar_time = int(dt.timestamp())
        except ValueError:
            return

        main_window = self._find_main_window()
        if main_window and hasattr(main_window, 'open_chart_at_bar'):
            main_window.open_chart_at_bar(symbol, tf, bar_time)
        elif main_window and hasattr(main_window, 'open_chart_window'):
            main_window.open_chart_window()

    def _find_main_window(self):
        app = QApplication.instance()
        if not app:
            return None
        for widget in app.topLevelWidgets():
            if widget.metaObject().className() == "MainWindow":
                return widget
        return None

```

--------------------------------------------------

### DATEI: config/__init__.py
```py

```

--------------------------------------------------

### DATEI: config/app_settings.py
```py
# config/app_settings.py
"""
AppSettings – typsichere Data-Class für anwendungsweite Konfiguration.
Alle Werte haben sinnvolle Defaults und werden in app_data.duckdb persistiert.
Erbt von AbstractStateModel für einheitliches Serialisieren/Deserialisieren.
"""

from dataclasses import dataclass
from typing import Any, Dict

from config.base_state_model import AbstractStateModel


@dataclass
class AppSettings(AbstractStateModel):
    # Chart: Maximale Anzahl Candles beim Laden
    chart_candle_limit: int = 3000

    # Feature-Builder: Default-Limit beim Laden von OHLCV
    feature_builder_limit: int = 3000

    # Historical Scanner: Maximale Candles pro Timeframe beim Scan
    scanner_candle_limit: int = 100_000

    # Statistik: Maximale Signale für die Detail-Tabelle
    statistics_signal_limit: int = 10_000

    # Signal-Overlay: Maximale Marker im Chart
    signal_marker_limit: int = 500

    # Statistik: Zeilen pro Seite in der Tabelle
    statistics_page_size: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chart_candle_limit": self.chart_candle_limit,
            "feature_builder_limit": self.feature_builder_limit,
            "scanner_candle_limit": self.scanner_candle_limit,
            "statistics_signal_limit": self.statistics_signal_limit,
            "signal_marker_limit": self.signal_marker_limit,
            "statistics_page_size": self.statistics_page_size,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppSettings":
        return cls(
            chart_candle_limit=int(data.get("chart_candle_limit", 3000)),
            feature_builder_limit=int(data.get("feature_builder_limit", 3000)),
            scanner_candle_limit=int(data.get("scanner_candle_limit", 100_000)),
            statistics_signal_limit=int(data.get("statistics_signal_limit", 10_000)),
            signal_marker_limit=int(data.get("signal_marker_limit", 500)),
            statistics_page_size=int(data.get("statistics_page_size", 100)),
        )

```

--------------------------------------------------

### DATEI: config/base_state_model.py
```py
# config/base_state_model.py
"""
AbstractStateModel – Abstrakte Basisklasse für typsichere State-Modelle.
Ermöglicht einheitliches Serialisieren/Deserialisieren für DuckDB-Persistierung.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class AbstractStateModel(ABC):
    """Abstrakte Basisklasse für persistierbare State-Modelle."""

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Serialisiert das Modell in ein JSON-kompatibles Dict."""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AbstractStateModel":
        """Deserialisiert ein Dict zurück in eine Modell-Instanz."""
        pass

```

--------------------------------------------------

### DATEI: config/event_bus.py
```py
# config/event_bus.py
"""
config/event_bus.py - Zentraler Signal-Hub (EventBus-Singleton) fuer die
schwellenfreie Entkopplung der Fenster (Phase 15, Invariante 5).

Fenster kommunizieren NIE direkt miteinander (keine zirkulaeren
Abhaengigkeiten, kein Hardcoding von Fensterklassen). Stattdessen emittieren
sie Events auf dem zentralen EventBus und andere Fenster/Module abonnieren
diese Signale.

Phase 15.01: `favorites_changed` wird vom SymbolsWindow nach jedem
Favoriten-Toggle emittiert; ServiceWindow (und spaeter AnalyticsWindow)
befuellen daraufhin ihre Symbol-Dropdowns neu.

Verwendungsbeispiel:
    from config.event_bus import event_bus
    event_bus.favorites_changed.connect(self._refresh_symbol_combo)
    event_bus.favorites_changed.emit()
"""

from typing import ClassVar, Optional

from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    """Zentraler Signal-Hub (Singleton) fuer fensteruebergreifende Events.

    Signaldefinitionen (minimal gehalten, Phase-15-Entscheidungs-Protokoll):
    - favorites_changed : Favoriten-Liste wurde geaendert (SymbolsWindow).
    - profile_changed   : Analytics-Profil wurde geaendert (15.03, Payload =
                          Profil-Name/-ID).
    - service_set_changed: Service-Set wurde gespeichert/geloescht (15.02).
    - service_run_started: Intensiver Service-Run/Scan wurde gestartet
                           (ServiceWindow) – MainWindow pausiert den 45s-
                           sync_timer (Concurrency-Guard, 05.08.2026).
    - service_run_finished: Alle gestarteten Service-Runs/Scans sind beendet
                            (Referenzzähler auf 0) – MainWindow startet den
                            sync_timer wieder.
    """

    favorites_changed = Signal()
    profile_changed = Signal(str)
    service_set_changed = Signal()
    # 21.03.11 (Bug 6): Tabellen-Sortierung der Filterleiste. Das
    # ChartWindow emittiert nach jeder Sortier-Aenderung ('date'|'signal'|
    # 'tf'); das AnalyticsWindow wendet sie auf die TablePage an. Entkoppelt
    # via EventBus – das ChartWindow kennt das AnalyticsWindow NICHT (IoC).
    mtf_fc_sort_changed = Signal(str)
    # Phase 16 (05.08.2026): Concurrency-Guard gegen Konflikte zwischen
    # Service-Berechnungen (SetRunWorker/ServiceRunWorker/HistoricalScanner)
    # und dem 45s-Hintergrund-Sync (sync_timer in main.py). Entkoppelt via
    # EventBus – das ServiceWindow kennt den MainWindow NICHT (IoC).
    service_run_started = Signal()
    service_run_finished = Signal()

    _instance: ClassVar[Optional["EventBus"]] = None

    def __init__(self) -> None:
        # QObject ohne Parent: Der Singleton lebt app-weit und wird nie
        # geloescht (gehoert keiner Fenster-Hierarchie an).
        super().__init__(None)
        # Phase 21.02 (12.08.2026): Referenzzaehler fuer laufende Service-
        # Berechnungen/Scans. Wird von MainWindow in service_run_started/
        # finished mitgepflegt; PropertiesWindow nutzt ihn als
        # Concurrency-Guard fuer die DB-Kompaktierung (getattr-Fallback 0,
        # falls ein Modul ohne Initialisierung liest).
        self.sync_pause_count: int = 0

    @classmethod
    def instance(cls) -> "EventBus":
        """Liefert die app-weite Singleton-Instanz (lazy)."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# Bequeme Modul-Level-Instanz: `from config.event_bus import event_bus`
event_bus = EventBus.instance()

```

--------------------------------------------------

### DATEI: ui/__init__.py
```py
# ui/__init__.py
"""
ui-Paket (18.01.02, E5): Fenster-Lifecycle-Management.

  * window_manager.py – WindowManager (Sub-/Chart-Fenster, Jump-to-Bar)

Kein Import von main.py (IoC – der WindowManager kennt MainWindow nicht).
"""

```

--------------------------------------------------

### DATEI: ui/chart_win.ui
```xml
<?xml version="1.0" encoding="UTF-8"?>
<ui version="4.0">
 <class>ChartWindow</class>
 <widget class="QMainWindow" name="ChartWindow">
  <property name="geometry">
   <rect>
    <x>0</x>
    <y>0</y>
    <width>1200</width>
    <height>750</height>
   </rect>
  </property>
  <property name="windowTitle">
   <string>PyTrader - TradingView Native JS Studio</string>
  </property>
  <widget class="QWidget" name="centralwidget">
   <layout class="QVBoxLayout" name="verticalLayout_main">
    <property name="spacing">
     <number>5</number>
    </property>
    <property name="leftMargin">
     <number>5</number>
    </property>
    <property name="topMargin">
     <number>5</number>
    </property>
    <property name="rightMargin">
     <number>5</number>
    </property>
    <property name="bottomMargin">
     <number>5</number>
    </property>
    <item>
     <widget class="QWidget" name="toolbar_widget" native="true">
      <property name="sizePolicy">
       <sizepolicy hsizetype="Expanding" vsizetype="Fixed">
        <horstretch>0</horstretch>
        <verstretch>0</verstretch>
       </sizepolicy>
      </property>
      <layout class="QVBoxLayout" name="verticalLayout_toolbar">
       <property name="spacing">
        <number>4</number>
       </property>
       <property name="leftMargin">
        <number>0</number>
       </property>
       <property name="topMargin">
        <number>0</number>
       </property>
       <property name="rightMargin">
        <number>0</number>
       </property>
       <property name="bottomMargin">
        <number>0</number>
       </property>
       <item>
        <layout class="QHBoxLayout" name="horizontalLayout_row1">
         <property name="spacing">
          <number>8</number>
         </property>
         <item>
          <widget class="QComboBox" name="combo_symbol">
           <property name="sizePolicy">
            <sizepolicy hsizetype="Fixed" vsizetype="Fixed">
             <horstretch>0</horstretch>
             <verstretch>0</verstretch>
            </sizepolicy>
           </property>
           <property name="minimumSize">
            <size>
             <width>100</width>
             <height>28</height>
            </size>
           </property>
           <item>
            <property name="text">
             <string>SILVER</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>GOLD</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>BTCUSD</string>
            </property>
           </item>
          </widget>
         </item>
         <item>
          <widget class="QComboBox" name="combo_tf">
           <property name="sizePolicy">
            <sizepolicy hsizetype="Fixed" vsizetype="Fixed">
             <horstretch>0</horstretch>
             <verstretch>0</verstretch>
            </sizepolicy>
           </property>
           <property name="minimumSize">
            <size>
             <width>80</width>
             <height>28</height>
            </size>
           </property>
           <item>
            <property name="text">
             <string>M1</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>M2</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>M5</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>M10</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>M15</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>M30</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>H1</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>H4</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>D1</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>W1</string>
            </property>
           </item>
           <item>
            <property name="text">
             <string>MN1</string>
            </property>
           </item>
          </widget>
         </item>
         <item>
          <spacer name="horizontalSpacer_row1">
           <property name="orientation">
            <enum>Qt::Orientation::Horizontal</enum>
           </property>
           <property name="sizeHint" stdset="0">
            <size>
             <width>40</width>
             <height>20</height>
            </size>
           </property>
          </spacer>
         </item>
         <item>
          <widget class="QPushButton" name="btn_indicator_grid_liquidity">
           <property name="sizePolicy">
            <sizepolicy hsizetype="Fixed" vsizetype="Fixed">
             <horstretch>0</horstretch>
             <verstretch>0</verstretch>
            </sizepolicy>
           </property>
           <property name="minimumSize">
            <size>
             <width>28</width>
             <height>28</height>
            </size>
           </property>
           <property name="maximumSize">
            <size>
             <width>28</width>
             <height>28</height>
            </size>
           </property>
           <property name="toolTip">
            <string>Grid Liquidity Plugin (Linksklick: An/Aus, Rechtsklick: Einstellungen)</string>
           </property>
           <property name="text">
            <string>◆</string>
           </property>
          </widget>
         </item>
         <item>
          <widget class="QPushButton" name="btn_indicator_ma">
           <property name="sizePolicy">
            <sizepolicy hsizetype="Fixed" vsizetype="Fixed">
             <horstretch>0</horstretch>
             <verstretch>0</verstretch>
            </sizepolicy>
           </property>
           <property name="minimumSize">
            <size>
             <width>28</width>
             <height>28</height>
            </size>
           </property>
           <property name="maximumSize">
            <size>
             <width>28</width>
             <height>28</height>
            </size>
           </property>
           <property name="toolTip">
            <string>Multi Moving Average (Linksklick: An/Aus, Rechtsklick: Einstellungen)</string>
           </property>
           <property name="text">
            <string>MA</string>
           </property>
          </widget>
         </item>
        </layout>
       </item>
       <item>
        <layout class="QHBoxLayout" name="horizontalLayout_row2">
         <property name="spacing">
          <number>8</number>
         </property>
         <item>
          <widget class="QPushButton" name="btn_reset_chart">
           <property name="sizePolicy">
            <sizepolicy hsizetype="Fixed" vsizetype="Fixed">
             <horstretch>0</horstretch>
             <verstretch>0</verstretch>
            </sizepolicy>
           </property>
           <property name="minimumSize">
            <size>
             <width>28</width>
             <height>28</height>
            </size>
           </property>
           <property name="maximumSize">
            <size>
             <width>28</width>
             <height>28</height>
            </size>
           </property>
           <property name="toolTip">
            <string>Reset Chart</string>
           </property>
           <property name="text">
            <string>↺</string>
           </property>
          </widget>
         </item>
         <item>
          <spacer name="horizontalSpacer_row2">
           <property name="orientation">
            <enum>Qt::Orientation::Horizontal</enum>
           </property>
           <property name="sizeHint" stdset="0">
            <size>
             <width>40</width>
             <height>20</height>
            </size>
           </property>
          </spacer>
         </item>
        </layout>
       </item>
      </layout>
     </widget>
    </item>
    <item>
     <widget class="QWidget" name="web_container" native="true">
      <property name="sizePolicy">
       <sizepolicy hsizetype="Expanding" vsizetype="Expanding">
        <horstretch>1</horstretch>
        <verstretch>1</verstretch>
       </sizepolicy>
      </property>
      <layout class="QVBoxLayout" name="verticalLayout_web">
       <property name="leftMargin">
        <number>0</number>
       </property>
       <property name="topMargin">
        <number>0</number>
       </property>
       <property name="rightMargin">
        <number>0</number>
       </property>
       <property name="bottomMargin">
        <number>0</number>
       </property>
      </layout>
     </widget>
    </item>
   </layout>
  </widget>
 </widget>
 <resources/>
 <connections/>
</ui>

```

--------------------------------------------------

### DATEI: ui/main_win.ui
```xml
<?xml version="1.0" encoding="UTF-8"?>
<ui version="4.0">
 <class>MainWindow</class>
 <widget class="QMainWindow" name="MainWindow">
  <property name="geometry">
   <rect>
    <x>0</x>
    <y>0</y>
    <width>800</width>
    <height>600</height>
   </rect>
  </property>
  <property name="windowTitle">
   <string>MainWindow</string>
  </property>
  <widget class="QWidget" name="centralwidget">
   <widget class="QLineEdit" name="input_field">
    <property name="geometry">
     <rect>
      <x>80</x>
      <y>10</y>
      <width>571</width>
      <height>26</height>
     </rect>
    </property>
   </widget>
   <widget class="QPushButton" name="btn_send">
    <property name="geometry">
     <rect>
      <x>80</x>
      <y>40</y>
      <width>131</width>
      <height>26</height>
     </rect>
    </property>
    <property name="text">
     <string>Abfage Gemini</string>
    </property>
   </widget>
   <widget class="QLabel" name="status_label">
    <property name="geometry">
     <rect>
      <x>80</x>
      <y>80</y>
      <width>561</width>
      <height>51</height>
     </rect>
    </property>
    <property name="text">
     <string>TextLabel</string>
    </property>
   </widget>
   <widget class="QTableWidget" name="table_result">
    <property name="geometry">
     <rect>
      <x>60</x>
      <y>170</y>
      <width>681</width>
      <height>351</height>
     </rect>
    </property>
   </widget>
   <widget class="QPushButton" name="btn_open_chart">
    <property name="geometry">
     <rect>
      <x>300</x>
      <y>60</y>
      <width>81</width>
      <height>71</height>
     </rect>
    </property>
    <property name="text">
     <string>Charts</string>
    </property>
   </widget>
   <widget class="QPushButton" name="btn_service">
    <property name="geometry">
     <rect>
      <x>390</x>
      <y>60</y>
      <width>81</width>
      <height>71</height>
     </rect>
    </property>
    <property name="text">
     <string>Scan</string>
    </property>
   </widget>
      <widget class="QPushButton" name="btn_statistics">
    <property name="geometry">
     <rect>
      <x>480</x>
      <y>60</y>
      <width>81</width>
      <height>71</height>
     </rect>
    </property>
    <property name="text">
     <string>📊 Statistik</string>
    </property>
   </widget>
   <widget class="QPushButton" name="btn_properties">
    <property name="geometry">
     <rect>
      <x>570</x>
      <y>60</y>
      <width>81</width>
      <height>71</height>
     </rect>
    </property>
    <property name="text">
     <string>⚙ Optionen</string>
    </property>
    <property name="toolTip">
     <string>Anwendungs-Einstellungen (Candle-Limits, Seitengrößen, etc.)</string>
    </property>
   </widget>
   <widget class="QLabel" name="label_db_status">
    <property name="geometry">
     <rect>
      <x>540</x>
      <y>140</y>
      <width>141</width>
      <height>28</height>
     </rect>
    </property>
    <property name="text">
     <string>DB Status: –</string>
    </property>
    <property name="toolTip">
     <string>DB-Fragmentierung (via PRAGMA database_size) beim App-Start</string>
    </property>
   </widget>
  </widget>
  <widget class="QMenuBar" name="menubar">
   <property name="geometry">
    <rect>
     <x>0</x>
     <y>0</y>
     <width>800</width>
     <height>33</height>
    </rect>
   </property>
  </widget>
  <widget class="QStatusBar" name="statusbar"/>
 </widget>
 <resources/>
 <connections/>
</ui>

```

--------------------------------------------------

### DATEI: ui/service_win.ui
```xml
<?xml version="1.0" encoding="UTF-8"?>
<ui version="4.0">
 <class>ServiceWindow</class>
 <widget class="QWidget" name="ServiceWindow">
  <property name="geometry">
   <rect>
    <x>0</x>
    <y>0</y>
    <width>1400</width>
    <height>800</height>
   </rect>
  </property>
  <property name="windowTitle">
   <string>PyTrader - Service Kontrolle</string>
  </property>
   <layout class="QVBoxLayout" name="verticalLayout">
    <item>
     <layout class="QHBoxLayout" name="layout_symbol">
      <item>
       <widget class="QLabel" name="label_symbol">
        <property name="text">
         <string>Symbol:</string>
        </property>
       </widget>
      </item>
      <item>
       <widget class="QComboBox" name="combo_symbol">
        <property name="minimumSize">
         <size>
          <width>120</width>
          <height>0</height>
         </size>
        </property>
        <item>
         <property name="text">
          <string>SILVER</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>GOLD</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>BTCUSD</string>
         </property>
        </item>
       </widget>
      </item>
      <item>
       <widget class="QLabel" name="label_tf_filter">
        <property name="text">
         <string>Timeframe:</string>
        </property>
       </widget>
      </item>
      <item>
       <widget class="QComboBox" name="combo_tf">
        <property name="minimumSize">
         <size>
          <width>150</width>
          <height>0</height>
         </size>
        </property>
        <property name="toolTip">
         <string>Timeframe für die gezielte Kontextmenü-Ausführung (MasterTree '▶️ Service(s) ausführen'). 'ALLE Timeframes' führt alle verfügbaren Timeframes nacheinander aus (Multi-TF).</string>
        </property>
        <item>
         <property name="text">
          <string>ALLE Timeframes</string>
         </property>
        </item>
       </widget>
      </item>
      <item>
       <spacer name="horizontalSpacer">
        <property name="orientation">
         <enum>Qt::Orientation::Horizontal</enum>
        </property>
        <property name="sizeHint" stdset="0">
         <size>
          <width>40</width>
          <height>20</height>
         </size>
        </property>
       </spacer>
      </item>
      <item>
       <widget class="QPushButton" name="btn_trash_sets">
        <property name="text">
         <string>🗑️ Papierkorb</string>
        </property>
        <property name="toolTip">
         <string>P14-05: Gelöschte Service-Sets einsehen, wiederherstellen oder endgültig entfernen (Soft-Delete).</string>
        </property>
       </widget>
      </item>
     </layout>
    </item>
    <item>
     <widget class="QTextEdit" name="text_log">
      <property name="readOnly">
       <bool>true</bool>
      </property>
      <property name="placeholderText">
       <string>Log wird hier angezeigt...</string>
      </property>
     </widget>
    </item>
   </layout>
 </widget>
 <resources/>
 <connections/>
</ui>

```

--------------------------------------------------

### DATEI: ui/statistic_win.ui
```xml
<?xml version="1.0" encoding="UTF-8"?>
<ui version="4.0">
 <class>StatisticsWindow</class>
 <widget class="QMainWindow" name="StatisticsWindow">
  <property name="geometry">
   <rect>
    <x>0</x>
    <y>0</y>
    <width>900</width>
    <height>600</height>
   </rect>
  </property>
  <property name="windowTitle">
   <string>PyTrader - Signal-Statistik</string>
  </property>
  <widget class="QWidget" name="centralwidget">
   <layout class="QVBoxLayout" name="verticalLayout_main">
    <property name="spacing">
     <number>8</number>
    </property>
    <property name="leftMargin">
     <number>10</number>
    </property>
    <property name="topMargin">
     <number>10</number>
    </property>
    <property name="rightMargin">
     <number>10</number>
    </property>
    <property name="bottomMargin">
     <number>10</number>
    </property>
    <item>
     <layout class="QHBoxLayout" name="horizontalLayout_filter">
      <property name="spacing">
       <number>6</number>
      </property>
      <item>
       <widget class="QLabel" name="label_symbol">
        <property name="text">
         <string>Symbol:</string>
        </property>
       </widget>
      </item>
      <item>
       <widget class="QComboBox" name="combo_symbol_filter">
        <property name="minimumSize">
         <size>
          <width>100</width>
          <height>0</height>
         </size>
        </property>
        <item>
         <property name="text">
          <string>ALLE</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>SILVER</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>GOLD</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>BTCUSD</string>
         </property>
        </item>
       </widget>
      </item>
      <item>
       <widget class="QLabel" name="label_timeframe">
        <property name="text">
         <string>Timeframe:</string>
        </property>
       </widget>
      </item>
      <item>
       <widget class="QComboBox" name="combo_tf_filter">
        <property name="minimumSize">
         <size>
          <width>80</width>
          <height>0</height>
         </size>
        </property>
        <item>
         <property name="text">
          <string>ALLE</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>M1</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>M5</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>M15</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>M30</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>H1</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>H4</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>D1</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>W1</string>
         </property>
        </item>
        <item>
         <property name="text">
          <string>MN1</string>
         </property>
        </item>
       </widget>
      </item>
      <item>
       <spacer name="horizontalSpacer_filter">
        <property name="orientation">
         <enum>Qt::Orientation::Horizontal</enum>
        </property>
        <property name="sizeHint" stdset="0">
         <size>
          <width>40</width>
          <height>20</height>
         </size>
        </property>
       </spacer>
      </item>
      <item>
       <widget class="QPushButton" name="btn_refresh_stats">
        <property name="minimumSize">
         <size>
          <width>120</width>
          <height>28</height>
         </size>
        </property>
        <property name="text">
         <string>⟳ Aktualisieren</string>
        </property>
       </widget>
      </item>
     </layout>
    </item>
    <item>
     <layout class="QHBoxLayout" name="horizontalLayout_cards">
      <property name="spacing">
       <number>10</number>
      </property>
      <item>
       <widget class="QFrame" name="card_total_signals">
        <property name="styleSheet">
         <string>QFrame { background-color: #1e222d; border: 1px solid #3d4450; border-radius: 6px; padding: 8px; }</string>
        </property>
        <property name="frameShape">
         <enum>QFrame::Shape::StyledPanel</enum>
        </property>
        <layout class="QVBoxLayout" name="verticalLayout_card1">
         <item>
          <widget class="QLabel" name="label_total_signals_title">
           <property name="styleSheet">
            <string>color: #787b86; font-size: 11px;</string>
           </property>
           <property name="text">
            <string>Signale Gesamt</string>
           </property>
          </widget>
         </item>
         <item>
          <widget class="QLabel" name="label_total_signals">
           <property name="styleSheet">
            <string>color: #d1d4dc; font-size: 24px; font-weight: bold;</string>
           </property>
           <property name="text">
            <string>0</string>
           </property>
          </widget>
         </item>
        </layout>
       </widget>
      </item>
      <item>
       <widget class="QFrame" name="card_avg_confidence">
        <property name="styleSheet">
         <string>QFrame { background-color: #1e222d; border: 1px solid #3d4450; border-radius: 6px; padding: 8px; }</string>
        </property>
        <property name="frameShape">
         <enum>QFrame::Shape::StyledPanel</enum>
        </property>
        <layout class="QVBoxLayout" name="verticalLayout_card2">
         <item>
          <widget class="QLabel" name="label_avg_confidence_title">
           <property name="styleSheet">
            <string>color: #787b86; font-size: 11px;</string>
           </property>
           <property name="text">
            <string>Ø Confidence</string>
           </property>
          </widget>
         </item>
         <item>
          <widget class="QLabel" name="label_avg_confidence">
           <property name="styleSheet">
            <string>color: #d1d4dc; font-size: 24px; font-weight: bold;</string>
           </property>
           <property name="text">
            <string>0.00</string>
           </property>
          </widget>
         </item>
        </layout>
       </widget>
      </item>
      <item>
       <widget class="QFrame" name="card_win_rate">
        <property name="styleSheet">
         <string>QFrame { background-color: #1e222d; border: 1px solid #3d4450; border-radius: 6px; padding: 8px; }</string>
        </property>
        <property name="frameShape">
         <enum>QFrame::Shape::StyledPanel</enum>
        </property>
        <layout class="QVBoxLayout" name="verticalLayout_card3">
         <item>
          <widget class="QLabel" name="label_win_rate_title">
           <property name="styleSheet">
            <string>color: #787b86; font-size: 11px;</string>
           </property>
           <property name="text">
            <string>Win-Rate (Forward)</string>
           </property>
          </widget>
         </item>
         <item>
          <widget class="QLabel" name="label_win_rate">
           <property name="styleSheet">
            <string>color: #d1d4dc; font-size: 24px; font-weight: bold;</string>
           </property>
           <property name="text">
            <string>0.0%</string>
           </property>
          </widget>
         </item>
        </layout>
       </widget>
      </item>
      <item>
       <widget class="QFrame" name="card_best_tf">
        <property name="styleSheet">
         <string>QFrame { background-color: #1e222d; border: 1px solid #3d4450; border-radius: 6px; padding: 8px; }</string>
        </property>
        <property name="frameShape">
         <enum>QFrame::Shape::StyledPanel</enum>
        </property>
        <layout class="QVBoxLayout" name="verticalLayout_card4">
         <item>
          <widget class="QLabel" name="label_best_tf_title">
           <property name="styleSheet">
            <string>color: #787b86; font-size: 11px;</string>
           </property>
           <property name="text">
            <string>Bester TF</string>
           </property>
          </widget>
         </item>
         <item>
          <widget class="QLabel" name="label_best_tf">
           <property name="styleSheet">
            <string>color: #d1d4dc; font-size: 24px; font-weight: bold;</string>
           </property>
           <property name="text">
            <string>-</string>
           </property>
          </widget>
         </item>
        </layout>
       </widget>
      </item>
     </layout>
    </item>
    <item>
     <widget class="QWidget" name="paging_bar" native="true">
      <property name="fixedHeight" stdset="0">
       <number>32</number>
      </property>
      <layout class="QHBoxLayout" name="horizontalLayout_paging">
       <property name="spacing">
        <number>6</number>
       </property>
       <property name="leftMargin">
        <number>0</number>
       </property>
       <property name="topMargin">
        <number>0</number>
       </property>
       <property name="rightMargin">
        <number>0</number>
       </property>
       <property name="bottomMargin">
        <number>0</number>
       </property>
       <item>
        <widget class="QPushButton" name="btn_prev_page">
         <property name="styleSheet">
          <string>QPushButton { background-color: #2b5c8f; color: white; font-weight: bold; border-radius: 3px; } QPushButton:disabled { background-color: #37474f; color: #787b86; }</string>
         </property>
         <property name="text">
          <string>◀ Zurück</string>
         </property>
         <property name="fixedSize" stdset="0">
          <size>
           <width>90</width>
           <height>24</height>
          </size>
         </property>
        </widget>
       </item>
       <item>
        <widget class="QLabel" name="label_page_info">
         <property name="styleSheet">
          <string>color: #d1d4dc; font-weight: bold; font-size: 12px;</string>
         </property>
         <property name="text">
          <string>Seite 0 / 0</string>
         </property>
        </widget>
       </item>
       <item>
        <widget class="QPushButton" name="btn_next_page">
         <property name="styleSheet">
          <string>QPushButton { background-color: #2b5c8f; color: white; font-weight: bold; border-radius: 3px; } QPushButton:disabled { background-color: #37474f; color: #787b86; }</string>
         </property>
         <property name="text">
          <string>Weiter ▶</string>
         </property>
         <property name="fixedSize" stdset="0">
          <size>
           <width>90</width>
           <height>24</height>
          </size>
         </property>
        </widget>
       </item>
       <item>
        <spacer name="horizontalSpacer_paging_right">
         <property name="orientation">
          <enum>Qt::Orientation::Horizontal</enum>
         </property>
         <property name="sizeHint" stdset="0">
          <size>
           <width>40</width>
           <height>20</height>
          </size>
         </property>
        </spacer>
       </item>
      </layout>
     </widget>
    </item>
    <item>
     <widget class="QTableWidget" name="table_signals">
      <property name="styleSheet">
       <string>QTableWidget { background-color: #131722; color: #d1d4dc; gridline-color: #2B2B43; border: 1px solid #2B2B43; }
QHeaderView::section { background-color: #1e222d; color: #787b86; border: 1px solid #2B2B43; padding: 4px; font-weight: bold; }
QTableWidget::item { padding: 4px; }
QTableWidget::item:selected { background-color: #2b5c8f; }</string>
      </property>
      <property name="editTriggers">
       <set>QAbstractItemView::EditTrigger::NoEditTriggers</set>
      </property>
      <property name="selectionBehavior">
       <enum>QAbstractItemView::SelectionBehavior::SelectRows</enum>
      </property>
      <attribute name="horizontalHeaderStretchLastSection">
       <bool>true</bool>
      </attribute>
      <attribute name="verticalHeaderVisible">
       <bool>true</bool>
      </attribute>
      <column>
       <property name="text">
        <string>Time</string>
       </property>
      </column>
      <column>
       <property name="text">
        <string>Symbol</string>
       </property>
      </column>
      <column>
       <property name="text">
        <string>Timeframe</string>
       </property>
      </column>
      <column>
       <property name="text">
        <string>Signal-Set</string>
       </property>
      </column>
      <column>
       <property name="text">
        <string>Confidence</string>
       </property>
      </column>
      <column>
       <property name="text">
        <string>Outcome</string>
       </property>
      </column>
     </widget>
    </item>
   </layout>
  </widget>
 </widget>
 <resources/>
 <connections/>
</ui>

```

--------------------------------------------------

### DATEI: ui/window_manager.py
```py
# ui/window_manager.py
"""
ui/window_manager.py - Zentraler Fenster-Lifecycle-Manager (18.01.02, E5).

Kapselt die Sub-/Chart-Fenster-Verwaltung des MainWindow (Single Responsibility
Principle, Inversion of Control):

  * Wiederherstellung aller gespeicherten Fenster (restore_all_windows)
  * Oeffnen/Fokussieren von Chart-, Service-, Analytics- und Properties-Fenstern
  * Jump-to-Bar (open_chart_at_bar)
  * Ermittlung der aktuell aktiven Symbol/Timeframe-Paare (LiveTickWorker-Callback)

Der WindowManager kennt MainWindow NICHT (kein Import von main.py). Die
Kopplung erfolgt ueber Konstruktor-Parameter (parent + state_manager +
Listen-Referenzen). `restore_main_window_geometry` und die Tick-Verteilung
bleiben im MainWindow (E5).
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QApplication

from analytics.ui.analytics_win import AnalyticsWindow
from chart.chart_win import PyTraderChartWindow
from persistent_win import PersistentWindow
from properties_win import PropertiesWindow
from serviceui.service_win import ServiceWindow
from state_manager import StateManager


class WindowManager:
    """Verwaltet alle Sub-/Chart-Fenster des MainWindow (Fenster-Lifecycle)."""

    def __init__(self, parent, state_manager: StateManager,
                 chart_windows: List[PyTraderChartWindow],
                 persistent_sub_windows: List[PersistentWindow]) -> None:
        """Erstellt den Fenster-Manager.

        Args:
            parent: Qt-Parent fuer neu erzeugte Fenster (duck-typed, z. B. das
                    MainWindow – wird NIE importiert, E5/IoC).
            state_manager: StateManager – Persistenz (Instanzen, Geometrien).
            chart_windows: Referenz auf die Chart-Fenster-Liste des Aufrufers
                           (gemeinsames List-Objekt, in-place-Mutationen).
            persistent_sub_windows: Referenz auf die PersistentWindow-Liste
                           des Aufrufers (gemeinsames List-Objekt).
        """
        self._parent = parent
        self.state_manager = state_manager
        self.chart_windows = chart_windows
        self.persistent_sub_windows = persistent_sub_windows

    def restore_all_windows(self) -> None:
        """Stellt ALLE gespeicherten Fenster vollautomatisch und generisch wieder her.

        Nutzt die Klassen-Registry aus persistent_win.py, um ohne Hardcoding
        zwischen PersistentWindow-Subklassen (Service, Statistik) und
        dynamischen Chart-Fenstern zu unterscheiden.
        """
        all_instances: List[Dict[str, Any]] = self.state_manager.load_all_instances()
        if not all_instances:
            print("✨ Keine gespeicherten Instanzen vorhanden.")
            return

        print(f"🔄 Prüfe {len(all_instances)} gespeicherte Fenster-Einträge...")

        for inst in all_instances:
            inst_id = str(inst.get("instance_id", ""))
            if not inst_id or inst_id == "win_main":
                continue

            # 1. Fall: Registrierte PersistentWindow-Subklasse (Service, Statistik, etc.)
            window_cls = PersistentWindow.get_registered_class(inst_id)
            if window_cls is not None:
                if not PersistentWindow.should_auto_restore(inst_id):
                    print(f"  → Überspringe {inst_id} ({window_cls.__name__}): auto_restore=False")
                    continue
                print(f"  → Öffne registriertes Fenster: {inst_id} ({window_cls.__name__})")
                # WICHTIG: parent=self nur für state_manager-Zugriff, nicht als Qt-Parent!
                # PersistentWindow.__init__() übergibt kein Parent an QMainWindow,
                # damit das Fenster einen eigenen Taskleisten-Eintrag hat.
                win = window_cls(parent=self._parent)
                self.persistent_sub_windows.append(win)
                # Ohne Fokus anzeigen (damit MainWindow den Fokus behält)
                win.setAttribute(Qt.WA_ShowWithoutActivating, True)
                win.show()
                win.setAttribute(Qt.WA_ShowWithoutActivating, False)
                # Maximiert wiederherstellen (nach show(), ohne Fokus-Klau)
                if getattr(win, '_restored_is_maximized', False):
                    win.showMaximized()
                continue

            # 2. Fall: Dynamische Chart-Fenster (win_1, win_2, ...)
            if inst_id.startswith("win_"):
                print(f"  → Öffne Chart-Fenster: {inst_id}")
                win = PyTraderChartWindow(
                    instance_id=inst_id,
                    symbol=inst.get("symbol") or "SILVER",
                    timeframe=inst.get("timeframe") or "H1",
                    visible_from=inst.get("visible_range_from"),
                    visible_to=inst.get("visible_range_to"),
                    state_manager=self.state_manager
                )
                win.closed_signal.connect(self.handle_chart_closed)

                # Geometrie anwenden
                screen_geo = QApplication.primaryScreen().availableGeometry()
                pos_x, pos_y = inst.get("pos_x"), inst.get("pos_y")
                width = inst.get("width") or 900
                height = inst.get("height") or 600

                if pos_x is not None and pos_y is not None:
                    if pos_x < screen_geo.x() - 100 or pos_x > screen_geo.right() or \
                       pos_y < screen_geo.y() - 100 or pos_y > screen_geo.bottom():
                        pos_x, pos_y = 100, 100
                    win.move(pos_x, pos_y)
                    win.resize(width, height)

                if inst.get("is_maximized"):
                    win.showMaximized()
                else:
                    win.setAttribute(Qt.WA_ShowWithoutActivating, True)
                    win.show()
                    win.setAttribute(Qt.WA_ShowWithoutActivating, False)

                self.chart_windows.append(win)

        # MainWindow NICHT in den Vordergrund holen – die WA_ShowWithoutActivating-Logik
        # bei den Sub-Fenstern verhindert bereits Fokus-Klau. Ein erzwungenes
        # raise_() + activateWindow() würde nur stören, falls der User inzwischen
        # eine andere Anwendung fokussiert hat.

    def open_chart_window(self) -> None:
        new_id: str = self.state_manager.get_next_instance_id()
        win = PyTraderChartWindow(
            instance_id=new_id,
            symbol="SILVER",
            timeframe="H1",
            visible_from=None,
            visible_to=None,
            state_manager=self.state_manager
        )
        win.closed_signal.connect(self.handle_chart_closed)
        win.show()
        self.chart_windows.append(win)

    @Slot(str)
    def handle_chart_closed(self, instance_id: str) -> None:
        app = QApplication.instance()
        if getattr(app, '_is_quitting', False):
            return
        # In-place-Filter (gemeinsames List-Objekt mit dem Aufrufer, E5)
        self.chart_windows[:] = [w for w in self.chart_windows if w.instance_id != instance_id]

    def open_service_window(self) -> None:
        # Singleton: Bestehendes Fenster in den Vordergrund holen
        existing = ServiceWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = ServiceWindow(self._parent)  # parent nur für state_manager-Zugriff
        self.persistent_sub_windows.append(win)
        win.show()

    def open_analytics_window(self) -> None:
        # Phase 15 15.03: Statistik-Fenster durch AnalyticsWindow ersetzt
        # (win_statistics-Persistenz wird per E-2 nach win_analytics migriert).
        # Singleton: Bestehendes Fenster in den Vordergrund holen
        existing = AnalyticsWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = AnalyticsWindow(self._parent)  # parent nur für state_manager-Zugriff
        self.persistent_sub_windows.append(win)
        win.show()

    def open_properties_window(self) -> None:
        # Singleton: Bestehendes Fenster in den Vordergrund holen
        existing = PropertiesWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = PropertiesWindow(self._parent)
        self.persistent_sub_windows.append(win)
        win.show()

    def open_chart_at_bar(self, symbol: str, timeframe: str, bar_time: int) -> None:
        """Oeffnet oder fokussiert ein Chart-Fenster und scrollt zur angegebenen Bar-Position."""
        # Bestehendes Chart-Fenster mit passendem Symbol/TF suchen
        for win in self.chart_windows:
            try:
                if win.current_symbol == symbol and win.current_tf == timeframe and win.isVisible():
                    win.raise_()
                    win.activateWindow()
                    # Chart zur Position scrollen
                    win.visible_from = bar_time
                    win.visible_to = None
                    win.refresh_chart_data()
                    return
            except (RuntimeError, AttributeError):
                pass

        # Kein passendes Fenster gefunden -> neues oeffnen
        from chart.chart_win import PyTraderChartWindow
        new_id: str = self.state_manager.get_next_instance_id()
        win = PyTraderChartWindow(
            instance_id=new_id,
            symbol=symbol,
            timeframe=timeframe,
            visible_from=bar_time,
            visible_to=None,
            state_manager=self.state_manager
        )
        win.closed_signal.connect(self.handle_chart_closed)
        win.show()
        self.chart_windows.append(win)

    def get_currently_active_pairs(self) -> Set[Tuple[str, str]]:
        active_pairs: Set[Tuple[str, str]] = set()
        for win in list(self.chart_windows):
            try:
                if win.isVisible():
                    active_pairs.add((win.current_symbol, win.current_tf))
            except (RuntimeError, AttributeError):
                pass
        return active_pairs

```

--------------------------------------------------

### DATEI: workers/__init__.py
```py
# workers/__init__.py
"""
workers-Paket (18.01.02, E7): Qt-Hintergrund-Threads.

  * data_sync_worker.py – DataSyncWorker (MT5-Historie-Sync)
  * live_tick_worker.py – LiveTickWorker (Tick-Polling + Bar-Close-Persistenz)

Kein Import von main.py (E4); UI-Logik ist verboten (SRP).
"""

```

--------------------------------------------------

### DATEI: workers/data_sync_worker.py
```py
# workers/data_sync_worker.py
"""
workers/data_sync_worker.py - Hintergrund-Sync der historischen Marktdaten.

Ausgelagert aus main.py im Rahmen von 18.01.02 (E7). Der Worker fuehrt den
Voll-/Update-Import der MT5-Historie in einem QThread aus und emittiert die
aktualisierten Symbol/Timeframe-Paare. Keine UI-Logik (SRP).
"""

from typing import Set, Tuple

from PySide6.QtCore import QThread, Signal

from data_sync.mt5_sync_service import sync_market_data


class DataSyncWorker(QThread):
    """Führt den Hintergrund-Sync für alle historischen Daten aus."""

    sync_completed = Signal(object)

    def run(self) -> None:
        """Führt den Hintergrund-Sync für alle historischen Daten aus."""
        try:
            updated_pairs: Set[Tuple[str, str]] = sync_market_data()
            self.sync_completed.emit(updated_pairs)
        except Exception as e:
            print(f"❌ Fehler im DataSyncWorker: {e}")
            self.sync_completed.emit(set())

```

--------------------------------------------------

### DATEI: workers/live_tick_worker.py
```py
# workers/live_tick_worker.py
"""
workers/live_tick_worker.py - Kontinuierliches MT5-Tick-Polling & Bar-Close.

Ausgelagert aus main.py im Rahmen von 18.01.02 (E7). Der Worker pollt
MT5-Ticks fuer die aktuell aktiven Symbol/Timeframe-Paare, erkennt
Bar-Close-Events, schreibt abgeschlossene Kerzen in market_data.duckdb und
emittiert Live-Candle-Updates an die Charts. Keine UI-Logik (SRP).
"""

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Set, Tuple

import MetaTrader5 as mt5
from PySide6.QtCore import QThread, Signal

from data_sync.mt5_sync_service import MT5_LOCK, get_timeframes
from db.db_pool import DB_MARKET_DATA, DbPool


class LiveTickWorker(QThread):
    """Kontinuierliche MT5-Tick-Polling-Schleife mit Bar-Close-Erkennung."""

    ticks_ready = Signal(str)

    def __init__(self, get_active_pairs_callback: Callable[[], Set[Tuple[str, str]]]) -> None:
        super().__init__()
        self.get_active_pairs: Callable[[], Set[Tuple[str, str]]] = get_active_pairs_callback
        self._running: bool = True
        self._last_bar_times: Dict[str, int] = {}  # Für Bar-Close-Erkennung
        self._last_bar_data: Dict[str, Dict[str, Any]] = {}  # OHLCV der letzten abgeschlossenen Kerze

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        """Kontinuierliche Polling-Schleife für MT5-Ticks mit try/finally Freigabe.
        Erkennt Bar-Close-Events und schreibt abgeschlossene Kerzen in market_data.duckdb."""
        try:
            with MT5_LOCK:
                if not mt5.initialize():
                    # MT5 ist möglicherweise bereits von MainWindow initialisiert
                    print("⚠️ [LiveTickWorker] mt5.initialize() war False, versuche trotzdem weiter...")

            while self._running:
                active_pairs: Set[Tuple[str, str]] = self.get_active_pairs()
                if not active_pairs:
                    self.msleep(200)
                    continue

                results: Dict[str, Dict[str, float | int]] = {}
                try:
                    for symbol, tf_str in active_pairs:
                        mt5_tf: Optional[int] = get_timeframes().get(tf_str)
                        if mt5_tf is None:
                            continue

                        with MT5_LOCK:
                            tick = mt5.symbol_info_tick(symbol)
                            rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, 1)

                        if tick and rates is not None and len(rates) > 0:
                            rate = rates[0]
                            key: str = f"{symbol}|{tf_str}"
                            current_bar_time = int(rate['time'])

                            # Bar-Close erkennen: neue Bar-Time != letzte Bar-Time
                            last_bar = self._last_bar_times.get(key, 0)
                            if last_bar > 0 and current_bar_time > last_bar:
                                # Alte (abgeschlossene) Kerze aus dem Zwischenspeicher in DB schreiben
                                last_data = self._last_bar_data.get(key)
                                if last_data:
                                    self._persist_bar(symbol, tf_str, last_bar, last_data)

                            # Aktuelle Kerze zwischenspeichern (wird beim nächsten Bar-Close persistiert)
                            self._last_bar_times[key] = current_bar_time
                            self._last_bar_data[key] = {
                                'open': float(rate[1]),  # open
                                'high': float(rate[2]),  # high
                                'low': float(rate[3]),   # low
                                'close': float(rate[4]), # close
                                'tick_volume': int(rate[5]) if len(rate) > 5 else 0,
                                'spread': int(rate[6]) if len(rate) > 6 else 0,
                                'real_volume': int(rate[7]) if len(rate) > 7 else 0,
                            }

                            # JEDEN Tick an die Charts senden (für Live-Candle-Updates)
                            results[key] = {
                                "time": current_bar_time,
                                "open": float(rate['open']),
                                "high": max(float(rate['high']), float(tick.bid)),
                                "low": min(float(rate['low']), float(tick.bid)),
                                "close": float(tick.bid)
                            }
                except Exception as e:
                    print(f"⚠️ [LiveTickWorker] Fehler in Poll-Schleife: {e}")

                if results:
                    self.ticks_ready.emit(json.dumps(results))

                self.msleep(500)

        finally:
            with MT5_LOCK:
                try:
                    mt5.shutdown()
                except Exception:
                    pass

    def _persist_bar(self, symbol: str, tf_str: str, bar_time: int, bar_data: Dict[str, Any]) -> None:
        """Schreibt eine abgeschlossene Kerze per INSERT OR REPLACE in market_data.duckdb."""
        try:
            con = DbPool.get(DB_MARKET_DATA)
            con.execute("""
                INSERT OR REPLACE INTO ohlcv_bars (symbol, timeframe, time, open, high, low, close, tick_volume, spread, real_volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                symbol,
                tf_str,
                datetime.fromtimestamp(bar_time, tz=timezone.utc),
                bar_data['open'],
                bar_data['high'],
                bar_data['low'],
                bar_data['close'],
                bar_data['tick_volume'],
                bar_data['spread'],
                bar_data['real_volume'],
            ])
        except Exception as e:
            print(f"⚠️ [LiveTickWorker] Fehler beim Persistieren von {symbol} {tf_str} @ {bar_time}: {e}")

```

--------------------------------------------------

