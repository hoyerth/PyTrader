# db/schema_initializer.py
"""
db/schema_initializer.py - Pruefen, Anlegen & Migrieren der Kern-Datenbanken.

Ausgelagert aus db_service.py im Rahmen von 18.01.02 (E3): `check_and_init_databases`
legt die drei DuckDB-Dateien (market_data, analytics, app_data) mit ihrem
Schema idempotent an und fuehrt additive Migrationen aus. Importiert die
Basis-Schicht db/db_pool (E4); kein MT5-Import (Lazy-Import-Prinzip).
"""

import os

from db.db_pool import DATA_DIR, DB_ANALYTICS, DB_APP_DATA, DB_MARKET_DATA, DbPool


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
    # 17.01 (E-1, 07.08.2026): 4-Spalten-PK (symbol, timeframe, bar_time,
    # feature_id) – erlaubt die konfliktfreie Speicherung MEHRERER Services auf
    # derselben Kerze (feature_id identifiziert das erzeugende Plugin, Default
    # 'native' fuer den klassischen Feature-Builder-Pfad). Bei bestehenden DBs
    # ist CREATE TABLE IF NOT EXISTS ein No-op; die Migration existierender
    # Tabellen erfolgt ueber test/migrate_pk.py (Table-Rewrite + RENAME, da
    # DuckDB 1.5.5 kein DROP PRIMARY KEY unterstuetzt).
    con_analytics.execute("""
        CREATE TABLE IF NOT EXISTS feature_store (
            symbol      VARCHAR NOT NULL,
            timeframe   VARCHAR NOT NULL,
            bar_time    TIMESTAMPTZ NOT NULL,
            ema_diff    DOUBLE,
            rsi_14      DOUBLE,
            atr_normalized DOUBLE,
            created_at  TIMESTAMP DEFAULT current_timestamp,
            feature_id  VARCHAR NOT NULL DEFAULT 'native',
            plugin_version VARCHAR,
            feature_data JSON,
            PRIMARY KEY (symbol, timeframe, bar_time, feature_id)
        );
    """)

    # Phase 12 (Hybrid-Schema): Additive Erweiterung des feature_store um die
    # Plugin-Architektur. feature_id identifiziert das erzeugende Plugin
    # (z.B. 'srv_grid_lines'), plugin_version dessen Version und feature_data
    # haelt den vollstaendigen FeatureStorePayload (JSON). Bestehende Spalten
    # und Daten bleiben unangetastet.
    con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_id VARCHAR;")
    con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS plugin_version VARCHAR;")
    con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_data JSON;")
    # Bugfix 07.08.2026 (Phase 17 Bugfix-Runde 2): Der Spalten-DEFAULT von
    # created_at wurde durch die PK-Migration (17.01 E-1, test/migrate_pk.py –
    # Table-Rewrite + RENAME) entfernt. Seitdem bleiben NEUE feature_store-Rows
    # ohne explizites created_at NULL und das 'Datum der letzten Ausfuehrung'
    # (MasterTree, MAX(created_at) je feature_id) zeigt '--.--.--'. Der DEFAULT
    # wird hier idempotent wiederhergestellt (No-op bei korrekter DB).
    try:
        con_analytics.execute(
            "ALTER TABLE feature_store ALTER created_at "
            "SET DEFAULT current_timestamp")
    except Exception as e:
        print(f"⚠️ [MIGRATION WARNUNG] created_at-Default des feature_store "
              f"konnte nicht wiederhergestellt werden: {e}")

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
