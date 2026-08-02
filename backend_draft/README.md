# Runner Backend Draft

This is a Dockerized SQLite backend for the installed-runner protocol. It is separate from the root demo backend.

## Run

    docker compose up --build

It listens on port 38123 through Gunicorn and persists data in the judge-data Docker volume.

After the container starts, exercise the complete backend API with:

    python smoke_test.py

## Endpoints

- GET /v1/runner/manifest returns backend-owned runner configuration.
- POST /v1/local-runs/grants issues a five-minute HMAC-signed run grant. This draft reads X-Demo-User-Id; replace that header lookup with the real platform authentication adapter.
- GET /v1/local-runs/problems/{slug} requires Bearer grant and returns the complete public test set.
- POST /v1/local-runs/complete requires Bearer grant and atomically inserts the completed submission and test rows.

The completion path uses the grant jti as a unique idempotency key. Retrying the same successful completion returns the existing submission instead of creating a duplicate.

## Deployment

Set GRANT_SIGNING_SECRET to a unique value of at least 32 characters and use HTTPS outside local development. Change backend_url in the installed runner bootstrap configuration when moving this container to another host.
