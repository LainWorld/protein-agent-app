#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runtime.sh"
cd "$PROJECT_ROOT/backend"
"$PROJECT_ROOT/.venv/bin/python" -m pytest -q
cd "$PROJECT_ROOT"
pnpm --dir frontend build
