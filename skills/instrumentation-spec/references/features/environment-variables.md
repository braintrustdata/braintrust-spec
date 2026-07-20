# SDK environment variables and dotenv files

## Overview

Braintrust SDKs are configured from three kinds of sources:

1. Caller-provided options.
2. Process environment variables.
3. SDK defaults.

SDKs should not load arbitrary dotenv files as a general configuration source.
Applications, CLIs, frameworks, and test harnesses may load dotenv files before
the SDK is initialized; once those values are present in the process
environment, SDKs treat them like any other environment variables.

The only SDK-owned dotenv-style file fallback defined by this spec is the
special `.env.braintrust` fallback for allowlisted Braintrust environment
variables described below.

## Configuration source precedence

For each SDK setting, use this precedence:

1. A caller-provided option wins over ambient configuration.
2. A nonblank process environment variable wins over file-based fallbacks and
   SDK defaults.
3. For variables allowlisted by this spec, a nonblank `.env.braintrust` value
   wins over SDK defaults.
4. If none of the above is present, use the SDK default when one exists.

Missing, empty, or whitespace-only process environment values must be treated as
unset. A blank caller-provided option is not a usable value for required
settings; SDKs should preserve their existing explicit-option validation
behavior, but must never override a nonblank caller-provided option with ambient
configuration.

The `.env.braintrust` fallback is an extra source only for environment variables
explicitly allowlisted by this spec.

## Process environment contract

SDKs should read environment variables through the runtime's standard process
environment API. This contract applies to every variable listed in
`semconv/envar.yaml`.

SDKs must not mutate the process environment while resolving configuration.
Reading from the process environment must not populate, rewrite, or delete
environment variables.

SDK APIs that expose environment values, such as internal `getEnv` helpers,
should remain process-environment-only lookups. They must not expose values read
from dotenv files or other file-based fallbacks.

If a runtime has no process environment, the SDK should use caller-provided
options and SDK defaults. It should skip file-based lookup unless the runtime
also has a current working directory and filesystem access.

## Generic dotenv files

Braintrust SDKs must not automatically load generic dotenv files such as:

- `.env`
- `.env.local`
- `.env.development`
- `.env.production`

This keeps Braintrust SDK initialization predictable and avoids changing an
application's environment-loading policy. If users want generic dotenv behavior,
they should load those files through their application framework or dotenv
library before calling Braintrust SDK APIs.

Once a user or framework loads a dotenv file into the process environment, the
normal process environment precedence applies. For example, if an application
loads `.env` and sets `BRAINTRUST_API_URL`, the SDK should see that value as a
process environment value, not as a file value.

## Special case: `.env.braintrust`

The Braintrust instrumentation wizard writes a file named `.env.braintrust` in
the user's working directory. The file contains dotenv-style Braintrust
configuration entries so that users can run or verify local instrumentation
immediately without manually exporting environment variables.

`.env.braintrust` is a Braintrust SDK configuration fallback only. It is not a
general dotenv loader and must not configure unrelated SDK settings.

SDK entrypoints that resolve allowlisted Braintrust environment variables from
caller options or the process environment must use the same `.env.braintrust`
discovery contract. This includes login/init paths, generated API clients, and
OpenTelemetry exporters or span processors.

File discovery only applies to runtimes that have a current working directory
and filesystem access. Browser, edge, embedded, or sandboxed runtimes without a
filesystem should keep their existing explicit-key and environment-key behavior
and skip `.env.braintrust` lookup.

### Allowlist

SDKs may read only variables explicitly marked with `env_braintrust: true` in
`semconv/envar.yaml` from `.env.braintrust`.

The current `.env.braintrust` allowlist is:

| Variable                       | Purpose                                          |
| ------------------------------ | ------------------------------------------------ |
| `BRAINTRUST_API_KEY`           | API key for authentication with Braintrust.      |
| `BRAINTRUST_APP_URL`           | Base URL for the Braintrust web application.     |
| `BRAINTRUST_API_URL`           | Base URL for the Braintrust API.                 |
| `BRAINTRUST_PROJECT`           | Project name for Braintrust logging and tracing. |
| `BRAINTRUST_PROJECT_ID`        | Project ID for logging spans.                    |
| `BRAINTRUST_ORG_NAME`          | Organization name to use when logging in.        |
| `BRAINTRUST_ENVIRONMENT_TYPE`  | Explicit span-origin environment type.           |
| `BRAINTRUST_ENVIRONMENT_NAME`  | Explicit span-origin environment name.           |

If `.env.braintrust` contains other names, SDKs must ignore them. They must not
expose ignored values through SDK config APIs or process-environment helpers.

### Resolution order

SDKs must resolve each allowlisted Braintrust setting in this order:

1. A caller-provided option wins over all ambient configuration.
2. A nonblank process environment value for that variable wins over
   `.env.braintrust`.
