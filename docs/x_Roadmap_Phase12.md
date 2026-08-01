# Roadmap Phase 12: Dynamische Feature- & Signal-Architektur (Vollständig synthetisiert)

## 1. Zielsetzung & Architektur-Konzept

Das Ziel von Phase 12 ist die vollständige Entkopplung von Berechnungslogik, Parameter-Steuerung, Speicherung und visueller Darstellung bei 100%iger Abwärtskompatibilität zum bestehenden Codebase.
Core Architecture & Guiding Principles

    Strikte Zustandslosigkeit (Stateless Plugins): Plugins speichern niemals eigene Zustände oder Parameter. Jede Berechnung ist eine reine Funktion calculate(df, params). Das ermöglicht fehlerfreie Parallelisierung und Thread-Sicherheit.

    Entkopplung Feature-Engine vs. Visueller Indikator:

        Plugin-Engine (PluginFeature): Reine Mathematik/Logik unter analytics/features/definitions/. Generiert strikt getrennt den FeatureStorePayload (für DuckDB) und den ChartRenderPayload (für LightweightCharts v5).

        Visueller Indikator (BaseIndicator / Chart-UI): Konsumiert den ChartRenderPayload und steuert UI-Interaktionen. Der Chart liest niemals direkt aus dem Feature-Store; der Scanner schreibt niemals aus dem Render-Payload.

    Additive Rückwärtskompatibilität: Alt-Indikatoren und bestehende BaseFeature-Klassen bleiben unangetastet parallel lauffähig.

    Zentrale Ausführungsschicht (PluginExecutor): Scanner, Analyzer und Chart-UI greifen nicht direkt auf Plugins zu, sondern nutzen die PluginExecutor-Schicht für zentrales Logging, Caching, Parametervalidierung und Thread-Safety.

                               ┌────────────────────────────────────────┐
                               │   analytics/features/definitions/      │
                               │  (grid_liquidity.py, ema_diff_v2.py)   │
                               └───────────────────┬────────────────────┘
                                                   │
                                             PluginLoader
                                      (Discovery, Validation)
                                                   │
                                            PluginRegistry
                                                   │
                                            PluginExecutor
                                  (Execution, Caching, Logging)
                                                   │
                  ┌────────────────────────────────┴────────────────────────────────┐
                  ▼                                                                 ▼
   ┌──────────────────────────────┐                                ┌──────────────────────────────┐
   │          Chart-UI            │                                │        Batch-Services        │
   │    (PyTraderChartWindow)     │                                │ (HistoricalScanner/Analyzer) │
   ├──────────────────────────────┤                                ├──────────────────────────────┤
   │ - Liest Schema & Schema-UI   │                                │ - Holt Preset per plugin_id  │
   │ - Validiert Parameter        │                                │ - Validiert Parameter        │
   │ - Rendert ChartRenderPayload │                                │ - Schreibt FeatureStorePayload│
   └──────────────┬───────────────┘                                └──────────────┬───────────────┘
                  │                                                               │
                  ▼                                                               ▼
   ┌──────────────────────────────────────────────────────────────────────────────────────────────┐
   │                                   DuckDB (Hybrid-Schema)                                     │
   │ - app_data.duckdb  : indicator_presets (mit plugin_id, version, params, is_active_batch)    │
   │ - analytics.duckdb : feature_store     (Native Spalten + feature_data JSON + feature_id)    │
   │ - analytics.duckdb : signal_results    (Generischer Event-Store)                             │
   └──────────────────────────────────────────────────────────────────────────────────────────────┘

## 2. Datenbank-Architektur (Hybrid-Schema & Stabile Presets)
Stabile Schema-Entscheidungen

    Stabile plugin_id: Die plugin_id bleibt dauerhaft konstant (z.B. grid_liquidity). Die Versionierung wird als eigene Spalte version geführt, damit Presets und Datenbank-Referenzen bei Version-Updates nicht abreißen.

    Eindeutige Preset-Zuordnung: indicator_presets wird um plugin_id, version und is_active_batch erweitert.

