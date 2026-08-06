# chart/indicators/multi_ma.py
"""
Phase 16.05 – Multi-MA-Indikator (8x Moving Averages)
======================================================

Selbst-contained Indikator (BaseIndicator) für den Chart: zeichnet bis zu
8 Moving Averages als LWC-v5-LineSeries über die GENERISCHE Render-Pipeline
(Prework, 16.05) – KEIN Indikator-spezifischer JS-/chart_win-Branch mehr.

  * Nutzt die `MATemplateEngine` aus Phase 16.04
    (chart/indicators/utils/ma_template.py) für die Berechnung (12 MA-Typen,
    vektorisiert), Farb-Serien (dual_color-Semantik) und den LWC-v5-Payload.
  * `calculate()` liefert den generischen Render-Payload
    `{"lines": [{"id": "ma1".."ma8", "data": [{time, value, color}],
                 "width", "style", "title"}, ...]}` (Entscheidung D6,
    P-C5: `lines` statt `maLines` – der `lines`-Key ist ausschließlich für
    Zeitreihen-LineSeries reserviert, F1-Beschluss).
  * Das Parameter-Schema (56+ Parameter: 8 MAs × 7 Keys) wird PROGRAMMATISCH
    in einer Schleife `for x in range(1, 9)` erzeugt (Ergänzung C3), nicht
    manuell ausgeschrieben. `maX_smooth_type` ist Schema-Vertrag
    (Forward-Compatibility, Entscheidung D5) und wird von der Engine nicht
    konsumiert – die Berechnung läuft über `maX_type`.
  * Defaults (Entscheidung D7): MA1 `EHMA/4/alpha 2.0/dual_color=False`,
    MA2..8 `EMA/10*X/alpha 2.0`, alle `show=False` außer MA1.
  * Kontrastfarben (Entscheidung D4): MA1 teal #26A69A (Führungslinie),
    MA2 #2962FF, MA3 #FF6D00, MA4 #AB47BC, MA5 #FDD835, MA6 #FF5252,
    MA7 #00E5FF, MA8 #B0BEC5.
  * VWMA (P-D4/F3): nutzt `df["tick_volume"]` aus `fetch_historical_candles`
    (None/NaN -> 0 normalisiert). Fehlt die Spalte oder ist das Volumen
    Null, greift der Engine-interne E5-Fallback (SMA).

Keine Analytics-/Feature-Store-Schreibzugriffe (reine Darstellung, P16.01).
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from .base_indicator import BaseIndicator
from .utils.ma_template import MATemplateEngine, MA_TYPES, resolve_bull_color

# ---------------------------------------------------------------------------
# Konstanten & Defaults (Entscheidungen D4/D7)
# ---------------------------------------------------------------------------
_INDICATOR_ID: str = "ind_moving_averages"
_DISPLAY_NAME: str = "Multi Moving Average (8x)"

# Kontrastfarben MA1..MA8 (D4) – MA1 teal bleibt Führungslinie.
_MA_COLORS: Dict[int, str] = {
    1: "#26A69A",   # teal (Führung)
    2: "#2962FF",   # Blau
    3: "#FF6D00",   # Orange
    4: "#AB47BC",   # Violett
    5: "#FDD835",   # Gelb
    6: "#FF5252",   # Rot
    7: "#00E5FF",   # Cyan
    8: "#B0BEC5",   # Blaugrau
}
_MA1_BEAR_COLOR: str = "#EF5350"

# Strichstärke: MA1 (Führungslinie) kräftiger, MA2..8 dünner.
_MA1_WIDTH: int = 2
_MA_WIDTH: int = 1
_LINE_STYLE: str = "solid"


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if value is None:
        return default
    return bool(value)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class MultiMovingAverageIndicator(BaseIndicator):
    """Multi-MA-Indikator (8 MAs) – generische `lines`-LineSeries via
    MATemplateEngine (Phase 16.04)."""

    def __init__(self) -> None:
        super().__init__()
        self._symbol: Optional[str] = None
        self._timeframe: Optional[str] = None
        self._settings: Any = None
        self._plugin_id: str = _INDICATOR_ID

    # ------------------------------------------------------------- Identität
    @property
    def indicator_id(self) -> str:
        return _INDICATOR_ID

    @property
    def display_name(self) -> str:
        return _DISPLAY_NAME

    @property
    def plugin_id(self) -> str:
        """Selbst-contained Plugin-Schnittstelle (Branch 1 in
        indicator_dialog._get_plugin: parameter_schema + plugin_id)."""
        return _INDICATOR_ID

    @property
    def service_plugin_ids(self) -> List[str]:
        """Keine Services – reiner Darstellungs-Indikator."""
        return []

    # ----------------------------------------------------- Parameter-Schema
    @staticmethod
    def _build_schema() -> Dict[str, Dict[str, Any]]:
        """Programmatische Schema-Erzeugung (Ergänzung C3): 8 MAs × 7 Keys.

        MA1 (Führung, mit DualColor): show_ma1, ma1_type, ma1_period,
        ma1_smooth_type, ma1_alpha, ma1_dual_color, ma1_bull_color,
        ma1_bear_color.
        MA2..8 (Standard): show_maX, maX_type, maX_period, maX_smooth_type,
        maX_alpha, maX_color (kein dual_color/bear_color).
        """
        schema: Dict[str, Dict[str, Any]] = {}
        for x in range(1, 9):
            prefix = f"ma{x}"
            schema[f"show_{prefix}"] = {
                "type": "bool",
                "default": (x == 1),  # D7: nur MA1 sichtbar
                "description": f"MA {x} anzeigen",
            }
            schema[f"{prefix}_type"] = {
                "type": "choice",
                "options": list(MA_TYPES),
                "default": ("EHMA" if x == 1 else "EMA"),  # D7
                "description": f"MA {x} Typ",
            }
            schema[f"{prefix}_period"] = {
                "type": "int",
                "default": (4 if x == 1 else 10 * x),  # D7
                "min": 1,
                "max": 500,
                "step": 1,
                "description": f"MA {x} Periode",
            }
            schema[f"{prefix}_smooth_type"] = {
                "type": "choice",
                "options": list(MA_TYPES),
                "default": ("EHMA" if x == 1 else "EMA"),  # D5 (nicht konsumiert)
                "description": f"MA {x} Smoothing (Forward-Compatibility)",
            }
            schema[f"{prefix}_alpha"] = {
                "type": "float",
                "default": 2.0,
                "min": 0.1,
                "max": 10.0,
                "step": 0.1,
                "description": f"MA {x} Decay-Faktor (Alpha-MAs)",
            }
            if x == 1:
                # MA1: NUR DualColor-Schalter + bull/bear (Spezial-Führung).
                schema["ma1_dual_color"] = {
                    "type": "bool",
                    "default": False,  # D7
                    "description": "MA 1 Auf/Ab-Färbung",
                }
                schema["ma1_bull_color"] = {
                    "type": "color",
                    "default": _MA_COLORS[1],
                    "description": "MA 1 Farbe steigend",
                    "style_type": "line",
                }
                schema["ma1_bear_color"] = {
                    "type": "color",
                    "default": _MA1_BEAR_COLOR,
                    "description": "MA 1 Farbe fallend (dual_color)",
                    "style_type": "line",
                }
            else:
                # MA2..8: einfarbig (kein dual_color/bear_color).
                schema[f"{prefix}_color"] = {
                    "type": "color",
                    "default": _MA_COLORS[x],
                    "description": f"MA {x} Farbe",
                    "style_type": "line",
                }
        return schema

    @property
    def parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self._build_schema().items()}

    @property
    def parameter_order(self) -> List[str]:
        """Darstellungs-Reihenfolge: MA1-Gruppe, dann MA2..8."""
        order: List[str] = []
        for x in range(1, 9):
            order.append(f"show_ma{x}")
            order.append(f"ma{x}_type")
            order.append(f"ma{x}_period")
            order.append(f"ma{x}_smooth_type")
            order.append(f"ma{x}_alpha")
            if x == 1:
                order.extend(["ma1_dual_color", "ma1_bull_color", "ma1_bear_color"])
            else:
                order.append(f"ma{x}_color")
        return order

    @property
    def base_parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        """Kein lookback nötig – reiner Darstellungs-Indikator über alle
        Candles des Charts (keine Service-Pipeline)."""
        return {}

    def full_parameter_schema(self) -> Dict[str, Dict[str, Any]]:
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            k: v["default"]
            for k, v in self.full_parameter_schema().items()
            if "default" in v
        }

    @property
    def param_options(self) -> Dict[str, List[Any]]:
        return {}

    @property
    def param_labels(self) -> Dict[str, str]:
        labels: Dict[str, str] = {}
        for x in range(1, 9):
            labels[f"show_ma{x}"] = f"MA {x} anzeigen"
            labels[f"ma{x}_type"] = f"MA {x} Typ"
            labels[f"ma{x}_period"] = f"MA {x} Periode"
            labels[f"ma{x}_smooth_type"] = f"MA {x} Smoothing"
            labels[f"ma{x}_alpha"] = f"MA {x} Decay-Faktor"
            if x == 1:
                labels["ma1_dual_color"] = "MA 1 Auf/Ab-Färbung"
                labels["ma1_bull_color"] = "MA 1 Farbe steigend"
                labels["ma1_bear_color"] = "MA 1 Farbe fallend"
            else:
                labels[f"ma{x}_color"] = f"MA {x} Farbe"
        return labels

    @property
    def param_layout(self) -> Optional[List[Any]]:
        """Gruppen: 'MA 1 (Führung)' + 'MA 2'..'MA 8' (Ergänzung C3)."""
        layout: List[Any] = []
        for x in range(1, 9):
            keys = [
                f"show_ma{x}", f"ma{x}_type", f"ma{x}_period",
                f"ma{x}_smooth_type", f"ma{x}_alpha",
            ]
            if x == 1:
                keys.extend(["ma1_dual_color", "ma1_bull_color", "ma1_bear_color"])
                title = "MA 1 (Führung)"
            else:
                keys.append(f"ma{x}_color")
                title = f"MA {x}"
            layout.append((title, keys))
        return layout

    # ------------------------------------------------------------- Kontext
    def set_context(self, symbol: str, timeframe: str) -> None:
        self._symbol = symbol
        self._timeframe = timeframe

    def set_settings(self, settings: Any) -> None:
        """Injiziert AppSettings (Kopie) – sonst lazy aus dem StateManager."""
        self._settings = settings

    def _get_app_settings(self) -> Any:
        if self._settings is not None:
            return self._settings
        try:
            from state_manager import StateManager
            return StateManager().get_app_settings()
        except Exception:
            return None

    def _get_candle_limit(self) -> int:
        """chart_candle_limit aus den AppSettings (Default 3000)."""
        try:
            settings = self._get_app_settings()
            limit = int(getattr(settings, "chart_candle_limit", 3000))
            return max(limit, 1)
        except Exception:
            return 3000

    # ------------------------------------------------------------ Berechnung
    def build_chart_render_payload(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
    ) -> Dict[str, List[Any]]:
        """Baut den generischen Render-Payload (alle aktiven MAs).

        Args:
            df: OHLCV-DataFrame mit Spalten time/open/high/low/close (und
                optional tick_volume für VWMA, P-D4/F3) – reale
                Wanduhr-Epochs. Wird auf AppSettings.chart_candle_limit
                zugeschnitten (crop_dataframe).
            params: Indikator-Parameter (show_maX / maX_type / maX_period /
                maX_smooth_type (D5, nicht konsumiert) / maX_alpha /
                ma1_dual_color / ma1_bull_color / ma1_bear_color /
                maX_color).

        Returns:
            {"lines": [{id, data, width, style, title}, ...]} – data ist
            direkt LWC-v5-setData-Input ([{time, value, color}] mit
            Pro-Punkt-color für dual_color-MA1, P16.04 build_chart_payload).
            Zeiten sind reale Wanduhr-Epochs; das Mapping real→kontinuierlich
            übernimmt chart_win._collect_render_payload generisch
            (Ergänzung C1).
        """
        lines: List[Dict[str, Any]] = []
        if df is None or df.empty:
            return {"lines": lines}

        # Daten-Zuschnitt (Ergänzung C3 / Spezifikation Punkt 2.1).
        df_crop = MATemplateEngine.crop_dataframe(df, self._get_candle_limit())
        if df_crop is None or df_crop.empty:
            return {"lines": lines}
        if "close" not in df_crop.columns:
            return {"lines": lines}

        close: pd.Series = df_crop["close"]
        volume: Optional[pd.Series] = None
        if "tick_volume" in df_crop.columns:
            volume = df_crop["tick_volume"]

        for x in range(1, 9):
            prefix = f"ma{x}"
            if not _as_bool(params.get(f"show_{prefix}"), x == 1):
                continue
            ma_type = str(params.get(f"{prefix}_type") or ("EHMA" if x == 1 else "EMA"))
            period = _as_int(params.get(f"{prefix}_period"), 4 if x == 1 else 10 * x)
            alpha = _as_float(params.get(f"{prefix}_alpha"), 2.0)

            ma_series = MATemplateEngine.calculate_ma(
                close, ma_type, period, alpha_factor=alpha, volume=volume
            )

            if x == 1:
                # MA1: dual_color-Semantik (E6) – bull/bear aus den Params.
                dual_color = _as_bool(params.get("ma1_dual_color"), False)
                bull_color = resolve_bull_color(
                    dual_color, params.get("ma1_bull_color"),
                    default=_MA_COLORS[1],
                )
                bear_color = str(params.get("ma1_bear_color") or _MA1_BEAR_COLOR)
                colors = MATemplateEngine.build_color_series(
                    ma_series, dual_color, bull_color, bear_color
                )
                width = _MA1_WIDTH
                title = f"MA1 {str(ma_type).upper()} {period}"
            else:
                # MA2..8: einfarbige Farbliste (maX_color).
                color = str(params.get(f"{prefix}_color") or _MA_COLORS[x])
                n = len(ma_series)
                colors = [color] * n
                width = _MA_WIDTH
                title = f"MA{x} {str(ma_type).upper()} {period}"

            data = MATemplateEngine.build_chart_payload(
                df_crop["time"], ma_series, colors
            )
            lines.append({
                "id": prefix,
                "data": data,
                "width": width,
                "style": _LINE_STYLE,
                "title": title,
            })
        return {"lines": lines}

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
        """Berechnet alle aktiven MAs und liefert den generischen
        Render-Payload {"lines": [...]} (D6/P-C5)."""
        if df is None or df.empty:
            return {"lines": []}
        return self.build_chart_render_payload(df, params)
