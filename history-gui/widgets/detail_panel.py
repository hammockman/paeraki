"""Right-hand detail inspector panel for Paeraki Telemetry History Explorer.

Displays synchronized cursor timestamp, instantaneous values for all active metrics,
window range statistics, contextual 20S cell voltage spectrum, and GPS navigation data.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import db


class DetailPanel(QWidget):
    """Right-hand inspector panel showing real-time scrubbed telemetry values."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("detailPanel")
        self._selected_metrics: list[db.MetricDef] = []
        self._table_data: dict[str, list[dict[str, Any]]] = {}
        self._timestamps: dict[str, np.ndarray] = {}
        self._summary_stats: dict[str, dict[str, float]] = {}

        self._init_ui()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Scroll area
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("""
            QScrollArea {
                background-color: #090e1c;
                border: none;
                border-left: 1px solid #1e293b;
            }
            QScrollBar:vertical {
                background-color: #0b1329;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #1e293b;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #0284c7;
            }
        """)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(8)

        # 1. Cursor Timestamp Card
        self.card_time = QFrame()
        self.card_time.setProperty("class", "kpi-card")
        self.card_time.setStyleSheet("""
            QFrame.kpi-card {
                background-color: #0b1329;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        ct_layout = QVBoxLayout(self.card_time)
        ct_layout.setContentsMargins(10, 8, 10, 8)
        ct_layout.setSpacing(2)

        lbl_ct_title = QLabel("📍 SYNCHRONIZED CURSOR POSITION")
        lbl_ct_title.setStyleSheet("font-size: 10px; font-weight: 800; color: #94a3b8; letter-spacing: 0.8px;")
        self.lbl_time_val = QLabel("Hover over charts to inspect")
        self.lbl_time_val.setStyleSheet("font-size: 14px; font-weight: 800; color: #00e5ff; font-family: 'JetBrains Mono';")
        self.lbl_time_sub = QLabel("Move mouse across any plot")
        self.lbl_time_sub.setStyleSheet("font-size: 10px; color: #64748b;")

        ct_layout.addWidget(lbl_ct_title)
        ct_layout.addWidget(self.lbl_time_val)
        ct_layout.addWidget(self.lbl_time_sub)
        self.content_layout.addWidget(self.card_time)

        # Container for dynamically populated unit cards
        self.unit_cards_container = QWidget()
        self.unit_cards_layout = QVBoxLayout(self.unit_cards_container)
        self.unit_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.unit_cards_layout.setSpacing(8)
        self.content_layout.addWidget(self.unit_cards_container)

        # 2. Contextual 20S Cell Bar Spectrum Card
        self.card_cell = QFrame()
        self.card_cell.setProperty("class", "kpi-card")
        self.card_cell.setStyleSheet("""
            QFrame.kpi-card {
                background-color: #0b1329;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        cc_layout = QVBoxLayout(self.card_cell)
        cc_layout.setContentsMargins(8, 6, 8, 6)
        cc_layout.setSpacing(4)

        self.lbl_cell_title = QLabel("<b style='color:#00f59b; font-size:11px;'>20S CELL BALANCE SPECTRUM</b> <span style='color:#94a3b8; font-size:10px;'>Δ: -- mV</span>")
        cc_layout.addWidget(self.lbl_cell_title)

        self.cell_plot = pg.PlotWidget()
        self.cell_plot.setBackground("#0d162d")
        self.cell_plot.setMaximumHeight(100)
        self.cell_plot.setYRange(3.6, 4.3)
        self.cell_plot.setXRange(0.5, 20.5)
        self.cell_plot.showGrid(x=False, y=True, alpha=0.3)
        self.cell_plot.hideAxis("left")
        self.cell_plot.hideAxis("bottom")
        self.cell_plot.plotItem.vb.wheelEvent = lambda ev, axis=None: ev.accept()

        self.cell_bars = pg.BarGraphItem(x=list(range(1, 21)), height=[3.8] * 20, width=0.72, brush="#00f59b")
        self.cell_plot.addItem(self.cell_bars)
        cc_layout.addWidget(self.cell_plot)
        self.content_layout.addWidget(self.card_cell)

        # 3. Contextual GPS Fix Card
        self.card_gps = QFrame()
        self.card_gps.setProperty("class", "kpi-card")
        self.card_gps.setStyleSheet("""
            QFrame.kpi-card {
                background-color: #0b1329;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        cg_layout = QVBoxLayout(self.card_gps)
        cg_layout.setContentsMargins(10, 8, 10, 8)
        cg_layout.setSpacing(3)
        lbl_gps_title = QLabel("<b style='color:#38bdf8; font-size:10px;'>GNSS POSITION AT CURSOR</b>")
        self.lbl_gps_pos = QLabel("--° --' S  •  ---° --' E")
        self.lbl_gps_pos.setStyleSheet("font-family: 'JetBrains Mono'; font-size: 13px; color: #ffffff; font-weight: 700;")
        self.lbl_gps_meta = QLabel("Satellites: -- | HDOP: --")
        self.lbl_gps_meta.setStyleSheet("font-size: 10px; color: #64748b;")
        cg_layout.addWidget(lbl_gps_title)
        cg_layout.addWidget(self.lbl_gps_pos)
        cg_layout.addWidget(self.lbl_gps_meta)
        self.content_layout.addWidget(self.card_gps)

        self.content_layout.addStretch()
        self.scroll.setWidget(self.content_widget)
        root_layout.addWidget(self.scroll)

        # Map to track metric label widgets for instantaneous updates
        self._metric_val_labels: dict[str, QLabel] = {}
        self._metric_stat_labels: dict[str, QLabel] = {}

    def set_data(self, selected_ids: set[str], tables_data: dict[str, list[dict[str, Any]]]):
        """Update metrics configuration and cached table data."""
        self._selected_metrics = [db.METRIC_CATALOG[mid] for mid in selected_ids if mid in db.METRIC_CATALOG]
        self._table_data = tables_data
        self._timestamps.clear()
        self._summary_stats.clear()

        # Cache timestamps
        for tbl, rows in tables_data.items():
            if rows:
                self._timestamps[tbl] = np.array([r["epoch_ms"] / 1000.0 for r in rows], dtype=np.float64)
            else:
                self._timestamps[tbl] = np.array([], dtype=np.float64)

        # Compute summary statistics (Min, Max, Mean) for each active metric
        for m in self._selected_metrics:
            rows = tables_data.get(m.table, [])
            vals = [float(r[m.column]) for r in rows if r.get(m.column) is not None]
            if vals:
                self._summary_stats[m.id] = {
                    "min": float(np.min(vals)),
                    "max": float(np.max(vals)),
                    "mean": float(np.mean(vals)),
                    "latest": float(vals[-1]),
                }

        self._rebuild_unit_cards()

        # Toggle contextual cards
        has_72v = any(m.category_id == "72v" for m in self._selected_metrics)
        self.card_cell.setVisible(has_72v)

        has_gps = any(m.category_id in ("stng", "gps") for m in self._selected_metrics)
        self.card_gps.setVisible(has_gps)

        # Render latest cell bar if 72V is active
        if has_72v:
            rows_72 = tables_data.get("telemetry_72v", [])
            if rows_72:
                self._render_cell_bars(rows_72[-1])

    def _rebuild_unit_cards(self):
        """Group active metrics by unit and generate card widgets."""
        # Clear existing unit cards
        while self.unit_cards_layout.count():
            item = self.unit_cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._metric_val_labels.clear()
        self._metric_stat_labels.clear()

        # Group by unit
        unit_map: dict[str, list[db.MetricDef]] = {}
        for m in self._selected_metrics:
            unit_map.setdefault(m.unit, []).append(m)

        for unit, metrics in unit_map.items():
            card = QFrame()
            card.setProperty("class", "kpi-card")
            card.setStyleSheet("""
                QFrame.kpi-card {
                    background-color: #0b1329;
                    border: 1px solid #1e293b;
                    border-radius: 8px;
                    padding: 8px;
                }
            """)
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(10, 8, 10, 8)
            c_layout.setSpacing(6)

            # Section Title
            unit_title = f"{metrics[0].unit} READINGS"
            first_color = metrics[0].color
            lbl_title = QLabel(f"<b style='color:{first_color}; font-size:11px;'>⚡ {unit_title} ({unit})</b>")
            c_layout.addWidget(lbl_title)

            # Each metric row
            for m in metrics:
                row_layout = QVBoxLayout()
                row_layout.setSpacing(1)

                val_lbl = QLabel(f"<b><span style='color:{m.color};'>●</span> {m.name}:</b> <span style='color:{m.color}; font-size:14px; font-family:JetBrains Mono; font-weight:800;'>-- {m.unit}</span>")
                self._metric_val_labels[m.id] = val_lbl
                row_layout.addWidget(val_lbl)

                stats = self._summary_stats.get(m.id)
                if stats:
                    stat_text = f"Min: {stats['min']:.2f} | Max: {stats['max']:.2f} | Avg: {stats['mean']:.2f}"
                else:
                    stat_text = "No samples in range"
                stat_lbl = QLabel(stat_text)
                stat_lbl.setStyleSheet("color: #64748b; font-size: 10px; font-family: 'JetBrains Mono';")
                self._metric_stat_labels[m.id] = stat_lbl
                row_layout.addWidget(stat_lbl)

                c_layout.addLayout(row_layout)

            self.unit_cards_layout.addWidget(card)

    def update_cursor_position(self, cursor_sec: float):
        """Update instantaneous readouts across all selected metrics at cursor timestamp."""
        dt = datetime.datetime.fromtimestamp(cursor_sec)
        time_str = dt.strftime("%Y-%m-%d  %H:%M:%S  NZST")
        self.lbl_time_val.setText(time_str)

        now_sec = datetime.datetime.now().timestamp()
        delta_sec = now_sec - cursor_sec
        if delta_sec > 0:
            hrs = int(delta_sec // 3600)
            mins = int((delta_sec % 3600) // 60)
            self.lbl_time_sub.setText(f"{hrs}h {mins:02d}m ago • Timestamp {cursor_sec:.1f}s")
        else:
            self.lbl_time_sub.setText(f"Timestamp {cursor_sec:.1f}s")

        # Query nearest row for each table
        nearest_rows: dict[str, dict[str, Any]] = {}
        for tbl, t_arr in self._timestamps.items():
            rows = self._table_data.get(tbl, [])
            if not rows or t_arr is None or len(t_arr) == 0:
                continue
            idx = int(np.searchsorted(t_arr, cursor_sec))
            idx = max(0, min(len(rows) - 1, idx))
            # Check if cursor is within active table range
            if (t_arr[0] - 60.0) <= cursor_sec <= (t_arr[-1] + 60.0):
                nearest_rows[tbl] = rows[idx]

        # Update metric labels
        for m in self._selected_metrics:
            row = nearest_rows.get(m.table)
            val_lbl = self._metric_val_labels.get(m.id)
            if not val_lbl:
                continue

            if row is not None and m.column in row and row[m.column] is not None:
                val = row[m.column]
                # Format based on unit
                if m.unit in ("V", "A"):
                    val_str = f"{float(val):.2f} {m.unit}"
                elif m.unit in ("W", "count", "Ah"):
                    val_str = f"{float(val):,.0f} {m.unit}"
                elif m.unit in ("°", "°C", "kn", "hPa", "°/s"):
                    val_str = f"{float(val):.1f} {m.unit}"
                elif m.unit == "mV":
                    val_str = f"{int(val)} mV"
                else:
                    val_str = f"{val} {m.unit}"

                extra_badge = ""
                if m.id == "72v_i":
                    extra_badge = " <span style='color:#f43f5e; font-size:10px;'>[DISCHARGE]</span>" if float(val) < -0.5 else " <span style='color:#10b981; font-size:10px;'>[CHARGE]</span>" if float(val) > 0.5 else ""
                elif m.id == "12v_net_i":
                    extra_badge = " <span style='color:#10b981; font-size:10px;'>[HARVEST]</span>" if float(val) > 0.2 else ""

                val_lbl.setText(
                    f"<b><span style='color:{m.color};'>●</span> {m.name}:</b> "
                    f"<span style='color:{m.color}; font-size:14px; font-family:JetBrains Mono; font-weight:800;'>{val_str}</span>{extra_badge}"
                )
            else:
                val_lbl.setText(
                    f"<b><span style='color:{m.color};'>●</span> {m.name}:</b> "
                    f"<span style='color:#64748b; font-size:13px; font-family:JetBrains Mono;'>-- {m.unit}</span>"
                )

        # Contextual 20S Cell Spectrum
        row_72 = nearest_rows.get("telemetry_72v")
        if row_72 is not None:
            self._render_cell_bars(row_72)

        # Contextual GPS Fix
        row_gps = nearest_rows.get("telemetry_seatalkng") or nearest_rows.get("telemetry_gps")
        if row_gps is not None:
            lat = row_gps.get("latitude")
            lon = row_gps.get("longitude")
            sats = row_gps.get("satellites") or "--"
            hdop = row_gps.get("hdop") or "--"
            if lat is not None and lon is not None:
                lat_card = "S" if lat < 0 else "N"
                lon_card = "E" if lon >= 0 else "W"
                lat_deg = int(abs(lat))
                lat_min = (abs(lat) - lat_deg) * 60.0
                lon_deg = int(abs(lon))
                lon_min = (abs(lon) - lon_deg) * 60.0
                self.lbl_gps_pos.setText(f"{lat_deg:02d}°{lat_min:06.3f}' {lat_card}  •  {lon_deg:03d}°{lon_min:06.3f}' {lon_card}")
                self.lbl_gps_meta.setText(f"Satellites: {sats} | HDOP: {hdop} | Cortex GNSS")

    def _render_cell_bars(self, row: dict[str, Any]):
        """Render 20S cell balance bar heights at the current instant."""
        cell_json = row.get("cell_voltages_json")
        delta = row.get("cell_delta_mv") or 0
        min_v = row.get("cell_min_v") or 0.0
        max_v = row.get("cell_max_v") or 0.0
        self.lbl_cell_title.setText(
            f"<b style='color:#00f59b; font-size:11px;'>20S CELL BALANCE SPECTRUM</b> "
            f"<span style='color:#94a3b8; font-size:10px;'>Δ: {delta} mV | Min: {min_v:.3f}V | Max: {max_v:.3f}V</span>"
        )
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

            brushes = []
            for c in cells:
                if max_c > min_c and (max_c - c) > 0.015:
                    brushes.append(pg.mkBrush("#f59e0b"))  # lower cell
                else:
                    brushes.append(pg.mkBrush("#00f59b"))  # healthy cell

            self.cell_plot.removeItem(self.cell_bars)
            self.cell_bars = pg.BarGraphItem(x=x_vals, height=cells, width=0.72, brushes=brushes)
            self.cell_plot.addItem(self.cell_bars)
            self.cell_plot.setYRange(max(2.5, min_c - 0.05), min(4.4, max_c + 0.05))
            self.cell_plot.setXRange(0.5, n + 0.5)
        except Exception:
            pass
