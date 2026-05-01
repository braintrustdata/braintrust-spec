# Dataset versioning: contracts

## Shared response objects

### Dataset snapshot

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Snapshot id |
| `dataset_id` | `string` | Dataset id |
| `name` | `string` | Human-readable snapshot name |
| `description` | `string \| null` | Optional snapshot description |
| `xact_id` | `string` | Concrete dataset version captured by the snapshot |
| `created` | `string` | ISO timestamp |

Example:

```json
{
  "id": "00000000-0000-0000-0000-000000000004",
  "dataset_id": "00000000-0000-0000-0000-000000000002",
  "name": "baseline",
  "description": "Initial QA baseline",
  "xact_id": "1000192656880881099",
  "created": "2026-04-21T00:00:00.000Z"
}
```

### Environment

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Environment id |
| `org_id` | `string` | Organization id |
| `name` | `string` | Human-readable environment name |
| `slug` | `string` | Stable environment slug |
| `description` | `string \| null` | Optional description |
| `created` | `string` | ISO timestamp |
| `deleted_at` | `string \| null` | ISO timestamp if soft-deleted |

Example:

```json
{
  "id": "00000000-0000-0000-0000-000000000010",
  "org_id": "00000000-0000-0000-0000-000000000011",
  "name": "Production",
  "slug": "production",
  "description": "Live customer-facing environment",
  "created": "2026-04-21T00:00:00.000Z",
  "deleted_at": null
}
```

### Environment object association

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Association id |
| `object_type` | `string` | Currently `dataset` or `prompt` |
| `object_id` | `string` | Id of the tagged base object, such as the dataset id or prompt id |
| `object_version` | `string` | Concrete version for that base object, such as the dataset `xact_id` |
| `environment_slug` | `string` | Environment slug |
| `created` | `string` | ISO timestamp |

Example:

```json
{
  "id": "00000000-0000-0000-0000-000000000020",
  "object_type": "dataset",
  "object_id": "00000000-0000-0000-0000-000000000002",
  "object_version": "1000192656880881099",
  "environment_slug": "production",
  "created": "2026-04-21T00:00:00.000Z"
}
```

### Restore preview result

| Field | Type | Description |
|-------|------|-------------|
| `rows_to_restore` | `number` | Rows that would be reinserted or updated from the target version |
| `rows_to_delete` | `number` | Rows that would be deleted from the current head |

Example:

```json
{
  "rows_to_restore": 3,
  "rows_to_delete": 1
}
```

### Restore result

| Field | Type | Description |
|-------|------|-------------|
| `xact_id` | `string \| null` | New head version created by the restore, or `null` for a no-op |
| `rows_restored` | `number` | Rows restored into the new head |
| `rows_deleted` | `number` | Rows deleted from the new head |

Example:

```json
{
  "xact_id": "1000192657000000000",
  "rows_restored": 3,
  "rows_deleted": 1
}
```

## Snapshot APIs

### `POST /api/dataset_snapshot/register`

##### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `dataset_id` | `string` | yes | Dataset to snapshot |
| `dataset_snapshot_name` | `string` | yes | Snapshot name |
| `xact_id` | `string` | yes | Concrete dataset version captured by the snapshot |
| `description` | `string \| null` | no | Optional description |
| `update` | `boolean` | no | Opt-in update-if-exists behavior |

Example:

```json
{
  "dataset_id": "00000000-0000-0000-0000-000000000002",
  "dataset_snapshot_name": "baseline",
  "xact_id": "1000192656880881099",
  "description": "Initial QA baseline",
  "update": false
}
```

##### Response format

A JSON object:

```json
{
  "dataset_snapshot": {
    "id": "00000000-0000-0000-0000-000000000004",
    "dataset_id": "00000000-0000-0000-0000-000000000002",
    "name": "baseline",
    "description": "Initial QA baseline",
    "xact_id": "1000192656880881099",
    "created": "2026-04-21T00:00:00.000Z"
  },
  "found_existing": false
}
```

