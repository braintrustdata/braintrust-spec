# History snapshots and deltas

Use the snapshot/append-only delta model in
[OTel proposal #364](https://github.com/open-telemetry/semantic-conventions-genai/issues/364).
Full reporting remains the default. Delta reporting is an option; slice support
is future work. The upstream attribute is proposed, not an adopted OTel standard.

## Fields

| Meaning | OTel attribute | Braintrust-native span field |
| --- | --- | --- |
| Complete input / checkpoint | `gen_ai.input.messages` | `input` |
| New messages since the preceding request | `gen_ai.input.messages_delta` | `input_delta` |
| Current response | `gen_ai.output.messages` | `output` |
| Conversation stream | `gen_ai.conversation.id` | `metadata["gen_ai.conversation.id"]` |

Native names are this spec's binding of the OTel semantics, not additional upstream
attributes. Use each integration's established message schema consistently between
full inputs and deltas; OTel adapters preserve the OTel message schema. Arbitrary
native object/scalar inputs continue full reporting. Do not discard provider fields.
There are no custom history wrappers, sequence IDs, or slice objects in this model.

A request carries either a full input or a delta, never both. Output is unchanged.
An absent field is not an empty array. Preserve message order, repeated messages,
reasoning, attachments, JSON types, numeric precision, and content-capture policy.

## Reporting policy

In full mode, report every complete input without retaining a comparison history
beyond ordinary pending delivery data. In delta mode, retain the preceding captured
input and response per active conversation stream. Apply redaction, customizers,
provider mapping, and attachment handling before comparison; freeze captured data
rather than retaining mutable application objects.

Let `I` be the preceding effective input and `O` its captured response messages.
If `I + O` is an exact prefix of the current input, report only the remaining
messages as `input_delta`. The receiver reconstructs `I + O + input_delta`, as
suggested by the OTel proposal. Deltas are per preceding request, not a growing
cumulative tail repeated since the last checkpoint. Never infer a response from
another request or append an unselected response candidate.

Otherwise report the complete current input as a checkpoint. This includes the
first request, compaction, truncation, prompt/history edits, regeneration without
the previous response, unknown/changed output, ambiguous ordering, and cache loss.
This profile always starts with a full checkpoint, although upstream also permits
putting the initial full input in the first delta. Only emit a delta when its
captured predecessor input/output are known and the exact prefix check succeeds.
Unknown or disabled content must not be invented to make a delta work.

For example, the first native span is a checkpoint:

```json
{
  "id": "request-1",
  "metadata": {"gen_ai.conversation.id": "conversation-A"},
  "input": [{"role": "user", "content": "Hello"}],
  "output": [{"role": "assistant", "content": "Hello!"}]
}
```

Its successor can report only the new user message:

```json
{
  "id": "request-2",
  "metadata": {"gen_ai.conversation.id": "conversation-A"},
  "input_delta": [{"role": "user", "content": "Tell me more"}],
  "output": [{"role": "assistant", "content": "More detail"}]
}
```

The second logical input is `[user("Hello"), assistant("Hello!"), user("Tell me more")]`.
An empty delta is valid when the complete preceding context is reused unchanged.

## Conversation identity and forks

`gen_ai.conversation.id` identifies a stream, not the chronological order of all
spans in a trace. Use a stable ID from the source/application that owns conversation
history. Do not invent an observer-local UUID, trace ID, or content hash when no
conversation identity is available; use full reporting instead. This follows the
[OTel conversation-ID guidance](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/registry/attributes/gen-ai.md).

When the application/session manager creates a fork as a new conversation stream,
it assigns a new stable conversation ID. The first recorded request in that branch
contains its complete effective input, including inherited context; later requests
may use deltas within the branch. The original keeps its ID. Preserve fork lineage
through existing trace relationships or metadata; a new ID alone does not encode it.
Resume the same branch with its stable ID, using another checkpoint if the cache
is unavailable. Compaction by itself does not require a new conversation ID.

If the source keeps multiple branches under one ID and no existing correlation
makes each predecessor unambiguous, keep full reporting for those streams. A
checkpoint at a fork does not by itself disambiguate subsequent interleaved deltas.
The upstream proposal does not define branch/predecessor metadata; that remains an
extension point, not something to infer from timestamps or generic span parentage.

## Optional state and readback

Bound cached bytes and active conversations. Eviction, restart, or switching into
delta mode starts a fresh checkpoint; switching to full mode releases comparison
state. SDKs need no disk or backend read endpoint to support this policy. Coding
agents may persist their active state in the existing SQLite/journal storage, but
recovering it is an optimization, not a prerequisite for capture or reporting.
Full-array comparison still scans history; enabling deltas has a memory/CPU cost.

To reconstruct a request, start at its latest checkpoint, then apply each subsequent
request's captured predecessor output and input delta in causal conversation order.
A new checkpoint replaces that context and needs no earlier messages. Preserve the
captured versions used by descendants; later mutations of a source span must not
silently change an already reconstructed input.

Enable deltas only on complete, ordered streams with compatible capture/sampling
and delivery behavior. Missing checkpoints, predecessor outputs, or ordering must
produce an explicit unresolved-history result, never partial or guessed input.
A producer that knows a record was lost restarts with a checkpoint. Repeated span
updates must not append the same delta twice; existing reporting IDs, merge rules,
replay cursors, and acknowledgements continue to apply. Preserve pending data until
ordinary delivery requirements are met; hook capture does not wait for replay.

Backend queries, filters, scoring, UI, and ordinary exports observe complete logical
inputs for both full and delta rows. Resolve dependencies outside the result page,
and keep retained descendants reconstructable when source rows are removed.
Storage/indexing and read caches are separate concerns. Requesting every expanded
input may still produce quadratic response bytes; telemetry compression does not
change model token/cache metrics. Backend support is deployed before clients;
there is no runtime negotiation introduced here.

## Possible future work: slices

A later, mutually exclusive input attribute could describe new items plus ranges
of the explicitly identified predecessor's **materialized history**. This could
avoid resending retained content after compaction/editing while preserving existing
snapshot/delta meanings. Its field name and wire shape are intentionally undefined.

That extension must specify predecessor/version correlation (including forks),
range validation, readback, retention, and a full-snapshot fallback for readers
without slice support. A receiver must not silently ignore an unknown slice field
and treat its messages as an append delta. Add it only if measured snapshot traffic
justifies the extra complexity; initial implementations need no slice machinery.

# SDK support

```yaml
id: history-sequences
name: History snapshots and deltas
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
