# Phase 16: Architektur Servive/Indikator - Feinarbeit Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 16)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase16_step1`, `phase16_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
4. **Zentraler `EventBus`:** Fenster und Worker communicaten schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
5. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db_service.py`) – eine Verbindung pro Thread und DB-Datei.
6. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
7. **Concurrency-Guard & Timer-Pausierung (Ergänzung 1):** Solange im ServiceWindow intensive Service-Berechnungen laufen (`SetRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
8. **Isolierter Test-Workspace (Ergänzung 2):** Alle neuen Test-Python-Dateien und temporären Test-Datenbanken (`*.duckdb`) müssen strikt im Unterordner `test/` erzeugt, gelesen und abgelegt werden – niemals im Projekt-Root oder im `data/`-Ordner.
9. **Open/Closed-Principle & Code-Preserving (Ergänzung 3):** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden und bestehende Kern-Klassen bleiben geschützt.
10. **Test-Cleanup (Ergänzung 4, Entscheidung 06.08.2026):** Tests werden NICHT aufbewahrt. Nach Abschluss jedes Phasenkapitels wird der Ordner `test/` aufgeräumt – es bleibt ausschließlich die Datei `test/test.py` (dauerhafter Test-Harness) bestehen. Alle temporären Check-Skripte (`check_*.py`/`*.js`), einmaligen Migrations-/Bereinigungsskripte, Test-Datenbanken (`*.duckdb`) und generierten Dateien (`tmp_*.json` u. Ä.) werden entfernt. Die Verifikation eines Kapitels erfolgt daher VOR der Bereinigung; danach existieren die Prüfskripte nicht mehr.

---
# 16.05 Prework: Generische Render-Engine für LWC v5 (Frontend Refactoring)

## 1. Konzept & Zielsetzung (Ultrakompakt)
* **Problem:** `chart/js/03_chart_rendering.js` enthält hartcodierte Branches (z. B. `indid == "indfixedgridproximity"`) und spezifische Canvas-Functions (`renderGridLines`, `renderGridCircles`)[cite: 1, 4].
* **Lösung:** Entfernung aller Indikator-spezifischen `if/else`-Branches. Einführung des generischen Grafik-Primitivs `renderLineSeries()` für unbegrenzte, hochperformante Linien-Drawings (MAs, Bänder, Trends) in Lightweight Charts v5[cite: 1].

---

## 2. IDE-AI Anweisung 

Führe ein Refactoring der Chart-Rendering-Engine durch, um hartcodierte Indikator-IDs zu entfernen und die generische Aufruf-Pipeline für Grafik-Primitive (`lines`, `markers`) zu etablieren.

### Schritt 1: Python Bridge-Pass-Through bereinigen (`chart/chart_win.py`)
* Entferne alle hartcodierten Fallunterscheidungen nach `indicator_id` (z. B. `if ind_id == "indfixedgridproximity"`) beim Aufruf von `runJavaScript`[cite: 1, 4].
* Leite das von den Indikatoren generierte `chart_render_payload` (Dict mit Keys `"lines"`, `"hit_circles"` / `"markers"`) **1:1 als generisches JSON-Objekt** an die JS-Funktion `applyChartRenderPayload(payload)` weiter[cite: 1].

---

### Schritt 2: Generische Render-Pipeline in JS erstellen (`chart/js/03_chart_rendering.js`)

1. **Neue Haupt-Schnittstelle `applyChartRenderPayload(payload)` erstellen:**
   * Empfängt das JSON-Payload und verteilt die Sub-Arrays an die jeweiligen Grafik-Primitive[cite: 1]:
     * `payload.lines` $\rightarrow$ ruft `renderLineSeries(payload.lines)` auf[cite: 1].
     * `payload.hit_circles` / `payload.markers` $\rightarrow$ ruft `renderMarkers(payload.hit_circles)` auf[cite: 1].

2. **Generischen Linien-Renderer `renderLineSeries(linesArray)` implementieren:**
   * Vergewissere dich, dass pro Eintrag im `linesArray` (`{ id, data, color, width, style }`) dynamisch eine LWC v5 `LineSeries` angelegt oder per `setData()` aktualisiert wird[cite: 1].
   * Verwalte aktive LineSeries in einer JS-Registry (`_activeLineSeries[id]`), damit inaktive/gelöschte MAs/Linien bei Payloaded-Updates sauber per `chart.removeSeries()` entfernt werden[cite: 1].

3. **Legacy-Cleanup:**
   * Binde die bisherigen Grid-Linien und Circles als Unterfälle in die generische Schnittstelle ein[cite: 1].
   * Lösche hartcodierte String-Checks auf alte Indikator-Namen[cite: 1, 4].

---
### ⚠️ Wichtiger Fix für VWMA: Volumendaten in `fetch_historical_candles` selektieren

**Problem:** `MarketDataRepository.fetch_historical_candles()` in `db_service.py` selektiert aktuell nur `open, high, low, close`. Das im DataFrame fehlende `tick_volume` führt beim `VWMA` zu einem Fallback.

**Anpassung in `db_service.py` (`MarketDataRepository`):**
1. Erweitere die SQL-Abfrage in `fetch_historical_candles()` um `tick_volume`:
   SELECT EXTRACT('epoch' FROM "time")::BIGINT AS time_epoch,
          open, high, low, close, tick_volume 
   FROM ohlcv_bars ...
---
### Schritt 3: Verifikation & System-Check (Ohne GUI)
* Führe den Node.js Syntax-Check auf allen geänderten JS-Dateien aus:
  * `node --check chart/js/01_core.js`[cite: 1]
  * `node --check chart/js/03_chart_rendering.js`[cite: 1]
* Führe das bestehende Test-Skript aus: `python test/check_html_template.py`[cite: 1].

--- 

# Phase 16.05 - Multi MA Indikator

Erstelle den Multi-MA-Indikator unter `chart/indicators/multi_ma.py`.
Der Indikator erbt von `BaseIndicator` und nutzt die `MATemplateEngine` aus Phase 16.04 (`chart/indicators/utils/ma_template.py`).

