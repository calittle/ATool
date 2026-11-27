"""Advisory selector checks; never rewrite or reject an authored expression."""
from __future__ import annotations

import re

from .condition_evaluator import ConditionEvaluator
from .jsonpath_preflight import _receiver, _syntax


def selector_recommendations(expression: str, data: object = None, *, mapped: bool = False,
                             contexts: list[object] | None = None, parent_path: str = '') -> list[str]:
    """Inspect each selector against its receiver in this sample, including filters.

    Quoted strings and regexes are masked before scanning. Relative paths within
    filters are evaluated against the enclosing filter's candidate nodes. Unknown
    expressions stay inconclusive rather than suggesting a replacement.
    """
    syntax = _syntax(expression)
    evaluator = ConditionEvaluator()

    def receivers(end: int) -> list[object]:
        end = len(syntax[:end].rstrip())
        receiver = _receiver(syntax, end)
        start = end - len(receiver)
        path = expression[start:end].strip()
        if not path.startswith(('$', '@')) or '(' in re.split(r'\[\s*\?\(', _syntax(path), maxsplit=1)[0]:
            return []
        targets = [data] if contexts is None else contexts
        if path.startswith('@'):
            # Locate the innermost filter containing this relative reference.
            stack = []
            for index, char in enumerate(syntax[:start]):
                if char == '[':
                    stack.append(index)
                elif char == ']' and stack:
                    stack.pop()
            filters = [index for index in stack if re.match(r'\[\s*\?\(', syntax[index:])]
            if filters:
                targets = []
                for container in receivers(filters[-1]):
                    if isinstance(container, list):
                        targets.extend(container)
                    elif isinstance(container, dict):
                        targets.append(container)
            path = '$' + path[1:]
        elif parent_path and (path == parent_path or path.startswith((parent_path + '.', parent_path + '['))):
            path = '$' + path[len(parent_path):]
        elif parent_path and parent_path.startswith((path + '.', path + '[')):
            # A full-document field path repeats its iterator's selectors;
            # those receivers occur before the iterator row scope begins.
            targets = [data]
        return [value for context in targets for value in evaluator._extract_values_by_path(context, path)]

    findings = []
    for match in re.finditer(r'\[\s*(\*|0\s*:)\s*\]', syntax):
        wildcard = match.group(1) == '*'
        label = f'{expression[match.start():match.end()]} at character {match.start() + 1}'
        if not mapped:
            if wildcard:
                findings.append(f'{label}: Product recommends [0:] for arrays to avoid intermittent missing '
                                'preview values. Map a data file to check the target type; keep [*] for objects.')
            continue
        values = receivers(match.start())
        arrays = any(isinstance(value, list) for value in values)
        objects = any(isinstance(value, dict) for value in values)
        other = any(not isinstance(value, (list, dict)) for value in values)
        if arrays and not objects and not other:
            if not wildcard:
                continue
            message = ('Based on the mapped data, this selector targets arrays only. Prefer [0:] '
                       'to avoid the intermittent preview omissions reported by Product.')
        elif objects and not arrays and not other:
            message = ('Based on the mapped data, this selector targets objects only. Keep [*]; '
                       '[0:] selects no object properties.' if wildcard else
                       'Based on the mapped data, [0:] targets objects and returns no matches. '
                       'Use [*] if you intend to select their property values.')
        elif arrays or objects:
            message = ('The mapped data contains mixed target types. [*] supports arrays and objects; '
                       '[0:] supports arrays only. Changing selectors can change results; review the data structure.')
        else:
            message = ('The mapped data provides no array or object target at this location. '
                       'ATool cannot recommend a replacement. Prefer [0:] only for known arrays; '
                       'keep [*] for objects.')
        findings.append(f'{label}: {message} Other input files may have different structures.')
    return findings


def audit_selector_paths(value: object, data: object = None, *, mapped: bool = False,
                        path: str = '$', owners: tuple[str, ...] = (),
                        contexts: list[object] | None = None, parent_path: str = '',
                        iteration: bool = False) -> list[dict]:
    """Audit persisted paths, conditions, and clauses using the current sample."""
    findings = []
    if isinstance(value, dict):
        owner = value.get('$$Id') or value.get('Name') or value.get('name')
        if isinstance(owner, str) and owner:
            owners = (*owners, owner)
        child_contexts, child_path = contexts, parent_path
        if iteration or value.get('Type') in ('Iterator', 'Spliterator'):
            iteration_path = str(value.get('Path') or '').strip()
            relative = iteration_path
            if parent_path and (relative == parent_path or relative.startswith((parent_path + '.', parent_path + '['))):
                relative = '$' + relative[len(parent_path):]
            evaluator = ConditionEvaluator()
            values = [item for context in ([data] if contexts is None else contexts)
                      for item in evaluator._extract_values_by_path(context, relative)] if relative else []
            child_contexts = [item for collection in values
                              for item in (collection if isinstance(collection, list) else [collection])]
            child_path = iteration_path
        for key, item in value.items():
            location = f'{path}.{key}'
            if key in {'Path', 'Condition', 'expression'} and isinstance(item, str):
                issues = selector_recommendations(item, data, mapped=mapped,
                                                  contexts=contexts, parent_path=parent_path)
                if issues:
                    findings.append(dict(path=location, owners=list(owners), expression=item, issues=issues))
            elif isinstance(item, (dict, list)):
                findings.extend(audit_selector_paths(item, data, mapped=mapped, path=location, owners=owners,
                                                     contexts=child_contexts, parent_path=child_path,
                                                     iteration=key.lower() == 'iteration'))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(audit_selector_paths(item, data, mapped=mapped, path=f'{path}[{index}]', owners=owners,
                                                 contexts=contexts, parent_path=parent_path, iteration=iteration))
    return findings
