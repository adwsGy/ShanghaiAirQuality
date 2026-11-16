#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

port=8000
reload=false
while (($#)); do
    case "$1" in
        --port)
            (($# >= 2)) || die '--port requires a value.'
            validate_port "$2"; port="$2"; shift 2 ;;
        --reload) reload=true; shift ;;
        -h|--help)
            printf '%s\n' 'Usage: start-backend.sh [--port 8000] [--reload]'
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

require_python
cd -- "$app_root"
args=(-m uvicorn api.app:app --host 127.0.0.1 --port "$port")
if [[ "$reload" == true ]]; then args+=(--reload); fi
exec "$app_python" "${args[@]}"
