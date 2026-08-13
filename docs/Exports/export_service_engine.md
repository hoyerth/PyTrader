# PROJEKT-ÜBERSICHT: PyTrader — Service-UI & Service-Engine

> Teil-Export (sachbezogen). Vollständiger Export: export_Full.md
> Dateien in dieser Datei: 17

## 1. ORDNERSTRUKTUR
```
PyTrader/
    analytics/
        background_workers/
            historical_scanner.py
        engine/
            service_models.py
            service_selector_model.py
            service_set_repository.py
    serviceui/
        __init__.py
        common_widgets.py
        master_tree.py
        new_set_dialog.py
        param_columns.py
        run_worker.py
        service_selector_dialog.py
        service_selector_widget.py
        service_set_utils.py
        service_win.py
        status_panel.py
        symbols_win.py
        trash_dialog.py
```

## 2. QUELLCODE

### DATEI: analytics/background_workers/historical_scanner.py
```py
# analytics/background_workers/historical_scanner.py
"""
Historical Scanner – QThread-Worker für Batch-Scans über historische Daten.

Phase 15 (Alt-Signal-Rückbau): Der Alt-Scan (grid_scan / Standard-Scan über
SetEvaluator mit ema_atr_set_v1 / grid_proximity_v1) wurde komplett entfernt –
es gibt keine Signal-Engine und keine signal_results-Writes mehr. Der Scanner
führt ausschließlich den PLUGIN-BATCH aus: aktive Batch-Presets aus
`indicator_presets` werden über den PluginExecutor ausgeführt und schreiben
ihre Ergebnisse in den feature_store (feature_data, feature_id = Plugin).
"""

import time
from typing import Any, Dict, List, Optional
from PySide6.QtCore import QThread, Signal

from analytics.engine.service_models import generate_instance_hash
from analytics.features.feature_builder import FeatureBuilder, PluginExecutor, prepare_plugin_df
from db_service import get_timeframes
from state_manager import StateManager


class HistoricalScanner(QThread):
    """Scannt historische Daten für ein Symbol über alle Timeframes (Plugin-Batch)."""

    progress_updated = Signal(str, int, int)  # message, current, total
    scan_finished = Signal(str, int)          # symbol, total_feature_rows
    log_message = Signal(str)                 # log text

    def __init__(
        self,
        symbol: str,
        new_scan: bool = False,
        parent=None,
        db_path_app: Optional[str] = None,
        db_path_analytics: Optional[str] = None,
        db_path_market: Optional[str] = None,
        timeframes: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self.symbol = symbol
        self.new_scan = new_scan
        self._running = True
        # Override-Pfade (Test/Isolation) – None = Produktions-DBs
        self._db_path_app = db_path_app
        self._db_path_analytics = db_path_analytics
        self._db_path_market = db_path_market
        self._timeframes = timeframes

        self._state_mgr = StateManager(db_path=db_path_app) if db_path_app else StateManager()
        self._settings = self._state_mgr.get_app_settings()

        self.feature_builder = FeatureBuilder()
        # PluginExecutor fuer den Plugin-Batch (aktive Batch-Presets).
        self.plugin_executor = PluginExecutor()

    def stop(self):
        self._running = False

    def _get_active_batch_plugins(self) -> List[Dict[str, Any]]:
        """Liefert die aktiven Batch-Presets (is_active_batch = True) aus den
        indicator_presets. Steuert den Plugin-Batch."""
        try:
            return self._state_mgr.list_active_batch_presets()
        except Exception as e:
            self.log_message.emit(f"Plugin-Presets konnten nicht geladen werden: {e}")
            return []

    def _run_plugin_batch(
        self,
        df_ohlcv,
        tf: str,
        active_plugins: List[Dict[str, Any]],
    ) -> int:
        """Fuehrt alle aktiven Batch-Presets ueber den PluginExecutor aus und
        schreibt den feature_store_payload in den feature_store (Hybrid-Spalten
        feature_id/plugin_version/feature_data).

        Returns:
            Anzahl der geschriebenen Feature-Rows (summiert ueber alle Plugins).
        """
        if df_ohlcv is None or df_ohlcv.empty:
            return 0
        # Plugin-Vertrag: DataFrame mit 'time'-Spalte (epoch-Sekunden).
        # load_ohlcv() liefert 'bar_time' (datetime) -> hier anpassen.
        df_plugin = prepare_plugin_df(df_ohlcv)
        total_rows = 0
        for preset in active_plugins:
            plugin_id = preset.get("plugin_id")
            if not plugin_id:
                continue
            try:
                result = self.plugin_executor.execute(
                    plugin_id, df_plugin, preset.get("params", {})
                )
            except Exception as e:
                import traceback
                self.log_message.emit(f"  {tf}: Plugin {plugin_id} FEHLER: {e}")
                self.log_message.emit(f"    {traceback.format_exc()}")
                continue
            payload = result.get("feature_store_payload", {}) if isinstance(result, dict) else {}
            if payload:
                try:
                    # 20.04 (Q9): instance_hash der Preset-Variante (Parameter-
                    # Hash) – Spalte im feature_store fuer Varianten-Statistik
                    # und gezieltes Purge (Q5).
                    instance_hash = generate_instance_hash(
                        plugin_id, preset.get("params") or {})
                    n = self.feature_builder.store_plugin_payload(
                        self.symbol, tf, payload, instance_hash=instance_hash)
                    total_rows += n
                    self.log_message.emit(
                        f"  {tf}: Plugin {plugin_id}: {n} Feature-Rows im feature_store"
                    )
                except Exception as e:
                    self.log_message.emit(f"  {tf}: Plugin {plugin_id} Store-Fehler: {e}")
        return total_rows

    def run(self):
        # Phase 12: aktive Batch-Presets (Plugin-Batch) einmal bestimmen
        active_plugins = self._get_active_batch_plugins()

        total_rows = 0
        timeframes = self._timeframes if self._timeframes is not None else list(get_timeframes().keys())
        num_tfs = len(timeframes)

        self.log_message.emit(f"Starte Plugin-Batch fuer {self.symbol} ueber {num_tfs} Timeframes...")
        if not active_plugins:
            self.log_message.emit(
                "Keine aktiven Batch-Presets (is_active_batch) gefunden – "
                "nichts zu tun. Aktiviere zuerst einen Batch-Service in den "
                "Indikator-Einstellungen."
            )
            self.progress_updated.emit("Fertig", num_tfs, num_tfs)
            self.scan_finished.emit(self.symbol, 0)
            return
        if self.new_scan:
            self.log_message.emit("Modus: FULL SCAN (kompletter Neuaufbau der Feature-Rows)")
        else:
            self.log_message.emit("Modus: DELTA UPDATE (Upsert, fehlende Bars werden ergaenzt)")

        start_time = time.time()

        for idx, tf in enumerate(timeframes):
            if not self._running:
                self.log_message.emit("Scan abgebrochen.")
                return

            self.progress_updated.emit(f"Verarbeite {tf}...", idx, num_tfs)

            try:
                df_ohlcv = self.feature_builder.load_ohlcv(self.symbol, tf, limit=self._settings.scanner_candle_limit)
                if df_ohlcv.empty:
                    self.log_message.emit(f"  {tf}: Keine OHLCV-Daten, ueberspringe")
                    continue

                total_rows += self._run_plugin_batch(df_ohlcv, tf, active_plugins)

            except Exception as e:
                self.log_message.emit(f"  {tf}: FEHLER: {e}")
                import traceback
                self.log_message.emit(f"    {traceback.format_exc()}")

        elapsed = time.time() - start_time
        elapsed_str = f"{int(elapsed // 3600):02d}:{int((elapsed % 3600) // 60):02d}:{int(elapsed % 60):02d}"
        self.log_message.emit(f"Scan abgeschlossen in {elapsed_str}")
        self.log_message.emit(f"Gesamt: {total_rows} Feature-Rows geschrieben")
        self.progress_updated.emit("Fertig", num_tfs, num_tfs)
        self.scan_finished.emit(self.symbol, total_rows)

```

--------------------------------------------------

### DATEI: analytics/engine/service_models.py
```py
# analytics/engine/service_models.py
"""
Phase 13 Schritt 2 – Service-Set-Datenmodell (TypedDicts).

Diese Strukturen sind JSON-konform und werden direkt (als JSON) vom
ServiceSetRepository in app_data.duckdb persistiert. Bewusst KEINE
Dataclasses – der ServiceSetEvaluator (Schritt 3) und die UI (Schritte 4/5)
arbeiten auf denselben Dict-Strukturen wie die JSON-Speicherung.

Multi-Use-Prinzip: Ein Plugin (z.B. srv_grid_lines) kann MEHRFACH in einem Set
vorkommen. Jede Nutzung erhält eine eindeutige instance_id (z.B. grid_1,
grid_2). execution_order bestimmt die Ausführungs-Reihenfolge, depends_on
deklariert explizit, welche instance_ids der Service aus dem shared_state
liest (Service→Service-Abhängigkeit).
"""

from typing import Any, Dict, List, Optional, TypedDict

import hashlib
import json


# ------------------------------------------------------------------
# 20.04 (Q4): Kanonische Hash-Serialisierung
# ------------------------------------------------------------------
def _sanitize_for_hash(value: Any) -> Any:
    """Rekursive Umwandlung in JSON-feste native Python-Typen (20.04, Q4).

    numpy-Skalare (np.int64/np.float64), None, verschachtelte Dicts/Listen
    und datetime-Werte werden deterministisch in native Typen überführt –
    Grundlage der stabilen `instance_hash`-Berechnung (sonst
    `TypeError: Object of type int64 is not JSON serializable` bzw.
    instabile Hashes bei wechselnder Speicherreihenfolge).
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    # numpy-Skalare (np.int64, np.float64, np.bool_) -> native Python-Typen.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _sanitize_for_hash(item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): _sanitize_for_hash(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_hash(v) for v in value]
    # datetime/date -> ISO-String (deterministisch).
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def generate_instance_hash(
    plugin_id: str,
    params: Optional[Dict[str, Any]] = None,
    preset_name: Optional[str] = None,
) -> str:
    """8-stelliger deterministischer SHA256-Short-Hash einer Instanz (20.04).

    `SHA256("<plugin_id>|" + json.dumps(sanitized_params, sort_keys=True))[:8]`

    * **Q3:** `lookback` fließt BEWUSST NICHT ein – das Kerzen-Ergebnis hängt
      nur von Algorithmus-Logik + `params` ab; `lookback` ist ein Laufzeit-
      Fenster (Performance) und kein Inhalts-Identitätsmerkmal.
    * **Q4:** `_sanitize_for_hash` überführt numpy-Werte/None/verschachtelte
      Dicts vorher in native Python-Typen; `sort_keys=True` macht die
      Serialisierung kanonisch (unabhängig von der Speicherreihenfolge).

    **11.08.2026 (Bugfix Varianten-Kollision):** Optionaler `preset_name`
    (Varianten-/Clone-Pfad). Wird er mitgegeben, fließt er als `__preset`-
    Schlüssel in die kanonische Serialisierung ein – Presets mit IDENTISCHEN
    Parametern aber unterschiedlichen Namen erhalten dadurch unterschiedliche
    Hashes (vorher kollidierten z.B. `params={}`-Presets, womit Kontextmenü-
    Runs und Ausführungsdaten im MasterTree alle Varianten gemeinsam trafen).
    Ohne `preset_name` (Set-Instanzen) bleibt der Hash exakt wie bisher
    (Backward-Compat zu Alt-Bestand).
    """
    input_params: Dict[str, Any] = dict(params or {})
    if preset_name is not None:
        input_params["__preset"] = str(preset_name)
    canonical = json.dumps(
        _sanitize_for_hash(input_params),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        f"{plugin_id}|{canonical}".encode("utf-8")
    ).hexdigest()
    return digest[:8]


class ServiceInstanceConfig(TypedDict, total=False):
    """Konfiguration einer einzelnen Service-Instanz innerhalb eines Sets.

    Attribute:
        plugin_id:  Dauerhaft stabile Plugin-ID (z.B. 'srv_grid_lines', 'srv_proximity').
        lookback:   Scan-Fenster über die Historie (Anzahl Bars, df.tail(lookback)).
        params:     Plugin-Parameter (werden gegen das parameter_schema validiert).
        depends_on: Optional. instance_ids, deren shared_state-Einträge dieser
                    Service liest (muss früher in execution_order stehen).
        description: Optional (Phase 14 P14-01). Individuelle Anmerkung für
                    diese Instanz (wird im Tooltip/Info-Dialog angezeigt).
        version:    Optional (Phase 14 P14-01). Plugin-Version dieser Instanz,
                    Default "1.0.0" (Semantic Versioning major.minor.patch).
        instance_hash: Optional (20.04). 8-stelliger Hash der Parameter-
                    Variante (generate_instance_hash); stabile Identifikation
                    im feature_store (Spalte instance_hash) für
                    Multi-Varianten-Statistiken.
        doc_log:    Optional (20.04). Freitextfeld (Negativ-Wissen) – z. B.
                    "85% false signals in chop markets".
        is_archived: Optional (20.04, Q6). True = Instanz ist archiviert
                    (MasterTree: non-checkable, unter 📁 Archiv).
    """
    plugin_id: str
    lookback: int
    params: Dict[str, Any]
    depends_on: Optional[List[str]]
    description: Optional[str]
    version: Optional[str]
    instance_hash: Optional[str]
    doc_log: Optional[str]
    is_archived: bool


class ServiceSetDefinition(TypedDict, total=False):
    """Vollständige Definition eines Service-Sets (JSON-konform).

    Beispiel (Roadmap Phase 13 §2):
    {
      "set_id": "uuid-oder-name",
      "display_name": "Mein Scalper",
      "execution_order": ["grid_1", "prox_1", "ema_1"],
      "services": {
        "grid_1": {"plugin_id": "srv_grid_lines", "lookback": 1000,
                   "params": {"step_size": 0.5, "steps_around": 4, "custom_levels": []}},
        "prox_1": {"plugin_id": "srv_proximity", "lookback": 10000,
                   "depends_on": ["grid_1"],
                   "params": {"visit_pct": 0.05, "time_window_mins": 5}}
      }
    }
    """
    set_id: str                      # Eindeutige ID (uuid oder Name)
    display_name: str                # Anzeigename (leer → Auto-Name aus instance_ids)
    description: Optional[str]       # Phase 14 P14-01: Ausführliche Set-/Strategie-Beschreibung
    category: Optional[str]          # Phase 18.01.03 (E2): Kategorie-Pfad für den
                                     # MasterTree-Sets-Ordner (z.B. 'Swing Points/Geometrie',
                                     # Slash-separiert OHNE '📁 '-Präfixe; leer/"General" =
                                     # Root-Ebene der Sets-Gruppe). Persistiert additiv
                                     # in save_set().
    version: Optional[str]           # Kap 5: Set-Level Semantic Version (major.minor.patch)
    schema_version: Optional[str]    # Kap 5: Schema-Format-Version der Definition (z.B. "1.0")
    created_at: Optional[str]        # Kap 5: Erstellungs-Zeitstempel (ISO-8601 UTC)
    is_archived: bool                # 20.04 (Q6): True = gesamtes Set archiviert
                                     # (MasterTree: non-checkable, unter 📁 Archiv)
    execution_order: List[str]       # Ausführungs-Reihenfolge der instance_ids
    services: Dict[str, ServiceInstanceConfig]  # instance_id → Konfiguration

```

--------------------------------------------------

### DATEI: analytics/engine/service_selector_model.py
```py
# analytics/engine/service_selector_model.py
"""
Phase 15 15.02 – ServiceSelectorModel (zentrales, lesendes Datenmodell).

Bereitet die Service-/Set-Hierarchie fuer das 2-Spalten-MasterTree und die
generische Service-Auswahl (ServiceSelectorWidget) auf. Quellen:

  * `ServiceSetRepository.list_sets()`       – gespeicherte Service-Sets
  * `PluginRegistry`                          – alle verfuegbaren Plugins
  * `StateManager.load_all_instances()`       – Live-Status "aktiv im Chart"
    (indicators_state[*]['active'] == True)
  * `FeatureStoreReader.fetch_last_execution_dates()` – Datum der letzten
    Ausfuehrung je feature_id (MAX(created_at) in analytics.duckdb/
    feature_store) fuer die MasterTree-Anzeige 'Service_Name (DD.MM.JJ)'

Der Model hoert auf `EventBus.service_set_changed` und aktualisiert sich
automatisch in allen Fenstern (Invariante 5: schwellenfreie Entkopplung).

Reines Lesemodell – es schreibt NIE in die DB. UI-Klassen zeigen ausschliesslich
diese aufbereiteten Daten an (Invariante 4: kein SQL in UI).

Verwendete Badge-Konvention (Spalte 1 des MasterTree):
  * `📌 im <Indikator>`     – Plugin mit capabilities['chart'] == True
                             (bezieht sich auf den echten Indikator-Namen,
                             z.B. 'Ind_FixedGridProximity' – KEIN Service-Name)
  * `🟢 aktiv in <Indikator>` – Indikator ist in mind. einem Chart-Fenster aktiv
  * `⚪ inaktiv in <Indikator>` – Indikator ist nirgends aktiv / kein Chart-Pflicht
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, Signal

from config.event_bus import event_bus
from analytics.engine.service_models import generate_instance_hash


def list_indicators() -> List[Dict[str, Any]]:
    """Alle verfuegbaren Indikatoren (deterministisch).

    Liefert pro Indikator: {"indicator_id", "display_name",
    "service_plugin_ids"} – Grundlage der Indikator-Auswahl beim Anlegen
    neuer Service-Sets (Bugfix 05.08.2026). Aktuell existiert genau ein
    Plugin-Indikator (Ind_FixedGridProximity); weitere Indikatoren werden
    hier Open/Closed ergaenzt (Registry-Prinzip).
    """
    result: List[Dict[str, Any]] = []
    try:
        from chart.indicators.ind_fixed_grid_proximity import FixedGridProximityIndicator
        ind = FixedGridProximityIndicator()
        svc_ids = list(getattr(ind, "service_plugin_ids", []) or [])
        # Konsistenter Anzeigename: bevorzugt metadata['indicator_name'] des
        # ersten Indikator-Services (identisch zur Tree-Badge-Logik in
        # get_indicator_display_name); Fallback ind.display_name/indicator_id.
        display = str(getattr(ind, "display_name", "")
                      or getattr(ind, "indicator_id", ""))
        try:
            if svc_ids:
                from analytics.features.feature_builder import PluginRegistry
                meta = getattr(PluginRegistry().get(svc_ids[0]),
                               "metadata", {}) or {}
                if meta.get("indicator_name"):
                    display = str(meta["indicator_name"])
        except Exception:
            pass
        result.append({
            "indicator_id": str(getattr(ind, "indicator_id", "")),
            "display_name": display,
            "service_plugin_ids": svc_ids,
        })
    except Exception:
        pass
    return result


def indicator_display_name(indicator_id: str) -> str:
    """Anzeigename eines Indikators (id -> Name); ohne Treffer die id."""
    if not indicator_id:
        return ""
    for info in list_indicators():
        if info["indicator_id"] == indicator_id:
            return info["display_name"] or indicator_id
    return indicator_id


class ServiceSelectorModel(QObject):
    """Zentrales, lesendes Datenmodell der Service-Hierarchie (Phase 15.02).

    Signals:
        data_changed: wird nach jedem Refresh emittiert (Set-/Status-Aenderung
                      oder Plugin-Reload) – Widgets abonnieren es und bauen
                      ihren Baum/die Combos neu auf.
    """

    data_changed = Signal()

    #: Gruppen-Kennungen der Hierarchie (build_tree)
    # 17.01.01: GROUP_STANDALONE entfällt ersatzlos – alle Plugins werden über
    # metadata["category"] in Ordner einsortiert (2 Root-Gruppen: sets, plugins).
    GROUP_SETS = "sets"
    GROUP_PLUGINS = "plugins"
    # 16.08 (K2): Kategorie-Ordner-Knoten (Dynamic Category Trees).
    # Ein Ordner-Dict besitzt das Format:
    #   {"group": GROUP_CATEGORY, "label": "📁 <Name>", "children": [...]}
    GROUP_CATEGORY = "category_node"

    def __init__(self, set_repo=None, state_manager=None, registry=None,
                 feature_store_reader=None,
                 parent: Optional[QObject] = None) -> None:
        """Erstellt das Modell.

        Args:
            set_repo:      ServiceSetRepository (Default: echte Instanz).
            state_manager: StateManager (Default: echte Instanz) – Quelle fuer
                           den Live-Status "aktiv im Chart".
            registry:      PluginRegistry (Default: echte Instanz) – Quelle der
                           verfuegbaren Plugins.
            feature_store_reader: FeatureStoreReader (Default: echte Instanz) –
                           rein lesende Quelle fuer das 'Datum der letzten
                           Ausfuehrung' (MAX(created_at) je feature_id in
                           analytics.duckdb/feature_store – MasterTree-Anzeige
                           'Service_Name (DD.MM.JJ)').
            parent:        Qt-Parent (optional).
        """
        super().__init__(parent)
        from analytics.engine.service_set_repository import ServiceSetRepository
        from analytics.features.feature_builder import PluginRegistry
        from analytics.engine.feature_store_reader import FeatureStoreReader
        from state_manager import StateManager

        self.set_repo = set_repo or ServiceSetRepository()
        self.state_manager = state_manager or StateManager()
        self.registry = registry or PluginRegistry()
        self.feature_store_reader = feature_store_reader or FeatureStoreReader()

        self._sets: List[Dict[str, Any]] = []
        self._active_indicator_ids: Set[str] = set()
        # 05.08.2026: Datum der letzten Ausfuehrung je feature_id (DD.MM.JJ)
        self._last_execution_dates: Dict[str, str] = {}
        # 11.08.2026 (Bugfix Runde 16c, Dropdown-Anzeige): Datum+Uhrzeit der
        # letzten Ausfuehrung je feature_id ('DD.MM.JJ HH:MM') – Grundlage der
        # Feld-Dropdown-Anzeige '{Name} / {Key} / DD.MM.JJ HH:MM' fuer
        # Services OHNE Varianten (Standalone). Quelle:
        # FeatureStoreReader.fetch_last_execution_datetimes().
        self._last_execution_datetimes: Dict[str, str] = {}
        # 10.08.2026 (Varianten-Ausfuehrungsdatum): Datum der letzten
        # Ausfuehrung je (feature_id, instance_hash) – Grundlage der
        # MasterTree-Varianten-Anzeige '<Preset> (DD.MM.JJ)'. Quelle:
        # FeatureStoreReader.fetch_last_execution_dates_by_hash().
        self._last_execution_dates_by_hash: Dict[str, Dict[str, str]] = {}
        # 11.08.2026 (Bugfix Runde 16, Dropdown-Anzeige): Datum+Uhrzeit der
        # letzten Ausfuehrung je (feature_id, instance_hash) – Grundlage der
        # Feld-Dropdown-Anzeige '{Name} / {Preset} / DD.MM.JJ HH:MM'.
        # Quelle: FeatureStoreReader.fetch_last_execution_datetimes_by_hash().
        self._last_execution_datetimes_by_hash: Dict[str, Dict[str, str]] = {}
        # 18.01.03 (E1): Kategorie-Overrides je Plugin (global_settings,
        # Key 'plugin_category_<pid>'). Ein gesetzter Override UEBERSCHREIBT
        # metadata['category'] (auch "" = Root-Ebene); ohne Override gilt das
        # metadata-Feld. Wird in refresh() einmalig geladen und von
        # _category_parts() ausgewertet (kein DB-Zugriff im Baum-Aufbau).
        self._plugin_category_overrides: Dict[str, str] = {}
        # 18.01.03 (E3-revidiert, 08.08.2026): Persistierte benutzererzeugte
        # (ggf. leere) Ordner je Gruppe (global_settings, Key
        # 'tree_folders_<group>'). Wird in refresh() geladen und in
        # build_tree() in die Gruppen-Kinder eingemischt – leere Ordner
        # verschwinden damit NICHT beim Refresh, sondern nur bei manueller
        # Loeschung (Kontextmenue 'Ordner löschen').
        self._empty_folder_paths: Dict[str, List[str]] = {}
        # 20.04 (Q7): Presets/Clones je Plugin (plugin_id.lower() -> Liste
        # von {"preset_name", "params", "instance_hash", "is_archived",
        # "doc_log"}). Quelle: indicator_presets
        # (StateManager.list_plugin_presets). Nur
        # Plugins MIT Presets erscheinen als Parent-Knoten mit Clone-Kindern
        # im MasterTree (Services-Gruppe); Plugins ohne Presets bleiben
        # flache Blaetter (Zero-Regression). Wird in refresh() geladen.
        self._plugin_presets: Dict[str, List[Dict[str, Any]]] = {}

        # Initialbefuellung + Live-Sync (schwellenfrei via EventBus)
        self.refresh()
        event_bus.service_set_changed.connect(self.refresh)

    # -------------------------------------------------------------------------
    # Refresh & Status-Ermittlung
    # -------------------------------------------------------------------------

    def refresh(self) -> None:
        """Laedt Sets, Plugins und den Live-Status neu und informiert alle
        lauschenden Widgets (data_changed)."""
        try:
            self._sets = self.set_repo.list_sets()
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] list_sets() fehlgeschlagen: {e}")
            self._sets = []
        self._active_indicator_ids = self._collect_active_indicator_ids()
        # 05.08.2026: Datum der letzten Ausfuehrung je feature_id (DD.MM.JJ) –
        # wird nach jedem Service-Run (ServiceRunWorker -> EventBus) neu
        # gelesen, damit der MasterTree das Datum live aktualisiert.
        self._last_execution_dates = self._load_last_execution_dates()
        # 11.08.2026 (Bugfix Runde 16c, Dropdown-Anzeige): Datum+Uhrzeit der
        # letzten Ausfuehrung je feature_id – Grundlage der Feld-Dropdown-
        # Anzeige fuer Services OHNE Varianten ('{Name} / {Key} / DD.MM.JJ HH:MM').
        self._last_execution_datetimes = self._load_last_execution_datetimes()
        # 10.08.2026 (Varianten-Ausfuehrungsdatum): Datum der letzten
        # Ausfuehrung je (feature_id, instance_hash) – Grundlage der
        # MasterTree-Varianten-Anzeige '<Preset> (DD.MM.JJ)'. Wird NACH den
        # Plugin-Ausfuehrungsdaten gelesen, damit _load_plugin_presets() die
        # Hash-Daten je Clone mitgeben kann.
        self._last_execution_dates_by_hash = self._load_last_execution_dates_by_hash()
        # 11.08.2026 (Bugfix Runde 16, Dropdown-Anzeige): Datum+Uhrzeit der
        # letzten Ausfuehrung je (feature_id, instance_hash) – Grundlage der
        # Feld-Dropdown-Anzeige '{Name} / {Preset} / DD.MM.JJ HH:MM'.
        self._last_execution_datetimes_by_hash = (
            self._load_last_execution_datetimes_by_hash())
        # 18.01.03 (E1): Kategorie-Overrides (plugin_category_<pid>) laden –
        # einmalig pro Refresh, damit _category_parts() ohne DB-Zugriff
        # auswertet (Baum-Aufbau bleibt rein lesend aus dem RAM).
        self._plugin_category_overrides = self._load_plugin_category_overrides()
        # 18.01.03 (E3-revidiert): Persistierte benutzererzeugte Ordner je
        # Gruppe laden (tree_folders_<group>); build_tree() mischt sie in
        # die Gruppen-Kinder ein (leere Ordner bleiben ueber Refreshs).
        self._empty_folder_paths = self._load_empty_folders()
        # 20.04 (Q7): Presets/Clones je Plugin laden (indicator_presets via
        # StateManager) – Grundlage der Parent-Child-Clone-Ansicht.
        self._plugin_presets = self._load_plugin_presets()
        self.data_changed.emit()

    def _load_empty_folders(self) -> Dict[str, List[str]]:
        """Liest die persistierten benutzererzeugten Ordner je Gruppe.

        Quelle: global_settings (Key 'tree_folders_<group>' aus
        service_set_utils, 18.01.03 E3-revidiert). Liefert pro Gruppe eine
        deduplizierte Liste Slash-Pfade OHNE '📁 '-Praefix (z.B.
        ['Swing Points', 'Swing Points/Geometrie']). Defensiv: Fehler -> leer.
        """
        try:
            from serviceui.service_set_utils import EMPTY_FOLDERS_KEY
        except Exception:
            EMPTY_FOLDERS_KEY = "tree_folders_{}"
        result: Dict[str, List[str]] = {}
        for group in (self.GROUP_SETS, self.GROUP_PLUGINS):
            paths: List[str] = []
            try:
                raw = self.state_manager.get_global_value(
                    EMPTY_FOLDERS_KEY.format(group), [])
                if isinstance(raw, list):
                    for p in raw:
                        p = str(p or "").strip().strip("/")
                        if p and p not in paths:
                            paths.append(p)
            except Exception as e:
                print(f"WARN [ServiceSelectorModel] Leere-Ordner der Gruppe "
                      f"'{group}' nicht lesbar: {e}")
            result[group] = paths
        return result

    def empty_folder_paths(self, group: str) -> List[str]:
        """Persistierte benutzererzeugte Ordner-Pfade einer Gruppe (lesend).

        Gruppe 'sets' oder 'plugins' (GROUP_SETS/GROUP_PLUGINS); unbekannte
        Gruppen -> [] (defensiv). Rein lesend aus dem Refresh-Zustand.
        """
        return list(self._empty_folder_paths.get(str(group or ""), []) or [])

    def _load_plugin_category_overrides(self) -> Dict[str, str]:
        """Liest die Kategorie-Overrides aller Plugins aus global_settings.

        Key-Format: 'plugin_category_<plugin_id>' (18.01.03, E1) – Wert ist
        der Slash-Pfad ("" = Root-Ebene) oder ein leerer Eintrag bei fehlendem
        Override (dann gilt metadata['category']). Defensiv: Fehler -> leer.
        """
        overrides: Dict[str, str] = {}
        try:
            for pid in sorted(self.get_plugins().keys()):
                raw = self.state_manager.get_global_value(
                    f"plugin_category_{pid}", None)
                if isinstance(raw, str):
                    overrides[str(pid).lower()] = raw
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Kategorie-Overrides nicht "
                  f"lesbar: {e}")
        return overrides

    def _load_plugin_presets(self) -> Dict[str, List[Dict[str, Any]]]:
        """Laedt die Presets/Clones aller Plugins (20.04, Q7).

        Quelle: indicator_presets (StateManager.list_plugin_presets,
        plugin_id-Verknuepfung). Der instance_hash wird fuer jedes Preset
        deterministisch aus `generate_instance_hash(plugin_id, params)`
        berechnet (Q2/Q4: ohne lookback, Typ-Sanitizer + sort_keys). Ein
        Preset gilt als archiviert, wenn `is_active_batch = False` (Q7:
        Archivierung eines Presets => is_active_batch = False; die Scans
        isolieren diese Presets). Rueckgabe: plugin_id.lower() -> Liste
        von {"preset_name", "params", "instance_hash", "is_archived",
        "doc_log"}.
        Defensiv: Fake-/Alt-StateManager ohne list_plugin_presets liefern
        leere Dicts (kein Baum-Rendering, keine Regression in Tests).
        """
        result: Dict[str, List[Dict[str, Any]]] = {}
        try:
            for pid in sorted(self.get_plugins().keys()):
                raw = self.state_manager.list_plugin_presets(pid)
                if not raw:
                    continue
                clones: List[Dict[str, Any]] = []
                for p in raw or []:
                    if not isinstance(p, dict):
                        continue
                    params = p.get("params") or {}
                    # 11.08.2026 (Bugfix Varianten-Kollision): Der
                    # instance_hash eines Presets wird inkl. preset_name
                    # berechnet (generate_instance_hash mit preset_name) –
                    # Presets mit identischen Parametern aber unterschiedlichen
                    # Namen erhalten dadurch UNTERSCHIEDLICHE Hashes (vorher
                    # kollidierten sie: Runs/Ausfuehrungsdatum trafen alle
                    # Varianten gemeinsam).
                    preset_name = str(p.get("preset_name") or "Default")
                    instance_hash = generate_instance_hash(
                        pid, params, preset_name=preset_name)
                    per_hash = self._last_execution_dates_by_hash.get(
                        str(pid).lower(), {}) or {}
                    clones.append({
                        "preset_name": preset_name,
                        "params": params,
                        "instance_hash": instance_hash,
                        "is_archived": not bool(p.get("is_active_batch")),
                        "doc_log": str(p.get("doc_log") or ""),
                        # 10.08.2026: Datum der letzten Ausfuehrung dieser
                        # Parameter-Variante (Feature-Store, Spalte
                        # instance_hash) – fuer die MasterTree-Anzeige
                        # '<Preset> (DD.MM.JJ)'. Fallback '--.--.--'.
                        # 11.08.2026 (Runde 2): KEIN Legacy-Fallback mehr –
                        # Alt-Rows unter dem alten Params-only-Hash sind keiner
                        # Variante eindeutig zuordenbar (Pool) und wuerden sonst
                        # an ALLEN kollidierenden Varianten dasselbe Datum
                        # zeigen (User-Meldung). Eine Variante zeigt ein Datum
                        # erst, wenn sie unter ihrem EIGENEN Hash gelaufen ist.
                        "last_execution": per_hash.get(
                            instance_hash, "--.--.--"),
                    })
                if clones:
                    result[str(pid).lower()] = clones
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Plugin-Presets nicht lesbar: {e}")
        return result

    def _load_last_execution_dates(self) -> Dict[str, str]:
        """Liest das Datum der letzten Ausfuehrung je feature_id aus dem
        feature_store (rein lesend ueber den FeatureStoreReader, Invariante
        4: kein SQL im Modell). Defensiv: Fehler -> leer (Baum zeigt dann
        den Fallback '(--.--.--)')."""
        try:
            raw = self.feature_store_reader.fetch_last_execution_dates() or {}
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Ausfuehrungsdaten nicht "
                  f"lesbar: {e}")
            return {}
        # Case-insensitive Zuordnung (feature_id ist die Plugin-ID, z.B.
        # 'srv_proximity' – Registry-IDs sind case-insensitiv).
        return {str(k).lower(): v for k, v in raw.items()}

    def _load_last_execution_datetimes(self) -> Dict[str, str]:
        """Liest Datum+Uhrzeit der letzten Ausfuehrung je feature_id.

        11.08.2026 (Bugfix Runde 16c, Dropdown-Anzeige): Delegate an den
        FeatureStoreReader (fetch_last_execution_datetimes) – das
        Feld-Dropdown haengt an Services OHNE Varianten (Standalone) das
        Ausfuehrungsdatum an ('DD.MM.JJ HH:MM'). Defensiv: Fehler -> leer
        (Eintraege zeigen dann keinen Datums-Anhang).
        """
        try:
            raw = self.feature_store_reader.fetch_last_execution_datetimes() or {}
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Ausfuehrungsdaten "
                  f"(Datum+Uhrzeit) nicht lesbar: {e}")
            return {}
        return {str(k).lower(): v for k, v in raw.items()}

    def last_execution_datetime(self, plugin_id: str) -> str:
        """Datum+Uhrzeit der letzten Ausfuehrung eines Services.

        11.08.2026 (Bugfix Runde 16c, Dropdown-Anzeige): Format 'DD.MM.JJ HH:MM'
        (z. B. '23.04.26 22:14') – Fallback '--.--.-- --:--' ohne Eintraege.
        Quelle: MAX(created_at) des feature_store fuer die feature_id
        (Plugin-ID) des Services ueber ALLE Varianten/Symbole/Timeframes.
        Rein lesend aus dem Refresh-Zustand.
        """
        if not plugin_id:
            return "--.--.-- --:--"
        return self._last_execution_datetimes.get(
            str(plugin_id).lower(), "--.--.-- --:--")

    def last_execution_date(self, plugin_id: str) -> str:
        """Formatiertes Datum der letzten Ausfuehrung eines Services
        ('DD.MM.JJ', z.B. '05.08.26') – Fallback '--.--.--' ohne Eintraege.

        Der Zeitstempel stammt aus MAX(created_at) des feature_store fuer
        die feature_id (Plugin-ID) des Services. store_plugin_payload()
        aktualisiert created_at bei jedem Upsert, sodass der Wert die
        LETZTE Ausfuehrung widerspiegelt.

        Achtung (05.08.2026, Punkt 1): Der Rueckgabewert enthaelt BEWUSST
        KEINE Klammern – der MasterTree umschliesst ihn beim Label-Aufbau
        ('Service_Name (DD.MM.JJ)' / 'Service_Name (--.--.--)'), damit der
        Fallback nicht doppelt geklammert wird.
        """
        if not plugin_id:
            return "--.--.--"
        return self._last_execution_dates.get(
            str(plugin_id).lower(), "--.--.--")

    def last_execution_date_for_hash(
        self, plugin_id: str, instance_hash: str
    ) -> str:
        """Datum der letzten Ausfuehrung einer Parameter-Variante.

        10.08.2026 (Varianten-Ausfuehrungsdatum): Varianten/Clones haben
        EIGENE Feature-Store-Rows (Spalte instance_hash). Formatiert als
        'DD.MM.JJ' – Fallback '--.--.--' ohne Eintraege (bzw. ohne
        instance_hash). Rueckgabewert ohne Klammern (MasterTree-Wrapper).

        11.08.2026 (Runde 2): KEIN Legacy-Fallback – das Datum kommt NUR aus
        Rows unter dem EIGENEN (Preset-eindeutigen) Hash der Variante.
        """
        if not plugin_id or not instance_hash:
            return "--.--.--"
        per_hash = self._last_execution_dates_by_hash.get(
            str(plugin_id).lower(), {}) or {}
        return per_hash.get(str(instance_hash), "--.--.--")

    def _load_last_execution_dates_by_hash(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """Liest die Varianten-Ausfuehrungsdaten je (feature_id, hash).

        10.08.2026: Delegate an den FeatureStoreReader
        (fetch_last_execution_dates_by_hash). Defensiv: Fehler -> leer
        (Clones zeigen dann den Fallback '(--.--.--)').
        """
        try:
            raw = self.feature_store_reader.fetch_last_execution_dates_by_hash() or {}
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Varianten-Ausfuehrungsdaten "
                  f"nicht lesbar: {e}")
            return {}
        return {str(k).lower(): v for k, v in raw.items()}

    def _load_last_execution_datetimes_by_hash(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """Liest die Varianten-Ausfuehrungsdaten je (feature_id, hash) mit Uhrzeit.

        11.08.2026 (Bugfix Runde 16, Dropdown-Anzeige): Delegate an den
        FeatureStoreReader (fetch_last_execution_datetimes_by_hash) - die
        Feld-Dropdown-Anzeige '{Name} / {Preset} / DD.MM.JJ HH:MM' braucht
        Datum+Uhrzeit der letzten Ausfuehrung. Defensiv: Fehler -> leer
        (Eintraege zeigen dann keinen Datums-Anhang).
        """
        try:
            raw = self.feature_store_reader.fetch_last_execution_datetimes_by_hash() or {}
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Varianten-Ausfuehrungsdaten "
                  f"(Datum+Uhrzeit) nicht lesbar: {e}")
            return {}
        return {str(k).lower(): v for k, v in raw.items()}

    def last_execution_datetime_for_hash(
        self, plugin_id: str, instance_hash: str
    ) -> str:
        """Datum+Uhrzeit der letzten Ausfuehrung einer Parameter-Variante.

        11.08.2026 (Bugfix Runde 16, Dropdown-Anzeige): Format 'DD.MM.JJ HH:MM'
        (z. B. '23.04.26 22:14') - Fallback '--.--.-- --:--' ohne Eintraege
        (bzw. ohne instance_hash). Rein lesend aus dem Refresh-Zustand.

        11.08.2026 (Runde 2): KEIN Legacy-Fallback – das Datum kommt NUR aus
        Rows unter dem EIGENEN (Preset-eindeutigen) Hash der Variante.
        """
        if not plugin_id or not instance_hash:
            return "--.--.-- --:--"
        per_hash = self._last_execution_datetimes_by_hash.get(
            str(plugin_id).lower(), {}) or {}
        return per_hash.get(str(instance_hash), "--.--.-- --:--")

    def _collect_active_indicator_ids(self) -> Set[str]:
        """Sammelt alle indicator_ids/plugin_ids, die in offenen Chart-
        Fenstern aktiv sind (indicators_state[..]['active'] == True).

        Quelle: StateManager.load_all_instances() – pro Fenster-Instanz wird
        das indicators_state-JSON ausgewertet. Defensiv gegen fehlende/leere
        Eintraege und JSON-Strings (DuckDB liefert die JSON-Spalte teils als
        String).
        """
        active: Set[str] = set()
        try:
            for inst in self.state_manager.load_all_instances() or []:
                ind_state = self._as_dict(inst.get("indicators_state"))
                if not ind_state:
                    continue
                for ind_id, st in ind_state.items():
                    if isinstance(st, dict) and st.get("active"):
                        active.add(str(ind_id))
        except Exception as e:
            print(f"WARN [ServiceSelectorModel] Aktiv-Status nicht lesbar: {e}")
        return active

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        """Wandelt einen Wert defensiv in ein Dict um (JSON-String oder dict)."""
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                from db_service import _parse_json_field
                parsed = _parse_json_field(value)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    # -------------------------------------------------------------------------
    # Lese-API (fuer Widgets & Tests)
    # -------------------------------------------------------------------------

    def get_sets(self) -> List[Dict[str, Any]]:
        """Alle gespeicherten Service-Sets (volle Definitionen)."""
        return list(self._sets)

    def get_plugins(self) -> Dict[str, Any]:
        """Alle registrierten Plugins (plugin_id.lower() -> PluginFeature)."""
        return dict(getattr(self.registry, "plugins", {}) or {})

    def get_plugin(self, plugin_id: str) -> Optional[Any]:
        """Plugin aus der Registry (case-insensitiv) oder None."""
        try:
            return self.registry.get(plugin_id)
        except (KeyError, AttributeError):
            return None

    def is_chart_indicator(self, plugin_id: str) -> bool:
        """True, wenn das Plugin als Chart-Indikator verfuegbar ist
        (capabilities['chart'] == True)."""
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return False
        try:
            return bool((plugin.capabilities or {}).get("chart", False))
        except Exception:
            return False

    def get_indicator_id(self, plugin_id: str) -> str:
        """Indikator-ID, in der das Plugin laeuft (metadata['indicator_id']).

        Services (srv_grid_lines/srv_proximity) laufen IN einem Indikator
        (Ind_FixedGridProximity -> 'ind_fixed_grid_proximity'); aktiv im Chart sind
        die indicators_state-Keys des Indikators, nicht die Plugin-ID.
        Ohne Angabe faellt die Methode auf die plugin_id selbst zurueck.
        """
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return plugin_id
        try:
            meta = plugin.metadata or {}
            return str(meta.get("indicator_id") or plugin_id)
        except Exception:
            return plugin_id

    def belongs_to_indicator(self, plugin_id: str) -> bool:
        """True, wenn das Plugin explizit einem Indikator zugeordnet ist.

        Signal: metadata['indicator_id'] ODER metadata['indicator_name'] sind
        gesetzt (z.B. Ind_FixedGridProximity fuer srv_grid_lines/srv_proximity).
        """
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return False
        try:
            meta = plugin.metadata or {}
            return bool(meta.get("indicator_id") or meta.get("indicator_name"))
        except Exception:
            return False

    def get_indicator_display_name(self, plugin_id: str) -> str:
        """Anzeige-Name des Indikators zu einer Plugin-ID.

        Bevorzugt metadata['indicator_name'] (echter Indikatorname, z.B.
        'Ind_FixedGridProximity'); Fallback metadata['display_name']
        (Service-Name) bzw. plugin_id.
        """
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return plugin_id
        try:
            meta = plugin.metadata or {}
            return str(meta.get("indicator_name")
                       or meta.get("display_name") or plugin_id)
        except Exception:
            return plugin_id

    def is_active_in_chart(self, plugin_id: str) -> bool:
        """True, wenn das Plugin in mind. einem Chart-Fenster aktiv ist.

        Bugfix 05.08.2026: Beruecksichtigt zusaetzlich den ZUGEHOERIGEN
        Indikator (metadata['indicator_id']). Services laufen IN einem
        Indikator – aktiv im Chart sind die indicators_state-Keys des
        Indikators ('ind_fixed_grid_proximity'), nicht die Plugin-ID selbst. Dadurch
        greift die Tooltip-Variante a) ('aktiv <Indikator>') auch fuer
        Services wie srv_grid_lines/srv_proximity.
        """
        key = str(plugin_id).lower()
        if any(pid.lower() == key for pid in self._active_indicator_ids):
            return True
        ind_id = self.get_indicator_id(plugin_id)
        if ind_id and ind_id.lower() != key:
            return any(pid.lower() == ind_id.lower()
                       for pid in self._active_indicator_ids)
        return False

    def get_set_indicator_names(self, definition: Dict[str, Any]) -> List[str]:
        """Distinkte Indikator-Namen eines Service-Sets.

        Bugfix 05.08.2026: Ein explizit zugewiesenes Feld `indicator_id` in
        der Set-Definition (Anlage-Dialog) wird zuerst ausgewertet; zusaetz-
        lich liefern Services mit Indikator-Zugehoerigkeit (in execution_
        order-Reihenfolge) weitere Indikatoren. Leer, wenn das Set keinem
        Indikator gehoert.
        """
        names: List[str] = []
        explicit = str(definition.get("indicator_id") or "")
        if explicit:
            nm = indicator_display_name(explicit)
            if nm and nm not in names:
                names.append(nm)
        services = definition.get("services") or {}
        order = definition.get("execution_order") or list(services.keys())
        for iid in order:
            cfg = services.get(iid) or {}
            if not isinstance(cfg, dict):
                continue
            pid = str(cfg.get("plugin_id") or iid)
            if not self.belongs_to_indicator(pid):
                continue
            nm = self.get_indicator_display_name(pid)
            if nm and nm not in names:
                names.append(nm)
        return names

    def is_set_active(self, definition: Dict[str, Any]) -> bool:
        """True, wenn mindestens ein Service des Sets aktuell aktiv in einem
        Chart verwendet wird (der zugehoerige Indikator ist aktiv)."""
        services = definition.get("services") or {}
        for cfg in services.values():
            if isinstance(cfg, dict) and cfg.get("plugin_id"):
                if self.is_active_in_chart(str(cfg["plugin_id"])):
                    return True
        return False

    def badge_for(self, plugin_id: str) -> str:
        """Kompaktes Status-Badge (Spalte 1 des MasterTree).

        Die Badges referenzieren den INDIKATOR-Namen (metadata['indicator_name'],
        z.B. 'Ind_FixedGridProximity') – Service-Namen erscheinen hier bewusst
        NICHT:

            "📌 im Ind_FixedGridProximity | 🟢 aktiv in Ind_FixedGridProximity"
            "📌 im Ind_FixedGridProximity | ⚪ inaktiv in Ind_FixedGridProximity"
            "⚪ inaktiv in Ind_FixedGridProximity"   (kein Chart-Indikator)
            "🟢 aktiv in Ind_FixedGridProximity"     (kein Chart-Indikator, aktiv)
        """
        parts: List[str] = []
        name = self.get_indicator_display_name(plugin_id)
        if self.is_chart_indicator(plugin_id):
            parts.append(f"📌 im {name}")
        parts.append(f"🟢 aktiv in {name}" if self.is_active_in_chart(plugin_id)
                     else f"⚪ inaktiv in {name}")
        return " | ".join(parts)

    # ------------------------------------------------------------------
    # 16.08 (K1/K2/K8/K9): Kategorie-Ordner (Dynamic Category Trees)
    # ------------------------------------------------------------------
    # 18.01.02 (E6): Die Baum-Konstruktions-/Aufloesungslogik ist in
    # `analytics/engine/tree_builder.py` ausgelagert (reine Modul-Funktionen,
    # keine Zirkularitaet). Dieses Modell bleibt die oeffentliche API und
    # delegiert hierher (dünne Wrapper).

    @staticmethod
    def _cat_key(label: str) -> str:
        """Case-insensitiver Sortier-/Vergleichsschluessel eines Ordners.

        Delegation an tree_builder._cat_key (18.01.02 E6).
        """
        from analytics.engine.tree_builder import _cat_key as _tb_cat_key
        return _tb_cat_key(label)

    def category_plugin_ids(self, category_path: str) -> List[str]:
        """Alle Plugin-IDs unter einem Kategorie-Pfad (rekursiv, 17.01.02).

        Liefert deterministisch (alphabetisch) alle Plugins, deren
        `metadata['category']`-Pfad mit `category_path` beginnt – d.h. auch
        Plugins in UNTER-Ordnern (z.B. Pfad 'Swing Points' liefert auch
        Plugins aus 'Swing Points/Geometrie'). Pfad-Format: slash-separiert
        OHNE '📁 '-Praefixe (z.B. 'Swing Points/Geometrie'), case-insensitiv.

        Grundlage fuer:
          * Kontextmenue '▶️ Alle Services ausführen' auf Ordner-Knoten
            (run_category_requested).
          * Info-Button auf Ordner-Knoten (category_info_requested).
        """
        from analytics.engine.tree_builder import category_plugin_ids
        return category_plugin_ids(self.get_plugins(),
                                   self._plugin_category_overrides,
                                   category_path)

    def category_set_ids(self, category_path: str) -> List[str]:
        """Alle set_ids unter einem Kategorie-Pfad (rekursiv, 18.01.03).

        Liefert deterministisch (Set-Reihenfolge = display_name) alle Sets,
        deren `category`-Pfad mit `category_path` beginnt – d.h. auch Sets in
        UNTER-Ordnern (z.B. Pfad 'Swing Points' liefert auch Sets aus
        'Swing Points/Geometrie'). Pfad-Format: slash-separiert OHNE
        '📁 '-Praefixe, case-insensitiv. Analog `category_plugin_ids` fuer
        die Sets-Gruppe.
        """
        from analytics.engine.tree_builder import category_set_ids
        return category_set_ids(self._sets, category_path)

    def plugin_category_path(self, plugin_id: str) -> str:
        """Aktueller Kategorie-Pfad eines Plugins (lesend, 18.01.03).

        Liefert den voll aufgeloesten Pfad (Override -> metadata['category'])
        slash-separiert OHNE '📁 '-Praefix (z.B. 'Swing Points/Geometrie');
        leer = Root-Ebene. Grundlage fuer die Ordner-Verschiebung und
        Rename-String-Replace im Orchestrator.
        """
        from analytics.engine.tree_builder import plugin_category_path
        plugin = self.get_plugin(plugin_id)
        return plugin_category_path(plugin_id, plugin,
                                    self._plugin_category_overrides)

    def category_service_plugin_ids(self, group: str,
                                    category_path: str) -> List[str]:
        """Alle plugin_ids unter einem Kategorie-Ordner (rekursiv, 18.01.03).

        Gruppenspezifische Aufloesung (L3):
          * group == GROUP_SETS    -> Sets unter dem Pfad
            (category_set_ids), dann alle plugin_ids ihrer Services
            (execution_order, dedupliziert, deterministisch).
          * group == GROUP_PLUGINS -> Plugins unter dem Pfad
            (category_plugin_ids).
        Leerer Pfad/leere Gruppe -> [] (defensiv). Wird von den Run-/Info-
        Aktionen des ServiceWindow und der Picker-Aufloesung genutzt.
        """
        from analytics.engine.tree_builder import category_service_plugin_ids
        return category_service_plugin_ids(group, self._sets,
                                           self.get_plugins(),
                                           self._plugin_category_overrides,
                                           category_path)

    def build_tree(self) -> List[Dict[str, Any]]:
        """Baut die vollstaendige Hierarchie fuer das 2-Spalten-MasterTree.

        17.01.01: NUR noch 2 Root-Gruppen – die ehemalige Gruppe
        '⚡ Standalone Services' (GROUP_STANDALONE) entfaellt ersatzlos, da
        alle Plugins ueber metadata['category'] in Ordner einsortiert werden.
        Root-Label kompakt: '📁 Sets' und '📦 Services'.

        Rueckgabe (pro Gruppe ein Dict):
            [{"group": "sets", "label": "📁 Sets", "children": [
                 {"set_id": ..., "display_name": ..., "definition": {...},
                  "services": [{"instance_id": ..., "plugin_id": ...,
                                "badge": ...}, ...]}, ...]},
             {"group": "plugins", "label": "📦 Services",
              "children": [Blatt- und/oder Ordner-Knoten ...]}]

        Deterministisch sortiert (Sets nach display_name; Plugins/Ordner
        alphabetisch, 16.08 K8). Die Baum-Logik selbst ist seit 18.01.02 (E6)
        in `analytics/engine/tree_builder.build_tree` ausgelagert – dieses
        Modell berechnet lediglich die Badges/Ausfuehrungsdaten und delegiert.
        """
        from analytics.engine.tree_builder import build_tree as _tb_build_tree
        plugins = self.get_plugins()
        badges: Dict[str, str] = {pid: self.badge_for(pid) for pid in plugins}
        last_executions: Dict[str, str] = {
            pid: self.last_execution_date(pid) for pid in plugins}
        # 20.04 (Q7): Presets/Clones je Plugin durchreichen – Plugins MIT
        # Presets werden als Parent-Knoten mit Clone-Kindern gerendert,
        # archivierte Clones (is_archived) in den '📁 Archiv'-Ordner.
        return _tb_build_tree(self._sets, plugins,
                              self._plugin_category_overrides,
                              self._empty_folder_paths,
                              badges, last_executions,
                              presets=self._plugin_presets)

    def plugin_presets(self) -> Dict[str, List[Dict[str, Any]]]:
        """Presets/Clones je Plugin (20.04, Q7) – lesend fuer Widgets/Tests.

        Liefert plugin_id.lower() -> Liste von {"preset_name", "params",
        "instance_hash", "is_archived", "doc_log"} (Quelle:
        indicator_presets). Wird in refresh() aktualisiert; leere Dicts
        bei Fake-/Alt-StateManagern.
        """
        return dict(self._plugin_presets)

    def find_set(self, set_id: str) -> Optional[Dict[str, Any]]:
        """Liefert die Set-Definition zur set_id (oder None)."""
        for s in self._sets:
            if s.get("set_id") == set_id:
                return s
        return None

    def find_service(self, set_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
        """Liefert die Service-Konfiguration (instance_id) eines Sets (oder None)."""
        s = self.find_set(set_id)
        if not s:
            return None
        return (s.get("services") or {}).get(instance_id)

    # ------------------------------------------------------------------
    # 15.03-E (Multi-Select): Anzeigenamen zu feature_ids (Reverse-Mapping)
    # ------------------------------------------------------------------
    def resolve_display_names(self, feature_ids) -> List[str]:
        """Leitbare Anzeigenamen zu plugin_ids (Fallback: die id selbst).

        Wird vom AnalyticsWindow genutzt, wenn nach einem Profilwechsel nur
        die persistierten feature_ids (plugin_ids) vorliegen, aber keine
        display_names (der Dialog wurde nicht geoeffnet). Matcht Set-Services
        deterministisch (erster Treffer in Set-Reihenfolge) und liefert
        '<Set-Anzeigename>/<instance_id>'; ohne Treffer die plugin_id.
        """
        names: List[str] = []
        for fid in feature_ids or []:
            target = str(fid).strip().lower()
            if not target:
                continue
            found: Optional[str] = None
            for s in self._sets:
                services = s.get("services") or {}
                for iid, cfg in services.items():
                    if not isinstance(cfg, dict):
                        continue
                    pid = str(cfg.get("plugin_id") or iid).strip().lower()
                    if pid == target:
                        set_name = s.get("display_name") or s.get("set_id") or "?"
                        found = f"{set_name}/{iid}"
                        break
                if found:
                    break
            names.append(found if found else str(fid))
        return names

    # ------------------------------------------------------------------
    # 20.01 (E5): Fault-Tolerant Resolver fuer persistierte feature_ids
    # ------------------------------------------------------------------
    def resolve_valid_feature_ids(
        self, feature_ids: List[str]
    ) -> Tuple[List[str], List[str]]:
        """Prueft feature_ids gegen die PluginRegistry (Phase 20.01, E5).

        Wird vom AnalyticsViewModel beim Profil-/Workspace-Restore genutzt,
        um entfernte/umbenannte Plugins (fehlende feature_ids) zu isolieren:
        die validen IDs bleiben aktiv, die fehlenden werden gemeldet
        (missing_services_detected -> Warn-Label, Graceful Degradation).

        Returns:
            (valid_ids, missing_ids): gueltige Plugin-IDs (case-insensitiv,
            dedupliziert, Reihenfolge erhalten) und nicht (mehr) registrierte
            IDs. `'native'` ist der Feature-Store-Sentinel des nativen
            Feature-Builder-Pfads (kein Plugin) und gilt als fehlend (B7) –
            der ServiceSelectorDialog emittiert ausschliesslich plugin_ids.
        """
        valid: List[str] = []
        missing: List[str] = []
        seen: Set[str] = set()
        for fid in feature_ids or []:
            key = str(fid or "").strip()
            if not key or key.lower() in seen:
                continue
            seen.add(key.lower())
            if self.get_plugin(key) is not None:
                valid.append(key)
            else:
                missing.append(key)
        return valid, missing

```

--------------------------------------------------

### DATEI: analytics/engine/service_set_repository.py
```py
# analytics/engine/service_set_repository.py
"""
Phase 13 Schritt 2 – ServiceSetRepository.

Kapselt das Laden/Speichern von Service-Sets in einer eigenen Tabelle
`service_sets` in app_data.duckdb. Der StateManager wird NICHT angefasst –
das Repository hält seine Persistenz vollständig selbst.

Tabelle service_sets:
    set_id        VARCHAR PRIMARY KEY
    display_name  VARCHAR
    definition    JSON (vollständige ServiceSetDefinition)
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP

Pflicht-API (Roadmap §Schritt 2.2):
    save_set()   – speichert/überschreibt ein Set (Upsert); generiert bei
                   leerem display_name einen Default-Namen aus instance_ids
                   (z.B. "grid_1 + prox_1"). Liefert die set_id zurück.
    get_set()    – lädt eine Definition per set_id (oder None).
    list_sets()  – liefert ALLE gespeicherten Sets (Quelle für die
                   Set-Dropdowns im Prop-/Service-Fenster).
    delete_set() – entfernt ein Set sauber (liefert bool).
"""

import copy
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from db_service import DbPool, _parse_json_field
from analytics.engine.schema_migrator import MigrationError

# Projekt-Root = 3 Ebenen über dieser Datei (engine/ → analytics/ → Projekt-Root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
APP_DB_PATH = str(BASE_DIR / "data" / "app_data.duckdb")


class ServiceSetRepository:
    """Persistenz-Layer für Service-Sets (eigene Tabelle in app_data.duckdb)."""

    def __init__(self, db_path: str = APP_DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    # -------------------------------------------------------------------------
    # Interna
    # -------------------------------------------------------------------------
    def _get_connection(self) -> Any:
        return DbPool.get(self.db_path)

    def _init_db(self) -> None:
        """Legt die Tabelle service_sets an (lazy, idempotent)."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = self._get_connection()
        con.execute("""
            CREATE TABLE IF NOT EXISTS service_sets (
                set_id       VARCHAR PRIMARY KEY,
                display_name VARCHAR,
                definition   JSON NOT NULL,
                description  VARCHAR,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Phase 14 P14-01: Additive Spalte für bestehende Datenbanken (idempotent)
        con.execute("ALTER TABLE service_sets ADD COLUMN IF NOT EXISTS description VARCHAR;")
        # Phase 14 P14-05: Papierkorb- & Historien-Tabellen (Soft-Delete &
        # Deterministische Snapshots). Idempotent – bestehende DBs werden
        # additiv erweitert (Invariante 9: Snapshot nur bei Überschreiben).
        con.execute("""
            CREATE TABLE IF NOT EXISTS service_sets_trash (
                set_id       VARCHAR PRIMARY KEY,
                display_name VARCHAR,
                definition   JSON,
                deleted_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS service_set_history (
                history_id VARCHAR PRIMARY KEY,
                set_id     VARCHAR,
                version    VARCHAR,
                definition JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Phase 14 P14-04 (Bestands-Migration): Nach dem ALTER TABLE laufende
        # Sets bereinigen (fehlende description-Felder mit "" auffüllen).
        self._migrate_existing_sets()

    def _migrate_existing_sets(self) -> None:
        """Phase 14 P14-04 (Bestands-Migration, idempotent).

        Lädt alle vorhandenen Service-Sets und prüft, ob das `description`-
        Feld fehlt. Fehlt es, wird es mit `""` aufgefüllt und das Set erneut
        gespeichert. Damit haben alle Bestands-Sets nach dem Öffnen ein
        konsistentes Beschreibungsfeld (P14-01-Spalte + JSON-Payload).

        Läuft direkt nach dem `ALTER TABLE` in `_init_db()`. Fehler einzelner
        Sets brechen die Initialisierung nicht ab (Skip-Logik).
        """
        try:
            con = self._get_connection()
            rows = con.execute(
                "SELECT set_id, definition FROM service_sets"
            ).fetchall()
        except Exception as e:
            print(f"WARN [ServiceSetRepository] Bestands-Migration Lesen "
                  f"fehlgeschlagen: {e}")
            return
        for set_id, definition_json in rows:
            if not set_id:
                continue
            definition = _parse_json_field(definition_json) or {}
            if "description" in definition:
                continue
            definition["description"] = ""
            try:
                # P14-05: record_snapshot=False – die Bestands-Migration ist ein
                # interner Verwaltungsschreibvorgang (nur description ergänzen)
                # und darf KEINE Snapshot-Historie erzeugen (Invariante 9:
                # Snapshot nur bei Nutzer-Überschreiben).
                self.save_set(definition, record_snapshot=False)
                print(f"  . Bestandsset '{set_id}': description aufgefuellt (P14-04)")
            except Exception as e:
                print(f"WARN [ServiceSetRepository] Bestands-Migration Set "
                      f"'{set_id}' fehlgeschlagen: {e}")

    @staticmethod
    def _default_display_name(definition: Dict[str, Any]) -> str:
        """Default-Name aus den instance_ids der execution_order.

        Beispiel: execution_order=["grid_1", "prox_1"] → "grid_1 + prox_1".
        Nur instance_ids, die auch in services existieren, werden verwendet.
        """
        order = definition.get("execution_order") or []
        services = definition.get("services") or {}
        names = [iid for iid in order if iid in services]
        if not names:
            names = list(services.keys())
        return " + ".join(names) if names else "Unbenanntes Set"

    @staticmethod
    def _semver_bump_patch(version: str) -> str:
        """Erhoeht die Patch-Stufe einer Semantic-Version (1.2.3 -> 1.2.4).

        Dient dem Set-Level `version`-Feld (Kap 5 AKTUELLE_UMSETZUNG): Bei jedem
        Ueberschreiben eines Sets wird die Patch-Stufe automatisch angehoben,
        sofern der Aufrufer keine explizite Version mitgibt. Ungueltige/leere
        Versionen werden als "0.0.1" behandelt (defensiv).
        """
        parts = str(version or "0.0.0").split(".")
        try:
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            return "0.0.1"
        return f"{major}.{minor}.{patch + 1}"

    # -------------------------------------------------------------------------
    # Pflicht-API
    # -------------------------------------------------------------------------
    def save_set(self, definition: Dict[str, Any], record_snapshot: bool = True) -> str:
        """Speichert ein Service-Set (Upsert) und liefert die set_id zurück.

        - set_id leer → wird als uuid4-hex generiert.
        - display_name leer → Default-Name aus instance_ids (z.B. 'grid_1 + prox_1').
        - Gleiche set_id überschreibt die bestehende Zeile (kein Duplikat).

        Phase 14 P14-05 (Deterministische Snapshot-Historie): Existiert das Set
        bereits in service_sets (Überschreiben), wird UNMITTELBAR VOR dem
        Überschreiben der bisherige Stand als Snapshot in service_set_history
        gesichert (version = fortlaufender Zähler je set_id). Bei reinen
        Neuanlagen oder Schreibfehlern entsteht KEIN Snapshot (Invariante 9).

        Kap 5 AKTUELLE_UMSETZUNG (Set-Level Metadaten, additiv): Jede Definition
        erhält automatisch die Felder
          - version         Set-Level Semantic Version (major.minor.patch).
                            Aufrufer-Version gewinnt; sonst Patch-Bump beim
                            Überschreiben, "1.0.0" bei Neuanlage.
          - schema_version  Format-Version der Definition ("1.0", Default).
          - created_at      Erstellungs-Zeitstempel (ISO-8601 UTC); wird bei
                            Überschreiben aus dem Bestand übernommen.
        Bestehende Sets werden beim nächsten Speichern automatisch auf diese
        Felder nachgezogen (idempotent, kein Datenverlust).

        Args:
            definition: ServiceSetDefinition.
            record_snapshot: False unterdrückt die Snapshot-Erzeugung für
                interne Verwaltungsschreibvorgänge (z. B. die P14-04
                Bestands-Migration, die Bestands-Sets nur um description
                ergänzt und dafür keinen Historie-Eintrag erzeugen darf).
        """
        set_id = str(definition.get("set_id") or uuid.uuid4().hex)
        display_name = str(definition.get("display_name") or "").strip()
        if not display_name:
            display_name = self._default_display_name(definition)
        # Phase 14 P14-01: description optional – wird in der eigenen Spalte
        # UND im JSON-Payload persistiert (Definition bleibt vollständig).
        description = definition.get("description")
        description = str(description).strip() if description is not None else None

        con = self._get_connection()

        # Kap 5 AKTUELLE_UMSETZUNG: Set-Level Metadaten (version/schema_version/
        # created_at). Bestand lesen, damit created_at bei Überschreiben erhalten
        # bleibt und die Snapshot-Historie denselben Lesezugriff nutzen kann.
        existing_row = con.execute(
            "SELECT definition FROM service_sets WHERE set_id = ?", [set_id]
        ).fetchone()
        existing_def = _parse_json_field(existing_row[0]) if existing_row else {}

        if definition.get("version"):
            version = str(definition["version"])
        elif existing_def.get("version"):
            version = self._semver_bump_patch(str(existing_def["version"]))
        else:
            version = "1.0.0"
        schema_version = str(
            definition.get("schema_version")
            or existing_def.get("schema_version")
            or "1.0"
        )
        created_at = definition.get("created_at") or existing_def.get("created_at")
        if not created_at:
            created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        payload = {
            "set_id": set_id,
            "display_name": display_name,
            "description": description,
            # Bugfix 05.08.2026: Explizite Indikator-Zuordnung (Anlage-Dialog)
            # wird in der Definition persistiert (kein Service noetig).
            "indicator_id": definition.get("indicator_id"),
            # 18.01.03 (E2): Sets-Kategorie (Dynamic Category Trees) – der
            # Slash-Pfad (z.B. 'Swing Points/Geometrie') wird additiv
            # persistiert; leer/fehlend = Root-Ebene der Sets-Gruppe.
            "category": definition.get("category"),
            "version": version,
            "schema_version": schema_version,
            "created_at": created_at,
            "execution_order": definition.get("execution_order", []),
            "services": definition.get("services", {}),
        }

        # P14-05: Snapshot-Historie – NUR bei erfolgreichem Überschreiben eines
        # BEREITS EXISTIERENDEN Sets (vor dem Upsert).
        if record_snapshot:
            if existing_row:
                old_definition = existing_def or {}
                history_count = con.execute(
                    "SELECT COUNT(*) FROM service_set_history WHERE set_id = ?",
                    [set_id],
                ).fetchone()
                count = int(history_count[0]) if history_count and history_count[0] else 0
                con.execute("""
                    INSERT INTO service_set_history (history_id, set_id, version, definition, created_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, [uuid.uuid4().hex, set_id, str(count + 1),
                      json.dumps(old_definition)])

        con.execute("""
            INSERT INTO service_sets (set_id, display_name, definition, description, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (set_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                definition   = EXCLUDED.definition,
                description  = EXCLUDED.description,
                updated_at   = EXCLUDED.updated_at
        """, [set_id, display_name, json.dumps(payload), description])
        return set_id

    def get_set(self, set_id: str) -> Optional[Dict[str, Any]]:
        """Lädt eine Service-Set-Definition per set_id (oder None).

        Phase 14 P14-04: Wendet den SchemaMigrator TRANSPARENT IM SPEICHER an
        (Semantic Versioning): Abweichende Instanz-Konfigurationen werden
        gegen das aktuelle Plugin-Schema migriert (Defaults ergänzt, veraltete
        Keys entfernt, Version angehoben). Die Datenbank bleibt unverändert.

        ROLLBACK-SCHUTZ: Tritt während der Migration ein MigrationError auf,
        wird die Migration abgebrochen und das UNMIGRIERTE Original-Set
        zurückgegeben (Rollback auf Datenbank-Ebene, Invariante 8).
        """
        con = self._get_connection()
        res = con.execute(
            "SELECT set_id, display_name, definition, description FROM service_sets WHERE set_id = ?",
            [set_id],
        ).fetchone()
        if not res:
            return None
        db_set_id, db_display_name, definition_json, db_description = res
        definition = _parse_json_field(definition_json) or {}
        # DB-Spalten sind die Single Source of Truth für set_id/display_name
        definition["set_id"] = str(db_set_id)
        if not definition.get("display_name"):
            definition["display_name"] = db_display_name or ""
        # Phase 14 P14-01: description aus der DB-Spalte nachziehen
        if not definition.get("description") and db_description:
            definition["description"] = db_description

        # P14-04: Original für den Rollback tief kopieren, DANN migrieren.
        original = copy.deepcopy(definition)
        try:
            definition = self._apply_schema_migration(definition)
        except MigrationError as e:
            print(f"WARN [ServiceSetRepository] Schema-Migration fuer Set "
                  f"'{set_id}' abgebrochen - Original wird geladen. {e}")
            return original
        return definition

    def _apply_schema_migration(self, definition: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 14 P14-04: Wendet den SchemaMigrator auf alle Instanzen an.

        Iteriert über alle Service-Instanzen des Sets und migriert jede
        Konfiguration gegen ihr Plugin (PluginRegistry). Plugins, die nicht
        (mehr) registriert sind, bleiben unverändert (Skip – ein fehlendes
        Plugin darf das Laden des restlichen Sets nicht brechen).

        Raises:
            MigrationError: bei jedem Fehler der Migrations-Engine – der
            Aufrufer (get_set) führt dann den Rollback auf das Original aus.
        """
        from analytics.features.feature_builder import PluginRegistry
        from analytics.engine.schema_migrator import SchemaMigrator

        services = definition.get("services") or {}
        migrator = SchemaMigrator()
        registry = PluginRegistry()
        for iid, cfg in services.items():
            if not isinstance(cfg, dict):
                continue
            pid = cfg.get("plugin_id") or iid
            try:
                plugin = registry.get(pid)
            except KeyError:
                # Plugin nicht (mehr) registriert → Instanz unverändert lassen.
                continue
            services[iid] = migrator.migrate_instance_config(cfg, plugin)
        definition["services"] = services
        return definition

    def list_sets(self) -> List[Dict[str, Any]]:
        """Liefert ALLE gespeicherten Service-Sets (volle Definitionen).

        Quelle für die Set-Dropdowns im Prop-/Service-Fenster. Deterministisch
        nach updated_at sortiert (älteste zuerst, analog load_all_instances).
        """
        con = self._get_connection()
        rows = con.execute(
            "SELECT set_id, display_name, definition, description FROM service_sets ORDER BY updated_at ASC"
        ).fetchall()
        sets: List[Dict[str, Any]] = []
        for db_set_id, db_display_name, definition_json, db_description in rows:
            definition = _parse_json_field(definition_json) or {}
            definition["set_id"] = str(db_set_id)
            if not definition.get("display_name"):
                definition["display_name"] = db_display_name or ""
            # Phase 14 P14-01: description aus der DB-Spalte nachziehen
            if not definition.get("description") and db_description:
                definition["description"] = db_description
            sets.append(definition)
        return sets

    def delete_set(self, set_id: str, soft_delete: bool = True) -> bool:
        """Entfernt ein Set. Liefert True, wenn eine Zeile existierte.

        Phase 14 P14-05 (Soft-Delete): Bei soft_delete=True wird das Set in
        die Papierkorb-Tabelle `service_sets_trash` verschoben (mit
        deleted_at-Zeitstempel) statt hart gelöscht. Die Wiederherstellung
        erfolgt über restore_set_from_trash(). Bei soft_delete=False wird das
        Set ENDGÜLTIG entfernt (z. B. für die Papierkorb-Bereinigung).
        """
        con = self._get_connection()
        res = con.execute(
            "SELECT set_id, display_name, definition FROM service_sets WHERE set_id = ?",
            [set_id],
        ).fetchone()
        if not res:
            return False
        db_set_id, db_display_name, definition_json = res
        if soft_delete:
            # Kopie nach service_sets_trash (Upsert – erneutes Löschen eines
            # bereits im Papierkorb liegenden Sets aktualisiert den Zeitstempel).
            con.execute("""
                INSERT INTO service_sets_trash (set_id, display_name, definition, deleted_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (set_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    definition   = EXCLUDED.definition,
                    deleted_at   = EXCLUDED.deleted_at
            """, [db_set_id, db_display_name or "", definition_json])
        con.execute("DELETE FROM service_sets WHERE set_id = ?", [set_id])
        return True

    def list_trash(self) -> List[Dict[str, Any]]:
        """Liefert ALLE im Papierkorb befindlichen Service-Sets.

        Analog list_sets() – deterministisch nach deleted_at sortiert
        (älteste zuerst). Enthält zusätzlich das Feld 'deleted_at' und ist
        die Quelle für den Papierkorb-Dialog im Service-Fenster.
        """
        con = self._get_connection()
        rows = con.execute(
            "SELECT set_id, display_name, definition, deleted_at "
            "FROM service_sets_trash ORDER BY deleted_at ASC"
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for db_set_id, db_display_name, definition_json, db_deleted_at in rows:
            definition = _parse_json_field(definition_json) or {}
            definition["set_id"] = str(db_set_id)
            if not definition.get("display_name"):
                definition["display_name"] = db_display_name or ""
            definition["deleted_at"] = db_deleted_at
            items.append(definition)
        return items

    def restore_set_from_trash(self, set_id: str) -> bool:
        """Stellt ein Set aus dem Papierkorb wieder her (Trash → service_sets).

        Liefert True, wenn ein Trash-Eintrag existierte und wiederhergestellt
        wurde. Existiert die set_id in service_sets bereits (z. B. weil sie
        zwischenzeitlich neu angelegt wurde), wird sie überschrieben.
        """
        con = self._get_connection()
        res = con.execute(
            "SELECT set_id, display_name, definition FROM service_sets_trash WHERE set_id = ?",
            [set_id],
        ).fetchone()
        if not res:
            return False
        db_set_id, db_display_name, definition_json = res
        definition = _parse_json_field(definition_json) or {}
        definition["set_id"] = str(db_set_id)
        if not definition.get("display_name"):
            definition["display_name"] = db_display_name or ""
        description = definition.get("description")
        description = str(description).strip() if description is not None else None
        # Wiederherstellen (Upsert auf service_sets)
        con.execute("""
            INSERT INTO service_sets (set_id, display_name, definition, description, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (set_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                definition   = EXCLUDED.definition,
                description  = EXCLUDED.description,
                updated_at   = EXCLUDED.updated_at
        """, [db_set_id, definition.get("display_name") or "", json.dumps(definition), description])
        con.execute("DELETE FROM service_sets_trash WHERE set_id = ?", [set_id])
        return True

    def purge_trash_set(self, set_id: str) -> bool:
        """Entfernt ein Set ENDGÜLTIG aus dem Papierkorb (hartes Löschen).

        Liefert True, wenn ein Trash-Eintrag existierte und entfernt wurde.
        Dieser Vorgang ist nicht umkehrbar – die UI verlangt daher eine
        doppelte Sicherheitsabfrage.
        """
        con = self._get_connection()
        res = con.execute(
            "SELECT COUNT(*) FROM service_sets_trash WHERE set_id = ?", [set_id]
        ).fetchone()
        exists = bool(res and res[0] and res[0] > 0)
        if exists:
            con.execute("DELETE FROM service_sets_trash WHERE set_id = ?", [set_id])
        return exists

    def purge_trash(self) -> int:
        """Leert den Papierkorb vollständig (Endgültige Bereinigung der DB).

        Liefert die Anzahl endgültig entfernter Sets. Nicht umkehrbar – die
        UI verlangt daher eine doppelte Sicherheitsabfrage.
        """
        con = self._get_connection()
        res = con.execute("SELECT COUNT(*) FROM service_sets_trash").fetchone()
        count = int(res[0]) if res and res[0] else 0
        if count:
            con.execute("DELETE FROM service_sets_trash")
        return count

```

--------------------------------------------------

### DATEI: serviceui/__init__.py
```py
# serviceui/__init__.py
"""
Service-UI-Paket (Phase 15, Kapitel 15.1 – U15-D1 + 15.02).

Modularisierte Service-UI: Die gewachsene service_win.py wurde in den
Unterordner serviceui/ verschoben und in SRP-Module zerlegt:

  * service_set_utils.py   – _available_plugin_ids, _sets_using_plugin
  * run_worker.py          – ServiceRunWorker (QThread, gezielter Kontextmenue-
                             Run mit FeatureStore-Persistenz, 05.08.2026)
  * param_columns.py       – ServiceParamColumnsMixin (Parameter-Column-Builder)
  * trash_dialog.py        – ServiceSetTrashDialog (Papierkorb-Dialog)
  * service_win.py         – ServiceWindow (Hauptfenster, re-exportiert API)

Phase 15.02 (Master-Tree & generischer ServiceSelector):
  * master_tree.py             – 2-Spalten MasterTree (Hierarchie + Badges,
                                 Ausfuehrungsdatum, Kontextmenue-Run-Aktionen)
  * service_selector_widget.py – ServiceSelectorWidget (SELECT_ONLY/FULL_EDIT)
  * new_set_dialog.py          – NewServiceSetDialog (Set + Indikator)
  * analytics/engine/service_selector_model.py – lesendes Datenmodell

Die fruehere Aktions-Toolbar (serviceui/toolbar.py, ServiceToolbar) ist seit
05.08.2026 komplett entfernt – alle Struktur-Aktionen laufen ueber das
MasterTree-Kontextmenue. Die Datei ist unter .backup_service_toolbar/
archiviert (gitignored, Konvention wie .backup_grid_liquidity und
.backup_parameter_panel).
"""

from serviceui.service_win import (
    ServiceWindow,
    _available_plugin_ids,
    _sets_using_plugin,
    BASE_DIR,
)

# 05.08.2026: Gezielter Run-Worker (MasterTree-Kontextmenue 'Service(s)
# ausführen') – FeatureStore-Persistenz + EventBus-Sync.
from serviceui.run_worker import ServiceRunWorker

# Phase 15.02: Wiederverwendbare Sub-Widgets
from serviceui.master_tree import MasterTree
from serviceui.status_panel import StatusPanel
from serviceui.service_selector_widget import ServiceSelectorWidget
from serviceui.new_set_dialog import NewServiceSetDialog

__all__ = [
    "ServiceWindow",
    "ServiceRunWorker",
    "_available_plugin_ids",
    "_sets_using_plugin",
    "BASE_DIR",
    # Phase 15.02
    "MasterTree",
    "StatusPanel",
    "ServiceSelectorWidget",
    "NewServiceSetDialog",
]

```

--------------------------------------------------

### DATEI: serviceui/common_widgets.py
```py
# serviceui/common_widgets.py
"""
Service-UI: Gemeinsame Widgets (Phase 21.01b, 11.08.2026).

Enthaelt:
  * TfStatusBadgeBar – kleine Pill-Badges je Timeframe mit Status-Info
    (Daten vorhanden / laeuft / Fehler) fuer den MasterTree/ServicePicker
    und das ServiceWindow. Reines Anzeige-Widget ohne Geschaeftslogik
    (SRP): Der Orchestrator versorgt es ueber `update_status`, `set_running`
    und `set_error` mit Werten; die Daten selbst kommen aus
    FeatureStoreReader.fetch_service_tf_status() (21.01b Schritt 1).
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

# ---------------------------------------------------------------------------
# Farb-Schema (dunkles UI; konsistent mit den uebrigen Service-Panels)
# ---------------------------------------------------------------------------
_STYLE_IDLE = ("background-color: #3a3a46; color: #cfd2dc; "
               "border-radius: 3px; border: 1px solid #4a4a58;")
_STYLE_RUNNING = ("background-color: #2f6fb2; color: #ffffff; "
                  "border-radius: 3px; border: 1px solid #5a9bdc;")
_STYLE_ERROR = ("background-color: #b04343; color: #ffffff; "
                "border-radius: 3px; border: 1px solid #d07070;")
_STYLE_HINT = ("background-color: #2c3e2c; color: #9fcf9f; "
               "border-radius: 3px; border: 1px solid #4a7a4a;")

# 13.08.2026 (Punkt 3, F3): Kanonische TF-Reihenfolge (fein -> grob) fuer
# die Pill-Badges. Die Reader-Rueckgabe (fetch_service_tf_status) ist seit
# 13.08.2026 bereits kanonisch sortiert; diese Sortierung sichert das
# Widget zusaetzlich DEFENSIV gegen unsortierte Alt-Daten/Test-Aufrufer ab.
_TF_CANONICAL_ORDER = [
    "M1", "M2", "M5", "M10", "M15", "M30",
    "H1", "H4", "D1", "W1", "MN1",
]


def _sort_tfs_canonical(tfs: list) -> list:
    """Kanonische TF-Reihenfolge (unbekannte TFs am Ende, alphabetisch)."""
    order = {tf: i for i, tf in enumerate(_TF_CANONICAL_ORDER)}
    return sorted(
        (str(t) for t in (tfs or [])
        if t is not None and str(t).strip()),
        key=lambda tf: (order.get(str(tf).upper(), 10 ** 6), str(tf)),
    )


class TfStatusBadgeBar(QWidget):
    """Pill-Badges je Timeframe eines Services (21.01b, Schritt 2).

    Jedes Badge ist ein kleines QLabel (Default ~28x16 px, 9 pt fett,
    Eckenradius 3 px) mit dem Timeframe-Kuerzel. Der Tooltip zeigt die
    Detail-Info aus dem feature_store:
        'M1: 99.000 Eintraege\nZuletzt: 11.08.26 20:15'

    Zustands-Wechsel:
        update_status(map)  – Badges aus dem DB-Status (TF -> {count, last_run})
                              neu aufbauen/aktualisieren (ohne TF-Eintrag
                              bleibt nur das Kuerzel sichtbar).
        set_running(tf|None)– TF waehrend eines Runs blau hervorheben.
        set_error(tf)       – TF nach einem Fehler rot markieren.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._labels: Dict[str, QLabel] = {}
        self._status: Dict[str, Dict[str, Any]] = {}
        self._running: Optional[str] = None
        self._errors: set = set()

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(2)
        self._lay.addStretch(1)  # Badges links buendig, Rest dehnbar

    # ------------------------------------------------------------------
    # Datenversorgung
    # ------------------------------------------------------------------
    def update_status(self, status_map: Dict[str, Dict[str, Any]]) -> None:
        """Baut die TF-Badges aus `fetch_service_tf_status()` auf.

        `status_map`: TF (upper) -> {'count': int, 'last_run': str}. TFs,
        die in der DB existieren, bekommen einen Tooltip; TFs, die
        uebergeben werden, aber nicht in `status_map` stehen, werden mit
        leerem Tooltip (keine Daten) angezeigt.
        """
        self._status = dict(status_map or {})
        # Sichtbare TFs: DB-TFs + aktuell laufende/fehlerhafte TFs (auch
        # ohne DB-Eintrag, z.B. beim ERSTEN Run eines noch leeren Stores).
        known_tfs: list = list(self._status.keys())
        if self._running and self._running not in known_tfs:
            known_tfs.append(self._running)
        for extra in self._errors:
            if extra not in known_tfs:
                known_tfs.append(extra)
        # 13.08.2026 (Punkt 3, F3): Kanonische TF-Reihenfolge (fein -> grob).
        self._rebuild(_sort_tfs_canonical(known_tfs))

    def _rebuild(self, tfs: list) -> None:
        """Erzeugt/entfernt Badge-Labels so, dass `tfs` angezeigt werden."""
        # 13.08.2026 (Punkt 3, F3): Defensive kanonische Sortierung - das
        # Widget rendert TFs unabhaengig von der Aufrufer-Reihenfolge
        # korrekt (fein -> grob).
        tfs = _sort_tfs_canonical(tfs)
        wanted = set(tfs)
        # Entfernen nicht mehr benoetigter Badges
        for tf in list(self._labels.keys()):
            if tf not in wanted:
                lbl = self._labels.pop(tf)
                self._lay.removeWidget(lbl)
                lbl.deleteLater()
        # Fehlende Badges anlegen (vor dem Stretch)
        idx = self._lay.count() - 1  # Stretch ist das letzte Element
        if idx < 0:
            idx = 0
        for tf in tfs:
            if tf in self._labels:
                continue
            lbl = QLabel(str(tf), self)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(28, 16)
            font = lbl.font()
            font.setPointSize(9)
            font.setBold(True)
            lbl.setFont(font)
            self._lay.insertWidget(idx, lbl)
            self._labels[tf] = lbl
            idx += 1
        self._refresh_styles()

    # ------------------------------------------------------------------
    # Zustands-Wechsel
    # ------------------------------------------------------------------
    def set_running(self, tf: Optional[str]) -> None:
        """Hebt den laufenden Timeframe blau hervor (None = nichts laeuft)."""
        self._running = tf
        self._refresh_styles()

    def set_error(self, tf: str) -> None:
        """Markiert einen Timeframe als fehlgeschlagen (rot)."""
        self._errors.add(tf)
        self._refresh_styles()

    def clear_error(self, tf: str) -> None:
        """Entfernt die Fehler-Markierung eines Timeframes."""
        self._errors.discard(tf)
        self._refresh_styles()

    def clear(self) -> None:
        """Leert alle Badges und Zustaende."""
        self._status = {}
        self._running = None
        self._errors.clear()
        self._rebuild([])

    # ------------------------------------------------------------------
    # Interna
    # ------------------------------------------------------------------
    def _refresh_styles(self) -> None:
        """Wendet die aktuelle QSS-Farbe je Badge an und setzt Tooltips."""
        for tf, lbl in self._labels.items():
            if tf == self._running:
                lbl.setStyleSheet(_STYLE_RUNNING)
            elif tf in self._errors:
                lbl.setStyleSheet(_STYLE_ERROR)
            elif tf in self._status:
                lbl.setStyleSheet(_STYLE_IDLE)
            else:
                lbl.setStyleSheet(_STYLE_HINT)
            info = self._status.get(tf)
            if info and info.get("count"):
                count = int(info.get("count") or 0)
                last_run = str(info.get("last_run") or "")
                tip = (f"{tf}: {count:,} Eintraege".replace(",", ".")
                       if count else f"{tf}: keine Eintraege")
                if last_run:
                    tip += f"\nZuletzt: {last_run}"
                lbl.setToolTip(tip)
            else:
                lbl.setToolTip(f"{tf}: keine Daten")

```

--------------------------------------------------

### DATEI: serviceui/master_tree.py
```py
# serviceui/master_tree.py
"""
Service-UI: 2-Spalten-MasterTree (Phase 15 15.02).

Hierarchische Darstellung der Service-Landschaft:

  * Spalte 0: Knoten – 📁 Service-Sets (mit ihren Service-Instanzen),
              📦 Alle verfuegbaren Services (kategorisierte Ordner).
              Die Spalte ist Stretch und fuellt die gesamte Breite bis zur
              Status-Spalte. Untereintraege sind per setIndentation()
              eingerueckt (Bugfix 04.08.2026); die Top-Level-Knoten starten
              ganz links (rootIsDecorated=False, keine Branch-Einrueckung
              auf Ebene 0). Jeder Knoten mit Kindern (potentiell aufklappbar)
              traegt ein Auf-/Zuklapp-Symbol vor dem Namen ('>' wenn
              eingeklappt, '⌄' wenn ausgeklappt); ein einfacher Mausklick auf
              einen aufklappbaren Knoten togglet auf/zu (Doppelklick ist
              deaktiviert). Die Top-Level-Knoten beginnen ganz links an der
              Linie der umschliessenden Box (kein Icon/Spacer auf Ebene 0).
              05.08.2026 (Ausfuehrungsdatum): An den Namen jedes Service-
              Knotens haengt das Datum der letzten Ausfuehrung in Klammern:
              'prox_1 (05.08.26)' (DD.MM.JJ aus MAX(created_at) des
              feature_store je feature_id) – ohne Eintrag '(--.--.--)'.
              Gilt seit 05.08.2026 (Punkt 4) auch fuer Standalone-Services
              und Plugin-Zeilen ('srv_proximity (02.08.26)').
  * Spalte 1: Schmale Status-Spalte ganz RECHTS (Fixed-Spalte, fest am
              rechten Rand verankert) – pro Zeile ein echter Info-Button
              (QPushButton "ℹ", Icon-Breite ~20 px). Badge-TEXTE werden
              NICHT mehr angezeigt (Bugfix 05.08.2026: der Button ersetzt
              die frueheren Text-Badges bzw. das gekuerzte ASCII-'i').
              Der Button-Tooltip zeigt den Indikator-Namen ('aktiv
              <Indikator>' wenn der Indikator im Chart aktiv ist, sonst
              'im <Indikator>' – Bugfix 05.08.2026: Aktiv-Pruefung ueber
              die indicator_id des zugehoerigen Indikators). Gehoert eine
              Zeile (Service/Plugin/Set) einem Indikator, ist der Button
              gelb (#FFD700) eingefaerbt, sonst neutral. Klick oeffnet den
              Beschreibungs-Dialog (Signal `info_requested`).

Der Baum wird ausschliesslich aus dem `ServiceSelectorModel` befuellt
(lesendes Datenmodell, Invariante 4: kein SQL in UI) und aktualisiert sich
automatisch ueber `data_changed`/EventBus. Der `ServiceSelectorWidget` nutzt
den MasterTree im Modus `FULL_EDIT` (seit 05.08.2026 ohne Aktions-Toolbar –
volle vertikale Hoehe, alle Aktionen via Kontextmenue).

Signale:
  * selection_changed(set_id, service_id) – bei jeder Baum-Selektion
    (set_id/service_id koennen leer sein, wenn nichts Konkretes gewaehlt ist).
  * info_requested(set_id, service_id, plugin_id) – Klick auf den Info-Button
    (Spalte 1). Je nach Zeilentyp sind nur die passenden Felder gefuellt:
      Service-Zeile: set_id + service_id + plugin_id
      Set-Zeile:      set_id (service_id/plugin_id leer)
      Plugin-Zeile:   plugin_id (set_id/service_id leer)
  * Kontextmenue (Bugfix 05.08.2026, strikt entkoppelt – der Orchestrator
    verknuepft die Aktionen mit seinen Handlern):
      create_set_requested()                          – 'Neues Set anlegen'
      rename_set_requested(set_id)                    – 'Set umbenennen'
      add_set_service_requested(set_id)               – 'Service hinzufuegen'
      delete_set_requested(set_id)                    – 'Set loeschen (Papierkorb)'
      move_service_requested(set_id, service_id, delta) – Order ▲ (-1) / ▼ (+1)
      remove_service_requested(set_id, service_id)    – 'Service entfernen'
      run_service_requested(set_id, instance_id)      – '▶️ Diesen Service ausführen'
      run_set_requested(set_id)                        – '▶️ Alle Services ausführen'
      open_trash_requested()                           – '🗑️ Papierkorb öffnen...'
    (Service-Info nutzt das bestehende `info_requested`-Signal.)
"""

from typing import Any, Dict, List, Optional

import json

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QHeaderView, QInputDialog, QMenu, QPushButton, QTreeWidget,
    QTreeWidgetItem,
)

# 20.04 (Q2/Q4): Deterministischer Parameter-Hash. Runde 13b
# (Bugfix Dropdown-NoData): on-the-fly-Fallback in _build_set_item fuer
# Set-Instanzen, deren Set-Definition beim regularen Hinzufuegen keinen
# instance_hash persistiert hat (Alt-Bestand).
from analytics.engine.service_models import generate_instance_hash

# 18.01.03 (Dynamic Tree Management): MIME-Typ fuer den internen
# Kategorie-Drag & Drop. Die MIME-Daten kodieren den gezogenen Knoten als
# JSON: {"node_type": "set|plugin|category", "group": "sets|plugins",
#         "id": <set_id|plugin_id|category-path>, "path": <Quell-Pfad>}.
MIME_CATEGORY_MOVE = "application/x-pytrader-category-move"

# P15-Bugfix: shiboken6.isValid() schuetzt vor dem Zugriff auf bereits
# C++-seitig zerstoerte Items (QTreeWidget.clear() nach data_changed bei
# wildem Klicken) – verhindert Access Violation (0xC0000005).
try:
    from shiboken6 import isValid
except ImportError:  # pragma: no cover
    def isValid(obj) -> bool:  # type: ignore
        return obj is not None

# UserRole-Kennungen fuer die Knotentypen (Deterministische Auswertung)
ROLE_NODE_TYPE = Qt.UserRole
ROLE_SET_ID = Qt.UserRole + 1
ROLE_INSTANCE_ID = Qt.UserRole + 2
ROLE_PLUGIN_ID = Qt.UserRole + 3
# 20.04 (Q6/Q7): Zusaetzliche Rollen fuer Clone-Knoten (TYPE_CLONE) und
# die Archiv-Kennzeichnung. ROLE_INSTANCE_HASH traegt den 8-stelligen
# Parameter-Hash eines Clones (generate_instance_hash); ROLE_ARCHIVED=True
# markiert archivierte Knoten (non-checkable, Archiv-Safety).
ROLE_INSTANCE_HASH = Qt.UserRole + 4
ROLE_ARCHIVED = Qt.UserRole + 5
# 10.08.2026 (Bugfix): ROLE_PRESET_NAME traegt den Anzeigenamen eines
# Clone-/Preset-Knotens (fuer den 'Variante umbenennen'-Dialog, ohne
# DB-Lookup im MasterTree).
ROLE_PRESET_NAME = Qt.UserRole + 6

# 15.03-E (Multi-Select): Klickzone der Checkbox-Indikatoren in Spalte 0.
# Klicks links dieser Zone (innerhalb der Item-Zeile) werden dem Qt-Default
# ueberlassen, damit die Checkbox togglet (itemChanged feuert); Klicks
# rechts davon togglen weiterhin das Auf-/Zuklappen (mousePressEvent).
CHECKBOX_ZONE_WIDTH = 24

#: Knotentypen
TYPE_GROUP = "group"
TYPE_SET = "set"
TYPE_SERVICE = "service"
TYPE_PLUGIN = "plugin"
# 20.04 (Q7): Clone-/Preset-Knoten (Kind eines Plugin-Parents in der
# Services-Gruppe). Traegt ROLE_PLUGIN_ID (plugin_id des Parents) und
# ROLE_INSTANCE_HASH; aktive Clones sind anhakbar, archivierte nicht.
TYPE_CLONE = "clone"
# 16.08 (K3): Kategorie-Ordner-Knoten (Dynamic Category Trees). Nicht
# auswaehlbar, expandierbar; traegt KEINEN Info-Button (K5), keine Badges
# und ist im Checkbox-Modus nicht anhakbar (K4).
TYPE_CATEGORY = "category"

# Bugfix 2.1 (04.08.2026, aktualisiert): Lange Relationstexte in der Badge-
# Spalte (z. B. "📌 im Ind_FixedGridProximity | ⚪ inaktiv in ...") werden auf
# das Info-Zeichen 'i' gekuerzt – der Indikator-Name steht im Tooltip der
# Spalte 1 (keine extrem breiten Spalten im MasterTree).
MAX_BADGE_CELL_CHARS = 24
# Bugfix 04.08.2026 (Punkt 5): ASCII 'i' statt Unicode '🛈' (U+1F5D8) – das
# Emoji rendert in den Qt-Fonts unter Windows nicht zuverlaessig (tofu-Box).
# WICHTIG (05.08.2026): Der Text-'i' ist durch den echten Info-Button ersetzt;
# die Konstante bleibt nur als Test-Referenz erhalten (Historik).
BADGE_TRUNCATE_ICON = "i"

# Bugfix 20.03.01 (09.08.2026): Das Unicode-Zeichen "ℹ" (U+2139) rendert
# unter Windows in Qt bei fehlendem Font als Tofu-Box – der Info-Button
# war nicht mehr erkennbar (User-Meldung 'i-Button im Tree geht nicht
# mehr'; vgl. Bugfix 04.08.2026, Punkt 5: Unicode-Badge '🛈' ebenfalls
# durch ASCII 'i' ersetzt). Daher wieder ASCII 'i' als Button-Beschriftung.
# Der QPushButton (Spalte 1) ersetzt seit 05.08.2026 das Badge-Text-'i';
# die Status-Spalte wird auf die Button-Breite verkleinert (Spalte 0 ist
# Stretch und bekommt den freien Platz). Der Button erscheint auf ALLEN
# Service-/Plugin-/Set-Zeilen; gehoert die Zeile einem Indikator, ist er
# gelb (#FFD700) und traegt den Tooltip 'aktiv/im <Indikator>'
# (Namenslogik unveraendert aus _apply_badge).
INFO_BUTTON_TEXT = "i"
INFO_BUTTON_SIZE = 20          # ~Icon-Breite
INFO_BUTTON_WIDTH = 24         # Spaltenbreite (Status-Spalte)
INFO_BUTTON_COLOR_INDICATOR = "#FFD700"   # gelb bei Indikator-Zugehoerigkeit
INFO_BUTTON_COLOR_NEUTRAL = "#666666"     # neutral sonst

# Bugfix 3.0 (04.08.2026): Status-Spalte (Spalte 1) ist eine schmale
# Festbreiten-Spalte ganz rechts. Die Breite richtet sich seit 05.08.2026
# nach dem Info-Button (INFO_BUTTON_WIDTH); BADGE_COLUMN_WIDTH bleibt als
# Test-Referenz fuer die historische Text-Badge-Breite erhalten.
BADGE_COLUMN_WIDTH = 36

# Bugfix 3.1 (04.08.2026, aktualisiert): Einrueckung + '>'/'⌄'-Marker.
# Untereintraege sind per setIndentation(LEVEL_INDENT) eingerueckt; die
# Auf-/Zuklapp-Markierung uebernimmt das Symbol vor dem Namen ('>' bei
# eingeklappt, '⌄' bei ausgeklappt, siehe _expandable_label). drawBranches
# bleibt als bewusst leerer Override erhalten, damit Qt KEINE nativen
# Branch-Dreiecke zeichnet. Ein einfacher Mausklick auf die GESAMTE Zeile
# eines aufklappbaren Knotens togglet (Punkt 4) – der fruehere schmale
# Klickstreifen entfaellt. BRANCH_ZONE_WIDTH bleibt nur als Test-Referenz
# erhalten (historische Symbol-Klickzone).
BRANCH_ZONE_WIDTH = 16

# Bugfix (04.08.2026): Hierarchie-Einrueckung in Pixeln je Ebene (Qt-Default
# 20px) – Untereintraege (Service-Instanzen unter Sets, Sets unter Gruppen)
# werden dadurch sichtbar eingerueckt statt buendig angeordnet.
LEVEL_INDENT = 20


def _expandable_label(name: str, has_children: bool,
                      is_expanded: bool) -> str:
    """Auf-/Zuklapp-Praefix fuer Knoten mit Untereintraegen (04.08.2026).

    An jedem Knoten, der Kinder enthaelt (potentiell aufklappbar), steht ein
    Symbol vor dem Namen: '>' wenn eingeklappt, '⌄' wenn ausgeklappt.
    Blatt-Knoten (ohne Kinder) erhalten keinen Praefix.
    """
    if not has_children:
        return name
    return ("⌄ " if is_expanded else "> ") + name


class MasterTree(QTreeWidget):
    """2-Spalten-TreeWidget fuer die hierarchische Service-Darstellung."""

    selection_changed = Signal(str, str)  # set_id, service_id
    # Bugfix 06.08.2026 (Bugfix-Runde 3, Punkte 1-7): Klick-Scope der
    # geklickten Zeile (node_type, set_id, service_id, plugin_id). Wird aus
    # `mousePressEvent` bei JEDEM Mausklick auf eine gueltige Zeile emittiert
    # (auch Checkbox-Zone / Expand-Toggle, unabhaengig von einer Selektion).
    # Der ServiceSelectorDialog zeigt daraus die Parameter im Read-Only-Panel
    # (analog service_win: Set/Service-in-Set -> alle Set-Services; Plugin-
    # Zeile -> nur dieser Service; sonst leer).
    selection_details = Signal(str, str, str, str)
    # Bugfix 05.08.2026: Klick auf den Info-Button (Spalte 1).
    # Argumente (set_id, service_id, plugin_id) – je nach Zeilentyp gefuellt.
    info_requested = Signal(str, str, str)
    # Bugfix 05.08.2026: Kontextmenue (Rechtsklick) – entkoppelt; der
    # Orchestrator (ServiceWindow) verknuepft die Aktionen mit seinen Handlern.
    create_set_requested = Signal()
    rename_set_requested = Signal(str)          # set_id
    add_set_service_requested = Signal(str)     # set_id
    delete_set_requested = Signal(str)          # set_id
    move_service_requested = Signal(str, str, int)  # set_id, service_id, delta
    remove_service_requested = Signal(str, str)     # set_id, service_id
    # Bugfix 05.08.2026: Kontextmenue 'Papierkorb löschen' – endgueltig
    # leeren (Orchestrator fuehrt die doppelte Sicherheitsabfrage aus).
    purge_trash_requested = Signal()
    # Phase 15: Kontextmenue '🗑️ Papierkorb öffnen...' (Haupt-Gruppe
    # 📁 Service-Sets) – oeffnet den Papierkorb-Dialog. Der Orchestrator
    # (ServiceWindow) ruft dieselbe Methode auf wie der Papierkorb-Button
    # in der Aktionsleiste (show_trash_dialog()).
    open_trash_requested = Signal()
    # 15.03-E (Multi-Select): Checkbox-Zustand wurde geaendert (SELECT_MULTI).
    # Der ServiceSelectorDialog lauscht darauf und baut sein rechter
    # Read-Only-Parameter-Panel neu auf.
    checked_changed = Signal()
    # 05.08.2026 (Ausfuehrungsdatum & Kontextmenue-Ausfuehrung):
    #   run_service_requested(set_id, instance_id) – '▶️ Diesen Service ausfuehren'
    #   run_set_requested(set_id)                   – '▶️ Alle Services ausfuehren'
    # Der Orchestrator (ServiceWindow) startet dafuer den gezielten
    # ServiceRunWorker (kein globaler Massen-Scan) und zeigt zuvor den
    # Bestaetigungsdialog (Set/Service + Symbol/Timeframe).
    run_service_requested = Signal(str, str)
    run_set_requested = Signal(str)
    # 17.01.02 (Bugfix-Runde): Run-/Info-Aktionen fuer die Services-Gruppe.
    #   run_plugin_requested(plugin_id, instance_hash) – '▶️ Diesen Service
    #      ausführen' (Einzel-Plugin-Zeile, ohne Set). 11.08.2026 (Bugfixing):
    #      Clone-Zeilen liefern den instance_hash der Variante mit (NUR diese
    #      Variante laeuft mit ihren Parametern); Plugin-Zeilen senden '' (mit
    #      Presets laufen alle aktiven Varianten, sonst Basis-Parameter).
    #   run_category_requested(group, path) – '▶️ Alle Services ausführen'
    #                                      (Kategorie-Ordner, rekursiv; path
    #                                      z.B. 'Swing Points/Geometrie';
    #                                      group = 'sets' | 'plugins',
    #                                      18.01.03: Sets-Ordner moeglich)
    #   category_info_requested(group, path) – Info-Button auf Kategorie-Ordnern
    run_plugin_requested = Signal(str, str)
    run_category_requested = Signal(str, str)
    category_info_requested = Signal(str, str)
    # 18.01.03 (Dynamic Tree Management): Ordner-CRUD & Kategorie-Drag&Drop.
    #   create_folder_requested(group, full_path) – 'Neuer Ordner' (der
    #       MasterTree zeigt den Namensdialog; der Orchestrator PERSISTIERT
    #       den Ordner ueber global_settings (tree_folders_<group>,
    #       service_set_utils.create_empty_folder) – E3-revidiert
    #       08.08.2026: Leere Ordner verschwinden NICHT beim Refresh).
    #   delete_folder_requested(group, path) – 'Ordner löschen' (manuelle
    #       Loeschung; der Orchestrator entfernt den Eintrag ueber
    #       service_set_utils.delete_empty_folder).
    #   rename_folder_requested(group, old_path, new_path) – 'Umbenennen'
    #       (String-Replace aller Kinder + persistierter Leere-Ordner im
    #       Orchestrator).
    #   folder_item_moved(node_type, item_id, new_path) – Drop eines Sets
    #       (TYPE_SET) bzw. Plugins (TYPE_PLUGIN) in einen Ziel-Ordner.
    #   folder_moved(group, old_path, new_path) – Drop eines Ordners auf
    #       einen anderen Ordner (verschiebt alle Kinder rekursiv).
    create_folder_requested = Signal(str, str)
    delete_folder_requested = Signal(str, str)
    rename_folder_requested = Signal(str, str, str)
    folder_item_moved = Signal(str, str, str)
    folder_moved = Signal(str, str, str)
    # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im Kontextmenue (Service-/Clone-
    # Zeilen). Der Orchestrator (ServiceWindow) verknuepft die Aktionen mit
    # seinen Handlern:
    #   data_only_purge_requested(set_id, service_id, plugin_id,
    #                             instance_hash)
    #       – 'Data Only Löschen': NUR die berechneten Feature-Daten der
    #         Instanz purgen (FeatureBuilder.purge_instance_data, Q5). Bei
    #         Clone-Zeilen sind set_id/service_id leer (plugin_id + Hash).
    #   delete_complete_requested(set_id, service_id, plugin_id,
    #                             instance_hash)
    #       – 'Vollständig Löschen': Instanz/Preset + Feature-Daten entfernen
    #         (2-stufige Sicherheitsabfrage im Orchestrator).
    #   doc_log_requested(set_id, service_id, plugin_id, instance_hash)
    #       – 'Doc Log bearbeiten': Negativ-Wissen editieren
    #         (ServiceInstanceConfig.doc_log bzw. indicator_presets.doc_log
    #         bei Clones).
    #   duplicate_variant_requested(set_id, service_id, plugin_id,
    #                               instance_hash)
    #       – 'Als Variante duplizieren' (Q8): neue Instanz/Preset-Variante
    #         mit kopierten Parametern (neue instance_id / Preset-Name).
    data_only_purge_requested = Signal(str, str, str, str)
    delete_complete_requested = Signal(str, str, str, str)
    doc_log_requested = Signal(str, str, str, str)
    duplicate_variant_requested = Signal(str, str, str, str)
    # 10.08.2026 (Bugfix): 'Variante umbenennen' (Clone/Preset-Kontextmenue).
    # Der MasterTree fragt den neuen Namen ab (vorbelegt) und emittiert
    # rename_variant_requested(plugin_id, instance_hash, new_name) – der
    # Orchestrator (ServiceWindow / ServiceSelectorDialog) persistiert den
    # Preset-Rename in indicator_presets (indicator_id, preset_name).
    rename_variant_requested = Signal(str, str, str)

    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        self.setColumnCount(2)
        self.setHeaderLabels(["Services", ""])
        header = self.header()
        if header is not None:
            # Bugfix (04.08.2026): Spalte 0 (Services) ist Stretch – sie fuellt
            # die gesamte verfuegbare Breite bis zur Status-Spalte. Spalte 1
            # (Status): schmale Fixed-Spalte, dadurch fest am RECHTEN Rand
            # verankert. WICHTIG: setStretchLastSection(False) – QTreeView
            # setzt den Default auf True, wodurch die letzte Spalte trotz
            # Fixed-Mode auf die Restbreite gedehnt wuerde.
            header.setStretchLastSection(False)
            header.setSectionResizeMode(0, QHeaderView.Stretch)
            header.setSectionResizeMode(1, QHeaderView.Fixed)
            header.resizeSection(1, INFO_BUTTON_WIDTH)
        # Bugfix (04.08.2026): Untereintraege werden per setIndentation()
        # eingerueckt (LEVEL_INDENT px je Ebene). rootIsDecorated=False –
        # die Top-Level-Knoten starten ganz links (keine zusaetzliche
        # Branch-Einrueckung auf Ebene 0); die nativen Branch-Dreiecke
        # unterdrueckt zusaetzlich der bewusst leere drawBranches()-Override.
        # Die Auf-/Zuklapp-Markierung uebernimmt das '>'-Symbol (siehe
        # _expandable_label).
        self.setIndentation(LEVEL_INDENT)
        self.setRootIsDecorated(False)
        # Bugfix 04.08.2026 (Punkt 4): Einfacher Klick togglet auf/zu – der
        # Qt-Default-Doppelklick (expandsOnDoubleClick) ist deaktiviert.
        self.setExpandsOnDoubleClick(False)
        # Bugfix 04.08.2026 (Punkt 2/3): Das Auf-/Zuklapp-Symbol ('>'/'⌄')
        # folgt dem Zustand jedes aufklappbaren Knotens. Die Signale muessen
        # VOR _populate() verbunden sein – _populate() laeuft zwar unter
        # blockSignals, refresht die Top-Level-Labels aber explizit am Ende.
        self.itemExpanded.connect(self._refresh_expand_label)
        self.itemCollapsed.connect(self._refresh_expand_label)

        # Bugfix 05.08.2026: Kontextmenue per Rechtsklick (dynamisch je
        # Knotentyp, siehe _show_context_menu). Die Aktionen sind entkoppelt
        # (Signale) – der Orchestrator verknuepft sie mit seinen Handlern.
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # Phase 15 (Dirty-State): instance_ids mit ungespeicherten Parameter-
        # Aenderungen. Die Sternchen-Markierung ('*' am Service-Knoten) wird
        # bei jedem Baum-Neuaufbau aus diesem Set re-appliziert (set_instance_
        # dirty / clear_dirty_markers halten es aktuell).
        self._dirty_instance_ids: set = set()

        # 15.03-E (Multi-Select): Checkbox-Modus (SELECT_MULTI, nur im
        # ServiceSelectorDialog). _checked_items haelt die angehakten Knoten
        # als (node_type, set_id, key_id)-Tupel – key_id = instance_id bei
        # Services bzw. plugin_id bei Standalone-/Plugin-Zeilen. Der Zustand
        # bleibt ueber data_changed-Baum-Neuaufbauten erhalten (analog zum
        # Dirty-Set); Set-Knoten sind Tri-State und werden IMMER aus ihren
        # Service-Kindern abgeleitet (kein eigener Key).
        self._checkable: bool = False
        self._checked_items: set = set()
        self._updating_checks: bool = False

        # 18.01.03 (Dynamic Tree Management): Interner Kategorie-Drag&Drop.
        # Nur Sets/Plugins/Ordner sind ziehbar (E4 – kein Service-Reorder);
        # der Drop aktualisiert den Kategorie-Pfad ueber die Signale
        # folder_item_moved/folder_moved (Modell/Repositories persistieren).
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.DragDrop)  # type: ignore[attr-defined]
        #: Beim Mausklick gemerktes Item – Quelle eines beginnenden Drags
        #: (mousePressEvent -> startDrag).
        self._drag_source: Optional[QTreeWidgetItem] = None
        # 18.01.03 (Bugfix 08.08.2026): Aufklapp-Zustand ueber Baum-
        # Neuaufbauten hinweg erhalten. Ein Ordner-/Item-Move oder eine
        # Ordner-Erstellung triggert data_changed -> _populate(); der Baum
        # soll dabei NICHT zusammenklappen. Schluessel im RAM:
        #   ("cat", group, kategorie-pfad) fuer Ordner,
        #   ("set", set_id)                 fuer Set-Knoten.
        self._expand_after_rebuild: set = set()

        self._populate()
        self.itemSelectionChanged.connect(self._emit_selection)
        # 15.03-E: Checkbox-Aenderungen (Klick) -> Tri-State + Signal.
        self.itemChanged.connect(self._on_item_changed)
        self.model.data_changed.connect(self._populate)

    # -------------------------------------------------------------------------
    # Befuellung aus dem Modell
    # -------------------------------------------------------------------------

    def _populate(self) -> None:
        """Baut den Baum aus model.build_tree() neu auf (deterministisch)."""
        current = self._safe_current_selection()
        # 18.01.03 (Bugfix 08.08.2026): Expansion-Zustand VOR dem Neuaufbau
        # sichern – der Baum soll nach Ordner-Erstellung/-Verschiebung NICHT
        # zusammenklappen (_collect_expanded_state liest den IST-Baum).
        expanded = self._collect_expanded_state()
        self.blockSignals(True)
        self.clear()
        try:
            for group in self.model.build_tree():
                children = group.get("children", [])
                label = _expandable_label(str(group.get("label", "")),
                                          bool(children), False)
                group_item = QTreeWidgetItem([label])
                group_item.setData(0, ROLE_NODE_TYPE, TYPE_GROUP)
                group_item.setData(0, ROLE_SET_ID, group.get("group", ""))
                group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
                for child in children:
                    item = self._build_child_item(group.get("group"), child)
                    if item is not None:
                        group_item.addChild(item)
                self.addTopLevelItem(group_item)
                group_item.setExpanded(True)
        except Exception as e:
            print(f"WARN [MasterTree] Baum-Aufbau fehlgeschlagen: {e}")
        # 18.01.03 (Bugfix 08.08.2026): Expansion unter blockSignals
        # wiederherstellen (keine Signal-Seiteneffekte; die '>'/'⌄'-Labels
        # refresht der anschliessende Label-Block explizit).
        self._apply_expanded_state(expanded)
        self.blockSignals(False)
        # Bugfix 04.08.2026 (Punkt 2/3): unter blockSignals feuern die
        # itemExpanded/itemCollapsed-Signale nicht – die Labels der
        # Top-Level-Knoten werden hier explizit auf den IST-Zustand gebracht
        # ('⌄' wenn expandiert, '>' wenn zugeklappt).
        try:
            for i in range(self.topLevelItemCount()):
                item = self.topLevelItem(i)
                if item is not None and isValid(item):
                    self._refresh_expand_label(item)
        except (RuntimeError, AttributeError):
            pass
        # Aktuelle Auswahl nach Refresh wiederherstellen (falls noch vorhanden)
        try:
            self._restore_selection(current)
        except Exception as e:
            print(f"WARN [MasterTree] Auswahl-Restore fehlgeschlagen: {e}")
        # Bugfix 05.08.2026: Info-Buttons (Spalte 1) NACH dem vollstaendigen
        # Baum-Aufbau anhaengen – setItemWidget() verlangt, dass das Item
        # bereits Teil des TreeWidgets ist (sonst kein sichtbarer Button).
        self._attach_item_buttons()
        # 15.03-E (Multi-Select): _checked_items mit dem IST-Baum abgleichen
        # (stale Keys geloeschter Services/Plugins entfernen).
        self._sync_checked_from_tree()
        # Phase 15 (Dirty-State): Sternchen-Markierungen ungespeicherter
        # Parameter-Aenderungen nach einem Neuaufbau wieder anwenden
        # (data_changed -> _populate wuerde sie sonst verlieren). Waehrend
        # dessen ist die Checkbox-Verarbeitung gesperrt (die Text-Aenderung
        # wuerde sonst ein spurious checked_changed emittieren).
        self._updating_checks = True
        try:
            for iid in list(getattr(self, "_dirty_instance_ids", set())):
                self._apply_dirty_label(iid, True)
        finally:
            self._updating_checks = False
        # 18.01.03 (E3-revidiert): Leere Ordner kommen jetzt aus dem Modell
        # (build_tree mischt die persistierten tree_folders_<group>-Pfade
        # ein) – ein separater UI-Zustand ist nicht mehr noetig.
        pass
        # Runde 9 (Bug 1): Pending-Haken aus set_checked_feature_ids (wurde
        # auf einem noch leeren Baum aufgerufen, z.B. Picker-Oeffnen vor dem
        # ersten data_changed) jetzt auf den fertigen Baum anwenden. Emittiert
        # KEIN checked_changed (Bug-5-Fix), damit der Restore-Filter nicht
        # ueberschrieben wird.
        pending = getattr(self, "_pending_feature_ids", None)
        if pending is not None:
            pending_hashes = getattr(self, "_pending_instance_hashes", None)
            self._pending_feature_ids = None
            self._pending_instance_hashes = None
            self.set_checked_feature_ids(pending, pending_hashes)

    def _safe_current_selection(self) -> Dict[str, str]:
        """Liess die aktuelle Auswahl defensiv (isValid-Guard gegen zerstoerte
        Items, z.B. nach einem zwischenzeitlichen clear())."""
        try:
            item = self.currentItem()
            if item is None or not isValid(item):
                return {"set_id": "", "service_id": ""}
            node_type = item.data(0, ROLE_NODE_TYPE)
            set_id = str(item.data(0, ROLE_SET_ID) or "")
            if node_type == TYPE_SERVICE:
                return {"set_id": set_id,
                        "service_id": str(item.data(0, ROLE_INSTANCE_ID) or "")}
            if node_type == TYPE_SET:
                return {"set_id": set_id, "service_id": ""}
            return {"set_id": "", "service_id": ""}
        except (RuntimeError, AttributeError):
            return {"set_id": "", "service_id": ""}

    def _build_child_item(self, group: str,
                          child: Dict[str, Any]) -> Optional[QTreeWidgetItem]:
        """Erzeugt das Kind-Item fuer einen Knoten der Gruppe `group`.

        16.08 (K2/K3): Ordner-Knoten (group == GROUP_CATEGORY) werden
        rekursiv aufgebaut; Plugin-Blaetter in Ordnern nutzen weiterhin
        _build_plugin_item (Badge/Ausfuehrungsdatum unveraendert). Die
        Original-Gruppe (standalone/plugins) wird durch die Rekursion
        durchgereicht, damit ROLE_SET_ID der Blaetter stabil bleibt.
        """
        if isinstance(child, dict) and child.get("group") == self.model.GROUP_CATEGORY:
            return self._build_category_item(child, group)
        if group == self.model.GROUP_SETS:
            return self._build_set_item(child)
        # 17.01.01: GROUP_STANDALONE entfaellt ersatzlos – Plugin-Zeilen
        # existieren nur noch in GROUP_PLUGINS (Kategorien-Ordner inklusive).
        if group == self.model.GROUP_PLUGINS:
            return self._build_plugin_item(child, group)
        return None

    def _build_category_item(self, child: Dict[str, Any],
                             group: str) -> QTreeWidgetItem:
        """Erzeugt einen Ordner-Knoten (K3, 16.08).

        Nicht auswaehlbar, expandierbar, '📁 <Name>' im Label (aus dem
        Modell, K2-Format); Kinder rekursiv ueber _build_child_item.
        Ordner tragen KEINEN Info-Button (K5 – _attach_item_buttons
        ueberspringt TYPE_CATEGORY automatisch), keine Badges/Datum (K2)
        und sind im Checkbox-Modus nicht anhakbar (K4 – kein
        ItemIsUserCheckable). Die Selektion liefert fuer Ordner den
        Default-Pfad zurueck (K7).
        """
        label = _expandable_label(str(child.get("label") or "?"),
                                  bool(child.get("children")), False)
        cat_item = QTreeWidgetItem([label, ""])
        cat_item.setData(0, ROLE_NODE_TYPE, TYPE_CATEGORY)
        cat_item.setData(0, ROLE_SET_ID, str(child.get("label") or ""))
        # K3/K4: nicht auswaehlbar UND nicht anhakbar – Qt setzt
        # ItemIsUserCheckable standardmaessig, daher beide Flags entfernen.
        cat_item.setFlags(cat_item.flags()
                          & ~(Qt.ItemIsSelectable | Qt.ItemIsUserCheckable))
        for sub in child.get("children") or []:
            item = self._build_child_item(group, sub)
            if item is not None:
                cat_item.addChild(item)
        return cat_item

    def _build_set_item(self, child: Dict[str, Any]) -> QTreeWidgetItem:
        services = child.get("services", [])
        name = _expandable_label(str(child.get("display_name") or "Unbenannt"),
                                 bool(services), False)
        set_item = QTreeWidgetItem([name, ""])
        set_item.setData(0, ROLE_NODE_TYPE, TYPE_SET)
        set_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
        set_item.setToolTip(0, f"Service-Set: {child.get('set_id') or '?'}")
        # 20.04 (Q6): Archivierte Sets (is_archived=True) sind non-checkable
        # (Archive Safety) – sie liegen im '📁 Archiv'-Ordner der Sets-Gruppe.
        archived_set = bool(child.get("archived"))
        if archived_set:
            set_item.setData(0, ROLE_ARCHIVED, True)
        # 15.03-E (Multi-Select): Set-Knoten anhakbar – der Tri-State wird
        # NACH dem Anhaengen der Service-Kinder aus deren Zustaenden
        # abgeleitet (_apply_set_state).
        if self._checkable and not archived_set:
            set_item.setFlags(set_item.flags() | Qt.ItemIsUserCheckable)
        # Bugfix 05.08.2026: Gehoert das Set einem Indikator, traegt der
        # Info-Button (Spalte 1) den Tooltip 'aktiv/im <Indikator>' (siehe
        # _apply_set_badge und _attach_item_buttons).
        self._apply_set_badge(set_item, child.get("definition") or child)
        for svc in services:
            # Keine fuehrenden Leerzeichen im Text: die Einrueckung der
            # Untereintraege kommt aus setIndentation(LEVEL_INDENT).
            # 05.08.2026 (Ausfuehrungsdatum): Das Datum der letzten
            # Ausfuehrung (DD.MM.JJ, aus dem feature_store) haengt direkt am
            # Service-Namen: 'prox_1 (05.08.26)' – ohne Eintrag '(--.--.--)'.
            plugin_id = svc.get("plugin_id") or ""
            last_exec = str(svc.get("last_execution") or "")
            last_exec = last_exec if last_exec and last_exec != "--.--.--" else "nie"
            # 13.08.2026 (Punkt 6, F6): Modus-Suffix am Service-Namen
            # (Format 'swing_momentum [MA_Peak_Hysteresis] (13.08.26)').
            mode_sfx = self._mode_suffix(plugin_id, svc.get("params"))
            svc_label = f"{svc.get('instance_id')}{mode_sfx} ({last_exec})"
            # 20.04 (Q6): Einzeln archivierte Instanzen tragen im Archiv
            # eine Kennzeichnung (is_archived=True -> non-checkable).
            svc_archived = bool(svc.get("is_archived"))
            if svc_archived:
                svc_label = f"🔹 {svc_label}"
            svc_item = QTreeWidgetItem([svc_label, ""])
            svc_item.setData(0, ROLE_NODE_TYPE, TYPE_SERVICE)
            svc_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
            svc_item.setData(0, ROLE_INSTANCE_ID, svc.get("instance_id") or "")
            svc_item.setData(0, ROLE_PLUGIN_ID, plugin_id)
            # Runde 13b (Bugfix Dropdown-NoData): Set-Instanzen werden beim
            # regularen Hinzufuegen OHNE instance_hash in der Set-Definition
            # gespeichert (nur _duplicate_set_instance persistiert ihn) -
            # daraus blieb `instance_hashes` fuer Set-Instanzen leer und die
            # '(No Data)'-Varianten-Einschraenkung des Readers griff nicht
            # (Dropdown zeigte die erste/falsche Variante und ungecheckte
            # Instanzen). Hier wird der fehlende Hash on-the-fly aus den
            # Params berechnet (identisch zum Reader-Set-Pfad
            # generate_instance_hash(pid, params)) - heilt Alt-Bestand ohne
            # DB-Migration.
            svc_hash = str(svc.get("instance_hash") or "")
            if not svc_hash and self.model is not None:
                try:
                    cfg = self.model.find_service(
                        str(child.get("set_id") or ""),
                        str(svc.get("instance_id") or "")) or {}
                    svc_hash = generate_instance_hash(
                        str(cfg.get("plugin_id") or plugin_id),
                        cfg.get("params") or {}) or ""
                except Exception:
                    svc_hash = ""
            svc_item.setData(0, ROLE_INSTANCE_HASH, svc_hash)
            if svc_archived or archived_set:
                svc_item.setData(0, ROLE_ARCHIVED, True)
            # 15.03-E (Multi-Select): Service-Knoten anhakbar – Zustand aus
            # _checked_items re-applizieren (bleibt ueber Neuaufbauten erhalten).
            if self._checkable and not svc_archived and not archived_set:
                svc_item.setFlags(svc_item.flags() | Qt.ItemIsUserCheckable)
                key = (TYPE_SERVICE,
                       str(child.get("set_id") or ""),
                       str(svc.get("instance_id") or ""),
                       svc_hash)
                state = (Qt.Checked if key in self._checked_items
                         else Qt.Unchecked)
                svc_item.setData(0, Qt.CheckStateRole, state)
            self._apply_badge(
                svc_item, plugin_id, svc.get("badge") or "",
                params=svc.get("params"))
            set_item.addChild(svc_item)
        if self._checkable:
            self._apply_set_state(set_item)
        return set_item

    @staticmethod
    def _mode_suffix(plugin_id: str,
                     params: Optional[Dict[str, Any]] = None) -> str:
        """'[{Modus}]'-Suffix fuer MasterTree-Labels (13.08.2026, Punkt 6, F6).

        Nur fuer Multi-Modus-Services: parameter_schema['mode']['options']
        enthaelt MEHR ALS EINEN Eintrag (z. B. srv_swing_momentum mit
        MA_Peak_Hysteresis/MA_Slope_Change/Chande_Kroll_Ratchet). Ein-
        Modus-Services bleiben ohne Suffix (kein Rauschen im Baum). Der
        Modus kommt aus den params der Instanz (Clone/Set-Service) bzw.
        aus dem Schema-Default (flache Plugin-Zeile ohne eigene params).
        Rein lesend (PluginRegistry-Singleton), Fehler defensiv leer.
        """
        try:
            from analytics.features.feature_builder import PluginRegistry
            reg = PluginRegistry()
            plugins = getattr(reg, "plugins", None) or {}
            pid_l = str(plugin_id or "").strip().lower()
            plugin = None
            for k, v in plugins.items():
                if str(k).strip().lower() == pid_l:
                    plugin = v
                    break
            if plugin is None:
                return ""
            schema = getattr(plugin, "parameter_schema", None) or {}
            mode_cfg = schema.get("mode") or {}
            options = [str(o).strip() for o in (mode_cfg.get("options") or [])
                       if str(o).strip()]
            if len(options) <= 1:
                return ""
            mode = ""
            if isinstance(params, dict):
                mode = str(params.get("mode") or "").strip()
            if not mode:
                mode = str(mode_cfg.get("default") or "").strip()
            return f" [{mode}]" if mode else ""
        except Exception:
            return ""

    def _build_plugin_item(self, child: Dict[str, Any],
                           group: str) -> QTreeWidgetItem:
        pid = child.get("plugin_id") or ""
        # Keine fuehrenden Leerzeichen: Einrueckung via setIndentation().
        # 05.08.2026 (Punkt 4): Das Datum der letzten Ausfuehrung (DD.MM.JJ,
        # aus dem feature_store) haengt auch an Standalone-/Plugin-Zeilen:
        # 'srv_proximity (02.08.26)' – ohne Eintrag '(--.--.--)'.
        last_exec = str(child.get("last_execution") or "")
        last_exec = last_exec if last_exec and last_exec != "--.--.--" else "nie"
        clones = child.get("clones") or []
        archived_parent = bool(child.get("archived"))
        # 10.08.2026 (Varianten-Ausfuehrungsdatum): Hat ein Plugin Varianten
        # (Clones), haengt das Datum der letzten Ausfuehrung an der Variante
        # (Clone-Zeile) – der Parent-Knoten zeigt nur noch die Plugin-ID
        # (kein Ausfuehrungsdatum mehr im Knoten darueber).
        # 11.08.2026 (Bugfix, Kosmetik): 'srv_'-Praefix der Plugin-ID wird
        # im Label abgeschnitten (Konsistenz zur Sets-Gruppe mit
        # instance_ids; ROLE_PLUGIN_ID bleibt die echte plugin_id).
        display_pid = pid[4:] if pid.startswith("srv_") else pid
        # 13.08.2026 (Punkt 6, F6): Modus-Suffix an flachen Plugin-Zeilen
        # (Plugins MIT Clones zeigen den Modus an den Clone-Zeilen).
        mode_sfx = "" if clones else self._mode_suffix(pid, None)
        plugin_label = (display_pid if clones
                        else f"{display_pid}{mode_sfx} ({last_exec})")
        plugin_item = QTreeWidgetItem([plugin_label, ""])
        plugin_item.setData(0, ROLE_NODE_TYPE, TYPE_PLUGIN)
        plugin_item.setData(0, ROLE_SET_ID, group)
        plugin_item.setData(0, ROLE_PLUGIN_ID, pid)
        if archived_parent:
            plugin_item.setData(0, ROLE_ARCHIVED, True)
        # 20.04 (Q7): Plugins MIT Clones sind Template-Parents (nicht direkt
        # ausfuehrbar) – KEINE Checkbox am Plugin-Knoten; die Clones tragen
        # die Haken. Plugins OHNE Clones bleiben anhakbare flache Blaetter
        # (Bestandsverhalten, feature_id des Feature-Store = plugin_id).
        if clones:
            plugin_item.setFlags(
                plugin_item.flags() & ~Qt.ItemIsUserCheckable)
        elif self._checkable:
            plugin_item.setFlags(
                plugin_item.flags() | Qt.ItemIsUserCheckable)
            key = (TYPE_PLUGIN, "", pid)
            state = (Qt.Checked if key in self._checked_items
                     else Qt.Unchecked)
            plugin_item.setData(0, Qt.CheckStateRole, state)
        self._apply_badge(plugin_item, pid, child.get("badge") or "")
        for clone in clones:
            plugin_item.addChild(self._build_clone_item(clone, pid))
        return plugin_item

    def _build_clone_item(self, clone: Dict[str, Any],
                          plugin_id: str) -> QTreeWidgetItem:
        """Erzeugt ein Clone-/Preset-Kind unter einem Plugin-Parent (20.04).

        Label-Format (Doku §3): aktive Clones `🟢 <Preset> (#<hash>)`,
        archivierte Clones `🔹 <Preset> (#<hash>)`. Aktive Clones sind im
        Checkbox-Modus anhakbar; ARCHIVIERTE Clones sind non-checkable
        (Archive Safety, Q6) und emittieren keine IDs an Scans/Analytics.
        """
        preset_name = str(clone.get("preset_name") or "Default")
        instance_hash = str(clone.get("instance_hash") or "")
        archived = bool(clone.get("is_archived"))
        # 10.08.2026 (Bugfix, Varianten-Ausfuehrungsdatum): Die ID (#hash)
        # entfaellt aus dem Label – stattdessen haengt das Datum der letzten
        # Ausfuehrung dieser Variante direkt am Varianten-Namen:
        # '🟢 <Preset> (DD.MM.JJ)' (ohne Eintrag '(--.--.--)').
        last_exec = str(clone.get("last_execution") or "")
        last_exec = last_exec if last_exec and last_exec != "--.--.--" else "nie"
        prefix = "🔹" if archived else "🟢"
        # 13.08.2026 (Punkt 6, F6): Modus-Suffix an der Variante
        # (Format '🟢 <Preset> [MA_Peak_Hysteresis] (13.08.26)') - die ID
        # (#hash) ist seit 10.08.2026 bereits aus dem Label entfernt.
        mode_sfx = self._mode_suffix(plugin_id, clone.get("params"))
        clone_item = QTreeWidgetItem(
            [f"{prefix} {preset_name}{mode_sfx} ({last_exec})", ""])
        clone_item.setData(0, ROLE_NODE_TYPE, TYPE_CLONE)
        clone_item.setData(0, ROLE_PLUGIN_ID, plugin_id)
        clone_item.setData(0, ROLE_INSTANCE_HASH, instance_hash)
        clone_item.setData(0, ROLE_PRESET_NAME, preset_name)
        if archived:
            clone_item.setData(0, ROLE_ARCHIVED, True)
        # Tooltip: Plugin/Preset + Modus + Parameter + Doc-Log (F6c).
        tooltip = f"Plugin: {plugin_id}\nPreset: {preset_name}"
        if mode_sfx:
            tooltip += f"\nModus:{mode_sfx}"
        params = clone.get("params") or {}
        if isinstance(params, dict) and params:
            try:
                tooltip += "\n" + ", ".join(
                    f"{k}={v}" for k, v in list(params.items())[:8])
            except Exception:
                pass
        doc_log = str(clone.get("doc_log") or "").strip()
        if doc_log:
            tooltip += f"\n📝 {doc_log}"
        clone_item.setToolTip(0, tooltip)
        # Checkbox nur fuer AKTIVE Clones im Checkbox-Modus (Q6).
        if self._checkable and not archived:
            clone_item.setFlags(
                clone_item.flags() | Qt.ItemIsUserCheckable)
            key = (TYPE_CLONE, plugin_id, instance_hash)
            state = (Qt.Checked if key in self._checked_items
                     else Qt.Unchecked)
            clone_item.setData(0, Qt.CheckStateRole, state)
        elif archived:
            # QTreeWidgetItem traegt ItemIsUserCheckable per Default – bei
            # ARCHIVIERTEN Clones explizit entfernen (Archive Safety, Q6).
            clone_item.setFlags(
                clone_item.flags() & ~Qt.ItemIsUserCheckable)
        return clone_item

    def _apply_badge(self, item: QTreeWidgetItem, plugin_id: str,
                     badge: str,
                     params: Optional[Dict[str, Any]] = None) -> None:
        """Setzt die Darstellung eines Service-/Plugin-Items (Spalte 0/1).

        * Spalte 1: KEIN Badge-Text mehr (Bugfix 05.08.2026) – den Platz
          nimmt der echte Info-Button ein (siehe _attach_item_buttons).
        * Tooltip (Bugfix 05.08.2026): ODER-Logik auf Indikator-Basis –
          a) Service wird aktiv von einem Indikator verwendet
             -> 'aktiv <Indikator>'
          b) sonst, wenn der Service zu einem Indikator gehoert
             -> 'im <Indikator>'
          Die Aktiv-Pruefung beruecksichtigt den ZUGEHOERIGEN Indikator
          (metadata['indicator_id']), nicht nur die Plugin-ID selbst –
          dadurch greift Variante a) auch fuer Services (srv_grid_lines/
          srv_proximity), die IN einem aktiven Indikator (Ind_FixedGridProximity)
          laufen. Der Tooltip wird auf Spalte 0 UND Spalte 1 gesetzt
          (Spalte 1 uebernimmt ihn der Info-Button).
        """
        # Badge-Text entfaellt in Spalte 1 (Info-Button statt Text-Badge).
        item.setText(1, "")
        if self.model.belongs_to_indicator(plugin_id):
            name = self.model.get_indicator_display_name(plugin_id)
            tooltip = (f"aktiv {name}" if self.model.is_active_in_chart(plugin_id)
                       else f"im {name}")
        else:
            tooltip = ""
        # 13.08.2026 (Punkt 6, F6c): Modus auch im Tooltip (falls die
        # Instanz-Params verfuegbar sind - Set-Service-/Clone-Zeile).
        mode_sfx = self._mode_suffix(plugin_id, params)
        if mode_sfx:
            tooltip = (f"{tooltip}\nModus:{mode_sfx}"
                       if tooltip else f"Modus:{mode_sfx}")
        item.setToolTip(0, tooltip)
        item.setToolTip(1, tooltip)

    def _apply_set_badge(self, item: QTreeWidgetItem,
                         definition: Dict[str, Any]) -> None:
        """Set-Badge (Bugfix 05.08.2026): gehoert ein Service-Set einem
        Indikator, traegt der Info-Button (Spalte 1) die Tooltip-Namenslogik
        aus _apply_badge ('aktiv <Indikator>' / 'im <Indikator>'). Mehrere
        Indikatoren im Set werden mit ' + ' verknuepft. Ohne Indikator-
        Zugehoerigkeit bleibt Spalte 1 leer (neutraler Button, kein Tooltip).
        Spalte 0 behaelt den 'Service-Set: <set_id>'-Tooltip (siehe
        _build_set_item) – der Set-Bezug bleibt erhalten.
        """
        names = self.model.get_set_indicator_names(definition or {})
        if not names:
            item.setToolTip(1, "")
            return
        label = " + ".join(names)
        tooltip = (f"aktiv {label}" if self.model.is_set_active(definition or {})
                   else f"im {label}")
        item.setToolTip(1, tooltip)

    def _category_path_of(self, item) -> str:
        """Voller Kategorie-Pfad eines Ordner-Items (17.01.02).

        Sammelt die Ordner-Labels von der Wurzel bis zum Item und verkettet
        sie slash-separiert OHNE '📁 '-Praefix (z.B. 'Swing Points/Geometrie').
        Liefert '' fuer Nicht-Ordner-Items oder leere Ketten. Das Format
        entspricht exakt `ServiceSelectorModel.category_plugin_ids()`.
        """
        parts: List[str] = []
        node = item
        hops = 0
        while node is not None and isValid(node) and hops < 64:
            if node.data(0, ROLE_NODE_TYPE) == TYPE_CATEGORY:
                label = str(node.data(0, ROLE_SET_ID) or "").strip()
                if label.startswith("📁"):
                    label = label[len("📁"):].lstrip()
                if label:
                    parts.append(label)
            node = node.parent()
            hops += 1
        return "/".join(reversed(parts))

    # -------------------------------------------------------------------------
    # 18.01.03 (Dynamic Tree Management): Kategorie-Drag&Drop + Ordner-CRUD
    # -------------------------------------------------------------------------

    def _group_of(self, item) -> str:
        """Eltern-GRUPPE eines Items ('sets' / 'plugins', 18.01.03, L3).

        Wandert vom Item zur Top-Level-Gruppe (TYPE_GROUP) und liefert deren
        ROLE_SET_ID (GROUP_SETS/GROUP_PLUGINS). Leer, wenn keine Gruppe
        gefunden wird (defensiv).
        """
        node = item
        hops = 0
        while node is not None and isValid(node) and hops < 64:
            if node.data(0, ROLE_NODE_TYPE) == TYPE_GROUP:
                return str(node.data(0, ROLE_SET_ID) or "")
            node = node.parent()
            hops += 1
        return ""

    def _drag_id(self, item) -> str:
        """Eindeutige ID eines ziehbaren Knotens fuer die MIME-Daten.

        Sets -> set_id (ROLE_SET_ID), Plugins -> plugin_id (ROLE_PLUGIN_ID),
        Kategorie-Ordner -> voller Kategorie-Pfad (_category_path_of).
        """
        node_type = item.data(0, ROLE_NODE_TYPE)
        if node_type == TYPE_CATEGORY:
            return self._category_path_of(item)
        if node_type == TYPE_SET:
            return str(item.data(0, ROLE_SET_ID) or "")
        if node_type == TYPE_PLUGIN:
            return str(item.data(0, ROLE_PLUGIN_ID) or "")
        return ""

    def startDrag(self, supported_actions) -> None:
        """Startet den internen Kategorie-Drag (18.01.03, E4).

        Ueberschrieben, damit NUR Sets/Plugins/Ordner gezogen werden
        (kein Service-Reorder – E4) und die Ziel-Informationen als JSON-MIME
        transportiert werden (Ordner sind nicht selektierbar, daher liefert
        der Qt-Default-Mime aus selectedItems() nicht die Quelle).
        """
        item = getattr(self, "_drag_source", None)
        if item is None or not isValid(item):
            super().startDrag(supported_actions)
            return
        node_type = item.data(0, ROLE_NODE_TYPE)
        if node_type not in (TYPE_SET, TYPE_PLUGIN, TYPE_CATEGORY):
            super().startDrag(supported_actions)
            return
        # 20.04 (Q6): Archivierte Knoten sind nicht ziehbar (Archive
        # Safety) – sie duerfen nicht in normale Kategorie-Ordner wandern.
        if item.data(0, ROLE_ARCHIVED):
            super().startDrag(supported_actions)
            return
        try:
            payload = {
                "node_type": node_type,
                "group": self._group_of(item),
                "id": self._drag_id(item),
                "path": (self._category_path_of(item)
                         if node_type == TYPE_CATEGORY else ""),
            }
            mime = QMimeData()
            mime.setData(MIME_CATEGORY_MOVE,
                         json.dumps(payload).encode("utf-8"))
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.MoveAction, Qt.MoveAction)
        except (RuntimeError, AttributeError):
            pass
        finally:
            self._drag_source = None

    def dragEnterEvent(self, event) -> None:
        """Akzeptiert nur den eigenen Kategorie-Move-MIME (18.01.03)."""
        try:
            if event.mimeData().hasFormat(MIME_CATEGORY_MOVE):
                event.acceptProposedAction()
                return
        except (RuntimeError, AttributeError):
            pass
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        """Akzeptiert den eigenen Kategorie-Move-MIME waehrend des Drags."""
        try:
            if event.mimeData().hasFormat(MIME_CATEGORY_MOVE):
                event.acceptProposedAction()
                return
        except (RuntimeError, AttributeError):
            pass
        super().dragMoveEvent(event)

    def _drop_target(self, item) -> tuple:
        """Bestimmt (Gruppe, Ziel-Kategorie-Pfad) fuer ein Drop-Ziel-Item.

        * Gruppe (TYPE_GROUP)  -> ("sets"/"plugins", "" = Root-Ebene)
        * Ordner (TYPE_CATEGORY) -> (Eltern-Gruppe, Ordner-Pfad)
        * Blatt (Set/Service/Plugin) -> (Eltern-Gruppe, Pfad des naechsten
          Kategorie-Vorfahren; "" wenn direkt unter der Gruppe)
        Liefert ("", "") wenn kein gueltiges Ziel gefunden wird (18.01.03).
        """
        if item is None or not isValid(item):
            return "", ""
        node_type = item.data(0, ROLE_NODE_TYPE)
        if node_type == TYPE_GROUP:
            return str(item.data(0, ROLE_SET_ID) or ""), ""
        if node_type == TYPE_CATEGORY:
            return self._group_of(item), self._category_path_of(item)
        # Blatt: zum naechsten Kategorie-Vorfahren (oder zur Gruppe) wandern.
        node = item.parent()
        hops = 0
        while node is not None and isValid(node) and hops < 64:
            nt = node.data(0, ROLE_NODE_TYPE)
            if nt == TYPE_CATEGORY:
                return self._group_of(node), self._category_path_of(node)
            if nt == TYPE_GROUP:
                return str(node.data(0, ROLE_SET_ID) or ""), ""
            node = node.parent()
            hops += 1
        return "", ""

    def dropEvent(self, event) -> None:
        """Verarbeitet den Kategorie-Drop (18.01.03).

        Der Baum fuehrt KEINEN echten Item-Move aus – es werden nur die
        Signale folder_item_moved (Set/Plugin) bzw. folder_moved (Ordner)
        emittiert; der Orchestrator persistiert den Kategorie-Pfad ueber
        Modell/Repositories und der naechste Refresh baut den Baum neu.
        Guards:
          * Nur der eigene MIME wird verarbeitet (sonst Qt-Default).
          * Gruppen-Mismatch (Set in Plugins-Ordner ziehen) -> abgelehnt.
          * Ordner-Zyklus (Ordner in seinen eigenen Unterordner) -> abgelehnt.
        """
        if not event.mimeData().hasFormat(MIME_CATEGORY_MOVE):
            super().dropEvent(event)
            return
        try:
            payload = json.loads(
                bytes(event.mimeData().data(MIME_CATEGORY_MOVE)).decode("utf-8"))
        except (ValueError, TypeError):
            event.ignore()
            return
        source_type = str(payload.get("node_type") or "")
        source_group = str(payload.get("group") or "")
        source_id = str(payload.get("id") or "")
        source_path = str(payload.get("path") or "")
        try:
            pos = (event.position().toPoint() if hasattr(event, "position")
                   else event.pos())
        except AttributeError:
            pos = event.pos()
        target = self.itemAt(pos)
        target_group, target_path = self._drop_target(target)
        if not target_group:
            event.ignore()
            return
        # 20.04 (Q6): Der Archiv-Ordner ist kein Drag-Ziel (Archive Safety).
        # Kategorie-Pfad 'Archiv' (ohne '📁 '-Praefix) wird abgelehnt.
        if str(target_path or "").strip().lower().startswith("archiv"):
            event.ignore()
            return
        if source_group and source_group != target_group:
            event.ignore()
            return
        if source_type == TYPE_CATEGORY:
            # Ordner-Verschiebung: Zyklus-Schutz (eigener Unterordner).
            if (not source_path or target_path == source_path
                    or target_path.startswith(source_path + "/")):
                event.ignore()
                return
            # 18.01.03 (Bugfix 08.08.2026): Ziel-Ordnerkette fuer den
            # folgenden Refresh zum Aufklappen merken (VOR dem emit).
            self._mark_expand(source_group, target_path)
            self.folder_moved.emit(source_group, source_path, target_path)
            event.accept()
            return
        if source_type in (TYPE_SET, TYPE_PLUGIN) and source_id:
            # 18.01.03 (Bugfix 08.08.2026): Ziel-Ordnerkette fuer den
            # folgenden Refresh zum Aufklappen merken (VOR dem emit).
            self._mark_expand(target_group, target_path)
            self.folder_item_moved.emit(source_type, source_id, target_path)
        event.accept()

    def _on_new_folder(self, group: str, parent_path: str) -> None:
        """Kontextmenue 'Neuer Ordner' (18.01.03, E3-revidiert).

        Fragt den Namen ab und emittiert `create_folder_requested(group,
        full_path)` – der Orchestrator PERSISTIERT den (ggf. leeren) Ordner
        ueber global_settings (service_set_utils.create_empty_folder,
        Key 'tree_folders_<group>'). Damit bleibt der Ordner ueber Refreshs
        erhalten und verschwindet nur bei manueller Loeschung im
        Kontextmenue ('Ordner löschen').
        """
        name, ok = QInputDialog.getText(
            self, "Neuer Ordner", "Ordner-Name:")
        name = (name or "").strip().strip("/")
        if not ok or not name:
            return
        parent_path = str(parent_path or "").strip().strip("/")
        full_path = f"{parent_path}/{name}" if parent_path else name
        # 18.01.03 (Bugfix 08.08.2026): Neuen Ordner (und Elternkette) fuer
        # den folgenden Refresh zum Aufklappen merken – VOR dem emit, weil
        # der Orchestrator den EventBus synchron feuert (data_changed ->
        # _populate).
        self._mark_expand(str(group), full_path)
        self.create_folder_requested.emit(str(group), full_path)

    def _on_rename_folder(self, group: str, old_path: str) -> None:
        """Kontextmenue 'Umbenennen' (18.01.03).

        Fragt den neuen Namen ab (vorbelegt mit dem letzten Pfad-Teil) und
        emittiert `rename_folder_requested(group, old_path, new_path)` – der
        Orchestrator fuehrt den String-Replace ueber alle Kinder aus
        (service_set_utils.rename_category) und emittiert den EventBus.
        """
        old_path = str(old_path or "").strip().strip("/")
        if not old_path:
            return
        old_name = old_path.split("/")[-1]
        new_name, ok = QInputDialog.getText(
            self, "Ordner umbenennen", "Neuer Name:", text=old_name)
        new_name = (new_name or "").strip().strip("/")
        if not ok or not new_name or new_name == old_name:
            return
        parts = old_path.split("/")
        new_path = "/".join(parts[:-1] + [new_name])
        self.rename_folder_requested.emit(str(group), old_path, new_path)

    def _on_rename_clone(self, item) -> None:
        """Kontextmenue 'Variante umbenennen' (10.08.2026, Bugfix).

        Fragt den neuen Preset-Namen ab (vorbelegt mit dem aktuellen Namen)
        und emittiert `rename_variant_requested(plugin_id, instance_hash,
        new_name)` – der Orchestrator (ServiceWindow/ServiceSelectorDialog)
        persistiert den Rename in indicator_presets und emittiert den
        EventBus (Live-Sync aller MasterTrees).
        """
        if item is None or not isValid(item):
            return
        plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
        instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
        old_name = str(item.data(0, ROLE_PRESET_NAME) or "")
        if not plugin_id or not instance_hash:
            return
        new_name, ok = QInputDialog.getText(
            self, "Variante umbenennen",
            "Neuer Name der Variante:", text=old_name)
        new_name = (new_name or "").strip()
        if not ok or not new_name or new_name == old_name:
            return
        self.rename_variant_requested.emit(
            plugin_id, instance_hash, new_name)

    # -------------------------------------------------------------------------
    # 18.01.03 (Bugfix 08.08.2026): Expansion-Erhaltung ueber _populate()
    # -------------------------------------------------------------------------

    def _collect_expanded_state(self) -> set:
        """Sammelt die aufgeklappten Knoten des IST-Baums (RAM-Schluessel).

        Schluessel: ("cat", group, kategorie-pfad) fuer Ordner bzw.
        ("set", set_id) fuer Set-Knoten. Top-Level-Gruppen (TYPE_GROUP)
        werden in _populate() ohnehin immer expandiert; Blatt-/Service-
        Knoten sind nicht aufklappbar. isValid-Guards gegen zerstoerte
        Items (Access-Violation-Schutz).
        """
        result: set = set()
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                if not item.isExpanded():
                    continue
                node_type = item.data(0, ROLE_NODE_TYPE)
                if node_type == TYPE_CATEGORY:
                    result.add(("cat", self._group_of(item),
                                self._category_path_of(item)))
                elif node_type == TYPE_SET:
                    result.add(("set",
                                str(item.data(0, ROLE_SET_ID) or "")))
                elif node_type == TYPE_PLUGIN and item.childCount() > 0:
                    # 10.08.2026 (Bugfix): Plugin-Parents mit Varianten/
                    # Clones sind aufklappbare Knoten - ihre Expansion muss
                    # ueber Rebuilds (data_changed -> _populate nach
                    # Speichern/Umbenennen/Duplizieren) erhalten bleiben,
                    # sonst klappt der Knoten zusammen. Nur ein Mausklick
                    # auf den Knoten soll togglen.
                    result.add(("plugin",
                                str(item.data(0, ROLE_PLUGIN_ID) or "")))
        except (RuntimeError, AttributeError):
            pass
        return result

    def _apply_expanded_state(self, expanded: set) -> None:
        """Expandiert die gesammelten Knoten nach dem Neuaufbau wieder.

        Zusaetzlich werden Einmal-Expansionen aus `_expand_after_rebuild`
        angewandt (Ziel-Ordner nach Drop, neu erzeugter Ordner) und danach
        geleert. Die '>'/'⌄'-Labels werden explizit aktualisiert (setExpanded
        unter blockSignals feuert kein itemExpanded).
        """
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                node_type = item.data(0, ROLE_NODE_TYPE)
                expand = False
                if node_type == TYPE_CATEGORY:
                    key = ("cat", self._group_of(item),
                           self._category_path_of(item))
                    expand = (key in expanded
                              or key in self._expand_after_rebuild)
                elif node_type == TYPE_SET:
                    key = ("set", str(item.data(0, ROLE_SET_ID) or ""))
                    expand = key in expanded
                elif node_type == TYPE_PLUGIN and item.childCount() > 0:
                    key = ("plugin",
                           str(item.data(0, ROLE_PLUGIN_ID) or ""))
                    expand = key in expanded
                if expand:
                    item.setExpanded(True)
        except (RuntimeError, AttributeError):
            pass
        self._expand_after_rebuild.clear()
        # Labels aller aufklappbaren Knoten auf den IST-Zustand bringen.
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                self._refresh_expand_label(item)
        except (RuntimeError, AttributeError):
            pass

    def _mark_expand(self, group: str, path: str) -> None:
        """Merkt die Ordnerkette von `path` fuer die naechste Expansion.

        Wird VOR dem emit() der Struktur-Signale gerufen (der EventBus-
        Refresh laeuft synchron waehrend des emit): Beim unmittelbar
        folgenden _populate() werden diese Pfade (und alle Eltern-Glieder)
        aufgeklappt, damit z. B. ein neu erzeugter Ordner oder ein
        Drop-Ziel-Ordner sofort sichtbar bleibt.
        """
        parts = [p.strip() for p in str(path or "").split("/") if p.strip()]
        for i in range(len(parts)):
            self._expand_after_rebuild.add(
                ("cat", str(group or ""), "/".join(parts[: i + 1])))

    def _attach_item_buttons(self) -> None:
        """Haengt die Info-Buttons (Spalte 1) an alle Service-/Set-/Plugin-
        Zeilen UND Kategorie-Ordner (Bugfix 05.08.2026 / 17.01.02).

        Der Button ist ein kompakter QPushButton ("ℹ", Icon-Breite) und ersetzt
        die frueheren Text-Badges. Gehoert die Zeile einem Indikator (Tooltip
        aus _apply_badge/_apply_set_badge vorhanden), ist er gelb (#FFD700)
        eingefaerbt und traegt den Tooltip; sonst neutral. Der Klick emittiert
        `info_requested` mit den zeilenspezifischen Daten:
          Service-Zeile -> (set_id, instance_id, plugin_id)
          Set-Zeile      -> (set_id, "", "")
          Plugin-Zeile   -> ("", "", plugin_id)
          Kategorie-Ordner -> `category_info_requested(Kategorie-Pfad)`
            (17.01.02: wie bei Sets – der Ordner-Button zeigt die Kategorie-
            Info mit allen Services unter dem Ordner).
        Gruppen-Knoten (📁 Sets / 📦 Services, TYPE_GROUP) erhalten bewusst
        KEINEN Button.
        """
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                node_type = item.data(0, ROLE_NODE_TYPE)
                if node_type not in (TYPE_SERVICE, TYPE_SET, TYPE_PLUGIN,
                                     TYPE_CATEGORY, TYPE_CLONE):
                    continue
                tooltip = item.toolTip(1) or ""
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                service_id = ""
                plugin_id = ""
                if node_type == TYPE_SERVICE:
                    service_id = str(item.data(0, ROLE_INSTANCE_ID) or "")
                    plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                elif node_type in (TYPE_PLUGIN, TYPE_CLONE):
                    # Plugin-/Clone-Zeilen: set_id bewusst leer (die
                    # ROLE_SET_ID traegt nur die Gruppenkennung); bei
                    # Clones liefert ROLE_PLUGIN_ID die feature_id.
                    set_id = ""
                    plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")

                btn = QPushButton(INFO_BUTTON_TEXT, self)
                btn.setFixedSize(INFO_BUTTON_SIZE, INFO_BUTTON_SIZE)
                btn.setCursor(Qt.PointingHandCursor)
                color = (INFO_BUTTON_COLOR_INDICATOR if tooltip
                         else INFO_BUTTON_COLOR_NEUTRAL)
                btn.setStyleSheet(
                    f"QPushButton {{ color:{color}; border:none;"
                    f" font-weight:bold; background:transparent; }}")
                if tooltip:
                    btn.setToolTip(tooltip)
                # 17.01.02: Kategorie-Ordner emittieren category_info_requested
                # mit dem vollen Kategorie-Pfad (analog Set-Info). 18.01.03
                # (L3): Zusaetzlich wird die Eltern-GRUPPE uebergeben, damit
                # der Orchestrator Sets-Ordner ('sets') von Plugins-Ordnern
                # ('plugins') unterscheiden kann.
                if node_type == TYPE_CATEGORY:
                    cat_path = self._category_path_of(item)
                    cat_group = self._group_of(item)
                    btn.setToolTip(
                        f"Kategorie: {cat_path or '?'}")
                    btn.clicked.connect(
                        lambda _=False, g=cat_group, cp=cat_path:
                        self.category_info_requested.emit(g, cp))
                else:
                    btn.clicked.connect(
                        lambda _=False, s=set_id, svc=service_id, pid=plugin_id:
                        self.info_requested.emit(s, svc, pid))
                self.setItemWidget(item, 1, btn)
        except (RuntimeError, AttributeError):
            pass

    # -------------------------------------------------------------------------
    # Phase 15 (Dirty-State): '*' am Service-Knoten bei ungespeicherten
    # Parameter-Aenderungen (Format 'Service_Name* (DD.MM.JJ)')
    # -------------------------------------------------------------------------

    def set_instance_dirty(self, instance_id: str, dirty: bool) -> None:
        """Markiert eine Service-Instanz als ungespeichert ('*' am Knoten).

        Der Dirty-Zustand wird im RAM gehalten (self._dirty_instance_ids) und
        bei jedem Baum-Neuaufbau (_populate) re-appliziert. Nach erfolgreichem
        Speichern ruft der Orchestrator clear_dirty_markers() auf.
        """
        if not instance_id:
            return
        if dirty:
            self._dirty_instance_ids.add(instance_id)
        else:
            self._dirty_instance_ids.discard(instance_id)
        self._apply_dirty_label(instance_id, dirty)

    def clear_dirty_markers(self) -> None:
        """Entfernt ALLE Sternchen-Markierungen (nach Speichern).

        Das Set wird geleert und die Knoten-Labels zurueckgesetzt; der
        naechste Baum-Neuaufbau erzeugt damit saubere Labels.
        """
        for iid in list(self._dirty_instance_ids):
            self._apply_dirty_label(iid, False)
        self._dirty_instance_ids.clear()

    def _apply_dirty_label(self, instance_id: str, dirty: bool) -> None:
        """Setzt/entfernt das '*' im Label des Service-Knotens mit
        instance_id. Das Ausfuehrungsdatum '(DD.MM.JJ)' bleibt erhalten."""
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                if item.data(0, ROLE_NODE_TYPE) != TYPE_SERVICE:
                    continue
                if str(item.data(0, ROLE_INSTANCE_ID) or "") != instance_id:
                    continue
                text = item.text(0) or ""
                name, sep, rest = text.partition(" (")
                if not sep:
                    continue
                name = name.rstrip("*")
                item.setText(0, f"{name}{'*' if dirty else ''} ({rest}")
                break
        except (RuntimeError, AttributeError):
            pass

    # -------------------------------------------------------------------------
    # 15.03-E (Multi-Select): Checkbox-Modus (ServiceSelectorDialog)
    # -------------------------------------------------------------------------

    def set_checkable(self, checkable: bool) -> None:
        """Schaltet den Checkbox-Modus ein/aus (SELECT_MULTI).

        Im Normalbetrieb (FULL_EDIT, ServiceWindow) ist der Baum NICHT
        anhakbar – `set_checkable(True)` aktiviert die Checkboxen fuer den
        ServiceSelectorDialog und baut den Baum neu auf (Zustand beginnt
        leer). `set_checkable(False)` deaktiviert und leert den Zustand.
        """
        checkable = bool(checkable)
        if checkable == self._checkable:
            return
        self._checkable = checkable
        if not checkable:
            self._checked_items.clear()
        self._populate()

    def _expand_ancestors(self, item) -> None:
        """Klappt die Eltern-Kette eines Items auf (Bugfix 08.08.2026).

        Bug 2 (User-Meldung: 'Tree-Knoten sollen aufgeklappt sein und die
        Services sichtbar sein, die aktiviert wurden'): Nach dem Setzen der
        Checkboxen (`set_checked_feature_ids`) bzw. beim Live-Anhaken
        (`_on_item_changed`) muessen die Eltern-Knoten (Sets / Kategorie-
        Ordner) expandiert sein – der Baum startet eingeklappt, nur die
        Top-Level-Gruppen sind in _populate() expandiert. Ohne Expansion
        bleiben angehakte Services/Plugins in eingeklappten Eltern unsichtbar.
        setExpanded feuert itemExpanded -> _refresh_expand_label ('>'/'⌄'-
        Label-Sync); waehrend `_updating_checks == True` ignoriert
        _on_item_changed die dadurch ausgeloesten spurious itemChanged-Events.
        """
        node = item
        hops = 0
        while node is not None and isValid(node) and hops < 64:
            node = node.parent()
            if node is None or not isValid(node):
                break
            try:
                if node.childCount() > 0 and not node.isExpanded():
                    node.setExpanded(True)
            except (RuntimeError, AttributeError):
                break
            hops += 1

    def _on_item_changed(self, item, column: int) -> None:
        """Aktualisiert die Checkbox-Zustaende (15.03-E, SELECT_MULTI).

        itemChanged feuert bei JEDER Daten-Aenderung eines Items; die Guards
        (`_checkable`, `_updating_checks`, Knotentyp) halten den Handler
        schlank. Set-Knoten propagieren ihren Zustand auf alle Service-
        Kinder; der Tri-State der Sets wird IMMER aus den Kindern abgeleitet
        (Qt bietet in QTreeWidget keine automatische Synchronisation).

        Bugfix 06.08.2026 (Punkte 1/2/6): `itemChanged` feuert auch bei
        TEXT-Aenderungen – z. B. `_refresh_expand_label` nach einem
        Zeilen-Klick auf einen Set-Knoten (Auf-/Zuklappen). Solche spurious
        Events duerfen die Haken NICHT veraendern: Es wird nur verarbeitet,
        wenn sich der CheckState tatsaechlich vom erwarteten Zustand
        unterscheidet (erwartet = aus `_checked_items` bzw. den Service-
        Kindern des Sets abgeleitet).
        """
        if column != 0 or not self._checkable or self._updating_checks:
            return
        if item is None or not isValid(item):
            return
        node_type = item.data(0, ROLE_NODE_TYPE)
        if node_type not in (TYPE_SET, TYPE_SERVICE, TYPE_PLUGIN, TYPE_CLONE):
            return
        self._updating_checks = True
        try:
            state = item.checkState(0)
            if node_type == TYPE_SERVICE:
                key = (TYPE_SERVICE,
                       str(item.data(0, ROLE_SET_ID) or ""),
                       str(item.data(0, ROLE_INSTANCE_ID) or ""),
                       str(item.data(0, ROLE_INSTANCE_HASH) or ""))
                # Kein echter Checkbox-Wechsel (z. B. Text-Refresh)? -> return.
                expected = (Qt.Checked if key in self._checked_items
                            else Qt.Unchecked)
                if state == expected:
                    return
                if state == Qt.Checked:
                    self._checked_items.add(key)
                    # Bugfix 08.08.2026: Eltern-Kette aufklappen, damit der
                    # angehakte Service im Set sofort sichtbar ist.
                    self._expand_ancestors(item)
                else:
                    self._checked_items.discard(key)
                    # Runde 9 (Bug 3): KEIN _uncheck_plugin_rows mehr - das
                    # Abhaengen ALLER Zeilen einer plugin_id hat beim Uncheck
                    # einer Variante auch die anderen Clones abgehaengt
                    # (falsch). checked_feature_ids() dedupliziert ohnehin
                    # auf plugin_id: Der Filter bleibt aktiv, solange
                    # mindestens eine Zeile gecheckt ist.
                parent = item.parent()
                if parent is not None and isValid(parent):
                    self._apply_set_state(parent)
            elif node_type == TYPE_PLUGIN:
                key = (TYPE_PLUGIN, "",
                       str(item.data(0, ROLE_PLUGIN_ID) or ""))
                expected = (Qt.Checked if key in self._checked_items
                            else Qt.Unchecked)
                if state == expected:
                    return
                if state == Qt.Checked:
                    self._checked_items.add(key)
                    # Bugfix 08.08.2026: Eltern-Kette aufklappen (Ordner/
                    # Gruppe), damit die angehakte Plugin-Zeile sichtbar ist.
                    self._expand_ancestors(item)
                else:
                    self._checked_items.discard(key)
                    # Runde 9 (Bug 3): _uncheck_plugin_rows entfernt (siehe
                    # TYPE_SERVICE) - nur diesen einen Key abhaengen.
            elif node_type == TYPE_CLONE:
                # 20.04 (Q7): Clone-Haken -> feature_id ist die plugin_id
                # des Plugin-Parents (WHERE feature_id IN (plugin_ids)).
                key = (TYPE_CLONE,
                       str(item.data(0, ROLE_PLUGIN_ID) or ""),
                       str(item.data(0, ROLE_INSTANCE_HASH) or ""))
                expected = (Qt.Checked if key in self._checked_items
                            else Qt.Unchecked)
                if state == expected:
                    return
                if state == Qt.Checked:
                    self._checked_items.add(key)
                    self._expand_ancestors(item)
                else:
                    self._checked_items.discard(key)
                    # Runde 9 (Bug 3): _uncheck_plugin_rows entfernt (siehe
                    # TYPE_SERVICE) - nur diesen einen Key abhaengen.
            elif node_type == TYPE_SET:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                # Nur bei ECHTEM Wechsel verarbeiten (Tri-State-Ableitung).
                if state == self._derive_set_state(item):
                    return
                for i in range(item.childCount()):
                    child = item.child(i)
                    if child is None or not isValid(child):
                        continue
                    if child.data(0, ROLE_NODE_TYPE) != TYPE_SERVICE:
                        continue
                    key = (TYPE_SERVICE, set_id,
                           str(child.data(0, ROLE_INSTANCE_ID) or ""),
                           str(child.data(0, ROLE_INSTANCE_HASH) or ""))
                    if state == Qt.Checked:
                        self._checked_items.add(key)
                        child.setData(0, Qt.CheckStateRole, Qt.Checked)
                    else:
                        self._checked_items.discard(key)
                        child.setData(0, Qt.CheckStateRole, Qt.Unchecked)
                        # Runde 9 (Bug 3): _uncheck_plugin_rows entfernt
                        # (siehe TYPE_SERVICE) - nur diesen einen Key
                        # abhaengen, nicht alle Zeilen der plugin_id.
                self._apply_set_state(item)
                # Bugfix 08.08.2026: Auch beim Set-Anhaken die Eltern-Kette
                # des Sets aufklappen (Set in Kategorie-Ordner sichtbar).
                self._expand_ancestors(item)
            self.checked_changed.emit()
        finally:
            self._updating_checks = False

    # Runde 9 (Bug 3): _uncheck_plugin_rows ist ENTFERNT/AUSKOMMENTIERT -
    # das Abhaengen ALLER Zeilen einer plugin_id beim Uncheck einer
    # Variante hat auch die anderen Clones abgehaengt (falsch). Siehe
    # _on_item_changed (nur den einen Key abhaengen).
    #     def _uncheck_plugin_rows(self, plugin_id: str) -> None:
    #         """Haengt ALLE Zeilen einer plugin_id ab (Bugfix 10.08.2026).

    #         `checked_feature_ids()` dedupliziert die Haken auf
    #         plugin_id-Ebene (eine plugin_id == eine feature_id fuer
    #         `WHERE feature_id IN (...)`). Beim Restore
    #         (`set_checked_feature_ids`) koennen deshalb mehrere Zeilen-
    #         Typen derselben plugin_id angehakt sein: die Service-Zeile im
    #         Set, das Standalone-Plugin-Blatt (TYPE_PLUGIN) und ggf.
    #         Clones. Ein Uncheck NUR einer Zeile wuerde die plugin_id
    #         ueber die anderen Zeilen im Filter belassen (Dropdown/
    #         Historie reagieren nicht) - deshalb werden hier alle Zeilen
    #         mit derselben plugin_id abgehaengt und ihre Keys aus
    #         `_checked_items` entfernt. Wird aus den Uncheck-Zweigen von
    #         `_on_item_changed` gerufen (laeuft unter `_updating_checks
    #         == True`, d. h. die setData-Aufrufe feuern keine spurious
    #         Events).
    #         """
    #         pid = str(plugin_id or "").lower()
    #         if not pid:
    #             return
    #         for item in TreeItemIterator(self):
    #             if item is None or not isValid(item):
    #                 continue
    #             node_type = item.data(0, ROLE_NODE_TYPE)
    #             if node_type not in (TYPE_SERVICE, TYPE_PLUGIN, TYPE_CLONE):
    #                 continue
    #             if str(item.data(0, ROLE_PLUGIN_ID) or "").lower() != pid:
    #                 continue
    #             if item.checkState(0) != Qt.Checked:
    #                 continue
    #             if node_type == TYPE_SERVICE:
    #                 key = (TYPE_SERVICE,
    #                        str(item.data(0, ROLE_SET_ID) or ""),
    #                        str(item.data(0, ROLE_INSTANCE_ID) or ""))
    #             elif node_type == TYPE_PLUGIN:
    #                 key = (TYPE_PLUGIN, "",
    #                        str(item.data(0, ROLE_PLUGIN_ID) or ""))
    #             else:
    #                 key = (TYPE_CLONE,
    #                        str(item.data(0, ROLE_PLUGIN_ID) or ""),
    #                        str(item.data(0, ROLE_INSTANCE_HASH) or ""))
    #             self._checked_items.discard(key)
    #             item.setData(0, Qt.CheckStateRole, Qt.Unchecked)
    #             parent = item.parent()
    #             if (parent is not None and isValid(parent)
    #                     and parent.data(0, ROLE_NODE_TYPE) == TYPE_SET):
    #                 self._apply_set_state(parent)
    def _derive_set_state(self, set_item) -> int:
        """Erwarteter Tri-State eines Set-Knotens aus seinen Service-Kindern.

        Checked = alle Kinder gecheckt, PartiallyChecked = gemischt,
        Unchecked = keines (Sets ohne Service-Kinder = Unchecked). Dient als
        Vergleichswert in `_on_item_changed`, um spurious itemChanged-Events
        (Text-/Tooltip-Refresh) von echten Checkbox-Klicks zu unterscheiden.
        """
        checked = 0
        total = 0
        for i in range(set_item.childCount()):
            child = set_item.child(i)
            if child is None or not isValid(child):
                continue
            if child.data(0, ROLE_NODE_TYPE) != TYPE_SERVICE:
                continue
            total += 1
            if child.checkState(0) == Qt.Checked:
                checked += 1
        if total > 0 and checked == total:
            return Qt.Checked
        if checked > 0:
            return Qt.PartiallyChecked
        return Qt.Unchecked

    def _apply_set_state(self, set_item) -> None:
        """Setzt den Tri-State eines Set-Knotens aus seinen Service-Kindern.

        Checked = alle Kinder gecheckt, PartiallyChecked = gemischt,
        Unchecked = keines. Sets ohne Service-Kinder sind Unchecked.
        """
        if set_item is None or not isValid(set_item):
            return
        if not self._checkable:
            return
        checked = 0
        total = 0
        for i in range(set_item.childCount()):
            child = set_item.child(i)
            if child is None or not isValid(child):
                continue
            if child.data(0, ROLE_NODE_TYPE) != TYPE_SERVICE:
                continue
            total += 1
            if child.checkState(0) == Qt.Checked:
                checked += 1
        if total > 0 and checked == total:
            state = Qt.Checked
        elif checked > 0:
            state = Qt.PartiallyChecked
        else:
            state = Qt.Unchecked
        set_item.setData(0, Qt.CheckStateRole, state)

    def _sync_checked_from_tree(self) -> None:
        """Gleicht `_checked_items` mit dem IST-Baum ab (stale Keys raus).

        Wird am Ende von `_populate()` gerufen: Nach einem Neuaufbau haelt
        das Set nur noch Keys tatsaechlich vorhandener, angehakter Knoten
        (geloeschte Sets/Services/Plugins verschwinden automatisch).
        """
        if not self._checkable:
            return
        synced: set = set()
        for item in TreeItemIterator(self):
            if item is None or not isValid(item):
                continue
            if item.checkState(0) != Qt.Checked:
                continue
            node_type = item.data(0, ROLE_NODE_TYPE)
            if node_type == TYPE_SERVICE:
                synced.add((TYPE_SERVICE,
                            str(item.data(0, ROLE_SET_ID) or ""),
                            str(item.data(0, ROLE_INSTANCE_ID) or ""),
                            str(item.data(0, ROLE_INSTANCE_HASH) or "")))
            elif node_type == TYPE_PLUGIN and item.childCount() == 0:
                # 10.08.2026 (Punkt 6): Plugin-Parents mit Varianten sind
                # non-checkable - kein Haken-Sync (Konsistenz zum Reverse-
                # Mapping in set_checked_feature_ids).
                synced.add((TYPE_PLUGIN, "",
                            str(item.data(0, ROLE_PLUGIN_ID) or "")))
            elif node_type == TYPE_CLONE:
                # 20.04 (Q7): Clone-Keys (plugin_id, instance_hash).
                synced.add((TYPE_CLONE,
                            str(item.data(0, ROLE_PLUGIN_ID) or ""),
                            str(item.data(0, ROLE_INSTANCE_HASH) or "")))
        self._checked_items = synced

    def checked_services(self) -> List[Dict[str, str]]:
        """Alle angehakten Service-/Plugin-Knoten (deterministisch sortiert).

        Returns:
            Pro Eintrag: {"node_type", "set_id", "instance_id", "plugin_id"}.
            Bei Service-Knoten ist instance_id die Set-Instanz; bei
            Standalone-/Plugin-Zeilen ist plugin_id gesetzt (set_id/instance_id
            leer).
        """
        result: List[Dict[str, str]] = []
        for entry in sorted(self._checked_items):
            node_type = str(entry[0])
            if node_type == TYPE_SERVICE:
                set_id = str(entry[1] or "")
                instance_id = str(entry[2] or "")
                # Runde 13 (Bugfix Dropdown-NoData): 4. Element = instance_hash
                # der Set-Instanz-Variante (variantengenaue Einschraenkung).
                instance_hash = str(entry[3] or "") if len(entry) > 3 else ""
                cfg = self.model.find_service(set_id, instance_id) or {}
                result.append({
                    "node_type": TYPE_SERVICE,
                    "set_id": set_id,
                    "instance_id": instance_id,
                    "plugin_id": str(cfg.get("plugin_id") or instance_id),
                    "instance_hash": instance_hash,
                })
            elif node_type == TYPE_PLUGIN:
                result.append({
                    "node_type": TYPE_PLUGIN,
                    "set_id": "",
                    "instance_id": "",
                    "plugin_id": str(entry[2] or ""),
                    "instance_hash": "",
                })
            elif node_type == TYPE_CLONE:
                # 20.04 (Q7): Clone-Haken -> feature_id ist die plugin_id
                # (im set_id-Slot gespeichert); instance_hash im
                # instance_id-Slot fuer die Varianten-Aufloesung.
                result.append({
                    "node_type": TYPE_CLONE,
                    "set_id": "",
                    "instance_id": str(entry[2] or ""),
                    "plugin_id": str(entry[1] or ""),
                    "instance_hash": str(entry[2] or ""),
                })
        return result

    def checked_feature_ids(self) -> List[str]:
        """Deduplizierte plugin_ids aller Haken (SQL-Vertrag `IN (...)`).

        Mehrere Services mit derselben plugin_id (z. B. grid_1 + grid_2)
        ergeben EINEN feature_id-Eintrag ('srv_grid_lines').
        """
        ids: List[str] = []
        for entry in self.checked_services():
            pid = entry["plugin_id"]
            if pid and pid not in ids:
                ids.append(pid)
        return ids

    def checked_instance_hashes(self) -> List[str]:
        """Deduplizierte instance_hashes aller gecheckten Clone-Varianten.

        Runde 10 (Bug 1): Der Filter ist damit varianten-granular - ein
        Check/Uncheck EINER Variante (Clone) aendert den Datenfilter
        sichtbar (feature_ids bleibt plugin_id-granular fuer die
        IN-Klausel, instance_hashes schraenkt auf die gewaehlten
        Varianten ein). Leere Liste = keine Varianten-Einschraenkung.
        """
        hashes: List[str] = []
        for entry in self.checked_services():
            # Runde 13 (Bugfix Dropdown-NoData): Hashes ALLER gecheckten
            # Varianten sammeln - Clone-Knoten UND Set-Instanz-Varianten
            # (vorher nur TYPE_CLONE; Set-Instanzen verloren ihren Hash in
            # der Check-Sync-Kette und die Varianten-Einschraenkung blieb
            # leer -> No-Data-Dropdown zeigte die falsche/erste Variante).
            h = entry.get("instance_hash") or ""
            if h and h not in hashes:
                hashes.append(h)
        return hashes

    def checked_display_names(self) -> List[str]:
        """Lesbare Namen fuer die Button-Anzeige (Top-Bar).

        Set-Services: '<Set-Anzeigename>/<instance_id>'
        (z. B. 'Mein Scalper/prox_1'); Standalone-/Plugin-Zeilen: plugin_id
        (z. B. 'srv_proximity').
        """
        names: List[str] = []
        for entry in self.checked_services():
            if entry["node_type"] == TYPE_SERVICE:
                s = self.model.find_set(entry["set_id"]) or {}
                set_name = s.get("display_name") or entry["set_id"] or "?"
                names.append(f"{set_name}/{entry['instance_id']}")
            elif entry["node_type"] == TYPE_CLONE:
                # 20.04 (Q7): Clone-Anzeige '<plugin_id> (#<hash>)'.
                pid = entry["plugin_id"]
                h = entry.get("instance_id") or ""
                names.append(f"{pid} (#{h})" if h else pid)
            else:
                names.append(entry["plugin_id"])
        return names

    def clear_checks(self) -> None:
        """Entfernt ALLE Checkbox-Haken (Dialog-'Filter entfernen').

        Set-Knoten werden mit ihren Service-Kindern zurueckgesetzt; das
        Signal `checked_changed` wird anschliessend emittiert.
        """
        if not self._checkable:
            return
        self._updating_checks = True
        try:
            self._checked_items.clear()
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                if item.data(0, ROLE_NODE_TYPE) in (TYPE_SET, TYPE_SERVICE,
                                                    TYPE_PLUGIN, TYPE_CLONE):
                    item.setData(0, Qt.CheckStateRole, Qt.Unchecked)
        finally:
            self._updating_checks = False
        self.checked_changed.emit()

    def set_checked_feature_ids(self, feature_ids,
                               instance_hashes=None) -> None:
        """Setzt die Haken anhand von plugin_ids (Reverse-Mapping).

        Wird beim Oeffnen des Dialogs aufgerufen, damit die aktuelle
        ViewModel-Auswahl (Profil/Filter) im Baum widergespiegelt wird.
        Matcht Services ueber ihre plugin_id UND Standalone-/Plugin-Zeilen;
        nicht gematchte Haken werden entfernt.
        """
        if not self._checkable:
            return
        wanted = {str(f).strip().lower() for f in (feature_ids or []) if str(f).strip()}
        # Runde 9 (Bug 1): Ist der Baum noch NICHT aufgebaut (das initiale
        # data_changed des Modells lief VOR der Dialog-Erstellung, der Baum
        # bleibt sonst leer), werden die gewuenschten IDs gemerkt und beim
        # naechsten _populate() automatisch angewendet - sonst gingen die
        # restaurierten Haken verloren ('restore fails wenn offen').
        if self.topLevelItemCount() == 0:
            self._pending_feature_ids = [str(f) for f in (feature_ids or [])]
            self._pending_instance_hashes = [
                str(h) for h in (instance_hashes or []) if str(h).strip()]
            return
        self._updating_checks = True
        # Runde 10 (Bug 1): instance_hashes is None = KEINE
        # Varianten-Einschraenkung (alle Clones der wanted plugin_ids);
        # leere Liste = explizit KEINE Variante angehakt.
        hash_restriction = instance_hashes is not None
        wanted_hashes = {str(h).strip().lower()
                         for h in (instance_hashes or []) if str(h).strip()}
        # Bugfix 08.08.2026 (Bug 2): Angehakte Items merken, um danach ihre
        # Eltern-Kette aufzuklappen (der Baum startet eingeklappt – ohne
        # Expansion bleiben die aktivierten Services/Plugins unsichtbar).
        checked_items: List[QTreeWidgetItem] = []
        try:
            self._checked_items.clear()
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                node_type = item.data(0, ROLE_NODE_TYPE)
                if node_type == TYPE_SERVICE:
                    set_id = str(item.data(0, ROLE_SET_ID) or "")
                    instance_id = str(item.data(0, ROLE_INSTANCE_ID) or "")
                    instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
                    cfg = self.model.find_service(set_id, instance_id) or {}
                    pid = str(cfg.get("plugin_id") or instance_id)
                    # Runde 13 (Bugfix Dropdown-NoData): Reverse-Mapping mit
                    # Hash-Granularitaet auch fuer Set-Instanz-Varianten
                    # (analog TYPE_CLONE) - sind instance_hashes gesetzt,
                    # wird NUR die passende Instanz angehakt.
                    if hash_restriction:
                        checked = (pid.lower() in wanted
                                   and instance_hash.strip().lower()
                                   in wanted_hashes)
                    else:
                        checked = pid.lower() in wanted
                    if checked:
                        self._checked_items.add((TYPE_SERVICE, set_id,
                                                 instance_id,
                                                 instance_hash))
                        checked_items.append(item)
                    item.setData(0, Qt.CheckStateRole,
                                 Qt.Checked if checked else Qt.Unchecked)
                elif node_type == TYPE_PLUGIN and item.childCount() == 0:
                    # 10.08.2026 (Punkt 6): Plugin-Parents MIT Varianten/
                    # Clones sind Template-Knoten OHNE Checkbox (sie tragen
                    # nur die Clone-Haken) - beim Reverse-Mapping werden sie
                    # uebersprungen; nur flache Blaetter bleiben anhakbar.
                    pid = str(item.data(0, ROLE_PLUGIN_ID) or "")
                    checked = pid.lower() in wanted
                    if checked:
                        self._checked_items.add((TYPE_PLUGIN, "", pid))
                        checked_items.append(item)
                    item.setData(0, Qt.CheckStateRole,
                                 Qt.Checked if checked else Qt.Unchecked)
                elif node_type == TYPE_CLONE:
                    # 20.04 (Q7): Clone-Haken folgen der plugin_id (feature-
                    # id des Filters); instance_hash unterscheidet Varianten.
                    # Runde 10 (Bug 1): Reverse-Mapping mit Hash-Granularitaet
                    # - sind instance_hashes gesetzt, wird NUR die passende
                    # Variante angehakt (sonst alle der plugin_id).
                    pid = str(item.data(0, ROLE_PLUGIN_ID) or "")
                    instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
                    if hash_restriction:
                        checked = (pid.lower() in wanted
                                   and instance_hash.strip().lower()
                                   in wanted_hashes)
                    else:
                        checked = pid.lower() in wanted
                    if checked:
                        self._checked_items.add(
                            (TYPE_CLONE, pid, instance_hash))
                        checked_items.append(item)
                    item.setData(0, Qt.CheckStateRole,
                                 Qt.Checked if checked else Qt.Unchecked)
            # Tri-States der Sets aus den Kindern ableiten
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                if item.data(0, ROLE_NODE_TYPE) == TYPE_SET:
                    self._apply_set_state(item)
            # Bugfix 08.08.2026 (Bug 2): Eltern-Kette aller angehakten Items
            # aufklappen, damit die aktivierten Services sichtbar sind.
            for item in checked_items:
                self._expand_ancestors(item)
        finally:
            self._updating_checks = False
        # Bugfix 10.08.2026 (Bug 5): KEIN checked_changed hier - dieses
        # programmatische Set (beim Oeffnen des Picker-Dialogs) darf keine
        # Feedback-Schleife in Gang setzen (checked_changed -> selection_ids
        # -> set_feature_ids wuerde den restaurierten Filter ueberschreiben).
        # Nur Nutzer-Aktionen (_on_item_changed) und clear_checks() emittieren.

    # -------------------------------------------------------------------------
    # Kontextmenue (Bugfix 05.08.2026, entkoppelt)
    # -------------------------------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        """Baut das Kontextmenue fuer den Rechtsklick dynamisch je Knotentyp.

        Die Aktionen emittieren AUSSCHLIESSLICH Signale – der Orchestrator
        (ServiceWindow) verknuepft sie mit seinen Handlern:

          * Gruppe 📁 (sets)      -> 'Neues Set anlegen' (create_set_requested)
          * Set-Knoten            -> '▶️ Alle Services ausführen' (run_set),
                                     'Set umbenennen', 'Service hinzufuegen',
                                     'Set loeschen' (rename/add/delete-requested)
          * Service-Knoten        -> '▶️ Diesen Service ausführen' (run_service),
                                     'Order ▲/▼', 'Service entfernen',
                                     'Service-Info anzeigen' (move/remove/
                                     info_requested)
          * Plugin-Zeile (Services) -> '▶️ Diesen Service ausführen'
                                     (run_plugin_requested, einzeln) +
                                     'Service-Info anzeigen' (17.01.02)
          * Kategorie-Ordner      -> '▶️ Alle Services ausführen'
                                     (run_category_requested, rekursiv) +
                                     'Ordner-Info anzeigen' (17.01.02) +
                                     'Neuer Ordner' / 'Umbenennen' /
                                     'Ordner löschen' (18.01.03; Loeschen
                                     nur fuer leere Ordner aktiv)
          * Sonstige Gruppen      -> Order/Entfernen ausgegraut (17.01.02).

        isValid-Guards: Bei wildem Klicken koennen Items zwischen itemAt() und
        Datenzugriff C++-seitig zerstoert sein (Access-Violation-Schutz).
        """
        try:
            item = self.itemAt(pos)
            if item is None or not isValid(item):
                return
            # Bugfix 05.08.2026: Rechtsklick togglet aufklappbare Knoten
            # (Konsistenz mit Linksklick), damit das Kontextmenue immer auf
            # dem sichtbaren Knoten steht.
            try:
                if item.childCount() > 0:
                    item.setExpanded(not item.isExpanded())
            except (RuntimeError, AttributeError):
                pass
            node_type = item.data(0, ROLE_NODE_TYPE)
            # 17.01.02 (Bugfix-Runde): Kategorie-Ordner erhalten jetzt ein
            # Kontextmenue mit '▶️ Alle Services ausführen' (rekursiv, alle
            # Services unter dem Ordner) + 'Ordner-Info anzeigen' (analog zu
            # den Set-Aktionen in der 📁-Gruppe). 18.01.03: Run/Info tragen
            # zusaetzlich die Eltern-GRUPPE ('sets'/'plugins', L3) und das
            # Menue bietet 'Neuer Ordner' + 'Umbenennen' + 'Ordner löschen'
            # (Ordner-CRUD, 18.01.03; Loeschen nur fuer leere Ordner aktiv).
            if node_type == TYPE_CATEGORY:
                cat_path = self._category_path_of(item)
                cat_group = self._group_of(item)
                if not cat_path:
                    return
                menu = QMenu(self)
                act_run = menu.addAction("▶️ Alle Services ausführen")
                act_run.triggered.connect(
                    lambda _=False, g=cat_group, cp=cat_path:
                    self.run_category_requested.emit(g, cp))
                menu.addSeparator()
                act_info = menu.addAction("Ordner-Info anzeigen")
                act_info.triggered.connect(
                    lambda _=False, g=cat_group, cp=cat_path:
                    self.category_info_requested.emit(g, cp))
                menu.addSeparator()
                act_new = menu.addAction("Neuer Ordner")
                act_new.triggered.connect(
                    lambda _=False, g=cat_group, cp=cat_path:
                    self._on_new_folder(g, cp))
                act_ren = menu.addAction("Umbenennen")
                act_ren.triggered.connect(
                    lambda _=False, g=cat_group, cp=cat_path:
                    self._on_rename_folder(g, cp))
                menu.addSeparator()
                # 18.01.03 (E3-revidiert, 08.08.2026): 'Ordner löschen' –
                # die EINZIGE Moeglichkeit, einen leeren Ordner zu entfernen
                # (leere Ordner verschwinden NICHT automatisch beim Refresh).
                # Nur fuer Ordner OHNE Kinder aktiv – bei gefuellten Ordnern
                # muss der Benutzer zuerst die Kinder herausziehen (Guard).
                act_del = menu.addAction("Ordner löschen")
                act_del.setToolTip(
                    "Nur für leere Ordner verfügbar – entfernt den Ordner "
                    "dauerhaft.")
                act_del.setEnabled(item.childCount() == 0)
                act_del.triggered.connect(
                    lambda _=False, g=cat_group, cp=cat_path:
                    self.delete_folder_requested.emit(g, cp))
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            menu = QMenu(self)
            if node_type == TYPE_GROUP:
                group = str(item.data(0, ROLE_SET_ID) or "")
                if group == self.model.GROUP_SETS:
                    act = menu.addAction("Neues Set anlegen")
                    act.triggered.connect(
                        lambda _=False: self.create_set_requested.emit())
                    # 18.01.03: 'Neuer Ordner' in der Sets-Gruppe (Root).
                    act_folder = menu.addAction("Neuer Ordner")
                    act_folder.triggered.connect(
                        lambda _=False, g=group:
                        self._on_new_folder(g, ""))
                    menu.addSeparator()
                    act_trash = menu.addAction("🗑️ Papierkorb öffnen...")
                    act_trash.triggered.connect(
                        lambda _=False: self.open_trash_requested.emit())
                else:
                    # 18.01.03: 'Neuer Ordner' auch in der Services-Gruppe
                    # (Root) – die uebrigen Struktur-Aktionen bleiben
                    # ausgegraut (_add_outside_set_actions).
                    act_folder = menu.addAction("Neuer Ordner")
                    act_folder.triggered.connect(
                        lambda _=False, g=group:
                        self._on_new_folder(g, ""))
                    menu.addSeparator()
                    self._add_outside_set_actions(menu, item)
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            if node_type == TYPE_SET:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                archived_set = bool(item.data(0, ROLE_ARCHIVED))
                # 05.08.2026: 'Alle Services ausführen' – gezielter Run des
                # Sets (kein globaler Massen-Scan); der Orchestrator zeigt
                # den Bestaetigungsdialog (Set + Symbol/Timeframe).
                # 20.04 (Q6): Archivierte Sets sind von Run/Struktur-Aktionen
                # ausgenommen (Archive Safety) – nur Loeschen bleibt aktiv.
                act_run = menu.addAction("▶️ Alle Services ausführen")
                act_run.setEnabled(not archived_set)
                act_run.triggered.connect(
                    lambda _=False, s=set_id:
                    self.run_set_requested.emit(s))
                menu.addSeparator()
                act_rename = menu.addAction("Set umbenennen")
                act_rename.setEnabled(not archived_set)
                act_rename.triggered.connect(
                    lambda _=False, s=set_id:
                    self.rename_set_requested.emit(s))
                act_add = menu.addAction("Service hinzufügen")
                act_add.setEnabled(not archived_set)
                act_add.triggered.connect(
                    lambda _=False, s=set_id:
                    self.add_set_service_requested.emit(s))
                menu.addSeparator()
                act_del = menu.addAction("Set löschen")
                act_del.triggered.connect(
                    lambda _=False, s=set_id:
                    self.delete_set_requested.emit(s))
                menu.addSeparator()
                act_purge = menu.addAction("Papierkorb löschen…")
                act_purge.triggered.connect(
                    lambda _=False: self.purge_trash_requested.emit())
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            if node_type == TYPE_SERVICE:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                service_id = str(item.data(0, ROLE_INSTANCE_ID) or "")
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                # 20.04 (Q1/Q9): instance_hash der Instanz (aus der Set-
                # Definition, ROLE_INSTANCE_HASH) – Grundlage von Data-Only-
                # Purge, Voll-Loeschung und Doc-Log.
                instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
                # 05.08.2026: 'Diesen Service ausführen' – gezielter Run des
                # Einzel-Services (inkl. Upstream-Abhaengigkeiten im Set);
                # der Orchestrator zeigt den Bestaetigungsdialog (Service +
                # Symbol/Timeframe).
                act_run = menu.addAction("▶️ Diesen Service ausführen")
                act_run.triggered.connect(
                    lambda _=False, s=set_id, i=service_id:
                    self.run_service_requested.emit(s, i))
                menu.addSeparator()
                act_up = menu.addAction("Order ▲")
                act_up.triggered.connect(
                    lambda _=False, s=set_id, i=service_id:
                    self.move_service_requested.emit(s, i, -1))
                act_down = menu.addAction("Order ▼")
                act_down.triggered.connect(
                    lambda _=False, s=set_id, i=service_id:
                    self.move_service_requested.emit(s, i, 1))
                menu.addSeparator()
                act_rem = menu.addAction("Service entfernen")
                act_rem.triggered.connect(
                    lambda _=False, s=set_id, i=service_id:
                    self.remove_service_requested.emit(s, i))
                act_info = menu.addAction("Service-Info anzeigen")
                act_info.triggered.connect(
                    lambda _=False, s=set_id, i=service_id, p=plugin_id:
                    self.info_requested.emit(s, i, p))
                # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung (Service-in-Set).
                # 'Als Variante duplizieren' erzeugt eine neue Instanz mit
                # kopierten Parametern (Q8); 'Doc Log bearbeiten' editiert
                # das Negativ-Wissen; 'Data Only Löschen' purgt NUR die
                # Feature-Daten (Q5); 'Vollständig Löschen' entfernt die
                # Instanz + Daten (2-stufige Sicherheitsabfrage).
                menu.addSeparator()
                act_variant = menu.addAction("Als Variante duplizieren")
                act_variant.triggered.connect(
                    lambda _=False, s=set_id, i=service_id, p=plugin_id,
                           h=instance_hash:
                    self.duplicate_variant_requested.emit(s, i, p, h))
                act_doclog = menu.addAction("Doc Log bearbeiten")
                act_doclog.triggered.connect(
                    lambda _=False, s=set_id, i=service_id, p=plugin_id,
                           h=instance_hash:
                    self.doc_log_requested.emit(s, i, p, h))
                menu.addSeparator()
                act_purge = menu.addAction("Data Only Löschen")
                act_purge.triggered.connect(
                    lambda _=False, s=set_id, i=service_id, p=plugin_id,
                           h=instance_hash:
                    self.data_only_purge_requested.emit(s, i, p, h))
                act_del = menu.addAction("Vollständig Löschen")
                act_del.triggered.connect(
                    lambda _=False, s=set_id, i=service_id, p=plugin_id,
                           h=instance_hash:
                    self.delete_complete_requested.emit(s, i, p, h))
                menu.addSeparator()
                act_purge = menu.addAction("Papierkorb löschen…")
                act_purge.triggered.connect(
                    lambda _=False: self.purge_trash_requested.emit())
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            # 20.04 (Q7): Clone-Zeile (Preset/Variante eines Plugin-Parents).
            # Der Run adressiert den Service ueber die plugin_id; archivierte
            # Clones sind von allen Aktionen ausgenommen (Archive Safety, Q6).
            if node_type == TYPE_CLONE:
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
                archived = bool(item.data(0, ROLE_ARCHIVED))
                menu = QMenu(self)
                act_run = menu.addAction("▶️ Diesen Service ausführen")
                act_run.setEnabled(not archived)
                act_run.triggered.connect(
                    lambda _=False, p=plugin_id, h=instance_hash:
                    self.run_plugin_requested.emit(p, h))
                menu.addSeparator()
                act_info = menu.addAction("Service-Info anzeigen")
                act_info.setEnabled(not archived)
                act_info.triggered.connect(
                    lambda _=False, p=plugin_id:
                    self.info_requested.emit("", "", p))
                # 20.04 (Q5/Q6/Q8): Preset-/Varianten-Verwaltung. Archivierte
                # Clones sind von den Bearbeitungs-/Lauf-Aktionen ausgenommen
                # (Archive Safety, Q6) – nur 'Vollständig Löschen' bleibt als
                # einzige Loesch-Option aktiv (Archiv-Einheit: einzelner Clone).
                menu.addSeparator()
                act_variant = menu.addAction("Als Variante duplizieren")
                act_variant.setEnabled(not archived)
                act_variant.triggered.connect(
                    lambda _=False, p=plugin_id, h=instance_hash:
                    self.duplicate_variant_requested.emit("", "", p, h))
                # 10.08.2026 (Bugfix): 'Variante umbenennen' – Fragt den
                # neuen Preset-Namen ab (Namensdialog im MasterTree) und
                # emittiert rename_variant_requested (Orchestrator persistiert).
                act_rename = menu.addAction("Variante umbenennen")
                act_rename.setEnabled(not archived)
                act_rename.triggered.connect(
                    lambda _=False, it=item:
                    self._on_rename_clone(it))
                act_doclog = menu.addAction("Doc Log bearbeiten")
                act_doclog.setEnabled(not archived)
                act_doclog.triggered.connect(
                    lambda _=False, p=plugin_id, h=instance_hash:
                    self.doc_log_requested.emit("", "", p, h))
                menu.addSeparator()
                act_purge = menu.addAction("Data Only Löschen")
                act_purge.setEnabled(not archived)
                act_purge.triggered.connect(
                    lambda _=False, p=plugin_id, h=instance_hash:
                    self.data_only_purge_requested.emit("", "", p, h))
                act_del = menu.addAction("Vollständig Löschen")
                act_del.triggered.connect(
                    lambda _=False, p=plugin_id, h=instance_hash:
                    self.delete_complete_requested.emit("", "", p, h))
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            # Plugin-Zeile (Services-Gruppe / Kategorie-Ordner):
            # 17.01.02 (Bugfix-Runde) – '▶️ Diesen Service ausführen' wie bei
            # den Set-Service-Zeilen (einzelner Run, Sicherheitsabfrage durch
            # den Orchestrator); 'Service-Info anzeigen' bleibt aktiv.
            if node_type == TYPE_PLUGIN:
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                menu = QMenu(self)
                act_run = menu.addAction("▶️ Diesen Service ausführen")
                act_run.triggered.connect(
                    lambda _=False, p=plugin_id:
                    self.run_plugin_requested.emit(p, ""))
                menu.addSeparator()
                act_info = menu.addAction("Service-Info anzeigen")
                act_info.triggered.connect(
                    lambda _=False, p=plugin_id:
                    self.info_requested.emit("", "", p))
                # 20.04 (Q8): 'Als Variante duplizieren' – erzeugt eine
                # Preset-Variante (indicator_presets) aus den aktuellen
                # Plugin-Parametern; der Plugin-Knoten wird zum Parent mit
                # Clone-Kindern (erste Variante eines flachen Blatts).
                menu.addSeparator()
                act_variant = menu.addAction("Als Variante duplizieren")
                act_variant.triggered.connect(
                    lambda _=False, p=plugin_id:
                    self.duplicate_variant_requested.emit("", "", p, ""))
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            # Sonstige Nicht-Set-Knoten (Gruppen der Services-Seite)
            self._add_outside_set_actions(menu, item)
            menu.exec(self.viewport().mapToGlobal(pos))
        except (RuntimeError, AttributeError):
            pass

    def _add_outside_set_actions(self, menu: QMenu, item) -> None:
        """Fuegt die ausgegrauten Struktur-Aktionen fuer Knoten ausserhalb
        eines Sets hinzu (Plugin-Zeilen sowie ⚡- und 📦-Gruppen). Bei
        Plugin-Zeilen bleibt 'Service-Info anzeigen' aktiv."""
        menu.addAction("Order ▲").setEnabled(False)
        menu.addAction("Order ▼").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Service entfernen").setEnabled(False)
        if item is not None and isValid(item) and \
                item.data(0, ROLE_NODE_TYPE) == TYPE_PLUGIN:
            menu.addSeparator()
            plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
            act_info = menu.addAction("Service-Info anzeigen")
            act_info.triggered.connect(
                lambda _=False, p=plugin_id:
                self.info_requested.emit("", "", p))

    # -------------------------------------------------------------------------
    # Bugfix 04.08.2026: '>'/'⌄'-Marker statt Branch-Dreiecke + Einfach-Klick
    # -------------------------------------------------------------------------

    def drawBranches(self, painter, rect, index) -> None:
        """Bewusst leerer Override: KEINE nativen Branch-Dreiecke.

        Die Auf-/Zuklapp-Markierung uebernimmt das Symbol vor dem Namen
        ('>' eingeklappt / '⌄' ausgeklappt, siehe _expandable_label und
        _refresh_expand_label). Dieser Override bleibt erhalten, damit Qt
        (auch bei rootIsDecorated=False) keine nativen Branch-Dreiecke
        zeichnet; die Einrueckung der Untereintraege (setIndentation) bleibt
        davon unberuehrt.
        """
        pass

    def _refresh_expand_label(self, item) -> None:
        """Setzt das Auf-/Zuklapp-Symbol ('>'/'⌄') auf den IST-Zustand.

        Bugfix 04.08.2026 (Punkt 2/3): Slot fuer itemExpanded/itemCollapsed.
        Blatt-Knoten (ohne Kinder) tragen kein Symbol.
        """
        if item is None or not isValid(item):
            return
        if item.childCount() <= 0:
            return
        text = item.text(0)
        prefix = "⌄ " if item.isExpanded() else "> "
        if text.startswith("> ") or text.startswith("⌄ "):
            item.setText(0, prefix + text[2:])
        else:
            item.setText(0, prefix + text)

    def mousePressEvent(self, event) -> None:
        """Bugfix 04.08.2026 (Punkt 4): Einfacher Klick togglet auf/zu.

        Ein einfacher Mausklick auf einen Knoten MIT Untereintraegen klappt
        den Knoten auf bzw. zu (gesamte Zeile = Klickzone, kein Zielen auf
        ein schmales Symbol noetig). Der Doppelklick togglet NICHT mehr
        (setExpandsOnDoubleClick(False)). Klicks auf Blatt-Knoten verhalten
        sich normal (Selektion). Das Symbol aktualisiert sich automatisch
        ueber itemExpanded/itemCollapsed (_refresh_expand_label).

        Erweiterung 15.03-E (Multi-Select): Klicks in die Checkbox-Zone
        (CHECKBOX_ZONE_WIDTH, linke Kante der Item-Zeile in Spalte 0) werden
        dem Qt-Default ueberlassen, damit die Checkbox togglet
        (itemChanged feuert); nur Klicks rechts der Zone togglen das
        Auf-/Zuklappen.

        Bugfix 06.08.2026 (Bugfix-Runde 3, Punkte 1-7): JEDER Mausklick auf
        eine gueltige Zeile emittiert `selection_details` (vor der
        Verzweigung, damit auch Checkbox-Zonen- und Expand-Klicks den
        Klick-Scope liefern) – das Read-Only-Panel des Dialogs folgt damit
        dem Klick, NICHT den Checkboxen.
        """
        try:
            pos = (event.position().toPoint() if hasattr(event, "position")
                   else event.pos())
            item = self.itemAt(pos)
            if item is None or not isValid(item):
                super().mousePressEvent(event)
                return
            # 18.01.03 (Drag & Drop): Quelle fuer einen beginnenden Drag
            # merken (nur linke Maustaste; startDrag wertet sie aus).
            self._drag_source = (
                item if event.button() == Qt.LeftButton else None)
            # Klick-Scope fuer das Read-Only-Panel (Bugfix 06.08.2026).
            self._emit_selection_details(item)
            # Checkbox-Klick hat Vorrang vor dem Expand-Toggle
            if self._checkable and (item.flags() & Qt.ItemIsUserCheckable):
                rect = self.visualItemRect(item)
                if pos.x() < rect.left() + CHECKBOX_ZONE_WIDTH:
                    super().mousePressEvent(event)
                    return
            if item.childCount() > 0:
                item.setExpanded(not item.isExpanded())
                # Selektierbare Knoten (Sets) trotzdem auswaehlen, damit die
                # Auswahl-API (current_set_id/current_service_id) funktioniert.
                if item.flags() & Qt.ItemIsSelectable:
                    self.setCurrentItem(item)
                event.accept()
                return
        except (RuntimeError, AttributeError):
            pass
        super().mousePressEvent(event)

    def _emit_selection_details(self, item) -> None:
        """Emittiert `selection_details` fuer die geklickte Zeile.

        Liefert die Zeilen-Daten (node_type, set_id, service_id, plugin_id)
        je Knotentyp – Service-Zeilen tragen alle vier Rollen, Set-Zeilen nur
        node_type+set_id, Plugin-Zeilen nur node_type+plugin_id (set_id ist
        hier bewusst leer, die ROLE_SET_ID haelt nur die Gruppenkennung),
        Gruppen-/sonstige Zeilen nur node_type. Der Dialog entscheidet aus
        diesem Scope, welche Parameter angezeigt werden.
        """
        if item is None or not isValid(item):
            return
        try:
            node_type = str(item.data(0, ROLE_NODE_TYPE) or "")
            set_id = ""
            service_id = ""
            plugin_id = ""
            if node_type == TYPE_SERVICE:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                service_id = str(item.data(0, ROLE_INSTANCE_ID) or "")
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
            elif node_type == TYPE_SET:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
            elif node_type == TYPE_PLUGIN:
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
            elif node_type == TYPE_CLONE:
                # 20.04 (Q7): Clone-Zeilen liefern plugin_id (feature_id)
                # im plugin_id-Slot; der instance_hash (Varianten-Key) wird
                # im service_id-Slot mitgeliefert (Info/Param-Panel).
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                service_id = str(item.data(0, ROLE_INSTANCE_HASH) or "")
            elif node_type == TYPE_CATEGORY:
                # 18.01.01 (E-4): Kategorie-Ordner liefern den VOLLEN
                # Kategorie-Pfad (z.B. 'Swing Points/Geometrie') im
                # plugin_id-Slot – Grundlage fuer die ID-Aufloesung im
                # AnalyticsWindow (Baum-Selektion -> set_feature_ids).
                # 18.01.03 (L3): Zusaetzlich wird die Eltern-GRUPPE
                # ('sets'/'plugins') im set_id-Slot geliefert, damit die
                # Aufloesung Sets-Ordner von Plugins-Ordnern unterscheiden
                # kann (Sets-Ordner -> category_set_ids -> Services).
                set_id = self._group_of(item)
                plugin_id = self._category_path_of(item)
            self.selection_details.emit(node_type, set_id, service_id,
                                        plugin_id)
        except (RuntimeError, AttributeError):
            pass

    # -------------------------------------------------------------------------
    # Selektion / Auswertung
    # -------------------------------------------------------------------------

    def current_selection(self) -> Dict[str, str]:
        """Liefert die aktuelle Auswahl als {"set_id": ..., "service_id": ...}.

        P15-Bugfix: isValid-Guard – bei wildem Klicken kann currentItem() auf
        ein durch clear() zerstoertes C++-Item zeigen; der Zugriff auf
        .data() wuerde sonst einen Access Violation (0xC0000005) ausloesen.
        """
        try:
            item = self.currentItem()
            if item is None or not isValid(item):
                return {"set_id": "", "service_id": ""}
            node_type = item.data(0, ROLE_NODE_TYPE)
            set_id = str(item.data(0, ROLE_SET_ID) or "")
            if node_type == TYPE_SERVICE:
                return {"set_id": set_id,
                        "service_id": str(item.data(0, ROLE_INSTANCE_ID) or "")}
            if node_type == TYPE_SET:
                return {"set_id": set_id, "service_id": ""}
            return {"set_id": "", "service_id": ""}
        except (RuntimeError, AttributeError):
            return {"set_id": "", "service_id": ""}

    def current_set_id(self) -> str:
        return self.current_selection().get("set_id", "")

    def current_service_id(self) -> str:
        return self.current_selection().get("service_id", "")

    def _emit_selection(self) -> None:
        sel = self.current_selection()
        try:
            self.selection_changed.emit(sel["set_id"], sel["service_id"])
        except (RuntimeError, AttributeError):
            pass

    def _restore_selection(self, previous: Dict[str, str]) -> None:
        """Stellt die Auswahl nach einem Refresh wieder her (sofern vorhanden).

        P15-Bugfix: setCurrentItem unter blockSignals (kein Signal-Sturm /
        keine Rekursion in _on_master_selection) + isValid-Guards gegen
        zerstoerte Items (Access-Violation-Schutz).
        """
        if not previous or not previous.get("set_id"):
            return
        target_id = previous.get("service_id") or previous.get("set_id")
        try:
            self.blockSignals(True)
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                svc_id = item.data(0, ROLE_INSTANCE_ID)
                set_id = item.data(0, ROLE_SET_ID)
                node_type = item.data(0, ROLE_NODE_TYPE)
                if (node_type == TYPE_SERVICE and svc_id == target_id
                        and set_id == previous.get("set_id")):
                    self.setCurrentItem(item)
                    break
                if (node_type == TYPE_SET and set_id == target_id
                        and not previous.get("service_id")):
                    self.setCurrentItem(item)
                    break
        finally:
            self.blockSignals(False)

    # -------------------------------------------------------------------------
    # 20.04 (Q8-Bugfix): Programmgesteuerte Selektion nach dem Duplizieren –
    # 'Als Variante duplizieren' muss ein SICHTBARES Ergebnis liefern. Die
    # neuen Instanzen/Clones werden expandiert (Eltern-Kette), selektiert und
    # in den sichtbaren Bereich gescrollt (unter blockSignals, kein Signal-
    # Sturm auf _on_master_selection).
    # -------------------------------------------------------------------------

    def select_instance(self, set_id: str, service_id: str) -> bool:
        """Selektiert eine Service-Instanz (TYPE_SERVICE) im Baum."""
        return self._select_by(lambda it: (
            it.data(0, ROLE_NODE_TYPE) == TYPE_SERVICE
            and str(it.data(0, ROLE_SET_ID) or "") == str(set_id)
            and str(it.data(0, ROLE_INSTANCE_ID) or "") == str(service_id)))

    def select_clone(self, plugin_id: str, instance_hash: str) -> bool:
        """Selektiert einen Clone-Knoten (TYPE_CLONE, Preset/Variante)."""
        return self._select_by(lambda it: (
            it.data(0, ROLE_NODE_TYPE) == TYPE_CLONE
            and str(it.data(0, ROLE_PLUGIN_ID) or "") == str(plugin_id)
            and str(it.data(0, ROLE_INSTANCE_HASH) or "") == str(instance_hash)))

    def _select_by(self, predicate) -> bool:
        """Iterator + Prädikat: expandieren, selektieren, scrollen."""
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                try:
                    if not predicate(item):
                        continue
                    self._expand_ancestors(item)
                    self.blockSignals(True)
                    try:
                        self.setCurrentItem(item)
                        self.scrollToItem(item)
                    finally:
                        self.blockSignals(False)
                    return True
                except (RuntimeError, AttributeError):
                    continue
        except (RuntimeError, AttributeError):
            pass
        return False


class TreeItemIterator:
    """Leichter Iterator ueber alle QTreeWidgetItems (rekursiv, depth-first).

    P15-Bugfix: isValid-Guard im __next__ – Items koennen zwischen Sammlung
    und Iteration C++-seitig zerstoert werden (clear() bei data_changed).
    """

    def __init__(self, tree: QTreeWidget) -> None:
        self._items: list = []
        try:
            for i in range(tree.topLevelItemCount()):
                self._collect(tree.topLevelItem(i))
        except (RuntimeError, AttributeError):
            self._items = []
        self._index = 0

    def _collect(self, item: Optional[QTreeWidgetItem]) -> None:
        if item is None or not isValid(item):
            return
        self._items.append(item)
        try:
            for i in range(item.childCount()):
                self._collect(item.child(i))
        except (RuntimeError, AttributeError):
            pass

    def __iter__(self):
        self._index = 0
        return self

    def __next__(self) -> Optional[QTreeWidgetItem]:
        if self._index >= len(self._items):
            raise StopIteration
        item = self._items[self._index]
        self._index += 1
        if item is None or not isValid(item):
            return None
        return item

```

--------------------------------------------------

### DATEI: serviceui/new_set_dialog.py
```py
# serviceui/new_set_dialog.py
"""
Service-UI: Dialog zum Anlegen neuer Service-Sets (Bugfix 05.08.2026).

Einfache Bedienung: ein Namensfeld + eine Indikator-Auswahl. Wird ein
Indikator gewaehlt, legt der Aufrufer (ServiceWindow._on_add_set) die
Basis-Services des Indikators (service_plugin_ids, z.B. grid_lines +
proximity) automatisch im neuen Set an – das Set ist damit sofort gueltig
fuer den Indikator.

Reine UI-Klasse (SRP): kein SQL, kein Repository-Zugriff – die Indikator-
Liste wird vom Aufrufer als Daten uebergeben.
"""

from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QMessageBox, QVBoxLayout, QWidget,
)


class NewServiceSetDialog(QDialog):
    """Namens- + Indikator-Auswahl fuer ein neues Service-Set."""

    def __init__(self, indicators: List[Dict[str, Any]],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neues Service-Set anlegen")

        self.edit_name = QLineEdit(self)
        self.edit_name.setPlaceholderText("Name (z.B. 'Grid Basis')")

        self.combo_indicator = QComboBox(self)
        self.combo_indicator.addItem("(kein Indikator)", None)
        for info in indicators:
            ind_id = str(info.get("indicator_id") or "")
            if not ind_id:
                continue
            label = str(info.get("display_name") or ind_id)
            self.combo_indicator.addItem(label, ind_id)

        form = QFormLayout()
        form.addRow("Name:", self.edit_name)
        form.addRow("Indikator:", self.combo_indicator)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Validierung & Ergebnis-API
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        """OK: Name ist Pflicht (Bugfix 05.08.2026 – 'ein neuer Name soll
        eingegeben werden'). Leerer Name bleibt im Dialog offen."""
        if not self.edit_name.text().strip():
            QMessageBox.warning(
                self, "Name fehlt",
                "Bitte einen Namen für das neue Service-Set eingeben.")
            return
        self.accept()

    def result_name(self) -> str:
        """Der eingegebene Set-Name (getrimmt)."""
        return self.edit_name.text().strip()

    def result_indicator_id(self) -> str:
        """Die gewaehlte Indikator-ID ('' = kein Indikator)."""
        return str(self.combo_indicator.currentData() or "")

```

--------------------------------------------------

### DATEI: serviceui/param_columns.py
```py
# serviceui/param_columns.py
"""
Service-UI: Parameter-Column-Builder (dynamische Service-Spalten).

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert –
Verhalten unverändert. Als Mixin, damit die Host-Klasse (ServiceWindow)
weiterhin direkt `self._build_service_columns(...)` etc. aufrufen kann.

Die Methoden greifen auf Host-Attribute zurück, die zur Laufzeit vorhanden
sind: service_columns_layout, _service_param_controls, _service_desc_controls,
widget_service_columns, combo_symbol, combo_tf, _symbol_precision,
collect_set_definition(), _schedule_reflow (ContentScrollMixin),
_service_lock/_build_tooltip (ServiceWindow).
"""

from typing import Any, Dict, List, Tuple

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtGui import QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget,
)


class ServiceParamColumnsMixin:
    """Baut die dynamischen Service-Spalten (Roadmap 5.4.2.2).

    Für jede instance_id in execution_order wird eine QGroupBox-Spalte im
    service_columns_layout erzeugt. Jede Spalte skaliert in der Höhe exakt
    mit der Anzahl ihrer Parameter (QSizePolicy.Maximum); die Fensterbreite
    wächst mit der Anzahl der Spalten nach rechts – ohne leeren Raum und
    ohne fixe Pixelwerte.
    """

    @staticmethod
    def _is_visual_key(key: str) -> bool:
        """Konvention für reine Darstellungs-Props: Sichtbarkeit (show_*) + Farben (color).

        Darstellungs-Parameter gehören NICHT ins Service-Set (nur Berechnungs-
        Logik, Roadmap 5.4.1.2) und werden daher in den Service-Spalten
        ausgeblendet (konsistent zum Indikator-Dialog).
        """
        if key.startswith("show_"):
            return True
        if "color" in key.lower():
            return True
        return False

    @staticmethod
    def _human(key: str) -> str:
        return key.replace("_", " ").title()

    @staticmethod
    def _decimal_places(value: Any) -> int:
        """Nachkommastellen eines float (für QDoubleSpinBox.setDecimals)."""
        if not isinstance(value, float) or value != value:  # NaN-Schutz
            return 4
        s = f"{value:.10f}".rstrip("0")
        if "." in s:
            return len(s.split(".")[1])
        return 0

    def _get_symbol_precision(self) -> int:
        """USER-REQ: Preisskala-Praezision (fix je Symbol) fuer die 6
        Custom-Level-Eingabefelder. Lazy ermittelt (db_service.get_symbol_
        precision) und fuer die Fenster-Instanz gecacht – kein DB-Zugriff
        bei jedem Spalten-Neuaufbau."""
        if self._symbol_precision is None:
            try:
                from db_service import get_symbol_precision
                symbol = (self.combo_symbol.currentText()
                          if self.combo_symbol else "SILVER")
                timeframe = (self.combo_tf.currentText()
                             if self.combo_tf else "H1")
                self._symbol_precision = get_symbol_precision(symbol, timeframe)
            except Exception:
                self._symbol_precision = 2
        return self._symbol_precision

    def _create_param_control(self, key: str, val: Any, spec: Dict[str, Any]) -> QWidget:
        """Erzeugt ein Eingabe-Widget exakt aus dem ParameterSchema.

        float -> QDoubleSpinBox, int -> QSpinBox, bool -> QCheckBox,
        choice -> QComboBox, color/str -> QLineEdit. min/max/step werden 1:1
        übertragen (Roadmap 5.4.2.2).

        17.01.05 (Bugfix, UI-Dropdown-Extension): Deklariert der Schema-
        Eintrag `options` (Liste/Tupel), wird VOR der Datentyp-Prüfung eine
        QComboBox gerendert – unabhängig vom type-Wert ("str"/"choice").
        Dadurch werden z. B. die mode-/ma_type-/period_extrema_type-Felder
        der Swing-Services (type="str" + options) als Dropdown statt als
        QLineEdit angezeigt.
        """
        options = spec.get("options")
        if options and isinstance(options, (list, tuple)):
            combo = QComboBox()
            combo.addItems([str(o) for o in options])
            val_str = str(val if val is not None else spec.get("default", ""))
            idx = combo.findText(val_str)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            return combo
        p_type = spec.get("type")
        if p_type == "float":
            spin = QDoubleSpinBox()
            spin.setRange(float(spec.get("min", -1e9)), float(spec.get("max", 1e9)))
            step = spec.get("step")
            decimals = self._decimal_places(step) if step is not None else self._decimal_places(spec.get("default"))
            # USER-REQ: Custom-Levels (prox_level1..6) nutzen die Preisskala-
            # Praezision (fix je Symbol). MUSS vor setValue geschehen, sonst
            # rundet QDoubleSpinBox den Wert auf die Schema-Default-Digits.
            if key.startswith("prox_level"):
                decimals = self._get_symbol_precision()
            spin.setDecimals(min(6, max(0, decimals)))
            spin.setSingleStep(float(step) if step is not None else 0.01)
            try:
                spin.setValue(float(val))
            except (TypeError, ValueError):
                spin.setValue(float(spec.get("default", 0.0)))
            return spin
        if p_type == "int":
            spin = QSpinBox()
            spin.setRange(int(spec.get("min", -100000)), int(spec.get("max", 100000)))
            spin.setSingleStep(int(spec.get("step", 1)))
            try:
                spin.setValue(int(val))
            except (TypeError, ValueError):
                spin.setValue(int(spec.get("default", 0)))
            return spin
        if p_type == "bool":
            chk = QCheckBox()
            chk.setChecked(bool(val))
            return chk
        if p_type == "choice":
            combo = QComboBox()
            combo.addItems([str(o) for o in (spec.get("options") or [])])
            combo.setCurrentText(str(val))
            return combo
        txt = QLineEdit()
        txt.setText(str(val))
        return txt

    @staticmethod
    def _ctrl_value(ctrl: QWidget) -> Any:
        """Liest den aktuellen Wert eines Controls typsicher aus."""
        if isinstance(ctrl, QCheckBox):
            return ctrl.isChecked()
        if isinstance(ctrl, QSpinBox):
            return ctrl.value()
        if isinstance(ctrl, QDoubleSpinBox):
            return ctrl.value()
        if isinstance(ctrl, QComboBox):
            return ctrl.currentText()
        return ctrl.text()

    @staticmethod
    def _scroll_textedit_top(editor: QTextEdit) -> None:
        """Scrollt eine Read-Only-QTextEdit HART nach oben (Cursor + Scroll).

        Qt setzt nach `setHtml` den Text-Cursor intern ans Dokument-ENDE und
        scrollt beim finalen Layout dorthin – dadurch ist die erste Zeile
        verdeckt. Fix (17.01.06):
          1. Cursor ans Dokument-Anfang (`QTextCursor.MoveOperation.Start`).
          2. Vertikalen Scrollbalken erst auf Maximum setzen (erzwingt die
             Neuberechnung des Viewports) und dann auf 0 (ganz oben).
        Wirkt nur dauerhaft, wenn es NACH dem endgueltigen Layout/Resize
        ausgefuehrt wird (Qt wrappt das Dokument nach setHtml erst in einer
        spaeteren Event-Loop-Runde um und scrollt dann ggf. erneut).
        """
        if editor is None:
            return
        try:
            cur = editor.textCursor()
            cur.setPosition(0)
            editor.setTextCursor(cur)
            editor.moveCursor(QTextCursor.MoveOperation.Start)
            sb = editor.verticalScrollBar()
            if sb is not None:
                sb.setValue(sb.maximum())  # unten -> Viewport neu berechnen
                sb.setValue(0)             # ganz nach oben (erste Zeile)
            editor.ensureCursorVisible()
        except (RuntimeError, AttributeError):
            pass  # Widget bereits zerstoert (deleteLater) – ignorieren

    # ------------------------------------------------------------------
    # 17.01.05 (Bugfix): Conditional Visibility (Modus-abhaengige Parameter)
    # ------------------------------------------------------------------
    def _apply_conditional_visibility(self, iid: str) -> None:
        """Blendet Parameter mit `visible_when`-Schema-Deklaration ein/aus.

        Konvention (additiv, 17.01.05): Ein Parameter-Schema-Eintrag kann
        zusaetzlich tragen:
            "visible_when": {"mode": ["Algo_A", "Algo_B"]}
        (auch einzelner String erlaubt). Liegt der aktuelle Wert des
        `mode`-Controls (Dropdown) NICHT in der Liste, werden Control + Label
        ausgeblendet; sonst eingeblendet. Parameter ohne `visible_when`
        bleiben immer sichtbar. Wird beim Spaltenaufbau und bei jedem
        Mode-Wechsel aufgerufen.
        """
        schema = getattr(self, "_mode_schemas", {}).get(iid)
        if not schema:
            return
        mode_ctrl = self._service_param_controls.get((iid, "mode"))
        mode_val = (str(self._ctrl_value(mode_ctrl))
                    if mode_ctrl is not None else "")
        # Bugfix (Mode-Wechsel): Spalten (QGroupBox), deren Controls durch
        # die Ein-/Ausblendung beruehrt wurden – deren Geometrie-Caches werden
        # NACH der Sichtbarkeits-Aenderung invalidiert (s. u.).
        touched_cols: set = set()
        for key, spec in schema.items():
            vw = spec.get("visible_when")
            if not isinstance(vw, dict) or "mode" not in vw:
                continue
            allowed = vw["mode"]
            if isinstance(allowed, str):
                allowed = [allowed]
            visible = mode_val in {str(a) for a in allowed}
            ctrl = self._service_param_controls.get((iid, key))
            if ctrl is None:
                continue
            try:
                ctrl.setVisible(visible)
            except (RuntimeError, AttributeError):
                pass
            col = ctrl.parentWidget()
            if col is not None:
                touched_cols.add(col)
            lbl = getattr(self, "_service_param_labels", {}).get((iid, key))
            if lbl is not None:
                try:
                    lbl.setVisible(visible)
                except (RuntimeError, AttributeError):
                    pass
        # 17.01.05 (Bugfix): Auch das Info-Label (Service-/Algo-Beschreibung)
        # auf den aktuellen Modus aktualisieren.
        self._update_service_info_label(iid)
        # Bugfix (Mode-Wechsel, Hoehe der Box): Nach dem Ein-/Ausblenden der
        # modus-abhaengigen Parameter muss die BOX-HOEHE der neuen Parameter-
        # zahl folgen (nicht die Hoehe der Einzelfelder). Qt 6.11 cached den
        # QWidgetItemV2-sizeHint – ohne updateGeometry()/Re-Indexierung bleibt
        # die alte Hoehe stehen und der QFormLayout streckt die verbliebenen
        # Zeilen (gestreckte Einzelfelder). Daher werden die Caches der
        # betroffenen Spalten + der Service-Parameter-Box invalidiert.
        #
        # 07.08.2026 (User-Anweisung): KEIN self._reflow() mehr – der volle
        # Reflow (_schedule_reflow -> _apply_reflow_size ->
        # resize_to_clamped_content, _exact_fit_to_content) wuerde die
        # FENSTERHOEHE an die neue Box-Hoehe anpassen und damit den gesamten
        # Canvas + die Fensterhoehe versetzen. Gewuenscht: NUR die Box wird
        # auf ihre Layout-Groesse gesetzt; ist sie zu hoch, zeigt die
        # ContentScrollArea (_param_scroll) Scrollbalken (Original-Spezifika-
        # tion Punkt 5). Der Baum (links) behaelt seine Hoehe und scrollt
        # selbst (User-Anweisung Punkt 3).
        try:
            for col in touched_cols:
                col.updateGeometry()
            box = getattr(self, "widget_service_columns", None)
            if box is not None:
                box.updateGeometry()
            QTimer.singleShot(0, self._resize_param_box_deferred)
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # 17.01.05 (Bugfix): Read-only Info-Label unter dem individuellen
    # Beschreibungsfeld – zeigt die in der Definition vorgefuellte
    # Service-Beschreibung + die Beschreibung des aktuell gewaehlten
    # Algorithmus (mode) an. Wird beim Spaltenaufbau und bei jedem
    # Mode-Wechsel aktualisiert.
    # ------------------------------------------------------------------
    def _update_service_info_label(self, iid: str) -> None:
        """Setzt den Rich-Text des Info-Labels fuer eine Service-Instanz.

        Angezeigt werden (read-only, unter dem editierbaren Beschreibungs-
        Feld): display_name/plugin_id, die Service-Beschreibung aus den
        Plugin-Metadaten (description_long, sonst description) sowie der
        aktuell gewaehlte Algorithmus (mode) inkl. Schema-Beschreibung.
        """
        label = getattr(self, "_service_info_labels", {}).get(iid)
        if label is None:
            return
        pid = getattr(self, "_service_info_pids", {}).get(iid, iid)
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(pid)
        except (KeyError, AttributeError):
            plugin = None
        meta = dict(getattr(plugin, "metadata", None) or {})
        display = str(meta.get("display_name") or pid)
        desc = str(meta.get("description_long")
                   or meta.get("description") or "").strip()
        schema = getattr(self, "_mode_schemas", {}).get(iid, {})
        mode_spec = schema.get("mode", {}) if isinstance(schema, dict) else {}
        mode_ctrl = self._service_param_controls.get((iid, "mode"))
        mode_val = (str(self._ctrl_value(mode_ctrl)) if mode_ctrl is not None
                    else str(mode_spec.get("default") or ""))
        labels = dict(getattr(plugin, "param_labels", None) or {})
        mode_label = str(labels.get("mode")
                         or mode_spec.get("description") or "Algorithmus")
        mode_desc = str(mode_spec.get("description") or "")

        import html as _html
        parts = [f"<b>{_html.escape(display)}</b>"]
        if desc:
            parts.append(_html.escape(desc))
        if mode_val:
            parts.append(f"<b>{_html.escape(mode_label)}:</b> "
                         f"{_html.escape(mode_val)}")
        if mode_desc and mode_desc != mode_label:
            parts.append(f"<i>{_html.escape(mode_desc)}</i>")

        try:
            # QTextEdit (read-only): HTML setzen – bei langem Text scrollt
            # die Anzeige vertikal (max. Hoehe gedeckelt).
            label.setHtml("<br>".join(parts))
            # 17.01.06 (Bugfix): Nach dem Text-Update die Anzeige IMMER ganz
            # nach oben scrollen (Cursor->Start + Scrollbar->0). Synchrone
            # Ausfuehrung + DEFERRED (QTimer singleShot 0): Qt setzt nach
            # setHtml den Cursor ans Dokument-Ende und wrappt das Dokument
            # erst in einer spaeteren Event-Loop-Runde um (dann scrollt es
            # ggf. erneut zum Cursor). Der deferred Reset wirkt daher erst
            # nach dem finalen Layout; zusaetzlich wird der Reset nach dem
            # finalen Box-Resize in _resize_param_box_deferred ausgefuehrt.
            self._scroll_textedit_top(label)
            QTimer.singleShot(
                0, lambda l=label: self._scroll_textedit_top(l))
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # 20.03 (Bugfix): Feld-Beschreibung eines Resultatfelds (Output-Schema)
    # in einem kleinen modalen Dialog anzeigen (i-Button in der Sektion
    # 'Resultatfelder (Output-Schema)' der Service-Spalte).
    # ------------------------------------------------------------------
    def _show_output_field_info(self, field_name: str, field_type: str,
                                description: str, plugin_id: str) -> None:
        """Zeigt Name, Typ und Beschreibung eines Output-Schema-Felds an.

        Kleiner QDialog (modal, keine Bearbeitung – rein informativ),
        konsistent zur Read-only-Natur des Output-Schemas (Kapitel 20.03).

        20.03.01 (Bugfix): Der Mixin-Host ist nicht IMMER ein QWidget
        (ServiceWindow ja; _DialogParamHost ist ein Plain-Object mit
        `_dialog`-Referenz auf das echte Dialog-Fenster). `QDialog(self)`
        wirft daher im Dialog-Kontext einen TypeError. Eltern-Widget wird
        robust aufgeloest: `self`, sonst `self._dialog`, sonst None.
        """
        try:
            parent = (self if isinstance(self, QWidget)
                      else getattr(self, "_dialog", None))
            if not isinstance(parent, QWidget):
                parent = None
            dlg = QDialog(parent)
            dlg.setWindowTitle(f"Resultatfeld: {field_name}")
            dlg.setModal(True)
            dvl = QVBoxLayout(dlg)
            head = QLabel(f"<b>{field_name}</b>  <i>({field_type})</i>")
            dvl.addWidget(head)
            if description:
                desc = QLabel(description)
                desc.setWordWrap(True)
                dvl.addWidget(desc)
            if plugin_id:
                note = QLabel(f"Service: {plugin_id}")
                note.setStyleSheet("color: #999; font-size: 10px;")
                dvl.addWidget(note)
            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            ok_btn = QPushButton("OK")
            ok_btn.setDefault(True)
            ok_btn.clicked.connect(dlg.accept)
            btn_row.addWidget(ok_btn)
            dvl.addLayout(btn_row)
            dlg.exec()
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # 20.03.02 (UI-Umbau, F6): Sammel-Info aller Resultatparameter einer
    # Service-Instanz in einem kompakten Info-Window. Der einzelne
    # (i)-Button hinter '📊 Resultatfelder:' ersetzt die bisherigen
    # Per-Zeilen-i-Buttons (User-Req). Technische Felder (`technical:
    # True`) werden UNTERHALB der Haupt-Resultatfelder in einer separaten,
    # kleineren Sektion '🔧 System-Metriken' gerendert.
    # ------------------------------------------------------------------
    def _show_output_params_info(self, plugin_id: str) -> None:
        """Zeigt ALLE Output-Parameter einer Service-Instanz an (20.03.02).

        Haupt-Resultatfelder mit Typ + Beschreibung; Felder mit
        `"technical": True` im `output_schema` in separater, kleinerer
        Sektion `🔧 System-Metriken` (F6). Modaler QDialog (read-only),
        Eltern-Widget robust aufgeloest (Bugfix b772c93: `self` falls
        QWidget, sonst `self._dialog`, sonst None).
        """
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except (KeyError, AttributeError):
            plugin = None
        schema = dict(getattr(plugin, "output_schema", None) or {})
        if not schema:
            return
        try:
            parent = (self if isinstance(self, QWidget)
                      else getattr(self, "_dialog", None))
            if not isinstance(parent, QWidget):
                parent = None
            dlg = QDialog(parent)
            dlg.setWindowTitle(f"Resultatfelder – {plugin_id}")
            dlg.setModal(True)
            dlg.setMinimumWidth(420)
            dvl = QVBoxLayout(dlg)

            main_fields: List[Tuple[str, Dict[str, Any]]] = []
            tech_fields: List[Tuple[str, Dict[str, Any]]] = []
            for fname, fspec in schema.items():
                fspec = fspec or {}
                if fspec.get("technical"):
                    tech_fields.append((fname, fspec))
                else:
                    main_fields.append((fname, fspec))

            for fname, fspec in main_fields:
                ftype = str(fspec.get("type") or "")
                fdesc = str(fspec.get("description") or "")
                head = QLabel(f"<b>{fname}</b>  <i>({ftype})</i>")
                dvl.addWidget(head)
                if fdesc:
                    desc = QLabel(fdesc)
                    desc.setWordWrap(True)
                    desc.setStyleSheet("color: #555;")
                    dvl.addWidget(desc)

            if tech_fields:
                sep = QLabel("<hr>")
                dvl.addWidget(sep)
                tech_head = QLabel("🔧 System-Metriken")
                tech_head.setStyleSheet(
                    "color: #888; font-size: 11px; font-weight: bold;")
                dvl.addWidget(tech_head)
                for fname, fspec in tech_fields:
                    ftype = str(fspec.get("type") or "")
                    fdesc = str(fspec.get("description") or "")
                    line = f"<b>{fname}</b> <i>({ftype})</i>"
                    if fdesc:
                        line += f" – {fdesc}"
                    tech_lbl = QLabel(line)
                    tech_lbl.setWordWrap(True)
                    tech_lbl.setStyleSheet("color: #999; font-size: 10px;")
                    dvl.addWidget(tech_lbl)

            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            ok_btn = QPushButton("OK")
            ok_btn.setDefault(True)
            ok_btn.clicked.connect(dlg.accept)
            btn_row.addWidget(ok_btn)
            dvl.addLayout(btn_row)
            dlg.exec()
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # Phase 15 (Dirty-State): Aenderungs-Tracking der Parameter-Controls
    # ------------------------------------------------------------------
    def _connect_param_change(self, ctrl: QWidget, iid: str, key: str) -> None:
        """Verbindet das Aenderungs-Signal eines Parameter-Controls mit dem
        Dirty-State-Tracking (valueChanged/textChanged/toggled).

        Jede Aenderung aktualisiert die ServiceSetDefinition im RAM
        (_current_set_definition) und markiert die instance_id im MasterTree
        als ungespeichert ('*' am Service-Knoten).
        """
        if isinstance(ctrl, QCheckBox):
            ctrl.toggled.connect(
                lambda _v, i=iid, k=key: self._on_param_changed(i, k))
        elif isinstance(ctrl, (QSpinBox, QDoubleSpinBox)):
            ctrl.valueChanged.connect(
                lambda _v, i=iid, k=key: self._on_param_changed(i, k))
        elif isinstance(ctrl, QComboBox):
            ctrl.currentTextChanged.connect(
                lambda _v, i=iid, k=key: self._on_param_changed(i, k))
        else:  # QLineEdit (color/str)
            ctrl.textChanged.connect(
                lambda _t, i=iid, k=key: self._on_param_changed(i, k))

    def _on_param_changed(self, iid: str, key: str) -> None:
        """Aktualisiert die RAM-ServiceSetDefinition und markiert die
        Instanz als dirty ('*' im MasterTree)."""
        ctrl = self._service_param_controls.get((iid, key))
        if ctrl is None:
            return
        value = self._ctrl_value(ctrl)
        # RAM-Definition der geladenen ServiceSetDefinition aktualisieren
        # (lookback ist eine Instanz-Einstellung, alle anderen gehoeren in
        # params; Phase 15 Dirty-State).
        definition = getattr(self, "_current_set_definition", None)
        if definition is not None:
            cfg = (definition.get("services") or {}).get(iid)
            if isinstance(cfg, dict):
                if key == "lookback":
                    cfg["lookback"] = value
                else:
                    cfg.setdefault("params", {})[key] = value
        self._mark_service_dirty(iid)

    def _mark_service_dirty(self, iid: str) -> None:
        """Versieht den Service-Knoten im MasterTree mit einem '*' (und
        merkt den Dirty-Zustand fuer Baum-Neuaufbauten).

        Bugfix 05.08.2026 (Punkt 2): Blendet zusaetzlich die Speicher-
        Buttons der Parameter-Spalte ein (_set_param_actions_visible im
        Orchestrator) - eine manuelle Parameter-Aenderung macht das
        Speichern erst noetig/sichtbar.
        """
        try:
            self._set_param_actions_visible(True)
        except (RuntimeError, AttributeError):
            pass
        selector = getattr(self, "service_selector", None)
        tree = getattr(selector, "master_tree", None)
        if tree is None or not iid:
            return
        try:
            tree.set_instance_dirty(iid, True)
        except (RuntimeError, AttributeError):
            pass

    def _setup_collapsible(self, group: QGroupBox) -> None:
        """Macht eine ausklappbare QGroupBox wirklich kollabierbar.

        Beim Abwählen werden die Kinder ausgeblendet und die Box-Hoehe per
        deferred Box-Resize angepasst; die ScrollArea (_param_scroll) zeigt
        bei Ueberhoehe Scrollbalken. Zusaetzlich wird group.updateGeometry()
        gerufen, damit der gecachte QWidgetItemV2-sizeHint der Box invalidiert
        wird (Qt 6.11: Layouts refreshen diesen Cache sonst NICHT).

        07.08.2026 (User-Anweisung): Frueher lief hier self._reflow() (voller
        Fenster-Reflow) – dadurch wurde die FENSTERHOEHE an die Box angepasst.
        Gewuenscht: NUR die Box resizen, Fenster-/Canvas-Hoehe bleibt stabil
        (Original-Spezifikation: ScrollArea aktiviert bei Ueberhoehe einen
        Scrollbalken; der Baum scrollt selbst).
        """
        def _toggle(checked: bool) -> None:
            for child in group.findChildren(QWidget):
                child.setVisible(checked)
            group.updateGeometry()  # QWidgetItemV2-Cache invalidieren (s. oben)
            QTimer.singleShot(0, self._resize_param_box_deferred)
        group.toggled.connect(_toggle)
        _toggle(group.isChecked())

    def _reflow(self) -> None:
        """Erzwingt die Neuberechnung der Layouts (dynamische Höhe/Breite).

        Qt 6.11: QWidgetItemV2 cached den sizeHint eines Widgets beim ersten
        Zugriff und aktualisiert ihn NICHT, wenn der Inhalt später wächst –
        selbst layout.invalidate() hilft nicht. Daher werden die Caches der
        betroffenen Widgets explizit per updateGeometry() invalidiert
        (invalidateSizeCache) und die Layout-Caches geleert.

        WICHTIG: Die Fenstergröße wird DEFERRED (nächste Event-Loop-Runde)
        angepasst. Beim Set-Wechsel sind die alten Service-Spalten per
        deleteLater() noch im Widget-Baum; bis sie zerstört sind, melden die
        Layout-Caches einen veralteten (zu kleinen) sizeHint (z.B. 18x18 für
        eine volle Spalten-Zeile). Ein synchrones resize würde das Fenster
        daher fälschlich schrumpfen. _schedule_reflow() zerstört die
        deleteLater-Widgets und berechnet die Größe erst aus dem konsistenten
        Zustand (ContentScrollMixin).

        Zusatz (Layout-Runde 2, 05.08.2026): Die Service-Parameter-Box liegt
        in einer ContentScrollArea mit widgetResizable=False – die ScrollArea
        resizet das Widget NICHT automatisch. Die Box wird daher DEFERRED
        (nach dem Zerstören der deleteLater-Altspalten) auf ihre aktuelle
        Layout-Größe gesetzt, damit die ScrollArea Scrollbalken anzeigen
        kann, sobald die Box das max. Format übersteigt (Punkt 5).
        """
        self._schedule_reflow()
        QTimer.singleShot(0, self._resize_param_box_deferred)

    def _resize_param_box_deferred(self) -> None:
        """Setzt die Service-Parameter-Box (in der ContentScrollArea) DEFERRED
        auf ihre aktuelle Layout-Größe.

        Muss NACH dem Zerstören der per deleteLater() markierten Alt-Spalten
        laufen – ein synchrones resize in _reflow() würde den veralteten
        QWidgetItemV2-sizeHint (18x18 für ein gerade geleertes Layout) lesen
        und die Box auf 18x18 schrumpfen (Bugfix 05.08.2026, Punkt 5).
        """
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        except (RuntimeError, AttributeError):
            pass
        box = getattr(self, "widget_service_columns", None)
        if box is None or box.layout() is None:
            return
        try:
            box.updateGeometry()
            # 11.08.2026 (Bugfix Runde 17c, User-Meldung 5): Bei einer
            # _param_scroll mit widgetResizable=True streckt die ScrollArea
            # die Box automatisch auf den Viewport – ein manuelles resize auf
            # die Layout-Groesse wuerde sie wieder zuruecksetzen. NUR bei
            # widgetResizable=False (Alt-Verhalten) wird die Box weiterhin
            # explizit auf ihre Layout-Groesse gesetzt. _DialogParamHost hat
            # keinen _param_scroll -> resize bleibt aktiv (Layout streckt).
            scroll = getattr(self, "_param_scroll", None)
            if scroll is None or not scroll.widgetResizable():
                box.resize(box.layout().sizeHint())
            if scroll is not None:
                scroll.updateGeometry()
            # Bugfix 05.08.2026 (Punkt 1): Der QSplitter fixiert die
            # Spaltengroessen beim addWidget (VOR dem Spaltenaufbau) und
            # aktualisiert sie nicht, wenn die sizeHints danach wachsen
            # (Qt-Quirk, analog QWidgetItemV2). Nach dem Spaltenaufbau wird
            # die Param-Spalte auf ihre aktuelle Layout-Breite gesetzt, damit
            # 2 Services nebeneinander ohne horizontalen Scroll passen.
            splitter = getattr(self, "main_splitter", None)
            # 05.08.2026 (Layout-Runde 3): ZWEI-SPALTEN-Splitter seit der
            # Phase-13-Bereinigung – der deferred setSizes greift erst mit
            # count() == 2 (vorher 3 -> stale Spaltengroessen nach dem
            # Spaltenaufbau, Bugfix Punkt 1).
            if splitter is not None and splitter.count() == 2:
                hints = []
                for i in range(splitter.count()):
                    w = splitter.widget(i)
                    if w is not None:
                        hints.append(w.sizeHint().width())
                if hints:
                    # 10.08.2026 (Bugfix, Slider): setSizes nur WACHSEN -
                    # eine vom Anwender verschobene Splitter-Position darf
                    # ein Param-Box-Rebuild nicht zuruecksetzen. Wird der
                    # Inhalt breiter als das aktuelle Panel, waechst das
                    # Panel auf den Bedarf (Tree-Breite bleibt).
                    current = splitter.sizes()
                    if not current or sum(current) <= 0:
                        splitter.setSizes(hints)
                    elif hints[1] > current[1]:
                        splitter.setSizes([current[0], hints[1]])
        except (RuntimeError, AttributeError):
            pass
        # 17.01.06 (Bugfix): Nach dem FINALEN Box-Resize (DeferredDelete +
        # box.resize) alle Read-only-Info-Anzeigen wieder ganz nach oben
        # scrollen. Durch das Resize wrappt das Dokument der QTextEdit um;
        # Qt scrollt dabei (weil der Cursor von setHtml intern am Dokument-
        # Ende stand) um einige Zeilen nach unten – die erste Zeile waere
        # sonst verdeckt. Dieser Aufruf laeuft NACH dem Layout, sodass die
        # Scroll-Position oben haelt.
        for _info in list(
                getattr(self, "_service_info_labels", {}).values()):
            self._scroll_textedit_top(_info)

    def _clear_service_columns(self) -> None:
        """Entfernt alle Service-Spalten aus dem service_columns_layout."""
        if self.service_columns_layout is None:
            return
        while self.service_columns_layout.count():
            item = self.service_columns_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._service_param_controls = {}
        self._service_desc_controls = {}
        # 17.01.05 (Bugfix): Conditional-Visibility-Zustand je Instanz
        # (Modus-abhaengige Parameter-Ein-/Ausblendung) zuruecksetzen.
        self._mode_schemas = {}
        self._service_param_labels = {}
        # 17.01.05 (Bugfix): Read-only Info-Label (vorgefuellte Service-/Algo-
        # Beschreibung) je Instanz zuruecksetzen.
        self._service_info_labels = {}
        self._service_info_pids = {}
        # 20.03 (Bugfix): Output-Schema-Zustand je Instanz zuruecksetzen
        # (Resultatfelder-Sektion mit i-Buttons in den Service-Spalten).
        self._service_output_schemas = {}

    def _build_service_columns(self, set_definition: Dict[str, Any]) -> None:
        """Baut die dynamischen Service-Spalten (Roadmap 5.4.2.2).

        Für jede instance_id in execution_order wird eine QGroupBox-Spalte im
        service_columns_layout erzeugt. Jede Spalte skaliert in der Höhe exakt
        mit der Anzahl ihrer Parameter (QSizePolicy.Maximum); die Fensterbreite
        wächst mit der Anzahl der Spalten nach rechts – ohne leeren Raum und
        ohne fixe Pixelwerte.
        """
        if self.service_columns_layout is None:
            return
        self._clear_service_columns()
        services = set_definition.get("services") or {}
        for iid in (set_definition.get("execution_order") or []):
            cfg = services.get(iid) or {}
            pid = cfg.get("plugin_id") or iid
            col = self._build_service_column(iid, pid, cfg)
            self.service_columns_layout.addWidget(col)
        # Bugfix 05.08.2026 (Layout-Runde 2): Die Service-Parameter-Box
        # (widget_service_columns) liegt seit dem ZWEI-SPALTEN-Splitter FEST in
        # einer ContentScrollArea (_param_scroll, rechte Splitter-Spalte, max.
        # Hoehe/Breite mit Scrollbalken - Punkt 5). KEIN Reinsert mehr noetig
        # (der fruehere Reinsert stammte aus dem Alt-Layout und verschob die
        # Box aus dem Editor-Panel). Der Qt-6.11-QWidgetItemV2-Cache wird ueber
        # updateGeometry() invalidiert, damit die ScrollArea/der Splitter die
        # aktuelle Spaltenbreite/-hoehe live uebernehmen (vgl. _reflow).
        if self.widget_service_columns is not None:
            self.widget_service_columns.updateGeometry()
        scroll = getattr(self, "_param_scroll", None)
        if scroll is not None:
            scroll.updateGeometry()
        # 08.08.2026 (Bugfix): KEIN self._reflow() – der volle Reflow
        # (_schedule_reflow -> _apply_reflow_size -> resize_to_clamped_
        # content, _exact_fit_to_content) wuerde die FENSTERHOEHE an die neue
        # Spaltenhoehe anpassen und damit Canvas + Fenster bei jedem Set-/
        # Service-Klick versetzen (User-Anweisung: Hoehe fix, vgl.
        # _apply_conditional_visibility/_setup_collapsible, 07.08.2026).
        # Gewuenscht: NUR die Service-Parameter-Box wird auf ihre Layout-
        # Groesse gesetzt; ist sie zu hoch, zeigt die ContentScrollArea
        # (_param_scroll) Scrollbalken. Der initiale Fensteraufbau (show)
        # setzt die Groesse weiterhin ueber _apply_reflow_size.
        QTimer.singleShot(0, self._resize_param_box_deferred)

    def _build_service_column(self, iid: str, pid: str, cfg: Dict[str, Any]) -> QGroupBox:
        """Erzeugt EINE Service-Spalte (QGroupBox) mit Parameter-Formular.

        - Normale Parameter im QFormLayout (float/int/bool nach Schema).
        - expert: True (inkl. lookback) in einer einklappbaren
          QGroupBox 'Experten-Optionen' am Spaltenfuß.

        P14-04-E: Spaltentitel trägt die 🔒-Kennzeichnung, wenn der Service in
        einem gespeicherten Service-Set vorkommt (Sperre sichtbar).
        """
        prefix, _ = self._service_lock(pid)
        col = QGroupBox(f"{prefix}{iid}  [{pid}]")
        # 5.4.2.2 Punkt 3: Spalte skaliert in der Höhe exakt mit ihrem Inhalt
        # (endet unter dem letzten Parameter), wächst beim Vergrößern des
        # Fensters NICHT mit.
        col.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        vl = QVBoxLayout(col)
        vl.setAlignment(Qt.AlignTop)

        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(pid)
        except KeyError:
            vl.addWidget(QLabel(f"Plugin '{pid}' nicht gefunden."))
            return col

        full_schema: Dict[str, Any] = dict(getattr(plugin, "base_parameter_schema", None) or {})
        full_schema.update(dict(plugin.parameter_schema or {}))
        # 17.01.05 (Bugfix): Conditional Visibility – Schema je Instanz merken,
        # um Parameter mit "visible_when"-Deklaration modus-abhaengig
        # ein-/auszublenden (_apply_conditional_visibility).
        self._mode_schemas[iid] = full_schema
        order = list(getattr(plugin, "parameter_order", None) or (plugin.parameter_schema or {}).keys())
        for key in (getattr(plugin, "base_parameter_schema", None) or {}):
            if key not in order:
                order.append(key)
        labels = dict(getattr(plugin, "param_labels", None) or {})
        for key, spec in (getattr(plugin, "base_parameter_schema", None) or {}).items():
            labels.setdefault(key, spec.get("description") or self._human(key))

        params = dict(cfg.get("params") or {})
        lookback = cfg.get("lookback")

        # Phase 14 P14-01: Individuelle Instanz-Beschreibung (bearbeitbar) –
        # wird in ServiceInstanceConfig.description gespeichert und in
        # Tooltip + Info-Dialog angezeigt.
        # Phase 16 (05.08.2026): Stift-Button (✏️) neben dem Beschreibungsfeld
        # oeffnet den modalen ServiceDescriptionEditDialog (mehrzeiliger
        # QTextEdit); [Speichern] persistiert via Repo + EventBus. Die
        # QLineEdit bleibt als schnelles Einzeilen-Feld erhalten.
        desc_row = QHBoxLayout()
        desc_label = QLabel("Beschreibung:")
        desc_edit = QLineEdit()
        desc_edit.setPlaceholderText("Individuelle Anmerkung für diese Instanz (optional)")
        desc_edit.setText(str(cfg.get("description") or ""))
        self._service_desc_controls[iid] = desc_edit
        # Phase 15 (Dirty-State): auch die Instanz-Beschreibung ist Teil des
        # Sets und wird erst beim Set-Speichern persistiert -> dirty markieren.
        desc_edit.textChanged.connect(lambda _t, iid=iid: self._mark_service_dirty(iid))
        desc_row.addWidget(desc_label)
        desc_row.addWidget(desc_edit)
        desc_edit_btn = QPushButton("✏️")
        desc_edit_btn.setObjectName("btn_desc_edit")
        desc_edit_btn.setToolTip(
            "Beschreibung bearbeiten – öffnet den mehrzeiligen Editor")
        desc_edit_btn.setFixedWidth(32)
        desc_edit_btn.setCursor(Qt.PointingHandCursor)
        desc_edit_btn.clicked.connect(
            lambda _=False, iid=iid: self._open_service_desc_editor(iid))
        desc_row.addWidget(desc_edit_btn)
        vl.addLayout(desc_row)

        # 17.01.05 (Bugfix): Read-only Info-Anzeige unter dem individuellen
        # Beschreibungsfeld – zeigt die in der Definition vorgefuellte
        # Service-Beschreibung + die Beschreibung des aktuell gewaehlten
        # Algorithmus (mode). Rein informativ (kein Input), wird beim
        # Mode-Wechsel live aktualisiert (_update_service_info_label).
        # Ergaenzung: Als QTextEdit (read-only) mit gedeckelter Hoehe – wird
        # der Text zu lang, erscheint eine vertikale Scrollbar (kein
        # Aufblahen der Spalte).
        info_label = QTextEdit()
        info_label.setReadOnly(True)
        info_label.setAcceptRichText(True)
        info_label.setFrameShape(QTextEdit.NoFrame)
        info_label.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        info_label.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        info_label.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        info_label.setTabChangesFocus(True)
        info_label.setStyleSheet(
            "QTextEdit { background: transparent; border: none; "
            "color: #666; font-size: 11px; }")
        info_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # Deckelhoehe: ~3 Textzeilen – darueber scrollt der Text vertikal.
        fm = info_label.fontMetrics()
        info_label.setMaximumHeight(fm.lineSpacing() * 3 + 12)
        self._service_info_labels[iid] = info_label
        self._service_info_pids[iid] = pid
        vl.addWidget(info_label)

        # 20.03 (Bugfix): Resultatfelder (Output-Schema) als eigene Sektion
        # UNTER dem Beschreibungs-/Info-Feld (nicht mehr im Info-Label, User-
        # Meldung: Ergebnisparameter gehoeren nicht ins Beschreibungsfeld).
        # 20.03.02 (UI-Umbau, User-Req + F6): KEINE Einzelzeilen mehr – nur
        # die Gruppenueberschrift '📊 Resultatfelder:' mit einem EINZELNEN
        # (i)-Button dahinter, der ALLE Ergebnisparameter der gewaehlten
        # Service-Instanz kompakt in einem Info-Window zeigt (Name/Typ/
        # Beschreibung). Technische Felder (`technical: True`) erscheinen dort
        # UNTERHALB der Haupt-Resultatfelder in einer separaten, kleineren
        # Sektion '🔧 System-Metriken' (F6).
        output_schema = dict(getattr(plugin, "output_schema", None) or {})
        if output_schema:
            out_header_row = QHBoxLayout()
            out_header_row.setContentsMargins(0, 0, 0, 0)
            out_header = QLabel("📊 Resultatfelder:")
            out_header.setObjectName("lbl_output_schema_header")
            out_header.setStyleSheet(
                "color: #666; font-size: 11px; font-weight: bold;")
            out_header_row.addWidget(out_header)
            out_info_btn = QPushButton("(i)")
            out_info_btn.setObjectName("btn_output_params_info")
            out_info_btn.setFixedSize(24, 16)
            out_info_btn.setCursor(Qt.PointingHandCursor)
            out_info_btn.setToolTip(
                "Alle Ergebnisparameter dieser Service-Instanz anzeigen")
            out_info_btn.setStyleSheet(
                "QPushButton { color:#666; border:1px solid #aaa;"
                " border-radius:8px; font-size:9px; font-weight:bold;"
                " background:transparent; }"
                "QPushButton:hover { color:#000; border-color:#000; }")
            out_info_btn.clicked.connect(
                lambda _=False, p=pid: self._show_output_params_info(p))
            out_header_row.addWidget(out_info_btn)
            out_header_row.addStretch(1)
            vl.addLayout(out_header_row)
            # Zustand je Instanz merken (Reset in _clear_service_columns).
            self._service_output_schemas[iid] = output_schema

        # Normale (Nicht-Expert-, Nicht-Darstellungs-)Parameter
        form = QFormLayout()
        for key in order:
            spec = full_schema.get(key, {})
            if spec.get("expert") or self._is_visual_key(key):
                continue
            cval = params.get(key, spec.get("default"))
            # USER-REQ: P14-01 Nachtrag - Alt-Sets speichern die 6 Custom-Levels
            # als Aggregat custom_levels (Liste/String) statt als Einzelparameter
            # prox_level1..6 - leere Level-Felder werden daraus vorbefüllt.
            if key.startswith("prox_level") and not cval:
                try:
                    from analytics.features.definitions.srv_grid_lines import map_custom_levels_to_prox_levels
                    cval = map_custom_levels_to_prox_levels(params).get(key, cval)
                except Exception:
                    pass
            ctrl = self._create_param_control(key, cval, spec)
            self._service_param_controls[(iid, key)] = ctrl
            # Phase 15 (Dirty-State): Aenderungen markieren die Instanz.
            self._connect_param_change(ctrl, iid, key)
            form.addRow(labels.get(key, self._human(key)), ctrl)
            # 17.01.05 (Bugfix): Label-Referenz fuer die modus-abhaengige
            # Ein-/Ausblendung merken.
            lbl = form.labelForField(ctrl)
            if lbl is not None:
                self._service_param_labels[(iid, key)] = lbl
            # 17.01.05 (Bugfix): Mode-Wechsel (Dropdown) blendet die
            # modus-spezifischen Parameter passend ein/aus.
            if key == "mode" and isinstance(ctrl, QComboBox):
                ctrl.currentTextChanged.connect(
                    lambda _v, i=iid: self._apply_conditional_visibility(i))
        vl.addLayout(form)
        # 17.01.05 (Bugfix): Initialzustand der Modus-Sichtbarkeit anwenden
        # (ein geladenes Set kann einen nicht-Default-Mode besitzen).
        self._apply_conditional_visibility(iid)

        # Expert-Parameter (inkl. lookback als Service-Instanz-Einstellung)
        expert_keys = [k for k in order if full_schema.get(k, {}).get("expert")]
        if expert_keys:
            exp_grp = QGroupBox("Experten-Optionen")
            exp_grp.setCheckable(True)
            exp_grp.setChecked(False)
            exp_grp.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            ef = QFormLayout(exp_grp)
            for key in expert_keys:
                spec = full_schema.get(key, {})
                if key == "lookback":
                    cval = lookback if lookback is not None else spec.get("default")
                else:
                    cval = params.get(key, spec.get("default"))
                ctrl = self._create_param_control(key, cval, spec)
                self._service_param_controls[(iid, key)] = ctrl
                # Phase 15 (Dirty-State): Aenderungen markieren die Instanz.
                self._connect_param_change(ctrl, iid, key)
                ef.addRow(labels.get(key, self._human(key)), ctrl)
            vl.addWidget(exp_grp)
            self._setup_collapsible(exp_grp)

        return col

    def _rebuild_columns(self) -> None:
        """Baut die Service-Spalten aus dem aktuellen Editor-Zustand neu."""
        if self.service_columns_layout is None:
            return
        definition = self.collect_set_definition()
        self._build_service_columns(definition)


```

--------------------------------------------------

### DATEI: serviceui/run_worker.py
```py
# serviceui/run_worker.py
"""
Service-UI: Gezielter Hintergrund-Worker fuer die MasterTree-Kontextmenue-
Aktionen '▶️ Diesen Service ausfuehren' / '▶️ Alle Services ausfuehren'
(Phase 15, 05.08.2026).

Im Gegensatz zum historischen `ServiceSetRunWorker` (btn_execute_set, KEIN
Feature-Store-Schreibpfad) persistiert dieser Worker den erzeugten
`feature_store_payload` ZWINGEND in analytics.duckdb (`feature_store`, via
FeatureBuilder.store_plugin_payload) und emittiert danach den EventBus
(`service_set_changed`) – dadurch liest das `ServiceSelectorModel` beim
automatischen refresh() das neue `MAX(created_at)` je feature_id und der
MasterTree aktualisiert das Datum '(DD.MM.JJ)' am betroffenen Service-Knoten
ohne App-Neustart (alle offenen Analytics-/Chart-Fenster folgen synchron).

KEIN globaler Massen-Scan (HistoricalScanner wird bewusst NICHT verwendet):
Der Run ist strikt zielgerichtet –
  * laedt OHLCV nur fuer das aktive Symbol + den gewaehlten Timeframe
    (FeatureBuilder.load_ohlcv),
  * fuehrt nur die selektierte Instanz (Single) bzw. das selektierte Set
    (Set) in execution_order aus (ServiceSetEvaluator.execute_set).

Einzel-Service-Run (single): Es wird eine Mini-Definition gebildet, die den
selektierten Service UND alle Upstream-Services (fruehere Positionen in der
execution_order des Sets) enthaelt – damit liefern Abhaengigkeiten
(depends_on, z.B. grid_1 -> prox_1) ihre shared_state-Eintraege und ein
nachgelagerter Service (srv_proximity) kann tatsaechlich Hits erzeugen und in
den feature_store schreiben.

Der Worker emittiert NUR Signale (log_message / run_finished / run_failed /
tf_started / tf_finished); den Bestaetigungsdialog zeigt der Orchestrator
(ServiceWindow) VOR dem Start.
"""

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

# U15-E (05.08.2026): Sentinel-Wert der Timeframe-Filterleiste im
# ServiceWindow. Wird der Kontextmenue-Run mit diesem Timeframe gestartet,
# fuehrt der Worker ALLE verfuegbaren Timeframes nacheinander aus (Multi-TF).
ALL_TIMEFRAMES = "ALLE Timeframes"


class ServiceRunWorker(QThread):
    """Fuehrt einen Einzel-Service oder ein ganzes Service-Set zielgerichtet
    im Hintergrund aus und persistiert die Feature-Payloads im feature_store.

    05.08.2026 (U15-E): Multi-Timeframe-Ausfuehrung – wenn `timeframe` den
    Sentinel-Wert ALL_TIMEFRAMES ('ALLE Timeframes') traegt, laeuft der Worker
    ALLE verfuegbaren Timeframes (get_timeframes, Fallback TF_SECONDS_MAP)
    nacheinander durch: pro Timeframe OHLCV laden, Pipeline ausfuehren und
    die Payloads mit dem jeweiligen Timeframe in den feature_store schreiben.
    Der EventBus-Sync (`service_set_changed`) wird NUR EINMAL nach Abschluss
    aller Timeframes emittiert (E17, 11.08.2026: auch bei Teilerfolg bzw.
    auf Fehlerpfaden, damit bereits geschriebene Payloads im Baum ankommen).

    Signals:
        log_message(str)      – Fortschritts-/Ergebnis-Meldungen.
        run_finished(str, int)– scope_id (set_id ODER instance_id), Anzahl
                                geschriebener Feature-Rows (0 moeglich, wenn
                                der Service keinen feature_store-Payload hat).
        run_failed(str, str)  – scope_id, Fehlermeldung.
        tf_started(str)       – Timeframe-Start (21.01b, Pill-Strip-Laufzeit).
        tf_finished(str, int, bool) – Timeframe fertig: tf, geschriebene
                                Rows, ob OHLCV-Daten vorhanden waren.
        service_progress(str, str, int, int) - Per-Service-Fortschritt:
                                tf, instance_id, erledigte Services, Gesamt.
    """

    log_message = Signal(str)
    run_finished = Signal(str, int)
    run_failed = Signal(str, str)
    tf_started = Signal(str)
    tf_finished = Signal(str, int, bool)
    # 12.08.2026 (User-Meldung 2): Per-Service-Fortschritt.
    service_progress = Signal(str, str, int, int)

    def __init__(self, evaluator, symbol: str, timeframe: str,
                 set_definition: Dict[str, Any],
                 instance_id: Optional[str] = None,
                 parent=None) -> None:
        """Erstellt den Worker.

        Args:
            evaluator:      ServiceSetEvaluator (execute_set-Pipeline).
            symbol:         Aktives Symbol (z.B. 'SILVER').
            timeframe:      Gewaehlter Timeframe (z.B. 'M1').
            set_definition: Vollstaendige ServiceSetDefinition des Sets.
            instance_id:    Optional – bei Single-Run die selektierte
                            instance_id; None = ganzes Set ausfuehren.
            parent:         Qt-Parent (optional).
        """
        super().__init__(parent)
        self.evaluator = evaluator
        self.symbol = symbol
        self.timeframe = timeframe
        self.set_definition = set_definition
        self.instance_id = instance_id
        # 12.08.2026 (WAL-Korruption beim App-Exit): Abbruch-Flag fuer einen
        # sauberen Worker-Stopp. Wird nur zwischen zwei DB-Writes geprueft
        # (Service-Grenzen / Timeframe-Grenzen) - NIE mitten in einem
        # store_plugin_payload-INSERT, sonst bleibt die WAL inkonsistent.
        self._abort_requested = False

    def stop(self) -> None:
        """Fordert einen sauberen Abbruch an (12.08.2026).

        Setzt das Abbruch-Flag. Der Worker beendet sich an der naechsten
        Service-/Timeframe-Grenze - d. h. nach dem naechsten abgeschlossenen
        store_plugin_payload-Write. Bereits gespeicherte Payloads bleiben
        erhalten, die WAL bleibt konsistent (kein Abbruch mitten im INSERT).
        """
        self._abort_requested = True

    # ------------------------------------------------------------------
    # Ausfuehrungs-Scope (Single vs. Set)
    # ------------------------------------------------------------------
    def _build_scope_definition(self) -> Dict[str, Any]:
        """Liefert die auszufuehrende (Mini-)Definition.

        * Set-Run: die vollstaendige Set-Definition.
        * Single-Run: der selektierte Service + alle Upstream-Services
          (vorherige Positionen in execution_order) – Abhaengigkeiten
          (depends_on) bleiben gueltig, die Pipeline ist aber strikt auf
          die selektierte Instanz ausgerichtet (kein globaler Massen-Scan).
        """
        if not self.instance_id:
            return self.set_definition
        order = list(self.set_definition.get("execution_order") or [])
        services = dict(self.set_definition.get("services") or {})
        if self.instance_id not in services:
            raise ValueError(
                f"Service '{self.instance_id}' nicht im Set vorhanden.")
        if self.instance_id in order:
            idx = order.index(self.instance_id)
        else:
            # Instanz nicht in der Reihenfolge -> nur die Instanz selbst
            idx = 0
            order = []
        scope_order = order[:idx + 1]
        scope_services = {
            iid: services[iid] for iid in scope_order if iid in services
        }
        return {
            "set_id": self.set_definition.get("set_id"),
            "display_name": self.set_definition.get("display_name"),
            "execution_order": scope_order,
            "services": scope_services,
        }

    # ------------------------------------------------------------------
    # U15-E (05.08.2026): Timeframe-Aufloesung (Single vs. Multi-TF)
    # ------------------------------------------------------------------
    def _resolve_timeframes(self) -> List[str]:
        """Liefert die auszufuehrenden Timeframes in stabiler Reihenfolge.

        * Spezifischer Timeframe: [self.timeframe] (Single-Run, unveraendert).
        * ALL_TIMEFRAMES: alle verfuegbaren Timeframes aus get_timeframes()
          (Fallback: TF_SECONDS_MAP; letzter Fallback: Basisliste).
        """
        if self.timeframe != ALL_TIMEFRAMES:
            return [self.timeframe]
        try:
            from db_service import TF_SECONDS_MAP, get_timeframes
            try:
                tfs = list(get_timeframes().keys())
            except Exception:
                tfs = list(TF_SECONDS_MAP.keys())
            # 21.01b (E18c, 11.08.2026): stabil AUFSTEIGEND nach Dauer
            # (M1..MN1) – gleiche Reihenfolge wie combo_tf/Pill-Strip;
            # schnelle TFs laufen damit zuerst.
            return sorted(tfs, key=lambda tf: TF_SECONDS_MAP.get(tf, 10 ** 12))
        except Exception:
            return ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

    def _execute_timeframe(self, fb, settings, definition: Dict[str, Any],
                           scope_label: str, tf: str) -> Tuple[int, bool]:
        """Fuehrt die Pipeline fuer EINEN Timeframe aus und persistiert die
        Feature-Payloads im feature_store.

        E17 (11.08.2026): Die Pipeline laeuft resilient – schlaegt ein
        EINZELNER Service fehl, wird er geloggt (execute_set_resilient:
        last_errors/last_skipped) und die restlichen Services laufen weiter
        statt die Gesamt-Ausfuehrung abzubrechen. execute_set (Fail-Fast)
        bleibt als Fallback fuer fremde Evaluator-Instanzen ohne die
        Resilient-Methode.

        Returns:
            (stored, had_data) – Anzahl geschriebener Feature-Rows (0, wenn
            kein Payload vorhanden ist) und ob OHLCV-Daten geladen wurden
            (False, wenn die Quelle leer war – NUR dann ist die Meldung
            'Keine OHLCV-Daten' korrekt, 17.01.02 Bugfix).
        """
        from analytics.features.feature_builder import prepare_plugin_df
        from analytics.features.plugins.base_plugin import PluginContext

        df = fb.load_ohlcv(self.symbol, tf,
                           limit=settings.scanner_candle_limit)
        if df is None or df.empty:
            self.log_message.emit(
                f"  {self.symbol} {tf}: keine OHLCV-Daten – uebersprungen")
            return 0, False

        df_plugin = prepare_plugin_df(df)
        context = PluginContext(
            symbol=self.symbol,
            timeframe=tf,
            mode="batch",
            timestamp=int(df_plugin["time"].iloc[-1]) if len(df_plugin) else None,
            settings=settings,
        )

        self.log_message.emit(
            f"Ausfuehren: {scope_label} ({self.symbol} {tf})")
        if hasattr(self.evaluator, "execute_set_resilient"):
            results = self.evaluator.execute_set_resilient(
                definition, df_plugin, context=context,
                progress_callback=lambda iid, pos, total: (
                    self.service_progress.emit(tf, iid, pos, total)))
        else:
            results = self.evaluator.execute_set(definition, df_plugin,
                                                 context=context)

        stored = 0
        # 20.04 (Q9): Instanz-Hashes je iid – Grundlage der feature_store-
        # Spalte instance_hash (Varianten-Statistik + gezieltes Purge, Q5).
        # Bevorzugt cfg.instance_hash (Set-Definition), sonst deterministisch
        # aus generate_instance_hash(plugin_id, params) neu berechnet.
        from analytics.engine.service_models import generate_instance_hash
        svc_cfgs = dict(definition.get("services") or {})
        for iid, result in results.items():
            # 12.08.2026 (WAL-Korruption beim App-Exit): Sauberer Abbruch an
            # der Service-Grenze - VOR dem naechsten store_plugin_payload.
            # Bereits geschriebene Payloads dieses Timeframes bleiben intakt.
            if self._abort_requested:
                break
            payload = (result or {}).get("feature_store_payload") or {}
            records = payload.get("records") or []
            if not records:
                self.log_message.emit(
                    f"  {iid}: fertig (kein Feature-Store-Payload)")
                continue
            cfg = svc_cfgs.get(iid) or {}
            pid = str(cfg.get("plugin_id") or iid)
            params = cfg.get("params") or {}
            # 11.08.2026 (Bugfix Varianten-Kollision): Fallback-Hash inkl.
            # preset_name berechnen (identisch zum ServiceSelectorModel) –
            # die cfg.instance_hash (aus variant_run_entries) hat Vorrang.
            preset_name = str(cfg.get("preset_name") or "") or None
            instance_hash = str(cfg.get("instance_hash") or "") or \
                generate_instance_hash(pid, params,
                                       preset_name=preset_name)
            fb.store_plugin_payload(self.symbol, tf, payload,
                                    instance_hash=instance_hash)
            stored += len(records)
            self.log_message.emit(
                f"  {iid}: {len(records)} Feature-Row(s) gespeichert "
                f"({self.symbol} {tf})")
        return stored, True

    # ------------------------------------------------------------------
    # E17 (11.08.2026): EventBus-Sync (auch auf Fehlerpfaden)
    # ------------------------------------------------------------------
    def _emit_service_changed(self) -> None:
        """Stoesst den UI-Sync einmalig an.

        Nach (Teil-)Abschluss des Workers werden alle lauschenden
        ServiceSelectorModel-Instanzen (MasterTree, Analytics, ...)
        automatisch aktualisiert – sie lesen das neue MAX(created_at) und
        der Baum zeigt das Datum (DD.MM.JJ) live an. E17: Der Sync wird
        auch bei run_failed/Teilerfolg emittiert, damit bereits geschriebene
        Payloads (z.B. fruehere Timeframes eines Multi-TF-Runs) sichtbar
        werden.
        """
        try:
            from config.event_bus import event_bus
            event_bus.service_set_changed.emit()
        except Exception as e:  # pragma: no cover
            print(f"WARN [ServiceRunWorker] EventBus-Emitt fehlgeschlagen: {e}")

    # ------------------------------------------------------------------
    # Worker-Loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Laedt OHLCV (ein oder alle Timeframes), fuehrt die Pipeline aus,
        persistiert die Payloads im feature_store und stoesst den EventBus-
        Sync an (einmalig nach Abschluss – auch bei Teilerfolg/Fehler)."""
        scope_id = self.instance_id or str(
            self.set_definition.get("set_id") or "")
        try:
            from analytics.features.feature_builder import FeatureBuilder
            from state_manager import StateManager

            settings = StateManager().get_app_settings()
            fb = FeatureBuilder()
            definition = self._build_scope_definition()
            # 20.04 (Q6): Archiv-Ignoranz (Archive Safety) – archivierte Sets
            # bzw. einzeln archivierte Instanzen werden NICHT ausgefuehrt.
            # Der MasterTree deaktiviert die Run-Aktionen zusaetzlich
            # (Doppel-Absicherung; Scans/Executors bleiben rein lesend).
            if not self.instance_id and self.set_definition.get("is_archived"):
                self.log_message.emit(
                    f"Archiviertes Set '{scope_id}' wird nicht ausgefuehrt "
                    f"(Q6).")
                self.run_finished.emit(scope_id, 0)
                return
            if self.instance_id:
                _svc = (self.set_definition.get("services") or {}).get(
                    self.instance_id) or {}
                if _svc.get("is_archived"):
                    self.log_message.emit(
                        f"Archivierte Instanz '{self.instance_id}' wird nicht "
                        f"ausgefuehrt (Q6).")
                    self.run_finished.emit(scope_id, 0)
                    return
            # 05.08.2026 (Bugfix Service-Run):
            #  * Fehlende depends_on-Einträge (z.B. srv_proximity -> srv_grid_lines)
            #    werden automatisch aufgelöst (sonst 'kein Feature-Store-
            #    Payload' beim Single-Run eines nachgelagerten Services).
            #  * Scanner-Candles (max) aus den App-Optionen als max Lookback
            #    für ALLE Services (Datenbasis wie beim Historical Scanner).
            from serviceui.service_set_utils import prepare_worker_definition
            definition = prepare_worker_definition(
                definition,
                getattr(settings, "scanner_candle_limit", 100000),
            )
            display = str(definition.get("display_name")
                          or self.set_definition.get("display_name")
                          or scope_id or "Unbenannt")
            scope_label = (f"Service '{self.instance_id}' im Set '{display}'"
                           if self.instance_id else f"Set '{display}'")
            self.log_message.emit(f"Ausfuehren: {scope_label}")

            timeframes = self._resolve_timeframes()
            if not timeframes:
                self.run_failed.emit(
                    scope_id, "Keine Timeframes verfuegbar.")
                return

            total_stored = 0
            no_data_tfs: List[str] = []
            no_payload_tfs: List[str] = []
            for tf in timeframes:
                # 12.08.2026 (WAL-Korruption beim App-Exit): Sauberer Abbruch
                # an der Timeframe-Grenze (nach abgeschlossener Persistenz des
                # vorherigen Timeframes) - nie mitten in einem DB-Write.
                if self._abort_requested:
                    self.log_message.emit("Abbruch angefordert - Ausfuehrung "
                                          "wird sauber beendet.")
                    break
                self.tf_started.emit(tf)
                try:
                    stored, had_data = self._execute_timeframe(
                        fb, settings, definition, scope_label, tf)
                except Exception as e:
                    # U15-E (Multi-TF): Ein fehlgeschlagener Timeframe bricht
                    # die Gesamt-Ausfuehrung NICHT ab – Fehler wird geloggt,
                    # die restlichen Timeframes laufen weiter.
                    self.tf_finished.emit(tf, 0, False)
                    if self.timeframe == ALL_TIMEFRAMES:
                        self.log_message.emit(
                            f"  {self.symbol} {tf}: FEHLER – {e}")
                        continue
                    raise
                self.tf_finished.emit(tf, stored, had_data)
                total_stored += stored
                if not had_data:
                    no_data_tfs.append(tf)
                elif stored == 0:
                    no_payload_tfs.append(tf)

            # E17: Sync NACH der (Teil-)Ausfuehrung – auch wenn anschliessend
            # run_failed folgt, kommen bereits geschriebene Payloads im Baum an.
            self._emit_service_changed()

            # Single-TF-Fehler differenzieren (17.01.02 Bugfix): Die
            # Meldung 'Keine OHLCV-Daten' ist NUR korrekt, wenn die Quelle
            # leer war. Waren Daten vorhanden, aber der Service hat keinen
            # Feature-Store-Payload erzeugt, wird das praezise gemeldet
            # (z. B. Scaffold mit records=[], unbekannter Modus).
            if len(timeframes) == 1:
                if no_data_tfs:
                    self.run_failed.emit(
                        scope_id,
                        f"Keine OHLCV-Daten fuer {self.symbol} {timeframes[0]}.")
                    return
                if no_payload_tfs:
                    self.run_failed.emit(
                        scope_id,
                        f"Kein Feature-Store-Payload erzeugt fuer "
                        f"{self.symbol} {timeframes[0]} (Service lieferte "
                        f"0 Records – Daten waren vorhanden).")
                    return

            self.log_message.emit(
                f"Fertig: {total_stored} Feature-Row(s) im feature_store "
                f"({self.symbol}).")

            self.run_finished.emit(scope_id, total_stored)
        except Exception as e:
            # E17: Auch bei Abbruch durch Exception wird der Sync angestossen
            # (falls bereits Payloads geschrieben wurden).
            self._emit_service_changed()
            self.run_failed.emit(scope_id, str(e))

```

--------------------------------------------------

### DATEI: serviceui/service_selector_dialog.py
```py
# serviceui/service_selector_dialog.py
"""
Service-UI: ServiceSelectorDialog (Phase 15.03-E, Multi-Select).

Dialog/Popover fuer die wiederverwendbare Service-Auswahl im
AnalyticsWindow ("Datenquellen"). Bettet das bestehende
`ServiceSelectorWidget` im Modus `MODE_SELECT_MULTI` ein (DRY-Prinzip):

  * Links:  `MasterTree` mit Checkboxen (`[x]`) an allen Set-, Service-,
            Standalone- und Plugin-Knoten (Tri-State fuer Sets).
  * Rechts: Read-Only-"Service-Parameter"-Panel – die Parameter-Spalten aus
            service_win.py (`ServiceParamColumnsMixin._build_service_column`),
            deaktiviert (setEnabled(False), kein Bearbeiten/Speichern):
              - angehakte Set-Services -> Spalte je Service des Sets
              - angehakte Standalone-/Plugin-Zeilen -> Spalte je Plugin

Aktions-Zeile unten:
  * [ 🗑️ Aktive Filter entfernen ] – modale Sicherheitsabfrage
    (`QMessageBox.question`), setzt alle Checkboxen zurueck und emittiert
    `services_selected([], [])`.
  * [ 💾 Anwenden & Schließen ]     – emittiert
    `services_selected(display_names, feature_ids)` und schliesst.

Datenvertrag (Entscheidung 06.08.2026):
  * `display_names`: lesbare Namen fuer die Button-Anzeige
    (z. B. ["Mein Scalper/prox_1", "srv_proximity"]).
  * `feature_ids`:   technische IDs fuer die SQL-Abfrage – die plugin_ids
    des Feature-Store (z. B. ["srv_grid_lines", "srv_proximity"]), dedupliziert
    (`feature_store.feature_id` IST die plugin_id).

Live-Sync (Invariante 5): Das `ServiceSelectorModel` hoert auf
`event_bus.service_set_changed` und refresht den Baum automatisch; der
Checkbox-Zustand bleibt dank MasterTree-internem `_checked_items` ueber
Neuaufbauten erhalten. Das rechte Panel wird nach einem Modell-Refresh mit
dem zuletzt GEKLICKTEN Scope neu gebaut.

Bugfix-Runde 3 (06.08.2026, User-Anweisung Punkte 1-7): Das Read-Only-Panel
folgt dem MAUSKLICK auf eine Tree-Zeile (analog service_win), NICHT den
Checkboxen:
  1. Angezeigt werden NICHT mehr alle angehakten Services, sondern die
     Parameter der GEKLICKTEN Zeile.
  2. Die Anzeige haengt NICHT von den Checkboxen ab (die Checkboxen
     bestimmen weiterhin nur den Analytics-Filter feature_ids).
  3. Jeder einfache Mausklick in einer Tree-Zeile waehlt die Anzeige
     (`MasterTree.selection_details`, wird aus mousePressEvent emittiert).
  4. Klick auf eine SET-Zeile -> Parameter aller Services des Sets.
  5. Klick auf eine SERVICE-Zeile IN einem Set -> ebenfalls alle Services
     des Sets (service_win-Muster `_on_master_selection`).
  6. Klick auf eine PLUGIN-Zeile (⚡ Standalone / 📦 Plugins) -> NUR dieser
     eine Service wird angezeigt.
  7. Alle anderen Zeilen (Gruppen, leere Auswahl) -> KEIN Service im Panel.
  8. (Nachtrag) Die einzelnen Service-Rahmen (QGroupBox) behalten beim
     Vergroessern ihre DEFAULT-Breite (sizeHint) – der abschliessende
     Stretch im QHBoxLayout absorbiert den freien Platz (kein Strecken).

Bugfix-Runde 06.08.2026 (User-Anweisung, Punkte 1-4):
  1. Services im Parameter-Panel liegen HORIZONTAL nebeneinander
     (`QHBoxLayout` statt `QVBoxLayout`).
  2. Default-Breite der Parameter-Box = Platz fuer ZWEI Spalten
     nebeneinander; bei mehr angehakten Services wird horizontal gescrollt
     (QScrollArea, `ScrollBarAsNeeded`).
  3. Die Fensterbreite endet exakt an der rechten Kante der Parameter-Box
     (rechte Kante Dialog == rechte Kante Panel, `_fit_dialog_width`).
  4. Letzte Fensterposition/-groesse werden persistiert
     (`state_manager.save_dialog_geometry`, Key 'service_selector') und beim
     naechsten Oeffnen wiederhergestellt (Muster IndicatorSettingsDialog).
"""

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.description_dialog import ServiceDescriptionDialog
from analytics.engine.feature_store_reader import FeatureStoreReader
from analytics.engine.service_models import generate_instance_hash
from analytics.engine.service_selector_model import ServiceSelectorModel
from analytics.engine.set_evaluator import ServiceSetEvaluator
from config.event_bus import event_bus
from serviceui.master_tree import (
    TYPE_CATEGORY, TYPE_CLONE, TYPE_PLUGIN, TYPE_SERVICE, TYPE_SET,
)
from serviceui.param_columns import ServiceParamColumnsMixin
from serviceui.service_selector_widget import ServiceSelectorWidget
# 21.01b (11.08.2026): Run im Picker (TF-Zeile + Pill-Strip, User-Entscheid).
from serviceui.common_widgets import TfStatusBadgeBar
from serviceui.run_worker import ALL_TIMEFRAMES, ServiceRunWorker
from serviceui.service_set_utils import variant_run_entries

#: Geometrie-Key fuer Position/Groesse des Datenquellen-Dialogs
#: (global_settings, Muster IndicatorSettingsDialog).
DIALOG_GEOMETRY_KEY = "service_selector"
#: Puffer fuer ScrollArea-Rahmen/-Scrollbar, damit 2 Spalten OHNE horizontale
#: Scrollbar nebeneinander passen (Punkt 2).
PANEL_BUFFER = 24
#: Body-Spacing (body.setSpacing(8) unten) – fuer die Breiten-Rechnung (Punkt 3).
BODY_SPACING = 8
#: 06.08.2026 (Punkte 3+4): FESTE Default-Breite des MasterTree (links).
#: Beim manuellen Vergroessern des Fensters behaelt der Tree diese Breite;
#: nur die Parameter-Box waechst mit (bzw. schrumpft bis zu ihrer
#: Minimum-Breite = Platz fuer zwei Service-Spalten nebeneinander).
TREE_DEFAULT_WIDTH = 300


class _DialogParamHost(ServiceParamColumnsMixin):
    """Mixin-Host fuer das Parameter-Panel des Dialogs.

    `ServiceParamColumnsMixin._build_service_column()` erwartet Host-
    Attribute des ServiceWindow (Parameter-Controls, Sperr-Lookup usw.).
    Dieser Host stellt die benoetigten Attribute/Methoden bereit:

      * Read-Only-Anzeige (Sets/Indikator-Services): deaktivierte QGroupBox,
        kein Dirty-Tracking (kein Speichern).
      * 18.01.01 (E-3/E-4): Standalone-Services (`belongs_to_indicator ==
        False`) werden EDITIERBAR gerendert – Parameter laufen in
        global_settings (Key 'plugin_params_<pid>'), der Speichern-Button
        des Dialogs wird bei Aenderungen eingeblendet (_set_param_actions_
        visible) und `_save_plugin_params()` persistiert + emittiert
        `event_bus.service_set_changed` (Live-Sync aller MasterTree).
    """

    def __init__(self, state_manager=None) -> None:
        self._service_param_controls: Dict[str, Any] = {}
        self._service_desc_controls: Dict[str, Any] = {}
        # 08.08.2026 (Bugfix): `ServiceParamColumnsMixin._build_service_column`
        # schreibt auch in diese Registrys (Conditional-Visibility-Schema je
        # Instanz, Form-Label-Referenzen, Info-Labels) – ohne Init schlaegt die
        # Parameteranzeige mit 'AttributeError: _mode_schemas' fehl.
        self._mode_schemas: Dict[str, Any] = {}
        self._service_param_labels: Dict[str, Any] = {}
        self._service_info_labels: Dict[str, Any] = {}
        self._service_info_pids: Dict[str, Any] = {}
        # 20.03.01 (Bugfix): `ServiceParamColumnsMixin._build_service_column`
        # schreibt seit dem Output-Schema-Umbau auch in diese Registry –
        # ohne Init schlaegt die Parameteranzeige mit 'AttributeError:
        # _service_output_schemas' fehl (analog _mode_schemas, 08.08.2026).
        self._service_output_schemas: Dict[str, Any] = {}
        self._symbol_precision: Optional[int] = None
        self.combo_symbol = None
        self.combo_tf = None
        # 18.01.01: Standalone-Editierung im Dialog-Kontext.
        self._state_manager = state_manager
        self._current_plugin_editing: Optional[str] = None
        self._current_set_definition: Optional[Dict[str, Any]] = None
        # 10.08.2026 (Bugfix, Varianten-Params): Wird ein Clone-Knoten
        # (Preset/Variante) editiert, haelt dieses Feld das Preset-Dict aus
        # indicator_presets - _save_plugin_params schreibt dann in das
        # Preset statt in global_settings (plugin_params_<pid>).
        self._current_preset_editing: Optional[Dict[str, Any]] = None
        #: Speichern-Button des Dialogs (wird nach dem UI-Aufbau gesetzt).
        self.btn_save_params: Optional[QPushButton] = None

    def _service_lock(self, plugin_id: str):
        """Keine Set-Sperre im Dialog (kein Set-Editing hier)."""
        return "", ""

    def _open_service_desc_editor(self, instance_id: str) -> None:
        """Read-Only: kein Beschreibungs-Editor im Dialog."""
        pass

    def _schedule_reflow(self) -> None:
        """Kein Fenster-Reflow (Param-Panel skaliert nicht)."""
        pass

    def _resize_param_box_deferred(self) -> None:
        """08.08.2026 (Bugfix): Dialog-Variante statt ServiceWindow-No-op.

        `_setup_collapsible` (Experten-Optionen) und
        `_apply_conditional_visibility` (Mode-Wechsel) rufen diese Methode
        nach Aenderungen der Spaltenhoehe. Hier wird der Param-Container des
        Dialogs auf seine Layout-Groesse nachgezogen – die ScrollArea zeigt
        bei Ueberhoehe Scrollbalken, die Dialog-Fensterhoehe bleibt FIX
        (ServiceWindow-Muster 07.08.2026).
        """
        dlg = getattr(self, "_dialog", None)
        if dlg is not None:
            try:
                dlg._resize_param_container_deferred()
            except (RuntimeError, AttributeError):
                pass

    def _set_param_actions_visible(self, visible: bool) -> None:
        """Blendet den Speichern-Button des Dialogs ein/aus (Dirty-State)."""
        btn = self.btn_save_params
        if btn is not None:
            try:
                btn.setVisible(bool(visible))
            except (RuntimeError, AttributeError):
                pass

    def _plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """ServiceInstanceConfig eines Standalone-Plugins (service_win-Muster).

        Basis sind die Registry-Defaults; gespeicherte Werte aus
        global_settings (Key 'plugin_params_<pid>') ueberschreiben
        lookback/params und ergaenzen eine optionale Beschreibung.
        """
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            plugin = None
        params = dict(getattr(plugin, "default_params", None) or {}) if plugin else {}
        lookback: int = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        cfg: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
        }
        if self._state_manager is not None:
            try:
                saved = self._state_manager.get_global_value(
                    f"plugin_params_{plugin_id}", None)
            except Exception:
                saved = None
            if isinstance(saved, dict):
                lb = saved.get("lookback")
                if lb is not None:
                    try:
                        cfg["lookback"] = int(lb)
                    except (TypeError, ValueError):
                        pass
                saved_params = saved.get("params")
                if isinstance(saved_params, dict):
                    merged = dict(params)
                    merged.update(saved_params)
                    cfg["params"] = merged
                desc = saved.get("description")
                if desc:
                    cfg["description"] = str(desc)
        return cfg

    def _save_plugin_params(self) -> bool:
        """Persistiert die Parameter des editierbaren Standalone-Plugins.

        global_settings (Key 'plugin_params_<pid>') + EventBus-Sync
        (`service_set_changed`, 18.01.01 E-3) – so synchronisieren alle
        ServiceSelectorModel-Instanzen den MasterTree live.

        Wie `collect_set_definition` in service_win wird die individuelle
        Instanz-Beschreibung aus dem Beschreibungs-Control uebernommen
        (`_service_desc_controls`), damit auch Beschreibungs-Aenderungen
        persistiert werden (nicht nur lookback/params).
        """
        plugin_id = self._current_plugin_editing
        if not plugin_id or self._state_manager is None:
            return False
        definition = self._current_set_definition or {}
        services = definition.get("services") or {}
        cfg = next(iter(services.values()), None)
        if not isinstance(cfg, dict):
            return False
        # 10.08.2026 (Bugfix, Varianten-Params): Im Clone-/Preset-Modus wird
        # in indicator_presets gespeichert (eigene Parameter je Variante)
        # statt in global_settings (plugin_params_<pid>).
        preset = self._current_preset_editing
        if isinstance(preset, dict):
            indicator_id = str(preset.get("indicator_id") or "")
            preset_name = str(preset.get("preset_name") or "Default")
            if not indicator_id:
                return False
            try:
                self._state_manager.save_indicator_preset(
                    indicator_id, preset_name,
                    dict(cfg.get("params") or {}),
                    plugin_id=plugin_id,
                    version=str(cfg.get("version")
                                or preset.get("version") or "0.0.0"),
                    is_active_batch=bool(preset.get("is_active_batch")),
                    doc_log=str(preset.get("doc_log") or ""),
                )
            except Exception as e:
                print(f"WARN [ServiceSelectorDialog] Varianten-Parameter "
                      f"nicht gespeichert: {e}")
                return False
            self._set_param_actions_visible(False)
            event_bus.service_set_changed.emit()
            return True
        description = str(cfg.get("description") or "")
        desc_ctrl = self._service_desc_controls.get(plugin_id)
        if desc_ctrl is not None:
            try:
                description = str(desc_ctrl.text()).strip()
            except (RuntimeError, AttributeError):
                pass
        data: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": int(cfg.get("lookback") or 1000),
            "params": dict(cfg.get("params") or {}),
            "description": description,
        }
        try:
            self._state_manager.save_global_value(
                f"plugin_params_{plugin_id}", data)
        except Exception as e:
            print(f"WARN [ServiceSelectorDialog] Plugin-Parameter nicht "
                  f"gespeichert: {e}")
            return False
        self._set_param_actions_visible(False)
        event_bus.service_set_changed.emit()
        return True


class ServiceSelectorDialog(QDialog):
    """Multi-Select-Dialog fuer die Analytics-Datenquellen (15.03-E).

    18.01.01 (E-4): Der Picker ist das frei bewegliche "Manager-Window"
    waehrend einer Analytics-Session. Zusaetzlich zum Multi-Select-Filter:
      * Live-Filter: Klick auf eine Baum-Zeile (Set/Ordner/Plugin) loest die
        feature_ids auf und emittiert `selection_ids_requested` – das
        AnalyticsWindow filtert sofort (ohne 'Anwenden').
      * Standalone-Editierung: Standalone-Services (belongs_to_indicator ==
        False) sind im Param-Panel editierbar (plugin_params_<id>, E-3).
      * Verwaltung: MasterTree-Kontextmenue (Set anlegen/umbenennen/loeschen,
        Service hinzufuegen/entfernen/verschieben) via ServiceSetRepository –
        Services lassen sich waehrend der Session live verwalten.
    """

    #: (display_names, feature_ids) – beim 'Anwenden & Schliessen' bzw.
    #: leere Listen beim 'Aktive Filter entfernen'.
    services_selected = Signal(list, list)
    #: 18.01.01 (E-4): Live-Filter - aufgeloeste feature_ids (plugin_ids),
    #: sofort an das AnalyticsWindow. 10.08.2026 (Bugfix, Punkt 1+2): Der
    #: Filter folgt AUSSCHLIESSLICH den Checkboxen (checked_changed ->
    #: _on_checked_changed -> checked_feature_ids()); der Zeilen-Klick
    #: emittiert dieses Signal NICHT mehr (nur das Read-Only-Panel folgt
    #: dem Klick, Punkte 1-7).
    selection_ids_requested = Signal(list)
    # Runde 10 (Bug 1): Varianten-granularer Filter - instance_hashes der
    # gecheckten Clone-Varianten (parallel zu selection_ids_requested).
    selection_hashes_requested = Signal(list)

    def __init__(
        self,
        model: Optional[ServiceSelectorModel] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.model = model or ServiceSelectorModel(parent=self)
        # 18.01.01: Zugriff auf die ServiceSetRepository (CRUD-Verwaltung).
        self.set_repo = getattr(self.model, "set_repo", None)
        # 06.08.2026 (Punkt 4): StateManager fuer die Dialog-Geometrie.
        # Der Parent (AnalyticsWindow) ist ein PersistentWindow mit
        # `state_manager`-Property; ohne Parent bleiben Save/Restore no-ops.
        self._state_manager = getattr(parent, "state_manager", None)
        self._param_host = _DialogParamHost(state_manager=self._state_manager)
        # 21.01b (11.08.2026): Run-Infrastruktur fuer die MasterTree-
        # Kontextmenue-Aktionen (User-Entscheid: Run im Picker voll
        # funktional, TF-Zeile + Pill-Strip).
        self.set_evaluator = ServiceSetEvaluator()
        self._run_worker: Optional[ServiceRunWorker] = None
        #: Plugin-ID des Services, dessen TF-Pills aktuell angezeigt werden.
        self._badge_plugin_id: Optional[str] = None
        # 12.08.2026 (User-Meldung 'Data only loeschen'): Optionaler
        # instance_hash der angezeigten Variante - der Pill-Strip wird
        # damit VARIANTEN-GENAU geladen (nach Purge verschwinden ihre TFs).
        self._badge_instance_hash: Optional[str] = None
        # 06.08.2026 (Bugfix-Runde 3, Punkte 1-7): Zuletzt GEKLICKTE
        # Tree-Zeile (node_type, set_id, service_id, plugin_id) – Grundlage
        # des Panels (analog service_win). Bleibt nach Modell-Refreshes
        # erhalten, damit das Panel nicht ungewollt zurueckspringt.
        self._last_scope: Optional[tuple] = None
        # 06.08.2026 (Punkte 3+4): Minimum-Breite der Parameter-Box
        # (Default: Platz fuer 2 Service-Spalten nebeneinander).
        self._panel_min_width: int = 0

        self.setWindowTitle("Datenquellen auswählen")
        self.resize(980, 600)
        self.setMinimumWidth(760)
        root = QVBoxLayout(self)
        # 08.08.2026 (Bugfix): `setSizeConstraint` ist eine QLayout-Methode,
        # KEIN QWidget-Attribut – der fruehere self.setSizeConstraint(...)-
        # Aufruf crashte beim Oeffnen des Pickers (AttributeError). Der
        # QDialog-Default (SetDefaultConstraint) wuerde die Fenstergroesse
        # beim show() auf den Layout-sizeHint setzen (Hoehe an die Parameter-
        # Spalten geklemmt); SetNoConstraint haelt die Fenstergroesse FIX,
        # bei Ueberhoehe zeigt die ScrollArea Scrollbalken.
        root.setSizeConstraint(QLayout.SetNoConstraint)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Body: links MasterTree (Checkboxen), rechts Parameter-Panel ---
        body = QHBoxLayout()
        body.setSpacing(BODY_SPACING)
        self.selector = ServiceSelectorWidget(
            ServiceSelectorWidget.MODE_SELECT_MULTI,
            model=self.model,
            parent=self,
        )
        # 10.08.2026 (Bugfix, UI-Splitter): Der Tree ist NICHT mehr starr
        # fixiert - er liegt zusammen mit dem Parameter-Panel in einem
        # QSplitter, dessen Handle der Anwender mit der Maus frei verschieben
        # kann (Klick-Ergonomie, Punkt 3). Nur die Mindestbreite verhindert
        # das Kollabieren; TREE_DEFAULT_WIDTH ist die Startgroesse.
        self.selector.setMinimumWidth(180)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self.selector)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setCollapsible(0, False)

        panel = QWidget(self)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(4)
        panel_layout.addWidget(
            QLabel("Service-Parameter (Read-Only):"))
        # 21.01b (11.08.2026): Run-Timeframe-Zeile (combo_run_tf, Sentinel
        # ALL_TIMEFRAMES wie im ServiceWindow) + TF-Status-Pills des zuletzt
        # geklickten Services (fetch_service_tf_status).
        tf_row = QHBoxLayout()
        tf_row.setSpacing(4)
        tf_row.addWidget(QLabel("Run Timeframe:"))
        self.combo_run_tf = QComboBox()
        self.combo_run_tf.setMinimumWidth(130)
        self.combo_run_tf.setToolTip(
            "Zeitrahmen fuer '▶️ Service(s) ausführen' – 'ALLE Timeframes' "
            "fuehrt alle verfuegbaren Timeframes nacheinander aus.")
        tf_row.addWidget(self.combo_run_tf)
        tf_row.addStretch(1)
        panel_layout.addLayout(tf_row)
        self.badge_bar = TfStatusBadgeBar()
        panel_layout.addWidget(self.badge_bar)
        # 12.08.2026 (User-Meldung 2): Fortschrittsbalken fuer Service-Runs
        # (Muster service_win) - zeigt je Service den Fortschritt ueber alle
        # Services des aktuellen Timeframes (ServiceRunWorker.service_progress).
        self.progress_label = QLabel("")
        self.progress_bar = QProgressBar()
        # 12.08.2026 (User-Meldung 'Fortschrittsbalken laeuft dauerhaft'):
        # setMaximum(0) startet eine INDETERMINATE Busy-Animation, die nie
        # endet. Determinate leere Range (0..1, Wert 0) statt Busy-Loop;
        # _on_service_progress setzt beim Run die echte Range (max(total,1)).
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setTextVisible(False)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(6)
        progress_row.addWidget(self.progress_label, 3)
        progress_row.addWidget(self.progress_bar, 2)
        panel_layout.addLayout(progress_row)
        self._fill_run_tf_combo()
        self.param_panel = panel  # 06.08.2026: feste Breite auf dem PANEL-WIDGET
        self.param_scroll = QScrollArea(panel)
        # 08.08.2026 (Bugfix, ServiceWindow-Muster 07.08.2026): widgetResizable
        # False – der Param-Container behaelt seine NATUERLICHE Groesse
        # (wird nach jedem Panel-Aufbau explizit auf layout().sizeHint()
        # gesetzt, _resize_param_container_deferred). Wird er groesser als
        # der Viewport (viele/hohe Parameter), zeigt die ScrollArea vertikale
        # Scrollbalken – die Dialog-Fensterhoehe bleibt FIX (keine
        # Hoehen-Anpassung an den Parameter-Inhalt).
        self.param_scroll.setWidgetResizable(False)
        # Punkt 2: bei mehr als 2 Spalten horizontale Scrollbar (AsNeeded).
        self.param_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 08.08.2026 (Bugfix): auch vertikal Scrollbalken bei Ueberhoehe.
        self.param_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.param_container = QWidget()
        # Punkt 1: Service-Spalten horizontal nebeneinander (QHBoxLayout).
        self.param_box_layout = QHBoxLayout(self.param_container)
        self.param_box_layout.setContentsMargins(0, 0, 0, 0)
        self.param_box_layout.setSpacing(6)
        self.param_scroll.setWidget(self.param_container)
        panel_layout.addWidget(self.param_scroll, 1)
        # 18.01.01 (E-3): Speichern-Button fuer editierbare Standalone-
        # Services (wird nur bei Parameter-Aenderungen eingeblendet).
        self.btn_save_params = QPushButton("💾 Parameter speichern")
        self.btn_save_params.setVisible(False)
        self.btn_save_params.setToolTip(
            "Speichert die Parameter des editierbaren Standalone-Services "
            "(plugin_params_<id>) inkl. EventBus-Sync (E-3).")
        panel_layout.addWidget(self.btn_save_params)
        self._splitter.addWidget(panel)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([TREE_DEFAULT_WIDTH, 620])
        body.addWidget(self._splitter, 1)
        root.addLayout(body, 1)

        # --- Aktions-Zeile unten ---
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.btn_clear = QPushButton("🗑️ Aktive Filter entfernen")
        self.btn_clear.setToolTip(
            "Entfernt alle angehakten Datenquellen (mit Sicherheitsabfrage).")
        self.btn_apply = QPushButton("💾 Anwenden & Schließen")
        self.btn_apply.setDefault(True)
        actions.addWidget(self.btn_clear)
        actions.addStretch(1)
        actions.addWidget(self.btn_apply)
        root.addLayout(actions)

        # --- Verdrahtung ---
        self.btn_clear.clicked.connect(self._on_clear_filters)
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_save_params.clicked.connect(self._on_save_plugin_params)
        tree = self.selector.master_tree
        if tree is not None:
            # Bugfix-Runde 3 (06.08.2026): Das Panel folgt dem MAUSKLICK auf
            # eine Tree-Zeile (selection_details), NICHT den Checkboxen
            # (checked_changed-Verbindung entfernt – Punkte 1-7).
            tree.selection_details.connect(self._on_tree_selection_details)
            # 10.08.2026 (Bugfix, Punkt 2): Check/Uncheck im ServicePicker
            # muss die Resultatparameter-Dropdowns live aktualisieren - der
            # Analytics-Filter (feature_ids) folgt den HAKEN (checked_changed),
            # zusaetzlich zum Klick-Scope (selection_details). Das Panel
            # selbst bleibt klickgesteuert (Punkte 1-7 unveraendert).
            tree.checked_changed.connect(self._on_checked_changed)
            # 18.01.01 (E-4): Live-Verwaltung waehrend der Analytics-Session –
            # der MasterTree emittiert die CRUD-Signale; der Dialog fuehrt
            # sie ueber die ServiceSetRepository aus (Set anlegen/umbenennen/
            # loeschen, Service hinzufuegen/entfernen/verschieben).
            tree.create_set_requested.connect(self._on_create_set)
            tree.rename_set_requested.connect(self._on_rename_set)
            tree.add_set_service_requested.connect(self._on_add_set_service)
            tree.delete_set_requested.connect(self._on_delete_set)
            tree.move_service_requested.connect(self._on_move_service)
            tree.remove_service_requested.connect(self._on_remove_service)
            # 18.01.03 (Dynamic Tree Management): Kategorie-Drag&Drop &
            # Ordner-CRUD im Picker (Manager-Window) – Sets/Plugins/Ordner
            # ziehen (folder_item_moved/folder_moved), 'Neuer Ordner' (wird
            # PERSISTIERT, E3-revidiert 08.08.2026), 'Umbenennen'
            # (rename_folder_requested) und 'Ordner löschen' (manuelle
            # Loeschung) werden hier persistiert.
            tree.folder_item_moved.connect(self._on_folder_item_moved)
            tree.folder_moved.connect(self._on_folder_moved)
            tree.rename_folder_requested.connect(self._on_rename_folder)
            tree.create_folder_requested.connect(self._on_create_folder)
            tree.delete_folder_requested.connect(self._on_delete_folder)
            # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im MasterTree-Kontextmenue
            # (Service-/Clone-Zeilen) -> Handler (Muster service_win). Ohne
            # diese Verbindungen emittiert der MasterTree die Signale zwar,
            # aber niemand fuehrt sie aus – 'Als Variante duplizieren' im
            # Analytics-Datenquellen-Picker blieb wirkungslos (Q8-Bugfix).
            tree.data_only_purge_requested.connect(
                self._on_data_only_purge)
            tree.delete_complete_requested.connect(
                self._on_delete_complete)
            tree.doc_log_requested.connect(self._on_doc_log_requested)
            tree.duplicate_variant_requested.connect(
                self._on_duplicate_variant)
            # 10.08.2026 (Bugfix): 'Variante umbenennen' (Clone/Preset) –
            # der MasterTree fragt den neuen Namen ab; dieser Handler
            # persistiert den Rename in indicator_presets.
            tree.rename_variant_requested.connect(
                self._on_rename_variant)
            # 21.01b (11.08.2026): Run-Aktionen im Picker verdrahten (TF-Zeile
            # + Pill-Strip voll funktional, User-Entscheid). Die Handler
            # zeigen die Sicherheitsabfrage und starten den ServiceRunWorker
            # mit dem Timeframe aus combo_run_tf (Muster service_win).
            tree.run_service_requested.connect(self._on_run_service)
            tree.run_set_requested.connect(self._on_run_set)
            tree.run_plugin_requested.connect(self._on_run_plugin)
            tree.run_category_requested.connect(self._on_run_category)
        # Live-Sync: Modell-Refresh (EventBus -> data_changed) baut den Baum
        # neu; das Panel wird mit dem zuletzt geklickten Scope nachgezogen.
        self.model.data_changed.connect(self._on_model_data_changed)
        # 18.01.01: Der Host blendet den Speichern-Button des Dialogs ein.
        self._param_host.btn_save_params = self.btn_save_params
        # 08.08.2026 (Bugfix): Host kann den Param-Container nachziehen
        # (Mode-Wechsel/Experten-Kollaps rufen _resize_param_box_deferred)
        # – kein Fenster-Reflow, nur Container-Resize (Scrollbalken).
        self._param_host._dialog = self

        # 20.03.02 (F4): i-Button im MasterTree (ServicePicker) oeffnet den
        # Read-Only ServiceDescriptionDialog.from_plugin()/from_set() –
        # im Gegensatz zum editierbaren ServiceDescriptionEditDialog im
        # ServiceWindow. Kategorie-Ordner zeigen die Ordner-Info analog zur
        # Set-Info (ServiceWindow-Muster _on_category_info_requested).
        self.selector.info_requested.connect(self._on_info_requested)
        self.selector.category_info_requested.connect(
            self._on_category_info_requested)

        # Punkt 4: Letzte Position/Groesse wiederherstellen.
        self._restore_geometry()
        # Panel initial bauen (leer -> Hinweis), damit die Breiten-Logik
        # (Punkte 2+3) vor dem Anzeigen greift.
        self._rebuild_param_panel()

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------
    def apply_feature_ids(self, feature_ids: List[str],
                          instance_hashes=None) -> None:
        """Spiegelt die aktuelle ViewModel-Auswahl im Baum (Reverse-Mapping).

        Wird beim Oeffnen des Dialogs gerufen, damit ein restauriertes
        Profil bzw. der aktive Filter im Checkbox-Baum sichtbar ist.
        Runde 10 (Bug 1): instance_hashes (Varianten) werden ebenfalls
        auf den Baum gemappt - nur die passenden Clone-Varianten werden
        angehakt (Hash-Granularitaet).
        """
        tree = self.selector.master_tree
        if tree is not None:
            tree.set_checked_feature_ids(
                list(feature_ids or []), list(instance_hashes or []))

    def current_display_names(self) -> List[str]:
        tree = self.selector.master_tree
        return tree.checked_display_names() if tree is not None else []

    def current_feature_ids(self) -> List[str]:
        tree = self.selector.master_tree
        return tree.checked_feature_ids() if tree is not None else []

    # ------------------------------------------------------------------
    # Aktions-Zeile
    # ------------------------------------------------------------------
    def _on_clear_filters(self) -> None:
        """Leert alle Checkboxen (mit Sicherheitsabfrage) und emittiert leer.

        Entspricht dem Task-Vertrag: `services_selected([], [])` – der
        AnalyticsWindow setzt daraufhin den Filter zurueck (alle Features).
        """
        reply = QMessageBox.question(
            self, "Aktive Filter entfernen",
            "Möchtest du alle aktiven Datenquellen-Filter wirklich entfernen? "
            "Die Anzeige im Analytics-Fenster zeigt danach wieder alle "
            "Features.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        tree = self.selector.master_tree
        if tree is not None:
            tree.clear_checks()
        # Bugfix-Runde 3 (06.08.2026): Filter entfernen leert auch das
        # Klick-Panel (kein Scope mehr, Hinweis-Text).
        self._last_scope = None
        self._rebuild_param_panel([])
        self.services_selected.emit([], [])

    def _on_apply(self) -> None:
        """Emittiert `services_selected(display_names, feature_ids)` und zu."""
        self.services_selected.emit(
            self.current_display_names(),
            self.current_feature_ids(),
        )
        self.accept()

    # ------------------------------------------------------------------
    # 20.03.02 (F4): i-Button im MasterTree -> Read-Only-Beschreibung
    # ------------------------------------------------------------------
    @Slot(str, str, str)
    def _on_info_requested(self, set_id: str, service_id: str,
                           plugin_id: str) -> None:
        """Info-Button im MasterTree (ServicePicker, 20.03.02 F4).

        Read-Only `ServiceDescriptionDialog.from_plugin()` bzw.
        `from_set()` (kein Editieren – der editierbare
        `ServiceDescriptionEditDialog` bleibt dem ServiceWindow
        vorbehalten). `header_line` im vereinheitlichten F5-Format
        ('📌 im <Indikator> | 🟢 aktiv in <Indikator>' / '⚪ inaktiv').
        """
        try:
            if service_id and set_id:
                cfg = self.model.find_service(set_id, service_id) or {}
                pid = str(cfg.get("plugin_id") or service_id)
                plugin = self._resolve_info_plugin(pid)
                if plugin is None:
                    return
                dlg = ServiceDescriptionDialog.from_plugin(
                    plugin, instance_id=service_id, config=cfg, parent=self,
                    header_line=self._info_header_line(pid))
                dlg.exec()
            elif plugin_id and not service_id:
                plugin = self._resolve_info_plugin(plugin_id)
                if plugin is None:
                    return
                dlg = ServiceDescriptionDialog.from_plugin(
                    plugin, parent=self,
                    header_line=self._info_header_line(plugin_id))
                dlg.exec()
            elif set_id and not service_id:
                definition = self.model.find_set(set_id)
                if not definition:
                    return
                dlg = ServiceDescriptionDialog.from_set(
                    definition, parent=self,
                    header_line=self._info_set_header_line(definition))
                dlg.exec()
        except (RuntimeError, AttributeError):
            pass

    @Slot(str, str)
    def _on_category_info_requested(self, group: str,
                                    category_path: str) -> None:
        """Info-Dialog fuer einen Kategorie-Ordner (20.03.02, F4).

        Analog zur Set-Info (ServiceDescriptionDialog.from_set, keine
        persistierbare Beschreibung): Read-Only-Liste aller Services unter
        dem Ordner (rekursiv) mit dem Kategorie-Pfad als Titel
        (ServiceWindow-Muster _on_category_info_requested).
        """
        if not category_path:
            return
        try:
            plugin_ids = self.model.category_service_plugin_ids(
                group, category_path)
            definition = {
                "set_id": f"category_{category_path}",
                "display_name": category_path,
                "description": f"Kategorie-Ordner: {category_path}",
                "execution_order": list(plugin_ids),
                "services": {pid: {"plugin_id": pid} for pid in plugin_ids},
            }
            dlg = ServiceDescriptionDialog.from_set(definition, parent=self)
            dlg.exec()
        except (RuntimeError, AttributeError):
            pass

    def _resolve_info_plugin(self, plugin_id: str):
        """Registry-Lookup fuer den Info-Dialog (defensiv, ohne KeyError)."""
        try:
            from analytics.features.feature_builder import PluginRegistry
            return PluginRegistry().get(plugin_id)
        except KeyError:
            return None

    def _info_header_line(self, plugin_id: str) -> str:
        """Erste Dialog-Zeile fuer Plugin-/Service-Zeilen (20.03.02, F5).

        Vereinheitlichtes Badge-Format ('📌 im <Indikator> | 🟢 aktiv in
        <Indikator>' / '⚪ inaktiv'); leer ohne Indikator-Zugehoerigkeit.
        """
        model = self.model
        if model is None or not model.belongs_to_indicator(plugin_id):
            return ""
        name = model.get_indicator_display_name(plugin_id)
        if model.is_active_in_chart(plugin_id):
            return f"📌 im {name} | 🟢 aktiv in {name}"
        return f"📌 im {name} | ⚪ inaktiv"

    def _info_set_header_line(self, set_def: Dict[str, Any]) -> str:
        """Erste Dialog-Zeile fuer Set-Zeilen (20.03.02, F5).

        Vereinheitlichtes Badge-Format; mehrere Indikatoren mit ' + '
        verknuepft.
        """
        model = self.model
        if model is None:
            return ""
        names = model.get_set_indicator_names(set_def or {})
        if not names:
            return ""
        label = " + ".join(names)
        if model.is_set_active(set_def or {}):
            return f"📌 im {label} | 🟢 aktiv in {label}"
        return f"📌 im {label} | ⚪ inaktiv"

    # ------------------------------------------------------------------
    # 18.01.01 (E-4): Live-Verwaltung (Set/Service-CRUD im Picker)
    # ------------------------------------------------------------------
    @Slot()
    def _on_save_plugin_params(self) -> None:
        """Speichern-Button: persistiert die editierbaren Standalone-Params."""
        if not self._param_host._save_plugin_params():
            QMessageBox.warning(
                self, "Fehler",
                "Parameter konnten nicht gespeichert werden "
                "(kein editierbarer Standalone-Service ausgewählt).")

    # ------------------------------------------------------------------
    # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im Kontextmenue – Handler
    # (Muster service_win, ohne Editor-Load/Logging; der Dialog ist ein
    # Read-Only-Picker, aber die Duplizierung/Loeschung muss funktionieren).
    # ------------------------------------------------------------------

    def _find_preset_for_hash(self, plugin_id: str,
                              instance_hash: str):
        """Preset-Dict zu plugin_id + instance_hash (indicator_presets)."""
        try:
            sm = self.model.state_manager
            for preset in sm.list_plugin_presets(plugin_id) or []:
                if not isinstance(preset, dict):
                    continue
                from analytics.engine.service_models import (
                    generate_instance_hash)
                # 11.08.2026 (Bugfix Varianten-Kollision): Hash eines
                # Presets inkl. preset_name (identisch zu Modell/Run);
                # Legacy-Fallback fuer Alt-Bestand.
                preset_name = str(preset.get("preset_name") or "Default")
                if (generate_instance_hash(plugin_id,
                                           preset.get("params") or {},
                                           preset_name=preset_name)
                        == instance_hash
                        or generate_instance_hash(
                            plugin_id, preset.get("params") or {})
                        == instance_hash):
                    return preset
        except Exception:
            pass
        return None

    def _purge_legacy_allowed(self, plugin_id: str,
                              params: Optional[Dict[str, Any]]) -> bool:
        """True, wenn der Params-only-Legacy-Pool der Variante EINDEUTIG
        dieser Variante gehoert (12.08.2026, Bugfix Runde 6).

        Alt-Rows aus Runs VOR der Preset-Hash-Umstellung (11.08.2026) liegen
        unter dem reinen Params-only-Hash `generate_instance_hash(plugin_id,
        params)` (ohne preset_name). Dieser Pool ist mehreren Varianten mit
        IDENTISCHEN Params gemeinsam - er darf beim 'Data Only Loeschen'
        einer einzelnen Variante nur entfernt werden, wenn KEINE andere
        aktive Variante (Preset/Clone ODER Set-Instanz) denselben
        Params-only-Hash besitzt.

        Returns:
            True = Pool eindeutig dieser Variante zugeordnet (Legacy-Purge
            erlaubt); False = Pool wird geteilt oder nicht bestimmbar.
        """
        if not plugin_id or params is None:
            return False
        try:
            from analytics.engine.service_models import generate_instance_hash
        except Exception:
            return False
        target = generate_instance_hash(plugin_id, params)
        owners = 0
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            try:
                sm = self.model.state_manager
            except Exception:
                sm = None
        if sm is not None:
            try:
                for p in sm.list_plugin_presets(plugin_id) or []:
                    if not isinstance(p, dict):
                        continue
                    if generate_instance_hash(
                            plugin_id, p.get("params") or {}) == target:
                        owners += 1
            except Exception:
                pass
        try:
            for set_id in (self.set_repo.list_sets()
                           if self.set_repo is not None else []):
                defn = self.set_repo.get_set(set_id)
                if not isinstance(defn, dict):
                    continue
                for cfg in (defn.get("services") or {}).values():
                    if not isinstance(cfg, dict):
                        continue
                    cpid = str(cfg.get("plugin_id") or "")
                    if cpid.lower() == plugin_id.lower() and \
                            generate_instance_hash(
                                cpid, cfg.get("params") or {}) == target:
                        owners += 1
        except Exception:
            pass
        # owners == 1: nur diese eine Variante belegt den Pool. owners == 0
        # (z. B. Standalone-Service): kein Legacy-Pool-Szenario - False.
        return owners == 1

    @Slot(str, str, str, str)
    def _on_duplicate_variant(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Als Variante duplizieren' (20.04, Q8) – Muster service_win."""
        try:
            if set_id and service_id:
                self._duplicate_set_instance(set_id, service_id)
                return
            if plugin_id:
                self._duplicate_preset(plugin_id, instance_hash)
                return
        except (RuntimeError, AttributeError):
            pass

    @Slot(str, str, str)
    def _on_rename_variant(self, plugin_id: str, instance_hash: str,
                           new_name: str) -> None:
        """'Variante umbenennen' (10.08.2026, Bugfix) – Picker-Variante.

        Persistiert den Rename in indicator_presets (indicator_id,
        preset_name) mit Kollisionspruefung. Die Feature-Store-Daten
        (Spalte instance_hash) bleiben unberuehrt. Der Picker nutzt
        QMessageBox-Warnungen statt des ServiceWindow-Loggings.
        """
        try:
            sm = self.model.state_manager
        except Exception:
            return
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            QMessageBox.warning(
                self, "Umbenennen",
                f"Preset zu #{instance_hash} nicht gefunden.")
            return
        old_name = str(preset.get("preset_name") or "Default")
        indicator_id = str(preset.get("indicator_id") or "")
        if not indicator_id:
            QMessageBox.warning(
                self, "Umbenennen",
                "Preset hat keine indicator_id – Umbenennen abgebrochen.")
            return
        clean = (new_name or "").strip()
        if not clean or clean == old_name:
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if clean in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{clean}'.")
            return
        try:
            sm.rename_indicator_preset(indicator_id, old_name, clean)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _next_preset_copy_name(self, plugin_id: str, base: str) -> str:
        """Naechster freier Preset-Name '<base> (Kopie)', '(Kopie 2)', ..."""
        try:
            sm = self.model.state_manager
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if base not in existing:
            return base
        candidate = f"{base} (Kopie)"
        i = 2
        while candidate in existing:
            i += 1
            candidate = f"{base} (Kopie {i})"
        return candidate

    def _duplicate_set_instance(self, set_id: str, service_id: str) -> None:
        """Dupliziert eine Service-Instanz in ihrem Set (Q8)."""
        if self.set_repo is None:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception:
            return
        if not definition:
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id)
        if not isinstance(cfg, dict):
            return
        pid = str(cfg.get("plugin_id") or service_id)
        iid = self._next_instance_id(services, pid)
        copy = dict(cfg)
        copy["params"] = dict(cfg.get("params") or {})
        from analytics.engine.service_models import generate_instance_hash
        copy["instance_hash"] = generate_instance_hash(pid, copy["params"])
        copy.pop("description", None)
        copy.pop("doc_log", None)
        services[iid] = copy
        order = list(definition.get("execution_order") or [])
        order.append(iid)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception:
            return
        event_bus.service_set_changed.emit()

    def _duplicate_preset(self, plugin_id: str, instance_hash: str) -> None:
        """Dupliziert einen Plugin-Clone als neues Preset (Q8)."""
        try:
            sm = self.model.state_manager
        except Exception:
            return
        base = "Default"
        params = {}
        indicator_id = plugin_id
        version = "1.0.0"
        if instance_hash:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset is None:
                return
            base = str(preset.get("preset_name") or "Default")
            params = dict(preset.get("params") or {})
            indicator_id = str(preset.get("indicator_id") or plugin_id)
            version = preset.get("version") or "1.0.0"
        else:
            # Flaches Plugin-Blatt: aktuelle Standalone-Parameter.
            try:
                raw = sm.get_global_value(f"plugin_params_{plugin_id}", {})
            except Exception:
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            params = dict(raw.get("params") or {})
            version = raw.get("version") or "1.0.0"
        # 10.08.2026 (Bugfix): Beim Anlegen einer neuen Variante MUSS ein
        # neuer Name vergeben werden – der Dialog ist mit dem freien
        # Kopiernamen vorbelegt; Kollisionen werden abgefangen.
        suggested = self._next_preset_copy_name(plugin_id, base)
        new_name, ok = QInputDialog.getText(
            self, "Variante anlegen",
            f"Name für die neue Variante (aus '{base}'):", text=suggested)
        new_name = (new_name or "").strip()
        if not ok or not new_name:
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if new_name in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{new_name}'.")
            return
        try:
            sm.save_indicator_preset(
                indicator_id, new_name, params,
                plugin_id=plugin_id,
                version=version,
                # Q8-Bugfix: Kopie IMMER batch-aktiv (nicht Erbe vom
                # Quell-Preset), damit Scans/LiveAnalyzer sie berechnen.
                is_active_batch=True,
                doc_log="",
            )
        except Exception:
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_data_only_purge(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Data Only Löschen' (Q5): Feature-Daten purgen, Struktur bleibt."""
        if not instance_hash:
            return
        # 11.08.2026 (Bugfix Runde 5): Parameter der Variante ermitteln
        # – Grundlage fuer den Legacy-Pool-Purge (Params-only-Hash).
        params = None
        if set_id and service_id:
            try:
                _cfg = self.model.find_service(set_id, service_id)
                if isinstance(_cfg, dict):
                    params = _cfg.get("params") or {}
            except Exception:
                pass
        if params is None:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset:
                params = preset.get("params") or {}
        reply = QMessageBox.question(
            self, "Data Only Löschen",
            f"Feature-Daten der Variante #{instance_hash} löschen?\n"
            "Struktur, Parameter und Doc-Log bleiben erhalten.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            from analytics.features.feature_builder import FeatureBuilder
            FeatureBuilder().purge_instance_data(
                instance_hash, plugin_id, params,
                purge_legacy=self._purge_legacy_allowed(
                    plugin_id, params))
        except Exception:
            pass
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_delete_complete(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Vollständig Löschen': Preset/Instanz + Daten entfernen."""
        try:
            sm = self.model.state_manager
        except Exception:
            return
        if set_id and service_id and self.set_repo is not None:
            try:
                definition = self.set_repo.get_set(set_id)
            except Exception:
                return
            if not definition:
                return
            services = dict(definition.get("services") or {})
            cfg = services.get(service_id)
            if not isinstance(cfg, dict):
                return
            label = str(cfg.get("plugin_id") or service_id)
            reply = QMessageBox.question(
                self, "Vollständig Löschen",
                f"Instanz '{service_id}' aus Set '{set_id}' vollständig "
                "löschen?\n\nDas Preset wird entfernt UND die "
                "berechneten Feature-Daten gelöscht.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            services.pop(service_id, None)
            order = [i for i in (definition.get("execution_order") or [])
                     if i != service_id]
            definition["execution_order"] = order
            definition["services"] = services
            try:
                self.set_repo.save_set(definition)
            except Exception:
                return
            if instance_hash:
                try:
                    from analytics.features.feature_builder import (
                        FeatureBuilder)
                    FeatureBuilder().purge_instance_data(
                        instance_hash,
                        plugin_id or (cfg.get("plugin_id") or ""),
                        cfg.get("params") or {})
                except Exception:
                    pass
            event_bus.service_set_changed.emit()
            return
        if plugin_id and instance_hash:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset is None:
                return
            preset_name = str(preset.get("preset_name") or "Default")
            indicator_id = str(preset.get("indicator_id") or "")
            reply = QMessageBox.question(
                self, "Vollständig Löschen",
                f"Preset '{preset_name}' von '{plugin_id}' vollständig "
                "löschen?\n\nDas Preset wird entfernt UND die "
                "berechneten Feature-Daten gelöscht.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            if sm is not None and indicator_id:
                try:
                    sm.delete_indicator_preset(indicator_id, preset_name)
                except Exception:
                    return
            if instance_hash:
                try:
                    from analytics.features.feature_builder import (
                        FeatureBuilder)
                    FeatureBuilder().purge_instance_data(
                        instance_hash, plugin_id, preset.get("params") or {},
                        purge_legacy=self._purge_legacy_allowed(
                            plugin_id, preset.get("params") or {}))
                except Exception:
                    pass
            event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_doc_log_requested(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Doc Log bearbeiten' (Q7) – Read-Only-Hinweis im Picker.

        Der Dialog ist ein Read-Only-Datenquellen-Picker ohne Editor – die
        vollstaendige Doc-Log-Bearbeitung uebernimmt das ServiceWindow. Hier
        wird eine kurze Info angezeigt, damit der Menuepunkt nicht wirkungslos
        bleibt.
        """
        try:
            if set_id and service_id:
                QMessageBox.information(
                    self, "Doc Log",
                    "Die Doc-Log-Bearbeitung erfolgt im ServiceWindow "
                    "(Kontextmenü der Instanz).")
                return
            if plugin_id and instance_hash:
                preset = self._find_preset_for_hash(plugin_id, instance_hash)
                doc = str((preset or {}).get("doc_log") or "")
                QMessageBox.information(
                    self, "Doc Log",
                    f"Doc Log von '{plugin_id}':\n\n{doc or '(leer)'}\n\n"
                    "Bearbeitung im ServiceWindow (Kontextmenü des Clones).")
                return
        except (RuntimeError, AttributeError):
            pass

    def _next_instance_id(self, services: Dict[str, Any],
                          plugin_id: str) -> str:
        """Naechste freie instance_id fuer ein Plugin im Set (service_win-
        Muster): Basis ist die plugin_id, bei Belegung '_2', '_3', ..."""
        base = plugin_id
        if base not in services:
            return base
        i = 2
        while f"{base}_{i}" in services:
            i += 1
        return f"{base}_{i}"

    def _add_service_to_set(self, set_id: str, plugin_id: str) -> None:
        """Fuegt einen Service (Plugin) mit Registry-Defaults zum Set hinzu
        und persistiert sofort (set_repo + EventBus-Live-Sync)."""
        if not set_id or not plugin_id or self.set_repo is None:
            return
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            QMessageBox.warning(
                self, "Fehler", f"Plugin '{plugin_id}' nicht gefunden.")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            return
        services = dict(definition.get("services") or {})
        order = list(definition.get("execution_order") or [])
        iid = self._next_instance_id(services, plugin_id)
        params = dict(getattr(plugin, "default_params", None) or {})
        lookback = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        services[iid] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
            # Runde 13b (Bugfix Dropdown-NoData): instance_hash mit
            # persistieren (analog service_win._add_service_to_set).
            "instance_hash": generate_instance_hash(plugin_id, params),
        }
        order.append(iid)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _on_create_set(self) -> None:
        """Kontextmenue 'Neues Set anlegen' (Pickername-Dialog)."""
        name, ok = QInputDialog.getText(self, "Neues Service-Set", "Set-Name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": name,
            "description": "",
            "execution_order": [],
            "services": {},
        }
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _on_rename_set(self, set_id: str) -> None:
        """Kontextmenue 'Set umbenennen' (Namensdialog, Kollisionspruefung)."""
        if not set_id or self.set_repo is None:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            return
        current_name = str(definition.get("display_name") or "")
        name, ok = QInputDialog.getText(
            self, "Set umbenennen",
            f"Neuer Name für das Service-Set '{current_name}':",
            text=current_name,
        )
        if not ok:
            return
        clean = (name or "").strip()
        if not clean:
            QMessageBox.warning(self, "Fehler", "Der Name darf nicht leer sein.")
            return
        collision = any(
            (s.get("display_name") or "") == clean and s.get("set_id") != set_id
            for s in self.set_repo.list_sets())
        if collision:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Ein anderes Service-Set heißt bereits '{clean}'.")
            return
        definition["display_name"] = clean
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _on_add_set_service(self, set_id: str) -> None:
        """Kontextmenue 'Service hinzufügen' (Plugin-Auswahlbox)."""
        if not set_id:
            return
        ids = sorted(self.model.get_plugins().keys())
        if not ids:
            QMessageBox.information(
                self, "Service hinzufügen", "Keine Services verfügbar.")
            return
        pid, ok = QInputDialog.getItem(
            self, "Service hinzufügen", "Service wählen:", ids, 0, False)
        if not ok or not pid:
            return
        self._add_service_to_set(set_id, str(pid))

    def _on_delete_set(self, set_id: str) -> None:
        """Kontextmenue 'Set löschen' (Rueckfrage, Soft-Delete/Papierkorb)."""
        if not set_id or self.set_repo is None:
            return
        reply = QMessageBox.question(
            self, "Set löschen",
            f"Service-Set '{set_id}' wirklich löschen (in den Papierkorb)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            self.set_repo.delete_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _on_move_service(self, set_id: str, service_id: str, delta: int) -> None:
        """Kontextmenue 'Order ▲/▼' (execution_order verschieben)."""
        if not set_id or not service_id or self.set_repo is None:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            return
        order = list(definition.get("execution_order") or [])
        if service_id not in order:
            return
        i = order.index(service_id)
        j = i + delta
        if j < 0 or j >= len(order):
            return
        order[i], order[j] = order[j], order[i]
        definition["execution_order"] = order
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _on_remove_service(self, set_id: str, service_id: str) -> None:
        """Kontextmenue 'Service entfernen' (Rueckfrage, direkter Entzug)."""
        if not set_id or not service_id or self.set_repo is None:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            return
        reply = QMessageBox.question(
            self, "Service entfernen",
            f"Service '{service_id}' aus dem Set entfernen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        services = dict(definition.get("services") or {})
        order = [i for i in (definition.get("execution_order") or [])
                 if i != service_id]
        services.pop(service_id, None)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    # ------------------------------------------------------------------
    # 18.01.03 (Dynamic Tree Management): Kategorie-Drag&Drop & Ordner-CRUD
    # im Picker (Manager-Window). Persistenz analog service_win ueber die
    # gemeinsamen Helfer service_set_utils (DRY, E1/E2).
    # ------------------------------------------------------------------
    @Slot(str, str, str)
    def _on_folder_item_moved(self, node_type: str, item_id: str,
                              new_path: str) -> None:
        """Drop eines Sets/Plugins in einen Ziel-Ordner (MasterTree).

        TYPE_SET    -> category-Feld der Set-Definition (E2).
        TYPE_PLUGIN -> Kategorie-Override plugin_category_<id> (E1).
        18.01.03 (E3-revidiert, Bugfix 08.08.2026): Der QUELL-Ordner
        (und seine Elternkette) wird VOR dem Update ermittelt und nach dem
        Verschieben als Leere-Ordner persistiert (ensure_folder_path) –
        damit bleibt der Ordner sichtbar, wenn sein letztes Kind entzogen
        wurde. Danach EventBus-Sync (Live-Refresh aller MasterTrees).
        """
        from serviceui.master_tree import TYPE_PLUGIN, TYPE_SET
        from serviceui.service_set_utils import (
            ensure_folder_path, set_plugin_category, set_set_category)
        source_path = ""
        group = ""
        ok = False
        if node_type == TYPE_SET:
            group = "sets"
            try:
                definition = self.set_repo.get_set(item_id) or {}
                source_path = str(definition.get("category") or "").strip().strip("/")
            except Exception:
                source_path = ""
            ok = set_set_category(self.set_repo, item_id, new_path)
        elif node_type == TYPE_PLUGIN:
            group = "plugins"
            try:
                source_path = self.model.plugin_category_path(item_id)
            except Exception:
                source_path = ""
            ok = set_plugin_category(self._state_manager, item_id, new_path)
        if not ok:
            print(f"WARN [ServiceSelectorDialog] Kategorie-Verschiebung "
                  f"fehlgeschlagen ({node_type} '{item_id}').")
            return
        if source_path:
            ensure_folder_path(self._state_manager, group, source_path)
        event_bus.service_set_changed.emit()

    @Slot(str, str)
    def _on_create_folder(self, group: str, full_path: str) -> None:
        """Kontextmenue 'Neuer Ordner' (create_folder_requested).

        18.01.03 (E3-revidiert, 08.08.2026): Persistiert den
        benutzererzeugten (ggf. leeren) Ordner ueber global_settings
        (service_set_utils.create_empty_folder, Key 'tree_folders_<group>')
        und emittiert den EventBus. Leere Ordner verschwinden damit NICHT
        beim Refresh, sondern nur bei manueller Loeschung.
        """
        from serviceui.service_set_utils import create_empty_folder
        if not create_empty_folder(self._state_manager,
                                   str(group or ""), full_path):
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str)
    def _on_delete_folder(self, group: str, path: str) -> None:
        """Kontextmenue 'Ordner löschen' (delete_folder_requested).

        18.01.03 (E3-revidiert): Entfernt den persistierten Ordner-Eintrag
        (service_set_utils.delete_empty_folder, Key 'tree_folders_<group>')
        und emittiert den EventBus. Der MasterTree erlaubt die Aktion nur
        fuer Ordner ohne Kinder; Kinder bleiben unangetastet.
        """
        from serviceui.service_set_utils import delete_empty_folder
        if not delete_empty_folder(self._state_manager,
                                   str(group or ""), path):
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str, str)
    def _on_folder_moved(self, group: str, old_path: str,
                         new_path: str) -> None:
        """Drop eines Ordners auf einen anderen Ordner (MasterTree)."""
        self._rename_folder(group, old_path, new_path)

    @Slot(str, str, str)
    def _on_rename_folder(self, group: str, old_path: str,
                          new_path: str) -> None:
        """Kontextmenue 'Umbenennen' (rename_folder_requested)."""
        self._rename_folder(group, old_path, new_path)

    def _rename_folder(self, group: str, old_path: str,
                       new_path: str) -> None:
        """Zentraler Ordner-Rename (String-Replace aller Kinder).

        18.01.03 (E1/E2): Sets-Ordner aktualisieren das category-Feld der
        Set-Definitionen; Plugins-Ordner setzen Kategorie-Overrides.
        """
        from serviceui.service_set_utils import rename_category
        try:
            count = rename_category(
                self.model, self.set_repo, self._state_manager,
                str(group or ""), old_path, new_path)
        except Exception as e:
            print(f"WARN [ServiceSelectorDialog] Ordner-Umbenennung "
                  f"fehlgeschlagen: {e}")
            return
        if count > 0:
            event_bus.service_set_changed.emit()

    # ------------------------------------------------------------------
    # Read-Only-Parameter-Panel (Punkte 1-3: horizontal, 2-Spalten-Default,
    # Fensterbreite == rechte Kante der Parameter-Box)
    # ------------------------------------------------------------------
    @Slot()
    def _on_checked_changed(self) -> None:
        """Live-Filter bei Checkbox-Aenderungen im Picker (10.08.2026).

        Ein An-/Abhaken aktualisiert sofort die Datenquellen des
        AnalyticsWindow (selection_ids_requested -> set_feature_ids) -
        dadurch erneuern sich auch die Resultatparameter-Dropdowns
        (heatmap field/agg etc.). Das Read-Only-Panel folgt weiterhin der
        GEKLICKTEN Zeile (Punkte 1-7), nicht den Haken.
        """
        tree = self.selector.master_tree
        if tree is None:
            return
        try:
            ids = list(tree.checked_feature_ids() or [])
            hashes = list(tree.checked_instance_hashes() or [])
        except (RuntimeError, AttributeError):
            return
        self.selection_ids_requested.emit(ids)
        self.selection_hashes_requested.emit(hashes)

    def _on_tree_selection_details(self, node_type: str, set_id: str,
                                   service_id: str, plugin_id: str) -> None:
        """Slot fuer `MasterTree.selection_details` (Mausklick in einer Zeile).

        Bugfix-Runde 3 (06.08.2026, Punkte 1-7): Das Panel folgt der
        GEKLICKTEN Zeile, NICHT den Checkboxen (analog service_win
        `_on_master_selection`):

          * Set-Zeile ODER Service-Zeile IN einem Set -> ALLE Services des
            Sets nebeneinander (`_entries_for_scope`, Punkt 4+5).
          * Plugin-Zeile (⚡ Standalone / 📦 Plugins) -> NUR dieser eine
            Service (Punkt 6).
          * Kategorie-Ordner (18.01.01, E-4) -> ALLE Elemente des Pfads
            (rekursiv). 18.01.03 (L3): Sets-Ordner (set_id == 'sets')
            liefern die Service-Spalten aller Sets unter dem Pfad,
            Plugins-Ordner die Plugin-Spalten (category_plugin_ids).
          * Gruppen-/sonstige Zeilen -> KEIN Service (Punkt 7).

        10.08.2026 (Bugfix, Punkt 1+2): Der LIVE-FILTER folgt
        AUSSCHLIESSLICH den Checkboxen (`checked_changed` ->
        `_on_checked_changed` -> `selection_ids_requested` mit
        `checked_feature_ids()`) - der Zeilen-Klick steuert NUR das Panel.
        Vorher emittierte dieser Handler beim Klick zusaetzlich
        `selection_ids_requested` mit dem Zeilen-Scope und ueberschrieb
        damit den angehakten Filter (feature_ids der Historie/des Profils
        entsprach dem letzten Klick statt den Haken; die
        Ergebnisparameter-Dropdowns folgten dem Klick statt den Haken).
        Standalone-Services (belongs_to_indicator == False) sind editierbar
        (plugin_params_<id>), alle anderen Zeilen bleiben read-only.
        """
        self._last_scope = (node_type, set_id, service_id, plugin_id)
        # 10.08.2026 (Bugfix, Punkt 1+2): KEIN selection_ids_requested mehr -
        # der Filter folgt den Checkboxen (checked_changed), nicht dem Klick.
        # Ein Klick darf den angehakten Filter nicht ueberschreiben (sonst
        # speichern Historie/Profil den letzten Klick statt der Haken).
        editable = None
        if node_type in (TYPE_PLUGIN, TYPE_CLONE) and plugin_id:
            if not self.model.belongs_to_indicator(str(plugin_id)):
                editable = str(plugin_id)
        self._rebuild_param_panel(
            self._entries_for_scope(node_type, set_id, service_id, plugin_id),
            editable_plugin=editable)
        # 21.01b: Pill-Strip dem geklickten Service nachziehen.
        pid_badge, hash_badge = self._resolve_badge_scope(
            node_type, set_id, service_id, plugin_id)
        self._refresh_badge_bar(pid_badge, hash_badge)

    def _resolve_selection_ids(self, node_type: str, set_id: str,
                               service_id: str, plugin_id: str) -> List[str]:
        """Loest eine geklickte Baum-Zeile in feature_ids (plugin_ids) auf.

        18.01.01 (E-4): Klick auf Set -> alle Services des Sets; Klick auf
        Kategorie-Ordner -> rekursive Aufloesung; Klick auf Plugin-Zeile ->
        [plugin_id]; Service-Zeile -> [plugin_id des Service]. 18.01.03
        (L3): Fuer Kategorie-Ordner traegt set_id die Eltern-GRUPPE
        ('sets'/'plugins', aus MasterTree._emit_selection_details) – die
        Aufloesung unterscheidet damit Sets-Ordner (Sets unter dem Pfad ->
        deren Service-plugin_ids) von Plugins-Ordnern (category_plugin_ids).
        """
        if node_type == TYPE_CATEGORY:
            return self.model.category_service_plugin_ids(
                set_id or "", plugin_id or "")
        if node_type in (TYPE_PLUGIN, TYPE_CLONE) and plugin_id:
            # 20.04 (Q7): Clone-Zeilen loesen auf die plugin_id des
            # Plugin-Parents auf (Filter bleibt feature_id IN (plugin_ids)).
            return [str(plugin_id)]
        if node_type == TYPE_SERVICE and set_id and service_id:
            cfg = self.model.find_service(set_id, service_id) or {}
            pid = str(cfg.get("plugin_id") or service_id)
            return [pid] if pid else []
        if node_type == TYPE_SET and set_id:
            definition = self.model.find_set(set_id) or {}
            services = definition.get("services") or {}
            order = definition.get("execution_order") or list(services.keys())
            ids: List[str] = []
            for iid in order:
                cfg = services.get(iid) or {}
                pid = str(cfg.get("plugin_id") or iid)
                if pid and pid not in ids:
                    ids.append(pid)
            return ids
        return []

    # ------------------------------------------------------------------
    # 21.01b (11.08.2026): Run im Picker (TF-Zeile + Pill-Strip)
    # ------------------------------------------------------------------
    def _run_symbol(self) -> str:
        """Aktives Symbol aus dem Parent (AnalyticsWindow.combo_symbol)."""
        parent = self.parent()
        cb = getattr(parent, "combo_symbol", None)
        if cb is not None:
            try:
                txt = cb.currentText()
            except Exception:
                txt = ""
            if txt:
                return str(txt)
        return "SILVER"

    def _run_timeframe(self) -> str:
        """Gewaehlter Run-Timeframe (Sentinel = Multi-TF im Worker)."""
        combo = getattr(self, "combo_run_tf", None)
        if combo is None:
            return ALL_TIMEFRAMES
        return str(combo.currentText() or ALL_TIMEFRAMES)

    def _fill_run_tf_combo(self) -> None:
        """Befuellt combo_run_tf: Sentinel 'ALLE Timeframes' + alle TFs
        aufsteigend nach Dauer (M1..MN1, wie combo_tf im ServiceWindow)."""
        combo = getattr(self, "combo_run_tf", None)
        if combo is None:
            return
        try:
            from db_service import TF_SECONDS_MAP, get_timeframes
            try:
                tfs = list(get_timeframes().keys())
            except Exception:
                tfs = list(TF_SECONDS_MAP.keys())
            sort_map = TF_SECONDS_MAP
        except Exception:
            tfs = ["M1", "M2", "M5", "M10", "M15", "M30",
                   "H1", "H4", "D1", "W1", "MN1"]
            sort_map = {}
        tfs = sorted(tfs, key=lambda tf: sort_map.get(tf, 10 ** 12))
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(ALL_TIMEFRAMES)
        for tf in tfs:
            if tf != ALL_TIMEFRAMES:
                combo.addItem(tf)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """Standalone-Plugin-Config wie im ServiceWindow (17.01.04-Muster).
        Basis sind die Registry-Defaults; gespeicherte Werte aus
        global_settings (Key 'plugin_params_<pid>') ueberschreiben."""
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            plugin = None
        params = dict(getattr(plugin, "default_params", None) or {}) \
            if plugin else {}
        lookback: int = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        cfg: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
        }
        try:
            saved = self._state_manager.get_global_value(
                f"plugin_params_{plugin_id}", None)
        except Exception:
            saved = None
        if isinstance(saved, dict):
            lb = saved.get("lookback")
            if lb is not None:
                try:
                    cfg["lookback"] = int(lb)
                except (TypeError, ValueError):
                    pass
            saved_params = saved.get("params")
            if isinstance(saved_params, dict):
                merged = dict(cfg["params"])
                merged.update(saved_params)
                cfg["params"] = merged
        return cfg

    def _start_run_worker(self, scope_id: str, set_definition: Dict[str, Any],
                          instance_id: Optional[str]) -> None:
        """Startet den gezielten ServiceRunWorker (Single/Set) mit dem
        Timeframe aus combo_run_tf – Muster service_win._start_run_worker."""
        if self._run_worker is not None and self._run_worker.isRunning():
            QMessageBox.information(
                self, "Service-Ausführung",
                "Eine Service-Ausführung läuft bereits.")
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        self._run_worker = ServiceRunWorker(
            self.set_evaluator, symbol, timeframe, set_definition,
            instance_id=instance_id, parent=self,
        )
        self._run_worker.log_message.connect(self._on_run_log)
        self._run_worker.run_finished.connect(self._on_run_worker_finished)
        self._run_worker.run_failed.connect(self._on_run_worker_failed)
        # 21.01b: Per-TF-Signale -> Pill-Strip (Laufzeit-/Fehler-Zustand).
        self._run_worker.tf_started.connect(self._on_tf_started)
        self._run_worker.tf_finished.connect(self._on_tf_finished)
        # 12.08.2026 (User-Meldung 2): Per-Service-Fortschritt -> Progress-Bar.
        self._run_worker.service_progress.connect(self._on_service_progress)
        self._reset_run_progress("Starte Ausfuehrung ...")
        self._run_worker.start()

    def _on_run_log(self, message: str) -> None:
        try:
            print(f"[ServicePicker] {message}")
        except Exception:
            pass

    def _merge_live_param_values(self, definition: Dict[str, Any]) -> None:
        """13.08.2026 (Punkt 7, F7): Implizites Uebernehmen der Parameterbox.

        Der Picker-Run nutzt sonst die GESPEICHERTE Set-/Plugin-Definition
        (set_repo.get_set / variant_run_entries + _plugin_config). Wurden
        in der Parameterbox Werte geaendert, ohne zu speichern (inkl.
        Modus), gingen sie bei der Ausfuehrung verloren - Wurzel von Bug 4
        (MA_Slope_Change landete nie im Store, weil der Run mit
        default_params -> erstem Mode-Eintrag lief). Hier werden die LIVE-
        Control-Werte der aktuellen Parameterbox in die Run-Definition
        uebernommen (nur fuer DIESEN Run, keine Persistenz).

        Match: exakte instance_id (Set-Service/Standalone ohne Presets);
        bei Clone-Runs (instance_id = '<pid>#<hash>') zusaetzlich per
        plugin_id, sofern in der Definition genau EIN Service matcht
        (mehrere Varianten = mehrdeutig, dann keine Uebernahme).
        """
        host = getattr(self, "_param_host", None)
        if host is None:
            return
        controls = getattr(host, "_service_param_controls", None) or {}
        if not controls:
            return
        services = definition.get("services") or {}
        for (iid, key), ctrl in controls.items():
            cfg = services.get(iid)
            if not isinstance(cfg, dict):
                matches = [c for c in services.values()
                           if isinstance(c, dict)
                           and str(c.get("plugin_id") or "") == str(iid)]
                if len(matches) == 1:
                    cfg = matches[0]
                else:
                    continue
            try:
                value = host._ctrl_value(ctrl)
            except (RuntimeError, AttributeError):
                continue
            if key == "lookback":
                try:
                    cfg["lookback"] = int(value)
                except (TypeError, ValueError):
                    pass
            else:
                cfg.setdefault("params", {})[key] = value

    def _on_run_service(self, set_id: str, service_id: str) -> None:
        """'▶️ Diesen Service ausführen' (Picker-MasterTree)."""
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            QMessageBox.warning(
                self, "Service ausführen",
                f"Set '{set_id}' nicht gefunden.")
            return
        if service_id not in (definition.get("services") or {}):
            QMessageBox.warning(
                self, "Service ausführen",
                f"Service '{service_id}' nicht im Set '{set_id}'.")
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        set_name = str(definition.get("display_name") or set_id)
        reply = QMessageBox.question(
            self, "Service ausführen",
            f"Service '{service_id}' aus dem Set '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        # 13.08.2026 (Punkt 7, F7): Implizites Uebernehmen der Parameterbox-
        # Werte (inkl. Modus) vor der Ausfuehrung - sonst liefe der Run mit
        # der GESPEICHERTEN Definition (Aenderungen ohne Speichern gehen
        # verloren).
        self._merge_live_param_values(definition)
        self._start_run_worker(service_id, definition, instance_id=service_id)

    def _on_run_set(self, set_id: str) -> None:
        """'▶️ Alle Services ausführen' (Picker-MasterTree)."""
        if not set_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            QMessageBox.warning(
                self, "Set ausführen", f"Set '{set_id}' nicht gefunden.")
            return
        if not definition.get("execution_order"):
            QMessageBox.information(
                self, "Set ausführen", f"Set '{set_id}' hat keine Services.")
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        set_name = str(definition.get("display_name") or set_id)
        count = len(definition.get("execution_order") or [])
        reply = QMessageBox.question(
            self, "Set ausführen",
            f"Alle Services ({count}) des Sets '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Die erzeugten Feature-Store-Payloads werden in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        # 13.08.2026 (Punkt 7, F7): Parameterbox-Werte implizit uebernehmen
        # (sichtbare Set-Service-Spalten), bevor das ganze Set laeuft.
        self._merge_live_param_values(definition)
        self._start_run_worker(set_id, definition, instance_id=None)

    def _on_run_plugin(self, plugin_id: str, instance_hash: str = "") -> None:
        """'▶️ Diesen Service ausführen' (Plugin-/Clone-Zeile).

        11.08.2026 (Bugfixing, Varianten-Run): `instance_hash` wird vom
        MasterTree-Kontextmenue mitgeliefert – Clone-Zeilen laufen NUR mit
        den Parametern + Hash der Variante; Plugin-Zeilen mit Presets
        laufen ALLE aktiven Varianten (Bug 1/2/3).
        """
        if not plugin_id:
            return
        sm = getattr(self, "_state_manager", None)
        entries = variant_run_entries(plugin_id, sm, self._plugin_config)
        if not entries:
            return
        if instance_hash:
            entries = [e for e in entries
                       if e[1].get("instance_hash") == instance_hash]
            if not entries:
                entries = [(plugin_id, self._plugin_config(plugin_id))]
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        single = len(entries) == 1
        if single:
            _iid, _cfg = entries[0]
            _name = str(_cfg.get("preset_name") or plugin_id)
            title = "Service ausführen"
            text = (f"Service '{plugin_id}' (Variante '{_name}') ausführen?\n\n"
                    f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                    f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
                    f"geschrieben.")
        else:
            title = "Alle Varianten ausführen"
            text = (f"Alle Varianten ({len(entries)}) von '{plugin_id}' "
                    f"ausführen?\n\n"
                    f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                    f"Die erzeugten Feature-Store-Payloads werden in "
                    f"analytics.duckdb geschrieben.")
        reply = QMessageBox.question(
            self, title, text, QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        definition = {
            "set_id": f"plugin_{plugin_id}",
            "display_name": plugin_id,
            "execution_order": [e[0] for e in entries],
            "services": {e[0]: e[1] for e in entries},
        }
        # 13.08.2026 (Punkt 7, F7): Parameterbox-Werte implizit uebernehmen
        # (inkl. Modus - Bug 4: der Run nutzte sonst default_params und
        # lief immer mit dem ersten Mode-Eintrag).
        self._merge_live_param_values(definition)
        self._start_run_worker(
            plugin_id, definition,
            instance_id=entries[0][0] if single else None)

    def _on_run_category(self, group: str, category_path: str) -> None:
        """'▶️ Alle Services ausführen' (Kategorie-Ordner, rekursiv)."""
        if not category_path:
            return
        model = getattr(self, "model", None)
        if model is None:
            return
        plugin_ids = model.category_service_plugin_ids(group, category_path)
        if not plugin_ids:
            QMessageBox.information(
                self, "Alle Services ausführen",
                f"Kategorie '{category_path}' hat keine Services.")
            return
        # 11.08.2026 (Bugfixing, Bug 3): Plugins MIT Presets -> ALLE aktiven
        # Varianten werden ausgefuehrt (jede mit eigenen Parametern + Hash).
        sm = getattr(self, "_state_manager", None)
        entries_all: List[tuple] = []
        for pid in plugin_ids:
            entries_all.extend(variant_run_entries(pid, sm, self._plugin_config))
        if not entries_all:
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        count = len(entries_all)
        reply = QMessageBox.question(
            self, "Alle Services ausführen",
            f"Alle Services ({count}) der Kategorie '{category_path}' "
            f"ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Die erzeugten Feature-Store-Payloads werden in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        definition = {
            "set_id": f"category_{category_path}",
            "display_name": category_path,
            "execution_order": [e[0] for e in entries_all],
            "services": {e[0]: e[1] for e in entries_all},
        }
        self._start_run_worker(category_path, definition, instance_id=None)

    def _on_run_worker_finished(self, scope_id: str, stored: int) -> None:
        """Run abgeschlossen: Pill-Strip zuruecksetzen + Status neu laden."""
        self._on_run_log(f"Ausführung abgeschlossen: {stored} Feature-Row(s) "
                         f"im feature_store gespeichert ({scope_id}).")
        self._reset_run_progress()
        self.badge_bar.set_running(None)
        self._refresh_badge_bar()

    def _on_run_worker_failed(self, scope_id: str, error: str) -> None:
        """Run fehlgeschlagen: Pill-Strip zuruecksetzen + Status neu laden."""
        self._on_run_log(f"FEHLER bei Ausführung ({scope_id}): {error}")
        self._reset_run_progress()
        self.badge_bar.set_running(None)
        self._refresh_badge_bar()

    @Slot(str, str, int, int)
    def _on_service_progress(self, tf: str, iid: str, done: int,
                             total: int) -> None:
        """12.08.2026 (User-Meldung 2): Per-Service-Fortschritt anzeigen."""
        bar = getattr(self, "progress_bar", None)
        if bar is not None:
            bar.setMaximum(max(total, 1))
            bar.setValue(done)
        lbl = getattr(self, "progress_label", None)
        if lbl is not None:
            lbl.setText(f"{tf}: {iid} ({done}/{total})")

    def _reset_run_progress(self, label: str = "") -> None:
        """Setzt den Fortschrittsbalken zurueck (Default: leeres Label)."""
        bar = getattr(self, "progress_bar", None)
        if bar is not None:
            # 12.08.2026: setMaximum(0) waere eine endlose Busy-Animation
            # (indeterminate) - determinate leere Range (0..1) verwenden.
            bar.setRange(0, 1)
            bar.setValue(0)
        lbl = getattr(self, "progress_label", None)
        if lbl is not None:
            lbl.setText(label)

    def closeEvent(self, event) -> None:
        """12.08.2026 (WAL-Korruption beim App-Exit): Laufenden
        ServiceRunWorker sauber stoppen, bevor der Dialog schliesst."""
        worker = getattr(self, "_run_worker", None)
        if worker is not None and worker.isRunning():
            worker.stop()
            worker.wait(5000)
        super().closeEvent(event)

    def _on_tf_started(self, tf: str) -> None:
        """Hebt den gerade laufenden Timeframe im Pill-Strip blau hervor."""
        self.badge_bar.set_running(tf)
        self.badge_bar.clear_error(tf)

    def _on_tf_finished(self, tf: str, stored: int, had_data: bool) -> None:
        """TF fertig: ohne OHLCV-Daten/Fehler rot markieren, sonst neutral."""
        if had_data:
            self.badge_bar.clear_error(tf)
        else:
            self.badge_bar.set_error(tf)
        self.badge_bar.set_running(None)

    def _resolve_badge_scope(self, node_type: str, set_id: str,
                             service_id: str,
                             plugin_id: str) -> Tuple[Optional[str],
                                                      Optional[str]]:
        """Ermittelt (plugin_id, instance_hash) fuer den Pill-Strip.

        12.08.2026 (User-Meldung 'Data only loeschen'): Der Pill-Strip wird
        VARIANTEN-GENAU geladen. Clone-Knoten tragen den instance_hash im
        service_id-Slot (MasterTree._emit_selection_details, 20.04 Q7);
        Set-/Service-Zeilen liefern den Hash der ersten Instanz aus der
        Set-Definition (cfg['instance_hash'], sonst Params-only-Hash).
        """
        if plugin_id:
            h = str(service_id) if node_type == TYPE_CLONE else None
            return str(plugin_id), (h or None)
        if node_type == TYPE_SERVICE:
            if set_id and service_id:
                cfg = self.model.find_service(set_id, service_id) or {}
                pid = str(cfg.get("plugin_id") or service_id)
                h = str(cfg.get("instance_hash") or "") or None
                if not h and pid:
                    try:
                        h = generate_instance_hash(
                            pid, cfg.get("params") or {})
                    except Exception:
                        h = None
                return pid, h
            return (str(service_id) if service_id else None), None
        if node_type == TYPE_SET and set_id:
            definition = self.model.find_set(set_id) or {}
            order = list(definition.get("execution_order") or [])
            services = dict(definition.get("services") or {})
            for iid in order:
                cfg = services.get(iid) or {}
                pid = str(cfg.get("plugin_id") or iid)
                if pid:
                    h = str(cfg.get("instance_hash") or "") or None
                    if not h:
                        try:
                            h = generate_instance_hash(
                                pid, cfg.get("params") or {})
                        except Exception:
                            h = None
                    return pid, h
        return None, None

    def _refresh_badge_bar(self, plugin_id: Optional[str] = None,
                           instance_hash: Optional[str] = None) -> None:
        """Laedt die TF-Status-Pills fuer den angegebenen Service neu
        (FeatureStoreReader.fetch_service_tf_status).

        12.08.2026 (User-Meldung 'Data only loeschen'): Mit `instance_hash`
        wird der Pill-Strip VARIANTEN-GENAU geladen (nur die TFs dieser
        Variante); ohne Hash bleibt das service-weite Verhalten erhalten."""
        if plugin_id:
            self._badge_plugin_id = plugin_id
        if instance_hash:
            self._badge_instance_hash = instance_hash
        pid = self._badge_plugin_id
        if not pid:
            self.badge_bar.clear()
            return
        h = self._badge_instance_hash or None
        try:
            status = FeatureStoreReader().fetch_service_tf_status(pid, h)
        except Exception:
            status = {}
        self.badge_bar.update_status(status)

    def _on_model_data_changed(self) -> None:
        """Modell-Refresh (EventBus -> data_changed): Panel neu aufbauen.

        Nach einem Baum-Neuaufbau (neues Set, Ausfuehrungsdatum, ...) wird
        das Panel mit dem zuletzt GEKLICKTEN Scope nachgezogen; ohne Scope
        (noch nichts angeklickt) bleibt das Panel leer.
        """
        scope = getattr(self, "_last_scope", None)
        if scope:
            self._on_tree_selection_details(*scope)
        else:
            self._rebuild_param_panel([])

    def _entries_for_scope(self, node_type: str, set_id: str, service_id: str,
                           plugin_id: str) -> List[Dict[str, str]]:
        """Panel-Entries fuer die geklickte Tree-Zeile (service_win-Muster).

        Returns:
            Liste von {"node_type", "set_id", "instance_id", "plugin_id"} –
            leer fuer Zeilen ohne Parameter-Anzeige (Gruppen, leere Auswahl).
            Kategorie-Ordner (18.01.01, E-4) liefern die Elemente des Pfads
            rekursiv; 18.01.03 (L3) unterscheidet dabei ueber die im set_id-
            Slot mitgelieferte Gruppe: Sets-Ordner -> Set-Service-Entries
            aller Sets unter dem Pfad, Plugins-Ordner -> Plugin-Entries
            (category_plugin_ids).
        """
        if node_type == TYPE_CATEGORY:
            if str(set_id or "") == str(self.model.GROUP_SETS):
                entries: List[Dict[str, str]] = []
                for set_id_under in self.model.category_set_ids(
                        plugin_id or ""):
                    definition = self.model.find_set(set_id_under) or {}
                    services = definition.get("services") or {}
                    order = definition.get("execution_order") \
                        or list(services.keys())
                    for iid in order:
                        cfg = services.get(iid) or {}
                        if not isinstance(cfg, dict):
                            continue
                        entries.append({
                            "node_type": TYPE_SERVICE,
                            "set_id": str(set_id_under),
                            "instance_id": str(iid),
                            "plugin_id": str(cfg.get("plugin_id") or iid),
                        })
                return entries
            entries: List[Dict[str, str]] = []
            for pid in self.model.category_plugin_ids(plugin_id or ""):
                entries.append({
                    "node_type": TYPE_PLUGIN,
                    "set_id": "",
                    "instance_id": "",
                    "plugin_id": pid,
                })
            return entries
        if node_type in (TYPE_PLUGIN, TYPE_CLONE) and plugin_id:
            # 20.04 (Q7): Clone-Zeilen zeigen wie Plugin-Zeilen den
            # Standalone-Service (feature_id = plugin_id des Parents).
            # 10.08.2026 (Bugfix, Varianten-Params): Zusaetzlich werden die
            # presetspezifischen Parameter (indicator_presets) mitgegeben -
            # das Panel zeigt die EIGENEN Parameter der Variante (service_id
            # traegt hier den instance_hash, MasterTree._emit_selection_-
            # details), nicht die globalen Standalone-Params.
            if node_type == TYPE_CLONE:
                preset = self._find_preset_for_hash(
                    plugin_id, service_id)
                if preset is not None:
                    return [{
                        "node_type": TYPE_PLUGIN,
                        "set_id": "",
                        "instance_id": "",
                        "plugin_id": str(plugin_id),
                        "preset_params": dict(preset.get("params") or {}),
                        "preset": preset,
                    }]
            return [{
                "node_type": TYPE_PLUGIN,
                "set_id": "",
                "instance_id": "",
                "plugin_id": str(plugin_id),
            }]
        if node_type in (TYPE_SET, TYPE_SERVICE) and set_id:
            definition = self.model.find_set(set_id) or {}
            services = definition.get("services") or {}
            order = definition.get("execution_order") or list(services.keys())
            entries: List[Dict[str, str]] = []
            for iid in order:
                cfg = services.get(iid) or {}
                if not isinstance(cfg, dict):
                    continue
                entries.append({
                    "node_type": TYPE_SERVICE,
                    "set_id": str(set_id),
                    "instance_id": str(iid),
                    "plugin_id": str(cfg.get("plugin_id") or iid),
                })
            return entries
        return []

    def _rebuild_param_panel(
        self,
        entries: Optional[List[Dict[str, str]]] = None,
        editable_plugin: Optional[str] = None,
    ) -> None:
        """Baut das rechte Parameter-Panel aus den uebergebenen Entries neu.

        Bugfix-Runde 3 (06.08.2026): Die Entries kommen aus `_entries_for_scope`
        (GEKLICKTE Zeile, service_win-Muster) – NICHT mehr aus
        `tree.checked_services()` (Checkboxen). Fuer jeden Eintrag wird eine
        QGroupBox-Spalte ueber `ServiceParamColumnsMixin._build_service_column()`
        erzeugt (seit 06.08.2026 HORIZONTAL nebeneinander, Punkt 1):
          * Set-Service:  cfg aus der Set-Definition (instance_id + params)
          * Plugin-Zeile: cfg aus `_plugin_config(pid)` (Schema-Defaults +
            gespeicherte plugin_params_<id>)
        18.01.01 (E-4): Standalone-Services (editable_plugin gesetzt) sind
        EDITIERBAR (Dirty-Tracking + Speichern); alle anderen bleiben
        read-only (deaktivierte QGroupBox).
        Danach werden Panel-Breite (Default: 2 Spalten, Punkt 2) und
        Fensterbreite (Punkt 3) angepasst.
        """
        self._clear_panel()
        host = self._param_host
        host._current_plugin_editing = None
        host._current_set_definition = None
        host._current_preset_editing = None
        host._set_param_actions_visible(False)
        entries = list(entries or [])
        if not entries:
            self.param_box_layout.addWidget(
                QLabel("Keine Auswahl – klicke eine Zeile im Baum."))
            # Bugfix 06.08.2026 (Runde 3): Der abschliessende Stretch nimmt
            # den freien Platz auf – der Hinweis behaelt seine Default-Breite.
            self.param_box_layout.addStretch(1)
            self._apply_panel_size(0)
            # 08.08.2026 (Bugfix): Container auf Layout-Groesse nachziehen
            # (Scrollbalken statt Fensterhoehen-Anpassung).
            QTimer.singleShot(0, self._resize_param_container_deferred)
            return
        for entry in entries:
            pid = str(entry.get("plugin_id") or "")
            if entry["node_type"] == TYPE_SERVICE:
                iid = str(entry.get("instance_id") or "")
                cfg = self.model.find_service(
                    str(entry.get("set_id") or ""), iid) or {}
            else:
                iid = pid
                cfg = host._plugin_config(pid)
                # 10.08.2026 (Bugfix, Varianten-Params): presetspezifische
                # Parameter ueberschreiben die Registry-/Standalone-Defaults.
                preset_params = entry.get("preset_params")
                if isinstance(preset_params, dict) and preset_params:
                    merged = dict(cfg.get("params") or {})
                    merged.update(preset_params)
                    cfg["params"] = merged
                # Preset fuer den Save-Pfad merken (indicator_presets statt
                # global_settings).
                host._current_preset_editing = entry.get("preset")
            editable = bool(editable_plugin) and pid == editable_plugin
            try:
                box = host._build_service_column(iid, pid, cfg)
            except Exception as e:  # defensiv: Plugin/Schema-Fehler
                box = None
                self.param_box_layout.addWidget(
                    QLabel(f"Parameteranzeige nicht verfügbar: {e}"))
            if box is not None:
                if not editable:
                    box.setEnabled(False)
                    box.setToolTip("Read-Only – Parameter der gewählten "
                                   "Datenquelle (editierbar im ServiceWindow)")
                else:
                    # 18.01.01 (E-4): Editierbarer Standalone-Service –
                    # RAM-Definition fuer das Dirty-Tracking (_on_param_changed)
                    # bereitstellen; Persistenz via _save_plugin_params.
                    definition: Dict[str, Any] = {
                        "set_id": "",
                        "display_name": pid,
                        "description": str(cfg.get("description") or ""),
                        "execution_order": [pid],
                        "services": {pid: cfg},
                    }
                    host._current_plugin_editing = pid
                    host._current_set_definition = definition
                self.param_box_layout.addWidget(box)
        # Bugfix 06.08.2026 (Runde 3): Die einzelnen Service-Rahmen
        # (QGroupBox) werden beim Vergroessern NICHT gestreckt – sie behalten
        # ihre Default-Breite (sizeHint). Ohne abschliessenden Stretch
        # verteilt QHBoxLayout den freien Platz gleichmaessig auf alle
        # Spalten (Stretch-Faktor 0 = Aufteilung des Ueberschusses). Der
        # Stretch (Faktor 1) absorbiert den gesamten freien Platz.
        self.param_box_layout.addStretch(1)
        self._apply_panel_size(len(entries))
        # 08.08.2026 (Bugfix): Container auf Layout-Groesse nachziehen –
        # ScrollArea zeigt Scrollbalken statt Fensterhoehen-Anpassung.
        QTimer.singleShot(0, self._resize_param_container_deferred)

    def _apply_panel_size(self, col_count: int) -> None:
        """Punkt 2+3: Panel-MINIMUM-Breite (Default: ZWEI Spalten).

        Bei 1 Spalte wird das Minimum auf die Spaltenbreite gesetzt; ab 2
        Spalten gilt der Default (Platz fuer 2 nebeneinander). Mehr Spalten
        erzeugen eine horizontale Scrollbar (QScrollArea, AsNeeded). Die Box
        ist seit 06.08.2026 NICHT mehr fix: Der Benutzer kann das Fenster
        verzoegern/vergroessern – der Tree behaelt seine feste Breite
        (Punkt 4), die Parameter-Box waechst mit bzw. schrumpft bis zu
        diesem Minimum (Punkt 3).
        """
        widths = []
        for i in range(self.param_box_layout.count()):
            item = self.param_box_layout.itemAt(i)
            w = item.widget()
            if w is not None and w.sizeHint().isValid():
                widths.append(w.sizeHint().width())
        if not widths:
            panel_w = 280
        elif col_count >= 2:
            # Default: ZWEI Spalten nebeneinander (+ Puffer fuer Rahmen/
            # vertikale Scrollbar, damit keine horizontale Scrollbar erscheint).
            panel_w = widths[0] + widths[1] \
                + self.param_box_layout.spacing() + PANEL_BUFFER
        else:
            panel_w = widths[0] + PANEL_BUFFER
        panel_w = max(panel_w, 280)
        self._panel_min_width = panel_w
        # Minimum auf dem PANEL-WIDGET (Direkt-Kind im Body-Layout) UND der
        # ScrollArea: das Panel kann beim Fenster-Vergroessern mitwachsen,
        # aber nicht unter die 2-Spalten-Default-Groesse schrumpfen.
        self.param_panel.setMinimumWidth(panel_w)
        self.param_scroll.setMinimumWidth(panel_w)
        # Container-Minimum: volle Breite aller Spalten -> horizontale
        # Scrollbar, sobald der Inhalt breiter als das Panel ist (Punkt 2).
        total_w = sum(widths) + self.param_box_layout.spacing() * max(
            0, len(widths) - 1)
        self.param_container.setMinimumWidth(max(total_w, panel_w))
        # Punkt 3: Fensterbreite exakt bis zur rechten Kante der Parameter-Box.
        self._fit_dialog_width()

    def _resize_param_container_deferred(self) -> None:
        """Setzt den Param-Container auf seine Layout-Groesse (Scrollbar).

        08.08.2026 (Bugfix, ServiceWindow-Muster 07.08.2026): Bei
        widgetResizable=False behaelt der Container seine natuerliche
        Groesse (hier: layout().sizeHint()). Wird er groesser als der
        Viewport (viele/hohe Parameter), zeigt die ScrollArea vertikale
        Scrollbalken – die Dialog-Fensterhoehe bleibt FIX. Deferred (nach
        deleteLater der Alt-Spalten), damit der sizeHint nicht veraltet
        gelesen wird (QWidgetItemV2-Cache, Muster
        `_resize_param_box_deferred` in param_columns.py).
        """
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        except (RuntimeError, AttributeError):
            pass
        try:
            lay = self.param_container.layout()
            if lay is None:
                return
            self.param_container.updateGeometry()
            self.param_container.resize(lay.sizeHint())
            self.param_scroll.updateGeometry()
        except (RuntimeError, AttributeError):
            pass

    def _fit_dialog_width(self) -> None:
        """Punkt 3: Fensterbreite == rechte Kante der Parameter-Box.

        Misst die tatsaechliche rechte Kante des Panel-Widgets (Direkt-Kind
        des Dialogs, Minimum-Breite) und zieht das Fenster nach, falls die
        Kante ueber die Dialogkante hinauslaeuft. Beim Oeffnen gilt:
        Breite = Margins + fester Tree + Spacing + Panel-Minimum (2 Spalten).
        Eine vom Benutzer bewusst groessere Breite (gespeicherte Geometrie,
        Punkt 4) bleibt erhalten. Nach dem Anzeigen wird der Fit ueber
        `showEvent` + QTimer erneut angestossen (stabile Layout-Geometrie).
        """
        self.layout().activate()
        # 10.08.2026 (Bugfix, UI-Splitter): Das Panel liegt jetzt in einem
        # QSplitter - die rechte Kante muss dialog-relativ bestimmt werden
        # (mapTo statt geometry(), dessen Eltern-System der Splitter ist).
        # Das Panel ist das rechte Splitter-Widget; target = Tree-Breite +
        # Handle + Panel-Minimum + Margins waechst mit dem Inhalt mit.
        splitter = getattr(self, "_splitter", None)
        if splitter is not None:
            margins = self.layout().contentsMargins()
            tree_w = self.selector.size().width()
            handle = splitter.handleWidth()
            panel_min = max(self.param_panel.minimumWidth(),
                            self.param_panel.sizeHint().width())
            target = (margins.left() + tree_w + handle + panel_min
                      + margins.right() + 1)
        else:
            panel_right = self.param_panel.geometry().right()  # dialog-relativ
            margins_right = self.layout().contentsMargins().right()
            target = panel_right + margins_right + 1
        target = max(target, self.minimumWidth())
        if self.width() < target:
            self.resize(target, self.height())

    def showEvent(self, event) -> None:
        """Punkt 3: Fensterbreite nach dem Anzeigen nachziehen (deferred).

        Vor `show()` sind die Layout-Geometrien (Positionen) noch nicht
        berechnet – der deferred Fit stellt sicher, dass die Fensterbreite
        exakt an der rechten Kante der Parameter-Box endet.
        """
        super().showEvent(event)
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._fit_dialog_width)
        except Exception:
            pass

    def _clear_panel(self) -> None:
        """Leert das Parameter-Panel (alle Spalten + Control-Registry)."""
        while self.param_box_layout.count():
            item = self.param_box_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        host = self._param_host
        host._service_param_controls.clear()
        host._service_desc_controls.clear()
        # 08.08.2026 (Bugfix): Schema-/Label-Registrys ebenfalls zuruecksetzen
        # (Muster `_clear_service_columns` in param_columns.py) – sonst bleiben
        # Conditional-Visibility-Schemas und Info-Labels fremder Instanzen
        # haengen, wenn der naechste Spaltenaufbau weniger Spalten baut.
        host._mode_schemas.clear()
        host._service_param_labels.clear()
        host._service_info_labels.clear()
        host._service_info_pids.clear()

    # ------------------------------------------------------------------
    # Punkt 4: Geometrie-Persistenz (global_settings, IndicatorDialog-Muster)
    # ------------------------------------------------------------------
    def _restore_geometry(self) -> None:
        """Stellt die letzte Position/Groesse des Dialogs wieder her.

        Gespeichert wird in global_settings (save_dialog_geometry) – der
        Dialog ist kein PersistentWindow. Beim naechsten Panel-Aufbau wird
        die Breite ggf. auf den Inhalts-Bedarf angehoben (Punkt 3).
        """
        sm = self._state_manager
        if sm is None:
            return
        try:
            geom = sm.get_dialog_geometry(DIALOG_GEOMETRY_KEY)
        except Exception:
            return
        if not geom:
            return
        try:
            pos_x = geom.get("pos_x")
            pos_y = geom.get("pos_y")
            w = geom.get("width")
            h = geom.get("height")
            # Runde 10 (Bug 5): Gegen ALLE Screens pruefen - eine Position
            # auf dem 2. Monitor ist NICHT off-screen (Fallback nur, wenn
            # sie auf KEINEM Screen liegt). Vorher wurde nur der Primary-
            # Screen geprueft -> Position auf Monitor 2 wurde verworfen.
            screens = [s.availableGeometry()
                       for s in QApplication.screens()]
            if pos_x is not None and pos_y is not None:
                on_screen = any(
                    (scr.x() - 100 <= pos_x <= scr.right())
                    and (scr.y() - 100 <= pos_y <= scr.bottom())
                    for scr in screens)
                if not on_screen:
                    pos_x = pos_y = None
                else:
                    self.move(pos_x, pos_y)
            if w and h:
                self.resize(max(int(w), self.minimumWidth()), int(h))
        except Exception:
            pass

    def _save_geometry(self) -> None:
        """Speichert die aktuelle Position/Groesse des Dialogs (Punkt 4)."""
        sm = self._state_manager
        if sm is None:
            return
        try:
            p = self.pos()
            s = self.size()
            sm.save_dialog_geometry(
                DIALOG_GEOMETRY_KEY, p.x(), p.y(), s.width(), s.height())
        except Exception:
            pass

    def done(self, r: int) -> None:
        """Wird bei jedem Schliessen gerufen (accept/reject/Esc/X) ->
        Geometrie vor dem Schliessen speichern (Punkt 4)."""
        self._save_geometry()
        super().done(r)

```

--------------------------------------------------

### DATEI: serviceui/service_selector_widget.py
```py
# serviceui/service_selector_widget.py
"""
Service-UI: Generisches Service-Auswahl-Widget (Phase 15 15.02).

Konfigurierbares PySide6-Widget mit zwei Betriebsmodi:

  * Modus A (SELECT_ONLY): Kompakte Dropdown-Auswahl (Set-Combo + Service-
    Combo) fuer die schwellenfreie Wiederverwendung in Analytics (15.03),
    Backtester oder Charts. Emittiert `selection_changed(set_id, service_id)`.
  * Modus B (FULL_EDIT):  Vollstaendiges Master-Tree-Widget fuer service_win.py
    (Erstellen, Umsortieren, Loeschen ueber das Kontextmenue). Seit
    05.08.2026 OHNE Aktions-Toolbar: die CRUD-/Order-Buttons oberhalb des
    Baums sind entfernt – der MasterTree hat die volle vertikale Hoehe der
    linken Spalte und alle Struktur-Aktionen laufen ueber das Kontextmenue.
  * Modus C (SELECT_MULTI): MasterTree mit Checkboxen (15.03-E) – alle Set-,
    Service-, Standalone- und Plugin-Knoten sind anhakbar; wird vom
    `ServiceSelectorDialog` (Analytics-Datenquellen) eingebettet. Die
    Auswahl-API (`checked_services`/`checked_feature_ids`/...) liegt im
    MasterTree.

Beide Modi werden ausschliesslich aus dem `ServiceSelectorModel` befuellt
(lesendes Datenmodell, EventBus-Live-Sync, Invariante 4/5).
"""

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from analytics.engine.service_selector_model import ServiceSelectorModel
from serviceui.master_tree import MasterTree


class ServiceSelectorWidget(QWidget):
    """Wiederverwendbares Auswahl-Widget fuer Service-Sets & Services."""

    #: Betriebsmodi
    MODE_SELECT_ONLY = "SELECT_ONLY"
    MODE_FULL_EDIT = "FULL_EDIT"
    # 15.03-E: Multi-Select (Checkbox-MasterTree) fuer den
    # ServiceSelectorDialog (Analytics-Datenquellen).
    MODE_SELECT_MULTI = "SELECT_MULTI"

    #: Emittiert (set_id, service_id) – service_id leer, wenn nur ein Set
    #: gewaehlt wurde (bzw. in SELECT_ONLY ohne aktives Set).
    selection_changed = Signal(str, str)
    #: Bugfix 05.08.2026: Klick auf den Info-Button im MasterTree (FULL_EDIT)
    #: wird an den Aufrufer weitergereicht (set_id, service_id, plugin_id).
    info_requested = Signal(str, str, str)
    #: 20.03.02 (F4): Info-Button auf Kategorie-Ordnern wird an den Aufrufer
    #: weitergereicht (group, category_path) – ServicePicker zeigt die
    #: Read-Only-Ordner-Info (ServiceWindow-Muster).
    category_info_requested = Signal(str, str)

    def __init__(self, mode: str = MODE_SELECT_ONLY, model: Optional[ServiceSelectorModel] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.model = model or ServiceSelectorModel()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Modus-Bausteine (werden je nach Modus erzeugt/eingefuegt)
        self._compact_row: Optional[QWidget] = None
        self.master_tree: Optional[MasterTree] = None

        self.model.data_changed.connect(self._on_model_changed)
        self.set_mode(mode)

    # -------------------------------------------------------------------------
    # Modus-Umschaltung
    # -------------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """Baut das Widget fuer den gewuenschten Betriebsmodus auf.

        Args:
            mode: MODE_SELECT_ONLY (Dropdown) oder MODE_FULL_EDIT (MasterTree).
        """
        mode = mode or self.MODE_SELECT_ONLY
        # Alte Bausteine entfernen
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._compact_row = None
        self.master_tree = None

        if mode == self.MODE_FULL_EDIT:
            self._build_full_edit()
        elif mode == self.MODE_SELECT_MULTI:
            self._build_select_multi()
        else:
            self._build_select_only()

    def _build_select_multi(self) -> None:
        """Modus C (15.03-E): MasterTree mit Checkboxen (Multi-Select).

        Fuer den ServiceSelectorDialog (Analytics-Datenquellen): Alle Set-,
        Service-, Standalone- und Plugin-Knoten sind anhakbar
        (MasterTree.set_checkable(True)). Kein CRUD-/Run-Kontextmenue –
        der Dialog zeigt ausschliesslich die Auswahl + Read-Only-Parameter.
        """
        self.master_tree = MasterTree(self.model, parent=self)
        self.master_tree.set_checkable(True)
        self._layout.addWidget(self.master_tree, 1)

        self.master_tree.selection_changed.connect(self.selection_changed)
        # Bugfix 05.08.2026: Info-Button-Klicks im MasterTree re-emittieren.
        self.master_tree.info_requested.connect(self.info_requested)
        # 20.03.02 (F4): Kategorie-Ordner-Info ebenfalls re-emittieren.
        self.master_tree.category_info_requested.connect(
            self.category_info_requested)

    def _build_select_only(self) -> None:
        """Modus A: kompakte Set-/Service-Combos."""
        self._compact_row = QWidget(self)
        row = QHBoxLayout(self._compact_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(QLabel("Set:"))
        self.combo_set = QComboBox()
        self.combo_set.setMinimumWidth(140)
        row.addWidget(self.combo_set, 1)
        row.addWidget(QLabel("Service:"))
        self.combo_service = QComboBox()
        self.combo_service.setMinimumWidth(140)
        row.addWidget(self.combo_service, 1)

        self.combo_set.currentIndexChanged.connect(self._on_set_combo_changed)
        self.combo_service.currentIndexChanged.connect(self._emit_combo_selection)
        self._layout.addWidget(self._compact_row)
        self._repopulate_select_only()

    def _build_full_edit(self) -> None:
        """Modus B: MasterTree (2 Spalten) – volle Hoehe, KEINE Toolbar.

        05.08.2026: Die Aktions-Toolbar (btn_add/btn_remove/Order-Pfeile)
        oberhalb des Baums ist entfernt – der MasterTree fuellt die gesamte
        vertikale Hoehe der linken Spalte. Alle Struktur-Aktionen (Set
        anlegen/umbenennen/loeschen, Service hinzufuegen/verschieben/
        entfernen) und die neuen Run-Aktionen ('▶️ Diesen Service ausführen' /
        '▶️ Alle Services ausführen') laufen ueber das Kontextmenue
        (entkoppelte Signale, der Orchestrator verknuepft sie mit seinen
        Handlern)."""
        self.master_tree = MasterTree(self.model, parent=self)
        self._layout.addWidget(self.master_tree, 1)

        self.master_tree.selection_changed.connect(self.selection_changed)
        # Bugfix 05.08.2026: Info-Button-Klicks im MasterTree re-emittieren.
        self.master_tree.info_requested.connect(self.info_requested)
        # 20.03.02 (F4): Kategorie-Ordner-Info ebenfalls re-emittieren.
        self.master_tree.category_info_requested.connect(
            self.category_info_requested)

    # -------------------------------------------------------------------------
    # Modell-Sync
    # -------------------------------------------------------------------------

    def _on_model_changed(self) -> None:
        """Modell-Aenderung (EventBus): SELECT_ONLY-Combos neu befuellen;
        im FULL_EDIT aktualisiert der MasterTree sich selbst."""
        if self._compact_row is not None:
            self._repopulate_select_only()

    def _repopulate_select_only(self) -> None:
        """Befuellt Set- und Service-Combo aus dem Modell (deterministisch)."""
        current_set = self.combo_set.currentData() if hasattr(self, "combo_set") else None
        sets = self.model.get_sets()

        self.combo_set.blockSignals(True)
        self.combo_set.clear()
        self.combo_set.addItem("(kein Set)", None)
        for s in sets:
            self.combo_set.addItem(
                str(s.get("display_name") or s.get("set_id") or "Unbenannt"),
                s.get("set_id"))
        if current_set is not None:
            idx = self.combo_set.findData(current_set)
            if idx >= 0:
                self.combo_set.setCurrentIndex(idx)
        self.combo_set.blockSignals(False)

        self._fill_service_combo(self.combo_set.currentData())

    def _fill_service_combo(self, set_id: Optional[str]) -> None:
        """Befuellt die Service-Combo mit den Services des gewaehlten Sets."""
        self.combo_service.blockSignals(True)
        self.combo_service.clear()
        self.combo_service.addItem("(Service wählen)", None)
        if set_id:
            s = self.model.find_set(set_id)
            services = (s or {}).get("services") or {}
            for iid in (s or {}).get("execution_order") or []:
                cfg = services.get(iid) or {}
                pid = cfg.get("plugin_id") or iid
                self.combo_service.addItem(f"{iid} [{pid}]", iid)
        self.combo_service.blockSignals(False)

    def _on_set_combo_changed(self, _index: int) -> None:
        self._fill_service_combo(self.combo_set.currentData())
        self._emit_combo_selection()

    def _emit_combo_selection(self) -> None:
        set_id = self.combo_set.currentData() or ""
        service_id = self.combo_service.currentData() or ""
        self.selection_changed.emit(set_id, service_id)

    # -------------------------------------------------------------------------
    # Oeffentliche Auswahl-API
    # -------------------------------------------------------------------------

    def current_set_id(self) -> str:
        if self._compact_row is not None:
            return self.combo_set.currentData() or ""
        if self.master_tree is not None:
            return self.master_tree.current_set_id()
        return ""

    def current_service_id(self) -> str:
        if self._compact_row is not None:
            return self.combo_service.currentData() or ""
        if self.master_tree is not None:
            return self.master_tree.current_service_id()
        return ""

    def get_plugin_ids(self) -> List[str]:
        """Alle verfuegbaren Plugin-IDs (sortiert) – fuer das [➕]-Popup."""
        return sorted(self.model.get_plugins().keys())

    def refresh(self) -> None:
        """Erzwingt einen Modell-Refresh (z.B. nach manuellen DB-Aenderungen)."""
        self.model.refresh()

```

--------------------------------------------------

### DATEI: serviceui/service_set_utils.py
```py
# serviceui/service_set_utils.py
"""
Service-UI: Wiederverwendbare Helfer für das Service-Fenster.

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert –
Verhalten unverändert.
"""

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 11.08.2026 (Bugfixing-Modus): Varianten-/Clone-Aufloesung fuer Runs
# ---------------------------------------------------------------------------
def variant_run_entries(
    plugin_id: str,
    state_manager,
    base_config_fn,
) -> List[tuple]:
    """Erzeugt die ausfuehrbaren Eintraege (instance_id, config) eines Plugins.

    Bugfix 11.08.2026 (User-Meldung 2): 'Kontextmenue auf eine Variante wird
    faelschlicherweise bei allen Varianten ausgefuehrt/angezeigt'. Ein Clone-
    Run muss mit den PARAMETERN DER VARIANTE + deren instance_hash laufen,
    damit (a) die richtigen Parameter berechnet werden und (b) das Datum im
    Baum an der Variante (per Hash) aktualisiert wird (Bug 1).

    * Plugin MIT aktiven Presets: je aktivem Preset ein Eintrag
      (instance_id = '{plugin_id}#{instance_hash}') – Parameter = Preset-
      Parameter, instance_hash = deterministischer Hash daraus. Die Config
      traegt zusaetzlich 'preset_name' (fuer Dialog/Anzeige).
    * Plugin OHNE aktive Presets: ein Basis-Eintrag (plugin_id,
      base_config_fn(plugin_id)) – Bestandsverhalten.

    Returns:
        Liste von (instance_id, config)-Tupeln; leer, wenn plugin_id leer.
    """
    plugin_id = str(plugin_id or "")
    if not plugin_id:
        return []
    presets: List[Dict[str, Any]] = []
    if state_manager is not None:
        try:
            presets = list(state_manager.list_plugin_presets(plugin_id) or [])
        except Exception:
            presets = []
    active = [p for p in presets if isinstance(p, dict)
              and bool(p.get("is_active_batch"))]
    if active:
        from analytics.engine.service_models import generate_instance_hash
        entries: List[tuple] = []
        for p in active:
            params = dict(p.get("params") or {})
            # 11.08.2026 (Bugfix Varianten-Kollision): Der Hash eines
            # Presets fliesst inkl. preset_name ein (identisch zum
            # ServiceSelectorModel) – Presets mit identischen Parametern aber
            # unterschiedlichen Namen erhalten UNTERSCHIEDLICHE Hashes.
            # Dadurch matcht der Kontextmenue-Filter ('Kontextmenue auf eine
            # Variante') GENAU EINE Variante (vorher: Hash-Kollision -> alle
            # Varianten wurden ausgefuehrt/angezeigt).
            preset_name = str(p.get("preset_name") or "Default")
            inst_hash = generate_instance_hash(
                plugin_id, params, preset_name=preset_name)
            cfg: Dict[str, Any] = {
                "plugin_id": plugin_id,
                "lookback": 1000,
                "params": params,
                "version": str(p.get("version") or "0.0.0"),
                "instance_hash": inst_hash,
                "preset_name": preset_name,
            }
            entries.append((f"{plugin_id}#{inst_hash}", cfg))
        return entries
    base = base_config_fn(plugin_id)
    if not isinstance(base, dict):
        base = {"plugin_id": plugin_id}
    return [(plugin_id, base)]


# ==========================================================================
# 18.01.03 (E1): Separater global_settings-Key fuer den Kategorie-Override
# eines Standalone-Plugins (NICHT plugin_params_<id> – das bleibt exklusiv
# dem Parameter-Preset vorbehalten; siehe Entscheidung E1 im Prüfprotokoll).
# ==========================================================================
PLUGIN_CATEGORY_KEY = "plugin_category_{}"

# 18.01.03 (E3-revidiert, Bugfixing-Modus 08.08.2026): Persistenz leerer
# Ordner. Der Benutzer hat E3 widerrufen – leere Ordner duerfen NICHT beim
# naechsten Refresh verschwinden, sondern NUR bei manueller Loeschung im
# Kontextmenue. Dafuer werden die Pfade benutzererzeugter Ordner je Gruppe
# in global_settings persistiert (Key 'tree_folders_<group>', Wert =
# Liste Slash-Pfade OHNE '📁 '-Praefix). Das ServiceSelectorModel mischt
# sie in build_tree() ein; create/delete laufen ueber diese Helfer.
EMPTY_FOLDERS_KEY = "tree_folders_{}"


def set_set_category(set_repo, set_id: str, category_path: str) -> bool:
    """Setzt den Kategorie-Pfad eines Service-Sets (18.01.03, E2).

    Laedt die Definition FRISCH aus der DB (kein Cache), setzt das
    `category`-Feld ("" = Root-Ebene) und persistiert additiv via
    save_set(). record_snapshot=False – ein Ordner-Verschieben ist eine
    interne Struktur-Verwaltung (wie die P14-04 Bestands-Migration) und
    erzeugt KEINE Snapshot-Historie (Invariante 9).

    Returns:
        True bei Erfolg (Set existierte und wurde gespeichert).
    """
    set_id = str(set_id or "").strip()
    if not set_id or set_repo is None:
        return False
    try:
        definition = set_repo.get_set(set_id)
    except Exception as e:
        print(f"WARN [service_set_utils] Set '{set_id}' nicht ladbar: {e}")
        return False
    if not definition:
        return False
    definition["category"] = str(category_path or "").strip()
    try:
        set_repo.save_set(definition, record_snapshot=False)
    except Exception as e:
        print(f"WARN [service_set_utils] Kategorie fuer Set '{set_id}' "
              f"nicht gespeichert: {e}")
        return False
    return True


def set_plugin_category(state_manager, plugin_id: str,
                        category_path: str) -> bool:
    """Setzt den Kategorie-Override eines Plugins (18.01.03, E1).

    Persistiert den Slash-Pfad unter `plugin_category_<plugin_id>` in
    global_settings ("" = Root-Ebene hebt metadata['category'] auf). Der
    Override hat VORRANG vor metadata['category'] (Modell _category_parts).
    Das bestehende `plugin_params_<id>` bleibt unangetastet.

    Returns:
        True bei Erfolg (plugin_id vorhanden und gespeichert).
    """
    plugin_id = str(plugin_id or "").strip()
    if not plugin_id or state_manager is None:
        return False
    try:
        state_manager.save_global_value(
            PLUGIN_CATEGORY_KEY.format(plugin_id),
            str(category_path or "").strip())
    except Exception as e:
        print(f"WARN [service_set_utils] Kategorie fuer Plugin '{plugin_id}' "
              f"nicht gespeichert: {e}")
        return False
    return True


def list_empty_folders(state_manager, group: str) -> List[str]:
    """Alle persistierten Pfade benutzererzeugter leerer Ordner einer Gruppe.

    Quelle: global_settings (Key 'tree_folders_<group>', 18.01.03 E3-
    revidiert). Liefert eine deduplizierte Liste Slash-Pfade OHNE
    '📁 '-Praefix (z.B. ['Swing Points', 'Swing Points/Geometrie']);
    Fehler -> [] (defensiv).
    """
    if state_manager is None:
        return []
    try:
        raw = state_manager.get_global_value(
            EMPTY_FOLDERS_KEY.format(str(group or "").strip()), [])
    except Exception as e:
        print(f"WARN [service_set_utils] Leere-Ordner-Liste der Gruppe "
              f"'{group}' nicht lesbar: {e}")
        return []
    result: List[str] = []
    if isinstance(raw, list):
        for p in raw:
            p = str(p or "").strip().strip("/")
            if p and p not in result:
                result.append(p)
    return result


def save_empty_folders(state_manager, group: str, paths) -> bool:
    """Persistiert die Leere-Ordner-Liste einer Gruppe (Upsert).

    Returns:
        True bei Erfolg.
    """
    if state_manager is None:
        return False
    cleaned: List[str] = []
    for p in paths or []:
        p = str(p or "").strip().strip("/")
        if p and p not in cleaned:
            cleaned.append(p)
    try:
        state_manager.save_global_value(
            EMPTY_FOLDERS_KEY.format(str(group or "").strip()), cleaned)
    except Exception as e:
        print(f"WARN [service_set_utils] Leere-Ordner-Liste der Gruppe "
              f"'{group}' nicht speicherbar: {e}")
        return False
    return True


def create_empty_folder(state_manager, group: str, path: str) -> bool:
    """Registriert einen benutzererzeugten (ggf. leeren) Ordner.

    Haengt den Slash-Pfad an die Leere-Ordner-Liste der Gruppe an
    (idempotent – bereits vorhandene Pfade werden nicht dupliziert). Das
    Modell rendert den Ordner daraufhin dauerhaft (auch ohne Kinder), bis
    er manuell ueber delete_empty_folder() entfernt wird.

    Returns:
        True, wenn der Pfad (neu) persistiert wurde.
    """
    path = str(path or "").strip().strip("/")
    if not path:
        return False
    paths = list_empty_folders(state_manager, group)
    if path in paths:
        return False
    paths.append(path)
    return save_empty_folders(state_manager, group, paths)


def delete_empty_folder(state_manager, group: str, path: str) -> bool:
    """Entfernt einen benutzererzeugten Ordner (manuelle Loeschung).

    Loescht NUR den persistierten Ordner-Eintrag der Gruppe; Kinder
    (falls vorhanden) bleiben unangetastet. Die UI erlaubt die Loeschung
    nur fuer Ordner ohne Kinder (MasterTree-Guard).

    Returns:
        True, wenn der Pfad vorhanden war und entfernt wurde.
    """
    path = str(path or "").strip().strip("/")
    if not path:
        return False
    paths = list_empty_folders(state_manager, group)
    if path not in paths:
        return False
    paths.remove(path)
    return save_empty_folders(state_manager, group, paths)


def ensure_folder_path(state_manager, group: str, path: str) -> bool:
    """Stellt sicher, dass die Ordnerkette von `path` persistiert ist.

    18.01.03 (E3-revidiert, Bugfix 08.08.2026): Wird nach Struktur-
    Aenderungen aufgerufen (letztes Kind aus einem Ordner verschoben,
    Ordner per Drag verschoben), damit benutzererzeugte Ordner auch dann
    sichtbar bleiben, wenn ihr letztes Kind entzogen wurde. Ergaenzt
    idempotent ALLE Kettenglieder von `path` in der Leere-Ordner-Liste
    der Gruppe (tree_folders_<group>) – ein Kettenglied, das aktuell noch
    Kinder hat, ist als redundanter Eintrag unschaedlich (build_tree
    dedupliziert ueber _ensure_category_path).

    Returns:
        True, wenn die Kette gesichert ist (neu ergaenzt oder bereits
        vorhanden); False bei fehlendem state_manager/Speicherfehler.
    """
    path = str(path or "").strip().strip("/")
    if not path or state_manager is None:
        return False
    parts = [p.strip() for p in path.split("/") if p.strip()]
    if not parts:
        return False
    paths = list_empty_folders(state_manager, group)
    changed = False
    for i in range(len(parts)):
        p = "/".join(parts[: i + 1])
        if p not in paths:
            paths.append(p)
            changed = True
    if changed:
        return save_empty_folders(state_manager, group, paths)
    return True


def _replace_prefix(path: str, old_path: str, new_path: str) -> str:
    """Ersetzt das Pfad-Praefix old_path in path durch new_path.

    Nur echte Ordner-Grenzen zaehlen: 'A/B' ersetzt 'A' UND 'A/C' (unter
    'A'), aber NICHT 'AB'. Liefert path unveraendert, wenn old_path nicht
    Praefix ist.
    """
    if path == old_path:
        return new_path
    if path.startswith(old_path + "/"):
        return new_path + path[len(old_path):]
    return path


def rename_category(model, set_repo, state_manager, group: str,
                    old_path: str, new_path: str) -> int:
    """Benennt/verschiebt einen Kategorie-Ordner (String-Replace, 18.01.03).

    Fuehrt fuer ALLE Kinder des Ordners ein Pfad-Update durch:
      * group == 'sets'     -> jedes Set mit category-Praefix old_path wird
                               via set_set_category() neu gespeichert.
      * group == 'plugins'  -> jedes Plugin mit aufgeloestem Pfad-Praefix
                               old_path erhaelt einen Kategorie-Override auf
                               den neuen Pfad (plugin_category_<id>). Auch
                               Plugins, deren Kategorie bisher aus
                               metadata['category'] stammte, werden dadurch
                               dauerhaft umgezogen (Override gewinnt).
    Der Aufrufer emittiert danach `event_bus.service_set_changed`.

    Returns:
        Anzahl der betroffenen Elemente (Sets bzw. Plugins).
    """
    old_path = str(old_path or "").strip().strip("/")
    new_path = str(new_path or "").strip().strip("/")
    if not old_path or old_path == new_path:
        return 0
    group = str(group or "").strip()
    count = 0
    try:
        if group == "sets":
            for s in (model.get_sets() if model is not None else []) or []:
                cat = str(s.get("category") or "").strip()
                if not cat:
                    continue
                updated = _replace_prefix(cat, old_path, new_path)
                if updated != cat and set_set_category(
                        set_repo, str(s.get("set_id") or ""), updated):
                    count += 1
        else:
            plugins = (model.get_plugins() if model is not None else {}) or {}
            for pid in sorted(plugins.keys()):
                current = (model.plugin_category_path(pid)
                           if model is not None else "")
                if not current:
                    continue
                updated = _replace_prefix(current, old_path, new_path)
                if updated != current and set_plugin_category(
                        state_manager, pid, updated):
                    count += 1
        # 18.01.03 (E3-revidiert): Auch persistierte leere Ordner der Gruppe
        # umziehen (Praefix-Replace auf die 'tree_folders_<group>'-Liste),
        # damit benutzererzeugte Ordner ihren Platz behalten.
        try:
            empty_paths = list_empty_folders(state_manager, group)
            if empty_paths:
                updated_paths = [
                    _replace_prefix(p, old_path, new_path)
                    for p in empty_paths]
                if updated_paths != empty_paths:
                    if save_empty_folders(state_manager, group,
                                          updated_paths):
                        count += sum(1 for a, b in zip(empty_paths,
                                                       updated_paths)
                                     if a != b)
        except Exception as e:
            print(f"WARN [service_set_utils] Leere-Ordner-Rename "
                  f"'{old_path}' -> '{new_path}' fehlgeschlagen: {e}")
        # 18.01.03 (E3-revidiert, Bugfix 08.08.2026): Der QUELL-Ordner
        # bleibt nach dem Wegziehen seines letzten Kindes sichtbar (auch
        # wenn er bisher nur aus echten Kindern bestand und NICHT in der
        # Leere-Ordner-Liste stand). Idempotent – ein Ordner mit verbleibenden
        # Kindern bekommt einen redundanten Eintrag (unschaedlich).
        try:
            ensure_folder_path(state_manager, group, old_path)
        except Exception as e:
            print(f"WARN [service_set_utils] Leere-Ordner-Sicherung des "
                  f"Quell-Ordners '{old_path}' fehlgeschlagen: {e}")
    except Exception as e:
        print(f"WARN [service_set_utils] Ordner-Rename '{old_path}' -> "
              f"'{new_path}' fehlgeschlagen: {e}")
    return count


def _available_plugin_ids() -> str:
    """Alle registrierten Plugin-IDs (sortiert, kommasepariert).

    Phase 13 Schritt 6-Korrektur: Die Verfügbarkeit wird dynamisch aus der
    PluginRegistry abgeleitet (srv_grid_lines, srv_proximity, ...),
    NICHT hartkodiert auf einen Indikator-Namen.
    """
    try:
        from analytics.features.feature_builder import PluginRegistry
        return ", ".join(sorted(PluginRegistry().plugins.keys()))
    except Exception:
        return "?"


def _sets_using_plugin(plugin_id: str, sets: List[Dict[str, Any]]) -> List[str]:
    """P14-04-E: Namen aller Service-Sets, die einen Service mit dieser
    plugin_id enthalten.

    Basis der Service-Sperre: Einzel-Services, die in einem gespeicherten
    Service-Set vorkommen, dürfen im Service-Fenster nicht entfernt werden
    (Indikator-Basisservices wie srv_grid_lines/srv_proximity bleiben funktionsfähig).
    Beim Löschversuch wird der Name des verwendeten Sets angezeigt.
    """
    names: List[str] = []
    for s in sets or []:
        services = s.get("services") or {}
        if any((cfg or {}).get("plugin_id") == plugin_id
               for cfg in services.values()):
            names.append(str(s.get("display_name") or s.get("set_id") or "?"))
    return names


def prepare_worker_definition(
    definition: Dict[str, Any],
    lookback_limit: int,
) -> Dict[str, Any]:
    """Bereitet eine ServiceSetDefinition für die gezielte Worker-Ausführung
    auf (serviceui/run_worker.py; der historische ServiceSetRunWorker bzw.
    set_run_worker.py wurde am 05.08.2026 mit der Phase-13-Box entfernt). Die
    übergebene Definition bleibt unverändert – es wird eine Kopie zurückgegeben.

    05.08.2026 (Bugfix Service-Run, zwei Korrekturen):

    1. Implizite Abhängigkeiten (depends_on): Services OHNE expliziten
       `depends_on`-Eintrag, deren Plugin `dependencies` deklariert
       (z.B. srv_proximity -> ['srv_grid_lines']), erhalten die nächstliegende
       VORHERIGE Instanz in execution_order mit passender plugin_id als
       depends_on. Dadurch liest der ProximityService seine Linienliste
       aus shared_state[depends_on[0]] (vorher: 'fertig (kein
       Feature-Store-Payload)' bei UI-angelegten Sets, die kein depends_on
       speichern). Explizit gesetzte Werte werden NIE überschrieben
       (Indikator-intern grid_1 -> prox_1 bleibt unverändert).

    2. Lookback-Override: Jede Service-Instanz läuft mit `lookback_limit`
       (Scanner-Candles (max) aus den App-Optionen, AppSettings.
       scanner_candle_limit) als Scan-Fenster – damit verwenden ALLE
       Services dieselbe Datenbasis wie der Historical Scanner (vorher:
       gespeicherter Service-lookback, z.B. 1000 Feature-Rows bei
       srv_grid_lines).
    """
    import copy as _copy
    from analytics.features.feature_builder import PluginRegistry

    order = list(definition.get("execution_order") or [])
    services = dict(definition.get("services") or {})
    out = dict(definition)
    out["execution_order"] = order
    out["services"] = services
    if not order or not services:
        return out

    try:
        lb = int(lookback_limit)
        if lb < 1:
            lb = 1
    except (TypeError, ValueError):
        lb = 1

    registry = PluginRegistry()
    resolved = _copy.deepcopy(services)
    position = {iid: idx for idx, iid in enumerate(order)}

    for iid in order:
        cfg = resolved.get(iid)
        if not isinstance(cfg, dict):
            continue

        # 1) Implizite depends_on-Auflösung (nur wenn NICHT explizit gesetzt)
        if not cfg.get("depends_on"):
            pid = str(cfg.get("plugin_id") or iid)
            upstream: List[str] = []
            try:
                plugin = registry.get(pid)
                upstream = list(getattr(plugin, "dependencies", None) or [])
            except (KeyError, AttributeError):
                upstream = []
            if upstream:
                for prev_iid in reversed(order[:position.get(iid, 0)]):
                    prev_cfg = resolved.get(prev_iid)
                    if not isinstance(prev_cfg, dict):
                        continue
                    if str(prev_cfg.get("plugin_id") or prev_iid) in upstream:
                        cfg["depends_on"] = [prev_iid]
                        break

        # 2) Lookback-Override (Scanner-Candles (max) für alle Services)
        cfg["lookback"] = lb

    out["services"] = resolved
    return out


```

--------------------------------------------------

### DATEI: serviceui/service_win.py
```py
# serviceui/service_win.py
"""
Service-Kontrollfenster für PyTrader.
Service-Set-Verwaltung, Parameter-Editor und gezielte Service-Ausführung
(MasterTree-Kontextmenü -> ServiceRunWorker). Der globale Historical Scanner
wurde am 05.08.2026 ersatzlos entfernt – Ausführung nur noch zielgerichtet.
Mit automatischem State Persistence via PersistentWindow.

Phase 13 Schritt 4: Zusätzlich Service-Set-Verwaltung (ServiceSetRepository +
ServiceSetEvaluator): Set-Auswahl (list_sets()), execution_order-Anzeige mit
Up/Down-Umsortierung, Name (leer → Auto-Name), Speichern/Löschen (mit
QMessageBox-Rückfrage) und Ausführen (ServiceSetEvaluator im Hintergrund).

Phase 15 Kapitel 15.1 (U15-D1): Modularisierung – die gewachsene Datei wurde
in den Unterordner serviceui/ verschoben und in Module zerlegt (Verhalten
unverändert):
  * service_set_utils.py   – _available_plugin_ids, _sets_using_plugin
  * param_columns.py       – ServiceParamColumnsMixin (Parameter-Column-Builder)
  * trash_dialog.py        – ServiceSetTrashDialog (Papierkorb-Dialog)
Diese Datei re-exportiert die öffentliche API, damit bestehende Aufrufe
(main.py, Tests) weiter funktionieren.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QFile, QIODevice, QSize, QTimer, Qt, Slot
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QMenu,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTextEdit,
    QVBoxLayout, QWidget,
)

# P15-Bugfix: shiboken6.isValid() schuetzt vor dem Zugriff auf bereits
# C++-seitig zerstoerte Qt-Objekte (Access Violation 0xC0000005 bei wildem
# Klicken, wenn z.B. Controls per deleteLater entfernt werden).
try:
    from shiboken6 import isValid as _qt_valid
except ImportError:  # pragma: no cover
    def _qt_valid(obj) -> bool:  # type: ignore
        return obj is not None

from analytics.engine.description_dialog import (
    ServiceDescriptionDialog,
    ServiceDescriptionEditDialog,
)
from analytics.engine.service_models import generate_instance_hash
from analytics.engine.service_set_repository import ServiceSetRepository
from analytics.engine.set_evaluator import ServiceSetEvaluator
from persistent_win import PersistentWindow, register_persistent_window
from scrollable_content import ContentScrollArea, ContentScrollMixin
from chart.widgets.named_item_actions import NamedItemActionsMixin

# Phase 15 U15-D1: Submodule der Service-UI
from serviceui.service_set_utils import (
    _available_plugin_ids,
    _sets_using_plugin,
    variant_run_entries,
)
from serviceui.param_columns import ServiceParamColumnsMixin
from serviceui.trash_dialog import ServiceSetTrashDialog
from serviceui.new_set_dialog import NewServiceSetDialog
# 05.08.2026: Gezielter Run-Worker fuer die MasterTree-Kontextmenue-Aktionen
# ('▶️ Diesen Service ausführen' / '▶️ Alle Services ausführen') – persistiert
# den feature_store_payload und emittiert den EventBus (Datum live im Baum).
# U15-E (05.08.2026): ALL_TIMEFRAMES = Sentinel fuer Multi-TF-Ausfuehrung.
from serviceui.run_worker import ALL_TIMEFRAMES, ServiceRunWorker
# 21.01b (11.08.2026): TF-Status-Pills (Pill-Strip) – zeigt je Timeframe die
# feature_store-Belegung des gewaehlten Services (fetch_service_tf_status).
from analytics.engine.feature_store_reader import FeatureStoreReader
from serviceui.common_widgets import TfStatusBadgeBar

# Phase 15 15.01: Symbol- & Favoriten-Verwaltung (SymbolsWindow + EventBus)
from serviceui.symbols_win import SymbolsWindow
from symbol_repository import SymbolRepository, get_symbol_repository
from config.event_bus import event_bus

# Phase 15 15.02: Service-UI Refactoring – MasterTree & generischer
# ServiceSelector (ServiceSelectorWidget im Modus FULL_EDIT).
from serviceui.service_selector_widget import ServiceSelectorWidget

# Projekt-Root (eine Ebene über serviceui/) – für die UI-Datei unter ui/.
BASE_DIR = Path(__file__).resolve().parent.parent


@register_persistent_window()  # auto_restore=True (Bugfix 05.08.2026)
class ServiceWindow(ServiceParamColumnsMixin, ContentScrollMixin, NamedItemActionsMixin, PersistentWindow):
    INSTANCE_ID = "win_service"
    # Bugfix 06.08.2026 (User-Anweisung, History-Bug): auto_restore=True
    # bleibt – war das Fenster beim Beenden der App OFFEN, wird es beim
    # naechsten Start wiederhergestellt (Save & Restore wie AnalyticsWindow).
    # _keep_history_on_close=False (NEU): Ein MANUELL geschlossenes
    # ServiceWindow (X) wird aus der Fenster-Historie entfernt
    # (delete_instance) und beim naechsten App-Start NICHT wiederhergestellt.
    # Die FENSTERPOSITION ueberlebt das manuelle Schliessen ueber
    # global_settings (save_dialog_geometry in save_state) und wird beim
    # naechsten manuellen Oeffnen ueber den Service-Button wiederhergestellt
    # (Fallback in restore_state, DIALOG_GEOMETRY_KEY).
    _keep_history_on_close = False
    #: Geometrie-Key fuer die POSITION, die ein manuelles Schliessen
    #: ueberlebt (global_settings, vgl. IndicatorSettingsDialog-Muster).
    DIALOG_GEOMETRY_KEY = "win_service"
    # 05.08.2026: Die FensterGROESSE folgte exakt dem Inhalt (auch schrumpfen).
    # 11.08.2026 (Bugfix Runde 17c, User-Meldung 4/5): Umgestellt – der INHALT
    # folgt jetzt dem FENSTER (normales resizable Fenster): _exact_fit_to_content
    # = False bedeutet 'nur wachsen, nie schrumpfen' (Mixin-Pfad). Das Fenster
    # kann manuell grossgezogen und maximiert werden; widgetResizable=True
    # streckt den Inhalt auf den Viewport (Splitter, MasterTree, Param-Box).
    _exact_fit_to_content = False
    # 11.08.2026 (Bugfix, Slider): Mindest-Breite des FENSTERS ueber der
    # Splitter-Minima-Summe (Tree 400 + Panel 520 = 920). Dadurch hat der
    # QSplitter IMMER Spielraum - der Slider zwischen den beiden Hauptrahmen
    # bleibt beweglich, auch wenn der Inhalt schmal ist (vorher klebte das
    # Fenster exakt am Inhalt und der Slider war fixiert). ContentScrollMixin
    # resizet das Inhalt-Widget dabei auf die Fensterbreite (Splitter fuellt
    # den Spielraum). Screen-Klemme schuetzt kleine Bildschirme.
    _min_window_width = 1100

    def __init__(self, parent=None, service_set_repo: Optional[ServiceSetRepository] = None):
        super().__init__(parent)

        # Phase 13 Schritt 4: Service-Set-Verwaltung
        self.set_repo: ServiceSetRepository = service_set_repo or ServiceSetRepository()
        self.set_evaluator = ServiceSetEvaluator()
        # 05.08.2026: Worker fuer die gezielte Kontextmenue-Ausfuehrung
        # (MasterTree '▶️ Service(s) ausführen') – FeatureStore-Persistenz.
        self._run_worker: Optional[ServiceRunWorker] = None
        # 21.01b: Plugin-ID des aktuell im Pill-Strip angezeigten Services.
        self._badge_plugin_id: Optional[str] = None
        # 12.08.2026 (User-Meldung 'Data only loeschen'): Optionaler
        # instance_hash der angezeigten Variante - der Pill-Strip wird
        # damit VARIANTEN-GENAU geladen (nach Purge verschwinden ihre TFs).
        self._badge_instance_hash: Optional[str] = None
        self._current_set_id: Optional[str] = None
        self._current_set_definition: Optional[Dict[str, Any]] = None
        # 17.01.04 (Bugfix): Standalone-Plugin-Editierung – ist eine
        # Plugin-Zeile unter 'Services' (Kategorie-Ordner) im Parameter-
        # Editor geladen, haelt dieses Feld die plugin_id. Die gespeicherten
        # Parameter liegen in global_settings (Key 'plugin_params_<pid>').
        self._current_plugin_editing: Optional[str] = None
        # 10.08.2026 (Bugfix, Varianten-Params): Wird ein Clone-Knoten
        # (Preset/Variante) editiert, haelt dieses Feld das Preset-Dict aus
        # indicator_presets (indicator_id, preset_name, is_active_batch,
        # doc_log) - der Save-Pfad schreibt dann in das Preset statt in
        # global_settings (plugin_params_<pid>).
        self._current_preset_editing: Optional[Dict[str, Any]] = None
        # USER-REQ (P14-03): Preisskala-Praezision je Symbol fuer die 6
        # Custom-Level-Eingabefelder (prox_level1..6). Lazy + gecacht.
        self._symbol_precision: Optional[int] = None
        # Phase 16 (05.08.2026): Concurrency-Guard – Referenzzähler für die
        # pausierten 45s-Hintergrund-Syncs (sync_timer in main.py). Bei
        # jedem beginnenden Service-Run wird das EventBus-Signal
        # service_run_started emittiert (nur beim Übergang 0→1), nach dem
        # letzten Abschluss service_run_finished (1→0). Dadurch wird der
        # Sync-Timer für die Dauer intensiver Berechnungen geblockt.
        self._sync_guard_count: int = 0


        # UI laden
        ui_file = QFile(str(BASE_DIR / "ui" / "service_win.ui"))
        if ui_file.open(QIODevice.ReadOnly):
            loader = QUiLoader()
            self.ui = loader.load(ui_file)
            ui_file.close()
            self.setCentralWidget(self.ui)
        else:
            self.ui = QWidget(self)
            self.setCentralWidget(self.ui)

        self.setWindowTitle("PyTrader - Service Kontrolle")

        # Controls
        self.combo_symbol: QComboBox = self.ui.findChild(QComboBox, "combo_symbol")
        self.text_log: QTextEdit = self.ui.findChild(QTextEdit, "text_log")

        # 05.08.2026 (U15-E): Timeframe-Control in der Filterleiste (neben dem
        # Symbol-Dropdown) – steuert die gezielte Kontextmenue-Ausfuehrung
        # (MasterTree '▶️ Service(s) ausführen'). 'ALLE Timeframes' (Index 0,
        # Sentinel ALL_TIMEFRAMES) fuehrt alle verfuegbaren Timeframes aus.
        self.combo_tf: QComboBox = self.ui.findChild(QComboBox, "combo_tf")
        # Phase 14 P14-05: Papierkorb-Button (Soft-Delete/Wiederherstellung)
        self.btn_trash_sets: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_trash_sets")
        # 05.08.2026 (Kleinere Einstellungen): Das Log wird in die LINKE
        # Splitter-Spalte UNTER den MasterTree verschoben (Breite = Tree-Breite)
        # und auf 4 Zeilen Hoehe begrenzt. Das Fenster endet dadurch exakt
        # unter dem Log (siehe right_panel-Aufbau weiter unten).
        if self.text_log:
            fm = self.text_log.fontMetrics()
            # 11.08.2026 (User-Nachtrag): Log-Hoehe 6 Zeilen = 2 Zeilen
            # HOEHER als die 4-Zeilen-Stufe (die 10.08.-Reduktion auf 2 ist
            # damit zweifach ueberholt).
            self.text_log.setMaximumHeight(fm.lineSpacing() * 6 + 12)
            self.text_log.setMinimumHeight(fm.lineSpacing() * 6 + 12)

        # Phase 13 5.4 Schritt 1: Dynamische Service-Spalten (Breite/Höhe aus
        # dem Inhalt – KEINE fixen Pixelwerte). Das Inhalt-Layout erhält
        # SetFixedSize + AlignTop|AlignLeft: Das Fenster wächst mit der Anzahl
        # der Spalten nach rechts und beim Ausklappen der Experten-Optionen
        # nach unten – ohne leeren Raum (Roadmap 5.4.2.2 Punkt 3).
        #
        # WICHTIG: Der Spalten-Container wird IM CODE erzeugt (nicht per
        # QUiLoader). Das QWidgetItem QUiLoader-erzeugter Widgets meldet nach
        # einer späteren Layout-Änderung einen veralteten sizeHint (Qt-Quirk:
        # 18x18 bzw. alter Gruppenstand), wodurch die Fensterbreite nicht mit
        # der Spaltenanzahl wachsen würde. Im Code erzeugte Widgets (wie die
        # Spalten selbst) werden korrekt weitergereicht.
        self.widget_service_columns = QGroupBox("Service-Parameter")
        self.widget_service_columns.setObjectName("widget_service_columns")
        self.service_columns_layout = QHBoxLayout(self.widget_service_columns)
        self.service_columns_layout.setSpacing(6)
        # Inhalt-Widget + Layout VOR dem Scroll-Wrapper referenzieren.
        # 11.08.2026 (Bugfix Runde 17c, User-Meldung 4): self.ui ist seit der
        # .ui-Umstellung (QMainWindow -> QWidget) das WIDGET mit dem Layout
        # selbst (kein centralwidget-Zwischenschritt mehr). Das frueher hier
        # eingebettete QMainWindow wuchs NICHT mit dem Fenster (Qt verlangt
        # QMainWindow nur als Top-Level) - Ursache fuer 'Grossziehen ohne
        # Anpassung'. install_content_scroll setzt die ScrollArea jetzt direkt
        # als CentralWidget von self (siehe unten).
        self.content_widget = self.ui
        self.central_layout = self.content_widget.layout() if self.content_widget else None
        if self.central_layout is not None:
            # Bugfix 05.08.2026 (Layout-Bereinigung Phase 13): ZWEI-SPALTEN-
            # Splitter statt Drei-Spalten - die Service-Sets-Box (Phase 13)
            # ist ersatzlos entfernt (alle Funktionen im MasterTree/Kontext-
            # menue bzw. im Parameterfenster der rechten Spalte).
            #  * Spalte 1 (links):  MasterTree (Service tree) - volle Hoehe.
            #  * Spalte 2 (rechts): Service-Parameter-Box (widget_service_
            #                       columns) in einer ContentScrollArea mit
            #                       max. Hoehe/Breite + Scrollbalken,
            #                       darunter fest die Aktions-Leiste
            #                       [Speichern] / [Speichern & Ausfuehren].
            # Die Status-Zeile (Laufzeit/Fortschritt) bleibt im central_layout
            # direkt UNTER dem Splitter (= unter der hoechsten Box).
            self.top_row = QHBoxLayout()
            self.top_row.setSpacing(6)
            # Splitter direkt NACH der Filter-/Symbol-Zeile (layout_symbol,
            # Index 0) einfuegen. Die frueheren Scan-Widgets (btn_start_scan,
            # layout_status) sind am 05.08.2026 ersatzlos entfernt – Status
            # + Log liegen darunter im central_layout.
            idx = 1

            # Spalte 1: MasterTree (Service tree)
            self.right_panel = QWidget()
            right_layout = QVBoxLayout(self.right_panel)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(6)
            # MasterTree im Modus B / FULL_EDIT (seit 05.08.2026 ohne Toolbar)
            self.service_selector = ServiceSelectorWidget(
                mode=ServiceSelectorWidget.MODE_FULL_EDIT, parent=self)
            right_layout.addWidget(self.service_selector, 1)
            # 12.08.2026 (User-Meldung 2): Fortschrittsbalken fuer
            # Service-Runs unter dem MasterTree (ueber dem Log) - zeigt
            # je Service den Fortschritt ueber alle Services des
            # aktuellen Timeframes (ServiceRunWorker.service_progress).
            self.progress_label = QLabel("")
            self.progress_bar = QProgressBar()
            # 12.08.2026 (User-Meldung 'Fortschrittsbalken laeuft dauerhaft'):
            # setMaximum(0) startet eine INDETERMINATE Busy-Animation, die nie
            # endet. Determinate leere Range (0..1, Wert 0) statt Busy-Loop;
            # _on_service_progress setzt beim Run die echte Range (max(total,1)).
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFixedHeight(16)
            self.progress_bar.setTextVisible(False)
            progress_row = QHBoxLayout()
            progress_row.setSpacing(6)
            progress_row.addWidget(self.progress_label, 3)
            progress_row.addWidget(self.progress_bar, 2)
            progress_widget = QWidget()
            progress_widget.setLayout(progress_row)
            right_layout.addWidget(progress_widget, 0)
            # 05.08.2026 (Kleinere Einstellungen, Punkt 5): Das Log wandert
            # UNTER den MasterTree in dieselbe Spalte – seine Breite entspricht
            # damit exakt der Tree-Breite, und das Fenster endet unten exakt
            # unter dem Log (Punkt 3). Das QTextEdit wird dabei automatisch aus
            # dem central_layout (verticalLayout) umgehaengt.
            if self.text_log:
                right_layout.addWidget(self.text_log, 0)
            # Mindest-Breite, damit eingerueckte Texte (LEVEL_INDENT) lesbar
            # sind; die Maximalbreite entfaellt im 2-Spalten-Layout (der Tree
            # bekommt den groesseren Anteil, die Parameter-Spalte bleibt
            # min. 320px breit).
            try:
                self.service_selector.master_tree.setMinimumWidth(400)
            except (RuntimeError, AttributeError):
                pass

            # Spalte 2: Service-Parameter-Box + Aktions-Leiste
            self._param_panel = QWidget()
            # 10.08.2026 (Bugfix, Slider): Das 960px-Minimum addierte sich mit
            # dem Tree-Minimum (400px) auf ~1360px - der QSplitter hatte
            # praktisch keinen Spielraum, der Slider war unbeweglich. Das
            # Panel-Minimum ist jetzt schlank (520px); bei schmalerem Panel
            # zeigt die ContentScrollArea horizontale Scrollbalken.
            self._param_panel.setMinimumWidth(520)
            param_layout = QVBoxLayout(self._param_panel)
            param_layout.setContentsMargins(0, 0, 0, 0)
            param_layout.setSpacing(6)
            # 21.01b (11.08.2026): TF-Status-Pills (Pill-Strip) am Kopf der
            # Parameter-/Status-Spalte – pro Timeframe die feature_store-
            # Belegung des aktuell gewaehlten Services. Wird bei der
            # Service-Auswahl (_on_master_selection_details) und nach jedem
            # Run neu geladen (fetch_service_tf_status).
            self.badge_bar = TfStatusBadgeBar()
            param_layout.insertWidget(0, self.badge_bar)
            # 05.08.2026 (Kleinere Einstellungen, Punkt 2): max. Hoehe der
            # Parameter-Box VERDOPPELT (620 -> 1240), damit Tree UND Box
            # standardmaessig doppelt so hoch sind; die max. BREITE bleibt so
            # bemessen, dass ZWEI Service-Spalten nebeneinander OHNE
            # horizontalen Scrollbalken passen - bei mehr Services/Spalten
            # scrollt die ContentScrollArea.
            self._param_scroll = ContentScrollArea()
            # 11.08.2026 (Bugfix Runde 17c, User-Meldung 5): widgetResizable
            # = True + KEINE max. Breite/Hoehe mehr – die Service-Parameter-
            # Box passt sich der Fenstergroesse an (vorher auf 1000x1240
            # gedeckelt; beim Grossziehen blieb sie stehen).
            self._param_scroll.setWidgetResizable(True)
            self._param_scroll.setWidget(self.widget_service_columns)
            param_layout.addWidget(self._param_scroll, 1)
            # Aktions-Leiste direkt UNTER der Parameter-Box - [Speichern]
            # persistiert die Parameter-Aenderungen ohne Neuberechnung;
            # [Speichern & Ausfuehren] speichert und stoesst sofort den
            # Service-Run an (ServiceRunWorker, kein Schwerlast-Scan).
            # Feste Position ausserhalb der ScrollArea -> immer sichtbar.
            self._param_action_row = QHBoxLayout()
            self._param_action_row.setSpacing(6)
            self.btn_save_params = QPushButton("✔ Speichern")
            self.btn_save_run_params = QPushButton(
                "▶ Speichern & Ausführen")
            self.btn_save_params.setToolTip(
                "Speichert die aktuellen Parameter-Aenderungen im Set "
                "(app_data.duckdb) und entfernt das '*' im Baum.")
            self.btn_save_run_params.setToolTip(
                "Speichert die Aenderungen UND stoesst sofort die "
                "Neuberechnung an (Bestaetigungsabfrage mit Symbol/Timeframe).")
            # Nur bei manueller Parameter-Aenderung (Dirty) sichtbar.
            self.btn_save_params.setVisible(False)
            self.btn_save_run_params.setVisible(False)
            self._param_action_row.addWidget(self.btn_save_params)
            self._param_action_row.addWidget(self.btn_save_run_params)
            self._param_action_row.addStretch(1)
            param_layout.addLayout(self._param_action_row)

            self.main_splitter = QSplitter(Qt.Horizontal)
            self.main_splitter.addWidget(self.right_panel)
            self.main_splitter.addWidget(self._param_panel)
            # 11.08.2026 (Bugfix, Slider): KEINE setStretchFactor-Aufrufe mehr -
            # die 3:2-Faktoren erzwangen bei jedem Fenster-Reflow die Verteilung
            # und machten den Slider zaeh (die Anwenderposition sprang zurueck).
            # Der QSplitter behaelt jetzt die vom Anwender gezogene Position.
            # Keine Spalte unter ihre Mindestgroesse kollabieren lassen.
            self.main_splitter.setCollapsible(0, False)
            self.main_splitter.setCollapsible(1, False)
            # 11.08.2026 (Bugfix, Slider): Der Handle wird dicker (8px statt
            # 4px Default) - besser greifbar/ziehbar.
            self.main_splitter.setHandleWidth(8)
            # 10.08.2026 (Bugfix, Slider): Startgroessen einmalig setzen -
            # danach behaelt der QSplitter die Position des Anwenders
            # (_resize_param_box_deferred waechst nur noch, siehe
            # param_columns.py).
            self.main_splitter.setSizes([460, 820])

            self.top_row.addWidget(self.main_splitter)
            self.central_layout.insertLayout(idx, self.top_row)
        # Fenstergroesse (15.02): 1280 x 800 als Default – Single Source of
        # Truth ist die ui/service_win.ui-Geometrie (der QUiLoader wendet sie
        # beim Laden an). KEIN resize()-Aufruf im Code: der 5.4-Content-Reflow
        # (resize_to_clamped_content) darf die Groesse weiterhin inhalt- und
        # bildschirmbasiert anpassen (keine fixen Pixel im Quellcode).
        # Scroll-Wrapper: gesamtes Fenster scrollbar, wenn Inhalt > Bildschirm
        # (ContentScrollMixin). Der Inhalt behält seine natürliche Größe; das
        # Fenster wird auf den Bildschirm geklemmt (Scrollbars erscheinen erst,
        # wenn der Inhalt den Viewport übersteigt).
        self.install_content_scroll(self.content_widget, install_to=self)
        # 11.08.2026 (Bugfix Runde 17c, User-Meldung 4): widgetResizable=True
        # – die ContentScrollArea streckt das Inhalt-Widget auf den Viewport.
        # Beim manuellen Grossziehen (Rahmen/Ecke) wachsen Splitter, MasterTree
        # und Param-Box mit (vorher widgetResizable=False: Inhalt blieb stehen,
        # das Fenster wurde nur leer groesser). Nur ServiceWindow; der
        # IndicatorSettingsDialog (anderer Mixin-Nutzer) bleibt unveraendert.
        if self.content_scroll is not None:
            self.content_scroll.setWidgetResizable(True)
        self.main_layout = self.ui.layout()
        # KEIN SetFixedSize auf dem QMainWindowLayout: das würde die
        # Fenstergröße auf den Inhalt fixieren und das Bildschirm-Cap
        # (setMaximumSize) überschreiben. Auch das INHALT-Layout bekommt KEIN
        # SetFixedSize: QLayout.SetFixedSize ruft setFixedSize() auf dem
        # Inhalt-Widget auf und fixiert es auf die ERSTE Layout-Größe – späteres
        # Wachstum (Service-Spalten, Experten-Optionen) wäre dadurch blockiert.
        # Stattdessen setzt resize_to_clamped_content() das Inhalt-Widget in
        # jedem Reflow explizit auf die aktuelle Layout-Größe (ContentScrollMixin).
        if self.central_layout is not None:
            self.central_layout.setSpacing(6)
            # 11.08.2026 (Bugfix Runde 17d, User-Meldungen 4+5): KEIN
            # setAlignment(AlignTop|AlignLeft) mehr - es HIELT die Layout-
            # Verteilung an: Der QSplitter (MasterTree | Parameter-Box) blieb
            # auf seiner Mindest-Hoehe stehen, obwohl das Fenster groesser
            # gezogen/maximiert wurde (extra Raum blieb als Leerflaeche
            # unterhalb des Splitters). Mit widgetResizable=True +
            # _exact_fit_to_content=False folgt der INHALT dem FENSTER: Der
            # Splitter faengt das Wachstum ab und verteilt es an MasterTree
            # (Hoehe!) und Parameter-Box (Breite + Hoehe).
        self._service_param_controls: Dict[Any, QWidget] = {}
        # Phase 14 P14-01: Beschreibungs-Eingabefelder der Service-Instanzen
        self._service_desc_controls: Dict[str, QWidget] = {}

        # Phase 14 P14-05: Papierkorb-Dialog (Soft-Delete)
        if self.btn_trash_sets:
            self.btn_trash_sets.clicked.connect(self.show_trash_dialog)
        # Phase 15 (Dirty-State): Parameter-Panel-Aktionsleiste (Speichern /
        # Speichern & Ausführen) – siehe _save_params_from_panel /
        # _save_and_run_from_panel.
        if self.btn_save_params:
            self.btn_save_params.clicked.connect(self._save_params_from_panel)
        if self.btn_save_run_params:
            self.btn_save_run_params.clicked.connect(self._save_and_run_from_panel)

        # U15-D2 (Bedien-Feinschliff): Log-Kontextmenü (Kopieren / Log leeren)
        # + Auto-Scroll ans Ende in log() – siehe _on_log_context_menu().
        if self.text_log:
            self.text_log.setContextMenuPolicy(Qt.CustomContextMenu)
            self.text_log.customContextMenuRequested.connect(self._on_log_context_menu)

        # Sofort speichern bei Symbol-Änderung
        if self.combo_symbol:
            self.combo_symbol.currentTextChanged.connect(self.save_state)
            # USER-REQ: Preisskala-Praezision ist je Symbol fix – beim
            # Symbol-Wechsel Cache invalidieren + Spalten neu bauen.
            self.combo_symbol.currentTextChanged.connect(self._on_symbol_changed)
        # U15-E (05.08.2026): Timeframe-Control (Filterleiste) ebenfalls sofort
        # speichern – get_persistent_timeframe() liest combo_tf.
        if self.combo_tf:
            self.combo_tf.currentTextChanged.connect(self.save_state)

        # Phase 15 15.01: Favoriten-Symbol-Verwaltung.
        # ★-Button rechts neben der Symbol-ComboBox oeffnet das nicht-modale
        # SymbolsWindow (Favoriten verwalten). Das Symbol-Dropdown zeigt nur
        # Favoriten (is_favorite == True) und wird ueber den EventBus bei
        # jeder Favoriten-Aenderung neu befuellt (Entkopplung, kein direktes
        # Fenster-Wissen).
        self._symbol_repo: SymbolRepository = get_symbol_repository()
        self.btn_symbol_fav: QPushButton = QPushButton("★", self.ui)
        self.btn_symbol_fav.setObjectName("btn_symbol_fav")
        self.btn_symbol_fav.setToolTip(
            "Favoriten verwalten – oeffnet das Symbol-Fenster. "
            "Das Symbol-Dropdown zeigt nur Favoriten.")
        self.btn_symbol_fav.setFixedWidth(32)
        layout_symbol = self.ui.findChild(QHBoxLayout, "layout_symbol")
        if layout_symbol is not None and self.combo_symbol is not None:
            idx = layout_symbol.indexOf(self.combo_symbol)
            layout_symbol.insertWidget(idx + 1, self.btn_symbol_fav)
        self.btn_symbol_fav.clicked.connect(self.open_symbols_window)
        # EventBus: Favoriten-Aenderungen -> ComboBox neu befuellen
        event_bus.favorites_changed.connect(self._refresh_symbol_combo)
        self._refresh_symbol_combo()

        # U15-E (05.08.2026): Timeframe-Dropdown der Filterleiste befuellen –
        # 'ALLE Timeframes' (Index 0) + alle Timeframes aus get_timeframes().
        self._refresh_timeframe_combo()

        # Phase 15 15.02: MasterTree/ServiceSelector (FULL_EDIT) verdrahten –
        # Kontextmenue-Aktionen auf die bestehenden Set-Methoden + EventBus-
        # Sync. Die fruehere Aktions-Toolbar oberhalb des Baums ist entfernt
        # (05.08.2026) – der MasterTree hat die volle vertikale Hoehe.
        self._wire_selector_toolbar()

        self.log(f"Verfügbare Plugins: {_available_plugin_ids()}")

        # State asynchron wiederherstellen (nach show(), damit move vom
        # Window-Manager akzeptiert werden). Die POSITION wird restauriert
        # (Punkt 1); direkt danach setzt der Reflow das Fenster exakt auf den
        # Inhalt (Breite = Tree+Box, Hoehe = bis Log-Unterkante, Punkte 3+4).
        QTimer.singleShot(0, self.restore_state)
        QTimer.singleShot(0, self._apply_reflow_size)

    # --- PersistentWindow-Interface ---

    def save_state(self) -> None:
        """Persistiert Fenster-POSITION und -GROESSE (05.08.2026, Punkt 1).

        11.08.2026 (Bugfix Runde 17c): Seit _exact_fit_to_content=False folgt
        der Inhalt dem Fenster – die GROESSE wird jetzt wiederhergestellt
        (restore_state), damit die manuell gezogene/Maximize-Groesse des Users
        erhalten bleibt. Position + Symbol/Timeframe bleiben weiterhin erhalten.

        06.08.2026 (History-Bug): Die POSITION wird zusaetzlich in
        global_settings gesichert (save_dialog_geometry). Beim manuellen
        Schliessen loescht delete_instance den window_instances-Eintrag
        (_keep_history_on_close=False) – die Position ueberlebt das und wird
        beim naechsten manuellen Oeffnen ueber den Fallback in
        restore_state() wiederhergestellt (User-Anweisung 06.08.2026).
        """
        inst_id = self.get_instance_id()
        if not inst_id:
            return
        p = self.pos()
        self._state_manager.save_window_geometry(
            inst_id, p.x(), p.y(), self.width(), self.height(), self.isMaximized())
        try:
            self._state_manager.save_dialog_geometry(
                self.DIALOG_GEOMETRY_KEY, p.x(), p.y(),
                self.width(), self.height())
        except Exception:
            pass
        symbol = self.get_persistent_symbol()
        tf = self.get_persistent_timeframe()
        if symbol and tf:
            self._state_manager.save_instance_state(
                instance_id=inst_id, symbol=symbol, timeframe=tf)

    def restore_state(self) -> None:
        """Stellt NUR die Fenster-POSITION wieder her (05.08.2026, Punkt 1).

        Die Groesse wird hier bewusst NICHT angewendet – der Inhalt-Reflow
        (resize_to_clamped_content) setzt das Fenster exakt auf min(Inhalt,
        Bildschirm). Die gespeicherte Breite/Hoehe waere sonst stale
        (z.B. schmaler als die Parameter-Box).

        06.08.2026 (History-Bug): Nach einem MANUELLEN Schliessen wurde der
        window_instances-Eintrag geloescht (delete_instance). Die Position
        liegt dann in global_settings (save_dialog_geometry in save_state)
        und wird hier als Fallback wiederhergestellt – so bleibt die
        Fensterposition beim erneuten manuellen Oeffnen erhalten, ohne dass
        das Fenster beim App-Start automatisch restauriert wird.
        """
        inst_id = self.get_instance_id()
        if not inst_id:
            return
        # Window-Flags korrigieren (QUiLoader setzt oft Qt.Tool | Qt.Dialog).
        # 11.08.2026 (Bugfix Runde 17c): Nur wenn das Fenster noch NICHT
        # sichtbar ist - setWindowFlags() auf einem sichtbaren Fenster bricht
        # die Layout-Geometrie-Verwaltung (Inhalt folgt dem Resize nicht
        # mehr). Die Flags werden seit Runde 17c bereits im Konstruktor
        # (PersistentWindow.__init__) gesetzt, wo das Fenster unsichtbar ist.
        if not self.isVisible():
            self._fix_window_flags()
        geom = self._state_manager.get_window_geometry(inst_id)
        if not geom:
            try:
                geom = self._state_manager.get_dialog_geometry(
                    self.DIALOG_GEOMETRY_KEY)
            except Exception:
                geom = None
        if geom:
            pos_x = geom.get("pos_x")
            pos_y = geom.get("pos_y")
            width = geom.get("width")
            height = geom.get("height")
            screen_geo = QApplication.primaryScreen().availableGeometry()
            # 11.08.2026 (Bugfix Runde 17c, User-Meldung 4): Fenster-GROESSE
            # wiederherstellen – vorher bewusst ignoriert (exakt-fit-to-content).
            # Mit _exact_fit_to_content=False bleibt die User-Groesse erhalten.
            if width and height:
                self.resize(max(int(width), 640), max(int(height), 480))
            if pos_x is not None and pos_y is not None:
                if pos_x < screen_geo.x() - 100 or pos_x > screen_geo.right() or \
                   pos_y < screen_geo.y() - 100 or pos_y > screen_geo.bottom():
                    pos_x, pos_y = 100, 100
                self.move(pos_x, pos_y)
            self._restored_is_maximized = bool(geom.get("is_maximized", False))
        # Symbol/Timeframe aus instance_states
        all_inst = self._state_manager.load_all_instances()
        matched = next((i for i in all_inst if i.get("instance_id") == inst_id), None)
        if matched:
            raw_symbol = matched.get("symbol")
            raw_tf = matched.get("timeframe")
            symbol = str(raw_symbol) if raw_symbol is not None else self.get_persistent_symbol()
            tf = str(raw_tf) if raw_tf is not None else self.get_persistent_timeframe()
            self._apply_persistent_filters(symbol, tf)

    def _apply_reflow_size(self) -> None:
        """Erweitert den Mixin-Reflow um Punkt 2 (05.08.2026).

        Der Splitter (Tree | Parameter-Box) bekommt eine Mindest-Hoehe von
        2x seiner natuerlichen Hoehe – dadurch oeffnet das Fenster
        standardmaessig doppelt so hoch und Tree UND Box sind doppelt so
        hoch. WICHTIG: Nach dem setMinimumHeight muessen die Layout-Caches
        erneut invalidiert werden – der vertikale Layout-sizeHint ist sonst
        veraltet (Qt 6.11-Caching) und uebernimmt das neue Minimum nicht
        (Fenster bliebe auf der alten Hoehe).
        """
        sp = getattr(self, "main_splitter", None)
        if sp is not None:
            natural = sp.sizeHint().height()
            sp.setMinimumHeight(natural * 2)
            sp.updateGeometry()
            self._invalidate_content_caches()
        super()._apply_reflow_size()

    def resize_to_clamped_content(self) -> None:
        """11.08.2026 (Bugfix Runde 17c, User-Meldung 4): Override.

        Das Basis-Mixin resizet das Inhalt-Widget MANUELL (auf sizeHint bzw.
        auf die Fensterbreite). Mit widgetResizable=True (Runde 17c) verwaltet
        die ContentScrollArea das Inhalt-Widget aber selbst - das manuelle
        resize() brach die Layout-Verwaltung und 'fror' die ScrollArea auf der
        alten Groesse ein (Inhalt folgte dem Fenster-Resize nicht mehr).

        Daher wird hier NUR die FENSTER-Groesse nachgefuehrt:
          * nur wachsen, nie schrumpfen (User darf frei ziehen/verkleinern),
          * Screen-Klemme (max. verfuegbare Flaeche),
          * _min_window_width (Splitter-Spielraum, ServiceWindow=1100).
        Das Inhalt-Widget (Splitter, MasterTree, Param-Box) folgt der
        ScrollArea automatisch (widgetResizable=True).
        """
        if self._content_widget is None:
            return
        content = self.clamped_content_size()
        frame = self.frameGeometry().size() - self.size()
        desired = QSize(content.width() + frame.width(),
                        content.height() + frame.height())
        screen = QApplication.primaryScreen().availableGeometry()
        current = self.size()
        new_w = min(max(desired.width(), current.width()), screen.width())
        new_h = min(max(desired.height(), current.height()), screen.height())
        min_w = getattr(self, '_min_window_width', 0) or 0
        if min_w:
            new_w = max(new_w, min(min_w, screen.width()))
        if not self.isMaximized():
            self.resize(new_w, new_h)

    def apply_screen_cap(self) -> None:
        """11.08.2026 (Bugfix Runde 17d2, User-Meldung 1): KEIN setMaximumSize.

        Qt's Windows-QPA zeigt/aktiviert den Maximize-Button NUR, wenn
        maximumSize() == QWINDOWSIZE_MAX (16777215) ist (oder
        Qt::CustomizeWindowHint gesetzt ist) - siehe qwindowswindow.cpp,
        shouldShowMaximizeButton(): 'return (flags & Qt::CustomizeWindowHint)
        || w->maximumSize() == QSize(QWINDOWSIZE_MAX, QWINDOWSIZE_MAX);'.

        Das bisherige setMaximumSize(screen.size()) (Runde 17b) bzw.
        setMaximumSize(screen.size()*2) (Runde 17c) war NIE gleich
        QWINDOWSIZE_MAX -> Windows graute den Maximize-Button weiterhin aus.

        Mit widgetResizable=True + _exact_fit_to_content=False ist die
        Screen-Klemme der DEFAULT-Groesse Aufgabe des Reflows
        (resize_to_clamped_content klemmt auf availableGeometry). Ein
        OS-seitiges Maximum ist nicht noetig: Das Fenster behaelt die
        Qt-Defaults (max = QWINDOWSIZE_MAX) und kann frei maximiert werden
        (der Inhalt folgt via ContentScrollArea).
        """
        pass  # bewusst KEIN setMaximumSize - Maximize-Button bleibt aktiv

    def get_persistent_symbol(self) -> str:
        return self.combo_symbol.currentText() if self.combo_symbol else "SILVER"

    def get_persistent_timeframe(self) -> str:
        """Liefert den aktuell gewaehlten Timeframe der Filterleiste (combo_tf).

        05.08.2026 (U15-E): 'ALLE Timeframes' ist eine reguläre, persistierbare
        Auswahl (Sentinel ALL_TIMEFRAMES) – save_state() speichert sie 1:1,
        damit beim naechsten Oeffnen exakt derselbe Modus wiederhergestellt
        wird. Fallback: "H1", wenn kein Control existiert.
        """
        if self.combo_tf:
            tf = self.combo_tf.currentText()
            if tf:
                return tf
        return "H1"

    def _apply_persistent_filters(self, symbol: str, timeframe: str) -> None:
        if self.combo_symbol:
            idx = self.combo_symbol.findText(symbol)
            if idx >= 0:
                self.combo_symbol.setCurrentIndex(idx)
        # U15-E: Timeframe der Filterleiste wiederherstellen (inkl. Sentinel
        # 'ALLE Timeframes' – findText trifft den exakten Eintrag).
        if self.combo_tf and timeframe:
            idx = self.combo_tf.findText(timeframe)
            if idx >= 0:
                self.combo_tf.setCurrentIndex(idx)

    def _refresh_timeframe_combo(self) -> None:
        """Befuellt das Timeframe-Control der Filterleiste (U15-E).

        Index 0 ist der Sentinel 'ALLE Timeframes' (Multi-TF-Ausfuehrung),
        danach folgen alle Timeframes AUFSTEIGEND nach Dauer sortiert –
        kuerzeste zuerst (M1, M2, M5, M10, M15, M30, H1, H4, D1, W1, MN1),
        identische Reihenfolge wie im chart_win (Bugfix 05.08.2026).
        get_timeframes() liefert intern die MT5-Reihenfolge (MN1..M1),
        daher wird explizit ueber TF_SECONDS_MAP sortiert. Fallback bei
        nicht verfuegbarem MT5: TF_SECONDS_MAP bzw. eine Basisliste. Die
        aktuelle Auswahl bleibt erhalten, sofern sie noch existiert;
        Default ist 'M1'.
        """
        if not self.combo_tf:
            return
        try:
            from db_service import TF_SECONDS_MAP, get_timeframes
            try:
                tfs = list(get_timeframes().keys())
            except Exception:
                tfs = list(TF_SECONDS_MAP.keys())
        except Exception:
            tfs = ["M1", "M2", "M5", "M10", "M15", "M30",
                   "H1", "H4", "D1", "W1", "MN1"]
        # Bugfix 05.08.2026: Kuerzeste zuerst (M1..MN1) wie im chart_win.
        tfs = sorted(tfs, key=lambda tf: TF_SECONDS_MAP.get(tf, 10**12))
        current = self.combo_tf.currentText()
        self.combo_tf.blockSignals(True)
        self.combo_tf.clear()
        self.combo_tf.addItem(ALL_TIMEFRAMES)
        for tf in tfs:
            if tf != ALL_TIMEFRAMES:
                self.combo_tf.addItem(tf)
        idx = self.combo_tf.findText(current)
        if idx < 0:
            idx = self.combo_tf.findText("M1")
        self.combo_tf.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_tf.blockSignals(False)

    def _on_symbol_changed(self, symbol: str) -> None:
        """USER-REQ: Preisskala-Praezision ist je Symbol fix. Beim Symbol-
        Wechsel wird der Precision-Cache invalidiert und – falls ein Set
        aktiv ist – die Service-Spalten neu aufgebaut, damit die 6
        Custom-Level-Felder (prox_level1..6) die neue Preisskala-Praezision
        des Symbols anzeigen."""
        self._symbol_precision = None
        if (self._current_set_definition is not None
                and self.service_columns_layout is not None):
            self._rebuild_columns()

    # --- Phase 15 15.02: MasterTree / ServiceSelector (FULL_EDIT) ---

    def _wire_selector_toolbar(self) -> None:
        """Verdrahtet den ServiceSelectorWidget (Modus FULL_EDIT) mit den
        bestehenden Set-Methoden (add/move/remove/rename).

        05.08.2026 (CRUD-Buttons entfernt): Die Aktions-Toolbar oberhalb des
        MasterTrees (btn_add/btn_remove/Order-Pfeile) ist ersatzlos aus der
        UI und aus allen Event-Verbindungen entfernt – alle Struktur-Aktionen
        und die neuen Run-Aktionen laufen ueber das MasterTree-Kontextmenue
        (entkoppelte Signale, DRY: dieselben Handler wie zuvor)."""
        selector = getattr(self, "service_selector", None)
        if selector is None or selector.master_tree is None:
            return
        tree = selector.master_tree
        # MasterTree-Auswahl + Kontextmenue (entkoppelt) -> Editor/Handler
        tree.selection_changed.connect(self._on_master_selection)
        # 17.01.04 (Bugfix): Klick-Scope (node_type, set_id, service_id,
        # plugin_id) – traegt auch die plugin_id von Plugin-Zeilen unter
        # 'Services'. Daraus wird der Standalone-Plugin-Editor geladen
        # (Parameter anzeigen/editieren/speichern wie bei Sets).
        tree.selection_details.connect(self._on_master_selection_details)
        # Bugfix 05.08.2026: Info-Button-Klicks (Spalte 1) -> Beschreibungs-
        # Dialog (Service / Plugin / Set).
        tree.info_requested.connect(self._on_tree_info_requested)
        # Kontextmenue-Aktionen (Rechtsklick im Baum).
        tree.create_set_requested.connect(self._on_add_set)
        tree.rename_set_requested.connect(self._on_rename_set)
        tree.add_set_service_requested.connect(self._on_add_set_service)
        tree.delete_set_requested.connect(self._on_delete_set)
        tree.move_service_requested.connect(self._on_move_service)
        tree.remove_service_requested.connect(self._on_remove_service)
        tree.purge_trash_requested.connect(self._on_purge_trash)
        # Phase 15: Kontextmenue '🗑️ Papierkorb öffnen...' (Haupt-Gruppe
        # 📁 Service-Sets) – gleiche Methode wie der Papierkorb-Button in
        # der oberen Aktionsleiste (btn_trash_sets).
        tree.open_trash_requested.connect(self.show_trash_dialog)
        # 05.08.2026: Gezielte Ausfuehrung ('▶️ Diesen Service ausführen' /
        # '▶️ Alle Services ausführen') -> ServiceRunWorker mit Sicherheits-
        # abfrage (Set/Service + aktives Symbol/Timeframe) + FeatureStore-
        # Persistenz + EventBus-Sync.
        tree.run_service_requested.connect(self._on_run_service)
        tree.run_set_requested.connect(self._on_run_set)
        # 17.01.02 (Bugfix-Runde): Run-/Info-Aktionen der Services-Gruppe
        # (Plugin-Zeilen einzeln, Kategorie-Ordner rekursiv, Ordner-Info).
        tree.run_plugin_requested.connect(self._on_run_plugin)
        tree.run_category_requested.connect(self._on_run_category)
        tree.category_info_requested.connect(self._on_category_info_requested)
        # 18.01.03 (Dynamic Tree Management): Ordner-CRUD & Kategorie-
        # Drag&Drop – Sets/Plugins/Ordner ziehen, 'Neuer Ordner' (wird
        # PERSISTIERT, E3-revidiert 08.08.2026), 'Umbenennen' (String-Replace
        # aller Kinder) und 'Ordner löschen' (manuelle Loeschung) werden hier
        # persistiert.
        tree.folder_item_moved.connect(self._on_folder_item_moved)
        tree.folder_moved.connect(self._on_folder_moved)
        tree.rename_folder_requested.connect(self._on_rename_folder)
        tree.create_folder_requested.connect(self._on_create_folder)
        tree.delete_folder_requested.connect(self._on_delete_folder)
        # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im MasterTree-Kontextmenue
        # (Service-/Clone-Zeilen) -> Handler (unten). 'Data Only Löschen'
        # purgt die Feature-Daten (Q5), 'Vollständig Löschen' entfernt
        # Instanz/Preset + Daten, 'Doc Log bearbeiten' editiert das
        # Negativ-Wissen und 'Als Variante duplizieren' erzeugt Kopien (Q8).
        tree.data_only_purge_requested.connect(self._on_data_only_purge)
        tree.delete_complete_requested.connect(self._on_delete_complete)
        tree.doc_log_requested.connect(self._on_doc_log_requested)
        tree.duplicate_variant_requested.connect(self._on_duplicate_variant)
        # 10.08.2026 (Bugfix): 'Variante umbenennen' (Clone/Preset) – der
        # MasterTree fragt den neuen Namen ab; dieser Handler persistiert
        # den Rename in indicator_presets (indicator_id, preset_name).
        tree.rename_variant_requested.connect(self._on_rename_variant)

    @Slot(str)
    def _toolbar_add_service(self, plugin_id: str,
                             set_id: Optional[str] = None) -> None:
        """Fuegt einen Service (Plugin) in das Set ein (Kontextmenue
        'Service hinzufuegen' -> eigene Auswahlbox).

        Phase 13-Bereinigung (05.08.2026): Der fruehere Weg ueber das
        Instanz-Eingabefeld der entfernten Service-Sets-Box entfaellt - der
        Service wird direkt ueber die Plugin-Auswahl mit
        Registry-Defaults angelegt (_add_service_to_set)."""
        if not plugin_id:
            return
        target = set_id or self._current_set_id
        if not target:
            self.log("Kein Set geladen - Service kann nicht hinzugefuegt werden.")
            return
        self._add_service_to_set(target, str(plugin_id))

    @Slot(str, str)
    def _on_master_selection(self, set_id: str, service_id: str) -> None:
        """Laedt das im MasterTree gewaehlte Set direkt in den Parameter-
        Editor (rechte Splitter-Spalte).

        Phase 13-Bereinigung (05.08.2026): Der bisherige Umweg ueber das
        Set-Dropdown der entfernten Service-Sets-Box entfaellt - die
        Auswahl im MasterTree ist die alleinige Quelle. Bei Set-Auswahl
        werden die Parameter-Spalten aufgebaut; ohne Auswahl (Plugin-/
        Standalone-Zeilen) wird der Editor geleert.

        17.01.04 (Bugfix): Bei einer Plugin-Zeile unter 'Services' feuert
        selection_changed mit leeren IDs NACH selection_details. Der
        Plugin-Editor wurde dort bereits geladen (_current_plugin_editing) –
        der Editor darf in diesem Fall NICHT geleert werden."""
        self._set_param_actions_visible(False)
        if not set_id:
            if self._current_plugin_editing:
                return  # Plugin-Editor bleibt (via selection_details geladen)
            self._clear_set_editor()
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        self.load_set_into_editor(definition)

    # -------------------------------------------------------------------------
    # 17.01.04 (Bugfix): Standalone-Plugin-Editor (Parameter-Spalte fuer
    # Plugin-Zeilen unter 'Services' – anzeigen/editieren/speichern wie bei
    # Sets; Persistenz in global_settings, Key 'plugin_params_<pid>').
    # -------------------------------------------------------------------------

    @Slot(str, str, str, str)
    def _on_master_selection_details(self, node_type: str, set_id: str,
                                     service_id: str, plugin_id: str) -> None:
        """Slot fuer `MasterTree.selection_details` (Mausklick in einer Zeile).

        17.01.04 (Bugfix): Klick auf eine Plugin-Zeile (TYPE_PLUGIN) unter
        'Services' (auch in Kategorie-Ordnern) laedt den Standalone-Plugin-
        Editor in die rechte Parameter-Spalte – editierbar, mit Speichern.
        Set-/Service-Zeilen verhalten sich unveraendert (der eigentliche
        Set-Load laeuft ueber selection_changed); hier wird nur der
        Plugin-Modus zurueckgesetzt.
        """
        if node_type in ("plugin", "clone") and plugin_id:
            # 21.01b: Pill-Strip fuer den geklickten Service laden.
            # 12.08.2026: Clone-Knoten tragen den instance_hash im
            # service_id-Slot -> Pills VARIANTEN-GENAU anzeigen.
            self._refresh_badge_bar(
                str(plugin_id),
                str(service_id) if node_type == "clone" else None)
            if node_type == "clone":
                # 10.08.2026 (Bugfix, Varianten-Params): Eine Variante/Clone
                # hat EIGENE Parameter in indicator_presets (20.04, Q7) -
                # der Editor laedt die presetspezifischen Werte statt der
                # globalen Standalone-Parameter (plugin_params_<pid>). Der
                # instance_hash liegt im service_id-Slot (MasterTree.
                # _emit_selection_details).
                self._load_clone_editor(str(plugin_id), str(service_id))
            else:
                self._load_plugin_editor(str(plugin_id))
            return
        # Jede andere Zeile beendet den Plugin-Editor-Modus; der Set-Editor
        # wird weiterhin ueber selection_changed gesteuert (Bestandslogik).
        if self._current_plugin_editing:
            self._current_plugin_editing = None
        if self._current_preset_editing:
            self._current_preset_editing = None
        # 21.01b: Pill-Strip fuer Set-/Service-Zeilen nachziehen (erster
        # Service des Sets bzw. der Service selbst).
        pid_badge, hash_badge = self._resolve_badge_scope(
            node_type, set_id, service_id, plugin_id)
        self._refresh_badge_bar(pid_badge, hash_badge)

    def _plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """ServiceInstanceConfig eines Standalone-Plugins.

        Liefert {"plugin_id", "lookback", "params", "version"} – Basis sind
        die Registry-Defaults; gespeicherte Werte aus global_settings
        (Key 'plugin_params_<pid>') ueberschreiben lookback/params und
        ergaenzen eine optionale Beschreibung.
        """
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            plugin = None
        params = dict(getattr(plugin, "default_params", None) or {}) if plugin else {}
        lookback: int = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        cfg: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
        }
        try:
            saved = self._state_manager.get_global_value(
                f"plugin_params_{plugin_id}", None)
        except Exception:
            saved = None
        if isinstance(saved, dict):
            lb = saved.get("lookback")
            if lb is not None:
                try:
                    cfg["lookback"] = int(lb)
                except (TypeError, ValueError):
                    pass
            saved_params = saved.get("params")
            if isinstance(saved_params, dict):
                merged = dict(params)
                merged.update(saved_params)
                cfg["params"] = merged
            desc = saved.get("description")
            if desc:
                cfg["description"] = str(desc)
        return cfg

    def _load_plugin_editor(self, plugin_id: str) -> None:
        """Laedt die Parameter eines Standalone-Plugins in den Editor.

        Baut eine Ad-hoc-Definition (nur dieser eine Service) aus
        `_plugin_config` und zeigt sie editierbar in der rechten Spalte.
        Der Speicherpfad laeuft bei Aenderungen ueber `_save_plugin_params`
        (global_settings) statt ueber ServiceSetRepository.
        """
        if not plugin_id:
            return
        try:
            from analytics.features.feature_builder import PluginRegistry
            PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden.")
            self._current_plugin_editing = None
            self._current_preset_editing = None
            self._clear_set_editor()
            return
        cfg = self._plugin_config(plugin_id)
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": plugin_id,
            "description": str(cfg.get("description") or ""),
            "execution_order": [plugin_id],
            "services": {plugin_id: cfg},
        }
        self._current_plugin_editing = plugin_id
        self._current_preset_editing = None
        self.load_set_into_editor(definition)

    def _load_clone_editor(self, plugin_id: str, instance_hash: str) -> None:
        """Laedt die Parameter einer Variante (Clone) in den Editor.

        10.08.2026 (Bugfix, Varianten-Params): Jede Variante hat EIGENE
        Parameter-Einstellungen in indicator_presets (Kapitel 20.04, Model C).
        Ein Klick auf einen Clone-Knoten darf NICHT die globalen Standalone-
        Parameter (plugin_params_<pid>) laden - der Editor zeigt die
        presetspezifischen Werte. Der Save-Pfad (_save_plugin_params)
        schreibt Aenderungen via save_indicator_preset in das Preset
        (indicator_id, preset_name) zurueck.
        """
        if not plugin_id or not instance_hash:
            return
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            self.log(f"Preset zu #{instance_hash} nicht gefunden.")
            self._current_plugin_editing = None
            self._current_preset_editing = None
            self._clear_set_editor()
            return
        indicator_id = str(preset.get("indicator_id") or "")
        preset_name = str(preset.get("preset_name") or "Default")
        if not indicator_id:
            self.log(f"Preset '{preset_name}' hat keine indicator_id.")
            return
        # Basis = Registry-Defaults + gespeicherte Standalone-Werte; die
        # presetspezifischen Parameter ueberschreiben (Varianten-Params).
        cfg = self._plugin_config(plugin_id)
        preset_params = preset.get("params") or {}
        if isinstance(preset_params, dict) and preset_params:
            merged = dict(cfg.get("params") or {})
            merged.update(preset_params)
            cfg["params"] = merged
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": f"{plugin_id} ({preset_name})",
            "description": str(preset.get("doc_log") or ""),
            "execution_order": [plugin_id],
            "services": {plugin_id: cfg},
        }
        self._current_plugin_editing = plugin_id
        # Merke das Preset fuer den Save-Pfad (is_active_batch/doc_log
        # bleiben beim Speichern erhalten).
        self._current_preset_editing = preset
        self.load_set_into_editor(definition)

    def _save_plugin_params(self) -> bool:
        """Persistiert die Parameter des aktuell editierten Standalone-
        Plugins in global_settings (Key 'plugin_params_<pid>').

        Returns: True bei Erfolg (Dirty-Marker entfernt).
        """
        plugin_id = self._current_plugin_editing
        if not plugin_id:
            return False
        definition = self.collect_set_definition()
        services = definition.get("services") or {}
        cfg = next(iter(services.values()), None)
        if not isinstance(cfg, dict):
            self.log(f"FEHLER beim Speichern der Plugin-Parameter: "
                     f"keine Service-Config.")
            return False
        # 10.08.2026 (Bugfix, Varianten-Params): Im Clone-/Preset-Modus wird
        # in indicator_presets gespeichert (eigene Parameter je Variante)
        # statt in global_settings (plugin_params_<pid>).
        preset = self._current_preset_editing
        if isinstance(preset, dict):
            indicator_id = str(preset.get("indicator_id") or "")
            preset_name = str(preset.get("preset_name") or "Default")
            if not indicator_id:
                self.log("Preset hat keine indicator_id - nicht gespeichert.")
                return False
            try:
                self._state_manager.save_indicator_preset(
                    indicator_id, preset_name,
                    dict(cfg.get("params") or {}),
                    plugin_id=plugin_id,
                    version=str(cfg.get("version")
                                or preset.get("version") or "0.0.0"),
                    is_active_batch=bool(preset.get("is_active_batch")),
                    doc_log=str(preset.get("doc_log") or ""),
                )
            except Exception as e:
                self.log(f"FEHLER beim Speichern der Varianten-Parameter: {e}")
                return False
            self._clear_dirty_markers()
            event_bus.service_set_changed.emit()
            self.log(f"Parameter gespeichert (Variante '{preset_name}'): "
                     f"{plugin_id}")
            return True
        data: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": int(cfg.get("lookback") or 1000),
            "params": dict(cfg.get("params") or {}),
            "description": str(cfg.get("description") or ""),
        }
        try:
            self._state_manager.save_global_value(
                f"plugin_params_{plugin_id}", data)
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Plugin-Parameter: {e}")
            return False
        self._clear_dirty_markers()
        # 18.01.01 (E-3): EventBus-Live-Sync - analog zum Set-Speichern
        # (save_set-Pfad) und zum Dialog-Picker, damit alle MasterTree-
        # Instanzen (auch der Analytics-Picker) die Standalone-Parameter
        # bzw. den geaenderten Zustand live uebernehmen.
        event_bus.service_set_changed.emit()
        self.log(f"Parameter gespeichert (Plugin): {plugin_id}")
        return True

    def _begin_sync_guard(self) -> None:
        """Blockt den 45s-Hintergrund-Sync (sync_timer in main.py).

        Erhoeht den Referenzzaehler und emittiert `service_run_started`
        ausschliesslich beim Uebergang 0→1 – mehrere parallele Runs
        (ServiceRunWorker) pausieren den Sync nur EINMAL.
        """
        self._sync_guard_count += 1
        if self._sync_guard_count == 1:
            try:
                event_bus.service_run_started.emit()
            except (RuntimeError, AttributeError):
                pass

    def _end_sync_guard(self) -> None:
        """Gibt den 45s-Hintergrund-Sync wieder frei.

        Senkt den Referenzzaehler; erst beim Uebergang 1→0 (alle
        Service-Berechnungen abgeschlossen) wird `service_run_finished`
        emittiert und der Sync-Timer im MainWindow wieder gestartet.
        """
        if self._sync_guard_count <= 0:
            return
        self._sync_guard_count -= 1
        if self._sync_guard_count == 0:
            try:
                event_bus.service_run_finished.emit()
            except (RuntimeError, AttributeError):
                pass

    # -------------------------------------------------------------------------
    # 05.08.2026: Gezielte Kontextmenue-Ausfuehrung (Service(s) ausfuehren)
    # -------------------------------------------------------------------------

    def _start_run_worker(self, scope_id: str, set_definition: Dict[str, Any],
                          instance_id: Optional[str]) -> None:
        """Startet den gezielten ServiceRunWorker (Single/Set) im Hintergrund.

        * Laedt OHLCV nur fuer das aktive Symbol + den gewaehlten Timeframe
          (FeatureBuilder.load_ohlcv) – KEIN globaler Massen-Scan.
        * Fuehrt die Pipeline via ServiceSetEvaluator.execute_set() aus und
          persistiert die erzeugten feature_store_payloads ZWINGEND in
          analytics.duckdb (feature_store, FeatureBuilder.store_plugin_payload).
        * Der Worker emittiert nach Abschluss `event_bus.service_set_changed`
          – alle ServiceSelectorModel-Instanzen (MasterTree, Analytics, ...)
          aktualisieren dadurch live das Ausfuehrungsdatum '(DD.MM.JJ)'.
        """
        if self._run_worker and self._run_worker.isRunning():
            self.log("Service-Ausführung läuft bereits.")
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E (05.08.2026): Timeframe-Control der Filterleiste (combo_tf) –
        # 'ALLE Timeframes' startet die Multi-TF-Ausfuehrung im Worker.
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        self._run_worker = ServiceRunWorker(
            self.set_evaluator, symbol, timeframe, set_definition,
            instance_id=instance_id, parent=self,
        )
        self._run_worker.log_message.connect(self.log)
        self._run_worker.run_finished.connect(self._on_run_worker_finished)
        self._run_worker.run_failed.connect(self._on_run_worker_failed)
        # 12.08.2026 (User-Meldung 2): Per-Service-Fortschrittsbalken.
        self._run_worker.service_progress.connect(self._on_service_progress)
        # 21.01b: Per-TF-Signale -> Pill-Strip (Laufzeit-/Fehler-Zustand).
        self._run_worker.tf_started.connect(self._on_tf_started)
        self._run_worker.tf_finished.connect(self._on_tf_finished)
        # 12.08.2026: Progress-Reset beim Start (Busy-Modus).
        self._reset_run_progress("Starte Ausführung ...")
        # Phase 16: 45s-Hintergrund-Sync pausieren, solange der Run laeuft.
        self._begin_sync_guard()
        self._run_worker.start()

    @Slot(str, str)
    def _on_run_service(self, set_id: str, service_id: str) -> None:
        """'▶️ Diesen Service ausführen' (MasterTree-Kontextmenue).

        Sicherheitsabfrage mit Set-/Service-Name und dem aktuell gewaehlten
        Symbol/Timeframe, danach gezielter Single-Run (inkl. Upstream-
        Abhaengigkeiten im Set, damit z.B. srv_proximity seine Linien hat).
        """
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Ausführung abgebrochen.")
            return
        if service_id not in (definition.get("services") or {}):
            self.log(f"Service '{service_id}' nicht im Set '{set_id}'.")
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Zeitachsen-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        set_name = str(definition.get("display_name") or set_id)
        reply = QMessageBox.question(
            self, "Service ausführen",
            f"Service '{service_id}' aus dem Set '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen.")
            return
        self._start_run_worker(service_id, definition, instance_id=service_id)

    @Slot(str)
    def _on_run_set(self, set_id: str) -> None:
        """'▶️ Alle Services ausführen' (MasterTree-Kontextmenue).

        Sicherheitsabfrage mit Set-Name und dem aktuell gewaehlten
        Symbol/Timeframe, danach gezielter Set-Run (nur dieses Set).
        """
        if not set_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Ausführung abgebrochen.")
            return
        if not definition.get("execution_order"):
            self.log(f"Set '{set_id}' hat keine Services – Ausführung abgebrochen.")
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Zeitachsen-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        set_name = str(definition.get("display_name") or set_id)
        count = len(definition.get("execution_order") or [])
        reply = QMessageBox.question(
            self, "Set ausführen",
            f"Alle Services ({count}) des Sets '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Die erzeugten Feature-Store-Payloads werden in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen.")
            return
        self._start_run_worker(set_id, definition, instance_id=None)

    @Slot(str, str)
    def _on_run_plugin(self, plugin_id: str, instance_hash: str = "") -> None:
        """'▶️ Diesen Service ausführen' (Plugin-/Clone-Zeile unter 📦 Services).

        17.01.02 (Bugfix-Runde): Einzel-Services ausserhalb von Sets (z.B.
        unter Kategorie-Ordnern) erhalten dieselbe Run-Aktion wie die
        Service-Zeilen der Sets. Sicherheitsabfrage mit Plugin-Name und dem
        aktuell gewaehlten Symbol/Timeframe, danach gezielter Single-Run via
        ServiceRunWorker mit einer Ad-hoc-Mini-Definition (nur dieser
        Service; prepare_worker_definition loest ggf. dependencies auf).

        11.08.2026 (Bugfixing, Varianten-Run): `instance_hash` wird vom
        MasterTree-Kontextmenue mitgeliefert:
          * Clone-Zeile  -> hash der Variante: NUR diese Variante laeuft mit
                            ihren EIGENEN Parametern + Hash (Datum im Baum
                            aktualisiert sich an der Variante, Bug 1).
          * Plugin-Zeile -> leer: mit Presets laufen ALLE aktiven Varianten,
                            sonst Basis-Parameter (Bestandsverhalten).
        """
        if not plugin_id:
            return
        sm = getattr(self, "_state_manager", None)
        entries = variant_run_entries(plugin_id, sm, self._plugin_config)
        if not entries:
            return
        if instance_hash:
            entries = [e for e in entries
                       if e[1].get("instance_hash") == instance_hash]
            if not entries:
                # Variante nicht (mehr) vorhanden -> Basis-Fallback.
                entries = [(plugin_id, self._plugin_config(plugin_id))]
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Timeframe-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        single = len(entries) == 1
        if single:
            _iid, _cfg = entries[0]
            _name = str(_cfg.get("preset_name") or plugin_id)
            title = "Service ausführen"
            text = (f"Service '{plugin_id}' (Variante '{_name}') ausführen?\n\n"
                    f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                    f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
                    f"geschrieben.")
        else:
            title = "Alle Varianten ausführen"
            text = (f"Alle Varianten ({len(entries)}) von '{plugin_id}' "
                    f"ausführen?\n\n"
                    f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                    f"Die erzeugten Feature-Store-Payloads werden in "
                    f"analytics.duckdb geschrieben.")
        reply = QMessageBox.question(
            self, title, text, QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen.")
            return
        definition = {
            "set_id": f"plugin_{plugin_id}",
            "display_name": plugin_id,
            "execution_order": [e[0] for e in entries],
            "services": {e[0]: e[1] for e in entries},
        }
        self._start_run_worker(
            plugin_id, definition,
            instance_id=entries[0][0] if single else None)

    @Slot(str, str)
    def _on_run_category(self, group: str, category_path: str) -> None:
        """▶️ Alle Services ausführen (Kategorie-Ordner).

        17.01.02 (Bugfix-Runde): Ordner-Knoten erhalten dieselbe Run-Aktion
        wie die Sets. Es werden ALLE Services unter dem Ordner ausgefuehrt
        (rekursiv, inkl. Unter-Ordner). 18.01.03 (L3): `group` unterscheidet
        Sets-Ordner ('sets' – alle Service-plugin_ids der Sets unter dem
        Pfad, rekursiv) von Plugins-Ordnern ('plugins' – via
        ServiceSelectorModel.category_plugin_ids). Sicherheitsabfrage mit
        Kategorie-Name und dem aktuell gewaehlten Symbol/Timeframe, danach
        gezielter Set-Run mit einer Ad-hoc-Definition.
        """
        if not category_path:
            return
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return
        plugin_ids = model.category_service_plugin_ids(group, category_path)

        if not plugin_ids:
            self.log(f"Kategorie '{category_path}' hat keine Services – "
                     f"Ausführung abgebrochen.")
            return
        # 11.08.2026 (Bugfixing, Bug 3): Plugins MIT Presets werden zu ALLEN
        # aktiven Varianten expandiert (jede mit eigenen Parametern + Hash),
        # damit 'Alle Services ausführen' auch die Varianten ausfuehrt.
        sm = getattr(self, "_state_manager", None)
        entries_all: List[tuple] = []
        for pid in plugin_ids:
            entries_all.extend(variant_run_entries(pid, sm, self._plugin_config))
        if not entries_all:
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Timeframe-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        count = len(entries_all)
        reply = QMessageBox.question(
            self, "Alle Services ausführen",
            f"Alle Services ({count}) der Kategorie '{category_path}' "
            f"ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Die erzeugten Feature-Store-Payloads werden in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen.")
            return
        definition = {
            "set_id": f"category_{category_path}",
            "display_name": category_path,
            "execution_order": [e[0] for e in entries_all],
            # 17.01.04: Gespeicherte Plugin-Parameter je Service verwenden
            # (falls vorhanden), sonst Registry-Defaults. Varianten tragen
            # Preset-Parameter + instance_hash.
            "services": {e[0]: e[1] for e in entries_all},
        }
        self._start_run_worker(category_path, definition, instance_id=None)

    @Slot(str, str)
    def _on_category_info_requested(self, group: str,
                                    category_path: str) -> None:
        """Info-Dialog fuer einen Kategorie-Ordner (17.01.02, wie Set-Info).

        Read-Only-Liste aller Services unter dem Ordner (rekursiv) mit dem
        Kategorie-Pfad als Titel – analog zur Set-Info (ServiceDescription
        Dialog.from_set, keine persistierbare Beschreibung). 18.01.03 (L3):
        `group` unterscheidet Sets- von Plugins-Ordnern (Aufloesung via
        ServiceSelectorModel.category_service_plugin_ids).
        """
        if not category_path:
            return
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return
        plugin_ids = model.category_service_plugin_ids(group, category_path)

        definition = {
            "set_id": f"category_{category_path}",
            "display_name": category_path,
            "description": f"Kategorie-Ordner: {category_path}",
            "execution_order": list(plugin_ids),
            "services": {pid: {"plugin_id": pid} for pid in plugin_ids},
        }
        try:
            dlg = ServiceDescriptionDialog.from_set(definition, parent=self)
            dlg.exec()
        except (RuntimeError, AttributeError) as e:
            self.log(f"Info-Dialog nicht möglich: {e}")

    # -------------------------------------------------------------------------
    # 18.01.03 (Dynamic Tree Management): Kategorie-Drag&Drop & Ordner-CRUD
    # -------------------------------------------------------------------------

    @Slot(str, str, str)
    def _on_folder_item_moved(self, node_type: str, item_id: str,
                              new_path: str) -> None:
        """Drop eines Sets/Plugins in einen Ziel-Ordner (MasterTree).

        Persistiert den neuen Kategorie-Pfad:
          * TYPE_SET    -> Set-Definition (category-Feld) via save_set (E2).
          * TYPE_PLUGIN -> Kategorie-Override (plugin_category_<id>,
                           global_settings – E1).
        18.01.03 (E3-revidiert, Bugfix 08.08.2026): Der QUELL-Ordner
        (und seine Elternkette) wird VOR dem Update ermittelt und nach
        dem Verschieben als Leere-Ordner persistiert
        (ensure_folder_path) – damit bleibt der Ordner sichtbar und
        verschiebbar, wenn sein letztes Kind entzogen wurde.
        Danach EventBus-Sync, damit ALLE MasterTree-Instanzen live
        refreshen (Invariante 5).
        """
        from serviceui.master_tree import TYPE_PLUGIN, TYPE_SET
        from serviceui.service_set_utils import (
            ensure_folder_path, set_plugin_category, set_set_category)
        source_path = ""
        group = ""
        ok = False
        if node_type == TYPE_SET:
            group = "sets"
            try:
                definition = self.set_repo.get_set(item_id) or {}
                source_path = str(definition.get("category") or "").strip().strip("/")
            except Exception:
                source_path = ""
            ok = set_set_category(self.set_repo, item_id, new_path)
        elif node_type == TYPE_PLUGIN:
            group = "plugins"
            model = getattr(self.service_selector, "model", None)
            if model is not None:
                try:
                    source_path = model.plugin_category_path(item_id)
                except Exception:
                    source_path = ""
            ok = set_plugin_category(self.state_manager, item_id, new_path)
        if not ok:
            self.log(f"Kategorie-Verschiebung fehlgeschlagen "
                     f"({node_type} '{item_id}').")
            return
        if source_path:
            ensure_folder_path(self.state_manager, group, source_path)
        event_bus.service_set_changed.emit()

    @Slot(str, str)
    def _on_create_folder(self, group: str, full_path: str) -> None:
        """Kontextmenue 'Neuer Ordner' (create_folder_requested).

        18.01.03 (E3-revidiert, 08.08.2026): Persistiert den
        benutzererzeugten (ggf. leeren) Ordner ueber global_settings
        (service_set_utils.create_empty_folder, Key
        'tree_folders_<group>') und emittiert den EventBus, damit alle
        MasterTree-Instanzen live refreshen (Invariante 5). Leere
        Ordner verschwinden damit NICHT beim Refresh, sondern nur bei
        manueller Loeschung ('Ordner löschen').
        """
        from serviceui.service_set_utils import create_empty_folder
        if not create_empty_folder(self.state_manager,
                                   str(group or ""), full_path):
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str)
    def _on_delete_folder(self, group: str, path: str) -> None:
        """Kontextmenue 'Ordner löschen' (delete_folder_requested).

        18.01.03 (E3-revidiert): Entfernt den persistierten Ordner-
        Eintrag (service_set_utils.delete_empty_folder, Key
        'tree_folders_<group>') und emittiert den EventBus. Der
        MasterTree erlaubt die Aktion nur fuer Ordner ohne Kinder;
        Kinder (falls vorhanden) bleiben unangetastet.
        """
        from serviceui.service_set_utils import delete_empty_folder
        if not delete_empty_folder(self.state_manager,
                                   str(group or ""), path):
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str, str)
    def _on_folder_moved(self, group: str, old_path: str,
                         new_path: str) -> None:
        """Drop eines Ordners auf einen anderen Ordner (MasterTree).

        Verschiebt alle Kinder rekursiv (String-Replace des Pfad-Praefixes
        via service_set_utils.rename_category) und emittiert den EventBus.
        """
        self._rename_folder(group, old_path, new_path)

    @Slot(str, str, str)
    def _on_rename_folder(self, group: str, old_path: str,
                          new_path: str) -> None:
        """Kontextmenue 'Umbenennen' (rename_folder_requested).

        Fuehrt dasselbe String-Replace aus wie der Ordner-Drop
        (_on_folder_moved) – DRY ueber `_rename_folder`.
        """
        self._rename_folder(group, old_path, new_path)

    def _rename_folder(self, group: str, old_path: str,
                       new_path: str) -> None:
        """Zentraler Ordner-Rename (String-Replace aller Kinder).

        18.01.03 (E1/E2): Sets-Ordner aktualisieren das category-Feld der
        Set-Definitionen; Plugins-Ordner setzen Kategorie-Overrides
        (plugin_category_<id>). Nach Aenderung EventBus-Sync.
        """
        from serviceui.service_set_utils import rename_category
        try:
            count = rename_category(
                getattr(self.service_selector, "model", None),
                self.set_repo, self.state_manager,
                str(group or ""), old_path, new_path)
        except Exception as e:
            self.log(f"Ordner-Umbenennung fehlgeschlagen: {e}")
            return
        if count > 0:
            event_bus.service_set_changed.emit()
        self.log(f"Ordner '{old_path}' -> '{new_path}': {count} "
                 f"Element(e) verschoben.")

    @Slot(str, int)
    def _on_run_worker_finished(self, scope_id: str, stored: int) -> None:
        """Loggt den Abschluss des gezielten Runs (FeatureStore-Persistenz).

        Der EventBus-Sync erfolgt bereits im Worker (service_set_changed) –
        das ServiceSelectorModel hat dadurch das neue MAX(created_at) gelesen
        und der MasterTree zeigt das Datum '(DD.MM.JJ)' live an.
        """
        # Phase 16: 45s-Hintergrund-Sync wieder freigeben.
        self._end_sync_guard()
        self._reset_run_progress()
        self.log(f"Ausführung abgeschlossen: {stored} Feature-Row(s) im "
                 f"feature_store gespeichert ({scope_id}).")
        # 21.01b: Pill-Strip nach dem Run neu laden (neue Counts/last_run).
        bar = getattr(self, "badge_bar", None)
        if bar is not None:
            bar.set_running(None)
        self._refresh_badge_bar()

    @Slot(str, str)
    def _on_run_worker_failed(self, scope_id: str, error: str) -> None:
        # Phase 16: 45s-Hintergrund-Sync auch bei Fehler freigeben.
        self._end_sync_guard()
        self._reset_run_progress()
        self.log(f"FEHLER bei Ausführung ({scope_id}): {error}")
        # 21.01b: Pill-Strip nach Fehler zuruecksetzen + Status neu laden.
        bar = getattr(self, "badge_bar", None)
        if bar is not None:
            bar.set_running(None)
        self._refresh_badge_bar()

    @Slot(str, str, int, int)
    def _on_service_progress(self, tf: str, iid: str, done: int,
                             total: int) -> None:
        """12.08.2026 (User-Meldung 2): Per-Service-Fortschritt anzeigen."""
        bar = getattr(self, "progress_bar", None)
        if bar is not None:
            bar.setMaximum(max(total, 1))
            bar.setValue(done)
        lbl = getattr(self, "progress_label", None)
        if lbl is not None:
            lbl.setText(f"{tf}: {iid} ({done}/{total})")

    def _reset_run_progress(self, label: str = "") -> None:
        """Setzt den Fortschrittsbalken zurueck (Default: leeres Label)."""
        bar = getattr(self, "progress_bar", None)
        if bar is not None:
            # 12.08.2026: setMaximum(0) waere eine endlose Busy-Animation
            # (indeterminate) - determinate leere Range (0..1) verwenden.
            bar.setRange(0, 1)
            bar.setValue(0)
        lbl = getattr(self, "progress_label", None)
        if lbl is not None:
            lbl.setText(label)

    # -------------------------------------------------------------------------
    # 21.01b (11.08.2026): TF-Status-Pills (Pill-Strip)
    # -------------------------------------------------------------------------
    def _on_tf_started(self, tf: str) -> None:
        """Hebt den gerade laufenden Timeframe im Pill-Strip blau hervor."""
        bar = getattr(self, "badge_bar", None)
        if bar is None:
            return
        bar.set_running(tf)
        bar.clear_error(tf)

    def _on_tf_finished(self, tf: str, stored: int, had_data: bool) -> None:
        """TF fertig: ohne OHLCV-Daten/Fehler rot markieren, sonst neutral."""
        bar = getattr(self, "badge_bar", None)
        if bar is None:
            return
        if had_data:
            bar.clear_error(tf)
        else:
            bar.set_error(tf)
        bar.set_running(None)

    def _resolve_badge_scope(self, node_type: str, set_id: str,
                             service_id: str,
                             plugin_id: str) -> Tuple[Optional[str],
                                                      Optional[str]]:
        """Ermittelt (plugin_id, instance_hash) fuer den Pill-Strip.

        12.08.2026 (User-Meldung 'Data only loeschen'): Der Pill-Strip wird
        VARIANTEN-GENAU geladen. Clone-Knoten tragen den instance_hash im
        service_id-Slot (MasterTree._emit_selection_details, 20.04 Q7);
        Set-/Service-Zeilen liefern den Hash der ersten Instanz aus der
        Set-Definition (cfg['instance_hash'], sonst Params-only-Hash).
        """
        if plugin_id:
            h = str(service_id) if node_type == "clone" else None
            return str(plugin_id), (h or None)
        if set_id:
            try:
                definition = self.set_repo.get_set(set_id)
            except Exception:
                definition = None
            if definition:
                order = list(definition.get("execution_order") or [])
                services = dict(definition.get("services") or {})
                for iid in order:
                    cfg = services.get(iid) or {}
                    pid = str(cfg.get("plugin_id") or iid)
                    if pid:
                        h = str(cfg.get("instance_hash") or "") or None
                        if not h:
                            try:
                                h = generate_instance_hash(
                                    pid, cfg.get("params") or {})
                            except Exception:
                                h = None
                        return pid, h
        return (str(service_id) if service_id else None), None

    def _refresh_badge_bar(self, plugin_id: Optional[str] = None,
                           instance_hash: Optional[str] = None) -> None:
        """Laedt die TF-Status-Pills fuer den angegebenen Service neu.

        Quelle: FeatureStoreReader.fetch_service_tf_status() – je Timeframe
        die Anzahl der feature_store-Eintraege und der letzte Lauf.

        12.08.2026 (User-Meldung 'Data only loeschen'): Mit `instance_hash`
        wird der Pill-Strip VARIANTEN-GENAU geladen (nur die TFs dieser
        Variante); ohne Hash bleibt das service-weite Verhalten erhalten.
        """
        bar = getattr(self, "badge_bar", None)
        if bar is None:
            return
        if plugin_id:
            self._badge_plugin_id = plugin_id
        if instance_hash:
            self._badge_instance_hash = instance_hash
        pid = self._badge_plugin_id
        if not pid:
            bar.clear()
            return
        h = self._badge_instance_hash or None
        try:
            status = FeatureStoreReader().fetch_service_tf_status(pid, h)
        except Exception:
            status = {}
        bar.update_status(status)

    # -------------------------------------------------------------------------
    # Phase 15 (Dirty-State): Parameter-Panel-Aktionsleiste
    # -------------------------------------------------------------------------

    @Slot()
    def _save_params_from_panel(self) -> None:
        """'[💾 Speichern]' – persistiert die aktuellen Parameter-Aenderungen
        des aktiven Sets (ServiceSetRepository.save_set, ohne Neuberechnung),
        entfernt den '*' -Dirty-Marker im Baum und emittiert den EventBus
        (Live-Sync aller ServiceSelectorModel-Instanzen).

        17.01.04: Im Standalone-Plugin-Modus (_current_plugin_editing)
        laeuft die Persistenz ueber global_settings (_save_plugin_params)
        statt ueber ServiceSetRepository.
        """
        if self._current_plugin_editing:
            self._save_plugin_params()
            return
        if not self._current_set_id:
            self.log("Kein Set geladen – Speichern nicht möglich.")
            return
        definition = self.collect_set_definition()
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Parameter: {e}")
            return
        self._clear_dirty_markers()
        event_bus.service_set_changed.emit()
        self.log(f"Parameter gespeichert (P15): {self._current_set_id}")

    @Slot()
    def _save_and_run_from_panel(self) -> None:
        """'[▶️ Speichern & Ausführen]' – speichert die Aenderungen und
        stoesst nach Bestaetigungsabfrage (Symbol/Timeframe) sofort die
        Neuberechnung an.

        Die Neuberechnung laeuft ueber den gezielten ServiceRunWorker
        (FeatureStore-Persistenz + EventBus-Sync): Dadurch wird der
        '*' -Marker entfernt und nach Abschluss das Ausfuehrungsdatum
        '(DD.MM.JJ)' im MasterTree live aktualisiert.

        17.01.04: Im Standalone-Plugin-Modus wird nur der eine Service
        gespeichert (global_settings) und ausgefuehrt.
        """
        if self._current_plugin_editing:
            plugin_id = self._current_plugin_editing
            if not self._save_plugin_params():
                return
            definition = self.collect_set_definition()
            symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
            # U15-E: Zeitachsen-Control der Filterleiste (combo_tf) – kann
            # auch 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
            timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
            reply = QMessageBox.question(
                self, "Speichern & Ausführen",
                f"Plugin '{plugin_id}' wurde gespeichert.\n\n"
                f"Jetzt ausführen?\n"
                f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                f"Der Service wird neu berechnet und der Feature-Store-Payload "
                f"in analytics.duckdb geschrieben.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                self.log("Ausführung abgebrochen (Parameter gespeichert).")
                return
            self._start_run_worker(plugin_id, definition, instance_id=plugin_id)
            return
        if not self._current_set_id:
            self.log("Kein Set geladen – Speichern & Ausführen nicht möglich.")
            return
        definition = self.collect_set_definition()
        if not definition.get("execution_order"):
            self.log("Keine Services in der Ausführungs-Reihenfolge – "
                     "Speichern & Ausführen abgebrochen.")
            return
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Parameter: {e}")
            return
        self._clear_dirty_markers()
        event_bus.service_set_changed.emit()
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Timeframe-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        set_name = str(definition.get("display_name") or self._current_set_id)
        count = len(definition.get("execution_order") or [])
        reply = QMessageBox.question(
            self, "Speichern & Ausführen",
            f"Set '{set_name}' wurde gespeichert.\n\n"
            f"Jetzt ausführen?\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Alle Services ({count}) werden neu berechnet und die "
            f"Feature-Store-Payloads in analytics.duckdb geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen (Parameter gespeichert).")
            return
        self._start_run_worker(self._current_set_id, definition, instance_id=None)

    def _clear_dirty_markers(self) -> None:
        """Entfernt alle '*' -Dirty-Marker im MasterTree (nach Speichern).

        Bugfix 05.08.2026 (Punkt 2): Blendet zusaetzlich die Speicher-
        Buttons aus - ohne manuelle Parameter-Aenderung sind sie nicht
        sichtbar.
        """
        self._set_param_actions_visible(False)
        selector = getattr(self, "service_selector", None)
        tree = getattr(selector, "master_tree", None)
        if tree is None:
            return
        try:
            tree.clear_dirty_markers()
        except (RuntimeError, AttributeError):
            pass

    def _set_param_actions_visible(self, visible: bool) -> None:
        """Blendet die Speicher-Buttons der Parameter-Spalte ein/aus.

        Bugfix 05.08.2026 (Punkt 2/3): Sichtbar NUR bei manueller
        Parameter-Aenderung (Dirty), sonst unsichtbar. Wird von
        _mark_service_dirty (param_columns) eingeblendet und von
        _clear_dirty_markers / _on_master_selection ausgeblendet.
        """
        for name in ("btn_save_params", "btn_save_run_params"):
            btn = getattr(self, name, None)
            if btn is not None:
                try:
                    btn.setVisible(bool(visible))
                except (RuntimeError, AttributeError):
                    pass

    def _plugin_belongs_to_indicator(self, plugin_id: str) -> bool:
        """True, wenn der Service einem Indikator zugeordnet ist
        (metadata['indicator_id']/['indicator_name']).

        Bugfix 05.08.2026: Grundlage der entschaerften P14-04-Sperre –
        nur Indikator-Services sind ueber die 'letztes Vorkommen'-Regel
        geschuetzt, freie Services sind immer loeschbar.
        """
        try:
            model = getattr(getattr(self, "service_selector", None),
                            "model", None)
            if model is not None:
                return bool(model.belongs_to_indicator(plugin_id))
        except (RuntimeError, AttributeError):
            pass
        return False

    def _remaining_sets_with_plugin(self, plugin_id: str,
                                    exclude_set_id: Optional[str]) -> list:
        """GESPEICHERTE Sets (ohne exclude_set_id), die einen Service mit
        plugin_id enthalten – Basis der P14-04-Sperre (Bugfix 05.08.2026:
        Entfernen/Loeschen erlaubt, solange ein gueltiges Set fuer den
        Indikator erhalten bleibt)."""
        return [
            s for s in self.set_repo.list_sets()
            if s.get("set_id") != exclude_set_id
            and any((cfg or {}).get("plugin_id") == plugin_id
                    for cfg in (s.get("services") or {}).values())
        ]

    def _select_set_in_tree(self, set_id: str) -> None:
        """Selektiert ein Set im MasterTree (Bugfix 05.08.2026).

        Loest ueber selection_changed -> _on_master_selection den Editor-Sync
        aus – direkt nach dem Anlegen eines neuen Sets.
        """
        selector = getattr(self, "service_selector", None)
        tree = getattr(selector, "master_tree", None)
        if tree is None or not set_id:
            return
        try:
            from serviceui.master_tree import (
                ROLE_NODE_TYPE, ROLE_SET_ID, TYPE_SET, TreeItemIterator)
            for item in TreeItemIterator(tree):
                if item is None:
                    continue
                if (item.data(0, ROLE_NODE_TYPE) == TYPE_SET and
                        str(item.data(0, ROLE_SET_ID) or "") == set_id):
                    tree.setCurrentItem(item)
                    return
        except (RuntimeError, AttributeError):
            pass

    def _build_new_set_definition(self, name: str,
                                  indicator_id: str) -> Dict[str, Any]:
        """Baut die Definition fuer ein neues Service-Set.

        Bugfix 05.08.2026: Bei Indikator-Auswahl wird die `indicator_id`
        explizit gespeichert und die Basis-Services des Indikators
        (service_plugin_ids, z.B. srv_grid_lines + srv_proximity) werden mit
        Registry-Defaults automatisch angelegt (instance_id = plugin_id) –
        einfache Bedienung und das Set ist sofort gueltig fuer den Indikator.
        """
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": name,
            "description": "",
            "execution_order": [],
            "services": {},
        }
        if not indicator_id:
            return definition
        definition["indicator_id"] = indicator_id
        try:
            from analytics.engine.service_selector_model import list_indicators
            info = next(
                (i for i in list_indicators()
                 if str(i.get("indicator_id") or "") == indicator_id),
                None,
            )
        except Exception:
            info = None
        if info is None:
            return definition
        try:
            from analytics.features.feature_builder import PluginRegistry
            registry = PluginRegistry()
        except Exception:
            registry = None
        for pid in (info.get("service_plugin_ids") or []):
            pid = str(pid)
            if not pid or pid in definition["services"]:
                continue
            params: Dict[str, Any] = {}
            if registry is not None:
                try:
                    params = dict(getattr(
                        registry.get(pid), "default_params", {}) or {})
                except (KeyError, AttributeError):
                    params = {}
            lookback: int = 1000
            if "lookback" in params:
                try:
                    lookback = int(params.pop("lookback") or 1000)
                except (TypeError, ValueError):
                    lookback = 1000
            definition["services"][pid] = {
                "plugin_id": pid,
                "lookback": lookback,
                "params": params,
            }
            definition["execution_order"].append(pid)
        return definition

    @Slot()
    def _on_add_set(self) -> None:
        """Erzeugt ein NEUES Service-Set ([➕ Set] / Kontextmenue
        'Neues Set anlegen').

        Bugfix 05.08.2026 (einfache Bedienung): Dialog mit Namens- und
        Indikator-Auswahl (NewServiceSetDialog). Der Name ist Pflicht; wird
        ein Indikator gewaehlt, wird er explizit zugewiesen (indicator_id)
        und die Basis-Services automatisch angelegt (_build_new_set_definition).
        Das neue Set wird direkt im MasterTree selektiert.
        """
        try:
            from analytics.engine.service_selector_model import list_indicators
            indicators = list_indicators()
        except Exception:
            indicators = []
        dlg = NewServiceSetDialog(indicators, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        name = dlg.result_name()
        ind_id = dlg.result_indicator_id()
        if any((s.get("display_name") or "") == name
               for s in self.set_repo.list_sets()):
            QMessageBox.warning(
                self, "Name vergeben",
                f"Ein Service-Set heißt bereits '{name}'.")
            return
        definition = self._build_new_set_definition(name, ind_id)
        try:
            set_id = self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Anlegen des Sets: {e}")
            return
        if not set_id:
            self.log("Set-Anlage fehlgeschlagen.")
            return
        self.log(f"Neues Service-Set angelegt: {set_id}"
                 + (f" (Indikator: {ind_id})" if ind_id else ""))
        event_bus.service_set_changed.emit()
        # Neues Set im MasterTree selektieren (Editor-Sync via selection_changed)
        self._select_set_in_tree(set_id)

    @Slot(str)
    def _on_rename_set(self, set_id: str) -> None:
        """Benennt ein Service-Set um (Kontextmenue 'Set umbenennen').

        Direkt ueber set_repo: Namensdialog (vorbelegt), Kollisionspruefung
        gegen die UEBRIGEN Sets, dann save_set() mit gleicher set_id und
        neuem display_name. Bewusst NICHT ueber den NamedItemAdapter –
        dessen _item_save_as() verweigert leere execution_order (leere Sets
        waeren sonst nicht umbenennbar).
        """
        if not set_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Umbenennen abgebrochen.")
            return
        current_name = str(definition.get("display_name") or "")
        name, ok = QInputDialog.getText(
            self, "Set umbenennen",
            f"Neuer Name für das Service-Set '{current_name}':",
            text=current_name,
        )
        if not ok:
            return
        clean = name.strip()
        if not clean:
            QMessageBox.warning(self, "Fehler", "Der Name darf nicht leer sein.")
            return
        collision = any(
            (s.get("display_name") or "") == clean and s.get("set_id") != set_id
            for s in self.set_repo.list_sets())
        if collision:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Ein anderes Service-Set heißt bereits '{clean}'.")
            return
        definition["display_name"] = clean
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Set umbenannt: '{current_name}' -> '{clean}'")
        event_bus.service_set_changed.emit()
        # Geladenes Set im Editor nachziehen (Baum-Label kommt aus dem Modell).
        if self._current_set_id == set_id:
            try:
                self.load_set_into_editor(self.set_repo.get_set(set_id))
            except Exception as e:
                self.log(f"FEHLER beim Nachladen des Sets: {e}")

    @Slot(str)
    def _on_add_set_service(self, set_id: str) -> None:
        """'Service hinzufuegen' (Kontextmenue): EIGENE Auswahlbox.

        Bugfix 05.08.2026: Eine eigene QInputDialog-Auswahlbox statt der
        frueheren Toolbar-Auswahl. Nach der Auswahl wird der Service direkt
        ins Set uebernommen und sofort persistiert (_add_service_to_set)."""
        if not set_id:
            return
        selector = getattr(self, "service_selector", None)
        ids = sorted(selector.get_plugin_ids()) if selector is not None else []
        if not ids:
            self.log("Keine Services verfuegbar.")
            return
        pid, ok = QInputDialog.getItem(
            self, "Service hinzufuegen",
            "Service waehlen:", ids, 0, False)
        if not ok or not pid:
            return
        self._toolbar_add_service(str(pid), set_id)

    @Slot(str)
    def _on_delete_set(self, set_id: str) -> None:
        """'Set loeschen' (Kontextmenue): Set laden (falls noetig) und
        delete_set() aufrufen - die P14-04-E-Sperre ('letztes Set') und die
        Rueckfrage (Papierkorb, P14-05) greifen dort zentral."""
        if not set_id:
            return
        if self._current_set_id != set_id:
            try:
                definition = self.set_repo.get_set(set_id)
                if definition:
                    self.load_set_into_editor(definition)
            except Exception as e:
                self.log(f"FEHLER beim Laden des Sets: {e}")
                return
        self.delete_set()

    @Slot(str, str, int)
    def _on_move_service(self, set_id: str, service_id: str, delta: int) -> None:
        """Order / (Kontextmenue): Service in der execution_order des Sets
        verschieben - arbeitet direkt auf der DB-Definition und persistiert
        sofort (P14-05-Snapshot via set_repo.save_set)."""
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        order = list(definition.get("execution_order") or [])
        if service_id not in order:
            return
        i = order.index(service_id)
        j = i + delta
        if j < 0 or j >= len(order):
            return
        order[i], order[j] = order[j], order[i]
        definition["execution_order"] = order
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Reihenfolge geaendert: {service_id} "
                 f"({'rauf' if delta < 0 else 'runter'})")
        event_bus.service_set_changed.emit()
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)

    @Slot(str, str)
    def _on_remove_service(self, set_id: str, service_id: str) -> None:
        """'Service entfernen' (Kontextmenue): P14-04-E-Sperrpruefung +
        doppelte Nachfrage (P14-05-Snapshot), dann direkter Entzug aus der
        DB-Definition (kein Umweg ueber die entfernte Service-Sets-Box)."""
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id) or {}
        plugin_id = str(cfg.get("plugin_id") or service_id)
        # P14-04-E: Nur der LETZTE Vorkommen eines Indikator-Services ueber
        # ALLE gespeicherten Sets ist gesperrt.
        if self._plugin_belongs_to_indicator(plugin_id):
            others = self._remaining_sets_with_plugin(
                plugin_id, exclude_set_id=set_id)
            if not others:
                QMessageBox.warning(
                    self, "Service gesperrt",
                    f"Der Service '{plugin_id}' ist der letzte in einem "
                    f"gespeicherten Service-Set.\n"
                    f"Fuer den Indikator muss mindestens ein gueltiges Set "
                    f"mit diesem Service erhalten bleiben (P14-04).")
                return
        reply = QMessageBox.question(
            self, "Service entfernen",
            f"Service '{service_id} [{plugin_id}]' aus dem Set entfernen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            "Der bisherige Set-Stand wird als Snapshot gesichert "
            "(service_set_history). Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        order = [i for i in (definition.get("execution_order") or [])
                 if i != service_id]
        services.pop(service_id, None)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Service entfernt: {service_id}")
        event_bus.service_set_changed.emit()
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)

    @Slot()
    def _on_purge_trash(self) -> None:
        """Leert den Papierkorb ENDGUELTIG (Kontextmenue 'Papierkorb löschen').

        Bugfix 05.08.2026: Doppelte Sicherheitsabfrage (P14-05) – der Vorgang
        ist nicht umkehrbar. Einzelne Sets koennen weiterhin ueber den
        Papierkorb-Dialog (btn_trash_sets) wiederhergestellt werden.
        """
        trash = self.set_repo.list_trash()
        if not trash:
            QMessageBox.information(
                self, "Papierkorb",
                "Der Papierkorb ist leer – es gibt nichts zu löschen.")
            return
        count = len(trash)
        reply = QMessageBox.question(
            self, "Papierkorb löschen",
            f"{count} Set(s) liegen im Papierkorb.\n"
            f"Wirklich ENDGÜLTIG löschen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            "Diese Aktion kann nicht rückgängig gemacht werden.\nFortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        try:
            n = self.set_repo.purge_trash()
        except Exception as e:
            self.log(f"FEHLER beim Leeren des Papierkorbs: {e}")
            return
        self.log(f"Papierkorb geleert: {n} Set(s) endgültig entfernt (P14-05).")
        event_bus.service_set_changed.emit()

    # --- Phase 15 15.01: Symbol- & Favoriten-Verwaltung ---

    @Slot()
    def open_symbols_window(self) -> None:
        """Oeffnet das nicht-modale SymbolsWindow (Singleton-Verhalten).

        Analog zu open_service_window in main.py: Existiert bereits eine
        sichtbare Instanz, wird sie in den Vordergrund geholt statt neu
        geoeffnet (PersistentWindow.get_existing_instance()).
        """
        existing = SymbolsWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = SymbolsWindow(self)  # parent=self nur fuer state_manager-Zugriff
        win.show()

    def _refresh_symbol_combo(self) -> None:
        """Befuellt die Symbol-ComboBox aus den Favoriten (is_favorite == True).

        Wird beim Start und bei jedem `EventBus.favorites_changed`-Event
        aufgerufen (Verbindung im __init__). Fallback auf die Standard-
        Defaults (SILVER/GOLD/BTCUSD), falls keine Favoriten gesetzt sind –
        damit die Service-Ausführung nie ohne Symbol-Auswahl steht. Die aktuelle
        Auswahl bleibt erhalten, sofern sie noch Favorit ist.
        """
        if not self.combo_symbol:
            return
        favorites = self._symbol_repo.get_favorite_symbols()
        if not favorites:
            favorites = list(SymbolRepository.DEFAULT_SYMBOLS)
        current = self.combo_symbol.currentText()
        self.combo_symbol.blockSignals(True)
        self.combo_symbol.clear()
        for sym in favorites:
            self.combo_symbol.addItem(sym)
        idx = self.combo_symbol.findText(current)
        if idx >= 0:
            self.combo_symbol.setCurrentIndex(idx)
        self.combo_symbol.blockSignals(False)

    @Slot(str)
    def log(self, message: str):
        if self.text_log:
            self.text_log.append(message)
            # U15-D2 (Bedien-Feinschliff): Auto-Scroll ans Log-Ende, damit
            # bei langen Scans immer die neueste Meldung sichtbar ist.
            bar = self.text_log.verticalScrollBar()
            if bar is not None:
                bar.setValue(bar.maximum())

    def _on_log_context_menu(self, pos) -> None:
        """U15-D2 (Bedien-Feinschliff): Kontext-Rechtsklick im Log-Bereich.

        Aktionen: 'Kopieren' (nur bei vorhandener Textauswahl) und
        'Log leeren'. Reine QTextEdit-Operationen (copy/clear), keine
        Logik-Duplikate.
        """
        if not self.text_log:
            return
        menu = QMenu(self)
        copy_action = menu.addAction("Kopieren")
        copy_action.setEnabled(bool(self.text_log.textCursor().hasSelection()))
        clear_action = menu.addAction("Log leeren")
        chosen = menu.exec(self.text_log.mapToGlobal(pos))
        if chosen == copy_action:
            self.text_log.copy()
        elif chosen == clear_action:
            self.text_log.clear()

    # =========================================================================
    # Phase 13 Schritt 4: Service-Set-Verwaltung
    # =========================================================================

    def _clear_set_editor(self) -> None:
        """Leert den Set-Zustand (ohne Phase-13-Box: nur interne Felder +
        Parameter-Spalten)."""
        self._current_set_id = None
        self._current_set_definition = None
        # 17.01.04: Auch den Standalone-Plugin-Editor-Modus beenden.
        self._current_plugin_editing = None
        # 10.08.2026 (Bugfix, Varianten-Params): Preset-Modus ebenfalls
        # beenden (sonst wuerde der naechste Save in ein fremdes Preset
        # schreiben).
        self._current_preset_editing = None
        # Phase 15 (Dirty-State): Marker des vorherigen Sets entfernen.
        self._clear_dirty_markers()
        self._clear_service_columns()

    def load_set_into_editor(self, definition: Dict[str, Any]) -> None:
        """Uebernimmt eine ServiceSetDefinition in den internen Zustand und
        baut die dynamischen Service-Spalten (Parameterfenster, rechte
        Splitter-Spalte) neu auf."""
        # Phase 15 (Dirty-State): Marker des vorherigen Sets entfernen - ein
        # frisch geladenes Set ist per Definition unveraendert (kein '*').
        self._clear_dirty_markers()
        self._current_set_id = definition.get("set_id")
        self._current_set_definition = definition
        self._build_service_columns(definition)

    def _next_instance_id(self, services: Dict[str, Any],
                          plugin_id: str) -> str:
        """Liefert die naechste freie instance_id fuer ein Plugin im Set.

        Basis ist der plugin_id selbst (z.B. 'srv_proximity'); bei bereits
        vorhandener Instanz werden '_2', '_3', ... angehaengt."""
        base = plugin_id
        if base not in services:
            return base
        i = 2
        while f"{base}_{i}" in services:
            i += 1
        return f"{base}_{i}"

    def _add_service_to_set(self, set_id: str, plugin_id: str) -> None:
        """Fuegt einen Service (Plugin) mit Registry-Defaults zum Set hinzu.

        Phase 13-Bereinigung (05.08.2026): ersetzt den frueheren
        Eingabe-/Hinzufuegen-Pfad der entfernten Service-Sets-Box.
        Die instance_id wird automatisch vergeben (plugin_id bzw.
        plugin_id_2/_3/...), Duplikate werden dadurch ausgeschlossen.
        Persistiert sofort (set_repo.save_set) + EventBus-Live-Sync."""
        if not set_id or not plugin_id:
            return
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden. "
                     f"Verfuegbare Plugins: {_available_plugin_ids()}")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        order = list(definition.get("execution_order") or [])
        iid = self._next_instance_id(services, plugin_id)
        params = dict(getattr(plugin, "default_params", None) or {})
        lookback = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        services[iid] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
            # Runde 13b (Bugfix Dropdown-NoData): instance_hash mit
            # persistieren, damit NEUE Set-Instanzen von Anfang an die
            # Varianten-Einschraenkung erfuellen (vorher fehlte der Hash
            # beim regularen Hinzufuegen - der MasterTree berechnet ihn fuer
            # Alt-Bestand on-the-fly, neue Instanzen tragen ihn direkt).
            "instance_hash": generate_instance_hash(plugin_id, params),
        }
        order.append(iid)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Service hinzugefuegt: {iid} [{plugin_id}]")
        event_bus.service_set_changed.emit()
        # Aktuelle Editor-Spalten aktualisieren, wenn das Set geladen ist.
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)
    def collect_set_definition(self) -> Dict[str, Any]:
        """Baut aus dem internen Set-Zustand + Parameter-Spalten eine
        ServiceSetDefinition.

        Phase 13-Bereinigung (05.08.2026): Ohne die entfernte Service-Sets-
        Box kommen Name/Beschreibung/Reihenfolge direkt aus der geladenen
        DB-Definition (_current_set_definition); die Werte der dynamischen
        Service-Spalten werden in die services-Konfiguration uebernommen."""
        current = dict(self._current_set_definition or {})
        order = list(current.get("execution_order") or [])
        services = dict(current.get("services") or {})

        # Werte aus den dynamischen Service-Spalten uebernehmen (lookback =
        # Service-Instanz-Einstellung, wird NICHT in params geschrieben).
        for (iid, key), ctrl in self._service_param_controls.items():
            cfg = services.setdefault(
                iid, {"plugin_id": "", "lookback": 1000, "params": {}})
            if key == "lookback":
                cfg["lookback"] = int(self._ctrl_value(ctrl))
            else:
                cfg.setdefault("params", {})[key] = self._ctrl_value(ctrl)

        # Instanz-Beschreibung aus den Spalten uebernehmen
        # (ServiceInstanceConfig.description - gehoert NICHT in params).
        for iid, ctrl in self._service_desc_controls.items():
            cfg = services.setdefault(
                iid, {"plugin_id": "", "lookback": 1000, "params": {}})
            cfg["description"] = ctrl.text().strip()

        # Semantische Versionierung: aktuelle plugin.version einstempeln.
        from analytics.features.feature_builder import PluginRegistry
        registry = PluginRegistry()
        for iid, cfg in services.items():
            pid = cfg.get("plugin_id") or iid
            try:
                plugin = registry.get(pid)
                cfg["version"] = getattr(plugin, "version", "0.0.0") or "0.0.0"
            except KeyError:
                pass

        return {
            "set_id": self._current_set_id or "",
            "display_name": str(current.get("display_name") or ""),
            "description": str(current.get("description") or ""),
            "indicator_id": current.get("indicator_id"),
            "execution_order": order,
            "services": services,
        }
    def _build_tooltip(self, instance_id: str, config: Dict[str, Any]) -> str:
        """Baut einen Rich-Text-Tooltip (HTML) für eine Service-Instanz.

        Angezeigt werden instance_id, Plugin-ID und – falls vorhanden – die
        individuelle Instanz-Beschreibung (ServiceInstanceConfig.description).
        """
        lines = [f"<b>{instance_id}</b>", f"Plugin: {config.get('plugin_id', '?')}"]
        desc = config.get("description")
        if desc:
            lines.append(f"<i>{desc}</i>")
        return "<br>".join(lines)

    def _service_lock(self, plugin_id: str) -> tuple:
        """P14-04-E: (🔒-Präfix, Tooltip-Nachtrag) für die sichtbare Sperr-
        Kennzeichnung im Service-Fenster.

        Ein Service ist gesperrt, wenn er in einem gespeicherten Service-Set
        vorkommt (Indikator-Basisservice). Liefert ("", "") wenn der Service
        frei ist; andernfalls ein 🔒-Präfix für Listeneintrag/Spaltentitel und
        einen HTML-Tooltip-Nachtrag mit dem Namen des verwendeten Sets.
        """
        names = _sets_using_plugin(str(plugin_id), self.set_repo.list_sets())
        if not names:
            return "", ""
        return "🔒 ", (f"<br><b>Gesperrt (P14-04)</b>: wird vom Service-Set "
                       f"'{names[0]}' verwendet – Entfernen nicht möglich")

    def _open_service_desc_editor(self, instance_id: str) -> None:
        """Oeffnet den modalen ServiceDescriptionEditDialog fuer die Instanz-
        Beschreibung (Stift-Button im Parameter-Panel).

        Phase 16: Bearbeitet AUSSCHLIESSLICH die Instanz-Beschreibung
        (ServiceInstanceConfig.description) – kein Plugin-Metadaten-Fallback,
        keine Verarbeitung von Plugin-Beschreibungen im Service Window.
        """
        if not instance_id:
            return
        cfg: Dict[str, Any] = {}
        if self._current_set_definition:
            cfg = dict((self._current_set_definition.get("services") or {})
                       .get(instance_id, {}))
        desc_ctrl = self._service_desc_controls.get(instance_id)
        if desc_ctrl is not None and _qt_valid(desc_ctrl):
            cfg["description"] = desc_ctrl.text()
        plugin_id = cfg.get("plugin_id") or instance_id
        dlg = ServiceDescriptionEditDialog(
            parent=self,
            instance_id=instance_id,
            plugin_id=plugin_id,
            header_line=self._info_header_tooltip(str(plugin_id)),
            description=str(cfg.get("description") or ""),
            title="Service-Beschreibung bearbeiten",
        )
        dlg.save_requested.connect(
            lambda desc, iid=instance_id:
            self._save_instance_description(self._current_set_id or "", iid, desc))
        dlg.exec()

    def _save_instance_description(self, set_id: str, instance_id: str,
                                   new_desc: str) -> None:
        """Persistiert eine geaenderte Instanz-Beschreibung.

        Phase 16 (05.08.2026): Single Source of Truth – die Instanz-
        Beschreibung gehoert ausschliesslich in
        `ServiceInstanceConfig.description` (JSON-Payload des Service-Sets in
        app_data.duckdb, Feld definition['services'][instance_id]
        ['description']). Kein Plugin-Fallback.

        * Editor-Spalte (QLineEdit) + Tooltip werden live aktualisiert.
        * Persistenz via ServiceSetRepository.save_set() + EventBus.
        """
        clean = (new_desc or "").strip()
        # Live-Update im Editor (setText feuert textChanged → Tooltip-Sync)
        desc_ctrl = self._service_desc_controls.get(instance_id)
        if desc_ctrl is not None and _qt_valid(desc_ctrl):
            desc_ctrl.setText(clean)
        # In der geladenen Definition nachziehen (sofortige Folge-Speicherung)
        if self._current_set_definition is not None:
            cfg = (self._current_set_definition.get("services") or {}).get(instance_id)
            if isinstance(cfg, dict):
                cfg["description"] = clean
        # 17.01.04: Standalone-Plugin-Editor – Beschreibung in die Plugin-
        # Konfiguration (global_settings) uebernehmen statt in ein Set.
        if self._current_plugin_editing:
            if self._save_plugin_params():
                self.log(f"Instanz-Beschreibung '{instance_id}' gespeichert "
                         f"(Plugin).")
            return
        if not set_id:
            self.log(f"Instanz-Beschreibung '{instance_id}' aktualisiert "
                     f"(Set noch nicht gespeichert).")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Beschreibung nicht "
                     f"gespeichert.")
            return
        services = definition.get("services") or {}
        if instance_id in services:
            services[instance_id]["description"] = clean
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
            event_bus.service_set_changed.emit()
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Instanz-Beschreibung: {e}")
            return
        # Phase 15 (Dirty-State): explizites Set-Speichern -> '*' entfernen.
        self._clear_dirty_markers()
        self.log(f"Instanz-Beschreibung '{instance_id}' gespeichert.")

    def _save_set_description(self, set_id: str, new_desc: str) -> None:
        """Persistiert die Set-Beschreibung (ServiceSetDefinition.description).

        Phase 16 (05.08.2026): analog zur Instanz-Beschreibung – Single
        Source of Truth ist das JSON-Payload des Sets in app_data.duckdb.
        """
        clean = (new_desc or "").strip()
        if self._current_set_definition is not None and \
                self._current_set_definition.get("set_id") == set_id:
            self._current_set_definition["description"] = clean
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Beschreibung nicht "
                     f"gespeichert.")
            return
        definition["description"] = clean
        try:
            self.set_repo.save_set(definition)
            event_bus.service_set_changed.emit()
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Set-Beschreibung: {e}")
            return
        # Phase 15 (Dirty-State): explizites Set-Speichern -> '*' entfernen.
        self._clear_dirty_markers()
        self.log(f"Set-Beschreibung '{set_id}' gespeichert.")

    @Slot(str, str, str)
    def _on_tree_info_requested(self, set_id: str, service_id: str,
                                plugin_id: str) -> None:
        """Oeffnet den Beschreibungs-Editor / -Dialog fuer die Info-Button-Zeile.

        Bugfix 05.08.2026: Der Info-Button sitzt jetzt direkt im MasterTree
        (Spalte 1) statt in der Box 'Service-Sets (Phase 13)'. Je nach
        Zeilentyp:

          * Service-Zeile:  ServiceDescriptionEditDialog (Instanz-Beschreibung
                            editierbar, header_line = 'aktiv/im <Indikator>').
          * Set-Zeile:      ServiceDescriptionEditDialog (Set-Beschreibung
                            editierbar, header_line aus _info_set_tooltip).
          * Plugin-Zeile:   ServiceDescriptionEditDialog (Plugin-Info, ohne
                            Instanz) – Bugfix 05.08.2026: derselbe Editor wie
                            bei den Einzel-Services der Sets (vorbefuellt mit
                            der Plugin-Beschreibung; kein Persistenz-Ziel).

        Bugfix 05.08.2026: Auch Plugin-/Standalone-Zeilen oeffnen den
        Beschreibungs-Editor (konsistent zu den Einzel-Services). Eine
        persistierbare Beschreibung existiert nur fuer Instanzen (in Sets)
        und fuer die Sets selbst.
        """
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return
        try:
            # 1) Service-Zeile (set_id + service_id) – editierbar
            if service_id and set_id:
                cfg = model.find_service(set_id, service_id) or {}
                pid = str(cfg.get("plugin_id") or service_id)
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id=service_id,
                    plugin_id=pid,
                    header_line=self._info_header_tooltip(pid),
                    description=str(cfg.get("description") or ""),
                    title="Service-Beschreibung bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda desc, s=set_id, i=service_id:
                    self._save_instance_description(s, i, desc))
                dlg.exec()
                return
            # 2) Plugin-Zeile (nur plugin_id; set_id = Gruppenkennung) –
            #    EDITIERBAR wie die Einzel-Services der Sets (Bugfix
            #    05.08.2026): derselbe ServiceDescriptionEditDialog. Ein
            #    Plugin ohne Instanz/Set hat keine persistierbare Instanz-
            #    Beschreibung – der Editor wird mit der Plugin-Metadaten-
            #    Beschreibung vorbefuellt (kein save_requested: Speichern/
            #    Abbrechen schliessen den Dialog, es gibt kein Ziel).
            if plugin_id and not service_id:
                plugin = self._resolve_info_plugin(plugin_id)
                if plugin is None:
                    return
                meta = dict(getattr(plugin, "metadata", None) or {})
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id="",
                    plugin_id=plugin_id,
                    header_line=self._info_header_tooltip(plugin_id),
                    description=str(meta.get("description") or ""),
                    title="Service-Beschreibung bearbeiten",
                )
                dlg.exec()
                return
            # 3) Set-Zeile (nur set_id) – editierbar (Set-Beschreibung)
            if set_id and not service_id and not plugin_id:
                set_def = model.find_set(set_id)
                if not set_def:
                    self.log(f"Set '{set_id}' nicht gefunden.")
                    return
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id="",
                    plugin_id=str(set_def.get("display_name") or set_id),
                    header_line=self._info_set_tooltip(set_def),
                    description=str(set_def.get("description") or ""),
                    title="Set-Beschreibung bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda desc, s=set_id: self._save_set_description(s, desc))
                dlg.exec()
                return
        except (RuntimeError, AttributeError) as e:
            self.log(f"Info-Dialog nicht moeglich: {e}")

    # =========================================================================
    # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im MasterTree-Kontextmenue
    # -------------------------------------------------------------------------
    # 'Data Only Löschen', 'Vollständig Löschen', 'Doc Log bearbeiten' und
    # 'Als Variante duplizieren' fuer Service-Instanzen (in Sets) und
    # Plugin-Clones (indicator_presets). Alle Aktionen laufen entkoppelt
    # ueber die MasterTree-Signale (keine UI-Kopplung, Invariante 2).
    # =========================================================================

    def _find_preset_for_hash(self, plugin_id: str,
                              instance_hash: str) -> Optional[Dict[str, Any]]:
        """Findet das Preset (indicator_presets) eines Clones ueber seinen
        deterministischen instance_hash (20.04, Q2/Q4)."""
        if not plugin_id or not instance_hash:
            return None
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            return None
        try:
            for p in sm.list_plugin_presets(plugin_id) or []:
                if not isinstance(p, dict):
                    continue
                params = p.get("params") or {}
                # 11.08.2026 (Bugfix Varianten-Kollision): Der Hash eines
                # Presets fliesst inkl. preset_name ein (identisch zum
                # ServiceSelectorModel / variant_run_entries). Fallback auf
                # den Legacy-Params-only-Hash fuer Alt-Bestand.
                preset_name = str(p.get("preset_name") or "Default")
                if (generate_instance_hash(plugin_id, params,
                                           preset_name=preset_name)
                        == instance_hash
                        or generate_instance_hash(plugin_id, params)
                        == instance_hash):
                    return p
        except Exception as e:
            self.log(f"Preset-Suche fehlgeschlagen: {e}")
        return None

    def _purge_legacy_allowed(self, plugin_id: str,
                              params: Optional[Dict[str, Any]]) -> bool:
        """True, wenn der Params-only-Legacy-Pool der Variante EINDEUTIG
        dieser Variante gehoert (12.08.2026, Bugfix Runde 6).

        Alt-Rows aus Runs VOR der Preset-Hash-Umstellung (11.08.2026) liegen
        unter dem reinen Params-only-Hash `generate_instance_hash(plugin_id,
        params)` (ohne preset_name). Dieser Pool ist mehreren Varianten mit
        IDENTISCHEN Params gemeinsam - er darf beim 'Data Only Loeschen'
        einer einzelnen Variante nur entfernt werden, wenn KEINE andere
        aktive Variante (Preset/Clone ODER Set-Instanz) denselben
        Params-only-Hash besitzt.

        Returns:
            True = Pool eindeutig dieser Variante zugeordnet (Legacy-Purge
            erlaubt); False = Pool wird geteilt oder nicht bestimmbar.
        """
        if not plugin_id or params is None:
            return False
        try:
            from analytics.engine.service_models import generate_instance_hash
        except Exception:
            return False
        target = generate_instance_hash(plugin_id, params)
        owners = 0
        sm = getattr(self, "_state_manager", None)
        if sm is not None:
            try:
                for p in sm.list_plugin_presets(plugin_id) or []:
                    if not isinstance(p, dict):
                        continue
                    if generate_instance_hash(
                            plugin_id, p.get("params") or {}) == target:
                        owners += 1
            except Exception:
                pass
        try:
            for set_id in self.set_repo.list_sets():
                defn = self.set_repo.get_set(set_id)
                if not isinstance(defn, dict):
                    continue
                for cfg in (defn.get("services") or {}).values():
                    if not isinstance(cfg, dict):
                        continue
                    cpid = str(cfg.get("plugin_id") or "")
                    if cpid.lower() == plugin_id.lower() and \
                            generate_instance_hash(
                                cpid, cfg.get("params") or {}) == target:
                        owners += 1
        except Exception:
            pass
        # owners == 1: nur diese eine Variante belegt den Pool. owners == 0
        # (z. B. Standalone-Service): kein Legacy-Pool-Szenario - False.
        return owners == 1

    def _next_preset_copy_name(self, sm, plugin_id: str,
                               base: str) -> str:
        """Naechster freier Preset-Name fuer eine Varianten-Kopie (Q8).

        Quelle ist `list_plugin_presets(plugin_id)` (nur ECHTE Preset-Rows) –
        NICHT `list_indicator_presets`, das den UI-Default 'Default' immer
        fabriziert. Ist der Basis-Name (z. B. 'Default') noch GAR NICHT
        vergeben – der Fall eines flachen Plugin-Blattes, das seine erste
        Variante erhaelt – wird der Basis-Name direkt verwendet. Sonst
        '<base> (Kopie)', '(Kopie 2)', ...
        """
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if base not in existing:
            return base
        candidate = f"{base} (Kopie)"
        i = 2
        while candidate in existing:
            candidate = f"{base} (Kopie {i})"
            i += 1
        return candidate

    @Slot(str, str, str, str)
    def _on_data_only_purge(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Data Only Löschen' (20.04, Q5): purge_instance_data.

        Entfernt NUR die berechneten Feature-Daten der Instanz aus dem
        feature_store – die Instanz-Konfiguration (Set/Preset) bleibt
        unangetastet; die Daten werden beim naechsten Scan neu berechnet.

        * Service-in-Set: Hash aus der Set-Definition (cfg.instance_hash)
          oder bei Alt-Daten aus den aktuellen Params neu berechnet.
        * Clone/Preset: Hash direkt aus ROLE_INSTANCE_HASH.
        """
        params = None
        if not instance_hash:
            if set_id and service_id:
                model = getattr(self.service_selector, "model", None)
                cfg = model.find_service(set_id, service_id) if model else None
                if cfg:
                    params = cfg.get("params") or {}
                    instance_hash = generate_instance_hash(
                        cfg.get("plugin_id") or service_id, params)
            if not instance_hash:
                self.log("Kein instance_hash fuer 'Data Only Löschen' "
                         "verfuegbar.")
                return
        # 11.08.2026 (Bugfix Runde 5): Parameter der Variante ermitteln
        # – Grundlage fuer den Legacy-Pool-Purge (Params-only-Hash) im
        # FeatureBuilder – sonst bleiben die Alt-Rows und das Datum
        # setzt nach dem Purge nicht auf 'nie' zurueck.
        if params is None:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset:
                params = preset.get("params") or {}
        label = service_id or f"{plugin_id} (#{instance_hash})"
        reply = QMessageBox.question(
            self, "Data Only Löschen",
            f"Berechnete Feature-Daten der Instanz '{label}' "
            f"(#{instance_hash}) dauerhaft löschen?\n\n"
            "Gelöscht werden ALLE Timeframes (M1-MN1) dieser "
            "Variante. Die Instanz-Konfiguration bleibt erhalten – die Daten werden "
            "beim nächsten Scan neu berechnet.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            from analytics.features.feature_builder import FeatureBuilder
            n = FeatureBuilder().purge_instance_data(
                instance_hash, plugin_id, params,
                purge_legacy=self._purge_legacy_allowed(
                    plugin_id, params))
        except Exception as e:
            self.log(f"FEHLER beim Purgen der Feature-Daten: {e}")
            return
        self.log(f"Feature-Daten gelöscht: {n} Zeilen "
                 f"(Instanz #{instance_hash}, alle Timeframes).")
        self._reset_run_progress()
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_delete_complete(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Vollständig Löschen' (20.04): Instanz/Preset + Daten entfernen.

        Zwei Sicherheitsabfragen (P14-05-Muster). Betrifft:
        * Service-in-Set: Instanz aus service_sets entfernen + Feature-Daten
          der Variante purgen (Hash aus cfg bzw. Params).
        * Clone/Preset: indicator_presets-Eintrag löschen + Feature-Daten
          purgen (Archiv-Einheit: einzelner Clone – auch archivierte Clones
          sind hierueber endgueltig entfernt).
        """
        if set_id and service_id:
            self._delete_complete_set_instance(set_id, service_id, plugin_id)
        elif plugin_id:
            self._delete_complete_preset(plugin_id, instance_hash)
        else:
            self.log("Vollständig Löschen: keine Ziel-Instanz.")

    def _delete_complete_set_instance(self, set_id: str, service_id: str,
                                      plugin_id: str) -> None:
        """Voll-Loeschung einer Service-Instanz in einem Set."""
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id) or {}
        pid = str(cfg.get("plugin_id") or plugin_id or service_id)
        # P14-04-E: nur der LETZTE Vorkommen eines Indikator-Services gesperrt.
        if self._plugin_belongs_to_indicator(pid):
            others = self._remaining_sets_with_plugin(
                pid, exclude_set_id=set_id)
            if not others:
                QMessageBox.warning(
                    self, "Service gesperrt",
                    f"Der Service '{pid}' ist der letzte in einem "
                    f"gespeicherten Service-Set.\n"
                    f"Für den Indikator muss mindestens ein gültiges Set "
                    f"mit diesem Service erhalten bleiben (P14-04).")
                return
        label = f"{service_id} [{pid}]"
        reply = QMessageBox.question(
            self, "Vollständig Löschen",
            f"Instanz '{label}' vollständig löschen?\n\n"
            "Die Instanz wird aus dem Set entfernt UND die berechneten "
            "Feature-Daten dieser Parameter-Variante werden gelöscht "
            "(ALLE Timeframes M1-MN1).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            f"'{label}' wird dauerhaft entfernt – inkl. aller gespeicherten "
            "Feature-Daten der Variante. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        # 1) Instanz aus dem Set entfernen
        order = [i for i in (definition.get("execution_order") or [])
                 if i != service_id]
        services.pop(service_id, None)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        # 2) Feature-Daten der Variante purgen
        hash_ = str(cfg.get("instance_hash") or "")
        if not hash_:
            hash_ = generate_instance_hash(pid, cfg.get("params") or {})
        if hash_:
            try:
                from analytics.features.feature_builder import FeatureBuilder
                n = FeatureBuilder().purge_instance_data(
                    hash_, pid, cfg.get("params") or {})
            except Exception as e:
                n = 0
                self.log(f"WARN: Feature-Daten-Purge fehlgeschlagen: {e}")
            self.log(f"Variante #{hash_} purged ({n} Zeilen).")
            self._reset_run_progress()
        self.log(f"Instanz vollständig gelöscht: {label}")
        event_bus.service_set_changed.emit()
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)

    def _delete_complete_preset(self, plugin_id: str,
                                instance_hash: str) -> None:
        """Voll-Loeschung eines Plugin-Presets/Clones."""
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            self.log(f"Preset zu #{instance_hash} nicht gefunden.")
            return
        preset_name = str(preset.get("preset_name") or "Default")
        indicator_id = str(preset.get("indicator_id") or "")
        reply = QMessageBox.question(
            self, "Vollständig Löschen",
            f"Preset '{preset_name}' von '{plugin_id}' vollständig löschen?"
            f"\n\nDas Preset wird aus indicator_presets entfernt UND die "
            "berechneten Feature-Daten dieser Parameter-Variante werden "
            "gelöscht (ALLE Timeframes M1-MN1).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            f"'{preset_name}' wird dauerhaft gelöscht – inkl. aller "
            "gespeicherten Feature-Daten der Variante. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        sm = getattr(self, "_state_manager", None)
        if sm is not None and indicator_id:
            try:
                sm.delete_indicator_preset(indicator_id, preset_name)
            except Exception as e:
                self.log(f"FEHLER beim Löschen des Presets: {e}")
                return
        if instance_hash:
            try:
                from analytics.features.feature_builder import FeatureBuilder
                n = FeatureBuilder().purge_instance_data(
                    instance_hash, plugin_id, preset.get("params") or {},
                    purge_legacy=self._purge_legacy_allowed(
                        plugin_id, preset.get("params") or {}))
            except Exception as e:
                n = 0
                self.log(f"WARN: Feature-Daten-Purge fehlgeschlagen: {e}")
            self.log(f"Variante #{instance_hash} purged ({n} Zeilen).")
            self._reset_run_progress()
        self.log(f"Preset vollständig gelöscht: '{preset_name}'.")
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_doc_log_requested(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Doc Log bearbeiten' (20.04, Q1/Q7).

        Oeffnet den ServiceDescriptionEditDialog fuer das Freitextfeld
        (Negativ-Wissen). Persistenz:
        * Service-in-Set: ServiceInstanceConfig.doc_log (Set-JSON).
        * Clone/Preset: indicator_presets.doc_log.
        """
        try:
            if set_id and service_id:
                model = getattr(self.service_selector, "model", None)
                cfg = model.find_service(set_id, service_id) if model else None
                cfg = cfg or {}
                pid = str(cfg.get("plugin_id") or service_id)
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id=service_id,
                    plugin_id=pid,
                    header_line=self._info_header_tooltip(pid),
                    description=str(cfg.get("doc_log") or ""),
                    title="Doc Log bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda text, s=set_id, i=service_id:
                    self._save_instance_doc_log(s, i, text))
                dlg.exec()
                return
            if plugin_id and instance_hash:
                preset = self._find_preset_for_hash(plugin_id, instance_hash)
                preset_name = str((preset or {}).get("preset_name")
                                  or instance_hash)
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id=preset_name,
                    plugin_id=plugin_id,
                    header_line=self._info_header_tooltip(plugin_id),
                    description=str((preset or {}).get("doc_log") or ""),
                    title="Doc Log bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda text, p=plugin_id, h=instance_hash:
                    self._save_plugin_doc_log(p, h, text))
                dlg.exec()
                return
        except (RuntimeError, AttributeError) as e:
            self.log(f"Doc-Log-Dialog nicht möglich: {e}")

    def _save_instance_doc_log(self, set_id: str, instance_id: str,
                               new_log: str) -> None:
        """Persistiert das Doc-Log einer Service-Instanz (20.04, Q7).

        Ziel: ServiceInstanceConfig.doc_log im Set-JSON (single source of
        truth wie description). Analog _save_instance_description.
        """
        clean = (new_log or "").strip()
        # In der geladenen Definition nachziehen (sofortige Folge-Speicherung)
        if self._current_set_definition is not None:
            cfg = (self._current_set_definition.get("services") or {}).get(
                instance_id)
            if isinstance(cfg, dict):
                cfg["doc_log"] = clean
        if not set_id:
            self.log(f"Doc Log '{instance_id}' aktualisiert "
                     f"(Set noch nicht gespeichert).")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Doc Log nicht "
                     f"gespeichert.")
            return
        services = definition.get("services") or {}
        if instance_id in services:
            services[instance_id]["doc_log"] = clean
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
            event_bus.service_set_changed.emit()
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Doc Logs: {e}")
            return
        self._clear_dirty_markers()
        self.log(f"Doc Log '{instance_id}' gespeichert.")

    def _save_plugin_doc_log(self, plugin_id: str, instance_hash: str,
                             new_log: str) -> None:
        """Persistiert das Doc-Log eines Plugin-Presets (20.04, Q7)."""
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            self.log("Doc Log nicht gespeichert (kein StateManager).")
            return
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if not preset or not preset.get("indicator_id"):
            self.log(f"Preset zu #{instance_hash} nicht gefunden.")
            return
        try:
            sm.set_plugin_preset_doc_log(
                preset.get("indicator_id"), preset.get("preset_name"),
                new_log)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Preset-Doc-Logs: {e}")
            return
        self.log(f"Doc Log '{preset.get('preset_name')}' gespeichert.")
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_duplicate_variant(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Als Variante duplizieren' (20.04, Q8).

        * Service-in-Set: neue Instanz mit kopierten Parametern + neu
          berechnetem instance_hash (neue instance_id via _next_instance_id).
        * Clone/Preset: neues Preset mit kopierten Parametern (Name
          '<Preset> (Kopie)'); aus einem flachen Plugin-Blatt entsteht so
          die erste Variante.
        """
        if set_id and service_id:
            self._duplicate_set_instance(set_id, service_id)
            return
        if plugin_id:
            self._duplicate_preset(plugin_id, instance_hash)
            return
        self.log("Als Variante duplizieren: keine Ziel-Instanz.")

    @Slot(str, str, str)
    def _on_rename_variant(self, plugin_id: str, instance_hash: str,
                           new_name: str) -> None:
        """'Variante umbenennen' (10.08.2026, Bugfix).

        Benennt ein Plugin-Preset (Clone/Variante) in indicator_presets um.
        Kollisionspruefung gegen die UEBRIGEN Presets des Plugins; die
        Feature-Store-Daten (Spalte instance_hash) bleiben unberuehrt
        (der Hash haengt an den Parametern, nicht am Namen).
        """
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            self.log(f"Preset zu #{instance_hash} nicht gefunden – "
                     f"Umbenennen abgebrochen.")
            return
        old_name = str(preset.get("preset_name") or "Default")
        indicator_id = str(preset.get("indicator_id") or "")
        if not indicator_id:
            self.log("Preset hat keine indicator_id – Umbenennen abgebrochen.")
            return
        clean = (new_name or "").strip()
        if not clean or clean == old_name:
            return
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            self.log("Umbenennen nicht moeglich (kein StateManager).")
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception as e:
            self.log(f"FEHLER beim Laden der Preset-Namen: {e}")
            return
        if clean in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{clean}'.")
            return
        try:
            sm.rename_indicator_preset(indicator_id, old_name, clean)
        except Exception as e:
            self.log(f"FEHLER beim Umbenennen der Variante: {e}")
            return
        self.log(f"Variante '{old_name}' umbenannt zu '{clean}'.")
        event_bus.service_set_changed.emit()

    def _duplicate_set_instance(self, set_id: str, service_id: str) -> None:
        """Dupliziert eine Service-Instanz in ihrem Set (Q8)."""
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id)
        if not isinstance(cfg, dict):
            self.log(f"Instanz '{service_id}' nicht gefunden.")
            return
        pid = str(cfg.get("plugin_id") or service_id)
        iid = self._next_instance_id(services, pid)
        copy = dict(cfg)
        copy["params"] = dict(cfg.get("params") or {})
        copy["instance_hash"] = generate_instance_hash(pid, copy["params"])
        copy.pop("description", None)
        copy.pop("doc_log", None)
        services[iid] = copy
        order = list(definition.get("execution_order") or [])
        order.append(iid)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Variante '{iid}' dupliziert aus '{service_id}' "
                 f"(#{copy['instance_hash']}).")
        event_bus.service_set_changed.emit()
        # Q8-Bugfix: Ergebnis SICHTBAR machen – das Ziel-Set wird in den
        # Parameter-Editor geladen (neue Service-Spalte der Variante) und
        # die neue Instanz im Baum expandiert/selektiert.
        self.load_set_into_editor(definition)
        tree = getattr(getattr(self, "service_selector", None),
                       "master_tree", None)
        if tree is not None:
            tree.select_instance(set_id, iid)

    def _duplicate_preset(self, plugin_id: str, instance_hash: str) -> None:
        """Dupliziert einen Plugin-Clone als neues Preset (Q8)."""
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            self.log("Variante nicht dupliziert (kein StateManager).")
            return
        if instance_hash:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset is None:
                self.log(f"Preset zu #{instance_hash} nicht gefunden.")
                return
            base = str(preset.get("preset_name") or "Default")
            params = dict(preset.get("params") or {})
            indicator_id = str(preset.get("indicator_id") or "")
            version = preset.get("version")
            # Diff 2 (User-Bugreport 09.08.2026): Eine duplizierte Variante
            # ist IMMER batch-aktiv (is_active_batch=True) – NICHT der Status
            # des Quell-Presets. Sonst bliebe eine archivierte/inaktive Kopie
            # unsichtbar: Scans/LiveAnalyzer ignorieren is_active_batch=False
            # und das Analytics-Dropdown zeigt sie erst nach einem Run.
            is_active = True
        else:
            # Flaches Plugin-Blatt: aktuelle Standalone-Parameter
            # (global_settings, Key 'plugin_params_<plugin_id>').
            try:
                raw = sm.get_global_value(f"plugin_params_{plugin_id}", {})
            except Exception:
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            base = "Default"
            params = dict(raw.get("params") or {})
            indicator_id = plugin_id
            version = raw.get("version") or "1.0.0"
            is_active = True
        if not indicator_id:
            indicator_id = plugin_id
        # 10.08.2026 (Bugfix): Beim Anlegen einer neuen Variante MUSS ein
        # neuer Name vergeben werden – kein stummes Auto-Schema
        # ('<base> (Kopie)'). Der Dialog ist mit dem freien Kopiernamen
        # vorbelegt; Kollisionen werden abgefangen.
        suggested = self._next_preset_copy_name(sm, plugin_id, base)
        new_name, ok = QInputDialog.getText(
            self, "Variante anlegen",
            f"Name für die neue Variante (aus '{base}'):", text=suggested)
        new_name = (new_name or "").strip()
        if not ok or not new_name:
            self.log("Variante nicht dupliziert (Name fehlt/abgebrochen).")
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if new_name in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{new_name}'.")
            return
        try:
            sm.save_indicator_preset(
                indicator_id, new_name, params,
                plugin_id=plugin_id,
                version=version,
                is_active_batch=is_active,
                doc_log="",
            )
        except Exception as e:
            self.log(f"FEHLER beim Duplizieren der Variante: {e}")
            return
        # 11.08.2026 (Bugfix Varianten-Kollision): Der Hash der neuen
        # Variante fliesst inkl. des NEUEN Preset-Namens ein (identisch zum
        # ServiceSelectorModel) - sonst kollidieren Params-only-Hashes.
        new_hash = generate_instance_hash(plugin_id, params,
                                          preset_name=new_name)
        self.log(f"Variante '{new_name}' dupliziert aus '{base}' "
                 f"(#{new_hash}).")
        event_bus.service_set_changed.emit()
        # Q8-Bugfix: Ergebnis SICHTBAR machen – den neuen Clone-Knoten im
        # Baum expandieren/selektieren (ohne Editor-Overwrite; der Clone-
        # Tooltip zeigt die kopierten Parameter).
        tree = getattr(getattr(self, "service_selector", None),
                       "master_tree", None)
        if tree is not None:
            tree.select_clone(plugin_id, new_hash)

    def _resolve_info_plugin(self, plugin_id: str):
        """Liefert das Plugin aus der Registry (oder None + Log-Eintrag)."""
        try:
            from analytics.features.feature_builder import PluginRegistry
            return PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden.")
            return None

    def _info_header_tooltip(self, plugin_id: str) -> str:
        """Erste Dialog-Zeile = Badge-Header des Info-Buttons (20.03.02, F5).

        Vereinheitlichtes Format: '📌 im <Indikator> | 🟢 aktiv in
        <Indikator>' bzw. '📌 im <Indikator> | ⚪ inaktiv'. Leer ohne
        Indikator-Zugehoerigkeit.
        """
        model = getattr(self.service_selector, "model", None)
        if model is None or not model.belongs_to_indicator(plugin_id):
            return ""
        name = model.get_indicator_display_name(plugin_id)
        if model.is_active_in_chart(plugin_id):
            return f"📌 im {name} | 🟢 aktiv in {name}"
        return f"📌 im {name} | ⚪ inaktiv"

    def _info_set_tooltip(self, set_def: Dict[str, Any]) -> str:
        """Erste Dialog-Zeile fuer Set-Zeilen (20.03.02, F5).

        Vereinheitlichtes Badge-Format analog _info_header_tooltip; mehrere
        Indikatoren mit ' + ' verknuepft ('📌 im <I1> + <I2> | 🟢 aktiv in
        <I1> + <I2>' bzw. '⚪ inaktiv').
        """
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return ""
        names = model.get_set_indicator_names(set_def or {})
        if not names:
            return ""
        label = " + ".join(names)
        if model.is_set_active(set_def or {}):
            return f"📌 im {label} | 🟢 aktiv in {label}"
        return f"📌 im {label} | ⚪ inaktiv"

    @Slot()
    def delete_set(self) -> None:
        """Loescht das aktive Set in den Papierkorb (P14-05).

        Phase 13-Bereinigung (05.08.2026): Ohne die entfernte Service-Sets-
        Box wird direkt auf die DB-Definition des geladenen Sets zugegriffen
        (kein NamedItemAdapter mehr). P14-04-E-Sperre ('letztes Set') und
        Papierkorb-Rueckfrage bleiben unveraendert."""
        current_id = self._current_set_id
        if not current_id:
            self.log("Kein Set geladen - Loeschen nicht moeglich.")
            return
        current = None
        try:
            current = self.set_repo.get_set(current_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not current:
            self.log(f"Set '{current_id}' nicht gefunden.")
            return
        # P14-04-E-Sperre: Letzter Vorkommen eines Indikator-Services.
        services = current.get("services") or {}
        for cfg in services.values():
            if not isinstance(cfg, dict):
                continue
            pid = str(cfg.get("plugin_id") or "")
            if not pid or not self._plugin_belongs_to_indicator(pid):
                continue
            others = self._remaining_sets_with_plugin(
                pid, exclude_set_id=current_id)
            if not others:
                QMessageBox.warning(
                    self, "Loeschen gesperrt",
                    f"Dieses Service-Set enthaelt den letzten "
                    f"gespeicherten Service '{pid}' fuer den Indikator.\n"
                    f"Es muss mindestens ein gueltiges Set mit diesem "
                    f"Service erhalten bleiben (P14-04).")
                return
        name = str(current.get("display_name") or current_id)
        reply = QMessageBox.question(
            self, "Set in den Papierkorb verschieben",
            f"Set '{name}' wirklich in den Papierkorb verschieben?\n"
            f"(Wiederherstellung ueber den Papierkorb-Dialog moeglich.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            ok = self.set_repo.delete_set(current_id)
        except Exception as e:
            self.log(f"FEHLER beim Loeschen des Sets: {e}")
            return
        if not ok:
            self.log(f"Set '{current_id}' nicht gefunden.")
            return
        self.log(f"Set in den Papierkorb verschoben (P14-05): {current_id}")
        event_bus.service_set_changed.emit()
        self._current_set_id = None
        self._current_set_definition = None
        self._clear_dirty_markers()
        self._clear_service_columns()
    @Slot()
    def show_trash_dialog(self) -> None:
        """Öffnet den Papierkorb-Dialog für Service-Sets (P14-05).

        Phase 15 U15-D1: Der Dialog ist in serviceui/trash_dialog.py als
        eigenständige Widget-Klasse (ServiceSetTrashDialog) ausgelagert –
        Verhalten unverändert (inkl. doppelter Sicherheitsnachfrage).
        """
        dialog = ServiceSetTrashDialog(
            repo=self.set_repo,
            log_fn=self.log,
            refresh_fn=lambda: None,
            parent=self,
        )
        dialog.exec()

    # =========================================================================
    # Phase 14 P14-02: Hot-Reload der Plugins (Dynamic Discovery)
    # =========================================================================

    def closeEvent(self, event):
        # PersistentWindow.save_state() wird in super().closeEvent gerufen
        # 05.08.2026: Gezielter Kontextmenue-Run-Worker sauber beenden.
        if self._run_worker and self._run_worker.isRunning():
            # 12.08.2026 (WAL-Korruption beim App-Exit): Worker VOR dem
            # Fenster-Close sauber stoppen - sonst stirbt der Thread mitten
            # im DB-Write, wenn die App den Prozess beendet (korrupte WAL
            # beim naechsten Start). stop() setzt nur das Abbruch-Flag; der
            # Worker beendet sich an der naechsten Service-Grenze.
            self._run_worker.stop()
            self._run_worker.wait(5000)
        super().closeEvent(event)

```

--------------------------------------------------

### DATEI: serviceui/status_panel.py
```py
# serviceui/status_panel.py
"""
Service-UI: Status- & Log-Panel (Phase 15 15.02).

Entkoppelte Anzeige fuer Laufzeit, Fortschritt und das Scan-/Set-Log.
Reines Anzeige-Widget ohne Geschaeftslogik (SRP): Der Orchestrator
(service_win.py) versorgt es ueber Methoden mit Werten.

Enthaelt:
  * Statuszeile (Laufzeit / Fortschritt)
  * Log-View (QTextEdit, readonly) mit Auto-Scroll ans Ende
"""

from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QTextEdit, QVBoxLayout, QWidget,
)


class StatusPanel(QWidget):
    """Status- & Log-Anzeige des Service-Fensters."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.label_elapsed = QLabel("Laufzeit:")
        self.label_elapsed_value = QLabel("00:00:00")
        self.label_progress = QLabel("Fortschritt:")
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.setPlaceholderText("Scan-/Set-Log wird hier angezeigt...")

        status_row = QHBoxLayout()
        status_row.addWidget(self.label_elapsed)
        status_row.addWidget(self.label_elapsed_value)
        status_row.addStretch(1)
        status_row.addWidget(self.label_progress)
        status_row.addWidget(self.progress_bar, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(status_row)
        lay.addWidget(self.text_log, 1)

    # -------------------------------------------------------------------------
    # Laufzeit
    # -------------------------------------------------------------------------

    @Slot(int)
    def set_elapsed_seconds(self, seconds: int) -> None:
        """Setzt die Laufzeit-Anzeige (h:mm:ss)."""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        self.label_elapsed_value.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def reset_elapsed(self) -> None:
        self.set_elapsed_seconds(0)

    # -------------------------------------------------------------------------
    # Fortschritt
    # -------------------------------------------------------------------------

    @Slot(int)
    def set_progress(self, current: int, total: int) -> None:
        """Setzt die Fortschritts-Anzeige."""
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(current)

    @Slot(int)
    def set_progress_value(self, value: int) -> None:
        self.progress_bar.setValue(value)

    # -------------------------------------------------------------------------
    # Log
    # -------------------------------------------------------------------------

    @Slot(str)
    def log(self, message: str) -> None:
        """Haengt eine Meldung ans Log an und scrollt ans Ende."""
        self.text_log.append(message)
        bar = self.text_log.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def clear_log(self) -> None:
        self.text_log.clear()

```

--------------------------------------------------

### DATEI: serviceui/symbols_win.py
```py
# serviceui/symbols_win.py
"""
serviceui/symbols_win.py - Nicht-modales SymbolsWindow (Phase 15.01).

Ermoeglicht die zentrale Symbol- & Favoriten-Verwaltung:
- 2-Spalten-Tabelle (Spalte 0: Symbol, Spalte 1: ★ Favoriten-Toggle per Klick).
- Live-Suche mit `scrollToItem` zum ersten Treffer.
- ESC schliesst das Fenster.
- Jeder Favoriten-Toggle persistiert ueber `SymbolRepository` und emittiert
  `EventBus.favorites_changed` – ServiceWindow (und spaeter AnalyticsWindow)
  befuellen daraufhin ihre Symbol-Dropdowns neu (Entkopplung via EventBus).

Architektur (SRP): Das Fenster ist NUR Event-Handling & Rendering. SQL-Zugriff
erfolgt exklusiv ueber `SymbolRepository` (kein SQL in UI, Invariante 4).
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.event_bus import event_bus
from persistent_win import PersistentWindow, register_persistent_window
from symbol_repository import SymbolRepository, get_symbol_repository

# Sichtbare Darstellung: ausgefuellter Stern = Favorit, leerer Stern = nicht.
STAR_FAVORITE = "★"
STAR_NORMAL = "☆"


@register_persistent_window(auto_restore=False)
class SymbolsWindow(PersistentWindow):
    """Nicht-modales Fenster zur Symbol- & Favoriten-Verwaltung."""

    INSTANCE_ID = "win_symbols"

    def __init__(self, parent=None, repo: Optional[SymbolRepository] = None) -> None:
        super().__init__(parent)
        self.repo: SymbolRepository = repo or get_symbol_repository()
        self._build_ui()
        self._load_symbols()

    # ------------------------------------------------------------------
    # UI-Aufbau (reines Rendering, kein SQL)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("PyTrader - Symbole & Favoriten")
        self.resize(420, 560)

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Symbol suchen...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_edit)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Symbol", "★"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.Stretch)
            header.setSectionResizeMode(1, QHeaderView.Fixed)
            self.table.setColumnWidth(1, 48)
        # Spalte 1 zentriert darstellen (★ / ☆)
        self.table.setColumnWidth(1, 48)
        self.table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.table)

    # ------------------------------------------------------------------
    # Daten-Befuellung
    # ------------------------------------------------------------------
    def _load_symbols(self) -> None:
        """Befuellt die Tabelle aus der gespeicherten Liste (`get_symbols()`).

        User-Anweisung 04.08.2026 (15.01-Nachtrag 3): Der MT5-Live-Fetch wurde
        aus diesem Fenster entfernt – alle Broker-Symbole werden NUR noch
        EINMALIG beim App-Start (main.py) von MT5 geladen und persistiert.
        Dieses Fenster liest ausschliesslich den gespeicherten DB-Stand
        (kein MT5-Zugriff beim Oeffnen -> keine Verzoegerungen).
        """
        self._rows: dict = {}  # symbol -> Zeilen-Index
        self.table.setRowCount(0)
        for entry in self.repo.get_symbols():
            self._append_symbol_row(entry["symbol"], entry["is_favorite"])

    def _append_symbol_row(self, symbol: str, is_favorite: bool) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        sym_item = QTableWidgetItem(symbol)
        sym_item.setData(Qt.UserRole, symbol)
        self.table.setItem(row, 0, sym_item)
        star_item = QTableWidgetItem(STAR_FAVORITE if is_favorite else STAR_NORMAL)
        star_item.setTextAlignment(Qt.AlignCenter)
        star_item.setData(Qt.UserRole, symbol)
        self.table.setItem(row, 1, star_item)
        self._rows[symbol] = row

    # ------------------------------------------------------------------
    # Interaktion
    # ------------------------------------------------------------------
    def _on_cell_clicked(self, row: int, column: int) -> None:
        """Klick in Spalte 1 togglet den Favoriten und emittiert das Event."""
        if column != 1:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        symbol = str(item.data(Qt.UserRole) or item.text())
        new_state = self.repo.toggle_favorite(symbol)
        star_item = self.table.item(row, 1)
        if star_item is not None:
            star_item.setText(STAR_FAVORITE if new_state else STAR_NORMAL)
        event_bus.favorites_changed.emit()

    def _apply_filter(self, text: str) -> None:
        """Live-Filter: blendet nicht passende Zeilen aus und scrollt zum
        ersten Treffer (scrollToItem, Spalte 0)."""
        query = text.strip().lower()
        first_visible_row = -1
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            symbol = item.text().lower() if item is not None else ""
            match = (query in symbol) if query else True
            self.table.setRowHidden(row, not match)
            if match and first_visible_row < 0:
                first_visible_row = row
        if first_visible_row >= 0:
            item = self.table.item(first_visible_row, 0)
            if item is not None:
                self.table.scrollToItem(item, QAbstractItemView.PositionAtTop)

    def keyPressEvent(self, event) -> None:
        """ESC schliesst das Fenster (Standard-PersistentWindow-Verhalten)."""
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

```

--------------------------------------------------

### DATEI: serviceui/trash_dialog.py
```py
# serviceui/trash_dialog.py
"""
Service-UI: Papierkorb-Dialog für Service-Sets (Soft-Delete).

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert –
Verhalten unverändert (inkl. doppelter Sicherheitsnachfrage, P14-05).

Der Dialog ist eine reine UI-Komponente: Er spricht ausschließlich die
Repository-API an (keine direkten SQL-Zugriffe) und protokolliert jede
Aktion über eine Log-Callback. Das endgültige Löschen/Bereinigen erfolgt
IMMER mit doppelter Sicherheitsnachfrage (User-Vorgabe P14-05).
"""

from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from analytics.engine.service_set_repository import ServiceSetRepository
from config.event_bus import event_bus

#: Deutsche Wochenkürzel (Index = datetime.weekday(), 0=Montag) für das
#: Datumsformat 'E. DD.MM.JJ HH:MM' (z.B. 'Mo. 04.07.26 14:34').
_GERMAN_WEEKDAYS = ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."]


def _format_deleted_at(value: object) -> str:
    """Formatiert den deleted_at-Zeitstempel als 'E. DD.MM.JJ HH:MM'.

    DuckDB liefert TIMESTAMP als datetime-Objekt; alternativ werden
    ISO-Strings (mit/ohne Z) akzeptiert. Nicht parsebare Werte werden als
    Rohwert zurueckgegeben, fehlende Werte als leerer String (defensiv).
    """
    if isinstance(value, datetime):
        dt = value
    elif value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return str(value)
    else:
        return ""
    return f"{_GERMAN_WEEKDAYS[dt.weekday()]} {dt.strftime('%d.%m.%y %H:%M')}"


def _deleted_at_sort_key(value: object) -> datetime:
    """Normalisiert deleted_at zu einem vergleichbaren datetime für die
    absteigende Sortierung (neueste zuerst). Nicht parsebare/fehlende Werte
    gelten als älteste (datetime.min)."""
    if isinstance(value, datetime):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return datetime.min
    return datetime.min


class ServiceSetTrashDialog(QDialog):
    """Phase 14 P14-05: Papierkorb-Dialog für Service-Sets (Soft-Delete).

    Zeigt alle soft-gelöschten Sets (list_trash()) mit Name und
    Lösch-Zeitstempel. Aktionen:
      - Wiederherstellen  : restore_set_from_trash() verschiebt das Set
                            zurück nach service_sets (das Set-Dropdown des
                            Hauptfensters wird anschließend refresht).
      - Endgültig löschen : purge_trash_set() mit doppelter Sicherheits-
                            abfrage (Vorgang ist nicht umkehrbar).
      - Papierkorb leeren : purge_trash() mit doppelter Sicherheits-
                            abfrage (Vorgang ist nicht umkehrbar).
    """

    def __init__(
        self,
        repo: ServiceSetRepository,
        log_fn: Callable[[str], None],
        refresh_fn: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._repo = repo
        self._log = log_fn
        self._refresh = refresh_fn

        self.setWindowTitle("Papierkorb - Service-Sets")
        self.setMinimumSize(440, 340)

        layout = QVBoxLayout(self)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        # Bugfix 05.08.2026: Tabelle statt Liste – das Löschdatum steht als
        # EIGENE Spalte GANZ VORN ("Gelöscht am"), danach nur der Name des
        # gelöschten Objekts (kein Datum hinter dem Namen). Sortierung:
        # neueste zuerst (absteigend nach deleted_at, siehe _reload).
        self.trash_table = QTableWidget()
        self.trash_table.setColumnCount(2)
        self.trash_table.setHorizontalHeaderLabels(["Gelöscht am", "Name"])
        self.trash_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trash_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.trash_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trash_table.verticalHeader().setVisible(False)
        header = self.trash_table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.trash_table, 1)

        btn_row = QHBoxLayout()
        self.btn_restore = QPushButton("Wiederherstellen")
        self.btn_purge_one = QPushButton("Löschen")
        self.btn_purge_all = QPushButton("Papierkorb leeren")
        btn_close = QPushButton("Schliessen")
        for b in (self.btn_restore, self.btn_purge_one, self.btn_purge_all, btn_close):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.btn_restore.clicked.connect(self._restore)
        self.btn_purge_one.clicked.connect(self._purge_selected)
        self.btn_purge_all.clicked.connect(self._purge_all)
        btn_close.clicked.connect(self.accept)

        self._reload()

    # --- intern ---

    def _reload(self) -> None:
        self.trash_table.setRowCount(0)
        trash_items = list(self._repo.list_trash())
        # Bugfix 05.08.2026: Neueste zuerst – absteigend nach deleted_at
        # (das Repository liefert aufsteigend).
        trash_items.sort(
            key=lambda it: _deleted_at_sort_key(it.get("deleted_at")),
            reverse=True,
        )
        for row, item in enumerate(trash_items):
            set_id = item.get("set_id")
            name = item.get("display_name") or set_id or "Unbenannt"
            deleted_at = _format_deleted_at(item.get("deleted_at"))
            date_item = QTableWidgetItem(deleted_at)
            date_item.setData(Qt.UserRole, set_id)
            self.trash_table.insertRow(row)
            self.trash_table.setItem(row, 0, date_item)
            self.trash_table.setItem(row, 1, QTableWidgetItem(name))
        has_items = self.trash_table.rowCount() > 0
        self.btn_restore.setEnabled(has_items)
        self.btn_purge_one.setEnabled(has_items)
        self.btn_purge_all.setEnabled(has_items)
        self.hint.setText(
            "Der Papierkorb ist leer."
            if not has_items
            else "Soft-geloeschte Service-Sets (P14-05). Wiederherstellen "
                 "verschiebt das Set zurueck in die aktive Liste; "
                 "endgueltiges Loeschen ist nicht umkehrbar."
        )

    def _selected_id(self) -> Optional[str]:
        row = self.trash_table.currentRow()
        if row < 0:
            return None
        item = self.trash_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _restore(self) -> None:
        set_id = self._selected_id()
        if not set_id:
            return
        if self._repo.restore_set_from_trash(set_id):
            self._log(f"Set wiederhergestellt (P14-05): {set_id}")
            self._reload()
            self._refresh()
            # Phase 15.02: Struktur-Aenderung -> EventBus (Live-Sync aller
            # ServiceSelectorModel-Instanzen, Invariante 5).
            event_bus.service_set_changed.emit()
        else:
            self._log(f"Set '{set_id}' nicht im Papierkorb gefunden.")

    def _purge_selected(self) -> None:
        set_id = self._selected_id()
        if not set_id:
            return
        # Doppelte Sicherheitsnachfrage - endgueltiges Loeschen ist nicht
        # umkehrbar (User-Vorgabe P14-05).
        first = QMessageBox.question(
            self, "Endgueltig loeschen?",
            "Das Set wird ENDGUELTIG geloescht und kann nicht "
            "wiederhergestellt werden. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if first != QMessageBox.Yes:
            return
        second = QMessageBox.question(
            self, "Wirklich endgueltig loeschen?",
            "Dieser Vorgang ist NICHT umkehrbar. Das Set wird unwiderruflich "
            "aus dem Papierkorb entfernt. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if second != QMessageBox.Yes:
            return
        if self._repo.purge_trash_set(set_id):
            self._log(f"Set endgueltig geloescht (P14-05): {set_id}")
            self._reload()
            # Phase 15: Struktur-Aenderung -> EventBus (Live-Sync aller
            # ServiceSelectorModel-Instanzen, Invariante 5).
            event_bus.service_set_changed.emit()
        else:
            self._log(f"Set '{set_id}' nicht im Papierkorb gefunden.")

    def _purge_all(self) -> None:
        if self.trash_table.rowCount() == 0:
            return
        # Doppelte Sicherheitsnachfrage - endgueltiges Loeschen ist nicht
        # umkehrbar (User-Vorgabe P14-05).
        first = QMessageBox.question(
            self, "Papierkorb leeren?",
            f"Alle {self.trash_table.rowCount()} Sets im Papierkorb werden "
            "ENDGUELTIG geloescht und koennen nicht wiederhergestellt "
            "werden. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if first != QMessageBox.Yes:
            return
        second = QMessageBox.question(
            self, "Wirklich Papierkorb leeren?",
            "Dieser Vorgang ist NICHT umkehrbar. Alle Sets werden "
            "unwiderruflich entfernt. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if second != QMessageBox.Yes:
            return
        count = self._repo.purge_trash()
        self._log(f"Papierkorb geleert (P14-05): {count} Set(s) endgueltig entfernt.")
        self._reload()
        # Phase 15: Struktur-Aenderung -> EventBus (Live-Sync aller
        # ServiceSelectorModel-Instanzen, Invariante 5).
        event_bus.service_set_changed.emit()

```

--------------------------------------------------

