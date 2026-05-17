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

## TODO
- [ ] Bridge tool `forward_to_cc(title, body)` — CD writes structured tickets to `notes/cc_inbox.md`; CC reads on demand
- [ ] Expand `SAFE_PARMS` whitelist for LOPs (intensity/exposure/coneAngle/color/normalize on light::2.0; xform t/r/s; editproperties primpath; prune method/primpattern). See `docs/SCENE_ANALYSIS.md` for grounded parm vocabulary.
- [ ] Consider per-node-type allowlist (LightLOP vs xform vs prune — different parm sets are safe)
- [ ] Decide on `set_material` exposure in bridge (handler exists in plugin)
- [ ] Claude Desktop Project "VFX MCP" with auto-instructions to call `get_project_context`
- [ ] Decide fate of `execute_houdini_code` bridge tool (currently surfaces but plugin blocks)
- [ ] Update README — currently mentions OPUS/set_material/asset_lib which were removed or never exposed

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
