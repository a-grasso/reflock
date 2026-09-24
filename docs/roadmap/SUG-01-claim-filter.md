# SUG-01 acceptance contract: not every link is worth a pin

Source: [issue #20](https://github.com/a-grasso/reflock/issues/20)
Owner: agent · Tier: near · Touches: [reflock_lib/suggest/claims.py](../../reflock_lib/suggest/claims.py), [test_reflock.py](../../test_reflock.py), [evalbench/fixtures/](../../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The problem

`reflock suggest` harvests every unpinned, whole-file markdown reference in
scope, but not every link makes a claim about its target. A pin says "this
sentence depends on what that text says"; a navigation link - a row of an
index table, an entry under "See also" - depends only on the target existing,
which `check` already verifies unpinned. A pin there fires on every edit of
the target and is right never, which is how a gate learns to be ignored.
Placing pins on that population would make `suggest`'s own output the thing
that teaches people to ignore reflock.

## The decision

Two cheap, shape-based rules, not a claim classifier, measured against 585
references an LLM judge labelled on a real repository (kai-crm, 2026-09):

- **Under a navigation heading.** `claims.NAV_HEADING` matches the *whole*
  nearest heading above the link - "see also", "related", "index", "table of
  contents", "further reading", "next steps", and similar - not a substring:
  "References" and "Related work" name prose sections as often as link lists,
  and substring matching dropped real claims wholesale. This rule alone drops
  203 non-claims and only 27 worth-pinning references.
- **Index-table row.** `claims.index_row` drops a table row whose first cell
  *is* the link (a catalogue entry), by checking the link is in the first
  `|`-delimited cell and that cell has two words or fewer once the link markup
  is stripped. Drops 4 non-claims, 0 worth-pinning.

Kept references are 63% worth a pin, against 42% before filtering. Two rules
that looked promising were measured out and rejected: dropping short
link-only list items (a principle list is a list of claims, so it removed
more real claims than navigation lists) and exempting "supersedes"/annotated
entries under navigation headings (it restored four non-claims for every
claim recovered).

## Explicitly out of scope

- Anything that reads link *text* or prose to judge intent - that is the
  anchor model's job (SUG-02), not the filter's. The filter is shape, not
  meaning, on purpose.
- Retuning the two rules against a different corpus. The numbers above are
  the measurement; changing the corpus is a new measurement, not a bug fix.

## Definition of done

1. `reflock_lib/suggest/claims.py`'s `pin_worthy`, `NAV_HEADING` and
   `index_row` implement the two rules as measured, matching whole headings
   only (`NAV_HEADING.fullmatch`, not `.search`).
2. Unit tests in `SuggestTest` pass:
   `test_filter_drops_links_under_a_navigation_heading` (a whole "See also"/
   "Related work" heading drops its links; a link under a prose heading that
   merely mentions "state" stays) and
   `test_filter_drops_index_rows_but_not_claims_in_a_table` (an index-style
   first-cell link is dropped; a claim inside a table cell's prose is kept).
3. `evalbench/fixtures/suggest-navigation-only/scenario.json` passes: a tree
   whose only unpinned references sit under a navigation heading or as index
   rows exits 0 with "nothing to suggest", before the `[suggest]` runtime is
   ever touched.
4. `just gate` is green.
5. `ROADMAP.yaml` lists SUG-01 under `done`.
