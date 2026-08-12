# External review — github.com/oculairmedia/houdini-mcp

Comparative review of a public Houdini MCP implementation, done to check our
own `hmcp` package (`houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md`) against an
independent design and pull out anything concretely worth adapting or
avoiding. Gathered read-only against the public repo (README, ADRs, docs/,
and source excerpts from `houdini_mcp/tools/`) — the items marked
**unverified** below were not confirmed against actual cloned source and
should be checked before acting on them.

## 1. Architecture / transport

| | Ours (`hmcp`) | Theirs |
|---|---|---|
| Transport | Raw socket server inside the Houdini process (`plugin/hmcp/server.py`, `hou.ui.addEventLoopCallback` pump, port 9878) + a thin MCP bridge (`bridge/hmcp_bridge.py`) that talks MCP to Claude | Houdini's bundled `hrpyc` (RPyC remote-Python), three modes: stdio plugin (in-process), HTTP gateway via a separate FastMCP process (RPyC port 18811), SSE |
| Network exposure | IP allowlist on the plugin socket | Loopback-only by default; non-local requires `HOUDINI_RPC_TRUSTED_NETWORK=1` or a shared-secret `HOUDINI_RPC_TOKEN` — their own docs concede the token is "not a cryptographic authentication system" |
| Design rationale | Bridge is a thin shim; plugin never reimplements `hou` semantics | Their ADR 0001 explicitly rejected a Rust/Go sidecar, TypeScript gateway, and C++ HDK plugin on the same grounds — "`hou`'s live proxy objects only exist inside Houdini's embedded interpreter," reimplementing that elsewhere is unbounded maintenance. Landed on a 4-layer model (L0 Houdini semantics → L1 RPyC transport → L2 tools → L3 FastMCP gateway) where no layer reimplements the one below it |

Their ADR reaching the same "don't reimplement `hou` outside Houdini"
conclusion by a different route is worth noting as independent validation of
our own approach, not something to copy structurally — RPyC and our raw
socket solve the transport problem differently, and RPyC brings its own
exposure (§3).

## 2. Tool coverage — 43 tools across 15 categories vs. our 24

Full list, as they group it: **Scene** (get_scene_info, serialize_scene,
new_scene, save_scene, load_scene, get_last_scene_diff), **Nodes**
(create_node, delete_node, get_node_info, list_children, find_nodes,
list_node_types), **Wiring** (connect_nodes, disconnect_node_input,
reorder_inputs, set_node_flags), **Parameters** (set_parameter,
get_parameter_schema), **Geometry** (get_geo_summary), **Rendering**
(render_viewport, render_quad_view, list_render_nodes, get/set_render_settings,
create_render_node), **Materials** (create_material, assign_material,
get_material_info), **Errors** (find_error_nodes), **Layout**
(layout_children, set_node_position, set_node_color, create_network_box),
**Code execution** (execute_code + internal detectors), **Help**
(get_houdini_help), **Cache** (node_type_cache, invalidate_all_caches,
get_cache_stats), **AI summarization** (summarize_geometry/errors/scene,
get_summarization_status, should_summarize, estimate_tokens), **Pane
screenshots** (capture_pane_screenshot, list_visible_panes,
capture_multiple_panes, render_node_network).

**Where they exceed us:**

- **Materials** — nothing on our side; out of scope per the rewrite plan's
  SOP/VEX-first target, worth flagging as a known future-phase gap rather
  than an oversight.
- **Rendering beyond viewport** — quad-view, ROP/render-settings management,
  Karma GPU/CPU. Deliberately scoped out on our side (OpenGL viewport
  snapshot only, no Karma/Arnold/Mantra) — confirmed intentional, not a gap.
- **Pane screenshots beyond viewport** — `capture_pane_screenshot` supports
  30 pane types (NetworkEditor, ParmSpreadsheet, SceneGraphTree,
  PerformanceMonitor, etc.), not just SceneViewer. A NetworkEditor screenshot
  specifically is worth adding — see §4.1.
- **AI summarization as first-class tools** (summarize_geometry/scene,
  estimate_tokens, should_summarize) rather than parameters. We have the same
  *goal* via max_nodes/max_parms/only_non_default flags — see §4.5 for the
  one piece worth borrowing.
- **`get_last_scene_diff` / TransactionManager** — a checkpoint/undo-audit
  layer distinct from raw `hou.undos.group()`. The single most interesting
  idea in the repo — see §4.1.
- **`find_nodes` / `list_children`** — scene-wide search/traversal. We only
  have `get_network(parent_path)`, one level at a time — see §4.3.
- **`reorder_inputs`** for merge-type nodes — narrow, useful, we have nothing
  equivalent — see §4.4.

