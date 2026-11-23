#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runtime.sh"
cd "$PROJECT_ROOT"
exec pnpm --dir frontend dev
