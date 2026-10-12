#!/usr/bin/env bash
# Build the static Live Overview into ./build (run from ./live_overview).
# Pass --mockup to read ../sitedata_mock. Data refresh and merging into ../build are the caller's job.
set -euo pipefail
export PYTHONIOENCODING=utf-8
uv run python scripts/build_miniconf.py "$@"
