"""Opening the last session restores shared edit context only for its owned lock."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

try:
    from ATool import AToolApp
except ImportError:  # pragma: no cover - environments without Tkinter
    AToolApp = None


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class OpenSharedSessionTests(unittest.TestCase):
    def _app(self, bundle_dir: Path, published_dir: Path):
        app = AToolApp.__new__(AToolApp)
        app._read_shared_baseline_for_local_copy = Mock(return_value={"publishedDir": str(published_dir)})
        app._shared_package_entry_from_package_dir = Mock(return_value={
            "package_dir": published_dir.parent.parent,
            "published_dir": published_dir,
        })
        app._is_shared_edit_resume_dir = Mock(return_value=True)
        app._current_shared_user_identity = Mock(return_value={"user": "me", "host": "machine"})
        app._read_shared_lock = Mock(return_value={
            "owner": {"user": "me", "host": "machine"},
            "bundleDir": str(bundle_dir),
        })
        return app

    def test_owned_lock_restores_edit_mode(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_dir = root / "local"
            published_dir = root / "shared" / "published" / "current"
            app = self._app(bundle_dir, published_dir)

            self.assertEqual(app._last_session_shared_context(bundle_dir), (root / "shared", "edit"))

    def test_missing_or_other_copy_lock_opens_for_testing(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_dir = root / "local"
            published_dir = root / "shared" / "published" / "current"
            app = self._app(bundle_dir, published_dir)

            app._read_shared_lock.return_value = None
            self.assertEqual(app._last_session_shared_context(bundle_dir), (root / "shared", "testing"))

            app._read_shared_lock.return_value = {
                "owner": {"user": "me", "host": "machine"},
                "bundleDir": str(root / "other-copy"),
            }
            self.assertEqual(app._last_session_shared_context(bundle_dir), (root / "shared", "testing"))

    def test_unmatched_shared_baseline_stays_local(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_dir = root / "local"
            published_dir = root / "shared" / "published" / "current"
            app = self._app(bundle_dir, published_dir)
            app._is_shared_edit_resume_dir.return_value = False

            self.assertEqual(app._last_session_shared_context(bundle_dir), (None, "local"))

    def test_open_session_passes_restored_context_to_loader(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_dir = root / "local"
            bundle_dir.mkdir()
            published_dir = root / "shared" / "published" / "current"
            app = self._app(bundle_dir, published_dir)
            app._occs_regular_operation_limit_reached = Mock(return_value=False)
            app._mapping_in_progress = False
            app._mapping_dialog_in_progress = False
            app._prompt_save_if_dirty = Mock(return_value=True)
            app._read_app_state = Mock(return_value={"last_occs_bundle": str(bundle_dir)})
            app._load_occs_bundle = Mock(return_value=True)
            app._show_temporary_status = Mock()

            app.open_last_session()

            app._load_occs_bundle.assert_called_once_with(
                str(bundle_dir), shared_package_dir=root / "shared", shared_mode="edit"
            )


if __name__ == "__main__":
    unittest.main()
