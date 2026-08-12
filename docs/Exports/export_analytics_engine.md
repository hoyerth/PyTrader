# PROJEKT-ÜBERSICHT: PyTrader — Analytics-Engine, Features & Auswertung

> Teil-Export (sachbezogen). Vollständiger Export: export_Full.md
> Dateien in dieser Datei: 27

## 1. ORDNERSTRUKTUR
```
PyTrader/
    analytics/
        __init__.py
        background_workers/
            __init__.py
            live_analyzer.py
        engine/
            __init__.py
            description_dialog.py
            schema_migrator.py
            set_evaluator.py
            tree_builder.py
        features/
            __init__.py
            base_feature.py
            definitions/
                __init__.py
                atr_normalized.py
                ema_diff.py
                grid_levels.py
                grid_math.py
                srv_grid_lines.py
                srv_proximity.py
                srv_swing_momentum.py
                srv_swing_structure.py
                srv_swing_volume_profile.py
                srv_trend_breakout.py
                srv_trend_hma_pivot.py
                srv_trend_regime.py
            feature_builder.py
            plugins/
                __init__.py
                base_plugin.py
        statistics_repository.py
```

## 2. QUELLCODE

### DATEI: analytics/__init__.py
```py

```

--------------------------------------------------

### DATEI: analytics/statistics_repository.py
```py
# analytics/statistics_repository.py
"""
Statistics Repository – SQL-Aggregations-Queries auf feature_data
(Proximity-Services, feature_id='srv_proximity') + Forward-Performance.

Die Statistik liest die Treffer-Records aus dem feature_store
(feature_data der Proximity-Services); signal_results-Tabellen existieren
seit Phase 15 nicht mehr.

Da die feature_store-Tabelle KEINE set_id-Spalte hat, ist das 'Set' im
neuen Datenmodell die feature_id (Plugin-Identität, z. B. 'srv_proximity').
"""

from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import duckdb
import pandas as pd

from db_service import DbPool

BASE_DIR = Path(__file__).resolve().parent.parent
DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")
DB_MARKET = str(BASE_DIR / "data" / "market_data.duckdb")


class StatisticsRepository:
    """Kapselt alle SQL-Zugriffe für das Statistik-Fenster."""

    def get_available_sets(self) -> List[str]:
        """Liefert alle verfügbaren Sets aus den Feature-Store-Daten.

        Phase 13 Schritt 7: Quelle sind die feature_data-Einträge der
        Proximity-Services (feature_id IS NOT NULL + feature_data gefüllt).
        """
        if not Path(DB_ANALYTICS).exists():
            return []
        con = DbPool.get(DB_ANALYTICS)
        rows = con.execute("""
                SELECT DISTINCT feature_id FROM feature_store
                WHERE feature_id IS NOT NULL AND feature_data IS NOT NULL
                ORDER BY feature_id
            """).fetchall()
        return [r[0] for r in rows]

    def get_summary(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Aggregierte Kennzahlen über feature_data (Proximity-Hits).

        Returns:
            Dict mit total_signals (Hit-Bars), avg_confidence (Hit-Fraktion
            0..1), win_rate (% der Hits im nativen Zeitfenster), best_tf.
        """
        if not Path(DB_ANALYTICS).exists():
            return {"total_signals": 0, "avg_confidence": 0.0, "win_rate": 0.0, "best_tf": "-"}

        conditions = ["feature_data IS NOT NULL"]
        params = []
        if symbol and symbol != "ALLE":
            conditions.append("LOWER(symbol) = LOWER(?)")
            params.append(symbol)
        if timeframe and timeframe != "ALLE":
            conditions.append("LOWER(timeframe) = LOWER(?)")
            params.append(timeframe)
        if source_id:
            conditions.append("feature_id = ?")
            params.append(source_id)

        where_clause = " AND ".join(conditions)

        con = DbPool.get(DB_ANALYTICS)
        # Gesamtzahl Bars + Hit-Bars (is_hit=true in feature_data)
        row = con.execute(f"""
            SELECT
                COUNT(*) AS total_bars,
                COUNT(*) FILTER (WHERE CAST(feature_data['is_hit'] AS BOOLEAN)) AS hit_bars
            FROM feature_store
            WHERE {where_clause}
        """, params).fetchone()
        total_bars = int(row[0]) if row[0] else 0
        hit_bars = int(row[1]) if row[1] else 0

        # avg_confidence = Hit-Fraktion über alle gescannten Bars (0..1)
        avg_conf = (hit_bars / total_bars) if total_bars else 0.0

        # Win-Rate: % der Hits im nativen UTC-Zeitfenster (in_time_window)
        win_rate = self._calc_win_rate(con, where_clause, params)

        # Bester Timeframe (meiste Hits)
        row_tf = con.execute(f"""
            SELECT timeframe, COUNT(*) AS cnt
            FROM feature_store
            WHERE {where_clause}
              AND CAST(feature_data['is_hit'] AS BOOLEAN)
            GROUP BY timeframe
            ORDER BY cnt DESC
            LIMIT 1
        """, params).fetchone()
        best_tf = str(row_tf[0]) if row_tf else "-"

        return {
            "total_signals": hit_bars,
            "avg_confidence": round(avg_conf, 4),
            "win_rate": round(win_rate, 1),
            "best_tf": best_tf,
        }

    def _calc_win_rate(
        self,
        con: duckdb.DuckDBPyConnection,
        where_clause: str,
        params: List[Any],
    ) -> float:
        """
        Berechnet die Win-Rate als Qualitäts-Proxy: Anteil der Hit-Bars,
        die im nativen UTC-Zeitfenster (in_time_window=true) liegen.
        """
        try:
            row = con.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE CAST(feature_data['is_hit'] AS BOOLEAN)) AS total,
                    COUNT(*) FILTER (WHERE CAST(feature_data['is_hit'] AS BOOLEAN)
                                     AND CAST(feature_data['in_time_window'] AS BOOLEAN)) AS wins
                FROM feature_store
                WHERE {where_clause}
            """, params).fetchone()

            total = int(row[0]) if row[0] else 0
            wins = int(row[1]) if row[1] else 0

            if total == 0:
                return 0.0
            return (wins / total) * 100.0
        except Exception as e:
            print(f"⚠️ [StatisticsRepository] Win-Rate Fehler: {e}")
            return 0.0

    def fetch_signals(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        Detailierte Signalliste für die Tabelle – aus feature_data.

        Returns:
            Liste von Dicts mit time, symbol, timeframe, source_id (feature_id),
            confidence (Hit-Intensität 0..1), outcome (Win/Neutral).
        """
        if not Path(DB_ANALYTICS).exists():
            return []

        conditions = ["feature_data IS NOT NULL"]
        params = []
        if symbol and symbol != "ALLE":
            conditions.append("LOWER(symbol) = LOWER(?)")
            params.append(symbol)
        if timeframe and timeframe != "ALLE":
            conditions.append("LOWER(timeframe) = LOWER(?)")
            params.append(timeframe)
        if source_id:
            conditions.append("feature_id = ?")
            params.append(source_id)

        where_clause = " AND ".join(conditions)

        con = DbPool.get(DB_ANALYTICS)
        try:
            rows = con.execute(f"""
                SELECT
                    bar_time,
                    symbol,
                    timeframe,
                    feature_id,
                    CAST(feature_data['is_hit'] AS BOOLEAN) AS is_hit,
                    CAST(feature_data['in_time_window'] AS BOOLEAN) AS in_window,
                    COALESCE(json_array_length(feature_data['levels_hit']), 0) AS n_levels
                FROM feature_store
                WHERE {where_clause}
                  AND CAST(feature_data['is_hit'] AS BOOLEAN)
                ORDER BY bar_time DESC
                LIMIT ?
            """, params + [limit]).fetchall()
        except Exception as e:
            print(f"⚠️ [StatisticsRepository] fetch_signals Fehler: {e}")
            return []

        results = []
        for row in rows:
            bar_time = row[0]
            symbol_val = str(row[1])
            tf_val = str(row[2])
            source = str(row[3]) if row[3] else ""
            n_levels = int(row[6]) if row[6] else 0
            in_window = bool(row[5])

            # Hit-Intensität: je getroffenes Level +0.25 (max. 1.0)
            confidence = min(1.0, n_levels * 0.25)

            # Outcome als Qualitäts-Proxy: Hit im nativen Zeitfenster = Win
            outcome = "Win" if in_window else "Neutral"

            # Zeitstempel
            if hasattr(bar_time, 'timestamp'):
                time_sec = int(bar_time.timestamp())
            else:
                time_sec = int(bar_time)

            results.append({
                "time": time_sec,
                "symbol": symbol_val,
                "timeframe": tf_val,
                "source_id": source,
                "confidence": confidence,
                "outcome": outcome,
            })

        return results

```

--------------------------------------------------

### DATEI: analytics/background_workers/__init__.py
```py

```

--------------------------------------------------

### DATEI: analytics/background_workers/live_analyzer.py
```py
# analytics/background_workers/live_analyzer.py
"""
Live Analyzer – QThread-Worker für die Live-Analyse bei Bar-Close.

Phase 15 (Alt-Signal-Rückbau): Die Alt-Signal-Mechanik (ema_atr_set_v1 /
alternating_arrow_v1 / grid_proximity_v1) wurde komplett entfernt – es gibt
keine Signal-Engine, keine signal_results-Writes und keine new_live_signal-
Emission mehr. Der LiveAnalyzer evaluiert ausschließlich die aktiven
Batch-Plugins (live_op=True) über den PluginExecutor:

    Tick -> Bar-Close -> PluginExecutor -> feature_store (feature_data)

Der resiliente Pfad `_process_plugin_bars_resilient()` (P14-03-E) ist der
primäre Bar-Close-Pfad: stark verkürzter Lookback (1-2 Bars) gegen das im
`PluginContext.shared_state` gepufferte Raster – keine volle Pipeline und
KEINE DB-Abfragen im Live-Tick.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

from analytics.engine.service_models import generate_instance_hash
from analytics.features.feature_builder import (
    FeatureBuilder,
    PluginExecutor,
    PluginExecutionError,
    prepare_plugin_df,
)
from analytics.features.plugins.base_plugin import PluginContext
from db_service import DbPool
from state_manager import StateManager

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")
DB_MARKET = str(BASE_DIR / "data" / "market_data.duckdb")


class LiveAnalyzer(QThread):
    """
    Analysiert eine geschlossene Live-Kerze (Bar-Close Event) über die
    aktiven Batch-Plugins (live_op=True) und schreibt die Ergebnisse in den
    feature_store (feature_data).
    """

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

        # Zentraler PluginExecutor für den Plugin-Modus (aktive Batch-Presets
        # mit live_op = True). Dieselbe Instanz, die auch der HistoricalScanner
        # nutzt.
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

        # Letzte verarbeitete Bar-Time (für Duplikatserkennung)
        self._last_processed_bar_time: Optional[int] = None

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        """
        Hauptschleife: Wartet auf Bar-Close-Events (Polling) und evaluiert
        die aktiven Batch-Plugins über den resilienten Pfad
        `_process_plugin_bars_resilient()` (Plugin-Modus, gepuffertes
        shared_state-Raster).
        """
        self.log_message.emit(
            f"LiveAnalyzer gestartet: {self.symbol} {self.timeframe}, "
            f"lookback={self.lookback_bars}"
        )

        while self._running:
            try:
                self._process_plugin_bars_resilient()
            except Exception as e:
                self.log_message.emit(f"❌ LiveAnalyzer Fehler: {e}")

            # Polling-Intervall: 1 Sekunde (fuer M1 ausreichend)
            self.msleep(1000)

        self.log_message.emit("LiveAnalyzer gestoppt.")

    def _get_active_live_plugins(self) -> List[Dict[str, Any]]:
        """Liefert aktive Batch-Presets, deren Plugin live_op = True ist
        (Phase 12 Plugin-Modus)."""
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
        den feature_store_payload in den feature_store.

        P14-03 (Schritt 3.1, additiv): Fuer laufende Bar-Close-Evaluierungen
        existiert der Seam _process_plugin_bars_resilient() – er nutzt einen
        stark verkuerzten Lookback (limit=2: 1 unvollstaendige + 1 frisch
        geschlossene Kerze) gegen das gepufferte EvaluationContext.shared_state
        -Raster. Dieser Alt-Pfad bleibt unveraendert."""
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
                    # 20.04 (Q9): instance_hash der Preset-Variante (Parameter-
                    # Hash) – Spalte im feature_store fuer Varianten-Statistik
                    # und gezieltes Purge (Q5).
                    instance_hash = generate_instance_hash(
                        plugin_id, preset.get("params") or {})
                    n = self.feature_builder.store_plugin_payload(
                        self.symbol, self.timeframe, payload,
                        instance_hash=instance_hash)
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
            # instance_id = plugin_id → srv_grid_lines schreibt sein Raster
            # in den persistenten shared_state (Namespace-isoliert).
            svc_ctx = replace(self._live_context, instance_id=plugin_id)
            if plugin_id == "srv_proximity":
                # srv_proximity liest das Grid-Raster aus shared_state[depends_on[0]].
                svc_ctx = replace(svc_ctx, depends_on=["srv_grid_lines"])
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
                    # 20.04 (Q9): instance_hash der Preset-Variante.
                    instance_hash = generate_instance_hash(
                        plugin_id, preset.get("params") or {})
                    n = self.feature_builder.store_plugin_payload(
                        self.symbol, self.timeframe, payload,
                        instance_hash=instance_hash
                    )
                    self.log_message.emit(
                        f"Plugin {plugin_id}: {n} Feature-Rows im feature_store"
                    )
                except Exception as e:
                    self.log_message.emit(f"Plugin-Store-Fehler ({plugin_id}): {e}")

        self._last_processed_bar_time = latest_bar_time

```

--------------------------------------------------

### DATEI: analytics/engine/__init__.py
```py

```

--------------------------------------------------

### DATEI: analytics/engine/description_dialog.py
```py
# analytics/engine/description_dialog.py
"""
Phase 14 P14-01 – ServiceDescriptionDialog.

Zeigt die vollständigen Beschreibungsfelder einer Service-Instanz / eines
Plugins / eines Service-Sets an: Plugin-Name, Version, API-Version, Autor,
Kurz-Beschreibung, description_long (Markdown-Hilfe) und condition_rules
(strukturierte Regeln) in einem sauberen Read-Only QTextBrowser.

Design-Regeln:
- Headless-fähig instanziierbar: Der Konstruktor startet KEINEN Event-Loop
  (kein exec_()); er baut nur das Widget auf. Der Aufrufer entscheidet, ob
  und wann der Dialog modal angezeigt wird.
- Rein additiv: Der Dialog importiert keine konkreten Orchestratoren und
  greift ausschließlich auf übergebene Daten (Plugin-Objekt / dict) zu
  (Entkopplung, keine zirkulären Abhängigkeiten).
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
)


class ServiceDescriptionEditDialog(QDialog):
    """Modaler Bearbeitungs-Dialog für die Instanz-/Set-Beschreibung.

    Phase 16 (05.08.2026): Ersetzt die Read-Only-Ansicht im Service Window
    für editierbare Beschreibungen (ServiceInstanceConfig.description bzw.
    ServiceSetDefinition.description). Reines UI-Widget (kein Repo-Zugriff,
    kein EventBus – IoC): Der Aufrufer (ServiceWindow) verbindet das
    `save_requested`-Signal und persistiert via ServiceSetRepository +
    `event_bus.service_set_changed`.

    Aufbau:
      * Optionale Kopfzeile: header_line (z.B. 'aktiv/im <Indikator>') +
        Instanz-ID / Plugin-ID.
      * Mehrzeiliges QTextEdit für die Beschreibung.
      * Buttons [Abbrechen] / [Speichern] – [Speichern] emittiert
        `save_requested(neuer_Text)` und schliesst den Dialog mit accept().

    Headless-fähig: Der Konstruktor startet KEINEN Event-Loop (kein
    exec_()); der Aufrufer entscheidet, wann modal geöffnet wird.
    """

    #: Wird beim Klick auf [Speichern] mit dem neuen Beschreibungstext
    #: emittiert (der Orchestrator persistiert via Repo + EventBus).
    save_requested = Signal(str)

    def __init__(
        self,
        parent=None,
        *,
        instance_id: str = "",
        plugin_id: str = "",
        header_line: str = "",
        description: str = "",
        title: str = "Beschreibung bearbeiten",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self.setMinimumHeight(260)

        layout = QVBoxLayout(self)

        head_parts: List[str] = []
        if header_line and str(header_line).strip():
            head_parts.append(
                f"<b>{self._html_escape(header_line)}</b>")
        info_bits: List[str] = []
        if instance_id:
            info_bits.append(f"<b>Instanz:</b> {self._html_escape(instance_id)}")
        if plugin_id:
            info_bits.append(f"<i>({self._html_escape(plugin_id)})</i>")
        if info_bits:
            head_parts.append(" ".join(info_bits))
        if head_parts:
            head = QLabel("<br>".join(head_parts))
            head.setWordWrap(True)
            layout.addWidget(head)

        self._editor = QTextEdit()
        self._editor.setPlainText(str(description or ""))
        self._editor.setPlaceholderText(
            "Individuelle Anmerkung für diese Instanz (optional)")
        layout.addWidget(self._editor, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Speichern")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    @staticmethod
    def _html_escape(value: str) -> str:
        """Minimaler HTML-Escape für Kopfzeilen-Strings (kein externer Import)."""
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _on_save(self) -> None:
        """[Speichern]: Emittiert save_requested mit dem aktuellen Text und
        schliesst den Dialog mit accept() (keine Repo-/DB-Logik hier)."""
        self.save_requested.emit(self._editor.toPlainText())
        self.accept()


class ServiceDescriptionDialog(QDialog):
    """Zeigt Plugin-/Service-/Set-Informationen im Read-Only-Modus an.

    Kann wahlweise direkt mit expliziten Feldern ODER komfortabel über die
    Klassenmethode ``from_plugin()`` aus einem PluginFeature + Instanz-Config
    befüllt werden (headless instanziierbar, kein exec_() im Konstruktor).
    """

    def __init__(
        self,
        parent=None,
        *,
        instance_id: Optional[str] = None,
        display_name: str = "",
        plugin_id: str = "",
        version: str = "1.0.0",
        api_version: str = "1",
        author: str = "",
        description: str = "",
        description_long: str = "",
        condition_rules: Optional[List[str]] = None,
        instance_description: str = "",
        header_line: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Service-Informationen")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        browser = QTextBrowser()
        browser.setReadOnly(True)
        browser.setOpenExternalLinks(True)
        browser.setHtml(self._render_html(
            instance_id=instance_id,
            display_name=display_name,
            plugin_id=plugin_id,
            version=version,
            api_version=api_version,
            author=author,
            description=description,
            description_long=description_long,
            condition_rules=condition_rules,
            instance_description=instance_description,
            header_line=header_line,
        ))
        layout.addWidget(browser)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # -------------------------------------------------------------------------
    # Fabrik-Methode: bequeme Befüllung aus PluginFeature + Instanz-Config
    # -------------------------------------------------------------------------
    @classmethod
    def from_plugin(
        cls,
        plugin: Any,
        instance_id: str = "",
        config: Optional[Dict[str, Any]] = None,
        parent=None,
        *,
        header_line: str = "",
    ) -> "ServiceDescriptionDialog":
        """Baut den Dialog aus einem PluginFeature und einer optionalen
        ServiceInstanceConfig (description der Instanz).

        Args:
            header_line: Optionale ERSTE Zeile (z.B. 'aktiv/im <Indikator>'
                         aus dem Info-Button-Tooltip) – Bugfix 05.08.2026.
        """
        meta = dict(getattr(plugin, "metadata", None) or {})
        cfg = dict(config or {})
        return cls(
            parent=parent,
            instance_id=instance_id or "",
            display_name=str(meta.get("display_name", "") or ""),
            plugin_id=str(getattr(plugin, "plugin_id", "") or ""),
            version=str(getattr(plugin, "version", "1.0.0") or "1.0.0"),
            api_version=str(meta.get("api_version", "1") or "1"),
            author=str(meta.get("author", "") or ""),
            description=str(meta.get("description", "") or ""),
            description_long=str(meta.get("description_long", "") or ""),
            condition_rules=list(meta.get("condition_rules") or []),
            instance_description=str(cfg.get("description", "") or ""),
            header_line=header_line,
        )

    @classmethod
    def from_set(
        cls,
        definition: Optional[Dict[str, Any]],
        parent=None,
        *,
        header_line: str = "",
    ) -> "ServiceDescriptionDialog":
        """Baut den Dialog aus einer Service-Set-Definition (Set-Info).

        Zeigt Set-Name (display_name), Set-Beschreibung (description) und die
        Service-Liste (instance_id [plugin_id] in execution_order-Reihenfolge).

        Args:
            definition:  Set-Definition aus dem ServiceSetRepository (set_id,
                         display_name, description, execution_order, services).
            parent:      Qt-Parent (optional).
            header_line: Optionale ERSTE Zeile (z.B. 'im Ind_FixedGridProximity'
                         aus dem Info-Button-Tooltip) – wird als fette Zeile
                         gefolgt von einer Leerzeile vor dem Beschreibungstext
                         gerendert (Bugfix 05.08.2026, Info-Button MasterTree).
        """
        d = dict(definition or {})
        set_id = str(d.get("set_id") or "")
        display_name = str(d.get("display_name") or set_id or "Unbenannt")
        description = str(d.get("description") or "")
        services = d.get("services") or {}
        order = d.get("execution_order") or []
        svc_lines = [
            f"{iid} [{str((services.get(iid) or {}).get('plugin_id') or iid)}]"
            for iid in order
        ]
        if svc_lines:
            details = "<br>".join(svc_lines)
        else:
            details = ""
        return cls(
            parent=parent,
            instance_id=None,
            display_name=display_name,
            plugin_id=set_id or "",
            version="",
            api_version="",
            author="",
            description=description,
            description_long=details,
            condition_rules=[],
            instance_description="",
            header_line=header_line,
        )

    # -------------------------------------------------------------------------
    # Interna
    # -------------------------------------------------------------------------
    @staticmethod
    def _html_escape(value: str) -> str:
        """Minimaler HTML-Escape für Anzeige-Strings (kein externer Import)."""
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _render_html(
        self,
        *,
        instance_id: Optional[str],
        display_name: str,
        plugin_id: str,
        version: str,
        api_version: str,
        author: str,
        description: str,
        description_long: str,
        condition_rules: Optional[List[str]],
        instance_description: str,
        header_line: str = "",
    ) -> str:
        """Erzeugt das Read-Only-HTML des Dialogs (sauber strukturiert)."""
        e = self._html_escape
        parts: List[str] = []

        # Bugfix 05.08.2026: optionale ERSTE Zeile (Info-Button-Tooltip,
        # z.B. 'aktiv/im <Indikator>') + Leerzeile vor dem eigentlichen Text.
        if header_line and str(header_line).strip():
            parts.append(f"<p style='margin-bottom:0;'><b>{e(header_line)}</b></p>")
            parts.append("<p>&nbsp;</p>")

        # Kopf: Instanz (falls vorhanden) + Plugin-Name + Version
        head = ""
        if instance_id:
            head += f"<b>Instanz:</b> {e(instance_id)}<br>"
        if display_name:
            head += f"<b>{e(display_name)}</b>"
        if plugin_id:
            head += f" <i>({e(plugin_id)})</i>"
        if version:
            head += f" &mdash; v{e(version)}"
        if head.strip():
            parts.append(f"<h3>{head}</h3>")

        # Meta-Zeile: API-Version + Autor
        meta_bits = []
        if api_version:
            meta_bits.append(f"API-Version: {e(api_version)}")
        if author:
            meta_bits.append(f"Autor: {e(author)}")
        if meta_bits:
            parts.append(f"<p style='color:#666;'>{' | '.join(meta_bits)}</p>")

        # Instanz-Beschreibung (ServiceInstanceConfig.description)
        if instance_description:
            parts.append(f"<p><b>Instanz-Anmerkung:</b><br>{e(instance_description)}</p>")

        # Kurz-Beschreibung
        if description:
            parts.append(f"<p><b>Beschreibung:</b><br>{e(description)}</p>")

        # Lange Beschreibung (Markdown-Hilfe)
        if description_long:
            parts.append(f"<p><b>Details:</b><br>{e(description_long)}</p>")

        # Strukturierte Regeln
        rules = [r for r in (condition_rules or []) if str(r).strip()]
        if rules:
            items = "".join(f"<li>{e(r)}</li>" for r in rules)
            parts.append(f"<p><b>Regeln:</b></p><ul>{items}</ul>")

        if not parts:
            parts.append("<p>Keine Beschreibungsfelder hinterlegt.</p>")

        return (
            "<html><body style='font-family:Segoe UI, sans-serif; font-size:12px;'>"
            + "".join(parts)
            + "</body></html>"
        )

```

--------------------------------------------------

### DATEI: analytics/engine/schema_migrator.py
```py
# analytics/engine/schema_migrator.py
"""
Phase 14 P14-04 – Schema-Migrator (Semantic Versioning & Rollback-Schutz).

Sicherstellung der dauerhaften Lauffähigkeit alter Service-Sets bei
Weiterentwicklung von Plugins. Jede ServiceInstanceConfig trägt ein
`version`-Feld (Semantic Versioning major.minor.patch, z. B. "1.0.0").
Wird ein Set geladen, dessen Instanz-Version hinter der aktuellen
Plugin-Version zurückliegt (Major-/Minor-Abweichung), migriert der
SchemaMigrator die Instanz-Konfiguration IM SPEICHER (transparent, ohne
die Datenbank zu verändern):

  1. fehlende Parameter-Keys werden mit ihren Schema-Defaults ergänzt,
  2. veraltete, nicht mehr im Parameter-Schema enthaltene Keys werden entfernt,
  3. die Instanz-Version wird auf die aktuelle plugin.version angehoben.

Reine Patch-Abweichungen (z. B. 1.0.0 -> 1.0.1) lösen KEINE Migration aus
(Architektur-Invariante 5). Ein fehlendes `version`-Feld wird als
Legacy-Stand "0.0.0" interpretiert und daher immer migriert.

ROLLBACK-SCHUTZ: Wirft der Migrator während der Aufbereitung eine Exception,
wird die Migration abgebrochen und ein MigrationError geworfen. Der Aufrufer
(ServiceSetRepository.get_set()) gibt dann das UNMIGRIERTE Original-Set
zurück (Rollback auf Datenbank-Ebene, Invariante 8).
"""

from typing import Any, Dict

from analytics.features.plugins.base_plugin import PluginFeature


class MigrationError(Exception):
    """Wird vom SchemaMigrator geworfen, wenn die Migration fehlschlägt.

    Löst beim Aufrufer (ServiceSetRepository.get_set()) den Rollback aus:
    das originale, unveränderte Set wird zurückgegeben und geloggt.
    """


def _parse_version(version: Any) -> tuple:
    """Parsed eine SemVer-Zeichenkette in (major, minor, patch) – numerisch.

    Robust: None/leer/ungültig → (0, 0, 0). Optionales 'v'-Präfix sowie
    Pre-Release-/Build-Segmente (z. B. '1.2.3-beta.1+build5') werden
    ignoriert. Nur die ersten drei numerischen Segmente zählen.
    """
    if version is None:
        return (0, 0, 0)
    s = str(version).strip()
    if not s:
        return (0, 0, 0)
    if s[:1].lower() == "v":
        s = s[1:]
    core = s.split("+")[0].split("-")[0]
    nums: list = []
    for part in core.split("."):
        try:
            nums.append(int(part))
        except (TypeError, ValueError):
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def _needs_migration(v_old: str, v_new: str) -> bool:
    """True, wenn eine Migration nötig ist (Major-/Minor-Abweichung).

    Reine Patch-Abweichungen (z. B. 1.0.0 -> 1.0.1) lösen KEINE Migration aus.
    Migriert wird ausschließlich, wenn die gespeicherte Version HINTER der
    aktuellen Plugin-Version liegt (Legacy "0.0.0" → immer). Ein Downgrade
    (gespeicherte Version über der Plugin-Version) wird NICHT migriert –
    kein destruktives Rücksetzen lauffähiger Sets.
    """
    old = _parse_version(v_old)
    new = _parse_version(v_new)
    if old[0] < new[0]:
        return True
    if old[0] > new[0]:
        return False
    return old[1] < new[1]


class SchemaMigrator:
    """Migriert Service-Instanz-Konfigurationen gegen das Plugin-Schema."""

    def migrate_instance_config(
        self,
        config: Dict[str, Any],
        plugin: PluginFeature,
    ) -> Dict[str, Any]:
        """Bereitet eine ServiceInstanceConfig für das aktuelle Plugin-Schema auf.

        Args:
            config: ServiceInstanceConfig (plugin_id, lookback, params, ...).
            plugin: Aktuelle PluginFeature-Instanz (plugin.version + Schema).

        Returns:
            Migrierte (tiefe) Kopie der Konfiguration – das Original bleibt
            unverändert (der Aufrufer entscheidet über die Übernahme).

        Raises:
            MigrationError: Bei jedem Fehler während der Aufbereitung –
            der Aufrufer führt dann den Rollback auf das Original aus.
        """
        if plugin is None:
            raise MigrationError("Plugin ist None – Migration nicht möglich.")
        try:
            result: Dict[str, Any] = dict(config or {})
            current_ver = result.get("version") or "0.0.0"
            new_ver = getattr(plugin, "version", "0.0.0") or "0.0.0"

            # Kein Handlungsbedarf: nur Patch-Differenz oder gleiche/höhere
            # Version → Instanz unverändert zurückgeben.
            if not _needs_migration(current_ver, new_ver):
                return result

            schema = plugin.full_parameter_schema()
            params: Dict[str, Any] = dict(result.get("params") or {})

            # 1) Fehlende Schema-Keys mit Default-Werten ergänzen.
            for key, spec in schema.items():
                if key in params:
                    continue
                if "default" in spec:
                    params[key] = spec["default"]

            # 2) Veraltete Keys entfernen, die nicht mehr im Parameter-Schema
            #    enthalten sind (Parameter-Schema = Single Source of Truth).
            known = set(schema.keys())
            for key in list(params.keys()):
                if key not in known:
                    params.pop(key, None)

            result["params"] = params

            # lookback ist Service-Instanz-Einstellung (top-level) und gehört
            # zum Basis-Schema – fehlt er, wird der Schema-Default ergänzt.
            if "lookback" not in result and "lookback" in schema:
                result["lookback"] = int(schema["lookback"].get("default", 1000))

            # 3) Instanz-Version auf die aktuelle Plugin-Version anheben.
            result["version"] = new_ver
            return result
        except MigrationError:
            raise
        except Exception as e:
            raise MigrationError(
                f"Schema-Migration fehlgeschlagen (Instanz "
                f"'{config.get('plugin_id', '?')}'): {e}"
            ) from e

```

--------------------------------------------------

