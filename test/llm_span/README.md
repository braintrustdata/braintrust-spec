# LLM span end-to-end tests

Each YAML file defines provider requests and partial assertions for the Braintrust spans emitted by an integration. See [the BTX implementation guide](../IMPLEMENTATION-GUIDE.md) for loading, execution, matcher, and validation semantics.

A runner should execute a spec through every registered integration that can express its provider and endpoint. For example, Google `:generateContent` specs apply to direct Google GenAI integrations and Google ADK integrations; `/v1/interactions` specs apply only to clients that support the Interactions API.

## Model selection

Model references were reviewed on October 26, 2026. Keep request models, model IDs in endpoints, and expected span metadata synchronized when changing models. Re-record affected cassettes in downstream SDK runners after an update.

The OpenAI specs use [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) in place of deprecated GPT-4o models and retired o4-mini. Chat Completions tests with sampling parameters or function tools explicitly use `reasoning_effort: none`; reasoning tests retain their explicit reasoning effort. Token limits use `max_completion_tokens`. See the [OpenAI migration guide](https://developers.openai.com/api/docs/guides/latest-model#migration-quickstart).

The Anthropic and Bedrock caching specs use active [Claude Sonnet 4.6](https://platform.claude.com/docs/en/models/sonnet-4-6/overview), preserving their sampling parameters, output shape, and 1,024-token cache threshold. Newer Sonnet models change these request requirements. Claude Haiku 4.5 and Amazon Nova Lite remain supported for the other existing tests; see the [Claude model lifecycle](https://platform.claude.com/docs/en/about-claude/model-deprecations) and [Bedrock model lifecycle](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.html).

The Google specs use stable Gemini 3.5 Flash-Lite for basic and attachment requests, Gemini 3.8 Flash for thinking, grounding, streaming, and Interactions, Gemini 3.8 Flash TTS for audio generation, and Nano Banana 2.1 for image generation. These replace the Flash-Lite preview and older Gemini 2.5 examples, whose availability is restricted for new users. See the [Google model catalog](https://ai.google.dev/gemini-api/docs/models).

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
