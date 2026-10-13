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

`probabilities` maps choice keys or score-level keys to numbers in [0, 1]; `confidence` is also a number in [0, 1].
`legend` maps score-level keys to JSON values.
Instrumentation SHOULD preserve these optional fields when returned, including per-answer confidence supplied separately in provider metadata.
Do not fabricate missing confidence, distributions, or legends.

Preserve `noul` answers as numeric `noul` values; `boolean` answers use numeric `probability` values.
A `score` answer is on the question's rubric scale and may be fractional; it MUST NOT be normalized into a Braintrust evaluation score.
Question answers remain in `output.answers` and do not automatically populate top-level `scores` or `classifications`.

The guide's usual timing, error, provenance, and data-capture rules apply.
Record model/provider in `metadata` and reported token usage in the standard token metrics.

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
