# Eval spans

This spec defines the trace shape and Braintrust span attributes SDKs emit when running evals. It covers local eval runs and remote eval runs executed by a dev server.

## Trace shape

Each eval case MUST produce one root eval span. The eval span represents one dataset case or inline case, not the whole experiment.

A successful eval case SHOULD have this shape:

```text
eval span
  task span
    user spans   <-- spans created inside the task; may be zero
  score span(s)  <-- at least one
```

## OTel to native SDK attribute mapping

Native SDKs directly set certain attributes on the span JSON. Because OTel only allows setting primitive values, some special Braintrust attributes are mapped to their native counterparts on the backend.

The `_json` variants signal to the backend that the attribute is a JSON string and should be parsed as such.

| OTel attribute                                    | Native field      | Notes                                       |
|---------------------------------------------------|-------------------|---------------------------------------------|
| `braintrust.input`, `braintrust.input_json`       | `input`           |                                             |
| `braintrust.expected`, `braintrust.expected_json` | `expected`        |                                             |
| `braintrust.output`, `braintrust.output_json`     | `output`          |                                             |
| `braintrust.span_attributes`                      | `span_attributes` | json map. also auto-expanded by the backend |

## Span semantic conventions

> **Note:** This section lists the values expected by the native SDKs. OTel SDKs should map to the appropriate values using the mapping section above.

### Eval span

| Property        | Value                           |
|-----------------|---------------------------------|
| name            | `eval`                          |
| input           | present                         |
| expected        | present                         |
| output          | present unless the task errored |
| span_attributes | `{type: eval}`                  |

### Task span

| Property        | Value                           |
|-----------------|---------------------------------|
| name            | `task`                          |
| input           | present                         |
| expected        | present                         |
| output          | present unless the task errored |
| span_attributes | `{type: task}`                  |

### Score span

#### Numeric scorers

| Property        | Value                                                         |
|-----------------|---------------------------------------------------------------|
| name            | `my_custom_scorer_name`                                       |
| span_attributes | `{type: scorer, purpose: scorer, my_custom_scorer_name: 0.8}` |

#### Classifiers

| Property        | Value                                                                 |
|-----------------|-----------------------------------------------------------------------|
| name            | `my_custom_classifier_name`                                           |
| span_attributes | `{type: classifier, purpose: scorer, my_custom_classifier_name: 0.8}` |
