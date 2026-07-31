# db_service.py
"""
db_service.py - MT5 Sync Service for PyTrader mit globaler Thread-Sperre, TIMESTAMPTZ & Native Upsert (INSERT OR REPLACE)
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Set, Tuple, Optional, List, Dict, Any
import duckdb
import pandas as pd

# ==============================================================================
# CONFIGURATION & THREAD SAFETY
# ==============================================================================
DATA_DIR = "data"
DB_MARKET_DATA = os.path.join(DATA_DIR, "market_data.duckdb")
DB_ANALYTICS = os.path.join(DATA_DIR, "analytics.duckdb")
DB_APP_DATA = os.path.join(DATA_DIR, "app_data.duckdb")

SYMBOLS = ["SILVER", "GOLD"]

# TIMEFRAMES als Lazy-Initialisierung (vermeidet MT5-DLL-Load beim Import)
_TIMEFRAMES_CACHE: Optional[Dict[str, int]] = None


def get_timeframes() -> Dict[str, int]:
    """Gibt das Timeframe-Mapping zurueck (lazy, importiert mt5 nur bei Bedarf)."""
    global _TIMEFRAMES_CACHE
    if _TIMEFRAMES_CACHE is None:
        import MetaTrader5 as _mt5
        _TIMEFRAMES_CACHE = {
            "MN1": _mt5.TIMEFRAME_MN1,
            "W1": _mt5.TIMEFRAME_W1,
            "D1": _mt5.TIMEFRAME_D1,
            "H4": _mt5.TIMEFRAME_H4,
            "H1": _mt5.TIMEFRAME_H1,
            "M30": _mt5.TIMEFRAME_M30,
            "M15": _mt5.TIMEFRAME_M15,
            "M10": _mt5.TIMEFRAME_M10,
            "M5": _mt5.TIMEFRAME_M5,
            "M2": _mt5.TIMEFRAME_M2,
            "M1": _mt5.TIMEFRAME_M1,
        }
    return _TIMEFRAMES_CACHE

TF_SECONDS_MAP: Dict[str, int] = {
	"M1": 60,
	"M2": 120,
	"M5": 300,
	"M10": 600,
	"M15": 900,
	"M30": 1800,
	"H1": 3600,
	"H4": 14400,
	"D1": 86400,
	"W1": 604800,
	"MN1": 2592000,
}

MT5_LOCK = threading.Lock()

# ==============================================================================
# DB LOCK-FREIER CONNECTION-HELPER
# ==============================================================================
# DuckDB unterstützt Multiple Connections innerhalb eines Prozesses nativ.
# Threading-Locks sind hier kontraproduktiv, da sie z. B. eine dauerhaft
# offene Haupt-Connection (self.db in MainWindow) blockieren.
# Cross-Prozess-Konflikte (IO Error: file is already open) werden durch
# sauberes Beenden vorheriger Prozesse gelöst, nicht durch threading.Lock.


def with_db_lock(db_path: str):
    """No-op decorator (Lock-frei). Beibehalten für API-Kompatibilität."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ==============================================================================
# DB CONNECTION POOL (Thread-local Singleton) – eine Connection pro Thread & DB
# ==============================================================================
# Loest drei Kernprobleme unter Windows:
#   1. "Can't open a connection with a different configuration" – immer gleiche Config
#   2. "Cannot open file – file used by another process" – keine Open/Close-Zyklen
#   3. DuckDB-Connections sind nicht thread-safe – eigenes Connection pro Thread
#
# Nutzung: DbPool.get(db_path) statt db_connect(db_path)
# Connections werden automatisch via atexit geschlossen.

_db_pool_lock = threading.Lock()
_db_pool_global: Dict[str, int] = {}  # abs_path -> Referenzzähler (fuer atexit)


