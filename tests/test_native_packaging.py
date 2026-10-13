"""Verify runtime staging isolation and complete Windows distribution archives."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.build_native import stage_cli
from tools.archive_native import archive_bundle


class NativePackagingTests(unittest.TestCase):
    def test_cli_staging_retains_runtime_and_licenses_but_excludes_private_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'cli'
            source.mkdir()
            for name in ('bin', 'lib', 'node_modules'):
                (source / name).mkdir()
                (source / name / 'runtime.js').write_text('export default {}')
            for name in ('package.json', 'package-lock.json', 'LICENSE', 'README.md'):
                (source / name).write_text('runtime')
            for name in ('.env', '.occs-session.json', 'customer-data.json'):
                (source / name).write_text('secret')
            (source / 'node_modules' / '.env').write_text('secret')
            (source / 'node_modules' / 'LICENSE').write_text('dependency license')
            destination = root / 'stage'
            stage_cli(source, destination)
            self.assertTrue((destination / 'node_modules/LICENSE').exists())
            self.assertTrue((destination / 'bin/runtime.js').exists())
            self.assertFalse(any(path.name in ('.env', '.occs-session.json', 'customer-data.json') for path in destination.rglob('*')))

    def test_missing_cli_dependencies_fail_instead_of_building_incomplete_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bin').mkdir()
            with self.assertRaisesRegex(ValueError, 'missing lib'):
                stage_cli(root, root / 'stage')
            self.assertFalse((root / 'stage').exists())

    def test_windows_archive_keeps_executable_and_runtime_together_and_checksums_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'native' / 'ATool'
            (bundle / '_internal/runtime/node').mkdir(parents=True)
            (bundle / 'ATool.exe').write_bytes(b'executable')
            (bundle / '_internal/runtime/node/node.exe').write_bytes(b'node')
            archive = archive_bundle(bundle, root / 'downloads', 'ATool-windows-x86_64')
            with zipfile.ZipFile(archive) as zipped:
                self.assertIn('ATool/ATool.exe', zipped.namelist())
                self.assertIn('ATool/_internal/runtime/node/node.exe', zipped.namelist())
            self.assertIn(archive.name, archive.with_suffix('.zip.sha256').read_text())
