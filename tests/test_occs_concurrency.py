import unittest

try:
    from ATool import AToolApp
except ImportError:  # pragma: no cover - environments without Tkinter
    AToolApp = None


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class OccsConcurrencyTests(unittest.TestCase):
    def _app(self):
        app = AToolApp.__new__(AToolApp)
        app.current_occs_bundle_dir = "/tmp/package"
        app.current_occs_manifest = {"package": {"shortName": "sample"}}
        app.current_data_payload = {"sample": True}
        app._occs_operation_in_progress = False
        app._occs_preview_in_progress = False
        return app

    def test_preview_is_available_while_regular_command_runs(self):
        app = self._app()
        app._occs_operation_in_progress = True

        self.assertTrue(app._can_preview_occs_package())

        app._occs_preview_in_progress = True
        self.assertFalse(app._can_preview_occs_package())

    def test_preview_completion_preserves_regular_command_state(self):
        app = self._app()
        app._occs_operation_in_progress = True
        app._occs_preview_in_progress = True
        app._occs_preview_cancel_requested = True
        app._update_package_menu_states = lambda: None
        app._stop_occs_status_timer = lambda: self.fail("preview must not stop another command's status")
        app._restore_default_status_text = lambda: self.fail("preview must not reset another command's status")
        completed = []

        app._on_occs_preview_command_success({"stdout": "done"}, completed.append)

        self.assertFalse(app._occs_preview_in_progress)
        self.assertFalse(app._occs_preview_cancel_requested)
        self.assertTrue(app._occs_operation_in_progress)
        self.assertEqual(completed, [{"stdout": "done"}])


if __name__ == "__main__":
    unittest.main()
