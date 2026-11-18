"""Suite-driven smoke runs through the configured OCCS CLI, independent of the open package."""
from __future__ import annotations

import copy
import json
import math
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                              QPushButton, QVBoxLayout)

from .shared_packages import segment


def validate_smoke_settings(value):
    for key in ('suite_dir','output_dir',
                'comparison_source_tenancy','comparison_source_session','comparison_target_tenancy',
                'comparison_target_session','browser_path','tools_path'):
        if not isinstance(value.get(key,''),str):
            raise ValueError('Smoke test '+key.replace('_',' ')+' must be text.')
    for key in ('run_standard','run_comparison'):
        if not isinstance(value.get(key,True),bool):
            raise ValueError('Smoke test run options must be true or false.')
    for key,minimum,maximum,default in (('request_timeout_seconds',1,86400,60),
                                       ('run_timeout_minutes',1,1440,120),('concurrency',1,2,2)):
        number=value.get(key,default)
        if isinstance(number,bool) or not isinstance(number,int) or not minimum<=number<=maximum:
            raise ValueError(f'Smoke test {key.replace("_"," ")} must be a whole number between {minimum} and {maximum}.')
    threshold=value.get('comparison_threshold_percent',1.0)
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<=threshold<=100:
        raise ValueError('Smoke test Allowed Changed Pixels must be between 0 and 100 percent.')


def discover_smoke_suites(settings):
    """Read names from suite JSONs, ignoring data files and malformed suites."""
    directory=settings.get('suite_dir','').strip()
    if not directory:
        raise ValueError('Choose a Suite JSON Folder in Settings → User Settings → Smoke Tests.')
    root=Path(directory).expanduser().resolve()
    try:
        files=sorted(root.iterdir(),key=lambda path:path.name.casefold())
    except OSError as error:
        raise ValueError(f'Could not read smoke suite folder: {error}') from error
    suites=[]
    skipped=0
    for source in files:
        if source.suffix.lower()!='.json' or not source.is_file():
            continue
        try:
            suite=json.loads(source.read_text(encoding='utf-8-sig'))
            if (not isinstance(suite,dict) or not isinstance(suite.get('name'),str)
                    or not suite['name'].strip() or not isinstance(suite.get('tests'),list)
                    or not suite['tests']):
                skipped+=1
                continue
            suites.append((suite['name'].strip(),source))
        except (OSError,ValueError):
            skipped+=1
    return sorted(suites,key=lambda suite:suite[0].casefold()),skipped


def suite_standard_target(suite):
    """Match the CLI's suite session precedence, without using global defaults."""
    for key,option in (('session','--session'),('tenancy','--tenancy'),('environment','--tenancy')):
        value=suite.get(key)
        if value is None or value=='':
            continue
        if not isinstance(value,str):
            raise ValueError(f'The smoke suite {key} must be text.')
        if value.strip():
            return value.strip(),[option,value.strip()]
    raise ValueError('Define a tenancy or session in the suite JSON for the standard test.')


