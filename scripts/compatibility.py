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

import yaml

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


class _SupportLoader(yaml.SafeLoader):
    """Reject YAML constructs that could hide or couple compatibility entries."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("aliases are not allowed in SDK support data")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise yaml.YAMLError("mapping keys must be strings")
            if key in mapping:
                raise yaml.YAMLError(f"duplicate mapping key `{key}`")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _parse_support(text: str, path: str) -> tuple[dict, yaml.MappingNode, int] | None:
    lines = text.splitlines(keepends=True)
    headings = [
        index for index, line in enumerate(lines)
        if line.rstrip("\r\n") == SUPPORT_HEADING
    ]
    if not headings:
        return None
    if len(headings) > 1:
        raise CompatibilityError(f"{path}: more than one `{SUPPORT_HEADING}` section")
    start = headings[0] + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start == len(lines) or lines[start].rstrip("\r\n") != "```yaml":
        raise CompatibilityError(f"{path}: SDK support must contain one fenced `yaml` block")
    end = start + 1
    while end < len(lines) and lines[end].rstrip("\r\n") != "```":
        end += 1
    if end == len(lines):
        raise CompatibilityError(f"{path}: SDK support YAML block is not closed")
    if any(line.strip() for line in lines[end + 1:]):
        raise CompatibilityError(f"{path}: SDK support YAML must be the final content")

    loader = _SupportLoader("".join(lines[start + 1:end]))
    try:
        node = loader.get_single_node()
        if not isinstance(node, yaml.MappingNode):
            raise CompatibilityError(f"{path}: SDK support YAML must be a mapping")
        data = loader.construct_document(node)
        if not isinstance(data, dict):
            raise CompatibilityError(f"{path}: SDK support YAML must be a mapping")
    except yaml.YAMLError as exc:
        raise CompatibilityError(f"{path}: invalid SDK support YAML: {exc}") from None
    finally:
        loader.dispose()
    return data, node, sum(len(line) for line in lines[:start + 1])


def load_feature(
    abs_path: str,
    sdks: list[Sdk],
    repo_root: str = REPO_ROOT,
) -> Feature | None:
    """Parse the final fenced YAML SDK support block in one feature spec."""
    path = rel(abs_path, repo_root)
    with open(abs_path, encoding="utf-8") as handle:
        parsed = _parse_support(handle.read(), path)
    if parsed is None:
        return None
    metadata, _, _ = parsed
    support = metadata.pop("support", None)
    if not isinstance(support, dict) or not support:
        raise CompatibilityError(f"{path}: `support` must be a non-empty mapping")

    expected_keys = [sdk.key for sdk in sdks]
    rows = []
    for row_id, statuses in support.items():
        if ID_PATTERN.fullmatch(row_id) is None:
            raise CompatibilityError(f"{path}: invalid capability ID {row_id!r}")
        if not isinstance(statuses, dict) or list(statuses) != expected_keys:
            raise CompatibilityError(
                f"{path}: `{row_id}` must contain exactly these SDK keys in order: "
                f"{', '.join(expected_keys)}"
            )
        for sdk, status in statuses.items():
            if not isinstance(status, str) or status not in STATUSES:
                raise CompatibilityError(
                    f"{path}: `{row_id}` / `{sdk}` has invalid status {status!r}; "
                    f"expected a string from {', '.join(STATUSES)} (quote yes/no)"
                )
        rows.append(Row(
            id=row_id,
            title=row_id.replace("-", " ").capitalize(),
            cells={sdk: Cell(status) for sdk, status in statuses.items()},
        ))

    default_id = os.path.splitext(os.path.basename(abs_path))[0]
    feature_id = metadata.pop("id", default_id)
    title = metadata.pop("name", default_id.replace("-", " ").capitalize())
    if not isinstance(feature_id, str) or ID_PATTERN.fullmatch(feature_id) is None:
        raise CompatibilityError(f"{path}: invalid feature ID {feature_id!r}")
    if not isinstance(title, str) or not title.strip():
        raise CompatibilityError(f"{path}: SDK support `name` must be a non-empty string")
    try:
        json.dumps(metadata, allow_nan=False)
    except (TypeError, ValueError):
        raise CompatibilityError(f"{path}: feature metadata must contain JSON-compatible values") from None
    return Feature(path=path, id=feature_id, title=title, metadata=metadata, rows=rows)


def update_support_statuses(
    text: str, changes: dict[tuple[str, str], str], path: str
) -> str:
    """Replace only requested non-yes YAML scalars, preserving surrounding text."""
    parsed = _parse_support(text, path)
    if parsed is None:
        raise CompatibilityError(f"{path}: missing `{SUPPORT_HEADING}` section")
    data, root, offset = parsed
    support = data.get("support")
    if not isinstance(support, dict) or not support:
        raise CompatibilityError(f"{path}: `support` must be a non-empty mapping")
    support_node = next(value for key, value in root.value if key.value == "support")
    nodes = {
        (capability.value, sdk.value): value
        for capability, sdks in support_node.value
        if isinstance(sdks, yaml.MappingNode)
        for sdk, value in sdks.value
    }
    edits = []
    for (capability, sdk), status in changes.items():
        if not isinstance(status, str) or status not in STATUSES:
            raise CompatibilityError(f"{path}: invalid replacement status {status!r}")
        node = nodes.get((capability, sdk))
        if node is None or support[capability][sdk] not in ("no", "partial", "unknown", "n/a"):
            raise CompatibilityError(
                f"{path}: `{capability}` / `{sdk}` is not a non-yes SDK status"
            )
        if node.style not in (None, "'", '"'):
            raise CompatibilityError(f"{path}: status updates require plain or quoted scalars")
        edits.append((offset + node.start_mark.index, offset + node.end_mark.index, json.dumps(status)))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


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
