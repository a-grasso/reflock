# CLI-01 acceptance contract: backlinks and explain reject path forms check accepts

Source: review 2026-07-28
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format), [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

`check` normalizes its path arguments against the tree root. `backlinks` and
`explain` compare the raw string against `idx.files`, so the same file is
addressable by one command and not the other:

```
$ reflock backlinks docs/t.md          ok
$ reflock backlinks ./docs/t.md        error: no such file in index: ./docs/t.md
$ cd docs && reflock backlinks t.md    error: no such file in index: t.md
$ cd docs && reflock explain a.md:1    error: no such file in index: a.md
$ cd docs && reflock check a.md        ok            <- same path, different answer
```

Shell completion produces `./` prefixes, and working from a subdirectory is
normal. Three commands taking a path should agree about what a path is.

### Second defect: a misspelled anchor reports zero, not an error

`backlinks` validates the file half of `path#anchor` and not the anchor half:

```
$ reflock backlinks docs/t.md#no-such-anchor
No backlinks to docs/t.md.
$ echo $?
0
```

The README already argues the opposite principle one level up - *"a path absent
from the index exits nonzero, since silently reporting zero backlinks for a
typo'd filename would mislead"*. A misspelled **anchor** misleads identically,
and worse: "nothing points at this section" is the answer you act on before
editing that section.

## Required behavior

### One notion of a path argument

All five commands share one normalization helper: resolve against the process
CWD like `git` and `find`, express the result relative to the tree root, and
`realpath` both sides so a symlinked checkout, a `./` prefix and a `..` spelling
reduce to the same thing.

Accepted by `backlinks`/`explain`, all naming the same file: `docs/t.md`,
`./docs/t.md`, `t.md` from inside `docs/`, and an absolute path.

A path that does not name an indexed file stays exit 2, as today.

#### Refinement found while implementing: single-file arguments also accept the repo-relative form

Making `backlinks`/`explain` purely CWD-relative broke something the raw string
comparison had been getting right by accident. `check` *prints* repo-relative
paths - `docs/a.md:1` - whatever directory it runs in, and the obvious workflow
is to paste one straight into `explain`. Purely CWD-relative resolution turns
that paste into `docs/docs/a.md` the moment the user is inside `docs/`.

So the two single-file commands resolve CWD-relative **first, then fall back to
the repo-relative reading**, which is the same relative-first-then-fallback
shape D4 already uses for wiki-links. CWD wins on the rare collision, which is
shell intuition and is deterministic.

`scoped_files` keeps its CWD-only resolution. The distinction is real rather
than cosmetic: `check docs/` takes a *path* to scope by, where git-like
behavior is the whole expectation, while `backlinks`/`explain` take an
*identifier* for one indexed file - and reflock is itself a publisher of those
identifiers, in exactly the repo-relative form. A command should accept the
strings it prints.

### An unresolvable anchor is an error

`backlinks <path>#<anchor>` where the anchor resolves to neither a heading slug
nor a `reflock-anchor:` span exits **2**, naming the anchor. A heading slug and a
marker span are both valid; `locate_anchor` already answers this and is what
`explain` uses, so the two cannot disagree about what an anchor is.

Zero backlinks to a *valid* anchor stays exit 0 with the "no backlinks" line -
that is a real answer.

## Explicitly out of scope

- `explain`'s `<file>:<line>` grammar. `rpartition(":")` stays; a filename
  containing a colon is not a case this item takes on.
- Accepting a path outside the tree, or a glob. Unchanged.
- `backlinks` scoping to a subset of the tree. It answers "what points here"
  and must see everything to answer it.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified -
  `backlinks-unknown-path-exits-nonzero` and the `explain-*` error fixtures
  included.
- A valid repo-relative path keeps working exactly as today.
- Both commands stay read-only.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `backlinks-accepts-dot-slash-path` | `./t.md` returns the same rows as `t.md`, byte-identical stdout |
| `backlinks-unknown-anchor-exits-two` | `t.md#no-such-anchor` exits 2 naming the anchor, and a *valid* anchor with no referrers still exits 0 |
| `backlinks-accepts-marker-span-anchor` | an anchor defined by `reflock-anchor:` markers is accepted, not just a heading slug |
| `explain-accepts-dot-slash-path` | `./a.md:1` explains the same reference as `a.md:1` |

Working from a subdirectory is covered in the unit tests rather than a fixture:
`run_bench.py` always invokes reflock with the tree root as CWD, and adding a
per-step CWD to the harness is a bench feature, not this item.

## Unit tests to add

- `backlinks` accepts `./t.md`, an absolute path, and a cwd-relative path from
  inside a subdirectory - each returning the same rows as the repo-relative
  form.
- `explain` accepts the same three spellings.
- `backlinks docs/t.md#no-such-anchor` exits 2 and names the anchor.
- `backlinks docs/t.md#real-anchor` with no referrers exits 0.
- `backlinks` accepts a marker-span anchor.
- An unknown path still exits 2 for both commands.
- The normalization helper is shared: assert `scoped_files` and the
  `backlinks`/`explain` path resolution agree for a `./`-prefixed spelling.

## Verification

```
make gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. README's `backlinks` paragraph states that an unresolvable anchor exits
   nonzero for the same reason a missing file does. Re-stamp the file.
3. `ROADMAP.yaml` marks CLI-01 `done`.
