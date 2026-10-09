"""Package sessions using ATool's local mapping engine and bundle metadata."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from atool_core.condition_evaluator import ConditionEvaluator
from .paths import PathNormalizer
from .diagnostics import ConditionDiagnostics
from .layout_mapping import layout_nodes


def read_json(path: Path) -> object:
    text = path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Match ATool's tolerant reader, without writing corrected files.
        return json.loads(PathNormalizer._strip_trailing_commas(text))


def resolve_template(path: Path) -> Path:
    """Accept a raw AT, a bundle directory, or its manifest."""
    path = path.expanduser().resolve()
    if path.is_dir():
        if (path / "occs-package.json").is_file():
            return resolve_template(path / "occs-package.json")
        for name in ("assembly-template.json", "AssemblyTemplate.json"):
            if (path / name).is_file():
                return path / name
        manifests = sorted(path.glob("*manifest*.json"))
        if len(manifests) != 1:
            raise ValueError("Choose the bundle's Assembly Template JSON file.")
        path = manifests[0]
    value = read_json(path)
    if isinstance(value, dict) and (isinstance(value.get("files"), dict) or value.get("schemaVersion") == "occs-package-bundle/v1"):
        files = value.get("files") if isinstance(value.get("files"), dict) else {}
        relative = files.get("assemblyTemplate") or ("assembly-template.json" if value.get("schemaVersion") == "occs-package-bundle/v1" else None)
        if relative:
            return (path.parent / str(relative)).resolve()
    return path


@dataclass
class PackageSession:
    name: str
    source: Path | None
    documents: list[dict]
    fields: list[dict]
    data: object = None
    data_name: str = "No data mapped"
    mapped: bool = False
    clauses: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    mapping_revision: int = 0
    payload: dict = field(default_factory=dict)
    bundle: dict = field(default_factory=dict)

    @classmethod
    def open(cls, path: Path) -> "PackageSession":
        template = resolve_template(path)
        payload = read_json(template)
        session = cls.from_payload(payload, template)
        manifest, root, manifest_path = {}, template.parent, None
        requested = path.expanduser().resolve()
        candidates = ([requested] if requested.is_file() else
                      [requested / "occs-package.json", *sorted(requested.glob("*manifest*.json"))])
        candidates += [parent / "occs-package.json" for parent in list(template.parents)[:3]]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            value = read_json(candidate)
            if isinstance(value, dict) and (isinstance(value.get("files"), dict) or value.get("schemaVersion") == "occs-package-bundle/v1"):
                files = value.get("files") if isinstance(value.get("files"), dict) else {}
                target = files.get("assemblyTemplate", "assembly-template.json")
                if (candidate.parent / str(target)).resolve() == template:
                    manifest, root, manifest_path = value, candidate.parent, candidate
                    break

        def optional(key, fallback):
            files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
            candidate = root / str(files.get(key) or fallback)
            if not candidate.is_file():
                return None
            try:
                value = read_json(candidate)
                if not isinstance(value, dict):
                    raise ValueError("Expected a JSON object")
                return value
            except (OSError, ValueError) as error:
                session.notes.append(f"Could not read {candidate.name}: {error}")
                return None

        helper = optional("documentAssociations", "document-associations.json")
        master = optional("versionMaster", "version-master.json")
        if manifest_path:
            files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
            session.bundle = {"root": root, "manifest_path": manifest_path, "manifest": manifest,
                              "helper_path": root / str(files.get("documentAssociations") or "document-associations.json"),
                              "master_path": root / str(files.get("versionMaster") or "version-master.json"),
                              "helper": helper, "master": master}
        session.incorporate_package_documents(helper, master)
        # Match ATool's fallback to its saved per-package clause library.
        if not session.clauses and not embedded_clauses(payload)[1]:
            slug = re.sub(r"[^A-Za-z0-9]+", "_", session.name).strip("_").lower() or "unknown"
            metadata = Path.home() / ".atool" / f".{slug}.meta.json"
            if metadata.is_file():
                try:
                    saved = read_json(metadata)
                    session.clauses = clean_clauses(saved.get("clause_library", [])) if isinstance(saved, dict) else []
                except (OSError, ValueError) as error:
                    session.notes.append(f"Could not read saved clause library: {error}")
        return session

    @classmethod
    def from_payload(cls, payload: object, source: Path | None = None) -> "PackageSession":
        if not isinstance(payload, dict) or not any(key in payload for key in ("Documents", "Fields")):
            raise ValueError("This file is not an Assembly Template (expected Documents or Fields).")
        for key in ("Documents", "Fields"):
            if key in payload and not isinstance(payload[key], list):
                raise ValueError(f"{key} must be a list.")
        documents = []
        for doc in payload.get("Documents", []):
            if isinstance(doc, dict) and doc.get("$$Id"):
                documents.append({"name": str(doc["$$Id"]), "condition": str(doc.get("Condition", "")),
                                  "descr": str(doc.get("Descr", "")), "updated": str(doc.get("Updated", "")),
                                  "source": doc, "in_at": True, "associated": None, "order": None,
                                  "status": "Package list unavailable", "always_trigger": False})
        normalizer = PathNormalizer()
        fields, seen = [], set()
        for item in payload.get("Fields", []):
            if not isinstance(item, dict) or not item.get("Name") or not item.get("Path"):
                continue
            mandatory = item.get("Mandatory")
            mandatory = (mandatory.strip().lower() in {"true", "1", "yes"} if isinstance(mandatory, str)
                         else True if mandatory is None else bool(mandatory))
            path = normalizer._normalize_path_expression(str(item["Path"]))
            key = (str(item["Name"]), path, mandatory)
            if key in seen:
                continue
            seen.add(key)
            fields.append({"name": key[0], "path": path, "true_path": normalizer._normalize_true_path(path),
                           "mandatory": mandatory, "descr": str(item.get("Descr", "")),
                           "updated": str(item.get("Updated", "")), "source": item})
        return cls(str(payload.get("$$Id") or (source.stem if source else "Package")), source, documents, fields,
                   clauses=clean_clauses(embedded_clauses(payload)[0]), payload=payload)

    def incorporate_package_documents(self, helper: dict | None, master: dict | None = None) -> None:
        """Merge package associations into the document list in relationship order."""
        associations = helper.get("associations") if isinstance(helper, dict) else None
        associations = [dict(item) for item in associations if isinstance(item, dict)] if isinstance(associations, list) else None
        relations = master.get("CommunicationPackageVersionDocuments") if isinstance(master, dict) else None
        if isinstance(relations, list):
            by_uuid = {str(item.get("documentConfigUuid")): item for item in associations or []}
            resolved = []
            for item in relations:
                if not isinstance(item, dict):
                    continue
                rec = item.get("CommunicationPackageVersionConfigCommunicationDocumentConfigRelRec", {})
                info = rec.get("CommunicationPackageVersionConfigCommunicationDocumentConfigRelInfo", {}) if isinstance(rec, dict) else {}
                if not isinstance(info, dict) or not info:
                    continue
                uuid = str(info.get("CommunicationDocumentConfigUuid", ""))
                association = dict(by_uuid.get(uuid, {}))
                doc_rec = item.get("CommunicationDocumentConfigRec", {})
                doc_info = doc_rec.get("CommunicationDocumentConfigInfo", {}) if isinstance(doc_rec, dict) else {}
                if not association.get("documentShortName") and isinstance(doc_info, dict):
                    association["documentShortName"] = str(doc_info.get("ShortName", ""))
                association.update(documentConfigUuid=uuid, documentRelIndex=info.get("DocumentRelIndex"),
                                   documentAlwaysTriggerInd=info.get("DocumentAlwaysTriggerInd", False))
                resolved.append(association)
            associations = resolved
        if associations is None:
            self.notes.append("Package document list unavailable; showing Assembly Template order.")
            return
        at = {doc["name"].strip().casefold(): doc for doc in self.documents}
        rows, seen = [], set()
        for association in associations:
            name = str(association.get("documentShortName", "")).strip()
            doc = at.get(name.casefold())
            row = dict(doc) if doc else {"name": name or str(association.get("documentConfigUuid") or "Unresolved document"),
                                       "source": {}, "condition": "", "descr": str(association.get("documentDescription", "")),
                                       "updated": "", "in_at": False}
            try:
                order = int(str(association.get("documentRelIndex")))
            except (ValueError, TypeError):
                order = None
            always = association.get("documentAlwaysTriggerInd", False)
            always = always.strip().lower() in {"true", "1", "yes"} if isinstance(always, str) else bool(always)
            row.update(associated=True, order=order, always_trigger=always, association=association,
                       status="In package + AT" if doc else "Missing from AT")
            if name.casefold() in seen:
                row["status"] += " · Duplicate association"
            if order is None:
                row["status"] += " · Order missing"
            rows.append(row)
            seen.add(name.casefold())
        rows.sort(key=lambda row: (row["order"] is None, row["order"] or 0))
        for doc in self.documents:
            if doc["name"].strip().casefold() not in seen:
                rows.append(dict(doc, associated=False, status="AT only — not in package"))
        self.documents = rows

    def document_details(self, doc: dict) -> dict:
        if not self.mapped:
            return {"label": "Map JSON data to evaluate conditions", "passed": None, "details": []}
        evaluator = ConditionDiagnostics(self.fields)
        condition = evaluator.explain(doc["condition"], self.data, self.clauses) if doc.get("in_at") else None
        details = []
        if doc.get("associated") is False:
            details.append("Assembly Template document is not listed in the package.")
        if not doc.get("in_at"):
            details.append("Document is listed in the package but missing from the Assembly Template.")
        if doc.get("always_trigger"):
            details.append("Package association is set to Always Trigger; AT condition does not gate this document.")
        elif condition is None:
            details.append("No Assembly Template condition is available; conditional trigger cannot be evaluated.")
        return {"label": "Document trigger", "passed": doc.get("triggered", False), "details": details + doc.get("warnings", []),
                "children": [condition] if condition else []}

    def map_data(self, data: object, name: str) -> None:
        evaluator = ConditionEvaluator(self.fields)
        # Build all results first so failed jobs cannot leave partial mapping state.
        values = [evaluator._extract_values_by_path(data, item["true_path"]) for item in self.fields]
        triggers = []
        for doc in self.documents:
            warnings: list[str] = []
            matched = bool(doc.get("always_trigger")) or (doc.get("in_at", True) and
                      evaluator._evaluate_document_condition(doc["condition"], data, warnings=warnings))
            if doc.get("associated") is False:
                matched = False
            triggers.append((matched, warnings))
        for item, value in zip(self.fields, values):
            item["mapped_values"] = value
        for doc, (matched, warnings) in zip(self.documents, triggers):
            doc["triggered"], doc["warnings"] = matched, warnings
        self.data, self.data_name, self.mapped = data, name, True
        self.mapping_revision += 1

    def layouts_for(self, document: dict) -> list[dict]:
        return layout_nodes(document, self.data, self.mapped, self.fields, self.clauses)


def clean_clauses(entries: object) -> list[dict]:
    if not isinstance(entries, list):
        return []
    return [{**item, "name": str(item["name"]), "expression": str(item.get("expression", "")),
             "description": str(item.get("description", item.get("descr", "")))}
            for item in entries if isinstance(item, dict) and item.get("name")]


def embedded_clauses(payload: object) -> tuple[list, bool]:
    meta = payload.get("Meta", {}) if isinstance(payload, dict) else {}
    if not isinstance(meta, dict):
        return [], False
    namespaced = meta.get("ATool", {})
    for entries in (meta.get("clause_library"), namespaced.get("clause_library") if isinstance(namespaced, dict) else None,
                    meta.get("condition_library")):
        if isinstance(entries, list):
            return entries, True
    return [], False


def demo_session() -> PackageSession:
    session = PackageSession.from_payload({
        "$$Id": "Sample billing package",
        "Documents": [
            {"$$Id": "BILL", "Descr": "Main customer bill", "Layouts": [
                {"$$Id": "header", "Type": "Block", "Descr": "Customer and account details", "Contents": [
                    {"$$Id": "customer_details", "Descr": "Customer details block"}]},
                {"$$Id": "charges", "Descr": "Itemized charges", "Contents": [
                    {"$$Id": "charge_rows", "Condition": "$[?(@.balance > 0)]", "Iteration": {"Name": "Charges", "Path": "$.charges[*]", "Fields": [
                        {"Name": "Description", "Type": "Text", "Mandatory": False, "Path": "$.charges[*].description"},
                        {"Name": "Amount", "Type": "Number", "Mandatory": True, "Path": "$.charges[*].amount"}]}}]},
            ]},
            {"$$Id": "BILL_NOTICE", "Descr": "Notice for an outstanding balance", "Condition": "$[?(@.balance > 0 && @.customer.name not empty)]"},
            {"$$Id": "BILL_CREDIT", "Descr": "Credit balance notice", "Condition": "$[?(@.balance < 0)]"},
        ],
        "Fields": [
            {"Name": "CustomerName", "Path": "$.customer.name", "Descr": "Customer display name"},
            {"Name": "AccountNumber", "Path": "$.customer.account"},
            {"Name": "Balance", "Path": "$.balance"},
            {"Name": "ChargeDescription", "Path": "$.charges[*].description", "Mandatory": False},
            {"Name": "ChargeAmount", "Path": "$.charges[*].amount", "Mandatory": False},
            {"Name": "CustomerEmail", "Path": "$.customer.email", "Mandatory": False},
        ],
    })
    session.clauses = [{"name": "positive_balance", "expression": "@.balance > 0"},
                       {"name": "customer_present", "expression": "@.customer.name not empty"},
                       {"name": "credit_balance", "expression": "@.balance < 0"}]
    session.incorporate_package_documents({"associations": [
        {"documentShortName": "BILL", "documentRelIndex": 1, "documentAlwaysTriggerInd": True},
        {"documentShortName": "BILL_NOTICE", "documentRelIndex": 2},
        {"documentShortName": "BILL_CREDIT", "documentRelIndex": 3},
        {"documentShortName": "BILL_APPENDIX", "documentRelIndex": 4}]})
    session.map_data({"customer": {"name": "Alex Morgan", "account": "ACC-1042"}, "balance": 84.5,
                      "charges": [{"description": "Monthly service", "amount": 65},
                                  {"description": "Usage", "amount": 19.5}]}, "Sample data")
    return session
