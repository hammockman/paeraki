"""Dynamic unit-based chart stack with linked X-axes and synchronized crosshairs.

Creates and stacks pyqtgraph PlotWidgets grouped strictly by metric engineering unit (V, A, W, °, kn, etc.).
"""

from __future__ import annotations

import datetime
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import db
from widgets.viewbox import TimeSeriesViewBox

# Standard unit sorting hierarchy
UNIT_ORDER = [
    "V", "A", "W", "%", "°", "kn", "°C", "hPa", "mV", "°/s", "Ah", "kWh", "count", "HDOP", "m"
]

UNIT_LABELS = {
    "V": "VOLTAGE",
    "A": "CURRENT",
    "W": "POWER",
    "%": "STATE OF CHARGE / PERCENT",
    "°": "VESSEL ATTITUDE & HEADING",
    "kn": "VESSEL SPEED",
    "°C": "TEMPERATURES",
    "hPa": "BAROMETRIC PRESSURE",
    "mV": "CELL BALANCE DELTA",
    "°/s": "RATE OF TURN",
    "Ah": "CAPACITY",
    "kWh": "ENERGY HARVEST / CONSUMPTION",
    "count": "DISCRETE COUNTS",
    "HDOP": "GNSS DILUTION OF PRECISION",
    "m": "ELEVATION / ALTITUDE",
}


