# chart/widgets/mtf_filter_bar.py
"""
MTF-FC v4 (Kapitel 21.03.07) – MtfFilterBarWidget & Control-Panel.

Filterleiste mit Source-Data-TF, Chart-Overlay-TF, Range-Picker,
View-Templates (über SchemaMigrator), Tabellen-Sortierung und
Session-Filter (§4 Säule 1).

MVVM (Grundsatz 4): KEINE SQL-Queries, KEINE DB-Connects in der UI.
Der Zustand wird ausschliesslich über den `MtfFcProvider` im isolierten
Namespace `shared_state["mtf_fc"]` gelesen/geschrieben. Die Kommunikation
mit Orchestratoren läuft über Signale (keine direkten Fenster-Referenzen,
Grundsatz 2/5).

Das Widget ist bewusst zustandsarm: Es rendert die Steuerungselemente und
emittiert Signale; die eigentliche Verarbeitung (Boundary, Kaskade, Guards)
liegt in den Engine-Modulen (21.03.02-21.03.05).
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from analytics.engine.mtf_fc_confluence import WEIGHTS
from analytics.engine.mtf_fc_provider import MtfFcProvider
from analytics.engine.mtf_fc_templates import (
    MtfFcTemplateStore,
    TemplateError,
    create_template,
    migrate_template,
)

#: Data-TF-Auswahl (Multi + fixierte Timeframes).
DATA_TF_OPTIONS = ["🌐 Alle Timeframes (Multi)", "🔒 M1", "🔒 M5", "🔒 M15", "🔒 H1", "🔒 H4"]

#: Chart-Overlay-TF (Auto-Kaskade vs. manuell fix).
CHART_TF_OPTIONS = ["⚡ Auto (Kaskade)", "🔒 Manuell Fix"]

#: Range-Presets.
RANGE_PRESETS = ["24h", "7d", "30d", "YTD", "Benutzerdefiniert"]

#: Tabellen-Sortierung.
SORT_MODES = ["Datum 🠇", "Signal-Stärke 🠇", "TF 🠅"]

#: Session-Filter (Farbbalken im M1/M5-Zoom, 21.03.08).
SESSION_OPTIONS = ["London", "New York", "Tokio"]

_STRIP_PREFIX = ("🌐 ", "🔒 ", "⚡ ", "🠇", "🠅", " (Multi)", " (Kaskade)", " Manuell Fix", "Benutzerdefiniert")


def _parse_data_tf(text: str) -> str:
    """Konvertiert ein Data-TF-Dropdown-Label in den Wert ('multi' | 'M15')."""
    for prefix in ("🌐 ", "🔒 "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    stripped = text.strip()
    if not stripped or stripped.startswith("Alle Timeframes"):
        return "multi"
    return stripped


def _parse_chart_tf(text: str) -> str:
    """Konvertiert ein Chart-TF-Dropdown-Label in 'auto' oder fixierten TF."""
    if text.startswith("⚡"):
        return "auto"
    return "fix"


class MtfFilterBarWidget(QWidget):
    """Filterleiste des MTF-FC-Systems (QWidget, reines Event-Handling).

    Signale (Entkopplung über den Aufrufer, kein Fenster-Know-how):
      * `data_tf_changed(str)`     – 'multi' oder fixierter TF (z. B. 'M15').
      * `chart_tf_changed(str)`    – 'auto' (Kaskade) oder 'fix'.
      * `range_changed(str, int, int)` – Preset-Name, from_ts, to_ts.
      * `sort_mode_changed(str)`   – 'date' | 'signal' | 'tf'.
      * `sessions_changed(list)`   – aktive Sessions (z. B. ['london']).
      * `template_applied(dict)`   – geladenes View-Template.
      * `guard_override_requested(str, str)` – target_tf, reason (21.03.05).
    """

    data_tf_changed = Signal(str)
    chart_tf_changed = Signal(str)
    range_changed = Signal(str, int, int)
    sort_mode_changed = Signal(str)
    sessions_changed = Signal(list)
    template_applied = Signal(dict)
    guard_override_requested = Signal(str, str)

    def __init__(
        self,
        provider: Optional[MtfFcProvider] = None,
        template_store: Optional[MtfFcTemplateStore] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        # Provider ist die EINZIGE Brücke zum shared_state-Namespace (MVVM).
        self._provider = provider or MtfFcProvider()
        self._store = template_store or MtfFcTemplateStore()
        self._sessions: List[str] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # --- Source-Data-TF --------------------------------------------
        layout.addWidget(QLabel("Data-TF:"))
        self._data_tf_combo = QComboBox()
        self._data_tf_combo.addItems(DATA_TF_OPTIONS)
        self._data_tf_combo.setToolTip(
            "Source-Data-TF: 🌐 alle Timeframes (Multi) vs. 🔒 fixiert auf einen TF")
        self._data_tf_combo.currentTextChanged.connect(self._on_data_tf_changed)
        layout.addWidget(self._data_tf_combo)

        # --- Chart-Overlay-TF ------------------------------------------
        layout.addWidget(QLabel("Chart-TF:"))
        self._chart_tf_combo = QComboBox()
        self._chart_tf_combo.addItems(CHART_TF_OPTIONS)
        self._chart_tf_combo.setToolTip(
            "Chart-Overlay-TF: ⚡ Auto (Kaskade) vs. 🔒 manuell fixiert")
        self._chart_tf_combo.currentTextChanged.connect(self._on_chart_tf_changed)
        layout.addWidget(self._chart_tf_combo)

        # --- Range-Picker ----------------------------------------------
        layout.addWidget(QLabel("Range:"))
        self._range_combo = QComboBox()
        self._range_combo.addItems(RANGE_PRESETS)
        self._range_combo.setToolTip("Zeitfenster-Preset (24h/7d/30d/YTD)")
        self._range_combo.currentTextChanged.connect(self._on_range_changed)
        layout.addWidget(self._range_combo)

        # --- Tabellen-Sortierung ---------------------------------------
        layout.addWidget(QLabel("Sortierung:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(SORT_MODES)
        self._sort_combo.setToolTip(
            "Tabellen-Sortierung: Datum, Signal-Stärke oder Timeframe")
        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)
        layout.addWidget(self._sort_combo)

        # --- Session-Filter --------------------------------------------
        self._session_checks: Dict[str, QCheckBox] = {}
        for session in SESSION_OPTIONS:
            cb = QCheckBox(session)
            cb.setToolTip("Session-Farbbalken im M1/M5-Zoom (UTC-Epochs)")
            cb.stateChanged.connect(self._on_sessions_changed)
            self._session_checks[session.lower()] = cb
            layout.addWidget(cb)

        # --- View-Templates (SchemaMigrator) ---------------------------
        layout.addSpacing(8)
        self._template_name = QLineEdit()
        self._template_name.setPlaceholderText("Preset-Name")
        self._template_name.setMaximumWidth(110)
        self._template_name.setToolTip("Name des View-Templates")
        layout.addWidget(self._template_name)

        self._btn_save_template = QPushButton("💾 Preset")
        self._btn_save_template.setToolTip(
            "Aktuelle Filter-Konfiguration als View-Template speichern")
        self._btn_save_template.clicked.connect(self._save_template)
        layout.addWidget(self._btn_save_template)

        self._btn_load_template = QPushButton("📂 Preset")
        self._btn_load_template.setToolTip("Gespeichertes View-Template laden")
        self._btn_load_template.clicked.connect(self._load_template)
        layout.addWidget(self._btn_load_template)

        self._template_combo = QComboBox()
        self._template_combo.setToolTip("Verfügbare View-Templates")
        self._template_combo.currentIndexChanged.connect(self._on_template_selected)
        layout.addWidget(self._template_combo)

        layout.addStretch(1)

    # ------------------------------------------------------------------
    # Public API (State-Sync über Provider, kein SQL)
    # ------------------------------------------------------------------
    def apply_namespace_state(self, context: Any) -> None:
        """Synchronisiert die Widgets aus dem MTF-FC-Namespace des Contexts.

        Wird z. B. nach `applyFullChartUpdate` aufgerufen, damit die
        Filterleiste die aktiven Werte (Data-TF, Chart-TF) anzeigt.
        """
        ns = self._provider.read_namespace(context)
        data_tf = str(ns.get("active_data_tf") or "M15")
        chart_tf = str(ns.get("active_chart_tf") or "M5")

        data_label = "🌐 Alle Timeframes (Multi)" if data_tf.lower() == "multi" \
            else f"🔒 {data_tf}"
        self._data_tf_combo.blockSignals(True)
        self._data_tf_combo.setCurrentText(data_label)
        self._data_tf_combo.blockSignals(False)

        # 'auto' wird im Chart über die Kaskade bestimmt; bei fixiertem
        # aktiven Chart-TF bleibt die Auswahl auf '⚡ Auto (Kaskade)'.
        self._chart_tf_combo.blockSignals(True)
        self._chart_tf_combo.setCurrentText(CHART_TF_OPTIONS[0])
        self._chart_tf_combo.blockSignals(False)

    def current_data_tf(self) -> str:
        """Aktiver Source-Data-TF ('multi' oder z. B. 'M15')."""
        return _parse_data_tf(self._data_tf_combo.currentText())

    def current_chart_tf(self) -> str:
        """Aktiver Chart-Overlay-TF ('auto' oder 'fix')."""
        return _parse_chart_tf(self._chart_tf_combo.currentText())

    def current_sort_mode(self) -> str:
        """Aktive Sortierung ('date' | 'signal' | 'tf')."""
        text = self._sort_combo.currentText()
        if text.startswith("Signal"):
            return "signal"
        if text.startswith("TF"):
            return "tf"
        return "date"

    def active_sessions(self) -> List[str]:
        """Aktive Session-Filter (klein geschrieben)."""
        return [s for s, cb in self._session_checks.items() if cb.isChecked()]

    def refresh_templates(self) -> None:
        """Aktualisiert die Template-Dropdown-Liste aus dem Store."""
        self._template_combo.blockSignals(True)
        self._template_combo.clear()
        self._template_combo.addItems(self._store.names())
        self._template_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_data_tf_changed(self, _text: str) -> None:
        self.data_tf_changed.emit(self.current_data_tf())

    def _on_chart_tf_changed(self, _text: str) -> None:
        self.chart_tf_changed.emit(self.current_chart_tf())

    def _on_range_changed(self, preset: str) -> None:
        if preset == "Benutzerdefiniert":
            return
        now = _now_epoch()
        seconds = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400,
                   "YTD": _ytd_epoch_offset(now)}.get(preset, 86400)
        self.range_changed.emit(preset, now - seconds, now)

    def _on_sort_changed(self, _text: str) -> None:
        self.sort_mode_changed.emit(self.current_sort_mode())

    def _on_sessions_changed(self, _state: int) -> None:
        self._sessions = self.active_sessions()
        self.sessions_changed.emit(list(self._sessions))

    def _save_template(self) -> None:
        name = self._template_name.text().strip() or "Unbenannt"
        template = create_template(
            name=name,
            data_tf=self.current_data_tf(),
            chart_tf=self.current_chart_tf(),
            range_preset=self._range_combo.currentText(),
            sort_mode=self.current_sort_mode(),
            session_filters=list(self._sessions),
        )
        self._store.save(template)
        self.refresh_templates()
        self._template_combo.setCurrentText(name)

    def _load_template(self) -> None:
        name = self._template_combo.currentText()
        if not name:
            return
        template = self._store.load(name)
        if template is None:
            return
        self._apply_template(template)
        self.template_applied.emit(template)

    def _on_template_selected(self, index: int) -> None:
        if index < 0:
            return
        self._load_template()

    def _apply_template(self, template: Dict[str, Any]) -> None:
        """Wendet ein geladenes Template auf die Widgets an (in-memory)."""
        data_tf = str(template.get("data_tf") or "multi")
        label = "🌐 Alle Timeframes (Multi)" if data_tf.lower() == "multi" \
            else f"🔒 {data_tf}"
        self._data_tf_combo.blockSignals(True)
        self._data_tf_combo.setCurrentText(label)
        self._data_tf_combo.blockSignals(False)

        range_preset = str(template.get("range_preset") or "7d")
        self._range_combo.blockSignals(True)
        self._range_combo.setCurrentText(range_preset)
        self._range_combo.blockSignals(False)

        sort_mode = str(template.get("sort_mode") or "date")
        self._sort_combo.blockSignals(True)
        self._sort_combo.setCurrentText(
            {"date": SORT_MODES[0], "signal": SORT_MODES[1],
             "tf": SORT_MODES[2]}.get(sort_mode, SORT_MODES[0]))
        self._sort_combo.blockSignals(False)

        sessions = template.get("session_filters") or []
        for key, cb in self._session_checks.items():
            cb.blockSignals(True)
            cb.setChecked(key in sessions)
            cb.blockSignals(False)
        self._sessions = [s for s in sessions if s in self._session_checks]
        self.sessions_changed.emit(list(self._sessions))

    # ------------------------------------------------------------------
    # Guard-Override (Ebene 2, 21.03.05) – Klick auf Reset-Badge
    # ------------------------------------------------------------------
    def request_guard_override(self, target_tf: str, reason: str = "ghost_marker_click") -> None:
        """Leitet einen Geister-Marker-Klick an die State-Machine weiter."""
        self.guard_override_requested.emit(target_tf, reason)


def _now_epoch() -> int:
    """Aktuelle Wanduhr-Epoch (Sekunden)."""
    import time
    return int(time.time())


def _ytd_epoch_offset(now: int) -> int:
    """Sekunden seit Jahresbeginn (Wanduhr)."""
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(now, tz=timezone.utc)
    start = datetime(dt.year, 1, 1, tzinfo=timezone.utc)
    return int(now - start.timestamp())
