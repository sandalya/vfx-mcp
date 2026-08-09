# CLAUDE.md — Nuke

Nuke-specific rules. Shared safety doctrine is in the repo-root `CLAUDE.md`.

- Plugin changes go only through `plugin/nuke_mcp_plugin.py` →
  `../scripts/deploy_plugin.sh nuke` (it backs up before every deploy) —
  never scp by hand
- `little_helpers/` (incl. `little_helpers/split_layers/`) is a separate repo
  (`github.com/sandalya/little_helpers`), checked out as a sibling directory
  next to this repo (`../../little_helpers`) — `deploy_plugin.sh nuke` reads
  it from there. Edit it in that checkout, not here.

## Reference docs

- `little_helpers/docs/NUKE_COMP_LAYER_ASSEMBLY.md` (in the sibling repo) —
  Sashok's recurring Nuke comp pattern: each layer branch
  (fg/bg/floorVolume/atmo/...) assembled from 4 Read nodes
  (lights/beauty/tech/crypto product passes), merged via Copy nodes,
  per-object mattes off a Cryptomatte/Dot-spine chain. Read this before
  touching any comp-layer or Read-node tooling.