def smoke_plan(settings, standard, comparison, resume=False, suite_path=None):
    """Validate inputs and build an explicit plan without invoking a remote operation."""
    validate_smoke_settings(settings)
    if not standard and not comparison:
        raise ValueError('Select a standard test, a comparison, or both.')
    directory=settings.get('suite_dir','').strip()
    if not directory:
        raise ValueError('Choose a Suite JSON Folder in Settings → User Settings → Smoke Tests.')
    if not suite_path:
        raise ValueError('Select a smoke suite by name before running.')
    source=Path(suite_path).expanduser().resolve()
    if source.parent!=Path(directory).expanduser().resolve() or source.suffix.lower()!='.json':
        raise ValueError('Select a JSON suite from the configured Suite JSON Folder.')
    try:
        suite=json.loads(source.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError) as error:
        raise ValueError(f'Could not read smoke suite {source}: {error}') from error
    if not isinstance(suite,dict) or not isinstance(suite.get('tests'),list) or not suite['tests']:
        raise ValueError('The smoke suite must contain a non-empty tests list.')
    suite=copy.deepcopy(suite)
    for index,test in enumerate(suite['tests'],1):
        if not isinstance(test,dict) or not isinstance(test.get('package'),str) or not test['package'].strip() or not isinstance(test.get('input'),str) or not test['input'].strip():
            raise ValueError(f'Smoke test {index} needs a package and an input file.')
        path=(source.parent/Path(test['input']).expanduser()).resolve()
        if not path.is_file():
            raise ValueError(f'Smoke test {index} input file does not exist: {path}')
        test['input']=str(path)
    standard_target=suite_standard_target(suite) if standard else None
    # Pass each run's chosen target explicitly. Suite session aliases otherwise
    # override comparison settings, and suite compare fields can enable comparison
    # during a standard run. Never modify the original JSON.
    for key in ('session','tenancy','environment','compareSession','compareTenancy'):
        suite.pop(key,None)
    suite.setdefault('name',source.stem)
    output=Path(settings.get('output_dir','').strip() or source.parent).expanduser().resolve()
    def target(prefix,compare=False):
        alias=settings.get(prefix+'_session','').strip()
        tenancy=settings.get(prefix+'_tenancy','').strip()
        if not alias and not tenancy:
            raise ValueError('Set a tenancy or session alias for '+prefix.replace('_',' ')+'.')
        option=('--compare-session' if compare else '--session') if alias else ('--compare-tenancy' if compare else '--tenancy')
        return alias or tenancy,[option,alias or tenancy]
    runs=[]
    if standard:
        label,args=standard_target
        runs.append(dict(label='Standard: '+label,args=args,output=output/('smoke-output-'+segment(label))))
    if comparison:
        left,args=target('comparison_source')
        right,compare_args=target('comparison_target',True)
        runs.append(dict(label='Comparison: '+left+' → '+right,
                         args=args+compare_args+['--compare-threshold',str(settings.get('comparison_threshold_percent',1.0)/100)],
                         output=output/('smoke-output-'+segment(left)+'-vs-'+segment(right))))
    for run in runs:
        run['args']+=['--output',str(run['output']),'--timeout',str(settings.get('request_timeout_seconds',60)*1000),
                      '--concurrency',str(settings.get('concurrency',2))]
        if resume:
            run['args'].append('--resume')
    return dict(source=source,suite=suite,output=output,runs=runs,
                timeout_ms=settings.get('run_timeout_minutes',120)*60000)