Entscheidungen
 - D1: Additiver Integrationspfad – Registry-Eintrag + 2 Branches in chart_win + neuer Button btn_indicator_ma (Text "MA") in chart_win.ui (Muster btn_indicator_grid_liquidity)
 - D4: Kontrastfarben MA2–8: Blau/Orange/Violett/Gelb/Rot/Cyan/Blaugrau (MA1 teal #26A69A bleibt Führung)
 - D5: maX_smooth_type bleibt Forward-Compat-Vertrag (nicht konsumiert, wie 16.04)
 - D6: calculate() → {"maLines": [...]}; build_chart_render_payload(df, params) als eigene Methode
 - D7: Defaults: MA1 EHMA/4/alpha 2.0/dual=False, MA2–8 EMA/10·X/alpha 2.0, alle show=False (außer MA1)

---

### 1. Parameter-Schema & Identität
* **`indicator_id`**: `"ind_moving_averages"`
* **`display_name`**: `"Multi Moving Average (8x)"`
* **`parameter_schema`**:
  * **MA 1 (Spezial-Führungslinie mit DualColor):**
    * `show_ma1` (bool, default: True)
    * `ma1_type` (Enum, default: `"EHMA"`)
    * `ma1_period` (int, min: 1, default: 4)
    * `ma1_smooth_type` (Enum, default: `"EHMA"`)
    * `ma1_alpha` (float, min: 0.1, default: 2.0)
    * `ma1_dual_color` (bool, default: False)  <-- NUR FÜR MA 1!
    * `ma1_bull_color` (color, default: `"#26A69A"`)
    * `ma1_bear_color` (color, default: `"#EF5350"`)
  * **MA 2 bis MA 8 (Standardschleife $X = 2..8$):**
    * `show_maX` (bool, default: False für MA2..8)
    * `maX_type` (Enum, default: `"EMA"`)
    * `maX_period` (int, min: 1, default: 10 * X)
    * `maX_smooth_type` (Enum, default: `"EMA"`)
    * `maX_alpha` (float, min: 0.1, default: 2.0)
    * `maX_color` (color, default: individuelle Kontrastfarben)  <-- Keine dual_color / bear_color Schalter!

---

### 2. Logik & Payload-Erzeugung (`build_chart_render_payload`)
1. **Daten-Zuschnitt:** Schneide den OHLCV-DataFrame auf `AppSettings.chart_candle_limit` zu[cite: 4].
2. **Schleife über alle 8 MAs:**
   * Prüfe `show_maX`. Wenn `False`, überspringe die Linie.
   * Berechne die MA-Series über `MATemplateEngine.calculate_ma(...)`.
   * **Farb-Zuweisung:**
     * Für **MA 1**: Nutze `MATemplateEngine.build_color_series(...)` basierend auf `ma1_dual_color`, `ma1_bull_color` und `ma1_bear_color`.
     * Für **MA 2..8**: Erzeuge eine einfarbige Farbliste mit `maX_color`.
   * Formatiere die Linie als LWC-kompatibles Objekt-Array.
3. **Rückgabe:** Gib das `chart_render_payload` mit allen aktiven Linien-Daten an das Frontend ab[cite: 1].

---
### ⚠️ Wichtiger Hinweis zur Frontend-Schnittstelle (Prework-Anpassung)
Durch das **16.05 Prework** ist die Chart-Rendering-Engine (`03_chart_rendering.js`) vollständig entkoppelt:
* Es gibt **keine** Indikator-spezifischen JS-Aufrufe mehr (`if ind_id == ...`)[cite: 1, 4].
* Der Indikator übergibt sein `chart_render_payload` direkt an die generische Pipeline `applyChartRenderPayload(payload)`[cite: 1].

### Erzeugungs-Regel für `chart_render_payload` im Multi-MA Indikator:
Jeder aktive MA (1–8) muss als eigener Linien-Eintrag im `lines`-Array des Payloads geliefert werden[cite: 1]:

# Beispiel-Struktur des generierten chart_render_payload:
{
    "lines": [
        {
            "id": "ma1",                      # Eindeutige ID pro Linie
            "data": [                        # LWC-kompatible Datenpunkte
                {"time": 1770000000, "value": 24.50, "color": "#26A69A"},
                {"time": 1770000060, "value": 24.52, "color": "#EF5350"}
            ],
            "width": 2,                      # Strichstärke
            "style": "solid"                 # Linienstil
        },
        {
            "id": "ma2",
            "data": [ ... ],                 # Farbwerte aus ma2_color
            "width": 1,
            "style": "solid"
        }
        # Weitere aktive MAs (3..8)...
    ]
}

### ⚠️ Wichtige Hinweise zur Frontend-Schnittstelle & Zeit-Mapping (Prework-Anpassung)

1. **Generische Render-Engine (Prework):**
   * Die Chart-Engine (`03_chart_rendering.js`) ist vollständig entkoppelt – keine Indikator-spezifischen JS-Aufrufe mehr (`if ind_id == ...`)[cite: 1, 4].
   * Der Indikator übergibt sein `chart_render_payload` direkt an die generische Pipeline `applyChartRenderPayload(payload)`.

2. **Zeit-Mapping (`real → kontinuierlich`):**
   * Die Datenpunkte im Payload müssen exakt auf die kontinuierliche Zeitachse des Charts gemappt sein (`timeRealToCont`), damit die MA-Linien lückenlos und deckungsgleich auf den Candles liegen[cite: 1].
   * Das JS-Frontend nutzt `resolveRealTime(ts)`[cite: 1], um sicherzustellen, dass jeder Datenpunkt exakt einem realen Candle-Zeitstempel zugeordnet ist[cite: 1].

### Erzeugungs-Regel für `chart_render_payload` im Multi-MA Indikator:
Jeder aktive MA (1–8) wird als eigener Linien-Eintrag im `lines`-Array des Payloads geliefert[cite: 1]:

# Beispiel-Struktur des generierten chart_render_payload:
{
    "lines": [
        {
            "id": "ma1",                      # Eindeutige ID pro Linie
            "data": [                        # LWC-kompatible Datenpunkte (gemappte Wanduhr-Epochs)
                {"time": 1770000000, "value": 24.50, "color": "#26A69A"},
                {"time": 1770000060, "value": 24.52, "color": "#EF5350"}
            ],
            "width": 2,                      # Strichstärke
            "style": "solid"                 # Linienstil
        },
        {
            "id": "ma2",
            "data": [ ... ],                 # Farbwerte aus ma2_color
            "width": 1,
            "style": "solid"
        }
        # Weitere aktive MAs (3..8)...
    ]
}
---

### 3. Persistenz & System-Integration
* Das Fenster- und Preset-System speichert/lädt alle Parameter automatisch über den `StateManager` (`indicator_presets`)[cite: 4].
* Registriere den Indikator ordnungsgemäß, sodass er im Chart-Fenster-Dialog auswählbar ist[cite: 1, 4].

---

### 4. Verifikation (Backend ohne GUI)
* Erstelle die Testdatei `test/test_multi_ma_indicator.py` (keine GUI/PySide6!).
* Prüfe:
  * Korrekte Generierung des Payloads für MA 1 mit `dual_color=True` vs. `dual_color=False`.
  * Einwandfreie Abarbeitung aller 8 MAs (Sichtbarkeit an/aus).
* Führe den statischen Syntax-Check aus: `python -m py_compile chart/indicators/multi_ma.py`.
* 
---

---

# Phase 16.05 – Konsistenz-Check, Entscheidungen & Ergänzungen (06.08.2026, Doku-Analyse)

> **Status:** Spezifikation analysiert, Projekt-Ist-Stand verifiziert, **Entscheidungen F1–F4 beschlossen (Benutzer-Freigabe 06.08.2026)**. Implementierung erfolgt erst auf ausdrücklichen Startbefehl. Vor der Umsetzung wird gemäß Invariante 1 ein Git-Commit/Tag gesetzt (Vorschlag: `phase16_step5`). **Prework-Anweisung (Generische Render-Engine) eingearbeitet – siehe unten.**

## 16.05 Prework – Konsistenz-Check (Generische Render-Engine, verifiziert am Ist-Stand)

### P-A. Ist-Stand-Verifikation

1. **Problemstellung bestätigt:** `chart/chart_win.py` enthält **zwei hartcodierte** `if ind_id == "ind_fixed_grid_proximity"`-Branches (Z.~607 in `render_indicators()`, Z.~772 in `_do_refresh_chart_data()`); `_apply_grid_render()` ruft `renderGridLines`/`renderGridCircles` direkt per `runJavaScript` auf (Z.~678-682). `chart/js/03_chart_rendering.js` hat nur die spezifischen `renderGridLines` (Preislinien) / `renderGridCircles` (Marker) – **kein** generisches Zeitreihen-Primitiv. ✅ (Refactoring-Bedarf real)
2. **`applyChartRenderPayload`/`renderLineSeries`/`renderMarkers` existieren NOCH NICHT** in `03_chart_rendering.js` – werden additiv neu erstellt. ✅ (Anweisung konsistent)
3. **`resolveRealTime(ts)` existiert** in `chart/js/02_time_utils.js` (Z.~87), inkl. `toReal`/`toCont`/`_rebuildTimeMaps`. ✅ (Prework-Referenz korrekt)
4. **`fetch_historical_candles` selektiert KEIN `tick_volume`** (`db_service.py`, Z.~558: nur `time_epoch, open, high, low, close`). → Prework-VWMA-Fix ist real und erforderlich. ⚠️
5. **Node.js verfügbar:** `node v24.18.0` → `node --check` auf JS-Dateien ausführbar. ✅
6. **`test/check_html_template.py` existiert NICHT mehr** (Invariante-10-Cleanup in 16.04). Prework Schritt 3 referenziert eine entfernte Datei. ⚠️ (Offene Frage F2)

### P-B. Entscheidungen Prework (aus der Anleitung abgeleitet)

- **P-D1 – Payload-Durchleitung 1:1:** `chart_win.py` baut pro Refresh/Re-Render das **generische Payload-Dict** `{"lines": [...], "hit_circles": [...]}` (aggregiert über alle aktiven Indikatoren) und reicht es per `applyChartRenderPayload(payload)` an JS. Die hartcodierten `if ind_id == ...`-Branches entfallen; der Indikator-spezifische Kreis-Mapping-Schritt (`_time_real_to_cont`) wird generisch über alle `hit_circles`-Zeiten aller Indikatoren angewendet.
- **P-D2 – JS-Dispatcher:** `applyChartRenderPayload(payload)` routet `payload.price_lines → renderPriceLines(price_lines)` (Preislinien, F1), `payload.lines → renderLineSeries(lines)` (LineSeries-Registry), `payload.hit_circles → renderMarkers(hit_circles)`. `renderLineSeries` pflegt eine Registry `_activeLineSeries[id]` (incrementelles `setData`, `removeSeries` für verschwundene IDs). `renderMarkers` übernimmt die bestehende inkrementelle Circle-Logik (`renderGridCircles` wird Unterfall/Refactoring).
- **P-D3 – Legacy-Unterfälle:** Die bestehenden Grid-Preislinien (`createPriceLine`, Felder `price/color/width/style/is_custom`) und Circles werden in die generische Pipeline eingebunden (Legacy-Cleanup gemäß Anweisung) – Preislinien unter dem neuen Key `price_lines` (F1), Circles unter `hit_circles` (unverändert).
- **P-D4 – VWMA-Fix (revidiert D3 aus 16.05-Analyse):** `fetch_historical_candles` wird um `tick_volume` erweitert. `df_data` erhält damit die Spalte `tick_volume` → der Multi-MA-Indikator kann `VWMA` mit echten Volumendaten rechnen (`volume=df["tick_volume"]`). Der frühere D3 („VWMA→SMA-Fallback") wird **obsolet** – der Template-Fallback bleibt als Defensivschutz (NaN/Null-Volumen), ist aber nicht mehr der Regelpfad.

### P-C. Ergänzungen der Doku (präzisierte Verträge für Prework-Umsetzung)

1. **`lines`/`price_lines`-Trennung (F1-Beschluss, ersetzt Feld-Dispatch):** Der frühere Vorschlag „Dispatch über `data` vs. `price` im selben `lines`-Array" ist **durch die Benutzerentscheidung F1 überholt**: Grid-Preislinien erhalten einen **eigenen `price_lines`-Key**, Multi-MA-LineSeries den `lines`-Key. Kein Feld-Dispatch, kein `kind`-Feld nötig. Routing in `applyChartRenderPayload`: `payload.price_lines → renderPriceLines()`, `payload.lines → renderLineSeries()`, `payload.hit_circles → renderMarkers()`. (Details siehe Abschnitt „Entscheidungen F1–F4".)
2. **Merging über alle Indikatoren:** chart_win aggregiert die Payloads **aller aktiven** Indikatoren in ein einziges `{"lines": [...], "price_lines": [...], "hit_circles": [...]}`. Kollisionen sind ausgeschlossen: Grid-Indikator liefert `price_lines` + `hit_circles`; Multi-MA liefert `lines` (LineSeries mit `id: "ma1".."ma8"`). Die JS-Registry ist id-basiert → inkrementelles Update über beide Pfade hinweg.
3. **Serializer-Umbau (F4-Beschluss):** `GridDataSerializer`/`_serialize_and_render_grid` werden auf das generische Payload-JSON umgestellt – **Threading-Muster exakt beibehalten** (QThread + done-Signal + Generations-Guard), nur das Payload-Format ändert sich (`done = Signal(str, int)` mit payload_json statt getrennte lines_json/circles_json). Der `update_package`-Pfad (`_do_refresh_chart_data`) erhält ein `chartRenderPayload`-Feld (analog `gridLines`/`gridCircles`), `applyFullChartUpdate` ersetzt Schritt 5+6 durch einen `applyChartRenderPayload`-Aufruf.
4. **Live-Overlay-Pfad unberührt:** `get_live_overlays` + `applyLiveOverlays` (04_live_updates.js) bleiben (bereits generisch über `kind`). Multi-MA liefert keine Live-Overlays (Basis-Default `[]`).
5. **Kein `btn_indicator_ma`-Sonderpfad mehr nötig:** Durch die generische Pipeline entfällt der frühere D1-Teil „2 Branches + renderMALines + Serializer". Die Registrierung (`self.indicators`-Dict) und der Button (`ui/chart_win.ui`, Text „MA") bleiben wie in D1. `D6` wird angepasst: `calculate()` → `{"lines": [...]}` (statt `{"maLines": [...]}`), jede Linie `{id, data, width, style, title}`; `build_chart_render_payload(df, params)` bleibt eigene Methode.

