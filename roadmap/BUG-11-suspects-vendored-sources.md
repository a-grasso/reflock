# BUG-11 acceptance contract: `suspects` scans files nobody authored

Source: kai-crm dogfooding 2026-07-30
Owner: agent · Tier: near · Touches: [reflock_lib/engine.py](../reflock_lib/engine.py), [reflock_lib/commands.py](../reflock_lib/commands.py), [README.md](../README.md), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

`suspects --all` scans every text file in the tree, including files no human
maintains references in:

```
platform/.mvn/wrapper/maven-wrapper.properties:3  maven/3.9.12/apache-maven-…-bin.zip
platform/mvnw:202                                 TMP_DOWNLOAD_DIR/Downloader.java
.gitignore:2                                      doc/DECISIONS.md
tools/pipeline-showcase/package-lock.json:31      babel/code-frame/…
```

Three distinct category errors:

- **Lockfiles and wrapper scripts** are generated or vendored. A path in one is
  a fact about a build tool, not a reference into this repo, and nobody will
  ever act on the finding.
- **Ignore files** contain *patterns*, not references. `doc/DECISIONS.md` in a
  `.gitignore` is a rule saying that path should not be tracked. Reporting it
  as a reference that fails to resolve inverts its meaning.

`.reflockignore` already exists as the escape hatch, and this repo's own copy
uses it. But it requires every consumer to discover the problem, then hand-write
a list of the same half-dozen well-known filenames. Out of the box the command
is unusable on any repo with a lockfile, and "free by default" is the property
that makes the mechanical layer worth running at all.

## Required behavior

`cmd_suspects` skips a documented set of never-authored sources by default:

- lockfiles: `*.lock`, `*-lock.json`, `go.sum`
- build-tool wrappers: `mvnw`, `mvnw.cmd`, `gradlew`, `gradlew.bat`, and
  anything under a `*/wrapper/` directory of those tools
- ignore/attribute files: `.gitignore`, `.gitattributes`, `.dockerignore`,
  `.npmignore`, `.eslintignore`, `.prettierignore`, `.reflockignore`
- vendored trees: `vendor/`, `third_party/`

The list lives in one named constant in `engine.py` next to `read_reflockignore`,
as fnmatch globs matched against the repo-relative path, so it reads as data and
a reader can audit it in one place. `node_modules/` and `.git/` are already
excluded upstream in `list_files` and are not restated.

**This applies to `suspects` only, not to `check` or `stamp`.** The distinction
is the point: `check` acts on explicit reference syntax an author wrote, and a
`REF:` comment in a vendored file is still a claim someone made and should still
be verified. `suspects` *guesses* from shape, and a guess about a generated file
is never worth surfacing. Narrowing the skip to the guessing command is what
keeps this from quietly shrinking the gate.

Skipping is silent. Reporting "12 files skipped" on an advisory command adds a
line the user must learn to ignore; `.reflockignore`'s existing behavior is
silent for the same reason.

## Explicitly out of scope

- Tool-generated config that is not from a known-fixed list (`.serena/project.yml`,
  IDE metadata). There is no shape that distinguishes it from hand-written
  config, so it stays the user's `.reflockignore` call. The README says so.
- Build-recipe files (`Justfile`, `Makefile`, CI YAML). These *are* hand-written
  and can carry real references in comments; their bare paths are relative to a
  recipe's working directory, which is BUG-12's problem, not this one.
- Making the list configurable. That is ID-12 (a config file) and needs a human.
- Any change to `check`, `stamp`, `backlinks` or `explain` source selection.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- `check` and `stamp` see exactly the same source set as before - asserted, not
  assumed, because this is the one way the change could shrink the gate.
- A markdown file is never skipped by this rule; the list contains no `.md`
  pattern and a test pins that.
- An explicit scope argument does not override the skip: `suspects package-lock.json`
  reports nothing rather than resurrecting the noise. It matches a path in the
  tree, so BUG-04's unmatched-scope error does not fire - the same "matched and
  simply empty" contract `scoped_files` already documents for `.reflockignore`.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `suspects-skips-vendored-sources` | with `--all`, dangling paths inside `package-lock.json`, `mvnw` and `.gitignore` yield nothing, while one in a hand-written `.py` in the same repo is still reported |
| `suspects-vendored-still-checked-for-refs` | `check` still reports a `REF:` in a skipped file as DANGLING - the skip is scoped to the heuristic |

## Unit tests to add

- A dangling path in `package-lock.json` is not a suspect under `--all`.
- Same for `yarn.lock`, `go.sum`, `mvnw`, `gradlew`, `.gitignore`,
  `vendor/x.py`, `third_party/y.py`.
- A dangling path in a hand-written `app.py` still is.
- A `.md` file named like nothing in the list is unaffected.
- `check` on a repo whose only reference is a `REF:` inside `package-lock.json`
  still reports it (the scoping invariant).
- `suspects package-lock.json` exits 0 with no hits and does not raise
  `ScopeError`.

## Verification

```
just gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. README's `suspects` section names the built-in skip list and points at
   `.reflockignore` for anything else. Re-stamp the file.
3. `ROADMAP.yaml` marks BUG-11 `done`.
