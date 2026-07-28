# NIT-01 acceptance contract: review nits too small for their own items

Source: review 2026-07-28
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

Last in the queue on purpose: both touch code the items above rewrite, so doing
them earlier would have produced conflicts for no benefit.

## 1. `unit_text` is annotated with a type it never returns

```python
def unit_text(idx: Index, path: str, anchor: str | None) -> str | list | None:
```

It returns `"\n".join(...)`, `""`, or `None`. The `list` is a leftover from an
earlier shape and is now a false statement about the function in the one place a
reader looks first.

**Required:** the annotation is `str | None`. A test asserts `list` does not
appear in it - the defect, rather than the exact spelling, so reformatting the
signature does not fail the suite.

## 2. References on one line are not in column order

`parse_refs` applies its patterns in sequence and appends each pattern's matches,
so a line carrying two *kinds* of reference reports them grouped by kind rather
than left to right:

```markdown
See [[wiki]] and [inline](t.md) on one line.
```

`finditer` is left-to-right, so this is invisible for a line whose references are
all the same kind - which is why it has gone unnoticed. `cmd_explain` sorts by
`col` before printing; `cmd_check` does not. So the two commands can list the
same line's references in different orders, and `explain`'s claim that it "reuses
the same `classify` logic, so it can never disagree with `check`" holds for
verdicts while the *ordering* quietly differs.

**Required:** `parse_refs` returns references in `(line, column)` order, so
every consumer inherits it. `cmd_explain`'s local sort then becomes redundant and
is removed rather than left as a second guarantee of the same thing - one place
must own the ordering, or this recurs.

## Explicitly out of scope

- Any change to which references are found, to verdicts, or to the JSON schema.
  Ordering only.
- De-duplicating a target matched by two patterns. No line does that today, and
  deciding what should win is a grammar question, not a nit.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
  `multiple-refs-per-line` in particular must keep passing - its references are
  one kind, so the order it asserts is already column order.
- Reference *discovery* is unchanged: same references, same verdicts, same
  counts.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `mixed-ref-kinds-one-line-column-order` | a wiki-link, an inline link and a REF comment on one line are reported left to right by `check --json`, and `explain` on that line lists them in the same order |

## Unit tests to add

- A line with a wiki-link *before* an inline link yields them in that order from
  `parse_refs` (the wiki pattern runs last, so this fails before the fix).
- `check --json` findings for such a line are in ascending column order.
- `explain` on that line lists the references in the same order `check` does -
  asserted against each other, not against a hardcoded expectation, since the
  point is that they agree.
- `unit_text`'s return annotation does not mention `list`.
- Reference count and verdicts for a mixed line are unchanged by the ordering
  fix.

## Verification

```
make gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. `cmd_explain` no longer sorts - `parse_refs` owns the order.
3. `ROADMAP.yaml` marks NIT-01 `done`.