### A. Konsistenz-Check (verifiziert am Ist-Stand des Projekts)

1. **Basis vorhanden:** `MATemplateEngine` aus P16.04 (`chart/indicators/utils/ma_template.py`) existiert und ist committet (`092cc57`) – `calculate_ma` (12 Typen, α-Pfad E4, VWMA-SMA-Fallback E5), `build_color_series` (dual_color-Semantik E6), `build_chart_payload` (LWC-v5-Array `[{time, value, color}]`), `crop_dataframe` (tail), `get_ma_parameter_schema` + `resolve_bull_color`. ✅
2. **`AppSettings.chart_candle_limit` existiert** (`config/app_settings.py`, Default 3000). `chart_win` lädt OHLCV bereits mit `limit=self.settings.chart_candle_limit`; `df_data` (pd.DataFrame aus clean_candles) enthält Spalten `time/open/high/low/close` mit **echten Wanduhr-Epochs** (`fetch_historical_candles`, `db_service.py`). ✅
3. **BaseIndicator-Vertrag erfüllbar:** `indicator_id`, `display_name`, `default_params` (Properties) + `calculate(df, params)` (abstract) müssen implementiert werden. Der Dialog erkennt selbst-contained-Indikatoren über `parameter_schema` + `plugin_id` (Branch 1, `indicator_dialog._get_plugin`) – exakt das Muster von `FixedGridProximityIndicator` (`parameter_schema`, `parameter_order`, `base_parameter_schema`, `default_params`, `param_options`, `param_labels`, `param_layout`, `plugin_id`). ✅
4. **LWC-v5-Payload passt:** `build_chart_payload` liefert `[{time, value, color}]` – direkt als `LineSeries.setData()` verwendbar (Pro-Punkt-`color`, v5-konform). Zeit = reale Wanduhr-Epochs, müssen aber vor dem JS-Render auf **kontinuierliche Zeiten** gemappt werden (wie `grid_circles` via `self._time_real_to_cont`). ⚠️ (Ergänzung 1)
5. **KEIN generischer Time-Series-Renderer im JS:** `renderGridLines` zeichnet **horizontale Preislinien** (`createPriceLine`), `renderGridCircles` unsichtbare LineSeries mit Markern – **kein** Pfad für Zeitreihen-Linien (MA). Der bestehende `ind_id == "ind_fixed_grid_proximity"`-Branch in `chart_win` (`render_indicators()` ~Z.595 und `_do_refresh_chart_data()` ~Z.770, jeweils hartcodiert) ist die aktuelle Integrationsstelle. → Additive JS-Renderfunktion + additive chart_win-Branches nötig (Open/Closed, Invariante 9). ⚠️ (Ergänzung 2)
6. **`df_data` enthält KEIN `tick_volume`:** `fetch_historical_candles` selektiert nur `time/open/high/low/close`. VWMA im Multi-MA hat damit keinen Volumen-Input aus dem Chart-DF → Entscheidung D3. ⚠️
7. **Registrierung/Button:** chart_win-Registry (`self.indicators` Dict, Z.~187) + UI-Button `btn_indicator_grid_liquidity` in `ui/chart_win.ui` (Z.~178, 28×28, EventFilter Rechtsklick→Einstellungen) sind der etablierte Muster-Pfad. Für MA-Button additiv erweiterbar. ✅ (Ergänzung 3)
8. **Preset-Persistenz generisch:** `StateManager.indicator_presets` + `_PresetItemAdapter` (indicator_dialog) greifen automatisch, sobald der Indikator in Registry + Dialog erreichbar ist. Kein Sonderfall nötig. ✅
9. **`smooth_type`-Vertrag (aus P16.04, Ergänzung 1):** `maX_smooth_type` ist Schema-Vertrag (Forward-Compatibility) und wird von `MATemplateEngine.calculate_ma` **nicht konsumiert** – die Berechnung läuft über `maX_type`. Wird für 16.05 identisch übernommen (Entscheidung D5). ✅
10. **`test/test.py` unberührt:** Der permanente Harness konstruiert kein `ChartWindow` – die Registry-Erweiterung bricht keine bestehenden Checks. ✅

