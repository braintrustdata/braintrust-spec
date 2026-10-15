# Decision spans

A `decision` span represents one model call that answers typed questions about supplied state.
Instrumentation MUST emit `span_attributes.type: "decision"` and record the call's questions and answers together on that span.
These spans were previously called `question` spans; that type remains supported for compatibility with existing traces, but new instrumentation MUST emit `decision`.

## Input and output

`input` MUST have the shape `{ "state": <JSON value>, "questions": [...] }` and successful `output` MUST have the shape `{ "answers": [...] }`.
The question and answer arrays are non-empty, with a non-empty string `id` unique within each array.
Answers identify their corresponding questions by `id`, not array position.
Instrumentation MUST convert provider maps keyed by question ID into these arrays, preserving the keys as `id`.

Each question contains `id`, `type`, `instructions`, and the type-specific `criteria` below.
`state`, `instructions`, and criteria values MAY be any JSON value, including structured objects, arrays, and `null`.
Each answer contains `id`, `type`, and the corresponding result fields below.

| `type`    | Question `criteria`                                                    | Required answer field           | Optional answer fields                  |
| --------- | ---------------------------------------------------------------------- | ------------------------------- | --------------------------------------- |
| `noul`    | Optional object mapping labels such as `true` / `false` to JSON values | `noul`: number in [0, 1]        | —                                       |
| `boolean` | Optional object mapping labels such as `true` / `false` to JSON values | `probability`: number in [0, 1] | —                                       |
| `choice`  | Object mapping choice keys to JSON values                              | `choice`: string                | `probabilities`, `confidence`           |
| `score`   | Ordered array of at least two JSON values describing score levels      | `score`: finite number          | `legend`, `probabilities`, `confidence` |
| `box`     | Not accepted                                                          | `box`: object with four edges   | `confidence`: number in [0, 1] or `null` |

`probabilities` maps choice keys or score-level keys to numbers in [0, 1]; numeric `confidence` is also a number in [0, 1].
`legend` maps score-level keys to JSON values.
Instrumentation SHOULD preserve these optional fields when returned, including per-answer confidence supplied separately in provider metadata.
Do not fabricate missing confidence, distributions, or legends.

Preserve `noul` answers as numeric `noul` values; `boolean` answers use numeric `probability` values.
A `score` answer is on the question's rubric scale and may be fractional; it MUST NOT be normalized into a Braintrust evaluation score.
Question answers remain in `output.answers` and do not automatically populate top-level `scores` or `classifications`.

The guide's usual timing, error, provenance, and data-capture rules apply.
Record model/provider in `metadata` and reported token usage in the standard token metrics.

## Image boxes

A `box` question locates a target in an input image.
It has `id`, `type: "box"`, and `instructions`, without `criteria`.
Its answer has the same `id`, `type: "box"`, and a `box` object:

```ts
type BoxAnswer = {
  id: string;
  type: "box";
  box: {
    top: number;
    bottom: number;
    left: number;
    right: number;
  };
  confidence?: number | null;
};
```

The edges are finite numbers in [0, 1], measured from the image's top-left corner.
`top` and `bottom` are fractions of image height; `left` and `right` are fractions of image width.
A valid box has `top < bottom` and `left < right`.

Adapters MUST normalize provider coordinates to this representation when the provider uses different units or a different coordinate layout.
Conversion MUST use known provider semantics and image dimensions already available to instrumentation; do not guess dimensions or fetch images solely for conversion.
Preserve numeric precision without rounding or clamping.
Coordinates already in the canonical representation MUST remain unchanged.
Instrumentation MUST preserve numeric confidence, including zero, and explicit `null`; absent confidence stays absent.
This nullable field is specific to box answers and does not change the other answer contracts.
Confidence MUST NOT become a Braintrust evaluation score or be used by instrumentation to filter answers.

