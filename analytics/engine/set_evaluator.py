# analytics/engine/set_evaluator.py
"""
ServiceSetEvaluator – Führt Service-Sets (ServiceSetDefinition, siehe
service_models.py) in execution_order über den PluginExecutor aus.

Phase 15 (Alt-Signal-Rückbau): Der Signal-basierte SetEvaluator (ema_trend_v1 /
atr_filter_v1 / grid_proximity_v1 / alternating_arrow_v1) wurde komplett
entfernt – es gibt keine Signal-Engine mehr.
"""

from dataclasses import replace
from typing import Any, Callable, Dict, Optional, Set
import threading
import time
import traceback
import pandas as pd

from analytics.features.plugins.base_plugin import PluginContext, ServiceErrorLog
from analytics.features.feature_builder import (
    PluginExecutor,
    PluginExecutionError,
    PluginExecutionErrorInfo,
)


# ==============================================================================
# ServiceSetEvaluator (Service-Pipeline)
# ------------------------------------------------------------------------------
# Führt Service-Sets (ServiceSetDefinition, siehe service_models.py) in
# execution_order aus.
#
# Kernregeln (Roadmap Phase 13 §3.2):
#   - df.tail(lookback) je Service (exakter Zuschnitt).
#   - shared_state ist mutable, aber strikt per instance_id-Namespace isoliert:
#     context.shared_state[self.instance_id] ist les-/schreibbar; der Evaluator
#     legt zusätzlich das Ergebnis unter der instance_id ab, falls der Service
#     seinen Namespace nicht selbst beschrieben hat.
#   - Abhängigkeiten (depends_on) werden VOR der Ausführung validiert:
#     (1) statisch: alle depends_on-IDs müssen früher in execution_order stehen;
#     (2) runtime:  deren shared_state-Einträge müssen nach deren Ausführung
#                   vorhanden sein (sonst Fail-Fast).
#   - Fail-Fast: Bricht ein Service mit Exception ab, wird die Exception als
#     ServiceSetExecutionError geloggt und die restliche Pipeline übersprungen.
# ==============================================================================


class ServiceSetExecutionError(Exception):
    """Fail-Fast: Ein Service in der Service-Pipeline ist fehlgeschlagen."""


