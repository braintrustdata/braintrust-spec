# Application logging

Braintrust SDKs should let applications send searchable, structured logs through
familiar logging APIs. A log captures an event at one point in time, with a body,
severity, optional metadata, and trace correlation when available.

This specification defines the behavior SDKs should provide across languages.
API signatures and integration mechanisms should fit the language and its
logging ecosystem. The Python and JavaScript PRs linked below are implementation
examples.

## Logging API

SDKs MUST expose severity methods on their project logger:

```text
logger.trace(body, ...)
logger.debug(body, ...)
logger.info(body, ...)
logger.warn(body, ...)
logger.error(body, ...)
logger.fatal(body, ...)
```

Each method MUST accept a message body and optional structured metadata. SDKs
MUST support strings and JSON-compatible structured bodies, preserving their
values instead of always converting them to text. They MUST provide a way to
supply message templates and parameters as described below.

Argument layout, return types, and synchronous or asynchronous behavior SHOULD
follow existing SDK conventions. An SDK MAY expose a generic emission method
that accepts an explicit severity. All entry points MUST use the same log
record contract.

Calling a logging method MUST NOT require creating or ending a span.
`logger.trace()` records a trace-level message; it does not start a trace.
Existing tracing APIs such as `logger.log(...)` retain their behavior.

## Emitting a log

Each call MUST produce one complete, independent Braintrust row with
`span_attributes.type: "log"`. All captured fields MUST be supplied in the
initial record. SDKs MUST NOT enqueue a start record followed by an end record,
completion update, or merge merely to emit a log. Repeated identical messages
are separate events and MUST receive different row IDs.

One record per event does not require one network request per event. Logs
SHOULD use the SDK's existing buffering and batching facilities. Explicit flush,
shutdown, synchronous export, and transport retries follow the SDK's normal
delivery behavior. Retrying delivery MUST preserve the original record's
identity and event time.

| Field | Required behavior |
| --- | --- |
| `id` | A fresh identifier for this log row. |
| `span_attributes.type` | `"log"`. |
| `span_attributes.log_level` | A canonical severity from the next section. |
| `output` | The structured body or rendered message. |
| `metadata` | Caller metadata and any captured template or logging-source fields. |
| `created` | The event time as an ISO 8601 timestamp. |
| `metrics.start`, `metrics.end` | The same event time, in Unix seconds. |
| `span_id`, `root_span_id` | Correlation IDs as described below. |
| `span_parents` | Empty or absent. |

A log has no operation duration. Its start and end timestamps MUST be equal.
Use the source event timestamp when forwarding an existing record, including a
valid timestamp of zero; otherwise capture the time of emission. Do not
substitute background processing or upload time. `span_attributes.name` SHOULD
be absent or null; the message belongs in `output`.

### Trace correlation

Every log MUST have its own row `id`. Its correlation IDs depend on the active
context:

| Context | `span_id` | `root_span_id` |
| --- | --- | --- |
| Active Braintrust or compatible OpenTelemetry span | Reuse the active span's ID. | Reuse the active span's trace ID. |
| No active span | Generate a fresh span ID. | Reuse a baseline trace ID unique to the logger instance. |

IDs MUST use the SDK's configured generator. Capture context when the log is
created, before asynchronous processing or thread handoff. Emitting a log MUST
leave the active span unchanged and MUST NOT create a child operation or merge
into the span's row. Logs go to the project logger used to emit them.

## Severity

The canonical levels, from least to most severe, are:

| Level | Intended use |
| --- | --- |
| `trace` | Detailed execution diagnostics. |
| `debug` | Information useful when debugging. |
| `info` | Normal application activity. |
| `warn` | A condition that may need attention. |
| `error` | An operation or action failed. |
| `fatal` | A critical failure affecting continued operation. |

SDKs MUST store the selected level in `span_attributes.log_level`. Severity
MUST NOT be inferred from message text or stored only in user metadata.
Caller metadata MUST NOT override the canonical level.

Integrations MUST map their source library's severities to these levels and
SHOULD document mappings for aliases, numeric levels, and custom levels. For
example, Python `WARNING` maps to `warn`, Python `CRITICAL` maps to `fatal`,
and JavaScript `console.log` maps to `info`.

Severity describes the log event. Calling `error()` or `fatal()` MUST NOT by
itself populate the row's top-level `error`, mark a correlated span as failed,
or terminate the application.

## Templates and parameters