A call containing boxes MUST remain one `decision` span, including when mixed with other question types.
Keep all questions and answers, associating them by `id` even when the provider returns them in a different order.
Boxes remain structured values in `output.answers`; they are not generated images or OCR annotations.
Instrumentation MUST NOT create crops, draw overlays, or attach a second copy of the input image to each answer.

Each box answer represents one region.
Low confidence does not imply that the target is absent.
Applications can ask a separate presence question, but instrumentation MUST retain both answers even when the presence probability or the box's confidence is low.
It MUST NOT synthesize a presence question, a null box, or an image identifier inferred from instruction text.
The original state and instructions retain the image context; images follow the [attachment contract below](#attachments).

These constraints describe valid captured results, not an additional validation layer around the provider.
An unexpected provider value MUST NOT cause instrumentation to throw into application code, discard the entire span, or repair coordinates silently.
Preserve JSON-representable returned values for diagnosis and follow the guide's normal error handling when the provider itself rejects the call.
If coordinates cannot be normalized because their semantics or required dimensions are unavailable, preserve the original JSON-representable answer for diagnosis rather than inventing a canonical box.

### Example

This is the logged payload after attachment conversion for an image in the supplied state.
The answer order deliberately differs from the question order.

```json
{
  "span_attributes": { "type": "decision" },
  "metadata": { "provider": "example-provider", "model": "example-model" },
  "input": {
    "state": {
      "photo": {
        "type": "braintrust_attachment",
        "content_type": "image/png",
        "filename": "attachment.png",
        "key": "550e8400-e29b-41d4-a716-446655440000"
      }
    },
    "questions": [
      {
        "id": "label_present",
        "type": "noul",
        "instructions": "Is there a shipping label in `photo`?"
      },
      {
        "id": "label_bounds",
        "type": "box",
        "instructions": "The shipping label in `photo`"
      }
    ]
  },
  "output": {
    "answers": [
      {
        "id": "label_bounds",
        "type": "box",
        "box": { "top": 0.12, "bottom": 0.48, "left": 0.31, "right": 0.76 },
        "confidence": 0.87
      },
      { "id": "label_present", "type": "noul", "noul": 0.98 }
    ]
  }
}
```

### Conformance scenarios

| Scenario | Expected behavior |
| -------- | ----------------- |
| A box question and answer | Preserve `type: "box"`, the question's instructions, all four edges, and the shared ID; do not add `criteria`. |
| Box mixed with Noul, Boolean, Choice, or Score | One decision span contains every question and answer; existing answer types retain their shapes. |
| Multiple boxes and images, reordered answers | Each answer stays paired with its question by ID; preserve image locations and instructions without guessing an image-to-box mapping. |
| Coordinates at 0 or 1, or with fractional precision | Preserve exact numeric values without rounding or pixel conversion. |
| Provider returns pixel coordinates or an origin/width/height layout | Normalize to fractional edges using known semantics and available dimensions; leave the application-visible result unchanged. |
| Coordinate semantics or required dimensions are unavailable | Preserve the original answer for diagnosis without guessing a canonical box or fetching an image. |
| Confidence is zero, null, or absent | Preserve zero and explicit null; omit an absent field; retain the box in every case. |
| Presence Noul is low | Preserve both the Noul and the returned box; do not infer not-found or suppress output. |
| Image capture or upload fails | Apply the shared attachment fallback; retain box answers and export the span. |
| Returned coordinates violate the expected range or ordering | Preserve JSON-representable values for diagnosis; do not repair them or fail the application call. |
| Provider rejects the model, header, image, or question | Use normal error capture; do not retry with altered inputs or fabricate a box. |

## Attachments

Decision spans MUST follow the shared [attachment contract](../instrumentation-guide.md#multimodal--attachments).
Attachment processing MUST recursively cover media in the decision payload, including nested `input.state`, question `instructions`, and `criteria` values.
Replace inline media with `braintrust_attachment` references at the original media locations, preserving surrounding objects, text, and array order.
Do not add a separate attachment list or move media into `metadata`.
The `{ "state": ..., "questions": [...] }` input and `{ "answers": [...] }` output shapes remain unchanged.

Preserve existing `braintrust_attachment`, `external_attachment`, and `inline_attachment` references.
Preserve remote URLs without fetching them solely to create attachments.
Conversion applies only to the logged payload and MUST NOT change the model request.

Use the shared [scanning, upload, retry, and fallback rules](attachments.md), including [all-or-nothing per-span fallback](attachments.md#partial-replacement-safety).
If media cannot be decoded or its MIME type cannot be determined, leave the value unchanged.
Conversion or upload failures MUST NOT prevent span export and MUST preserve the original payload according to the shared fallback contract.
Automatic uploads MUST run after [span customizers](span-customizers.md), so removing or redacting media prevents its upload.

### Example

The following excerpt shows the logged state before and after attachment conversion; `input.questions` and `output.answers` follow the existing typed-question contract.
The state fields are illustrative; attachment handling does not require a particular state schema.
The data URL's bytes are abbreviated for readability.

```diff
 {
   "input": {
     "state": {
       "description": "Inspect this product for damage.",
-      "photo": "data:image/png;base64,<base64>"
+      "photo": {
+        "type": "braintrust_attachment",
+        "content_type": "image/png",
+        "filename": "attachment.png",
+        "key": "550e8400-e29b-41d4-a716-446655440000"
+      }
     }
   }
 }
```

### Conformance scenarios

| Scenario | Expected behavior |
| -------- | ----------------- |
| Mixed text and multiple inline images | Each media leaf becomes an attachment reference; text, array order, and question/answer associations are preserved. |
| Nested media in state, instructions, or criteria | Media is converted recursively without flattening surrounding objects or arrays. |
| Existing attachment references and remote URLs | References and URLs are preserved without re-uploading attachments or fetching remote media. |
| Invalid media or unknown MIME type | The original value is retained. |
| Attachment conversion, enqueue, or upload failure | The shared fallback contract preserves the original payload and span export continues; an enqueue failure aborts the per-span rewrite. |
| Media removed or redacted by a customizer | Removed media is not automatically uploaded. |
| Text-only decision | The existing input/output shape is retained without attachment fields. |

## Examples

Input and output for a call with three questions:

```json
{
  "input": {
    "state": { "message": "I was charged twice. Please refund me today." },
    "questions": [
      {
        "id": "duplicate_charge",
        "type": "noul",
        "instructions": "Does the customer report a duplicate charge?"
      },
      {
        "id": "category",
        "type": "choice",
        "instructions": "Which team should handle this?",
        "criteria": { "billing": "Payments and refunds", "technical": null }
      },
      {
        "id": "urgency",
        "type": "score",
        "instructions": "How urgent is this request?",
        "criteria": ["Routine", "Soon", "Urgent"]
      },
      {
        "id": "fraudulent",
        "type": "boolean",
        "instructions": "Does the charge look fraudulent?"
      }
    ]
  },
  "output": {
    "answers": [
      { "id": "duplicate_charge", "type": "noul", "noul": 0.99 },
      {
        "id": "category",
        "type": "choice",
        "choice": "billing",
        "probabilities": { "billing": 0.95, "technical": 0.05 },
        "confidence": 0.8
      },
      {
        "id": "urgency",
        "type": "score",
        "score": 1.8,
        "legend": { "0": "Routine", "1": "Soon", "2": "Urgent" },
        "probabilities": { "0": 0, "1": 0.2, "2": 0.8 }
      },
      { "id": "fraudulent", "type": "boolean", "probability": 0.99 }
    ]
  }
}
```

# SDK support

```yaml
id: question-spans
name: Decision spans
category: Tracing
support:
  question-span-type:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  input-output-shape:
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
  typed-answers:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  box-answers:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  answer-metadata:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  rubric-scores:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
```
