"""Interactive SQL Workbench tab for querying paeraki.db with pre-canned presets,
instant results table, and CSV export.
"""

from __future__ import annotations

import csv
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from db import execute_sql

SQL_PRESETS = [
    (
        "Recent 100 72V samples",
        "SELECT timestamp, total_voltage, current, power, rsoc, cell_delta_mv FROM telemetry_72v ORDER BY epoch_ms DESC LIMIT 100;"
    ),
    (
        "Top 50 highest propulsion power spikes",
        "SELECT timestamp, total_voltage, current, power, rsoc, cell_min_v, cell_max_v, cell_delta_mv FROM telemetry_72v WHERE power > 50 ORDER BY power DESC LIMIT 50;"
    ),
    (
        "Cell Imbalance Events (Delta >= 15 mV)",
        "SELECT timestamp, total_voltage, current, cell_min_v, cell_max_v, cell_delta_mv FROM telemetry_72v WHERE cell_delta_mv >= 15 ORDER BY epoch_ms DESC LIMIT 100;"
    ),
    (
        "12V Solar Daily Generation Summary",
        "SELECT date(timestamp) as day, max(daily_yield_kwh) as total_yield_kwh, max(solar_power) as peak_solar_w, max(solar_voltage) as max_pv_v FROM telemetry_12v GROUP BY date(timestamp) ORDER BY day DESC;"
    ),
    (
        "GPS Navigation Underway (SOG > 1.0 knot)",
        "SELECT timestamp, sog_knots, sog_kmh, cog_true, latitude, longitude, altitude_m, satellites, hdop FROM telemetry_gps WHERE sog_knots > 1.0 ORDER BY epoch_ms DESC LIMIT 200;"
    ),
    (
        "72V Charger Hunting & Current Fluctuations",
        "SELECT timestamp, state, output_voltage, output_current, target_current, output_power, temp, error_code FROM telemetry_charger WHERE output_current > 0 ORDER BY epoch_ms DESC LIMIT 200;"
    ),
    (
        "MQTT Topic Distribution (Packet Counts)",
        "SELECT topic, count(*) as count, min(timestamp) as first_seen, max(timestamp) as last_seen FROM packets GROUP BY topic ORDER BY count DESC LIMIT 50;"
    ),
]


class SqlTableModel(QAbstractTableModel):
    """Fast tabular model for SQL query results."""

    def __init__(self, columns: list[str], rows: list[list[Any]], parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows = rows

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section] if section < len(self.columns) else ""
        if orientation == Qt.Orientation.Vertical and role == Qt.ItemDataRole.DisplayRole:
            return str(section + 1)
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        val = self.rows[index.row()][index.column()]
        if val is None:
            return "NULL"
        if isinstance(val, float):
            return f"{val:.4g}"
        return str(val)


class TabSQL(QWidget):
    """SQL Query Workbench tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns: list[str] = []
        self.rows: list[list[Any]] = []
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # Top Control Row: Presets + Run Button + Export
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(10)

        lbl_presets = QLabel("PRESETS:")
        lbl_presets.setStyleSheet("font-weight: 700; color: #64748b; font-size: 11px;")
        ctrl_layout.addWidget(lbl_presets)

        self.combo_presets = QComboBox(self)
        for name, _ in SQL_PRESETS:
            self.combo_presets.addItem(name)
        self.combo_presets.currentIndexChanged.connect(self._on_preset_changed)
        ctrl_layout.addWidget(self.combo_presets, stretch=1)

        self.btn_run = QPushButton("▶ Run Query (Ctrl+Enter)")
        self.btn_run.setProperty("class", "action-btn")
        self.btn_run.clicked.connect(self.run_query)
        ctrl_layout.addWidget(self.btn_run)

        self.btn_export = QPushButton("Export CSV")
        self.btn_export.setProperty("class", "preset-btn")
        self.btn_export.clicked.connect(self.export_csv)
        ctrl_layout.addWidget(self.btn_export)

        main_layout.addLayout(ctrl_layout)

        # SQL Editor
        self.editor = QPlainTextEdit(self)
        self.editor.setPlaceholderText("Enter SQL query (e.g. SELECT * FROM telemetry_72v LIMIT 100;)...")
        self.editor.setMaximumHeight(140)
        self.editor.setPlainText(SQL_PRESETS[0][1])
        main_layout.addWidget(self.editor)

        # Keyboard Shortcut: Ctrl+Return or F5 to execute query
        self.shortcut_run = QShortcut(QKeySequence("Ctrl+Return"), self)
        self.shortcut_run.activated.connect(self.run_query)
        self.shortcut_f5 = QShortcut(QKeySequence("F5"), self)
        self.shortcut_f5.activated.connect(self.run_query)

        # Status row
        self.lbl_query_status = QLabel("Ready")
        self.lbl_query_status.setStyleSheet("color: #64748b; font-family: 'JetBrains Mono'; font-size: 11px;")
        main_layout.addWidget(self.lbl_query_status)

        # Results Table
        self.table_view = QTableView(self)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        main_layout.addWidget(self.table_view, stretch=1)

        # Run first query
        self.run_query()

    def _on_preset_changed(self, idx: int):
        if 0 <= idx < len(SQL_PRESETS):
            self.editor.setPlainText(SQL_PRESETS[idx][1])
            self.run_query()

    def run_query(self):
        query = self.editor.toPlainText().strip()
        if not query:
            return

        self.lbl_query_status.setText("Executing query...")
        try:
            cols, rows, elapsed_ms = execute_sql(query, limit=5000)
            self.columns = cols
            self.rows = rows
            model = SqlTableModel(cols, rows, self)
            self.table_view.setModel(model)
            self.lbl_query_status.setText(
                f"✓ Fetched {len(rows):,} rows ({len(cols)} columns) in {elapsed_ms:.1f} ms"
            )
            self.lbl_query_status.setStyleSheet("color: #10b981; font-family: 'JetBrains Mono';")
        except Exception as e:
            self.lbl_query_status.setText(f"✕ Query Error: {e}")
            self.lbl_query_status.setStyleSheet("color: #ef4444; font-family: 'JetBrains Mono';")

    def export_csv(self):
        if not self.rows or not self.columns:
            self.lbl_query_status.setText("Nothing to export")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Query Results as CSV", "paeraki_query_export.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self.columns)
                writer.writerows(self.rows)
            self.lbl_query_status.setText(f"✓ Exported {len(self.rows):,} rows to {path}")
            self.lbl_query_status.setStyleSheet("color: #10b981; font-family: 'JetBrains Mono';")
        except Exception as e:
            self.lbl_query_status.setText(f"✕ Export Error: {e}")
            self.lbl_query_status.setStyleSheet("color: #ef4444; font-family: 'JetBrains Mono';")
