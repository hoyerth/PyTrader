# Phase 12: Dynamische Feature- & Signal-Architektur (AI-Plugin-System)

## 1. Konzept & Zielsetzung

Um neue Trading-Logiken, Akkumulatoren und Signal-Definitionen extrem flexibel ohne Änderungen am Rumpfcode oder Datenbank-Schema zu integrieren, führen wir eine **Plugin-basierte Architektur** ein. 

Sowohl visuelle Chart-Indikatoren als auch abstrakte Batch-Services (Scanner/Analyzer) greifen auf **exakt dieselben externen Definitions-Dateien** im Ordner `../analytics/features/definitions` zurück.

### Kernprinzipien:
1. **Single Source of Truth:** Die mathematische/logische Berechnung existiert genau einmal als Python-Datei im Verzeichnis `../analytics/features/definitions`.
2. **Einfaches Einklinken (Drop-in AI Plugins):** Eine von einer AI generierte Python-Datei muss lediglich in das Definitions-Verzeichnis gelegt werden. Das System erkennt und registriert sie automatisch (Auto-Discovery).
3. **Schaltzentrale UI & Batch:** 
   - **Im Chart-Fenster:** Der UI-Indikator lädt das Plugin, rendert Vorschau-Marker/Linien und erlaubt das visuelle Tunen der Parameter.
   - **Im Batch-Service:** Der Scanner lädt dasselbe Plugin, liest gespeicherte Parameter-Presets aus DuckDB und führt historische Massen-Scans durch.
4. **Schema-Invariante Datenbank:** Keine DDL-Anpassungen (`ALTER TABLE`) bei neuen Indikatoren. Alle Parameter, Feature-Vektoren und Metadaten werden in generischen `JSON`-Spalten in DuckDB gespeichert.

---

## 2. Datenbank-Architektur (Schema-Invariant)

Die Datenbanken `analytics.duckdb` und `app_data.duckdb` nutzen hochflexible Strukturen, die beliebige neue Signale und Parameter aufnehmen können.

```sql
-- 1. ANALYTICS.DUCKDB: Generischer Feature Store
CREATE TABLE IF NOT EXISTS feature_store (
    symbol          VARCHAR NOT NULL,
    timeframe       VARCHAR NOT NULL,
    bar_time        TIMESTAMPTZ NOT NULL,
    feature_id      VARCHAR NOT NULL,      -- z.B. 'grid_liquidity_v1'
    feature_data    JSON NOT NULL,          -- Beliebige Payloads: {"liq_lines": [...], "atr": 1.25}
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timeframe, bar_time, feature_id)
);

-- 2. ANALYTICS.DUCKDB: Signal-Ergebnisse
CREATE TABLE IF NOT EXISTS signal_results (
    event_id        VARCHAR PRIMARY KEY,
    symbol          VARCHAR NOT NULL,
    timeframe       VARCHAR NOT NULL,
    bar_time        TIMESTAMPTZ NOT NULL,
    source_id       VARCHAR NOT NULL,      -- ID des Signal/Feature Plugins
    confidence      DOUBLE,
    context_type    VARCHAR NOT NULL,      -- 'BUY', 'SELL', 'NEUTRAL', 'INFO'
    metadata_payload JSON,                  -- Zusätzliche Details zur Signal-Auslösung
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. APP_DATA.DUCKDB: Parameter-Presets & Service-Konfigurationen
CREATE TABLE IF NOT EXISTS plugin_presets (
    plugin_id       VARCHAR NOT NULL,      -- ID des Plugins
    preset_name     VARCHAR NOT NULL,      -- z.B. 'Default', 'Conservative_Silver'
    params          JSON NOT NULL,          -- Parameter-Dict als JSON
    is_active_batch BOOLEAN DEFAULT FALSE, -- Flag ob das Preset im Batch-Service genutzt wird
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (plugin_id, preset_name)
);

```

---

## 3. Plugin-Schnittstelle (`BaseFeatureDefinition`)

Jedes Plugin erbt von `BaseFeatureDefinition` und definiert Eingabeparameter, Berechnungslogik und Visualisierungs-Metadaten.

### `../analytics/features/base_feature.py`

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple
import pandas as pd

