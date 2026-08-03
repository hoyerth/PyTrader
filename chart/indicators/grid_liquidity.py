# chart/indicators/grid_liquidity.py
"""
NEUER Grid-Indikator mit Service-Pipeline (Phase 13 Schritt 6).

Der Indikator ist jetzt der VISUELLE ADAPTER über die neuen Services
grid_lines + proximity (analytics/features/definitions/):

  * Historical-Run: Er instanziiert intern eine ServiceSetDefinition
    (grid_1 → grid_lines, prox_1 → proximity, Reihenfolge + depends_on) und
    führt sie über den ServiceSetEvaluator aus. Die Linien (Parität zu
    chart/indicators/grid.py) werden THREAD-SICHER in self._cached_grid_lines
    zwischengespeichert (atomare Zuweisung unter Lock).
  * Live-Ticks (update_live_candle): Die Pipeline wird NICHT aufgerufen. Es
    wird ausschließlich die mathematische Differenz zwischen dem Live-Tick und
    den gecachten Linien berechnet (prozentuale visit%-Semantik), um
    Live-Punkte zu setzen. Ein neuer Close (gerundete Time nicht in
    self._known_times) stößt NUR einen debounced Refresh an – nicht jeder Tick.

Das UI-Schema bleibt über das Alt-Plugin 'grid_liquidity' (PluginRegistry)
bezogen (grid_step/proximity_threshold/prox_level1-6/Farben) – es ist die
Single Source of Truth für das Prop-Fenster. Der Alt-Bestand
(analytics/features/definitions/grid_liquidity.py und chart/indicators/grid.py)
bleibt UNVERÄNDERT als Referenz-Parallelbetrieb erhalten.
"""

import threading
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from db_service import TF_SECONDS_MAP
from .base_indicator import BaseIndicator
from analytics.features.feature_builder import PluginExecutor, PluginRegistry
from analytics.features.plugins.base_plugin import PluginContext
from analytics.engine.set_evaluator import ServiceSetEvaluator


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if value is None:
        return default
    return bool(value)


def _f_in_window_around(minute_val: int, center: int, span: int) -> bool:
    """Native UTC-Zeitfenster-Logik (identisch zu grid.py / proximity_service)."""
    lower = center - span
    upper = center + span
    if lower < 0:
        return minute_val >= (60 + lower) or minute_val <= upper
    elif upper > 59:
        return minute_val >= lower or minute_val <= (upper - 60)
    else:
        return lower <= minute_val <= upper


