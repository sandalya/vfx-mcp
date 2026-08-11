#!/usr/bin/env bash
# Thin wrapper around check_contract.py pointed at the local Houdini
# (mode 2 -- no VPN). Requires local Houdini to already have
# `import hmcp; hmcp.start_server()` called.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HMCP_HOST=127.0.0.1 "$REPO_ROOT/.venv/Scripts/python.exe" "$REPO_ROOT/scripts/check_contract.py"
