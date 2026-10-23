# Extraction spans

An `extraction` span represents one model call that extracts, computes, estimates, or forecasts typed values from supplied state and field definitions.
This contract defines a provider-independent capture format.
Adapters MUST map equivalent provider fields to the canonical properties below using documented semantics, omitting optional properties the provider does not expose.

## Span model

Instrumentation MUST emit one span with `span_attributes.type: "extraction"` per eligible model call, including calls with multiple fields or provider-internal inference passes.
Do not create a span per field, list item, forecast step, or internal pass.
The guide's [auto-instrumentation eligibility rules](../instrumentation-guide.md#auto-instrumentation-eligibility) apply.

Record `metadata.provider` and `metadata.model`, preferring the response's model identifier and falling back to the requested model.
The provider identifies the serving provider, gateway, or reseller whose pricing applies.
Use the guide's usual timing, error, parentage, and provenance conventions.

Extraction calls use the structured payload below, without wrapping state or results in chat messages or serializing them into strings.
Calls that answer decision questions follow [Decision spans](decision-spans.md).
Generative chat calls that return JSON, including calls prompted to extract data, remain `llm` spans under the completion API contract.

## Input

`input` MUST contain `state` and a non-empty `fields` array.
Preserve the supplied state as a JSON value, including its text and structure.
If the request supplies only images with no separate state, use `input.state: null`.
Each field MUST have a non-empty string `id`, unique within the array, and its declared `type`.
Convert provider maps keyed by field name into arrays, preserving each key as `id` and preserving request order where available.
Optional field properties MUST be retained when supplied, including explicit `false` and zero; do not materialize unspecified provider defaults.

The field definition allowlist is:

| Property | Meaning |
| --- | --- |
| `instructions` | The supplied description of the value to return. |
| `unit` | The value's unit, such as USD or days. |
| `integer`, `decimals` | Numeric precision constraints. |
| `items` | The element type of a list: `text`, `number`, or `date`. |
| `min`, `max`, `step`, `scale` | Prediction bounds, grid, and linear or logarithmic scale; preserve number and date representations. |
| `null_threshold` | The requested threshold for returning a null value. |
| `horizon`, `interval` | The number and spacing of forecast steps. |

The input MUST also retain `images`, `reference_date`, and the allowlisted `options` properties when supplied by the caller.
`images` preserves the ordered image inputs, using the attachment rules below.
`reference_date` preserves the date used to resolve relative or incomplete dates.
Only `include_quantiles` and `return_state_text` are allowed within `options`.
These represent requests for additional prediction quantiles and the processed source text, respectively.
Model identifiers belong in metadata, and credentials, HTTP configuration, and unlisted request properties MUST NOT be copied into the payload.

## Output

Successful `output` MUST contain an `answers` array.
Convert provider answer maps into arrays with their keys as `id`.
Each answer contains `id`, `type`, and `value`; associate answers with fields by `id`, never by position.
Preserve returned answer order and preserve list and forecast element order.

| `type` | `value` | Additional result fields to retain when returned |
| --- | --- | --- |
| `text` | String or `null` | `guess`, `span`, `p_null`, `confidence` |
| `number` | Number or `null` | `guess`, `p_null`, `confidence` |
| `date`, `time`, `datetime` | Provider's ISO string or `null` | `guess`, `p_null`, `confidence` |
| `duration` | Number or `null` | `unit`, `guess`, `p_null`, `confidence` |
| `list` | Array of values of the requested element type | `spans`, `confidence` |
| `estimate` | Predicted number or date | `mean`, `median`, `p10`, `p90`, `p_below`, `p_above`, `quantiles` |
| `forecast` | Ordered array of predicted values | `mean`, `median`, `p10`, `p90`, `p_below`, `p_above`, `quantiles`, `steps` |

Retain the provider's numeric precision and date/time strings without rounding, timezone conversion, clamping, or recalculation.
For forecasts, preserve returned parallel arrays and their step alignment.
When the provider returns `steps`, preserve its ordered per-step estimates using the estimate result fields above, including `value`.
Preserve the returned shape and order of quantiles; do not interpolate missing percentiles or request additional quantiles solely for telemetry.

`value: null` is a successful model result, distinct from an absent answer, zero, or an empty list.
Keep `guess` separate even when `value` is null, and do not replace the value with the guess or reapply `null_threshold` in instrumentation.
Preserve reported `p_null`, confidence, and prediction bounds, including zero and explicit nulls; omit absent properties.
`p_null` is the probability that the input does not determine a value; `p_below` and `p_above` are probabilities outside the requested prediction bounds.
`p10` and `p90` are the 10th and 90th percentiles, not minimum and maximum possible values.
Do not synthesize confidence, discard low-confidence results, or move predictions and probabilities into top-level `scores`, `classifications`, or `metrics`.

`output` MUST also retain `truncated` and `state_text` when returned.
These fields describe the provider's processed input and are relevant to interpreting source offsets.
Do not copy the entire provider response or transport envelope into the span.

### Source offsets

`span` is a returned `[start, end]` source range, and `spans` contains returned ranges associated with list items.
These are text offsets, not tracing spans.
Preserve the ranges exactly, including a range associated with a `guess` when `value` is null.
Do not find a replacement range by searching for the answer text, reorder list ranges, or interpret text offsets as image coordinates.

