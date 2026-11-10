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

When the backend computes estimated cost from registry pricing, it looks up the model using `metadata.model` and selects non-standard tier prices using `metadata.provider`. SDKs MUST emit `metadata.requested_service_tier` and `metadata.served_service_tier` when available, as specified in [Service tiers](service-tiers.md). If the exact applicable price is known to the SDK but is not representable by registry pricing, emit `metrics.estimated_cost`.

## Canonical metrics

All token counts MUST be non-negative integers. Omit a metric when the provider did not report it and the SDK cannot compute it accurately. Do not fabricate zero values to hide missing provider data.

| Metric | Type | Required | Semantics |
| --- | --- | --- | --- |
| `prompt_tokens` | integer | MUST for LLM spans when reported | Total input/prompt tokens. For cache-aware providers, this includes uncached prompt tokens, cache-read tokens, and cache-write tokens. |
| `completion_tokens` | integer | MUST for LLM spans when reported | Output/completion tokens. |
| `tokens` | integer | MUST when prompt and completion totals are known | Total tokens for the call, normally `prompt_tokens + completion_tokens`. |
| `prompt_cached_tokens` | integer | SHOULD when reported | Prompt tokens read from a provider cache. These are a subset of `prompt_tokens`, not extra tokens. |
| `prompt_cache_creation_tokens` | integer | SHOULD when reported | Aggregate prompt tokens written to a provider cache. These are a subset of `prompt_tokens`, not extra tokens. |
| `prompt_cache_creation_5m_tokens` | integer | SHOULD when reported | Prompt cache-write tokens for a 5-minute TTL bucket. This is a breakdown or alternative representation of cache creation tokens, not an additional token class. |
| `prompt_cache_creation_1h_tokens` | integer | SHOULD when reported | Prompt cache-write tokens for a 1-hour TTL bucket. This is a breakdown or alternative representation of cache creation tokens, not an additional token class. |
| `completion_reasoning_tokens` | integer | MUST when reported | Tokens used for model reasoning. These are a subset of `completion_tokens`, usage diagnostics, and not separately costed by the current estimated-cost formula. |
| `prompt_audio_tokens` | integer | SHOULD when reported | Input audio tokens. These are a subset of `prompt_tokens`, not additional tokens. |
| `completion_audio_tokens` | integer | SHOULD when reported | Output audio tokens. These are a subset of `completion_tokens`, not additional tokens. |
| `completion_image_tokens` | integer | SHOULD when reported | Output image tokens. These are a subset of `completion_tokens`, not additional tokens. |
| `time_to_first_token` | number | MUST for streaming spans | For text output, seconds from request start to the first model-generated token or text chunk; for multimodal output, seconds to the first content-bearing output event. |
| `estimated_cost` | number | MAY | Explicit per-span total cost override in dollars. Must be finite. |

`input_tokens`, `output_tokens`, and `total_tokens` are accepted by some OpenTelemetry ingestion adapters and normalized to `prompt_tokens`, `completion_tokens`, and `tokens`. SDKs emitting Braintrust-native metrics MUST use the canonical Braintrust names directly.