##### Side effect

Creates or intentionally updates snapshot metadata so that a human-readable name points at a concrete dataset version.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Body is not an object, required fields are missing, or the backend rejects the snapshot registration request |
| `403 Forbidden` | Caller lacks permission to update the target dataset or is not authorized |

### `GET /api/dataset_snapshot/get`

This route may also be called as `POST /api/dataset_snapshot/get` with the same fields in the JSON body.

##### Query parameters or body fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | no | Exact snapshot id |
| `dataset_id` | `string` | no | Dataset id |
| `name` | `string` | no | Snapshot name |
| `xact_id` | `string` | no | Concrete dataset version |
| `limit` | `number` | no | Pagination limit |
| `cursor` | `string` | no | Pagination cursor |

Example:

```json
{
  "dataset_id": "00000000-0000-0000-0000-000000000002",
  "name": "baseline"
}
```

##### Response format

A JSON array of snapshot objects:

```json
[
  {
    "id": "00000000-0000-0000-0000-000000000004",
    "dataset_id": "00000000-0000-0000-0000-000000000002",
    "name": "baseline",
    "description": "Initial QA baseline",
    "xact_id": "1000192656880881099",
    "created": "2026-04-21T00:00:00.000Z"
  }
]
```

##### Side effect

None.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Query parameters or body fields are invalid |
| `403 Forbidden` | Caller lacks permission to read the target dataset or is not authorized |

### `POST /api/dataset_snapshot/patch_id`

##### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Snapshot id |
| `name` | `string \| null` | no | New snapshot name |
| `description` | `string \| null` | no | New description |

Example:

```json
{
  "id": "00000000-0000-0000-0000-000000000004",
  "name": "renamed snapshot",
  "description": null
}
```

##### Response format

A single snapshot object:

```json
{
  "id": "00000000-0000-0000-0000-000000000004",
  "dataset_id": "00000000-0000-0000-0000-000000000002",
  "name": "renamed snapshot",
  "description": null,
  "xact_id": "1000192656880881099",
  "created": "2026-04-21T00:00:00.000Z"
}
```

##### Side effect

Updates snapshot metadata only. It does not change dataset rows or the captured `xact_id`.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Body is not an object or patch fields are invalid |
| `403 Forbidden` | Caller lacks permission to update the target dataset or is not authorized |

### `POST /api/dataset_snapshot/delete_id`

##### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Snapshot id |

Example:

```json
{
  "id": "00000000-0000-0000-0000-000000000004"
}
```

##### Response format

The deleted snapshot object:

```json
{
  "id": "00000000-0000-0000-0000-000000000004",
  "dataset_id": "00000000-0000-0000-0000-000000000002",
  "name": "baseline",
  "description": "Initial QA baseline",
  "xact_id": "1000192656880881099",
  "created": "2026-04-21T00:00:00.000Z"
}
```

##### Side effect

Deletes snapshot metadata. It does not change dataset rows or dataset head.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Body is not an object or id is invalid |
| `403 Forbidden` | Caller lacks permission to update the target dataset or is not authorized |

## Environment APIs

### `GET /environment`

##### Query parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `org_name` | `string` | no | Organization name when the token is not already org-scoped |
| `name` | `string` | no | Exact environment name filter |
| `ids` | `string \| string[]` | no | One or more environment ids |

Example:

```text
GET /environment?org_name=my-org
```

##### Response format

A JSON object containing an `objects` array:

```json
{
  "objects": [
    {
      "id": "00000000-0000-0000-0000-000000000010",
      "org_id": "00000000-0000-0000-0000-000000000011",
      "name": "Production",
      "slug": "production",
      "description": "Live customer-facing environment",
      "created": "2026-04-21T00:00:00.000Z",
      "deleted_at": null
    }
  ]
}
```

##### Side effect

