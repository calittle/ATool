"""Verify runtime staging isolation and complete Windows distribution archives."""
import tempfile
import unittest
import zipfile
import os
import runpy
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.build_native import stage_cli
from tools.archive_native import archive_bundle


class NativePackagingTests(unittest.TestCase):
    def test_migration_login_bridge_is_collected_for_native_apps(self):
        from PyInstaller.utils.hooks import collect_data_files
        data=collect_data_files('atool_qt')
        self.assertTrue(any(Path(source).name=='migration_login.mjs' and destination=='atool_qt'
                            for source,destination in data))

    def test_docx_footer_template_is_accessible_through_frozen_parts_directory(self):
        # Exercise the actual spec and PyInstaller data collector without
        # installing python-docx (or downloading wheels). Its file layout is the
        # contract that matters: parts/../templates must be traversable on disk.
        from PyInstaller.utils import hooks
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for package in ('docx','atool_qt'):
                (root/package).mkdir()
                (root/package/'__init__.py').write_text('')
            (root/'docx'/'parts').mkdir()
            (root/'docx'/'parts'/'__init__.py').write_text('')
            (root/'docx'/'parts'/'hdrftr.py').write_text('# frozen module path')
            templates=root/'docx'/'templates'
            templates.mkdir()
            for name in ('default-footer.xml','default-header.xml','default.docx'):
                (templates/name).write_bytes(name.encode())
            captured={}
            def analysis(*args,**options):
                captured.update(options)
                return SimpleNamespace(pure=[],scripts=[],binaries=[],datas=options['datas'])
            project=Path(__file__).resolve().parents[1]
            with patch.dict(os.environ,ATOOL_NATIVE_STAGE=str(root/'stage'),ATOOL_NATIVE_NODE=str(root/'node'),ATOOL_CODESIGN_IDENTITY=''), \
                    patch.object(hooks,'is_package',return_value=True), \
                    patch.object(hooks,'get_all_package_paths',side_effect=lambda package:[str(root/package)]):
                runpy.run_path(str(project/'packaging'/'ATool.spec'),init_globals=dict(
                    SPECPATH=str(project/'packaging'),Analysis=analysis,
                    PYZ=lambda *a,**k:None,EXE=lambda *a,**k:None,
                    COLLECT=lambda *a,**k:None,BUNDLE=lambda *a,**k:None))
            extracted=root/'extracted'
            for source,destination in captured['datas']:
                source=Path(source)
                if source.is_file() and source.is_relative_to(root/'docx'):
                    target=extracted/destination/source.name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,target)
            # Source collection creates docx/parts, which is otherwise absent
            # because code in PYZ alone does not create filesystem directories.
            mode=captured.get('module_collection_mode',{}).get('docx','pyz')
            if 'py' in mode.split('+'):
                for source in (root/'docx').rglob('*.py'):
                    target=extracted/source.relative_to(root)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,target)
            for name in ('default-footer.xml','default-header.xml','default.docx'):
                self.assertEqual((extracted/'docx'/'parts'/'..'/'templates'/name).read_bytes(),name.encode())

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
