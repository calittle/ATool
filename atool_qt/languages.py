"""Language preferences and concrete input-field resolution for package previews."""
import re

from .data_editing import path_parts


def language_parts(path):
    try:
        parts = path_parts(path)
        if not parts:
            raise ValueError()
        return parts
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Language mapping must identify one field using an absolute JSONPath '
                         '(for example $.billPrint.billDetails.cmElements.billLanguagePreference). '
                         'Use property names and array indices; wildcards and filters are not supported.') from None


def validate_languages(settings):
    language_parts(settings.get('mapping', ''))
    rows = settings.get('display_mapping')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Add at least one language display mapping.')
    values, short_names = set(), set()
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                                          for key in ('label', 'data', 'short_name')):
            raise ValueError('Each language requires a Label, Data value, and Short Name.')
        if row['data'] in values:
            raise ValueError('Language Data values must be unique.')
        short = row['short_name']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', short):
            raise ValueError('Language Short Names must start with a letter or number and contain '
                             'only letters, numbers, underscores, or hyphens.')
        if short.casefold() in short_names:
            raise ValueError('Language Short Names must be unique (ignoring case).')
        values.add(row['data'])
        short_names.add(short.casefold())


def language_field(payload, mapping):
    """Return an existing field's parent/key so updates cannot create missing data."""
    parts = language_parts(mapping)
    parent = payload
    try:
        for key in parts[:-1]:
            parent = _child(parent, key)
        value = _child(parent, parts[-1])
    except (KeyError, IndexError, TypeError):
        raise ValueError('Language mapping does not resolve to an existing field in the input data.') from None
    if not isinstance(value, str):
        raise ValueError('The mapped language field must contain a text value.')
    return parent, parts[-1]


def _child(parent, key):
    if isinstance(key, str) and isinstance(parent, dict):
        return parent[key]
    if type(key) is int and isinstance(parent, list):
        return parent[key]
    raise TypeError()
