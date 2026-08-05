"""Dockerized SQLite backend for the runner-installation draft."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
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


def init_database() -> None:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with database() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS problems (
              id INTEGER PRIMARY KEY,
              slug TEXT NOT NULL UNIQUE,
              title TEXT NOT NULL,
              statement TEXT NOT NULL,
              time_limit_ms INTEGER NOT NULL,
              memory_limit_mb INTEGER NOT NULL,
              allowed_languages TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS test_cases (
              id INTEGER PRIMARY KEY,
              problem_id INTEGER NOT NULL REFERENCES problems(id),
              display_order INTEGER NOT NULL,
              input TEXT NOT NULL,
              expected_output TEXT NOT NULL,
              is_sample INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS submissions (
              id INTEGER PRIMARY KEY,
              grant_jti TEXT NOT NULL UNIQUE,
              user_id TEXT NOT NULL,
              problem_id INTEGER NOT NULL REFERENCES problems(id),
              language TEXT NOT NULL,
              source_code TEXT NOT NULL,
              source_sha256 TEXT NOT NULL,
              docker_image TEXT NOT NULL,
              client_version TEXT NOT NULL,
              overall_status TEXT NOT NULL,
              total_test_cases INTEGER NOT NULL,
              passed_test_cases INTEGER NOT NULL,
              max_runtime_ms INTEGER NOT NULL,
              reported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS submission_test_results (
              id INTEGER PRIMARY KEY,
              submission_id INTEGER NOT NULL REFERENCES submissions(id),
              test_case_id INTEGER NOT NULL REFERENCES test_cases(id),
              status TEXT NOT NULL,
              runtime_ms INTEGER NOT NULL,
              actual_output TEXT NOT NULL,
              error_output TEXT NOT NULL,
              UNIQUE(submission_id, test_case_id)
            );
        """)
        for problem in json.loads(Path(__file__).with_name("seed_problems.json").read_text(encoding="utf-8")):
            connection.execute(
                "INSERT OR IGNORE INTO problems(slug,title,statement,time_limit_ms,memory_limit_mb,allowed_languages) VALUES(?,?,?,?,?,?)",
                (problem["slug"], problem["title"], problem["statement"], problem["time_limit_ms"], problem["memory_limit_mb"], json.dumps(problem["allowed_languages"])),
            )
            problem_id = connection.execute("SELECT id FROM problems WHERE slug=?", (problem["slug"],)).fetchone()["id"]
            if connection.execute("SELECT 1 FROM test_cases WHERE problem_id=? LIMIT 1", (problem_id,)).fetchone():
                continue
            for test in problem["tests"]:
                connection.execute(
                    "INSERT INTO test_cases(problem_id,display_order,input,expected_output,is_sample) VALUES(?,?,?,?,?)",
                    (problem_id, test["display_order"], test["input"], test["expected_output"], test["is_sample"]),
                )


def problem_payload(connection: sqlite3.Connection, slug: str, include_expected: bool, include_hidden_tests: bool = True) -> dict[str, Any] | None:
    problem = connection.execute("SELECT * FROM problems WHERE slug=?", (slug,)).fetchone()
    if not problem:
        return None
    tests = connection.execute("SELECT * FROM test_cases WHERE problem_id=? ORDER BY display_order", (problem["id"],)).fetchall()
    return {
        "slug": problem["slug"],
        "title": problem["title"],
        "statement": problem["statement"],
        "time_limit_ms": problem["time_limit_ms"],
        "memory_limit_mb": problem["memory_limit_mb"],
        "allowed_languages": json.loads(problem["allowed_languages"]),
        "tests": [
            {
                "id": test["id"],
                "input": test["input"],
                **({"expected_output": test["expected_output"]} if include_expected or test["is_sample"] else {}),
                "is_sample": bool(test["is_sample"]),
            }
            for test in tests if include_hidden_tests or test["is_sample"]
        ],
    }


@APP.errorhandler(ValueError)
def invalid_request(error: ValueError):
    return jsonify(error=str(error)), 400


@APP.get("/v1/runner/manifest")
def manifest():
    return jsonify(
        version=1,
        allowed_origins=[item for item in os.environ.get("RUNNER_ALLOWED_ORIGINS", "").split(",") if item],
        api_paths={"grant": "/v1/local-runs/grants", "problem": "/v1/local-runs/problems/{slug}", "complete": "/v1/local-runs/complete"},
        images={
            "python": "python:3.13-alpine",
            "c": "gcc:14",
            "cpp": "gcc:14",
            "javascript": "node:22-alpine",
            "java": "eclipse-temurin:21-jdk",
        },
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
    if not problem or body["language"] not in problem["allowed_languages"]:
        raise ValueError("problem or language is not available")
    now = int(time.time())
    return jsonify(run_grant=grant_encode({
        "sub": user_id, "problem_slug": body["problem_slug"], "language": body["language"],
        "source_sha256": body["source_sha256"], "jti": secrets.token_urlsafe(18),
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
    required = ("docker_image", "client_version", "overall_status", "total_test_cases", "passed_test_cases", "max_runtime_ms", "test_results")
    if any(field not in body for field in required) or not isinstance(body["test_results"], list):
        raise ValueError("completion payload is incomplete")
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT id FROM submissions WHERE grant_jti=?", (claims["jti"],)).fetchone()
        if existing:
            return jsonify(submission_id=existing["id"], idempotent=True)
        problem = connection.execute("SELECT id FROM problems WHERE slug=?", (claims["problem_slug"],)).fetchone()
        if not problem:
            raise ValueError("problem no longer exists")
        cursor = connection.execute(
            """INSERT INTO submissions(grant_jti,user_id,problem_id,language,source_code,source_sha256,docker_image,client_version,overall_status,total_test_cases,passed_test_cases,max_runtime_ms)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (claims["jti"], claims["sub"], problem["id"], body["language"], body["source_code"], source_hash, body["docker_image"], body["client_version"], body["overall_status"], body["total_test_cases"], body["passed_test_cases"], body["max_runtime_ms"]),
        )
        for result in body["test_results"]:
            connection.execute(
                "INSERT INTO submission_test_results(submission_id,test_case_id,status,runtime_ms,actual_output,error_output) VALUES(?,?,?,?,?,?)",
                (cursor.lastrowid, result["test_case_id"], result["status"], result["runtime_ms"], result["actual_output"], result["error_output"]),
            )
    return jsonify(submission_id=cursor.lastrowid, idempotent=False), 201


init_database()

if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=38123)
