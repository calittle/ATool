"""Personal, package-scoped favorites and their transaction summary panel."""
from __future__ import annotations

import copy
import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QComboBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .diagnostics import ConditionDiagnostics
from .grids import configure_grid
from .package_guard import session_package_name

ROLE = Qt.ItemDataRole.UserRole


def has_value(value):
    """Empty results have no value; zero and false are meaningful data."""
    return value is not None and value != '' and value != [] and value != {}


class FavoritesPanel(QWidget):
    open_item = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.session = None
        self.rows = []
        layout = QVBoxLayout(self)
        self.filter = QComboBox()
        self.filter.addItems(['Pass / Mapped', 'Fail / Unmapped', 'All'])
        self.filter.currentIndexChanged.connect(self.apply_filter)
        layout.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Name', 'Type', 'Result / Value'])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        configure_grid(self.tree)
        self.tree.setColumnWidth(0, 240)
        self.tree.setColumnWidth(1, 70)
        self.tree.itemClicked.connect(self.open_row)
        self.tree.itemActivated.connect(self.open_row)
        layout.addWidget(self.tree, 1)
        self.count = QLabel('Mark favorites in Field Manager and Clause Manager.')
        self.count.setWordWrap(True)
        layout.addWidget(self.count)

    def set_session(self, session, favorites):
        self.session = session
        self.rows = []
        evaluator = ConditionDiagnostics(session.fields)
        for kind, records in (('fields', session.fields), ('clauses', session.clauses)):
            selected = favorites.get(kind, [])
            for record in records:
                name = record['name']
                if name not in selected:
                    continue
                state, detail = None, ''
                text = 'No data loaded'
                if session.mapped and kind == 'fields':
                    values = record.get('mapped_values', [])
                    state = any(has_value(value) for value in values)
                    text = (str(values[0]) if len(values) == 1 and isinstance(values[0], str)
                            else json.dumps(values[0] if len(values) == 1 else values, ensure_ascii=False)) if state else 'Unmapped'
                elif session.mapped:
                    try:
                        expression = evaluator._resolve_clause_expression_by_name_from_entries(session.clauses, name)
                        issues = evaluator._condition_path_syntax_issues(expression)
                        if issues:
                            raise ValueError('\n'.join(issues))
                        warnings = []
                        state = evaluator._evaluate_document_condition(expression, session.data, warnings=warnings)
                        text = 'PASS' if state else 'FAIL'
                        detail = '\n'.join(warnings)
                    except (ValueError, TypeError, KeyError, IndexError) as error:
                        text, detail = 'ERROR', str(error)
                self.rows.append((kind, name, text, state, detail))
        self.rows.sort(key=lambda row: (row[1].casefold(), row[0]))
        self.apply_filter()

    def apply_filter(self, *_):
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        selected = self.filter.currentIndex()
        visible = 0
        for kind, name, text, state, detail in self.rows:
            if self.session.mapped and selected != 2 and state is not (selected == 0):
                continue
            item = QTreeWidgetItem([name, 'Field' if kind == 'fields' else 'Clause', text])
            item.setData(0, ROLE, (kind, name))
            item.setToolTip(0, 'Open in ' + ('Field Manager' if kind == 'fields' else 'Clause Manager'))
            item.setToolTip(2, detail or text)
            if state is not None or text == 'ERROR':
                color = QColor('#0057d9' if state else '#c52323')
                for column in range(3):
                    item.setForeground(column, color)
            self.tree.addTopLevelItem(item)
            visible += 1
        if hasattr(self.tree, '_grid_user_sort'):
            self.tree.setSortingEnabled(True)
            self.tree.sortByColumn(*self.tree._grid_user_sort)
        self.count.setText(f'{visible} of {len(self.rows)} favorites' if self.rows else
                           'Mark favorites in Field Manager and Clause Manager.')

    def open_row(self, item, *_):
        self.open_item.emit(*item.data(0, ROLE))


class FavoritesActions:
    def install_favorites(self):
        self.fields.tree.itemChanged.connect(lambda item, column: self.favorite_changed('fields', item, column))
        self.clauses.tree.itemChanged.connect(lambda item, column: self.favorite_changed('clauses', item, column))
        self.favorites.open_item.connect(self.open_favorite)

    def package_favorites(self):
        if self.session is None:
            return {}
        value = self.comms.settings.section('favorites').get(session_package_name(self.session), {})
        if not isinstance(value, dict):
            return {}
        return {kind: names if isinstance(names, list) else [] for kind, names in value.items()}

    def refresh_favorites(self):
        if self.session is None:
            return
        favorites = self.package_favorites()
        for kind, column in (('fields', 3), ('clauses', 2)):
            panel = getattr(self, kind)
            panel.favorite_names = set(favorites.get(kind, []))
            panel.tree.blockSignals(True)
            sorting = panel.tree.isSortingEnabled()
            panel.tree.setSortingEnabled(False)
            try:
                items = panel.items() if kind == 'fields' else (
                    panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount()))
                for item in items:
                    name = item.data(0, ROLE + 4) if kind == 'fields' else panel.records[item.data(0, ROLE)]['name']
                    item.setCheckState(column, Qt.CheckState.Checked if name in favorites.get(kind, []) else Qt.CheckState.Unchecked)
            finally:
                panel.tree.setSortingEnabled(sorting)
                panel.tree.blockSignals(False)
        self.favorites.set_session(self.session, favorites)

    def favorite_changed(self, kind, item, column):
        if self.refreshing or self.session is None or column != (3 if kind == 'fields' else 2):
            return
        index = item.data(0, ROLE)
        if index is None:
            return
        name = item.data(0, ROLE + 4) if kind == 'fields' else self.clauses.records[index]['name']
        store = self.comms.settings
        payload = copy.deepcopy(store.payload)
        favorites = copy.deepcopy(self.package_favorites())
        names = set(favorites.get(kind, []))
        if item.checkState(column) == Qt.CheckState.Checked:
            names.add(name)
        else:
            names.discard(name)
        favorites[kind] = sorted(names)
        payload['favorites'] = dict(store.section('favorites'))
        payload['favorites'][session_package_name(self.session)] = favorites
        try:
            store.save(payload)
        except (ValueError, OSError) as error:
            self.report_error('Could not save favorites', str(error))
        self.refresh_favorites()

    def open_favorite(self, kind, name):
        panel = getattr(self, kind)
        panel.search.clear()
        if kind == 'fields':
            panel.matched_only.setChecked(False)
            items = panel.items()
        else:
            items = (panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount()))
        for item in items:
            raw_name = item.data(0, ROLE + 4) if kind == 'fields' else panel.records[item.data(0, ROLE)]['name']
            if raw_name == name:
                parent = item.parent()
                while parent:
                    parent.setExpanded(True)
                    parent = parent.parent()
                panel.tree.clearSelection()
                panel.tree.setCurrentItem(item)
                panel.tree.scrollToItem(item)
                self.show_panel(kind)
                panel.tree.setFocus()
                break
