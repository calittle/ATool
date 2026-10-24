#!/usr/bin/env python3
"""Audit AT files/bundle directories without modifying package data (exit 1 on findings)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atool_core.jsonpath_preflight import audit_length_paths
from atool_qt.session import read_json, resolve_template


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('templates', nargs='+', type=Path, help='Raw ATs, bundle manifests or bundle directories')
    parser.add_argument('--output', type=Path, help='Save full JSON findings to this report file')
    args = parser.parse_args(argv)
    results = []
    seen = set()
    for source in args.templates:
        try:
            path = resolve_template(source)
            if path in seen:
                continue
            seen.add(path)
            findings = audit_length_paths(read_json(path))
            results.append(dict(file=str(path), findings=findings))
            print(f'{path}: {len(findings)} affected expressions')
            for finding in findings:
                print(f"  {finding['path']} ({' / '.join(finding['owners'])})")
        except (OSError, ValueError) as error:
            results.append(dict(file=str(source), error=str(error)))
            print(f'{source}: ERROR: {error}', file=sys.stderr)
    if args.output:
        args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if any('error' in result for result in results):
        return 2
    return int(any(result['findings'] for result in results))


if __name__ == '__main__':
    raise SystemExit(main())