### B. Entscheidungen (aus der Anleitung abgeleitet)

- **D1 – Integrationspfad (additiv, Invariante 9):** `chart_win.py` erhält **einen** neuen Registry-Eintrag `"ind_moving_averages": MultiMovingAverageIndicator()` und **zwei additive** Branches:
  * `render_indicators()`: `elif ind_id == "ind_moving_averages"` → MA-Linien aus `calculate()` über neue `_serialize_and_render_ma_lines()` an JS.
  * `_do_refresh_chart_data()`: `maLines`-Feld im `update_package` sammeln (analog `gridLines`/`gridCircles`), damit MA-Linien auch nach Voll-Rebuild erhalten bleiben.
  * `ui/chart_win.ui`: neuer Button `btn_indicator_ma` (additive XML-Elemente) + Verdrahtung in chart_win (toggle/settings/eventFilter/Style) – exakt das Muster von `btn_indicator_grid_liquidity`.
- **D2 – JS-Renderer (additiv):** Neue Funktion `renderMALines(maLines)` + `clearMALines()` in `chart/js/03_chart_rendering.js` (incrementelles Upsert je MA-Linie per `setData`, analog `renderGridCircles` – kein removeSeries/addSeries für unveränderte Linien). Aufruf in `applyFullChartUpdate` als neuer Schritt (nach Schritt 6). `maLines`-Format: `[{id, title, color, data: [{time, value, color}]}]` – `data` direkt LWC-`LineSeries.setData`-Input (Zeiten vorher in chart_win real→kontinuierlich gemappt).
- **D3 – VWMA ohne `tick_volume`:** `df_data` hat kein Volumen. **Entscheidung:** VWMA fällt auf SMA zurück (E5-Fallback des Templates, dokumentiert). Ein separates Volumen-Nachladen via DB ist eine spätere optionale Erweiterung (read-only via `DbPool` + `set_context`), **kein** Bestandteil von 16.05 (kein Kern-Eingriff in `fetch_historical_candles`).
- **D4 – Kontrastfarben MA2..8 (individuelle Defaults):** `maX_color`-Defaults (TradingView-kontrastreich, MA1 teal `#26A69A` bleibt Führungslinie):
  * MA2 `#2962FF` (Blau), MA3 `#FF6D00` (Orange), MA4 `#AB47BC` (Violett), MA5 `#FDD835` (Gelb), MA6 `#FF5252` (Rot), MA7 `#00E5FF` (Cyan), MA8 `#B0BEC5` (Blaugrau).
