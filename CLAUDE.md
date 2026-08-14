# CLAUDE.md

Project-specific instructions for Claude Code in this repo.

## Work log habit

After a block of work is verified working (test passes, round-trip confirmed,
deploy succeeds) — before moving to the next thing — append one line to
`BACKLOG.md` under `## Done`:

```
- [x] YYYY-MM-DD — <what, one line, one sentence>
```

Keep it to what changed and whether it's verified — no incident narrative, no
"how we found it," no alternatives tried. `BACKLOG.md` is a fast scan of
*what and when*, not a debugging diary; it gets read fresh every session, so
weight here is paid every time.

Anything more detailed (why, how it was diagnosed, dead ends, gotchas) goes in
the **commit message body** instead. Git history costs nothing until someone
explicitly asks for it (`git log`, `git show <sha>`) — that's where the full
story belongs.

`README.md` and nested docs (`houdini/docs/*`, `nuke/docs/*`) describe
*current state* — edit them in place when behavior changes. Don't leave the
superseded description next to the new one "for history"; that's what git
blame is for.

No memory update unless the user asks.

## Document lifecycle — plans die, facts get rehomed

Three genres of document, and only one of them lives forever:

| Genre | Where | Lifetime |
|---|---|---|
| **Plan** — instructions for work not yet done | `<stack>/docs/plans/` | ends when the work lands |
| **Reference** — how it works *now* | `<stack>/docs/`, `README.md` | permanent, edited in place |
| **Notes / gotchas** — measured facts, silent failure modes | `<stack>/docs/*_NOTES.md`, triage docs | permanent, appended to |

A non-empty `plans/` means there is open work. That is the whole point of the
folder — "should this still exist?" answerable at a glance.

**When a plan closes, harvest it, then delete it.** Fixed addresses:

- how it works now → the reference doc / `README.md`, **edited in place**
- why it's this way, don't undo it → the decision log in the stack's design
  doc, or a docstring at the guard it protects
- a fact that was expensive to measure, or a failure mode that's silent →
  the notes doc
- what and when → one line in `BACKLOG.md` under `## Done`
- everything else — dead ends, alternatives, verification transcripts, the
  full reasoning → **the body of the commit that deletes the doc**

Deleting loses nothing: `git show <sha>^:path/to/doc.md` brings it back
whole, and the design doc's "superseded documents" section records the
pointer. The difference is that git costs no context until someone asks.

If a fact lives *only* in a closed plan, that's a filing bug — move it, don't
keep the plan alive for it. Same rule for `BACKLOG.md`'s `## Done`: it is read
fresh every session, so trim old entries into `BACKLOG_ARCHIVE.md` rather than
letting it grow without bound.

Before deleting, rewrite the references that point at the doc — code
comments and docstrings especially, since those are instructions to whoever
edits that code next.

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
