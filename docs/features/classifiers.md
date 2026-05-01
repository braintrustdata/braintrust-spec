# Classifiers

> **Reference implementation:** [braintrust-sdk-javascript PR #1553](https://github.com/braintrustdata/braintrust-sdk-javascript/pull/1553), updated by [PR #1842](https://github.com/braintrustdata/braintrust-sdk-javascript/pull/1842)

## Overview

Classifiers categorize and label eval outputs. Unlike scorers (numeric 0-1), classifiers produce structured classification items with optional metadata. Both receive the same arguments (`output`, `expected`, `input`, `metadata`) and run in parallel during evaluations.

Classifications are stored as `Record<string, ClassificationItem[]>` -- a dictionary keyed by classifier name, where each value is an array of items. This supports multiple classifiers producing independent label sets, a single classifier producing multiple labels, and multiple classifiers contributing to the same key.

---

## Public API

### Evaluator Interface

An evaluator **MUST** include at least one of `scores` or `classifiers` (or both). Both fields are typed as optional; SDKs **MUST** validate this at runtime and raise a clear error if neither is provided.

```typescript
interface Evaluator<Input, Output, Expected, Metadata> {
  data: () => Dataset<Input, Expected, Metadata>;
  task: (input: Input, hooks: Hooks) => Output | Promise<Output>;

  /**
   * A set of scorer functions. At least one of `scores` or `classifiers` must be provided.
   */
  scores?: EvalScorer<Input, Output, Expected, Metadata>[];

  /**
   * A set of classifier functions. At least one of `scores` or `classifiers` must be provided.
   */
  classifiers?: EvalClassifier<Input, Output, Expected, Metadata>[];
}
```

### EvalClassifier

A classifier function accepts the same arguments as a scorer. It **MAY** return a single `Classification`, an array (multi-label), or `null`. It **MAY** be synchronous or asynchronous.

```typescript
type OneOrMoreClassifications = Classification | Classification[] | null;

type EvalClassifier<Input, Output, Expected, Metadata> = (
  args: EvalScorerArgs<Input, Output, Expected, Metadata>,
) => OneOrMoreClassifications | Promise<OneOrMoreClassifications>;
```

### Classification

Returned by classifier functions. The `name` field is used as the grouping key in the results dictionary and is omitted when converting to the storage format.

```typescript
interface Classification {
  name: string;
  id: string;
  label?: string;
  metadata?: Record<string, unknown>;
}
```

### EvalResult

The `scores` field is always present (may be an empty `{}`). The `classifications` field **MUST** be omitted (not an empty object) when no classifiers are defined, all return `null`, or all fail.

```typescript
interface EvalResult {
  input: unknown;
  output: unknown;
  expected?: unknown;
  error: unknown;
  origin?: ObjectReference;
  scores: Record<string, number | null>;
  classifications?: Record<string, ClassificationItem[]>;
  metadata?: Record<string, unknown>;
}
```

---

## Behavior

### Execution

SDKs **MUST** run classifiers in parallel with scorers (e.g., `Promise.all`).

Each classifier **MUST** run inside a traced span with `type: "classifier"` and `purpose: "scorer"`. The traced span also receives the propagated event from the root span and the scoring arguments (excluding `trace`) as the span's input. The span name is resolved from the classifier function name (or fallback) rather than from returned classification items:

```typescript
rootSpan.traced(
  async (classifierSpan) => {
    const result = await classifierFn(scoringArgs);
    classifierSpan.log({
      output: resultOutput,
      metadata: resultMetadata,
    });
    return result;
  },
  {
    name: resolvedClassifierSpanName,
    spanAttributes: {
      type: "classifier",
      purpose: "scorer",
    },
    propagatedEvent: makeScorerPropagatedEvent(await rootSpan.export()),
    event: { input: scoringArgsForLogging },
  },
);
```

### Name Resolution

SDKs **MUST** resolve names in two places:

1. **Classifier span name**: `.name` property of the classifier function, falling back to `classifier_${index}`.
2. **Classification result grouping key**: `name` field on each returned `Classification` object. If `name` is missing, empty, or not a string, it **MUST** default to the classifier function's resolved span name (from step 1). This is **not** a validation failure.

Items with the same resolved `name` **MUST** be appended to the same array.

### Validation

Each classification result **MUST** be a non-empty object. If the returned value is not a non-empty object, the classifier **MUST** be treated as failed with an error like:

```
When returning structured classifier results, each classification must be a non-empty object.
```

Additional field rules:
- `name` defaults to the classifier function's resolved span name when missing/empty (see Name Resolution above).
- `metadata` is an unconstrained `Record<string, unknown>`. SDKs **MUST NOT** impose size limits.
- Duplicate `{name, id}` pairs are allowed. Multiple items with the same `id` under the same name key **MUST** all be stored. Deduplication, if needed, is handled at the display layer.
- Order is stable. Items **MUST** be stored in the order they are returned by the classifier.

### Conversion to ClassificationItem

When storing results, SDKs **MUST** convert `Classification` to `ClassificationItem`:

1. Copy `id` as-is
2. Copy `label` only if present (omit when `undefined`)
3. Include `metadata` only if present (omit when `undefined`)
4. Omit `name` (it becomes the dictionary key)

### Logging Classifications

When the `classifications` dictionary is non-empty, SDKs **MUST** log it to the root span:

```typescript
rootSpan.log({ classifications });
```

### Error Handling

Classifier failures **MUST NOT** abort the evaluation or affect other classifiers/scorers.

On failure:
1. Record the error under `classifier_errors` in eval metadata (maps classifier name to error message/stack)
2. Log the error to the root span's metadata
3. **SHOULD** emit a debug warning

This mirrors the `scorer_errors` pattern.

---

## Wire Format

### ClassificationItem

The storage format for a single classification. Derived from `Classification` by dropping `name`. `label` remains optional in the wire format.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | String | **REQUIRED** | Stable identifier for filtering and grouping. |
| `label` | String | **OPTIONAL** | Display label. Consumers **MAY** fall back to `id` when omitted. |
| `metadata` | Record\<string, unknown\> | **OPTIONAL** | Arbitrary metadata. |

### Classifications on Events

Stored as a top-level `classifications` field on experiment and log events. **MUST** be `Record<string, ClassificationItem[]>`. **MUST** be omitted when empty.

```json
{
  "classifications": {
    "category": [
      { "id": "greeting", "label": "Greeting" }
    ],
    "sentiment": [
      { "id": "positive", "label": "Positive" },
      { "id": "enthusiastic", "label": "Enthusiastic" }
    ]
  }
}
```

---

## Examples

### Basic

```javascript
Eval("my-project", {
  data: () => [{ input: "Hello!", expected: "Hi there!" }],
  task: async (input) => callMyModel(input),
  scores: [
    ({ output, expected }) => ({
      name: "exact_match",
      score: output === expected ? 1 : 0,
    }),
  ],
  classifiers: [
    ({ output }) => ({
      name: "category",
      id: "greeting",
      label: "Greeting",
    }),
  ],
});
```

### Classifiers Only (No Scores)

```javascript
Eval("my-project", {
  data: () => [{ input: "Hello!", expected: "Hi there!" }],
  task: async (input) => callMyModel(input),
  classifiers: [categoryClassifier, sentimentClassifier],
});
```

### Multi-Label

```javascript
const sentimentClassifier = ({ output }) => [
  { name: "sentiment", id: "positive", label: "Positive" },
  { name: "sentiment", id: "enthusiastic", label: "Enthusiastic" },
];
```

### Classifier with Metadata

```javascript
Eval("my-project", {
  data: [{ input: "hello", expected: "greeting" }],
  task: (input) => input,
  classifiers: [
    () => ({
      name: "category",
      id: "greeting",
      label: "Greeting",
      metadata: { source: "unit-test" },
    }),
  ],
});
```

### Error Output

When a classifier fails, the result includes:

```json
{
  "metadata": {
    "classifier_errors": {
      "broken_classifier": "When returning structured classifier results, each classification must be a non-empty object. Got: null"
    }
  }
}
```