- **D5 – `smooth_type` nicht konsumiert:** Schema enthält `maX_smooth_type` (Forward-Compatibility, P16.04-Ergänzung 1), `calculate` nutzt nur `maX_type`.
- **D6 – `chart_render_payload`-Schlüssel:** `calculate()` liefert `{"maLines": [...]}` (additiv, kollisionsfrei zu `lines`/`hit_circles`). `build_chart_render_payload(df, params)` wird als eigene Methode implementiert (analog fixed_grid_proximity), `calculate()` ruft sie intern auf.
- **D7 – Defaults:** MA1 `show=True`, `ma1_type="EHMA"`, `ma1_period=4`, `ma1_alpha=2.0`, `ma1_dual_color=False`, `ma1_bull_color="#26A69A"`, `ma1_bear_color="#EF5350"`; MA2..8 `show=False`, `maX_type="EMA"`, `maX_period=10*X`, `maX_alpha=2.0`, Farben nach D4.

### C. Ergänzungen der Doku (präzisierte Verträge für die Umsetzung)

1. **Zeit-Mapping real→kontinuierlich:** MA-Linien-Zeiten sind reale Wanduhr-Epochs. Vor der JS-Übergabe werden sie via `self._time_real_to_cont.get(ts, ts)` gemappt (gleicher Mechanismus wie `hit_circles`). Ohne Mapping lägen die Linien an falschen x-Positionen (kontinuierliche Skala).
2. **Zwei Render-Pfade konsistent halten:** `render_indicators()` (Param-/Toggle-Änderungen ohne Voll-Rebuild) UND `update_package.maLines` (Voll-Rebuild) müssen dieselben Daten liefern – beide Pfade nutzen dieselbe Sammel-Methode im chart_win, damit kein Doppel-Pflege-Problem entsteht.
3. **Schema-Erzeugung programmatisch:** Das 56+-Param-Schema (8 MAs × 7 Keys) wird in einer Schleife `for x in range(1, 9)` generiert (MA1 mit `dual_color`/`bull`/`bear`, MA2..8 mit `maX_color`), nicht manuell ausgeschrieben – Fehlerquelle minimieren. `param_labels`/`param_layout` analog generisch (Gruppen „MA 1 (Führung)" und „MA 2..8").
4. **NaN-Handling:** `build_chart_payload` (P16.04) skippt Warmup-NaNs bereits – jede MA-Linie beginnt dadurch deterministisch bei ihrem ersten definierten Wert. Kein zusätzliches Cleanup im Indikator nötig.
5. **`set_context`/`set_settings` implementieren:** Wie `FixedGridProximityIndicator` (duck-typed via `hasattr` in chart_win) – `set_context(symbol, timeframe)` und `set_settings(settings)` (Injection der AppSettings, sonst lazy aus StateManager). Wird für D3 (späteres Volumen-Nachladen) und den `chart_candle_limit`-Zugriff vorbereitet.
6. **Testabdeckung (F2-Beschluss, gezielter Logik-Test in `test/test.py` – permanente Harness statt temporärer `test/test_multi_ma_indicator.py`):** Schema-Vollständigkeit (56 Parameter, Defaults MA1/MA2..8), Payload MA1 `dual_color=True` vs `False` (Farbumschlag korrekt), alle 8 MAs einzeln + kombiniert (show an/aus), `crop_dataframe` auf `chart_candle_limit`, LWC-Konformität (`time` int, `value` float, `color` str), VWMA mit `tick_volume` aus `df_data` (F3), `py_compile` auf `multi_ma.py` + Import-Smoke. Prework-Logik (Payload-Aggregation, Key-Routing `lines`/`price_lines`/`hit_circles`, tick_volume-Spalte) wird als gezielter Logik-Test in `test/test.py` abgedeckt.

