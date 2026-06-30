# Token and cost metrics

This spec defines the token and cost fields Braintrust SDKs must emit for LLM spans. The goal is to make token counts, cache behavior, latency, reasoning usage, and estimated cost attributable from the data in each span.

## Span identity

Every LLM span MUST include:

| Field | Type | Required | Semantics |
| --- | --- | --- | --- |
| `span_attributes.type` | string | MUST | Set to `"llm"` for model-call spans. |
| `metadata.model` | string | MUST | The resolved model identifier for the call, preferably the model string returned by the provider. |
| `metadata.provider` | string | MUST | The provider, gateway, or reseller whose pricing applies to the call. |

`metadata.provider` is required even when a model name appears globally unique. Resellers and gateways can sell the same model at different prices, and provider is the minimum field needed to attribute cost to the pricing surface actually used.

When the backend computes estimated cost from registry pricing, current cost lookup is model-driven. SDKs MUST still emit `metadata.provider` so provider-specific and reseller-specific pricing can be attributed correctly. If the exact applicable price is known to the SDK but is not representable by registry pricing, emit `metrics.estimated_cost`.

## Canonical metrics

All token counts MUST be non-negative integers. Omit a metric when the provider did not report it and the SDK cannot compute it accurately. Do not fabricate zero values to hide missing provider data.

| Metric | Type | Required | Semantics |
| --- | --- | --- | --- |
| `prompt_tokens` | integer | MUST for LLM spans when reported | Total input/prompt tokens. For cache-aware providers, this includes uncached prompt tokens, cache-read tokens, and cache-write tokens. |
| `completion_tokens` | integer | MUST for LLM spans when reported | Output/completion tokens. |
| `tokens` | integer | MUST when prompt and completion totals are known | Total tokens for the call, normally `prompt_tokens + completion_tokens`. |
| `total_tokens` | integer | MAY | Compatibility total. SDKs SHOULD prefer `tokens`; raw `braintrust.metrics.total_tokens` is not a cost input unless also normalized to `tokens`. |
| `prompt_cached_tokens` | integer | SHOULD when reported | Prompt tokens read from a provider cache. These are a subset of `prompt_tokens`, not extra tokens. |
| `prompt_cache_creation_tokens` | integer | SHOULD when reported | Aggregate prompt tokens written to a provider cache. These are a subset of `prompt_tokens`, not extra tokens. |
| `prompt_cache_creation_5m_tokens` | integer | SHOULD when reported | Prompt cache-write tokens for a 5-minute TTL bucket. This is a breakdown or alternative representation of cache creation tokens, not an additional token class. |
| `prompt_cache_creation_1h_tokens` | integer | SHOULD when reported | Prompt cache-write tokens for a 1-hour TTL bucket. This is a breakdown or alternative representation of cache creation tokens, not an additional token class. |
| `completion_reasoning_tokens` | integer | MUST when reported | Tokens used for model reasoning. These are usage diagnostics and are not separately costed by the current estimated-cost formula. |
| `time_to_first_token` | number | MUST for streaming spans | Seconds from request start to first streamed token or chunk. |
| `estimated_cost` | number | MAY | Explicit per-span total cost override in dollars. Must be finite. |

`input_tokens` and `output_tokens` are accepted by some OpenTelemetry ingestion adapters and normalized to `prompt_tokens` and `completion_tokens`. SDKs emitting Braintrust-native metrics MUST use the canonical Braintrust names directly.

## Data required by insight

Braintrust can only compute or display an insight when the required data is present. Missing data should result in a missing or explicitly incomplete insight, not a fabricated value.

| Insight | Required data | Completeness semantics |
| --- | --- | --- |
| Identify LLM spans | `span_attributes.type = "llm"` | Without this, token/cost fields may not appear in LLM-specific views or aggregations. |
| Attribute model usage | `metadata.model`, `metadata.provider` | Model alone is insufficient for reseller or gateway pricing attribution. |
| Prompt/completion token totals | `metrics.prompt_tokens`, `metrics.completion_tokens` | If one side is missing, only partial usage is known. |
| Total tokens | `metrics.tokens`, or both `metrics.prompt_tokens` and `metrics.completion_tokens` | SDKs SHOULD emit `tokens` when the provider reports a total; otherwise compute it only when both parts are known. |
| Cache-read usage and savings | `metrics.prompt_cached_tokens`, `metrics.prompt_tokens`, `metadata.model`, `metadata.provider` | If cache-read tokens are missing, cost falls back to treating all prompt tokens as uncached for cache-read purposes. |
| Aggregate cache-write cost | `metrics.prompt_cache_creation_tokens`, `metrics.prompt_tokens`, `metadata.model`, `metadata.provider` | If aggregate cache-write tokens are missing, cache-write cost can only be computed from TTL split fields if present. |
| TTL-specific cache-write cost | `metrics.prompt_cache_creation_5m_tokens`, `metrics.prompt_cache_creation_1h_tokens`, `metadata.model`, `metadata.provider`, pricing with both split cache-write rates | If split rates or a complete split are unavailable, cost falls back to aggregate cache-write pricing. |
| Reasoning usage | `metrics.completion_reasoning_tokens` | Missing means the provider did not report reasoning tokens or the SDK did not capture them. |
| Streaming latency | `metrics.time_to_first_token` | Required only for streaming spans. |
| Estimated dollar cost | `metrics.estimated_cost`, or token metrics plus `metadata.model`, `metadata.provider`, and matching model/provider pricing | `estimated_cost` is the most authoritative per-span value. Token-derived cost is unavailable when pricing or token inputs are unavailable. |
| Exclude scorer costs | `span_attributes.purpose = "scorer"` on scorer LLM spans | Braintrust estimated-cost functions exclude scorer spans. Omit this only when scorer cost should be counted with normal task cost. |

