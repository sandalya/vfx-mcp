# little_helpers

Self-contained Nuke artist tools for building and maintaining layer-branch
comps (see `docs/NUKE_COMP_LAYER_ASSEMBLY.md` in the parent repo for the
comp pattern these tools assume). No MCP, no network, no server -- this
package never opens a socket and never talks to anything outside the Nuke
session it's running in.

## What's here

| Tool | Hotkey | What it does |
| --- | --- | --- |
| Create Layer Branch | `Shift+A` | Lists layer-branch folders under `$FTRACK_RENDER_PATH`, freshest first. Pick one to build the 4-Read (lights/beauty/tech/crypto) assembly chain for it. |
| Change Layer Version | `Shift+E` | Jump to latest / step version up / step version down on the selected Read node(s) (or, if nothing's selected, whatever Reads are visible in the Node Graph). Optional "History" checkbox keeps a row of old-version reference Reads in sync next to the live one. |
| Split Layers | `F10` | Sashok's per-lightgroup comp splitter, standalone. Also reachable as a checkbox inside the Create Layer Branch panel, which runs it on the branch it just built. |

## Install

1. Copy the whole `little_helpers/` folder into `~/.nuke/` (i.e. it should
   end up on `NUKE_PATH` as `<...>/.nuke/little_helpers/`).
2. Add two lines to `~/.nuke/menu.py`:

   ```python
   import little_helpers
   little_helpers.register_menu()
   ```

3. Restart Nuke. The three tools appear under the `Little Helpers` menu in
   the Node Graph, with the hotkeys above.

That's the entire install. Nothing else needs to run, nothing else needs
to be configured, and nothing in this package binds a port or reaches
outside the Nuke process.

## Notes

- Menu registration is idempotent -- `register_menu()` can be called again
  (e.g. after a `reload_all()`) without piling up duplicate menu entries.
- `reload_all()` is a dev-loop convenience: it reloads every submodule of
  this package (in dependency order) plus the package itself, so edited
  code goes live on the next hotkey press without restarting Nuke. Not
  needed for normal use -- Nuke's own module caching handles everything
  once the package is installed and Nuke is running.
