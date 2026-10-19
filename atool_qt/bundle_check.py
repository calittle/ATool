"""Offline native-build check: real widgets, WebEngine and bundled OCCS CLI."""
import json
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer
from .occs import CommsSettings
from .runtime import bundled_runtime


def run_bundle_check(app, report):
    from .window import WorkspaceWindow
    with tempfile.TemporaryDirectory() as directory:
        window = WorkspaceWindow(QSettings(str(Path(directory) / 'qt.ini'), QSettings.Format.IniFormat))
        window.comms.settings.payload['application']['confirm_on_quit'] = False
        window.show()
        window.content.ensure_rich(0)
        rich = window.content.rich
        timer = QTimer(window)
        timer.setInterval(100)

        def finish(code, message):
            timer.stop()
            report.write_text(json.dumps({'successful': code == 0, 'message': message,
                                          'application_name': app.applicationName()}), encoding='utf-8')
            window.close()
            app.exit(code)

        def check():
            if not rich.ready:
                return
            timer.stop()
            try:
                if app.windowIcon().isNull() or window.windowIcon().isNull():
                    raise RuntimeError('The bundled ATool application icon is missing.')
                if not bundled_runtime():
                    raise RuntimeError('This check must run from a native bundle.')
                settings = CommsSettings(Path(directory) / 'unused.json')
                result = subprocess.run(settings.command(['--help']), cwd=settings.cwd,
                                        capture_output=True, text=True, timeout=30)
                if result.returncode != 0 or 'Usage:' not in result.stdout:
                    raise RuntimeError('Bundled OCCS CLI did not start: ' + result.stderr)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                finish(1, str(error))
                return
            rich.page().runJavaScript('document.body !== null',
                                      lambda ready: finish(0 if ready else 1, 'Qt WebEngine and OCCS CLI checked.'))

        timer.timeout.connect(check)
        timer.start()
        QTimer.singleShot(60000, lambda: finish(1, 'Bundle check timed out.'))
        return app.exec()
