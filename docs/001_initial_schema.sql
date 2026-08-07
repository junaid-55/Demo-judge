-- Chakrikoi Judge: initial SQLite schema and development seed data.
-- Apply once to an empty SQLite database:
--   sqlite3 chakrikoi.db < docs/001_initial_schema.sql

PRAGMA foreign_keys = ON;

BEGIN;

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
  is_sample INTEGER NOT NULL CHECK (is_sample IN (0, 1)),
  UNIQUE(problem_id, display_order)
);

-- Shared language runtime configuration. Java needs a JDK image because
-- submissions are compiled inside the container.
CREATE TABLE IF NOT EXISTS runtime_images (
  language TEXT PRIMARY KEY,
  docker_image TEXT NOT NULL
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

CREATE INDEX IF NOT EXISTS submissions_user_problem_reported_at
  ON submissions(user_id, problem_id, reported_at DESC);

-- Development problem: mirrors the shape expected by the local runner.
INSERT OR IGNORE INTO problems (
  slug, title, statement, time_limit_ms, memory_limit_mb, allowed_languages
) VALUES (
  'sum-two-integers',
  'Sum of Two Integers',
  'Read two signed integers from standard input and print their sum.',
  1000,
  128,
  '["python", "c", "cpp", "javascript", "java"]'
);

INSERT OR IGNORE INTO test_cases (
  problem_id, display_order, input, expected_output, is_sample
) SELECT id, 1, '1 2' || char(10), '3' || char(10), 1
  FROM problems WHERE slug = 'sum-two-integers';

INSERT OR IGNORE INTO test_cases (
  problem_id, display_order, input, expected_output, is_sample
) SELECT id, 2, '-10 15' || char(10), '5' || char(10), 1
  FROM problems WHERE slug = 'sum-two-integers';

INSERT OR IGNORE INTO test_cases (
  problem_id, display_order, input, expected_output, is_sample
) SELECT id, 3, '0 0' || char(10), '0' || char(10), 0
  FROM problems WHERE slug = 'sum-two-integers';

INSERT OR IGNORE INTO test_cases (
  problem_id, display_order, input, expected_output, is_sample
) SELECT id, 4, '999999999 1' || char(10), '1000000000' || char(10), 0
  FROM problems WHERE slug = 'sum-two-integers';

-- Minimal official runtime images shared by all problems that allow the language.
INSERT OR IGNORE INTO runtime_images (language, docker_image) VALUES
  ('python', 'python:3.13-alpine'),
  ('c', 'gcc:14'),
  ('cpp', 'gcc:14'),
  ('javascript', 'node:22-alpine'),
  ('java', 'eclipse-temurin:21-jdk-alpine');

COMMIT;
