"""Preview dates remain in memory for the current ATool session only."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from ATool import AToolApp
except ImportError:  # pragma: no cover - environments without Tkinter
    AToolApp = None


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class OccsPreviewSettingsTests(unittest.TestCase):
    def test_date_is_not_saved_and_old_saved_date_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            settings_path.write_text(
                json.dumps({"occs": {"last_preview_effective_date": "2026-09-25"}}),
                encoding="utf-8",
            )
            with patch.object(AToolApp, "_settings_file", return_value=settings_path):
                app = AToolApp.__new__(AToolApp)
                app.user_settings = app._load_user_settings()
                self.assertNotIn("last_preview_effective_date", app.user_settings["occs"])

                app._occs_preview_effective_date = "2026-09-25"
                self.assertEqual(app._get_last_occs_preview_effective_date(), "2026-09-25")
                app._set_last_occs_preview_options(["PDF"], 360)
                self.assertNotIn("last_preview_effective_date", json.loads(settings_path.read_text())["occs"])

if __name__ == "__main__":
    unittest.main()
