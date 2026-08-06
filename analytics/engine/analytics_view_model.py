# analytics/engine/analytics_view_model.py
"""
analytics_view_model.py - AnalyticsViewModel (Phase 15.03 Schritt 4).

Vermittelt zwischen `AnalyticsRepository` (+ `FeatureStoreReader`), dem
asynchronen `AnalyticsAsyncWorker` und den UI-Pages (analytics/ui/*,
Invariante 4 / MVVM). KEIN SQL, KEIN UI-Code – nur Qt-Core (QObject/QTimer)
und Repositories. Datenfluss:

    UI-Page -> set_*()/request_*() -> ViewModel (Debounce-QTimer 250 ms)
    -> AnalyticsAsyncWorker (QThread) -> data_ready(query_kind, data)

Aufgaben (15.03-Spezifikation):
1. Datenfluss: UI-Pages fordern Daten ueber `request_*()` an; der ViewModel
   puffert die aktuellen Parameter, debounced (QTimer, 200-300 ms) und
   startet bei Bedarf einen Async-Worker. Parameternaenderungen (Slider
   usw.) feuern die betroffenen Abfragen automatisch nach.
2. Profil-Verwaltung (Option B – Explicit Save): Aktives Profil via
   `AnalyticsProfileRepository`; Parametertrends setzen das Dirty-Flag
   (`*` im Titel/Combo); gespeichert wird erst auf `save_profile()`.
3. Max-Lookback-Cap: `MAX_LOOKBACK_LIMIT = 50_000` (hart, 15.03-Spez).
4. EventBus: Profilwechsel wird auf `event_bus.profile_changed(str)`
   emittiert (Invariante 5 / zentraler EventBus, Payload = Profil-Name).
"""

from typing import Any, Dict, Iterable, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from analytics.engine.analytics_repository import AnalyticsRepository
from analytics.engine.analytics_worker import (
    QUERY_TABLE,
    QUERY_HEATMAP,
    QUERY_SCATTER,
    QUERY_DISTRIBUTION,
    QUERY_FEATURES,
    MAX_LOOKBACK_LIMIT,
    AnalyticsAsyncWorker,
)
from analytics_profile_repository import (
    AnalyticsProfileRepository,
    get_analytics_profile_repository,
    SCHEMA_VERSION_DEFAULT,
)
from config.event_bus import event_bus

# QTimer-Debounce (15.03-Spezifikation: 200-300 ms) gegen SQL-Feuer.
DEBOUNCE_MS = 250

# Default-Parameter (Anfangs-Parametrisierung der Analytics-Ansichten).
DEFAULT_BINS = 20
DEFAULT_LIMIT = 5000