### DATEI: analytics/engine/set_evaluator.py
```py
# analytics/engine/set_evaluator.py
"""
ServiceSetEvaluator – Führt Service-Sets (ServiceSetDefinition, siehe
service_models.py) in execution_order über den PluginExecutor aus.

Phase 15 (Alt-Signal-Rückbau): Der Signal-basierte SetEvaluator (ema_trend_v1 /
atr_filter_v1 / grid_proximity_v1 / alternating_arrow_v1) wurde komplett
entfernt – es gibt keine Signal-Engine mehr.
"""

from dataclasses import replace
from typing import Any, Dict, Optional, Set
import threading
import time
import traceback
import pandas as pd

from analytics.features.plugins.base_plugin import PluginContext, ServiceErrorLog
from analytics.features.feature_builder import (
    PluginExecutor,
    PluginExecutionError,
    PluginExecutionErrorInfo,
)


# ==============================================================================
# ServiceSetEvaluator (Service-Pipeline)
# ------------------------------------------------------------------------------
# Führt Service-Sets (ServiceSetDefinition, siehe service_models.py) in
# execution_order aus.
#
# Kernregeln (Roadmap Phase 13 §3.2):
#   - df.tail(lookback) je Service (exakter Zuschnitt).
#   - shared_state ist mutable, aber strikt per instance_id-Namespace isoliert:
#     context.shared_state[self.instance_id] ist les-/schreibbar; der Evaluator
#     legt zusätzlich das Ergebnis unter der instance_id ab, falls der Service
#     seinen Namespace nicht selbst beschrieben hat.
#   - Abhängigkeiten (depends_on) werden VOR der Ausführung validiert:
#     (1) statisch: alle depends_on-IDs müssen früher in execution_order stehen;
#     (2) runtime:  deren shared_state-Einträge müssen nach deren Ausführung
#                   vorhanden sein (sonst Fail-Fast).
#   - Fail-Fast: Bricht ein Service mit Exception ab, wird die Exception als
#     ServiceSetExecutionError geloggt und die restliche Pipeline übersprungen.
# ==============================================================================


class ServiceSetExecutionError(Exception):
    """Fail-Fast: Ein Service in der Service-Pipeline ist fehlgeschlagen."""


class ServiceSetEvaluator:
    """Sichere Ausführung einer Service-Pipeline mit Namespace-Isolation.

    P14-03 (Resiliente Evaluator-Schleife): execute_set_resilient() ersetzt
    das Fail-Fast-Prinzip durch Skip-Logic, Dependency-Skip, State-Fallback
    und eine RAM-Quarantäne (3 aufeinanderfolgende Fehler → für die Session
    gesperrt; Zähler-Ready nach 300 s ohne Fehler, Quarantäne bleibt bis
    reset()). Die bestehende execute_set()-Methode bleibt unverändert
    (Fail-Fast) und läuft für Bestands-Aufrufer parallel weiter.
    """

    def __init__(self, executor: Optional[PluginExecutor] = None) -> None:
        self.executor = executor or PluginExecutor()
        # P14-03: Session-Zustand (nur RAM, wird NICHT in DuckDB persistiert)
        self._failure_counters: Dict[str, int] = {}
        self._quarantined: Set[str] = set()
        self._last_failure_time: Dict[str, float] = {}
        self._recovery_seconds: float = 300.0
        self._execution_lock = threading.RLock()
        # Diagnose-Status der letzten resilienten Ausführung (instance_id ->
        # skip_reason bzw. strukturiertes Fehlerobjekt).
        self.last_skipped: Dict[str, str] = {}
        self.last_errors: Dict[str, PluginExecutionErrorInfo] = {}

    # -------------------------------------------------------------------------
    # Session-Quarantäne & Auto-Recovery (P14-03, Invariante 4 + 11)
    # -------------------------------------------------------------------------
    def reset(self) -> None:
        """Vollständiger Neustart der Pipeline (Invariante 11): Quarantäne,
        Fehlerzähler und Diagnose-Status werden geleert (Session-Scope)."""
        with self._execution_lock:
            self._failure_counters.clear()
            self._quarantined.clear()
            self._last_failure_time.clear()
            self.last_skipped.clear()
            self.last_errors.clear()

    def _is_quarantined(self, instance_id: str) -> bool:
        """True, wenn die Instanz für die Session quarantänisiert ist.

        Auto-Recovery (Invariante 11): Der Fehlerzähler wird nach
        _recovery_seconds (300 s) ohne weiteren Fehler automatisch
        zurückgesetzt – die einmalige Quarantäne selbst bleibt bis reset()
        bestehen."""
        last = self._last_failure_time.get(instance_id)
        if last is not None and time.time() - last >= self._recovery_seconds:
            self._failure_counters.pop(instance_id, None)
            self._last_failure_time.pop(instance_id, None)
        return instance_id in self._quarantined

    def _record_failure(self, instance_id: str) -> bool:
        """Zählt einen Fehler; bei 3 aufeinanderfolgenden Fehlern wird die
        Instanz quarantänisiert. Gibt True zurück, wenn Quarantäne ausgelöst."""
        now = time.time()
        self._last_failure_time[instance_id] = now
        self._failure_counters[instance_id] = self._failure_counters.get(instance_id, 0) + 1
        if self._failure_counters[instance_id] >= 3:
            self._quarantined.add(instance_id)
            return True
        return False

    def _reset_failure(self, instance_id: str) -> None:
        """Erfolgreiche Ausführung → Fehlerzähler zurücksetzen (nur
        aufeinanderfolgende Fehler zählen)."""
        self._failure_counters.pop(instance_id, None)
        self._last_failure_time.pop(instance_id, None)

    # -------------------------------------------------------------------------
    # Pipeline-Ausführung (bestehender Fail-Fast-Pfad – unverändert)
    # -------------------------------------------------------------------------
    def execute_set(
        self,
        set_definition: Dict[str, Any],
        df: pd.DataFrame,
        context: Optional[PluginContext] = None,
    ) -> Dict[str, Any]:
        """Führt alle Services nacheinander in execution_order aus.

        Args:
            set_definition: ServiceSetDefinition (set_id/display_name werden
                hier nicht benötigt – nur execution_order + services).
            df: OHLCV-DataFrame. Jeder Service bekommt exakt df.tail(lookback).
            context: Optionaler PluginContext. Wenn None, wird ein frischer
                Context mit mode='batch' erzeugt.

        Returns:
            Dict instance_id -> FeatureCalculateResult. Jedes Ergebnis ist
            zusätzlich unter context.shared_state[instance_id] abgelegt
            (Namespace-isoliert), sofern der Service seinen Namespace nicht
            selbst beschrieben hat.

        Raises:
            ValueError: Ungültige execution_order / Abhängigkeits-Verletzung
                (statisch ODER runtime: fehlender shared_state-Eintrag).
            ServiceSetExecutionError: Fail-Fast bei Service-Exception.
        """
        if df is None or df.empty:
            raise ValueError("execute_set: df ist None oder leer")

        execution_order = list(set_definition.get("execution_order") or [])
        services = dict(set_definition.get("services") or {})

        if not execution_order:
            raise ValueError("execute_set: execution_order ist leer")

        missing = [iid for iid in execution_order if iid not in services]
        if missing:
            raise ValueError(
                f"execute_set: instance_ids fehlen in 'services': {missing}")

        if context is None:
            context = PluginContext(mode="batch")

        # --- Statische Abhängigkeits-Validierung VOR der Ausführung ----------
        position = {iid: idx for idx, iid in enumerate(execution_order)}
        for iid, cfg in services.items():
            for dep in (cfg.get("depends_on") or []):
                if dep not in position:
                    raise ValueError(
                        f"execute_set: Service '{iid}' depends_on '{dep}', "
                        f"das nicht in execution_order existiert")
                if position[dep] >= position[iid]:
                    raise ValueError(
                        f"execute_set: Abhängigkeits-Verletzung – Service "
                        f"'{iid}' depends_on '{dep}', aber '{dep}' steht nicht "
                        f"VOR '{iid}' in execution_order (nachgelagerte Referenz)")

        # --- Pipeline-Ausführung (Fail-Fast) ---------------------------------
        results: Dict[str, Any] = {}
        for iid in execution_order:
            cfg = services[iid]
            plugin_id = cfg["plugin_id"]
            lookback = int(cfg.get("lookback") or len(df))
            params = dict(cfg.get("params") or {})

            # Runtime-Check: abhängige shared_state-Einträge müssen nach deren
            # Ausführung vorhanden sein (sonst Fail-Fast VOR diesem Service).
            for dep in (cfg.get("depends_on") or []):
                if dep not in context.shared_state:
                    raise ValueError(
                        f"execute_set: Service '{iid}' erwartet "
                        f"shared_state['{dep}'], aber der Eintrag fehlt "
                        f"(abhängiger Service lief nicht oder schrieb nichts)")

            # Exakter Zuschnitt auf den Service-lookback
            service_df = df.tail(lookback)

            # Context je Service: instance_id + depends_on setzen (Namespace).
            # replace() erzeugt eine flache Kopie – shared_state (dict) bleibt
            # DASSELBE Objekt, ist also über alle Services hinweg sichtbar.
            service_ctx = replace(
                context,
                instance_id=iid,
                depends_on=list(cfg.get("depends_on") or []),
            )

            try:
                result = self.executor.execute(
                    plugin_id, service_df, params, context=service_ctx)
            except Exception as e:
                raise ServiceSetExecutionError(
                    f"execute_set: Service '{iid}' (plugin '{plugin_id}') "
                    f"fehlgeschlagen – Pipeline abgebrochen: {e}") from e

            # Namespace-Isolation: Ergebnis unter der instance_id ablegen.
            # Hat der Service seinen Namespace bereits selbst beschrieben
            # (z.B. GridLinesService schreibt Linienliste), wird NICHT
            # überschrieben – die Linien bleiben für abhängige Services lesbar.
            if iid not in context.shared_state:
                context.shared_state[iid] = result
            results[iid] = result

        return results

    # -------------------------------------------------------------------------
    # P14-03: Resiliente Pipeline-Ausführung (Skip-Logic / Dependency-Skip /
    # State-Fallback / Session-Quarantäne)
    # -------------------------------------------------------------------------
    def execute_set_resilient(
        self,
        set_definition: Dict[str, Any],
        df: pd.DataFrame,
        context: Optional[PluginContext] = None,
    ) -> Dict[str, Any]:
        """Führt die Service-Pipeline elastisch aus (P14-03) – Ablösung des
        strikten Fail-Fast-Prinzips (A.3/A.4 des Kapitels):

        * Skip-Logic: Schlägt ein unkritischer Service fehl, wird er geloggt
          (strukturiertes Fehlerobjekt unter self.last_errors) und mit
          skip_reason in self.last_skipped markiert. Unabhängige Services
          laufen weiter.
        * Dependency-Skip: Services, die per depends_on von der fehlerhaften
          instance_id abhängen, werden mit skip_reason="dependency_failed"
          übersprungen.
        * State-Fallback: Der shared_state-Eintrag der VORHERIGEN Kerze einer
          fehlgeschlagenen Instanz bleibt unangetastet erhalten – der Aufrufer
          kann exklusiv darüber auf den letzten guten Zustand zugreifen
          (EvaluationContext.shared_state.get(instance_id)).
        * RAM-Quarantäne: 3 aufeinanderfolgende Fehler einer Instanz →
          quarantäne (nur RAM, keine DB-Persistenz); Zähler-Ready nach 300 s
          ohne Fehler (Invariante 11), Quarantäne bleibt bis reset().

        Der Rückgabewert enthält ausschließlich erfolgreiche Ausführungen
        (Dict instance_id -> FeatureCalculateResult) – identische Struktur wie
        execute_set(). Diagnose über self.last_skipped / self.last_errors.

        Raises:
            ValueError: Ungültige execution_order / statische
                Abhängigkeits-Verletzung (wie execute_set).
        """
        if df is None or df.empty:
            raise ValueError("execute_set_resilient: df ist None oder leer")

        execution_order = list(set_definition.get("execution_order") or [])
        services = dict(set_definition.get("services") or {})

        if not execution_order:
            raise ValueError("execute_set_resilient: execution_order ist leer")

        missing = [iid for iid in execution_order if iid not in services]
        if missing:
            raise ValueError(
                f"execute_set_resilient: instance_ids fehlen in 'services': {missing}")

        if context is None:
            context = PluginContext(mode="batch")

        # --- Statische Abhängigkeits-Validierung VOR der Ausführung ----------
        position = {iid: idx for idx, iid in enumerate(execution_order)}
        for iid, cfg in services.items():
            for dep in (cfg.get("depends_on") or []):
                if dep not in position:
                    raise ValueError(
                        f"execute_set_resilient: Service '{iid}' depends_on "
                        f"'{dep}', das nicht in execution_order existiert")
                if position[dep] >= position[iid]:
                    raise ValueError(
                        f"execute_set_resilient: Abhängigkeits-Verletzung – "
                        f"Service '{iid}' depends_on '{dep}', aber '{dep}' "
                        f"steht nicht VOR '{iid}' in execution_order")

        # --- Resiliente Pipeline-Ausführung (Skip-Logic) ---------------------
        results: Dict[str, Any] = {}
        with self._execution_lock:
            self.last_skipped.clear()
            self.last_errors.clear()
            for iid in execution_order:
                # Quarantäne-Skip (Session-Scope, RAM only)
                if self._is_quarantined(iid):
                    self.last_skipped[iid] = "quarantined"
                    print(f"WARN [ServiceSetEvaluator] Service '{iid}' "
                          f"uebersprungen (quarantined)")
                    continue

                cfg = services[iid]
                plugin_id = cfg["plugin_id"]
                lookback = int(cfg.get("lookback") or len(df))
                params = dict(cfg.get("params") or {})

                # Dependency-Skip: abhängige Instanz fehlgeschlagen oder
                # quarantänisiert → kontrolliert überspringen.
                dep_failed = False
                for dep in (cfg.get("depends_on") or []):
                    if dep in self.last_skipped or dep in self._quarantined:
                        self.last_skipped[iid] = "dependency_failed"
                        print(f"WARN [ServiceSetEvaluator] Service '{iid}' "
                              f"uebersprungen (dependency_failed: '{dep}')")
                        dep_failed = True
                        break
                if dep_failed:
                    continue

                # Exakter Zuschnitt auf den Service-lookback
                service_df = df.tail(lookback)

                # Context je Service: instance_id + depends_on setzen (Namespace).
                service_ctx = replace(
                    context,
                    instance_id=iid,
                    depends_on=list(cfg.get("depends_on") or []),
                )

                try:
                    result = self.executor.execute(
                        plugin_id, service_df, params, context=service_ctx)
                except PluginExecutionError as e:
                    self.last_errors[iid] = e.info
                    quarantined_now = self._record_failure(iid)
                    self.last_skipped[iid] = "quarantined" if quarantined_now else "error"
                    # P14-03 (Schritt 2.2): Logging über das strukturierte
                    # ServiceErrorLog-TypedDict (maschinelle Auswertung).
                    log: ServiceErrorLog = e.info.to_service_error_log()
                    print(
                        f"WARN [ServiceSetEvaluator] Service '{iid}' "
                        f"(plugin '{log['plugin_id']}') fehlgeschlagen: "
                        f"{log['exception']} "
                        f"(Fehler #{self._failure_counters.get(iid, 0)})"
                    )
                    if quarantined_now:
                        print(f"WARN [ServiceSetEvaluator] Service '{iid}' fuer "
                              f"die Session quarantaenisiert (RAM only)")
                    # State-Fallback: alter shared_state-Eintrag (vorherige
                    # Kerze) bleibt unangetastet erhalten.
                    continue
                except Exception as e:
                    # Sicherheitsnetz: PluginExecutor kapselt eigentlich alle
                    # Fehler – hier trotzdem defensiv absichern.
                    info = PluginExecutionErrorInfo(
                        timestamp=time.time(),
                        plugin_id=plugin_id,
                        instance_id=iid,
                        symbol=str(getattr(context, "symbol", "") or ""),
                        timeframe=str(getattr(context, "timeframe", "") or ""),
                        bar_time=getattr(context, "timestamp", None),
                        stage="execute_set_resilient",
                        exception_type=type(e).__name__,
                        exception_message=str(e),
                        traceback=traceback.format_exc(),
                    )
                    self.last_errors[iid] = info
                    quarantined_now = self._record_failure(iid)
                    self.last_skipped[iid] = "quarantined" if quarantined_now else "error"
                    log2: ServiceErrorLog = info.to_service_error_log()
                    print(f"WARN [ServiceSetEvaluator] Service '{iid}' "
                          f"(plugin '{log2['plugin_id']}') fehlgeschlagen: "
                          f"{log2['exception']}")
                    continue

                # Erfolg → Fehlerzähler zurücksetzen, Diagnose-Status bereinigen.
                self._reset_failure(iid)
                self.last_skipped.pop(iid, None)
                self.last_errors.pop(iid, None)

                # Namespace-Isolation (wie execute_set): Ergebnis ablegen, falls
                # der Service seinen Namespace nicht selbst beschrieben hat.
                if iid not in context.shared_state:
                    context.shared_state[iid] = result
                results[iid] = result

        return results

```

--------------------------------------------------

### DATEI: analytics/engine/tree_builder.py
```py
# analytics/engine/tree_builder.py
"""
analytics/engine/tree_builder.py - Rekursiver Baumaufbau der Service-Hierarchie.

Ausgelagert aus service_selector_model.py im Rahmen von 18.01.02 (E6): alle
Baum-Konstruktions- und Kategorie-Aufloesungsfunktionen als REINE Modul-
Funktionen (kein Klassenzustand, keine Qt-Signale, kein Import von
ServiceSelectorModel – keine Zirkularitaet).

Eingangsdaten (Sets, Plugins, Kategorie-Overrides, Empty-Folder-Pfade,
Badges, Last-Execution-Daten) werden als Parameter uebergeben. Der
ServiceSelectorModel bleibt die oeffentliche API und delegiert hierher
(dünne Wrapper).

Gruppen-Kennungen (Spiegel der ServiceSelectorModel-Konstanten):
  * GROUP_SETS = "sets"      – Root-Gruppe '📁 Sets'
  * GROUP_PLUGINS = "plugins" – Root-Gruppe '📦 Services'
  * GROUP_CATEGORY = "category_node" – 📁-Ordner-Knoten
"""

from typing import Any, Dict, List, Optional

#: Root-Gruppe der gespeicherten Service-Sets.
GROUP_SETS = "sets"
#: Root-Gruppe aller registrierten Plugins/Services.
GROUP_PLUGINS = "plugins"
#: Kategorie-Ordner-Knoten (Dynamic Category Trees).
GROUP_CATEGORY = "category_node"
# 20.04 (Q6): Label des dynamischen Archiv-Ordners. Enthaelt archivierte
# Knoten (is_archived=True / Presets mit is_active_batch=False) – alle
# darin liegenden Knoten sind non-checkable (Archive Safety).
ARCHIVE_LABEL = "📁 Archiv"


# ------------------------------------------------------------------
# Kategorie-Bausteine (K1/K2/K8/K9)
# ------------------------------------------------------------------
def _cat_key(label: str) -> str:
    """Case-insensitiver Sortier-/Vergleichsschluessel eines Ordners.

    Entfernt das '📁 '-Praefix des Ordnerlabels (K2-Format), damit
    Sortierung (K8) und Pfad-Lookup stabil auf dem reinen Namen laufen.
    """
    s = str(label or "").strip()
    if s.startswith("📁"):
        s = s[len("📁"):].lstrip()
    return s.lower()


def _category_parts(plugin_id: str, plugin: Optional[Any],
                    overrides: Dict[str, str]) -> List[str]:
    """Kategorienpfad eines Plugins (K1, 16.08 / 18.01.03 E1).

    Ein gesetzter Kategorie-Override (global_settings, Key
    'plugin_category_<plugin_id>', Quelle des Drag & Drop) hat VORRANG vor
    `metadata['category']` – auch ein leerer String "" hebt die metadata-
    Kategorie auf (Root-Ebene). Ohne Override gilt das metadata-Feld wie
    bisher. Leer ODER der Ist-Default `"General"` (base_plugin.py) gelten
    als "keine Kategorie" -> das Plugin bleibt auf der obersten Ebene der
    Hauptgruppe.
    """
    category = ""
    if plugin_id:
        override = overrides.get(str(plugin_id).lower())
        if override is not None:
            category = str(override or "").strip()
    if not category:
        try:
            meta = getattr(plugin, "metadata", None) or {}
            category = str(meta.get("category") or "").strip()
        except Exception:
            category = ""
    if not category or category.lower() == "general":
        return []
    return [p.strip() for p in category.split("/") if p.strip()]


def _insert_into_category_tree(nodes: List[Dict[str, Any]],
                               parts: List[str],
                               leaf: Dict[str, Any]) -> None:
    """Fuegt ein Plugin-Blatt rekursiv in die Ordnerstruktur ein (K2).

    Erzeugt fehlende Ordner entlang des Pfads. Ordner entstehen NUR
    durch eine tatsaechliche Blatt-Einfuegung -> keine leeren Ordner
    (K9). Ordner-Label folgt dem K2-Format '📁 <Name>'.
    """
    if not parts:
        nodes.append(leaf)
        return
    key = _cat_key(parts[0])
    folder = None
    for n in nodes:
        if (n.get("group") == GROUP_CATEGORY
                and _cat_key(n.get("label")) == key):
            folder = n
            break
    if folder is None:
        folder = {"group": GROUP_CATEGORY,
                  "label": f"📁 {parts[0]}", "children": []}
        nodes.append(folder)
    _insert_into_category_tree(folder["children"], parts[1:], leaf)


def _sort_category_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sortiert eine Ordner-Ebene (K8, 16.08 / 18.01.03).

    Deterministisch: Ordner zuerst, dann Blaetter; jeweils alphabetisch
    (case-insensitiv). Innerhalb der Ordner rekursiv dieselbe Regel.
    Blaetter koennen sowohl Plugin-Dicts ({plugin_id, ...}) als auch
    Sets-Dicts ({set_id, display_name, ...}) sein – als Sortiername gilt
    plugin_id, sonst display_name/set_id.
    """
    def sort_key(n: Dict[str, Any]) -> tuple:
        is_folder = n.get("group") == GROUP_CATEGORY
        if is_folder:
            name = _cat_key(n.get("label"))
            # 20.04 (Q6): '📁 Archiv' immer ans ENDE der Gruppe (nach allen
            # normalen Ordnern UND Blaettern) – markiert ueber 'archived'.
            if n.get("archived"):
                return (2, name)
            return (0, name)
        else:
            name = str(n.get("plugin_id")
                       or n.get("display_name")
                       or n.get("set_id") or "").lower()
        return (0 if is_folder else 1, name)

    result = sorted(nodes, key=sort_key)
    for n in result:
        if n.get("group") == GROUP_CATEGORY:
            n["children"] = _sort_category_nodes(n.get("children") or [])
    return result


def _set_category_parts(definition: Dict[str, Any]) -> List[str]:
    """Kategorienpfad eines Service-Sets (18.01.03, E2).

    Lese das optionale Feld `category` der Set-Definition (Slash-Pfad,
    z.B. 'Swing Points/Geometrie'). Leer ODER der Ist-Default "General"
    gelten als "keine Kategorie" -> das Set bleibt auf der obersten
    Ebene der Sets-Gruppe (Spiegel der Plugin-Logik K1).
    """
    category = str((definition or {}).get("category") or "").strip()
    if not category or category.lower() == "general":
        return []
    return [p.strip() for p in category.split("/") if p.strip()]


def _insert_set_into_category_tree(nodes: List[Dict[str, Any]],
                                   parts: List[str],
                                   leaf: Dict[str, Any]) -> None:
    """Fuegt ein Set-Blatt rekursiv in die Ordnerstruktur ein (18.01.03).

    Analoge Mechanik zu `_insert_into_category_tree` (K2), aber fuer
    Sets-Blatt-Dicts ({set_id, display_name, definition, services}).
    Ordner entstehen NUR durch eine tatsaechliche Blatt-Einfuegung ->
    keine leeren Ordner (K9).
    """
    if not parts:
        nodes.append(leaf)
        return
    key = _cat_key(parts[0])
    folder = None
    for n in nodes:
        if (n.get("group") == GROUP_CATEGORY
                and _cat_key(n.get("label")) == key):
            folder = n
            break
    if folder is None:
        folder = {"group": GROUP_CATEGORY,
                  "label": f"📁 {parts[0]}", "children": []}
        nodes.append(folder)
    _insert_set_into_category_tree(folder["children"], parts[1:], leaf)


def _ensure_category_path(nodes: List[Dict[str, Any]],
                          parts: List[str]) -> None:
    """Stellt sicher, dass die Ordnerkette fuer `parts` existiert
    (18.01.03, E3-revidiert).

    Erzeugt fehlende Ordner entlang des Pfads OHNE Blatt-Einfuegung
    (K2-Format '📁 <Name>', children leer). Dient der Einmischung
    persistierter benutzererzeugter (ggf. leerer) Ordner in build_tree():
    Ein bereits vorhandener Ordner (aus echten Blatt-Kategorien) wird
    wiederverwendet – kein Duplikat, keine Kinder-Aenderung.
    """
    if not parts:
        return
    key = _cat_key(parts[0])
    folder = None
    for n in nodes:
        if (n.get("group") == GROUP_CATEGORY
                and _cat_key(n.get("label")) == key):
            folder = n
            break
    if folder is None:
        folder = {"group": GROUP_CATEGORY,
                  "label": f"📁 {parts[0]}", "children": []}
        nodes.append(folder)
    _ensure_category_path(folder["children"], parts[1:])


def _clones_for(presets: Optional[Dict[str, List[Dict[str, Any]]]],
                plugin_id: str) -> List[Dict[str, Any]]:
    """Preset-/Clone-Liste eines Plugins (20.04, Q7) oder [].

    `presets` mappt plugin_id.lower() -> Liste von
    {"preset_name", "params", "instance_hash", "is_archived"}. Plugins
    ohne Eintrag liefern [] (keine Clones -> flaches Blatt).
    """
    if not presets:
        return []
    key = str(plugin_id or "").lower()
    clones = presets.get(key)
    if not clones:
        clones = presets.get(str(plugin_id or ""))
    return list(clones or [])


def _category_nodes(plugin_ids: List[str],
                    plugins: Dict[str, Any],
                    overrides: Dict[str, str],
                    badges: Dict[str, str],
                    last_executions: Dict[str, str],
                    presets: Optional[Dict[str, List[Dict[str, Any]]]] = None
                    ) -> List[Dict[str, Any]]:
    """Baut die (ggf. verschachtelte) Kinderliste einer Plugin-Gruppe.

    Plugins mit Kategorienpfad werden in 📁-Ordner einsortiert; Plugins
    ohne Kategorie (bzw. Default 'General') bleiben auf oberster Ebene
    (K1). Blatt-Dicts unveraendert ({plugin_id, badge, last_execution}).
    Sortierung pro Ebene: Ordner vor Blaettern, alphabetisch (K8).

    20.04 (Q7): Plugins MIT Presets/Clones werden als Parent-Knoten
    gerendert – das Blatt-Dict erhaelt zusaetzlich `clones` (Liste der
    AKTIVEN Clones, is_archived=False). Plugins OHNE Presets bleiben
    flache Blaetter (Blatt-Struktur identisch, Zero-Regression). Die
    ARCHIVIERTEN Clones (is_archived=True) wandern in den dynamischen
    '📁 Archiv'-Ordner (Q6, Archiv-Einheit: einzelne Clone) – das
    Archiv-Blatt traegt das 'archived'-Flag (non-checkable im MasterTree).
    """
    root: List[Dict[str, Any]] = []
    archive_entries: List[Dict[str, Any]] = []
    for pid in plugin_ids:
        plugin = plugins.get(pid)
        parts = _category_parts(pid, plugin, overrides)
        clones = _clones_for(presets, pid)
        leaf = {
            "plugin_id": pid,
            "badge": badges.get(pid, ""),
            "last_execution": last_executions.get(pid, "--.--.--"),
        }
        if not clones:
            # Plugin ohne Presets: flaches Blatt (Bestandsverhalten).
            _insert_into_category_tree(root, parts, leaf)
            continue
        active = [c for c in clones if not c.get("is_archived")]
        archived = [c for c in clones if c.get("is_archived")]
        if active:
            leaf_with_clones = dict(leaf, clones=active)
            _insert_into_category_tree(root, parts, leaf_with_clones)
        if archived:
            archive_entries.append(dict(
                leaf, clones=archived, archived=True))
    if archive_entries:
        archive_folder: Dict[str, Any] = {
            "group": GROUP_CATEGORY,
            "label": ARCHIVE_LABEL,
            "children": sorted(
                archive_entries,
                key=lambda e: str(e.get("plugin_id") or "").lower()),
            "archived": True,
        }
        root.append(archive_folder)
    return _sort_category_nodes(root)


# ------------------------------------------------------------------
# Kategorie-Aufloesung
# ------------------------------------------------------------------
def category_plugin_ids(plugins: Dict[str, Any],
                        overrides: Dict[str, str],
                        category_path: str) -> List[str]:
    """Alle Plugin-IDs unter einem Kategorie-Pfad (rekursiv, 17.01.02).

    Liefert deterministisch (alphabetisch) alle Plugins, deren Kategorie-
    Pfad mit `category_path` beginnt – d.h. auch Plugins in UNTER-Ordnern
    (z.B. Pfad 'Swing Points' liefert auch Plugins aus 'Swing Points/
    Geometrie'). Pfad-Format: slash-separiert OHNE '📁 '-Praefixe
    (z.B. 'Swing Points/Geometrie'), case-insensitiv.

    Grundlage fuer:
      * Kontextmenue '▶️ Alle Services ausführen' auf Ordner-Knoten
        (run_category_requested).
      * Info-Button auf Ordner-Knoten (category_info_requested).
    """
    target = [p.strip().lower() for p in str(category_path or "").split("/")
              if p.strip()]
    if not target:
        return []
    result: List[str] = []
    for pid in sorted(plugins.keys()):
        parts = [p.lower() for p in _category_parts(pid, plugins.get(pid),
                                                    overrides)]
        if len(parts) >= len(target) and parts[:len(target)] == target:
            result.append(pid)
    return result


def _find_set(sets_data: List[Dict[str, Any]], set_id: str) -> Optional[Dict[str, Any]]:
    """Liefert die Set-Definition zur set_id (oder None)."""
    for s in sets_data:
        if s.get("set_id") == set_id:
            return s
    return None


def category_set_ids(sets_data: List[Dict[str, Any]],
                     category_path: str) -> List[str]:
    """Alle set_ids unter einem Kategorie-Pfad (rekursiv, 18.01.03).

    Liefert deterministisch (Set-Reihenfolge = display_name) alle Sets,
    deren `category`-Pfad mit `category_path` beginnt – d.h. auch Sets in
    UNTER-Ordnern (z.B. Pfad 'Swing Points' liefert auch Sets aus
    'Swing Points/Geometrie'). Pfad-Format: slash-separiert OHNE
    '📁 '-Praefixe, case-insensitiv. Analog `category_plugin_ids` fuer
    die Sets-Gruppe.
    """
    target = [p.strip().lower() for p in str(category_path or "").split("/")
              if p.strip()]
    if not target:
        return []
    result: List[str] = []
    for s in sorted(sets_data, key=lambda x: str(
            x.get("display_name") or x.get("set_id") or "").lower()):
        parts = [p.lower() for p in _set_category_parts(s)]
        if len(parts) >= len(target) and parts[:len(target)] == target:
            result.append(str(s.get("set_id") or ""))
    return result


def plugin_category_path(plugin_id: str, plugin: Optional[Any],
                         overrides: Dict[str, str]) -> str:
    """Aktueller Kategorie-Pfad eines Plugins (lesend, 18.01.03).

    Liefert den voll aufgeloesten Pfad (Override -> metadata['category'])
    slash-separiert OHNE '📁 '-Praefix (z.B. 'Swing Points/Geometrie');
    leer = Root-Ebene. Ist das Plugin nicht registriert, gilt leer
    (Spiegel der Original-Semantik: Override wird nur bei vorhandenem
    Plugin ausgewertet).
    """
    if not plugin_id:
        return ""
    parts = _category_parts(plugin_id, plugin, overrides) if plugin else []
    return "/".join(parts)


def category_service_plugin_ids(group: str,
                                sets_data: List[Dict[str, Any]],
                                plugins: Dict[str, Any],
                                overrides: Dict[str, str],
                                category_path: str) -> List[str]:
    """Alle plugin_ids unter einem Kategorie-Ordner (rekursiv, 18.01.03).

    Gruppenspezifische Aufloesung (L3):
      * group == GROUP_SETS    -> Sets unter dem Pfad
        (category_set_ids), dann alle plugin_ids ihrer Services
        (execution_order, dedupliziert, deterministisch).
      * group == GROUP_PLUGINS -> Plugins unter dem Pfad
        (category_plugin_ids).
    Leerer Pfad/leere Gruppe -> [] (defensiv). Wird von den Run-/Info-
    Aktionen des ServiceWindow und der Picker-Aufloesung genutzt.
    """
    if str(group or "") == str(GROUP_SETS):
        ids: List[str] = []
        for set_id in category_set_ids(sets_data, category_path):
            definition = _find_set(sets_data, set_id) or {}
            services = definition.get("services") or {}
            order = definition.get("execution_order") \
                or list(services.keys())
            for iid in order:
                cfg = services.get(iid) or {}
                pid = str(cfg.get("plugin_id") or iid)
                if pid and pid not in ids:
                    ids.append(pid)
        return ids
    return category_plugin_ids(plugins, overrides, category_path)


# ------------------------------------------------------------------
# Baumaufbau
# ------------------------------------------------------------------
def build_tree(sets_data: List[Dict[str, Any]],
               plugins: Dict[str, Any],
               overrides: Dict[str, str],
               empty_folders: Dict[str, List[str]],
               badges: Dict[str, str],
               last_executions: Dict[str, str],
               presets: Optional[Dict[str, List[Dict[str, Any]]]] = None
               ) -> List[Dict[str, Any]]:
    """Baut die vollstaendige Hierarchie fuer das 2-Spalten-MasterTree.

    17.01.01: NUR noch 2 Root-Gruppen – die ehemalige Gruppe
    '⚡ Standalone Services' (GROUP_STANDALONE) entfaellt ersatzlos, da
    alle Plugins ueber metadata['category'] in Ordner einsortiert werden.
    Root-Label kompakt: '📁 Sets' und '📦 Services'.

    20.04 (Q6/Q7): Plugins MIT Presets werden als Parent-Knoten mit
    Clone-Kindern gerendert (`clones` im Blatt-Dict); archivierte Clones
    bzw. archivierte Sets/Instanzen (is_archived=True) wandern in den
    dynamischen '📁 Archiv'-Ordner (per 'archived'-Flag markiert,
    non-checkable im MasterTree).

    Rueckgabe (pro Gruppe ein Dict):
        [{"group": "sets", "label": "📁 Sets", "children": [
             {"set_id": ..., "display_name": ..., "definition": {...},
              "services": [{"instance_id": ..., "plugin_id": ...,
                            "badge": ...}, ...]}, ...]},
         {"group": "plugins", "label": "📦 Services",
          "children": [Blatt- und/oder Ordner-Knoten ...]}]

    Deterministisch sortiert (Sets nach display_name; Plugins/Ordner
    alphabetisch, 16.08 K8; '📁 Archiv' immer am Ende). Die Kinder der
    Plugin-Gruppen sind eine Mischung aus flachen Blatt-Dicts
    ({plugin_id, badge, last_execution}) und verschachtelten Ordner-Dicts
    ({"group": GROUP_CATEGORY, "label": "📁 <Name>", "children": [...]} –
    rekursiv), gesteuert ueber das Metadaten-Feld `category` der Plugins
    (K1). Dieselbe Ordner-Mechanik gilt fuer die Sets-Gruppe (18.01.03):
    Set-Definitionen mit `category`-Feld werden in identische Ordner-Dicts
    einsortiert, Sets ohne Kategorie bleiben flache Blaetter. Seit 18.01.03
    (E3-revidiert) werden zusaetzlich benutzererzeugte (ggf. leere) Ordner
    aus `empty_folders` (global_settings Key 'tree_folders_<group>') in die
    Gruppen-Kinder eingemischt – leere Ordner bleiben ueber Refreshs
    erhalten und verschwinden NUR bei manueller Loeschung im Kontextmenue.
    """
    sets = sorted(sets_data,
                  key=lambda s: str(s.get("display_name") or s.get("set_id") or "").lower())
    # Sets-Kategorien (Dynamic Category Trees fuer GROUP_SETS). Set-
    # Definitionen mit `category`-Pfad werden in 📁-Ordner einsortiert
    # (rekursiv, gleiche K2/K8/K9-Regeln wie die Plugins); ohne Kategorie
    # bleiben sie flache Blaetter auf oberster Ebene.
    set_nodes: List[Dict[str, Any]] = []
    # 20.04 (Q6): Archivierte Sets/Instanzen (is_archived=True) – sie
    # wandern in den '📁 Archiv'-Ordner der Sets-Gruppe (non-checkable).
    archive_set_nodes: List[Dict[str, Any]] = []
    for s in sets:
        services = s.get("services") or {}
        order = s.get("execution_order") or []
        set_archived = bool(s.get("is_archived"))
        service_nodes: List[Dict[str, Any]] = []
        archived_service_nodes: List[Dict[str, Any]] = []
        for iid in order:
            cfg = services.get(iid) or {}
            pid = str(cfg.get("plugin_id") or iid)
            svc_node = {
                "instance_id": iid,
                "plugin_id": pid,
                "badge": badges.get(pid, ""),
                "last_execution": last_executions.get(pid, "--.--.--"),
                "instance_hash": str(cfg.get("instance_hash") or ""),
                "is_archived": bool(cfg.get("is_archived")),
                "doc_log": str(cfg.get("doc_log") or ""),
                "params": cfg.get("params") or {},
            }
            if set_archived or svc_node["is_archived"]:
                archived_service_nodes.append(svc_node)
            else:
                service_nodes.append(svc_node)
        set_leaf = {
            "set_id": s.get("set_id"),
            "display_name": s.get("display_name") or s.get("set_id") or "Unbenannt",
            "definition": s,
            "services": service_nodes,
        }
        if set_archived:
            # Ganzes Set archiviert -> komplett in den Archiv-Ordner.
            archive_set_nodes.append(dict(set_leaf, archived=True))
        else:
            _insert_set_into_category_tree(
                set_nodes, _set_category_parts(s), set_leaf)
            # 20.04 (Q6): Einzeln archivierte Instanzen eines AKTIVEN Sets
            # erscheinen als eigene Eintraege im Archiv-Ordner (Anzeige
            # '<Set> / <instance_id>').
            for svc_node in archived_service_nodes:
                archive_set_nodes.append({
                    "set_id": s.get("set_id"),
                    "display_name": f"{s.get('display_name') or s.get('set_id') or 'Unbenannt'} / {svc_node['instance_id']}",
                    "definition": s,
                    "services": [svc_node],
                    "archived": True,
                })
    set_nodes = _sort_category_nodes(set_nodes)

    # EINE kategorisierte Services-Gruppe – Plugins mit `category`-Metadatum
    # werden in 📁-Ordner verschachtelt (K1), ohne Kategorie bleiben sie
    # flache Blaetter auf oberster Ebene. Die fruehere Standalone-Gruppe
    # (separate Knoten) ist entfallen. 20.04 (Q7): presets steuern die
    # Parent-Child-Clone-Ansicht + den Archiv-Ordner.
    plugin_nodes = _category_nodes(sorted(plugins.keys()), plugins,
                                   overrides, badges, last_executions,
                                   presets)

    # 18.01.03 (E3-revidiert): Persistierte benutzererzeugte (ggf. leere)
    # Ordner in die Gruppen-Kinder einmischen – leere Ordner verschwinden
    # damit NICHT beim Refresh, sondern nur bei manueller Loeschung
    # (Kontextmenue 'Ordner löschen'). Bereits vorhandene Ordner (aus
    # echten Blatt-Kategorien) werden wiederverwendet (kein Duplikat).
    for group, nodes in ((GROUP_SETS, set_nodes), (GROUP_PLUGINS, plugin_nodes)):
        for path in empty_folders.get(group, []) or []:
            parts = [p.strip() for p in str(path or "").split("/")
                     if p.strip()]
            if parts:
                _ensure_category_path(nodes, parts)

    # 20.04 (Q6): Archiv-Ordner der Sets-Gruppe (falls vorhanden) ans Ende.
    if archive_set_nodes:
        archive_set_nodes.sort(
            key=lambda n: str(n.get("display_name") or "").lower())
        set_nodes.append({
            "group": GROUP_CATEGORY,
            "label": ARCHIVE_LABEL,
            "children": archive_set_nodes,
            "archived": True,
        })
    set_nodes = _sort_category_nodes(set_nodes)
    plugin_nodes = _sort_category_nodes(plugin_nodes)

    return [
        {"group": GROUP_SETS, "label": "📁 Sets", "children": set_nodes},
        {"group": GROUP_PLUGINS, "label": "📦 Services",
         "children": plugin_nodes},
    ]

```

--------------------------------------------------

### DATEI: analytics/features/__init__.py
```py

```

--------------------------------------------------

### DATEI: analytics/features/base_feature.py
```py
# analytics/features/base_feature.py
"""
Basisklasse für alle Feature-Definitionen im Feature Store.
Jedes Feature erbt von BaseFeature und implementiert calculate().
Unterstützt Single-Spalten (pd.Series) und Multi-Spalten (pd.DataFrame) Rückgaben.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Union
import pandas as pd


class BaseFeature(ABC):
    """Abstrakte Basisklasse für Feature-Berechnungen."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Eindeutiger Spaltenname im feature_store (z. B. 'ema_diff')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Menschleserliche Beschreibung."""
        pass

    @property
    def column_names(self) -> List[str]:
        """
        Gibt die Liste der Spaltennamen zurück, die dieses Feature erzeugt.
        Default: [self.name] für Single-Spalten-Features.
        Überschreiben für Multi-Spalten-Features.
        """
        return [self.name]

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Union[pd.Series, pd.DataFrame]:
        """
        Berechnet das Feature auf einem OHLCV-DataFrame.
        
        Kann entweder eine pd.Series (Single-Spalte) oder ein pd.DataFrame 
        (Multi-Spalten) zurückgeben.
        
        Args:
            df: OHLCV-DataFrame mit bar_time, open, high, low, close, tick_volume
            params: Feature-spezifische Parameter
        
        Returns:
            pd.Series oder pd.DataFrame mit demselben Index wie df
        """
        return self._calculate(df, params)

    @abstractmethod
    def _calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Union[pd.Series, pd.DataFrame]:
        """Interne Berechnungslogik. Subklassen implementieren diese Methode."""
        pass

```

--------------------------------------------------

