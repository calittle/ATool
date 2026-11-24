"""Read-only configuration inventory from the CLI preflight report."""
import tempfile

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .grids import configure_grid


class ConfigObjectsDialog(QDialog):
    def __init__(self, workspace, config, session_alias, *, parent=None):
        super().__init__(parent if parent is not None else workspace)
        self.workspace, self.config, self.session_alias = workspace, dict(config), session_alias
        self.job = None
        self.closed = False
        self.report_folder = tempfile.TemporaryDirectory(prefix='atool-config-objects-')
        self.setWindowTitle('Config Objects — ' + (config.get('shortName') or config['id']))
        self.resize(1050, 600)
        layout = QVBoxLayout(self)
        heading = QLabel(f"Session: {session_alias or 'OCCS default session'} · Config: {config['id']}")
        layout.addWidget(heading)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter objects, changes, or dependencies')
        row.addWidget(self.search, 1)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.load_objects)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.tabs = QTabWidget()
        self.objects = self.add_table('Attached Objects', ['Type', 'Name', 'Version', 'Status', 'Object ID'])
        self.changes = self.add_table('Changes', ['Type', 'Name', 'Operation', 'Object ID'])
        self.dependencies = self.add_table('Dependencies', ['Type / Name', 'Version', 'Owner Config', 'Status'])
        layout.addWidget(self.tabs, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self.filter_objects)
        self.finished.connect(self.finish)
        self.load_objects()

    def add_table(self, title, headers):
        tree = QTreeWidget()
        tree.setHeaderLabels(headers)
        tree.setRootIsDecorated(title == 'Dependencies')
        configure_grid(tree)
        self.tabs.addTab(tree, title)
        return tree

    def load_objects(self):
        if self.closed or (self.job is not None and not self.job.done):
            return
        self.refresh_button.setEnabled(False)
        self.status.setText('Loading objects, registry changes, and dependencies. Large configs can take several minutes.')
        args = ['preflight', '--config-id', self.config['id'], '--list-attached', '--deep', '--show-blockers',
                '--output', self.report_folder.name, '--timeout', str(self.workspace.comms.settings.timeout_ms)]
        if self.session_alias:
            args += ['--session', self.session_alias]

        def loaded(result):
            if self.closed:
                return
            value = result.value
            reports = value.get('results') if isinstance(value, dict) else None
            if not isinstance(reports, list) or len(reports) != 1 or not isinstance(reports[0], dict):
                raise ValueError('Comms did not return a report for the selected configuration.')
            report = reports[0]
            if str(report.get('configurationId')) != self.config['id']:
                raise ValueError('Comms returned objects for a different configuration. Refresh the config list and try again.')
            session = value.get('session')
            if self.session_alias and (not isinstance(session, dict) or session.get('alias') != self.session_alias):
                raise ValueError('Comms did not confirm the selected environment for this report.')
            for key in ('attachedRows', 'registryChanges', 'deepChains'):
                if not isinstance(report.get(key), list) or any(not isinstance(row, dict) for row in report[key]):
                    raise ValueError('Comms returned an incomplete object report. Refresh and try again.')
            self.show_report(report)

        def failed(message):
            if not self.closed:
                self.status.setText('Could not refresh objects. Any displayed rows are from the previous scan.\n' + message)

        self.job = self.workspace.run_comms_operation('Load Config Objects', args, loaded, require_json=True,
                                                     on_failure=failed)
        self.job.completed.connect(self.completed)

    def completed(self, result):
        if self.closed:
            self.report_folder.cleanup()
        else:
            self.refresh_button.setEnabled(True)
            if result.cancelled:
                self.status.setText('Scan canceled. Any displayed rows are from the previous scan.')

    def show_report(self, report):
        for tree in (self.objects, self.changes, self.dependencies):
            tree.clear()
        for row in report.get('attachedRows', []):
            QTreeWidgetItem(self.objects, [str(row.get(key) or '') for key in
                                          ('domainNameDisplay', 'name', 'versionName', 'statusCode', 'recUuid')])
        # Registry changes include standalone fonts/styles and association changes.
        for row in report.get('registryChanges', []):
            QTreeWidgetItem(self.changes, [str(row.get(key) or '') for key in ('label', 'name', 'operation', 'recUuid')])
        for chain in report.get('deepChains', []):
            package, document = chain['packageVersion'], chain['documentVersion']
            parent = QTreeWidgetItem(self.dependencies, self.dependency_values('Package', package))
            child = QTreeWidgetItem(parent, self.dependency_values('Document', document))
            if chain.get('externalOwner'):
                child.setToolTip(2, 'This dependency belongs to another configuration.')
            for row in document.get('layouts', []):
                QTreeWidgetItem(child, self.dependency_values('Layout', row))
        self.dependencies.expandAll()
        self.status.setText(f"{self.objects.topLevelItemCount()} attached objects · "
                            f"{self.changes.topLevelItemCount()} registry changes · "
                            f"{report.get('inflightCount', 0)} in-flight items")
        self.filter_objects()

    @staticmethod
    def dependency_values(kind, row):
        return [kind + ': ' + str(row.get('name') or row.get('configUuid') or row.get('recUuid') or ''),
                str(row.get('versionName') or row.get('documentVersion') or ''),
                str(row.get('ownerShortName') or row.get('ownerConfigurationId') or 'Unknown'),
                str(row.get('statusCode') or row.get('ownerStatus') or row.get('relationStatusCode') or '')]

    def filter_objects(self):
        query = self.search.text().strip().casefold()
        def visit(item, parent_matches=False):
            own_match = parent_matches or query in ' '.join(item.text(i) for i in range(item.columnCount())).casefold()
            children = [visit(item.child(i), own_match) for i in range(item.childCount())]
            visible = own_match or any(children)
            item.setHidden(not visible)
            return visible
        for tree in (self.objects, self.changes, self.dependencies):
            for index in range(tree.topLevelItemCount()):
                visit(tree.topLevelItem(index))

    def finish(self, *_):
        self.closed = True
        if self.job is not None and not self.job.done:
            self.job.cancel()
        else:
            self.report_folder.cleanup()
