# CLI-03 acceptance contract: bare `reflock` shows usage instead of live state

Source: AXI adoption review 2026-07-28 ([kunchenguid/axi](https://github.com/kunchenguid/axi) principle 8, "content first")
Owner: agent · Tier: near · Touches: [reflock_lib/cli.py](../reflock_lib/cli.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: none (adds a default subcommand; no output-format or renderer change)

## The defect

`reflock` with no arguments at all exits 2 with an argparse usage error -
`the following arguments are required: cmd` - because the subparsers action
is declared `required=True`. A caller (human exploring the tool for the
first time, or an agent that just ran `reflock` to see what's here) gets a
usage manual instead of the answer to the obvious question: "are this
repo's references OK right now?" `check` with no arguments already *is*
that answer, and it is what every one of reflock's own docs
(`README.md`'s own quickstart, `examples/skill/refcheck/SKILL.md`) shows as
the first command to run.

## Required behavior

`reflock` invoked with a completely empty argument list behaves exactly like
`reflock check`:

```
$ reflock
All references OK.
$ echo $?
0
```

```
$ cd repo-with-a-broken-link && reflock
DANGLING (1)
  a.md:1  missing.md   [no such file: missing.md]

1 problem(s).

Run `reflock explain <file>:<line>` for details on any of the above.
```

- Implemented in `main()`: when `argv` (the effective argument list, whether
  passed explicitly or read from `sys.argv[1:]`) is empty, substitute
  `["check"]` before calling `ap.parse_args`. This is a rewrite of the
  argument list a single `if`, not a second code path - `check`'s own flags,
  renderer and exit codes are reused unchanged.
- `reflock --version` and `reflock --help` are unaffected - `argv` is
  `["--version"]` / `["--help"]` in those cases, not empty, so they hit
  argparse exactly as they do today.
- The subparsers action stays `required=True`. This contract does not make
  `cmd` optional in general - it special-cases the one input (nothing at
  all) where "which subcommand did you mean" has an unambiguous, documented
  answer.

## Explicitly out of scope

- `reflock --root <path>` with no subcommand. Passing a flag is a sign the
  caller had *some* explicit intent; guessing which subcommand they meant
  is a different (and much less certain) inference than "nothing at all
  means the default." This keeps erroring exactly as it does today.
- Any other subcommand becoming implicit. `check` is the only one every
  reflock doc already points a first-time reader at; making `stamp` (a
  mutation) or `suspects` (advisory) the default would be a much larger
  behavioral change for a much shakier justification.
- Changing `check`'s own default behavior (scope, format, flags). This
  contract only decides what runs when nothing is typed; `check` itself is
  untouched.

## Invariants

- `reflock check` and bare `reflock` produce byte-identical stdout, stderr,
  and exit code for the same tree - this is a delegation, not a
  reimplementation.
- `reflock --version` / `reflock --help` output and exit codes are
  unchanged.
- Every other subcommand invocation (`reflock stamp`, `reflock backlinks
  ...`, etc.) is unaffected - the empty-argv check only fires when there is
  truly nothing else.

## Fixtures to add

None. `evalbench`'s harness (`run_bench.py:run_reflock`) always invokes
`[REFLOCK, "--root", tmp, cmd, *args]` - it has no way to express "no
`--root`, no `cmd` at all," which is the exact input this contract changes
the behavior of. This stays a `test_reflock.py`-only contract, the same
situation CLI-02 documented for `--help` output.

## Unit tests to add

- `reflock.main([])` (empty list, not `None`) on a clean tree: same stdout
  and return code as `reflock.main(["--root", d, "check"])`.
- `reflock.main(["--root", d])` (root given, no subcommand): still exits 2
  with the existing `cmd` usage error - proves the default is scoped to
  *fully* empty argv, not "no subcommand however it's spelled."
- `reflock.main(["--version"])` and `reflock.main(["--help"])`: unchanged
  from current behavior (regression guard).
- `reflock.main(["stamp"])` and every other existing subcommand-level test:
  stay green unmodified - proves the empty-argv branch cannot be reached
  once any argument is present.

## Verification

```
make gate
```

## Definition of done

1. Fixtures and unit tests above pass; every existing test stays green
   unmodified.
2. README's quickstart or `check` paragraph notes that bare `reflock` is
   `reflock check`.
3. `ROADMAP.yaml` adds CLI-03 as `done`.
