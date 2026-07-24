# Multimodal API Surfaces

This document defines the Braintrust span contract for model APIs whose primary
input or output is media rather than a chat message: image generation and
editing, speech generation, transcription and translation, OCR/document
understanding, video generation, and similar prediction-style APIs.

Attachment discovery, upload, retry, and fallback behavior is defined in
[Attachments](attachments.md). Embedding and realtime APIs have additional
contracts in [Embeddings](embeddings.md) and [Realtime and live APIs](realtime.md).

## Conformance and API coverage

The payload and lifecycle rules in this document are normative. Once an SDK
instruments an API surface, its spans **MUST** conform to this document.

The provider method registry at the end of this document is advisory. SDKs
**SHOULD** instrument the listed stable inference methods when they already
provide an integration for that provider, but omitting a listed method does not
by itself make the SDK nonconformant.

## Span model

Each discrete model execution **MUST** produce exactly one `llm` span. A
streaming response is still one model execution and **MUST NOT** produce one
span per chunk.

Direct-provider span names use:

```text
<provider>.<resource>.<operation>
```

Framework functions use the exported function name. Realtime span names are
specified separately in [Realtime and live APIs](realtime.md).

Every span **MUST** include `metadata.model` and `metadata.provider`. The
resolved model returned by the provider is preferred over the requested model.
If the provider does not return a model, use the requested model.

## Canonical media parts

Providers with a Braintrust UI normalizer explicitly covering the API family
**MAY** preserve their provider-native request and response objects. Merely
having a chat/message normalizer for a provider does not imply that its
specialized media APIs have one.

All other implementations **MUST** use the canonical structures below.

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
      index?: number;
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

The common payload envelope is:

```ts
type MediaOperationInput = {
  operation: string;
  prompt?: string;
  content?: MediaPart[];
  parameters?: Record<string, unknown>;
};

type MediaOperationOutput = {
  status?: "queued" | "in_progress" | "completed" | "failed" | "cancelled";
  operation_id?: string;
  content: MediaPart[];
  annotations?: unknown;
};
```

`operation` is the provider-independent operation category, such as
`"generate"`, `"edit"`, `"speech"`, `"transcribe"`, `"translate"`, or `"ocr"`.

Only the parameter keys listed for the applicable API family may be captured.
Unknown provider request fields **MUST NOT** be copied into `parameters`.
Provider-native shapes allowed by an explicit UI normalizer are not required to
use the `parameters` object, but remain subject to the general data-capturing
policy.

Errors use the span's top-level `error` field. A failed call may retain partial
`output`, but instrumentation **MUST NOT** represent a provider failure only as
`output.status = "failed"`.

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
- `index`
- `width`
- `height`

Each returned image **MUST** remain a distinct ordered content part. An SDK
**MUST NOT** log only the first image when the provider returns multiple
results.

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

The canonical output is:

```ts
type TranscriptionOutput = {
  text: string;
  language?: string;
  duration?: number;
  segments?: unknown[];
  words?: unknown[];
};
```

`duration` is seconds. `segments` and `words` may preserve the provider's
structured timestamp, speaker, and confidence objects. They **MUST NOT**
contain a second copy of the complete input media.

Translation uses the same output shape. `language` identifies the output
language when reported by the provider.

## OCR and document understanding

Allowed input parameter keys:

- `pages`
- `table_format`
- `include_images`

The source image or document goes in `input.content`. A page selector goes in
`input.parameters.pages`.

The canonical output uses `MediaOperationOutput`. `output.annotations` may
contain the provider's structured page results, limited to:

- page index or number
- extracted text or Markdown
- page dimensions
- tables
- bounding boxes and annotations
- structured extraction results
- references to returned page or crop images

Returned page, crop, or figure images **MUST** also appear as image parts in
`output.content`, with inline bytes converted to attachments. Structured
annotations may refer to those parts by their ordered index but **MUST NOT**
duplicate their base64 data.

## Video and long-running media operations

Allowed input parameter keys:

- `duration`
- `size`
- `aspect_ratio`
- `seed`
- `output_format`

Prompts and reference media use the normal input fields. Completed video or
other media artifacts use file parts in `output.content`.

If a wrapper returns after starting an asynchronous operation, its span closes
with `output.operation_id`, the status available at return time, and an empty
`output.content`. Poll/retrieve calls are separate spans if they are
instrumented.

