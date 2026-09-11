# little_helpers dev/prod lane — plan

Status: Steps 1-7 built, deployed and fully live-verified on pc137
2026-09-11, including actual dev-mode dispatch (F12 toggle, mode badge,
personal-copy retirement, `[MAIN]`/`[DEV]` dispatch to the correct package
— see `BACKLOG.md` and `NUKE_NOTES.md`'s 2026-09-11 entries, and the code
itself, `nuke/plugin/lh_router.py`, for how it works now). Open: Step 8
(the TD ask) and pruning the stale `*_bak_*` backup directories — see
*Still open*.

Supersedes two earlier versions of this plan. The first was a `main`/`dev`
branch-workflow plan (its open questions are answered in *Superseded
questions* at the bottom). The second, of 2026-09-10, split dev from
production as **two parallel menus with two hotkey sets** — that is replaced
here by a **session-local router behind one unchanged hotkey set**, because
Sashok will not learn or use a second set of hotkeys for dev. Nothing about
the name split, the worktree or the deploy target changed; only what the
hotkeys dispatch to.

Background facts this plan stands on — all in `nuke/docs/NUKE_NOTES.md`,
not repeated here: how Nuke resolves two copies of the same package, what
pc137's Nuke environment actually looks like, why there is no local Nuke
lane, and what `reload_all()` does and doesn't do.

## The problem in one paragraph

`little_helpers` now exists on the studio share **and** existed, until
Step 7 removed it, in `C:/Users/Admin/.nuke/` (the TD rollout landed
2026-09-11). Both were importable as the top-level name `little_helpers`,
and pc137's own `~/.nuke/init.py` prepends the share to `sys.path` — so
the share copy silently wins, `deploy_plugin.sh nuke` appears to stop
working, and `reload_all()` faithfully reloads the wrong copy. Editing in
place on a single shared name is editing production. The fix has to be a
*name* split, not a path-order split: path order is decided by a launcher
Sashok doesn't control, and it fails without an error message.

## The design

One production copy, one dev copy, **different top-level package names**,
both loaded in the same Nuke session at the same time — and **one set of
hotkeys** that dispatches to whichever is currently active.

- Production stays `little_helpers` (now resolving to the share), on
  `Little Helpers/…`, on the hotkeys it already has: `Shift+A` Create Layer
  Branch, `Shift+E` Change Layer Version, `F10` Split Layers, plus the
  `Ctrl+V` override of `Edit/Paste` in `nuke.menu("Nuke")`. Untouched by
  dev work.
- Dev is the *same source*, installed under the directory name
  `little_helpers_dev`. It gets **no menu and no hotkeys of its own**.
- A **router** sits between the hotkeys and the packages. Each menu command
  reads a session-local mode flag, imports + `reload_all()`s the package that
  flag names, prints one line saying which one, then calls the tool.
