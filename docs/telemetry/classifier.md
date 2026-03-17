# Classifiers

## Overview

Classifiers categorize and label eval outputs. Unlike scorers (numeric 0-1), classifiers produce structured classification items with optional confidence and metadata. Both receive the same arguments (`output`, `expected`, `input`, `metadata`) and run in parallel during evaluations.

Classifications are stored as `Record<string, ClassificationItem[]>` -- a dictionary keyed by classifier name, where each value is an array of items. This supports multiple classifiers producing independent label sets, a single classifier producing multiple labels, and multiple classifiers contributing to the same key.

---

## Public API

### Evaluator Interface

An evaluator **MUST** include at least one of `scores` or `classifiers` (or both). SDKs **MUST** validate this at runtime and raise a clear error if neither is provided, even if the constraint is also enforced at the type level.

```typescript
interface EvaluatorBase<Input, Output, Expected, Metadata> {
  data: () => Dataset<Input, Expected, Metadata>;
  task: (input: Input, hooks: Hooks) => Output | Promise<Output>;
}

type Evaluator<Input, Output, Expected, Metadata> =
  | EvaluatorBase<Input, Output, Expected, Metadata> & {
      scores: EvalScorer<Input, Output, Expected, Metadata>[];
      classifiers?: EvalClassifier<Input, Output, Expected, Metadata>[];
    }
  | EvaluatorBase<Input, Output, Expected, Metadata> & {
      scores?: EvalScorer<Input, Output, Expected, Metadata>[];
      classifiers: EvalClassifier<Input, Output, Expected, Metadata>[];
    };
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
  confidence?: number | null;
  metadata?: Record<string, unknown>;
}
```

### EvalResult

The `classifications` field **MUST** be omitted (not an empty object) when no classifiers are defined or all return `null`.

```typescript
interface EvalResult {
  input: unknown;
  output: unknown;
  expected?: unknown;
  scores?: Record<string, number | null>;
  classifications?: Record<string, ClassificationItem[]>;
  metadata?: Record<string, unknown>;
}
```

---

## Behavior

### Execution

SDKs **MUST** run classifiers in parallel with scorers (e.g., `Promise.all`).

Each classifier **MUST** run inside a traced span with `type: "classifier"` and `name` set to the resolved classifier name:

```typescript
rootSpan.traced(
  (classifierSpan) => {
    const result = await classifierFn({ input, output, expected, metadata });
    classifierSpan.log({ output: result });
    return result;
  },
  {
    name: resolvedClassifierName,
    span_attributes: {
      name: resolvedClassifierName,
      type: "classifier",
    },
  },
);
```

### Name Resolution

SDKs **MUST** resolve classifier name with this precedence:

1. `name` field on the returned `Classification` object(s)
2. `.name` property of the classifier function
3. Fallback: `classifier_${index}`

Items with the same resolved name **MUST** be appended to the same array.

### Validation

Each classification result **MUST** have:
- A `name` that is a non-empty string
- An `id` that is a non-empty string

If validation fails, treat the classifier as failed.

Additional field rules:
- `confidence` is an unconstrained number (no 0-1 range enforced). SDKs **MUST NOT** reject values outside 0-1.
- `metadata` is an unconstrained `Record<string, unknown>`. SDKs **MUST NOT** impose size limits.
- Duplicate `{name, id}` pairs are allowed. Multiple items with the same `id` under the same name key **MUST** all be stored. Deduplication, if needed, is handled at the display layer.
- Order is stable. Items **MUST** be stored in the order they are returned by the classifier.

### Conversion to ClassificationItem

When storing results, SDKs **MUST** convert `Classification` to `ClassificationItem`:

1. Copy `id` as-is
2. Default `label` to `id` if not provided
3. Include `confidence` and `metadata` only if present
4. Omit `name` (it becomes the dictionary key)

### Error Handling

Classifier failures **MUST NOT** abort the evaluation or affect other classifiers/scorers.

On failure:
1. Record the error under `classifier_errors` in eval metadata (maps classifier name to error message)
2. Log the error to the root span's metadata
3. **SHOULD** emit a debug warning

This mirrors the `scorer_errors` pattern.

---

## Wire Format

### ClassificationItem

The storage format for a single classification. Derived from `Classification` by dropping `name` and adding an optional `source`.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | String | **REQUIRED** | Stable identifier for filtering and grouping. |
| `label` | String | **OPTIONAL** | Display label. Defaults to `id`. |
| `confidence` | Number \| null | **OPTIONAL** | Confidence score, typically 0-1. |
| `metadata` | Record\<string, unknown\> | **OPTIONAL** | Arbitrary metadata. |
| `source` | SavedFunctionId \| null | **OPTIONAL** | Function that produced this classification. Set by the platform for online scoring; SDKs MAY omit. |

### Classifications on Events

Stored as a top-level `classifications` field on experiment and log events. **MUST** be `Record<string, ClassificationItem[]>`. **MUST** be omitted when empty.

```json
{
  "classifications": {
    "category": [
      { "id": "greeting", "label": "Greeting", "confidence": 0.91 }
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
      confidence: 0.95,
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
  { name: "sentiment", id: "positive", label: "Positive", confidence: 0.8 },
  { name: "sentiment", id: "enthusiastic", label: "Enthusiastic", confidence: 0.6 },
];
```

### Error Output

When a classifier fails, the result includes:

```json
{
  "metadata": {
    "classifier_errors": {
      "broken_classifier": "must return classifications with a non-empty string name"
    }
  }
}
```
