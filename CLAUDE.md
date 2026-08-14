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

**That line is the trigger for filing everything else.** At the same moment,
before moving on, answer three questions:

1. Did this block establish a fact that was expensive to measure, or a
   failure mode that fails silently? → the stack's `*_NOTES.md`, now
2. Did it settle something a future session could undo by accident? → the
   dated decision log in the stack's `*_DESIGN.md`, now
3. Did it close a stage of a plan in `docs/plans/`? → collapse that stage's
   section to a status line. If it was the last stage, harvest and delete
   the plan — see *Document lifecycle* below

Three "no"s is a normal answer and costs seconds. Skipping the questions is
exactly what produces a 1500-line plan nobody can delete.

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

### While a plan is alive — this is what keeps the cleanup cheap

A closed plan should be nearly worthless by the time it closes. If harvesting
one turns out to be real work, facts were filed in the wrong place *while the
work was happening*. Four rules prevent that:

1. **A discovered fact is born in its permanent home, not in the plan.** When
   a probe answers something — a real parm name, an API that behaves against
   its documentation, a measured timing — write it into the notes doc *then*,
   and have the plan link to it. Never `> **Answer:**` blocks accumulating
   inside the plan; that is exactly what makes a finished plan undeletable.
2. **A decision is born in the design doc's decision log**, dated, with its
   reason. The plan cites it. Two plans needing the same decision is the
   signal it belongs there, not the signal to copy it.
3. **Plans cite reference docs, never other plans.** Cross-citation between
   plans builds a web where deleting any one of them breaks the rest.
4. **A plan holds only ordering, scope and open questions** — what to do in
   what order, what is deliberately out, what is still unknown. Everything
   durable it discovers moves out as it is discovered.

### Subagent research — the subagent writes the doc, not you afterwards

Do not spawn a research subagent and then work out where its output goes.
Put the destination in its prompt: *"write your findings to
`<stack>/docs/plans/<NAME>.md` before returning; your chat report is a
summary of that file, not the deliverable."* The file then exists before the
result is ever read, and nothing depends on remembering after the fact.

That doc lands in `plans/` and inherits this lifecycle. Its durable findings
are split out to the notes and design docs at the **first** read-through
with the user, not saved up for the end. If nothing is left after the split,
it was research rather than a plan, and the file in `plans/` goes away.

Backstop: a `SubagentStop` hook in `.claude/settings.json` fires when a
subagent finishes and nothing under `docs/plans/` has changed, and says so.

### Partial harvest — the normal case

Most plans land in stages, so harvest per stage, at the same moment the
`BACKLOG.md` line is written. That is one habit, not two: the stage is done →
its durable facts and decisions are filed → one Done line → the stage's
section in the plan collapses to a status line, not a kept transcript.

When the last stage closes, deleting the plan should be a formality. A plan
whose stages are all closed but which still holds unfiled content is
overdue — harvest it then, not "later".

A plan that gets abandoned rather than finished is deleted the same way: what
was learned goes to the notes doc, why it was dropped goes to the decision
log, and the commit body carries the rest.

### When a plan closes

**Harvest it, then delete it.** Fixed addresses:

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
