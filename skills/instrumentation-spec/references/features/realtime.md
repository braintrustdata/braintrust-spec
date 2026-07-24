# Realtime and Live APIs

This document defines Braintrust instrumentation for long-lived bidirectional
model sessions over WebSocket, WebRTC, or equivalent transports. Examples
include OpenAI Realtime and Google GenAI Live.

Realtime transport events are not spans by themselves. Instrumentation
normalizes them into a session `task` span with child `llm` spans for model
responses.

## Span tree

```text
task  <provider>.realtime.session
├── llm  <provider>.realtime.response
├── llm  <provider>.realtime.response
└── ...
```

An integration emits `tool` spans only when it observes the actual tool
execution. Merely receiving a tool call or sending a tool response does not
prove that execution occurred.

No span may be created for an individual audio, video, text, control, or usage
event.

## Logical session span

Create one parent `task` span for one logical provider session.

The session span starts immediately before the connection attempt. It remains
open across reconnects when the provider and SDK explicitly resume the same
logical session. It ends when:

- the application closes the session without resumption
- the provider permanently closes or expires the session
- a fatal transport or provider error prevents continuation
- the SDK abandons reconnection

A new connection without a verified provider resumption relationship starts a
new session span.

### Session input

The canonical parent input is:

```ts
type RealtimeSessionInput = {
  instructions?: string;
  input_modalities?: Array<"text" | "audio" | "image" | "video">;
  output_modalities?: Array<"text" | "audio" | "image" | "video">;
  voice?: string;
  tools?: unknown[];
};
```

Tool definitions follow the canonical tool schema in the instrumentation
guide. Unknown session configuration fields **MUST NOT** be captured.

### Session output

```ts
type RealtimeSessionOutput = {
  status: "closed" | "expired" | "failed";
  completed_turns: number;
  interrupted_turns: number;
};
```

The counters include only child response spans that reached a corresponding
terminal state. Cancelled responses are not counted as completed or
interrupted.

### Session metadata and secrets

The following realtime-specific metadata keys are allowed:

- `session_id`
- `response_id` (response spans only)
- `input_modalities`
- `output_modalities`
- `voice`

The normal `model` and `provider` fields remain required. Provider session IDs
are treated as opaque correlation identifiers.

Instrumentation **MUST NOT** capture:

- API keys or authorization headers
- ephemeral client tokens or client secrets
- provider resumption handles
- signed connection URLs containing credentials
- raw WebSocket/WebRTC handshake headers

Token/client-secret creation is not a model execution and **MUST NOT** produce
an `llm` span. If an SDK independently traces that operation, it may use a
`task` span only if all credentials and secret-bearing URLs are omitted.

## Response spans

Create one child `llm` span per provider model response. The canonical span
name is `<provider>.realtime.response`.

Start a response span at the earliest event the SDK can reliably associate
with the response:

- when the application explicitly requests a response
- when a user turn is committed and automatic response generation is enabled
- when the provider announces a response before either client event is
  observable

The span ends on exactly one terminal state:

- `completed`
- `interrupted`
- `cancelled`
- `failed`

Provider response IDs go in `metadata.response_id`. Item and call IDs remain in
the canonical output objects that they identify. Concurrent or interleaved
events **MUST** be routed by these provider identifiers rather than arrival
order alone.

### Response input

The input contains the complete user turn or conversation items supplied for
that response, using canonical messages and media parts. Text and media chunks
are accumulated in order.

Inbound audio and video bytes **MUST** be reconstructed into per-turn
attachments when the format and bytes are observable. Instrumentation
**MUST NOT** create one attachment per transport chunk.

Tool results sent to the provider are normal tool-result input items. They use
the existing tool-result message contract.

### Response output

```ts
type RealtimeResponseOutput = {
  status: "completed" | "interrupted" | "cancelled" | "failed";
  content: MediaPart[];
  tool_calls?: unknown[];
};
```

Text and transcripts use text parts. Audio, image, and video output use image
or file parts with attachment references. Tool calls use the canonical
completion-API tool-call shape.

The output contains only bytes and text delivered to the application before
the terminal event. On interruption or cancellation, partial delivered output
is retained and the discarded undispatched remainder is not fabricated.

`failed` responses also populate the span's top-level `error`. Interruption and
cancellation are expected lifecycle outcomes and **MUST NOT** populate
top-level `error` unless a separate provider or transport error occurred.

## Media and transcript aggregation

Instrumentation **MUST**:

- preserve event order within each response item
- concatenate transcript/text deltas in provider-defined order
- aggregate binary media into attachments
- preserve compact MIME type, byte size, and provider media identifiers when
  reported

If a response includes both transcript and audio, keep both. The transcript is
not a substitute for the requested media artifact.

## Tool calls

Tool definitions are captured on the session input and on individual LLM spans
when the available tool set changes.

A provider tool-call event is part of the response span output. A later tool
response is part of the next response span's input.

Create a child `tool` span only when the integration or framework:

1. invokes the tool implementation, and
2. can observe its input, output/error, and lifetime.

Pending tool calls cancelled by an interruption remain in the LLM output with
their provider cancellation status when available. Instrumentation **MUST
NOT** create failed tool spans for calls that never executed.

## Reconnection and resumption

Reconnects belong to the existing session span only when the provider confirms
that the new connection resumes the previous logical session. Control events
such as go-away warnings or session-resumption updates do not create spans.

If reconnection fails permanently, end the parent with `status = "failed"` and
populate top-level `error`. Any active child response also ends as `failed`
with its delivered partial output retained.

If the provider expires the logical session normally, use
`status = "expired"` without top-level error. Any active response ends as
`cancelled`, retains delivered partial output, and does not receive a
top-level error unless the provider also reported one.

## Metrics

Each response span records usage from its terminal usage event:

- `tokens`
- `prompt_tokens`
- `completion_tokens`
- `prompt_audio_tokens`
- `completion_audio_tokens`
- `completion_image_tokens`

Missing provider values are omitted rather than estimated.

`time_to_first_token` is measured from the response-span start to the first
content-bearing event delivered for that response. Text, audio, image, and
video content all qualify. Handshake, acknowledgement, rate-limit, session,
usage-only, and other control events do not qualify.

The parent task span may aggregate token metrics across completed, interrupted,
cancelled, and failed child responses when their usage was reported. It
**MUST NOT** infer missing child usage.

## Binary streams and instrumentation failure

Realtime media observation follows
[Attachments](attachments.md#binary-output-values-and-streams).
Instrumentation **MUST NOT** change transport backpressure, ordering,
cancellation, or application-visible errors to obtain trace data.

If media bytes cannot be observed safely, retain transcript and compact media
metadata, omit the unavailable attachment, and export the span. This is an
instrumentation limitation, not a provider error.

## Required implementation scenarios

SDK implementations should cover these scenarios in their own tests:

| Scenario | Expected result |
| --- | --- |
| Completed text/audio response | One child span contains transcript, audio attachment, usage, and time to first content. |
| User interruption | Delivered media is retained, status is interrupted, and top-level error is absent. |
| Explicit cancellation | Status is cancelled and partial delivered output is retained. |
| Fatal transport failure | Active response and session spans fail while retaining safe partial output. |
| Verified resumption vs unrelated reconnect | Resumption keeps one parent; an unrelated connection starts a new parent. |
| Interleaved responses | Events are correlated by response/item identifiers rather than arrival order alone. |
| Tool call and later tool response | They appear in LLM output/input without a fabricated execution span. |
| Observed tool execution | Exactly one child tool span captures execution input, output/error, and lifetime. |
| Secret creation and connection setup | No credentials, secret URLs, or resumption handles are captured. |
