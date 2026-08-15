# Phase 22: Fachliche Feinabstimmung Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 22)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase22_step1`, `phase22_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte Python-Skripte im Unterordner `test/` (kein PyTest im Projekt; primär `test/test.py`-Harness plus fokussierte `check_*.py`-Validator).
3. **Codebase-Formatierung:** Exakt **4 Leerzeichen** Einrückung (PEP8-Standard) und **exakt 1 Leerzeile** Spacing zwischen Methoden und Funktionsblöcken. Kein Umformatieren unbeteiligter Altbestand-Dateien.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`. `MasterTree`-Selektionen übergeben aufgelöste `feature_ids` sowie `instance_hashes` direkt an `view_model.set_feature_ids(ids, hashes)`.
5. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`db/db_pool.py`) – eine Verbindung pro Thread und DB-Datei. Die Fassade `db_service.py` bleibt als Re-Export-Wrapper für bestehende Caller erhalten.
7. **Tree-Persistenz & Kategorisierung:** 
   - Service-Kategorien werden primär im Code/Plugin über `metadata["category"]` (Slash-separierter Ordnerpfad) deklariert.
   - Ordner-Kategorien für Service-Sets werden im `category`-Feld der `ServiceSetDefinition` / des `save_set()`-Payloads persistiert.
   - Parameter-Varianten (Clones/Presets) werden transparent über `indicator_presets` und `instance_hash` im FeatureStore geführt.
8. **Wanduhr-Garantie (Invariante 7):** MT5-Epochs sind bereits Berlin-Wanduhr-encoded. SQL-Extraktionen (Heatmap, DOW, Hour, Date) nutzen strikt `bar_time AT TIME ZONE 'UTC'`, um eine fehlerhafte automatische Umrechnung durch DuckDB in Lokalzeiten zu unterbinden.
9. **Concurrency-Guard & Timer-Pausierung:** Solange im ServiceWindow intensive Service-Berechnungen laufen (`ServiceRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
10. **Isolierter Test-Workspace & Cleanup:** Neue Test-Skripte und temporäre `*.duckdb`-Dateien gehören strikt nach `test/` (Ordner ist gitignored). Der Test-Harness `test/test.py` (alle Block-Tests) und wiederverwendbare fokussierte Validatoren `check_*.py` verbleiben dort. Nach Abschluss jedes Phasenkapitels werden nur temporäre Artefakte aufgeräumt: Test-Datenbanken (`*.duckdb`/`*.wal`), `tmp_*`-Dateien und Cache-Ordner.
11. **Open/Closed-Principle & Code-Preserving:** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden; bestehende Kern-Klassen bleiben geschützt.
12. **Naming Conventions & PineScript-Input-Zone:** 
    - Services in `analytics/features/definitions/` nutzen strikt das Präfix `srv_` (`plugin_id = "srv_..."`).
    - Indikatoren in `chart/indicators/` nutzen strikt das Präfix `ind_` (`indicator_id = "ind_..."`).
    - Füllwörter (`service`, `plugin`, `indicator`) entfallen im Dateinamen.
    - Das `parameter_schema` liegt direkt am Dateianfang unter dem Header-Docstring.
    - Jedes Service-Plugin deklariert `metadata["category"]` für die dynamische Kategorie-Ordner-Struktur im MasterTree.

---

# 22.01 Spezifikation: `ind_peak` & Peak-Grabber (PyTrader Engine)

---

## 0. Review-Ergebnis & Entscheidungen (14.08.2026)

Das Review der Erstfassung (Review-Textblock vom 14.08.2026) ergab **7 harte Bugs (B1–B7)**, **fehlende Pflicht-Sektionen** und **Konventions-Verstöße**. Das Kapitel wurde als durchgehendes Konzept neu gefasst – die Entscheidungen zu den 7 Review-Fragen und die integrierten Bugfixes sind unten verbindlich.

### 0.1 Entscheidungen zu den Review-Fragen

1. **Plugin-Services statt isolierter Klassen:** `srv_peak_finder` und `srv_peak_grabber` werden **echte Plugin-Services** in `analytics/features/definitions/` (erben von `PluginFeature`, **zustandslos**, `calculate(df, params, context)`). Die zustandsbehaftete Live-State-Machine wird als Helper-Klasse `PeakGrabberLiveState` **direkt im Indikator** `ind_peak` implementiert (Muster `ind_fixed_grid_proximity`: Live-Pfad ohne Pipeline, Open/Closed). Eine Ausnahme-Regel ist damit nicht nötig.
2. **`ind_peak` vollständig in `BaseIndicator` integriert:** volle Indicator-API (`indicator_id`, `display_name`, `default_params`, `parameter_schema`, `calculate`, `update_live_candle`, `get_live_overlays`, `remember_live_time`) → erscheint im Prop-Dialog und wird vom ChartWindow generisch getrieben (kein Sonderfall).
3. **`is_yellow_window`-Ableitung (direkt im Service implementiert, Frage 3):**
   `is_yellow_window := is_in_proximity_zone ∧ is_in_time_window(±5 min um :00/:30)` (Wanduhr, Präambel 8).
   * `is_in_time_window`: Wanduhr-Minute der Bar in `[0±5]` oder `[30±5]` (Muster `_f_in_window_around`, srv_proximity).
   * `is_in_proximity_zone`: Preis trifft eine Proximity-Zone (`levels_hit` ≠ leer) – Zone-Hit-Daten je Bar kommen aus der `srv_proximity`-Instanz im `context.shared_state` (depends_on).
   * **Fallback `True`:** Fehlt das Proximity-Signal im Context (kein Zone-Hit-Datensatz), gilt `is_in_proximity_zone := True` (Gate offen).
   Batch: Der Service `srv_peak_grabber` leitet das bool-Array je Bar selbst her (§4B `_derive_yellow_window`). Live: Yellow-Flag der aktuellen Bar analog (letzter Proximity-Record, Fallback `True`).
4. **Outcome-Evaluator NICHT in 22.01 (Frage 4):** Die Spalten `outcome_status`, `pnl_r_multiple`, `max_favorable_exc`, `max_adverse_exc` werden im Schema angelegt und initial mit `'PENDING'` / `NULL` befüllt. Die dedizierte Exit-/Forward-Evaluation (TP/SL-Simulation) folgt als **separates Auswertungs-Modul in einem späteren Kapitel** – `PeakGrabberConfig.take_profit_r` / `max_hold_bars` bleiben als reservierte (dokumentierte) Felder für dieses Modul erhalten und werden in 22.01 **nicht** ausgewertet.
5. **Button-Anbindung im AnalyticsWindow (Frage 5):** primär `analytics/ui/analytics_win.py` (Alternative: Chart-Overlay-Controlbar). Kommunikation über **neue EventBus-Signale** – angepasst an das bestehende `Signal`-Attribut-Muster des EventBus (kein String-`emit`):
   `grabber_toggle = Signal(dict)` mit Payload `{"active": bool, "symbol": str, "timeframe": str}` und `grabber_event = Signal(object)` (`GrabberResultRecord`). `chart_win` subscribed `grabber_toggle` generisch und ruft `set_button_active(active)` auf allen Indikatoren mit diesem Hook auf (IoC, kein Hardcoding). Order-Vorschau: `analytics/ui/order_preview_dialog.py` (`OrderPreviewDialog`, PySide6-Modal, **keine Order-Platzierung**, **kein SQL in UI** – MVVM, Präambel 4). **Zusätzlich (14.08.2026):** Das ChartWindow erhält einen eigenen **aufrufenden Button** `btn_peak_grabber` (§9.5), der denselben `grabber_toggle`-Payload emittiert – beide Buttons laufen über **einen** Routing-Pfad (§9.3), kein Sonderfall im ChartWindow.
6. **DDL-Ort (Frage 6):** `grabber_test_results` wird **additiv in `db/schema_initializer.py`** (`check_and_init_databases()`, analytics.duckdb) registriert – das ist die tatsächliche Schema-Init-Stelle im Code (zusätzlich zu `state_manager.py`-Initialisierung). Schreibzugriff **ausschließlich** über `repositories/grabber_repository.py` (DbPool-Muster, kein manuelles `close()`, Präambel 6).
7. **Naming:** `ind_peak` (klein, Konvention 16.08.01). Services `srv_peak_finder` / `srv_peak_grabber`. Keine neuen Top-Level-Ordner `services/`, `models/`, `bridge/` – Einordnung in bestehende Pakete (siehe §2.1).

### 0.2 Integrierte Review-Bugfixes (B1–B9)

| ID | Finding | Fix im Kapitel |
|----|---------|----------------|
| B1 | INSERT nur 17 Werte vs. 18 Tabellenspalten (`max_adverse_exc` fehlt) → DuckDB-Mismatch | §2.3 DDL 18 Spalten; §7 Repository-INSERT mit exakt 18 Spalten |
| B2 | Kernel startet `ARMED(1)` bei `gate_active`, Live startet `IDLE(0)` → Backtest ≠ Live | §3.1/3.2 IDLE-Start; Bar 0 = Bootstrap (First-Peak-Skip), Live äquivalent |
| B3 | Live berechnet `bars_h` **nach** `update_scalar()` → immer 0 bei neuem High (toter `else`-Zweig) | §4C VOR `update_scalar()` sichern; Alter des **vorherigen** Peaks (Parität zu Kernel) |
| B4 | `bootstrap_history` setzt keinen Scalar-State → Live-SL-Linie startet inkonsistent | §5 `_bootstrap_live_state` übernimmt Batch-Endwerte in den `PeakFinderLive`-Scalar-State |
| B5 | `np.roll` in `on_bar_close` ist O(n)-Kopie → widerspricht Zero-GC | §5 Ringpuffer mit zirkulärem Index (kein `np.roll`) |
| B6 | Division-by-Zero bei `prev_h`/`peak_l` = 0 (Exoten-Symbole) | §3.2 Kernel-Guards + §4C Live-Guards (NaN-Schutz) |
| B7 | `timestamps[idx].astype(datetime)` fragil | §7/§8 `pd.Timestamp(...).to_pydatetime()` |
| B8 | Tabs statt 4 Leerzeichen (Präambel 3) | Alle Code-Blöcke in diesem Kapitel: exakt 4 Leerzeichen |
| B9 | Keine MasterTree-/Varianten-Integration (Präambel 7) | `metadata["category"]` + `indicator_id` je Service; `instance_hash` via ServiceSet-Evaluator |

---

## 1. Systemarchitektur & Datenfluss

```
[ DuckDB ohlcv_bars / MT5 Live Tick Feed ]
                    │
                    ▼
         ┌─────────────────────────────────────────────┐
         │            PyTrader Core Pipeline           │
         └──────────────┬──────────────────────────────┘
                        │ (OHLCV Stream / Ring-Buffer)
     ┌──────────────────┴───────────────────────────────────────────┐
     ▼                                                              ▼
┌──────────────────────────────┐                    ┌──────────────────────────────┐
│   srv_proximity (Bestand)    │                    │      srv_peak_finder         │
│   feature_store: in_time_    │                    │   (Peak/SL-Batch, stateless) │
│   window, levels_hit         │                    └──────────────┬───────────────┘
└──────────────┬───────────────┘                                   │ depends_on
               │ Zone-Hits (levels_hit) via shared_state            ▼
               │ Fallback True ohne Proximity-Signal      ┌──────────────────────────────┐
               │  Yellow = Zone-Hit ∧ Zeitfenster          │      srv_peak_grabber        │
               └──────────────┬──────────────────────────│  (Kernel-Batch, stateless)   │
                              │                          └──────────────┬───────────────┘
                              ▼                                         │ Signals/SL/Peak
   ┌──────────────────────────────────────────────────────────────┐     │ (feature_store)
   │              chart/indicators/ind_peak.py                    │     ▼
   │  ┌─────────────────────────┐   ┌──────────────────────────┐  │  ┌──────────────────────────┐
   │  │ calculate() (Hist)      │   │ PeakGrabberLiveState     │  │  │  outcome: PENDING/NULL  │
   │  │ ServiceSet-Evaluation   │   │ (Live-State-Machine,     │  │  │  (Modul folgt später)   │
   │  │ → SL-Linien + Marker    │   │  ring buffer, live SL)   │  │  └────────────┬─────────────┘
   │  └─────────────────────────┘   └──────────────────────────┘  │               │ records
   └───────────────┬──────────────────────────────────────────────┘               ▼
                   │                                                     ┌──────────────────────┐
                   ▼                                                     │  grabber_repository  │
   event_bus.grabber_event (record)                                      │  (DbPool, analytics) │
                   │                                                     └──────────┬───────────┘
                   ▼                                                                ▼
┌──────────────────────────────┐                                      ┌──────────────────────────────┐
│ analytics/order_preview_dialog│    analytics_win: btn_grabber_peak    │   DuckDB: grabber_test_     │
│ (PySide6-Modal, KEINE Order)  │ ◄── event_bus.grabber_toggle(dict)   │   results (Serientests)     │
└──────────────────────────────┘                                      └──────────────────────────────┘
```

**Pfade im Überblick:**
* Batch/Backtest: `ohlcv` → `srv_grid_lines` + `srv_proximity` (Yellow-Zonen) + `srv_peak_finder` + `srv_peak_grabber` (ServiceSetEvaluator) → `GrabberRepository.save_records()` (Outcome-Spalten `'PENDING'`/`NULL`, Frage 4).
* Live: `ind_peak.on_tick()` → `PeakGrabberLiveState` (zirkulärer Ringpuffer) → Live-Overlays an den Chart; Trigger/Update-Records via `event_bus.grabber_event` → `OrderPreviewDialog` (UI) + `GrabberRepository` (DB, über das AnalyticsWindow als Subscriber).
* `is_yellow_window` wird **im Service `srv_peak_grabber`** hergeleitet (`_derive_yellow_window`, Frage 3): Zone-Hits aus der `srv_proximity`-Instanz im `context.shared_state` + eigenes Zeitfenster (±5 min um :00/:30, Wanduhr); **Fallback `True`** ohne Proximity-Signal.

---

## 2. Datenmodelle & DuckDB Schema

### 2.1 Dateien (Konvention statt neuer Top-Level-Ordner)

* `analytics/engine/peak_models.py` – Dataclasses, Enums, Configs (Kollokation im Engine-Paket neben `service_models.py`).
* `analytics/features/definitions/grabber_kernel.py` – NumPy/Numba-Kernel (Helper-Modul, analog `grid_math.py`; enthält KEINE `PluginFeature`-Subklasse → wird von der Plugin-Discovery nicht als Plugin registriert).
* `db/schema_initializer.py` – DDL `grabber_test_results` (additiv).
* `repositories/grabber_repository.py` – DB-Zugriff (DbPool).
* `analytics/engine/peak_backtest_runner.py` – Serientest-Orchestrierung (Outcome-Spalten bleiben `'PENDING'`/`NULL`, Frage 4).
* `chart/indicators/ind_peak.py` – Indikator + `PeakGrabberLiveState` + `PeakFinderLive`.
* `config/event_bus.py` – neue Signale `grabber_toggle` (dict), `grabber_event` (object).
* `analytics/ui/order_preview_dialog.py` – Order-Vorschau-Modal.
* `analytics/ui/analytics_win.py` – Button `btn_grabber_peak`; `chart/chart_win.py` – Subscription (§9.3) + aufrufender Button `btn_peak_grabber` (§9.5).

**Deferred (späteres Kapitel, NICHT 22.01):** `analytics/engine/peak_outcome.py` – Exit-/Forward-Evaluation (TP/SL-Simulation, Frage 4).

### 2.2 Dataclasses (`analytics/engine/peak_models.py`)

```python
# analytics/engine/peak_models.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class GrabberState(int, Enum):
    IDLE = 0
    ARMED = 1
    TRIGGERED = 2
    INVALIDATED = 3


@dataclass(frozen=True)
class PeakConfig:
    sl_offset_pct: float = 0.15  # SL-Puffer über/unter Peak (%)

    def sl_factor_high(self) -> float:
        return 1.0 + (self.sl_offset_pct / 100.0)

    def sl_factor_low(self) -> float:
        return 1.0 - (self.sl_offset_pct / 100.0)


@dataclass(frozen=True)
class PeakGrabberConfig:
    reversal_pct: float = 0.30           # z% Reversal für Trigger
    min_hold_bars: int = 3               # Min. Bars Haltedauer des Peaks
    invalidation_bars: int = 5           # x Bars Beobachtungsfenster
    invalidation_threshold_pct: float = 0.10  # y% Toleranz vor Hard-Invalidation
    require_proximity_window: bool = True     # Verknüpfung mit Yellow Window
    take_profit_r: Optional[float] = None     # RESERVIERT (Frage 4): TP in R für späteres Outcome-Modul (None = kein TP)
    max_hold_bars: int = 100                  # RESERVIERT (Frage 4): Timeout für späteres Outcome-Modul


@dataclass
class GrabberResultRecord:
    signal_id: str
    run_id: str
    timestamp: datetime
    symbol: str
    timeframe: str
    direction: SignalDirection
    entry_price: float
    sl_price: float
    peak_price: float
    peak_bar_index: int
    is_update: bool                       # True bei <= y% Aktualisierung
    reversal_pct: float
    is_yellow_window: bool
    gate_source: str                      # GATE_/SERIES_ + UPDATE/TRIGGER
    outcome_status: str = "PENDING"
    pnl_r_multiple: Optional[float] = None
    max_favorable_exc: Optional[float] = None
    max_adverse_exc: Optional[float] = None
```

### 2.3 DuckDB Schema (`db/schema_initializer.py`, additiv in analytics.duckdb)

**18 Spalten** – der INSERT-Weg (§7) muss exakt diese 18 Spalten bedienen (B1).

```sql
-- db/schema_initializer.py (check_and_init_databases, analytics.duckdb)
CREATE TABLE IF NOT EXISTS grabber_test_results (
    signal_id           VARCHAR PRIMARY KEY,
    run_id              VARCHAR NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,   -- Wanduhr-Epochs (Präambel 8)
    symbol              VARCHAR NOT NULL,
    timeframe           VARCHAR NOT NULL,
    direction           VARCHAR NOT NULL,
    entry_price         DOUBLE NOT NULL,
    sl_price            DOUBLE NOT NULL,
    peak_price          DOUBLE NOT NULL,
    peak_bar_index      BIGINT NOT NULL,
    is_update           BOOLEAN NOT NULL,
    reversal_pct        FLOAT NOT NULL,
    is_yellow_window    BOOLEAN NOT NULL,
    gate_source         VARCHAR NOT NULL,
    outcome_status      VARCHAR DEFAULT 'PENDING',
    pnl_r_multiple      FLOAT,
    max_favorable_exc   FLOAT,
    max_adverse_exc     FLOAT
);
CREATE INDEX IF NOT EXISTS idx_grabber_run ON grabber_test_results (run_id);
```

`run_id`-Konvention: `"LIVE-<YYYYmmdd-HHMMSS>"` für Live-Läufe, `"BT-<YYYYmmdd-HHMMSS>"` für Serientests (kein UUID-Salat, gruppierbar).

---

## 3. High-Speed NumPy State-Machine Kernel (`analytics/features/definitions/grabber_kernel.py`)

### 3.1 Definierte Kernel-Semantik (Basis für Live/Batch-Parität)

* **Signale:** `0` = Keins, `1` = BUY_TRIGGER, `2` = BUY_UPDATE, `-1` = SELL_TRIGGER, `-2` = SELL_UPDATE.
* **Zustände:** `0` IDLE, `1` ARMED, `2` TRIGGERED, `3` INVALIDATED.
* **Startzustand immer IDLE (B2):** `gate_active` armiert NICHT automatisch – es schaltet nur das Gate frei.
* **Bar 0 = Bootstrap:** initialisiert `peak_h/peak_l` OHNE Event (entspricht dem ersten Live-Tick, dessen `prev` noch `NaN` ist – First-Peak-Skip).
* **`bars_h/bars_l` = Alter des VORHERIGEN Peaks** im New-Peak-Zweig (vor dem Update ermittelt), **= Alter des AKTUELLEN Peaks** im Reversal-Zweig (B3, identisch zur Live-Logik).
* **Division-by-Zero-Guards (B6):** `prev_h`/`peak_l` ≤ 0 → `breach_pct = 0.0` bzw. `rev_pct = 0.0` (kein NaN/Inf).

### 3.2 Kernel-Code (korrigiert, 4 Leerzeichen)

```python
# analytics/features/definitions/grabber_kernel.py
import numpy as np

try:
    from numba import njit
except ImportError:  # Fallback: pure NumPy (gleiche Semantik, langsamer)

    def njit(func):
        return func


@njit(fastmath=True)
def run_grabber_kernel(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    is_yellow_window: np.ndarray,
    reversal_pct: float,
    min_hold_bars: int,
    inval_bars: int,
    inval_thresh_pct: float,
    sl_offset_pct: float,
    require_prox: bool,
    gate_active: bool,
):
    """Serieller Backtest-Kernel (Zero-GC, native Geschwindigkeit).

    Signale: 0: Keins, 1: BUY_TRIGGER, 2: BUY_UPDATE, -1: SELL_TRIGGER,
    -2: SELL_UPDATE. Zustände: 0 IDLE, 1 ARMED, 2 TRIGGERED, 3 INVALIDATED.
    Startzustand IDLE (B2); Bar 0 = Bootstrap ohne Event.
    """
    n = len(highs)
    signals = np.zeros(n, dtype=np.int8)
    sl_prices = np.full(n, np.nan, dtype=np.float64)
    peak_prices = np.full(n, np.nan, dtype=np.float64)

    sl_factor_h = 1.0 + (sl_offset_pct / 100.0)
    sl_factor_l = 1.0 - (sl_offset_pct / 100.0)

    peak_h = highs[0]          # Bootstrap: kein Event (First-Peak-Skip, B2)
    peak_h_idx = 0
    state_short = 0            # IDLE

    peak_l = lows[0]           # Bootstrap
    peak_l_idx = 0
    state_long = 0             # IDLE

    for i in range(1, n):
        h = highs[i]
        l = lows[i]
        c = closes[i]
        yw = is_yellow_window[i]
        gate = gate_active and (yw if require_prox else True)

        # --- SHORT LOGIK (Peak = laufendes High) --------------------------
        if h > peak_h:
            prev_h = peak_h
            bars_h = i - peak_h_idx       # B2/B3: Alter des VORHERIGEN Peaks
            peak_h = h
            peak_h_idx = i
            if gate:
                breach_pct = ((h - prev_h) / prev_h) * 100.0 if prev_h > 0.0 else 0.0
                if bars_h <= inval_bars:
                    if breach_pct <= inval_thresh_pct:
                        state_short = 1   # ARMED / UPDATE
                        signals[i] = -2
                        sl_prices[i] = peak_h * sl_factor_h
                        peak_prices[i] = peak_h
                    else:
                        state_short = 3   # INVALIDATED
                else:
                    state_short = 1       # frischer Peak nach langer Ruhe
        elif gate and state_short == 1:   # ARMED: Reversal-Pruefung
            bars_h = i - peak_h_idx       # Alter des AKTUELLEN Peaks
            rev_pct = ((peak_h - c) / peak_h) * 100.0 if peak_h > 0.0 else 0.0
            if rev_pct >= reversal_pct and bars_h >= min_hold_bars:
                state_short = 2           # TRIGGERED
                signals[i] = -1
                sl_prices[i] = peak_h * sl_factor_h
                peak_prices[i] = peak_h

        # --- LONG LOGIK (Peak = laufendes Low) ----------------------------
        if l < peak_l:
            prev_l = peak_l
            bars_l = i - peak_l_idx       # Alter des VORHERIGEN Peaks
            peak_l = l
            peak_l_idx = i
            if gate:
                breach_pct = ((prev_l - l) / prev_l) * 100.0 if prev_l > 0.0 else 0.0
                if bars_l <= inval_bars:
                    if breach_pct <= inval_thresh_pct:
                        state_long = 1    # ARMED / UPDATE
                        signals[i] = 2
                        sl_prices[i] = peak_l * sl_factor_l
                        peak_prices[i] = peak_l
                    else:
                        state_long = 3    # INVALIDATED
                else:
                    state_long = 1        # frischer Peak nach langer Ruhe
        elif gate and state_long == 1:    # ARMED: Reversal-Pruefung
            bars_l = i - peak_l_idx       # Alter des AKTUELLEN Peaks
            rev_pct = ((c - peak_l) / peak_l) * 100.0 if peak_l > 0.0 else 0.0
            if rev_pct >= reversal_pct and bars_l >= min_hold_bars:
                state_long = 2            # TRIGGERED
                signals[i] = 1
                sl_prices[i] = peak_l * sl_factor_l
                peak_prices[i] = peak_l

    return signals, sl_prices, peak_prices
```

