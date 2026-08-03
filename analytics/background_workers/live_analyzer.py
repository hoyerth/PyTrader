# analytics/background_workers/live_analyzer.py
"""
Live Analyzer – QThread-Worker für die Live-Analyse bei Bar-Close.
Empfängt neue Ticks/Bar-Events, berechnet Features, evaluiert Signal-Sets
und schreibt Ergebnisse in signal_results (context_type='live_stream').

Architektur (Phase 6 Roadmap):
    Tick -> Bar-Close -> Feature Store -> Signal-Engine -> signal_results -> UI-Overlay

Phase 13 Schritt 7.B (Rückbau Alt-Signal-Mechanik): Der Alt-Pfad in
signal_results ist DEAKTIVIERT – set_config['signals'] ist leer, daher
liefern _fill_gaps/_process_new_bars/analyze_single_bar früh zurück und
es finden KEINE signal_results-Writes mehr statt. Marker/Statistik lesen
den feature_store; die Tabelle signal_results bleibt nur als Referenz.
"""

import json
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd
from PySide6.QtCore import QThread, Signal

from analytics.engine.set_evaluator import SetEvaluator
from analytics.features.feature_builder import (
    FeatureBuilder,
    PluginExecutor,
    PluginExecutionError,
    prepare_plugin_df,
)
from analytics.features.plugins.base_plugin import PluginContext
from analytics.signals.heuristics.ema_trend import EMATrendSignal
from analytics.signals.heuristics.atr_filter import ATRFilterSignal
from analytics.signals.experimental.alternating_arrow_signal import AlternatingArrowSignal
from analytics.signals.composite.grid_proximity_signal import GridProximitySignal
from db_service import DbPool
from state_manager import StateManager

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")
DB_MARKET = str(BASE_DIR / "data" / "market_data.duckdb")


