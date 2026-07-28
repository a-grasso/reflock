# UX-02 acceptance contract: `backlinks` human output has no total count

Source: AXI adoption review 2026-07-28 ([kunchenguid/axi](https://github.com/kunchenguid/axi) principle 4, "pre-computed aggregates")
Owner: agent · Tier: near · Touches: [reflock_lib/commands.py](../reflock_lib/commands.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format)

## The defect

`check --format human` ends with `"{problems} problem(s)."` or
`"All references OK."`. `stamp --check` ends with `"{N} pin(s) would be
stamped."` or `"Nothing to stamp."`. `suspects` ends with `"{N}
suspect(s)."` or `"No bare-path suspects."`. Every list-shaped command in
reflock states its total as the last line of human output - except
`backlinks`, whose human renderer lists rows and stops:

```
$ reflock backlinks docs/spec.md
a.md:12  docs/spec.md#overview  pinned
b.md:3   docs/spec.md           unpinned
```

A caller (human or agent) that wants "how many referrers does this file
have" has to count lines. Every sibling command already answers that
question inline; `backlinks` is the one inconsistency, not a considered
choice - `render_backlinks_human`'s empty-list branch already prints
`"No backlinks to {target}."`, so the *definitive-empty-state* half of this
was done and the *count-when-non-empty* half was not.

## Required behavior

`render_backlinks_human` prints one trailing count line after the rows, in
the same `"{N} <noun>(s)."` shape the other three renderers use:

```
$ reflock backlinks docs/spec.md
a.md:12  docs/spec.md#overview  pinned
b.md:3   docs/spec.md           unpinned

2 backlink(s).
```

- The blank line before the count matches `check`'s and `suspects`'
  spacing (`\n{msg}`).
- Singular/plural is not special-cased (`"1 backlink(s)."` is the existing
  convention for every sibling renderer - `check`'s `"1 problem(s)."` is the
  precedent, not a new decision).

## Explicitly out of scope

- `render_backlinks_json`. Its shape is a bare array with no count field.
  Adding one would be a schema change, which is exactly what D1 protects for
  `check`'s JSON output and, for consistency, is not carved out selectively
  for `backlinks` either - see BUG-07's contract for why the error path
  could add a *new* shape (there was none before) while this contract does
  not touch an *existing* one.
- `check`, `stamp --check`, `suspects` human output - already correct.
- Any change to `explain`'s human output. It is a detail view for one
  reference; a "how many" total does not apply (AXI principle 9's own
  "omit when self-contained" rule for detail views, applied here to
  aggregates by the same reasoning).

## Invariants

- `render_backlinks_json`'s output is byte-identical to today.
- The empty-list message (`"No backlinks to {target}."`) is unchanged - it
  already is a definitive empty state and does not need a redundant "0
  backlink(s)." beneath it.
- Exit codes are unchanged (`backlinks` always returns 0 on its own success
  path; this contract adds no new error).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `backlinks-lists-referrers-with-count` | two referrers to the same target print both rows followed by a blank line and `2 backlink(s).` |
| `backlinks-none-exits-zero` (existing) | still passes unmodified - the empty-list message gets no count line appended |

## Unit tests to add

- One referrer: output ends with `"\n\n1 backlink(s)."`.
- Two referrers: output ends with `"\n\n2 backlink(s)."`.
- Zero referrers: output is exactly `"No backlinks to {target}.\n"` - no
  count line appended (regression guard for the existing empty-state
  message).
- `--format json` output is byte-identical with and without this change
  (same rows, no `count` key).

## Verification

```
make gate
```

## Definition of done

1. Fixtures and unit tests above pass; every existing test stays green
   unmodified.
2. README's `backlinks` paragraph mentions the trailing count line.
3. `ROADMAP.yaml` adds UX-02 as `done`.
