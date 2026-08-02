"""Manifest-aware loopback runner used by the installation draft."""

from __future__ import annotations

import argparse, hashlib, json, os, shutil, subprocess, tempfile, threading, time, uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode()) if response.length != 0 else {}


def normalized(value):
    return "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").split("\n")).rstrip()


class Service:
    def __init__(self, bootstrap):
        self.base = bootstrap["backend_url"].rstrip("/")
        self.manifest = request_json("GET", self.base + bootstrap["manifest_path"])
        self.origins = set(self.manifest["allowed_origins"])
        self.runs, self.lock, self.changed = {}, threading.Lock(), None
        self.changed = threading.Condition(self.lock)

    def start(self, data):
        run_id = str(uuid.uuid4())
        with self.changed:
            self.runs[run_id] = {"status": "queued", "detail": ""}
        threading.Thread(target=self.run, args=(run_id, data), daemon=True).start()
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
            slug, language, source, grant = (data[key] for key in ("problem_slug", "language", "source_code", "run_grant"))
            self.set(run_id, "fetching_problem")
            problem = request_json("GET", self.base + f"/v1/local-runs/problems/{slug}", headers={"Authorization": f"Bearer {grant}"})
            if language not in problem["allowed_languages"] or language not in PROFILES:
                raise ValueError("unsupported language")
            self.set(run_id, "running")
            result = self.execute(language, source, problem, self.manifest["images"][language])
            payload = {
                "problem_slug": slug, "language": language, "source_code": source,
                "docker_image": self.manifest["images"][language], "client_version": "installed-draft-0.1",
                **result,
            }
            request_json("POST", self.base + "/v1/local-runs/complete", payload, {"Authorization": f"Bearer {grant}"})
            self.set(run_id, "completed", result["overall_status"], result)
        except Exception as error:
            self.set(run_id, "failed", str(error))

    def execute(self, language, source, problem, image):
        extension, compile_cmd, run_cmd = PROFILES[language]
        if shutil.which("docker") is None:
            raise RuntimeError("Docker is not available")
        if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode:
            subprocess.run(["docker", "pull", image], check=True)
        results = []
        with tempfile.TemporaryDirectory(prefix="chakrikoi-installed-") as directory:
            os.chmod(directory, 0o777)
            path = Path(directory) / f"solution{extension}"
            path.write_text(source)
            os.chmod(path, 0o644)
            if compile_cmd:
                compiled = self.docker(image, directory, compile_cmd, False, "", 20)
                if compiled.returncode:
                    results = [self.result(test, "compile_error", 0, "", compiled.stderr) for test in problem["tests"]]
            if not results:
                for test in problem["tests"]:
                    started = time.monotonic()
                    try:
                        completed = self.docker(image, directory, run_cmd, True, test["input"], problem["time_limit_ms"] / 1000 + 2)
                        elapsed = round((time.monotonic() - started) * 1000)
                        status = "passed" if completed.returncode == 0 and normalized(completed.stdout) == normalized(test["expected_output"]) else "runtime_error" if completed.returncode else "failed"
                        results.append(self.result(test, status, elapsed, completed.stdout, completed.stderr))
                    except subprocess.TimeoutExpired as error:
                        results.append(self.result(test, "time_limit_exceeded", round((time.monotonic() - started) * 1000), "", str(error)))
        passed = sum(item["status"] == "passed" for item in results)
        statuses = {item["status"] for item in results}
        overall = "accepted" if passed == len(results) else "compile_error" if "compile_error" in statuses else "time_limit_exceeded" if "time_limit_exceeded" in statuses else "runtime_error" if "runtime_error" in statuses else "partial" if passed else "wrong_answer"
        return {"overall_status": overall, "total_test_cases": len(results), "passed_test_cases": passed, "max_runtime_ms": max((item["runtime_ms"] for item in results), default=0), "test_results": results}

    @staticmethod
    def result(test, status, runtime, output, error):
        return {"test_case_id": test["id"], "status": status, "runtime_ms": runtime, "actual_output": output[:1048576], "error_output": error[:1048576]}

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
        def send_json(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data)))
            if self.headers.get("Origin") in service.origins: self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.end_headers(); self.wfile.write(data)
        def do_POST(self):
            if self.headers.get("Origin") not in service.origins or self.path != "/v1/runs": return self.send_json(403, {"error": "forbidden"})
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if not all(isinstance(body.get(key), str) and body[key] for key in ("problem_slug", "language", "source_code", "run_grant")): return self.send_json(400, {"error": "missing run fields"})
            self.send_json(202, {"run_id": service.start(body), "status": "queued"})
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/v1/health": return self.send_json(200, {"status": "ok", "docker_available": bool(shutil.which("docker"))})
            if not parsed.path.startswith("/v1/runs/") or self.headers.get("Origin") not in service.origins: return self.send_json(403, {"error": "forbidden"})
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