SQL

-- 1. ANALYTICS.DUCKDB: Hybrid-Feature Store (Additive Erweiterung)
ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_id VARCHAR;
ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS plugin_version VARCHAR;
ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_data JSON;

-- 2. APP_DATA.DUCKDB: Erweiterung der indicator_presets Tabelle um Plugin-Verknüpfung
ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS plugin_id VARCHAR;
ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS version VARCHAR DEFAULT '1.0.0';
ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS is_active_batch BOOLEAN DEFAULT FALSE;

## 3. Typisierte Verträge & Basisklasse (PluginFeature)

Verortet unter analytics/features/plugins/base_plugin.py.
Python

from abc import ABC, abstractmethod
from typing import Dict, Any, List, TypedDict, Literal, Optional
import pandas as pd

# --- Parametervalidierung & Schema ---
class ParameterSchema(TypedDict, total=False):
    type: Literal["float", "int", "bool", "str", "color", "choice"]
    default: Any
    min: Optional[float]
    max: Optional[float]
    step: Optional[float]
    options: Optional[List[str]]
    description: str

# --- Zukunftssicherer ChartRenderPayload ---
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

# --- Strikter FeatureStorePayload ---
class FeatureStorePayload(TypedDict, total=False):
    feature_id: str
    plugin_version: str
    records: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    statistics: Dict[str, Any]

class FeatureCalculateResult(TypedDict):
    feature_store_payload: FeatureStorePayload
    chart_render_payload: ChartRenderPayload

# --- Plugin-Metadaten & Schnittstelle ---
class PluginMetadata(TypedDict):
    category: str
    display_name: str
    description: str
    author: str
    tags: List[str]

