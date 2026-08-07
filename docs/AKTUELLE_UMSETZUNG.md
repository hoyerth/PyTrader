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
# Kapitel 16.07: Two-Tier Caching & Dynamic Range Management

## 1. Executive Summary & Zielsetzung
Zweistufige Datenarchitektur (**Two-Tier Caching**), die das Laden und Berechnen historischer Marktdaten (OHLCV) und Indikator-Overlays beim Scrollen in die Vergangenheit entkoppelt. Sie kombiniert minimale JS-Render-Last im Chart (Tier 1) mit einem erweiterten RAM-Datenpuffer im Python-Backend (Tier 2), um nahtloses, latenzfreies Scrollen ohne Performance-Einbußen zu gewährleisten.

---

## 2. Die Zwei-Stufen-Architektur (Two-Tier Concept)

* **Tier 1: Frontend Render Window (JS / LWC v5)**
  * **Umfang:** Hält strikt nur das aktive Darstellungsfenster (z. B. $N = \text{chart\_candle\_limit} \approx 1.000$ Kerzen) im DOM/Canvas.
  * **Aufgabe:** Gewährleistet flüssiges Rendering mit 60 FPS ohne Memory-Leaks.
  * **Verhalten:** Erhält synchrone, bereits berechnete Gesamt-Pakete (OHLCV-Candles + fertige Indikator-Payloads) direkt von Python per JS-Bridge.

* **Tier 2: Backend Memory Buffer (Python / `MATemplateEngine` & FeatureBuilder)**
  * **Umfang:** Puffert ein erweitertes Historien-Fenster im RAM (z. B. $M = N \cdot 10 \approx 10.000$ Kerzen).
  * **Aufgabe:** Führt Indikator-Berechnungen durch und bedient Nachlade-Anfragen des Frontends verzögerungsfrei (0 ms I/O-Latenz).
  * **Storage Fallback:** Lädt asynchron Blöcke aus `market_data.duckdb` (`ohlcv_bars`) nach, sobald der Tier-2-RAM-Puffer nach links erschöpft ist.

---

## 3. Dynamisches Nachladen, Warmup & Range Management

[ DuckDB Storage ] ──(Async Chunk)──> [ Tier 2: RAM Buffer (10.000) ] ──(Sliding View)──> [ Tier 1: JS Canvas (1.000) ]
│                                       │
[DB-Lookback]                           [Warmup Vorlauf]



1. **Sliding Window Shift (Tier 1 ↔ Tier 2):**
   * Das Frontend überwacht den Scroll-Rand via `visibleLogicalRangeChanged`.
   * Nähert sich die Viewport-Position dem linken Rand ($< 100$ verbleibende Kerzen im Canvas), fordert JS per Bridge den nächsten Daten-Ausschnitt aus dem Tier-2-RAM-Puffer an.
   * Der sichtbare Bereich in JS wird unter Beibehaltung der `visibleLogicalRange` nahtlos aktualisiert, ohne dass der Chart springt.

2. **Backend Chunk Fetch (Tier 2 ↔ DuckDB):**
   * Erreicht der Tier-1-Viewport die $20\%$-Grenze des Tier-2-RAM-Puffers, stößt Python im Hintergrund (QThread) das Nachladen des nächsten Chunks aus `market_data.duckdb` an.
   * DB-Fetches werden bei schnellem Scrollen debounced (300 ms).

3. **Lookback / Warmup Buffer (Mathematische Nahtstellen-Garantie):**
   * Zur Vermeidung von Indikator-Verzerrungen (z. B. bei rekursiven Alpha-EMAs / EHMA / Smoothed MA) liest Tier 2 aus DuckDB immer eine erweiterte Historie aus:
     $$\text{Warmup-Vorlauf} = \text{period} \cdot 4 + \text{smoothing} \cdot 3$$
   * Dieser reine Warmup-Vorlauf wird für die mathematische Einschwingphase genutzt und danach verworfen; nur valide Indikator-Punkte fließen in den Tier-2-Puffer und an Tier 1.

4. **Live-Tick-Entkopplung bei Historien-Ansicht:**
   * Befindet sich der Anwender in der Historie (nicht am rechten Rand), aktualisieren eingehende Live-Ticks den Tier-2-Puffer im Hintergrund, verändern jedoch nicht den aktiven Historien-Viewport in Tier 1.

