#!/usr/bin/env bash
# Deploy plugin code to pc137, with a timestamped backup before every
# file overwrite.
# Usage: ./scripts/deploy_plugin.sh <houdini|hmcp|nuke|all>
# Requires: ssh pc137 alias configured, VPN up.
#
# "houdini" deploys the OLD plugin (port 9876, untouched, still in
# production use). "hmcp" deploys the NEW plugin package under rewrite
# (houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md; port 9878, separate process,
# separate sandbox-only write boundary). "all" does not include hmcp --
# it's opted into explicitly until Phase 3 passes and the old plugin is
# retired.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"

HOUDINI_LOCAL_DIR="$REPO_ROOT/houdini/plugin"
HOUDINI_REMOTE_DIR='C:/Users/Admin/Documents/houdini21.0/scripts/python/houdinimcp'
HOUDINI_FILES=("server.py" "HoudiniMCPRender.py")

HMCP_LOCAL_DIR="$REPO_ROOT/houdini/plugin/hmcp"
HMCP_REMOTE_DIR='C:/Users/Admin/Documents/houdini21.0/scripts/python/hmcp'
COMMANDS_SPEC_LOCAL="$REPO_ROOT/houdini/commands_spec.py"

NUKE_LOCAL_DIR="$REPO_ROOT/nuke/plugin"
NUKE_REMOTE_DIR='C:/Users/Admin/.nuke'
NUKE_FILES=("nuke_mcp_plugin.py")

# little_helpers/ is its own repo (github.com/sandalya/little_helpers) as of
# the Phase 0 restructuring -- checked out as a sibling directory next to
# this repo, not inside it.
LITTLE_HELPERS_REPO_DIR="$(cd "$REPO_ROOT/.." && pwd)/little_helpers"
NUKE_LITTLE_HELPERS_LOCAL_DIR="$LITTLE_HELPERS_REPO_DIR"
NUKE_LITTLE_HELPERS_REMOTE_DIR='C:/Users/Admin/.nuke/little_helpers'

NUKE_LITTLE_HELPERS_SPLIT_LAYERS_LOCAL_DIR="$LITTLE_HELPERS_REPO_DIR/split_layers"
NUKE_LITTLE_HELPERS_SPLIT_LAYERS_REMOTE_DIR='C:/Users/Admin/.nuke/little_helpers/split_layers'

NUKE_LITTLE_HELPERS_VERITER_LOCAL_DIR="$LITTLE_HELPERS_REPO_DIR/veriter"
NUKE_LITTLE_HELPERS_VERITER_REMOTE_DIR='C:/Users/Admin/.nuke/little_helpers/veriter'

TARGET="${1:-}"
if [[ -z "$TARGET" || ! "$TARGET" =~ ^(houdini|hmcp|nuke|all)$ ]]; then
  echo "Usage: $0 <houdini|hmcp|nuke|all>" >&2
  exit 1
fi

# deploy_one <local_dir> <remote_dir> <file...>
deploy_one() {
  local local_dir="$1" remote_dir="$2"
  shift 2
  local f

  for f in "$@"; do
    if [ ! -f "$local_dir/$f" ]; then
      echo "ERROR: local plugin file not found at $local_dir/$f" >&2
      exit 1
    fi
  done

  for f in "$@"; do
    local backup_name="${f}.bak_${STAMP}"
    echo "==> Backup $f -> $backup_name"
    ssh pc137 "powershell -Command \"Copy-Item '$remote_dir/$f' '$remote_dir/$backup_name'\""
    echo "==> SCP $f -> pc137"
    scp "$local_dir/$f" "pc137:$remote_dir/$f"
  done
}

