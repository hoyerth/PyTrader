# BEREIT FÜR PHASE 15
# test/check_app_state.py
"""Liest den gespeicherten App-State (visible ranges, Instanzen) fuer die Diagnose
der Chart-Leerstelle. KEIN UI-Test."""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import duckdb

con = duckdb.connect("data/app_data.duckdb", read_only=True)

print("=== window_instances ===")
try:
    rows = con.execute("SELECT * FROM window_instances").fetchall()
    cols = [d[0] for d in con.description]
    for r in rows:
        print("  " + ", ".join(f"{c}={v}" for c, v in zip(cols, r)))
except Exception as e:
    print("  Fehler:", e)

print("\n=== instance_states ===")
try:
    rows = con.execute("SELECT * FROM instance_states").fetchall()
    cols = [d[0] for d in con.description]
    for r in rows:
        print("  " + ", ".join(f"{c}={v}" for c, v in zip(cols, r)))
except Exception as e:
    print("  Fehler:", e)

print("\n=== symbol_tf_states ===")
try:
    rows = con.execute("SELECT * FROM symbol_tf_states").fetchall()
    cols = [d[0] for d in con.description]
    for r in rows:
        print("  " + ", ".join(f"{c}={v}" for c, v in zip(cols, r)))
except Exception as e:
    print("  Fehler:", e)

print("\n=== global_settings ===")
try:
    rows = con.execute("SELECT * FROM global_settings").fetchall()
    for r in rows:
        print("  ", r)
except Exception as e:
    print("  Fehler:", e)

con.close()
