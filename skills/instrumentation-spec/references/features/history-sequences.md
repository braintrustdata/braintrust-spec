# History sequences

**Status: draft proposal.** This document defines a proposed version 1 protocol,
not an available endpoint or a change to current SDK defaults. The endpoint names
below are proposed API contracts. Existing reporting continues to send full inputs
until both producer and receiver explicitly enable this protocol.

## Purpose and scope

An LLM span logically contains the complete ordered input sent to the model.
Repeatedly transmitting and storing that array is unnecessary when most elements
already occur in another input. Version 1 represents an immutable array as a
concatenation of literal elements and slices of previously defined arrays.

Only arrays have identities. Individual messages need neither IDs nor content
hashes. A reference identifies an immutable array and a half-open index range;
its meaning is independent of timestamps, arrival order, and span updates.

This protocol applies to SDKs, coding-agent translators, gateway reporting, and
the receiving service. It preserves the existing logical `input` and `output`
contracts. It does not normalize provider formats, infer missing messages, change
model requests, or reduce provider-reported token usage. The same encoding can
bind an explicitly identified array in either field. Version 1 does not encode
arbitrary JSON patches, streaming partial messages, or cross-trace references.

Normative terms MUST, SHOULD, and MAY apply to implementations opting into v1.

## Sequence values and identity

A sequence's value is a finite ordered JSON array. Every element is an opaque
JSON value: a message, multimodal content, reasoning part, or another native
value. Ordering, repeated occurrences, nested fields, and attachment references
MUST be preserved. Empty arrays are distinct from omitted fields and `null`.

A `sequence_id` is a randomly generated, nonzero, lowercase 32-hex-character
identifier (128 random bits). It MUST be allocated once and reused on retries.
The identity key is `(organization, object_type, object_id, root_span_id,
sequence_id)`. Organization is determined by authenticated routing; references
cannot grant access to another organization, container, or trace. Object IDs
MUST be resolved IDs, never mutable project names.

`object_type` is `project_logs` or `experiment`. Other destinations use full
payloads until a later protocol explicitly supports them. The `root_span_id`
remains the existing trace identifier, including supported legacy ID formats.
A native conversation/session ID MAY accompany ordinary span metadata but is
neither a sequence identity nor a prerequisite for this protocol. Sessions
spanning multiple traces require a new literal definition in each trace.

An ID denotes one immutable definition. Producers MUST NOT edit or repurpose it.
Retries of the same definition are allowed. Conflicting definitions for an
existing ID MUST fail with `sequence_conflict`, even if they happen to expand
to equal arrays. Servers MAY internally deduplicate equal values while retaining
these distinct public identities. Object member order is irrelevant when comparing
definitions; number tokens and string values MUST retain their accepted JSON
precision and meaning. This comparison MUST NOT round numbers through a less
precise numeric representation. No producer-side canonicalization or digest
algorithm is part of v1.

## Definition grammar and evaluation

A sequence definition has exactly `id`, `length`, and `parts`. Each part is
exactly one of these alternatives:

```text
Sequence = { id: SequenceId, length: Index, parts: Part[] }
Part     = { literal: JsonValue[] }
         | { slice: { id: SequenceId, start: Index, end: Index } }
Index    = integer in [0, 9007199254740991]
```

Each literal contributes its elements. Each slice contributes elements in
`source[start:end]`, with `0 <= start <= end <= source.length`. Concatenate the
parts in order. The result's element count MUST equal `length`; integer arithmetic
MUST be checked for overflow. An empty sequence is `{id, length: 0, parts: []}`.
Empty parts are valid but SHOULD be omitted. Unknown definition/part members,
malformed tags, missing fields, invalid IDs, and out-of-bounds slices are errors.

A snapshot is simply a definition containing literal parts only. An append is a
slice of an existing array followed by new literals. A compaction replaces some
slices with summary literals. Reordering or repeated slices are permitted; all
slice indexes address their named immutable source, never an intermediate result.
Definitions can reference multiple earlier sequences without creating message IDs.

Definitions form an acyclic graph. An ID MUST occur at most once in a request,
even if duplicate definitions would be equal. They MAY arrive in any order within
one request. Every dependency MUST already be retained by the receiver or be defined
in that request. A self-reference or cycle is invalid even if its slice is empty.
Only the final sequence needs a span binding; intermediate states MAY be reported
in the same request when needed by a dependency.

