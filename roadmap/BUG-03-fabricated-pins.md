# BUG-03 acceptance contract: stamp fabricates a pin for targets it cannot hash

Source: review 2026-07-28
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies), [D4](DECIDED.md#d4-wiki-link-resolution-relative-first-then-unique-basename)

## The defect

`classify()` resolves a target through `resolve_target()`. `plan_stamp()` does
not - it re-derives the path itself from `ref.target`. For any target that is
not an indexed text file, that re-derivation produces a path `unit_text()`
cannot read, `unit_text()` returns `""` for it, and `stamp` writes the
fingerprint of the empty string into the user's file:

```
External [x](https://example.com/spec)<!--@-->
Outside  [y](../outside.md)<!--@-->
Dir      [z](sub)<!--@-->

$ reflock stamp
Stamped 3 pin(s).

External [x](https://example.com/spec)<!--@e3b0c442-->     # sha256("")
Outside  [y](../outside.md)<!--@e3b0c442-->
Dir      [z](sub)<!--@e3b0c442-->
```

`check` returns `OK` for these kinds *before* it compares the hash, so it never
contradicts the pin. The user is left with a reference that claims to be
blessed at a content hash, is not watching anything, and will never report
`DRIFTED`. That is a silent false negative on the tool's central promise, and
`stamp --check` actively steers the user into it by reporting the pins as
pending work.

A binary target is the same defect by a different route: it *is* an indexed
file, but `idx.lines` has no text for it, so it hashes to `e3b0c442` too, and
every binary target in a tree shares one fingerprint.

## Required behavior

`stamp` writes a fingerprint only for a reference whose target resolves to an
indexed text file with a resolvable unit. For every other reference it leaves
the pin exactly as it found it, and `stamp --check` does not report it.

Skipped, silently, pin untouched:

| Target | Why |
|---|---|
| external (`https://…`) | not in the tree; nothing to hash |
| outside the tree (`../x.md`) | deliberately unresolved, per `resolve_path` |
| a directory | no content of its own |
| dangling (no such file, ambiguous basename) | already skipped today |
| an anchor that does not resolve | already skipped today |
| an existing file with no indexed text (binary) | `""` is not its content |

Stamped, as today:

- any indexed text file, with or without an anchor
- a **genuinely empty** text file. `e3b0c442` is the honest fingerprint of an
  empty file, and the fix must not confuse "empty" with "unhashable" - this is
  the positive control that proves the skip list is not over-broad.

## How, not just what

The two call sites must be unified, not patched in parallel. PR #12 flagged
this duplication as a review risk before it was known to be live: any ref kind
with custom resolution has to be wired into both `classify()` and
`plan_stamp()` or `stamp` mis-resolves what `check` gets right. Wiki-links were
wired into both; this bug is the case that was not.

`plan_stamp()` must obtain its path from `resolve_target()` - the same function
`classify()` uses - so that a future ref kind cannot resolve one way for `check`
and another for `stamp`. Introduce one helper that answers "what text would
`stamp` hash for this reference, if any", and have `plan_stamp()` use only that.

### Amendment: the advice `check` gives must stay true

Found while writing this item's fixtures. Of the skipped kinds, exactly one
still reaches the pin comparison in `classify()`: a binary target is an indexed
file, so it is `UNSTAMPED` with detail `run: reflock stamp`. Once `stamp`
correctly refuses to stamp it, that advice names a command that provably does
nothing - `check` nags, `stamp` no-ops, and the user has no way to read the
loop.

So `classify` must give an unstampable opted-in pin a detail that says why,
instead of prescribing a command that cannot help. Verdict stays `UNSTAMPED`,
exit codes and the JSON schema are untouched - `detail` is free text and this is
the same class of change as `DANGLING`'s `ambiguous: …`. This is not a widening
of the item: shipping the fix without it would replace a silent wrong answer
with a misleading one.

## Explicitly out of scope

- Any change to `check`'s **verdicts**. A pinned external link stays
  `OK external`; changing that is a verdict-semantics decision, not this bug.
- Warning about a pin on an external, outside-tree or directory target. Those
  never reach the pin comparison at all, so surfacing them means changing what
  `OK` means - a reporting decision worth its own item.
- `unit_text()`'s `""`-for-binary return. `check` depends on it and a test pins
  it; this item stops `stamp` from *acting* on it.
## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- `stamp` on an ordinary reference behaves exactly as today, including
  `--rebless`.
- After this fix, no pin anywhere in a stamped tree holds `e3b0c442` unless its
  target is a genuinely empty text file.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `stamp-skips-unhashable-targets` | external, outside-tree, directory and binary targets keep `<!--@-->` after `stamp`; the tree is byte-identical to before it ran |
| `stamp-check-ignores-unhashable-targets` | `stamp --check` on that same tree exits 0 and says nothing is to be stamped |
| `stamp-rebless-does-not-fabricate` | with a hand-written wrong pin on an unhashable target, `--rebless` leaves it alone rather than rewriting it to `e3b0c442` |
| `stamp-empty-file-target-is-stamped` | a reference to an existing empty `.md` file *is* stamped, proving the skip is not over-broad |

## Unit tests to add

- One per skipped kind: after `stamp`, the pin is still empty.
- `plan_stamp` reports an empty edit set for a tree of only unhashable pins.
- An empty text file target is stamped, and its pin is `fingerprint("")`.
- `--rebless` does not rewrite a pin on an unhashable target.
- A test asserting `plan_stamp` resolves through `resolve_target`: for a
  wiki-link that resolves by unique basename, the path `stamp` hashes is the
  same path `classify` resolved. (Guards the unification itself, not just its
  effect today.)

## Verification

```
make gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. `plan_stamp` no longer re-derives a path; `resolve_target` is the only
   resolver.
3. `ROADMAP.yaml` marks BUG-03 `done`.
