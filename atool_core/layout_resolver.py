"""Explain the content selected by a cached Comms document layout."""

from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from atool_core.condition_evaluator import ConditionEvaluator


_COMMS_TAG = re.compile(r"<comms-(cond|data|loop)(?:\s[^>]*)?>", re.IGNORECASE)
_BLOCK_END = re.compile(r"</(?:p|div|tr|table|figure)>|<br\s*/?>", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_COND_HEAD = re.compile(
    r'^\$Cond\{"Condition":"(?P<condition>(?:\\.|[^"\\])*)","(?P<kind>Text|Content)":"',
    re.DOTALL,
)


def _label(record: dict[str, Any]) -> str:
    return str(record.get("ShortName") or record.get("Name") or record.get("$$Id") or "")


def _display(values: list[Any]) -> str:
    return ", ".join(str(value) for value in values if value is not None)


def _clean_text(value: str) -> str:
    lines = [re.sub(r"[\t \u00a0]+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


class LayoutResolver:
    """Resolve one layout from a downloaded resource cache and an input JSON object.

    Results are evidence trees. Unknown conditions stay unknown rather than
    silently selecting or suppressing a branch.
    """

    def __init__(
        self,
        cache_root: Path,
        package: str,
        document: str,
        payload: object,
        *,
        effective_date: str | None = None,
        at_version: str | None = None,
        system_fields: dict[str, Any] | None = None,
        assembly_template: dict[str, Any] | None = None,
    ) -> None:
        self.cache_root = Path(cache_root)
        self.package = package
        self.document = document
        self.payload = payload
        self.effective_date = effective_date or date.today().isoformat()
        self.system_fields = {"PackagePageNum": 1, **(system_fields or {})}
        self.evaluator = ConditionEvaluator()
        self.warnings: list[str] = []
        self._field_cache: dict[str, dict[str, Any]] = {}
        self._content_stack: list[str] = []

        if assembly_template is not None:
            template = assembly_template
            self.template_path: Path | str = "(open ATool package)"
        else:
            version_root = self.cache_root / "packages" / package / "versions"
            templates = sorted(version_root.glob("*/AssemblyTemplate.json"))
            if at_version is not None:
                templates = [path for path in templates if path.parent.name == at_version]
            if len(templates) != 1:
                raise ValueError(
                    f"Expected one Assembly Template for {package}; found {len(templates)}. "
                    "Specify --at-version if the cache has several."
                )
            self.template_path = templates[0]
            template = self._read_json(self.template_path)
        self.fields = {
            str(field.get("Name")): str(field.get("Path", ""))
            for field in template.get("Fields", [])
            if isinstance(field, dict) and field.get("Name")
        }
        matches = [
            item for item in template.get("Documents", [])
            if isinstance(item, dict) and str(item.get("$$Id", "")).casefold() == document.casefold()
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one document named {document!r} in {self.template_path}; found {len(matches)}")
        self.at_document = matches[0]
        self.document_name = str(self.at_document["$$Id"])

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Cannot read cached JSON {path}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"Expected a JSON object in {path}")
        return value

    @staticmethod
    def _cached_folder(root: Path, name: str) -> Path:
        candidate = root / quote(name, safe=" -_.()")
        if candidate.is_dir():
            return candidate
        candidate = root / name
        if candidate.is_dir():
            return candidate
        for folder in root.iterdir() if root.is_dir() else ():
            if folder.is_dir() and folder.name.casefold() == name.casefold():
                return folder
        raise ValueError(f"Cached resource {name!r} was not found below {root}")

    @staticmethod
    def _active_version(master: dict[str, Any], versions_key: str, record_key: str, effective_date: str) -> dict[str, Any]:
        candidates: list[tuple[str, dict[str, Any]]] = []
        for item in master.get(versions_key, []):
            record = item.get(record_key, {}) if isinstance(item, dict) else {}
            if not isinstance(record, dict):
                continue
            dates = [
                str(status.get("EffDtTm", ""))
                for status in record.get("Status", {}).get("Items", [])
                if status.get("StatusCode") == "Active"
                and str(status.get("EffDtTm", ""))[:10] <= effective_date
            ]
            if dates:
                candidates.append((max(dates), record))
        if not candidates:
            raise ValueError(f"No active cached version on {effective_date}")
        return max(candidates, key=lambda pair: pair[0])[1]

    @staticmethod
    def _arguments(expression: str) -> list[str]:
        result: list[str] = []
        start = 0
        parens = brackets = 0
        quote_char = ""
        escaped = False
        for index, char in enumerate(expression):
            if quote_char:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote_char:
                    quote_char = ""
                continue
            if char in "'\"":
                quote_char = char
            elif char == "(":
                parens += 1
            elif char == ")":
                parens -= 1
            elif char == "[":
                brackets += 1
            elif char == "]":
                brackets -= 1
            elif char == "," and parens == brackets == 0:
                result.append(expression[start:index].strip())
                start = index + 1
        result.append(expression[start:].strip())
        return result

    def _path_values(self, path: str) -> list[Any]:
        path = path.strip()
        wrapper = re.fullmatch(r"\$\.?(concat|length)\((.*)\)", path, re.DOTALL)
        if wrapper:
            operation, arguments = wrapper.group(1), self._arguments(wrapper.group(2))
            if operation == "length":
                return [len(self._path_values(arguments[0]))]
            pieces: list[str] = []
            for argument in arguments:
                literal, is_literal = self.evaluator._parse_condition_literal(argument)
                if is_literal:
                    pieces.append("" if literal is None else str(literal))
                else:
                    pieces.extend(str(value) for value in self._path_values(argument) if value is not None)
            combined = "".join(pieces)
            return [combined] if combined else []
        if not path.startswith("$"):
            self._warn(f"Unsupported field path: {path}")
            return []
        return self.evaluator._extract_values_by_path(self.payload, path)

    def _field(self, name: str) -> dict[str, Any]:
        if name in self._field_cache:
            return self._field_cache[name]
        if name in self.system_fields:
            result = {"name": name, "path": "(system generated)", "values": [self.system_fields[name]]}
        elif name in self.fields:
            path = self.fields[name]
            result = {"name": name, "path": path, "values": self._path_values(path)}
        else:
            self._warn(f"Unknown field {name!r}")
            result = {"name": name, "path": "(unknown)", "values": [], "unknown": True}
        self._field_cache[name] = result
        return result

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def _operand(self, token: str) -> tuple[list[Any], dict[str, Any] | None, bool]:
        token = token.strip()
        literal, is_literal = self.evaluator._parse_condition_literal(token)
        if is_literal:
            return [literal], None, False
        if token.startswith(("$", "@")):
            values = self.evaluator._extract_values_by_path(self.payload, "$" + token[1:] if token.startswith("@") else token)
            return values, {"name": token, "path": token, "values": values}, False
        field = self._field(token)
        return field["values"], field, bool(field.get("unknown"))

    def _condition(self, expression: str) -> dict[str, Any]:
        expr = self.evaluator._strip_outer_parens(expression)
        or_parts = self.evaluator._split_top_level_operator(expr, "||")
        if len(or_parts) > 1:
            parts = [self._condition(part) for part in or_parts]
            status = True if any(part["passed"] is True for part in parts) else None if any(part["passed"] is None for part in parts) else False
            return {"expression": expression, "passed": status, "parts": parts}
        and_parts = self.evaluator._split_top_level_operator(expr, "&&")
        if len(and_parts) > 1:
            parts = [self._condition(part) for part in and_parts]
            status = False if any(part["passed"] is False for part in parts) else None if any(part["passed"] is None for part in parts) else True
            return {"expression": expression, "passed": status, "parts": parts}
        negated = self.evaluator._unwrap_condition_negation(expr)
        if negated is not None:
            child = self._condition(negated)
            return {"expression": expression, "passed": None if child["passed"] is None else not child["passed"], "parts": [child]}
        empty = re.fullmatch(r"(.+?)\s+empty\s+(true|false)", expr, re.IGNORECASE | re.DOTALL)
        if empty:
            values, field, unknown = self._operand(empty.group(1))
            is_empty = not any(value is not None and value != "" and value != [] and value != {} for value in values)
            passed = None if unknown else is_empty == (empty.group(2).lower() == "true")
            return {"expression": expression, "passed": passed, "operands": [field] if field else []}
        comparison = self.evaluator._find_top_level_comparison(expr)
        if comparison:
            left, operator, right = comparison
            lhs, lhs_field, lhs_unknown = self._operand(left)
            rhs, rhs_field, rhs_unknown = self._operand(right)
            if not lhs:
                lhs = [None]
            if not rhs:
                rhs = [None]
            if operator == "!=":
                passed = all(not self.evaluator._compare_single_condition_value(a, "==", b) for a in lhs for b in rhs)
            else:
                passed = any(self.evaluator._compare_single_condition_value(a, operator, b) for a in lhs for b in rhs)
            return {
                "expression": expression,
                "passed": None if lhs_unknown or rhs_unknown else passed,
                "operands": [item for item in (lhs_field, rhs_field) if item],
            }
        self._warn(f"Unsupported content condition: {expression}")
        return {"expression": expression, "passed": None, "operands": []}

    @staticmethod
    def _plain(markup: str) -> str:
        text = _BLOCK_END.sub("\n", markup)
        text = re.sub(r"</td>", " ", text, flags=re.IGNORECASE)
        return html.unescape(_HTML_TAG.sub("", text))

    @staticmethod
    def _tag_end(markup: str, kind: str, start: int) -> tuple[int, int]:
        tags = re.compile(rf"</?comms-{kind}(?:\s[^>]*)?>", re.IGNORECASE)
        depth = 0
        for match in tags.finditer(markup, start):
            depth += -1 if match.group().startswith("</") else 1
            if depth == 0:
                return match.start(), match.end()
        raise ValueError(f"Unclosed comms-{kind} tag")

    def _markup(self, markup: str) -> tuple[list[dict[str, Any]], str]:
        children: list[dict[str, Any]] = []
        output: list[str] = []
        cursor = 0
        while match := _COMMS_TAG.search(markup, cursor):
            output.append(self._plain(markup[cursor:match.start()]))
            kind = match.group(1).lower()
            inner_end, tag_end = self._tag_end(markup, kind, match.start())
            inner = markup[match.end():inner_end]
            if kind == "loop":
                self._warn("Content loop requires iteration context and is not resolved in this first cut")
                children.append({"kind": "loop", "passed": None, "warning": "Iteration context not implemented"})
                output.append("[unresolved loop]")
            elif kind == "data":
                data_match = re.search(r"\$Data(\{[^}]*\})", inner, re.DOTALL)
                try:
                    data = json.loads(data_match.group(1)) if data_match else {}
                except json.JSONDecodeError:
                    data = {}
                field_name = str(data.get("Id", ""))
                field = self._field(field_name) if field_name else {"name": "", "path": "(invalid)", "values": [], "unknown": True}
                value = _display(field["values"])
                if data.get("BarcodeType"):
                    value = f"[{data['BarcodeType']} barcode: {value}]" if value else "[barcode: no mapped value]"
                transform = re.search(r"<comms-transform\b([^>]*)>", inner, re.IGNORECASE)
                if transform:
                    attributes = dict(re.findall(r"([\w-]+)\s*=\s*\"([^\"]*)\"", transform.group(1)))
                    if attributes.get("type") == "substring":
                        try:
                            start = max(0, int(attributes.get("start", "1")) - 1)
                            length = int(attributes.get("length", str(len(value))))
                            value = value[start:start + length]
                        except ValueError:
                            self._warn(f"Invalid substring transform on {field_name}")
                    else:
                        self._warn(f"Unsupported transform on {field_name}: {attributes.get('type', '(unknown)')}")
                children.append({"kind": "field", **field, "passed": bool(field["values"]) and not field.get("unknown", False), "rendered": value, "barcode_type": data.get("BarcodeType")})
                output.append(value)
            else:
                head = _COND_HEAD.match(inner)
                if not head or not inner.endswith('"}'):
                    self._warn("Could not parse a conditional content fragment")
                    children.append({"kind": "condition", "passed": None, "raw": inner[:300]})
                else:
                    condition_text = json.loads('"' + head.group("condition") + '"')
                    check = self._condition(condition_text)
                    target = inner[head.end():-2]
                    branch: dict[str, Any] = {"kind": "condition", **check, "target_kind": head.group("kind")}
                    if head.group("kind") == "Content":
                        branch["target"] = target
                        if check["passed"] is True:
                            child = self._content(target)
                            branch["children"] = [child]
                            branch["rendered"] = child.get("rendered", "")
                            if branch["rendered"]:
                                output.append("\n" + branch["rendered"] + "\n")
                    elif check["passed"] is True:
                        branch["children"], branch["rendered"] = self._markup(target)
                        output.append(branch["rendered"])
                    children.append(branch)
            cursor = tag_end
        output.append(self._plain(markup[cursor:]))
        return children, "".join(output)

    def _content(self, name: str) -> dict[str, Any]:
        node: dict[str, Any] = {"kind": "content", "name": name, "passed": True, "children": [], "rendered": ""}
        if name in self._content_stack:
            node["passed"] = None
            node["warning"] = "Content include cycle"
            self._warn(f"Content include cycle: {' -> '.join([*self._content_stack, name])}")
            return node
        try:
            folder = self._cached_folder(self.cache_root / "contents", name)
            master_path = next(folder.glob("*_master.json"))
            master = self._read_json(master_path)
            version = self._active_version(master, "CommunicationContentMasterVersions", "CommunicationContentVersionConfigRec", self.effective_date)
            version_name = str(version.get("CommunicationContentVersionConfigInfo", {}).get("ShortName", ""))
            node.update({"version": version_name, "source": str(master_path)})
            version_folder = folder / "versions" / version_name
            blob_ids = [
                str(item.get("ContentData", {}).get("FileId", ""))
                for item in version.get("CommunicationContentVersionConfigInfo", {}).get("CommunicationContentVersionConfigData", {}).get("Items", [])
            ]
            blobs = [version_folder / f"{blob_id}.blob" for blob_id in blob_ids if blob_id]
            if not blobs:
                blobs = sorted(version_folder.glob("*.blob"))
            self._content_stack.append(name)
            try:
                for blob_path in blobs:
                    markup = html.unescape(blob_path.read_text(encoding="utf-8"))
                    unsupported = sorted(set(re.findall(r"<comms-(?!cond\b|data\b|loop\b|transform\b)([\w-]+)", markup, flags=re.IGNORECASE)))
                    for tag in unsupported:
                        self._warn(f"Unsupported comms-{tag} markup in {name}")
                    branches, rendered = self._markup(markup)
                    node["children"].extend(branches)
                    node["rendered"] = _clean_text("\n".join(filter(None, [node["rendered"], rendered])))
                    node.setdefault("blobs", []).append(str(blob_path))
            finally:
                self._content_stack.pop()
            if not blobs:
                self._warn(f"No content blob found for {name} version {version_name}")
        except (ValueError, OSError, StopIteration) as error:
            node["passed"] = None
            node["warning"] = str(error)
            self._warn(f"Could not resolve content {name}: {error}")
        return node

    def _layout(self, name: str, uuid: str, trail: tuple[str, ...] = ()) -> dict[str, Any]:
        node: dict[str, Any] = {"kind": "layout", "name": name, "uuid": uuid, "passed": True, "children": []}
        if uuid in trail:
            node["passed"] = None
            node["warning"] = "Layout relationship cycle"
            self._warn(f"Layout relationship cycle at {name}")
            return node
        folder = self._cached_folder(self.cache_root / "layouts", name)
        paths = [path for path in folder.glob("*.json") if path.name != "document.json"]
        if len(paths) != 1:
            raise ValueError(f"Expected one layout record for {name}, found {len(paths)}")
        record = self._read_json(paths[0])
        actual_uuid = str(record.get("CommunicationLayoutConfigRec", {}).get("CommunicationLayoutConfigUuid", ""))
        if actual_uuid != uuid:
            raise ValueError(f"Layout UUID mismatch for {name}: relationship {uuid}, cache {actual_uuid}")
        node.update({"type": record.get("CommunicationLayoutConfigRec", {}).get("CommunicationLayoutConfigInfo", {}).get("LayoutType", ""), "source": str(paths[0])})
        relationships: list[tuple[int, dict[str, Any]]] = []
        for item in record.get("CommunicationLayoutLayouts", []):
            rel = item.get("CommunicationLayoutConfigCommunicationLayoutConfigRelRec", {}).get("CommunicationLayoutConfigCommunicationLayoutConfigRelInfo", {})
            relationships.append((int(rel.get("LayoutRelIndex") or 0), {"kind": "layout", "name": _label(item), "uuid": str(rel.get("RelCommunicationLayoutConfigUuid", "")), "area": str(rel.get("StyleAreaName", "")), "always": rel.get("LayoutAlwaysTriggerInd")}))
        for item in record.get("CommunicationLayoutContents", []):
            rel = item.get("CommunicationLayoutConfigCommunicationContentConfigRelRec", {}).get("CommunicationLayoutConfigCommunicationContentConfigRelInfo", {})
            relationships.append((int(rel.get("ContentRelIndex") or 0), {"kind": "content", "name": _label(item), "area": str(rel.get("StyleAreaName", "")), "always": rel.get("ContentAlwaysTriggerInd")}))
        for index, child in sorted(relationships, key=lambda pair: pair[0]):
            if child["always"] is False:
                self._warn(f"{name} -> {child['name']} has an unmodeled relationship trigger")
                node["children"].append({**child, "index": index, "passed": None, "warning": "Relationship trigger not modeled"})
                continue
            resolved = self._layout(child["name"], child["uuid"], (*trail, uuid)) if child["kind"] == "layout" else self._content(child["name"])
            resolved.update({"index": index, "area": child["area"]})
            node["children"].append(resolved)
        return node

    def _document_record(self) -> tuple[str, Path, dict[str, Any]]:
        doc_folder = self._cached_folder(self.cache_root / "documents", self.document_name)
        master_path = next(doc_folder.glob("*_master.json"))
        master = self._read_json(master_path)
        version = self._active_version(master, "CommunicationDocumentMasterVersions", "CommunicationDocumentVersionConfigRec", self.effective_date)
        version_name = str(version.get("CommunicationDocumentVersionConfigInfo", {}).get("ShortName", ""))
        version_path = doc_folder / "versions" / f"{version_name}.json"
        record = self._read_json(version_path)
        return version_name, version_path, record

    @staticmethod
    def _document_roots(record: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
        roots = []
        for item in record.get("CommunicationDocumentVersionLayouts", []):
            rel = item.get("CommunicationDocumentVersionConfigCommunicationLayoutConfigRelRec", {}).get("CommunicationDocumentVersionConfigCommunicationLayoutConfigRelInfo", {})
            layout = item.get("CommunicationLayoutConfigRec", {})
            roots.append((_label(layout.get("CommunicationLayoutConfigInfo", {})), str(layout.get("CommunicationLayoutConfigUuid", "")), rel))
        return sorted(roots, key=lambda item: int(item[2].get("LayoutRelIndex") or 0))

    def available_layouts(self) -> tuple[str, list[str]]:
        """Return root layout choices for the selected cached document version."""
        version_name, _, record = self._document_record()
        return version_name, [name for name, _, _ in self._document_roots(record) if name]

    def resolve(self, layout_name: str) -> dict[str, Any]:
        condition = str(self.at_document.get("Condition", ""))
        doc_warnings: list[str] = []
        triggered = self.evaluator._evaluate_document_condition(condition, self.payload, warnings=doc_warnings)
        self.warnings.extend(item for item in doc_warnings if item not in self.warnings)
        version_name, version_path, record = self._document_record()
        roots = self._document_roots(record)
        matches = [root for root in roots if root[0].casefold() == layout_name.casefold()]
        if len(matches) != 1:
            raise ValueError(f"Expected one root layout {layout_name!r} in {self.document_name} version {version_name}; found {len(matches)}")
        root_name, uuid, relation = matches[0]
        root = self._layout(root_name, uuid) if triggered else {"kind": "layout", "name": root_name, "uuid": uuid, "passed": False, "children": []}
        root["placement"] = relation.get("LayoutPlacement", "")
        root["index"] = relation.get("LayoutRelIndex", 0)
        return {
            "package": self.package,
            "document": self.document_name,
            "document_triggered": triggered,
            "document_version": version_name,
            "document_source": str(version_path),
            "assembly_template": str(self.template_path),
            "effective_date": self.effective_date,
            "system_fields": self.system_fields,
            "layout": root,
            "warnings": self.warnings,
        }


def format_report(result: dict[str, Any]) -> str:
    """Turn a resolver evidence tree into a concise, readable trace."""
    header = [
        f"{result['package']} / {result['document']} {result['document_version']}",
        f"Effective date: {result['effective_date']}",
        f"Document trigger: {'yes' if result['document_triggered'] else 'no'}",
        "System fields: " + ", ".join(f"{key}={value}" for key, value in result["system_fields"].items()),
        "",
    ]

    def walk(node: dict[str, Any], depth: int) -> list[str]:
        indent = "  " * depth
        status = "✓" if node.get("passed") is True else "✗" if node.get("passed") is False else "?"
        kind = node.get("kind", "item")
        if kind == "condition":
            label = f"{status} if {node.get('expression', '(unparsed)')}"
            if node.get("target_kind") == "Content":
                label += f" → {node.get('target', '')}"
        elif kind == "field":
            label = f"{status} ${node['name']} = {node.get('rendered', '')!r} ({node['path']})"
        else:
            label = f"{status} {kind} {node.get('name', '')}"
            if node.get("area"):
                label += f" [{node['area']}]"
            if node.get("version"):
                label += f" v{node['version']}"
        lines = [indent + label]
        if kind == "condition" and node.get("passed") is not True:
            operands: dict[str, list[Any]] = {}
            def gather(check: dict[str, Any]) -> None:
                for operand in check.get("operands", []):
                    operands[str(operand["name"])] = operand.get("values", [])
                for part in check.get("parts", []):
                    gather(part)
            gather(node)
            if operands:
                lines.append(indent + "  values: " + "; ".join(
                    f"{name}={values!r}" for name, values in operands.items()
                ))
        if kind == "content" and node.get("rendered"):
            lines.extend(indent + "  " + line for line in node["rendered"].splitlines())
        if node.get("warning"):
            lines.append(indent + "  " + str(node["warning"]))
        for child in node.get("children", []):
            lines.extend(walk(child, depth + 1))
        return lines

    header.extend(walk(result["layout"], 0))
    if result["warnings"]:
        header.extend(["", "Warnings:", *(f"- {warning}" for warning in result["warnings"])])
    return "\n".join(header) + "\n"
