# Prompt caching

> **Providers:** Anthropic, AWS Bedrock
> **Upstream references:** [Anthropic prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [Bedrock prompt caching docs](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
> **Conformance tests:**
> - [`test/llm_span/anthropic/prompt_caching_5m.yaml`](../../test/llm_span/anthropic/prompt_caching_5m.yaml) — default 5m TTL, no beta header
> - [`test/llm_span/anthropic/prompt_caching_1h.yaml`](../../test/llm_span/anthropic/prompt_caching_1h.yaml) — extended 1h TTL, requires `extended-cache-ttl-2025-04-11` beta
> - [`test/llm_span/bedrock/prompt_caching.yaml`](../../test/llm_span/bedrock/prompt_caching.yaml) — Bedrock `cachePoint`, covering a cache write and a cache read

## Overview

Anthropic's prompt caching lets callers mark portions of a prompt with `cache_control` so those tokens are cached on the provider side and re-used across requests. Cached reads are billed at roughly 10% of the base input rate, and cache writes are billed above the base input rate, with the **write rate depending on the TTL** of the cache entry (5 minutes vs. 1 hour).

Because the two TTL tiers have different prices, Braintrust SDKs **MUST** surface Anthropic cache writes using the 5m/1h breakdown so that downstream cost tooling can attribute spend correctly. In general, SDKs **SHOULD** emit either the aggregate `prompt_cache_creation_tokens` metric or the TTL-specific creation metrics, not both. Anthropic spans **MUST** use a single representation.

For cross-provider token and estimated-cost semantics, including provider/model attribution requirements and the complete cost formula, see [Token and cost metrics](token-and-cost-metrics.md).

---

## Applicability

### Claude models

Prompt caching is available on Claude 3 Haiku, Claude 3.5 Haiku, Claude 3.5 Sonnet, Claude 3 Opus, Claude 3.7 Sonnet, and every Claude 4 / 4.5 / 4.6 model (Sonnet, Opus, Haiku variants). See the upstream reference for the authoritative list.

### Anthropic SDK versions

The nested `cache_creation` usage object is **only emitted by recent Anthropic SDKs**:

- **Python (`anthropic`):** the nested `usage.cache_creation` object with `ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens` is returned by SDK versions that track the `2024-10-22` Messages API revision and newer. Older SDKs return only the flat `cache_creation_input_tokens` field.
- **TypeScript (`@anthropic-ai/sdk`):** same story — recent releases expose `usage.cache_creation`; older ones do not.

SDK implementations **MUST** treat the nested field as optional. A missing `cache_creation` object is normal on older Anthropic SDK versions and **MUST NOT** be an error. In that case the SDK **MAY** emit `prompt_cache_creation_tokens` from the flat field and **MUST NOT** fabricate a 5m/1h split. When the nested per-TTL fields are available, Anthropic spans **MUST** emit the per-TTL metrics instead of the aggregate metric.

### 1-hour TTL beta

`cache_control.ttl: "1h"` currently requires the `extended-cache-ttl-2025-04-11` beta header. The default 5m TTL does not. SDKs wrapping the Anthropic client **MUST** pass the beta header through unchanged when the caller supplies it; they **MUST NOT** silently add or strip it.

---

## Braintrust metric mapping (Anthropic)

SDKs **MUST** emit the following span metrics. All are optional — omit any metric whose source field is absent from the Anthropic response.

| Braintrust metric                 | Source on `message.usage`                      | Notes                                      |
| --------------------------------- | ---------------------------------------------- | ------------------------------------------ |
| `prompt_cached_tokens`            | `cache_read_input_tokens`                      | Cache reads                                |
| `prompt_cache_creation_5m_tokens` | `cache_creation.ephemeral_5m_input_tokens`     | 5-minute-TTL writes only                   |
| `prompt_cache_creation_1h_tokens` | `cache_creation.ephemeral_1h_input_tokens`     | 1-hour-TTL writes only                     |
| `prompt_cache_creation_tokens`    | `cache_creation_input_tokens`                  | Legacy aggregate; emit only when no split is available |

### Totals

Anthropic's `input_tokens` field **excludes** cache-read and cache-creation tokens. SDKs **MUST** roll those back in when finalizing `prompt_tokens` and `tokens`:

```
prompt_tokens = input_tokens + cache_read_input_tokens + effective_cache_creation_tokens
tokens        = prompt_tokens + completion_tokens

where:

effective_cache_creation_tokens =
  cache_creation_input_tokens, when only the aggregate is emitted
  otherwise ephemeral_5m_input_tokens + ephemeral_1h_input_tokens
```

The split metrics are an alternative representation of cache creation tokens, not additional tokens. SDKs **MUST NOT** add `prompt_cache_creation_5m_tokens` + `prompt_cache_creation_1h_tokens` into `prompt_tokens` or `tokens` on top of `prompt_cache_creation_tokens`.

SDKs **SHOULD** emit a single representation in each span: either the aggregate `prompt_cache_creation_tokens` metric or the TTL-specific `prompt_cache_creation_5m_tokens` / `prompt_cache_creation_1h_tokens` metrics. For Anthropic responses that include the nested `cache_creation` breakdown, SDKs **MUST** emit the TTL-specific metrics and leave `prompt_cache_creation_tokens` unset.

### Consistency

If both an aggregate and a per-TTL breakdown are available from the provider, the SDK **MUST** choose one representation for the Braintrust span. For Anthropic, prefer the per-TTL breakdown whenever it is present. If the breakdown is absent, emitting the aggregate is acceptable.

### Server-side cost computation

Braintrust's cost pipeline is tolerant of all SDK shapes: aggregate only, breakdown only, or both aggregate and breakdown. SDKs should still prefer a single representation, and Anthropic spans must send only one representation. The complete cross-provider cost semantics are defined in [Token and cost metrics](token-and-cost-metrics.md).

Server cost logic computes effective creation tokens with a `max(...)` rule so both representations can be present without double-counting:

```
effective_creation_tokens =
  max(prompt_cache_creation_tokens,
      prompt_cache_creation_5m_tokens + prompt_cache_creation_1h_tokens)
```

Cache-write cost is billed per bucket using per-TTL rates only when both split rates are available and the split token sum covers the aggregate total:

```
prompt_cache_creation_5m_tokens + prompt_cache_creation_1h_tokens
  >= prompt_cache_creation_tokens
```

Otherwise, cost falls back to the legacy single-rate calculation against `effective_creation_tokens`. This preserves compatibility for aggregate-only spans and for mixed spans where the split does not account for the full aggregate total.

Consequences for SDK implementors:

- Emit the TTL-specific metrics for Anthropic when `usage.cache_creation` is present.
- For Anthropic, emit `prompt_cache_creation_tokens` only when no per-TTL breakdown is available.
- Do not synthesize missing per-TTL fields from the aggregate.
- Prefer not to emit the aggregate and per-TTL metrics together in the same span, even though the server can tolerate both.

---

## AWS Bedrock

Bedrock exposes prompt caching through the Converse API. The mechanics differ from Anthropic's in
three ways that matter to instrumentation, even when the underlying model is a Claude model.

### Request shape

Bedrock marks a cacheable prefix with a standalone `cachePoint` block appended to `system`,
`messages`, or `toolConfig.tools`, rather than attaching `cache_control` to an existing block:

```json
{
  "system": [
    { "text": "<long cacheable prefix>" },
    { "cachePoint": { "type": "default" } }
  ]
}
```

SDKs **MUST** pass `cachePoint` blocks through unchanged, and **MUST NOT** synthesize them.

### No TTL tiers

Bedrock exposes no TTL selection — there is no equivalent of Anthropic's 5m/1h split. Bedrock spans
therefore **MUST** emit the aggregate `prompt_cache_creation_tokens` metric and **MUST NOT** emit
`prompt_cache_creation_5m_tokens` or `prompt_cache_creation_1h_tokens`.

### Braintrust metric mapping

| Braintrust metric              | Source on Converse `usage` | Notes                                       |
| ------------------------------ | -------------------------- | ------------------------------------------- |
| `prompt_cached_tokens`         | `cacheReadInputTokens`     | Cache reads                                 |
| `prompt_cache_creation_tokens` | `cacheWriteInputTokens`    | Cache writes; no TTL breakdown exists        |

Bedrock also returns `cacheReadInputTokenCount` and `cacheWriteInputTokenCount` as aliases of the
same two values. SDKs **SHOULD** read the `...InputTokens` spelling and **MUST NOT** emit both.

`usage.cacheDetails` (per-checkpoint `{inputTokens, ttl}` entries) has no metric mapping: a metric
must be a single number, and the entries do not distinguish reads from writes. When captured, keep
it as provider metadata.

### Totals

Bedrock reports `inputTokens` **exclusive** of cache reads and writes, but folds both into
`totalTokens`. So `prompt_tokens` **MUST** roll the cache counts back in, while `tokens` **MUST**
preserve the provider's own total rather than recomputing it:

```
prompt_tokens    = inputTokens + cacheReadInputTokens + cacheWriteInputTokens
completion_tokens = outputTokens
tokens           = totalTokens
```

Because `totalTokens` is reported independently, it doubles as a cross-check on the sum: a correct
mapping always satisfies `tokens == prompt_tokens + completion_tokens`. A conformant implementation
run against the Bedrock conformance test produces, on the cache-write turn:

```
inputTokens 12 + cacheWriteInputTokens 1175 + outputTokens 5 == totalTokens 1192
```

and the identical relationship on the cache-read turn with the 1175 counted as a read. An SDK that
copies `inputTokens` straight into `prompt_tokens` reports 12 instead of 1187 — a ~100x undercount
that flows directly into estimated cost, and which leaves the cache metrics larger than the total
they are defined to be a subset of.

---

## Wire format

### Metrics on events

```json
{
  "metrics": {
    "prompt_tokens": 2100,
    "completion_tokens": 42,
    "tokens": 2142,
    "prompt_cached_tokens": 0,
    "prompt_cache_creation_5m_tokens": 1042,
    "prompt_cache_creation_1h_tokens": 1000
  }
}
```

# SDK support

| ID | Capability | .NET | Go | Java | JS | Python | Ruby | Rust |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cache-token-metrics | Cache read/write token metrics | unknown | unknown | unknown | unknown | unknown | unknown | unknown |
| ttl-split | 5m/1h cache-creation split | unknown | unknown | unknown | unknown | unknown | unknown | unknown |
| bedrock-cachepoint | Bedrock `cachePoint` blocks | unknown | unknown | unknown | unknown | unknown | unknown | unknown |
| beta-header-passthrough | 1h TTL beta header passthrough | unknown | unknown | unknown | unknown | unknown | unknown | unknown |

```json
{
  "id": "prompt-cache",
  "name": "Prompt caching",
  "category": "Token & cost",
  "providers": ["anthropic", "bedrock"]
}
```
