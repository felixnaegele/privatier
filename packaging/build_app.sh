#!/bin/sh
# Builds dist/Privatier.app and dist/Privatier-<version>-arm64.dmg.
#   sh packaging/build_app.sh               app + self-test + dmg
#   sh packaging/build_app.sh --dmg-only    only the disk image, from the existing dist/Privatier.app
# More options: sh packaging/build_app.sh --help
cd "$(dirname "$0")/.." || exit 1
exec .venv/bin/python packaging/build_app.py "$@"
