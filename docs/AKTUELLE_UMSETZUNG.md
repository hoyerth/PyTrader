# Phase 21: Fachliche Feinabstimmung Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 21)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase21_step1`, `phase21_step1` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
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
10. **Isolierter Test-Workspace & Cleanup:** Neue Test-Skripte und temporäre `*.duckdb`-Dateien gehören strikt nach `test/`. Nach Abschluss jedes Phasenkapitels wird `test/` aufgeräumt – es verbleibt nur der Test-Harness `test/test.py`.
11. **Open/Closed-Principle & Code-Preserving:** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden; bestehende Kern-Klassen bleiben geschützt.
12. **Naming Conventions & PineScript-Input-Zone:** 
    - Services in `analytics/features/definitions/` nutzen strikt das Präfix `srv_` (`plugin_id = "srv_..."`).
    - Indikatoren in `chart/indicators/` nutzen strikt das Präfix `ind_` (`indicator_id = "ind_..."`).
    - Füllwörter (`service`, `plugin`, `indicator`) entfallen im Dateinamen.
    - Das `parameter_schema` liegt direkt am Dateianfang unter dem Header-Docstring.
    - Jedes Service-Plugin deklariert `metadata["category"]` für die dynamische Kategorie-Ordner-Struktur im MasterTree.

---

# 21.03.22 – Full Market-Data Sync Button (ServiceWindow)

## 🎯 Zielstellung & Fachliche Motivation
Für umfassende Analysen im `ServiceWindow` müssen alle in `market_data.duckdb` gespeicherten **Symbol:Timeframe-Paare** auf den neuesten Stand gebracht werden. Ein manueller Button oben rechts in der `top_row` stößt den vollständigen Sync aller lokal vorhandenen Paare an. Während dieses Vorgangs pausiert der automatische 45-Sekunden-Sync.

---

## ✅ Entscheidungen & Antworten auf IDE-Rückfragen (13.08.2026)

1. **Einbindung in `serviceui/service_win.py`:** Es existieren KEINE Methoden `_build_ui()` / `_wire_events()` – Layout-Aufbau (Zeilen 184–395) und Signal-Verdrahtung (ab Zeile 410) passieren direkt im `__init__`. Button-Erzeugung daher direkt im `__init__` im `top_row`-Block NACH `self.top_row.addWidget(self.main_splitter)` (Zeile 365), rechtsbündig via `self.top_row.addStretch(1)` + `addWidget`. Signal-Verdrahtung `clicked.connect(...)` im bestehenden Connect-Block ab Zeile 410.
2. **`sync_market_data(target_pairs=None)`:** Signatur `sync_market_data(target_pairs: Optional[Set[Tuple[str, str]]] = None)`. Bei übergebenem `target_pairs` (nicht `None`) wird **exakt über diese `(symbol, timeframe)`-Paare** iteriert; bei `None`/leer greift der **Fallback auf das bisherige Standard-Raster** (`SYMBOLS` × `get_timeframes()`). Der Delta-Sync-Abgleich mit `get_latest_timestamp(symbol, tf)` bleibt pro Paar voll erhalten (inkrementelles Laden).
3. **Signal & Typing:** `sync_completed = Signal(set)` wird übernommen (voll kompatibel mit `main.py`, das ein Set empfängt). `from typing import Optional, Set, Tuple` im `DataSyncWorker` ergänzen.
4. **DB-Zugriffsmuster im Repository:** Generell `DbPool.get(self.db_path)` nutzen (Thread-local, kein manuelles `close()`, konsistent mit `get_symbol_precision` und projektweiten Standards).
5. **Headless-Testbarkeit (Akzeptanzkriterium 2):** `sync_market_data` bzw. der `DataSyncWorker` wird im Test gemockt (Monkeypatching) – **kein echter MT5-Netzwerk-Sync**. Der Test verifiziert rein synchron die Signal-Emission (`service_run_started` vor Start, `service_run_finished` nach `sync_completed`) sowie die Button-Deaktivierung/Aktivierung.
6. **Formatierung:** Rechtsbündige Platzierung in `top_row` bestätigt; entbehrliche Casts (`str(r[0])`) entfallen zugunsten des Filters `if r[0] and r[1]`.

---

## 🛠️ Schritt-für-Schritt Umsetzungsanleitung für die IDE

### Schritt 1: Paar-Abfrage im Repository (`repositories/market_data_repository.py`)

Ergänze `repositories/market_data_repository.py` um die Abfrage aller gespeicherten Paare (Muster: `DbPool.get`, kein manuelles `close()`, Filter auf nicht-leere Werte statt Casts):

