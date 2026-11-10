# Service tiers

Service levels describe the processing tier requested for a model call and the tier that actually served it.
SDKs MUST record these separately because a provider can serve a request at a different tier, which can change its price.
This spec uses the backend's term, **service tier**, and defines the metadata sent on each model-call span.
It does not define APIs for selecting a tier, routing requests, or retrying capacity errors.

## Payload contract

Native Braintrust logging and provider/framework instrumentation MUST use these fields when their source values are available:

| Field | Type | Source |
| --- | --- | --- |
| `metadata.requested_service_tier` | string | The service tier in the effective request for this call. |
| `metadata.served_service_tier` | string | The service tier reported by the provider for this response. |

Both fields belong alongside `metadata.model` and `metadata.provider` on the span for the model call.
They MUST NOT be emitted as metrics, top-level row fields, or span attributes.
An ambiguous field such as `metadata.service_tier`, or a tier retained only in provider-native output, does not satisfy this contract.
Existing allowlisted provider metadata MAY remain, but consumers MUST be able to read the two canonical fields without parsing it.

The fields are independent:

- SDKs MUST capture the requested tier when it is available, including a client or framework default that is known to be applied to the request.
- SDKs MUST capture the served tier when the response reports it, even if no tier was specified in the request.
- SDKs MUST NOT copy the requested tier into the served field or infer the served tier from the model, latency, price, account configuration, or a successful HTTP status.
- SDKs MUST omit each field whose source is absent, null, empty, or not a string after extracting the provider's tier value.
  They MUST NOT emit a placeholder such as `"unknown"`, stringify an object, or fabricate a default.
- Tier capture MUST select these fields explicitly and MUST NOT copy the entire request configuration, response, usage object, or headers into metadata.
- Disabling input/output content capture or optional request-parameter capture MUST NOT disable these cost-attribution fields when span logging remains enabled.
  Explicit user transformations still follow [Span customizer hooks](span-customizers.md).

SDKs MUST preserve the meaning of the provider's tier identifier.
They MUST trim surrounding whitespace and use lowercase ASCII for tier identifiers; for example, Google's `"PRIORITY"` becomes `"priority"`.
They MUST NOT collapse provider-specific values such as `"default"`, `"standard"`, `"on_demand"`, and `"standard_only"` into one identifier.
The fields are open strings, not a closed enum: an unfamiliar non-empty tier MUST be retained after this normalization.
The backend may have no price for that tier.
Request policies such as `"auto"` MUST remain `"auto"`; they do not prove which tier served the call.

These rules change the logged data only.
Instrumentation MUST NOT add, remove, or change a provider request parameter to obtain tier telemetry.

## Provider mappings

Paths below refer to provider wire objects.
Language-specific clients may expose equivalent snake_case properties or enum values; SDKs MUST extract the underlying wire value rather than the enum's debug representation.
Apply a mapping only to the API surface that defines it.

| API | Requested tier source | Served tier source | Streaming served tier source |
| --- | --- | --- | --- |
| OpenAI Chat Completions | Request `service_tier` | Response `service_tier` | Chunk `service_tier`, including chunks without content. |
| OpenAI Responses | Request `service_tier` | Response `service_tier` | Lifecycle event `response.service_tier`, including the final response. |
| Anthropic Messages | Request `service_tier` | Response `usage.service_tier` | `message_start.message.usage.service_tier`, and subsequent usage updates when reported. |
| Google GenerateContent | Request `serviceTier` | Response `usageMetadata.serviceTier` | Chunk `usageMetadata.serviceTier`. |
| AWS Bedrock Converse | Request `serviceTier.type` | Response `serviceTier.type` | Stream event `metadata.serviceTier.type`. |

For example, an Anthropic request can contain `"standard_only"` while its response reports `"standard"`.
A Bedrock `serviceTier` object MUST be reduced to its `type` string.
Google values such as `"FLEX"`, `"PRIORITY"`, `"STANDARD"`, and `"UNSPECIFIED"` become `"flex"`, `"priority"`, `"standard"`, and `"unspecified"` respectively.