class DbPool:
    """Thread-sicherer Connection-Pool: eine persistente Connection pro Thread & DB-Datei."""

    _local = threading.local()

    @staticmethod
    def get(db_path: str) -> duckdb.DuckDBPyConnection:
        """Gibt eine persistente Connection zur DB-Datei zurueck (eine pro Thread).
        Die Connection lebt bis Prozess-Ende und wird nie geschlossen."""
        abs_path = os.path.abspath(db_path)
        # Thread-local Storage: Jeder Thread hat seine eigenen Connections
        if not hasattr(DbPool._local, 'conns'):
            DbPool._local.conns = {}
        if abs_path not in DbPool._local.conns:
            DbPool._local.conns[abs_path] = duckdb.connect(abs_path)
            # Globalen Referenzzähler erhöhen (für atexit)
            with _db_pool_lock:
                if _db_pool_global.get(abs_path, 0) == 0:
                    import atexit
                    atexit.register(lambda p=abs_path: DbPool._close_all_for(p))
                _db_pool_global[abs_path] = _db_pool_global.get(abs_path, 0) + 1
        return DbPool._local.conns[abs_path]

    @staticmethod
    def _close_all_for(abs_path: str) -> None:
        """Schliesst ALLE Connections zu einer DB-Datei (fuer atexit)."""
        # Kann nur die Connections des aktuellen Threads schliessen
        if hasattr(DbPool._local, 'conns'):
            con = DbPool._local.conns.pop(abs_path, None)
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @staticmethod
    def close_all() -> None:
        """Schliesst ALLE Connections des aktuellen Threads."""
        if hasattr(DbPool._local, 'conns'):
            for abs_path in list(DbPool._local.conns.keys()):
                try:
                    DbPool._local.conns[abs_path].close()
                except Exception:
                    pass
            DbPool._local.conns = {}


class _LockedConnection:
    """Wrapper um DuckDBPyConnection (LEGACY – nur noch fuer sync_market_data & MarketDataRepository).
    Oeffnet/schliesst die Connection bei jedem Aufruf.
    """

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self._con = con

    def __getattr__(self, name):
        return getattr(self._con, name)

    def close(self):
        try:
            self._con.close()
        finally:
            pass


def db_connect(db_path: str, read_only: bool = False) -> _LockedConnection:
    """LEGACY: Oeffnet eine neue Connection (wird geschlossen nach Gebrauch).
    
    Warnung: Nicht fuer haeufige Zugriffe verwenden!
    Nutze stattdessen: DbPool.get(db_path)
    """
    con = duckdb.connect(db_path, read_only=read_only)
    return _LockedConnection(con)