**Where we're already at parity or ahead:** `get_node_type_parms`,
`get_node_help`, `list_node_types`, `get_geometry_info`, `get_node_errors`,
`get_network`, `get_node_info`, `create_node`, `connect_nodes`, `set_parm`,
`set_expression`, `delete_node`, `rename_node`, `set_position`, `set_color`,
`set_comment`, `layout_children`, `set_display_flag`, `set_render_flag`,
`set_bypass`, `save_scene_as`, `viewport_snapshot` all have direct or
near-direct equivalents on both sides. One difference worth flagging: our
`set_expression` is HScript-only by design; their `set_parameter` accepts an
"expression"-style value with no documented language restriction
(**unverified** — check their actual source for a Python-expression path,
since if none exists this is a real safety gap on their side).

## 3. Safety / scope — the finding to lead with

**Their `execute_code` tool is exactly the capability our own doctrine
permanently forbids, gated by precisely the control our own plan document
already names and rejects.**

Confirmed from `houdini_mcp/tools/code.py`:

```python
exec_globals = {"hou": hou, "__builtins__": builtins.__dict__}
```

Full `hou` plus the complete, unrestricted `__builtins__` — `__import__`,
`open`, `eval`, everything — is available inside every `execute_code` call.
The only gate is three regex/pattern detector functions
(`_detect_dangerous_code`, `_detect_mutation_code`,
`_detect_heavy_geometry_code`, in `_common.py` — contents **unverified**,
flagged for a follow-up clone pass) that scan the code *string* before
running it. That gate is itself bypassable two ways: `allow_dangerous=True`
together with the `HOUDINI_MCP_ALLOW_BYPASS` environment variable, or (for
the heavy-geometry class) an internal `_trusted_internal_heavy_geometry`
flag. Their "protective error" on `import hou` inside `execute_code` is
itself just a string-match special case, not a real capability boundary —
`__import__('os').system(...)` isn't called out as blocked anywhere, and
given `__builtins__` passes through whole, nothing indicates it would be.

This is a textbook instance of the exact anti-pattern
`HOUDINI_MCP_REWRITE_PLAN.md` §4 already names and rejects:

> "A blacklist over Python source text ... is not acceptable as a control —
> it is trivially bypassed via `__import__`, `getattr`, `hou.hscript()` —
> which is why Python-bearing parameters are refused outright instead."

Secondary points:

- Their RPyC transport, once opened beyond loopback, is itself a broad
  remote-code-execution surface independent of `execute_code` — RPyC by
  design exposes live Python object proxies over the wire. Loopback-default
  + optional token is reasonable but explicitly not cryptographic auth per
  their own docs.
- No file-path allowlist analogous to our `OUTPUT_PATH_PARMS`/
  `INPUT_PATH_PARMS` split was surfaced from what's public — `save_scene` /
  `load_scene` / render-settings tools likely accept caller-supplied paths
  (**unverified**). If true, that's the same unrestricted-write-path problem
  our rewrite plan retired from the *old* plugin (`import_opus_url`,
  caller-supplied `render_path`).
- Their `TransactionPolicy.EXTERNAL_SIDE_EFFECT` category (§4.1) is an
  implicit admission that some of their tools do irreversible file writes —
  consistent with the point above.

**Bottom line:** do not adopt `execute_code`, its detector functions, or the
bypass-flag pattern in any form. This is the one part of the external repo
that stands as a direct counter-example to our own "absence of capability,
not validation of capability" rule, not a source of ideas.

## 4. Worth adapting

1. **Checkpoint/diff-aware transaction wrapper** (`transactions.py`,
   `TransactionManager`/`TransactionPolicy`/`MUTATING_TOOL_POLICIES`). They
   classify every mutating tool into one of three reversibility classes:
   `UNDOABLE` (wrap in `hou.undos.group()`, revert via `performUndo()` on
   exception — the half we already do), `CHECKPOINT_REQUIRED` (explicit scene
   backup first, for things Houdini's undo can't cleanly cover), and
   `EXTERNAL_SIDE_EFFECT` (file writes — flagged, not undoable at all). The
   interesting part we don't have: before allowing a revert, they check the
   scene's current undo-stack position against the revision recorded right
   after the agent's own transaction, and refuse if it's moved. That protects
   against the owner making manual edits in Houdini between the agent's write
   and a later agent-initiated undo — silently eating the owner's work
   otherwise. Worth a lightweight version: record the hip file's revision (or
   equivalent) at write time, refuse `delete_node`/undo-adjacent operations
   if it's since moved.

2. **NetworkEditor screenshot as a second, narrow snapshot tool.** Their
   `render_node_network(node_path)` navigates the NetworkEditor to a path,
   frames its children, and screenshots — same "no caller-chosen destination,
   generated path only" shape our `viewport_snapshot` already has. A
   `network_snapshot(parent_path)` sibling (same guard model: read-only path
   argument, generated filename under `_snapshots/`) would let the agent
   visually verify wiring/layout, not just geometry — directly useful for the
   Phase 3 acceptance target's "reading node errors, correcting itself,"
   since a misrouted connection is exactly what a geometry-only snapshot
   won't reveal. Low risk: it's a read operation dressed as a screenshot, no
   new write surface beyond what `viewport_snapshot` already established.

