#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runtime.sh"
cd "$PROJECT_ROOT"
export BACKEND_PROXY_TARGET=http://127.0.0.1:8001
exec pnpm --dir frontend exec vite --mode faults --host 127.0.0.1 --port 5174 --strictPort
