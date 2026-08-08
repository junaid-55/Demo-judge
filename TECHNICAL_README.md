# Technical Reference

## Components

| Path | Purpose |
| --- | --- |
| backend_draft/app.py | Flask and Gunicorn backend, SQLite schema, grants, manifest, problem and completion APIs. |
| backend_draft/seed_problems.json | Idempotently seeded problems and public tests. |
| source/runner/chakrikoi_installed_runner/runner.py | Loopback agent, Docker execution, result aggregation, and backend calls. |
| source/submit.py | Development submit client and human-readable result report. |
| source/build.sh | One-command PyInstaller build pipeline. |
| user_agent | Generated binary plus source-linked runtime files. |
| ui | Static Netlify UI; it communicates only with the local runner. |

## Backend API

### GET /v1/runner/manifest

Returns version, allowed_origins, api_paths, images, and expires_at. The runner uses it to determine permitted browser origins and the Docker image for each language.

### POST /v1/local-runs/grants

Request fields:

| Field | Meaning |
| --- | --- |
| problem_slug | Target problem identifier. |
| language | Submitted language. |
| source_sha256 | SHA-256 hash of the exact source text. |

The current draft uses the X-Demo-User-Id header as an authentication adapter. It returns run_grant, an HMAC-signed token containing user, problem, language, source hash, expiry, and audience. Before granting a run, the backend returns `409 Conflict` when that user has already submitted the exact source hash for that problem and language.

The browser never calls this API. `Service.run` obtains the grant after the browser has delegated a submission to the loopback runner.

### GET /v1/problems and GET /v1/problems/{slug}

Public catalog endpoints used directly by the browser UI. They return statement, limits, language list, and sample tests only. Hidden test input and expected output stay behind the grant-required runner endpoint. These endpoints add CORS only for origins allowed by the backend configuration.

### GET /v1/local-runs/problems/{slug}

Requires an Authorization Bearer run grant. It returns slug, time_limit_ms, memory_limit_mb, allowed_languages, and all tests. `allowed_languages` is assembled from `problem_languages` and `languages`; the first two test rows by ID are marked as samples for the UI.

### POST /v1/local-runs/complete

Requires the same bearer grant. The runner sends problem_slug, language, source_code, client_version, overall_status, max_runtime_ms, and test_results.

Each test_results item has test_case_id, status, runtime_ms, actual_output, and error_output. The backend verifies the grant and source hash, resolves `language_id`, then inserts `submissions` and boolean `test_results.passed` rows in one SQLite transaction. Test counts are computed from `test_results`; Docker image configuration belongs to `languages`. A unique `(user_id, problem_id, language_id, source_sha256)` constraint rejects an exact repeat and returns the existing submission ID.

## Loopback Agent API

The user-facing runner binds only to `127.0.0.1`. It permits the exact origins named by the backend manifest; the demo manifest includes `https://*.netlify.app` so a deployed Netlify site can call it. It handles browser `OPTIONS` preflight requests and sends CORS and private-network headers only to allowed origins.

### GET /v1/health

Returns `status` and `docker_available`. The UI uses it to indicate whether local submission execution is available.

### POST /v1/runs

Browser request fields are `problem_slug`, `language`, and `source_code`. The browser supplies no grant. The runner computes the source hash, requests the grant using its configured local identity, fetches all test expected output with that grant, executes Docker, and posts completion.

The response is `202` with `run_id` and `status: queued`.

### GET /v1/runs/{run_id}?wait=25

Long-polls local status. Intermediate states include `requesting_grant`, `fetching_problem`, and `running`. A completed response includes `result`, including the overall verdict and one result per test. In the current diagnostic mode, each local result includes its input, expected output, actual output, and captured error output; only the existing persisted result fields are sent to backend completion.

## Runner Functions

| Function | Responsibility |
| --- | --- |
| Service.__init__ | Loads bootstrap configuration and the backend manifest. |
| Service.accepts_origin | Matches the manifest allow-list, including the demo Netlify wildcard. |
| Service.start | Allocates a local run ID and starts a worker thread. |
| Service.run | Requests a signed grant, fetches private test data, invokes Docker execution, and posts completion. |
| Service.execute | Pulls the selected image, compiles once, executes all tests, and computes the verdict. |
| Service.ensure_image | Pulls a missing Docker runtime automatically, retrying once before reporting Docker's error. |
| Service.docker | Creates restricted Docker commands with no network, read-only root, dropped capabilities, temporary filesystem, and workspace mount. |
| Service.status | Supports long-polling local status with wait=30. |
| request_json | Performs backend HTTP requests. |
| normalized | Compares output while ignoring trailing whitespace differences. |

## Build Pipeline

source/build.sh creates or reuses source/.build-venv, installs a Python-3.14-compatible PyInstaller when needed, packages runner.py into user_agent/chakrikoi-runner, and creates symlinks for bootstrap configuration, submit client, systemd unit, solutions, and source tests.

The `ui` directory has no Node dependency or build step. `ui/netlify.toml` publishes the directory as static files and adds basic browser security headers.

## Tests

- source/tests/test_runner.py verifies runner helpers and language profiles.
- user_agent/tests/test_user_package.py verifies the generated binary and user-package runtime links.