### DATEI: analytics/features/feature_builder.py
```py
# analytics/features/feature_builder.py
"""
Feature Builder – Lädt OHLCV aus market_data.duckdb, berechnet Features
(grid_levels, Phase 11) vektorisiert und schreibt sie per Bulk-Upsert in
analytics.duckdb.

19.02 (Cleanup): Die Legacy-Native-Spalten ema_diff/atr_normalized wurden
entfernt. Services persistieren ihre Werte ausschliesslich ueber
feature_data (JSON, store_plugin_payload); der native Feature-Builder-Pfad
liefert nur noch die Grid-Level-Spalten.

Stabiler Basis-Stand + Phase-11-Erweiterung: grid_levels (Y-Achsen-Grid-Levels
und X-Achsen-Zeitfenster-Flags), gekapselt in analytics/features/definitions/.
"""

from typing import Any, Dict, List, Optional, Tuple
import importlib
import inspect
import json
import pkgutil
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analytics.features.base_feature import BaseFeature
from analytics.features.definitions.grid_levels import GridLevelsFeature
from analytics.features.plugins.base_plugin import (
    PluginFeature,
    FeatureCalculateResult,
    PluginContext,
    ServiceErrorLog,
)
from state_manager import StateManager
from db_service import DbPool

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DB_MARKET = str(DATA_DIR / "market_data.duckdb")
DB_ANALYTICS = str(DATA_DIR / "analytics.duckdb")


def _feature_store_conflict_target(con) -> str:
    """Liefert den ON CONFLICT-Zielspalten-String passend zum aktuellen PK
    der feature_store-Tabelle (11.08.2026, Bugfix Varianten-Kollision):

    * PK (symbol, timeframe, bar_time, feature_id, instance_hash) nach der
      Migration -> 5-Spalten-Target (Varianten koexistieren pro Bar).
    * Alt-PK (4 Spalten, Migration nicht gelaufen) -> 4-Spalten-Target
      (Bestandsverhalten, kein Write-Bruch).

    Defensiv: Fehler -> 4-Spalten-Target.
    """
    try:
        rows = con.execute(
            "SELECT constraint_column_indexes FROM duckdb_constraints() "
            "WHERE table_name='feature_store' "
            "AND constraint_type='PRIMARY KEY'").fetchall()
        if rows:
            idxs = rows[0][0] or []
            cols = [r[0].lower() for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='feature_store' ORDER BY ordinal_position"
            ).fetchall()]
            if any(cols[i].lower() == "instance_hash" for i in idxs):
                return "(symbol, timeframe, bar_time, feature_id, instance_hash)"
    except Exception:
        pass
    return "(symbol, timeframe, bar_time, feature_id)"


def _timestamp_to_epoch(value: Any) -> int:
    """Konvertiert pandas Timestamp / datetime in epoch-Sekunden (int).
    Int/Float-Werte (bereits epoch-Sekunden) werden unveraendert uebernommen."""
    if hasattr(value, "to_pydatetime"):
        return int(value.to_pydatetime().timestamp())
    if hasattr(value, "timestamp"):
        return int(value.timestamp())
    return int(value)


def prepare_plugin_df(df: pd.DataFrame) -> pd.DataFrame:
    """Bereitet einen OHLCV-DataFrame fuer Plugin-Aufrufe vor.
    Plugin-Vertrag (base_plugin.py): der Input-DataFrame enthaelt eine
    'time'-Spalte mit epoch-Sekunden (int). load_ohlcv() liefert stattdessen
    'bar_time' (datetime) – diese wird hier passend umgewandelt."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if "bar_time" in out.columns and "time" not in out.columns:
        out["time"] = out["bar_time"].apply(_timestamp_to_epoch)
    return out


def _to_utc_datetime(value: Any):
    """Konvertiert epoch-Sekunden / pandas Timestamp / datetime in ein
    timezone-aware datetime (UTC), passend zur TIMESTAMPTZ-Spalte im Store."""
    if isinstance(value, bool):
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return value


# ==============================================================================
# P14-03: Strukturierte Fehlerobjekte & In-Memory-Cache-Invalidierung
# ------------------------------------------------------------------------------
# Architektur-Invariante 8: Logging verwendet strukturierte Fehlerobjekte
# (timestamp, plugin, instance, symbol, timeframe, bar, exception, traceback).
# Architektur-Invariante 13: store_plugin_payload() invalidiert den
# In-Memory-Cache für (symbol, timeframe).
# ==============================================================================
@dataclass
class PluginExecutionErrorInfo:
    """Strukturiertes Fehlerobjekt eines fehlgeschlagenen Plugin-Aufrufs.

    Wird von PluginExecutor bei jeder Exception der Ausführungskette erzeugt
    (stage: resolve / dependency / validate_params / calculate) und als
    .info am PluginExecutionError mitgereicht. Der ServiceSetEvaluator nutzt
    es für Skip-Logic, State-Fallback und Session-Quarantäne.
    """
    timestamp: float
    plugin_id: str
    instance_id: Optional[str]
    symbol: str
    timeframe: str
    bar_time: Optional[int]
    stage: str
    exception_type: str
    exception_message: str
    traceback: str

    def to_service_error_log(self) -> ServiceErrorLog:
        """P14-03 (Schritt 2.2): Liefert das strukturierte Fehlerobjekt als
        ServiceErrorLog-TypedDict (Pflichtfelder laut Anleitung) für die
        maschinelle Auswertung des Loggings in PluginExecutor /
        ServiceSetEvaluator."""
        return ServiceErrorLog(
            timestamp=self.timestamp,
            plugin_id=self.plugin_id,
            instance_id=self.instance_id,
            symbol=self.symbol,
            timeframe=self.timeframe,
            bar_time=self.bar_time,
            exception=f"{self.exception_type}: {self.exception_message}",
            traceback=self.traceback,
        )


class PluginExecutionError(Exception):
    """Getypter Ausführungsfehler mit strukturiertem Fehlerobjekt (.info)."""

    def __init__(self, info: PluginExecutionErrorInfo):
        self.info = info
        super().__init__(info.exception_message)


_feature_cache_lock = threading.Lock()
_feature_cache_invalidated: Dict[Tuple[str, str], float] = {}


def invalidate_feature_cache(symbol: str, timeframe: str) -> None:
    """P14-03 (Invariante 13): Meldet die Invalidation des In-Memory-Caches
    für (symbol, timeframe). Wird bei jedem store_plugin_payload() aufgerufen,
    damit veraltete Zustände (z. B. in EvaluationContext.shared_state) nicht
    über einen Refresh hinweg weiterleben."""
    with _feature_cache_lock:
        _feature_cache_invalidated[
            (str(symbol).lower(), str(timeframe).lower())
        ] = time.time()


def feature_cache_last_invalidated(symbol: str, timeframe: str) -> Optional[float]:
    """Letzter Invalidation-Zeitpunkt für (symbol, timeframe) oder None."""
    with _feature_cache_lock:
        return _feature_cache_invalidated.get(
            (str(symbol).lower(), str(timeframe).lower())
        )


class PluginLoader:
    """Class-Finder scannt Verzeichnisse rein nach Subklassen von PluginFeature (Dateiname-unabhängig).

    P14-02 (additiv): Automatische, rekursive Discovery über
    pkgutil.walk_packages() + importlib.import_module() für
    analytics/features/definitions/ (Core) und data/custom_plugins/ (Custom).
    - data/custom_plugins/ wird automatisch angelegt (os.makedirs).
    - Eindeutigkeit der plugin_id strikt case-insensitiv (plugin_id.lower()).
    - Core Protection Rule: Custom-Plugins mit bereits belegter ID werden
      verworfen (WARN-Log).
    - Abstrakte Klassen werden ignoriert; Import-/Instanzierungsfehler einzelner
      Module werden isoliert abgefangen (kein App-Absturz).
    """

    def __init__(self, definitions_path: Optional[Path] = None,
                 custom_plugins_path: Optional[Path] = None):
        self.definitions_path = definitions_path or Path(__file__).parent / "definitions"
        self.custom_plugins_path = custom_plugins_path or DATA_DIR / "custom_plugins"
        # P14-02: Namen der zuletzt erfolgreich geladenen Custom-Plugin-Module
        # (fuer gezieltes importlib.reload in PluginRegistry.reload()).
        self.loaded_custom_modules: List[str] = []

    def _ensure_custom_dir(self) -> None:
        """Legt data/custom_plugins/ an, falls es noch nicht existiert (P14-02)."""
        try:
            self.custom_plugins_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"WARN [PluginLoader] Ordner {self.custom_plugins_path} nicht erstellbar: {e}")

    def _scan_dir(self, plugins: Dict[str, PluginFeature], path: Path,
                  package_prefix: str, is_custom: bool) -> None:
        """Scannt ein Verzeichnis rekursiv nach PluginFeature-Subklassen (P14-02).

        is_custom=True: Module werden in loaded_custom_modules registriert und
        eine bereits belegte plugin_id (Core Protection Rule) fuehrt zum
        Ueberspringen mit WARN-Log.
        """
        if not path.exists():
            return
        for mod_info in pkgutil.walk_packages([str(path)]):
            module_name = mod_info.name
            full_module_name = f"{package_prefix}.{module_name}"
            try:
                module = importlib.import_module(full_module_name)
            except Exception as e:
                print(f"WARN [PluginLoader] Modul {full_module_name} nicht ladbar: {e}")
                continue
            if is_custom and full_module_name not in self.loaded_custom_modules:
                self.loaded_custom_modules.append(full_module_name)
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if inspect.isabstract(obj):
                    continue  # abstrakte Basisklassen ignorieren
                if issubclass(obj, PluginFeature) and obj is not PluginFeature:
                    try:
                        instance = obj()
                    except Exception as e:
                        print(f"WARN [PluginLoader] Instanzierung {_name} ({full_module_name}) fehlgeschlagen: {e}")
                        continue
                    pid = str(instance.plugin_id)
                    pid_key = pid.lower()
                    if is_custom and pid_key in plugins:
                        print(f"WARN: Custom plugin skipped: plugin_id '{pid}' already registered")
                        continue
                    plugins[pid_key] = instance

    def discover_plugins(self) -> Dict[str, PluginFeature]:
        """Entdeckt Core-Plugins (zuerst) und Custom-Plugins (danach), case-insensitiv.

        P14-02: data/custom_plugins/ wird automatisch angelegt; fuer den Import
        der Custom-Module ('custom_plugins.<mod>') wird data/ in sys.path
        aufgenommen, falls noetig (namespace package).
        """
        plugins: Dict[str, PluginFeature] = {}
        self.loaded_custom_modules = []
        self._ensure_custom_dir()
        # Core zuerst (analytics/features/definitions/)
        self._scan_dir(plugins, self.definitions_path,
                       "analytics.features.definitions", is_custom=False)
        # Custom danach (data/custom_plugins/) - data/ in sys.path sicherstellen
        try:
            data_dir = str(DATA_DIR)
            if data_dir not in sys.path:
                sys.path.insert(0, data_dir)
        except Exception:
            pass
        self._scan_dir(plugins, self.custom_plugins_path, "custom_plugins", is_custom=True)
        return plugins

    def find_custom_conflicts(self) -> List[Dict[str, str]]:
        """Kapitel 7.3 AKTUELLE_UMSETZUNG (Core Protection Rule, --check-plugins).

        Scannt die Core-Definitions und anschliessend die Custom-Plugins –
        exakt wie discover_plugins() – und liefert alle Custom-Plugin-IDs, die
        mit einer bereits registrierten Core-Plugin-ID kollidieren. Die
        eigentliche Registry verwirft solche Custom-Plugins bereits beim Laden
        (WARN-Log); dieser Check macht die Kollisionen fuer den Deployment-
        Check (`python main.py --check-plugins`) sichtbar und pruefbar.

        Returns:
            Liste von Dicts {"plugin_id", "custom_module"} – leer, wenn die
            Core Protection Rule vollstaendig greift.
        """
        conflicts: List[Dict[str, str]] = []
        core: Dict[str, PluginFeature] = {}
        self._scan_dir(core, self.definitions_path,
                       "analytics.features.definitions", is_custom=False)
        if not self.custom_plugins_path.exists():
            return conflicts
        # data/ in sys.path sicherstellen (namespace package custom_plugins)
        try:
            data_dir = str(DATA_DIR)
            if data_dir not in sys.path:
                sys.path.insert(0, data_dir)
        except Exception:
            pass
        for mod_info in pkgutil.walk_packages([str(self.custom_plugins_path)]):
            full_module_name = f"custom_plugins.{mod_info.name}"
            try:
                module = importlib.import_module(full_module_name)
            except Exception as e:
                print(f"WARN [PluginLoader] Modul {full_module_name} nicht "
                      f"ladbar: {e}")
                continue
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if inspect.isabstract(obj):
                    continue
                if issubclass(obj, PluginFeature) and obj is not PluginFeature:
                    try:
                        instance = obj()
                    except Exception as e:
                        print(f"WARN [PluginLoader] Instanzierung {_name} "
                              f"({full_module_name}) fehlgeschlagen: {e}")
                        continue
                    pid = str(instance.plugin_id)
                    if pid.lower() in core:
                        conflicts.append({
                            "plugin_id": pid,
                            "custom_module": full_module_name,
                        })
        return conflicts


class PluginRegistry:
    """Zentraler Singleton-Katalog für entdeckte Plugins (P14-02: thread-sicher)."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # P14-02: Reentrant Lock fuer Schreib-/Lesezugriffe (Thread-Safety)
            cls._instance._lock = threading.RLock()
            cls._instance.loader = PluginLoader()
            cls._instance.plugins = cls._instance.loader.discover_plugins()
        return cls._instance

    def reload(self):
        """Expliziter Reload nur beim Start oder per Button (thread-sicher).

        P14-02: Unter dem RLock werden zuerst die geladenen Custom-Plugin-Module
        gezielt neu importiert (importlib.reload), danach die Registry ueber
        discover_plugins() neu aufgebaut. Bereits laufende Service-Instanzen
        behalten ihre bisherigen Objekt-Referenzen (Hot-Reload-Semantik); neue
        Instanziierungen nutzen die neuen Klassen.
        """
        with self._lock:
            # 1. Custom-Module gezielt neu laden (Datei geloescht/fehlerhaft ->
            #    Modul aus sys.modules entfernen)
            for mod_name in list(self.loader.loaded_custom_modules):
                try:
                    if mod_name in sys.modules:
                        importlib.reload(sys.modules[mod_name])
                except Exception as e:
                    sys.modules.pop(mod_name, None)
                    print(f"WARN [PluginRegistry] Custom-Modul {mod_name} nicht reloadbar: {e}")
            # 2. Registry neu aufbauen
            self.plugins = self.loader.discover_plugins()

    def get(self, plugin_id: str) -> PluginFeature:
        """Case-insensitiver Zugriff (P14-02): plugin_id.lower()."""
        key = plugin_id.lower()
        if key not in self.plugins:
            raise KeyError(f"Plugin '{plugin_id}' nicht gefunden.")
        return self.plugins[key]


class PluginExecutor:
    """Zentrale Schicht für Ausführung, Validierung, Dependency-Ordering & Logging.

    P14-03 (Ganzheitliche Fehlerkapselung): Sämtliche Exceptions der
    Ausführungskette eines Plugins – Plugin-Auflösung (resolve), interne
    Dependency-Aufrufe (dependency), validate_params() und calculate() –
    werden isoliert abgefangen, in ein strukturiertes Fehlerobjekt
    (PluginExecutionErrorInfo, Invariante 8) umgewandelt, geloggt und als
    PluginExecutionError weitergereicht. Der ServiceSetEvaluator entscheidet
    darüber mit Skip-Logic / Dependency-Skip / Quarantäne.
    """

    def __init__(self, registry: Optional[PluginRegistry] = None):
        self.registry = registry or PluginRegistry()

    @staticmethod
    def _call_calculate(
        plugin: PluginFeature,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Ruft plugin.calculate() auf – mit Context, falls das Plugin ihn
        unterstützt. Plugins mit der alten Phase-12-Signatur calculate(df, params)
        bleiben kompatibel (context ist Optional, Rückwärtskompatibilität)."""
        sig = inspect.signature(plugin.calculate)
        if "context" in sig.parameters:
            return plugin.calculate(df, params, context=context)
        return plugin.calculate(df, params)

    @staticmethod
    def _build_error(
        plugin_id: str,
        context: Optional[PluginContext],
        exc: Exception,
        stage: str,
    ) -> "PluginExecutionError":
        """Baut aus einer Exception das strukturierte Fehlerobjekt (P14-03)."""
        symbol = getattr(context, "symbol", "") or ""
        timeframe = getattr(context, "timeframe", "") or ""
        instance_id = getattr(context, "instance_id", None)
        bar_time = getattr(context, "timestamp", None)
        info = PluginExecutionErrorInfo(
            timestamp=time.time(),
            plugin_id=plugin_id,
            instance_id=instance_id,
            symbol=str(symbol),
            timeframe=str(timeframe),
            bar_time=bar_time,
            stage=stage,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            traceback=traceback.format_exc(),
        )
        # P14-03 (Schritt 2.2): Logging über das strukturierte
        # ServiceErrorLog-TypedDict (maschinelle Auswertung).
        log: ServiceErrorLog = info.to_service_error_log()
        print(
            f"WARN [PluginExecutor] {stage} fehlgeschlagen: plugin='{log['plugin_id']}' "
            f"instance='{log['instance_id']}' {log['symbol']}/{log['timeframe']} – "
            f"{log['exception']}"
        )
        return PluginExecutionError(info)

    def execute(
        self,
        plugin_id: str,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        # 0. Plugin-Auflösung (Registry) – Fehler werden strukturiert gekapselt.
        try:
            plugin = self.registry.get(plugin_id)
        except Exception as e:
            raise self._build_error(plugin_id, context, e, "resolve") from e

        # 1. Dependency Resolution (falls Abhängigkeiten angegeben sind) –
        #    Context wird auch an Abhängigkeiten durchgereicht. Fehler in
        #    Dependency-Aufrufen werden unter der Dependency-plugin_id gekapselt.
        for dep_id in plugin.dependencies:
            try:
                dep_plugin = self.registry.get(dep_id)
                self._call_calculate(dep_plugin, df, dep_plugin.default_params, context)
            except PluginExecutionError:
                raise
            except Exception as e:
                raise self._build_error(dep_id, context, e, "dependency") from e

        # 2. Parametervalidierung
        try:
            validated_params = plugin.validate_params(params)
        except Exception as e:
            raise self._build_error(plugin_id, context, e, "validate_params") from e

        # 3. Stateless Execution – Context (inkl. shared_state) wird durchgereicht,
        #    damit Services den shared_state erreichen (Schritt 3 Evaluator).
        try:
            return self._call_calculate(plugin, df, validated_params, context)
        except Exception as e:
            raise self._build_error(plugin_id, context, e, "calculate") from e


class FeatureBuilder:
    """Orchestriert die Feature-Berechnung und persistiert sie im feature_store."""

    def __init__(self) -> None:
        # 19.02 (Cleanup): Legacy-Native-Spalten (ema_diff, atr_normalized)
        # entfernt. Der native Feature-Builder-Pfad berechnet nur noch die
        # Phase-11 Grid-Levels; Services persistieren ihre Werte ueber
        # feature_data (JSON, store_plugin_payload).
        self.features: Dict[str, BaseFeature] = {
            "grid_levels": GridLevelsFeature(),
        }
        # Spaltenname -> Feature-Modul-Name. Erlaubt calculate_features() auch
        # Spaltennamen aus signal.required_features (z. B. 'grid_dist_pct')
        # statt nur Modul-Namen zu uebernehmen.
        self._column_to_feature: Dict[str, str] = {}
        for fname, feat in self.features.items():
            for col in feat.column_names:
                self._column_to_feature[col] = fname
            self._column_to_feature.setdefault(fname, fname)
        self._state_mgr = StateManager()
        self._settings = self._state_mgr.get_app_settings()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_available_features(self) -> List[str]:
        return list(self.features.keys())

    def load_ohlcv(self, symbol: str, timeframe: str, limit: Optional[int] = None) -> pd.DataFrame:
        """Laedt OHLCV-Daten aus market_data.duckdb (read-only via DbPool)."""
        if limit is None:
            limit = self._settings.feature_builder_limit
        con = DbPool.get(DB_MARKET)
        query = """
            SELECT "time" AS bar_time, open, high, low, close, tick_volume
            FROM ohlcv_bars
            WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
              AND "time" IS NOT NULL
              AND open IS NOT NULL
              AND high IS NOT NULL
              AND low IS NOT NULL
              AND close IS NOT NULL
            ORDER BY "time" DESC
            LIMIT ?
        """
        df = con.execute(query, [symbol, timeframe, limit]).df()
        return df.sort_values("bar_time").reset_index(drop=True)

    def calculate_features(
        self,
        df: pd.DataFrame,
        feature_names: Optional[List[str]] = None,
        params: Optional[Dict[str, Dict[str, any]]] = None
    ) -> pd.DataFrame:
        """
        Berechnet ausgewaehlte Features auf einem OHLCV-DataFrame.

        Args:
            df: OHLCV-DataFrame mit bar_time, open, high, low, close
            feature_names: Liste der Feature-Namen (None = alle)
            params: Dict mit Feature-spezifischen Parametern

        Returns:
            DataFrame mit bar_time + feature-Spalten
        """
        if feature_names is None:
            feature_names = list(self.features.keys())

        if params is None:
            params = {}

        result = df[["bar_time"]].copy()

        for name in feature_names:
            # Spaltenname -> Feature-Modul aufloesen (z. B. 'grid_dist_pct' -> 'grid_levels')
            resolved = self._column_to_feature.get(name, name)
            feature = self.features.get(resolved)
            if feature is None:
                print(f"  [FeatureBuilder] Unbekanntes Feature: {name}")
                continue

            feature_params = params.get(name, {})
            try:
                calculated = feature.calculate(df, feature_params)

                if isinstance(calculated, pd.DataFrame):
                    for col in calculated.columns:
                        result[col] = calculated[col].values
                else:
                    result[feature.name] = calculated.values

            except Exception as e:
                print(f"  [FeatureBuilder] Fehler bei {name}: {e}")
                for col in feature.column_names:
                    result[col] = None

        return result

    def store_features(
        self,
        symbol: str,
        timeframe: str,
        features_df: pd.DataFrame,
        con: Optional = None,
    ) -> int:
        """
        Schreibt berechnete Features per Bulk-Upsert in analytics.duckdb.

        Args:
            symbol: Symbol-Name
            timeframe: Timeframe-String
            features_df: DataFrame mit bar_time + feature-Spalten
            con: Optionale externe DB-Connection

        Returns:
            Anzahl der geschriebenen Zeilen
        """
        if features_df.empty:
            return 0

        df = features_df.copy()
        df["symbol"] = symbol
        df["timeframe"] = timeframe
        # 17.01 (E-1, 07.08.2026): Der nativen Feature-Builder-Pfad schreibt
        # mit feature_id='native' (Sentinel) – der PK ist seit der Migration
        # (symbol, timeframe, bar_time, feature_id), damit mehrere Services auf
        # derselben Bar koexistieren koennen.
        df["feature_id"] = "native"

        own_connection = False
        if con is None:
            con = DbPool.get(DB_ANALYTICS)
        else:
            own_connection = True

        try:
            con.register("df_temp", df)

            feature_cols = [c for c in df.columns if c not in ("bar_time", "symbol", "timeframe", "feature_id")]
            if not feature_cols:
                return 0

            insert_cols = ", ".join(['"symbol"', '"timeframe"', '"bar_time"', '"feature_id"'] + [f'"{c}"' for c in feature_cols])
            select_cols = ", ".join(['"symbol"', '"timeframe"', '"bar_time"', '"feature_id"'] + [f'"{c}"' for c in feature_cols])
            set_clause = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in feature_cols])

            sql = f"""
                INSERT INTO feature_store ({insert_cols})
                SELECT {select_cols}
                FROM df_temp
                ON CONFLICT {_feature_store_conflict_target(con)} DO UPDATE SET
                    {set_clause}
            """
            con.execute(sql)
            con.unregister("df_temp")

            return len(df)
        finally:
            if own_connection:
                con.close()

    def store_plugin_payload(
        self,
        symbol: str,
        timeframe: str,
        payload: Dict[str, Any],
        con: Optional = None,
        instance_hash: Optional[str] = None,
    ) -> int:
        """
        Schreibt den feature_store_payload eines Plugins (Phase 12 Hybrid-Schema)
        in analytics.duckdb.

        Setzt/aktualisiert NUR die Plugin-Spalten (feature_id, plugin_version,
        feature_data); native Feature-Spalten bleiben unberuehrt. Dadurch ist
        der Plugin-Pfad parallel zum Alt-Pfad betreibbar – seit 17.01 (E-1,
        PK-Migration auf (symbol, timeframe, bar_time, feature_id)) koennen
        MEHRERE Services denselben (symbol, timeframe, bar_time)-Schluessel
        tragen; feature_id des Payloads ist der Trenner.

        20.04 (Q9): Optionaler `instance_hash` (8-stelliger SHA256-Short-Hash
        der Parameter-Variante) wird in die neue Spalte `instance_hash`
        geschrieben – nur wenn gesetzt, sonst NULL (bestehende Hashes werden
        beim Upsert NICHT durch NULL ueberschrieben, COALESCE). Der Aufrufer
        (SetEvaluator / HistoricalScanner / LiveAnalyzer) uebergibt den Hash
        der ausgeführten Instanz, damit Signal-/Metrik-Ergebnisse verschiedener
        Clones in DuckDB getrennt und einzeln auswertbar sind (Multi-Clone-
        Vergleich, §4). feature_id bleibt plugin_id (Q1).

        payload: {"feature_id", "plugin_version", "records": [{bar_time, ...}]}
        """
        records = payload.get("records") or []
        if not records:
            return 0

        feature_id = payload.get("feature_id")
        plugin_version = payload.get("plugin_version", "1.0.0")

        own_connection = False
        if con is None:
            con = DbPool.get(DB_ANALYTICS)
        else:
            own_connection = True

        try:
            rows = []
            for rec in records:
                if not isinstance(rec, dict) or "bar_time" not in rec:
                    continue
                dt_val = _to_utc_datetime(rec["bar_time"])
                data = {k: v for k, v in rec.items() if k != "bar_time"}
                rows.append((symbol, timeframe, dt_val, feature_id,
                             plugin_version, json.dumps(data),
                             instance_hash or ""))
            if not rows:
                return 0

            # Bugfix 05.08.2026: `now()` statt `current_timestamp` im
            # ON CONFLICT DO UPDATE SET – DuckDB 1.5.5 bindet das (lowercase)
            # Keyword dort als SPALTENREFERENZ der feature_store-Tabelle und
            # wirft 'Binder Error: Table "feature_store" does not have a column
            # named "current_timestamp"'. `now()` (Funktionsaufruf) wird
            # korrekt als Zeitfunktion aufgeloest (verifiziert in
            # test/check_current_timestamp.py).
            #
            # Phase 16 (05.08.2026, Performance-Nachtrag): `executemany` mit
            # einem parameterisierten INSERT pro Bar war der eigentliche
            # Engpass der Service-Ausfuehrung (z.B. ~20 s fuer 8k D1-Bars,
            # mehrere Minuten fuer 100k M1-Bars). Ersetzt durch einen
            # BULK-INSERT via con.register + INSERT..SELECT (identisches
            # ON CONFLICT-Upsert) – ~2000x schneller (8k Rows: ~10 ms).
            df_rows = pd.DataFrame(
                rows,
                columns=["symbol", "timeframe", "bar_time", "feature_id",
                         "plugin_version", "feature_data", "instance_hash"],
            )
            con.register("df_temp", df_rows)
            try:
                # Bugfix 07.08.2026 (Phase 17 Bugfix-Runde 2): created_at wird
                # JETZT auch fuer NEUE Rows explizit mit now() geschrieben
                # (nicht nur im ON CONFLICT-Zweig). Die PK-Migration
                # (17.01 E-1, test/migrate_pk.py) hat den Spalten-DEFAULT
                # (current_timestamp) der feature_store-Tabelle entfernt –
                # ohne die explizite Spalte waeren neue Rows created_at=NULL
                # und das Datum der letzten Ausfuehrung ('DD.MM.JJ' im
                # MasterTree) bliebe fuer neu berechnete Services '--.--.--'.
                #
                # 20.04 (Q9): instance_hash wird beim Upsert mitgeschrieben;
                # COALESCE verhindert, dass ein NULL (Aufrufer ohne Hash) einen
                # bestehenden Varianten-Hash ueberschreibt.
                con.execute(f"""
                    INSERT INTO feature_store
                        (symbol, timeframe, bar_time, feature_id,
                         plugin_version, feature_data, instance_hash, created_at)
                    SELECT symbol, timeframe, bar_time, feature_id,
                           plugin_version, feature_data, instance_hash, now()
                    FROM df_temp
                    ON CONFLICT {_feature_store_conflict_target(con)} DO UPDATE SET
                        feature_id = EXCLUDED.feature_id,
                        plugin_version = EXCLUDED.plugin_version,
                        feature_data = EXCLUDED.feature_data,
                        instance_hash = COALESCE(
                            EXCLUDED.instance_hash, feature_store.instance_hash),
                        created_at = now()
                """)
            finally:
                con.unregister("df_temp")
            # P14-03 (Invariante 13): In-Memory-Cache für (symbol, timeframe)
            # explizit invalidieren (veraltete shared_state-Zustände vermeiden).
            invalidate_feature_cache(symbol, timeframe)
            return len(rows)
        finally:
            if own_connection:
                con.close()

    def purge_instance_data(self, instance_hash: str, plugin_id: str = "",
                            params: Optional[Dict[str, Any]] = None) -> int:
        """Loescht alle feature_store-Rows einer Parameter-Variante (20.04, Q5).

        `DELETE FROM feature_store WHERE instance_hash = ?` – ausschliesslich
        im Schreib-/Store-Kontext (FeatureBuilder). Der `FeatureStoreReader`
        bleibt 100 % read-only (MVVM-Invariante). Behaelt MasterTree-Struktur,
        Parameter-Settings und `doc_log` vollstaendig bei – nur die
        DB-Daten der Variante werden entfernt (`feature_id` bleibt plugin_id
        und wird NICHT geloescht, Q1; andere Varianten/Instanzen bleiben
        unangetastet).

        11.08.2026 (Bugfix Runde 5): Zusaetzlich werden bei uebergebenem
        plugin_id + params die LEGACY-Pool-Rows der Variante geloescht.
        Alt-Rows aus Runs VOR der Preset-Hash-Umstellung liegen unter dem
        reinen Params-only-Hash `generate_instance_hash(plugin_id, params)`
        (ohne preset_name) und sind keiner Variante eindeutig zuordenbar
        (Kollisions-Pool). Sie wurden ueber den (inzwischen entfernten)
        Legacy-Anzeige-Fallback an ALLEN kollidierenden Varianten angezeigt
        und liessen das Ausfuehrungsdatum nach 'Data Only Loeschen' nicht
        zuruecksetzen. Mit plugin_id + params werden diese Alt-Rows jetzt
        zusammen mit den Varianten-Rows geloescht, damit das Datum im
        MasterTree wirklich auf 'nie' zurueckgesetzt wird.

        Args:
            instance_hash: 8-stelliger Parameter-Hash (generate_instance_hash,
                inkl. preset_name seit dem Varianten-Kollisions-Bugfix).
            plugin_id: Plugin-ID (optional) – noetig fuer den Legacy-Purge.
            params: Parameter-Dict der Variante (optional) – Grundlage des
                Params-only-Legacy-Hashes fuer den Legacy-Purge.

        Returns:
            Anzahl der geloeschten Rows (0 bei leerem Hash/keinem Treffer).
        """
        if not instance_hash:
            return 0
        # DbPool verwaltet die Connection thread-lokal (Invariante 6) –
        # NICHT schliessen (Muster store_plugin_payload: own_connection=False
        # bei DbPool.get; ein close() wuerde die Pool-Connection korrumpieren).
        con = DbPool.get(DB_ANALYTICS)
        try:
            deleted = 0
            # 1) Varianten-eigene Rows (Preset-eindeutiger Hash inkl.
            #    preset_name, seit Bugfix Varianten-Kollision).
            result = con.execute(
                "DELETE FROM feature_store WHERE instance_hash = ? "
                "RETURNING feature_id",
                [instance_hash])
            rows = result.fetchall() if result is not None else []
            deleted += len(rows or [])
            # 2) Legacy-Pool-Rows (Params-only-Hash aus Runs vor der
            #    Preset-Hash-Umstellung, 11.08.2026). Der Params-only-Hash
            #    ist aus dem Preset-Hash (inkl. preset_name) nicht umkehrbar
            #    – er wird hier aus plugin_id + params neu berechnet.
            if plugin_id and params is not None:
                try:
                    from analytics.engine.service_models import (
                        generate_instance_hash)
                    legacy_hash = generate_instance_hash(plugin_id, params)
                    if legacy_hash and legacy_hash != instance_hash:
                        result2 = con.execute(
                            "DELETE FROM feature_store "
                            "WHERE feature_id = ? AND instance_hash = ? "
                            "RETURNING feature_id",
                            [plugin_id, legacy_hash])
                        rows2 = (result2.fetchall()
                                 if result2 is not None else [])
                        deleted += len(rows2 or [])
                except Exception:
                    # Defensiv: Legacy-Purge ist optional – kein Abbruch.
                    pass
            return deleted
        except Exception:
            # Defensiv: keine Exception in den UI-Pfad durchreichen.
            return 0

    def build(
        self,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
        feature_names: Optional[List[str]] = None,
        params: Optional[Dict[str, Dict[str, any]]] = None,
    ) -> int:
        """
        Vollstaendiger Pipeline-Durchlauf: Laden -> Berechnen -> Speichern.

        Args:
            symbol: Symbol-Name
            timeframe: Timeframe-String
            limit: Maximale Anzahl Bars
            feature_names: Liste der Feature-Namen (None = alle)
            params: Feature-spezifische Parameter

        Returns:
            Anzahl der geschriebenen Zeilen
        """
        if limit is None:
            limit = self._settings.feature_builder_limit

        df_ohlcv = self.load_ohlcv(symbol, timeframe, limit)

        if df_ohlcv.empty:
            return 0

        features_df = self.calculate_features(df_ohlcv, feature_names, params)
        count = self.store_features(symbol, timeframe, features_df)
        return count

```

--------------------------------------------------

### DATEI: analytics/features/definitions/__init__.py
```py
# analytics/features/definitions/__init__.py
# 19.02 (Cleanup): Legacy-Native-Features ema_diff/atr_normalized deaktiviert
# (Dateien verbleiben als Code-Archiv auf Platte, werden aber nirgends mehr
# importiert/registriert). Der native Feature-Builder-Pfad nutzt nur noch
# grid_levels (Phase 11).
from analytics.features.definitions.grid_levels import GridLevelsFeature

__all__ = [
    "GridLevelsFeature",
]

```

--------------------------------------------------

### DATEI: analytics/features/definitions/atr_normalized.py
```py
# analytics/features/definitions/atr_normalized.py
"""
Feature: Normalisierter ATR (atr_normalized)
Berechnet den Average True Range, normalisiert auf den Schlusskurs in Prozent.
"""

from typing import Any, Dict
import pandas as pd
import numpy as np
from analytics.features.base_feature import BaseFeature


class ATRNormalizedFeature(BaseFeature):
    @property
    def name(self) -> str:
        return "atr_normalized"

    @property
    def description(self) -> str:
        return "Average True Range, normalisiert auf close in Prozent"

    def _calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
        period = params.get("period", 14)

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        # True Range
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]

        tr1 = high - low
        tr2 = np.abs(high - prev_close)
        tr3 = np.abs(low - prev_close)
        tr = np.maximum(np.maximum(tr1, tr2), tr3)

        # ATR als EMA der True Range
        atr = pd.Series(tr).ewm(span=period, adjust=False).mean()

        # Normalisierung auf close in Prozent
        normalized = (atr / df["close"]) * 100.0

        return normalized

```

--------------------------------------------------

### DATEI: analytics/features/definitions/ema_diff.py
```py
# analytics/features/definitions/ema_diff.py
"""
Feature: EMA-Differenz (ema_diff)
Berechnet die normalisierte Differenz zwischen zwei EMAs (schnell - langsam).
"""

from typing import Any, Dict
import pandas as pd
from analytics.features.base_feature import BaseFeature


class EMADiffFeature(BaseFeature):
    @property
    def name(self) -> str:
        return "ema_diff"

    @property
    def description(self) -> str:
        return "Normalisierte Differenz zwischen schnellem und langsamem EMA"

    def _calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
        fast_period = params.get("fast_period", 12)
        slow_period = params.get("slow_period", 26)

        ema_fast = df["close"].ewm(span=fast_period, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow_period, adjust=False).mean()

        diff = ema_fast - ema_slow
        # Normalisierung auf close-Preis (Prozentuale Abweichung)
        normalized = (diff / df["close"]) * 100.0

        return normalized

```

--------------------------------------------------

