# Prompts API

This document specifies a cross-language SDK API for Braintrust prompts.

It is informed by the research in `docs/research/prompts-api-research.md`, but this document is normative where the research note is descriptive.

## Overview

The Prompts API covers three distinct workflows:

1. Defining and publishing prompts via SDK APIs
2. Loading prompts from Braintrust and building them locally
3. Invoking prompts in deployed applications

The canonical public surface is a top-level `prompts` namespace.

Prompt storage and prompt execution are separate backend concerns:

- Prompt storage uses the prompt control plane.
- Prompt execution uses the function invocation plane.

The public SDK API MUST preserve that distinction even if an implementation shares lower-level helpers internally.

## Public API

### Top-level namespace

The canonical public entrypoint is:

```ts
prompts.create(...)
prompts.load(...)
prompts.invoke(...)
```

Languages MAY provide additional ergonomic aliases, but those aliases are not the normative API.

Examples of allowed aliases:

- `projects.create(...).prompts.create(...)`
- `loadPrompt(...)` as an alias for `prompts.load(...)`
- `prompt.invoke(...)` on a loaded prompt object

### Selectors

A prompt is identified by exactly one of these selectors:

```ts
type PromptSelector =
  | { id: string }
  | { project: string; slug: string }
  | { projectId: string; slug: string };
```

Version selection and environment selection are modifiers on a selector:

```ts
type PromptResolution = {
  version?: string;
  environment?: string;
};
```

`version` and `environment` are mutually exclusive.

### Authoring

In this spec, `prompts.create(...)` creates a local draft prompt. It does not perform network I/O.

```ts
type PromptContent =
  | {
      type: "chat";
      messages: MessageTemplate[];
    }
  | {
      type: "completion";
      content: string;
    };

type PromptTool = SavedToolRef | RawToolDefinition;

type PromptCreateArgs = {
  project?: string;
  projectId?: string;
  id?: string;
  name: string;
  slug?: string;
  description?: string;
  content: PromptContent;
  model: string;
  params?: ModelParams;
  tools?: PromptTool[];
  parser?: ParserSpec;
  templateFormat?: "mustache" | "nunjucks" | "none";
  metadata?: Record<string, unknown>;
  tags?: string[];
  environments?: string[];
  noTrace?: boolean;
};

interface DraftPrompt {
  readonly project?: string;
  readonly projectId?: string;
  readonly id?: string;
  readonly name: string;
  readonly slug: string;
  readonly definition: PromptCreateArgs;

  build(
    input: Record<string, unknown>,
    options?: PromptBuildOptions,
  ): BuiltPrompt;

  publish(options?: PromptPublishOptions): Promise<ResolvedPrompt>;
}

interface PromptPublishOptions {
  ifExists?: "error" | "replace" | "ignore";
}
```

`project` or `projectId` MUST be provided if the draft will be published.

SDKs MAY provide language-specific sugar that accepts `prompt` xor `messages` instead of the canonical `content` tagged union, but the canonical API shape is `content`.

### Loading

`prompts.load(...)` resolves a stored prompt and returns a resolved prompt object.

```ts
type PromptLoadOptions = PromptSelector &
  PromptResolution & {
    defaults?: Record<string, unknown>;
    noTrace?: boolean;
    state?: unknown;
  };

interface ResolvedPrompt {
  readonly id: string;
  readonly projectId?: string;
  readonly name: string;
  readonly slug: string;
  readonly version: string;
  readonly templateFormat: "mustache" | "nunjucks" | "none" | null;
  readonly promptData: PromptData;

  build(
    input: Record<string, unknown>,
    options?: PromptBuildOptions,
  ): BuiltPrompt;

  invoke(
    args: PromptInvokeArgs,
  ): Promise<PromptInvokeResult | PromptInvokeStream>;
}
```

### Building

```ts
type PromptBuildOptions = {
  flavor?: "chat" | "completion";
  strict?: boolean;
  messages?: Message[];
  templateFormat?: "mustache" | "nunjucks" | "none";
};
```

`build(...)` is local compilation. It renders templates, merges defaults and stored parameters, and produces a provider-ready request payload.

Attachment-aware build helpers are OPTIONAL language-specific ergonomics. The required cross-language API is `build(...)`.

### Invocation

`prompts.invoke(...)` is the canonical one-shot execution API.

```ts
type PromptInvokeArgs = {
  input: Record<string, unknown>;
  messages?: Message[];
  metadata?: Record<string, unknown>;
  tags?: string[];
  parent?: ExportedParent;
  stream?: boolean;
  mode?: "auto" | "parallel";
  strict?: boolean;
  state?: unknown;
};

declare const prompts: {
  create(args: PromptCreateArgs): DraftPrompt;
  load(args: PromptLoadOptions): Promise<ResolvedPrompt>;
  invoke(
    selector: PromptSelector & PromptResolution,
    args: PromptInvokeArgs,
  ): Promise<PromptInvokeResult | PromptInvokeStream>;
};
```

`prompts.invoke(...)` MUST accept the same selector forms as `prompts.load(...)`.

