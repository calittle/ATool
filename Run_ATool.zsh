#!/bin/zsh
cd -- "$(dirname -- "$0")"
if [[ -x .venv/bin/python ]]; then
  .venv/bin/python ATool.py
else
  python3 ATool.py
fi
