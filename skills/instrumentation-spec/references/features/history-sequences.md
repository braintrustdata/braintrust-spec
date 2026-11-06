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
indexes, and length mismatches are errors. Identical definitions may be shared
by both history fields in one operation.

All references are interpreted within the cache's identity domain, supplied by
its owner. Reporting domains MUST be isolated by organization, destination, and
trace. A sequence ID is not authorization. Native session/conversation identifiers
and span parentage keep their existing meanings; neither determines sequence
ancestry. Separate domains can share a sequence's contents only by copying them
under new local IDs.

## History fields on span operations

Add two optional fields to the span row carried by an existing SpanOp:

```text
input_history?: Sequence
output_history?: Sequence
```

`input` and `output` retain their existing full-payload formats. `input_history`
is a compact representation of an array-valued `input`; `output_history` similarly
represents an array-valued `output`. Each field contains its own complete sequence
definition, not a pointer to a separately transmitted definition. SDKs and the
gateway report the same fields on their ordinary span updates. All other span
fields, Insert/Merge behavior, and routing remain unchanged.

For example, the first span reports its initial history in full as literals:

```json
{
  "id": "span-row-1",
  "span_id": "span-1",
  "root_span_id": "trace-1",
  "input_history": {
    "id": "00000000000000000000000000000001",
    "length": 2,
    "parts": [{"literal": [
      {"role": "system", "content": "Be helpful."},
      {"role": "user", "content": "Hello"}
    ]}]
  }
}
```

The next span carries its own sequence, reusing the first span's history:

```json
{
  "id": "span-row-2",
  "span_id": "span-2",
  "root_span_id": "trace-1",
  "input_history": {
    "id": "00000000000000000000000000000002",
    "length": 4,
    "parts": [
      {"slice": {"id": "00000000000000000000000000000001", "start": 0, "end": 2}},
      {"literal": [
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Tell me more"}
      ]}
    ]
  }
}
```

`input_history.id` names the resulting whole input, so later operations can slice
it without knowing where its individual messages originally came from. A compaction
can define `literal([summary]) + slice(second, 2, 4)`; an append adds another literal
part. A branch references an earlier sequence without changing other histories.
Explicit compaction events keep their ordinary metadata; the replication algorithm
need not recognize or infer compaction. Output histories can be referenced by later
input histories only when the actual captured values match.

### Full and compact payloads

For each `input`/`input_history` or `output`/`output_history` pair:

- Full field only: process the existing JSON payload unchanged. The producer need
  not assign any sequence IDs. A receiver MAY intern array values locally, but
  senders cannot reference those private IDs without being given them.
- Compact field only: its materialized array is the complete logical field value.
  It replaces the previous value; omitted full payload is not a missing history.
- Both fields: the materialized compact sequence MUST equal the full field. Reject
  conflicting values before changing the row or cache. Sending both is permitted
  for migration/validation but saves no payload bytes.
- Neither field: retain the existing value under ordinary merge semantics.

A full-field update replaces the field's previous compact association, and a compact
update replaces its previous full representation. The two are alternative encodings
of one logical field, not independently merged values. Update that choice with the
row, not in a separate publication step. Older retained sequences remain immutable
and available while other spans depend on them. `null`, empty arrays, and omitted
fields keep their distinct meanings.

The sequence format represents arrays. Arbitrary object/scalar payloads continue
using ordinary full fields; it does not rewrite provider-native objects through
placeholder paths. Integrations using compact histories must capture their complete
array-valued logical input/output under the existing instrumentation contract.
Provider-native object payloads retain full reporting until a separately specified
representation preserves all of their fields. No native fields may be discarded
merely to enable this optimization.

## Uniform cache interface

Every participant uses the same conceptual interface:

```text
encode(array) -> Sequence
apply(sequence) -> SequenceId
read(sequence_id) -> JsonValue[]
snapshot(sequence_id) -> Sequence
unload(sequence_id)
```

`encode` registers a captured array and returns its sequence definition, reusing
matching ranges when beneficial. The caller attaches that definition directly to
its SpanOp's history field. `apply` registers an incoming definition without needing
to expand its full array. `read` materializes that array. `snapshot` returns an
equivalent all-literal definition under a fresh ID, requiring no earlier state.
The caller can attach that snapshot to a span and use its new ID for subsequent
references. A snapshot does not rename old IDs or repair outstanding references to
them; those dependencies must be retained or their pending operations re-encoded.

