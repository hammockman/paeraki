"""Paeraki Vessel Telemetry Historian & Workbench (PyQt6).
Queries and visualizes the SQLite database collected on hammer.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QThreadPool, Qt
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Ensure history-gui is in sys.path
BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import db
from styles import DARK_THEME_QSS
from time_bar import TimeBar
from widgets.tab_12v import Tab12V
from widgets.tab_72v import Tab72V
from widgets.tab_explorer import TabExplorer
from widgets.tab_gps import TabGPS
from widgets.tab_packets import TabPackets
from widgets.tab_sql import TabSQL


class MainWindow(QMainWindow):
    """Main window for Paeraki Telemetry History & Analytics GUI."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Paeraki • Vessel Telemetry Historian")
        self.resize(1560, 940)
        self.setMinimumSize(1024, 680)

        self.threadpool = QThreadPool.globalInstance()
        self.start_ms = 0
        self.end_ms = 0

        self._init_ui()
        self._load_initial_bounds()

    def _init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Top Nautical Header
        header = QFrame()
        header.setObjectName("appHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(14)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_vessel = QLabel("PAERAKI")
        lbl_vessel.setObjectName("vesselTitle")
        lbl_sub = QLabel("VESSEL TELEMETRY HISTORIAN & WORKBENCH")
        lbl_sub.setObjectName("vesselSubtitle")
        title_box.addWidget(lbl_vessel)
        title_box.addWidget(lbl_sub)
        header_layout.addLayout(title_box)

        header_layout.addStretch()

        # Database Meta Badge
        db_box = QVBoxLayout()
        db_box.setSpacing(2)
        db_box.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_db_path = QLabel("DB: /home/jh/paeraki/data/paeraki.db (RO)")
        self.lbl_db_path.setObjectName("dbPathLabel")
        self.lbl_db_meta = QLabel("Connecting...")
        self.lbl_db_meta.setStyleSheet("font-size: 11px; color: #10b981; font-family: 'JetBrains Mono'; font-weight: 600;")
        db_box.addWidget(self.lbl_db_path)
        db_box.addWidget(self.lbl_db_meta)
        header_layout.addLayout(db_box)

        root_layout.addWidget(header)

        # 2. Time Control Bar
        self.time_bar = TimeBar(self)
        self.time_bar.range_changed.connect(self._on_range_changed)
        self.time_bar.refresh_requested.connect(self._refresh_current_range)
        root_layout.addWidget(self.time_bar)

        # 3. Main Navigation TabWidget
        self.tabs = QTabWidget(self)
        self.tab_explorer = TabExplorer(self)
        self.tab_72v = Tab72V(self)
        self.tab_12v = Tab12V(self)
        self.tab_gps = TabGPS(self)
        self.tab_packets = TabPackets(self)
        self.tab_sql = TabSQL(self)

        self.tabs.addTab(self.tab_explorer, "📊  Metric Explorer")
        self.tabs.addTab(self.tab_72v, "⚡  72V Propulsion")
        self.tabs.addTab(self.tab_12v, "☀  12V House & Solar")
        self.tabs.addTab(self.tab_gps, "🧭  GPS Navigation")
        self.tabs.addTab(self.tab_packets, "📦  MQTT Packets")
        self.tabs.addTab(self.tab_sql, "💻  SQL Workbench")

        self.tab_explorer.status_message.connect(self._on_explorer_status)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root_layout.addWidget(self.tabs, stretch=1)

        # 4. Status Bar
        self.status = QStatusBar(self)
        self.setStatusBar(self.status)
        self.status.showMessage("Initializing Paeraki database engine...")

    def _load_initial_bounds(self):
        """Query DB bounds asynchronously."""
        worker = db.DbQueryWorker(db.get_time_bounds)
        worker.signals.result.connect(self._on_bounds_loaded)
        worker.signals.error.connect(lambda err: self.status.showMessage(f"DB Error: {err}"))
        self.threadpool.start(worker)

    def _on_bounds_loaded(self, bounds: dict):
        min_ms = bounds["min_ms"]
        max_ms = bounds["max_ms"]
        counts = bounds.get("counts", {})
        self.time_bar.set_time_bounds(min_ms, max_ms)

        # Update DB meta label
        db_size_mb = 0.0
        if db.DB_PATH.exists():
            db_size_mb = db.DB_PATH.stat().st_size / (1024.0 * 1024.0)

        tot_packets = counts.get("packets", 0)
        tot_72v = counts.get("telemetry_72v", 0)
        tot_12v = counts.get("telemetry_12v", 0)
        tot_gps = counts.get("telemetry_gps", 0)
        tot_stng = counts.get("telemetry_seatalkng", 0)
        tot_charger = counts.get("telemetry_charger", 0)

        meta_parts = [
            f"{db_size_mb:.1f} MB",
            f"{tot_packets:,} packets",
            f"{tot_72v:,} 72V",
            f"{tot_12v:,} 12V",
            f"{tot_gps:,} GPS",
        ]
        if tot_stng:
            meta_parts.append(f"{tot_stng:,} SeaTalkNG")
        if tot_charger:
            meta_parts.append(f"{tot_charger:,} charger")

        self.lbl_db_meta.setText("  •  ".join(meta_parts))
        self.status.showMessage("Database connected in read-only mode. Loading telemetry...")
        # Trigger initial 24h range load
        self.time_bar._apply_preset("24h")

    def _on_range_changed(self, start_ms: int, end_ms: int):
        self.start_ms = start_ms
        self.end_ms = end_ms
        self._refresh_current_range()

    def _on_tab_changed(self, index: int):
        self._refresh_current_range()

    def _refresh_current_range(self):
        if not self.start_ms or not self.end_ms:
            return

        curr_tab = self.tabs.currentIndex()
        self.time_bar.set_status_text("Querying...")

        if curr_tab == 0:  # Metric Explorer
            self.tab_explorer.set_time_range(self.start_ms, self.end_ms)
        elif curr_tab == 1:  # 72V
            worker = db.DbQueryWorker(db.query_72v, self.start_ms, self.end_ms, 8000)
            worker.signals.result.connect(self._on_72v_loaded)
            self.threadpool.start(worker)

            charger_worker = db.DbQueryWorker(db.query_charger, self.start_ms, self.end_ms, 8000)
            charger_worker.signals.result.connect(self.tab_72v.update_charger_data)
            self.threadpool.start(charger_worker)
        elif curr_tab == 2:  # 12V
            worker = db.DbQueryWorker(db.query_12v, self.start_ms, self.end_ms, 8000)
            worker.signals.result.connect(self._on_12v_loaded)
            self.threadpool.start(worker)
        elif curr_tab == 3:  # GPS
            worker = db.DbQueryWorker(db.query_gps, self.start_ms, self.end_ms, 8000)
            worker.signals.result.connect(self._on_gps_loaded)
            self.threadpool.start(worker)
        elif curr_tab == 4:  # Packets
            self.tab_packets.set_time_range(self.start_ms, self.end_ms)
            self.time_bar.set_status_text("Ready")

    def _on_explorer_status(self, msg: str):
        self.status.showMessage(msg)
        self.time_bar.set_status_text(msg)

    def _on_72v_loaded(self, rows):
        self.tab_72v.update_data(rows)
        self.time_bar.set_status_text(f"72V: {len(rows):,} samples")
        self.status.showMessage(f"Loaded {len(rows):,} 72V telemetry data points")

    def _on_12v_loaded(self, rows):
        self.tab_12v.update_data(rows)
        self.time_bar.set_status_text(f"12V: {len(rows):,} samples")
        self.status.showMessage(f"Loaded {len(rows):,} 12V telemetry data points")

    def _on_gps_loaded(self, rows):
        self.tab_gps.update_data(rows)
        self.time_bar.set_status_text(f"GPS: {len(rows):,} fixes")
        self.status.showMessage(f"Loaded {len(rows):,} GPS navigation points")


def main():
    # Enable high-DPI scaling
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME_QSS)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
