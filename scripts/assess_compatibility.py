"""Prepare SDK research, validate evidence, and reassess non-yes statuses."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

from compatibility import REPO_ROOT, STATUSES, load_catalog, update_support_statuses

SDK_REPOSITORIES = {
    key: f"braintrustdata/braintrust-sdk-{name}"
    for key, name in {
        "dotnet": "dotnet", "go": "go", "java": "java", "js": "javascript",
        "python": "python", "ruby": "ruby", "rust": "rust",
    }.items()
}
# GitHub cron cannot express a fortnight. Gate a weekly Monday trigger by elapsed
# weeks from a fixed Monday, rather than ISO week parity (which breaks at year-end).
SCHEDULE_ANCHOR = date(2026, 9, 28)


def scheduled_week(today: date) -> bool:
    return ((today - SCHEDULE_ANCHOR).days // 7) % 2 == 0


def non_yes_cells(root: str = REPO_ROOT) -> dict[str, list[dict]]:
    catalog = load_catalog(root)
    missing = {sdk.key for sdk in catalog.sdks} - SDK_REPOSITORIES.keys()
    if missing:
        raise ValueError(f"Missing SDK repository mappings: {sorted(missing)}")
    result = {}
    for sdk in catalog.sdks:
        cells = [
            {"feature": feature.id, "capability": row.id, "title": row.title,
             "spec": feature.path, "current_status": row.cells[sdk.key].status}
            for feature in catalog.features for row in feature.rows
            if row.cells[sdk.key].status != "yes"
        ]
        if cells:
            result[sdk.key] = cells
    return result


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def release_ref(repository: str) -> tuple[str, str]:
    response = subprocess.run(
        ["gh", "api", f"repos/{repository}/releases/latest"],
        text=True, capture_output=True,
    )
    if response.returncode == 0:
        return json.loads(response.stdout)["tag_name"], "release"
    # Some SDKs publish packages/tags without GitHub Releases. Do not silently
    # fall back on authentication, rate-limit, or server errors.
    error = json.loads(response.stdout)
    if str(error.get("status")) != "404":
        raise ValueError(f"Cannot resolve release for {repository}: {response.stderr}")
    tags = json.loads(command("gh", "api", f"repos/{repository}/tags?per_page=1"))
    if not tags:
        raise ValueError(f"No release or tag available for {repository}")
    return tags[0]["name"], "tag"


def prepare(sdk: str, directory: Path, root: str = REPO_ROOT) -> None:
    cells = non_yes_cells(root)[sdk]
    repository = SDK_REPOSITORIES[sdk]
    ref, kind = release_ref(repository)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "source"
    subprocess.run(
        ["git", "clone", "--depth=1", "--branch", ref, "--",
         f"https://github.com/{repository}.git", str(source)],
        check=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    revision = command("git", "-C", str(source), "rev-parse", "HEAD")
    write_json(directory / "request.json", {
        "sdk": sdk, "repository": repository, "ref": ref, "ref_kind": kind,
        "revision": revision, "capabilities": cells,
    })


def validate(request: dict, result: dict, expected: list[dict],
             source: Path | None = None) -> list[dict]:
    sdk = request["sdk"]
    if request["repository"] != SDK_REPOSITORIES[sdk]:
        raise ValueError("Unexpected SDK repository")
    if not re.fullmatch(r"[0-9a-f]{40}", request["revision"]):
        raise ValueError("Expected a full SDK commit SHA")
    if request["capabilities"] != expected:
        raise ValueError("Assessment request does not match current non-yes cells and statuses")
    wanted = {(cell["feature"], cell["capability"]) for cell in expected}
    seen = set()
    assessments = result["assessments"]
    for item in assessments:
        key = (item["feature"], item["capability"])
        if key not in wanted or key in seen:
            raise ValueError(f"Unexpected or duplicate assessment: {key}")
        seen.add(key)
        if item["status"] not in STATUSES:
            raise ValueError(f"Invalid assessment status: {item['status']}")
        if not isinstance(item["rationale"], str) or not item["rationale"].strip():
            raise ValueError(f"Missing rationale: {key}")
        if not isinstance(item["evidence"], list):
            raise ValueError(f"Invalid evidence: {key}")
        if item["status"] != "unknown" and not item["evidence"]:
            raise ValueError(f"Known status requires source evidence: {key}")
        for evidence in item["evidence"]:
            path = Path(evidence["path"])
            start, end = evidence["start_line"], evidence["end_line"]
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(f"Unsafe evidence path: {path}")
            if type(start) is not int or type(end) is not int or not 1 <= start <= end:
                raise ValueError(f"Invalid evidence line range: {path}")
            if source is not None:
                resolved = (source / path).resolve()
                if not resolved.is_relative_to(source.resolve()):
                    raise ValueError(f"Evidence escapes SDK checkout: {path}")
                # Only tracked files at the pinned commit qualify as evidence.
                content = subprocess.check_output(
                    ["git", "-C", str(source), "show",
                     f"{request['revision']}:{path.as_posix()}"], text=True,
                )
                if end > len(content.splitlines()):
                    raise ValueError(f"Evidence line range exceeds source: {path}")
    if seen != wanted:
        raise ValueError(f"Missing assessments: {sorted(wanted - seen)}")
    return assessments


def apply(results: Path, report: Path, root: str = REPO_ROOT) -> int:
    expected = non_yes_cells(root)
    requests = sorted(results.glob("*/request.json"))
    seen = set()
    updates = {}
    audit = []
    # Validate all results before touching any spec. Never accept a partial run.
    for path in requests:
        request = json.loads(path.read_text(encoding="utf-8"))
        sdk = request["sdk"]
        if sdk not in expected or sdk in seen:
            raise ValueError(f"Unexpected or duplicate SDK result: {sdk}")
        seen.add(sdk)
        result = json.loads(path.with_name("result.json").read_text(encoding="utf-8"))
        assessments = validate(request, result, expected[sdk])
        for item in assessments:
            for evidence in item["evidence"]:
                evidence["url"] = (
                    f"https://github.com/{request['repository']}/blob/"
                    f"{request['revision']}/{quote(evidence['path'], safe='/')}"
                    f"#L{evidence['start_line']}-L{evidence['end_line']}"
                )
        audit.append({**request, "assessments": assessments})
        prior = {
            (cell["feature"], cell["capability"]): cell["current_status"]
            for cell in expected[sdk]
        }
        for item in assessments:
            previous = prior[(item["feature"], item["capability"])]
            if item["status"] not in ("unknown", previous):
                updates[(item["feature"], item["capability"], sdk)] = item["status"]
    if seen != set(expected):
        raise ValueError(f"Missing SDK results: {sorted(set(expected) - seen)}")
    catalog = load_catalog(root)
    pending = {}
    for feature in catalog.features:
        changes = {(row.id, sdk.key): updates[(feature.id, row.id, sdk.key)]
                   for row in feature.rows for sdk in catalog.sdks
                   if (feature.id, row.id, sdk.key) in updates}
        if not changes:
            continue
        path = Path(root) / feature.path
        pending[path] = update_support_statuses(
            path.read_text(encoding="utf-8"), changes, feature.path,
        )
    for path, text in pending.items():
        path.write_text(text, encoding="utf-8")
    if updates:
        write_json(report, {
            "assessed_at": datetime.now(timezone.utc).isoformat(),
            "note": "Automated source assessment; human review required. Other catalog values may still be prototype data.",
            "sdks": audit,
        })
    counts = Counter(updates.values())
    print(f"Updated {len(updates)} non-yes cells: {dict(counts)}")
    return len(updates)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--event", choices=["schedule", "workflow_dispatch"], required=True)
    for operation in ("prepare", "validate"):
        sub = commands.add_parser(operation)
        sub.add_argument("--sdk", choices=SDK_REPOSITORIES, required=True)
        sub.add_argument("--directory", type=Path, required=True)
    update = commands.add_parser("apply")
    update.add_argument("--results", type=Path, required=True)
    update.add_argument("--report", type=Path, default=Path(REPO_ROOT) / "capabilities/assessment.json")
    args = parser.parse_args()
    if args.operation == "plan":
        due = args.event == "workflow_dispatch" or scheduled_week(datetime.now(timezone.utc).date())
        matrix = {"sdk": list(non_yes_cells()) if due else []}
        values = f"enabled={str(bool(matrix['sdk'])).lower()}\nmatrix={json.dumps(matrix)}\n"
        print(values, end="")
        if output := os.environ.get("GITHUB_OUTPUT"):
            with open(output, "a", encoding="utf-8") as handle:
                handle.write(values)
    elif args.operation == "prepare":
        prepare(args.sdk, args.directory)
    elif args.operation == "validate":
        request = json.loads((args.directory / "request.json").read_text(encoding="utf-8"))
        if request["sdk"] != args.sdk:
            raise ValueError("SDK request mismatch")
        result = json.loads((args.directory / "result.json").read_text(encoding="utf-8"))
        validate(request, result, non_yes_cells()[args.sdk], args.directory / "source")
        print(f"Validated all {len(result['assessments'])} assessments for {args.sdk}")
    else:
        apply(args.results, args.report)


if __name__ == "__main__":
    main()
