# NS-03 acceptance contract: `stamp --check`

Source: northstar #3 (implemented; the source entry is deleted from NORTHSTARS.md per this contract's definition of done)
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)
Locked decisions: [D5](DECIDED.md#d5-stamp---check-follows-the---check-convention), [D3](DECIDED.md#d3-zero-runtime-dependencies)

## Required behavior

`stamp --check` computes exactly the edits `stamp` would make, reports them, and
**writes nothing**. Exit 0 if `stamp` would be a no-op, nonzero otherwise.

The `--check` convention this follows is `black --check` / `terraform fmt -check`
/ `prettier --check`: the question is only "would this change anything", not
"are the references correct". `check` answers correctness; this answers
staleness.

Report, per reference `stamp` would touch: file, line, target, and which case it
is - a pin that is absent (opted-in but unstamped) or a pin whose hex would be
rewritten.

Section 3 of [DECISIONS.md](../DECISIONS.md) already assigns this its purpose:
it is what makes an *advisory* pre-commit run useful, with enforcement at
pre-push. Do not re-argue gate placement.

## Explicitly out of scope

- Any change to `stamp`'s writing behavior.
- Any change to `check`.
- Re-blessing policy. Whether a `DRIFTED` reference *should* be re-stamped is
  northstar #10 and is human-owned. This item reports what `stamp` would do
  under today's rules, nothing more.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- Zero writes. The contract's central assertion is a filesystem one: mtime and
  bytes of every file in the tree are unchanged after a `--check` run.
- `stamp` without `--check` behaves exactly as today.
- The edits reported must be the edits `stamp` actually makes. Do not
  reimplement the computation - share the code path with `stamp` so the two
  cannot diverge.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `stamp-check-clean-exits-zero` | a fully stamped tree exits 0 and prints nothing actionable |
| `stamp-check-unstamped-exits-nonzero` | an opted-in unstamped pin exits nonzero and is named in the output |
| `stamp-check-stale-pin-exits-nonzero` | a pin whose target changed exits nonzero |
| `stamp-check-writes-nothing` | run `--check` on a dirty-in-reflock-terms tree, then assert every file is byte-identical, then run real `stamp` and assert it makes exactly the reported edits |
| `stamp-check-then-stamp-is-clean` | `stamp` followed by `stamp --check` exits 0 |

The fourth fixture is the important one. If the bench runner cannot compare file
bytes across steps, say so rather than weakening the assertion - that is a
finding about the harness, and it is worth a separate item.

## Unit tests to add

- `--check` on a tree needing no edits: exit 0.
- `--check` on a tree needing edits: exit nonzero, and the reported set equals
  the set `stamp` then writes.
- `--check` does not create, truncate, or rewrite any file.

## Verification

```
make gate
```

`suspects` is advisory and exits nonzero whenever it has
anything to say, so it is not part of the gate. Read its output, act on
anything real, but do not chain it.

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. README's "Three gates" section is updated - it currently promises an
   advisory-run story this item is what actually delivers. Re-stamp the file.
3. Northstar #3 is **deleted** from [NORTHSTARS.md](../NORTHSTARS.md).
4. `ROADMAP.yaml` marks NS-03 `done`.
