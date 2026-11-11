# History sequences

This model shares conversation history across SDKs, coding agents, the gateway,
and backend. Each SpanOp carries its effective input; network and disk adapters
replicate the same immutable data. Deploy backend support before clients use it;
there is no runtime negotiation. MUST/SHOULD/MAY describe conforming implementations.

## Representation

```text
Input    = ordinary JSON | { "$bt_history": Sequence }
Sequence = { id: SequenceId, parts: Part[] }
Part     = ordinary JSON | { "$bt_slice": { id: SequenceId, start: uint32, end: uint32 } }
```

IDs are nonzero random 128-bit values encoded as 32 lowercase hex characters.
They identify immutable history snapshots, not mutable span rows. References are
scoped to organization, destination, and trace; an ID grants no access by itself.
The same definition may be replayed; conflicting reuse of an ID is an error.

Only exact single-key wrappers are syntax: `$bt_history` at the input root and
`$bt_slice` at a part root. Malformed wrappers are errors. Those shapes are reserved
and cannot be literal data there; extra keys or nested occurrences are ordinary
JSON. Full inputs remain supported. Tagged inputs replace the logical input and
MUST NOT be deep-merged as application objects; omitted input preserves normal
merge behavior. Null, empty arrays, repetitions, nested arrays, numeric precision,
reasoning, and attachments retain their captured meanings. Materialized query
results must not be decoded again.

Every direct part contributes one item. A slice contributes the half-open range
`[start, end)` of its source's **entire materialized array**, recursively resolving
references. It never indexes the source's parts. Length is derived by summing one
per direct item and `end - start` per slice. Use checked uint32 arithmetic and
validate `start <= end <= source.length`; no wire length field is needed.

For example, B has four parts but five materialized items:

```text
A = [a, b, c]
B = [x, slice(A, 1, 3), y, z]   => [x, b, c, y, z]
C = [slice(B, 1, 4)]            => [b, c, y]
```

`slice(...)` abbreviates the tagged object. Definitions form an acyclic graph.
Reject invalid IDs, ranges, tags, overflow, cycles, or missing dependencies before
exposing a successful span update. An empty sequence has `parts: []`.

## Span inputs

The sequence describes the actual complete array sent to the model: retained
history with compaction/edits applied, plus new messages. `output` remains only
the current response. A later input includes that response only if actually sent.
Provider-native object/scalar inputs keep full reporting; do not discard fields
to enable this array representation. Existing span identity/routing stays unchanged.

First request and response:

```json
{
  "id": "span-row-1", "span_id": "span-1", "root_span_id": "trace-1",
  "input": {"$bt_history": {
    "id": "00000000000000000000000000000001",
    "parts": [{"role": "system", "content": "Be helpful."}, {"role": "user", "content": "Hello"}]
  }},
  "output": [{"role": "assistant", "content": "Hello!"}]
}
```

Next request, reusing that input and adding the response and new user message:

```json
{
  "id": "span-row-2", "span_id": "span-2", "root_span_id": "trace-1",
  "input": {"$bt_history": {
    "id": "00000000000000000000000000000002",
    "parts": [
      {"$bt_slice": {"id": "00000000000000000000000000000001", "start": 0, "end": 2}},
      {"role": "assistant", "content": "Hello!"}, {"role": "user", "content": "Tell me more"}
    ]
  }}
}
```

Compaction is a new sequence such as `[summary, slice(previous, 2, 4), new_message]`.
It does not mutate older histories. Explicit compaction events keep their metadata;
the encoding does not infer why messages changed or implicitly append outputs.

## Branch-local matching and resumption

Keep only `(parent_id, parent_items)` for each active branch. The parent is the
immediately preceding input **on that branch**, not the latest span by timestamp.
A fork can share its parent's immutable value; advancing one branch does not move
another. Producers supply the predecessor through their tracing/session context.
If it is unknown, send the current array directly under a fresh sequence ID.

Compare the frozen current array directly with that parent. Reuse unchanged
prefix/suffix ranges; a bounded sequence diff can find retained middle runs after
compaction followed by append. Emit new items between slices in current order,
preserving duplicates. Bound comparison work and use direct items when matching
costs too much or references save no bytes. The model requires neither a persistent
hash-to-position index nor a search across historical branches. Native append/edit
operations may supply ranges directly if they preserve the exact captured input.

