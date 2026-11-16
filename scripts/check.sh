#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

if (($#)); then
    case "$1" in
        -h|--help) printf '%s\n' 'Usage: check.sh' 'Verify data, frontend tests/build, and backend tests.'; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
fi

require_python
cd -- "$app_root"
"$app_python" scripts/check_runtime.py
"$app_python" -m pipeline.verify
(
    cd -- "$app_root/frontend"
    npm test
    npm run build
)
# Build before the HTTP tests so static-asset checks also run on a fresh checkout.
"$app_python" -m unittest discover -s tests -q
