# CLAUDE.md — Houdini

Houdini-specific rules. Shared safety doctrine is in the repo-root `CLAUDE.md`.

- Never touch production Houdini scenes — sandbox only: `C:/houdini_mcp_sandbox/`
- Never start/stop Houdini yourself — the user does that manually
- Plugin changes go only through `plugin/server.py` → `../scripts/deploy_plugin.sh houdini`
  (it backs up before every deploy) — never scp by hand
- Syntax-check on pc137 after every deploy:
  `& "C:\Program Files\Side Effects Software\Houdini 21.0.596\bin\hython.exe" -m py_compile <path>`
  (both 21.0.596 and 21.0.729 are installed there; the build that actually
  **runs** is 21.0.729 — see `docs/HMCP_HOUDINI_NOTES.md`)

## Reference docs — read the one that matches what you're doing

- `docs/HMCP_DESIGN.md` — **read before touching anything under
  `plugin/hmcp/`.** Doctrine, safety model, the hard rules for editing the
  package, and the decision log (what's settled, what's permanently out)
- `docs/HMCP_HOUDINI_NOTES.md` — measured HOM API facts and failure modes:
  the camera rotation convention (HOM's docs are wrong), renderer parm
  names, `executebackground` behaviour, plugin-reload gotchas. Check here
  before probing something that looks already-answered — and write new
  probe answers back into it
- `docs/HMCP_LOCAL_TIMEOUT_TRIAGE.md` — why the poll pump is an event-loop
  callback and not a `QTimer`. Only matters if you touch `server.py`'s pump
- `docs/SCENE_ANALYSIS.md` — Houdini `/stage` lighting scene breakdown
  (lighting artist's node topology, render passes, light rig). Lighting
  work only; unrelated to `hmcp`
- `docs/plans/` — work not yet built. A non-empty `plans/` means open work.
  Nothing in there describes current state
