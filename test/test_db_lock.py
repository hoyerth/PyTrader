# BEREIT FÜR PHASE 15
# test/test_db_lock.py
"""Test: Kann ein paralleler Schreiber (INSERT-Loop) neue Lese-Verbindungen blockieren?
Simuliert DataSyncWorker (schreibt) vs. MarketDataRepository (liest via db_connect)."""
import os
import sys
import threading
import time

sys.path.insert(0, r"F:\Python\PyTrader")

import duckdb

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locktest.duckdb")
if os.path.exists(DB):
    os.remove(DB)

con = duckdb.connect(DB)
con.execute("CREATE TABLE t (id INT, val DOUBLE)")
con.execute("INSERT INTO t SELECT i, i*1.0 FROM range(100000) r(i)")
con.close()

failures = []
stop = threading.Event()

def writer():
    wc = duckdb.connect(DB)
    i = 0
    while not stop.is_set():
        wc.execute("INSERT INTO t SELECT ? + i, i*1.0 FROM range(1000) r(i)", [i])
        i += 1000
        wc.execute("DELETE FROM t WHERE id < ?", [i])
    wc.close()

t = threading.Thread(target=writer, daemon=True)
t.start()

# Reader: wiederholt neue Verbindung oeffnen und lesen (wie db_connect)
attempts = 0
errors = 0
time.sleep(0.2)
for _ in range(50):
    try:
        rc = duckdb.connect(DB)
        row = rc.execute("SELECT COUNT(*) FROM t").fetchone()
        rc.close()
        if row is None:
            errors += 1
    except Exception as e:
        errors += 1
        failures.append(str(e))
    attempts += 1
    time.sleep(0.05)

stop.set()
t.join(timeout=2)

print(f"Attempts: {attempts}, Errors: {errors}")
if failures:
    print("Erste Fehler:")
    for f in failures[:5]:
        print("  ", f)

os.remove(DB)
print("LOCKTEST FERTIG")
