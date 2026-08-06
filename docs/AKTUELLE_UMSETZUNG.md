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

# Phase 16.04 - Generisches MA Template Modul

Erstelle ein generisches, wiederverwendbares Moving-Average-Helper-Modul unter `chart/indicators/utils/ma_template.py`.
Das Modul ist KEIN Analytics-Plugin und schreibt KEINE Daten in den Feature Store. Es dient als reine Utility-Klasse für Indikatoren.

---

### Schritt 1: Dateistruktur anlegen
Erstelle die Datei `chart/indicators/utils/ma_template.py` (inkl. `__init__.py` im `utils`-Ordner, falls nicht vorhanden).

### Schritt 2: Kerntypen & Parameter-Schema definieren
* Definiere `MAType = Literal["SMA", "EMA", "WMA", "DEMA", "TEMA", "HMA", "EHMA", "ZLEMA", "RMA", "KAMA", "ALMA", "VWMA"]`.
* Erstelle eine statische Methode `get_ma_parameter_schema()`, die Standard-Parameter für Indikatoren bereitstellt:
  * `ma_type` (Enum/Choice, Default: `"EHMA"`)
  * `period` (int, min: 1, default: 4)
  * `smooth_type` (Enum/Choice, Default: `"EHMA"`)
  * `alpha_factor` (float, min: 0.1, default: 2.0)
  * `dual_color` (bool, default: False)
  * `bull_color` (color, default: `"#2196F3"` wenn dual_color=False, `"#26A69A"` wenn dual_color=True)
  * `bear_color` (color, default: `"#EF5350"`)

### Schritt 3: Vektorisierte Mathematik-Engine implementieren
Implementiere die Klasse `MATemplateEngine` mit folgenden Methoden:

1. `crop_dataframe(df: pd.DataFrame, max_limit: int) -> pd.DataFrame`:
   * Schneidet den DataFrame auf `df.tail(max_limit)` zu.
2. `calculate_ma(source: pd.Series, ma_type: MAType, period: int, alpha_factor: float, volume: Optional[pd.Series] = None) -> pd.Series`:
   * Implementiere alle 12 MA-Typen vektorisiert via NumPy/Pandas.
   * Für `VWMA`: Nutze `volume` (z. B. `df['tick_volume']`). Falls `volume` fehlt/Null ist, Fallback auf `SMA`.
   * Für Alpha-MAs (`EHMA`, `DEMA`, `TEMA`): Verfahre über den dynamischen Decay-Faktor $\alpha = \frac{\text{alpha\_factor}}{\text{period} + 1}$.
3. `build_color_series(ma_series: pd.Series, dual_color: bool, bull_color: str, bear_color: str) -> List[str]`:
   * Vergleiche $t$ vs. $t-1$.
   * Wenn `dual_color==False`: Verwende durchgehend `bull_color`.
   * Wenn `dual_color==True`: $ma_t \ge ma_{t-1} \rightarrow$ `bull_color`, sonst `bear_color`.
4. `build_chart_payload(time_series: pd.Series, ma_series: pd.Series, colors: List[str]) -> List[Dict[str, Any]]`:
   * Formatiere das Array direkt als LWC-kompatibles Objekt-Array: `[{"time": ts, "value": val, "color": col}, ...]`.

### Schritt 4: Backend-Logiktest erstellen
* Erstelle die Testdatei `test/test_ma_template.py` (keine GUI/PySide6!).
* Teste:
  * Korrekte Längenberechnung aller 12 MA-Typen.
  * Korrekten Farbumschlag ($t$ vs. $t-1$) bei `dual_color=True` und `dual_color=False`.
  * Funktion von `VWMA` mit `tick_volume` aus `market_data.duckdb`.
* Führe den statischen Syntax-Check aus: `python -m py_compile chart/indicators/utils/ma_template.py`.

---

## Konsistenz-Check, Entscheidungen & Ergänzungen (06.08.2026, Doku-Analyse)

> **Status:** ✅ UMGESETZT & COMMITTET (06.08.2026 21:09). Spezifikation analysiert, Projekt-Ist-Stand verifiziert, Implementierung abgeschlossen (Invariante-1-Backup/Tag `phase16_step4` auf Commit `edc823d`, danach Umsetzungs-Commit). Verifikation headless über `test/test_ma_template.py` (61/61 Checks PASS, inkl. VWMA-DB-Test gegen echte `market_data.duckdb`).

### A. Konsistenz-Check (verifiziert am Ist-Stand des Projekts)

