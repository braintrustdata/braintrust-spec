# Experiment Git metadata

This spec defines how Braintrust SDKs attach Git repository metadata to an
experiment when it is created: which fields exist, how SDKs decide whether to
run Git at all, how organization policy, caller options, and the
`BRAINTRUST_ENABLE_GIT_METADATA` environment variable combine, and how
automatic ancestor collection interacts with base-experiment selection.

## Scope

This spec covers experiment initialization only: the experiment
registration/creation request sent by `init`, `Eval`, eval builders, and CLI
eval runners.

It does not cover coding-agent session repository state. That contract is
[Repo state metadata](repo-state-metadata.md), which emits three fields on a
session root span and has no collection settings. The two features share no
configuration: `BRAINTRUST_ENABLE_GIT_METADATA` and Git metadata settings do not
affect repo state metadata, and repo state metadata fields are not experiment
`repo_info` fields.

The spec separates five capabilities. An SDK can support one without the
others:

| Capability | Meaning |
| --- | --- |
| Explicit repository info | A caller can pass `repo_info` / `repoInfo` / `RepoInfo` when creating an experiment, and the SDK sends it. No Git work is involved. |
| Automatic collection | The SDK runs Git in the working directory to build `repo_info` when the caller did not pass it. |
| Policy enforcement | Organization policy, caller settings, and the environment variable resolve to one effective setting, and that setting controls every automatic Git operation, ancestors included. |
| Field-selective collection | The SDK works out which fields are permitted before running Git, then runs only the commands those fields need. |
| Ancestor discovery | The SDK sends `ancestor_commits` so the server can pick a base experiment automatically. |

SDKs without automatic collection are not required to add it. SDKs that collect
automatically but do not discover ancestors are not required to add ancestor
discovery. The requirements for policy enforcement, the environment variable,
and field-selective collection apply only to SDKs that collect automatically.

Subprocess deadlines and timeouts, and replacing network-based default-branch
discovery with local refs, are outside this spec.

## Repository metadata

`repo_info` is an object with the following optional fields. SDKs must omit
a field that is not permitted or whose value cannot be resolved. If no field has
a value, SDKs must omit `repo_info` entirely rather than send an empty object or
an object of nulls.

| Field | Type | Semantics |
| --- | --- | --- |
| `commit` | string | Full SHA of `HEAD`. |
| `branch` | string | Current symbolic branch name. Omit when `HEAD` is detached; never send the literal `HEAD`. |
| `tag` | string | A tag that points exactly at `HEAD`. Omit when `HEAD` has no exact tag; never fall back to an abbreviated SHA (do not use `git describe --always`). |
| `dirty` | boolean | `true` when tracked files differ from `HEAD`, whether the change is staged or unstaged. Untracked files do not count, so `dirty` agrees with `git_diff`. |
| `author_name` | string | Author name of the `HEAD` commit with `.mailmap` applied (`%aN`). |
| `author_email` | string | Author email of the `HEAD` commit with `.mailmap` applied (`%aE`). |
| `commit_message` | string | Full message of the `HEAD` commit, trimmed. |
| `commit_time` | string | Committer date of `HEAD` in strict ISO 8601 form (`%cI`), with a numeric UTC offset. A trailing `Z` is written as `+00:00`. |
| `git_diff` | string | Output of `git diff --no-ext-diff HEAD`, truncated to at most 65,536 UTF-8 bytes without splitting a character. Only sent when `dirty` is `true`. |

These field names are the permitted values of a settings `fields` list. SDKs
must ignore unknown names in `fields` rather than fail.

## Collection settings

A Git metadata setting has this shape:

```json
{ "collect": "all" | "some" | "none", "fields": ["commit", "branch"] }
```

- `all`: every field is permitted.
- `some`: only the fields listed in `fields` are permitted.
- `none`: no field is permitted, and no automatic Git work runs.

A `some` setting whose `fields` contains no known field name is equivalent to
`none`.

### Merging

To merge two settings `a` and `b`:

1. If `a` is `all`, the result is `b`. If `b` is `all`, the result is `a`.
2. Otherwise, if either is `none`, the result is `none`.
3. Otherwise both are `some`. The result is `some` with the intersection of
   their fields, or `none` if the intersection is empty.

