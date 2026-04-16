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
| `context`         | object                       | Code location (caller_functionname, caller_filename, caller_lineno)  |

Note: `input` and `output` are **free-form JSON** — the backend does not enforce any structure on them. The conventions described in this guide are SDK-level standards for how instrumentation should populate these fields.

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

The `metrics` field is an object of string keys to numeric values. The backend accepts any numeric key-value pair. Standard fields:

| Field               | Description                               |
| ------------------- | ----------------------------------------- |
| `start`             | Unix timestamp when the span started      |
| `end`               | Unix timestamp when the span ended        |
| `prompt_tokens`     | Input/prompt token count (LLM spans)      |
| `completion_tokens` | Output/completion token count (LLM spans) |
| `tokens`            | Total token count (LLM spans)             |

Additional metrics (e.g. `time_to_first_token`, `completion_reasoning_tokens`) are added as needed — the backend accepts arbitrary numeric keys.

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

Braintrust SDK spans use the following attribute prefixes (see also the [AI span filtering spec](../feature/filter-ai-spans.md)):

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

| Field           | Type            | Required | Description                                                                                          |
| --------------- | --------------- | -------- | ---------------------------------------------------------------------------------------------------- |
| `index`         | number          | SHOULD   | The index of this choice in the response (0 for single-choice responses)                             |
| `finish_reason` | string          | MUST     | Why the model stopped generating. Use `"tool_calls"` when the model produced one or more tool calls. Other values: `"stop"` (natural completion), `"length"` (hit max tokens), `"content_filter"`. |
| `message`       | object          | MUST     | The assistant's message — see below                                                                  |

**Message fields when calling tools:**

| Field        | Type             | Required | Description                                                                                                       |
| ------------ | ---------------- | -------- | ----------------------------------------------------------------------------------------------------------------- |
| `role`       | `"assistant"`    | MUST     | Always `"assistant"` for model output                                                                             |
| `content`    | string \| null   | MUST     | Text content from the model. `null` if the model only produced tool calls without accompanying text.              |
| `tool_calls` | array            | MUST     | One or more tool call objects (the model can request multiple tools in parallel)                                  |

**Tool call object fields:**

| Field                | Type            | Required | Description                                                                                          |
| -------------------- | --------------- | -------- | ---------------------------------------------------------------------------------------------------- |
| `id`                 | string          | MUST     | Unique identifier for this tool call (e.g. `"call_abc123"`). Used to correlate tool results back to the call in subsequent turns. |
| `type`               | `"function"`    | MUST     | Always the literal string `"function"`                                                               |
| `function.name`      | string          | MUST     | The name of the tool/function the model wants to call                                                |
| `function.arguments` | string          | MUST     | The arguments as a **JSON-encoded string** (not a JSON object). Example: `"{\"location\": \"Paris\"}"`. The string MAY be malformed JSON if the model produced invalid output — in which case it MUST be passed through as-is rather than dropped. |

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

| Field   | Type           | Required | Description                                                                                          |
| ------- | -------------- | -------- | ---------------------------------------------------------------------------------------------------- |
| `type`  | `"tool_use"`   | MUST     | Always `"tool_use"`                                                                                  |
| `id`    | string         | MUST     | Unique identifier (Anthropic format: `"toolu_..."`)                                                  |
| `name`  | string         | MUST     | The tool name                                                                                        |
| `input` | object         | MUST     | The tool arguments as a **JSON object** (NOT a string — this is a key difference from the OpenAI format) |

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

| Field  | Type   | Required | Description                                                                              |
| ------ | ------ | -------- | ---------------------------------------------------------------------------------------- |
| `name` | string | MUST     | The tool name                                                                            |
| `args` | object | MUST     | The tool arguments as a **JSON object** (NOT a string)                                   |

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

### Tool definitions

Tool definitions are the schemas the user passes to the model in the request, declaring what tools the model is allowed to call. They are **request configuration**, not conversation content — so they MUST NOT appear in the `input` messages array. Instead, they are transported on the span's `metadata` field.

#### Where they go

