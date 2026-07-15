# Braintrust Instrumentation Guide

This document is a prescriptive specification for Braintrust SDK implementers. It defines which SDK APIs Braintrust instruments, what data each instrumentation MUST capture, and the structure of the resulting spans.

## Scope

This guide covers:

- **LLM provider APIs** — direct calls to OpenAI, Anthropic, Google (Gemini), and other model providers
- **Framework integrations** — LangChain, Vercel AI SDK, LiteLLM, agent frameworks, and similar

It does NOT cover the Braintrust evaluation/scoring APIs (`Eval`, `init_dataset`, etc.) or manual tracing (`@traced`, `start_span`).

---

## Span Data Model

Each span is stored as a Braintrust log row. The backend accepts the following fields:

| Field             | Type                         | Description                                                          |
| ----------------- | ---------------------------- | -------------------------------------------------------------------- |
| `id`              | string                       | Unique identifier for the row                                        |
| `span_id`         | string                       | Unique identifier for this span within the trace                     |
| `root_span_id`    | string                       | Identifier for the root of the trace (same for all spans in a trace) |
| `span_parents`    | array of strings             | Parent span IDs (empty for root spans, typically one parent)         |
| `span_attributes` | object                       | Contains `type`, `name`, and optional additional fields              |
| `input`           | any                          | Free-form JSON — the input to the operation                          |
| `output`          | any                          | Free-form JSON — the result of the operation                         |
| `metrics`         | object (string → number)     | Numeric metrics (tokens, timing, etc.)                               |
| `metadata`        | object (string → any)        | Arbitrary metadata (model, provider, etc.)                           |
| `scores`          | object (string → number 0-1) | Named scoring metrics                                                |
| `error`           | any                          | Error data if the span failed                                        |
| `tags`            | array of strings             | Labels for categorization                                            |
| `context`         | object                       | Code location and span-origin provenance                             |

Note: `input` and `output` are **free-form JSON** — the backend does not enforce any structure on them. The conventions described in this guide are SDK-level standards for how instrumentation should populate these fields.

### Data capturing policy

Instrumentation MUST NOT capture any data or fields unless this guide explicitly requires or allows them. This applies even when the backend can store arbitrary JSON or a provider/framework SDK exposes additional data.

New captured fields MUST be added to this specification before SDKs emit them. This background behind this policy is to keep telemetry reliable and predictable, avoids unnecessary data capture (which are critical both in terms of data-volume and PII), and facilitates building an opinionated product around our instrumentation.

It is encouraged to expand this specification for any data that may already be captured (preceding this policy), however extensions of this specification should go through critical review.

### Span types

Braintrust supports the following `span_attributes.type` values:

| Type           | Description                                                                   |
| -------------- | ----------------------------------------------------------------------------- |
| `llm`          | A single LLM API call (chat completion, message creation, content generation) |
| `function`     | A tool/function execution — code that runs in response to a model's tool call |
| `task`         | A unit of application logic — an agent run, pipeline step, or named operation |
| `tool`         | A model-initiated external call (API, database query, retrieval)              |
| `eval`         | Root span for an evaluation run                                               |
| `score`        | A scorer/quality metric computation                                           |
| `automation`   | An automated operation                                                        |
| `preprocessor` | A data preprocessing step                                                     |
| `classifier`   | A classification operation                                                    |
| `review`       | A human review/annotation                                                     |

This guide primarily concerns `llm`, `tool`, and `task` spans.

### Span hierarchy

Spans form a tree (technically a DAG) within a trace:

- All spans in a trace share the same `root_span_id`
- A span's parent is identified by `span_parents` (an array, typically with one element)
- Root spans have an empty `span_parents` array

### Metrics

The `metrics` field is an object of string keys to numeric values. Instrumentation MUST only emit metric fields explicitly listed in this guide even though the backend accepts arbitrary numeric keys. Standard LLM token and cost field semantics are specified in [Token and cost metrics](features/token-and-cost-metrics.md). Standard fields:

| Field                 | Description                                                                          |
| --------------------- | ------------------------------------------------------------------------------------ |
| `start`               | Unix timestamp when the span started                                                 |
| `end`                 | Unix timestamp when the span ended                                                   |
| `prompt_tokens`       | Input/prompt token count (LLM spans)                                                 |
| `completion_tokens`   | Output/completion token count (LLM spans)                                            |
| `tokens`              | Total token count (LLM spans)                                                        |
| `time_to_first_token` | Seconds from request start to the first generated token or chunk                     |

### Context

The `context` field is an object containing textual information about the code and systems that produced the span. SDKs MUST preserve the existing caller-location fields when available; caller-location fields are optional because not every runtime or instrumentation path can determine them.

| Field                              | Type            | Description                                                                                  |
| ---------------------------------- | --------------- | -------------------------------------------------------------------------------------------- |
| `caller_functionname`              | string optional | Function or method that created the span                                                     |
| `caller_filename`                  | string optional | File where the span was created                                                              |
| `caller_lineno`                    | number optional | Line number where the span was created                                                       |
| `span_origin.name`                 | string optional | SDK, integration, Braintrust service, or exporter that emitted or exported the span           |
| `span_origin.version`              | string optional | Version of the SDK, integration, Braintrust service, or exporter when known                  |
| `span_origin.instrumentation.name` | string optional | Stable module, package, plugin, or OTel instrumentation scope that created the span          |
| `span_origin.environment.type`     | string optional | Operating environment type where the span was captured: `ci`, `server`, or `local`            |
| `span_origin.environment.name`     | string optional | Normalized operating environment name, such as `github_actions`, `vercel`, or `development` |

Braintrust-created spans MUST also include span-origin provenance. Omit fields whose values are unknown.

```json
{
  "caller_functionname": "main",
  "caller_filename": "app.py",
  "caller_lineno": 42,
  "span_origin": {
    "name": "braintrust.sdk.javascript",
    "version": "1.2.3",
    "instrumentation": {
      "name": "openai-auto"
    },
    "environment": {
      "type": "ci",
      "name": "github_actions"
    }
  }
}
```

OTLP ingestion will map standard OTel code attributes into caller-location context when explicit context is not provided: `code.function.name` → `context.caller_functionname`, `code.file.path` → `context.caller_filename`, and `code.line.number` → `context.caller_lineno`.

`context.span_origin` identifies the SDK, integration, service, or exporter that emitted or exported the span. For OTLP spans that do not include explicit Braintrust span-origin provenance, ingestion SHOULD set `context.span_origin.name` to `opentelemetry` and SHOULD fill `context.span_origin.version` from the OTel `telemetry.sdk.version` resource attribute when present.

