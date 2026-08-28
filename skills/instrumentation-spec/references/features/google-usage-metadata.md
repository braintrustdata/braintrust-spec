# Google Gemini usage metadata

> **Upstream reference:** [Google GenerateContent `UsageMetadata`](https://ai.google.dev/api/generate-content#UsageMetadata)

Applies to direct Google GenAI, Google ADK, and Interactions integrations.

## GenerateContent

Map `GenerateContentResponse.usageMetadata` as follows:

```text
prompt_tokens = promptTokenCount + toolUsePromptTokenCount
completion_tokens = candidatesTokenCount + thoughtsTokenCount
completion_reasoning_tokens = thoughtsTokenCount
tokens = totalTokenCount
prompt_cached_tokens = cachedContentTokenCount
```

- Preserve `totalTokenCount`; do not recompute it.
- Preserve reported zero values. If only one component of a sum is reported, treat the missing component as zero.
- Reasoning tokens are a subset of `completion_tokens`.
- Tool-use prompt tokens are part of `prompt_tokens`; do not emit a separate metric for them.
- Cached tokens are a subset of `promptTokenCount`; do not add them to `prompt_tokens`.

When all component counts are reported, the normalized metrics should satisfy:

```text
tokens = prompt_tokens + completion_tokens
```

Retain returned thought parts in output, including their thought marker and returned text or signature. This also applies to ADK and streaming aggregation.

## Interactions

Map Interactions `usage` as follows:

```text
prompt_tokens = total_input_tokens
completion_tokens = total_output_tokens + total_thought_tokens
completion_reasoning_tokens = total_thought_tokens
tokens = total_tokens
prompt_cached_tokens = total_cached_tokens
```

Do not emit `total_tool_use_tokens` as a `tool_use_tokens` metric. If captured, store it as `metadata.total_tool_use_tokens`.

## Modality details

Sum all entries matching the modality.

| Google usage detail | Braintrust metric |
| --- | --- |
| `promptTokensDetails[AUDIO]` | `prompt_audio_tokens` |
| `candidatesTokensDetails[AUDIO]` | `completion_audio_tokens` |
| `candidatesTokensDetails[IMAGE]` | `completion_image_tokens` |
| Interactions `input_tokens_by_modality[audio]` | `prompt_audio_tokens` |
| Interactions `output_tokens_by_modality[audio]` | `completion_audio_tokens` |
| Interactions `output_tokens_by_modality[image]` | `completion_image_tokens` |

These detail metrics are subsets of their prompt or completion totals. Do not create metrics for unsupported modalities, including input images.

Cache and tool-use modality arrays have no standard metric mapping. When captured, preserve them as provider metadata:

```json
{
  "metadata": {
    "usage_by_modality": {
      "cache_tokens_details": [],
      "tool_use_prompt_tokens_details": []
    }
  }
}
```

## Streaming and ADK

For streams, use the final usage-bearing event. ADK model-call spans use the GenerateContent mapping.

Related BTX specs:

- GenerateContent: [thinking](../../../../test/llm_span/google/thinking.yaml), [grounding](../../../../test/llm_span/google/grounding.yaml), and [streaming](../../../../test/llm_span/google/streaming.yaml)
- Interactions: [standard](../../../../test/llm_span/google/interactions.yaml) and [streaming](../../../../test/llm_span/google/interactions_streaming.yaml)
- Modalities: [input audio](../../../../test/llm_span/google/attachments.yaml), [output audio](../../../../test/llm_span/google/generated_audio_usage.yaml), and [output image](../../../../test/llm_span/google/generated_image_usage.yaml)

# SDK support

| ID | Capability | .NET | Go | Java | JS | Python | Ruby | Rust |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| google-usage-metadata | Google usage metadata | unknown | unknown | unknown | unknown | unknown | unknown | unknown |

```json
{
  "id": "google-usage-metadata",
  "name": "Google Gemini usage metadata",
  "category": "Token & cost",
  "providers": [
    "google"
  ]
}
```