class GridLiquidityIndicator(BaseIndicator):

    def __init__(self) -> None:
        super().__init__()
        self._symbol: Optional[str] = None
        self._timeframe: Optional[str] = None
        self._settings: Any = None
        self._executor: PluginExecutor = PluginExecutor()
        self._evaluator: ServiceSetEvaluator = ServiceSetEvaluator(self._executor)
        self._plugin_id: str = "grid_liquidity"

        # --- Thread-sicherer Cache (Phase 13 Schritt 6) ----------------------
        self._cache_lock = threading.Lock()
        self._cached_grid_lines: List[Dict[str, Any]] = []
        self._live_points: List[Dict[str, Any]] = []
        self._known_times: set = set()
        self._last_params: Dict[str, Any] = {}
        self._on_new_candle: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------ Basis
    @property
    def indicator_id(self) -> str:
        return "grid_liquidity"

    @property
    def display_name(self) -> str:
        return "Grid Liquidity (Plugin)"

    @property
    def default_params(self) -> Dict[str, Any]:
        """Standard-Parameter direkt aus dem Plugin-Schema (Single Source of Truth)."""
        return dict(PluginRegistry().get(self._plugin_id).default_params)

    @property
    def service_plugin_ids(self) -> List[str]:
        """Die Service-Plugin-IDs, die dieser Indikator intern ausführt (Schritt 6):
        grid_lines + proximity. grid_liquidity ist nur Schema-Quelle (Altbestand)
        und KEIN Service dieses Indikators."""
        return ["grid_lines", "proximity"]

    @property
    def param_options(self) -> Dict[str, List[Any]]:
        return {}

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "grid_step": "Rasterabstand",
            "proximity_threshold": "Toleranz",
            "use_time_filter": "Time Filter aktiv",
            "time_window_mins": "Time Filter Minuten (0/30)",
            "line_color": "Linien-Farbe",
            "circle_color_std": "Std-Hit-Farbe (im Fenster)",
            "circle_color_active": "Aktiv-Hit-Farbe (ausserhalb)",
            "show_lines": "Linien anzeigen",
            "show_circles": "Circles anzeigen",
            "prox_level1": "Level 1",
            "prox_level2": "Level 2",
            "prox_level3": "Level 3",
            "prox_level4": "Level 4",
            "prox_level5": "Level 5",
            "prox_level6": "Level 6",
        }

    @property
    def param_layout(self) -> Optional[List[Any]]:
        return [
            ("Raster & Toleranz", ["grid_step", "proximity_threshold"]),
            ("Time Filter", ["use_time_filter", "time_window_mins"]),
            ("Farben", ["line_color", "circle_color_std", "circle_color_active"]),
            ("Anzeige", ["show_lines", "show_circles"]),
            ("Custom Levels 1-3", ["prox_level1", "prox_level2", "prox_level3"]),
            ("Custom Levels 4-6", ["prox_level4", "prox_level5", "prox_level6"]),
        ]

    # ------------------------------------------------------------ Kontext-API
    def set_context(self, symbol: str, timeframe: str) -> None:
        self._symbol = symbol
        self._timeframe = timeframe

    def set_settings(self, settings: Any) -> None:
        """Injiziert AppSettings (Kopie) – sonst lazy aus dem StateManager."""
        self._settings = settings

    def set_new_candle_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Debounced Refresh-Callback (chart_win.refresh_chart_data). Wird bei
        einem neuen Close genau EINMAL aufgerufen (Cache-Neuaufbau)."""
        self._on_new_candle = callback

    # ------------------------------------------------------------- Cache-API
    def _set_cached_lines(self, lines: List[Dict[str, Any]]) -> None:
        """Thread-sichere atomare Zuweisung: ersetzt die Liste als GANZES
        (neue Liste, niemals in-place-Mutation) unter Lock."""
        with self._cache_lock:
            self._cached_grid_lines = list(lines)

    def _get_cached_lines(self) -> List[Dict[str, Any]]:
        """Liefert eine flache Kopie der gecachten Linien (Lock-geschützt)."""
        with self._cache_lock:
            return list(self._cached_grid_lines)

    # ------------------------------------------------- P14-03: Lesepfad (additiv)
    def read_proximity_from_feature_store(
        self,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
        db_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """P14-03 (Live-Entkopplung A.1.3): Liest fertige Proximity-Hits aus
        dem feature_store (JSON-Feld feature_data, feature_id='proximity',
        inkl. schema_version) – der GUI-Lesepfad beim Chart-Re-Render/Refresh
        OHNE synchrone Service-Pipeline (Invariante 10: definierter Fallback).

        Der Indikator führt hier KEINE Berechnungen aus; er liest ausschließlich
        vorberechnete Daten aus DuckDB. Liefert die Hit-Kreise des Proximity-
        Service ({time, price, in_window}) oder [] bei fehlenden Daten/Fehlern –
        der Aufrufer entscheidet, ob er auf die Pipeline (calculate) zurückfällt.

        Args:
            symbol: Symbol-Name
            timeframe: Timeframe
            limit: Maximale Anzahl Bars (Default 1000)
            db_path: Optionaler DB-Pfad (für Tests) – Default analytics.duckdb
        """
        if not symbol or not timeframe:
            return []
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent.parent.parent
                          / "data" / "analytics.duckdb")
        if limit is None:
            limit = 1000
        try:
            from db_service import DbPool
            con = DbPool.get(db_path)
            rows = con.execute("""
                SELECT EXTRACT('epoch' FROM bar_time)::BIGINT AS time_epoch,
                       feature_data
                FROM (
                    SELECT bar_time, feature_data
                    FROM feature_store
                    WHERE symbol = ? AND timeframe = ? AND feature_id = 'proximity'
                      AND feature_data IS NOT NULL
                    ORDER BY bar_time DESC
                    LIMIT ?
                )
                ORDER BY bar_time ASC
            """, [symbol, timeframe, limit]).fetchall()
        except Exception as e:
            print(f"WARN [GridLiquidityIndicator] feature_store-Lesepfad "
                  f"fehlgeschlagen: {e}")
            return []

        circles: List[Dict[str, Any]] = []
        for row in rows:
            time_sec = row[0]
            if time_sec is None or time_sec <= 0:
                continue
            data = row[1] or {}
            if isinstance(data, str):
                try:
                    import json as _json
                    data = _json.loads(data) or {}
                except (ValueError, TypeError):
                    data = {}
            if not data.get("is_hit"):
                continue
            # feature_data enthält levels_hit (Preise der getroffenen Levels)
            # – je Level ein Hit-Kreis (Farbe setzt der Aufrufer über das
            # in_window-Flag, wie bei der Live-Pipeline).
            in_window = bool(data.get("in_time_window"))
            for lvl in (data.get("levels_hit") or []):
                try:
                    circles.append({
                        "time": time_sec,
                        "price": float(lvl),
                        "in_window": in_window,
                        "priority": 10,
                    })
                except (TypeError, ValueError):
                    continue
        return circles

    # -------------------------------------------------------------- Berechnung
    def _get_app_settings(self) -> Any:
        if self._settings is not None:
            return self._settings
        try:
            from state_manager import StateManager
            return StateManager().get_app_settings()
        except Exception:
            return None

    @staticmethod
    def _extract_custom_levels(params: Dict[str, Any]) -> List[float]:
        """prox_level1..6 (nur > 0) ODER custom_levels (Liste/String)."""
        levels: List[float] = []
        for i in range(1, 7):
            v = params.get(f"prox_level{i}")
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0.0:
                levels.append(round(fv, 6))
        if levels:
            return levels
        raw = params.get("custom_levels")
        if isinstance(raw, (list, tuple)):
            return [round(float(x), 6) for x in raw if float(x) > 0.0]
        if isinstance(raw, str) and raw.strip():
            parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
            return [round(float(x), 6) for x in parts if float(x) > 0.0]
        return []

    def _build_set_definition(self, params: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
        """Interne ServiceSetDefinition für den Historical-Run (Schritt 6):
        grid_1 → grid_lines, prox_1 → proximity (depends_on grid_1)."""
        lookback = int(params.get("lookback") or len(df))
        if lookback < 1:
            lookback = 1
        step_size = float(params.get("step_size", params.get("grid_step", 0.5)))
        steps_around = int(params.get("steps_around", 4))
        visit_pct = float(params.get("visit_pct", params.get("proximity_threshold", 0.05)))
        time_window_mins = int(params.get("time_window_mins", 5))
        use_time_filter = _as_bool(params.get("use_time_filter"), True)
        show_lines = _as_bool(params.get("show_lines"), True)
        line_color = str(params.get("line_color") or "").strip()
        custom_levels = self._extract_custom_levels(params)

        return {
            "set_id": "grid_liquidity_internal",
            "display_name": "Grid Liquidity (intern)",
            "execution_order": ["grid_1", "prox_1"],
            "services": {
                "grid_1": {
                    "plugin_id": "grid_lines",
                    "lookback": lookback,
                    "params": {
                        "step_size": step_size,
                        "steps_around": steps_around,
                        "custom_levels": custom_levels,
                        "show_lines": show_lines,
                        "line_color": line_color,
                    },
                },
                "prox_1": {
                    "plugin_id": "proximity",
                    "lookback": lookback,
                    "depends_on": ["grid_1"],
                    "params": {
                        "visit_pct": visit_pct,
                        "time_window_mins": time_window_mins,
                        "use_time_filter": use_time_filter,
                    },
                },
            },
        }

    def _compute_known_times(self, df: pd.DataFrame) -> set:
        """Rundet alle Bar-Zeiten auf den Timeframe (gerundete Time) – dieselbe
        Erkennung wie chart_win (rounded_t nicht in _time_real_to_cont)."""
        t_sec = TF_SECONDS_MAP.get(str(self._timeframe or "").upper(), 60)
        out: set = set()
        for t in df["time"]:
            try:
                ti = int(t)
            except (TypeError, ValueError):
                continue
            out.add(ti - (ti % t_sec))
        return out

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
        """Führt die Service-Pipeline (grid_lines + proximity) für den
        Historical-Run aus, cached die Linien thread-sicher und liefert den
        Render-Payload (Parität zu grid.py)."""
        empty_result: Dict[str, Any] = {
            "lines": [],
            "hit_circles": [],
            "status_info": {"in_time_window": False, "active_hits": []},
        }
        if df is None or df.empty:
            return empty_result

        try:
            p = dict(params or {})
            self._last_params = dict(p)

            context = PluginContext(
                symbol=self._symbol or "",
                timeframe=self._timeframe or "",
                mode="chart",
                settings=self._get_app_settings(),
            )
            definition = self._build_set_definition(p, df)
            results = self._evaluator.execute_set(definition, df, context)

            # Linien kommen aus dem Namespace grid_1 (GridLinesService schreibt
            # die Linienliste dorthin) – atomare, thread-sichere Zuweisung.
            grid_lines = context.shared_state.get("grid_1") or []
            lines = list(grid_lines) if isinstance(grid_lines, list) else []

            prox_result = results.get("prox_1") or {}
            prox_crp = prox_result.get("chart_render_payload") or {}
            # Display-Layer: priority=10 (JS-Bridge-Erwartung, wie Alt-Plugin).
            # Die Services selbst bleiben Paritäts-pur (kein priority – exakt
            # wie grid.py); die Anreicherung passiert erst hier im Adapter.
            # Der Proximity-Service meldet pro Hit nur das in_window-Flag; die
            # Farbe setzt der INDIKATOR aus seinem eigenen Schema:
            #   use_time_filter und ausserhalb des Fensters → circle_color_active
            #   sonst                            → circle_color_std
            # show_circles=false (Indikator-Parameter) → keine Circles.
            circles_raw = prox_crp.get("hit_circles") or []
            if _as_bool(p.get("show_circles"), True):
                circle_std = str(p.get("circle_color_std") or "#FFEB3B")
                circle_active = str(p.get("circle_color_active") or "#E91E63")
                use_time_filter = _as_bool(p.get("use_time_filter"), True)
                circles = [
                    dict(
                        c,
                        color=(
                            circle_active
                            if (use_time_filter and not bool(c.get("in_window", True)))
                            else circle_std
                        ),
                        priority=10,
                    )
                    for c in circles_raw
                ]
            else:
                circles = []
            status = dict(prox_crp.get("status_info") or empty_result["status_info"])

            self._set_cached_lines(lines)
            self._known_times = self._compute_known_times(df)
            self._live_points = []

            return {
                "lines": lines,
                "hit_circles": circles,
                "status_info": status,
            }
        except Exception as e:
            print(f"⚠️ [GridLiquidityIndicator] Service-Pipeline fehlgeschlagen: {e}")
            return empty_result

    def update_live_candle(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Live-Tick-Verarbeitung OHNE Pipeline (Phase 13 Schritt 6):
        berechnet ausschließlich die mathematische Differenz zwischen dem
        Live-Tick und self._cached_grid_lines (prozentuale visit%-Semantik),
        um Live-Punkte zu setzen. Ein neuer Close wird über self._known_times
        erkannt und löst genau EINEN debounced Refresh aus (Cache-Neuaufbau),
        nicht bei jedem Tick.

        Args:
            candle: Live-Candle/Quote mit 'time' (epoch-Sekunden, auf den
                    Timeframe gerundet) und 'close' (bzw. 'price').

        Returns:
            Liste der Live-Punkte [{time, price, color}, ...] – zusätzlich in
            self._live_points (atomare Zuweisung).
        """
        if not candle:
            return []
        cached_lines = self._get_cached_lines()
        if not cached_lines:
            return []

        try:
            ts = int(candle.get("time", 0))
            if ts <= 0:
                return []
        except (TypeError, ValueError):
            return []

        t_sec = TF_SECONDS_MAP.get(str(self._timeframe or "").upper(), 60)
        rounded = ts - (ts % t_sec)

        # Neue Candle → NUR ein debounced Cache-Neuaufbau (nicht jeder Tick).
        if rounded not in self._known_times:
            self._known_times.add(rounded)
            if self._on_new_candle is not None:
                try:
                    self._on_new_candle()
                except Exception as e:
                    print(f"⚠️ [GridLiquidityIndicator] Cache-Neuaufbau fehlgeschlagen: {e}")

        try:
            price = float(candle.get("close", candle.get("price", 0.0)))
        except (TypeError, ValueError):
            return []

        p = self._last_params or {}
        visit_pct = float(p.get("visit_pct", p.get("proximity_threshold", 0.05)))
        use_time_filter = _as_bool(p.get("use_time_filter"), True)
        time_window_mins = int(p.get("time_window_mins", 5))
        circle_std = str(p.get("circle_color_std") or "#FFEB3B")
        circle_active = str(p.get("circle_color_active") or "#E91E63")

        row_m = datetime.fromtimestamp(rounded, tz=dt_timezone.utc).minute
        row_in_time = (
            _f_in_window_around(row_m, 0, time_window_mins)
            or _f_in_window_around(row_m, 30, time_window_mins)
        )
        color = circle_active if (use_time_filter and not row_in_time) else circle_std

        points: List[Dict[str, Any]] = []
        for line in cached_lines:
            lvl = line.get("price")
            if lvl is None:
                continue
            try:
                lvl = float(lvl)
            except (TypeError, ValueError):
                continue
            visit_min = lvl * (1.0 - visit_pct / 100.0)
            visit_max = lvl * (1.0 + visit_pct / 100.0)
            if visit_min <= price <= visit_max:
                points.append({"time": rounded, "price": lvl, "color": color,
                               "priority": 10})

        self._live_points = list(points)  # atomare Zuweisung
        return points
