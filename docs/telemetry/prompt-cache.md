# Prompt caching

> **Provider:** Anthropic
> **Upstream reference:** [Anthropic prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
> **Conformance tests:**
> - [`test/llm_span/anthropic/prompt_caching_5m.yaml`](../../test/llm_span/anthropic/prompt_caching_5m.yaml) — default 5m TTL, no beta header
> - [`test/llm_span/anthropic/prompt_caching_1h.yaml`](../../test/llm_span/anthropic/prompt_caching_1h.yaml) — extended 1h TTL, requires `extended-cache-ttl-2025-04-11` beta

## Overview

Anthropic's prompt caching lets callers mark portions of a prompt with `cache_control` so those tokens are cached on the provider side and re-used across requests. Cached reads are billed at roughly 10% of the base input rate, and cache writes are billed above the base input rate, with the **write rate depending on the TTL** of the cache entry (5 minutes vs. 1 hour).

Because the two TTL tiers have different prices, Braintrust SDKs **MUST** surface the 5m/1h breakdown as separate metrics so that downstream cost tooling can attribute spend correctly.

---

## Applicability

### Claude models

Prompt caching is available on Claude 3 Haiku, Claude 3.5 Haiku, Claude 3.5 Sonnet, Claude 3 Opus, Claude 3.7 Sonnet, and every Claude 4 / 4.5 / 4.6 model (Sonnet, Opus, Haiku variants). See the upstream reference for the authoritative list.

### Anthropic SDK versions

The nested `cache_creation` usage object is **only emitted by recent Anthropic SDKs**:

- **Python (`anthropic`):** the nested `usage.cache_creation` object with `ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens` is returned by SDK versions that track the `2024-10-22` Messages API revision and newer. Older SDKs return only the flat `cache_creation_input_tokens` field.
- **TypeScript (`@anthropic-ai/sdk`):** same story — recent releases expose `usage.cache_creation`; older ones do not.

SDK implementations **MUST** treat the nested field as optional. A missing `cache_creation` object is normal on older Anthropic SDK versions and **MUST NOT** be an error. In that case the SDK **MUST** still emit `prompt_cache_creation_tokens` from the flat field and **MUST NOT** fabricate a 5m/1h split.

### 1-hour TTL beta

`cache_control.ttl: "1h"` currently requires the `extended-cache-ttl-2025-04-11` beta header. The default 5m TTL does not. SDKs wrapping the Anthropic client **MUST** pass the beta header through unchanged when the caller supplies it; they **MUST NOT** silently add or strip it.

---

## Braintrust metric mapping

SDKs **MUST** emit the following span metrics. All are optional — omit any metric whose source field is absent from the Anthropic response.

| Braintrust metric                 | Source on `message.usage`                      | Notes                            |
| --------------------------------- | ---------------------------------------------- | -------------------------------- |
| `prompt_cached_tokens`            | `cache_read_input_tokens`                      | Cache reads                      |
| `prompt_cache_creation_tokens`    | `cache_creation_input_tokens`                  | Total cache writes, all TTLs     |
| `prompt_cache_creation_5m_tokens` | `cache_creation.ephemeral_5m_input_tokens`     | 5-minute-TTL writes only         |
| `prompt_cache_creation_1h_tokens` | `cache_creation.ephemeral_1h_input_tokens`     | 1-hour-TTL writes only           |

### Totals

Anthropic's `input_tokens` field **excludes** cache-read and cache-creation tokens. SDKs **MUST** roll those back in when finalizing `prompt_tokens` and `tokens`:

```
prompt_tokens = input_tokens + cache_read_input_tokens + cache_creation_input_tokens
tokens        = prompt_tokens + completion_tokens
```

The split metrics are a **breakdown** of the total, not additional tokens. SDKs **MUST NOT** add `prompt_cache_creation_5m_tokens` + `prompt_cache_creation_1h_tokens` into `prompt_tokens` or `tokens` on top of `prompt_cache_creation_tokens` — the TTL-tagged tokens are already counted inside `cache_creation_input_tokens`.

Emitting all three metrics in the same event (total + 5m + 1h) is **expected and safe**. See [Server-side cost computation](#server-side-cost-computation) below for how Braintrust handles the three-way relationship.

### Consistency

When both the total and the breakdown are present, the following invariant **SHOULD** hold:

```
prompt_cache_creation_5m_tokens + prompt_cache_creation_1h_tokens
  == prompt_cache_creation_tokens
```

Anthropic's `cache_creation_input_tokens` is defined as the sum of the per-TTL buckets, so equality is the normal case. If Anthropic returns inconsistent values, the SDK **MUST** pass them through unchanged. Correctness of this invariant is the provider's responsibility, not the SDK's.

### Server-side cost computation

Braintrust's cost pipeline is tolerant of all three SDK shapes — total only, breakdown only, or both — using an effective-creation-tokens rule:

```
effective_creation_tokens =
  max(prompt_cache_creation_tokens,
      prompt_cache_creation_5m_tokens + prompt_cache_creation_1h_tokens)

uncached_prompt_tokens =
  prompt_tokens - prompt_cached_tokens - effective_creation_tokens
```

Cache-write cost is then billed per bucket when the breakdown is present (using per-TTL rates with fallback to the legacy single cache-write rate), and falls back to the legacy single-rate calculation against `prompt_cache_creation_tokens` when the breakdown is absent.

Consequences for SDK implementors:

- Emit whatever the provider actually returns; do not synthesize missing fields beyond reconstructing `prompt_cache_creation_tokens` from `5m + 1h` when Anthropic only returned the breakdown.
- Do not drop the total when the breakdown is present. Older Braintrust backends only understand `prompt_cache_creation_tokens`, so keeping the total guarantees correct legacy-path cost tracking.
- Do not drop the breakdown when the total is present. Newer backends use the breakdown for per-TTL pricing.
- The `max(...)` rule means the server will not double-count if an SDK accidentally emits `5m + 1h != total`.

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
    "prompt_cache_creation_tokens": 2042,
    "prompt_cache_creation_5m_tokens": 1042,
    "prompt_cache_creation_1h_tokens": 1000
  }
}
```
