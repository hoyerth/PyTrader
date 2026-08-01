# analytics/engine/set_evaluator.py
"""
Set-Evaluator – Kombiniert mehrere Signale zu einem gewichteten Gesamt-Score.
Unterstützt gewichtete Summen mit Schwellenwert (Threshold).

Phase 13 Schritt 3: Zusätzlich enthält dieses Modul den NEUEN
ServiceSetEvaluator (Service-Pipeline). Der bestehende SetEvaluator
(Signal-Sets) bleibt UNVERÄNDERT und läuft parallel weiter.
"""

from dataclasses import replace
from typing import Any, Dict, Optional
import pandas as pd
import json

from analytics.engine.base_definition import SignalDefinition
from analytics.features.plugins.base_plugin import PluginContext
from analytics.features.feature_builder import PluginExecutor


class SetEvaluator:
    """
    Wertet Signal-Sets aus: Kombiniert Einzelsignale mit Gewichtung
    zu einem Gesamt-Confidence-Score pro Bar.
    """

    def __init__(self, signals: Dict[str, SignalDefinition]) -> None:
        """
        Args:
            signals: Dict aller verfügbarer Signale {signal_id: SignalDefinition}
        """
        self.signals = signals

    def evaluate_set(
        self,
        set_config: Dict[str, Any],
        df_features: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Wertet ein komplettes Signal-Set aus.

        Args:
            set_config: JSON-konforme Konfiguration {
                "signals": [{"id": "ema_trend_v1", "weight": 0.6, "params": {...}}, ...],
                "threshold": 0.5
            }
            df_features: DataFrame mit Feature-Spalten

        Returns:
            DataFrame mit Spalten: bar_time, confidence_total, sowie Einzel-Confidences
        """
        signal_configs = set_config.get("signals", [])
        threshold = float(set_config.get("threshold", 0.5))

        if not signal_configs:
            raise ValueError("Set-Konfiguration enthält keine Signale")

        result = df_features[["bar_time"]].copy()
        total_weight = 0.0
        weighted_sum = pd.Series(0.0, index=df_features.index)

        for cfg in signal_configs:
            signal_id = cfg["id"]
            weight = float(cfg.get("weight", 1.0))
            params = cfg.get("params", {})

            if signal_id not in self.signals:
                print(f"⚠️ [SetEvaluator] Unbekanntes Signal: {signal_id}")
                continue

            signal = self.signals[signal_id]

            # Prüfen ob benötigte Features vorhanden sind
            missing = [f for f in signal.required_features if f not in df_features.columns]
            if missing:
                print(f"⚠️ [SetEvaluator] Fehlende Features für {signal_id}: {missing}")
                continue

            confidence = signal.evaluate(df_features, params)
            result[f"conf_{signal_id}"] = confidence.values

            weighted_sum += confidence * weight
            total_weight += weight

        # Gewichteter Gesamt-Score
        if total_weight > 0:
            result["confidence_total"] = (weighted_sum / total_weight).values
        else:
            result["confidence_total"] = 0.0

        # Binäres Signal (Threshold-Überschreitung)
        result["signal_binary"] = (result["confidence_total"] >= threshold).astype(int)

        return result

    def evaluate_set_from_db(
        self,
        set_id: str,
        set_configs: Dict[str, Dict[str, Any]],
        df_features: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Lädt eine Set-Konfiguration anhand der set_id und wertet sie aus.

        Args:
            set_id: ID des Signal-Sets
            set_configs: Dict aller verfügbarer Set-Konfigurationen
            df_features: DataFrame mit Feature-Spalten

        Returns:
            DataFrame mit Ergebnissen
        """
        if set_id not in set_configs:
            raise ValueError(f"Set-ID '{set_id}' nicht gefunden")

        config = set_configs[set_id]
        if isinstance(config.get("configuration"), str):
            config["configuration"] = json.loads(config["configuration"])

        return self.evaluate_set(config["configuration"], df_features)


# ==============================================================================
# Phase 13 Schritt 3: ServiceSetEvaluator (Service-Pipeline)
# ------------------------------------------------------------------------------
# Führt Service-Sets (ServiceSetDefinition, siehe service_models.py) in
# execution_order aus. Der bestehende SetEvaluator (oben, Signal-Sets) bleibt
# UNVERÄNDERT und läuft parallel weiter.
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
    """Sichere Ausführung einer Service-Pipeline mit Namespace-Isolation."""

    def __init__(self, executor: Optional[PluginExecutor] = None) -> None:
        self.executor = executor or PluginExecutor()

    # -------------------------------------------------------------------------
    # Pipeline-Ausführung
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
