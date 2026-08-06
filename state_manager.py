# state_manager.py

"""
state_manager.py - Persistence Manager with Symbol/TF Reset Support, Robust Schema Migration & Type Validation
"""

import json
import os
from typing import Any, Dict, List, Optional
import duckdb

from db_service import _parse_json_field, DbPool
from config.base_state_model import AbstractStateModel
from config.app_settings import AppSettings
# Phase 15.04: Instanz-/Fenster-SQL-Zugriffe sind in das
# WindowStateRepository ausgelagert (window_state_repository.py). Der
# StateManager ist seitdem eine additive Fassade – alle Bestands-Methoden
# bleiben mit identischen Signaturen erhalten und delegieren intern.
from window_state_repository import WindowStateRepository

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DB_PATH = os.path.join(BASE_DIR, "data", "app_data.duckdb")

KEY_APP_SETTINGS = "app_settings"


class StateManager:

    def __init__(self, db_path: str = APP_DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()
        # Phase 15.04: Fassaden-Delegation an das WindowStateRepository.
        # Die DB-Pfad-Aufloesung verbleibt beim StateManager und wird an das
        # Repository durchgereicht (Test-Isolation: Temp-DBs bleiben getrennt).
        self._window_repo = WindowStateRepository(db_path)

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        return DbPool.get(self.db_path)

    def _init_db(self) -> None:
        """Initialisiert die Tabellenstrukturen und f\u00fchrt eine saubere Schema-Migration durch."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = self._get_connection()
        con.execute("""
            CREATE TABLE IF NOT EXISTS window_instances (
                instance_id VARCHAR PRIMARY KEY,
                preset_id VARCHAR,
                window_title VARCHAR,
                pos_x INTEGER,
                pos_y INTEGER,
                width INTEGER,
                height INTEGER,
                is_maximized BOOLEAN DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS instance_states (
                instance_id VARCHAR PRIMARY KEY,
                symbol VARCHAR NOT NULL,
                timeframe VARCHAR NOT NULL,
                visible_range_from BIGINT,
                visible_range_to BIGINT,
                visible_price_from DOUBLE,
                visible_price_to DOUBLE,
                indicators_state JSON,
                measurement_state JSON,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS symbol_tf_states (
                symbol VARCHAR NOT NULL,
                timeframe VARCHAR NOT NULL,
                visible_range_from BIGINT,
                visible_range_to BIGINT,
                visible_price_from DOUBLE,
                visible_price_to DOUBLE,
                indicators_state JSON,
                measurement_state JSON,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, timeframe)
            );

            CREATE TABLE IF NOT EXISTS indicator_presets (
                indicator_id VARCHAR NOT NULL,
                preset_name VARCHAR NOT NULL,
                params JSON NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (indicator_id, preset_name)
            );

            CREATE TABLE IF NOT EXISTS global_settings (
                key VARCHAR PRIMARY KEY,
                value JSON NOT NULL
            );
        """)

        # Phase 12 (Hybrid-Schema): Additive Erweiterung der indicator_presets
        # um die Plugin-Verknuepfung. plugin_id verknuepft ein Preset mit einem
        # Plugin (z.B. 'grid_lines'), version fuehrt die Plugin-Version und
        # is_active_batch markiert Presets, die von den Batch-Services
        # (HistoricalScanner/LiveAnalyzer) ueber den PluginExecutor aktiv
        # verarbeitet werden. Bestehende Presets und Daten bleiben unangetastet.
        con.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS plugin_id VARCHAR;")
        con.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS version VARCHAR DEFAULT '1.0.0';")
        con.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS is_active_batch BOOLEAN DEFAULT FALSE;")

        # Phase 15 (U15-B4): Alt-Indikator 'grid' (chart/indicators/grid.py)
        # wurde am 04.08.2026 entfernt. Persistierte Presets mit
        # indicator_id='grid' werden idempotent bereinigt (einmalig pro
        # App-Start, additiv – bestehende 'ind_fixed_grid_proximity'-Presets
        # bleiben unangetastet). Der Legacy-Pfad in _resolve_indicator_params()
        # bleibt fuer Abwaertskompatibilitaet bestehen.
        con.execute("DELETE FROM indicator_presets WHERE indicator_id = 'grid'")

        # Phase 16 (06.08.2026): Rollen- und Namens-Klarheit – der Indikator
        # 'grid_liquidity' wurde in 'ind_fixed_grid_proximity' umbenannt
        # (indicator_id/indicators_state-Key). Persistierte Alt-Referenzen
        # (indicator_presets.indicator_id sowie indicators_state-JSON in
        # instance_states/symbol_tf_states) werden idempotent migriert.
        _legacy_ind_id = "grid_liquidity"
        _new_ind_id = "ind_fixed_grid_proximity"
        try:
            con.execute(
                "UPDATE indicator_presets SET indicator_id = ? WHERE indicator_id = ?",
                [_new_ind_id, _legacy_ind_id])
            # indicators_state-JSON: Legacy-Key auf neuen Indikator-Key mappen.
            for _row in con.execute(
                    "SELECT instance_id, indicators_state FROM instance_states").fetchall():
                _rid, _raw = _row[0], _row[1]
                if _raw is None:
                    continue
                _data = _parse_json_field(_raw) if isinstance(_raw, str) else _raw
                if not isinstance(_data, dict) or _legacy_ind_id not in _data:
                    continue
                _data.setdefault(_new_ind_id, _data.pop(_legacy_ind_id))
                con.execute(
                    "UPDATE instance_states SET indicators_state = ? WHERE instance_id = ?",
                    [json.dumps(_data), _rid])
            for _row in con.execute(
                    "SELECT symbol, timeframe, indicators_state FROM symbol_tf_states").fetchall():
                _sym, _tf, _raw = _row[0], _row[1], _row[2]
                if _raw is None:
                    continue
                _data = _parse_json_field(_raw) if isinstance(_raw, str) else _raw
                if not isinstance(_data, dict) or _legacy_ind_id not in _data:
                    continue
                _data.setdefault(_new_ind_id, _data.pop(_legacy_ind_id))
                con.execute(
                    "UPDATE symbol_tf_states SET indicators_state = ? WHERE symbol = ? AND timeframe = ?",
                    [json.dumps(_data), _sym, _tf])
        except Exception as e:
            print(f"WARN [StateManager] Phase-16-Migration (grid_liquidity -> "
                  f"ind_fixed_grid_proximity) fehlgeschlagen: {e}")

        # Explicit Column Check via information_schema
        tables_to_migrate = ["instance_states", "symbol_tf_states"]
        columns_to_check = ["indicators_state", "measurement_state"]

        for table in tables_to_migrate:
            existing_cols = con.execute(f"""
                SELECT LOWER(column_name)
                FROM information_schema.columns
                WHERE LOWER(table_name) = '{table.lower()}'
            """).fetchall()
            existing_col_names = [col[0] for col in existing_cols]

            for col_name in columns_to_check:
                if col_name.lower() not in existing_col_names:
                    try:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} JSON")
                        print(f"[MIGRATION] Spalte '{col_name}' (JSON) zur Tabelle '{table}' hinzugefuegt.")
                    except Exception as e:
                        print(f"[MIGRATION WARNUNG] Spalte '{col_name}' konnte nicht hinzugefuegt werden: {e}")

    def get_next_instance_id(self) -> str:
        # Phase 15.04: Delegation an das WindowStateRepository.
        return self._window_repo.get_next_instance_id()

    def delete_instance(self, instance_id: str) -> None:
        # Phase 15.04: Delegation an das WindowStateRepository.
        self._window_repo.delete_instance(instance_id)

    def delete_symbol_tf_state(self, symbol: str, timeframe: str) -> None:
        # Phase 15.04: Delegation an das WindowStateRepository.
        self._window_repo.delete_symbol_tf_state(symbol, timeframe)

    def save_instance_state(
        self,
        instance_id: str,
        symbol: str,
        timeframe: str,
        visible_range_from: Optional[int] = None,
        visible_range_to: Optional[int] = None,
        visible_price_from: Optional[float] = None,
        visible_price_to: Optional[float] = None,
        indicators_state: Optional[Dict[str, Any]] = None,
        measurement_state: Optional[Dict[str, Any]] = None
    ) -> None:
        # Phase 15.04: Delegation an das WindowStateRepository.
        self._window_repo.save_instance_state(
            instance_id, symbol, timeframe,
            visible_range_from, visible_range_to,
            visible_price_from, visible_price_to,
            indicators_state, measurement_state,
        )

    def save_symbol_tf_state(
        self,
        symbol: str,
        timeframe: str,
        visible_range_from: Optional[int] = None,
        visible_range_to: Optional[int] = None,
        visible_price_from: Optional[float] = None,
        visible_price_to: Optional[float] = None,
        indicators_state: Optional[Dict[str, Any]] = None,
        measurement_state: Optional[Dict[str, Any]] = None
    ) -> None:
        # Phase 15.04: Delegation an das WindowStateRepository.
        self._window_repo.save_symbol_tf_state(
            symbol, timeframe,
            visible_range_from, visible_range_to,
            visible_price_from, visible_price_to,
            indicators_state, measurement_state,
        )

    def get_symbol_tf_state(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        # Phase 15.04: Delegation an das WindowStateRepository.
        return self._window_repo.get_symbol_tf_state(symbol, timeframe)

    def save_window_geometry(
        self,
        instance_id: str,
        x: int,
        y: int,
        width: int,
        height: int,
        is_maximized: bool,
        preset_id: Optional[str] = None
    ) -> None:
        # Phase 15.04: Delegation an das WindowStateRepository.
        self._window_repo.save_window_geometry(
            instance_id, x, y, width, height, is_maximized, preset_id,
        )

    def get_window_geometry(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Liest die gespeicherte Fenstergeometrie einer spezifischen Instanz aus.

        Phase 15.04: Delegation an das WindowStateRepository (Bestandsverhalten
        exakt reproduziert).
        """
        return self._window_repo.get_window_geometry(instance_id)

    def load_all_instances(self) -> List[Dict[str, Any]]:
        # Phase 15.04: Delegation an das WindowStateRepository (pandas-.df()-
        # Leseart + String-Normalisierung exakt wie im Bestand).
        return self._window_repo.load_all_instances()

    def get_indicator_preset(self, indicator_id: str, preset_name: str) -> Optional[Dict[str, Any]]:
        """Liest die Parametervalue eines Indikator-Presets (RÜCKWÄRTSKOMPATIBEL:
        gibt direkt das params-Dict zurück, wie vom bestehenden indicator_dialog erwartet)."""
        con = self._get_connection()
        res = con.execute(
            "SELECT params FROM indicator_presets WHERE indicator_id = ? AND preset_name = ?",
            [indicator_id, preset_name]
        ).fetchone()
        if res and res[0]:
            return _parse_json_field(res[0])
        return None

    def get_indicator_preset_meta(self, indicator_id: str, preset_name: str) -> Optional[Dict[str, Any]]:
        """Liest ein Indikator-Preset INKL. Plugin-Verknüpfung (Phase 12 Hybrid-Schema).
        Rückgabe: {"params": ..., "plugin_id": ..., "version": ..., "is_active_batch": ...}."""
        con = self._get_connection()
        res = con.execute(
            "SELECT params, plugin_id, version, is_active_batch FROM indicator_presets WHERE indicator_id = ? AND preset_name = ?",
            [indicator_id, preset_name]
        ).fetchone()
        if res and res[0]:
            params = _parse_json_field(res[0])
            data = {"params": params}
            # Neue Hybrid-Schema-Spalten (können NULL sein bei Alt-Presets)
            if len(res) > 1 and res[1] is not None:
                data["plugin_id"] = str(res[1])
            if len(res) > 2 and res[2] is not None:
                data["version"] = str(res[2])
            if len(res) > 3 and res[3] is not None:
                data["is_active_batch"] = bool(res[3])
            return data
        return None

    def save_indicator_preset(
        self,
        indicator_id: str,
        preset_name: str,
        params: Dict[str, Any],
        plugin_id: Optional[str] = None,
        version: Optional[str] = None,
        is_active_batch: bool = False,
    ) -> None:
        """Speichert ein Indikator-Preset. Unterstützt zusätzlich plugin_id,
        version und is_active_batch (Phase 12 Hybrid-Schema)."""
        con = self._get_connection()
        con.execute("""
            INSERT INTO indicator_presets (indicator_id, preset_name, params, plugin_id, version, is_active_batch)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (indicator_id, preset_name) DO UPDATE SET
                params = EXCLUDED.params,
                plugin_id = EXCLUDED.plugin_id,
                version = EXCLUDED.version,
                is_active_batch = EXCLUDED.is_active_batch;
        """, [
            indicator_id, preset_name, json.dumps(params),
            plugin_id, version, bool(is_active_batch),
        ])

    def delete_indicator_preset(self, indicator_id: str, preset_name: str) -> None:
        con = self._get_connection()
        con.execute(
            "DELETE FROM indicator_presets WHERE indicator_id = ? AND preset_name = ?",
            [indicator_id, preset_name]
        )

    def list_indicator_presets(self, indicator_id: str) -> List[str]:
        con = self._get_connection()
        res = con.execute(
            "SELECT preset_name FROM indicator_presets WHERE indicator_id = ? ORDER BY preset_name ASC",
            [indicator_id]
        ).fetchall()
        presets = [r[0] for r in res]
        if "Default" not in presets:
            presets.insert(0, "Default")
        return presets

    def list_active_batch_presets(self) -> List[Dict[str, Any]]:
        """Liefert alle Batch-aktiven Plugin-Presets (Phase 12 Hybrid-Schema).

        Selektiert aus indicator_presets nur Presets mit is_active_batch = TRUE
        und gesetzter plugin_id. Diese steuern den Plugin-Modus der
        Batch-Services (HistoricalScanner / LiveAnalyzer) über den
        PluginExecutor – der Alt-Pfad bleibt davon unberührt.

        Rückgabe: Liste von {"indicator_id", "preset_name", "plugin_id",
        "version", "params"}.
        """
        con = self._get_connection()
        res = con.execute("""
            SELECT indicator_id, preset_name, params, plugin_id, version, is_active_batch
            FROM indicator_presets
            WHERE is_active_batch = TRUE AND plugin_id IS NOT NULL
            ORDER BY preset_name ASC
        """).fetchall()
        presets: List[Dict[str, Any]] = []
        for indicator_id, preset_name, params_json, plugin_id, version, is_active in res:
            presets.append({
                "indicator_id": indicator_id,
                "preset_name": preset_name,
                "plugin_id": plugin_id,
                "version": version,
                "params": _parse_json_field(params_json) if params_json else {},
            })
        return presets

    def get_app_settings(self) -> AppSettings:
        """L\u00e4dt AppSettings aus der DB oder gibt Defaults zur\u00fcck."""
        con = self._get_connection()
        row = con.execute(
            "SELECT value FROM global_settings WHERE key = ?",
            [KEY_APP_SETTINGS]
        ).fetchone()
        if row and row[0]:
            raw = row[0]
            data = _parse_json_field(raw)
            return AppSettings.from_dict(data)
        return AppSettings()

    def save_app_settings(self, settings: AppSettings) -> None:
        """Speichert AppSettings in der DB."""
        con = self._get_connection()
        con.execute("""
            INSERT INTO global_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, [KEY_APP_SETTINGS, json.dumps(settings.to_dict())])

    # =========================================================================
    # Dialog-Geometrie (nicht-modale Dialoge, z. B. IndicatorSettingsDialog)
    # -------------------------------------------------------------------------
    # Speichert Position/Groesse eines nicht-modalen Dialogs in global_settings,
    # damit er beim erneuten Oeffnen an der letzten Position erscheint.
    # dialog_key: z. B. "indicator_settings" (gilt generisch fuer alle Indikatoren)
    # =========================================================================
    def save_dialog_geometry(self, dialog_key: str, x: int, y: int, width: int, height: int) -> None:
        con = self._get_connection()
        key = f"dialog_geometry_{dialog_key}"
        con.execute("""
            INSERT INTO global_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, [key, json.dumps({"pos_x": x, "pos_y": y, "width": width, "height": height})])

    def get_dialog_geometry(self, dialog_key: str) -> Optional[Dict[str, Any]]:
        """Liest die gespeicherte Dialog-Geometrie eines dialog_key aus (oder None)."""
        con = self._get_connection()
        key = f"dialog_geometry_{dialog_key}"
        row = con.execute("SELECT value FROM global_settings WHERE key = ?", [key]).fetchone()
        if row and row[0]:
            data = _parse_json_field(row[0])
            if isinstance(data, dict):
                return data
        return None
