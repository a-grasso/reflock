#!/usr/bin/env bash
# Claude Code Stop hook — block the agent from ENDING its turn while any
# cross-reference is broken, and hand the report back so it fixes them first.
#
# Register it in .claude/settings.json (see settings.snippet.json), then:
#   chmod +x .claude/hooks/reflock-gate.sh
#
# reflock must be runnable. Either put `reflock` on PATH, or point at the file:
#   export REFLOCK="python3 /abs/path/to/reflock.py"
set -euo pipefail

input="$(cat)"

# Loop-guard: if the runner is already replaying us after a block, allow the
# stop — an unfixable state must not wedge the agent. (Claude Code also hard-caps
# consecutive blocks; raise it with CLAUDE_CODE_STOP_HOOK_BLOCK_CAP.)
if [ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false')" = "true" ]; then
  exit 0
fi

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
reflock_cmd="${REFLOCK:-reflock}"

if report="$($reflock_cmd check --root "$root" 2>&1)"; then
  exit 0  # references clean — let the agent finish
fi

# Broken — block (exit 0 + decision JSON on stdout) and feed the report back.
jq -cn --arg r "reflock: cross-references are broken — fix them before finishing.

$report" '{decision: "block", reason: $r}'
exit 0
