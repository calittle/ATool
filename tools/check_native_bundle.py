#!/usr/bin/env python3
"""Run the actual packaged executable with no Python or Node on PATH."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def check_bundle(bundle):
    if bundle.suffix == '.zip':
        with tempfile.TemporaryDirectory(prefix='atool-extracted-') as directory:
            if sys.platform == 'darwin':
                subprocess.run(['ditto', '-xk', str(bundle.resolve()), directory], check=True)
            else:
                with zipfile.ZipFile(bundle) as archive:
                    archive.extractall(directory)
            check_bundle(Path(directory) / ('ATool.app' if sys.platform == 'darwin' else 'ATool'))
        return
    executable = bundle / ('Contents/MacOS/ATool' if bundle.suffix == '.app' else 'ATool.exe')
    with tempfile.TemporaryDirectory(prefix='atool-native-check-') as directory:
        root = Path(directory)
        report = root / 'report.json'
        environment = dict(os.environ)
        # Isolate settings and prove that installed developer tools aren't needed.
        for variable in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
            environment.pop(variable, None)
        environment.update(HOME=directory, USERPROFILE=directory,
                           APPDATA=str(root / 'AppData'), LOCALAPPDATA=str(root / 'LocalAppData'),
                           PATH=os.path.join(environment.get('SystemRoot', 'C:\\Windows'), 'System32') if os.name == 'nt' else '/usr/bin:/bin')
        result = subprocess.run([str(executable.resolve()), '--bundle-check', str(report)],
                                cwd=directory, env=environment, timeout=90)
        if result.returncode or not report.exists():
            details = report.read_text(encoding='utf-8') if report.exists() else 'No startup report was written.'
            raise RuntimeError(f'Native executable failed its startup check (exit {result.returncode}): {details}')
        value = json.loads(report.read_text(encoding='utf-8'))
        if not value.get('successful') or value.get('application_name') != 'ATool':
            raise RuntimeError(f'Native bundle check failed: {value}')
        print(value['message'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    check_bundle(parser.parse_args().bundle)