class PluginFeature(ABC):
    """Stateless Plugin-Basisklasse mit Schemavalidierung und Metadaten."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Dauerhaft stabile ID (z.B. 'grid_liquidity')."""
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
            "tags": []
        }

    @property
    def live_op(self) -> bool:
        return True

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
    def default_params(self) -> Dict[str, Any]:
        return {k: v["default"] for k, v in self.parameter_schema.items() if "default" in v}

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validiert Eingabeparameter gegen das Schema und setzt Defaults ein."""
        validated = {}
        schema = self.parameter_schema
        for key, spec in schema.items():
            val = params.get(key, spec.get("default"))
            p_type = spec.get("type")
            if p_type == "float": val = float(val)
            elif p_type == "int": val = int(val)
            elif p_type == "bool": val = bool(val)
            
            if "min" in spec and val < spec["min"]: val = spec["min"]
            if "max" in spec and val > spec["max"]: val = spec["max"]
            validated[key] = val
        return validated

    @abstractmethod
    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> FeatureCalculateResult:
        """Stateless Berechnungslogik: Leseinput = df + validated_params."""
        pass

## 4. Feature-Paritäts-Plugin (grid_liquidity.py)

Vollständiges Plugin unter analytics/features/definitions/grid_liquidity.py.
Python

from typing import Dict, Any
import pandas as pd
import numpy as np
from analytics.features.plugins.base_plugin import PluginFeature, FeatureCalculateResult, ParameterSchema, PluginMetadata

class GridLiquidityFeature(PluginFeature):

    @property
    def plugin_id(self) -> str:
        return "grid_liquidity"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> PluginMetadata:
        return {
            "category": "Grid",
            "display_name": "Grid Liquidity & Proximity",
            "description": "Erkennt Preisnähe zu Grid-Leveln inkl. Custom Levels & Zeitfenstern",
            "author": "PyTrader AI",
            "tags": ["grid", "liquidity", "proximity"]
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        return {
            "grid_step": {"type": "float", "default": 0.50, "min": 0.01, "max": 100.0, "step": 0.05, "description": "Rasterabstand"},
            "proximity_threshold": {"type": "float", "default": 0.05, "min": 0.001, "max": 10.0, "step": 0.005, "description": "Toleranzschwelle"},
            "line_color": {"type": "color", "default": "#2196F3", "description": "Farbe Grid-Linien"},
            "circle_color_std": {"type": "color", "default": "#FFEB3B", "description": "Farbe Standard-Hit"},
            "circle_color_active": {"type": "color", "default": "#E91E63", "description": "Farbe Hit in Aktivitätsfenster"},
            "show_lines": {"type": "bool", "default": True, "description": "Grid-Linien anzeigen"},
            "show_circles": {"type": "bool", "default": True, "description": "Hits anzeigen"},
            "prox_level1": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 1"},
            "prox_level2": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 2"},
            "prox_level3": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 3"},
            "prox_level4": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 4"},
            "prox_level5": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 5"},
            "prox_level6": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 6"},
        }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> FeatureCalculateResult:
        if df.empty:
            return {"feature_store_payload": {}, "chart_render_payload": {}}

        p = self.validate_params(params)
        step = p["grid_step"]
        threshold = p["proximity_threshold"]

        min_price = df["low"].min()
        max_price = df["high"].max()

        start_lvl = np.floor(min_price / step) * step
        end_lvl = np.ceil(max_price / step) * step
        levels = list(np.arange(start_lvl, end_lvl + step, step))

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
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": feature_rows,
                "metadata": {"total_hits": len(hit_circles)}
            },
            "chart_render_payload": {
                "lines": lines_payload,
                "hit_circles": hit_circles
            }
        }

### Entscheidungen (verbindliche Vorgaben für Phase 12)

**1. Native UTC-Zeitfenster (unantastbar):**
Das native UTC-Zeitfenster (Minute 0/30 ± `time_window_mins`, vektorisiert in `analytics/features/definitions/grid_levels.py` → `in_window_around()` bzw. `chart/indicators/grid.py` → `f_in_window_around()`) ist **grundlegende Logik und wird nie mehr angefasst**. Die im Plugin-Beispiel oben verwendete Farb-/Aktivitätslogik (`8 <= dt.hour <= 16`) ist **ausschließlich ein Platzhalter** und darf das native Zeitfenster **nicht ersetzen**. Andere Zeitkonzepte (Sessions, etc.) werden bei Bedarf in einem **separaten Layer darübergelegt** – nie in die native Logik hinein.

**2. Liq-Raster-Persistenz – Phase 11 wird hiermit abgeschlossen:**
Phase 11 gilt mit dem aktuellen Stand als beendet. Die persistente Speicherung des **vollständigen Liq-Rasters** (Level-Liste, nicht nur das per-Bar Nearest-Level im `feature_store_payload`) wird **nicht** in Phase 12 vorweggenommen, sondern später **im neuen Plugin-System erweitert** (Service schreibt Raster in die DB → Indikator holt es von dort).

**3. Bestands-Indikator bleibt unangetastet (hardcoded):**
Der existierende Grid-Indikator (`chart/indicators/grid.py`) wird in Phase 12 **weder verändert noch entfernt** – er bleibt in seiner aktuellen, hartkodierten Form voll funktionsfähig (Referenz-Alt-Implementierung, kann jederzeit parallel betrieben werden). Phase 12 baut daraus einen **NEUEN Grid-Indikator** mit Plugin-Architektur (siehe Schritt 5): Die Service-Logik wandert in das Plugin (`GridLiquidityFeature`), der neue Indikator konsumiert dessen `chart_render_payload`. Beide laufen parallel in der Chart-Registry (Alt: `grid`, Neu: `grid_liquidity`). Der Paritätstest (Schritt 4) dient dem Vergleich, nicht der Migration des Alt-Codes.

**4. Neues Property-Fenster – eigenständige Entwicklung NACH Phase 12:**
Der NEUE Grid-Indikator erhält ein **vollständig neues Property-Fenster** (kein Wiederverwenden/Anpassen des bestehenden `indicator_dialog.py`). Darin erscheinen zusätzlich zu den Indikator-Parametern **Standard-Felder des genutzten Services** mit zugehörigen **Action-Buttons** (z. B. Service-Scan auslösen, Preset laden/speichern). Dieses Property-Fenster ist eine **komplett neue Entwicklung und startet NACH Phase 12** – in Phase 12 wird der neue Indikator nur mit seinen Basis-Parametern über den bestehenden generischen Dialog (Interim) bedient.

## 5. Ausführungsschicht (PluginLoader, PluginRegistry, PluginExecutor)

Verortet in analytics/features/feature_builder.py.
Python

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Dict, Type, Optional, Any
import pandas as pd
from analytics.features.plugins.base_plugin import PluginFeature, FeatureCalculateResult

class PluginLoader:
    """Class-Finder scannt Verzeichnisse rein nach Subklassen von PluginFeature (Dateiname-unabhängig)."""
    
    def __init__(self, definitions_path: Optional[Path] = None):
        self.definitions_path = definitions_path or Path(__file__).parent / "definitions"

    def discover_plugins(self) -> Dict[str, PluginFeature]:
        plugins = {}
        if not self.definitions_path.exists():
            return plugins

        for _, module_name, is_pkg in pkgutil.iter_modules([str(self.definitions_path)]):
            if is_pkg: continue
            full_module_name = f"analytics.features.definitions.{module_name}"
            try:
                module = importlib.import_module(full_module_name)
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, PluginFeature) and obj is not PluginFeature:
                        instance = obj()
                        plugins[instance.plugin_id] = instance
            except Exception as e:
                print(f"⚠️ [PluginLoader] Fehler in Modul {module_name}: {e}")
        return plugins

class PluginRegistry:
    """Zentraler Singleton-Katalog für entdeckte Plugins."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.loader = PluginLoader()
            cls._instance.plugins = cls._instance.loader.discover_plugins()
        return cls._instance

    def reload(self):
        """Expliziter Reload nur beim Start oder per Button (thread-sicher)."""
        self.plugins = self.loader.discover_plugins()

    def get(self, plugin_id: str) -> PluginFeature:
        if plugin_id not in self.plugins:
            raise KeyError(f"Plugin '{plugin_id}' nicht gefunden.")
        return self.plugins[plugin_id]

