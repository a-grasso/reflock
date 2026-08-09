# Contributing to reflock

Thanks for looking. reflock is small on purpose, so the bar for changes is less
"is this useful?" and more "does this hold the line the project has drawn?"

## The two constraints that decide most PRs

1. **Stdlib only.** reflock ships as a single dependency-free Python file. A
   change that needs a package is a change that won't be merged - see
   [ADR-0001](docs/adr/0001-adopt-agent-docs-standard.md) and
   [DECISIONS.md](DECISIONS.md).
2. **No model in the hot path.** `check` is a grep, a hashmap lookup, and a byte
   compare. It must stay fast enough to run on every commit, on every repo, for
   free. Semantic judgement belongs in the layer *above* reflock, on the handful
   of references that drifted.

[DECISIONS.md](DECISIONS.md) records what has already been considered and
rejected, and why. Reading it first will save you writing a PR that was decided
against a year ago.

## Working on it

```bash
just test      # unit tests
just bench     # behavioural fixtures under evalbench/
just check     # reflock checking its own references
just gate      # all of the above - must be green before you commit
```

`just gate` is what CI runs. There is a pre-commit hook in `.githooks/` that
runs it for you:

```bash
git config core.hooksPath .githooks
```

`just suspects` is deliberately outside the gate - it is an advisory heuristic
that exits nonzero whenever it has anything to say.

## Bugs

The most useful bug report is a **fixture**. `evalbench/fixtures/` is a
directory per scenario: a tiny `repo/` and a `scenario.json` describing the
command and the expected output. A failing fixture that reproduces your problem
is worth more than a paragraph describing it, and it becomes the regression test
for the fix.

If a fixture is too much, an issue with the reference as written, the tree
around it, and what reflock said versus what you expected is plenty.

## Pull requests

- One concern per PR.
- New behaviour comes with a fixture or a unit test. Bug fixes come with a test
  that fails before the fix.
- Don't edit auto-generated files; change whatever generates them.
- Don't bump the version - releases are cut by the maintainer with
  `just release X.Y.Z`.

## Design documents

`roadmap/` (under `docs/`) holds per-feature specs and bug writeups that feed
[DECISIONS.md](DECISIONS.md) and [NORTHSTARS.md](NORTHSTARS.md). If you're
proposing something sizable, a short writeup there first will get you an answer
faster than a large PR will.
