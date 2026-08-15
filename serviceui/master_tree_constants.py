"""
serviceui/master_tree_constants.py - Konstanten, isValid, _expandable_label, TreeItemIterator

23.06 God-File-Split (15.08.2026): Aus serviceui/master_tree.py ausgelagert,
KEINE Logik-Aenderung. Die Hauptdatei re-exportiert alle Namen, damit externe
Importe (TYPE_*, ROLE_*, MIME_CATEGORY_MOVE, TreeItemIterator, ...) unveraendert
funktionieren. isValid/_expandable_label/TreeItemIterator stehen hier, weil sie
von mehreren Mixins genutzt werden und sonst einen Zirkularimport erzeugen
wuerden (master_tree importiert die Mixins, die Mixins importieren die
Support-Datei).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from typing import Optional

# 18.01.03 (Dynamic Tree Management): MIME-Typ fuer den internen
# Kategorie-Drag & Drop. Die MIME-Daten kodieren den gezogenen Knoten als
# JSON: {"node_type": "set|plugin|category", "group": "sets|plugins",
#         "id": <set_id|plugin_id|category-path>, "path": <Quell-Pfad>}.
MIME_CATEGORY_MOVE = "application/x-pytrader-category-move"

# P15-Bugfix: shiboken6.isValid() schuetzt vor dem Zugriff auf bereits
# C++-seitig zerstoerte Items (QTreeWidget.clear() nach data_changed bei
# wildem Klicken) – verhindert Access Violation (0xC0000005).
try:
    from shiboken6 import isValid
except ImportError:  # pragma: no cover
    def isValid(obj) -> bool:  # type: ignore
        return obj is not None

# UserRole-Kennungen fuer die Knotentypen (Deterministische Auswertung)
ROLE_NODE_TYPE = Qt.UserRole
ROLE_SET_ID = Qt.UserRole + 1
ROLE_INSTANCE_ID = Qt.UserRole + 2
ROLE_PLUGIN_ID = Qt.UserRole + 3
# 20.04 (Q6/Q7): Zusaetzliche Rollen fuer Clone-Knoten (TYPE_CLONE) und
# die Archiv-Kennzeichnung. ROLE_INSTANCE_HASH traegt den 8-stelligen
# Parameter-Hash eines Clones (generate_instance_hash); ROLE_ARCHIVED=True
# markiert archivierte Knoten (non-checkable, Archiv-Safety).
ROLE_INSTANCE_HASH = Qt.UserRole + 4
ROLE_ARCHIVED = Qt.UserRole + 5
# 10.08.2026 (Bugfix): ROLE_PRESET_NAME traegt den Anzeigenamen eines
# Clone-/Preset-Knotens (fuer den 'Variante umbenennen'-Dialog, ohne
# DB-Lookup im MasterTree).
ROLE_PRESET_NAME = Qt.UserRole + 6

# 15.03-E (Multi-Select): Klickzone der Checkbox-Indikatoren in Spalte 0.
# Klicks links dieser Zone (innerhalb der Item-Zeile) werden dem Qt-Default
# ueberlassen, damit die Checkbox togglet (itemChanged feuert); Klicks
# rechts davon togglen weiterhin das Auf-/Zuklappen (mousePressEvent).
CHECKBOX_ZONE_WIDTH = 24

#: Knotentypen
TYPE_GROUP = "group"
TYPE_SET = "set"
TYPE_SERVICE = "service"
TYPE_PLUGIN = "plugin"
# 20.04 (Q7): Clone-/Preset-Knoten (Kind eines Plugin-Parents in der
# Services-Gruppe). Traegt ROLE_PLUGIN_ID (plugin_id des Parents) und
# ROLE_INSTANCE_HASH; aktive Clones sind anhakbar, archivierte nicht.
TYPE_CLONE = "clone"
# 16.08 (K3): Kategorie-Ordner-Knoten (Dynamic Category Trees). Nicht
# auswaehlbar, expandierbar; traegt KEINEN Info-Button (K5), keine Badges
# und ist im Checkbox-Modus nicht anhakbar (K4).
TYPE_CATEGORY = "category"

# Bugfix 2.1 (04.08.2026, aktualisiert): Lange Relationstexte in der Badge-
# Spalte (z. B. "📌 im Ind_FixedGridProximity | ⚪ inaktiv in ...") werden auf
# das Info-Zeichen 'i' gekuerzt – der Indikator-Name steht im Tooltip der
# Spalte 1 (keine extrem breiten Spalten im MasterTree).
MAX_BADGE_CELL_CHARS = 24
# Bugfix 04.08.2026 (Punkt 5): ASCII 'i' statt Unicode '🛈' (U+1F5D8) – das
# Emoji rendert in den Qt-Fonts unter Windows nicht zuverlaessig (tofu-Box).
# WICHTIG (05.08.2026): Der Text-'i' ist durch den echten Info-Button ersetzt;
# die Konstante bleibt nur als Test-Referenz erhalten (Historik).
BADGE_TRUNCATE_ICON = "i"

# Bugfix 20.03.01 (09.08.2026): Das Unicode-Zeichen "ℹ" (U+2139) rendert
# unter Windows in Qt bei fehlendem Font als Tofu-Box – der Info-Button
# war nicht mehr erkennbar (User-Meldung 'i-Button im Tree geht nicht
# mehr'; vgl. Bugfix 04.08.2026, Punkt 5: Unicode-Badge '🛈' ebenfalls
# durch ASCII 'i' ersetzt). Daher wieder ASCII 'i' als Button-Beschriftung.
# Der QPushButton (Spalte 1) ersetzt seit 05.08.2026 das Badge-Text-'i';
# die Status-Spalte wird auf die Button-Breite verkleinert (Spalte 0 ist
# Stretch und bekommt den freien Platz). Der Button erscheint auf ALLEN
# Service-/Plugin-/Set-Zeilen; gehoert die Zeile einem Indikator, ist er
# gelb (#FFD700) und traegt den Tooltip 'aktiv/im <Indikator>'
# (Namenslogik unveraendert aus _apply_badge).
INFO_BUTTON_TEXT = "i"
INFO_BUTTON_SIZE = 20          # ~Icon-Breite
INFO_BUTTON_WIDTH = 24         # Spaltenbreite (Status-Spalte)
INFO_BUTTON_COLOR_INDICATOR = "#FFD700"   # gelb bei Indikator-Zugehoerigkeit
INFO_BUTTON_COLOR_NEUTRAL = "#666666"     # neutral sonst

# Bugfix 3.0 (04.08.2026): Status-Spalte (Spalte 1) ist eine schmale
# Festbreiten-Spalte ganz rechts. Die Breite richtet sich seit 05.08.2026
# nach dem Info-Button (INFO_BUTTON_WIDTH); BADGE_COLUMN_WIDTH bleibt als
# Test-Referenz fuer die historische Text-Badge-Breite erhalten.
BADGE_COLUMN_WIDTH = 36

# Bugfix 3.1 (04.08.2026, aktualisiert): Einrueckung + '>'/'⌄'-Marker.
# Untereintraege sind per setIndentation(LEVEL_INDENT) eingerueckt; die
# Auf-/Zuklapp-Markierung uebernimmt das Symbol vor dem Namen ('>' bei
# eingeklappt, '⌄' bei ausgeklappt, siehe _expandable_label). drawBranches
# bleibt als bewusst leerer Override erhalten, damit Qt KEINE nativen
# Branch-Dreiecke zeichnet. Ein einfacher Mausklick auf die GESAMTE Zeile
# eines aufklappbaren Knotens togglet (Punkt 4) – der fruehere schmale
# Klickstreifen entfaellt. BRANCH_ZONE_WIDTH bleibt nur als Test-Referenz
# erhalten (historische Symbol-Klickzone).
BRANCH_ZONE_WIDTH = 16

# Bugfix (04.08.2026): Hierarchie-Einrueckung in Pixeln je Ebene (Qt-Default
# 20px) – Untereintraege (Service-Instanzen unter Sets, Sets unter Gruppen)
# werden dadurch sichtbar eingerueckt statt buendig angeordnet.
LEVEL_INDENT = 20


def _expandable_label(name: str, has_children: bool,
                      is_expanded: bool) -> str:
    """Auf-/Zuklapp-Praefix fuer Knoten mit Untereintraegen (04.08.2026).

    An jedem Knoten, der Kinder enthaelt (potentiell aufklappbar), steht ein
    Symbol vor dem Namen: '>' wenn eingeklappt, '⌄' wenn ausgeklappt.
    Blatt-Knoten (ohne Kinder) erhalten keinen Praefix.
    """
    if not has_children:
        return name
    return ("⌄ " if is_expanded else "> ") + name
class TreeItemIterator:
    """Leichter Iterator ueber alle QTreeWidgetItems (rekursiv, depth-first).

    P15-Bugfix: isValid-Guard im __next__ – Items koennen zwischen Sammlung
    und Iteration C++-seitig zerstoert werden (clear() bei data_changed).
    """

    def __init__(self, tree: QTreeWidget) -> None:
        self._items: list = []
        try:
            for i in range(tree.topLevelItemCount()):
                self._collect(tree.topLevelItem(i))
        except (RuntimeError, AttributeError):
            self._items = []
        self._index = 0

    def _collect(self, item: Optional[QTreeWidgetItem]) -> None:
        if item is None or not isValid(item):
            return
        self._items.append(item)
        try:
            for i in range(item.childCount()):
                self._collect(item.child(i))
        except (RuntimeError, AttributeError):
            pass

    def __iter__(self):
        self._index = 0
        return self

    def __next__(self) -> Optional[QTreeWidgetItem]:
        if self._index >= len(self._items):
            raise StopIteration
        item = self._items[self._index]
        self._index += 1
        if item is None or not isValid(item):
            return None
        return item
