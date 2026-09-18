# BUG-16 acceptance contract: a literal underscore survives the slug

Source: [issue #14](https://github.com/a-grasso/reflock/issues/14), reported against 0.4.0
Owner: agent · Tier: near · Touches: [reflock_lib/engine.py](../../reflock_lib/engine.py), [test_reflock.py](../../test_reflock.py), [fixtures/](../../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

A heading carrying a `SNAKE_CASE` identifier gets an anchor nobody can link to:

```markdown
## 2026-08-24 MANUAL_PROCESSES was unsatisfiable

[with underscore](#2026-08-24-manual_processes-was-unsatisfiable)
```
```
t.md:7  #2026-08-24-manual_processes-was-unsatisfiable
        [no anchor '#2026-08-24-manual_processes-was-unsatisfiable' in t.md]
```

GitHub and GitLab both resolve that link: `_` is a word character and survives
their slug. `slugify` deletes it, in `engine.py`:

```python
s = re.sub(r"[*_~]", "", s)                     # emphasis markers
```

`*` and `~` are already removed by the next line's `[^\w\- ]`, so that line
exists solely to delete `_` - and it cannot tell an emphasis delimiter from a
character inside an identifier. The same-file control link without an
underscore resolves, which is what isolates the cause.

The cost is the one BUG-01 and BUG-13 were about: a blocking gate that reports
a problem which is not a problem stops being trusted, and real breaks are waved
through with the exit code. A repo with snake_case in headings gets a permanent
false `DANGLING`.

## Required behavior

GitHub slugs the *rendered* text, where the parser has already consumed
emphasis syntax and left literal underscores alone. reflock approximates that
rather than deleting the character:

```
2026-08-24 MANUAL_PROCESSES was unsatisfiable -> 2026-08-24-manual_processes-was-unsatisfiable
snake_case_name                               -> snake_case_name
_italic_ heading                              -> italic-heading
__bold__ heading                              -> bold-heading
_MANUAL_PROCESSES_                            -> manual_processes
a _b_ c_d                                     -> a-b-c_d
*star* and ~strike~                           -> star-and-strike
```

The rule: a run of one or two `_` is emphasis syntax when it opens at a
non-word boundary, closes at one, and wraps non-space content - CommonMark's
flanking rules, as much of them as a regex can carry. Everything else is a
character in a word. `_MANUAL_PROCESSES_` falls out of the rule rather than
being special-cased: the interior `_` is followed by a word character so it
cannot close, and the pair spans the whole token, exactly as CommonMark reads
it.

`*` and `~` need no clause of their own. Neither is a word character, so the
existing `[^\w\- ]` pass removes them whether they are emphasis or literal -
which is also what GitHub produces.

## Explicitly out of scope

- Full inline-emphasis parsing. `_ a _`, intraword `*`, and delimiter runs
  longer than two are left to the approximation; the failure mode is a slug
  that differs from GitHub's on a heading nobody writes.
- Unpaired leading underscores (`## _draft notes`). GitHub keeps the `_`; so
  does this rule, since a run that never closes is not emphasis. Called out
  because it is the shape the old line got wrong in the opposite direction.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified - in
  particular the double-hyphen and code-span cases (BUG-01).
- `*bold*` and `~strike~` headings slug exactly as before.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `anchor-heading-with-underscore` | the issue's file: a link to a `SNAKE_CASE` heading anchor is `OK`, and the emphasis control in the same file still slugs without its markers |

## Unit tests to add

- The table above, asserted case by case through `slugify`.
- The issue's reproduction end to end: both links in one file verify `OK`.
- A heading whose underscore run never closes keeps the underscore.

## Verification

```
just gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. `ROADMAP.yaml` lists BUG-16 under `done`.
3. Issue #14 closed with the release that carries the fix.
