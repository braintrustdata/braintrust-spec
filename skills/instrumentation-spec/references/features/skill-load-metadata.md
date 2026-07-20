# Skill load metadata

This spec defines the metadata Braintrust integrations should emit when a coding
agent loads or explicitly requests a skill during a conversation. The goal is to
make skill participation queryable from trace data so backend analysis can
correlate loaded skills with conversation outcomes.

## Scope

There are two distinct skill attribution surfaces:

- **Observed loads**: agent, model, or harness actions that make a
  skill's instructions, scripts, or resources available for the current
  generation or turn. These are usually implicit, but may be explicitly sourced
  when an explicit user request materializes as a skill-load tool call.
- **Explicit parsed requests**: user messages that directly request one or more
  skills, such as slash commands, `$skill` syntax, or other agent-specific
  explicit skill invocation syntax.

These surfaces intentionally use different span identities and metadata shapes.
Observed loads are represented by `tool` spans with `metadata.tool_kind =
"skill"` and singular `skill_*` fields. Explicit parsed requests are represented
on the message or turn span that contains the request, using plural `loaded_*`
fields because one message may reference multiple skills. When an explicit
request also produces a real skill-load tool span, emit both surfaces: the
message/turn span records what the user requested, and the tool span records what
content was actually loaded.

Examples of observed loads include:

- A native skill tool call, such as a `Skill` or `skill` tool.
- A read of a `SKILL.md` file performed by the model or harness.
- A read through an orchestrator skill API, such as `skills.read`.
- A skill-owned script execution that necessarily loads or runs that skill.

Do not emit either surface for speculative relevance, inventory exposure, or
client-side guesses that a skill may have been useful. Inventory capture can use
separate metadata, but it is not a skill load or explicit request.

## Skill Load Tool Spans

Observed skill loads MUST be represented on `tool` spans.

| Field | Type | Required | Semantics |
| --- | --- | --- | --- |
| `span_attributes.type` | string | MUST | Set to `"tool"`. |
| `span_attributes.name` | string | SHOULD | Prefer `skill: <skill_name>` when the skill name is known. Otherwise use a stable tool span name. |
| `metadata.tool_name` | string | MUST | Preserve the raw tool name observed from the agent, such as `"read"`, `"Skill"`, `"skill"`, or `"exec_command"`. |
| `metadata.tool_kind` | string | MUST | Set to `"skill"` for observed skill-load spans. |

Preserving `metadata.tool_name` keeps the raw agent event inspectable and avoids
assigning cross-agent semantics to tool-name strings. Use
`metadata.tool_kind = "skill"` as the canonical discriminator for observed skill
loads, including when the underlying event was a generic read or command tool.

### Metadata

| Field | Type | Required | Semantics |
| --- | --- | --- | --- |
| `metadata.skill_name` | string | SHOULD when known | Stable skill identifier or directory/package name. |
| `metadata.skill_path` | string | SHOULD for path-based loads | File or resource path that caused the load, such as a `SKILL.md` path or skill script path. |
| `metadata.skill_load_trigger` | string | MAY | Selection cause for the observed load. Defaults to `"implicit"` when omitted. Set to `"explicit"` only when the integration knows this load was caused by an explicit user skill request. |

`metadata.skill_load_trigger` MUST be one of:

| Value | Semantics |
| --- | --- |
| `implicit` | The agent, model, or harness selected and loaded the skill from conversation context without a direct user command for that skill. This is the default when the field is omitted. |
| `explicit` | The observed load was caused by a direct user skill request, such as a slash command, `$skill` syntax, or other agent-specific explicit skill invocation. |

If the integration observes a real skill load but cannot reliably link it to an
explicit user skill request, it SHOULD omit `metadata.skill_load_trigger`. The
missing field is interpreted as `"implicit"`.

If an integration cannot determine the skill name but can still observe a real
skill load, it MUST still emit `metadata.tool_kind = "skill"` and SHOULD use a
stable skill span name such as `"skill"`.

When the observed agent event exposes the loaded skill content, integrations
SHOULD record that content using the normal tool span `output` field. For
example, a `SKILL.md` read span's `output` should contain the file contents, and
a native skill tool span's `output` should contain the loaded skill instructions
or response text exposed by the harness. Do not duplicate loaded skill content
into metadata; metadata should identify the skill load, while `output` preserves
the content that was loaded.

## Explicit Request Message Spans

Explicit parsed skill requests MUST be represented on the message or turn span
that contains the explicit user request. Use the narrowest span available in the
integration:

- If the integration has user-message spans, attach explicit request metadata to
  the user-message span.
