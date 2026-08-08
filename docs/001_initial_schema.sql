-- Chakrikoi Judge: normalized initial SQLite schema and development seed data.
-- Apply once to an empty SQLite database:
--   sqlite3 chakrikoi.db < docs/001_initial_schema.sql

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE languages (
  id INTEGER PRIMARY KEY,
  language_name TEXT NOT NULL UNIQUE,
  docker_image TEXT NOT NULL
);

CREATE TABLE problems (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  statement TEXT NOT NULL,
  time_limit_ms INTEGER NOT NULL,
  memory_limit_mb INTEGER NOT NULL
);

CREATE TABLE problem_languages (
  problem_id INTEGER NOT NULL REFERENCES problems(id),
  language_id INTEGER NOT NULL REFERENCES languages(id),
  PRIMARY KEY (problem_id, language_id)
);

CREATE TABLE test_cases (
  id INTEGER PRIMARY KEY,
  problem_id INTEGER NOT NULL REFERENCES problems(id),
  input TEXT NOT NULL,
  expected_output TEXT NOT NULL
);

CREATE TABLE submissions (
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
  UNIQUE (user_id, problem_id, language_id, source_sha256)
);

CREATE TABLE test_results (
  id INTEGER PRIMARY KEY,
  submission_id INTEGER NOT NULL REFERENCES submissions(id),
  test_case_id INTEGER NOT NULL REFERENCES test_cases(id),
  passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
  runtime_ms INTEGER NOT NULL,
  actual_output TEXT NOT NULL,
  error_output TEXT NOT NULL,
  UNIQUE (submission_id, test_case_id)
);

CREATE INDEX submissions_user_problem_reported_at
  ON submissions(user_id, problem_id, reported_at DESC);

-- An exact repeat by the same user for the same problem and language is blocked
-- by the UNIQUE constraint on submissions above.

INSERT INTO languages (language_name, docker_image) VALUES
  ('python', 'python:3.13-alpine'),
  ('c', 'gcc:14'),
  ('cpp', 'gcc:14'),
  ('javascript', 'node:22-alpine'),
  ('java', 'eclipse-temurin:21-jdk-alpine');

INSERT INTO problems (slug, title, statement, time_limit_ms, memory_limit_mb) VALUES
  ('sum-two-integers', 'Sum of Two Integers',
   'Read two signed integers from standard input and print their sum.', 1000, 128);

INSERT INTO problem_languages (problem_id, language_id)
SELECT p.id, l.id FROM problems p CROSS JOIN languages l
WHERE p.slug = 'sum-two-integers';

-- The first two inserted tests are public samples. The public API selects them
-- with ORDER BY id LIMIT 2; no display-order or sample flag is stored.
INSERT INTO test_cases (problem_id, input, expected_output)
SELECT id, '1 2' || char(10), '3' || char(10) FROM problems WHERE slug = 'sum-two-integers';
INSERT INTO test_cases (problem_id, input, expected_output)
SELECT id, '-10 15' || char(10), '5' || char(10) FROM problems WHERE slug = 'sum-two-integers';
INSERT INTO test_cases (problem_id, input, expected_output)
SELECT id, '0 0' || char(10), '0' || char(10) FROM problems WHERE slug = 'sum-two-integers';
INSERT INTO test_cases (problem_id, input, expected_output)
SELECT id, '999999999 1' || char(10), '1000000000' || char(10) FROM problems WHERE slug = 'sum-two-integers';

COMMIT;
