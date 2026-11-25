# Audio traces

This document defines audio trace schema version `3.2.0` for voice conversations, covering both the conversation users experience and the operations that produce it.

## Overview

A `session` span contains the conversation, recordings, and shared audio timeline. Speech spans describe audio activity; transcription, end-of-utterance waiting, model-response, synthesis, and tool spans describe the associated operations. Links associate these activities, while integration-specific spans and `contrib.<integration>.*` metadata capture additional framework behavior.

The schema covers three common conversation patterns:

- **Cascade:** STT transcribes user speech, a text-based LLM responds, and TTS speaks the response.
- **Half-cascade:** A model receives audio and emits text for a separate TTS service.
- **Full-duplex:** A model receives and generates audio, listening and speaking concurrently.

## Trace examples

### Cascade

Cascade uses STT to hear the user, an LLM to respond, and TTS to speak. Turns group speech spans with STT, model, and TTS work.

```text
User audio → STT → LLM → TTS → Agent audio

Time (s) 0         1         2         3         4         5
         |---------|---------|---------|---------|---------|
Agent    ___________________________________/|\|/|\|/|\|/|\
User     __________/|\|/|\|/|______________________________
```

```text
session [S] : task                              0.0–5.0s
│  audio.schema.version: "3.2.0"
│  audio.sources: session-input, agent-output
│  audio.participants: caller-connection (type: user), agent-connection (type: agent)
│  audio.speakers: speaker-1 (type: user)
│  audio.segments: part-0 → call.ogg; session-input → channel 0, agent-output → channel 1
│  audio.timeline.origin_unix_ms: shared session epoch
│
├─ user_turn [UT1] : task                       1.0–2.5s
│  │  metadata: { "turn.id": "UT1" }
│  │  input: [{ role: "user", content: "Where is my order?" }]
│  │  audio.selections: [1.0–2.0s]
│  ├─ user_speech [U1] : task                   1.0–2.0s
│  │    audio.source_id: session-input
│  │    audio.selections: [1.0–2.0s]
│  ├─ stt [ST1] : task                         1.0–2.3s
│  │  │  output: "Where is my order?"
│  │  │  links: transcribes → U1
│  │  └─ Transcription [ST1L] : llm             1.0–2.3s  # From OpenAI SDK instrumentation
│  └─ eou_wait [E1] : task                     2.0–2.5s
│       metadata: { "turn.id": "UT1", "eou.outcome": "committed" }
│       audio.source_id: session-input
│
└─ agent_turn [AT1] : task                      2.5–5.0s
   │  metadata: { "turn.id": "AT1", "turn.reply_to": "UT1" }
   ├─ llm_response [M1] : task                 2.5–3.0s
   │  │  input: "Where is my order?"
   │  │  output: "It arrives Friday."
   │  │  links: uses_context → ST1
   │  └─ Chat Completion [M1L] : llm           2.5–3.0s   # From OpenAI SDK instrumentation
   ├─ tts [TT1] : task                         3.0–4.0s
   │  │  input: "It arrives Friday."
   │  │  links: generated_by → M1
   │  └─ Speech [TT1L] : llm                   3.0–4.0s.  # From OpenAI SDK instrumentation
   └─ agent_speech [A1] : task                  3.5–5.0s
        output: "It arrives Friday."
        audio.source_id: agent-output
        audio.selections: [3.5–5.0s]
        links: generated_by → TT1
```

```text
[00:01.0] User:  Where is my order?              [ST1 via U1]
[00:03.5] Agent: It arrives Friday.             [A1]
```

### Half-cascade

Half-cascade feeds audio directly to a realtime model, which emits text for a separate TTS service. This example has TTS but no separate STT or turn containers.

```text
User audio → Realtime model → Text → TTS → Agent audio

Time (s) 0         1         2         3         4         5
         |---------|---------|---------|---------|---------|
Agent    ___________________________________/|\|/|\|/|\|/|\
User     __________/|\|/|\|/|______________________________
```

```text
session [S] : task                              0.0–5.0s
│  audio.schema.version: "3.2.0"
│  audio.sources: session-input, agent-output
│  audio.participants: caller-connection (type: user), agent-connection (type: agent)
│  audio.speakers: speaker-1 (type: user)
│  audio.segments: part-0 → call.ogg; session-input → channel 0, agent-output → channel 1
│  audio.timeline.origin_unix_ms: shared session epoch
│
├─ user_speech [U1] : task                      1.0–2.0s
│    audio.source_id: session-input
│    audio.selections: [1.0–2.0s]
├─ transcript_received [TR1] : task            2.1s
│    output: "Where is my order?"
│    links: transcribes → U1
├─ llm_response [M1] : task                    2.0–3.0s
│  │  input: observed user audio / context
│  │  output: "It arrives Friday."
│  │  links: uses_context → U1
│  └─ livekit.llm_response [M1L] : llm         2.0–3.0s  # LiveKit owns the OpenAI Realtime client
│       metadata.model / provider: "gpt-realtime" / "openai"
│       metrics: { prompt_tokens: 1000, completion_tokens: 100, tokens: 1100,
│                  prompt_audio_tokens: 800, prompt_cached_tokens: 600, prompt_cached_audio_tokens: 500 }
│       metadata["contrib.livekit.cached_tokens"]: { audio_tokens: 500, text_tokens: 100 }
├─ tts [TT1] : task                            3.0–4.0s
│  │  input: "It arrives Friday."
│  │  links: generated_by → M1
│  └─ livekit.tts [TT1L] : llm                 3.0–4.0s  # TTS client has no known Braintrust integration
└─ agent_speech [A1] : task                     3.5–5.0s
     output: "It arrives Friday."
     audio.source_id: agent-output
     audio.selections: [3.5–5.0s]
     links: generated_by → TT1
```

```text
[00:01.0] User:  Where is my order?              [TR1 via U1]
[00:03.5] Agent: It arrives Friday.             [A1]
```

The 500 cached audio tokens are included in both the 800 audio tokens and the 600 cached tokens, all within the 1,000 prompt tokens.

### Duplex

A full-duplex model can listen and speak at the same time. The speakers can overlap. Links connect their utterances to model responses and tool work.

#### Turnless

This example has no turn containers because the framework does not establish them.

```text
User audio ──→ Model listening
               Model speaking ──→ Agent audio
               ↕ Tools

Time (s) 0     1     2     3     4     5     6     7     8     9     10
         |-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|
Agent    ______/|\|/|\|/|\|/|\|/|________________________/|\|/|\|/|\|
User     __________________/|\|/|\|/|\|/|\|/|\|/|\|__________________
Overlap                    <---->  3–4s
```

