"""Pure path helpers copied from AToolApp for the isolated Qt prototype.

Keep behavior aligned with ATool until these helpers can be shared.
"""


class PathNormalizer:
    @staticmethod
    def _strip_trailing_commas(text: str) -> str:
        chars: list[str] = []
        index = 0
        in_string = False
        escaped = False

        while index < len(text):
            ch = text[index]

            if in_string:
                chars.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                index += 1
                continue

            if ch == '"':
                in_string = True
                chars.append(ch)
                index += 1
                continue

            if ch == ",":
                lookahead = index + 1
                while lookahead < len(text) and text[lookahead] in " \t\r\n":
                    lookahead += 1
                if lookahead < len(text) and text[lookahead] in "]}":
                    index += 1
                    continue

            chars.append(ch)
            index += 1

        return "".join(chars)

    def _normalize_true_path(self, path: str) -> str:
        candidate = self._normalize_path_expression(path.strip())
        if not candidate:
            return "$"

        previous = ""
        while candidate != previous:
            previous = candidate
            candidate = self._strip_wrapper_function(candidate, "length")
            candidate = self._strip_wrapper_function(candidate, "concat")
            candidate = candidate.replace(".length()", "")
            candidate = self._trim_trailing_unmatched_closing_parens(candidate)
            candidate = candidate.strip()

        if candidate.startswith("$.length("):
            candidate = self._strip_wrapper_function(candidate[2:], "length")
            candidate = self._trim_trailing_unmatched_closing_parens(candidate)
        if candidate.startswith("$.concat("):
            candidate = self._strip_wrapper_function(candidate[2:], "concat")
            candidate = self._trim_trailing_unmatched_closing_parens(candidate)

        if not candidate.startswith("$"):
            extracted = self._extract_first_jsonpath(candidate)
            if extracted:
                candidate = extracted

        extracted = self._extract_first_jsonpath(candidate)
        return extracted or candidate or "$"

    @staticmethod
    def _trim_trailing_unmatched_closing_parens(expression: str) -> str:
        text = expression.strip()
        while text.endswith(")") and PathNormalizer._paren_balance(text) < 0:
            text = text[:-1].rstrip()
        return text

    @staticmethod
    def _paren_balance(expression: str) -> int:
        balance = 0
        in_string = ""
        escaped = False
        for char in expression:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == in_string:
                    in_string = ""
                continue
            if char in {"'", '"'}:
                in_string = char
                continue
            if char == "(":
                balance += 1
            elif char == ")":
                balance -= 1
        return balance

    @staticmethod
    def _normalize_path_expression(path: str) -> str:
        text = path.strip()
        if not text:
            return text
        # Some payloads preserve JSON-escaped quotes (e.g. \"\") in Path values.
        # Normalize those escape sequences before syntax validation and path parsing.
        return text.replace('\\"', '"').replace("\\'", "'")

    def _strip_wrapper_function(self, expression: str, function_name: str) -> str:
        expr = expression.strip()
        direct = self._unwrap_named_call(expr, function_name)
        if direct is not None:
            if function_name == "concat":
                return self._select_concat_path(direct)
            return direct.strip()

        prefixed = self._unwrap_named_call(expr[2:], function_name) if expr.startswith("$.") else None
        if prefixed is not None:
            if function_name == "concat":
                return self._select_concat_path(prefixed)
            return prefixed.strip()
        return expr

    def _select_concat_path(self, args_text: str) -> str:
        args = self._split_top_level(args_text)
        best = ""
        for arg in args:
            normalized = self._normalize_true_path(arg)
            if "$" in normalized and len(normalized) > len(best):
                best = normalized
        return best or args_text.strip()

    def _extract_first_jsonpath(self, expression: str) -> str:
        expr = expression.strip()
        if not expr:
            return ""

        in_string = ""
        escaped = False
        paren_depth = 0
        bracket_depth = 0
        start = -1

        for index, char in enumerate(expr):
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == in_string:
                    in_string = ""
                continue

            if char in {"'", '"'}:
                in_string = char
                continue

            if char == "[":
                bracket_depth += 1
            elif char == "]":
                if bracket_depth > 0:
                    bracket_depth -= 1
            elif char == "(":
                paren_depth += 1
            elif char == ")":
                if paren_depth > 0:
                    paren_depth -= 1

            if start < 0 and char == "$":
                start = index
                continue

            if start >= 0 and paren_depth == 0 and bracket_depth == 0 and char in {",", "+"}:
                break

        if start < 0:
            return ""
        end = len(expr)
        in_string = ""
        escaped = False
        paren_depth = 0
        bracket_depth = 0
        for index in range(start, len(expr)):
            char = expr[index]
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == in_string:
                    in_string = ""
                continue

            if char in {"'", '"'}:
                in_string = char
                continue
            if char == "[":
                bracket_depth += 1
                continue
            if char == "]":
                if bracket_depth > 0:
                    bracket_depth -= 1
                continue
            if char == "(":
                paren_depth += 1
                continue
            if char == ")":
                if paren_depth > 0:
                    paren_depth -= 1
                    continue
                if bracket_depth == 0:
                    end = index
                    break
            if char in {",", "+"} and paren_depth == 0 and bracket_depth == 0:
                end = index
                break
        return expr[start:end].strip()

    def _unwrap_named_call(self, expression: str, function_name: str) -> str | None:
        expr = expression.strip()
        prefix = f"{function_name}("
        if not expr.startswith(prefix) or not expr.endswith(")"):
            return None
        if not self._is_balanced_parenthesized(expr[len(function_name):]):
            return None
        return expr[len(prefix) : -1]

    @staticmethod
    def _is_balanced_parenthesized(text: str) -> bool:
        depth = 0
        in_string = ""
        escaped = False
        for char in text:
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == in_string:
                    in_string = ""
                continue

            if char in {"'", '"'}:
                in_string = char
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    return False
        return depth == 0 and not in_string

    def _split_top_level(self, text: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        paren_depth = 0
        bracket_depth = 0
        in_string = ""
        escaped = False

        for char in text:
            if in_string:
                current.append(char)
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == in_string:
                    in_string = ""
                continue

            if char in {"'", '"'}:
                in_string = char
                current.append(char)
                continue

            if char == "(":
                paren_depth += 1
            elif char == ")":
                if paren_depth > 0:
                    paren_depth -= 1
            elif char == "[":
                bracket_depth += 1
            elif char == "]":
                if bracket_depth > 0:
                    bracket_depth -= 1

            if char == "," and paren_depth == 0 and bracket_depth == 0:
                token = "".join(current).strip()
                if token:
                    parts.append(token)
                current = []
                continue

            current.append(char)

        tail = "".join(current).strip()
        if tail:
            parts.append(tail)
        return parts
