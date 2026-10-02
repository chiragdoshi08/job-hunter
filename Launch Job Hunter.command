#!/bin/zsh
set -eu
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  ./Install\ Job\ Hunter.command
fi
.venv/bin/python launch.py
