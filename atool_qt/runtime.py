"""Locate runtime files inside native application distributions."""
from pathlib import Path
import sys


def bundled_runtime():
    if not getattr(sys, 'frozen', False):
        return None
    return Path(sys._MEIPASS) / 'runtime'


def start_new_instance():
    """Launch a blank workspace that can outlive the current application."""
    from PySide6.QtCore import QProcess, QProcessEnvironment

    process = QProcess()
    process.setProgram(sys.executable)
    if getattr(sys, 'frozen', False):
        # PyInstaller otherwise treats this as a worker sharing our runtime.
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYINSTALLER_RESET_ENVIRONMENT', '1')
        process.setProcessEnvironment(environment)
    else:
        process.setArguments([str(Path(__file__).resolve().parents[1] / 'ATool_Qt.py')])
    return process.startDetached()