---

## 4. Service-Implementierungen (Plugin-Services)

### A. `srv_peak_finder` (`analytics/features/definitions/srv_peak_finder.py`)

Zustandsloser Plugin-Service (erbt `PluginFeature`): vektorisierte Peak-/SL-Berechnung, **keine** eigene Zustandshaltung.

```python
# analytics/features/definitions/srv_peak_finder.py
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

_PEAK_FINDER_SCHEMA: Dict[str, ParameterSchema] = {
    "sl_offset_pct": {
        "type": "float", "default": 0.15, "min": 0.0, "max": 10.0,
        "step": 0.01, "description": "SL-Puffer über/unter Peak (%)",
    },
}


class PeakFinderService(PluginFeature):
    """Vektorisierte Peak-Tracking & SL-Berechnung (Hist-Batch, stateless)."""

    @property
    def plugin_id(self) -> str:
        return "srv_peak_finder"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, str]:
        return {
            "category": "Swing Points/Peak Grabber",
            "display_name": "Peak Finder",
            "indicator_name": "Ind_Peak",
            "indicator_id": "ind_peak",
            "description": "Running Highs/Lows samt SL-Offset (Batch, stateless)",
            "author": "PyTrader AI",
            "tags": ["peak", "swing", "stop-loss"],
            "condition_rules": [
                "peak_high = maximum.accumulate(high)",
                "peak_low  = minimum.accumulate(low)",
                "sl_high = peak_high * (1 + sl_offset_pct/100)",
                "sl_low  = peak_low  * (1 - sl_offset_pct/100)",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": True,
            "batch": True,
            "live": False,            # Live läuft im Indikator (PeakGrabberLiveState)
            "feature_store": True,
            "render": False,          # P16.01: Styling baut der Indikator
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        return {k: dict(v) for k, v in _PEAK_FINDER_SCHEMA.items()}

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        if df is None or df.empty:
            return {"feature_store_payload": {}}
        p = self.validate_params(params)
        highs = df["high"].to_numpy(dtype=np.float64)
        lows = df["low"].to_numpy(dtype=np.float64)

        peak_highs = np.maximum.accumulate(highs)
        peak_lows = np.minimum.accumulate(lows)
        f_h = 1.0 + (float(p["sl_offset_pct"]) / 100.0)
        f_l = 1.0 - (float(p["sl_offset_pct"]) / 100.0)

        records: List[Dict[str, Any]] = []
        times = df["time"].to_numpy()
        for i in range(len(df)):
            records.append({
                "bar_time": int(times[i]),
                "peak_high": float(peak_highs[i]),
                "peak_low": float(peak_lows[i]),
                "sl_high": float(peak_highs[i] * f_h),
                "sl_low": float(peak_lows[i] * f_l),
            })
        # Shared-State für nachgelagerte srv_peak_grabber (depends_on):
        if context is not None and context.instance_id:
            context.shared_state[context.instance_id] = {
                "peak_highs": peak_highs,
                "peak_lows": peak_lows,
                "sl_highs": peak_highs * f_h,
                "sl_lows": peak_lows * f_l,
                "records": records,
            }
        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {"schema_version": "1.0.0"},
            },
        }
```

### B. `srv_peak_grabber` (`analytics/features/definitions/srv_peak_grabber.py`)

Zustandsloser Plugin-Service (erbt `PluginFeature`): liest die Peak-Arrays aus `shared_state` (`depends_on` `srv_peak_finder`), leitet `is_yellow_window` **selbst** her (`_derive_yellow_window`, Frage 3: Zone-Hit ∧ Zeitfenster ±5 min um :00/:30, **Fallback `True`**) und ruft `run_grabber_kernel`.

```python
# analytics/features/definitions/srv_peak_grabber.py
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from analytics.features.definitions.grabber_kernel import run_grabber_kernel
from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

_PEAK_GRABBER_SCHEMA: Dict[str, ParameterSchema] = {
    "reversal_pct": {"type": "float", "default": 0.30, "min": 0.01, "max": 10.0, "step": 0.01, "description": "Reversal % für Trigger (z)"},
    "min_hold_bars": {"type": "int", "default": 3, "min": 1, "max": 1000, "step": 1, "description": "Min. Bars Haltedauer des Peaks"},
    "invalidation_bars": {"type": "int", "default": 5, "min": 1, "max": 10000, "step": 1, "description": "Beobachtungsfenster x (Bars)"},
    "invalidation_threshold_pct": {"type": "float", "default": 0.10, "min": 0.0, "max": 10.0, "step": 0.01, "description": "Toleranz y% vor Hard-Invalidation"},
    "require_proximity_window": {"type": "bool", "default": True, "description": "Nur im Yellow Window triggern"},
    # Gemeinsamer SL-Parameter (Parität zu srv_peak_finder): Das Set muss
    # BEIDEN Instanzen denselben Wert geben (Single Source: Indikator-Schema).
    "sl_offset_pct": {"type": "float", "default": 0.15, "min": 0.0, "max": 10.0, "step": 0.01, "description": "SL-Puffer über/unter Peak (%) – muss srv_peak_finder entsprechen"},
    # Optionaler Test-Override (NICHT in parameter_order): JSON-bool-Liste je
    # Bar. Fehlt er, leitet der Service selbst ab (_derive_yellow_window, Frage 3).
    "is_yellow_window": {"type": "str", "default": "", "description": "Intern/Test: JSON-bool-Liste je Bar (Override)"},
}


class PeakGrabberService(PluginFeature):
    """Batch-Pfad der Peak-Grabber-State-Machine (stateless, Kernel)."""

    @property
    def plugin_id(self) -> str:
        return "srv_peak_grabber"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, str]:
        return {
            "category": "Swing Points/Peak Grabber",
            "display_name": "Peak Grabber",
            "indicator_name": "Ind_Peak",
            "indicator_id": "ind_peak",
            "description": "Gated State-Machine: BUY/SELL-Trigger & -Updates aus Peaks",
            "author": "PyTrader AI",
            "tags": ["peak", "grabber", "signal"],
            "condition_rules": [
                "Startzustand IDLE; Bar 0 = Bootstrap (First-Peak-Skip)",
                "Neuer Peak im Fenster: kleine Überschreitung -> ARMED/UPDATE, grosse -> INVALIDATED",
                "Reversal >= z% nach min_hold_bars -> TRIGGERED",
                "is_yellow_window = Zone-Hit ∧ Zeitfenster (±5 min um :00/:30); Fallback True ohne Proximity-Signal (Frage 3)",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": True,
            "batch": True,
            "live": False,            # Live läuft im Indikator
            "feature_store": True,
            "render": False,          # P16.01: Styling baut der Indikator
        }

    @property
    def dependencies(self) -> List[str]:
        return ["srv_peak_finder"]

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        return {k: dict(v) for k, v in _PEAK_GRABBER_SCHEMA.items()}

    # -------------------------------------------------- Frage 3: Yellow-Fenster
    @staticmethod
    def _bar_in_time_window(epoch_sec: int) -> bool:
        """Wanduhr-Minute in [0±5] oder [30±5] (Präambel 8: MT5-Epochs sind
        Berlin-Wanduhr-encoded; Muster `_f_in_window_around`, srv_proximity)."""
        minute = (epoch_sec // 60) % 60

        def _in(center: int, span: int = 5) -> bool:
            lower = center - span
            upper = center + span
            if lower < 0:
                return minute >= (60 + lower) or minute <= upper
            if upper > 59:
                return minute >= lower or minute <= (upper - 60)
            return lower <= minute <= upper

        return _in(0) or _in(30)

    @staticmethod
    def _extract_prox_zone_map(context: Optional[PluginContext]):
        """Zone-Hit (`levels_hit` ≠ leer) je bar_time aus der srv_proximity-
        Instanz im `context.shared_state`. None = kein Proximity-Signal."""
        if context is None:
            return None
        for _key, value in (context.shared_state or {}).items():
            if not isinstance(value, dict):
                continue
            if isinstance(value.get("records"), list):
                rows = value["records"]
                if any("levels_hit" in r for r in rows):
                    return {
                        int(r.get("bar_time", 0)): bool(r.get("levels_hit"))
                        for r in rows
                    }
            if "levels_hit" in value:  # Einzel-Record (Live)
                return {
                    int(value.get("bar_time", 0)): bool(
                        value.get("levels_hit"))
                }
        return None

    def _derive_yellow_window(
        self, df: pd.DataFrame, context: Optional[PluginContext]
    ) -> List[bool]:
        """Frage 3: `is_yellow_window := is_in_proximity_zone ∧
        is_in_time_window(±5 min um :00/:30)`.

        `is_in_proximity_zone` aus der srv_proximity-Instanz im Context
        (Zone-Hit-Records); **fehlt das Proximity-Signal → Fallback `True`**
        (Gate offen). `is_in_time_window` wird immer aus der Wanduhr-Minute
        der Bar hergeleitet (Präambel 8)."""
        zone_map = self._extract_prox_zone_map(context)
        out: List[bool] = []
        for t in df["time"]:
            epoch = int(t)
            in_win = self._bar_in_time_window(epoch)
            zone = True if zone_map is None else bool(
                zone_map.get(epoch, False))
            out.append(bool(zone and in_win))
        return out

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        if df is None or df.empty:
            return {"feature_store_payload": {}}
        p = self.validate_params(params)

        # Frage 3: is_yellow_window wird IM SERVICE hergeleitet
        # (_derive_yellow_window, Zone-Hit ∧ Zeitfenster, Fallback True).
        # Optionaler Test-Override: params["is_yellow_window"] als JSON-bool-
        # Liste (nicht in parameter_order, siehe Schema-Kommentar).
        yw_raw = p.get("is_yellow_window")
        if isinstance(yw_raw, str) and yw_raw.strip():
            import json as _json
            yw_list = _json.loads(yw_raw)
        elif isinstance(yw_raw, (list, tuple)):
            yw_list = list(yw_raw)
        else:
            yw_list = self._derive_yellow_window(df, context)
        yw = np.asarray([bool(x) for x in yw_list], dtype=bool)

        highs = df["high"].to_numpy(dtype=np.float64)
        lows = df["low"].to_numpy(dtype=np.float64)
        closes = df["close"].to_numpy(dtype=np.float64)

        # Peak/SL-Arrays aus dem depends_on-shared_state (srv_peak_finder).
        if context is not None and context.depends_on:
            src = context.shared_state.get(context.depends_on[0]) or {}
        else:
            src = {}
        sl_offset_pct = float((p.get("sl_offset_pct") or 0.15))
        if src and "sl_highs" in src:
            sl_highs = src["sl_highs"]
            sl_lows = src["sl_lows"]
            peak_highs = src["peak_highs"]
            peak_lows = src["peak_lows"]
        else:
            # Fallback: eigene Peak-Berechnung (Parität srv_peak_finder).
            peak_highs = np.maximum.accumulate(highs)
            peak_lows = np.minimum.accumulate(lows)
            f_h = 1.0 + (sl_offset_pct / 100.0)
            f_l = 1.0 - (sl_offset_pct / 100.0)
            sl_highs = peak_highs * f_h
            sl_lows = peak_lows * f_l

        signals, sl_prices, peak_prices = run_grabber_kernel(
            highs, lows, closes, yw,
            float(p["reversal_pct"]),
            int(p["min_hold_bars"]),
            int(p["invalidation_bars"]),
            float(p["invalidation_threshold_pct"]),
            sl_offset_pct,
            bool(p["require_proximity_window"]),
            True,  # gate_active: Button-Steuerung ist Aufgabe des Aufrufers
        )

        records: List[Dict[str, Any]] = []
        times = df["time"].to_numpy()
        for i in range(len(df)):
            if signals[i] == 0:
                continue
            records.append({
                "bar_time": int(times[i]),
                "signal": int(signals[i]),
                "signal_label": _SIGNAL_LABELS.get(int(signals[i]), "?"),
                "sl_price": float(sl_prices[i]),
                "peak_price": float(peak_prices[i]),
                "peak_high": float(peak_highs[i]),
                "peak_low": float(peak_lows[i]),
                "is_yellow_window": bool(yw[i]),
            })
        n_triggers = int(np.count_nonzero((signals == 1) | (signals == -1)))
        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {
                    "schema_version": "1.0.0",
                    "statistics": {
                        "signal_count": len(records),
                        "trigger_count": n_triggers,
                    },
                },
            },
        }


_SIGNAL_LABELS: Dict[int, str] = {
    1: "BUY_TRIGGER",
    2: "BUY_UPDATE",
    -1: "SELL_TRIGGER",
    -2: "SELL_UPDATE",
}
```

**Wichtig:** Der Plugin-Service erzeugt **keine** `GrabberResultRecord`-Objekte (zustandslos, keine DB). Die Record-Bildung übernimmt der Backtest-Runner (§8) bzw. der Live-Indikator (§5) – **eine** Record-Semantik, zwei Erzeuger.

**Set-Kopplung (Frage 3):** Die `srv_proximity`-Instanz muss im selben Set laufen und ihre Zone-Hit-Records (`{bar_time, levels_hit}`) über `context.shared_state` bereitstellen (`execution_order: grid_1 → prox_1 → peak_1 → grab_1`; `grab_1.depends_on = ["peak_1", "prox_1"]`). Fehlt sie (oder liefert keine Daten), greift der **Fallback `True`** – `srv_peak_grabber` bleibt auch ohne Proximity funktionsfähig.

### C. Live-State-Machine `PeakGrabberLiveState` (`chart/indicators/ind_peak.py`)

Zustandsbehaftet, aber **nur im Indikator** (kein Plugin) – Muster `ind_fixed_grid_proximity`. Parität zu Kernel gemäß §3.1.

```python
# chart/indicators/ind_peak.py (Teil 1: Live-State-Machine)
import numpy as np
from datetime import datetime
from typing import List, Optional, Tuple

from analytics.engine.peak_models import (
    GrabberResultRecord,
    GrabberState,
    PeakConfig,
    PeakGrabberConfig,
    SignalDirection,
)


class PeakFinderLive:
    """O(1) Live-Peak-Tracker (Scalar-State, Parität zu compute_batch)."""

    def __init__(self, cfg: PeakConfig) -> None:
        self.cfg = cfg
        self.cur_high_price: float = np.nan
        self.cur_high_idx: int = -1
        self.cur_high_sl: float = np.nan
        self.cur_low_price: float = np.nan
        self.cur_low_idx: int = -1
        self.cur_low_sl: float = np.nan

    def reset(self) -> None:
        self.cur_high_price = np.nan
        self.cur_high_idx = -1
        self.cur_high_sl = np.nan
        self.cur_low_price = np.nan
        self.cur_low_idx = -1
        self.cur_low_sl = np.nan

    def set_state(self, high: float, high_idx: int, low: float,
                  low_idx: int) -> None:
        """B4: Übernahme der Batch-Endwerte (bootstrap_history)."""
        self.cur_high_price = float(high)
        self.cur_high_idx = int(high_idx)
        self.cur_high_sl = float(high) * self.cfg.sl_factor_high()
        self.cur_low_price = float(low)
        self.cur_low_idx = int(low_idx)
        self.cur_low_sl = float(low) * self.cfg.sl_factor_low()

    def update_scalar(self, bar_idx: int, high: float,
                      low: float) -> Tuple[bool, bool]:
        is_new_h = False
        is_new_l = False
        if np.isnan(self.cur_high_price) or high > self.cur_high_price:
            self.cur_high_price = high
            self.cur_high_idx = bar_idx
            self.cur_high_sl = high * self.cfg.sl_factor_high()
            is_new_h = True
        if np.isnan(self.cur_low_price) or low < self.cur_low_price:
            self.cur_low_price = low
            self.cur_low_idx = bar_idx
            self.cur_low_sl = low * self.cfg.sl_factor_low()
            is_new_l = True
        return is_new_h, is_new_l


class PeakGrabberLiveState:
    """Live-State-Machine (Parität zum Kernel §3.1, B2/B3/B6).

    Kein Plugin – wird ausschließlich vom Indikator ind_peak getrieben.
    """

    def __init__(self, cfg: PeakGrabberConfig, finder: PeakFinderLive,
                 symbol: str, timeframe: str) -> None:
        self.cfg = cfg
        self.finder = finder
        self.symbol = symbol
        self.tf = timeframe
        self.run_id: str = "LIVE"
        self.is_btn_active: bool = False
        self.state_short: GrabberState = GrabberState.IDLE
        self.state_long: GrabberState = GrabberState.IDLE

    def set_button_active(self, active: bool) -> None:
        self.is_btn_active = bool(active)
        if not active:
            self.state_short = GrabberState.IDLE
            self.state_long = GrabberState.IDLE

    def process_tick_or_bar(
        self,
        bar_idx: int,
        high: float,
        low: float,
        close: float,
        ts: datetime,
        is_yellow_window: bool,
    ) -> List[GrabberResultRecord]:
        events: List[GrabberResultRecord] = []

        # B3: VOR update_scalar den vorherigen Peak-Stand sichern
        # (Alter des VORHERIGEN Peaks, Parität zur Kernel-Semantik).
        prev_h_price = self.finder.cur_high_price
        prev_h_idx = self.finder.cur_high_idx
        prev_l_price = self.finder.cur_low_price
        prev_l_idx = self.finder.cur_low_idx

        is_new_h, is_new_l = self.finder.update_scalar(bar_idx, high, low)

        gate = self.is_btn_active and (
            is_yellow_window if self.cfg.require_proximity_window else True
        )
        if not gate:
            return events

        # --- Short Side (Peak = laufendes High) --------------------------
        if is_new_h and not np.isnan(prev_h_price):
            bars_h = bar_idx - prev_h_idx
            breach_pct = ((high - prev_h_price) / prev_h_price) * 100.0
            if bars_h <= self.cfg.invalidation_bars:
                if breach_pct <= self.cfg.invalidation_threshold_pct:
                    self.state_short = GrabberState.ARMED
                    events.append(self._build_record(
                        ts, SignalDirection.SELL, close,
                        self.finder.cur_high_sl, self.finder.cur_high_price,
                        bar_idx, True, 0.0, is_yellow_window,
                        "GATE_UPDATE"))
                else:
                    self.state_short = GrabberState.INVALIDATED
            else:
                self.state_short = GrabberState.ARMED
        elif self.state_short == GrabberState.ARMED:
            bars_h = bar_idx - self.finder.cur_high_idx
            rev = (((self.finder.cur_high_price - close)
                    / self.finder.cur_high_price) * 100.0
                   if self.finder.cur_high_price > 0.0 else 0.0)
            if rev >= self.cfg.reversal_pct and bars_h >= self.cfg.min_hold_bars:
                self.state_short = GrabberState.TRIGGERED
                events.append(self._build_record(
                    ts, SignalDirection.SELL, close,
                    self.finder.cur_high_sl, self.finder.cur_high_price,
                    bar_idx, False, rev, is_yellow_window, "GATE_TRIGGER"))

        # --- Long Side (Peak = laufendes Low) ----------------------------
        if is_new_l and not np.isnan(prev_l_price):
            bars_l = bar_idx - prev_l_idx
            breach_pct = ((prev_l_price - low) / prev_l_price) * 100.0
            if bars_l <= self.cfg.invalidation_bars:
                if breach_pct <= self.cfg.invalidation_threshold_pct:
                    self.state_long = GrabberState.ARMED
                    events.append(self._build_record(
                        ts, SignalDirection.BUY, close,
                        self.finder.cur_low_sl, self.finder.cur_low_price,
                        bar_idx, True, 0.0, is_yellow_window,
                        "GATE_UPDATE"))
                else:
                    self.state_long = GrabberState.INVALIDATED
            else:
                self.state_long = GrabberState.ARMED
        elif self.state_long == GrabberState.ARMED:
            bars_l = bar_idx - self.finder.cur_low_idx
            rev = (((close - self.finder.cur_low_price)
                    / self.finder.cur_low_price) * 100.0
                   if self.finder.cur_low_price > 0.0 else 0.0)
            if rev >= self.cfg.reversal_pct and bars_l >= self.cfg.min_hold_bars:
                self.state_long = GrabberState.TRIGGERED
                events.append(self._build_record(
                    ts, SignalDirection.BUY, close,
                    self.finder.cur_low_sl, self.finder.cur_low_price,
                    bar_idx, False, rev, is_yellow_window, "GATE_TRIGGER"))

        return events

    def _build_record(self, ts: datetime, direction: SignalDirection,
                      entry: float, sl: float, peak: float, idx: int,
                      upd: bool, rev: float, yellow: bool,
                      src: str) -> GrabberResultRecord:
        import uuid
        return GrabberResultRecord(
            signal_id=str(uuid.uuid4()),
            run_id=self.run_id,
            timestamp=ts,
            symbol=self.symbol,
            timeframe=self.tf,
            direction=direction,
            entry_price=entry,
            sl_price=sl,
            peak_price=peak,
            peak_bar_index=idx,
            is_update=upd,
            reversal_pct=rev,
            is_yellow_window=yellow,
            gate_source=src,
        )
```

