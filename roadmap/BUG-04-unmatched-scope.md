# BUG-04 acceptance contract: a path argument that matches nothing exits 0

Source: review 2026-07-28
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

`scoped_files()` prefix-filters the index by the requested paths and returns
whatever matched. Nothing matched is not an error - it is an empty work list,
and an empty work list has no problems in it:

```
$ reflock check does-not-exist.md
All references OK.
$ echo $?
0

$ reflock check nosuchdir/
All references OK.
$ echo $?
0
```

A CI step pinned to `reflock check docs/` therefore keeps passing forever the
day `docs/` is renamed to `documentation/`. That is precisely the class of
stale-reference rot reflock exists to catch, sitting in the contract by which
reflock is invoked. `reflock check .` has the same shape and checks nothing at
all today, because `.` normalizes to a path no indexed file is prefixed by.

## Required behavior

A path argument that names nothing in the tree is a usage error: a message on
stderr naming the offending argument as the user spelled it, and exit **2** -
the code `check` already uses for `--json`/`--format` conflicts, distinct from
1 (findings exist) so CI can tell "reflock is misconfigured" from "reflock found
problems".

This applies to every command taking `paths`: `check`, `stamp` and `suspects`,
which all scope through the same function.

### What counts as matching

- An indexed file, or any directory prefix of one. `docs/` and `docs` are the
  same request.
- A path that exists in the tree but contributes no reference *sources* - a
  binary file, a `.reflockignore`d file, a directory holding only those - is
  **matched**, not an error. It names something real; it is simply empty of
  work. Reporting it as a usage error would make `.reflockignore` and reflock's
  own scoping fight each other.
- `.` (and an absolute path equal to the tree root) means the whole tree, as it
  reads. Today it silently means nothing.

## Explicitly out of scope

- Glob or pattern arguments. `paths` stays a list of literal paths; shells
  already expand globs and `.reflockignore` owns pattern exclusion.
- Any change to what a *matched* path selects, or to sort order.
- `backlinks` / `explain` path handling. Those take a single positional with
  their own validation and are CLI-01.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified. In
  particular `scoped-check-limits-to-path-arg` must still scope exactly as it
  does now.
- A run with no `paths` at all is unaffected.
- Exit 1 still means "found problems" and 0 still means "clean". A misconfigured
  invocation must not be reported as either.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `scope-unmatched-path-exits-two` | `check does-not-exist.md` exits 2, names the argument on stderr, and prints nothing to stdout |
| `scope-unmatched-dir-exits-two` | the same for a directory-shaped argument, so the prefix branch is covered too |
| `scope-dot-means-whole-tree` | `check .` finds the same DANGLING finding a bare `check` does, with byte-identical stdout |
| `scope-ignored-path-is-not-an-error` | a `.reflockignore`d file passed explicitly exits 0, not 2 |

## Unit tests to add

- `check`, `stamp` and `suspects` each exit 2 on an unmatched path.
- The error names the path as the user spelled it (`docs/` stays `docs/`, not a
  normalized form), so the message matches what they typed.
- A valid path alongside an invalid one still errors - reflock must not do half
  the work and report success.
- `.` selects the whole tree.
- A binary file, and a `.reflockignore`d file, each passed explicitly: exit 0.
- An existing directory containing only ignored files: exit 0.
- `scoped_files` raises for an unmatched path and returns normally otherwise
  (asserted directly, not only through the commands).

## Verification

```
make gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. README's CI section states the exit-code contract, including 2 for a
   misconfigured invocation. Re-stamp the file.
3. `ROADMAP.yaml` marks BUG-04 `done`.
