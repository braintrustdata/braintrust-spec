#!/usr/bin/env python3
"""Aggregate the hand-maintained SDK support tables.

    scripts/render-parity.py
    scripts/render-parity.py --sdk java
    scripts/render-parity.py --json
    scripts/render-parity.py --feature "Eval spans"
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import compatibility as compat

LEGEND = "✅ supported · ⚠️ partial · ❌ not supported · ❓ unverified · – not applicable"


def glyph(status: str) -> str:
    return compat.STATUSES.get(status, f"?{status}?")


def render_table(rows: list[compat.Row], sdks: list[compat.Sdk]) -> list[str]:
    body = [
        [row.title] + [glyph(row.cells[sdk.key].status) for sdk in sdks]
        for row in rows
    ]
    header = ["Capability"] + [sdk.title for sdk in sdks]
    widths = [max(display_width(row[i]) for row in [header] + body) for i in range(len(header))]
    return [render_row(header, widths), render_divider(widths)] + [
        render_row(row, widths) for row in body
    ]


def display_width(text: str) -> int:
    return len(text) - text.count("\ufe0f") + sum(1 for char in text if char in "✅⚠❌❓")


def render_row(cells: list[str], widths: list[int]) -> str:
    padded = [
        cell + " " * max(0, width - display_width(cell))
        for cell, width in zip(cells, widths)
    ]
    return "| " + " | ".join(padded) + " |"


def render_divider(widths: list[int]) -> str:
    return "| " + " | ".join("-" * width for width in widths) + " |"


def select_feature(features: list[compat.Feature], title: str | None) -> list[compat.Feature]:
    if not title:
        return features
    matched = [
        feature
        for feature in features
        if feature.id.lower() == title.lower() or feature.title.lower() == title.lower()
    ]
    if not matched:
        sys.exit(
            f"error: no feature named {title!r} "
            f"(have: {', '.join(feature.title for feature in features)})"
        )
    return matched


def render_markdown(features: list[compat.Feature], sdks: list[compat.Sdk]) -> str:
    out = ["# SDK feature support", ""]
    for feature in features:
        out.extend([f"## {feature.title}", "", *render_table(feature.rows, sdks), ""])
    out.extend([f"Legend: {LEGEND}", ""])
    return "\n".join(out)


def render_sdk(features: list[compat.Feature], sdks: list[compat.Sdk], key: str) -> str:
    sdk = next((sdk for sdk in sdks if sdk.key == key), None)
    if sdk is None:
        sys.exit(f"error: unknown sdk {key!r} (have: {', '.join(s.key for s in sdks)})")

    out = [f"# {sdk.title} — feature support", ""]
    tally: dict[str, int] = {}
    for feature in features:
        out.extend([f"## {feature.title}", ""])
        for row in feature.rows:
            status = row.cells[sdk.key].status
            tally[status] = tally.get(status, 0) + 1
            out.append(f"- {glyph(status)} {row.title}")
        out.append("")
    out.append(" · ".join(f"{glyph(status)} {tally[status]}" for status in compat.STATUSES if status in tally))
    return "\n".join(out) + "\n"


def render_json(features: list[compat.Feature], sdks: list[compat.Sdk]) -> str:
    return json.dumps(
        {
            "sdks": [{"key": sdk.key, "title": sdk.title} for sdk in sdks],
            "features": [
                {
                    "id": feature.id,
                    "name": feature.title,
                    "source": feature.path,
                    "metadata": feature.metadata,
                    "capabilities": [
                        {
                            "id": row.id,
                            "title": row.title,
                            "support": {key: cell.status for key, cell in row.cells.items()},
                        }
                        for row in feature.rows
                    ],
                }
                for feature in features
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", help="render one SDK as a checklist")
    parser.add_argument("--feature", help="render only one feature")
    parser.add_argument("--json", action="store_true", help="render machine-readable JSON")
    args = parser.parse_args()

    try:
        catalog = compat.load_catalog()
        sdks = catalog.sdks
        features = select_feature(catalog.features, args.feature)
    except compat.CompatibilityError as exc:
        sys.exit(f"error: {exc}")

    if args.json:
        print(render_json(features, sdks))
    elif args.sdk:
        print(render_sdk(features, sdks, args.sdk), end="")
    else:
        print(render_markdown(features, sdks), end="")


if __name__ == "__main__":
    main()
