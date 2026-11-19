"""Editable, portable TD plan; machine-specific paths are owned by the dialog."""
from copy import deepcopy
from atool_core.td_profile import normalize_plan
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
                              QDateEdit, QTreeWidget, QTreeWidgetItem, QPushButton,
                              QHBoxLayout, QLabel)


class ProfilePlanEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.original = {}
        self.loading = False
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.family = QLineEdit()
        self.description = QLineEdit()
        self.package = QComboBox()
        self.package.setEditable(True)
        self.effective = QDateEdit(QDate.currentDate())
        self.effective.setCalendarPopup(True)
        self.effective.setDisplayFormat('yyyy-MM-dd')
        self.version = QLineEdit()
        self.version.setPlaceholderText('Optional exact AT version')
        for label, widget in [('Family name', self.family), ('Description', self.description),
                              ('Comms package', self.package), ('Effective date', self.effective),
                              ('AT reference version', self.version)]:
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addWidget(QLabel('Each top-level row is a business case with its own baseline. Child rows are its variants.\nMap cases to Comms documents (comma-separated); multiple cases may share one template.'))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Business case ID', 'Scenario folder', 'Input filename', 'Label (optional)', 'Comms documents'])
        self.tree.setColumnWidth(0, 190)
        self.tree.setColumnWidth(1, 180)
        self.tree.setColumnWidth(2, 250)
        layout.addWidget(self.tree)
        buttons = QHBoxLayout()
        for label, callback in [('Add baseline', self.add_baseline), ('Add variant', self.add_variant),
                                ('Remove', self.remove), ('Move up', lambda: self.move(-1)),
                                ('Move down', lambda: self.move(1))]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        self.pick_input = QPushButton('Choose input…')
        buttons.addWidget(self.pick_input)
        layout.addLayout(buttons)
        layout.addWidget(QLabel('Choose whether to compare each document. Document only retains its design and input coverage without scenario comparisons.'))
        self.references = QTreeWidget()
        self.references.setHeaderLabels(['Comms document', 'Reference business case', 'Comparison'])
        self.references.setMaximumHeight(140)
        self.references.setColumnWidth(0, 250)
        layout.addWidget(self.references)
        self.tree.itemChanged.connect(self.refresh_references)

    def reference_values(self):
        return {self.references.topLevelItem(i).text(0): self.references.itemWidget(self.references.topLevelItem(i), 1).currentData()
                for i in range(self.references.topLevelItemCount())
                if self.references.itemWidget(self.references.topLevelItem(i), 1).isEnabled()
                and self.references.itemWidget(self.references.topLevelItem(i), 1).currentData()}

    def comparison_values(self):
        return {self.references.topLevelItem(i).text(0): self.references.itemWidget(self.references.topLevelItem(i), 2).currentData()
                for i in range(self.references.topLevelItemCount())}

    def refresh_references(self, *_args, selected=None, modes=None):
        if self.loading:
            return
        previous = selected if selected is not None else self.reference_values()
        modes = modes if modes is not None else self.comparison_values()
        owners = {}
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            case = item.text(0).strip()
            if not case:
                continue
            for document in (name.strip() for name in item.text(4).split(',')):
                if document:
                    owners.setdefault(document, []).append(case)
        self.references.clear()
        for document, cases in owners.items():
            item = QTreeWidgetItem([document, ''])
            self.references.addTopLevelItem(item)
            combo = QComboBox()
            combo.addItem('Choose reference case…', '')
            for case in dict.fromkeys(cases):
                combo.addItem(case, case)
            reference = previous.get(document, cases[0] if len(cases) == 1 else '')
            if reference not in cases and len(cases) == 1:
                reference = cases[0]
            combo.setCurrentIndex(max(0, combo.findData(reference)))
            self.references.setItemWidget(item, 1, combo)
            mode = QComboBox()
            mode.addItem('Compare cases and variants', 'compare')
            mode.addItem('Document only', 'document_only')
            mode.setCurrentIndex(max(0, mode.findData(modes.get(document, 'compare'))))
            combo.setEnabled(mode.currentData() == 'compare')
            mode.currentIndexChanged.connect(lambda _index, selector=mode, reference=combo: reference.setEnabled(selector.currentData() == 'compare'))
            self.references.setItemWidget(item, 2, mode)

    def add_row(self, record, parent=None):
        item = QTreeWidgetItem([str(record.get('case') or record.get('document', '')) if parent is None else 'Variant',
                               str(record.get('scenario', '')), str(record.get('input', '')),
                               str(record.get('label', '')), ', '.join(record.get('documents', [record['document']] if record.get('document') else [])) if parent is None else ''])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setData(0, Qt.ItemDataRole.UserRole, deepcopy(record))
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
            parent.setExpanded(True)
        self.refresh_references()
        return item

    def add_baseline(self):
        self.tree.setCurrentItem(self.add_row({}))

    def add_variant(self):
        item = self.tree.currentItem()
        if item:
            self.tree.setCurrentItem(self.add_row({}, item.parent() or item))

    def remove(self):
        item = self.tree.currentItem()
        if item:
            parent = item.parent() or self.tree.invisibleRootItem()
            parent.takeChild(parent.indexOfChild(item))
            self.refresh_references()

    def move(self, delta):
        item = self.tree.currentItem()
        if not item:
            return
        parent = item.parent() or self.tree.invisibleRootItem()
        index = parent.indexOfChild(item)
        target = index + delta
        if 0 <= target < parent.childCount():
            parent.takeChild(index)
            parent.insertChild(target, item)
            self.tree.setCurrentItem(item)
            self.refresh_references()

    def load(self, profile):
        if not isinstance(profile, dict) or not isinstance(profile.get('comms', {}), dict):
            raise ValueError('Profile and comms settings must be JSON objects.')
        rows = profile.get('baselines', [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) or
                not isinstance(row.get('variants', []), list) or
                any(not isinstance(v, dict) for v in row.get('variants', [])) for row in rows):
            raise ValueError('Baselines and variants must be lists of objects.')
        effective = QDate.fromString(str(profile.get('comms', {}).get('effective_date', QDate.currentDate().toString('yyyy-MM-dd'))), 'yyyy-MM-dd')
        if not effective.isValid():
            raise ValueError('Effective date must be YYYY-MM-DD.')
        for row in rows:
            if 'documents' in row and (not isinstance(row['documents'], list) or any(not isinstance(d, str) for d in row['documents'])):
                raise ValueError('Each case documents value must be a list of Comms document names.')
        if not isinstance(profile.get('document_references', {}), dict):
            raise ValueError('Document references must map document names to case IDs.')
        modes = profile.get('document_comparisons', {})
        if not isinstance(modes, dict) or any(value not in ('compare', 'document_only') for value in modes.values()):
            raise ValueError('Invalid document comparison settings.')
        self.loading = True
        self.original = deepcopy(profile)
        self.family.setText(str(profile.get('family', '')))
        self.description.setText(str(profile.get('description', '')))
        self.package.setCurrentText(str(profile.get('comms', {}).get('package', '')))
        self.effective.setDate(effective)
        self.version.setText(str(profile.get('comms', {}).get('reference_version', '')))
        self.tree.clear()
        for row in rows:
            item = self.add_row(row)
            for variant in row.get('variants', []):
                self.add_row(variant, item)
        self.loading = False
        self.refresh_references(selected=profile.get('document_references', {}), modes=modes)

    def plan(self, validate=False):
        profile = deepcopy(self.original)
        # These settings are local to a workstation/run, never part of a saved plan.
        for key in ('scenarios', 'occs', 'formats', 'output', 'xml_conversion', 'render_evidence', 'rebuild_resource_index'):
            profile.pop(key, None)
        profile.update(family=self.family.text().strip(), description=self.description.text().strip())
        comms = profile.setdefault('comms', {})
        comms.pop('resource_cache', None)
        comms.update(package=self.package.currentText().strip(), effective_date=self.effective.date().toString('yyyy-MM-dd'))
        if self.version.text().strip():
            comms['reference_version'] = self.version.text().strip()
        else:
            comms.pop('reference_version', None)
        def record(item, baseline):
            value = deepcopy(item.data(0, Qt.ItemDataRole.UserRole) or {})
            value.update(scenario=item.text(1).strip(), input=item.text(2).strip())
            if item.text(3).strip():
                value['label'] = item.text(3).strip()
            else:
                value.pop('label', None)
            if baseline:
                value.pop('document', None)
                value['case'] = item.text(0).strip()
                value['documents'] = list(dict.fromkeys(name.strip() for name in item.text(4).split(',') if name.strip()))
                value['variants'] = [record(item.child(i), False) for i in range(item.childCount())]
            else:
                value.pop('variants', None)
                value.pop('document', None)
            if validate and (not value['scenario'] or not value['input'] or (baseline and not value['case'])):
                raise ValueError('Each baseline needs a business case ID, scenario and input; each variant needs scenario and input.')
            return value
        profile['baselines'] = [record(self.tree.topLevelItem(i), True) for i in range(self.tree.topLevelItemCount())]
        profile['document_references'] = self.reference_values()
        profile['document_comparisons'] = self.comparison_values()
        if validate:
            if not profile['family'] or not comms['package'] or not profile['baselines']:
                raise ValueError('Enter a family name, package and at least one baseline.')
            normalize_plan(profile)
        return profile
