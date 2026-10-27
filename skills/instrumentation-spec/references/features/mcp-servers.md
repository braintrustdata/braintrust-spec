# MCP server instrumentation

This spec defines Braintrust instrumentation for Model Context Protocol (MCP) server libraries.
It applies across languages, server abstractions, and transports.
The integration API and the mechanism used to observe incoming requests and outgoing responses are implementation-specific.

## Scope

Instrument server-side processing of incoming MCP requests, including:

- `tools/call`: execute a tool.
- `prompts/get`: retrieve a rendered prompt.
- `resources/read`: read resource contents.

Discovery, initialization, ping, subscription requests, and custom request methods are also eligible where supported by the protocol version and server library.
Notifications and responses to server-initiated requests MUST NOT create independent MCP request spans.
Notifications MAY update an existing request span, for example when a request is cancelled.
Client-side MCP instrumentation is outside the scope of this spec.
The [auto-instrumentation eligibility rules](../instrumentation-guide.md#auto-instrumentation-eligibility) still apply: task submission and separate polling or retrieval lifecycles MUST NOT be auto-instrumented.
For subscriptions, capture only the request and its response; do not keep a span open for subsequent notifications or the subscription lifetime.

## Span model

Each eligible incoming request MUST produce exactly one span.
Start the span when the transport delivers the parsed request, before validation, dispatch, or handler execution.
End it when sending the corresponding result or error response completes or fails, including asynchronous sends.
This captures validation and dispatch failures even when no handler runs, and includes response serialization and sending in the request duration.
Cancellation and connection closure can end a request without a response, as specified below.
The exact transport hooks are implementation-specific; observing only the handler lifetime does not cover the full request lifecycle.

Correlate responses with pending requests using both the connection and the protocol request ID, preserving the distinction between string and numeric IDs.
Instrumenting multiple layers of a server library or enabling instrumentation more than once MUST NOT produce duplicate spans for the same request.
Separate requests MUST have distinct spans, even when an ID is reused after completion or on another connection.
End each span at most once and release its pending correlation state on every terminal path.

| MCP method | `span_attributes.type` | `span_attributes.name` | `input` |
| --- | --- | --- | --- |
| `tools/call` | `tool` | Requested tool name; `tools/call` if unavailable | Tool arguments |
| `prompts/get` | `function` | `prompts/get` | Prompt arguments |
| `resources/read` | `function` | `resources/read` | `{ "uri": <requested URI> }` |
| Other eligible request methods | `function` | The MCP method | Omitted unless an explicit capture contract permits it |

Capture arguments as structured values rather than JSON-encoded strings.
If arguments are absent, omit `input`; do not invent arguments.
Prompt names and resource URIs belong in metadata, not in span names.
Do not capture the full request envelope, transport headers, or authentication context as input or metadata.
Translate allowlisted protocol `_meta` fields as specified below; do not copy the raw `_meta` object.

The request span MUST use valid incoming trace context when available, otherwise the active parent context when one exists, and otherwise start a new trace.
It MUST be active during request processing, including validation, dispatch, and handler execution, so nested LLM calls, tool calls, and manual spans become its children.
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
| `mcp.cancelled` | MUST for observed request cancellation | Boolean `true`; omitted otherwise. |

When the transport has no session ID, an integration MAY generate a stable opaque identifier per connection.
Such an identifier MUST be reused for requests on that connection and MUST NOT be shared across independent connections.
If neither a session nor a connection can be identified reliably, omit `mcp.session_id`.
Do not synthesize request IDs or infer model tool-call IDs from MCP request IDs.

The [data capturing policy](../instrumentation-guide.md#data-capturing-policy) applies to additional metadata.
Do not copy arbitrary handler context or protocol metadata into the span.
Span-origin provenance identifies the Braintrust integration using the normal [context fields](../instrumentation-guide.md#context).

### Protocol `_meta` allowlist

Integrations MUST translate the following well-known fields when present with the expected types.
The mappings apply to request `params._meta` and response `result._meta` in the directions specified below.

| Source | Translation |
| --- | --- |
| Request `io.modelcontextprotocol/protocolVersion` string | `metadata["mcp.protocol_version"]` |
| Request `io.modelcontextprotocol/clientInfo` object | String `name`, `title`, and `version` fields become `metadata["mcp.client.name"]`, `metadata["mcp.client.title"]`, and `metadata["mcp.client.version"]`. |
| Response `io.modelcontextprotocol/serverInfo` object | String `name`, `title`, and `version` fields become `metadata["mcp.server.name"]`, `metadata["mcp.server.title"]`, and `metadata["mcp.server.version"]`. |
| Request `traceparent`, `tracestate`, and `baggage` strings | Extract distributed trace context before starting the request span, following [Distributed tracing](distributed-tracing.md). |

Trace propagation fields establish trace identity, parentage, and Braintrust routing; they MUST NOT be copied into span metadata or payloads.
Invalid propagation values follow the distributed tracing validation rules and MUST NOT prevent request processing.
Response metadata MUST NOT change the request span's parent after it has started.
Client and server identity fields are self-reported descriptive metadata, not authentication or authorization signals.

The `io.modelcontextprotocol/` prefix is not a wildcard allowlist.
Other keys, including capabilities, log levels, progress tokens, and extension fields, MUST be omitted unless an integration explicitly allowlists them with a defined translation under the data capturing policy.
Omit missing or incorrectly typed fields rather than stringifying objects or copying unrecognized properties.

## Output

Capture the MCP result object as `output`, without the JSON-RPC response envelope:

- Tool calls preserve `content`, `structuredContent`, and `isError` when present.
- Prompt retrievals preserve `messages` and `description` when present.
- Resource reads preserve `contents` when present.

For other request methods, omit `input` and `output` unless an explicit integration capture contract allows particular fields.
Their spans still record timing, method, correlation, allowlisted metadata, and outcome.
For example, discovery instrumentation MUST NOT copy entire tool schemas or resource inventories by default.

Preserve MCP content structures and ordering, including message roles, text, resource links, embedded resources, URIs, and MIME types.
Do not convert prompt messages to a provider-specific chat format or flatten tool content into a single string.
Extract allowlisted result metadata before omitting protocol `_meta` fields from captured results and protocol content objects.
Application-defined keys inside tool arguments or `structuredContent` remain application data, not protocol metadata.

Inline media follows [Attachments](attachments.md), including its configuration and failure behavior.
Replace media at its original location, such as an image or audio content block's `data` field or a resource's `blob` field, and preserve surrounding content.
This applies to nested content in tool results, prompt messages, and resource contents.
Resource links and remote URLs MUST NOT be fetched solely for instrumentation.
Sanitize protocol metadata before attachment processing so attachment fallback cannot restore omitted `_meta` fields.

All capture and transformation MUST operate on telemetry data without changing the arguments, result, or error seen by the application.
Instrumentation failures MUST NOT prevent or retry handler execution, change its outcome, or interfere with cancellation.

## Errors

A thrown exception, failed asynchronous result, or outgoing JSON-RPC error response MUST populate the span's top-level `error` field, except for cancellation as specified below.
For a JSON-RPC error response, capture its code and message without copying arbitrary error `data`.
This includes failures before the handler runs, such as invalid parameters or an unknown method.
If an error response will be sent, keep the span open through the send; if processing terminates without a response, end the span at that point.
A response-send failure or connection closure MUST end affected pending spans with an error unless they have already ended through cancellation.
Propagate the original failure unchanged.
Do not fabricate an `output` when no result was returned.

A tool result with `isError: true` MUST also populate `error`, even when the handler returns normally.
Use the result's text content as the error message when available; otherwise use a descriptive fallback such as `Tool returned an error result`.
Keep the captured result in `output`, including `isError` and any partial content.
Do not throw an exception merely because a tool returned an error result.

### Cancellation

When the server observes that a pending request is cancelled, set `metadata["mcp.cancelled"] = true` and end the span when request processing terminates, even if no response is sent.
Use an explicit cancellation signal from the protocol or runtime, not a substring match on an exception message.
A cancellation notification must be correlated to a pending request on the same connection; it does not create a separate span.
Receiving a cancellation request does not prove that the server honored it: ignored, unknown, or already-completed cancellations MUST NOT mark a successful request as cancelled or create a new span.

Cancellation alone MUST NOT populate `error`, including when the runtime represents it as an exception or a protocol error response.
Preserve an independently observed failure if one occurred before cancellation.
Do not fabricate an output or capture the notification's free-form cancellation reason.
Late responses or duplicate cancellation signals MUST NOT end the span again or overwrite its terminal outcome.
Instrumentation MUST preserve the server library's cancellation behavior.

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

- Tool calls, prompt retrievals, and resource reads produce the specified span type, name, input, output, and metadata.
- Discovery, initialization, ping, subscription, and custom requests produce method-named `function` spans without unallowlisted payloads; notifications produce no independent spans.
- Request timing includes validation, dispatch, and asynchronous response sending, including failures before handler execution and during sending.
- Missing arguments and optional identifiers remain absent; numeric request ID `0` is preserved.
- Nested work uses the request span as its parent, including across asynchronous boundaries and concurrent requests.
- Repeated instrumentation produces no duplicates, while separate requests produce distinct spans, including reused IDs and equal IDs on different connections.
- Thrown failures and returned tool error results both populate `error` without changing application behavior.
- Cancellation sets `mcp.cancelled` without an error for cancellation alone; ignored or late cancellations do not change completed outcomes.
- Cancellation, connection closure, and response races end affected spans at most once and release pending state.
- Allowlisted protocol `_meta` fields are translated while unknown keys and raw `_meta` are omitted; structured application data and content order are preserved.
- Valid incoming `_meta` trace context establishes parentage and routing; invalid context does not break processing, and response context does not reparent the span.
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
  transport-request-lifecycle:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  protocol-request-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  cancellation-metadata:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  protocol-metadata-translation:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
```
