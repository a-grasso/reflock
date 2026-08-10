# AGT-04 acceptance contract: the Stop hook must not send an agent to repair a config error

Source: this contract
Owner: agent · Tier: near · Touches: [examples/hooks/reflock-gate.sh](../../examples/hooks/reflock-gate.sh), [reflock_lib/commands.py](../../reflock_lib/commands.py) (`setup claude`)
Locked decisions: —
Depends on: —

## The bug

[reflock-gate.sh](../../examples/hooks/reflock-gate.sh) does:

```sh
if report="$($reflock_cmd check --root "$root" 2>&1)"; then
  exit 0
fi
# ...anything nonzero...
jq -cn --arg r "reflock: cross-references are broken — fix them before finishing.

$report" '{decision: "block", reason: $r}'
```

Any nonzero exit blocks, with stderr folded into the reason. So exit **2** -
reflock could not run: bad flag combination, a `--root` pointing at a tree that
no longer matches, a stale `REFLOCK` path - tells the agent *"cross-references
are broken, fix them before finishing"* and hands it an error message as the
repair task. The agent then edits documents to fix a problem that is not in the
documents, until Claude Code's consecutive-block cap stops it.

[manual.md](../manual.md) calls the 1-vs-2 distinction "the one CI cares
about". The flagship agent integration is the one caller that ignores it. This
is a live bug in shipped example code, not a design gap.

## Required behavior

The gate branches on the exit code, capturing the streams separately:

- **0** - allow the stop, as today.
- **1** - block, as today, with the findings report. Unchanged wording.
- **2** - **do not** ask the agent to fix references. reflock did not evaluate
  anything, so there is no evidence the docs are wrong and blocking on a repair
  the agent cannot perform is strictly worse than not gating. Allow the stop and
  emit a clearly-labelled warning to stderr naming the exit code and reflock's
  own message, so the human sees a broken gate rather than a silent one.
- **command not found / not executable** - same as 2. A hook whose tool is
  missing must fail open and say so, not wedge the turn.

Also required:

- Stop folding stderr into the block reason. Capture stdout for the report;
  surface stderr on the warning path. A findings report handed to an agent
  should contain findings.
- `jq` is a hard dependency of this script and is undeclared. Either check for
  it up front and fail open with a named message, or drop it - the emitted JSON
  is two fixed keys and the input parse is one boolean field, both of which are
  reachable with `python3`, which reflock already requires. Prefer dropping it:
  a gate that silently no-ops on a machine without `jq` is the same class of
  failure this item is fixing.
- The loop-guard on `stop_hook_active` stays exactly as it is.
- Whatever `reflock setup claude` installs must be the fixed script. If that
  subcommand embeds a copy of the gate rather than reading
  [examples/hooks/](../../examples/hooks/), fixing one and not the other ships
  the bug to everyone who followed the documented path; check both.

## Explicitly out of scope

- Gating on a *subset* of verdicts (e.g. block on DANGLING, allow UNSTAMPED).
  Defensible, but it is a policy decision about what "done" means and belongs to
  a human.
- Consuming `--format json` in the hook. The block reason is read by a model, so
  the human report is the right input; AGT-01 does not change that.
- Making the gate configurable (env var for scope, verdicts, or root).
- Hooks for any other agent runner.

## Invariants

- Exit-0 and exit-1 behavior byte-identical to today, including the block reason
  wording.
- No new runtime dependency for the script beyond what reflock already needs
  (D3 in spirit: the hook is part of the distributed surface).
- `reflock setup claude` stays idempotent and safe to re-run (ID-22).

## Fixtures to add

The gate is shell, not reflock, so evalbench does not reach it directly. Add
what does:

| Fixture | Asserts |
|---|---|
| `setup-claude-installs-current-gate` | the script `setup claude` writes matches `examples/hooks/reflock-gate.sh` byte-for-byte (this is the divergence guard, and it is the whole reason the item touches `commands.py`) |

## Unit tests to add

Drive the script directly with a stub `reflock` on PATH that exits with a chosen
code and writes chosen streams:

- exit 0 → script exits 0, stdout empty (no decision JSON).
- exit 1 → stdout is `{"decision": "block", ...}` whose reason contains the
  stub's stdout findings and **not** its stderr.
- exit 2 → no `decision: block` anywhere in stdout; script exits 0; stderr names
  the exit code and the underlying message.
- missing binary → same shape as exit 2.
- `stop_hook_active: true` → exits 0 without invoking reflock at all.

If the harness cannot host a shell test today, say so and propose where it goes
rather than dropping the coverage - an untested hook is how this bug shipped.

## Verification

```
just gate
```

Additionally: run the real hook against a repo with a genuine DANGLING reference
and confirm the agent is blocked; then run it with `REFLOCK="python3 /nope.py"`
and confirm the turn ends with a visible warning and no repair instruction.
Paste both in the PR body. This item is about behavior under misconfiguration,
which passing tests are especially good at not proving.

## Definition of done

1. Tests above pass; the exit-2 path is covered.
2. `setup claude` installs the fixed script, verified by fixture.
3. [manual.md](../manual.md)'s Stop hook section documents the fail-open
   behavior on exit 2 - a gate that can decline to gate must say when. Re-stamp.
4. `ROADMAP.yaml` marks AGT-04 `done`.
