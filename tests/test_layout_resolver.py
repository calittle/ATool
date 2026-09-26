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
            "Documents": [
                {"$$Id": "Doc", "Condition": "$[?(@.show == true)]"},
                {"$$Id": "Trigger Catalog", "Layouts": [{
                    "$$Id": "header",
                    "Contents": [{
                        "$$Id": "conditional-content",
                        "Condition": "$[?(@.includeExtra == true)]",
                    }],
                }]},
            ],
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
            }, {
                "ShortName": "conditional-content",
                "CommunicationLayoutConfigCommunicationContentConfigRelRec": {
                    "CommunicationLayoutConfigCommunicationContentConfigRelInfo": {
                        "ContentRelIndex": 2, "ContentAlwaysTriggerInd": False,
                    },
                },
            }],
        })
        for name in ("header-content", "address-content", "conditional-content"):
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
            '<p><comms-cond>$Cond{"Condition":"GRIDPAGENUMBER == 1","Text":"grid page one"}</comms-cond></p>'
            '<p><comms-cond>$Cond{"Condition":"Name not empty","Text":"name present"}</comms-cond></p>'
        )
        address_blob = '<p><comms-data>$Data{"Id":"Address"}</comms-data></p>'
        for name, blob in (
            ("header-content", header_blob),
            ("address-content", address_blob),
            ("conditional-content", "<p>extra relationship content</p>"),
        ):
            path = self.cache / f"contents/{name}/versions/1.0/{name}.blob"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(blob, encoding="utf-8")

    def test_nested_content_substring_and_default_page(self) -> None:
        result = LayoutResolver(self.cache, "Pkg", "Doc", {"show": True, "name": "ABCDE", "address": "Main St"}, effective_date="2026-09-25").resolve("header")
        report = format_report(result)
        self.assertIn("ABC\n", report)
        self.assertIn("Main St", report)
        self.assertIn("page one", report)
        self.assertIn("grid page one", report)
        self.assertIn("name present", report)
        self.assertEqual([], result["warnings"])

    def test_page_override_and_suppressed_content(self) -> None:
        result = LayoutResolver(
            self.cache,
            "Pkg",
            "Doc",
            {"show": True, "name": "ABCDE"},
            effective_date="2026-09-25",
            system_fields={"PackagePageNum": 2, "GRIDPAGENUMBER": 2},
        ).resolve("header")
        content = result["layout"]["children"][0]
        self.assertEqual("ABC\nname present", content["rendered"])
        self.assertFalse(content["children"][1]["passed"])
        self.assertFalse(content["children"][2]["passed"])
        self.assertFalse(content["children"][3]["passed"])

    def test_document_gate_suppresses_layout(self) -> None:
        result = LayoutResolver(self.cache, "Pkg", "Doc", {"show": False}, effective_date="2026-09-25").resolve("header")
        self.assertFalse(result["document_triggered"])
        self.assertFalse(result["layout"]["passed"])

    def test_package_wide_relationship_condition_selects_content(self) -> None:
        result = LayoutResolver(
            self.cache,
            "Pkg",
            "Doc",
            {"show": True, "name": "ABCDE", "includeExtra": True},
            effective_date="2026-09-25",
        ).resolve("header")
        content = result["layout"]["children"][1]
        self.assertTrue(content["passed"])
        self.assertEqual("conditional-content", content["name"])
        self.assertEqual("extra relationship content", content["rendered"])
        self.assertTrue(content["children"][0]["passed"])
        self.assertEqual(["Trigger Catalog"], content["children"][0]["sources"])

    def test_package_wide_relationship_condition_suppresses_content(self) -> None:
        result = LayoutResolver(
            self.cache,
            "Pkg",
            "Doc",
            {"show": True, "name": "ABCDE", "includeExtra": False},
            effective_date="2026-09-25",
        ).resolve("header")
        content = result["layout"]["children"][1]
        self.assertFalse(content["passed"])
        self.assertFalse(content["children"][0]["passed"])
        self.assertNotIn("extra relationship content", format_report(result))

    def test_selected_document_condition_precedes_package_wide_conflict(self) -> None:
        template_path = self.cache / "packages/Pkg/versions/v1/AssemblyTemplate.json"
        template = json.loads(template_path.read_text(encoding="utf-8"))
        template["Documents"][0]["Layouts"] = [{
            "$$Id": "header",
            "Contents": [{
                "$$Id": "conditional-content",
                "Condition": "$[?(@.selectedRule == true)]",
            }],
        }]
        template_path.write_text(json.dumps(template), encoding="utf-8")

        result = LayoutResolver(
            self.cache,
            "Pkg",
            "Doc",
            {"show": True, "name": "ABCDE", "includeExtra": False, "selectedRule": True},
            effective_date="2026-09-25",
        ).resolve("header")
        content = result["layout"]["children"][1]
        self.assertTrue(content["passed"])
        self.assertEqual(["Doc"], content["children"][0]["sources"])

    def test_missing_relationship_condition_stays_unknown(self) -> None:
        layout_path = self.cache / "layouts/header/header.json"
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
        layout["CommunicationLayoutContents"].append({
            "ShortName": "cache-only-content",
            "CommunicationLayoutConfigCommunicationContentConfigRelRec": {
                "CommunicationLayoutConfigCommunicationContentConfigRelInfo": {
                    "ContentRelIndex": 3,
                    "ContentAlwaysTriggerInd": False,
                },
            },
        })
        layout_path.write_text(json.dumps(layout), encoding="utf-8")

        result = LayoutResolver(
            self.cache,
            "Pkg",
            "Doc",
            {"show": True, "name": "ABCDE"},
            effective_date="2026-09-25",
        ).resolve("header")
        content = result["layout"]["children"][2]
        self.assertIsNone(content["passed"])
        self.assertIn("No Assembly Template content condition found", content["warning"])

    def test_triggered_image_reports_asset_without_decoding_blob(self) -> None:
        template_path = self.cache / "packages/Pkg/versions/v1/AssemblyTemplate.json"
        template = json.loads(template_path.read_text(encoding="utf-8"))
        template["Documents"][1]["Layouts"][0]["Contents"].append({
            "$$Id": "conditional-image",
            "Condition": "$[?(@.includeImage == true)]",
        })
        template_path.write_text(json.dumps(template), encoding="utf-8")

        layout_path = self.cache / "layouts/header/header.json"
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
        layout["CommunicationLayoutContents"].append({
            "ShortName": "conditional-image",
            "CommunicationLayoutConfigCommunicationContentConfigRelRec": {
                "CommunicationLayoutConfigCommunicationContentConfigRelInfo": {
                    "ContentRelIndex": 3,
                    "ContentAlwaysTriggerInd": False,
                },
            },
        })
        layout_path.write_text(json.dumps(layout), encoding="utf-8")

        active = {"Items": [{"StatusCode": "Active", "EffDtTm": "2026-01-01T00:00:00Z"}]}
        master_path = self.cache / "contents/conditional-image/conditional-image_master.json"
        master_path.parent.mkdir(parents=True, exist_ok=True)
        master_path.write_text(json.dumps({
            "CommunicationContentConfigRec": {
                "CommunicationContentConfigInfo": {"ContentType": "Image"},
            },
            "CommunicationContentMasterVersions": [{"CommunicationContentVersionConfigRec": {
                "CommunicationContentVersionConfigInfo": {
                    "ShortName": "1.0",
                    "CommunicationContentVersionConfigData": {"Items": [{
                        "ContentData": {"FileId": "image-id", "FileName": "sample.png"},
                        "CommunicationContentVersionConfigImageData": {
                            "ImageFormat": "PNG", "ResolutionDPI": 300,
                        },
                    }]},
                },
                "Status": active,
            }}],
        }), encoding="utf-8")
        blob_path = self.cache / "contents/conditional-image/versions/1.0/image-id.blob"
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff")

        result = LayoutResolver(
            self.cache,
            "Pkg",
            "Doc",
            {"show": True, "name": "ABCDE", "includeImage": True},
            effective_date="2026-09-25",
        ).resolve("header")
        content = result["layout"]["children"][2]
        self.assertTrue(content["passed"])
        self.assertEqual("[image: sample.png]", content["rendered"])
        self.assertEqual("PNG", content["assets"][0]["format"])

    def test_iteration_fields_render_for_each_matching_row(self) -> None:
        template_path = self.cache / "packages/Pkg/versions/v1/AssemblyTemplate.json"
        template = json.loads(template_path.read_text(encoding="utf-8"))
        template["Documents"][0]["Layouts"] = [{
            "$$Id": "header",
            "Contents": [{
                "$$Id": "iterated-content",
                "Condition": "$[?(@.rows empty false)]",
                "Iteration": {
                    "$$Id": "Rows",
                    "Type": "Iterator",
                    "Path": "$.rows[*]",
                    "Fields": [{"Name": "RowName", "Path": "$.name"}],
                },
            }],
        }]
        template_path.write_text(json.dumps(template), encoding="utf-8")

        layout_path = self.cache / "layouts/header/header.json"
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
        layout["CommunicationLayoutContents"].append({
            "ShortName": "iterated-content",
            "CommunicationLayoutConfigCommunicationContentConfigRelRec": {
                "CommunicationLayoutConfigCommunicationContentConfigRelInfo": {
                    "ContentRelIndex": 3,
                    "ContentAlwaysTriggerInd": False,
                },
            },
        })
        layout_path.write_text(json.dumps(layout), encoding="utf-8")

        active = {"Items": [{"StatusCode": "Active", "EffDtTm": "2026-01-01T00:00:00Z"}]}
        master_path = self.cache / "contents/iterated-content/iterated-content_master.json"
        master_path.parent.mkdir(parents=True, exist_ok=True)
        master_path.write_text(json.dumps({
            "CommunicationContentMasterVersions": [{"CommunicationContentVersionConfigRec": {
                "CommunicationContentVersionConfigInfo": {
                    "ShortName": "1.0",
                    "CommunicationContentVersionConfigData": {
                        "Items": [{"ContentData": {"FileId": "iterated-content"}}],
                    },
                },
                "Status": active,
            }}],
        }), encoding="utf-8")
        blob_path = self.cache / "contents/iterated-content/versions/1.0/iterated-content.blob"
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_text(
            '<p><comms-loop><comms-data>$Data{"Id":"Rows"}</comms-data></comms-loop>'
            '<comms-data>$Data{"Id":"RowName"}</comms-data></p>',
            encoding="utf-8",
        )

        result = LayoutResolver(
            self.cache,
            "Pkg",
            "Doc",
            {"show": True, "name": "ABCDE", "rows": [{"name": "Alpha"}, {"name": "Beta"}]},
            effective_date="2026-09-25",
        ).resolve("header")
        content = result["layout"]["children"][2]
        self.assertTrue(content["passed"])
        self.assertEqual("Alpha\nBeta", content["rendered"])
        loop = content["children"][1]
        self.assertEqual(2, loop["count"])
        self.assertEqual(["Alpha"], loop["children"][0]["children"][0]["values"])
        self.assertNotIn("Iteration context", "\n".join(result["warnings"]))

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
        self.assertEqual(
            "ABC\npage one\ngrid page one\nname present",
            resolver.resolve("header")["layout"]["children"][0]["rendered"],
        )


if __name__ == "__main__":
    unittest.main()
