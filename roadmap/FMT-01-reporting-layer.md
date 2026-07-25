# FMT-01 acceptance contract: one reporting layer behind `--format`

Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format), [D3](DECIDED.md#d3-zero-runtime-dependencies)

This is a **pure refactor plus one new flag**. It must not change a single byte
of existing output. Four queued items depend on it, so it lands before them.

## Required behavior

Extract the printing currently inlined in `cmd_check` into one renderer,
selected by a `--format` choice on `check`:

- `--format human` - the default. Byte-identical to today's output, including
  colors, the `--no-color` flag, the `--verbose` listing of `OK` refs, and the
  trailing `N problem(s).` / `All references OK.` lines.
- `--format json` - byte-identical to today's `--json` output, same key order,
  same shape.
- `--json` - retained as an alias for `--format json`. Per D1 this is not
  negotiable; it is a documented flag.

`--json` and `--format` together: if they agree, fine; if they disagree, error
out with a clear message rather than silently preferring one.

Adding a third format later must mean adding one function and one choice value.
No caller of the renderer may branch on format.

## Explicitly out of scope

- `--format github` - that is NS-04.
- `-q` / quiet - that is ID-13.
- `backlinks` / `explain` - those are ID-15 and ID-10. Do not add them here,
  but do not design the renderer in a way that assumes `check` is its only
  caller: it takes findings and a format, not a `check` result object.

## Invariants

- Existing unit tests and evalbench fixtures stay green, **unmodified**. The
  bench asserts exact JSON, so any drift in shape fails loudly - that is the
  safety net for this refactor and it must not be edited.
- Exit codes unchanged.
- Color behavior unchanged, including the existing `--no-color` handling and
  whatever TTY detection is already in place.
- No new imports outside the stdlib (D3).

## Tests to add

- `check --format human` output equals `check` output for the same tree, for
  both a clean tree and a tree with findings.
- `check --format json` output equals `check --json` output.
- `check --json --format json` succeeds; `check --json --format human` exits
  nonzero with a message naming both flags.
- An invalid `--format` value exits nonzero and lists the valid choices
  (argparse gives this free, but assert it so a later hand-rolled parse cannot
  regress it silently).

## Fixture to add

`evalbench/fixtures/format-human-matches-default`: a tree with one `DANGLING`
finding, run twice - once with no format flag, once with `--format human` -
asserting identical stdout and exit code.

## Verification

```
make test && make bench && make check && make suspects
```

## Definition of done

1. Tests and fixture above pass; nothing existing was modified.
2. Adding a format is a one-function change. State in the PR body where that
   function goes, so the next three items can point at it.
3. README's CLI documentation covers `--format`, and notes `--json` as an alias.
4. `ROADMAP.yaml` marks FMT-01 `done`.
5. A commit whose diff is confined to reflock.py, test_reflock.py, the new
   fixture, README.md and ROADMAP.yaml.