### DATEI: analytics/features/definitions/grid_levels.py
```py
# analytics/features/definitions/grid_levels.py
"""
Feature: Grid-Levels (Y-Achse) + Zeitfenster-Flags (X-Achse) – Phase 11

Berechnet vektorisiert fuer jede Bar die Liq-Line / Grid-Level Logik des
Grid-Systems (Paritaetsfunktionen in `grid_math.py`, Phase 15 U15-B3 –
eingefrorene Referenz-Kopien des am 04.08.2026 entfernten Alt-Indikators
chart/indicators/grid.py) und stellt sie als Feature-Spalten fuer den
feature_store bereit:

    grid_nearest_level      naechstes Grid-Level zum close (Preis)
    grid_dist_abs           absoluter Preisabstand |close - nearest_level|
    grid_dist_pct           prozentualer Abstand (dist_abs / close * 100)
    is_time_window_active   1 wenn die Bar im Zeitfenster liegt (Minute 0/30
                            +/- time_window_mins, native UTC), sonst 0

Das Modul ist bewusst gekapselt und unabhaengig vom Chart-Indikator. Es bildet
nur die Berechnungslogik ab (kein Rendering, kein DB-Zugriff). Die Konsistenz
wird durch dieselben Kernfunktionen sichergestellt (vektorisierte Varianten
der Skalar-Funktionen in `grid_math.py`):

    build_grid_levels()  <->  grid_math.build_grid_levels() (center +- i*step + custom)
    in_window_around()   <->  grid_math.f_in_window_around() (Minute 0/30 +- span)

Parameter (params-Dict):
    step_size          float, Schrittweite des Grids (Default 0.5, prox_stepSize)
    steps_around       int,   Anzahl Level ober-/unterhalb des Zentrums (Default 4,
                              prox_stepsAround)
    custom_levels      list[float], zusaetzliche Fix-Level (Default [], nur > 0
                              werden verwendet, prox_level1..6)
    time_window_mins   int,   Halbbreite des Zeitfensters in Minuten (Default 5,
                              prox_timeWindowMins)
    use_time_filter    bool,  False => is_time_window_active ist immer 1
                              (Default True, prox_useTimeFilter)
"""

from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from analytics.features.base_feature import BaseFeature

# Spaltennamen, wie sie im feature_store (analytics.duckdb) erwartet werden.
GRID_COLUMNS = [
    "grid_nearest_level",
    "grid_dist_abs",
    "grid_dist_pct",
    "is_time_window_active",
]


def build_grid_levels(
    center: float,
    step_size: float,
    steps_around: int,
    custom_levels: Optional[List[float]] = None,
) -> List[float]:
    """
    Erzeugt die sortierte Grid-Level-Liste (absteigend) fuer ein Zentrum.

    Identische Logik wie grid_math.build_grid_levels() (Referenz-Snapshot):
      center = round(price / step) * step
      levels = center + i*step  fuer i in [-steps_around, steps_around]
      + zusaetzliche custom_levels (nur > 0)
    """
    if step_size <= 0:
        base = {round(float(center), 6)}
    else:
        inv_step = 1.0 / step_size
        center_r = round(float(center) * inv_step) / inv_step
        base = {round(center_r + i * step_size, 6) for i in range(-steps_around, steps_around + 1)}

    for lvl in (custom_levels or []):
        v = float(lvl)
        if v > 0.0:
            base.add(round(v, 6))

    return sorted(base, reverse=True)


def in_window_around(
    minute_val: np.ndarray,
    center: int,
    span: int,
) -> np.ndarray:
    """
    Vektorisierte Version von grid_math.f_in_window_around():
    Liefert True fuer Minuten, die im Fenster center +/- span liegen
    (mit Wrap-Around ueber 0/59).
    """
    minute_val = np.asarray(minute_val, dtype=int)
    lower = center - span
    upper = center + span
    if lower < 0:
        return (minute_val >= (60 + lower)) | (minute_val <= upper)
    elif upper > 59:
        return (minute_val >= lower) | (minute_val <= (upper - 60))
    else:
        return (lower <= minute_val) & (minute_val <= upper)


class GridLevelsFeature(BaseFeature):
    """Vektorisierte Grid-Level-Berechnung fuer den feature_store."""

    @property
    def name(self) -> str:
        return "grid_levels"

    @property
    def description(self) -> str:
        return (
            "Naechstes Grid-Level zum close (Y-Achse), Preisabstaende "
            "(abs/pct) und Zeitfenster-Flag (is_time_window_active, X-Achse)"
        )

    @property
    def column_names(self) -> List[str]:
        return list(GRID_COLUMNS)

    def _calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
        n = len(df)
        if n == 0:
            return pd.DataFrame({c: [] for c in GRID_COLUMNS})

        # --- Parameter (Defaults konsistent zu grid_math.py) ---
        step_size = float(params.get("step_size", 0.5))
        steps_around = int(params.get("steps_around", 4))
        time_window_mins = int(params.get("time_window_mins", 5))

        use_time_filter_raw = params.get("use_time_filter", True)
        if isinstance(use_time_filter_raw, str):
            use_time_filter = use_time_filter_raw.lower() in ("true", "1", "yes")
        else:
            use_time_filter = bool(use_time_filter_raw)

        custom_levels_raw = params.get("custom_levels", [])
        valid_custom = [float(x) for x in custom_levels_raw if float(x) > 0.0]

        close = df["close"].to_numpy(dtype=float)

        # --- Grid-Level-Matrix vektorisiert aufbauen ---
        # Zentrum pro Bar = naechstes Vielfaches von step_size zum close
        if step_size > 0:
            centers = np.round(close / step_size) * step_size
            offsets = np.arange(-steps_around, steps_around + 1) * step_size
            levels = centers[:, None] + offsets[None, :]
        else:
            centers = close.copy()
            levels = centers[:, None]

        if valid_custom:
            custom_arr = np.full((n, len(valid_custom)), np.array(valid_custom, dtype=float)[None, :])
            levels = np.concatenate([levels, custom_arr], axis=1)

        # --- Naechstes Level & Abstaende ---
        diff = np.abs(levels - close[:, None])
        nearest_idx = np.argmin(diff, axis=1)
        nearest_level = levels[np.arange(n), nearest_idx]
        dist_abs = diff[np.arange(n), nearest_idx]

        with np.errstate(divide="ignore", invalid="ignore"):
            dist_pct = np.where(close != 0.0, dist_abs / close * 100.0, np.nan)

        # --- Zeitfenster-Flags (native UTC-Minute der Bar) ---
        minutes = self._bar_utc_minutes(df)
        full_win = in_window_around(minutes, 0, time_window_mins)
        half_win = in_window_around(minutes, 30, time_window_mins)
        in_window = full_win | half_win
        if not use_time_filter:
            in_window = np.ones(n, dtype=bool)

        return pd.DataFrame(
            {
                "grid_nearest_level": nearest_level,
                "grid_dist_abs": dist_abs,
                "grid_dist_pct": dist_pct,
                "is_time_window_active": in_window.astype(int),
            },
            index=df.index,
        )

    @staticmethod
    def _bar_utc_minutes(df: pd.DataFrame) -> np.ndarray:
        """
        Liefert die UTC-Minute (0-59) jeder Bar.

        Unterstuetzt:
          - 'bar_time' als tz-aware pandas datetime (feature_builder load_ohlcv)
          - 'bar_time' als naive datetime/str (wird als UTC interpretiert)
          - 'time' als Unix-Epoch-Integer (grid_math.py-Stil)
        """
        n = len(df)
        if "bar_time" in df.columns:
            t = pd.to_datetime(df["bar_time"])
            if t.dt.tz is not None:
                return t.dt.tz_convert("UTC").dt.minute.to_numpy(dtype=int)
            return t.dt.minute.to_numpy(dtype=int)
        elif "time" in df.columns:
            t = pd.to_datetime(df["time"], unit="s", utc=True)
            return t.dt.minute.to_numpy(dtype=int)
        return np.zeros(n, dtype=int)

```

--------------------------------------------------

### DATEI: analytics/features/definitions/grid_math.py
```py
# analytics/features/definitions/grid_math.py
"""
Phase 15 (U15-B3): Eigenständige Paritäts-Mathematik für Grid-Services.

Die Funktionen sind die eingefrorenen Referenz-Kopien der ehemaligen
Alt-Implementierung `chart/indicators/grid.py` (am 04.08.2026 entfernt).
Sie dienen als SINGLE SOURCE OF TRUTH für die Grid-Parität:

* `f_round_to_custom_step` – Rundung auf das nächste Vielfache von step.
* `build_grid_levels`      – Level-Array (Center ± steps_around × step + Custom).
* `f_in_window_around`     – natives UTC-Zeitfenster (Minute 0/30 ± span, Wrap-Around).
* `f_strip_trailing_zeros` – '%.6f' ohne nachgestellte Nullen (Level-Strings).

Die Services (srv_grid_lines.py, srv_proximity.py) importieren diese
Funktionen und garantieren damit identisches Verhalten zum historischen
Alt-Indikator, ohne auf das gelöschte Modul zu verweisen.

HINWEIS: Der Indikator-Adapter (chart/indicators/ind_fixed_grid_proximity.py) behält seine
private Kopie (`_f_in_window_around`) unverändert – sie wird nicht umgestellt.
Das Alt-Plugin analytics/features/definitions/grid_liquidity.py wurde am
04.08.2026 archiviert/entfernt (Schema ist im Indikator selbst hinterlegt).
"""

from typing import List, Optional


def f_round_to_custom_step(price: float, step: float) -> float:
    """Rundet price auf das nächste Vielfache von step.

    Exakte Parität zur ehemaligen chart/indicators/grid.py.
    """
    if step <= 0:
        return price
    inv_step = 1.0 / step
    return round(price * inv_step) / inv_step


def build_grid_levels(
    last_close: float,
    step_size: float,
    steps_around: int,
    custom_levels: Optional[List[float]] = None,
) -> List[float]:
    """Sortierte Level-Liste (absteigend) – exakte Parität zum Alt-Grid.

    grid.py (historisch):
      center_price = f_round_to_custom_step(last_close, step_size)
      grid_levels  = {round(center_price + i*step_size, 6)
                      | i in range(-steps_around, steps_around+1)}
      + {round(c_lvl, 6) | c_lvl in custom_levels, c_lvl > 0.0}
    """
    center_price = f_round_to_custom_step(last_close, step_size)
    grid_levels: set = set()
    for i in range(-steps_around, steps_around + 1):
        grid_levels.add(round(center_price + (i * step_size), 6))
    for c_lvl in (custom_levels or []):
        v = float(c_lvl)
        if v > 0.0:
            grid_levels.add(round(v, 6))
    return sorted(list(grid_levels), reverse=True)


def f_in_window_around(minute_val: int, center: int, span: int) -> bool:
    """Native UTC-Zeitfenster-Logik – exakte Parität zum Alt-Grid.

    True, wenn minute_val im Fenster center ± span liegt (mit Wrap-Around
    über 0/59). Zentren: 0 (ganze Stunde) und 30 (halbe Stunde).
    """
    lower = center - span
    upper = center + span
    if lower < 0:
        return minute_val >= (60 + lower) or minute_val <= upper
    elif upper > 59:
        return minute_val >= lower or minute_val <= (upper - 60)
    else:
        return lower <= minute_val <= upper


def f_strip_trailing_zeros(val: float) -> str:
    """'%.6f' ohne nachgestellte Nullen – exakte Parität zum Alt-Grid."""
    s = f"{val:.6f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s

```

--------------------------------------------------

### DATEI: analytics/features/definitions/srv_grid_lines.py
```py
# analytics/features/definitions/srv_grid_lines.py
"""
Service: GridLines (Phase 13 Schritt 6) – Naming Convention 16.08.01: srv_

Paritäts-Service zur Alt-Implementierung (ehemals chart/indicators/grid.py,
am 04.08.2026 entfernt) – baut das Level-Raster EXAKT wie der Alt-Indikator.
Die Paritätsfunktionen liegen in `grid_math.py` (Phase 15 U15-B3, eingefrorene
Referenz-Kopien):

    center = f_round_to_custom_step(last_close, step_size)
    levels = {round(center + i * step_size, 6) | i in [-steps_around, steps_around]}
             + Custom-Levels (prox_level1..6, nur > 0)

Der Service liefert KEINEN chart_render_payload mehr (Phase 16 P16.01, E2/E5:
render=False) – er schreibt ausschliesslich eine REINE Level-Liste
(`[{price}, ...]`, ohne Farben/Styling) nach context.shared_state[self.instance_id];
der nachgelagerte ProximityService liest sie von dort (depends_on), der
Indikator (chart/indicators/ind_fixed_grid_proximity.py) baut daraus in
`build_chart_render_payload()` das Styling (is_custom-Färbung, width 1/3,
style Solid – Parität zum Alt-Grid).

KEINE eigenen Zeitkonzepte: Das native UTC-Zeitfenster (Minute 0/30 ±
time_window_mins) ist ausschließlich Sache des ProximityService (Farbgebung),
nicht dieses Services.

Capabilities: render=False (P16.01), feature_store=True (schreibt Grid-Level je Bar in den Store).

05.08.2026 (U15-E, echte Feature-Store-Payloads): `calculate()` erzeugt jetzt
ZWINGEND ein gefuelltes `feature_store_payload` mit `feature_id="srv_grid_lines"`,
`plugin_version` und `records` je Bar:
    {"bar_time", "grid_nearest_level", "grid_step", "upper_level", "lower_level"}
  * grid_nearest_level = center = round(close / step_size) * step_size
  * upper_level        = center + step_size
  * lower_level        = center - step_size
Dadurch schreibt grid_lines (srv_grid_lines) bei der Ausfuehrung echte
mathematische Zeilen in analytics.duckdb (`feature_store`) – unabhaengig von
`show_lines` (das nur die RENDER-Darstellung steuert, nicht die
Daten-Mathematik).

PARAMETER (PineScript-Input-Zone, 16.08.02 M3): Alle Inputs/Defaults stehen
als Modul-Konstante `_GRID_LINES_SCHEMA` direkt unter diesem Header (siehe
dort) und sind wie in PineScript am Dateianfang anpassbar. Darstellungs-
Reihenfolge steuert `parameter_order`; `custom_levels` bleibt intern
(Aggregat), die 6 Einzel-Level `prox_level1..6` werden im Editor gerendert.
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from analytics.features.definitions.grid_math import (
    build_grid_levels,
    f_round_to_custom_step,
)
from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 16.08.02 M3): Single Source of Truth
# fürs Prop-Fenster. Inputs/Defaults stehen hier direkt am Dateianfang
# (analog _FIXED_GRID_PROXIMITY_SCHEMA), damit sie wie in PineScript ohne
# Suchen anpassbar sind. `parameter_schema` gibt eine flache Kopie zurück
# (M1: kein geteiltes mutable Dict über Instanzen).
# ---------------------------------------------------------------------------
_GRID_LINES_SCHEMA: Dict[str, ParameterSchema] = {
    "step_size": {
        "type": "float", "default": 0.5, "min": 0.01, "max": 1000.0,
        "step": 0.05, "description": "Rasterabstand (prox_stepSize ↔ step_size)",
    },
    "steps_around": {
        "type": "int", "default": 4, "min": 0, "max": 100,
        "step": 1, "description": "Level ober-/unterhalb des Zentrums (prox_stepsAround ↔ steps_around)",
    },
    # USER-REQ: P14-01 Nachtrag - die 6 Custom-Levels werden im Editor
    # als EINZELPARAMETER prox_level1..6 gerendert (Level 1..6). Das
    # Aggregat custom_levels bleibt im Schema erhalten - die interne
    # Pipeline (FixedGridProximityIndicator._build_set_definition) und
    # Alt-Sets speichern die Level als Liste/String. calculate() liest
    # beide Formen (custom_levels_from_params).
    "custom_levels": {
        "type": "str", "default": "",
        "description": "Custom-Levels, nur > 0 (prox_level1..6 ↔ custom_levels)",
    },
    "prox_level1": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 1"},
    "prox_level2": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 2"},
    "prox_level3": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 3"},
    "prox_level4": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 4"},
    "prox_level5": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 5"},
    "prox_level6": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 6"},
}

# ---------------------------------------------------------------------------
# OUTPUT-SCHEMA (20.03): Resultatfelder je feature_data-Record.
# `bar_time` ist eine native DB-Spalte und wird NICHT deklariert (E4).
# `type` sind freie Strings (E5). `technical: True` -> kompakte Anzeige im
# Unterblock `🔧 System-Metrik` (E2).
# ---------------------------------------------------------------------------
_GRID_OUTPUT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "grid_nearest_level": {
        "type": "float",
        "description": "Nächstes Grid-Level zum Close (Center = round(close/step_size) × step_size)",
    },
    "grid_step": {
        "type": "float",
        "description": "Rasterabstand (step_size) der Grid-Konstruktion",
    },
    "upper_level": {
        "type": "float",
        "description": "Obere Klammer = Center + step_size",
    },
    "lower_level": {
        "type": "float",
        "description": "Untere Klammer = Center - step_size",
    },
}

def _parse_custom_levels(raw: Any) -> List[float]:
    """Akzeptiert Liste/Tupel ODER Komma-/Semikolon-String; nur Werte > 0."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [round(float(x), 6) for x in raw if _to_float(x, 0.0) > 0.0]
    if isinstance(raw, str) and raw.strip():
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        return [round(float(x), 6) for x in parts if _to_float(x, 0.0) > 0.0]
    return []


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_prox_levels(params: Dict[str, Any]) -> List[float]:
    """Custom-Levels aus den EINZELPARAMETERN prox_level1..6 (nur > 0).

    Parität zu ind_fixed_grid_proximity._extract_custom_levels(): Einzelwerte werden
    bevorzugt, wenn mindestens einer > 0 ist.
    """
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
    return levels


def custom_levels_from_params(params: Dict[str, Any]) -> List[float]:
    """Custom-Levels aus params: bevorzugt prox_level1..6 (Einzelparameter,
    Alt-/Neu-Speicherung im Service-Modell), sonst custom_levels (Liste/String).

    USER-REQ: P14-01 Nachtrag - Sets koennen die 6 Level EINZELN
    (prox_level1..6) ODER als Aggregat (custom_levels) gespeichert haben -
    beide Formen werden gelesen.
    """
    levels = _extract_prox_levels(params)
    if levels:
        return levels
    return _parse_custom_levels(params.get("custom_levels"))


def map_custom_levels_to_prox_levels(params: Dict[str, Any]) -> Dict[str, float]:
    """Mappt gespeicherte custom_levels (Liste/String) auf prox_level1..6.

    USER-REQ: P14-01 Nachtrag - damit Alt-Sets mit Aggregat-Speicherung im
    Editor (6 Level-Felder) ihre Werte weiterhin anzeigen. Nur Werte > 0
    werden gemappt; max. 6 Level.
    """
    out: Dict[str, float] = {}
    for i, v in enumerate(_parse_custom_levels(params.get("custom_levels"))[:6], start=1):
        if v > 0.0:
            out[f"prox_level{i}"] = float(v)
    return out


class GridLinesService(PluginFeature):

    @property
    def plugin_id(self) -> str:
        return "srv_grid_lines"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, str]:
        return {
            "category": "Grid",
            "display_name": "Grid Lines",
            # Phase 16 (06.08.2026): Zugehoeriger Indikator-Name fuer die Status-
            # Badges im MasterTree (der Service laeuft IN Ind_FixedGridProximity).
            "indicator_name": "Ind_FixedGridProximity",
            # Phase 16 (06.08.2026): indicator_id = indicators_state-Key des
            # zugehoerigen Indikators. ServiceSelectorModel.is_active_in_chart()
            # prueft damit die Aktiv-Frage auf Indikator-Ebene (Tooltip
            # 'aktiv <Indikator>' statt nur 'im <Indikator>').
            "indicator_id": "ind_fixed_grid_proximity",

            "description": "Baut das Grid-Raster in Parität zum Alt-Grid (Center ± steps_around × step_size + Custom-Levels)",
            "author": "PyTrader AI",
            "tags": ["grid", "lines", "raster"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Baut das Level-Raster exakt wie der Alt-Grid-Indikator "
                                "(Paritätsfunktionen in grid_math.py) und "
                                "schreibt die Linienliste in den shared_state "
                                "für nachgelagerte Services (depends_on).",
            "condition_rules": [
                "Zentrierung: runden(close / step_size) × step_size",
                "Levels: center + i × step_size für i in [-steps_around, steps_around]",
                "Custom-Levels nur > 0",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": True,
            "batch": True,
            "live": False,
            # 05.08.2026 (U15-E): grid_lines schreibt jetzt echte Grid-Level
            # je Bar in den Store (feature_store_payload in calculate()).
            "feature_store": True,
            # Phase 16 (P16.01, E5): render=False - der Service liefert KEINEN
            # chart_render_payload mehr; der Indikator baut das Styling.
            "render": False,
        }

    # --- Single Source of Truth fürs Prop-Fenster (Phase 13 Schritt 5) -------
    @property
    def parameter_order(self) -> List[str]:
        # USER-REQ: P14-01 Nachtrag - die 6 Custom-Levels werden im Editor als
        # EINZELPARAMETER prox_level1..6 (Level 1..6, wie ind_fixed_grid_proximity)
        # gerendert. custom_levels bleibt im parameter_schema (interne Pipeline
        # & Aggregat-Speicherung), ist aber NICHT in der Darstellungs-Reihenfolge
        # -> wird im Editor nicht als Komma-Feld gerendert.
        # Phase 16 (P16.01): show_lines/line_color sind KEINE Service-Parameter
        # mehr (E1/E5) - sie steuern ausschliesslich die Render-Darstellung im
        # Indikator (chart/indicators/ind_fixed_grid_proximity.py).
        return [
            "step_size", "steps_around",
            "prox_level1", "prox_level2", "prox_level3",
            "prox_level4", "prox_level5", "prox_level6",
        ]

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "step_size": "Rasterabstand",
            "steps_around": "Level-Anzahl (je Seite)",
            "prox_level1": "Level 1",
            "prox_level2": "Level 2",
            "prox_level3": "Level 3",
            "prox_level4": "Level 4",
            "prox_level5": "Level 5",
            "prox_level6": "Level 6",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_GRID_LINES_SCHEMA` (16.08.02 M3).

        Inhalt/Reihenfolge identisch zur vorherigen Inline-Property – nur die
        Position des Dict-Literals hat sich an den Dateianfang verschoben
        (PineScript-Input-Zone, kein geteiltes mutable Dict: flache Kopie).
        """
        return {k: dict(v) for k, v in _GRID_LINES_SCHEMA.items()}

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): flache Kopie der Modul-Konstante
        `_GRID_OUTPUT_SCHEMA` (PineScript-Input-Zone, M1: kein geteiltes
        mutable Dict)."""
        return {k: dict(v) for k, v in _GRID_OUTPUT_SCHEMA.items()}

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Baut das Raster in Parität zum Alt-Grid (grid_math.py) und schreibt
        die reine LEVEL-Liste nach context.shared_state[self.instance_id]
        (Namespace-isoliert).

        05.08.2026 (U15-E): Zusaetzlich wird ein gefuelltes feature_store_payload
        erzeugt (feature_id='srv_grid_lines', plugin_version, records je Bar mit
        bar_time / grid_nearest_level / grid_step / upper_level / lower_level) -
        grid_lines schreibt damit echte mathematische Grid-Level in den
        feature_store.

        Phase 16 (P16.01, E2): Der Service liefert KEINEN chart_render_payload
        mehr (render=False, E5). Die Level-Liste im shared_state enthaelt nur
        noch {price} - OHNE Farben/width/style. Das Render-Styling (Farben,
        Sichtbarkeit) baut ausschliesslich der Indikator
        (build_chart_render_payload in ind_fixed_grid_proximity.py)."""
        if df is None or df.empty:
            return {"feature_store_payload": {}}

        p = self.validate_params(params)
        step_size = float(p["step_size"])
        steps_around = int(p["steps_around"])

        custom_levels = custom_levels_from_params(p)
        sorted_levels = build_grid_levels(
            last_close=float(df.iloc[-1]["close"]),
            step_size=step_size,
            steps_around=steps_around,
            custom_levels=custom_levels,
        )

        # --- Reine Level-Liste (P16.01/E2, exakte Parität zu grid.py) --------
        # OHNE Farben/Styling - der nachgelagerte ProximityService liest nur
        # {price} (tracked_levels), der Indikator baut das Styling daraus.
        level_entries: List[Dict[str, Any]] = [
            {"price": lvl} for lvl in sorted_levels
        ]

        # Level-Liste in den Namespace schreiben – der ProximityService liest
        # sie von dort (depends_on). Atomare Zuweisung (neue Liste).
        if context is not None and context.instance_id:
            context.shared_state[context.instance_id] = list(level_entries)

        # --- Feature-Store-Payload (05.08.2026, U15-E) -----------------------
        # Pro Bar: grid_nearest_level = center (naechstes Grid-Level zum close),
        # upper/lower = center +/- step_size (deterministische Klammer um den
        # close). Unabhaengig von show_lines – die Mathematik gilt immer.
        #
        # Phase 16 (05.08.2026): Numpy-Vektorisierung statt df.iterrows() –
        # 10k+ Lookback-Bars laufen in wenigen Millisekunden. Exakte Paritaet:
        #   * NaN/Inf-close wird uebersprungen (Alt-Pfad: round(NaN) wirft
        #     ValueError -> continue; np.isfinite liefert dieselbe Maske).
        #   * np.round (half-to-even) ist identisch zu Pythons round() fuer
        #     dieselben float64-Werte; step<=0 liefert close unveraendert
        #     (f_round_to_custom_step-Parität).
        #   * Nicht int-konvertierbare 'time'-Spalten (z.B. datetime64) fallen
        #     auf den identischen Zeilenpfad zurueck.
        feature_rows: List[Dict[str, Any]] = []
        if "time" in df.columns and "close" in df.columns and len(df):
            try:
                import numpy as np
                closes = df["close"].to_numpy(dtype=np.float64)
                t_raw = df["time"].to_numpy()
                if np.issubdtype(t_raw.dtype, np.datetime64):
                    # Datetime-Spalte: Zeilenpfad (Paritaet zur Alt-Logik).
                    raise TypeError("datetime-Spalte -> Zeilen-Fallback")
                times = t_raw.astype(np.int64)
                valid = np.isfinite(closes)
                if step_size > 0:
                    inv_step = 1.0 / step_size
                    centers = np.round(closes[valid] * inv_step) / inv_step
                else:
                    centers = closes[valid]
                ts_list = times[valid].tolist()
                c_list = [float(c) for c in centers.tolist()]
                for bar_ts_int, center in zip(ts_list, c_list):
                    feature_rows.append({
                        "bar_time": int(bar_ts_int),
                        "grid_nearest_level": center,
                        "grid_step": step_size,
                        "upper_level": round(center + step_size, 6),
                        "lower_level": round(center - step_size, 6),
                    })
            except (TypeError, ValueError):
                # Fallback: Spalten nicht numpy-konvertierbar – identischer
                # Zeilenpfad wie vor der Vektorisierung.
                for _i, row in df.iterrows():
                    try:
                        close_val = float(row["close"])
                        center = f_round_to_custom_step(close_val, step_size)
                    except (TypeError, ValueError, KeyError):
                        continue
                    bar_ts = row.get("time")
                    if bar_ts is None:
                        continue
                    try:
                        bar_ts_int = int(bar_ts)
                    except (TypeError, ValueError):
                        continue
                    feature_rows.append({
                        "bar_time": bar_ts_int,
                        "grid_nearest_level": center,
                        "grid_step": step_size,
                        "upper_level": round(center + step_size, 6),
                        "lower_level": round(center - step_size, 6),
                    })

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": feature_rows,
                "metadata": {
                    "schema_version": "1.0.0",
                    "step_size": step_size,
                },
            },
        }

```

--------------------------------------------------

### DATEI: analytics/features/definitions/srv_proximity.py
```py
# analytics/features/definitions/srv_proximity.py
"""
Service: Proximity (Phase 13 Schritt 6) – Naming Convention 16.08.01: srv_

Liest die Linienliste aus context.shared_state[depends_on[0]] (z. B. grid_1)
und wendet die PROZENTUALE visit%-Semantik des Alt-Grid-Indikators an
(Paritätsfunktionen in `grid_math.py`, Phase 15 U15-B3):

    visit_min = lvl * (1.0 - visit_pct / 100.0)
    visit_max = lvl * (1.0 + visit_pct / 100.0)
    touch_high = visit_min <= high <= visit_max
    touch_low  = visit_min <= low  <= visit_max
    pierce     = low <= lvl and high >= lvl

– NICHT die absolute threshold-Distanz des Alt-Plugins grid_liquidity.

Das native UTC-Zeitfenster (Minute 0/30 ± time_window_mins) wird pro Bar als
`in_time_window`-Flag in die Feature-Records geschrieben. Die FARBE der Kreise
(gelb im Fenster / fuchsia außerhalb) und die Sichtbarkeit (show_lines /
show_circles) sind KEINE Service-Parameter – sie werden vom INDIKATOR gesteuert
(chart/indicators/ind_fixed_grid_proximity.py), der die Circle-Farben auf Basis seines
eigenen Schemas (circle_color_std / circle_color_active) und des
`in_time_window`-Flags setzt (P16.01: `status_info` liegt als
metadata["statistics"] im feature_store_payload).

lookback (Scan-Fenster von rechts nach links) = min(statistics_signal_limit,
len(df)) aus context.settings. Der Service schreibt die Hit-Records nach
feature_data (feature_store=True) für Schritt 7 (Marker/Statistik).

Capabilities: render=False (P16.01), feature_store=True.

PARAMETER (PineScript-Input-Zone, 16.08.02 M3): Alle Inputs/Defaults stehen
als Modul-Konstante `_PROXIMITY_SCHEMA` direkt unter diesem Header (siehe
dort) und sind wie in PineScript am Dateianfang anpassbar. Die visuellen
Parameter (Farben/Sichtbarkeit) gehören NICHT zum Service – sie steuert der
Indikator (ind_fixed_grid_proximity).
"""

from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np

from analytics.features.definitions.grid_math import (
    f_in_window_around,
    f_strip_trailing_zeros,
)
from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 16.08.02 M3): Single Source of Truth
# fürs Prop-Fenster. Inputs/Defaults stehen hier direkt am Dateianfang
# (analog _FIXED_GRID_PROXIMITY_SCHEMA), damit sie wie in PineScript ohne
# Suchen anpassbar sind. `parameter_schema` gibt eine flache Kopie zurück
# (M1: kein geteiltes mutable Dict über Instanzen).
# ---------------------------------------------------------------------------
_PROXIMITY_SCHEMA: Dict[str, ParameterSchema] = {
    "visit_pct": {
        "type": "float", "default": 0.05, "min": 0.0, "max": 100.0,
        "step": 0.005, "description": "Prozentuale Toleranz um jede Linie (Parität zu grid_math.py visit_pct)",
    },
    "time_window_mins": {
        "type": "int", "default": 5, "min": 0, "max": 30,
        "step": 1, "description": "Time Filter Minuten um 0/30 UTC",
    },
    "use_time_filter": {
        "type": "bool", "default": True,
        "description": "Time Filter aktiv – steuert das in_window-Flag der Hits",
    },
}

# ---------------------------------------------------------------------------
# OUTPUT-SCHEMA (20.03): Resultatfelder je feature_data-Record.
# `bar_time` ist eine native DB-Spalte und wird NICHT deklariert (E4).
# `type` sind freie Strings (E5). `technical: True` -> kompakte Anzeige im
# Unterblock `🔧 System-Metrik` (E2).
# ---------------------------------------------------------------------------
_PROXIMITY_OUTPUT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "levels_hit": {
        "type": "list[float]",
        "description": "Getroffene Grid-Level der Bar (near/Piercing-Semantik, Parität grid_math.py)",
    },
    "is_hit": {
        "type": "bool",
        "description": "True, wenn die Bar mindestens ein Grid-Level trifft",
    },
    "in_time_window": {
        "type": "bool",
        "description": "True, wenn die Bar im nativen UTC-Zeitfenster (Minute 0/30 ± time_window_mins) liegt",
    },
    "time_window_mins": {
        "type": "int",
        "description": "Fenster-Minuten (Parameter-Abbild im Record)",
        "technical": True,
    },
    "use_time_filter": {
        "type": "bool",
        "description": "Time-Filter aktiv (Parameter-Abbild im Record)",
        "technical": True,
    },
    "visit_pct": {
        "type": "float",
        "description": "Prozentuale Toleranz um jede Linie (Parameter-Abbild im Record)",
        "technical": True,
    },
}

def _bar_utc_minutes(df: pd.DataFrame) -> List[int]:
    """UTC-Minute (0-59) jeder Bar – konsistent zu ind_fixed_grid_proximity.py.

    Phase 16 (05.08.2026): Vektorisierter Fast-Path fuer 'time'-Spalten
    (epoch-Sekunden, int) – (t // 60) % 60 ist mathematisch identisch zu
    datetime.fromtimestamp(t, tz=utc).minute (auch fuer negative Zeiten,
    Python/numpy-Floor-Division). Bereichs-Guard: Zeiten ausserhalb des
    datetime-basierten Alt-Bereichs fallen auf den OSError-Fallback zurueck
    (dort wird 0 gesetzt – exakte Alt-Paritaet).
    """
    if "time" in df.columns:
        try:
            import numpy as np
            t = df["time"].to_numpy(dtype=np.int64)
            if len(t) == 0 or (int(np.min(t)) >= -62135596800
                               and int(np.max(t)) < 253402300799):
                return [int(m) for m in ((t // 60) % 60).tolist()]
        except (TypeError, ValueError, OSError):
            pass
        out: List[int] = []
        for t in df["time"]:
            try:
                out.append(datetime.fromtimestamp(int(t), tz=dt_timezone.utc).minute)
            except (TypeError, ValueError, OSError):
                out.append(0)
        return out
    elif "bar_time" in df.columns:
        t = pd.to_datetime(df["bar_time"])
        if t.dt.tz is not None:
            out = t.dt.tz_convert("UTC").dt.minute.tolist()
        else:
            out = t.dt.minute.tolist()
    return [int(m) for m in out]


class ProximityService(PluginFeature):

    @property
    def plugin_id(self) -> str:
        return "srv_proximity"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, str]:
        return {
            "category": "Grid",
            "display_name": "Proximity",
            # Phase 16 (06.08.2026): Zugehoeriger Indikator-Name fuer die Status-
            # Badges im MasterTree (der Service laeuft IN Ind_FixedGridProximity).
            "indicator_name": "Ind_FixedGridProximity",
            # Phase 16 (06.08.2026): indicator_id = indicators_state-Key des
            # zugehoerigen Indikators. ServiceSelectorModel.is_active_in_chart()
            # prueft damit die Aktiv-Frage auf Indikator-Ebene (Tooltip
            # 'aktiv <Indikator>' statt nur 'im <Indikator>').
            "indicator_id": "ind_fixed_grid_proximity",

            "description": "Prozentuale visit%-Treffer auf den Grid-Linien (Parität zu grid_math.py) inkl. Feature-Store-Records",
            "author": "PyTrader AI",
            "tags": ["grid", "proximity", "liquidity", "feature-store"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Liest die Linienliste aus shared_state[depends_on] "
                                "und wendet die prozentuale visit%-Semantik der "
                                "Paritätsfunktionen (grid_math.py) an "
                                "(visit_min/max je Linie). Schreibt "
                                "Hit-Records in den Feature-Store.",
            "condition_rules": [
                "Treffer: visit_min <= high/low <= visit_max ODER Piercing (low <= lvl <= high)",
                "in_window-Flag: Minute 0/30 ± time_window_mins (UTC)",
                "Scan-Fenster: min(statistics_signal_limit, len(df)) von rechts",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": True,
            "batch": True,
            "live": False,
            "feature_store": True,  # schreibt Hit-Records nach feature_data
            # Phase 16 (P16.01, E5): render=False - der Service liefert KEINEN
            # chart_render_payload mehr; der Indikator baut das Styling.
            "render": False,
        }

    @property
    def dependencies(self) -> List[str]:
        """Vorab berechnete Service-Plugins (PluginFeature.dependencies).

        05.08.2026 (Bugfix Service-Run): proximity liest seine Linienliste aus
        context.shared_state[depends_on[0]] – dafuer muss eine vorgelagerte
        srv_grid_lines-Instanz in execution_order stehen. Gespeicherte Sets aus
        der UI-Pfade haben oft KEIN explizites depends_on; die Worker-
        Aufbereitung (serviceui/service_set_utils.prepare_worker_definition)
        loest daraus die implizite Abhaengigkeit auf (naechste VORHERIGE
        Instanz mit plugin_id in dependencies). Explizit gesetzte
        depends_on-Werte (z.B. Indikator-intern grid_1 -> prox_1) bleiben
        unveraendert gueltig.
        """
        return ["srv_grid_lines"]

    # --- Single Source of Truth fürs Prop-Fenster (Phase 13 Schritt 5) -------
    # Hinweis (Schritt 6-Korrektur 3): Die visuellen Parameter (show_circles,
    # circle_color_std, circle_color_active, show_lines) sind KEINE
    # Service-Parameter – sie gehören zum Indikator-Schema und werden dort
    # gesteuert (chart/indicators/ind_fixed_grid_proximity.py). Der Service meldet nur
    # das in_window-Flag; der Indikator färbt die Kreise.
    @property
    def parameter_order(self) -> List[str]:
        return [
            "visit_pct",
            "use_time_filter", "time_window_mins",
        ]

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "visit_pct": "Besuchs-Toleranz (%)",
            "use_time_filter": "Time Filter aktiv",
            "time_window_mins": "Time Filter Minuten (0/30)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_PROXIMITY_SCHEMA` (16.08.02 M3).

        Inhalt/Reihenfolge identisch zur vorherigen Inline-Property – nur die
        Position des Dict-Literals hat sich an den Dateianfang verschoben
        (PineScript-Input-Zone, kein geteiltes mutable Dict: flache Kopie).
        """
        return {k: dict(v) for k, v in _PROXIMITY_SCHEMA.items()}

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): flache Kopie der Modul-Konstante
        `_PROXIMITY_OUTPUT_SCHEMA` (PineScript-Input-Zone, M1: kein
        geteiltes mutable Dict)."""
        return {k: dict(v) for k, v in _PROXIMITY_OUTPUT_SCHEMA.items()}

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Wendet die prozentuale visit%-Semantik der Paritätsfunktionen
        (grid_math.py) auf die Linien aus context.shared_state[depends_on[0]]
        an und schreibt Hit-Records nach feature_data (feature_store=True).

        Phase 16 (P16.01, E3/E4/E5): Der Service liefert KEINEN
        chart_render_payload mehr (render=False). `status_info`
        {in_time_window, active_hits} wird in metadata["statistics"] des
        feature_store_payload ausgelagert und vom Indikator
        (build_chart_render_payload) uebernommen."""
        empty: FeatureCalculateResult = {
            "feature_store_payload": {},
        }
        if df is None or df.empty:
            return empty

        # --- Linien aus dem shared_state des abhängigen Services lesen -------
        dep_id: Optional[str] = None
        if context is not None:
            deps = context.depends_on or []
            dep_id = deps[0] if deps else None
        lines_payload: List[Dict[str, Any]] = []
        if context is not None and dep_id is not None:
            shared = context.shared_state.get(dep_id)
            if isinstance(shared, list):
                lines_payload = shared
            elif isinstance(shared, dict):
                lines_payload = shared.get("lines") or []

        if not lines_payload:
            # Keine Linien verfügbar (z. B. Direkt-Aufruf ohne Pipeline) →
            # kein Proximity möglich. Fail-Fast würde der Evaluator ohnehin
            # werfen; hier defensiv leer zurückgeben.
            return empty

        p = self.validate_params(params)
        visit_pct = float(p["visit_pct"])
        time_window_mins = int(p["time_window_mins"])
        use_time_filter = bool(p["use_time_filter"])

        # --- Scan-Fenster von rechts nach links: min(statistics_signal_limit, len(df))
        limit = len(df)
        if context is not None and context.settings is not None:
            try:
                sig_limit = int(getattr(context.settings, "statistics_signal_limit", 0))
                if sig_limit > 0:
                    limit = min(sig_limit, limit)
            except (TypeError, ValueError):
                pass
        scan_df = df.tail(limit)

        # tracked_levels: IMMER aus der Linienliste – Sichtbarkeit (show_lines)
        # steuert der GridLinesService (liefert bei show_lines=false gar keine
        # Linien) bzw. der Indikator. show_lines ist KEIN Service-Parameter.
        tracked_levels = [float(l["price"]) for l in lines_payload]

        # --- Proximity & Hit-Logik (exakte Parität zu grid_math.py) ----------
        # Phase 16 (05.08.2026): Numpy-Vektorisierung statt der O(n*m)-Double-
        # Loop (df.iterrows() x tracked_levels). Bei 10k+ Lookback-Bars sinkt
        # die Rechenzeit von mehreren Sekunden auf wenige Millisekunden.
        # Parität:
        #   * near = (visit_min <= high <= visit_max) | (visit_min <= low <=
        #     visit_max) | (low <= lvl <= high) – identische Vergleichs-
        #     Semantik zu grid_math.py.
        #   * NaN high/low propagieren in den Vergleichen zu False (kein Hit)
        #     – wie im Alt-Pfad (Float-Vergleich mit NaN ist False).
        #   * Reihung levels_hit: zeilen-major, innerhalb einer Zeile in
        #     tracked_levels-Reihenfolge (lexsort über Zeile+Level).
        # Phase 16 (P16.01, E4): hit_circles werden NICHT mehr erzeugt – der
        # Indikator baut sie aus den feature_rows (levels_hit/in_time_window).
        active_hits: List[str] = []
        feature_rows: List[Dict[str, Any]] = []

        n = len(scan_df)
        minutes = _bar_utc_minutes(scan_df)
        if n:
            times = scan_df["time"].to_numpy(dtype=np.int64)
            high = scan_df["high"].to_numpy(dtype=np.float64)
            low = scan_df["low"].to_numpy(dtype=np.float64)
            levels_arr = np.array(tracked_levels, dtype=np.float64)
            in_win = np.array([
                (f_in_window_around(m, 0, time_window_mins)
                 or f_in_window_around(m, 30, time_window_mins))
                for m in minutes
            ], dtype=bool)

            levels_hit: List[List[float]] = [[] for _ in range(n)]
            if len(levels_arr):
                factor = visit_pct / 100.0
                vmin = levels_arr * (1.0 - factor)
                vmax = levels_arr * (1.0 + factor)
                # Broadcasting: (len(levels), n)-Bool-Matrix – jede Zeile ist
                # ein Level, jede Spalte eine Bar.
                near = (
                    ((vmin[:, None] <= high[None, :]) & (high[None, :] <= vmax[:, None]))
                    | ((vmin[:, None] <= low[None, :]) & (low[None, :] <= vmax[:, None]))
                    | ((low[None, :] <= levels_arr[:, None]) & (high[None, :] >= levels_arr[:, None]))
                )
                # np.nonzero liefert (Achse-0 = Level, Achse-1 = Bar).
                lvl_idxs, bar_idxs = np.nonzero(near)
                if len(lvl_idxs):
                    # Zeilen-major (Bar aussen) + Level-Reihenfolge innen
                    # (stabil) – identische Abfolge wie die Alt-Double-Loop.
                    order = np.lexsort((lvl_idxs, bar_idxs))
                    bar_sorted = bar_idxs[order]
                    lvl_sorted = lvl_idxs[order]
                    starts = np.concatenate(
                        ([0], np.flatnonzero(np.diff(bar_sorted) != 0) + 1))
                    ends = np.concatenate((starts[1:], [len(bar_sorted)]))
                    last_pos = n - 1
                    for s, e in zip(starts, ends):
                        r = int(bar_sorted[s])
                        lvls = [float(x) for x in levels_arr[lvl_sorted[s:e]]]
                        levels_hit[r] = lvls
                        if r == last_pos:
                            active_hits.extend(
                                f_strip_trailing_zeros(v) for v in lvls)

            feature_rows = []
            for pos in range(n):
                feature_rows.append({
                    "bar_time": int(times[pos]),
                    "levels_hit": levels_hit[pos],
                    "is_hit": bool(levels_hit[pos]),
                    "in_time_window": bool(in_win[pos]),
                    "time_window_mins": time_window_mins,
                    "use_time_filter": use_time_filter,
                    "visit_pct": visit_pct,
                })

        # --- Status-Info (letzte Bar des Scan-Fensters, Parität zu grid_math.py)
        if len(scan_df):
            last_ts = int(scan_df.iloc[-1]["time"])
            last_m = datetime.fromtimestamp(last_ts, tz=dt_timezone.utc).minute
            full_win = f_in_window_around(last_m, 0, time_window_mins)
            half_win = f_in_window_around(last_m, 30, time_window_mins)
            in_time_window_raw = full_win or half_win
            in_time_window = in_time_window_raw if use_time_filter else True
        else:
            in_time_window = False

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": feature_rows,
                "metadata": {
                    "total_hits": sum(
                        len(r.get("levels_hit") or []) for r in feature_rows),
                    "depends_on": dep_id,
                    "scan_limit": limit,
                    "visit_pct": visit_pct,
                    # P14-03 (Invariante 5): explizite schema_version in jedem
                    # Feature-Payload – der Indikator-Lesepfad (feature_data)
                    # prüft sie beim Chart-Re-Render.
                    "schema_version": "1.0.0",
                    # Phase 16 (P16.01, E4): status_info als Feature-Daten
                    # (KEINE Farben) – der Indikator übernimmt sie in
                    # build_chart_render_payload().
                    "statistics": {
                        "in_time_window": in_time_window,
                        "active_hits": active_hits,
                    },
                },
            },
        }

