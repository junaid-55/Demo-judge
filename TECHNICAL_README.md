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

The current draft uses the X-Demo-User-Id header as an authentication adapter. It returns run_grant, an HMAC-signed token containing user, problem, language, source hash, expiry, audience, and jti.

### GET /v1/local-runs/problems/{slug}

Requires an Authorization Bearer run grant. It returns slug, time_limit_ms, memory_limit_mb, allowed_languages, and all public tests. Each test contains id, input, expected_output, and is_sample.

### POST /v1/local-runs/complete

Requires the same bearer grant. The runner sends problem_slug, language, source_code, docker_image, client_version, overall_status, total_test_cases, passed_test_cases, max_runtime_ms, and test_results.

Each test_results item has test_case_id, status, runtime_ms, actual_output, and error_output. The backend verifies the grant and source hash, then inserts submissions and submission_test_results in one SQLite transaction. The grant jti is unique, so retrying a lost completion response does not insert a duplicate.

## Runner Functions

| Function | Responsibility |
| --- | --- |
| Service.__init__ | Loads bootstrap configuration and the backend manifest. |
| Service.start | Allocates a local run ID and starts a worker thread. |
| Service.run | Fetches problem data, invokes Docker execution, and posts completion. |
| Service.execute | Pulls the selected image, compiles once, executes all tests, and computes the verdict. |
| Service.docker | Creates restricted Docker commands with no network, read-only root, dropped capabilities, temporary filesystem, and workspace mount. |
| Service.status | Supports long-polling local status with wait=30. |
| request_json | Performs backend HTTP requests. |
| normalized | Compares output while ignoring trailing whitespace differences. |

## Build Pipeline

source/build.sh creates or reuses source/.build-venv, installs a Python-3.14-compatible PyInstaller when needed, packages runner.py into user_agent/chakrikoi-runner, and creates symlinks for bootstrap configuration, submit client, systemd unit, solutions, and source tests.

## Tests

- source/tests/test_runner.py verifies runner helpers and language profiles.
- user_agent/tests/test_user_package.py verifies the generated binary and user-package runtime links.
