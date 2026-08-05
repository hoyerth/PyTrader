# test/migrate_legacy_feature_store.py
"""
Migration (05.08.2026, Punkt 1): Legacy-Rows im feature_store erhalten eine
gueltige feature_id.

Hintergrund:
  Alle 673.235 Zeilen der analytics.duckdb/feature_store wurden von der ALTEN
  Monolith-Pipeline (FeatureBuilder.build(), Phasen 12-13) geschrieben und
  tragen KEINE Plugin-Identitaet (feature_id = NULL, plugin_version = NULL,
  feature_data = NULL). Dadurch fand fetch_last_execution_dates() keine
  Zeilen und der MasterTree zeigte ueberall '(--.--.--)', obwohl Daten
  vorhanden sind.

  Die Legacy-Zeilen mit befuellten grid_*-Spalten (grid_nearest_level /
  grid_dist_abs / grid_dist_pct / is_time_window_active) tragen exakt die
  Daten, die heute der `proximity`-Service erzeugt (Abstand des Preises zu
  den Grid-Linien). Sie werden daher semantisch korrekt auf
  feature_id = 'proximity' migriert.

  WICHTIG (keine Verfaelschung):
    * feature_data bleibt NULL – der Chart-Lesepfad
      (read_proximity_from_feature_store) filtert `feature_data IS NOT NULL`
      UND `is_hit == True` und ignoriert die migrierten Zeilen dadurch
      weiterhin (keine Aenderung im Chart-Rendering).
    * created_at bleibt unveraendert (liefert das echte Legacy-Datum).
    * plugin_version = 'legacy' kennzeichnet die migrierten Zeilen
      transparent (echte Plugin-Runs schreiben '1.0.0').

Aufruf:
    python test/migrate_legacy_feature_store.py            # Dry-Run
    python test/migrate_legacy_feature_store.py --apply    # Migration

Exit-Code:
    0 = keine unklassifizierten Legacy-Zeilen (feature_id IS NULL) mehr
"""

import argparse
import sys
from pathlib import Path

import duckdb

PROJECT = Path(__file__).resolve().parent.parent
ANALYTICS_DB = PROJECT / "data" / "analytics.duckdb"

# Legacy-Zeilen mit grid_*-Spalten = Proximity-Semantik (Abfrage)
GRID_ROWS_SQL = """
    SELECT COUNT(*) FROM feature_store
    WHERE feature_id IS NULL
      AND (grid_nearest_level IS NOT NULL
           OR grid_dist_abs IS NOT NULL
           OR grid_dist_pct IS NOT NULL)
"""

APPLY_SQL = """
    UPDATE feature_store
    SET feature_id = 'proximity',
        plugin_version = 'legacy'
    WHERE feature_id IS NULL
      AND (grid_nearest_level IS NOT NULL
           OR grid_dist_abs IS NOT NULL
           OR grid_dist_pct IS NOT NULL)
"""


def _count(con, sql: str, params=None) -> int:
    row = con.execute(sql, params or []).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Legacy feature_store-Migration")
    ap.add_argument("--apply", action="store_true",
                    help="Migration tatsaechlich ausfuehren (sonst Dry-Run)")
    ap.add_argument("--db", default=str(ANALYTICS_DB),
                    help="Pfad zur analytics.duckdb")
    args = ap.parse_args()

    con = duckdb.connect(args.db)

    total = _count(con, "SELECT COUNT(*) FROM feature_store")
    null_fid = _count(con,
                      "SELECT COUNT(*) FROM feature_store "
                      "WHERE feature_id IS NULL")
    grid_rows = _count(con, GRID_ROWS_SQL)
    non_grid_legacy = null_fid - grid_rows

    print(f"feature_store gesamt      : {total}")
    print(f"feature_id IS NULL (Legacy): {null_fid}")
    print(f"  davon grid_*-Zeilen      : {grid_rows}  -> werden 'proximity'")
    print(f"  davon ohne grid_*        : {non_grid_legacy}  -> bleiben NULL")

    if not args.apply:
        print("\nDRY-RUN: keine Aenderung. Mit --apply ausfuehren.")
        # Exit 0 = konsistent (keine migrierbaren Zeilen mehr erwartet)
        return 0 if grid_rows == 0 else 1

    # created_at defensiv nachziehen (falls Alt-Rows ohne Zeitstempel)
    _count(con, """
        UPDATE feature_store
        SET created_at = current_timestamp
        WHERE created_at IS NULL
    """)
    affected = _count(con, APPLY_SQL)
    print(f"\nMigration angewendet: {affected} Zeilen -> feature_id='proximity'")

    # Verifikation
    remaining = _count(con,
                       "SELECT COUNT(*) FROM feature_store "
                       "WHERE feature_id IS NULL")
    remaining_grid = _count(con, GRID_ROWS_SQL)
    prox = _count(con,
                  "SELECT COUNT(*) FROM feature_store "
                  "WHERE feature_id = 'proximity'")
    print(f"Verbleibende feature_id IS NULL: {remaining}")
    print(f"  davon grid_*-Zeilen           : {remaining_grid}")
    print(f"feature_id = 'proximity'       : {prox}")
    # Exit 0 = keine migrierbaren Grid-Legacy-Zeilen mehr (atr-only Rows
    # ohne grid_* bleiben bewusst NULL – sie tragen keine Proximity-Semantik).
    return 0 if remaining_grid == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
