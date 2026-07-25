# NS-02b acceptance contract: wiki-links

Source: [northstar #2](../NORTHSTARS.md#2-markdown-link-forms-beyond-texttarget-near)
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)
Locked decisions: [D4](DECIDED.md#d4-wiki-link-resolution-relative-first-then-unique-basename), [D2](DECIDED.md#d2-inline-code-spans-are-not-references), [D3](DECIDED.md#d3-zero-runtime-dependencies)

Second half of northstar #2. Land NS-02a first - both touch `parse_refs` and
sequencing them avoids a conflict on every hunk.

## Required behavior

```markdown
See [[loader]] and [[0013-prompts-as-resources#loader|the loader]].
```

- An anchor after `#` and an alias after `|` are both handled. The alias is
  display text and never part of the target.
- A `|` inside alias text must not corrupt the target: split the target at the
  **first** `|` only.
- Pin placement matches the inline form - a trailing comment on the same line,
  including the existing tolerance for sentence punctuation between the link and
  the marker.
- `kind` stays `md`.

### Resolution

Per D4, in order:

1. As a path relative to the referring file, with `.md` appended when the target
   carries no extension.
2. Failing that, by basename across the index, when exactly **one** file matches.

An ambiguous basename is `DANGLING`, candidates listed in the detail, sorted for
determinism:

```
ambiguous: docs/loader.md, spec/loader.md
```

**No fifth verdict.** Do not add `AMBIGUOUS`, do not change the JSON schema, do
not change exit codes. `DANGLING` already means "does not resolve to one thing".

The basename index is built from the file set already held in `Index`. Do not add
a second directory walk.

Anchors resolve against whichever file won, by either route.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- Fenced blocks and code spans stay exempt (D2).
- `pin_span` is the `(start, end)` of the hex within the source line.
- `PIN_STRIP` and `normalize` untouched.
- Parsed only in `.md` / `.markdown`.
- Verdict set stays at four.
- No new imports outside the stdlib (D3).
- A wiki-link that resolves by the relative route must resolve identically to
  how the inline form would resolve the same path. Two resolution results for
  one path is a bug.

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `md-wikilink-ok` | resolves to a sibling `.md` file, `.md` implied |
| `md-wikilink-explicit-extension` | an explicit `.md` in the target works, no double-suffixing |
| `md-wikilink-anchor` | an anchor after `#` resolves |
| `md-wikilink-alias` | alias after `|` excluded from the target |
| `md-wikilink-alias-contains-pipe` | only the first `|` splits |
| `md-wikilink-basename-fallback-ok` | a target that is not a valid relative path resolves by unique basename |
| `md-wikilink-basename-ambiguous` | two same-basename files give `DANGLING` with both candidates in the detail |
| `md-wikilink-dangling` | no relative match and no basename match is `DANGLING` |
| `md-wikilink-stamp-roundtrip` | `stamp` then `check` is `OK`; edit the target, `check` is `DRIFTED` |
| `md-wikilink-basename-becomes-ambiguous` | a pinned basename-resolved link goes `DANGLING` once a second same-basename file is added - a true finding, not noise |
| `md-wikilink-in-fence-ignored` | inside a fence is not parsed |

## Unit tests to add

Direct `parse_refs` assertions:

- Every combination of anchor and alias present or absent.
- Alias containing a `|`.
- A pre-existing pin - exact `pin` and `pin_span`.
- Fence skipping.

Plus resolution unit tests for the two-step order, including the ambiguous case
and the detail string's sort order.

## Verification

```
make test && make bench && make check && make suspects
```

## Definition of done

1. All fixtures and unit tests above pass; nothing existing was modified.
2. README documents the form and, explicitly, that resolution is relative-first
   then unique-basename - **and that this is not full Obsidian fidelity**. A user
   with a vault needs to know where the boundary is. Re-stamp the file.
3. Northstar #2 is now fully true and is **deleted** from
   [NORTHSTARS.md](../NORTHSTARS.md), per that document's own rule.
4. `ROADMAP.yaml` marks NS-02b `done`.
