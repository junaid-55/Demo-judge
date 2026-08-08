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

SQL problems use a separate PostgreSQL path inside the local agent. The `sql` language maps to the shared `postgres:17-alpine` image. A SQL problem stores public DDL in `problems.sql_schema`, base rows/setup in protected `problems.sql_fixture`, and each test's change in `test_cases.sql_delta`. The runner concatenates schema and fixture only inside the local PostgreSQL runtime.

For SQL puzzle problems, the public catalog returns `sql_schema`, ordered `sql_tasks` IDs, and a scenario description for every task. Each task maps to one protected test delta and expected result. A notebook-cell run is local only: it creates no submission row and cannot change the user's persisted submission history.

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
   The agent supplies a source hash and its authenticated user identity. The backend declines an exact prior submission before Docker work starts.

3. Local agent -> backend
   GET /v1/local-runs/problems/{slug}
   Authorization: Bearer <run grant>

4. Local agent -> Docker
   Pulls a missing language image, compiles once, executes every test. For SQL, it starts a reusable PostgreSQL container, restores the fixture to `problem_base`, clones that database for each test delta, runs the submitted SQL as the `solver` role, then drops the clone.

5. Local agent -> backend
   POST /v1/local-runs/complete
   Includes verdict and one result for every test.

6. Browser -> local agent
   GET /v1/runs/{run_id}?wait=25
   Displays every executed test's input, expected output, actual output,
   and diagnostics in the results drawer.
```

The backend creates a submission only in step 5. A failed agent, unavailable Docker runtime, or interrupted run therefore cannot leave a pending submission row.

The local agent retains an SQL PostgreSQL container and its temporary Docker volume while the user remains on that SQL problem. Switching away or closing the browser calls the local release endpoint; it stops the container and removes that volume. The PostgreSQL image remains cached by Docker.

The SQL notebook tracks passed cells in the browser session. Zero passed cells is `Incomplete`; some passed cells is `Partially complete`; every cell passed is `Complete`.

## Trust Boundaries

- The local agent binds only to `127.0.0.1`; it is not reachable from the network.
- Browser origins are checked before the local agent accepts a submission request.
- A short-lived HMAC-signed grant binds one user, problem, language, and exact source hash.
- Program containers have no network, a read-only root filesystem, dropped Linux capabilities, and an isolated temporary workspace. PostgreSQL has a writable temporary data volume for initialization and no network. SQL cells may change only their disposable cloned test database; `problem_base` is never written by submitted SQL.
- The database rejects an exact repeat for the same user, problem, language, and `source_sha256`. A duplicate completion returns the existing submission ID without creating another row.

The current diagnostic mode intentionally returns all executed test data to the local browser after a run. For a production judge that needs hidden tests to remain secret, return only public-test detail and aggregate verdicts for hidden tests.

## Database Migration

[001_initial_schema.sql](001_initial_schema.sql) creates the SQLite schema and adds the `sum-two-integers` development problem with two sample tests and two hidden tests, plus the `engineering-roster` SQL problem. `languages` holds the shared Docker image for each language, while `problem_languages` records which languages a problem permits. The backend manifest now reads images from `languages`.

The demo rows use `python:3.13-alpine`, `node:22-alpine`, `gcc:14` for C/C++, and `eclipse-temurin:21-jdk-alpine` for Java compilation. The first two test rows by ID are samples, selected with `ORDER BY id LIMIT 2`. This is an initial migration for an empty database; the demo backend automatically converts its previous schema on startup, including the earlier grant-JTI submission format.
