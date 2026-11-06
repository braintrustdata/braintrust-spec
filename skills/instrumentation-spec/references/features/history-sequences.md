# History sequences

Conversation history is shared state. This specification defines a reversible
representation of that state and the updates needed to replicate it. The same
model applies in SDKs, coding agents, the gateway, and the backend, whether updates
are sent over a network or written to storage and read back later.

The backend is deployed before producers use this representation. There is no
runtime capability negotiation. Existing full-payload reporting remains valid.
Normative terms MUST, SHOULD, and MAY describe implementations using this model.

## Shared object model

A cache contains immutable sequences, each representing an ordered JSON array.
A sequence is composed of literal elements and slices of existing sequences:

```text
Sequence = { id: SequenceId, length: uint32, parts: Part[] }
Part     = { literal: JsonValue[] }
         | { slice: { id: SequenceId, start: uint32, end: uint32 } }
```

`SequenceId` is a nonzero random 128-bit identifier, encoded as 32 lowercase hex
characters in JSON. Individual messages do not need identities. Each slice
contributes `source[start:end]`: indexes are half-open, address array elements,
and MUST satisfy `start <= end <= source.length`. Concatenating the parts MUST
yield exactly `length` elements. Lengths and indexes are unsigned 32-bit integers;
implementations MUST check arithmetic rather than wrap on overflow.

An empty sequence has `length: 0` and `parts: []`. Repeated equal elements remain
separate occurrences. Nested payload fields, reasoning, attachment references,
and numeric precision retain their existing captured meanings. Literal elements
are opaque JSON; reference-shaped objects inside them remain ordinary data.

Sequences form an immutable directed acyclic graph. An ID denotes one definition;
it MUST NOT be reused for a different definition. Reapplying an identical
definition is a no-op. Conflicting definitions, cycles, malformed tags, invalid
indexes, and length mismatches are errors. A frame defines each ID at most once.

All references are interpreted within the cache's identity domain, supplied by
its owner. Reporting domains MUST be isolated by organization, destination, and
trace. A sequence ID is not authorization. Native session/conversation identifiers
and span parentage keep their existing meanings; neither determines sequence
ancestry. Separate domains can share a sequence's contents only by copying them
under new local IDs.

## Encoded values and update frames

A sequence reference occurs directly in the encoded value that contains it.
There are no span-specific bindings, field paths, or placeholder replacement rules:

```text
Value = { literal: JsonValue }
      | { object: { string: Value } }
      | { array: SequenceId }
Frame = { sequences: Sequence[], values: Value[] }
```

The alternatives are tagged unions with exactly the shown fields. `literal`
contains an ordinary complete JSON value. `object` recursively describes its
members. `array` resolves to the referenced complete array. This wrapper belongs
to the replication format, not the application payload, so it cannot collide
with a user's literal object. An encoder can leave an entire value literal when
sharing its arrays would not help. Empty arrays, missing fields, and `null` remain
distinct. A frame can define state without emitting a value (`values: []`).

For example, this frame reports a span whose logical input is two messages:

```json
{
  "sequences": [{
    "id": "00000000000000000000000000000001",
    "length": 2,
    "parts": [{"literal": [
      {"role": "system", "content": "Be helpful."},
      {"role": "user", "content": "Hello"}
    ]}]
  }],
  "values": [{"object": {
    "id": {"literal": "span-row-1"},
    "input": {"array": "00000000000000000000000000000001"}
  }}]
}
```

Applying it and reading the value yields the ordinary span object with its full
`input` array. A later frame can define another array from that sequence:

```json
{
  "sequences": [{
    "id": "00000000000000000000000000000002",
    "length": 4,
    "parts": [
      {"slice": {"id": "00000000000000000000000000000001", "start": 0, "end": 2}},
      {"literal": [
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Tell me more"}
      ]}
    ]
  }],
  "values": [{"object": {
    "id": {"literal": "span-row-2"},
    "input": {"array": "00000000000000000000000000000002"}
  }}]
}
```