# ==============================================================================
# 1) DATENBANKEN PRÜFEN, ANLEGEN & MIGRIEREN
# ==============================================================================
def check_and_init_databases() -> None:
	"""Prüft, initialisiert und migriert die Kern-Datenbanken bei Bedarf."""
	print("🔍 [1/3] Prüfe und initialisiere Ordnerstruktur und Datenbanken...")
	os.makedirs(DATA_DIR, exist_ok=True)

	con_market = DbPool.get(DB_MARKET_DATA)
	con_market.execute("""
		CREATE TABLE IF NOT EXISTS ohlcv_bars (
			symbol      VARCHAR NOT NULL,
			timeframe   VARCHAR NOT NULL,
			time        TIMESTAMPTZ NOT NULL,
			open        DOUBLE NOT NULL,
			high        DOUBLE NOT NULL,
			low         DOUBLE NOT NULL,
			close       DOUBLE NOT NULL,
			tick_volume BIGINT,
			spread      INTEGER,
			real_volume BIGINT,
			created_at  TIMESTAMP DEFAULT current_timestamp,
			PRIMARY KEY (symbol, timeframe, time)
		);
	""")

	try:
		col_type_row = con_market.execute("""
			SELECT data_type 
			FROM information_schema.columns 
			WHERE LOWER(table_name) = 'ohlcv_bars' AND LOWER(column_name) = 'time'
		""").fetchone()

		if col_type_row and col_type_row[0].upper() == "TIMESTAMP":
			print("⚠️ [MIGRATION] Konvertiere 'time' Spalte in ohlcv_bars von TIMESTAMP zu TIMESTAMPTZ...")
			con_market.execute("ALTER TABLE ohlcv_bars ALTER time TYPE TIMESTAMPTZ")
			print("✅ [MIGRATION] Konvertierung erfolgreich abgeschlossen.")
	except Exception as e:
		print(f"⚠️ [MIGRATION WARNUNG] Migration konnte nicht durchgeführt werden: {e}")

	con_analytics = DbPool.get(DB_ANALYTICS)
	con_analytics.execute("""
		CREATE TABLE IF NOT EXISTS analytics_metadata (
			created_at TIMESTAMP DEFAULT current_timestamp,
			info VARCHAR
		);
	""")

	# Phase 1: Analytics-Tabellen für Signal-Engine
	con_analytics.execute("""
		CREATE TABLE IF NOT EXISTS feature_store (
			symbol      VARCHAR NOT NULL,
			timeframe   VARCHAR NOT NULL,
			bar_time    TIMESTAMPTZ NOT NULL,
			ema_diff    DOUBLE,
			rsi_14      DOUBLE,
			atr_normalized DOUBLE,
			created_at  TIMESTAMP DEFAULT current_timestamp,
			PRIMARY KEY (symbol, timeframe, bar_time)
		);
	""")

	con_analytics.execute("""
		CREATE TABLE IF NOT EXISTS signal_definitions (
			signal_id   VARCHAR PRIMARY KEY,
			category    VARCHAR NOT NULL,
			version     VARCHAR,
			params      JSON
		);
	""")
	con_analytics.execute("""
		CREATE TABLE IF NOT EXISTS signal_sets (
			set_id          VARCHAR PRIMARY KEY,
			configuration   JSON NOT NULL,
			logic           VARCHAR NOT NULL
		);
	""")
	con_analytics.execute("""
		CREATE TABLE IF NOT EXISTS signal_results (
			event_id        VARCHAR PRIMARY KEY,
			symbol          VARCHAR NOT NULL,
			timeframe       VARCHAR NOT NULL,
			bar_time        TIMESTAMPTZ NOT NULL,
			source_id       VARCHAR NOT NULL,
			confidence      DOUBLE,
			context_type    VARCHAR NOT NULL,
			metadata_payload JSON,
			created_at      TIMESTAMP DEFAULT current_timestamp
		);
	""")

	con_app = DbPool.get(DB_APP_DATA)
	con_app.execute("""
		CREATE TABLE IF NOT EXISTS app_config (
			key VARCHAR PRIMARY KEY,
			value VARCHAR,
			updated_at TIMESTAMP DEFAULT current_timestamp
		);
	""")
	print(f"   ✅ Ordner '{DATA_DIR}/' und alle 3 DBs sind einsatzbereit.")


# ==============================================================================
# 2) MT5 VERBINDUNG PRÜFEN
# ==============================================================================
def check_mt5_connection() -> None:
	"""Prüft die MT5-Verbindung mit abgesicherter Fehlerbehandlung (lazy mt5 import)."""
	import MetaTrader5 as _mt5

	print("\n🔗 [2/3] Prüfe MT5-Verbindung...")

	with MT5_LOCK:
		if not _mt5.initialize():
			error_code = _mt5.last_error()
			try:
				_mt5.shutdown()
			except Exception:
				pass
			raise SystemExit(
				f"❌ KRITISCHER FEHLER: MT5-Verbindung fehlgeschlagen!\n"
				f"   Fehlercode: {error_code}\n"
				f"   Bitte stelle sicher, dass das MT5 Terminal geöffnet und eingeloggt ist."
			)

		account = _mt5.account_info()
		if account is None:
			try:
				_mt5.shutdown()
			except Exception:
				pass
			raise SystemExit("❌ KRITISCHER FEHLER: Im MT5-Terminal ist kein Konto eingeloggt!")

		for symbol in SYMBOLS:
			if not _mt5.symbol_select(symbol, True):
				try:
					_mt5.shutdown()
				except Exception:
					pass
				raise SystemExit(f"❌ KRITISCHER FEHLER: Symbol '{symbol}' konnte im MT5 nicht aktiviert werden.")

	print(f"   ✅ Verbunden mit Broker: {account.company} (Server: {account.server}, Login: {account.login})")


