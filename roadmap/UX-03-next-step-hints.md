# UX-03 acceptance contract: `check` and `stamp --check` report problems with no next step

Source: AXI adoption review 2026-07-28 ([kunchenguid/axi](https://github.com/kunchenguid/axi) principle 9, "contextual disclosure")
Owner: agent · Tier: near · Touches: [reflock_lib/commands.py](../reflock_lib/commands.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format)

## The defect

`check --format human` on a broken tree prints the grouped findings and a
count - `"2 problem(s)."` - and stops. Nothing in the output says what to do
next. The two obvious next actions (`explain` a specific finding, `stamp` an
`UNSTAMPED` pin) exist and are documented in the README and the shipped
`examples/skill/refcheck/SKILL.md`, but only a reader who already knows the
tool discovers them. The same gap exists in `stamp --check`: it reports what
would change and stops, without saying that plain `stamp` is the command that
applies it.

An agent driving `reflock` without having read the README has to already
know the CLI's surface area; every other AXI-adjacent gap this review found
was about machine-readability, but this one is about discoverability for a
first-time caller, human or agent.

## Required behavior

Human-format output only - `json`/`github` stay exactly as they are, since
they're consumed by scripts/CI that already know what they're calling next
(D1: this contract adds no new key to either shape).

**`check`**, only when `problems > 0` (self-contained on the clean path -
`"All references OK."` gets no hint, per AXI's own "omit when self-contained"
rule):

```
2 problem(s).

Run `reflock explain <file>:<line>` for details on any of the above.
```

- The `explain` hint always appears when there is at least one problem,
  regardless of which verdicts they are.
- A second hint line appears only when at least one result in this run's
  output is `UNSTAMPED`:

  ```
  Run `reflock stamp` to fill in UNSTAMPED pins.
  ```

- `<file>:<line>` is a literal placeholder, not a guessed concrete value -
  `explain`'s own `--help` already documents `spec` as `<file>:<line>`, so
  this is the same convention, not a new one. Picking "the first" finding to
  name concretely would be arbitrary and, per AXI principle 9, is exactly the
  kind of guess that can mislead a caller into thinking one finding is
  special.

**`stamp --check`**, only when `report` is non-empty (the `--warn` exit-code
variant included - the hint is part of stdout, not the exit code, and an
existing invariant already requires `--check` and `--check --warn` to share
stdout byte-for-byte):

```
2 pin(s) would be stamped.

Run `reflock stamp` to apply.
```

`"Nothing to stamp."` gets no hint - already the terminal, self-contained
state.

## Explicitly out of scope

- `suspects`. There is no single fix command - a bare-path hit is resolved by
  human judgment (turn it into a real link, or delete it), which is exactly
  why `examples/skill/refcheck/SKILL.md` already calls it "a migration aid,
  not a gate." Suggesting a command that doesn't exist would violate AXI's
  own "actionable: every suggestion is a complete command" rule.
- Plain `stamp` (write mode, no `--check`). It already performed the action;
  there is no obvious single next step to suggest, and "run check to verify"
  would be prescribing a workflow rather than guiding discovery (AXI: "guide
  discovery, not workflows").
- `backlinks`, `explain`. Both are detail/list views where the output itself
  is the answer - AXI's own "omit when self-contained" rule, already applied
  to `backlinks`' empty-list case and to `explain` generally.
- Any change to `--format json` or `--format github` shapes.

## Invariants

- `--format json` and `--format github` output is byte-identical to today
  for both `check` and `stamp --check`.
- The clean-tree and nothing-to-stamp paths are unchanged (no hint text
  appears).
- `stamp --check` and `stamp --check --warn` still produce byte-identical
  stdout (existing invariant, unmodified).
- Exit codes are unchanged.

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `check-hints-explain-on-dangling` | a `DANGLING` finding's human output contains the `explain` hint line, exactly once |
| `check-hints-stamp-on-unstamped` | an `UNSTAMPED` finding's human output contains both the `explain` hint and the `stamp` hint |
| `check-clean-has-no-hints` | `"All references OK."` output does not contain the string `` `reflock `` |
| `stamp-check-hints-apply` | `stamp --check` with a pending pin prints the `Run `reflock stamp` to apply.` hint |
| `stamp-check-nothing-has-no-hint` | `stamp --check` on a clean tree prints `"Nothing to stamp."` and no hint |

## Unit tests to add

- `check` human output with one `DANGLING` result: contains the `explain`
  hint, does not contain the `stamp` hint.
- `check` human output with one `UNSTAMPED` result: contains both hints.
- `check` human output with a mix of `DANGLING` and `UNSTAMPED`: both hints
  appear exactly once each (not once per finding).
- `check --format json` and `--format github` on the same broken tree: output
  is byte-identical to before this contract (no hint text leaks in).
- `check` on a clean tree: output is exactly `"\nAll references OK.\n"` -
  unchanged.
- `stamp --check` with a pending pin: output ends with the `stamp` hint.
- `stamp --check --warn` with the same tree: stdout identical to the
  non-`--warn` run (existing invariant, re-asserted after this change).
- `stamp --check` on a clean tree: output is exactly `"\nNothing to
  stamp.\n"` - unchanged.

## Verification

```
make gate
```

## Definition of done

1. Fixtures and unit tests above pass; every existing test stays green
   unmodified.
2. README's `check` and `stamp --check` paragraphs mention the hint lines.
3. `ROADMAP.yaml` adds UX-03 as `done`.
