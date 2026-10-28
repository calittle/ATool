"""Document-linked layout inspection, with scoped iteration field mapping."""
from __future__ import annotations

from .diagnostics import ConditionDiagnostics
from .paths import PathNormalizer


def layout_nodes(document: dict, data: object, mapped: bool, fields: list[dict], clauses: list[dict]) -> list[dict]:
    evaluator = ConditionDiagnostics(fields)
    normalizer = PathNormalizer()

    def relative(path: str, parent_path: str) -> str:
        path = normalizer._normalize_true_path(path)
        if parent_path and path == parent_path:
            return "$"
        if parent_path and path.startswith(parent_path):
            remainder = path[len(parent_path):]
            if remainder.startswith((".", "[")):
                return "$" + remainder
        return path

    def build(kind, source, key, contexts, parent_path=""):
        node = {"kind": kind, "source": source, "key": key, "state": None, "rows": [], "children": [], "details": []}
        condition = str(source.get("Condition", ""))
        active = []
        for row, context, allowed in contexts:
            passed = allowed and evaluator._evaluate_document_condition(condition, context)
            active.append((row, context, passed))
            if mapped and condition:
                detail = evaluator.explain(condition, context, clauses)
                detail["label"] = f"Row {row}: {detail['label']}" if parent_path else detail["label"]
                node["details"].append(detail)
        path = str(source.get("Path", "")).strip()
        child_contexts, child_path = active, parent_path
        if kind == "Iteration":
            child_contexts = []
            child_path = normalizer._normalize_true_path(path) if path else ""
            for row, context, passed in active:
                values = evaluator._extract_values_by_path(context, relative(path, parent_path)) if path and passed and mapped else []
                items = [item for value in values for item in (value if isinstance(value, list) else [value])]
                for index, value in enumerate(items, 1):
                    number = f"{row}.{index}" if parent_path else str(index)
                    child_contexts.append((number, value, True))
                    node["rows"].append({"row": number, "values": [value], "passed": True})
            node["state"] = bool(child_contexts) if mapped else None
            node["reason"] = f"{len(child_contexts)} iterator rows" if child_contexts else "No iterator rows or parent suppressed"
        elif kind == "Field":
            for row, context, passed in active:
                values = evaluator._extract_values_by_path(context, relative(path, parent_path)) if path and passed and mapped else []
                node["rows"].append({"row": row, "values": values, "passed": passed and bool(values)})
            mapped_rows = sum(row["passed"] for row in node["rows"])
            node["state"] = bool(mapped_rows) if mapped else None
            node["reason"] = ("Mapped in every row" if mapped_rows == len(node["rows"]) else
                              f"Mapped in {mapped_rows} of {len(node['rows'])} rows") if node["state"] else "No mapped values, or condition/parent suppressed"
        else:
            node["state"] = any(passed for _, _, passed in active) if mapped else None
            node["reason"] = "Triggered" if node["state"] else "Condition or parent not triggered"
        iteration = source.get("Iteration", source.get("iteration"))
        iteration_node = None
        if isinstance(iteration, dict):
            iteration_node = build("Iteration", iteration, f"{key}/Iteration", active, parent_path)
            if kind in {"Layout", "Content"} and iteration.get("Type") == "Spliterator":
                child_contexts = [(row["row"], row["values"][0], True) for row in iteration_node["rows"]]
                child_path = normalizer._normalize_true_path(str(iteration.get("Path", "")))
        groups = (("Layouts", "Layout"), ("Contents", "Content"), ("Content", "Content"),
                  ("contents", "Content"), ("content", "Content"), ("Fields", "Field"), ("fields", "Field"))
        seen = set()
        for property_name, child_kind in groups:
            children = source.get(property_name)
            if not isinstance(children, list) or child_kind in seen:
                continue
            seen.add(child_kind)
            for index, child in enumerate(children):
                if isinstance(child, dict):
                    node["children"].append(build(child_kind, child, f"{key}/{property_name}/{index}", child_contexts, child_path))
        if iteration_node is not None:
            node["children"].append(iteration_node)
        # Repeated layouts and content need at least one active iteration row.
        if kind in {"Layout", "Content"} and isinstance(iteration, dict) and mapped:
            node["state"] = bool(node["state"]) and bool(node["children"][-1]["state"])
            node["reason"] = "Triggered with iterator rows" if node["state"] else "No iterator rows or condition/parent suppressed"
        return node

    layouts = document.get("source", {}).get("Layouts", [])
    if not isinstance(layouts, list):
        return []
    return [build("Layout", source, f"layout/{index}", [("1", data, bool(document.get("triggered")))])
            for index, source in enumerate(layouts) if isinstance(source, dict)]