Embedding spans have no generated-token component. They emit
`prompt_tokens` and `tokens` only when reported and MUST omit
`completion_tokens` rather than fabricate zero. See
[Embeddings](embeddings.md#metrics).

Extraction spans reuse the canonical token and cost fields with their own
`extraction` span type. Preserve reported output-token counts, including zero;
do not count serialized result JSON as generated tokens. See
[Extraction spans](extraction-spans.md#metrics) for input-only usage and
aggregate token accounting.

For multimodal output, a content-bearing event contains generated text or media
data. Empty deltas, handshake messages, acknowledgements, usage-only events,
and other control events do not satisfy `time_to_first_token`.

Provider usage fields sometimes divide prompt or completion usage into additional categories. Those categories MUST be included in the canonical totals when the provider defines them as input or output usage. In particular, Google Gemini thoughts are included in `completion_tokens`, Google tool-use prompts are included in `prompt_tokens`, and Google's reported total is preserved as `tokens`; see [Google Gemini usage metadata](google-usage-metadata.md). SDKs MUST NOT invent custom metrics such as `tool_use_tokens` for provider-specific categories.

## Data required by insight

Braintrust can only compute or display an insight when the required data is present. Missing data should result in a missing or explicitly incomplete insight, not a fabricated value.

| Insight | Required data | Completeness semantics |
| --- | --- | --- |
| Identify LLM spans | `span_attributes.type = "llm"` | Without this, token/cost fields may not appear in LLM-specific views or aggregations. |
| Attribute model usage | `metadata.model`, `metadata.provider` | Model alone is insufficient for reseller or gateway pricing attribution. |
| Attribute service-tier pricing | `metadata.model`, `metadata.provider`, `metadata.requested_service_tier` when specified, `metadata.served_service_tier` when reported | A requested non-standard tier does not prove the served tier. See [Service-tier pricing](#service-tier-pricing) for missing-tier and missing-price behavior. |
| Prompt/completion token totals | `metrics.prompt_tokens`, `metrics.completion_tokens` | If one side is missing, only partial usage is known. |
| Total tokens | `metrics.tokens`, or both `metrics.prompt_tokens` and `metrics.completion_tokens` | SDKs SHOULD emit `tokens` when the provider reports a total; otherwise compute it only when both parts are known. |
| Cache-read usage and savings | `metrics.prompt_cached_tokens`, `metrics.prompt_tokens`, `metadata.model`, `metadata.provider` | If cache-read tokens are missing, cost falls back to treating all prompt tokens as uncached for cache-read purposes. |
| Aggregate cache-write cost | `metrics.prompt_cache_creation_tokens`, `metrics.prompt_tokens`, `metadata.model`, `metadata.provider` | If aggregate cache-write tokens are missing, cache-write cost can only be computed from TTL split fields if present. |
| TTL-specific cache-write cost | `metrics.prompt_cache_creation_5m_tokens`, `metrics.prompt_cache_creation_1h_tokens`, `metadata.model`, `metadata.provider`, pricing with both split cache-write rates | If split rates or a complete split are unavailable, cost falls back to aggregate cache-write pricing. |
| Reasoning usage | `metrics.completion_reasoning_tokens` | This is a subset of `completion_tokens`. Missing means the provider did not report reasoning tokens or the SDK did not capture them. |
| Audio/image usage | `metrics.prompt_audio_tokens`, `metrics.completion_audio_tokens`, `metrics.completion_image_tokens` | Each detail is a subset of its prompt or completion total. Unsupported modality arrays remain provider metadata rather than custom metrics. |
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

### Service-tier pricing

Before applying the token cost formula, the backend selects rates using `metadata.served_service_tier`, with `metadata.requested_service_tier` indicating whether a missing served tier leaves pricing uncertain. The [SDK payload contract](service-tiers.md) keeps these fields separate.

- A served tier takes precedence over the requested tier. A request for `flex` served as `default` uses standard prices.
- `default`, `standard`, `on_demand`, `standard_only`, and `unspecified` select standard pricing. Backend comparisons ignore case and surrounding whitespace.
- If both tier fields are absent, standard pricing applies for backward compatibility. If only the requested tier is present, standard pricing applies only when that value is one of the standard aliases above.
- For models with a `pricing` section, a missing served tier after a non-standard or `auto` request, or an unrecognized served tier, produces an unknown cost (`null`).
- Recognized non-standard tiers (`flex`, `batch`, and `priority`) require matching provider/tier rates. A missing provider, missing tier rates, date-bounded rates, conflicting prices among rates matching the prompt length, or missing rates for a used token category produces an unknown cost.
- Models without a `pricing` section retain legacy standard pricing regardless of tier metadata. This fallback does not prove that standard processing served the call.
- An explicit finite `metrics.estimated_cost` still takes precedence, after scorer exclusion. SDKs MUST NOT populate it from an assumed served tier.

These rules follow the [backend tier-pricing implementation](https://github.com/braintrustdata/braintrust/blob/674c68bd741937365d3c3d337caf5d86cd332c08/brainstore/util/src/cost.rs). An unknown cost is not zero; sums skip spans with unknown costs.

### Token cost formula

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

All rates are per million tokens. Under legacy standard pricing, cache-read and aggregate cache-write rates fall back to the input-token rate when no specialized rate is available. Non-standard tier pricing first requires rates for every used token category as described above; missing tier-specific cache rates do not fall back to standard prices.

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
    "model": "claude-sonnet-4-6",
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

# SDK support

```yaml
id: token-and-cost-metrics
name: Token and cost metrics
category: Token & cost
support:
  prompt-completion-tokens:
    dotnet: "yes"
    go: "yes"
    java: "yes"
    js: "yes"
    python: "yes"
    ruby: "yes"
    rust: "yes"
  time-to-first-token:
    dotnet: "yes"
    go: "yes"
    java: "yes"
    js: "yes"
    python: "yes"
    ruby: "yes"
    rust: "yes"
  reasoning-tokens:
    dotnet: "no"
    go: "yes"
    java: "yes"
    js: "yes"
    python: "yes"
    ruby: "yes"
    rust: "yes"
  model-provider-attribution:
    dotnet: "yes"
    go: "yes"
    java: "yes"
    js: "yes"
    python: "yes"
    ruby: "yes"
    rust: "partial"
```
