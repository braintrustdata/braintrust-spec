#!/usr/bin/env python3
"""Export the repository compatibility catalog as CSV."""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys

import compatibility as compat

DEFAULT_OUTPUT = os.path.join(compat.REPO_ROOT, "capabilities", "compatibility.csv")


def render_csv(catalog: compat.Catalog) -> str:
    """Return one spreadsheet row per capability in deterministic order."""
    sdk_columns = [sdk.title for sdk in catalog.sdks]
    fieldnames = [
        "Category",
        "Feature",
        "Feature ID",
        "Providers",
        "Capability ID",
        "Capability",
        *sdk_columns,
        "Source",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()

    for feature in catalog.features:
        category = feature.metadata.get("category", "")
        providers = feature.metadata.get("providers", [])
        if isinstance(providers, list):
            providers = ", ".join(str(provider) for provider in providers)
        for capability in feature.rows:
            row = {
                "Feature ID": feature.id,
                "Feature": feature.title,
                "Category": str(category),
                "Providers": str(providers),
                "Capability ID": capability.id,
                "Capability": capability.title,
                "Source": feature.path,
            }
            row.update(
                {
                    sdk.title: capability.cells[sdk.key].status
                    for sdk in catalog.sdks
                }
            )
            writer.writerow(row)
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="CSV output path")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the existing output does not match the catalog",
    )
    args = parser.parse_args()

    try:
        content = render_csv(compat.load_catalog())
    except compat.CompatibilityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output_path = os.path.abspath(args.output)
    if args.check:
        try:
            with open(output_path, encoding="utf-8", newline="") as handle:
                existing = handle.read()
        except FileNotFoundError:
            existing = None
        if existing != content:
            print(
                f"error: {os.path.relpath(output_path, compat.REPO_ROOT)} is out of date; "
                "run `make compatibility-csv`",
                file=sys.stderr,
            )
            return 1
        print(f"ok: {os.path.relpath(output_path, compat.REPO_ROOT)} is up to date")
        return 0

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    print(f"wrote {os.path.relpath(output_path, compat.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
