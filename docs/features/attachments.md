# Attachments

Most LLM vendors support attachments (images, pdfs, audio, video, etc).

Often, attachments come in two variants:

- references to an external file (e.g. a link to a png on a server)
- an inline base64 encoded string (e.g. a png in its base64 representation)

External references are usually passed through to braintrust and rendered by the UI.

Base64 media is processed specially by braintrust:

- if the braintrust backend detects a base64 attachment:
    - the attachment is uploaded to the braintrust cloud storage provider (which is often s3)
    - the string is stripped from the span and replaced with a pointer to the uploaded file

This greatly reduces the size of spans with attachments.

(NOTE: The braintrust UI can still render spans with raw base64 attachments, but this is not desired for performance/storage reasons)

This replacement process is done by the Braintrust backend. Some SDKs do this as well to reduce the size of spans sent to our trace collector endpoints.

## base64 span processing

### scanning

The SDK scans the `braintrust.input_json` and `braintrust.output_json` span attributes for base64 attachment data. These attributes contain JSON-serialized LLM conversation messages.

Each LLM vendor encodes attachments differently (data URIs, raw base64 in named fields, etc.). The scanning and replacement logic must support multiple vendor formats and be easy to extend when new formats are added.

Before doing any JSON parsing, use a combined regex heuristic as a fast-path check that covers all supported formats in a single pass. Each format contributes a regex fragment, and they are joined with `|` (deduplicating identical fragments). If nothing matches, skip the span entirely. This avoids paying the cost of a JSON parse on every span.

Use a minimum base64 string length threshold (e.g. 20 characters) in the heuristic to avoid false positives on short strings that happen to look like base64.

### replacement

When the heuristic matches, parse the JSON and walk the tree. The walker should pass the current field name and node to each format's matcher. The first format that matches handles the replacement — no further recursion into that subtree. If no format matches, recurse into children.

The attachment replacement process should be designed so that:

- Each vendor format is defined as a self-contained unit (detection predicate + replacement function).
- Adding support for a new vendor or attachment type is a matter of adding one entry, not modifying shared logic.
- Tests should be structured so that adding a new format without corresponding test data causes a test failure.

Cap the tree-walk recursion at a reasonable depth (e.g. 128) so that pathological deeply-nested input cannot exhaust the stack or otherwise wedge processing. When the cap is hit, return the subtree unchanged.

#### partial-replacement safety

A single span may contain multiple attachments, and the uploader can reject some of them (queue full, uploader shut down due to a prior failure). The walk must not leave the span in a mixed state where some attachments are replaced with references and others are still inline base64 — that produces references whose data never gets uploaded, which is data loss.

If any enqueue call fails during the walk, abort the rewrite and return the original JSON unchanged. The backend can handle inline base64; partial replacements are unrecoverable.

After replacement, the base64 data is replaced with an attachment reference object:

```json
{
  "type": "braintrust_attachment",
  "content_type": "image/png",
  "filename": "attachment.png",
  "key": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
}
```

The `filename` is derived from the MIME type (e.g. `image/png` -> `attachment.png`, `application/pdf` -> `attachment.pdf`).

Where the reference object is placed depends on the vendor format. The Braintrust collector and UI understand these formats.

### vendor-specific notes

These are implementation notes for things that are easy to get wrong. Each vendor's message format and exact replacement behavior is defined by the btx spec YAML files in `spec/test/llm_span/<vendor>/attachments.yaml`.

#### OpenAI

Data URIs (`data:<mime>;base64,<data>`) appear as text node values. Only replace when the **entire** text value is a data URI — if the data URI is embedded in a larger string (e.g. `"Check this: data:image/png;base64,... please"`), do **not** replace it. A good heuristic for "entirely a data URI": the trimmed value starts with `data:` and contains no quotes, backslashes, or spaces.

OpenAI-style content parts place image data under `image_url.url`, file data under `file.file_data`, and audio input data under `input_audio.data`. Replace the raw media leaf with the attachment reference and preserve sibling metadata such as filename, format, or MIME type.

Generated-image output items may contain base64 image data in result fields such as `image_generation_call.result`. Replace the raw result leaf with the attachment reference and preserve compact sibling metadata.

#### Bedrock (Converse API)

Bedrock wraps attachments in a parent block with a type key (`image`, `document`, `video`, `audio`) containing `{"format": "<ext>", "source": {"bytes": "<base64>"}}`. The same `format` string (e.g. `mp4`) can appear in different block types and must resolve to different MIME types (`video/mp4` vs `audio/mp4`). Use the parent block type key to select the correct format-to-MIME mapping. Do not use a single flat format-to-MIME table.

#### Anthropic

Anthropic encodes inline attachments as `{"type": "base64", "media_type": "<mime>", "data": "<base64>"}` inside a `source` object. The entire `source` object is replaced with the attachment reference. The `media_type` field provides the MIME type directly.

#### Gemini

Gemini uses `{"inlineData": {"mimeType": "<mime>", "data": "<base64>"}}` or the snake_case equivalent `{"inline_data": {"mime_type": "<mime>", "data": "<base64>"}}`. The replacement depends on content type:
- **Images** (`image/*`): replace `inlineData`/`inline_data` with `image_url: {url: <ref>}`
- **Non-images**: replace `inlineData`/`inline_data` with `file: {file_data: <ref>}`

### upload flow

Each attachment upload is a three-step process against the Braintrust API:

#### 1. Request a signed upload URL

```
POST {api_url}/attachment
Content-Type: application/json
Authorization: Bearer {api_key}

{
  "key": "<uuid>",
  "filename": "attachment.png",
  "content_type": "image/png",
  "org_id": "<org_id>"
}
```

Response:

```json
{
  "signedUrl": "https://storage.example.com/...",
  "headers": { }
}
```

