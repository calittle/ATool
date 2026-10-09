"""Sample input synthesis from the original application, without UI dependencies."""
from __future__ import annotations
import copy
import re
from .diagnostics import ConditionDiagnostics
from .paths import PathNormalizer

class SampleBuilder(ConditionDiagnostics, PathNormalizer):

    def _generate_sample_input_payload(
        self,
        condition_text: str,
        field_specs: list[dict[str, str]],
    ) -> tuple[dict[str, object], list[str]]:
        payload: dict[str, object] = {}
        report: list[str] = []

        for spec in field_specs:
            field_path = str(spec.get("path", "")).strip()
            if not field_path:
                continue
            true_path = self._normalize_true_path(field_path)
            seed_value = self._infer_mock_value_for_field(
                path=true_path,
                field_name=str(spec.get("name", "")),
                field_descr=str(spec.get("descr", "")),
            )
            self._set_generated_value_for_path(payload, true_path, seed_value)

        condition_body = self._extract_condition_body(condition_text)
        if condition_body:
            self._satisfy_condition_expression(condition_body, payload, report)

        missing_fields: list[str] = []
        for spec in field_specs:
            field_path = str(spec.get("path", "")).strip()
            if not field_path:
                continue
            true_path = self._normalize_true_path(field_path)
            if self._extract_values_by_path(payload, true_path):
                continue
            seed_value = self._infer_mock_value_for_field(
                path=true_path,
                field_name=str(spec.get("name", "")),
                field_descr=str(spec.get("descr", "")),
            )
            self._set_generated_value_for_path(payload, true_path, seed_value)
            if not self._extract_values_by_path(payload, true_path):
                missing_fields.append(field_path)

        if missing_fields:
            report.append("Some field paths could not be materialized:")
            report.extend(f"- {path}" for path in missing_fields[:25])
            if len(missing_fields) > 25:
                report.append(f"- ... and {len(missing_fields) - 25} more")

        condition_ok = self._evaluate_document_condition(condition_text, payload)
        if condition_ok:
            report.append("Document condition: satisfied.")
        else:
            report.append("Document condition: not satisfied after synthesis.")
            atomic = self._collect_atomic_condition_clauses(condition_body) if condition_body else []
            for clause in atomic:
                passed, details = self._evaluate_atomic_condition_with_detail(clause, payload)
                if passed:
                    continue
                report.append(f"- {clause} -> {details}")

        return payload, report

    def _satisfy_condition_expression(self, expression: str, payload: object, report: list[str]) -> bool:
        expr = self._strip_outer_parens(expression)
        if not expr:
            return True

        or_parts = self._split_top_level_operator(expr, "||")
        if len(or_parts) > 1:
            for part in or_parts:
                candidate = copy.deepcopy(payload)
                local_report: list[str] = []
                if self._satisfy_condition_expression(part, candidate, local_report):
                    if isinstance(payload, dict) and isinstance(candidate, dict):
                        payload.clear()
                        payload.update(candidate)
                    report.extend(local_report)
                    return True
            report.append(f"Could not satisfy OR expression: {expr}")
            return False

        and_parts = self._split_top_level_operator(expr, "&&")
        if len(and_parts) > 1:
            overall = True
            for part in and_parts:
                if not self._satisfy_condition_expression(part, payload, report):
                    overall = False
            return overall

        return self._apply_atomic_generation_constraint(expr, payload, report)

    def _apply_atomic_generation_constraint(self, expression: str, payload: object, report: list[str]) -> bool:
        expr = self._strip_outer_parens(expression)
        if not expr:
            return True

        empty_match = re.match(r"^(.*?)\s+empty\s+(true|false)\s*$", expr, flags=re.IGNORECASE)
        if empty_match:
            path = self._normalize_condition_path(empty_match.group(1).strip())
            expect_empty = empty_match.group(2).lower() == "true"
            if expect_empty:
                parent_path = self._get_empty_check_parent_path(path)
                self._ensure_generated_path_exists(payload, parent_path)
                self._clear_generated_path_value(payload, path)
                return True
            self._set_generated_value_for_path(payload, path, "sample")
            return True

        size_match = self._find_top_level_word_operator(expr, "size")
        if size_match is not None:
            path_text, expected_size_text = size_match
            expected_values = self._evaluate_condition_operand(payload, expected_size_text)
            expected_size = self._first_integral_condition_value(expected_values)
            if expected_size is None:
                report.append(f"Could not determine target size for expression: {expr}")
                return False
            path = self._normalize_condition_path(path_text)
            if expected_size <= 0:
                self._clear_generated_path_value(payload, path)
            else:
                self._ensure_generated_path_exists(payload, path)
            actual_size = len(self._extract_values_by_path(payload, path))
            if actual_size != expected_size:
                report.append(
                    f"Could not materialize expression size: {expr} "
                    f"(expected {expected_size}, found {actual_size})"
                )
                return False
            return True

        comparison = self._find_top_level_comparison(expr)
        if comparison is not None:
            lhs_text, operator, rhs_text = comparison
            lhs_literal, lhs_is_literal = self._parse_condition_literal(lhs_text)
            rhs_literal, rhs_is_literal = self._parse_condition_literal(rhs_text)
            lhs_path = None if lhs_is_literal else self._normalize_condition_path(lhs_text)
            rhs_path = None if rhs_is_literal else self._normalize_condition_path(rhs_text)

            if lhs_path is None and rhs_path is None:
                return self._compare_single_condition_value(lhs_literal, operator, rhs_literal)

            if lhs_path is not None and rhs_path is None:
                lhs_value = self._derive_generation_value(operator, rhs_literal, side="left")
                self._set_generated_value_for_path(payload, lhs_path, lhs_value)
                return True

            if lhs_path is None and rhs_path is not None:
                rhs_value = self._derive_generation_value(operator, lhs_literal, side="right")
                self._set_generated_value_for_path(payload, rhs_path, rhs_value)
                return True

            left_value, right_value = self._derive_generation_pair(operator)
            if lhs_path is not None:
                self._set_generated_value_for_path(payload, lhs_path, left_value)
            if rhs_path is not None:
                self._set_generated_value_for_path(payload, rhs_path, right_value)
            return True

        literal_value, is_literal = self._parse_condition_literal(expr)
        if is_literal:
            return bool(literal_value)

        path = self._normalize_condition_path(expr)
        self._set_generated_value_for_path(payload, path, "sample")
        if not self._extract_values_by_path(payload, path):
            report.append(f"Could not materialize path for expression: {expr}")
            return False
        return True

    @staticmethod
    def _derive_generation_pair(operator: str) -> tuple[object, object]:
        if operator == "==":
            return "sample", "sample"
        if operator == "!=":
            return "sample", "different"
        if operator in {">", ">="}:
            return 2.0, 1.0
        if operator in {"<", "<="}:
            return 1.0, 2.0
        return "sample", "sample"

    def _derive_generation_value(self, operator: str, rhs_value: object, side: str) -> object:
        if operator == "==":
            return rhs_value
        if operator == "!=":
            return self._different_value(rhs_value)

        rhs_number = self._as_float(rhs_value)
        if rhs_number is None:
            return 2.0 if operator in {">", ">="} else 1.0

        if side == "left":
            if operator == ">":
                return rhs_number + 1.0
            if operator == ">=":
                return rhs_number
            if operator == "<":
                return rhs_number - 1.0
            if operator == "<=":
                return rhs_number
        else:
            if operator == ">":
                return rhs_number - 1.0
            if operator == ">=":
                return rhs_number
            if operator == "<":
                return rhs_number + 1.0
            if operator == "<=":
                return rhs_number
        return rhs_value

    @staticmethod
    def _as_float(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _different_value(value: object) -> object:
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return float(value) + 1.0
        if value is None:
            return "sample"
        if isinstance(value, str):
            return value + "_x"
        return "different"

    def _default_generated_value_for_path(self, path: str) -> object:
        lowered = str(path).lower()
        if lowered.endswith(".mandatory") or lowered.endswith(".required"):
            return True
        if lowered.endswith(".count") or lowered.endswith(".amount") or lowered.endswith(".total"):
            return 1.0
        return "sample"

    def _infer_mock_value_for_field(self, path: str, field_name: str, field_descr: str) -> object:
        combined = " ".join([field_name, field_descr, path]).casefold()
        compact = combined.replace("_", " ").replace("-", " ")

        if any(token in compact for token in ("mandatory", "required", "is ", " has ", "flag", "enabled")):
            return True
        if any(token in compact for token in ("date", "due", "issued", "updated", "created", "posted", "period")):
            return "2026-03-13"
        if any(token in compact for token in ("time", "timestamp")):
            return "2026-03-13T09:30:00Z"
        if any(token in compact for token in ("email", "e-mail")):
            return "sample.user@example.com"
        if any(token in compact for token in ("phone", "tel", "mobile", "fax")):
            return "+1-212-555-0188"
        if any(token in compact for token in ("url", "uri", "website", "link")):
            return "https://example.com/sample"
        if any(token in compact for token in ("zip", "postal", "postcode")):
            return "10001"
        if any(token in compact for token in ("country",)):
            return "US"
        if any(token in compact for token in ("state", "province")):
            return "NY"
        if any(token in compact for token in ("city",)):
            return "New York"
        if any(token in compact for token in ("address", "street")):
            return "123 Sample Street"
        if any(token in compact for token in ("currency", "ccy")):
            return "USD"
        if any(token in compact for token in ("percent", "percentage", "rate")):
            return 12.5
        if any(token in compact for token in ("amount", "total", "balance", "price", "cost", "charge", "fee")):
            return 123.45
        if any(token in compact for token in ("count", "qty", "quantity", "number of", "num ")) or compact.endswith(" count"):
            return 2
        if any(token in compact for token in ("id", "identifier", "reference", "ref", "code", "number", "acct", "account")):
            return "REF-10001"
        if any(token in compact for token in ("name", "customer", "person", "contact")):
            return "Sample Name"
        if any(token in compact for token in ("status", "state", "result")):
            return "ACTIVE"
        if any(token in compact for token in ("desc", "description", "note", "remark", "comment")):
            return "Sample description"
        return self._default_generated_value_for_path(path)

    def _ensure_generated_path_exists(self, payload: object, path: str) -> bool:
        refs = self._resolve_generation_leaf_refs(payload, path, create=True)
        return len(refs) > 0

    def _set_generated_value_for_path(self, payload: object, path: str, value: object) -> bool:
        refs = self._resolve_generation_leaf_refs(payload, path, create=True)
        if not refs:
            return False
        for parent, slot in refs:
            self._assign_generation_slot(parent, slot, value)
        return True

    def _clear_generated_path_value(self, payload: object, path: str) -> bool:
        refs = self._resolve_generation_leaf_refs(payload, path, create=False)
        if not refs:
            return False
        for parent, slot in refs:
            if isinstance(parent, dict) and isinstance(slot, str):
                parent.pop(slot, None)
            elif isinstance(parent, list) and isinstance(slot, int) and 0 <= slot < len(parent):
                parent[slot] = None
        return True

    def _resolve_generation_leaf_refs(
        self,
        payload: object,
        path: str,
        create: bool,
    ) -> list[tuple[object, str | int]]:
        normalized = self._normalize_true_path(path)
        if not normalized.startswith("$"):
            return []
        segments = self._path_to_segments(normalized)
        if not segments or segments[0] != "$":
            return []
        if len(segments) == 1:
            return []

        refs: list[tuple[object, object, object]] = [(None, None, payload)]
        for segment in segments[1:]:
            refs = self._advance_generation_refs(refs, str(segment), create)
            if not refs:
                return []
        leaf_refs: list[tuple[object, str | int]] = []
        for parent, slot, _node in refs:
            if parent is None:
                continue
            if isinstance(slot, (str, int)):
                leaf_refs.append((parent, slot))
        return leaf_refs

    def _advance_generation_refs(
        self,
        refs: list[tuple[object, object, object]],
        segment: str,
        create: bool,
    ) -> list[tuple[object, object, object]]:
        base, brackets = self._split_path_segment(segment.strip())
        current_refs = refs

        if base:
            next_refs: list[tuple[object, object, object]] = []
            for parent, slot, node in current_refs:
                if base == "*":
                    wildcard_target = self._select_or_create_wildcard_child(parent, slot, node, create)
                    if wildcard_target is None:
                        continue
                    next_refs.append(wildcard_target)
                    continue
                child_ref = self._select_or_create_named_child(parent, slot, node, base, create)
                if child_ref is not None:
                    next_refs.append(child_ref)
            current_refs = next_refs

        for bracket in brackets:
            content = bracket[1:-1].strip()
            next_refs = []
            for parent, slot, node in current_refs:
                bracket_refs = self._select_or_create_bracket_child(parent, slot, node, content, create)
                next_refs.extend(bracket_refs)
            current_refs = next_refs
            if not current_refs:
                break

        return current_refs

    def _select_or_create_named_child(
        self,
        parent: object,
        slot: object,
        node: object,
        key: str,
        create: bool,
    ) -> tuple[object, object, object] | None:
        current = node
        if not isinstance(current, dict):
            if not create:
                return None
            replacement: dict[str, object] = {}
            if not self._replace_generation_node(parent, slot, replacement):
                return None
            current = replacement
        if key not in current:
            if not create:
                return None
            current[key] = {}
        return (current, key, current[key])

    def _select_or_create_wildcard_child(
        self,
        parent: object,
        slot: object,
        node: object,
        create: bool,
    ) -> tuple[object, object, object] | None:
        current = node
        if isinstance(current, dict):
            if not current:
                if not create:
                    return None
                current["item"] = {}
            first_key = next(iter(current))
            return (current, first_key, current[first_key])

        if not isinstance(current, list):
            if not create:
                return None
            replacement: list[object] = []
            if not self._replace_generation_node(parent, slot, replacement):
                return None
            current = replacement

        if not current:
            if not create:
                return None
            current.append({})
        return (current, 0, current[0])

    def _select_or_create_bracket_child(
        self,
        parent: object,
        slot: object,
        node: object,
        content: str,
        create: bool,
    ) -> list[tuple[object, object, object]]:
        text = content.strip()
        if not text:
            return []
        if text == "*":
            wildcard = self._select_or_create_wildcard_child(parent, slot, node, create)
            return [wildcard] if wildcard is not None else []

        if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
            key = text[1:-1]
            named = self._select_or_create_named_child(parent, slot, node, key, create)
            return [named] if named is not None else []

        if text.startswith("?(") and text.endswith(")"):
            wildcard = self._select_or_create_wildcard_child(parent, slot, node, create)
            if wildcard is None:
                return []
            filter_expression = text[2:-1].strip()
            candidate = wildcard[2]
            self._satisfy_condition_expression(filter_expression, candidate, [])
            return [wildcard]

        try:
            index_value = int(text)
        except ValueError:
            return []

        current = node
        if not isinstance(current, list):
            if not create:
                return []
            replacement: list[object] = []
            if not self._replace_generation_node(parent, slot, replacement):
                return []
            current = replacement

        target_index = index_value if index_value >= 0 else 0
        while len(current) <= target_index:
            if not create:
                return []
            current.append({})
        return [(current, target_index, current[target_index])]

    def _replace_generation_node(self, parent: object, slot: object, value: object) -> bool:
        if parent is None:
            return False
        self._assign_generation_slot(parent, slot, value)
        return True

    @staticmethod
    def _assign_generation_slot(parent: object, slot: object, value: object) -> None:
        if isinstance(parent, dict) and isinstance(slot, str):
            parent[slot] = value
        elif isinstance(parent, list) and isinstance(slot, int):
            while len(parent) <= slot:
                parent.append({})
            parent[slot] = value

    def _collect_atomic_condition_clauses(self, expression: str) -> list[str]:
        expr = self._strip_outer_parens(expression)
        if not expr:
            return []
        or_parts = self._split_top_level_operator(expr, "||")
        if len(or_parts) > 1:
            clauses: list[str] = []
            for part in or_parts:
                clauses.extend(self._collect_atomic_condition_clauses(part))
            return clauses
        and_parts = self._split_top_level_operator(expr, "&&")
        if len(and_parts) > 1:
            clauses = []
            for part in and_parts:
                clauses.extend(self._collect_atomic_condition_clauses(part))
            return clauses
        return [expr]

    @staticmethod
    def _first_integral_condition_value(values: list[object]) -> int | None:
        if not values:
            return None
        value = values[0]
        if isinstance(value, bool):
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not numeric_value.is_integer():
            return None
        return int(numeric_value)
