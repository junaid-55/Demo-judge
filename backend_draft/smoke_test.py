"""Exercise the installed-runner backend API against a running container."""

from __future__ import annotations

import hashlib
import json
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:38123"
SOURCE = "#include <iostream>\nint main() { long long a, b; std::cin >> a >> b; std::cout << a + b << '\\n'; }\n"


def call(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> dict:
    request = Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    with urlopen(request) as response:
        return json.loads(response.read().decode())


manifest = call("GET", "/v1/runner/manifest")
grant = call("POST", "/v1/local-runs/grants", {
    "problem_slug": "sum-two-integers",
    "language": "cpp",
    "source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
}, {"X-Demo-User-Id": "smoke-test-user"})["run_grant"]
problem = call("GET", "/v1/local-runs/problems/sum-two-integers", headers={"Authorization": f"Bearer {grant}"})
completion = call("POST", "/v1/local-runs/complete", {
    "problem_slug": problem["slug"],
    "language": "cpp",
    "source_code": SOURCE,
    "docker_image": "gcc:14",
    "client_version": "smoke-test",
    "overall_status": "accepted",
    "total_test_cases": len(problem["tests"]),
    "passed_test_cases": len(problem["tests"]),
    "max_runtime_ms": 1,
    "test_results": [{
        "test_case_id": test["id"], "status": "passed", "runtime_ms": 1,
        "actual_output": test["expected_output"], "error_output": "",
    } for test in problem["tests"]],
}, {"Authorization": f"Bearer {grant}"})

print(json.dumps({
    "manifest_version": manifest["version"],
    "test_count": len(problem["tests"]),
    "submission_id": completion["submission_id"],
    "idempotent": completion["idempotent"],
}, indent=2))
