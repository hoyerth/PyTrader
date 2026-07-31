import duckdb

con = duckdb.connect(r'F:/Python/PyTrader/trading_data.duckdb')
tables = con.execute("SHOW TABLES").fetchall()
print("Tables:", tables)

# Try listing schemas
schemas = con.execute("SELECT * FROM information_schema.schemata").fetchall()
print("Schemata:", schemas)

# Try a direct query on sih1_candles
try:
    r = con.execute("SELECT count(*) FROM sih1_candles").fetchall()
    print("sih1_candles count:", r)
except Exception as e:
    print("sih1_candles error:", e)

# Try to find ANY table with candle in name
try:
    r = con.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema NOT IN ('information_schema', 'pg_catalog')").fetchall()
    print("User tables:", r)
except Exception as e:
    print("User tables error:", e)
