"""
guards.py — the entire hmcp safety layer, in one reviewable file.

Design rule (see houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md, section 4):
the plugin runs inside the owner's Houdini process with full OS-level
access to the machine, including mounted studio shares. There is no
sandbox, no jail, no privilege boundary. The only barrier is which
functions exist in the code. So the rule here is: do not write the
dangerous capability at all, rather than write it and guard it.

Concretely: this file (and every other file in this package) must never
`import os`, `import shutil`, `import requests`, `import subprocess`,
`import zipfile`, and must never call `os.remove`/`unlink`/`rmtree` or
`open(..., "w")`. Paths are plain strings built from the constants below,
never from caller input.

Phase 1 is read-only, so nothing in this file is called yet -- it exists
now, as one reviewable unit, so Phase 2's write handlers only ever need
to *call* already-reviewed guard functions, never invent new ones.
"""

import re

# ---------------------------------------------------------------------------
# Sandbox boundary
# ---------------------------------------------------------------------------

SANDBOX_ROOT = "c:/houdini_mcp_sandbox/"
SNAPSHOT_DIR = "c:/houdini_mcp_sandbox/_snapshots/"  # must pre-exist; plugin never creates it

# Houdini's default path for a session that has never been saved. Used as a
# fallback for the "never saved" check if hou.hipFile.isNewFile() is ever
# unavailable (confirmed present in 21.0.596 via hython, but checked
# defensively here rather than assumed).
_DEFAULT_UNTITLED_PATH = "untitled.hip"


def _normalize(path):
    """Lowercase + forward-slash a hip path for prefix comparison. Windows
    paths are case-insensitive and Houdini mixes slash direction."""
    return path.replace("\\", "/").lower()


def is_never_saved_scene():
    """True if the open scene has never been saved to disk."""
    import hou

    if hasattr(hou.hipFile, "isNewFile"):
        try:
            return hou.hipFile.isNewFile()
        except Exception:
            pass
    # Fallback: compare against Houdini's default untitled filename.
    name = hou.hipFile.name() or ""
    return _normalize(name).endswith(_normalize(_DEFAULT_UNTITLED_PATH))


def is_sandbox_scene():
    """True if the open .hip lives under SANDBOX_ROOT."""
    import hou

    path = hou.hipFile.path() or ""
    return _normalize(path).startswith(_normalize(SANDBOX_ROOT))


def require_sandbox_scene():
    """Raise unless the open .hip lives under SANDBOX_ROOT.

    An unsaved/untitled scene is also refused -- this forces an explicit,
    saved sandbox scene before any write happens. `save_scene_as` is the
    single exception, and it does its own check (see
    `require_bootstrap_scene` below), never this one.
    """
    if not is_sandbox_scene():
        import hou

        raise PermissionError(
            f"Refused: this write command only runs when the open scene "
            f"lives under {SANDBOX_ROOT}. Current scene: "
            f"{hou.hipFile.path()!r}. Call save_scene_as() from a "
            f"never-saved scene to bootstrap into the sandbox."
        )


def require_bootstrap_scene():
    """Raise unless the scene is eligible for the one-time save_scene_as
    bootstrap: it must never have been saved.

    Deliberately NOT satisfied merely by being outside the sandbox: if a
    named production scene were open, save_scene_as would leave that file
    untouched on disk but would repoint the Houdini session at the sandbox
    copy -- the owner's next Ctrl+S would then silently go somewhere they
    did not expect. A genuinely new scene is required instead.
    """
    if not is_never_saved_scene():
        import hou

        raise PermissionError(
            f"Refused: save_scene_as only bootstraps a never-saved scene "
            f"into the sandbox. Current scene {hou.hipFile.path()!r} has "
            f"already been saved once -- open a fresh scene first."
        )


# ---------------------------------------------------------------------------
# Parameter whitelists
# ---------------------------------------------------------------------------

# Always refused, even inside the sandbox -- these are output/write paths.
OUTPUT_PATH_PARMS = {
    "outputimage", "picture", "vm_picture", "ar_picture", "lopoutput",
    "sopoutput", "dopoutput", "copoutput", "ropoutput", "usdfile",
    "savepath", "outputfile", "output", "basedir", "hdafile", "otlfile",
}

