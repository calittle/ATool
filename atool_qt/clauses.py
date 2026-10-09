"""Data-independent condition composition, using ATool's original pure helpers."""
from __future__ import annotations
import re

from .diagnostics import ConditionDiagnostics


class ClauseComposer(ConditionDiagnostics):
    def _build_clause_expression_lookup_with_entries(self, entries):
        from .clause_usage import clause_token
        return {key: clause_token(name) for key, name in super()._build_clause_expression_lookup_with_entries(entries).items()}

    def compose(self, condition, entries):
        resolved = self._resolve_clause_expression_text_from_entries(entries, condition)
        return self._compose_expression_from_raw_condition_with_entries(resolved, entries)

    def _compose_expression_from_raw_condition_with_entries(
        self,
        condition_text: str,
        entries: list[dict[str, str]],
    ) -> tuple[str, bool, int]:
        raw_body = self._strip_outer_parens(self._extract_condition_body(condition_text)).strip()
        if not raw_body:
            return "", True, 0
        clause_lookup = self._build_clause_expression_lookup_with_entries(entries)
        composed, exact, unmatched = self._compose_clause_expression_recursive(raw_body, clause_lookup)
        return composed, exact, unmatched

    def _compose_clause_expression_recursive(
        self,
        expression: str,
        clause_lookup: dict[str, str],
    ) -> tuple[str, bool, int]:
        expr = self._strip_outer_parens(str(expression or "").strip())
        if not expr:
            return "", True, 0
        key = self._canonical_condition_expression(expr)
        if key in clause_lookup:
            return clause_lookup[key], True, 0

        or_parts = self._split_top_level_operator(expr, "||")
        if len(or_parts) > 1:
            parts: list[str] = []
            exact_all = True
            unmatched_total = 0
            for part in or_parts:
                rendered, exact, unmatched = self._compose_clause_expression_recursive(part, clause_lookup)
                parts.append(f"({rendered})" if self._compose_needs_parens(rendered) else rendered)
                exact_all = exact_all and exact
                unmatched_total += unmatched
            return " OR ".join(parts), exact_all, unmatched_total

        and_parts = self._split_top_level_operator(expr, "&&")
        if len(and_parts) > 1:
            parts = []
            exact_all = True
            unmatched_total = 0
            for part in and_parts:
                rendered, exact, unmatched = self._compose_clause_expression_recursive(part, clause_lookup)
                parts.append(f"({rendered})" if self._compose_needs_parens(rendered) else rendered)
                exact_all = exact_all and exact
                unmatched_total += unmatched
            return " + ".join(parts), exact_all, unmatched_total

        escaped = expr.replace("}", "\\}")
        return f"RAW{{{escaped}}}", False, 1

    @staticmethod
    def _compose_needs_parens(text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        if value.startswith("RAW{") and value.endswith("}"):
            return False
        return (" + " in value) or (" OR " in value)

    def _render_composed_condition_with_entries(
        self,
        compose_text: str,
        entries: list[dict[str, str]],
    ) -> str:
        text = str(compose_text or "").strip()
        if not text:
            raise ValueError("Composed expression is empty.")
        tokens = self._tokenize_clause_expression(text)
        if not tokens:
            raise ValueError("Composed expression is empty.")
        position = 0

        def parse_or() -> tuple[str, object]:
            nonlocal position
            parts: list[tuple[str, object]] = [parse_and()]
            while position < len(tokens) and tokens[position][0] == "OR":
                position += 1
                parts.append(parse_and())
            if len(parts) == 1:
                return parts[0]
            return ("OR", parts)

        def parse_and() -> tuple[str, object]:
            nonlocal position
            parts: list[tuple[str, object]] = [parse_term()]
            while position < len(tokens) and tokens[position][0] == "AND":
                position += 1
                parts.append(parse_term())
            if len(parts) == 1:
                return parts[0]
            return ("AND", parts)

        def parse_term() -> tuple[str, object]:
            nonlocal position
            if position >= len(tokens):
                raise ValueError("Unexpected end of expression.")
            token_type, token_value = tokens[position]
            if token_type == "LPAREN":
                position += 1
                inner = parse_or()
                if position >= len(tokens) or tokens[position][0] != "RPAREN":
                    raise ValueError("Missing closing parenthesis in composed expression.")
                position += 1
                return inner
            if token_type == "RAW":
                position += 1
                raw_body = self._extract_condition_body(token_value).strip()
                if not raw_body:
                    raise ValueError("RAW{...} token cannot be empty.")
                return ("ATOM", raw_body)
            if token_type != "NAME":
                raise ValueError(f"Unexpected token '{token_value}'.")
            position += 1
            clause_expression = self._resolve_clause_expression_by_name_from_entries(entries, token_value)
            clause_expression = self._extract_condition_body(clause_expression)
            if not clause_expression:
                raise ValueError(f"Clause '{token_value}' has no expression.")
            return ("ATOM", clause_expression)

        def needs_atom_parens(expr: str) -> bool:
            stripped = self._strip_outer_parens(expr)
            return len(self._split_top_level_operator(stripped, "&&")) > 1 or len(
                self._split_top_level_operator(stripped, "||")
            ) > 1

        def render(node: tuple[str, object], parent_precedence: int = 0) -> str:
            kind, value = node
            if kind == "ATOM":
                atom = str(value).strip()
                if needs_atom_parens(atom):
                    return f"({atom})"
                return atom
            if kind == "AND":
                precedence = 2
                assert isinstance(value, list)
                text_value = " && ".join(render(child, precedence) for child in value)
                if precedence < parent_precedence:
                    return f"({text_value})"
                return text_value
            if kind == "OR":
                precedence = 1
                assert isinstance(value, list)
                text_value = " || ".join(render(child, precedence) for child in value)
                if precedence < parent_precedence:
                    return f"({text_value})"
                return text_value
            raise ValueError("Unexpected compose parser node type.")

        parsed_tree = parse_or()
        if position != len(tokens):
            raise ValueError("Unexpected trailing tokens in composed expression.")
        rendered_body = render(parsed_tree)
        return f"$[?({rendered_body})]"

    @staticmethod
    def _tokenize_clause_expression(text: str) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        index = 0
        while index < len(text):
            char = text[index]
            if char.isspace():
                index += 1
                continue
            if char == "(":
                tokens.append(("LPAREN", char))
                index += 1
                continue
            if char == ")":
                tokens.append(("RPAREN", char))
                index += 1
                continue
            if text.startswith("CLAUSE{", index):
                start = index + 7
                end = text.find("}", start)
                if end < 0:
                    raise ValueError("Unterminated CLAUSE{...} token.")
                clause_name = text[start:end].strip()
                if not clause_name:
                    raise ValueError("CLAUSE{...} token cannot be empty.")
                tokens.append(("NAME", clause_name))
                index = end + 1
                continue
            if text.startswith("RAW{", index):
                start = index + 4
                cursor = start
                depth = 1
                quote = ""
                escaped = False
                while cursor < len(text):
                    ch = text[cursor]
                    if quote:
                        if escaped:
                            escaped = False
                        elif ch == "\\":
                            escaped = True
                        elif ch == quote:
                            quote = ""
                        cursor += 1
                        continue
                    if ch in {"'", '"'}:
                        quote = ch
                        cursor += 1
                        continue
                    if ch == "{":
                        depth += 1
                        cursor += 1
                        continue
                    if ch == "}":
                        depth -= 1
                        if depth == 0:
                            payload = text[start:cursor].strip().replace("\\}", "}")
                            if not payload:
                                raise ValueError("RAW{...} token cannot be empty.")
                            tokens.append(("RAW", payload))
                            cursor += 1
                            index = cursor
                            break
                        cursor += 1
                        continue
                    cursor += 1
                else:
                    raise ValueError("Unterminated RAW{...} token.")
                continue
            if text.startswith("&&", index):
                tokens.append(("AND", "&&"))
                index += 2
                continue
            if text.startswith("||", index):
                tokens.append(("OR", "||"))
                index += 2
                continue
            if char == "+":
                tokens.append(("AND", "+"))
                index += 1
                continue
            if char == "|":
                tokens.append(("OR", "|"))
                index += 1
                continue
            and_match = re.match(r"AND\b", text[index:], flags=re.IGNORECASE)
            if and_match:
                tokens.append(("AND", and_match.group(0)))
                index += len(and_match.group(0))
                continue
            or_match = re.match(r"OR\b", text[index:], flags=re.IGNORECASE)
            if or_match:
                tokens.append(("OR", or_match.group(0)))
                index += len(or_match.group(0))
                continue
            name_match = re.match(r"[A-Za-z_][A-Za-z0-9_-]*", text[index:])
            if name_match:
                name = name_match.group(0)
                tokens.append(("NAME", name))
                index += len(name)
                continue
            raise ValueError(f"Unsupported token near '{text[index:index + 20]}'.")
        return tokens

    def _find_impacted_clause_names(
        self,
        old_entries: list[dict[str, str]],
        new_entries: list[dict[str, str]],
        *,
        changed_clause_name: str,
    ) -> set[str]:
        impacted: set[str] = set()
        old_names = {str(item.get("name", "")).strip() for item in old_entries}
        new_names = {str(item.get("name", "")).strip() for item in new_entries}
        for name in sorted((old_names & new_names) - {""}, key=str.casefold):
            try:
                old_expression = self._resolve_clause_expression_by_name_from_entries(old_entries, name)
            except ValueError as error:
                if name == changed_clause_name:
                    raise ValueError(f"Could not resolve the saved clause expression.\n\nDetails: {error}") from error
                continue
            try:
                new_expression = self._resolve_clause_expression_by_name_from_entries(new_entries, name)
            except ValueError as error:
                if name == changed_clause_name:
                    raise ValueError(f"Could not resolve the edited clause expression.\n\nDetails: {error}") from error
                continue
            if self._canonical_condition_expression(old_expression) != self._canonical_condition_expression(new_expression):
                impacted.add(name)
        return impacted

    def _clause_names_in_compose_text(self, compose_text: str) -> set[str]:
        try:
            tokens = self._tokenize_clause_expression(compose_text)
        except ValueError:
            return set()
        return {token_value for token_type, token_value in tokens if token_type == "NAME"}

    def _classify_clause_trigger_match(
        self,
        compose_text: str,
        matched_names: set[str],
        *,
        changed_clause_name: str,
    ) -> str:
        single_clause_name = self._single_compose_clause_name(compose_text)
        if single_clause_name == changed_clause_name:
            return "Exact clause"
        if single_clause_name:
            return "Dependent clause"
        if changed_clause_name in matched_names:
            return "Embedded clause"
        return "Dependent clause"

    def _single_compose_clause_name(self, compose_text: str) -> str:
        try:
            tokens = self._tokenize_clause_expression(compose_text)
        except ValueError:
            return ""
        if len(tokens) == 1 and tokens[0][0] == "NAME":
            return tokens[0][1]
        return ""

    def _classify_clause_usage_match(self, compose_text: str, matched_clauses: list[str], clause_name: str) -> str:
        matched = set(matched_clauses)
        single_clause_name = self._single_compose_clause_name(compose_text)
        if single_clause_name == clause_name:
            return "Exact clause"
        if single_clause_name and single_clause_name in matched:
            return "Dependent clause"
        if clause_name in matched:
            return "Embedded clause"
        return "Dependent clause"

    def _raw_fragments_in_compose_text(self, compose_text: str) -> list[str]:
        if not compose_text:
            return []
        try:
            tokens = self._tokenize_clause_expression(compose_text)
        except ValueError:
            return []
        return [token_value for token_type, token_value in tokens if token_type == "RAW"]
