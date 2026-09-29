# Span Customizer Hooks

## Overview

A **span customizer** is a user-provided object whose hooks transform span data in the SDK. Customizers let applications redact sensitive values, add metadata, or adjust captured fields without modifying each provider or framework integration.

Customizers are registered programmatically as an ordered list. With no customizers configured, export behavior is unchanged. An omitted hook is a no-op.

This specification defines the `onSpanExport` hook. The shared contract is language-independent; the SDK-specific sections describe the APIs and behavior currently in review.

Additional hooks may be added in the future. SDKs SHOULD design customizers as extensible objects or interfaces with named hooks, rather than as a single export callback. New hooks SHOULD be optional or have default no-op implementations so existing customizers continue to work without implementing them.

## Export hook

Conceptually:

```text
onSpanExport(outgoingSpanData) -> outgoingSpanData
```

The hook runs on outgoing span data before transport serialization. It receives the SDK's export representation, not a live span. Changes affect the exported telemetry, not the application-visible provider response.

When configured, export hooks MUST apply to all spans reaching the SDK's Braintrust export path, regardless of whether they were created manually or by instrumentation. This includes root spans and child spans in both logger and experiment traces. SDKs MUST NOT restrict hooks based on a span's instrumentation provenance. Non-span records, such as dataset rows and feedback, are outside this hook's scope.

SDKs whose native span pipeline is separate from OpenTelemetry (JavaScript and Python) do not yet customize spans exported through their OpenTelemetry processors or exporters. Until they do, attempting to register a non-empty customizer list while OpenTelemetry compatibility mode is enabled MUST log one error and leave the existing registration unchanged, without throwing or interrupting setup. Enabling compatibility mode after registering customizers MUST likewise log one error and continue setup. These errors MUST be logged only at hookup time, not for each span or export. Clearing customizers MUST always be allowed without logging an error.

The exact datatype passed to and returned from the hook is an SDK design decision. SDKs SHOULD use the representation most idiomatic to their language and tracing stack; this specification does not require a shared cross-language datatype or an OpenTelemetry dependency. For example, JavaScript passes a plain object with no fixed field schema (`Record<string, unknown>`), while Java uses OpenTelemetry `SpanData`.

### Transformation contract

- A customizer MAY add, change, or remove fields supported by the SDK's export representation, for example to redact `input` or `output` or add application metadata.
- The hook MUST return the data to export: either the original value or a replacement. Returning nothing or `null` is not a supported way to drop a span.
- Customizers MUST preserve span identity and parent relationships. The concrete protected fields are described below.
- Returned data MUST remain valid for the SDK's serialization pipeline.
- Hooks run synchronously in registration order. Each hook receives the result of the preceding hook; the last result proceeds through export.
- Customizers SHOULD be fast and avoid blocking I/O because they execute in the export path. They MUST NOT assume they execute on the application thread that created the span.

The instrumentation guide's capture rules describe the data produced by instrumentation by default. Explicit user customizers MAY transform that data; integrations MUST NOT use customizers to bypass their default capture requirements.

Automatic attachment uploads MUST run after export customization, using only the customized data. Removing or redacting inline image, audio, or other attachment data in a hook MUST prevent its automatic upload. Integrations MAY convert inline media into SDK attachment objects when data is captured, before hooks run; hooks then receive those objects, and removing or replacing one MUST prevent its upload. Customizers that serialize or walk record values MUST tolerate attachment objects. If customization rejects an entire batch, no attachments from that batch may be uploaded, including attachments in spans whose hooks succeeded before the failure.

### Record lifecycle

An export hook is not necessarily called once per logical span. An SDK may export incremental records while a span is still active. Hooks MUST apply to every outgoing span record, including incremental records from manually created spans. Customizers MUST tolerate absent fields and MUST NOT assume that input, output, metrics, or errors are available together. Export retries MAY reuse an already-customized record without invoking the hooks again.

Removing a field removes it from the current outgoing record. It does not retract a value already exported in an earlier record. A redaction customizer must therefore handle every record containing the sensitive field.