Braintrust-maintained SDKs, plugins, services, and exporters SHOULD use stable `span_origin.name` values under the reserved `braintrust.` prefix when they provide explicit Braintrust span-origin provenance. Braintrust SDKs SHOULD use `braintrust.sdk.<language>` names, such as `braintrust.sdk.javascript`; Braintrust plugins SHOULD use `braintrust.plugin.<plugin>` names, such as `braintrust.plugin.codex`; Braintrust Gateway SHOULD use `braintrust.gateway`. User code and third-party integrations SHOULD NOT use the `braintrust.` prefix for caller-provided origin names.

`context.span_origin.instrumentation.name` identifies the stable module, package, plugin, or OTel instrumentation scope that directly created the span. Provider/client SDKs such as `openai` or `anthropic` are not the span origin and SHOULD continue to appear in `metadata.provider` when provider metadata is available.

`context.span_origin.environment` identifies the operating environment where the span was captured. The `type` field SHOULD be one of `ci`, `server`, or `local`; SDK type definitions SHOULD allow future string values. The `name` field is optional and SHOULD be a normalized lower-snake-case label. Explicit `type` and `name` values are independent; if only one is supplied, SDKs SHOULD preserve that field and omit the unknown field. Emit this object only when the value comes from an explicit override or a reliable positive signal; do not infer `local` from the absence of CI or server signals. Gateway identity belongs in `context.span_origin.name`, not in `context.span_origin.environment.type`.

When SDKs and Braintrust-internal emitters resolve `context.span_origin.environment`, they SHOULD apply this precedence:

1. Caller-provided SDK option. If an SDK supports an explicit null/none environment option, that value disables ambient environment detection.
2. `BRAINTRUST_ENVIRONMENT_TYPE` / `BRAINTRUST_ENVIRONMENT_NAME`, resolved through process environment and `.env.braintrust` fallback.
3. CI provider environment variables or generic `CI`.
4. Server/platform environment variables.
5. Language or framework deployment-mode variables.
6. Omit `environment`.

SDKs SHOULD use provider-specific CI variables when present, such as `GITHUB_ACTIONS`, `GITLAB_CI`, `CIRCLECI`, `BUILDKITE`, `JENKINS_URL`, `JENKINS_HOME`, `TF_BUILD`, `TEAMCITY_VERSION`, `TRAVIS`, or `BITBUCKET_BUILD_NUMBER`; if only generic `CI` is present, use `type: "ci"` and `name: "ci"`. SDKs MAY identify server environments from explicit platform variables such as `VERCEL`, `NETLIFY`, `AWS_LAMBDA_FUNCTION_NAME`, Lambda-specific `AWS_EXECUTION_ENV` values such as `AWS_Lambda_*`, `K_SERVICE`, `FUNCTION_TARGET`, `KUBERNETES_SERVICE_HOST`, `ECS_CONTAINER_METADATA_URI`, `ECS_CONTAINER_METADATA_URI_V4`, ECS-specific `AWS_EXECUTION_ENV` values such as `AWS_ECS_*`, `DYNO`, `FLY_APP_NAME`, `RAILWAY_ENVIRONMENT`, or `RENDER_SERVICE_NAME`. ECS metadata variables and ECS-specific `AWS_EXECUTION_ENV` values SHOULD classify as `server/ecs` rather than `server/aws_lambda`. SDKs MAY use language/framework variables such as `NODE_ENV`, `RAILS_ENV`, `RACK_ENV`, `ASPNETCORE_ENVIRONMENT`, or `DOTNET_ENVIRONMENT` only as weaker fallback signals: production/staging values map to `server`, development/local values map to `local`, and test values SHOULD be ignored unless CI was already detected.

---

## General Principles

### Span model

Braintrust instrumentation is built on OpenTelemetry. Each instrumented API call produces one or more OTel spans that are exported to Braintrust and converted into Braintrust log rows.

### Span naming

Span names SHOULD reflect the provider and operation. Current conventions for LLM spans:

| Provider  | Span name                   |
| --------- | --------------------------- |
| OpenAI    | `Chat Completion`           |
| Anthropic | `anthropic.messages.create` |
| Google    | `generate_content`          |

SDKs MAY define span names for additional providers as they are added.

### Attribute namespacing

Braintrust SDK spans use the following attribute prefixes (see also the [AI span filtering spec](features/filter-ai-spans.md)):

| Prefix        | Source                     |
| ------------- | -------------------------- |
| `gen_ai.`     | GenAI semantic conventions |
| `braintrust.` | Braintrust SDK             |
| `llm.`        | Common LLM instrumentation |
| `ai.`         | Vercel AI SDK and similar  |
| `traceloop.`  | Traceloop / OpenLLMetry    |

---

## Completion APIs vs Agentic APIs

This is the most important distinction in Braintrust instrumentation. The two API categories produce fundamentally different span structures.

### Completion APIs

Completion APIs are **single request-response** calls. The user sends messages to a model and gets back a response. If the model requests tool calls, **the user is responsible for executing them** and making follow-up calls. Each call is independent from the SDK's perspective.

**Examples:** OpenAI `chat.completions.create`, Anthropic `messages.create`, Google `generateContent`

**Span structure:** One `llm` span per API call. No child spans.

```
llm  (Chat Completion)          ← one span, one API call
```

If the model returns tool calls, the completion API span captures them in its output, but does NOT execute them or create tool spans.

### Agentic APIs

Agentic APIs manage the **full tool-use loop** internally. A single call from the user's perspective may trigger multiple LLM calls and tool executions under the hood. The SDK/framework handles sending tool results back to the model and continuing the conversation until the model produces a final response.

**Examples:** OpenAI Responses API (with tools), Vercel AI SDK `generateText` / `streamText` (with tools), LangChain agents, OpenAI Agents SDK, Claude Agent SDK

**Span structure:** One parent `task` span wrapping multiple child `llm` and `tool` spans.

```
task  (agent run)               ← parent span for the entire agentic operation
├── llm   (LLM call 1)         ← first model call, output includes tool_calls
├── tool  (get_weather)         ← tool execution
├── tool  (search_db)           ← tool execution
├── llm   (LLM call 2)         ← second model call with tool results, output includes tool_calls
├── tool  (format_result)       ← tool execution
└── llm   (LLM call 3)         ← final model call, output is the final text response
```

The key differences:

| Aspect                      | Completion API           | Agentic API                       |
| --------------------------- | ------------------------ | --------------------------------- |
| Spans per user call         | 1                        | 1 parent + N children             |
| Parent span type            | —                        | `task`                            |
| LLM span type               | `llm`                    | `llm` (child)                     |
| Tool execution spans        | None (not SDK's job)     | `tool` (child, one per tool call) |
| Who executes tools?         | User code                | SDK / framework                   |
| Tool calls in LLM output?   | Yes (for user to act on) | Yes (for observability)           |
| Tool results in next input? | User's responsibility    | SDK handles automatically         |

---

## Completion API Instrumentation

### One span per API call

Each discrete API call MUST produce exactly one `llm` span. A streaming call produces a single span that closes when the stream finishes, not one span per chunk.

### Canonical payload format

Braintrust uses the **OpenAI Chat Completions message format** as the canonical representation for LLM input and output. The Braintrust UI parses, displays, and diffs spans assuming this format.

For the three providers that Braintrust ships built-in UI normalizers for (OpenAI, Anthropic, Google), instrumentation MAY preserve the provider-native payload as-is — the UI will normalize it for display based on `metadata.provider`. For all other providers (Mistral, Cohere, Groq, Fireworks, Together, xAI, Perplexity, custom providers, etc.), instrumentation MUST convert payloads into the OpenAI Chat Completions format so that the UI can render them.

### Input capture

The span MUST capture the full input messages sent to the model in one of the following formats.

#### Default: OpenAI Chat Completions format

For any provider that does not have a dedicated UI normalizer (i.e. anything other than Anthropic and Google), the input MUST be an ordered array of OpenAI-style message objects:

```json
[
  { "role": "system", "content": "you are a helpful assistant" },
  { "role": "user", "content": "What is the capital of France?" }
]
```

Each message:

- `role` — one of `system`, `user`, `assistant`, `tool`, `developer`
- `content` — a string, or an array of typed content parts (`{ "type": "text", "text": "..." }`, `{ "type": "image_url", "image_url": { "url": "..." } }`, etc.)

If the provider exposes the system prompt as a separate parameter (rather than as a message), the SDK MUST insert it into the messages array as a `role: "system"` entry.

#### Anthropic (provider-native)

Instrumentation MAY preserve Anthropic's native message format. The system prompt SHOULD be normalized into the messages array as a `role: "system"` entry:

```json
[
  { "role": "user", "content": "What is the capital of France?" },
  { "role": "system", "content": "You are a helpful assistant." }
]
```

#### Google (provider-native)

Instrumentation MAY preserve Google's native `contents`/`parts` structure. The `model` field is included at the top level of the input object:

```json
{
  "model": "gemini-2.5-flash",
  "contents": [
    {
      "role": "user",
      "parts": [{ "text": "What is the capital of France?" }]
    }
  ]
}
```

### Output capture

The span MUST capture the model's response in one of the following formats.

#### Default: OpenAI Chat Completions format

For any provider that does not have a dedicated UI normalizer, the output MUST be an array of OpenAI-style choice objects:

```json
[
  {
    "index": 0,
    "finish_reason": "stop",
    "message": {
      "role": "assistant",
      "content": "The capital of France is Paris."
    }
  }
]
```

#### Anthropic (provider-native)

Instrumentation MAY preserve Anthropic's native response object:

```json
{
  "role": "assistant",
  "content": [{ "type": "text", "text": "The capital of France is Paris." }]
}
```

#### Google (provider-native)

Instrumentation MAY preserve Google's native `candidates` structure:

```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [{ "text": "The capital of France is Paris." }]
      }
    }
  ]
}
```

### Tool calls in completion API output

When the model decides to call a tool instead of responding with text, that decision is part of the model's output. In a completion API, the SDK does NOT execute the tool — it only records that the model asked for it. The user code is responsible for executing the tool and making a follow-up call.

The exact shape of the tool-call payload depends on whether the span output uses the canonical OpenAI format or a provider-native format.

#### Default: OpenAI Chat Completions format

For any provider that does not have a dedicated UI normalizer, tool calls in the output MUST follow the OpenAI Chat Completions structure. The output is an array of choice objects:

```json
[
  {
    "index": 0,
    "finish_reason": "tool_calls",
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": {
            "name": "get_weather",
            "arguments": "{\"location\": \"Paris, France\"}"
          }
        }
      ]
    }
  }
]
```

**Choice fields:**

| Field           | Type   | Required | Description                                                                                                                                                                                        |
| --------------- | ------ | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `index`         | number | SHOULD   | The index of this choice in the response (0 for single-choice responses)                                                                                                                           |
| `finish_reason` | string | MUST     | Why the model stopped generating. Use `"tool_calls"` when the model produced one or more tool calls. Other values: `"stop"` (natural completion), `"length"` (hit max tokens), `"content_filter"`. |
| `message`       | object | MUST     | The assistant's message — see below                                                                                                                                                                |

**Message fields when calling tools:**

| Field        | Type           | Required | Description                                                                                          |
| ------------ | -------------- | -------- | ---------------------------------------------------------------------------------------------------- |
| `role`       | `"assistant"`  | MUST     | Always `"assistant"` for model output                                                                |
| `content`    | string \| null | MUST     | Text content from the model. `null` if the model only produced tool calls without accompanying text. |
| `tool_calls` | array          | MUST     | One or more tool call objects (the model can request multiple tools in parallel)                     |

**Tool call object fields:**

| Field                | Type         | Required | Description                                                                                                                                                                                                                                        |
| -------------------- | ------------ | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                 | string       | MUST     | Unique identifier for this tool call (e.g. `"call_abc123"`). Used to correlate tool results back to the call in subsequent turns.                                                                                                                  |
| `type`               | `"function"` | MUST     | Always the literal string `"function"`                                                                                                                                                                                                             |
| `function.name`      | string       | MUST     | The name of the tool/function the model wants to call                                                                                                                                                                                              |
| `function.arguments` | string       | MUST     | The arguments as a **JSON-encoded string** (not a JSON object). Example: `"{\"location\": \"Paris\"}"`. The string MAY be malformed JSON if the model produced invalid output — in which case it MUST be passed through as-is rather than dropped. |

#### Anthropic (provider-native)

When the output is in Anthropic's native format, tool calls appear as `tool_use` content blocks within the assistant message:

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "tool_use",
      "id": "toolu_01A09q90qw90lq917835lq9",
      "name": "get_weather",
      "input": { "location": "Paris, France" }
    }
  ],
  "stop_reason": "tool_use"
}
```

**Tool use block fields:**

| Field   | Type         | Required | Description                                                                                              |
| ------- | ------------ | -------- | -------------------------------------------------------------------------------------------------------- |
| `type`  | `"tool_use"` | MUST     | Always `"tool_use"`                                                                                      |
| `id`    | string       | MUST     | Unique identifier (Anthropic format: `"toolu_..."`)                                                      |
| `name`  | string       | MUST     | The tool name                                                                                            |
| `input` | object       | MUST     | The tool arguments as a **JSON object** (NOT a string — this is a key difference from the OpenAI format) |

The response-level `stop_reason` SHOULD be `"tool_use"` when the model is requesting tool calls. Text and `tool_use` blocks may be interleaved in a single `content` array.

#### Google (provider-native)

When the output is in Google's native format, tool calls appear as `functionCall` parts within a candidate:

```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          {
            "functionCall": {
              "name": "get_weather",
              "args": { "location": "Paris, France" }
            }
          }
        ]
      },
      "finishReason": "STOP"
    }
  ]
}
```

**Function call fields:**

| Field  | Type   | Required | Description                                            |
| ------ | ------ | -------- | ------------------------------------------------------ |
| `name` | string | MUST     | The tool name                                          |
| `args` | object | MUST     | The tool arguments as a **JSON object** (NOT a string) |

Note that Google does not assign IDs to function calls (unlike OpenAI's `id` and Anthropic's `id`). If correlation is needed across turns, the SDK MUST generate stable IDs synthetically.

### Tool result messages (multi-turn)

When the user makes a follow-up completion API call after executing a tool, the tool's return value is sent back to the model as a message. This message is part of the **input** of the next span. Format depends on the provider convention being used:

**OpenAI (default):**

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "{\"temperature\": 18, \"unit\": \"celsius\"}"
}
```

