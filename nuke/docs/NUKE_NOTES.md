# Nuke stack — notes

Measured facts and gotchas for the Nuke side of this repo. Permanent,
append-only. See `nuke/CLAUDE.md` for rules, `README.md` for topology.

## `little_helpers` repo mechanics (checked 2026-08-20)

`little_helpers` (`github.com/sandalya/little_helpers`, sibling checkout
at `../../little_helpers`) is a real GitHub-backed repo, not a solo-local
one — currently a single `main` branch, 12 commits, clean working tree,
in sync with `origin/main`. No CI, no tests, no `pyproject.toml`/
`package.json`, no pre-commit hooks — `.gitignore` only excludes
`__pycache__/`/`*.pyc`.

**How Nuke loads it — no build/copy step, code runs live off disk.**
There's no `init.py`; the repo root's `menu.py` (`import little_helpers;
little_helpers.register_menu()`) is what Nuke auto-loads, and it works
because the repo root sits directly on `NUKE_PATH`. Consequence:
switching branches (or leaving uncommitted edits) in the checkout changes
Nuke's behavior on the very next launch/reload — there is no packaging,
install, or deploy step in `little_helpers` itself that copies code
anywhere.

**pc137 is the one exception, and it goes through `vfx-mcp`, not
`little_helpers`.** `little_helpers` has no deploy script of its own (no
analog to `vfx-mcp`'s `deploy_plugin.sh`) — but `vfx-mcp`'s
`scripts/deploy_plugin.sh nuke` does deploy it: it reads the sibling
checkout at `../../little_helpers` (whatever branch/commit is on disk
locally at deploy time, uncommitted changes included) and `scp`s
`little_helpers/`, `little_helpers/split_layers/`, and
`little_helpers/veriter/` to `C:/Users/Admin/.nuke/little_helpers` on
pc137, backing up the previous remote copy first and clearing stale
`__pycache__` after. pc137 itself never runs `git` against this repo —
it only ever receives whatever was scp'd.

`nuke/plugin/nuke_mcp_plugin.py` imports directly from
`little_helpers.nuke_utils` (`dag_viewport_rect`, `list_render_dir`) and
is deployed to the same pc137 `.nuke` folder by the same script run — a
breaking change in `little_helpers` that reaches pc137 can break the MCP
plugin's menu/dispatch too, not just the three artist-tools hotkeys.

See `nuke/docs/plans/LITTLE_HELPERS_BRANCH_WORKFLOW.md` for the dev/prod
lane design this raises.

## How Nuke resolves two copies of the same package (checked 2026-09-10)

Nuke uses **two different orderings** for two different things, and they
disagree. This is the mechanism behind the 2026-08-14 stray-`.nuke/split_layers`
shadowing incident, and it fails silently every time.

- **`init.py` / `menu.py` execution**: Foundry's docs state the plug-in
  path is walked in *reverse* order and **every discovered copy is
  executed** — most global first (`nuke_dir`), most local last (`~/.nuke`),
  so a local `menu.py` can override a studio one. Two `menu.py` files on
  two different path entries both run; neither shadows the other.
- **`import <name>` (Python)**: first match on `sys.path` wins and the
  result is cached in `sys.modules` for the life of the process. Nothing
  warns about the losers.
- Plug-in path entries are put on `sys.path`, and `nuke.pluginAddPath()`
  **prepends** to both (`addToSysPath=True` by default). So the *last*
  `init.py` to call `pluginAddPath` puts its directory at the *front* of
  `sys.path` — the opposite end from where the same directory sits in
  menu-execution order.

Default plug-in path search order (Foundry docs): `~/.nuke`, `project_dir`,
`studio_dir`, `company_dir`, `nuke_dir`.

**The one-second check for "which copy is actually live", in the Script
Editor:**

```python
import little_helpers, nuke
print(little_helpers.__file__)
print("\n".join(nuke.pluginPath()))
```

`__file__` is the whole answer. Anything that reasons about path order
instead of reading `__file__` is guessing.

**Corollary — a sourceless `.pyc` still imports.** A legacy-layout
`foo.pyc` sitting *directly in* a package dir (not under `__pycache__/`)
is importable with no `foo.py` next to it. This is why
`deploy_plugin.sh nuke` clears remote `__pycache__` after every deploy;
keep that step on any new deploy target.

## pc137's Nuke environment (read 2026-09-10, read-only over ssh)

- `NUKE_PATH` is **not** set at Machine or User level. It is injected per
  process by the ftrack/pipeline launcher, so it can't be inspected or
  changed from outside a launched session, and a system env var is not a
  usable lever.
- `C:/Users/Admin/.nuke/init.py` (Sashok's own) calls
  `nuke.pluginAddPath('//loky.rep2.local/repository/app/winOld/nuke')` —
  the studio share. Because `pluginAddPath` prepends and `~/.nuke/init.py`
  runs last, **that share ends up ahead of `~/.nuke` on `sys.path`**. If a
  `little_helpers` package is ever installed on that share, it will
  silently win `import little_helpers` over `C:/Users/Admin/.nuke/little_helpers`,
  and `deploy_plugin.sh nuke` will appear to stop having any effect.
  (Share contents not verifiable over ssh — non-interactive Windows ssh
  sessions get no network credentials, `Test-Path` returns Access denied.)
- `C:/Users/Admin/.nuke/menu.py` registers, in order: a large personal
  hotkey set, `nuke_mcp_plugin.register_menu()`, then
  `little_helpers.register_menu()`. Nothing is wrapped in try/except — an
  exception in an earlier line silently drops every registration after it.
- `~/.nuke` holds 14 `little_helpers_bak_*` and 13 `split_layers_bak_*`
  directories from `deploy_dir()`'s backup-before-overwrite. Inert today
  (wrong top-level names, no `menu.py` inside), but it is dead weight on
  the production plug-in path and the residue of exactly the shadowing
  failure class above.

## The local dev machine has no working Nuke lane (checked 2026-09-10)

Contrary to what earlier plans assumed: this machine has **Nuke 15.0v4**
(pc137 runs 16.0v5), `NUKE_PATH` is unset, and `~/.nuke` contains only
prefs — no `menu.py`, no `little_helpers`. There is no local Nuke lane to
fall back on, and standing one up would only exercise two of the three
tools: `Split Layers` needs the pipeline's `pl_scripts` (share-only) and
`Create Layer Branch` needs `$FTRACK_RENDER_PATH` (launcher-only). Nuke 15
also means PySide2 rather than pc137's PySide6, so Qt behaviour would
differ from production. Fast-loop iteration has to happen on pc137.

## `reload_all()` limits (read from source, 2026-09-10)

`little_helpers.reload_all()` reloads `sys.modules[__name__]`, i.e. it
targets **whatever the package is currently imported as** — it is not
hardcoded to the name `little_helpers`. Every intra-package import is
relative. So a copy of the package installed under a different directory
name is a fully working, independently reloadable package with no source
edits. (The three menu command strings in `register_menu()` are the *only*
place the literal name `little_helpers` appears in executable code — see
the plan doc for the change that removes that last hardcode.)

Three things `reload_all()` does **not** do:

1. **New menu entries / new hotkeys don't appear.** `register_menu()` runs
   at Nuke startup only; `reload_all()` refreshes the code behind existing
   command strings but never re-runs registration. Adding a hotkey needs
   `register_menu()` called by hand or a Nuke restart. (First hit
   2026-08-07 with the new `F10` binding.)
2. **`_RELOAD_ORDER` is a static tuple, and module-scope
   `from .sibling import NAME` bindings depend on it being complete and
   correctly ordered.** `veriter/version_ui.py` does
   `from .versions import _HISTORY_ENABLED` at module scope — reloading
   `versions` rebinds it there but leaves `version_ui`'s copy stale;
   correctness only holds because `_RELOAD_ORDER` reloads `versions`
   before `version_ui` on every keypress. Any new module added with a
   module-scope `from .sibling import name` must be added to
   `_RELOAD_ORDER` *after* its dependency, or it will silently serve stale
   values with no error.
3. **Nothing outside the package is reloaded** — `pl_scripts.split_layers`
   in particular is deliberately left alone.

Qt caveat: reloading a module that defines a `QWidget` subclass does not
re-class already-open instances, and it resets the module-level singletons
that track them (`layer_picker_ui._layer_picker_hud`,
`veriter.version_ui._version_hud`). Close a tool's HUD before relying on a
reload.

## Render layer folders are named `<layer>_<shot-number>`, not `<layer>` (confirmed 2026-09-10)

Found via a real `WinError 3` on paste, project `raid_c`: under
`$FTRACK_RENDER_PATH`, layer folders carry the shot's own number as a
suffix baked into the folder name itself — sh320's render root has
`bg_320`/`atmo_320`/`chars_320`, sh370's has `bg_370`/`atmo_370`/
`chars_370`. This is a per-project convention, not universal — an earlier
project (`raid_echoes_of_oz`, see the 2026-08-07 entries above) had plain
`bg`/`fg`/`atmo` with no numeric suffix at all. Anything that carries a
layer name across shots (`little_helpers.repath`, and any future tool)
must strip a trailing `_\d+` before treating two shots' layer names as
"the same layer", then re-resolve the real folder name against the target
shot's actual directory listing — never assume the suffix format, and
never assume there is one.

## Nuke's built-in Paste command lives at `Nuke/Edit/Paste`, not a top-level "Edit" menu

`nuke.menu("Edit")` returns `None` — Paste is a leaf under
`nuke.menu("Nuke")`'s `Edit` submenu instead, confirmed via a recursive
`nuke.menu()` walk across `Nuke`/`Nodes`/`Viewer`/`Preferences`/`Player`
(the same class of hidden-top-level-menu gotcha as the Shift+D/native
"go to next keyframe" collision documented earlier in this file). Full
live-probed inventory of paste-related bindings:

- `Nuke/Edit/Paste` — natively `Ctrl+V` — `with nuke.lastHitGroup(): nuke.nodePaste(nukescripts.cut_paste_file())`. `little_helpers.repath` overrides this exact menu path (`findItem`/`removeItem`/`addCommand`, same idiom `register_menu()` uses for the three `Little Helpers/...` entries, just on `nuke.menu("Nuke")` instead of `nuke.menu("Nodes")`) and rebinds it to `Alt+V` (moved off `Ctrl+V` 2026-09-11, Sashok's ask, to keep plain `Ctrl+V` free). Confirmed live 2026-09-12: `removeItem` really does drop the native `Ctrl+V` binding for good, no fallback — plain `Ctrl+V` did nothing until a *second* override, `Edit/Paste (Plain)` (`little_helpers.paste_plain`, identical body to the native command, no repath check), was added and bound to `Ctrl+V` itself.
- `Nuke/Edit/Paste (Plain)` — `Ctrl+V` — added 2026-09-12, `little_helpers.paste_plain` — restores what the native `Edit/Paste` used to do, now that that menu path/hotkey belongs to the repath override above.
- `Nuke/Edit/@;Paste2` — `Ctrl+Shift+V` — `nuke.nodePaste(nukescripts.cut_paste_file())` (no `lastHitGroup()` — pastes without regard to the group under the cursor). Not overridden by `little_helpers.repath`.
- `Nuke/Edit/Paste Knob Values` — `Ctrl+Alt+V` — unrelated (copies knob values, not nodes).

## Studio share `little_helpers` resolves under `Documents\plarium-nuke-external`, not the raw UNC path (confirmed live 2026-09-11)

The 2026-09-10 entry above flagged the share path as unverifiable over ssh
and only guessable from `init.py`'s `pluginAddPath` call. Live-checked in a
real Nuke session on pc137 after the TD rollout landed and the personal
`C:/Users/Admin/.nuke/little_helpers/` copy was deleted:

```
print(little_helpers.__file__)
# C:\Users\Admin\Documents\plarium-nuke-external\little_helpers-2\little_helpers\__init__.py
```

So the pipeline's actual install point is a synced/managed local mirror
under `Documents\plarium-nuke-external\little_helpers-2\`, not a raw
`\\loky.rep2.local\...` UNC read. Whatever puts it there (launcher sync,
`NUKE_PATH` injection, or something else) still isn't identified — doesn't
change anything about the router design, since it only cares that
`import little_helpers` resolves to *something*, not to which path — but
it answers "which copy are other artists on" partially: it's a per-machine
synced copy, not a live UNC read, so two artists' copies can in principle
be out of sync with each other depending on when each last synced.

## `lh_router`'s `nuke`-module state stash survives self-reload (verified live 2026-09-11)

`nuke/plugin/lh_router.py` stores its dev/prod flag (`nuke._lh_dev_mode`)
and its floating mode-badge widget instance (`nuke._lh_mode_badge`) as
attributes on the `nuke` module itself, specifically because the router's
own menu commands `importlib.reload()` the router module on every press —
the same pattern that orphans `nuke_mcp_plugin.py`'s `_hud`/`_mcp_hud`
module-level references (see that file's comments). Confirmed working as
designed on pc137: repeated `F12` presses correctly toggled
`[DEV]`/`[MAIN]` in the Script Editor and the on-screen badge across many
consecutive presses, with no orphaned/duplicate badge and no flag reset.
Full dev-mode dispatch also confirmed live: with `little_helpers_dev`
deployed via `nuke-dev`, pressing a tool hotkey in each mode printed the
correct package and path — `[MAIN] little_helpers active` resolving to
`...\Documents\plarium-nuke-external\little_helpers-2\little_helpers\__init__.py`,
`[DEV] little_helpers_dev active` resolving to
`C:\Users\Admin\.nuke\little_helpers_dev\__init__.py` — across repeated
toggles with no state loss.

## A reload-persistent object needs its own staleness check, not just the flag pattern (confirmed 2026-09-11)

`lh_router._ModeBadge`'s instance is deliberately stashed on `nuke`
(`nuke._lh_mode_badge`) so it survives `lh_router`'s self-reload on every
press -- same reasoning as the mode flag. That worked exactly as intended
for *state* (the flag), but not for *code*: adding a new method
(`flash_status()`) to `_ModeBadge` and redeploying hit the live badge with
`AttributeError: '_ModeBadge' object has no attribute 'flash_status'`.

Cause: `importlib.reload()` re-executes the module and rebinds the class
name (`_ModeBadge`) to a *new* class object in the module's namespace, but
any already-constructed instance's `__class__` still points at the *old*
class object -- reload never re-classes existing instances. An object kept
alive specifically to survive reload therefore keeps running on whatever
class shape existed when it was built, silently missing anything a later
edit added, until something crashes on the missing attribute.

This is the same root cause as `nuke_mcp_plugin`'s documented `_hud`/
`_mcp_hud` gotcha (reload wiping a module-level reference), but the fix is
the opposite shape: those are solved by *always rebuilding* on every press
(cheap, since they're throwaway UI). A reload-persistent object can't take
that fix without losing the reason it's persistent, so it needs an active
staleness check instead: `_update_badge()` now does
`isinstance(badge, _ModeBadge)` against the *current* class before reusing
the cached instance, and transparently rebuilds if it's stale. Generalizes:
**anything stashed on `nuke` specifically to survive a self-reloading
module's reload must re-validate its class on every access, not just check
"does it exist."**

## `nuke_execute_code`'s `exec(code, {}, local_ns)` breaks nested-`def` closures over top-level names (confirmed 2026-09-11)

The plugin's `cmd_execute_code` (`nuke/plugin/nuke_mcp_plugin.py`) runs
diagnostic code as `exec(code, {}, local_ns)` — two *different* dict
objects for globals and locals. This is the same scoping CPython uses for
a class body, and it has the same well-known gotcha: a `def` written at
the top level of the exec'd code can only close over another top-level
name via a genuine closure if the compiler recognizes an enclosing
*function* scope. Exec/class-body top-level "locals" don't count as that —
a name looked up inside a nested `def` resolves via `LOAD_GLOBAL` against
that function's `__globals__`, which was bound to the `{}` passed to
`exec()`, not `local_ns`. Any name that only exists in `local_ns` is
invisible to the nested function, and fails inside it at call time, not
at `def` time — confirmed by a direct A/B (a closure-based fake read
`captured` fine when called in the same top-level scope that defined it,
but calling the exact same function object from *another module's* code
failed).

This bit while trying to monkeypatch `nuke.ask` with a closure-based fake
to dry-run `_maybe_repath_cross_shot_reads` without a live popup — the
call surfaced only as `'NoneType' object is not a mapping`, a genuinely
misleading message (`cmd_execute_code`'s error path collapses whatever
went wrong to `str(exception)`, no traceback returned over the socket).
The exact mechanism behind that specific message was never nailed down
(plausible: the broken fake raised before returning, so the *real*
`nuke.ask` fired for real on pc137's main thread) — not worth more
forensic effort now that the underlying scoping gotcha is understood and
the actual feature was separately confirmed working by Sashok's own live
test.

**Fix for any future diagnostic script that needs to monkeypatch/close
over a value from `execute_code`**: bind it as a default-argument value
instead of relying on closure —
`def fake(x, _captured=captured): ...` — default args are evaluated
eagerly at `def`-time and read back via `LOAD_FAST`, sidestepping the
global/local split entirely.
