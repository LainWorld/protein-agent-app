#!/usr/bin/env bash
# Source from the other scripts. Use installed tools, with a Codex-local fallback.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_RUNTIME_DIR="${CODEX_RUNTIME_DIR:-$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies}"

if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) === 24 ? 0 : 1)' 2>/dev/null; then
  if [[ -x "$TASK_RUNTIME_DIR/node/bin/node" ]]; then
    export PATH="$TASK_RUNTIME_DIR/node/bin:$PATH"
  else
    echo '需要 Node.js 24.x。请安装后重开终端。' >&2
    return 1
  fi
fi
if ! command -v pnpm >/dev/null 2>&1; then
  if [[ -x "$TASK_RUNTIME_DIR/bin/fallback/pnpm" ]]; then
    export PATH="$TASK_RUNTIME_DIR/bin/fallback:$PATH"
  else
    echo '需要 pnpm 11.25.0。安装 Node 后执行 npm install -g pnpm@11.25.0。' >&2
    return 1
  fi
fi

if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  PROJECT_PYTHON="$(command -v python3)"
elif [[ -x "$TASK_RUNTIME_DIR/python/bin/python3" ]]; then
  PROJECT_PYTHON="$TASK_RUNTIME_DIR/python/bin/python3"
else
  echo '需要 Python 3.11+（已验证 3.12.14）。系统 Python 3.9 不适用。' >&2
  return 1
fi