SDKs MUST support structured messages that preserve a stable template and its
parameters alongside the rendered message. This lets users group similar logs
and query parameter values without parsing message text.

| Location | Content |
| --- | --- |
| `output` | The rendered message. |
| `metadata["braintrust.template"]` | The original template, including placeholders. |
| `metadata["braintrust.template.parameter.<key>"]` | Each interpolation value, keyed by name or zero-based position. |

These metadata keys are literal dotted keys, not nested objects. For example,
a named-parameter API could emit:

```json
{
  "span_attributes": { "type": "log", "log_level": "warn" },
  "output": "Retry 2 for job_123",
  "metadata": {
    "queue": "payments",
    "braintrust.template": "Retry {attempt} for {job_id}",
    "braintrust.template.parameter.attempt": 2,
    "braintrust.template.parameter.job_id": "job_123"
  }
}
```

The example shows message fields; identity and timing follow the record
contract above.

SDKs SHOULD use idiomatic formatting facilities, such as named format
arguments, positional arguments, tagged templates, or native interpolated
string objects. Native template strings SHOULD be supported where the language
exposes their template and values separately. A common template syntax across
languages is not required.

Implementations MUST:

- Preserve parameter values before message rendering, retaining JSON-compatible
  types. Unsupported values SHOULD use the SDK's safe serialization or a safe
  textual representation.
- Keep every interpolation value, including repeated expressions. Use
  positional or occurrence-specific keys when names alone cannot distinguish
  them.
- Merge generated template fields with caller metadata without mutating the
  caller's objects. Generated fields take precedence on a key collision.
- Leave ordinary strings unchanged. Do not infer a template or reconstruct
  parameters from text that has already been interpolated.
- Handle rendering failures without disrupting application execution. Preserve
  the template and captured parameters, and use the original message or retain
  unresolved placeholders when rendering cannot complete.

Rendering failures are distinct from invalid API arguments, which MAY follow
the SDK's normal validation behavior.

## Logging integrations

SDKs SHOULD integrate with built-in loggers and common logging libraries, such
as Python's `logging` and JavaScript's `console`, so applications can forward
existing log calls. Integrations MUST require explicit enablement through a
handler, sink, wrapper, or equivalent mechanism.

Forwarded logs MUST follow the same record, severity, template, and correlation
rules as direct calls. Integrations SHOULD preserve available source data:

- The formatted message, including supplied exception and stack information.
- The original template, parameters, and application-supplied structured fields.
- The event timestamp, logger name, and code location. Use `logger.name`,
  `code.file.path`, `code.function.name`, and `code.line.number` in metadata for
  the source logger and location.

Capture source data before queues or formatters discard it. Forward rendered
text when that is all the source provides; do not invent missing fields.
Captured console text MAY differ from its visual rendering when the runtime
cannot safely reproduce it.

Integrations MUST preserve the source logger's filters, formatting, outputs,
and call behavior. Capture failures MUST NOT interrupt the original call, and
capture SHOULD avoid running application formatting or serialization hooks
again.

Repeated installation or nested wrappers MUST NOT duplicate forwarding for the
same registration. Integrations MUST support detaching without disrupting other
handlers, wrappers, newer registrations, or queued logs. Cleanup SHOULD be
idempotent.

Integrations MUST exclude SDK diagnostics and export transport logs to prevent
recursion, including across asynchronous handoff, without suppressing unrelated
application logs from the same libraries. Forwarding MUST NOT deadlock flush or
shutdown.

## Implementation references

- [Python logging API and standard-library adapter (PR #759)](https://github.com/braintrustdata/braintrust-sdk-python/pull/759)
- [JavaScript logging API, templates, and console adapter (PR #2639)](https://github.com/braintrustdata/braintrust-sdk-javascript/pull/2639)

# SDK support

```yaml
id: application-logging
name: Application logging
category: Tracing
support:
  # Severity methods and structured bodies.
  severity-helpers:
    dotnet: "unknown"
    go: "yes"
    java: "unknown"
    js: "yes"
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
  # Single-record emission and scoped or unscoped trace correlation.
  log-record-emission:
    dotnet: "unknown"
    go: "yes"
    java: "unknown"
    js: "yes"
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
  # Template parameters and supported native template strings.
  message-templates:
    dotnet: "unknown"
    go: "yes"
    java: "unknown"
    js: "yes"
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
  # Built-in loggers and logging libraries, including console APIs.
  standard-logging-adapter:
    dotnet: "unknown"
    go: "yes"
    java: "unknown"
    js: "yes"
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
```
