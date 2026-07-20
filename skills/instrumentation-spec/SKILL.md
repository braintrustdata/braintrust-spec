---
name: instrumentation-spec
description: Implement and review Braintrust SDK instrumentation for LLM providers and agent frameworks. Use when adding or changing traced span structure, captured inputs and outputs, tool calls, metadata, metrics, streaming behavior, attachments, token caching, or other behavior governed by the Braintrust instrumentation specification.
---

# Braintrust Instrumentation Specification

Use [references/instrumentation-guide.md](references/instrumentation-guide.md) as the canonical specification when implementing or reviewing Braintrust SDK instrumentation.

- Read the relevant sections before changing instrumentation, and follow linked feature specifications when they apply.
- Emit only the data and fields that the specification requires or allows.
- Verify span hierarchy, payloads, metadata, metrics, streaming behavior, and error handling against the specification.
- Keep the bundled specification unchanged in consuming repositories; propose specification changes in `braintrustdata/braintrust-spec`.
