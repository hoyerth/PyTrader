# analytics/signals/machine_learning/xgboost_signal.py
"""
ML-Signal: XGBoost Inferenz
Lädt ein trainiertes XGBoost-Modell dynamisch über params['model_file']
und führt Inferenz auf dem Feature-Store aus.

Modell-Namenskonvention:
    model_xgb_<symbol>_<timeframe>_<created_YYYYMMDD>_<updated_YYYYMMDD>.json

Abhängigkeit: xgboost (pip install xgboost)
"""

from typing import Any, Dict, Optional
import pandas as pd
import numpy as np
from pathlib import Path

from analytics.engine.base_definition import SignalDefinition


class XGBoostSignal(SignalDefinition):
    """XGBoost-Modell-Inferenz als Signal."""

    @property
    def signal_id(self) -> str:
        return "xgboost_v1"

    @property
    def display_name(self) -> str:
        return "XGBoost ML Signal"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "model_file": "",           # Relativer Pfad zur .json-Datei
            "feature_columns": [],       # Liste der Feature-Spaltennamen
            "threshold": 0.5,           # Schwellwert für binäre Klassifikation
        }

    @property
    def param_descriptions(self) -> Dict[str, str]:
        return {
            "model_file": "Pfad zur XGBoost-Modelldatei (.json)",
            "feature_columns": "Liste der Feature-Spalten für die Inferenz",
            "threshold": "Schwellwert für die binäre Klassifikation",
        }

    @property
    def required_features(self) -> list:
        return self._params.get("feature_columns", []) if hasattr(self, '_params') else []

    def __init__(self):
        super().__init__()
        self._model = None
        self._params = {}

    def _load_model(self, model_path: str) -> None:
        """Lädt das XGBoost-Modell aus einer JSON-Datei."""
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"XGBoost-Modell nicht gefunden: {model_path}")

        try:
            import xgboost as xgb
            self._model = xgb.XGBClassifier()
            self._model.load_model(str(path))
            print(f"✅ XGBoost-Modell geladen: {path.name}")
        except ImportError:
            raise ImportError(
                "XGBoost ist nicht installiert. "
                "Installiere es mit: pip install xgboost"
            )

    def evaluate(self, df_features: pd.DataFrame, params: Optional[Dict[str, Any]] = None) -> pd.Series:
        p = {**self.default_params, **(params or {})}
        self._params = p
        model_file = str(p.get("model_file", ""))
        feature_cols = list(p.get("feature_columns", []))
        threshold = float(p.get("threshold", 0.5))

        if not model_file:
            raise ValueError("XGBoostSignal: 'model_file' ist nicht gesetzt")

        if not feature_cols:
            raise ValueError("XGBoostSignal: 'feature_columns' ist leer")

        # Prüfen ob alle benötigten Features vorhanden sind
        missing = [f for f in feature_cols if f not in df_features.columns]
        if missing:
            raise ValueError(f"XGBoostSignal: Fehlende Features: {missing}")

        # Modell laden (cached)
        if self._model is None:
            self._load_model(model_file)

        # Feature-Matrix erstellen
        X = df_features[feature_cols].values

        # Inferenz
        try:
            y_pred = self._model.predict_proba(X)
        except Exception as e:
            raise RuntimeError(f"XGBoost-Inferenz fehlgeschlagen: {e}")

        # Confidence = predicted probability der positiven Klasse
        if y_pred.ndim > 1 and y_pred.shape[1] > 1:
            confidence = y_pred[:, 1]
        else:
            confidence = y_pred.flatten()

        # Clipping auf [0, 1]
        confidence = np.clip(confidence, 0.0, 1.0)

        return pd.Series(confidence, index=df_features.index)
