# Embedding APIs

This document defines Braintrust instrumentation for text and multimodal
embedding APIs. Multimodal inputs use the canonical media and attachment rules
from [Multimodal API surfaces](multimodal-api-surfaces.md) and
[Attachments](attachments.md).

## Span model

Each embedding request **MUST** produce exactly one `llm` span, including a
request that contains multiple input items. Instrumentation **MUST NOT** emit
one span per returned vector.

Embedding spans **SHOULD** include:

- `metadata.provider`
- `metadata.model`

The resolved model returned by the provider is preferred. If the provider does
not return a model, use the requested model.

## Canonical input

All embedding instrumentation **MUST** emit:

```ts
type EmbeddingTaskType =
  | "retrieval_query"
  | "retrieval_document"
  | "semantic_similarity"
  | "classification"
  | "clustering"
  | "question_answering"
  | "fact_verification"
  | "code_retrieval_query";

type EmbeddingInput = {
  inputs: Array<{
    index: number;
    content: string | MediaPart[];
  }>;
  task_type?: EmbeddingTaskType;
  output_dimensions?: number;
};
```

`index` starts at zero and preserves request order. A scalar provider input is
represented by one entry. A batch input is represented by one entry per
independently returned embedding.

Provider task types are normalized to the concrete values in
`EmbeddingTaskType`. For example, provider values such as `search_query` map to
`retrieval_query`, and `search_document` maps to `retrieval_document`. If a
provider value has no defined mapping, omit `task_type`.

`output_dimensions` preserves an explicitly requested vector size. Other
provider configuration fields **MUST NOT** be captured until added to this
specification.

### Multimodal content

`MediaPart` is defined in
[Multimodal API surfaces](multimodal-api-surfaces.md#canonical-media-parts).
Inline image, audio, video, and document data **MUST** be replaced with
attachment references. Text remains a text part. Remote URLs remain URLs.

The `inputs` boundary represents the provider's embedding aggregation
boundary:

- Multiple text/media parts combined into one provider content object remain
  one `inputs` entry and produce one embedding summary.
- Multiple provider content objects remain separate ordered `inputs` entries
  and produce separate embedding summaries.
- Instrumentation **MUST NOT** split or combine inputs in a way that changes
  their mapping to provider outputs.

## Canonical output

All embedding instrumentation **MUST** emit the canonical output:

```ts
type EmbeddingOutput = {
  count: number;
  embeddings: Array<{
    index: number;
  }>;
};
```

`count` **MUST** equal `embeddings.length`. Output entries preserve provider
order and contain only their normalized index.

Instrumentation **MUST NOT** capture:

- raw vector values
- prefixes or samples of vector values
- vector hashes
- vector norms or other derived vector statistics

Provider-native embedding responses **MUST NOT** be logged. Non-vector provider
response fields are captured only when this document explicitly defines them.

## Metrics

Embedding spans use input/total token metrics only when the provider reports
them:

| Metric | Requirement |
| --- | --- |
| `prompt_tokens` | Emit when the provider reports input tokens. |
| `tokens` | Emit when the provider reports total tokens. |
| `prompt_audio_tokens` | Emit when the provider reports an audio-input breakdown. |
| `estimated_cost` | May be emitted under the normal cost rules. |

`completion_tokens`, `completion_audio_tokens`,
`completion_image_tokens`, and `time_to_first_token` do not apply to embedding
spans and **MUST** be omitted. Instrumentation **MUST NOT** fabricate
`completion_tokens: 0`.

If only `prompt_tokens` is reported, instrumentation **MAY** set `tokens` to the
same value because an embedding request has no generated-token component. It
**MUST NOT** infer prompt tokens by tokenizing the input locally unless another
Braintrust specification explicitly permits that behavior.

## Errors and partial responses

Provider failures populate the span's top-level `error` field. If a provider
returns partial batch results with an error, instrumentation may retain the
summaries that were actually returned. Their indices **MUST** continue to
refer to the original input order.

Attachment conversion failures follow the all-or-nothing per-span fallback in
[Attachments](attachments.md#partial-replacement-safety) and **MUST NOT**
prevent the embedding span from being exported.

## Required implementation scenarios

SDK implementations should cover these scenarios in their own tests:

| Scenario | Expected result |
| --- | --- |
| Single text input | One indexed summary is emitted without vector values. |
| Text batch | Input/output indices are preserved. |
| Aggregated text and image parts | One input boundary produces one embedding summary. |
| Separate image, audio, video, and document inputs | Separate ordered summaries are emitted and inline inputs become attachments. |
| Explicit output dimensionality | The requested value is captured in input without adding dimensions to output. |
| Usage present vs absent | Reported tokens are captured; unavailable metrics are omitted. |
| Partial batch failure | Returned indices are preserved and top-level `error` is populated. |