For example, let `a`, `b`, `c`, and `d` below be distinct valid sequence IDs:

```text
a = literal([system, user1])
b = slice(a, 0, 2) + literal([assistant1, user2])
c = literal([summary]) + slice(b, 2, 4) + literal([user3])
d = slice(a, 0, 2) + literal([alternate_user2])
```

`c` drops the first two elements, preserves the next two, and appends one new
message. `d` forks from `a`; it neither changes `b` nor depends on `c`. A repeated
message remains a separate occurrence at every position where it is included.

## Span bindings

A binding replaces one explicit empty-array placeholder in a reporting row:

```text
Binding = { field: "input" | "output", path: Segment[], id: SequenceId,
            reason?: "compaction" | "truncation" | "edit" }
Segment = string | Index
Row     = { event: ExistingSpanUpdate, bindings: Binding[] }
```

The `event` is an ordinary Braintrust span creation or merge update. It MUST
carry its ordinary row ID, span ID, and the request's `root_span_id`; routing
must match the enclosing scope. Existing validation and merge rules still apply.

`path: []` selects the field itself. A string segment selects an object member;
a numeric segment selects an array index. Numeric strings are object keys, not
array indexes. Every traversed member/index MUST exist and have the corresponding
container type. The selected value MUST be exactly `[]`. The receiver replaces
it with the complete sequence before applying the ordinary logical row update.
Bindings in one row MUST NOT select identical or overlapping paths.

Other fields and unbound arrays retain their ordinary values. Literal message
objects are opaque: an object resembling a reference inside a literal is data.
There are no special reference objects embedded in application payloads.

`reason` describes a change known by the producer, not a reconstruction rule.
It belongs to that binding and MUST be preserved in the compact trace view. It
MUST NOT be inferred merely because a different prefix was observed. Compaction
changes a later input, not older inputs or the retention of their underlying data.

An output can be bound to a sequence and reused explicitly in a subsequent input.
Producers MUST verify the actual next input: a prior output is not implicitly
appended, and tool spans, multiple candidates, redaction, or provider transformations
may make it different. Spans may update output during streaming; each newly
captured array has a new sequence ID, while old definitions remain immutable.
An update omitting a field retains its previous logical value under ordinary
merge rules. A later full value or binding updates that field under those same
rules; this protocol introduces no last-writer ordering guarantee beyond them.

## Network transport and negotiation

The proposed authenticated `GET /logs3/history/capabilities` returns:

```json
{
  "versions": [1],
  "max_request_bytes": 4194304,
  "max_definitions": 4096,
  "max_parts_per_definition": 1024,
  "max_sequence_length": 1000000,
  "max_expanded_bytes_per_sequence": 67108864,
  "max_request_expanded_bytes": 134217728,
  "max_dependency_depth": 256,
  "max_retry_seconds": 604800
}
```

These numbers are an illustrative deployment profile, not universal defaults.
Every v1 receiver MUST publish finite positive limits for all listed dimensions.
Expanded byte sizes are the UTF-8 sizes of a lossless JSON serialization without
insignificant whitespace, measured over the full logical array. The request
expansion budget counts each newly defined sequence once, including intermediates;
servers MUST enforce it before allocating expanded arrays. Receivers may reject
excess work conservatively rather than exhaust memory to calculate an exact size.
Control envelopes MUST reject duplicate object keys; opaque payload values follow
the existing JSON ingestion contract.
The depth limit counts dependency edges among newly defined, unresolved states
in this request; an already accepted indexed root is a terminal dependency. It
MUST NOT count the historical wire ancestry of an accepted state. Thus ordinary
appends can continue indefinitely without a depth-triggered full-history resend.
Receivers MUST bound aggregate validation/expansion work as well as individual
sequences; shared dependencies MUST be memoized, not recursively expanded per
reference. Advertised limits cannot imply that the service accepts exponential
logical expansion without bounds. Unknown versions, unsupported endpoints, or
failed negotiation mean the producer uses ordinary full-payload reporting.
Negotiation and delivery MUST NOT delay an instrumented application's model call
or a coding-agent capture acknowledgement.

The proposed `POST /logs3/history` accepts exactly this envelope shape:

```json
{
  "version": 1,
  "request_id": "10000000000000000000000000000001",
  "expires_at": "2026-11-12T00:00:00Z",
  "scope": {
    "object_type": "project_logs",
    "object_id": "resolved-project-id",
    "root_span_id": "trace-id"
  },
  "sequences": [
    {
      "id": "20000000000000000000000000000001",
      "length": 2,
      "parts": [{"literal": [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Hello"}
      ]}]
    }
  ],
  "rows": [{
    "event": {
      "id": "row-id",
      "span_id": "span-id",
      "root_span_id": "trace-id",
      "input": []
    },
    "bindings": [{
      "field": "input",
      "path": [],
      "id": "20000000000000000000000000000001"
    }]
  }]
}
```

A subsequent request can define the following state, bind its input to that ID,
and omit the already acknowledged initial definition:

```json
{
  "id": "20000000000000000000000000000002",
  "length": 4,
  "parts": [
    {"slice": {"id": "20000000000000000000000000000001", "start": 0, "end": 2}},
    {"literal": [
      {"role": "assistant", "content": "Hello!"},
      {"role": "user", "content": "Tell me more"}
    ]}
  ]
}
```

A later compaction preserving the last two messages is represented as:

```json
{
  "id": "20000000000000000000000000000003",
  "length": 3,
  "parts": [
    {"literal": [{"role": "system", "content": "Summary of earlier context"}]},
    {"slice": {"id": "20000000000000000000000000000002", "start": 2, "end": 4}}
  ]
}
```

Only the summary is sent as new content. Its binding has `reason: "compaction"`
when the producer observed a compaction event. Neither wire definition needs to
identify the individual messages in the retained slice.

The endpoint adapts the scope to ordinary destination routing. Version 1 requests
contain one scope, at least one row, and no repeated row IDs. Producers split
batches by scope and serialize updates to a given row using their existing
reporting-order policy. Multiple bindings per row support provider-native input
objects containing separate system and conversation arrays. Existing span IDs,
metrics, attachments, sampling, and merge controls retain their meanings.

An existing sequence ID with an identical definition is accepted using its
retained indexed value; its original dependencies need not still have public IDs.
A conflicting redefinition fails before any row changes.

The receiver MUST atomically validate and durably commit the definitions, row
updates/bindings, their dependency ownership, and a request receipt, or commit
none of them. An implementation MAY use staged writes internally but MUST NOT
expose or acknowledge a partial commit. Success returns HTTP 200:

```json
{"version": 1, "request_id": "10000000000000000000000000000001", "status": "committed"}
```

`request_id` follows the sequence ID syntax and identifies an immutable request
within its authenticated scope. A retry uses the same ID, body, and expiration.
The server MUST return the prior final result without reapplying updates, even
if the row has since changed. Different contents under an existing request ID
fail with `request_conflict`. Concurrent duplicates MUST serialize on that ID.

`expires_at` is a UTC RFC 3339 timestamp. Its future distance on first receipt
MUST NOT exceed `max_retry_seconds`. The receiver MUST retain final request
receipts through this deadline, including definitive dependency rejections.
A previously recorded receipt is checked before resolving dependencies. An
unrecorded request received after its deadline is rejected with HTTP 410
`request_expired`. Producers MUST stop automatic retries after that deadline
and surface a delivery failure; they MUST NOT silently submit an uncertain
mutation under a new ID. Timeouts and HTTP 5xx are uncertain, not rejections.

Missing or unavailable dependencies return HTTP 409 with a recorded final result:

```json
{
  "version": 1,
  "request_id": "10000000000000000000000000000001",
  "status": "rejected",
  "code": "missing_sequences",
  "ids": ["20000000000000000000000000000002"]
}
```

No row or sequence is committed for this result. The uploader MAY send a new
request with the missing definitions included, or encode the intended current
arrays as literals under fresh sequence IDs. A repaired request MUST use a new
request ID. This repair is safe only after definitive rejection; uncertain
requests must first be retried to obtain their receipt. Rejected requests that
exceed bounds can similarly be replaced by smaller requests or ordinary full
reporting after definitive rejection. Every replacement still follows ordinary
row-update ordering; repairs MUST NOT overtake later updates to the same row.

Other defined errors are HTTP 400 `invalid_history` (including cycles, ranges,
lengths, and bindings), HTTP 409 `sequence_conflict` / `request_conflict`, HTTP 413
`history_limit`, and ordinary authentication/authorization errors. Missing IDs
MUST only be disclosed after authenticating and authorizing the entire scope.
Receivers MUST NOT silently replace a missing history with an empty/partial input.

