"""Integrated 3-panel Metric Explorer tab for Paeraki Telemetry Historian.

Combines the left-hand hierarchical metric tree, center dynamic unit chart stack,
and right-hand real-time scrubbed detail inspector in a responsive 3-way QSplitter.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThreadPool, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import db
from widgets.detail_panel import DetailPanel
from widgets.metric_tree_panel import MetricTreePanel
from widgets.unit_chart_stack import UnitChartStack


class TabExplorer(QWidget):
    """Main 3-panel dynamic metric exploration workspace."""

    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tabExplorer")
        self.threadpool = QThreadPool.globalInstance()

        self.start_ms = 0
        self.end_ms = 0
        self.cached_tables: dict[str, list[dict[str, Any]]] = {}

        self._init_ui()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 3-Way Horizontal Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setHandleWidth(6)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #1e293b;
            }
            QSplitter::handle:hover {
                background-color: #0284c7;
            }
        """)

        # 1. Left Panel: Metric Tree
        initial_presets = db.PRESETS.get("72V", ["72v_v", "72v_i", "72v_p", "72v_delta"])
        self.metric_tree = MetricTreePanel(self, initial_selected=set(initial_presets))
        self.metric_tree.setMinimumWidth(240)
        self.metric_tree.setMaximumWidth(340)
        self.metric_tree.selection_changed.connect(self._on_metric_selection_changed)
        self.splitter.addWidget(self.metric_tree)

        # 2. Center Panel: Dynamic Unit Chart Stack
        self.chart_stack = UnitChartStack(self)
        self.chart_stack.cursor_moved.connect(self._on_cursor_moved)
        self.splitter.addWidget(self.chart_stack)

        # 3. Right Panel: Detail Inspector
        self.detail_panel = DetailPanel(self)
        self.detail_panel.setMinimumWidth(320)
        self.detail_panel.setMaximumWidth(420)
        self.splitter.addWidget(self.detail_panel)

        # Proportions: Left 18%, Center 57%, Right 25%
        self.splitter.setStretchFactor(0, 18)
        self.splitter.setStretchFactor(1, 57)
        self.splitter.setStretchFactor(2, 25)

        root_layout.addWidget(self.splitter)

        # Initial layout of default metrics
        self.chart_stack.update_selected_metrics(self.metric_tree.get_selected_metrics())
        self.detail_panel.set_data(self.metric_tree.get_selected_metrics(), self.cached_tables)

    def set_time_range(self, start_ms: int, end_ms: int):
        """Update active time range and refresh database data."""
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.cached_tables.clear()
        self._fetch_needed_data()

    def _on_metric_selection_changed(self, selected_ids: set[str]):
        """Handle metric selection changes in tree panel."""
        self.chart_stack.update_selected_metrics(selected_ids)
        self._fetch_needed_data()

    def _fetch_needed_data(self):
        """Determine tables required by currently selected metrics and query if not cached."""
        if not self.start_ms or not self.end_ms:
            return

        selected_ids = self.metric_tree.get_selected_metrics()
        needed_tables = {
            db.METRIC_CATALOG[mid].table
            for mid in selected_ids
            if mid in db.METRIC_CATALOG
        }

        # Check what tables are missing from cache
        missing = [t for t in needed_tables if t not in self.cached_tables]

        if not missing:
            # Everything already in cache: instantly update UI
            self.chart_stack.set_table_data(self.cached_tables)
            self.detail_panel.set_data(selected_ids, self.cached_tables)
            return

        # Fetch missing tables asynchronously
        self.status_message.emit(f"Loading data for {len(missing)} tables...")
        worker = db.DbQueryWorker(db.query_tables_batch, missing, self.start_ms, self.end_ms, 8000)
        worker.signals.result.connect(self._on_data_loaded)
        worker.signals.error.connect(lambda err: self.status_message.emit(f"DB Error: {err}"))
        self.threadpool.start(worker)

    def _on_data_loaded(self, batch_result: dict[str, list[dict[str, Any]]]):
        """Merge newly fetched table batches into cache and update charts & detail panel."""
        self.cached_tables.update(batch_result)
        selected_ids = self.metric_tree.get_selected_metrics()

        self.chart_stack.set_table_data(self.cached_tables)
        self.detail_panel.set_data(selected_ids, self.cached_tables)

        total_samples = sum(len(rows) for rows in self.cached_tables.values())
        self.status_message.emit(f"Loaded {total_samples:,} samples across {len(self.cached_tables)} telemetry tables")

    def _on_cursor_moved(self, cursor_sec: float):
        """Pass synchronized cursor position to detail panel."""
        self.detail_panel.update_cursor_position(cursor_sec)
