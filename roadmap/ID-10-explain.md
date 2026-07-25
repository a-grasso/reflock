# ID-10 acceptance contract: `reflock explain <file>:<line>`

Source: idea #10 in [IDEAS.md](../IDEAS.md)
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format), [D3](DECIDED.md#d3-zero-runtime-dependencies)
Depends on: FMT-01

## Required behavior

Everything about one reference, so nobody has to reconstruct it by hand from a
`check` line plus a manual diff.

```
$ reflock explain README.md:42
reference   README.md:42
target      DECISIONS.md#3-where-to-gate-and-what-each-gate-can-honestly-promise
resolves to DECISIONS.md
anchor      matched heading, lines 86-109
pin         a1b2c3d4
current     9f8e7d6c
verdict     DRIFTED
```

Then the unit text itself: what was fingerprinted. When pin and current differ,
show enough of both to be actionable rather than making the user go look.

- Argument form is `<file>:<line>`. A line with no reference exits nonzero with a
  message saying so.
- A line with more than one reference reports all of them, in column order.
  Multiple references per line already exist in the fixture set, so this is not
  hypothetical.
- Read-only. Never writes.
- Supports `--format` per D1.

## The one open question, decide and state it in the PR

When a reference is `DRIFTED`, the pinned text is not recoverable - only its
hash was stored, which is decision #2 in [DECISIONS.md](../DECISIONS.md) working
as intended. So `explain` can show the *current* unit text and both hashes, but
it cannot show what the text used to be.

Show the current unit text plus both hashes, and say plainly that the prior text
is not recoverable by design. Do **not** try to reconstruct it from git history:
that would reintroduce the commit-SHA coupling decision #2 exists to avoid, and
it would make a read-only command shell out to git.

## Explicitly out of scope

- Any writing, including offering to re-stamp. That is `stamp`.
- A diff view against git history, per the above.
- Accepting a bare file with no line number.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- No writes.
- Verdicts reported must match what `check` reports for the same reference.
  Two code paths computing verdicts would be a bug - reuse `classify`.
- Unit text shown is the same text `normalize` and `fingerprint` consume, so
  what the user reads is what was hashed.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `explain-ok-reference` | an `OK` pinned reference reports target, resolution, pin, current, verdict |
| `explain-drifted-shows-both-hashes` | a `DRIFTED` reference shows pin and current, and states prior text is unrecoverable |
| `explain-dangling` | a `DANGLING` reference explains why it failed to resolve |
| `explain-unpinned` | an unpinned reference is reported as such, with no hash comparison |
| `explain-multiple-refs-on-line` | a line with two references reports both in column order |
| `explain-no-reference-on-line` | exits nonzero with a clear message |
| `explain-verdict-matches-check` | the verdict equals what `check --format json` reports for the same reference |

The last one is the important fixture: it is what stops the two code paths
drifting.

## Unit tests to add

- Argument parsing: valid `file:line`, missing line, non-numeric line,
  out-of-range line.
- Anchor span reporting for a heading anchor and for a marker span.

## Verification

```
make test && make bench && make check && make suspects
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. Idea #10 is **deleted** from [IDEAS.md](../IDEAS.md).
3. README documents the subcommand, including the unrecoverable-prior-text point,
   since that will otherwise be reported as a bug.
4. `ROADMAP.yaml` marks ID-10 `done`.
