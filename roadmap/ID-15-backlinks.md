# ID-15 acceptance contract: `reflock backlinks <path>`

Source: idea #15 in [IDEAS.md](../IDEAS.md)
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format), [D3](DECIDED.md#d3-zero-runtime-dependencies)
Depends on: FMT-01

## Required behavior

A new subcommand answering "what points at this file", the question you want
answered *before* editing a heavily-cited document: what would I invalidate?

```
$ reflock backlinks DECISIONS.md
README.md:42        DECISIONS.md#3-where-to-gate-and-what-each-gate-can-honestly-promise  pinned
NORTHSTARS.md:18    DECISIONS.md                                                          unpinned
```

- Argument is a repo-relative path. Accept a path with an anchor
  (`DECISIONS.md#section`) to narrow to references targeting that anchor
  specifically.
- Output per backlink: referring file and line, the target as written, and pin
  state. Pin state matters because an unpinned reference will not notice your
  edit - that is the actionable part.
- Read-only. This command never writes.
- Supports `--format` per D1, reusing FMT-01's renderer.
- A path with no backlinks prints a clear "no backlinks" line and exits 0. Not
  finding references is not an error.
- A path that does not exist in the index exits nonzero - that is a typo, and
  silently reporting zero backlinks for a misspelled filename is the failure
  mode most likely to mislead.

## Explicitly out of scope

- Suspects. `suspects` is a separate heuristic command; do not fold bare
  path-shaped tokens into backlinks.
- Reverse-index caching. This is a linear pass over an index already built.
- Transitive backlinks (what points at what points at this). Not asked for.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- No writes.
- Ordering is deterministic - sort by referring file then line, so output is
  diffable and testable.
- No new imports outside the stdlib (D3).
- Anchor matching uses the same slug comparison `check` uses. Two notions of
  anchor equality would be a bug.

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `backlinks-lists-referrers` | two files referencing a target both appear, sorted |
| `backlinks-anchor-narrows` | a target with an anchor lists only references to that anchor |
| `backlinks-reports-pin-state` | a pinned and an unpinned reference are distinguished |
| `backlinks-none-exits-zero` | an uncited file exits 0 with a clear message |
| `backlinks-unknown-path-exits-nonzero` | a path absent from the index exits nonzero |
| `backlinks-format-json` | JSON output shape is stable and documented |

## Unit tests to add

- Sort order for referrers in the same file and across files.
- Anchor narrowing including the case where a file is referenced both bare and
  with an anchor.

## Verification

```
make test && make bench && make check && make suspects
```

Then run it against this repo for real and put the output in the PR body -
DECISIONS.md and NORTHSTARS.md are genuinely cross-referenced, so it is a live
test of whether the output is actually useful to read.

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. Idea #15 is **deleted** from [IDEAS.md](../IDEAS.md).
3. README documents the subcommand and its JSON shape.
4. `ROADMAP.yaml` marks ID-15 `done`.