### Hook failures

Export customization is **fail closed**. If a hook throws or returns an invalid value, the SDK MUST log an error, stop running subsequent customizers for the affected record, and prevent that record from being uploaded. It MUST NOT fall back to the original data or export partial mutations made before the failure. Error diagnostics MUST NOT include span payloads or exception messages or stacks, which may contain sensitive data.

There are no configurable error-handling policies. Customizer authors who want to recover from an error MUST handle it inside their hook and return a valid record.

For incremental exporters, failure drops the current outgoing record; it cannot retract records already uploaded. Subsequent records for the same logical span are evaluated independently. Incremental exporters MUST continue exporting unrelated records and MUST memoize dropped records so transport retries do not rerun failed hooks or log the same failure again. Exporters that operate on completed-span batches MAY reject the entire batch instead, as documented below for Java and Go.

## JavaScript

### API and registration

```typescript
export type SpanExportData = Record<string, unknown>;

export interface SpanCustomizer {
  onSpanExport?(data: SpanExportData): SpanExportData;
}
```

Register `spanCustomizers` with `configureInstrumentation` from `braintrust/instrumentation` before instrumentation is enabled. Importing the main SDK enables instrumentation during platform initialization, so configure in a bootstrap module before importing it or running an auto-instrumentation preload. Static imports are hoisted; use a dynamic import when configuration and initialization are in the same module.

```typescript
import { configureInstrumentation } from "braintrust/instrumentation";

configureInstrumentation({
  spanCustomizers: [
    {
      onSpanExport(data) {
        if ("input" in data) data.input = "[redacted]";
        if ("output" in data) data.output = "[redacted]";
        delete data.error;
        return data;
      },
    },
  ],
});

const { initLogger } = await import("braintrust");
initLogger({ projectName: "my-project" });
```

### Export behavior

- Hooks apply to **all spans**, whether created manually or by instrumentation, including their incremental records. Dataset rows and feedback are not customized.
- The hook runs after lazy values resolve and before attachment processing, record merging, masking, and JSON serialization. A record may be exported before the span ends.
- The record is mutable. A hook may mutate and return it or return a replacement object. Replacement is not an implicit merge: callers must retain the fields they want to export.
- Customizers MUST preserve identity and routing fields, including `id`, `span_id`, `root_span_id`, `span_parents`, and the project or experiment destination fields.
- Configuration is shared across SDK bundles in the same JavaScript global environment.
- Hooks apply to native SDK spans. Spans exported through `@braintrust/otel`'s `BraintrustSpanProcessor` or `BraintrustExporter` are not customized. Registering customizers while OTel compatibility mode is enabled (`BRAINTRUST_OTEL_COMPAT` or `setupOtelCompat()`) logs one error per attempt and leaves the existing registration unchanged. Calling `setupOtelCompat()` after customizers are registered logs one error and continues enabling compatibility mode.
- Export retries reuse the transformed record without invoking the hooks again.

### Hook failures

Thrown exceptions and invalid return values drop the current outgoing record and stop the remaining customizers for that record. The SDK logs an error without the exception message, stack, or span payload. Unrelated records continue through export; retries reuse the dropped result without rerunning its hooks.

Hooks must return a valid plain object, not a promise, `undefined`, `null`, or another invalid value. Accidental promises are rejected as hook results; rejected promises are consumed to avoid unhandled rejections. Customizer authors must catch errors inside their hook if they want to recover and still export the record.

## Python

### API and registration

```python
SpanExportData = dict[str, Any]

class SpanCustomizer:
    def on_span_export(self, data: SpanExportData) -> SpanExportData:
        return data
```

Register an ordered list with `braintrust.set_span_customizers(customizers)` or `auto_instrument(span_customizers=...)` before logging spans. Registration validates customizers eagerly and rejects classes, objects without a callable `on_span_export`, and async hooks. Passing `None` or an empty sequence disables customization. There is no environment-variable registration mechanism.

### Export behavior