# The only file-type parms that may be set. This is an allowlist, not a
# heuristic: "contains the word file" would eventually let an output parm
# through, since `file` means different things on different node types.
INPUT_PATH_PARMS = {"file", "filepath"}

# VEX only. Never Python.
CODE_PARMS_ALLOWED = {"snippet", "vexpression"}

# ROP script parameters execute shell/HScript and are as dangerous as
# Python -- refused outright, same as Python parms.
CODE_PARMS_REFUSED = {
    "python", "script", "callback", "command", "precmd", "postcmd",
    "prerender", "postrender", "preframe", "postframe",
}

NODE_TYPES_REFUSED = {"python", "pythonscript", "unix", "shell"}

# Phase 1/2 restrict node creation to the categories the target domain
# (SOP-level procedural geometry and VEX) actually needs. The obj context's
# real category name is "Object", not "Obj" -- confirmed against
# plugin/server.py:766 (`target_node.type().category().name() != "Object"`),
# proven code from the old plugin. This was wrong at Phase 1 (unexercised,
# since Phase 1 is read-only) and would have silently refused every /obj
# node creation in Phase 2 -- fixed here before create_node's first caller.
ALLOWED_NODE_CATEGORIES = {"Sop", "Object"}


def check_creatable_node_type(type_name, category_name):
    """Raise unless a node of this type/category may be created."""
    if category_name not in ALLOWED_NODE_CATEGORIES:
        raise ValueError(
            f"Refused: node category '{category_name}' is outside the "
            f"Phase 1/2 target domain. Allowed: {sorted(ALLOWED_NODE_CATEGORIES)}."
        )
    if type_name.lower() in NODE_TYPES_REFUSED:
        raise ValueError(f"Refused: node type '{type_name}' is never creatable.")


def check_settable_parm(parm):
    """Raise unless this hou.Parm may be set by set_parm.

    Checks, in order: output-path names (always refused), code-bearing
    names (VEX allowed, Python/callback/script refused), then file-type
    parm templates (only the exact INPUT_PATH_PARMS names allowed -- any
    other file-type parm is refused even if its name looks harmless).
    """
    name = parm.name()
    lname = name.lower()

    if lname in OUTPUT_PATH_PARMS:
        raise ValueError(f"Refused: '{name}' is an output-path parameter.")

    if lname in CODE_PARMS_REFUSED:
        raise ValueError(f"Refused: '{name}' can hold Python/shell code.")

    if lname in CODE_PARMS_ALLOWED:
        return  # VEX snippet/vexpression -- fine, caller sets via set_expression too

    try:
        pt = parm.parmTemplate()
        is_file_type = pt is not None and pt.type().name() == "String" and pt.stringType().name() == "FileReference"
    except Exception:
        is_file_type = False

    if is_file_type and lname not in INPUT_PATH_PARMS:
        raise ValueError(
            f"Refused: '{name}' is a file-reference parameter not in the "
            f"input allowlist {sorted(INPUT_PATH_PARMS)}."
        )


def check_expression_language(language):
    """Raise unless the expression language is HScript. Never Python."""
    import hou

    if language != hou.exprLanguage.Hscript:
        raise ValueError("Refused: expressions may only use hou.exprLanguage.Hscript.")


# ---------------------------------------------------------------------------
# Session-scoped deletion registry
# ---------------------------------------------------------------------------


class SessionRegistry:
    """Tracks nodes created by the agent in the current session, keyed by
    `node.sessionId()` rather than path.

    Why sessionId and not path: a path breaks on rename/move (which the
    cosmetic commands allow), so the agent would lose the ability to
    delete its own work. Worse, Houdini reuses node names -- if a node is
    destroyed and a later, unrelated node ends up at the same path, a
    stale path-based registry entry would authorise deleting someone
    else's node. sessionId() is stable across rename/move and is never
    handed to a different node.

    Known limitation, and it fails safe: session ids do not survive a
    scene reload, so after a reload the agent loses delete rights over
    nodes it created earlier in the session.
    """

    def __init__(self):
        self._ids = set()

    def register_created(self, node):
        self._ids.add(node.sessionId())

    def can_delete(self, node):
        return node.sessionId() in self._ids

    def forget(self, node):
        self._ids.discard(node.sessionId())


# One registry per running plugin instance (module-level singleton, reset
# on every plugin reload / Houdini restart -- which is the safe direction
# for the "does not survive reload" limitation above).
session_registry = SessionRegistry()
