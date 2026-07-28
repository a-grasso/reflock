# CLI-02 acceptance contract: subcommand `--help` has no usage examples

Source: AXI adoption review 2026-07-28 ([kunchenguid/axi](https://github.com/kunchenguid/axi) principle 10, "consistent way to get help")
Owner: agent · Tier: near · Touches: [reflock_lib/cli.py](../reflock_lib/cli.py), [test_reflock.py](../test_reflock.py)
Locked decisions: none (help text only; no output-format or renderer change)

## The defect

`reflock <subcommand> --help` lists flags with a one-line description each -
argparse's default - but no worked example. A caller who has never run
`explain` before sees `spec  <file>:<line>` and `--full  print the whole unit
text, not the first 40 lines`, and has to infer the actual invocation shape
from the flag list plus whatever prose it can find in the README. Every
sibling subcommand has the same gap: `--help` documents flags in isolation,
never a runnable line.

## Required behavior

Each subcommand gains an `epilog` of 2-3 concrete, runnable example
invocations, rendered with `formatter_class=argparse.RawDescriptionHelpFormatter`
so the lines keep their own layout instead of being rewrapped into a
paragraph:

```
$ reflock explain --help
usage: reflock explain [-h] [--format {human,json}] [--full] spec

positional arguments:
  spec                  <file>:<line>
...

examples:
  reflock explain docs/a.md:12
  reflock explain docs/a.md:12 --full
  reflock explain docs/a.md:12 --format json
```

- Every subcommand added by `build_parser` (`check`, `stamp`, `suspects`,
  `backlinks`, `explain`, `completion`) gets an `epilog`.
- Examples are real, syntactically valid invocations of *that* subcommand -
  no placeholders standing in for a flag name, though a path argument may be
  a representative example path (`docs/a.md`, `docs/DESIGN.md`) since AXI's
  "don't guess a concrete value" rule is about a *suggested next command in
  output* pointing at data that exists, not about a static help example,
  which is illustrative by nature (every man-page and `--help` in existence
  uses illustrative paths for exactly this reason).
- The epilog is headed `examples:` (lowercase, colon, matching argparse's own
  `positional arguments:` / `options:` section heading style) so it reads as
  one more standard section, not bolted-on prose.
- The top-level `reflock --help` (no subcommand) is unchanged - this
  contract is about the six subcommand help screens, not the umbrella one.

## Explicitly out of scope

- The top-level parser's `description`/identity (binary path, one-line
  purpose at the very top). That's CLI-03's concern (bare-invocation
  behavior), not a `--help` text change.
- Any change to flag help strings themselves, or to the flags available.
- Machine-readable help (`--help --format json` or similar). AXI's principle
  10 asks for a concise reference "when agents need it," and argparse's
  human-readable `--help` already serves that; no command reads `--help`
  output programmatically today, so a structured variant would be new
  surface area with no consumer.

## Invariants

- `--help` still exits 0 via argparse's own `SystemExit`, for every
  subcommand.
- Existing help text (usage line, flag descriptions) is byte-for-byte
  unchanged; only an epilog section is appended.
- `parser_spec()`'s introspection (used for shell-completion generation, see
  `reflock_lib/cli.py`) is unaffected - `epilog` and `formatter_class` are not
  actions and do not appear in `subparser._actions`.
- No new imports outside the stdlib (`argparse.RawDescriptionHelpFormatter`
  is already part of `argparse`, already imported).

## Fixtures to add

None - `--help` output is exercised via `main()` raising `SystemExit`, which
`evalbench`'s subprocess harness has no assertion primitive for distinguishing
from a normal exit; this stays a `test_reflock.py`-only contract, matching
`test_version_flag`'s existing pattern for `--version`.

## Unit tests to add

- For each of `check`, `stamp`, `suspects`, `backlinks`, `explain`,
  `completion`: `reflock <cmd> --help` exits 0 and stdout contains an
  `examples:` section with at least one line starting with `  reflock <cmd>
  `.
- `reflock completion bash --help` (a subcommand with a `choices`-constrained
  positional) still exits 0 with its usage line intact - proves the epilog
  addition didn't disturb argument parsing for the one subcommand whose
  positional isn't a free-form path.
- `shell_completion` parity tests (existing, in `test_reflock.py`) stay green
  unmodified - proves `parser_spec()` still ignores `epilog`.
- `reflock --help` (no subcommand) is unchanged from its current text
  (regression guard that this contract touched subcommands only).

## Verification

```
make gate
```

## Definition of done

1. Unit tests above pass; every existing test stays green unmodified.
2. `ROADMAP.yaml` adds CLI-02 as `done`.
