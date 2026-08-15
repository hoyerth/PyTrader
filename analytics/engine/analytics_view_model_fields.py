"""
analytics_view_model_fields.py - Feature-/Feld-Selektion & Normalisierung (field_pairs, feature_ids, hashes)

23.07 God-File-Split (15.08.2026): Aus analytics/engine/analytics_view_model.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der AnalyticsViewModel-
Klasse als Mixin (Klasse AnalyticsViewModelFieldMixin).
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

from analytics.engine.analytics_worker import (
    QUERY_TABLE,
    QUERY_HEATMAP,
    QUERY_HEATMAP_GENERIC,
    QUERY_SCATTER,
    QUERY_DISTRIBUTION,
    QUERY_FEATURES,
)

class AnalyticsViewModelFieldMixin:

    def set_feature_id(self, feature_id: Optional[str]) -> None:
        """Kompatibilitaets-Alias (Legacy): Einzel-ID -> Multi-Liste."""
        self.set_feature_ids([feature_id] if feature_id else [])

    def set_feature_ids(self, feature_ids, instance_hashes=None) -> None:
        """Setzt die Multi-Auswahl der Datenquellen (15.03-E).

        `feature_ids` sind die plugin_ids des Feature-Store (z. B.
        ["srv_grid_lines", "srv_proximity"]); leer = kein Filter (alle Features).
        Typen-/Duplikat-normalisiert; ohne Aenderung wird kein Refresh
        ausgeloest (idempotent, wie set_symbol/set_timeframe).

        Runde 10 (Bug 1): `instance_hashes` schraenkt die gewaehlten
        plugin_ids auf bestimmte Varianten (Clones) ein - None/leer =
        KEINE Varianten-Einschraenkung (alle Varianten der plugin_ids).
        None bedeutet ausserdem: bestehende Hash-Einschraenkung bleibt
        erhalten (z. B. bei reinen feature_ids-Aenderungen durch das
        Feld-Dropdown). Die Hashes fliessen als zusaetzliche
        WHERE-Bedingung in die Reader-Queries
        (`(instance_hash IS NULL OR instance_hash IN (...))`).
        """
        ids = self._normalize_feature_ids(feature_ids)
        hashes_changed = instance_hashes is not None
        if hashes_changed:
            hashes = self._normalize_instance_hashes(instance_hashes)
        else:
            # None = bestehende Einschraenkung beibehalten (kein
            # versehentliches Leeren durch Alt-Aufrufer).
            hashes = self._params.get("instance_hashes") or []
        if (ids == self._params.get("feature_ids")
                and (not hashes_changed
                     or hashes == self._params.get("instance_hashes"))):
            return
        ids_changed = ids != self._params.get("feature_ids")
        self._params["feature_ids"] = ids
        if hashes_changed:
            self._params["instance_hashes"] = hashes
        self._mark_dirty()
        if ids_changed:
            # Runde 8 (Bugfix 4): Die UI leitet ihr 'Feld'-Dropdown
            # SYNCHRON neu ab (kein Query-Round-Trip) - das
            # HeatmapWidget verbindet feature_ids_changed und baut
            # Items/Haken/Current sofort neu. (Nur bei feature_ids-
            # Aenderung; reine Hash-Aenderung laesst das Feld-Dropdown
            # unveraendert.)
            self.feature_ids_changed.emit()
        # Runde 15b (Bugfix Dropdown, User-Meldung 10.08.2026): QUERY_FEATURES
        # gehoert in den Refresh - der leichte Metadaten-Pfad liefert die
        # field_sources/no_data_variants fuer die AKTUELLEN feature_ids +
        # instance_hashes (Feld-Dropdown + NoData-Hinweise). Ohne den
        # Refresh bliebe das Dropdown auf dem Cache-Stand des letzten
        # Payloads (z. B. ein zuvor gefilterter Satz ohne die neu gecheckten
        # Services) - Check/Uncheck waere erst nach einem Seitenwechsel
        # sichtbar. Die Queue-Reihenfolge (QUERY_FEATURES zuerst) spiegelt
        # die Runde-15-Prioritaet: leichtes Dropdown-Update VOR der Grafik.
        self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                       QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                       QUERY_DISTRIBUTION))

    def set_field_selection(self, field_pairs, update_ids: bool = True) -> None:
        """Setzt die (Service|Parameter)-Auswahl des 'Feld'-Dropdowns.

        12.08.2026 (Option A, Bug 1/2): Die Feld-Auswahl ist eine explizite
        Liste von '{service_id}|{key}'-Paaren (effective pairs) - der
        Reader filtert damit auf PARAMETER-Ebene (field_pairs-WHERE:
        `feature_data->>key IS NOT NULL` je Service). Leere Liste = kein
        Paar-Filter (reines feature_ids-Verhalten wie bisher).

        `update_ids=True` (USER-Interaktion, ServicePicker-Sync): Die
        Services werden aus den Paaren abgeleitet und in `feature_ids`
        uebernommen (Dropdown und Picker bleiben konsistent; Abwaehlen des
        letzten Parameters eines Services entfernt ihn aus dem Picker).

        `update_ids=False` (PROGRAMMATISCHER Sync am Ende des
        Dropdown-Rebuilds): `feature_ids` bleibt UNANGETASTET - der
        ServicePicker ist die Service-Quelle; Services OHNE numerische
        Feld-Keys duerfen dadurch nicht stillschweigend aus der Auswahl
        fallen (nur ihre Paare koennen fehlen).

        Im Gegensatz zu set_feature_ids() wird der Refresh auch bei
        UNVERAENDERTER Service-Menge ausgeloest, wenn sich die Parameter-
        Auswahl geaendert hat. Idempotent ohne Aenderung (kein
        Refresh/Dirty).
        """
        pairs = self._normalize_field_pairs(field_pairs)
        ids = self._pairs_to_feature_ids(pairs)
        current_pairs = self._params.get("field_selection") or []
        current_ids = self._params.get("feature_ids") or []
        pairs_changed = pairs != current_pairs
        ids_changed = update_ids and ids != current_ids
        if not pairs_changed and not ids_changed:
            return
        self._params["field_selection"] = pairs
        if ids_changed:
            self._params["feature_ids"] = ids
        self._mark_dirty()
        if ids_changed:
            # Service-Satz geaendert -> ServicePicker + Feld-Metadaten
            # (QUERY_FEATURES) synchron nachziehen (identisch zu
            # set_feature_ids).
            self.feature_ids_changed.emit()
            self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                       QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                       QUERY_DISTRIBUTION))
        else:
            # NUR die Parameter-Auswahl hat sich geaendert -> nur die
            # generische Heatmap neu aggregieren (Bug 1: An/Abwaehlen
            # eines Parameters muss die Grafik aendern).
            self._refresh((QUERY_HEATMAP_GENERIC,))

    @staticmethod
    def _normalize_field_pairs(value) -> List[str]:
        """Normalisiert '{service_id}|{key}'-Paare (dedupliziert, getrimmt).

        12.08.2026 (Option A): Eintraege ohne `|` oder mit leerer Service-/
        Key-Seite werden verworfen. Die Keys bleiben case-sensitiv (JSON-
        Keys aus den Service-Payloads), die Service-ID wird getrimmt.
        """
        if not value:
            return []
        out: List[str] = []
        for v in value:
            s = str(v).strip()
            if not s or "|" not in s:
                continue
            sid, key = s.split("|", 1)
            sid = sid.strip()
            key = key.strip()
            if sid and key and f"{sid}|{key}" not in out:
                out.append(f"{sid}|{key}")
        return out

    @staticmethod
    def _pairs_to_feature_ids(pairs) -> List[str]:
        """Leitet die aktiven Service-IDs aus '{service_id}|{key}'-Paaren ab.

        12.08.2026 (Option A): Dedupliziert in Paar-Reihenfolge (die
        Feld-Dropdown-Item-Reihenfolge bestimmt die ServicePicker-Reihenfolge
        - konsistent zu _checked_field_service_ids()).
        """
        out: List[str] = []
        for p in pairs or []:
            s = str(p or "")
            if "|" not in s:
                continue
            sid = s.split("|", 1)[0].strip()
            if sid and sid not in out:
                out.append(sid)
        return out

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

    @staticmethod
    def _normalize_instance_hashes(value) -> List[str]:
        """Normalisiert instance_hashes (Liste[str], dedupliziert,
        getrimmt) - Runde 10 (Bug 1, Varianten-Einschraenkung)."""
        if not value:
            return []
        out: List[str] = []
        for v in value:
            s = str(v).strip()
            if s and s not in out:
                out.append(s)
        return out

    def _resolve_feature_ids(
        self, feature_ids: List[str]
    ) -> Tuple[List[str], List[str]]:
        """Isoliert fehlende Services ueber den Resolver (20.01, E5).

        Ohne ein injiziertes Modell (Tests/Alt-Aufrufer) wird ein lazies
        Default-Modell erzeugt (nur wenn ueberhaupt IDs zu pruefen sind).
        Fehler -> (normalisierte ids, []) defensiv (kein Absturz).
        """
        ids = self._normalize_feature_ids(feature_ids)
        if not ids:
            return [], []
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            return model.resolve_valid_feature_ids(ids)
        except Exception:
            return ids, []

    @staticmethod
    def _flatten_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Flacht v2-Sections (sources/charts/table/styling) auf Top-Level ab.

        20.01 (E2/E3): Der ViewModel arbeitet weiterhin mit flachen `_params` –
        die v2-Sektions-Keys haben Vorrang vor gleichnamigen Top-Level-Resten
        (die bei der v1→v2-Migration verlustfrei erhalten bleiben).
        """
        flat: Dict[str, Any] = {}
        for section in ("sources", "charts", "table", "styling"):
            values = payload.get(section)
            if isinstance(values, dict):
                flat.update(values)
        for key, value in payload.items():
            if key in ("schema_version", "sources", "charts", "table",
                       "styling"):
                continue
            if key not in flat:
                flat[key] = value
        return flat
