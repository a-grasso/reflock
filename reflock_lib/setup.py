"""`reflock setup claude` - installs/repairs the Stop-hook gate that blocks an
agent from finishing while references are broken, promoting
examples/hooks/reflock-gate.sh from copy-paste material to an idempotent
command (AXI principle 7's "explicit setup command").
"""
from __future__ import annotations

import json
import os
import shutil
import sys

import reflock_lib
from reflock_lib.engine import repo_root

STOP_HOOK_COMMAND = '"$CLAUDE_PROJECT_DIR"/.claude/hooks/reflock-gate.sh'

HOOK_SCRIPT_TEMPLATE = """\
#!/usr/bin/env bash
# Installed by `reflock setup claude` - re-run it after moving or
# reinstalling reflock to repair this path. Blocks the agent from ending its
# turn while any cross-reference is broken, and hands the report back so it
# fixes them first.
set -euo pipefail

input="$(cat)"

# Loop-guard: if the runner is already replaying us after a block, allow the
# stop - an unfixable state must not wedge the agent. (Claude Code also
# hard-caps consecutive blocks; raise it with CLAUDE_CODE_STOP_HOOK_BLOCK_CAP.)
if [ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false')" = "true" ]; then
  exit 0
fi

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
reflock_cmd="${{REFLOCK:-{invocation}}}"

if report="$($reflock_cmd check --root "$root" 2>&1)"; then
  exit 0
fi

jq -cn --arg r "reflock: cross-references are broken — fix them before finishing.

$report" '{{decision: "block", reason: $r}}'
exit 0
"""


def _reflock_py_path() -> str:
    """The real path to reflock.py, the sibling of this package - resolved
    through __file__ rather than sys.argv[0], so it is invocation-independent
    (a symlink, `python3 reflock.py`, and an in-process call all agree) and
    correct even when reflock is imported rather than run as a script, as
    every test in this suite does."""
    lib_dir = os.path.dirname(os.path.realpath(reflock_lib.__file__))
    return os.path.join(os.path.dirname(lib_dir), "reflock.py")


def reflock_invocation() -> str:
    """The command a generated hook script should run: bare `reflock` if
    that name resolves via PATH to this same install (AXI's "portable
    commands" rule), otherwise a portable absolute invocation through the
    current interpreter, so it works with no execute bit and no PATH entry."""
    current = _reflock_py_path()
    on_path = shutil.which("reflock")
    if on_path and os.path.realpath(on_path) == current:
        return "reflock"
    return f"{sys.executable} {current}"


def render_hook_script(invocation: str) -> str:
    return HOOK_SCRIPT_TEMPLATE.format(invocation=invocation)


def add_stop_hook(settings: dict) -> dict:
    """`settings` with the Stop hook merged in, or `settings` itself
    (same object) if a Stop entry for STOP_HOOK_COMMAND is already there -
    the idempotency check a caller uses via `result is settings`. Never
    mutates its input; every other key (other hook types, permissions, ...)
    is carried over untouched."""
    for entry in settings.get("hooks", {}).get("Stop", []):
        for h in entry.get("hooks", []):
            if h.get("command") == STOP_HOOK_COMMAND:
                return settings
    updated = dict(settings)
    hooks = dict(updated.get("hooks", {}))
    hooks["Stop"] = list(hooks.get("Stop", [])) + [
        {"matcher": "", "hooks": [{"type": "command", "command": STOP_HOOK_COMMAND}]}
    ]
    updated["hooks"] = hooks
    return updated


def cmd_setup(args) -> int:
    from reflock_lib.commands import render_error

    root = repo_root(args.root)
    claude_dir = os.path.join(root, ".claude")
    hook_path = os.path.join(claude_dir, "hooks", "reflock-gate.sh")
    settings_path = os.path.join(claude_dir, "settings.json")

    script = render_hook_script(reflock_invocation())
    os.makedirs(os.path.dirname(hook_path), exist_ok=True)
    existing = None
    if os.path.exists(hook_path):
        with open(hook_path, encoding="utf-8") as fh:
            existing = fh.read()
    if existing == script:
        print(".claude/hooks/reflock-gate.sh unchanged")
    else:
        with open(hook_path, "w", encoding="utf-8") as fh:
            fh.write(script)
        os.chmod(hook_path, 0o755)
        print(("wrote" if existing is None else "updated") + " .claude/hooks/reflock-gate.sh")

    if os.path.exists(settings_path):
        with open(settings_path, encoding="utf-8") as fh:
            text = fh.read()
        try:
            settings = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as e:
            render_error(f".claude/settings.json is not valid JSON: {e}", "human")
            return 2
    else:
        os.makedirs(claude_dir, exist_ok=True)
        settings = {}
    updated = add_stop_hook(settings)
    if updated is settings:
        print(".claude/settings.json already has the Stop hook")
    else:
        with open(settings_path, "w", encoding="utf-8") as fh:
            json.dump(updated, fh, indent=2)
            fh.write("\n")
        print("added Stop hook to .claude/settings.json")
    return 0
