# Braintrust Spec

Cross language specs for implementing a Braintrust SDK.

Contains:

- `skills/instrumentation-spec/` — installable Braintrust instrumentation skill
  - `skills/instrumentation-spec/references/` — markdown specs and guidance
  - `skills/instrumentation-spec/references/features/` — feature-specific specs, designs, and API contracts
- `test/` — yaml end-to-end test cases and assertions
- `semconv/` — yaml cross-language constants such as envars and span attributes

## Consume the instrumentation skill

From a repository initialized with [dotagents](https://docs.sentry.io/ai/dotagents/), run:

```bash
npx @sentry/dotagents add braintrustdata/braintrust-spec instrumentation-spec
```

This adds the following dependency to `agents.toml`:

```toml
[[skills]]
name = "instrumentation-spec"
source = "braintrustdata/braintrust-spec"
```
