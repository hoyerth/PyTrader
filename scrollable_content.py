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