```text
session [S] : task                              0.0–10.0s
│  audio.schema.version: "3.2.0"
│  audio.sources: session-input, agent-output
│  audio.participants: caller-connection (type: user), agent-connection (type: agent)
│  audio.speakers: speaker-1 (type: user)
│  audio.segments: part-0 → call.ogg; session-input → channel 0, agent-output → channel 1
│  audio.timeline.origin_unix_ms: shared session epoch
│
├─ llm_response [M1] : task                    0.5–4.0s
│  │  output: "With leather interiors, we recommend…"
│  │  metadata: { "contrib.livekit.response_id": "B1" }
│  └─ livekit.llm_response [M1L] : llm         0.5–4.0s  # LiveKit owns the OpenAI GPT-Live client
│       metrics: { completion_tokens: 120, completion_audio_tokens: 100 }
├─ agent_speech [A1] : task                     1.0–4.0s
│    output: "With leather interiors, we recommend…"
│    links: generated_by → M1
│    audio.source_id: agent-output
│    audio.selections: [1.0–4.0s]
│    native interruption outcome: interrupted at 4.0s
├─ user_speech [U1] : task                      3.0–7.0s
│    audio.source_id: session-input
│    audio.selections: [3.0–7.0s]
├─ transcript_received [TR1] : task            7.0s
│    output: "Just the floors, please. The seats have covers."
│    metadata: { "contrib.livekit.item_id": "user-msg-1" }
│    links: transcribes → U1
├─ llm_response [M2] : task                    7.0–7.2s
│  │  input: "Just the floors, please. The seats have covers."
│  │  output.tool_calls: [{ id: "C1", name: "get_price", arguments: { service: "floors_only" } }]
│  │  links: uses_context → TR1
│  └─ livekit.llm_response [M2L] : llm         7.0–7.2s  # LiveKit owns the OpenAI GPT-Live client
├─ get_price [T1] : tool                       7.2–7.4s
│    input: { service: "floors_only" }
│    output: { price: 250, currency: "USD" }
│    metadata: { "gen_ai.tool.call.id": "C1" }
│    links: requested_by → M2
├─ llm_response [M3] : task                    7.4–9.0s
│  │  input: tool result C1: { price: 250, currency: "USD" }
│  │  output: "Got it. Floors only is $250."
│  │  metadata: { "contrib.livekit.response_id": "B2" }
│  │  links: consumes_tool_result → T1
│  └─ livekit.llm_response [M3L] : llm         7.4–9.0s  # LiveKit owns the OpenAI GPT-Live client
└─ agent_speech [A2] : task                     8.0–10.0s
     output: "Got it. Floors only is $250."
     audio.source_id: agent-output
     audio.selections: [8.0–10.0s]
     links: generated_by → M3
```

```text
[00:01.0] Agent: With leather interiors,                        [A1, part 1]
[00:03.0] User:  Just the floors, please. The seats have covers. [TR1 via U1]
[00:03.0] Agent: we recommend… [cut off at 4s]                   [A1, part 2]
[00:08.0] Agent: Got it. Floors only is $250.                    [A2]
```

The agent speaks continuously from 1–4s. The user starts talking over it at 3s. The transcript can split the agent’s words at that point while keeping one span, A1. That split can be added later.

#### Framework turns

In this example, framework turns group transcript events and can overlap. Speech and backend work have no framework-established turn membership and remain under the session. Transcript times describe receipt; speech selections describe intervals in the recording.

```text
session [S] : task                              0.0–7.0s
│  audio.schema.version: "3.2.0"
│  audio.sources: session-input, agent-output
│  audio.segments: part-0 → call.ogg; session-input → channel 0, agent-output → channel 1
│  audio.timeline.origin_unix_ms: shared session epoch
│
├─ pipecat.live [L1] : llm                      0.1–6.5s
│    audio.scope: "session"
│    metadata.model / provider: "gpt-live-1" / "openai"
│    metrics.usage_seconds: 6.25
├─ agent_speech [A1] : task                     1.0–2.0s
│    audio.source_id: agent-output
│    audio.selections: [1.0–2.0s]
├─ agent_turn [AT1] : task                      1.1–2.4s
│  │  metadata: { "turn.id": "AT1" }
│  └─ transcript_received [TR1] : task         1.1–2.4s
│       metadata: { "turn.id": "AT1" }
│       audio.source_id: agent-output
│       output: [{ role: "assistant", content: "How can I help?" }]
├─ user_speech [U1] : task                      1.5–3.0s
│    audio.source_id: session-input
│    audio.selections: [1.5–3.0s]
├─ user_turn [UT1] : task                       1.9–3.9s
│  │  metadata: { "turn.id": "UT1" }
│  └─ transcript_received [TR2] : task         1.9–3.9s
│       metadata: { "turn.id": "UT1" }
│       audio.source_id: session-input
│       output: [{ role: "user", content: "When does the store close?" }]
├─ llm_response [M1] : task                     3.7–4.4s
│  └─ pipecat.live.backend_response [M1L] : llm 3.7–4.4s
│       metadata.model / provider: <resolved backend model> / "openai"
│       metrics: { prompt_tokens: 800, completion_tokens: 100, tokens: 900 }
│       output: [{ role: "assistant", content: "We close at six." }]
├─ agent_turn [AT2] : task                      4.5–6.1s
│  │  metadata: { "turn.id": "AT2" }
│  └─ transcript_received [TR3] : task         4.5–6.1s
│       metadata: { "turn.id": "AT2" }
│       audio.source_id: agent-output
│       output: [{ role: "assistant", content: "We close at six." }]
└─ agent_speech [A2] : task                     4.6–6.2s
     audio.source_id: agent-output
     audio.selections: [4.6–6.2s]
```

The Live service owns its metered seconds; the backend operation owns its tokens and model identity. Metered seconds need not equal the span duration.

## Trace specification

The audio trace is rooted under a `session` span. This session span may be the root span, or it might be nested under another parent span.

```text
session : task [1]
│  metadata["audio.schema.version"]: "3.2.0"
│  metadata["audio.sources"]?: map<string, AudioSource>
│  metadata["audio.participants"]?: map<string, AudioParticipant>
│  metadata["audio.speakers"]?: map<string, AudioSpeaker>
│  metadata["audio.segments"]?: map<string, AudioSegment>
│  metadata["audio.timeline"]?: AudioTimeline
│
├─ user_speech : task [0..n]
│    input?: [{ role: "user", content: ... }]
│    metrics.start / end: speech interval
│    metadata["audio.source_id"]?: source ID
│    metadata["audio.participant_ids"]?: participant IDs
│    metadata["audio.selections"]?: selections by ID
│
├─ agent_speech : task [0..n]
│    output?: [{ role: "assistant", content: ... }]
│    metrics.start / end: speech interval
│    metadata["audio.source_id"]?: source ID
│    metadata["audio.participant_ids"]?: participant IDs
│    metadata["audio.speaker_ids"]?: speaker IDs
│    metadata["audio.selections"]?: selections by ID
│    links?: generated_by → llm_response or tts
│
├─ <session model operation> : llm [0..n]      optional: session-wide model execution, e.g. duplex
│    metadata["audio.scope"]: "session"
│    metrics: this model's usage, cost, and execution timing
│
├─ llm_response : task [0..n]
│  │  input?: observed context messages
│  │  output?: generated messages / tool calls
│  │  metadata.model / provider?: string
│  │  metrics.start / end: framework operation interval
│  │  links?: uses_context → speech / STT / transcript spans; consumes_tool_result → tools
│  ├─ <provider operation> or <framework>.llm_response : llm [0..n]
│  └─ <tool name> : tool [0..n]                 when owned by this operation
│       input?: arguments; output?: result
│       metadata["gen_ai.tool.call.id"]?: string
│       links?: requested_by → llm_response
│
├─ <tool name> : tool [0..n]                    alternative parent: session
│    input?: arguments; output?: result
│    metadata["gen_ai.tool.call.id"]?: string
│    links?: requested_by → llm_response
│
│  OPTIONAL STRUCTURE
│
├─ user_turn : task [0..n]                      framework-established grouping
│  │  input?: user messages reported for the turn
│  │  metadata["turn.id"]: this span_id
│  │  metadata["audio.selections"]?: selections by ID
│  ├─ user_speech [0..n]                        same common-core span
│  ├─ stt : task [0..n]
│  │  └─ <provider operation> or <framework>.stt : llm [0..n]
│  ├─ transcript_received : task [0..n]
│  ├─ eou_wait : task [0..n]
│  └─ <framework operation> [0..n]
│
├─ agent_turn : task [0..n]                     framework-established grouping
│  │  input?: user messages reported as prompting this turn
│  │  metadata["turn.id"]: this span_id
│  │  metadata["turn.reply_to"]?: user_turn span_id
│  ├─ agent_speech [0..n]                       same common-core span
│  ├─ transcript_received : task [0..n]
│  ├─ llm_response : task [0..n]                may also contain tool executions
│  │  └─ <provider operation> or <framework>.llm_response : llm [0..n]
│  ├─ <tool name> [0..n]                       alternative parent: turn
│  ├─ tts : task [0..n]
│  │  └─ <provider operation> or <framework>.tts : llm [0..n]
│  └─ <framework operation> [0..n]
│
├─ eou_wait : task [0..n]                       without a turn container
│    metrics.start / end: last speech end → outcome, or observation cutoff if unfinished
│    metadata["eou.outcome"]?: "committed" | "user_resumed" | "dropped"
│    metadata["audio.source_id"]?: source ID
│    metadata["audio.participant_ids"]?: participant IDs
│
├─ transcript_received : task [0..n]
│    output: recognized messages
│    metrics.start / end: receipt time
│    metadata["audio.source_id"]?: source ID
│    metadata["audio.participant_ids"]?: participant IDs
│    metadata["audio.speaker_ids"]?: speaker IDs
│    links?: transcribes → speech spans
│
├─ stt : task [0..n]                            without a turn container
│  │  metrics.start / end: recognition operation interval
│  │  output?: recognized user messages
│  │  metadata["audio.source_id"]?: source ID
│  │  metadata["audio.participant_ids"]?: participant IDs
│  │  metadata["audio.speaker_ids"]?: speaker IDs
│  │  metadata.model / provider?: string
│  │  links?: transcribes → speech spans
│  └─ <provider operation> or <framework>.stt : llm [0..n]
│
├─ tts : task [0..n]                            without a turn container
│  │  metrics.start / end: synthesis operation interval
│  │  input?: text; output?: generated text / audio
│  │  metadata["audio.speaker_ids"]?: speaker IDs
│  │  metadata.model / provider?: string
│  │  links?: generated_by → llm_response
│  └─ <provider operation> or <framework>.tts : llm [0..n]
│
└─ <framework operation> : task [0..n]           session, turn, or operation child
     native attributes under metadata["contrib.<framework>.*"]
```