Export behavior matches JavaScript: hooks apply to all native SDK spans and their incremental records, run after lazy values resolve and before attachment uploads, merging, masking, and serialization, and protocol fields are restored after each hook. Spans exported through `braintrust.otel`'s `BraintrustSpanProcessor` or `OtelExporter` are not customized. `set_span_customizers` logs one error per registration attempt and leaves the existing registration unchanged if given customizers while `BRAINTRUST_OTEL_COMPAT` is enabled; it does not raise or log again during span export.

### Hook failures

Failures are handled as in JavaScript. Hooks must return a `dict`; subclasses are accepted and copied into a plain `dict`. Any exception raised by a hook drops the record, except `KeyboardInterrupt` and `SystemExit`, which propagate.

## Go

### API and registration

`config.SpanCustomizer` is a struct of optional hook functions:

```go
type SpanCustomizer struct {
    OnSpanExport func(span trace.ReadOnlySpan) (trace.ReadOnlySpan, error)
}
```

Register customizers through the `SpanCustomizers` configuration field. Use keyed struct literals so future hooks can be added compatibly.

### Export behavior

- Hooks apply to all completed OTel spans reaching the Braintrust exporter, after span filtering and before automatic attachment processing, uploads, and serialization.
- Customizers MUST preserve trace, span, and parent IDs. Attributes, including `braintrust.parent` routing, may change.

### Hook failures

A returned error, a panic, a `nil` result, or changed IDs fail the entire export batch, as in Java. No spans or attachments from that batch are sent. Diagnostics identify the customizer and the kind of failure, but not the hook's error text.

## Java

### API and registration

`dev.braintrust.trace.SpanCustomizer` exposes:

```java
public interface SpanCustomizer {
    default SpanData onSpanExport(SpanData span) {
        return span;
    }
}
```

`SpanData` is `io.opentelemetry.sdk.trace.data.SpanData`. Register customizers with `BraintrustConfig.Builder.addSpanCustomizer(customizer)` before building the SDK configuration. Repeated calls append in execution order; the built configuration retains an immutable copy of the list. There is no environment-variable registration mechanism.

The hook returns the original `SpanData` or a replacement, typically an OpenTelemetry `DelegatingSpanData` overriding the fields to change. Unlike the JavaScript record, `SpanData` is not a mutable map. Braintrust content is represented through OTel attributes such as `braintrust.input_json` and `braintrust.output_json`.

### Export behavior

- Hooks apply to **all spans reaching the Braintrust exporter**, not only instrumentation-created spans.
- The hook receives completed OTel span data before grouping by Braintrust destination and before OTLP serialization.
- Customizers MUST preserve the trace ID, span ID, and parent span ID, including the corresponding values exposed through the span contexts. The exporter validates these after each hook.
- Destination grouping uses the customized span's `braintrust.parent` attribute, falling back to the configured destination. Unlike JavaScript's routing-preservation contract, the Java exporter permits destination changes.
- Customization completes for the entire export batch before attachment conversion/uploads or any destination group is sent.

### Hook failures

A thrown exception, a `null` result, or a changed protected ID fails the entire export batch. The exporter logs the failure, returns a failed export result, and sends none of that batch. It does not fall back to exporting the original spans.

This is **fail-closed** behavior at batch granularity. Customization runs on each call to the Braintrust exporter's `export` method; submitting a batch again invokes the hooks again.

## References

- [Java implementation under review](https://github.com/braintrustdata/braintrust-sdk-java/pull/177)
- [JavaScript implementation under review](https://github.com/braintrustdata/braintrust-sdk-javascript/pull/2489)

# SDK support

```yaml
id: span-customizers
name: Span customizer hooks
category: Tracing
support:
  export-hook:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  all-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "yes"
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
  ordered-customizers:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  field-transforms:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  customize-before-attachments:
    dotnet: "unknown"
    go: "yes"
    java: "unknown"
    js: "yes"
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
  identity-preservation:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  hook-failure-handling:
    dotnet: "unknown"
    go: "yes"
    java: "unknown"
    js: "yes"
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
```
