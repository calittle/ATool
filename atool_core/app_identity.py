"""Shared application artwork and Windows taskbar identity."""
from pathlib import Path
import sys


APP_ID = 'com.calittle.ATool'


def icon_path(extension='png'):
    return Path(__file__).resolve().parents[1] / 'atool_qt' / 'assets' / f'atool.{extension}'


def set_windows_app_id():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
