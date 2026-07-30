# BUG-10 acceptance contract: `suspects` reports a truncated path

Source: kai-crm dogfooding 2026-07-30
Owner: agent · Tier: near · Touches: [reflock_lib/grammar.py](../reflock_lib/grammar.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

`PATHISH` caps the extension at six characters:

```python
r"...[\w.\-]+\.[A-Za-z][A-Za-z0-9]{0,5}"
```

An extension longer than that is not rejected - it is *silently truncated*, and
the truncated form is what gets printed:

```
platform/mvnw:111  .mvn/wrapper/maven-wrapper.proper   [bare path, does not resolve]
```

The source says `maven-wrapper.properties`. reflock reported a path that appears
nowhere in the file, then asserted it does not resolve - which is trivially true
of a string nobody wrote. Two failures in one line of output: the finding is
unactionable (grep for it and you find nothing), and it is self-evidently wrong
to a reader, which costs the whole report its credibility.

The truncation is also load-bearing in the wrong direction: `.properties` files
are exactly the config-file class reflock wants to reference, and today no
reference to one can ever be matched whole.

## Required behavior

The extension must match to its own end or not at all. Two changes, together:

- Cap widened from 5 trailing characters to 9, so the longest extensions that
  actually appear in a repo fit: `.properties` (10 with the leading letter),
  `.markdown` (9), `.gradle`, `.kotlin_module`-length names are past it and
  correctly unmatched.
- A `(?!\w)` boundary after the extension, so a token is matched whole or
  skipped. This is the part that fixes the defect; the widened cap is what
  keeps the fix from turning every `.properties` mention into silence.

A cap remains - it is what keeps `and/or something.Nevertheless` out - but it
now bounds *which tokens match*, never *what a matched token looks like*.

## Explicitly out of scope

- Extensions longer than 10 characters total. They stay unmatched, silently, as
  a bounded and deliberate blind spot; a suspect never reported is the failure
  mode this heuristic is allowed to have (it is advisory), whereas a suspect
  reported wrong is not.
- The dotless-file case (`Justfile`, `LICENSE`). `PATHISH` requires an
  extension by design and that is unchanged.
- Reference parsing, which never used `PATHISH`.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified. In
  particular `suspects-ignores-version-like-token` (`Opus 4.8/4.7/4.6`) must
  still report nothing: the widened cap must not make a version string
  path-shaped.
- Every token `suspects` prints appears verbatim in the source line it cites.
  This is the invariant the defect violated, and it is stated here as a
  property, not an example.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `suspects-reports-long-extension-whole` | with `--all`, a dangling `conf/app.properties` in a script is reported with its full extension, and the reported token appears verbatim in the file |

## Unit tests to add

- A dangling `conf/app.properties` is reported as `conf/app.properties`, not
  `conf/app.proper`.
- `a/b.markdown` is reported whole.
- A token whose extension exceeds the cap yields no match at all - asserted on
  `PATHISH` directly - rather than a truncated one.
- A property test over the `suspects` output: for every hit, the reported target
  is a substring of the cited source line. Runs over a fixture line carrying
  several extension lengths, so the guarantee is checked as a guarantee.
- `Opus 4.8/4.7/4.6 today` still yields nothing (explicit regression lock, kept
  as a unit test as well as its fixture, because the widened cap is what puts
  it at risk).

## Verification

```
just gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. `ROADMAP.yaml` marks BUG-10 `done`.