---

# Kapitel 16.07 – Review & Finale Entscheidungen (07.08.2026, kritische Prüfung gegen Ist-Code)

> **Status:** Kapitel 16.07 ist ein **Konzept/Plan**, keine Umsetzung. Stand heute existiert im Code **keine** Two-Tier-Architektur, kein RAM-Puffer, kein Chunk-Nachladen, kein Sliding Window. Die Entscheidungen **D1–D10 sind final** (Anwender-Review, 07.08.2026) und verbindlich für die Umsetzung. **Coding startet erst nach ausdrücklichem Startbefehl des Anwenders.**

## 1. Konsistenz mit dem Ist-Code (Abweichungen)

1. **`N ≈ 1.000` vs. `chart_candle_limit = 3000`:** Der Ist-Code lädt exakt `settings.chart_candle_limit` Kerzen (`chart/chart_win.py:790`), Default **3000** (`config/app_settings.py:17`, `properties_win.py:47`). Das Kapitel nennt "z. B. ≈1.000" – es ist zu entscheiden, ob `N` die **bestehende** Einstellung (`chart_candle_limit`) ist oder eine neue Konstante entsteht (und wie die Properties-UI das abbildet).
2. **`M = N·10 ≈ 10.000`:** Es gibt **keinen** RAM-Puffer. Aktueller Ablauf: `fetch_historical_candles(..., limit=chart_candle_limit)` → kompletter Chart-**Rebuild** je Refresh (`applyFullChartUpdate`: `chart.remove()` + `createChart` + `setData`). Verortung/Zuständigkeit von `M` (ChartWindow? FeatureBuilder? `MATemplateEngine`?) ist offen.
3. **Warmup-Formel `period·4 + smoothing·3`:** Der Ist-Code (`chart/indicators/utils/ma_template.py`) definiert Warmup als **`period−1` NaNs** (Zeilen 221–223, 424) – die Formel ist also **neu** und ändert potenziell die Indikator-Semantik (Einschwingverhalten). Zudem deckt sie nur MA-artige Indikatoren ab; `FixedGridProximity`/`custom_levels` haben kein `smoothing`. Zu klären: Ist der Warmup-Vorlauf **nur Lese-Vorlauf für die Berechnung** (verworfen) oder verändert er das bisherige NaN-Vertragsverhalten?
4. **Bridge-Vertrag fehlt:** `ChartBridge` (`chart/chart_win.py:92–99`) kennt nur `onRangeChanged` / `onPriceRangeChanged` / `measurementChanged`. Das Kapitel verlangt "fordert JS per Bridge den nächsten Daten-Ausschnitt an" – **kein Slot/kein Payload-Vertrag definiert** (Namen, Parameter, Antwortformat, updateId-Guard analog `_updateId`).
5. **Schwellwerte "100 Kerzen / 20% / 300 ms":** Keine Konstanten definiert, kein Ort (Python oder JS) benannt.
6. **Sliding Window ≠ Ist-Architektur:** Ein nahtloses Sliding-Window erfordert JS-seitiges **inkrementelles Hinzufügen/Entfernen** von Candles/Serien ohne Chart-Rebuild sowie eine über Chunk-Grenzen **konsistente** `_continuousTimeMap`/`_continuousKeys` (aktuell bei jedem `applyFullChartUpdate` neu aufgebaut). Das ist eine erhebliche JS-Architekturänderung (`01_core.js`/`03_chart_rendering.js`/`04_live_updates.js`), die im Kapitel nicht adressiert ist.

## 2. Vollständigkeit – fehlende Aspekte

