# Multimodal API Surfaces

This document defines the Braintrust span contract for model APIs whose primary
input or output is media rather than a chat message: image generation and
editing, speech generation, transcription and translation, OCR/document
understanding, video generation, and similar prediction-style APIs.

Attachment discovery, upload, retry, and fallback behavior is defined in
[Attachments](attachments.md). Embedding APIs have an additional contract in
[Embedding APIs](embeddings.md).

## Span model

Auto-instrumentation is subject to the guide's
[eligibility rules](../instrumentation-guide.md#auto-instrumentation-eligibility).
The span requirements below do not authorize auto-instrumentation of excluded
job or task lifecycles.

Each discrete model execution **MUST** produce exactly one `llm` span. A
streaming response is still one model execution and **MUST NOT** produce one
span per chunk.

Every span **MUST** include `metadata.model` and `metadata.provider`. The
resolved model returned by the provider is preferred over the requested model.
If the provider does not return a model, use the requested model.

## Span payload

Implementations **MUST** use the canonical span structures in this document.
Provider-native request and response objects do not replace these structures.

The structures map to the Braintrust span payload as follows:

| Structure | Span field | OTel attribute |
| --- | --- | --- |
| `MediaOperationInput` | `input` | `braintrust.input_json` |
| `MediaOperationOutput` | `output` | `braintrust.output_json` |
| Model and provider identifiers | `metadata.model` and `metadata.provider` | `braintrust.metadata` |
| Model-call span type | `span_attributes.type = "llm"` | `braintrust.span_attributes` |
| Provider failure | top-level `error` | standard span error handling |

OTel attributes contain JSON strings. For example,
`braintrust.input_json` is `JSON.stringify(input)` where `input` is the exact
`MediaOperationInput` object defined below.

The following complete span payload represents one generated image. The raw
image bytes have been uploaded and replaced at their original logical position
with a `braintrust_attachment` reference:

```json
{
  "span_attributes": {
    "type": "llm"
  },
  "input": {
    "operation": "generate",
    "prompt": "A red fox in a snowy forest",
    "parameters": {
      "n": 1,
      "size": "1024x1024"
    }
  },
  "output": {
    "content": [
      {
        "type": "image_url",
        "image_url": {
          "url": {
            "type": "braintrust_attachment",
            "content_type": "image/png",
            "filename": "generated-image.png",
            "key": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
          }
        }
      }
    ]
  },
  "metadata": {
    "model": "example-image-model",
    "provider": "example-provider"
  }
}
```

## Canonical media parts

Every media item in `input.content` and `output.content` **MUST** use one of the
canonical `MediaPart` structures below. Media parts and attachment references
belong in these content arrays, not in `metadata` or a separate attachment
list.

```ts
type AttachmentOrExternal =
  | {
      type: "braintrust_attachment";
      content_type: string;
      filename: string;
      key: string;
    }
  | string
  | { type: "external_attachment"; url: string; [key: string]: unknown }
  | { type: "inline_attachment"; [key: string]: unknown };

type MediaPart =
  | { type: "text"; text: string }
  | {
      type: "image_url";
      image_url: {
        url: AttachmentOrExternal;
        width?: number;
        height?: number;
      };
      purpose?: "input" | "reference" | "mask";
      revised_prompt?: string;
    }
  | {
      type: "file";
      file: {
        filename: string;
        file_data: AttachmentOrExternal;
        byte_size?: number;
      };
    };
```

Inline bytes in any `AttachmentOrExternal` position **MUST** be converted to a
`braintrust_attachment`. Remote URLs **MUST** remain remote references and
**MUST NOT** be fetched solely for tracing.

`width`, `height`, and `byte_size` are allowed only when they are reported by
the provider or can be determined from bytes already available to the
instrumentation. Instrumentation **MUST NOT** fetch, decode, or probe remote
media just to populate them.

## Canonical operation payload

The value of the span's `input` field **MUST** be a `MediaOperationInput`. The
value of the span's `output` field **MUST** be a `MediaOperationOutput` when an
output is available. The same values are JSON-serialized into
`braintrust.input_json` and `braintrust.output_json` by OTel instrumentation.

The canonical payload structures are:

```ts
type MediaOperationInput = {
  operation: string;
  prompt?: string;
  content?: MediaPart[];
  parameters?: Record<string, unknown>;
};

type MediaOperationOutput = {
  content: MediaPart[];
  annotations?: unknown;
};
```

`operation` is the provider-independent operation category, such as
`"generate"`, `"edit"`, `"speech"`, `"transcribe"`, `"translate"`, or `"ocr"`.

`output.annotations` is a free-form JSON value. It **SHOULD** use the
representation that best preserves the useful non-media result for the
operation. Depending on the API and request, it may be:

- a plain text or Markdown string
- provider-returned structured information
- an object or array containing extraction details
- a response conforming to a schema supplied by the user

Binary media belongs in `output.content`, not in `output.annotations`.

Only the parameter keys listed for the applicable API family may be captured.
Unknown provider request fields **MUST NOT** be copied into `parameters`.

Provider failures use the span's top-level `error` field. Safe partial artifacts
may remain in `output.content`, and safe partial annotations may remain in
`output.annotations`.

## Image generation, editing, and variation

Allowed input parameter keys:

- `n`
- `size`
- `aspect_ratio`
- `quality`
- `style`
- `seed`
- `background`
- `output_format`

Text prompts go in `input.prompt`. Reference images and masks go in
`input.content` as image parts. When a provider distinguishes a mask from other
reference images, the corresponding image part may include
`"purpose": "mask"`; other supported purpose values are `"reference"` and
`"input"`.

Generated images go in `output.content` as image parts. The following compact
fields are allowed on a generated image part when reported by the provider:

- `revised_prompt`
- `width`
- `height`

Each returned image **MUST** remain a distinct ordered content part. An SDK
**MUST NOT** log only the first image when the provider returns multiple
results. Its position in `output.content` preserves its provider result order.

## Speech generation

Allowed input parameter keys:

- `voice`
- `format`
- `speed`
- `language`

The text to synthesize goes in `input.prompt`. Generated audio goes in
`output.content` as exactly one file part unless the provider returns multiple
independent audio artifacts.

The file's `filename`, attachment `content_type`, and optional `byte_size`
describe the generated encoding. If a provider returns a stream, the binary
stream rules in [Attachments](attachments.md#binary-output-values-and-streams)
apply.

## Transcription and translation

Allowed input parameter keys:

- `language`
- `prompt`
- `format`
- `timestamp_granularities`

The source audio goes in `input.content` as a file part. Context or bias text
goes in `input.prompt`.

The transcript goes in `output.content` as one text part. Transcript metadata
goes in `output.annotations` using this structure:

```ts
type TranscriptionAnnotations = {
  language?: string;
  duration?: number;
  segments?: unknown[];
  words?: unknown[];
};
```

`duration` is seconds. `segments` and `words` may preserve the provider's
structured timestamp, speaker, and confidence objects. They **MUST NOT**
contain a second copy of the complete input media.

For example, a transcription result has the following span `output`:

```json
{
  "content": [
    {
      "type": "text",
      "text": "Welcome to Braintrust."
    }
  ],
  "annotations": {
    "language": "en",
    "duration": 1.4
  }
}
```

Translation uses the same output structure. `annotations.language` identifies
the output language when reported by the provider.

## OCR and document understanding

Allowed input parameter keys:

- `pages`
- `table_format`
- `include_images`

The source image or document goes in `input.content`. A page selector goes in
`input.parameters.pages`.

The canonical output uses `MediaOperationOutput`. `output.annotations` is
free-form and **SHOULD** preserve the result in the form most useful to the
caller. For example, it may be plain extracted text or Markdown, structured
page/table/bounding-box data returned by the provider, or a response conforming
to an extraction schema supplied by the user. These examples are not an
allowlist.

Returned page, crop, or figure images **MUST** also appear as image parts in
`output.content`, with inline bytes converted to attachments. Annotations may
refer to those content parts but **MUST NOT** duplicate their binary or base64
data.

## Video and long-running media operations

Allowed input parameter keys:

- `duration`
- `size`
- `aspect_ratio`
- `seed`
- `output_format`

Prompts and reference media use the normal input fields. Completed video or
other media artifacts use file parts in `output.content`.

Only calls that return or stream the media result directly are eligible for
auto-instrumentation. APIs that submit a media job and expose its result through
waiting, polling, retrieval, webhooks, or listeners **MUST NOT** be
auto-instrumented. This includes higher-level wrappers that submit and wait or
poll until completion as one user-visible operation.

Such job lifecycles require manual tracing or an explicitly invoked
[manual capture API](../instrumentation-guide.md#manual-capture-for-excluded-apis).
Where possible, capture inputs and start spans at submission, then capture the
caller-supplied media result and end those spans when it arrives. Capture APIs
**MUST NOT** invoke the provider or its SDK to submit work or obtain the result.
For explicitly instrumented operations, if no media artifact is available,
`output.content` is empty. Instrumentation **MUST NOT** perform additional
polling solely to obtain an artifact for tracing.

## Metrics

Specialized media spans emit only metrics reported by the provider or measured
according to the general instrumentation guide:

- `tokens`, `prompt_tokens`, and `completion_tokens`
- `prompt_audio_tokens` and `completion_audio_tokens`
- `completion_image_tokens`
- `time_to_first_token` for streaming model output, measured to the first
  model-generated text token or chunk, or the first content-bearing media event
- `estimated_cost`

Missing usage values **MUST** be omitted rather than fabricated. Byte counts,
dimensions, durations, and artifact counts belong in the canonical payload,
not in `metrics`.
