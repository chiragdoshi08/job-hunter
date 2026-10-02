#!/bin/zsh
set -eu
cd "${0:A:h}"
if ! command -v python3 >/dev/null; then
  print 'Use the bundled Mac release, or install Python 3 from https://www.python.org/downloads/.'
  read '?Press Enter to close…'
  exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
print 'Installed. Open Launch Job Hunter.command.'