None.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Query parameters are invalid |
| `403 Forbidden` | Caller is not authorized to read the organization |

### `POST /environment`

##### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | yes | Human-readable environment name |
| `slug` | `string` | yes | Stable environment slug |
| `description` | `string \| null` | no | Optional description |
| `org_name` | `string \| null` | no | Organization name when the token is not already org-scoped |

Example:

```json
{
  "name": "Production",
  "slug": "production",
  "description": "Live customer-facing environment",
  "org_name": "my-org"
}
```

##### Response format

A single environment object:

```json
{
  "id": "00000000-0000-0000-0000-000000000010",
  "org_id": "00000000-0000-0000-0000-000000000011",
  "name": "Production",
  "slug": "production",
  "description": "Live customer-facing environment",
  "created": "2026-04-21T00:00:00.000Z",
  "deleted_at": null
}
```

##### Side effect

Creates a new environment record inside the target organization.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Body is invalid or the slug already exists in the organization |
| `403 Forbidden` | Caller is not authorized to update the organization |

### `GET /environment/:id`

##### Path parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Environment id |

##### Response format

A single environment object.

##### Side effect

None.

##### Error responses

| Status | Condition |
|--------|-----------|
| `403 Forbidden` | Caller cannot read that environment or is not authorized |

### `PATCH /environment/:id`

##### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string \| null` | no | New environment name |
| `slug` | `string \| null` | no | New environment slug |
| `description` | `string \| null` | no | New description |

Example:

```json
{
  "description": "Customer-facing production environment"
}
```

##### Response format

A single environment object with the updated fields.

##### Side effect

Updates environment metadata in place.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Body is invalid, no patch fields are supplied, or the new slug conflicts with an existing environment |
| `403 Forbidden` | Caller is not authorized to update the organization |

### `DELETE /environment/:id`

##### Path parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Environment id |

##### Response format

A single environment object with `deleted_at` populated.

##### Side effect

Soft-deletes the environment.

##### Error responses

| Status | Condition |
|--------|-----------|
| `403 Forbidden` | Caller is not authorized to update the organization or cannot access that environment |

## Environment-object APIs

The environment-object API is the shared version-tagging primitive used by datasets and prompts.

Important note:

- `object_type` currently supports `dataset` and `prompt`
- `object_type` / `object_id` identify the base object being tagged, not a snapshot record
- for dataset tagging, use `object_type = "dataset"` and `object_id = <dataset_id>`
- `object_version` must be the concrete version for that base object; for datasets, that means the dataset `xact_id`
- snapshot names are not accepted directly by the write APIs; callers must resolve snapshot names to versions first

### `GET /environment-object/:object_type/:object_id`

##### Path parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | `string` | yes | Object type, currently `dataset` or `prompt` |
| `object_id` | `string` | yes | Object id |

##### Query parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `org_name` | `string` | no | Organization name when the token is not already org-scoped |

##### Response format

A JSON object containing an `objects` array:

```json
{
  "objects": [
    {
      "id": "00000000-0000-0000-0000-000000000020",
      "object_type": "dataset",
      "object_id": "00000000-0000-0000-0000-000000000002",
      "object_version": "1000192656880881099",
      "environment_slug": "production",
      "created": "2026-04-21T00:00:00.000Z"
    }
  ]
}
```

##### Side effect

None.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Path or query parameters are invalid |
| `403 Forbidden` | Caller lacks permission to read the underlying object or is not authorized |

### `POST /environment-object/:object_type/:object_id`

##### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object_version` | `string` | yes | Concrete version to tag. For datasets, this is the dataset `xact_id` |
| `environment_slug` | `string` | yes | Target environment slug |
| `org_name` | `string \| null` | no | Organization name when the token is not already org-scoped |

Example:

```json
{
  "object_version": "1000192656880881099",
  "environment_slug": "production",
  "org_name": "my-org"
}
```

##### Response format

A single environment-object association:

