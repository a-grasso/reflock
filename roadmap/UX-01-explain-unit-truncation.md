# UX-01 acceptance contract: explain dumps the whole target file for a whole-file pin

Source: review 2026-07-28
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [README.md](../README.md), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format), [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

`explain` prints the unit text that was fingerprinted. For an anchored
reference that is the feature - the section under scrutiny, right there. For an
*unanchored* reference the unit is the whole file, so `explain` prints the whole
file:

```
$ reflock explain a.md:1        # [x](t.md) with no anchor, t.md is 43 lines
$ reflock explain a.md:1 | wc -l
50
```

A pinned reference to a 2000-line design document prints 2000 lines. The command
whose purpose is "everything about **one** reference" becomes unreadable exactly
where a reference matters most - a heavily-pinned authority file is usually a
long one.

## Required behavior

The unit text is **previewed**, not dumped, and the rule is uniform rather than
special-cased to whole-file units. A 900-line `##` section is as unreadable as a
900-line file, and a rule with one branch is easier to trust than one with two.

- Units up to `UNIT_PREVIEW_LINES` (40) print in full, exactly as today. Short
  units - the common case, and every existing fixture - are untouched.
- A longer unit prints its first 40 lines followed by one marker line stating
  how many lines were withheld and how to see them:

  ```
  … 1960 more lines (--full to show)
  ```

- `explain --full` prints the entire unit, with no marker. That is the escape
  hatch, and it is discoverable from the marker itself rather than from the
  README alone.

The limit is a named module constant, not a literal buried in the renderer.

### The JSON format is unchanged

`render_explain_json` already omits `unit_text` entirely, so there is nothing to
truncate there and no schema change. `--full` is accepted with `--format json`
and does nothing, because refusing it would make a scripted caller special-case
a flag that cannot matter. D1's "one renderer, one place" is satisfied: this is
one change in one function.

## Explicitly out of scope

- Truncating anything else. `check`'s report, `backlinks`' rows and the
  `DRIFTED` note are all bounded already.
- Paging, or shelling out to a pager. reflock writes to stdout and stops.
- A configurable limit. That is ID-12 (a config file) and it is human-owned; a
  flag plus a constant is enough until that exists.
- Showing a *diff* against the pinned text. Impossible by design - only the hash
  was ever stored - and `explain` already says so.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified. Every
  existing `explain-*` fixture targets a short unit, so none of them should see
  a marker line; if one does, the limit is wrong.
- Verdicts, exit codes and the JSON shape are untouched.
- `explain` stays read-only.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `explain-truncates-long-unit` | a 60-line whole-file unit prints the marker naming the withheld line count, and does not contain the last line of the file |
| `explain-full-shows-everything` | `--full` on the same tree prints the last line and no marker |
| `explain-short-unit-not-truncated` | a 5-line unit prints no marker at all, so the common case is provably unchanged |

## Unit tests to add

- A unit longer than the limit: output contains exactly the first 40 lines of
  the unit, plus the marker, and the marker's count equals the real remainder.
- The same tree with `--full`: the whole unit, no marker.
- A unit of exactly 40 lines: no marker (boundary).
- A unit of 41 lines: marker saying 1 more line.
- `--format json` output is byte-identical with and without `--full`.
- An anchored unit longer than the limit is truncated too - the rule is not
  whole-file-only.

## Verification

```
make gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. README's `explain` paragraph documents the preview and `--full`. Re-stamp the
   file.
3. `ROADMAP.yaml` marks UX-01 `done`.