The resolved prompt object MAY also expose `prompt.invoke(...)` as an ergonomic instance method. That method is equivalent to calling `prompts.invoke(...)` with the prompt's own concrete identity and version.

## Behavior

### 1. Namespace and import shape

`prompts` is the canonical API namespace. In JavaScript, SDKs SHOULD expose it from the package entrypoint so it can be used as:

```ts
import { prompts } from "braintrust";
```

or:

```ts
import * as braintrust from "braintrust";

braintrust.prompts.load(...);
```

Client-scoped APIs such as `bt.prompts` are allowed, but they are not required by this spec.

### 2. Draft prompts vs resolved prompts

Draft prompts and resolved prompts are different objects with different guarantees.

- A draft prompt is local authoring state.
- A resolved prompt is a stored prompt with a concrete identity and version.

This is a normative API decision in this spec, not a claim about every current SDK surface.

Current SDKs are mixed:

- JavaScript already behaves like a local builder plus separate publish step.
- Python appears close to the same model from the research notes.
- Ruby and Java do not currently expose the same high-level prompt authoring API.

Draft prompts MAY support `build(...)`.

Draft prompts MUST NOT require backend support for inline prompt execution in order to conform to this spec.

### 3. Publishing

`draft.publish(...)` converts a draft prompt into a stored prompt that can later be loaded or invoked by selector.

Publishing MUST preserve:

- `name`
- `slug`
- `description`
- prompt content
- `model`
- `params`
- `parser`
- raw tools
- referenced tool functions
- `templateFormat`
- `metadata`
- `tags`
- `environments`

After successful publish, the returned prompt object MUST include a concrete `id` and `version`.

An implementation MAY persist prompts through a prompt CRUD endpoint, through function-definition publishing with `function_data.type = "prompt"`, or through another equivalent backend path, as long as observable behavior matches this spec.

#### CLI push integration

CLI push workflows are compatible with this model.

In a CLI workflow such as:

```bash
npx braintrust push summarizer.ts
```

the SDK or CLI MAY evaluate the module in a discovery mode, collect draft prompts created by `prompts.create(...)`, and perform the network upload later as part of the push command.

In that workflow:

- `prompts.create(...)` still does not perform network I/O
- the push command is responsible for publishing discovered drafts
- the observable result MUST be equivalent to calling `draft.publish(...)` on each discovered draft

This allows a language SDK to support both explicit runtime publishing and file-based declaration discovery for CLI workflows.

### 4. Resolution

Resolution rules are:

1. If `id` is provided, it takes precedence over project and slug fields.
2. Otherwise exactly one of `project + slug` or `projectId + slug` MUST be provided.
3. `version` and `environment` MUST NOT be provided together.
4. If neither `version` nor `environment` is provided, the latest published version is resolved.

`environment` is part of the normative prompt API for both loading and invocation.

### 5. Build semantics

`build(...)` MUST be deterministic with respect to:

- the prompt definition
- the resolved prompt version, if applicable
- the provided input
- the provided defaults
- the provided build options

Build parameter precedence is:

1. `defaults`
2. stored prompt params
3. stored prompt model

Template format resolution precedence is:

1. `build(..., { templateFormat })`
2. stored prompt `templateFormat`
3. `"mustache"`

`strict` applies to template rendering and parameter rendering.

`build(...)` MUST support both chat and completion prompts.

For chat prompts:

- runtime `messages` are appended after stored prompt messages
- runtime `messages` MUST NOT introduce an additional system message if the stored prompt already contains a system message

For completion prompts:

- runtime `messages` are invalid

If a prompt references attachments and the SDK cannot render them in `build(...)`, the SDK MUST fail with a clear error unless it provides an explicit attachment-aware build helper.

### 6. Trace metadata

By default, `build(...)` SHOULD include prompt trace metadata in the built request payload when the language SDK supports tracing.

That metadata MUST identify the prompt artifact being built, including:

- prompt id, if known
- project id, if known
- version, if known
- rendered variables

If `noTrace` is set on the prompt handle, trace prompt metadata MUST be omitted.

### 7. Invocation semantics

`prompts.invoke(...)` is equivalent to:

1. resolve the prompt selector using the provided `version` or `environment`
2. execute that resolved prompt through the function invocation plane

The public prompt API MUST remain prompt-centric even if the transport is implemented as generic function invocation.

Invocation MUST support:

- `input`
- `messages`
- `metadata`
- `tags`
- `parent`
- `stream`
- `mode`
- `strict`
- `version`
- `environment`

If `stream` is false or omitted, `prompts.invoke(...)` returns a final result.

If `stream` is true, `prompts.invoke(...)` returns a stream object.

The prompt API does not require callers to manually `load(...)` before `invoke(...)`.

### 8. Caching

SDKs MAY cache successfully loaded prompts.

If an SDK caches prompt loads:

- the cache key MUST include the selector and the concrete resolved version
- `defaults` and `noTrace` MUST NOT change prompt identity
- stale cache fallback MUST NOT be used when `version` or `environment` is specified

