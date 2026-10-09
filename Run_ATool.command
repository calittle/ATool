#!/bin/zsh
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print "Set up ATool first: python3 -m venv .venv"
  print "Then: .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi
.venv/bin/python ATool_Qt.py "$@"
