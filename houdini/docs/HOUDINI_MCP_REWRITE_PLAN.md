# Houdini MCP Rewrite — Execution Plan

Status: approved, not started.
Audience: an implementing agent with no memory of the planning conversation.
Read this whole document before touching anything.

---

## 1. Why this rewrite exists

The Houdini MCP bridge works as plumbing but has never successfully built a
setup. A code audit found the cause is missing capability, not missing model
knowledge:

| Problem | Evidence |
|---|---|
| Nodes cannot be wired at all | `houdini_mcp_server.py:354` sends a `connect_nodes` command; the plugin dispatcher (`plugin/server.py:185-199`) has no such handler and the file contains no `setInput` call anywhere |
| No geometry feedback | Nothing returns point/prim counts, attributes, or bbox — the agent builds a SOP graph and cannot see what came out |
| No error feedback | No handler exposes node errors, warnings, or cook state |
| No way to discover parameters | Only existing nodes can be read; there is no way to ask "what parameters does a `mountain` node have" |
| Mistakes are permanent | `delete_node` is unrouted, so a wrong node stays in the scene forever |
| Parameter whitelist is bypassable | `create_node` (`plugin/server.py:290-294`) sets any parm via its `parameters` dict without calling `SAFE_PARMS` |
| Live arbitrary-URL-to-disk path | `import_opus_url` is routed (`plugin/server.py:192`) and does `requests.get` → `os.makedirs` → write → unzip → `os.remove` |
| Render path is caller-supplied and unvalidated | `handle_render_single_view(render_path=...)` (`plugin/server.py:1083+`) writes wherever asked and silently overwrites |
| The agent with the good iteration loop has no access | The `houdini` MCP server is registered only in Claude Desktop; Claude Code has `mcp__houdini__*` permissions in `.claude/settings.local.json` but no server entry |

The machine (pc137) sits on a shared studio network with other artists' data on
mounted shares. The owner's hard requirement: the plugin must not be able to
delete or overwrite anything outside a single sandbox directory. The guarantee
chosen is **absence of capability, not validation of capability** — see §4.

## 2. Target domain (changed from the original project)

The agent is being built for **SOP-level procedural geometry and VEX**, later
DOPs, HDAs and Copernicus. **Not lighting, not `/stage`, not Solaris.**

Rationale: generic SOP/VEX knowledge is common, stable across versions and
well represented in model weights, and the result is visually self-verifying in
an OpenGL viewport. The studio's lighting stack is custom `pl_*` HDAs that no
model has seen, so lighting work would depend entirely on copying from an
existing scene.

Phase 1 goal: **Claude Code, unattended, builds a working procedural-rock SOP
graph in a sandbox scene and verifies it itself.**

## 3. Decisions already made — do not relitigate

| Topic | Decision |
|---|---|
| Who builds | Claude Code gets its own MCP server. Claude Desktop keeps the existing one for scene inspection. |
| Reading | Unrestricted, always, in any scene. Reading cannot damage anything. |
| Write boundary | Write commands work **only** when the open `.hip` lives under `C:/houdini_mcp_sandbox/`. Otherwise every write refuses. Single exception: `save_scene_as` from a never-saved scene, to bootstrap into the sandbox. |
| Rollback | Every write block wrapped in `hou.undos.group()`; plus a per-session registry of created nodes. |
| Node deletion | Only nodes the agent created in the current session. |
| Filesystem paths | The agent **never** passes a path to any tool. All paths are computed by the plugin from constants. |
| Filesystem deletion | No delete capability exists in the new package at all. |
| File-path parameters | Input paths (`file`, `filepath`) settable; output paths (`outputimage`, `sopoutput`, any ROP output) never settable. |
| Code in parameters | VEX (`snippet`, `vexpression`) allowed. Python SOP, callback scripts, Python expressions — never. |
| Eyes | OpenGL viewport snapshot only. No Karma/Arnold/Mantra rendering. |
| Migration | New plugin package on a new port, alongside the untouched old one. Old one is retired only after Phase 3 passes. |
| Recipes / eval harness | Deferred until there is something worth recording. |

