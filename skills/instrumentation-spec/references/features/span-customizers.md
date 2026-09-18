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

The exact datatype passed to and returned from the hook is an SDK design decision. SDKs SHOULD use the representation most idiomatic to their language and tracing stack; this specification does not require a shared cross-language datatype or an OpenTelemetry dependency. For example, JavaScript passes a plain object with no fixed field schema (`Record<string, unknown>`), while Java uses OpenTelemetry `SpanData`.

### Transformation contract

- A customizer MAY add, change, or remove fields supported by the SDK's export representation, for example to redact `input` or `output` or add application metadata.
- The hook MUST return the data to export: either the original value or a replacement. Returning nothing or `null` is not a supported way to drop a span.
- Customizers MUST preserve span identity and parent relationships. The concrete protected fields are described below.
- Returned data MUST remain valid for the SDK's serialization pipeline.
- Hooks run synchronously in registration order. Each hook receives the result of the preceding hook; the last result proceeds through export.
- Customizers SHOULD be fast and avoid blocking I/O because they execute in the export path. They MUST NOT assume they execute on the application thread that created the span.

The instrumentation guide's capture rules describe the data produced by instrumentation by default. Explicit user customizers MAY transform that data; integrations MUST NOT use customizers to bypass their default capture requirements.

### Record lifecycle

An export hook is not necessarily called once per logical span. An SDK may export incremental records while a span is still active. Customizers MUST tolerate absent fields and MUST NOT assume that input, output, metrics, or errors are available together.

Removing a field removes it from the current outgoing record. It does not retract a value already exported in an earlier record. A redaction customizer must therefore handle every record containing the sensitive field.

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

- Hooks apply to **instrumentation-created spans**, including their incremental records. Ordinary manually created spans, dataset rows, and feedback are not customized.
- The hook runs after lazy values resolve and before attachment processing, record merging, masking, and JSON serialization. A record may be exported before the span ends.
- The record is mutable. A hook may mutate and return it or return a replacement object. Replacement is not an implicit merge: callers must retain the fields they want to export.
- Customizers MUST preserve identity and routing fields, including `id`, `span_id`, `root_span_id`, `span_parents`, and the project or experiment destination fields.
- Configuration is shared across SDK bundles in the same JavaScript global environment.
- Export retries reuse the transformed record without invoking the hooks again.

### Hook failures

Thrown exceptions are swallowed; subsequent customizers and export continue with the current record. In-place mutations made before an exception are not rolled back.

This is **fail-open** behavior. A redaction hook that throws can allow unredacted data to be exported; throwing MUST NOT be used to block export. Hooks must return a valid record, not a promise, `undefined`, or `null`.

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
- Customization completes for the entire export batch before any destination group is sent.

### Hook failures

A thrown exception, a `null` result, or a changed protected ID fails the entire export batch. The exporter logs the failure, returns a failed export result, and sends none of that batch. It does not fall back to exporting the original spans.

This is **fail-closed** behavior, unlike JavaScript. Customization runs on each call to the Braintrust exporter's `export` method; submitting a batch again invokes the hooks again.

## References

- [Java implementation under review](https://github.com/braintrustdata/braintrust-sdk-java/pull/177)
- [JavaScript implementation under review](https://github.com/braintrustdata/braintrust-sdk-javascript/pull/2489)
