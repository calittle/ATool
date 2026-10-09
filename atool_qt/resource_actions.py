"""Resource downloads and cached document model actions."""
from __future__ import annotations

import copy
import platform
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

RESOURCE_TYPES = (
    ('Package', 'get-package', 'list-packages', 'packages'),
    ('Style', 'get-style', 'list-styles', 'styles'),
    ('Layout', 'get-layout', 'list-layouts', 'layouts'),
    ('Content', 'get-content', 'list-contents', 'contents'),
    ('Font', 'get-font', 'list-fonts', 'fonts'),
    ('Document', 'get-document', 'list-documents', 'documents'),
    ('Chart', 'get-chart', 'list-charts', 'charts'),
)


def cache_has_files(path):
    try:
        return path.is_dir() and any(item.is_file() for item in path.rglob('*'))
    except OSError:
        return False


class ResourceDialog(QDialog):
    def __init__(self, workspace, single):
        super().__init__(workspace)
        self.workspace, self.single = workspace, single
        self.setWindowTitle('Download Single Resource' if single else 'Download Resources')
        self.resize(660, 300)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.resource_name, self.resource_type = QLineEdit(), QComboBox()
        self.resource_type.addItems([row[0] for row in RESOURCE_TYPES])
        if single:
            form.addRow('Resource name', self.resource_name)
        form.addRow('Type', self.resource_type)
        self.recent = QComboBox()
        self.recent.addItem('Choose a recent resource', None)
        entries = workspace.comms.settings.get('resource_cache_mru') or []
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get('type') in [row[0] for row in RESOURCE_TYPES] and entry.get('name'):
                self.recent.addItem(f"{entry['type']}: {entry['name']}", entry)
        if single:
            form.addRow('Recent', self.recent)
        self.recent.currentIndexChanged.connect(self.use_recent)
        layout.addLayout(form)
        self.status = QLabel('Cache folder: ' + str(workspace.comms.settings.get('comms_cache_dir') or 'not configured'))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Refresh Cache' if single else 'Download')
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def use_recent(self, *_):
        entry = self.recent.currentData()
        if entry:
            self.resource_name.setText(entry['name'])
            self.resource_type.setCurrentText(entry['type'])

    def submit(self):
        name = self.resource_name.text().strip()
        if self.single and not name:
            self.status.setText('A resource name is required.')
            return
        try:
            self.workspace.download_resource(self.resource_type.currentText(), name if self.single else None)
            self.accept()
        except (ValueError, OSError) as error:
            self.status.setText(str(error))


