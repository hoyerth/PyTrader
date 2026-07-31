# test/check_html_template.py
"""Verifiziert, dass das gebaute Chart-HTML-Template die JS-Fixes enthaelt."""
import sys
import os

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chart.chart_basics import HTML_TEMPLATE

checks = {
    "Guard getBerlinParts": "day: '--'" in HTML_TEMPLATE,
    "Kein Berlin-Offset (+2h)": "t + offset" not in HTML_TEMPLATE and "t + 7200" not in HTML_TEMPLATE,
    "Kein _isBerlinDST mehr": "_isBerlinDST" not in HTML_TEMPLATE,
    "Fix timeFormatter": "typeof t === 'object'" in HTML_TEMPLATE,
    "createSeriesMarkers (v5)": "createSeriesMarkers" in HTML_TEMPLATE,
    "Measurement-Modul (05_measurement)": "var Measurement = (function()" in HTML_TEMPLATE,
    "Measurement-Region DIV": "id=\"measurement-region\"" in HTML_TEMPLATE,
    "Measurement-Box DIV": "id=\"measurement-box\"" in HTML_TEMPLATE,
    "Measurement-Restore in applyFullChartUpdate": "Measurement.restore(data.measurementState)" in HTML_TEMPLATE,
}

all_ok = True
for name, ok in checks.items():
    print(("OK  " if ok else "FAIL") + " " + name)
    all_ok = all_ok and ok

print("HTML-Template-Laenge:", len(HTML_TEMPLATE))
sys.exit(0 if all_ok else 1)