class PluginExecutor:
    """Zentrale Schicht für Ausführung, Validierung, Dependency-Ordering & Logging."""

    def __init__(self, registry: Optional[PluginRegistry] = None):
        self.registry = registry or PluginRegistry()

    def execute(self, plugin_id: str, df: pd.DataFrame, params: Dict[str, Any]) -> FeatureCalculateResult:
        plugin = self.registry.get(plugin_id)
        
        # 1. Dependency Resolution (falls Abhängigkeiten angegeben sind)
        for dep_id in plugin.dependencies:
            dep_plugin = self.registry.get(dep_id)
            dep_plugin.calculate(df, dep_plugin.default_params)

        # 2. Parametervalidierung
        validated_params = plugin.validate_params(params)

        # 3. Stateless Execution
        return plugin.calculate(df, validated_params)

## 6. Scope & Abgrenzung (Signal-Engine)

    Grenzziehung: Phase 12 entkoppelt und dynamisiert exklusiv die Feature-/Indikator-Ebene. Die Signal-Engine (GridProximitySignal, set_evaluator.py) bleibt unverändert und greift weiterhin über das Hybrid-Schema auf die benötigten Feature-Werte zu. Die Verallgemeinerung der Signal-Sets folgt in Phase 13.

    **Entscheidung (verbindlich):** Die Signal-Engine ist **nur eine Test-Engine**. Sie wird in einer späteren Phase als **Service in das Plugin-System überführt** und dort durch einen Indikator visualisiert. In Phase 12 bleibt sie unverändert (nur über das Hybrid-Schema angebunden).