1. **Indikator-Neuberechnung beim Nachladen:** Neue ältere Kerzen → `price_lines`, `hit_circles`, `DaySeparator`, Live-Overlays, LineSeries-Registry (`_activeLineSeries`) müssen für den erweiterten Bereich **neu berechnet und nahtlos ergänzt** werden. Trigger/Zyklus fehlt.
2. **Race-Conditions:** Veraltete Chunk-Antworten (analog zum bestehenden `updateId`-Guard), Symbol/TF-Wechsel während eines laufenden Chunk-Loads, doppelte Requests bei schnellem Scrollen – kein Konzept.
3. **Linker Rand / DB-Ende:** Verhalten, wenn keine älteren Daten existieren (Stop-Flag, kein Endlos-Loop).
4. **Handelspause & Wochenend-Lücke:** Chunk-Grenzen können mitten in der Pause (Wanduhr 23:00–23:59) oder der Wochenend-Lücke liegen. Die Invarianten "keine leeren Candles / keine Lückenfüller" und `resolveRealTime`/`formatDT` müssen über Chunk-Grenzen hinweg gelten (kontinuierliche Zeitachse).
5. **Live-Tick-Entkopplung (Punkt 4):** Nur als Satz beschrieben – es fehlt, wie der rechte Rand (Puffer-Wachstum, Sync), der Rücksprung ans Live-Ende und der Konflikt "Historie-Viewport vs. neuer Tick" konkret gelöst werden.
6. **Restore:** `visible_from`/`visible_range_from` (`chart_win.py:241/265`, State-Persistenz) müssen bei einem Sliding-Window in **Chunk-/Offset-Koordinaten** übersetzt werden.
7. **Verifikation & Zielgrößen:** Kein Testkonzept (headless), keine Performance-Zielwerte (FPS, Latenz, Speicher), kein Migrations-/Cleanup-Plan (Regel 10).

## 3. Finale Entscheidungen D1–D10 (verbindlich für die Umsetzung)

### D1: Größe `N` (Tier-1-Renderfenster) → **fix 1.000 Kerzen**
* **Kritik (teilweise):** 3.000 Kerzen gleichzeitig im DOM/Canvas von LWC v5 sind performant, aber als Render-Fenster für flüssiges 60-FPS-Scrolling unnötig groß.
* **Entscheidung:** $N = 1.000$ als **festes Tier-1-Renderfenster** (Canvas) für maximale JS-FPS und flüssiges Wischen.
* `chart_candle_limit` (3.000, `AppSettings`/`PropertiesWindow`) dient ab jetzt nur noch als **Sichtbarkeits-Standard beim initialen Öffnen** eines Charts – es steuert **nicht mehr** die obere harte Render-Grenze des Tier-1-Puffers.

### D2: Größe & Verortung `M` (Tier-2-RAM-Puffer) → **eigene Engine-Klasse `ChartDataBuffer`**
* **Kritik (SRP-Verstoß):** `PyTraderChartWindow` ist ein PySide6-UI-Fenster. Laut **Rule 2.3 (SRP)** gehören mathematische Datenpuffer und schwere DataFrames **niemals** in eine UI-Klasse.
* **Entscheidung:** Kapsele den Tier-2-Puffer in einer eigenen, zustandslosen Engine-Klasse **`ChartDataBuffer`** (unter `chart/chart_basics.py` oder `chart/indicators/utils/`). `PyTraderChartWindow` hält nur eine **Referenz** auf dieses Backend-Puffer-Objekt.
* **Größe:** $M = 10.000$ Kerzen (Faktor 10) – perfekt (~5 MB RAM pro Chart), entlastet DuckDB hervorragend.

### D3: Trigger Nachladen → **JS-Request über die Bridge**
* **Kritik (vollkommen richtig):** Nur Lightweight Charts kennt den exakten Pixel-/LogicalRange-Scrollstand des Anwenders.
* **Entscheidung:** JS ruft über die `QWebChannel`-Bridge eine Python-Slot-Methode auf, sobald der Rand erreicht wird.

### D4: Bridge-Vertrag → **Slot `request_older_data(from_time_epoch, count)`**
* **Korrektur:** Der Slot heißt `request_older_data(from_time_epoch, count)` – **zeitbasierte Abfragen (Epoch-Wanduhr)** sind robuster gegen Chart-Indizes.
* **Entscheidung:** Antwort-Payload mit `updateId`, `candles`, `timeMapDelta`, `chartRenderPayloadDelta`. `updateId` + Delta-Payloads sind essenziell gegen Race-Conditions bei schnellem Wischen (Debounce).

### D5: Indikator-Berechnung pro Chunk → **vollständige Tier-2-Neuberechnung auf `M`**
* **Kritik (Gold-Standard):** Vektorisierte NumPy/Pandas-Berechnungen über 10.000 Kerzen dauern in Python nur wenige Millisekunden (z. B. `< 5 ms` für EHMA/Multi-MA). Synchrone inkrementelle „Nahtstellen-Flickerei" wäre fehleranfällig und komplex.
* **Entscheidung:** Die Mathe in Tier 2 rechnet das Gesamtfeld $M$ **vektorisiert neu**; nur der JS-Ausschnitt bleibt inkrementell.

