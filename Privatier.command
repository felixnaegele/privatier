#!/bin/zsh
# Double-click this file to open Privatier.
cd "$(dirname "$0")" || exit 1
if ! .venv/bin/python -c "import webview" 2>/dev/null; then
  echo "Installing the window library (only once)..."
  .venv/bin/python -m pip install -e ".[app]" || { echo; echo "The installation did not work."; read "?Press Return to close."; exit 1; }
fi
exec .venv/bin/python -m privatier.app