When returned, `output.state_text` is the provider's text for interpreting the ranges.
Otherwise use `input.state` only when the provider's documented semantics establish it as the indexed string.
Do not replace the original input state with the returned text.
Consumers MUST use the provider's documented offset units and endpoint convention; they MUST NOT assume bytes, Unicode code points, or UTF-16 code units are interchangeable.
If truncation, image processing, or unavailable offset semantics leave the source ambiguous, retain the ranges for inspection without highlighting an assumed source.
Instrumentation MUST NOT enable `return_state_text` or alter the provider request to obtain missing context.

## Images and attachments

Apply the shared [attachment contract](attachments.md) to inline media in the extraction payload, including nested state and `input.images`.
Replace images with attachment references at their original locations, preserving image order and surrounding data.
Keep existing attachment references and remote URLs without fetching them solely for logging.

Conversion changes only the logged payload and runs after [span customizers](span-customizers.md), so redacted media is not uploaded.
Use the shared [all-or-nothing fallback](attachments.md#partial-replacement-safety) on conversion or upload failure; retain the original payload and export the span.

## Metrics

Record `metrics.start` and `metrics.end` for the observed call.
Use canonical [token and cost metrics](token-and-cost-metrics.md) for reported usage on extraction spans.
Serialized answer JSON is not completion-token usage.

| Reported usage | Braintrust metric |
| --- | --- |
| Input tokens | `prompt_tokens`. |
| Output tokens | `completion_tokens`, including an explicitly reported zero. |
| Total tokens | `tokens`; preserve the reported total, or compute the sum when complete input and output counts are known. |

If only input usage is reported for a model known to have no generated-token component, `metrics.tokens` MAY equal `metrics.prompt_tokens`; leave `completion_tokens` absent.
If usage is absent, omit token metrics rather than tokenizing locally or fabricating zeros.
Provider usage may break down input tokens by state, images, or field definitions, or report the number of internal inference passes.
Do not add breakdowns to aggregate input usage, multiply a reported total by the number of passes, or emit these details as custom metrics.
Do not emit `time_to_first_token` for a non-streaming response.
`metrics.estimated_cost` MAY be emitted when the applicable total cost is known under the shared cost rules.

## Errors

Provider failures populate the top-level `error` field and end the span.
Retain any returned partial answers using the same allowlist without filling in missing answers with nulls.
A null value, empty list, or `truncated: true` does not by itself indicate a failed call.
Unexpected JSON-representable values in allowed fields MUST NOT make instrumentation throw into application code, silently repair results, or discard the entire span.
The capture contract does not authorize extra provider requests, retries, or validation of application inputs.

## Example

This illustrative captured span includes an extracted value and a missing value with a separate guess.
The provider explicitly reported zero output tokens.
Timing and trace identifiers are omitted from this excerpt.

```json
{
  "span_attributes": { "type": "extraction" },
  "metadata": { "provider": "example-provider", "model": "example-model" },
  "input": {
    "state": "Order A-42. Total USD 25.",
    "fields": [
      { "id": "order_id", "type": "text" },
      { "id": "tracking_number", "type": "text" }
    ]
  },
  "output": {
    "answers": [
      {
        "id": "order_id",
        "type": "text",
        "value": "A-42",
        "guess": "A-42",
        "span": [6, 10],
        "p_null": 0.001,
        "confidence": 0.99
      },
      {
        "id": "tracking_number",
        "type": "text",
        "value": null,
        "guess": "A-42",
        "span": [6, 10],
        "p_null": 0.98,
        "confidence": 0.4
      }
    ],
    "truncated": false
  },
  "metrics": { "prompt_tokens": 80, "completion_tokens": 0, "tokens": 80 }
}
```

## Conformance scenarios

SDK implementations SHOULD cover these scenarios:

| Scenario | Expected capture |
| --- | --- |
| Multiple fields, answers returned in a different order | One extraction span; field and answer IDs preserve their association. |
| Text, numeric, temporal, duration, and list results | Preserve types, precision, units, values, source ranges, and list order. |
| Null value with a non-null guess; zero value; empty list | Preserve each distinctly without filtering or substituting the guess. |
| Estimate with bounds and optional quantiles | Capture the requested grid and returned distribution without recomputation. |
| Multi-step forecast | Preserve horizon, interval, ordered predictions, and per-step uncertainty. |
| Returned source text or truncation | Preserve the original input, returned text, ranges, and truncation indicator. |
| Non-ASCII input or ambiguous offset semantics | Keep offsets unchanged; do not highlight using guessed string indices. |
| Image-only or mixed text/image request | Preserve state and image order with attachment references and shared fallback. |
| Several internal passes with usage breakdowns | One span; use aggregate input usage once without adding details or multiplying by passes. |
| Reported zero output tokens versus absent usage | Preserve reported zero; omit unavailable metrics. |
| Provider failure with partial answers | Capture the error and available answers without synthesizing missing results. |
| Generative chat call asked to extract JSON | Retain the existing completion API contract and `llm` span type. |

# SDK support

```yaml
id: extraction-spans
name: Extraction spans
category: Tracing
support:
  extraction-span-type:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  typed-fields-and-answers:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  source-offsets:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  estimates-and-forecasts:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  multimodal-input:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  token-usage:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
```