If a higher-level wrapper waits or polls until completion as one user-visible
operation, it **MAY** keep one `llm` span open and record the final artifact on
that span. Internal polling **MUST NOT** create duplicate LLM spans unless the
polling calls are independently exposed to the user.

## Metrics

Specialized media spans emit only metrics reported by the provider or measured
according to the general instrumentation guide:

- `tokens`, `prompt_tokens`, and `completion_tokens`
- `prompt_audio_tokens` and `completion_audio_tokens`
- `completion_image_tokens`
- `time_to_first_token` for streaming model output
- `estimated_cost`

Missing usage values **MUST** be omitted rather than fabricated. Byte counts,
dimensions, durations, and artifact counts belong in the canonical payload,
not in `metrics`.

## Advisory provider registry

This registry reflects stable JavaScript/TypeScript surfaces associated with
the open multimodal SDK issues as of July 2026. Equivalent methods in other
language SDKs use the same operation contract.

| Provider / framework | API surface | Canonical span name |
| --- | --- | --- |
| OpenAI | `images.generate` | `openai.images.generate` |
| OpenAI | `images.edit` | `openai.images.edit` |
| OpenAI | `images.createVariation` | `openai.images.createVariation` |
| OpenAI | `audio.speech.create` | `openai.audio.speech.create` |
| OpenAI | `audio.transcriptions.create` | `openai.audio.transcriptions.create` |
| OpenAI | `audio.translations.create` | `openai.audio.translations.create` |
| OpenAI | Chat Completions with audio input/output | existing Chat Completion span name |
| OpenAI | Realtime WebSocket/WebRTC session | see [Realtime and live APIs](realtime.md) |
| Google GenAI | `models.generateImages` | `google.models.generateImages` |
| Google GenAI | `models.generateContent` / `generateContentStream` with media output | existing generate-content span name |
| Google GenAI | `models.embedContent` | — |
| Google GenAI | `live.connect` | see [Realtime and live APIs](realtime.md) |
| Vercel AI SDK | `generateImage` | `generateImage` |
| Hugging Face Inference | `textToImage` | `huggingface.textToImage` |
| Mistral | `audio.speech.complete` | `mistral.audio.speech.complete` |
| Mistral | `audio.transcriptions.complete` | `mistral.audio.transcriptions.complete` |
| Mistral | `ocr.process` | `mistral.ocr.process` |
| Groq | `audio.speech.create` | `groq.audio.speech.create` |
| Groq | `audio.transcriptions.create` | `groq.audio.transcriptions.create` |
| Groq | `audio.translations.create` | `groq.audio.translations.create` |

Upstream method names change over time. The registry should be updated when a
provider renames or replaces a stable surface; such a rename does not change
the provider-independent span contract.

Embedding span names are not specified.

Upstream references:

- [OpenAI image generation](https://developers.openai.com/api/docs/guides/image-generation),
  [audio](https://developers.openai.com/api/docs/guides/audio), and
  [Realtime](https://developers.openai.com/api/docs/guides/realtime)
- [Google image generation](https://ai.google.dev/gemini-api/docs/image-generation),
  [embeddings](https://ai.google.dev/gemini-api/docs/embeddings), and
  [Live API](https://ai.google.dev/gemini-api/docs/live)
- [Vercel AI SDK `generateImage`](https://ai-sdk.dev/docs/reference/ai-sdk-core/generate-image)
- [Hugging Face inference API](https://huggingface.co/docs/huggingface.js/en/inference/README)
- [Mistral audio](https://docs.mistral.ai/capabilities/audio/) and
  [OCR](https://docs.mistral.ai/capabilities/document_ai/basic_ocr)
- [Groq TypeScript API](https://github.com/groq/groq-typescript/blob/main/api.md)

## Required implementation scenarios

SDK implementations should cover these scenarios in their own tests:

| Scenario | Expected result |
| --- | --- |
| Multiple generated images | Order is preserved and each result becomes a distinct attachment. |
| Image edit with source and mask | Both inputs are captured with their purpose and bytes are not duplicated. |
| Speech returned as buffer vs stream | Both forms produce the same canonical output shape. |
| Timestamped/diarized transcription | Text, language, timestamps, and speaker data are retained; source audio is attached. |
| OCR with returned page images | Images are attached and structured annotations contain no base64 duplicate. |
| Enqueue-only video call | Operation ID/status are recorded and no final artifact is fabricated. |
| Provider failure with partial output | Safe partial output is retained and top-level `error` is populated. |
