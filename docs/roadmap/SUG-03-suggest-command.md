# SUG-03 acceptance contract: `reflock suggest` places the first pins

Source: [issue #20](https://github.com/a-grasso/reflock/issues/20)
Owner: agent · Tier: near · Touches: [reflock_lib/suggest/__init__.py](../../reflock_lib/suggest/__init__.py), [reflock_lib/suggest/harvest.py](../../reflock_lib/suggest/harvest.py), [reflock_lib/suggest/churn.py](../../reflock_lib/suggest/churn.py), [reflock_lib/suggest/apply.py](../../reflock_lib/suggest/apply.py), [reflock_lib/cli.py](../../reflock_lib/cli.py), [test_reflock.py](../../test_reflock.py), [evalbench/fixtures/](../../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The problem

Pins work, but nobody places them: `check` at level 1 needs no adoption
effort, but level 2 requires a human to read every cross-reference and decide
what it claims about its target - and this repository shipped with 1 pin.
`reflock suggest` does that pass once, as a diff you read, wiring the filter
(SUG-01), the anchor model (SUG-02) and churn ranking into one command that
degrades gracefully when there is nothing to do.

## The decision

**Pipeline**, in `cmd_suggest`:

1. `harvest.candidates` - every unpinned, whole-file markdown reference in
   scope, via `parse_refs`/`resolve_target` so the population matches `check`'s.
2. `claims.pin_worthy` filters out navigation (SUG-01). If nothing survives,
   print `nothing to suggest: ...` and exit 0 - **before** the `[suggest]`
   runtime is imported.
3. `runtime.require()`. `MissingRuntime` prints the install hint to stderr and
   exits 2.
4. `fetch.ensure()` (or `--model DIR`) gets the model onto disk; `FetchError`
   exits 2.
5. `Anchorer.anchor` narrows each surviving reference to a heading or leaves
   it whole-file.
6. `Churn.rate` ranks by `(changes + 1) / (commits + 2)` over first-parent
   history, calmest unit first, ties broken by descending confidence then
   file/line/col.
7. The top `--max-pins` are kept; the rest are dropped from consideration.
8. `apply.apply` writes the `#anchor` and empty `<!--@-->` pin, re-matching at
   the parser's own column and re-parsing the file afterward - a pin the
   engine cannot see as opted-in is worse than none, so a mismatch is skipped
   and reported rather than written.
9. A next-step hint: `reflock stamp && reflock check`, and a reminder that the
   diff is a suggestion to read.

**Exit codes**: `0` for "done" (pins written or dry-run) and for "nothing to
do" (no candidates, or everything already filtered); `2` for not a git work
tree, a scope error, missing `[suggest]` runtime, or a model fetch failure.
No exit 1 - `suggest` does not report a pass/fail verdict the way `check` does.

**Flags**: `paths` (positional, scope like other commands), `--max-pins`
(default 25), `--since` (default `'90 days ago'`, the churn window), `-n`/
`--dry-run` (print what would be pinned, write nothing), `--model DIR`
(use a local model directory instead of fetching).

**Lazy import.** `cli.py`'s `cmd_suggest` imports `reflock_lib.suggest` only
when the `suggest` subcommand runs, and nothing inside `reflock_lib.suggest`
that isn't behind `runtime.require()` touches the third-party extra - so
every other command starts without ever importing it.

**Why suggest ranks by git history at all.** Churn is the ranking; without
history there is nothing to rank by, and a ranking that silently degraded to
file order would be a guess dressed up as a decision. Outside a git work tree,
`suggest` refuses with exit 2 rather than guessing.

## Explicitly out of scope

- Any interactive/TUI review flow - the diff itself is the review surface.
- Re-anchoring or re-ranking already-pinned references; `suggest` only
  touches references with no pin at all (`ref.pin is not None` is skipped in
  `harvest.candidates`).
- A `--yes`/no-review-required mode. The output is always a diff to read
  before `stamp`.

## Definition of done

1. Unit tests in `SuggestTest` pass:
   `test_harvest_takes_unpinned_whole_file_links_into_text`,
   `test_churn_counts_first_parent_changes_of_the_unit`,
   `test_suggest_writes_an_opt_in_pin_that_stamp_fills`,
   `test_suggest_dry_run_writes_nothing`,
   `test_suggest_keeps_line_endings_and_code_spans`,
   `test_suggest_ranks_calm_units_first_and_caps`,
   `test_suggest_outside_git_exits_2`,
   `test_suggest_with_nothing_to_pin_needs_no_runtime`,
   `test_suggest_without_the_extra_prints_the_install_hint`, and
   `test_other_commands_never_import_the_suggester`.
2. `evalbench/fixtures/suggest-not-a-git-repo/scenario.json` and
   `evalbench/fixtures/suggest-nothing-to-pin/scenario.json` pass.
3. `just gate` is green.
4. `docs/manual.md` documents the command, its flags and its exit codes.
5. `ROADMAP.yaml` lists SUG-03 under `done`.