# repositories/market_data_repository.py

def get_all_stored_symbol_tf_pairs(self) -> Set[Tuple[str, str]]:
    """Liefert alle (symbol, timeframe)-Paare, für die bereits Daten in ohlcv_bars existieren."""
    from db_service import DbPool
    con = DbPool.get(self.db_path)
    try:
        rows = con.execute("""
            SELECT DISTINCT UPPER(symbol), UPPER(timeframe)
            FROM ohlcv_bars
            WHERE symbol IS NOT NULL AND timeframe IS NOT NULL
        """).fetchall()
        return {(r[0], r[1]) for r in rows if r[0] and r[1]}
    except Exception as e:
        print(f"WARN [MarketDataRepository] Pair-Abfrage fehlgeschlagen: {e}")
        return set()

---

### Schritt 2: `DataSyncWorker` erweitern (`workers/data_sync_worker.py`)

Erweitere den Konstruktor von `DataSyncWorker`, um ein optionales `pairs`-Set zu akzeptieren (Typing `Optional` ergänzen, Signal `Signal(set)`):

# workers/data_sync_worker.py

from typing import Optional, Set, Tuple
# ...
class DataSyncWorker(QThread):
    sync_completed = Signal(set)

    def __init__(self, pairs: Optional[Set[Tuple[str, str]]] = None, parent=None):
        super().__init__(parent)
        self.pairs = pairs

    def run(self):
        # Wenn pairs übergeben wurden, werden nur diese synchronisiert
        updated = sync_market_data(target_pairs=self.pairs)
        self.sync_completed.emit(updated)

---

### Schritt 2b: `sync_market_data(target_pairs=None)` erweitern (`data_sync/mt5_sync_service.py`)

- **Signatur:** `sync_market_data(target_pairs: Optional[Set[Tuple[str, str]]] = None)`
- **Logik:**
  - Ist `target_pairs` übergeben (nicht `None`), wird **exakt über diese `(symbol, timeframe)`-Paare** iteriert (statt über das Standard-Raster).
  - Ist `target_pairs` `None` (oder leer), greift der **Fallback auf das bisherige Standard-Raster** (`SYMBOLS` × `get_timeframes()`).
  - Der Delta-Sync-Abgleich mit `get_latest_timestamp(symbol, tf)` bleibt pro Paar voll erhalten (inkrementelles Laden).

---

### Schritt 3: Button & Einbindung in `serviceui/service_win.py`

In `serviceui/service_win.py` direkt im `__init__` (kein `_build_ui()`/`_wire_events()` – Aufbau und Verdrahtung passieren dort):

# serviceui/service_win.py (in __init__, top_row-Block NACH self.top_row.addWidget(self.main_splitter), Zeile ~365)

self.btn_sync_all_market = QPushButton("🔄 Sync Alle Daten")
self.btn_sync_all_market.setToolTip(
    "Aktualisiert ALLE in market_data.duckdb gespeicherten Symbol:Timeframe-Paare aus MT5."
)
self.top_row.addStretch(1)
self.top_row.addWidget(self.btn_sync_all_market)

# serviceui/service_win.py (in __init__, bestehender Connect-Block ab Zeile ~410)

self.btn_sync_all_market.clicked.connect(self._on_sync_all_market_clicked)


# Neue Handler-Methoden:
@Slot()
def _on_sync_all_market_clicked(self) -> None:
    """Startet den Full-Sync aller in market_data.duckdb vorhandenen Symbol:TF-Paare."""
    if hasattr(self, "_sync_worker") and self._sync_worker is not None and self._sync_worker.isRunning():
        return

    from repositories.market_data_repository import MarketDataRepository
    all_pairs = MarketDataRepository().get_all_stored_symbol_tf_pairs()

    if not all_pairs:
        return

    # 45s-Auto-Sync pausieren via Concurrency-Guard
    from config.event_bus import event_bus
    event_bus.service_run_started.emit()

    self.btn_sync_all_market.setEnabled(False)
    self.btn_sync_all_market.setText("⏳ Sync läuft...")

    from workers.data_sync_worker import DataSyncWorker
    self._sync_worker = DataSyncWorker(pairs=all_pairs, parent=self)
    self._sync_worker.sync_completed.connect(self._on_sync_all_completed)
    self._sync_worker.finished.connect(self._sync_worker.deleteLater)
    self._sync_worker.start()