1. **Zielverzeichnis existiert noch nicht:** `chart/indicators/utils/` ist nicht vorhanden (Ist: nur `base_indicator.py`, `fixed_grid_proximity.py`, `__init__.py`). → Wird additiv angelegt (`utils/__init__.py` + `ma_template.py`); `chart/indicators/__init__.py` bleibt bewusst exportfrei (bestehender Kommentar, kein harter Import). ✅ Open/Closed-konform (Invariante 9).
2. **Schema-Konvention ist kompatibel:** Das Projekt nutzt `{"type": "float|int|bool|choice|color", "default", "min"/"max"/"step", "options", "description", "style_type"}` (verifiziert an `_FIXED_GRID_PROXIMITY_SCHEMA` in `chart/indicators/fixed_grid_proximity.py` und am Renderer in `chart/indicator_dialog.py`, Zeilen ~510–576). → „Enum/Choice" wird als `"type": "choice"` mit `"options": list(MAType)` abgebildet; `bull_color`/`bear_color` als `"type": "color", "style_type": "line"`. ✅
3. **LWC-v5-Payload-Vertrag passt:** `[{"time": ts, "value": val, "color": col}, ...]` ist LWC-v5-konform (LineSeries unterstützt Pro-Punkt-`color`). `time` = epoch-Sekunden (Wanduhr-encoded, int) – exakt die Konvention der `hit_circles.bar_time` (`fixed_grid_proximity.py`). Invariante 6 (Wanduhr ohne Berlin-Offset) wird dadurch geerbt. ✅
4. **NaN-Handling ist zwingend im Template:** `chart_win.py` strippt NaN/Inf global via `_clean_nan()` (Zeilen 76–81) vor `json.dumps(allow_nan=False)`. Die Warmup-NaNs der MAs (erste `period-1` Werte) werden aber bereits im Template gefiltert (siehe Ergänzung 3), damit der Payload deterministisch sauber ist. ✅ (Ergänzung)
5. **Volumen-Vertrag passt:** `tick_volume` ist exakt die Spalte aus `FeatureBuilder.load_ohlcv()` / `market_data.duckdb`. → `VWMA`-Aufruf `volume=df["tick_volume"]` ist projektkonform. ✅
6. **Runtime vorhanden:** `.venv` = numpy 2.5.1 / pandas 3.0.5. → Alle 12 Typen sind vektorisierbar; RMA via `ewm(alpha=1/period, adjust=False)`, KAMA rekursiv über NumPy-Array (ER-basiert), ALMA/HMA/WMA via Rolling/Convolve. ✅
7. **Testdatei & Test-Cleanup sind vereinbar:** `test/test_ma_template.py` wird als temporäres Verifikationsskript erzeugt und nach Kapitelabschluss gemäß Invariante 10 entfernt (dauerhaft bleibt nur `test/test.py`). Die Verifikation erfolgt VOR der Bereinigung – konsistent mit dem dokumentierten Ablauf. ✅

### B. Entscheidungen (aus der Anleitung abgeleitet)

- **E1:** Das Modul ist eine reine Utility – **kein** Analytics-Plugin, **kein** Feature-Store-Write (deckt sich mit der P16.01-Philosophie: Services liefern Rohdaten, Darstellung erfolgt additiv im Indikator).
- **E2:** `MAType` = TradingView-konformer 12er-Satz in exakter Reihenfolge: SMA, EMA, WMA, DEMA, TEMA, HMA, EHMA, ZLEMA, RMA, KAMA, ALMA, VWMA.
- **E3:** Defaults: `ma_type="EHMA"`, `period=4`, `alpha_factor=2.0`, `smooth_type="EHMA"`, `dual_color=False`, `bear_color="#EF5350"`.
- **E4:** Alpha-MAs (EHMA, DEMA, TEMA) verwenden den dynamischen Decay $\alpha = \frac{\text{alpha\_factor}}{\text{period} + 1}$ (statt fixer Standardfaktoren).
- **E5:** VWMA ohne gültiges Volumen → Fallback auf SMA.
- **E6:** dual_color-Semantik: Vergleich $t$ vs. $t-1$; `dual_color=False` → durchgehend `bull_color`; `dual_color=True` → $ma_t \ge ma_{t-1}$ = `bull_color`, sonst `bear_color`.
- **E7:** `bull_color`-Default ist bedingt (siehe Ergänzung 2) – `#2196F3` bei `dual_color=False`, `#26A69A` bei `dual_color=True`.

### C. Ergänzungen der Doku (präzisierte Verträge für die Umsetzung)

