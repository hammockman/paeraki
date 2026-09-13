"""Time range control bar for Paeraki History GUI.
Provides quick presets (1h, 6h, 24h, 7d, All), custom datetime pickers, and live auto-refresh.
"""

import time
from datetime import datetime, timedelta

from PyQt6.QtCore import QDateTime, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)


class TimeBar(QWidget):
    """Top bar containing time range controls, presets, and auto-refresh."""

    range_changed = pyqtSignal("qint64", "qint64")  # start_epoch_ms, end_epoch_ms
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeBar")
        self._active_preset = "24h"
        self._init_ui()

        # Timer for live auto-refresh
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._on_timer_tick)

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        # Quick Range Presets
        lbl_presets = QLabel("RANGE:")
        lbl_presets.setStyleSheet("font-weight: 700; color: #64748b; font-size: 11px;")
        layout.addWidget(lbl_presets)

        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)

        self.btn_1h = QPushButton("1h")
        self.btn_6h = QPushButton("6h")
        self.btn_24h = QPushButton("24h")
        self.btn_7d = QPushButton("7d")
        self.btn_all = QPushButton("All")

        self.preset_btns = {
            "1h": self.btn_1h,
            "6h": self.btn_6h,
            "24h": self.btn_24h,
            "7d": self.btn_7d,
            "all": self.btn_all,
        }

        for key, btn in self.preset_btns.items():
            btn.setProperty("class", "preset-btn")
            btn.setCheckable(True)
            self.preset_group.addButton(btn)
            layout.addWidget(btn)
            btn.clicked.connect(lambda checked, k=key: self._on_preset_clicked(k))

        self.btn_24h.setChecked(True)

        layout.addSpacing(12)

        # Custom Start DateTime
        lbl_from = QLabel("FROM:")
        lbl_from.setStyleSheet("font-weight: 700; color: #64748b; font-size: 11px;")
        layout.addWidget(lbl_from)

        self.dt_start = QDateTimeEdit(self)
        self.dt_start.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_start.setCalendarPopup(True)
        layout.addWidget(self.dt_start)

        lbl_to = QLabel("TO:")
        lbl_to.setStyleSheet("font-weight: 700; color: #64748b; font-size: 11px;")
        layout.addWidget(lbl_to)

        self.dt_end = QDateTimeEdit(self)
        self.dt_end.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_end.setCalendarPopup(True)
        layout.addWidget(self.dt_end)

        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setProperty("class", "action-btn")
        self.btn_apply.clicked.connect(self._on_custom_apply)
        layout.addWidget(self.btn_apply)

        layout.addSpacing(16)

        # Live Auto-Refresh
        self.chk_live = QCheckBox("Live Refresh")
        self.chk_live.toggled.connect(self._on_live_toggled)
        layout.addWidget(self.chk_live)

        self.combo_interval = QComboBox(self)
        self.combo_interval.addItems(["2s", "5s", "10s", "30s"])
        self.combo_interval.setCurrentText("5s")
        self.combo_interval.currentTextChanged.connect(self._on_interval_changed)
        layout.addWidget(self.combo_interval)

        layout.addStretch()

        # Row count / status indicator
        self.lbl_status = QLabel("Ready")
        self.lbl_status.setStyleSheet("color: #00e5ff; font-family: 'JetBrains Mono'; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # Initialize to 24h
        self._apply_preset("24h")

    def set_time_bounds(self, min_ms: int, max_ms: int):
        """Configure bounds based on database contents."""
        dt_min = QDateTime.fromMSecsSinceEpoch(min_ms)
        dt_max = QDateTime.fromMSecsSinceEpoch(max_ms)
        self.dt_start.setMinimumDateTime(dt_min)
        self.dt_start.setMaximumDateTime(dt_max.addDays(1))
        self.dt_end.setMinimumDateTime(dt_min)
        self.dt_end.setMaximumDateTime(dt_max.addDays(1))

    def _on_preset_clicked(self, preset_key: str):
        self._active_preset = preset_key
        self._apply_preset(preset_key)

    def _apply_preset(self, preset_key: str):
        now = datetime.now()
        if preset_key == "1h":
            start = now - timedelta(hours=1)
        elif preset_key == "6h":
            start = now - timedelta(hours=6)
        elif preset_key == "24h":
            start = now - timedelta(hours=24)
        elif preset_key == "7d":
            start = now - timedelta(days=7)
        elif preset_key == "all":
            start = datetime(2020, 1, 1)
        else:
            start = now - timedelta(hours=24)

        self.dt_start.setDateTime(QDateTime.fromSecsSinceEpoch(int(start.timestamp())))
        self.dt_end.setDateTime(QDateTime.fromSecsSinceEpoch(int(now.timestamp()) + 60))

        start_ms = int(start.timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000) + 60000
        self.range_changed.emit(start_ms, end_ms)

    def _on_custom_apply(self):
        self._active_preset = None
        for btn in self.preset_btns.values():
            btn.setChecked(False)
        start_ms = self.dt_start.dateTime().toMSecsSinceEpoch()
        end_ms = self.dt_end.dateTime().toMSecsSinceEpoch()
        self.range_changed.emit(start_ms, end_ms)

    def _on_live_toggled(self, enabled: bool):
        if enabled:
            self._update_timer_interval()
            self.refresh_timer.start()
            self.lbl_status.setText("● LIVE STREAM")
            self.lbl_status.setStyleSheet("color: #10b981; font-weight: 700; font-family: 'JetBrains Mono';")
        else:
            self.refresh_timer.stop()
            self.lbl_status.setText("PAUSED")
            self.lbl_status.setStyleSheet("color: #64748b; font-family: 'JetBrains Mono';")

    def _on_interval_changed(self):
        if self.chk_live.isChecked():
            self._update_timer_interval()

    def _update_timer_interval(self):
        text = self.combo_interval.currentText()
        seconds = int(text.replace("s", ""))
        self.refresh_timer.setInterval(seconds * 1000)

    def _on_timer_tick(self):
        if self._active_preset and self._active_preset != "all":
            # Slide window forward to now
            self._apply_preset(self._active_preset)
        else:
            self.refresh_requested.emit()

    def set_status_text(self, text: str):
        self.lbl_status.setText(text)
