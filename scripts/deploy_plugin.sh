#!/usr/bin/env bash
# Deploy plugin/*.py to pc137 with timestamped backups.
# Usage: ./scripts/deploy_plugin.sh
# Requires: ssh pc137 alias configured, VPN up.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="$REPO_ROOT/plugin"
REMOTE_DIR='C:/Users/Admin/Documents/houdini21.0/scripts/python/houdinimcp'
STAMP="$(date +%Y%m%d_%H%M%S)"

FILES=("server.py" "HoudiniMCPRender.py")

# Sanity: every file must exist locally before we start
for f in "${FILES[@]}"; do
  if [ ! -f "$LOCAL_DIR/$f" ]; then
    echo "ERROR: local plugin file not found at $LOCAL_DIR/$f" >&2
    exit 1
  fi
done

echo "==> Reachability check"
ssh -o BatchMode=yes -o ConnectTimeout=5 pc137 'echo ok' >/dev/null || {
  echo "ERROR: cannot reach pc137. VPN up? ssh config correct?" >&2
  exit 1
}

for f in "${FILES[@]}"; do
  backup_name="${f}.bak_${STAMP}"
  echo "==> Backup $f -> $backup_name"
  ssh pc137 "powershell -Command \"Copy-Item '$REMOTE_DIR/$f' '$REMOTE_DIR/$backup_name'\""
  echo "==> SCP $f -> pc137"
  scp "$LOCAL_DIR/$f" "pc137:$REMOTE_DIR/$f"
done

echo "==> Done."
echo
echo "Next steps on pc137 (RDP):"
echo "  1. Click the 'Stop MCP' shelf button (or run houdinimcp.stop_server() in Python Shell)"
echo "  2. Close the Houdini instance that was serving MCP"
echo "  3. Reopen Houdini, load your scene, in Python Shell run:"
echo "       import houdinimcp"
echo "       houdinimcp.start_server(host='0.0.0.0')"
echo
echo "  Then restart Claude Desktop locally if bridge tools changed (this run touched plugin only)."
