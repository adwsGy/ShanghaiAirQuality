#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

bootstrap_python="${PYTHON:-}"
while (($#)); do
    case "$1" in
        --python)
            (($# >= 2)) || die '--python requires an interpreter name or path.'
            bootstrap_python="$2"; shift 2 ;;
        -h|--help)
            printf '%s\n' 'Usage: setup.sh [--python python3.12]' 'Install dependencies, build the frontend, and verify the bundled data.'
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

cd -- "$app_root"
find_python
if [[ -z "$app_python" ]]; then
    bootstrap=()
    if [[ -n "$bootstrap_python" ]]; then
        require_command "$bootstrap_python"
        bootstrap=("$bootstrap_python")
    else
        for candidate in python3.12 python3 python; do
            candidate_path="$(command -v "$candidate" || true)"
            [[ -n "$candidate_path" ]] || continue
            # Windows Store aliases are launchers, not installed interpreters.
            [[ "$candidate_path" != */Microsoft/WindowsApps/* ]] || continue
            if "$candidate_path" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' >/dev/null 2>&1; then
                bootstrap=("$candidate_path"); break
            fi
        done
        if ((${#bootstrap[@]} == 0)) && command -v py >/dev/null 2>&1 \
            && py -3.12 -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' >/dev/null 2>&1; then
            bootstrap=(py -3.12)
        fi
        ((${#bootstrap[@]})) || die 'Python 3.12 was not found. Install it, or pass --python with its interpreter path.'
    fi
    "${bootstrap[@]}" scripts/check_runtime.py
    "${bootstrap[@]}" -m venv .venv
else
    "$app_python" scripts/check_runtime.py
fi
require_python
"$app_python" -m pip install --disable-pip-version-check -r requirements-lock.txt
(
    cd -- "$app_root/frontend"
    npm ci
    npm run build
)
"$app_python" -m pipeline.verify
printf '%s\n' 'Ready. Start the backend and frontend, or run scripts/start.sh.'
