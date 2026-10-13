#!/usr/bin/env bash
# Build the static Pre-Conference Lounge into ./build (run from ./preconf).
# Pass --mockup to read ../sitedata_mock. Data refresh and merging into ../build are the caller's job.
set -euo pipefail
PYTHON="${PYTHON:-python3}"
export PYTHONIOENCODING=utf-8
"$PYTHON" scripts/build_miniconf.py "$@"
