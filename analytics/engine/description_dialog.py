# analytics/engine/description_dialog.py
"""
Phase 14 P14-01 – ServiceDescriptionDialog.

Zeigt die vollständigen Beschreibungsfelder einer Service-Instanz / eines
Plugins / eines Service-Sets an: Plugin-Name, Version, API-Version, Autor,
Kurz-Beschreibung, description_long (Markdown-Hilfe) und condition_rules
(strukturierte Regeln) in einem sauberen Read-Only QTextBrowser.

Design-Regeln:
- Headless-fähig instanziierbar: Der Konstruktor startet KEINEN Event-Loop
  (kein exec_()); er baut nur das Widget auf. Der Aufrufer entscheidet, ob
  und wann der Dialog modal angezeigt wird.
- Rein additiv: Der Dialog importiert keine konkreten Orchestratoren und
  greift ausschließlich auf übergebene Daten (Plugin-Objekt / dict) zu
  (Entkopplung, keine zirkulären Abhängigkeiten).
"""

from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)


class ServiceDescriptionDialog(QDialog):
    """Zeigt Plugin-/Service-/Set-Informationen im Read-Only-Modus an.

    Kann wahlweise direkt mit expliziten Feldern ODER komfortabel über die
    Klassenmethode ``from_plugin()`` aus einem PluginFeature + Instanz-Config
    befüllt werden (headless instanziierbar, kein exec_() im Konstruktor).
    """

    def __init__(
        self,
        parent=None,
        *,
        instance_id: Optional[str] = None,
        display_name: str = "",
        plugin_id: str = "",
        version: str = "1.0.0",
        api_version: str = "1",
        author: str = "",
        description: str = "",
        description_long: str = "",
        condition_rules: Optional[List[str]] = None,
        instance_description: str = "",
        header_line: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Service-Informationen")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        browser = QTextBrowser()
        browser.setReadOnly(True)
        browser.setOpenExternalLinks(True)
        browser.setHtml(self._render_html(
            instance_id=instance_id,
            display_name=display_name,
            plugin_id=plugin_id,
            version=version,
            api_version=api_version,
            author=author,
            description=description,
            description_long=description_long,
            condition_rules=condition_rules,
            instance_description=instance_description,
            header_line=header_line,
        ))
        layout.addWidget(browser)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # -------------------------------------------------------------------------
    # Fabrik-Methode: bequeme Befüllung aus PluginFeature + Instanz-Config
    # -------------------------------------------------------------------------
    @classmethod
    def from_plugin(
        cls,
        plugin: Any,
        instance_id: str = "",
        config: Optional[Dict[str, Any]] = None,
        parent=None,
        *,
        header_line: str = "",
    ) -> "ServiceDescriptionDialog":
        """Baut den Dialog aus einem PluginFeature und einer optionalen
        ServiceInstanceConfig (description der Instanz).

        Args:
            header_line: Optionale ERSTE Zeile (z.B. 'aktiv/im <Indikator>'
                         aus dem Info-Button-Tooltip) – Bugfix 05.08.2026.
        """
        meta = dict(getattr(plugin, "metadata", None) or {})
        cfg = dict(config or {})
        return cls(
            parent=parent,
            instance_id=instance_id or "",
            display_name=str(meta.get("display_name", "") or ""),
            plugin_id=str(getattr(plugin, "plugin_id", "") or ""),
            version=str(getattr(plugin, "version", "1.0.0") or "1.0.0"),
            api_version=str(meta.get("api_version", "1") or "1"),
            author=str(meta.get("author", "") or ""),
            description=str(meta.get("description", "") or ""),
            description_long=str(meta.get("description_long", "") or ""),
            condition_rules=list(meta.get("condition_rules") or []),
            instance_description=str(cfg.get("description", "") or ""),
            header_line=header_line,
        )

    @classmethod
    def from_set(
        cls,
        definition: Optional[Dict[str, Any]],
        parent=None,
        *,
        header_line: str = "",
    ) -> "ServiceDescriptionDialog":
        """Baut den Dialog aus einer Service-Set-Definition (Set-Info).

        Zeigt Set-Name (display_name), Set-Beschreibung (description) und die
        Service-Liste (instance_id [plugin_id] in execution_order-Reihenfolge).

        Args:
            definition:  Set-Definition aus dem ServiceSetRepository (set_id,
                         display_name, description, execution_order, services).
            parent:      Qt-Parent (optional).
            header_line: Optionale ERSTE Zeile (z.B. 'im GridLiquidityIndicator'
                         aus dem Info-Button-Tooltip) – wird als fette Zeile
                         gefolgt von einer Leerzeile vor dem Beschreibungstext
                         gerendert (Bugfix 05.08.2026, Info-Button MasterTree).
        """
        d = dict(definition or {})
        set_id = str(d.get("set_id") or "")
        display_name = str(d.get("display_name") or set_id or "Unbenannt")
        description = str(d.get("description") or "")
        services = d.get("services") or {}
        order = d.get("execution_order") or []
        svc_lines = [
            f"{iid} [{str((services.get(iid) or {}).get('plugin_id') or iid)}]"
            for iid in order
        ]
        if svc_lines:
            details = "<br>".join(svc_lines)
        else:
            details = ""
        return cls(
            parent=parent,
            instance_id=None,
            display_name=display_name,
            plugin_id=set_id or "",
            version="",
            api_version="",
            author="",
            description=description,
            description_long=details,
            condition_rules=[],
            instance_description="",
            header_line=header_line,
        )

    # -------------------------------------------------------------------------
    # Interna
    # -------------------------------------------------------------------------
    @staticmethod
    def _html_escape(value: str) -> str:
        """Minimaler HTML-Escape für Anzeige-Strings (kein externer Import)."""
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _render_html(
        self,
        *,
        instance_id: Optional[str],
        display_name: str,
        plugin_id: str,
        version: str,
        api_version: str,
        author: str,
        description: str,
        description_long: str,
        condition_rules: Optional[List[str]],
        instance_description: str,
        header_line: str = "",
    ) -> str:
        """Erzeugt das Read-Only-HTML des Dialogs (sauber strukturiert)."""
        e = self._html_escape
        parts: List[str] = []

        # Bugfix 05.08.2026: optionale ERSTE Zeile (Info-Button-Tooltip,
        # z.B. 'aktiv/im <Indikator>') + Leerzeile vor dem eigentlichen Text.
        if header_line and str(header_line).strip():
            parts.append(f"<p style='margin-bottom:0;'><b>{e(header_line)}</b></p>")
            parts.append("<p>&nbsp;</p>")

        # Kopf: Instanz (falls vorhanden) + Plugin-Name + Version
        head = ""
        if instance_id:
            head += f"<b>Instanz:</b> {e(instance_id)}<br>"
        if display_name:
            head += f"<b>{e(display_name)}</b>"
        if plugin_id:
            head += f" <i>({e(plugin_id)})</i>"
        if version:
            head += f" &mdash; v{e(version)}"
        if head.strip():
            parts.append(f"<h3>{head}</h3>")

        # Meta-Zeile: API-Version + Autor
        meta_bits = []
        if api_version:
            meta_bits.append(f"API-Version: {e(api_version)}")
        if author:
            meta_bits.append(f"Autor: {e(author)}")
        if meta_bits:
            parts.append(f"<p style='color:#666;'>{' | '.join(meta_bits)}</p>")

        # Instanz-Beschreibung (ServiceInstanceConfig.description)
        if instance_description:
            parts.append(f"<p><b>Instanz-Anmerkung:</b><br>{e(instance_description)}</p>")

        # Kurz-Beschreibung
        if description:
            parts.append(f"<p><b>Beschreibung:</b><br>{e(description)}</p>")

        # Lange Beschreibung (Markdown-Hilfe)
        if description_long:
            parts.append(f"<p><b>Details:</b><br>{e(description_long)}</p>")

        # Strukturierte Regeln
        rules = [r for r in (condition_rules or []) if str(r).strip()]
        if rules:
            items = "".join(f"<li>{e(r)}</li>" for r in rules)
            parts.append(f"<p><b>Regeln:</b></p><ul>{items}</ul>")

        if not parts:
            parts.append("<p>Keine Beschreibungsfelder hinterlegt.</p>")

        return (
            "<html><body style='font-family:Segoe UI, sans-serif; font-size:12px;'>"
            + "".join(parts)
            + "</body></html>"
        )
