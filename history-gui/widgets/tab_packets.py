"""Raw MQTT Packet Inspector tab for searching, filtering, and deeply analyzing
individual packets logged across all topics.
"""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from db import query_packets


class PacketsTableModel(QAbstractTableModel):
    """Tabular model for raw packets."""

    HEADERS = ["ID", "Time", "Topic", "Payload Preview", "Type"]

    def __init__(self, rows: list[dict[str, Any]], parent=None):
        super().__init__(parent)
        self.rows = rows

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        r = self.rows[index.row()]
        col = index.column()
        if col == 0:
            return str(r.get("id"))
        elif col == 1:
            ts = r.get("timestamp", "")
            return ts.split("T")[1][:12] if "T" in ts else ts
        elif col == 2:
            return str(r.get("topic"))
        elif col == 3:
            payload = str(r.get("payload", ""))
            return payload.replace("\n", " ")[:90] + ("..." if len(payload) > 90 else "")
        elif col == 4:
            return "JSON" if r.get("is_json") else "TXT"
        return None


class TabPackets(QWidget):
    """Raw MQTT Packet Explorer tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict[str, Any]] = []
        self._start_ms: int = 0
        self._end_ms: int = 0
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # Filter Bar
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        lbl_topic = QLabel("TOPIC:")
        lbl_topic.setStyleSheet("font-weight: 700; color: #64748b; font-size: 11px;")
        filter_layout.addWidget(lbl_topic)

        # Quick topic filters
        self.topic_btn_group = QButtonGroup(self)
        self.topic_btn_group.setExclusive(True)

        self.btn_topic_all = QPushButton("All")
        self.btn_topic_72v = QPushButton("72V")
        self.btn_topic_12v = QPushButton("12V")
        self.btn_topic_gps = QPushButton("GPS")
        self.btn_topic_charger = QPushButton("Charger")

        topics = [
            ("all", self.btn_topic_all),
            ("paeraki/72v/#", self.btn_topic_72v),
            ("paeraki/12v/#", self.btn_topic_12v),
            ("paeraki/gps/#", self.btn_topic_gps),
            ("paeraki/charger/#", self.btn_topic_charger),
        ]

        for topic_key, btn in topics:
            btn.setProperty("class", "preset-btn")
            btn.setCheckable(True)
            self.topic_btn_group.addButton(btn)
            filter_layout.addWidget(btn)
            btn.clicked.connect(lambda checked, t=topic_key: self._on_topic_filter_clicked(t))

        self.btn_topic_all.setChecked(True)
        self.active_topic = "all"

        # Search field
        filter_layout.addSpacing(10)
        self.txt_search = QLineEdit(self)
        self.txt_search.setPlaceholderText("Filter payload content...")
        self.txt_search.returnPressed.connect(self.reload_packets)
        filter_layout.addWidget(self.txt_search, stretch=1)

        self.btn_search = QPushButton("Filter")
        self.btn_search.setProperty("class", "action-btn")
        self.btn_search.clicked.connect(self.reload_packets)
        filter_layout.addWidget(self.btn_search)

        main_layout.addLayout(filter_layout)

        # Splitter: Packet list on Left, Detailed Inspector on Right
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)

        # Packet Table
        self.table_view = QTableView(self)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_view.horizontalHeader().setStretchLastSection(False)
        self.table_view.selectionModel()
        splitter.addWidget(self.table_view)

        # Detailed Inspector on Right
        insp_container = QWidget()
        insp_container.setMinimumWidth(340)
        insp_layout = QVBoxLayout(insp_container)
        insp_layout.setContentsMargins(6, 0, 0, 0)
        insp_layout.setSpacing(8)

        insp_header = QFrame()
        insp_header.setProperty("class", "kpi-card")
        insp_h_layout = QVBoxLayout(insp_header)
        insp_h_layout.setContentsMargins(10, 8, 10, 8)

        self.lbl_selected_topic = QLabel("SELECT A PACKET")
        self.lbl_selected_topic.setStyleSheet("font-size: 13px; font-weight: 700; color: #00e5ff; font-family: 'JetBrains Mono';")
        self.lbl_selected_meta = QLabel("Timestamp • Payload Size")
        self.lbl_selected_meta.setStyleSheet("font-size: 11px; color: #94a3b8; font-family: 'JetBrains Mono';")

        btn_copy = QPushButton("Copy Payload")
        btn_copy.setProperty("class", "preset-btn")
        btn_copy.clicked.connect(self._copy_payload)

        meta_row = QHBoxLayout()
        meta_row.addWidget(self.lbl_selected_meta, stretch=1)
        meta_row.addWidget(btn_copy)

        insp_h_layout.addWidget(self.lbl_selected_topic)
        insp_h_layout.addLayout(meta_row)
        insp_layout.addWidget(insp_header)

        self.payload_view = QPlainTextEdit(self)
        self.payload_view.setReadOnly(True)
        insp_layout.addWidget(self.payload_view, stretch=1)

        splitter.addWidget(insp_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, stretch=1)

        # Status row
        self.lbl_status = QLabel("Ready")
        self.lbl_status.setStyleSheet("color: #64748b; font-family: 'JetBrains Mono'; font-size: 11px;")
        main_layout.addWidget(self.lbl_status)

    def set_time_range(self, start_ms: int, end_ms: int):
        self._start_ms = start_ms
        self._end_ms = end_ms
        self.reload_packets()

    def _on_topic_filter_clicked(self, topic: str):
        self.active_topic = topic
        self.reload_packets()

    def reload_packets(self):
        if not self._start_ms or not self._end_ms:
            return

        search = self.txt_search.text().strip()
        rows, total = query_packets(
            self._start_ms,
            self._end_ms,
            topic_filter=self.active_topic,
            payload_search=search if search else None,
            limit=500,
        )
        self.rows = rows
        model = PacketsTableModel(rows, self)
        self.table_view.setModel(model)
        self.table_view.selectionModel().selectionChanged.connect(self._on_row_selected)

        # Configure column widths
        self.table_view.setColumnWidth(0, 75)
        self.table_view.setColumnWidth(1, 100)
        self.table_view.setColumnWidth(2, 170)
        self.table_view.setColumnWidth(3, 300)
        self.table_view.setColumnWidth(4, 55)

        self.lbl_status.setText(f"Showing {len(rows):,} of {total:,} matching packets")

        if rows:
            self.table_view.selectRow(0)

    def _on_row_selected(self, selected, deselected):
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            return
        row_idx = indexes[0].row()
        if 0 <= row_idx < len(self.rows):
            r = self.rows[row_idx]
            self.lbl_selected_topic.setText(r.get("topic", "--"))
            ts = r.get("timestamp", "--")
            payload = r.get("payload", "")
            self.lbl_selected_meta.setText(f"{ts} • {len(payload)} bytes")

            # Try formatting as JSON if valid
            if r.get("is_json"):
                try:
                    parsed = json.loads(payload)
                    pretty = json.dumps(parsed, indent=2)
                    self.payload_view.setPlainText(pretty)
                    return
                except Exception:
                    pass
            self.payload_view.setPlainText(payload)

    def _copy_payload(self):
        text = self.payload_view.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.lbl_status.setText("✓ Payload copied to clipboard")
