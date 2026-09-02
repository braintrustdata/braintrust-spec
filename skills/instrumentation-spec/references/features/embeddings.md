# Embedding APIs

This document defines Braintrust instrumentation for text and multimodal
embedding APIs. Because raw vectors are intentionally omitted, these spans
primarily intend to record request timing and token usage rather than
embedding vector payloads.

## Span model

Each embedding request **MUST** produce exactly one `llm` span, including a
request that contains multiple input items. Instrumentation **MUST NOT** emit
one span per returned embedding.

Embedding spans **MUST** include:

- `metadata.provider`
- `metadata.model`

The resolved model returned by the provider is preferred. If the provider does
not return a model, use the requested model.

## Canonical input

All embedding instrumentation **MUST** emit as `input`:

```ts
type BraintrustAttachment = {
  type: "braintrust_attachment";
  content_type: string;
  filename: string;
  key: string;
};

type EmbeddingContentPart =
  | { type: "text"; text: string }
  | {
      type: "image_url";
      image_url: { url: string | BraintrustAttachment };
    }
  | {
      type: "file";
      file: {
        filename?: string;
        file_data: string | BraintrustAttachment;
      };
    };

type EmbeddingInput = {
  inputs: Array<{
    content: string | EmbeddingContentPart[];
  }>;
  output_dimensions?: number;
};
```

The array preserves request order. A scalar provider input is represented by
one object. A batch input is represented by one object per independently
returned embedding. This is so that the input schema of this spec can be extended
in the future.

`output_dimensions` preserves an explicitly requested vector size. Other
provider configuration fields **MUST NOT** be captured until added to this
specification.

### Multimodal content

Text-only inputs use a string. Inputs containing multiple text or media parts
use `EmbeddingContentPart[]`. Images use `image_url`; audio, video, documents,
and other files use `file`. Remote URLs remain strings in the corresponding
URL or data field.

Inline image, audio, video, and document data **MUST** be replaced with
`BraintrustAttachment` references according to
[Attachments](attachments.md). In particular, attachment conversion failures
follow the [all-or-nothing per-span fallback](attachments.md#partial-replacement-safety)
and **MUST NOT** prevent the embedding span from being exported.

The `inputs` boundary represents the provider's embedding aggregation
boundary:

- Multiple text or media parts combined into one provider content object remain
  one `inputs` entry and correspond to one returned embedding.
- Multiple provider content objects remain separate ordered `inputs` entries
  and correspond to separate returned embeddings.
- Instrumentation **MUST NOT** split or combine inputs in a way that changes
  their mapping to provider outputs.

## Canonical output

Embedding instrumentation **MUST** emit a compact output and **MUST NOT** log
raw vectors. Provider embedding APIs use the canonical count output:

```ts
type EmbeddingOutput = {
  count: number;
};
```

`count` **MUST** equal the number of embeddings returned by the provider.

Local, in-process model runners that return a tensor **MAY** instead emit a
compact tensor-shape summary:

```ts
type LocalTensorEmbeddingOutput = {
  shape: number[];
};
```

`shape` **MUST** contain the size of each tensor dimension in axis order.
Instrumentation **MUST** read it from shape metadata exposed by the model
runtime and **MUST NOT** materialize or iterate the vector to compute it.

Instrumentation **MUST NOT** capture:

- raw vector values
- prefixes or samples of vector values
- vector hashes
- vector norms or other derived vector statistics

An explicitly requested `output_dimensions` value belongs in the canonical
input. Provider-native embedding responses **MUST NOT** be logged. Non-vector
provider response fields are captured only when this document explicitly
defines them.

## Metrics

Embedding spans use input and total token metrics only when the provider reports
them:

| Metric                | Requirement                                              |
| --------------------- | -------------------------------------------------------- |
| `prompt_tokens`       | Emit when the provider reports input tokens.             |
| `tokens`              | Emit when the provider reports total tokens.             |
| `prompt_audio_tokens` | Emit when the provider reports an audio-input breakdown. |
| `estimated_cost`      | May be emitted under the normal cost rules.              |

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
returns partial batch results with an error, `count` **MUST** equal the number
actually returned. If no embeddings were returned, `count` **MUST** be zero.
For local tensor outputs, the shape summary **MUST** describe only the tensor
actually returned.

Malformed or missing provider vectors do not relax the output privacy rule:
instrumentation **MUST NOT** log provider-native output while reporting an
error.

## Required conformance scenarios

SDK implementations **SHOULD** cover these scenarios in their own tests:

| Scenario                                          | Expected result                                                                                                            |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Single text input                                 | One input object and `count: 1` are emitted without vector values.                                                         |
| Text batch                                        | Input objects preserve request order and `count` matches the returned batch size.                                          |
| Local tensor output                               | The compact output reports an ordered array of tensor dimension sizes without vector values.                              |
| Aggregated text and image parts                   | One input object represents the provider's aggregation boundary.                                                           |
| Separate image, audio, video, and document inputs | Separate ordered input objects are emitted, inline inputs become attachments, and `count` matches the returned batch size. |
| Explicit output dimensionality                    | The requested value is captured in input; local tensor runners may also report the returned shape in output.               |
| Usage present vs. absent                          | Reported tokens are captured; unavailable metrics are omitted.                                                             |
| Provider failure                                  | Top-level `error` is populated and provider-native output is not logged.                                                   |
| Partial batch failure                             | `count` matches the number returned and top-level `error` is populated.                                                    |
| Attachment conversion failure                     | The original input is retained and the span is still exported.                                                             |

# SDK support

| ID | Capability | .NET | Go | Java | JS | Python | Ruby | Rust |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| embedding-spans | Embedding instrumentation | no | partial | partial | partial | partial | no | no |

```json
{
  "id": "embeddings",
  "name": "Embedding APIs",
  "category": "LLM APIs"
}
```
