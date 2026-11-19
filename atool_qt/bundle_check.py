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
                from tools.td_generator import td_generator
                from tools.td_generator.render_td import export_formats
                from .technical_design import TechnicalDesignDialog
                dialog = TechnicalDesignDialog(window)
                dialog.close()
                root = Path(directory)
                markdown = root / 'design.md'
                markdown.write_text('# Technical Design\n\nNative export check.\n', encoding='utf-8')
                export_formats(markdown, root / 'design.docx')
                (root / 'contents').mkdir()
                script = Path(td_generator.__file__).with_name('build_content_catalog.mjs')
                result = subprocess.run([td_generator.node_executable(), str(script), str(root / 'contents'),
                                         str(root / 'index'), '2026-01-01', str(td_generator.default_occs_cli())],
                                        capture_output=True, text=True, timeout=30)
                if result.returncode or not (root / 'index' / 'content-usage.json').is_file():
                    raise RuntimeError('Bundled TD cache parser failed: ' + result.stderr)
            except (ImportError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                finish(1, str(error))
                return
            rich.page().runJavaScript('document.body !== null',
                                      lambda ready: finish(0 if ready else 1, 'Qt WebEngine, OCCS CLI and Technical Design export checked.'))

        timer.timeout.connect(check)
        timer.start()
        QTimer.singleShot(60000, lambda: finish(1, 'Bundle check timed out.'))
        return app.exec()
