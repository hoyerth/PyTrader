# test/check_mt5_m1_boundary.py
"""Holt SILVER M1-Daten direkt von MT5 (Ground Truth) und analysiert die
Tagesgrenzen der letzten Tage.
WICHTIG: MT5 liefert Zeiten als BERLIN-WANDUHR-encoded Epochs (empirisch
verifiziert: tick.time liegt bei echter UTC 10:00 bereits bei der Zahl "12:00").
datetime.fromtimestamp(e, tz=utc) liefert daher direkt die Wanduhrzeit -
eine zusaetzliche +2h-Umrechnung waere doppelt.
KEIN UI-Test - nur Datenabruf + Logik."""
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import MetaTrader5 as mt5

print("Initialisiere MT5...")
if not mt5.initialize():
    print(f"MT5 initialize fehlgeschlagen: {mt5.last_error()}")
    sys.exit(1)

info = mt5.account_info()
if info:
    print(f"Konto: {info.company} | Server: {info.server} | Login: {info.login}")
else:
    print("Kein Konto (oder Fehler):", mt5.last_error())

SYMBOL = "SILVER"
N_BARS = 20000

print(f"\n=== SILVER M1: letzte {N_BARS} Bars von MT5 ===")
rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, N_BARS)
if rates is None:
    print(f"copy_rates_from_pos Fehler: {mt5.last_error()}")
    mt5.shutdown()
    sys.exit(1)

print(f"Bars erhalten: {len(rates)}")

# rates ist numpy-Struktur. Felder: time, open, high, low, close, tick_volume, spread, real_volume
import numpy as np

t = rates["time"]  # Roh-Epoch (bereits Berlin-Wanduhr-encoded)
o = rates["open"]
h = rates["high"]
l = rates["low"]
c = rates["close"]

def fmt_epoch(epoch):
    wall = datetime.fromtimestamp(int(epoch), tz=timezone.utc)  # == Wanduhrzeit
    return f"{wall.strftime('%d.%m.%y %H:%M')} (Wanduhr)"

print(f"\n=== Erste/Letzte Bar ===")
print(f"  Erste: {fmt_epoch(t[0])}")
print(f"  Letzte: {fmt_epoch(t[-1])}")

# Tagesgrenzen finden: Wanduhr-Tag wechselt
print(f"\n=== Tagesgrenzen (Wanduhr) in den letzten Tagen ===")
prev_day = None
for i in range(len(t)):
    wall = datetime.fromtimestamp(int(t[i]), tz=timezone.utc)
    day = wall.date()
    if prev_day is not None and day != prev_day:
        # i ist die erste Bar des neuen Tages
        j = i - 1
        while j >= 0:
            prev_wall = datetime.fromtimestamp(int(t[j]), tz=timezone.utc)
            if prev_wall.date() == prev_day:
                break
            j -= 1
        # letzten 3 Bars des Vortags und erste 3 Bars des neuen Tags
        print(f"\n--- Grenze {prev_day} -> {day} ---")
        for k in range(max(0, j - 2), min(len(t), j + 4)):
            label = "VORTAG " if k <= j else "NEU-TAG"
            print(f"  [{label}] idx={k} {fmt_epoch(t[k])}  O={o[k]:.3f} H={h[k]:.3f} L={l[k]:.3f} C={c[k]:.3f}")
    prev_day = day

# Luecken-Analyse (Differenz > 60s), letzte 3000 Bars
print(f"\n=== Luecken > 60s (letzte 3000 Bars) ===")
start_idx = max(0, len(t) - 3000)
gaps = []
for i in range(start_idx + 1, len(t)):
    diff = int(t[i]) - int(t[i - 1])
    if diff > 60:
        prev_w = datetime.fromtimestamp(int(t[i - 1]), tz=timezone.utc)
        curr_w = datetime.fromtimestamp(int(t[i]), tz=timezone.utc)
        # Handelspause: letzte Bar 22:xx Wanduhr, naechste 00:xx Wanduhr
        # (Pause = Wanduhr 23:00-23:59), diff = 3720s
        is_pause = (prev_w.hour >= 22 and curr_w.hour <= 0 and curr_w.minute < 10) or diff > 3600
        gaps.append((prev_w, curr_w, diff, is_pause))

for prev_w, curr_w, diff, is_pause in gaps:
    tag = "[PAUSE 23-24]" if is_pause else "[!!! LUEKE]"
    print(f"  {prev_w.strftime('%d.%m %H:%M')} -> {curr_w.strftime('%d.%m %H:%M')}  diff={diff}s {tag}")

print(f"\nLuecken gesamt: {len(gaps)}")

# Bars in der Zeit 23:00-23:59 Wanduhr (innerhalb der Pause) - sollten 0 sein
print(f"\n=== Bars zwischen Wanduhr 23:00-23:59 (innerhalb Pause?) ===")
in_pause = 0
for i in range(len(t)):
    wall = datetime.fromtimestamp(int(t[i]), tz=timezone.utc)
    if wall.hour == 23 and t[i] >= t[-3000] if len(t) >= 3000 else True:
        in_pause += 1
print(f"  Bars mit Wanduhr-Stunde 23: {in_pause} (in letzten {min(3000, len(t))} Bars)")

mt5.shutdown()
print("\nFertig.")
