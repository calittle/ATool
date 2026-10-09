"""Package preview controls and independent, cancellable rendering operations."""
import json
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QCheckBox, QDateEdit, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout)
from .shared_packages import bundle_hashes, manifest, names, segment

RENDER_TYPES = ('PDF', 'HTML', 'TEXT', 'CSV', 'JSON', 'METADATA')


def exclude_charts(payload):
    if isinstance(payload, dict):
        return {key: exclude_charts(value) for key, value in payload.items() if key != 'charts'}
    if isinstance(payload, list):
        return [exclude_charts(value) for value in payload]
    return payload


def preview_outputs(stdout):
    outputs, seen = [], set()
    for line in stdout.splitlines():
        line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
        match = re.search(r'Preview written \[([A-Z]+)\](?:\s+\[[^\]]+\])?\s+to\s+(.+)$', line)
        if match and match.groups() not in seen:
            seen.add(match.groups())
            outputs.append(dict(renderType=match[1], path=match[2].strip()))
    return outputs


class PreviewDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        self.setWindowTitle('Preview Package')
        self.resize(650, 380)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow('Package', QLabel(names(workspace.session.bundle['manifest'])[0]))
        mapped_path = workspace.mapped_data_path()
        self.input = QLineEdit(str(mapped_path or ''))
        self.input.setReadOnly(bool(mapped_path))
        input_row = QHBoxLayout()
        input_row.addWidget(self.input)
        if not mapped_path:
            browse = QPushButton('Browse…')
            browse.clicked.connect(self.browse)
            input_row.addWidget(browse)
        form.addRow('Mapped Data' if mapped_path else 'JSON File', input_row)
        self.pre = QCheckBox('Use Pre-Prod Session Alias for this preview')
        form.addRow(self.pre)
        selected = workspace.comms.settings.get('last_preview_render_types') or ['PDF']
        self.renders = {}
        render_row = QHBoxLayout()
        for name in RENDER_TYPES:
            check = QCheckBox(name)
            check.setChecked(name in selected)
            self.renders[name] = check
            render_row.addWidget(check)
        form.addRow('Render Types', render_row)
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 2147483)
        try:
            seconds = int(workspace.comms.settings.get('last_preview_timeout_seconds') or workspace.comms.settings.timeout_ms // 1000)
        except (ValueError, TypeError):
            seconds = workspace.comms.settings.timeout_ms // 1000
        self.timeout.setValue(seconds)
        form.addRow('Timeout (seconds)', self.timeout)
        self.effective = QDateEdit(QDate.fromString(workspace.preview_effective_date, 'yyyy-MM-dd'))
        self.effective.setCalendarPopup(True)
        self.effective.setDisplayFormat('yyyy-MM-dd')
        form.addRow('Effective date', self.effective)
        self.exclude = QCheckBox('Exclude Charts')
        self.open_after = QCheckBox('Open after generation')
        self.open_after.setChecked(True)
        form.addRow(self.exclude)
        form.addRow(self.open_after)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addStretch()
        cancel, submit = QPushButton('Cancel'), QPushButton('Preview')
        submit.setDefault(True)
        cancel.clicked.connect(self.reject)
        submit.clicked.connect(self.submit)
        row.addWidget(cancel)
        row.addWidget(submit)
        layout.addLayout(row)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select JSON File', '', 'JSON Files (*.json);;All Files (*)')
        if path:
            self.input.setText(path)

    def submit(self):
        if self.workspace.start_package_preview(self.input.text(), [name for name, check in self.renders.items() if check.isChecked()],
                self.timeout.value(), self.effective.date().toString('yyyy-MM-dd'), pre=self.pre.isChecked(),
                exclude=self.exclude.isChecked(), open_after=self.open_after.isChecked()):
            self.accept()


class PackagePreviewActions:
    def install_preview_actions(self):
        self.preview_job = None
        self.preview_effective_date = date.today().isoformat()
        self.preview_action = self.action('Preview…', self.preview_package, 'Ctrl+P')
        self.cancel_preview_action = self.action('Cancel Preview', self.cancel_package_preview, 'Ctrl+.')
        self.package_menu.insertAction(self.publish_action, self.preview_action)
        self.package_menu.insertAction(self.publish_action, self.cancel_preview_action)
        self.package_menu.aboutToShow.connect(self.update_preview_actions)

    def mapped_data_path(self):
        if self.session and self.session.mapped:
            path = Path(self.session.data_name).expanduser()
            if path.is_file():
                return path
            loaded = str(self.settings.value('lastDataFile', '') or '')
            if loaded:
                loaded_path = Path(loaded).expanduser()
                if loaded_path.name == path.name and loaded_path.is_file():
                    return loaded_path
        return None

    def update_preview_actions(self):
        if hasattr(self, 'preview_action'):
            running = bool(self.preview_job and not self.preview_job.done)
            self.preview_action.setEnabled(bool(self.current_bundle_dir()) and not running and not self.package_busy())
            self.cancel_preview_action.setEnabled(running)

    def preview_package(self):
        if not self.current_bundle_dir() or self.package_busy() or (self.preview_job and not self.preview_job.done):
            return
        self.preview_dialog = PreviewDialog(self)
        self.preview_dialog.show()

    def preview_unpublished_reasons(self):
        reasons = []
        if self.editor and self.editor.dirty:
            reasons.append('Current package has unsaved local edits.')
        roots = [(self.current_bundle_dir(), 'Local package copy')]
        if self.shared_package_dir:
            roots.append((Path(self.shared_package_dir) / 'published' / 'current', 'Shared package folder'))
        for root, label in roots:
            if not root:
                continue
            try:
                sources = manifest(root).get('sourceHashes')
                hashes = bundle_hashes(root)
                if isinstance(sources, dict) and any(key in hashes and hashes[key] != str(value) for key, value in sources.items()):
                    reasons.append(label + ' differs from the last Comms publish.')
            except (OSError, ValueError) as error:
                reasons.append(f'Could not verify {label.lower()}: {error}')
        return reasons

    def start_package_preview(self, input_path, renders, seconds, effective, *, pre=False, exclude=False, open_after=True):
        temporary = None
        if not self.current_bundle_dir() or self.package_busy() or (self.preview_job and not self.preview_job.done):
            return False
        try:
            source = Path(input_path).expanduser()
            if not input_path.strip() or not source.is_file():
                raise ValueError('Select an existing JSON file.')
            if not renders or any(name not in RENDER_TYPES for name in renders):
                raise ValueError('Select at least one render type.')
            if int(seconds) <= 0:
                raise ValueError('Timeout must be a positive number of seconds.')
            date.fromisoformat(effective)
            alias = str(self.comms.settings.get('pre_prod_session_alias') or '').strip()
            if pre and not alias:
                raise ValueError('Set a Pre-Prod Session Alias in User Settings first.')
            reasons = self.preview_unpublished_reasons()
            if reasons and QMessageBox.question(self, 'Preview Package', 'Local and/or Shared Changes have not been published to Comms; preview anyway?\n\n' + '\n'.join(reasons)) != QMessageBox.StandardButton.Yes:
                return False
            package = names(self.session.bundle['manifest'])[0]
            output = source.parent / f"{source.stem}-{segment(package)}-{'pre' if pre else 'non'}-{datetime.now():%Y-%m-%d_%H-%M-%S}"
            args = ['preview', '--package', package, '--input', str(source), '--output', str(output),
                    '--timeout', str(int(seconds) * 1000), '--effective-date', effective, '--render-type', *renders]
            if pre:
                args[1:1] = ['--session', alias]
            if exclude:
                payload = json.loads(source.read_text(encoding='utf-8-sig'))
                temporary = tempfile.TemporaryDirectory(prefix='atool-preview-')
                path = Path(temporary.name) / 'input.json'
                path.write_text(json.dumps(exclude_charts(payload), ensure_ascii=False), encoding='utf-8')
                args[args.index('--input') + 1] = str(path)
            settings = self.comms.settings
            settings.payload.setdefault('occs', {}).update(last_preview_render_types=renders, last_preview_timeout_seconds=int(seconds))
            settings.save()
            self.preview_effective_date = effective
            def complete(result):
                self.log('Preview complete.\n' + (result.stdout or ', '.join(renders)))
                self.statusBar().showMessage('Preview complete.', 7000)
                outputs = preview_outputs(result.stdout)
                errors = []
                if open_after:
                    for item in outputs:
                        try:
                            self.open_output_file(item['renderType'], item['path'])
                        except OSError as error:
                            errors.append(str(error))
                if errors:
                    QMessageBox.warning(self, 'Open Preview', 'Preview files were generated, but could not all be opened.\n\n' + '\n'.join(errors))
            job = self.run_comms_operation('Preview Package', args, complete, channel='preview', timeout_ms=int(seconds)*1000+30000, close_on_success=True)
            self.preview_job = job
            def finished(_):
                if temporary:
                    temporary.cleanup()
                self.update_preview_actions()
            job.completed.connect(finished)
            self.update_preview_actions()
            return True
        except (ValueError, OSError) as error:
            if temporary:
                temporary.cleanup()
            self.report_error('Preview Package', str(error))
            return False

    def cancel_package_preview(self):
        if self.preview_job and not self.preview_job.done:
            self.preview_job.cancel()