---

## Entscheidungen F1–F4 – BESCHLOSSEN (Benutzer-Freigabe 06.08.2026)

> Verbindliche Vorgaben für die Umsetzung von 16.05 Prework + Multi-MA. Alle offenen Fragen sind damit beantwortet.

### F1 – Eigener `price_lines`-Key (beschlossen)

**Entscheidung:** Grid-Preislinien erhalten einen eigenen `price_lines`-Key; der `lines`-Key ist ausschließlich für Zeitreihen-LineSeries (Multi-MA) reserviert.

**Konsequenzen (verbindlich):**
1. **Generisches Payload-Schema:** `{"lines": [...], "price_lines": [...], "hit_circles": [...]}`.
   * `price_lines` = horizontale Preislinien (Grid-Legacy, Felder `price/color/width/style/is_custom`) → `candleSeries.createPriceLine(...)`.
   * `lines` = Zeitreihen-LineSeries (Multi-MA, `{id, data, width, style, title}`) → LWC-`LineSeries` via `_activeLineSeries[id]`.
   * `hit_circles` = Marker (Grid-Legacy, unverändert).
2. **`fixed_grid_proximity.py`:** `build_chart_render_payload()` und `calculate()` liefern den Grid-Render-Payload künftig mit **`price_lines`** statt `lines` (zusätzlich `hit_circles` + `status_info`). `_cached_grid_lines`-Logik (Live-Overlays) bleibt unverändert.
3. **chart_win:** aggregiert die Payloads aller aktiven Indikatoren generisch (Keys `lines`/`price_lines`/`hit_circles` gemerged) – keine Indikator-spezifischen Branches mehr.
4. **JS-Dispatcher `applyChartRenderPayload(payload)`:** `payload.price_lines → renderPriceLines()`, `payload.lines → renderLineSeries()`, `payload.hit_circles → renderMarkers()`. **Kein Feld-Dispatch, kein `kind`-Feld.**

### F2 – Verifikation ohne eigenständige Check-Skripte (beschlossen)

**Entscheidung:** Verifikation ausschließlich über `node --check` (geänderte JS-Dateien) + `python -m py_compile` (geänderte Python-Dateien) + **gezielter Logik-Test in `test/test.py`** (permanenter Harness).

**Konsequenzen (verbindlich):**
1. `test/check_html_template.py` wird **nicht** neu angelegt (Prework Schritt 3 entfällt in dieser Form).
2. **16.05 Schritt 4 (Multi-MA):** Die geforderte `test/test_multi_ma_indicator.py` wird **nicht** als eigene Datei angelegt – die Tests laufen als gezielte Logik-Tests in `test/test.py` (Benutzerentscheidung F2 hebt die Schritt-4-Formulierung auf; Invariante 10 wird dadurch strikt eingehalten, kein Cleanup-Schritt nötig).
3. Prework-Logik (Payload-Aggregation, Key-Routing, tick_volume-Spalte) wird in `test/test.py` als gezielter Logik-Test abgedeckt.

### F3 – `tick_volume` NaN → 0 (beschlossen)

**Entscheidung:** Normalisierung NaN/None → 0; die Candle bleibt gültig.

**Konsequenzen (verbindlich):**
1. `fetch_historical_candles()` selektiert `tick_volume` (ohne `IS NOT NULL`-Filter; WHERE-Bedingung prüft weiterhin nur OHLC).
2. NaN/None-`tick_volume` verwirft die Candle **nicht**; die Normalisierung auf 0 erfolgt beim Aufbau von `clean_candles`/`df_data` (damit `json.dumps(allow_nan=False)` nie an `tick_volume` scheitert).
3. Die VWMA-Engine normalisiert zusätzlich intern NaN→0 (P16.04 Ergänzung 5) – Doppel-Absicherung.
4. Multi-MA nutzt `df["tick_volume"]` (mit `fillna(0)`-Garantie aus Punkt 2) für `VWMA`.

### F4 – Threading-Muster exakt beibehalten (beschlossen)

**Entscheidung:** `GridDataSerializer` (QThread + done-Signal + Generations-Guard) bleibt unverändert; **nur das Payload-Format** wird angepasst.

**Konsequenzen (verbindlich):**
1. `GridDataSerializer.done = Signal(str, int)` (payload_json, gridGen) statt getrennter `lines_json`/`circles_json`.
2. `_serialize_and_render_grid(payload: dict)` serialisiert das aggregierte generische Payload-Dict als **ein** JSON.
3. `_apply_grid_render(payload_json, grid_gen)` verwirft veraltete Generationen (unverändert) und ruft `applyChartRenderPayload(payload_json)` auf.
4. Kein Ersatz durch `ChartDataSerializer`; kein neues Threading-Muster.

---

## Umsetzungs-Reihenfolge (verbindlich, auf Startbefehl)

