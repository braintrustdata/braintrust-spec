# Repo state metadata

This spec defines the minimal Git repository metadata Braintrust coding-agent
integrations should emit to attribute a session to the repository state where it
ran.

## Scope

Repo state metadata belongs on the coding-agent session root span. Integrations
MUST NOT emit these fields on every turn, LLM span, or tool span.

Integrations SHOULD capture repo state once when the session root span is
created. Use the agent session cwd or worktree as the Git lookup point.

## Metadata

| Field | Type | Required | Semantics |
| --- | --- | --- | --- |
| `metadata.git_origin_url` | string | SHOULD when available | Credential-redacted `origin` remote URL for the repository. |
| `metadata.git_branch` | string | SHOULD when available | Current symbolic branch name. Omit when HEAD is detached. |
| `metadata.git_commit_sha` | string | SHOULD when available | Full current HEAD commit SHA. |

If a value cannot be resolved, omit that field. Git metadata capture is
best-effort and MUST NOT break or delay the coding-agent session.

Do not capture dirty state, unavailable reasons, tags, upstream data, status
counts, file names, diffs, or diff hashes as part of this v1 contract.

Remote URLs MUST be redacted before logging. For URL-style remotes such as
`https://token@example.com/org/repo.git`, integrations must remove embedded
usernames and passwords. SCP-like SSH remotes such as
`git@example.com:org/repo.git` may be preserved as-is.

## Wire format

```json
{
  "span_attributes": {
    "name": "codex: my-repo",
    "type": "task"
  },
  "metadata": {
    "git_origin_url": "https://github.com/braintrustdata/my-repo.git",
    "git_branch": "main",
    "git_commit_sha": "0123456789abcdef0123456789abcdef01234567"
  }
}
```

