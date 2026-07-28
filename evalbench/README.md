# reflock eval bench

Isolated, disposable repos that pin down what reflock *should* find. Each
fixture under `fixtures/<name>/` is a real git repo (built fresh in a temp dir
on every run) plus a `scenario.json` describing which reflock command(s) to
run and what the output must be.

This is a behavioral regression suite, distinct from `test_reflock.py`'s unit
tests: it exercises reflock as a subprocess, end to end, against realistic
mixed docs+code trees, including the git-specific behaviors (`.gitignore`
honoring, untracked files, `git ls-files` scoping) that don't engage against a
plain non-git temp directory.

## Run it

```sh
make bench                       # every fixture
python3 evalbench/run_bench.py   # equivalent
python3 evalbench/run_bench.py dangling-file drifted-after-edit   # just these
python3 evalbench/run_bench.py -v                                  # show diffs on failure
```

Nonzero exit if any fixture fails.

## Anatomy of a fixture

```
fixtures/dangling-file/
  repo/
    a.md
  scenario.json
```

`repo/` is copied into a fresh temp dir, `git init`'d, and committed before
any commands run. `scenario.json`:

```json
{
  "description": "A markdown link to a file that doesn't exist is DANGLING.",
  "git": { "track": ["a.md"] },
  "steps": [
    {
      "cmd": "check",
      "args": ["--json"],
      "expect_exit": 1,
      "expect_json": [ { "verdict": "DANGLING", "file": "a.md", "line": 1,
                          "target": "missing.md", "detail": "no such file: missing.md" } ]
    }
  ]
}
```

- `git` (optional): `{"track": [...]}` stages and commits only the listed
  paths, leaving everything else in `repo/` present on disk but untracked
  (the mechanism for testing untracked/gitignored-file semantics). Omit
  `git` entirely to `git add -A` everything. `{"skip": true}` skips
  `git init` altogether, to exercise reflock's non-git directory-walk
  fallback.
- `steps`: run in order, against the *same* materialized repo, so a later
  step sees an earlier step's mutations (e.g. `stamp` then `check`). Each
  step:
  - `cmd` / `args`: the reflock subcommand and its arguments.
  - `write` (optional): `{"relpath": "new content"}` written to the repo
    before this step runs — for scenarios that mutate a file mid-scenario
    (e.g. to provoke `DRIFTED`) without a separate fixture per state.
  - `expect_exit`: required process exit code.
  - `expect_json`: exact structural match against parsed `--json` stdout.
  - `expect_contains` / `expect_not_contains`: substring checks against
    stdout — used instead of `expect_json` whenever the expected output
    embeds a content hash that isn't worth hardcoding (e.g. a `DRIFTED`
    detail's `pinned @xxxxxxxx, now @yyyyyyyy`).
  - `expect_file_regex`: `{"relpath": "regex"}` checked against a file's
    content after the step runs (e.g. confirming `stamp` spliced in a hex
    fingerprint).
  - `expect_stderr` / `expect_stderr_not_contains`: the same substring checks
    against stderr. A contract that says "this goes to stderr" needs both
    halves — present on stderr *and* absent from stdout.
  - `expect_stdout_empty` / `expect_stderr_empty`: `true` asserts the stream is
    exactly empty. "Prints nothing on success" is a claim about the whole
    stream; an `expect_not_contains` list of words that happen not to appear
    passes just as well when the command printed something else entirely.
  - `expect_stdout_same_as_step`: a 0-based index of an **earlier** step in this
    scenario; this step's stdout must be byte-identical to that step's. For
    "these two invocations are the same command spelled differently".
  - `expect_tree_unchanged_since_step`: a 0-based index of an earlier step;
    every file in the tree must have the same bytes it had after that step,
    with none added or removed. This is how a read-only command's "writes
    nothing" is asserted. Content only — mtime isn't a promise reflock makes,
    and asserting it would be flaky on coarse-grained filesystems.

Unknown keys are a **fixture error**, not silently ignored: a step carrying
`expect_containss` used to report `PASS` having asserted nothing. If you add a
primitive, add it to `STEP_KEYS` in `run_bench.py` — `BenchHarnessTest` in
`test_reflock.py` asserts the accepted set matches the documented one.

## Adding a fixture

Pick the closest existing fixture, copy its directory, change the repo
content and `scenario.json`. There's no fixture generator to run — write the
files directly. Keep one behavior per fixture; if you need multiple states of
the same repo, chain `steps` (optionally with `write`) rather than making a
new fixture.