**Hinweis (Import-Disziplin):** `PeakFinderLive` ist im Indikator lokal implementiert (kein Import des Plugin-Services `srv_peak_finder` in die Chart-Schicht nötig). Die Plugin-Variante `srv_peak_finder` bedient ausschließlich die Batch-/Store-Pipeline; beide teilen dieselbe Mathematik (`PeakConfig.sl_factor_high/low`).

---

## 5. Indikator & Charting-Adapter (`chart/indicators/ind_peak.py`)

`IndPeak` erbt von `BaseIndicator` (volle API, Frage 2). Render-Payload-Konvention (P16.05):

* **`lines`** (Zeitreihen-LineSeries, Multi-MA-Konvention): `{id, data:[{time, value, color}], width, style, title}` – `sl_high` (rot/SELL) und `sl_low` (grün/BUY).
* **`markers`** (LWC-v5): TRIGGER = `arrowUp`/`arrowDown` (aboveBar/belowBar, size 2); UPDATE = `circle` (size 1) nur bei `show_updates=True`.
* **`status_info`**: `{is_btn_active, trigger_count}` aus den Service-`metadata["statistics"]`.

```python
# chart/indicators/ind_peak.py (Teil 2: Indikator, BaseIndicator)
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from chart.indicators.base_indicator import BaseIndicator
from analytics.engine.peak_models import (
    GrabberResultRecord,
    PeakConfig,
    PeakGrabberConfig,
)
from analytics.features.feature_builder import PluginExecutor
from analytics.features.plugins.base_plugin import PluginContext
from analytics.engine.set_evaluator import ServiceSetEvaluator

_PEAK_SCHEMA: Dict[str, Dict[str, Any]] = {
    "sl_offset_pct": {"type": "float", "default": 0.15, "min": 0.0, "max": 10.0, "step": 0.01, "description": "SL-Puffer über/unter Peak (%)"},
    "reversal_pct": {"type": "float", "default": 0.30, "min": 0.01, "max": 10.0, "step": 0.01, "description": "Reversal % für Trigger (z)"},
    "min_hold_bars": {"type": "int", "default": 3, "min": 1, "max": 1000, "step": 1, "description": "Min. Bars Haltedauer des Peaks"},
    "invalidation_bars": {"type": "int", "default": 5, "min": 1, "max": 10000, "step": 1, "description": "Beobachtungsfenster x (Bars)"},
    "invalidation_threshold_pct": {"type": "float", "default": 0.10, "min": 0.0, "max": 10.0, "step": 0.01, "description": "Toleranz y% vor Hard-Invalidation"},
    "require_proximity_window": {"type": "bool", "default": True, "description": "Nur im Yellow Window triggern"},
    "show_sl_high": {"type": "bool", "default": True, "description": "SL-High-Linie anzeigen"},
    "show_sl_low": {"type": "bool", "default": True, "description": "SL-Low-Linie anzeigen"},
    "show_signals": {"type": "bool", "default": True, "description": "Trigger-Marker anzeigen"},
    "show_updates": {"type": "bool", "default": False, "description": "Update-Marker anzeigen"},
    "sl_high_color": {"type": "color", "default": "#EF5350", "description": "Farbe SL-High-Linie", "style_type": "line", "show_visibility": False},
    "sl_low_color": {"type": "color", "default": "#26A69A", "description": "Farbe SL-Low-Linie", "style_type": "line", "show_visibility": False},
}


class IndPeak(BaseIndicator):
    """Peak-Grabber-Indikator: SL-Linien + Trigger-Marker (Hist & Live)."""

    def __init__(self) -> None:
        super().__init__()
        self._symbol: Optional[str] = None
        self._timeframe: Optional[str] = None
        self._settings: Any = None
        self._on_new_candle: Optional[Callable[[], None]] = None
        self._executor = PluginExecutor()
        self._evaluator = ServiceSetEvaluator(self._executor)
        self._last_params: Dict[str, Any] = {}

        # Live-Komponenten (ring buffer, Zero-GC, B5)
        self._buffer_size: int = 2000
        self._head: int = 0
        self._buf_time = np.zeros(self._buffer_size, dtype=np.int64)
        self._buf_sl_high = np.full(self._buffer_size, np.nan, dtype=np.float64)
        self._buf_sl_low = np.full(self._buffer_size, np.nan, dtype=np.float64)
        self._filled: int = 0
        self._known_times: set = set()  # New-Candle-Erkennung (gerundete Zeit)

        self._live_state: Optional[PeakGrabberLiveState] = None

    # ------------------------------------------------------------- Identität
    @property
    def indicator_id(self) -> str:
        return "ind_peak"

    @property
    def display_name(self) -> str:
        return "Ind_Peak (Peak Grabber)"

    @property
    def plugin_id(self) -> str:
        return "ind_peak"

    @property
    def service_plugin_ids(self) -> List[str]:
        return ["srv_peak_finder", "srv_peak_grabber"]

    @property
    def parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in _PEAK_SCHEMA.items()}

    @property
    def parameter_order(self) -> List[str]:
        return list(_PEAK_SCHEMA.keys())

    @property
    def default_params(self) -> Dict[str, Any]:
        return {k: v["default"] for k, v in _PEAK_SCHEMA.items() if "default" in v}

    # ------------------------------------------------------------- Kontext
    def set_context(self, symbol: str, timeframe: str) -> None:
        self._symbol = symbol
        self._timeframe = timeframe

    def set_settings(self, settings: Any) -> None:
        self._settings = settings

    def set_new_candle_callback(self, callback: Optional[Callable[[], None]]) -> None:
        self._on_new_candle = callback

    # ------------------------------------------------------------- Live-Hook
    def set_button_active(self, active: bool) -> None:
        """Wird von chart_win generisch über event_bus.grabber_toggle gerufen."""
        if self._live_state is not None:
            self._live_state.set_button_active(active)

    # ------------------------------------------------ Ringpuffer (B5, Zero-GC)
    def _push(self, ts: int, sl_high: float, sl_low: float) -> None:
        idx = self._head % self._buffer_size
        self._buf_time[idx] = int(ts)
        self._buf_sl_high[idx] = float(sl_high)
        self._buf_sl_low[idx] = float(sl_low)
        self._head += 1
        if self._filled < self._buffer_size:
            self._filled += 1

    def _ordered_buffers(self):
        start = max(0, self._head - self._filled)
        out_t = np.empty(self._filled, dtype=np.int64)
        out_h = np.empty(self._filled, dtype=np.float64)
        out_l = np.empty(self._filled, dtype=np.float64)
        for k in range(self._filled):
            src = (start + k) % self._buffer_size
            out_t[k] = self._buf_time[src]
            out_h[k] = self._buf_sl_high[src]
            out_l[k] = self._buf_sl_low[src]
        return out_t, out_h, out_l

    # ------------------------------------------------------------ Berechnung
    def _get_app_settings(self) -> Any:
        if self._settings is not None:
            return self._settings
        try:
            from state_manager import StateManager
            return StateManager().get_app_settings()
        except Exception:
            return None

    def _build_set_definition(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Frage 3: Set mit grid_1 → prox_1 (Zone-Hits in shared_state) →
        peak_1 → grab_1. Der Service srv_peak_grabber leitet is_yellow_window
        selbst her (Fallback True ohne Proximity-Signal)."""
        return {
            "set_id": "ind_peak_internal",
            "display_name": "Ind_Peak (intern)",
            "execution_order": ["grid_1", "prox_1", "peak_1", "grab_1"],
            "services": {
                "grid_1": {
                    "plugin_id": "srv_grid_lines",
                    "lookback": int(params.get("lookback") or 1000),
                    "params": {
                        "step_size": params.get("grid_step", 0.5),
                        "steps_around": params.get("steps_around", 4),
                    },
                },
                "prox_1": {
                    "plugin_id": "srv_proximity",
                    "lookback": int(params.get("lookback") or 1000),
                    "depends_on": ["grid_1"],
                    "params": {
                        # Frage 3: festes Zeitfenster ±5 min um :00/:30
                        "visit_pct": params.get("proximity_threshold", 0.05),
                        "time_window_mins": 5,
                        "use_time_filter": True,
                    },
                },
                "peak_1": {
                    "plugin_id": "srv_peak_finder",
                    "lookback": int(params.get("lookback") or 1000),
                    "params": {"sl_offset_pct": params.get("sl_offset_pct", 0.15)},
                },
                "grab_1": {
                    "plugin_id": "srv_peak_grabber",
                    "lookback": int(params.get("lookback") or 1000),
                    "depends_on": ["peak_1", "prox_1"],
                    "params": {
                        "reversal_pct": params.get("reversal_pct", 0.30),
                        "min_hold_bars": params.get("min_hold_bars", 3),
                        "invalidation_bars": params.get("invalidation_bars", 5),
                        "invalidation_threshold_pct": params.get(
                            "invalidation_threshold_pct", 0.10),
                        "require_proximity_window": params.get(
                            "require_proximity_window", True),
                        "sl_offset_pct": params.get("sl_offset_pct", 0.15),
                    },
                },
            },
        }

    def calculate(self, df: pd.DataFrame,
                  params: Dict[str, Any]) -> Dict[str, Any]:
        empty = {"lines": [], "markers": [], "status_info": {}}
        if df is None or df.empty:
            return empty
        try:
            p = dict(params or {})
            self._last_params = dict(p)
            context = PluginContext(
                symbol=self._symbol or "",
                timeframe=self._timeframe or "",
                mode="chart",
                settings=self._get_app_settings(),
            )
            definition = self._build_set_definition(p)
            results = self._evaluator.execute_set(definition, df, context)

            # SL-Linien aus srv_peak_finder (sl_high/sl_low je Bar)
            finder_recs = ((results.get("peak_1") or {}).get(
                "feature_store_payload") or {}).get("records") or []
            grabber_recs = ((results.get("grab_1") or {}).get(
                "feature_store_payload") or {}).get("records") or []
            stats = ((results.get("grab_1") or {}).get(
                "feature_store_payload") or {}).get("metadata") or {}

            lines: List[Dict[str, Any]] = []
            if p.get("show_sl_high", True):
                lines.append({
                    "id": "sl_high",
                    "data": [{"time": int(r["bar_time"]),
                              "value": float(r["sl_high"]),
                              "color": p.get("sl_high_color", "#EF5350")}
                             for r in finder_recs],
                    "width": 1, "style": "solid", "title": "SL High",
                })
            if p.get("show_sl_low", True):
                lines.append({
                    "id": "sl_low",
                    "data": [{"time": int(r["bar_time"]),
                              "value": float(r["sl_low"]),
                              "color": p.get("sl_low_color", "#26A69A")}
                             for r in finder_recs],
                    "width": 1, "style": "solid", "title": "SL Low",
                })

            markers: List[Dict[str, Any]] = []
            if p.get("show_signals", True):
                for r in grabber_recs:
                    sig = int(r["signal"])
                    if sig in (1, -1):  # Trigger
                        markers.append({
                            "time": int(r["bar_time"]),
                            "position": "aboveBar" if sig == 1 else "belowBar",
                            "color": "#26A69A" if sig == 1 else "#EF5350",
                            "shape": "arrowUp" if sig == 1 else "arrowDown",
                            "size": 2,
                            "text": "BUY" if sig == 1 else "SELL",
                            "priority": 8,
                        })
                    elif p.get("show_updates", False):  # Update
                        markers.append({
                            "time": int(r["bar_time"]),
                            "position": "aboveBar" if sig == 2 else "belowBar",
                            "color": "#90A4AE",
                            "shape": "circle",
                            "size": 1,
                            "text": "upd",
                            "priority": 5,
                        })

            # Bootstrap des Live-States (B4): Batch-Endwerte übernehmen.
            self._bootstrap_live_state(finder_recs, p)

            return {
                "lines": lines,
                "markers": markers,
                "status_info": {
                    "is_btn_active": bool(
                        self._live_state and self._live_state.is_btn_active),
                    "trigger_count": int((stats.get("statistics") or {}).get(
                        "trigger_count", 0)),
                },
            }
        except Exception as e:
            print(f"[IndPeak] Service-Pipeline fehlgeschlagen: {e}")
            return empty

    def _bootstrap_live_state(self, finder_recs: List[Dict[str, Any]],
                              p: Dict[str, Any]) -> None:
        """B4: übernimmt die letzten Batch-Peaks in den Live-Scalar-State."""
        if not finder_recs:
            return
        last = finder_recs[-1]
        peak_cfg = PeakConfig(sl_offset_pct=float(
            p.get("sl_offset_pct", 0.15)))
        if self._live_state is None:
            finder_live = PeakFinderLive(peak_cfg)
            self._live_state = PeakGrabberLiveState(
                PeakGrabberConfig(
                    reversal_pct=float(p.get("reversal_pct", 0.30)),
                    min_hold_bars=int(p.get("min_hold_bars", 3)),
                    invalidation_bars=int(p.get("invalidation_bars", 5)),
                    invalidation_threshold_pct=float(p.get(
                        "invalidation_threshold_pct", 0.10)),
                    require_proximity_window=bool(p.get(
                        "require_proximity_window", True)),
                ),
                finder_live,
                self._symbol or "",
                self._timeframe or "",
            )
        # Ringpuffer mit History-SL füllen (nur die letzten buffer_size).
        n = min(len(finder_recs), self._buffer_size)
        self._filled = 0
        self._head = 0
        for r in finder_recs[-n:]:
            self._push(int(r["bar_time"]),
                       float(r["sl_high"]), float(r["sl_low"]))
        last_high = float(last["peak_high"])
        last_low = float(last["peak_low"])
        self._live_state.finder.set_state(
            last_high, len(finder_recs) - 1, last_low, len(finder_recs) - 1)

    # ----------------------------------------------------- Live-Tick-Pfad
    def update_live_candle(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Live: O(1) Tick-Update auf den letzten Ringpuffer-Slot + Yellow-
        Flag der aktuellen Bar. Neue Candle → genau EIN debounced Refresh."""
        if not candle or self._live_state is None:
            return []
        try:
            ts = int(candle.get("time", 0))
            high = float(candle.get("high", candle.get("price", 0.0)))
            low = float(candle.get("low", high))
            close = float(candle.get("close", candle.get("price", 0.0)))
        except (TypeError, ValueError):
            return []

        # Yellow-Flag aktuell (letzter srv_proximity-Record, FeatureStoreReader)
        yellow = self._is_current_bar_yellow(ts)
        # New-Candle-Erkennung (gerundete Zeit, Muster ind_fixed_grid_proximity)
        from db_service import TF_SECONDS_MAP
        t_sec = TF_SECONDS_MAP.get(str(self._timeframe or "").upper(), 60)
        rounded = ts - (ts % t_sec)
        if rounded not in self._known_times:
            self._known_times.add(rounded)
            if self._on_new_candle is not None:
                try:
                    self._on_new_candle()
                except Exception:
                    pass

        bar_idx = max(self._filled, self._live_state.finder.cur_high_idx + 1)
        records = self._live_state.process_tick_or_bar(
            bar_idx, high, low, close,
            pd.Timestamp(ts, unit="s").to_pydatetime(),  # B7
            yellow)
        # Live-SL-Punkt in den Ringpuffer (In-Place, letzter Slot).
        self._push(ts, self._live_state.finder.cur_high_sl,
                   self._live_state.finder.cur_low_sl)

        if records:
            # Persistenz + UI-Modal über den EventBus (Präambel 4, IoC)
            try:
                from config.event_bus import event_bus
                for rec in records:
                    event_bus.grabber_event.emit(rec)
            except Exception:
                pass
        return records

    def _is_current_bar_yellow(self, ts: int) -> bool:
        """Frage 3 (Live): Zone-Hit ∧ Zeitfenster der aktuellen Bar aus dem
        letzten srv_proximity-Record; **Fallback `True`** ohne Proximity-
        Signal (Gate offen)."""
        try:
            from analytics.engine.feature_store_reader import FeatureStoreReader
            reader = FeatureStoreReader(db_path=None)
            rec = reader.latest_proximity_record(
                self._symbol or "", self._timeframe or "", int(ts))
            if rec:
                fd = rec.get("feature_data") or {}
                return bool(fd.get("in_time_window") and (fd.get("levels_hit") or []))
        except Exception:
            pass
        return True

    # ---------------------------------------------------- Overlay-Hooks (P14-03)
    def get_live_overlays(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Live-SL-Punkte als generische Overlays (kind='circle')."""
        self.update_live_candle(candle)
        if self._live_state is None:
            return []
        overlays = []
        if not np.isnan(self._live_state.finder.cur_high_sl):
            overlays.append({
                "kind": "circle", "layer": self.indicator_id,
                "time": int(candle.get("time", 0)),
                "price": float(self._live_state.finder.cur_high_sl),
                "color": self._last_params.get("sl_high_color", "#EF5350"),
                "priority": 10,
            })
        if not np.isnan(self._live_state.finder.cur_low_sl):
            overlays.append({
                "kind": "circle", "layer": self.indicator_id,
                "time": int(candle.get("time", 0)),
                "price": float(self._live_state.finder.cur_low_sl),
                "color": self._last_params.get("sl_low_color", "#26A69A"),
                "priority": 10,
            })
        return overlays

    def remember_live_time(self, ts: int) -> None:
        try:
            self._known_times.add(int(ts))
        except (TypeError, ValueError):
            pass
```

---

## 6. Outcome-Spalten (PENDING-Platzhalter, Frage 4)

**In 22.01 wird KEINE Exit-/Forward-Evaluation implementiert** (Entscheidung 4). Die vier Outcome-Spalten existieren bereits im DDL-Schema (§2.3) mit Defaults:

| Spalte | 22.01-Wert |
|--------|-----------|
| `outcome_status` | `'PENDING'` (DEFAULT) |
| `pnl_r_multiple` | `NULL` |
| `max_favorable_exc` | `NULL` |
| `max_adverse_exc` | `NULL` |

**Deferred – separates Auswertungs-Modul (späteres Kapitel):** `analytics/engine/peak_outcome.py` – Forward-Walk-Exit-Evaluation (SL-Hit, TP-Hit via `PeakGrabberConfig.take_profit_r`, `max_hold_bars`-Timeout, OPEN; MFE/MAE in Preis-Einheiten; `pd.Timestamp(...).to_pydatetime()`-Semantik, B7). Nur TRIGGER-Records (`is_update=False`) öffnen dort eine Position. Die reservierten Config-Felder `take_profit_r` / `max_hold_bars` (§2.2) werden erst in diesem Modul ausgewertet.

**Wichtig:** `GrabberRepository` (§7) persistiert die Records **immer** mit `outcome_status='PENDING'` / Outcome-`NULL` – das spätere Modul aktualisiert die Zeilen per `ON CONFLICT (signal_id) DO UPDATE` (nur die 4 Outcome-Spalten, §7).

---

## 7. Persistenz & Repository (`repositories/grabber_repository.py`)

DbPool-Muster (Präambel 6): Thread-local `DbPool.get(self.db_path)`, **kein** manuelles `close()`. Batch-INSERT via `con.register` (Muster `store_plugin_payload`) mit **exakt 18 Spalten** (B1).

```python
# repositories/grabber_repository.py
from typing import List

import pandas as pd

from analytics.engine.peak_models import GrabberResultRecord
from db_service import DB_ANALYTICS, DbPool


class GrabberRepository:
    """Kapselt den DB-Zugriff auf grabber_test_results (MVVM, Präambel 4/6)."""

    def __init__(self, db_path: str = DB_ANALYTICS) -> None:
        self.db_path = db_path

    _COLS = [
        "signal_id", "run_id", "timestamp", "symbol", "timeframe",
        "direction", "entry_price", "sl_price", "peak_price",
        "peak_bar_index", "is_update", "reversal_pct",
        "is_yellow_window", "gate_source", "outcome_status",
        "pnl_r_multiple", "max_favorable_exc", "max_adverse_exc",
    ]

    def save_records(self, records: List[GrabberResultRecord]) -> int:
        """Batch-Upsert (18 Spalten, B1). ON CONFLICT aktualisiert nur
        die Outcome-Felder (nachlaufende Serientest-Bewertung)."""
        if not records:
            return 0
        rows = [
            (
                r.signal_id, r.run_id, r.timestamp, r.symbol, r.timeframe,
                r.direction.value, r.entry_price, r.sl_price, r.peak_price,
                r.peak_bar_index, r.is_update, r.reversal_pct,
                r.is_yellow_window, r.gate_source, r.outcome_status,
                r.pnl_r_multiple, r.max_favorable_exc, r.max_adverse_exc,
            )
            for r in records
        ]
        con = DbPool.get(self.db_path)
        df = pd.DataFrame(rows, columns=self._COLS)
        con.register("df_grabber", df)
        cols = ", ".join(self._COLS)
        try:
            con.execute(f"""
                INSERT INTO grabber_test_results ({cols})
                SELECT {cols} FROM df_grabber
                ON CONFLICT (signal_id) DO UPDATE SET
                    outcome_status = EXCLUDED.outcome_status,
                    pnl_r_multiple = EXCLUDED.pnl_r_multiple,
                    max_favorable_exc = EXCLUDED.max_favorable_exc,
                    max_adverse_exc = EXCLUDED.max_adverse_exc
            """)
        finally:
            con.unregister("df_grabber")
        return len(rows)

    def fetch_records(self, run_id: str) -> List[dict]:
        con = DbPool.get(self.db_path)
        rows = con.execute(
            "SELECT * FROM grabber_test_results WHERE run_id = ? "
            "ORDER BY timestamp", [run_id]).fetchall()
        cols = [d[0] for d in con.description]
        return [dict(zip(cols, r)) for r in rows]

    def delete_run(self, run_id: str) -> int:
        con = DbPool.get(self.db_path)
        res = con.execute(
            "DELETE FROM grabber_test_results WHERE run_id = ?",
            [run_id])
        return len(res.fetchall() or [])
```

---

## 8. Serientests / Backtest-Orchestrierung (`analytics/engine/peak_backtest_runner.py`)

Headless Runner (läuft in einem Worker nach `ServiceRunWorker`-Muster mit `event_bus.service_run_started/finished`, Präambel 9):

