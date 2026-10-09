"""Dockable workspace focused on Document and Field managers."""
from __future__ import annotations

import copy
import json
import re
from html import escape
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDockWidget, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QDoubleSpinBox,
    QSplitter, QTabBar, QTabWidget, QTextEdit, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .session import PackageSession, read_json
from .diagnostics import ConditionDiagnostics
from .clauses import ClauseComposer
from .authoring import AuthoringActions
from .data_queries import DataQueries
from .package_responses import PackageResponses
from .package_documents import PackageDocumentTree
from .clause_completion import ClauseComposeEdit
from .dialog_placement import DialogPlacement
from .grids import configure_grid

ROLE = Qt.ItemDataRole.UserRole
BLUE = "#0057d9"
RED = "#c52323"


def color_item(item, state):
    if state is not None:
        for column in range(item.columnCount()):
            item.setForeground(column, QColor(BLUE if state else RED))


class DiagnosticBox(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMinimumHeight(110)

    def show_diagnostic(self, node):
        lines = []
        def render(record, depth=0):
            state = record.get("passed")
            color = BLUE if state else RED if state is not None else "inherit"
            status = "PASS" if state else "FAIL" if state is not None else ""
            lines.append(f'<div style="margin-left:{depth * 12}px;color:{color};margin-top:5px">'
                         f'<b>{status}</b> {escape(str(record.get("label", "")))}</div>')
            for detail in record.get("details", []):
                lines.append(f'<div style="margin-left:{depth * 12 + 12}px">{escape(str(detail))}</div>')
            for child in record.get("children", []):
                render(child, depth + 1)
        render(node)
        self.setHtml("".join(lines))


def pretty(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def text_box() -> QPlainTextEdit:
    box = QPlainTextEdit()
    box.setReadOnly(True)
    box.setMinimumHeight(55)
    return box


def line_box() -> QLineEdit:
    box = QLineEdit()
    box.setReadOnly(True)
    return box


def table(headers: list[str], tree_class=QTreeWidget) -> QTreeWidget:
    tree = tree_class()
    tree.setHeaderLabels(headers)
    tree.setAlternatingRowColors(True)
    tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    tree.setUniformRowHeights(True)
    tree.setRootIsDecorated(False)
    configure_grid(tree)
    tree.setColumnWidth(0, 260)
    tree.setMinimumSize(200, 120)
    return tree


def diagnostic_tree(tree, node):
    """Show clause names as leaves; expand only unnamed condition branches."""
    tree.clear()
    def add(parent, record):
        state = record.get("passed")
        item = QTreeWidgetItem([str(record.get("clause_name") or record.get("label", "")),
                               "PASS" if state else "FAIL" if state is not None else "—"])
        item.setToolTip(0, "\n".join(record.get("details", [])))
        color_item(item, state)
        if parent is None:
            tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        if not record.get('clause_name'):
            for child in record.get("children", []):
                add(item, child)
    add(None, node)
    tree.expandAll()


def condition_details(session, expression):
    evaluator = ConditionDiagnostics(session.fields)
    try:
        resolved = evaluator._resolve_clause_expression_text_from_entries(session.clauses, expression)
    except ValueError as error:
        return {"label": expression, "passed": False if session.mapped else None,
                "details": [str(error)]}
    result = evaluator.explain(resolved, session.data, session.clauses)
    if not session.mapped:
        def neutral(node):
            node["passed"] = None
            node["details"] = ["Map JSON data to evaluate this clause."]
            for child in node.get("children", []):
                neutral(child)
        neutral(result)
    return result


class ManagerPanel(QWidget):
    selected = Signal(object)

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.source_changed = lambda source: False
        self.session: PackageSession | None = None
        self.mapping_token = None
        self.hierarchy = False
        self.field_view = "name"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name, description, or " + ("condition…" if kind == "documents" else "path…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        self.clear_filter = QPushButton('Clear')
        self.clear_filter.clicked.connect(self.search.clear)
        search_row.addWidget(self.clear_filter)
        layout.addLayout(search_row)
        self.matched_only = QCheckBox("Matched documents only" if kind == "documents" else "Fields with values only")
        self.matched_only.setEnabled(False)
        self.matched_only.toggled.connect(self.apply_filter)
        layout.addWidget(self.matched_only)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        headers = ["Document", "Order", "AT / Pkg", "Match"] if kind == "documents" else ["Field", "Value", "Required"]
        self.tree = table(headers, PackageDocumentTree if kind == "documents" else QTreeWidget)
        if kind == "documents":
            self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSortingEnabled(kind != "documents")
        if kind != "documents":
            self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        else:
            self.tree.setColumnWidth(1, 60)
            self.tree.setColumnWidth(2, 72)
            self.tree.setColumnWidth(3, 45)
        if kind == 'fields':
            controls = QHBoxLayout()
            self.field_view_toggle = QPushButton('View: Path')
            self.field_view_toggle.clicked.connect(self.toggle_field_view)
            controls.addWidget(self.field_view_toggle)
            for title, callback in (('Collapse All', self.tree.collapseAll), ('Expand All', self.tree.expandAll)):
                button = QPushButton(title)
                button.clicked.connect(callback)
                controls.addWidget(button)
            layout.insertLayout(1, controls)
        self.tree.currentItemChanged.connect(self.show_details)
        self.splitter.addWidget(self.tree)
        details = QWidget()
        form = QFormLayout(details)
        form.setContentsMargins(0, 10, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.name = line_box()
        self.description = text_box()
        self.expression = text_box()
        self.result = DiagnosticBox() if kind == "documents" else text_box()
        if kind == "documents":
            self.description.setMaximumHeight(60)
            self.expression.setMaximumHeight(65)
            self.result.setMinimumHeight(170)
        form.addRow("Name", self.name)
        form.addRow("Description", self.description)
        if kind == "documents":
            self.package_status = line_box()
            self.always_trigger = QCheckBox("Always trigger")
            self.always_trigger.setEnabled(False)
            form.addRow("Package", self.package_status)
            form.addRow("", self.always_trigger)
            self.clauses_tree = table(["Clause / Condition", "Match"])
            self.clauses_tree.setRootIsDecorated(True)
            self.clauses_tree.header().setStretchLastSection(False)
            self.clauses_tree.setColumnWidth(1, 65)
            form.addRow(QLabel("Clauses"))
            form.addRow(self.clauses_tree)
            self.tabs = QTabWidget()
            self.tabs.addTab(details, "Properties")
            self.source = text_box()
            self.tabs.addTab(self.source, "Source JSON")
            self.tabs.addTab(self.result, "Match Details")
        else:
            form.addRow("Field path", self.expression)
        if kind == "fields":
            self.true_path = line_box()
            form.addRow("Mapping path", self.true_path)
            self.path_hierarchy = line_box()
            form.addRow("Hierarchy", self.path_hierarchy)
            form.addRow("Mapped values", self.result)
        self.splitter.addWidget(self.tabs if kind == "documents" else details)
        self.splitter.setSizes([360, 300])
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        self.count = QLabel("Open a package to begin")
        layout.addWidget(self.count)

    def records(self) -> list[dict]:
        if self.session is None:
            return []
        return self.session.documents if self.kind == "documents" else self.session.fields

    def items(self):
        def walk(item):
            if item.data(0, ROLE) is not None:
                yield item
            for index in range(item.childCount()):
                yield from walk(item.child(index))
        for index in range(self.tree.topLevelItemCount()):
            yield from walk(self.tree.topLevelItem(index))

    def toggle_field_view(self):
        self.field_view = 'path' if self.field_view == 'name' else 'name'
        self.field_view_toggle.setText('View: Name' if self.field_view == 'path' else 'View: Path')
        self.tree.setRootIsDecorated(self.field_view == 'path')
        if self.session:
            self.set_session(self.session, preserve_selection=True)

    def set_hierarchy(self, enabled):
        if self.kind != 'documents' or self.hierarchy == bool(enabled):
            return
        self.hierarchy = bool(enabled)
        self.tree.setRootIsDecorated(self.hierarchy)
        if self.session:
            self.set_session(self.session, preserve_selection=True)

    def set_session(self, session: PackageSession, *, preserve_selection: bool = False):
        current = self.tree.currentItem()
        previous = current.data(0, ROLE) if current and preserve_selection else 0
        self.session = session
        self.matched_only.setEnabled(session.mapped)
        token = (id(session), session.mapping_revision)
        self.matched_only.blockSignals(True)
        if not session.mapped or (self.kind == "documents" and token != self.mapping_token):
            self.matched_only.setChecked(session.mapped)
        self.matched_only.blockSignals(False)
        self.mapping_token = token
        self.tree.blockSignals(True)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        path_nodes = {}
        for index, record in enumerate(self.records()):
            if self.kind == "documents":
                match = "PASS" if record.get("triggered") else "FAIL"
                membership = ("Missing AT" if not record.get("in_at", True) else "AT only" if record.get("associated") is False
                              else "In both" if record.get("associated") else "Unknown")
                columns = [record["name"], str(record["order"]) if record.get("order") is not None else "—",
                           membership, match if session.mapped else "—"]
            else:
                values = record.get("mapped_values", [])
                preview = " ".join(json.dumps(values, ensure_ascii=False).split()) if session.mapped else "—"
                columns = [record["name"], preview[:120], "Yes" if record["mandatory"] else "No"]
            label = record['name']
            if self.kind == 'fields' and session.mapped and len(record.get('mapped_values', [])) > 1:
                label += f" x{len(record['mapped_values'])}"
            if record.get('in_at', True) and self.source_changed(record['source']):
                label += ' *'
            columns[0] = label
            item = QTreeWidgetItem(columns)
            item.setData(0, ROLE + 4, record['name'])
            item.setData(0, ROLE, index)
            if self.kind == "documents":
                item.setData(0, ROLE + 3, bool(record.get("associated") and session.bundle))
            item.setToolTip(0, record.get("descr", ""))
            state = (record.get("triggered") if self.kind == "documents" else bool(record.get("mapped_values"))) if session.mapped else None
            if self.kind == "documents" and record.get("associated") is False:
                state = False
            if self.kind == "fields" and not session.mapped:
                state = bool(record["mandatory"])
            color_item(item, state)
            if self.kind == "documents":
                item.setToolTip(2, record.get("status", ""))
                if not record.get("in_at", True):
                    item.setForeground(2, QColor(RED))
            if self.kind == "fields":
                item.setToolTip(1, pretty(record.get("mapped_values", [])) if session.mapped else "Map data to inspect values")
            parent = None
            if self.kind == 'fields' and self.field_view == 'path':
                for path_part in DataQueries._path_to_segments(record.get('true_path') or record['path']):
                    group_key = (id(parent), str(path_part))
                    if group_key not in path_nodes:
                        group = QTreeWidgetItem([str(path_part)])
                        if parent:
                            parent.addChild(group)
                        else:
                            self.tree.addTopLevelItem(group)
                        group.setExpanded(True)
                        path_nodes[group_key] = group
                    parent = path_nodes[group_key]
            if parent:
                parent.addChild(item)
            else:
                self.tree.addTopLevelItem(item)
        if self.kind == 'documents' and self.hierarchy:
            by_name = {item.data(0, ROLE + 4): item for item in self.items()}
            for name, item in by_name.items():
                prefix = name
                while '_' in prefix:
                    prefix = prefix.rsplit('_', 1)[0]
                    if prefix in by_name:
                        index = self.tree.indexOfTopLevelItem(item)
                        by_name[prefix].addChild(self.tree.takeTopLevelItem(index))
                        break
            self.tree.collapseAll()
        self.tree.setSortingEnabled(self.kind == "fields" and self.field_view == "name")
        if hasattr(self.tree, '_grid_user_sort'):
            self.tree.setSortingEnabled(True)
            self.tree.sortByColumn(*self.tree._grid_user_sort)
        self.tree.blockSignals(False)
        self.apply_filter()
        for item in self.items():
            if item.data(0, ROLE) == previous and not item.isHidden():
                self.tree.setCurrentItem(item)
                break
        self.show_details(self.tree.currentItem())

    def apply_filter(self, *_):
        query = self.search.text().casefold().strip()
        visible = []
        if self.kind == 'fields' and self.field_view == 'path':
            def hide_groups(item):
                if item.data(0, ROLE) is None:
                    item.setHidden(True)
                for index in range(item.childCount()):
                    hide_groups(item.child(index))
            for index in range(self.tree.topLevelItemCount()):
                hide_groups(self.tree.topLevelItem(index))
        for item in self.items():
            record = self.records()[item.data(0, ROLE)]
            haystack = " ".join(str(record.get(key, "")) for key in ("name", "descr", "condition", "path", "status"))
            has_result = record.get("triggered") if self.kind == "documents" else bool(record.get("mapped_values"))
            hidden = not PackageResponses()._fuzzy_text_match(query, haystack) or (self.matched_only.isChecked() and not has_result)
            item.setHidden(hidden)
            if not hidden:
                visible.append(item)
        for item in visible:
            parent = item.parent()
            while parent:
                parent.setHidden(False)
                if query:
                    parent.setExpanded(True)
                parent = parent.parent()
        current = self.tree.currentItem()
        if not current or current.isHidden():
            self.tree.setCurrentItem(visible[0] if visible else None)
            self.show_details(self.tree.currentItem())
        self.count.setText(f"{len(visible)} of {len(self.records())} {self.kind}")

    def show_details(self, current, *_):
        if current is None or current.data(0, ROLE) is None:
            for box in (self.name, self.description, self.expression, self.result):
                box.clear()
            if self.kind == "fields":
                self.true_path.clear()
                self.path_hierarchy.clear()
            else:
                self.package_status.clear()
                self.always_trigger.setChecked(False)
                self.clauses_tree.clear()
                self.source.clear()
            self.selected.emit(None)
            return
        record = self.records()[current.data(0, ROLE)]
        self.name.setText(record["name"])
        self.description.setPlainText(record.get("descr", ""))
        self.expression.setPlainText(record.get("condition", "") if self.kind == "documents" else record["path"])
        if self.kind == "fields":
            self.true_path.setText(record["true_path"])
            self.path_hierarchy.setText(" > ".join(DataQueries._path_to_segments(record["true_path"])))
            result = pretty(record.get("mapped_values", [])) if self.session.mapped else "Map a JSON data file to inspect values."
        else:
            self.package_status.setText(f"{self.session.name} · {record.get('status', '')}")
            self.package_status.setCursorPosition(0)
            self.package_status.setToolTip(record.get("status", ""))
            self.always_trigger.setChecked(record.get("always_trigger", False))
            self.result.show_diagnostic(self.session.document_details(record))
            self.source.setPlainText(pretty({"Condition": record["source"].get("Condition")}))
            diagnostic_tree(self.clauses_tree, condition_details(self.session, record.get("condition", "")))
            if not record.get("in_at", True):
                self.clauses_tree.clear()
                self.source.setPlainText("No source condition: document is missing from the Assembly Template.")
            self.selected.emit(record)
            return
        self.result.setPlainText(result)
        self.result.setStyleSheet(f"color: {BLUE if record.get('mapped_values') else RED}" if self.session.mapped else "")
        self.selected.emit(record)


class LayoutTree(QTreeWidget):
    empty_message = 'Select a document to inspect its layouts'

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.topLevelItemCount() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(self.palette().color(QPalette.ColorRole.Text))
            painter.drawText(self.viewport().rect().adjusted(8, 8, -8, -8),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                             self.empty_message)
            painter.end()


class LayoutPanel(QWidget):
    details_ready = Signal(object)
    """Document-linked layout hierarchy and editable properties."""

    def __init__(self):
        super().__init__()
        self.document_name = ""
        self.source_changed = lambda source: False
        self.session = None
        self.mapping_token = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter layouts, content, iterations, or fields…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        controls.addWidget(self.search, 1)
        self.toggle_tree = QPushButton('📂')
        self.toggle_tree.setToolTip('Expand or collapse the full layout tree.')
        self.toggle_tree.clicked.connect(self.toggle_tree_expansion)
        controls.addWidget(self.toggle_tree)
        layout.addLayout(controls)
        self.matched_only = QCheckBox("Matched Only")
        self.matched_only.setEnabled(False)
        self.matched_only.toggled.connect(self.apply_filter)
        layout.addWidget(self.matched_only)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.tree = table(["Layout / Content", "Kind", "Match"], LayoutTree)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setRootIsDecorated(True)
        self.tree.itemExpanded.connect(self.update_tree_toggle)
        self.tree.itemCollapsed.connect(self.update_tree_toggle)
        self.tree.currentItemChanged.connect(self.show_details)
        self.splitter.addWidget(self.tree)
        tabs = QTabWidget()
        properties = QWidget()
        property_layout = QVBoxLayout(properties)
        property_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_widget = QWidget()
        self.property_form = QFormLayout(form_widget)
        self.property_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.property_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.name, self.kind = line_box(), line_box()
        self.condition, self.path = text_box(), line_box()
        self.condition.setMaximumHeight(65)
        for label, box in (("Name", self.name), ("Item kind", self.kind), ("Condition", self.condition), ("Path", self.path)):
            self.property_form.addRow(label, box)
        self.property_controls = {}
        scroll.setWidget(form_widget)
        property_layout.addWidget(scroll, 1)
        self.mapping_status = QLabel("Map JSON data to inspect trigger state")
        self.mapping_status.setWordWrap(True)
        property_layout.addWidget(self.mapping_status)
        self.mapped_values = table(["Row", "Mapped values", "Match"])
        self.mapped_values.setMinimumHeight(80)
        self.mapped_values.setMaximumHeight(110)
        self.mapped_values.setColumnWidth(0, 55)
        self.mapped_values.setColumnWidth(1, 260)
        property_layout.addWidget(self.mapped_values)
        tabs.addTab(properties, "Properties")
        self.match_details = DiagnosticBox()
        tabs.addTab(self.match_details, "Match Details")
        self.source = text_box()
        tabs.addTab(self.source, "Source JSON")
        self.splitter.addWidget(tabs)
        self.splitter.setSizes([360, 300])
        layout.addWidget(self.splitter, 1)
        self.count = QLabel("No document selected")
        layout.addWidget(self.count)
        self.update_tree_toggle()

    def update_tree_toggle(self, *_):
        nodes = [item for item in self.items() if item.childCount()]
        self.toggle_tree.setEnabled(bool(nodes))
        self.toggle_tree.setText('📂' if any(not item.isExpanded() for item in nodes) else '📁')

    def toggle_tree_expansion(self):
        if any(not item.isExpanded() for item in self.items() if item.childCount()):
            self.tree.expandAll()
        else:
            self.tree.collapseAll()
        self.update_tree_toggle()

    def set_document(self, record, session=None):
        self.session = session if session is not None else self.session
        mapped = bool(self.session and self.session.mapped)
        token = (id(self.session), self.session.mapping_revision if self.session else 0)
        self.matched_only.blockSignals(True)
        self.matched_only.setEnabled(mapped)
        if not mapped or token != self.mapping_token:
            self.matched_only.setChecked(mapped)
        self.matched_only.blockSignals(False)
        self.mapping_token = token
        current = self.tree.currentItem()
        same_document = record is not None and record["name"] == self.document_name
        previous = current.data(0, ROLE + 1) if current and same_document else None
        expanded = {item.data(0, ROLE + 1) for item in self.items() if item.isExpanded()} if same_document else set()
        self.document_name = record["name"] if record else ""
        self.tree.headerItem().setText(0, f"Layout / Content — {self.document_name}" if record else "Layout / Content")
        self.tree.empty_message = "No layouts in this document" if record else "Select a document to inspect its layouts"
        self.tree.viewport().update()
        self.tree.blockSignals(True)
        self.tree.clear()
        if record and self.session:
            for node in self.session.layouts_for(record):
                self.add_node(None, node)
        for item in self.items():
            item.setExpanded(item.data(0, ROLE + 1) in expanded if same_document else item.parent() is None)
        self.tree.blockSignals(False)
        self.apply_filter()
        if previous:
            for item in self.items():
                if item.data(0, ROLE + 1) == previous and not item.isHidden():
                    self.tree.setCurrentItem(item)
                    break
        self.show_details(self.tree.currentItem())
        self.update_tree_toggle()

    def add_node(self, parent, node):
        kind, source, key = node["kind"], node["source"], node["key"]
        name = str(source.get("$$Id") or source.get("Name") or source.get("Id") or source.get("Path") or kind)
        state = node["state"]
        item = QTreeWidgetItem([name + (" *" if self.source_changed(source) else ""), kind, "PASS" if state else "FAIL" if state is not None else "—"])
        item.setData(0, ROLE + 4, name)
        item.setData(0, ROLE, node)
        item.setData(0, ROLE + 1, key)
        item.setToolTip(0, str(source.get("Descr", "")))
        item.setToolTip(2, node.get("reason", ""))
        color_item(item, state)
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        for child in node["children"]:
            self.add_node(item, child)

    def items(self):
        def walk(item):
            yield item
            for row in range(item.childCount()):
                yield from walk(item.child(row))
        for row in range(self.tree.topLevelItemCount()):
            yield from walk(self.tree.topLevelItem(row))

    def apply_filter(self, *_):
        query = self.search.text().strip().casefold()
        def visit(item, parent_allowed=True):
            record = item.data(0, ROLE)
            allowed = parent_allowed and (not self.matched_only.isChecked() or record["state"] is True)
            child_matches = [visit(item.child(row), allowed) for row in range(item.childCount())]
            own_text = " ".join([item.text(0), record["kind"]] +
                                [str(value) for value in record["source"].values() if not isinstance(value, (dict, list))])
            visible = allowed and (query in own_text.casefold() or any(child_matches))
            item.setHidden(not visible)
            if query and any(child_matches):
                item.setExpanded(True)
            return visible
        for row in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(row))
        current = self.tree.currentItem()
        if current is None or current.isHidden():
            first = next((item for item in self.items() if not item.isHidden()), None)
            self.tree.setCurrentItem(first)
            self.show_details(first)
        total = sum(1 for _ in self.items())
        visible = sum(not item.isHidden() for item in self.items())
        self.count.setText(f"{visible} of {total} items" if total else
                           "No layouts in this document" if self.document_name else "No document selected")

    def show_details(self, current, *_):
        for key in list(self.property_controls):
            self.property_form.removeRow(self.property_controls.pop(key))
        self.mapped_values.clear()
        self.mapped_values.hide()
        self.match_details.clear()
        if current is None:
            for box in (self.name, self.kind, self.condition, self.path, self.source):
                box.clear()
            self.mapping_status.setText("No layout item selected")
            self.mapping_status.setStyleSheet("")
            self.details_ready.emit(None)
            return
        record = current.data(0, ROLE)
        source = record["source"]
        self.mapped_values.setVisible(record["kind"] in {"Iteration", "Field"})
        self.name.setText(current.data(0, ROLE + 4))
        self.kind.setText(record["kind"])
        self.condition.setPlainText(str(source.get("Condition", "")))
        self.path.setText(str(source.get("Path", "")))
        excluded = {"$$Id", "Name", "Id", "Condition", "Path"}
        for key, value in source.items():
            if key in excluded or isinstance(value, (list, dict)):
                continue
            label = {"Descr": "Description", "Mandatory": "Required", "Updated": "Updated"}.get(key, re.sub(r"(?<!^)(?=[A-Z])", " ", key))
            if isinstance(value, bool) or key == "Mandatory":
                box = QCheckBox()
                checked = value.strip().lower() in {"true", "1", "yes"} if isinstance(value, str) else bool(value)
                box.setChecked(checked)
                box.setEnabled(False)
            elif isinstance(value, int) and -(2**31) <= value < 2**31:
                box = QSpinBox()
                box.setRange(-(2**31), 2**31 - 1)
                box.setValue(value)
                box.setReadOnly(True)
                box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            elif isinstance(value, float):
                box = QDoubleSpinBox()
                box.setRange(-1e100, 1e100)
                box.setDecimals(8)
                box.setValue(value)
                box.setReadOnly(True)
                box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            elif key == "Type":
                box = QComboBox()
                box.addItem(str(value))
                box.setEnabled(False)
            else:
                box = line_box()
                box.setText(str(value))
            self.property_controls[key] = box
            self.property_form.addRow(label, box)
        self.source.setPlainText(pretty(source))
        state = record["state"]
        self.mapping_status.setText(("PASS · " if state else "FAIL · ") + record.get("reason", "") if state is not None else "Map JSON data to inspect trigger state")
        self.mapping_status.setStyleSheet(f"color:{BLUE if state else RED}" if state is not None else "")
        for row in record["rows"] if state is not None else []:
            values = pretty(row["values"]) if row["values"] else "No mapped value"
            item = QTreeWidgetItem([row["row"], " ".join(values.split()), "PASS" if row["passed"] else "FAIL"])
            item.setToolTip(1, values)
            color_item(item, row["passed"])
            self.mapped_values.addTopLevelItem(item)
        self.match_details.show_diagnostic({"label": record.get("reason", "Mapping"), "passed": state,
                                            "children": record["details"]})
        self.details_ready.emit(current)


class ClausePanel(QWidget):
    """Saved clause library and selected-target composer; independent of mapped data."""

    def __init__(self):
        super().__init__()
        self.session = None
        self.records = []
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter clauses by name, description, or expression…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        self.clear_filter = QPushButton('Clear')
        self.clear_filter.clicked.connect(self.search.clear)
        search_row.addWidget(self.clear_filter)
        layout.addLayout(search_row)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.tree = table(["Name", "Description"])
        self.tree.currentItemChanged.connect(self.show_details)
        self.splitter.addWidget(self.tree)
        properties = QWidget()
        form = QFormLayout(properties)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name = line_box()
        self.description = line_box()
        self.expression = text_box()
        form.addRow(QLabel("Clause Library"))
        for label, widget in (("Name", self.name), ("Description", self.description),
                              ("Expression", self.expression)):
            form.addRow(label, widget)
        self.splitter.addWidget(properties)
        composer = QWidget()
        composer_layout = QVBoxLayout(composer)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Compose Condition"))
        heading.addStretch()
        self.compose_help = QPushButton('(i)')
        self.compose_help.clicked.connect(self.show_compose_help)
        heading.addWidget(self.compose_help)
        composer_layout.addLayout(heading)
        self.target_label = QLabel("Target: (none selected)")
        self.target_label.setWordWrap(True)
        font = self.target_label.font()
        font.setBold(True)
        self.target_label.setFont(font)
        composer_layout.addWidget(self.target_label)
        self.compose = ClauseComposeEdit()
        self.compose.setReadOnly(True)
        self.compose.setPlaceholderText("Select a document or layout item to view its condition in clause names.")
        composer_layout.addWidget(self.compose, 1)
        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel('Clause'))
        self.clause_picker = QComboBox()
        picker_row.addWidget(self.clause_picker, 1)
        composer_layout.addLayout(picker_row)
        self.compose_status = QLabel("No target selected.")
        self.compose_status.setWordWrap(True)
        composer_layout.addWidget(self.compose_status)
        self.splitter.addWidget(composer)
        self.splitter.setSizes([220, 240, 260])
        layout.addWidget(self.splitter, 1)
        self.count = QLabel("Open a package to inspect its clause library")
        layout.addWidget(self.count)

    def set_session(self, session):
        previous = self.name.text()
        self.session = session
        self.compose.set_clauses(session.clauses)
        selected_clause_name = self.clause_picker.currentText()
        self.clause_picker.blockSignals(True)
        self.clause_picker.clear()
        self.clause_picker.addItems(sorted({entry['name'] for entry in session.clauses}, key=str.casefold))
        self.clause_picker.blockSignals(False)
        self.records = sorted([dict(entry) for entry in session.clauses],
                              key=lambda entry: entry["name"].casefold())
        self.tree.blockSignals(True)
        self.tree.clear()
        for index, record in enumerate(self.records):
            item = QTreeWidgetItem([record["name"], record.get("description", "")])
            item.setData(0, ROLE, index)
            item.setToolTip(0, record["expression"])
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)
        self.apply_filter()
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item.text(0) == previous and not item.isHidden():
                self.tree.setCurrentItem(item)
                break
        self.show_details(self.tree.currentItem())
        if selected_clause_name and self.clause_picker.findText(selected_clause_name) >= 0:
            self.clause_picker.setCurrentText(selected_clause_name)

    def show_compose_help(self):
        QMessageBox.information(self, 'Composer Help',
            "Build conditions with clause names and operators:\n"
            "AND: '+' or 'AND'\nOR: 'OR', '||', or '|'\n"
            "Group expressions with parentheses.\n"
            "Use RAW{...} for unmatched or advanced fragments.\n\n"
            "Use CLAUSE{name} to reference clauses inside clause definitions or names with spaces.\n\n"
            "Examples:\nis_English + (isNot_Elderly OR isNot_Staff)\n"
            "is_English + RAW{@.billPrint.billDetails.currBal > 150}\n\n"
            "Type a clause name fragment for suggestions; Up/Down navigates, Tab or Enter accepts, Esc closes.\n"
            "Ctrl+Space shows suggestions for the current fragment.")

    def set_target(self, source, kind="Document", name=""):
        self.compose.clear()
        if source is None:
            self.target_label.setText("Target: (none selected)")
            self.compose_status.setText("No target selected. Select a document or layout item.")
            return
        self.target_label.setText(f"Target: {kind} {name}")
        condition = str(source.get("Condition", "")).strip()
        if not condition:
            self.compose_status.setText("Target has no condition.")
            return
        try:
            text, exact, unmatched = ClauseComposer().compose(condition, self.session.clauses)
        except ValueError as error:
            self.compose_status.setText(str(error))
            return
        self.compose.setPlainText(text)
        self.compose_status.setText("Auto-compose: exact clause match." if exact else
                                   f"Auto-compose: partial match ({unmatched} raw fragment{'s' if unmatched != 1 else ''} as RAW{{...}}).")

    def apply_filter(self, *_):
        query = self.search.text().strip().casefold()
        visible = []
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            record = self.records[item.data(0, ROLE)]
            hidden = query not in " ".join(str(record.get(key, "")) for key in
                                          ("name", "expression", "description")).casefold()
            item.setHidden(hidden)
            if not hidden:
                visible.append(item)
        current = self.tree.currentItem()
        if current is None or current.isHidden():
            self.tree.setCurrentItem(visible[0] if visible else None)
            self.show_details(self.tree.currentItem())
        self.count.setText(f"{len(visible)} of {len(self.records)} clauses" if self.records else
                           "No saved clause library in this package")

    def show_details(self, current, *_):
        if current is None:
            self.clause_picker.setCurrentIndex(-1)
            for box in (self.name, self.description, self.expression):
                box.clear()
            return
        record = self.records[current.data(0, ROLE)]
        self.clause_picker.setCurrentText(record["name"])
        self.name.setText(record["name"])
        self.description.setText(record.get("description", ""))
        self.expression.setPlainText(record["expression"])


class DataPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.values = {}
        self.payload = None
        self.mapped = False
        self.fields = []
        layout = QVBoxLayout(self)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mapped data…")
        self.mode = QComboBox()
        self.mode.addItems(["Auto", "JSONPath", "Full Text", "Condition"])
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.mode)
        for title, callback in (("Search", self.run_search), ("Clear", self.clear_search)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            search_row.addWidget(button)
        self.search.returnPressed.connect(self.run_search)
        layout.addLayout(search_row)
        path_row = QHBoxLayout()
        self.path = line_box()
        self.path.setPlaceholderText("Select a node to inspect its JSON path")
        copy_button = QPushButton("Copy Path")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.path.text()))
        path_row.addWidget(self.path, 1)
        path_row.addWidget(copy_button)
        layout.addLayout(path_row)
        self.splitter = splitter = QSplitter()
        self.tree = table(["Path", "Value"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(0, 300)
        self.tree.setRootIsDecorated(True)
        self.tree.itemExpanded.connect(self.expand_node)
        self.tree.currentItemChanged.connect(self.show_value)
        self.value = text_box()
        splitter.addWidget(self.tree)
        splitter.addWidget(self.value)
        layout.addWidget(splitter)
        self.status = QLabel("Map data to inspect it.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def set_data(self, value: object, *, mapped=True, fields=None):
        self.payload, self.mapped = value, mapped
        self.fields = fields or []
        self.tree.clear()
        self.values.clear()
        self.value.clear()
        self.path.clear()
        if not mapped:
            self.value.setPlainText("Map JSON data to browse its contents.")
            self.status.setText("Map data to inspect it.")
            return
        root = self.node("$", value)
        self.tree.addTopLevelItem(root)
        self.tree.setCurrentItem(root)
        root.setExpanded(True)
        self.status.setText("Mapped data loaded. Expand nodes or search by path, text, or condition.")

    def clear_search(self):
        self.search.clear()
        self.set_data(self.payload, mapped=self.mapped, fields=self.fields)

    def run_search(self):
        query = self.search.text().strip()
        if not self.mapped:
            self.status.setText("Map a data file before searching.")
            return
        if not query:
            self.clear_search()
            return
        evaluator = DataQueries(self.fields)
        mode = self.mode.currentText()
        self.tree.clear()
        self.values.clear()
        self.path.clear()
        self.value.clear()
        if mode == "Condition":
            passed = evaluator._evaluate_document_condition(query, self.payload)
            item = self.node("Condition", passed)
            item.setText(1, "PASS" if passed else "FAIL")
            color_item(item, passed)
            self.tree.addTopLevelItem(item)
            self.tree.setCurrentItem(item)
            self.status.setText("Condition: " + ("PASS" if passed else "FAIL"))
            return
        if mode == "JSONPath" or (mode == "Auto" and query.startswith("$")):
            valid, reason = evaluator._validate_field_path(query)
            if not valid:
                self.status.setText("Invalid JSONPath: " + reason)
                return
            results = evaluator._extract_values_and_paths_by_path(self.payload, query)
            label = "JSONPath"
        else:
            results = evaluator._find_data_browser_text_matches(self.payload, query)
            label = "Full text"
        for path, value in results:
            self.tree.addTopLevelItem(self.node(path, value))
        self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.status.setText(f"{label} returned {len(results)} result(s).")

    def node(self, path: str, value: object) -> QTreeWidgetItem:
        preview = f"{len(value)} items" if isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False)
        item = QTreeWidgetItem([path, preview[:120]])
        # Keep Python values intact: QVariant conversion can reorder object keys.
        self.values[path] = value
        item.setData(0, ROLE + 1, path)
        if isinstance(value, (dict, list)) and value:
            item.addChild(QTreeWidgetItem(["Loading…"]))
        return item

    def expand_node(self, item):
        if item.data(0, ROLE + 2):
            return
        item.setData(0, ROLE + 2, True)
        path = item.data(0, ROLE + 1)
        value = self.values[path]
        item.takeChildren()
        pairs = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else []
        for key, child in pairs:
            # Bracket notation also handles keys containing punctuation.
            child_path = f"{path}[{json.dumps(key, ensure_ascii=False)}]"
            item.addChild(self.node(child_path, child))

    def show_value(self, current, *_):
        self.value.setPlainText(pretty(self.values[current.data(0, ROLE + 1)]) if current else "")
        self.path.setText(current.data(0, ROLE + 1) if current else "")


class MappingJob(QThread):
    completed = Signal(object, str)

    def __init__(self, session: PackageSession, path: Path, parent):
        super().__init__(parent)
        self.session = copy.deepcopy(session)
        self.path = path
        self.result = None
        self.error = ""

    def run(self):
        try:
            self.session.map_data(read_json(self.path), self.path.name)
            self.result = self.session
        except Exception as error:
            self.error = str(error)
        self.completed.emit(self.result, self.error)


class WorkspaceWindow(AuthoringActions, QMainWindow):
    # The three-manager layout replaces the initial two-column prototype.
    LAYOUT_VERSION = 4

    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        application = QApplication.instance()
        if not hasattr(application, '_atool_dialog_placement'):
            application._atool_dialog_placement = DialogPlacement(application)
            application.installEventFilter(application._atool_dialog_placement)
        self.settings = settings if settings is not None else QSettings("ATool", "QtPrototype")
        self.session: PackageSession | None = None
        self.job: MappingJob | None = None
        self.close_pending = False
        self.setObjectName("atool-qt-workspace")
        self.setWindowTitle("ATool")
        self.menuBar().setNativeMenuBar(False)
        self.resize(1440, 900)
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AllowTabbedDocks |
                            QMainWindow.DockOption.AnimatedDocks)
        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        self.setDockNestingEnabled(True)
        # The managers themselves are the workspace; no empty editor occupies the centre.
        centre = QWidget()
        self.setCentralWidget(centre)
        centre.hide()
        self.docks: dict[str, QDockWidget] = {}
        self.documents = ManagerPanel("documents")
        self.fields = ManagerPanel("fields")
        self.data = DataPanel()
        self.layouts = LayoutPanel()
        self.clauses = ClausePanel()
        self.activity = text_box()
        self.add_panel("documents", "Document Manager", self.documents, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.add_panel("fields", "Field Manager", self.fields, Qt.DockWidgetArea.RightDockWidgetArea)
        self.add_panel("layouts", "Layout Manager", self.layouts, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.add_panel("data", "Data Browser", self.data, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.add_panel("clauses", "Clause Manager", self.clauses, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.add_panel("activity", "Activity", self.activity, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.active_document = None
        self.updating_layout = False
        self.documents.selected.connect(self.document_selected)
        self.layouts.tree.currentItemChanged.connect(self.layout_selected)
        self.create_actions()
        self.package_label = QLabel("Package: (none)")
        self.package_label.setMargin(5)
        self.statusBar().addWidget(self.package_label, 1)
        self.editable_label = QLabel("Mode: (none)")
        self.statusBar().addWidget(self.editable_label)
        self.data_label = QLabel("Data: (none)")
        self.data_label.setMargin(5)
        self.statusBar().addWidget(self.data_label, 1)
        self.install_authoring()
        self.reset_layout()
        geometry = self.settings.value("geometry")
        state = self.settings.value("dockState")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            if self.restoreState(state, self.LAYOUT_VERSION):
                self.default_layout_pending = False
            else:
                self.reset_layout()
        for key in ("documents", "layouts", "fields", "data", "content"):
            sizes = self.settings.value(f"{key}/splitter")
            if sizes is not None:
                getattr(self, key).splitter.restoreState(sizes)
        clause_sizes = self.settings.value('clauses/stackedSplitter')
        if clause_sizes is not None:
            self.clauses.splitter.restoreState(clause_sizes)
        self.log("Drag a panel title to move or detach it. Drop onto another panel to tab them.\n"
                 "Use View → Panels to reopen hidden panels, or View → Reset Layout to start over.")
        self.update_actions()

        self.apply_user_settings()
        if self.settings.contains('documentHierarchy'):
            enabled = self.settings.value('documentHierarchy', type=bool)
            self.documents.set_hierarchy(enabled)
            self.update_manager_controls()

    def add_panel(self, key, title, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName("panel-" + key)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable |
                         QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        self.docks[key] = dock

    def action(self, label, callback, shortcut=None):
        action = QAction(label, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(shortcut)
        return action

    def create_actions(self):
        file_menu = self.menuBar().addMenu("&File")
        self.open_action = self.action("Open Raw AT…", self.choose_package)
        self.bundle_action = self.action("Open Local Package…", self.choose_bundle)
        file_menu.addActions([self.open_action, self.bundle_action])
        file_menu.addSeparator()
        self.quit_action = self.action("Exit", self.close, QKeySequence.StandardKey.Quit)
        file_menu.addAction(self.quit_action)
        data_menu = self.menuBar().addMenu("&Data")
        self.map_action = self.action("Map…", self.choose_data, "Ctrl+M")
        data_menu.addAction(self.map_action)
        view_menu = self.menuBar().addMenu("&View")
        panels_menu = view_menu.addMenu("Panels")
        for dock in self.docks.values():
            panels_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        self.reset_action = self.action("Reset Layout", self.reset_layout)
        view_menu.addAction(self.reset_action)
        view_menu.addAction(self.action("Documents + Layouts + Fields", self.reset_layout))
        view_menu.addAction(self.action("Tab Document and Field Managers", self.tab_managers))
        help_menu = self.menuBar().addMenu("&Help")
        self.about_action = self.action("About ATool", self.about)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        help_menu.addAction(self.about_action)
        file_menu.insertAction(self.quit_action, self.about_action)

    def reset_layout(self):
        for dock in self.docks.values():
            dock.setFloating(False)
            self.removeDockWidget(dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.docks["documents"])
        self.splitDockWidget(self.docks["documents"], self.docks["layouts"], Qt.Orientation.Horizontal)
        self.splitDockWidget(self.docks["layouts"], self.docks["fields"], Qt.Orientation.Horizontal)
        for key in ("clauses", "data"):
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.docks[key])
            self.tabifyDockWidget(self.docks["fields"], self.docks[key])
            self.docks[key].show()
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.docks["activity"])
        self.docks["activity"].hide()
        if 'content' in self.docks:
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.docks['content'])
            self.tabifyDockWidget(self.docks['layouts'], self.docks['content'])
            self.docks['content'].hide()
        for key in ("documents", "layouts", "fields"):
            self.docks[key].show()
            getattr(self, key).splitter.setSizes([360, 300])
        self.resizeDocks([self.docks[key] for key in ("documents", "layouts", "fields")],
                         [310, 580, 540], Qt.Orientation.Horizontal)
        self.show_panel("fields")
        self.default_layout_pending = True
        QTimer.singleShot(0, self.activate_default_layout)

    def activate_default_layout(self):
        if self.default_layout_pending:
            self.default_layout_pending = False
            self.show_panel("fields")

    def show_panel(self, key):
        self.docks[key].show()
        self.docks[key].raise_()
        # Select the dock tab explicitly; raising an inactive dock can leave it behind.
        for bar in self.findChildren(QTabBar):
            if bar.parent() is self:
                for index in range(bar.count()):
                    if bar.tabText(index) == self.docks[key].windowTitle():
                        bar.setCurrentIndex(index)
                        return

    def tab_managers(self):
        self.reset_layout()
        self.default_layout_pending = False
        self.tabifyDockWidget(self.docks["fields"], self.docks["documents"])
        self.show_panel("documents")

    def log(self, message):
        self.activity.appendPlainText(message)

    def update_actions(self):
        busy = self.package_busy() if hasattr(self, "package_download_jobs") else self.job is not None
        for action in (self.open_action, self.bundle_action):
            action.setEnabled(not busy)
        self.map_action.setEnabled(self.session is not None and not busy)
        if hasattr(self, "editor"):
            self.update_authoring_actions()

    def set_session(self, session: PackageSession, *, preserve_selection=False):
        previous = self.refreshing
        self.refreshing = True
        try:
            self.set_session_widgets(session, preserve_selection=preserve_selection)
        finally:
            self.refreshing = previous

    def set_session_widgets(self, session: PackageSession, *, preserve_selection=False):
        self.prepare_editor(session)
        self.session = session
        for panel in (self.documents, self.fields, self.layouts):
            panel.source_changed = self.editor.source_changed
        self.clauses.set_session(session)
        self.documents.set_session(session, preserve_selection=preserve_selection)
        self.fields.set_session(session, preserve_selection=preserve_selection)
        self.data.set_data(session.data, mapped=session.mapped, fields=session.fields)
        if hasattr(self, 'content'):
            self.content.refresh_fields()
        self.update_package_status()
        self.setWindowTitle(f"{session.name} — ATool[*]")
        self.update_actions()

    def document_selected(self, record):
        self.active_document = record
        self.updating_layout = True
        try:
            self.layouts.set_document(record, self.session)
        finally:
            self.updating_layout = False
        self.clauses.set_target(record["source"] if record and record.get("in_at", True) else None,
                                "Document", record["name"] if record else "")

    def layout_selected(self, current, *_):
        if self.updating_layout:
            return
        if current is None:
            record = self.active_document
            self.clauses.set_target(record["source"] if record and record.get("in_at", True) else None,
                                    "Document", record["name"] if record else "")
        else:
            node = current.data(0, ROLE)
            self.clauses.set_target(node["source"], node["kind"], current.data(0, ROLE + 4))

    def open_package(self, path: Path) -> bool:
        if self.package_busy() or not self.confirm_discard():
            return False
        try:
            session = PackageSession.open(path)
        except (OSError, ValueError, RecursionError) as error:
            self.report_error("Could not open package", str(error))
            return False
        if not self.prepare_shared_exit():
            return False
        self.editor = None
        self.set_session(session)
        self.shared_package_dir, self.shared_mode = self.shared_store().restore_context(session.bundle['root']) if session.bundle else (None, 'local')
        self.update_shared_actions()
        self.log(f"Opened {session.name}: {session.source}")
        for note in session.notes:
            self.log(note)
        self.settings.setValue("lastDirectory", str(session.source.parent))
        self.remember_package_session()
        return True

    def remember_package_session(self):
        if not self.session or not self.session.source:
            return
        self.settings.setValue('lastSessionAlias', str(self.comms.settings.get('session_alias') or ''))
        self.settings.setValue('lastPackageFile', str(self.session.source))
        self.settings.setValue('lastPackageManifest', str(self.session.bundle.get('manifest_path') or ''))
        if self.session.bundle:
            from .shared_packages import names
            self.record_package_mru(*names(self.session.bundle['manifest']))

    def choose_package(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Assembly Template or Bundle Manifest",
                                             self.settings.value("lastDirectory", ""), "JSON files (*.json);;All files (*)")
        if path:
            self.open_package(Path(path))

    def choose_bundle(self):
        path = QFileDialog.getExistingDirectory(self, "Open Package Folder", self.settings.value("lastDirectory", ""))
        if path:
            self.open_package(Path(path))

    def choose_data(self):
        directory = self.settings.value("lastMappingDirectory", "")
        if not directory:
            previous = self.settings.value("lastDataFile", "")
            directory = str(Path(previous).expanduser().parent) if previous else self.settings.value("lastDirectory", "")
        path, _ = QFileDialog.getOpenFileName(self, "Map JSON Data", directory,
                                             "JSON files (*.json);;All files (*)")
        if path:
            self.map_file(Path(path))

    def map_file(self, path: Path, *, on_complete=None):
        if self.session is None or self.package_busy():
            return False
        self.settings.setValue("lastMappingDirectory", str(path.expanduser().resolve().parent))
        self.job = MappingJob(self.session, path, self)
        self.job.completed.connect(self.mapping_complete)
        if on_complete is not None:
            self.job.completed.connect(on_complete)
        self.job.finished.connect(self.mapping_finished)
        self.update_actions()
        self.log(f"Mapping {path.name}…")
        self.log(f"Mapping {path}")
        self.job.start()
        return True

    def mapping_complete(self, session, error):
        if error:
            self.report_error("Could not map data", error)
            self.set_session(self.session, preserve_selection=True)
        else:
            self.set_session(session, preserve_selection=True)
            self.settings.setValue("lastDataFile", str(self.job.path))
            matched = sum(bool(doc.get("triggered")) for doc in session.documents)
            self.log(f"Mapped {session.data_name}: {matched} of {len(session.documents)} documents matched.")

    def mapping_finished(self):
        job, self.job = self.job, None
        job.deleteLater()
        self.statusBar().clearMessage()
        self.update_actions()
        if self.close_pending:
            self.close()

    def report_error(self, title, message):
        self.log(f"{title}: {message}")
        QMessageBox.warning(self, title, message)

    def about(self):
        from .build_info import about_text
        QMessageBox.information(self, 'About ATool', about_text())

    def closeEvent(self, event):
        if self.local_jobs:
            self.close_pending = True
            self.statusBar().showMessage("Finishing the current operation before closing…")
            event.ignore()
            return
        if self.job is not None:
            self.close_pending = True
            self.statusBar().showMessage("Finishing mapping before closing…")
            event.ignore()
            return
        if not self.confirm_quit():
            event.ignore()
            return
        if not self.confirm_discard():
            event.ignore()
            return
        if hasattr(self, 'content') and not self.content.confirm_discard('quitting'):
            event.ignore()
            return
        if not self.prepare_shared_exit():
            event.ignore()
            return
        self.comms.shutdown()
        self.finish_publish()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("dockState", self.saveState(self.LAYOUT_VERSION))
        for key in ("documents", "layouts", "fields", "data", "content"):
            self.settings.setValue(f"{key}/splitter", getattr(self, key).splitter.saveState())
        self.settings.setValue('clauses/stackedSplitter', self.clauses.splitter.saveState())
        self.settings.sync()
        event.accept()
