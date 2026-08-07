# Backlog

## Done
- [x] 2026-05-16 — Bridge + plugin operational over VPN
- [x] 2026-05-16 — IP allowlist (`{127.0.0.1, 10.10.11.41}`) on plugin
- [x] 2026-05-16 — Dispatcher hardening: `execute_code`, `modify_node`, `delete_node` removed
- [x] 2026-05-16 — Auto-start removed from plugin `__init__.py`
- [x] 2026-05-17 — First live session validated (Claude Desktop ↔ pc137 sandbox via RDP)
- [x] 2026-05-17 — `set_node_parameter` (plugin + bridge) with `SAFE_PARMS` whitelist
- [x] 2026-05-17 — `get_node_info` bridge wrapper
- [x] 2026-05-17 — `parameters` passthrough in `create_node`
- [x] 2026-05-17 — `get_scene_info` cap raised to 100, added `context_filter` + `truncated` field
- [x] 2026-05-17 — Shelf-button kill switch "Stop MCP" on pc137
- [x] 2026-05-17 — OPUS code removed from bridge (was dead, no RapidAPI keys)
- [x] 2026-05-17 — Canonical local plugin copy at `vfx-mcp/plugin/server.py`
- [x] 2026-05-17 — `scripts/deploy_plugin.sh` (backup + scp + reminder)
- [x] 2026-05-17 — Bugfix: `hou.Color` serialization in `get_node_info`
- [x] 2026-05-17 — Bugfix: `parm.label()` → `parm.parmTemplate().label()`
- [x] 2026-05-17 — `get_node_info` cap removed; new `max_parms` and `only_non_default` flags
- [x] 2026-05-17 — Bugfix: defensive serialization (None-safe inputs/outputs/parms) — unblocks setvariant, collection::2.0
- [x] 2026-05-17 — First full /stage scene analyzed (`docs/SCENE_ANALYSIS.md`)
- [x] 2026-05-17 — Bridge tools `forward_to_cc` / `read_cc_inbox` (CD ↔ CC handoff via `notes/cc_inbox.md`)
- [x] 2026-05-17 — README refreshed: actual tool list + agent instructions section (CD picks up via `get_project_context`)
- [x] 2026-05-17 — Bugfix: defensive top-level `get_node_info` (ObjNode `isBypassed` AttributeError, plus `_safe()` wrapper for every field)
- [x] 2026-05-17 — Plugin error responses now include `exception_type` + full `traceback` (so CD can pinpoint future NoneTypes without round-tripping through the user)
- [x] 2026-05-17 — `scripts/dump_scene.py` (offline JSON dump of /stage and /obj — workaround for MCP token budget on big scenes)
- [x] 2026-05-17 — Bugfix: `execute_houdini_code` short-circuits in bridge (no socket round-trip) → no more 4-min MCP timeout on the disabled path
- [x] 2026-05-17 — SAFE_PARMS expansion: USD-encoded `xn__inputsexposure_vya`, `xn__arnoldglobalbucket_size_jebg`, `xn__arnoldglobalAA_samples_wcbg`
- [x] 2026-08-06 — `nuke_mcp_bridge.py` restructured to match `houdini_mcp_server.py` pattern (NukeConnection dataclass, Context, per-command timeouts, get_*_connection singleton)
- [x] 2026-08-06 — `nuke_mcp_plugin.py` deployed to pc137 `~/.nuke/`, wired via `menu.py` (manual start only, no auto-start — mirrors Houdini)
- [x] 2026-08-06 — Nuke MCP round-trip confirmed end-to-end: raw TCP ping, direct call, and real MCP protocol (list_tools/call_tool via stdio subprocess) all working against live Nuke on pc137 (port 9877). No SSH tunnel — direct VPN TCP like Houdini. Found: pc137 Windows Firewall fully OFF (all profiles) — port access is VPN reachability + app-level allowlist only, no OS rule for 9876 either.
- [x] 2026-08-06 — `nuke_mcp_plugin.py`: every MCP command now prints to Nuke's Script Editor (`[nuke-mcp HH:MM:SS] ip -> cmd(payload) -> ok/ERROR`) for live debugging; also fixed a bug where handler exceptions skipped `_audit()`. Deployed + verified live; pushed to `origin/main` (`909d28f`).
- [x] 2026-08-06 — New command `get_nodes_in_view` (plugin + bridge tool `nuke_get_nodes_in_view`): reconstructs the DAG's visible viewport rect from `nuke.center()`/`nuke.zoom()` + the `DAG_Window` Qt widget's pixel size, flags each node `in_view` by bounding-box intersection. `scripts/deploy_plugin.sh` extended to take a `<houdini|nuke|all>` target so it can deploy either plugin, each with its own backup. Deployed via hot `importlib.reload` (no Nuke restart needed) and verified round-trip on both raw TCP and the real MCP tool call.

