#!/usr/bin/env bash
# The static build uses only the Python standard library.
set -euo pipefail
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 9)' \
  || { echo "Pre-Conference Lounge needs Python 3.9+." >&2; exit 1; }
echo "Pre-Conference Lounge: no extra dependencies required."
