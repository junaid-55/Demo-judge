# Demo Problem Guide

This guide is for creating a problem in the local SQLite backend, writing a solution, and verifying it with the packaged runner.

## Prerequisites

Install and verify:

- Docker Engine with permission to run docker commands.
- Docker Compose plugin.
- Python 3.11 or newer for the development submit helper.
- Linux x86_64 for the current packaged runner binary.

Check Docker:

    docker version
    docker compose version

The backend uses port 38123. The local runner uses port 37123. Stop another process using either port before starting this demo.

## Add a Problem

Edit `backend_draft/seed_problems.json` and add a new object to its top-level `problems` array. Add a language to the top-level `languages` array only when its runtime image is not already configured.

Required problem fields:

| Field | Meaning |
| --- | --- |
| slug | Unique lowercase URL-safe ID, such as reverse-string. |
| title | Visible problem title. |
| statement | Plain-text problem instructions. |
| time_limit_ms | Time limit for each test. |
| memory_limit_mb | Docker memory limit. |
| languages | Array of supported language names; each must exist in the top-level `languages` seed array. |
| tests | Array of public test cases. |

Each test case requires:

| Field | Meaning |
| --- | --- |
| input | Exact stdin string, including newlines. |
| expected_output | Exact expected stdout string. |

The first two inserted tests are shown as samples through `ORDER BY id LIMIT 2`; later rows are run-only tests. This order is the order in `tests` within the seed file. Use a new slug whenever changing test data. Seed data is idempotent: the backend adds a problem only when its slug is not already in SQLite. It intentionally does not overwrite existing tests or alter recorded submissions.

After editing seed data, rebuild and start the backend:

    cd backend_draft
    docker compose up --build

Leave this process running.

## Write a Solution

Create your own solution under source/solutions. For example:

    source/solutions/my_reverse_string.py

Use one of these language IDs when submitting:

| Language ID | File extension |
| --- | --- |
| python | .py |
| c | .c |
| cpp | .cpp |
| javascript | .js |
| java | .java |

The runner supplies test input through standard input and compares standard output with expected output. Do not print prompts or debugging text.

## Build and Start the Runner

Build from the editable source:

    ./source/build.sh

Start the generated user-facing binary:

    cd user_agent
    ./chakrikoi-runner --bootstrap bootstrap.json

Leave the runner process running. In a future installer-based release, the user service starts this automatically; this command is only for development verification.

## Submit a Solution

Open another terminal and run:

    cd user_agent
    python submit.py \
      --problem YOUR_PROBLEM_SLUG \
      --language python \
      --file ../source/solutions/my_reverse_string.py

Replace python and the file path with your language and solution file.

The helper delegates the source to the local runner. The helper does not request or see a run grant. The runner:

1. hashes your source code and requests a short-lived development grant;
2. fetches tests and executes Docker;
3. stores the complete result with the backend;
4. returns verdict, passed/total tests, per-test runtimes, failed output, and error text.

## Browser UI

The same delegated submission flow is available through the static UI in `ui`. Its deployment and local-agent setup are documented in `ui/README.md`.

## Expected Results

An accepted run has this shape:

    Verdict: accepted
    Passed: 5/5
    Maximum runtime: 12 ms

For a wrong answer, the report identifies each failed test and shows actual output. For compile or runtime errors, it prints the captured error message. A time limit failure reports time_limit_exceeded.

## Stop the Demo

Stop the runner with Ctrl+C in its terminal.

Stop the backend with Ctrl+C in its terminal, or run this from backend_draft:

    docker compose down

This keeps the SQLite Docker volume. Use docker compose down -v only when you intentionally want to delete all local problems, submissions, and test data.