```python
# analytics/engine/peak_backtest_runner.py
import uuid
from datetime import datetime
from typing import List, Optional

import pandas as pd

from analytics.engine.peak_models import (
    GrabberResultRecord,
    PeakConfig,
    PeakGrabberConfig,
)
from analytics.features.feature_builder import (
    PluginExecutor,
    prepare_plugin_df,
)
from analytics.features.plugins.base_plugin import PluginContext
from analytics.engine.set_evaluator import ServiceSetEvaluator
from repositories.grabber_repository import GrabberRepository


class PeakBacktestRunner:
    """Serientest: ohlcv → grid/prox + peak-Services → DB (PENDING/NULL)."""

    def __init__(self) -> None:
        self.executor = PluginExecutor()
        self.evaluator = ServiceSetEvaluator(self.executor)
        self.repo = GrabberRepository()

    def _load_ohlcv(self, symbol: str, timeframe: str,
                    limit: Optional[int]) -> pd.DataFrame:
        from analytics.features.feature_builder import FeatureBuilder
        df = FeatureBuilder().load_ohlcv(symbol, timeframe, limit)
        return prepare_plugin_df(df)

    def run_series(
        self,
        symbol: str,
        timeframe: str,
        cfg: PeakGrabberConfig,
        peak_cfg: PeakConfig = PeakConfig(),
        limit: Optional[int] = None,
    ) -> List[GrabberResultRecord]:
        df = self._load_ohlcv(symbol, timeframe, limit)
        if df is None or df.empty:
            return []

        # Frage 3: grid_1 → prox_1 (Zone-Hits in shared_state) → peak_1 → grab_1.
        # Der Service srv_peak_grabber leitet is_yellow_window selbst her.
        definition = {
            "set_id": "peak_backtest_internal",
            "display_name": "Peak Backtest (intern)",
            "execution_order": ["grid_1", "prox_1", "peak_1", "grab_1"],
            "services": {
                "grid_1": {
                    "plugin_id": "srv_grid_lines",
                    "lookback": int(limit or len(df)),
                    "params": {"step_size": 0.5, "steps_around": 4},
                },
                "prox_1": {
                    "plugin_id": "srv_proximity",
                    "lookback": int(limit or len(df)),
                    "depends_on": ["grid_1"],
                    "params": {
                        "visit_pct": 0.05,
                        "time_window_mins": 5,   # Frage 3: ±5 min um :00/:30
                        "use_time_filter": True,
                    },
                },
                "peak_1": {
                    "plugin_id": "srv_peak_finder",
                    "lookback": int(limit or len(df)),
                    "params": {"sl_offset_pct": peak_cfg.sl_offset_pct},
                },
                "grab_1": {
                    "plugin_id": "srv_peak_grabber",
                    "lookback": int(limit or len(df)),
                    "depends_on": ["peak_1", "prox_1"],
                    "params": {
                        "reversal_pct": cfg.reversal_pct,
                        "min_hold_bars": cfg.min_hold_bars,
                        "invalidation_bars": cfg.invalidation_bars,
                        "invalidation_threshold_pct": cfg.invalidation_threshold_pct,
                        "require_proximity_window": cfg.require_proximity_window,
                        "sl_offset_pct": peak_cfg.sl_offset_pct,
                    },
                },
            },
        }
        context = PluginContext(symbol=symbol, timeframe=timeframe,
                                mode="batch")
        results = self.evaluator.execute_set(definition, df, context)
        grab_recs = ((results.get("grab_1") or {}).get(
            "feature_store_payload") or {}).get("records") or []

        # Schnellzugriff: bar_time (epoch) -> Zeilen-Index (kein index()-Scan)
        times = df["time"].to_numpy()
        idx_by_time = {int(t): i for i, t in enumerate(times)}

        run_id = f"BT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        records: List[GrabberResultRecord] = []
        for r in grab_recs:
            sig = int(r["signal"])
            is_upd = abs(sig) == 2
            i = idx_by_time.get(int(r["bar_time"]))
            if i is None:
                continue
            rec = GrabberResultRecord(
                signal_id=str(uuid.uuid4()),  # stabil (kein hash(), B: Pythons
                # hash() ist pro Prozess randomisiert)
                run_id=run_id,
                timestamp=pd.Timestamp(int(r["bar_time"]),
                                       unit="s").to_pydatetime(),  # B7
                symbol=symbol,
                timeframe=timeframe,
                direction=("BUY" if sig > 0 else "SELL"),
                entry_price=float(df.iloc[i]["close"]),
                sl_price=float(r["sl_price"]),
                peak_price=float(r["peak_price"]),
                peak_bar_index=i,
                is_update=is_upd,
                reversal_pct=(0.0 if is_upd else abs(
                    float(df.iloc[i]["close"]) - float(r["peak_price"]))
                    / float(r["peak_price"]) * 100.0),
                is_yellow_window=bool(r["is_yellow_window"]),
                gate_source="SERIES_UPDATE" if is_upd else "SERIES_TRIGGER",
                # Frage 4: Outcome bleibt PENDING-Platzhalter (späteres Modul)
                outcome_status="PENDING",
                pnl_r_multiple=None,
                max_favorable_exc=None,
                max_adverse_exc=None,
            )
            records.append(rec)
        self.repo.save_records(records)
        return records
```

---

## 9. UI-Integration (EventBus, AnalyticsWindow, ChartWindow, OrderPreviewDialog)

### 9.1 EventBus-Signale (`config/event_bus.py`, additiv)

```python
# config/event_bus.py (additiv zu den bestehenden Signal-Deklarationen)
    # 22.01 (14.08.2026): Peak-Grabber (Frage 5). Der AnalyticsWindow-Button
    # emittiert grabber_toggle(dict) mit {"active", "symbol", "timeframe"} –
    # chart_win subscribed und ruft generisch set_button_active(active) auf
    # allen Indikatoren mit diesem Hook auf (IoC). Live-Trigger/-Updates
    # emittieren grabber_event(GrabberResultRecord) – das AnalyticsWindow
    # persistiert über GrabberRepository und öffnet die OrderPreviewDialog
    # (UI ohne SQL, MVVM).
    grabber_toggle = Signal(dict)
    grabber_event = Signal(object)
```

### 9.2 Button im AnalyticsWindow (`analytics/ui/analytics_win.py`)

Primärer Ort (Frage 5): Toolbar/Control-Zeile des AnalyticsWindow; Alternative: Chart-Overlay-Controlbar. Der Handler emittiert den **Dict-Payload** `{"active", "symbol", "timeframe"}` – die Symbol-/Timeframe-Werte kommen aus dem aktuellen Analytics-Kontext.

```python
# analytics/ui/analytics_win.py (in der Toolbar-/Control-Zeile)
self.btn_grabber_peak = QPushButton("🎯 Peak Grabber", self)
self.btn_grabber_peak.setCheckable(True)
self.btn_grabber_peak.setToolTip(
    "Aktiviert den Peak-Grabber (Trigger/Updates im Yellow Window).")
self.btn_grabber_peak.toggled.connect(self._on_grabber_toggled)

# analytics/ui/analytics_win.py (Handler)
from PySide6.QtCore import Slot

@Slot(bool)
def _on_grabber_toggled(self, active: bool) -> None:
    """Frage 5: leitet den Button-Zustand + Kontext entkoppelt an den Chart
    weiter (IoC, kein Hardcoding auf Indikator-/Fensterklassen)."""
    from config.event_bus import event_bus
    event_bus.grabber_toggle.emit({
        "active": bool(active),
        "symbol": str(self._current_symbol or ""),
        "timeframe": str(self._current_timeframe or ""),
    })
```

### 9.3 ChartWindow-Subscription (`chart/chart_win.py`)

`chart_win` subscribed `grabber_toggle` und routet generisch an alle Indikatoren mit `set_button_active`-Hook (IoC, kein Indikator-Sonderfall, kein `if ind_id == ...`-Branch). Voraussetzung: `ind_peak` ist in der Indikator-Registry `self.indicators` registriert (additiv, §9.5 §2A). **Korrektur:** `_get_active_plugins()` existiert im Code nicht – iteriert wird über `self.indicators.values()`.

```python
# chart/chart_win.py (in der Connect-Zone des __init__)
from config.event_bus import event_bus
event_bus.grabber_toggle.connect(self._on_grabber_toggle)

# chart/chart_win.py (Handler, generisch – kein Indikator-Sonderfall)
def _on_grabber_toggle(self, payload: dict) -> None:
    """Reicht den Grabber-Zustand (active) an alle Indikatoren mit
    set_button_active weiter (Open/Closed – neue Indikatoren brauchen keinen
    chart_win-Branch). symbol/timeframe des Payloads dienen optional der
    Kontext-Prüfung gegen das aktuelle Chart-Symbol."""
    active = bool((payload or {}).get("active", False))
    # 9.5: Eigener ChartButton bleibt synchron (blockSignals gegen Rekursion).
    if self.btn_peak_grabber is not None and self.btn_peak_grabber.isChecked() != active:
        self.btn_peak_grabber.blockSignals(True)
        self.btn_peak_grabber.setChecked(active)
        self.btn_peak_grabber.blockSignals(False)
        self._apply_peak_grabber_button_style()
    # Hinweis: _get_active_plugins() existiert nicht -> self.indicators.
    for plugin in self.indicators.values():
        setter = getattr(plugin, "set_button_active", None)
        if callable(setter):
            try:
                setter(active)
            except Exception as e:
                print(f"WARN [chart_win] set_button_active fehlgeschlagen: {e}")
```

### 9.4 OrderPreviewDialog (`analytics/ui/order_preview_dialog.py`)

Schlankes PySide6-Modal: zeigt die Order-Vorschau, **platzierr keine Order**, enthält **kein SQL** (MVVM, Präambel 4). AnalyticsWindow subscribed `grabber_event` und öffnet/aktualisiert den Dialog.

```python
# analytics/ui/order_preview_dialog.py
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QPushButton


class OrderPreviewDialog(QDialog):
    """Order-Vorschau (keine Platzierung, kein SQL – MVVM)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Order-Vorschau (Peak Grabber)")
        self.setMinimumWidth(420)
        self._label = QLabel(self)
        self._close_btn = QPushButton("Schließen", self)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._close_btn)
        self._close_btn.clicked.connect(self.accept)

    def show_record(self, record) -> None:
        risk_pct = (abs(record.entry_price - record.sl_price)
                    / record.entry_price * 100.0)
        flag = "[UPDATE]" if record.is_update else "[NEW TRIGGER]"
        self._label.setText(
            f"{'=' * 56}\n"
            f"  ORDER PREVIEW {flag}\n"
            f"  Action   : {record.direction.value} {record.symbol} "
            f"@ {record.entry_price:.4f}\n"
            f"  StopLoss : {record.sl_price:.4f} ({risk_pct:.2f}% Risk)\n"
            f"  Peak Ref : {record.peak_price:.4f} | "
            f"Yellow Window: {record.is_yellow_window}\n"
            f"{'=' * 56}\n"
            f"  Run: {record.run_id} | {record.gate_source}")
        self.show()
        self.raise_()
        self.activateWindow()
```

```python
# analytics/ui/analytics_win.py (Subscription, Kontext-Abwärtskompatibel)
from config.event_bus import event_bus
from analytics.ui.order_preview_dialog import OrderPreviewDialog
self._order_preview = None

def _on_grabber_event(self, record) -> None:
    """Öffnet/aktualisiert das Order-Vorschau-Modal (kein SQL)."""
    if self._order_preview is None:
        self._order_preview = OrderPreviewDialog(self)
    self._order_preview.show_record(record)

event_bus.grabber_event.connect(self._on_grabber_event)
```

### 9.5 Aufrufender Button im ChartWindow (`chart/chart_win.py`)

Zusätzlich zum AnalyticsWindow-Button (§9.2) erhält das ChartWindow einen eigenen **aufrufenden Button** `btn_peak_grabber`. Beide Buttons emittieren denselben `grabber_toggle`-Dict-Payload; `chart_win` subscribed selbst (§9.3) und routet generisch zu `ind_peak.set_button_active(active)` – **ein einziger Code-Pfad**. Kein Loop: `set_button_active` emittiert nicht zurück.

> **Korrekturen ggü. Entwurf (14.08.2026):** Der Entwurf verwies auf `charts_win`, `btn_inms_1`-Buttons, statisches `EventBus.emit(...)` und `_get_active_plugins()` – keines davon existiert im Code. Verbindlich ist der reale Stand:
> * Datei/Klasse: `chart/chart_win.py`, `PyTraderChartWindow(QMainWindow)` (kein `charts_win`).
> * Die Indikator-Buttons heißen `btn_indicator_grid_liquidity` („≋", `ind_fixed_grid_proximity`) und `btn_indicator_ma` („MA") – beide in `horizontalLayout_row1` der `ui/chart_win.ui` (selbe Zeile wie `combo_symbol`/`combo_tf`), **keine** `btn_inms_*`.
> * `EventBus` ist ein QObject mit Signal-Attributen – **keine** statische `emit`-Methode: `event_bus.grabber_toggle.emit({...})`.
> * `_get_active_plugins()` existiert nicht – Iteration über `self.indicators.values()` (§9.3).
> * Attribut: `self.current_tf` (nicht `current_timeframe`), `self.current_symbol` (nicht `current_symbol`-Variante im Entwurf).

#### §1 Icon-Empfehlung
* Primär: SVG-Icon `resources/icons/peak.svg` (Strichzeichnung z. B. Mountain/Activity/Trending-up) als `QIcon`.
* Fallback ohne SVG: `self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp)`.
* Textfallback (Muster Nachbar-Buttons „≋"/„MA"): „⛰" bzw. „PK", 28×28.

#### §2A Button erzeugen (additiv)
Platzierung: `ui/chart_win.ui`, `horizontalLayout_row1`, **direkt nach `btn_indicator_ma`** (Muster `btn_indicator_grid_liquidity`/`btn_indicator_ma`: 28×28, checkable). Danach im `__init__` per `findChild` greifen (Muster Zeilen 405–407) und verdrahten:

```python
# chart/chart_win.py (in der Connect-Zone des __init__, nach btn_indicator_ma-Wiring)
self.btn_peak_grabber = self.ui_widget.findChild(QPushButton, "btn_peak_grabber")
if self.btn_peak_grabber is not None:
    self.btn_peak_grabber.setCheckable(True)
    self.btn_peak_grabber.toggled.connect(self._on_peak_grabber_toggled)
    self.btn_peak_grabber.installEventFilter(self)  # Rechtsklick -> Einstellungen
    self._apply_peak_grabber_button_style()
```

Zusätzlich muss `ind_peak` in die Indikator-Registry aufgenommen werden (additiv, sonst findet §9.3 den Hook nicht):

```python
# chart/chart_win.py (self.indicators-Dict, additiv)
self.indicators: Dict[str, BaseIndicator] = {
    "ind_fixed_grid_proximity": FixedGridProximityIndicator(),
    "ind_moving_averages": MultiMovingAverageIndicator(),
    # 22.01: Peak-Grabber (live) - set_button_active-Hook via grabber_toggle.
    "ind_peak": IndPeak(),
}
```

Rechtsklick → `_toggle_settings_dialog("ind_peak")`: `ind_peak` additiv in die `eventFilter`-Tupel-Zeile (Muster Zeilen 479–484) und in `update_indicator_button_style()` (Muster Zeilen 503–510) aufnehmen – sonst bleibt der Button ohne Rechtsklick-/Styling-Anbindung.

#### §2B Handler (EventBus-emit, kein String-emit)
```python
# chart/chart_win.py
from PySide6.QtCore import Slot

@Slot(bool)
def _on_peak_grabber_toggled(self, active: bool) -> None:
    """ChartButton -> EventBus. Gleicher Payload wie AnalyticsWindow-Button
    (9.2); chart_win subscribed selbst (9.3) -> generischer Routing-Pfad.
    Kein Loop: set_button_active emittiert nicht zurueck."""
    event_bus.grabber_toggle.emit({
        "active": bool(active),
        "symbol": str(self.current_symbol or ""),
        "timeframe": str(self.current_tf or ""),
    })
    self._apply_peak_grabber_button_style()
```

#### §2C Styling (checked/unchecked)
Muster `_apply_indicator_button_style` (chart_win.py, `#2e7d32`/`#37474f`), aber **eigene Methode + eigene Akzentfarbe** (Grabber-Modus ≠ Indikator-An/Aus), damit der Zustand sofort sichtbar ist:

```python
# chart/chart_win.py
def _apply_peak_grabber_button_style(self) -> None:
    if self.btn_peak_grabber is None:
        return
    active = self.btn_peak_grabber.isChecked()
    color = "#e65100" if active else "#37474f"  # tiefes Orange = aktiv
    self.btn_peak_grabber.setStyleSheet(
        f"background-color: {color}; color: white; font-weight: bold; "
        f"border-radius: 4px; padding: 3px 10px;")
```

---

## 10. Akzeptanzkriterien & Validierung (headless)

**Test-Harness:** `test/check_2201_peak_grabber.py` + Block in `test/test.py` (kein UI, kein echter MT5-Sync). Alle Prüfungen gegen eine Test-DB unter `test/`.

| ID | Kriterium | Nachweis |
|----|-----------|----------|
| T1 | `grabber_test_results` existiert nach `check_and_init_databases()` in analytics.duckdb, **18 Spalten** + Index `idx_grabber_run` | `information_schema.columns` / `duckdb_indexes()` |
| T2 | Repository-Roundtrip: `save_records()` (18 Werte, B1) → `fetch_records(run_id)` liefert identische Records | Insert/Fetch-Vergleich |
| T3 | **Kernel/Live-Parität (B2/B3):** frisches `PeakGrabberLiveState` + frischer Kernel auf identischem Mini-Datensatz liefern identische Trigger/Update-Bars | Vergleich der Signal-Indices |
| T4 | First-Peak-Skip + IDLE-Start: kein Signal auf Bar 0; Bar 1 erzeugt nur bei New-Peak + Gate ein UPDATE | Kernel-Output auf Mini-Datensatz |
| T5 | Division-by-Zero-Guard (B6): Datensatz mit `high=0`/`low=0` läuft ohne NaN/Inf durch | `np.isfinite` auf SL/Peak-Arrays |
| T6 | Ringpuffer (B5): nach N>buffer_size `_push` sind Zeit/SL konsistent, letzter Slot == aktueller SL | `_ordered_buffers()` |
| T7 | `bootstrap_history` (B4): `cur_high_price/idx/sl` == Batch-Endwerte | Scalar-State nach `_bootstrap_live_state` |
| T8 | **Outcome-Platzhalter (Frage 4):** alle `save_records()`-Rows haben `outcome_status='PENDING'`, `pnl_r_multiple`/`max_favorable_exc`/`max_adverse_exc` = `NULL` | `fetch_records(run_id)` nach `run_series()` |
| T9 | Plugin-Discovery: `PluginRegistry().get("srv_peak_finder")` / `("srv_peak_grabber")` gefunden; `ind_peak` erfüllt `BaseIndicator`-API (`indicator_id`/`display_name`/`default_params`/`parameter_schema`/`calculate`) | `py_compile` + Discovery-Test |
| T10 | EventBus (Frage 5): `grabber_toggle(dict)` emit→Slot (Payload `{"active","symbol","timeframe"}`), `grabber_event(record)` emit→Slot (headless) | Signal-Proxy-Mock |
| T11 | Serientest-Runner: `run_series()` persistiert Records in Test-DB; **Yellow-Ableitung (Frage 3)**: Fallback `True` ohne Proximity-Signal, Zone-Hit ∧ Zeitfenster bei vorhandener `srv_proximity`-Instanz | `fetch_records(run_id)` + Direktaufruf `_derive_yellow_window` |

Abschluss: `py_compile` aller neuen/geänderten Dateien; **keine UI-Tests** (Präambel 2, harte Regel).

---

## 11. Schritt-für-Schritt Umsetzungsanleitung

1. **Schritt 1 – Modelle:** `analytics/engine/peak_models.py` (§2.2) anlegen (Dataclasses, Enums, `sl_factor_*`-Methoden, 18-Feld-Record).
2. **Schritt 2 – DDL:** `db/schema_initializer.py` um `grabber_test_results` + `idx_grabber_run` erweitern (§2.3); additive, idempotente Migration (Outcome-Defaults `'PENDING'`/`NULL`, Frage 4).
3. **Schritt 3 – Kernel:** `analytics/features/definitions/grabber_kernel.py` (§3) anlegen (IDLE-Start, First-Peak-Skip, Guards, 4 Spaces).
4. **Schritt 4 – `srv_peak_finder`:** Plugin-Service (§4A) in `analytics/features/definitions/` mit Schema, `metadata["category"]="Swing Points/Peak Grabber"`, `capabilities`.
5. **Schritt 5 – `srv_peak_grabber`:** Plugin-Service (§4B) mit `depends_on=["srv_peak_finder"]`, `_derive_yellow_window` (Frage 3, Fallback `True`), Kernel-Aufruf, feature_store_payload.
6. **Schritt 6 – (entfällt, Frage 4):** Kein Outcome-Modul in 22.01 – Exit-/Forward-Evaluation folgt als separates Auswertungs-Modul in einem späteren Kapitel.
7. **Schritt 7 – Repository:** `repositories/grabber_repository.py` (§7) mit 18-Spalten-Batch-Upsert (DbPool, Outcome-Spalten `'PENDING'`/`NULL`).
8. **Schritt 8 – Indikator:** `chart/indicators/ind_peak.py` (§5) – `BaseIndicator`-API + `PeakGrabberLiveState` + `PeakFinderLive` + Ringpuffer; `srv_proximity`-Zone-Hit-Bereitstellung im `shared_state` sicherstellen; `latest_proximity_record`-Lese-Helfer in `FeatureStoreReader` ergänzen (nur Lese-Methoden, additiv).
9. **Schritt 9 – UI (Frage 5):** `config/event_bus.py` Signale `grabber_toggle(dict)` + `grabber_event(object)` (§9.1); `analytics/ui/order_preview_dialog.py` (§9.4); `analytics_win.py` Button + Handler (§9.2/9.4); `chart_win.py` Subscription (§9.3) **+ aufrufender Button `btn_peak_grabber` (§9.5, inkl. `ind_peak`-Registry-Eintrag)**.
10. **Schritt 10 – Runner:** `analytics/engine/peak_backtest_runner.py` (§8); Worker-Anbindung nach `ServiceRunWorker`-Muster mit Concurrency-Guard (Präambel 9).
11. **Schritt 11 – Validierung:** `test/check_2201_peak_grabber.py` + Block in `test/test.py` (§10 T1–T11), headless; `py_compile`.
12. **Schritt 12 – Doku:** Implementierungs-Log (§12) erst NACH bestätigter Funktionsfähigkeit durch den Anwender eintragen (Regel 4.5C).

---

## 12. Implementierungs-Log

