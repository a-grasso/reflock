# BUG-01 acceptance contract: `slugify` misreads link syntax inside a heading code span

Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)

## The bug

`slugify` strips code spans first and only then reduces an inline link to its
link text.
Content that was inside backticks therefore gets re-parsed as markdown, which
GitHub never does - inside a code span, link syntax is literal.

Reproduction, against northstar #2's real heading in
[NORTHSTARS.md](../NORTHSTARS.md):

```
$ python3 -c "import reflock; print(reflock.slugify('2. Markdown link forms beyond \`[text](target)\` *(Near)*'))"
2-markdown-link-forms-beyond-text-near
```

GitHub produces `2-markdown-link-forms-beyond-texttarget-near`. A correct
in-repo link to that heading is reported `DANGLING`, and a link written to
reflock's slug is broken on GitHub - the same failure mode as closed issue #4,
where slug divergence produced a false positive.

The two rules collide in `slugify` in [reflock.py](../reflock.py): the code-span
unwrap runs first, and the link reduction then applies to its output.

## Required behavior

The link reduction applies only to link syntax that was **not** inside a code
span. Code-span content is preserved verbatim (minus the backticks) and never
re-parsed. All other slugify rules - emphasis stripping, punctuation removal,
per-space hyphens with no collapsing - are unchanged.

Implementation note, not a licence to redesign: protect code-span contents
before the link reduction and restore them after. Do not reorder the two rules,
which just moves the bug.

## Invariants

- All 40 unit tests and all 37 evalbench fixtures stay green, unmodified.
- The no-collapse behavior from issue #4 stays exactly as is.
- A heading containing a genuine inline link still reduces to that link's text
  (see the `See ...` row in the table below).

## Tests to add in `test_reflock.py`

Direct `slugify` assertions, each failing before the fix:

```
heading text                                    -> expected slug
2. Markdown link forms beyond `[text](target)` *(Near)*
                                                -> 2-markdown-link-forms-beyond-texttarget-near
Use `[a](b)` here                               -> use-ab-here
See [the loader](x.md)                          -> see-the-loader
Mixed [real](r.md) and `[fake](f.md)`           -> mixed-real-and-fakefmd
`a` and `b`                                     -> a-and-b
```

Cross-check each expectation against GitHub's own anchor generation before
trusting the table - the table is the intent, GitHub is the authority.

## Fixture to add

`evalbench/fixtures/heading-code-span-link-slug`: a target doc with a heading
containing link syntax inside a code span, and a source doc linking to the
GitHub-correct anchor. Asserts `OK`, not `DANGLING`.

## Verification

```
make gate
```

`suspects` is advisory and exits nonzero whenever it has
anything to say, so it is not part of the gate. Read its output, act on
anything real, but do not chain it.

## Definition of done

1. The fixture and all unit tests above pass.
2. Invariants hold.
3. Any in-repo link that was written around the old buggy slug is corrected -
   grep for anchors before assuming there are none.
4. `ROADMAP.yaml` marks BUG-01 `done`.
5. A PR is open. Nothing is merged.