```

--------------------------------------------------

### DATEI: analytics/features/definitions/srv_swing_momentum.py
```py
# analytics/features/definitions/srv_swing_momentum.py
# ==============================================================================
# DEFINITION: srv_swing_momentum
# ==============================================================================
# NAME:        Swing Momentum Service
# KATEGORIE:   Swing Points/Dynamik & Filter
# BESCHREIBUNG: Wendepunkts-Erkennung über MA-Hysteresen, Steigungswechsel & Chande-Kroll
# ==============================================================================
"""
Service: SwingMomentum (Phase 17.01) – Naming Convention 16.08.01: srv_

Erfasst Richtungswechsel ueber Glättungs-Hysteresen (alle 12 MA-Typen des
MA-Templates 16.04), Steigungswechsel und Trailing-Stops (Chande Kroll).
Reiner Datenlieferant fuer die Analytics-UI und spaetere ML-Pipelines –
KEINE Chart-Visualisierung in diesem Kapitel (17.01, §1).

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt des tatsaechlichen Extremums.
  * confirmation_bar_time: Zeitpunkt, an dem das Signal kausal feststand
                           (bar_time der aktuellen Kerze).
  * confirmation_lag_bars: dynamische Differenz in Bars
                           (params['period'] bzw. Modus-Verzoegerung).
  * Kerzen am Serienanfang ohne ausreichenden Lookback/Lookahead erhalten
    calculation_status = 'INSUFFICIENT_DATA' und is_swing_* = False.

Persistenz: feature_store_payload mit feature_id='srv_swing_momentum'
(Datenvertrag 17.01 §4). Seit 17.01 (E-1, PK-Migration) koennen mehrere
Services konfliktfrei auf derselben Kerze gespeichert werden.

Capabilities (E-5, 07.08.2026): chart=False, batch=True, live=False,
feature_store=True, render=False.
metadata['category'] = 'Swing Points/Dynamik & Filter' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_SWING_MOMENTUM_SCHEMA` direkt unter diesem Header.
`parameter_schema` gibt eine flache Kopie zurueck (M1).
E-2 (07.08.2026): type-Werte als Strings.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 17.01): Single Source of Truth fuer das
# Prop-Fenster. Inputs/Defaults stehen hier direkt am Dateianfang.
# `parameter_schema` gibt eine flache Kopie zurueck (M1).
# E-2 (07.08.2026): type-Werte als Strings.
# ---------------------------------------------------------------------------
_SWING_MOMENTUM_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "MA_Peak_Hysteresis",
        "options": [
            "MA_Peak_Hysteresis", "MA_Slope_Change", "Chande_Kroll_Ratchet",
        ],
        "description": "Algorithmus-Modus für Momentum-Swings",
    },
    "ma_type": {
        "type": "str",
        "default": "EHMA",
        "options": [
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA",
        ],
        "description": "Gleitender Durchschnittstyp (MA-Template 16.04)",
        "visible_when": {"mode": ["MA_Peak_Hysteresis", "MA_Slope_Change"]},
    },
    "period": {
        "type": "int", "default": 14, "min": 2,
        "description": "Berechnungsperiode für Glättungs-MA",
        "visible_when": {"mode": ["MA_Peak_Hysteresis", "MA_Slope_Change"]},
    },
    "piv_maxMaMovePct": {
        "type": "float", "default": 0.2, "min": 0.01,
        "description": "Erforderliche Gegenbewegung in % für MA Peak Pivot (gültig für alle ma_type-Optionen)",
        "visible_when": {"mode": "MA_Peak_Hysteresis"},
    },
    "chande_lookback": {
        "type": "int", "default": 10, "min": 1,
        "description": "Lookback-Periode für Highest-High/Lowest-Low im Chande_Kroll_Ratchet Modus",
        "visible_when": {"mode": "Chande_Kroll_Ratchet"},
    },
    "x_atr": {
        "type": "float", "default": 3.0, "min": 0.5,
        "description": "ATR-Multiplikator für Chande Kroll Stops",
        "visible_when": {"mode": "Chande_Kroll_Ratchet"},
    },
}

# ---------------------------------------------------------------------------
# OUTPUT-SCHEMA (20.03): Resultatfelder je feature_data-Record (Datenvertrag
# 17.01 §4). `bar_time` ist eine native DB-Spalte und wird NICHT deklariert
# (E4). `type` sind freie Strings (E5). `technical: True` -> kompakte
# Anzeige im Unterblock `🔧 System-Metrik` (E2).
# ---------------------------------------------------------------------------
_SWING_MOMENTUM_OUTPUT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "result_type": {
        "type": "str",
        "description": "Klassifikation des Records (immer 'SWING')",
        "technical": True,
    },
    "source_mode": {
        "type": "str",
        "description": "Aktiver Algorithmus-Modus (MA_Peak_Hysteresis/MA_Slope_Change/Chande_Kroll_Ratchet)",
        "technical": True,
    },
    "calculation_status": {
        "type": "str",
        "description": "Berechnungsstatus ('OK' | 'INSUFFICIENT_DATA')",
        "technical": True,
    },
    "is_swing_high": {
        "type": "bool",
        "description": "True, wenn die Bar ein bestätigtes Swing-High ist",
    },
    "is_swing_low": {
        "type": "bool",
        "description": "True, wenn die Bar ein bestätigtes Swing-Low ist",
    },
    "is_rejection": {
        "type": "bool",
        "description": "Rejection-Flag (Momentum: immer False)",
    },
    "event_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch des tatsächlichen Extremums (kausal, kein Look-ahead)",
        "technical": True,
    },
    "confirmation_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch, an der das Signal kausal feststand",
        "technical": True,
    },
    "confirmation_lag_bars": {
        "type": "int",
        "description": "Dynamische Bestätigungs-Verzögerung in Bars",
        "technical": True,
    },
    "confirmation_type": {
        "type": "str",
        "description": "Bestätigungsart (immer 'CAUSAL')",
        "technical": True,
    },
    "price": {
        "type": "float",
        "description": "Preis des Extremums (MA-/High-/Low-Wert) bzw. Close bei Nicht-Swing-Bars",
    },
    "strength_value": {
        "type": "float",
        "description": "Signalstärke (PERCENT: Gegenbewegung %; NORMALIZED: |Steigung|; ATR_MULTIPLE: ATR-Einheiten)",
    },
    "strength_type": {
        "type": "str",
        "description": "Stärke-Maßstab ('PERCENT' | 'NORMALIZED' | 'ATR_MULTIPLE')",
        "technical": True,
    },
}

# ---------------------------------------------------------------------------
# Modul-Helfer (17.01.02: echte Swing-Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-ATR (EMA-alpha 1/period, adjust=False) ueber OHLCV.

    Liefert NaN fuer Bars ohne ausreichende Historie (min_periods=period) –
    diese Bars werden als INSUFFICIENT_DATA markiert (Chande_Kroll_Ratchet).
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / max(1, period), min_periods=max(1, period),
                  adjust=False).mean()


def _detect_ma_hysteresis(ma: np.ndarray,
                          change_pct: float,
                          ) -> Tuple[np.ndarray, np.ndarray,
                                     Dict[int, Tuple[int, str, float]]]:
    """MA-Peak-Hysterese: alternierend wird ein laufendes MA-Extremum
    mitgefuehrt; erst wenn sich das MA um >= `change_pct` % gegen das
    Extremum bewegt, ist der Pivot bestaetigt (kausal am aktuellen Bar).

    Rueckgabe: (is_swing_high, is_swing_low, pivot_info) –
    pivot_info {ext_idx: (conf_idx, 'high'|'low', move_pct)}.
    """
    n = len(ma)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    pivot_info: Dict[int, Tuple[int, str, float]] = {}
    if n < 2:
        return is_high, is_low, pivot_info
    direction = 1  # 1 = auf der Jagd nach Swing-High, -1 = Swing-Low
    ext_idx = -1
    ext_price = np.nan
    for i in range(1, n):
        cur = float(ma[i])
        if not np.isfinite(cur):
            continue
        # Warmup-NaN (MA-Typen ohne Fruehwert) ueberspringen: erstes finites
        # MA-Extremum als Startpunkt setzen (17.01.02 Bugfix – sonst bleibt
        # der Zustand dauerhaft auf NaN haengen -> 0 Swings).
        if not np.isfinite(ext_price):
            ext_idx, ext_price = i, cur
            continue
        if direction == 1:
            if cur > ext_price:
                ext_idx, ext_price = i, cur
            elif abs(ext_price) > 0.0 and (ext_price - cur) / abs(ext_price) * 100.0 >= change_pct:
                is_high[ext_idx] = True
                pivot_info[ext_idx] = (i, "high",
                                       (ext_price - cur) / abs(ext_price) * 100.0)
                direction = -1
                ext_idx, ext_price = i, cur
        else:
            if cur < ext_price:
                ext_idx, ext_price = i, cur
            elif abs(ext_price) > 0.0 and (cur - ext_price) / abs(ext_price) * 100.0 >= change_pct:
                is_low[ext_idx] = True
                pivot_info[ext_idx] = (i, "low",
                                       (cur - ext_price) / abs(ext_price) * 100.0)
                direction = 1
                ext_idx, ext_price = i, cur
    return is_high, is_low, pivot_info


def _detect_ma_slope(ma: np.ndarray,
                     ) -> Tuple[np.ndarray, np.ndarray,
                                Dict[int, Tuple[int, str, float]]]:
    """MA-Steigungswechsel: Swing-High, wenn die MA-Steigung von positiv auf
    <= 0 dreht (MA-Peak), Swing-Low beim Uebergang von negativ auf >= 0.
    Event = letzte Bar des alten Vorzeichens (Peak/Tief), Confirmation =
    aktuelle Bar (kausal)."""
    n = len(ma)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    pivot_info: Dict[int, Tuple[int, str, float]] = {}
    if n < 3:
        return is_high, is_low, pivot_info
    slope = np.diff(ma)
    for i in range(1, n):
        if not np.isfinite(ma[i]) or not np.isfinite(ma[i - 1]):
            continue
        if i - 1 >= 1 and np.isfinite(slope[i - 2]):
            if slope[i - 2] > 0 and slope[i - 1] <= 0:
                is_high[i - 1] = True
                pivot_info[i - 1] = (i, "high", float(slope[i - 1]))
            elif slope[i - 2] < 0 and slope[i - 1] >= 0:
                is_low[i - 1] = True
                pivot_info[i - 1] = (i, "low", abs(float(slope[i - 1])))
    return is_high, is_low, pivot_info


def _detect_chande_kroll(df: pd.DataFrame, lookback: int, x_atr: float,
                         atr: np.ndarray,
                         ) -> Tuple[np.ndarray, np.ndarray,
                                    Dict[int, Tuple[int, str, float]]]:
    """Chande-Kroll-Ratchet: Trailing-Stop = Highest-High/Lowest-Low ueber
    `lookback` ± x_atr × ATR. Verlassen des Stopps durch den Schlusskurs
    bestaetigt das vorherige Extremum (kausal am aktuellen Bar)."""
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    pivot_info: Dict[int, Tuple[int, str, float]] = {}
    if n < 2:
        return is_high, is_low, pivot_info
    s_hi = pd.Series(hi).rolling(lookback, min_periods=1).max().to_numpy()
    s_lo = pd.Series(lo).rolling(lookback, min_periods=1).min().to_numpy()
    direction = 1  # 1 = Aufwaerts-Ratchet (Swing-Highs), -1 = Abwaerts
    for i in range(1, n):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        if direction == 1:
            stop = s_hi[i] - x_atr * a
            if close[i] < stop:
                j0 = max(0, i - lookback + 1)
                ext_idx = j0 + int(np.argmax(hi[j0:i + 1]))
                is_high[ext_idx] = True
                pivot_info[ext_idx] = (i, "high", s_hi[i] - stop)
                direction = -1
        else:
            stop = s_lo[i] + x_atr * a
            if close[i] > stop:
                j0 = max(0, i - lookback + 1)
                ext_idx = j0 + int(np.argmin(lo[j0:i + 1]))
                is_low[ext_idx] = True
                pivot_info[ext_idx] = (i, "low", stop - s_lo[i])
                direction = 1
    return is_high, is_low, pivot_info


class SrvSwingMomentum(PluginFeature):
    """Dynamik- & MA-Hysterese-Swings.

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) – keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_swing_momentum"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Swing Points/Dynamik & Filter",
            "display_name": "Swing Momentum Service",
            "description": "Dynamische Momentum-Swings via MA-Hysterese, Steigung & Chande Kroll",
            "author": "PyTrader AI",
            "tags": ["swing", "momentum", "ma", "hysteresis", "chande-kroll"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) für "
                                "die Analytics-UI und ML-Pipelines. Erkennt "
                                "Richtungswechsel über MA-Peak-Hysterese (alle "
                                "12 MA-Typen des Templates 16.04), "
                                "MA-Steigungswechsel und Chande-Kroll-Ratchet "
                                "(ATR-Stopps). Keine Chart-Visualisierung in "
                                "Kapitel 17.01.",
            "condition_rules": [
                "MA_Peak_Hysteresis: Pivot erst bei Gegenbewegung >= piv_maxMaMovePct %",
                "MA_Slope_Change: Richtungswechsel der MA-Steigung (Vorzeichen des Differentials)",
                "Chande_Kroll_Ratchet: Stopps = Highest-High/Lowest-Low über chande_lookback ± x_atr × ATR",
                "alle 12 MA-Typen: SMA/EMA/WMA/DEMA/TEMA/HMA/EHMA/ZLEMA/RMA/KAMA/ALMA/VWMA",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": False,   # E-5: kein Indikator in Kapitel 17.01
            "batch": True,
            "live": False,
            "feature_store": True,
            "render": False,  # E-5: reine Datenlieferanten
        }

    # --- Single Source of Truth fürs Prop-Fenster (17.01 §2.2, PineScript-Zone)
    @property
    def parameter_order(self) -> List[str]:
        return list(_SWING_MOMENTUM_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Algorithmus-Modus",
            "ma_type": "Gleitender Durchschnittstyp",
            "period": "Berechnungsperiode",
            "piv_maxMaMovePct": "Gegenbewegung % (MA Peak Pivot)",
            "chande_lookback": "Lookback (Chande Kroll)",
            "x_atr": "ATR-Multiplikator (Chande Kroll Stops)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_SWING_MOMENTUM_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _SWING_MOMENTUM_SCHEMA.items()}

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): flache Kopie der Modul-Konstante
        `_SWING_MOMENTUM_OUTPUT_SCHEMA` (PineScript-Input-Zone, M1: kein
        geteiltes mutable Dict)."""
        return {k: dict(v) for k, v in _SWING_MOMENTUM_OUTPUT_SCHEMA.items()}

    # 2. SCHEMA-EXPOSURE FÜR DIE UI (07.08.2026, Bugfix): Die Spalten-UI
    # (serviceui/param_columns.py & ServiceSelectorWidget) liest Parameter-
    # Definitionen über `default_params` / `full_parameter_schema()`. Diese
    # expliziten Overrides stellen das Schema unabhängig von der jeweiligen
    # parameter_schema-Definition (Property/Klassen-Attribut) bereit und
    # erhalten den Basisklassen-Vertrag (Basis-Parameter wie lookback + 
    # plugin-spezifische Parameter, vgl. base_plugin.PluginFeature).
    @property
    def default_params(self) -> Dict[str, Any]:
        """Extrahiert die Default-Werte aus dem parameter_schema für die Engine."""
        return {k: v.get("default") for k, v in self.parameter_schema.items()
                if "default" in v}

    def full_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Liefert das vollständige Schema (Basis + plugin-spezifisch) inkl.
        Min/Max/Typ für die UI-Spalten (Basisklassen-Vertrag)."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Momentum-Swings (MA-Hysterese, Steigung, Chande Kroll).

        17.01.02 (Bugfix-Runde): Echte Erkennung ersetzt den Scaffold
        (vorher records=[], daher '0 Feature-Row(s)' im Store + irrefuehrende
        Meldung 'Keine OHLCV-Daten' im ServiceRunWorker).

        Datenvertrag (17.01 §4): JEDER Bar entspricht genau EIN Record
        (dichte Label-Reihe). Swing-Bars tragen is_swing_high/is_swing_low
        sowie kausale Zeitstempel. Bars am Serienanfang ohne ausreichenden
        Lookback (MA-/ATR-Warmup) erhalten calculation_status=
        'INSUFFICIENT_DATA' (is_swing_* = False).

        Modi (params['mode']):
          * MA_Peak_Hysteresis: MA (alle 12 Typen, Template 16.04) – Pivot
            erst bei Gegenbewegung >= piv_maxMaMovePct % (strength PERCENT).
          * MA_Slope_Change: Vorzeichenwechsel der MA-Steigung (strength
            NORMALIZED, |Steigung|).
          * Chande_Kroll_Ratchet: Trailing-Stop = Highest-High/Lowest-Low
            ueber chande_lookback ± x_atr × ATR (strength ATR_MULTIPLE).
        """
        empty: FeatureCalculateResult = {"feature_store_payload": {}}
        if df is None or df.empty:
            return empty

        # Defensive Normalisierung: 'time'-Spalte (epoch) sicherstellen.
        work = df.copy()
        if "time" not in work.columns:
            if "bar_time" in work.columns:
                work["time"] = work["bar_time"].apply(
                    lambda v: int(v.timestamp())
                    if hasattr(v, "timestamp") else int(v))
            else:
                return empty

        p = self.validate_params(params)
        mode = str(p.get("mode") or "MA_Peak_Hysteresis")
        ma_type = str(p.get("ma_type") or "EHMA")
        period = int(p.get("period") or 14)
        move_pct = float(p.get("piv_maxMaMovePct") or 0.2)
        chande_lookback = int(p.get("chande_lookback") or 10)
        x_atr = float(p.get("x_atr") or 3.0)

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)
        atr = _atr_series(work, period).to_numpy(dtype=float)

        # MA-Serie (Template 16.04, alle 12 Typen; VWMA nutzt tick_volume).
        try:
            from chart.indicators.utils.ma_template import MATemplateEngine
        except Exception:
            MATemplateEngine = None  # type: ignore
        if MATemplateEngine is not None and ma_type in (
                "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
                "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"):
            volume = work["tick_volume"] if "tick_volume" in work.columns else None
            ma = MATemplateEngine.calculate_ma(
                work["close"], ma_type, period, volume=volume,
            ).to_numpy(dtype=float)
        else:
            # Fallback: einfacher SMA (defensiv, kein Crash).
            ma = pd.Series(close).rolling(period, min_periods=1).mean().to_numpy()

        is_high = np.zeros(n, dtype=bool)
        is_low = np.zeros(n, dtype=bool)
        # Kausale Bestaetigung je Swing-Bar: {idx: (conf_idx, lag, price)}
        swing_meta: Dict[int, Tuple[int, int, float]] = {}
        status = np.full(n, "OK", dtype=object)
        strength = np.zeros(n, dtype=float)
        strength_type = "NORMALIZED"
        conf_type = "CAUSAL"

        # MA-Warmup-Bars ohne Wert -> INSUFFICIENT_DATA.
        ma_nan = ~np.isfinite(ma)
        if ma_nan.any():
            status[ma_nan] = "INSUFFICIENT_DATA"

        if mode == "MA_Peak_Hysteresis":
            is_high, is_low, pivot_info = _detect_ma_hysteresis(ma, move_pct)
            strength_type = "PERCENT"
            for idx, (conf_idx, kind, move) in pivot_info.items():
                price = float(ma[idx])
                swing_meta[idx] = (conf_idx, conf_idx - idx, price)
                strength[idx] = move

        elif mode == "MA_Slope_Change":
            is_high, is_low, pivot_info = _detect_ma_slope(ma)
            for idx, (conf_idx, _kind, move) in pivot_info.items():
                price = float(ma[idx])
                swing_meta[idx] = (conf_idx, conf_idx - idx, price)
                strength[idx] = move

        elif mode == "Chande_Kroll_Ratchet":
            atr_nan = ~np.isfinite(atr)
            if atr_nan.any():
                status[atr_nan] = "INSUFFICIENT_DATA"
            is_high, is_low, pivot_info = _detect_chande_kroll(
                work, chande_lookback, x_atr, atr)
            strength_type = "ATR_MULTIPLE"
            for idx, (conf_idx, kind, move) in pivot_info.items():
                price = float(work["high"].iloc[idx] if kind == "high"
                              else work["low"].iloc[idx])
                swing_meta[idx] = (conf_idx, conf_idx - idx, price)
                strength[idx] = move / atr[idx] if np.isfinite(atr[idx]) and atr[idx] > 0 else 0.0

        else:
            # Unbekannter Modus: defensiv leer (kein Crash, 0 Rows).
            return empty

        # --- Records bauen (dicht: 1 Record pro Bar, 17.01 §4) ----------------
        records: List[Dict[str, Any]] = []
        total_high = int(is_high.sum())
        total_low = int(is_low.sum())
        for i in range(n):
            is_sh = bool(is_high[i])
            is_sl = bool(is_low[i])
            conf_idx, lag, price = swing_meta.get(i, (i, 0, 0.0))
            conf_idx = min(max(conf_idx, 0), n - 1)
            if not (is_sh or is_sl):
                price = float(close[i])
            records.append({
                "bar_time": int(times[i]),
                "result_type": "SWING",
                "source_mode": mode,
                "calculation_status": str(status[i]),
                "is_swing_high": is_sh,
                "is_swing_low": is_sl,
                "is_rejection": False,
                "event_bar_time": int(times[i]),
                "confirmation_bar_time": int(times[conf_idx]),
                "confirmation_lag_bars": int(lag),
                "confirmation_type": conf_type,
                "price": float(price),
                "strength_value": float(strength[i]),
                "strength_type": strength_type,
            })

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {
                    # E-7 / base_plugin (U15-A1, Invariante 5): schema_version
                    # ist Pflichtfeld fuer alle feature_store=True-Plugins.
                    "schema_version": "1.0.0",
                    "source_mode": mode,
                    "total_swing_highs": total_high,
                    "total_swing_lows": total_low,
                    "bars": n,
                },
            },
        }

