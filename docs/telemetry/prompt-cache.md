# Prompt caching

> **Provider:** Anthropic
> **Upstream reference:** [Anthropic prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
> **Conformance tests:**
> - [`test/llm_span/anthropic/prompt_caching_5m.yaml`](../../test/llm_span/anthropic/prompt_caching_5m.yaml) — default 5m TTL, no beta header
> - [`test/llm_span/anthropic/prompt_caching_1h.yaml`](../../test/llm_span/anthropic/prompt_caching_1h.yaml) — extended 1h TTL, requires `extended-cache-ttl-2025-04-11` beta

## Overview

Anthropic's prompt caching lets callers mark portions of a prompt with `cache_control` so those tokens are cached on the provider side and re-used across requests. Cached reads are billed at roughly 10% of the base input rate, and cache writes are billed above the base input rate, with the **write rate depending on the TTL** of the cache entry (5 minutes vs. 1 hour).

Because the two TTL tiers have different prices, Braintrust SDKs **MUST** surface Anthropic cache writes using the 5m/1h breakdown so that downstream cost tooling can attribute spend correctly. SDKs **MUST NOT** emit the aggregate `prompt_cache_creation_tokens` metric in the same span as the TTL-specific creation metrics.

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

## Braintrust metric mapping

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

SDKs **MUST NOT** emit both representations in the same span: send either the aggregate `prompt_cache_creation_tokens` metric or the TTL-specific `prompt_cache_creation_5m_tokens` / `prompt_cache_creation_1h_tokens` metrics. For Anthropic responses that include the nested `cache_creation` breakdown, emit the TTL-specific metrics and leave `prompt_cache_creation_tokens` unset.

### Consistency

If both an aggregate and a per-TTL breakdown are available from the provider, the SDK **MUST** choose one representation for the Braintrust span. For Anthropic, prefer the per-TTL breakdown whenever it is present. If the breakdown is absent, emitting the aggregate is acceptable.

### Server-side cost computation

Braintrust's cost pipeline accepts either SDK shape — aggregate only or breakdown only.

When the breakdown is present, cache-write cost is billed per bucket using the per-TTL rates. When the breakdown is absent, cost falls back to the legacy single-rate calculation against `prompt_cache_creation_tokens`.

Consequences for SDK implementors:

- Emit the TTL-specific metrics for Anthropic when `usage.cache_creation` is present.
- Emit `prompt_cache_creation_tokens` only when no per-TTL breakdown is available.
- Do not synthesize missing per-TTL fields from the aggregate.
- Do not emit the aggregate and per-TTL metrics together in the same span.

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
