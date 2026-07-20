# Remote Eval Parameters: Contracts

## SDK

### Evaluator

#### `parameters`

A map from parameter name to parameter spec, declared in the evaluator definition. This is the source of truth for what parameters exist and what their defaults are.

```pseudocode
evaluator.parameters = {
  "model":       { type: "model", default: "gpt-4",  description: "Model to use" },
  "temperature": { type: "data",  default: 0.7,      description: "Sampling temperature" },
  "max_length":  { type: "data",  default: 100,      description: "Max output length" }
}
```

Each parameter spec:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `default` | `any` | No | Value used when the `POST /eval` request does not include this parameter |
| `description` | `string` | No | Human-readable description shown in the Playground UI |
| `type` | `string` | No | Type hint — `"data"` (default), `"model"`, or `"prompt"`. See `parameter` entry under `GET /list` Response Format. |

#### `task`

A callable that optionally declares a `parameters` argument. When declared, it receives the merged parameter map (request values overlaid on evaluator defaults) as a plain string-keyed object.

Tasks that do not declare `parameters` must continue to work unchanged — the SDK must not pass `parameters` to functions that don't accept it.

**Side effect**: the merged `parameters` map is passed to the task function on every test case invocation during a `POST /eval` run.

#### `scorers`

Local scorer functions follow the same contract as `task` with respect to parameters — they optionally declare `parameters` and receive the same merged map if they do. The SDK must not pass `parameters` to scorers that don't declare it.

Remote scorers (sent by the Playground in the `POST /eval` request) also receive the merged parameters via the SDK's remote scorer invocation mechanism.

**Side effect**: the merged `parameters` map is passed to every scorer function (local and remote) on every test case invocation during a `POST /eval` run.

### Dev Server

#### `GET /list`

##### Request Format

No body. Accepts both `GET` and `POST`.

```
GET /list
Authorization: Bearer <token>
X-Bt-Org-Name: <org>
```

##### Response Format

```
HTTP 200 OK
Content-Type: application/json
```

Body: a JSON object keyed by evaluator name. For each evaluator, the `parameters` field contains a `parameters` object serialized from the evaluator's `parameters` definition, or `null` if the evaluator defines no parameters.

```json
{
  "food-classifier": {
    "scores": [{ "name": "exact_match" }],
    "parameters": {
      "type": "braintrust.staticParameters",
      "schema": {
        "model": {
          "type": "data",
          "schema": { "type": "string" },
          "default": "gpt-4",
          "description": "Model to use"
        },
        "temperature": {
          "type": "data",
          "schema": { "type": "number" },
          "default": 0.7,
          "description": "Sampling temperature"
        }
      },
      "source": null
    }
  },
  "text-summarizer": {
    "scores": [],
    "parameters": null
  }
}
```

**`parameters` object:**

| Field | Type | Description |
|-------|------|-------------|
| `type` | `string` | Always `"braintrust.staticParameters"` for inline (code-defined) parameters |
| `schema` | `Record<string, parameter>` | Map of parameter name to definition |
| `source` | `null` | Always `null` for static parameters. Non-null values reference remotely-stored parameter definitions — out of scope for baseline. |

When the evaluator defines no parameters, set `"parameters": null` or omit the field.

> **Note for existing SDK implementors**: Prior to the introduction of the container format, some SDKs returned the `schema` map directly (i.e. `Record<string, parameter>`) rather than wrapping it in a `parameters` object with `type` and `source` fields. The container was introduced to distinguish static (inline) parameters from dynamic (remotely-stored) ones. If updating an existing SDK, check whether it predates this format and update accordingly.

**`parameter` entry** (each value in `schema`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `string` | Yes | `"data"` for generic values; `"model"` for a model picker; `"prompt"` for a prompt editor. For a baseline implementation, `"data"` is sufficient. |
| `schema` | `object` | No | JSON Schema fragment describing the value shape. Set `type` to `"string"`, `"number"`, `"boolean"`, `"object"`, or `"array"` to match the parameter's value type. Used by the Playground to render appropriate input controls. Omit if the type is unknown or mixed. |
| `default` | `any` | No | Default value. Should match the type described by `schema`. |
| `description` | `string` | No | Human-readable description shown in the Playground UI. |

**Serialization**: each entry in `evaluator.parameters` maps to a `parameter` entry in the `schema` object. The parameter name becomes the key; the spec fields (`default`, `description`, `type`) are preserved as-is.

##### Error Responses

| Status | Condition |
|--------|-----------|
| `401 Unauthorized` | Missing or invalid auth token |

#### `POST /eval`

##### Request Format

```
POST /eval
Content-Type: application/json
Authorization: Bearer <token>
X-Bt-Org-Name: <org>
```

The `parameters` field in the request body carries the user's chosen values from the Playground UI:

```json
{
  "name": "food-classifier",
  "data": { ... },
  "parameters": {
    "model": "gpt-4o",
    "temperature": 0.9
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `parameters` | `Record<string, unknown>` | No | Parameter values chosen by the user. Keys match the evaluator's parameter names. Absent, `null`, and `{}` all mean no overrides were provided. |

See the [Dev Server specification](../server/specification.md) for the full `POST /eval` request schema (all fields beyond `parameters`).

##### Response Format

An SSE stream. The `parameters` field has no effect on the response format — progress, summary, and done events are the same structure as without parameters.

See the [Dev Server specification](../server/specification.md) for the full SSE event schema.

**Side effect**: the merged parameters (request values overlaid on evaluator defaults) are forwarded to the task and all scorers on every test case invocation. Output values in the SSE stream reflect whatever the task produced using those parameters.

##### Error Responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | `parameters` field is present but not a JSON object |
| `401 Unauthorized` | Missing or invalid auth token |
| `404 Not Found` | No evaluator registered with the given `name` |

---

## References

- [Braintrust: Remote evals guide](https://www.braintrust.dev/docs/evaluate/remote-evals)
- [Dev Server specification](../server/specification.md) — full `POST /eval` and `GET /list` schemas
