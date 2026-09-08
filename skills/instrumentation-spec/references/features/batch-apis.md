# Batch APIs

This document defines Braintrust instrumentation for asynchronous provider
batch APIs. A batch API accepts many model requests as a long-running job and
exposes its results later, often through result files, polling, or a webhook.

This document does not apply to synchronous APIs that accept several inputs in
one request. For example, an embedding request containing multiple inputs is
still one request and follows [Embedding APIs](embeddings.md).

## Provider API ownership

The guide's [manual capture rules](../instrumentation-guide.md#manual-capture-for-excluded-apis)
apply. The start and collect APIs below specialize that two-part lifecycle for
batches: capture inputs at submission, then capture results and end the same
spans when the caller supplies the outcome.

Braintrust batch instrumentation **MUST NOT** make provider API calls. In
particular, it **MUST NOT**:

- submit, cancel, or retrieve a batch;
- upload, download, or retrieve provider files;
- poll provider status;
- register or receive provider webhooks; or
- accept a provider client or callback in order to perform any of these actions
  on the caller's behalf.

The caller owns every provider interaction and passes the resulting request
parameters, batch objects, input records, result records, errors, or streams to
the Braintrust API. Instrumentation-only failures **MUST NOT** prevent, retry,
or otherwise change the caller's provider operation.

A start API may need to add trace context to an outbound provider request. It
**MAY** return a copy of provider-ready request parameters, an opaque context
for the caller to attach, or another provider-appropriate carrier. The caller,
not Braintrust, sends that data to the provider. Implementations **SHOULD NOT**
mutate caller-owned request objects when the language permits returning a copy.

## Explicit instrumentation only

