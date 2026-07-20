# Remote Eval Parameters: Design

## Overview

Eval parameters are **declared** in the user's application (in code), **discovered** by the Braintrust UI (via the application's `GET /list`), then finally **executed** by the application (via `POST /eval`).

```
Phase 1: Declaration (code)
  Developer writes evaluator with parameter specs
       |
       v
Phase 2: Discovery (GET /list)
  Playground fetches evaluator metadata
  Dev server serializes parameter specs to JSON schema
  Playground renders UI controls
       |
       v
Phase 3: Execution (POST /eval)
  Playground sends user-chosen values in request body
  Dev server merges values with evaluator defaults
  Dev server runs the eval with merged values
```

## Components

### Evaluator

*In the SDK...*

An evaluator defines the template for an eval. It also defines parameters, their defaults, and their descriptions. This is the single source of truth -- the UI reads from it and the runtime uses it to execute evals.

During `GET /list`, the dev server reads parameter specs from each evaluator and serializes them for the Playground.

During `POST /eval`, the dev server reads the same specs to extract default values for any parameters the user didn't override.

### Dev Server

#### `GET /list`

Serializes each evaluator's parameter specs into the format the Playground expects. See [contracts.md](contracts.md) for the exact schema.

The serialization must preserve:

- Parameter names (keys)
- Types (e.g., `"data"` for generic values)
- Default values
- Descriptions

#### `POST /eval`

Responsible for merging request parameters with evaluator defaults and forwarding the merged result to the task and scorers.

##### Merging parameters

The merge is straightforward:

1. Collect default values from the evaluator's parameter specs (one per named parameter)
2. Overlay the request's `"parameters"` object on top (request values override defaults)
3. Forward the merged result

```
defaults = { "model": "gpt-4", "temperature": 0.7 }
request  = { "model": "gpt-4o" }
merged   = { "model": "gpt-4o", "temperature": 0.7 }
```

Parameters not present in the request keep their defaults. Parameters sent by the request but not declared in the evaluator are passed through as-is (do not reject unknown keys).

If neither the request nor the evaluator defines a value for a parameter, omit it from the merged result. Do not pass `null` or `undefined` for undeclared parameters.

##### Executing an eval

The merged parameters must be passed to both the task function and all scorer functions (both local scorers defined in the evaluator and remote scorers sent by the Playground).

**Backward compatibility is critical.** Tasks and scorers that do not declare they want parameters must not break. How this compatibility is implemented is language-specific (e.g., Ruby uses a `KeywordFilter` to filter out parameters; Python and JavaScript pass parameters via a `hooks` object that callers can ignore).

##### When no parameters are defined

If the evaluator defines no parameters and the request body contains no `"parameters"` field, the task and scorers receive no parameters (or an empty value, depending on language conventions). Callers that don't declare `parameters` in their signature are unaffected.

If the evaluator defines parameters but the request body omits the `"parameters"` field, apply evaluator defaults only (treat the request as if it sent `{}`).

### Tasks

The task function may optionally accept a `parameters` argument. If it does, it receives the merged parameter values as a plain key-value mapping with string keys. If it does not, it runs unchanged.

### Scorers

Same as task functions. Both local scorers and remote scorers can optionally access parameters. The same merged parameter values are passed to all scorers.

## Design Decisions

### String keys

Parameters arrive as JSON from the Playground, so they naturally have string keys. Evaluator definitions may use language-idiomatic key types (e.g., symbol keys in Ruby), but the merged result forwarded to task/scorer functions must always use string keys, consistent with the JSON origin.

### Requests override defaults

When both the request and the evaluator define a value for the same parameter, the request wins. This allows the Playground to be the authoritative source of runtime configuration without requiring the evaluator to hardcode values.

### No type coercion required for basic implementation

For simple parameters (strings, numbers, booleans), the value from the request can be used as-is without additional type validation. More advanced implementations may choose to validate or coerce types using the parameter's declared type, but this is not required for baseline correctness.

### Prompt parameters are a special case

The Playground defines a `"prompt"` parameter type that carries a full prompt definition (messages, model settings, etc.) rather than a scalar value. When a prompt parameter is sent, its value is a structured JSON object conforming to the prompt data schema.

SDKs that support prompt parameters may deserialize this JSON into a higher-level `Prompt` object that provides template rendering. SDKs that don't yet support this type can pass the raw JSON object through as-is. Tasks that access a prompt parameter must be aware of the form it takes.

For a baseline implementation, supporting `"data"` type (generic values) is sufficient. `"prompt"` type support can be added later.

### Evaluator parameters are optional

Evaluators that don't define parameters continue to work as before. The `parameters` field in both `GET /list` and `POST /eval` is optional. An evaluator without parameters responds to `GET /list` with `"parameters": null` (or omits the field).

## Process Flow

```
Playground                    Dev Server                  Evaluator
    |                              |                           |
    |  GET /list                   |                           |
    |----------------------------->|                           |
    |                              | read parameter specs      |
    |                              |<--------------------------|
    |                              |                           |
    |  200 { "eval-name": {        |                           |
    |    parameters: { ... } } }   |                           |
    |<-----------------------------|                           |
    |                              |                           |
    |  Render UI controls          |                           |
    |  User adjusts params         |                           |
    |                              |                           |
    |  POST /eval                  |                           |
    |  { parameters: {             |                           |
    |     "model": "gpt-4o" } }   |                           |
    |----------------------------->|                           |
    |                              | read defaults from specs  |
    |                              |<--------------------------|
    |                              |                           |
    |                              | merge: request + defaults |
    |                              | = { "model": "gpt-4o",   |
    |                              |     "temp": 0.7 }        |
    |                              |                           |
    |                              | run task with merged params
    |                              |-------------------------->|
    |                              |                           | task(input, parameters)
    |                              |                           |
    |                              | run scorers with merged params
    |                              |-------------------------->|
    |                              |                           | scorer(input, expected, output, parameters)
    |                              |                           |
    |  SSE: progress events        |                           |
    |<-----------------------------|                           |
    |  SSE: summary                |                           |
    |<-----------------------------|                           |
    |  SSE: done                   |                           |
    |<-----------------------------|                           |
```