## Producer lifecycle

1. Capture the complete logical event in its existing in-memory form. Apply
   content-capture policy, sampling, customizers/redaction, provider mapping, and
   attachment processing before deciding which accepted values can be shared.
2. Compare explicitly recognized arrays against retained immutable histories.
   Choose slices plus literal new values when that is smaller; otherwise choose
   literals. A changed message is a new literal, not a mutation to an old one.
3. Queue the reporting envelope for asynchronous delivery. Retain the intended
   full logical row values, or a complete recoverable dependency closure, until
   its request is acknowledged or definitively fails. A cache alone is not a
   durability guarantee. Delivery has the same durability guarantees as the
   producer's existing queue; enabling this protocol MUST NOT weaken them.
4. Mark state IDs as remotely available only after successful acknowledgement.
   Pending dependencies can accompany dependents in the same request; dependencies
   sent separately must be acknowledged first. In a long session, known IDs may
   be reused without resending their contents.
5. On a definitive missing-base rejection, use the retained full values or closure
   to repair the rejected batch. On restart or cache eviction, a producer that
   cannot recover a base defines the next complete history with fresh IDs.

A producer MUST NOT assume shared identity merely because another service reports
the same trace. Cross-service reuse requires explicitly passing the scoped ID
and having either an acknowledged definition or its dependency closure available.
Such handoff is application/reporting metadata, not an invented OTel conversation
ID. No history content is automatically injected into public HTTP baggage in v1.
Independent SDK/gateway reporters may send separate literal roots; backend
interning can share their storage but does not eliminate their ingress bytes.

For coding agents, journal capture retains its existing event contract, complete
live events continue directly through translation, and history encoding belongs
to asynchronous outbound reporting. Recovery may rebuild this encoder from the
journal/SQLite or fall back to new literal states. This protocol requires no
additional local files and no live-path journal rereads. Each destination route
tracks its own acknowledgement; acceptance by one route does not acknowledge
another. A resumed session reuses states only within the same destination/trace
scope and when their availability is established.

### Client memory and durable resumption

A producer need not track the original storage location of every message. The
most recent sequence ID and its length address any unchanged range of that
sequence, even when the receiver assembled it from many older sequences. For
ordinary linear histories, locator metadata is constant-size per active history;
branches may retain additional roots within the same bounded cache.

Locating reusable ranges is a separate cost. A generic wrapper receiving a complete
new array must compare it with a retained immutable previous value, or use another
reliable source of change information. Keeping the previous value costs memory
proportional to the current history, not merely its ID. Retaining every prior
expanded input is unnecessary. Reference equality on mutable application objects
is not evidence of unchanged content. Fingerprints may accelerate matching but
must not silently change the required fidelity of captured values.

An SDK receiving explicit append/replace operations can derive slices directly
without rescanning old messages. A wrapper receiving only full arrays may scan
the previous/current arrays for common prefix and suffix ranges. Repeating such
scans across growing histories can still have quadratic cumulative CPU cost even
when reporting bytes are small; the protocol does not remove that work by itself.

SDKs MUST bound optional matching-cache bytes and entries across active histories,
with eviction and a literal fallback. They MUST NOT depend on local disk or remote
reads to construct live reports. On cache eviction or process restart, the next
complete observed input can establish a fresh literal root. If only incremental
changes are available and their base is lost, the producer must obtain a complete
state from its source or report the loss explicitly; inventing a root is invalid.

Matching caches and pending delivery have different lifetimes. Eviction MUST NOT
remove data needed to retry or repair an unacknowledged request. Queued roots may
share immutable segments, retaining one copy of unchanged contents rather than
one expanded history per pending span. Acknowledged obsolete roots can be released
when no cache entry or queued report needs them. Existing queue bounds and loss
reporting continue to apply; this protocol adds no unbounded offline buffer.

Coding-agent implementations MAY persist encoder roots, dependency definitions,
and pending request/receipt information in their existing SQLite store. Journal
positions may locate source data during recovery, but are not network sequence
IDs. A reference to journal data is sufficient only when it can reproduce the
exact post-transformation reporting value; otherwise pending values must be
retained in SQLite. Source reconstruction positions remain session-bound, while
remote acceptance is tracked per destination route. No extra files are required.
On restart, recovery can restore a bounded active working set or choose a fresh
literal root for the next complete input. Capture acknowledgement remains
independent of that recovery. Live matching uses the event and retained in-memory
state; it does not read old journal records on demand.

