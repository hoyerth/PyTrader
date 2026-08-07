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

SYMBOLS = ["SILVER", "GOLD", "BTCUSD"]

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
        """Schliesst ALLE Connections des aktuellen Threads.

        Dekrementiert dabei den globalen Referenzzaehler, damit der
        atexit-Bookkeeping-Dict (Fix 15.03, Worker-Connection-Leak) nicht
        unbegrenzt waechst. Wird u. a. von AnalyticsAsyncWorker nach jeder
        Abfrage aufgerufen (Worker-Thread gibt seine Connection frei; ein
        neuer Worker-Thread erhaelt automatisch eine frische Connection).
        """
        if hasattr(DbPool._local, 'conns'):
            for abs_path in list(DbPool._local.conns.keys()):
                try:
                    DbPool._local.conns[abs_path].close()
                except Exception:
                    pass
                with _db_pool_lock:
                    _db_pool_global[abs_path] = max(
                        0, _db_pool_global.get(abs_path, 0) - 1)
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

	# Analytics-Tabelle für Feature-/Plugin-Daten
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

	# Phase 12 (Hybrid-Schema): Additive Erweiterung des feature_store um die
	# Plugin-Architektur. feature_id identifiziert das erzeugende Plugin
	# (z.B. 'grid_lines'), plugin_version dessen Version und feature_data
	# haelt den vollstaendigen FeatureStorePayload (JSON). Bestehende Spalten
	# und Daten bleiben unangetastet.
	con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_id VARCHAR;")
	con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS plugin_version VARCHAR;")
	con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_data JSON;")

	con_app = DbPool.get(DB_APP_DATA)
	con_app.execute("""
		CREATE TABLE IF NOT EXISTS app_config (
			key VARCHAR PRIMARY KEY,
			value VARCHAR,
			updated_at TIMESTAMP DEFAULT current_timestamp
		);
	""")

	# Phase 15 (15.01): Symbol- & Favoriten-Verwaltung. broker_symbols haelt
	# die Broker-Symbole (aus mt5.symbols_get()) inkl. Favoriten-Flag und
	# dient als Fallback, wenn MT5 nicht verfuegbar ist. Standard-Defaults
	# (SILVER, GOLD, BTCUSD) werden als Favoriten vorbelegt, damit die
	# Favoriten-Dropdowns (ServiceWindow/AnalyticsWindow) nie leer starten.
	con_app.execute("""
		CREATE TABLE IF NOT EXISTS broker_symbols (
			symbol      VARCHAR PRIMARY KEY,
			path        VARCHAR,
			is_favorite BOOLEAN DEFAULT FALSE,
			updated_at  TIMESTAMP DEFAULT current_timestamp
		);
	""")
	con_app.execute("""
		INSERT INTO broker_symbols (symbol, path, is_favorite)
		VALUES ('SILVER', '', TRUE), ('GOLD', '', TRUE), ('BTCUSD', '', TRUE)
		ON CONFLICT (symbol) DO NOTHING;
	""")

	# Phase 15 (15.03): Analytics-Profile. analytics_profiles haelt benannte
	# Parametrisierungen der Analytics-UI (Option B – Explicit Save: Slider-/
	# Parametertrends setzen Dirty-Flag, Speichern erst auf [Save]). Das
	# Profil-Payload-JSON (Spalte payload) enthaelt als Pflichtfeld
	# `schema_version` (15.03-Spezifikation: 1). Additiv/idempotent –
	# bestehende Profile bleiben unangetastet.
	con_app.execute("""
		CREATE TABLE IF NOT EXISTS analytics_profiles (
			profile_id  VARCHAR PRIMARY KEY,
			name        VARCHAR NOT NULL,
			description VARCHAR,
			payload     JSON,
			is_active   BOOLEAN DEFAULT FALSE,
			created_at  TIMESTAMP DEFAULT current_timestamp,
			updated_at  TIMESTAMP DEFAULT current_timestamp
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
# HELPER: Symbol-Preision (fixer Wert je Symbol, identisch zur Preisskala)
# ==============================================================================
def get_symbol_precision(symbol: str, timeframe: str,
                         db_path: str = DB_MARKET_DATA) -> int:
    """Liefert die Preisskala-Praezision (Nachkommastellen) eines Symbols.

    Identische Query wie MarketDataRepository.fetch_historical_candles()
    (die Preisskala im Chart nutzt exakt diesen Wert) – jedoch OHNE die
    Candles zu laden. Wird fuer die Custom-Level-Eingabefelder (prox_level1..6)
    verwendet, damit die Eingabe dieselbe Dezimalanzahl wie die Preisskala hat.

    Fallback: 2 bei fehlender DB / leerer Tabelle / Fehler.
    """
    default = 2
    if not os.path.exists(db_path):
        return default
    try:
        con = DbPool.get(db_path)
        p_row = con.execute("""
            SELECT COALESCE(MAX(
                CASE
                    WHEN POSITION('.' IN CAST(ROUND(close, 5) AS VARCHAR)) > 0
                    THEN LENGTH(RTRIM(CAST(ROUND(close, 5) AS VARCHAR), '0'))
                         - POSITION('.' IN CAST(ROUND(close, 5) AS VARCHAR))
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
        """, [symbol, timeframe]).fetchone()
        if p_row and p_row[0] is not None:
            return int(p_row[0])
    except Exception:
        pass
    return default


# ==============================================================================
# 5) REPOSITORY MIT ROBUSTER STATISTISCHER PRECISION-ERMITTLUNG
# ==============================================================================
class MarketDataRepository:
	"""Kapselt den exklusiven Lesezugriff auf die Marktdatenbank."""

	def __init__(self, db_path: str = DB_MARKET_DATA) -> None:
		self.db_path = db_path

	def fetch_historical_candles(self, symbol: str, timeframe: str, limit: int = 3000,
	                             before_epoch: Optional[int] = None) -> Tuple[List[Dict[str, Any]], int]:
		"""Liest OHLCV-Kerzen aus der Marktdatenbank (aufsteigend sortiert).

		Phase 16.07 (Two-Tier Caching, D4): Additiver Parameter `before_epoch`.
		Ist er gesetzt, werden ausschliesslich KERZEN GELADEN, DIE ÄLTER ALS
		diese Wanduhr-Epoch sind (WHERE "time" < to_timestamp(?)) – das
		Chunk-Nachladen des `ChartDataBuffer` (Tier 2 -> DuckDB) nutzt genau
		diesen Pfad, um den naechsten Block alter Geschichte vorzuladen.
		Ohne `before_epoch` ist das Verhalten unveraendert (letzte `limit`
		Kerzen, Abwaertskompatibilitaet).
		"""
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

				# Phase 16.07: before_epoch filtert additiv auf ältere Kerzen
				# (Wanduhr-Epoch; "time" ist TIMESTAMPTZ, daher to_timestamp-
				# Vergleich). Die WHERE-Bedingung wird nur bei gesetztem
				# before_epoch ergänzt (Abwaertskompatibilität).
				older_filter = ""
				params: List[Any] = [symbol, timeframe]
				if before_epoch is not None:
					older_filter = ' AND "time" < to_timestamp(?)'
					params.append(int(before_epoch))
				params.append(limit)

				query = """
					SELECT EXTRACT('epoch' FROM "time")::BIGINT AS time_epoch,
					       open, high, low, close, tick_volume 
					FROM (
						SELECT "time", open, high, low, close, tick_volume 
						FROM ohlcv_bars 
						WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
						  AND "time" IS NOT NULL 
						  AND open IS NOT NULL 
						  AND high IS NOT NULL 
						  AND low IS NOT NULL 
						  AND close IS NOT NULL
						""" + older_filter + """
						ORDER BY "time" DESC 
						LIMIT ?
					) 
					ORDER BY "time" ASC;
				"""
				rows = con.execute(query, params).fetchall()
				con.close()

				for r in rows:
					t_epoch = int(r[0])  # Bereits epoch-Integer aus DuckDB
					# P16.05 VWMA-Fix (P-D4): tick_volume wird mitgeliefert.
					# Entscheidung F3: NaN/None -> 0, Candle bleibt gueltig
					# (kein WHERE-Filter auf tick_volume, damit Candles mit
					# NULL-Volumen nicht wegfallen).
					vol_raw = r[5]
					candles.append({
						"time": t_epoch,
						"open": float(r[1]),
						"high": float(r[2]),
						"low": float(r[3]),
						"close": float(r[4]),
						"tick_volume": float(vol_raw) if vol_raw is not None else 0.0
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