A compaction can then define `literal([summary]) + slice(second, 2, 4)`; an append
adds another literal part. A branch references an earlier sequence without
changing other histories. Explicit compaction events retain their existing event
metadata; the replication algorithm need not recognize or infer compaction.

Frames MUST contain a dependency-closed set of definitions relative to the
receiving cache. Definitions within a frame may appear in any order. A receiver
validates the entire frame before exposing its definitions or values. Missing
state is an error, never an empty or partially reconstructed history. An export
intended for an empty cache MUST include the complete dependency closure; it can
instead flatten sequences to literals under fresh IDs.

## Uniform cache interface

Every participant uses the same conceptual interface:

```text
intern(array) -> SequenceId
encode(json_value, known_ids = empty) -> Frame
apply(frame) -> Value[]
read(value) -> JsonValue
export(roots, known_ids = empty) -> Frame
unload(sequence_id)
```

`intern` registers a captured array, reusing matching ranges when beneficial.
`encode` traverses a captured value, interns selected arrays, and exports its
encoded value with definitions not already in the target's `known_ids`. `apply` registers
incoming definitions and returns the encoded values without requiring their full
arrays to be expanded. `read` reconstructs ordinary JSON. `export` emits the
roots and their dependency closure, omitting only state known to be available at
the target. With an empty `known_ids`, it produces a self-contained snapshot.
`unload` releases resident payloads only when they remain retrievable from storage
or another retained copy; otherwise it must refuse while retained roots need them.

These are model operations, not prescribed SDK methods or network endpoints.
Both sender and receiver can intern, apply, read, and export. There is no separate
client object model or backend object model. Implementations may eagerly or lazily
materialize sequences, but MUST preserve identical values. Unloaded/unavailable
content is distinguishable from an empty sequence. Loading data is explicit in
the storage/transport adapter; matching does not initiate hidden remote reads.

### Finding reusable ranges

The cache can retain an ordered fingerprint array alongside each candidate root:
`(sequence_id, length, serializer_version, fingerprints[])`. It need not retain
old message contents or mirror every historical sequence tree to match new input.
Fingerprint position is the message's position in that named sequence.

Use SHA-256 over a domain separator `braintrust.history.element.v1` followed by a
zero byte and a complete lossless UTF-8 JSON serialization of the captured element.
Capture policy, provider mapping, redaction, and attachment conversion happen
before interning. Values MUST be frozen for capture; reference equality on mutable
application objects is insufficient. Serializer changes invalidate the index.
Harmless encoding differences can reduce reuse, but omitted captured fields or
lossy numeric conversion must not hide a changed value. Fingerprints are internal
matching metadata, not message identities sent in frames. Matching assumes SHA-256
collision resistance; applications requiring collision-free equality must compare
retained values or use trustworthy source change information instead.

For a new array, compute its fingerprints, find a matching contiguous run, and
emit current literals before/after a slice of the matched parent. For example:

```text
cached H: [h(A), h(B), h(C), h(D)]
current:  [Summary, C, D, E]
encoded:  literal([Summary]) + slice(H, 2, 4) + literal([E])
```

A simple implementation indexes parent fingerprints by position and extends equal
candidates. It MUST bound search work, including repeated-digest candidates; it
can use the best run found or fall back to literals. Prefer the longest run found,
then the lowest parent start, then the lowest current start. Multiple runs are
allowed if they preserve current order and occurrences. Emit literals if slices
would cost more bytes. Prefix/suffix matching alone misses the example above.

`apply` can build the same index by hashing literals and copying fingerprint
ranges from slice sources, without reading old message contents. Persisted index
metadata can also be restored directly. This index has the same meaning everywhere;
it is independent of which participant holds the cache or how payloads are stored.