Tool definitions MUST be placed in `metadata.tools` as an array of OpenAI Chat Completions tool objects, regardless of the underlying provider:

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
    "tool_choice": "auto"
  }
}
```

#### Tool object schema

Each entry in `metadata.tools` MUST conform to the following shape:

| Field                            | Type           | Required | Description                                                                                                          |
| -------------------------------- | -------------- | -------- | -------------------------------------------------------------------------------------------------------------------- |
| `type`                           | `"function"`   | MUST     | Always the literal string `"function"`. (Future tool types like `"web_search"` may be added; for now use `"function"`.) |
| `function.name`                  | string         | MUST     | The tool name. MUST exactly match the `name` the model emits in its tool calls so the user can correlate them.        |
| `function.description`           | string         | SHOULD   | Human-readable description of what the tool does. Helps the model decide when to call it.                            |
| `function.parameters`            | object         | SHOULD   | A [JSON Schema](https://json-schema.org/) object describing the arguments the tool accepts. May be omitted for tools that take no arguments. |
| `function.strict`                | boolean        | MAY      | When `true`, the model is constrained to produce arguments that strictly match the schema. Pass through if the provider supports it. |

If the user passed no tools in the request, `metadata.tools` MUST be omitted (do NOT emit an empty array).

#### `tool_choice`

If the user passed a `tool_choice` (or equivalent) parameter to control whether/which tool the model uses, it MUST be captured in `metadata.tool_choice`. Valid values follow the OpenAI convention:

- `"auto"` — Model decides whether to call tools (default)
- `"none"` — Model is forbidden from calling tools
- `"required"` — Model MUST call at least one tool
- `{ "type": "function", "function": { "name": "..." } }` — Model MUST call this specific tool

Other provider-specific values (e.g. Anthropic's `{ "type": "any" }`, Google's `function_calling_config.mode`) MUST be normalized to one of the OpenAI values above before being placed in `metadata.tool_choice`.

#### Converting from provider-native formats

The SDK MUST convert the provider's tool definition format into the OpenAI shape above before placing it in metadata. The following table describes the field mappings.

**Anthropic → OpenAI:**

```
Anthropic                          OpenAI
─────────────────────────────────────────────────────────────────
{                                  {
  "name": "get_weather",             "type": "function",
  "description": "...",              "function": {
  "input_schema": {                    "name": "get_weather",
    "type": "object", ...               "description": "...",
  }                                     "parameters": {
}                                         "type": "object", ...
                                        }
                                      }
                                   }
