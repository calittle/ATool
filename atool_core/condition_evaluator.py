"""UI-free condition evaluation extracted mechanically from AToolApp."""
from __future__ import annotations

import re


class ConditionEvaluator:
    def __init__(self, fields: list[dict[str, object]] | None = None) -> None:
        self._loaded_fields = fields or []

    def _evaluate_document_condition(
            self,
            condition: str,
            data_payload: object,
            *,
            comms_compatible: bool = True,
            warnings: list[str] | None = None,
        ) -> bool:
            text = self._extract_condition_body(condition)
            if not text:
                return True
            return self._evaluate_condition_expression(
                text,
                data_payload,
                comms_compatible=comms_compatible,
                warnings=warnings,
            )

    def _evaluate_condition_expression(
            self,
            expression: str,
            data_payload: object,
            *,
            comms_compatible: bool = True,
            warnings: list[str] | None = None,
        ) -> bool:
            expr = self._strip_outer_parens(expression)
            if not expr:
                return True

            or_parts = self._split_top_level_operator(expr, "||")
            if len(or_parts) > 1:
                return any(
                    self._evaluate_condition_expression(
                        part,
                        data_payload,
                        comms_compatible=comms_compatible,
                        warnings=warnings,
                    )
                    for part in or_parts
                )

            and_parts = self._split_top_level_operator(expr, "&&")
            if len(and_parts) > 1:
                return all(
                    self._evaluate_condition_expression(
                        part,
                        data_payload,
                        comms_compatible=comms_compatible,
                        warnings=warnings,
                    )
                    for part in and_parts
                )

            negated_expr = self._unwrap_condition_negation(expr)
            if negated_expr is not None:
                return not self._evaluate_condition_expression(
                    negated_expr,
                    data_payload,
                    comms_compatible=comms_compatible,
                    warnings=warnings,
                )

            return self._evaluate_atomic_condition(
                expr,
                data_payload,
                comms_compatible=comms_compatible,
                warnings=warnings,
            )

    def _evaluate_atomic_condition(
            self,
            expression: str,
            data_payload: object,
            *,
            comms_compatible: bool = True,
            warnings: list[str] | None = None,
        ) -> bool:
            expr = self._strip_outer_parens(expression)
            if not expr:
                return True

            negated_expr = self._unwrap_condition_negation(expr)
            if negated_expr is not None:
                return not self._evaluate_condition_expression(
                    negated_expr,
                    data_payload,
                    comms_compatible=comms_compatible,
                    warnings=warnings,
                )

            empty_match = re.match(r"^(.*?)\s+empty\s+(true|false)\s*$", expr, flags=re.IGNORECASE)
            if empty_match:
                path = empty_match.group(1).strip()
                expect_empty = empty_match.group(2).lower() == "true"
                parse_issue = self._condition_path_comms_filter_literal_parse_issue(path)
                if parse_issue and warnings is not None:
                    self._append_condition_warning(warnings, parse_issue)
                return self._evaluate_empty_check(
                    data_payload,
                    path,
                    expect_empty,
                    comms_compatible=comms_compatible,
                    warnings=warnings,
                )

            size_match = self._find_top_level_word_operator(expr, "size")
            if size_match is not None:
                path, expected_size = size_match
                values = self._evaluate_condition_operand(data_payload, path)
                expected_values = self._evaluate_condition_operand(data_payload, expected_size)
                if not expected_values:
                    return False
                return self._compare_condition_operand_values([len(values)], "==", expected_values)

            comparison = self._find_top_level_comparison(expr)
            if comparison is not None:
                lhs, operator, rhs = comparison
                left_values = self._evaluate_condition_operand(data_payload, lhs)
                right_values = self._evaluate_condition_operand(data_payload, rhs)
                if warnings is not None:
                    if not left_values:
                        self._append_condition_template_field_reference_warning(warnings, lhs)
                    if not right_values:
                        self._append_condition_template_field_reference_warning(warnings, rhs)
                if operator in {"==", "!="}:
                    missing_result = self._compare_missing_condition_operand_values(
                        left_values,
                        operator,
                        right_values,
                        comms_compatible=comms_compatible,
                    )
                    if missing_result is not None:
                        return bool(missing_result[0])
                if not left_values or not right_values:
                    return False
                return self._compare_condition_operand_values(left_values, operator, right_values)

            values = self._evaluate_condition_operand(data_payload, expr)
            return len(values) > 0

    @classmethod
    def _condition_path_comms_filter_literal_parse_issue(cls, path_expression: str) -> str:
            path = str(path_expression or "")
            if "[?(" not in path:
                return ""
            for filter_body in cls._iter_condition_filter_bodies(path):
                match = re.search(r"'\(([A-Za-z_$][\w$]*)\)'", filter_body)
                if match:
                    literal = match.group(0)
                    return (
                        f"Comms JSONPath may parse {literal} as a function call inside a single-quoted filter literal; "
                        "use double quotes for that literal."
                    )
            return ""

    @staticmethod
    def _iter_condition_filter_bodies(path_expression: str):
        text = str(path_expression or "")
        index = 0
        while True:
            start = text.find("[?(", index)
            if start < 0:
                return
            body_start = start + 3
            depth = 1
            quote = ""
            escaped = False
            pos = body_start
            while pos < len(text):
                char = text[pos]
                if quote:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = ""
                else:
                    if char in {"'", '"'}:
                        quote = char
                    elif char == "(":
                        depth += 1
                    elif char == ")":
                        depth -= 1
                        if depth == 0:
                            yield text[body_start:pos]
                            index = pos + 1
                            break
                pos += 1
            else:
                return

    def _evaluate_empty_check(
            self,
            data_payload: object,
            path_expression: str,
            expect_empty: bool,
            *,
            comms_compatible: bool = True,
            warnings: list[str] | None = None,
        ) -> bool:
            normalized_full_path = self._normalize_condition_path(path_expression)
            parent_path = self._get_empty_check_parent_path(normalized_full_path)
            parent_values = self._extract_values_by_path(data_payload, parent_path)
            if len(parent_values) == 0:
                if comms_compatible and expect_empty and self._path_has_filter(normalized_full_path):
                    return False
                return expect_empty

            full_values = self._extract_values_by_path(data_payload, normalized_full_path)
            is_empty = len(full_values) == 0
            if comms_compatible and expect_empty and is_empty and not self._path_has_filter(normalized_full_path):
                return False
            return is_empty if expect_empty else not is_empty

    @staticmethod
    def _path_has_filter(path_expression: str) -> bool:
            return "[?(" in path_expression

    @staticmethod
    def _append_condition_warning(warnings: list[str], warning: str) -> None:
            if warning not in warnings:
                warnings.append(warning)

    @staticmethod
    def _get_empty_check_parent_path(path_expression: str) -> str:
            normalized = path_expression.strip()
            filter_index = normalized.find("[?(")
            if filter_index >= 0:
                return normalized[:filter_index].strip()
            dot_index = normalized.rfind(".")
            if dot_index > 0:
                return normalized[:dot_index].strip()
            return normalized

    def _evaluate_condition_operand(self, data_payload: object, expression: str) -> list[object]:
            literal_value, is_literal = self._parse_condition_literal(expression)
            if is_literal:
                return [literal_value]
            path = self._normalize_condition_path(expression)
            return self._extract_values_by_path(data_payload, path)

    def _append_condition_template_field_reference_warning(
            self,
            warnings: list[str],
            expression: str,
        ) -> None:
            note = self._condition_template_field_reference_note(expression)
            if note:
                self._append_condition_warning(warnings, note)

    def _condition_template_field_reference_note(self, expression: str) -> str:
            field = self._condition_template_field_for_operand(expression)
            if field is None:
                return ""
            field_name = str(field.get("name", "")).strip()
            field_path = str(field.get("path", "")).strip()
            if field_path:
                return (
                    f"Condition operand {expression.strip()} matches ATool field '{field_name}', "
                    "but Comms conditions evaluate against the input JSON and do not resolve ATool field names. "
                    f"Use the field's JSON path instead: {field_path}"
                )
            return (
                f"Condition operand {expression.strip()} matches ATool field '{field_name}', "
                "but Comms conditions evaluate against the input JSON and do not resolve ATool field names."
            )

    def _condition_template_field_for_operand(self, expression: str) -> dict[str, object] | None:
            path = self._normalize_condition_path(expression)
            match = re.match(r"^\$\.([A-Za-z_][A-Za-z0-9_]*)$", path)
            if not match:
                return None
            field_name = match.group(1).casefold()
            for field in self._loaded_fields:
                if str(field.get("name", "")).casefold() == field_name:
                    return field
            return None

    def _compare_condition_operand_values(
            self, left_values: list[object], operator: str, right_values: list[object]
        ) -> bool:
            if operator in {"==", "!="}:
                sequence_result = self._compare_condition_operand_sequences(left_values, operator, right_values)
                if sequence_result is not None:
                    return sequence_result

            if operator == "!=":
                for left in left_values:
                    for right in right_values:
                        if self._compare_single_condition_value(left, "==", right):
                            return False
                return True

            for left in left_values:
                for right in right_values:
                    if self._compare_single_condition_value(left, operator, right):
                        return True
            return False

    @staticmethod
    def _compare_condition_operand_sequences(
            left_values: list[object],
            operator: str,
            right_values: list[object],
        ) -> bool | None:
            if len(left_values) <= 1 and len(right_values) <= 1:
                return None

            if len(left_values) == 1 and len(right_values) == 1:
                return None

            if len(left_values) == 0 or len(right_values) == 0:
                return None

            left = AToolApp._coerce_condition_sequence_value(left_values)
            right = AToolApp._coerce_condition_sequence_value(right_values)
            matched = AToolApp._compare_single_condition_value(left, "==", right)
            return not matched if operator == "!=" else matched

    @staticmethod
    def _coerce_condition_sequence_value(values: list[object]) -> object:
            if len(values) == 1:
                return values[0]
            return ",".join(AToolApp._stringify_condition_sequence_item(value) for value in values)

    @staticmethod
    def _stringify_condition_sequence_item(value: object) -> str:
            if value is None:
                return ""
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

    def _compare_missing_condition_operand_values(
            self,
            left_values: list[object],
            operator: str,
            right_values: list[object],
            *,
            comms_compatible: bool,
        ) -> tuple[bool, str, list[object]] | None:
            if bool(left_values) == bool(right_values):
                return None

            missing_side = "left" if not left_values else "right"
            present_values = right_values if not left_values else left_values

            if operator == "!=" and comms_compatible:
                return True, missing_side, present_values

            if operator == "!=":
                return None

            if operator == "==" and comms_compatible:
                return False, missing_side, present_values

            return None

    @staticmethod
    def _compare_single_condition_value(value: object, operator: str, rhs: object) -> bool:
            if operator in (">", "<", ">=", "<="):
                try:
                    left = float(value)
                    right = float(rhs)
                except (TypeError, ValueError):
                    return False
                if operator == ">":
                    return left > right
                if operator == "<":
                    return left < right
                if operator == ">=":
                    return left >= right
                return left <= right

            if operator == "==":
                return AToolApp._js_like_strict_equals(value, rhs)
            if operator == "!=":
                return not AToolApp._js_like_strict_equals(value, rhs)
            return False

    @staticmethod
    def _js_like_strict_equals(left: object, right: object) -> bool:
            if left is None or right is None:
                return left is right
            left_is_bool = isinstance(left, bool)
            right_is_bool = isinstance(right, bool)
            if left_is_bool or right_is_bool:
                return left_is_bool and right_is_bool and (left is right)

            number_types = (int, float)
            if isinstance(left, number_types) and isinstance(right, number_types):
                return float(left) == float(right)

            if isinstance(left, str) and isinstance(right, str):
                return left == right

            if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
                return left is right

            if type(left) is not type(right):
                return False
            return left == right

    @staticmethod
    def _parse_condition_literal(text: str) -> tuple[object, bool]:
            stripped = text.strip()
            if (stripped.startswith("'") and stripped.endswith("'")) or (
                stripped.startswith('"') and stripped.endswith('"')
            ):
                return stripped[1:-1], True
            lowered = stripped.lower()
            if lowered == "true":
                return True, True
            if lowered == "false":
                return False, True
            if lowered == "null":
                return None, True
            try:
                if re.match(r"^-?\d+(\.\d+)?$", stripped):
                    return float(stripped), True
            except ValueError:
                pass
            return None, False

    @staticmethod
    def _find_top_level_comparison(expression: str) -> tuple[str, str, str] | None:
            text = expression
            operators = ("==", "!=", "<=", ">=", "<", ">")
            paren_depth = 0
            bracket_depth = 0
            quote = ""
            escaped = False
            index = 0
            while index < len(text):
                char = text[index]
                if quote:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = ""
                    index += 1
                    continue

                if char in {"'", '"'}:
                    quote = char
                    index += 1
                    continue
                if char == "(":
                    paren_depth += 1
                    index += 1
                    continue
                if char == ")":
                    paren_depth = max(0, paren_depth - 1)
                    index += 1
                    continue
                if char == "[":
                    bracket_depth += 1
                    index += 1
                    continue
                if char == "]":
                    bracket_depth = max(0, bracket_depth - 1)
                    index += 1
                    continue

                if paren_depth == 0 and bracket_depth == 0:
                    for operator in operators:
                        if text[index : index + len(operator)] == operator:
                            left = text[:index].strip()
                            right = text[index + len(operator) :].strip()
                            return left, operator, right
                index += 1
            return None

    @staticmethod
    def _find_top_level_word_operator(expression: str, operator: str) -> tuple[str, str] | None:
            text = expression
            operator_text = operator.strip()
            if not text or not operator_text:
                return None

            paren_depth = 0
            bracket_depth = 0
            quote = ""
            escaped = False
            index = 0
            while index < len(text):
                char = text[index]
                if quote:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = ""
                    index += 1
                    continue

                if char in {"'", '"'}:
                    quote = char
                    index += 1
                    continue
                if char == "(":
                    paren_depth += 1
                    index += 1
                    continue
                if char == ")":
                    paren_depth = max(0, paren_depth - 1)
                    index += 1
                    continue
                if char == "[":
                    bracket_depth += 1
                    index += 1
                    continue
                if char == "]":
                    bracket_depth = max(0, bracket_depth - 1)
                    index += 1
                    continue

                if paren_depth == 0 and bracket_depth == 0:
                    candidate = text[index : index + len(operator_text)]
                    if candidate.lower() == operator_text.lower():
                        before = text[index - 1] if index > 0 else ""
                        after_index = index + len(operator_text)
                        after = text[after_index] if after_index < len(text) else ""
                        if (not before or before.isspace()) and (not after or after.isspace()):
                            left = text[:index].strip()
                            right = text[after_index:].strip()
                            if left and right:
                                return left, right
                index += 1
            return None

    @staticmethod
    def _split_top_level_operator(expression: str, operator: str) -> list[str]:
            parts: list[str] = []
            current: list[str] = []
            paren_depth = 0
            bracket_depth = 0
            quote = ""
            escaped = False
            index = 0
            while index < len(expression):
                char = expression[index]
                if quote:
                    current.append(char)
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = ""
                    index += 1
                    continue

                if char in {"'", '"'}:
                    quote = char
                    current.append(char)
                    index += 1
                    continue
                if char == "(":
                    paren_depth += 1
                    current.append(char)
                    index += 1
                    continue
                if char == ")":
                    paren_depth -= 1
                    current.append(char)
                    index += 1
                    continue
                if char == "[":
                    bracket_depth += 1
                    current.append(char)
                    index += 1
                    continue
                if char == "]":
                    bracket_depth -= 1
                    current.append(char)
                    index += 1
                    continue

                is_split = (
                    paren_depth == 0
                    and bracket_depth == 0
                    and expression[index : index + len(operator)] == operator
                )
                if is_split:
                    token = "".join(current).strip()
                    if token:
                        parts.append(token)
                    current = []
                    index += len(operator)
                    continue

                current.append(char)
                index += 1

            tail = "".join(current).strip()
            if tail:
                parts.append(tail)
            return parts

    @staticmethod
    def _unwrap_condition_negation(expression: str) -> str | None:
            expr = str(expression or "").strip()
            if not expr.startswith("!") or expr.startswith("!="):
                return None

            operand = expr[1:].strip()
            if not operand:
                return None

            if operand.startswith("("):
                unwrapped = AToolApp._strip_outer_parens(operand)
                return unwrapped if unwrapped != operand else None

            return operand

    @staticmethod
    def _strip_outer_parens(text: str) -> str:
            expression = str(text or "").strip()
            while expression.startswith("(") and expression.endswith(")"):
                depth = 0
                valid = True
                quote = ""
                escaped = False
                for index, char in enumerate(expression):
                    if quote:
                        if escaped:
                            escaped = False
                        elif char == "\\":
                            escaped = True
                        elif char == quote:
                            quote = ""
                        continue
                    if char in {"'", '"'}:
                        quote = char
                        continue
                    if char == "(":
                        depth += 1
                    elif char == ")":
                        depth -= 1
                    if depth == 0 and index < len(expression) - 1:
                        valid = False
                        break
                    if depth < 0:
                        valid = False
                        break
                if not valid:
                    break
                expression = expression[1:-1].strip()
            return expression

    @staticmethod
    def _extract_condition_body(condition: str) -> str:
            raw = str(condition or "").strip()
            match = re.match(r"^\$\s*\[\s*\?\s*\((.*)\)\s*\]\s*$", raw, flags=re.DOTALL)
            return match.group(1).strip() if match else raw

    def _normalize_condition_path(self, path: str) -> str:
            normalized = self._strip_outer_parens(path)
            if normalized.startswith("@"):
                normalized = "$" + normalized[1:]
            return normalized

    def _extract_values_by_path(self, payload: object, path: str) -> list[object]:
            normalized_path = path.strip()
            if not normalized_path:
                return []

            if normalized_path.startswith("$.."):
                return self._extract_values_by_deep_path(payload, normalized_path[3:])

            segments = self._path_to_segments(normalized_path)
            if not segments:
                return []
            nodes: list[object] = [payload]
            for segment in segments[1:]:
                next_nodes: list[object] = []
                for node in nodes:
                    next_nodes.extend(self._resolve_path_segment(node, segment))
                nodes = next_nodes
                if not nodes:
                    break
            return nodes

    def _extract_values_by_deep_path(self, payload: object, deep_expression: str) -> list[object]:
            expression = deep_expression.strip(".")
            if not expression:
                return []
            first_segment, tail = self._split_first_path_segment(expression)
            first_segment = first_segment.strip()
            if not first_segment:
                return []

            base_name, brackets = self._split_path_segment(first_segment)
            base_name = base_name.strip()
            if not base_name:
                return []
            base_values = self._deep_find_values(payload, base_name)
            resolved_first_segment = self._apply_segment_brackets(base_values, brackets)
            if not tail:
                return resolved_first_segment
            results: list[object] = []
            for value in resolved_first_segment:
                results.extend(self._extract_values_by_path(value, "$." + tail))
            return results

    def _deep_find_values(self, node: object, key: str) -> list[object]:
            matches: list[object] = []
            if isinstance(node, dict):
                if key in node:
                    matches.append(node[key])
                for value in node.values():
                    matches.extend(self._deep_find_values(value, key))
                return matches
            if isinstance(node, list):
                for item in node:
                    matches.extend(self._deep_find_values(item, key))
            return matches

    def _resolve_path_segment(self, node: object, segment: str) -> list[object]:
            base_name, brackets = self._split_path_segment(segment)
            current_nodes: list[object] = [node]

            if base_name == "length()":
                next_nodes: list[object] = []
                for current in current_nodes:
                    if isinstance(current, (str, list)):
                        next_nodes.append(len(current))
                current_nodes = next_nodes
            elif base_name and base_name != "*":
                next_nodes: list[object] = []
                for current in current_nodes:
                    if isinstance(current, dict) and base_name in current:
                        next_nodes.append(current[base_name])
                current_nodes = next_nodes
            elif base_name == "*":
                wildcard_nodes: list[object] = []
                for current in current_nodes:
                    if isinstance(current, dict):
                        wildcard_nodes.extend(current.values())
                    elif isinstance(current, list):
                        wildcard_nodes.extend(current)
                current_nodes = wildcard_nodes

            return self._apply_segment_brackets(current_nodes, brackets)

    def _apply_segment_brackets(self, current_nodes: list[object], brackets: list[str]) -> list[object]:
            nodes = list(current_nodes)
            for bracket in brackets:
                content = bracket[1:-1].strip()
                next_nodes: list[object] = []
                if content == "*":
                    for current in nodes:
                        if isinstance(current, list):
                            next_nodes.extend(current)
                        elif isinstance(current, dict):
                            next_nodes.extend(current.values())
                elif (content.startswith("'") and content.endswith("'")) or (
                    content.startswith('"') and content.endswith('"')
                ):
                    key_name = content[1:-1]
                    for current in nodes:
                        if isinstance(current, dict) and key_name in current:
                            next_nodes.append(current[key_name])
                elif content.startswith("?(") and content.endswith(")"):
                    filter_expression = content[2:-1].strip()
                    for current in nodes:
                        candidates: list[object] = []
                        if isinstance(current, list):
                            candidates = list(current)
                        elif isinstance(current, dict):
                            candidates = [current]
                        for candidate in candidates:
                            if self._evaluate_condition_expression(filter_expression, candidate):
                                next_nodes.append(candidate)
                else:
                    try:
                        index_value = int(content)
                    except ValueError:
                        # Unsupported index/filter syntax; abort this branch.
                        return []
                    for current in nodes:
                        if isinstance(current, list):
                            if -len(current) <= index_value < len(current):
                                next_nodes.append(current[index_value])
                nodes = next_nodes
                if not nodes:
                    break
            return nodes

    @staticmethod
    def _split_path_segment(segment: str) -> tuple[str, list[str]]:
            if "[" not in segment:
                return segment, []
            first_bracket = segment.find("[")
            base = segment[:first_bracket]
            bracket_part = segment[first_bracket:]
            brackets = re.findall(r"\[[^\]]*\]", bracket_part)
            return base, brackets

    @staticmethod
    def _split_first_path_segment(path_expression: str) -> tuple[str, str]:
            text = str(path_expression or "").strip()
            if not text:
                return "", ""
            bracket_depth = 0
            paren_depth = 0
            quote = ""
            escaped = False
            for index, char in enumerate(text):
                if quote:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = ""
                    continue
                if char in {"'", '"'}:
                    quote = char
                    continue
                if char == "[":
                    bracket_depth += 1
                    continue
                if char == "]":
                    bracket_depth = max(0, bracket_depth - 1)
                    continue
                if char == "(":
                    paren_depth += 1
                    continue
                if char == ")":
                    paren_depth = max(0, paren_depth - 1)
                    continue
                if char == "." and bracket_depth == 0 and paren_depth == 0:
                    first = text[:index].strip()
                    tail = text[index + 1 :].strip()
                    return first, tail
            return text, ""

    @staticmethod
    def _path_to_segments(path: str) -> list[str]:
            cleaned = path.strip()
            if not cleaned:
                return ["(no path)"]

            segments = ["$"]
            if cleaned == "$":
                return segments

            remaining = cleaned[1:] if cleaned.startswith("$") else cleaned
            remaining = remaining.lstrip(".")
            if not remaining:
                return segments

            current: list[str] = []
            bracket_depth = 0
            paren_depth = 0
            quote_char = ""
            escaped = False
            for character in remaining:
                if quote_char:
                    current.append(character)
                    if escaped:
                        escaped = False
                        continue
                    if character == "\\":
                        escaped = True
                        continue
                    if character == quote_char:
                        quote_char = ""
                    continue

                if character in {"'", '"'}:
                    quote_char = character
                    current.append(character)
                    continue
                if character == "[":
                    bracket_depth += 1
                    current.append(character)
                    continue
                if character == "]":
                    if bracket_depth > 0:
                        bracket_depth -= 1
                    current.append(character)
                    continue
                if character == "(":
                    paren_depth += 1
                    current.append(character)
                    continue
                if character == ")":
                    if paren_depth > 0:
                        paren_depth -= 1
                    current.append(character)
                    continue
                if character == "." and bracket_depth == 0 and paren_depth == 0:
                    token = "".join(current).strip()
                    if token:
                        segments.append(token)
                    current = []
                    continue
                current.append(character)

            tail = "".join(current).strip()
            if tail:
                segments.append(tail)
            return segments


# Preserve references retained from the source methods.
AToolApp = ConditionEvaluator
