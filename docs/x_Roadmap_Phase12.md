
# Roadmap Phase 12: Dynamische Feature- & Signal-Architektur (Refined)

## 1. Zielsetzung & Architektur-Konzept

Das Ziel von Phase 12 ist die **vollständige Entkopplung von Berechnungslogik, Parameter-Steuerung, Speicherung und visueller Darstellung**, ohne bestehenden Code zu brechen.

### Entkopplungs-Prinzip: Feature-Engine vs. Visueller Indikator
* **Plugin-Engine (`PluginFeature`):** Reine mathematische/logische Berechnung (z. B. Grid-Abstände, Trend-Filter, Machine-Learning-Features). Sie liegt isoliert unter `analytics/features/definitions/` und generiert sowohl den strukturierten Feature-Store-Payload (für DuckDB) als auch den typisierten Visualisierungs-Payload (`ChartRenderPayload`).
* **Visueller Indikator (`BaseIndicator` / Chart-UI):** Konsumiert den `ChartRenderPayload` des Features, steuert die Interaktion im Chart (Settings-Dialog, Button-Styles) und verwaltet das Rendern über die JS-Bridge (`LightweightCharts v5`).

                 ┌────────────────────────────────────────┐
                 │   analytics/features/definitions/      │
                 │ (grid_liquidity.py, ema_diff_v2.py)    │
                 └───────────────────┬────────────────────┘
                                     │
                               PluginLoader
                        (Auto-Discovery, Thread-Safe)
                                     │
            ┌────────────────────────┴────────────────────────┐
            ▼                                                 ▼

┌──────────────────────────┐                      ┌──────────────────────────┐
│       Chart-UI           │                      │      Batch-Service       │
│ (PyTraderChartWindow)    │                      │   (HistoricalScanner)    │
├──────────────────────────┤                      ├──────────────────────────┤
│ - Holt Preset aus DB     │                      │ - Holt Preset aus DB     │
│ - Tuned Parameter        │                      │ - Führt Massen-Scan aus  │
│ - Rendert Chart-Payload  │                      │ - Schreibt Feature-Store │
└────────────┬─────────────┘                      └────────────┬─────────────┘
│                                                 │
▼                                                 ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                       DuckDB (Hybrid-Schema)                               │
│ - app_data.duckdb  : indicator_presets (Erweitert um version & batch)     │
│ - analytics.duckdb : feature_store     (Native Spalten + feature_data JSON) │
│ - analytics.duckdb : signal_results    (Generischer Event-Store)           │
└────────────────────────────────────────────────────────────────────────────┘


---

## 2. Datenbank-Architektur (Hybrid-Schema & Konsolidierte Presets)

Die Kern-Datenbanken werden über `db_service.py` abwärtskompatibel erweitert.

```sql
-- 1. ANALYTICS.DUCKDB: Hybrid-Feature Store (Additive Erweiterung)
ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_id VARCHAR;
ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS plugin_version VARCHAR;
ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_data JSON;

-- 2. APP_DATA.DUCKDB: Erweiterung der bestehenden indicator_presets Tabelle
ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS version VARCHAR DEFAULT '1.0.0';
ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS is_active_batch BOOLEAN DEFAULT FALSE;
```

3. Typisierte Verträge (PluginFeature)

Verortet in analytics/features/plugins/base_plugin.py, um Kollisionen mit der Alt-Klasse BaseFeature zu vermeiden.
Python

from abc import ABC, abstractmethod
from typing import Dict, Any, List, TypedDict, Literal
import pandas as pd

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

class ChartRenderPayload(TypedDict, total=False):
    lines: List[ChartLine]
    hit_circles: List[ChartCircle]  # Harmonisiert mit bestehender JS-Bridge!
    markers: List[ChartMarker]

class FeatureCalculateResult(TypedDict):
    feature_store_payload: Dict[str, Any]
    chart_render_payload: ChartRenderPayload

