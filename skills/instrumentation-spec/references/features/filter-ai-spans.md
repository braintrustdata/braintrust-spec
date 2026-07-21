# Filter AI Spans Feature Spec

## Overview

When enabled, the Braintrust SDK filters out non-AI spans before export, keeping only spans that originate from AI/LLM instrumentation. This reduces noise and cost when the SDK is used alongside other tracing instrumentation (e.g. HTTP, database, framework spans).

## Configuration

The feature is disabled by default. It can be enabled via environment variable or programmatically depending on the SDK.

### Environment variable

```
BRAINTRUST_FILTER_AI_SPANS=true
```

### Python

```python
from braintrust.otel import BraintrustSpanProcessor

processor = BraintrustSpanProcessor(filter_ai_spans=True)
```

### TypeScript

```typescript
import { BraintrustSpanProcessor } from "@braintrust/otel";

// Via the span processor
new BraintrustSpanProcessor({ filterAISpans: true });

// Or via the exporter directly
import { BraintrustExporter } from "@braintrust/otel";
new BraintrustExporter({ filterAISpans: true });
```

## Behavior

When enabled, the SDK inspects each span's attributes **when the span ends** (i.e. after all attributes have been set) and applies a prefix-based allowlist to decide whether to export or discard the span.

### Allowed attribute prefixes

| Prefix        | Source                         |
|---------------|--------------------------------|
| `gen_ai.`     | GenAI semantic conventions     |
| `braintrust.` | Braintrust SDK                 |
| `llm.`        | Common LLM instrumentation     |
| `ai.`         | Vercel AI SDK and similar      |
| `traceloop.`  | Traceloop/OpenLLMetry          |

### Filtering decision

- If **any** attribute key on the span starts with one of the allowed prefixes, the span is **kept** and exported to Braintrust.
- Otherwise, the span is **silently discarded**.

The match is strictly prefix-based — an attribute key like `zbraintrust.foo` does not match the `braintrust.` prefix.

### Why filter at span end, not span start?

AI instrumentation libraries commonly add attributes to spans *after* the span has been started (e.g. after an LLM call completes and the model name, token counts, etc. are known). Filtering at span end ensures all attributes are available for the decision.

## Implementation note

OpenTelemetry-based SDKs might implement this as a span processor filter in `onEnd()`, rather than an OTel `Sampler` (Samplers run at span start time when AI-relevant attributes may not yet be present).
