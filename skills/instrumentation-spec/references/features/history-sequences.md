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
Sequence = { id: SequenceId, parts: Part[] }
Part     = JsonValue
         | { "$braintrust_slice": { id: SequenceId, start: uint32, end: uint32 } }
         | { "$braintrust_literal": JsonValue }
```

`SequenceId` is a nonzero random 128-bit identifier, encoded as 32 lowercase hex
characters in JSON. Individual messages need no identities. Ordinary parts are
individual messages or other JSON items; each contributes exactly one element.
An exact single-key `$braintrust_slice` object contributes the referenced
materialized range `[start, end)`. Indexes are unsigned 32-bit integers and MUST
satisfy `start <= end <= source.length`.

The materialized length is derived: sum one for each ordinary or escaped item and
`end - start` for each slice. It is not transmitted. Computing it does not require
expanding referenced contents. Implementations MAY cache this derived length and
part offsets; they MUST check unsigned 32-bit arithmetic rather than wrap on overflow.
An empty sequence is `{id, parts: []}`.

At the top level of each part, exact single-key `$braintrust_slice` and
`$braintrust_literal` objects are reserved. To include such an object as actual
data, wrap it once in `$braintrust_literal`. Unwrap that escape once and emit its
contents as one item, without interpreting them again. Malformed slice wrappers
are errors; objects with additional keys and reserved-looking objects nested
inside a message remain ordinary data. A nested array is also one literal item,
not a group of messages to flatten.

Slice indexes MUST address the referenced sequence's entire materialized array,
not positions in its `parts` list. This applies recursively when the referenced
sequence contains slices. A slice can start/end inside another slice and cross
several parts:

```text
A.parts = [a, b, c]                           => [a, b, c]
B.parts = [x, slice(A, 1, 3), y, z]           => [x, b, c, y, z]
C.parts = [slice(B, 1, 4)]                    => [b, c, y]
```

B has four parts but five materialized items. C takes materialized positions
1 through 3, crossing B's slice and its following literal item. `slice(...)` is
shorthand here for the `$braintrust_slice` object above. Repeated equal messages
remain separate occurrences; nested fields, reasoning, attachment references,
and numeric precision retain their captured meanings.

Sequences form an immutable directed acyclic graph. An ID denotes one definition;
it MUST NOT be reused for a different definition. Reapplying an identical
definition is a no-op. Conflicting definitions, cycles, malformed tags, invalid
indexes, and derived-length overflow are errors.

All references are interpreted within the cache's identity domain, supplied by
its owner. Reporting domains MUST be isolated by organization, destination, and
trace. A sequence ID is not authorization. Native session/conversation identifiers
and span parentage keep their existing meanings; neither determines sequence
ancestry. Separate domains can share a sequence's contents only by copying them
under new local IDs.

## Full and sequenced input shapes

The existing `input` field accepts either its ordinary JSON payload or a tagged
sequence representation. The reserved shape is an object with exactly one key:

```text
SequencedInput = { "$braintrust_history": Sequence }
LiteralInput   = { "$braintrust_literal": JsonValue }
```

At the root of `input`, an exact `$braintrust_history` wrapper is decoded as a
sequence and validated as such. An exact `$braintrust_literal` wrapper is unwrapped
once and its contents are ordinary data, never recursively interpreted as another
wrapper. All other values retain their existing full-payload behavior. Objects
with additional keys and reserved-looking objects nested inside message payloads
are ordinary data. Malformed reserved wrappers are errors, not full-payload fallbacks.

Producers MUST escape a literal input that itself has either exact reserved shape
using `$braintrust_literal`. These shapes become reserved: an older producer already
emitting that exact application object cannot be distinguished by shape alone.
The backend rollout must account for that compatibility boundary. Materialized
query results are logical data and MUST NOT be decoded a second time.

The sequence describes the complete array-valued input sent to this LLM request:
retained session messages, compaction/edits, and new messages. Its definition lives
directly in that SpanOp's `input`. `output` contains only this request's response
and keeps its existing representation. The next input includes a previous response
only when it was actually part of that captured request.

For example, the first span carries its initial history and its response:

```json
{
  "id": "span-row-1",
  "span_id": "span-1",
  "root_span_id": "trace-1",
  "output": [
    {"role": "assistant", "content": "Hello!"}
  ],
  "input": {
    "$braintrust_history": {
      "id": "00000000000000000000000000000001",
      "parts": [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Hello"}
      ]
    }
  }
}
```

The next span carries its own sequence, reusing the preceding input:

```json
{
  "id": "span-row-2",
  "span_id": "span-2",
  "root_span_id": "trace-1",
  "input": {
    "$braintrust_history": {
      "id": "00000000000000000000000000000002",
      "parts": [
        {
          "$braintrust_slice": {
            "id": "00000000000000000000000000000001",
            "start": 0,
            "end": 2
          }
        },
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Tell me more"}
      ]
    }
  }
}
```

Reading the second input yields four ordinary messages. Its ID names that
whole array, so future spans can slice it without knowing the original location
of each message. A compaction can define `[summary, slice(second, 2, 4)]`;
a branch can reference an older sequence. Responses first join reusable history
as literals in subsequent inputs; they are not implicitly appended from `output`.

Supplying either a full or tagged input replaces the logical input under the
ordinary span update rules. The tagged wrapper and its parts MUST NOT be deep-merged
as application input objects. An omitted input retains the previous value; `null`
and an empty array remain distinct. Validate/register a compact definition with
its row update before exposing either. Legacy and tagged rows can coexist.

The sequence represents an array. Provider-native object/scalar inputs remain
full payloads until a representation preserves all their fields. Implementations
MUST NOT drop native fields merely to enable compact reporting.

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
matching ranges when beneficial. The caller wraps that definition in
`$braintrust_history` in its SpanOp's `input`. `apply` registers an incoming
definition without needing to expand its full array. `read` materializes that array. `snapshot` returns an
equivalent all-literal definition under a fresh ID, requiring no earlier state.
The caller can wrap that snapshot as a span input and use its new ID for subsequent
references. A snapshot does not rename old IDs or repair outstanding references to
them; those dependencies must be retained or their pending operations re-encoded.

`unload` releases resident payloads only when they remain retrievable from storage
or another retained copy; otherwise it must refuse while retained roots need them.
Missing state is an error, never an empty or partially reconstructed array. Both
sides use these operations; persistence and transport are separate adapters.
Implementations may eagerly or lazily materialize data. A read adapter supplies
`load(sequence_id) -> Sequence` within the same identity domain. It loads the
definition from memory, disk, or a scoped remote read. An in-memory-only adapter reports unavailable state rather than fetching implicitly.
Matching never initiates hidden remote reads. A persistence adapter indexes each
scoped ID to its immutable definition or record position; it must not resolve it
through a span's mutable current input, which may have been updated since capture.

### Reading a sequence chain

`read(id)` reconstructs the entire array; the same operation can accept an optional
half-open range for consumers needing only part of it. The cache obtains missing
definitions through `load`, validates their identity and structure, and retains
only a bounded working set. A sequence ID is a lookup key for this adapter, not
an instruction to replay all earlier spans or search by timestamps.

To read `[start, end)` from a sequence:

1. Load its definition if absent. Validate the requested range against its
   derived length. Track the active dependency path to detect cycles; reject missing,
   conflicting, or invalid definitions without returning a successful partial input.
2. Walk its parts in order, tracking cumulative element offsets. Each literal
   item contributes one; each slice contributes `end - start`. Sum them with
   checked arithmetic to derive the sequence's materialized length.
3. Skip parts outside the requested range. For an overlapping literal, emit only
   that one item. For an overlapping slice starting at `source_start`,
   translate the overlap's offsets within that part to
   `[source_start + overlap_start, source_start + overlap_end)` in the source.
   Load that source and repeat for that range, preserving output order.
4. Emit the resulting messages into the caller's array or iterator. On successful
   completion, verify the emitted count. Use an explicit traversal stack for long
   chains, share loaded descriptors, and avoid expanding every ancestor's array.
   A streaming consumer must observe a later read error as a failed input.

For `C.parts = [summary, slice(B, 2, 4)]` and
`B.parts = [slice(A, 0, 2), assistant, user]`, reading C yields
`[summary, assistant, user]`. It visits C and the tail of B; A's discarded prefix
is not materialized or fetched for its contents. Previously accepted definitions
remain subject to validation; range-selective readback is not permission to accept
an invalid dependency graph. Physical I/O granularity is the adapter's concern.

A persisted fingerprint index can restore matching state without reading messages.
If it is absent, the same traversal can fingerprint each emitted element to build
the requested root's index while rebuilding its contents. An available parent index
can instead supply copied fingerprint ranges plus hashes of new literals. Neither
approach requires retaining full arrays or indexes for every ancestor. Metadata-only
restoration supports matching against a new complete input; actually reading old
contents still requires accessible literal data.

A fresh client can restore by replaying original SpanOps in dependency order, or
by loading a requested definition and following its dependencies through the read
adapter. Replay registers the sequences and rebuilds their indexes; it need not
expand every historical input. A self-contained literal snapshot needs no preceding
records. An SDK that has lost its cache and has no remote read adapter can establish
a new root from the next complete observed input instead of recovering old data.

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
parts:    [Summary, slice(H, 2, 4), E]
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
operations; persistence records the same operations and replays their tagged
inputs into the same cache. Batching, authentication, acknowledgements, and storage
layout belong to existing adapters, not a second history envelope or value stream.

Adapters must preserve these rules:

- A referenced sequence is available before a dependent operation is exposed.
  Operations in a batch may be resolved in dependency order; otherwise restore
  missing source operations or re-encode pending arrays as all-literal snapshots.
  Successfully queueing an operation does not establish remote acceptance.
- Validate tagged sequence definitions before exposing
  the corresponding row change or advancing durable progress.
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
input, whether its stored `input` is full JSON or a tagged sequence. Output capture and reads
retain their existing behavior. Predicates, search, scoring, and ordinary exports
evaluate the reconstructed value. Resolving a history must not depend on its source span appearing in the same
query page. Legacy rows and compact rows can coexist in one trace.

A compact export returns ordinary spans with tagged `input` objects referencing
state known to its consumer or substituting self-contained snapshot definitions
with fresh IDs. This preserves which spans belong to the result set; source spans
need not be added as extra results. The consumer registers those definitions and uses the same read operation.

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
matching without old contents, selective chain readback, literal escapes, mixed full/compact
updates, restart/replay, missing state, and invalid ranges. Implementations must
additionally validate storage/transport crash boundaries and measure matching CPU,
queue memory, ingress bytes, physical storage, and query cost. Requesting every expanded history can
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
