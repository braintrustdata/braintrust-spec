# Prompts API Research

This document is research for a future SDK spec for Braintrust prompts. It is not the spec itself.

The target workflows are:

1. Defining prompts via SDK APIs
2. Loading prompts from Braintrust via SDK APIs
3. Invoking prompts in deployed applications

The intended shape for the eventual spec should be similar to [braintrust-spec PR #2](https://github.com/braintrustdata/braintrust-spec/pull/2): overview, public API, behavior, wire format, and examples.

## Primary References

- Spec template: https://github.com/braintrustdata/braintrust-spec/pull/2
- User docs: https://www.braintrust.dev/docs/evaluate/write-prompts#sdk
- Deploy docs: https://www.braintrust.dev/docs/deploy/prompts

Local code and docs used for this research:

- `braintrust/docs/evaluate/write-prompts.mdx`
- `braintrust/docs/deploy/prompts.mdx`
- `braintrust/docs/openapi.yaml`
- `braintrust/tests/bt_services/functions.test.ts`
- `braintrust/tests/bt_services/test_prompt_environment_integration.py`
- `braintrust-sdk-javascript/js/src/framework2.ts`
- `braintrust-sdk-javascript/js/src/prompt-schemas.ts`
- `braintrust-sdk-javascript/js/src/logger.ts`
- `braintrust-sdk-javascript/js/src/functions/invoke.ts`
- `braintrust-sdk-python/py/src/braintrust/framework2.py`
- `braintrust-sdk-python/py/src/braintrust/logger.py`
- `braintrust-sdk-python/py/src/braintrust/functions/invoke.py`
- `braintrust-sdk-ruby/lib/braintrust/prompt.rb`
- `braintrust-sdk-ruby/lib/braintrust/api/functions.rb`
- `braintrust-sdk-java/src/main/java/dev/braintrust/prompt/BraintrustPrompt.java`
- `braintrust-sdk-java/src/main/java/dev/braintrust/prompt/BraintrustPromptLoader.java`
- `braintrust-sdk-java/src/main/java/dev/braintrust/api/BraintrustApiClient.java`

## Versions Reviewed

This research was based on the following local SDK/backend checkouts:

| Repo | Package / SDK version | Revision reviewed |
|---|---|---|
| `braintrust-sdk-javascript` | `3.4.0` from `js/package.json` | `js-sdk-v3.3.0-59-g704597f2-dirty` (`704597f2`) |
| `braintrust-sdk-python` | `0.9.0` from `py/src/braintrust/version.py` | `py-sdk-v0.9.0-9-gf4b70dd4` (`f4b70dd4`) |
| `braintrust-sdk-ruby` | `0.2.1` from `lib/braintrust/version.rb` | `v0.2.1-1-g74b588b` (`74b588b`) |
| `braintrust-sdk-java` | git-derived version from `build.gradle` | `v0.2.9-5-gb06777a` (`b06777a`) |
| `braintrust` backend/docs repo | workspace repo checkout | `v1.1.31-1149-g1d2aac55b9-dirty` (`1d2aac55b9`) |

Notes:

- The Java SDK computes its published version from git metadata at build time rather than storing a fixed version string in `gradle.properties`.
- The JavaScript checkout was dirty when reviewed, so its exact local state may have included uncommitted changes beyond commit `704597f2`.

## Executive Summary

The current Braintrust prompt surface is split across three related but not identical concepts:

1. Prompt objects stored in the control plane (`/v1/prompt`)
2. Prompt definitions published as functions with `function_data.type = "prompt"`
3. Prompt execution through the function invocation plane (`/function/invoke` or `/v1/function/{id}/invoke`)

The SDKs do not currently expose the same prompt feature set:

- JavaScript is the most complete implementation.
- Python covers the same broad workflows but has notable parity gaps.
- Ruby has a useful load/build implementation, but not the same high-level authoring or invoke surface.
- Java has a minimal load/render surface and generic function invocation by ID, but not a prompt-centric API.

There are also real docs/code mismatches today, especially around deployed prompt invocation.

## Canonical Backend Model

### Prompt object

The control plane exposes prompt CRUD on `/v1/prompt` and `/v1/prompt/{prompt_id}`.

Key backend schemas from `braintrust/docs/openapi.yaml`:

- `CreatePrompt`
- `PatchPrompt`
- `Prompt`
- `PromptData`
- `PromptBlockData`

Relevant fields on `PromptData`:

- `prompt`
- `options`
- `parser`
- `tool_functions`
- `template_format`
- `mcp`

`PromptBlockData` is a tagged union:

- chat prompt: `{ type: "chat", messages, tools? }`
- completion prompt: `{ type: "completion", content }`

### Prompt invocation

Prompt execution is not a dedicated `/v1/prompt/.../invoke` API. It goes through function invocation.

There are two relevant backend invocation paths:

- Proxy path used by JS/Python SDKs: `/function/invoke`
- REST path used by Java/Ruby low-level clients: `/v1/function/{function_id}/invoke`

The backend `FunctionId` union supports these function identifiers:

- `function_id`
- `project_name + slug`
- `global_function`
- `prompt_session_id + prompt_session_function_id`
- `inline_code`
- `inline_function`
- `inline_prompt`

The backend `InvokeApi` request supports at least:

- `input`
- `expected`
- `metadata`
- `tags`
- `messages`
- `parent`
- `stream`
- `mode`
- `strict`
- `mcp_auth`
- `overrides`
- `version`

Important implication: prompt execution is already modeled as a special case of function execution.

## Workflow 1: Defining Prompts Via SDK APIs

### JavaScript

Current authoring API is `project.prompts.create(...)` in `framework2.ts`.

Supported inputs:

- `name`
- `slug`
- `description`
- `id`
- exactly one of `prompt` or `messages`
- `model`
- `params`
- `tools`
- `ifExists`
- `metadata`
- `tags`
- `templateFormat`
- `environments`
- `noTrace` on the returned local prompt handle

Behavior:

- Raw tool JSON is serialized into `prompt_data.prompt.tools`
- Tool/function references are serialized into `prompt_data.tool_functions`
- `templateFormat` is persisted as top-level `prompt_data.template_format`
- `environments` are emitted as top-level function definition environment assignments
- Published function definition uses `function_data: { type: "prompt" }`

Observations:

- JS is the only SDK in this research set that already threads `environments` through prompt authoring.
- JS is also the only SDK here that clearly threads `templateFormat` through prompt authoring.

### Python

Current authoring API is `project.prompts.create(...)` in `framework2.py`.

Supported inputs:

- `name`
- `slug`
- `description`
- `id`
- exactly one of `prompt` or `messages`
- `model`
- `params`
- `tools`
- `if_exists`
- `metadata`
- `tags`

Behavior:

- Raw tools are serialized into `prompt_data.prompt.tools`
- Tool/function references are serialized into `prompt_data.tool_functions`
- Published definition uses `function_data: { type: "prompt" }`

Notable gaps relative to JS:

- No `templateFormat` authoring surface
- No `environments` authoring surface

### Ruby

There is no `project.prompts.create(...)` style high-level SDK builder in the repo.

The closest current surface is low-level function creation through `API::Functions#create(...)`, typically with:

- `function_data: { type: "prompt" }`
- `prompt_data: {...}`

This is workable, but it is not the same SDK ergonomics as JS/Python.

### Java

There is no prompt authoring builder in the Java SDK repo.

Java currently has:

- prompt loading
- prompt rendering helpers
- generic function invocation by function ID

but not code-based prompt definition/publishing.

### Research Conclusion For Authoring

The eventual spec will need to choose between:

- a minimal common denominator based on current cross-language support, or
- a normative target where other SDKs converge toward the JS surface

If the goal is a real cross-language prompt SDK spec, the JS authoring surface is the strongest candidate for the normative model.

## Workflow 2: Loading Prompts From Braintrust Via SDK APIs

### JavaScript

Current entrypoint: `loadPrompt(...)` in `js/src/logger.ts`.

Supported selectors:

- `id`
- `projectName + slug`
- `projectId + slug`

Supported modifiers:

- `version`
- `environment`
- `defaults`
- `noTrace`

Behavior:

- `version` and `environment` are mutually exclusive
- loading by `id` uses `/v1/prompt/{id}`
- loading by project/slug uses `/v1/prompt`
- successful fetches are cached
- cache fallback is skipped when `version` or `environment` is set

Returned object:

- `Prompt`

Prompt capabilities:

- `id`, `projectId`, `name`, `slug`, `version`, `options`, `templateFormat`
- `build(...)`
- `buildWithAttachments(...)`

Build behavior:

- supports both chat and completion prompts
- defaults merge with prompt params and model
- injects `span_info.metadata.prompt`
- resolves `template_format`
- supports `strict`
- supports appending extra `messages`
- deduplicates an extra system message if the saved prompt already has one
- parses rendered `tools` JSON into typed tool objects

JS is the most complete prompt loading/build implementation in the repos reviewed.

### Python

Current public entrypoint:

- `load_prompt(...)`

Supported selectors:

- `id`
- `project + slug`
- `project_id + slug`

Supported modifiers:

- `version`
- `environment`
- `defaults`
- `no_trace`

Behavior:

- rejects `version + environment`
- loading by ID uses `/v1/prompt/{id}`
- loading by project/slug uses `/v1/prompt`
- successful fetches are cached
- cache fallback is skipped when `version` or `environment` is set

Returned object:

- `Prompt`

Prompt capabilities:

- `id`, `name`, `slug`, `version`, `options`
- `from_prompt_data(...)`
- `build(**kwargs)`

Build behavior:

- always uses Mustache rendering
- no explicit support for `template_format`
- no attachment-hydration equivalent to JS `buildWithAttachments`
- no `messages` append/merge surface on `build`
- `strict` is passed as a keyword inside `build_args`, not as a separate method parameter

Important doc/code mismatch:

- The docs show Python examples like `prompt.build({"name": "Alice"}, strict=True)`, but the current method signature is `build(self, **build_args)`, so the real implementation is keyword-argument oriented.

### Ruby

Current entrypoint: `Braintrust::Prompt.load(project:, slug:, version: nil, defaults: {}, api: nil)`

Selector support:

- `project + slug`

Modifier support:

- `version`
- `defaults`

Behavior:

- resolves prompt by listing functions, then fetching a single function
- uses `/v1/function` and `/v1/function/{id}`, not `/v1/prompt`

Returned object:

- `Braintrust::Prompt`

Prompt capabilities:

- `id`, `name`, `slug`, `project_id`
- `prompt`, `messages`, `tools`, `model`, `options`, `template_format`
- `build(...)`

Build behavior:

- supports explicit hash or keyword args
- supports `strict`
- supports template formats:
  - `mustache`
  - `none`
  - `nunjucks` is recognized but intentionally unsupported and raises
- merges params into top-level output
- parses tools JSON

Ruby is a decent prompt load/build implementation, but it is not aligned with the JS/Python prompt loading path or selector set.

### Java

Current entrypoint: `BraintrustPromptLoader.load(...)`

Selector support:

- prompt slug
- optional project name
- optional version

Modifier support:

- defaults

Behavior:

- loads through `BraintrustApiClient.getPrompt(projectName, slug, version)`
- current API client uses `/v1/prompt?project_name=...&slug=...&version=...`

Returned object:

- `BraintrustPrompt`

Prompt capabilities:

- `renderMessages(parameters)`
- `getOptions()`

Build-like behavior:

- rendering and option merging are separate operations
- Mustache only
- no strict mode
- no `template_format`
- no load by ID
- no environment selection
- no cache layer

Java currently provides a partial prompt loading story rather than a full prompt object API.

### Research Conclusion For Loading

A future spec will need to normalize at least:

- selector inputs: `id`, `projectName/project`, `projectId`, `slug`
- modifiers: `version`, `environment`, `defaults`, `noTrace`
- build behavior
- cache semantics
- template-format semantics

JS is the clearest normative target. Python is close but not fully aligned. Ruby and Java are materially narrower.

## Workflow 3: Invoking Prompts

### Backend capability

The backend invocation plane is broader than the SDK public surfaces.

Backend already supports prompt invocation by:

- `function_id`
- `project_name + slug`
- `prompt_session_id + prompt_session_function_id`
- `inline_prompt`

and also supports:

- `version`
- `messages`
- `strict`
- `stream`
- `mode`
- `overrides`
- `mcp_auth`

### JavaScript

Current public entrypoint: `invoke(...)` in `js/src/functions/invoke.ts`.

Supported identifiers:

- `function_id`
- `projectName + slug`
- `globalFunction`
- `promptSessionId + promptSessionFunctionId`

Supported execution args:

- `input`
- `messages`
- `metadata`
- `tags`
- `parent`
- `stream`
- `mode`
- `strict`
- `version`
- `projectId` via `x-bt-project-id`

Notably absent from the public JS invoke surface:

- `environment`
- `inline_prompt`
- `overrides`
- `mcp_auth`

### Python

Current public entrypoint: `invoke(...)` in `py/src/braintrust/functions/invoke.py`.

Supported identifiers:

- `function_id`
- `project_name + slug`
- `global_function`
- `prompt_session_id + prompt_session_function_id`

Supported execution args:

- `input`
- `messages`
- `metadata`
- `tags`
- `parent`
- `stream`
- `mode`
- `strict`
- `version`
- `project_id` via `x-bt-project-id`

Notably absent from the public Python invoke surface:

- `environment`
- `inline_prompt`
- `overrides`
- `mcp_auth`

### Ruby

Current low-level invoke surface is `API::Functions#invoke(id:, input:)`.

There is no prompt-oriented top-level `invoke(project:, slug:, ...)` implementation in the repo matching the current deploy docs.

Higher-level Ruby helpers exist for:

- remote task wrappers
- remote scorer wrappers

but not a JS/Python-style prompt invoke API.

### Java

Current low-level invoke surface is `BraintrustApiClient.invokeFunction(functionId, request)`, which calls `/v1/function/{function_id}/invoke`.

There is no prompt-specific `invokePrompt(projectName, slug, ...)` helper in the Java SDK.

### Docs/Code Mismatches Around Invocation

The docs currently describe a broader prompt invocation surface than the code reviewed here.

Examples:

- `braintrust/docs/deploy/prompts.mdx` documents `invoke(..., environment=...)`
- current JS and Python `invoke(...)` implementations do not expose `environment`
- `braintrust/docs/deploy/prompts.mdx` shows Ruby `Braintrust.invoke(...)`
- the Ruby SDK repo reviewed here does not appear to implement that top-level invoke surface
- `braintrust/docs/evaluate/write-prompts.mdx` shows `logger.invoke("summarizer", ...)`
- the JS and Python SDK repos reviewed here do not expose a corresponding logger method in the main logger implementations

These look like either:

- docs ahead of SDK implementation, or
- parallel code paths not present in the repos reviewed

For a spec, these mismatches must be resolved explicitly.

## Cross-Language Matrix

| Capability | JS | Python | Ruby | Java |
|---|---|---|---|---|
| High-level `project.prompts.create(...)` | Yes | Yes | No | No |
| Prompt authoring `templateFormat` | Yes | No | N/A | N/A |
| Prompt authoring `environments` | Yes | No | No | No |
| Load by prompt ID | Yes | Yes | No | No |
| Load by project + slug | Yes | Yes | Yes | Yes |
| Load by environment | Yes | Yes | No | No |
| Cache loaded prompts | Yes | Yes | No obvious cache | No obvious cache |
| Prompt object `build()` | Yes | Yes | Yes | No single build method |
| `template_format = none` on build | Yes | No | Yes | No |
| `template_format = nunjucks` | Yes, addon-based | No | Recognized but unsupported | No |
| Attachment-aware prompt build | Yes | No | No | No |
| Public prompt invoke by project + slug | Yes | Yes | No | No |
| Public prompt invoke by ID | Yes | Yes | Low-level only | Low-level only |
| Public invoke `environment` | No | No | No | No |
| Public invoke `inline_prompt` | No | No | No | No |

## Important Gaps To Decide In The Spec

### 1. What is the normative invoke surface?

The backend already supports:

- slug-based prompt invocation
- ID-based invocation
- prompt-session invocation
- inline prompt invocation

The public SDKs only expose a subset of that.

The spec should decide whether inline prompt invocation is in scope for the prompt spec or intentionally out of scope.

### 2. Should `environment` be part of prompt invocation?

The docs say yes. The current JS/Python invoke implementations say no.

Because prompt loading already supports `environment`, a spec should decide whether invocation must support it directly or whether callers are expected to:

1. `loadPrompt(environment=...)`
2. then execute separately

That second model is not how the docs currently describe deployed prompts.

### 3. What is the canonical prompt-loading backend path?

Current implementations differ:

- JS/Python: `/v1/prompt`
- Ruby: `/v1/function`
- Java: `/v1/prompt`

The spec should likely normalize on prompt objects rather than generic function lookup for prompt loading, while still allowing equivalent implementations if behavior matches.

### 4. What is the canonical prompt object shape and build contract?

Current implementations differ on:

- strict mode
- template formats
- extra message merging
- tool parsing
- attachment hydration
- whether build is one method or split across `renderMessages()` and `getOptions()`

This is one of the most important parts of the eventual spec.

### 5. What is the minimum cross-language authoring API?

Current JS authoring is richer than Python, and Ruby/Java do not match at all.

If the spec is meant to drive convergence, it should probably standardize:

- prompt contents: `prompt` xor `messages`
- `model`
- `params`
- `tools`
- `metadata`
- `tags`
- `templateFormat`
- `environments`

## Suggested Direction For The Future Spec

The eventual PR2-style spec should probably:

1. Treat prompt authoring, prompt loading/building, and prompt invocation as three separate public API sections.
2. Use the backend prompt data model as the wire-format source of truth.
3. Make JS the behavioral reference point where current SDKs differ, unless backend behavior or docs clearly imply a different target.
4. Call out doc/code gaps as explicit decisions rather than silently inheriting one side.
5. Distinguish required cross-language semantics from optional language-specific ergonomics.

## Concrete Findings To Carry Into Spec Drafting

- Prompt storage and prompt execution are different backend surfaces and should be spec'd separately.
- Prompt execution is function execution, so prompt invoke APIs should either wrap or mirror function invocation semantics.
- `environment` is already first-class in prompt loading, and likely needs a clear spec position for invocation too.
- Prompt authoring currently has the most complete shape in JavaScript.
- Prompt loading/building currently has the most complete shape in JavaScript.
- Python is close enough that a convergence spec is realistic, but it has several concrete parity gaps.
- Ruby and Java currently look more like partial implementations than full prompt SDKs.

## Proposed Next Step

Use this research to draft a separate spec doc with these top-level sections:

- Overview
- Public API
- Behavior
- Wire Format
- Examples
- Open Questions / Non-goals
