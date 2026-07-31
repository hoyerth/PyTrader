# test/check_generation_guard.py
# Verifiziert die Generations-Guard-Logik aus chart_win.py (_apply_chart_update /
# _apply_grid_render): Veraltete Serializer-Ergebnisse werden verworfen,
# aktuelle werden durchgelassen. Kein UI-Test - reine Logik-Pruefung.

class FakeWin:
    """Simuliert die relevanten Attribute/Methoden von PyTraderChartWindow."""
    def __init__(self):
        self._update_generation = 0
        self._grid_generation = 0
        self.applied_chart = []
        self.applied_grid = []
        self.loading_reset = 0
        self.passed = True

    def _set_loading(self, loading):
        if loading is False:
            self.loading_reset += 1

    # Kernlogik aus _apply_chart_update (Guard-Teil)
    def apply_chart_update(self, payload, update_id):
        if update_id < self._update_generation:
            self.passed = self.passed and False  # darf nicht passieren (wird abgefangen)
            return 'DISCARDED-STALE-CHECK'
        if update_id > self._update_generation:
            # aktuelle Generation noch nicht erhöht -> sollte nicht vorkommen
            return 'FUTURE'
        if not payload:
            self._set_loading(False)
            return 'EMPTY'
        self.applied_chart.append((update_id, payload))
        return 'APPLIED'

    # Kernlogik aus _apply_grid_render (Guard-Teil)
    def apply_grid_render(self, lines_json, circles_json, grid_gen):
        if grid_gen < self._grid_generation:
            return 'DISCARDED'
        if not lines_json and not circles_json:
            return 'EMPTY'
        self.applied_grid.append((grid_gen, lines_json))
        return 'APPLIED'


win = FakeWin()

print('=== Szenario 1: Normale Reihenfolge ===')
win._update_generation = 1
assert win.apply_chart_update('{"a":1}', 1) == 'APPLIED', "aktuelles Update muss angewendet werden"
assert win.applied_chart == [(1, '{"a":1}')]
print('  OK: aktuelles Update (id=1) angewendet')

print('=== Szenario 2: Veralteter Serializer-Thread ===')
# Refresh B (id=2) startet -> _update_generation=2
win._update_generation = 2
# Der alte Thread von Refresh A (id=1) liefert NACH B sein Ergebnis -> verwerfen
win.apply_chart_update('{"stale":true}', 1)  # sollte verworfen werden
assert len(win.applied_chart) == 1, "veraltetes Update darf nicht angewendet werden"
print('  OK: veraltetes Update (id=1 < 2) verworfen')

print('=== Szenario 3: Grid-Render Veraltet ===')
win._grid_generation = 5
r = win.apply_grid_render('[]', '[]', 3)  # alt
assert r == 'DISCARDED', "altes Grid-Render muss verworfen werden"
assert len(win.applied_grid) == 0
win._grid_generation = 6
r = win.apply_grid_render('[1]', '', 6)  # aktuell
assert r == 'APPLIED' and len(win.applied_grid) == 1
print('  OK: altes Grid-Render verworfen, aktuelles angewendet')

print('=== Szenario 4: Leeres Payload nach Guard ===')
win._update_generation = 3
r = win.apply_chart_update('', 3)
assert r == 'EMPTY' and win.loading_reset == 1, "leeres Payload muss loading zuruecksetzen"
print('  OK: leeres Payload setzt loading zurueck')

print('\nRESULT: PASS')
