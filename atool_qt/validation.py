"""Original AT text normalization and persisted-condition validation."""
from __future__ import annotations
import re
import unicodedata

class PayloadValidation:

    @staticmethod
    def _mojibake_score(value: str) -> int:
        """Score common UTF-8 bytes that were decoded as Windows-1252 text."""
        return len(re.findall(r"(?:Ã.|Â.|â.{1,2}|ð.|[À-ÿ][\u0080-\u00bf]|[€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ])", value))

    @classmethod
    def _repair_utf8_mojibake(cls, value: str) -> str:
        """Repair a safe, high-confidence Windows-1252/UTF-8 decoding mistake once."""
        score = cls._mojibake_score(value)
        if score == 0:
            return value
        try:
            repaired = value.encode("cp1252").decode("utf-8")
        except UnicodeError:
            return value
        return repaired if cls._mojibake_score(repaired) < score else value

    @classmethod
    def _sanitize_package_text(cls, value: object) -> str:
        text = unicodedata.normalize("NFC", str(value or ""))
        text = re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", text)
        return cls._repair_utf8_mojibake(text)

    @classmethod
    def _sanitize_package_text_object(cls, value: object) -> bool:
        changed = False
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if isinstance(item, str):
                    sanitized = cls._sanitize_package_text(item)
                    if sanitized != item:
                        value[key] = sanitized
                        changed = True
                elif isinstance(item, (dict, list)):
                    changed = cls._sanitize_package_text_object(item) or changed
            return changed
        if isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    sanitized = cls._sanitize_package_text(item)
                    if sanitized != item:
                        value[index] = sanitized
                        changed = True
                elif isinstance(item, (dict, list)):
                    changed = cls._sanitize_package_text_object(item) or changed
            return changed
        return False

    @classmethod
    def _payload_condition_validation_issues(cls, value: object, path: str = "$") -> list[str]:
        """Return validation errors for persisted Condition values only."""
        issues: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                item_path = f"{path}.{key}"
                if key == "Condition" and isinstance(item, str):
                    condition_issues, _warnings = cls._at_condition_validation_messages(item)
                    issues.extend(f"{item_path}: {issue}" for issue in condition_issues)
                elif isinstance(item, (dict, list)):
                    issues.extend(cls._payload_condition_validation_issues(item, item_path))
            return issues
        if isinstance(value, list):
            for index, item in enumerate(value):
                issues.extend(cls._payload_condition_validation_issues(item, f"{path}[{index}]"))
        return issues

    @classmethod
    def _normalize_field_mandatory_defaults(cls, value: object) -> None:
        """Make persisted Field definitions explicit about their optional status.

        OCCS defaults iteration fields to mandatory when the key is omitted,
        unlike regular fields.  Field collections can appear at any nesting
        depth in a layout, so normalize them recursively immediately before
        every save.
        """
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() == "fields" and isinstance(item, list):
                    for field in item:
                        if isinstance(field, dict):
                            field.setdefault("Mandatory", False)
                cls._normalize_field_mandatory_defaults(item)
        elif isinstance(value, list):
            for item in value:
                cls._normalize_field_mandatory_defaults(item)

    @classmethod
    def _at_condition_validation_messages(cls, condition: str) -> tuple[list[str], list[str]]:
        text = str(condition or "").strip()
        if not text:
            return [], []
        issues: list[str] = []
        warnings: list[str] = []
        match = re.match(r"^\$\s*\[\s*\?\s*\((.*)\)\s*\]\s*$", text, flags=re.DOTALL)
        if not match:
            issues.append("Use the AT condition wrapper format: $[?(...)]")
            return issues, warnings
        body = match.group(1).strip()
        if not body:
            issues.append("Condition body cannot be empty.")
            return issues, warnings
        balance_error = cls._condition_delimiter_error(body)
        if balance_error:
            issues.append(balance_error)
        if "@" not in body and "$" not in body:
            warnings.append("Condition body does not reference a JSON path using @ or $.")
        if "==" in body and not re.search(r"[@$][\w.$@\[\]'\"*?()=<>!\s-]*==", body):
            warnings.append("Condition uses ==, but no JSON path was found near the comparison.")
        return issues, warnings

    @staticmethod
    def _condition_delimiter_error(expression: str) -> str:
        pairs = {")": "(", "]": "[", "}": "{"}
        opening = set(pairs.values())
        stack: list[str] = []
        quote = ""
        escaped = False
        for char in expression:
            if quote:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == quote:
                    quote = ""
                continue
            if char in {"'", '"'}:
                quote = char
                continue
            if char in opening:
                stack.append(char)
                continue
            expected = pairs.get(char)
            if expected is None:
                continue
            if not stack or stack[-1] != expected:
                return f"Unbalanced delimiter near '{char}'."
            stack.pop()
        if quote:
            return f"Unterminated quoted string ({quote})."
        if stack:
            return f"Unclosed delimiter '{stack[-1]}'."
        return ""