## 4. The safety model, stated plainly

The plugin runs inside the owner's Houdini process under the owner's account. At
OS level it can reach everything the owner can reach, including studio shares.
There is no sandbox, no jail, no privilege boundary. **The only barrier is which
functions exist in the code.**

Therefore the design rule is: *do not write the dangerous capability at all*,
rather than write it and guard it.

Concretely, in the new package:

- No `import os`, `import shutil`, `import requests`, `import subprocess`,
  `import zipfile`. No `os.remove`, `unlink`, `rmtree`, `open(..., "w")`.
- Path handling uses plain string operations and `hou.hipFile.path()`. The
  render/snapshot directory must **pre-exist** (the owner creates it once); the
  plugin never creates directories.
- Snapshot filenames are `mcp_<YYYYmmdd_HHMMSS>.jpg` under a constant directory,
  so overwriting an existing file is impossible by construction.
- Scene saving is `hou.hipFile.saveAs(<constant dir> + "mcp_<ts>.hip")` only.
  Never `hou.hipFile.save()`, which would overwrite the open file.

A blacklist over Python source text (rejecting `import os` etc.) is **not**
acceptable as a control — it is trivially bypassed via `__import__`, `getattr`,
`hou.hscript()` — which is why Python-bearing parameters are refused outright
instead.

## 5. Environment facts

- Repo: `C:\Users\gamai\vfx-mcp` (Windows 11, PowerShell primary, Bash available).
- Workstation: **pc137**, `10.10.10.31`, reachable over VPN as `ssh pc137`.
  Local VPN address `10.10.11.41` is the one on the plugin's IP allowlist.
- Houdini 21.0.596. Python package root on pc137:
  `C:/Users/Admin/Documents/houdini21.0/scripts/python/`
- Sandbox root: `C:/houdini_mcp_sandbox/`
- Audit log on pc137: `C:\Users\Admin\houdini_mcp_audit.log`
- Existing MCP server registered in Claude Desktop:
  `C:\Users\gamai\vfx-mcp\.venv\Scripts\python.exe C:\Users\gamai\vfx-mcp\houdini_mcp_server.py`

**Rules that apply to every phase:**

- Never start, stop, or restart Houdini. The owner does that manually; ask.
- Never `scp` plugin code by hand — deploys go through `scripts/deploy_plugin.sh`,
  which takes a timestamped backup first.
- Syntax-check on pc137 after every deploy:
  `& "C:\Program Files\Side Effects Software\Houdini 21.0.596\bin\hython.exe" -m py_compile <path>`
- Never touch production scenes. Sandbox only.
- Never re-enable `execute_code` / broad `modify_node` / broad `delete_node` in
  the old plugin.
- After each phase is verified working, append one line to `BACKLOG.md` under
  `## Done`: `- [x] YYYY-MM-DD — <what, one line>`.

---

## Phase 0 — restructure the repository

Do this first, so new code is born in the right place. No behaviour changes.

1. Extract `little_helpers/` (including `split_layers/`,
   `docs/NUKE_COMP_LAYER_ASSEMBLY.md`, `docs/NUKE_PIPELINE_TD_INTEGRATION.md`)
   into **https://github.com/sandalya/little_helpers**. It is a product shipped
   to other compositors and was already designed standalone — see
   `little_helpers/README.md`. Preserve history for the extracted files if
   practical; if not, a clean initial commit is acceptable — confirm with the
   owner which they prefer before pushing.
2. Reorganise what stays:
   ```
   CLAUDE.md                  ← shared safety doctrine, one copy only
   README.md                  ← topology, kill switches
   BACKLOG.md
   houdini/
     CLAUDE.md                ← Houdini-specific rules
     bridge/houdini_mcp_server.py     (moved, unmodified)
     plugin/server.py                 (moved, unmodified)
     plugin/HoudiniMCPRender.py       (moved, unmodified)
     docs/SCENE_ANALYSIS.md
   nuke/
     CLAUDE.md
     bridge/nuke_mcp_bridge.py
     plugin/nuke_mcp_plugin.py
   scripts/deploy_plugin.sh
   ```
