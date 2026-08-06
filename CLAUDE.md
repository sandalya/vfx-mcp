# CLAUDE.md

Project-specific instructions for Claude Code in this repo.

## Work log habit

After a block of work is verified working (test passes, round-trip confirmed,
deploy succeeds) — before moving to the next thing — append one line to
`BACKLOG.md` under `## Done`:

```
- [x] YYYY-MM-DD — <what, one line>
```

That's the log. No separate write-up, no memory update unless the user asks.

## Safety rules

- Never touch production Houdini scenes — sandbox only: `C:/houdini_mcp_sandbox/`
- Never start/stop Houdini yourself — the user does that manually
- Plugin changes go only through `plugin/server.py` → `scripts/deploy_plugin.sh` (it backs up before every deploy) — never scp by hand
- Never re-enable `execute_code` / `modify_node` / `delete_node` in the dispatcher — new capabilities go through narrow whitelisted tools only
- Destructive actions (deleting files/nodes, force-git, changing production data, anything on pc137 beyond a normal read/deploy) — always ask before doing it, even if technically permitted
- Full context (topology, tool list, kill switches) lives in README.md — read it on demand

## Language

Separate the interface language from the model's working language: write system prompts, instructions, and internal context in English — that's the model's working language, cheaper and more precise — but keep the conversation with the user in their own language. Reply language follows the language of the incoming message, not the language of the system prompt.