**14.08.2026 (Umsetzung & Validierung, phase22_step4 - phase22_step11):** Kapitel 22.01 (`ind_peak` & Peak-Grabber, PyTrader Engine) vollständig umgesetzt - alle Schritte 1-11 der Umsetzungsanleitung, headless validiert (keine UI-Tests, keine Regressionstests, Praeambel 2):
- **Schritt 1** (`d33c654`, Tag `phase22_step4`): `analytics/engine/peak_models.py` - Dataclasses/Enums (`PeakConfig`, `PeakGrabberConfig`, `GrabberResultRecord` 18-Feld-Vertrag, `SignalDirection`, `GrabberState`), `sl_factor_*`-Methoden, Outcome-PLatzhalter (Frage 4).
- **Schritt 2** (`3c4f902`, Tag `phase22_step5`): `db/schema_initializer.py` - additive, idempotente DDL `grabber_test_results` (18 Spalten, `outcome_status` DEFAULT 'PENDING', Outcome-Spalten NULL) + Index `idx_grabber_run`.
- **Schritt 3** (`e06ebf0`, Tag `phase22_step6`): `analytics/features/definitions/grabber_kernel.py` - Numba/NumPy-State-Machine (IDLE-Start B2, First-Peak-Skip, Guards B6, Zero-GC), Signale 0/1/2/-1/-2, Zustaende 0-3.
- **Schritte 4+5** (`b71090f`, Tag `phase22_step7`): `srv_peak_finder.py` + `srv_peak_grabber.py` - Plugin-Services mit `metadata["category"]="Swing Points/Peak Grabber"`, `depends_on`, `_derive_yellow_window` (Frage 3: Zone-Hit & Zeitfenster, Fallback True ohne Proximity-Signal).
- **Schritt 7** (`e661952`, Tag `phase22_step8`): `repositories/grabber_repository.py` - 18-Spalten-Batch-Upsert (DbPool, `ON CONFLICT` aktualisiert nur Outcome-Felder).
- **Schritt 8** (`12c82b6`, Tag `phase22_step9`): `chart/indicators/ind_peak.py` - `BaseIndicator`-API + `PeakFinderLive` + `PeakGrabberLiveState` + Ringpuffer (B5) + Bootstrap (B4); `latest_proximity_record`-Lese-Helfer additiv in `analytics/engine/feature_store_reader.py`.
- **Schritt 9** (`b45ca08`, Tag `phase22_step10`): UI-Integration (Frage 5) - `config/event_bus.py` Signale `grabber_toggle(dict)` + `grabber_event(object)`; `analytics/ui/order_preview_dialog.py` (schlankes PySide6-Modal, keine Order, kein SQL - MVVM); `analytics_win.py` Button `btn_grabber_peak` (checkable) + Handler (Payload mit realen Combo-Werten); `chart_win.py` `ind_peak`-Registry-Eintrag (additiv), `grabber_toggle`-Subscription mit generischem `set_button_active`-Routing (IoC, `self.indicators.values()`), eigener aufrufender Button `btn_peak_grabber` (gleicher Payload, `blockSignals`-Sync, eigene Akzentfarbe #e65100), eventFilter/Style-Tupel erweitert; `ui/chart_win.ui` Button `btn_peak_grabber` (28x28, Text "PK") nach `btn_indicator_ma`.
- **Schritt 10** (`4cf5597`, Tag `phase22_step11`): `analytics/engine/peak_backtest_runner.py` - `PeakBacktestRunner.run_series()` (grid_1 -> prox_1 -> peak_1 -> grab_1, `run_id = BT-<ts>`-Konvention, `pd.Timestamp(...).to_pydatetime()`, Outcome PENDING/NULL). Abweichung vom Spec-Snippet: `SignalDirection`-Enum statt Raw-String (`.value`-kompatibel mit OrderPreviewDialog).
- **Schritt 11 - Validierung (headless, `test/check_2201_peak_grabber.py` + Block in `test/test.py`):** T1 Schema (18 Spalten + Index + Default PENDING + NULL), T2 Repository-Roundtrip (18 Werte, Feld-Identitaet), T3 Kernel/Live-Paritaet (B2/B3), T4 First-Peak-Skip + IDLE-Start, T5 Div-by-Zero-Guard (B6), T6 Ringpuffer (B5), T7 Bootstrap (B4), T8 Outcome-Platzhalter (PENDING/NULL nach `run_series`), T9 Plugin-Discovery + BaseIndicator-API, T10 EventBus emit->Slot (headless, Signal-Proxy-Mock), T11 run_series-Persistenz + Yellow-Ableitung (Fallback True / Zone-Hit & Zeitfenster). **23/23 Checks PASS.** `py_compile` OK fuer alle neuen/geaenderten Dateien (15 Dateien); `chart_win.ui` XML-validiert. Alle Test-DBs unter `test/` (Regel: keine Test-DBs im Root/data).
- **Schritt 12 (dieser Eintrag, `phase22_step12`):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**Offen (bewusst, Frage 4):** Outcome-Modul (`peak_outcome.py`) - Exit-/Forward-Evaluation folgt als separates Auswertungs-Modul in einem spaeteren Kapitel (Schritt 6 entfaellt in 22.01).

**14.08.2026 (22.01b - User-Anweisungen 1-4a + 4b, `phase22_step13`):** Peak-Grabber-Feinabstimmung nach 22.01 - Anwenderanweisungen umgesetzt, headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Anweisung 1:** `analytics/ui/analytics_win.py` - Peak-Button `btn_grabber_peak` + Handler `_on_grabber_toggled` + Toggle-Bindung entfernt; `grabber_event`-Subscription bleibt als passiver Konsument (OrderPreviewDialog).
- **Anweisung 2:** `chart/indicator_dialog.py` - neue Methode `_indicator_sets()`: Prop-Fenster zeigt nur noch Sets mit `indicator_id == current.indicator_id` ODER Sets, die ausschliesslich Plugins aus `service_plugin_ids` des Indikators enthalten (strenger Filter). Angewendet in `refresh_service_set_list`, `_item_list_names`, `_item_exists`, `_item_save_as`. AnalyticsWindow bleibt global/ungefiltert.
- **Anweisung 3:** keine Anpassung noetig (`show_signals` existierte bereits im `_PEAK_SCHEMA`).
- **Anweisung 4a (Viewback-Parameter):** `analytics/engine/peak_models.py` (`PeakConfig.viewback_bars=3`); `analytics/features/definitions/srv_peak_finder.py` - Rolling-Window statt kumulativem Max/Min (monotone Deques, O(n)), Records NUR an Peak-Aenderungen (neuer Peak ODER Expiry), Supersession aelterer Records innerhalb viewback_bars (`delete_bar_times` im Payload), Records aelter als viewback bleiben persistent, `window_tail` im shared_state fuer Live-Bootstrap; `analytics/features/feature_builder.py` - `store_plugin_payload` loescht `delete_bar_times` VOR dem Upsert (Helfer `_delete_plugin_bar_times`, scoped auf symbol/timeframe/feature_id/instance_hash); `chart/indicators/ind_peak.py` - Schema + `_build_set_definition` (viewback_bars -> peak_1), `PeakFinderLive` auf Rolling-Window umgestellt, Bootstrap via `window_tail`, Live-Bar-Zaehler (`_live_bar_base`/`_live_bar_idx`/`_last_live_rounded`) fuer Expiry pro BAR statt pro Tick; `analytics/engine/peak_backtest_runner.py` - `viewback_bars` durchgereicht.
- **Anweisung 4b (Grabber-Rework, aufgeloeste Interim-Divergenz):** `chart/indicators/ind_peak.py` - `PeakFinderLive.update_scalar()` liefert zusaetzlich die Richtungs-Flags `h_dir`/`l_dir` (+1/-1: echter neuer Fenster-Peak vs. Expiry des alten Extremums); `PeakGrabberLiveState.process_tick_or_bar()` loest die Arm-/Update-/Invalidate-Logik NUR bei echten neuen Peaks aus (Hoch steigt / Tief faellt), Expiry aktualisiert die SL-Referenz stumm (KEIN Event), ARMED-Reversal-Check als separater `if`-Block. Damit keine spurious BUY_UPDATE-Events mehr an den Expiry-Bars 3/4 (strikte Kernel/Live-Paritaet zum kumulativen Kernel).
- **Validierung (headless, `test/`):** `check_2201_peak_grabber.py` **24/24 PASS** (T3 auf strikte Paritaet umgestellt, EXPIRY_BARS entfernt; neues T3b High-Expiry stumm), `check_2201_viewback.py` **11/11 PASS** (V4 auf 4er-Rueckgabe angepasst), `check_2201_parity.py`/`check_2201_calc.py`/`check_2201_runner.py`/`check_2201_reader.py`/`check_2201_schema.py` PASS, Bloecke 22.01 + 22.01b in `test/test.py` alle PASS, `py_compile` OK fuer alle geaenderten Dateien.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**14.08.2026 (22.01c - Bugfixing 1-4, `phase22_step14`):** Peak-Grabber-Bugfixing-Runde auf Basis der 4 User-Fragen, headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Bugfix 1 (Live-Overlay-Gating, "Peak-Linien trotz deaktiviertem Indikator"):** `chart/indicators/ind_peak.py` - `get_live_overlays()` zeichnet die Live-SL-Kreise NUR noch, wenn der Grabber-Modus aktiv ist (`_live_state.is_btn_active`, via `btn_peak_grabber`/`grabber_toggle`) UND die jeweilige Serie sichtbar ist (`show_sl_high`/`show_sl_low`). Vorher wurden die Kreise unabhaengig vom Toggle-Zustand bei jedem Tick gezeichnet, sobald `cur_*_sl != NaN` war; der Finder/die State-Machine laeuft weiter (nur das Zeichnen wird gegated). JS-Seite: `chart/js/04_live_updates.js` - `updateLiveCandle()` ruft `applyLiveOverlays(c.overlays || [])` IMMER auf (auch leer) und `applyLiveOverlays()` erfasst jetzt auch den LEEREN Satz in der Change-Detection: Der erste leere Aufruf entfernt die alten Live-Circles der letzten Live-Zeit aus `_gridCirclesCache` (danach stumm) - keine verwaisten Peak-Kreise mehr nach Deaktivierung.
- **Erkenntnis 2 (zwei getrennte Datenquellen, keine Code-Aenderung):** Der Chart berechnet die SL-Linien In-Memory ueber `ServiceSetEvaluator.execute_set()` (ind_peak.calculate); der Analytics-Service-Picker liest den persistierten `feature_store` aus `analytics.duckdb` (`fetch_service_tf_status`). Ohne HistoricalScanner/LiveAnalyzer-Lauf ist die DB leer -> "No Data" im Picker, waehrend der Chart die In-Memory-Rechnung zeigt. Konsistentes Soll-Verhalten (kein Render-Fehler), in der Doku festgehalten.
- **Bugfix 3 (Order-Vorschau in den Live-Chart verlagert):** `chart/chart_win.py` - `event_bus.grabber_event` wird jetzt im CHART-Fenster konsumiert: neuer Handler `_on_grabber_event` (Lazy-Singleton `OrderPreviewDialog`, `show_record()` aktualisiert denselben Dialog - mehrere Trigger kurz nacheinander erzeugen KEIN Doppel-Fenster/kein Crash, das erste Fenster bleibt offen); `analytics/ui/analytics_win.py` - `grabber_event`-Subscription + `_on_grabber_event` + `OrderPreviewDialog`-Import entfernt (Analytics ist kein Konsument mehr, dort fehlt der Live-Kontext). Der Trigger selbst war korrekt: `ind_peak.update_live_candle()` emittiert `grabber_event` gegated durch `is_btn_active` (Quelle = Peak-Indikator, wie vom User gefordert).
- **Erkenntnis 4 (Finder-Zeichnung korrekt, keine Code-Aenderung):** `srv_peak_finder` zeichnet exakt wie beschrieben: waagerechter Strich/Marker auf SL-Hoehe der Treffer-Bar (`sl_high = peak_high * (1 + sl_offset_pct/100)`), Supersession innerhalb `viewback_bars` (`delete_bar_times`), aeltere Records bleiben persistent. Eine 2-Punkt-Strich-Erweiterung (t ± halbe Barbreite) wurde verworfen, da `_time_real_to_cont` ein reines Dict-Mapping ist (keine Interpolation) und Zwischenzeiten ungemappt blieben.
- **Validierung (headless, `test/`):** neue `check_2201c_fixes.py` **8/8 PASS** (G1-G5 Overlay-Gating: is_btn_active=False -> leer, show_sl_high/low-Flags je Serie; O1-O2 OrderPreviewDialog-Lazy-Singleton: 2x show_record idempotent, Dialog bleibt offen), neue `check_2201c_overlay_clearing.js` (node, VM-Sandbox laedt die ECHTE `04_live_updates.js`) **4/4 PASS** (T1 Live-Zeit-Ersatz, T2 leeres Clearing, T3 Change-Detection stumm, T4 Live-Zeit-Wechsel verdraengt alte). Block 22.01c in `test/test.py` ergaenzt (importlib + node-Subprocess). `py_compile` OK fuer alle geaenderten Dateien (`chart/chart_win.py`, `chart/indicators/ind_peak.py`, `analytics/ui/analytics_win.py`, `test/test.py`, `test/check_2201c_fixes.py`), `node --check` OK fuer `chart/js/04_live_updates.js`.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**14.08.2026 (22.01d - User-Anweisungen 1-3, `phase22_step15`):** Peak-Grabber-Umbau - keine Zeichnung ohne Store-Daten (Anw. 1), SL-Striche NIE verbunden (Anw. 2), Trigger als Dreiecke statt Kreise (Anw. 3). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Anweisung 1 (keine Zeichnung bei deaktiviertem/leerem Indikator):** `chart/indicators/ind_peak.py` - `calculate()` liest AUSSCHLIESSLICH persistierte Service-Daten aus dem feature_store (keine In-Memory-Fantasie-Linien); leerer Store (vor Servicelauf) -> leeres Ergebnis + `_reset_live_state()` (raeumt Live-State, Live-Trigger, Bar-Zaehler, Ringpuffer); `_btn_active` ueberlebt den Reset und wird beim naechsten Bootstrap via `set_button_active` uebertragen (User muss den Grabber nicht neu aktivieren).
- **Anweisung 2 (Peak Finder - Striche NIE verbunden):** `chart/indicators/ind_peak.py` - `calculate()` erzeugt je Finder-Record eine SEPARATE LineSeries `sl_high_<t0>`/`sl_low_<t0>` mit 2 Punkten auf gleichem SL-Value (t0 -> Zeit der naechsten Bar aus der df-Zeit-Map, letzte df-Bar = 1 Punkt) - keine gemeinsame Sammel-Serie mehr (die vorher die Punkte ueber Stunden hinweg verband).
- **Anweisung 3 (Peak Grabber - KEINE Kreise, Orderpunkt = Dreieck):** `chart/indicators/ind_peak.py` - `get_live_overlays()` zeichnet nur noch den letzten Live-Trigger als Dreieck (arrowDown=SELL bei peak_high / arrowUp=BUY bei peak_low); Proximity-Circles & Grid-Lines sind reine Berechnungshilfen und werden nie gezeichnet; `calculate()` rendert srv_peak_grabber-Records als hit_circles-Dreiecke (arrowDown/arrowUp). Deaktivierter Grabber -> keine Overlays (raeumt Trigger beim Deaktivieren).
- **Neue Lesemethode:** `analytics/engine/feature_store_reader.py` - `fetch_plugin_records(symbol, timeframe, feature_id, limit=20000)` (read-only, feature_data-JSON + bar_time als Wanduhr-Epoch, aufsteigend sortiert).
- **Blocker-Analyse (Conn-Handling im Test):** `store_plugin_payload()` schliesst eine UEBERGEGEBENE Connection selbst (Bestandsverhalten `own_connection=True` bei `con != None`, dokumentiert in `test/test.py` Block 17/18/19/24) - KEIN Produktionsbug (kein Caller uebergibt con); der Test `check_2201d_fixes.py` oeffnet daher pro Store-Aufruf eine frische Wegwerf-Connection. Isoliert verifiziert: zwei parallele Connections zu derselben DuckDB-Datei ueberleben einander (Debugging-Skripte `tmp_conn_test3.py`, danach geloescht).
- **Validierung (headless, `test/`):** neue `check_2201d_fixes.py` **16/16 PASS** (G1-G6 get_live_overlays: deaktiviert leer / SELL arrowDown bei peak_price / BUY arrowUp / ohne Trigger leer / ohne Live-State leer / keine SL-Kreise; C1-C3 calculate: leerer Store -> leer + Live-State-Reset, Striche 2 Punkte gleicher Value NIE verbunden, Endpunkt = naechste Bar-Zeit 2060, keine Sammel-Serie 'sl_high', Trigger-Dreiecke arrowDown bei peak_high 102.0 / arrowUp bei peak_low 98.0; O1 OrderPreviewDialog 2x show_record idempotent). Block 22.01d in `test/test.py` ergaenzt (importlib-Muster 22.01c). `py_compile` OK fuer alle geaenderten Dateien (`chart/indicators/ind_peak.py`, `analytics/engine/feature_store_reader.py`, `test/test.py`, `test/check_2201d_fixes.py`). Test-DB `check_2201d.duckdb` in `test/` (Regel: keine Test-DBs im Root/data), wird vom Test selbst aufgeraeumt.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**14.08.2026 (22.01e - Performance-Fix chart_win: ewiger Chart-Aufbau + Maus-Pan blockiert, `phase22_step16`):** Bugfixing-Modus - User-Meldung "Grafik dauert ewig aufzubauen inkl. Skalen" + "Grafik laesst sich nicht mit Maus verschieben (Loops?)". Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Ursache (Kern):** `ind_peak.calculate()` (22.01d) erzeugte seit dem Store-Umbau **EINE LineSeries pro Finder-Record** (`sl_high_<t0>`/`sl_low_<t0>`). `renderLineSeries` (chart/js/03_chart_rendering.js) ruft pro Eintrag `chart.addSeries()` auf - bei 617 realen Records also **1.234 LWC-Series** pro Chart-Rebuild. Jede addSeries triggert Timescale/PriceScale-Neuberechnung -> Chart-Aufbau dauert ewig, LWC ist ueberlastet -> Maus-Panning/Interaktion blockiert.
- **Fix 1 (`chart/indicators/ind_peak.py`, User-Anweisung 2 bleibt erfuellt):** Die SL-Striche als **ZWEI Sammel-Series** (`sl_high`/`sl_low`) statt einer Serie pro Record. Zwischen zwei Strichen wird ein **Luecken-Marker `{time, value: None}`** eingefuegt (LWC-null = Luecke) -> die Striche sind NIE verbunden (keine Fantasie-Verbindung ueber Stunden). Die Luecken-Zeit ist immer die **naechste echte df-Bar-Zeit** (`_next_bar_after`, binaere Suche) - kein Phantom-Slot in der Timescale (22.01-Lektion). Edge: direkt benachbarte Records (Strich-Ende == naechster Strich-Start) -> 1-Punkt-Strich (selten, minimale Verbindung, keine doppelten Zeitstempel).
- **Fix 2 (`analytics/engine/feature_store_reader.py`):** `fetch_plugin_records()` um optionale Zeitfenster-Filter **`up_to_epoch`/`from_epoch`** erweitert (SQL `EXTRACT('epoch' FROM bar_time)::BIGINT <= ? / >= ?`); `ind_peak.calculate()` begrenzt die DB-Last auf das df-Fenster (`up_to = max(df.time)`) - Records jenseits der letzten Bar werden im Render-Payload ohnehin verworfen.
- **Fix 3 (`chart/chart_win.py`):** `_collect_render_payload()` verwirft LineSeries, deren Datenpunkte nach dem Zeitfenster-Filter (Tier-1) vollstaendig ausserhalb liegen (generisch, Open/Closed) - vorher gingen auch leere Series als addSeries an LWC.
- **Fix 4 (`chart/indicators/ind_peak.py`, Tick-Pfad):** `_is_current_bar_yellow()` - `FeatureStoreReader(db_path=None)` auf Default korrigiert (vorher warf `DbPool.get(None)` bei JEDEM Tick eine Exception -> stiller Fallback immer True, Yellow-Gate greift jetzt wirklich) + **Pro-Candle-Cache** (`_yellow_rounded`/`_yellow_value`: Query nur 1x pro neuer gerundeter Bar, nicht pro Tick); Cache-Reset in `_reset_live_state`.
- **Validierung (headless, `test/`):** `check_2201d_fixes.py` erweitert auf **19/19 PASS** (G1-G6, C1-C3, C4 up_to_epoch-Filter wirkt, C4b from+up_to kombiniert, C2e Performance-Fix: KEINE Serie pro Record, C2b/C2c/C2d auf 2-Sammel-Series-Semantik mit null-Luecken umgestellt; Test-df lueckenlos 1000..4000 im 60s-Raster). Performance-Smoke auf echter analytics.duckdb + 10k M1-Bars: `calculate()` **0.061s**, **2 LineSeries** (sl_high/sl_low je 761 Punkte inkl. 72 Luecken) statt 1.234 Series. `py_compile` OK fuer alle geaenderten Dateien. Kein JS geaendert (LWC unterstuetzt `value: null` nativ; `_clean_nan` laesst None durch -> JSON null).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).
**14.08.2026 (22.01f - Bugfix "Linien trotz ausgeschalteter Indikatoren", phase22_step17):** User-Meldung: SL-Linien/Marker werden gezeichnet, obwohl der PK-Button AUS ist. Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Ursache:** Der PK-Button (`btn_peak_grabber`) und der Plugin-Zustand (`IndPeak._btn_active`) waren von `indicators_state['ind_peak']['active']` entkoppelt. `_collect_render_payload()` rendert ind_peak NUR bei `active=True` - die DB (symbol_tf_states fuer SILVER H1/M1/M5/M10/M2, BTCUSD M1) sagte aber `active=true`, der Button zeigte false -> SL-Linien/Marker wurden gezeichnet, obwohl der Grabber optisch AUS war.
- **Fix (`chart/chart_win.py`, +57 Zeilen):** neue `_sync_peak_button_from_state()` (synchronisiert PK-Button + Plugin-`_btn_active` aus `indicators_state`); `_on_grabber_toggle()` zieht `indicators_state['ind_peak']['active']` nach (persistiert via `save_state` + rendert neu); Sync-Aufrufe in `__init__`, `on_symbol_changed`, `on_tf_changed`, `_on_indicator_params_updated`; CRLF normalisiert.
- **Validierung (headless, `test/`):** neue `check_2201f_state_sync.py` **21/21 PASS** (S1-S6: Start-Sync, State False->Button unchecked, State True->Button checked, save+render-Gate, Settings-Dialog sync, Idempotenz); `check_2201d_fixes.py` weiter **22/22 PASS**. `py_compile` OK fuer `chart/chart_win.py`.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**14.08.2026 (22.01g - Bugfixing 1-6 Peak-Grabber nach 22.01f, phase22_step18):** User-Meldung: (1) Skala veraendert sich bei On/Off-Toggle, (2) wild verbundene SL-Linien (nur sl_low), (3) Orderpunkt/Updates 30$ ueber der Bar, (4) H1/5M-Probleme, bei 5M gar keine Orderpunkte, (5) Orderfenster kommen auf 5M oft hintereinander, (6) Grafikeinfrieren. Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Bugfix 1 (Skala springt beim On/Off):** `chart/indicators/ind_peak.py` - SL-Serien (`sl_high`/`sl_low`) bekommen `no_autoscale: True`; `chart/js/03_chart_rendering.js` - `renderLineSeries()` setzt bei `line.no_autoscale` `autoscaleInfoProvider: function() { return null; }` -> die Serie nimmt NICHT an der Preisskalen-Autoscale teil, die Skala bleibt beim Toggle unveraendert (Indikator additiv).
- **Bugfix 2 (wild verbundene SL-Linien):** Ursache: LWC-v5-Default `LineType.Simple` verbindet `null`-Punkte hindurch -> zwei SL-Striche werden diagonal verbunden (nur sl_low auffaellig, weil sl_high-Records seltener sind). Fix (`chart/js/03_chart_rendering.js`): `renderLineSeries()` setzt `lineType: LightweightCharts.LineType.WithGaps` bei addSeries UND applyOptions -> `{time, value: null}` erzeugt eine ECHTE Luecke, die Striche bleiben isolierte waagerechte Segmente. Die Python-Daten waren korrekt (Test `check_sl_stroke_bug.py` beweist Gap-Punkte im Fenster).
- **Bugfix 3 (Orderpunkte 30$ ueber der Bar):** Ursache: Batch-Marker nutzten `peak_high`/`peak_low` (Rolling-Fenster-Extrema, bei SILVER oft >5$ daneben) statt des Bar-Preises. Fix (`chart/indicators/ind_peak.py`): `_order_price()` berechnet den Orderpunkt aus der TRIGGER-BAR (`bar_ohlc`-Map aus df) - SELL = Bar-High * (1 + sl_offset_pct/100), BUY = Bar-Low * (1 - sl_offset_pct/100); Fallback auf persistierte Peak-Preise. Live-Pfad: `get_live_overlays()` nutzt jetzt `entry_price` der Trigger-Bar * (1 +/- offset) statt `trig.peak_price` (Rolling-Extremum).
- **Bugfix 4 (5M keine Orderpunkte):** gleiche Ursache wie Bugfix 3 - die alten Marker-Preise (28-121) lagen ausserhalb der sichtbaren Skala; mit bar-basierten Preisen (~65) liegen sie direkt an der Bar (analytics.duckdb: 434 M5-Grabber-Records, Trigger {1:11, -1:119} existierten).
- **Bugfix 5 (Orderfenster-Flut):** `chart/chart_win.py` - `_on_grabber_event()` bekommt ein Bar-Gate (`_last_grabber_bar_key`, TF-gerundete Bar-Zeit): NUR EIN Orderfenster pro Bar, mehrere Trigger/Updates derselben Bar werden unterdrueckt; Reset bei Symbol-/TF-Wechsel.
- **Bugfix 6 (Grafikeinfrieren):** Folge von Bugfix 5 (Dialog-Storm bei jedem M5-Tick) + 22.01e-Series-Fix; mit dem Bar-Gate und WithGaps behoben (kein eigener Code, verifiziert).
- **Validierung (headless, `test/`):** neue `check_2201g_fixes.py` **16 PASS/0 FAIL** (no_autoscale-Flag, Gap-Punkte im Fenster, keine Diagonalen im Fenster - Filter wie `_collect_render_payload`); neue `check_2201g_live_marker.py` **14 PASS/0 FAIL** (Fake-Reader mit Grabber-Records IM df-Bereich: SELL/BUY/UPDATE-Marker an der Bar, nicht am Rolling-Extremum); `check_2201d_fixes.py` auf neue Bar-Semantik angepasst **22/22 PASS** (G2/G3/C3b/C3c pruefen jetzt Bar-Preis statt peak_high/peak_low); `check_2201f_state_sync.py` **21/21 PASS**; Live-Preis-Check (Sell 65*1.0015=65.0975 / Buy 64.5*0.9985=64.4032) und Bar-Gate-Logik OK; `node --check` OK fuer alle 6 JS-Dateien; HTML-Template-Check (WithGaps + no_autoscale eingebettet); `py_compile` OK fuer `chart/chart_win.py`, `chart/indicators/ind_peak.py`.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).


