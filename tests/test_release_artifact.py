"""Distribution completeness, entry points, assets and macOS executable modes."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools.build_artifact import PACKAGE_FILES, build_zip, compile_app, read_package_file, release_version


class ReleaseArtifactTests(unittest.TestCase):
    def test_zip_contains_both_apps_launchers_dependencies_and_editor_assets(self):
        root = Path(__file__).resolve().parents[1]
        compile_app(root, 'worktree')
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', ATOOL_RELEASE_TAG='v2.3.0'):
                archive_path = build_zip(root, Path(directory), 'worktree')
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn('release_tag=v2.3.0\n', archive.read('BUILD_INFO.txt').decode())
                paths = set(archive.namelist())
                self.assertTrue(set(PACKAGE_FILES).issubset(paths))
                self.assertIn('atool_qt/content_editor.html', paths)
                self.assertIn('atool_qt/content_chip_editors.js', paths)
                self.assertIn('atool_qt/window.py', paths)
                for extension in ('png', 'ico', 'icns'):
                    self.assertIn(f'atool_qt/assets/atool.{extension}', paths)
                self.assertIn('tools/build_icons.py', paths)
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

    def test_release_version_overrides_source_commit_tag_for_rebuilds(self):
        with patch.dict('os.environ', ATOOL_RELEASE_TAG='v2.3.0'), patch('tools.build_artifact.git_value') as git:
            self.assertEqual(release_version(Path('.')), 'v2.3.0')
            git.assert_not_called()
        with patch.dict('os.environ', ATOOL_RELEASE_TAG=''), patch('tools.build_artifact.git_value', return_value='v2.4.0'):
            self.assertEqual(release_version(Path('.')), 'v2.4.0')
