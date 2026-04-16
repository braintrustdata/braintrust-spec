# BTX Implementation Guide

This guide describes how to implement the BTX (Braintrust Cross-language) test runner for a new SDK.  Follow it end-to-end and you will have a self-contained test suite that validates your SDK's instrumentation against the same YAML specs used by every other language.

---

## What you are building

A test suite that lives inside your SDK repo and does the following for each YAML spec file:

1. **Fetches the spec** from `braintrustdata/braintrust-spec` at a pinned ref (cached locally).
2. **Executes the spec in-process** — makes real provider API calls (OpenAI, Anthropic, …) wrapped with Braintrust instrumentation.
3. **Validates spans** by either:
   - **Live mode** (default): fetches spans back from the Braintrust backend via BTQL and compares them against the spec's `expected_brainstore_spans`.
   - **VCR/replay mode** (CI): replays recorded HTTP cassettes, captures spans in-memory, compares in-memory.

### Two reference implementations

| Language | Repository | Path |
|---|---|---|
| Python | [braintrustdata/braintrust-sdk-python](https://github.com/braintrustdata/braintrust-sdk-python) | `py/src/braintrust/btx/` |
| Java | [braintrustdata/braintrust-sdk-java](https://github.com/braintrustdata/braintrust-sdk-java) | `btx/src/test/java/dev/braintrust/sdkspecimpl/` |

Read these alongside this guide. The Python implementation is the simplest to follow.

---

## Directory layout

Suggested layout (adapt to your language's conventions):

```
<sdk-repo>/
  btx/                         # or tests/btx/, or inline with test files
    spec-ref.txt               # pinned braintrust-spec ref, e.g. v0.0.1
    fetch-spec.sh              # downloads spec tarball (copy from braintrustdata/braintrust-sdk-python)
    .spec-cache/               # gitignored; cached downloaded specs
      v0.0.1/
        test/llm_span/
          openai/completions.yaml
          openai/streaming.yaml
          ...
    cassettes/                 # VCR cassettes, one per spec
      openai/completions.<ext>
      anthropic/messages.<ext>
    spec_loader.<ext>          # YAML parsing + custom tag support
    spec_executor.<ext>        # in-process API calls
    span_fetcher.<ext>         # BTQL fetch with retry
    span_validator.<ext>       # recursive assertion logic
    test_btx.<ext>             # parametrized test runner
```

---

## Step 1: Fetch the spec

### spec-ref.txt

A single line containing the ref to fetch from `braintrustdata/braintrust-spec`:

```
v0.0.1
```

### fetch-spec.sh

Copy [`fetch-spec.sh`](https://github.com/braintrustdata/braintrust-sdk-python/blob/main/py/src/braintrust/btx/fetch-spec.sh) from the Python reference implementation.  It downloads and extracts the tarball from GitHub:

```bash
curl -sfL "https://github.com/braintrustdata/braintrust-spec/archive/$REF.tar.gz" | tar -xzf - ...
```

### Auto-fetch before tests run

The fetch must happen **before test collection** so the test framework can discover spec files when parametrizing tests.  Both reference implementations do this via a hook that runs before any test is collected:

- **Python**: `pytest_configure` hook in `btx/conftest.py` (runs before collection)
- **Java**: `fetchSpec` Gradle task declared as a dependency of the `test` task; `btx.spec.root` system property passed to the JVM

The fetch is idempotent — if `.spec-cache/<ref>/test/llm_span/` already exists, skip the download.  This makes repeated local runs instant.

The `BTX_SPEC_ROOT` environment variable (Python) / `btx.spec.root` JVM property (Java) can override the cache path for CI environments that pre-download specs separately.

---

## Step 2: Parse the spec files

Each file under `test/llm_span/<provider>/<name>.yaml` has this structure:

```yaml
name: completions
type: llm_span_test
provider: openai
endpoint: /v1/chat/completions
requests:
  - model: gpt-4o-mini
    temperature: 0.0
    messages:
      - role: system
        content: you are a helpful assistant
      - role: user
        content: What is the capital of France?
expected_brainstore_spans:
  - metrics:
      tokens: !fn is_non_negative_number
      prompt_tokens: !fn is_non_negative_number
    metadata:
      model: !starts_with "gpt-4o-mini"
      provider: openai
    span_attributes:
      name: Chat Completion
      type: llm
    input:
      - role: user
        content: What is the capital of France?
    output:
      - finish_reason: stop
        message:
          role: assistant
          content: The capital of France is Paris.
```

### Custom YAML tags

The spec uses three custom tags that must be handled by your YAML parser:

| Tag | Argument | Meaning |
|---|---|---|
| `!fn <name-or-expr>` | String | Named predicate or language-native expression |
| `!starts_with <prefix>` | String | The actual value must start with this prefix |
| `!or [...]` | Sequence | The actual value must match at least one alternative |

Parse each into a distinct matcher object (not a string).  Example:

```python
# Python (dataclasses)
@dataclass
class FnMatcher:    expr: str
@dataclass
class StartsWithMatcher: prefix: str
@dataclass
class OrMatcher:    alternatives: list
```

```java
// Java (sealed interface / records)
interface SpecMatcher {
    record FnMatcher(String name) implements SpecMatcher {}
    record StartsWithMatcher(String prefix) implements SpecMatcher {}
    record OrMatcher(List<Object> alternatives) implements SpecMatcher {}
}
```

Register the constructors with your YAML library before loading any files.

### LlmSpanSpec data model

After parsing, represent each spec as a value object:

```
LlmSpanSpec {
  name:                    string          # e.g. "completions"
  type:                    string          # always "llm_span_test" for now
  provider:                string          # "openai" | "anthropic"
  endpoint:                string          # "/v1/chat/completions" | "/v1/messages" | ...
  requests:                list<map>       # one map per API call (raw YAML, passed to SDK)
  expected_brainstore_spans: list<map>     # may contain FnMatcher / StartsWithMatcher / OrMatcher
  display_name:            string          # "<provider>/<name>" — used in test IDs and error messages
}
```

### Walk the spec directory

Recursively find all `*.yaml` files under `test/llm_span/`, sorted for determinism.  Filter to only the providers your SDK supports.  Construct one `LlmSpanSpec` per file.

---

## Step 3: Execute the spec

For each spec, make the API calls described by `spec.requests` under a parent Braintrust span, and return the root span ID.

### The root span

Wrap all API calls for a spec in a single parent span named after `spec.name`.  The returned identifier is used to find child spans in Braintrust (live mode) or to correlate them in memory (VCR mode).

- **Python/TypeScript (non-OTel SDKs)**: use `logger.start_span(name=spec.name)` → returns `root_span.root_span_id` (string like `"span_xxxxxxxx"`)
- **Java/Go and all future OTel-based SDKs**: use `tracer.startSpan(spec.name())` → return `rootSpan.getSpanContext().getTraceId()` (hex string like `"e6f892e37dac9e3ef2f8906d6600d70c"`)

After the span ends, flush the SDK so spans are exported before you attempt to fetch them.

### Dispatch by provider + endpoint

```
provider=openai,  endpoint=/v1/chat/completions  → executeChatCompletions(requests, client)
provider=openai,  endpoint=/v1/responses         → executeResponses(requests, client)
provider=anthropic, endpoint=/v1/messages        → executeAnthropicMessages(requests, client)
```

Raise `NotImplementedError` for combinations you haven't implemented yet.

### Multi-turn requests

Some specs have more than one entry in `requests` (e.g. `reasoning.yaml` has two turns).  Each turn's response must be appended to the conversation history and prepended to the next request's input, so the model has full context.

- **Chat completions**: accumulate `messages` list; prepend to next turn's `messages`.
- **Responses API**: accumulate `input` items; prepend to next turn's `input`.
- **Anthropic messages**: accumulate `messages` list; prepend to next turn's `messages`.

### Streaming

Detect `stream: true` in the request map and call the streaming variant of the API.  The SDK must fully consume the stream before the root span ends so that all chunks are captured.

```python
# Python — consume synchronous stream
with client.messages.create(**req) as stream:
    for _ in stream:
        pass

# Java — consume with try-with-resources
try (var stream = client.chat().completions().createStreaming(params)) {
    stream.stream().forEach(chunk -> {});
}
```

### Attachment handling (inline base64 images)

Some specs pass a `data:image/png;base64,...` URL in a message content part.  Your SDK's instrumentation should convert this to a `braintrust_attachment` reference in the logged span rather than logging the raw base64 blob.  The expected span structure in the spec reflects the converted form.

**OpenAI** (`image_url.url`): the instrumentation replaces the data URL with `{type: braintrust_attachment, content_type, filename, key}`.

**Anthropic** (`source.data` in an image block): the instrumentation replaces the `source` field with `{type: braintrust_attachment, content_type, filename, key}`.

If your SDK does not yet perform this conversion, the `attachments` specs will fail.  That is expected and is a good signal that the SDK needs this feature.

---

## Step 4: Fetch spans from Braintrust (live mode)

After the spec executes and the SDK flushes, the spans are ingested into Braintrust.  Query them back via the BTQL HTTP API.

### BTQL query

```json
{
  "query": {
    "select": [{"op": "star"}],
    "from": {
      "op": "function",
      "name": {"op": "ident", "name": ["project_logs"]},
      "args": [{"op": "literal", "value": "<project_id>"}]
    },
    "filter": {
      "op": "and",
      "left": {
        "op": "eq",
        "left":  {"op": "ident", "name": ["root_span_id"]},
        "right": {"op": "literal", "value": "<root_span_id>"}
      },
      "right": {
        "op": "ne",
        "left":  {"op": "ident", "name": ["span_parents"]},
        "right": {"op": "literal", "value": null}
      }
    },
    "sort": [{"expr": {"op": "ident", "name": ["created"]}, "dir": "asc"}],
    "limit": 1000
  },
  "use_columnstore": true,
  "use_brainstore": true,
  "brainstore_realtime": true
}
```

POST to `$BRAINTRUST_API_URL/btql` with `Authorization: Bearer $BRAINTRUST_API_KEY`.

### Post-processing the results

1. **Filter scorer spans**: remove any span where `span_attributes.purpose == "scorer"` — these are injected by the Braintrust backend and are not part of the SDK instrumentation under test.
2. **Sort by `created` ascending** (the query already does this).
3. **Wait for payload**: a span may arrive before its `output` and `metrics` are indexed. If a span has `output == null && metrics == null`, retry.

### Retry with backoff

Spans may not be immediately available after flushing.  Retry with a fixed interval (30 s) up to a maximum total wait (600 s).  Both reference implementations use this exact timing.

```
while total_wait < 600s:
    result = try_fetch(root_span_id, num_expected)
    if result.ok: return result.spans
    if result.too_many_spans: raise non-retriable error
    sleep(30s)
    total_wait += 30s
raise TimeoutError
```

### Required environment variables

| Variable | Description |
|---|---|
| `BRAINTRUST_API_KEY` | API key for both logging and BTQL queries |
| `BRAINTRUST_API_URL` | API base URL (default: `https://api.braintrust.dev`) |
| `BRAINTRUST_PROJECT` or `BRAINTRUST_DEFAULT_PROJECT_NAME` | Project to log spans into |
| `BRAINTRUST_PROJECT_ID` or `BRAINTRUST_DEFAULT_PROJECT_ID` | Project UUID (optional if name is given) |
| `OPENAI_API_KEY` | Required for OpenAI specs |
| `ANTHROPIC_API_KEY` | Required for Anthropic specs |

---

## Step 5: Validate spans

Compare the list of fetched (or in-memory) spans against `spec.expected_brainstore_spans`.

### Filtering and ordering

Before validating, filter `actual_spans` to LLM spans only (`span_attributes.type == "llm"`).  Sort by `span_attributes.exec_counter` ascending for deterministic ordering across multi-span specs.

Validate `actual_spans[i]` against `expected_brainstore_spans[i]` pairwise.  If `len(actual) < len(expected)`, fail immediately.  Extra actual spans (beyond what the spec expects) are allowed and ignored.

### Recursive validation

```
validate_value(actual, expected, path):
  if expected is OrMatcher:
    try each alternative; pass if any matches; fail with all errors if none match
  if expected is FnMatcher:
    resolve to a callable and invoke it; fail if it returns false
  if expected is StartsWithMatcher:
    assert actual is a string starting with matcher.prefix
  if expected is null:
    pass (don't care)
  if expected is dict:
    assert actual is also a dict
    for each key in expected: validate_value(actual[key], expected[key], path.key)
    extra keys in actual are ignored
  if expected is list:
    assert actual is also a list (or single-item list vs dict — see below)
    assert len(actual) >= len(expected)
    validate pairwise for first len(expected) elements
  else (scalar):
    assert actual == expected
```

**Single-item list vs object special case**: when `expected` is a list of one element that is a dict, and `actual` is a dict (not a list), validate `actual` against `expected[0]`.  This handles providers like Anthropic that return an object for `output` instead of a list of choices.

### Named predicates (`!fn`)

Implement these by name:

| Name | Assertion |
|---|---|
| `is_non_negative_number` | `isinstance(v, (int, float)) and v >= 0` |
| `is_non_empty_string` | `isinstance(v, str) and len(v) > 0` |
| `is_reasoning_message` | `v` is a list (possibly empty) of `{type: "summary_text", text: <non-empty str>}` dicts |

For any other `!fn` expression (e.g. `lambda value: "Paris" in value`):
- **Python/Ruby/dynamic**: `eval()` / `eval` the expression directly — it is a valid expression in the language.
- **Java/Go/static**: treat as "non-null and non-empty" — you cannot evaluate Python lambda strings, so a loose check is acceptable.

### Collect all errors before failing

Do not fail on the first mismatch.  Collect all errors into a list and raise a single assertion at the end that prints every failed path.  This makes debugging much faster.

### Error message format

Include the full path to the failure, the expected value, and the actual value:

```
anthropic/streaming: span validation failed:

--- Span 0 (anthropic.messages.create) ---
span[0].span_attributes.name: expected='anthropic.messages.create', actual='anthropic.messages.stream'

Full span JSON:
{ ... }
```

---

## Step 6: VCR / cassette support (optional but strongly recommended for CI)

### What VCR does

A VCR library intercepts outbound HTTP calls and either records them to cassette files or replays them from cassettes.  With cassettes committed to git, CI runs without any API keys and in milliseconds.

### Mode detection

Detect the current mode from an environment variable or test runner option:

| Mode | Behaviour |
|---|---|
| `replay` / default | Replay cassettes; fail if cassette missing |
| `record` | Make real API calls; write cassettes |
| `off` / `--disable-vcr` | Make real API calls; do not read or write cassettes; validate via BTQL |

### Span capture in replay mode

In replay mode the spans must be captured in-memory rather than fetched from Braintrust (there are no real spans in the backend).

- **Python**: wrap the test in `logger._internal_with_memory_background_logger()`.  This context manager intercepts all spans that would be flushed to the backend and collects them in a list instead.  Drain with `memory_logger.pop()` after the executor returns.
- **Java**: the `TestHarness` class provides an `UnitTestSpanExporter` that buffers exported OTel spans in-memory.  Use `harness.awaitExportedSpans(n)` to drain them, then run them through `SpanConverter.toBrainstoreSpans()` to produce the same format that BTQL would return.

In replay mode, skip the BTQL fetch entirely — use the in-memory spans directly.

### Cassette organisation

Organise cassettes by provider so they are easy to find and update:

```
cassettes/
  openai/
    completions.<ext>
    streaming.<ext>
    tools.<ext>
    reasoning.<ext>
    attachments.<ext>
  anthropic/
    messages.<ext>
    streaming.<ext>
    attachments.<ext>
```

Name cassettes after `<provider>/<spec_name>` so they are stable across refactors of the test function name.

### Recording cassettes for the first time

The exact command depends on your language's VCR library.  Refer to the reference implementations:

- **Python** ([vcrpy](https://github.com/kevin1024/vcrpy) via pytest-vcr): `pytest btx/ --vcr-record=all -v`
- **Java** ([WireMock](https://wiremock.org/)): `./gradlew btx:test -Pbtx.vcr.mode=record`

Commit the cassettes.  Re-record when the spec or model behaviour changes.

---

## Step 7: Wire up the test runner

### Test structure

The test is a parametrized test — one test case per spec file.  The test ID should be `<provider>/<name>` (e.g. `openai/completions`, `anthropic/streaming`) for easy filtering.

```
for each spec in load_specs():
    test_id = f"{spec.provider}/{spec.name}"

    def test(spec):
        root_span_id = execute_spec(spec)
        if vcr_off:
            spans = fetch_spans(root_span_id, project_id, len(spec.expected_brainstore_spans))
        else:
            spans = memory_logger.pop()
        validate_spans(spans, spec)
```

### Spec pre-execution (Java pattern)

For large test suites, Java executes all specs in parallel before JUnit collects results (in the static `specs()` method source).  This means all API calls happen concurrently, reducing total wall-clock time.  After all calls complete, `harness.awaitExportedSpans(total)` blocks until all OTel spans have been exported.

For simpler implementations (Python), execute each spec sequentially inside the test body — this is fine for a small number of specs.

### Build system integration

- **Gradle (Java)**: register a `fetchSpec` task that runs `fetch-spec.sh`; declare `test.dependsOn(fetchSpec)`; pass `btx.spec.root` as a JVM system property.
- **nox (Python)**: add a `test_btx` session; call `_run_tests(session, "braintrust/btx")`.
- **Make / shell**: add a `test-btx` target that sets `BTX_SPEC_ROOT` and runs the test command.

---

## Checklist

Work through these in order.  Each step has a clear verification criterion.

- [ ] **Spec fetch**: `fetch-spec.sh v0.0.1 /tmp/test-spec` exits 0 and creates `test/llm_span/openai/completions.yaml`.
- [ ] **Auto-fetch**: running the test suite with no env vars fetches specs automatically and collects N tests.
- [ ] **Cache**: a second run is instant (no network call).
- [ ] **YAML parsing**: loading all spec files succeeds; `FnMatcher`, `StartsWithMatcher`, `OrMatcher` objects are produced where the custom tags appear.
- [ ] **Execution (single)**: `execute_spec(completions_spec)` returns a non-empty root span ID and does not raise.
- [ ] **Live validation (single)**: `completions` test passes with `--disable-vcr`.
- [ ] **Live validation (all)**: all specs pass with `--disable-vcr`.
- [ ] **VCR record**: running with record mode writes cassette files.
- [ ] **VCR replay**: running in replay mode passes without any API keys or network access.
- [ ] **CI**: tests pass in a clean environment with only cassettes and no API keys (other than `BRAINTRUST_API_KEY` for BTQL — or skip BTQL entirely in replay mode).

---

## Common pitfalls

### Span name mismatch for streaming

Some SDKs use a different span name when streaming (e.g. `anthropic.messages.stream`) vs non-streaming (`anthropic.messages.create`).  The spec always expects the `create` name regardless of whether streaming was used.  Fix this in the SDK's instrumentation, not in the test.

### `!fn` lambda expressions in static languages

The spec contains Python lambda strings like `!fn lambda value: "Paris" in value`.  In static languages you cannot evaluate these.  Treat any `!fn` expression that starts with `lambda` as a "non-null and non-empty" check — this is what Java's `SpanValidator` does.  If you need exact semantics, evaluate the expression via a subprocess call to a Python interpreter.

### Attachment format in Anthropic spans

The spec expects image content blocks to have their `source` field replaced with a braintrust_attachment reference dict:
```yaml
source:
  type: braintrust_attachment
  content_type: image/png
  filename: <non-empty string>
  key: <non-empty string>
```
If your SDK still logs `source: {type: base64, data: ...}` the `attachments` spec will fail.  This is intentional — it tests that the SDK correctly converts inline image data to uploaded attachments.

### Scorer spans in BTQL results

The Braintrust backend may inject `purpose: scorer` spans.  Always filter these out before validating.

### Spans not yet indexed

After flushing, spans may appear in BTQL before their `output` and `metrics` fields are indexed.  Always check that at least one of these fields is non-null before treating a span as "ready".  Retry if not.

### Multiple calls to `init_logger` (Python)

In the Python SDK, calling `braintrust.init_logger()` multiple times in the same process is idempotent only if the project name/ID does not change.  In test code, call it once at the start of each test (or once per session with a session-scoped fixture) and do not mix fake test loggers with real loggers in the same process.
