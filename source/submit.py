"""Submit a source file to the local runner during development."""

from __future__ import annotations

import argparse, json
from pathlib import Path
from urllib.request import Request, urlopen


def call(method, url, body=None, headers=None):
    request = Request(
        url,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    with urlopen(request) as response:
        return json.loads(response.read().decode())


parser = argparse.ArgumentParser()
parser.add_argument("--runner", default="http://127.0.0.1:37123")
parser.add_argument("--problem", default="count-vowels")
parser.add_argument("--language", default="cpp")
parser.add_argument(
    "--file",
    type=Path,
    default=Path(__file__).resolve().parent / "solutions/count_vowels.cpp",
)
args = parser.parse_args()
source = args.file.read_text()
run = call(
    "POST",
    args.runner + "/v1/runs",
    {
        "problem_slug": args.problem,
        "language": args.language,
        "source_code": source,
    },
    {"Origin": "http://localhost:3000"},
)
while True:
    state = call(
        "GET",
        args.runner + f"/v1/runs/{run['run_id']}?wait=30",
        headers={"Origin": "http://localhost:3000"},
    )
    if state["status"] in {"completed", "failed"}:
        if state["status"] == "failed":
            print(f"Runner failed: {state['detail']}")
            break
        result = state["result"]
        print(f"Verdict: {result['overall_status']}")
        print(f"Passed: {result['passed_test_cases']}/{result['total_test_cases']}")
        print(f"Maximum runtime: {result['max_runtime_ms']} ms")
        print("\nTest results:")
        for test in result["test_results"]:
            print(f"  Test {test['test_case_id']}: {test['status']} ({test['runtime_ms']} ms)")
            if test["actual_output"] and test["status"] != "passed":
                print(f"    Output: {test['actual_output']!r}")
            if test["error_output"]:
                print(f"    Error: {test['error_output'].strip()}")
        break
