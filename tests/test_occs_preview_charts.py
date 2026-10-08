"""Chart exclusion changes only the input submitted for preview."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

try:
    from ATool import AToolApp, OccsCommandCancelled
except ImportError:  # pragma: no cover - environments without Tkinter
    AToolApp = None


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class OccsPreviewChartsTests(unittest.TestCase):
    def make_app(self):
        app = AToolApp.__new__(AToolApp)
        app._occs_preview_in_progress = False
        app._update_package_menu_states = Mock()
        app._occs_regular_operations_active = Mock(return_value=True)
        app._on_occs_preview_command_success = Mock()
        app._on_occs_preview_command_failure = Mock()
        app.root = Mock()
        app.root.after.side_effect = lambda _delay, callback: callback()
        return app

    def run_preview(self, app, args, **options):
        # Run the worker synchronously so assertions cover the full input lifetime.
        with patch("ATool.threading.Thread") as thread:
            thread.side_effect = lambda *, target, daemon: Mock(start=target)
            app._run_occs_preview_command_async(args, "Previewing...", Mock(), **options)

    def test_nested_charts_removed_without_mutating_payload(self):
        payload = {
            "charts": {"series": [1, 2]},
            "rows": [{"charts": [{"type": "pie"}], "label": "café"}],
            "nested": {"charts": {}, "text": "charts", "Charts": {"keep": True}},
        }
        original = copy.deepcopy(payload)
        filtered = AToolApp._exclude_charts_from_preview_payload(payload)
        self.assertEqual(filtered, {
            "rows": [{"label": "café"}],
            "nested": {"text": "charts", "Charts": {"keep": True}},
        })
        self.assertEqual(payload, original)

    def test_checked_uses_temporary_input_and_cleans_up_on_all_outcomes(self):
        for error in (None, RuntimeError("failed"), OccsCommandCancelled("canceled")):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "mapped.json"
                source_bytes = b'{ "charts": {}, "rows": [{"charts": [], "value": 7}] }\n'
                source.write_bytes(source_bytes)
                args = ["preview", "--input", str(source), "--output", str(Path(directory) / "output")]
                original_args = list(args)
                app = self.make_app()
                submitted_paths = []

                def command(submitted_args, **kwargs):
                    input_path = Path(submitted_args[submitted_args.index("--input") + 1])
                    submitted_paths.append(input_path)
                    self.assertNotEqual(input_path, source)
                    self.assertEqual(json.loads(input_path.read_text()), {"rows": [{"value": 7}]})
                    self.assertEqual(submitted_args[-2:], original_args[-2:])
                    if error is not None:
                        raise error
                    return {"stdout": "done"}

                app._run_occs_command = command
                self.run_preview(app, args, exclude_charts=True)
                self.assertEqual(source.read_bytes(), source_bytes)
                self.assertEqual(args, original_args)
                self.assertEqual(len(submitted_paths), 1)
                self.assertFalse(submitted_paths[0].parent.exists())
                if error is None:
                    app._on_occs_preview_command_success.assert_called_once()
                else:
                    self.assertIs(app._on_occs_preview_command_failure.call_args.args[0], error)

    def test_default_submits_original_file(self):
        app = self.make_app()
        args = ["preview", "--input", "/mapped/data.json"]
        app._run_occs_command = Mock(return_value={"stdout": "done"})
        with patch("ATool.tempfile.TemporaryDirectory") as temporary_directory:
            self.run_preview(app, args)
        self.assertEqual(app._run_occs_command.call_args.args[0], args)
        temporary_directory.assert_not_called()

    def test_invalid_json_reports_failure_without_submitting_or_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.json"
            source.write_text("invalid JSON")
            app = self.make_app()
            app._run_occs_command = Mock()
            self.run_preview(app, ["preview", "--input", str(source)], exclude_charts=True)
            app._run_occs_command.assert_not_called()
            app._on_occs_preview_command_failure.assert_called_once()
            self.assertEqual(source.read_text(), "invalid JSON")


if __name__ == "__main__":
    unittest.main()
