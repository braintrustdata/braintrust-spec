# Remote Evals -- Overview

## What Are Remote Evals?

Remote evals let users run evaluations on their own infrastructure while using Braintrust's [Playground](https://www.braintrust.dev/docs/playground) for iteration, comparison, and analysis. Evaluation code runs on the user's servers or local machine, and the Braintrust Playground sends parameters and receives results through a simple HTTP interface.

If an evaluation can run entirely inside the Braintrust Playground (e.g., a single prompt call), remote evals are not needed. Remote evals exist for cases where the evaluation logic must run outside of Braintrust:

- **Agentic workflows** -- Multi-step agent flows or complex task logic beyond a single prompt.
- **Custom infrastructure** -- Access to internal APIs, databases, or services that can't run in the cloud.
- **Specific runtime environments** -- Custom dependencies, system libraries, or environment configurations.
- **Security or compliance** -- Data that must remain on the user's infrastructure.
- **Long-running evaluations** -- Complex processing that exceeds typical cloud execution timeouts.

The Playground handles dataset management, scoring, comparison, and visualization. The user's code handles task execution.

See the [Braintrust documentation on remote evals](https://www.braintrust.dev/docs/evaluate/remote-evals) for the full product guide.

## How It Works

The user experience is:

1. Write an evaluator that defines a **task** (the code under test) and optionally **scorers** and **parameters**.
2. Start a local dev server (defaults to `http://localhost:8300`).
3. In the Braintrust Playground, select "Remote eval" as the task type and choose the evaluator.
4. Configure parameters via UI controls, pick a dataset, and click "Run".
5. Results stream back in real-time; scores and experiment data appear in the Playground.

Under the hood, this is a straightforward HTTP interaction between the Braintrust UI (client) and the dev server (server):

```
 Braintrust Playground                     Developer's Machine
+----------------------+                 +-------------------------+
|                      |  GET /list      |   Dev Server (:8300)    |
|  Discover evaluators | --------------> |                         |
|  and their params    | <-------------- |  Evaluator Registry     |
|                      |  JSON response  |  +-------------------+  |
|                      |                 |  | "food-classifier"  |  |
|  User clicks "Run"   |  POST /eval     |  |   task: classify() |  |
|  with dataset +      | --------------> |  |   scorers: [...]   |  |
|  parameters          |                 |  +-------------------+  |
|                      |  SSE stream     |                         |
|  Real-time results   | <-------------- |  Execute task per case  |
|  per test case       |                 |  Run scorers            |
|                      |                 |  Stream results         |
+----------------------+                 +------+------------------+
                                                |
                                                | Export spans
                                                v
                                         +-------------------------+
                                         | Braintrust API          |
                                         | Experiment storage      |
                                         +-------------------------+
```

The dev server exposes three endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Health check -- confirms the server is running |
| `GET /list` | Returns registered evaluators with their scorer names and parameter definitions |
| `POST /eval` | Executes an evaluator against provided data; streams results as SSE events |

## Key Concepts

**Evaluator** -- A named unit that pairs a task with scorers. The name is how the Playground identifies and dispatches to it.

**Task** -- The code under test. A callable that receives an `input` and returns an output. This is typically the AI model, agent, or pipeline being evaluated.

**Scorer** -- A function that grades a task's output. Receives the `input`, `expected` output, and actual `output`; returns a numeric score (typically 0.0--1.0). Each scorer has a unique name. The dev server can define local scorers, and the Playground can add additional remote scorers -- both sets run during evaluation.

**Parameters** -- Optional configurable inputs declared by the evaluator (e.g., temperature, model name, prompt template). These render as UI controls in the Playground, letting users tweak settings and compare runs without changing code.

**Dev Server** -- A lightweight HTTP server (default port 8300) that hosts evaluators and implements the protocol the Braintrust Playground expects.

## Example

```
# 1. Define an evaluator with a task, scorer, and parameters
evaluator = Evaluator(
    task = (input) => MyModel.classify(input),
    scorers = [
        Scorer("exact_match", (expected, output) => output == expected ? 1.0 : 0.0)
    ],
    parameters = {
        "model": { type: "string", default: "gpt-4", description: "Model to use" },
        "temperature": { type: "number", default: 0.7, description: "Sampling temperature" }
    }
)

# 2. Start the dev server
server = DevServer(
    evaluators = { "food-classifier": evaluator },
    port = 8300
)
```

From the Playground, the user selects "food-classifier", adjusts the temperature slider, picks a dataset, and runs. Each test case streams back in real time, and the averaged scores appear in the summary.

## Further Reading

| Document | Purpose |
|----------|---------|
| [design.md](design.md) | System architecture, components, and end-to-end process flows |
| [contracts.md](contracts.md) | API schemas, data types, SSE event formats, CORS policy |
| [validation.md](validation.md) | Test cases and expected behaviors for verifying an implementation |
| [implementation.md](implementation.md) | Phased implementation plan and reference resources |

### External Resources

- [Braintrust: Remote evals guide](https://www.braintrust.dev/docs/evaluate/remote-evals)
- [Braintrust: Run evaluations](https://www.braintrust.dev/docs/evaluate/run-evaluations)
- [Braintrust: Evaluate systematically](https://www.braintrust.dev/docs/evaluate)
