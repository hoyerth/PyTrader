"""
serviceui/service_selector_dialog_constants.py - Modul-Konstanten des ServiceSelectorDialog

23.08 God-File-Split (15.08.2026): Aus serviceui/service_selector_dialog.py
ausgelagert, KEINE Logik-Aenderung. Die Hauptdatei re-exportiert alle Namen,
damit __init__ (BODY_SPACING/TREE_DEFAULT_WIDTH) und die Mixin-Methoden
(DIALOG_GEOMETRY_KEY, PANEL_BUFFER) sie ohne Zirkularimport nutzen koennen.
"""

#: Geometrie-Key fuer Position/Groesse des Datenquellen-Dialogs
#: (global_settings, Muster IndicatorSettingsDialog).
DIALOG_GEOMETRY_KEY = "service_selector"
#: Puffer fuer ScrollArea-Rahmen/-Scrollbar, damit 2 Spalten OHNE horizontale
#: Scrollbar nebeneinander passen (Punkt 2).
PANEL_BUFFER = 24
#: Body-Spacing (body.setSpacing(8) unten) – fuer die Breiten-Rechnung (Punkt 3).
BODY_SPACING = 8
#: 06.08.2026 (Punkte 3+4): FESTE Default-Breite des MasterTree (links).
#: Beim manuellen Vergroessern des Fensters behaelt der Tree diese Breite;
#: nur die Parameter-Box waechst mit (bzw. schrumpft bis zu ihrer
#: Minimum-Breite = Platz fuer zwei Service-Spalten nebeneinander).
TREE_DEFAULT_WIDTH = 300