OpenAI-compatible endpoints MAY use the OpenAI mapping when they expose the same fields with the same meaning.
The wire format does not establish the billing provider: Azure, Bedrock, gateways, and resellers MUST retain the provider identity required by [Token and cost metrics](token-and-cost-metrics.md#span-identity).
Other integrations MUST map documented request and response tier fields to this contract when available, and omit unavailable fields.
They MUST NOT assume that a provider-native field is present merely because the model is also available through another provider.

## Streaming, errors, and call boundaries

Capture the requested tier before the provider call and retain it if the call fails or the stream is cancelled.
SDKs MUST collect served-tier values throughout the stream, including lifecycle and usage-only events, and merge the result into the same span's metadata.
A later reported tier replaces an earlier tier; an absent, null, or empty value MUST NOT erase a previously captured value.
In particular, an OpenAI Responses stream that starts with `"auto"` and completes with `"default"` MUST end with `served_service_tier: "default"`.
SDKs MUST NOT finalize tier capture at the first content chunk or stop processing metadata at a finish-reason chunk when the provider can still send usage events.

An error or interrupted stream MUST preserve any tier already observed and MUST NOT fabricate a served tier when none was reported.
These rules do not require draining a stream after the caller cancels it or making an additional provider request.

Tier metadata is local to each model call.
SDKs MUST NOT inherit a tier from a parent span or another call in an agent loop.
When retries or fallbacks have separate spans, each span MUST describe its own request and response.
When an integration uses one span for a logical call, a served tier from a failed attempt MUST NOT be carried into a later attempt, and the final tier fields MUST describe the same attempt as its output and usage.

For [batch APIs](batch-apis.md), record tier fields on each child model-call span when the caller-supplied request or result exposes them.
SDKs MUST NOT infer `served_service_tier: "batch"` merely from submission of a batch job.
An explicit `"batch"` response tier follows the same contract as other reported tiers.

## Wire examples

The following row fragment records a request for flex processing that was served at the default tier:

```json
{
  "span_attributes": { "type": "llm" },
  "metadata": {
    "model": "gpt-5-mini",
    "provider": "openai",
    "requested_service_tier": "flex",
    "served_service_tier": "default"
  },
  "metrics": {
    "prompt_tokens": 100,
    "completion_tokens": 20,
    "tokens": 120
  }
}
```

If the request fails before a provider reports its tier, the tier metadata is only:

```json
{
  "metadata": {
    "model": "gpt-5-mini",
    "provider": "openai",
    "requested_service_tier": "flex"
  }
}
```

OpenTelemetry exporters MUST JSON-encode the same metadata object in `braintrust.metadata`, using the existing metadata transport:

```json
{
  "braintrust.metadata": "{\"model\":\"gpt-5-mini\",\"provider\":\"openai\",\"requested_service_tier\":\"flex\",\"served_service_tier\":\"default\"}"
}
```

Separate OTel tier attributes do not replace these canonical metadata fields.

## Cost attribution

The served tier determines tier-specific pricing.
For example, the first payload above uses standard prices even though it requested flex.
The full precedence and missing-price behavior are specified in [Token and cost metrics](token-and-cost-metrics.md#service-tier-pricing).
SDKs MUST NOT emit a guessed `metrics.estimated_cost` based only on the requested tier, because an explicit cost overrides backend estimation.

## Conformance cases

SDK implementations MUST cover these cases for each supported API mapping, using controlled responses where live provider behavior is not deterministic:

| Case | Expected metadata behavior |
| --- | --- |
| Request `flex`, response `flex` | Record both fields as `"flex"`. |
| Request `flex`, response `default` | Retain requested `"flex"` and served `"default"`. |
| Request `auto`, response `priority` | Retain requested `"auto"` and served `"priority"`. |
| No requested tier, response `priority` | Emit only the served field. |
| Request `flex`, no response tier | Emit only the requested field, including on errors. |
| Neither source has a tier | Omit both fields. |
| Tier is null, whitespace-only, or non-string | Omit that field without failing the provider call or span export. |
| Response has an unfamiliar non-empty string | Preserve its normalized identifier without guessing a known tier. |
| Tier appears only in a usage or terminal stream event | Record it on the existing span. |
| Stream reports `auto`, then `default`, then no tier | Retain served `"default"`. |
| Cancelled stream | Retain observed values and omit an unobserved served tier. |
| Framework default or per-call override | Record the effective requested tier for that call. |
| Retry or concurrent calls | Do not mix tier values between attempts or calls. |
| Content capture disabled | Retain tier metadata. |
| OTel export | Decoding `braintrust.metadata` yields the same canonical fields as native logging. |

## Implementation references

The field names and requested/served distinction match the [backend tier-pricing change](https://github.com/braintrustdata/braintrust/pull/24310) and [gateway logging change](https://github.com/braintrustdata/braintrust/pull/24458).
Provider mappings were checked against the [Lingua provider adapters](https://github.com/braintrustdata/lingua/tree/e58a8658058ad56904cd86ba851c589359270577/crates/lingua/src/providers).

# SDK support

```yaml
id: service-tiers
name: Service tiers
category: Token & cost
providers: [openai, anthropic, google, bedrock]
support:
  requested-service-tier:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  served-service-tier:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  streaming-service-tier:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  otel-service-tier-metadata:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
```