class ServiceSetEvaluator:
    """Sichere Ausführung einer Service-Pipeline mit Namespace-Isolation.

    P14-03 (Resiliente Evaluator-Schleife): execute_set_resilient() ersetzt
    das Fail-Fast-Prinzip durch Skip-Logic, Dependency-Skip, State-Fallback
    und eine RAM-Quarantäne (3 aufeinanderfolgende Fehler → für die Session
    gesperrt; Zähler-Ready nach 300 s ohne Fehler, Quarantäne bleibt bis
    reset()). Die bestehende execute_set()-Methode bleibt unverändert
    (Fail-Fast) und läuft für Bestands-Aufrufer parallel weiter.
    """

    def __init__(self, executor: Optional[PluginExecutor] = None) -> None:
        self.executor = executor or PluginExecutor()
        # P14-03: Session-Zustand (nur RAM, wird NICHT in DuckDB persistiert)
        self._failure_counters: Dict[str, int] = {}
        self._quarantined: Set[str] = set()
        self._last_failure_time: Dict[str, float] = {}
        self._recovery_seconds: float = 300.0
        self._execution_lock = threading.RLock()
        # Diagnose-Status der letzten resilienten Ausführung (instance_id ->
        # skip_reason bzw. strukturiertes Fehlerobjekt).
        self.last_skipped: Dict[str, str] = {}
        self.last_errors: Dict[str, PluginExecutionErrorInfo] = {}

    # -------------------------------------------------------------------------
    # Session-Quarantäne & Auto-Recovery (P14-03, Invariante 4 + 11)
    # -------------------------------------------------------------------------
    def reset(self) -> None:
        """Vollständiger Neustart der Pipeline (Invariante 11): Quarantäne,
        Fehlerzähler und Diagnose-Status werden geleert (Session-Scope)."""
        with self._execution_lock:
            self._failure_counters.clear()
            self._quarantined.clear()
            self._last_failure_time.clear()
            self.last_skipped.clear()
            self.last_errors.clear()

    def _is_quarantined(self, instance_id: str) -> bool:
        """True, wenn die Instanz für die Session quarantänisiert ist.

        Auto-Recovery (Invariante 11): Der Fehlerzähler wird nach
        _recovery_seconds (300 s) ohne weiteren Fehler automatisch
        zurückgesetzt – die einmalige Quarantäne selbst bleibt bis reset()
        bestehen."""
        last = self._last_failure_time.get(instance_id)
        if last is not None and time.time() - last >= self._recovery_seconds:
            self._failure_counters.pop(instance_id, None)
            self._last_failure_time.pop(instance_id, None)
        return instance_id in self._quarantined

    def _record_failure(self, instance_id: str) -> bool:
        """Zählt einen Fehler; bei 3 aufeinanderfolgenden Fehlern wird die
        Instanz quarantänisiert. Gibt True zurück, wenn Quarantäne ausgelöst."""
        now = time.time()
        self._last_failure_time[instance_id] = now
        self._failure_counters[instance_id] = self._failure_counters.get(instance_id, 0) + 1
        if self._failure_counters[instance_id] >= 3:
            self._quarantined.add(instance_id)
            return True
        return False

    def _reset_failure(self, instance_id: str) -> None:
        """Erfolgreiche Ausführung → Fehlerzähler zurücksetzen (nur
        aufeinanderfolgende Fehler zählen)."""
        self._failure_counters.pop(instance_id, None)
        self._last_failure_time.pop(instance_id, None)

    # -------------------------------------------------------------------------
    # Pipeline-Ausführung (bestehender Fail-Fast-Pfad – unverändert)
    # -------------------------------------------------------------------------
    def execute_set(
        self,
        set_definition: Dict[str, Any],
        df: pd.DataFrame,
        context: Optional[PluginContext] = None,
    ) -> Dict[str, Any]:
        """Führt alle Services nacheinander in execution_order aus.

        Args:
            set_definition: ServiceSetDefinition (set_id/display_name werden
                hier nicht benötigt – nur execution_order + services).
            df: OHLCV-DataFrame. Jeder Service bekommt exakt df.tail(lookback).
            context: Optionaler PluginContext. Wenn None, wird ein frischer
                Context mit mode='batch' erzeugt.

        Returns:
            Dict instance_id -> FeatureCalculateResult. Jedes Ergebnis ist
            zusätzlich unter context.shared_state[instance_id] abgelegt
            (Namespace-isoliert), sofern der Service seinen Namespace nicht
            selbst beschrieben hat.

        Raises:
            ValueError: Ungültige execution_order / Abhängigkeits-Verletzung
                (statisch ODER runtime: fehlender shared_state-Eintrag).
            ServiceSetExecutionError: Fail-Fast bei Service-Exception.
        """
        if df is None or df.empty:
            raise ValueError("execute_set: df ist None oder leer")

        execution_order = list(set_definition.get("execution_order") or [])
        services = dict(set_definition.get("services") or {})

        if not execution_order:
            raise ValueError("execute_set: execution_order ist leer")

        missing = [iid for iid in execution_order if iid not in services]
        if missing:
            raise ValueError(
                f"execute_set: instance_ids fehlen in 'services': {missing}")

        if context is None:
            context = PluginContext(mode="batch")

        # --- Statische Abhängigkeits-Validierung VOR der Ausführung ----------
        position = {iid: idx for idx, iid in enumerate(execution_order)}
        for iid, cfg in services.items():
            for dep in (cfg.get("depends_on") or []):
                if dep not in position:
                    raise ValueError(
                        f"execute_set: Service '{iid}' depends_on '{dep}', "
                        f"das nicht in execution_order existiert")
                if position[dep] >= position[iid]:
                    raise ValueError(
                        f"execute_set: Abhängigkeits-Verletzung – Service "
                        f"'{iid}' depends_on '{dep}', aber '{dep}' steht nicht "
                        f"VOR '{iid}' in execution_order (nachgelagerte Referenz)")

        # --- Pipeline-Ausführung (Fail-Fast) ---------------------------------
        results: Dict[str, Any] = {}
        for iid in execution_order:
            cfg = services[iid]
            plugin_id = cfg["plugin_id"]
            lookback = int(cfg.get("lookback") or len(df))
            params = dict(cfg.get("params") or {})

            # Runtime-Check: abhängige shared_state-Einträge müssen nach deren
            # Ausführung vorhanden sein (sonst Fail-Fast VOR diesem Service).
            for dep in (cfg.get("depends_on") or []):
                if dep not in context.shared_state:
                    raise ValueError(
                        f"execute_set: Service '{iid}' erwartet "
                        f"shared_state['{dep}'], aber der Eintrag fehlt "
                        f"(abhängiger Service lief nicht oder schrieb nichts)")

            # Exakter Zuschnitt auf den Service-lookback
            service_df = df.tail(lookback)

            # Context je Service: instance_id + depends_on setzen (Namespace).
            # replace() erzeugt eine flache Kopie – shared_state (dict) bleibt
            # DASSELBE Objekt, ist also über alle Services hinweg sichtbar.
            service_ctx = replace(
                context,
                instance_id=iid,
                depends_on=list(cfg.get("depends_on") or []),
            )

            try:
                result = self.executor.execute(
                    plugin_id, service_df, params, context=service_ctx)
            except Exception as e:
                raise ServiceSetExecutionError(
                    f"execute_set: Service '{iid}' (plugin '{plugin_id}') "
                    f"fehlgeschlagen – Pipeline abgebrochen: {e}") from e

            # Namespace-Isolation: Ergebnis unter der instance_id ablegen.
            # Hat der Service seinen Namespace bereits selbst beschrieben
            # (z.B. GridLinesService schreibt Linienliste), wird NICHT
            # überschrieben – die Linien bleiben für abhängige Services lesbar.
            if iid not in context.shared_state:
                context.shared_state[iid] = result
            results[iid] = result

        return results

    # -------------------------------------------------------------------------
    # P14-03: Resiliente Pipeline-Ausführung (Skip-Logic / Dependency-Skip /
    # State-Fallback / Session-Quarantäne)
    # -------------------------------------------------------------------------
    def execute_set_resilient(
        self,
        set_definition: Dict[str, Any],
        df: pd.DataFrame,
        context: Optional[PluginContext] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Führt die Service-Pipeline elastisch aus (P14-03) – Ablösung des
        strikten Fail-Fast-Prinzips (A.3/A.4 des Kapitels):

        * Skip-Logic: Schlägt ein unkritischer Service fehl, wird er geloggt
          (strukturiertes Fehlerobjekt unter self.last_errors) und mit
          skip_reason in self.last_skipped markiert. Unabhängige Services
          laufen weiter.
        * Dependency-Skip: Services, die per depends_on von der fehlerhaften
          instance_id abhängen, werden mit skip_reason="dependency_failed"
          übersprungen.
        * State-Fallback: Der shared_state-Eintrag der VORHERIGEN Kerze einer
          fehlgeschlagenen Instanz bleibt unangetastet erhalten – der Aufrufer
          kann exklusiv darüber auf den letzten guten Zustand zugreifen
          (EvaluationContext.shared_state.get(instance_id)).
        * RAM-Quarantäne: 3 aufeinanderfolgende Fehler einer Instanz →
          quarantäne (nur RAM, keine DB-Persistenz); Zähler-Ready nach 300 s
          ohne Fehler (Invariante 11), Quarantäne bleibt bis reset().

        Der Rückgabewert enthält ausschließlich erfolgreiche Ausführungen
        (Dict instance_id -> FeatureCalculateResult) – identische Struktur wie
        execute_set(). Diagnose über self.last_skipped / self.last_errors.

        Raises:
            ValueError: Ungültige execution_order / statische
                Abhängigkeits-Verletzung (wie execute_set).
        """
        if df is None or df.empty:
            raise ValueError("execute_set_resilient: df ist None oder leer")

        execution_order = list(set_definition.get("execution_order") or [])
        services = dict(set_definition.get("services") or {})

        if not execution_order:
            raise ValueError("execute_set_resilient: execution_order ist leer")

        missing = [iid for iid in execution_order if iid not in services]
        if missing:
            raise ValueError(
                f"execute_set_resilient: instance_ids fehlen in 'services': {missing}")

        if context is None:
            context = PluginContext(mode="batch")

        # --- Statische Abhängigkeits-Validierung VOR der Ausführung ----------
        position = {iid: idx for idx, iid in enumerate(execution_order)}
        for iid, cfg in services.items():
            for dep in (cfg.get("depends_on") or []):
                if dep not in position:
                    raise ValueError(
                        f"execute_set_resilient: Service '{iid}' depends_on "
                        f"'{dep}', das nicht in execution_order existiert")
                if position[dep] >= position[iid]:
                    raise ValueError(
                        f"execute_set_resilient: Abhängigkeits-Verletzung – "
                        f"Service '{iid}' depends_on '{dep}', aber '{dep}' "
                        f"steht nicht VOR '{iid}' in execution_order")

        # --- Resiliente Pipeline-Ausführung (Skip-Logic) ---------------------
        results: Dict[str, Any] = {}
        with self._execution_lock:
            self.last_skipped.clear()
            self.last_errors.clear()
            for idx, iid in enumerate(execution_order):
                # Quarantäne-Skip (Session-Scope, RAM only)
                if self._is_quarantined(iid):
                    self.last_skipped[iid] = "quarantined"
                    print(f"WARN [ServiceSetEvaluator] Service '{iid}' "
                          f"uebersprungen (quarantined)")
                    if progress_callback:
                        progress_callback(iid, idx + 1, len(execution_order))
                    continue

                cfg = services[iid]
                plugin_id = cfg["plugin_id"]
                lookback = int(cfg.get("lookback") or len(df))
                params = dict(cfg.get("params") or {})

                # Dependency-Skip: abhängige Instanz fehlgeschlagen oder
                # quarantänisiert → kontrolliert überspringen.
                dep_failed = False
                for dep in (cfg.get("depends_on") or []):
                    if dep in self.last_skipped or dep in self._quarantined:
                        self.last_skipped[iid] = "dependency_failed"
                        print(f"WARN [ServiceSetEvaluator] Service '{iid}' "
                              f"uebersprungen (dependency_failed: '{dep}')")
                        dep_failed = True
                        break
                if dep_failed:
                    if progress_callback:
                        progress_callback(iid, idx + 1, len(execution_order))
                    continue

                # Exakter Zuschnitt auf den Service-lookback
                service_df = df.tail(lookback)

                # Context je Service: instance_id + depends_on setzen (Namespace).
                service_ctx = replace(
                    context,
                    instance_id=iid,
                    depends_on=list(cfg.get("depends_on") or []),
                )

                try:
                    result = self.executor.execute(
                        plugin_id, service_df, params, context=service_ctx)
                except PluginExecutionError as e:
                    self.last_errors[iid] = e.info
                    quarantined_now = self._record_failure(iid)
                    self.last_skipped[iid] = "quarantined" if quarantined_now else "error"
                    # P14-03 (Schritt 2.2): Logging über das strukturierte
                    # ServiceErrorLog-TypedDict (maschinelle Auswertung).
                    log: ServiceErrorLog = e.info.to_service_error_log()
                    print(
                        f"WARN [ServiceSetEvaluator] Service '{iid}' "
                        f"(plugin '{log['plugin_id']}') fehlgeschlagen: "
                        f"{log['exception']} "
                        f"(Fehler #{self._failure_counters.get(iid, 0)})"
                    )
                    if quarantined_now:
                        print(f"WARN [ServiceSetEvaluator] Service '{iid}' fuer "
                              f"die Session quarantaenisiert (RAM only)")
                    # State-Fallback: alter shared_state-Eintrag (vorherige
                    # Kerze) bleibt unangetastet erhalten.
                    if progress_callback:
                        progress_callback(iid, idx + 1, len(execution_order))
                    continue
                except Exception as e:
                    # Sicherheitsnetz: PluginExecutor kapselt eigentlich alle
                    # Fehler – hier trotzdem defensiv absichern.
                    info = PluginExecutionErrorInfo(
                        timestamp=time.time(),
                        plugin_id=plugin_id,
                        instance_id=iid,
                        symbol=str(getattr(context, "symbol", "") or ""),
                        timeframe=str(getattr(context, "timeframe", "") or ""),
                        bar_time=getattr(context, "timestamp", None),
                        stage="execute_set_resilient",
                        exception_type=type(e).__name__,
                        exception_message=str(e),
                        traceback=traceback.format_exc(),
                    )
                    self.last_errors[iid] = info
                    quarantined_now = self._record_failure(iid)
                    self.last_skipped[iid] = "quarantined" if quarantined_now else "error"
                    log2: ServiceErrorLog = info.to_service_error_log()
                    print(f"WARN [ServiceSetEvaluator] Service '{iid}' "
                          f"(plugin '{log2['plugin_id']}') fehlgeschlagen: "
                          f"{log2['exception']}")
                    if progress_callback:
                        progress_callback(iid, idx + 1, len(execution_order))
                    continue

                # Erfolg → Fehlerzähler zurücksetzen, Diagnose-Status bereinigen.
                self._reset_failure(iid)
                self.last_skipped.pop(iid, None)
                self.last_errors.pop(iid, None)

                # Namespace-Isolation (wie execute_set): Ergebnis ablegen, falls
                # der Service seinen Namespace nicht selbst beschrieben hat.
                if iid not in context.shared_state:
                    context.shared_state[iid] = result
                results[iid] = result
                if progress_callback:
                    progress_callback(iid, idx + 1, len(execution_order))

        return results
