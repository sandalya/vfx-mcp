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

## Safety rules (shared, both stacks)

- Destructive actions (deleting files/nodes, force-git, changing production
  data, anything on pc137 beyond a normal read/deploy) — always ask before
  doing it, even if technically permitted
- Never re-enable `execute_code` / broad `modify_node` / broad `delete_node`
  in either dispatcher — new capabilities go through narrow whitelisted
  tools only
- Full context (topology, tool list, kill switches) lives in README.md —
  read it on demand
- Domain-specific rules live in nested `CLAUDE.md` files, loaded
  automatically when working inside that subtree: `houdini/CLAUDE.md`,
  `nuke/CLAUDE.md`

## Language

Separate the interface language from the model's working language: write system prompts, instructions, and internal context in English — that's the model's working language, cheaper and more precise — but keep the conversation with the user in their own language. Reply language follows the language of the incoming message, not the language of the system prompt.
