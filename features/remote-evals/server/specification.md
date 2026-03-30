# Braintrust Remote Eval Dev Server -- Technical Specification

**Version:** 1.0
**Date:** 2026-03-13
**Status:** Prescriptive specification for implementing the Remote Eval Dev Server feature

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Architecture](#2-system-architecture)
3. [API Contract](#3-api-contract)
4. [Data Model](#4-data-model)
5. [Authentication](#5-authentication)
6. [SSE Streaming Protocol](#6-sse-streaming-protocol)
7. [Eval Execution Flow](#7-eval-execution-flow)
8. [CORS Policy](#8-cors-policy)
9. [OTel vs Non-OTel SDK Considerations](#9-otel-vs-non-otel-sdk-considerations)
10. [Implementation Checklist](#10-implementation-checklist)
11. [References](#11-references)

---

## 1. Overview

### 1.1 Purpose

The Braintrust Remote Eval Dev Server enables users to run evaluations from the Braintrust web UI against code running in their own local application. Instead of pushing code to a remote environment, users define **evaluators** locally (a task function paired with scoring functions), start a lightweight HTTP server, and the Braintrust UI sends eval requests to it over the network.

This bridges the gap between local development and the Braintrust evaluation platform: users iterate on their AI task code locally while leveraging Braintrust's UI for dataset management, experiment tracking, score visualization, and comparison.

### 1.2 How It Works

```
 Braintrust Web UI                          Developer's Machine
+---------------------+                  +------------------------+
|                     |   HTTP/SSE       |   Dev Server (:8300)   |
|  Playground /       | ---------------> |                        |
|  Eval Runner        |   POST /eval     |  +------------------+  |
|                     | <--------------- |  | Evaluator        |  |
|  - Dataset picker   |   SSE stream     |  |  - task()        |  |
|  - Score display    |                  |  |  - scorers[]     |  |
|  - Experiment view  |   GET /list      |  +------------------+  |
|                     | ---------------> |                        |
|                     | <--------------- |  +------------------+  |
|                     |   JSON           |  | Your App Code    |  |
+---------------------+                  |  |  - Models        |  |
                                         |  |  - Services      |  |
                                         |  |  - DB Access     |  |
                                         +--+------------------+--+
                                                    |
                                                    | OTLP / API
                                                    v
                                         +------------------------+
                                         | Braintrust API         |
                                         | (span ingest,          |
                                         |  experiment storage)   |
                                         +------------------------+
```

### 1.3 Illustrative Example

A developer has a food classification model they want to evaluate:

```
# 1. Define an evaluator
evaluator = Evaluator(
    task = (input) => MyModel.classify(input),
    scorers = [
        Scorer("exact_match", (expected, output) => output == expected ? 1.0 : 0.0)
    ]
)

# 2. Register it with the dev server
server = DevServer(
    evaluators = { "food-classifier": evaluator },
    auth = ClerkToken
)

# 3. Start on port 8300
server.listen(port=8300, host="0.0.0.0")
```

Then in the Braintrust web UI:
1. Open the Playground or Eval Runner
2. Select a dataset (or provide inline test cases)
3. Click "Run" -- the UI sends `POST /eval` to `localhost:8300`
4. Results stream back in real-time via SSE
5. Scores and spans appear in the Braintrust experiment view

### 1.4 Key Design Principles

- **Port 8300** is the default/expected port the Braintrust UI connects to
- **Evaluators are named** -- names appear in the UI and are used to dispatch eval requests
- **SSE streaming** -- results stream back one test case at a time for real-time UI updates
- **Auth flows through the browser** -- the UI forwards the user's Clerk session token to the dev server, which validates it and uses it to log results to Braintrust
- **Scores flow through spans** -- in OTel-based SDKs, scores are recorded as span attributes and exported via OTLP, not embedded in SSE progress events

---

## 2. System Architecture

### 2.1 Component Diagram

```
+------------------------------------------------------------------+
|                        Dev Server                                 |
|                                                                   |
|  +------------------+                                             |
|  | CORS Middleware   |  Validates Origin against *.braintrust.dev |
|  +--------+---------+                                             |
|           |                                                       |
|  +--------v---------+                                             |
|  | Auth Middleware   |  Validates Bearer token via Clerk login    |
|  +--------+---------+  Sets auth context on request              |
|           |                                                       |
|  +--------v---------+                                             |
|  | Router            |  Dispatches: GET /, GET|POST /list,       |
|  +--+-----+-----+---+              POST /eval, OPTIONS *         |
|     |     |     |                                                 |
|  +--v-+ +-v--+ +v---------+                                      |
|  |Health| |List| |  Eval   |                                      |
|  +-----+ +----+ +----+----+                                      |
|                       |                                           |
|            +----------v-----------+                               |
|            | Evaluator.run()      |                               |
|            |  - Execute task      |                               |
|            |  - Run scorers       |                               |
|            |  - Report progress   |                               |
|            +----------+-----------+                               |
|                       |                                           |
|            +----------v-----------+                               |
|            | SSE Writer           |                               |
|            |  - progress events   |                               |
|            |  - summary event     |                               |
|            |  - done event        |                               |
|            +----------------------+                               |
+------------------------------------------------------------------+
```

### 2.2 Middleware Stack (outermost first)

| Order | Middleware | Responsibility |
|-------|-----------|---------------|
| 1 | CORS | Validate origin, add CORS headers, handle OPTIONS preflight |
| 2 | Auth | Validate Bearer token, set auth context on request |
| 3 | Router | Dispatch to handler based on method + path |

### 2.3 Request Flow (End-to-End)

```
Browser (Braintrust UI)
  |
  |  POST /eval
  |  Authorization: Bearer <clerk-session-token>
  |  X-Bt-Org-Name: my-org
  |  Origin: https://www.braintrust.dev
  |
  v
CORS Middleware
  |  - Check Origin matches *.braintrust.dev
  |  - Add access-control-allow-origin header
  v
Auth Middleware
  |  - Extract Bearer token
  |  - POST token to {app_url}/api/apikey/login
  |  - Set auth context: { api_key, org_id, org_name, app_url, api_url }
  v
Router
  |  - Match "POST /eval"
  v
Eval Handler
  |  1. Parse JSON body
  |  2. Validate required fields (name, data)
  |  3. Look up evaluator by name
  |  4. Resolve data source (inline / dataset_id / dataset_name)
  |  5. Resolve remote scorers (function_id references)
  |  6. Resolve parent span context
  |  7. Build State from auth context (cached, LRU max 64)
  |  8. Return 200 with SSE body
  v
SSE Body (streams as response)
  |  9. Execute evaluator.run(cases, on_progress: callback, ...)
  |     For each test case:
  |       a. Run task(input) -> output
  |       b. Run scorers(input, expected, output) -> scores
  |       c. Fire on_progress callback -> SSE "progress" event
  |  10. Flush OTLP spans (OTel SDKs only)
  |  11. Compute averaged scores from results
  |  12. Send SSE "summary" event
  |  13. Send SSE "done" event
  v
Browser receives SSE stream
  - Updates UI per progress event
  - Shows final scores from summary
  - Fetches experiment spans from Braintrust API
```

---

## 3. API Contract

### 3.1 `GET /` -- Health Check

Simple liveness probe.

**Request:** No body required.

**Response:**
```
HTTP/1.1 200 OK
Content-Type: application/json

{"status": "ok"}
```

> **Note:** The response body is not critical -- any 200 response indicates the server is running. Returning JSON `{"status": "ok"}` is recommended for consistency.

### 3.2 `GET /list` or `POST /list` -- List Evaluators

Returns all registered evaluators with their scorer names and parameter definitions. The UI calls this to discover what evaluators are available and render configuration controls.

**Request:** No body required. Accepts both GET and POST.

**Response:**
```
HTTP/1.1 200 OK
Content-Type: application/json
```

**Response body** -- a JSON object keyed by evaluator name:

```json
{
  "food-classifier": {
    "scores": [
      { "name": "exact_match" },
      { "name": "relevance" }
    ],
    "parameters": {
      "type": "braintrust.staticParameters",
      "schema": {
        "temperature": {
          "type": "data",
          "schema": { "type": "number" },
          "default": 0.7,
          "description": "LLM temperature"
        },
        "model": {
          "type": "data",
          "schema": { "type": "string" },
          "default": "gpt-4",
          "description": "Model to use"
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

**Field definitions:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scores` | `Array<{name: string}>` | Yes | List of local scorer names registered on the evaluator |
| `parameters` | `ParametersContainer \| null` | No | Omit or set null when no parameters are defined |

**ParametersContainer** (for static/inline parameters):

| Field | Type | Description |
|-------|------|-------------|
| `type` | `string` | Always `"braintrust.staticParameters"` for inline params |
| `schema` | `Record<string, ParameterDef>` | Map of parameter name to definition |
| `source` | `null` | Always null for static parameters |

**ParameterDef:**

| Field | Type | Description |
|-------|------|-------------|
| `type` | `string` | `"data"` for user-configurable data parameters |
| `schema` | `object` | JSON Schema fragment (e.g., `{"type": "number"}`) |
| `default` | `any` | Default value |
| `description` | `string` | Human-readable description |

The UI also recognizes `"prompt"` and `"model"` parameter types within `ParameterDef`, and a `"braintrust.parameters"` container type with a `source` referencing a remote parameters function. For an initial implementation, supporting `"braintrust.staticParameters"` with `"data"` type is sufficient.

### 3.3 `POST /eval` -- Run Evaluation

Executes an evaluator against provided test data and streams results via Server-Sent Events (SSE).

**Request:**
```
POST /eval
Content-Type: application/json
Authorization: Bearer <clerk-session-token>
X-Bt-Org-Name: <org-name>
```

**Request body:**

```json
{
  "name": "food-classifier",
  "data": { ... },
  "experiment_name": "exp-2026-03-13",
  "project_id": "proj-uuid-here",
  "scores": [ ... ],
  "parent": { ... },
  "parameters": { ... },
  "stream": true
}
```

**Field definitions:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | **Yes** | Name of the evaluator to run (must match a registered evaluator) |
| `data` | `DataSource` | **Yes** | Test data source -- exactly one sub-field must be set |
| `experiment_name` | `string` | No | Name for the experiment in Braintrust |
| `project_id` | `string` | No | UUID of the Braintrust project |
| `scores` | `Array<ScorerRef>` | No | Remote scorer references (from the UI's scorer picker) |
| `parent` | `ParentContext` | No | Parent span context (typically from a Playground session) |
| `parameters` | `Record<string, unknown>` | No | Parameter values to pass to the evaluator (keys match the evaluator's parameter schema) |
| `stream` | `boolean` | No | Whether to use SSE streaming (default: true). Non-streaming mode may not be supported by all SDKs. |

**DataSource** (exactly one field must be present):

| Field | Type | Description |
|-------|------|-------------|
| `data` | `Array<TestCase>` | Inline test cases |
| `dataset_id` | `string` | UUID of a Braintrust dataset |
| `dataset_name` | `string` | Name of a dataset (optionally with `project_name`) |
| `project_name` | `string` | Project owning the dataset (used with `dataset_name`) |

**TestCase:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input` | `any` | Yes | The input to the task function |
| `expected` | `any` | No | The expected output (ground truth) |
| `metadata` | `object` | No | Additional metadata for the case |
| `tags` | `Array<string>` | No | Tags for filtering/grouping |

**ScorerRef:**

| Field | Type | Description |
|-------|------|-------------|
| `function_id` | `FunctionId` | Identifies the remote scorer function (see FunctionId union below) |
| `name` | `string` | Display name of the scorer |

**FunctionId** is a union type. The UI may send any of these forms:

| Variant | Fields | Description |
|---------|--------|-------------|
| By ID | `{ function_id: string, version?: string }` | Reference by UUID. **Most common form.** |
| By slug | `{ project_name: string, slug: string, version?: string }` | Reference by project + slug |
| Global | `{ global_function: string, function_type?: string }` | Reference to a global/built-in function |
| By prompt session | `{ prompt_session_id: string, prompt_session_function_id: string, version?: string }` | Reference within a prompt session |
| Inline context | `{ inline_context: { runtime: string, version: string } }` | Inline function definition |

The most common form sent by the UI is the "By ID" variant: `{ function_id: "<uuid>" }`. Note that this means the `function_id` field of `ScorerRef` is itself an object with a `function_id` string property (i.e., the ID is nested). Implementations must handle this nesting: `scores[i].function_id.function_id` is the actual UUID. Handle both the nested object and plain string forms defensively.

**ParentContext** (can be an object or a serialized string):

When an object:

| Field | Type | Description |
|-------|------|-------------|
| `object_type` | `string` | Type of parent object. Values: `"project_logs"`, `"experiment"`, `"playground_logs"` |
| `object_id` | `string` | UUID of the parent object |
| `row_ids` | `object \| null` | Optional row IDs: `{ id: string, span_id: string, root_span_id: string }` |
| `propagated_event` | `object \| null` | Optional propagated event data |
| `propagated_event.span_attributes.generation` | `string` | Optional generation identifier |

When a string, it is a serialized span components reference (used by the TypeScript SDK's native tracing).

For OTel-based implementations, hardcode the parent type to `"playground_id"` when constructing the span attribute (i.e., `braintrust.parent = "playground_id:<object_id>"`), regardless of the `object_type` sent in the request. This is required for the OTLP backend to correctly associate spans with playground sessions. Non-OTel implementations pass the parent through to their native tracing system as-is.

**Response:**
```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

See [Section 6: SSE Streaming Protocol](#6-sse-streaming-protocol) for the event format.

**Error responses:**

| Status | Condition | Body |
|--------|-----------|------|
| 400 | Invalid JSON body | `{"error": "Invalid JSON body"}` |
| 400 | Missing `name` field | `{"error": "Missing required field: name"}` |
| 400 | Missing `data` field | `{"error": "Missing required field: data"}` |
| 400 | Multiple data sources | `{"error": "Exactly one data source required"}` |
| 401 | Auth failure | `{"error": "Unauthorized"}` |
| 404 | Evaluator not found | `{"error": "Evaluator '<name>' not found"}` |
| 405 | Wrong HTTP method | `{"error": "Method not allowed"}` |

### 3.4 `OPTIONS *` -- CORS Preflight

Handled by the CORS middleware. See [Section 8: CORS Policy](#8-cors-policy).

---

## 4. Data Model

### 4.1 Evaluator

An evaluator is the core unit of the dev server. It pairs a **task** (the code being evaluated) with **scorers** (functions that grade the output).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task` | `Callable(input) -> output` | Yes | The function under test. Receives `input` (from test case) and returns an output. |
| `scorers` | `Array<Scorer>` | No | Local scoring functions. Each must have a unique name. |
| `parameters` | `Record<string, ParameterDef>` | No | Configurable parameters exposed in the UI. |

**Task signature:** The task callable receives a single keyword/named argument `input` and returns any JSON-serializable value.

### 4.2 Scorer

A scorer evaluates the quality of a task's output.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string` | Unique identifier. Displayed in the UI and used as the key in score maps. |
| `call(...)` | `Callable` | Scoring function. Receives keyword arguments: `input`, `expected`, `output`, `metadata`, `trace`. Returns a numeric score (typically 0.0-1.0). |

### 4.3 Scorer::ID (Remote Scorer Reference)

A reference to a scorer function stored in Braintrust, resolved at eval time.

| Field | Type | Description |
|-------|------|-------------|
| `function_id` | `string` | UUID of the scorer function in Braintrust |
| `version` | `string \| null` | Optional pinned version |

### 4.4 Dataset::ID (Remote Dataset Reference)

A reference to a dataset stored in Braintrust, fetched at eval time.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | UUID of the dataset in Braintrust |

### 4.5 Eval Result

Returned by the evaluator after running all test cases.

| Field | Type | Description |
|-------|------|-------------|
| `experiment_id` | `string \| null` | UUID of the created experiment (null if no API state) |
| `experiment_name` | `string \| null` | Name of the experiment |
| `project_id` | `string \| null` | UUID of the project |
| `project_name` | `string \| null` | Name of the project |
| `permalink` | `string \| null` | URL to view the experiment in Braintrust |
| `errors` | `Array<string>` | List of errors that occurred during evaluation |
| `duration` | `float` | Wall-clock duration in seconds |
| `scores` | `Record<string, Array<number>>` | Raw score arrays per scorer name |
| `scorer_stats` | `Record<string, ScorerStats>` | Computed statistics per scorer |

### 4.6 ScorerStats

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string` | Scorer name |
| `score_mean` | `float` | Average score across all test cases |

### 4.7 Auth Context

Set by the auth middleware on the request, consumed by the eval handler to build SDK state.

| Field | Type | Description |
|-------|------|-------------|
| `api_key` | `string` | The Clerk session token (used as API key) |
| `org_id` | `string` | Organization UUID |
| `org_name` | `string` | Organization name |
| `app_url` | `string` | Braintrust app URL (e.g., `https://www.braintrust.dev`) |
| `api_url` | `string` | Braintrust API URL (e.g., `https://api.braintrust.dev`) |

---

## 5. Authentication

### 5.1 Auth Flow

The Braintrust web UI authenticates users via Clerk. When making requests to the dev server, the browser forwards the Clerk session token as a Bearer token. The dev server validates this token against the Braintrust app server.

```
Browser                    Dev Server                 Braintrust App
  |                           |                           |
  |  POST /eval               |                           |
  |  Authorization:           |                           |
  |    Bearer <clerk-token>   |                           |
  |  X-Bt-Org-Name: my-org   |                           |
  |-------------------------->|                           |
  |                           |  POST /api/apikey/login   |
  |                           |  {"token": "<clerk-token>"}|
  |                           |-------------------------->|
  |                           |                           |
  |                           |  200 OK                   |
  |                           |  {"org_id": "...",        |
  |                           |   "org_name": "...",      |
  |                           |   "api_url": "..."}       |
  |                           |<--------------------------|
  |                           |                           |
  |  SSE response stream      |                           |
  |<--------------------------|                           |
```

### 5.2 Token Extraction

The UI sends the auth token via one of two headers, depending on the organization's configuration:

1. **`X-Bt-Auth-Token`** header (preferred, used when the org has a custom firewall bearer token)
2. **`Authorization: Bearer <token>`** header (standard path)

In some configurations, the UI sends both -- `Authorization` carries a firewall token while `X-Bt-Auth-Token` carries the actual Braintrust auth token.

**Extraction priority:** Check `X-Bt-Auth-Token` first, then fall back to extracting the Bearer token from `Authorization`.

### 5.3 Token Validation

Validate the token by sending a POST request to the Braintrust app server:

```
POST {app_url}/api/apikey/login
Content-Type: application/json

{"token": "<clerk-session-token>"}
```

On success (HTTP 200), the response contains:

```json
{
  "org_id": "org-uuid",
  "org_name": "org-name",
  "api_url": "https://api.braintrust.dev"
}
```

On failure (non-200 or network error), return 401 Unauthorized.

### 5.4 Auth Strategies

Implementations should support pluggable auth strategies:

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| `ClerkToken` | Validates Bearer token via `/api/apikey/login` | Production (Braintrust UI) |
| `NoAuth` | Always succeeds, no credentials checked | Local testing, development |
| Custom | User-provided auth logic | Enterprise/custom deployments |

**Default app URL:** `https://www.braintrust.dev`

### 5.5 State Caching

Authenticated state objects should be cached to avoid repeated login calls. Use an LRU cache keyed by `(api_key, app_url, org_name)` with a reasonable maximum size (32-64 entries). The cache must be thread-safe.

---

## 6. SSE Streaming Protocol

### 6.1 Wire Format

Each SSE event follows the standard [Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html) format:

```
event: <event_type>\ndata: <json_string>\n\n
```

The response must use these headers:

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

### 6.2 Event Types

An eval response emits events in this order:

```
[progress, progress] * N   (2 per test case: json_delta + done)
summary                     (once, after all cases complete)
done                        (once, final -- signals stream end)
```

On error during a test case, an `error` progress event replaces the `json_delta`:

```
progress (error)            (once per failed case)
progress (done)             (once per failed case)
```

### 6.3 Progress Event

Emitted after each test case completes. Two progress events are sent per case.

**First event (json_delta) -- task output:**

```json
{
  "event": "progress",
  "data": "{\"object_type\":\"task\",\"name\":\"food-classifier\",\"format\":\"code\",\"output_type\":\"completion\",\"id\":\"abc123\",\"event\":\"json_delta\",\"data\":\"\\\"fruit\\\"\"}"
}
```

The `data` field of the SSE event is a JSON string. When parsed, it contains:

| Field | Type | Description |
|-------|------|-------------|
| `object_type` | `string` | Always `"task"` |
| `name` | `string` | Evaluator name |
| `format` | `string` | Always `"code"` (indicates code-generated output, not LLM streaming) |
| `output_type` | `string` | Always `"completion"` |
| `id` | `string` | Span ID for this test case |
| `origin` | `ObjectReference \| undefined` | Origin metadata (present when data came from a dataset). See Origin below. |
| `event` | `string` | `"json_delta"` for successful output, `"error"` for failures. See full enum below. |
| `data` | `string` | **Double-encoded JSON** of the task output (for json_delta) or error message string (for error) |

**`origin` (ObjectReference)** -- present when test cases come from a remote dataset:

| Field | Type | Description |
|-------|------|-------------|
| `object_type` | `string` | Source type: `"project_logs"`, `"experiment"`, `"dataset"`, `"prompt"`, `"function"`, `"prompt_session"` |
| `object_id` | `string` | UUID of the source object |
| `id` | `string` | Row ID within the source |
| `_xact_id` | `string` | Optional transaction ID |
| `created` | `string` | Optional creation timestamp |

The UI uses `origin.id` to route streaming chunks to the correct row in its data grid.

**Full `event` enum values** (the complete set recognized by the UI):

| Value | Used by dev server | Description |
|-------|-------------------|-------------|
| `json_delta` | **Yes** | JSON-encoded task output chunk |
| `done` | **Yes** | Signals per-cell completion |
| `error` | **Yes** | Error message |
| `text_delta` | No (LLM streaming) | Plain text streaming chunk |
| `reasoning_delta` | No (LLM streaming) | Reasoning/chain-of-thought chunk |
| `console` | No | Console output |
| `start` | No | Cell execution start |
| `progress` | No | Status update |

For dev server implementations, only `json_delta`, `done`, and `error` are needed.

**Full `object_type` enum** (values recognized by the UI):

`"prompt"`, `"tool"`, `"scorer"`, `"task"`, `"workflow"`, `"custom_view"`, `"preprocessor"`, `"facet"`, `"classifier"`, `"parameters"`, `"sandbox"`

For dev server evaluators, always use `"task"`.

**Full `format` enum**: `"llm"`, `"code"`, `"global"`, `"graph"`, `"topic_map"`. For dev server evaluators, always use `"code"`.

**Full `output_type` enum**: `"completion"`, `"score"`, `"facet"`, `"classification"`, `"any"`. For dev server evaluators, always use `"completion"`.

> **Critical:** The `data` field within the progress payload is itself a JSON-encoded string. For example, if the task returns the string `"fruit"`, the `data` field will be `"\"fruit\""` (a JSON string containing a JSON string). This double-encoding matches the UI protocol and is required for correct rendering.

**Second event (done) -- signals per-case completion:**

```json
{
  "event": "progress",
  "data": "{\"object_type\":\"task\",\"name\":\"food-classifier\",\"format\":\"code\",\"output_type\":\"completion\",\"id\":\"abc123\",\"event\":\"done\",\"data\":\"\"}"
}
```

This per-case done event signals the UI to exit the "Streaming..." state for this cell and update the progress bar. The `id` field must match the preceding json_delta event. Sending this event is recommended as it provides better UI responsiveness.

**Error progress event:**

When a task throws an exception:

```json
{
  "event": "progress",
  "data": "{\"object_type\":\"task\",\"name\":\"food-classifier\",\"format\":\"code\",\"output_type\":\"completion\",\"id\":\"abc123\",\"event\":\"error\",\"data\":\"Task failed: division by zero\"}"
}
```

### 6.4 Summary Event

Emitted once after all test cases have been processed.

```json
{
  "event": "summary",
  "data": "{\"scores\":{\"exact_match\":0.85,\"relevance\":0.72},\"experiment_name\":\"exp-2026-03-13\",\"experiment_id\":\"exp-uuid\",\"project_id\":\"proj-uuid\"}"
}
```

**Summary payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `scores` | `Record<string, number>` | Averaged scores per scorer name |
| `experiment_name` | `string \| null` | Experiment name |
| `experiment_id` | `string \| null` | Experiment UUID |
| `project_id` | `string \| null` | Project UUID |

The UI also recognizes additional optional fields (`projectName`, `projectUrl`, `experimentUrl`, `comparisonExperimentName`, `metrics`) but handles their absence gracefully. The minimal set above is sufficient.

### 6.5 Done Event

Final event signaling the stream is complete. The client should close the connection after receiving this.

```json
{
  "event": "done",
  "data": ""
}
```

### 6.6 Complete Example Stream

For an eval with 2 test cases and 1 scorer:

```
event: progress
data: {"object_type":"task","name":"food-classifier","format":"code","output_type":"completion","id":"span-1","event":"json_delta","data":"\"fruit\""}

event: progress
data: {"object_type":"task","name":"food-classifier","format":"code","output_type":"completion","id":"span-1","event":"done","data":""}

event: progress
data: {"object_type":"task","name":"food-classifier","format":"code","output_type":"completion","id":"span-2","event":"json_delta","data":"\"vegetable\""}

event: progress
data: {"object_type":"task","name":"food-classifier","format":"code","output_type":"completion","id":"span-2","event":"done","data":""}

event: summary
data: {"scores":{"exact_match":1.0},"experiment_name":"exp-2026-03-13","experiment_id":"exp-uuid","project_id":"proj-uuid"}

event: done
data:
```

---

## 7. Eval Execution Flow

### 7.1 Request Processing

1. **Parse request body** as JSON. Return 400 if invalid.
2. **Validate required fields:** `name` and `data` must be present.
3. **Look up evaluator** by `name`. Return 404 if not found.
4. **Validate data source:** Exactly one of `data.data`, `data.dataset_id`, or `data.dataset_name` must be present. Return 400 otherwise.
5. **Resolve data source:**
   - `data.data`: Map each element to `{input, expected}` test cases.
   - `data.dataset_id`: Create a dataset reference to be fetched during eval execution.
   - `data.dataset_name` (+ optional `data.project_name`): Create a dataset reference by name.
6. **Resolve remote scorers:** Map the `scores` array to scorer ID references. Handle the nested `function_id` format.
7. **Resolve parent context:** Extract `object_id` from `parent`, hardcode `object_type` to `"playground_id"`, extract `generation` from `parent.propagated_event.span_attributes.generation`.
8. **Build SDK state** from auth context (if present). Use LRU cache.
9. **Return 200 with SSE response body.** The body streams events as the eval executes.

### 7.2 Eval Execution (inside SSE body)

10. **Call evaluator.run()** with resolved parameters:
    - `cases`: The test cases (from inline data or dataset)
    - `dataset`: Dataset reference (if using remote dataset)
    - `on_progress`: Callback that converts progress data to SSE events
    - `scorers`: Remote scorer IDs (merged with evaluator's local scorers)
    - `parent`: Resolved parent context
    - `state`: SDK state (from auth)
    - `experiment`: Experiment name (if state available)
    - `project_id`: Project UUID (if state available)
    - `quiet: true`: Suppress console output

11. **For each test case:**
    a. Create an eval span (OTel) or experiment row (native tracing)
    b. Run the task function with `input` from the test case
    c. Run all scorers with `{input, expected, output}`
    d. Set span attributes: `braintrust.input_json`, `braintrust.output_json`, `braintrust.expected`, `braintrust.scores`, `braintrust.span_attributes`, `braintrust.parent`
    e. Fire `on_progress` callback with `{id, data, scores}` (or `{id, error}` on failure)

12. **Flush spans** (OTel SDKs): Force the OTLP batch span processor to export. This is critical -- without it, fast evals may complete before the 5-second batch interval fires, and the UI will see no results.

13. **Compute summary:** Average scores across all test cases per scorer.

14. **Send summary event** with averaged scores and experiment metadata.

15. **Send done event** and close the stream.

### 7.3 Experiment Creation

When a parent context is present (which is the typical case for UI-triggered evals), experiment creation is **skipped**. The OTLP backend creates experiments automatically from the ingested spans. The parent context (`playground_id:<uuid>`) links the spans to the correct playground session.

When no parent is present (e.g., programmatic API usage), the server creates an experiment via the Braintrust API before running the eval.

### 7.4 Span Structure (OTel SDKs)

For OTel-based SDKs (Java, Ruby), each test case creates this span hierarchy:

```
eval (root span, no OTel parent)
  |
  +-- task (child of eval)
  |     |
  |     +-- [user-instrumented LLM calls] (children of task)
  |
  +-- score (child of eval)
```

**Span attributes set on each span type:**

**Eval span:**

| Attribute | Value |
|-----------|-------|
| `braintrust.parent` | `"playground_id:<object_id>"` |
| `braintrust.span_attributes` | `{"type":"eval","name":"<experiment_name>","generation":"<generation>"}` |
| `braintrust.input_json` | JSON of `input` |
| `braintrust.output_json` | JSON of task `output` |
| `braintrust.expected` | JSON of `expected` (if present) |
| `braintrust.origin` | JSON origin metadata (if from dataset) |
| `braintrust.tags` | Array of tags (if present) |

**Task span:**

| Attribute | Value |
|-----------|-------|
| `braintrust.parent` | `"playground_id:<object_id>"` |
| `braintrust.span_attributes` | `{"type":"task","name":"<experiment_name>","generation":"<generation>"}` |
| `braintrust.input_json` | JSON of `input` |
| `braintrust.output_json` | JSON of task `output` |

**Score span:**

| Attribute | Value |
|-----------|-------|
| `braintrust.parent` | `"playground_id:<object_id>"` |
| `braintrust.span_attributes` | `{"type":"score","name":"<experiment_name>","generation":"<generation>"}` |
| `braintrust.scores` | JSON of `{"scorer_name": score_value}` |

All `braintrust.*` attribute values are **JSON-encoded strings** (not raw objects).

### 7.5 OTLP Export

OTel-based SDKs export spans to Braintrust's OTLP ingest endpoint:

```
POST {api_url}/otel/v1/traces
Authorization: Bearer <api_key>
X-Bt-Parent: playground_id:<object_id>
```

The `X-Bt-Parent` header is critical -- it tells the ingest endpoint which playground session to associate the spans with. Implementations should route spans to per-parent exporters that set this header, or use a custom `SpanExporter` that groups spans by their `braintrust.parent` attribute and sets the header accordingly.

---

## 8. CORS Policy

### 8.1 Allowed Origins

The following origins must be allowed. The canonical list comes from the TypeScript SDK's `authorize.ts`:

**Static whitelist:**
- `https://www.braintrust.dev`
- `https://www.braintrustdata.com`

**Dynamic pattern:**
- `https://*.preview.braintrust.dev` (preview/staging deployments)

**Configurable (optional):**
- The value of `BRAINTRUST_APP_URL` environment variable (if set)
- The value of `WHITELISTED_ORIGIN` environment variable (if set)
- `http://localhost:3000` (for local development of the Braintrust UI)

A regex pattern for the minimum required set:

```
/^https?:\/\/([\w-]+\.)*braintrust\.dev$/
```

Plus exact match for `https://www.braintrustdata.com`.

Supporting configurable origins via environment variables is recommended but not required for an initial implementation.

### 8.2 Preflight Response (OPTIONS)

```
HTTP/1.1 204 No Content
Access-Control-Allow-Origin: <origin>
Access-Control-Allow-Credentials: true
Access-Control-Allow-Methods: GET, PATCH, POST, PUT, DELETE, OPTIONS
Access-Control-Allow-Headers: <allowed-headers>
Access-Control-Max-Age: 86400
Access-Control-Allow-Private-Network: true   (if requested)
```

The `Access-Control-Allow-Private-Network: true` header is required for Chrome's Private Network Access checks, since the browser is making requests from a public origin (braintrust.dev) to a private/local address (localhost:8300).

### 8.3 Allowed Request Headers

```
content-type
authorization
x-amz-date
x-api-key
x-amz-security-token
x-bt-auth-token
x-bt-parent
x-bt-org-name
x-bt-project-id
x-bt-stream-fmt
x-bt-use-cache
x-bt-use-gateway
x-stainless-os
x-stainless-lang
x-stainless-package-version
x-stainless-runtime
x-stainless-runtime-version
x-stainless-arch
```

### 8.4 Exposed Response Headers

```
x-bt-cursor
x-bt-found-existing
x-bt-span-id
x-bt-span-export
```

### 8.5 Regular Response Headers

All non-preflight responses from allowed origins include:

```
Access-Control-Allow-Origin: <origin>
Access-Control-Allow-Credentials: true
Access-Control-Expose-Headers: x-bt-cursor, x-bt-found-existing, x-bt-span-id, x-bt-span-export
```

---

## 9. OTel vs Non-OTel SDK Considerations

### 9.1 Two Architecture Families

| Aspect | OTel SDKs (Java, Ruby) | Non-OTel SDKs (TypeScript, Python) |
|--------|------------------------|-------------------------------------|
| Tracing | OpenTelemetry spans with `braintrust.*` attributes | Native Braintrust span protocol |
| Span export | OTLP HTTP exporter to `{api_url}/otel/v1/traces` | Direct API calls to Braintrust |
| Score delivery | Via OTLP spans (score span attributes) | Via direct API logging |
| Span flush | **Must flush** batch processor before summary | No explicit flush needed |
| Parent propagation | `braintrust.parent` span attribute + `X-Bt-Parent` OTLP header | `x-bt-parent` header or `InvokeParent` object |
| Remote scorer invocation | Via OTLP spans | Via `function/invoke` API endpoint |
| Experiment creation | Skipped when parent present (OTLP backend creates) | Explicit via API |

### 9.2 Key Implementation Difference: Span Flushing

In OTel-based SDKs, the `BatchSpanProcessor` exports spans on a timer (typically every 5 seconds). Fast evaluations (a few test cases with simple tasks) can complete in under 1 second. Without an explicit flush before sending the SSE summary event, the UI may receive the summary but see no experiment data because the spans haven't been exported yet.

**Recommendation for OTel SDKs:** Always call `force_flush()` on the tracer provider (or span processor) after the eval completes and before sending the summary event.

### 9.3 Key Implementation Difference: SSE Events

The TypeScript SDK supports an additional `start` event sent before progress events, containing experiment metadata. OTel SDKs do not need this since experiment metadata comes from the OTLP ingest side.

| Event | OTel SDKs | Non-OTel SDKs |
|-------|-----------|---------------|
| `start` | Not sent | Optional (experiment metadata) |
| `progress` | Task output only (scores via OTLP) | Task output (scores may be included) |
| `summary` | Minimal (scores, experiment_name, experiment_id, project_id) | Full (includes URLs, metrics, comparison) |
| `done` | Always sent | Always sent |
| `error` | Via progress event with `"event":"error"` | Dedicated `error` SSE event type |

---

## 10. Implementation Checklist

### 10.1 Core Server

- [ ] HTTP server listening on configurable port (default 8300)
- [ ] Router dispatching GET `/`, GET+POST `/list`, POST `/eval`, OPTIONS `*`
- [ ] JSON request body parsing with error handling
- [ ] JSON error responses with appropriate HTTP status codes

### 10.2 Endpoints

- [ ] Health check endpoint returning `{"status": "ok"}`
- [ ] List endpoint returning evaluator metadata (scores, parameters)
- [ ] Eval endpoint with request validation (name, data, data source exclusivity)
- [ ] SSE response streaming for eval endpoint

### 10.3 Authentication

- [ ] Auth middleware with pluggable strategies
- [ ] ClerkToken strategy: extract Bearer token, validate via `/api/apikey/login`
- [ ] NoAuth strategy for testing/development
- [ ] Auth context propagation to eval handler
- [ ] State construction from auth context
- [ ] LRU state cache (thread-safe, max 32-64 entries)

### 10.4 CORS

- [ ] Origin validation against `*.braintrust.dev` pattern
- [ ] Preflight OPTIONS handling with correct headers
- [ ] Private Network Access support (`Access-Control-Allow-Private-Network`)
- [ ] CORS headers on all responses (not just preflight)

### 10.5 Eval Execution

- [ ] Data source resolution (inline, dataset_id, dataset_name)
- [ ] Remote scorer resolution (handle nested function_id format)
- [ ] Parent context resolution (hardcode playground_id, extract generation)
- [ ] Task execution with error handling
- [ ] Scorer execution with error handling
- [ ] Progress callback -> SSE event conversion
- [ ] Per-case done events for UI responsiveness
- [ ] Summary computation (averaged scores)
- [ ] Stream termination (done event)

### 10.6 OTel-Specific (if applicable)

- [ ] Span hierarchy: eval -> task, eval -> score
- [ ] `braintrust.*` span attributes (JSON-encoded strings)
- [ ] Parent span attribute: `"playground_id:<object_id>"`
- [ ] OTLP export with `X-Bt-Parent` header
- [ ] Force flush before sending summary event

### 10.7 Testing

- [ ] Request validation (missing/invalid fields, unknown evaluator)
- [ ] SSE event format verification
- [ ] Progress event protocol fields (object_type, format, output_type, etc.)
- [ ] Double-encoded JSON in progress data field
- [ ] Summary event with averaged scores
- [ ] Error handling (task failures, scorer failures)
- [ ] Auth middleware (token validation, state caching)
- [ ] CORS (origin validation, preflight, private network access)
- [ ] Multiple data source rejection

---

## 11. References

### 11.1 Implementations

| SDK | Repository | Key Server Files |
|-----|-----------|-----------------|
| **Ruby** (OTel) | [braintrustdata/braintrust-sdk-ruby](https://github.com/braintrustdata/braintrust-sdk-ruby) | `lib/braintrust/server/` |
| **Java** (OTel) | [braintrustdata/braintrust-sdk-java](https://github.com/braintrustdata/braintrust-sdk-java) | `src/main/java/dev/braintrust/devserver/` |
| **TypeScript** (non-OTel) | [braintrustdata/braintrust-sdk-javascript](https://github.com/braintrustdata/braintrust-sdk-javascript) | `js/dev/` |

### 11.2 Key PRs

| SDK | PR | Description |
|-----|-----|------------|
| Ruby | [#108](https://github.com/braintrustdata/braintrust-sdk-ruby/pull/108) | Initial dev server implementation |

### 11.3 File Index (Ruby SDK -- reference implementation)

| File | Description |
|------|-------------|
| `lib/braintrust/server.rb` | Module entry point, soft-requires rack |
| `lib/braintrust/server/rack.rb` | `Rack.app()` factory method |
| `lib/braintrust/server/rack/app.rb` | Middleware stack builder |
| `lib/braintrust/server/router.rb` | Method+path request router |
| `lib/braintrust/server/sse.rb` | SSEBody, SSEStreamBody, SSEWriter |
| `lib/braintrust/server/handlers/health.rb` | GET / handler |
| `lib/braintrust/server/handlers/list.rb` | GET/POST /list handler |
| `lib/braintrust/server/handlers/eval.rb` | POST /eval handler (core protocol logic) |
| `lib/braintrust/server/middleware/auth.rb` | Auth middleware |
| `lib/braintrust/server/middleware/cors.rb` | CORS middleware |
| `lib/braintrust/server/auth/clerk_token.rb` | Clerk token auth strategy |
| `lib/braintrust/server/auth/no_auth.rb` | No-op auth strategy |
| `lib/braintrust/eval/evaluator.rb` | Evaluator base class |
| `lib/braintrust/eval/runner.rb` | Eval runner with OTel span creation |
| `lib/braintrust/eval/context.rb` | Eval context (normalized inputs) |
| `lib/braintrust/eval/result.rb` | Eval result model |
| `examples/server/eval.ru` | Example Rack config file |

### 11.4 Standards

- [Server-Sent Events (SSE)](https://html.spec.whatwg.org/multipage/server-sent-events.html) -- W3C HTML Living Standard
- [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/) -- OTLP trace export
- [Private Network Access](https://wicg.github.io/private-network-access/) -- Chrome preflight for local network requests