### D6: Warmup-Formel → **reiner Lese-Vorlauf, nur für Gleitdurchschnitts-Indikatoren**
* **Kritik (sehr durchdacht):** Grid- & Proximity-Indikatoren benötigen **keinen Warmup-Vorlauf** ($\text{Warmup} = 0$), da Preis-Raster rein statisch auf dem aktuellen Preis berechnet werden.
* **Entscheidung:** Die Formel $\text{Warmup} = \text{period} \cdot 4 + \text{smoothing} \cdot 3$ greift **ausschließlich** bei Indikatoren mit zeitlichen Gleitdurchschnitten (Multi-MA, EHMA, Volatilitäts-MAs). Der Vorlauf ist **reiner Lese-Vorlauf** (verworfen, NaN-Vertrag `period−1` bleibt unverändert).

### D7: Schwellwerte → **100 Kerzen / 20% / 300 ms, geteilte Verantwortung**
* **Entscheidung:** JS überwacht den Rand (`< 100` verbleibende Kerzen) und **debounct** Mehrfach-Trigger mit **300 ms**. Python debounct **zusätzlich** den DuckDB-I/O-Fetch, falls sehr schnell gewischt wird.

### D8: DB-Ende & Datenlücken → **`has_more_history`-Stop-Flag**
* **Entscheidung:** Liefert DuckDB **0 neue Zeilen**, setzt Python `has_more_history = False`; JS stellt weitere Nachlade-Requests am linken Rand ein (kein Endlos-Loop).
* **Wanduhr-Pausen/Wochenende:** Dank `resolveRealTime()` (`01_core.js`) und Wanduhr-Epochs werden historische Pausen (23:00–23:59) und Wochenend-Lücken ohne Phantom-Index-Slots gerendert.

### D9: Live-Ticks vs. Historie-Viewport → **Viewport fix, stummer Puffer-Update, „Live"-Button**
* **Entscheidung (Exzellente Trading-UX):** Eingehende M1-Bar-Closes (`LiveAnalyzer`) schreiben die neue Kerze ans **rechte Ende** von Tier 2. Scrollt der User in der Historie (Tier-1-Ausschnitt nicht am rechten Rand), wird `updateLiveCandle()` in JS **unterdrückt oder nur stumm im Speicher aktualisiert**, damit der Scroll-Fokus nicht zuckt. Ein dezenter **„Live"-Button** im Chart springt bei Klick an den aktuellen Rand.

### D10: Restore / Window Geometry & State → **offsetbasiert relativ zum rechten Rand**
* **Entscheidung:** Da im Hintergrund ständig neue Ticks hinzukommen, verändern sich absolute Bar-Indizes. Der Restore (`visible_from`/`visible_range_from`) erfolgt als **zeit-/offsetbasierter Offset relativ zum rechten Rand** (Chunk-Koordinaten), umbruchfest – beim Wiederöffnen wird exakt derselbe Wochentag/Ausschnitt geladen.

> **Zusammenfassung (Anwender-Urteil):** Die Vorschläge sind bis auf die **Verortung von Tier 2 (D2: heraus aus UI, hinein in eine Buffer-Klasse)** und die **Klarstellung der N-Größe (D1: N=1000 Canvas)** perfekt durchdacht. Die Verträge zur zeitzonenfreien Wanduhr-Formatierung, die Entkopplung von Background-Workern und der Erhalt aller OOP-Prinzipien sind lückenlos gewahrt.
>
> **Kein Coding:** Die Entscheidungen sind dokumentiert. Eine Umsetzung von 16.07 erfolgt erst nach ausdrücklichem Startbefehl des Anwenders. *(Inzwischen erfolgt – siehe unten: Implementierungs-Log 16.07, 07.08.2026.)*

---
# Kapitel 16.07 – Implementierungs-Log (07.08.2026, 12:56 Uhr)