- [x] 2026-08-06 — Hotkey-triggered overlay PoC, round 1: OS-level global hotkey (`keyboard` pkg's `WH_KEYBOARD_LL` hook, then raw `RegisterHotKey`) never fired — even synthetic `keybd_event` didn't trigger it, likely swallowed by AV/EDR (that hook shape is exactly what keyloggers use). Root-caused by isolating trigger vs. reaction: the PySide6 transparent-panel show logic was independently confirmed working (direct call + pixel-level alpha check), so the break was specifically in OS-level key detection, not the UI. Fix: register the shortcut Nuke-side instead, via `nuke.menu('Nodes').addCommand(..., 'alt+shift+p', shortcutContext=2)` calling `nuke_mcp_plugin.cmd_print(...)` directly — confirmed working end-to-end (Script Editor printed "Hotkey -> cmd_print works!"). Next: wire the actual PySide6 overlay to show via this same Nuke-native shortcut instead of a standalone process + OS hook.
- [x] 2026-08-06 — Hotkey-triggered overlay PoC, round 2 (done): moved the registration into `nuke_mcp_plugin.py` itself (`register_menu()`, idempotent via `findItem`/`removeItem`) so the dev loop is edit → deploy → hotkey, no more menu.py edits or Nuke restarts; confirmed by bumping a `TEST_ITERATION` constant and watching it update live. Landed on `ctrl+shift+a` (no `shortcutContext` override) as the working combo. Then ported the standalone `nuke_overlay.py` HUD widget (`_PrintHUD`) straight into the plugin: since Nuke 16 is itself a PySide6 app, the transparent panel now runs inside Nuke's own Qt loop on the same Nuke-native shortcut — no separate process, no socket, no OS hotkey at all. Confirmed working live by the user end-to-end.
- [x] 2026-08-06 — Nuke MCP server lifecycle: added `stop_server()` (closes the listening socket to unblock the blocking `accept()`, `_stop_requested` Event distinguishes a clean stop from a real error) and made `_server_thread`/`_server_socket`/`_stop_requested`/`_mcp_hud` reload-safe (`if 'x' not in globals()`), so `importlib.reload()` — which fires on every hotkey press — no longer orphans a live server thread or resets HUD visibility state. New dispatch commands `get_selected_nodes` (selection, Read nodes' `file` knob) and `get_env` (env vars by prefix) + matching bridge tools `nuke_get_selected_nodes`/`nuke_get_env`, for the live-scene discovery session next.
- [x] 2026-08-06 — New "MCP Server" HUD (Start/Restart/Stop stacked around the cursor; `ctrl+shift+t` or `Little Helpers/MCP Server` menu item, no hotkey required per Sashok's original ask). Bugfix along the way: `_serve()`'s "listening"/"stopped" prints never reached the Script Editor — background-thread stdout isn't captured there, same reason `_handle_client` already routes through `executeInMainThreadWithResult`; fixed the same way, plus added a status-flash label directly on the HUD so feedback doesn't depend on the Script Editor being visible. Discovered mouse clicks don't register reliably on this frameless/translucent/`Qt.Tool` window over the pc137 RDP session (Esc/keyboard events do reach it fine) — added a keyboard fallback (↑ Start, ↓ Stop, Enter/Space Restart, Esc close) as the actually-working interaction; mouse click wiring left in place but still unverified.
- [x] 2026-08-07 — `menu.py` on pc137 now calls `nuke_mcp_plugin.register_menu()` at Nuke startup (backed up first), so all hotkeys/menu items exist on a clean session with no manual `register_menu()` call — confirmed by Sashok on a fresh Nuke launch. Deliberately does NOT auto-start the socket server; that stays a manual Start in the MCP HUD, keeping the dev-convenience bridge fully decoupled from the tools themselves.
- [x] 2026-08-07 — Root-caused and fixed the MCP HUD mouse-click bug (was misdiagnosed as an RDP/translucent-window hit-testing issue): `_McpHud.show_near_cursor()` puts keyboard focus on the top-level widget itself, and `QPushButton`'s default focus policy steals focus on click — which fired the top-level's `focusOutEvent()` → `self.hide()` mid-click, before `mouseReleaseEvent` could complete the button's press/release gesture, so `clicked` never emitted. Fixed by setting `QtCore.Qt.NoFocus` on every button. Found via a from-scratch rebuild (per Sashok's steer: strip the MCP HUD down to a single Print button cloned from the already-working `_PrintHUD`, get that clicking, then build back up) plus temporary `mousePressEvent`/`eventFilter` diagnostics (removed once root-caused). Along the way also fixed a second, independent bug: `_mcp_hud`'s reload-safety (kept across `importlib.reload()` to support press-to-close) meant the widget instance was never rebuilt on redeploy, so code changes silently didn't show up until Nuke was fully restarted — now `_mcp_hud` always rebuilds fresh on every open, at the cost of the press-to-close toggle (Esc still closes). Start/Restart/Stop HUD rebuilt on the fixed base and confirmed working end-to-end by Sashok, mouse clicks included.

## TODO
- [ ] Live-scene discovery, once Sashok opens the real working scene (not sandbox): confirm the actual render-root env var (repo docs only document `$FTRACK_STUDIO_PATH` — `$FTRACK_RENDER_PATH` doesn't exist anywhere in the codebase) and how project/sequence/shot get determined in a live Nuke session (parse from the saved script path vs. read from env vars). Use the new `get_env`/`get_selected_nodes` tools for this. Blocks both items below.
- [ ] Function 1 (node init, per `docs/NUKE_COMP_LAYER_ASSEMBLY.md`) — HUD picks a render pass/branch from the render folder, script builds the full assembly chain: 4 Read nodes (beauty/lights/tech/crypto, versioned independently per pass — they don't move in lockstep) → ShuffleCopy → Copy chain → Cryptomatte/Dot-spine per-object mattes. Sashok confirmed full chain, not just the 4 Reads, is the target for the first real pass at this.
- [ ] Function 2 (node maintenance) — detect the current branch from selection, or from `get_nodes_in_view` if nothing's selected; must trace which Read nodes are actually live by following downstream connections (per the doc's note that stale/history Read nodes are kept, not deleted, so enumeration alone picks up dead ones too); diff on-disk versions against the live Reads; "update to latest" HUD action bumping each of the 4 passes independently. Side-by-side old-beauty stacking and keeping the second-to-latest Light version nearby are explicitly deferred — Sashok's own call, discuss later.
- [ ] Bridge tool `forward_to_cc(title, body)` — CD writes structured tickets to `notes/cc_inbox.md`; CC reads on demand
- [ ] Expand `SAFE_PARMS` whitelist for LOPs (intensity/exposure/coneAngle/color/normalize on light::2.0; xform t/r/s; editproperties primpath; prune method/primpattern). See `docs/SCENE_ANALYSIS.md` for grounded parm vocabulary.
- [ ] Consider per-node-type allowlist (LightLOP vs xform vs prune — different parm sets are safe)
- [ ] Decide on `set_material` exposure in bridge (handler exists in plugin)
- [ ] Claude Desktop Project "VFX MCP" with auto-instructions to call `get_project_context`
- [ ] Decide fate of `execute_houdini_code` bridge tool (currently surfaces but plugin blocks)
- [ ] Update README — currently mentions OPUS/set_material/asset_lib which were removed or never exposed (DONE 2026-05-17 in `cb121cf`)
- [ ] BUG 2: some /stage nodes still return `'NoneType' object has no attribute 'name'` (moon, hdri, tree_decoy, NO_PROXY_TEX1/2). Defensive `get_node_info` didn't cover the root cause — investigate with new traceback field next time CD hits it.
- [ ] Investigate `read_cc_inbox` intermittent hang reported after `execute_houdini_code` hang (2026-05-17 avp_assemble session). Hypothesis: FastMCP serialises tool calls and a previous slow tool poisons the queue. Now that `execute_houdini_code` short-circuits, this may resolve itself — re-check next session.
- [ ] More SAFE_PARMS entries as they surface (encoded `xn__` names from light::2.0 intensity/color/coneAngle/radius; rendersettings `xn__arnoldglobalGI_*`; xform `t/r/s`). Add incrementally from real scenes, not from speculation.
- [ ] Token-budget tools for big scenes:
  - `get_node_parm_names_only(path)` — list non-default parm names without values
  - `include_raw=False` flag on `get_node_info` — drop `raw_value` to save tokens
  - `parm_prefix_filter` on `get_node_info` — e.g. only `xn__arnoldglobal*`
  - `recursive=True` or new `get_node_tree(path, depth=N)` for flat sub-network walks

## Known scene-level anomalies (from `docs/SCENE_ANALYSIS.md` — informational, not infra TODOs)
- WIP rendersettings reference `/cams/cam_sh010` but no such camera (likely typo for `cam_sh110`)
- All rendersettings at 1280×1280 — preview resolution, not final
- Three bypassed production nodes: `sh110_sky`, `edit_standard_volume5`, `OUTPUT_120`
- `char_top` ≡ `char_top1` (duplicates)

## Decisions
- Hardening keeps `execute_code`, `modify_node`, `delete_node` out of dispatcher — re-enable only via narrow whitelisted tools
- Kill switches: VPN disconnect (instant) + Houdini shelf button (graceful). Nuclear SSH-kill of process holding port 9876 is a later addition
- Plugin source of truth: pc137 path. Repo holds patches and bridge. Canonical plugin checkout in repo is a future cleanup
- All editing tools must operate on whitelisted parameters/types — no broad `parm.set()` exposure

## Known limits
- `get_scene_info` caps at 10 nodes across `obj/shop/out/ch/vex/stage` (plugin `server.py` L247)
- Bridge host hardcoded `10.10.10.31`, port `9876` (bridge `houdini_mcp_server.py` L522)
- OPUS tools defined but inactive (no RapidAPI key) — they will fail at call time
