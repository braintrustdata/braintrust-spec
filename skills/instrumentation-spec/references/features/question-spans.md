# Question spans

A `question` span represents one model call that answers typed questions about supplied state.
Instrumentation MUST use the `question` span type and record the call's questions and answers together on that span.

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
name: Question spans
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
