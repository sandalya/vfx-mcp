# CLAUDE.md — Houdini

Houdini-specific rules. Shared safety doctrine is in the repo-root `CLAUDE.md`.

- Never touch production Houdini scenes — sandbox only: `C:/houdini_mcp_sandbox/`
- Never start/stop Houdini yourself — the user does that manually
- Plugin changes go only through `plugin/server.py` → `../scripts/deploy_plugin.sh houdini`
  (it backs up before every deploy) — never scp by hand
- Syntax-check on pc137 after every deploy:
  `& "C:\Program Files\Side Effects Software\Houdini 21.0.596\bin\hython.exe" -m py_compile <path>`

## Reference docs

- `docs/SCENE_ANALYSIS.md` — Houdini `/stage` lighting scene breakdown
  (lighting artist's node topology, render passes, light rig)
- `docs/HOUDINI_MCP_REWRITE_PLAN.md` — execution plan for the new
  read/write plugin layer (port 9878, sandbox-only write boundary);
  read this before touching anything under `houdini/plugin/hmcp/`