**14.08.2026 (22.01h - Bugfix "Objekte vor vorhandenen Kerzen" (LWC-Phantom-Slots), phase22_step19):** Bugfixing-Modus - User-Meldung: Chart-Objekte (SL-Striche/Marker) erscheinen weit links VOR den aeltesten Kerzen (z. B. 2013 auf H1/D1, obwohl die Kerzen erst 2024 beginnen). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Ursache:** Der Python-Filter `_collect_render_payload()` haengt an den Tier-1-Fenster-Bounds (`_js_window_first_real`/`_js_window_last_real`). In manchen Pfaden (Indikator-Toggle/Parameter-Aenderung VOR dem ersten vollstaendigen Refresh, direkt nach Start oder nach Symbol/TF-Wechsel) waren diese Bounds `None` -> der Zeitfenster-Filter hatte KEINE Grenze und der komplette historische Record-Bestand (persistiert aus frueheren Service-Laeufen mit vollem Historien-Scan, ohne Range-Cleanup) ging ungefiltert an JS -> LWC erzeugt fuer Zeiten weit ausserhalb des Kerzenbereichs leere Timescale-Slots (Phantom-Slots), die Objekte erscheinen vor den Kerzen.
- **Fix 1 (`chart/chart_win.py`):** Neuer Guard vor jedem `_collect_render_payload`-Aufruf: Sind die Fenster-Bounds `None`, werden sie defensiv aus dem Datenpuffer abgeleitet (`_derive_js_window_bounds_from_buffer()`, idempotent: setzt nur fehlende Bounds, `TIER1_WINDOW`-Begrenzung, `last_real`-Kante) -> der Filter hat IMMER eine Grenze, auch vor dem ersten vollstaendigen Refresh.
- **Fix 2 (`chart/indicators/ind_peak.py`):** `fetch_plugin_records()` fuer `srv_peak_finder`/`srv_peak_grabber` bekommt zusaetzlich `from_epoch = int(min(df["time"]))` (Untergrenze = aelteste df-Bar) -> db-seitiger Zuschnitt auf den darstellbaren Bereich; der Tier-1-Filter faengt zwar auch, der Zuschnitt reduziert zusaetzlich DB-Last/JSON-Parsing (22.01e-Muster erweitert).
- **Fix 3 (`chart/js/03_chart_rendering.js`):** Defense-in-Depth auf JS-Seite: neue Funktion `_overlayTimeBounds()` (Kerzen-Zeitbereich aus `rawCandleData`); `applyChartRenderPayload()` filtert `p.lines` und `p.hit_circles` VOR dem Rendering auf `[min, max]` -> Punkte ausserhalb des Kerzenbereichs (Raw-Epochs, Phantom-Slots) erreichen LWC gar nicht erst.
- **Validierung (headless, `test/`):** bestehende JS-Node-Harnesses (`diag_prod_repro.js`, `diag_lwc_crash.js`) decken den Guard ab; `node --check` OK fuer alle geaenderten JS-Dateien; `py_compile` OK fuer `chart/chart_win.py`, `chart/indicators/ind_peak.py`.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**14.08.2026 (22.01i - Bugfix "[JS ERROR] Uncaught Error: Value is null | L7:797" + veraltete TwoTier-Chunk-Antwort, phase22_step20):** Bugfixing-Modus - User-Meldung: `[JS ERROR] Uncaught Error: Value is null | L7:797` im Chart, zeitgleich `[TwoTier] Veraltete Chunk-Antwort verworfen (id=58 != 62)`. Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Root-Cause (zweifelsfrei verifiziert):** `L7:797` = `ensureNotNull(null)` in LWC-5.2.0-Dist. Exakter Stack (Test H in `test/diag_lwc_crash.js` reproduziert, identisch zur Produktion): `a (ensureNotNull)` -> `xt.Line [as Mh]` (SeriesBarColorer lineStyleFn) -> `Ce.xb`/`Ce.DM` (line-pane-view-base `_fillRawPoints`) -> Render-Zyklus. Mechanik: LWC v5 `setData` verlangt NACH ZEIT SORTIERTE Serien-Daten; `PlotList.setData` speichert die Reihen in Input-Reihenfolge, aber `PlotList.valueAt()` (SeriesColorer) binaersucht nach dem sortierten `row.index` -> unsortierte Input-Daten -> binaere Suche verfehlt -> `ensureNotNull(null)` -> "Value is null"-Crash beim Rendern der LineSeries.
- **Nicht die Ursache (ausgeschlossen):** trailing/leading `value: null` (WithGaps), Marker mit Raw-Epoch ausserhalb, doppelte Zeitstempel, Live-Pfad (`updateLiveCandle` fasst LineSeries nie an), Produktions-`_stroke_series` selbst (statisch monoton, `t1 == t_next`-Sonderfall vermeidet Duplikate; `test/diag_prod_repro.js` PASS mit exakter Produktions-Nachbildung), `fetch_plugin_records` sortiert `ORDER BY bar_time ASC` (feature_store_reader.py).
- **Wahrscheinlichster Produktions-Trigger:** Ein Record, dessen `bar_time` NICHT in `_time_real_to_cont` liegt (z. B. Mid-Bar-Zeitstempel oder Records aus frueheren Service-Laeufen mit vollem Scan), ueberlebt den Zeitfenster-Filter -> bleibt als RAW-Epoch (~1.7e9) zwischen kont-Zeiten (~1e6) -> UNSORTIERTE LineSeries-Daten -> Crash. Die Chunk-Ansicht zeigte denselben Fehler zeitgleich, da der Chunk-Pfad (`applyOlderDataChunk`) den `_overlayTimeBounds`-Guard (22.01h) NICHT hatte.
- **Fix 1 (`chart/js/03_chart_rendering.js`):** `renderLineSeries()` sortiert die Daten VOR `series.setData()` defensiv aufsteigend nach Zeit und entfernt Duplikate (letzter Wert gewinnt = exakt LWC-Row-Overwrite); ungueltige Punkte (`time` keine finite Zahl) werden gefiltert. Geschuetzt sind BEIDE Pfade (Full-Update + Chunk, da beide durch `renderLineSeries` laufen).
- **Fix 2 (`chart/js/06_two_tier.js`):** `applyOlderDataChunk()` bekommt den `_overlayTimeBounds()`-Guard (analog `applyChartRenderPayload`, 22.01h): `rp.lines`/`rp.hit_circles` werden vor dem Rendering auf den Kerzenbereich gefiltert -> Raw-Epochs/Phantom-Slots werden im Chunk-Delta verworfen.
- **Fix 3 (`chart/js/01_core.js`):** `window.onerror` loggt jetzt zusaetzlich den Stack (`[JS ERROR] Stack: ...`), damit beim naechsten Repro die exakte LWC-Call-Site sichtbar ist.
- **Validierung (headless, `test/`):** `node --check` OK fuer `01_core.js`, `03_chart_rendering.js`, `06_two_tier.js`. `test/diag_lwc_crash.js`: Tests A-G/I PASS; Test H (UNSORTIERTE Zeiten, SL-Strich-Muster) crasht auf ROHER LWC-`setData` = erwartete Negativ-Kontrolle (beweist: ohne Fix crasht exakt dieses Muster). `test/diag_prod_repro.js` erweitert um `scenarioUnsortedFix` **PASS**: unsortierte SL-Strich-Daten + Raw-Epoch mitten zwischen kont-Zeiten durch den ECHTEN `renderLineSeries` -> abgefangenes `setData`-Array aufsteigend sortiert + keine doppelten Zeitstempel (Monotonie-/Dedup-Check), kein Render-Crash; `applyOlderDataChunk` mit Raw-Epoch im Delta -> Guard filtert -> kein Crash. `py_compile` OK fuer geaenderte Python-Dateien.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**15.08.2026 (23.01 - Architektur-Map fuer Bugfix-Entkopplung, phase23_step1):** Grundlagen-Schritt fuer das Ziel, Bugfix-Zeit und Token-Kosten von ~1.000 s auf ~100 s zu senken (Wechsel auf DeepSeek-Flash-Routine-Bugfixes erst NACH der Entkopplung). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Ziel:** Jeder Bugfix-Prompt startet mit der Landkarte und liest nur noch die minimalen Datei-Sets statt ganzer God-Files -> weniger Token, schnellere Iteration.
- **Umgesetzt:** neue Datei `../Architektur_map.md` mit Teil A (Layering & Invarianten: DB -> Repositories -> Engine -> UI, EventBus, DbPool, Wanduhr-Garantie, `srv_`/`ind_`-Naming), Teil B (Domaenen-Karte aller 117 Py- + 6 JS-Dateien mit Zeilenzahlen und 1-Zeilen-Verantwortlichkeit), Teil C (Bug-Routing-Tabelle: 24 Symptom-Bereiche -> minimale Datei-Sets in Lese-Reihenfolge + Test-Validatoren), Teil D (Hotspots/Quer-Kopplungen & God-File-Split-Vorschlaege fuer Top-5), Teil E (Wartung der Karte). Basis: Analyse von 117 Py-Dateien / 44.105 Zeilen + 6 JS-Dateien / 1.684 Zeilen; 9 God-Files ~45 % des Codes (`service_win.py` 3.264, `master_tree.py` 2.511, `service_selector_dialog.py` 2.414, `heatmap_widget.py` 2.483, `feature_store_reader.py` 2.410, `indicator_dialog.py` 1.893, `analytics_view_model.py` 1.886, `chart_win.py` 1.630, `analytics_win.py` 1.500); Quer-Kopplungen erfasst (chart_win -> serviceui+analytics, analytics_win -> 3x serviceui, service_selector_model -> chart.indicators+serviceui, ind_peak -> analytics.engine, srv_trend_*/srv_swing_momentum -> chart, service_win -> alle Schichten); vorhandene Entkopplungs-Bausteine erfasst (EventBus `config/event_bus.py`, Plugin-Registry, Mixins `ServiceParamColumnsMixin`/`ContentScrollMixin`/`NamedItemActionsMixin`, JS-Hook-System, Repository-Muster).
- **Nutzen:** Typischer Fix = 1-3 Dateien a 200-400 Zeilen statt 3-5 Dateien a 800-3.000 Zeilen; die Karte macht die Lese-Reihenfolge deterministisch (gezieltes Erst-Lesen statt Volltext-Scan).
- **Naechste Schritte (nur auf Anweisung):** 23.02 Root-Orphans sortieren (`db_service.py`, `symbol_repository.py`, `window_state_repository.py`, `analytics_profile_repository.py` -> `repositories/`; `statistic_win.py`, `properties_win.py` -> `ui/`) - reine Ordnung, keine Logikaenderung; 23.03 God-File-Splits (Top-5, inkrementell).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Abschluss von Schritt 1 der Hauptanweisung (Architektur-Landkarte zuerst, dann inkrementelle God-File-Splits; Modellwechsel auf Flash erst NACH der Entkopplung).

**15.08.2026 (23.02 - Root-Orphans sortiert: repositories/ & ui/, phase23_step2):** Reine Ordnung ohne Logikaenderung: 6 Root-Orphans in die Pakete verschoben. Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **git mv (History erhalten):** `symbol_repository.py`, `window_state_repository.py`, `analytics_profile_repository.py`, `db_service.py` -> `repositories/`; `statistic_win.py`, `properties_win.py` -> `ui/` (Commit `c164b68`, 17 Dateien, +113/-53).
- **Root-Shim `db_service.py`:** reiner Re-Export aus `repositories.db_service` (alle Namen inkl. `main()`); CLI-Einstieg `python db_service.py` (MT5-Sync) und test.py-Teil-30-Fassaden-Identitaetschecks bleiben gueltig. Es ist KEINE Logik im Shim.
- **Interne Pfade der verschobenen Dateien angepasst:** `window_state_repository` (`BASE_DIR` eine Ebene hoeher fuer `APP_DB_PATH`), `analytics_profile_repository` (importiert jetzt direkt aus `db.db_pool`/`db.db_utils`), `statistic_win` (UI-Pfad `BASE_DIR / "statistic_win.ui"`), `properties_win` (`db_path -> BASE_DIR.parent / data`).
- **13 Import-Stellen in 8 Importern aktualisiert:** `main.py`, `state_manager.py`, `analytics/ui/analytics_win.py`, `chart/chart_win.py`, `analytics/engine/analytics_view_model.py`, `serviceui/symbols_win.py`, `serviceui/service_win.py`, `ui/window_manager.py`; zusaetzlich interner Alt-Import in `ui/statistic_win.py` (im Scan gefunden) und `test/test.py` (4 Stellen inkl. Mehrzeilen-Import `_APR39`).
- **Paket-Docstrings aktualisiert:** `repositories/__init__.py` (neue Mitglieder, Invariante: kein Import von main.py/db_service.py bleibt erfuellt - Repos importieren direkt aus `db.db_pool`/`db.db_utils`) und `ui/__init__.py` (WindowManager + statistic_win + properties_win).
- **Validierung (headless, `test/`):** Alt-Import-Scan im gesamten Quellcode (ohne docs/): 0 Treffer; `py_compile` OK fuer alle 18 geaenderten Dateien; neuer gezielter Check `test/check_2302_migration.py` **30/30 PASS** (Zielpfade, Alt-Root-Entfernung, Shim-Export inkl. main, keine Alt-Importe, Repository-Invariante); Import-Smoke-Test mit `.venv`-Python: alle verschobenen Module + Shim importierbar (`get_symbol_repository`, `WindowStateRepository`, `AnalyticsProfileRepository`, `main` vorhanden).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).

**15.08.2026 (23.03 - God-File-Split #1: indicator_dialog.py, phase23_step3):** Erster God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** 5 Top-Level-Elemente (Z61-320: DialogServiceSetRunWorker, _ServiceStack, _jsonify_style_objects, _PresetItemAdapter, _ServiceSetItemAdapter) + IndicatorSettingsDialog (Z323-2127, 52 Methoden). Nur chart_win.py importiert IndicatorSettingsDialog; die 5 Helfer werden ausschliesslich intern genutzt -> sicherer Split ohne externen Caller.
- **Neue Datei chart/indicator_dialog_support.py (10.522 Bytes):** enthaelt die 5 Support-Klassen 1:1 (keine Logik-Aenderung). Deterministisch per test/build_2303_support.py aus den Original-Zeilen extrahiert, Block-Identitaet per AST/Text-Check verifiziert.
- **Hauptdatei chart/indicator_dialog.py (88.859 -> 78.744 Bytes, -10.115):** Imports getrimmt (QThread/Signal/QSize aus QtCore entfernt -> nur Qt; QStackedWidget aus QtWidgets entfernt; NamedItemAdapter aus named_item_actions-Import entfernt -> nur NamedItemActionsMixin) und der 260-Zeilen-Block durch einen Import ersetzt: from chart.indicator_dialog_support import (DialogServiceSetRunWorker, _ServiceStack, _jsonify_style_objects, _PresetItemAdapter, _ServiceSetItemAdapter).
- **Validierung (headless, test/):** py_compile OK fuer beide Dateien; AST-Check: Hauptdatei enthaelt nur noch IndicatorSettingsDialog (genau 1 Klasse), 0 Code-Referenzen auf entfernte Symbole (QStackedWidget/QSize/QThread/Signal/NamedItemAdapter); Import-Smoke mit .venv-Python: beide Module importierbar, alle 5 Support-Symbole aufloesbar; test/build_2303_remove_block.py bestaetigt Block-Identitaet 1:1 (9.856 Bytes).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).
**15.08.2026 (23.03 - God-File-Split #2: chart_win.py, phase23_step4):** Zweiter God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** chart_win.py (92.461 Bytes/1.815 Zeilen) ist ein God-File mit einer Klasse PyTraderChartWindow (Z215-1808, 1.594 Zeilen, ~55 Methoden) plus 7 Top-Level-Helfer. Die 5 Worker-/Serializer-/Bridge-Klassen (WebEngineConsolePage, ChartBridge, ChartDataSerializer, GridDataSerializer, OlderDataWorker, Z103-212) sind bereits top-level, werden aber ausschliesslich von der Window-Klasse genutzt (kein externer Caller im gesamten Quellcode) -> sicherer erster Split-Schritt ohne Logik-Eingriff in die Window-Klasse (konsistent mit Split #1-Muster).
- **Neue Datei chart/chart_win_workers.py (4.869 Bytes/124 Zeilen):** enthaelt die 5 Klassen 1:1 (keine Logik-Aenderung), Header nach Split #1-Muster, UTF-8 ohne BOM, LF. Deterministisch per test/build_2303_workers.py aus den Original-Zeilen extrahiert; Block-Identitaet (110 Zeilen/4.559 Bytes) textuell 1:1 verifiziert.
- **Hauptdatei chart/chart_win.py (92.461 -> 88.024 Bytes, -4.437):** nur 3 Aenderungen: (1) QtCore-Import bereinigt (QObject, QThread entfernt - wandern in die neue Datei), (2) QWebEngineCore-Import-Zeile entfernt, (3) Import 'from chart.chart_win_workers import ChartBridge, ChartDataSerializer, GridDataSerializer, OlderDataWorker, WebEngineConsolePage' nach dem symbols_win-Import eingefuegt. Line-Endings (CRLF/LF-Mischung) unveraendert erhalten.
- **Validierung (headless, test/):** py_compile OK fuer beide Dateien; AST-Check: chart_win.py enthaelt nur noch find_null_fields/_clean_nan/PyTraderChartWindow, neue Datei exakt die 5 Klassen; Import-Smoke mit .venv-Python: beide Module importierbar, alle 5 Referenzen in chart_win.py korrekt aufgeloest (Klassen aus chart.chart_win_workers); git diff: exakt 2 insertions/114 deletions, kein Kollateralschaden; Scan ueber alle Py-Dateien (ohne docs/): keine andere Datei referenziert die verschobenen Klassen.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).
**15.08.2026 (23.03 - God-File-Split #3: chart_win.py-Mixins, phase23_step5):** Dritter God-File-Split der Entkopplungs-Roadmap. Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** Die Window-Klasse PyTraderChartWindow (52 Methoden nach Split #2) wurde per AST-Scan in 5 thematische Gruppen zerlegt (INDICATOR 17, RENDER 6, REFRESH 8, TWOTIER 9, SYMBOLTF 12) plus Cross-Referenz-Analyse (Methoden-Callgraph + Modul-Globals pro Gruppe inkl. try/except-Importen). `_normalize_indicators_state` (referenziert PyTraderChartWindow._LEGACY_IND_ID/_NEW_IND_ID), `__init__` und `eventFilter` bleiben in der Hauptklasse (Zirkularimport-Vermeidung). `find_null_fields`/`_clean_nan` werden von REFRESH/TWOTIER genutzt -> nach chart/chart_win_workers.py verschoben.
- **5 neue Mixin-Dateien:** chart/chart_win_indicators.py (ChartIndicatorMixin, 17 Methoden), chart/chart_win_render.py (ChartRenderMixin, 6), chart/chart_win_refresh.py (ChartRefreshMixin, 8), chart/chart_win_twotier.py (ChartTwoTierMixin, 9), chart/chart_win_symboltf.py (ChartSymbolTfMixin, 12) - 1:1 extrahiert (keine Logik-Aenderung), deterministisch per test/build_2303_mixins.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen, @Slot() inklusive), Methoden-Identitaet per AST/Text-Check verifiziert.
- **Hauptdatei chart/chart_win.py (88.024 -> 22.026 Bytes, -65.998):** Basis erweitert auf `QMainWindow, ChartIndicatorMixin, ChartRenderMixin, ChartRefreshMixin, ChartTwoTierMixin, ChartSymbolTfMixin`; 5 Mixin-Importe ergaenzt; 52 Methoden + 2 Helfer entfernt. Verbleibende Mitglieder: closed_signal, _LEGACY_IND_ID/_NEW_IND_ID, _normalize_indicators_state, __init__, eventFilter. Line-Endings unveraendert.
- **chart/chart_win_workers.py erweitert (+31):** find_null_fields/_clean_nan (aus chart_win.py uebernommen, inkl. math-Import) + Docstring ergaenzt.
- **Validierung (headless, test/):** py_compile OK (6 Dateien); AST-Check: Hauptklasse exakt 6 Mitglieder, jede Mixin exakt 1 Klasse mit erwarteten Methoden; 52/52 Methoden byte-identisch; Import-Smoke mit .venv-Python: chart.chart_win + ui.window_manager importierbar, MRO korrekt (PyTraderChartWindow -> QMainWindow -> ... -> 5 Mixins -> object), alle 55 Methoden erreichbar; test/check_2303_selfcalls.py: alle self.X()-Calls aufloesbar (nur Qt-Basis-Methoden wie setWindowTitle/pos/size sind extern); Scan ueber alle Py-Dateien (ohne docs/): keine andere Datei referenziert die verschobenen Helfer.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).