- **`F12` toggles the flag**, globally.
- **`Shift+F12`** does the same flip and also starts/stops the MCP server
  to match (added 2026-09-11, after live use showed Sashok wants MCP
  running whenever he's in DEV) — a separate hotkey, not a modifier on the
  same code path, so plain `F12` can never have an MCP side effect by
  accident. Flashes a temporary status line on the mode badge
  ("MCP started"/"stopped"/etc). See `NUKE_NOTES.md`'s "A reload-persistent
  object needs its own staleness check" entry for a real gotcha this hit
  and fixed.

Different top-level name means a different `sys.modules` key. Path order
stops mattering, `importlib.reload` cannot cross over, and a stale `.pyc` in
one cannot shadow the other. "Which copy am I running" is answered by the
mode badge and by the Script Editor line the router prints on every press —
not by introspection.

The flag is **session-local and resets to production on every Nuke launch**.
No env var, no file, no persisted state. A forgotten toggle cannot silently
carry into tomorrow's session; the worst case is one confusing press, with a
badge on screen saying why.

The dev copy is produced by **renaming a directory at deploy time**, not by
forking the source. Every intra-package import is already relative and
`reload_all()` already targets `__name__`, so a renamed directory is a
working independent package as-is. The repo never contains a
`little_helpers_dev` directory.

The iteration loop stays what it is today — edit, `deploy_plugin.sh`, press
the hotkey, `reload_all()` picks it up — with two words changed: it targets
`nuke-dev`, and `F12` is pressed once at the start of the session. No
restart, no relaunch, no env toggle, no `git checkout` in the loop.

### Where the router lives — outside both packages

The router is **not** part of `little_helpers` and **not** part of
`nuke_mcp_plugin.py`. It is its own module, `nuke/plugin/lh_router.py` in
this repo, deployed by the existing `nuke` target to
`C:/Users/Admin/.nuke/lh_router.py`, and called from `menu.py`. Three
reasons, all structural:

- `little_helpers` is now **shared studio code**. Other artists import it
  off the share; none of them should get a dev router, an `F12` binding or a
  mode badge. Sashok's dev lane must not ship to them.
- The production copy being on the share makes it the *worst* place for
  router code: changing the router would mean a TD pull, which is the
  opposite of a fast iteration loop.
- `nuke_mcp_plugin.py` is infra and stays infra. It keeps
  `ctrl+shift+t` → `toggle_mcp_hud()` exactly as it is, gains no router
  awareness, and still imports `little_helpers` only.

`lh_router.register_menu()` rebinds the same four menu paths that
`little_helpers.register_menu()` owns, using the same
findItem/removeItem/addCommand idiom, so calling it *after* the stock
registration simply overwrites those four entries with router commands — no
duplicates, and deleting the router line from `menu.py` reverts to stock
behaviour on the next launch.

## Steps

### Steps 1-7 — done, verified live on pc137 2026-09-11

- **Step 1** (router) — built as `nuke/plugin/lh_router.py`, deployed via
  the `nuke` target. How it works is documented in the module itself and
  in `NUKE_NOTES.md`'s "`lh_router`'s `nuke`-module state stash survives
  self-reload" entry — not repeated here.
- **Step 2** (F12 collision check) — done by Sashok directly on the
  production machine: no collision.
- **Step 3** (dev worktree) — created: `../little_helpers-dev`, branch
  `dev`.
- **Step 4** (`nuke-dev` deploy target) — added to `deploy_plugin.sh`.
  Not yet run — see *Still open*.
- **Step 5** (wire the router into `menu.py`) — done by Sashok, live on
  pc137.
- **Step 6** (floating mode badge) — built inside `lh_router.py`. The
  reload-safety and early-creation risks the original version of this step
  flagged are resolved: confirmed live via repeated F12 presses, no
  orphaning, no duplicate widget (`NUKE_NOTES.md`, same entry as Step 1).
- **Step 7** (retire the personal production copy) — done: precondition
  confirmed (`little_helpers.__file__` resolves to
  `Documents\plarium-nuke-external\little_helpers-2\...`, not `~/.nuke`,
  see `NUKE_NOTES.md`'s "Studio share `little_helpers` resolves under
  `Documents\plarium-nuke-external`" entry), `C:/Users/Admin/.nuke/little_helpers/`
  deleted. `deploy_plugin.sh`'s `nuke` target no longer deploys
  `little_helpers` at all (it briefly, accidentally recreated the deleted
  copy on the next `nuke` deploy before this was caught and fixed — fixed
  now, the target is infra-only: `nuke_mcp_plugin.py` + `lh_router.py`).

Dev-mode dispatch itself is also confirmed: `little_helpers_dev` deployed
via `nuke-dev`, and pressing a tool hotkey in each mode printed the correct
package and resolved path in both directions (`NUKE_NOTES.md`, same entry
as Step 1). The `nuke-dev` target's `py_compile` step needed two follow-up
fixes to run cleanly over ssh (Microsoft Store `python.exe` alias stub gave
a false "python is available" reading) — not a design issue, just a PowerShell
error-handling gotcha, fixed in `deploy_plugin.sh` itself.

### Step 8 — one thing to hand the TD

Ask that the share install be an **atomic directory swap** (copy to a temp
dir next to it, then rename into place), not a file-by-file copy over the
live directory. Production is imported off the share and every hotkey press
re-reads and reloads it — a press landing mid-copy hands a live production
session a half-written module.

## Working rules once this is up

- Dev iteration is `nuke-dev` only. Production (the share) is touched by
  graduated code only.
- `F12` at the start of a dev session, and the badge says `DEV` until Nuke
  is relaunched. If the badge says `MAIN`, the hotkeys are running studio
  code.
- Exercise dev tools on a `Save As` copy of the shot, not the live script.
  These tools write into the node graph; that is the one real risk the name
  split does not cover.
- `nuke_mcp_plugin.py` imports `little_helpers`, never `little_helpers_dev`,
  and knows nothing about the router. Infra depends on the stable copy.
- The router prints the active package and its `__file__` on every press, so
  the old "print `__file__` before trusting surprising behaviour" rule is now
  automatic — read the last line in the Script Editor instead
  (see `NUKE_NOTES.md`).

## Deliberately not in scope

- **No local Nuke lane.** This machine is Nuke 15.0v4 with an empty
  `~/.nuke` and no `NUKE_PATH`; it can't run `Split Layers` (needs
  `pl_scripts`) or `Create Layer Branch` (needs `$FTRACK_RENDER_PATH`) and
  it's on the wrong Qt binding. Not worth standing up.
- **No venv, no packaging, no CI, no tests in `little_helpers`.** Nuke
  embeds its own interpreter and artists launch through the pipeline
  launcher; there is nowhere for a venv to attach. Keep the package
  import-only.
- **No per-mode hotkeys.** Rejected explicitly: one set of hotkeys, one
  toggle. Anything that makes dev and production respond to different keys
  is out.
- **No persisted mode.** No env var, no dotfile, no "remember last mode".
  The reset-on-launch is the safety property, not an omission.
- **No `NUKE_PATH` / launch-profile toggle as the dev mechanism.** It needs
  a Nuke relaunch per switch, which is the one thing this design is
  optimising against. It stays available as the emergency off-switch: stop
  deploying `nuke-dev` and the dev lane is simply gone.
- **The studio rollout itself** — content, timing, who pulls what — stays
  the TD's call, per `little_helpers/docs/NUKE_PIPELINE_TD_INTEGRATION.md`.

## Still open

- **Step 8** — deprioritized 2026-09-11, Sashok's call: not raising the
  atomic-swap ask with the TD proactively. Reasoning: it's the TD's
  deploy process to run, and if the file-by-file-copy race ever actually
  bites (a hotkey press landing mid-copy hands a live session a
  half-written module), the TD will surface it. Revisit only if that
  actually happens, not preemptively.
- ~~Prune the stale `*_bak_*` backup directories under `~/.nuke`~~ — done,
  separately, by Sashok. Confirmed clean on pc137 2026-09-11: zero
  `*_bak_*` directories left, only the 4 small per-file backups from
  today's own `nuke`/`nuke-dev` deploys (`nuke_mcp_plugin.py.bak_*` ×3,
  `lh_router.py.bak_*` ×1) — recent, small, not cruft, left alone.