```

--------------------------------------------------

### DATEI: analytics/features/definitions/srv_swing_structure.py
```py
# analytics/features/definitions/srv_swing_structure.py
# ==============================================================================
# DEFINITION: srv_swing_structure
# ==============================================================================
# NAME:        Swing Structure Service
# KATEGORIE:   Swing Points/Geometrie
# BESCHREIBUNG: Extrahierte Swing Highs/Lows über Fraktale, Pivots, Gann & ZigZag
# ==============================================================================
"""
Service: SwingStructure (Phase 17.01) – Naming Convention 16.08.01: srv_

Erfasst lokale Extrema ueber Fraktale, Pivots, Gann Swings, Period Extrema
(PDH/PWH) und ZigZag. Reiner Datenlieferant fuer die Analytics-UI und
spaetere ML-Pipelines (XGBoost/LightGBM) – KEINE Chart-Visualisierung in
diesem Kapitel (17.01, §1); dedizierte Chart-Indikatoren (ind_...) folgen
erst nach statistischer Validierung der erzeugten Features.

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt (Epoch) des tatsaechlichen Extremums.
  * confirmation_bar_time: Zeitpunkt, an dem das Signal mathematisch/kausal
                           feststand (bar_time der aktuellen Kerze).
  * confirmation_lag_bars: dynamisch berechnete Differenz in Bars
                           (params['right_bars'] bzw. Modus-Verzoegerung).
  * Kerzen am Serienanfang ohne ausreichenden Lookback/Lookahead erhalten
    calculation_status = 'INSUFFICIENT_DATA' und is_swing_* = False.

Persistenz: feature_store_payload mit feature_id='srv_swing_structure'
(Datenvertrag 17.01 §4). Seit 17.01 (E-1, PK-Migration) koennen mehrere
Services konfliktfrei auf derselben Kerze gespeichert werden
(PK (symbol, timeframe, bar_time, feature_id)).

Capabilities (E-5, 07.08.2026): chart=False (kein Indikator in diesem
Kapitel), batch=True, live=False, feature_store=True, render=False.
metadata['category'] = 'Swing Points/Geometrie' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_SWING_STRUCTURE_SCHEMA` direkt unter diesem Header
(siehe dort) und sind wie in PineScript am Dateianfang anpassbar.
`parameter_schema` gibt eine flache Kopie zurueck (M1: kein geteiltes
mutable Dict ueber Instanzen).
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 17.01): Single Source of Truth fuer das
# Prop-Fenster. Inputs/Defaults stehen hier direkt am Dateianfang.
# `parameter_schema` gibt eine flache Kopie zurueck (M1).
# E-2 (07.08.2026): type-Werte als Strings ("int"/"float"/"str") – die
# Basisklasse (base_plugin.validate_params) vergleicht string-basiert.
# ---------------------------------------------------------------------------
_SWING_STRUCTURE_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "Williams_Fractal",
        "options": [
            "Williams_Fractal", "Standard_Pivot", "Gann_Mechanical",
            "ZigZag_ATR", "ZigZag_Pct", "Period_Extrema",
        ],
        "description": "Erkennungs-Modus für Strukturswings",
    },
    "left_bars": {
        "type": "int", "default": 2, "min": 1,
        "description": "Anzahl erforderlicher Kerzen links mit niedrigeren Hochs / höheren Tiefs",
        "visible_when": {"mode": ["Williams_Fractal", "Standard_Pivot", "Gann_Mechanical"]},
    },
    "right_bars": {
        "type": "int", "default": 2, "min": 1,
        "description": "Anzahl Bestätigungskerzen rechts (bestimmt dynamisch confirmation_lag_bars)",
        "visible_when": {"mode": ["Williams_Fractal", "Standard_Pivot", "Gann_Mechanical"]},
    },
    "atr_period": {
        "type": "int", "default": 14, "min": 1,
        "description": "ATR-Periode für ZigZag_ATR",
        "visible_when": {"mode": "ZigZag_ATR"},
    },
    "atr_mult": {
        "type": "float", "default": 2.0, "min": 0.1,
        "description": "ATR-Multiplikator für ZigZag_ATR",
        "visible_when": {"mode": "ZigZag_ATR"},
    },
    "change_pct": {
        "type": "float", "default": 0.5, "min": 0.05,
        "description": "Mindestprozentbewegung für ZigZag_Pct",
        "visible_when": {"mode": "ZigZag_Pct"},
    },
    "period_extrema_type": {
        "type": "str",
        "default": "PREVIOUS_CLOSED",
        "options": ["PREVIOUS_CLOSED", "CURRENT_DEVELOPING"],
        "description": "PREVIOUS_CLOSED (z. B. PDH/PWH final) oder CURRENT_DEVELOPING",
        "visible_when": {"mode": "Period_Extrema"},
    },
}

# ---------------------------------------------------------------------------
# OUTPUT-SCHEMA (20.03): Resultatfelder je feature_data-Record (Datenvertrag
# 17.01 §4). `bar_time` ist eine native DB-Spalte und wird NICHT deklariert
# (E4). `type` sind freie Strings (E5). `technical: True` -> kompakte
# Anzeige im Unterblock `🔧 System-Metrik` (E2).
# ---------------------------------------------------------------------------
_SWING_STRUCTURE_OUTPUT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "result_type": {
        "type": "str",
        "description": "Klassifikation des Records (immer 'SWING')",
        "technical": True,
    },
    "source_mode": {
        "type": "str",
        "description": "Aktiver Erkennungs-Modus (Williams_Fractal/Standard_Pivot/Gann_Mechanical/ZigZag_*/Period_Extrema)",
        "technical": True,
    },
    "calculation_status": {
        "type": "str",
        "description": "Berechnungsstatus ('OK' | 'INSUFFICIENT_DATA')",
        "technical": True,
    },
    "is_swing_high": {
        "type": "bool",
        "description": "True, wenn die Bar ein bestätigtes Swing-High ist",
    },
    "is_swing_low": {
        "type": "bool",
        "description": "True, wenn die Bar ein bestätigtes Swing-Low ist",
    },
    "is_rejection": {
        "type": "bool",
        "description": "Rejection-Flag (Struktur: immer False)",
    },
    "event_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch des tatsächlichen Extremums (kausal, kein Look-ahead)",
        "technical": True,
    },
    "confirmation_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch, an der das Signal kausal feststand",
        "technical": True,
    },
    "confirmation_lag_bars": {
        "type": "int",
        "description": "Dynamische Bestätigungs-Verzögerung in Bars (right_bars bzw. Modus-Verzögerung)",
        "technical": True,
    },
    "confirmation_type": {
        "type": "str",
        "description": "Bestätigungsart ('FRACTAL' | 'PIVOT' | 'CAUSAL' | 'SESSION_CLOSE')",
        "technical": True,
    },
    "price": {
        "type": "float",
        "description": "Preis des Extremums (High/Low) bzw. Close bei Nicht-Swing-Bars",
    },
    "strength_value": {
        "type": "float",
        "description": "Signalstärke (ATR_MULTIPLE: ATR-Einheiten; PERCENT: %; PRICE_DISTANCE: Preisdistanz)",
    },
    "strength_type": {
        "type": "str",
        "description": "Stärke-Maßstab ('NORMALIZED' | 'ATR_MULTIPLE' | 'PERCENT' | 'PRICE_DISTANCE')",
        "technical": True,
    },
}

# ---------------------------------------------------------------------------
# Modul-Helfer (17.01.02: echte Swing-Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-ATR (EMA-alpha 1/period, adjust=False) ueber OHLCV.

    Liefert NaN fuer Bars ohne ausreichende Historie (min_periods=period) –
    diese Bars werden als INSUFFICIENT_DATA markiert (ZigZag_ATR).
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / max(1, period), min_periods=max(1, period),
                  adjust=False).mean()


def _detect_fractal(df: pd.DataFrame, left: int, right: int,
                    ) -> Tuple[np.ndarray, np.ndarray]:
    """Williams-Fraktal / Standard-Pivot: lokale Extrema mit links/rechts
    tieferen Hochs bzw. hoeheren Tiefs (kausale Bestaetigung nach `right`
    Bars). Liefert (is_swing_high, is_swing_low) als bool-Arrays."""
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        if hi[i] > hi[i - left:i].max() and hi[i] > hi[i + 1:i + right + 1].max():
            is_high[i] = True
        if lo[i] < lo[i - left:i].min() and lo[i] < lo[i + 1:i + right + 1].min():
            is_low[i] = True
    return is_high, is_low


def _detect_gann(df: pd.DataFrame, left: int, right: int,
                 ) -> Tuple[np.ndarray, np.ndarray]:
    """Gann_Mechanical: mechanische Swing-Bestaetigung – das Extremum ist
    zugleich Fenster-Extremum UND der Schlusskurs `right` Bars spaeter liegt
    gegen die Extremum-Richtung (Reversal bestaetigt)."""
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        if (hi[i] >= hi[i - left:i + right + 1].max()
                and close[i + right] < hi[i]):
            is_high[i] = True
        if (lo[i] <= lo[i - left:i + right + 1].min()
                and close[i + right] > lo[i]):
            is_low[i] = True
    return is_high, is_low


def _detect_zigzag(df: pd.DataFrame, threshold_for: Callable[[int, float], Optional[float]],
                   ) -> Tuple[np.ndarray, np.ndarray, Dict[int, Tuple[int, str, float]]]:
    """Klassischer ZigZag (alternierende Swings).

    `threshold_for(i, ext_price)` liefert die aktuelle Umkehr-Schwelle
    (oder None, wenn keine Umkehr moeglich ist – z.B. ATR noch NaN).
    Rueckgabe: (is_swing_high, is_swing_low, pivot_info) – pivot_info
    {ext_idx: (conf_idx, 'high'|'low', move_amount)} fuer die kausale
    Bestaetigung (confirmation_bar_time = times[conf_idx]).
    """
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    pivot_info: Dict[int, Tuple[int, str, float]] = {}
    if n < 2:
        return is_high, is_low, pivot_info
    direction = 1  # 1 = aufsteigend (Swing-Highs), -1 = absteigend (Swing-Lows)
    ext_idx = 0
    ext_price = hi[0]
    for i in range(1, n):
        if direction == 1:
            if hi[i] > ext_price:
                ext_idx, ext_price = i, hi[i]
            else:
                th = threshold_for(i, ext_price)
                if th is not None and (ext_price - lo[i]) >= th:
                    is_high[ext_idx] = True
                    pivot_info[ext_idx] = (i, "high", ext_price - lo[i])
                    direction = -1
                    ext_idx, ext_price = i, lo[i]
        else:
            if lo[i] < ext_price:
                ext_idx, ext_price = i, lo[i]
            else:
                th = threshold_for(i, ext_price)
                if th is not None and (hi[i] - ext_price) >= th:
                    is_low[ext_idx] = True
                    pivot_info[ext_idx] = (i, "low", hi[i] - ext_price)
                    direction = 1
                    ext_idx, ext_price = i, hi[i]
    return is_high, is_low, pivot_info


def _detect_period_extrema(df: pd.DataFrame, extrema_type: str,
                           ) -> Tuple[np.ndarray, np.ndarray, Dict[int, Tuple[int, int, int, float, float]]]:
    """Period-Extrema (PDH/PWH).

    * CURRENT_DEVELOPING: Flag an jeder Bar, die ein NEUES laufendes
      Tages-Hoch/Tief setzt (event == confirmation, lag 0, CAUSAL).
    * PREVIOUS_CLOSED: Flag an jeder Bar, die das Hoch/Tief der VORHERIGEN
      (abgeschlossenen) Periode beruehrt (event = Vortages-Extremum-Bar,
      confirmation = die beruehrende Bar selbst, SESSION_CLOSE).
    Rueckgabe: (is_swing_high, is_swing_low, ext_info) – ext_info
    {bar_idx: (event_idx, conf_idx, lag, price_high, price_low)} fuer die
    kausale Bestaetigung der geflaggten Bars.
    """
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    times = df["time"].to_numpy(dtype=np.int64)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    ext_info: Dict[int, Tuple[int, int, int, float, float]] = {}
    if n == 0:
        return is_high, is_low, ext_info
    # pd.to_datetime(...) liefert einen DatetimeIndex (kein Series) -> .dt
    # existiert dort nicht; der Zugriff erfolgt ueber .date (ndarray aus
    # datetime.date-Objekten, 17.01.02 Bugfix).
    days = pd.to_datetime(times, unit="s", utc=True).date
    day_str = [str(d) for d in days]

    if extrema_type == "CURRENT_DEVELOPING":
        cur_day: Optional[str] = None
        day_high = -np.inf
        day_low = np.inf
        for i in range(n):
            d = day_str[i]
            if d != cur_day:
                cur_day, day_high, day_low = d, -np.inf, np.inf
            if hi[i] > day_high:
                day_high = hi[i]
                is_high[i] = True
                ext_info[i] = (i, i, 0, hi[i], 0.0)
            if lo[i] < day_low:
                day_low = lo[i]
                is_low[i] = True
                ext_info[i] = (i, i, 0, hi[i], lo[i])
        return is_high, is_low, ext_info

    # PREVIOUS_CLOSED: Tages-Extrema (Preis + Index + letzte Bar) sammeln
    day_hl: Dict[str, Dict[str, Any]] = {}
    for i in range(n):
        d = day_str[i]
        entry = day_hl.setdefault(d, {
            "high": -np.inf, "low": np.inf,
            "high_idx": i, "low_idx": i, "last_idx": i,
        })
        if hi[i] > entry["high"]:
            entry["high"], entry["high_idx"] = hi[i], i
        if lo[i] < entry["low"]:
            entry["low"], entry["low_idx"] = lo[i], i
        entry["last_idx"] = i
    day_order = list(day_hl.keys())
    for k in range(1, len(day_order)):
        prev = day_hl[day_order[k - 1]]
        cur_d = day_order[k]
        for i in range(n):
            if day_str[i] != cur_d:
                continue
            if hi[i] >= prev["high"]:
                is_high[i] = True
                # event = Vortages-Extremum-Bar, confirmation = beruehrende Bar
                ext_info[i] = (prev["high_idx"], i, i - prev["high_idx"],
                               prev["high"], prev["low"])
            if lo[i] <= prev["low"]:
                is_low[i] = True
                ext_info[i] = (prev["low_idx"], i, i - prev["low_idx"],
                               prev["high"], prev["low"])
    return is_high, is_low, ext_info


class SrvSwingStructure(PluginFeature):
    """Geometrische & Preis-Swings (Fraktale, Pivots, Gann, ZigZag).

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) – keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_swing_structure"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Swing Points/Geometrie",
            "display_name": "Swing Structure Service",
            "description": "Erfasst Fraktal-, Pivot-, Gann- und ZigZag-Extrema für die Struktur-Analyse",
            "author": "PyTrader AI",
            "tags": ["swing", "fractal", "pivot", "zigzag", "structure"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) für "
                                "die Analytics-UI und ML-Pipelines. Erkennt "
                                "lokale Extrema über Williams-Fraktale, "
                                "Standard-Pivots, Gann-Mechanik, ZigZag "
                                "(ATR/Prozent) und Period-Extrema (PDH/PWH). "
                                "Keine Chart-Visualisierung in Kapitel 17.01.",
            "condition_rules": [
                "Williams_Fractal: high[i] > high[i±k] / low[i] < low[i±k] für k in 1..left/right_bars",
                "Standard_Pivot: lokales Extremum mit links/rechts tieferen Hochs bzw. höheren Tiefs",
                "Gann_Mechanical: mechanische Swing-Bestätigung über links/rechts-Zählung",
                "ZigZag_ATR: Richtungswechsel erst bei |move| >= atr_mult × ATR(atr_period)",
                "ZigZag_Pct: Richtungswechsel erst bei |move| >= change_pct %",
                "Period_Extrema: PDH/PWH (PREVIOUS_CLOSED) bzw. laufende Periode (CURRENT_DEVELOPING)",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": False,   # E-5: kein Indikator in Kapitel 17.01
            "batch": True,
            "live": False,
            "feature_store": True,
            "render": False,  # E-5: reine Datenlieferanten
        }

    # --- Single Source of Truth fürs Prop-Fenster (17.01 §2.2, PineScript-Zone)
    @property
    def parameter_order(self) -> List[str]:
        return list(_SWING_STRUCTURE_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Erkennungs-Modus",
            "left_bars": "Kerzen links",
            "right_bars": "Kerzen rechts (Bestätigung)",
            "atr_period": "ATR-Periode (ZigZag_ATR)",
            "atr_mult": "ATR-Multiplikator (ZigZag_ATR)",
            "change_pct": "Mindestbewegung % (ZigZag_Pct)",
            "period_extrema_type": "Period-Extrema-Typ",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_SWING_STRUCTURE_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _SWING_STRUCTURE_SCHEMA.items()}

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): flache Kopie der Modul-Konstante
        `_SWING_STRUCTURE_OUTPUT_SCHEMA` (PineScript-Input-Zone, M1: kein
        geteiltes mutable Dict)."""
        return {k: dict(v) for k, v in _SWING_STRUCTURE_OUTPUT_SCHEMA.items()}

    # 2. SCHEMA-EXPOSURE FÜR DIE UI (07.08.2026, Bugfix): Die Spalten-UI
    # (serviceui/param_columns.py & ServiceSelectorWidget) liest Parameter-
    # Definitionen über `default_params` / `full_parameter_schema()`. Diese
    # expliziten Overrides stellen das Schema unabhängig von der jeweiligen
    # parameter_schema-Definition (Property/Klassen-Attribut) bereit und
    # erhalten den Basisklassen-Vertrag (Basis-Parameter wie lookback + 
    # plugin-spezifische Parameter, vgl. base_plugin.PluginFeature).
    @property
    def default_params(self) -> Dict[str, Any]:
        """Extrahiert die Default-Werte aus dem parameter_schema für die Engine."""
        return {k: v.get("default") for k, v in self.parameter_schema.items()
                if "default" in v}

    def full_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Liefert das vollständige Schema (Basis + plugin-spezifisch) inkl.
        Min/Max/Typ für die UI-Spalten (Basisklassen-Vertrag)."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Struktur-Swings (Fraktale/Pivots/Gann/ZigZag/Period).

        17.01.02 (Bugfix-Runde): Die echte Swing-Erkennung ersetzt den
        Scaffold (vorher records=[], daher '0 Feature-Row(s)' im Store).

        Datenvertrag (17.01 §4): JEDER Bar entspricht genau EIN Record
        (dichte Label-Reihe fuer ML/Analytics). Swing-Bars tragen
        is_swing_high/is_swing_low=True sowie kausale Zeitstempel
        (event/confirmation_bar_time, confirmation_lag_bars). Bars am
        Serienanfang ohne ausreichenden Lookback/Lookahead erhalten
        calculation_status='INSUFFICIENT_DATA' (is_swing_* = False).

        Modi (params['mode']):
          * Williams_Fractal: lokale Extrema mit links/rechts tieferen Hochs
            bzw. hoeheren Tiefs (left/right_bars), Bestaetigung nach right_bars.
          * Standard_Pivot: identische Extremum-Logik (Pivot = Fraktal mit
            konfigurierbaren Fenstern).
          * Gann_Mechanical: Fenster-Extremum + Schlusskurs-Reversal
            (`right` Bars spaeter) gegen die Extremum-Richtung.
          * ZigZag_ATR: Richtungswechsel erst bei |move| >= atr_mult × ATR.
          * ZigZag_Pct: Richtungswechsel erst bei |move| >= change_pct %.
          * Period_Extrema: PDH/PWH (PREVIOUS_CLOSED = Vortages-Level-Touch)
            bzw. laufende Periode (CURRENT_DEVELOPING = neue Tages-Extrema).
        """
        empty: FeatureCalculateResult = {"feature_store_payload": {}}
        if df is None or df.empty:
            return empty

        # Defensive Normalisierung: 'time'-Spalte (epoch) sicherstellen.
        work = df.copy()
        if "time" not in work.columns:
            if "bar_time" in work.columns:
                work["time"] = work["bar_time"].apply(
                    lambda v: int(v.timestamp())
                    if hasattr(v, "timestamp") else int(v))
            else:
                return empty

        p = self.validate_params(params)
        mode = str(p.get("mode") or "Williams_Fractal")
        left = int(p.get("left_bars") or 2)
        right = int(p.get("right_bars") or 2)
        atr_period = int(p.get("atr_period") or 14)
        atr_mult = float(p.get("atr_mult") or 2.0)
        change_pct = float(p.get("change_pct") or 0.5)
        extrema_type = str(p.get("period_extrema_type") or "PREVIOUS_CLOSED")

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)
        atr = _atr_series(work, atr_period).to_numpy(dtype=float)

        is_high = np.zeros(n, dtype=bool)
        is_low = np.zeros(n, dtype=bool)
        # Kausale Bestaetigung je Swing-Bar: {idx: (event_idx, conf_idx,
        # lag, price)} – event = tatsaechliches Extremum, conf = kausale
        # Feststellung (fuer PREVIOUS_CLOSED liegt event VOR der Flag-Bar).
        swing_meta: Dict[int, Tuple[int, int, int, float]] = {}
        status = np.full(n, "OK", dtype=object)
        strength = np.zeros(n, dtype=float)
        strength_type = "NORMALIZED"
        conf_type = "PIVOT"

        if mode in ("Williams_Fractal", "Standard_Pivot"):
            is_high, is_low = _detect_fractal(work, left, right)
            status[:left] = "INSUFFICIENT_DATA"
            status[n - right:] = "INSUFFICIENT_DATA"
            conf_type = "FRACTAL" if mode == "Williams_Fractal" else "PIVOT"
            for i in range(n):
                if not (is_high[i] or is_low[i]):
                    continue
                conf = min(i + right, n - 1)
                price = float(work["high"].iloc[i] if is_high[i]
                              else work["low"].iloc[i])
                swing_meta[i] = (i, conf, right, price)
                if np.isfinite(atr[i]) and atr[i] > 0:
                    strength[i] = abs(
                        price - (float(work["low"].iloc[i])
                                 if is_high[i] else float(work["high"].iloc[i]))
                    ) / atr[i]
                    strength_type = "ATR_MULTIPLE"

        elif mode == "Gann_Mechanical":
            is_high, is_low = _detect_gann(work, left, right)
            status[:left] = "INSUFFICIENT_DATA"
            status[n - right:] = "INSUFFICIENT_DATA"
            conf_type = "PIVOT"
            for i in range(n):
                if not (is_high[i] or is_low[i]):
                    continue
                conf = min(i + right, n - 1)
                price = float(work["high"].iloc[i] if is_high[i]
                              else work["low"].iloc[i])
                swing_meta[i] = (i, conf, right, price)
                if np.isfinite(atr[i]) and atr[i] > 0:
                    strength[i] = abs(
                        price - (float(work["low"].iloc[i])
                                 if is_high[i] else float(work["high"].iloc[i]))
                    ) / atr[i]
                    strength_type = "ATR_MULTIPLE"

        elif mode == "ZigZag_ATR":
            def _thr_atr(i: int, _ext_price: float) -> Optional[float]:
                if not np.isfinite(atr[i]):
                    return None
                return atr_mult * atr[i]

            is_high, is_low, pivot_info = _detect_zigzag(work, _thr_atr)
            status[~np.isfinite(atr)] = "INSUFFICIENT_DATA"
            conf_type = "CAUSAL"
            strength_type = "ATR_MULTIPLE"
            for idx, (conf_idx, kind, move) in pivot_info.items():
                price = float(work["high"].iloc[idx] if kind == "high"
                              else work["low"].iloc[idx])
                swing_meta[idx] = (idx, conf_idx, conf_idx - idx, price)
                strength[idx] = move / atr[idx] if np.isfinite(atr[idx]) and atr[idx] > 0 else 0.0

        elif mode == "ZigZag_Pct":
            def _thr_pct(_i: int, ext_price: float) -> Optional[float]:
                return abs(ext_price) * change_pct / 100.0

            is_high, is_low, pivot_info = _detect_zigzag(work, _thr_pct)
            conf_type = "CAUSAL"
            strength_type = "PERCENT"
            for idx, (conf_idx, kind, move) in pivot_info.items():
                price = float(work["high"].iloc[idx] if kind == "high"
                              else work["low"].iloc[idx])
                swing_meta[idx] = (idx, conf_idx, conf_idx - idx, price)
                strength[idx] = (move / price * 100.0) if price else 0.0

        elif mode == "Period_Extrema":
            is_high, is_low, ext_info = _detect_period_extrema(work, extrema_type)
            status[0] = "INSUFFICIENT_DATA"  # erste Bar ohne Vortag/Historie
            conf_type = "CAUSAL" if extrema_type == "CURRENT_DEVELOPING" \
                else "SESSION_CLOSE"
            strength_type = "PRICE_DISTANCE"
            for idx, (event_idx, conf_idx, lag, price_high, price_low) in ext_info.items():
                price = float(price_high if is_high[idx] else price_low)
                swing_meta[idx] = (event_idx, conf_idx, lag, price)
                strength[idx] = abs(
                    float(work["high"].iloc[idx] if is_high[idx]
                          else work["low"].iloc[idx]) - price)

        else:
            # Unbekannter Modus: defensiv leer (kein Crash, 0 Rows).
            return empty

        # --- Records bauen (dicht: 1 Record pro Bar, 17.01 §4) ----------------
        records: List[Dict[str, Any]] = []
        total_high = int(is_high.sum())
        total_low = int(is_low.sum())
        for i in range(n):
            is_sh = bool(is_high[i])
            is_sl = bool(is_low[i])
            event_idx, conf_idx, lag, price = swing_meta.get(i, (i, i, 0, 0.0))
            event_idx = min(max(event_idx, 0), n - 1)
            conf_idx = min(max(conf_idx, 0), n - 1)
            if not (is_sh or is_sl):
                price = float(close[i])
            records.append({
                "bar_time": int(times[i]),
                "result_type": "SWING",
                "source_mode": mode,
                "calculation_status": str(status[i]),
                "is_swing_high": is_sh,
                "is_swing_low": is_sl,
                "is_rejection": False,
                "event_bar_time": int(times[event_idx]),
                "confirmation_bar_time": int(times[conf_idx]),
                "confirmation_lag_bars": int(lag),
                "confirmation_type": conf_type,
                "price": float(price),
                "strength_value": float(strength[i]),
                "strength_type": strength_type,
            })

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {
                    # E-7 / base_plugin (U15-A1, Invariante 5): schema_version
                    # ist Pflichtfeld fuer alle feature_store=True-Plugins.
                    "schema_version": "1.0.0",
                    "source_mode": mode,
                    "total_swing_highs": total_high,
                    "total_swing_lows": total_low,
                    "bars": n,
                },
            },
        }

```

--------------------------------------------------

### DATEI: analytics/features/definitions/srv_swing_volume_profile.py
```py
# analytics/features/definitions/srv_swing_volume_profile.py
# ==============================================================================
# DEFINITION: srv_swing_volume_profile
# ==============================================================================
# NAME:        Swing Volume Profile Service
# KATEGORIE:   Swing Points/Volumen & Grid
# BESCHREIBUNG: Berechnet POC/VAH/VAL, LVN-Rejections, Grid-Proximity und Anchored VWAP
# ==============================================================================
"""
Service: SwingVolumeProfile (Phase 17.01) – Naming Convention 16.08.01: srv_

Berechnet POC/VAH/VAL, Low Volume Nodes (LVNs), Raster-Annäherungen
(Grid_Proximity) und Anchored VWAP Bänder. Reiner Datenlieferant fuer die
Analytics-UI und spaetere ML-Pipelines – KEINE Chart-Visualisierung in
diesem Kapitel (17.01, §1).

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt des tatsaechlichen Extremums (z. B.
                           Session_Start beim Anchored VWAP).
  * confirmation_bar_time: Zeitpunkt, an dem das Signal kausal feststand.
  * confirmation_lag_bars: dynamische Differenz in Bars (Modus-Verzoegerung).
  * Profile am Serienanfang ohne ausreichenden Lookback erhalten
    calculation_status = 'INSUFFICIENT_DATA'.

Persistenz: feature_store_payload mit feature_id='srv_swing_volume_profile'
(Datenvertrag 17.01 §4, modus-spezifische Zusatzfelder §4.2). Seit 17.01
(E-1, PK-Migration) koennen mehrere Services konfliktfrei auf derselben
Kerze gespeichert werden.

Capabilities (E-5, 07.08.2026): chart=False, batch=True, live=False,
feature_store=True, render=False.
metadata['category'] = 'Swing Points/Volumen & Grid' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_SWING_VOLUME_PROFILE_SCHEMA` direkt unter diesem Header.
`parameter_schema` gibt eine flache Kopie zurueck (M1).
E-2 (07.08.2026): type-Werte als Strings.

Hinweis (17.01.02): 'Sessions' wird ohne Session-Kalender als Kalendertag
(24h-Periode) behandelt – Dokumentation der Vereinfachung fuer den
Batch-Datenlieferanten.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 17.01): Single Source of Truth fuer das
# Prop-Fenster. Inputs/Defaults stehen hier direkt am Dateianfang.
# `parameter_schema` gibt eine flache Kopie zurueck (M1).
# E-2 (07.08.2026): type-Werte als Strings.
# ---------------------------------------------------------------------------
_SWING_VOLUME_PROFILE_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "Volume_Profile",
        "options": ["Volume_Profile", "Grid_Proximity", "Anchored_VWAP"],
        "description": "Haupt-Berechnungsmodus",
    },
    "profile_period": {
        "type": "str",
        "default": "Sessions",
        "options": ["Bars", "Sessions", "Days", "Weeks", "Months"],
        "description": "Profil-Zeitraum (nur aktiv bei mode == 'Volume_Profile')",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "period_val": {
        "type": "int", "default": 1, "min": 1,
        "description": "Multiplier für profile_period",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "volume_source": {
        "type": "str",
        "default": "tick_volume",
        "options": ["tick_volume", "real_volume"],
        "description": "Volumenquelle aus MT5 (standardmäßig tick_volume)",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "volume_thresh_pct": {
        "type": "float", "default": 5.0, "min": 0.5,
        "description": "Mindestvolumenanteil in % für Cluster",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "value_area_pct": {
        "type": "float", "default": 0.70, "min": 0.1, "max": 1.0,
        "description": "Value Area Abdeckung (0.70 = 70%)",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "lvn_sensitivity": {
        "type": "float", "default": 0.20, "min": 0.05,
        "description": "Schwellwert für Low Volume Nodes",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "grid_step": {
        "type": "float", "default": 0.5, "min": 0.01,
        "description": "Rasterabstand (nur bei mode == 'Grid_Proximity')",
        "visible_when": {"mode": "Grid_Proximity"},
    },
    "vwap_anchor": {
        "type": "str",
        "default": "Session_Start",
        "options": ["Session_Start", "Week_Start", "Month_Start"],
        "description": "Ankerpunkt (nur bei mode == 'Anchored_VWAP')",
        "visible_when": {"mode": "Anchored_VWAP"},
    },
    "vwap_band_mult": {
        "type": "float", "default": 2.0, "min": 0.1,
        "description": "StDev-Multiplikator für VWAP-Bänder",
        "visible_when": {"mode": "Anchored_VWAP"},
    },
}

# ---------------------------------------------------------------------------
# OUTPUT-SCHEMA (20.03): Resultatfelder je feature_data-Record (Datenvertrag
# 17.01 §4, modus-spezifische Zusatzfelder §4.2). `bar_time` ist eine native
# DB-Spalte und wird NICHT deklariert (E4). `type` sind freie Strings (E5).
# `technical: True` -> kompakte Anzeige im Unterblock `🔧 System-Metrik` (E2).
# ---------------------------------------------------------------------------
_SWING_VOLUME_PROFILE_OUTPUT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "result_type": {
        "type": "str",
        "description": "Klassifikation des Records ('LEVEL' | 'VWAP')",
        "technical": True,
    },
    "source_mode": {
        "type": "str",
        "description": "Aktiver Modus (Volume_Profile/Grid_Proximity/Anchored_VWAP)",
        "technical": True,
    },
    "calculation_status": {
        "type": "str",
        "description": "Berechnungsstatus ('OK' | 'INSUFFICIENT_DATA')",
        "technical": True,
    },
    "is_swing_high": {
        "type": "bool",
        "description": "True, wenn der Close über VAH bzw. über Upper-Band liegt",
    },
    "is_swing_low": {
        "type": "bool",
        "description": "True, wenn der Close unter VAL bzw. unter Lower-Band liegt",
    },
    "is_rejection": {
        "type": "bool",
        "description": "True bei LVN-Rejection (Close nahe LVN) – nur Volume_Profile",
    },
    "event_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch des Events (Session_Start beim VWAP, sonst Bar selbst)",
        "technical": True,
    },
    "confirmation_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch, an der das Signal kausal feststand",
        "technical": True,
    },
    "confirmation_lag_bars": {
        "type": "int",
        "description": "Bestätigungs-Verzögerung in Bars (VWAP: Bars seit Anker)",
        "technical": True,
    },
    "confirmation_type": {
        "type": "str",
        "description": "Bestätigungsart (immer 'CAUSAL')",
        "technical": True,
    },
    "price": {
        "type": "float",
        "description": "Close-Preis der Bar",
    },
    "strength_value": {
        "type": "float",
        "description": "Signalstärke (VOLUME_RATIO: Volumen/POC-Volumen; NORMALIZED: |Distanz|/grid_step; PRICE_DISTANCE: |Close-VWAP|/StDev)",
    },
    "strength_type": {
        "type": "str",
        "description": "Stärke-Maßstab ('VOLUME_RATIO' | 'NORMALIZED' | 'PRICE_DISTANCE')",
        "technical": True,
    },
    "volume_source": {
        "type": "str",
        "description": "Volumenquelle (tick_volume/real_volume) – nur Volume_Profile",
        "technical": True,
    },
    "poc_price": {
        "type": "float",
        "description": "Point of Control (volumenstärkste Preisstufe) – nur Volume_Profile, nullbar",
    },
    "vah_price": {
        "type": "float",
        "description": "Value Area High (obere Wertbereichsgrenze) – nur Volume_Profile, nullbar",
    },
    "val_price": {
        "type": "float",
        "description": "Value Area Low (untere Wertbereichsgrenze) – nur Volume_Profile, nullbar",
    },
    "lvn_price": {
        "type": "float",
        "description": "Nächstgelegener Low Volume Node zum Close – nur Volume_Profile, nullbar",
    },
    "is_lvn_swing": {
        "type": "bool",
        "description": "True bei LVN-Rejection – nur Volume_Profile",
    },
    "grid_price": {
        "type": "float",
        "description": "Nächstes Raster-Level (round(close/grid_step) × grid_step) – nur Grid_Proximity",
    },
    "vwap_price": {
        "type": "float",
        "description": "Anchored VWAP (kumulativ ab Perioden-Start) – nur Anchored_VWAP",
    },
    "vwap_upper": {
        "type": "float",
        "description": "Oberes VWAP-Band (VWAP + band_mult × StDev) – nur Anchored_VWAP",
    },
    "vwap_lower": {
        "type": "float",
        "description": "Unteres VWAP-Band (VWAP - band_mult × StDev) – nur Anchored_VWAP",
    },
}

# ---------------------------------------------------------------------------
# Modul-Helfer (17.01.02: echte Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _volume_series(work: pd.DataFrame, source: str) -> np.ndarray:
    """Volumen-Serie (tick_volume/real_volume); fehlt die Spalte, Fallback
    auf gleichbleibendes Volumen 1.0 (defensiv, kein Crash)."""
    col = "real_volume" if source == "real_volume" else "tick_volume"
    if col in work.columns:
        v = pd.to_numeric(work[col], errors="coerce").fillna(0.0).to_numpy()
    else:
        v = np.ones(len(work), dtype=float)
    return v


def _profile_for(hi: np.ndarray, lo: np.ndarray, close: np.ndarray,
                 vol: np.ndarray, value_area_pct: float,
                 lvn_sensitivity: float, n_bins: int = 80,
                 ) -> Optional[Tuple[float, float, float, List[float],
                                     float, float]]:
    """Baut ein Volume-Profil ueber die uebergebenen Bars (entwickelnd).

    Rueckgabe: (poc_price, vah_price, val_price, lvn_prices, total_vol,
    max_bin_vol) oder None, wenn kein sinnvolles Profil konstruierbar ist
    (weniger als 2 Bars, flache Range oder Null-Gesamtvolumen)."""
    n = len(hi)
    if n < 2:
        return None
    hi_min = float(np.nanmin(hi))
    lo_max = float(np.nanmax(lo))
    lo_min = float(np.nanmin(lo))
    hi_max = float(np.nanmax(hi))
    total = float(np.sum(vol))
    if not np.isfinite(total) or total <= 0.0:
        return None
    lower = lo_min
    upper = hi_max
    if not (np.isfinite(lower) and np.isfinite(upper)) or upper <= lower:
        return None
    edges = np.linspace(lower, upper, n_bins + 1)
    typ = (hi + lo + close) / 3.0
    idx = np.clip(np.floor((typ - lower) / (upper - lower) * n_bins),
                  0, n_bins - 1).astype(int)
    bins_vol = np.zeros(n_bins, dtype=float)
    np.add.at(bins_vol, idx, vol)
    poc_bin = int(np.argmax(bins_vol))
    poc = float((edges[poc_bin] + edges[poc_bin + 1]) / 2.0)
    max_vol = float(bins_vol[poc_bin])
    # Value Area: ab POC beidseitig expandieren bis value_area_pct erreicht.
    cum = bins_vol[poc_bin]
    lo_b = hi_b = poc_bin
    target = total * float(value_area_pct)
    while cum < target and (lo_b > 0 or hi_b < n_bins - 1):
        left_v = bins_vol[lo_b - 1] if lo_b > 0 else -1.0
        right_v = bins_vol[hi_b + 1] if hi_b < n_bins - 1 else -1.0
        if lo_b > 0 and left_v >= right_v:
            lo_b -= 1
            cum += left_v
        elif hi_b < n_bins - 1:
            hi_b += 1
            cum += right_v
        else:
            break
    vah = float(edges[hi_b + 1])
    val = float(edges[lo_b])
    # LVN: Bins mit Volumen < lvn_sensitivity × POC-Volumen (aber > 0).
    lvn_mask = (bins_vol > 0.0) & (bins_vol < lvn_sensitivity * max_vol)
    lvn_prices = [float((edges[b] + edges[b + 1]) / 2.0)
                  for b in np.where(lvn_mask)[0]]
    return poc, vah, val, lvn_prices, total, max_vol


def _group_ids(times: np.ndarray, spec: str, period_val: int,
               ) -> np.ndarray:
    """Gruppen-IDs je Bar fuer die Profilperioden.

    * Bars:     i // period_val
    * Sessions: Kalendertag (Vereinfachung ohne Session-Kalender, 24h).
    * Days:     Kalendertag.
    * Weeks:    ISO-Jahr-Woche.
    * Months:   Kalender-Jahr-Monat.
    """
    n = len(times)
    if spec == "Bars":
        return np.floor(np.arange(n) / max(1, int(period_val))).astype(np.int64)
    # pd.to_datetime(...) liefert einen DatetimeIndex (kein Series) -> .dt
    # existiert dort nicht; die Formatierung erfolgt direkt via .strftime
    # (17.01.02 Bugfix, identisch zu srv_swing_structure).
    dates = pd.to_datetime(times, unit="s", utc=True)
    if spec in ("Sessions", "Days"):
        return dates.strftime("%Y-%m-%d").to_numpy()
    if spec == "Weeks":
        return dates.strftime("%G-W%V").to_numpy()
    if spec == "Months":
        return dates.strftime("%Y-%m").to_numpy()
    return dates.strftime("%Y-%m-%d").to_numpy()


def _anchored_vwap(work: pd.DataFrame, times: np.ndarray, vol: np.ndarray,
                   anchor: str, band_mult: float,
                   ) -> Tuple[np.ndarray, np.ndarray, np.ndarray,
                              np.ndarray, np.ndarray]:
    """Anchored VWAP (entwickelnd ab Perioden-Start).

    Rueckgabe: (vwap, upper, lower, anchor_idx, stdev). anchor_idx[i] =
    Index der Anker-Bar (Session/Week/Month-Start), 0 fuer die erste Bar.
    """
    n = len(work)
    hi = work["high"].to_numpy(dtype=float)
    lo = work["low"].to_numpy(dtype=float)
    close = work["close"].to_numpy(dtype=float)
    typ = (hi + lo + close) / 3.0
    if anchor == "Week_Start":
        spec = "Weeks"
    elif anchor == "Month_Start":
        spec = "Months"
    else:
        spec = "Sessions"
    groups = _group_ids(times, spec, 1)
    # Neue Periode erkennen (causal: letzte Gruppe bis i).
    new_period = np.zeros(n, dtype=bool)
    new_period[0] = True
    for i in range(1, n):
        if groups[i] != groups[i - 1]:
            new_period[i] = True
    anchor_idx = np.zeros(n, dtype=np.int64)
    cur = 0
    for i in range(n):
        if new_period[i]:
            cur = i
        anchor_idx[i] = cur
    # Kumulativ ab Anker: Summe(typ*vol) / Summe(vol).
    cum_pv = np.zeros(n, dtype=float)
    cum_v = np.zeros(n, dtype=float)
    pv = 0.0
    cv = 0.0
    for i in range(n):
        if new_period[i]:
            pv = 0.0
            cv = 0.0
        pv += typ[i] * vol[i]
        cv += vol[i]
        cum_pv[i] = pv
        cum_v[i] = cv
    vwap = np.where(cum_v > 0.0, cum_pv / np.maximum(cum_v, 1e-12), 0.0)
    # Entwickelnde Varianz (gewichtete Quadrat-Abweichung ab Anker).
    dev2 = ((typ - vwap) ** 2) * vol
    cum_d2 = np.zeros(n, dtype=float)
    cd2 = 0.0
    for i in range(n):
        if new_period[i]:
            cd2 = 0.0
        cd2 += dev2[i]
        cum_d2[i] = cd2
    var = np.where(cum_v > 0.0, cum_d2 / np.maximum(cum_v, 1e-12), 0.0)
    stdev = np.sqrt(np.maximum(var, 0.0))
    upper = vwap + band_mult * stdev
    lower = vwap - band_mult * stdev
    return vwap, upper, lower, anchor_idx, stdev


class SrvSwingVolumeProfile(PluginFeature):
    """Volumen-, Grid- & VWAP-Swings.

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) – keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_swing_volume_profile"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Swing Points/Volumen & Grid",
            "display_name": "Swing Volume Profile Service",
            "description": "Volumengewichtetes Profil mit POC/VAH/VAL, LVNs, Grid & Anchored VWAP",
            "author": "PyTrader AI",
            "tags": ["swing", "volume", "profile", "lvn", "vwap", "grid"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) für "
                                "die Analytics-UI und ML-Pipelines. Berechnet "
                                "POC/VAH/VAL und Low Volume Nodes (LVNs) je "
                                "Profil, Raster-Annäherungen (Grid_Proximity) "
                                "und Anchored-VWAP-Bänder. Keine "
                                "Chart-Visualisierung in Kapitel 17.01.",
            "condition_rules": [
                "Volume_Profile: POC/VAH/VAL über value_area_pct, Cluster ab volume_thresh_pct, LVNs ab lvn_sensitivity",
                "Grid_Proximity: Abstand des Preises zum naechsten Rasterlevel (grid_step)",
                "Anchored_VWAP: VWAP ab Session/Week/Month_Start ± vwap_band_mult × StDev",
                "volume_source: tick_volume (Standard) oder real_volume",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA/MISSING_MTF_CONTEXT",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": False,   # E-5: kein Indikator in Kapitel 17.01
            "batch": True,
            "live": False,
            "feature_store": True,
            "render": False,  # E-5: reine Datenlieferanten
        }

    # --- Single Source of Truth fürs Prop-Fenster (17.01 §2.2, PineScript-Zone)
    @property
    def parameter_order(self) -> List[str]:
        return list(_SWING_VOLUME_PROFILE_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Haupt-Berechnungsmodus",
            "profile_period": "Profil-Zeitraum (Volume_Profile)",
            "period_val": "Multiplier (Profil-Zeitraum)",
            "volume_source": "Volumenquelle",
            "volume_thresh_pct": "Mindestvolumenanteil % (Cluster)",
            "value_area_pct": "Value Area Abdeckung",
            "lvn_sensitivity": "LVN-Schwellwert",
            "grid_step": "Rasterabstand (Grid_Proximity)",
            "vwap_anchor": "VWAP-Ankerpunkt",
            "vwap_band_mult": "VWAP-Band-Multiplikator",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_SWING_VOLUME_PROFILE_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _SWING_VOLUME_PROFILE_SCHEMA.items()}

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): flache Kopie der Modul-Konstante
        `_SWING_VOLUME_PROFILE_OUTPUT_SCHEMA` (PineScript-Input-Zone, M1:
        kein geteiltes mutable Dict)."""
        return {k: dict(v) for k, v in _SWING_VOLUME_PROFILE_OUTPUT_SCHEMA.items()}

    # 2. SCHEMA-EXPOSURE FÜR DIE UI (07.08.2026, Bugfix): Die Spalten-UI
    # (serviceui/param_columns.py & ServiceSelectorWidget) liest Parameter-
    # Definitionen über `default_params` / `full_parameter_schema()`. Diese
    # expliziten Overrides stellen das Schema unabhängig von der jeweiligen
    # parameter_schema-Definition (Property/Klassen-Attribut) bereit und
    # erhalten den Basisklassen-Vertrag (Basis-Parameter wie lookback + 
    # plugin-spezifische Parameter, vgl. base_plugin.PluginFeature).
    @property
    def default_params(self) -> Dict[str, Any]:
        """Extrahiert die Default-Werte aus dem parameter_schema für die Engine."""
        return {k: v.get("default") for k, v in self.parameter_schema.items()
                if "default" in v}

    def full_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Liefert das vollständige Schema (Basis + plugin-spezifisch) inkl.
        Min/Max/Typ für die UI-Spalten (Basisklassen-Vertrag)."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Volume-Profile/Grid/VWAP-Swings.

        17.01.02 (Bugfix-Runde): Echte Erkennung ersetzt den Scaffold
        (vorher records=[], daher '0 Feature-Row(s)' im Store + irrefuehrende
        Meldung 'Keine OHLCV-Daten' im ServiceRunWorker).

        Datenvertrag (17.01 §4): JEDER Bar entspricht genau EIN Record.
        Modus-spezifische Zusatzfelder (§4.2):
          * Volume_Profile:  volume_source, poc_price, vah_price, val_price,
                             lvn_price, is_lvn_swing (result_type LEVEL).
          * Grid_Proximity:  grid_price (result_type LEVEL).
          * Anchored_VWAP:   vwap_price, vwap_upper, vwap_lower
                             (result_type VWAP).
        """
        empty: FeatureCalculateResult = {"feature_store_payload": {}}
        if df is None or df.empty:
            return empty

        # Defensive Normalisierung: 'time'-Spalte (epoch) sicherstellen.
        work = df.copy()
        if "time" not in work.columns:
            if "bar_time" in work.columns:
                work["time"] = work["bar_time"].apply(
                    lambda v: int(v.timestamp())
                    if hasattr(v, "timestamp") else int(v))
            else:
                return empty

        p = self.validate_params(params)
        mode = str(p.get("mode") or "Volume_Profile")
        profile_period = str(p.get("profile_period") or "Sessions")
        period_val = int(p.get("period_val") or 1)
        volume_source = str(p.get("volume_source") or "tick_volume")
        value_area_pct = float(p.get("value_area_pct") or 0.70)
        lvn_sensitivity = float(p.get("lvn_sensitivity") or 0.20)
        grid_step = float(p.get("grid_step") or 0.5)
        vwap_anchor = str(p.get("vwap_anchor") or "Session_Start")
        vwap_band_mult = float(p.get("vwap_band_mult") or 2.0)

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)
        hi = work["high"].to_numpy(dtype=float)
        lo = work["low"].to_numpy(dtype=float)
        vol = _volume_series(work, volume_source)

        records: List[Dict[Any, Any]] = []
        total_high = 0
        total_low = 0

        if mode == "Volume_Profile":
            groups = _group_ids(times, profile_period, period_val)
            # Serienanfang: erste Bar jeder Gruppe ohne Historie.
            is_first = np.zeros(n, dtype=bool)
            is_first[0] = True
            for i in range(1, n):
                if groups[i] != groups[i - 1]:
                    is_first[i] = True
            group_start = 0
            for i in range(n):
                if is_first[i]:
                    group_start = i
                prof = _profile_for(hi[group_start:i + 1], lo[group_start:i + 1],
                                    close[group_start:i + 1], vol[group_start:i + 1],
                                    value_area_pct, lvn_sensitivity)
                if prof is None or is_first[i]:
                    records.append({
                        "bar_time": int(times[i]),
                        "result_type": "LEVEL",
                        "source_mode": mode,
                        "calculation_status": "INSUFFICIENT_DATA",
                        "is_swing_high": False,
                        "is_swing_low": False,
                        "is_rejection": False,
                        "event_bar_time": int(times[i]),
                        "confirmation_bar_time": int(times[i]),
                        "confirmation_lag_bars": 0,
                        "confirmation_type": "CAUSAL",
                        "price": float(close[i]),
                        "strength_value": 0.0,
                        "strength_type": "VOLUME_RATIO",
                        "volume_source": volume_source,
                        "poc_price": None,
                        "vah_price": None,
                        "val_price": None,
                        "lvn_price": None,
                        "is_lvn_swing": False,
                    })
                    continue
                poc, vah, val, lvn_prices, total, max_vol = prof
                # Naechster LVN am aktuellen Preis (kausal).
                lvn_price: Optional[float] = None
                if lvn_prices:
                    lvn_price = min(lvn_prices,
                                    key=lambda x: abs(x - float(close[i])))
                is_lvn_swing = lvn_price is not None and abs(
                    float(close[i]) - lvn_price) <= (vah - val) / 20.0
                is_sh = float(close[i]) >= vah
                is_sl = float(close[i]) <= val
                total_high += int(is_sh)
                total_low += int(is_sl)
                records.append({
                    "bar_time": int(times[i]),
                    "result_type": "LEVEL",
                    "source_mode": mode,
                    "calculation_status": "OK",
                    "is_swing_high": bool(is_sh),
                    "is_swing_low": bool(is_sl),
                    "is_rejection": bool(is_lvn_swing),
                    "event_bar_time": int(times[i]),
                    "confirmation_bar_time": int(times[i]),
                    "confirmation_lag_bars": 0,
                    "confirmation_type": "CAUSAL",
                    "price": float(close[i]),
                    "strength_value": float(vol[i] / max_vol) if max_vol > 0 else 0.0,
                    "strength_type": "VOLUME_RATIO",
                    "volume_source": volume_source,
                    "poc_price": poc,
                    "vah_price": vah,
                    "val_price": val,
                    "lvn_price": lvn_price,
                    "is_lvn_swing": bool(is_lvn_swing),
                })

        elif mode == "Grid_Proximity":
            grid_price = np.round(close / grid_step) * grid_step
            for i in range(n):
                gp = float(grid_price[i])
                dist = float(close[i]) - gp
                is_sh = i > 0 and float(close[i]) >= gp and float(close[i - 1]) < gp
                is_sl = i > 0 and float(close[i]) <= gp and float(close[i - 1]) > gp
                total_high += int(is_sh)
                total_low += int(is_sl)
                records.append({
                    "bar_time": int(times[i]),
                    "result_type": "LEVEL",
                    "source_mode": mode,
                    "calculation_status": "OK",
                    "is_swing_high": bool(is_sh),
                    "is_swing_low": bool(is_sl),
                    "is_rejection": False,
                    "event_bar_time": int(times[i]),
                    "confirmation_bar_time": int(times[i]),
                    "confirmation_lag_bars": 0,
                    "confirmation_type": "CAUSAL",
                    "price": float(close[i]),
                    "strength_value": abs(dist) / grid_step if grid_step > 0 else 0.0,
                    "strength_type": "NORMALIZED",
                    "grid_price": gp,
                })

        elif mode == "Anchored_VWAP":
            vwap, upper, lower, anchor_idx, stdev = _anchored_vwap(
                work, times, vol, vwap_anchor, vwap_band_mult)
            for i in range(n):
                vw = float(vwap[i])
                up = float(upper[i])
                lw = float(lower[i])
                is_sh = float(close[i]) > up
                is_sl = float(close[i]) < lw
                total_high += int(is_sh)
                total_low += int(is_sl)
                status = "INSUFFICIENT_DATA" if i == int(anchor_idx[i]) else "OK"
                records.append({
                    "bar_time": int(times[i]),
                    "result_type": "VWAP",
                    "source_mode": mode,
                    "calculation_status": status,
                    "is_swing_high": bool(is_sh),
                    "is_swing_low": bool(is_sl),
                    "is_rejection": False,
                    "event_bar_time": int(times[int(anchor_idx[i])]),
                    "confirmation_bar_time": int(times[i]),
                    "confirmation_lag_bars": int(i - int(anchor_idx[i])),
                    "confirmation_type": "CAUSAL",
                    "price": float(close[i]),
                    "strength_value": (float(close[i]) - vw) / stdev[i]
                    if np.isfinite(stdev[i]) and stdev[i] > 0 else 0.0,
                    "strength_type": "PRICE_DISTANCE",
                    "vwap_price": vw,
                    "vwap_upper": up,
                    "vwap_lower": lw,
                })

        else:
            # Unbekannter Modus: defensiv leer (kein Crash, 0 Rows).
            return empty

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {
                    # E-7 / base_plugin (U15-A1, Invariante 5): schema_version
                    # ist Pflichtfeld fuer alle feature_store=True-Plugins.
                    "schema_version": "1.0.0",
                    "source_mode": mode,
                    "total_swing_highs": total_high,
                    "total_swing_lows": total_low,
                    "bars": n,
                },
            },
        }

