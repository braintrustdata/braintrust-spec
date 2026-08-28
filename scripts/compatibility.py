"""Parse and validate SDK compatibility data from this repository.

`load_catalog()` is the public entry point for components that consume compatibility
information. It returns one validated, deterministic representation of the SDK
master list and every feature specification in the repository.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEATURES_PATH = os.path.join(
    "skills", "instrumentation-spec", "references", "features"
)
SUPPORT_HEADING = "# SDK support"
ID_PATTERN = re.compile(r"[a-z][a-z0-9-]*")

STATUSES = {
    "yes": "✅",
    "partial": "⚠️",
    "no": "❌",
    "unknown": "❓",
    "n/a": "–",
}


class CompatibilityError(Exception):
    """Compatibility data is missing or invalid."""


@dataclass
class Sdk:
    key: str
    title: str


@dataclass
class Cell:
    status: str


@dataclass
class Row:
    id: str
    title: str
    cells: dict[str, Cell]


@dataclass
class Feature:
    path: str
    id: str
    title: str
    metadata: dict = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)


@dataclass
class Catalog:
    sdks: list[Sdk]
    features: list[Feature]


def load_catalog(repo_root: str = REPO_ROOT) -> Catalog:
    """Load the SDK list and every feature spec, rejecting incomplete data."""
    sdks = load_sdks(repo_root)
    features = load_features(sdks, repo_root=repo_root, require_all=True)

    seen_features: dict[str, str] = {}
    for feature in features:
        previous = seen_features.get(feature.id)
        if previous:
            raise CompatibilityError(
                f"{feature.path}: feature ID `{feature.id}` already used by {previous}"
            )
        seen_features[feature.id] = feature.path

    return Catalog(sdks=sdks, features=features)


def load_sdks(repo_root: str = REPO_ROOT) -> list[Sdk]:
    path = os.path.join(repo_root, "capabilities", "sdks.json")
    display_path = rel(path, repo_root)
    if not os.path.exists(path):
        raise CompatibilityError(f"{display_path}: missing")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise CompatibilityError(f"{display_path}: invalid JSON: {exc}") from None

    if not isinstance(data, dict) or set(data) != {"sdks"}:
        raise CompatibilityError(f"{display_path}: expected one top-level `sdks` field")
    entries = data["sdks"]
    if not isinstance(entries, list) or not entries:
        raise CompatibilityError(f"{display_path}: `sdks` must be a non-empty list")

    sdks: list[Sdk] = []
    seen_keys: set[str] = set()
    seen_titles: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"{display_path}: sdk entry {index + 1}"
        if not isinstance(entry, dict) or set(entry) != {"key", "title"}:
            raise CompatibilityError(f"{where} must contain exactly `key` and `title`")
        key = entry["key"]
        title = entry["title"]
        if not isinstance(key, str) or ID_PATTERN.fullmatch(key) is None:
            raise CompatibilityError(f"{where} has invalid key {key!r}")
        if not isinstance(title, str) or not title.strip():
            raise CompatibilityError(f"{where} has invalid title {title!r}")
        if key in seen_keys:
            raise CompatibilityError(f"{display_path}: duplicate sdk key `{key}`")
        if title in seen_titles:
            raise CompatibilityError(f"{display_path}: duplicate sdk title `{title}`")
        seen_keys.add(key)
        seen_titles.add(title)
        sdks.append(Sdk(key=key, title=title))
    return sdks


def _split_table_row(line: str, path: str) -> list[str]:
    if not line.startswith("|") or not line.endswith("|"):
        raise CompatibilityError(
            f"{path}: SDK support table rows must start and end with `|`"
        )
    return [cell.strip() for cell in line[1:-1].split("|")]


def _parse_metadata(lines: list[str], index: int, path: str) -> dict:
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index == len(lines):
        return {}
    if lines[index] != "```json":
        raise CompatibilityError(
            f"{path}: only an optional JSON block may follow the SDK support table; "
            "the support section must be the final section"
        )

    try:
        end = lines.index("```", index + 1)
    except ValueError:
        raise CompatibilityError(
            f"{path}: SDK support metadata JSON block is not closed"
        ) from None
    try:
        metadata = json.loads("\n".join(lines[index + 1 : end]))
    except json.JSONDecodeError as exc:
        raise CompatibilityError(
            f"{path}: invalid SDK support metadata JSON: {exc}"
        ) from None
    if not isinstance(metadata, dict):
        raise CompatibilityError(f"{path}: SDK support metadata must be a JSON object")
    if any(line.strip() for line in lines[end + 1 :]):
        raise CompatibilityError(f"{path}: SDK support metadata must be the final content")
    return metadata


def load_feature(
    abs_path: str,
    sdks: list[Sdk],
    repo_root: str = REPO_ROOT,
) -> Feature | None:
    """Parse the final `# SDK support` table in one feature spec."""
    path = rel(abs_path, repo_root)
    with open(abs_path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    headings = [index for index, line in enumerate(lines) if line == SUPPORT_HEADING]
    if not headings:
        return None
    if len(headings) > 1:
        raise CompatibilityError(f"{path}: more than one `{SUPPORT_HEADING}` section")

    index = headings[0] + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index + 1 >= len(lines):
        raise CompatibilityError(f"{path}: `{SUPPORT_HEADING}` has no table")

    header = _split_table_row(lines[index], path)
    divider = _split_table_row(lines[index + 1], path)
    expected_header = ["ID", "Capability"] + [sdk.title for sdk in sdks]
    if header != expected_header:
        raise CompatibilityError(
            f"{path}: SDK columns must be `{' | '.join(expected_header)}`"
        )
    if len(divider) != len(header) or any(
        re.fullmatch(r":?-{3,}:?", cell) is None for cell in divider
    ):
        raise CompatibilityError(f"{path}: invalid SDK support table divider")

    rows: list[Row] = []
    seen_rows: set[str] = set()
    index += 2
    while index < len(lines) and lines[index].startswith("|"):
        values = _split_table_row(lines[index], path)
        if len(values) != len(header):
            raise CompatibilityError(
                f"{path}: SDK support row has {len(values)} cells; expected {len(header)}"
            )
        row_id, title, *statuses = values
        if ID_PATTERN.fullmatch(row_id) is None:
            raise CompatibilityError(f"{path}: invalid capability ID {row_id!r}")
        if row_id in seen_rows:
            raise CompatibilityError(f"{path}: duplicate capability ID `{row_id}`")
        if not title:
            raise CompatibilityError(f"{path}: capability `{row_id}` has no title")
        seen_rows.add(row_id)

        for sdk, status in zip(sdks, statuses):
            if status not in STATUSES:
                raise CompatibilityError(
                    f"{path}: `{row_id}` / `{sdk.key}` has bad status {status!r} "
                    f"(expected one of: {', '.join(STATUSES)})"
                )
        rows.append(
            Row(
                id=row_id,
                title=title,
                cells={sdk.key: Cell(status) for sdk, status in zip(sdks, statuses)},
            )
        )
        index += 1

    if not rows:
        raise CompatibilityError(f"{path}: SDK support table has no capability rows")

    metadata = _parse_metadata(lines, index, path)
    default_id = os.path.splitext(os.path.basename(abs_path))[0]
    feature_id = metadata.pop("id", default_id)
    title = metadata.pop("name", default_id.replace("-", " ").capitalize())
    if not isinstance(feature_id, str) or ID_PATTERN.fullmatch(feature_id) is None:
        raise CompatibilityError(f"{path}: invalid feature ID {feature_id!r}")
    if not isinstance(title, str) or not title.strip():
        raise CompatibilityError(
            f"{path}: SDK support metadata `name` must be a non-empty string"
        )

    return Feature(path=path, id=feature_id, title=title, metadata=metadata, rows=rows)


def load_features(
    sdks: list[Sdk] | None = None,
    *,
    repo_root: str = REPO_ROOT,
    require_all: bool = False,
) -> list[Feature]:
    sdks = sdks or load_sdks(repo_root)
    features_dir = os.path.join(repo_root, FEATURES_PATH)
    if not os.path.isdir(features_dir):
        raise CompatibilityError(f"{rel(features_dir, repo_root)}: missing")

    features: list[Feature] = []
    spec_count = 0
    for dirpath, dirnames, filenames in os.walk(features_dir):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            spec_count += 1
            abs_path = os.path.join(dirpath, name)
            feature = load_feature(abs_path, sdks, repo_root)
            if feature is None:
                if require_all:
                    raise CompatibilityError(
                        f"{rel(abs_path, repo_root)}: missing `{SUPPORT_HEADING}` section"
                    )
                continue
            features.append(feature)

    if spec_count == 0:
        raise CompatibilityError(f"{rel(features_dir, repo_root)}: no feature specs found")
    return sorted(features, key=lambda feature: feature.path)


def rel(path: str, repo_root: str = REPO_ROOT) -> str:
    return os.path.relpath(path, repo_root)