class ResourceModelActions:
    def install_resource_model_actions(self):
        self.download_all_job = None
        menu = self.menuBar().addMenu('&Resources')
        for title, callback in [('Download Single…', lambda: self.open_resource_download(single=True)),
                                ('Download…', self.open_resource_download), ('Download All', self.download_all_resources)]:
            if title == 'Download All':
                menu.addSeparator()
            menu.addAction(self.action(title, callback))
        self.cancel_download_all_action = self.action('Cancel Download All', self.cancel_download_all)
        menu.addAction(self.cancel_download_all_action)
        self.cancel_download_all_action.setEnabled(False)
        menu = self.menuBar().addMenu('&Model')
        self.model_actions = {}
        for title, callback in [('View', lambda: self.document_model(open_after=True)),
                                ('Generate', lambda: self.document_model(regenerate=True)),
                                ('Generate all', self.generate_all_models)]:
            self.model_actions[title] = self.action(title, callback)
            menu.addAction(self.model_actions[title])
        self.documents.selected.connect(self.update_model_actions)
        self.update_model_actions()

    def update_model_actions(self, *_):
        session = self.session
        document = self.selected_record('documents')
        available = bool(session) and not self.package_busy()
        self.model_actions['Generate all'].setEnabled(available)
        self.model_actions['Generate all'].setText('Generate all' + (f' ({session.name})' if session else ''))
        for title in ('View', 'Generate'):
            self.model_actions[title].setEnabled(bool(available and document and document.get('in_at')))
            self.model_actions[title].setText(title + (f" ({document['name']})" if document else ''))

    def open_resource_download(self, *, single=False):
        self.resource_dialog = ResourceDialog(self, single)
        self.resource_dialog.show()

    def resource_cache(self):
        value = str(self.comms.settings.get('comms_cache_dir') or '').strip()
        if not value:
            raise ValueError('Set a Comms Cache Folder in User Settings before downloading resources.')
        return Path(value).expanduser()

    def download_resource(self, resource_type, name=None):
        spec = next((row for row in RESOURCE_TYPES if row[0] == resource_type), None)
        if spec is None:
            raise ValueError('Select a valid resource type.')
        cache = self.resource_cache() / spec[3]
        if name is not None:
            payload = copy.deepcopy(self.comms.settings.payload)
            entries = payload.setdefault('occs', {}).get('resource_cache_mru') or []
            entries = [entry for entry in entries if isinstance(entry, dict) and not (str(entry.get('name') or '').casefold() == name.casefold() and entry.get('type') == resource_type)] if isinstance(entries, list) else []
            payload['occs']['resource_cache_mru'] = [{'type': resource_type, 'name': name, 'lastUsedAt': datetime.now().isoformat()}, *entries][:5]
            self.comms.settings.save(payload)
        args = [spec[1], name, '--output', str(cache)] if name is not None else [spec[2], '--output', str(cache)]
        return self.run_comms_operation('Download ' + resource_type, args, channel='resources')

    def download_all_resources(self):
        if self.download_all_job and not self.download_all_job.done:
            return
        try:
            cache = self.resource_cache()
        except ValueError as error:
            self.report_error('Download All Resources', str(error))
            return
        job = self.run_comms_operation('Download All Resources', ['get-everything', '--output', str(cache)], channel='download_all')
        self.download_all_job = job
        self.cancel_download_all_action.setEnabled(True)
        job.completed.connect(lambda result: self.cancel_download_all_action.setEnabled(False))

    def cancel_download_all(self):
        if self.download_all_job:
            self.download_all_job.cancel()

    def open_output_file(self, render_type, path):
        path = Path(path)
        if not path.is_file():
            raise OSError(f'File not found: {path}')
        programs = self.comms.settings.get('preview_open_programs') or {}
        program = str(programs.get(render_type, '') or '').strip() if isinstance(programs, dict) else ''
        if program:
            executable, args = ('open', ['-a', program, str(path)]) if platform.system() == 'Darwin' else (program, [str(path)])
            started, _ = QProcess.startDetached(executable, args)
            if not started:
                raise OSError(f'Could not open {path.name} with {program}.')
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            raise OSError(f'Could not open {path.name}.')

    def model_paths(self, document=None):
        models = str(self.comms.settings.get('models_dir') or '').strip()
        if not models:
            raise ValueError('Set Models Folder in User Settings before generating or viewing a document model.')
        output = Path(models).expanduser() / self.session.name
        return output / (document['name'] + '-inspector.html') if document else output

    def document_model(self, *, open_after=False, regenerate=False):
        from PySide6.QtCore import Qt
        regenerate = regenerate or bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        document = self.selected_record('documents')
        if not self.session or not document or not document.get('in_at'):
            return
        try:
            output = self.model_paths(document)
            if output.is_file() and not regenerate:
                self.open_output_file('HTML', output)
                return
            cache = self.resource_cache()
            if not cache_has_files(cache):
                raise ValueError('Download Comms resources before generating a document model.')
            output.parent.mkdir(parents=True, exist_ok=True)
            args = ['mockup', document['name'], '--cache', str(cache), '--package', self.session.name, '--output', str(output)]
            def complete(result):
                if not output.is_file():
                    raise ValueError('Comms mockup completed but did not create the inspector file.')
                if open_after:
                    self.open_output_file('HTML', output)
                self.statusBar().showMessage('Generated model for ' + document['name'], 5000)
            self.run_comms_operation('Generate Document Model', args, complete, close_on_success=True)
        except (ValueError, OSError) as error:
            self.report_error('Model', str(error))

    def generate_all_models(self):
        if not self.session:
            return
        try:
            output, cache = self.model_paths(), self.resource_cache()
            if not cache_has_files(cache):
                raise ValueError('Download Comms resources before generating package models.')
            output.mkdir(parents=True, exist_ok=True)
            self.run_comms_operation('Generate All Models', ['mockup', '--package', self.session.name, '--all', '--cache', str(cache), '--output', str(output)], close_on_success=True)
        except (ValueError, OSError) as error:
            self.report_error('Generate All Models', str(error))
