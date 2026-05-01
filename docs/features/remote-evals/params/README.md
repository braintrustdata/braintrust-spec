# Remote Eval Parameters: Overview

## What Are Eval Parameters?

**Eval parameters** let users configure evaluator behavior from the Braintrust Playground without changing code. Developers declare named parameters in their evaluator -- anything that affects how the eval runs: a model name, a similarity threshold, a feature flag, a service URL, a max output length, etc. The Playground renders these as UI controls (sliders, text inputs, etc.) and passes the user's chosen values to the evaluator when running.

This makes it easy to compare how a system behaves under different configurations -- for example, running the same test cases with `temperature: 0.2` vs `temperature: 0.9`, or against a staging vs. production endpoint -- without deploying new code.

## How It Works

```
 Braintrust Playground                     Developer's Machine
+----------------------+                 +-------------------------+
|                      |                 |   Dev Server            |
|  GET /list           | --------------> |                         |
|                      | <-------------- |  "food-classifier":     |
|  Render UI controls: |  parameters:    |    parameters:          |
|    model: [gpt-4 v]  |  { model: ..., |      model: "gpt-4"     |
|    temp:  [0.7  ---] |    temp: ... }  |      temperature: 0.7   |
|                      |                 |                         |
|  User changes model  |                 |                         |
|  to "gpt-4o", clicks |  POST /eval     |                         |
|  "Run"               | --------------> |  parameters:            |
|                      |  parameters:    |    { model: "gpt-4o",   |
|                      |  { model:       |      temperature: 0.7 } |
|                      |   "gpt-4o" }   |                         |
|  Results stream back | <-------------- |  task receives params   |
+----------------------+                 +-------------------------+
```

1. **Declaration**: The developer declares named parameters in the evaluator definition. Each parameter has a name, optional type, default value, and description.
2. **Discovery**: When the Playground fetches `GET /list`, the dev server includes parameter definitions in the response. The Playground renders appropriate UI controls for each parameter.
3. **Delivery**: When the user clicks "Run", the Playground sends the current parameter values in the `POST /eval` request body under the `"parameters"` key.
4. **Merging**: The dev server merges request values with evaluator defaults (request overrides defaults). This means parameters not changed by the user still have their default values.
5. **Forwarding**: The merged parameters are forwarded to the task function and all scorer functions as they run.

## Key Concepts

**Parameter definition** -- A declaration in the evaluator specifying a parameter's name, default value, and optional metadata (type, description). Defined once in code; used to populate UI controls.

**Parameter values** -- The runtime values the Playground sends per-run. These override any defaults defined in the evaluator.

**Backward compatibility** -- Tasks and scorers that do not declare they want parameters must continue to work unchanged. The SDK is responsible for filtering parameters out of function calls to functions that don't expect them.

## Example

```pseudocode
# Define an evaluator with parameters
evaluator = Evaluator(
    task = (input, parameters) => MyModel.classify(input, model: parameters["model"]),
    scorers = [
        Scorer("exact_match", (expected, output) => output == expected ? 1.0 : 0.0)
    ],
    parameters = {
        "model":       { type: "model", default: "gpt-4", description: "Model to use" },
        "temperature": { type: "data",  default: 0.7,     description: "Sampling temperature" }
    }
)
```

The Playground renders a model picker and temperature input. When the user selects "gpt-4o" and clicks "Run", the task receives `parameters = {"model": "gpt-4o", "temperature": 0.7}` (temperature keeps its default since the user didn't change it).

## Parameters vs. Input

**Input** is per-case data — each test case has its own `input` value (e.g., `"apple"`, `"carrot"`). It varies case-by-case and represents *what* is being evaluated.

**Parameters** are per-run configuration — the same values apply to every test case in the run. They represent *how* the evaluator behaves.

The typical workflow: run the same dataset (same inputs) with different parameter values to compare configurations. For example, run `model: "gpt-4"` and `model: "gpt-4o"` against identical test cases, then compare scores side-by-side in the Playground.

## Further Reading

| Document | Purpose |
|----------|---------|
| [design.md](design.md) | End-to-end flow, component roles, and design decisions |
| [contracts.md](contracts.md) | Wire protocol, data types, and API schemas |
| [validation.md](validation.md) | Test scenarios and expected behaviors |

### Related Specs

- [Remote Eval Dev Server](../server/README.md) -- The broader remote eval feature this builds on