## 7. Zusätzliche Architektur-Vorbereitung (additiv)

### 7.1 PluginCapabilities (optionale Erweiterung)

Zur Vorbereitung zukünftiger Plugin-Typen kann die Eigenschaft `live_op` später durch ein allgemeineres Capability-Modell ergänzt werden. Dadurch lässt sich zentral definieren, in welchen Systembereichen ein Plugin verwendet werden darf, ohne Sonderlogik in Chart, Scanner oder Analyzer zu hinterlegen.

**Beispiel:**

```python
class PluginCapabilities(TypedDict):
    chart: bool
    batch: bool
    live: bool
    feature_store: bool
    render: bool
```

Diese Erweiterung ist **nicht Bestandteil von Phase 12**, wird jedoch für spätere Analyse-, ML- oder Service-Plugins empfohlen.

---

### 7.2 PluginContext (API-Vorbereitung)

Die aktuelle Schnittstelle `calculate(df, params)` bleibt in Phase 12 unverändert.

Zur langfristigen Erweiterbarkeit kann später ein optionaler `PluginContext` eingeführt werden, der Laufzeitinformationen wie Symbol, Timeframe, Ausführungsmodus oder weitere Services kapselt.

**Beispiel:**

```python
calculate(context, df, params)
```

Ein möglicher `PluginContext` enthält beispielsweise:

- symbol
- timeframe
- mode (live / historical)
- timestamp

Diese Vorbereitung verhindert zukünftige API-Brüche, wenn Plugins zusätzliche Kontextinformationen benötigen. **Der PluginContext ist ausdrücklich nicht Bestandteil von Phase 12.**





# Phase 12: Step-by-Step AI Implementation Guide

Dieser Leitfaden sichert nach jedem Schritt einen voll funktionsfähigen Projektzustand.

## Workflow-Vereinbarung (verbindlich, vor Beginn)

**1. Backups über Git statt Ordner-Kopien:**
- Code-Backups erfolgen als **Git-Commit/Tag** pro Schritt (`phase12_step1`, `phase12_step2`, …) – sekundenschnell, versioniert, jederzeit zurückrollbar. Die `.backup_*`-Ordner-Kopien entfallen.
- **`data/` wird NICHT kopiert** (`market_data.duckdb` ist ~1,2 GB und ändert sich nur durch MT5-Sync). Einzige Ausnahme: **einmaliges Backup von `analytics.duckdb` + `app_data.duckdb`** (zusammen ~23 MB) direkt vor Schritt 1 (DB-Migration), da diese migriert werden.
- Pro Schritt werden nur die **tatsächlich geänderten Dateien** gesichert (siehe Schritt-Backup-Listen).

**2. Testauswahl (nur relevante Tests):**
- Für Phase 12 werden **nur** folgende Tests ausgeführt:
  - Regression Grid: `test/check_grid_levels_feature.py`, `test/check_grid_scan_integration.py`
  - Neu (aus der Roadmap): `test/check_plugin_executor.py`, `test/check_grid_parity.py`
- Die übrigen `test/`-Skripte sind Einmal-Validierungen vergangener Fixes (Zeitzonen, Chart-JS-Interna) und werden **nicht** automatisch mit ausgeführt.
- Schritt 7 "alle Test-Skripte ausführen" wird entsprechend auf die obige Auswahl reduziert.