# ==============================================================================
# 3 & 4) DATEN HILFSFUNKTIONEN & IMPORT-SCHLEIFE
# ==============================================================================
def get_latest_timestamp(con: duckdb.DuckDBPyConnection, symbol: str, timeframe_str: str) -> Optional[datetime]:
	res = con.execute("""
		SELECT MAX(time) 
		FROM ohlcv_bars 
		WHERE symbol = ? AND timeframe = ?
	""", [symbol, timeframe_str]).fetchone()

	return res[0] if res and res[0] is not None else None


def sync_market_data() -> Set[Tuple[str, str]]:
	import MetaTrader5 as _mt5
	timeframes = get_timeframes()

	check_and_init_databases()
	check_mt5_connection()

	print(f"\n📥 [3/3] Starte Synchronisation für {', '.join(SYMBOLS)} über {len(timeframes)} Timeframes...")

	start_time_total = time.perf_counter()
	total_bars_downloaded = 0
	updated_pairs: Set[Tuple[str, str]] = set()

	for symbol in SYMBOLS:
		print(f"\n--- Synchronisiere {symbol} ---")
		# Connection pro Symbol öffnen/schließen, damit andere Threads (LiveTickWorker)
		# zwischendurch ebenfalls auf die DB zugreifen können
		con = db_connect(DB_MARKET_DATA)
		try:
			for tf_str, tf_mt5 in timeframes.items():
				tf_start = time.perf_counter()

				last_time = get_latest_timestamp(con, symbol, tf_str)

				with MT5_LOCK:
					if last_time is not None:
						rates = _mt5.copy_rates_from_pos(symbol, tf_mt5, 0, 5_000)
						update_type = "UPDATE"
					else:
						rates = _mt5.copy_rates_from_pos(symbol, tf_mt5, 0, 10_000_000)
						update_type = "VOLLIMPORT"

					if rates is None:
						err = _mt5.last_error()
						print(f"   [--] {tf_str:<4} | MT5 Fehler beim Abrufen der Kerzen: {err}")
						continue

				if len(rates) == 0:
					print(f"   [--] {tf_str:<4} | Keine Kerzen von MT5 empfangen.")
					continue

				df = pd.DataFrame(rates)
				df["symbol"] = symbol
				df["timeframe"] = tf_str
				df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
				df = df.drop_duplicates(subset=["time"], keep="last")

				df_to_insert = df[
					[
						"symbol",
						"timeframe",
						"time",
						"open",
						"high",
						"low",
						"close",
						"tick_volume",
						"spread",
						"real_volume",
					]
				]

				con.register("df_temp", df_to_insert)

				# NATIVE UPSERT VIA PRIMÄRSCHLÜSSEL (symbol, timeframe, time)
				con.execute("""
					INSERT OR REPLACE INTO ohlcv_bars (
						symbol, timeframe, time, open, high, low, close, tick_volume, spread, real_volume
					)
					SELECT 
						symbol, timeframe, "time", open, high, low, close, tick_volume, spread, real_volume 
					FROM df_temp
				""")

				con.unregister("df_temp")

				tf_elapsed = time.perf_counter() - tf_start
				bars_count = len(df_to_insert)
				total_bars_downloaded += bars_count

				if bars_count > 0:
					updated_pairs.add((symbol, tf_str))

				print(f"   [✅] {tf_str:<4} | {update_type:<10} | {bars_count:>8,} Kerzen verarbeitet in {tf_elapsed:.2f}s")
		finally:
			con.close()

	total_elapsed = time.perf_counter() - start_time_total

	print("\n" + "=" * 60)
	print("⏱️  ERGEBNIS & ZEITMESSUNG")
	print("=" * 60)
	print(f"Gesamtdauer Process:    {total_elapsed:.2f} Sekunden")
	print(f"Gesamtanzahl Kerzen:    {total_bars_downloaded:,}")
	print(f"Durchschnittliche Rate: {total_bars_downloaded / max(total_elapsed, 0.001):,.0f} Kerzen/Sekunde")
	print("=" * 60)
	return updated_pairs


