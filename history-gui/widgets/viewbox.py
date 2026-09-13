"""Custom PyQtGraph ViewBox for vessel history time-series plots.

Supports:
- Left-click drag: Zoom into selected area (time interval or 2D box).
- Shift + Left-click drag: Pan horizontally along time axis (X-direction only, Y locked).
- Double-click: Reset view to full range (autoRange).
- Scroll wheel: Zooming disabled entirely across all axes.
"""

from __future__ import annotations

import pyqtgraph as pg
from PyQt6 import QtCore
from PyQt6.QtCore import Qt


class TimeSeriesViewBox(pg.ViewBox):
    """ViewBox tailored for synchronized time-series plots."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseMode(pg.ViewBox.RectMode)
        self.rbScaleBox.setPen(pg.mkPen("#00e5ff", width=1.5, style=Qt.PenStyle.DashLine))
        self.rbScaleBox.setBrush(pg.mkBrush(0, 229, 255, 40))

    def wheelEvent(self, ev, axis=None):
        """Disable scroll wheel zooming entirely."""
        ev.accept()

    def mouseClickEvent(self, ev):
        """Double left-click resets view to full range."""
        if ev.button() == Qt.MouseButton.LeftButton and ev.double():
            ev.accept()
            self.autoRange()
            return
        super().mouseClickEvent(ev)

    def mouseDragEvent(self, ev, axis=None):
        ev.accept()

        if ev.button() == Qt.MouseButton.LeftButton:
            modifiers = ev.modifiers()
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                # ---------------- Pan: Shift + Left-Click Drag (X-dir only) ----------------
                pos = ev.pos()
                lastPos = ev.lastPos()
                dif = (pos - lastPos) * -1

                tr = self.childGroup.transform()
                tr = pg.functions.invertQTransform(tr)
                # Map strictly the horizontal difference:
                tr_dif = tr.map(QtCore.QPointF(dif.x(), 0)) - tr.map(QtCore.QPointF(0, 0))

                self._resetTarget()
                self.translateBy(x=tr_dif.x(), y=None)
                self.sigRangeChangedManually.emit([True, False])

                if ev.isFinish():
                    self.unsetCursor()
                else:
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
            else:
                # ---------------- Zoom: Left-Click Drag Box ----------------
                if ev.isFinish():
                    self.rbScaleBox.hide()
                    self.unsetCursor()
                    p1 = ev.buttonDownPos(ev.button())
                    p2 = ev.pos()
                    if (p2 - p1).manhattanLength() > 5:
                        v1 = self.mapToView(p1)
                        v2 = self.mapToView(p2)
                        x_min = min(v1.x(), v2.x())
                        x_max = max(v1.x(), v2.x())
                        y_min = min(v1.y(), v2.y())
                        y_max = max(v1.y(), v2.y())
                        if (x_max - x_min) > 0.05:
                            self.setXRange(x_min, x_max, padding=0)
                            if abs(p2.y() - p1.y()) > 30 and (y_max - y_min) > 1e-4:
                                self.setYRange(y_min, y_max, padding=0)
                            else:
                                self.enableAutoRange(axis="y")
                            self.sigRangeChangedManually.emit([True, True])
                    return
                else:
                    self.setCursor(Qt.CursorShape.CrossCursor)
                    self.updateScaleBox(ev.buttonDownPos(), ev.pos())
                    return

        super().mouseDragEvent(ev, axis=axis)
