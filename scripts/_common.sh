#!/usr/bin/env bash
# Shared paths and checks for the Bash entry points.
app_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

die() {
    printf '%s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

find_python() {
    app_python=''
    if [[ -x "$app_root/.venv/bin/python" ]]; then
        app_python="$app_root/.venv/bin/python"
    elif [[ -x "$app_root/.venv/Scripts/python.exe" ]]; then
        app_python="$app_root/.venv/Scripts/python.exe"
    fi
}

require_python() {
    find_python
    [[ -n "$app_python" ]] || die 'Run scripts/setup.sh first.'
}

validate_port() {
    [[ "$1" =~ ^[0-9]{1,5}$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535)) \
        || die "Invalid port: $1 (expected 1-65535)."
}
