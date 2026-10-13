"""Locate runtime files inside native application distributions."""
from pathlib import Path
import sys


def bundled_runtime():
    if not getattr(sys, 'frozen', False):
        return None
    return Path(sys._MEIPASS) / 'runtime'
