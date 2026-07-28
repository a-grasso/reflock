# DOC-01 acceptance contract: the documented pre-commit rev names a tag without the manifest

Source: review 2026-07-28; version chosen by a human on the same day
Owner: agent · Tier: near · Touches: [README.md](../README.md), [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [release.yml](../.github/workflows/release.yml)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

ID-21's deliverable is a `.pre-commit-hooks.yaml` adopters consume by pinning a
tag. The README tells them which:

```yaml
repos:
  - repo: https://github.com/a-grasso/reflock
    rev: v0.1.0
```

`.pre-commit-hooks.yaml` exists in **no** tag - v0.1.0 through v0.1.4 - and not
on `main`; it was added on this branch. Copy-pasting the documented config gives
`InvalidManifestError`. The flagship deliverable of ID-21 is unreachable by the
only instructions provided for reaching it.

`__version__` was also `0.1.4` while the README said `v0.1.0`, four releases
behind, which is the same defect in a second place.

### The same drift, unguarded at release time

`release.yml` derives the published version from the pushed tag
(`${GITHUB_REF_NAME#v}`) and never compares it to `__version__`. So a tag can
ship a Homebrew formula whose `reflock --version` disagrees with the release it
came from, with nothing failing.

## Required behavior

1. `__version__` becomes `0.1.5`, the release that will contain the manifest.
2. The README's `rev:` names `v0.1.5`.
3. **A test ties them together**: the version in the README's pre-commit snippet
   must equal `__version__`. Neither can move without the other, which is what
   turns this from a fix into a fixed *class*. reflock cannot check this itself -
   a version string is not a cross-reference - so it belongs in the suite.
4. `release.yml` fails the release if the pushed tag's version does not equal
   `__version__`, before it publishes anything or touches the tap.

The tag itself is **not** cut here. Tagging is a release action and a human owns
it; this item makes the documentation correct the moment `v0.1.5` exists, and the
release workflow refuse if it never does.

## Explicitly out of scope

- Cutting or pushing `v0.1.5`, or editing the Homebrew tap.
- Deriving `__version__` from git describe, or any single-sourcing scheme. D3
  keeps reflock a single stdlib file with no build step, so a literal plus a test
  is the honest mechanism.
- A CHANGELOG. Nothing generates one here, and the global rule against
  hand-editing generated files means inventing one is a separate decision.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- `reflock --version` keeps its current output shape (`reflock X.Y.Z`).
- No new imports outside the stdlib (D3).

## Fixtures to add

None. A version string is not tree behavior, and `run_bench.py` runs reflock
against fixture repos - there is nothing for a fixture to observe here that the
unit tests do not already pin. Recorded rather than left implicit, since every
other item in this queue ships fixtures.

## Unit tests to add

- The README's pre-commit `rev:` equals `__version__` (the drift guard).
- `reflock --version` prints exactly `reflock <__version__>`.
- The README quotes a `rev:` at all, in the expected `vX.Y.Z` shape - so
  deleting the snippet cannot silently satisfy the guard above.
- `release.yml` contains the tag-vs-`__version__` check, so removing the guard
  fails the suite rather than only surfacing at release time.

## Verification

```
make gate
```

## Definition of done

1. Tests above pass; nothing existing was modified.
2. `ROADMAP.yaml` marks DOC-01 `done`, and the handover states that `v0.1.5`
   must be tagged by a human for the documented config to work.
