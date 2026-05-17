# notes/

Cross-agent handoff folder.

## `cc_inbox.md`

Append-only log written by Claude Desktop via the `forward_to_cc` bridge tool.
Read by Claude Code (CC) at the start of a session or on demand.

**CD writes** with category-labelled entries:
- `[bug]` — plugin / bridge / infra defect with repro context
- `[observation]` — workflow pattern, parm idiom, scene structure worth recording
- `[question]` — something CD couldn't resolve and wants CC to investigate
- `[note]` — anything else worth handing off (default category)

**CC reads** by either:
- Asking the user "check inbox" → CC reads `cc_inbox.md`
- Doing it automatically at session start when this file shows new content since the previous CC commit

**Lifecycle:** entries are not auto-deleted. CC processes them, writes any code/doc/commit, and either:
- Marks them done inline (`> resolved: <commit-sha>`), or
- Moves them into a permanent doc (BACKLOG.md, SCENE_ANALYSIS.md, memory)

The inbox is committed to git when meaningful — it's a project artefact, not a temp file.
