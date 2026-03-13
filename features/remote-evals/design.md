# Remote Evals -- Design

This document describes the architecture and behavior of the Remote Eval Dev Server. It is intended to give an implementer a comprehensive understanding of how the system works end-to-end before diving into the precise API contracts ([contracts.md](contracts.md)) or implementation plan ([implementation.md](implementation.md)).

## The Big Picture

Three systems collaborate to make remote evals work:

```
+---------------------------+         +---------------------------+         +---------------------------+
|    Braintrust Playground  |         |       Dev Server          |         |     Braintrust API        |
|    (browser)              |         |       (user's machine)    |         |     (cloud)               |
|                           |         |                           |         |                           |
|  - Sends eval requests    | ------> |  - Runs task code         |         |  - Stores experiments     |
|  - Renders results        | <------ |  - Runs scorers           | ------> |  - Ingests spans          |
|  - Manages datasets       |   SSE   |  - Streams progress       |  spans  |  - Serves dataset rows    |
|  - Manages scorers        |         |  - Exports spans          |         |  - Hosts scorer functions  |
+---------------------------+         +---------------------------+         +---------------------------+
```

**The Playground** is the orchestrator. It owns the dataset, decides which evaluator to run and with what parameters, sends the request, and renders the streamed results. It also manages remote scorers (functions stored in Braintrust that the dev server fetches and invokes).

**The Dev Server** is the executor. It receives eval requests, runs the user's task code against each test case, runs scorers, streams per-case progress back to the Playground via SSE, and exports tracing spans so the Playground can display the full experiment.

**The Braintrust API** is the persistence layer. It stores experiment data, serves dataset rows when the Playground references a dataset by ID or name, and hosts remote scorer functions.

## Process Flows

### Listing Evaluators

This happens when the user opens the Playground and selects a remote eval source. The Playground needs to know what evaluators are available and what parameters they accept.

```
Playground                          Dev Server
    |                                   |
    |  GET /list                        |
    |  Headers: Authorization, Org      |
    |---------------------------------->|
    |                                   |
    |  200 OK                           |
    |  {                                |
    |    "food-classifier": {           |
    |      "scores": [{"name":"exact"}],|
    |      "parameters": { ... }        |
    |    }                              |
    |  }                                |
    |<----------------------------------|
    |                                   |
    |  Render evaluator dropdown        |
    |  Render parameter controls        |
```

The response is a flat map of evaluator names to metadata. The Playground uses the `scores` array to display available scorer names and the `parameters` object to render UI controls (text fields, number sliders, etc.).

### Running an Evaluation

This is the core flow. The user has selected an evaluator, configured parameters, picked a dataset, and clicked "Run".

```
Playground                          Dev Server                       Braintrust API
    |                                   |                                   |
    |  POST /eval                       |                                   |
    |  { name, data, scores,            |                                   |
    |    parent, experiment_name,        |                                   |
    |    project_id, parameters }        |                                   |
    |---------------------------------->|                                   |
    |                                   |                                   |
    |                                   |  (if dataset_id/name)             |
    |                                   |  Fetch dataset rows ------------->|
    |                                   |                    <--------------|
    |                                   |                                   |
    |                                   |  (if remote scorers)              |
    |                                   |  Resolve scorer functions ------->|
    |                                   |                    <--------------|
    |                                   |                                   |
    |                                   |  For each test case:              |
    |                                   |    1. Run task(input) -> output   |
    |                                   |    2. Run scorers                 |
    |                                   |    3. Record span                 |
    |  SSE: progress (json_delta)       |                                   |
    |<----------------------------------|                                   |
    |  SSE: progress (done)             |                                   |
    |<----------------------------------|                                   |
    |                                   |                                   |
    |  ... repeat for each case ...     |                                   |
    |                                   |                                   |
    |                                   |  Export spans ------------------->|
    |                                   |                                   |
    |  SSE: summary                     |                                   |
    |<----------------------------------|                                   |
    |  SSE: done                        |                                   |
    |<----------------------------------|                                   |
    |                                   |                                   |
    |  Fetch experiment from API ----------------------------------------->|
    |  Display full results     <-----------------------------------------|
```

Key observations:

- The response begins immediately as a `text/event-stream`. The eval executes inside the streaming response body, not before it.
- Each test case produces two SSE `progress` events: one with the task output (`json_delta`), one signaling the case is complete (`done`). This lets the Playground update its UI row-by-row.
- Scores are **not** included in SSE progress events. They flow through spans (exported to the Braintrust API) and the Playground fetches them from there.
- The `summary` event at the end carries averaged scores and experiment metadata.
- The final `done` event signals the stream is complete.

### Authentication