A bounded cache of current roots costs one fixed-size digest per element rather
than all prior message bytes. Evicted matching entries cause literal fallback for
the next complete observed array. Hashing complete arrays still scans their content
and can accumulate quadratic CPU work across a growing conversation. Sources with
trustworthy append/replace operations can update the shared model incrementally.
If only increments are available and their base is lost, obtain complete source
state or report the loss; fingerprints alone cannot recover content.

## Replication, persistence, and lifetime

Transport and storage are adapters around frames. A network stream can transmit
them; a persistence adapter can record the same frames and replay them into a fresh
cache. Framing, authentication, acknowledgements, and storage layout belong to
those adapters, not this object model.

An adapter must preserve these rules:

- Send definitions before dependent values, either within a validated frame or
  after successful delivery of prerequisite frames. A durable progress cursor may
  establish which state has been accepted; queueing alone does not establish that.
- Repeated sequence definitions are idempotent. Emitted values are ordinary span
  updates, not automatically deduplicated commands. The enclosing reporting system
  retains its existing ordering, retry, merge, and acknowledgement semantics.
- An interrupted/incomplete frame exposes no new values. Durable progress advances
  only after the corresponding frame is recoverable. Replay resumes from that
  progress with its required cache state, or from a self-contained export.
- Retain enough actual content to retry/repair pending updates. Fingerprints cannot
  substitute for that content. Metadata and payloads may be unloaded independently,
  but an acknowledged state must remain reconstructable while retained values need
  it. Missing dependencies must be restored or replaced by a self-contained export.
- Release unused roots and garbage-collect unreachable data under existing retention
  rules. Deleting a source span must not break another retained span's history.
  Compaction changes a new array; it does not erase older retained values. Existing
  authorization and explicit content-erasure policies also apply to shared data.

An in-memory SDK can keep a bounded matching index and pending values, unload
acknowledged payloads, and establish new literal roots after cache eviction/restart.
This gives no durability beyond its existing queue. Coding agents can persist
frames and active indexes in their existing SQLite/journal storage and restore a
bounded working set. Persist active fingerprint changes incrementally rather than
copying every entire vector per span. No extra files or live-path journal reads
are required. Recovery and outbound replication remain independent of hook capture.
Each reporting route establishes its own accepted progress.

Backend storage can index shared segments for efficient reads instead of replaying
all historical frames per query. The model does not prescribe trees, tables, or
checkpoint frequency. Snapshots/exports and incremental frames describe the same
state and can be converted without changing materialized span values.

## Reporting and queries

Capture remains complete: existing consumers MUST observe the full logical span
input/output, including when predicates, search, scoring, or exports evaluate it.
An ordinary query resolves references through the shared cache/storage layer;
reconstruction must not depend on earlier spans appearing in the result page.
A compact export can return encoded values plus their dependency-closed definitions
for a consumer to apply to the same model. Pagination/transport may share known
state or make each page self-contained; neither changes the representation.

The format applies equally to SDKs, coding agents, and gateway-owned spans. Existing
ownership of exported span inputs remains unchanged. It does not infer that one
span's output belongs in the next span's input. The actual next captured array is
authoritative. Provider token/cache metrics remain independent of telemetry size.

[OTel issue #364](https://github.com/open-telemetry/semantic-conventions-genai/issues/364)
proposes append-only message deltas and full checkpoints on non-append changes.
This shared sequence model also expresses compaction and branching explicitly.
Ordinary OTel output retains its established complete-message format unless its
consumer supports a compact representation; conversation IDs retain their meaning.

The sequence vectors and cache tests exercise round-trip reconstruction, matching
without old contents, compaction, branches, duplicates, restart/replay, missing
state, and invalid ranges. Implementations must additionally validate their actual
storage/transport crash boundaries and measure matching CPU, queue memory, ingress
bytes, physical storage, and query cost. Requesting every expanded history can
still produce quadratic response bytes; a compact export avoids those repetitions.

# SDK support

```yaml
id: history-sequences
name: History sequences
category: Tracing
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
