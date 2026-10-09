"""Path-preserving browser queries and validation from the original ATool app."""
from __future__ import annotations
import json
import re
from atool_core.condition_evaluator import ConditionEvaluator
from .paths import PathNormalizer


class DataQueries(ConditionEvaluator, PathNormalizer):
    @staticmethod
    def _data_browser_child_path(parent_path: str, key: str) -> str:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            return f"{parent_path}.{key}"
        return f"{parent_path}[{json.dumps(key, ensure_ascii=False)}]"

    def _find_data_browser_text_matches(self, payload: object, query: str) -> list[tuple[str, object]]:
        needle = query.casefold()
        matches: list[tuple[str, object]] = []

        def visit(value: object, path: str) -> None:
            if len(matches) >= 1000:
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    child_path = self._data_browser_child_path(path, str(key))
                    if needle in str(key).casefold():
                        matches.append((child_path, child))
                    visit(child, child_path)
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if needle in str(value).casefold():
                matches.append((path, value))

        visit(payload, "$")
        return matches

    def _validate_field_path(self, path: str) -> tuple[bool, str]:
        candidate = path.strip()
        if not candidate:
            return False, "Path is empty."
        if not candidate.startswith("$"):
            return False, "Path must start with '$'."
        parse_candidate = self._normalize_path_expression(candidate)
        if not self._is_balanced_parenthesized(parse_candidate):
            return False, "Unbalanced brackets/parentheses/quotes."

        true_path = self._normalize_true_path(parse_candidate).strip()
        if not true_path or not true_path.startswith("$"):
            return False, "Could not derive a valid JSONPath from the expression."
        if not self._is_supported_jsonpath_segments(true_path):
            return False, f"Unsupported JSONPath syntax in resolved path: {true_path}"
        return True, ""

    def _is_supported_jsonpath_segments(self, path: str) -> bool:
        expression = path.strip()
        if expression == "$":
            return True
        if expression.startswith("$.."):
            tail = expression[3:].strip()
            if not tail:
                return False
            expression = "$." + tail
        segments = self._path_to_segments(expression)
        if not segments or segments[0] != "$":
            return False
        for segment in segments[1:]:
            if not self._is_supported_jsonpath_segment(str(segment)):
                return False
        return True

    def _is_supported_jsonpath_segment(self, segment: str) -> bool:
        text = segment.strip()
        if not text:
            return False
        base, brackets = self._split_path_segment(text)
        if "[" in text and not brackets:
            return False
        if base and base != "*" and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", base):
            return False
        if not base and not brackets:
            return False
        for bracket in brackets:
            content = bracket[1:-1].strip()
            if not content:
                return False
            if content == "*":
                continue
            if content.startswith("?(") and content.endswith(")"):
                continue
            if (content.startswith("'") and content.endswith("'")) or (
                content.startswith('"') and content.endswith('"')
            ):
                continue
            try:
                int(content)
                continue
            except ValueError:
                return False
        return True

    def _extract_values_and_paths_by_path(self, payload: object, path: str) -> list[tuple[str, object]]:
        """Resolve a JSONPath and retain the concrete data path for each result."""
        normalized_path = path.strip()
        if not normalized_path:
            return []

        nodes: list[tuple[str, object]] = [("$", payload)]
        if normalized_path.startswith("$.."):
            expression = normalized_path[3:].strip(".")
            first_segment, tail = self._split_first_path_segment(expression)
            base_name, brackets = self._split_path_segment(first_segment.strip())
            if not base_name:
                return []
            nodes = self._deep_find_values_with_paths(payload, "$", base_name)
            nodes = self._apply_path_segment_brackets(nodes, brackets)
            segments = self._path_to_segments("$." + tail)[1:] if tail else []
        else:
            segments = self._path_to_segments(normalized_path)[1:]

        for segment in segments:
            nodes = self._resolve_path_segment_with_paths(nodes, segment)
            if not nodes:
                break
        return nodes

    def _deep_find_values_with_paths(self, node: object, path: str, key: str) -> list[tuple[str, object]]:
        matches: list[tuple[str, object]] = []
        if isinstance(node, dict):
            if key in node:
                matches.append((self._data_browser_child_path(path, key), node[key]))
            for child_key, child in node.items():
                matches.extend(self._deep_find_values_with_paths(child, self._data_browser_child_path(path, child_key), key))
        elif isinstance(node, list):
            for index, child in enumerate(node):
                matches.extend(self._deep_find_values_with_paths(child, f"{path}[{index}]", key))
        return matches

    def _resolve_path_segment_with_paths(
        self, nodes: list[tuple[str, object]], segment: str
    ) -> list[tuple[str, object]]:
        base_name, brackets = self._split_path_segment(segment)
        resolved: list[tuple[str, object]] = []
        if base_name == "length()":
            for path, value in nodes:
                if isinstance(value, (str, list)):
                    resolved.append((f"{path}.length()", len(value)))
        elif base_name and base_name != "*":
            for path, value in nodes:
                if isinstance(value, dict) and base_name in value:
                    resolved.append((self._data_browser_child_path(path, base_name), value[base_name]))
        elif base_name == "*":
            for path, value in nodes:
                if isinstance(value, dict):
                    resolved.extend((self._data_browser_child_path(path, key), child) for key, child in value.items())
                elif isinstance(value, list):
                    resolved.extend((f"{path}[{index}]", child) for index, child in enumerate(value))
        else:
            resolved = nodes
        return self._apply_path_segment_brackets(resolved, brackets)

    def _apply_path_segment_brackets(
        self, nodes: list[tuple[str, object]], brackets: list[str]
    ) -> list[tuple[str, object]]:
        for bracket in brackets:
            content = bracket[1:-1].strip()
            next_nodes: list[tuple[str, object]] = []
            if content == "*":
                for path, value in nodes:
                    if isinstance(value, dict):
                        next_nodes.extend((self._data_browser_child_path(path, key), child) for key, child in value.items())
                    elif isinstance(value, list):
                        next_nodes.extend((f"{path}[{index}]", child) for index, child in enumerate(value))
            elif (content.startswith("'") and content.endswith("'")) or (
                content.startswith('"') and content.endswith('"')
            ):
                key_name = content[1:-1]
                for path, value in nodes:
                    if isinstance(value, dict) and key_name in value:
                        next_nodes.append((self._data_browser_child_path(path, key_name), value[key_name]))
            elif content.startswith("?(") and content.endswith(")"):
                filter_expression = content[2:-1].strip()
                for path, value in nodes:
                    candidates = (
                        [(f"{path}[{index}]", child) for index, child in enumerate(value)]
                        if isinstance(value, list)
                        else [(path, value)] if isinstance(value, dict) else []
                    )
                    next_nodes.extend(
                        (candidate_path, candidate)
                        for candidate_path, candidate in candidates
                        if self._evaluate_condition_expression(filter_expression, candidate)
                    )
            else:
                try:
                    index_value = int(content)
                except ValueError:
                    return []
                for path, value in nodes:
                    if isinstance(value, list) and -len(value) <= index_value < len(value):
                        actual_index = index_value if index_value >= 0 else len(value) + index_value
                        next_nodes.append((f"{path}[{actual_index}]", value[index_value]))
            nodes = next_nodes
            if not nodes:
                break
        return nodes

    def _layout_field_browser_path(self, field_path: str, iteration_path: str) -> str:
        """Expand an iteration-relative field path for a document-wide search."""
        field_path = self._field_path_for_data_browser(field_path)
        iteration_path = self._field_path_for_data_browser(iteration_path)
        if not iteration_path or iteration_path == "$":
            return field_path
        if field_path == iteration_path or (
            field_path.startswith(iteration_path)
            and field_path[len(iteration_path) :].startswith((".", "["))
        ):
            return field_path
        if field_path == "$":
            return iteration_path
        if field_path.startswith("$.") or field_path.startswith("$["):
            return iteration_path + field_path[1:]
        return field_path

    def _field_path_for_data_browser(self, field_path: str) -> str:
        """Return the JSONPath to search from a field's authored Path value."""
        candidate = self._normalize_path_expression(field_path)
        concat_args = self._unwrap_named_call(candidate[2:], "concat") if candidate.startswith("$.") else None
        if concat_args is None:
            concat_args = self._unwrap_named_call(candidate, "concat")
        if concat_args is not None:
            paths: list[str] = []
            for arg in self._split_top_level(concat_args):
                arg = arg.strip()
                if len(arg) >= 2 and arg[0] in {"'", '"'} and arg[-1] == arg[0]:
                    arg = arg[1:-1]
                normalized = self._normalize_true_path(arg)
                if normalized.startswith("$"):
                    paths.append(normalized)
            if paths:
                return max(paths, key=len)
        return self._normalize_true_path(candidate)
