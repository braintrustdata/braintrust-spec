# Tool approval metadata

This spec defines a small metadata convention for agent tool spans to identify
whether execution was approved or denied.
Execution failure is represented by the span's top-level `error` field, not by
this metadata enum.

## Scope

Tool approval metadata belongs on completed `tool` spans when the integration
can reliably determine whether that specific tool interaction was approved or
denied. This includes pre-execution rejections only when the agent exposes a
concrete denial signal that can be tied to the specific tool interaction.

If the integration cannot reliably determine the approval state, omit
`metadata.tool_approval`.

Do not add `tool_approval` to `span_attributes`. Tool spans continue to use
`span_attributes.type = "tool"` and `span_attributes.name` for the tool or
function name.

## Metadata

| Field | Type | Required | Semantics |
| --- | --- | --- | --- |
| `metadata.tool_approval` | string | SHOULD when known | Low-cardinality approval state for the completed tool interaction. |

`metadata.tool_approval` MUST be one of:

| Value | Semantics |
| --- | --- |
| `approved` | The tool request was approved for execution. |
| `denied` | The tool request was rejected before execution. |

A tool span MUST have at most one `metadata.tool_approval`.

The top-level `error` field indicates that a span failed. Failed tool calls are
identified by `span_attributes.type = "tool"` and a non-null `error` value.
Instrumentation MUST NOT use `metadata.tool_approval` to encode execution
success or failure.

The exact contents of `error` are intentionally unspecified here beyond the
backend contract that `error` is a valid JSON value.

## Classification rules

Use `approved` when the tool request was allowed to execute. If an approved
tool later fails, keep `metadata.tool_approval = "approved"` and set the
top-level `error` field to a valid JSON value.

Use `denied` only when the tool did not execute because the agent exposed a
concrete permission, policy, user, or hook denial for that tool interaction. Do
not infer rejection from a missing execution event alone.

Do not classify approval prompts themselves. Spans represent completed
interactions, not streams of intermediate events.

## Wire format examples

### Approved tool

```json
{
  "span_attributes": {
    "name": "get_weather",
    "type": "tool"
  },
  "metadata": {
    "tool_name": "get_weather",
    "tool_call_id": "call_1",
    "tool_approval": "approved"
  }
}
```

### Tool ran and failed

```json
{
  "span_attributes": {
    "name": "search_inventory",
    "type": "tool"
  },
  "metadata": {
    "tool_name": "search_inventory",
    "tool_call_id": "call_2",
    "tool_approval": "approved"
  },
  "error": "Inventory service timed out"
}
```

### Tool rejected before execution

```json
{
  "span_attributes": {
    "name": "send_email",
    "type": "tool"
  },
  "metadata": {
    "tool_name": "send_email",
    "tool_call_id": "call_3",
    "tool_approval": "denied"
  }
}
```

### Approved tool request that failed

```json
{
  "span_attributes": {
    "name": "update_ticket",
    "type": "tool"
  },
  "metadata": {
    "tool_name": "update_ticket",
    "tool_call_id": "retry",
    "tool_approval": "approved",
    "permission": {
      "approval": "approved_once",
      "justification": "Ticket update requires confirmation"
    }
  },
  "error": "Ticket service rejected the update"
}
```