**3. Autonomes Durcharbeiten (keine Bestätigungen):**
- Die AI arbeitet die Schritte **durchgehend und autonom** bis zum nächsten Prompt aus – ohne Rückfragen/Bestätigungen für Standard-Schritte (Code schreiben, Tests ausführen, kleine Korrekturen).
- **Stopp-Punkte (hier wird trotzdem kurz Rücksprache gehalten):**
  1. **Echte Architektur-Entscheidungen** (z. B. Schema-Design, plugin_id-Vergabe)
  2. **Änderungen, die bestehende Logik/Strukturen brechen könnten** (widerspricht Agents.md: "Originalsourcen nicht überschreiben")
  3. **DB-Migrationen**, die bestehende Daten verändern (Schritt 1) – vorher wird das 23-MB-Backup erstellt

## Schritt 1: Datenbank-Erweiterung (Hybrid-Schema & Presets)

### 1.1 Backup-Anforderung

- **DB-Backup (einmalig, vor der Migration):** `analytics.duckdb` + `app_data.duckdb` → `.backup_Phase12_Step1/`. (`market_data.duckdb` wird NICHT kopiert.)
- **Code:** Git-Commit/Tag `phase12_step1` für `db_service.py` + `state_manager.py`.

### 1.2 Anweisung an die AI

    Öffne db_service.py und passe check_and_init_databases() an.

    Führe folgende Statements aus:

Python

con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_id VARCHAR;")
con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS plugin_version VARCHAR;")
con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_data JSON;")

con_app.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS plugin_id VARCHAR;")
con_app.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS version VARCHAR DEFAULT '1.0.0';")
con_app.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS is_active_batch BOOLEAN DEFAULT FALSE;")

### 1.3 Validierung & Test

**Keine UI-Tests (Regel Agents.md §4).** Validierung headless:
   - Migration direkt ausführen: `db_service.check_and_init_databases()` in einer Testdatei unter `test/` aufrufen (kein `main.py`-Start).
   - Danach `DESCRIBE feature_store` / `DESCRIBE indicator_presets` via DuckDB: die neuen Spalten (`feature_id`, `plugin_version`, `feature_data` bzw. `plugin_id`, `version`, `is_active_batch`) sind vorhanden.
   - Datenintegrität: Zeilenzahl und Stichproben in `feature_store`/`signal_results` vor/nach Migration identisch.

## Schritt 2: Neue Plugin-Basisklasse (PluginFeature)

### 2.1 Backup-Anforderung

Git-Commit/Tag `phase12_step2` für `analytics/features/`. `analytics/features/base_feature.py` DARF NICHT geändert oder gelöscht werden!

### 2.2 Anweisung an die AI

    Erstelle das Ordnerverzeichnis analytics/features/plugins/ mit leerer __init__.py.

    Erstelle darin base_plugin.py mit PluginFeature, ParameterSchema, PluginMetadata, ChartRenderPayload (inkl. hit_circles, areas, labels) und FeatureStorePayload.

### 2.3 Validierung & Test

Führe python -c "from analytics.features.plugins.base_plugin import PluginFeature" aus.


## Schritt 3: Ausführungsschicht (PluginLoader, PluginRegistry, PluginExecutor)

###3.1 Backup-Anforderung

Git-Commit/Tag `phase12_step3` für `analytics/features/feature_builder.py`.

### 3.2 Anweisung an die AI

    Erstelle analytics/features/definitions/ mit leerer __init__.py.

    Implementiere in analytics/features/feature_builder.py die Klassen PluginLoader, PluginRegistry und PluginExecutor.

    Stelle sicher, dass PluginLoader rein nach Subklassen von PluginFeature scannt (Dateinamen-unabhängig) und keine automatischen Reloads in Threads durchführt.

### 3.3 Validierung & Test

Erstelle ein Testskript test/check_plugin_executor.py und verifiziere die Instanziierung von PluginExecutor().


## Schritt 4: Paritäts-Plugin & Paritäts-Test

### 4.1 Backup-Anforderung

Git-Commit/Tag `phase12_step4` für `analytics/features/definitions/`.