1. **`smooth_type`-Vertrag (Offenpunkt aus Schritt 2/3):** Das Schema führt `smooth_type` (Default `"EHMA"`), Schritt 3 spezifiziert aber nur den α-Pfad. **Präzisierung:** `smooth_type` ist ein Schema-Vertrag für spätere MA-Indikatoren und wird von `MATemplateEngine` in 16.04 **noch nicht konsumiert** (reine Forward-Compatibility). EHMA wird als $\text{EMA}(\text{HMA}(src, len), len)$ mit α aus E4 implementiert.
2. **Bedingter `bull_color`-Default:** Ein statisches Schema kann den dual_color-abhängigen Default nicht ausdrücken. **Vertrag:** `get_ma_parameter_schema()` liefert `"default": "#2196F3"`; der Konsument wendet `"#26A69A"` an, wenn `dual_color=True` UND `bull_color` nicht vom User gesetzt wurde (leer/None). `build_color_series()` erhält die final aufgelösten Farben als Parameter.
3. **`build_chart_payload`-Vertrag:** Zeilen mit NaN/None in `time` oder `value` werden übersprungen (Warmup); `time` = int epoch-Sekunden (Wanduhr), `value` = float, `color` = String. Ein Längen-Mismatch (`len(colors) < len(ma_series)`) wird defensiv toleriert (fehlende Farbe → Default bull_color).
4. **KAMA/ALMA/RMA-Details:** KAMA nutzt `period` als ER-Periode (Default 10) mit Standard fast `2/(2+1)` und slow `2/(30+1)`; `alpha_factor` entfällt bei KAMA. ALMA nutzt TradingView-Defaults (Offset 0.85, Sigma = `period/6`). RMA = Wilder: `ewm(alpha=1/period, adjust=False)`.
5. **VWMA-Nullschutz:** Volumen wird mit `fillna(0)` normalisiert; ist die rollierende Volumen-Summe eines Fensters ≤ 0, fällt dieses Fenster auf den SMA-Wert zurück (kein Division-by-Zero).
6. **Testabdeckung `test/test_ma_template.py`:** Längen-/Paritätsprüfung aller 12 Typen gegen eine einfache Referenzimplementierung (defensive Formeln), Farbumschlag (E6), `VWMA` mit `tick_volume` aus `market_data.duckdb` (read-only via `DbPool`, nur Lesen – keine Schreibzugriffe auf `data/`), NaN-Filter von `build_chart_payload`, VWMA-Fallback (E5), Warmup-Länge = `period-1`.

---

## Implementierungs-Log Phase 16.04 (06.08.2026 21:09)

**Schritt 1–3 – Modul erstellt (`chart/indicators/utils/ma_template.py` + `utils/__init__.py`):**
* `MAType`-Literal + `MA_TYPES`-Tuple (12er-Satz, E2), `MATemplateEngine` (stateless, ohne Engine-Abhängigkeiten).
* `get_ma_parameter_schema()` – 7 Parameter in Projekt-Schema-Konvention (`choice`/`int`/`float`/`bool`/`color`, `style_type`), Defaults nach E3.
* `resolve_bull_color()` – bedingter bull-Default (E7/Ergänzung 2): Schema `#2196F3`, dual=True + ungesetzt → `#26A69A`.
* `crop_dataframe()` – `df.tail(max_limit)`, `calculate_ma()` – alle 12 Typen vektorisiert (SMA/WMA/HMA/ALMA/VWMA via np.convolve, EMA/RMA/DEMA/TEMA/EHMA via pandas ewm, KAMA ER-basiert mit kompakter Schleife, ZLEMA mit lag), α-Pfad nach E4.
* `build_color_series()` – dual_color-Semantik (E6), NaN-Vergleich = bull. `build_chart_payload()` – LWC-v5-Array, NaN/Inf-Skip (Warmup), Mismatch-Toleranz (Ergänzung 3).
* **Bugfix-Faltung:** `np.convolve` wendet Gewichte rückwärts an – `_wma_values` nutzt daher absteigende Gewichte `[p..1]`, `_alma_values` faltet `weights[::-1]` (Parität zur Referenzschleife).
* **pandas-3.0-Kompatibilität:** `ewm(...).to_numpy()` liefert read-only Arrays → `_ema_alpha/_ema_span/_rma` liefern beschreibbare Kopien (wichtig für ZLEMA-Warmup-Overwrite).

**Schritt 4 – Backend-Logiktest (`test/test_ma_template.py`, temporär):**
* **61/61 Checks PASS** – Schema-Defaults & resolve_bull_color (S1–S12), Länge/Warmup aller 12 Typen (L1/L2, typspezifisch tolerant: EWM-Typen seeden ab Index 0), volle Parität aller 12 Typen gegen defensive Referenzimplementierung (P1, period=10), VWMA mit echten `tick_volume`-Daten aus `market_data.duckdb` (D1–D3, weicht vom SMA ab), VWMA-Fallback exakt SMA (E5), Null-Volumen-SMA-Fallback (E5b), Farbumschlag (C1–C3), Payload-Vertrag (Q1–Q5), crop/Edge-Cases (R1–R4).
* Verifikation: `python -m py_compile` auf Modul + `utils/__init__.py` + Test → OK; Import-Smoke `chart.indicators.utils.ma_template` → OK.

**Cleanup (Invariante 10):** `test/test_ma_template.py` wird erst nach bestätigter Freigabe des Kapitels entfernt (Verifikation erfolgte VOR der Bereinigung). Dauerhaft bleibt nur `test/test.py`.

---

