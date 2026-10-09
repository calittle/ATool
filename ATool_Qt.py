"""Launch the isolated Qt workspace: python ATool_Qt.py [--package PATH]."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="ATool")
    parser.add_argument("--package", type=Path, help="Assembly Template JSON, manifest, or package folder")
    parser.add_argument("--data", type=Path, help="JSON data file to map after opening")
    args = parser.parse_args()
    if args.data and not args.package:
        parser.error("--data requires --package.")
    try:
        from PySide6.QtCore import QLoggingCategory
        from PySide6.QtWidgets import QApplication
        from atool_qt.window import WorkspaceWindow
    except ModuleNotFoundError as error:
        if error.name == "PySide6":
            print("Install the application dependencies: python -m pip install -r requirements-qt.txt", file=sys.stderr)
            return 1
        raise
    # Qt emits this warning while rebuilding empty trees on macOS.
    QLoggingCategory.setFilterRules('qt.accessibility.table.warning=false')
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ATool")
    app.setOrganizationName("ATool")
    window = WorkspaceWindow()
    window.show()
    if args.package:
        if not window.open_package(args.package):
            args.data = None
    if args.data:
        window.map_file(args.data)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