Merging never permits a field that one of the inputs excludes.

### Sources

| Source | Examples |
| --- | --- |
| Organization policy | The `git_metadata` setting the SDK gets for the organization during login or organization lookup. |
| Explicit caller collection option | Python `git_metadata_settings`, JavaScript `gitMetadataSettings`, .NET `GitMetadataSettings(...)` (including `GitMetadataSettings.None()`), and the matching CLI flags. |
| Environment | `BRAINTRUST_ENABLE_GIT_METADATA`. See [Environment variable](#environment-variable). |
| Default | Used when no other source supplies a value. |

Explicit repository info is not a collection option. It goes through the
explicit-data path described in [Explicit repository info](#explicit-repository-info).

## Effective settings

Organization policy is the ceiling. No caller option and no environment value
can permit a field the organization does not permit. Within that ceiling, the
explicit caller option wins over the environment, and the environment wins
over the default.

SDKs must resolve the effective setting before running any Git command:

```text
if caller supplied an explicit collection option:
    requested = caller option
elif BRAINTRUST_ENABLE_GIT_METADATA parses as false:
    requested = { collect: "none" }
else:                                   # unset, blank, invalid, or true
    requested = null                    # no preference

if organization policy is present:
    effective = merge(org policy, requested ?? { collect: "all" })
elif requested is not null:
    effective = requested
else:
    effective = { collect: "none" }     # missing-policy default
```

### Missing organization policy

Organization policy is missing when the organization data the SDK received
has no `git_metadata` setting.

- With no explicit caller option, the default is `none`: no automatic Git work.
  The environment variable cannot turn collection on, because `true` only means
  "no preference".
- With an explicit caller option, that option is the effective setting. There
  is no ceiling to apply.

An SDK that collects by default when organization policy is missing does not
conform.

If an SDK proceeds with experiment initialization without having fetched
organization data at all, it must treat policy as missing.

### Examples

| Organization policy | Explicit caller option | `BRAINTRUST_ENABLE_GIT_METADATA` | Effective setting |
| --- | --- | --- | --- |
| `none` | `all` | any | `none`: no automatic Git work |
| `all` | `none` | `true` | `none`: no automatic Git work |
| `all` | `some [commit, branch]` | `false` | `some [commit, branch]` |
| `some [commit]` | `all` | `false` | `some [commit]` |
| `some [commit, branch]` | `some [branch, tag]` | unset | `some [branch]` |
| `some [commit]` | `some [tag]` | unset | `none` |
| `all` | none supplied | `false` | `none`: zero Git subprocesses |
| `some [commit, dirty]` | none supplied | unset or `true` | `some [commit, dirty]` |
| missing | none supplied | unset or `true` | `none` |
| missing | `some [commit]` | `false` | `some [commit]` |

## Environment variable

`BRAINTRUST_ENABLE_GIT_METADATA` is registered in
[`semconv/envar.yaml`](../../../../semconv/envar.yaml). It lets a process,
such as a CI job or a test subprocess, turn off automatic Git work without
changing code.

Parsing:

1. Read the variable from the process environment, following the
   [environment-variable contract](environment-variables.md#process-environment-contract).
2. Missing, empty, or whitespace-only values are unset.
3. Otherwise trim surrounding whitespace and compare case-insensitively.
   `true` and `1` mean enabled. `false` and `0` mean disabled.
4. Any other value is invalid. Treat it as unset. SDKs should log at most one
   warning per process that names the variable and the accepted values, and
   must not throw.

Semantics:

- **Default:** enabled. Unset and enabled behave the same way.
- **Enabled:** no preference. The organization/default resolution runs
  unchanged. It does not force collection on and does not permit extra fields.
- **Disabled:** if no explicit caller collection option is present, the
  effective setting is `none`. The SDK sends no automatic `repo_info` and no
  `ancestor_commits`, and starts zero Git subprocesses, including repository
  detection.
- An explicit caller collection option, including one that enables
  collection, takes precedence over a disabled variable. The organization
  ceiling still applies.

### `.env.braintrust`

`BRAINTRUST_ENABLE_GIT_METADATA` is not on the `.env.braintrust` allowlist
(`env_braintrust: false`). SDKs read it only from the process environment.

Reasons:

- `.env.braintrust` is written by the instrumentation wizard and carries
  credentials and project targeting, not runtime behavior.
- The variable exists so CI jobs and test harnesses can control Git work per
  process. A file found in a parent directory would be a less predictable
  source.
- Resolving it from a file would add a directory walk to a path whose
  purpose is to avoid unneeded work.

Applications that want the setting in a dotenv file can load that file into
the process environment themselves, as described in
[Generic dotenv files](environment-variables.md#generic-dotenv-files).

## Explicit repository info

If the caller passes repository info, the SDK sends it as `repo_info` as given:

- The SDK does not run Git to build or supplement it.
- The SDK does not filter it by organization or caller collection settings. It
  is caller data, not collection.
- The SDK must not run ancestor discovery. The caller has described the
  repository state, which may not be the current working directory, so
  ancestors computed from the working directory could contradict it.

Explicit repository info therefore means no automatic Git work at all, whatever
the effective setting. An explicit collection option passed alongside it has no
effect.

An explicit null, such as .NET `RepoInfo(null)`, means "send no repository
info". The SDK sends no `repo_info` and does no automatic Git work.

## Ancestor discovery

SDKs that support ancestor discovery send `ancestor_commits`: commits on the
default branch's first-parent history, starting at the merge base with `HEAD`.
The server uses the list to pick the most recent experiment run on one of those
commits as the base experiment when the caller did not name one.

### When it runs

1. An explicit base experiment (`base_experiment_id`, `base_experiment`, or the
   equivalent) wins. When one is passed, the SDK must not run ancestor
   discovery.
2. Explicit repository info, including an explicit null, disables ancestor
   discovery (see [Explicit repository info](#explicit-repository-info)).
3. If the effective setting is `none`, the SDK must not run ancestor discovery
   or any Git command it needs. This applies whether `none` came from
   organization policy, an explicit caller option, the environment variable,
   or the missing-policy default.
4. If the effective setting is `all` or `some`, the SDK runs ancestor
   discovery. Individual fields do not gate it. For example, a setting of
   `some [branch]` still runs it.

### Algorithm

1. **Remote.** Use `origin` if it exists, otherwise the first remote listed by
   `git remote`. If the repository has no remote, stop with no ancestors.
2. **Default branch.** If exactly one of `main`, `master`, and `develop`
   exists as a local branch (`git for-each-ref --format=%(refname:short)
   refs/heads/`), use it. Otherwise read the `HEAD branch:` line of
   `git remote show <remote>`. If that fails, use `main`.
3. **Merge base.** Run `git merge-base <start> <remote>/<branch>`, where
   `<start>` is `HEAD` when the working tree is dirty and `HEAD^` when it is
   clean. A clean `HEAD` is the commit being evaluated, so starting from its
   parent keeps an earlier run on the same commit from becoming its own base.
4. **List.** Run `git rev-list --first-parent --max-count=1000 <merge-base>`
   and send the SHAs in output order, nearest first.

The dirty state in step 3 is the same check as the `dirty` field and must be
reused when both are needed.

Replacing the network-based `git remote show` lookup with local refs is a
separate follow-up and outside this spec.

### Failures

Failures produce an omitted or empty `ancestor_commits`. They never fail
experiment creation. Examples: no remote, a missing `<remote>/<branch>` ref, a
missing `HEAD^` in a single-commit or shallow checkout, or a failed merge base.

## Selective collection and Git operations

### Resolve before running Git

SDKs must determine everything below before running any Git command,
including repository detection:

1. Whether explicit repository info was passed.
2. The effective setting.
3. Whether an explicit base experiment was passed.
4. The set of permitted fields, and whether ancestor discovery will run.

If no field will be collected and ancestor discovery will not run, the SDK
must not start any Git subprocess.

### Operations per field

Run only the operations that the permitted fields and ancestor discovery need:

| Need | Required Git work |
| --- | --- |
| Any field or ancestor discovery | Repository detection, such as `git rev-parse --show-toplevel`. Run it once per initialization. |
| `commit`, `author_name`, `author_email`, `commit_message`, `commit_time` | One `git log -1` call for all permitted fields, for example `git log -1 --format=%H%x00%aN%x00%aE%x00%cI%x00%B HEAD`. `commit` alone may use `git rev-parse HEAD` instead. |
| `branch` | `git symbolic-ref --quiet --short HEAD`. A non-zero exit means detached. |
| `tag` | `git describe --tags --exact-match HEAD`. A non-zero exit means no tag. |
| `dirty` | One check of staged and unstaged changes to tracked files, for example `git diff --quiet HEAD` (exit status 1 means dirty). |
| `git_diff` | The dirty check, then `git diff --no-ext-diff HEAD` only if the result is dirty. |
| Ancestor discovery | The remote and default-branch lookups, the dirty check, `git merge-base`, and `git rev-list`. |

Requirements:

- SDKs must generate a patch only when `git_diff` is permitted and the working
  tree is dirty. Patches must not be generated and then discarded.
- SDKs must run the dirty check only when `dirty` or `git_diff` is permitted,
  or when ancestor discovery will run.
- SDKs must read all permitted commit details with a single `git log`
  call.
- Within one experiment initialization, SDKs must run each check at most once
  and reuse the result. This covers repository detection and the dirty check,
  and the dirty result must be shared between repository metadata and
  ancestor discovery.
- SDKs must not cache working-tree or `HEAD` state across experiment
  initializations. This includes dirty state, `HEAD`, commit details, branch,
  tag, diff, and ancestors. Two initializations in one process must see
  changes made between them.
- SDKs may cache, for the life of the process, the resolved Git executable
  path and the remote/default-branch result from ancestor discovery. A cached
  repository root must be keyed by the working directory it was resolved
  from.
- SDKs must run Git by an absolute path resolved from `PATH` and must not run
  a `git` executable found in the current working directory. On Windows,
  default process lookup checks the current directory first, so a `git.exe`
  committed to a repository would otherwise run.
- SDKs may run Git asynchronously so experiment initialization does not block
  the caller's thread, but the order requirements above still apply.
- Git failures in the collector, including a missing Git executable, a
  directory that is not a repository, or a failed command, omit the affected
  fields. They never fail experiment creation.

## Wire format

These are the Git-related fields of the experiment registration/creation
request body:

```json
{
  "repo_info": {
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "branch": "main",
    "dirty": false,
    "author_name": "Ada Lovelace",
    "author_email": "ada@example.com",
    "commit_message": "Add scorer",
    "commit_time": "2026-01-01T12:00:00+00:00"
  },
  "ancestor_commits": [
    "0123456789abcdef0123456789abcdef01234567",
    "89abcdef0123456789abcdef0123456789abcdef"
  ]
}
```

`base_exp_id` or `base_experiment` replaces `ancestor_commits` when the
caller names a base experiment.

# SDK support

```yaml
# Initial values come from a source-level audit of each SDK's main branch, not a
# release assessment. Like the rest of the catalog, treat them as prototype data
# until a real assessment replaces them.
id: experiment-git-metadata
name: Experiment Git metadata
category: Metadata
support:
  explicit-repo-info:
    dotnet: "yes"
    go: "no"
    java: "no"
    js: "yes"
    python: "yes"
    ruby: "no"
    rust: "yes"
  automatic-collection:
    dotnet: "partial"
    go: "no"
    java: "no"
    js: "partial"
    python: "partial"
    ruby: "no"
    rust: "no"
  org-policy-enforcement:
    dotnet: "no"
    go: "n/a"
    java: "n/a"
    js: "partial"
    python: "yes"
    ruby: "n/a"
    rust: "n/a"
  enable-git-metadata-env:
    dotnet: "no"
    go: "n/a"
    java: "n/a"
    js: "no"
    python: "no"
    ruby: "n/a"
    rust: "n/a"
  field-selective-collection:
    dotnet: "partial"
    go: "n/a"
    java: "n/a"
    js: "no"
    python: "no"
    ruby: "n/a"
    rust: "n/a"
  ancestor-discovery:
    dotnet: "no"
    go: "no"
    java: "no"
    js: "partial"
    python: "partial"
    ruby: "no"
    rust: "no"
```
