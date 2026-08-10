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

# The invocation is substituted by name rather than through str.format: the
# script is full of shell `${...}` and JSON `{...}`, and doubling every brace to
# survive .format() is exactly the kind of transcription hazard that lets this
# copy drift from examples/hooks/reflock-gate.sh unnoticed.
INVOCATION_SENTINEL = "__REFLOCK_INVOCATION__"

HOOK_SCRIPT_TEMPLATE = """\
#!/usr/bin/env bash
# Installed by `reflock setup claude` - re-run it after moving or
# reinstalling reflock to repair this path. Blocks the agent from ending its
# turn while any cross-reference is broken, and hands the report back so it
# fixes them first.
#
# Not `set -e`: this script branches on reflock's exit code, and the difference
# between "found problems" and "could not run" is the whole point of it.
set -uo pipefail

input="$(cat)"

# Loop-guard: if the runner is already replaying us after a block, allow the
# stop - an unfixable state must not wedge the agent. (Claude Code also
# hard-caps consecutive blocks; raise it with CLAUDE_CODE_STOP_HOOK_BLOCK_CAP.)
if [ "$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    print("true" if json.load(sys.stdin).get("stop_hook_active") else "false")
except Exception:
    print("false")
')" = "true" ]; then
  exit 0
fi

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
reflock_cmd="${REFLOCK:-__REFLOCK_INVOCATION__}"

# stdout and stderr are kept apart on purpose: a findings report handed to an
# agent must contain findings, not a diagnostic about reflock itself.
stderr_file="$(mktemp)"
trap 'rm -f "$stderr_file"' EXIT

# --root is a global flag: it must precede the subcommand. `check --root`
# is an argparse usage error, so this line spelled the other way round
# made every single invocation exit 2.
report="$($reflock_cmd --root "$root" check 2>"$stderr_file")"
status=$?
diagnostic="$(cat "$stderr_file")"

case "$status" in
  0)
    exit 0    # references clean - let the agent finish
    ;;
  1)
    ;;        # references broken - fall through and block
  *)
    # reflock could not run: exit 2 (bad invocation, a --root that no longer
    # matches), or the command is missing entirely. It evaluated nothing, so
    # there is no evidence the docs are wrong - asking the agent to "fix
    # references" here sends it to repair a config error it cannot reach, and
    # it will thrash until the runner's block cap stops it. Fail open, loudly:
    # a broken gate the human can see beats a silent one, and beats a wedged
    # agent.
    printf 'reflock gate: skipped, `%s check` exited %s (not a reference failure).\\n' \\
      "$reflock_cmd" "$status" >&2
    if [ -n "$diagnostic" ]; then
      printf '%s\\n' "$diagnostic" >&2
    fi
    exit 0
    ;;
esac

# Block: exit 0 plus decision JSON on stdout, with the report fed back.
REFLOCK_GATE_REPORT="$report" python3 -c '
import json, os
print(json.dumps({
    "decision": "block",
    "reason": "reflock: cross-references are broken — fix them before finishing.\\n\\n"
              + os.environ["REFLOCK_GATE_REPORT"],
}))
'
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
    return HOOK_SCRIPT_TEMPLATE.replace(INVOCATION_SENTINEL, invocation)


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