class AnalyticsViewModel(QObject):
    """MVVM-ViewModel der Analytics-Engine (kein SQL, kein UI)."""

    # Datenfluss-Signale (query_kind -> Ergebnis/Fehler)
    data_ready = Signal(str, dict)
    query_failed = Signal(str, str)
    busy_changed = Signal(bool)  # Progress-Spinner an/aus

    # Profil-Signale (Option B – Explicit Save)
    active_profile_changed = Signal(object)  # Profil-Dict oder None
    dirty_changed = Signal(bool)             # '*' im Titel/Combo
    profile_saved = Signal(str)              # profile_id
    profile_deleted = Signal(str)            # profile_id
    profiles_available = Signal(list)        # Liste der Profile

    def __init__(
        self,
        analytics_repo: Optional[AnalyticsRepository] = None,
        profile_repo: Optional[AnalyticsProfileRepository] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._repo = analytics_repo or AnalyticsRepository()
        self._profile_repo = profile_repo or get_analytics_profile_repository()

        # Aktuelle Ansichtsparameter (werden im Profil-Payload persistiert).
        self._params: Dict[str, Any] = {
            "symbol": "",
            "timeframe": "M1",
            # 15.03-E (Multi-Select): feature_ids = Liste der plugin_ids
            # (Datenquellen-Filter, `WHERE feature_id IN (...)`); leer = alle.
            "feature_ids": [],
            "heatmap_metric": "count",
            "scatter_x": "ema_diff",
            "scatter_y": "rsi_14",
            "distribution_column": "atr_normalized",
            "bins": DEFAULT_BINS,
            "limit": DEFAULT_LIMIT,
        }
        self._pending_kinds: List[str] = []
        self._worker: Optional[AnalyticsAsyncWorker] = None
        self._dirty = False
        self._active_profile: Optional[Dict[str, Any]] = None
        self._profiles: List[Dict[str, Any]] = []

        # Debounce-QTimer (200-300 ms, 15.03-Spezifikation)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._start_next_query)

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Stoppt Debounce + laufenden Worker und wartet dessen Ende ab.

        Fix 15.03 (Haenger bei TF-Wechsel): Der Worker wird gecancelt (Flag)
        und mit wait() abgewartet (Queries sind schnell, < 1 s). Ohne wait()
        wuerde der noch laufende QThread beim Zerstoeren des Fensters/
        ViewModel abgebrochen ('QThread: Destroyed while thread is still
        running') – die App haengt. self._worker wird vorher auf None gesetzt,
        damit verspaetete Signale des alten Workers vom Guard in
        _on_finished/_on_failed verworfen werden.
        """
        self._debounce.stop()
        self._pending_kinds.clear()
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.cancel()
            if worker.isRunning():
                worker.wait(5000)

    # ------------------------------------------------------------------
    # Datenfluss: UI-Pages fordern Abfragen an (MVVM)
    # ------------------------------------------------------------------
    def request_table(self) -> None:
        self._refresh((QUERY_TABLE,))

    def request_heatmap(self) -> None:
        self._refresh((QUERY_HEATMAP,))

    def request_scatter(self) -> None:
        self._refresh((QUERY_SCATTER,))

    def request_distribution(self) -> None:
        self._refresh((QUERY_DISTRIBUTION,))

    def request_features(self) -> None:
        self._refresh((QUERY_FEATURES,))

    def refresh_all(self) -> None:
        """Stoesst alle Abfragen neu an (Seiten-/Profilwechsel)."""
        self._refresh((QUERY_TABLE, QUERY_HEATMAP, QUERY_SCATTER,
                       QUERY_DISTRIBUTION, QUERY_FEATURES))

    # ------------------------------------------------------------------
    # Parameter setzen (UI-Pages) – markieren Dirty + feuern betroffen ab
    # ------------------------------------------------------------------
    def set_symbol(self, symbol: str) -> None:
        self._set_param("symbol", str(symbol or ""),
                        (QUERY_TABLE, QUERY_HEATMAP, QUERY_SCATTER,
                         QUERY_DISTRIBUTION, QUERY_FEATURES))

    def set_timeframe(self, timeframe: str) -> None:
        self._set_param("timeframe", str(timeframe or "M1"),
                        (QUERY_TABLE, QUERY_HEATMAP, QUERY_SCATTER,
                         QUERY_DISTRIBUTION, QUERY_FEATURES))

    def set_feature_id(self, feature_id: Optional[str]) -> None:
        """Kompatibilitaets-Alias (Legacy): Einzel-ID -> Multi-Liste."""
        self.set_feature_ids([feature_id] if feature_id else [])

    def set_feature_ids(self, feature_ids) -> None:
        """Setzt die Multi-Auswahl der Datenquellen (15.03-E).

        `feature_ids` sind die plugin_ids des Feature-Store (z. B.
        ["grid_lines", "proximity"]); leer = kein Filter (alle Features).
        Typen-/Duplikat-normalisiert; ohne Aenderung wird kein Refresh
        ausgeloest (idempotent, wie set_symbol/set_timeframe).
        """
        ids = self._normalize_feature_ids(feature_ids)
        if ids == self._params.get("feature_ids"):
            return
        self._params["feature_ids"] = ids
        self._mark_dirty()
        self._refresh((QUERY_TABLE, QUERY_HEATMAP, QUERY_SCATTER,
                       QUERY_DISTRIBUTION))

    @staticmethod
    def _normalize_feature_ids(value) -> List[str]:
        """Normalisiert feature_ids (Liste[str], dedupliziert, getrimmt)."""
        if not value:
            return []
        out: List[str] = []
        for v in value:
            s = str(v).strip()
            if s and s not in out:
                out.append(s)
        return out

    def set_heatmap_metric(self, metric: str) -> None:
        self._set_param("heatmap_metric", str(metric or "count"),
                        (QUERY_HEATMAP,))

    def set_scatter_columns(self, x_column: str, y_column: str) -> None:
        self._set_param("scatter_x", str(x_column or "ema_diff"),
                        (QUERY_SCATTER,))
        self._set_param("scatter_y", str(y_column or "rsi_14"),
                        (QUERY_SCATTER,))

    def set_distribution_column(self, column: str) -> None:
        self._set_param("distribution_column",
                        str(column or "atr_normalized"),
                        (QUERY_DISTRIBUTION,))

    def set_bins(self, bins: int) -> None:
        new_bins = self._clamp_bins(bins)
        if new_bins != self._params["bins"]:
            self._params["bins"] = new_bins
            self._mark_dirty()
            self._refresh((QUERY_DISTRIBUTION,))

    def set_limit(self, limit: int) -> None:
        new_limit = self._clamp_limit(limit)
        if new_limit != self._params["limit"]:
            self._params["limit"] = new_limit
            self._mark_dirty()
            self._refresh((QUERY_TABLE, QUERY_SCATTER, QUERY_DISTRIBUTION))

    def _set_param(self, key: str, value: Any, kinds: Iterable[str]) -> None:
        if self._params.get(key) == value:
            return
        self._params[key] = value
        self._mark_dirty()
        self._refresh(kinds)

    # ------------------------------------------------------------------
    # Interna: Debounce + Worker-Verwaltung
    # ------------------------------------------------------------------
    def _refresh(self, kinds: Iterable[str]) -> None:
        for kind in kinds:
            if kind not in self._pending_kinds:
                self._pending_kinds.append(kind)
        self._debounce.start()

    def _start_next_query(self) -> None:
        """Startet die naechste gepufferte Abfrage (Debounce-Timeout)."""
        if self._worker is not None and self._worker.isRunning():
            return  # laufender Worker uebernimmt; Puffer bleibt gefuellt
        while self._pending_kinds:
            kind = self._pending_kinds.pop(0)
            params = self._current_params(kind)
            if params is None:
                continue  # kein Symbol/Timeframe -> Abfrage ueberspringen
            self._launch(kind, params)
            return
        self.busy_changed.emit(False)

    def _launch(self, kind: str, params: Dict[str, Any]) -> None:
        worker = AnalyticsAsyncWorker(self._repo, kind, params, parent=self)
        self._worker = worker
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        self.busy_changed.emit(True)
        worker.start()

    def _on_finished(self, worker, kind: str, result: Dict[str, Any]) -> None:
        """Verarbeitet das Ergebnis eines Workers – NUR des aktuellen.

        Fix 15.03 (Haenger bei TF-Wechsel): Race-Condition, bei der ein
        veralteter Worker (Thread bereits beendet, finished_ok noch nicht
        zugestellt, waehrend der Debounce bereits einen neuen Worker startet)
        den self._worker-Verweis ueberschrieb und mehrere Worker parallel
        liefen. Der Guard `self._worker is worker` verwirft verspaetete
        Ergebnisse veralteter Worker; nur der zuletzt gestartete Worker darf
        weiterverarbeiten.
        """
        if self._worker is not worker:
            return
        self._worker = None
        self.data_ready.emit(kind, result)
        self._start_next_query()

    def _on_failed(self, worker, kind: str, error: str) -> None:
        """Verarbeitet einen Worker-Fehler – NUR des aktuellen (Race-Guard).

        Siehe _on_finished: Verspaetete Fehler veralteter Worker werden
        verworfen, damit der laufende/naechste Worker nicht gestoert wird.
        """
        if self._worker is not worker:
            return
        self._worker = None
        self.query_failed.emit(kind, error)
        self._start_next_query()

    def _current_params(self, kind: str) -> Optional[Dict[str, Any]]:
        """Baut die Abfrageparameter fuer einen query_kind (oder None)."""
        p = self._params
        if not p.get("symbol") or not p.get("timeframe"):
            return None
        base: Dict[str, Any] = {
            "symbol": p["symbol"],
            "timeframe": p["timeframe"],
            "feature_ids": p["feature_ids"],
        }
        if kind == QUERY_TABLE:
            base["limit"] = p["limit"]
        elif kind == QUERY_HEATMAP:
            base["metric"] = p["heatmap_metric"]
        elif kind == QUERY_SCATTER:
            base["x_column"] = p["scatter_x"]
            base["y_column"] = p["scatter_y"]
            base["limit"] = p["limit"]
        elif kind == QUERY_DISTRIBUTION:
            base["column"] = p["distribution_column"]
            base["bins"] = p["bins"]
            base["limit"] = p["limit"]
        return base

    # ------------------------------------------------------------------
    # Dirty-Flag (Option B – Explicit Save)
    # ------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        """Nur bei vorhandenem aktivem Profil (sonst nichts zu speichern)."""
        if not self._dirty and self._active_profile is not None:
            self._dirty = True
            self.dirty_changed.emit(True)

    # ------------------------------------------------------------------
    # Profil-Verwaltung (CRUD + aktives Profil)
    # ------------------------------------------------------------------
    def load_profiles(self) -> None:
        """Laedt die Profil-Liste und wendet das aktive Profil an."""
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        active = self._profile_repo.get_active_profile()
        if active is not None:
            self._apply_profile(active, mark_dirty=False)
        elif self._active_profile is not None:
            self._active_profile = None
            self._dirty = False
            self.dirty_changed.emit(False)
            self.active_profile_changed.emit(None)

    def create_profile(
        self, name: str, description: str = ""
    ) -> Optional[str]:
        """Legt ein neues Profil mit den aktuellen Parametern an.

        Das neue Profil wird sofort aktiv (genau EIN aktives Profil).
        Raises ValueError bei doppeltem Namen.
        """
        name = (name or "").strip()
        if not name:
            return None
        if self._profile_repo.get_profile_by_name(name) is not None:
            raise ValueError(f"Profil '{name}' existiert bereits.")
        profile_id = self._profile_repo.create_profile(
            name, self._current_payload(), description
        )
        self._profile_repo.set_active(profile_id)
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        self._active_profile = self._profile_repo.get_profile(profile_id)
        self._dirty = False
        self.dirty_changed.emit(False)
        self.active_profile_changed.emit(dict(self._active_profile))
        self._emit_profile_changed(self._active_profile["name"])
        return profile_id

    def save_profile(self) -> bool:
        """Persistiert die aktuellen Parameter im aktiven Profil (Save).

        Returns:
            True, wenn ein aktives Profil existierte und gespeichert wurde.
        """
        if self._active_profile is None:
            return False
        profile_id = self._active_profile["profile_id"]
        ok = self._profile_repo.update_profile(
            profile_id, payload=self._current_payload()
        )
        if ok:
            self._active_profile = self._profile_repo.get_profile(profile_id)
            self._dirty = False
            self.dirty_changed.emit(False)
            self.profile_saved.emit(profile_id)
            self._emit_profile_changed(self._active_profile["name"])
        return ok

    def update_profile(
        self,
        profile_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Aktualisiert Name/Beschreibung eines Profils (additiv)."""
        ok = self._profile_repo.update_profile(
            profile_id, name=name, description=description
        )
        if ok:
            self._profiles = self._profile_repo.list_profiles()
            self.profiles_available.emit([dict(p) for p in self._profiles])
            if (self._active_profile is not None
                    and self._active_profile["profile_id"] == profile_id):
                self._active_profile = self._profile_repo.get_profile(profile_id)
                self.active_profile_changed.emit(dict(self._active_profile))
                self._emit_profile_changed(self._active_profile["name"])
        return ok

    def delete_profile(self, profile_id: str) -> bool:
        """Loescht ein Profil (hart). Aktives Profil wird zurueckgesetzt."""
        ok = self._profile_repo.delete_profile(profile_id)
        if not ok:
            return False
        was_active = (self._active_profile is not None
                      and self._active_profile["profile_id"] == profile_id)
        if was_active:
            self._active_profile = None
            self._dirty = False
            self.dirty_changed.emit(False)
            self.active_profile_changed.emit(None)
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        self.profile_deleted.emit(profile_id)
        return True

    def set_active_profile(self, profile_id: str) -> bool:
        """Setzt ein Profil als aktiv und wendet dessen Parameter an."""
        profile = self._profile_repo.get_profile(profile_id)
        if profile is None:
            return False
        self._profile_repo.set_active(profile_id)
        self._apply_profile(profile, mark_dirty=False)
        self.active_profile_changed.emit(dict(profile))
        self._emit_profile_changed(profile["name"])
        return True

    def _apply_profile(
        self, profile: Dict[str, Any], mark_dirty: bool = True
    ) -> None:
        """Uebernimmt die Profil-Parameter in die Ansicht (Explicit Save)."""
        self._active_profile = dict(profile)
        payload = profile.get("payload") or {}
        for key in list(self._params.keys()):
            if key in payload and payload[key] is not None:
                self._params[key] = payload[key]
        # 15.03-E (Profil-Migration): Alt-Payloads speicherten den Filter als
        # Einzelwert `feature_id` (String) – in `feature_ids` (Liste) wandeln.
        if "feature_ids" not in payload and payload.get("feature_id"):
            self._params["feature_ids"] = self._normalize_feature_ids(
                [payload["feature_id"]])
        self._params["feature_ids"] = self._normalize_feature_ids(
            self._params.get("feature_ids"))
        self._params["bins"] = self._clamp_bins(self._params.get("bins"))
        self._params["limit"] = self._clamp_limit(self._params.get("limit"))
        if not mark_dirty:
            self._dirty = False
            self.dirty_changed.emit(False)
        self.refresh_all()

    def _current_payload(self) -> Dict[str, Any]:
        """Profil-Payload aus den aktuellen Ansichtsparametern."""
        payload = dict(self._params)
        payload["schema_version"] = SCHEMA_VERSION_DEFAULT
        return payload

    @staticmethod
    def _emit_profile_changed(name: str) -> None:
        """Emittiert profile_changed auf dem zentralen EventBus."""
        event_bus.profile_changed.emit(name or "")

    # ------------------------------------------------------------------
    # Jump-to-Chart-Resolution (15.03 Schritt 5, Variante 2)
    # ------------------------------------------------------------------
    def resolve_latest_bar_time(
        self, symbol: str, timeframe: str
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch fuer 'Jump-to-Chart' (oder None).

        Schnelle Punktabfrage (PK-Index) fuer Klick-auf-Punkt aus dem
        Scatter – delegiert lesend an das AnalyticsRepository (kein SQL
        im ViewModel).
        """
        return self._repo.get_latest_bar_time(
            symbol, timeframe,
            feature_ids=self._params.get("feature_ids"),
        )

    def resolve_recent_bar_time_for_cell(
        self, symbol: str, timeframe: str, dow: int, hour: int
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch einer (dow, hour)-Zelle (oder None).

        Jump-to-Chart aus der Heatmap (Doppelklick auf eine Zelle) –
        delegiert lesend an das AnalyticsRepository.
        """
        return self._repo.get_recent_bar_time_for_cell(
            symbol, timeframe, dow, hour,
            feature_ids=self._params.get("feature_ids"),
        )

    # ------------------------------------------------------------------
    # Clamping (Typ- & Werte-Sicherheit)
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp_bins(value: Any) -> int:
        try:
            return max(2, int(value))
        except (TypeError, ValueError):
            return DEFAULT_BINS

    @staticmethod
    def _clamp_limit(value: Any) -> int:
        if value is None:
            return DEFAULT_LIMIT
        try:
            return max(1, min(int(value), MAX_LOOKBACK_LIMIT))
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    # ------------------------------------------------------------------
    # Lesende Zugriffe fuer UI-Pages
    # ------------------------------------------------------------------
    @property
    def params(self) -> Dict[str, Any]:
        """Kopie der aktuellen Ansichtsparameter (fuer UI-Kontrolle)."""
        return dict(self._params)

    @property
    def active_profile(self) -> Optional[Dict[str, Any]]:
        """Kopie des aktiven Profils (oder None)."""
        return dict(self._active_profile) if self._active_profile else None

    @property
    def profiles(self) -> List[Dict[str, Any]]:
        """Kopie der Profil-Liste (deterministisch nach Name sortiert)."""
        return [dict(p) for p in self._profiles]

    @property
    def is_dirty(self) -> bool:
        """True, wenn ungespeicherte Parametertrends vorliegen ('*')."""
        return self._dirty

    @property
    def heatmap_metrics(self) -> List[str]:
        """Verfuegbare Heatmap-Metriken (fuer UI-Dropdown)."""
        return self._repo.available_heatmap_metrics()

    @property
    def native_columns(self) -> List[str]:
        """Native Feature-Spalten (fuer Scatter-/Verteilungs-Dropdown)."""
        return self._repo.native_columns

    @property
    def max_lookback_limit(self) -> int:
        """Max-Lookback-Cap (UI-Slider-Maximum)."""
        return MAX_LOOKBACK_LIMIT

    def available_timeframes(self, symbol: str) -> List[str]:
        """Timeframes mit Feature-Store-Daten fuer ein Symbol (TF-Ausgrauung).

        Delegiert lesend an das AnalyticsRepository (kein SQL im ViewModel).
        Bei Fehlern wird eine leere Liste geliefert; die UI kann dann alle
        Timeframes aktiv lassen (Fallback).
        """
        try:
            return self._repo.available_timeframes(str(symbol or ""))
        except Exception:
            return []
