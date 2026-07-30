# BUG-13 acceptance contract: a hyphen re-opens a match mid-path

Source: kai-crm dogfooding 2026-07-30, verifying the BUG-08..12 fixes
Owner: agent · Tier: near · Touches: [reflock_lib/grammar.py](../reflock_lib/grammar.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

Found by re-running `suspects --all` on the repo that produced BUG-08 through
BUG-12, on a line where a real path was interpolated:

```
Justfile:213  share/index.html   [bare path, does not resolve]
```

The source reads `out="{{ showcase }}/dist-share/index.html"`. The lookbehind
`(?<![\w./$])` blocks a match at `dist-share/…` (preceded by `/`), but `-` is
not in the class, so the pattern restarts *inside* the segment and reports
`share/index.html` - a suffix of a path fragment, not a path anyone wrote.

This is BUG-08's defect with a different character. The general rule was missed
there: the lookbehind exists to stop a match starting in the middle of a token,
so it must exclude every character the segment class `[\w.\-]` admits. It
excluded `\w`, `.` and `/`, and BUG-09 added `$`, but never `-`.

It also technically satisfies BUG-10's invariant - `share/index.html` does
appear verbatim in the line - while violating its intent. The invariant should
have been "the reported token is the whole token", and a substring check was the
cheapest honest approximation of it. This item is the reason to state the
stronger version.

## Required behavior

`PATHISH`'s lookbehind excludes `-`, so the character class it excludes is the
segment class plus the separators it must not restart after:

```
(?<![\w./$-])
```

The rule is stated in the pattern's comment as a rule, not as a list of
characters patched one incident at a time: *no match may begin at a character
the segment class would have consumed.*

## Explicitly out of scope

- Paths *inside* archives. `xl/_rels/workbook.xml.rels` in a `zipfile.read()`
  call is a path in a zip member, is correctly unresolvable against the repo,
  and there is no shape distinguishing it from a repo path. It survives the
  five fixes and stays a known false positive; `.reflockignore` is the answer if
  it bothers a consumer.
- Template placeholder targets (`doc/adr/00NN-….md`). A `00NN` slot is a real
  unfilled placeholder and arguably worth reporting; no change either way.
- Interpolation syntax generally (`{{ x }}`, `%s`, `$1`). Only the mid-token
  restart is a defect; a bare path adjacent to interpolation is still a path.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- A hyphen *inside* a token still matches: `a/my-file.md` is unchanged.
- A markdown list item `- doc/x.md` is still a suspect - the space after the
  bullet is what the match starts on, not the hyphen.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `suspects-no-restart-inside-a-hyphenated-segment` | with `--all`, `"{{ dir }}/dist-share/index.html"` in a Justfile-shaped file yields nothing, while a hyphenated bare path on the next line is reported whole |

## Unit tests to add

- `{{ x }}/dist-share/index.html` yields no suspect.
- `a/my-file.md` is still reported, whole.
- `- doc/x.md` (markdown bullet) is still reported.
- A parameterised assertion over every character in the segment class: for each,
  `X` + a resolvable-looking token produces no match starting mid-token. This is
  the rule, tested as a rule, so the next such character cannot slip through as
  `@` and `-` did.

## Verification

```
just gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. `ROADMAP.yaml` marks BUG-13 `done`.