The spec does not require a cache for prompt invocation.

### 9. Errors

SDKs MUST fail with clear errors for:

- invalid selector combinations
- `version` plus `environment`
- missing required selector fields
- prompt not found
- multiple prompts resolved for a supposedly unique selector
- `messages` used with a completion prompt
- unsupported template formats
- attempts to build attachments without an attachment-aware helper, if required

## Wire Format

### Prompt object

The wire-format source of truth for prompt data is the backend prompt data model.

Canonical prompt data fields are:

- `prompt`
- `options`
- `parser`
- `tool_functions`
- `template_format`
- `mcp`

The prompt content block is a tagged union:

```json
{ "type": "chat", "messages": [...], "tools": "..." }
```

or:

```json
{ "type": "completion", "content": "..." }
```

The canonical mapping from public API to wire format is:

- `content.type = "chat"` -> `prompt_data.prompt = { type: "chat", messages, tools? }`
- `content.type = "completion"` -> `prompt_data.prompt = { type: "completion", content }`
- `model` and `params` -> `prompt_data.options`
- raw tool definitions -> `prompt_data.prompt.tools`
- saved tool references -> `prompt_data.tool_functions`
- `templateFormat` -> `prompt_data.template_format`
- `parser` -> `prompt_data.parser`

### Stored prompt transport

The preferred storage surface is the prompt control plane:

- `GET /v1/prompt`
- `GET /v1/prompt/{prompt_id}`
- corresponding create/update endpoints

Implementations MAY use another equivalent backend transport if the resulting prompt object behavior matches this spec.

### Published function representation

When a prompt is published as a function definition, the canonical representation is:

```json
{
  "project_id": "...",
  "name": "...",
  "slug": "...",
  "description": "...",
  "function_data": { "type": "prompt" },
  "prompt_data": { "...": "..." },
  "if_exists": "replace",
  "tags": ["..."],
  "metadata": { "...": "..." },
  "environments": [{ "slug": "production" }]
}
```

That representation is valid so long as it preserves the same public behavior as prompt CRUD.

### Invocation transport

There is no dedicated prompt invoke endpoint in this spec.

Prompt execution is transported through the function invocation plane. Supported backend transports include:

- `POST /function/invoke`
- `POST /v1/function/{function_id}/invoke`

The canonical invocation request shape includes:

- prompt selector fields
- `version` or `environment`
- `input`
- `messages`
- `metadata`
- `tags`
- `parent`
- `stream`
- `mode`
- `strict`

## Examples

### Define and publish a prompt

```ts
import { prompts } from "braintrust";

const draft = prompts.create({
  project: "support",
  name: "Summarizer",
  slug: "summarizer",
  description: "Summarize a support conversation",
  content: {
    type: "chat",
    messages: [
      {
        role: "system",
        content: "You are a concise support assistant.",
      },
      {
        role: "user",
        content: "Summarize this conversation: {{conversation}}",
      },
    ],
  },
  model: "gpt-5",
  params: {
    temperature: 0.2,
  },
  templateFormat: "mustache",
  environments: ["production"],
});

const prompt = await draft.publish({ ifExists: "replace" });
```

### Load and build a prompt

```ts
import { prompts } from "braintrust";

const prompt = await prompts.load({
  project: "support",
  slug: "summarizer",
  environment: "production",
  defaults: {
    locale: "en-US",
  },
});

const built = prompt.build(
  {
    conversation: "Customer cannot log in.",
  },
  {
    strict: true,
  },
);
```

### Invoke a prompt directly

```ts
import { prompts } from "braintrust";

const result = await prompts.invoke(
  {
    project: "support",
    slug: "summarizer",
    environment: "production",
  },
  {
    input: {
      conversation: "Customer cannot log in.",
    },
    strict: true,
  },
);
```

### Compatibility aliases

These are equivalent, if a language SDK chooses to provide the aliases:

```ts
prompts.load({ project: "support", slug: "summarizer" });
```

```ts
loadPrompt({ projectName: "support", slug: "summarizer" });
```

and:

```ts
prompts.create({
  project: "support",
  name: "Summarizer",
  content: { type: "completion", content: "Summarize: {{text}}" },
  model: "gpt-5",
});
```

```ts
projects.create({ name: "support" }).prompts.create({
  name: "Summarizer",
  prompt: "Summarize: {{text}}",
  model: "gpt-5",
});
```

and:
draft.publish({ ifExists: "replace" });
```

## Open Questions And Non-goals

### Non-goals

The following are out of scope for Prompts API v1:

- inline prompt invocation as a public prompt API
- prompt-session-scoped function identifiers
- arbitrary invoke-time prompt overrides
- language-specific local code-function publishing semantics

Those capabilities MAY exist in lower-level function APIs without being part of the prompt API.

### Open questions

These questions remain open for a future revision:

- whether prompt CRUD should be specified as first-class public methods such as `prompts.get`, `prompts.update`, and `prompts.delete`, or whether `create` plus `publish` plus `load` is sufficient for SDK v1
- whether attachment-aware build should eventually become required rather than optional