3. Delete the empty leftover `nuke/split_layers/` directory.
4. Update `scripts/deploy_plugin.sh`: `HOUDINI_LOCAL_DIR` and `NUKE_LOCAL_DIR`
   now point at the new subdirectories.
5. Update the Claude Desktop config path for `houdini_mcp_server.py`
   (`C:\Users\gamai\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`)
   and tell the owner Claude Desktop must be restarted.
6. Nested `CLAUDE.md` files are picked up by Claude Code when working inside the
   subtree, so a Houdini session no longer loads Nuke context.

**Verify:** `./scripts/deploy_plugin.sh houdini` and `nuke` still run to
completion; nothing else changed. Commit as one change.

---

## Phase 1 — new plugin, read-only layer

New package `houdini/plugin/hmcp/`, deployed to
`C:/Users/Admin/Documents/houdini21.0/scripts/python/hmcp/`, listening on port
**9878**. The old plugin keeps running on 9876, untouched.

### Port from the old plugin (proven code, copy deliberately)

Socket accept loop, PySide6 `QTimer` main-thread pump, IP allowlist, audit-log
writer, inline-image encoding, and the "no auto-start; `start_server()` is
called by hand" rule.

### Do not port

`import_opus_url` and all download/unzip helpers, the asset-library handlers,
`modify_node`, `execute_code`, `set_material`, quad-view and specific-camera
renders.

### Files

**`hmcp/guards.py`** — the entire safety layer in one reviewable file.

```python
SANDBOX_ROOT = "c:/houdini_mcp_sandbox/"
SNAPSHOT_DIR = "c:/houdini_mcp_sandbox/_snapshots/"   # must pre-exist

def require_sandbox_scene():
    """Raise unless the open .hip lives under SANDBOX_ROOT.
    An unsaved/untitled scene is also refused — this forces an explicit,
    saved sandbox scene before any write happens."""
```

**Bootstrap exception.** `save_scene_as` is the single write command allowed to
run when the scene is *not* yet in the sandbox — and only when the scene has
**never been saved**. It cannot damage anything: the directory is a constant and
the filename is timestamped, so the target file never already exists.

It is deliberately *not* enough for the scene merely to be outside the sandbox.
If a named production scene were open, `saveAs` would leave that file untouched
on disk but would repoint the Houdini session at the sandbox copy — the owner's
next Ctrl+S would then silently go somewhere they did not expect. Refuse that
case; require a genuinely new scene.

Intended flow: owner opens a fresh Houdini → agent calls `save_scene_as()` →
scene becomes `C:/houdini_mcp_sandbox/mcp_<ts>.hip` → all other writes unlock.

Detecting "never saved": use `hou.hipFile.isNewFile()` **if it exists in 21.0.596** —
verify with hython before relying on it, this is exactly the kind of
version-specific API detail worth checking rather than recalling. Fallback:
compare `hou.hipFile.path()` against Houdini's default untitled path. Either way
the check belongs in `guards.py`, not in the command handler.

Lists, all matched case-insensitively on the exact parm name:

- `OUTPUT_PATH_PARMS` (always refused, even inside the sandbox):
  `outputimage`, `picture`, `vm_picture`, `ar_picture`, `lopoutput`,
  `sopoutput`, `dopoutput`, `copoutput`, `ropoutput`, `usdfile`, `savepath`,
  `outputfile`, `output`, `basedir`, `hdafile`, `otlfile`
- `INPUT_PATH_PARMS` (the only file parms that may be set): `file`, `filepath`.
  Any other parameter whose parm template is a file type is refused — this is an
  allowlist, not a heuristic, because `file` means different things on different
  node types and a substring test like "contains the word file" will eventually
  let an output parm through.
