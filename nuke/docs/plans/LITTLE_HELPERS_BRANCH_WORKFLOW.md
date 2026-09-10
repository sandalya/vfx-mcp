# little_helpers dev/prod lane — plan

Status: designed 2026-09-10, nothing built yet. Supersedes the earlier
`main`/`dev` branch-workflow plan of the same name (its three open
questions are answered in *Superseded questions* at the bottom).

Background facts this plan stands on — all in `nuke/docs/NUKE_NOTES.md`,
not repeated here: how Nuke resolves two copies of the same package, what
pc137's Nuke environment actually looks like, why there is no local Nuke
lane, and what `reload_all()` does and doesn't do.

## The problem in one paragraph

`little_helpers` is about to exist on the studio share as well as in
`C:/Users/Admin/.nuke/`. Both are importable as the top-level name
`little_helpers`, and pc137's own `~/.nuke/init.py` prepends the share to
`sys.path` — so the share copy would silently win, `deploy_plugin.sh nuke`
would appear to stop working, and `reload_all()` would faithfully reload
the wrong copy. Editing in place on a single shared name is now editing
production. The fix has to be a *name* split, not a path-order split:
path order is decided by a launcher Sashok doesn't control, and it fails
without an error message.

## The design

One production copy, one dev copy, **different top-level package names**,
both loaded in the same Nuke session at the same time.

- Production stays `little_helpers`, on `Little Helpers/…`, on
  `Shift+A` / `Shift+E` / `F10`. Untouched by dev work.
- Dev is the *same source*, installed under the directory name
  `little_helpers_dev`, on a `Little Helpers (dev)/…` menu with its own
  hotkeys.

Different top-level name means a different `sys.modules` key. Path order
stops mattering, `importlib.reload` cannot cross over, and a stale `.pyc`
in one cannot shadow the other. The menu label is the tell: "which copy am
I running" is answered by reading the menu, not by introspection.

The dev copy is produced by **renaming a directory at deploy time**, not by
forking the source. Every intra-package import is already relative and
`reload_all()` already targets `__name__`, so a renamed directory is a
working independent package after one small change (Step 1). The repo
never contains a `little_helpers_dev` directory.

The iteration loop stays what it is today — edit, `deploy_plugin.sh`, press
the hotkey, `reload_all()` picks it up — with two words changed: it targets
`nuke-dev` and a dev hotkey. No restart, no relaunch, no env toggle, no
`git checkout` in the loop.

## Steps, in order

### Step 1 — make `register_menu()` name-agnostic (`little_helpers` repo, `main`)

The only place the literal string `little_helpers` appears in executable
code is the three menu command strings in `register_menu()`, plus the
three `*_MENU_PATH` constants and the three hotkeys. Derive all of them
from `__name__`:

- command strings become `f"import {__name__}; {__name__}.reload_all(); {__name__}.show_…()"`
- a module-level `_IS_DEV = __name__.endswith("_dev")` selects the menu
  root (`"Little Helpers"` vs `"Little Helpers (dev)"`) and the hotkey set
- when `_IS_DEV`, `reload_all()` also prints `__name__` and `__file__` —
  one line per keypress, so every dev press states which copy just ran

Do this on `main`, not on a dev branch: it makes the package genuinely
relocatable, which the TD rollout wants anyway.

Candidate dev hotkeys: `Ctrl+Shift+A`, `Ctrl+Shift+E`, `Ctrl+F10`. Verify
them the way §3 of the TD doc says — against *every* top-level Nuke menu,
not just `Nodes` (the `Shift+D` collision came from the `Viewer` menu).
The dev hotkeys are optional; the `Little Helpers (dev)` submenu alone is
enough if a clean set can't be found.

### Step 2 — add a `Reload + re-register` item to the dev menu

`reload_all()` cannot introduce a *new* hotkey — `register_menu()` runs at
startup only. A dev-only menu item that calls
`reload_all(); register_menu()` closes the last case that currently needs
a Nuke restart. Dev-only: re-registering in production mid-session is not
something to invite.

### Step 3 — create the dev worktree

In the `little_helpers` repo:

```
git branch dev
git worktree add ../little_helpers-dev dev
```

Result: `C:\Users\gamai\little_helpers` stays on `main` and is what the
production deploy reads; `C:\Users\gamai\little_helpers-dev` is on `dev`
and is what the dev deploy reads. Both on disk at once.

A worktree rather than branch-switching in the one checkout, because
`deploy_plugin.sh nuke` reads whatever is checked out at deploy time — a
`git checkout dev` in the main checkout silently re-aims the *production*
deploy at dev code. The worktree removes `git checkout` from the loop
entirely.

### Step 4 — add a `nuke-dev` target to `deploy_plugin.sh`

New target, alongside the existing ones (never folded into `all`):

- source: `$(dirname $REPO_ROOT)/little_helpers-dev/little_helpers`
  (plus its `split_layers/` and `veriter/` subdirs, same three
  `deploy_dir` calls as the `nuke` target)
- destination: `C:/Users/Admin/.nuke/little_helpers_dev/`
- **skip the backup** on all three calls — dev has nothing worth backing
  up, and skipping saves an ssh round-trip per iteration
- keep the remote `__pycache__` clean step
- deploys `little_helpers` only. It must never touch
  `nuke_mcp_plugin.py` — infra is not part of the dev lane.

The existing `nuke` target is unchanged.

### Step 5 — wire the dev copy into pc137's `menu.py`

Append to `C:/Users/Admin/.nuke/menu.py`, *after* the existing
`little_helpers.register_menu()` line:

```python
try:
    import little_helpers_dev
    little_helpers_dev.register_menu()
except Exception as exc:
    print("little_helpers_dev not loaded: %s" % exc)
```