@Slot(set)
def _on_sync_all_completed(self, updated_pairs) -> None:
    """Nach Abschluss des Full-Syncs: Auto-Sync fortsetzen & UI refreshen."""
    from config.event_bus import event_bus
    event_bus.service_run_finished.emit()

    self.btn_sync_all_market.setEnabled(True)
    self.btn_sync_all_market.setText("🔄 Sync Alle Daten")

    self._refresh_badge_bar()
    if hasattr(self, "service_selector"):
        self.service_selector.refresh()


---

## 📊 Akzeptanzkriterien für die Validierung (`test/test.py`)

1. **Pair-Query-Test:** `MarketDataRepository().get_all_stored_symbol_tf_pairs()` liefert alle in `ohlcv_bars` vertretenen Paare als Set von Tuples zurück.
2. **Signal-Emission-Test (headless via Mock):** `sync_market_data` bzw. der `DataSyncWorker` wird gemockt (Monkeypatching) – **kein echter MT5-Netzwerk-Sync**. Der Test verifiziert rein synchron, dass `event_bus.service_run_started` VOR dem Start des Workers und `event_bus.service_run_finished` NACH `sync_completed` emittiert wird.
3. **UI-State-Test (headless via Mock):** `btn_sync_all_market` schaltet während der Ausführung auf `enabled=False` und nach `sync_completed` wieder auf `enabled=True`.

---

## 📝 Implementierungs-Log

**13.08.2026 (Entscheidungen zu IDE-Rückfragen):** Kapitel 21.03.22 um den Abschnitt „Entscheidungen & Antworten auf IDE-Rückfragen" erweitert und die Schritte 1–3 sowie die Akzeptanzkriterien entsprechend präzisiert: (1) Einbindung direkt im `__init__` statt `_build_ui()`/`_wire_events()`; (2) `sync_market_data(target_pairs=None)` mit exakter Paar-Iteration und Fallback auf `SYMBOLS` × `get_timeframes()`; (3) `Signal(set)` + `Optional`-Import im `DataSyncWorker`; (4) DB-Muster `DbPool.get` ohne manuelles `close()`; (5) Headless-Test via Monkeypatch (kein echter MT5-Sync); (6) Casts entfallen, Filter `if r[0] and r[1]`. **Noch kein Coding – Umsetzung wartet auf manuellen Befehl.**

**13.08.2026 (Umsetzung & Validierung, phase21_step4):** Kapitel 21.03.22 vollständig umgesetzt:
- `repositories/market_data_repository.py`: `get_all_stored_symbol_tf_pairs()` ergänzt (`DbPool.get`-Muster, UPPER-normalisiert, NULL-Filter).
- `workers/data_sync_worker.py`: `DataSyncWorker(pairs=None)` + `sync_completed = Signal(set)`; reicht `target_pairs` an `sync_market_data()` durch.
- `data_sync/mt5_sync_service.py`: `sync_market_data(target_pairs=None)` – exakte Paar-Iteration (UPPER-normalisiert, unbekannte TFs gefiltert) mit Fallback auf `SYMBOLS` × `get_timeframes()`; Delta-Sync via `get_latest_timestamp` bleibt pro Paar erhalten.
- `serviceui/service_win.py`: `btn_sync_all_market` rechtsbündig in `top_row` (nach Splitter, Zeile ~365), `clicked`-Verdrahtung im Connect-Block (Zeile ~427), Handler `_on_sync_all_market_clicked`/`_on_sync_all_completed` (vor `_refresh_badge_bar`). Concurrency-Guard via `event_bus.service_run_started/finished`; UI-Refresh via `_refresh_badge_bar()` + `service_selector.refresh()`. Zwei Robustheits-Fixes während der Validierung: Guard nutzt `_qt_valid` (shiboken) gegen „Internal C++ object already deleted" nach `deleteLater`, und `_sync_worker` wird nach Abschluss auf `None` gesetzt.
- **Validierung (headless, `test/check_21322_full_sync.py` + Block in `test/test.py`, kein echter MT5-Sync):** T1 Pair-Query (UPPER + NULL-Filter), T2/T2b Worker-Param-Durchreichung (pairs/None), T2c/T2c2 `target_pairs`-Filter (D1 raus) + Fallback-Raster (6 Paare), T3a–T3e Signal-Emission (`service_run_started` vor Start, `service_run_finished` nach `sync_completed`) + Button-State (enabled/disabled/enabled). **Alle Checks PASS.** `py_compile` OK für alle 4 Dateien. Git-Tag: `phase21_step4`.