> **Status:** Kapitel 16.07 ist **umgesetzt** (D1–D10, siehe Review oben). Implementierungs-Log gemäß Regel 0c – Datum/Uhrzeit 07.08.2026 12:56 Uhr. Verifikation headless (Regel 4: keine UI-Tests, keine Regressionstests) über `test/test.py` Teil 12 (P16.07) sowie `py_compile`/`node --check` auf allen geänderten Dateien.

## 1. Umgesetzte Architektur (Ist-Stand)

* **Tier 1 (JS-Renderfenster):** fest **N = 1.000** Kerzen (`TIER1_WINDOW`, D1). `chart_candle_limit` (3.000) steuert nur noch den initialen Sichtbarkeits-Standard beim Öffnen, nicht die harte Render-Grenze.
* **Tier 2 (RAM-Puffer):** eigene Backend-Engine-Klasse **`ChartDataBuffer`** (D2, SRP – Rule 2.3), `TIER2_CAPACITY = 10.000`. `PyTraderChartWindow` (PySide6-UI) hält nur eine Referenz; schwere DataFrames/Zeit-Maps leben ausschließlich im Puffer.
* **Nachlade-Trigger:** JS-Seite über die QWebChannel-Bridge (D3): `olderDataRequested(from_epoch, count, request_id, window_right)`.
* **Bridge-Vertrag (D4):** Python-Slot liefert Delta-Payload `{updateId, symbol, timeframe, candles, timeMapDelta, windowRightEpoch, hasMoreHistory, chartRenderPayloadDelta}`; `updateId`-Guard gegen Race-Conditions (analog `_updateId`).

## 2. Umsetzung D1–D10 im Detail

* **D1 (N=1000):** `ChartDataBuffer.TIER1_WINDOW = 1000`; `window_candles()` liefert die letzten N served Kerzen kont-zeit-gemappt; `_do_refresh_chart_data()` sendet nur `window_candles(TIER1_WINDOW)` an JS.
* **D2 (M=10000):** `chart/indicators/utils/chart_data_buffer.py` (NEU). In-place-Erhalt der cont-Zeit-Maps (`time_cont_to_real`/`time_real_to_cont` – ChartWindow hält gültige Referenzen), Sliding-Window-Trim rechts bei Kapazitätsüberschreitung (rechteste/neueste Kerzen werden samt Map-Einträgen verworfen).
* **D3 (JS-Trigger):** `chart/js/06_two_tier.js` (NEU) überwacht `visibleLogicalRange`; `< 100` Kerzen links → debounced (300 ms) `onRequestOlderData(leftReal, 1000, serial, rightReal)`. Live-Erkennung über `_isHistoryView()` (D9).
* **D4 (Bridge/Slot):** `ChartBridge.olderDataRequested` → `_on_older_data_requested` (Debounce-Timer 300 ms) → `_do_older_data_load`: Priorität 1 = RAM-Serve aus `ChartDataBuffer.serve_older()` (0 ms I/O, D3/D4), Priorität 2 = `OlderDataWorker` (QThread) mit `before_epoch`-DB-Fetch. Antwort via `_send_older_chunk` (Delta-Payload).
* **D5 (vektorisierte Neuberechnung):** `merge_older()` baut `df = warmup + served` vollständig neu; `_apply_data_window_size()` setzt das Multi-MA-Fenster; nur der JS-Ausschnitt bleibt inkrementell (`applyOlderDataChunk` mit `candleSeries.setData` OHNE `chart.remove/createChart`; Render-Delta via `renderLineSeries`/`renderMarkers`/`DaySeparator.render`).
* **D6 (Warmup):** `_compute_warmup()` = `max(period*4 + smoothing*3)` **nur über aktive MAs** (Grid/Proximity: 0). `ChartDataBuffer` hält den Vorlauf als `_warmup_candles` (reiner Lese-Vorlauf, verworfen – NaN-Vertrag `period−1` unverändert).
* **D7 (Schwellwerte):** 100 Kerzen / 20% / 300 ms – JS-Debounce (`OLDER_REQUEST_DEBOUNCE_MS=300`) + Python-Debounce (`_older_debounce_timer`) für den DB-Fetch.
* **D8 (DB-Ende):** `has_more_history=False` bei 0 neuen Zeilen (`merge_older` leerer Fetch); JS stellt Nachlade-Requests ein. Pausen/Wochenende bleiben dank `resolveRealTime()`-Wanduhr-Handling korrekt.
* **D9 (Historie-Viewport):** `updateLiveCandle()` bricht ab, wenn `window._isHistoryView()` (stummer Puffer-Update); dezenter **„Live"-Button** (`#live-button` in `chart/chart_basics.py`) springt per `jumpToLiveRequested` an den rechten Rand.
* **D10 (Offset-Restore):** `syncRanges` sendet `totalBars` als 3. Argument; `handle_range_changed` speichert Offsets relativ zum rechten Rand (`visible_from = total - from`, `visible_to = total - to`); `_resolve_visible_logical_range(total)` stellt sie umbruchfest wieder her (Offset-Format from>to; Alt-Format wird geklemmt).

