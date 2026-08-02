#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
test -x "$ROOT/chakrikoi-runner"
test -L "$ROOT/bootstrap.json"
test -L "$ROOT/submit.py"
"$ROOT/chakrikoi-runner" --help >/dev/null
