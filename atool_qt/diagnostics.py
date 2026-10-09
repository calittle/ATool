"""Read-only diagnostics, using pure clause/value helpers copied from AToolApp."""
from __future__ import annotations
import json
import re
from atool_core.condition_evaluator import ConditionEvaluator


class ConditionDiagnostics(ConditionEvaluator):
    def explain(self, condition: str, data: object, entries: list[dict] | None = None) -> dict:
        """Evaluate every branch, including branches skipped by AND/OR short circuiting."""
        def logic_key(expression):
            body = self._strip_outer_parens(self._extract_condition_body(expression)).strip()
            for operator, symbol in (("OR", "||"), ("AND", "&&")):
                parts = self._split_top_level_operator(body, symbol)
                if len(parts) > 1:
                    return (operator, tuple(logic_key(part) for part in parts))
            inner = self._unwrap_condition_negation(body)
            if inner is not None:
                return ("NOT", logic_key(inner))
            return ("ATOM", self._canonical_condition_expression(body))

        lookup = {}
        for entry in entries or []:
            try:
                expression = self._resolve_clause_expression_by_name_from_entries(entries, entry["name"])
                lookup.setdefault(logic_key(expression), entry["name"])
            except ValueError:
                continue

        def visit(expression):
            body = self._strip_outer_parens(self._extract_condition_body(expression)).strip()
            warnings = []
            passed = self._evaluate_document_condition(body, data, warnings=warnings)
            name = lookup.get(logic_key(body))
            if not body:
                return {"label": "No condition — always triggers", "passed": True, "details": []}
            for operator, symbol in (("OR", "||"), ("AND", "&&")):
                parts = self._split_top_level_operator(body, symbol)
                if len(parts) > 1:
                    return {"label": f"{name} ({operator})" if name else operator, "passed": passed,
                            "clause_name": name, "details": warnings, "children": [visit(part) for part in parts]}
            inner = self._unwrap_condition_negation(body)
            if inner is not None:
                return {"label": f"{name} (NOT)" if name else "NOT", "passed": passed,
                        "clause_name": name, "details": warnings, "children": [visit(inner)]}
            # The core evaluator is authoritative; the copied helpers supply found/expected text.
            not_empty = re.match(r"^(.*?)\s+not\s+empty\s*$", body, re.IGNORECASE)
            if not_empty:
                values = self._evaluate_condition_operand(data, not_empty.group(1))
                details = [f"Expected: {not_empty.group(1)} should be present and non-empty.",
                           f"Found: {self._format_mapped_nodeset_preview(values)}"]
            else:
                _, details = self._describe_atomic_condition_result(body, data)
            return {"label": name or body, "passed": passed, "clause_name": name,
                    "details": ([body] if name else []) + details + warnings}

        return visit(condition)

    def _build_clause_expression_lookup_with_entries(self, entries: list[dict[str, str]]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for item in entries:
            name = str(item.get("name", "")).strip()
            expression = str(item.get("expression", "")).strip()
            if not name or not expression:
                continue
            try:
                resolved_expression = self._resolve_clause_expression_by_name_from_entries(entries, name)
            except ValueError:
                resolved_expression = expression
            key = self._canonical_condition_expression(resolved_expression)
            if not key:
                continue
            if key not in lookup:
                lookup[key] = name
        return lookup

    @staticmethod
    def _extract_embedded_clause_references(expression: str) -> list[str]:
        matches = re.findall(r"CLAUSE\{([^}]+)\}", str(expression or ""), flags=re.IGNORECASE)
        references: list[str] = []
        for match in matches:
            name = str(match).strip()
            if name:
                references.append(name)
        return references

    @staticmethod
    def _get_clause_expression_by_name_from_entries(entries: list[dict[str, str]], clause_name: str) -> str:
        target = str(clause_name or "").strip()
        if not target:
            return ""
        for item in entries:
            if str(item.get("name", "")).strip() == target:
                return str(item.get("expression", "")).strip()
        return ""

    @classmethod
    def _resolve_clause_expression_by_name_from_entries(
        cls,
        entries: list[dict[str, str]],
        clause_name: str,
        *,
        stack: tuple[str, ...] = (),
    ) -> str:
        name = str(clause_name or "").strip()
        if not name:
            raise ValueError("Embedded clause name is empty.")
        if name in stack:
            chain = " -> ".join((*stack, name))
            raise ValueError(f"Embedded clause cycle detected: {chain}")
        expression = cls._get_clause_expression_by_name_from_entries(entries, name)
        if not expression:
            raise ValueError(f"Unknown clause '{name}'.")
        return cls._resolve_clause_expression_text_from_entries(entries, expression, stack=(*stack, name))

    @classmethod
    def _resolve_clause_expression_text_from_entries(
        cls,
        entries: list[dict[str, str]],
        expression: str,
        *,
        stack: tuple[str, ...] = (),
    ) -> str:
        text = str(expression or "").strip()
        if not text:
            return ""
        if not cls._extract_embedded_clause_references(text):
            return text

        def replace_match(match: re.Match[str]) -> str:
            ref_name = str(match.group(1) or "").strip()
            if not ref_name:
                raise ValueError("Embedded clause name is empty.")
            resolved = cls._resolve_clause_expression_by_name_from_entries(entries, ref_name, stack=stack)
            resolved_body = cls._extract_condition_body(resolved).strip()
            if not resolved_body:
                raise ValueError(f"Embedded clause '{ref_name}' has no expression.")
            return f"({resolved_body})"

        return re.sub(r"CLAUSE\{([^}]+)\}", replace_match, text, flags=re.IGNORECASE)

    @staticmethod
    def _canonical_condition_expression(expression: str) -> str:
        text = ConditionDiagnostics._strip_outer_parens(ConditionDiagnostics._extract_condition_body(str(expression or ""))).strip()
        if not text:
            return ""
        chars: list[str] = []
        in_quote = ""
        escaped = False
        for ch in text:
            if in_quote:
                chars.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == in_quote:
                    in_quote = ""
                continue
            if ch in {"'", '"'}:
                in_quote = ch
                chars.append(ch)
                continue
            if ch.isspace():
                continue
            chars.append(ch)
        canonical = "".join(chars)
        if canonical.startswith("$."):
            canonical = "@." + canonical[2:]
        return canonical

    def _evaluate_atomic_condition_with_detail(
        self,
        expression: str,
        data_payload: object,
        *,
        comms_compatible: bool = True,
    ) -> tuple[bool, str]:
        expr = self._strip_outer_parens(expression)
        if not expr:
            return True, "empty expression"

        negated_expr = self._unwrap_condition_negation(expr)
        if negated_expr is not None:
            passed = self._evaluate_condition_expression(
                negated_expr,
                data_payload,
                comms_compatible=comms_compatible,
            )
            return (
                not passed,
                f"inner condition {self._condition_status_text(passed)}: {negated_expr}",
            )

        empty_match = re.match(r"^(.*?)\s+empty\s+(true|false)\s*$", expr, flags=re.IGNORECASE)
        if empty_match:
            path = empty_match.group(1).strip()
            expect_empty = empty_match.group(2).lower() == "true"
            normalized_path = self._normalize_condition_path(path)
            parse_issue = self._condition_path_comms_filter_literal_parse_issue(normalized_path)
            parent_path = self._get_empty_check_parent_path(normalized_path)
            parent_values = self._extract_values_by_path(data_payload, parent_path)
            if len(parent_values) == 0:
                if comms_compatible and expect_empty and self._path_has_filter(normalized_path):
                    detail = (
                        "filtered parent path missing: "
                        f"{parent_path}; Comms-compatible check treats this as not empty"
                    )
                    if parse_issue:
                        detail = f"{detail}; warning: {parse_issue}"
                    return (
                        False,
                        detail,
                    )
                passed = expect_empty
                detail = f"parent path missing: {parent_path}"
                if parse_issue:
                    detail = f"{detail}; warning: {parse_issue}"
                return passed, detail
            full_values = self._extract_values_by_path(data_payload, normalized_path)
            is_empty = len(full_values) == 0
            if comms_compatible and expect_empty and is_empty and not self._path_has_filter(normalized_path):
                detail = f"missing leaf path: {normalized_path}"
                if parse_issue:
                    detail = f"{detail}; warning: {parse_issue}"
                return False, detail
            passed = is_empty if expect_empty else not is_empty
            detail = f"values={self._format_mapped_nodeset_preview(full_values)}"
            if parse_issue:
                detail = f"{detail}; warning: {parse_issue}"
            return passed, detail

        size_match = self._find_top_level_word_operator(expr, "size")
        if size_match is not None:
            path, expected_size = size_match
            values = self._evaluate_condition_operand(data_payload, path)
            expected_values = self._evaluate_condition_operand(data_payload, expected_size)
            passed = self._compare_condition_operand_values([len(values)], "==", expected_values)
            return (
                passed,
                f"size={len(values)} "
                f"values={self._format_mapped_nodeset_preview(values)} "
                f"expected={self._format_mapped_nodeset_preview(expected_values)}",
            )

        comparison = self._find_top_level_comparison(expr)
        if comparison is not None:
            lhs, operator, rhs = comparison
            left_values = self._evaluate_condition_operand(data_payload, lhs)
            right_values = self._evaluate_condition_operand(data_payload, rhs)
            if operator in {"==", "!="}:
                missing_result = self._compare_missing_condition_operand_values(
                    left_values,
                    operator,
                    right_values,
                    comms_compatible=comms_compatible,
                )
                if missing_result is not None:
                    passed, side, present_values = missing_result
                    return (
                        passed,
                        f"{side} missing; comparison has no matching value "
                        f"against {self._format_mapped_nodeset_preview(present_values)}",
                    )
            if not left_values or not right_values:
                notes = []
                if not left_values:
                    left_note = self._condition_template_field_reference_note(lhs)
                    if left_note:
                        notes.append(left_note)
                if not right_values:
                    right_note = self._condition_template_field_reference_note(rhs)
                    if right_note:
                        notes.append(right_note)
                detail = f"left={len(left_values)} right={len(right_values)}"
                if notes:
                    detail = f"{detail}; " + "; ".join(notes)
                return False, detail
            passed = self._compare_condition_operand_values(left_values, operator, right_values)
            return (
                passed,
                f"left={self._format_mapped_nodeset_preview(left_values)} "
                f"right={self._format_mapped_nodeset_preview(right_values)}",
            )

        values = self._evaluate_condition_operand(data_payload, expr)
        passed = len(values) > 0
        return passed, f"values={self._format_mapped_nodeset_preview(values)}"

    def _format_mapped_nodeset_preview(self, mapped_values: list[object]) -> str:
        preview_items = [self._format_mapping_value_preview(value) for value in mapped_values[:5]]
        preview_json = json.dumps(preview_items, ensure_ascii=False)
        if len(mapped_values) > 5:
            return f"{preview_json} (+{len(mapped_values) - 5} more)"
        return preview_json

    @staticmethod
    def _format_mapping_value_preview(value: object) -> object:
        """Keep mapping diagnostics useful without rendering entire mapped objects."""
        if isinstance(value, dict):
            return f"{{…}} ({len(value)} key(s))"
        if isinstance(value, list):
            return f"[…] ({len(value)} item(s))"
        if isinstance(value, str) and len(value) > 300:
            return f"{value[:297]}…"
        return value

    @staticmethod
    def _condition_status_text(passed: bool) -> str:
        return "PASS" if passed else "FAIL"

    def _describe_atomic_condition_result(
        self,
        expression: str,
        data_payload: object,
    ) -> tuple[bool, list[str]]:
        expr = self._strip_outer_parens(expression)
        negated_expr = self._unwrap_condition_negation(expr)
        if negated_expr is not None:
            inner_passed, inner_details = self._describe_atomic_condition_result(negated_expr, data_payload)
            passed = not inner_passed
            details = [
                f"Check: {expr}",
                f"Expected: NOT ({negated_expr})",
                f"Inner result: {self._condition_status_text(inner_passed)}",
            ]
            details.extend(inner_details)
            return passed, details

        passed, details = self._evaluate_atomic_condition_with_detail(expr, data_payload)

        empty_match = re.match(r"^(.*?)\s+empty\s+(true|false)\s*$", expr, flags=re.IGNORECASE)
        if empty_match:
            path = empty_match.group(1).strip()
            expect_empty = empty_match.group(2).lower() == "true"
            expected = (
                f"{path} should be empty or missing."
                if expect_empty
                else f"{path} should be present and non-empty."
            )
            return passed, [
                f"Check: {expr}",
                f"Expected: {expected}",
                f"Found: {self._humanize_condition_detail(details)}",
            ]

        size_match = self._find_top_level_word_operator(expr, "size")
        if size_match is not None:
            path, expected_size = size_match
            return passed, [
                f"Check: {expr}",
                f"Expected: {path} should resolve to {expected_size} value(s).",
                f"Found: {self._humanize_condition_detail(details)}",
            ]

        comparison = self._find_top_level_comparison(expr)
        if comparison is not None:
            lhs, operator, rhs = comparison
            return passed, [
                f"Check: {expr}",
                f"Expected: {lhs} {operator} {rhs}",
                f"Found: {self._humanize_condition_detail(details)}",
            ]

        return passed, [
            f"Check: {expr}",
            "Expected: path/expression should find at least one value.",
            f"Found: {self._humanize_condition_detail(details)}",
        ]

    @staticmethod
    def _humanize_condition_detail(details: str) -> str:
        text = str(details or "").strip()
        if text == "values=[]":
            return "no values."
        if text.startswith("values="):
            return f"values found: {text[len('values='):]}"
        size_match = re.match(r"^size=(\d+)\s+values=(.*?)\s+expected=(.*)$", text)
        if size_match:
            return (
                f"size {size_match.group(1)}; "
                f"values found: {size_match.group(2)}; "
                f"expected sizes: {size_match.group(3)}"
            )
        left_right_match = re.match(r"^left=(.*?)\s+right=(.*)$", text)
        if left_right_match:
            return f"left values: {left_right_match.group(1)}; right values: {left_right_match.group(2)}"
        if text.startswith("parent path missing:"):
            return text + "."
        if text.startswith("filtered parent path missing:"):
            return text + "."
        return text
