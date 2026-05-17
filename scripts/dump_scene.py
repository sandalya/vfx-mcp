"""
Offline full-scene dump as a workaround for MCP token limits.

Run inside Houdini Python Shell on pc137 (uses `hou` module). Writes
two JSON files with every node under /stage and /obj plus their
non-default parameters.

Why: get_node_info via MCP is fine for inspecting a handful of nodes,
but a 332-node /stage walk at ~80 non-default parms each blows past
the model's token budget. This script does the same diff offline and
produces files that CC can read locally for offline analysis.

Original script came from CD via forward_to_cc (inbox 2026-05-17),
formalized here as a reusable tool.

Usage in Houdini Python Shell:

    exec(open(r"C:/path/to/dump_scene.py").read())

or copy the body into the shell directly. Output paths can be edited
at the bottom (default writes to C:/houdini_mcp_sandbox/).
"""

import hou
import json
from pathlib import Path


def parm_diff(node):
    """Return dict of parm-name -> {value, default, [raw]} for parms that differ from defaults."""
    out = {}
    for p in node.parms():
        try:
            tpl = p.parmTemplate()
            default = tpl.defaultValue()
            if isinstance(default, tuple) and len(default) == 1:
                default = default[0]
            v = p.eval()
            unexp = p.unexpandedString() if tpl.dataType() == hou.parmData.String else None
            is_diff = v != default
            if isinstance(v, float) and isinstance(default, (int, float)):
                is_diff = abs(v - default) > 1e-9
            if is_diff or (unexp and unexp != str(default)):
                entry = {"value": v, "default": default}
                if unexp and unexp != str(v):
                    entry["raw"] = unexp
                out[p.name()] = entry
        except Exception as e:
            out[p.name()] = {"error": str(e)}
    return out


def node_dump(node):
    """Serialize one node defensively."""
    return {
        "path": node.path(),
        "type": node.type().name(),
        "category": node.type().category().name(),
        "bypassed": node.isBypassed() if hasattr(node, "isBypassed") else None,
        "color": list(node.color().rgb()) if hasattr(node, "color") else None,
        "inputs": [
            {"index": i, "path": inp.path()}
            for i, inp in enumerate(node.inputs()) if inp
        ],
        "outputs": [
            {"path": c.outputNode().path()}
            for c in node.outputConnections()
            if hasattr(node, "outputConnections") and c.outputNode()
        ] if hasattr(node, "outputConnections") else [],
        "parms_non_default": parm_diff(node),
    }


def crawl(root_path, output_file):
    """Walk one top-level context (e.g. /stage) and dump every direct child."""
    root = hou.node(root_path)
    if not root:
        print(f"!!! {root_path} not found")
        return
    data = {"root": root_path, "nodes": []}
    for n in root.children():
        try:
            data["nodes"].append(node_dump(n))
        except Exception as e:
            data["nodes"].append({"path": n.path(), "error": str(e)})
    Path(output_file).write_text(json.dumps(data, indent=2, default=str))
    print(f"Wrote {len(data['nodes'])} nodes to {output_file}")


if __name__ == "__main__" or "hou" in dir():
    crawl("/stage", "C:/houdini_mcp_sandbox/stage_dump.json")
    crawl("/obj",   "C:/houdini_mcp_sandbox/obj_dump.json")
