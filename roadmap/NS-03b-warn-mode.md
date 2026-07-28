# NS-03b acceptance contract: `stamp --check --warn`, so the advisory hook is advisory

Source: review 2026-07-28; resolution chosen by a human on the same day
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [.pre-commit-hooks.yaml](../.pre-commit-hooks.yaml), [README.md](../README.md), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D5](DECIDED.md#d5-stamp---check-follows-the---check-convention), [D6](DECIDED.md#d6-the-shipped-pre-commit-manifest-is-advisory), [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The conflict this resolves

D6 is titled *"The shipped pre-commit manifest is advisory"* and ends *"Do not
ship a hook that hard-fails a commit by default."* The shipped manifest declares
`reflock-stamp-check` with `verbose: true` at `stages: [pre-push]`, and it
hard-fails a push whenever any pin is opted-in but unstamped - a routine
intermediate state.

ID-21 reasoned that pre-push was *the only way* to honor D6, because pre-commit
has no warn-only mode. That reasoning was sound about pre-commit and incomplete
about reflock: a hook is only as blocking as the command it runs, and reflock had
no exit-0 reporting mode to offer it. The existing unit test encodes the
workaround as the principle - its docstring says "the only way to honor D6 is to
default both hooks to pre-push" - so this item has to correct the test too.

A human chose this resolution over amending D6: give reflock a genuinely advisory
mode, so D6 is satisfied as written rather than rewritten to match what was
built.

## Required behavior

### `--warn`

`reflock stamp --check --warn` reports exactly what `stamp --check` reports and
**always exits 0**.

- stdout is byte-identical to `stamp --check`'s for the same tree. The flag
  changes the exit code, nothing else - it is not a second output format.
- It writes nothing, like `--check`.
- `--warn` without `--check` is a usage error, exit 2. Plain `stamp` already
  exits 0, so the flag would be meaningless there, and silently accepting it
  would imply it did something.

This does not weaken D5. `stamp --check` keeps its `black --check` exit
semantics; `--warn` is an explicit opt out for callers that want the report
without the verdict, which is exactly what an advisory hook is.

### The manifest

With something non-blocking to call, the manifest can finally say what
DECISIONS.md section 3 always described - advisory at commit time, enforcement
at push time:

| Hook | Entry | Stage | Blocks? |
|---|---|---|---|
| `reflock-stamp-check` | `stamp --check --warn` | `pre-commit` | never |
| `reflock-check` | `check` | `pre-push` | yes |

`reflock-stamp-check` moves *to* `pre-commit` precisely because it can no longer
fail: commit time is where the advice is useful, and D6's prohibition was on
hard-failing a commit, not on speaking during one. `verbose: true` stays, since
pre-commit hides a passing hook's output without it.

`reflock-check` stays at pre-push and stays enforcing, unchanged.

## Authorized test change

`test_no_hook_blocks_a_commit_by_default` currently asserts no hook names
`pre-commit` at all. That is a proxy for the real invariant, and it was the
right proxy only while every hook could fail. Replace it with the invariant
itself:

> **no hook that can fail runs at `pre-commit`** - a hook at that stage must
> invoke a command that cannot exit nonzero (`--warn`)

That is strictly stronger: it still forbids today's `reflock-check` from
appearing at pre-commit, and it keeps forbidding a future blocking hook from
being added there, while permitting the advisory one D6 asks for.

## Explicitly out of scope

- `--warn` on `check`. `check` is the enforcing gate; an exit-0 mode for it
  would be a way to run CI that cannot fail. If someone wants that they can
  append `|| true` themselves and own it.
- Changing `stamp --check`'s exit codes or output.
- Re-arguing gate placement generally (D5 forbids it). This item moves one hook
  because its blocking behavior changed, not because the gate story changed.

## Invariants

- Existing unit tests and evalbench fixtures stay green unmodified, except the
  one named above.
- `stamp --check` without `--warn` behaves exactly as today, exit codes
  included.
- Neither mode writes anything.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `stamp-check-warn-exits-zero` | a tree with an unstamped pin: `--check` exits 1, `--check --warn` exits 0, and the report still names the pin |
| `stamp-check-warn-stdout-identical` | `--check --warn`'s stdout is byte-identical to `--check`'s |
| `stamp-check-warn-writes-nothing` | the tree is byte-identical after `--check --warn` |
| `stamp-warn-without-check-is-an-error` | `stamp --warn` exits 2 and says so on stderr |

## Unit tests to add

- `--check --warn` on a tree needing edits: exit 0, report non-empty.
- `--check --warn` on a clean tree: exit 0 (unchanged from `--check`).
- `--check --warn` stdout equals `--check` stdout for the same tree.
- `stamp --warn` without `--check`: exit 2, message names both flags.
- `--check --warn` writes nothing.
- Manifest: `reflock-stamp-check`'s entry passes `--warn`; `reflock-check`'s
  does not.
- Manifest: `reflock-stamp-check` runs at `pre-commit`, `reflock-check` does
  not.
- Manifest invariant (the replacement test): every hook whose stages include
  `pre-commit` invokes `--warn`.

## Verification

```
make gate
```

Plus a real `pre-commit try-repo` run of both hooks, as ID-21's contract
required - a manifest that parses but does not run is this file's whole risk.

## Definition of done

1. Fixtures and tests above pass; the one authorized test change is made and
   its docstring states the new invariant.
2. README's pre-commit section documents the two stages and that
   `reflock-stamp-check` cannot fail. Re-stamp the file.
3. `roadmap/ID-21-pre-commit-manifest.md` gets a note pointing at this item, so
   its amendment no longer reads as the final word on D6.
4. `ROADMAP.yaml` marks NS-03b `done`.
