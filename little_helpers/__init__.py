"""
little_helpers

Self-contained Nuke artist tools: Create Layer Branch (Shift+A), Change
Layer Version (Shift+E), Split Layers (F10). No MCP, no network, no
server -- copy this folder into ~/.nuke/ and call register_menu() from
menu.py. See README.md for the two-line install.

Invariant: this package imports nothing outside itself. Anything that
wants to use it imports it -- never the other way around.
"""

import nuke

from .layer_picker_ui import show_layer_picker
from .version_ui import show_version_hud

__version__ = "0.1.0"

LAYER_PICKER_MENU_PATH = "Little Helpers/Create Layer Branch"
VERSION_HUD_MENU_PATH = "Little Helpers/Change Layer Version"
SPLIT_LAYERS_MENU_PATH = "Little Helpers/Split Layers"


# ---- Split layers hookup (Function 1 checkbox + standalone F10) ---------
# Calls the standalone split_layers tool (little_helpers/split_layers/)
# unmodified -- per Sashok's explicit ask, this is thin glue only (optional
# node selection + the call), no split_layers logic ported in here.
# Isolating *which* layers to split stays manual, inside that tool's own
# panel.

def run_split_layers(node):
    """Function 1's "Split layers" checkbox -- selects `node` (the branch's
    last node) before launching the tool on it."""
    from .split_layers import split_layers
    for n in nuke.allNodes():
        n.setSelected(False)
    node.setSelected(True)
    split_layers.main()


def show_split_layers():
    """F10 -- standalone entry point, runs on whatever is already selected."""
    from .split_layers import split_layers
    split_layers.main()


def register_menu():
    """Idempotent -- safe to call repeatedly without piling up duplicate
    menu entries (removes each old item first, if present)."""
    menu = nuke.menu("Nodes")

    if menu.findItem(LAYER_PICKER_MENU_PATH):
        menu.removeItem(LAYER_PICKER_MENU_PATH)
    menu.addCommand(
        LAYER_PICKER_MENU_PATH,
        "import little_helpers; little_helpers.reload_all(); "
        "little_helpers.show_layer_picker()",
        "shift+a",
    )

    if menu.findItem(VERSION_HUD_MENU_PATH):
        menu.removeItem(VERSION_HUD_MENU_PATH)
    menu.addCommand(
        VERSION_HUD_MENU_PATH,
        "import little_helpers; little_helpers.reload_all(); "
        "little_helpers.show_version_hud()",
        "shift+e",
    )

    if menu.findItem(SPLIT_LAYERS_MENU_PATH):
        menu.removeItem(SPLIT_LAYERS_MENU_PATH)
    menu.addCommand(
        SPLIT_LAYERS_MENU_PATH,
        "import little_helpers; little_helpers.reload_all(); "
        "little_helpers.show_split_layers()",
        "F10",
    )


_RELOAD_ORDER = (
    "nuke_utils", "hud", "layer_branch", "versions",
    "layer_picker_ui", "version_ui",
    "split_layers.models", "split_layers.uii",
    "split_layers.nuke_actions", "split_layers.split_layers",
)


def reload_all():
    """Dev loop: reload every submodule bottom-up, then this package, so the
    menu command strings pick up new code without restarting Nuke. Order
    matters -- a module must be fresh before its importers rebind from it."""
    import importlib, sys
    for name in _RELOAD_ORDER:
        mod = sys.modules.get(f"{__name__}.{name}")
        if mod is not None:
            importlib.reload(mod)
    importlib.reload(sys.modules[__name__])