```

--------------------------------------------------

### DATEI: analytics/features/definitions/srv_trend_breakout.py
```py
# analytics/features/definitions/srv_trend_breakout.py
# ==============================================================================
# DEFINITION: srv_trend_breakout
# ==============================================================================
# NAME:        Trend Breakout Service
# KATEGORIE:   Trend & Reversal/Breakout & Kanal
# BESCHREIBUNG: Trendfolgende Trailing-Stops & Kanal-Breakouts via Supertrend & Donchian/Keltner
# ==============================================================================
"""
Service: TrendBreakout (Phase 17.02) - Naming Convention 16.08.01: srv_

Erkennt Trendwechsel und Ausbrueche ueber dynamische ATR-Trailings und
Bänder (Supertrend ATR, Donchian/Keltner-Kanaele). Reiner Datenlieferant
fuer die Analytics-UI und spaetere ML-Pipelines - KEINE Chart-Visualisierung
in diesem Kapitel (17.02, §1).

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt der betrachteten Kerze (Bar-Close-Signal).
  * confirmation_bar_time: identisch zu event_bar_time (confirmation_lag_bars
                           = 0).
  * Kerzen am Serienanfang ohne ausreichenden Lookback (Kanal-/ATR-Warmup)
    erhalten calculation_status = 'INSUFFICIENT_DATA' und is_trend_* = False.

Datenvertrag (17.02 §3): result_type TREND|BREAKOUT, 1 Record pro Bar,
flache Records (nur bar_time + feature_data-Inhalte; symbol/timeframe/
feature_id setzt store_plugin_payload selbst).

Capabilities (E-5, 07.08.2026): chart=False, batch=True, live=False,
feature_store=True, render=False.
metadata['category'] = 'Trend & Reversal/Breakout & Kanal' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Modul-Konstante
`_TREND_BREAKOUT_SCHEMA` direkt unter diesem Header. `parameter_schema`
gibt eine flache Kopie zurueck (M1). `visible_when` (17.01.05): Conditional
Visibility beim Mode-Wechsel.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 17.01): Single Source of Truth fuer das
# Prop-Fenster. E-2: type-Werte als Strings. E-4: `visible_when`-Deklarationen.
# ---------------------------------------------------------------------------
_TREND_BREAKOUT_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "Supertrend_ATR",
        "options": ["Supertrend_ATR", "Donchian_Keltner_Breakout"],
        "description": "Breakout-Algorithmus",
    },
    "channel_type": {
        "type": "str",
        "default": "Donchian",
        "options": ["Donchian", "Keltner"],
        "description": "Kanal-Typ bei mode == 'Donchian_Keltner_Breakout'",
        "visible_when": {"mode": "Donchian_Keltner_Breakout"},
    },
    "atr_period": {
        "type": "int", "default": 10, "min": 1,
        "description": "ATR-Periode fuer Supertrend / Keltner",
    },
    "atr_mult": {
        "type": "float", "default": 3.0, "min": 0.1,
        "description": "ATR-Multiplikator fuer Bänder/Trailing",
    },
    "period": {
        "type": "int", "default": 20, "min": 2,
        "description": "Donchian/Keltner Kanal-Periode",
        "visible_when": {"mode": "Donchian_Keltner_Breakout"},
    },
    "ma_type": {
        "type": "str",
        "default": "EMA",
        "options": [
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA",
        ],
        "description": "MA-Typ fuer Keltner Baseline",
        "visible_when": {"mode": "Donchian_Keltner_Breakout"},
    },
}

# ---------------------------------------------------------------------------
# OUTPUT-SCHEMA (20.03): Resultatfelder je feature_data-Record (Datenvertrag
# 17.02 §3). `bar_time` ist eine native DB-Spalte und wird NICHT deklariert
# (E4). `type` sind freie Strings (E5). `technical: True` -> kompakte
# Anzeige im Unterblock `🔧 System-Metrik` (E2).
# ---------------------------------------------------------------------------
_TREND_BREAKOUT_OUTPUT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "result_type": {
        "type": "str",
        "description": "Klassifikation des Records ('BREAKOUT' bei Signal, sonst 'TREND')",
        "technical": True,
    },
    "source_mode": {
        "type": "str",
        "description": "Aktiver Algorithmus (Supertrend_ATR/Donchian_Keltner_Breakout)",
        "technical": True,
    },
    "calculation_status": {
        "type": "str",
        "description": "Berechnungsstatus ('OK' | 'INSUFFICIENT_DATA')",
        "technical": True,
    },
    "is_trend_up": {
        "type": "bool",
        "description": "True, wenn der Close über der Supertrend-Linie bzw. dem Upper-Band liegt",
    },
    "is_trend_down": {
        "type": "bool",
        "description": "True, wenn der Close unter der Supertrend-Linie bzw. dem Lower-Band liegt",
    },
    "is_reversal_up": {
        "type": "bool",
        "description": "Reversal-Up-Flag (Breakout: immer False)",
    },
    "is_reversal_down": {
        "type": "bool",
        "description": "Reversal-Down-Flag (Breakout: immer False)",
    },
    "event_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch der Bar (Bar-Close-Signal, event == confirmation)",
        "technical": True,
    },
    "confirmation_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch der Bestätigung (identisch zu event_bar_time)",
        "technical": True,
    },
    "confirmation_lag_bars": {
        "type": "int",
        "description": "Bestätigungs-Verzögerung (immer 0, Bar-Close-Signal)",
        "technical": True,
    },
    "confirmation_type": {
        "type": "str",
        "description": "Bestätigungsart (immer 'BAR_CLOSE')",
        "technical": True,
    },
    "trend_strength": {
        "type": "float",
        "description": "Signalstärke (ATR_DISTANCE: Distanz zur Linie in ATR-Einheiten bzw. zum Kanal-Mittel)",
    },
    "strength_type": {
        "type": "str",
        "description": "Stärke-Maßstab (immer 'ATR_DISTANCE')",
        "technical": True,
    },
    "reference_price": {
        "type": "float",
        "description": "Close-Preis der Bar (Referenzpreis)",
    },
    "supertrend_line": {
        "type": "float",
        "description": "Supertrend-Linienwert – nur Supertrend_ATR, nullbar",
    },
    "atr_value": {
        "type": "float",
        "description": "ATR-Wert – nur Supertrend_ATR, nullbar",
    },
    "upper_band": {
        "type": "float",
        "description": "Oberes Kanalband – nur Donchian_Keltner_Breakout, nullbar",
    },
    "lower_band": {
        "type": "float",
        "description": "Unteres Kanalband – nur Donchian_Keltner_Breakout, nullbar",
    },
    "middle_band": {
        "type": "float",
        "description": "Kanal-Mittelband – nur Donchian_Keltner_Breakout, nullbar",
    },
}

# ---------------------------------------------------------------------------
# Modul-Helfer (17.02: direkte, vollstaendige Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-ATR (EMA-alpha 1/period, adjust=False) ueber OHLCV."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _supertrend(df: pd.DataFrame, atr_period: int, atr_mult: float
                ) -> pd.DataFrame:
    """Supertrend (ATR-Trailing) vektorisiert mit sequenzieller
    final-Band-Regel (wie im Ist-Stand des Projekts).

    basic_upper/lower = (high+low)/2 +- atr_mult * ATR.
    final_upper/lower: klemmt das Band in Trendrichtung (kein Ueberspringen
    beim Wechsel). supertrend = final_upper (downtrend) | final_lower (uptrend).
    """
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    close = df["close"].astype(float).to_numpy()
    atr = _atr_series(df, atr_period).to_numpy(dtype=float)

    n = len(df)
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + atr_mult * atr
    basic_lower = hl2 - atr_mult * atr

    final_upper = np.empty(n)
    final_lower = np.empty(n)
    supertrend = np.empty(n)
    direction = np.zeros(n, dtype=bool)  # True = uptrend

    for i in range(n):
        if i == 0:
            final_upper[i] = basic_upper[i]
            final_lower[i] = basic_lower[i]
            direction[i] = close[i] > final_upper[i]
        else:
            # final_upper: nur nach oben ziehen, wenn vorher nicht drunter.
            prev_close = close[i - 1]
            if prev_close <= final_upper[i - 1]:
                final_upper[i] = min(basic_upper[i], final_upper[i - 1])
            else:
                final_upper[i] = basic_upper[i]
            if prev_close >= final_lower[i - 1]:
                final_lower[i] = max(basic_lower[i], final_lower[i - 1])
            else:
                final_lower[i] = basic_lower[i]
            # Richtung beibehalten, bis der Schlusskurs die Linie durchbricht.
            if direction[i - 1]:
                if close[i] < final_lower[i]:
                    direction[i] = False
                else:
                    direction[i] = True
            else:
                if close[i] > final_upper[i]:
                    direction[i] = True
                else:
                    direction[i] = False

        supertrend[i] = final_lower[i] if direction[i] else final_upper[i]

    return pd.DataFrame({
        "supertrend_line": supertrend,
        "direction": direction,
        "atr": atr,
    }, index=df.index)


def _donchian_keltner(df: pd.DataFrame, channel_type: str, period: int,
                      ma_type: str, atr_period: int, atr_mult: float
                      ) -> pd.DataFrame:
    """Donchian- oder Keltner-Kanal vektorisiert (upper/lower/middle)."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    if channel_type == "Keltner":
        # MA-Serie (Template 16.04, alle 12 Typen; VWMA nutzt tick_volume).
        try:
            from chart.indicators.utils.ma_template import MATemplateEngine
        except Exception:
            MATemplateEngine = None  # type: ignore
        if MATemplateEngine is not None and ma_type in (
                "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
                "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"):
            volume = df["tick_volume"] if "tick_volume" in df.columns else None
            middle = MATemplateEngine.calculate_ma(
                close, ma_type, period, volume=volume)
        else:
            middle = close.rolling(period, min_periods=1).mean()
        atr = _atr_series(df, atr_period)
        upper = middle + atr_mult * atr
        lower = middle - atr_mult * atr
    else:  # Donchian
        # Kausaler Kanal: NUR abgeschlossene Bars (shift(1)) - ein Close
        # bricht die letzten N Bars DURCH. Ohne shift waere upper >= aktuelle
        # high > close immer, ein Breakout-Signal nie moeglich (Bugfix
        # waehrend der Tests, 17.02 Umsetzung).
        upper = high.shift(1).rolling(period, min_periods=period).max()
        lower = low.shift(1).rolling(period, min_periods=period).min()
        middle = (upper + lower) / 2.0

    return pd.DataFrame({
        "upper_band": upper,
        "lower_band": lower,
        "middle_band": middle,
    })


class SrvTrendBreakout(PluginFeature):
    """Trend-Ausbrueche & Trailing-Stops (Supertrend, Donchian/Keltner).

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) - keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_trend_breakout"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Trend & Reversal/Breakout & Kanal",
            "display_name": "Trend Breakout Service",
            "description": "Erfasst Trend-Ausbrueche und Trailing-Stops ueber Supertrend ATR und Donchian/Keltner-Kanaele.",
            "author": "PyTrader AI",
            "tags": ["trend", "breakout", "supertrend", "donchian", "keltner"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) fuer "
                                "die Analytics-UI und ML-Pipelines. Liefert "
                                "kausale Trendwechsel-Signale. Supertrend "
                                "schaltet bei Schlusskurs-Durchbruch des "
                                "Median+-ATR-Bandes um. Donchian/Keltner "
                                "signalisiert Ausbrueche aus N-Bar Extrema "
                                "oder Volatilitaetsbändern. Keine "
                                "Chart-Visualisierung in Kapitel 17.02.",
            "condition_rules": [
                "Supertrend_ATR: TrendUp = Close > Supertrend_Line",
                "Donchian_Keltner_Breakout: TrendUp = Close > Upper_Channel_Band",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": False,   # E-5: kein Indikator in Kapitel 17.02
            "batch": True,
            "live": False,
            "feature_store": True,
            "render": False,  # E-5: reine Datenlieferanten
        }

    # --- Single Source of Truth fuer's Prop-Fenster (17.01 §2.2, PineScript-Zone)
    @property
    def parameter_order(self) -> List[str]:
        return list(_TREND_BREAKOUT_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Breakout-Algorithmus",
            "channel_type": "Kanal-Typ (Donchian/Keltner)",
            "atr_period": "ATR-Periode",
            "atr_mult": "ATR-Multiplikator",
            "period": "Kanal-Periode",
            "ma_type": "MA-Typ (Keltner Baseline)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_TREND_BREAKOUT_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _TREND_BREAKOUT_SCHEMA.items()}

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): flache Kopie der Modul-Konstante
        `_TREND_BREAKOUT_OUTPUT_SCHEMA` (PineScript-Input-Zone, M1: kein
        geteiltes mutable Dict)."""
        return {k: dict(v) for k, v in _TREND_BREAKOUT_OUTPUT_SCHEMA.items()}

    # 2. SCHEMA-EXPOSURE FUER DIE UI (17.01.04, Bugfix): Siehe
    # srv_trend_regime.py - identischer Basisklassen-Vertrag.
    @property
    def default_params(self) -> Dict[str, Any]:
        """Extrahiert die Default-Werte aus dem parameter_schema fuer die Engine."""
        return {k: v.get("default") for k, v in self.parameter_schema.items()
                if "default" in v}

    def full_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Liefert das vollstaendige Schema (Basis + plugin-spezifisch) inkl.
        Min/Max/Typ fuer die UI-Spalten (Basisklassen-Vertrag)."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Trend-Breakouts (Supertrend/Donchian/Keltner).

        Datenvertrag (17.02 §3): 1 Record pro Bar (dichte Label-Reihe).
        Trend-Bars tragen is_trend_up/is_trend_down=True sowie kausale
        Zeitstempel (event/confirmation_bar_time, confirmation_lag_bars=0).
        Bars am Serienanfang ohne Kanal-/ATR-Historie erhalten
        calculation_status='INSUFFICIENT_DATA'.

        Modi (params['mode']):
          * Supertrend_ATR: ATR-Trailing; TrendUp = Close > Supertrend_Line.
          * Donchian_Keltner_Breakout: Donchian (N-Bar Extrema) oder Keltner
            (MA +- ATR-Multiplikator); TrendUp = Close > Upper_Channel_Band.
        """
        empty: FeatureCalculateResult = {"feature_store_payload": {}}
        if df is None or df.empty:
            return empty

        # Defensive Normalisierung: 'time'-Spalte (epoch) sicherstellen.
        work = df.copy()
        if "time" not in work.columns:
            if "bar_time" in work.columns:
                work["time"] = work["bar_time"].apply(
                    lambda v: int(v.timestamp())
                    if hasattr(v, "timestamp") else int(v))
            else:
                return empty

        p = self.validate_params(params)
        mode = str(p.get("mode") or "Supertrend_ATR")
        channel_type = str(p.get("channel_type") or "Donchian")
        atr_period = int(p.get("atr_period") or 10)
        atr_mult = float(p.get("atr_mult") or 3.0)
        period = int(p.get("period") or 20)
        ma_type = str(p.get("ma_type") or "EMA")

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)

        is_trend_up = np.zeros(n, dtype=bool)
        is_trend_down = np.zeros(n, dtype=bool)
        is_rev_up = np.zeros(n, dtype=bool)
        is_rev_down = np.zeros(n, dtype=bool)
        status = np.full(n, "OK", dtype=object)
        strength = np.zeros(n, dtype=float)
        strength_type = "ATR_DISTANCE"
        conf_type = "BAR_CLOSE"
        extra: Dict[str, np.ndarray] = {}

        if mode == "Supertrend_ATR":
            st = _supertrend(work, atr_period, atr_mult)
            line = st["supertrend_line"].to_numpy(dtype=float)
            atr = st["atr"].to_numpy(dtype=float)
            nan = ~np.isfinite(line) | ~np.isfinite(atr)
            status[nan] = "INSUFFICIENT_DATA"
            is_trend_up = close > line
            is_trend_down = close < line
            # Staerke: Distanz in ATR-Einheiten.
            strength = np.where(
                (np.isfinite(atr)) & (atr > 0),
                np.abs(close - line) / np.where(atr > 0, atr, np.nan),
                0.0)
            extra["supertrend_line"] = np.where(np.isfinite(line), line, np.nan)
            extra["atr_value"] = np.where(np.isfinite(atr), atr, np.nan)

        elif mode == "Donchian_Keltner_Breakout":
            ch = _donchian_keltner(work, channel_type, period, ma_type,
                                   atr_period, atr_mult)
            upper = ch["upper_band"].to_numpy(dtype=float)
            lower = ch["lower_band"].to_numpy(dtype=float)
            middle = ch["middle_band"].to_numpy(dtype=float)
            nan = ~np.isfinite(upper) | ~np.isfinite(lower)
            status[nan] = "INSUFFICIENT_DATA"
            is_trend_up = close > upper
            is_trend_down = close < lower
            spread = np.where(
                (np.isfinite(upper)) & (np.isfinite(lower)),
                (upper - lower) / 2.0, np.nan)
            strength = np.where(
                (np.isfinite(spread)) & (spread > 0),
                np.abs(close - middle) / np.where(spread > 0, spread, np.nan),
                0.0)
            strength_type = "ATR_DISTANCE"
            extra["upper_band"] = np.where(np.isfinite(upper), upper, np.nan)
            extra["lower_band"] = np.where(np.isfinite(lower), lower, np.nan)
            extra["middle_band"] = np.where(np.isfinite(middle), middle, np.nan)

        else:
            # Unbekannter Modus: defensiv leer (kein Crash, 0 Rows).
            return empty

        # --- Records bauen (dicht: 1 Record pro Bar, 17.02 §3) --------------
        records: List[Dict[str, Any]] = []
        total_up = int(is_trend_up.sum())
        total_down = int(is_trend_down.sum())
        for i in range(n):
            rec: Dict[str, Any] = {
                "bar_time": int(times[i]),
                "result_type": "BREAKOUT" if (is_trend_up[i] or is_trend_down[i])
                else "TREND",
                "source_mode": mode,
                "calculation_status": str(status[i]),
                "is_trend_up": bool(is_trend_up[i]),
                "is_trend_down": bool(is_trend_down[i]),
                "is_reversal_up": bool(is_rev_up[i]),
                "is_reversal_down": bool(is_rev_down[i]),
                # Bar-Close-Signal: event == confirmation (Lag 0).
                "event_bar_time": int(times[i]),
                "confirmation_bar_time": int(times[i]),
                "confirmation_lag_bars": 0,
                "confirmation_type": conf_type,
                "trend_strength": float(strength[i]),
                "strength_type": strength_type,
                "reference_price": float(close[i]),
            }
            for k, arr in extra.items():
                rec[k] = float(arr[i]) if np.isfinite(arr[i]) else None
            records.append(rec)

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {
                    # E-7 / base_plugin (U15-A1, Invariante 5): schema_version
                    # ist Pflichtfeld fuer alle feature_store=True-Plugins.
                    "schema_version": "1.0.0",
                    "source_mode": mode,
                    "total_trend_up": total_up,
                    "total_trend_down": total_down,
                    "bars": n,
                },
            },
        }

```

--------------------------------------------------

### DATEI: analytics/features/definitions/srv_trend_hma_pivot.py
```py
# analytics/features/definitions/srv_trend_hma_pivot.py
# ==============================================================================
# DEFINITION: srv_trend_hma_pivot
# ==============================================================================
# NAME:        HMA Peak-Toleranz Pivot Service
# KATEGORIE:   Trend & Reversal/Hysteresis & Pivots
# BESCHREIBUNG: Trendwechsel-Erkennung auf geglaetteter EHMA/HMA mit Prozent-Hysterese
# ==============================================================================
"""
Service: TrendHmaPivot (Phase 17.02) - Naming Convention 16.08.01: srv_

Spezialisierter Trendwechsel-Detektor auf Basis von HMA/EHMA-Extrema und
prozentualer Hysterese (PineScript-Logik `piv_pendingExtremeValue`).
Reiner Datenlieferant fuer die Analytics-UI und spaetere ML-Pipelines -
KEINE Chart-Visualisierung in diesem Kapitel (17.02, §1).

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt der betrachteten Kerze (Bar-Close-Signal).
  * confirmation_bar_time: identisch zu event_bar_time (confirmation_lag_bars
                           = 0; Bar-Close-Signal der geglaetteten MA).
  * Kerzen am Serienanfang ohne ausreichenden MA-Warmup erhalten
    calculation_status = 'INSUFFICIENT_DATA' und is_trend_* = False.

Datenvertrag (17.02 §3): result_type TREND|REVERSAL, 1 Record pro Bar,
flache Records (nur bar_time + feature_data-Inhalte; symbol/timeframe/
feature_id setzt store_plugin_payload selbst).

Capabilities (E-5, 07.08.2026): chart=False, batch=True, live=False,
feature_store=True, render=False.
metadata['category'] = 'Trend & Reversal/Hysteresis & Pivots' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Modul-Konstante
`_TREND_HMA_PIVOT_SCHEMA` direkt unter diesem Header. `parameter_schema`
gibt eine flache Kopie zurueck (M1). `visible_when` (17.01.05): Conditional
Visibility beim Mode-Wechsel.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 17.01): Single Source of Truth fuer das
# Prop-Fenster. E-2: type-Werte als Strings. E-4: `visible_when`-Deklarationen.
# ---------------------------------------------------------------------------
_TREND_HMA_PIVOT_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "HMA_Peak_Toleranz",
        "options": ["HMA_Peak_Toleranz"],
        "description": "HMA Pivot Hysteresis Modus",
    },
    "piv_len": {
        "type": "int", "default": 4, "min": 1,
        "description": "Pivot-Lookback/Glaettung",
        "visible_when": {"mode": "HMA_Peak_Toleranz"},
    },
    "hma_type": {
        "type": "str",
        "default": "EHMA",
        "options": [
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA",
        ],
        "description": "Gleitender Durchschnittstyp (EHMA/HMA)",
        "visible_when": {"mode": "HMA_Peak_Toleranz"},
    },
    "hma_smoothing": {
        "type": "int", "default": 10, "min": 2,
        "description": "Hauptperiode des MA",
        "visible_when": {"mode": "HMA_Peak_Toleranz"},
    },
    "piv_maxHmaMovePct": {
        "type": "float", "default": 0.2, "min": 0.01,
        "description": "Erforderlicher prozentualer Mindestabstand vom Peak fuer Trendwechsel",
        "visible_when": {"mode": "HMA_Peak_Toleranz"},
    },
}

# ---------------------------------------------------------------------------
# OUTPUT-SCHEMA (20.03): Resultatfelder je feature_data-Record (Datenvertrag
# 17.02 §3, §3.2). `bar_time` ist eine native DB-Spalte und wird NICHT
# deklariert (E4). `type` sind freie Strings (E5). `technical: True` ->
# kompakte Anzeige im Unterblock `🔧 System-Metrik` (E2).
# ---------------------------------------------------------------------------
_TREND_HMA_PIVOT_OUTPUT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "result_type": {
        "type": "str",
        "description": "Klassifikation des Records ('REVERSAL' bei Trendwechsel, sonst 'TREND')",
        "technical": True,
    },
    "source_mode": {
        "type": "str",
        "description": "Aktiver Algorithmus (immer 'HMA_Peak_Toleranz')",
        "technical": True,
    },
    "calculation_status": {
        "type": "str",
        "description": "Berechnungsstatus ('OK' | 'INSUFFICIENT_DATA')",
        "technical": True,
    },
    "is_trend_up": {
        "type": "bool",
        "description": "True, wenn MA das Pending-Low um piv_maxHmaMovePct % nach oben durchbrochen hat",
    },
    "is_trend_down": {
        "type": "bool",
        "description": "True, wenn MA das Pending-High um piv_maxHmaMovePct % nach unten durchbrochen hat",
    },
    "is_reversal_up": {
        "type": "bool",
        "description": "Reversal-Up-Flag (is_trend_up und nicht is_trend_down)",
    },
    "is_reversal_down": {
        "type": "bool",
        "description": "Reversal-Down-Flag (is_trend_down und nicht is_trend_up)",
    },
    "event_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch der Bar (Bar-Close-Signal, event == confirmation)",
        "technical": True,
    },
    "confirmation_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch der Bestätigung (identisch zu event_bar_time)",
        "technical": True,
    },
    "confirmation_lag_bars": {
        "type": "int",
        "description": "Bestätigungs-Verzögerung (immer 0, Bar-Close-Signal)",
        "technical": True,
    },
    "confirmation_type": {
        "type": "str",
        "description": "Bestätigungsart (immer 'BAR_CLOSE')",
        "technical": True,
    },
    "trend_strength": {
        "type": "float",
        "description": "Signalstärke (PERCENT: prozentuale Distanz des Close vom Pending-Extremwert)",
    },
    "strength_type": {
        "type": "str",
        "description": "Stärke-Maßstab (immer 'PERCENT')",
        "technical": True,
    },
    "reference_price": {
        "type": "float",
        "description": "Close-Preis der Bar (Referenzpreis)",
    },
    "ma_value": {
        "type": "float",
        "description": "Geglätteter MA-Wert der Bar (EHMA/HMA) – nullbar",
    },
    "pending_extreme_value": {
        "type": "float",
        "description": "Letzter extremer MA-Wert (piv_pendingExtremeValue) – nullbar",
    },
}