###4.2 Anweisung an die AI

    Erstelle analytics/features/definitions/grid_liquidity.py mit der Klasse GridLiquidityFeature(PluginFeature).

    Erstelle ein Vergleichs-Testskript test/check_grid_parity.py, das identische OHLCV-Daten durch den alten GridIndicator.calculate() und PluginExecutor().execute("grid_liquidity", df, params) schickt.

### 4.3 Validierung & Test

Führe python test/check_grid_parity.py aus. **Hinweis:** Linien und Circles sind später **eigenständige Services**, die unabhängig voneinander laufen. Circles hängen logisch an den Ergebnissen des Linien-Services, aber **Anzahl und Positionen von Linien und Circles sind NICHT korreliert** – eine Forderung nach gleicher Anzahl ist gegenstandslos. Der Test validiert daher:
   - Das Plugin läuft fehlerfrei über `PluginExecutor` (keine Exceptions, korrekte Payload-Struktur).
   - Linien-Output und Circle-Output werden jeweils für sich konsistent erzeugt (Linien = eigenes Raster-Ergebnis, Circles = eigene Proximity-Auswertung).
   - Die Circle-Ergebnisse beziehen sich korrekt auf die erzeugten Linien-Levels (logische Kopplung), ohne identische Anzahl zu verlangen.
---
## Schritt 5: Anbindung Chart UI, JS-Bridge & Presets

### 5.1 Backup-Anforderung

Git-Commit/Tag `phase12_step5` für `chart/indicators/grid.py` (nur Sicherung – wird NICHT verändert), `chart/chart_win.py`, `state_manager.py` sowie `chart/js/03_chart_rendering.js`.

### 5.2 Anweisung an die AI

    Erweitere state_manager.py um save_indicator_preset mit Unterstützung für plugin_id, version und is_active_batch.

    **NEUER Indikator (`chart/indicators/grid_liquidity.py`):** Erstelle einen NEUEN Chart-Indikator (indicator_id `grid_liquidity`), der intern das `GridLiquidityFeature` (Plugin) über den `PluginExecutor` nutzt und dessen `chart_render_payload` zurückgibt. Registriere ihn ZUSÄTZLICH zum bestehenden `grid`-Indikator in der Indikator-Registry von `chart/chart_win.py`. Seine Basis-Parameter werden in Phase 12 über den bestehenden generischen `indicator_dialog.py` (Interim) bedient.

    **Der bestehende `chart/indicators/grid.py` bleibt UNVERÄNDERT** (hardcoded, wie bisher) – er wird weder modifiziert noch entfernt und bleibt als Alt-Implementierung voll funktionsfähig (Parallelbetrieb).

    **Das vollständig neue Property-Fenster des neuen Indikators (Service-Felder + Action-Buttons) ist NICHT Teil von Phase 12** – es ist eine eigenständige Entwicklung, die NACH Phase 12 startet (siehe Entscheidung 4).

    Verifiziere in chart/js/03_chart_rendering.js und 04_live_updates.js, dass hit_circles verarbeitet wird.

### 5.3 Validierung & Test

**Keine UI-Tests (Regel Agents.md §4).** Die Validierung erfolgt stattdessen headless:
   - Direkter Aufruf des neuen Indikators `GridLiquidityIndicator.calculate(df, params)` auf synthetischen OHLCV-Daten → prüfe korrekte `chart_render_payload`-Struktur (`lines`, `hit_circles`).
   - Registry-Check: `chart_win.py` enthält ZUSÄTZLICH `grid_liquidity` neben `grid` (Parallelbetrieb).
   - `state_manager.save_indicator_preset(...)` mit `plugin_id`/`version`/`is_active_batch` → Roundtrip lesen und validieren.
   - JS-Bridge: Inspektion in `chart/js/03_chart_rendering.js`/`04_live_updates.js`, dass `hit_circles` von `renderGridCircles()` verarbeitet wird (Code-Inspektion, kein UI-Start).
   - Der bestehende `chart/indicators/grid.py` bleibt unverändert (Diff-Check via Git). Das neue Property-Fenster wird in dieser Phase NICHT gebaut.