`unload` releases resident payloads only when they remain retrievable from storage
or another retained copy; otherwise it must refuse while retained roots need them.
Missing state is an error, never an empty or partially reconstructed array. Both
sides use these operations; persistence and transport are separate adapters.
Implementations may eagerly or lazily materialize data. Loading is explicit in the
adapter; matching does not initiate hidden remote reads.

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
matching metadata, not message identities sent in span operations. Matching assumes SHA-256
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

The SpanOp itself carries the new history state. A network stream sends span
operations; persistence records the same operations and replays their history
fields into the same cache. Batching, authentication, acknowledgements, and storage
layout belong to existing adapters, not a second history envelope or value stream.

Adapters must preserve these rules:

- A referenced sequence is available before a dependent operation is exposed.
  Operations in a batch may be resolved in dependency order; otherwise restore
  missing source operations or re-encode pending arrays as all-literal snapshots.
  Successfully queueing an operation does not establish remote acceptance.
- Validate the history definitions and full/compact consistency before exposing
  the corresponding row change or advancing durable progress. Cross-references
  between history fields in the same operation must resolve without a cycle.
- Repeated definitions are idempotent. Span operations retain their existing
  ordering, merge, retry, and acknowledgement semantics. A replayed definition
  does not itself suppress or reorder a span operation.
- Retain actual data needed to retry/repair pending operations. Fingerprints do
  not substitute for content. Metadata and payloads may be unloaded independently,
  but retained spans must remain reconstructable. A replay starting with an empty
  cache must include source dependencies or self-contained snapshot operations.
- Release unused roots under existing retention rules. Deleting a source span must
  not break another retained span's history. Compaction changes a new array; it
  does not erase older retained values. Existing authorization and explicit
  content-erasure policies apply to shared data too.

An SDK can keep a bounded matching index and pending operations in memory, unload
acknowledged payloads, and establish new literal roots after eviction/restart.
This adds no durability beyond its existing queue. Coding agents can persist
operations and active indexes in their existing SQLite/journal storage and restore
a bounded working set. Persist active fingerprint changes incrementally rather
than copying entire vectors per span. No extra files or live-path journal reads
are required. Recovery/outbound replication remain independent of hook capture;
each route establishes its own accepted progress.

Backend storage can index shared segments instead of replaying all historical
operations per query. The model does not prescribe tables, trees, or checkpoint
frequency. Snapshots and incremental history definitions represent the same arrays
and can be converted without changing the logical span data.

## Reporting and queries

Capture remains complete: existing consumers MUST observe the full logical span
input/output, whether a row was reported with a full field or its compact history
field. Predicates, search, scoring, and ordinary exports evaluate the reconstructed
value. Resolving a history must not depend on its source span appearing in the same
query page. Legacy rows and compact rows can coexist in one trace.

A compact export returns ordinary spans with their history fields, referencing
state known to its consumer or substituting self-contained snapshot definitions
with fresh IDs. This preserves which spans belong to the result set; source spans
need not be added as extra results. The consumer applies the same history fields
to the same cache.

The format applies equally to SDKs, coding agents, and gateway-owned spans. Existing
ownership of exported span inputs remains unchanged. It does not infer that one
span's output belongs in the next span's input. The actual next captured array is
authoritative. Provider token/cache metrics remain independent of telemetry size.

[OTel issue #364](https://github.com/open-telemetry/semantic-conventions-genai/issues/364)
proposes append-only message deltas and full checkpoints on non-append changes.
This shared sequence model also expresses compaction and branching explicitly.
Ordinary OTel output retains its established complete-message format unless its
consumer supports a compact representation; conversation IDs retain their meaning.

The sequence vectors and cache tests exercise round-trip span reconstruction,
matching without old contents, compaction, branches, duplicates, mixed full/compact
updates, restart/replay, missing state, and invalid ranges. Implementations must
additionally validate storage/transport crash boundaries and measure matching CPU,
queue memory, ingress
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
