"""Dockerized SQLite backend for the runner-installation draft."""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

APP = Flask(__name__)
DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/chakrikoi.db")
SIGNING_SECRET = os.environ.get("GRANT_SIGNING_SECRET", "").encode()
if len(SIGNING_SECRET) < 32:
    raise RuntimeError("GRANT_SIGNING_SECRET must be at least 32 characters")


def allowed_browser_origin(origin: str | None) -> bool:
    patterns = [item for item in os.environ.get("RUNNER_ALLOWED_ORIGINS", "").split(",") if item]
    return bool(origin) and any(fnmatch.fnmatchcase(origin, pattern) for pattern in patterns)


@APP.after_request
def public_problem_cors(response):
    """Allow the deployed UI to read public problem metadata from this backend."""
    origin = request.headers.get("Origin")
    if request.path.startswith("/v1/problems") and allowed_browser_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Vary"] = "Origin"
    return response


def b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def grant_encode(claims: dict[str, Any]) -> str:
    header = b64_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64_encode(json.dumps(claims, separators=(",", ":")).encode())
    signature = b64_encode(hmac.new(SIGNING_SECRET, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def grant_decode(token: str) -> dict[str, Any]:
    try:
        header, payload, signature = token.split(".")
        expected = hmac.new(SIGNING_SECRET, f"{header}.{payload}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, b64_decode(signature)):
            raise ValueError("invalid signature")
        claims = json.loads(b64_decode(payload))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid run grant") from error
    if claims.get("aud") != "chakrikoi-local-runner" or claims.get("exp", 0) < time.time():
        raise ValueError("expired or invalid run grant")
    return claims


def require_grant() -> dict[str, Any]:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ValueError("missing bearer run grant")
    return grant_decode(header.removeprefix("Bearer "))


@contextmanager
def database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS languages (
          id INTEGER PRIMARY KEY,
          language_name TEXT NOT NULL UNIQUE,
          docker_image TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS problems (
          id INTEGER PRIMARY KEY,
          slug TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          statement TEXT NOT NULL,
          time_limit_ms INTEGER NOT NULL,
          memory_limit_mb INTEGER NOT NULL,
          sql_schema TEXT,
          sql_fixture TEXT
        );
        CREATE TABLE IF NOT EXISTS problem_languages (
          problem_id INTEGER NOT NULL REFERENCES problems(id),
          language_id INTEGER NOT NULL REFERENCES languages(id),
          PRIMARY KEY(problem_id, language_id)
        );
        CREATE TABLE IF NOT EXISTS test_cases (
          id INTEGER PRIMARY KEY,
          problem_id INTEGER NOT NULL REFERENCES problems(id),
          input TEXT NOT NULL,
          expected_output TEXT NOT NULL,
          sql_delta TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS submissions (
          id INTEGER PRIMARY KEY,
          user_id TEXT NOT NULL,
          problem_id INTEGER NOT NULL REFERENCES problems(id),
          language_id INTEGER NOT NULL REFERENCES languages(id),
          source_code TEXT NOT NULL,
          source_sha256 TEXT NOT NULL,
          client_version TEXT NOT NULL,
          overall_status TEXT NOT NULL,
          max_runtime_ms INTEGER NOT NULL,
          reported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(user_id, problem_id, language_id, source_sha256)
        );
        CREATE TABLE IF NOT EXISTS test_results (
          id INTEGER PRIMARY KEY,
          submission_id INTEGER NOT NULL REFERENCES submissions(id),
          test_case_id INTEGER NOT NULL REFERENCES test_cases(id),
          passed INTEGER NOT NULL CHECK(passed IN (0, 1)),
          runtime_ms INTEGER NOT NULL,
          actual_output TEXT NOT NULL,
          error_output TEXT NOT NULL,
          UNIQUE(submission_id, test_case_id)
        );
        CREATE INDEX IF NOT EXISTS submissions_user_problem_reported_at
          ON submissions(user_id, problem_id, reported_at DESC);
    """)


def migrate_legacy_schema(connection: sqlite3.Connection) -> None:
    """Convert the previous JSON-language demo schema without losing submissions."""
    legacy_tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("submission_test_results", "submissions", "test_cases", "problems"):
        if table in legacy_tables:
            connection.execute(f"ALTER TABLE {table} RENAME TO legacy_{table}")
    create_schema(connection)
    seed = json.loads(Path(__file__).with_name("seed_problems.json").read_text(encoding="utf-8"))
    for language in seed["languages"]:
        connection.execute("INSERT INTO languages(language_name,docker_image) VALUES(?,?)", (language["language_name"], language["docker_image"]))
    for problem in connection.execute("SELECT * FROM legacy_problems"):
        connection.execute("INSERT INTO problems(id,slug,title,statement,time_limit_ms,memory_limit_mb) VALUES(?,?,?,?,?,?)", tuple(problem[key] for key in ("id", "slug", "title", "statement", "time_limit_ms", "memory_limit_mb")))
        for language_name in json.loads(problem["allowed_languages"]):
            language_id = connection.execute("SELECT id FROM languages WHERE language_name=?", (language_name,)).fetchone()["id"]
            connection.execute("INSERT INTO problem_languages(problem_id,language_id) VALUES(?,?)", (problem["id"], language_id))
    if "test_cases" in legacy_tables:
        connection.execute("INSERT INTO test_cases(id,problem_id,input,expected_output) SELECT id,problem_id,input,expected_output FROM legacy_test_cases ORDER BY id")
    if "submissions" in legacy_tables:
        connection.execute("""INSERT OR IGNORE INTO submissions(id,user_id,problem_id,language_id,source_code,source_sha256,client_version,overall_status,max_runtime_ms,reported_at)
            SELECT s.id,s.user_id,s.problem_id,l.id,s.source_code,s.source_sha256,s.client_version,s.overall_status,s.max_runtime_ms,s.reported_at
            FROM legacy_submissions s JOIN languages l ON l.language_name=s.language ORDER BY s.id""")
    if "submission_test_results" in legacy_tables:
        connection.execute("""INSERT INTO test_results(id,submission_id,test_case_id,passed,runtime_ms,actual_output,error_output)
            SELECT id,submission_id,test_case_id,status='passed',runtime_ms,actual_output,error_output
            FROM legacy_submission_test_results WHERE submission_id IN (SELECT id FROM submissions)""")
    for table in ("submission_test_results", "submissions", "test_cases", "problems"):
        if table in legacy_tables:
            connection.execute(f"DROP TABLE legacy_{table}")


def migrate_grant_jti_schema(connection: sqlite3.Connection) -> None:
    """Replace grant-based idempotency with the scoped source-hash rule."""
    connection.execute("ALTER TABLE test_results RENAME TO legacy_test_results_source_hash")
    connection.execute("ALTER TABLE submissions RENAME TO legacy_submissions_source_hash")
    create_schema(connection)
    connection.execute("""INSERT OR IGNORE INTO submissions(id,user_id,problem_id,language_id,source_code,source_sha256,client_version,overall_status,max_runtime_ms,reported_at)
        SELECT id,user_id,problem_id,language_id,source_code,source_sha256,client_version,overall_status,max_runtime_ms,reported_at
        FROM legacy_submissions_source_hash ORDER BY id""")
    connection.execute("""INSERT INTO test_results(id,submission_id,test_case_id,passed,runtime_ms,actual_output,error_output)
        SELECT id,submission_id,test_case_id,passed,runtime_ms,actual_output,error_output
        FROM legacy_test_results_source_hash WHERE submission_id IN (SELECT id FROM submissions)""")
    connection.execute("DROP TABLE legacy_test_results_source_hash")
    connection.execute("DROP TABLE legacy_submissions_source_hash")


def init_database() -> None:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with database() as connection:
        legacy_columns = {row["name"] for row in connection.execute("PRAGMA table_info(problems)")}
        if "allowed_languages" in legacy_columns:
            migrate_legacy_schema(connection)
        submission_columns = {row["name"] for row in connection.execute("PRAGMA table_info(submissions)")}
        if "grant_jti" in submission_columns:
            migrate_grant_jti_schema(connection)
        create_schema(connection)
        problem_columns = {row["name"] for row in connection.execute("PRAGMA table_info(problems)")}
        if "sql_fixture" not in problem_columns:
            connection.execute("ALTER TABLE problems ADD COLUMN sql_fixture TEXT")
        if "sql_schema" not in problem_columns:
            connection.execute("ALTER TABLE problems ADD COLUMN sql_schema TEXT")
        test_columns = {row["name"] for row in connection.execute("PRAGMA table_info(test_cases)")}
        if "sql_delta" not in test_columns:
            connection.execute("ALTER TABLE test_cases ADD COLUMN sql_delta TEXT NOT NULL DEFAULT ''")
        seed = json.loads(Path(__file__).with_name("seed_problems.json").read_text(encoding="utf-8"))
        for language in seed["languages"]:
            connection.execute("INSERT OR IGNORE INTO languages(language_name,docker_image) VALUES(?,?)", (language["language_name"], language["docker_image"]))
        for problem in seed["problems"]:
            connection.execute("""INSERT OR IGNORE INTO problems(slug,title,statement,time_limit_ms,memory_limit_mb,sql_schema,sql_fixture)
                VALUES(?,?,?,?,?,?,?)""", (problem["slug"], problem["title"], problem["statement"], problem["time_limit_ms"], problem["memory_limit_mb"], problem.get("sql_schema"), problem.get("sql_fixture")))
            problem_id = connection.execute("SELECT id FROM problems WHERE slug=?", (problem["slug"],)).fetchone()["id"]
            if problem.get("sql_schema"):
                connection.execute("UPDATE problems SET sql_schema=? WHERE id=? AND sql_schema IS NULL", (problem["sql_schema"], problem_id))
            for language_name in problem["languages"]:
                language_id = connection.execute("SELECT id FROM languages WHERE language_name=?", (language_name,)).fetchone()["id"]
                connection.execute("INSERT OR IGNORE INTO problem_languages(problem_id,language_id) VALUES(?,?)", (problem_id, language_id))
            if not connection.execute("SELECT 1 FROM test_cases WHERE problem_id=? LIMIT 1", (problem_id,)).fetchone():
                for test in problem["tests"]:
                    connection.execute("INSERT INTO test_cases(problem_id,input,expected_output,sql_delta) VALUES(?,?,?,?)", (problem_id, test["input"], test["expected_output"], test.get("sql_delta", "")))


def problem_payload(connection: sqlite3.Connection, slug: str, include_expected: bool, include_hidden_tests: bool = True) -> dict[str, Any] | None:
    problem = connection.execute("SELECT * FROM problems WHERE slug=?", (slug,)).fetchone()
    if not problem:
        return None
    languages = connection.execute("""SELECT l.language_name FROM languages l JOIN problem_languages pl ON pl.language_id=l.id
        WHERE pl.problem_id=? ORDER BY l.id""", (problem["id"],)).fetchall()
    limit = "" if include_hidden_tests else " LIMIT 2"
    tests = connection.execute(f"SELECT * FROM test_cases WHERE problem_id=? ORDER BY id{limit}", (problem["id"],)).fetchall()
    return {
        "slug": problem["slug"], "title": problem["title"], "statement": problem["statement"],
        "time_limit_ms": problem["time_limit_ms"], "memory_limit_mb": problem["memory_limit_mb"],
        "execution_mode": "sql" if problem["sql_fixture"] is not None else "program",
        **({"sql_schema": problem["sql_schema"]} if problem["sql_schema"] is not None else {}),
        "allowed_languages": [language["language_name"] for language in languages],
        **({"sql_fixture": problem["sql_fixture"]} if include_expected and problem["sql_fixture"] is not None else {}),
        "tests": [{"id": test["id"], "input": test["input"], **({"expected_output": test["expected_output"], "sql_delta": test["sql_delta"]} if include_expected else ({"expected_output": test["expected_output"]} if not include_hidden_tests else {})), "is_sample": not include_hidden_tests} for test in tests],
    }


@APP.errorhandler(ValueError)
def invalid_request(error: ValueError):
    return jsonify(error=str(error)), 400


@APP.get("/v1/runner/manifest")
def manifest():
    with database() as connection:
        images = {row["language_name"]: row["docker_image"] for row in connection.execute("SELECT language_name,docker_image FROM languages")}
    return jsonify(
        version=1,
        allowed_origins=[item for item in os.environ.get("RUNNER_ALLOWED_ORIGINS", "").split(",") if item],
        api_paths={"grant": "/v1/local-runs/grants", "problem": "/v1/local-runs/problems/{slug}", "complete": "/v1/local-runs/complete"},
        images=images,
        expires_at=int(time.time()) + 3600,
    )


@APP.get("/v1/problems")
def public_problem_list():
    with database() as connection:
        slugs = connection.execute("SELECT slug FROM problems ORDER BY id").fetchall()
        problems = [problem_payload(connection, row["slug"], include_expected=False, include_hidden_tests=False) for row in slugs]
    return jsonify(problems=problems)


@APP.get("/v1/problems/<slug>")
def public_problem(slug: str):
    with database() as connection:
        problem = problem_payload(connection, slug, include_expected=False, include_hidden_tests=False)
    return jsonify(problem) if problem else (jsonify(error="not found"), 404)


@APP.post("/v1/local-runs/grants")
def create_grant():
    body = request.get_json(force=True)
    user_id = request.headers.get("X-Demo-User-Id")
    if not user_id:
        raise ValueError("authentication adapter did not provide a user")
    required = ("problem_slug", "language", "source_sha256")
    if not all(isinstance(body.get(field), str) and body[field] for field in required):
        raise ValueError("problem_slug, language, and source_sha256 are required")
    with database() as connection:
        problem = problem_payload(connection, body["problem_slug"], include_expected=False)
        existing = connection.execute("""SELECT s.id FROM submissions s
            JOIN problems p ON p.id=s.problem_id JOIN languages l ON l.id=s.language_id
            WHERE s.user_id=? AND p.slug=? AND l.language_name=? AND s.source_sha256=?""",
            (user_id, body["problem_slug"], body["language"], body["source_sha256"]),
        ).fetchone()
    if not problem or body["language"] not in problem["allowed_languages"]:
        raise ValueError("problem or language is not available")
    if existing:
        return jsonify(error="this exact solution was already submitted", submission_id=existing["id"], duplicate=True), 409
    now = int(time.time())
    return jsonify(run_grant=grant_encode({
        "sub": user_id, "problem_slug": body["problem_slug"], "language": body["language"],
        "source_sha256": body["source_sha256"],
        "aud": "chakrikoi-local-runner", "iat": now, "exp": now + 300,
    }))


@APP.get("/v1/local-runs/problems/<slug>")
def runner_problem(slug: str):
    claims = require_grant()
    if claims["problem_slug"] != slug:
        raise ValueError("grant is not valid for this problem")
    with database() as connection:
        problem = problem_payload(connection, slug, include_expected=True)
    return jsonify(problem) if problem else (jsonify(error="not found"), 404)


@APP.post("/v1/local-runs/complete")
def complete_run():
    claims = require_grant()
    body = request.get_json(force=True)
    source_hash = hashlib.sha256(body.get("source_code", "").encode()).hexdigest()
    if (body.get("problem_slug"), body.get("language"), source_hash) != (claims["problem_slug"], claims["language"], claims["source_sha256"]):
        raise ValueError("completion does not match the run grant")
    required = ("client_version", "overall_status", "max_runtime_ms", "test_results")
    if any(field not in body for field in required) or not isinstance(body["test_results"], list):
        raise ValueError("completion payload is incomplete")
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        problem = connection.execute("SELECT id FROM problems WHERE slug=?", (claims["problem_slug"],)).fetchone()
        language = connection.execute("SELECT id FROM languages WHERE language_name=?", (claims["language"],)).fetchone()
        if not problem or not language or not connection.execute("SELECT 1 FROM problem_languages WHERE problem_id=? AND language_id=?", (problem["id"], language["id"])).fetchone():
            raise ValueError("problem no longer exists")
        test_ids = {row["id"] for row in connection.execute("SELECT id FROM test_cases WHERE problem_id=?", (problem["id"],))}
        if {item.get("test_case_id") for item in body["test_results"]} != test_ids:
            raise ValueError("completion test results do not match the problem")
        cursor = connection.execute(
            """INSERT INTO submissions(user_id,problem_id,language_id,source_code,source_sha256,client_version,overall_status,max_runtime_ms)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id,problem_id,language_id,source_sha256) DO NOTHING""",
            (claims["sub"], problem["id"], language["id"], body["source_code"], source_hash, body["client_version"], body["overall_status"], body["max_runtime_ms"]),
        )
        if cursor.rowcount == 0:
            existing = connection.execute(
                "SELECT id FROM submissions WHERE user_id=? AND problem_id=? AND language_id=? AND source_sha256=?",
                (claims["sub"], problem["id"], language["id"], source_hash),
            ).fetchone()
            return jsonify(error="this exact solution was already submitted", submission_id=existing["id"], duplicate=True), 409
        for result in body["test_results"]:
            connection.execute(
                "INSERT INTO test_results(submission_id,test_case_id,passed,runtime_ms,actual_output,error_output) VALUES(?,?,?,?,?,?)",
                (cursor.lastrowid, result["test_case_id"], int(result["status"] == "passed"), result["runtime_ms"], result["actual_output"], result["error_output"]),
            )
    return jsonify(submission_id=cursor.lastrowid, duplicate=False), 201


init_database()

if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=38123)
