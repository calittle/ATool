"""Distribution completeness, entry points, assets and macOS executable modes."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.build_artifact import PACKAGE_FILES, build_zip, compile_app, read_package_file


class ReleaseArtifactTests(unittest.TestCase):
    def test_zip_contains_both_apps_launchers_dependencies_and_editor_assets(self):
        root = Path(__file__).resolve().parents[1]
        compile_app(root, 'worktree')
        with tempfile.TemporaryDirectory() as directory:
            archive_path = build_zip(root, Path(directory), 'worktree')
            with zipfile.ZipFile(archive_path) as archive:
                paths = set(archive.namelist())
                self.assertTrue(set(PACKAGE_FILES).issubset(paths))
                self.assertIn('atool_qt/content_editor.html', paths)
                self.assertIn('atool_qt/content_chip_editors.js', paths)
                self.assertIn('atool_qt/window.py', paths)
                self.assertFalse(any('__pycache__' in path or path.endswith('.pyc') for path in paths))
                self.assertIn('ATool_Qt.py', archive.read('Run_ATool.command').decode())
                self.assertIn('ATool_Qt.py', archive.read('Run_ATool.bat').decode())
                self.assertIn('ATool.py', archive.read('Run_ATool_Legacy.zsh').decode())
                self.assertIn('ATool.py', archive.read('Run_ATool_Legacy.bat').decode())
                self.assertIn('PySide6==6.12.0', archive.read('requirements.txt').decode())
                self.assertIn('## v2.0.0', archive.read('NOTES.MD').decode())
                for name in paths:
                    if name.endswith(('.command','.zsh')):
                        self.assertTrue((archive.getinfo(name).external_attr >> 16) & 0o111, name)

    def test_head_packaging_rejects_uncommitted_runtime_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'untracked.py').write_text('print("untracked")')
            with self.assertRaisesRegex(RuntimeError,'not committed'):
                read_package_file(root,'untracked.py','head')