## 3. Geänderte / neue Dateien

| Datei | Änderung |
|---|---|
| `db_service.py` | `fetch_historical_candles(..., before_epoch=None)` additiv (WHERE `"time" < to_timestamp(?)`) – Chunk-Fetch für ältere Daten (D4) |
| `chart/indicators/utils/chart_data_buffer.py` | **NEU:** `ChartDataBuffer` (D2) – load_initial/serve_older/merge_older/window_candles, cont-Maps, Warmup, Kapazitäts-Trim |
| `chart/indicators/multi_ma.py` | `set_data_window_size(n)` + `_get_candle_limit()`-Fallback (Tier-2-Fenster für D5) |
| `chart/chart_win.py` | ChartBridge-Erweiterung (rangeChanged/olderDataRequested/jumpToLiveRequested), `OlderDataWorker`, Two-Tier-Refresh, `_compute_warmup`, `_resolve_visible_logical_range`, `_collect_render_payload`-Zeitfenster-Filter, Delta-Payload-Sendung |
| `chart/js/06_two_tier.js` | **NEU:** Rand-Trigger, Debounce, `applyOlderDataChunk`, Viewport-Stabilisierung, Live-Button-Logik (D3/D7/D8/D9) |
| `chart/js/04_live_updates.js` | additiv: `syncRanges` mit totalBars, `_isHistoryView`-Guard, Hooks `_onFullChartUpdateApplied`/`_onVisibleRangeChanged` |
| `chart/chart_basics.py` | `#live-button`-CSS + Button-HTML; `JS_FILES` += `06_two_tier.js` |

## 4. Verifikation (headless, 07.08.2026)

* `py_compile` auf allen geänderten Python-Dateien → EXIT=0.
* `node --check` auf `02_time_utils.js`/`03_chart_rendering.js`/`04_live_updates.js`/`06_two_tier.js` → EXIT=0.
* `test/test.py` (offscreen, venv, UTF-8): **Teil 12 (P16.07) alle 28 Checks PASS** – T1 `before_epoch` (additiver Chunk-Fetch, älteste Kante → 0 Kerzen), T2 `load_initial`/Tier-1-Fenster/cont-Maps (bijektiv, lückenlos), T3 RAM-Serve + Erschöpfung, T4 `merge_older` Prepend/cont-Erhalt/Trim (Sliding-Window entfernt rechteste Kerze samt Map-Eintrag; verbliebene Alt-Kerzen behalten cont)/Warmup/`has_more_history` (D8), T5 `_compute_warmup` (nur aktive MAs, D6), T6 `_resolve_visible_logical_range` (D10 Offset-/Alt-Format, Klemmen), T7 Render-Payload-Zeitfenster-Filter (D1/D5).
* Teile 1–11 unverändert grün; weiterhin exakt **6 vorbestehende ServiceWindow-Fails** (P2/P5/H3/H4/H5/H7 – dokumentiert in E6, betrifft `serviceui/service_win.py` unverändert).
* Temporäre Test-Artefakte (`test/_tmp_p1607`, `test_stderr.txt`) nach Abschluss entfernt (Regel 8/10).
* Keine UI-Tests / keine Regressionstests ausgeführt (Regel 4).

## 5. Offene Punkte (bewusst, nicht Teil dieser Umsetzung)

* Performance-Messung JS-seitig (FPS/Latenz unter realer Last) – manuelle Verifikation durch den Anwender in der GUI.
* `_pending_older`-Auflösung bei Symbol-/TF-Wechsel mitten im Chunk-Load (durch `updateId`-Guard abgesichert, Verhalten beibehalten).