For gateways updating an exported span, the established owner of canonical input
retains ownership. The gateway MUST NOT overwrite that input merely to substitute
its independently parsed provider request. Gateway-created child spans may encode
their own captured inputs normally. Uninstrumented requests and initial histories
remain valid literal roots.

## Durable storage and retention

A conforming receiver MUST persist these logical entities (physical tables are
implementation-specific):

- **Sequence definitions**, keyed by scope and ID, with declared length and the
  immutable part list. Literal elements belong to the definition; they need no
  globally visible message keys. An implementation MAY intern equal values.
- **Row bindings**, owned by the committed revision of the ordinary row field,
  plus its unbound payload scaffold. Updating a row's binding updates the
  ownership roots atomically with the row; old query snapshots retain their own
  roots until they expire.
- **Request receipts**, including result and request identity comparison data,
  retained through the retry deadline.

A concrete reference storage layout is:

```text
sequence(scope, sequence_id) -> {length, immutable_parts, index_root}
segment(scope, internal_key) -> leaf{length, values: JsonValue[]}
                            | branch{length, children: InternalKey[]}
row_revision(row_id, revision) -> {ordinary_fields, bound_paths_and_roots}
receipt(scope, request_id) -> {request_identity, expires_at, final_result}
```

Segment keys are private storage addresses, not message identifiers or wire IDs.
Each branch length is the sum of its child lengths. Leaves have an implementation-
bounded chunk size; branch fanout and height are balanced. To slice a tree, retain
whole covered subtrees, copy only the boundary paths/partial leaf chunks, and form
a balanced root from the retained pieces and new literal chunks. Unchanged message
values need not be copied per span. An indexed root MUST be durable by the time its
sequence is acknowledged. The stored part list may reference shared literal storage
rather than duplicating literal bytes, but must retain enough information to check
an identical wire definition even after public dependency IDs are collected.

The physical sequence index SHOULD be a persistent, balanced concatenation/slice
structure, such as a rope or persistent vector. Leaf segments contain literal
arrays; internal segments reference child segments/ranges with cached lengths.
A sequence ID maps to an immutable root. Accepted wire parts are retained for
retry conflict validation, but reads SHOULD resolve the indexed root rather than
replay every ancestor definition. Slicing should share retained segments; balancing
and rewriting physical roots MUST preserve the logical sequence value and ID.
Storage engines may implement equivalent structures rather than this exact layout.

This distinction matters: a wire delta may reference yesterday's state without
forcing a query to replay yesterday's reporting stream. Regular full-history
checkpoints are not required for read performance and could restore quadratic
storage growth. Physical indexing must bound traversal overhead independently of
wire ancestry; configured depth-limit rejections have the literal fallback above.

Bindings retain their reachable logical contents and attachments under ordinary
row retention and authorization. A receiver MAY garbage-collect unreferenced
sequences, subject to live read snapshots and retry receipts. A retained binding
MUST remain reconstructable even when earlier span rows are deleted or filtered.
Deleting a source span must therefore retain its shared data or rewrite dependent
physical roots. Retaining a whole backing segment that includes excluded messages
is a physical choice, not permission to expose them through a sliced binding.

Compaction is not a content-erasure request. Explicit sensitive-data erasure MUST
remove/rewrite affected shared data and dependent materializations under the
platform's deletion policy; implementations must not silently preserve sensitive
content in interned leaves or caches. Where erasure intentionally makes a retained
history unavailable, queries must report that state explicitly. This protocol does
not invent a different right-to-delete policy for shared data.

## Query contract

Ordinary queries, filters, search, scoring, UI rendering, dataset/eval use, and
exports MUST observe the same logical `input`/`output` as full-payload reporting.
Bindings cannot be expanded only at response serialization: predicates and
aggregations evaluating these fields must see their complete values too. Unknown
or corrupt dependencies are errors, not valid empty histories.

The query engine MUST resolve state from durable storage independently of result
pagination, span sampling, or arrival order. It SHOULD lazily resolve only required
fields and ranges and share decoded segments within query execution. Indexes that
accelerate input search must account for inherited content; searching only literal
deltas is incorrect. Implementations must measure index growth as well as base
storage, and may evaluate supported predicates against shared values rather than
copying every inherited token into every span's index.