## Span specification

### `session`

The whole call, including recordings and the shared audio timeline.

```text
span_attributes: { name: "session", type: "task" }
metadata["audio.schema.version"]: "3.2.0"
metadata["audio.sources"]?: map<string, AudioSource>
metadata["audio.participants"]?: map<string, AudioParticipant>
metadata["audio.speakers"]?: map<string, AudioSpeaker>
metadata["audio.segments"]?: map<string, AudioSegment>
metadata["audio.timeline"]?: AudioTimeline
```

**Example**

A 75-second order-support call with two users sharing a microphone, captured as stereo Opus/Ogg. The first segment is uploaded; the final segment is still uploading.

```js
// Metadata on the session span; attachments live in its input.audio map.
{
  "audio.schema.version": "3.2.0",
  "audio.sources": {
    "session-input": { label: "Agent input audio" },
    "agent-output": { label: "Agent audio" }
  },
  "audio.participants": {
    "meeting-room": { type: "user", label: "Meeting room connection" },
    "agent-connection": { type: "agent", label: "Agent connection" }
  },
  "audio.speakers": {
    "speaker-1": { type: "user", label: "Speaker S1" },
    "speaker-2": { type: "user", label: "Speaker S2" },
    "support-voice": { type: "agent", label: "Support voice" }
  },
  "audio.segments": {
    "part-0": {
      state: "ready",
      start_offset_ms: 0,
      duration_ms: 60000,
      attachment: { ref: "/input/audio/part-0" },
      mime_type: "audio/ogg",
      encoding: "opus",
      sample_rate_hz: 48000,
      channels: {
        "0": { sources: ["session-input"] },
        "1": { sources: ["agent-output"] }
      },
      attributes: { "opus.bitrate_bps": 64000 }
    },
    "part-1": {
      state: "pending",
      start_offset_ms: 60000,
      duration_ms: 15000,
      mime_type: "audio/ogg",
      encoding: "opus",
      sample_rate_hz: 48000,
      channels: {
        "0": { sources: ["session-input"] },
        "1": { sources: ["agent-output"] }
      },
      attributes: { "opus.bitrate_bps": 64000 }
    }
  },
  "audio.timeline": { origin_unix_ms: 1790000000000 }
}
```

### `user_turn`

A user turn identified by the framework. It can group several speech intervals and their recognition operations or transcript events.

- May include `input` containing the turn transcript when reported by the framework.
- May include `audio.selections` containing the turn’s speaking interval when reported by the framework. This covers first to last speech, including pauses, without extending to include processing after speech ends.

Turns are optional in every architecture, including duplex. Membership must be established by the framework; other speech and operations remain outside the turn. Turns may overlap and need not alternate between speakers.

```text
span_attributes: { name: "user_turn", type: "task" }
input?: user messages                         turn transcript reported by the framework
metadata["turn.id"]: string                   this turn’s span ID; also on its speech/operations
metadata["turn.incomplete"]?: boolean         on the turn if native completion is missing at shutdown
metadata["audio.selections"]?: map<string, Selection>
```

**Example**

```text
user_turn [UT1] : task    1.0–2.0s
  root_span_id: S
  span_parents: ["S"]
  input: [{ role: "user", content: "Where is my order?" }]
  metadata["turn.id"]: "UT1"
  metadata["audio.selections"]:
    selection-0: { start_offset_ms: 1000, end_offset_ms: 2000 }
```

### `agent_turn`

An agent turn identified by the framework. It can group transcript events, model responses, tools, and speech.

- May include `input` containing the user message that prompted the turn, when reported by the framework.
  - The input may also be typed text, without a preceding user turn.
- Optional in every architecture, including duplex. Membership and overlap follow the same rules as `user_turn`.

```text
span_attributes: { name: "agent_turn", type: "task" }
input?: user messages                         user input that prompted this turn
metadata["turn.id"]: string                   this turn’s span ID; also on its speech/operations
metadata["turn.reply_to"]?: string            user-turn span ID; omit when ambiguous
metadata["turn.incomplete"]?: boolean         on the turn if native completion is missing at shutdown
```

**Example**

```text
agent_turn [AT1] : task    2.0–5.0s
  root_span_id: S
  span_parents: ["S"]
  input: [{ role: "user", content: "Where is my order?" }]
  metadata["turn.id"]: "AT1"
  metadata["turn.reply_to"]: "UT1"
```

### `user_speech`

The observed audio component of user speech.

May include transcription text when its natively emitted with the speech in the same event. Otherwise, independently reported transcription is represented by a `stt` or `transcript_received` span, optionally linked to this span with `transcribes`.

```text
span_attributes: { name: "user_speech", type: "task" }
input?: user messages
metadata["audio.source_id"]?: string            source ID within the audio session
// Updates replace the participant list; include all known IDs.
metadata["audio.participant_ids"]?: string[]    participant IDs within the audio session
metadata["audio.selections"]?: map<string, Selection>
```

**Example**

```text
user_speech [U1] : task    1.0–2.0s
  root_span_id: S
  span_parents: ["UT1"]
  metadata["audio.source_id"]: "session-input"
  metadata["audio.participant_ids"]: ["caller-connection"]
  metadata["audio.selections"]:
    selection-0: { start_offset_ms: 1000, end_offset_ms: 2000 }
```

### `agent_speech`

The observed audio component of agent speech, representing audio actually played.

May reference the synthesized voice with `audio.speaker_ids` when its association with playback is known. Native interruption outcomes are optional; an unknown outcome is omitted, not `false`.