class BaseFeatureDefinition(ABC):
    """Basisklasse für alle AI-generierten Feature- & Signal-Plugins."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Eindeutige ID des Plugins (z. B. 'grid_liquidity_v1')."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Lesbarer Name für die UI."""
        pass

    @property
    @abstractmethod
    def default_params(self) -> Dict[str, Any]:
        """Standard-Parameter mit Datentypen und UI-Hinweisen."""
        pass

    @abstractmethod
    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Hauptberechnungslogik.
        
        Args:
            df: DataFrame mit Spalten ['time', 'open', 'high', 'low', 'close', 'tick_volume']
            params: Überschriebene Parameter-Werte

        Returns:
            Dict mit zwei Schlüsseln:
            - 'feature_store_payload': Daten, die in DuckDB als JSON landen
            - 'chart_render_payload': Daten für Visualisierung (Lines, Circles, Markers)
        """
        pass

```

---

## 4. Beispiel-Plugin: Liquidity Lines & Proximity

### `analytics/features/definitions/grid_liquidity_v1.py`

```python
from typing import Dict, Any, List
import pandas as pd
import numpy as np
from analytics.features.base_feature import BaseFeatureDefinition

class GridLiquidityFeature(BaseFeatureDefinition):

    @property
    def plugin_id(self) -> str:
        return "grid_liquidity_v1"

    @property
    def display_name(self) -> str:
        return "Grid Liquidity Lines & Proximity"

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "grid_step": 0.50,
            "proximity_threshold": 0.05,
            "line_color": "#2196F3",
            "circle_color": "#FFEB3B"
        }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
        if df.empty:
            return {"feature_store_payload": {}, "chart_render_payload": {}}

        step = params.get("grid_step", 0.50)
        threshold = params.get("proximity_threshold", 0.05)
        line_color = params.get("line_color", "#2196F3")
        circle_color = params.get("circle_color", "#FFEB3B")

        # 1. Grid-Linien berechnen
        min_price = df["low"].min()
        max_price = df["high"].max()
        
        start_level = np.floor(min_price / step) * step
        end_level = np.ceil(max_price / step) * step
        levels = np.arange(start_level, end_level + step, step)

        lines_payload = [
            {"price": float(lvl), "color": line_color, "width": 1}
            for lvl in levels
        ]

        # 2. Proximity-Events erkennen (Treffer nahe an Grid-Linien)
        hit_circles = []
        feature_rows = []

        for idx, row in df.iterrows():
            close_price = row["close"]
            bar_time = int(row["time"])

            # Nächstgelegenes Level finden
            nearest_lvl = round(close_price / step) * step
            dist = abs(close_price - nearest_lvl)

            is_hit = dist <= threshold
            if is_hit:
                hit_circles.append({
                    "time": bar_time,
                    "price": float(close_price),
                    "color": circle_color,
                    "priority": 10
                })

            feature_rows.append({
                "bar_time": bar_time,
                "nearest_level": float(nearest_lvl),
                "distance": float(dist),
                "is_proximity_hit": bool(is_hit)
            })

        return {
            "feature_store_payload": {
                "records": feature_rows
            },
            "chart_render_payload": {
                "lines": lines_payload,
                "hit_circles": hit_circles
            }
        }

```

---

## 5. Auto-Discovery & Registry (`PluginRegistry`)

Damit eingeklinkte Dateien automatisch erkannt werden, scannt die `PluginRegistry` das Verzeichnis `../analytics/features/definitions`.

### `../analytics/features/feature_builder.py`

```python
import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Dict, Type
from analytics.features.base_feature import BaseFeatureDefinition

class PluginRegistry:
    _instance = None
    _plugins: Dict[str, Type[BaseFeatureDefinition]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PluginRegistry, cls).__new__(cls)
            cls._instance._discover_plugins()
        return cls._instance

    def _discover_plugins(self):
        definitions_dir = Path(__file__).parent / "definitions"
        if not definitions_dir.exists():
            return

        for _, module_name, is_pkg in pkgutil.iter_modules([str(definitions_dir)]):
            if is_pkg:
                continue
            full_module_name = f"analytics.features.definitions.{module_name}"
            module = importlib.import_module(full_module_name)

            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BaseFeatureDefinition) and obj is not BaseFeatureDefinition:
                    plugin_inst = obj()
                    self._plugins[plugin_inst.plugin_id] = obj
                    print(f"🔌 [PluginRegistry] Geladenes Plugin: {plugin_inst.plugin_id} ({plugin_inst.display_name})")

    def get_plugin(self, plugin_id: str) -> BaseFeatureDefinition:
        cls = self._plugins.get(plugin_id)
        if not cls:
            raise ValueError(f"Plugin '{plugin_id}' nicht gefunden.")
        return cls()

    def list_plugins(self) -> Dict[str, str]:
        return {pid: cls().display_name for pid, cls in self._plugins.items()}

```

---

## 6. Integration in Chart UI & Service Batch-Prozess

### A) Im Chart-UI Indikator (`PyTraderChartWindow`)

1. Der Benutzer öffnet die Eigenschaften des Indikators am Chart.
2. Der Dialog rendert dynamisch alle Eingabefelder basierend auf `plugin.default_params`.
3. Bei Parameter-Änderung berechnet das Plugin in-memory das `chart_render_payload` und schickt es per JS-Bridge an den Chart (`renderGridLines`, `renderGridCircles`).
4. Ein Klick auf **"Als Service-Preset speichern"** legt das Parameter-Dict in der Tabelle `plugin_presets` ab.

### B) Im Batch-Service (`HistoricalScanner`)

1. Der Scanner liest das aktive Preset aus `plugin_presets` für die gewünschte `plugin_id`.
2. Er lädt dieselbe Klasse aus der `PluginRegistry`.
3. Er führt die `calculate()` Methode über die geforderten Symbole/Timeframes aus.
4. Er schreibt das `feature_store_payload` per `INSERT OR REPLACE` in die Tabelle `feature_store` von `analytics.duckdb`.

---

## 7. Anweisungen zur Umsetzung (Phase 12 Workflow)

1. **Modul-Struktur anlegen:**
* Erstelle das Verzeichnis `../analytics/features/definitions`.
* Erstelle `../analytics/features/base_feature.py` mit der abstrakten Klasse.
* Erstelle `../analytics/features/feature_builder.py` mit der `PluginRegistry`.


2. **DuckDB Schemas absichern:**
* Erweitere `../db_service.py` (`check_and_init_databases()`) um die Tabellen `feature_store`, `signal_results` und `plugin_presets` mit den generischen JSON-Spalten.


3. **Chart & Service Anbindung:**
* Adaptiere `GridIndicator` in `../chart/indicators/grid.py`, sodass er die Berechnungslogik aus dem Plugin `grid_liquidity_v1.py` bezieht.
* Erweitere den `HistoricalScanner` um die Ausführung registrierter Plugins aus der `PluginRegistry`.


4. **Testing:**
* Füge ein Testskript `test/check_plugin_registry.py` hinzu, das verifiziert, ob neue Dateien im Verzeichnis `../analytics/features/definitions` ohne System-Neustart dynamisch erkannt und ausgeführt werden.
"""