class LiveAnalyzer(QThread):
    """
    Analysiert eine geschlossene Live-Kerze (Bar-Close Event):
    1. Features berechnen und in feature_store schreiben
    2. Signal-Set evaluieren
    3. Ergebnisse in signal_results schreiben (context_type='live_stream')
    4. Signal ans UI emittieren
    """

    # Emittiert, wenn ein neues Live-Signal erkannt wurde
    new_live_signal = Signal(str, str, int, float, str)
    # (symbol, timeframe, bar_time, confidence, source_id)

    log_message = Signal(str)

    def __init__(
        self,
        symbol: str = "SILVER",
        timeframe: str = "M1",
        lookback_bars: int = 500,
        parent=None,
    ):
        super().__init__(parent)
        self.symbol = symbol
        self.timeframe = timeframe
        self.lookback_bars = lookback_bars
        self._running = True

        # Feature Builder
        self.feature_builder = FeatureBuilder()

        # Phase 12: Zentraler PluginExecutor für den Plugin-Modus (aktive
        # Batch-Presets mit live_op = True). Dieselbe Instanz, die auch der
        # HistoricalScanner nutzt – der Alt-Pfad bleibt unverändert.
        self.plugin_executor = PluginExecutor()
        self._state_mgr = StateManager()

        # P14-03 (Live-Entkopplung A.1.2): Persistenter EvaluationContext-
        # Buffer über alle Polls hinweg. Der LiveAnalyzer evaluiert geschlossene
        # Kerzen mit stark verkürztem Lookback (1-2 Bars) GEGEN dieses im RAM
        # gepufferte Raster – kein voller Pipeline-Neuaufbau pro Poll.
        self._live_shared_state: Dict[str, Any] = {}
        self._live_context = PluginContext(
            symbol=self.symbol,
            timeframe=self.timeframe,
            mode="live",
            shared_state=self._live_shared_state,
        )

        # Verfügbare Signale (kann über set_active_signals() erweitert werden)
        self.signals: Dict[str, Any] = {
            "alternating_arrow_v1": AlternatingArrowSignal(),
            "ema_trend_v1": EMATrendSignal(),
            "atr_filter_v1": ATRFilterSignal(),
            "grid_proximity_v1": GridProximitySignal(),
        }
        self.evaluator = SetEvaluator(self.signals)

        # Aktive Set-Konfiguration (Testsignale DEAKTIVIERT – Signal-Liste leer).
        # TODO: Automatische Testsignale (alternating_arrow_v1) spaeter hier reaktivieren.
        self.set_config: Dict[str, Any] = {
            "signals": [],
            "threshold": 0.5,
        }

        # Letzte verarbeitete Bar-Time (für Duplikatserkennung)
        self._last_processed_bar_time: Optional[int] = None

    def stop(self) -> None:
        self._running = False

    def set_active_signals(self, signals: Dict[str, Any]) -> None:
        """Ersetzt die Signal-Registry (z. B. um ML-Modelle zu ergänzen)."""
        self.signals = signals
        self.evaluator = SetEvaluator(self.signals)

    def set_set_config(self, config: Dict[str, Any]) -> None:
        """Setzt die aktive Set-Konfiguration."""
        self.set_config = config

    def get_required_features(self) -> List[str]:
        """
        Sammelt alle required_features aus den im aktiven set_config
        verwendeten Signalen.
        """
        required = set()
        for cfg in self.set_config.get("signals", []):
            sid = cfg["id"]
            sig = self.signals.get(sid)
            if sig is not None:
                for feat in sig.required_features:
                    required.add(feat)
        # Fallback: immer ema_diff + atr_normalized fuer Basis-Funktion
        if not required:
            required = {"ema_diff", "atr_normalized"}
        return list(required)

    def _get_feature_params(self) -> Dict[str, Dict[str, Any]]:
        """
        Gibt optimierte Parameter fuer den FeatureBuilder zurueck,
        basierend auf den benoetigten Features (Basis: ema_diff, atr_normalized).
        """
        feats = self.get_required_features()
        params = {}
        if "ema_diff" in feats:
            params["ema_diff"] = {"fast_period": 12, "slow_period": 26}
        if "atr_normalized" in feats:
            params["atr_normalized"] = {"period": 14}
        # Grid-Spalten (grid_dist_pct / grid_nearest_level / grid_dist_abs /
        # is_time_window_active) werden vom Modul 'grid_levels' erzeugt.
        if any(f in feats for f in (
            "grid_dist_pct", "grid_nearest_level", "grid_dist_abs", "is_time_window_active"
        )):
            params["grid_levels"] = {
                "step_size": 0.5,
                "steps_around": 4,
                "custom_levels": [],
                "time_window_mins": 5,
                "use_time_filter": True,
            }
        return params

    def run(self) -> None:
        """
        Hauptschleife: Wartet auf Bar-Close-Events (Polling).
        Fuehrt vor dem Live-Betrieb einen einmaligen Auto-Fill durch,
        um Luecken seit dem letzten Signal in der DB zu schliessen.
        """
        self.log_message.emit(
            f"LiveAnalyzer gestartet: {self.symbol} {self.timeframe}, "
            f"lookback={self.lookback_bars}"
        )

        # Auto-Fill: Luecken schliessen bevor Live-Betrieb startet
        self._fill_gaps()

        while self._running:
            try:
                self._process_new_bars()
                self._process_plugin_bars()
            except Exception as e:
                self.log_message.emit(f"❌ LiveAnalyzer Fehler: {e}")

            # Polling-Intervall: 1 Sekunde (fuer M1 ausreichend)
            self.msleep(1000)

        self.log_message.emit("LiveAnalyzer gestoppt.")

    def _get_active_live_plugins(self) -> List[Dict[str, Any]]:
        """Liefert aktive Batch-Presets, deren Plugin live_op = True ist
        (Phase 12 Plugin-Modus). Bestehende Live-Signale bleiben unverändert."""
        try:
            presets = self._state_mgr.list_active_batch_presets()
        except Exception:
            return []
        active: List[Dict[str, Any]] = []
        for preset in presets:
            plugin_id = preset.get("plugin_id")
            if not plugin_id:
                continue
            try:
                plugin = self.plugin_executor.registry.get(plugin_id)
            except KeyError:
                continue
            if getattr(plugin, "live_op", True):
                active.append(preset)
        return active

    def _process_plugin_bars(self) -> None:
        """Phase 12 Plugin-Modus (Live): Fuehrt aktive Batch-Plugins mit
        live_op = True über dieselbe PluginExecutor-Instanz aus und schreibt
        den feature_store_payload in den feature_store."""
        plugins = self._get_active_live_plugins()
        if not plugins:
            return

        con = DbPool.get(DB_MARKET)
        latest_bar_time = con.execute("""
            SELECT EXTRACT('epoch' FROM MAX("time"))::BIGINT FROM ohlcv_bars
            WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
              AND "time" IS NOT NULL
        """, [self.symbol, self.timeframe]).fetchone()[0]
        if latest_bar_time is None:
            return
        latest_bar_time = int(latest_bar_time)

        if self._last_processed_bar_time is not None and latest_bar_time <= self._last_processed_bar_time:
            return

        df_ohlcv = self.feature_builder.load_ohlcv(
            self.symbol, self.timeframe, limit=self.lookback_bars
        )
        if df_ohlcv.empty:
            return

        df_plugin = prepare_plugin_df(df_ohlcv)
        for preset in plugins:
            plugin_id = preset.get("plugin_id")
            try:
                result = self.plugin_executor.execute(plugin_id, df_plugin, preset.get("params", {}))
            except Exception as e:
                self.log_message.emit(f"❌ Plugin-Fehler ({plugin_id}): {e}")
                continue
            payload = result.get("feature_store_payload", {}) if isinstance(result, dict) else {}
            if payload:
                try:
                    n = self.feature_builder.store_plugin_payload(self.symbol, self.timeframe, payload)
                    self.log_message.emit(
                        f"🔌 Plugin {plugin_id}: {n} Feature-Rows im feature_store"
                    )
                except Exception as e:
                    self.log_message.emit(f"❌ Plugin-Store-Fehler ({plugin_id}): {e}")

        self._last_processed_bar_time = latest_bar_time

    def _process_plugin_bars_resilient(self) -> None:
        """P14-03 (Live-Entkopplung A.1.2): Bar-Close-Evaluierung im
        Hintergrund mit STARK VERKÜRZTEM Lookback (1-2 Bars) gegen das im
        EvaluationContext.shared_state gepufferte Raster.

        Additiver Seam zum bestehenden Phase-12-Pfad (run() ruft weiterhin
        _process_plugin_bars auf): Der persistente self._live_context
        (shared_state = self._live_shared_state) puffert das Grid-Raster über
        alle Polls hinweg; bei Bar-Close werden nur die letzten 1-2 Bars neu
        bewertet. Schlägt ein Service fehl, wird der Fehler strukturiert
        (PluginExecutionErrorInfo) geloggt und der alte shared_state-Eintrag
        (State-Fallback) bleibt für abhängige Auswertungen erhalten – KEINE
        DB-Abfragen im Live-Tick, nur bei Bar-Close.
        """
        plugins = self._get_active_live_plugins()
        if not plugins:
            return

        con = DbPool.get(DB_MARKET)
        latest_bar_time = con.execute("""
            SELECT EXTRACT('epoch' FROM MAX("time"))::BIGINT FROM ohlcv_bars
            WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
              AND "time" IS NOT NULL
        """, [self.symbol, self.timeframe]).fetchone()[0]
        if latest_bar_time is None:
            return
        latest_bar_time = int(latest_bar_time)

        if self._last_processed_bar_time is not None and latest_bar_time <= self._last_processed_bar_time:
            return

        df_ohlcv = self.feature_builder.load_ohlcv(
            self.symbol, self.timeframe, limit=self.lookback_bars
        )
        if df_ohlcv.empty:
            return

        df_plugin = prepare_plugin_df(df_ohlcv)
        # P14-03: stark verkürzter Lookback (1-2 Bars) gegen das gepufferte
        # Raster – minimiert Rechnerlast und DB-I/O.
        df_short = df_plugin.tail(2)

        for preset in plugins:
            plugin_id = preset.get("plugin_id")
            # instance_id = plugin_id → GridLinesService schreibt sein Raster
            # in den persistenten shared_state (Namespace-isoliert).
            svc_ctx = replace(self._live_context, instance_id=plugin_id)
            if plugin_id == "proximity":
                # Proximity liest das Grid-Raster aus shared_state[depends_on[0]].
                svc_ctx = replace(svc_ctx, depends_on=["grid_lines"])
            try:
                result = self.plugin_executor.execute(
                    plugin_id, df_short, preset.get("params", {}), context=svc_ctx
                )
            except PluginExecutionError as e:
                info = e.info
                self.log_message.emit(
                    f"WARN [LiveAnalyzer] LiveService '{plugin_id}' fehlgeschlagen "
                    f"({info.stage}: {info.exception_type}: "
                    f"{info.exception_message}) – State-Fallback aktiv"
                )
                continue
            except Exception as e:
                self.log_message.emit(
                    f"WARN [LiveAnalyzer] LiveService '{plugin_id}' fehlgeschlagen: {e}"
                )
                continue
            payload = result.get("feature_store_payload", {}) if isinstance(result, dict) else {}
            if payload:
                try:
                    n = self.feature_builder.store_plugin_payload(
                        self.symbol, self.timeframe, payload
                    )
                    self.log_message.emit(
                        f"Plugin {plugin_id}: {n} Feature-Rows im feature_store"
                    )
                except Exception as e:
                    self.log_message.emit(f"Plugin-Store-Fehler ({plugin_id}): {e}")

        self._last_processed_bar_time = latest_bar_time

    def _get_live_signal_ids(self) -> List[str]:
        """Ermittelt alle signal_ids aus set_config, deren live_op == True ist."""
        live_ids = []
        for cfg in self.set_config.get("signals", []):
            sid = cfg["id"]
            sig = self.signals.get(sid)
            if sig is not None and getattr(sig, 'live_op', True):
                live_ids.append(sid)
        return live_ids

    def _fill_gaps(self) -> None:
        """
        Schliesst Luecken zwischen dem letzten Signal in signal_results
        und der aktuellsten Bar in market_data.duckdb.
        Verarbeitet NUR Signale mit live_op == True.
        """
        live_ids = self._get_live_signal_ids()
        if not live_ids:
            self.log_message.emit("  -> Keine live_op=True Signale, Auto-Fill uebersprungen.")
            return

        # Letztes Signal in der DB fuer dieses Symbol/TF ermitteln
        # EXTRACT(epoch) direkt in SQL fuer TIMESTAMPTZ-Korrektheit
        con = DbPool.get(DB_ANALYTICS)
        last_signal_ts = con.execute("""
            SELECT EXTRACT('epoch' FROM MAX(bar_time))::BIGINT FROM signal_results
            WHERE symbol = ? AND timeframe = ?
        """, [self.symbol, self.timeframe]).fetchone()[0]

        if last_signal_ts is None:
            self.log_message.emit("  -> Keine historischen Signale vorhanden, Auto-Fill uebersprungen.")
            return

        last_signal_ts = int(last_signal_ts)

        # Neueste Bar in market_data ermitteln
        con = DbPool.get(DB_MARKET)
        latest_bar_ts = con.execute("""
            SELECT EXTRACT('epoch' FROM MAX("time"))::BIGINT FROM ohlcv_bars
            WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
        """, [self.symbol, self.timeframe]).fetchone()[0]

        if latest_bar_ts is None:
            return

        latest_bar_ts = int(latest_bar_ts)

        # Pruefen ob Luecke existiert
        if latest_bar_ts <= last_signal_ts:
            self.log_message.emit("  -> Keine Luecken, Auto-Fill uebersprungen.")
            self._last_processed_bar_time = latest_bar_ts
            return

        self.log_message.emit(
            f"  -> Luecke erkannt! Letztes Signal: {last_signal_ts}, "
            f"aktuellste Bar: {latest_bar_ts}, fuelle auf..."
        )

        # OHLCV ab letztem Signal laden
        con = DbPool.get(DB_MARKET)
        df_missing = con.execute("""
            SELECT "time" AS bar_time, open, high, low, close
            FROM ohlcv_bars
            WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
              AND "time" > ? AND "time" <= ?
              AND "time" IS NOT NULL
              AND open IS NOT NULL AND high IS NOT NULL
              AND low IS NOT NULL AND close IS NOT NULL
            ORDER BY "time" ASC
        """, [self.symbol, self.timeframe,
              datetime.fromtimestamp(last_signal_ts, tz=timezone.utc),
              datetime.fromtimestamp(latest_bar_ts, tz=timezone.utc)]).df()

        if df_missing.empty:
            self.log_message.emit("  -> Keine neuen Bars gefunden.")
            self._last_processed_bar_time = latest_bar_ts
            return

        self.log_message.emit(f"  -> {len(df_missing)} neue Bars, berechne Signale...")

        # Features fuer das gesamte Lookback berechnen
        df_ohlcv = self.feature_builder.load_ohlcv(
            self.symbol, self.timeframe, limit=self.lookback_bars
        )
        if df_ohlcv.empty:
            return

        df_features = self.feature_builder.calculate_features(
            df_ohlcv,
            feature_names=self.get_required_features(),
            params=self._get_feature_params(),
        )

        # Features persistieren
        self.feature_builder.store_features(self.symbol, self.timeframe, df_features)

        # Signal-Set evaluieren
        result = self.evaluator.evaluate_set(self.set_config, df_features)

        # Nur die fehlenden Bars rausfiltern und Bulk-Insert
        sigs = result[result["signal_binary"] == 1].copy()
        if sigs.empty:
            self.log_message.emit("  -> Keine Signale in den neuen Bars.")
            self._last_processed_bar_time = latest_bar_ts
            return

        # Sicherstellen bar_time als int (value // 10**9 = epoch seconds, timezone-sicher)
        sigs["bar_time_epoch"] = sigs["bar_time"].apply(lambda x: int(x.value // 10**9))

        # Nur Bars nach dem letzten Signal nehmen
        sigs = sigs[sigs["bar_time_epoch"] > last_signal_ts]

        if sigs.empty:
            self.log_message.emit("  -> Keine neuen Signale in den gefuellten Bars.")
            self._last_processed_bar_time = latest_bar_ts
            return

        self._batch_write_signals(sigs)
        self._last_processed_bar_time = latest_bar_ts
        self.log_message.emit(f"  -> Auto-Fill abgeschlossen: {len(sigs)} Signale geschrieben.")

    def _batch_write_signals(self, sigs_df: pd.DataFrame) -> None:
        """Bulk-Insert fuer mehrere Signale mit DELETE-vor-INSERT pro Bar.
        Schreibt Signale basierend auf den Quell-Source-IDs im Ergebnis-DataFrame."""
        con = DbPool.get(DB_ANALYTICS)
        # Bestimme source_id(s) aus den Ergebnis-Spalten (conf_*)
        source_cols = [c for c in sigs_df.columns if c.startswith("conf_")]
        if not source_cols:
            self.log_message.emit("  [WARN] Keine conf_*-Spalten im Ergebnis.")
            return

        rows = []
        for _, row in sigs_df.iterrows():
            bt = row["bar_time_epoch"]
            dt_val = datetime.fromtimestamp(int(bt), tz=timezone.utc)
            for sc in source_cols:
                source_id = sc.replace("conf_", "")
                confidence = float(row[sc])
                rows.append((
                    str(uuid.uuid4()),
                    self.symbol,
                    self.timeframe,
                    dt_val,
                    source_id,
                    confidence,
                    "live_stream",
                    json.dumps({"source": "LiveAnalyzerFill", "lookback": self.lookback_bars}),
                ))
                # Einzel-DELETE pro Bar
                con.execute("""
                    DELETE FROM signal_results
                    WHERE symbol = ? AND timeframe = ? AND bar_time = ? AND source_id = ?
                """, [self.symbol, self.timeframe, dt_val, source_id])

        con.executemany("""
            INSERT INTO signal_results (event_id, symbol, timeframe, bar_time, source_id, confidence, context_type, metadata_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)

    def _process_new_bars(self) -> None:
        """Lädt ALLE neuen Kerzen seit _last_processed_bar_time aus market_data.duckdb
        und analysiert sie. EXTRACT(epoch) in SQL für TIMESTAMPTZ-Korrektheit."""
        # Keine aktiven Signale in der Set-Konfiguration → keine Live-Analyse (Testsignale deaktiviert)
        if not self.set_config.get("signals"):
            return

        # Neueste Zeit als Referenz holen
        con = DbPool.get(DB_MARKET)
        latest_bar_time = con.execute("""
            SELECT EXTRACT('epoch' FROM MAX("time"))::BIGINT FROM ohlcv_bars
            WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
              AND "time" IS NOT NULL
        """, [self.symbol, self.timeframe]).fetchone()[0]

        if latest_bar_time is None:
            return

        latest_bar_time = int(latest_bar_time)

        # Keine neuen Bars
        if self._last_processed_bar_time is not None and latest_bar_time <= self._last_processed_bar_time:
            return

        # Alle neuen Bars seit last_processed_bar_time laden
        if self._last_processed_bar_time is not None:
            con = DbPool.get(DB_MARKET)
            rows = con.execute("""
                SELECT EXTRACT('epoch' FROM "time")::BIGINT AS time_epoch,
                       open, high, low, close
                FROM ohlcv_bars
                WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
                  AND "time" > ?::TIMESTAMPTZ AND "time" <= ?::TIMESTAMPTZ
                  AND "time" IS NOT NULL
                  AND open IS NOT NULL AND high IS NOT NULL
                  AND low IS NOT NULL AND close IS NOT NULL
                ORDER BY "time" ASC
            """, [self.symbol, self.timeframe,
                  datetime.fromtimestamp(self._last_processed_bar_time, tz=timezone.utc),
                  datetime.fromtimestamp(latest_bar_time, tz=timezone.utc)]).fetchall()
        else:
            # Erstmaliger Start: nur neueste Bar nehmen
            con = DbPool.get(DB_MARKET)
            rows = con.execute("""
                SELECT EXTRACT('epoch' FROM "time")::BIGINT AS time_epoch,
                       open, high, low, close
                FROM ohlcv_bars
                WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
                  AND "time" IS NOT NULL
                  AND open IS NOT NULL AND high IS NOT NULL
                  AND low IS NOT NULL AND close IS NOT NULL
                ORDER BY "time" DESC
                LIMIT 1
            """, [self.symbol, self.timeframe]).fetchall()

        if not rows:
            self._last_processed_bar_time = latest_bar_time
            return

        # Lookback-Daten für Feature-Berechnung laden (nur einmal!)
        df_ohlcv = self.feature_builder.load_ohlcv(
            self.symbol, self.timeframe, limit=self.lookback_bars
        )
        if df_ohlcv.empty:
            return

        df_features = self.feature_builder.calculate_features(
            df_ohlcv,
            feature_names=self.get_required_features(),
            params=self._get_feature_params(),
        )

        self.feature_builder.store_features(self.symbol, self.timeframe, df_features)
        result = self.evaluator.evaluate_set(self.set_config, df_features)

        # Nur die letzten N Bars (neue) auswerten
        result_new = result.iloc[-len(rows):].copy()

        # Quell-Source-IDs aus den conf_-Spalten ermitteln
        source_cols = [c for c in result_new.columns if c.startswith("conf_")]
        if not source_cols:
            source_cols = ["confidence_total"]

        for _, row in result_new.iterrows():
            bar_time = int(row["bar_time"].value // 10**9)
            confidence = float(row["confidence_total"])
            signal_binary = int(row["signal_binary"])

            if signal_binary == 1:
                # Erste Quell-Source-ID für UI-Event nehmen
                src = source_cols[0]
                source_id = src.replace("conf_", "") if src.startswith("conf_") else "grid_proximity_v1"
                self._write_signal_result(bar_time, confidence, source_id)
                self.new_live_signal.emit(
                    self.symbol, self.timeframe, bar_time, confidence, source_id
                )
                self.log_message.emit(
                    f"🔔 Live-Signal: {self.symbol} {self.timeframe} @ {bar_time} "
                    f"(confidence={confidence:.2f})"
                )

        self._last_processed_bar_time = latest_bar_time

    def _write_signal_result(self, bar_time: int, confidence: float, source_id: str = "grid_proximity_v1") -> None:
        """Schreibt ein Live-Signal in signal_results.
        Loescht vorher ein evtl. vorhandenes Signal fuer denselben (symbol, timeframe, bar_time, source_id),
        damit es exakt 1 Signal pro Kerze gibt."""
        con = DbPool.get(DB_ANALYTICS)
        dt_val = datetime.fromtimestamp(bar_time, tz=timezone.utc)
        # Vorhandenes Signal entfernen
        con.execute("""
            DELETE FROM signal_results
            WHERE symbol = ? AND timeframe = ? AND bar_time = ? AND source_id = ?
        """, [self.symbol, self.timeframe, dt_val, source_id])
        # Neues Signal einfuegen
        con.execute("""
            INSERT INTO signal_results (event_id, symbol, timeframe, bar_time, source_id, confidence, context_type, metadata_payload)
            VALUES (?, ?, ?, ?, ?, ?, 'live_stream', ?)
        """, [
            str(uuid.uuid4()),
            self.symbol,
            self.timeframe,
            dt_val,
            source_id,
            confidence,
            json.dumps({"source": "LiveAnalyzer", "lookback": self.lookback_bars}),
        ])

    def analyze_single_bar(
        self,
        symbol: str,
        timeframe: str,
        bar_time: int,
        open_price: float,
        high: float,
        low: float,
        close: float,
    ) -> Optional[float]:
        """
        Analysiert eine einzelne Kerze (für externen Tick-Aggregator).
        
        Args:
            symbol: Symbol-Name
            timeframe: Timeframe
            bar_time: Unix-Timestamp der Kerze
            open_price, high, low, close: OHLC-Werte
        
        Returns:
            Confidence-Score oder None wenn kein Signal
        """
        # Keine aktiven Signale → keine Analyse (Testsignale deaktiviert)
        if not self.set_config.get("signals"):
            return None

        # Duplikatserkennung
        if self._last_processed_bar_time is not None and bar_time <= self._last_processed_bar_time:
            return None

        self._last_processed_bar_time = bar_time

        # Lookback-Daten laden
        df_ohlcv = self.feature_builder.load_ohlcv(symbol, timeframe, limit=self.lookback_bars)
        if df_ohlcv.empty:
            return None

        # Features berechnen (dynamisch aus set_config)
        df_features = self.feature_builder.calculate_features(
            df_ohlcv,
            feature_names=self.get_required_features(),
            params=self._get_feature_params(),
        )

        # Features persistieren
        self.feature_builder.store_features(symbol, timeframe, df_features)

        # Signal evaluieren
        result = self.evaluator.evaluate_set(self.set_config, df_features)
        last_row = result.iloc[-1]
        confidence = float(last_row["confidence_total"])
        signal_binary = int(last_row["signal_binary"])

        # Quell-Source-ID aus conf_-Spalten ermitteln
        source_cols = [c for c in result.columns if c.startswith("conf_")]
        src = source_cols[0] if source_cols else "confidence_total"
        source_id = src.replace("conf_", "") if src.startswith("conf_") else "grid_proximity_v1"

        if signal_binary == 1:
            self._write_signal_result(bar_time, confidence, source_id)
            self.new_live_signal.emit(symbol, timeframe, bar_time, confidence, source_id)
            return confidence

        return None


# ==============================================================================
# Standalone-Funktion fuer Chart-Trigger (aufrufbar ohne LiveAnalyzer-Instanz)
# ==============================================================================
# Phase 13 Schritt 7.B: Rueckbau der Alt-Signal-Mechanik.
# Die Funktion ist DEAKTIVIERT - es finden KEINE signal_results-Schreibvorgaenge
# mehr statt. Der Chart-Trigger (chart_win.py) wurde entfernt; der Stub bleibt
# nur als API-Hinweis erhalten, falls noch Alt-Code auf sie zeigt.
def fill_gaps_for_pair(symbol: str, timeframe: str, lookback_bars: int = 500) -> None:
    """
    DEAKTIVIERT (Phase 13 Schritt 7.B): Alt-Signal-Mechanik ist zurueckgebaut.

    Frucher: Schliessen von Datenluecken durch Nachberechnung der
    Alt-Signal-Sets (ema_atr_set_v1 / alternating_arrow_v1) mit Write in
    signal_results. Heute: Keine signal_results-Writes mehr - Marker und
    Statistik lesen ausschliesslich den feature_store (feature_data der
    Plugins/Proximity-Services). Der Stub gibt nur noch einen Hinweis aus.
    """
    print(
        f"  [Chart-Trigger] fill_gaps_for_pair DEAKTIVIERT (Phase 13 7.B): "
        f"{symbol}:{timeframe} - keine Alt-Signal-Writes mehr."
    )