Capture/redaction/provider mapping/attachment handling precede comparison. Use
structural equality preserving JSON types and precision, not identity of mutable
application objects. Comparing complete arrays still scans their content; keeping
one parent still uses memory proportional to its contents. Bound active branches
and resident bytes, evicting payloads to the configured store when needed.

The shared cache interface is conceptual, not a required SDK API:

```text
encode(items, parent_id?) -> Sequence    apply(sequence) -> SequenceId
read(id) -> items                       snapshot(id) -> all-literal Sequence with a fresh ID
unload(id)                              // release resident data only when recoverable
```

`encode` attaches its definition directly inside `input.$bt_history`. `apply`
registers it without expanding every ancestor. `snapshot` creates an independent
root; old IDs and pending references are not renamed by that operation.

On a cache miss, `read(parent_id)` can load from the configured local store or the
backend. Backend support MUST provide authorized lookup of the exact immutable
history by scope and ID, returning its materialized items; HTTP routing belongs
to the API implementation. Sequence/record lookup also supports the pointer
readback below. Never substitute a span's subsequently updated input for an ID.

SDKs keep a bounded in-memory parent cache and fetch from the backend on cold
resume/eviction. Coding agents may persist that cache in their existing SQLite/
journal storage. Loading is explicit, bounded outbound/recovery work; capture
and model requests never wait for it. If unavailable, a complete current input can
start a new literal root; incremental-only sources must recover their base or
report loss. Fetching a full parent on every span can recreate quadratic network
traffic, so neither diskless SDKs nor plugins should reload a resident parent.

## Pointer-based readback

Build a view of direct items and `pointer(sequence_id, materialized_index)` values.
A slice contributes one pointer for each requested source position; pointers are
internal and never add IDs to individual messages on the wire. Resolve a pointer
by locating its position among the source's derived part offsets: a direct part
is terminal; a slice redirects to its source at `slice.start + offset_within_part`.
Continue until terminal, then materialize that item into the requested result.
Do not expand an ancestor array and transplant its slices into each descendant.

```text
A = [0, 2, 3]
B = [1, slice(A, 1, 3), 4]
view(B) = [1, pointer(A, 1), pointer(A, 2), 4] => [1, 2, 3, 4]
```

Use an explicit stack/iteration for deep chains, memoize terminal pointers and
loaded descriptors within bounded caches, and share ranges where useful. Resolve
only requested positions; compaction can make entire ancestor prefixes unnecessary.
Pointers can be processed incrementally instead of allocating all of them at once.
Cache/index parent views or ranges to avoid repeated long-chain walks: pointers
alone do not guarantee linear metadata traversal. Physical reads may include extra bytes, but unrelated message payloads need not
be materialized. Detect identity/range errors and active-path cycles. A streamed
result that later fails is an incomplete input, never a successful partial history.

A fresh cache can replay source SpanOps, load the requested definition and follow
pointers, or accept an independent snapshot. Persisted indexes/derived offsets are
optional accelerators; data and definitions must remain recoverable. Readback has
the same meaning locally and on the backend, which may resolve it for an SDK.

## Delivery, retention, and queries

Make definitions available before dependent operations, or resolve a batch in
dependency order. Persist accepted progress only after data is recoverable. Keep
actual pending values/dependencies for retry or repair; queued is not acknowledged.
Existing SpanOp ordering, merge, deduplication, and route acknowledgements apply.
Replaying a definition is idempotent but does not itself deduplicate span updates.

Keep retained inputs reconstructable even if source spans are deleted or absent
from query pages. Unload payloads only when a retained copy can supply them; release
unused roots under normal retention/authorization/erasure rules. Compaction is not
erasure. Storage layout and checkpoint frequency are implementation choices.

Ordinary queries, predicates, search, scoring, and exports see complete logical
inputs for both full and tagged rows. Compact exports use the same tagged input,
with known dependencies or fresh literal snapshots so extra source spans need not
appear as results. Returning every expanded history can still be quadratic in
response bytes; compact reporting does not change provider token/cache metrics.
[OTel's delta-input proposal](https://github.com/open-telemetry/semantic-conventions-genai/issues/364)
can be adapted when its ordering/content assumptions hold; ordinary OTel consumers
continue receiving their established complete-message format.

Tests cover direct items, nested slices/pointers, compaction, branches, cold reads,
replay, snapshots, and invalid state. Implementations additionally test real crash
boundaries and measure CPU, memory, wire bytes, storage, and query latency.

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
