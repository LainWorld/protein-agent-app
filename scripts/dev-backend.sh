#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  echo '请先执行 bash scripts/setup.sh。' >&2
  exit 1
fi
cd "$PROJECT_ROOT/backend"
# One backend process, bound to loopback. Restart manually after backend edits.
if [[ "${1:-}" == "--colab" ]]; then
  exec "$PROJECT_ROOT/.venv/bin/python" -m uvicorn app.colab_app:create_colab_app --factory --host 127.0.0.1 --port 8000
fi
exec "$PROJECT_ROOT/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