doc_path = os.path.join(doc_dir, "Phase12_Feature_Signal_Architecture.md")
with open(doc_path, "w", encoding="utf-8") as f:
f.write(md_content)

print(f"File generated successfully: {doc_path}")

```

```text?code_stdout&code_event_index=1
Traceback (most recent call last):
  File "<xbox-string>", line 79
    md_content = """# Phase 12: Dynamische Feature- & Signal-Architektur (AI-Plugin-System)

## 1. Konzept & Zielsetzung

Um neue Trading-Logiken, Akkumulatoren und Signal-Definitionen extrem flexibel ohne Änderungen am Rumpfcode oder Datenbank-Schema zu integrieren, führen wir eine **Plugin-basierte Architektur** ein. 

Sowohl visuelle Chart-Indikatoren als auch abstrakte Batch-Services (Scanner/Analyzer) greifen auf **exakt dieselben externen Definitions-Dateien** im Ordner `analytics/features/definitions/` zurück.

### Kernprinzipien:
1. **Single Source of Truth:** Die mathematische/logische Berechnung existiert genau einmal als Python-Datei im Verzeichnis `analytics/features/definitions/`.
2. **Einfaches Einklinken (Drop-in AI Plugins):** Eine von einer AI generierte Python-Datei muss lediglich in das Definitions-Verzeichnis gelegt werden. Das System erkennt und registriert sie automatisch (Auto-Discovery).
3. **Schaltzentrale UI & Batch:** 
   - **Im Chart-Fenster:** Der UI-Indikator lädt das Plugin, rendert Vorschau-Marker/Linien und erlaubt das visuelle Tunen der Parameter.
   - **Im Batch-Service:** Der Scanner lädt dasselbe Plugin, liest gespeicherte Parameter-Presets aus DuckDB und führt historische Massen-Scans durch.
4. **Schema-Invariante Datenbank:** Keine DDL-Anpassungen (`ALTER TABLE`) bei neuen Indikatoren. Alle Parameter, Feature-Vektoren und Metadaten werden in generischen `JSON`-Spalten in DuckDB gespeichert.

---

## 2. Datenbank-Architektur (Schema-Invariant)

Die Datenbanken `analytics.duckdb` und `app_data.duckdb` nutzen hochflexible Strukturen, die beliebige neue Signale und Parameter aufnehmen können.

```sql
-- 1. ANALYTICS.DUCKDB: Generischer Feature Store
CREATE TABLE IF NOT EXISTS feature_store (
    symbol          VARCHAR NOT NULL,
    timeframe       VARCHAR NOT NULL,
    bar_time        TIMESTAMPTZ NOT NULL,
    feature_id      VARCHAR NOT NULL,      -- z.B. 'grid_liquidity_v1'
    feature_data    JSON NOT NULL,          -- Beliebige Payloads: {"liq_lines": [...], "atr": 1.25}
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timeframe, bar_time, feature_id)
);

-- 2. ANALYTICS.DUCKDB: Signal-Ergebnisse
CREATE TABLE IF NOT EXISTS signal_results (
    event_id        VARCHAR PRIMARY KEY,
    symbol          VARCHAR NOT NULL,
    timeframe       VARCHAR NOT NULL,
    bar_time        TIMESTAMPTZ NOT NULL,
    source_id       VARCHAR NOT NULL,      -- ID des Signal/Feature Plugins
    confidence      DOUBLE,
    context_type    VARCHAR NOT NULL,      -- 'BUY', 'SELL', 'NEUTRAL', 'INFO'
    metadata_payload JSON,                  -- Zusätzliche Details zur Signal-Auslösung
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. APP_DATA.DUCKDB: Parameter-Presets & Service-Konfigurationen
CREATE TABLE IF NOT EXISTS plugin_presets (
    plugin_id       VARCHAR NOT NULL,      -- ID des Plugins
    preset_name     VARCHAR NOT NULL,      -- z.B. 'Default', 'Conservative_Silver'
    params          JSON NOT NULL,          -- Parameter-Dict als JSON
    is_active_batch BOOLEAN DEFAULT FALSE, -- Flag ob das Preset im Batch-Service genutzt wird
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (plugin_id, preset_name)
);

```

---

## 3. Plugin-Schnittstelle (`BaseFeatureDefinition`)

Jedes Plugin erbt von `BaseFeatureDefinition` und definiert Eingabeparameter, Berechnungslogik und Visualisierungs-Metadaten.

### `../analytics/features/base_feature.py`

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple
import pandas as pd

class BaseFeatureDefinition(ABC):
    """Basisklasse für alle AI-generierten Feature- & Signal-Plugins."""
           ^^^^^^^^^^^
SyntaxError: invalid syntax


```

```python
import os

# Write Phase 12 documentation safely without inner string formatting conflicts
doc_dir = ""
os.makedirs(doc_dir, exist_ok=True)

md_lines = [
   "# Phase 12: Dynamische Feature- & Signal-Architektur (AI-Plugin-System)",
   "",
   "## 1. Konzept & Zielsetzung",
   "",
   "Um neue Trading-Logiken, Akkumulatoren und Signal-Definitionen extrem flexibel ohne Änderungen am Rumpfcode oder Datenbank-Schema zu integrieren, führen wir eine **Plugin-basierte Architektur** ein.",
   "",
   "Sowohl visuelle Chart-Indikatoren als auch abstrakte Batch-Services (Scanner/Analyzer) greifen auf **exakt dieselben externen Definitions-Dateien** im Ordner `analytics/features/definitions/` zurück.",
   "",
   "### Kernprinzipien:",
   "1. **Single Source of Truth:** Die mathematische/logische Berechnung existiert genau einmal als Python-Datei im Verzeichnis `analytics/features/definitions/`.",
   "2. **Einfaches Einklinken (Drop-in AI Plugins):** Eine von einer AI generierte Python-Datei muss lediglich in das Definitions-Verzeichnis gelegt werden. Das System erkennt und registriert sie automatisch (Auto-Discovery).",
   "3. **Schaltzentrale UI & Batch:**",
   "   - **Im Chart-Fenster:** Der UI-Indikator lädt das Plugin, rendert Vorschau-Marker/Linien und erlaubt das visuelle Tunen der Parameter.",
   "   - **Im Batch-Service:** Der Scanner lädt dasselbe Plugin, liest gespeicherte Parameter-Presets aus DuckDB und führt historische Massen-Scans durch.",
   "4. **Schema-Invariante Datenbank:** Keine DDL-Anpassungen (`ALTER TABLE`) bei neuen Indikatoren. Alle Parameter, Feature-Vektoren und Metadaten werden in generischen `JSON`-Spalten in DuckDB gespeichert.",
   "",
   "---",
   "",
   "## 2. Datenbank-Architektur (Schema-Invariant)",
   "",
   "Die Datenbanken `analytics.duckdb` und `app_data.duckdb` nutzen hochflexible Strukturen, die beliebige neue Signale und Parameter aufnehmen können.",
   "",
   "```sql",
   "-- 1. ANALYTICS.DUCKDB: Generischer Feature Store",
   "CREATE TABLE IF NOT EXISTS feature_store (",
   "    symbol          VARCHAR NOT NULL,",
   "    timeframe       VARCHAR NOT NULL,",
   "    bar_time        TIMESTAMPTZ NOT NULL,",
   "    feature_id      VARCHAR NOT NULL,      -- z.B. 'grid_liquidity_v1'",
   "    feature_data    JSON NOT NULL,          -- Beliebige Payloads: {\"liq_lines\": [...], \"atr\": 1.25}",
   "    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,",
   "    PRIMARY KEY (symbol, timeframe, bar_time, feature_id)",
   ");",
   "",
   "-- 2. ANALYTICS.DUCKDB: Signal-Ergebnisse",
   "CREATE TABLE IF NOT EXISTS signal_results (",
   "    event_id        VARCHAR PRIMARY KEY,",
   "    symbol          VARCHAR NOT NULL,",
   "    timeframe       VARCHAR NOT NULL,",
   "    bar_time        TIMESTAMPTZ NOT NULL,",
   "    source_id       VARCHAR NOT NULL,      -- ID des Signal/Feature Plugins",
   "    confidence      DOUBLE,",
   "    context_type    VARCHAR NOT NULL,      -- 'BUY', 'SELL', 'NEUTRAL', 'INFO'",
   "    metadata_payload JSON,                  -- Zusätzliche Details zur Signal-Auslösung",
   "    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
   ");",
   "",
   "-- 3. APP_DATA.DUCKDB: Parameter-Presets & Service-Konfigurationen",
   "CREATE TABLE IF NOT EXISTS plugin_presets (",
   "    plugin_id       VARCHAR NOT NULL,      -- ID des Plugins",
   "    preset_name     VARCHAR NOT NULL,      -- z.B. 'Default', 'Conservative_Silver'",
   "    params          JSON NOT NULL,          -- Parameter-Dict als JSON",
   "    is_active_batch BOOLEAN DEFAULT FALSE, -- Flag ob das Preset im Batch-Service genutzt wird",
   "    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,",
   "    PRIMARY KEY (plugin_id, preset_name)",
   ");",
   "```",
   "",
   "---",
   "",
   "## 3. Plugin-Schnittstelle (`BaseFeatureDefinition`)",
   "",
   "Jedes Plugin erbt von `BaseFeatureDefinition` und definiert Eingabeparameter, Berechnungslogik und Visualisierungs-Metadaten.",
   "",
   "### `analytics/features/base_feature.py`",
   "",
   "```python",
   "from abc import ABC, abstractmethod",
   "from typing import Dict, Any, List, Tuple",
   "import pandas as pd",
   "",
   "class BaseFeatureDefinition(ABC):",
   '    """Basisklasse fuer alle AI-generierten Feature- & Signal-Plugins."""',
   "",
   "    @property",
   "    @abstractmethod",
   "    def plugin_id(self) -> str:",
   '        """Eindeutige ID des Plugins (z. B. \'grid_liquidity_v1\')."""',
   "        pass",
   "",
   "    @property",
   "    @abstractmethod",
   "    def display_name(self) -> str:",
   '        """Lesbarer Name fuer die UI."""',
   "        pass",
   "",
   "    @property",
   "    @abstractmethod",
   "    def default_params(self) -> Dict[str, Any]:",
   '        """Standard-Parameter mit Datentypen und UI-Hinweisen."""',
   "        pass",
   "",
   "    @abstractmethod",
   "    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:",
   '        """',
   "        Hauptberechnungslogik.",
   "        ",
   "        Args:",
   "            df: DataFrame mit Spalten ['time', 'open', 'high', 'low', 'close', 'tick_volume']",
   "            params: Ueberschriebene Parameter-Werte",
   "",
   "        Returns:",
   "            Dict mit zwei Schluesseln:",
   "            - 'feature_store_payload': Daten, die in DuckDB als JSON landen",
   "            - 'chart_render_payload': Daten fuer Visualisierung (Lines, Circles, Markers)",
   '        """',
   "        pass",
   "```",
   "",
   "---",
   "",
   "## 4. Beispiel-Plugin: Liquidity Lines & Proximity",
   "",
   "### `analytics/features/definitions/grid_liquidity_v1.py`",
   "",
   "```python",
   "from typing import Dict, Any, List",
   "import pandas as pd",
   "import numpy as np",
   "from analytics.features.base_feature import BaseFeatureDefinition",
   "",
   "class GridLiquidityFeature(BaseFeatureDefinition):",
   "",
   "    @property",
   "    def plugin_id(self) -> str:",
   '        return "grid_liquidity_v1"',
   "",
   "    @property",
   "    def display_name(self) -> str:",
   '        return "Grid Liquidity Lines & Proximity"',
   "",
   "    @property",
   "    def default_params(self) -> Dict[str, Any]:",
   "        return {",
   '            "grid_step": 0.50,',
   '            "proximity_threshold": 0.05,',
   '            "line_color": "#2196F3",',
   '            "circle_color": "#FFEB3B"',
   "        }",
   "",
   "    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:",
   "        if df.empty:",
   '            return {"feature_store_payload": {}, "chart_render_payload": {}}',
   "",
   '        step = params.get("grid_step", 0.50)',
   '        threshold = params.get("proximity_threshold", 0.05)',
   '        line_color = params.get("line_color", "#2196F3")',
   '        circle_color = params.get("circle_color", "#FFEB3B")',
   "",
   "        # 1. Grid-Linien berechnen",
   '        min_price = df["low"].min()',
   '        max_price = df["high"].max()',
   "        ",
   "        start_level = np.floor(min_price / step) * step",
   "        end_level = np.ceil(max_price / step) * step",
   "        levels = np.arange(start_level, end_level + step, step)",
   "",
   "        lines_payload = [",
   '            {"price": float(lvl), "color": line_color, "width": 1}',
   "            for lvl in levels",
   "        ]",
   "",
   "        # 2. Proximity-Events erkennen (Treffer nahe an Grid-Linien)",
   "        hit_circles = []",
   "        feature_rows = []",
   "",
   "        for idx, row in df.iterrows():",
   '            close_price = row["close"]',
   '            bar_time = int(row["time"])',
   "",
   "            nearest_lvl = round(close_price / step) * step",
   "            dist = abs(close_price - nearest_lvl)",
   "",
   "            is_hit = dist <= threshold",
   "            if is_hit:",
   "                hit_circles.append({",
   '                    "time": bar_time,',
   '                    "price": float(close_price),',
   '                    "color": circle_color,',
   '                    "priority": 10',
   "                })",
   "",
   "            feature_rows.append({",
   '                "bar_time": bar_time,',
   '                "nearest_level": float(nearest_lvl),',
   '                "distance": float(dist),',
   '                "is_proximity_hit": bool(is_hit)',
   "            })",
   "",
   "        return {",
   '            "feature_store_payload": {',
   '                "records": feature_rows',
   "            },",
   '            "chart_render_payload": {',
   '                "lines": lines_payload,',
   '                "hit_circles": hit_circles',
   "            }",
   "        }",
   "```",
   "",
   "---",
   "",
   "## 5. Auto-Discovery & Registry (`PluginRegistry`)",
   "",
   "Damit eingeklinkte Dateien automatisch erkannt werden, scannt die `PluginRegistry` das Verzeichnis `analytics/features/definitions/`.",
   "",
   "### `analytics/features/feature_builder.py`",
   "",
   "```python",
   "import importlib",
   "import inspect",
   "import pkgutil",
   "from pathlib import Path",
   "from typing import Dict, Type",
   "from analytics.features.base_feature import BaseFeatureDefinition",
   "",
   "class PluginRegistry:",
   "    _instance = None",
   "    _plugins: Dict[str, Type[BaseFeatureDefinition]] = {}",
   "",
   "    def __new__(cls):",
   "        if cls._instance is None:",
   "            cls._instance = super(PluginRegistry, cls).__new__(cls)",
   "            cls._instance._discover_plugins()",
   "        return cls._instance",
   "",
   "    def _discover_plugins(self):",
   '        definitions_dir = Path(__file__).parent / "definitions"',
   "        if not definitions_dir.exists():",
   "            return",
   "",
   "        for _, module_name, is_pkg in pkgutil.iter_modules([str(definitions_dir)]):",
   "            if is_pkg:",
   "                continue",
   '            full_module_name = f"analytics.features.definitions.{module_name}"',
   "            module = importlib.import_module(full_module_name)",
   "",
   "            for name, obj in inspect.getmembers(module, inspect.isclass):",
   "                if issubclass(obj, BaseFeatureDefinition) and obj is not BaseFeatureDefinition:",
   "                    plugin_inst = obj()",
   "                    self._plugins[plugin_inst.plugin_id] = obj",
   '                    print(f"🔌 [PluginRegistry] Geladenes Plugin: {plugin_inst.plugin_id} ({plugin_inst.display_name})")',
   "",
   "    def get_plugin(self, plugin_id: str) -> BaseFeatureDefinition:",
   "        cls = self._plugins.get(plugin_id)",
   "        if not cls:",
   '            raise ValueError(f"Plugin \'{plugin_id}\' nicht gefunden.")',
   "        return cls()",
   "",
   "    def list_plugins(self) -> Dict[str, str]:",
   "        return {pid: cls().display_name for pid, cls in self._plugins.items()}",
   "```",
   "",
   "---",
   "",
   "## 6. Integration in Chart UI & Service Batch-Prozess",
   "",
   "### A) Im Chart-UI Indikator (`PyTraderChartWindow`)",
   "1. Der Benutzer öffnet die Eigenschaften des Indikators am Chart.",
   "2. Der Dialog rendert dynamisch alle Eingabefelder basierend auf `plugin.default_params`.",
   "3. Bei Parameter-Änderung berechnet das Plugin in-memory das `chart_render_payload` und schickt es per JS-Bridge an den Chart (`renderGridLines`, `renderGridCircles`).",
   "4. Ein Klick auf **\"Als Service-Preset speichern\"** legt das Parameter-Dict in der Tabelle `plugin_presets` ab.",
   "",
   "### B) Im Batch-Service (`HistoricalScanner`)",
   "1. Der Scanner liest das aktive Preset aus `plugin_presets` für die gewünschte `plugin_id`.",
   "2. Er lädt dieselbe Klasse aus der `PluginRegistry`.",
   "3. Er führt die `calculate()` Methode über die geforderten Symbole/Timeframes aus.",
   "4. Er schreibt das `feature_store_payload` per `INSERT OR REPLACE` in die Tabelle `feature_store` von `analytics.duckdb`.",
   "",
   "---",
   "",
   "## 7. Anweisungen zur Umsetzung (Phase 12 Workflow)",
   "",
   "1. **Modul-Struktur anlegen:**",
   "   - Erstelle das Verzeichnis `analytics/features/definitions/`.",
   "   - Erstelle `analytics/features/base_feature.py` mit der abstrakten Klasse.",
   "   - Erstelle `analytics/features/feature_builder.py` mit der `PluginRegistry`.",
   "",
   "2. **DuckDB Schemas absichern:**",
   "   - Erweitere `db_service.py` (`check_and_init_databases()`) um die Tabellen `feature_store`, `signal_results` und `plugin_presets` mit den generischen JSON-Spalten.",
   "",
   "3. **Chart & Service Anbindung:**",
   "   - Adaptiere `GridIndicator` in `chart/indicators/grid.py`, sodass er die Berechnungslogik aus dem Plugin `grid_liquidity_v1.py` bezieht.",
   "   - Erweitere den `HistoricalScanner` um die Ausführung registrierter Plugins aus der `PluginRegistry`.",
   "",
   "4. **Testing:**",
   "   - Füge ein Testskript `test/check_plugin_registry.py` hinzu, das verifiziert, ob neue Dateien im Verzeichnis `analytics/features/definitions/` ohne System-Neustart dynamisch erkannt und ausgeführt werden.",
]

