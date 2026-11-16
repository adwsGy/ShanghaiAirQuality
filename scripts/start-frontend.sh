#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

port=5173
api_port=8000
while (($#)); do
    case "$1" in
        --port|--api-port)
            (($# >= 2)) || die "$1 requires a value."
            validate_port "$2"
            if [[ "$1" == --port ]]; then port="$2"; else api_port="$2"; fi
            shift 2 ;;
        -h|--help)
            printf '%s\n' 'Usage: start-frontend.sh [--port 5173] [--api-port 8000]'
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

require_command npm
cd -- "$app_root/frontend"
export AIR_API_TARGET="http://127.0.0.1:$api_port"
exec npm run dev -- --port "$port"
