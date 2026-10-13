"""Single-item exports must never clear sibling resources in the cache."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from atool_core.resource_cache import ResourceDownload, SINGLE_RESOURCE_COMMANDS
from atool_qt.occs import CommsService, CommsSettings


class ResourceCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / 'contents'
        self.cache.mkdir()
        for name in ('selector ec detail4', 'EC detail PRO'):
            folder = self.cache / name
            folder.mkdir()
            (folder / 'old.blob').write_text('previous ' + name)
        self.cli = self.root / 'cli'
        self.cli.write_text(f'#!{sys.executable}\n' + '''
import json, shutil, sys, time
from pathlib import Path
args = sys.argv[1:]
output = Path(args[args.index('--output') + 1])
# Reproduce OCCS CLI setDir: clear the whole output before fetching the item.
shutil.rmtree(output, ignore_errors=True)
output.mkdir(parents=True)
if args[1] == 'empty':
    print('Downloaded nothing')
    sys.exit(0)
folder = output / args[1]
folder.mkdir()
(folder / 'latest.blob').write_text('latest ' + args[1])
if args[1] == 'slow':
    time.sleep(10)
if args[1] == 'fail':
    sys.exit(1)
if args[1] == 'partial':
    print('Artifact download failures (1):', file=sys.stderr)
print(json.dumps({'ok': True}))
''')
        self.cli.chmod(0o755)
        settings = CommsSettings(self.root / 'settings.json')
        settings.payload = {'occs': {'cli_path': str(self.cli)}}
        self.service = CommsService(settings)
        self.addCleanup(self.service.shutdown)

    def wait(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(condition())

    def test_alternating_downloads_preserve_both_resources_for_every_single_command(self):
        for command in SINGLE_RESOURCE_COMMANDS:
            for name in ('EC detail PRO', 'selector ec detail4', 'EC detail PRO'):
                results = []
                self.service.submit([command, name, '--output', str(self.cache)], results.append, channel='resources')
                self.wait(lambda: bool(results))
                self.assertTrue(results[0].successful, results[0].message)
                self.assertEqual('latest ' + name, (self.cache / name / 'latest.blob').read_text())
                self.assertFalse((self.cache / name / 'old.blob').exists())
                self.assertEqual({'EC detail PRO', 'selector ec detail4'}, {path.name for path in self.cache.iterdir()})
                self.assertEqual([], list(self.root.glob('.atool-resource-*')))

    def test_failed_empty_and_cancelled_downloads_preserve_cache_and_cleanup(self):
        for name in ('fail', 'empty', 'partial', 'slow'):
            results = []
            job = self.service.submit(['get-content', name, '--output', str(self.cache)], results.append)
            if name == 'slow':
                self.wait(lambda: bool(list(self.root.glob('.atool-resource-*/download/slow/latest.blob'))))
                job.cancel()
            self.wait(lambda: bool(results))
            self.assertFalse(results[0].successful)
            self.assertEqual({'EC detail PRO', 'selector ec detail4'}, {path.name for path in self.cache.iterdir()})
            self.assertEqual('previous EC detail PRO', (self.cache / 'EC detail PRO/old.blob').read_text())
            self.assertEqual([], list(self.root.glob('.atool-resource-*')))

    def test_concurrent_downloads_and_timeout_preserve_siblings(self):
        results = []
        for name in ('EC detail PRO', 'selector ec detail4'):
            self.service.submit(['get-content', name, '--output', str(self.cache)], results.append, channel='resources')
        self.wait(lambda: len(results) == 2)
        self.assertTrue(all(result.successful for result in results))
        for name in ('EC detail PRO', 'selector ec detail4'):
            self.assertTrue((self.cache / name / 'latest.blob').exists())
        self.service.submit(['get-content', 'slow', '--output', str(self.cache)], results.append, timeout_ms=100)
        self.wait(lambda: len(results) == 3)
        self.assertTrue(results[-1].timed_out)
        self.assertEqual({'EC detail PRO', 'selector ec detail4'}, {path.name for path in self.cache.iterdir()})
        self.assertEqual([], list(self.root.glob('.atool-resource-*')))

    def test_replacement_failure_rolls_back_original_resource(self):
        with ResourceDownload(['get-content', 'EC detail PRO', '--output', str(self.cache)]) as download:
            resource = download.output / 'EC detail PRO'
            resource.mkdir(parents=True)
            (resource / 'new.blob').write_text('latest')
            rename = Path.rename
            def fail_install(path, target):
                if path == resource:
                    raise OSError('Simulated install failure')
                return rename(path, target)
            with patch.object(Path, 'rename', fail_install), self.assertRaisesRegex(OSError, 'install failure'):
                download.commit()
            self.assertEqual('previous EC detail PRO', (self.cache / 'EC detail PRO/old.blob').read_text())

    def test_legacy_resource_download_preserves_siblings(self):
        try:
            from ATool import AToolApp
        except ImportError:
            self.skipTest('Tkinter is not installed')
        app = AToolApp.__new__(AToolApp)
        app._run_occs_cli = lambda args, **_: subprocess.run([str(self.cli), *args], capture_output=True, text=True)
        app._run_occs_resource_command(['get-content', 'EC detail PRO', '--output', str(self.cache)])
        self.assertTrue((self.cache / 'selector ec detail4/old.blob').exists())
        self.assertTrue((self.cache / 'EC detail PRO/latest.blob').exists())


if __name__ == '__main__':
    unittest.main()
