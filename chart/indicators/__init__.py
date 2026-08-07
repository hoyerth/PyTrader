# ==============================================================================
# chart/indicators/__init__.py
# ==============================================================================
# Phase 15: Alt-Indikator 'grid' (grid.py) entfernt. Verbleibende Indikatoren
# werden direkt über ihre Module importiert (z. B. chart_win.py importiert
# chart.indicators.ind_fixed_grid_proximity.FixedGridProximityIndicator bzw.
# chart.indicators.ind_moving_averages.MultiMovingAverageIndicator).
# Naming Convention 16.08.01: Dateiname = indicator_id (ind_-Präfix).
# Keine Exporte im Paket-__init__ – keine harten Imports erforderlich.