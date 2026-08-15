"""
indicator_dialog_geometry.py - Geometrie/Lebenszyklus: Geometrie-Restore/-Save, done

23.10 God-File-Split (15.08.2026): Aus chart/indicator_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der
IndicatorSettingsDialog-Klasse als Mixin (Klasse IndicatorSettingsDialogGeometryMixin).
"""

from PySide6.QtWidgets import (
    QApplication,
)

class IndicatorSettingsDialogGeometryMixin:

	# -------------------------------------------------------------------------
	# Geometrie-Persistenz & Presets (unverändert für beide Modi)
	# -------------------------------------------------------------------------

	def _restore_geometry(self) -> None:
		"""Stellt die letzte POSITION des nicht-modalen Dialogs wieder her.

		Phase 13 Schritt 5 Punkt 4: Die Größe wird NICHT wiederhergestellt –
		das Prop-Fenster ist vollständig dynamisch (Inhalt bestimmt Höhe/Breite,
		keine fixen Pixelwerte, kein leerer Raum unter dem Preset-Block).
		"""
		try:
			geom = self.state_manager.get_dialog_geometry(self.DIALOG_GEOMETRY_KEY)
			if not geom:
				return

			pos_x = geom.get("pos_x")
			pos_y = geom.get("pos_y")

			# Position validieren (Bildschirm-Bounds; sonst zuruecksetzen)
			if pos_x is not None and pos_y is not None:
				screen = QApplication.primaryScreen().availableGeometry()
				if pos_x < screen.x() - 100 or pos_x > screen.right() or \
				   pos_y < screen.y() - 100 or pos_y > screen.bottom():
					pos_x = pos_y = None
				else:
					self.move(pos_x, pos_y)
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Geometrie-Restore fehlgeschlagen: {e}")

	def _save_geometry(self) -> None:
		"""Speichert die aktuelle Position/Groesse des Dialogs.

		Punkt 4: Wiederhergestellt wird nur die Position (siehe
		_restore_geometry) – die Größe ist dynamisch (Inhalt bestimmt Höhe/Breite).
		"""
		try:
			p = self.pos()
			s = self.size()
			self.state_manager.save_dialog_geometry(
				self.DIALOG_GEOMETRY_KEY, p.x(), p.y(), s.width(), s.height()
			)
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Geometrie-Save fehlgeschlagen: {e}")

	def done(self, r: int) -> None:
		"""Wird bei jedem Schliessen aufgerufen (accept/reject/Esc/X) ->
		Geometrie vor dem Schliessen speichern."""
		self._save_geometry()
		if self._set_run_worker and self._set_run_worker.isRunning():
			self._set_run_worker.wait(2000)
		super().done(r)
