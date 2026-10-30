from __future__ import annotations

import os
import sys


def check_deployment(is_mockup: bool) -> None:
    """Exit unless the injected env file agrees with --mockup, so mock data never meets real credentials."""
    expected = "mockup" if is_mockup else "real"
    actual = os.environ.get("DEPLOYMENT")
    if actual != expected:
        sys.exit(
            f"DEPLOYMENT is {actual!r} but this run expects {expected!r}. "
            f"Run with: uv run --env-file {expected}.env python ..."
        )