Batch APIs are subject to the guide's general
[auto-instrumentation eligibility rules](../instrumentation-guide.md#auto-instrumentation-eligibility),
which also exclude non-batch submit-and-wait and detached task APIs.

Provider and framework auto-instrumentation **MUST NOT** create batch task or
child spans for asynchronous batch lifecycle methods. This includes batch
create, retrieve, list, cancel, file, polling, and webhook APIs.

Batch traces are created only through explicit batch instrumentation APIs.
Using an explicit batch API while provider auto-instrumentation is enabled
**MUST NOT** duplicate the batch task or its child LLM spans. Generic HTTP or
storage spans produced by instrumentation outside Braintrust's provider
integration are outside the scope of this rule.

## Span model

A batch trace has one parent `task` span and one child `llm` span for each
model request in the batch:

```
task  (<provider>.batch)
├── llm  (request 1)
├── llm  (request 2)
└── llm  (request N)
```

The task represents the asynchronous batch operation. Each child represents
one provider model request and **MUST** follow the applicable completion API
rules for input, output, metadata, metrics, attachments, and errors.

The task **MUST NOT** duplicate all child inputs or outputs. It **MAY** include
allowlisted operation-level data such as the provider, batch identifier,
endpoint, terminal status, and request counts. Parent token rollups follow
[Token and cost metrics](token-and-cost-metrics.md#data-required-by-insight).

Span names **SHOULD** follow existing names for the provider operation. The
task name **SHOULD** identify the provider and batch operation; child names
**SHOULD** match the equivalent non-batch model call.

## Start API

When a provider offers a reliable way to carry context from submission to
collection, its integration **SHOULD** expose a start API. The start API:

1. accepts the caller-supplied batch inputs and provider request parameters;
2. starts one pending `task` span;
3. starts one pending child `llm` span per valid batch request;
4. injects or returns resumable trace context when the provider supports an
   appropriate carrier; and
5. returns without calling the provider.

Pending spans have a `metrics.start` value and no `metrics.end`. Child input
and request metadata are captured according to the equivalent non-batch API.
The start API **MUST NOT** retain live span objects until the provider job
finishes; it must export or otherwise persist enough state to resume them in a
later process.

The start API's exact return type is provider- and language-specific. For
example, one integration may return provider request parameters containing an
injected metadata value, while another returns an opaque context alongside
unchanged request parameters. In every case, the caller performs the provider
submission.

If spans are started before the provider accepts the batch, the integration
**MUST** provide a way for the caller to report a submission failure. Reporting
that failure ends the task and all pending children with the caller-supplied
error. It **MUST NOT** retry the provider submission.

## Resumable context

Start context must contain or deterministically derive enough information for
collection to update the original task and child spans. It **MUST** preserve:

- Braintrust routing and the original trace parent;
- stable task and child span identities;
- the batch start time; and
- enough batch and input identity to reject mismatched collection data.

The mechanism is implementation-specific, but the resulting behavior
**MUST** be idempotent. Repeating collection for the same batch and records
updates the same rows and **MUST NOT** create duplicate spans.

Context sent through provider-controlled metadata **MUST** be bounded and
versioned. It **MUST NOT** contain prompts, model outputs, credentials, API
keys, propagated event data, or other sensitive payloads. It **MUST NOT**
overwrite caller metadata or a caller-owned value that conflicts with the
integration's reserved key. Implementations **SHOULD** integrity-protect the
context when the SDK has an appropriate signing mechanism.

Collection **MUST** validate the context's shape, version, routing data, and
association with the supplied batch and input. Invalid context **MUST NOT** be
used to choose arbitrary span or project identifiers. When feasible, the
integration falls back to [collect-only instrumentation](#collect-only-instrumentation).
Otherwise it skips tracing and emits an SDK diagnostic without affecting the
provider workflow.

## Collect API

Batch integrations **SHOULD** expose a collect API that accepts the
provider data already obtained by the caller. Depending on the provider, this
may include:

- the terminal batch object or status;
- the original batch input records;
- successful result records;
- failed result records;
- a caller-received webhook event; and
- the context returned or injected by start.

The API **MUST NOT** retrieve missing data itself. Provider-native strings,
iterables, asynchronous iterables, responses, and streams **SHOULD** be
accepted when they allow the implementation to avoid unnecessary buffering.

For each correlated result, collection resumes the corresponding child span
and records its output, resolved model, usage metrics, or top-level error. It
then ends the child using the provider's per-request terminal timestamp when
available, otherwise the batch terminal timestamp, otherwise collection time.
An end timestamp **MUST NOT** precede its span's start timestamp.

The task ends only when the supplied data establishes a terminal outcome:

- A non-terminal batch leaves the task and children pending.
- A completed batch with missing or inconsistent results remains pending and
  retryable rather than appearing complete.
- For a failed, expired, or cancelled batch, result spans are completed from
  any available records. Unresolved children and the task end with an error
  describing the terminal batch status.
- A provider submission failure reported after start ends the task and all
  children with that error.

Malformed, duplicate, or unknown item identifiers **MUST NOT** be matched to a
different child. The integration **SHOULD** emit a diagnostic and leave
affected spans retryable when the correct association cannot be established.

## Collect-only instrumentation

An integration **SHOULD** support collection without a prior start call when
the caller supplies enough data to reconstruct the batch and reliably
correlate every input with its result. In this mode, collection creates a new
task and its child LLM spans, populates their inputs and outcomes, and ends
them in the same operation.

The new task uses the active Braintrust parent at collection time. Start and
end timestamps use provider-reported batch or item timestamps when available.
When the provider does not report a valid start timestamp, the integration
uses collection time and **MUST NOT** fabricate the unobserved batch duration.

If the available provider data cannot establish stable item correlation, the
integration **MAY** omit collect-only support. It **MUST NOT** guess associations
from result ordering unless the provider contract guarantees that ordering.
The limitation **SHOULD** be documented by the integration.

## Resource requirements

Provider batches may contain many thousands of requests. Implementations
**MUST** bound transient resource use and avoid keeping the entire trace live
in memory.

- Parse input and result files incrementally when their representation permits
  it. Do not materialize an entire stream solely to split it into records.
- Bound concurrent parsing, attachment processing, span construction, and
  export. SDKs **SHOULD** document or expose a runtime-appropriate concurrency
  setting rather than assuming unbounded parallelism.
- Export or release each span update promptly. Do not retain one live span
  object per item while waiting for the batch to finish.
- Retain only the correlation keys, digests, and normalized payload data needed
  for a later processing phase. Implementations **MAY** use disk-backed state
  when in-memory correlation would be unsafe.
- Keep propagated context independent of the number of batch items; per-item
  identifiers belong in the input data or deterministic derivation, not in one
  ever-growing provider metadata value.
- Do not copy every child payload onto the task span or capture fields beyond
  the allowlists in this specification and the equivalent completion API.

Instrumentation **MUST NOT** silently truncate or automatically sample child
spans. If an implementation has a hard resource limit, reaching it must
produce an explicit diagnostic and leave incomplete work distinguishable and
retryable. It **MUST NOT** report a fully instrumented batch while silently
omitting requests.
