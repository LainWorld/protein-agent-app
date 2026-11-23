#!/usr/bin/env bash
# Only the test server, with a temporary database and no external LLM calls.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT/backend"
exec "$PROJECT_ROOT/.venv/bin/python" -m uvicorn demo_jobs:app --app-dir tests --host 127.0.0.1 --port 8001
