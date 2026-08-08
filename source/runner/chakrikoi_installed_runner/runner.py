"""Manifest-aware loopback runner used by the installation draft."""

from __future__ import annotations

import argparse, fnmatch, hashlib, json, os, shutil, subprocess, tempfile, threading, time, uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

PROFILES = {
    "python": (".py", [], ["python3", "/workspace/solution.py"]),
    "c": (".c", ["sh", "-c", "gcc -x c /workspace/solution.c -O2 -o /workspace/main"], ["/workspace/main"]),
    "cpp": (".cpp", ["sh", "-c", "g++ -x c++ /workspace/solution.cpp -O2 -o /workspace/main"], ["/workspace/main"]),
    "javascript": (".js", [], ["node", "/workspace/solution.js"]),
    "java": (".java", ["javac", "-d", "/workspace", "/workspace/solution.java"], ["java", "-cp", "/workspace", "solution"]),
}


def request_json(method, url, body=None, headers=None):
    request = Request(url, data=json.dumps(body).encode() if body else None,
                      headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode()) if response.length != 0 else {}
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode()).get("error")
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = None
        raise RuntimeError(detail or f"backend request failed with HTTP {error.code}") from error


def normalized(value):
    return "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").split("\n")).rstrip()


class Service:
    def __init__(self, bootstrap):
        self.base = bootstrap["backend_url"].rstrip("/")
        self.manifest = request_json("GET", self.base + bootstrap["manifest_path"])
        self.origins = set(self.manifest["allowed_origins"])
        self.user_id = bootstrap.get("demo_user_id", "local-demo-user")
        self.runs, self.lock, self.changed = {}, threading.Lock(), None
        self.changed = threading.Condition(self.lock)
        self.sql_sessions, self.sql_lock = {}, threading.Lock()

    def accepts_origin(self, origin):
        return bool(origin) and any(fnmatch.fnmatchcase(origin, pattern) for pattern in self.origins)

    def start(self, data, worker=None):
        run_id = str(uuid.uuid4())
        with self.changed:
            self.runs[run_id] = {"status": "queued", "detail": ""}
        threading.Thread(target=worker or self.run, args=(run_id, data), daemon=True).start()
        return run_id

    def set(self, run_id, status, detail="", result=None):
        with self.changed:
            self.runs[run_id] = {"status": status, "detail": detail}
            if result is not None:
                self.runs[run_id]["result"] = result
            self.changed.notify_all()

    def status(self, run_id, wait=0):
        with self.changed:
            current = self.runs.get(run_id)
            if current and current["status"] not in {"completed", "failed"} and wait:
                self.changed.wait(min(wait, 30))
            current = self.runs.get(run_id)
            return dict(current) if current else None

    def run(self, run_id, data):
        try:
            slug, language, source = (data[key] for key in ("problem_slug", "language", "source_code"))
            if language == "sql":
                raise ValueError("SQL problems run through individual notebook cells")
            self.set(run_id, "requesting_grant")
            grant = request_json(
                "POST", self.base + self.manifest["api_paths"]["grant"],
                {"problem_slug": slug, "language": language, "source_sha256": hashlib.sha256(source.encode()).hexdigest()},
                {"X-Demo-User-Id": self.user_id},
            )["run_grant"]
            self.set(run_id, "fetching_problem")
            problem_path = self.manifest["api_paths"]["problem"].replace("{slug}", slug)
            problem = request_json("GET", self.base + problem_path, headers={"Authorization": f"Bearer {grant}"})
            if language not in problem["allowed_languages"] or (language != "sql" and language not in PROFILES):
                raise ValueError("unsupported language")
            image = self.manifest["images"][language]
            progress = lambda detail: self.set(run_id, "preparing_runtime", detail)
            result = self.execute_sql(source, problem, image, progress) if language == "sql" else self.execute(language, source, problem, image, progress)
            self.set(run_id, "running")
            completion_result = {
                "overall_status": result["overall_status"],
                "max_runtime_ms": result["max_runtime_ms"],
                "test_results": [
                    {field: item[field] for field in ("test_case_id", "status", "runtime_ms", "actual_output", "error_output")}
                    for item in result["test_results"]
                ],
            }
            payload = {
                "problem_slug": slug, "language": language, "source_code": source,
                "client_version": "installed-draft-0.1",
                **completion_result,
            }
            request_json("POST", self.base + "/v1/local-runs/complete", payload, {"Authorization": f"Bearer {grant}"})
            self.set(run_id, "completed", result["overall_status"], result)
        except Exception as error:
            self.set(run_id, "failed", str(error))

    def run_sql_cell(self, run_id, data):
        try:
            slug, source, test_case_id = data["problem_slug"], data["source_code"], data["test_case_id"]
            self.set(run_id, "requesting_grant")
            grant = request_json(
                "POST", self.base + self.manifest["api_paths"]["grant"],
                {"problem_slug": slug, "language": "sql", "source_sha256": hashlib.sha256(source.encode()).hexdigest()},
                {"X-Demo-User-Id": self.user_id},
            )["run_grant"]
            self.set(run_id, "fetching_problem")
            problem_path = self.manifest["api_paths"]["problem"].replace("{slug}", slug)
            problem = request_json("GET", self.base + problem_path, headers={"Authorization": f"Bearer {grant}"})
            if "sql" not in problem["allowed_languages"]:
                raise ValueError("this problem does not support SQL cells")
            test = next((item for item in problem["tests"] if item["id"] == test_case_id), None)
            if not test:
                raise ValueError("SQL test case does not belong to this problem")
            result = self.execute_sql_test(source, problem, self.manifest["images"]["sql"], test, lambda detail: self.set(run_id, "preparing_runtime", detail))
            public_result = {field: result[field] for field in ("test_case_id", "status", "runtime_ms", "actual_output", "error_output", "exit_code")}
            self.set(run_id, "completed", result["status"], {"passed": result["status"] == "passed", "test": public_result})
        except Exception as error:
            self.set(run_id, "failed", str(error))

    def ensure_image(self, image, progress):
        if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0:
            return
        errors = []
        for attempt in range(1, 3):
            progress(f"Downloading runtime {image} (attempt {attempt}/2)")
            pulled = subprocess.run(["docker", "pull", image], text=True, capture_output=True)
            if pulled.returncode == 0:
                return
            errors.append((pulled.stderr or pulled.stdout or "Docker returned no error output").strip())
            if attempt == 1:
                time.sleep(2)
        detail = errors[-1]
        raise RuntimeError(f"Could not download runtime image {image} after 2 attempts: {detail}")

    def sql_command(self, container, database, source, user="judge", timeout=20):
        return subprocess.run(
            ["docker", "exec", "-i", "-e", f"PGPASSWORD={user}", "-e", "PGOPTIONS=-c statement_timeout=1000", container,
             "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", user, "-d", database, "-A", "-t", "-F", "\t"],
            input=source, text=True, capture_output=True, timeout=timeout,
        )

    def release_sql_session(self, slug):
        with self.sql_lock:
            session = self.sql_sessions.pop(slug, None)
        if not session:
            return
        subprocess.run(["docker", "rm", "--force", session["container"]], capture_output=True)
        subprocess.run(["docker", "volume", "rm", session["volume"]], capture_output=True)

    def sql_session(self, problem, image, progress):
        with self.sql_lock:
            session = self.sql_sessions.get(problem["slug"])
            if session:
                return session
            volume = f"chakrikoi-sql-{uuid.uuid4().hex}"
            created = subprocess.run(["docker", "volume", "create", volume], text=True, capture_output=True)
            if created.returncode:
                raise RuntimeError(created.stderr or "could not create SQL runtime volume")
            progress("Starting PostgreSQL runtime")
            started = subprocess.run([
                "docker", "run", "-d", "--rm", "--network", "none", "--memory", "256m",
                "--security-opt", "no-new-privileges", "-e", "POSTGRES_USER=judge", "-e", "POSTGRES_PASSWORD=judge",
                "-v", f"{volume}:/var/lib/postgresql/data", image,
            ], text=True, capture_output=True)
            if started.returncode:
                subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
                raise RuntimeError(started.stderr or "could not start PostgreSQL runtime")
            session = {"container": started.stdout.strip(), "volume": volume}
            try:
                for _ in range(120):
                    ready = subprocess.run(["docker", "exec", session["container"], "pg_isready", "-U", "judge"], capture_output=True)
                    if ready.returncode == 0:
                        break
                    time.sleep(0.5)
                else:
                    logs = subprocess.run(["docker", "logs", session["container"]], text=True, capture_output=True)
                    detail = (logs.stderr or logs.stdout or "no container logs were available").strip()
                    raise RuntimeError(f"PostgreSQL runtime did not become ready: {detail[-2000:]}")
                created_base = self.sql_command(session["container"], "postgres", "CREATE DATABASE problem_base;")
                if created_base.returncode:
                    raise RuntimeError(created_base.stderr or created_base.stdout or "could not create SQL base database")
                fixture = f"{problem.get('sql_schema', '')}\n{problem['sql_fixture']}"
                restored = self.sql_command(session["container"], "problem_base", fixture)
                if restored.returncode:
                    raise RuntimeError(restored.stderr or "could not restore SQL fixture")
                permissions = self.sql_command(session["container"], "problem_base", "CREATE ROLE solver LOGIN PASSWORD 'solver'; GRANT CONNECT ON DATABASE problem_base TO solver; GRANT USAGE ON SCHEMA public TO solver; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO solver; GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO solver;")
                if permissions.returncode:
                    raise RuntimeError(permissions.stderr or "could not configure SQL runner permissions")
            except Exception:
                subprocess.run(["docker", "rm", "--force", session["container"]], capture_output=True)
                subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
                raise
            self.sql_sessions[problem["slug"]] = session
            return session

    def execute_sql_case(self, session, source, problem, test):
        database = f"test_{uuid.uuid4().hex}"
        started = time.monotonic()
        output = error = ""
        exit_code = None
        try:
            cloned = self.sql_command(session["container"], "postgres", f"CREATE DATABASE {database} TEMPLATE problem_base;")
            if cloned.returncode:
                raise RuntimeError(cloned.stderr or "could not clone SQL test database")
            if test.get("sql_delta"):
                delta = self.sql_command(session["container"], database, test["sql_delta"])
                if delta.returncode:
                    raise RuntimeError(delta.stderr or "could not apply SQL test delta")
            completed = self.sql_command(session["container"], database, source, user="solver", timeout=problem["time_limit_ms"] / 1000 + 3)
            output, error, exit_code = completed.stdout, completed.stderr, completed.returncode
            status = "passed" if completed.returncode == 0 and normalized(output) == normalized(test["expected_output"]) else "runtime_error" if completed.returncode else "failed"
        except subprocess.TimeoutExpired as caught:
            status, error = "time_limit_exceeded", str(caught)
        except Exception as caught:
            status, error = "runtime_error", str(caught)
        finally:
            self.sql_command(session["container"], "postgres", f"DROP DATABASE IF EXISTS {database};")
        return self.result(test, status, round((time.monotonic() - started) * 1000), output, error, exit_code)

    def execute_sql_test(self, source, problem, image, test, progress=lambda _detail: None):
        if shutil.which("docker") is None:
            raise RuntimeError("Docker is not available")
        self.ensure_image(image, progress)
        session = self.sql_session(problem, image, progress)
        return self.execute_sql_case(session, source, problem, test)

    def execute_sql(self, source, problem, image, progress=lambda _detail: None):
        if shutil.which("docker") is None:
            raise RuntimeError("Docker is not available")
        self.ensure_image(image, progress)
        session = self.sql_session(problem, image, progress)
        results = []
        for test in problem["tests"]:
            results.append(self.execute_sql_case(session, source, problem, test))
        passed = sum(item["status"] == "passed" for item in results)
        statuses = {item["status"] for item in results}
        overall = "accepted" if passed == len(results) else "time_limit_exceeded" if "time_limit_exceeded" in statuses else "runtime_error" if "runtime_error" in statuses else "partial" if passed else "wrong_answer"
        return {"overall_status": overall, "total_test_cases": len(results), "passed_test_cases": passed, "max_runtime_ms": max((item["runtime_ms"] for item in results), default=0), "test_results": results}

    def execute(self, language, source, problem, image, progress=lambda _detail: None):
        extension, compile_cmd, run_cmd = PROFILES[language]
        if shutil.which("docker") is None:
            raise RuntimeError("Docker is not available")
        self.ensure_image(image, progress)
        results = []
        with tempfile.TemporaryDirectory(prefix="chakrikoi-installed-") as directory:
            os.chmod(directory, 0o777)
            path = Path(directory) / f"solution{extension}"
            path.write_text(source)
            os.chmod(path, 0o644)
            if compile_cmd:
                compiled = self.docker(image, directory, compile_cmd, False, "", 20)
                if compiled.returncode:
                    results = [self.result(test, "compile_error", 0, "", compiled.stderr, compiled.returncode) for test in problem["tests"]]
            if not results:
                for test in problem["tests"]:
                    started = time.monotonic()
                    try:
                        completed = self.docker(image, directory, run_cmd, True, test["input"], problem["time_limit_ms"] / 1000 + 2)
                        elapsed = round((time.monotonic() - started) * 1000)
                        status = "passed" if completed.returncode == 0 and normalized(completed.stdout) == normalized(test["expected_output"]) else "runtime_error" if completed.returncode else "failed"
                        results.append(self.result(test, status, elapsed, completed.stdout, completed.stderr, completed.returncode))
                    except subprocess.TimeoutExpired as error:
                        results.append(self.result(test, "time_limit_exceeded", round((time.monotonic() - started) * 1000), "", str(error), None))
        passed = sum(item["status"] == "passed" for item in results)
        statuses = {item["status"] for item in results}
        overall = "accepted" if passed == len(results) else "compile_error" if "compile_error" in statuses else "time_limit_exceeded" if "time_limit_exceeded" in statuses else "runtime_error" if "runtime_error" in statuses else "partial" if passed else "wrong_answer"
        return {"overall_status": overall, "total_test_cases": len(results), "passed_test_cases": passed, "max_runtime_ms": max((item["runtime_ms"] for item in results), default=0), "test_results": results}

    @staticmethod
    def result(test, status, runtime, output, error, exit_code=None):
        return {
            "test_case_id": test["id"], "status": status, "runtime_ms": runtime,
            "input": test["input"][:1048576], "expected_output": test["expected_output"][:1048576],
            "actual_output": output[:1048576], "error_output": error[:1048576], "exit_code": exit_code,
        }

    @staticmethod
    def docker(image, directory, command, readonly, input_data, timeout):
        mount = f"{directory}:/workspace" + (":ro" if readonly else "")
        return subprocess.run(["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,size=256m", "-v", mount, image, *command], input=input_data, text=True, capture_output=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", default="bootstrap.json")
    args = parser.parse_args()
    bootstrap = json.loads(Path(args.bootstrap).read_text())
    service = Service(bootstrap)

    class Handler(BaseHTTPRequestHandler):
        def cors_headers(self):
            origin = self.headers.get("Origin")
            if service.accepts_origin(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")

        def send_json(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data)))
            self.cors_headers()
            self.end_headers(); self.wfile.write(data)

        def do_OPTIONS(self):
            if not service.accepts_origin(self.headers.get("Origin")):
                return self.send_json(403, {"error": "forbidden"})
            self.send_response(204)
            self.cors_headers()
            self.end_headers()

        def do_POST(self):
            if not service.accepts_origin(self.headers.get("Origin")) or self.path not in {"/v1/runs", "/v1/sql-cells"}: return self.send_json(403, {"error": "forbidden"})
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/v1/sql-cells":
                if not isinstance(body.get("problem_slug"), str) or not isinstance(body.get("source_code"), str) or not body["source_code"].strip() or not isinstance(body.get("test_case_id"), int):
                    return self.send_json(400, {"error": "missing SQL cell fields"})
                return self.send_json(202, {"run_id": service.start(body, service.run_sql_cell), "status": "queued"})
            if not all(isinstance(body.get(key), str) and body[key] for key in ("problem_slug", "language", "source_code")): return self.send_json(400, {"error": "missing run fields"})
            if body["language"] == "sql": return self.send_json(400, {"error": "SQL problems run through individual notebook cells"})
            self.send_json(202, {"run_id": service.start(body), "status": "queued"})
        def do_DELETE(self):
            parsed = urlsplit(self.path)
            if not service.accepts_origin(self.headers.get("Origin")) or not parsed.path.startswith("/v1/sql-sessions/"):
                return self.send_json(403, {"error": "forbidden"})
            service.release_sql_session(parsed.path.removeprefix("/v1/sql-sessions/"))
            self.send_json(200, {"status": "released"})
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/v1/health":
                if self.headers.get("Origin") and not service.accepts_origin(self.headers.get("Origin")): return self.send_json(403, {"error": "forbidden"})
                return self.send_json(200, {"status": "ok", "docker_available": bool(shutil.which("docker"))})
            if not parsed.path.startswith("/v1/runs/") or not service.accepts_origin(self.headers.get("Origin")): return self.send_json(403, {"error": "forbidden"})
            status = service.status(parsed.path.removeprefix("/v1/runs/"), int(parse_qs(parsed.query).get("wait", ["0"])[0]))
            self.send_json(200 if status else 404, status or {"error": "not found"})
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(("127.0.0.1", bootstrap["runner_port"]), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