The Playground forwards the user's session token to the dev server. The dev server validates it against the Braintrust app server, then uses it to make API calls on behalf of the user (fetching datasets, exporting spans, etc.).

```
Playground                          Dev Server                       Braintrust App
    |                                   |                                   |
    |  POST /eval                       |                                   |
    |  Authorization: Bearer <token>    |                                   |
    |  X-Bt-Org-Name: my-org           |                                   |
    |---------------------------------->|                                   |
    |                                   |                                   |
    |                                   |  POST /api/apikey/login           |
    |                                   |  { "token": "<token>" }           |
    |                                   |---------------------------------->|
    |                                   |                                   |
    |                                   |  200 OK                           |
    |                                   |  { org_id, org_name, api_url }    |
    |                                   |<----------------------------------|
    |                                   |                                   |
    |                                   |  Build authenticated state        |
    |                                   |  (cached for subsequent requests) |
    |                                   |                                   |
    |  SSE response stream              |                                   |
    |<----------------------------------|                                   |
```

The token is extracted from the `X-Bt-Auth-Token` header (preferred) or the `Authorization: Bearer` header (fallback). See [contracts.md](contracts.md) for the full header and token validation details.

Authenticated state is expensive to construct (requires a network call), so it should be cached. Use an LRU cache keyed by `(api_key, app_url, org_name)` with a reasonable maximum size (32--64 entries).

## Dev Server Components

```
+------------------------------------------------------------------+
|                         Dev Server                                |
|                                                                   |
|  Incoming request                                                 |
|       |                                                           |
|  +----v-------------+                                             |
|  | CORS Middleware   |  Validate origin, add CORS headers,        |
|  +----+-------------+  handle OPTIONS preflight                   |
|       |                                                           |
|  +----v-------------+                                             |
|  | Auth Middleware   |  Extract token, validate via login API,    |
|  +----+-------------+  set auth context on request                |
|       |                                                           |
|  +----v-------------+                                             |
|  | Router            |  Dispatch by method + path                 |
|  +--+------+------+-+                                             |
|     |      |      |                                               |
|  +--v--+ +-v--+ +-v----------+                                    |
|  |GET /| |/list| | POST /eval |                                   |
|  +-----+ +----+ +-----+------+                                   |
|                        |                                          |
|              +---------v----------+                               |
|              | Evaluator.run()    |                               |
|              |  task + scorers    |                               |
|              +---------+----------+                               |
|                        |                                          |
|              +---------v----------+                               |
|              | SSE Writer         |                               |
|              |  progress/summary  |                               |
|              +--------------------+                               |
+------------------------------------------------------------------+
```

### Middleware Stack

Middleware runs in order on every request. Each layer can short-circuit (e.g., CORS returns 204 for OPTIONS; Auth returns 401 on failure).

| Order | Component | Responsibility |
|-------|-----------|----------------|
| 1 | **CORS** | Validates the `Origin` header against allowed patterns. Adds CORS response headers. Handles OPTIONS preflight requests. Supports Chrome Private Network Access. |
| 2 | **Auth** | Extracts auth token from request headers. Validates it by calling the Braintrust login API. Sets an auth context on the request for downstream handlers. |
| 3 | **Router** | Matches `(method, path)` to a handler. Returns 405 for known paths with wrong method, 404 for unknown paths. |

### Handlers

**Health** (`GET /`) -- Returns a simple success response. Used by the Playground to check if the server is reachable.

**List** (`GET /list`) -- Iterates over the evaluator registry and serializes each evaluator's scorer names and parameter definitions into the protocol format. See [contracts.md](contracts.md) for the response schema.

**Eval** (`POST /eval`) -- The core handler. Parses the request, validates fields, resolves data sources and scorers, and returns an SSE streaming response body. The eval execution happens inside the stream -- the handler returns 200 immediately and the response body is generated as the eval progresses.

### SSE Response Body

The eval handler returns a streaming response body that emits SSE events as the evaluation runs. This requires the HTTP server to support streaming/chunked responses (most modern servers do; WEBrick does not).

The body must:
1. Execute the evaluator against the test cases
2. Emit `progress` events as each case completes
3. Flush any buffered spans to ensure the API has received them
4. Emit a `summary` event with averaged scores
5. Emit a `done` event and close