```

The Anthropic `input_schema` field maps to `function.parameters`. The top-level `name` and `description` move under `function`.

**Google → OpenAI:**

Google passes tool declarations inside `tools[].function_declarations[]`. Each function declaration maps to one OpenAI tool:

```
Google                                                OpenAI
──────────────────────────────────────────────────────────────────────
{                                                     {
  "function_declarations": [                            "type": "function",
    {                                                   "function": {
      "name": "get_weather",                              "name": "get_weather",
      "description": "...",                               "description": "...",
      "parameters": { ... }                               "parameters": { ... }
    }                                                   }
  ]                                                   }
}
```

Google's `parameters` field is already a JSON Schema object, so it can be copied directly. The SDK MUST flatten `function_declarations` arrays — each declaration becomes its own entry in `metadata.tools`.

#### Provider-native tool types

Some providers offer built-in tools that are not user-defined functions (e.g. Anthropic's `computer_use`, `text_editor`, `bash`; OpenAI's `web_search`, `file_search`). These SHOULD be passed through with `type` reflecting the provider-native type and the rest of the configuration preserved as-is under `function` (or under a sibling key matching the provider's API). Capturing them is REQUIRED if the user supplied them, since they affect the model's behavior. The exact schema for these is provider-specific and is outside the scope of this section.

### Metadata

Every LLM span MUST include:

| Field      | Description                                 | Example                  |
| ---------- | ------------------------------------------- | ------------------------ |
| `model`    | The model identifier as returned by the API | `gpt-4o-mini-2024-07-18` |
| `provider` | The provider name                           | `openai`                 |

The `model` field SHOULD use the model string from the API response (which may include a version suffix) rather than the string the user passed in the request.

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
- Metadata includes `model` and `provider`

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

When inputs contain non-text content (images, audio, etc.), the SDK MUST handle them as Braintrust attachments.

### Image inputs

Inline image data (base64-encoded or data URIs) MUST be converted to Braintrust attachment references:

```json
{
  "type": "image_url",
  "image_url": {
    "url": {
      "type": "braintrust_attachment",
      "content_type": "image/png",
      "filename": "<generated>",
      "key": "<storage key>"
    }
  }
}
```

The original raw image bytes MUST NOT be stored inline in the span. Instead, the SDK uploads the image data and replaces the inline content with an attachment reference containing:

| Field          | Description                               |
| -------------- | ----------------------------------------- |
| `type`         | Always `"braintrust_attachment"`          |
| `content_type` | MIME type of the attachment               |
| `filename`     | Generated filename (non-empty string)     |
| `key`          | Storage key for retrieving the attachment |

### Google-specific

Google uses `inline_data` with `mime_type` and `data` fields. The SDK MUST convert these to the same `braintrust_attachment` reference format within the `parts` array, under an `image_url.url` wrapper.

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

The `metrics` object accepts arbitrary numeric keys. The following are standard metrics that instrumentation SHOULD populate:

| Metric                         | Type   | Applies to       | Required | Description                                |
| ------------------------------ | ------ | ---------------- | -------- | ------------------------------------------ |
| `start`                        | number | All spans        | MUST     | Unix timestamp when the span started       |
| `end`                          | number | All spans        | MUST     | Unix timestamp when the span ended         |
| `tokens`                       | number | All LLM spans    | MUST     | Total tokens (prompt + completion)         |
| `prompt_tokens`                | number | All LLM spans    | MUST     | Input / prompt tokens                      |
| `completion_tokens`            | number | All LLM spans    | MUST     | Output / completion tokens                 |
| `time_to_first_token`          | number | Streaming spans  | MUST     | Seconds from request start to first chunk  |
| `completion_reasoning_tokens`  | number | Reasoning models | MUST\*   | Tokens used for chain-of-thought reasoning |
| `prompt_cached_tokens`         | number | Cached responses | SHOULD   | Tokens read from provider cache            |
| `prompt_cache_creation_tokens` | number | Cached responses | SHOULD   | Tokens written to provider cache           |

\* MUST be captured when the provider reports it; not all providers/models support reasoning tokens.

SDKs MAY add additional numeric metrics beyond this list.

---

## Span Attributes Reference

Braintrust-specific OTel span attributes used by the SDK instrumentation. These are the keys read by the Braintrust ingestion pipeline when consuming OTel spans.

### Routing and context

| Attribute             | Type   | Description                                                                                                                                                                            |
| --------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `braintrust.parent`   | string | Serialized parent reference used to attach the span to a Braintrust container (project, experiment, dataset, or another span). Required for the ingestion endpoint to route the span. |
| `braintrust.org`      | string | The Braintrust organization name the span belongs to. Set by the SDK when the org cannot be inferred from the API key alone.                                                          |
| `braintrust.app_url`  | string | The Braintrust app URL associated with the span, used by the ingestion endpoint to disambiguate environments (e.g. production vs staging).                                            |

`braintrust.parent`, `braintrust.org`, and `braintrust.app_url` are treated as *system* attributes by the SDK's AI-span filter — their presence alone does not mark a span as AI-related.

### Span content

| Attribute                  | Type   | Description                                                                                                                                                                              |
| -------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `braintrust.input_json`    | string | JSON-encoded request input. For LLM spans, this is the messages array (or provider-equivalent input). Extracted into the `input` field of the log row.                                   |
| `braintrust.output_json`   | string | JSON-encoded response output. For LLM spans, this is the response choices/output. Extracted into the `output` field of the log row.                                                      |
| `braintrust.expected_json` | string | JSON-encoded expected output for eval cases. Extracted into the `expected` field of the log row.                                                                                         |
| `braintrust.metadata`      | string | JSON-encoded metadata (e.g. `model`, `provider`, request parameters like `temperature`/`max_tokens`). Extracted into the `metadata` field of the log row.                                |
| `braintrust.metrics`       | string | JSON-encoded metric annotations attached to the span. Used to pass SDK-computed metrics (e.g. `time_to_first_token`, token counts) to the Braintrust exporter as the `metrics` log field.|
| `braintrust.scores`        | string | JSON-encoded map of score name → numeric value. Set on `score` spans produced by evals. Extracted into the `scores` field of the log row.                                                |
| `braintrust.span_attributes` | string | JSON-encoded span type and naming info, e.g. `{"type": "llm"}` or `{"type": "task", "name": "agent run"}`. Extracted into the `span_attributes` field of the log row.                  |

### Span properties

| Attribute            | Type           | Description                                                                                                                                                                                       |
| -------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `braintrust.tags`    | string array   | Tags attached to the log row. Set as a native OTel string-array attribute (not JSON-encoded).                                                                                                     |
| `braintrust.origin`  | string         | JSON-encoded origin reference identifying the source row this span derives from (e.g. a dataset row pointer with `object_type`, `object_id`, and `id`). Extracted into the `origin` field.        |

### Legacy aliases

For backward compatibility, the ingestion pipeline also accepts the non-`_json` forms below. New instrumentation SHOULD prefer the `_json` variants documented above.

| Attribute            | Type   | Equivalent to             |
| -------------------- | ------ | ------------------------- |
| `braintrust.input`   | string | `braintrust.input_json`   |
| `braintrust.output`  | string | `braintrust.output_json`  |
| `braintrust.expected`| string | `braintrust.expected_json`|

---

## TODO

The following areas still need to be specified:

- **Embedding APIs** — instrumentation for embedding endpoints (e.g. OpenAI `embeddings.create`, Google `embedContent`), including input/output structure, token metrics, and multimodal embedding inputs (image embeddings, etc.)
- **Multimodal APIs** — instrumentation for non-chat multimodal endpoints (image generation, speech-to-text, text-to-speech, vision-only APIs, etc.), including input/output structure and relevant metrics
- **Realtime APIs** — instrumentation for realtime/WebSocket-based APIs (e.g. OpenAI Realtime API), including session lifecycle, event-driven span structure, and relevant metrics
- **Reranking APIs** — instrumentation for reranking endpoints (e.g. Cohere `rerank`, Jina Reranker), including input/output structure and relevance score metrics
