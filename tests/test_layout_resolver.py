"""Portable integration checks for the cached layout resolver."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from atool_core.layout_resolver import LayoutResolver, format_report


class LayoutResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name)

        def save(relative: str, value: object) -> None:
            path = self.cache / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding="utf-8")

        active = {"Items": [{"StatusCode": "Active", "EffDtTm": "2026-01-01T00:00:00Z"}]}
        save("packages/Pkg/versions/v1/AssemblyTemplate.json", {
            "Documents": [{"$$Id": "Doc", "Condition": "$[?(@.show == true)]"}],
            "Fields": [
                {"Name": "Name", "Path": "$.name"},
                {"Name": "Address", "Path": "$.address"},
            ],
        })
        save("documents/Doc/Doc_master.json", {
            "CommunicationDocumentMasterVersions": [{"CommunicationDocumentVersionConfigRec": {
                "CommunicationDocumentVersionConfigInfo": {"ShortName": "1.0"}, "Status": active,
            }}],
        })
        save("documents/Doc/versions/1.0.json", {
            "CommunicationDocumentVersionLayouts": [{
                "CommunicationLayoutConfigRec": {
                    "CommunicationLayoutConfigUuid": "layout-1",
                    "CommunicationLayoutConfigInfo": {"ShortName": "header"},
                },
                "CommunicationDocumentVersionConfigCommunicationLayoutConfigRelRec": {
                    "CommunicationDocumentVersionConfigCommunicationLayoutConfigRelInfo": {
                        "LayoutRelIndex": 1, "LayoutPlacement": "Header",
                    },
                },
            }],
        })
        save("layouts/header/header.json", {
            "CommunicationLayoutConfigRec": {
                "CommunicationLayoutConfigUuid": "layout-1",
                "CommunicationLayoutConfigInfo": {"ShortName": "header", "LayoutType": "Block"},
            },
            "CommunicationLayoutLayouts": [],
            "CommunicationLayoutContents": [{
                "ShortName": "header-content",
                "CommunicationLayoutConfigCommunicationContentConfigRelRec": {
                    "CommunicationLayoutConfigCommunicationContentConfigRelInfo": {
                        "ContentRelIndex": 1, "ContentAlwaysTriggerInd": True,
                    },
                },
            }],
        })
        for name in ("header-content", "address-content"):
            save(f"contents/{name}/{name}_master.json", {
                "CommunicationContentMasterVersions": [{"CommunicationContentVersionConfigRec": {
                    "CommunicationContentVersionConfigInfo": {
                        "ShortName": "1.0",
                        "CommunicationContentVersionConfigData": {"Items": [{"ContentData": {"FileId": name}}]},
                    },
                    "Status": active,
                }}],
            })
        header_blob = (
            '<p><comms-cond>$Cond{"Condition":"Name != null","Text":"'
            '<comms-data>$Data{"Id":"Name"}<comms-transform type="substring" start="1" length="3"></comms-transform></comms-data>'
            '"}</comms-cond></p>'
            '<p><comms-cond>$Cond{"Condition":"Address empty false","Content":"address-content"}</comms-cond></p>'
            '<p><comms-cond>$Cond{"Condition":"PackagePageNum == 1","Text":"page one"}</comms-cond></p>'
        )
        address_blob = '<p><comms-data>$Data{"Id":"Address"}</comms-data></p>'
        for name, blob in (("header-content", header_blob), ("address-content", address_blob)):
            path = self.cache / f"contents/{name}/versions/1.0/{name}.blob"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(blob, encoding="utf-8")

    def test_nested_content_substring_and_default_page(self) -> None:
        result = LayoutResolver(self.cache, "Pkg", "Doc", {"show": True, "name": "ABCDE", "address": "Main St"}, effective_date="2026-09-25").resolve("header")
        report = format_report(result)
        self.assertIn("ABC\n", report)
        self.assertIn("Main St", report)
        self.assertIn("page one", report)
        self.assertEqual([], result["warnings"])

    def test_page_override_and_suppressed_content(self) -> None:
        result = LayoutResolver(self.cache, "Pkg", "Doc", {"show": True, "name": "ABCDE"}, effective_date="2026-09-25", system_fields={"PackagePageNum": 2}).resolve("header")
        content = result["layout"]["children"][0]
        self.assertEqual("ABC", content["rendered"])
        self.assertFalse(content["children"][1]["passed"])
        self.assertFalse(content["children"][2]["passed"])

    def test_document_gate_suppresses_layout(self) -> None:
        result = LayoutResolver(self.cache, "Pkg", "Doc", {"show": False}, effective_date="2026-09-25").resolve("header")
        self.assertFalse(result["document_triggered"])
        self.assertFalse(result["layout"]["passed"])

    def test_open_package_template_and_cached_layout_choices(self) -> None:
        template = {
            "Documents": [{"$$Id": "Doc", "Condition": "$[?(@.show == true)]"}],
            "Fields": [{"Name": "Name", "Path": "$.name"}, {"Name": "Address", "Path": "$.address"}],
        }
        resolver = LayoutResolver(
            self.cache, "Pkg", "Doc", {"show": True, "name": "ABCDE"},
            effective_date="2026-09-25", assembly_template=template,
        )
        self.assertEqual(("1.0", ["header"]), resolver.available_layouts())
        self.assertEqual("ABC\npage one", resolver.resolve("header")["layout"]["children"][0]["rendered"])


if __name__ == "__main__":
    unittest.main()
