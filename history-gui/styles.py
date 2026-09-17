"""Nautical Dark theme stylesheet and color constants for Paeraki History GUI.
"""

DARK_THEME_QSS = """
/* ================= Base Application ================= */
QMainWindow, QWidget {
    background-color: #080c16;
    color: #f1f5f9;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 13px;
}

/* ================= Top App Header ================= */
#appHeader {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0a1124, stop:1 #0e1a38);
    border-bottom: 1px solid #1e293b;
    padding: 10px 16px;
}

#vesselTitle {
    color: #ffffff;
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 1.5px;
}

#vesselSubtitle {
    color: #00e5ff;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}

#dbPathLabel {
    color: #64748b;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
}

/* ================= Time Control Bar ================= */
#timeBar {
    background-color: #0b1329;
    border-bottom: 1px solid #1e293b;
    padding: 8px 16px;
}

QPushButton.preset-btn {
    background-color: #162038;
    color: #94a3b8;
    border: 1px solid #233354;
    border-radius: 6px;
    padding: 5px 12px;
    font-weight: 600;
    font-size: 12px;
}

QPushButton.preset-btn:hover {
    background-color: #1e2d4f;
    color: #00e5ff;
    border-color: #00e5ff;
}

QPushButton.preset-btn:checked, QPushButton.preset-btn.active {
    background-color: #0284c7;
    color: #ffffff;
    border-color: #38bdf8;
}

QDateTimeEdit {
    background-color: #111b33;
    color: #f8fafc;
    border: 1px solid #233354;
    border-radius: 6px;
    padding: 4px 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
}

QDateTimeEdit:focus {
    border-color: #00e5ff;
}

QPushButton.action-btn {
    background-color: #0284c7;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 700;
}

QPushButton.action-btn:hover {
    background-color: #0369a1;
}

QPushButton.action-btn:pressed {
    background-color: #075985;
}

QCheckBox {
    color: #cbd5e1;
    font-weight: 500;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #334155;
    background-color: #0f172a;
}

QCheckBox::indicator:checked {
    background-color: #10b981;
    border-color: #10b981;
}

/* ================= Tab Widget ================= */
QTabWidget::pane {
    border: none;
    background-color: #080c16;
}

QTabBar::tab {
    background-color: #0b1329;
    color: #94a3b8;
    padding: 10px 22px;
    border-bottom: 2px solid transparent;
    font-weight: 600;
    font-size: 13px;
    margin-right: 4px;
}

QTabBar::tab:hover {
    color: #f1f5f9;
    background-color: #111d3d;
}

QTabBar::tab:selected {
    color: #00e5ff;
    border-bottom: 2px solid #00e5ff;
    background-color: #0e1a38;
}

/* ================= KPI Summary Cards ================= */
QFrame.kpi-card {
    background-color: #0d162d;
    border: 1px solid #1e2c4d;
    border-radius: 8px;
    padding: 10px 14px;
}

QLabel.kpi-title {
    color: #64748b;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
}

QLabel.kpi-val {
    color: #ffffff;
    font-size: 20px;
    font-weight: 800;
    font-family: 'JetBrains Mono', monospace;
}

QLabel.kpi-sub {
    color: #94a3b8;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
}

/* ================= Tables & Inspectors ================= */
QTableView, QTableWidget {
    background-color: #0b1329;
    alternate-background-color: #0f1a36;
    gridline-color: #1a2744;
    border: 1px solid #1e293b;
    border-radius: 6px;
    color: #e2e8f0;
    selection-background-color: #0369a1;
    selection-color: #ffffff;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
}

QHeaderView::section {
    background-color: #0e172e;
    color: #94a3b8;
    border: none;
    border-bottom: 1px solid #1e293b;
    border-right: 1px solid #1a2744;
    padding: 6px 10px;
    font-weight: 700;
    font-size: 11px;
}

/* ================= Editor & Inputs ================= */
QPlainTextEdit, QTextEdit, QLineEdit {
    background-color: #0b1329;
    color: #f8fafc;
    border: 1px solid #1e2c4d;
    border-radius: 6px;
    padding: 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    selection-background-color: #0284c7;
}

QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus {
    border-color: #00e5ff;
}

QComboBox {
    background-color: #111b33;
    color: #f8fafc;
    border: 1px solid #233354;
    border-radius: 6px;
    padding: 5px 10px;
    font-weight: 500;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #0d162d;
    color: #f1f5f9;
    selection-background-color: #0284c7;
    border: 1px solid #1e2c4d;
}

/* ================= Scrollbars ================= */
QScrollBar:vertical {
    border: none;
    background: #080c16;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #1e293b;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #334155;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: #080c16;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: #1e293b;
    min-width: 20px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background: #334155;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ================= Status Bar ================= */
QStatusBar {
    background-color: #070a12;
    color: #64748b;
    border-top: 1px solid #141f36;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
}

/* ================= 3-Panel Telemetry Explorer ================= */
#metricTreePanel {
    background-color: #0a1022;
    border-right: 1px solid #1e293b;
}

#detailPanel {
    background-color: #090e1c;
    border-left: 1px solid #1e293b;
}

QSplitter::handle {
    background-color: #141f36;
}

QSplitter::handle:hover {
    background-color: #0284c7;
}

QTreeWidget::item:selected {
    background-color: #1e3a5f;
    color: #ffffff;
}
"""