The `tool_call_id` MUST match the `id` from the corresponding tool call in the previous turn. `content` is typically a string (often JSON-encoded).

**Anthropic (provider-native):** Tool results are content blocks inside a `user` message:

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_01A09q90qw90lq917835lq9",
      "content": "{\"temperature\": 18, \"unit\": \"celsius\"}"
    }
  ]
}
```

**Google (provider-native):** Tool results appear as `functionResponse` parts in a `user` role message:

```json
{
  "role": "user",
  "parts": [
    {
      "functionResponse": {
        "name": "get_weather",
        "response": { "temperature": 18, "unit": "celsius" }
      }
    }
  ]
}
```

### Available tool definitions

Available tool definitions are the schemas and configuration the user passes to the model in the request, declaring what tools the model is allowed to call for that exact LLM call. They are **request configuration**, not conversation content — so they MUST NOT appear in the `input` messages array. Instead, they are transported on the span's `metadata` field.

#### Where they go

Available tool definitions MUST be placed in `metadata.tools` on every `llm` span whose request makes one or more tools available. `metadata.tools` is an array of OpenAI Chat Completions-style tool objects for function-like tools, regardless of the underlying provider:

```json
{
  "metadata": {
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "Get the current weather for a location",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {
                "type": "string",
                "description": "The city and state, e.g. San Francisco, CA"
              },
              "unit": {
                "type": "string",
                "enum": ["celsius", "fahrenheit"]
              }
            },
            "required": ["location"]
          },
          "strict": false
        }
      }
    ],
    "tool_choice": "auto",
    "parallel_tool_calls": true,
    "max_tool_calls": 3
  }
}
```

If a model call occurs inside an agentic tool-use loop, each child `llm` span MUST include the `metadata.tools` value for the tools available to that specific model call. Do not copy a parent or earlier child span's tools if the available tool set changed.

#### Tool object schema

Each function-like entry in `metadata.tools` MUST conform to the following shape:

| Field                  | Type         | Required | Description                                                                                                                                               |
| ---------------------- | ------------ | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `type`                 | `"function"` | MUST     | Always the literal string `"function"` for user-defined function-like tools.                                                                              |
| `function.name`        | string       | MUST     | The tool name. MUST exactly match the `name` the model emits in its tool calls so the user can correlate definitions, calls, and results.                 |
| `function.description` | string       | MAY      | Human-readable description of what the tool does. Helps the model decide when to call it.                                                                 |
| `function.parameters`  | object       | SHOULD   | A [JSON Schema](https://json-schema.org/) object describing the tool's input arguments. May be omitted for tools that take no arguments.                  |
| `function.strict`      | boolean      | MAY      | Whether the model is constrained to produce arguments that strictly match the schema. Preserve `true` or `false` when known; omit when unknown or `null`. |

If the user passed no tools in the request, `metadata.tools` MUST be omitted (do NOT emit an empty array).

#### Tool request controls

If the user passed a `tool_choice` (or equivalent) parameter to control whether/which tool the model uses, it MUST be captured in `metadata.tool_choice`. Valid values follow the OpenAI convention:

- `"auto"` — Model decides whether to call tools (default)
- `"none"` — Model is forbidden from calling tools
- `"required"` — Model MUST call at least one tool
- `{ "type": "function", "function": { "name": "..." } }` — Model MUST call this specific tool

Other provider-specific values (e.g. Anthropic's `{ "type": "any" }`, Google's `function_calling_config.mode`) MUST be normalized to one of the OpenAI values above before being placed in `metadata.tool_choice`.

If the user passed `parallel_tool_calls`, `max_tool_calls`, or equivalent provider/framework settings, instrumentation MUST preserve them as `metadata.parallel_tool_calls` and `metadata.max_tool_calls` when supplied or known.

#### Converting from provider-native formats

The SDK MUST convert the provider's tool definition format into the OpenAI shape above before placing it in metadata.

#### Provider-native tool types

Some providers offer built-in tools that are not user-defined functions (e.g. Anthropic's `computer_use`, `text_editor`, `bash`; OpenAI's `web_search`, `file_search`). These MUST remain in `metadata.tools` if the user supplied them, since they affect the model's behavior. Preserve the provider-native `type` and JSON-serializable configuration for these tools; do not provide fake function names, input schemas, or output schemas.

Instrumentation MUST NOT log executable tool handlers, closures, code bodies, or other non-JSON runtime objects in `metadata.tools`. If the framework exposes both runtime handlers and serializable tool definitions, log only the serializable definitions sent or made available to the model.

### Prompt metadata

When an LLM call uses a Braintrust-managed prompt (either remote or locally defined using the SDK), instrumentation MUST attach the prompt provenance to the same `llm` span whose `input` contains the rendered prompt. This metadata lets Braintrust connect logged spans back to saved prompts, prompt versions, playground runs, and the exact variables used to render the prompt.

Prompt metadata is span metadata, not conversation content. It MUST be placed in `metadata.prompt`; it MUST NOT be included in the `input` messages array, in provider request payloads, or in `metadata.tools`.

#### Where it goes

Native Braintrust SDK logging MUST emit prompt provenance as nested span metadata:

```json
{
  "metadata": {
    "prompt": {
      "id": "prompt_123",
      "project_id": "project_456",
      "version": "1715895278123456",
      "variables": {
        "question": "What is the capital of France?"
      }
    }
  }
}
```

OpenTelemetry exporters MUST JSON-encode the same object in `braintrust.metadata`:

```json
{
  "braintrust.metadata": "{\"prompt\":{\"id\":\"prompt_123\",\"project_id\":\"project_456\",\"version\":\"1715895278123456\",\"variables\":{\"question\":\"What is the capital of France?\"}}}"
}
```

#### Prompt metadata schema

When `metadata.prompt` is present, it MUST conform to the following shape:

| Field               | Type   | Required                 | Description                                                                                     |
| ------------------- | ------ | ------------------------ | ----------------------------------------------------------------------------------------------- |
| `id`                | string | MUST                     | The rendered prompt row/function identifier.                                                    |
| `project_id`        | string | MUST                     | The Braintrust project containing the prompt reference.                                         |
| `version`           | string | MUST                     | The prompt row/version transaction identifier used to render the prompt.                        |
| `variables`         | any    | MUST                     | The exact JSON-serializable render/build variables used for the call.                           |
| `prompt_session_id` | string | MUST for prompt sessions | Playground/prompt-session identifier. Required when the prompt comes from a playground session. |

If the call does not use a Braintrust-managed prompt, `metadata.prompt` MUST be omitted.

For a playground or prompt-session call, instrumentation MUST emit the same `metadata.prompt` shape and include `prompt_session_id` in addition to `id`, `project_id`, `version`, and `variables`.

#### Injection and merging

Prompt builders MAY use wrapper-only carrier fields (for example, `span_info`) to pass prompt provenance from prompt rendering into instrumentation wrappers. These carrier fields are internal plumbing only: instrumentation MUST strip them before sending the provider request and MUST NOT log them in span `input`.

Instrumentation MUST merge `metadata.prompt` with other span metadata such as `provider`, `model`, `tools`, and `tool_choice`. `metadata.prompt` is reserved Braintrust provenance metadata; user-supplied metadata MUST NOT overwrite it.

### Metadata

Every LLM span MUST include:

| Field      | Description                                                          | Example                  |
| ---------- | -------------------------------------------------------------------- | ------------------------ |
| `model`    | The resolved model identifier as returned by the API                 | `gpt-4o-mini-2024-07-18` |
| `provider` | The provider, gateway, or reseller whose pricing applies to the call | `openai`                 |

The `model` field SHOULD use the model string from the API response (which may include a version suffix) rather than the string the user passed in the request. The `provider` field is required even when model names are globally recognizable, because gateways and resellers can price the same model differently.

Instrumentation MAY include only the following LLM request configuration fields in metadata when they are present and JSON-serializable: `temperature`, `top_p`, `max_tokens`, `frequency_penalty`, `presence_penalty`, `stop`, and `response_format`.

Tool-related metadata fields are specified in [Available tool definitions](#available-tool-definitions). Prompt provenance metadata fields are specified in [Prompt metadata](#prompt-metadata). Any additional metadata field requires a specification update before SDKs emit it.

### Metrics

Every completion API span MUST capture:

| Metric              | Type   | Description              |
| ------------------- | ------ | ------------------------ |
| `tokens`            | number | Total tokens used        |
| `prompt_tokens`     | number | Input/prompt tokens      |
| `completion_tokens` | number | Output/completion tokens |

All metric values MUST be non-negative numbers.

---

## Agentic API Instrumentation

Agentic APIs manage the tool-use loop internally: the SDK calls the model, executes any requested tools, feeds results back, and repeats until the model produces a final response. This entire loop MUST be captured as a span tree.

### Parent span (the agent run)

The outermost span MUST have:

- `span_attributes.type` = `"task"`
- `span_attributes.name` = a descriptive name for the operation (e.g. the framework's function name, or `"agent run"`)

The parent span SHOULD capture:

- **Input**: The initial user messages / prompt that started the agent run
- **Output**: The final response produced after all tool loops complete
- **Metrics**: Aggregated token counts across all child LLM calls (`tokens`, `prompt_tokens`, `completion_tokens`)

The parent span's lifetime covers the entire agent run — from the initial call to the final response.

### Child LLM spans

Each individual LLM API call within the loop MUST produce a child `llm` span, following the exact same structure as [Completion API Instrumentation](#completion-api-instrumentation). This means:

- The input captures the messages sent to the model for that specific call (including tool results from previous iterations)
- The output captures the model's response (which may include tool calls or a final text response)
- Metrics capture token counts for that individual call
- Metadata includes `model`, `provider`, and any available tool definitions for that specific model call in `metadata.tools`

### Child tool spans (tool executions)

Each tool execution MUST produce a child `tool` span with:

- `span_attributes.type` = `"tool"`
- `span_attributes.name` = the tool/function name (e.g. `"get_weather"`, `"search_db"`)
- **Input**: The arguments the model provided for the tool call
- **Output**: The return value of the tool execution

### Ordering

Child spans MUST reflect the actual execution order. In a typical agentic loop:

1. `llm` span — model generates tool calls
2. `tool` span(s) — tools execute (may be parallel if the model requested multiple tools)
3. `llm` span — model receives tool results and either generates more tool calls or a final response
4. Repeat until the model produces a final response without tool calls

### Example: full agentic span tree

User asks: _"What's the weather in Paris and Tokyo?"_

```
task  "generateText"                          input: [{role: "user", content: "What's the weather..."}]
│                                             output: "The weather in Paris is 18°C and Tokyo is 25°C."
│                                             metrics: {tokens: 820, prompt_tokens: 600, completion_tokens: 220}
│
├── llm  "Chat Completion"                    input: [{role: "user", content: "What's the weather..."}]
│                                             output: [{finish_reason: "tool_calls", message: {tool_calls: [...]}}]
│                                             metrics: {tokens: 180, prompt_tokens: 120, completion_tokens: 60}
│
├── tool  "get_weather"                        input: {location: "Paris, France"}
│                                             output: {temperature: 18, unit: "celsius"}
│
├── tool  "get_weather"                        input: {location: "Tokyo, Japan"}
│                                             output: {temperature: 25, unit: "celsius"}
│
└── llm  "Chat Completion"                    input: [{role: "user", content: "What's the weather..."},
                                                      {role: "assistant", tool_calls: [...]},
                                                      {role: "tool", content: "{temp: 18...}"},
                                                      {role: "tool", content: "{temp: 25...}"}]
                                              output: [{finish_reason: "stop", message: {content: "The weather..."}}]
                                              metrics: {tokens: 640, prompt_tokens: 480, completion_tokens: 160}