class SmokeTestDialog(QDialog):
    def __init__(self,workspace):
        super().__init__(workspace)
        self.workspace=workspace
        self.running=False
        self.stopping=False
        self.job=None
        self.temporary=None
        self.reports=[]
        self.failures=0
        self.setWindowTitle('Run Smoke Tests')
        self.resize(800,560)
        layout=QVBoxLayout(self)
        settings=workspace.comms.settings.section('smoke_tests')
        suite=QLabel()
        self.suite_label=suite
        suite.setWordWrap(True)
        layout.addWidget(suite)
        suite_row=QHBoxLayout()
        suite_row.addWidget(QLabel('Suite:'))
        self.suite_combo=QComboBox()
        self.suite_combo.setToolTip('Select a smoke suite by the name stored in its JSON file.')
        suite_row.addWidget(self.suite_combo,1)
        self.refresh_button=QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.refresh_suites)
        suite_row.addWidget(self.refresh_button)
        layout.addLayout(suite_row)
        self.suite_status=QLabel()
        self.suite_status.setWordWrap(True)
        layout.addWidget(self.suite_status)
        self.standard=QCheckBox('Standard test — tenancy from suite JSON')
        self.suite_combo.currentIndexChanged.connect(self.refresh_standard_target)
        self.comparison=QCheckBox('Compare '+str(settings.get('comparison_source_session') or settings.get('comparison_source_tenancy'))+
                                 ' → '+str(settings.get('comparison_target_session') or settings.get('comparison_target_tenancy')))
        self.standard.setChecked(settings.get('run_standard',True))
        self.comparison.setChecked(settings.get('run_comparison',True))
        self.resume=QCheckBox('Resume the most recent matching run (retry missing outputs)')
        self.standard.setToolTip('Generate the suite previews in the tenancy or session defined in the selected suite JSON. This does not compare environments.')
        self.comparison.setToolTip('Generate the same suite previews in both configured comparison environments and compare their appearance.')
        self.resume.setToolTip('Reuse the most recent matching timestamped output folder for each selected run. '
                               'Keep existing successful outputs and retry missing or failed previews. '
                               'Leave unchecked to generate all previews again in a new folder.')
        for control in (self.standard,self.comparison,self.resume):
            layout.addWidget(control)
        hint=QLabel('Runs the packages and inputs in the selected suite. Unsaved changes in the open package are not included. Email drafts are saved without sending.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.status=QLabel('Ready.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.output=QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output,1)
        row=QHBoxLayout()
        self.settings_button=QPushButton('Settings…')
        self.settings_button.clicked.connect(workspace.open_smoke_settings)
        row.addWidget(self.settings_button)
        self.report_button=QPushButton('Open Reports')
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(self.open_reports)
        row.addWidget(self.report_button)
        self.folder_button=QPushButton('Open Output Folder')
        self.folder_button.setEnabled(False)
        self.folder_button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.plan['output']))))
        row.addWidget(self.folder_button)
        row.addStretch()
        self.run_button=QPushButton('Run')
        self.run_button.clicked.connect(self.start)
        row.addWidget(self.run_button)
        self.cancel_button=QPushButton('Close')
        self.cancel_button.clicked.connect(self.cancel_or_close)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.finished.connect(lambda _:self.stop() if self.running else None)
        self.refresh_suites()

    def start(self):
        if self.running or self.workspace.package_busy():
            return
        try:
            self.plan=smoke_plan(self.workspace.comms.settings.section('smoke_tests'),self.standard.isChecked(),self.comparison.isChecked(),self.resume.isChecked(),
                                 suite_path=self.suite_combo.currentData())
            self.plan['output'].mkdir(parents=True,exist_ok=True)
            self.temporary=tempfile.TemporaryDirectory(prefix='atool-smoke-')
            self.suite_path=Path(self.temporary.name)/'smoke-suite.json'
            self.suite_path.write_text(json.dumps(self.plan['suite'],ensure_ascii=False,indent=2),encoding='utf-8')
        except (OSError,ValueError) as error:
            if self.temporary:
                self.temporary.cleanup()
                self.temporary=None
            self.status.setText(str(error))
            return
        self.reports=[]
        self.failures=0
        self.output.clear()
        self.running=True
        self.stopping=False
        self.queue=list(self.plan['runs'])
        for control in (self.standard,self.comparison,self.resume,self.run_button,self.settings_button,self.suite_combo,self.refresh_button):
            control.setEnabled(False)
        self.report_button.setEnabled(False)
        self.folder_button.setEnabled(True)
        self.cancel_button.setText('Cancel')
        self.workspace.update_actions()
        self.next_run()

    def refresh_suites(self):
        if self.running:
            return
        settings=self.workspace.comms.settings.section('smoke_tests')
        self.suite_label.setText('Suite folder: '+(settings.get('suite_dir') or '(not configured)'))
        selected=self.suite_combo.currentData()
        self.suite_combo.clear()
        try:
            suites,skipped=discover_smoke_suites(settings)
            for name,path in suites:
                self.suite_combo.addItem(name,str(path))
            index=self.suite_combo.findData(selected)
            if index>=0:
                self.suite_combo.setCurrentIndex(index)
            message='' if suites else 'No named smoke suites found. Each suite needs a name and a non-empty tests list.'
            if skipped:
                message+=(' ' if message else '')+f'Skipped {skipped} JSON file(s) without a valid named suite.'
        except ValueError as error:
            message=str(error)
        self.suite_status.setText(message)
        self.run_button.setEnabled(self.suite_combo.count()>0)
        self.refresh_standard_target()

    def refresh_standard_target(self):
        source=self.suite_combo.currentData()
        label='(select a suite)'
        if source:
            try:
                suite=json.loads(Path(source).read_text(encoding='utf-8-sig'))
                label,_=suite_standard_target(suite)
            except (OSError,ValueError,AttributeError) as error:
                label=str(error)
        self.standard.setText('Standard test — '+label)

    def refresh_configuration(self):
        if self.running:
            return
        settings=self.workspace.comms.settings.section('smoke_tests')
        self.refresh_suites()
        self.comparison.setText('Compare '+str(settings.get('comparison_source_session') or settings.get('comparison_source_tenancy'))+
                                ' → '+str(settings.get('comparison_target_session') or settings.get('comparison_target_tenancy')))
        self.standard.setChecked(settings.get('run_standard',True))
        self.comparison.setChecked(settings.get('run_comparison',True))

    def next_run(self):
        if self.stopping or not self.queue:
            self.finish()
            return
        run=self.queue.pop(0)
        self.status.setText('Running '+run['label']+'…')
        self.output.appendPlainText('\n'+run['label'])
        args=['smoke','--suite',str(self.suite_path),*run['args']]
        self.job=self.workspace.comms.submit(args,timeout_ms=self.plan['timeout_ms'])
        self.job.output.connect(self.output.insertPlainText)
        self.job.completed.connect(lambda result:self.completed(run,result))

    def completed(self,run,result):
        text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',result.stdout)
        report=None
        for line in text.splitlines():
            if line.startswith('Report: '):
                candidate=Path(line[8:].strip()).resolve()
                if candidate.name=='smoke-report.html' and candidate.is_relative_to(self.plan['output']) and candidate.is_file():
                    report=candidate
                    self.reports.append(candidate)
        attention=not result.successful or report is None
        if report:
            try:
                data=json.loads(report.with_name('smoke-results.json').read_text(encoding='utf-8-sig'))
                summary=data['summary']
                reviews=sum(1 for row in data.get('results',[]) if
                            (isinstance(row.get('comparison'),dict) and row['comparison'].get('status')!='Pass') or
                            (isinstance(row.get('compare'),dict) and row['compare'].get('status')!='Pass'))
                self.output.appendPlainText(f"{run['label']}: {summary['passed']} previews passed, {summary['failed']} failed; {reviews} comparisons need attention.")
                attention=attention or bool(summary['failed'] or reviews)
            except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:
                attention=True
                self.output.appendPlainText('Could not read smoke results: '+str(error))
        self.failures+=int(attention)
        if not result.successful:
            self.output.appendPlainText(result.message)
        elif report is None:
            self.output.appendPlainText('The CLI finished without a saved smoke report. Check the output above.')
        self.report_button.setEnabled(bool(self.reports))
        # Failed test cases still produce a report; continue the requested comparison.
        # A cancelled/timed-out process or a setup failure stops the remaining runs.
        if result.cancelled or result.timed_out or (not result.successful and report is None):
            self.stopping=True
        self.job=None
        QTimer.singleShot(0,self.next_run)

    def stop(self):
        self.stopping=True
        self.queue=[]
        if self.job and not self.job.done:
            self.job.cancel()
        else:
            self.finish()

    def cancel_or_close(self):
        if self.running:
            self.stop()
        else:
            self.reject()

    def finish(self):
        self.running=False
        if self.temporary:
            self.temporary.cleanup()
            self.temporary=None
        message='Smoke tests stopped.' if self.stopping else 'Smoke tests completed.'
        if self.failures:
            message+=' Some tests failed or need attention; review the output and reports.'
        self.status.setText(message)
        self.workspace.statusBar().showMessage(message,10000)
        for control in (self.standard,self.comparison,self.resume,self.run_button,self.settings_button,self.suite_combo,self.refresh_button):
            control.setEnabled(True)
        self.cancel_button.setText('Close')
        self.workspace.update_actions()

    def open_reports(self):
        for path in self.reports:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class SmokeTestActions:
    def install_smoke_actions(self):
        self.smoke_dialog=None
        self.smoke_action=self.action('Run Smoke Tests…',self.show_smoke_tests)
        self.package_menu.addAction(self.smoke_action)
        self.package_menu.aboutToShow.connect(self.update_smoke_actions)

    def update_smoke_actions(self):
        if hasattr(self,'smoke_action'):
            self.smoke_action.setEnabled(not self.package_busy())

    def show_smoke_tests(self):
        current=self.smoke_dialog
        if current and (current.isVisible() or current.running):
            current.show()
            current.raise_()
            current.activateWindow()
            return
        if self.package_busy():
            return
        self.smoke_dialog=SmokeTestDialog(self)
        self.smoke_dialog.show()

    def open_smoke_settings(self):
        self.open_user_settings()
        dialog=self.user_settings_dialog
        if self.smoke_dialog:
            dialog.accepted.connect(self.smoke_dialog.refresh_configuration)
        for index in range(dialog.tabs.count()):
            if dialog.tabs.tabText(index)=='Smoke Tests':
                dialog.tabs.setCurrentIndex(index)
                break