# ---------------------------------------------------------------------------
# Modul-Helfer (17.02: direkte, vollstaendige Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _ma_series(df: pd.DataFrame, ma_type: str, period: int) -> pd.Series:
    """MA-Serie (Template 16.04, alle 12 Typen; VWMA nutzt tick_volume).

    Lokaler Import (E-3, 17.02 Review): `chart.indicators.utils.ma_template`
    - der Pfad `analytics.features.helpers.ma_template` existiert nicht.
    """
    try:
        from chart.indicators.utils.ma_template import MATemplateEngine
    except Exception:
        MATemplateEngine = None  # type: ignore
    close = df["close"].astype(float)
    if MATemplateEngine is not None and ma_type in (
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"):
        volume = df["tick_volume"] if "tick_volume" in df.columns else None
        return MATemplateEngine.calculate_ma(close, ma_type, period,
                                             volume=volume)
    # Fallback: einfacher SMA (defensiv, kein Crash).
    return close.rolling(period, min_periods=1).mean()


def _hma_peak_toleranz(ma: np.ndarray, piv_len: int, move_pct: float
                       ) -> pd.DataFrame:
    """PineScript-Hysterese-Logik auf der geglaetteten MA-Serie.

    Haelt den letzten extremen MA-Wert (`piv_pendingExtremeValue`) als
    gleitendes Extremum ueber ein `piv_len`-Fenster (Rolling min/max,
    min_periods=1, NaN-robust: keine NaN-Verseuchung durch den MA-Warmup).
    Ein Trendwechsel wird erst signalisiert, wenn der MA den Extremwert um
    `move_pct` % durchbricht (verhindert Fehlsignale in Seitwaertsphasen):

      * TrendUp:   MA > PendingLow  * (1 + move_pct/100)
      * TrendDown: MA < PendingHigh * (1 - move_pct/100)

    Liefert je Bar is_trend_up/is_trend_down und die Extremwerte
    (pending_extreme_value) fuer den Datenvertrag (§3.2).
    """
    n = len(ma)
    series = pd.Series(ma)
    # Rolling-Extrema ueber piv_len Fenster (inkl. aktueller Bar);
    # NaN im Warmup werden uebersprungen (skipna) - kein Infekt.
    roll_low = series.rolling(piv_len, min_periods=1).min().to_numpy(dtype=float)
    roll_high = series.rolling(piv_len, min_periods=1).max().to_numpy(dtype=float)

    is_up = np.zeros(n, dtype=bool)
    is_down = np.zeros(n, dtype=bool)
    pending_low = np.full(n, np.nan)
    pending_high = np.full(n, np.nan)
    pending_val = np.full(n, np.nan)
    trend_up = False

    for i in range(n):
        if not np.isfinite(ma[i]) or not np.isfinite(roll_low[i]):
            trend_up = False
            continue
        pending_low[i] = roll_low[i]
        pending_high[i] = roll_high[i]

        # Trendwechsel mit Hysterese.
        if trend_up:
            if ma[i] < pending_high[i] * (1.0 - move_pct / 100.0):
                trend_up = False
                is_down[i] = True
            else:
                is_up[i] = True
        else:
            if ma[i] > pending_low[i] * (1.0 + move_pct / 100.0):
                trend_up = True
                is_up[i] = True
            else:
                is_down[i] = False

        pending_val[i] = pending_high[i] if trend_up else pending_low[i]

    return pd.DataFrame({
        "is_trend_up": is_up,
        "is_trend_down": is_down,
        "pending_extreme": pending_val,
        "ma_value": ma,
    })


class SrvTrendHmaPivot(PluginFeature):
    """HMA/EHMA Peak-Toleranz & Pivot-Trendwechsel.

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) - keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_trend_hma_pivot"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Trend & Reversal/Hysteresis & Pivots",
            "display_name": "HMA Peak Pivot Service",
            "description": "Erkennt Trendwechsel auf geglaetteten EHMA/HMA-Linien unter Beruecksichtigung einer Prozent-Hysterese.",
            "author": "PyTrader AI",
            "tags": ["trend", "hma", "ehma", "pivot", "hysteresis"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) fuer "
                                "die Analytics-UI und ML-Pipelines. Haelt den "
                                "letzten extremen MA-Wert "
                                "(piv_pendingExtremeValue). Ein Trendwechsel "
                                "wird erst signalisiert, wenn der MA den "
                                "Extremwert um piv_maxHmaMovePct % durchbricht. "
                                "Verhindert Fehlsignale in Seitwaertsphasen. "
                                "Keine Chart-Visualisierung in Kapitel 17.02.",
            "condition_rules": [
                "HMA_Peak_Toleranz: TrendUp = MA > PendingLow * (1 + MovePct/100)",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": False,   # E-5: kein Indikator in Kapitel 17.02
            "batch": True,
            "live": False,
            "feature_store": True,
            "render": False,  # E-5: reine Datenlieferanten
        }

    # --- Single Source of Truth fuer's Prop-Fenster (17.01 §2.2, PineScript-Zone)
    @property
    def parameter_order(self) -> List[str]:
        return list(_TREND_HMA_PIVOT_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Pivot-Modus",
            "piv_len": "Pivot-Lookback",
            "hma_type": "MA-Typ (EHMA/HMA)",
            "hma_smoothing": "Hauptperiode des MA",
            "piv_maxHmaMovePct": "Mindestabstand % vom Peak",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_TREND_HMA_PIVOT_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _TREND_HMA_PIVOT_SCHEMA.items()}

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): flache Kopie der Modul-Konstante
        `_TREND_HMA_PIVOT_OUTPUT_SCHEMA` (PineScript-Input-Zone, M1: kein
        geteiltes mutable Dict)."""
        return {k: dict(v) for k, v in _TREND_HMA_PIVOT_OUTPUT_SCHEMA.items()}

    # 2. SCHEMA-EXPOSURE FUER DIE UI (17.01.04, Bugfix): Siehe
    # srv_trend_regime.py - identischer Basisklassen-Vertrag.
    @property
    def default_params(self) -> Dict[str, Any]:
        """Extrahiert die Default-Werte aus dem parameter_schema fuer die Engine."""
        return {k: v.get("default") for k, v in self.parameter_schema.items()
                if "default" in v}

    def full_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Liefert das vollstaendige Schema (Basis + plugin-spezifisch) inkl.
        Min/Max/Typ fuer die UI-Spalten (Basisklassen-Vertrag)."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet HMA/EHMA-Peak-Toleranz-Trendwechsel.

        Datenvertrag (17.02 §3): 1 Record pro Bar (dichte Label-Reihe).
        Trend-Bars tragen is_trend_up/is_trend_down=True sowie kausale
        Zeitstempel (event/confirmation_bar_time, confirmation_lag_bars=0).
        Bars am Serienanfang ohne MA-Warmup erhalten
        calculation_status='INSUFFICIENT_DATA'.

        Modi (params['mode']):
          * HMA_Peak_Toleranz: Hysterese gegen letztes MA-Extremum
            (piv_maxHmaMovePct % Durchbruch => Trendwechsel).
        """
        empty: FeatureCalculateResult = {"feature_store_payload": {}}
        if df is None or df.empty:
            return empty

        # Defensive Normalisierung: 'time'-Spalte (epoch) sicherstellen.
        work = df.copy()
        if "time" not in work.columns:
            if "bar_time" in work.columns:
                work["time"] = work["bar_time"].apply(
                    lambda v: int(v.timestamp())
                    if hasattr(v, "timestamp") else int(v))
            else:
                return empty

        p = self.validate_params(params)
        mode = str(p.get("mode") or "HMA_Peak_Toleranz")
        piv_len = int(p.get("piv_len") or 4)
        hma_type = str(p.get("hma_type") or "EHMA")
        hma_smoothing = int(p.get("hma_smoothing") or 10)
        move_pct = float(p.get("piv_maxHmaMovePct") or 0.2)

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)

        is_trend_up = np.zeros(n, dtype=bool)
        is_trend_down = np.zeros(n, dtype=bool)
        status = np.full(n, "OK", dtype=object)
        strength = np.zeros(n, dtype=float)
        strength_type = "PERCENT"
        conf_type = "BAR_CLOSE"
        extra: Dict[str, np.ndarray] = {}

        if mode == "HMA_Peak_Toleranz":
            ma = _ma_series(work, hma_type, hma_smoothing).to_numpy(dtype=float)
            res = _hma_peak_toleranz(ma, piv_len, move_pct)
            is_trend_up = res["is_trend_up"].to_numpy(dtype=bool)
            is_trend_down = res["is_trend_down"].to_numpy(dtype=bool)
            pending = res["pending_extreme"].to_numpy(dtype=float)
            ma_nan = ~np.isfinite(ma)
            status[ma_nan] = "INSUFFICIENT_DATA"
            # Staerke: Prozent-Distanz vom Pending-Extremwert.
            with np.errstate(divide="ignore", invalid="ignore"):
                pct = np.where(
                    (np.isfinite(pending)) & (pending != 0),
                    np.abs(close - pending) / np.abs(pending) * 100.0,
                    0.0)
            strength = np.where(np.isfinite(pct), pct, 0.0)
            extra["ma_value"] = np.where(np.isfinite(ma), ma, np.nan)
            extra["pending_extreme_value"] = np.where(
                np.isfinite(pending), pending, np.nan)

        else:
            # Unbekannter Modus: defensiv leer (kein Crash, 0 Rows).
            return empty

        # --- Records bauen (dicht: 1 Record pro Bar, 17.02 §3) --------------
        records: List[Dict[str, Any]] = []
        total_up = int(is_trend_up.sum())
        total_down = int(is_trend_down.sum())
        for i in range(n):
            rec: Dict[str, Any] = {
                "bar_time": int(times[i]),
                "result_type": "REVERSAL" if (is_trend_up[i] or is_trend_down[i])
                else "TREND",
                "source_mode": mode,
                "calculation_status": str(status[i]),
                "is_trend_up": bool(is_trend_up[i]),
                "is_trend_down": bool(is_trend_down[i]),
                "is_reversal_up": bool(is_trend_up[i] and not is_trend_down[i]),
                "is_reversal_down": bool(is_trend_down[i] and not is_trend_up[i]),
                # Bar-Close-Signal: event == confirmation (Lag 0).
                "event_bar_time": int(times[i]),
                "confirmation_bar_time": int(times[i]),
                "confirmation_lag_bars": 0,
                "confirmation_type": conf_type,
                "trend_strength": float(strength[i]),
                "strength_type": strength_type,
                "reference_price": float(close[i]),
            }
            for k, arr in extra.items():
                rec[k] = float(arr[i]) if np.isfinite(arr[i]) else None
            records.append(rec)

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {
                    # E-7 / base_plugin (U15-A1, Invariante 5): schema_version
                    # ist Pflichtfeld fuer alle feature_store=True-Plugins.
                    "schema_version": "1.0.0",
                    "source_mode": mode,
                    "total_trend_up": total_up,
                    "total_trend_down": total_down,
                    "bars": n,
                },
            },
        }

```

--------------------------------------------------

### DATEI: analytics/features/definitions/srv_trend_regime.py
```py
# analytics/features/definitions/srv_trend_regime.py
# ==============================================================================
# DEFINITION: srv_trend_regime
# ==============================================================================
# NAME:        Trend Regime Service
# KATEGORIE:   Trend & Reversal/Regime & Staerke
# BESCHREIBUNG: Statistische Trendstaerke- und Regime-Analyse via LinReg (R2), ADX/DMI & Z-Score
# ==============================================================================
"""
Service: TrendRegime (Phase 17.02) - Naming Convention 16.08.01: srv_

Quantifiziert statistische Trend-Regimes, Trendstaerken und
Mittelwertabweichungen. Reiner Datenlieferant fuer die Analytics-UI und
spaetere ML-Pipelines - KEINE Chart-Visualisierung in diesem Kapitel (17.02,
§1); dedizierte Chart-Indikatoren (ind_...) folgen erst nach statistischer
Validierung der erzeugten Features.

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt der betrachteten Kerze (Bar-Close-Signal).
  * confirmation_bar_time: identisch zu event_bar_time (Bar-Close-Signal,
                           confirmation_lag_bars = 0).
  * Kerzen am Serienanfang ohne ausreichenden Lookback erhalten
    calculation_status = 'INSUFFICIENT_DATA' und is_trend_* = False.

Datenvertrag (17.02 §3): result_type TREND|REVERSAL, 1 Record pro Bar,
flache Records (nur bar_time + feature_data-Inhalte; symbol/timeframe/
feature_id setzt store_plugin_payload selbst).

Capabilities (E-5, 07.08.2026): chart=False (kein Indikator), batch=True,
live=False, feature_store=True, render=False.
metadata['category'] = 'Trend & Reversal/Regime & Staerke' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_TREND_REGIME_SCHEMA` direkt unter diesem Header
(siehe dort) und sind wie in PineScript am Dateianfang anpassbar.
`parameter_schema` gibt eine flache Kopie zurueck (M1: kein geteiltes
mutable Dict ueber Instanzen). `visible_when` (17.01.05): Conditional
Visibility beim Mode-Wechsel.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 17.01): Single Source of Truth fuer das
# Prop-Fenster. Inputs/Defaults stehen hier direkt am Dateianfang.
# E-2 (07.08.2026): type-Werte als Strings ("int"/"float"/"str").
# E-4 (17.02 Review): `visible_when`-Deklarationen fuer die Conditional
# Visibility (17.01.05).
# ---------------------------------------------------------------------------
_TREND_REGIME_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "Linear_Regression_Slope",
        "options": [
            "Linear_Regression_Slope", "ADX_DMI", "ZScore_Mean_Distance",
        ],
        "description": "Algorithmus-Modus zur Trend-Regime-Bestimmung",
    },
    "period": {
        "type": "int", "default": 20, "min": 2,
        "description": "Berechnungsperiode fuer Regressions-/Statistik-Fenster",
    },
    "r2_threshold": {
        "type": "float", "default": 0.6, "min": 0.0, "max": 1.0,
        "description": "Mindest-R2 fuer etablierten Trend (LinReg)",
        "visible_when": {"mode": "Linear_Regression_Slope"},
    },
    "di_period": {
        "type": "int", "default": 14, "min": 1,
        "description": "DMI-Periode (nur bei mode == 'ADX_DMI')",
        "visible_when": {"mode": "ADX_DMI"},
    },
    "adx_smooth": {
        "type": "int", "default": 14, "min": 1,
        "description": "ADX-Glaettung (nur bei mode == 'ADX_DMI')",
        "visible_when": {"mode": "ADX_DMI"},
    },
    "adx_threshold": {
        "type": "float", "default": 25.0, "min": 1.0,
        "description": "ADX-Schwellwert fuer Trend-Regime",
        "visible_when": {"mode": "ADX_DMI"},
    },
    "z_thresh": {
        "type": "float", "default": 2.0, "min": 0.1,
        "description": "Z-Score Extremwert-Schwelle fuer Reversals",
        "visible_when": {"mode": "ZScore_Mean_Distance"},
    },
    "ma_type": {
        "type": "str",
        "default": "SMA",
        "options": [
            "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
            "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA",
        ],
        "description": "Gleitender Durchschnitt fuer Z-Score Baseline",
        "visible_when": {"mode": "ZScore_Mean_Distance"},
    },
}

# ---------------------------------------------------------------------------
# OUTPUT-SCHEMA (20.03): Resultatfelder je feature_data-Record (Datenvertrag
# 17.02 §3). `bar_time` ist eine native DB-Spalte und wird NICHT deklariert
# (E4). `type` sind freie Strings (E5). `technical: True` -> kompakte
# Anzeige im Unterblock `🔧 System-Metrik` (E2).
# ---------------------------------------------------------------------------
_TREND_REGIME_OUTPUT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "result_type": {
        "type": "str",
        "description": "Klassifikation des Records ('REVERSAL' bei Z-Score-Signal, sonst 'TREND')",
        "technical": True,
    },
    "source_mode": {
        "type": "str",
        "description": "Aktiver Algorithmus (Linear_Regression_Slope/ADX_DMI/ZScore_Mean_Distance)",
        "technical": True,
    },
    "calculation_status": {
        "type": "str",
        "description": "Berechnungsstatus ('OK' | 'INSUFFICIENT_DATA')",
        "technical": True,
    },
    "is_trend_up": {
        "type": "bool",
        "description": "LinReg: Slope > 0 und R2 >= Threshold; ADX: +DI > -DI und ADX >= Threshold",
    },
    "is_trend_down": {
        "type": "bool",
        "description": "LinReg: Slope < 0 und R2 >= Threshold; ADX: -DI > +DI und ADX >= Threshold",
    },
    "is_reversal_up": {
        "type": "bool",
        "description": "Z-Score: True bei Z <= -z_thresh (überverkauft)",
    },
    "is_reversal_down": {
        "type": "bool",
        "description": "Z-Score: True bei Z >= +z_thresh (überkauft)",
    },
    "event_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch der Bar (Bar-Close-Signal, event == confirmation)",
        "technical": True,
    },
    "confirmation_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch der Bestätigung (identisch zu event_bar_time)",
        "technical": True,
    },
    "confirmation_lag_bars": {
        "type": "int",
        "description": "Bestätigungs-Verzögerung (immer 0, Bar-Close-Signal)",
        "technical": True,
    },
    "confirmation_type": {
        "type": "str",
        "description": "Bestätigungsart (immer 'BAR_CLOSE')",
        "technical": True,
    },
    "trend_strength": {
        "type": "float",
        "description": "Signalstärke (R2_SCORE: R2; ADX_VALUE: ADX; Z_SCORE: |Z|)",
    },
    "strength_type": {
        "type": "str",
        "description": "Stärke-Maßstab ('R2_SCORE' | 'ADX_VALUE' | 'Z_SCORE')",
        "technical": True,
    },
    "reference_price": {
        "type": "float",
        "description": "Close-Preis der Bar (Referenzpreis)",
    },
    "slope_value": {
        "type": "float",
        "description": "LinReg-Steigung des rolling Fensters – nur Linear_Regression_Slope, nullbar",
    },
    "r2_score": {
        "type": "float",
        "description": "Bestimmtheitsmaß R2 des rolling Fensters – nur Linear_Regression_Slope, nullbar",
    },
    "adx_value": {
        "type": "float",
        "description": "ADX-Wert – nur ADX_DMI, nullbar",
    },
    "plus_di": {
        "type": "float",
        "description": "+DI-Wert – nur ADX_DMI, nullbar",
    },
    "minus_di": {
        "type": "float",
        "description": "-DI-Wert – nur ADX_DMI, nullbar",
    },
    "z_score_value": {
        "type": "float",
        "description": "Z-Score (Close - MA) / rolling-std – nur ZScore_Mean_Distance, nullbar",
    },
    "mean_baseline": {
        "type": "float",
        "description": "MA-Baseline (Z-Score Nenner) – nur ZScore_Mean_Distance, nullbar",
    },
}

# ---------------------------------------------------------------------------
# Modul-Helfer (17.02: direkte, vollstaendige Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-ATR (EMA-alpha 1/period, adjust=False) ueber OHLCV."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _rolling_slope_r2(series: pd.Series, period: int) -> pd.Series:
    """Vektorisierte rolling LinReg: Steigung und R2 je Fenster.

    slope = Sxy / Sxx,  r2 = Sxy^2 / (Sxx * Syy)
    x = arange(period) (konstant), Sxx = sum((x-xbar)^2).
    Liefert NaN fuer Fenster mit fehlenden Werten (Warmup).
    """
    x = np.arange(period, dtype=float)
    xm = x - x.mean()
    sxx = float((xm ** 2).sum())

    def _slope(w: np.ndarray) -> float:
        y = np.asarray(w, dtype=float)
        if np.isnan(y).any() or sxx == 0:
            return np.nan
        ym = y - y.mean()
        sxy = float((xm * ym).sum())
        return sxy / sxx

    def _r2(w: np.ndarray) -> float:
        y = np.asarray(w, dtype=float)
        if np.isnan(y).any() or sxx == 0:
            return np.nan
        ym = y - y.mean()
        sxy = float((xm * ym).sum())
        syy = float((ym ** 2).sum())
        if syy <= 0:
            return 0.0
        return (sxy ** 2) / (sxx * syy)

    roll = series.rolling(period, min_periods=period)
    slope = roll.apply(_slope, raw=True)
    r2 = roll.apply(_r2, raw=True)
    return pd.DataFrame({"slope": slope, "r2": r2})


def _adx_dmi(df: pd.DataFrame, di_period: int, adx_smooth: int
             ) -> pd.DataFrame:
    """ADX/DMI (Wilder) vektorisiert: +DI, -DI, ADX.

    +DM = high - prev_high (falls > 0 und > -(low - prev_low))
    -DM = prev_low - low   (falls > 0 und > high - prev_high)
    Glaettung: Wilder RMA (EWM alpha=1/period, adjust=False).
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(np.where(
        (up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index)
    minus_dm = pd.Series(np.where(
        (down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index)

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    alpha = 1.0 / max(di_period, 1)
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    alpha_adx = 1.0 / max(adx_smooth, 1)
    adx = dx.ewm(alpha=alpha_adx, adjust=False).mean()

    return pd.DataFrame({
        "plus_di": plus_di,
        "minus_di": minus_di,
        "adx": adx,
    })


def _zscore_series(df: pd.DataFrame, ma: np.ndarray, period: int
                   ) -> np.ndarray:
    """Z-Score = (close - MA) / rolling-std(close, period)."""
    close = df["close"].astype(float)
    std = close.rolling(period, min_periods=period).std(ddof=0).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (close.to_numpy() - ma) / std
    return np.where(np.isfinite(std) & (std > 0), z, np.nan)


class SrvTrendRegime(PluginFeature):
    """Statistische Trendstaerke- und Regime-Analyse.

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) - keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_trend_regime"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Trend & Reversal/Regime & Staerke",
            "display_name": "Trend Regime Service",
            "description": "Quantifiziert Trendstaerke und Regimes ueber LinReg Slope/R2, ADX/DMI und Z-Score Mean Distance.",
            "author": "PyTrader AI",
            "tags": ["trend", "regime", "linreg", "adx", "zscore"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) fuer "
                                "die Analytics-UI und ML-Pipelines. LinReg misst "
                                "Steigung und Bestimmtheitsmass R2. ADX/DMI misst "
                                "Richtungsdynamik. Z-Score misst die "
                                "Standardabweichung vom Mittelwert fuer "
                                "Uebertreibungen. Keine Chart-Visualisierung in "
                                "Kapitel 17.02.",
            "condition_rules": [
                "Linear_Regression_Slope: TrendUp = Slope > 0 and R2 >= r2_threshold",
                "ADX_DMI: TrendUp = +DI > -DI and ADX >= adx_threshold",
                "ZScore_Mean_Distance: ReversalUp = Z-Score <= -z_thresh (Ueberverkauft), ReversalDown = Z >= +z_thresh (Ueberkauft)",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": False,   # E-5: kein Indikator in Kapitel 17.02
            "batch": True,
            "live": False,
            "feature_store": True,
            "render": False,  # E-5: reine Datenlieferanten
        }

    # --- Single Source of Truth fuer's Prop-Fenster (17.01 §2.2, PineScript-Zone)
    @property
    def parameter_order(self) -> List[str]:
        return list(_TREND_REGIME_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Algorithmus-Modus",
            "period": "Statistik-Fenster",
            "r2_threshold": "Mindest-R2 (LinReg)",
            "di_period": "DMI-Periode (ADX)",
            "adx_smooth": "ADX-Glaettung",
            "adx_threshold": "ADX-Schwellwert",
            "z_thresh": "Z-Score Schwelle",
            "ma_type": "MA-Typ (Z-Score Baseline)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_TREND_REGIME_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _TREND_REGIME_SCHEMA.items()}

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): flache Kopie der Modul-Konstante
        `_TREND_REGIME_OUTPUT_SCHEMA` (PineScript-Input-Zone, M1: kein
        geteiltes mutable Dict)."""
        return {k: dict(v) for k, v in _TREND_REGIME_OUTPUT_SCHEMA.items()}

    # 2. SCHEMA-EXPOSURE FUER DIE UI (17.01.04, Bugfix): Die Spalten-UI
    # (serviceui/param_columns.py & ServiceSelectorWidget) liest Parameter-
    # Definitionen ueber `default_params` / `full_parameter_schema()`. Diese
    # expliziten Overrides stellen das Schema unabhaengig von der jeweiligen
    # parameter_schema-Definition (Property/Klassen-Attribut) bereit und
    # erhalten den Basisklassen-Vertrag (Basis-Parameter wie lookback +
    # plugin-spezifische Parameter, vgl. base_plugin.PluginFeature).
    @property
    def default_params(self) -> Dict[str, Any]:
        """Extrahiert die Default-Werte aus dem parameter_schema fuer die Engine."""
        return {k: v.get("default") for k, v in self.parameter_schema.items()
                if "default" in v}

    def full_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Liefert das vollstaendige Schema (Basis + plugin-spezifisch) inkl.
        Min/Max/Typ fuer die UI-Spalten (Basisklassen-Vertrag)."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Trend-Regimes (LinReg/ADX/Z-Score).

        Datenvertrag (17.02 §3): JEDER Bar entspricht genau EIN Record
        (dichte Label-Reihe fuer ML/Analytics). Trend-Bars tragen
        is_trend_up/is_trend_down bzw. is_reversal_up/is_reversal_down=True
        sowie kausale Zeitstempel (event/confirmation_bar_time,
        confirmation_lag_bars = 0 fuer Bar-Close-Signale). Bars am
        Serienanfang ohne ausreichenden Lookback erhalten
        calculation_status='INSUFFICIENT_DATA'.

        Modi (params['mode']):
          * Linear_Regression_Slope: rolling LinReg auf close
            (Slope > 0 und R2 >= r2_threshold => TrendUp).
          * ADX_DMI: +DI > -DI und ADX >= adx_threshold => TrendUp.
          * ZScore_Mean_Distance: Z <= -z_thresh => ReversalUp,
            Z >= +z_thresh => ReversalDown (Uebertreibungen).
        """
        empty: FeatureCalculateResult = {"feature_store_payload": {}}
        if df is None or df.empty:
            return empty

        # Defensive Normalisierung: 'time'-Spalte (epoch) sicherstellen.
        work = df.copy()
        if "time" not in work.columns:
            if "bar_time" in work.columns:
                work["time"] = work["bar_time"].apply(
                    lambda v: int(v.timestamp())
                    if hasattr(v, "timestamp") else int(v))
            else:
                return empty

        p = self.validate_params(params)
        mode = str(p.get("mode") or "Linear_Regression_Slope")
        period = int(p.get("period") or 20)
        r2_threshold = float(p.get("r2_threshold") or 0.6)
        di_period = int(p.get("di_period") or 14)
        adx_smooth = int(p.get("adx_smooth") or 14)
        adx_threshold = float(p.get("adx_threshold") or 25.0)
        z_thresh = float(p.get("z_thresh") or 2.0)
        ma_type = str(p.get("ma_type") or "SMA")

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)

        is_trend_up = np.zeros(n, dtype=bool)
        is_trend_down = np.zeros(n, dtype=bool)
        is_rev_up = np.zeros(n, dtype=bool)
        is_rev_down = np.zeros(n, dtype=bool)
        status = np.full(n, "OK", dtype=object)
        strength = np.zeros(n, dtype=float)
        strength_type = "R2_SCORE"
        conf_type = "BAR_CLOSE"
        extra: Dict[str, np.ndarray] = {}

        if mode == "Linear_Regression_Slope":
            lr = _rolling_slope_r2(work["close"], period)
            slope = lr["slope"].to_numpy(dtype=float)
            r2 = lr["r2"].to_numpy(dtype=float)
            nan = ~np.isfinite(slope) | ~np.isfinite(r2)
            status[nan] = "INSUFFICIENT_DATA"
            is_trend_up = (slope > 0) & (r2 >= r2_threshold)
            is_trend_down = (slope < 0) & (r2 >= r2_threshold)
            strength = np.where(np.isfinite(r2), r2, 0.0)
            strength_type = "R2_SCORE"
            extra["slope_value"] = np.where(np.isfinite(slope), slope, np.nan)
            extra["r2_score"] = np.where(np.isfinite(r2), r2, np.nan)

        elif mode == "ADX_DMI":
            dmi = _adx_dmi(work, di_period, adx_smooth)
            plus_di = dmi["plus_di"].to_numpy(dtype=float)
            minus_di = dmi["minus_di"].to_numpy(dtype=float)
            adx = dmi["adx"].to_numpy(dtype=float)
            nan = ~np.isfinite(adx)
            status[nan] = "INSUFFICIENT_DATA"
            is_trend_up = (plus_di > minus_di) & (adx >= adx_threshold)
            is_trend_down = (minus_di > plus_di) & (adx >= adx_threshold)
            strength = np.where(np.isfinite(adx), adx, 0.0)
            strength_type = "ADX_VALUE"
            extra["adx_value"] = np.where(np.isfinite(adx), adx, np.nan)
            extra["plus_di"] = np.where(np.isfinite(plus_di), plus_di, np.nan)
            extra["minus_di"] = np.where(np.isfinite(minus_di), minus_di, np.nan)

        elif mode == "ZScore_Mean_Distance":
            # MA-Serie (Template 16.04, alle 12 Typen; VWMA nutzt tick_volume).
            try:
                from chart.indicators.utils.ma_template import MATemplateEngine
            except Exception:
                MATemplateEngine = None  # type: ignore
            if MATemplateEngine is not None and ma_type in (
                    "SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA",
                    "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"):
                volume = work["tick_volume"] if "tick_volume" in work.columns else None
                ma = MATemplateEngine.calculate_ma(
                    work["close"], ma_type, period, volume=volume,
                ).to_numpy(dtype=float)
            else:
                # Fallback: einfacher SMA (defensiv, kein Crash).
                ma = pd.Series(close).rolling(period, min_periods=1).mean().to_numpy()

            z = _zscore_series(work, ma, period)
            nan = ~np.isfinite(z)
            status[nan] = "INSUFFICIENT_DATA"
            is_rev_up = z <= -z_thresh
            is_rev_down = z >= z_thresh
            strength = np.where(np.isfinite(z), np.abs(z), 0.0)
            strength_type = "Z_SCORE"
            extra["z_score_value"] = np.where(np.isfinite(z), z, np.nan)
            extra["mean_baseline"] = np.where(np.isfinite(ma), ma, np.nan)

        else:
            # Unbekannter Modus: defensiv leer (kein Crash, 0 Rows).
            return empty

        # --- Records bauen (dicht: 1 Record pro Bar, 17.02 §3) --------------
        records: List[Dict[str, Any]] = []
        total_up = int(is_trend_up.sum())
        total_down = int(is_trend_down.sum())
        total_rev_up = int(is_rev_up.sum())
        total_rev_down = int(is_rev_down.sum())
        for i in range(n):
            rec: Dict[str, Any] = {
                "bar_time": int(times[i]),
                "result_type": "REVERSAL" if (is_rev_up[i] or is_rev_down[i])
                else "TREND",
                "source_mode": mode,
                "calculation_status": str(status[i]),
                "is_trend_up": bool(is_trend_up[i]),
                "is_trend_down": bool(is_trend_down[i]),
                "is_reversal_up": bool(is_rev_up[i]),
                "is_reversal_down": bool(is_rev_down[i]),
                # Bar-Close-Signal: event == confirmation (Lag 0).
                "event_bar_time": int(times[i]),
                "confirmation_bar_time": int(times[i]),
                "confirmation_lag_bars": 0,
                "confirmation_type": conf_type,
                "trend_strength": float(strength[i]),
                "strength_type": strength_type,
                "reference_price": float(close[i]),
            }
            for k, arr in extra.items():
                rec[k] = float(arr[i]) if np.isfinite(arr[i]) else None
            records.append(rec)

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {
                    # E-7 / base_plugin (U15-A1, Invariante 5): schema_version
                    # ist Pflichtfeld fuer alle feature_store=True-Plugins.
                    "schema_version": "1.0.0",
                    "source_mode": mode,
                    "total_trend_up": total_up,
                    "total_trend_down": total_down,
                    "total_reversal_up": total_rev_up,
                    "total_reversal_down": total_rev_down,
                    "bars": n,
                },
            },
        }

```

--------------------------------------------------

### DATEI: analytics/features/plugins/__init__.py
```py

```

--------------------------------------------------

### DATEI: analytics/features/plugins/base_plugin.py
```py
# analytics/features/plugins/base_plugin.py
"""
Basisklasse & typisierte Verträge für das Plugin-System (Phase 12 + 13).

Kernprinzip: STRICTE ZUSTANDSLOSIGKEIT. Plugins speichern niemals eigene
Zustände oder Parameter. Jede Berechnung ist eine reine Funktion
calculate(df, params, context). Das ermöglicht fehlerfreie Parallelisierung,
Thread-Sicherheit und eine klare Trennung zwischen Feature-Engine
(FeatureStorePayload) und visuellem Indikator (ChartRenderPayload).

Feature-Store-Lese-Regel (präzisiert für Phase 13): Die INDIKATOR-Berechnung
(GUI) liest NIE direkt aus dem Feature-Store; der Scanner schreibt NIE aus dem
Render-Payload. Overlay-Konsumenten (Statistik) lesen den Feature-Store erst
in Phase 13 Schritt 7.
"""

from abc import ABC, abstractmethod
from copy import copy as _shallow_copy
from dataclasses import dataclass, field
from typing import Dict, Any, List, TypedDict, Literal, Optional
import pandas as pd

from config.app_settings import AppSettings


# ==============================================================================
# Parametervalidierung & Schema
# ==============================================================================
class ParameterSchema(TypedDict, total=False):
    type: Literal["float", "int", "bool", "str", "color", "choice"]
    default: Any
    min: Optional[float]
    max: Optional[float]
    step: Optional[float]
    options: Optional[List[str]]
    description: str
    expert: bool  # True → Prop im ausklappbaren Expert-Bereich (Default: False)


# ==============================================================================
# PluginContext & PluginCapabilities (Phase 13)
# ==============================================================================
class PluginCapabilities(TypedDict):
    """Ersetzt das deprecated live_op (Cleanup in Phase 13 Schritt 7)."""
    chart: bool          # als Chart-Indikator verfügbar
    batch: bool          # in der Batch-Pipeline ausführbar
    live: bool           # unterstützt Live-Ticks
    feature_store: bool  # schreibt feature_data in feature_store
    render: bool         # liefert chart_render_payload


@dataclass
class PluginContext:
    """Immutabler Plugin-Kontext für die Service-/Plugin-Ausführung.

    Grundprinzip: Services greifen NIE direkt auf Datenbanken oder globale
    Settings zu – alles läuft über diesen Kontext.
    """
    symbol: str = ""
    timeframe: str = ""
    mode: Literal["chart", "batch", "live"] = "chart"
    timestamp: Optional[int] = None  # epoch-Sekunden des Live-Ticks / der letzten Bar
    shared_state: Dict[str, Any] = field(default_factory=dict)
    settings: Optional[AppSettings] = None  # Kopie (kein globaler Zugriff)
    # Phase 13 Schritt 3: Der ServiceSetEvaluator setzt diese Felder je
    # Service-Aufruf (instance_id = Namespace im shared_state, depends_on =
    # instance_ids, deren shared_state-Einträge der Service liest). Optional
    # und abwärtskompatibel – Direkt-Aufrufe (Schritt 1) bleiben unverändert.
    instance_id: Optional[str] = None
    depends_on: Optional[List[str]] = None

    def __post_init__(self) -> None:
        # Settings werden als Kopie übergeben – mutieren der Ursprungs-Instanz
        # darf den Context nicht beeinflussen (kein globaler Zugriff).
        if self.settings is not None:
            self.settings = _shallow_copy(self.settings)


# ==============================================================================
# Zukunftssicherer ChartRenderPayload (LightweightCharts v5 / JS-Bridge)
# ==============================================================================
class ChartLine(TypedDict):
    price: float
    color: str
    width: int
    style: Literal["solid", "dashed", "dotted"]


class ChartCircle(TypedDict):
    time: int
    price: float
    color: str
    priority: int


class ChartMarker(TypedDict):
    time: int
    position: Literal["aboveBar", "belowBar", "inBar"]
    color: str
    shape: Literal["circle", "square", "arrowUp", "arrowDown"]
    size: int
    text: str
    priority: int


class ChartArea(TypedDict):
    time_from: int
    time_to: int
    price_top: float
    price_bottom: float
    color: str


class ChartLabel(TypedDict):
    time: int
    price: float
    text: str
    color: str


class ChartRenderPayload(TypedDict, total=False):
    lines: List[ChartLine]
    hit_circles: List[ChartCircle]  # JS-Bridge kompatibel
    markers: List[ChartMarker]
    areas: List[ChartArea]          # Erweiterung für Zonen/Kanäle
    labels: List[ChartLabel]        # Erweiterung für Text-Labels
    custom: Dict[str, Any]


# ==============================================================================
# Strikter FeatureStorePayload (DuckDB)
# ==============================================================================
class FeatureStorePayload(TypedDict, total=False):
    """Feature-Store-Payload eines Plugins.

    Phase 15 (U15-A1, Invariante 5): `schema_version` ist für ALLE Plugins mit
    capabilities['feature_store']=True ein PFLICHTFELD (Semantic Versioning,
    major.minor.patch) und wird im `metadata`-Objekt gestempelt. Der
    GUI-Lesepfad (Indikator) prüft sie beim Chart-Re-Render.
    """
    feature_id: str
    plugin_version: str
    records: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    schema_version: str
    statistics: Dict[str, Any]


class FeatureCalculateResult(TypedDict):
    feature_store_payload: FeatureStorePayload
    chart_render_payload: ChartRenderPayload


# ==============================================================================
# Plugin-Metadaten & Schnittstelle
# ==============================================================================
class PluginMetadata(TypedDict):
    category: str
    display_name: str
    description: str
    author: str
    tags: List[str]
    # Phase 14 P14-01: Erweiterte Beschreibungsfelder (Markdown-Hilfe,
    # strukturierte Regeln und explizite API-Version). Defaults in
    # PluginFeature.metadata: description_long="", condition_rules=[], api_version="1".
    description_long: str
    condition_rules: List[str]
    api_version: str


# ==============================================================================
# P14-03 (Schritt 2.2): Strukturiertes Fehlerobjekt (maschinelle Auswertung)
# ==============================================================================
class ServiceErrorLog(TypedDict):
    """Strukturiertes Fehlerobjekt für das Logging in PluginExecutor und
    ServiceSetEvaluator (Pflichtfelder laut P14-03 Anleitung).

    Wird ausschließlich für die maschinelle Auswertung von Service-Fehlern
    verwendet (timestamp, plugin_id, instance_id, symbol, timeframe, bar_time,
    exception, traceback). PluginExecutionErrorInfo (feature_builder.py) liefert
    über to_service_error_log() ein exakt dieses TypedDict erfüllendes Dict.
    """
    timestamp: float
    plugin_id: str
    instance_id: Optional[str]
    symbol: str
    timeframe: str
    bar_time: Optional[int]
    exception: str
    traceback: str


class PluginFeature(ABC):
    """Stateless Plugin-Basisklasse mit Schemavalidierung und Metadaten."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Dauerhaft stabile ID (z.B. 'srv_grid_lines')."""
        pass

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> PluginMetadata:
        return {
            "category": "General",
            "display_name": self.plugin_id.replace("_", " ").title(),
            "description": "",
            "author": "System",
            "tags": [],
            # Phase 14 P14-01: Defaults für die erweiterten Beschreibungsfelder
            "description_long": "",
            "condition_rules": [],
            "api_version": "1",
        }

    @property
    def live_op(self) -> bool:
        """DEPRECATED: wird durch capabilities['live'] ersetzt
        (Cleanup in Phase 13 Schritt 7)."""
        return True

    @property
    def capabilities(self) -> PluginCapabilities:
        """PluginCapabilities (Phase 13) – ersetzt live_op."""
        return {
            "chart": True,
            "batch": True,
            "live": self.live_op,
            "feature_store": True,
            "render": True,
        }

    @property
    def dependencies(self) -> List[str]:
        """IDs anderer Plugins, die vorab berechnet werden müssen."""
        return []

    @property
    @abstractmethod
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Schema zur automatischen Validierung & UI-Generierung."""
        pass

    @property
    def base_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Basis-Parameter, die für ALLE Services gelten (Trading & Live).

        Phase 13 Schritt 5: Der lookback ist das Scan-Fenster jeder
        Service-Instanz (ServiceInstanceConfig.lookback). Er wird im
        Expert-Bereich des Prop-Fensters angezeigt und ist für jeden Service
        einzeln einstellbar. Was in den Expert-Bereich kommt, wird ALSO an den
        Parametern der (Service-)Definition angegeben – hier in der
        Basisklasse per 'expert': True. Plugins können weitere expert-Parameter
        in ihrem eigenen parameter_schema markieren.
        """
        return {
            "lookback": {
                "type": "int",
                "default": 1000,
                "min": 100,
                "max": 100000,
                "step": 50,
                "description": "Lookback (Scan-Fenster)",
                "expert": True,
            },
        }

    def full_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Vollständiges Schema: Basis-Parameter (z.B. lookback) + plugin-
        spezifische Parameter (Definition). Basis gewinnt NICHT – die
        Plugin-Definition überschreibt den Basis-Eintrag, falls sie denselben
        Key selbst definiert."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): dokumentiert alle im `feature_data`-JSON
        erzeugten Ergebnisspalten samt Typ und Beschreibung.

        Format: {"field_name": {"type": str, "description": str,
        "technical": bool (optional)}} – `technical: True` kennzeichnet
        System-/Metadaten-Felder (z. B. calculation_status), die die UI
        kompakt in einem Unterblock `🔧 System-Metrik` anzeigt (E2).

        Konventionen (Kapitel 20.03, E1/E4/E5):
          * Abwärtskompatibler Default: leeres Dict – Plugins ohne Schema
            zeigen keinen Resultatfelder-Block.
          * `bar_time` wird NICHT deklariert – es ist eine native
            DB-Spalte, kein `feature_data`-JSON-Key (E4).
          * `type` ist ein freier String (E5), z. B. "bool", "float",
            "int", "str" oder "list[float]".
        """
        return {}

    @property
    def parameter_order(self) -> List[str]:
        """Darstellungs-Reihenfolge der Props im Prop-Fenster.

        Single Source of Truth: Kann an den ANFANG jeder Plugin-/Service-
        Definition überschrieben werden. Default = Reihenfolge aus dem Schema.
        """
        return list(self.parameter_schema.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        """Label-Namen der Props im Prop-Fenster.

        Single Source of Truth: Kann an den ANFANG jeder Plugin-/Service-
        Definition überschrieben werden. Default = description bzw.
        humanisierter Parameter-Key.
        """
        labels: Dict[str, str] = {}
        for key, spec in self.full_parameter_schema().items():
            desc = spec.get("description", "")
            labels[key] = desc if desc else key.replace("_", " ").title()
        return labels

    def is_expert_param(self, key: str) -> bool:
        """True, wenn der Parameter mit expert=True markiert ist (Default: False)."""
        return bool(self.full_parameter_schema().get(key, {}).get("expert", False))

    @property
    def default_params(self) -> Dict[str, Any]:
        return {k: v["default"] for k, v in self.full_parameter_schema().items() if "default" in v}

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validiert Eingabeparameter gegen das Schema und setzt Defaults ein.

        min/max werden hart geclippt; step dient als Widget-Schrittweite im
        Prop-Fenster (keine Rundung auf step im Validator).
        """
        validated = {}
        schema = self.parameter_schema
        for key, spec in schema.items():
            val = params.get(key, spec.get("default"))
            p_type = spec.get("type")

            if val is None:
                # Kein Default angegeben → typspezifischen Null-Wert verwenden
                val = 0.0 if p_type == "float" else 0 if p_type == "int" else False if p_type == "bool" else ""
            elif p_type == "float":
                val = float(val)
            elif p_type == "int":
                val = int(val)
            elif p_type == "bool":
                val = bool(val)

            try:
                if "min" in spec and val < spec["min"]:
                    val = spec["min"]
                if "max" in spec and val > spec["max"]:
                    val = spec["max"]
            except TypeError:
                # Nicht-vergleichbare Werte (z.B. bool/color) unverändert lassen
                pass

            validated[key] = val
        return validated

    @abstractmethod
    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Stateless Berechnungslogik: Leseinput = df + validated_params.

        Rückwärtskompatibilität Phase 12: calculate(df, params) ohne context
        bleibt gültig (context ist Optional).
        """
        pass

```

--------------------------------------------------

