"""12V House & Solar Subsystem tab with synchronized battery and solar generation plots.
"""

from __future__ import annotations

import datetime
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


from widgets.viewbox import TimeSeriesViewBox


class Tab12V(QWidget):
    """Interactive 12V House & Solar Subsystem visualization tab."""

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

        self.kpi_batt_card, self.kpi_batt_val, self.kpi_batt_sub = self._create_kpi_card(
            "HOUSE BATTERY", "--.- V", "Min: -- | Max: --"
        )
        self.kpi_solar_card, self.kpi_solar_val, self.kpi_solar_sub = self._create_kpi_card(
            "SOLAR GENERATION", "-- W", "Peak: -- W | Curr: -- A"
        )
        self.kpi_load_card, self.kpi_load_val, self.kpi_load_sub = self._create_kpi_card(
            "DC LOAD OUTPUT", "-- W", "Load: -- A | Today: -- kWh"
        )
        self.kpi_state_card, self.kpi_state_val, self.kpi_state_sub = self._create_kpi_card(
            "MPPT CONTROLLER", "Active", "SRNE Shiner2440"
        )

        kpi_layout.addWidget(self.kpi_batt_card)
        kpi_layout.addWidget(self.kpi_solar_card)
        kpi_layout.addWidget(self.kpi_load_card)
        kpi_layout.addWidget(self.kpi_state_card)
        main_layout.addLayout(kpi_layout)

        # ---------------- Stacked Synchronized Plots ----------------
        # 1. House Battery Voltage (V)
        self.date_axis_batt = pg.DateAxisItem(orientation="bottom")
        self.plot_batt = pg.PlotWidget(viewBox=TimeSeriesViewBox(), axisItems={"bottom": self.date_axis_batt})
        self.plot_batt.setBackground("#080c16")
        self.plot_batt.showGrid(x=True, y=True, alpha=0.25)
        self.plot_batt.setTitle("<span style='color: #38bdf8; font-weight: bold;'>House Battery Voltage (V)</span>")
        self.plot_batt.setLabel("left", "Battery Voltage", units="V", color="#38bdf8")

        self.curve_batt_v = self.plot_batt.plot(
            pen=None,
            symbol="o",
            symbolSize=4,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#38bdf8"),
            name="Battery Voltage (V)",
        )

        # 2. Solar Generation (+ve) & DC Load Power (-ve) (W)
        self.date_axis_solar = pg.DateAxisItem(orientation="bottom")
        self.plot_solar = pg.PlotWidget(viewBox=TimeSeriesViewBox(), axisItems={"bottom": self.date_axis_solar})
        self.plot_solar.setBackground("#080c16")
        self.plot_solar.showGrid(x=True, y=True, alpha=0.25)
        self.plot_solar.setTitle(
            "<span style='color: #f59e0b; font-weight: bold;'>Solar Generation (+ve, Gold) & DC Load Power (-ve, Pink) (W)</span>"
        )
        self.plot_solar.setLabel("left", "Power", units="W", color="#f59e0b")

        # Synchronize X-axis with Battery plot
        self.plot_solar.setXLink(self.plot_batt)

        # Zero reference line for power
        zero_line = pg.InfiniteLine(
            pos=0, angle=0, pen=pg.mkPen(color="#334155", width=1, style=Qt.PenStyle.DashLine)
        )
        self.plot_solar.addItem(zero_line)

        self.curve_solar_w = self.plot_solar.plot(
            pen=None,
            symbol="o",
            symbolSize=4,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#f59e0b"),
            name="Solar Power (+ve W)",
        )
        self.curve_load_w = self.plot_solar.plot(
            pen=None,
            symbol="o",
            symbolSize=4,
            symbolPen=None,
            symbolBrush=pg.mkBrush("#ec4899"),
            name="DC Load Power (-ve W)",
        )

        # Add crosshairs
        self.v_line_1 = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen("#cbd5e1", width=1, style=Qt.PenStyle.DashLine)
        )
        self.v_line_2 = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen("#cbd5e1", width=1, style=Qt.PenStyle.DashLine)
        )
        self.plot_batt.addItem(self.v_line_1, ignoreBounds=True)
        self.plot_solar.addItem(self.v_line_2, ignoreBounds=True)

        self.plot_batt.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot_solar.scene().sigMouseMoved.connect(self._on_mouse_moved)

        main_layout.addWidget(self.plot_batt, stretch=1)
        main_layout.addWidget(self.plot_solar, stretch=1)


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

    def update_data(self, rows: list[dict[str, Any]]):
        """Update 12V curves and KPIs."""
        self.data = rows
        if not rows:
            self.curve_batt_v.clear()
            self.curve_solar_w.clear()
            self.curve_load_w.clear()
            self.kpi_batt_val.setText("--.- V")
            self.kpi_solar_val.setText("-- W")
            self.kpi_load_val.setText("-- W")
            self.kpi_state_val.setText("Idle")
            return

        timestamps_sec = np.array([r["epoch_ms"] / 1000.0 for r in rows], dtype=np.float64)
        self._timestamps = timestamps_sec
        batt_v = np.array([r.get("battery_voltage") or 0.0 for r in rows], dtype=np.float64)
        solar_w = np.array([abs(r.get("solar_power") or 0.0) for r in rows], dtype=np.float64)
        load_w = np.array([-abs(r.get("load_power") or 0.0) for r in rows], dtype=np.float64)

        self.curve_batt_v.setData(timestamps_sec, batt_v)
        self.curve_solar_w.setData(timestamps_sec, solar_w)
        self.curve_load_w.setData(timestamps_sec, load_w)

        self.plot_batt.enableAutoRange(axis="y")
        self.plot_solar.enableAutoRange(axis="y")

        # Constrain zoom-out boundaries
        if len(timestamps_sec) > 1:
            t_min = float(timestamps_sec[0])
            t_max = float(timestamps_sec[-1])
            pad = max(1.0, (t_max - t_min) * 0.02)
            total_span = (t_max - t_min) + 2 * pad
            for p in (self.plot_batt, self.plot_solar):
                p.plotItem.vb.setLimits(xMin=t_min - pad, xMax=t_max + pad, minXRange=5.0, maxXRange=total_span)

        # KPI Updates & Baseline Range Summary
        latest = rows[-1]
        cur_bv = latest.get("battery_voltage") or 0.0
        cur_chg_i = latest.get("battery_charge_current") or 0.0
        min_bv = np.min(batt_v)
        max_bv = np.max(batt_v)

        cur_sw = latest.get("solar_power") or 0.0
        peak_sw = np.max(solar_w)
        cur_sa = latest.get("solar_current") or 0.0
        cur_sv = latest.get("solar_voltage") or 0.0

        cur_lw = latest.get("load_power") or 0.0
        cur_li = latest.get("load_current") or 0.0
        cur_lkwh = latest.get("daily_load_kwh") or 0.0

        status = latest.get("charging_status") or "Active"
        ctrl_t = latest.get("controller_temp")
        batt_t = latest.get("battery_temp")
        temp_str = f"Ctrl: {ctrl_t:.0f}°C | Batt: {batt_t:.0f}°C" if (ctrl_t is not None and batt_t is not None) else "SRNE Shiner2440"

        self._summary = {
            "cur_bv": cur_bv, "cur_chg_i": cur_chg_i, "min_bv": min_bv, "max_bv": max_bv,
            "cur_sw": cur_sw, "peak_sw": peak_sw, "cur_sa": cur_sa, "cur_sv": cur_sv,
            "cur_lw": cur_lw, "cur_li": cur_li, "cur_lkwh": cur_lkwh,
            "status": status, "temp_str": temp_str
        }

        self.kpi_batt_val.setText(f"{cur_bv:.2f} V")
        self.kpi_batt_sub.setText(f"Charge: {cur_chg_i:+.2f}A | Range: {min_bv:.2f}–{max_bv:.2f}V")
        self.kpi_solar_val.setText(f"{cur_sw:.0f} W")
        self.kpi_solar_sub.setText(f"PV: {cur_sv:.1f}V @ {cur_sa:.2f}A | Peak: {peak_sw:.0f}W")
        self.kpi_load_val.setText(f"{cur_lw:.0f} W")
        self.kpi_load_sub.setText(f"Draw: {cur_li:.2f}A | Today: {cur_lkwh:.3f} kWh")
        self.kpi_state_val.setText(status)
        self.kpi_state_sub.setText(temp_str)

    def _on_mouse_moved(self, pos):
        if not self.data or len(self._timestamps) == 0:
            return
        mouse_point = self.plot_batt.plotItem.vb.mapSceneToView(pos)
        x_val = mouse_point.x()
        if x_val < self._timestamps[0] or x_val > self._timestamps[-1]:
            return
        self.v_line_1.setPos(x_val)
        self.v_line_2.setPos(x_val)

        # Dynamic scrubbing for 12V header cards
        idx = int(np.searchsorted(self._timestamps, x_val))
        idx = max(0, min(len(self.data) - 1, idx))
        row = self.data[idx]

        dt = datetime.datetime.fromtimestamp(row["epoch_ms"] / 1000.0)
        bv = row.get("battery_voltage") or 0.0
        bi = row.get("battery_charge_current") or 0.0
        sw = row.get("solar_power") or 0.0
        sv = row.get("solar_voltage") or 0.0
        sa = row.get("solar_current") or 0.0
        lw = row.get("load_power") or 0.0
        li = row.get("load_current") or 0.0
        status = row.get("charging_status") or "Active"
        ctrl_t = row.get("controller_temp")
        batt_t = row.get("battery_temp")

        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        self.kpi_batt_val.setText(f"{bv:.2f} V")
        self.kpi_batt_sub.setText(f"At: {time_str} | Chg: {bi:+.2f}A")

        self.kpi_solar_val.setText(f"{sw:.0f} W")
        self.kpi_solar_sub.setText(f"PV: {sv:.1f}V @ {sa:.2f}A | Peak: {self._summary.get('peak_sw', 0):.0f}W")

        self.kpi_load_val.setText(f"{lw:.0f} W")
        self.kpi_load_sub.setText(f"Draw: {li:.2f}A")

        temp_info = f"Ctrl: {ctrl_t:.0f}°C | Batt: {batt_t:.0f}°C" if (ctrl_t is not None and batt_t is not None) else status
        self.kpi_state_val.setText(status)
        self.kpi_state_sub.setText(temp_info)