3. **`find_nodes(name_filter, type_filter)` scene-wide search.** Small,
   pure-read, fills a real gap — today the agent can only enumerate via
   `get_network(parent_path)` one level at a time. A flat filtered search
   across the whole scene (or a subtree) is a natural complement to
   `list_node_types` and costs nothing safety-wise.

4. **`reorder_inputs` for merge-style nodes.** Narrow, single-purpose,
   read-then-rewrite-connections operation. Only worth adding once Phase-3+
   scope actually needs merge nodes with ordering semantics — a "when
   needed" item, not urgent.

5. **Token-budget constants as named thresholds.** They define
   `RESPONSE_SIZE_LARGE_THRESHOLD`/`RESPONSE_SIZE_WARNING_THRESHOLD` and an
   `estimate_tokens` helper, gating whether a summarized or raw response
   comes back (`should_summarize`). We already have the mechanism
   (max_nodes/max_parms/only_non_default flags), just not named constants or
   a shared size-estimate helper. Low priority — a code-quality
   consolidation, not a new capability.

6. **Structured error-response shape**
   (`{status, message, error_type, recoverable, exception}` /
   `{status, message, hint, suggested_fix}`). Worth matching in spirit: our
   `get_node_errors` already returns errors/warnings/cook state — worth
   confirming *every* handler, not just that one, consistently signals
   machine-checkable success/failure rather than relying on exceptions
   bubbling to the bridge. The `hint`/`suggested_fix` fields specifically are
   a cheap, useful addition for an LLM caller.

7. **Type-compatibility check before wiring.** Their `connect_nodes` refuses
   e.g. Sop → Dop with a named error. We don't currently validate category
   compatibility beyond what `node.setInput()` itself enforces —
   **unverified** whether that already raises a clean error on a mismatched
   category or an opaque one; if the latter, a pre-check
   (`.type().category()` compatibility before calling `setInput`) is a small,
   easy win. Worth transplanting the idea, not their code.

## 5. Worth avoiding

1. **`execute_code` in any form** — see §3. The headline avoid-item.
2. **Regex/heuristic string-blacklists as a safety control.** The
   `_detect_dangerous_code`/`_detect_mutation_code` pattern generalizes badly
   beyond `execute_code` too — our own doctrine already commits to
   allowlists over blacklists everywhere (`INPUT_PATH_PARMS` as an allowlist,
   not "reject paths containing /etc/"); treat this as a category of mistake
   to watch for, not something specific to that one tool.
3. **Bypass flags gated only by an env var**
   (`HOUDINI_MCP_ALLOW_BYPASS`/`allow_dangerous=True`). An env var isn't a
   permission boundary the MCP caller doesn't control — if the same
   process/environment runs the plugin, the agent effectively controls its
   own safety gate. Contrast with our sandbox-path check, which depends on
   which file is open, not a flag the agent can flip via a tool argument.
4. **Caller-supplied output paths on render/save tools** — flag as needing
   verification (**unverified**), but if `save_scene`/`render_viewport`
   accept arbitrary destination paths, as the public docs suggest with no
   allowlist parallel to our `INPUT_PATH_PARMS`/`OUTPUT_PATH_PARMS` split,
   that's the same class of problem our rewrite plan retired from the *old*
   plugin. Don't adopt "path is a tool parameter" for any write destination —
   matches our own already-decided rule that the agent never passes a path to
   any tool.
5. **43-tool surface breadth for its own sake.** Several categories
   (materials, full ROP/render-settings management, cache-introspection like
   `get_cache_stats`) exist because their scope is broader (general Houdini
   automation) than ours (SOP/VEX procedural geometry, Phase 1). Don't treat
   "they have more tools" as pressure to expand scope — our phase boundaries
   are a deliberate choice, not a gap.

## Open items — not verified against cloned source

Gathered via WebFetch against the public GitHub repo only; no local clone was
made. Worth a short follow-up pass if any of §4/§5's adopt/avoid calls need to
move from "likely" to "confirmed" before acting on them:

- `houdini_mcp/tools/_common.py` — actual detector regex/keyword lists behind
  `_detect_dangerous_code`/`_detect_mutation_code` (existence confirmed,
  content not read).
- `set_parameter` — whether it accepts Python-language expressions
  unrestricted, or only HScript-equivalent values (§2, §3).
- `save_scene`/`load_scene`/render-settings tools — actual path-parameter
  shape, to confirm or correct the "likely caller-supplied path" flag (§3,
  §5.4).
- `houdini_plugin/python/houdini_mcp_plugin/` (stdio mode) — whether it
  differs meaningfully in safety posture from the HTTP/hrpyc mode, since
  stdio mode runs in-process like ours does.
