# Distributed Tracing

This document specifies how Braintrust SDKs propagate trace context across
service and process boundaries, so that spans produced by separate services
are linked into a single trace.

## Scope

This document only concerns **how spans are linked into a trace across a
boundary** — i.e. how a downstream service learns which span/trace/project a
unit of work belongs to. It does NOT cover:

- How linked traces are rendered in the Braintrust UI.
- What happens when a service receives parent info referring to a trace or
  project it does not have access to. (This is a backend/UI concern and is
  out of scope here.)

## Propagation mechanism

Braintrust SDKs propagate trace context using the
[W3C Trace Context specification](https://www.w3.org/TR/trace-context/). W3C
carries trace identity (which trace and which parent span). Braintrust
additionally uses the [W3C Baggage](https://www.w3.org/TR/baggage/) header to
carry the **Braintrust parent** — the project or experiment the trace belongs
to.

Example headers:

```
traceparent: 00-f53d4cd03acedba3ca85a4605ca4bdce-baeeec9367deae51-03
baggage: braintrust.parent=project_id:12345
```

- `traceparent` encodes the trace id and parent span id (plus the W3C version
  and flags).
- `baggage` carries `braintrust.parent`, which tells the receiver which
  Braintrust container (project, experiment, etc.) the trace belongs to.

This is the propagation mechanism for **all** Braintrust SDKs, both the
OpenTelemetry-based SDKs (Java, Go, .NET, and the `braintrust[otel]` /
`@braintrust/otel` integrations) and the native SDKs (Python and TypeScript).

## Wire format

### Headers

A conforming SDK MUST propagate trace context using the following headers.

| Header        | Spec                                                      | Required on send                        | Carries                                          |
| ------------- | --------------------------------------------------------- | --------------------------------------- | ------------------------------------------------ |
| `traceparent` | [W3C Trace Context](https://www.w3.org/TR/trace-context/) | MUST                                    | trace id, parent span id, version, flags         |
| `baggage`     | [W3C Baggage](https://www.w3.org/TR/baggage/)             | MUST when a Braintrust parent is known  | `braintrust.parent=<parent>` plus any user baggage |
| `tracestate`  | [W3C Trace Context](https://www.w3.org/TR/trace-context/) | MAY                                     | vendor extensions (passed through if present)    |

### `traceparent`

The `traceparent` header MUST follow the W3C format
`version-trace_id-parent_id-flags`, e.g.:

```
traceparent: 00-f53d4cd03acedba3ca85a4605ca4bdce-baeeec9367deae51-03
```

The 16-byte `trace_id` identifies the trace (it is the analogue of Braintrust's
`root_span_id`); the 8-byte `parent_id` identifies the specific parent span.

### `baggage` and `braintrust.parent`

W3C `traceparent` carries trace identity but **not** the Braintrust container
the trace belongs to. The SDK MUST therefore also propagate the Braintrust
parent in the `baggage` header under the key `braintrust.parent`:

```
baggage: braintrust.parent=project_id:12345
```

The `braintrust.parent` value identifies a Braintrust container:
`project_id:<id>`, `project_name:<name>`, or `experiment_id:<id>`. This is the
same value carried by the `braintrust.parent` span attribute documented in the
[instrumentation guide](../instrumentation-guide.md#routing-and-context). (The
exported span slug used by the deprecated slug-passing path is a separate
mechanism and is not a valid `braintrust.parent` baggage value.)

The `braintrust.parent` baggage entry is REQUIRED whenever the sender knows its
Braintrust parent. Without it, a receiver can resolve trace identity from
`traceparent` but cannot determine which project/experiment to log under.

Implementations MUST preserve any non-Braintrust baggage entries already
present (baggage is a shared, multi-tenant header). Only the
`braintrust.parent` key is owned by the SDK.

## Send behavior

When an SDK forwards a request as part of an active span, it MUST inject the
propagation headers into the outbound carrier (HTTP headers, message-queue
metadata, gRPC metadata, etc.):

1. Inject `traceparent` (and `tracestate` if present) from the current span's
   context, per W3C.
2. Inject `baggage` with a `braintrust.parent` entry set to the SDK's current
   Braintrust parent, merged with any existing baggage.

Injected header names MUST be lowercase (`traceparent`, `baggage`,
`tracestate`), per W3C (§3.2.1 / §3.3.1). If the outbound carrier already
contains a case-variant of one of these headers (e.g. a title-cased `Baggage`
added by a framework), the SDK MUST overwrite it in place of emitting a second,
conflicting case-variant, so the carrier ends up with a single lowercase key.

Exception: native SDKs (Python and TypeScript) configured with the legacy UUID
ID format cannot produce W3C-shaped ids. For such spans, `inject` is a no-op —
neither `traceparent` nor `baggage` is written, and any pre-existing carrier
entries are left untouched. See
[Native SDK ID format and back-compat](#native-sdk-id-format-and-back-compat).

## Receive behavior

When an SDK begins a span in response to an inbound request, it MUST attempt to
resolve a parent from the incoming carrier:

1. **W3C context** — extract `traceparent` (and `tracestate`) to establish
   trace identity, and read `braintrust.parent` from `baggage` to establish the
   Braintrust container. A span started under this context MUST share the
   incoming trace id and be parented to the incoming span. If `traceparent` is
   valid but no `braintrust.parent` baggage entry is present, the SDK MUST still
   adopt the incoming trace identity and route under the currently-active
   logger/experiment.
2. **No parent** — if no valid `traceparent` is present, start a fresh root
   span.

Header lookups MUST be case-insensitive. (Some HTTP frameworks normalize header
names to title case, e.g. `Traceparent`, while the W3C propagators look up
lowercase keys. Implementations that delegate to a strict propagator MUST
lowercase incoming header names first.)

Native SDKs do not read inbound request objects themselves; the user supplies
the headers (see [Native SDK API](#native-sdk-api)).

## Native SDK API

The native SDKs (Python and TypeScript) expose a propagation API that mirrors
the OpenTelemetry vocabulary, so the concepts line up across paradigms:

| Concept                         | OpenTelemetry      | Braintrust native SDK                             |
|---------------------------------|--------------------|---------------------------------------------------|
| Write context into a carrier    | `inject(carrier)`  | `span.inject(carrier)` / `inject_trace_context()` |
| Read context from a carrier     | `extract(carrier)` | `extract_trace_context(headers)`                  |
| The headers/metadata being read | carrier            | carrier / headers                                 |

The terms **inject**, **extract**, and **carrier** are used exactly as in the
W3C/OTel propagation API. The native SDK never reads request objects directly:
the user pulls headers off their request and hands them to
`extract_trace_context`, just as they hand a carrier dict to `inject`.

`extract_trace_context(headers)` returns an **opaque propagation context** — a
value the caller passes straight to `start_span(parent=...)`. (Concretely, the
native SDKs return a dict carrying the relevant W3C headers; callers MUST treat
it as opaque.) `start_span(parent=...)` accepts either this opaque context or a
previously exported slug string.

```
# Send: write the current span's context into an outbound carrier.
carrier = span.inject(headers)        # or inject_trace_context(headers)

# Receive: read an inbound carrier and start a span under it.
ctx = extract_trace_context(request.headers)
with start_span(name="handler", parent=ctx) as span:
    ...
```

`span.inject` / `inject_trace_context` implement the
[Send behavior](#send-behavior); `extract_trace_context` + `start_span`
implement the [Receive behavior](#receive-behavior). Both interpret only the
W3C headers (`traceparent`, `baggage`, `tracestate`), case-insensitively. When
`extract_trace_context` finds no valid `traceparent` it returns the SDK's "no
parent" value, so `start_span` begins a fresh root.

`tracestate` is forwarded transparently: `start_span` captures any inbound
`tracestate` when it resolves an extracted context, every span in the trace
inherits it, and a later `inject` anywhere in the trace re-emits it unchanged.
Braintrust does not author or interpret `tracestate` entries of its own.

### Deprecated: passing the parent slug

Prior to adopting W3C Trace Context, the native SDKs propagated trace context by
serializing a span into a single opaque slug via `span.export()` and shipping it
across the boundary (conventionally in an `x-bt-parent` header, though the SDK
reads and writes no particular header — the user moves the slug across the
boundary themselves). The slug encodes the parent span id, root span id, and the
Braintrust parent in one self-describing token, and `start_span(parent=<slug>)`
still accepts it.

**This pattern is deprecated.** A single opaque slug cannot represent
multi-header W3C context and does not interoperate with OTel SDKs. New code
SHOULD use the `inject` / `extract` pattern above; `span.export()` /
`start_span(parent=<slug>)` remain only for backward compatibility. OTel SDKs
MUST NOT emit or honor the slug — linking a native service to an OTel service
requires the native SDK to speak W3C, not the slug.

## Test cases

SDK conformance tests SHOULD cover the following. Tests are organized by the
unit under test: header injection (send), header extraction (receive), and the
end-to-end round trip.

### Send: header injection

Given an active span with a known Braintrust parent, the SDK injects headers
into an outbound carrier. Assert:

- `traceparent` is present and well-formed: matches
  `^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$`, the trace id is non-zero, and
  the parent id is non-zero.
- The injected trace id equals the active span's trace id / `root_span_id`
  analogue, and the parent id equals the active span's span id.
- `baggage` is present and contains `braintrust.parent` set to the SDK's current
  parent (e.g. `project_id:<id>`).
- Pre-existing, non-Braintrust baggage entries on the outbound context are
  preserved (inject does not clobber unrelated baggage).
- Injected header names are lowercase. If the outbound carrier already carries a
  case-variant (e.g. a title-cased `Baggage`/`Traceparent`), the result has a
  single lowercase key, not two conflicting case-variants.

### Send: `braintrust.parent` value encoding

The `braintrust.parent` baggage value embeds an arbitrary, user-controlled
identifier (notably `project_name:<name>`, where the name may contain any
character). The SDK owns this member, so on inject it MUST percent-encode the
value to satisfy the W3C Baggage value grammar
([§3.3.1.3](https://www.w3.org/TR/baggage/#value)): the only bytes allowed
unencoded are `baggage-octet` (`%x21 / %x23-2B / %x2D-3A / %x3C-5B / %x5D-7E`);
everything else — including the percent sign, which MUST always be encoded — has
to be percent-encoded as UTF-8 octets. The SDK MAY over-encode (encoding a byte
that is technically legal unencoded is permitted), but it MUST NOT emit a value
byte outside `baggage-octet`. Assert:

- A `braintrust.parent` whose value contains characters outside `baggage-octet`
  (e.g. `"`, `\`, a comma, a semicolon, a space, a control character such as tab
  or newline, the percent sign, or non-ASCII such as `é` / an emoji) is injected
  with those characters percent-encoded. The emitted baggage member contains no
  raw `baggage-octet` violator and is pure ASCII on the wire.
- The encoding round-trips: extracting the produced `baggage` header yields the
  original `braintrust.parent` value byte-for-byte (e.g. a project named
  `Café` or `a,b c` is recovered exactly). Encode and decode MUST be inverses;
  in particular a literal `+` in the value MUST survive as `+` (the SDK uses
  `%20` for space, not the form-encoded `+`).
- Encoding is confined to the SDK-owned `braintrust.parent` member. Other
  vendors' inbound baggage members are relayed byte-for-byte (their existing
  percent-encoding is neither decoded nor re-encoded); e.g. `path=a%2Fb` is
  forwarded unchanged rather than rewritten to `path=a/b`.

### Receive: header extraction

Given an inbound carrier, the SDK starts a span and resolves its parent.
Assert one case per row:

| Inbound headers                                                    | Expected resolution                                                                                       |
|--------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| valid `traceparent` + `baggage: braintrust.parent=...`             | span shares the inbound trace id, is parented to the inbound span, and is routed to the baggage parent    |
| valid `traceparent`, no `braintrust.parent` baggage                | span shares the inbound trace id and parent; routing falls back to the active logger/experiment           |
| no propagation headers                                             | span is a fresh root (new trace id, no parent)                                                            |
| malformed `traceparent` (bad version, wrong length, zero ids)      | treated as absent → fresh root span                                                                       |
| header names in non-lowercase form (e.g. `Traceparent`, `Baggage`) | extracted correctly (case-insensitive lookup)                                                             |
| `baggage` with both `braintrust.parent` and unrelated keys         | `braintrust.parent` is consumed; unrelated keys are ignored, not errored                                  |
| valid `traceparent` + `tracestate`                                 | the inbound `tracestate` is captured and forwarded unchanged on any later `inject` within the trace        |

### Round trip

Inject from a parent span, then extract on a fresh context using the produced
headers. Assert the extracted context's trace id and parent span id match the
originating span, and the resolved Braintrust parent matches. This catches
inject/extract asymmetries (e.g. one side using a different baggage key or
encoding).

Also assert `tracestate` pass-through: given an inbound carrier with a
`tracestate` header, a span started from it (and its descendants) MUST forward
that same `tracestate` value when injecting onward; when no inbound `tracestate`
was present, none is emitted.

### Negative / robustness

- Injecting then exporting to Braintrust MUST NOT fail or drop the span if the
  Braintrust parent is unknown — propagation is best-effort and MUST NOT break
  span emission.
- An oversized or syntactically invalid `baggage` header MUST NOT throw; the SDK
  falls back to trace identity from `traceparent` (or a fresh root).

### Baggage size limits

The `baggage` header is untrusted, attacker-controllable input, and the W3C
Baggage spec ([§3.3.2](https://www.w3.org/TR/baggage/#limits)) bounds a
conforming `baggage-string` by **both**:

- **Condition 1** — at most **64** list-members.
- **Condition 2** — at most **8192** bytes total (a byte count, not a
  code-point count).

When the SDK parses an inbound `baggage` header or relays it onward, it MUST
bound the result to both limits, and when it cannot keep everything it MUST drop
whole list-members rather than truncate one mid-value (the spec states a
platform that cannot propagate all list-members "MUST NOT propagate any partial
list-members"). Assert:

- **Member-count cap (parse/relay).** A `baggage` header with more than 64
  list-members (each small, so the byte limit is not the binding constraint) is
  reduced to at most 64 members, keeping a leading prefix; no member is split.
  Boundary: exactly 64 members are all kept; 65 are reduced to 64.
- **Byte cap, whole members only.** A `baggage` header exceeding 8192 bytes is
  reduced to the leading whole members that fit; every kept member retains its
  full, intact value (nothing is cut mid-value), and the resulting header is
  ≤ 8192 bytes. A single member larger than the byte limit yields no complete
  member to keep and is dropped entirely (its partial value is never parsed or
  forwarded). Byte accounting MUST be UTF-8 byte-exact, so multi-byte members
  are bounded correctly.
- **`braintrust.parent` is prioritized on relay.** When the SDK merges its own
  `braintrust.parent` into an oversized inbound header, the SDK-owned member
  MUST survive: it reserves one of the 64 member slots and its byte cost first,
  then fills the remaining budget with relayed members in order. The emitted
  header stays within both limits with `braintrust.parent` present (e.g. 63
  relayed members + `braintrust.parent` = 64).
- **No throw.** Hitting either limit (including a single absurdly large member,
  or a header far over both limits) MUST NOT raise; trace identity from
  `traceparent` is unaffected.

### Native SDK ID format and back-compat

These cases apply only to the native SDKs (Python and TypeScript), which can
generate span ids in two formats: the default W3C/OTel-compatible **hex** ids
(16-byte trace id, distinct 8-byte span id) or legacy **UUID** ids (opt-in). The
ID format determines whether W3C propagation is possible and which span-export
serialization is used. See [Native SDK API](#native-sdk-api).

**ID format defaults and selection**

- By default (no configuration), spans use hex ids and `span.export()` produces
  the hex-compatible serialization.
- The legacy opt-out (e.g. `BRAINTRUST_LEGACY_IDS`) switches generation to
  UUID ids and the UUID serialization. The two move together: hex ids MUST
  serialize as the hex format and UUID ids as the UUID format, so a span is
  never exported in a serialization that cannot represent its ids.
- OTel-compat requires hex ids, so it takes precedence over the legacy UUID
  opt-out. If both are enabled, the SDK uses hex ids and logs a warning (at most
  once per process) noting that the legacy opt-out was ignored; it MUST NOT
  silently produce a contradictory configuration.

**Send (`inject`) by ID format**

| Active ID format | Expected `inject` behavior                                                            |
| ---------------- | ------------------------------------------------------------------------------------- |
| hex (default)    | injects a well-formed `traceparent` (and `braintrust.parent` baggage when known)      |
| legacy UUID      | no-op: ids are not W3C-shaped, so `traceparent`/`baggage` are NOT written; any pre-existing carrier entries are left untouched |

**Receive: parent slug (back-compat)**

`start_span(parent=<slug>)` accepts a serialized span slug (the deprecated
slug-passing path). For backwards compatibility, the slug's span/root ids are
always honored, regardless of whether they match the active ID format: a slug
exported by an older (UUID) sender links correctly when it reaches a newer (hex)
receiver, and vice versa. The child's own freshly generated span id stays in the
active format, so a trace can span both formats across a propagation boundary.

| Active ID format | Parent slug ids | Expected resolution                                                               |
|------------------|-----------------|-----------------------------------------------------------------------------------|
| hex (default)    | hex             | child links to the slug's span/root ids (shares trace, parented to the slug span) |
| hex (default)    | legacy UUID     | child links to the slug's UUID span/root ids; the child's own span id is hex      |
| legacy UUID      | legacy UUID     | child links to the slug's span/root ids                                           |
| legacy UUID      | hex             | child links to the slug's hex span/root ids; the child's own span id is UUID      |

This cross-format allowance is specific to the deprecated slug-passing path. The
W3C context path (`extract_trace_context`) carries only hex ids by construction
(`traceparent` is hex-only), so it never produces a mixed-format link.

**Back-compat round trip**

- `span.export()` followed by `start_span(parent=<slug>)` MUST round-trip
  correctly under the default hex ids (8-byte span id, 16-byte trace id): the
  child shares the parent's trace id and is parented to the parent's span id.