1. **Git-Backup/Tag `phase16_step5`** (Invariante 1).
2. **Prework Schritt 1 + VWMA-Fix:** `db_service.py` (`tick_volume` in `fetch_historical_candles`) + `chart_win.py` (generische Payload-Aggregation, hartcodierte Branches entfernen, Serializer-Payload-Format F4).
3. **Prework Schritt 2 (JS):** `03_chart_rendering.js` – `applyChartRenderPayload`, `renderLineSeries` (Registry), `renderPriceLines`, `renderMarkers`, Legacy-Cleanup (`renderGridLines`/`renderGridCircles` als Unterfälle/Aliasse); `04_live_updates.js` – `applyFullChartUpdate` Schritt 5+6 durch `applyChartRenderPayload` ersetzen.
4. **Prework Schritt 3 (F2):** `node --check` auf allen geänderten JS-Dateien + `py_compile` auf geänderten Python-Dateien + gezielter Logik-Test in `test/test.py`.
5. **16.05 Multi-MA:** `chart/indicators/multi_ma.py` (Schema programmatisch, `build_chart_render_payload` → `{"lines": [...]}` mit `id: "ma1".."ma8"`, `calculate()`), Registrierung in chart_win, Button `btn_indicator_ma` in `chart_win.ui` (D1).
6. **16.05 Verifikation (F2):** gezielter Logik-Test in `test/test.py` + `py_compile` + Import-Smoke.

---

# Phase 16.05 – Implementierungs-Log: Indikator-Dialog Bugfix Multi-MA (06.08.2026)

> **Status:** Umsetzung **abgeschlossen** (Commit `6cecb11`, nach Benutzer-Freigabe im Bugfixing-Modus). Die drei Anwenderanforderungen am Multi-MA-Prop-Fenster sind behoben und per gezieltem Logik-Test in `test/test.py` (Teil 10, D1–D6) verifiziert. Git-Backup vor der Umsetzung: `6cecb11`; Vor-Kapitel: Prework + Multi-MA (Commits `16a5838`, `ba60361`, `370031f`).

## Ausgangslage (Bugfixing-Modus, 3 Anwenderanforderungen)

1. **„in diesem indikator gibt es keine services – dazu alles ausblenden":** Das Prop-Fenster des Multi-MA zeigte trotz `service_plugin_ids=[]` die komplette Service-UI (`Service-Parameter`, `Service-Set Aktionen`, `Experten-Optionen`).
2. **„ma_farbe hat eine checkbox, das ist nicht richtig ... bitte entfernen":** Farb-Parameter wurden als `StylePickerWidget`-Composite gerendert – inklusive der „sichtbar"-Checkbox. Sie hat keine Funktion (die Sichtbarkeit steuert ausschließlich `show_maX`) und war vom Benutzer nicht definiert.
3. **„für jeden ma fehlen parameter: a. die länge, b. der ma type, c. der glättungstyp, d. der alpha wert":** Die Nicht-Darstellungs-Parameter (`maX_type`/`maX_period`/`maX_smooth_type`/`maX_alpha`) wurden im Plugin-Pfad von `_init_plugin_ui` über `_is_visual_key()` gefiltert und erschienen **nirgends** – die Service-Parameter-Box rendert nur Service-Seiten.

## Ursachenanalyse (Ist-Stand)

