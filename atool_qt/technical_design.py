"""Technical Design generation using the application's Python and Comms runtime."""
import json
import hashlib
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QThread, QUrl, Signal, QSettings
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                              QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                              QPlainTextEdit, QPushButton, QVBoxLayout, QTabWidget, QWidget)
from .td_profile_editor import ProfilePlanEditor
from .storage import write_files


def prepare_profile(profile_path, cache, settings, plan=None, samples=None):
    profile = deepcopy(plan) if plan is not None else json.loads(profile_path.read_text(encoding='utf-8'))
    if samples is not None:
        profile['scenarios'] = samples
    if not isinstance(profile, dict):
        raise ValueError('Profile must be a JSON object.')
    if not isinstance(profile.get('baselines'), list) or not profile['baselines']:
        raise ValueError('Define the document baselines and their input files in the profile first.')
    base = profile_path.parent
    if not isinstance(profile.get('scenarios'), str) or not profile['scenarios'].strip():
        raise ValueError('Set the scenarios folder in the profile.')
    scenario = Path(profile['scenarios']).expanduser()
    if not scenario.is_absolute():
        # Preserve existing profiles/ + samples/ folder distributions.
        candidates = [base / scenario, base.parent / scenario]
        scenario = next((path for path in candidates if path.is_dir()), candidates[0])
    if not scenario.is_dir():
        raise ValueError(f'Scenario folder does not exist: {scenario}')
    profile['scenarios'] = str(scenario.resolve())
    comms = profile.setdefault('comms', {})
    resource = str(cache or settings.get('comms_cache_dir') or comms.get('resource_cache', '')).strip()
    if not resource:
        raise ValueError('Select the downloaded Comms cache folder.')
    resource = Path(resource).expanduser()
    if not resource.is_absolute():
        resource = base / resource
    if not resource.is_dir():
        raise ValueError(f'Comms cache folder does not exist: {resource}')
    comms['resource_cache'] = str(resource.resolve())
    occs = profile['occs'] = {}
    occs.update(cli=settings.cli, timeout_ms=settings.timeout_ms)
    if settings.get('session_alias'):
        occs['session'] = settings.get('session_alias')
    return profile


class GenerationJob(QThread):
    progress = Signal(str)
    outcome = Signal(str)

    def __init__(self, options, parent):
        super().__init__(parent)
        self.options = options

    def run(self):
        try:
            from tools.td_generator.td_generator import generate
            generate(**self.options, progress=self.progress.emit)
        except Exception as error:
            self.outcome.emit(str(error))
        else:
            self.outcome.emit('')


class TechnicalDesignDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.settings = parent.comms.settings
        self.preferences = getattr(parent, 'settings', None) or QSettings('ATool', 'QtPrototype')
        self.job = None
        self.setWindowTitle('Generate Technical Design')
        self.resize(1050, 800)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.profile = QLineEdit()
        self.profile.setReadOnly(True)
        self.profile.setPlaceholderText('Unsaved profile')
        toolbar.addWidget(self.profile)
        self.profile_buttons = []
        for title, callback in [('New', self.new_profile), ('Open…', self.open_profile), ('Save', self.save_profile), ('Save As…', lambda: self.save_profile(save_as=True))]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
            self.profile_buttons.append(button)
        layout.addLayout(toolbar)
        self.tabs = QTabWidget()
        self.editor = ProfilePlanEditor()
        self.tabs.addTab(self.editor, 'Documentation plan')
        run_page = QWidget()
        run_layout = QVBoxLayout(run_page)
        self.tabs.addTab(run_page, 'Files and generation')
        layout.addWidget(self.tabs)
        form = QFormLayout()
        run_layout.addLayout(form)
        self.samples = self.path_row(form, 'Sample root folder', 'cache')
        self.cache = self.path_row(form, 'Comms cache override', 'cache')
        self.cache.setPlaceholderText(str(self.settings.get('comms_cache_dir') or 'Use Comms Cache Folder from User Settings'))
        self.output = self.path_row(form, 'Output Markdown', 'output')
        self.evidence = QComboBox()
        self.evidence.addItem('Generate fresh metadata from Comms', 'metadata')
        self.evidence.addItem('Reuse metadata beside the output file', 'cached')
        form.addRow('Scenario evidence', self.evidence)
        self.xml = QComboBox()
        for title, value in [('Convert XML only when JSON is missing', 'auto'), ('Use existing JSON only', 'never'), ('Refresh XML conversions', 'always')]:
            self.xml.addItem(title, value)
        form.addRow('Input conversion', self.xml)
        self.rebuild = QCheckBox('Rebuild the content index from the current cache')
        self.rebuild.setChecked(True)
        form.addRow(self.rebuild)
        formats = QHBoxLayout()
        self.formats = {}
        for name in ('md', 'docx', 'pdf'):
            checkbox = QCheckBox(name.upper())
            checkbox.setChecked(name == 'md')
            checkbox.setEnabled(name != 'md')
            self.formats[name] = checkbox
            formats.addWidget(checkbox)
        form.addRow('Output formats', formats)
        run_layout.addWidget(QLabel('These choices are remembered on this computer for each profile.\nPDF requires LibreOffice. The Comms connection comes from User Settings.'))
        run_layout.addStretch()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        buttons = QHBoxLayout()
        self.start = QPushButton('Generate')
        self.start.clicked.connect(self.generate)
        buttons.addWidget(self.start)
        self.open_output = QPushButton('Open output folder')
        self.open_output.setEnabled(False)
        self.open_output.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_path.parent))))
        buttons.addWidget(self.open_output)
        layout.addLayout(buttons)
        self.editor.pick_input.clicked.connect(self.choose_input)
        self.new_profile(initial=True)
        last_profile = str(self.preferences.value('technicalDesignLastProfile', '') or '')
        if last_profile:
            try:
                self.load_profile(Path(last_profile).expanduser())
            except Exception as error:
                self.new_profile(initial=True)
                self.log.appendPlainText(f'Could not reopen the last profile: {last_profile}\n{error}\nUse Open to locate a profile, or create a new one.')

    def preference_key(self):
        identity = str(Path(self.profile.text()).expanduser().resolve()) if self.profile.text() else 'new'
        return 'technicalDesign/' + hashlib.sha256(identity.encode()).hexdigest()

    def remember(self):
        values = dict(samples=self.samples.text(), cache=self.cache.text(), output=self.output.text(),
                      evidence=self.evidence.currentData(), xml=self.xml.currentData(),
                      rebuild=self.rebuild.isChecked(), formats=[key for key, box in self.formats.items() if box.isChecked()])
        self.preferences.setValue(self.preference_key(), json.dumps(values))
        if self.profile.text():
            self.preferences.setValue('technicalDesignLastProfile', self.profile.text())
        self.preferences.sync()

    def restore_run_settings(self, legacy=None):
        legacy = legacy or {}
        base = Path(self.profile.text()).parent if self.profile.text() else Path.home()
        samples = str(legacy.get('scenarios', ''))
        if samples and not Path(samples).expanduser().is_absolute():
            candidates = [base / samples, base.parent / samples]
            samples = str(next((p for p in candidates if p.is_dir()), candidates[0]))
        cache = str(legacy.get('comms', {}).get('resource_cache', ''))
        if cache and not Path(cache).expanduser().is_absolute():
            cache = str(base / cache)
        # Prefer the existing app cache setting over a legacy machine-specific path.
        if self.settings.get('comms_cache_dir'):
            cache = ''
        try:
            values = json.loads(self.preferences.value(self.preference_key(), '{}'))
        except (ValueError, TypeError):
            values = {}
        self.samples.setText(str(values.get('samples', samples)))
        self.cache.setText(str(values.get('cache', cache)))
        self.output.setText(str(values.get('output', '')))
        for widget, key, default in [(self.evidence, 'evidence', 'metadata'), (self.xml, 'xml', 'auto')]:
            widget.setCurrentIndex(max(0, widget.findData(values.get(key, default))))
        self.rebuild.setChecked(values.get('rebuild', True))
        for name, box in self.formats.items():
            box.setChecked(name == 'md' or name in values.get('formats', []))

    def confirm_discard(self):
        if self.editor.plan() == self.saved_plan:
            return True
        answer = QMessageBox.question(self, 'Unsaved documentation plan', 'Save changes to this profile?',
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_profile()
        return answer == QMessageBox.StandardButton.Discard

    def new_profile(self, checked=False, initial=False):
        if not initial:
            if not self.confirm_discard():
                return
            self.remember()
        session = getattr(self.parent(), 'session', None)
        comms = {'package': session.name if session else ''}
        if session:
            version = session.bundle.get('manifest', {}).get('version', {}).get('shortName')
            if version:
                comms['reference_version'] = version
        if hasattr(self.parent(), 'current_preview_effective_date'):
            comms['effective_date'] = self.parent().current_preview_effective_date()
        self.editor.load({'comms': comms, 'baselines': []})
        cache_root = str(self.settings.get('comms_cache_dir') or '')
        names = []
        if cache_root:
            packages = Path(cache_root).expanduser() / 'packages'
            if packages.is_dir():
                names = sorted(path.name for path in packages.iterdir() if path.is_dir())
        if session and session.name not in names:
            names.append(session.name)
        self.editor.package.clear()
        self.editor.package.addItems(names)
        self.editor.package.setCurrentText(comms['package'])
        self.profile.clear()
        self.restore_run_settings()
        self.saved_plan = self.editor.plan()

    def open_profile(self):
        if not self.confirm_discard():
            return
        start = self.profile.text() or str(self.preferences.value('technicalDesignLastProfile', '') or '')
        path = QFileDialog.getOpenFileName(self, 'Open TD profile', start, 'JSON (*.json)')[0]
        if path:
            try:
                self.load_profile(Path(path))
            except Exception as error:
                QMessageBox.warning(self, 'Open profile', str(error))

    def load_profile(self, path):
        profile = json.loads(path.read_text(encoding='utf-8'))
        self.remember()
        self.editor.load(profile)
        self.profile.setText(str(path.resolve()))
        self.restore_run_settings(profile)
        self.saved_plan = self.editor.plan()
        self.remember()

    def save_profile(self, checked=False, save_as=False):
        try:
            plan = self.editor.plan(validate=True)
            path = self.profile.text()
            if save_as or not path:
                path = QFileDialog.getSaveFileName(self, 'Save TD profile', path, 'JSON (*.json)')[0]
            if not path:
                return False
            path = Path(path).expanduser().resolve().with_suffix('.json')
            write_files({path: (json.dumps(plan, indent=2, ensure_ascii=False) + '\n').encode('utf-8')})
            self.profile.setText(str(path))
            self.saved_plan = deepcopy(plan)
            self.editor.original = deepcopy(plan)
            self.remember()
            return True
        except Exception as error:
            QMessageBox.warning(self, 'Save profile', str(error))
            return False

    def choose_input(self):
        item = self.editor.tree.currentItem()
        if item is None:
            QMessageBox.information(self, 'Choose input', 'Select a baseline or variant row first.')
            return
        root = Path(self.samples.text()).expanduser()
        if not self.samples.text().strip() or not root.is_dir():
            QMessageBox.information(self, 'Choose input', 'Select the sample root folder on Files and generation first.')
            return
        path = QFileDialog.getOpenFileName(self, 'Choose scenario input', str(root), 'Inputs (*.xml *.XML *.json *.JSON)')[0]
        if path:
            try:
                relative = Path(path).resolve().relative_to(root.resolve())
                if len(relative.parts) < 2:
                    raise ValueError('Inputs must be inside a scenario folder below the sample root.')
                item.setText(1, relative.parts[0])
                item.setText(2, relative.name)
            except ValueError as error:
                QMessageBox.warning(self, 'Choose input', str(error))

    def path_row(self, form, label, kind):
        row = QHBoxLayout()
        edit = QLineEdit()
        row.addWidget(edit)
        button = QPushButton('Browse…')
        def browse():
            if kind == 'cache':
                path = QFileDialog.getExistingDirectory(self, label, edit.text())
            elif kind == 'output':
                path = QFileDialog.getSaveFileName(self, label, edit.text(), 'Markdown (*.md)')[0]
            else:
                path = QFileDialog.getOpenFileName(self, label, edit.text(), 'JSON (*.json)')[0]
            if path:
                edit.setText(path)
        button.clicked.connect(browse)
        row.addWidget(button)
        form.addRow(label, row)
        return edit

    def generate(self):
        try:
            plan = self.editor.plan(validate=True)
            path = Path(self.profile.text()).expanduser().resolve() if self.profile.text() else Path.home() / 'untitled-td.json'
            profile = prepare_profile(path, self.cache.text(), self.settings, plan, self.samples.text())
            from tools.td_generator.td_generator import discover_scenarios, declared_baselines
            declared_baselines(profile, discover_scenarios(profile['scenarios'], path))
            if not self.output.text().strip():
                raise ValueError('Choose an output Markdown file.')
            output = Path(self.output.text()).expanduser().resolve().with_suffix('.md')
            if output.exists() and QMessageBox.question(self, 'Replace output?', f'Replace {output} and selected delivery formats?') != QMessageBox.StandardButton.Yes:
                return
            options = dict(profile_path=path, output_path=output, profile_override=profile,
                           source_mode='cached', render_evidence_mode=self.evidence.currentData(),
                           xml_conversion=self.xml.currentData(), rebuild_resource_index=self.rebuild.isChecked(),
                           formats={name for name, box in self.formats.items() if box.isChecked()})
            self.result_path = output
            self.log.clear()
            self.open_output.setEnabled(False)
            self.start.setEnabled(False)
            self.tabs.setEnabled(False)
            for button in self.profile_buttons:
                button.setEnabled(False)
            self.remember()
            self.job = GenerationJob(options, self)
            self.job.progress.connect(self.log.appendPlainText)
            self.job.outcome.connect(self.completed)
            self.job.finished.connect(self.generation_finished)
            self.job.start()
        except Exception as error:
            QMessageBox.warning(self, 'Technical Design', str(error))

    def completed(self, error):
        self.log.appendPlainText(f'ERROR: {error}' if error else 'Generation complete.')
        self.open_output.setEnabled(self.result_path.exists())

    def generation_finished(self):
        self.start.setEnabled(True)
        self.tabs.setEnabled(True)
        for button in self.profile_buttons:
            button.setEnabled(True)

    def reject(self):
        if self.job and self.job.isRunning():
            QMessageBox.information(self, 'Generation in progress', 'Wait for generation to finish before closing this window.')
            return
        if self.confirm_discard():
            self.remember()
            super().reject()

    def closeEvent(self, event):
        if self.job and self.job.isRunning():
            event.ignore()
        elif self.confirm_discard():
            self.remember()
            # QDialog.closeEvent calls reject; bypass a second save prompt.
            self.saved_plan = self.editor.plan()
            super().closeEvent(event)
        else:
            event.ignore()
