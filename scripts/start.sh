#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

port=8000
while (($#)); do
    case "$1" in
        --port)
            (($# >= 2)) || die '--port requires a value.'
            validate_port "$2"; port="$2"; shift 2 ;;
        -h|--help)
            printf '%s\n' 'Usage: start.sh [--port 8000]' 'Serve the built frontend and API from one backend process.'
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

[[ -f "$app_root/frontend/dist/index.html" ]] || die 'Run scripts/setup.sh or build the frontend first.'
exec bash "$app_root/scripts/start-backend.sh" --port "$port"
