# chart/chart_basics.py
"""
chart/chart_basics.py - TradingView Lightweight Charts v5 HTML-Template
Lädt JS-Module aus chart/js/ und baut das finale HTML dynamisch zusammen.
"""

from pathlib import Path
from typing import Dict, List, TypeAlias

OHLCVRecord: TypeAlias = Dict[str, float | int]
CandleDataList: TypeAlias = List[OHLCVRecord]

COMBOBOX_STYLE = """
	QComboBox { background-color: #2b313e; color: white; border: 1px solid #3d4450; border-radius: 4px; padding: 3px 8px; font-weight: bold; }
	QComboBox::drop-down { border: none; }
	QComboBox QAbstractItemView { background-color: #1e222d; color: white; selection-background-color: #3d4450; }
"""

BUTTON_PRIMARY_STYLE = "background-color: #2b5c8f; color: white; font-weight: bold;"

CSS_STYLE = """
	html, body { margin: 0; padding: 0; width: 100%; height: 100%; background-color: #131722; overflow: hidden; font-family: sans-serif; user-select: none; }
	#chart-container { width: 100%; height: 100%; position: relative; }
	#measurement-region { display: none; position: absolute; background: rgba(41, 98, 255, 0.15); border: 1px dashed #2962FF; pointer-events: none; z-index: 999; }
	#measurement-box { display: none; position: absolute; background: #1e222d; border: 1px solid #2962FF; border-radius: 6px; padding: 8px 12px; color: #d1d4dc; font-size: 12px; pointer-events: none; z-index: 1000; line-height: 1.5; white-space: nowrap; }
	#price-badge { display: none; position: absolute; right: 2px; background: #2962FF; color: white; font-size: 11px; font-weight: bold; padding: 2px 6px; border-radius: 3px; pointer-events: none; z-index: 1000; will-change: transform, top; }
	#countdown-badge { display: none; position: absolute; right: 62px; background: #1e222d; border: 1px solid #2962FF; color: #2962FF; font-size: 11px; font-weight: bold; padding: 2px 6px; border-radius: 3px; pointer-events: none; z-index: 1000; will-change: transform, top; }
"""

JS_DIR = Path(__file__).resolve().parent / "js"

JS_FILES = [
    "01_core.js",
    "02_time_utils.js",
    "03_chart_rendering.js",
    "04_live_updates.js",
    "05_measurement.js",
]


def _load_js_modules() -> str:
    """Lädt alle JS-Dateien aus chart/js/ in der definierten Reihenfolge."""
    parts: list[str] = []
    for filename in JS_FILES:
        filepath = JS_DIR / filename
        try:
            content = filepath.read_text(encoding="utf-8")
            parts.append(f"// --- {filename} ---\n{content}")
        except FileNotFoundError:
            print(f"⚠️ [chart_basics] JS-Datei nicht gefunden: {filepath}")
    return "\n\n".join(parts)


def _build_html_template() -> str:
    """Baut das finale HTML aus CSS, CDN-Links und den JS-Modulen zusammen."""
    js_code = _load_js_modules()
    return f"""<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<style>{CSS_STYLE}</style>
	<script crossorigin="anonymous" src="https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"></script>
	<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
</head>
<body>
	<div id="chart-container">
		<div id="measurement-region"></div>
		<div id="measurement-box"></div>
		<div id="price-badge"></div>
		<div id="countdown-badge"></div>
	</div>
	<script>
{js_code}
	</script>
</body>
</html>"""


def build_html_template() -> str:
    """Baut das HTML-Template FRISCH aus den aktuellen JS-Dateien auf der Platte.

    WICHTIG (Developer-Erfahrung): JS-Aenderungen in chart/js/ greifen sofort
    bei jedem neuen Chart-Fenster – OHNE vollstaendigen App-Neustart.
    Dafuer wird bei jedem Aufruf neu von der Platte gelesen (kein Modul-Cache).
    """
    return _build_html_template()


# Abwaertskompatibilitaet: Konstante fuer Tests (check_html_template.py).
HTML_TEMPLATE = _build_html_template()
