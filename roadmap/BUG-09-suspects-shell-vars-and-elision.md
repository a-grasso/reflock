# BUG-09 acceptance contract: shell variables and `.../` elisions are not paths

Source: kai-crm dogfooding 2026-07-30
Owner: agent · Tier: near · Touches: [reflock_lib/grammar.py](../reflock_lib/grammar.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

Two token shapes that no author intended as a reference are reported as
suspects.

**Shell variable interpolation.** `PATHISH`'s lookbehind excludes `[\w./]` but
not `$`, so a match starts immediately after the sigil and reports the variable
*name* as the first path segment:

```
platform/mvnw:117  scriptDir/.mvn/wrapper/maven-wrapper.proper   [bare path, does not resolve]
```

The source line is `"$scriptDir/.mvn/wrapper/maven-wrapper.properties"`. Nothing
called `scriptDir/` exists or ever will - the base is a runtime value.

**Elision idiom.** `.../` in prose means "some path under here, spelled short":

```
doc/plans/…/plan.mdx:15  platform/domain/.../domain/Signal.kt   [bare path, does not resolve]
```

That is a human writing a placeholder, not a reference. It is *correctly*
unresolvable and reporting it is noise. Seven of one repo's findings were this
one idiom in a single plan document.

## Required behavior

`PATHISH` does not match:

1. A token whose first segment is preceded by `$` - a shell/Make/CI variable
   reference, not a directory name. `${VAR}/a/b.c` is already unmatched (the
   `}` breaks the segment class) and stays that way.
2. A token containing a `...` path segment.

Both are grammar-level rules, in `PATHISH` itself, not filters in
`cmd_suspects`: `PATHISH` is documented as "a path-shaped token", and neither
of these is path-shaped. Keeping the judgement in one place is what stops
`suspects` and any future consumer of the pattern from disagreeing.

Note the consequence for rule 2, which is intended: `platform/domain/.../domain/Signal.kt`
yields *no* match at all rather than the two sub-paths either side of the
elision. The lookbehind blocks a restart after `/`, so `domain/Signal.kt` is
not separately reported. Reporting half of a placeholder would be worse than
reporting nothing.

## Explicitly out of scope

- Windows `%VAR%\path` and Make's `$(VAR)/path`. `$(` is already unmatched via
  the paren; `%VAR%` uses backslashes, which `PATHISH` never matched. Neither
  was observed.
- Actually *resolving* a variable by reading the surrounding script. Out of
  reach for a grep-shaped heuristic, and no design wants it.
- `..`/`.` prefixes, which are legitimate relative paths and stay matched.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- `../a/b.md` and `./a/b.md` still match - one leading dot segment or two is a
  relative path; three is an elision.
- A literal `$` elsewhere in a line does not suppress a genuine token after it.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `suspects-ignores-shell-variable-paths` | with `--all`, `"$scriptDir/.mvn/wrapper/x.properties"` in a shell script is not a suspect, while a genuine bare path on the next line is |
| `suspects-ignores-elided-path` | `platform/domain/.../domain/Signal.kt` in prose is not a suspect, and neither half of it is reported |

## Unit tests to add

- `$VAR/a/b.py` is not a suspect.
- `${VAR}/a/b.py` is not a suspect (regression lock on today's accident).
- A `.../` elision anywhere in a token yields no suspect, and specifically not
  the trailing `domain/Signal.kt` fragment.
- `../a/b.md` and `./a/b.md` are still suspects when dangling.
- A `$` earlier in the line does not suppress a later genuine token.
- `PATHISH` asserted directly for the elision case, since the "no partial
  match" guarantee is a property of the pattern, not of the command.

## Verification

```
just gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. `ROADMAP.yaml` marks BUG-09 `done`.