# deploy_dir <local_dir> <remote_dir> [skip_backup] -- backs up the whole
# remote folder (if it exists) before overwriting, then scp's every local
# *.py file in. Pass any non-empty 3rd arg to skip the backup -- used for
# a subpackage dir nested under a parent dir this was already called on,
# so its backup doesn't happen twice.
deploy_dir() {
  local local_dir="$1" remote_dir="$2" skip_backup="${3:-}"
  local backup_dir="${remote_dir}_bak_${STAMP}"

  if [[ -z "$skip_backup" ]]; then
    echo "==> Backup dir $remote_dir -> $backup_dir (if it exists)"
    ssh pc137 "powershell -Command \"if (Test-Path '$remote_dir') { Copy-Item -Recurse -Force '$remote_dir' '$backup_dir' }\""
  fi
  echo "==> Ensure $remote_dir exists"
  ssh pc137 "powershell -Command \"New-Item -ItemType Directory -Force -Path '$remote_dir' | Out-Null\""
  echo "==> SCP $local_dir/*.py -> pc137:$remote_dir"
  scp "$local_dir"/*.py "pc137:$remote_dir/"
}

echo "==> Reachability check"
ssh -o BatchMode=yes -o ConnectTimeout=5 pc137 'echo ok' >/dev/null || {
  echo "ERROR: cannot reach pc137. VPN up? ssh config correct?" >&2
  exit 1
}

if [[ "$TARGET" == "houdini" || "$TARGET" == "all" ]]; then
  echo "=== Houdini plugin ==="
  deploy_one "$HOUDINI_LOCAL_DIR" "$HOUDINI_REMOTE_DIR" "${HOUDINI_FILES[@]}"
fi

if [[ "$TARGET" == "hmcp" ]]; then
  echo "=== hmcp plugin (new, port 9878, Phase 1 read-only) ==="
  deploy_dir "$HMCP_LOCAL_DIR" "$HMCP_REMOTE_DIR"

  if [ ! -f "$COMMANDS_SPEC_LOCAL" ]; then
    echo "ERROR: commands_spec.py not found at $COMMANDS_SPEC_LOCAL" >&2
    exit 1
  fi
  echo "==> SCP commands_spec.py -> pc137:$HMCP_REMOTE_DIR (shared source of truth, deployed alongside the package)"
  scp "$COMMANDS_SPEC_LOCAL" "pc137:$HMCP_REMOTE_DIR/commands_spec.py"

  HYTHON='C:\Program Files\Side Effects Software\Houdini 21.0.596\bin\hython.exe'
  echo "==> hython -m py_compile every file in the deployed hmcp package"
  for f in "$HMCP_LOCAL_DIR"/*.py; do
    fname="$(basename "$f")"
    echo "    - $fname"
    ssh pc137 "powershell -Command \"& '$HYTHON' -m py_compile '$HMCP_REMOTE_DIR/$fname'\""
  done
  ssh pc137 "powershell -Command \"& '$HYTHON' -m py_compile '$HMCP_REMOTE_DIR/commands_spec.py'\""

  echo "==> check_contract.py (only meaningful once the plugin is running live; a connection failure here just means it isn't started yet)"
  "$REPO_ROOT/.venv/Scripts/python.exe" "$REPO_ROOT/scripts/check_contract.py" || echo "    (non-fatal at deploy time -- see message above)"
fi

if [[ "$TARGET" == "nuke" || "$TARGET" == "all" ]]; then
  echo "=== Nuke plugin (infra) ==="
  deploy_one "$NUKE_LOCAL_DIR" "$NUKE_REMOTE_DIR" "${NUKE_FILES[@]}"

  if [ ! -d "$LITTLE_HELPERS_REPO_DIR" ]; then
    echo "ERROR: little_helpers/ sibling checkout not found at $LITTLE_HELPERS_REPO_DIR" >&2
    echo "  It's a separate repo now -- clone it next to this one:" >&2
    echo "    git clone https://github.com/sandalya/little_helpers.git \"$LITTLE_HELPERS_REPO_DIR\"" >&2
    exit 1
  fi

  echo "=== little_helpers (artist tools) ==="
  deploy_dir "$NUKE_LITTLE_HELPERS_LOCAL_DIR" "$NUKE_LITTLE_HELPERS_REMOTE_DIR"
  echo "=== little_helpers/split_layers ==="
  deploy_dir "$NUKE_LITTLE_HELPERS_SPLIT_LAYERS_LOCAL_DIR" "$NUKE_LITTLE_HELPERS_SPLIT_LAYERS_REMOTE_DIR" skip_backup
  echo "=== little_helpers/veriter ==="
  deploy_dir "$NUKE_LITTLE_HELPERS_VERITER_LOCAL_DIR" "$NUKE_LITTLE_HELPERS_VERITER_REMOTE_DIR" skip_backup
  echo "==> Clean stale __pycache__ under little_helpers (flat-import-era .pyc can shadow the new subpackage)"
  ssh pc137 "powershell -Command \"Get-ChildItem -Path '$NUKE_LITTLE_HELPERS_REMOTE_DIR' -Recurse -Filter '__pycache__' -Directory | Remove-Item -Recurse -Force\""
fi

echo "==> Done."
echo

if [[ "$TARGET" == "houdini" || "$TARGET" == "all" ]]; then
  echo "Next steps for Houdini (RDP):"
  echo "  1. Click the 'Stop MCP' shelf button (or run houdinimcp.stop_server() in Python Shell)"
  echo "  2. Close the Houdini instance that was serving MCP"
  echo "  3. Reopen Houdini, load your scene, in Python Shell run:"
  echo "       import houdinimcp"
  echo "       houdinimcp.start_server(host='0.0.0.0')"
  echo
fi

if [[ "$TARGET" == "hmcp" ]]; then
  echo "Next steps for hmcp (RDP, does not affect the old plugin on 9876):"
  echo "  In Houdini's Python Shell, with a scene open:"
  echo "       import hmcp"
  echo "       hmcp.start_server()"
  echo "  Then re-run: ./scripts/check_contract.py to confirm the live"
  echo "  plugin agrees with houdini/commands_spec.py."
  echo
fi

if [[ "$TARGET" == "nuke" || "$TARGET" == "all" ]]; then
  echo "Next steps for Nuke (RDP):"
  echo "  Safest: restart Nuke entirely -- menu.py re-imports nuke_mcp_plugin"
  echo "  and calls start_server() fresh, so the new DISPATCH is guaranteed"
  echo "  to be live."
  echo "  Faster (less certain): in the Script Editor, run"
  echo "       import importlib, nuke_mcp_plugin"
  echo "       importlib.reload(nuke_mcp_plugin)"
  echo "  This updates the module in place, but the listener thread was"
  echo "  already started against the old module -- verify with nuke_ping"
  echo "  and a call to the new command before trusting it."
  echo
  echo "  If menu.py doesn't call little_helpers.register_menu() yet, add"
  echo "  (typed by hand -- clipboard paste doesn't work over RDP to pc137):"
  echo "       import little_helpers"
  echo "       little_helpers.register_menu()"
  echo "  (the existing 'import nuke_mcp_plugin; nuke_mcp_plugin.register_menu()'"
  echo "  lines stay -- the MCP menu entry still comes from there)."
  echo
fi

echo "  Then restart Claude Desktop locally if bridge tools changed."
