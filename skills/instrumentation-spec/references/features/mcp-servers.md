# MCP server instrumentation

This spec defines Braintrust instrumentation for Model Context Protocol (MCP) server libraries.
It applies across languages, server abstractions, and transports.
The integration API and the mechanism used to observe incoming requests, outgoing responses, and notifications are implementation-specific.
Span naming, kinds, attributes, and error classification follow the [OpenTelemetry MCP server semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/mcp.md#server).
Context propagation follows the accompanying [MCP context propagation conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/mcp.md#context-propagation).
These conventions are currently in development.
This document defines their mapping to Braintrust rows and the Braintrust-specific payload, provenance, and cancellation fields.

## Scope

Instrument server-side processing of incoming MCP requests, including:

- `tools/call`: execute a tool.
- `prompts/get`: retrieve a rendered prompt.
- `resources/read`: read resource contents.

Discovery, initialization, ping, subscription requests, and custom request methods are also eligible where supported by the protocol version and server library.
Incoming notifications also produce spans for their processing, without a request ID or an expected JSON-RPC response.
A notification MAY additionally update an existing request span, for example when a request is cancelled.
Outgoing notifications produce their own spans; when the server library associates one with a request, the notification span SHOULD be a child of that request span.
Responses to server-initiated requests MUST NOT create new operation spans.
Client-side MCP instrumentation is outside the scope of this spec.
The [auto-instrumentation eligibility rules](../instrumentation-guide.md#auto-instrumentation-eligibility) still apply: task submission and separate polling or retrieval lifecycles MUST NOT be auto-instrumented.
For subscriptions, capture only the request and its response; do not keep a span open for subsequent notifications or the subscription lifetime.

## Span model

Each eligible incoming request MUST produce exactly one span.
Each eligible incoming notification MUST likewise produce exactly one span.
OTel integrations SHOULD use span kind `SERVER`; this is distinct from Braintrust's `span_attributes.type`.
Start the span when the transport delivers the parsed request, before validation, dispatch, or handler execution.
End it when sending the corresponding result or error response completes or fails, including asynchronous sends.
For notifications, start at receipt and end when processing and any transport acknowledgement complete; do not wait for a JSON-RPC response.
This captures validation and dispatch failures even when no handler runs, and includes response serialization and sending in the request duration.
Cancellation and connection closure can end a request without a response, as specified below.
The exact transport hooks are implementation-specific; observing only the handler lifetime does not cover the full request lifecycle.

Correlate responses with pending requests using both the connection and the protocol request ID, preserving the distinction between string and numeric IDs.
Instrumenting multiple layers of a server library or enabling instrumentation more than once MUST NOT produce duplicate spans for the same request.
Separate requests MUST have distinct spans, even when an ID is reused after completion or on another connection.
End each span at most once and release its pending correlation state on every terminal path.

| MCP method | `span_attributes.type` | `span_attributes.name` | `input` |
| --- | --- | --- | --- |
| `tools/call` | `tool` | `tools/call <tool name>`; `tools/call` if unavailable | Tool arguments |
| `prompts/get` | `function` | `prompts/get <prompt name>`; `prompts/get` if unavailable | Prompt arguments |
| `resources/read` | `function` | `resources/read` | `{ "uri": <requested URI> }` |
| Other eligible request methods | `function` | The MCP method | Omitted unless an explicit capture contract permits it |
| Notifications | `function` | The MCP method | Sanitized notification parameters when the integration's capture setting permits them |

Names follow `<method> <target>` when a low-cardinality tool or prompt name is available, and `<method>` otherwise.
Resource URIs MUST NOT appear in span names by default; integrations MAY offer an explicit opt-in to include them.
The `input` column describes the payload when content capture is enabled, as specified below.
Capture arguments as structured values rather than JSON-encoded strings.
If arguments are absent, omit `input`; do not invent arguments.
Do not capture the full request envelope, transport headers, or authentication context as input or metadata.
Translate allowlisted protocol `_meta` fields as specified below; do not copy the raw `_meta` object.

By default, the operation span MUST use valid trace context extracted from MCP `params._meta` as its remote parent, or start a new trace if none is available.
An implementation MAY offer an explicit option to use or link ambient transport context, such as an HTTP server span.
Without that option, transport context MUST NOT become the operation span's parent: one HTTP stream can carry multiple MCP operations, and a single MCP operation can span multiple HTTP requests.
Apply the same extraction rules to notifications.
The operation span MUST be active during processing, including validation, dispatch, and handler execution, so nested LLM calls, tool calls, and manual spans become its children.
Concurrent requests MUST keep independent active contexts.
Cross-process parenting follows [Distributed tracing](distributed-tracing.md); session and request IDs are correlation metadata and MUST NOT be used as trace or parent span IDs.
Do not create an extra span spanning the server or session lifetime.

Record `metrics.start` and `metrics.end` using the normal timing conventions.
MCP request spans MUST NOT invent model, provider, token usage, or cost fields.
LLM calls made by a handler record those fields on their own spans under the existing LLM instrumentation rules.

## Metadata

Use the standard semantic-convention keys as flat keys within Braintrust `metadata` and as attributes on OTel spans.

| Field | Requirement | Value |
| --- | --- | --- |
| `mcp.method.name` | MUST | The request or notification method. |
| `mcp.session.id` | SHOULD when available | The actual MCP session identifier. |
| `jsonrpc.request.id` | MUST when available | String representation of a non-null request ID, including `"0"` for numeric `0`; omit for notifications. |
| `gen_ai.tool.name` | MUST when applicable | The tool name. |
| `gen_ai.prompt.name` | MUST when applicable | The prompt name. |
| `gen_ai.operation.name` | SHOULD for tool calls | `execute_tool`; omit for other operations. |
| `mcp.resource.uri` | MUST when applicable | The resource URI for reads, subscriptions, unsubscriptions, or resource-update notifications. |
| `mcp.protocol.version` | SHOULD when known | The MCP version used by the operation, from request metadata or negotiated protocol state. |
| `jsonrpc.protocol.version` | SHOULD when not `2.0` | The JSON-RPC version, distinct from the MCP version. |
| `rpc.response.status_code` | MUST on JSON-RPC error responses | String representation of the response's error code. |
| `error.type` | MUST if and only if the operation fails | Low-cardinality error classification, as specified below. |
| `network.transport` | SHOULD when known | Underlying transport, such as `pipe` for stdio or `tcp` / `quic` for HTTP. |
| `network.protocol.name` | SHOULD when applicable | Lowercase application protocol, such as `http` or `websocket`. |
| `network.protocol.version` | SHOULD when applicable | Actual application protocol version, such as `1.1` or `2` for HTTP. |
| `client.address` | SHOULD when available | Client address exposed by the transport; do not perform reverse DNS lookups to obtain it. |
| `client.port` | SHOULD when available with `client.address` | Numeric client port. |
| `mcp.cancelled` | MUST for observed request cancellation | Boolean `true`; omitted otherwise. |

Omit `mcp.session.id` when the operation is not part of an MCP session; do not substitute a generated connection ID.
Internal response correlation MUST still preserve the original request ID type, even though `jsonrpc.request.id` is serialized as a string in telemetry.
Do not synthesize request IDs or infer `gen_ai.tool.call.id` from JSON-RPC request IDs.
`mcp.cancelled` and the `mcp.client.*` / `mcp.server.*` identity fields below are Braintrust extensions, not standard OTel MCP attributes.

The [data capturing policy](../instrumentation-guide.md#data-capturing-policy) applies to additional metadata.
Do not copy arbitrary handler context or protocol metadata into the span.
Span-origin provenance identifies the Braintrust integration using the normal [context fields](../instrumentation-guide.md#context).

### Protocol `_meta` allowlist

Integrations MUST translate the following well-known fields when present with the expected types.
The mappings apply to incoming request/notification `params._meta` and outgoing response `result._meta` in the directions specified below.

| Source | Translation |
| --- | --- |
| Request `io.modelcontextprotocol/protocolVersion` string | `metadata["mcp.protocol.version"]` |
| Request `io.modelcontextprotocol/clientInfo` object | String `name`, `title`, and `version` fields become `metadata["mcp.client.name"]`, `metadata["mcp.client.title"]`, and `metadata["mcp.client.version"]`. |
| Response `io.modelcontextprotocol/serverInfo` object | String `name`, `title`, and `version` fields become `metadata["mcp.server.name"]`, `metadata["mcp.server.title"]`, and `metadata["mcp.server.version"]`. |
| Request or notification `traceparent`, `tracestate`, and `baggage` strings | Extract distributed trace context before starting the operation span, following [Distributed tracing](distributed-tracing.md). |

Trace propagation fields establish trace identity, parentage, and Braintrust routing; they MUST NOT be copied into span metadata or payloads.
Invalid propagation values follow the distributed tracing validation rules and MUST NOT prevent request processing.
Response metadata MUST NOT change the request span's parent after it has started.
Client and server identity fields are self-reported descriptive metadata, not authentication or authorization signals.

The `io.modelcontextprotocol/` prefix is not a wildcard allowlist.
Other keys, including capabilities, log levels, progress tokens, and extension fields, MUST be omitted unless an integration explicitly allowlists them with a defined translation under the data capturing policy.
Omit missing or incorrectly typed fields rather than stringifying objects or copying unrecognized properties.

## Content capture

Content capture is implementation-specific. Integrations SHOULD document their default and provide a setting to disable capture.
When enabled, use the `input` shapes above and the `output` shapes below, with the existing attachment and span customization rules.
Disabling content capture leaves span identity, timing, allowlisted metadata, and error classification available.
For returned tool errors, do not extract content text into `error` when content capture is disabled; use a generic message instead.

Native Braintrust integrations use `input` and `output` as their content fields.
OTel integrations exporting to Braintrust use the corresponding `braintrust.input_json` and `braintrust.output_json` attributes described in the instrumentation guide.
When also emitting standard OTel content attributes, `gen_ai.tool.call.arguments` maps to tool input, `gen_ai.tool.call.result` to successful tool output, and `gen_ai.prompt.variable.<argument_name>` to individual prompt arguments serialized as strings.
These optional attributes MUST use the same capture setting and sanitized values; they MUST NOT bypass redaction or attachment handling.
Braintrust's structured payloads and capture of partial/error tool output are extensions to the OTel content conventions.

### Output

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

A failed operation MUST populate the span's top-level `error` field and `metadata["error.type"]`, except for cancellation as specified below.
OTel spans SHOULD set status `ERROR` for these failures and leave status `UNSET` for successful operations and non-error outcomes.
When a JSON-RPC error response is available, always record its code as a string in `rpc.response.status_code`, without copying arbitrary error `data`.

Follow OTel's server-side classification: `-32700` (parse error), `-32600` (invalid request), `-32601` (method not found), `-32602` (invalid params), and `-32002` (resource not found) are caller errors and SHOULD NOT mark the server span as failed.
For these responses, omit the top-level `error` and `error.type` and leave OTel status `UNSET`, unless an independent server failure occurred.
Observe such responses only when they can be correlated to an operation; do not invent a method or request ID for an unparseable message.
Other JSON-RPC error codes SHOULD mark the operation as failed, with `error.type` set to the code's string representation and the error/status description taken from the response message when available.
For exceptions, timeouts, or transport failures without a JSON-RPC error response, use a predictable error type such as the exception class or `timeout`, falling back to `_OTHER` if no classification is available.
Do not use exception messages or request-specific values as `error.type`.
Classify the final operation outcome rather than treating an internally caught validation exception as an independent server failure.
If an error response will be sent, keep the span open through the send; if processing terminates without a response, end the span at that point.
A response-send failure or connection closure MUST end affected pending spans with an error unless they have already ended through cancellation.
Propagate the original failure unchanged.
Do not fabricate an `output` when no result was returned.

A tool result with `isError: true` MUST populate `error` and set `error.type = "tool_error"`, even when the JSON-RPC call succeeds.
Do not invent a `rpc.response.status_code` for a successful JSON-RPC result.
Use the result's text content as the error message when content capture is enabled and text is available; otherwise use a descriptive fallback such as `Tool returned an error result`.
When content capture is enabled, keep the captured result in `output`, including `isError` and any partial content.
Do not throw an exception merely because a tool returned an error result.

### Cancellation

When the server observes that a pending request is cancelled, set `metadata["mcp.cancelled"] = true` and end the span when request processing terminates, even if no response is sent.
Use an explicit cancellation signal from the protocol or runtime, not a substring match on an exception message.
Correlate a cancellation notification only to a matching pending request on the same connection.
Its own notification-processing span does not replace or extend the target request span and MUST NOT inherit the target request's cancellation state.
Receiving a cancellation request does not prove that the server honored it: ignored, unknown, or already-completed cancellations MUST NOT mark a successful request as cancelled or create a new span for the target request.

Cancellation alone MUST NOT populate `error` or `error.type`, or set OTel status `ERROR`, including when the runtime represents it as an exception or a protocol error response.
Preserve an independently observed failure if one occurred before cancellation.
Do not fabricate an output or capture the notification's free-form cancellation reason.
Late responses or duplicate cancellation signals MUST NOT end the span again or overwrite its terminal outcome.
Instrumentation MUST preserve the server library's cancellation behavior.

## OTel metrics

Integrations with an OTel metrics pipeline SHOULD emit `mcp.server.operation.duration` as a histogram in seconds for the same lifetime as the server operation span.
Use the upstream recommended bucket boundaries: `[0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 30, 60, 120, 300]`.
Use `mcp.method.name` and applicable low-cardinality attributes from the upstream metric definition, including tool/prompt name, protocol/transport attributes, response status code, and error type, with the same error classification as the span.
Do not add request IDs, session IDs, client addresses, prompt argument values, or resource URIs to metric dimensions by default.
Where an actual MCP session lifecycle is observable, integrations SHOULD also emit `mcp.server.session.duration` according to the upstream metric definition; do not fabricate sessions or add session-lifetime spans.
These are OTel metric instruments, not new fields in a Braintrust row's `metrics` object, which continues to record `start` and `end`.

## Example

A successful tool request with content capture enabled produces a row with these fields, in addition to normal span identity, timing, and provenance:

```json
{
  "span_attributes": {
    "type": "tool",
    "name": "tools/call get_weather"
  },
  "input": { "city": "Vienna" },
  "output": {
    "content": [{ "type": "text", "text": "Sunny" }],
    "structuredContent": { "forecast": "sunny" }
  },
  "metadata": {
    "mcp.method.name": "tools/call",
    "gen_ai.tool.name": "get_weather",
    "gen_ai.operation.name": "execute_tool",
    "mcp.session.id": "session-1",
    "jsonrpc.request.id": "7",
    "network.transport": "tcp",
    "network.protocol.name": "http",
    "network.protocol.version": "2"
  }
}
```

## Conformance scenarios

SDK implementations SHOULD cover:

- Tool calls, prompt retrievals, and resource reads produce the specified span type, name, input, output, and metadata.
- Discovery, initialization, ping, subscription, and custom requests produce method-named `function` spans without unallowlisted payloads; notifications produce spans ending after processing/acknowledgement without waiting for a JSON-RPC response.
- OTel spans use kind `SERVER`; tool and prompt names follow `<method> <target>`, while resource URIs are absent from names by default.
- Request timing includes validation, dispatch, and asynchronous response sending, including failures before handler execution and during sending.
- Missing arguments and optional identifiers remain absent; numeric request ID `0` becomes `jsonrpc.request.id = "0"`, with original ID types retained for correlation.
- Nested work uses the request span as its parent, including across asynchronous boundaries and concurrent requests.
- Repeated instrumentation produces no duplicates, while separate requests produce distinct spans, including reused IDs and equal IDs on different connections.
- Server failures set `error`, `error.type`, and OTel status `ERROR`; returned tool errors use `tool_error` without a fabricated response status code.
- JSON-RPC caller errors, including unknown methods and invalid arguments, record `rpc.response.status_code` without marking the server span as failed; internal errors such as `-32603` do mark it as failed.
- Cancellation sets `mcp.cancelled` without an error or OTel error status for cancellation alone; ignored or late cancellations do not change completed outcomes, and notification-processing spans remain distinct.
- Cancellation, connection closure, and response races end affected spans at most once and release pending state.
- Allowlisted protocol `_meta` fields are translated while unknown keys and raw `_meta` are omitted; structured application data and content order are preserved.
- Valid incoming `_meta` trace context establishes parentage and routing; when it is absent or invalid, start a new trace by default, and response context does not reparent the span.
- Content capture follows the integration's documented setting; optional OTel content attributes obey the same capture and sanitization settings.
- Outgoing notifications produce function spans and may be children of associated request spans; incoming notification spans remain distinct from any cancelled request span.
- Inline and nested media follow attachment rules, including disabled capture and conversion failures, without mutating results or fetching resource links.
- Actual MCP session IDs are recorded when available; connection identifiers are not substituted for absent sessions.
- Transport attributes distinguish stdio (`pipe`) and HTTP (`tcp` or `quic`, with the actual HTTP version).
- OTel operation duration uses seconds and matches the span lifetime and error classification, without high-cardinality correlation IDs in metric dimensions.

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
  otel-semantic-conventions:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  notification-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  opt-in-content-capture:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  otel-server-metrics:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
```