class PluginFeature(ABC):
    """Neue Plugin-Basisklasse zur sauberen Trennung von der Alt-Klasse BaseFeature."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def display_name(self) -> str:
        return self.name.replace("_", " ").title()

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def plugin_id(self) -> str:
        return f"{self.name}_v{self.version.replace('.', '_')}"

    @property
    def live_op(self) -> bool:
        return True

    @property
    @abstractmethod
    def default_params(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> FeatureCalculateResult:
        pass

4. Feature-Paritäts-Plugin (grid_liquidity.py)

Inklusive Custom-Levels, Pierce/Visit-Logik und Zeitfenster-Farben.
Python

from typing import Dict, Any
import pandas as pd
import numpy as np
from analytics.features.plugins.base_plugin import PluginFeature, FeatureCalculateResult

class GridLiquidityFeature(PluginFeature):

    @property
    def name(self) -> str:
        return "grid_liquidity"

    @property
    def display_name(self) -> str:
        return "Grid Liquidity & Proximity"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "grid_step": 0.50,
            "proximity_threshold": 0.05,
            "line_color": "#2196F3",
            "circle_color_std": "#FFEB3B",
            "circle_color_active": "#E91E63",
            "show_lines": True,
            "show_circles": True,
            "prox_level1": 0.0,
            "prox_level2": 0.0,
            "prox_level3": 0.0,
            "prox_level4": 0.0,
            "prox_level5": 0.0,
            "prox_level6": 0.0,
        }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> FeatureCalculateResult:
        if df.empty:
            return {"feature_store_payload": {}, "chart_render_payload": {}}

        p = {**self.default_params, **params}
        step = p["grid_step"]
        threshold = p["proximity_threshold"]

        min_price = df["low"].min()
        max_price = df["high"].max()

        start_lvl = np.floor(min_price / step) * step
        end_lvl = np.ceil(max_price / step) * step
        levels = list(np.arange(start_lvl, end_lvl + step, step))

        # Custom Levels einbinden
        custom_lvls = [p[f"prox_level{i}"] for i in range(1, 7) if p[f"prox_level{i}"] > 0]
        all_levels = sorted(list(set(levels + custom_lvls)))

        lines_payload = []
        if p["show_lines"]:
            lines_payload = [
                {"price": float(lvl), "color": p["line_color"], "width": 1, "style": "solid"}
                for lvl in all_levels
            ]

        hit_circles = []
        feature_rows = []

        for idx, row in df.iterrows():
            close_price = row["close"]
            bar_time = int(row["time"])

            nearest_lvl = round(close_price / step) * step
            dist = abs(close_price - nearest_lvl)
            is_hit = dist <= threshold

            if is_hit and p["show_circles"]:
                # Zeitfenster-Farblogik (Beispiel: Asien/London-Aktivität)
                dt = pd.to_datetime(bar_time, unit='s')
                is_active_window = 8 <= dt.hour <= 16
                color = p["circle_color_active"] if is_active_window else p["circle_color_std"]

                hit_circles.append({
                    "time": bar_time,
                    "price": float(close_price),
                    "color": color,
                    "priority": 10
                })

            feature_rows.append({
                "bar_time": bar_time,
                "nearest_level": float(nearest_lvl),
                "distance": float(dist),
                "is_hit": bool(is_hit)
            })

        return {
            "feature_store_payload": {"records": feature_rows},
            "chart_render_payload": {
                "lines": lines_payload,
                "hit_circles": hit_circles
            }
        }

5. Scope & Abgrenzung (Signal-Engine)

    Hinweis zur Phasen-Grenzziehung: Phase 12 behandelt exklusiv die Entkopplung und Dynamisierung der Feature-/Indikator-Ebene. Die Signal-Engine (z. B. GridProximitySignal, set_evaluator.py) bleibt in dieser Phase unverändert und greift weiterhin über das Hybrid-Schema auf die benötigten Feature-Werte zu. Die Verallgemeinerung der Signal-Sets ist Gegenstand von Phase 13.

---


# Phase 12: Step-by-Step AI Implementation Guide

Dieser Leitfaden ist strikt darauf ausgelegt, dass nach jedem Schritt ein voll funktionsfähiger Projektzustand gewährleistet bleibt.
Schritt 1: Datenbank-Erweiterung (Hybrid-Schema & Presets)
1.1 Backup-Anforderung

Erstelle vor Ausführung ein vollständiges Backup des Ordners data/ sowie der Datei db_service.py nach .backup_Phase12_Step1/.
1.2 Anweisung an die AI

    Öffne db_service.py und passe check_and_init_databases() an.

    Füge folgende DDL-Statements aus:

Python

con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_id VARCHAR;")
con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS plugin_version VARCHAR;")
con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_data JSON;")

con_app.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS version VARCHAR DEFAULT '1.0.0';")
con_app.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS is_active_batch BOOLEAN DEFAULT FALSE;")

1.3 Validierung & Test

Starte main.py. Verifiziere in der Konsole, dass die Migration fehlerfrei durchläuft und die alten Daten in ohlcv_bars sowie feature_store erhalten bleiben.
Schritt 2: Neue Plugin-Basisklasse (PluginFeature)
2.1 Backup-Anforderung

Erstelle ein Backup des Ordners analytics/features/ nach .backup_Phase12_Step2/. Note: Die bestehende analytics/features/base_feature.py DARF NICHT verändert oder gelöscht werden!

2.2 Anweisung an die AI

    Erstelle das Unterverzeichnis analytics/features/plugins/ mit einer leeren __init__.py.

    Erstelle darin die Datei base_plugin.py mit den Klassen PluginFeature, ChartRenderPayload (inkl. hit_circles) und FeatureCalculateResult.

2.3 Validierung & Test

Führe python -c "from analytics.features.plugins.base_plugin import PluginFeature" aus. Die Anwendung muss wie gewohnt starten.
Schritt 3: Thread-Sicherer PluginLoader

3.1 Backup-Anforderung

Sichere analytics/features/feature_builder.py nach .backup_Phase12_Step3/.

3.2 Anweisung an die AI

    Erstelle das Verzeichnis analytics/features/definitions/ mit einer leeren __init__.py.

    Erstelle in analytics/features/feature_builder.py die Klasse PluginLoader.

    Implementiere _discover_plugins(), das alle Module in analytics/features/definitions/ einliest. Entferne automatische importlib.reload()-Aufrufe innerhalb der Getter-Methoden, um Race Conditions zwischen QThreads zu vermeiden.

3.3 Validierung & Test

Erstelle ein Testskript test/check_plugin_loader.py und stelle sicher, dass PluginLoader().list_plugins() ohne Fehler aufgerufen werden kann.
Schritt 4: Paritäts-Plugin & Regressionstest gegen Altsystem

4.1 Backup-Anforderung

Sichere das Verzeichnis analytics/features/definitions/ nach .backup_Phase12_Step4/.

4.2 Anweisung an die AI

    Erstelle analytics/features/definitions/grid_liquidity.py mit der Klasse GridLiquidityFeature(PluginFeature).

    Erstelle ein Vergleichs-Testskript test/check_grid_parity.py, das identische OHLCV-Daten durch den alten GridIndicator.calculate() und das neue GridLiquidityFeature.calculate() schickt.


4.3 Validierung & Test

Führe python test/check_grid_parity.py aus. Die Anzahl und Positionen der berechneten Grid-Linien und Circles müssen exakt übereinstimmen.
Schritt 5: Anbindung Chart UI, JS-Bridge & Presets

5.1 Backup-Anforderung

Sichere chart/indicators/grid.py, chart/chart_win.py, state_manager.py sowie chart/js/03_chart_rendering.js nach .backup_Phase12_Step5/.

5.2 Anweisung an die AI

    Erweitere state_manager.py um die abwärtskompatible Handhabung von version und is_active_batch in indicator_presets.

    Passe chart/indicators/grid.py so an, dass calculate() intern das GridLiquidityFeature nutzt und dessen chart_render_payload zurückgibt.

    Überprüfe in chart/js/03_chart_rendering.js und 04_live_updates.js, dass das Feld hit_circles nahtlos von renderGridCircles() verarbeitet wird.

5.3 Validierung & Test

Starte PyTrader, öffne ein Chart-Fenster, schalte das Grid ein, verändere Parameter im Dialog und speichere ein Preset. Das Chart muss die Linien und Kreise korrekt rendern.
Schritt 6: Anbindung Batch-Services (Scanner & Analyzer)

6.1 Backup-Anforderung

Sichere analytics/background_workers/historical_scanner.py und live_analyzer.py nach .backup_Phase12_Step6/.

6.2 Anweisung an die AI

    Erweitere den HistoricalScanner: Wenn ein Plugin-Scan angefordert wird, liest er das als is_active_batch = True markierte Preset aus indicator_presets.

    Er führt plugin.calculate(df, params) aus und speichert feature_store_payload im feature_store in DuckDB ab.

    Der LiveAnalyzer nutzt bei Bar-Closes dieselbe Plugin-Instanz.

6.3 Validierung & Test

Starte im Service-Fenster einen historischen Scan für SILVER H1. Prüfe in der Konsole und via DuckDB-Abfrage, ob Einträge in feature_store geschrieben wurden.
Schritt 7: Systemweiter Regressionstest

7.1 Backup-Anforderung

Sichere das gesamte Projekt nach .backup_Phase12_Final/.

7.2 Anweisung an die AI

    Prüfe alle Fenster (Hauptfenster, Chart-Fenster, Service-Fenster, Statistik-Fenster, Optionen) auf korrekte Funktion.

    Führe alle vorhandenen Test-Skripte im Ordner test/ aus.

7.3 Validierung & Test

Vollständiger End-to-End-Test: App-Start → Chart öffnen → Parameter anpassen → Preset speichern → Historical Scan ausführen → Live-Signale empfangen. Alle Funktionen müssen stabil laufen.