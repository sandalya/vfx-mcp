#!/usr/bin/env bash
# Deploy plugin code to pc137, with a timestamped backup before every
# file overwrite.
# Usage: ./scripts/deploy_plugin.sh <houdini|nuke|all>
# Requires: ssh pc137 alias configured, VPN up.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"

HOUDINI_LOCAL_DIR="$REPO_ROOT/plugin"
HOUDINI_REMOTE_DIR='C:/Users/Admin/Documents/houdini21.0/scripts/python/houdinimcp'
HOUDINI_FILES=("server.py" "HoudiniMCPRender.py")

NUKE_LOCAL_DIR="$REPO_ROOT"
NUKE_REMOTE_DIR='C:/Users/Admin/.nuke'
NUKE_FILES=("nuke_mcp_plugin.py")

NUKE_SPLIT_LAYERS_LOCAL_DIR="$REPO_ROOT/nuke/split_layers"
NUKE_SPLIT_LAYERS_REMOTE_DIR='C:/Users/Admin/.nuke/split_layers'

TARGET="${1:-}"
if [[ -z "$TARGET" || ! "$TARGET" =~ ^(houdini|nuke|all)$ ]]; then
  echo "Usage: $0 <houdini|nuke|all>" >&2
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

# deploy_dir <local_dir> <remote_dir> -- backs up the whole remote folder
# (if it exists) before overwriting, then scp's every local *.py file in.
deploy_dir() {
  local local_dir="$1" remote_dir="$2"
  local backup_dir="${remote_dir}_bak_${STAMP}"

  echo "==> Backup dir $remote_dir -> $backup_dir (if it exists)"
  ssh pc137 "powershell -Command \"if (Test-Path '$remote_dir') { Copy-Item -Recurse -Force '$remote_dir' '$backup_dir' }\""
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

if [[ "$TARGET" == "nuke" || "$TARGET" == "all" ]]; then
  echo "=== Nuke plugin ==="
  deploy_one "$NUKE_LOCAL_DIR" "$NUKE_REMOTE_DIR" "${NUKE_FILES[@]}"
  echo "=== Nuke split_layers helper ==="
  deploy_dir "$NUKE_SPLIT_LAYERS_LOCAL_DIR" "$NUKE_SPLIT_LAYERS_REMOTE_DIR"
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
fi

echo "  Then restart Claude Desktop locally if bridge tools changed."
