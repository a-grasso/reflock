# BUG-06 acceptance contract: suspects scans inside inline code spans

Source: review 2026-07-28
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D2](DECIDED.md#d2-inline-code-spans-are-not-references), [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

BUG-02 exempted inline code spans from reference parsing, per D2: a markdown
renderer treats span content as literal text, and any document explaining
reflock's own grammar otherwise produces false findings.

`cmd_suspects` never got the same treatment. It skips fenced blocks but scans raw
lines, so a path named in backticks in prose is reported as a suspect:

```markdown
Older versions wrote to `build/legacy/out.json`, which no longer exists.
```

`suspects` is explicitly an advisory heuristic, and D2 already accepts the
converse cost ("a genuine reference someone wrapped in backticks silently stops
being checked"). But a path in backticks is usually prose *about* a path, and
this is the exact false-positive class D2 exists to remove - false positives are
what destroy trust in a gate.

## Required behavior

`cmd_suspects` masks inline code spans in markdown before scanning for
path-shaped tokens, using the same `mask_code_spans` helper and the same
`is_md` condition `parse_refs` uses. Fenced blocks stay skipped as they are.

For non-markdown files (`--all`), lines are scanned raw, exactly as
`parse_refs` does: a backtick in a `.py` or `.rs` file is not a markdown code
span, and treating it as one would blind the heuristic inside ordinary string
literals.

## Explicitly out of scope

- Any change to what `PATHISH` matches, to the `.gitignore` second pass, or to
  the `--all` flag's meaning.
- Making `suspects` part of `make gate`. It stays advisory - it exits nonzero
  whenever it has anything to say.
- Warning that a suspect was suppressed by a code span. D2 accepted silence for
  the reference case; the heuristic gets no louder treatment.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified - all five
  `suspects-*` fixtures included.
- A path-shaped token in ordinary prose is still a suspect.
- A path inside a fenced block is still skipped.
- `suspects --all` on a code file behaves exactly as today.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `suspects-ignores-inline-code-span` | a dangling path in backticks is not reported, while an identical path in prose on the next line is |
| `suspects-code-file-backticks-still-scanned` | with `--all`, a backticked path in a `.py` file is still a suspect - backticks are not code-span syntax there |

## Unit tests to add

- A dangling path in a code span is not a suspect.
- The same path in prose on the same line *is* a suspect (masking must not
  suppress the rest of the line - the BUG-02 lesson).
- A resolvable path in a code span stays unreported, as before.
- Double-backtick spans are exempt too.
- An unterminated backtick does not silence the rest of the line.
- `--all` on a `.py` file: a backticked path is still reported.

## Verification

```
make gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. README's `suspects` mention notes that code spans are exempt, on the same
   basis as references. Re-stamp the file.
3. `ROADMAP.yaml` marks BUG-06 `done`.
