#!/usr/bin/env python3
"""Validate the SDK master list and every feature compatibility table."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import compatibility as compat


def main() -> int:
    try:
        catalog = compat.load_catalog()
    except compat.CompatibilityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rows = sum(len(feature.rows) for feature in catalog.features)
    print(
        f"ok: {rows} capability rows x {len(catalog.sdks)} sdks "
        f"across {len(catalog.features)} feature specs"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