- `CODE_PARMS_ALLOWED`: `snippet`, `vexpression` (VEX only).
- `CODE_PARMS_REFUSED`: `python`, `script`, `callback`, `command`, `precmd`,
  `postcmd`, `prerender`, `postrender`, `preframe`, `postframe`. ROP script
  parameters execute shell/HScript and are as dangerous as Python.
- `NODE_TYPES_REFUSED`: `python`, `pythonscript`, `unix`, `shell`.
- Phase 1/2 additionally restricts node creation to the **SOP and OBJ**
  categories — the only ones the target domain needs.

Expressions are only ever set with `hou.exprLanguage.Hscript`. Never
`hou.exprLanguage.Python`.

Session registry: record `node.sessionId()` for every node the agent creates.
Deletion checks membership in that set.

Not the path, for two reasons. A path breaks on rename or move (which the
cosmetic commands allow), so the agent loses the ability to delete its own work.
Worse, Houdini reuses node names: if `/obj/geo1/sphere1` is destroyed and a
later, unrelated node ends up at that same path, a stale path-based registry
entry would authorise deleting *someone else's* node. `sessionId()` is stable
across rename and move and is not handed to a different node, so it answers
identity rather than name-matching.

Known limitation, and it fails in the safe direction: session ids do not survive
a scene reload, so after a reload the agent simply loses delete rights over
nodes it created earlier.

**`hmcp/intro.py`** — read commands, available always, in any scene:

- `get_geometry_info(node_path)` → `npoints`, `nprims`, `nvertices`, attribute
  list (name / class / type / size) per point-prim-vertex-detail, group names,
  bounding box, cook errors, cook warnings, cook time. **This is the most
  important new tool** — without it the agent builds a SOP graph blind.
- `get_node_errors(node_path)` → errors, warnings, cook state
- `get_node_type_parms(type_name, category)` → from `parmTemplates()`: names,
  labels, types, defaults, menu items. This is how the agent looks up real
  parameter names instead of recalling them.
- `list_node_types(category, name_filter)`
- `get_node_help(type_name, max_chars)` → built-in help text, truncated
- `get_network(parent_path)` → children plus their input connections, so the
  agent can read back the graph it just built
- `get_node_info(path, only_non_default)`, `get_scene_info(...)` — ported with
  the existing token-budget flags kept

**`hmcp/commands.py`** — one registry mapping command name →
`{handler, params, kind: "read" | "write"}`. The dispatcher is built from this
registry; there is no second hand-maintained list.

**`hmcp/server.py`** — transport plus dispatch over the registry.

**`hmcp/__init__.py`** — `start_server(host=...)` / `stop_server()`, no
auto-start on import.

### Preventing bridge/plugin drift

The broken `connect_nodes` exists because the bridge and the plugin each
maintain their own command list. Fix structurally:

- `houdini/commands_spec.py` — a single declaration of command names and
  parameters, imported by the bridge to build MCP tool schemas and deployed to
  pc137 to build the dispatcher table.
- `scripts/check_contract.py` — connects to the running plugin, calls a
  `describe_commands` read command, and diffs against the bridge's tool list.
  Call it from `deploy_plugin.sh` after the Houdini deploy.

### New bridge and Claude Code registration

`houdini/bridge/hmcp_bridge.py`, host `10.10.10.31`, port `9878`.

Register in Claude Code under a **different name** (`houdini2`) so the Claude
Desktop `houdini` entry is not disturbed:

```
claude mcp add houdini2 -- C:\Users\gamai\vfx-mcp\.venv\Scripts\python.exe C:\Users\gamai\vfx-mcp\houdini\bridge\hmcp_bridge.py
```

`.claude/settings.local.json` already allows `mcp__houdini__*`; add the
`mcp__houdini2__*` read tools alongside it.

### Verify Phase 1

Ask the owner to open a sandbox scene and start the new server. Then, from
Claude Code:

