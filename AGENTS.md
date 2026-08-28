# Braintrust Spec agent instructions

This repository contains cross-language specifications for Braintrust SDK behavior. Read the relevant spec before changing it, and keep compatibility data synchronized with specification changes.

## Tool setup with mise

This repository uses [`mise`](https://mise.jdx.dev/) to pin Python and run project tasks. Do not rely on an arbitrary system Python.

1. Install mise using the [official installation instructions](https://mise.jdx.dev/getting-started.html).
2. Review `mise.toml`, then trust it with `mise trust`.
3. Install the pinned tools with `mise install`.
4. Optionally activate mise in your shell using the instructions printed by `mise activate` for your shell.

Make targets delegate to mise, so normal development does not require shell activation. For an ad hoc Python command, use `mise exec -- python <args>`.

## Commands

- Run all checks: `make test` (or `mise run test`)
- Regenerate the compatibility spreadsheet: `make compatibility-csv` (or `mise run compatibility-csv`)
- Render compatibility as Markdown or JSON: `mise exec -- python scripts/render-parity.py [--json]`

Always run `make compatibility-csv` after changing compatibility data, then run `make test` before finishing.

## SDK compatibility tables

Detailed format documentation lives in [`capabilities/README.md`](capabilities/README.md). The following rules are mandatory:

1. Every Markdown file under `skills/instrumentation-spec/references/features/` must end with exactly one `# SDK support` section.
2. Keep the table updated when adding, removing, or changing capabilities in a spec.
3. Use stable lowercase kebab-case feature and capability IDs. Do not rename an existing ID merely to improve wording.
4. Every capability row must contain exactly one status for every SDK in `capabilities/sdks.json`, in canonical SDK order.
5. Allowed statuses are `yes`, `partial`, `no`, `unknown`, and `n/a`.
6. Use `unknown` when support has not been assessed. Do not guess `yes` or treat an unverified SDK as `no`.
7. Change the SDK master list only when adding, removing, or renaming a supported SDK. Updating it requires updating every compatibility table.
8. Optional feature metadata belongs in the final fenced `json` block after the table. Prefer the existing categories: Configuration, Datasets, Evals, LLM APIs, Metadata, Multimodal, Token & cost, and Tracing.
9. Do not edit `capabilities/compatibility.csv` by hand; regenerate it with `make compatibility-csv`.

The current compatibility values are prototype data and may be fabricated. Preserve that caveat until a real assessment replaces them.

## Programmatic consumers

`scripts/compatibility.py` is the base compatibility API. Components should call `load_catalog()` rather than parsing Markdown or `sdks.json` independently. The loader validates the complete repository before returning SDKs, features, metadata, capabilities, and statuses.