doc_path = os.path.join(doc_dir, "Phase12_Feature_Signal_Architecture.md")
with open(doc_path, "w", encoding="utf-8") as f:
   f.write("\n".join(md_lines))

print(f"File generated successfully: {doc_path}")


```

```text
File generated successfully: docs/Phase12_Feature_Signal_Architecture.md


```

Das umfassende Architektur-Konzept und die Umsetzungsanweisungen für **Phase 12: Dynamische Feature- & Signal-Architektur (AI-Plugin-System)** wurden als Markdown-Dokument generiert.

Die Dokumentation liegt unter `docs/Phase12_Feature_Signal_Architecture.md`:


---

### Zusammenfassung der Architektur

#### 1. Entkoppelte AI-Plugin-Dateien (`analytics/features/definitions/`)

* Jedes Signal/Feature wird von einer AI als eigenständige Datei (z. B. `grid_liquidity_v1.py`) im Ordner `analytics/features/definitions/` abgelegt.
* Jede Datei erbt von der abstrakten Schnittstelle `BaseFeatureDefinition`.
* **Einklink-Mechanismus:** Über eine automatische Modul-Erkennung (`PluginRegistry` mit `pkgutil` / `importlib`) liest das System alle vorhandenen Klassen dynamisch ein – ohne dass der Rumpfcode angepasst oder Klassen manuell importiert werden müssen.

#### 2. Einheitlicher Ausführungs-Output (`calculate()`)

Die Funktion `calculate()` liefert ein standardisiertes Dictionary mit zwei Entitäten zurück:

* `chart_render_payload`: Zeichnungs-Objekte (`lines`, `hit_circles`, `markers`) für die direkte Echtzeit-Vorschau im Chart.
* `feature_store_payload`: Strukturierte Feature-Datensätze, die direkt im Feature-Store gespeichert werden.

#### 3. Schema-Invariante Datenbank-Ebene (`DuckDB`)

Damit neue Indikatoren und Signale mit beliebigen Parametern und Variablen gespeichert werden können, ohne `ALTER TABLE`-Befehle auszuführen, arbeitet die DB-Schicht vollständig generisch mit `JSON`-Spalten:

* **`analytics.duckdb` -> `feature_store**`: speichert bar-weise die berechneten Indikator-Ergebnisse im `feature_data JSON`-Feld.
* **`analytics.duckdb` -> `signal_results**`: speichert ausgelöste Signale/Events im `metadata_payload JSON`-Feld.
* **`app_data.duckdb` -> `plugin_presets**`: speichert die am Chart abgestimmten Parameter-Sets per `plugin_id` & `preset_name` im `params JSON`-Feld.

#### 4. Zusammenspiel Chart UI & Batch Service

1. **At Chart UI (`PyTraderChartWindow` & `IndicatorSettingsDialog`)**:
* Die UI liest das Plugin per `plugin_id` aus der `PluginRegistry`.
* Der Einstellungsdialog baut automatisch die Eingabefelder basierend auf `default_params` auf.
* Der User tuned die Parameter visuell am Chart; mit einem Klick auf *„Als Service-Preset speichern“* wird das Parameter-Dict in DuckDB (`plugin_presets`) abgelegt.


2. **At Batch Service (`HistoricalScanner` / `LiveAnalyzer`)**:
* Der Scanner lädt das aktive Preset aus DuckDB und instantiiert exakt dasselbe Plugin aus `analytics/features/definitions/`.
* Er führt den historischen Massen-Scan oder die Kerzen-Auswertung aus und schreibt die Ergebnisse direkt in die `feature_store`- bzw. `signal_results`-Tabelle.