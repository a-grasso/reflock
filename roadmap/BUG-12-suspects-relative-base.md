# BUG-12 acceptance contract: a bare path has no single base to resolve against

Source: kai-crm dogfooding 2026-07-30
Owner: agent · Tier: near · Touches: [reflock_lib/engine.py](../reflock_lib/engine.py), [reflock_lib/commands.py](../reflock_lib/commands.py), [README.md](../README.md), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies), [D4](DECIDED.md#d4-wiki-link-resolution-relative-first-then-unique-basename)

## The defect

`cmd_suspects` resolves a token two ways - relative to the referring file, and
verbatim from the repo root - and tests both against `.gitignore` in pass 2.
Neither reading is right for a path whose base is a *process working directory*:

```
platform/app/src/main/kotlin/…/PipelineRunner.kt:49   ../data/crm.db
platform/app/src/test/kotlin/…/PipelineLiveTest.kt:20 ../../data/crm.db
submarine/db.py:1                                     data/crm.db
Justfile:196                                          dist/snapshot.json
```

Every one of these is a runtime or build artifact that is gitignored, i.e.
exactly the class pass 2 exists to suppress. They survive it because the
gitignore probe is handed the wrong candidate:

- `../data/crm.db` from a file six directories deep resolves to
  `platform/app/src/main/kotlin/com/deviceinsight/kaicrm/data/crm.db`, which is
  gitignored nowhere. The *intended* path is `data/crm.db` at the root, relative
  to where the JVM's working directory actually is.
- `dist/snapshot.json` in the root `Justfile` is relative to the directory a
  recipe `cd`s into, which reflock cannot know without parsing the recipe.

This is the last and softest item of the five from this review, because unlike
BUG-08 through BUG-11 it is not a coding slip - the information genuinely is not
in the file. The fix is therefore about what reflock may *claim*, not about
computing the right answer.

## Required behavior

Two additions, both about withdrawing an unsupportable claim.

**1. The root-relative reading of a dotted token joins the gitignore probe.**
A token's leading `./` and `../` segments are stripped and the remainder is
added to the pass-2 candidate set. `../data/crm.db` therefore also asks git
about `data/crm.db`, and a repo that gitignores `data/` suppresses it.

This is not a guess about which base is correct - it adds a candidate, and a
candidate only ever *suppresses* a finding. The asymmetry is what makes it safe:
being wrong costs a missed advisory hit, never a fabricated one.

**2. Tail resolution: a token that names a path existing somewhere in the tree
is not a suspect.** If any indexed file or directory path ends with the token at
a segment boundary, the token resolves - just not from the base reflock guessed.

D4 is the precedent: wiki-links already fall back from relative resolution to a
basename match across the index, for the same reason (the link works in the tool
it was written in, so calling it `DANGLING` is a false positive). D4 requires the
basename match to be *unique* because it must pick one target to fingerprint.
`suspects` picks nothing and fingerprints nothing - it only answers "is there
reason to believe this is rot?" - so uniqueness is irrelevant here and requiring
it would only re-introduce false positives. Stating that difference is the point
of citing D4 rather than reusing its resolver.

Implementation note: the tails are precomputed once into a set on the index
(every segment-boundary suffix of every indexed path), not searched per
candidate, so this stays a hashmap lookup per token in keeping with PERF-01's
standard for the hot path.

## Explicitly out of scope

- **Working-directory-relative paths in build recipes.** `dist/snapshot.json` in
  a root `Justfile` that `cd`s into a subproject stays a suspect. Resolving it
  means interpreting the recipe, which is a different tool. The README names
  `.reflockignore` as the answer, and `Justfile` is a plausible line for a
  consumer to put there.
- Inferring a base from a language's conventions (a JVM run configuration, a
  `package.json` script's directory). Real information, wrong layer - it would
  put a build-system model in a grep-shaped heuristic.
- Any change to `check`'s resolution. Reference resolution stays
  relative-to-the-referring-file, which for an explicit reference is correct and
  unambiguous. This item is entirely about the heuristic's tolerance.
- Reporting *why* a token was suppressed. Advisory command, silent suppression,
  consistent with D2's accepted cost and BUG-11.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- A token naming a path that exists nowhere in the tree and is not gitignored is
  still a suspect. The flagship case - `platform/research.sh` after the file is
  deleted - must still be reported, and its fixture pins it.
- `check` verdicts are byte-identical to before for every existing fixture; tail
  resolution is not reachable from the reference path.
- A candidate escaping the root (`../` past the top) is never handed to
  `git check-ignore` as a `..`-prefixed path.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `suspects-gitignored-via-root-relative-reading` | with `--all`, `../data/crm.db` in a nested source file is suppressed by a root `.gitignore` naming `data/`, while a non-ignored `../gone/x.py` from the same file is still reported |
| `suspects-tail-resolves-elsewhere-in-tree` | a bare `catalog/Ontology.kt` in prose is not a suspect when `platform/domain/catalog/Ontology.kt` exists, while a genuinely absent `catalog/Missing.kt` still is |

## Unit tests to add

- `../data/crm.db` from a nested file, with `data/` gitignored at the root, is
  not a suspect.
- The same token with nothing gitignored *is* a suspect (the addition suppresses
  only what git actually ignores).
- A token matching the tail of an indexed path is not a suspect.
- Tail matching respects segment boundaries: `log/Ontology.kt` does not match an
  indexed `catalog/Ontology.kt`.
- Tail matching does not fire on a bare basename with no slash, since `PATHISH`
  requires a slash - asserted so the leniency's blast radius is pinned.
- A token resolving above the repo root is not passed to `git check-ignore` with
  a `..` prefix (asserted on the candidate list, so the guarantee does not
  depend on git's error behavior).
- `platform/research.sh`, absent everywhere, is still a suspect.

## Verification

```
just gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. README's `suspects` section states what the heuristic will not claim: a bare
   path whose base is a working directory is out of reach, and `.reflockignore`
   is the escape hatch. Re-stamp the file.
3. `ROADMAP.yaml` marks BUG-12 `done`.
