# PERF-01 acceptance contract: check re-hashes the same unit once per reference

Source: review 2026-07-28
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

reflock's opening claim is that there is nothing expensive in the hot path:

> everything here is grep, a hashmap lookup, and a byte compare

But `classify()` recomputes the target's unit text and fingerprint for *every*
reference, so N references to one file hash that file N times. Measured on 400
pinned references to one 4 MB file:

```
build_index      0.06s
parse_refs       0.20s   (400 refs)
classify (all)  55.52s   <- 400 x 0.138s, one full re-hash per reference
```

56 seconds for a check whose docstring promises a hashmap lookup. The cost is
not sha256 (which would be ~5 ms for 4 MB) but the two regex passes in
`normalize()`.

A heavily-cited document is not an exotic case - it is the *motivating* case.
The design is "many references, one authority", so the most-referenced file in a
tree is exactly the one that gets rehashed most.

## Required behavior

### 1. One fingerprint per distinct unit

A unit is identified by `(path, anchor)`. Its fingerprint is computed at most
once per `Index`, and every reference to it reuses that value. Verdicts must be
byte-identical to today's for every input.

The cache lives on the `Index`, not in module state: an `Index` is one snapshot
of one tree, and a process-wide cache would leak between the repeated
`build_index` calls the tests and the bench make.

`stamp` mutates files, so it must not read a fingerprint computed before its
write. In practice pins are invisible to `normalize()` - `PIN_STRIP` removes
them, which is why stamping does not cascade drift - so a stale entry would
still be correct. Do not rely on that: invalidate explicitly, and say in a
comment why the invalidation is belt-and-braces rather than load-bearing.

### 2. normalize() without the regex pass

`re.sub(r"\s+", " ", text)` is the entire per-unit cost. `" ".join(text.split())`
is the same transformation, done in C.

This changes how *every* fingerprint in the world is computed, so it needs
proof of equivalence, not an assurance: the two forms must be shown identical
across whitespace classes where `str.split()` and `\s` are known to differ or
be suspected of differing - ASCII whitespace, `\x1c`-`\x1f`, `\x85`, `\xa0`,
` `, ` `, and the empty string. If any input disagrees, keep the regex
and report it; a 2x speedup is not worth invalidating stamped pins in the field.

## Explicitly out of scope

- Caching across processes or runs. That is NS-08 (incremental indexing) and it
  is human-owned.
- Lazy indexing, or not reading files reflock will not use. Same item.
- Any change to the fingerprint *value* for any input. This item is a pure
  speedup; if it changes one hash, it has failed.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified. The
  fingerprints they hardcode (`4f66db61`, `e3b0c442`, …) must not move.
- `reflow-whitespace-invariant` and `span-anchor-drift` keep passing - they are
  the fixtures that pin normalize()'s semantics.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `perf-many-refs-one-target` | 12 references to one anchored target all resolve, and a drift in that target is reported for every one of them - correctness under memoization, end to end |

## Unit tests to add

Mechanism, not wall-clock — a timing assertion would be flaky in CI:

- `normalize` is called **once** when 20 references share one `(path, anchor)`,
  and once per distinct anchor when they differ (asserted by counting calls).
- The cache is per-`Index`: a second `build_index` recomputes.
- Verdicts for a tree of many references are identical with and without the
  cache (compute the expected set by hand from `unit_text`/`fingerprint`).
- `normalize` equivalence: for every input listed above, the new form equals
  `PIN_STRIP` + `re.sub(r"\s+", " ")` + `.strip()`, byte for byte.
- After `stamp` writes, a fingerprint read from the same `Index` reflects the
  file on disk (guards the invalidation).
- A drift *does* still get detected after a target edit within one process.

## Verification

```
make gate
```

Plus a recorded before/after on the 400-reference case in the commit message.
Not a test - a number, so the claim in the docstring is checkable.

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified; no fingerprint
   changed.
2. The module docstring's "grep, a hashmap lookup, and a byte compare" is true
   for repeated references.
3. `ROADMAP.yaml` marks PERF-01 `done`.