- If the integration only has turn/task spans, attach explicit request metadata
  to the turn/task span for that user message.
- Do not attach plural explicit request metadata to a skill-load tool span. The
  tool span records that a skill was actually loaded; the message or turn span
  records the set of skills the user explicitly requested.
- If the explicit request causes a skill-load tool span, mark that tool span with
  `metadata.skill_load_trigger = "explicit"`.

The exact span type depends on the integration's trace model. Existing coding
agent integrations commonly use `task` spans for turns. Integrations with
message-level spans may use their local message span type. The required identity
is the metadata, not a single universal `span_attributes.type` value.

### Metadata

| Field | Type | Required | Semantics |
| --- | --- | --- | --- |
| `metadata.loaded_skill_names` | string[] | MUST | Skill names explicitly requested by this message or turn. |
| `metadata.loaded_skills` | object[] | MUST | Structured records for the explicitly requested skills. |

Each object in `metadata.loaded_skills` MUST use this shape:

| Field | Type | Required | Semantics |
| --- | --- | --- | --- |
| `name` | string | MUST | Stable skill identifier parsed from the explicit request. |

Do not emit confidence fields. These fields record parsed explicit requests or
observed implicit loads, not probabilistic attribution.

## Detection rules

Integrations should prefer direct skill-load signals from the coding agent or
harness. When no native skill-load signal exists, integrations may normalize
read-based loads if the observed event identifies skill content.

For path-based detection:

- A path ending in `SKILL.md` is sufficient to normalize the event as a skill
  load.
- The skill name SHOULD be inferred from the parent directory of `SKILL.md`.
- The observed path SHOULD be recorded as `metadata.skill_path`.

For script-based detection:

- A command or tool call that executes a file under a skill package's `scripts/`
  directory MAY be normalized as a skill load.
- The skill name SHOULD be inferred from the package directory when reliable.
- The script path SHOULD be recorded as `metadata.skill_path`.

When an integration cannot determine the skill name but can still observe a real
skill load, it MUST still emit `metadata.tool_kind = "skill"` and omit
`metadata.skill_name`.

## Wire format examples

### Implicit Native Skill Tool

```json
{
  "span_attributes": {
    "name": "skill: review",
    "type": "tool"
  },
  "output": "Review the current diff for correctness bugs...",
  "metadata": {
    "tool_name": "Skill",
    "tool_kind": "skill",
    "skill_name": "review"
  }
}
```

### Explicit-Sourced Skill Tool

```json
{
  "span_attributes": {
    "name": "skill: review",
    "type": "tool"
  },
  "output": "Review the current diff for correctness bugs...",
  "metadata": {
    "tool_name": "Skill",
    "tool_kind": "skill",
    "skill_name": "review",
    "skill_load_trigger": "explicit"
  }
}
```

### Implicit SKILL.md Read

```json
{
  "span_attributes": {
    "name": "skill: review",
    "type": "tool"
  },
  "output": "---\nname: review\n---\n\nReview the current diff...",
  "metadata": {
    "tool_name": "read",
    "tool_kind": "skill",
    "skill_name": "review",
    "skill_path": "/home/user/.agents/skills/review/SKILL.md"
  }
}
```

### Explicit Multi-Skill Message

```json
{
  "span_attributes": {
    "name": "user message",
    "type": "task"
  },
  "metadata": {
    "loaded_skill_names": ["review", "security-review"],
    "loaded_skills": [
      {
        "name": "review"
      },
      {
        "name": "security-review"
      }
    ]
  }
}
```

## Query guidance

The canonical filter for observed skill-load tool spans is:

```text
span_attributes.type = "tool" AND metadata.tool_kind = "skill"
```

For skill-load tool spans, treat missing `metadata.skill_load_trigger` as
`"implicit"`.

The canonical filter for explicit parsed skill requests is:

```text
metadata.loaded_skill_names IS NOT NULL OR metadata.loaded_skills IS NOT NULL
```

To identify all skill participation in a conversation, query both surfaces:

- observed loads from skill-load tool spans, grouped by
  `metadata.skill_name`; use `metadata.skill_load_trigger` to split explicit
  sourced loads from implicit/default loads
- explicit parsed requests from message or turn spans, grouped by
  `metadata.loaded_skill_names` or `metadata.loaded_skills[].name`

Message or turn spans with `loaded_*` metadata are explicit parsed requests.
Skill tool spans are observed loads; they are implicit by default unless
`metadata.skill_load_trigger = "explicit"` says the load was sourced from an
explicit request. To inspect the raw load event, use
`metadata.tool_name`.