1. `get_scene_info` returns the sandbox scene
2. `get_geometry_info` on a node returns point/prim counts and attributes
3. `get_node_type_parms("mountain", "Sop")` returns real parameter names
4. `get_node_errors` on a nonexistent path returns a clean error, not a traceback
5. `scripts/check_contract.py` reports no mismatch
6. `hython -m py_compile` passes on every file in the package

No write command exists yet at this point.

---

## Phase 2 — write layer

`hmcp/build.py`. Every handler calls `require_sandbox_scene()` on its first line
and wraps its work in `with hou.undos.group("MCP: <op>"):`.

- `create_node(parent, type, name)` — category and type checks; registers the new
  node's `sessionId()`
- `connect_nodes(from, to, input_index)` — the capability that was missing entirely
- `set_parm(node, parm, value)` — runs the same guard checks as `create_node`;
  the old plugin's bypass (parameters set at creation time skipping the
  whitelist) must not reappear
- `set_expression(node, parm, expr)` — HScript language only
- `delete_node(path)` — only if `sessionId()` is in the session registry
- cosmetic: `rename_node`, `set_position`, `set_color`, `set_comment`,
  `layout_children`
- flags: `set_display_flag`, `set_render_flag`, `set_bypass`
- `save_scene_as()` — no arguments; plugin generates the name. The one command
  exempt from `require_sandbox_scene()`, under the bootstrap rule in Phase 1's
  `guards.py` section: allowed only from a never-saved scene.
- `viewport_snapshot()` — no arguments; plugin generates the path

### Verify Phase 2

Negative tests matter more than positive ones here:

1. With a **non-sandbox** scene open, every write command refuses
2. With an **unsaved** scene open, every write command refuses **except**
   `save_scene_as`, which succeeds and lands the scene in the sandbox
3. With a named **production** scene open, `save_scene_as` also refuses — the
   bootstrap exception covers never-saved scenes only
3. `delete_node` on a node the agent did not create refuses
4. `set_parm` on `sopoutput` refuses; on `file` succeeds
5. `set_parm` on a `python` parm refuses
6. Creating a `python` SOP refuses
7. A build block is undone completely by one Ctrl+Z in Houdini
8. `grep -nE "os\.remove|shutil|unlink|rmtree|requests|subprocess|zipfile" houdini/plugin/hmcp/`
   returns **zero** matches
9. Every refusal appears in the audit log

---

## Phase 3 — the acceptance target

From an empty scene saved under `C:/houdini_mcp_sandbox/`, Claude Code builds a
procedural rock unattended: roughly `sphere → mountain → attribwrangle (VEX) →
smooth/remesh` inside a `geo` object, reading geometry after each step, reading
node errors, correcting itself, and finishing with a viewport snapshot.

Parameters sit directly on the nodes at this stage. Promoted subnet parameters
(`seed` / `size` / `roughness` wired with `ch("../seed")`) are Phase 3.5 and need
parameter-interface editing, which is deliberately not in Phase 2.

**Passes when:** the graph cooks without errors; `get_geometry_info` shows
sensible point/prim counts and a sensible bounding box; the snapshot looks like a
rock; and one Ctrl+Z removes the entire build.

Only after this passes, discuss retiring the old plugin on port 9876.

### After Phase 3

Window asset (frame + glass), then promoted parameters, then HDA creation
(which reintroduces a file write and needs its own decision), then DOPs and
Copernicus.

What actually happened after Phase 3: `houdini/docs/HMCP_FEEDBACK_LOOP_PLAN.md`
(camera control, non-blocking render, `find_nodes`, the undo-revision guard —
Stages 0-5, done 2026-08-12). That document is the authoritative execution
order for everything built on top of this one.

---

## Out of scope

Lighting and `/stage` work, Karma/Arnold/Mantra rendering, writing to production
scenes, Python in parameters, any file deletion, recipe/golden-task
infrastructure, and OS-level sandboxing (not achievable here — see §4).
