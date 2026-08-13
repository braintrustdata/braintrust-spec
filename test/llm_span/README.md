# LLM span end-to-end tests

Each YAML file defines provider requests and partial assertions for the Braintrust spans emitted by an integration. See [the BTX implementation guide](../IMPLEMENTATION-GUIDE.md) for loading, execution, matcher, and validation semantics.

A runner should execute a spec through every registered integration that can express its provider and endpoint. For example, Google `:generateContent` specs apply to direct Google GenAI integrations and Google ADK integrations; `/v1/interactions` specs apply only to clients that support the Interactions API.

## Google coverage

The Google specs cover:

- basic GenerateContent;
- thinking and retained thought parts;
- Google Search grounding/tool-use prompt usage;
- streaming;
- Interactions and Interactions streaming;
- multimodal attachments and input-audio usage;
- generated-audio and generated-image usage details.

`is_google_usage_metadata_normalized` verifies that reasoning and tool-use prompt categories are included in canonical completion/prompt totals, the provider total is preserved, and no nonstandard `tool_use_tokens` metric is emitted. See the instrumentation skill's [Google usage metadata specification](../../skills/instrumentation-spec/references/features/google-usage-metadata.md).