Parent `task` spans MAY include aggregate token metrics for display, but SDKs SHOULD avoid making parent rollups look like independent billable LLM calls. The most reliable cost attribution comes from leaf `llm` spans that correspond to actual provider requests.

## Cost computation semantics

Braintrust estimated-cost queries use the following precedence. Cost attribution requires both
`metadata.model` and `metadata.provider`; current registry lookup may still be model-keyed in
some backend paths, but SDKs MUST log provider so reseller and gateway prices can be resolved
without changing the span shape.

1. If `span_attributes.purpose` is `"scorer"`, no estimated cost is returned for that span.
2. If `metrics.estimated_cost` is present and finite, it is used as the span's total cost.
3. Otherwise, Braintrust computes cost from token metrics and model/provider pricing when the necessary data is available.

When computing from token metrics, missing token fields are treated as zero, but if all token fields are missing then no cost is computed.

Cache-write metrics are normalized before pricing:

```text
split_creation_tokens =
  prompt_cache_creation_5m_tokens + prompt_cache_creation_1h_tokens

effective_creation_tokens =
  max(prompt_cache_creation_tokens, split_creation_tokens)
```

Split 5m/1h cache-write pricing is used only when both split rates are available and the split token sum covers the aggregate cache-write total:

```text
split_creation_tokens >= prompt_cache_creation_tokens
```

Otherwise, Braintrust falls back to aggregate cache-write pricing on `effective_creation_tokens`.

Uncached prompt tokens are computed with saturation at zero:

```text
prompt_uncached_tokens =
  max(prompt_tokens - prompt_cached_tokens - effective_creation_tokens, 0)
```

Total token-derived cost is:

```text
prompt_uncached_tokens * input_rate
+ prompt_cached_tokens * cache_read_rate
+ cache_write_cost
+ completion_tokens * output_rate
```

All rates are per million tokens. Cache-read and aggregate cache-write rates fall back to the input-token rate when no specialized rate is available.

## Estimated-cost query outputs

`estimated_cost()` returns the total estimated cost for each row.

`estimated_cost_breakdown()` returns a JSON string with these fields:

| Field | Meaning |
| --- | --- |
| `promptUncachedTokens` | Prompt tokens priced at the normal input-token rate. |
| `promptCachedTokens` | Prompt tokens priced at the cache-read rate. |
| `promptCacheCreationTokens` | Aggregate cache-write tokens. |
| `promptCacheCreation5mTokens` | Cache-write tokens priced at the 5m split rate, when split pricing is used. |
| `promptCacheCreation1hTokens` | Cache-write tokens priced at the 1h split rate, when split pricing is used. |
| `completionTokens` | Completion tokens priced at the output-token rate. |
| `promptUncachedTokensCost` | Cost for uncached prompt tokens. |
| `promptCachedTokensCost` | Cost for cache-read prompt tokens. |
| `promptCacheCreationTokensCost` | Total cache-write cost. |
| `promptCacheCreation5mTokensCost` | 5m cache-write cost, or `0` when split pricing is not used. |
| `promptCacheCreation1hTokensCost` | 1h cache-write cost, or `0` when split pricing is not used. |
| `completionTokensCost` | Cost for completion tokens. |
| `totalCost` | Total estimated cost. |

`estimated_cost_component(name)` returns one component from the breakdown. Valid component names are `promptUncachedTokensCost`, `completionTokensCost`, `promptCachedTokensCost`, `promptCacheCreationTokensCost`, `promptCacheCreation5mTokensCost`, `promptCacheCreation1hTokensCost`, and `totalCost`.

## Wire format

```json
{
  "span_attributes": {
    "type": "llm"
  },
  "metadata": {
    "model": "claude-sonnet-4-5-20250929",
    "provider": "anthropic"
  },
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
