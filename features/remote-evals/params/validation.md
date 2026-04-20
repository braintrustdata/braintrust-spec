# Remote Eval Parameters: Validation

This document describes the scenarios and behaviors that an implementation must support to be considered correct. Each scenario includes the conditions, inputs, and expected outcomes.

---

## 1. Parameter Declaration and Discovery

### 1.1 Evaluator with Parameters Appears in `/list`

**Purpose**: Confirm the Playground receives parameter metadata when fetching available evaluators.

**Conditions**: Dev server running with at least one evaluator that declares parameters.

**Input**: `GET /list`

**Expected**:
- Response is `200 OK`
- Response body is a JSON object
- The evaluator's entry includes a `"parameters"` field with `"type": "braintrust.staticParameters"`
- Each declared parameter appears in the `"schema"` subfield with its `"default"` and `"description"` preserved
- Parameter names match what was declared in the evaluator definition

### 1.2 Evaluator Without Parameters Returns Null

**Purpose**: Confirm evaluators that define no parameters don't break the `/list` response.

**Conditions**: Dev server running with at least one evaluator that declares no parameters.

**Input**: `GET /list`

**Expected**:
- Response is `200 OK`
- The evaluator's entry has `"parameters": null` or omits the field entirely

### 1.3 Mixed Evaluators in Same `/list` Response

**Purpose**: Confirm the presence of parameters-enabled and parameters-free evaluators in the same response.

**Conditions**: Dev server with multiple evaluators, some with parameters and some without.

**Input**: `GET /list`

**Expected**:
- All evaluators appear in the response
- Parameter-enabled evaluators have valid `ParametersContainer` structures
- Parameter-free evaluators have `null` or omitted `parameters`

---

## 2. Parameter Merging

### 2.1 Request Values Override Evaluator Defaults

**Purpose**: Confirm user-supplied values take precedence over code-defined defaults.

**Conditions**: Evaluator declares a parameter with a known default value.

**Input**: `POST /eval` with `parameters: { "<param-name>": "<override-value>" }`

**Expected**: Task function receives `"<param-name>": "<override-value>"` (not the default).

### 2.2 Evaluator Defaults Fill Missing Request Parameters

**Purpose**: Confirm that parameters not sent in the request still reach the task with their default values.

**Conditions**: Evaluator declares parameters A and B with defaults. Request only sends a value for A.

**Input**: `POST /eval` with `parameters: { "A": "override" }`

**Expected**: Task receives `{ "A": "override", "B": <default-value-of-B> }`.

### 2.3 All Defaults Applied When Request Omits `parameters`

**Purpose**: Confirm that omitting `parameters` in the request body still results in defaults being forwarded.

**Conditions**: Evaluator declares parameters with defaults.

**Input**: `POST /eval` with no `parameters` field in the body (or `"parameters": null`).

**Expected**: Task receives all evaluator defaults.

### 2.4 Empty `parameters` Object Treated Same as Absent

**Purpose**: `{}` is equivalent to omitting the field -- both mean "no overrides."

**Conditions**: Evaluator declares parameters with defaults.

**Input**: `POST /eval` with `"parameters": {}`.

**Expected**: Task receives all evaluator defaults (same as scenario 2.3).

### 2.5 Unknown Parameters Passed Through

**Purpose**: Parameters not declared in the evaluator are forwarded without error.

**Conditions**: Evaluator declares parameter A. Request sends parameter A and unknown parameter B.

**Input**: `POST /eval` with `"parameters": { "A": "x", "B": "y" }`.

**Expected**: Task receives `{ "A": "x", "B": "y" }`. No error is returned.

---

## 3. Task and Scorer Access

### 3.1 Task That Declares `parameters` Receives Merged Values

**Purpose**: Verify end-to-end delivery to the task function.

**Conditions**: Evaluator declares parameter `"suffix"` with default `""`. Task declares and uses `parameters`.

**Input**: `POST /eval` with `"parameters": { "suffix": "!" }`, one test case with `input: "hello"`.

**Expected**: Task output is `"hello!"` (input + suffix from parameters).

### 3.2 Task Without `parameters` Declaration Is Unaffected

**Purpose**: Backward compatibility -- existing tasks must not break.

**Conditions**: Evaluator declares parameters. Task is an existing function that does not declare a `parameters` argument.

**Input**: `POST /eval` with `"parameters": { "suffix": "!" }`.

**Expected**: Task runs successfully. Task does not receive `parameters` and is not affected by it.

