# -*- coding: utf-8 -*-
"""
area_map_tool.py
-----------------
Niestandardowe narzędzie mapy (QgsMapTool) pozwalające użytkownikowi
narysować poligon bezpośrednio na mapie:

- lewy przycisk myszy / kliknięcie  -> dodaje wierzchołek,
- podgląd linii do bieżącej pozycji kursora,
- dwuklik (lub prawy przycisk)      -> kończy rysowanie,
- ESC                                -> anuluje rysowanie,
- Backspace                          -> usuwa ostatnio dodany wierzchołek.

Po zakończeniu emitowany jest sygnał geometryCaptured(geometry, crs)
z domkniętym poligonem w układzie współrzędnych canvasu. W razie
anulowania emitowany jest sygnał captureCanceled().
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsWkbTypes, QgsGeometry, QgsPointXY
from qgis.gui import QgsMapTool, QgsRubberBand


class AreaMapTool(QgsMapTool):

    geometryCaptured = pyqtSignal(QgsGeometry, object)  # (geometria, QgsCoordinateReferenceSystem)
    captureCanceled = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.points = []

        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber_band.setColor(QColor(255, 140, 0, 90))
        self.rubber_band.setStrokeColor(QColor(255, 120, 0, 230))
        self.rubber_band.setWidth(2)

        self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------------
    # Cykl życia narzędzia
    # ------------------------------------------------------------------

    def activate(self):
        super().activate()
        self.points = []
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self.canvas.setFocus()

    def deactivate(self):
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self.points = []
        super().deactivate()

    def isZoomTool(self):
        return False

    def isTransient(self):
        return False

    def isEditTool(self):
        return True

    # ------------------------------------------------------------------
    # Zdarzenia myszy
    # ------------------------------------------------------------------

    def canvasPressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            point = QgsPointXY(self.toMapCoordinates(event.pos()))
            self.points.append(point)
            self._redraw()
        elif event.button() == Qt.MouseButton.RightButton:
            self._finish()

    def canvasMoveEvent(self, event):
        if not self.points:
            return
        preview_point = QgsPointXY(self.toMapCoordinates(event.pos()))
        self._redraw(preview_point=preview_point)

    def canvasDoubleClickEvent(self, event):
        self._finish()

    # ------------------------------------------------------------------
    # Klawiatura
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            event.accept()
        elif event.key() == Qt.Key.Key_Backspace:
            if self.points:
                self.points.pop()
                self._redraw()
            event.accept()

    # ------------------------------------------------------------------
    # Wewnętrzne
    # ------------------------------------------------------------------

    def _redraw(self, preview_point=None):
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        pts = list(self.points)
        if preview_point is not None:
            pts = pts + [preview_point]
        if len(pts) < 2:
            for p in pts:
                self.rubber_band.addPoint(p, True)
            return
        for i, p in enumerate(pts):
            self.rubber_band.addPoint(p, i == len(pts) - 1)

    def _finish(self):
        pts = list(self.points)
        # Podwójne kliknięcie generuje dodatkowy (prawie identyczny) punkt
        # tuż przed zdarzeniem doubleClick - usuwamy go, aby nie tworzyć
        # zbędnego, prawie zdegenerowanego wierzchołka.
        if len(pts) >= 2:
            pts = pts[:-1]

        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self.points = []

        if len(pts) < 3:
            self.captureCanceled.emit()
            return

        ring = pts + [pts[0]]
        geometry = QgsGeometry.fromPolygonXY([ring])
        crs = self.canvas.mapSettings().destinationCrs()
        self.geometryCaptured.emit(geometry, crs)

    def _cancel(self):
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self.points = []
        self.captureCanceled.emit()
