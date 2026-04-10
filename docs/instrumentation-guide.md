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

### Input capture

The span MUST capture the full input messages sent to the model.

**Structure:** An ordered array of message objects. Each message MUST include:

- `role` — the message role (e.g. `user`, `assistant`, `system`)
- `content` — the message content (string or structured content array)

System messages MUST be included in the input array. For providers where the system message is a separate parameter (e.g. Anthropic's `system` field), the SDK MUST normalize it into the messages array with `role: "system"`.

**Example (OpenAI-style):**

```json
[
  { "role": "system", "content": "you are a helpful assistant" },
  { "role": "user", "content": "What is the capital of France?" }
]
```

**Example (Anthropic — normalized):**

```json
[
  { "role": "user", "content": "What is the capital of France?" },
  { "role": "system", "content": "You are a helpful assistant." }
]
```

**Example (Google):**

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

Note: Google input retains the provider-native structure (`contents` with `parts`) rather than normalizing to a flat messages array. The `model` field is included at the top level of the input object.

### Output capture

The span MUST capture the model's response.

**OpenAI:** An array of choice objects:

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

**Anthropic:** An object with `role` and `content` array:

```json
{
  "role": "assistant",
  "content": [{ "type": "text", "text": "The capital of France is Paris." }]
}
```

**Google:** A `candidates` array:

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

When the model responds with tool calls in a completion API, the output MUST include the tool call information. The SDK does NOT execute the tools — it only records what the model requested.

```json
[
  {
    "index": 0,
    "finish_reason": "tool_calls",
    "message": {
      "role": "assistant",
      "tool_calls": [
        {
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

The `finish_reason` MUST reflect the tool call (e.g. `"tool_calls"` for OpenAI).

Tool definitions provided in the request SHOULD be included as part of the request context, but are NOT required to appear in the `input` messages array.

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

### Provider notes

- **Anthropic**: Reports cached tokens via `usage.cache_read_input_tokens` and `usage.cache_creation_input_tokens`.
- **OpenAI**: Reports cached prompt tokens via `usage.prompt_tokens_details.cached_tokens`.

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

Braintrust-specific OTel span attributes used by the SDK instrumentation:

| Attribute            | Type   | Description                                                                                                                                                                                                                             |
| -------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `braintrust.parent`  | string | Serialized parent span context, used to link spans across service boundaries in distributed tracing. Contains the span ID and trace ID needed to re-parent a span under a remote trace.                                                 |
| `braintrust.metrics` | string | JSON-encoded metric annotations attached to the span. Used to pass SDK-computed metrics (e.g. `time_to_first_token`) through the OTel pipeline to the Braintrust exporter, which extracts them into the `metrics` field of the log row. |

---

## TODO

The following areas still need to be specified:

- **Embedding APIs** — instrumentation for embedding endpoints (e.g. OpenAI `embeddings.create`, Google `embedContent`), including input/output structure, token metrics, and multimodal embedding inputs (image embeddings, etc.)
- **Multimodal APIs** — instrumentation for non-chat multimodal endpoints (image generation, speech-to-text, text-to-speech, vision-only APIs, etc.), including input/output structure and relevant metrics
