"""
commands_spec.py — single declaration of hmcp command names and parameters.

This exists to structurally prevent the bug that broke the old plugin:
the bridge and the plugin each maintained their own command list, and
`connect_nodes` was wired into one but not the other.

Imported by:
  - houdini/bridge/hmcp_bridge.py   -- builds MCP tool wrappers from this,
    then asserts its registered tool names match COMMANDS exactly.
  - houdini/plugin/hmcp/commands.py -- builds the dispatcher registry from
    this, binding each name to its handler in intro.py / build.py.
  - scripts/check_contract.py       -- diffs the live plugin's
    `describe_commands` response against this list.

Deliberately has no `hou` / `fastmcp` / `mcp` imports so it can be loaded
by all three contexts (inside Houdini, in the bridge's plain Python, and
by a standalone contract-check script) without extra dependencies.

`params` values are human-readable type/default annotations for docs and
the contract check -- not enforced schemas.
"""

# Phase 1: read-only commands, available in any scene (no sandbox
# requirement). Phase 2 will append write commands here.
COMMANDS = [
    {
        "name": "get_scene_info",
        "kind": "read",
        "params": {
            "max_nodes": "int = 100",
            "context_filter": "list[str] | None = None",
        },
        "doc": "Current .hip file name/path and a sample of top-level nodes.",
    },
    {
        "name": "get_geometry_info",
        "kind": "read",
        "params": {"node_path": "str"},
        "doc": (
            "npoints/nprims/nvertices, attribute list (point/prim/vertex/"
            "detail), group names, bounding box, cook errors/warnings, "
            "cook time for a SOP node. The core tool: without it the agent "
            "builds a SOP graph blind."
        ),
    },
    {
        "name": "get_node_errors",
        "kind": "read",
        "params": {"node_path": "str"},
        "doc": "Errors, warnings, and cook state for a node.",
    },
    {
        "name": "get_node_type_parms",
        "kind": "read",
        "params": {"type_name": "str", "category": "str"},
        "doc": (
            "Parameter names/labels/types/defaults/menu items for a node "
            "type, from parmTemplates() -- how the agent looks up real "
            "parameter names instead of recalling them."
        ),
    },
    {
        "name": "list_node_types",
        "kind": "read",
        "params": {"category": "str", "name_filter": "str | None = None"},
        "doc": "Node type names available in a category, optionally filtered.",
    },
    {
        "name": "get_node_help",
        "kind": "read",
        "params": {"type_name": "str", "category": "str", "max_chars": "int = 4000"},
        "doc": "Built-in help text for a node type, truncated to max_chars.",
    },
    {
        "name": "get_network",
        "kind": "read",
        "params": {"parent_path": "str"},
        "doc": "Children of a network node plus their input connections.",
    },
    {
        "name": "get_node_info",
        "kind": "read",
        "params": {
            "path": "str",
            "max_parms": "int | None = None",
            "only_non_default": "bool = False",
        },
        "doc": "Detailed single-node info: parms, inputs, outputs, flags.",
    },
    {
        "name": "describe_commands",
        "kind": "read",
        "params": {},
        "doc": (
            "Returns this same command list as the live plugin sees it -- "
            "used by scripts/check_contract.py to catch bridge/plugin drift."
        ),
    },
    # Phase 2: write commands. Every one requires the open scene to already
    # live under the sandbox (guards.require_sandbox_scene) -- except
    # save_scene_as, the one-time bootstrap out of a never-saved scene.
    {
        "name": "create_node",
        "kind": "write",
        "params": {
            "parent_path": "str",
            "node_type": "str",
            "name": "str | None = None",
        },
        "doc": (
            "Create a node under parent_path. Category is derived from the "
            "parent, restricted to Sop/Object (guards.ALLOWED_NODE_CATEGORIES). "
            "No parameters dict -- use set_parm afterwards. Registers the new "
            "node so delete_node can remove it later this session."
        ),
    },
    {
        "name": "connect_nodes",
        "kind": "write",
        "params": {
            "from_path": "str",
            "to_path": "str",
            "input_index": "int = 0",
        },
        "doc": "Wire from_path's output into to_path's input_index-th input.",
    },
    {
        "name": "set_parm",
        "kind": "write",
        "params": {"node_path": "str", "parm_name": "str", "value": "any"},
        "doc": (
            "Set a single parameter value. Refuses output-path parms "
            "(sopoutput etc.), Python/callback/script parms, and any "
            "file-type parm other than file/filepath -- see "
            "guards.check_settable_parm."
        ),
    },
    {
        "name": "set_expression",
        "kind": "write",
        "params": {"node_path": "str", "parm_name": "str", "expression": "str"},
        "doc": "Set an HScript expression on a parameter. Never Python.",
    },
    {
        "name": "delete_node",
        "kind": "write",
        "params": {"node_path": "str"},
        "doc": (
            "Destroy a node -- only if the agent created it earlier this "
            "session (guards.session_registry, keyed on sessionId())."
        ),
    },
    {
        "name": "rename_node",
        "kind": "write",
        "params": {"node_path": "str", "new_name": "str"},
        "doc": "Rename a node.",
    },
    {
        "name": "set_position",
        "kind": "write",
        "params": {"node_path": "str", "x": "float", "y": "float"},
        "doc": "Set a node's network-view position.",
    },
    {
        "name": "set_color",
        "kind": "write",
        "params": {"node_path": "str", "r": "float", "g": "float", "b": "float"},
        "doc": "Set a node's network-view color.",
    },
    {
        "name": "set_comment",
        "kind": "write",
        "params": {"node_path": "str", "comment": "str"},
        "doc": "Set a node's comment text.",
    },
    {
        "name": "layout_children",
        "kind": "write",
        "params": {"parent_path": "str"},
        "doc": "Auto-layout a network's children (parent.layoutChildren()).",
    },
    {
        "name": "set_display_flag",
        "kind": "write",
        "params": {"node_path": "str", "on": "bool"},
        "doc": "Set/clear a node's display flag.",
    },
    {
        "name": "set_render_flag",
        "kind": "write",
        "params": {"node_path": "str", "on": "bool"},
        "doc": "Set/clear a node's render flag.",
    },
    {
        "name": "set_bypass",
        "kind": "write",
        "params": {"node_path": "str", "on": "bool"},
        "doc": "Set/clear a node's bypass flag.",
    },
    {
        "name": "save_scene_as",
        "kind": "write",
        "params": {},
        "doc": (
            "Bootstrap a never-saved scene into the sandbox. No arguments -- "
            "the plugin generates C:/houdini_mcp_sandbox/mcp_<timestamp>.hip. "
            "The only write command that runs outside require_sandbox_scene "
            "(gated instead by require_bootstrap_scene: never-saved only)."
        ),
    },
    {
        "name": "viewport_snapshot",
        "kind": "write",
        "params": {},
        "doc": (
            "OpenGL viewport snapshot of the current SceneViewer. No "
            "arguments -- writes to a generated path under "
            "C:/houdini_mcp_sandbox/_snapshots/ (must pre-exist)."
        ),
    },
]

COMMAND_NAMES = {c["name"] for c in COMMANDS}