---

## Schritt 6: Anbindung Batch-Services über PluginExecutor

### 6.1 Backup-Anforderung

Git-Commit/Tag `phase12_step6` für `analytics/background_workers/historical_scanner.py` und `live_analyzer.py`.

### 6.2 Anweisung an die AI

    **Parallelbetrieb (verbindlich):** Der bestehende Alt-Pfad (Standard-Scan `ema_atr_set_v1` / `alternating_arrow_v1` über harte Verzweigungen) bleibt UNVERÄNDERT voll funktionsfähig. Der Plugin-Pfad wird NEBEN dem Alt-Pfad ergänzt und ausschließlich über ein `is_active_batch = True` markiertes Preset (per `plugin_id` aus `indicator_presets`) aktiviert.

    Passe HistoricalScanner so an, dass er für den Plugin-Modus (statt harter Verzweigungen) den PluginExecutor nutzt und die aktiven Presets über plugin_id aus indicator_presets abfragt. Der Alt-Scan-Zweig bleibt dabei unberührt.

    Schreibe den feature_store_payload im feature_store ab (nur im Plugin-Modus; der Alt-Modus schreibt weiterhin seine nativen Spalten).

    Binde den LiveAnalyzer an dieselbe PluginExecutor-Instanz an (nur für Plugins mit `live_op = True`; bestehende Live-Signale bleiben unverändert).

### 6.3 Validierung & Test

**Keine UI-Tests (Regel Agents.md §4).** Die Validierung erfolgt headless:
   - `HistoricalScanner` direkt instanziieren (z. B. `HistoricalScanner("SILVER", grid_scan=True)` bzw. Plugin-Modus) und `run()`/Thread in einer Testdatei unter `test/` ausführen (ohne Service-Fenster).
   - Danach DuckDB-Abfrage auf `feature_store`: Einträge mit `feature_id = 'grid_liquidity'` und gefülltem `feature_data` vorhanden.
   - Alt-Modus-Regression: Standard-Scan (`grid_scan=False`) weiterhin lauffähig und schreibt weiterhin `ema_atr_set_v1`-Signale in `signal_results` (Parallelbetrieb intakt).
   - Der `LiveAnalyzer` wird per Code-Inspektion auf dieselbe `PluginExecutor`-Instanz geprüft (kein Live-UI-Test).

## Schritt 7: Systemweiter Regressionstest

### 7.1 Backup-Anforderung

Git-Commit/Tag `phase12_final` für das gesamte Projekt (Code-Bestand nach Phase 12).

### 7.2 Anweisung an die AI

    Prüfe alle Fenster (Hauptfenster, Chart-Fenster, Service-Fenster, Statistik-Fenster, Optionen) auf fehlerfreie Interaktion.

    Führe NUR die Phase-12-relevanten Test-Skripte aus (siehe Workflow-Vereinbarung Punkt 2):
    - test/check_grid_levels_feature.py
    - test/check_grid_scan_integration.py
    - test/check_plugin_executor.py (neu)
    - test/check_grid_parity.py (neu)

### 7.3 Validierung & Test

**Keine UI-Tests (Regel Agents.md §4).** Abschluss-Validierung headless:
   - Alle 4 Phase-12-Tests laufen grün (siehe 7.2).
   - Import-/Syntax-Checks (`py_compile`) für alle geänderten Dateien.
   - Code-Inspektion der Fenster-Kopplungen (Hauptfenster → Chart/Service/Statistik): keine neuen Abhängigkeiten gebrochen (Alt-Indikator `grid` und neuer `grid_liquidity` beide registriert).
   - Datenkonsistenz: `feature_store` enthält Plugin-Einträge (`feature_id='grid_liquidity'`), `signal_results` unverändert zusätzlich Alt-Signale.