3. If no usable caller or environment value is available, read that variable
   from `.env.braintrust` only when it is allowlisted.
4. If no usable `.env.braintrust` value is available, use the SDK default when
   one exists.

### File lookup

When `.env.braintrust` fallback is needed for an allowlisted variable, SDKs must
search from the current working directory, then each parent directory, up to the
filesystem root or the search depth cap.

The search depth cap is **cwd plus 64 parent directories**, for a maximum of 65
candidate files:

```text
<cwd>/.env.braintrust
<cwd parent>/.env.braintrust
...
<64th parent>/.env.braintrust
```

Missing candidate files are not boundaries. Continue walking upward until a file
is found, the root is reached, or the depth cap is reached.

The nearest existing `.env.braintrust` is a boundary:

- If it contains a nonblank value for the requested allowlisted variable, use
  that value.
- If it does not contain the requested allowlisted variable, stop and return
  "not found" for that variable.
- If the requested allowlisted variable is empty or whitespace-only after
  parsing, stop and return "not found" for that variable.
- If the file exists but cannot be read, stop and return "not found".

SDKs must not continue to a higher parent after encountering a nearest existing
file, even if that file has no usable value for the requested variable.

If the current working directory cannot be determined, discovery must return
"not found" rather than throwing. Language-level cancellation may propagate when
the caller explicitly supplies a cancellation token or timeout.

SDKs may start candidate file reads in parallel, but must still preserve
nearest-file-wins semantics. A higher parent may only win after all closer
candidates are known to be missing.

## Span origin environment

SDKs MAY populate `context.span_origin.environment` to identify the operating
environment where a span was captured. This is provenance about the caller's
runtime, not the Braintrust API or app URL environment.

SDKs SHOULD support explicit caller options equivalent to:

```json
{
  "type": "ci",
  "name": "github_actions"
}
```

SDKs SHOULD also support environment-variable overrides through the normal
Braintrust configuration precedence, including `.env.braintrust` fallback:

| Variable                       | Purpose                                                |
| ------------------------------ | ------------------------------------------------------ |
| `BRAINTRUST_ENVIRONMENT_TYPE`  | Explicit `context.span_origin.environment.type` value. |
| `BRAINTRUST_ENVIRONMENT_NAME`  | Explicit `context.span_origin.environment.name` value. |

The environment type SHOULD be one of `ci`, `server`, or `local`, but SDK type
definitions SHOULD allow future string values. Environment names SHOULD be
normalized lower-snake-case labels. `BRAINTRUST_ENVIRONMENT_TYPE` and
`BRAINTRUST_ENVIRONMENT_NAME` are independent overrides; if only one is set,
SDKs SHOULD preserve that field and omit the unknown field.

Use this precedence:

1. A caller-provided SDK option wins over all ambient configuration. If an SDK
   supports an explicit null/none environment option, that value disables
   ambient environment detection.
2. `BRAINTRUST_ENVIRONMENT_TYPE` and `BRAINTRUST_ENVIRONMENT_NAME`, resolved
   through process environment and `.env.braintrust` fallback, win over
   automatic detection.
3. CI provider detection wins over server and language/framework detection.
4. Server/platform detection wins over language/framework detection.
5. Language/framework deployment-mode detection is a fallback.
6. If no reliable positive signal is present, omit `span_origin.environment`.

SDKs must not infer `local` from the absence of CI or server signals.
Braintrust Gateway/internal code identifies itself with a gateway span origin
name, such as `context.span_origin.name = "braintrust.gateway"`, not with a
special environment type.

Reliable CI signals include `GITHUB_ACTIONS`, `GITLAB_CI`, `CIRCLECI`,
`BUILDKITE`, `JENKINS_URL`, `JENKINS_HOME`, `TF_BUILD`, `TEAMCITY_VERSION`,
`TRAVIS`, and `BITBUCKET_BUILD_NUMBER`. If no provider-specific signal is
present but `CI` is truthy, SDKs may emit type `ci` and name `ci`.

Reliable server/platform signals include `VERCEL`, `NETLIFY`,
`AWS_LAMBDA_FUNCTION_NAME`, Lambda-specific `AWS_EXECUTION_ENV` values such as
`AWS_Lambda_*`, `K_SERVICE`, `FUNCTION_TARGET`, `KUBERNETES_SERVICE_HOST`,
`ECS_CONTAINER_METADATA_URI`, `ECS_CONTAINER_METADATA_URI_V4`, ECS-specific
`AWS_EXECUTION_ENV` values such as `AWS_ECS_*`, `DYNO`, `FLY_APP_NAME`,
`RAILWAY_ENVIRONMENT`, and `RENDER_SERVICE_NAME`. ECS metadata variables and
ECS-specific `AWS_EXECUTION_ENV` values should classify as `server/ecs` rather
than `server/aws_lambda`.

