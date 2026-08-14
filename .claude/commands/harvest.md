---
description: Audit the docs against the lifecycle rule and harvest anything overdue
---

Run the document-lifecycle audit for this repo. The rule itself is in the
root `CLAUDE.md` under *Document lifecycle*; this is its checkable form.

Scope: `$ARGUMENTS` if given (a stack name like `houdini`, or a single plan
file). Otherwise audit every stack.

## 1. Measure

```
find . -path ./.venv -prune -o -name "*.md" -print | grep -v "^./.venv"
wc -l <each stack>/docs/*.md <each stack>/docs/plans/*.md
wc -c BACKLOG.md
```

## 2. Look for the four smells

Each maps to a rule the lifecycle section states. Report file:line for every
hit; do not fix anything yet.

| Smell | How to find it | Rule broken |
|---|---|---|
| Facts born inside a plan | `grep -nE "^> \*\*(Answer\|Answers)" <stack>/docs/plans/*.md` — also `Confirmed live`, `Measured`, `RESOLVED` in answer blocks | 1 — a discovered fact belongs in `*_NOTES.md` when discovered |
| Decisions born inside a plan | `grep -nE "^\*\*D[0-9]+ —\|Decision \(20\|Owner decision" <stack>/docs/plans/*.md` | 2 — decisions belong in the design doc's log, dated |
| Plan citing another plan | `grep -n "PLAN.md" <stack>/docs/plans/*.md` (hits naming another file in `plans/`) | 3 — plans cite reference docs only |
| A closed stage still carrying a transcript | in each plan's progress tracker, any stage marked done whose own section is longer than a status line | partial harvest — collapse it |

Also check for dangling references, which block deletion:

```
grep -rn "<plan basename>" --include="*.py" --include="*.sh" --include="*.md" . | grep -v "^./.venv"
```

## 3. Decide the disposition of each plan

For every file in `<stack>/docs/plans/`, state one of:

- **live** — nothing landed yet, leave alone
- **partially landed** — name which stages closed; their facts/decisions get
  filed now and their sections collapse to status lines
- **fully closed** — harvest and delete
- **abandoned** — what was learned → notes, why dropped → decision log,
  rest → the deletion commit body

## 4. Report before acting

Present the findings as a short list: what moves where, what gets collapsed,
what gets deleted. **Deletions are shown before they happen**, per the repo's
safety rules. Wait for the go-ahead unless the user already gave it.

## 5. Then execute, in this order

1. File the durable content at its destination (notes / design log / README)
2. Rewrite every reference that points at a doc about to be deleted — code
   comments and docstrings included, they are instructions to whoever edits
   that code next
3. Syntax-check anything touched (`py_compile`, `bash -n`)
4. `git rm` the closed plans
5. One line in `BACKLOG.md` under `## Done`
6. Commit — the body carries the full reasoning, the dead ends, and the
   harvest map, since that commit is the retrieval point for the deleted
   documents

Then verify the retrieval path actually works:

```
git log --diff-filter=D --oneline -- <stack>/docs/
git show <sha>^:<path> | wc -l
```

## Also check, since they share the same failure mode

- `BACKLOG.md` — read fresh every session. Over ~40KB, or entries older than
  the current work era, means trimming into `BACKLOG_ARCHIVE.md`
- `notes/cc_inbox.md` — append-only; entries that were processed should be
  marked resolved or moved into a permanent doc, per `notes/README.md`
