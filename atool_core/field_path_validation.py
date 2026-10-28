"""Check field path separators before permissive resolver normalization."""
import re


def separator_error(expression: str) -> str:
    """Leave quoted keys/values and filter spacing untouched."""
    quote = ''
    escaped = False
    index = 0
    while index < len(expression):
        char = expression[index]
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = ''
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == '.':
            end = index + 1
            while end < len(expression) and expression[end] == '.':
                end += 1
            if end - index > 2:
                return "JSONPath separators must be '.' or '..', never three or more dots."
            if end == len(expression) or expression[end] in ')]},':
                return 'A JSONPath dot separator must be followed by a property or wildcard.'
            if expression[end].isspace():
                return "Whitespace is not allowed after a JSONPath dot separator (use '$.bill', not '$. bill')."
            index = end
            continue
        index += 1
    return ''


def wildcard_concat_error(expression: str) -> str:
    """Every array wildcard must be inside a concat call for Comms fields."""
    quote = ''
    escaped = False
    calls = []
    for index, char in enumerate(expression):
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = ''
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == '(':
            calls.append(bool(re.search(r'\bconcat\s*$', expression[:index])))
        elif char == ')':
            if calls:
                calls.pop()
        elif char == '[' and re.match(r'\[\s*\*\s*\]', expression[index:]) and not any(calls):
            return ("Comms field paths containing [*] must use concat. "
                    "For example: $.concat($.rows[*].amount, '')")
    return ''
