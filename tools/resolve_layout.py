#!/usr/bin/env python3
"""Explain one cached Comms layout for a sample JSON input."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from atool_core.layout_resolver import LayoutResolver, format_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True, help="Downloaded Comms resource cache")
    parser.add_argument("--package", required=True)
    parser.add_argument("--document", required=True)
    parser.add_argument("--layout", required=True, help="Root layout name in the selected document")
    parser.add_argument("--data", type=Path, required=True, help="Input JSON")
    parser.add_argument("--effective-date", help="YYYY-MM-DD, default today")
    parser.add_argument("--at-version", help="Assembly Template version folder, required if ambiguous")
    parser.add_argument(
        "--system-field",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Override a generated field, e.g. PackagePageNum=2 or GRIDPAGENUMBER=2",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", type=Path, help="Write the report to a file")
    args = parser.parse_args()
    try:
        system_fields = {}
        for entry in args.system_field:
            if "=" not in entry:
                raise ValueError(f"Invalid --system-field {entry!r}; expected NAME=VALUE")
            name, raw = entry.split("=", 1)
            if not name:
                raise ValueError("System field name cannot be empty")
            try:
                system_fields[name] = json.loads(raw)
            except json.JSONDecodeError:
                system_fields[name] = raw
        payload = json.loads(args.data.read_text(encoding="utf-8-sig"))
        result = LayoutResolver(
            args.cache, args.package, args.document, payload,
            effective_date=args.effective_date,
            at_version=args.at_version,
            system_fields=system_fields,
        ).resolve(args.layout)
        report = json.dumps(result, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else format_report(result)
        if args.output:
            args.output.write_text(report, encoding="utf-8")
        else:
            sys.stdout.write(report)
        return 0
    except (OSError, ValueError, StopIteration) as error:
        parser.exit(2, f"resolve_layout: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
