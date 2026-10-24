"""Manual, offline JSONPath length audit available in native releases."""
import copy
from pathlib import Path

from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog,
                              QLabel, QPlainTextEdit, QPushButton, QVBoxLayout)

from atool_core.jsonpath_preflight import audit_length_paths


class JSONPathAuditDialog(QDialog):
    def __init__(self, workspace, findings):
        super().__init__(workspace)
        self.workspace = workspace
        self.source = workspace.session.source
        self.setWindowTitle('Audit JSONPaths')
        self.resize(860, 580)
        layout = QVBoxLayout(self)
        count = len(findings)
        self.summary = QLabel(f'{count} expression{"s" if count != 1 else ""} to review.' if findings else 'No matching length/path expressions found.')
        layout.addWidget(self.summary)
        lines = ['JSONPath length audit', f'Package: {workspace.session.name}',
                 f'Source: {workspace.session.source or "Unsaved template"}', '',
                 'Scope: the open template, including unsaved edits and the current clause library.',
                 'Experimental check: length() with relative or recursive paths.',
                 "PD's restriction is still being clarified; findings are review candidates, not confirmed defects.",
                 'This manual audit runs independently of the automatic preflight setting.', '']
        if not findings:
            lines.append('No matching length/path expressions found.')
        for index, finding in enumerate(findings, 1):
            lines.extend([f'{index}. {" / ".join(finding["owners"]) or "Unnamed owner"}',
                          f'Location: {finding["path"]}', f'Expression: {finding["expression"]}', ''])
        self.report = QPlainTextEdit('\n'.join(lines))
        self.report.setReadOnly(True)
        layout.addWidget(self.report, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.copy_button = buttons.addButton('Copy Report', QDialogButtonBox.ButtonRole.ActionRole)
        self.save_button = buttons.addButton('Save Report…', QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.report.toPlainText()))
        self.save_button.clicked.connect(self.save_report)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save_report(self):
        filename, _ = QFileDialog.getSaveFileName(self, 'Save JSONPath Audit Report', 'jsonpath-audit.txt', 'Text files (*.txt)')
        if not filename:
            return
        destination = Path(filename).expanduser().resolve()
        # A report must never overwrite the template being audited.
        if self.source and destination == Path(self.source).resolve():
            self.workspace.report_error('Save Audit Report', 'Choose a report file separate from the Assembly Template.')
            return
        try:
            destination.write_text(self.report.toPlainText() + '\n', encoding='utf-8')
        except OSError as error:
            self.workspace.report_error('Save Audit Report', str(error))


class JSONPathAuditActions:
    def install_jsonpath_audit(self):
        self.jsonpath_audit_action = self.action('Audit JSONPaths…', self.audit_jsonpaths)
        self.package_menu.addAction(self.jsonpath_audit_action)
        self.package_menu.aboutToShow.connect(self.update_jsonpath_audit_action)
        self.update_jsonpath_audit_action()

    def update_jsonpath_audit_action(self):
        self.jsonpath_audit_action.setEnabled(self.session is not None and not self.package_busy())

    def audit_jsonpaths(self):
        if self.session is None or self.package_busy():
            return
        try:
            self.flush_properties()
        except ValueError as error:
            self.report_error('Audit JSONPaths', str(error))
            return
        payload = copy.deepcopy(self.session.payload)
        # Clauses may have been edited independently of the embedded metadata.
        meta = payload.get('Meta')
        if isinstance(meta, dict):
            meta.pop('clause_library', None)
            meta.pop('condition_library', None)
            if isinstance(meta.get('ATool'), dict):
                meta['ATool'].pop('clause_library', None)
        findings = audit_length_paths(payload)
        findings.extend(audit_length_paths(self.session.clauses, '$.clause_library'))
        self.jsonpath_audit_dialog = JSONPathAuditDialog(self, findings)
        self.jsonpath_audit_dialog.show()
