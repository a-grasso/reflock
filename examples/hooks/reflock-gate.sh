#!/usr/bin/env bash
# Claude Code Stop hook — block the agent from ENDING its turn while any
# cross-reference is broken, and hand the report back so it fixes them first.
#
# Register it in .claude/settings.json (see settings.snippet.json), then:
#   chmod +x .claude/hooks/reflock-gate.sh
#
# reflock must be runnable. Either put `reflock` on PATH, or point at the file:
#   export REFLOCK="python3 /abs/path/to/reflock.py"
#
# Not `set -e`: this script branches on reflock's exit code, and the difference
# between "found problems" and "could not run" is the whole point of it.
set -uo pipefail

input="$(cat)"

# Loop-guard: if the runner is already replaying us after a block, allow the
# stop — an unfixable state must not wedge the agent. (Claude Code also hard-caps
# consecutive blocks; raise it with CLAUDE_CODE_STOP_HOOK_BLOCK_CAP.)
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
reflock_cmd="${REFLOCK:-reflock}"

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
    exit 0    # references clean — let the agent finish
    ;;
  1)
    ;;        # references broken — fall through and block
  *)
    # reflock could not run: exit 2 (bad invocation, a --root that no longer
    # matches), or the command is missing entirely. It evaluated nothing, so
    # there is no evidence the docs are wrong — asking the agent to "fix
    # references" here sends it to repair a config error it cannot reach, and
    # it will thrash until the runner's block cap stops it. Fail open, loudly:
    # a broken gate the human can see beats a silent one, and beats a wedged
    # agent.
    printf 'reflock gate: skipped, `%s` exited %s (not a reference failure).\n' \
      "$reflock_cmd" "$status" >&2
    if [ -n "$diagnostic" ]; then
      printf '%s\n' "$diagnostic" >&2
    fi
    exit 0
    ;;
esac

# Block: exit 0 plus decision JSON on stdout, with the report fed back.
REFLOCK_GATE_REPORT="$report" python3 -c '
import json, os
print(json.dumps({
    "decision": "block",
    "reason": "reflock: cross-references are broken — fix them before finishing.\n\n"
              + os.environ["REFLOCK_GATE_REPORT"],
}))
'
exit 0