```json
{
  "id": "00000000-0000-0000-0000-000000000020",
  "object_type": "dataset",
  "object_id": "00000000-0000-0000-0000-000000000002",
  "object_version": "1000192656880881099",
  "environment_slug": "production",
  "created": "2026-04-21T00:00:00.000Z"
}
```

##### Side effect

Creates a brand-new environment association.

##### Validation note

The current server validates `object_version` as a version-shaped string that normalizes through `normalizeXact()` and parses as a PostgreSQL `bigint`. It does not currently verify that the supplied version actually exists for the referenced dataset or prompt.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Body is invalid, the environment slug does not exist, or the object already has an association for that environment |
| `403 Forbidden` | Caller lacks permission to update the underlying object or is not authorized |

### `GET /environment-object/:object_type/:object_id/:environment_slug`

##### Path parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | `string` | yes | Object type, currently `dataset` or `prompt` |
| `object_id` | `string` | yes | Object id |
| `environment_slug` | `string` | yes | Environment slug |

##### Query parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `org_name` | `string` | no | Organization name when the token is not already org-scoped |

##### Response format

A single environment-object association.

##### Side effect

None.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Association does not exist or the request shape is invalid |
| `403 Forbidden` | Caller lacks permission to read the underlying object or is not authorized |

### `PUT /environment-object/:object_type/:object_id/:environment_slug`

##### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object_version` | `string` | yes | Concrete version to tag. For datasets, this is the dataset `xact_id` |
| `org_name` | `string \| null` | no | Organization name when the token is not already org-scoped |

Example:

```json
{
  "object_version": "1000192656880881099",
  "org_name": "my-org"
}
```

##### Response format

A single environment-object association.

##### Side effect

Creates the association if it does not exist, or overwrites the existing `object_version` for that environment/object pair.

##### Validation note

Like `POST`, the current server validates only that `object_version` is version-shaped and `bigint`-compatible after normalization. It does not currently confirm that the version exists for the supplied base object.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Body is invalid or the environment slug does not exist |
| `403 Forbidden` | Caller lacks permission to update the underlying object or is not authorized |

### `DELETE /environment-object/:object_type/:object_id/:environment_slug`

##### Path parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | `string` | yes | Object type, currently `dataset` or `prompt` |
| `object_id` | `string` | yes | Object id |
| `environment_slug` | `string` | yes | Environment slug |

##### Query parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `org_name` | `string` | no | Organization name when the token is not already org-scoped |

##### Response format

The deleted environment-object association.

##### Side effect

Deletes the current association for that environment/object pair.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Association does not exist or the request shape is invalid |
| `403 Forbidden` | Caller lacks permission to update the underlying object or is not authorized |

## Restore APIs

### `POST /v1/dataset/:id/restore/preview`

##### Path parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Dataset id |

##### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | `string` | yes | Target version to compare against current head |

Example:

```json
{
  "version": "1000192656880881099"
}
```

##### Response format

A restore preview result object:

```json
{
  "rows_to_restore": 3,
  "rows_to_delete": 1
}
```

##### Side effect

None. This endpoint only computes the restore diff.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Body is invalid, `version` is missing or malformed, or the restore query exceeds configured limits |
| `403 Forbidden` | Caller lacks permission to read the dataset or is not authorized |

### `POST /v1/dataset/:id/restore`

##### Path parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | yes | Dataset id |

##### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | `string` | yes | Target version to restore to |

Example:

```json
{
  "version": "1000192656880881099"
}
```

##### Response format

A restore result object:

```json
{
  "xact_id": "1000192657000000000",
  "rows_restored": 3,
  "rows_deleted": 1
}
```

##### Side effect

Writes compensating rows so that the new dataset head matches the requested version while preserving append-only history.

##### Error responses

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Body is invalid, `version` is missing or malformed, or the restore query exceeds configured limits |
| `403 Forbidden` | Caller lacks permission to update the dataset or is not authorized |
