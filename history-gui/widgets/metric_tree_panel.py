"""Left-hand hierarchical metric tree panel for Paeraki Telemetry History Explorer.

Provides collapsible category nodes, single-click toggle with highlighted selection,
instant search filtering, and 1-click presets.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import db


class MetricTreePanel(QWidget):
    """Hierarchical metric tree panel with search and collapsible categories."""

    selection_changed = pyqtSignal(object)  # emits set[str] of selected metric IDs

    def __init__(self, parent=None, initial_selected: set[str] | None = None):
        super().__init__(parent)
        self.setObjectName("metricTreePanel")
        self._selected_ids: set[str] = set(initial_selected or ["72v_v", "72v_i", "72v_p", "72v_delta"])
        self._items_by_id: dict[str, QTreeWidgetItem] = {}
        self._cat_nodes: dict[str, QTreeWidgetItem] = {}
        self._cat_titles: dict[str, str] = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 1. Panel Header
        h_box = QHBoxLayout()
        lbl_hdr = QLabel("AVAILABLE METRICS")
        lbl_hdr.setStyleSheet("font-size: 11px; font-weight: 800; color: #00e5ff; letter-spacing: 1px;")
        h_box.addWidget(lbl_hdr)
        h_box.addStretch()

        self.lbl_active = QLabel("0 active")
        self.lbl_active.setStyleSheet("font-size: 11px; font-weight: 700; color: #10b981; font-family: 'JetBrains Mono';")
        h_box.addWidget(self.lbl_active)
        layout.addLayout(h_box)

        # 2. Search Filter Input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Filter metrics...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #111b33;
                color: #ffffff;
                border: 1px solid #233354;
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-color: #00e5ff;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input)

        # 3. 1-Click Quick Presets
        lbl_presets = QLabel("QUICK PRESETS:")
        lbl_presets.setStyleSheet("font-size: 10px; font-weight: 700; color: #64748b; margin-top: 2px;")
        layout.addWidget(lbl_presets)

        preset_row1 = QHBoxLayout()
        preset_row1.setSpacing(4)
        for name in ["72V", "12V", "Nav", "Clear"]:
            btn = QPushButton(name)
            btn.setProperty("class", "preset-pill")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #162038;
                    color: #94a3b8;
                    border: 1px solid #233354;
                    border-radius: 4px;
                    padding: 3px 6px;
                    font-size: 10px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #1e2d4f;
                    color: #00e5ff;
                    border-color: #00e5ff;
                }
            """)
            btn.clicked.connect(lambda checked, p=name: self._apply_preset(p))
            preset_row1.addWidget(btn)
        layout.addLayout(preset_row1)

        preset_row2 = QHBoxLayout()
        preset_row2.setSpacing(4)
        for name in ["All V", "All A", "All W", "Temps"]:
            btn = QPushButton(name)
            btn.setProperty("class", "preset-pill")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #162038;
                    color: #94a3b8;
                    border: 1px solid #233354;
                    border-radius: 4px;
                    padding: 3px 6px;
                    font-size: 10px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #1e2d4f;
                    color: #00e5ff;
                    border-color: #00e5ff;
                }
            """)
            btn.clicked.connect(lambda checked, p=name: self._apply_preset(p))
            preset_row2.addWidget(btn)
        layout.addLayout(preset_row2)

        # 4. Hierarchical TreeWidget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setAnimated(True)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background-color: #0a1022;
                color: #f1f5f9;
                border: none;
                font-size: 11px;
            }
            QTreeWidget::item {
                padding: 4px 6px;
                border-radius: 4px;
                margin-bottom: 2px;
                color: #cbd5e1;
            }
            QTreeWidget::item:hover {
                background-color: #162340;
                color: #ffffff;
            }
            QTreeWidget::item:selected {
                background-color: #1e3a5f;
                color: #ffffff;
            }
        """)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree, stretch=1)

        # 5. Helper Footer
        lbl_tip = QLabel("Tip: Click any metric to toggle chart")
        lbl_tip.setStyleSheet("font-size: 10px; color: #64748b; font-style: italic;")
        layout.addWidget(lbl_tip)

        self._populate_tree()
        self._update_all_visuals()

    def _populate_tree(self):
        """Populate the tree with categories and metric items from db.METRIC_CATALOG."""
        self.tree.clear()
        self._items_by_id.clear()
        self._cat_nodes.clear()
        self._cat_titles.clear()

        # Group metrics by category
        grouped: dict[str, list[db.MetricDef]] = {}
        for m in db.METRIC_CATALOG.values():
            grouped.setdefault(m.category_id, []).append(m)

        for cat_id, cat_title in db.CATEGORIES:
            cat_node = QTreeWidgetItem(self.tree, [cat_title])
            cat_node.setFont(0, QFont("Inter", 11, QFont.Weight.Bold))
            cat_node.setForeground(0, QColor("#38bdf8"))
            cat_node.setData(0, Qt.ItemDataRole.UserRole, f"CAT:{cat_id}")
            self._cat_nodes[cat_id] = cat_node
            self._cat_titles[cat_id] = cat_title

            for m in grouped.get(cat_id, []):
                item = QTreeWidgetItem(cat_node, [f"{m.name}  [{m.unit}]"])
                item.setData(0, Qt.ItemDataRole.UserRole, m.id)
                self._items_by_id[m.id] = item

            cat_node.setExpanded(True)

    def _update_all_visuals(self):
        """Update node labels, checkmarks, colors, and category badges."""
        # Update metric items
        for m_id, item in self._items_by_id.items():
            m = db.METRIC_CATALOG.get(m_id)
            if not m:
                continue
            is_sel = m_id in self._selected_ids
            if is_sel:
                item.setText(0, f"✓  ●  {m.name}  [{m.unit}]")
                item.setForeground(0, QColor("#ffffff"))
                item.setBackground(0, QColor("#1e3a5f"))
                item.setFont(0, QFont("Inter", 10, QFont.Weight.Bold))
            else:
                item.setText(0, f"    ○  {m.name}  [{m.unit}]")
                item.setForeground(0, QColor("#cbd5e1"))
                item.setBackground(0, QColor("#0a1022"))
                item.setFont(0, QFont("Inter", 10, QFont.Weight.Normal))

        # Update category badges with count of active metrics
        for cat_id, cat_node in self._cat_nodes.items():
            base_title = self._cat_titles.get(cat_id, "")
            active_count = sum(
                1 for m in db.METRIC_CATALOG.values()
                if m.category_id == cat_id and m.id in self._selected_ids
            )
            if active_count > 0:
                cat_node.setText(0, f"{base_title}  ({active_count})")
            else:
                cat_node.setText(0, base_title)

        # Update panel header label
        total_active = len(self._selected_ids)
        self.lbl_active.setText(f"{total_active} active")

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle clicking a tree node: toggle selection if metric, expand/collapse if category."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if isinstance(data, str) and data.startswith("CAT:"):
            # Category clicked: toggle expansion
            item.setExpanded(not item.isExpanded())
            return

        # Metric clicked: toggle selection
        metric_id = str(data)
        if metric_id in self._selected_ids:
            self._selected_ids.remove(metric_id)
        else:
            self._selected_ids.add(metric_id)

        self._update_all_visuals()
        self.selection_changed.emit(self._selected_ids.copy())

    def _apply_preset(self, preset_name: str):
        """Apply a named preset from db.PRESETS."""
        if preset_name == "Clear":
            self._selected_ids.clear()
        else:
            metric_ids = db.PRESETS.get(preset_name, [])
            self._selected_ids = set(metric_ids)

        self._update_all_visuals()
        self.selection_changed.emit(self._selected_ids.copy())

    def _on_search_changed(self, text: str):
        """Filter tree items based on search text."""
        query = text.strip().lower()
        if not query:
            # Show all
            for cat_node in self._cat_nodes.values():
                cat_node.setHidden(False)
                for i in range(cat_node.childCount()):
                    cat_node.child(i).setHidden(False)
            return

        for cat_id, cat_node in self._cat_nodes.items():
            cat_visible = False
            for i in range(cat_node.childCount()):
                child = cat_node.child(i)
                m_id = child.data(0, Qt.ItemDataRole.UserRole)
                m = db.METRIC_CATALOG.get(m_id)
                match = False
                if m:
                    match = (
                        query in m.name.lower()
                        or query in m.unit.lower()
                        or query in m.description.lower()
                    )
                child.setHidden(not match)
                if match:
                    cat_visible = True

            cat_node.setHidden(not cat_visible)
            if cat_visible:
                cat_node.setExpanded(True)

    def get_selected_metrics(self) -> set[str]:
        return self._selected_ids.copy()

    def set_selected_metrics(self, metric_ids: set[str]):
        self._selected_ids = set(metric_ids)
        self._update_all_visuals()
        self.selection_changed.emit(self._selected_ids.copy())
