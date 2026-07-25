# ID-13 acceptance contract: quiet mode

Source: idea #13 in [IDEAS.md](../IDEAS.md)
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format)
Depends on: FMT-01

## Correction to the idea entry

IDEAS.md #13 says quiet mode "suppresses the per-reference `OK` noise". That is
**already the default** - `check` only lists `OK` references under `--verbose`.
The entry predates that flag. Do not implement what the entry describes; implement
what is below, and fix the entry as part of the work.

## Required behavior

`check -q` / `check --quiet`:

- Prints nothing on success. Exit 0, empty stdout, empty stderr.
- On failure, prints one summary line to **stderr** and nothing to stdout, then
  exits nonzero:

```
reflock: 1 of 137 references failed
```

- Counts are total references examined and total findings, so a CI log that only
  wants to hear from reflock when something is wrong gets exactly one line.

Interaction with `--format`, per D1 - quiet is orthogonal to format, not a format:

- `-q --format human` - as above.
- `-q --format json` - the findings array on stdout is unchanged (a machine
  consumer asked for it), and the summary line is not printed. `-q` suppresses
  human prose, never machine output.
- `-q --verbose` - contradictory. Exit nonzero with a message naming both.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- Default output with no flags is unchanged.
- Exit codes unchanged.
- Nothing is added to the renderer that other formats must know about; quiet is
  a suppression applied around it, not a fifth format.

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `quiet-clean-is-silent` | clean tree, `-q`: exit 0, stdout and stderr both empty |
| `quiet-failure-one-line-stderr` | one finding, `-q`: stdout empty, stderr is the single summary line, exit nonzero |
| `quiet-json-still-emits` | `-q --format json`: findings on stdout unchanged |
| `quiet-verbose-conflict` | `-q --verbose`: exit nonzero, message names both flags |

## Unit tests to add

- The summary line's exact text and stream for a known finding count.
- `-q` and `--quiet` are equivalent.

## Verification

```
make gate
```

`suspects` is advisory and exits nonzero whenever it has
anything to say, so it is not part of the gate. Read its output, act on
anything real, but do not chain it.

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. IDEAS.md #13 is **deleted**, and the stale claim about `OK` noise does not
   survive anywhere else in the docs.
3. README documents `-q`, including that the summary goes to stderr.
4. `ROADMAP.yaml` marks ID-13 `done`.
