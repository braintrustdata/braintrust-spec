# SDK compatibility catalog

SDK support is tracked in hand-maintained Markdown tables. The current values are fabricated examples and must not be treated as real compatibility data.

## Spec format

Every Markdown spec under `skills/instrumentation-spec/references/features/` must end with a `# SDK support` section:

````markdown
# SDK support

| ID | Capability | .NET | Go | Java | JS | Python | Ruby | Rust |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| external-file-refs | External file references | no | partial | yes | yes | yes | no | no |

```json
{
  "id": "attachments",
  "name": "Attachments",
  "category": "Multimodal",
  "providers": ["openai", "anthropic"]
}
```
````

The table is both the human-facing support matrix and the machine-readable source of truth. Its SDK columns must exactly match the unique keys and titles in `capabilities/sdks.json`.

The JSON block after the table is optional metadata. Without it, the filename stem is used as the feature ID and a humanized stem is used as its name (`prompt-cache.md` becomes `prompt-cache` / “Prompt cache”). `id` and `name` may override those defaults; all other JSON properties are preserved as metadata.

Each capability row has a stable ID, a display name, and exactly one status per known SDK:

| Status | Meaning |
| --- | --- |
| `yes` | Shipped |
| `partial` | Partially implemented |
| `no` | Applicable but not implemented |
| `unknown` | Not yet checked |
| `n/a` | Not applicable to this SDK |

The support section must be the final section in the file. When present, the metadata block must be its final content.

## Programmatic API

`scripts/compatibility.py` is the base component for consumers:

```python
from scripts.compatibility import load_catalog

catalog = load_catalog()
for feature in catalog.features:
    for capability in feature.rows:
        print(feature.id, capability.id, capability.cells["python"].status)
```

`load_catalog()` validates the SDK master list, requires every feature spec to have a support table, and returns features in deterministic source-path order.

## Commands

```bash
make test                                      # all checks, including CSV freshness
make compatibility-csv                         # regenerate capabilities/compatibility.csv
mise exec -- python scripts/validate-capabilities.py     # validate the complete catalog
mise exec -- python scripts/render-parity.py             # aggregate Markdown
mise exec -- python scripts/render-parity.py --sdk java  # one SDK checklist
mise exec -- python scripts/render-parity.py --json      # JSON representation
```

CI runs `make test` for every pull request and push to `main`.