```

---

## Streaming

Streaming applies to both completion and agentic APIs. It does not change the span structure — only adds requirements.

### Accumulation

The SDK MUST accumulate streamed chunks and produce a single complete `input` and `output` on the span, identical in structure to a non-streaming call. The user MUST NOT need to do anything different to get complete logged data for streamed responses.

### Additional metrics

| Metric                | Type   | Description                                                 |
| --------------------- | ------ | ----------------------------------------------------------- |
| `time_to_first_token` | number | Seconds from request initiation to the first chunk received |

This metric MUST be captured for all streaming calls. It is measured by the SDK, not reported by the provider.

### Token counts from stream metadata

Token metrics (`tokens`, `prompt_tokens`, `completion_tokens`) MUST be captured from the stream's usage metadata (e.g. OpenAI's `stream_options.include_usage`). If the provider does not include usage in the stream, the SDK SHOULD still attempt to capture token counts if they become available (e.g. from a final stream event).

---

## Reasoning Models

Models that perform chain-of-thought reasoning (e.g. OpenAI o-series) require additional capture.

### Additional metrics

| Metric                        | Type   | Description                        |
| ----------------------------- | ------ | ---------------------------------- |
| `completion_reasoning_tokens` | number | Tokens used for internal reasoning |

This metric MUST be captured when the provider reports it.

### Output structure

The output for reasoning models includes both reasoning and message blocks:

```json
[
  {
    "type": "reasoning",
    "summary": [{ "type": "summary_text", "text": "..." }]
  },
  {
    "type": "message",
    "role": "assistant",
    "status": "completed",
    "content": [
      {
        "type": "output_text",
        "text": "The answer is ..."
      }
    ]
  }
]
```

### Multi-turn with reasoning context

When a multi-turn conversation includes prior reasoning output, the full context (including prior reasoning blocks and assistant messages) MUST be included in the `input` of subsequent spans.

---

## Multimodal / Attachments

When an instrumented request or response contains inline binary media (images, PDFs, audio, video, etc.), SDKs MUST replace the raw media with Braintrust attachment references inside the log row's `input` or `output` payload. Do not add a separate attachment list. The lower-level scan, upload, retry, and fallback behavior is specified in [Attachments](features/attachments.md).

Attachment conversion is both a storage optimization and a display requirement. When conversion succeeds, raw media bytes MUST NOT remain inline in `input` or `output`. If conversion or upload fails, instrumentation MUST preserve the original payload and MUST NOT throw an exception that prevents span export.

### What SDKs must emit

Generate the same `input` and `output` payloads the SDK would normally log, but replace each inline media leaf with a `braintrust_attachment` object.

For a multimodal chat input, the replacement is local to the media field:

```diff
 {
   "role": "user",
   "content": [
     { "type": "text", "text": "Briefly describe these attachments" },
     {
       "type": "image_url",
       "image_url": {
-        "url": "data:image/png;base64,<base64>"
+        "url": {
+          "type": "braintrust_attachment",
+          "content_type": "image/png",
+          "filename": "attachment.png",
+          "key": "<attachment uuid>"
+        }
       }
     },
     {
       "type": "file",
       "file": {
         "filename": "blank.pdf",
-        "file_data": "data:application/pdf;base64,<base64>"
+        "file_data": {
+          "type": "braintrust_attachment",
+          "content_type": "application/pdf",
+          "filename": "blank.pdf",
+          "key": "<attachment uuid>"
+        }
       }
     }
   ]
 }
