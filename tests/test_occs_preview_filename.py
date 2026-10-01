"""Preview output names include the selected OCCS environment."""

from pathlib import Path
import unittest

try:
    from ATool import AToolApp
except ImportError:  # pragma: no cover - environments without Tkinter
    AToolApp = None


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class OccsPreviewFilenameTests(unittest.TestCase):
    def test_output_base_uses_environment_and_readable_timestamp(self) -> None:
        app = AToolApp.__new__(AToolApp)
        data_file = Path("/tmp/sample.data.json")

        for environment in ("non", "pre", "prod"):
            with self.subTest(environment=environment):
                output_base = app._build_occs_preview_output_base(data_file, "Package", environment)
                self.assertEqual(output_base.parent, data_file.parent)
                self.assertRegex(
                    output_base.name,
                    rf"^sample\.data-Package-{environment}-\d{{4}}-\d{{2}}-\d{{2}}_\d{{2}}-\d{{2}}-\d{{2}}$",
                )

    def test_unknown_environment_is_rejected(self) -> None:
        app = AToolApp.__new__(AToolApp)
        with self.assertRaises(ValueError):
            app._build_occs_preview_output_base(Path("/tmp/data.json"), "Package", "unknown")


if __name__ == "__main__":
    unittest.main()
