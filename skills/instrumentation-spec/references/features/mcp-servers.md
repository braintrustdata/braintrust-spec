# MCP server instrumentation

This spec defines Braintrust instrumentation for Model Context Protocol (MCP) server libraries.
It applies across languages, server abstractions, and transports.
The integration API and the mechanism used to observe request handlers are implementation-specific.

## Scope

Instrument server-side execution of these MCP methods:

- `tools/call`: execute a tool.
- `prompts/get`: retrieve a rendered prompt.
- `resources/read`: read resource contents.

MCP server instrumentation MUST NOT create spans for discovery, initialization, ping, notifications, subscriptions, or custom protocol methods.
Client-side MCP instrumentation is outside the scope of this spec.
The [auto-instrumentation eligibility rules](../instrumentation-guide.md#auto-instrumentation-eligibility) still apply: task submission and separate polling or retrieval lifecycles MUST NOT be auto-instrumented.

## Span model

Each eligible request handler invocation MUST produce exactly one span.
The span starts when handler execution begins and ends when the handler returns or fails, including asynchronous execution.
Instrumenting multiple layers of a server library or enabling instrumentation more than once MUST NOT produce duplicate spans for the same invocation.
Separate invocations MUST have distinct spans, even when their request IDs match.

| MCP method | `span_attributes.type` | `span_attributes.name` | `input` |
| --- | --- | --- | --- |
| `tools/call` | `tool` | Requested tool name; `tools/call` if unavailable | Tool arguments |
| `prompts/get` | `function` | `prompts/get` | Prompt arguments |
| `resources/read` | `function` | `resources/read` | `{ "uri": <requested URI> }` |

Capture arguments as structured values rather than JSON-encoded strings.
If arguments are absent, omit `input`; do not invent arguments.
Prompt names and resource URIs belong in metadata, not in span names.
Do not capture the full request envelope, transport headers, authentication context, or request `_meta` as input or metadata.

The request span MUST use the active parent context when one exists and otherwise start a new trace.
It MUST be active while the handler executes so nested LLM calls, tool calls, and manual spans become its children.
Concurrent requests MUST keep independent active contexts.
Cross-process parenting follows [Distributed tracing](distributed-tracing.md); session and request IDs are correlation metadata and MUST NOT be used as trace or parent span IDs.
Do not create an extra span spanning the server or session lifetime.

Record `metrics.start` and `metrics.end` using the normal timing conventions.
MCP request spans MUST NOT invent model, provider, token usage, or cost fields.
LLM calls made by a handler record those fields on their own spans under the existing LLM instrumentation rules.

## Metadata

Use these flat keys within `metadata`:

| Field | Requirement | Value |
| --- | --- | --- |
| `mcp.method` | MUST | The MCP method being handled. |
| `mcp.session_id` | SHOULD when available | The session identifier exposed by the server library or transport. |
| `mcp.request_id` | MUST when available | The protocol request ID, preserving its string or numeric type. |
| `mcp.prompt_name` | MUST for `prompts/get` when available | The requested prompt name. |
| `mcp.resource_uri` | MUST for `resources/read` when available | The requested resource URI. |

When the transport has no session ID, an integration MAY generate a stable opaque identifier per connection.
Such an identifier MUST be reused for requests on that connection and MUST NOT be shared across independent connections.
If neither a session nor a connection can be identified reliably, omit `mcp.session_id`.
Do not synthesize request IDs or infer model tool-call IDs from MCP request IDs.

The [data capturing policy](../instrumentation-guide.md#data-capturing-policy) applies to additional metadata.
Do not copy arbitrary handler context or protocol metadata into the span.
Span-origin provenance identifies the Braintrust integration using the normal [context fields](../instrumentation-guide.md#context).

## Output

Capture the MCP result object as `output`, without the JSON-RPC response envelope:

- Tool calls preserve `content`, `structuredContent`, and `isError` when present.
- Prompt retrievals preserve `messages` and `description` when present.
- Resource reads preserve `contents` when present.

Preserve MCP content structures and ordering, including message roles, text, resource links, embedded resources, URIs, and MIME types.
Do not convert prompt messages to a provider-specific chat format or flatten tool content into a single string.
Protocol `_meta` fields MUST be omitted from captured results and protocol content objects.
Application-defined keys inside tool arguments or `structuredContent` remain application data, not protocol metadata.

Inline media follows [Attachments](attachments.md), including its configuration and failure behavior.
Replace media at its original location, such as an image or audio content block's `data` field or a resource's `blob` field, and preserve surrounding content.
This applies to nested content in tool results, prompt messages, and resource contents.
Resource links and remote URLs MUST NOT be fetched solely for instrumentation.
Sanitize protocol metadata before attachment processing so attachment fallback cannot restore omitted `_meta` fields.

All capture and transformation MUST operate on telemetry data without changing the arguments, result, or error seen by the application.
Instrumentation failures MUST NOT prevent or retry handler execution, change its outcome, or interfere with cancellation.

## Errors

A thrown exception or failed asynchronous result MUST populate the span's top-level `error` field and end the span.
Propagate the original failure unchanged.
Do not fabricate an `output` when no result was returned.

A tool result with `isError: true` MUST also populate `error`, even when the handler returns normally.
Use the result's text content as the error message when available; otherwise use a descriptive fallback such as `Tool returned an error result`.
Keep the captured result in `output`, including `isError` and any partial content.
Do not throw an exception merely because a tool returned an error result.

## Example

A successful tool request produces a row with these fields, in addition to normal span identity, timing, and provenance:

```json
{
  "span_attributes": {
    "type": "tool",
    "name": "get_weather"
  },
  "input": { "city": "Vienna" },
  "output": {
    "content": [{ "type": "text", "text": "Sunny" }],
    "structuredContent": { "forecast": "sunny" }
  },
  "metadata": {
    "mcp.method": "tools/call",
    "mcp.session_id": "session-1",
    "mcp.request_id": 7
  }
}
```

## Conformance scenarios

SDK implementations SHOULD cover:

- All three methods produce the specified span type, name, input, output, and metadata.
- Discovery and lifecycle methods produce no MCP operation spans.
- Missing arguments and optional identifiers remain absent; numeric request ID `0` is preserved.
- Nested work uses the request span as its parent, including across asynchronous boundaries and concurrent requests.
- Repeated instrumentation produces no duplicates, while repeated invocations produce distinct spans.
- Thrown failures and returned tool error results both populate `error` without changing application behavior.
- Protocol `_meta` is omitted while structured application data and content order are preserved.
- Inline and nested media follow attachment rules, including disabled capture and conversion failures, without mutating results or fetching resource links.
- Session correlation remains stable within a connection and distinct across independent connections.

# SDK support

```yaml
id: mcp-servers
name: MCP server instrumentation
category: Tracing
support:
  tool-call-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  prompt-retrieval-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  resource-read-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  request-context-and-correlation:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  error-capture:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  result-capture:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
```