class UnitPlotContainer(QFrame):
    """Container for a single engineering unit's pyqtgraph plot."""

    def __init__(self, unit: str, metrics: list[db.MetricDef], is_bottom: bool = False, parent=None):
        super().__init__(parent)
        self.unit = unit
        self.metrics = metrics
        self.is_bottom = is_bottom

        self.curves: dict[str, pg.PlotDataItem] = {}

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Bottom DateAxisItem for time formatting
        self.date_axis = pg.DateAxisItem(orientation="bottom")
        self.plot_widget = pg.PlotWidget(
            viewBox=TimeSeriesViewBox(),
            axisItems={"bottom": self.date_axis} if self.is_bottom else None
        )
        self.plot_widget.setBackground("#080c16")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)

        # Unit Title
        unit_name = UNIT_LABELS.get(self.unit, self.unit)
        metric_parts = []
        for m in self.metrics:
            metric_parts.append(f"<span style='color:{m.color}; font-weight:600;'>{m.name}</span>")
        title_html = f"<span style='font-weight:bold; font-size:12px;'>{unit_name} ({self.unit})</span> — " + ", ".join(metric_parts)
        self.plot_widget.setTitle(title_html)

        # Left Y-Axis
        first_color = self.metrics[0].color if self.metrics else "#38bdf8"
        self.plot_widget.setLabel("left", unit_name.title(), units=self.unit, color=first_color)

        if not self.is_bottom:
            self.plot_widget.hideAxis("bottom")

        # Zero reference line for bipolar metrics
        has_bipolar = any(m.bipolar for m in self.metrics)
        if has_bipolar:
            self.plot_widget.addItem(
                pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#334155", width=1, style=Qt.PenStyle.DashLine))
            )

        # Create curves for each metric on the common unit Y-axis
        for m in self.metrics:
            pen = pg.mkPen(color=m.color, width=2)
            curve = self.plot_widget.plot(pen=pen, name=f"{m.name} ({m.unit})", connect="finite")
            self.curves[m.id] = curve

        # Synchronized vertical crosshair cursor line
        self.cursor_line = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen("#ffffff", width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.plot_widget.addItem(self.cursor_line, ignoreBounds=True)

        layout.addWidget(self.plot_widget)

    def set_bottom_axis_visible(self, visible: bool):
        """Toggle bottom time axis visibility."""
        if visible:
            self.plot_widget.showAxis("bottom")
        else:
            self.plot_widget.hideAxis("bottom")

    def set_cursor_pos(self, x_val: float):
        """Move vertical cursor line."""
        self.cursor_line.setPos(x_val)


class UnitChartStack(QWidget):
    """Dynamic vertical stack of unit-based pyqtgraph plots."""

    cursor_moved = pyqtSignal(float)  # emits cursor timestamp in seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("unitChartStack")
        self._selected_metrics: list[db.MetricDef] = []
        self._plot_containers: dict[str, UnitPlotContainer] = {}
        self._table_data: dict[str, list[dict[str, Any]]] = {}
        self._timestamps: dict[str, np.ndarray] = {}
        self._init_ui()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(4, 4, 4, 4)
        self.main_layout.setSpacing(6)

        # Empty state label
        self.lbl_empty = QLabel("No metrics selected.\nSelect one or more metrics from the left panel to display charts.")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet("""
            color: #64748b;
            font-size: 14px;
            font-weight: 600;
            background-color: #080c16;
            border: 1px dashed #1e293b;
            border-radius: 8px;
            padding: 40px;
        """)
        self.main_layout.addWidget(self.lbl_empty)

    def update_selected_metrics(self, selected_ids: set[str]):
        """Rebuild plot containers when selected metrics change."""
        # Resolve metrics
        metrics = [db.METRIC_CATALOG[mid] for mid in selected_ids if mid in db.METRIC_CATALOG]
        self._selected_metrics = metrics

        # Group by unit
        unit_map: dict[str, list[db.MetricDef]] = {}
        for m in metrics:
            unit_map.setdefault(m.unit, []).append(m)

        # Sort units by standard order
        sorted_units = sorted(
            unit_map.keys(),
            key=lambda u: UNIT_ORDER.index(u) if u in UNIT_ORDER else 999
        )

        # Clear existing containers
        for c in self._plot_containers.values():
            c.plot_widget.scene().sigMouseMoved.disconnect()
            self.main_layout.removeWidget(c)
            c.deleteLater()
        self._plot_containers.clear()

        if not sorted_units:
            self.lbl_empty.show()
            return

        self.lbl_empty.hide()

        # Create plot containers
        primary_plot: pg.PlotWidget | None = None
        n_units = len(sorted_units)

        for idx, unit in enumerate(sorted_units):
            is_bottom = (idx == n_units - 1)
            container = UnitPlotContainer(unit, unit_map[unit], is_bottom=is_bottom, parent=self)

            if primary_plot is None:
                primary_plot = container.plot_widget
            else:
                container.plot_widget.setXLink(primary_plot)

            # Connect mouse hover tracking
            container.plot_widget.scene().sigMouseMoved.connect(self._on_scene_mouse_moved)

            self.main_layout.addWidget(container, stretch=1)
            self._plot_containers[unit] = container

        # Render curves if data is already cached
        self._render_all_curves()

    def set_table_data(self, tables_data: dict[str, list[dict[str, Any]]]):
        """Store freshly fetched table rows and render curves."""
        self._table_data = tables_data
        self._timestamps.clear()

        # Cache timestamp arrays for fast binary search
        for tbl, rows in tables_data.items():
            if rows:
                self._timestamps[tbl] = np.array([r["epoch_ms"] / 1000.0 for r in rows], dtype=np.float64)
            else:
                self._timestamps[tbl] = np.array([], dtype=np.float64)

        self._render_all_curves()

    def _render_all_curves(self):
        """Populate pyqtgraph curves with data points."""
        if not self._plot_containers or not self._table_data:
            return

        all_t_min = []
        all_t_max = []

        for unit, container in self._plot_containers.items():
            for m in container.metrics:
                rows = self._table_data.get(m.table, [])
                t_arr = self._timestamps.get(m.table)
                if not rows or t_arr is None or len(t_arr) == 0:
                    if m.id in container.curves:
                        container.curves[m.id].clear()
                    continue

                all_t_min.append(float(t_arr[0]))
                all_t_max.append(float(t_arr[-1]))

                y_arr = np.array([np.nan if r.get(m.column) is None else float(r.get(m.column)) for r in rows], dtype=np.float64)
                connect_mask = db.compute_connect_array(t_arr, y_arr)

                if m.id in container.curves:
                    container.curves[m.id].setData(t_arr, y_arr, connect=connect_mask)

            container.plot_widget.enableAutoRange(axis="y")

        # Set zoom limits on first plot if timestamps exist
        if all_t_min and all_t_max:
            t_min = min(all_t_min)
            t_max = max(all_t_max)
            pad = max(1.0, (t_max - t_min) * 0.02)
            total_span = (t_max - t_min) + 2 * pad
            first_unit = list(self._plot_containers.keys())[0]
            first_plot = self._plot_containers[first_unit].plot_widget
            first_plot.plotItem.vb.setLimits(
                xMin=t_min - pad,
                xMax=t_max + pad,
                minXRange=5.0,
                maxXRange=total_span,
            )

    def _on_scene_mouse_moved(self, pos):
        """Handle mouse movement across any chart to project synchronized crosshairs."""
        if not self._plot_containers:
            return

        # Map to X timestamp
        first_container = list(self._plot_containers.values())[0]
        mouse_point = first_container.plot_widget.plotItem.vb.mapSceneToView(pos)
        x_val = mouse_point.x()

        # Update cursor line on ALL plots simultaneously
        for container in self._plot_containers.values():
            container.set_cursor_pos(x_val)

        self.cursor_moved.emit(x_val)