```

For OTel instrumentation, write these same JSON values as strings on the OTel span:

```js
span.setAttribute("braintrust.input_json", JSON.stringify(input));
span.setAttribute("braintrust.output_json", JSON.stringify(output));
```

After ingestion, Braintrust decodes those attributes into the row's `input` and `output` fields. Native Braintrust logging APIs should send the same JSON values directly as `input` and `output`.

Do not generate `braintrust.attachments`, `metadata.attachments`, or a top-level `attachments` field. The attachment reference belongs at the exact field that formerly contained the data URL, base64 string, bytes, buffer, or provider SDK file object.

### Attachment reference

The canonical replacement object is:

```json
{
  "type": "braintrust_attachment",
  "content_type": "image/png",
  "filename": "attachment.png",
  "key": "<attachment uuid>"
}
```

| Field          | Description                                             |
| -------------- | ------------------------------------------------------- |
| `type`         | Always `"braintrust_attachment"`                        |
| `content_type` | MIME type of the attachment                             |
| `filename`     | Generated or provider-supplied filename                 |
| `key`          | Usually a UUID v4 string identifying the uploaded bytes |

`filename`, `content_type`, and `key` MUST be non-empty strings. In current Braintrust SDKs and backend auto-conversion, `key` is generated as a UUID v4 string for each attachment. New SDKs SHOULD use the same convention. It is not a URL, filename, provider file ID, or content hash. Braintrust uses this id to derive the actual object-store path, so the `braintrust_attachment` reference should contain only the UUID-like id, not the full storage path. Use the same `key` when requesting the signed upload URL, uploading the bytes, reporting upload status, and writing the reference into `input` or `output`; treat it as opaque after it is generated.

Existing `external_attachment` and `inline_attachment` objects are valid Braintrust attachment forms and SHOULD be preserved when a provider or Braintrust API already supplies them. Remote media URLs SHOULD be logged as URLs or external references; instrumentation MUST NOT fetch arbitrary remote URLs solely to create an attachment.

SDK instrumentation SHOULD convert inline media to `braintrust_attachment` references before exporting the span. Backend conversion of known raw base64 formats is a fallback for older SDKs and unexpected payloads, not the preferred implementation path.

### Input payloads

SDKs MUST recursively scan provider request inputs and convert inline media in all message/content containers that the provider accepts. Convert these forms when the MIME type is known or can be inferred:

- Data URL strings such as `data:image/png;base64,...`
- Raw base64 strings whose surrounding provider field supplies a MIME type
- Bytes, buffers, array buffers, typed arrays, file-like objects, or local file/path objects exposed by the provider SDK wrapper

When instrumentation cannot determine a valid MIME type or cannot decode the value, it MUST leave the original value unchanged.

For normalized content parts that are not constrained to a provider-native shape, place attachments inside the message/content payload, not in `metadata`:

| Media type                                     | Logged content part                                                                              |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Images (`image/*`)                             | `{ "type": "image_url", "image_url": { "url": <braintrust_attachment> } }`                       |
| PDFs, documents, audio, video, and other files | `{ "type": "file", "file": { "filename": "<filename>", "file_data": <braintrust_attachment> } }` |

Preserve provider-supplied filenames when available.

If a provider-native payload has a dedicated Braintrust UI normalizer, instrumentation MAY preserve that provider-native structure and replace only the raw media leaf with a `braintrust_attachment`. Otherwise, instrumentation SHOULD emit the normalized `image_url` or `file` content parts above. Provider-unsupported media should still be represented in the logged attempted input. Instrumentation MUST NOT rewrite a provider request into a different provider-supported shape to hide an error from the underlying API.

### Output payloads

The same attachment rules apply to generated media in `output`. Generated media MUST be logged in the `output` payload, not in `metadata`. If the provider response already has an output item or content part containing inline media, preserve that provider response structure and replace only the binary leaf with a `braintrust_attachment`. If there is no provider-native structure to preserve, use the same normalized `image_url` and `file` content part shapes used for inputs.

- Chat audio outputs: attach binary audio data, preserve compact transcript/text fields, and record these audio metadata fields when the provider reports them: MIME type, byte size, and audio token metrics.
- Image generation and image edit outputs: convert returned base64 image data from provider-specific result fields to image attachments. Preserve provider status, prompt/revised prompt, and model when the provider reports them.
- Speech-to-text and OCR: log input media or documents as attachments. Log transcripts, pages, detected text, and structured extraction results as text/JSON. Attach any large returned page images or media artifacts.
- Text-to-speech: log input text as normal request input and log generated audio as an attachment.
- Video generation and other long-running media operations: when the wrapper waits or polls for completion, log the initial request and final media result on the `llm` span. If the wrapper only starts an operation, log the provider operation ID and status when available at return time.

### Streaming multimodal outputs

Streaming instrumentation MUST aggregate media chunks into the final `output` rather than dropping them or logging raw chunks as separate opaque blobs. The final span output SHOULD contain the same attachment-normalized shape as a non-streaming response.

- Inline media output parts MUST be accumulated and converted to image or file attachments.
- Streaming audio chunks SHOULD be aggregated into transcript/audio output. If binary audio data is retained, it MUST be converted to an attachment.
- `time_to_first_token` and other streaming metrics remain computed from the stream timing even when final media attachment conversion happens at the end of the stream.

### Multimodal API surfaces

These API families SHOULD follow the same attachment rules even when they are not chat/message APIs. SDK support may be phased in over time; this table defines the desired instrumentation shape without prescribing provider-specific APIs.

| API family                              | Span shape                                                                                                                                                                  |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Image generation / editing              | One `llm` span per model execution. Input prompt/reference images are logged in `input`; generated images are attachments in `output`.                                      |
| Video generation                        | One `llm` span for the operation observed by the wrapper. Inputs and final video artifacts use attachments; operation IDs/status remain in metadata or output.              |
| Audio transcription / speech generation | Speech-to-text attaches input audio and logs transcript output. Text-to-speech logs text input and attaches generated audio output.                                         |
| OCR / document understanding            | Attach input documents/images and log extracted text/structured page data as JSON.                                                                                          |
| Multimodal embeddings                   | For now, only track token metrics when the provider reports them. Detailed multimodal embedding payload conventions are still a separate TODO.                              |
| Realtime / live APIs                    | Use a parent `task` span for the session with child spans for model turns, media exchanges, and tool calls. Detailed event lifecycle conventions are still a separate TODO. |
| Prediction-style model runner APIs      | Log provider-native input/output JSON, converting any media fields with inline bytes/base64/data URLs into attachments.                                                     |

---

## Token Caching

Some providers support prompt caching which can significantly reduce costs and latency.

### Metrics

| Metric                         | Type   | Description                            |
| ------------------------------ | ------ | -------------------------------------- |
| `prompt_cached_tokens`         | number | Tokens read from the provider's cache  |
| `prompt_cache_creation_tokens` | number | Tokens written to the provider's cache |

These metrics SHOULD be captured when the provider reports them. They are not present in all responses — only when the provider's caching mechanism is active.

---

## Framework Integration Principles

Braintrust SDKs integrate with higher-level frameworks that wrap LLM provider APIs.

### Completion-style frameworks

Frameworks that expose a completion-style API (single call, no internal tool loop) — such as LiteLLM — MUST produce spans identical to direct provider calls:

- One `llm` span per call
- `metadata.provider` MUST identify the underlying provider (e.g. `"openai"`), NOT the framework name (e.g. NOT `"litellm"`)

### Agentic frameworks

Frameworks that manage tool-use loops — such as Vercel AI SDK (`generateText`/`streamText` with tools), LangChain agents, OpenAI Agents SDK, Claude Agent SDK — MUST follow the [Agentic API Instrumentation](#agentic-api-instrumentation) structure:

- One parent `task` span for the overall operation
- Child `llm` spans for each model call
- Child `tool` spans for each tool execution

### LangChain / LangChain.js

LangChain may add its own intermediate spans (e.g. for chain steps, retrievers). These are acceptable as additional spans in the tree, but the leaf `llm` spans MUST conform to this spec.

### Vercel AI SDK

Instrument calls through the Vercel AI SDK's `generateText`, `streamText`, and related functions. Attribute prefix: `ai.*`. When tools are provided, these become agentic calls and MUST produce the full span tree.

---

## Metrics Reference

Instrumentation MUST only emit the metric keys listed in this guide. The following are standard metrics that instrumentation SHOULD populate. See [Token and cost metrics](features/token-and-cost-metrics.md) for full semantics, completeness requirements, and cost formulas.

| Metric                            | Type   | Applies to       | Required | Description                                      |
| --------------------------------- | ------ | ---------------- | -------- | ------------------------------------------------ |
| `start`                           | number | All spans        | MUST     | Unix timestamp when the span started             |
| `end`                             | number | All spans        | MUST     | Unix timestamp when the span ended               |
| `tokens`                          | number | All LLM spans    | MUST     | Total tokens (prompt + completion)               |
| `prompt_tokens`                   | number | All LLM spans    | MUST     | Input / prompt tokens                            |
| `completion_tokens`               | number | All LLM spans    | MUST     | Output / completion tokens                       |
| `time_to_first_token`             | number | Streaming spans  | MUST     | Seconds from request start to first chunk        |
| `completion_reasoning_tokens`     | number | Reasoning models | MUST\*   | Tokens used for model reasoning                  |
| `prompt_cached_tokens`            | number | Cached responses | SHOULD   | Tokens read from provider cache                  |
| `prompt_cache_creation_tokens`    | number | Cached responses | SHOULD   | Tokens written to provider cache                 |
| `prompt_cache_creation_5m_tokens` | number | Cached responses | SHOULD   | Cache-write tokens for 5-minute TTL entries      |
| `prompt_cache_creation_1h_tokens` | number | Cached responses | SHOULD   | Cache-write tokens for 1-hour TTL entries        |
| `prompt_audio_tokens`             | number | Audio models     | SHOULD   | Input audio tokens reported by provider          |
| `completion_audio_tokens`         | number | Audio models     | SHOULD   | Output audio tokens reported by provider         |
| `completion_image_tokens`         | number | Image models     | SHOULD   | Output image tokens reported by provider         |
| `estimated_cost`                  | number | LLM spans        | MAY      | Explicit per-span total estimated cost in dollars |

\* MUST be captured when the provider reports it; not all providers/models support reasoning tokens.

SDKs MUST NOT add metrics beyond the keys listed in this guide. Add new metric keys to this specification before emitting them.

---

## Span Attributes Reference

Braintrust-specific OTel attributes used by the SDK instrumentation. These are the keys read by the Braintrust ingestion pipeline when consuming OTel spans.

### Routing and context

| Attribute            | Type   | Description                                                                                                                                                                           |
| -------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `braintrust.parent`  | string | Serialized parent reference used to attach the span to a Braintrust container (project, experiment, dataset, or another span). Required for the ingestion endpoint to route the span. |
| `braintrust.org`     | string | The Braintrust organization name the span belongs to. Set by the SDK when the org cannot be inferred from the API key alone.                                                          |
| `braintrust.app_url` | string | The Braintrust app URL associated with the span, used by the ingestion endpoint to disambiguate environments (e.g. production vs staging).                                            |

`braintrust.parent`, `braintrust.org`, and `braintrust.app_url` are treated as _system_ attributes by the SDK's AI-span filter — their presence alone does not mark a span as AI-related.

### Code location

Braintrust also consumes the standard OTel code attributes for caller location:

| Attribute            | Type   | Location       | Extracted context field       |
| -------------------- | ------ | -------------- | ----------------------------- |
| `code.function.name` | string | Span attribute | `context.caller_functionname` |
| `code.file.path`     | string | Span attribute | `context.caller_filename`     |
| `code.line.number`   | int    | Span attribute | `context.caller_lineno`       |

### Span origin provenance

| Attribute                 | Type   | Location       | Description                                                                                                                          |
| ------------------------- | ------ | -------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `braintrust.context_json` | string | Span attribute | JSON-encoded context object. Extracted into the `context` field of the log row and deep-merged with backend-derived OTel provenance. SDK/exporter-provided span-origin environment provenance is encoded inside this object as `context.span_origin.environment`. |

SDKs and exporters SHOULD encode Braintrust span-origin provenance in `braintrust.context_json` as `context.span_origin`. Ingestion MUST use those explicit `context.span_origin` values when present. When explicit Braintrust span-origin provenance is not provided on an OTLP span, ingestion SHOULD set `context.span_origin.name` to `opentelemetry` and SHOULD derive `context.span_origin.version` from the OTel `telemetry.sdk.version` resource attribute when present.

OTLP ingestion SHOULD derive `context.span_origin.instrumentation.name` from the OTLP instrumentation scope name.

SDKs and exporters MUST NOT emit environment provenance as standalone `braintrust.environment.*` resource or span attributes. If environment provenance is known, encode it inside `braintrust.context_json` as `context.span_origin.environment`.

Braintrust Gateway/internal OTLP emitters SHOULD set `context.span_origin.name = "braintrust.gateway"` in `braintrust.context_json`. They SHOULD include `context.span_origin.environment` only when there is separate runtime context worth recording, such as a server platform or CI environment. SDKs and general OTLP ingest MUST NOT infer gateway identity from public span attributes, routes, model/provider metadata, or `metadata.provider`.

### Span content

| Attribute                    | Type   | Description                                                                                                                                                                                                                                           |
| ---------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `braintrust.input_json`      | string | JSON-encoded request input. For LLM spans, this is the messages array (or provider-equivalent input). Extracted into the `input` field of the log row.                                                                                                |
| `braintrust.output_json`     | string | JSON-encoded response output. For LLM spans, this is the response choices/output. Extracted into the `output` field of the log row.                                                                                                                   |
| `braintrust.expected_json`   | string | JSON-encoded expected output for eval cases. Extracted into the `expected` field of the log row.                                                                                                                                                      |
| `braintrust.metadata`        | string | JSON-encoded metadata (e.g. `model`, `provider`, allowed request parameters such as `temperature`/`max_tokens`, available tool definitions in `tools`, and nested prompt provenance in `prompt`). Extracted into the `metadata` field of the log row. |
| `braintrust.metrics`         | string | JSON-encoded metric annotations attached to the span. Used to pass SDK-computed metrics (e.g. `time_to_first_token`, token counts) to the Braintrust exporter as the `metrics` log field.                                                             |
| `braintrust.scores`          | string | JSON-encoded map of score name → numeric value. Set on `score` spans produced by evals. Extracted into the `scores` field of the log row.                                                                                                             |
| `braintrust.span_attributes` | string | JSON-encoded span type and naming info, e.g. `{"type": "llm"}` or `{"type": "task", "name": "agent run"}`. Extracted into the `span_attributes` field of the log row.                                                                                 |

### Span properties

| Attribute           | Type         | Description                                                                                                                                                                                |
| ------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `braintrust.tags`   | string array | Tags attached to the log row. Set as a native OTel string-array attribute (not JSON-encoded).                                                                                              |
| `braintrust.origin` | string       | JSON-encoded origin reference identifying the source row this span derives from (e.g. a dataset row pointer with `object_type`, `object_id`, and `id`). Extracted into the `origin` field. |

### Legacy aliases

For backward compatibility, the ingestion pipeline also accepts the non-`_json` forms below. New instrumentation SHOULD prefer the `_json` variants documented above.

| Attribute             | Type   | Equivalent to              |
| --------------------- | ------ | -------------------------- |
| `braintrust.input`    | string | `braintrust.input_json`    |
| `braintrust.output`   | string | `braintrust.output_json`   |
| `braintrust.expected` | string | `braintrust.expected_json` |

---

## TODO

The following areas still need to be specified:

- **Embedding APIs** — instrumentation for embedding endpoints (e.g. OpenAI `embeddings.create`, Google `embedContent`), including input/output structure, token metrics
- **Realtime APIs** — detailed instrumentation for realtime/WebSocket-based APIs (e.g. OpenAI Realtime API), including event lifecycle, session finalization, and interruption/cancellation behavior
- **Reranking APIs** — instrumentation for reranking endpoints (e.g. Cohere `rerank`, Jina Reranker), including input/output structure and relevance score metrics