**15.08.2026 (23.04 - God-File-Split #4: service_win.py-Mixins, phase23_step6):** Vierter God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** service_win.py (172.339 Bytes/3.490 Zeilen) ist das groesste God-File des Projekts - eine Klasse ServiceWindow (Z89-3490, 93 Methoden), CRLF-Line-Endings. Importeure sind nur serviceui/__init__.py und ui/window_manager.py (+ Test-Dateien); kein Zirkularimport-Risiko in serviceui/. Methoden-Callgraph: 1 grosse Komponente (72 Methoden via __init__-Verdrahtung) -> thematische Gruppierung statt rein graph-basierter Zerlegung (Muster Split #3). `_qt_valid`-Guard (shiboken6) wird von Run-/Editor-Methoden genutzt -> in beide Mixins dupliziert. Restliche God-File-Kandidaten fuer spaetere Splits: master_tree (2.665), heatmap_widget (2.656), feature_store_reader (2.602), service_selector_dialog (2.560), analytics_view_model (2.051).
- **5 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** serviceui/service_win_run.py (ServiceRunMixin, 17 Methoden - Run-Worker, Sync-Guard, Fortschritt, TF-Status, Badges, Full-Sync; 23.480 Bytes), serviceui/service_win_tree.py (ServiceTreeMixin, 9 - MasterTree-Handler, Folder-Operationen, Kategorie-Info; 11.998), serviceui/service_win_editor.py (ServiceEditorMixin, 23 - Parameter-/Set-Editor, Save, Dirty-State, Set-Editor, Beschreibungen; 36.152), serviceui/service_win_sets.py (ServiceSetsMixin, 9 - Set-Verwaltung inkl. Papierkorb; 15.373), serviceui/service_win_presets.py (ServicePresetMixin, 18 - Presets/Varianten/Doc-Log, Purge, Duplicate; 36.841). Deterministisch per test/build_2304_swin.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching aus Modul-Importen; `_qt_valid`-Guard auto-eingefuegt wo noetig). Reihenfolge in jeder Mixin == Original-Quellreihenfolge (Fix im Build-Skript: `_toolbar_add_service` an Position 1 der editor-Gruppe, vor `_plugin_config`; vorher stand er an Position 13).
- **Hauptdatei serviceui/service_win.py (171.804 -> 52.795 Bytes, -119.009):** Klassendeklaration erweitert auf `ServiceWindow(ServiceParamColumnsMixin, ContentScrollMixin, NamedItemActionsMixin, ServiceRunMixin, ServiceTreeMixin, ServiceEditorMixin, ServiceSetsMixin, ServicePresetMixin, PersistentWindow)`; 5 Mixin-Importe nach dem new_set_dialog-Import eingefuegt; 76 Methoden entfernt. Verbleibende Mitglieder (5 Klassenvariablen + 17 Methoden): INSTANCE_ID, _keep_history_on_close, DIALOG_GEOMETRY_KEY, _exact_fit_to_content, _min_window_width, __init__, save_state, restore_state, _apply_reflow_size, resize_to_clamped_content, apply_screen_cap, get_persistent_symbol, get_persistent_timeframe, _apply_persistent_filters, _refresh_timeframe_combo, _on_symbol_changed, _wire_selector_toolbar, open_symbols_window, _refresh_symbol_combo, log, _on_log_context_menu, closeEvent. Line-Endings (CRLF) unveraendert erhalten; Original-Backup unter test/backup_service_win_pre_mixins_20260815_185123.py (172.339 Bytes).
- **Validierung (headless, test/):** py_compile OK (6 Dateien); AST-Check: Kern exakt 22 Mitglieder, jede Mixin exakt 1 Klasse mit erwarteten Methoden; 76/76 Methoden byte-identisch (normalisiert); test/check_2304_allorder.py: ALLE 5 Mixins in Original-Quellreihenfolge; Import-Smoke mit .venv-Python (test/smoke_2304_full.py): serviceui/__init__ + alle 5 Mixins + service_win + ui.window_manager importierbar, MRO korrekt (ServiceWindow -> 5 Mixins -> PersistentWindow -> QMainWindow), main.py importiert nur ui.window_manager; test/check_2304_selfcalls.py + test/check_2304_basemixins.py: alle externen self.X()-Calls in Basis-Mixins verifiziert (ContentScrollMixin/PersistentWindow/ServiceParamColumnsMixin); `_qt_valid`-Guards in run+editor (test/check_2304_localimports.py); alle gemeldeten refs sind lokale Variablen/Imports (test/check_2304_imports.py); test/check_2304_endings.py: CRLF beibehalten (946 CRLF, 0 LF-only, kein BOM).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.05 - God-File-Split #5: feature_store_reader.py-Mixins, phase23_step7):** Fuenfter God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** analytics/engine/feature_store_reader.py (122.318 Bytes/2.602 Zeilen) - eine Klasse FeatureStoreReader (Z173-2602, 46 Methoden), CRLF-Line-Endings, kein BOM. 17 Modul-Konstanten (Z46-154: BASE_DIR, DB_ANALYTICS, DB_MARKET, SCHEMA_VERSION_DEFAULT, SENTINEL_NATIVE, DOW_LABELS, DOW_WEEK_LABELS, HOURS_PER_DAY, DAYS_PER_WEEK, DIM_MAPPINGS, HEATMAP_DIMENSIONS, HEATMAP_AGGREGATIONS, MAX_HEATMAP_CELLS, OHLCV_SNAPSHOT_LIMIT, DAILY_OHLC_MAX_DAYS, TF_SECONDS, CANONICAL_TIMEFRAME_ORDER) + Modul-Funktion canonical_tf_sort (Z157-170, nur intern von fetch_service_tf_status/get_available_timeframes genutzt). KRITISCH: Die Konstanten werden extern importiert (analytics_view_model 7, heatmap_widget 5, analytics_worker 2, analytics_repository 1, heatmap_page 3, ind_peak TF_SECONDS, service_selector_dialog TF_SECONDS, service_win BASE_DIR+TF_SECONDS, mtf_fc_provider, feature_builder, common_widgets) -> Re-Export in Hauptdatei zwingend. Klassen-Nutzer: analytics_repository, analytics_view_model, analytics_worker, mtf_fc_provider, service_selector_model, analytics_win, table_page, ind_peak, common_widgets, service_selector_dialog, service_win, service_win_run, feature_builder. canonical_tf_sort MUSS in die Support-Datei (Mixin-Nutzung -> sonst Zirkularimport ueber die Mixins).
- **Neue Datei analytics/engine/feature_store_reader_constants.py (141 Zeilen):** 17 Konstanten (Z45-154 1:1) + canonical_tf_sort (Z157-170 1:1), eigener Docstring, Importe from pathlib import Path + from typing import List. Hauptdatei re-exportiert alle 18 Namen via from analytics.engine.feature_store_reader_constants import (...).
- **6 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** analytics/engine/feature_store_reader_meta.py (FeatureStoreMetaMixin, 8 Methoden - Meta-Cache, Connection, Epoch; 207 Zeilen), feature_store_reader_filter.py (FeatureStoreFilterMixin, 9 - Normalisierung, Filter, Formatierung; 305), feature_store_reader_query.py (FeatureStoreQueryMixin, 8 - Row-/Column-/Key-Fetch, Verfuegbarkeitslisten; 479), feature_store_reader_heatmap.py (FeatureStoreHeatmapMixin, 4 - Heatmap-Fetch klassisch+generisch; 492), feature_store_reader_ohlcv.py (FeatureStoreOhlcvMixin, 11 - OHLCV-Snapshots, Execution-Dates/Hashes, TF-Status; 637), feature_store_reader_plugin.py (FeatureStorePluginMixin, 5 - No-Data-Varianten, Proximity/Plugin-Records, exists; 464). Deterministisch per test/build_2305_fsr.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching; Support-Importe automatisch ergaenzt). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__: Klassendeklaration FeatureStoreReader(FeatureStoreMetaMixin, FeatureStoreFilterMixin, FeatureStoreQueryMixin, FeatureStoreHeatmapMixin, FeatureStoreOhlcvMixin, FeatureStorePluginMixin).
- **Hauptdatei analytics/engine/feature_store_reader.py (122.318 -> 4.219 Bytes, -118.099):** 45 Methoden entfernt, 17 Konstanten + canonical_tf_sort durch Re-Export-Import ersetzt (keine Doppel-Definition - lokale canonical_tf_sort-Definition entfernt), 6 Mixin-Importe nach db_service-Import eingefuegt. Verbleibend: Docstring, Importe, Re-Export, Klasse mit __init__ (db_path, Meta-Cache-Init).
- **Validierung (headless, test/):** build_2305_fsr.py (py_compile 8 Dateien OK; AST-Check Kern==["__init__"] + je Mixin exakt die vorgesehenen Methoden; alle 45 Methoden byte-identisch normalisiert; Konstanten-Block Z45-154 + canonical_tf_sort Z157-170 byte-identisch); check_2305_fsr_imports.py (Import-Smoke mit .venv-Python 3.14.5: Hauptdatei, alle 17 Konstanten + canonical_tf_sort via Re-Export, MRO = 6 Mixins, Instanz FeatureStoreReader(), 14 externe Nutzer importieren, direkter Import canonical_tf_sort/TF_SECONDS/DOW_LABELS funktioniert, TF_SECONDS["M15"]==900).
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B6: feature_store_reader 2.410 -> 93 Zeilen + 7 neue Dateien (constants 141, meta 207, filter 305, query 479, heatmap 492, ohlcv 637, plugin 464) mit 1-Zeilen-Verantwortlichkeit; Teil C Zeile 11: Routing auf Hauptdatei + Mixins (_query/_ohlcv/_heatmap/_filter) aktualisiert; Teil D2: Kandidat als GESPLITTET markiert; Stand-Header auf 23.05.
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.06 - God-File-Split #6: master_tree.py-Mixins, phase23_step8):** Sechster God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2, nach feature_store_reader). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** serviceui/master_tree.py (138.623 Bytes/2.511 Zeilen) - eine Klasse MasterTree(QTreeWidget, Z116-2665, 58 Methoden), CRLF-Line-Endings, kein BOM. 25 Modul-Konstanten (Z83-182: MIME_CATEGORY_MOVE, ROLE_SET_ID, ROLE_SERVICE_ID, ROLE_INSTANCE_HASH, ROLE_IS_FOLDER, ROLE_KIND, TYPE_SET, TYPE_SERVICE, TYPE_FOLDER, TYPE_CATEGORY, CHECKBOX_ZONE_WIDTH, MAX_BADGE_CELL_CHARS, BADGE_TRUNCATE_ICON, INFO_BUTTON_WIDTH/HEIGHT/MARGIN, BADGE_COLUMN_WIDTH, BRANCH_ZONE_WIDTH, LEVEL_INDENT, ...) + Modul-Funktion isValid (try/except, Z185-194) + Modul-Funktion _expandable_label (Z195-199) + Klasse TreeItemIterator (Z2628-2665). KRITISCH: isValid/_expandable_label/TreeItemIterator werden von mehreren Mixins genutzt, TreeItemIterator zusaetzlich extern importiert (service_selector_dialog, service_selector_widget, service_win_editor, service_win_tree, serviceui/__init__.py) -> Re-Export in Hauptdatei zwingend. Statische Methoden im Original: _mode_suffix (Z651, importiert PluginRegistry aus feature_builder), _fmt_last_exec, _set_label_mode (Z810, import re).
- **Neue Datei serviceui/master_tree_constants.py (167 Zeilen/7.815 Bytes):** 25 Konstanten (Z83-182 1:1) + isValid (try/except 1:1) + _expandable_label (1:1) + TreeItemIterator (Z2628-2665 1:1). Importe: from PySide6.QtCore import Qt, from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, from typing import Optional. Hauptdatei re-exportiert alle 27 Namen via from serviceui.master_tree_constants import (...).
- **6 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** serviceui/master_tree_build.py (MasterTreeBuildMixin, 16 Methoden - Baumaufbau Sets/Kategorien/Plugins/Clones, Badges, Modus-Label; 717 Zeilen/35.904 Bytes), master_tree_dragdrop.py (MasterTreeDragDropMixin, 9 - Drag&Drop, Ordner-Anlage/Umbenennung; 275/11.643), master_tree_ui.py (MasterTreeUiMixin, 9 - Expanded-State, Item-Buttons, Dirty-Marker, Checkable; 298/13.797), master_tree_checks.py (MasterTreeChecksMixin, 10 - Checkbox-Sync, Set-Zustand, checked-Abfragen; 524/25.733), master_tree_events.py (MasterTreeEventsMixin, 6 - Kontextmenue, drawBranches, Mouse-Events, Auswahl-Events; 499/26.878), master_tree_selection.py (MasterTreeSelectionMixin, 8 - Selection-APIs, Restore, Select-by; 139/5.860). Deterministisch per test/build_2306_master.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching; Support-Importe automatisch ergaenzt). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__ + Signal-Deklarationen (Z201-306): Klassendeklaration MasterTree(QTreeWidget, MasterTreeBuildMixin, MasterTreeDragDropMixin, MasterTreeUiMixin, MasterTreeChecksMixin, MasterTreeEventsMixin, MasterTreeSelectionMixin).
- **Build-Fixes (test/build_2306_master.py):** (1) Verifikations-Bug isValid - Funktion liegt verschachtelt im except-Zweig, daher ast.walk statt Modul-Body; (2) _expandable_label-Slice-Bug - End-Index 195-83 -> 195-82; (3) Echter Fehler: TreeItemIterator (separate Klasse am Dateiende) wird von _collect_expanded_state (master_tree_ui.py) genutzt, Name-Matching konnte sie nicht aufloesen (NameError im Smoke-Test) -> TreeItemIterator wandert in master_tree_constants.py, Hauptdatei re-exportiert sie, damit externe Importe (service_win_editor u. a.) weiter funktionieren.
- **Hauptdatei serviceui/master_tree.py (138.623 -> 18.003 Bytes, -120.620):** 58 Methoden entfernt, 25 Konstanten + isValid + _expandable_label + TreeItemIterator durch Re-Export-Import ersetzt (keine Doppel-Definition), 6 Mixin-Importe eingefuegt. Verbleibend: Docstring, Importe (unveraendert), Re-Export, Klasse mit __init__ + allen Signal-Deklarationen (Klassenvariablen bleiben im Kern).
- **Validierung (headless, test/):** build_2306_master.py (py_compile 8 Dateien OK; AST-Check Kern==["__init__"] + je Mixin exakt die vorgesehenen Methoden; alle 58 Methoden byte-identisch normalisiert; Konstanten-Block Z83-195 + _expandable_label + TreeItemIterator Z2628-2665 byte-identisch); check_2306_master_imports.py (Import-Smoke mit .venv-Python 3.14.5: Hauptdatei + alle 27 Re-Export-Namen, Support-Datei direkt, MRO = MasterTree -> QTreeWidget -> Qt-Kette -> 6 Mixins, Offscreen-Instanz MasterTree(DummyModel()) -> __init__ inkl. _populate (leerer Baum) OK, TreeItemIterator leerer Baum, _expandable_label-Logik, alle 5 externen Nutzer importieren; QFontDatabase-Warnung = harmloser Hinweis).
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B8: master_tree 2.511 -> 318 Zeilen + 7 neue Dateien (constants 167, build 717, dragdrop 275, ui 298, checks 524, events 499, selection 139) mit 1-Zeilen-Verantwortlichkeit; Teil C Zeile 9: Routing auf Hauptdatei + Mixins (_build/_events/_selection/_dragdrop/_ui/_checks, Konstanten _constants) aktualisiert; Teil D2: Kandidat als GESPLITTET markiert; Stand-Header auf 23.06 (144 Py-Dateien / 49.759 Zeilen).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.07 - God-File-Split #7: analytics_view_model.py-Mixins, phase23_step9):** Siebter God-File-Split der Entkopplungs-Roadmap (Top-5 laut Architektur-Landkarte Teil D2, nach master_tree). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** analytics/engine/analytics_view_model.py (98.605 Bytes/1.886 Zeilen, LF-only, kein BOM) - eine Klasse AnalyticsViewModel(QObject, Z78-1881, 87 Methoden). 11 Signal-Assignments (Klassenvariablen: data_ready, query_failed, busy_changed, active_profile_changed, dirty_changed, profile_saved, profile_deleted, profiles_available, missing_services_detected, params_restored, feature_ids_changed) + 4 Modul-Konstanten (Z50-61: DEBOUNCE_MS, DEFAULT_BINS, DEFAULT_LIMIT, _ALL_QUERIES). 7 Properties (params, active_profile, profiles, is_dirty, workspace_layout, restore_generation, max_lookback_limit) + 10 Staticmethods (_normalize_field_pairs, _pairs_to_feature_ids, _normalize_feature_ids, _normalize_instance_hashes, _flatten_payload, _clamp_zoom, _sanitize_dim, _emit_profile_changed, _clamp_bins, _clamp_limit). Lokale Imports (ServiceSelectorModel in 7 Methoden: _resolve_feature_ids Z626, resolve_service_label Z1640, resolve_service_display_name Z1698, checked_variant Z1763, service_execution_datetime Z1818, resolve_instance_hashes Z1847, _no_data_presets_snapshot Z1910) bleiben lokal in den Methoden (kein Zirkularimport). Nur 1 externer Klassen-Import: analytics/ui/analytics_win.py; keine externen Konstanten-Importe.
- **Neue Datei analytics/engine/analytics_view_model_constants.py (30 Zeilen/1.159 Bytes):** 4 Konstanten (Z50-61 1:1). Importe: from analytics.engine.analytics_worker import (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC, QUERY_SCATTER, QUERY_DISTRIBUTION, QUERY_FEATURES). Hauptdatei re-exportiert alle 4 Namen via from analytics.engine.analytics_view_model_constants import (...).
- **6 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** analytics/engine/analytics_view_model_query.py (AnalyticsViewModelQueryMixin, 18 Methoden - Query-Orchestrierung, Refresh, Async-Worker-Management, Shutdown; 253 Zeilen/11.785 Bytes), _setters.py (AnalyticsViewModelSetterMixin, 9 - Symbol, Timeframes, Sort/Service-Modus, Range, Epoch; 180/8.052), _fields.py (AnalyticsViewModelFieldMixin, 9 - Feature-/Feld-Selektion & Normalisierung (field_pairs, feature_ids, hashes); 244/10.620), _heatmap.py (AnalyticsViewModelHeatmapMixin, 17 - Heatmap-Config, Smart-Presets, Zoom/Projektion, Spalten/Bins/Limit/Settings; 296/13.235), _profile.py (AnalyticsViewModelProfileMixin, 13 - Profil-CRUD, Apply/Restore, Workspace, EventBus-Emit; 427/21.809), _resolve.py (AnalyticsViewModelResolveMixin, 20 - Properties & Service-Aufloesung (Labels, Zeit, Hashes); 586/27.779). Deterministisch per test/build_2307_avm.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching; Support-Importe automatisch ergaenzt). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__ + 11 Signal-Deklarationen: Klassendeklaration AnalyticsViewModel(QObject, AnalyticsViewModelQueryMixin, AnalyticsViewModelSetterMixin, AnalyticsViewModelFieldMixin, AnalyticsViewModelHeatmapMixin, AnalyticsViewModelProfileMixin, AnalyticsViewModelResolveMixin).
- **Build-Fix (test/build_2307_avm.py):** Verifikations-Bug - Konstanten-Check suchte nach DEBOUNCE_MS statt dem Zeilen-Start-Kommentar `# QTimer-Debounce` (Original beginnt Z50 mit Kommentar; im Support liegt der Block NACH dem Import-Header) -> Check auf `# QTimer-Debounce` gefixt, Original per `git checkout` wiederhergestellt, Build erneut -> BUILD FERTIG gruen (py_compile 8 Dateien OK, AST-Check Kern==["__init__"], alle 86 Methoden byte-identisch, Konstanten-Block Z50-61 byte-identisch).
- **Hauptdatei analytics/engine/analytics_view_model.py (100.656 -> 11.607 Bytes, -89.049, 225 Zeilen):** 86 Methoden entfernt, 4 Konstanten durch Re-Export-Import ersetzt (keine Doppel-Definition), 6 Mixin-Importe nach dem event_bus-Import eingefuegt. Verbleibend: Docstring, Importe (unveraendert), Re-Export, Klasse mit __init__ + allen 11 Signal-Deklarationen (Klassenvariablen bleiben im Kern).
- **Validierung (headless, test/):** build_2307_avm.py (py_compile 8 Dateien OK; AST-Check Kern==["__init__"] + je Mixin exakt die vorgesehenen Methoden; alle 86 Methoden byte-identisch normalisiert; Konstanten-Block Z50-61 byte-identisch); check_2307_avm_imports.py (Import-Smoke mit .venv-Python: Hauptdatei + 4 Re-Export-Konstanten, Support-Datei direkt (Werte identisch: DEBOUNCE_MS=250, DEFAULT_BINS=20, DEFAULT_LIMIT=5000, _ALL_QUERIES=6), MRO = AnalyticsViewModel -> QObject -> ... -> 6 Mixins, 6 Mixin-Dateien einzeln importierbar, AST Kern __init__ + 11 Signale, externer Nutzer analytics_win importiert, Properties/Statics via MRO-Suche erhalten, Instanz-Methoden-Stichprobe via Mixins - SMOKE TEST PASS). Zusaetzlich beim Commit-Check: Constants-Datei auf Platte fehlerhaft vorgefunden (enthielt den Import-Header der Hauptdatei statt des Konstanten-Blocks -> Zirkularimport im Smoke); korrigiert auf den 1:1-Z50-61-Block (aus git HEAD extrahiert), Import-Smoke danach erneut PASS.
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B6: analytics_view_model 1.886 -> 225 Zeilen + 7 neue Dateien (constants 30, query 253, setters 180, fields 244, heatmap 296, profile 427, resolve 586) mit 1-Zeilen-Verantwortlichkeit; Teil C Zeilen 11-13: Routing auf Hauptdatei + Mixins (Zeile 11: _query/_setters/_fields/_resolve; Zeile 12: _profile; Zeile 13: _heatmap/_resolve) aktualisiert; Teil D2: Kandidat als GESPLITTET markiert; Stand-Header auf 23.07 (151 Py-Dateien / 49.949 Zeilen).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.08 - God-File-Split #8: service_selector_dialog.py-Mixins, phase23_step10):** Achter God-File-Split der Entkopplungs-Roadmap (Benutzer-Prioritaet nach master_tree + analytics_view_model). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** serviceui/service_selector_dialog.py (120.922 Bytes/2.561 Zeilen, CRLF (2560 CRLF, 0 LF-only), kein BOM) - 2 Klassen: _DialogParamHost (Z127-329, 8 Methoden, Basis ServiceParamColumnsMixin) + ServiceSelectorDialog (Z332-2560, 73 Methoden inkl. __init__ Z365-614, Basis QDialog). 4 Modul-Konstanten (Z112-124: DIALOG_GEOMETRY_KEY, PANEL_BUFFER, BODY_SPACING, TREE_DEFAULT_WIDTH) -> muessen in constants-Datei (genutzt von __init__ UND Mixin-Methoden Z2329/2331/2498/2528/2545/2550, sonst Zirkularimport). 4 Signal-Klassenvariablen bleiben im Kern (services_selected, selection_ids_requested, selection_hashes_requested, splitter_changed). _DialogParamHost wird von __init__ UND Mixin-Methoden (Z793, Z2232, Z2429) genutzt -> eigene host-Datei noetig (Hauptdatei re-exportiert, Muster master_tree_constants/indicator_dialog_support). Keine externen Importe von _DialogParamHost; einziger externer Klassen-Import: analytics/ui/analytics_win.py. Lokale Imports (PluginRegistry, FeatureBuilder, generate_instance_hash, master_tree-Typen, service_set_utils-Funktionen, QTimer, TF_SECONDS_MAP) bleiben in den Methoden.
- **Neue Datei serviceui/service_selector_dialog_constants.py (22 Zeilen/1.131 Bytes):** 4 Konstanten (Z112-124 1:1). Hauptdatei re-exportiert alle 4 Namen via from serviceui.service_selector_dialog_constants import (...).
- **Neue Datei serviceui/service_selector_dialog_host.py (217 Zeilen/10.215 Bytes):** _DialogParamHost (8 Methoden, Z127-329 1:1, eigene Importe: QPushButton, ServiceSelectorModel, event_bus, ServiceParamColumnsMixin); Hauptdatei re-exportiert _DialogParamHost.
- **6 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** serviceui/service_selector_dialog_selection.py (ServiceSelectorDialogSelectionMixin, 10 Methoden - Filter/Apply, Info-Dialoge (Service/Kategorie), Resolve-Info; 198 Zeilen/8.210 Bytes), _presets.py (ServiceSelectorDialogPresetMixin, 12 - Varianten/Presets (Speichern, Finden, Duplizieren, Umbenennen), Purge (legacy/data-only), Delete-Complete, Doc-Log, Instance-IDs; 468/19.983), _sets.py (ServiceSelectorDialogSetMixin, 13 - Set-/Ordner-CRUD (Anlegen, Umbenennen, Loeschen), Service hinzufuegen/entfernen/verschieben, Drag&Drop-Handler; 336/13.671), _run.py (ServiceSelectorDialogRunMixin, 18 - Checkbox-Filter, Tree-Selection-Details, Run-Symbol/Timeframe/Service/Set/Plugin/Kategorie, Run-Worker, TF-Combo, Live-Parameter-Merge, Fortschritt; 529/23.890), _badge.py (ServiceSelectorDialogBadgeMixin, 7 - closeEvent, TF-Start/Ende, Badge-Scope, Badge-Bar-Refresh, Modell-Refresh; 222/9.708), _panel.py (ServiceSelectorDialogPanelMixin, 12 - Param-Panel (Rebuild/Apply/Clear), Dialog-Fit/Resize, Splitter (Move/Sizes), Geometrie (Restore/Save), done; 388/17.794). Deterministisch per test/build_2308_ssd.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching; Support-Importe automatisch ergaenzt). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__ + 4 Signal-Deklarationen: Klassendeklaration ServiceSelectorDialog(QDialog, ServiceSelectorDialogSelectionMixin, ServiceSelectorDialogPresetMixin, ServiceSelectorDialogSetMixin, ServiceSelectorDialogRunMixin, ServiceSelectorDialogBadgeMixin, ServiceSelectorDialogPanelMixin).
- **Hauptdatei serviceui/service_selector_dialog.py (120.663 -> 22.375 Bytes, -98.288, 414 Zeilen, CRLF erhalten):** 72 Methoden entfernt, Konstanten-Block Z112-124 durch Re-Export-Import ersetzt (keine Doppel-Definition), Host-Block Z127-329 entfernt (per Text-Suche), 6 Mixin-Importe nach `from serviceui.service_set_utils import variant_run_entries` eingefuegt. Verbleibend: Docstring, Importe (unveraendert), Re-Exports (Konstanten + _DialogParamHost), Klasse mit __init__ + allen 4 Signal-Deklarationen (Klassenvariablen bleiben im Kern).
- **Validierung (headless, test/):** build_2308_ssd.py (py_compile 9 Dateien OK; AST-Check Kern==["__init__"] + je Mixin exakt die vorgesehenen Methoden (10/12/13/18/7/12); alle 72 Methoden byte-identisch normalisiert; Konstanten-Block Z112-124 byte-identisch; Host-Block Z127-329 byte-identisch; Line-Endings: alle 9 Dateien CRLF, kein BOM - BUILD FERTIG gruen); check_2308_ssd_imports.py (Import-Smoke mit .venv-Python: Hauptdatei + 4 Re-Export-Konstanten (Werte identisch: BODY_SPACING=8, DIALOG_GEOMETRY_KEY="service_selector", PANEL_BUFFER=24, TREE_DEFAULT_WIDTH=300) + Host-Re-Export, constants/host direkt, MRO = ServiceSelectorDialog -> QDialog -> ... -> 6 Mixins, 6 Mixin-Dateien einzeln importierbar, AST Kern __init__ + 4 Signale, externer Nutzer analytics_win importiert, Stichproben-Methoden aus allen 6 Mixins vorhanden, Kern ohne property/staticmethod - SMOKE TEST PASS).
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B8: service_selector_dialog 2.414 -> 414 Zeilen + 8 neue Dateien (constants 22, host 217, selection 198, presets 468, sets 336, run 529, badge 222, panel 388) mit 1-Zeilen-Verantwortlichkeit; Teil C neue Routing-Zeile 25 (Datenquellen-Picker: service_selector_dialog.py -> 6 Mixins -> host -> analytics_win); Teil D2: Kandidat als GESPLITTET markiert; Stand-Header auf 23.08 (159 Py-Dateien / 50.190 Zeilen, 6 JS / 1.837). Zusaetzlich verpasste Map-Updates der frueheren Splits nachgezogen (Teil E Punkt 1): Teil B4 chart_win 1.630 -> 399 + 6 Mixins (23.03), Teil B6 analytics_view_model 1.886 -> 225 + 7 Dateien (23.07), Teil B8 service_win 3.264 -> 946 + 5 Mixins (23.04) und master_tree 2.511 -> 318 + 7 Dateien (23.06), Teil C Zeilen 1-5 auf chart_win-Mixins zeigen, Teil D2 service_win + chart_win als GESPLITTET markiert, verbleibende Kandidaten neu ausgezaehlt (heatmap_widget 2.656, indicator_dialog 1.867).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.09 - God-File-Split #9: heatmap_widget.py-Mixins, phase23_step11):** Neunter God-File-Split der Entkopplungs-Roadmap (Benutzer-Prioritaet nach service_selector_dialog). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** analytics/ui/heatmap_widget.py (129.128 Bytes/2.656 Zeilen, LF-only (0 CRLF), kein BOM) - 2 Klassen: _HeatmapAxis (Z298-569, 9 Methoden) + HeatmapWidget (Z572-2656, 54 Methoden inkl. __init__ Z580-848, Basis QWidget). 15 Modul-Konstanten (Z122-202: _CONFLUENCE_COLORS, _CONFLUENCE_POS, _CONFLUENCE_LEVELS, _VIRIDIS, _VALUE_AGGS, _PRICE_LIKE_KEY_HINTS, _DAY_SECONDS, _HALF_DAY, _MONTH_SECONDS, _YEAR_SECONDS, _TF_SECONDS, _DATE_TARGET_PX, _MONTHS_SHORT, _DIM_LABELS, _AGG_LABELS) -> constants-Datei (genutzt von __init__ UND Mixin-Methoden). 6 Modul-Funktionen NACH den Konstanten (Z152-295): _is_price_like_key (nutzt _PRICE_LIKE_KEY_HINTS) -> controls, _pick_time_step/_time_ticks/_nice_int_step -> axis, _format_heatmap_value/_format_legend_value -> info. _HeatmapAxis nur in __init__ (Z731/732) genutzt -> eigene axis-Datei (kein Zirkularimport, Hauptdatei re-exportiert, Muster heatmap_widget_constants/service_selector_dialog_host). 1 Signal-Klassenvariable: preset_clicked (Z578) -> bleibt im Kern. 5 Staticmethods: _set_combo_data, _set_zoom_slider, _field_key, _zoom_lo_hi, _axis_bounds. Keine lokalen Imports in Methoden. Einziger direkter externer Nutzer: analytics/ui/heatmap_page.py (analytics_win nur indirekt via heatmap_page). Backup: test/backup_heatmap_widget_pre_mixins_20260815.py.
- **Neue Datei analytics/ui/heatmap_widget_constants.py (86 Zeilen/3.601 Bytes):** 15 Konstanten (Z122-202 1:1). Hauptdatei re-exportiert alle 15 Namen via from analytics.ui.heatmap_widget_constants import (...).
- **Neue Datei analytics/ui/heatmap_widget_axis.py (333 Zeilen/15.154 Bytes):** _HeatmapAxis (9 Methoden, Z298-569 1:1) + 3 Tick-Helper (Z205-245: _pick_time_step, _time_ticks, _nice_int_step).
- **6 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** analytics/ui/heatmap_widget_controls.py (HeatmapWidgetControlsMixin, 11 Methoden - Config-Sync, Combos, Slider, Modus-Sync; + _is_price_like_key; 344 Zeilen/15.765 Bytes), _fields.py (HeatmapWidgetFieldMixin, 10 - Feld-Auswahl/Dropdown, Checked-Pairs, VM-Sync; 432/20.959), _zoom.py (HeatmapWidgetZoomMixin, 10 - Zoom-Slider X/Y, Range-Apply, Achsen-Bounds; 167/6.574), _data.py (HeatmapWidgetDataMixin, 10 - Daten-Anfrage/-Empfang, Render-Generic, No-Data; 512/25.054), _overlay.py (HeatmapWidgetOverlayMixin, 6 - Candle-Overlay, Preis-View, Grid-Linien; 273/12.161), _info.py (HeatmapWidgetInfoMixin, 6 - Info-Zeile, Maus-Tracking, Zell-Info, Legende; + 2 Format-Helper Z248-295; 305/13.970). Deterministisch per test/build_2309_hmw.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching; Support-Importe automatisch ergaenzt). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__ + Signal preset_clicked: Klassendeklaration HeatmapWidget(QWidget, HeatmapWidgetControlsMixin, HeatmapWidgetFieldMixin, HeatmapWidgetZoomMixin, HeatmapWidgetDataMixin, HeatmapWidgetOverlayMixin, HeatmapWidgetInfoMixin).
- **Hauptdatei analytics/ui/heatmap_widget.py (129.015 -> 21.321 Bytes, -107.694, 424 Zeilen, LF-only erhalten):** 53 Methoden entfernt, Konstanten-Block Z122-202 durch Re-Export-Import ersetzt (keine Doppel-Definition), Axis-Block Z298-569 entfernt, 6 Modul-Funktionen entfernt (in die jeweiligen Mixin-/axis-Dateien). Verbleibend: Docstring, Importe (unveraendert), Re-Exports (15 Konstanten + _HeatmapAxis), Klasse mit __init__ + Signal-Deklaration preset_clicked (Klassenvariable bleibt im Kern).
- **Validierung (headless, test/):** build_2309_hmw.py (py_compile 9 Dateien OK; AST-Check Kern==["__init__"] + je Mixin exakt die vorgesehenen Methoden (11/10/10/10/6/6 = 53); alle 53 Methoden byte-identisch normalisiert; Konstanten-Block Z122-202 byte-identisch; Axis-Block Z298-569 byte-identisch; Line-Endings: alle 9 Dateien LF-only, kein BOM - BUILD FERTIG gruen); check_2309_hmw_imports.py (Import-Smoke mit .venv-Python: Hauptdatei + 15 Re-Export-Konstanten (Werte identisch) + _HeatmapAxis, constants/axis direkt, MRO = HeatmapWidget -> QWidget -> ... -> 6 Mixins, 6 Mixin-Dateien einzeln importierbar, AST Kern __init__ + preset_clicked, externe Nutzer heatmap_page + analytics_win importiert, Stichproben-Methoden aus allen 6 Mixins vorhanden, 5 Staticmethods via MRO + Dekorator-AST, Kern ohne property/staticmethod - SMOKE TEST PASS).
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B7: heatmap_widget 2.656 -> 424 Zeilen + 8 neue Dateien (constants 86, axis 333, controls 344, fields 432, zoom 167, data 512, overlay 273, info 305) mit 1-Zeilen-Verantwortlichkeit; Teil C Zeile 13 Routing auf Mixins zeigen (heatmap_widget.py (Kern) -> controls/fields/zoom/data/overlay/info + axis -> heatmap_page); Teil D2: Kandidat als GESPLITTET markiert (~~2.656~~ -> GESPLITTET (23.09, 15.08.2026) -> 6 Mixins + constants + axis); Stand-Header auf 23.09 (167 Py-Dateien / 50.410 Zeilen, 6 JS / 1.837).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).



