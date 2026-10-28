# Turn-scoped correlation IDs

SDKs and instrumentation MAY adopt `metadata.turn_span_id` to group a user
turn's spans for cost and token aggregation. Adoption is optional.

`span_parents` records only immediate parents. A shared turn ID allows queries
to select all of a turn's descendants without walking the span tree.

## Convention

`metadata.turn_span_id` is a string containing the owning user turn's Braintrust
`span_id`. Implementations adopting this convention MUST:

- Set it to the turn's own `span_id` on the user turn span.
- Use that same ID on all spans belonging to the turn, including LLM calls,
  tools, subagents, and their descendants. Nested turns and continuations retain
  the owning user turn's ID.
- Use a new user turn's own span ID for that turn's activity.
- Omit it on spans outside a turn, such as a session root or session-level
  compaction.

Existing `span_parents` and `root_span_id` semantics remain unchanged. This
convention defines no cross-service propagation mechanism or requirement.

## Example

Coding-agent plugins are the main use case and
[reference implementation](https://github.com/braintrustdata/braintrust-coding-agent-plugins/pull/163).
Their tracing daemon stamps the owning user turn's ID across client-specific
spans, including subagents, child sessions, continuation turns, and LLM spans.

| Span ID | Immediate parent | `metadata.turn_span_id` |
| --- | --- | --- |
| `session-1` | — | omitted |
| `turn-1` | `session-1` | `turn-1` |
| `subagent-1` | `turn-1` | `turn-1` |
| `llm-1` | `subagent-1` | `turn-1` |
| `turn-2` | `session-1` | `turn-2` |

For per-turn cost and token totals, group LLM spans by `metadata.turn_span_id`,
excluding spans where it is absent. Avoid also summing parent rollup metrics,
which can double-count the same usage.

# SDK support

```yaml
id: turn-scoped-correlation-ids
name: Turn-scoped correlation IDs
category: Tracing
support:
  turn-span-id:
    dotnet: "no"
    go: "no"
    java: "no"
    js: "no"
    python: "no"
    ruby: "no"
    rust: "no"
```
