# BUG-15 acceptance contract: bracketed link text is not a wiki-link

Source: [issue #19](https://github.com/a-grasso/reflock/issues/19), reported against 0.4.0
Owner: agent · Tier: near · Touches: [reflock_lib/grammar.py](../../reflock_lib/grammar.py), [test_reflock.py](../../test_reflock.py), [fixtures/](../../evalbench/fixtures/)
Locked decisions: [D4](DECIDED.md#d4-wiki-link-resolution-relative-first-then-unique-basename)

## The defect

A markdown link whose *text* is itself bracketed - the common "back to index"
footer form - is reported as a dangling wiki-link:

```markdown
[[Back to README]](../README.md)
```
```
docs/guide.md:3  Back to README   [no such file: Back to README]
```

`WIKI_LINK` takes `Back to README` - the display text - for a target. It is not
a path, so it never resolves. Worse than the noise: `MD_REF`'s link text is
`[^\]]*`, which cannot cross the inner `]`, so the *real* reference on the line
(`../README.md`) is not indexed at all. A false finding stands in for a missing
one.

CommonMark and GitHub both render `[[text]](target)` as a link labelled
`[text]`; there is no wiki-link in it. Obsidian renders the same source as a
wiki-link followed by a literal `(../README.md)`, but an author writing for
Obsidian has `[[README|Back to README]]` and would not produce this shape. The
markdown link is the reading that carries a checkable target, and it is the
reading reflock takes.

## Required behavior

One rule, applied to both patterns: **a `]` followed directly by `(` belongs to
the innermost link.**

- `MD_REF`'s link text admits one level of balanced brackets, as CommonMark
  does - except a nested group followed by `(`, which is itself an inline
  link's label and belongs to that inner link.
- `WIKI_LINK` does not match a `[[…]]` followed directly by `(`: that is link
  text, and `MD_REF` now owns the construct.

```
[[Back to README]](../README.md)  -> one reference, md, target ../README.md
[[loader|the loader]](loader.md)  -> one reference, md, target loader.md
[![alt](i.png)](t.md)             -> one reference, md, target i.png  (unchanged)
[see [ADR-1](adr.md) first](o.md) -> one reference, md, target adr.md (unchanged)
See [[loader]] (the loader).      -> one reference, wiki, target loader
See [[loader]] here.              -> one reference, wiki, target loader
```

"Directly" is the whole rule: the `(` must follow the `]]` with nothing between,
which is exactly the condition under which `MD_REF` claims the construct. A
parenthetical merely adjacent to a wiki-link keeps its wiki-link, because
`MD_REF` does not match there either. The two patterns never both own one
construct, and neither leaves one unowned.

The rule lives in the patterns themselves, not as an overlap filter in
`parse_refs`: it is a statement about what each form *is*, and a reader of the
grammar should not have to find it elsewhere.

## Explicitly out of scope

- Reporting *both* references in a nested link (`[![alt](i.png)](t.md)` - image
  and outer target). Which one wins is now stated rather than accidental;
  reporting both needs a second pass over link text, and no one has asked.
- Obsidian's reading of `[[x]](y)`. Choosing the markdown link means a repo that
  really meant the wiki-link loses that reference; per D4 the wiki-link form is
  a convenience over the markdown link, not a replacement, and the alias syntax
  covers the intent without the ambiguity.
- Link text nested more than one level deep. CommonMark balances arbitrarily;
  one level covers the reported shape and keeps the pattern linear-time.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- Pins on both forms still round-trip: `[[x]](y.md)<!--@-->` is stamped as the
  markdown link it is, and `[[x]]<!--@-->` as a wiki-link.
- `pin_span` offsets stay correct relative to the original line.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `md-bracketed-link-text-not-a-wikilink` | the issue's line, in a subdirectory, is reported as the markdown link it is: `UNSTAMPED` on `../README.md`, then stamps, checks clean, and drifts when the README changes |

## Unit tests to add

- `[[Back to README]](../README.md)` yields exactly one ref: `kind="md"`,
  `wiki=False`, target `../README.md`.
- The alias form `[[loader|the loader]](loader.md)` likewise yields one ref.
- `[![alt](i.png)](t.md)` still yields exactly one ref, to `i.png`.
- `[see [ADR-1](adr.md) first](o.md)` still yields exactly one ref, to `adr.md`.
- `See [[loader]] (the loader).` still yields one wiki-link ref to `loader` -
  adjacency is not the same as the link syntax.
- `[[x]](t.md)<!--@-->` stamps to a hex pin and then verifies `OK`.
- The issue's exact line in a nested file verifies `OK` rather than `DANGLING`.

## Verification

```
just gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. `ROADMAP.yaml` lists BUG-15 under `done`.
3. Issue #19 closed with the release that carries the fix.