- `indicator_dialog._init_plugin_ui` baute `indi_group` („Anzeige & Farben") nur aus `_is_visual_key()`-Keys (`show_*` / `color`) und danach **immer** die drei Service-Boxen – unabhängig davon, ob der Indikator Services deklariert.
- `_is_visual_key` ordnet alle `color`-Keys als visuell ein → sie landen im `StylePickerWidget`-Composite (mit „sichtbar"-Checkbox). Das Composite ist für Grid-Farben (Linienstil/-stärke) korrekt, für reine MA-Farben nicht.
- Die Nicht-Darstellungs-Parameter des Multi-MA hatten im Plugin-Pfad **keinen** Render-Ort.

## Umsetzung (Commit `6cecb11`)

1. **Service-UI ausblenden (Anforderung 1):** `_init_plugin_ui` prüft `self._indicator_service_ids()`. Ohne Services wird die neue Methode `_init_plugin_ui_params_only(main_layout)` aufgerufen: rendert **alle** Parameter direkt, gruppiert nach `param_layout` (Multi-MA: „MA 1 (Führung)" … „MA 8"), plus Preset-Verwaltung rechts. Die drei Service-Boxen entfallen komplett. **Additiv:** Der Service-Pfad für Grid-Indikatoren bleibt unverändert.
2. **Reiner Farbwähler (Anforderung 2):** `StylePickerWidget` erhält den Konstruktor-Parameter `color_only` (nur der Farb-Button wird gerendert; keine „sichtbar"-Checkbox, keine Linienart/-stärke) + Property `color_only`. Die Multi-MA-Farbparameter (`ma1_bull_color`/`ma1_bear_color`/`ma2..8_color`) deklarieren `"color_only": True`; `create_schema_control` rendert sie als reinen Farbwähler. Die drei Round-Trip-Pfade (`_build_preset_payload`, `collect_params_from_ui`, `update_ui_from_params`) überspringen für `color_only` die Geschwister-Keys (`maX_style`/`maX_width`).
3. **Fehlende MA-Parameter (Anforderung 3):** Durch `_init_plugin_ui_params_only` erscheinen jetzt `maX_type` (Choice), `maX_period`/Länge (SpinBox), `maX_smooth_type` (Choice) und `maX_alpha` (DoubleSpinBox) mit den Defaults (D7): MA1 `EHMA/4/EHMA/2.0`, MA2..8 `EMA/10·X/EMA/2.0`.
4. **None-Vorbelegung der Service-Attribute in `__init__`:** `combo_service_set`, `combo_service_sel`, `stack_service_forms`, `edit_set_name`, `edit_set_description`, `group_expert` werden mit `None` initialisiert → alle bestehenden `if self.<attr>:`-Guards (z. B. `_build_preset_payload`, `on_preset_selected`, `refresh_service_set_list`) werden None-sicher, ohne den Service-Pfad zu verändern.

## Verifikation (F2, gezielter Logik-Test in `test/test.py` Teil 10)

- **D1:** `_get_plugin` liefert den Indikator selbst; `_indicator_service_ids()` leer. ✅
- **D2:** Keine Service-UI (`combo_service_set`/`edit_set_name`/`group_expert` sind `None`). ✅
- **D3:** Alle 50 Parameter in `param_controls`; `maX_type`/`maX_smooth_type` = ComboBox, `maX_period` = SpinBox, `maX_alpha` = DoubleSpinBox; Defaults MA1/MA2 korrekt. ✅
- **D4:** Farb-Controls = `StylePickerWidget` mit `color_only=True`. ✅
- **D5:** Preset-Payload: `logic_params` enthält `maX_type/period/smooth_type/alpha`; `display_params` enthält `show_maX` + Farben; keine Sibling-Keys (`maX_style`/`maX_width`). ✅
- **D6 (Kontrolle):** Grid-Indikator (mit Services) behält die Service-UI unverändert. ✅
- **Zusätzlich:** `python -m py_compile` auf allen 4 geänderten Dateien erfolgreich. Die 6 vorbestehenden Fehlschläge (P2/P5/H3–H5/H7, ServiceWindow) sind unverändert und **nicht** durch diese Änderung verursacht.
- **Datumskorrektur:** Die Code-Kommentare trugen zunächst fälschlich „08.08.2026" – auf das tatsächliche Datum **06.08.2026** korrigiert (nachgelagerter Commit).

---

# Phase 16.05 – Implementierungs-Log: Multi-MA Prop-Fenster Layout (06.08.2026)

> **Status:** Umsetzung **abgeschlossen** (Commit `d3e7f7e`, nach Benutzer-Freigabe im Bugfixing-Modus). Die vier Layout-Anforderungen am Multi-MA-Prop-Fenster sind behoben und per gezieltem Logik-Test in `test/test.py` (Teil 10, D7) verifiziert. Vorheriger Commit: `6cecb11`/`6566945` (Dialog-Bugfix + Doku).

## Anwenderanforderungen (Bugfixing-Modus, 4 Layout-Punkte)

1. **Preset-Box ganz oben links.**
2. **Darunter immer zwei MA-Boxen nebeneinander** (1-2, 3-4, 5-6, 7-8).
3. **Das Fenster ist immer nur etwas breiter als die zwei MA-Boxen nebeneinander.**
4. **Das Fenster ist genauso hoch wie der untere Rand der MA-Boxen 7 und 8.**

## Ausgangslage (Ist-Stand)

- `_init_plugin_ui_params_only` baute eine linke Spalte (`QVBoxLayout`) mit allen Parameter-Boxen untereinander und platzierte die Preset-Box rechts daneben (rechte Spalte). Der Schließen-Button hing am Ende von `init_ui` (unterhalb des Inhalts).
- **Problem 1/2:** Die MA-Boxen standen untereinander (eine Spalte), nicht paarweise nebeneinander.
- **Problem 3:** Die Preset-Box war **508px breit** und stand in einer eigenen Grid-Spalte – dadurch wurde die Gesamtbreite auf ~800px aufgebläht (die zwei MA-Boxen brauchen nur ~684px). Gemessen: Fenster 800px vs. MA-Boxen 684px.
- **Problem 4:** Der Schließen-Button unterhalb der Boxen + `_build_preset_group` rechts verlängerten das Fenster unter den unteren Rand von MA7/MA8.

## Umsetzung (Commit `d3e7f7e`)

`_init_plugin_ui_params_only` wurde auf ein **kompaktes `QGridLayout`** umgestellt:

1. **Zeile 0 – Preset oben links + Schließen oben rechts:** Eine `QHBoxLayout`-Zeile, die über **beide** Spalten spannt (`addLayout(top_row, 0, 0, 1, 2, Qt.AlignTop)`): Preset-Box links, `addStretch(1)`, Schließen-Button rechts. Der Button sitzt damit oben rechts (Anforderung 1) – kein separates Element unterhalb mehr.
2. **MA-Boxen in 2er-Zeilen:** Die Parameter-Boxen werden zunächst gesammelt (`rendered_groups`) und dann **paarweise** ins Grid gesetzt (`for i in range(0, len, 2)` → Zeile 1: MA1+MA2, Zeile 2: MA3+MA4, Zeile 3: MA5+MA6, Zeile 4: MA7+MA8). Anforderung 2.
3. **Breite nur „etwas breiter" als 2 MA-Boxen:** Weil die Top-Zeile über beide Spalten spannt und `addStretch(1)` den Restplatz aufnimmt, verbreitert die 508px-Preset-Box das Grid **nicht** mehr. Die Spaltenbreiten bestimmen die MA-Boxen (`setColumnStretch(0/1, 1)` gleichmäßig). **Gemessen:** Fenster 712px vs. zwei MA-Boxen 684px (nur Fensterrahmen) – vorher 800px. Anforderung 3.
4. **Höhe = unterer Rand MA7/MA8:** Nichts unterhalb der letzten Boxen-Zeile; `init_ui` fügt den Schließen-Button nur noch an, wenn er nicht bereits im Plugin-Grid platziert wurde (`_close_placed_in_plugin_ui`-Guard). Das `ContentScrollMixin` klemmt die Fenstergröße exakt auf den Inhalt → Fensterhöhe = unterer Rand von MA7/MA8. Anforderung 4.

## Verifikation (F2, gezielter Logik-Test in `test/test.py` Teil 10, D7)

- **D7 Grid-Layout gefunden:** `_init_plugin_ui_params_only` erzeugt ein `QGridLayout` im Inhalt. ✅
- **D7 Preset oben links + Schließen oben rechts** (Zeile 0, HBox span 2). ✅
- **D7 Kein separater Button unterhalb** (nur das Grid im Inhalt). ✅
- **D7 MA-Boxen 2er-Zeilen:** Zeile 1 = MA 1 (Führung)+MA 2, Zeile 2 = MA 3+MA 4, Zeile 3 = MA 5+MA 6, Zeile 4 = MA 7+MA 8. ✅
- **D7 Nichts unterhalb MA7/MA8** (Grid-Zeile 5 leer). ✅
- **Geometrie-Messung (offscreen):** Fensterbreite 712px ≈ 2 MA-Boxen (684px) + Rahmen; Inhalt endet am unteren Rand 937px (MA7/MA8). ✅
- **Zusätzlich:** `python -m py_compile` auf `chart/indicator_dialog.py` + `test/test.py` erfolgreich. Die 6 vorbestehenden Fehlschläge (P2/P5/H3–H5/H7, ServiceWindow) sind unverändert und **nicht** durch diese Änderung verursacht.

---

