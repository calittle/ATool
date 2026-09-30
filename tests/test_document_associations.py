"""Package-association state used by the Documents panel."""

from __future__ import annotations

import unittest

try:
    from ATool import AToolApp
except ImportError:  # pragma: no cover - environments without Tkinter
    AToolApp = None


@unittest.skipIf(AToolApp is None, "Tkinter is not installed")
class DocumentAssociationStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = AToolApp.__new__(AToolApp)

    def test_association_matches_document_short_name_case_insensitively(self) -> None:
        self.app.current_document_associations = {
            "associations": [{"documentShortName": "BillSummary"}],
        }

        self.assertTrue(self.app._document_is_package_associated({"name": "billsummary"}))
        self.assertFalse(self.app._document_is_package_associated({"name": "BillDetail"}))

    def test_missing_association_metadata_is_not_treated_as_unassociated(self) -> None:
        self.app.current_document_associations = None

        self.assertIsNone(self.app._document_is_package_associated({"name": "BillSummary"}))

    def test_unassociated_state_overrides_mapping_colours(self) -> None:
        self.app.current_document_associations = {"associations": []}
        self.app.current_data_payload = {"bill": True}

        self.assertEqual(("unassociated_doc",), self.app._document_mapping_tags({"name": "BillSummary", "triggered": True}))


if __name__ == "__main__":
    unittest.main()
