#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runtime.sh"
cd "$PROJECT_ROOT"
if [[ ! -x .venv/bin/python ]]; then
  "$PROJECT_PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r backend/requirements-dev.lock
pnpm --dir frontend install --frozen-lockfile
echo '依赖安装完成。在两个终端分别运行 bash scripts/dev-backend.sh 和 bash scripts/dev-frontend.sh。'