May include transcription describing the speech actually played, when provided by the framework. Generated text remains on the `llm_response` or `tts` span, which this span can reference with a `generated_by` link.

```text
span_attributes: { name: "agent_speech", type: "task" }
output?: assistant messages representing played speech
metadata["audio.source_id"]?: string            source ID within the audio session
// Updates replace the participant list; include all known IDs.
metadata["audio.participant_ids"]?: string[]    participant IDs within the audio session
metadata["audio.speaker_ids"]?: string[]        identified voices used for this speech
metadata["audio.selections"]?: map<string, Selection>
links?: generated_by → llm_response or tts
```

**Links**

| Type           | Target                  | Description                                 |
| -------------- | ----------------------- | ------------------------------------------- |
| `generated_by` | `llm_response` or `tts` | The target produced the audio being played. |

**Example**

```text
agent_speech [A1] : task    3.5–5.0s
  root_span_id: S
  span_parents: ["AT1"]
  metadata["audio.source_id"]: "agent-output"
  metadata["audio.participant_ids"]: ["agent-connection"]
  metadata["audio.speaker_ids"]: ["support-voice"]
  output:
    assistant: "It arrives Friday."
  links: generated_by → TT1
    context: traceId=TRACE, spanId=TT1, traceFlags=1
    attributes["braintrust.relationship.type"]: "generated_by"
```

### `eou_wait`

The wait to decide whether the user has finished their turn. Includes silence detection, transcription finalization, and turn analysis when they gate that decision.

- Represents an observed wait anchored to the end of user speech.
- A child of the owning `user_turn`, or `session` when turn membership is unknown.
- Repeated turn evaluations during the same pause belong to one wait. Resumed speech ends that wait; a later pause may have another.
- May overlap `stt` and `llm_response`. Model execution has its own spans and metrics.
- Detector spans have their own execution intervals, which may extend beyond the wait. Their parent is the wait, turn, or session according to framework-established ownership.

```text
span_attributes: { name: "eou_wait", type: "task" }
metrics.start: last speech end                 framework-reported or VAD-adjusted timestamp
metrics.end: turn decision, resumed speech, or abandonment
             observation cutoff when the outcome is unknown
metadata["turn.id"]?: string                   owning user-turn span ID
metadata["eou.outcome"]?: "committed" | "user_resumed" | "dropped"
metadata["eou.end_reason"]?: string            final condition permitting commitment
metadata["eou.speech_end_source"]?: "vad" | "stt" | "provider"
metadata["audio.source_id"]?: string
metadata["audio.participant_ids"]?: string[]
metadata["contrib.<integration>.*"]?: ...      strategy, configured delays, detector diagnostics
```

**Example**

The user pauses, continues, then finishes. A speculative response starts before the final decision.

```text
session [S] : task
│
├─ user_turn [UT1] : task                       1.0–4.0s
│  │  metadata: { "turn.id": "UT1" }
│  │  audio.selections: [1.0–3.5s]             speaking interval, including the pause
│  ├─ user_speech [U1] : task                  1.0–2.0s
│  ├─ eou_wait [E1] : task                     2.0–2.3s
│  │  │  metadata: { "turn.id": "UT1", "eou.outcome": "user_resumed" }
│  │  └─ livekit.eou_detection : task         2.1–2.5s
│  │       # Detector execution extends beyond resumed speech at 2.3s.
│  ├─ user_speech [U2] : task                  2.3–3.5s
│  └─ eou_wait [E2] : task                     3.5–4.0s
│       metadata: { "turn.id": "UT1", "eou.outcome": "committed" }
│       audio.source_id: session-input
│
└─ llm_response [M1] : task                    3.7–4.5s
     # Speculative generation overlaps E2; E2 ends at the turn decision.
```

An unfinished wait ends at the observation cutoff, with no known outcome or final commitment condition. Framework-specific termination metadata is optional.

```text
2.0s  speech ends
2.2s  session shuts down before a decision

eou_wait : task                              2.0–2.2s
  eou.outcome: omitted
  eou.end_reason: omitted
```

### `stt`

A framework speech-to-text operation.

Contains the recognized text produced by that operation. It may link to the corresponding `user_speech` or `agent_speech` with `transcribes`. When the framework reports recognized text without an observed speech-to-text operation (e.g. when a speech-native model reports a transcript of incoming audio), use `transcript_received`.

```text
span_attributes: { name: "stt", type: "task" }
metrics.start / end: recognition operation interval
output?: recognized messages
metadata["audio.source_id"]?: string            source ID, when established by the input stream
// Updates replace the participant and speaker lists; include all known IDs.
metadata["audio.participant_ids"]?: string[]    participant IDs, when established by the input stream
metadata["audio.speaker_ids"]?: string[]        speaker IDs, when reported by recognition
metadata.model / provider?: string            observed transcription service
links?: transcribes → speech spans
```

**Children**

- If the operation calls an underlying client (e.g. a provider SDK) with a known Braintrust integration, the framework MUST defer to it.
  - When enabled, that integration emits its naturally named `llm` children.
  - When disabled, only the `stt` wrapper is emitted.
