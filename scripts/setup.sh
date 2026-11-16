#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

bootstrap_python="${PYTHON:-python3}"
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

require_command npm
cd -- "$app_root"
find_python
if [[ -z "$app_python" ]]; then
    require_command "$bootstrap_python"
    "$bootstrap_python" -m venv .venv
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