- **Do other artists get the tools from the same share entry that
  `~/.nuke/init.py` prepends, or from a launcher-injected `NUKE_PATH`
  entry?** Partially answered (`NUKE_NOTES.md`'s "Studio share
  `little_helpers` resolves under `Documents\plarium-nuke-external`" entry):
  it's a per-machine synced local mirror, not a live UNC read, so two
  artists' copies can in principle drift out of sync depending on sync
  timing. What actually triggers the sync is still unidentified. Changes
  nothing in this plan — the router only ever runs from Sashok's `menu.py`.

Resolved since the previous version: the TD rollout has landed, the MCP
menu's `ctrl+shift+t` does not collide with `F12`, the F12 binding itself
has no collision, the badge's reload-safety/early-creation risks are
confirmed fine live, and dev-mode dispatch itself is confirmed working
end to end.

## Superseded questions

From the first version of this plan:

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

> Does `nuke_mcp_plugin.py`'s import of `little_helpers.nuke_utils` need
> its own compatibility check before merging `dev` → `main`?

Not as a separate gate. `nuke_mcp_plugin.py` imports `little_helpers`, and
dev code is never named that (Step 4's rule), so dev iteration cannot reach
it at all. What remains is the ordinary rule that
`nuke_utils.dag_viewport_rect` / `list_render_dir` are a public API with an
outside caller: changing either signature means checking that caller before
merging. That belongs in a docstring on those two functions, not in a
workflow gate.
