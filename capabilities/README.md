# SDK compatibility catalog

SDK support is tracked in YAML blocks in the feature specs. The current values are fabricated examples and must not be treated as real compatibility data.

## Spec format

Every Markdown spec under `skills/instrumentation-spec/references/features/` must end with a `# SDK support` section:

````markdown
# SDK support

```yaml
id: attachments
name: Attachments
category: Multimodal
providers: [openai, anthropic]
support:
  external-file-refs:
    dotnet: "no"
    go: "partial"
    java: "yes"
    js: "yes"
    python: "yes"
    ruby: "no"
    rust: "no"
```
````

The single fenced `yaml` block is the source of truth. `support` is a non-empty mapping from stable lowercase kebab-case capability IDs to SDK/status mappings. Each capability must contain exactly the SDK **keys** in `capabilities/sdks.json`, in canonical order. Use `dotnet` and `js`, not the display titles `.NET` and `JS`.

Feature metadata lives alongside `support`. The optional `id` and `name` fields override the filename-based defaults (`prompt-cache.md` becomes `prompt-cache` / “Prompt cache”). Other top-level properties are preserved as JSON-compatible metadata, including `category` and `providers`. Capability display labels in generated Markdown and CSV are humanized from their IDs; the YAML does not contain a separate label field.

Statuses are strings. Quote them, particularly `"yes"` and `"no"`, which YAML 1.1 otherwise interprets as booleans:

| Status | Meaning |
| --- | --- |
| `yes` | Shipped |
| `partial` | Partially implemented |
| `no` | Applicable but not implemented |
| `unknown` | Not yet checked |
| `n/a` | Not applicable to this SDK |

The support section must be the final section, containing only one fenced `yaml` block. Duplicate mapping keys, aliases, non-string statuses, missing/extra/out-of-order SDK keys, and trailing content are rejected. Use plain or quoted inline scalar values for statuses so automated assessments can update them without reformatting surrounding YAML. Legacy Markdown tables and JSON metadata blocks are no longer accepted.

## Programmatic API

`scripts/compatibility.py` is the base component for consumers:

```python
from scripts.compatibility import load_catalog

catalog = load_catalog()
for feature in catalog.features:
    for capability in feature.rows:
        print(feature.id, capability.id, capability.cells["python"].status)
```

`load_catalog()` validates the SDK master list, requires every feature spec to have a YAML support block, and returns features in deterministic source-path order. The assessment writer uses `update_support_statuses()` from the same module to replace only requested non-yes status scalars, preserving surrounding formatting, comments, and metadata.

## Commands

Python is pinned by mise. PyYAML is pinned in `requirements.txt` and installed into the project-local `.venv`. Run `mise trust`, `mise install`, and `mise run install-deps` before ad hoc commands. Both Make targets below install dependencies automatically.

```bash
make test                                      # unit tests and catalog validation
make compatibility-csv                         # regenerate capabilities/compatibility.csv
mise exec -- python scripts/validate-capabilities.py     # validate the complete catalog
mise exec -- python scripts/render-parity.py             # aggregate Markdown
mise exec -- python scripts/render-parity.py --sdk java  # one SDK checklist
mise exec -- python scripts/render-parity.py --json      # JSON representation
```

CI runs `make test` for every pull request and push to `main`.

## Automated assessments

The **Assess SDK compatibility** workflow (`.github/workflows/assess-compatibility.yml`)
investigates every cell not marked `yes` and opens a PR on
`automation/sdk-compatibility`. It runs at 06:17 UTC on the 1st and 15th of each
month and assesses the default branch. **Run workflow** in GitHub Actions runs it
on demand against the selected branch, which is useful for testing workflow changes.
Runs from other branches only upload artifacts; they never touch the PR.

Each default-branch run rebuilds the PR branch from the current default branch plus
its changes, updating any still-open PR in place (or closing it if nothing changed).
Unmerged results are not carried forward; the next run reassesses those cells. If
some SDKs failed to reassess and a PR is already open, the run leaves that PR
unchanged rather than dropping its results for those SDKs.

### Setup

- Add the `OPENAI_API_KEY` Actions secret. Research runs the pinned Codex CLI and
  model (set in the workflow) and incurs model usage charges. Only the local
  `codex-responses-api-proxy` process receives the key; Codex and the research
  agent talk to that proxy and never see it.
- Allow GitHub Actions to create pull requests in the repository's Actions
  settings. The publishing job requests `contents: write` and `pull-requests: write`.
- Optionally add `COMPATIBILITY_PR_TOKEN`, a GitHub App token or fine-grained PAT
  with repository contents and pull-request write permissions. Without it, the
  workflow uses `GITHUB_TOKEN`; PRs created with that token do not trigger ordinary
  `pull_request` workflows. The publishing job still runs `make test` before
  opening the PR.

### Research and review

`scripts/assess_compatibility.py` uses `load_catalog()` to enumerate `no`, `partial`,
`unknown`, and `n/a` cells, then prepares one read-only research job per SDK.
SDK repositories are mapped in that script; adding an SDK to the catalog also
requires adding its repository mapping. Cells already marked `yes` are never
reassessed or overwritten. Each request includes the starting `current_status`;
results are rejected if the eligible cells or their statuses changed meanwhile.

Research targets the latest GitHub release, falling back to the latest repository
tag when no GitHub release exists, and records the exact commit SHA. A tag alone
does not prove publication: the agent must establish shipped support or return
an inconclusive result. Inaccessible repositories, missing tags/releases, incomplete results,
and invalid citations fail that SDK's job rather than being interpreted as `no`.

Codex runs directly rather than through `openai/codex-action`, which froze runners
after research finished (timeouts never fired and logs were lost). Codex output
goes to a file uploaded as the `codex-diagnostics-<sdk>` artifact, and a hard
timeout bounds each SDK's research.

The agent reads the full feature spec and relevant SDK implementations and tests.
It returns `yes`, `partial`, `no`, or `n/a` only with a rationale and source
citations; an inconclusive `unknown` result preserves the existing catalog value.
A previously assessed `no`, `partial`, or `n/a` cell can change when the current SDK
source supports a different conclusion, including newly implemented support.
An unchanged conclusion produces no edit. A missing keyword is not
evidence of absent support. The validator requires a decision for every requested
cell and checks cited files and line ranges against the pinned SDK commit.
These checks verify the citations, not the correctness of the model's conclusions.

Only validated JSON results cross into the separate publishing job; the research
agent has no repository write token. The publisher applies changed non-yes assessments,
regenerates the CSV, runs the checks, and proposes the changes for human review.
The PR changes only the `support` statuses in the feature specs. Rationales, SDK
revisions, and source citations for every decision, including inconclusive ones,
are in the run's `assessment-<sdk>` artifacts, retained for 30 days.
If no statuses change, no PR is created.

The publisher runs even when some SDK jobs fail or time out, applying results from
the SDKs that validated. SDKs without a result are listed in the PR description and
the run is marked failed; their cells are left unchanged.

Existing prototype values are not made authoritative by this workflow. The
fabricated-data caveat remains until those values receive a real assessment.