**15.08.2026 (23.10 - God-File-Split #10: indicator_dialog.py-Mixins, phase23_step12):** Zehnter God-File-Split der Entkopplungs-Roadmap (Benutzer-Prioritaet: chart/indicator_dialog.py). Headless validiert (keine UI-/Regressionstests, Praeambel 2):
- **Analyse:** chart/indicator_dialog.py (79.038 Bytes/1.867 Zeilen, LF-only (0 CRLF), kein BOM) - 1 Klasse IndicatorSettingsDialog (Z63-1867, 52 Methoden inkl. __init__ Z69-168, Basis ContentScrollMixin, NamedItemActionsMixin, QDialog). KEINE Modul-Konstanten und KEINE Modul-Funktionen auf Modulebene. 1 Klassen-Konstante DIALOG_GEOMETRY_KEY (Z67) -> bleibt im Kern (self-Zugriff via MRO aus _restore_geometry/_save_geometry in der geometry-Datei, kein Zirkularimport). 4 Staticmethods (_decimal_places, _is_visual_key, _style_sibling_keys, _human), 2 Properties (set_repo, set_evaluator) wandern mit ihren Methoden in die Mixins. Lokale Imports in 7 Methoden (PluginRegistry in _get_plugin/_service_cfg/_show_service_info/_rebuild_service_stack/collect_set_definition, ServiceSetRepository in set_repo, ServiceSetEvaluator in set_evaluator, get_symbol_precision in _get_symbol_precision, map_custom_levels_to_prox_levels in _rebuild_service_stack, import re in _generate_default_service_set_name) bleiben in den Methoden. Keine Signal-Klassenvariablen. Einzige externe Nutzer: chart/chart_win.py + chart/chart_win_indicators.py (nur Klassen-Import). Backup: test/backup_indicator_dialog_pre_mixins_20260815.py.
- **7 neue Mixin-Dateien (1:1 extrahiert, keine Logik-Aenderung):** chart/indicator_dialog_plugin.py (IndicatorSettingsDialogPluginMixin, 3 Methoden - _get_plugin, set_repo, set_evaluator; 54 Zeilen/1.985 Bytes), _schema.py (IndicatorSettingsDialogSchemaMixin, 7 - _decimal_places, _get_symbol_precision, _is_visual_key, _style_sibling_keys, _human, create_schema_control, _ctrl_value; 249/9.782), _ui.py (IndicatorSettingsDialogUiMixin, 7 - init_ui, _init_legacy_ui, _init_plugin_ui, _init_plugin_ui_params_only, _setup_collapsible, _reflow, create_control_widget; 531/21.556), _sets.py (IndicatorSettingsDialogSetsMixin, 10 - _indicator_service_ids, _service_items, _service_cfg, refresh_service_set_list, _indicator_sets, _on_service_set_changed, _on_service_selected, _build_tooltip, _show_service_info, _rebuild_service_stack; 380/15.273), _run.py (IndicatorSettingsDialogRunMixin, 13 - _resolve_set_logic_params, _collect_logic_params, _build_preset_payload, collect_set_definition, _generate_default_service_set_name, create_new_service_set, save_service_set, delete_service_set, _connect_service_param_commit, _on_service_param_commit, execute_service_set, _on_set_run_finished, _on_set_run_failed; 364/15.243), _presets.py (IndicatorSettingsDialogPresetsMixin, 8 - _build_preset_group, refresh_preset_list, collect_params_from_ui, update_ui_from_params, on_param_control_changed, on_preset_selected, save_current_preset, delete_current_preset; 262/9.736), _geometry.py (IndicatorSettingsDialogGeometryMixin, 3 - _restore_geometry, _save_geometry, done; 66/2.360). Deterministisch per test/build_2310_idd.py (AST-Linienbereiche inkl. fuehrender Kommentar-/Dekorator-Zeilen; automatische Import-Generierung per Name-Matching). Reihenfolge in jeder Mixin == Original-Quellreihenfolge. Kern behaelt nur __init__ + DIALOG_GEOMETRY_KEY: Klassendeklaration IndicatorSettingsDialog(ContentScrollMixin, NamedItemActionsMixin, QDialog, IndicatorSettingsDialogPluginMixin, IndicatorSettingsDialogSchemaMixin, IndicatorSettingsDialogUiMixin, IndicatorSettingsDialogSetsMixin, IndicatorSettingsDialogRunMixin, IndicatorSettingsDialogPresetsMixin, IndicatorSettingsDialogGeometryMixin).
- **Hauptdatei chart/indicator_dialog.py (78.744 -> 8.182 Bytes, -70.562, 181 Zeilen, LF-only erhalten):** 51 Methoden entfernt. Verbleibend: Docstring, Importe (unveraendert), 7 Mixin-Importe, Klasse mit __init__ + Klassen-Konstante DIALOG_GEOMETRY_KEY (Klassenvariable bleibt im Kern).
- **Validierung (headless, test/):** build_2310_idd.py (py_compile 8 Dateien OK; AST-Check Kern==["__init__"] + DIALOG_GEOMETRY_KEY-Assign; je Mixin exakt die vorgesehenen Methoden (3/7/7/10/13/8/3 = 51); alle 51 Methoden byte-identisch normalisiert; Basis-Reihenfolge 10 Basen (ContentScrollMixin, NamedItemActionsMixin, QDialog, 7 Mixins); Line-Endings: alle 8 Dateien LF-only, kein BOM - BUILD FERTIG gruen); check_2310_idd_imports.py (Import-Smoke mit .venv-Python: Hauptdatei + MRO (ContentScrollMixin vor QDialog, QDialog vor Mixins), 7 Mixin-Dateien einzeln importierbar, AST Kern __init__ + DIALOG_GEOMETRY_KEY, externer Nutzer chart_win_indicators importiert, Stichproben-Methoden aus allen 7 Mixins vorhanden, 4 Staticmethods + 2 Properties via getattr_static, Kern ohne property/staticmethod, alle 51 Methoden byte-identisch zu Backup - SMOKE TEST PASS).
- **Architektur-Map (HARTE REGEL Teil E, im selben Schritt):** Teil B4: indicator_dialog 1.893 -> 181 Zeilen + 7 neue Dateien (plugin 54, schema 249, ui 531, sets 380, run 364, presets 262, geometry 66) mit 1-Zeilen-Verantwortlichkeit; Teil C Zeile 10 Routing auf Mixins zeigen (indicator_dialog.py (Kern) -> plugin/schema/ui/sets/run/presets/geometry -> serviceui/param_columns.py); Teil D2: Kandidat als GESPLITTET markiert (~~1.867~~ -> GESPLITTET (23.10, 15.08.2026) -> 7 Mixins (Teil B4)); Stand-Header auf 23.10 (174 Py-Dateien / 50.623 Zeilen, 6 JS / 1.837).
- **Doku (dieser Eintrag):** Implementierungs-Log nach Freigabe durch den Anwender eingetragen (Regel 4.5C).
