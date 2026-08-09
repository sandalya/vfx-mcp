"""
commands.py — one dispatcher registry: command name -> {handler, params, kind}.

Built from commands_spec.COMMANDS so there is exactly one place that
declares a command name (commands_spec.py) and exactly one place that
binds it to code (the _HANDLERS map below). This is the structural fix
for the bug that broke the old plugin: `connect_nodes` was wired into the
bridge's tool list but the plugin's dispatcher had no matching entry,
and nothing caught the mismatch until a human noticed. `_build_registry`
raises immediately if commands_spec and _HANDLERS disagree, and
scripts/check_contract.py catches the same class of drift from outside,
against the live running server.
"""

from . import build
from . import commands_spec
from . import intro

# The only hand-maintained mapping in this file: command name -> Python
# callable. Every name here must also appear in commands_spec.COMMANDS,
# and vice versa -- `_build_registry` enforces that at import time.
_HANDLERS = {
    "get_scene_info": intro.get_scene_info,
    "get_geometry_info": intro.get_geometry_info,
    "get_node_errors": intro.get_node_errors,
    "get_node_type_parms": intro.get_node_type_parms,
    "list_node_types": intro.list_node_types,
    "get_node_help": intro.get_node_help,
    "get_network": intro.get_network,
    "get_node_info": intro.get_node_info,
    "describe_commands": intro.describe_commands,
    # Phase 2: write commands (guarded, sandbox-only -- see build.py).
    "create_node": build.create_node,
    "connect_nodes": build.connect_nodes,
    "set_parm": build.set_parm,
    "set_expression": build.set_expression,
    "delete_node": build.delete_node,
    "rename_node": build.rename_node,
    "set_position": build.set_position,
    "set_color": build.set_color,
    "set_comment": build.set_comment,
    "layout_children": build.layout_children,
    "set_display_flag": build.set_display_flag,
    "set_render_flag": build.set_render_flag,
    "set_bypass": build.set_bypass,
    "save_scene_as": build.save_scene_as,
    "viewport_snapshot": build.viewport_snapshot,
}


def _build_registry():
    registry = {}
    declared = {spec["name"] for spec in commands_spec.COMMANDS}

    for spec in commands_spec.COMMANDS:
        name = spec["name"]
        handler = _HANDLERS.get(name)
        if handler is None:
            raise RuntimeError(
                f"commands_spec declares '{name}' but commands.py's "
                f"_HANDLERS has no entry for it. Fix before starting the server."
            )
        registry[name] = {"handler": handler, "params": spec["params"], "kind": spec["kind"]}

    extra = set(_HANDLERS) - declared
    if extra:
        raise RuntimeError(
            f"commands.py's _HANDLERS has entries not declared in "
            f"commands_spec: {sorted(extra)}. Add them to commands_spec.py first."
        )

    return registry


REGISTRY = _build_registry()