# ==============================================================================
# HELPER: Einheitlicher Unix-Epoch-Konverter
# ==============================================================================
def _ensure_epoch(val: Any) -> int:
    """DEPRECATED: Nutze stattdessen EXTRACT('epoch' FROM time)::BIGINT in SQL.
    Diese Funktion zerstört die Zeitzone bei TIMESTAMPTZ (timetuple() verliert offset).
    Nur noch für backward-compat in Test-Dateien."""
    if isinstance(val, datetime):
        import calendar
        return calendar.timegm(val.timetuple())
    return int(val)


# ==============================================================================
# HELPER: Sicheres JSON-Parsing (DuckDB liefert str oder dict je nach Treiber)
# ==============================================================================
def _parse_json_field(val: Any) -> Any:
    """Wandelt JSON aus DuckDB in Python-Objekt um (str->dict, dict bleibt)."""
    if isinstance(val, str):
        return json.loads(val) if val else None
    return val


# ==============================================================================
# 5) REPOSITORY MIT ROBUSTER STATISTISCHER PRECISION-ERMITTLUNG
# ==============================================================================
class MarketDataRepository:
	"""Kapselt den exklusiven Lesezugriff auf die Marktdatenbank."""

	def __init__(self, db_path: str = DB_MARKET_DATA) -> None:
		self.db_path = db_path

	def fetch_historical_candles(self, symbol: str, timeframe: str, limit: int = 3000) -> Tuple[List[Dict[str, Any]], int]:
		candles: List[Dict[str, Any]] = []
		precision: int = 2

		if not os.path.exists(self.db_path):
			return candles, precision

		for attempt in range(3):
			try:
				con = db_connect(self.db_path)

				precision_query = """
					SELECT COALESCE(MAX(
						CASE 
							WHEN POSITION('.' IN CAST(ROUND(close, 5) AS VARCHAR)) > 0 
							THEN LENGTH(RTRIM(CAST(ROUND(close, 5) AS VARCHAR), '0')) - POSITION('.' IN CAST(ROUND(close, 5) AS VARCHAR))
							ELSE 0 
						END
					), 2) AS precision
					FROM (
						SELECT close 
						FROM ohlcv_bars 
						WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
						  AND close IS NOT NULL 
						LIMIT 1000
					);
				"""
				p_row = con.execute(precision_query, [symbol, timeframe]).fetchone()
				if p_row and p_row[0] is not None:
					precision = int(p_row[0])

				query = """
					SELECT EXTRACT('epoch' FROM "time")::BIGINT AS time_epoch,
					       open, high, low, close 
					FROM (
						SELECT "time", open, high, low, close 
						FROM ohlcv_bars 
						WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
						  AND "time" IS NOT NULL 
						  AND open IS NOT NULL 
						  AND high IS NOT NULL 
						  AND low IS NOT NULL 
						  AND close IS NOT NULL
						ORDER BY "time" DESC 
						LIMIT ?
					) 
					ORDER BY "time" ASC;
				"""
				rows = con.execute(query, [symbol, timeframe, limit]).fetchall()
				con.close()

				for r in rows:
					t_epoch = int(r[0])  # Bereits epoch-Integer aus DuckDB
					candles.append({
						"time": t_epoch,
						"open": float(r[1]),
						"high": float(r[2]),
						"low": float(r[3]),
						"close": float(r[4])
					})
				break

			except Exception as e:
				if attempt == 2:
					print(f"❌ [Repository Error] Fehler beim Laden von {symbol} {timeframe}: {e}")
				else:
					time.sleep(0.1)

		return candles, precision


def main() -> None:
	sync_market_data()


if __name__ == "__main__":
	main()