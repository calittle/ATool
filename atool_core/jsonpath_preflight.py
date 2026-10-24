"""Read-only Comms JSONPath checks shared by save validation and AT audits."""
from __future__ import annotations

import re

from .condition_evaluator import ConditionEvaluator


def _syntax(expression: str) -> str:
    # Preserve offsets and brackets, but ignore text in literals and regexes.
    chars = list(ConditionEvaluator._condition_syntax_text(expression))
    quote = ""
    escaped = False
    for index, char in enumerate(chars):
        if quote:
            chars[index] = " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in {"'", '"'}:
            quote = char
            chars[index] = " "
    return "".join(chars)


def _receiver(syntax: str, end: int) -> str:
    """Read a method receiver backwards, retaining complete filters/calls."""
    end = len(syntax[:end].rstrip())
    index = end - 1
    brackets = parens = 0
    while index >= 0:
        char = syntax[index]
        if char == "]":
            brackets += 1
        elif char == "[":
            if not brackets:
                break
            brackets -= 1
        elif not brackets:
            if char == ")":
                parens += 1
            elif char == "(":
                if not parens:
                    break
                parens -= 1
            elif not parens:
                if char in "=<>!&|,+*/":
                    break
                if char.isspace():
                    before = syntax[:index].rstrip()
                    after = syntax[index + 1:end].lstrip()
                    if not (before.endswith('.') or after.startswith(('.', '['))):
                        break
        index -= 1
    return syntax[index + 1:end].strip()


def _path_kind(path: str) -> str:
    # @ inside an absolute path's filter is normal; classify the counted path,
    # rather than the filter's predicates or quoted property names.
    outer = []
    depth = 0
    for char in path:
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif not depth:
            outer.append(char)
    text = "".join(outer).strip()
    if ".." in text:
        return "recursive"
    if path.strip() and not path.lstrip().startswith("$"):
        return "relative"
    return ""


def length_path_issues(expression: str) -> list[str]:
    """Reject length on @/unrooted paths and recursive descent (including $..).

    Both method calls (path.length()) and wrappers (length(path) and
    $.length(path)) occur in Assembly Templates. Each call is inspected
    independently, including calls nested inside filters and other functions.
    """
    syntax = _syntax(str(expression or ""))
    kinds = set()
    for match in re.finditer(r"(?<![\w$@])length\s*\(", syntax):
        prefix = syntax[:match.start()].rstrip()
        if prefix.endswith("."):
            kind = _path_kind(_receiver(syntax, len(prefix) - 1))
            if kind:
                kinds.add(kind)
        # Read arguments through the matching closing parenthesis. A method's
        # empty argument list adds nothing; a wrapper supplies its counted path.
        start = match.end()
        end = start
        depth = 1
        while end < len(syntax):
            if syntax[end] == "(":
                depth += 1
            elif syntax[end] == ")":
                depth -= 1
                if not depth:
                    break
            end += 1
        argument = syntax[start:end].strip()
        if argument:
            kind = _path_kind(argument)
            if kind:
                kinds.add(kind)
    return [
        "Comms does not support length() with "
        + ("recursive JSONPath searches (..)." if kind == "recursive" else "relative JSONPaths (@ or unrooted paths).")
        + " Use an explicit absolute path starting with $ and no recursive descent; verify the intended counting scope."
        for kind in sorted(kinds)
    ]


def audit_length_paths(value: object, path: str = "$", owners: tuple[str, ...] = ()) -> list[dict]:
    """Locate offending persisted Paths, Conditions and reusable clause expressions."""
    findings = []
    if isinstance(value, dict):
        owner = value.get("$$Id") or value.get("Name") or value.get("name")
        if isinstance(owner, str) and owner:
            owners = (*owners, owner)
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if key in {"Path", "Condition", "expression"} and isinstance(item, str):
                issues = length_path_issues(item)
                if issues:
                    findings.append(dict(path=item_path, owners=list(owners), expression=item, issues=issues))
            elif isinstance(item, (dict, list)):
                findings.extend(audit_length_paths(item, item_path, owners))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(audit_length_paths(item, f"{path}[{index}]", owners))
    return findings


def payload_length_path_issues(value: object, path: str = "$") -> list[str]:
    return [f"{finding['path']}: {issue}" for finding in audit_length_paths(value, path)
            for issue in finding["issues"]]


def require_valid_length_paths(value: object) -> None:
    issues = payload_length_path_issues(value)
    if issues:
        suffix = f"\n… and {len(issues) - 8} more issues." if len(issues) > 8 else ""
        raise ValueError("JSONPath preflight failed:\n" + "\n".join(issues[:8]) + suffix)
