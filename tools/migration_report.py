#!/usr/bin/env python3
"""Convert a saved ATool migration JSON record to Markdown."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from atool_qt.migration_report import write_migration_report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record',type=Path,help='Saved migration.json file')
    parser.add_argument('-o','--output',type=Path,help='Output Markdown file; defaults to migration-report.md beside the JSON')
    args=parser.parse_args()
    try:
        output=write_migration_report(args.record,args.output)
    except (OSError,ValueError,TypeError,KeyError) as error:
        parser.exit(1,f'Could not create migration report: {error}\n')
    print(output)


if __name__=='__main__':
    main()