### 3.3 Scorer That Declares `parameters` Receives Merged Values

**Purpose**: Verify scorers can access parameters, not just tasks.

**Conditions**: Evaluator has a scorer that declares `parameters`. Parameter `"threshold"` is sent with value `0.8`.

**Input**: `POST /eval` with `"parameters": { "threshold": 0.8 }`.

**Expected**: Scorer receives `parameters` containing `"threshold": 0.8` and can use it in scoring logic.

### 3.4 Scorer Without `parameters` Declaration Is Unaffected

**Purpose**: Backward compatibility for scorers.

**Conditions**: Evaluator declares parameters. Scorer is written without a `parameters` argument.

**Input**: `POST /eval` with parameters.

**Expected**: Scorer runs successfully and is not affected.

### 3.5 All Scorers Receive Same Parameters

**Purpose**: Confirm consistency when multiple scorers are registered.

**Conditions**: Evaluator has two local scorers -- one that declares `parameters`, one that doesn't.

**Input**: `POST /eval` with parameters.

**Expected**: The scorer with `parameters` declared receives the merged values. The scorer without it runs unchanged. Both produce valid scores.

### 3.6 Remote Scorers Also Receive Parameters

**Purpose**: Confirm Playground-provided remote scorers are also passed parameters.

**Conditions**: Evaluator is run with both local scorers and remote scorers (sent via `"scores"` in the request).

**Input**: `POST /eval` with parameters and `"scores"` containing remote scorer references.

**Expected**: Remote scorer functions also receive the merged parameters (as their SDK/invocation mechanism allows).

---

## 4. No-Parameter Cases

### 4.1 Evaluator Without Parameters Runs Normally

**Purpose**: Evaluators that never defined parameters continue to work.

**Conditions**: Evaluator declares no parameters. Request body has no `"parameters"` field.

**Input**: Standard `POST /eval` request.

**Expected**: Eval completes successfully. Task and scorers are called without parameters.

### 4.2 Task Receives Empty Map When No Parameters Defined

**Purpose**: Tasks that do declare `parameters` get a safe, empty value when the evaluator has no parameter definitions and none were sent.

**Conditions**: Evaluator has no parameter definitions. Task declares `parameters`.

**Input**: `POST /eval` with no `"parameters"` field.

**Expected**: Task receives an empty map (e.g., `{}`), not `null`. Task runs without error.

---

## 5. Correctness of SSE Output

### 5.1 Progress Events Reflect Task Output Using Parameters

**Purpose**: Confirm that the task output visible in the SSE stream reflects parameter usage.

**Conditions**: Task uses a parameter value to modify its output.

**Input**: `POST /eval` with `"parameters": { "suffix": "!" }`, one case with `input: "hello"`.

**Expected**: SSE `progress` event contains `"data"` field with the task's output incorporating the parameter (e.g., `"hello!"`).

### 5.2 Summary Event Is Unaffected by Parameters

**Purpose**: The SSE `summary` event format doesn't change when parameters are in use.

**Conditions**: Evaluator with parameters.

**Input**: `POST /eval` with parameters.

**Expected**: SSE `summary` event has the same structure as without parameters: `{ "scores": {...}, "experiment_name": ..., "experiment_id": ..., "project_id": ... }`.

---

## 6. Error Handling

### 6.1 Invalid `parameters` Type Returns 400

**Purpose**: Guard against malformed requests.

**Conditions**: Request sends `parameters` as a non-object (e.g., a string or array).

**Input**: `POST /eval` with `"parameters": "not-an-object"`.

**Expected**: `400 Bad Request` with a descriptive error message.

### 6.2 Parameters Don't Cause Evaluator Lookup to Fail

**Purpose**: The presence of `parameters` in the request must not interfere with evaluator name resolution.

**Conditions**: Request includes valid `parameters` for an evaluator that does not define any.

**Input**: `POST /eval` targeting a no-parameter evaluator, with `"parameters": { "foo": "bar" }`.

**Expected**: Eval runs normally. No error from unexpected parameters.

---

## 7. Parallel Execution

### 7.1 Parameters Are Consistent Across Parallel Cases

**Purpose**: When an eval runs with parallelism > 1, all cases receive the same parameter values.

**Conditions**: Eval configured with `parallelism: N > 1`. Multiple test cases.

**Input**: `POST /eval` with parameters and multiple test cases.

**Expected**: Each test case's task invocation receives the same merged parameter map. Output reflects consistent parameter usage across all cases.