Order and the `try` are the guarantee that a broken dev copy can never
cost Sashok his production menu: production is registered first, and dev
failing is a printed line, not a traceback that drops everything below it.
Absent dev copy = the same printed line.

This is a one-time hand edit on pc137 (no clipboard over RDP — type it),
and per the repo safety rules, back `menu.py` up first.

### Step 6 — retire the personal production copy, once the studio share has one

Do this only when the TD rollout has actually landed and
`print(little_helpers.__file__)` in a fresh Nuke on pc137 reports the
share path.

At that point `C:/Users/Admin/.nuke/little_helpers` is a second copy of the
same name, which is the exact hazard this plan exists to remove. Delete it,
stop using `deploy_plugin.sh nuke`'s little_helpers legs for production,
and let the share be the only `little_helpers`. Graduation from dev to prod
becomes: merge `dev` → `main`, push, tell the TD to pull — not an scp.

Also prune the 27 `*_bak_*` directories under `~/.nuke` at this point, and
cap future backups (keep the last 3).

Both are destructive actions on pc137: ask before doing either.

### Step 7 — one thing to hand the TD

Ask that the share install be an **atomic directory swap** (copy to a temp
dir next to it, then rename into place), not a file-by-file copy over the
live directory. Once production is imported off the share, every hotkey
press re-reads and reloads it — a press landing mid-copy hands a live
production session a half-written module.

## Working rules once this is up

- Dev iteration is `nuke-dev` only. Production (`nuke` target, or the
  share once Step 6 lands) is touched by graduated code only.
- Exercise dev tools on a `Save As` copy of the shot, not the live script.
  These tools write into the node graph; that is the one real risk the
  name split does not cover.
- `nuke_mcp_plugin.py` imports `little_helpers`, never `little_helpers_dev`.
  Infra depends on the stable copy.
- Before trusting any surprising behaviour, print `__file__` (see
  `NUKE_NOTES.md`). It is the whole answer and it takes a second.

## Deliberately not in scope

- **No local Nuke lane.** This machine is Nuke 15.0v4 with an empty
  `~/.nuke` and no `NUKE_PATH`; it can't run `Split Layers` (needs
  `pl_scripts`) or `Create Layer Branch` (needs `$FTRACK_RENDER_PATH`) and
  it's on the wrong Qt binding. Not worth standing up.
- **No venv, no packaging, no CI, no tests in `little_helpers`.** Nuke
  embeds its own interpreter and artists launch through the pipeline
  launcher; there is nowhere for a venv to attach. Keep the package
  import-only.
- **No `NUKE_PATH` / launch-profile toggle as the dev mechanism.** It needs
  a Nuke relaunch per switch, which is the one thing this design is
  optimising against. It stays available as the emergency off-switch: stop
  deploying `nuke-dev` and the dev lane is simply gone.
- **The studio rollout itself** — content, timing, who pulls what — stays
  the TD's call, per `little_helpers/docs/NUKE_PIPELINE_TD_INTEGRATION.md`.

## Still open

- **Has the TD rollout actually happened, and what is on the share?**
  `//loky.rep2.local/repository/app/winOld/nuke` can't be listed over ssh
  (no network credentials in a non-interactive Windows ssh session). Needs
  one look from inside a launched Nuke on pc137:
  `import little_helpers; print(little_helpers.__file__)` plus
  `print("\n".join(nuke.pluginPath()))`. Steps 1–5 are correct either way;
  Step 6 depends on the answer.
- **Do other artists get the tools from the same share entry that
  `~/.nuke/init.py` prepends, or from a launcher-injected `NUKE_PATH`
  entry?** Changes nothing in this plan, but it decides whether Sashok's
  production copy and everyone else's are literally the same files.
- **Dev hotkeys pending a collision check** (Step 1).

## Superseded questions

From the previous version of this plan:

> Does "test on dev" mean local-Nuke-only (checkout `dev` here, restart
> Nuke, try it), or does it also need to reach pc137 without touching
> `main`'s deployed state?

Neither. Local-Nuke-only was never possible — there is no local Nuke lane
(see *Deliberately not in scope*). Dev testing happens on pc137, and it
reaches pc137 under a **different package name and a different directory**,
so "without touching `main`'s deployed state" is structural rather than
careful: `nuke-dev` cannot write to production's path, and the two
packages can't shadow each other. The suggested
`NUKE_LITTLE_HELPERS_REMOTE_DIR` override is replaced by a fixed second
target (Step 4); an override variable would just be another way to aim dev
code at production by accident.

> Merge criteria from `dev` → `main`: manual smoke test only (no CI/tests
> exist), or worth adding a minimal check (e.g. `py_compile` across the
> package, mirroring what `deploy_plugin.sh` already does for `hmcp`)?

Manual smoke test on pc137, and that is the real gate — every bug this
package has had (PySide6 enum moves, a knob's TCL serialisation, a version
bump not re-reading the frame range) was a live-behaviour bug that
`py_compile` would have passed. Add `py_compile` to the `nuke-dev` target
anyway, because it is nearly free and catches the one class it does catch:
a syntax error deployed into a live session, where the failure surfaces as
a hotkey that silently does nothing. Do not add CI or a test suite.

> Does `nuke_mcp_plugin.py`'s import of `little_helpers.nuke_utils` need
> its own compatibility check before merging `dev` → `main`?

Not as a separate gate. `nuke_mcp_plugin.py` imports `little_helpers`, and
dev code is never named that (Step 4's rule), so dev iteration cannot reach
it at all. What remains is the ordinary rule that
`nuke_utils.dag_viewport_rect` / `list_render_dir` are a public API with an
outside caller: changing either signature means checking that caller before
merging. That belongs in a docstring on those two functions, not in a
workflow gate.