See [contracts.md -- SSE Events](contracts.md#sse-events) for the exact event schemas.

## Evaluation Model

### Evaluator

An evaluator is the top-level unit registered with the dev server. It combines:

- A **task** -- the callable being evaluated
- **Scorers** -- local scoring functions (zero or more)
- **Parameters** -- configurable inputs exposed in the Playground UI (optional)

Evaluators are registered by name. The name is the primary identifier used by the Playground to request a specific evaluator.

### Task

A callable that receives `input` (from a test case) and returns any JSON-serializable value. The task is where the user's application logic lives -- calling an LLM, querying a database, running an agent pipeline, etc.

### Scorers

Two kinds of scorers can run during an evaluation:

**Local scorers** are defined in the evaluator code. They receive `input`, `expected`, `output`, and optionally `metadata` and `trace`. They return a numeric score (0.0--1.0).

**Remote scorers** are functions stored in Braintrust. The Playground sends their IDs in the `POST /eval` request. The dev server resolves them at eval time and invokes them alongside local scorers.

The final score set is the union of both. Each scorer must have a unique name since scores are keyed by name.

### Parameters

Parameters let users configure evaluator behavior from the Playground without changing code. They are declared in the evaluator definition with a name, type, default value, and description. The Playground renders them as UI controls and sends the user's chosen values in the `POST /eval` request body.

### Data Sources

Test cases can come from three sources. The Playground decides which to use and sends one in the `POST /eval` request:

| Source | Field | Description |
|--------|-------|-------------|
| Inline | `data.data` | Array of test cases sent directly in the request |
| Dataset by ID | `data.dataset_id` | UUID of a dataset stored in Braintrust |
| Dataset by name | `data.dataset_name` | Name of a dataset (with optional `project_name`) |

Each test case has at minimum an `input` field and optionally `expected`, `metadata`, and `tags`.

### Eval Result

After all test cases have been processed, the evaluator produces a result containing:

- Averaged scores per scorer (used for the `summary` SSE event)
- Experiment and project identifiers (if the eval was logged to Braintrust)
- Errors encountered during execution
- Duration

## Span Export and Experiment Creation

How evaluation data gets persisted in Braintrust depends on the SDK's tracing architecture.

### OTel-Based SDKs

SDKs that use OpenTelemetry (e.g., Java, Ruby) create a span hierarchy for each test case:

```
eval (root)
  +-- task
  |     +-- [user-instrumented LLM calls, etc.]
  +-- score
```

Each span carries `braintrust.*` attributes (JSON-encoded strings) containing the input, output, expected value, scores, and parent context. Spans are exported to Braintrust's OTLP ingest endpoint (`POST {api_url}/otel/v1/traces`) with an `X-Bt-Parent` header that associates them with the correct Playground session.

When the eval request includes a `parent` context (the typical case for Playground-triggered evals), **experiment creation is skipped** -- the OTLP backend creates the experiment automatically from the ingested spans. The parent's `object_id` is used as the Playground session identifier, and the `object_type` should be hardcoded to `"playground_id"` regardless of the value sent in the request.

**Span flushing is critical.** OTel SDKs typically batch-export spans on a timer (e.g., every 5 seconds). A fast eval can complete before the first batch fires. Always call `force_flush()` on the tracer provider after the eval completes and before sending the `summary` SSE event. Without this, the Playground may show the summary but see no experiment data.

### Non-OTel SDKs

SDKs with native Braintrust tracing (e.g., TypeScript, Python) log spans directly to the Braintrust API rather than through OTLP. They typically create experiments explicitly via the API before running the eval, and log each row directly. The parent context is passed through their native span protocol. Span flushing is not a concern since writes are synchronous or immediately queued.

## Important Caveats

**Double-encoded JSON in progress events.** The `data` field inside an SSE `progress` event payload is itself a JSON-encoded string. If the task returns `"fruit"`, the field value is `"\"fruit\""`. This double-encoding is required by the Playground's event parser. Getting this wrong is a common implementation mistake.

**Playground ignores the evaluator's dataset.** When running via the Playground, the dataset is always provided in the `POST /eval` request. Any dataset defined in the evaluator code is not used.

**Scorer concatenation.** Remote scorers sent by the Playground are added to (not replacing) the evaluator's local scorers. Both sets run.

**CORS and Private Network Access.** The Playground runs on `*.braintrust.dev` (HTTPS, public) and makes requests to the dev server on `localhost` (private network). Chrome's Private Network Access checks require the dev server to respond to the `Access-Control-Request-Private-Network` preflight header. Without this, Chrome blocks the request silently.

**Auth token header priority.** The Playground may send the auth token in `X-Bt-Auth-Token` (preferred) or `Authorization: Bearer` (fallback). Some organizations use a custom firewall token in `Authorization`, with the actual Braintrust token in `X-Bt-Auth-Token`. Always check `X-Bt-Auth-Token` first.

## Further Reading

| Document | Purpose |
|----------|---------|
| [overview.md](overview.md) | Product context, use cases, and key concepts |
| [contracts.md](contracts.md) | Precise API schemas, data types, SSE event formats, CORS policy |
| [validation.md](validation.md) | Test cases and expected behaviors for verifying correctness |
| [implementation.md](implementation.md) | Phased implementation plan and reference resources |
