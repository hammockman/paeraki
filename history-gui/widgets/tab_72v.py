"""72V Propulsion Subsystem tab with interactive multi-curve graphs,
crosshairs, dynamic cell balance bar inspector, and KPI analytics.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from widgets.viewbox import TimeSeriesViewBox


class Tab72V(QWidget):
    """Interactive 72V Propulsion Subsystem visualization tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: list[dict[str, Any]] = []
        self._timestamps: np.ndarray = np.array([])
        self._summary: dict[str, Any] = {}
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # ---------------- KPI Analytics Header ----------------
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(10)

        self.kpi_v_card, self.kpi_v_val, self.kpi_v_sub = self._create_kpi_card(
            "PACK VOLTAGE", "--.- V", "Min: -- | Max: --"
        )
        self.kpi_p_card, self.kpi_p_val, self.kpi_p_sub = self._create_kpi_card(
            "PROPULSION POWER", "-- W", "Peak: -- W | Curr: -- A"
        )
        self.kpi_delta_card, self.kpi_delta_val, self.kpi_delta_sub = self._create_kpi_card(
            "CELL BALANCE (20S)", "-- mV", "Min: -.---V | Max: -.---V"
        )
        self.kpi_temp_card, self.kpi_temp_val, self.kpi_temp_sub = self._create_kpi_card(
            "TEMPERATURES", "-- °C", "T1: -- | T2: --"
        )

        kpi_layout.addWidget(self.kpi_v_card)
        kpi_layout.addWidget(self.kpi_p_card)
        kpi_layout.addWidget(self.kpi_delta_card)
        kpi_layout.addWidget(self.kpi_temp_card)
        main_layout.addLayout(kpi_layout)

        # ---------------- Splitter: Graphs on Left, Cell Bar Inspector on Right ----------------
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)

        # Left Container: Stacked pyqtgraph plots
        plots_container = QWidget()
        plots_layout = QVBoxLayout(plots_container)
        plots_layout.setContentsMargins(0, 0, 0, 0)
        plots_layout.setSpacing(8)

        # Upper Plot: Pack Voltage (Left Axis) & Current (Right Axis)
        self.date_axis_top = pg.DateAxisItem(orientation="bottom")
        self.plot_vp = pg.PlotWidget(viewBox=TimeSeriesViewBox(), axisItems={"bottom": self.date_axis_top})
        self.plot_vp.setBackground("#080c16")
        self.plot_vp.showGrid(x=True, y=True, alpha=0.25)
        self.plot_vp.setTitle("<span style='color: #00e5ff; font-weight: bold;'>Pack Voltage (V) & Current (A)</span>")
        self.plot_vp.setLabel("left", "Voltage", units="V", color="#00e5ff")

        # Right Y-axis for Current
        self.view_current = pg.ViewBox()
        self.view_current.setMouseEnabled(x=False, y=False)
        self.plot_vp.scene().addItem(self.view_current)
        self.plot_vp.getAxis("right").linkToView(self.view_current)
        self.view_current.setXLink(self.plot_vp)
        self.plot_vp.showAxis("right")
        self.plot_vp.getAxis("right").setLabel("Current", units="A", color="#10b981")

        # Re-link view size
        self.plot_vp.getViewBox().sigResized.connect(self._update_views)

        # Curves
        self.curve_voltage = self.plot_vp.plot(
            pen=pg.mkPen("#00e5ff", width=1.5),
            symbol="o",
            symbolSize=3,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#00e5ff"),
            name="Voltage (V)",
            connect="finite",
        )
        self.curve_current = pg.PlotDataItem(
            pen=pg.mkPen("#10b981", width=1.5),
            symbol="o",
            symbolSize=3,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#10b981"),
            name="Current (A)",
            connect="finite",
        )
        self.view_current.addItem(self.curve_current)

        # Charger Current Curve
        self.curve_charger_current = pg.PlotDataItem(
            pen=pg.mkPen("#38bdf8", width=1.5),
            symbol="t",
            symbolSize=3,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#38bdf8"),
            name="Charger Current (A)",
            connect="finite",
        )
        self.view_current.addItem(self.curve_charger_current)

        # Zero line for current
        zero_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(color="#334155", width=1, style=Qt.PenStyle.DashLine))
        self.view_current.addItem(zero_line)

        # Lower Plot: Power (W) & Cell Delta (mV)
        self.date_axis_bottom = pg.DateAxisItem(orientation="bottom")
        self.plot_bottom = pg.PlotWidget(viewBox=TimeSeriesViewBox(), axisItems={"bottom": self.date_axis_bottom})

        self.plot_bottom.setBackground("#080c16")
        self.plot_bottom.showGrid(x=True, y=True, alpha=0.25)
        self.plot_bottom.setTitle("<span style='color: #fbbf24; font-weight: bold;'>Power (W) & Cell Delta (mV)</span>")
        self.plot_bottom.setLabel("left", "Power", units="W", color="#fbbf24")

        # Right Y-axis for Delta
        self.view_delta = pg.ViewBox()
        self.view_delta.setMouseEnabled(x=False, y=False)
        self.plot_bottom.scene().addItem(self.view_delta)
        self.plot_bottom.getAxis("right").linkToView(self.view_delta)
        self.view_delta.setXLink(self.plot_bottom)
        self.plot_bottom.showAxis("right")
        self.plot_bottom.getAxis("right").setLabel("Delta", units="mV", color="#f43f5e")

        self.plot_bottom.getViewBox().sigResized.connect(self._update_bottom_views)

        # Link X axes together for synchronous zooming and panning
        self.plot_bottom.setXLink(self.plot_vp)

        self.curve_power = self.plot_bottom.plot(
            pen=pg.mkPen("#fbbf24", width=1.5),
            symbol="o",
            symbolSize=3,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#fbbf24"),
            name="Power (W)",
            connect="finite",
        )
        self.curve_charger_power = self.plot_bottom.plot(
            pen=pg.mkPen("#c084fc", width=1.5),
            symbol="t",
            symbolSize=3,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#c084fc"),
            name="Charger Power (W)",
            connect="finite",
        )
        self.curve_delta = pg.PlotDataItem(
            pen=pg.mkPen("#f43f5e", width=1.5),
            symbol="o",
            symbolSize=3,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#f43f5e"),
            name="Cell Delta (mV)",
            connect="finite",
        )
        self.view_delta.addItem(self.curve_delta)

        # Crosshairs
        self.v_line_top = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#cbd5e1", width=1, style=Qt.PenStyle.DashLine))
        self.v_line_bottom = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#cbd5e1", width=1, style=Qt.PenStyle.DashLine))
        self.plot_vp.addItem(self.v_line_top, ignoreBounds=True)
        self.plot_bottom.addItem(self.v_line_bottom, ignoreBounds=True)

        # Mouse hover tracking
        self.plot_vp.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot_bottom.scene().sigMouseMoved.connect(self._on_mouse_moved)

        plots_layout.addWidget(self.plot_vp, stretch=1)
        plots_layout.addWidget(self.plot_bottom, stretch=1)

        splitter.addWidget(plots_container)

        # Right Container: 20S Cell Spectrum Bar Inspector
        right_container = QWidget()
        right_container.setMinimumWidth(320)
        right_container.setMaximumWidth(420)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(8)

        # Inspector Header Card
        insp_header = QFrame()
        insp_header.setProperty("class", "kpi-card")
        insp_h_layout = QVBoxLayout(insp_header)
        insp_h_layout.setContentsMargins(10, 8, 10, 8)
        
        lbl_insp_title = QLabel("TIME-SCRUBBER CELL INSPECTOR")
        lbl_insp_title.setProperty("class", "kpi-title")
        self.lbl_scrub_time = QLabel("Hover over graph to inspect")
        self.lbl_scrub_time.setStyleSheet("font-size: 13px; font-weight: 700; color: #00e5ff; font-family: 'JetBrains Mono';")
        self.lbl_scrub_stats = QLabel("V: --.- V | I: --.- A | P: -- W | Δ: -- mV")
        self.lbl_scrub_stats.setStyleSheet("font-size: 11px; color: #94a3b8; font-family: 'JetBrains Mono';")

        insp_h_layout.addWidget(lbl_insp_title)
        insp_h_layout.addWidget(self.lbl_scrub_time)
        insp_h_layout.addWidget(self.lbl_scrub_stats)
        right_layout.addWidget(insp_header)

        # 20S Cell Bar Plot
        self.cell_bar_plot = pg.PlotWidget()
        self.cell_bar_plot.plotItem.vb.wheelEvent = lambda ev, axis=None: ev.accept()
        self.cell_bar_plot.setBackground("#0d162d")
        self.cell_bar_plot.showGrid(x=False, y=True, alpha=0.3)
        self.cell_bar_plot.setTitle("<span style='color: #00f59b; font-weight: bold; font-size: 11px;'>20S Cell Balance Spectrum</span>")
        self.cell_bar_plot.setLabel("left", "Voltage", units="V", color="#00f59b")
        self.cell_bar_plot.setLabel("bottom", "Cell # (1..20)", color="#94a3b8")
        self.cell_bar_plot.setYRange(3.6, 4.2)
        self.cell_bar_plot.setXRange(0.5, 20.5)

        self.cell_bar_item = pg.BarGraphItem(x=list(range(1, 21)), height=[3.8] * 20, width=0.7, brush="#00f59b")
        self.cell_bar_plot.addItem(self.cell_bar_item)

        right_layout.addWidget(self.cell_bar_plot, stretch=1)

        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, stretch=1)

    def _create_kpi_card(self, title: str, val: str, sub: str) -> tuple[QFrame, QLabel, QLabel]:
        card = QFrame()
        card.setProperty("class", "kpi-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setProperty("class", "kpi-title")

        lbl_val = QLabel(val)
        lbl_val.setProperty("class", "kpi-val")

        lbl_sub = QLabel(sub)
        lbl_sub.setProperty("class", "kpi-sub")

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_val)
        layout.addWidget(lbl_sub)
        return card, lbl_val, lbl_sub

    def _update_views(self):
        self.view_current.setGeometry(self.plot_vp.getViewBox().sceneBoundingRect())
        self.view_current.linkedViewChanged(self.plot_vp.getViewBox(), self.view_current.XAxis)

    def _update_bottom_views(self):
        self.view_delta.setGeometry(self.plot_bottom.getViewBox().sceneBoundingRect())
        self.view_delta.linkedViewChanged(self.plot_bottom.getViewBox(), self.view_delta.XAxis)

    def update_data(self, rows: list[dict[str, Any]]):
        """Update plots and KPI analytics with freshly fetched rows."""
        self.data = rows
        if not rows:
            self.curve_voltage.clear()
            self.curve_current.clear()
            self.curve_power.clear()
            self.curve_delta.clear()
            self.kpi_v_val.setText("--.- V")
            self.kpi_p_val.setText("-- W")
            self.kpi_delta_val.setText("-- mV")
            self.kpi_temp_val.setText("-- °C")
            return

        # Extract arrays
        timestamps_sec = np.array([r["epoch_ms"] / 1000.0 for r in rows], dtype=np.float64)
        self._timestamps = timestamps_sec
        voltages = np.array([np.nan if r.get("total_voltage") is None else float(r.get("total_voltage")) for r in rows], dtype=np.float64)
        currents = np.array([np.nan if r.get("current") is None else float(r.get("current")) for r in rows], dtype=np.float64)
        powers = np.array([np.nan if r.get("power") is None else float(r.get("power")) for r in rows], dtype=np.float64)
        deltas = np.array([np.nan if r.get("cell_delta_mv") is None else float(r.get("cell_delta_mv")) for r in rows], dtype=np.float64)

        # Plot curves
        self.curve_voltage.setData(timestamps_sec, voltages, connect="finite")
        self.curve_current.setData(timestamps_sec, currents, connect="finite")
        self.curve_power.setData(timestamps_sec, powers, connect="finite")
        self.curve_delta.setData(timestamps_sec, deltas, connect="finite")

        if len(timestamps_sec) > 1:
            t_min = float(timestamps_sec[0])
            t_max = float(timestamps_sec[-1])
            pad = max(1.0, (t_max - t_min) * 0.02)
            total_span = (t_max - t_min) + 2 * pad
            self.plot_vp.plotItem.vb.setLimits(xMin=t_min - pad, xMax=t_max + pad, minXRange=5.0, maxXRange=total_span)
            self.plot_bottom.plotItem.vb.setLimits(xMin=t_min - pad, xMax=t_max + pad, minXRange=5.0, maxXRange=total_span)

        # Auto-fit view ranges
        self.plot_vp.enableAutoRange(axis="y")
        self.view_current.enableAutoRange(axis="y")
        self.plot_bottom.enableAutoRange(axis="y")
        self.view_delta.enableAutoRange(axis="y")

        # Update KPI statistics
        latest = rows[-1]
        cur_v = latest.get("total_voltage") or 0.0
        valid_v = voltages[np.isfinite(voltages)]
        min_v = float(np.min(valid_v)) if len(valid_v) > 0 else 0.0
        max_v = float(np.max(valid_v)) if len(valid_v) > 0 else 0.0

        cur_p = latest.get("power") or 0.0
        valid_p = powers[np.isfinite(powers)]
        peak_p = float(np.max(valid_p)) if len(valid_p) > 0 else 0.0
        cur_i = latest.get("current") or 0.0

        cur_d = latest.get("cell_delta_mv") or 0
        min_cell = latest.get("cell_min_v") or 0.0
        max_cell = latest.get("cell_max_v") or 0.0

        t1 = latest.get("temp_1") or 0.0
        t2 = latest.get("temp_2") or 0.0

        self._summary = {
            "cur_v": cur_v, "min_v": min_v, "max_v": max_v,
            "cur_p": cur_p, "peak_p": peak_p, "cur_i": cur_i,
            "cur_d": cur_d, "min_cell": min_cell, "max_cell": max_cell,
            "t1": t1, "t2": t2,
        }

        self.kpi_v_val.setText(f"{cur_v:.2f} V")
        self.kpi_v_sub.setText(f"Min: {min_v:.2f}V | Max: {max_v:.2f}V")

        self.kpi_p_val.setText(f"{cur_p:.0f} W")
        self.kpi_p_sub.setText(f"Peak: {peak_p:.0f}W | Curr: {cur_i:.1f}A")

        self.kpi_delta_val.setText(f"{cur_d} mV")
        self.kpi_delta_sub.setText(f"Min: {min_cell:.3f}V | Max: {max_cell:.3f}V")

        self.kpi_temp_val.setText(f"{max(t1, t2):.1f} °C")
        self.kpi_temp_sub.setText(f"T1: {t1:.1f}°C | T2: {t2:.1f}°C")

        # Render latest cell bar spectrum
        self._render_cell_bars(latest)

    def update_charger_data(self, rows: list[dict[str, Any]]):
        """Update charger curves if charger telemetry is present in time range."""
        if not rows:
            self.curve_charger_current.clear()
            self.curve_charger_power.clear()
            return
        timestamps_sec = np.array([r["epoch_ms"] / 1000.0 for r in rows], dtype=np.float64)
        currents = np.array([np.nan if r.get("output_current") is None else float(r.get("output_current")) for r in rows], dtype=np.float64)
        powers = np.array([np.nan if r.get("output_power") is None else float(r.get("output_power")) for r in rows], dtype=np.float64)

        self.curve_charger_current.setData(timestamps_sec, currents, connect="finite")
        self.curve_charger_power.setData(timestamps_sec, powers, connect="finite")

    def _render_cell_bars(self, row: dict[str, Any]):
        cell_json = row.get("cell_voltages_json")
        if not cell_json:
            return
        try:
            cells = json.loads(cell_json)
            if not cells:
                return
            n = len(cells)
            x_vals = list(range(1, n + 1))
            min_c = min(cells)
            max_c = max(cells)

            # Color bars by voltage relative to min/max
            brushes = []
            for c in cells:
                if max_c > min_c and (max_c - c) > 0.015:
                    brushes.append(pg.mkBrush("#f59e0b"))  # amber for lower cell
                else:
                    brushes.append(pg.mkBrush("#00f59b"))  # healthy mint

            self.cell_bar_plot.removeItem(self.cell_bar_item)
            self.cell_bar_item = pg.BarGraphItem(
                x=x_vals, height=cells, width=0.72, brushes=brushes
            )
            self.cell_bar_plot.addItem(self.cell_bar_item)
            self.cell_bar_plot.setYRange(max(2.5, min_c - 0.05), min(4.4, max_c + 0.05))
            self.cell_bar_plot.setXRange(0.5, n + 0.5)
        except Exception:
            pass

    def _on_mouse_moved(self, pos):
        """Handle cursor scrubbing across plots to display hovered values."""
        if not self.data or len(self._timestamps) == 0:
            return

        mouse_point = self.plot_vp.plotItem.vb.mapSceneToView(pos)
        x_val = mouse_point.x()

        if x_val < self._timestamps[0] or x_val > self._timestamps[-1]:
            return

        # Move crosshairs
        self.v_line_top.setPos(x_val)
        self.v_line_bottom.setPos(x_val)

        # Find closest record index
        idx = int(np.searchsorted(self._timestamps, x_val))
        idx = max(0, min(len(self.data) - 1, idx))
        row = self.data[idx]

        # Update inspector label
        dt = datetime.datetime.fromtimestamp(row["epoch_ms"] / 1000.0)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        self.lbl_scrub_time.setText(time_str)
        v = row.get("total_voltage") or 0.0
        i = row.get("current") or 0.0
        p = row.get("power") or 0.0
        d = row.get("cell_delta_mv") or 0
        min_cell = row.get("cell_min_v") or 0.0
        max_cell = row.get("cell_max_v") or 0.0
        t1 = row.get("temp_1") or 0.0
        t2 = row.get("temp_2") or 0.0
        self.lbl_scrub_stats.setText(f"V: {v:.2f}V | I: {i:.1f}A | P: {p:.0f}W | Δ: {d}mV")

        # Dynamic scrubbing for header row KPI cards
        self.kpi_v_val.setText(f"{v:.2f} V")
        self.kpi_v_sub.setText(f"At: {dt.strftime('%H:%M:%S')} | Range: {self._summary.get('min_v', 0):.2f}–{self._summary.get('max_v', 0):.2f}V")

        self.kpi_p_val.setText(f"{p:.0f} W")
        self.kpi_p_sub.setText(f"Current: {i:+.1f}A | Peak: {self._summary.get('peak_p', 0):.0f}W")

        self.kpi_delta_val.setText(f"{d} mV")
        self.kpi_delta_sub.setText(f"Min: {min_cell:.3f}V | Max: {max_cell:.3f}V")

        self.kpi_temp_val.setText(f"{max(t1, t2):.1f} °C")
        self.kpi_temp_sub.setText(f"T1: {t1:.1f}°C | T2: {t2:.1f}°C")

        # Update 20S cell spectrum at this instant
        self._render_cell_bars(row)

