# BUG-02 acceptance contract: inline code spans are not references

Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)
Locked decisions: [D2](DECIDED.md#d2-inline-code-spans-are-not-references)

## The bug

`parse_refs` skips fenced code blocks but not single-backtick spans, so both
`MD_REF` and `CODE_REF` fire on link and REF syntax that a markdown renderer
treats as literal text. Any document that explains reflock's own grammar in
prose produces false `DANGLING` findings.

Hit three times while writing the first contracts in this queue, each time
forcing an author to restructure prose into a fenced block to appease the
checker.

## Required behavior

Content inside a single-backtick span is not parsed for references, matching the
existing treatment of fenced blocks.

```
See `[x](t.md)` for the syntax.       -> no reference
See [x](t.md) for the thing.          -> one reference
`# REF: t.md` is how you write it.    -> no reference
Mixed `[a](skip.md)` and [b](real.md) -> one reference, to real.md
```

Double-backtick spans (used to embed a literal backtick) are spans too and are
exempt on the same basis.

An unterminated backtick on a line is not a span. Do not let one stray backtick
silence the rest of the line - that would turn this fix into a way to hide
references by accident, which is worse than the bug.

## Accepted cost, do not "fix" it

Per D2: a genuine reference someone wrapped in backticks silently stops being
checked. This was judged the better trade. Do **not** add a warning, a new
verdict, or a heuristic that guesses intent.

## Interaction with other items

- `slugify` had the same root cause and was fixed separately in BUG-01. Do not
  touch `slugify`; this item is about `parse_refs`.
- NS-02a and NS-02b add new reference forms. Whatever exemption mechanism this
  item introduces must apply to those forms automatically when they arrive -
  i.e. mask spans once per line before matching, rather than teaching each
  pattern about backticks.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- Fenced-block skipping is unchanged.
- `pin_span` offsets for surviving references remain correct relative to the
  **original** line, not to any masked or rewritten copy. This is the trap in
  this item: if you mask spans by substitution, offsets shift and `stamp`
  splices into the wrong column. Mask with same-length filler, or map offsets
  back explicitly.
- Non-markdown files: `CODE_REF` exemption applies to backtick spans in
  markdown. Do not start interpreting backticks in `.py` or `.rs` sources.
- No new imports outside the stdlib (D3).

## Tests to add

Direct `parse_refs` assertions:

- Each of the four cases in Required behavior - reference count and target.
- A pinned reference following a code span on the same line: assert `pin_span`
  is correct, which catches the offset-shift trap above.
- Double-backtick span is exempt.
- A line with a single unterminated backtick still yields its reference.
- A REF comment inside a span in a markdown file is exempt, while the same text
  in a `.py` source file is still a reference:

```
docs.md:  `# REF: t.md`   -> exempt
code.py:   # REF: t.md    -> still a reference
```

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `inline-code-span-not-a-ref` | a code-span link to a missing file is not `DANGLING` |
| `inline-code-span-mixed-line` | a real link on the same line as a code-span link is still found and stamped at the right column |
| `inline-code-span-code-ref-exempt` | a REF comment inside a span in a `.md` file is exempt |

## Verification

```
make gate
```

`suspects` is advisory and exits nonzero whenever it has
anything to say, so it is not part of the gate. Read its output, act on
anything real, but do not chain it.

Expect `make check` findings to *decrease* or hold, never increase. This item
makes reflock see less, deliberately.

## Definition of done

1. Tests and fixtures above pass; nothing existing was modified.
2. Any place in this repo's docs where prose was restructured into a fence
   purely to dodge this bug may be restored to inline prose. Optional, but if
   you do it, `make check` must stay green.
3. README documents the exemption alongside the existing fenced-block rule.
4. `ROADMAP.yaml` marks BUG-02 `done`.