The proposed authenticated `POST /logs3/history/read` provides an opt-in compact
trace view. Its request has exactly `version: 1`, `scope` (the reporting scope
shape), `page_size` (a positive integer), and `cursor` (null on the first request,
otherwise the prior response cursor). Scope and page size stay fixed across
pages. The server MAY cap page size under ordinary query resource limits. Its
response has exactly `version: 1`, `scope`, `sequences`, `rows`, and `cursor`.
`rows` uses the binding shape above, but `event` is a complete ordinary result row,
not a merge operation. A null cursor marks the end. This endpoint reads one trace;
arbitrary BTQL projections/aggregations continue using existing query APIs and
their full logical field semantics.

Each page MUST include a dependency-closed set of definitions for its bindings;
a page may refer only to definitions included on that page. Full literal
re-encoding under query-scoped fresh IDs is allowed; these are not reusable
reporting IDs. Consumers must not require preceding pages to decode a page.
The cursor is opaque and preserves the trace read snapshot; an expired snapshot
returns an explicit error requiring a fresh read. Compact exports may flatten a
page's DAG when needed to meet depth limits. Cross-page sharing is intentionally
not part of v1: independent pages can repeat a prefix, while a single-page/export
view can share it across all returned rows.

Returned slice data must be authorized for the requested scope; unrelated span
fields and excluded source ranges must not be exposed merely to satisfy a slice.
The server must trim/re-encode those ranges when necessary. For an oversized
single row, the endpoint returns an explicit resource-limit error; it must never
truncate history to make a page fit.

A full response requesting every complete input may still be quadratic in output
bytes. Compact responses let clients process shared history directly. The wire,
base storage, indexes, and returned logical payloads are separate cost dimensions;
no claim of linear cost applies to arbitrary rewrites, repeated literal fallbacks,
or a caller explicitly requesting every expanded history.

## OpenTelemetry interoperability

[OTel issue #364](https://github.com/open-telemetry/semantic-conventions-genai/issues/364)
proposes opt-in `gen_ai.input.messages_delta`, ordered by conversation, with full
checkpoints for non-append changes and reconstruction using prior outputs. It is
an open proposal, not an adopted replacement for `gen_ai.input.messages`.

A Braintrust receiver may adapt such events only when their full ordering,
correlation, and required captured content are available. Missing or ambiguous
content MUST remain explicitly unavailable, not guessed. Explicit sequence IDs
and slices handle branches and compaction without assuming that previous outputs
were subsequently fed back unchanged. Ordinary OTel exporters continue emitting
complete conventional message attributes unless an explicitly negotiated
extension supports compact sequences. Native `gen_ai.conversation.id` and provider
usage/cache metrics retain their own meanings.

## Conformance and rollout

The executable sequence vectors in `test/history/sequences.json` define append,
compaction with a retained tail, forks, reordering, duplicate occurrences, and
invalid dependencies. They exercise array semantics, not an implemented service.
Before enabling the protocol, integration tests MUST additionally demonstrate:

- Atomic state/row/receipt commit; replayed receipt after a later row update;
  response loss, simultaneous retries, definitive missing-base repair, expiration,
  and retention of pending values across producer restart.
- Out-of-order definitions, separate batches, mixed producers, independent routes,
  scopes, existing full rows, field merge updates, and nested/overlapping bindings.
- Native provider messages, repeated identical messages, reasoning, attachments,
  customizer/redaction changes, numeric precision, and disabled content capture.
- Partial trace pages, input predicates over inherited values, compact exports,
  source-row deletion, live query snapshots, erasure, and corrupt storage.
- Long append-only and compacting sessions: actual ingress bytes, ingestion CPU,
  queue size, physical/index storage, and first-span/full-trace query latency.
  Tests must distinguish wire ancestry from physical lookup depth.

Deploy receiver validation/storage and compatible query resolution first. Enable
producers only after capability negotiation and end-to-end conformance. SDKs,
coding agents, gateway, and OTel adapters may adopt independently; full payloads
remain the fallback. This proposal does not require or approve a local journal
codec change.

# SDK support

```yaml
id: history-sequences
name: History sequences
category: Tracing
status: draft
support:
  sequence-history-reporting:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
```