Language/framework variables such as `NODE_ENV`, `RAILS_ENV`, `RACK_ENV`,
`ASPNETCORE_ENVIRONMENT`, and `DOTNET_ENVIRONMENT` are weak fallback signals.
Map `production`, `prod`, `staging`, and `stage` to type `server`; map
`development`, `dev`, and `local` to type `local`; ignore `test` unless a
CI signal already classified the environment.

### Dotenv parsing

SDKs should use their runtime's standard dotenv parser when one is already
available. Custom parsers must support the common syntax generated by the
wizard:

```dotenv
BRAINTRUST_API_KEY=plain-key
export BRAINTRUST_API_KEY=exported-key
BRAINTRUST_API_KEY="quoted-key" # comment
BRAINTRUST_API_KEY='single-quoted-key'
BRAINTRUST_API_URL=https://api.braintrust.dev
```

Parsers must ignore blank lines and comments. They must not evaluate shell
commands, perform shell-style sourcing, or mutate the process environment.
Variable interpolation is not required.

The parsed value is usable only when it is nonblank after applying dotenv
parsing rules and trimming for emptiness. SDKs should return the parsed value
itself, not a trimmed variant, unless their existing environment handling already
normalizes that setting.

### Timing and caching

`.env.braintrust` discovery should be lazy. SDKs must not perform filesystem
lookup at package import time, and synchronous constructor/setup paths should
avoid blocking file IO where the language runtime allows that.

For synchronous SDKs, lookup at first configuration access is acceptable. For async
integrations, construct a lazy exporter or resolver and wait for discovery when
configuration is first required, such as during login, export, span end, or
force flush.

SDKs may cache a discovery result per config, state, session, exporter, or
resolver object. If an SDK snapshots the working directory when creating such an
object, it must do so consistently and should document that later process cwd
changes do not affect that object's lookup root.

### Error handling

Discovery failures must not crash application setup:

- Missing files return "not found".
- Unreadable nearest files return "not found".
- Invalid dotenv syntax returns "not found" for that nearest file.
- Filesystem errors while scanning return "not found".

When an API key is required and discovery returns "not found", the credential
consumer may raise or return its normal missing API key error. Error messages
should mention the three supported sources: explicit API key,
`BRAINTRUST_API_KEY`, and `.env.braintrust`.

When an optional setting is not found in caller options, the process
environment, or `.env.braintrust`, SDKs should use the normal SDK default.

### Security requirements

SDKs must treat `.env.braintrust` as local configuration that may contain
credential material:

- Do not log discovered credential values.
- Do not copy values from `.env.braintrust` into the process environment.
- Do not expose unrelated variables from `.env.braintrust` through SDK config
  APIs.
- Do not use `.env.braintrust` as a fallback for non-allowlisted settings.

## Conformance scenarios

SDK tests should cover these cases:

| Scenario                                                                            | Expected result                                                          |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Generic `.env` contains Braintrust variables but is not loaded by the app           | SDK does not read it directly                                            |
| Generic `.env` is loaded by the app before SDK initialization                       | Values are treated as process environment values                         |
| SDK resolves configuration from process environment                                 | Process environment remains unchanged                                    |
| SDK internal env helper reads an allowlisted variable                               | It returns only process environment values, not `.env.braintrust` values |
| `.env.braintrust` contains a non-allowlisted variable                               | SDK ignores that variable                                                |
| Explicit nonblank value, environment value, and `.env.braintrust` value are present | Explicit value is used                                                   |
| Nonblank environment value and `.env.braintrust` value are present                  | Environment value is used                                                |
| Blank or whitespace-only environment value and `.env.braintrust` value are present  | `.env.braintrust` value is used                                          |
| `.env.braintrust` exists in a parent directory                                      | Parent file value is used                                                |
| `.env.braintrust` files exist in multiple parents                                   | Nearest file value is used                                               |
| Nearest `.env.braintrust` lacks the requested allowlisted variable                  | Discovery returns not found for that variable                            |
| Nearest `.env.braintrust` has blank value for the requested allowlisted variable    | Discovery returns not found for that variable                            |
| Nearest `.env.braintrust` is unreadable                                             | Discovery returns not found                                              |
| `.env.braintrust` is more than 64 parents above cwd                                 | Discovery returns not found                                              |
| `.env.braintrust` is exactly 64 parents above cwd                                   | File value is used                                                       |
| `.env.braintrust` uses `export`, quotes, comments, and unrelated variables          | Allowlisted values are parsed; unrelated variables are ignored           |
| `.env.braintrust` value is used                                                     | Process environment remains unchanged                                    |
| Constructor/setup runs with no immediate API key                                    | Setup succeeds if the SDK defers credential use                          |
| Export/login/flush later needs a key and `.env.braintrust` key exists               | Operation waits for discovery and uses file key                          |
| Export/login/flush later needs a key and no key exists                              | Operation fails with missing API key                                     |
