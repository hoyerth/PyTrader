# ui/__init__.py
"""
ui-Paket (18.01.02, E5 / 23.02): Fenster-Lifecycle-Management & UI-Fenster.

  * window_manager.py  – WindowManager (Sub-/Chart-Fenster, Jump-to-Bar)
  * statistic_win.py   – Statistik-Fenster (von 15.03 Analytics abgeloest, legacy)
  * properties_win.py  – PropertiesWindow (Instanz-Eigenschaften)

Kein Import von main.py (IoC – der WindowManager kennt MainWindow nicht).
"""