The `org_id` is resolved by calling the login endpoint (`POST {api_url}/api/apikey/login`) and extracting the first org from the response. Cache the org ID for the lifetime of the uploader, and ensure the resolution itself is single-flight so concurrent uploads don't each hit the login endpoint.

#### 2. Upload data to the signed URL

```
PUT {signed_url}
Content-Type: image/png
{any headers from step 1}

<raw bytes>
```

If the signed URL host ends with `.blob.core.windows.net` (Azure Blob Storage), add the header `x-ms-blob-type: BlockBlob`.

#### 3. Report upload status

```
POST {api_url}/attachment/status
Content-Type: application/json
Authorization: Bearer {api_key}

{
  "key": "<uuid>",
  "org_id": "<org_id>",
  "status": { "upload_status": "done" }
}
```

On failure, report an error status instead:

```json
{
  "key": "<uuid>",
  "org_id": "<org_id>",
  "status": { "upload_status": "error", "error_message": "..." }
}
```

#### Retries

All HTTP requests in the upload flow should use exponential backoff with retry on 5xx errors and network failures. Do not retry 4xx client errors. Reasonable defaults: 8 retries, 500ms initial backoff, doubling each attempt.

### error handling

The attachment replacement is an optimization, not a hard requirement. The Braintrust backend can handle raw base64 data in spans. The error policy depends on the kind of error:

- **Per-span errors** (malformed JSON in `braintrust.input_json`/`braintrust.output_json`, decoder failures on a single value, etc.): silently skip that span and return its original JSON unchanged. Do not shut down the uploader. The heuristic can match on non-LLM spans whose attributes happen to look like base64, and those should not poison the processor for everyone else.
- **Upload-pipeline errors** (signed-URL request fails, signed-URL upload fails after retries, login/org-id resolution fails, worker thread crashes unexpectedly): shut down the uploader so subsequent spans skip attachment processing entirely rather than repeatedly failing. Subsequent spans are exported with inline base64.
- In either case, do not throw exceptions that would prevent the span from being exported.

Log a warning when the uploader shuts itself down due to an upload-pipeline error so operators can observe the fallback to inline base64.

Once the uploader has shut down, any spans already exported with attachment references whose uploads did not complete will refer to missing storage objects. This is an accepted trade-off — partial-replacement safety (see [replacement](#replacement)) only guarantees consistency within a single span's walk, not across spans.

### otel SDK impl

OTel SDKs hook into the span lifecycle via a custom `SpanProcessor`. The attachment processing runs in the `onEnd` callback, which is called synchronously on the thread that ends the span.

#### Span processor

The Braintrust span processor wraps a delegate processor (typically a `BatchSpanProcessor` that exports to the Braintrust collector). In `onEnd`:

1. Read the `braintrust.input_json` and `braintrust.output_json` attributes from the span.
2. Run the attachment scan/replacement on each (see [scanning](#scanning) and [replacement](#replacement)).
3. If either attribute was modified, wrap the span in a transformed span that overrides the attributes with the new values. Pass the transformed span to the delegate.
4. If neither was modified, pass the original span through unchanged.

The regex fast-path means non-attachment spans pay only the cost of a regex match against the raw attribute string, which is negligible.

Note: `onEnd` runs on the app thread. The JSON parsing and base64 decode happen synchronously. In practice this is fine because `span.end()` is typically called right after an LLM API call that already took hundreds of milliseconds.

#### Background uploader

The actual S3 uploads must not block the app thread. Use a background worker with a bounded queue:

- A single daemon thread pulls upload jobs from a `BlockingQueue` and executes the three-step upload flow.
- `enqueue(reference, data)` adds a job to the queue. If the queue is full, it blocks until space is available.
- `forceFlush(timeout)` blocks until all currently-enqueued uploads complete (or timeout). This is used during shutdown to ensure uploads finish before the process exits.
- On upload failure, set a flag that causes subsequent `enqueue` calls to return `false`. The processor detects this and falls back to sending raw base64 data. Continue draining remaining jobs in the queue before stopping.
- If the language supports it, register a shutdown hook so pending uploads complete on process exit. Use a generous timeout (e.g. 120s) since dropping uploads is a bad user experience.

The retry-backoff sleeps inside the upload pipeline must be cancellable by shutdown — otherwise an uploader stuck in exponential backoff can block process exit for tens of seconds past the user's deadline.

Wrap each upload job in a try/catch (or language equivalent) so that an unexpected exception in the upload code does not kill the worker permanently. Treat such crashes as upload failures: account for the job, log, and shut down the uploader.

#### Shutdown sequencing

When the span processor is shut down or flushed:

1. Flush/shutdown the wrapped span exporter first so that all buffered spans (which may contain attachment references) reach the collector.
2. Then drain or shut down the attachment uploader so that the referenced binary data is available in object storage when the collector processes the spans.

If the caller provides a deadline (e.g. a graceful-shutdown budget), the total wait must honor it rather than blocking for the uploader's internal 120s ceiling. If the uploader cannot finish within the caller's deadline, abandon the wait and let the worker continue in the background until the process exits — but never block the caller past their deadline.

`shutdown()` on the uploader must be idempotent (safe to call multiple times). The error-handling policy already produces double-shutdown call paths (uploader self-shutdown on failure + explicit shutdown on process exit).

#### Configuration

Provide a config flag to disable attachment processing entirely (e.g. `BRAINTRUST_AUTO_CONVERT_AI_ATTACHMENTS=false`). When disabled, the span processor skips the scan and passes spans through unmodified. The default should be `true`.

### native SDK impl

Native SDKs should follow the canonical placement and provider mapping rules in [Multimodal / Attachments](../instrumentation-guide.md#multimodal--attachments). This document covers the shared conversion and upload mechanics.
