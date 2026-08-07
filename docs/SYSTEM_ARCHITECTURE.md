# System Architecture

## Components

```text
Netlify UI (browser)
  |                         |
  | public problem reads    | local execution requests
  v                         v
Judge backend          Local agent (127.0.0.1:37123)
(38123 today)                |
  |                          | signed grant, protected test data,
  |                          | final completion
  v                          v
SQLite database          Docker runtime containers
```

## Ownership

| Component | Owns | Does not own |
| --- | --- | --- |
| Browser UI | Problem display, editor state, submitting source to the local agent, result presentation | Run grants, Docker commands, submission persistence |
| Backend | Public problem catalog, grants, protected test data, validation, persistent submission records | Local Docker execution |
| Local agent | Docker image acquisition, sandboxed compilation/execution, result aggregation | Public problem catalog, database writes before a run is complete |
| Docker | Compiler/runtime process isolation | Authentication, database access, network access |

## Public Problem Flow

The browser reads public metadata directly from the backend:

```text
GET /v1/problems
GET /v1/problems/{slug}
```

These responses include a problem statement, language list, limits, and sample tests only. This means the problem list remains usable even while the local agent is stopped.

For the current local demo, the UI calls `http://127.0.0.1:38123`. In production, this URL becomes the public backend address. The backend grants CORS access only to configured UI origins.

## Submission Flow

```text
1. Browser -> local agent
   POST /v1/runs
   { problem_slug, language, source_code }

2. Local agent -> backend
   POST /v1/local-runs/grants
   The agent supplies a source hash and its authenticated user identity.

3. Local agent -> backend
   GET /v1/local-runs/problems/{slug}
   Authorization: Bearer <run grant>

4. Local agent -> Docker
   Pulls a missing language image, compiles once, executes every test.

5. Local agent -> backend
   POST /v1/local-runs/complete
   Includes verdict and one result for every test.

6. Browser -> local agent
   GET /v1/runs/{run_id}?wait=25
   Displays every executed test's input, expected output, actual output,
   and diagnostics in the results drawer.
```

The backend creates a submission only in step 5. A failed agent, unavailable Docker runtime, or interrupted run therefore cannot leave a pending submission row.

## Trust Boundaries

- The local agent binds only to `127.0.0.1`; it is not reachable from the network.
- Browser origins are checked before the local agent accepts a submission request.
- A short-lived HMAC-signed grant binds one user, problem, language, and exact source hash.
- Docker runs have no network, a read-only root filesystem, dropped Linux capabilities, and an isolated temporary workspace.
- Submission completion is idempotent through the unique grant `jti` stored in `submissions.grant_jti`.

The current diagnostic mode intentionally returns all executed test data to the local browser after a run. For a production judge that needs hidden tests to remain secret, return only public-test detail and aggregate verdicts for hidden tests.

## Database Migration

[001_initial_schema.sql](001_initial_schema.sql) creates the SQLite schema and adds the `sum-two-integers` development problem with two sample tests and two hidden tests. It also creates `runtime_images`, which holds the shared Docker image for each supported language. The current draft runner still reads its image mapping from the backend manifest; this table is the migration-ready source for moving that mapping into the database.

The demo rows use `python:3.13-alpine`, `node:22-alpine`, `gcc:14` for C/C++, and `eclipse-temurin:21-jdk-alpine` for Java compilation. It is safe to run the migration again because its seed inserts and indexes are idempotent.