- Else, if the framework uses its own client or exposes operation data, it MUST emit its own `llm` child, named with a `<framework>.` prefix and following the [Braintrust instrumentation guide](../instrumentation-guide.md).
- The wrapper records its own start/end timing, but MUST NOT record usage, cost, or model timing metrics. Each `llm` child owns its reported [metered duration](#metered-duration) and [token metrics](token-and-cost-metrics.md), with its own `metadata.model` and `metadata.provider`.
- Each child MUST retain observed native usage and request/session IDs under `metadata["contrib.<integration>.*"]`, preserving names, units and structure.

**Links**

| Type          | Target                          | Description                                              |
| ------------- | ------------------------------- | -------------------------------------------------------- |
| `transcribes` | `user_speech` or `agent_speech` | The recognized text describes speech on the target span. |

**Examples**

```text
# LiveKit calls the OpenAI SDK; LiveKit and OpenAI SDK instrumentation enabled.
stt [ST1] : task    1.0–2.0s
│   root_span_id: S
│   span_parents: ["UT1"]
│   metadata["audio.source_id"]: "session-input"
│   metadata["audio.participant_ids"]: ["caller-connection"]
│   metadata["audio.speaker_ids"]: ["speaker-1"]
│   metadata["contrib.livekit.speaker_id"]: "S1"
│   output:
│     user: "Where is my order?"
│   links: transcribes → U1
│     context: traceId=TRACE, spanId=U1, traceFlags=1
│     attributes["braintrust.relationship.type"]: "transcribes"
└─ Transcription [ST1L] : llm    1.0–2.0s   # From OpenAI instrumentation
     root_span_id: S
     span_parents: ["ST1"]
     input / output: transcription payloads
     metadata.model / provider: observed transcription service
     metrics: reported usage and operation timing
```

```text
# LiveKit calls the OpenAI SDK; LiveKit instrumentation enabled, OpenAI SDK instrumentation disabled.
# No llm child or framework fallback; wrapper fields abbreviated.
stt [ST1] : task    1.0–2.0s
  output: user: "Where is my order?"
  links: transcribes → U1
```

```text
# LiveKit instrumentation enabled; the underlying client has no known Braintrust integration.
# LiveKit exposes operation data and supplies the llm child; fields abbreviated.
stt [ST1] : task    1.0–2.0s
│  output: user: "Where is my order?"
│  links: transcribes → U1
└─ livekit.stt [ST1L] : llm    1.0–2.0s   # From LiveKit instrumentation
     input / output: observed operation payloads
     metadata.model / provider: observed service
     metrics: reported usage and operation timing
```

### `transcript_received`

The receipt of a transcript from the framework.

Contains the recognized text when the integration observes receipt rather than the execution of a speech-to-text operation (e.g. a speech-native model reports a transcript of incoming or outgoing audio). One span per finalized transcript item or framework transcript group; a group need not correspond to a server item or turn. It may link to the corresponding `user_speech` or `agent_speech` spans with `transcribes`.

```text
span_attributes: { name: "transcript_received", type: "task" }
output: recognized messages with user or assistant role
metrics.start / end: receipt through item/group finalization
metadata["audio.source_id"]?: string            source ID, when established by the input stream
// Updates replace the participant and speaker lists; include all known IDs.
metadata["audio.participant_ids"]?: string[]    participant IDs, when established by the input stream
metadata["audio.speaker_ids"]?: string[]        speaker IDs, when reported by recognition
links?: transcribes → speech spans
```

**Links**

| Type          | Target                          | Description                                              |
| ------------- | ------------------------------- | -------------------------------------------------------- |
| `transcribes` | `user_speech` or `agent_speech` | The recognized text describes speech on the target span. |

**Example**

```text
transcript_received [TR1] : task    2.1s
  root_span_id: S
  span_parents: ["S"]
  metadata["audio.source_id"]: "session-input"
  metadata["contrib.livekit.item_id"]: "user-msg-1"
  output:
    user: "Where is my order?"
```

### Session model operation

Model execution across a session, such as a continuously listening/speaking duplex model.

The span name is the provider integration's operation name, or `<framework>.<operation>` when the framework owns the model client (e.g. `pipecat.live`).

This span is a child of `session`. It requires neither `turn.id` nor an `llm_response` wrapper. Duplex models with only response-scoped execution use `llm_response` instead.

- It owns the model's reported [metered duration](#metered-duration) and [token metrics](token-and-cost-metrics.md), with its own `metadata.model` and `metadata.provider`. Separate backend operations own their usage; it MUST NOT be duplicated here or on the parent `session`.
- It MUST retain observed native usage and request/session IDs under `metadata["contrib.<integration>.*"]`, preserving names, units and structure.

```text
span_attributes: { name: <observed model operation>, type: "llm" }
input / output?: observed model payloads
metadata["audio.scope"]: "session"
metadata.model / provider: string
metadata["contrib.<integration>.*"]?: ...      native usage and request/session IDs
metrics.start / end: model execution interval
metrics.usage_seconds?: number                 provider-reported metered duration in seconds
metrics.usage_standby_seconds?: number         provider-reported standby portion in seconds
metrics: this model's token usage and cost
```

### `llm_response`

One model response, which can include text, audio, or tool requests. This span shows what went into the model and what came out. Speech spans show what was actually said. Reported model usage remains on its `llm` child even when the response is interrupted.

```text
span_attributes: { name: "llm_response", type: "task" }
input?: observed context messages
output?: generated messages / tool calls
links?: uses_context → speech / STT / transcript spans; consumes_tool_result → tools
metadata.model / provider?: string            observed service configuration
metrics.start / end: framework operation interval
```

**Children**

- If the operation calls an underlying client (e.g. a provider SDK) with a known Braintrust integration, the framework MUST defer to it.
  - When enabled, that integration emits its naturally named `llm` children which MUST follow the [Braintrust instrumentation guide](../instrumentation-guide.md).
  - When disabled, only the `llm_response` wrapper is emitted.
- Else, if the framework uses its own client or exposes operation data, it MUST emit its own `llm` child, named with a `<framework>.` prefix and following the [Braintrust instrumentation guide](../instrumentation-guide.md).
- The wrapper records its own start/end timing, but MUST NOT record usage, cost, or model timing metrics. Each `llm` child owns its reported [metered duration](#metered-duration) and [token metrics](token-and-cost-metrics.md), with its own `metadata.model` and `metadata.provider`.
- Each child MUST retain observed native usage and request/session IDs under `metadata["contrib.<integration>.*"]`, preserving names, units and structure.

**Links**

| Type                   | Target                                                      | Description                                 |
| ---------------------- | ----------------------------------------------------------- | ------------------------------------------- |
| `uses_context`         | `user_speech`, `agent_speech`, `stt`, `transcript_received` | The target’s content appears in this input. |
| `consumes_tool_result` | Tool execution                                              | The target’s result appears in this input.  |

**Examples**

```text
# LiveKit calls the OpenAI SDK; LiveKit and OpenAI SDK instrumentation enabled.
llm_response [M1] : task    2.0–3.0s
│   root_span_id: S
│   span_parents: ["AT1"]
│   input:
│     user: "Where is my order?"
│   output:
│     assistant: "It arrives Friday."
│   links: uses_context → ST1
│     context: traceId=TRACE, spanId=ST1, traceFlags=1
│     attributes["braintrust.relationship.type"]: "uses_context"
└─ Chat Completion [M1L] : llm    2.0–3.0s   # From OpenAI instrumentation
     root_span_id: S
     span_parents: ["M1"]
     input: [{ role: "user", content: "Where is my order?" }]
     output: [{ index: 0, finish_reason: "stop", message: { role: "assistant", content: "It arrives Friday." } }]
     metadata.model / provider: observed model / "openai"
     metrics: reported usage and operation timing
```

```text
# LiveKit calls the OpenAI SDK; LiveKit instrumentation enabled, OpenAI SDK instrumentation disabled.
# No llm child or framework fallback; wrapper fields abbreviated.
llm_response [M1] : task    2.0–3.0s
  input: user: "Where is my order?"
  output: assistant: "It arrives Friday."
  links: uses_context → ST1
```

```text
# LiveKit instrumentation enabled; the underlying client has no known Braintrust integration.
# LiveKit exposes operation data and supplies the llm child; fields abbreviated.
llm_response [M1] : task    2.0–3.0s
│  input: user: "Where is my order?"
│  output: assistant: "It arrives Friday."
│  links: uses_context → ST1
└─ livekit.llm_response [M1L] : llm    2.0–3.0s   # From LiveKit instrumentation
     input / output: observed operation payloads
     metadata.model / provider: observed service
     metrics: reported usage and operation timing
```

```text
# LiveKit implements the OpenAI Realtime protocol directly; it does not call the OpenAI SDK.
# LiveKit instrumentation enabled; OpenAI SDK instrumentation may be enabled or disabled.
llm_response [M1] : task    2.0–3.0s
│  input: observed user audio / context
│  output: assistant: "It arrives Friday."
│  links: uses_context → U1
└─ livekit.llm_response [M1L] : llm    2.0–3.0s   # From LiveKit instrumentation
     input / output: observed model response payloads
     metadata.model / provider: observed model / "openai"
     metrics: reported usage and operation timing
```

### Tool execution

An execution of a tool.

`gen_ai.tool.call.id` identifies the tool call in the model’s output. A `requested_by` link points to the `llm_response` span that issued that call.

```text
span_attributes: { name: <tool name>, type: "tool" }
input?: arguments
output?: result
links?: requested_by → llm_response
metadata["gen_ai.tool.call.id"]?: string       native call ID, not a span ID
```

**Links**

| Type           | Target         | Description                              |
| -------------- | -------------- | ---------------------------------------- |
| `requested_by` | `llm_response` | The model requested this tool execution. |

**Example**

```text
get_price [T1] : tool    7.2–7.4s
  root_span_id: S
  span_parents: ["S"]
  input:
    service: "floors_only"
  output:
    price: 250
    currency: "USD"
  metadata["gen_ai.tool.call.id"]: "C1"
  links: requested_by → M2
    context: traceId=TRACE, spanId=M2, traceFlags=1
    attributes["braintrust.relationship.type"]: "requested_by"
```

### `tts`

A text-to-speech operation.

It represents the generation of the audio from text, whereas `agent_speech` represents actual audio playback. May identify the voice used for synthesis with `audio.speaker_ids`. Reported synthesis usage remains on its `llm` child even when the audio is not played.

```text
span_attributes: { name: "tts", type: "task" }
metrics.start / end: synthesis operation interval
input?: text
output?: generated text / audio
links?: generated_by → llm_response
metadata["audio.speaker_ids"]?: string[]        identified voices used for this speech
metadata.model / provider?: string            observed synthesis service
```

**Children**

- If the operation calls an underlying client (e.g. a provider SDK) with a known Braintrust integration, the framework MUST defer to it.
  - When enabled, that integration emits its naturally named `llm` children.
  - When disabled, only the `tts` wrapper is emitted.
- Else, if the framework uses its own client or exposes operation data, it MUST emit its own `llm` child, named with a `<framework>.` prefix and following the [Braintrust instrumentation guide](../instrumentation-guide.md).
- The wrapper records its own start/end timing, but MUST NOT record usage, cost, or model timing metrics. Each `llm` child owns its reported [metered duration](#metered-duration) and [token metrics](token-and-cost-metrics.md), with its own `metadata.model` and `metadata.provider`.
- Each child MUST retain observed native usage and request/session IDs under `metadata["contrib.<integration>.*"]`, preserving names, units and structure.

**Links**

| Type           | Target         | Description                                    |
| -------------- | -------------- | ---------------------------------------------- |
| `generated_by` | `llm_response` | The model produced the text being synthesized. |

**Examples**

```text
# LiveKit calls the OpenAI SDK; LiveKit and OpenAI SDK instrumentation enabled.
tts [TT1] : task    3.0–4.0s
│   root_span_id: S
│   span_parents: ["AT1"]
│   metadata["audio.speaker_ids"]: ["support-voice"]
│   input:
│     text: "It arrives Friday."
│   links: generated_by → M1
│     context: traceId=TRACE, spanId=M1, traceFlags=1
│     attributes["braintrust.relationship.type"]: "generated_by"
└─ Speech [TT1L] : llm    3.0–4.0s   # From OpenAI instrumentation
     root_span_id: S
     span_parents: ["TT1"]
     input / output: synthesis payloads
     metadata.model / provider: observed synthesis service
     metrics: reported usage and operation timing
```

```text
# LiveKit calls the OpenAI SDK; LiveKit instrumentation enabled, OpenAI SDK instrumentation disabled.
# No llm child or framework fallback; wrapper fields abbreviated.
tts [TT1] : task    3.0–4.0s
  input: text: "It arrives Friday."
  links: generated_by → M1
```

```text
# LiveKit instrumentation enabled; the underlying client has no known Braintrust integration.
# LiveKit exposes operation data and supplies the llm child; fields abbreviated.
tts [TT1] : task    3.0–4.0s
│  input: text: "It arrives Friday."
│  links: generated_by → M1
└─ livekit.tts [TT1L] : llm    3.0–4.0s   # From LiveKit instrumentation
     input / output: observed operation payloads
     metadata.model / provider: observed service
     metrics: reported usage and operation timing
```

### `contrib.<integration>.*`

An integration-specific operation.

They enrich traces with additional operational detail, such as opening a connection or running a turn detector within `eou_wait`. Native fields and values belong under `contrib.<integration>.*`.

```text
span_attributes: { name: <framework operation>, type: "task" }
input / output?: native operation payload
metadata["contrib.<integration>.*"]?: ...      native identities and outcomes
```

**Example**

```text
livekit.session_start [F1] : task    0.0–0.5s
  root_span_id: S
  span_parents: ["S"]
```

## Metrics specification

### Metered duration

`metrics.usage_seconds` is the shared metric for metered duration in seconds. When the provider reports a value, instrumentation MUST record it on the `llm` span for the operation that incurred it.

```text
metrics.usage_seconds?: number                 // Finite and nonnegative. Fractional seconds are allowed.
```

- Preserve reported zero and omit metered duration when unavailable. Span duration and recorded audio length measure different quantities.
- Convert other reported time units to seconds without additional rounding or billing adjustments. Preserve native usage and its breakdowns under `metadata["contrib.<integration>.*"]`.
- For cumulative reports, later totals replace earlier ones. Final reports, including late reports, belong to the same span.
- If the integration computes the dollar cost from metered duration, record it in `metrics.estimated_cost`.

#### `metrics.usage_standby_seconds`

The portion of `metrics.usage_seconds` billed at the provider's standby rate (idle or paused). It is already included in the total: active duration is `usage_seconds - usage_standby_seconds`. The value is finite and nonnegative; fractional seconds are allowed.

Instrumentation MUST record it on the same `llm` span as `metrics.usage_seconds` when the provider reports the breakdown. Preserve reported zero and omit the metric when unavailable rather than deriving it. For cumulative reports, later standby totals replace earlier ones.

For example, OpenAI GPT-Live reports `SessionUsage.paused_seconds` in `session.usage.updated` and `session.closed` for eligible WebRTC sessions. OpenAI pricing calls this the "Standby" rate.

### Audio token metrics

Record these breakdowns on the `llm` span for the operation that incurred the usage, following the [canonical token metrics](token-and-cost-metrics.md#canonical-metrics). The values are nonnegative integers. Instrumentation SHOULD record them when reported, preserve reported zero, and omit unavailable counts.

#### `metrics.prompt_audio_tokens`

Input audio tokens already included in `metrics.prompt_tokens`. The count includes cached audio tokens when the provider includes them in its input audio total.

#### `metrics.prompt_cached_audio_tokens`

Input audio tokens read from the prompt cache. These tokens are already included in both `metrics.prompt_audio_tokens` and `metrics.prompt_cached_tokens`. Record this metric only when the provider reports the intersection.

The value is cumulative for the owning operation. Later totals replace earlier ones. Final reports, including late reports, belong to the same span.

#### `metrics.completion_audio_tokens`

Output audio tokens already included in `metrics.completion_tokens`. The count reflects audio generated by the model, including reported usage for audio that was interrupted or never played.

## Metadata specification

### `audio.schema.version`

Identifies the audio trace schema implemented by the session and its child spans.

```text
metadata["audio.schema.version"]: string          // Semantic version: MAJOR.MINOR.PATCH
```

- **Major:** changes that require consumers to adapt, such as moving a field or changing its type or meaning.
- **Minor:** backward-compatible additions. Consumers must tolerate unknown fields and span types.
- **Patch:** clarifications that do not change valid trace data. These do not require instrumentation to update its emitted version.

Integrations emit the schema version they implement, independently of their SDK version or the latest document revision.

**Example**

```js
{ "audio.schema.version": "3.2.0" }
```

### `audio.scope`

`"session"` identifies a [session model operation](#session-model-operation), rather than a single response or turn.

```text
metadata["audio.scope"]?: "session"
```

### `eou.outcome`

How an `eou_wait` ended. Omitted when unknown; shutdown alone establishes neither commitment nor abandonment.

```text
metadata["eou.outcome"]?: "committed" | "user_resumed" | "dropped"
```

| Value | Meaning |
| ----- | ------- |
| `committed` | The framework accepted the user turn as complete. |
| `user_resumed` | The user resumed speaking before commitment. |
| `dropped` | The framework abandoned the wait without committing the turn. |

### `eou.end_reason`

For a `committed` wait, the final condition that permitted commitment. Omitted for other outcomes or when no single final condition is known.

| Value | Meaning |
| ----- | ------- |
| `silence_timeout` | The required interval without user speech elapsed. |
| `transcription_finalized` | The required final transcript became available. |
| `turn_detector` | A turn detector accepted the utterance as complete. |
| `provider_signal` | An external service declared the turn complete without exposing the deciding condition. |
| `manual_commit` | An application explicitly committed the turn. |

### `eou.speech_end_source`

The origin of the speech-end timestamp used for `metrics.start`, independent of what triggered turn evaluation. Omit when the origin is unknown or ambiguous.

| Value | Meaning |
| ----- | ------- |
| `vad` | A voice activity detector identified the end of speech. |
| `stt` | A transcription service identified the end of speech. |
| `provider` | Another audio-consuming service identified the end of speech. |

Notification receipt time and transcript completion time are not speech-end timestamps.

**Example**

```text
2.00s  VAD-reported speech end                 ← metrics.start
2.30s  final transcript available
2.50s  turn committed                         ← metrics.end

eou_wait : task                                2.00–2.50s
  metadata:
    turn.id: UT1
    audio.source_id: session-input
    eou.outcome: committed
    eou.speech_end_source: vad
    contrib.<integration>.*: ...               native strategy, delays, scores

# eou.end_reason omitted: no single final condition is known.
```

### `links`

Span links describe the relationship between different operations during the call. This is useful for tracking responses, source or cause, etc. They are best-effort, optional and describe observed associations, not relationships inferred from timing or text similarity.

> NOTE: As of October 2026, these links are implemented on `metadata.links` until support for a top-level attribute can be added. When support becomes available, they should be migrated to the `links` attribute as described below.

```text
links?: [{
  context: { traceId: string, spanId: string, traceFlags: integer };
  attributes: { "braintrust.relationship.type": string, ... };
}];
```

**Example**

```jsonc
// On llm_response M2 (source): M2 ──consumes_tool_result──→ tool T1 (target)
{
  "links": [{
    "context": {                         // Identifies the target span
      "traceId": "TRACE",                // Target's trace ID
      "spanId": "T1",                    // Target's span ID
      "traceFlags": 1                    // W3C Trace Context trace-flags; 1 means sampled. See https://www.w3.org/TR/trace-context/#trace-flags
    },
    "attributes": {                      // Describes the source → target relationship
      "braintrust.relationship.type": "consumes_tool_result"
    }
  }]
}
```

| `braintrust.relationship.type` | Source                       | Target                                   | Description                                                        |
| ------------------------------ | ---------------------------- | ---------------------------------------- | ------------------------------------------------------------------ |
| `uses_context`                 | `llm_response`               | `*_speech`, `stt`, `transcript_received` | The target's content appears in the model's observed input.        |
| `requested_by`                 | Tool execution               | `llm_response`                           | The target requested this tool execution.                          |
| `consumes_tool_result`         | `llm_response`               | Tool execution                           | The target's result appears in the model's observed input.         |
| `generated_by`                 | `agent_speech`, `tts`        | `llm_response`, `tts`                    | The target produced the content used for this speech or synthesis. |
| `transcribes`                  | `stt`, `transcript_received` | `*_speech`                               | The recognized text describes speech on the target span.           |

Integrations may also define their own `braintrust.relationship.type`s as `contrib.<integration>.*`, e.g. `contrib.livekit.interrupted_by` to link `user_speech` that interrupted `agent_speech`.

### `audio.sources`

A source identifies an audio stream being captured, such as the agent's input or output stream. 

- A `source` can can carry audio from different `participants` and `speakers`, as well as non-speech audio such as hold music.
- `attributes` may contain additional details about the source, including native descriptions in the form of `contrib.<integration>.*` fields.

```text
metadata["audio.sources"]?: map<string, AudioSource>

type AudioSource = {
  label?: string;                                 // Display name, e.g. "Agent input audio"
  attributes?: map<string, JSON value>;            // Source details
};
```

**Example**

```js
// Within audio.sources
{
  "session-input": {
    label: "Agent input audio",
    attributes: {
      "contrib.livekit.track_id": "TR_example"
    }
  },
  "agent-output": { label: "Agent audio" }
}
```

### `audio.source_id`

Identifies which `audio.sources` (as defined on the `session`) is associated with the operation.

```text
metadata["audio.source_id"]?: string
```

**Example**

```js
{ "audio.source_id": "session-input" }
```

### `audio.participants`

A participant is a registered member of the conversation, such as a person's phone, a conference room, or an agent. (Think Zoom or Google Meet participant.) 

- Multiple speakers can be under one participant when sharing a microphone (e.g. in a meeting room together.)
- `attributes` may contain additional details about the participant, including native descriptions in the form of `contrib.<integration>.*` fields.

```text
metadata["audio.participants"]?: map<string, AudioParticipant>

type AudioParticipant = {
  type: "user" | "agent" | "other" | "unknown";
  label?: string;                                 // Display name, e.g. "Meeting room connection"
  attributes?: map<string, JSON value>;            // Participant details
};
```

**Example**

```js
// Within audio.participants
{
  "meeting-room": {
    type: "user",
    label: "Meeting room connection",
    attributes: {
      "contrib.livekit.participant_id": "PA_example",
      "contrib.livekit.participant_kind": "STANDARD"
    }
  },
  "agent-connection": { type: "agent", label: "Agent connection" }
}
```

### `audio.participant_ids`

Identifies which `audio.participants` (as defined on the `session`) are associated with the operation.

```text
metadata["audio.participant_ids"]?: string[]
```

**Example**

```js
{ "audio.participant_ids": ["meeting-room"] }
```

### `audio.speakers`

A speaker is a voice identified in recognized or synthesized speech. 

- A speaker label does not necessarily identify a real person.
- A `participant` does not always map 1:1 with a `speaker`, particularly when there multiple speakers sharing one microphone.
- `attributes` may contain additional details about the speaker, including native descriptions in the form of `contrib.<integration>.*` fields.

```text
metadata["audio.speakers"]?: map<string, AudioSpeaker>

type AudioSpeaker = {
  type: "user" | "agent" | "other" | "unknown";
  label?: string;                                 // Display name, e.g. "Speaker S1"
  attributes?: map<string, JSON value>;            // Speaker details
};
```

**Example**

```js
// Within audio.speakers
{
  "speaker-1": {
    type: "user",
    label: "Speaker S1",
    attributes: {
      "contrib.livekit.speaker_id": "S1"
    }
  },
  "speaker-2": { type: "user", label: "Speaker S2" },
  "support-voice": { type: "agent", label: "Support voice" }
}
```

### `audio.speaker_ids`

Identifies which `audio.speakers` (as defined on the `session`) are associated with the operation.

```text
metadata["audio.speaker_ids"]?: string[]
```

**Example**

```js
{ "audio.speaker_ids": ["speaker-1"] }
```

### `audio.timeline`

`audio.timeline` defines an epoch for `audio.segments` and `audio.selections` in a `session`.

> ⚠️ Trimming pauses or silence when processing recorded audio can result in timing misalignment. Avoid this.

```text
metadata["audio.timeline"]?: AudioTimeline

type AudioTimeline = {
  origin_unix_ms: integer;                // Shared session epoch, in milliseconds since Unix epoch
};
```

**Example**

```js
// Within audio.timeline
{ origin_unix_ms: 1790000000000 }
```

### `audio.selections`

Maps this span against intervals on the `session`'s `audio.timeline`.

- `*_offset_ms` timestamps are relative to `audio.timeline.origin_unix_ms` in the nearest enclosing `session` span.

```text
metadata["audio.selections"]?: map<string, Selection>

type Selection = {
  start_offset_ms: integer;               // Relative to audio.timeline.origin_unix_ms
  end_offset_ms: integer;                 // End offset in milliseconds (exclusive)
};
```

**Example**

```js
// Metadata on a user_speech span; audio crosses a segment boundary at 60s.
{
  "audio.selections": {
    "selection-0": {
      start_offset_ms: 58000,
      end_offset_ms: 63000
    }
  }
}
```

### `audio.segments`

Segments are successive, non-overlapping pieces of one recording, each uploaded as an attachment on the owning session span. Each ready segment lists every output channel using contiguous, zero-based keys.

A channel lists source IDs represented at any point in the segment. Use an empty list when no source is identified.

```text
metadata["audio.segments"]?: map<string, AudioSegment>

type AudioSegment = {
  state: "pending" | "ready" | "omitted";
  start_offset_ms: integer;                       // Relative to audio.timeline.origin_unix_ms
  duration_ms?: integer;                          // Length of this segment’s audio, in milliseconds. Optional when "omitted"
  attachment?: {
    ref: string;                                  // Path to the attachment on the session span, e.g. "/input/audio/part-0"
  };
  mime_type?: string;                             // Media/container type, e.g. "audio/ogg", "audio/pcm"
  encoding?: string;                              // Audio codec, e.g. "opus", "pcm"
  sample_rate_hz?: integer;                       // Audio samples per second; required for raw PCM
  channels?: map<string, { sources: string[] }>;  // Every output channel, keyed "0", "1", ...
  attributes?: map<string, JSON value>;           // Audio format details, such as PCM sample format or Opus bitrate
  reason?: string;                                // Required when "omitted"
};
```

**Example**

```js
// Within audio.segments
{
  "part-0": {
    state: "ready",
    start_offset_ms: 0,
    duration_ms: 60000,
    attachment: { ref: "/input/audio/part-0" },
    mime_type: "audio/ogg",
    encoding: "opus",
    sample_rate_hz: 48000,
    channels: {
      "0": { sources: ["session-input"] },
      "1": { sources: ["agent-output"] }
    }
  }
}
```

#### Segment `attributes`

Segments may undergo processing before upload, such as compression. Format fields describe the resulting file: `mime_type` identifies its container/media format, while `encoding` identifies the audio codec inside it. Additional metadata belongs in `attributes`.

| Attribute            | Type / accepted values                         | Meaning                                                                                                        |
| -------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `pcm.sample_format`  | String enum: `"s16le"`                         | Signed 16-bit little-endian samples; required for raw PCM.                                                     |
| `pcm.channel_layout` | String enum: `"interleaved"`                   | Samples alternate between channels in channel-index order; required for raw PCM.                               |
| `opus.bitrate_bps`   | Integer, `500–512000` inclusive                | Optional configured target bitrate in bits per second for the whole encoded stream, not measured file bitrate. |
| `opus.complexity`    | Integer, `0–10` inclusive                      | Optional encoder effort, from fastest to highest complexity.                                                   |
| `opus.application`   | String enum: `"audio"`, `"voip"`, `"lowdelay"` | Optional tuning for general audio, speech, or restricted low-delay encoding.                                   |

Format fields for PCM and Opus/Ogg segments (other segment fields omitted):

```js
// Raw PCM
{
  mime_type: "audio/pcm",
  encoding: "pcm",
  sample_rate_hz: 24000,
  attributes: {
    "pcm.sample_format": "s16le",
    "pcm.channel_layout": "interleaved"
  }
}

// Opus audio in an Ogg container
{
  mime_type: "audio/ogg",
  encoding: "opus",
  sample_rate_hz: 48000,
  attributes: {
    "opus.bitrate_bps": 64000
  }
}
```

#### Segment `state`

Audio attachment uploads may complete asynchronously from the trace.

As it does, the corresponding segment's state changes from `pending` to `ready` after its attachment uploads successfully, or to `omitted` with a reason if it will not be available. When a segment is omitted, retain its known start offset and duration.

`ready` segments must include an attachment, MIME type, encoding, and channel mapping.

```js
// Add part-1 without resending previously logged segments.
{
  id: sessionRowId,
  _is_merge: true,
  metadata: {
    "audio.segments": {
      "part-1": { state: "pending", start_offset_ms: 60000, duration_ms: 15000 }
    }
  }
}
```

## References

- [Real-time Context Standard](https://docs.pipecat.ai/api-reference/standards/real-time-context-standard)
- [OpenTelemetry Span Links](https://opentelemetry.io/docs/specs/otel/trace/api/#link)
- [LiveKit speaker diarization](https://docs.livekit.io/agents/models/stt/diarization/)
- [LiveKit pipeline types](https://docs.livekit.io/agents/models/pipelines/)
- [Opus encoder controls](https://opus-codec.org/docs/opus_api-1.6/group__opus__encoderctls.html)

# SDK support

```yaml
# Release assessment: 2026-11-16. Other SDKs remain unassessed.
# Python 0.50.0: LiveKit and Pipecat; JavaScript 3.44.0: LiveKit cascade.
# Python: https://github.com/braintrustdata/braintrust-sdk-python/tree/3754367b1e5f6298cfcbaaa61ec64cbe883d2177
# JS: https://github.com/braintrustdata/braintrust-sdk-javascript/tree/4c1d334f707d13a01ed1815ee7a0194c079c1e30
id: audio-traces
name: Audio traces
category: Multimodal
support:
  metered-duration: # Shared metrics.usage_seconds field. Release support has not been assessed.
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  standby-duration: # Shared metrics.usage_standby_seconds field. Release support has not been assessed.
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  native-usage-metadata: # Native usage preservation; release support has not been assessed.
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  session-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "yes"
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
  turn-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown" # Duplex turn membership and overlap have not been assessed.
    python: "unknown" # Duplex turn membership and overlap have not been assessed.
    ruby: "unknown"
    rust: "unknown"
  speech-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "yes"
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
  eou-wait-spans: # New common span; release support has not been assessed.
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  eou-wait-metadata: # Speech-end source and commitment condition; release support is unassessed.
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  transcription-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "partial" # STT tasks; no nested model children or transcript_received support.
    python: "partial" # STT provider nesting and transcript receipts; no STT fallback children.
    ruby: "unknown"
    rust: "unknown"
  session-model-spans: # Session-wide model execution with audio.scope; not yet assessed.
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown"
    python: "unknown"
    ruby: "unknown"
    rust: "unknown"
  model-response-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "partial" # llm_response is still llm and owns usage/timing.
    python: "partial" # Task wrappers with children; Pipecat still logs model timing on the wrapper.
    ruby: "unknown"
    rust: "unknown"
  synthesis-spans:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "partial" # TTS tasks suppress provider instrumentation and lack fallback children.
    python: "partial" # No TTS fallback children; LiveKit logs time_to_first_audio on the wrapper.
    ruby: "unknown"
    rust: "unknown"
  provider-instrumentation-delegation:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "no" # Framework inference suppresses provider instrumentation.
    python: "partial" # LLM/STT client delegation exists; Pipecat lacks TTS provider-parent context.
    ruby: "unknown"
    rust: "unknown"
  framework-llm-fallback:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "no" # No separate framework fallback llm child.
    python: "partial" # LiveKit uses unprefixed LLM request / Realtime request; no STT/TTS fallback.
    ruby: "unknown"
    rust: "unknown"
  relationship-links:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "unknown" # Observed-only association requirement has not been reassessed.
    python: "unknown" # Observed-only association requirement has not been reassessed.
    ruby: "unknown"
    rust: "unknown"
  audio-identities:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "yes"
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
  audio-recordings:
    dotnet: "unknown"
    go: "unknown"
    java: "unknown"
    js: "partial" # Ready/omitted segments are published, but pending uploads are not.
    python: "yes"
    ruby: "unknown"
    rust: "unknown"
```
