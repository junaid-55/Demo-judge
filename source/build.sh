#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/source/.build-venv"
OUTPUT="$ROOT/user_agent"

if [[ ! -x "$VENV/bin/python" ]]; then
  python -m venv "$VENV"
fi
if ! "$VENV/bin/python" -m PyInstaller --version >/dev/null 2>&1; then
  "$VENV/bin/pip" install 'pyinstaller>=6.15'
fi

mkdir -p "$OUTPUT"
"$VENV/bin/python" -m PyInstaller \
  --onefile \
  --name chakrikoi-runner \
  --distpath "$OUTPUT" \
  --workpath /tmp/chakrikoi-runner-build \
  --specpath /tmp/chakrikoi-runner-spec \
  "$ROOT/source/runner/chakrikoi_installed_runner/runner.py"

ln -sfn ../source/bootstrap.json "$OUTPUT/bootstrap.json"
ln -sfn ../source/submit.py "$OUTPUT/submit.py"
ln -sfn ../source/systemd/chakrikoi-runner.service "$OUTPUT/chakrikoi-runner.service"
ln -sfn ../source/solutions "$OUTPUT/solutions"
ln -sfn ../source/tests "$OUTPUT/tests"
