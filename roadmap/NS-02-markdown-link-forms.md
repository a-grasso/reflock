# NS-02 acceptance contract: markdown link forms beyond the inline form

Source: [northstar #2](../NORTHSTARS.md#2-markdown-link-forms-beyond-texttarget-near)
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)

This contract is the definition of done. An agent implementing NS-02 may not
widen it, and may not resolve an ambiguity by choosing for itself - every
scoping call is already made below. If something here is wrong or
underspecified, stop and say so rather than improvising.

## 1. Scope

Two new reference forms become visible to `parse_refs`, both flowing through the
existing `Ref` / `classify` / `stamp` pipeline unchanged.

### Form A: reference-style links

```markdown
The tokenizer feeds [the loader][loader-ref] directly.

[loader-ref]: doc/adr/0013.md#loader
```

**In scope:** the full form `[text][id]` and the collapsed form `[id][]`.

**Out of scope:** the shortcut form `[id]` with no second bracket pair. It is
indistinguishable from ordinary bracketed prose and would fire on anything.
Do not implement it; do not add a heuristic for it.

**The reference lives on the definition line, not the usage.** One definition
may have many usages, and the target is named exactly once - so:

- `parse_refs` emits **one** `Ref` per link definition, with `line` = the
  definition's 1-based line number.
- The pin is written on the definition line:
  `[loader-ref]: doc/adr/0013.md#loader <!--@a1b2c3d4-->`
- Usages (`[the loader][loader-ref]`) emit no `Ref` at all and are never
  stamped.
- A definition with zero usages is still parsed and still checked. Reporting
  unused definitions is a separate lint and is out of scope.

`kind` stays `"md"`.

### Form B: wiki-links

```markdown
See [[loader]] and [[0013-prompts-as-resources#loader|the loader]].
```

- `#anchor` and `|alias` are both handled; the alias is display text only and
  never part of the target.
- Pin placement matches `MD_REF` exactly - a trailing comment on the same line:
  `[[loader]] <!--@a1b2c3d4-->`, including the existing tolerance for sentence
  punctuation between the link and the marker.
- `kind` stays `"md"`.

**Target resolution (the one real decision here):** a wiki-link target resolves
as a path relative to the referring file, with `.md` appended when the target
has no extension. `[[loader]]` in `docs/a.md` therefore means `docs/loader.md`.

Obsidian itself resolves `[[loader]]` by vault-wide note name, not by path. That
behavior is deliberately **not** implemented: it needs a name index and a
collision rule, which is a design change, not grammar surface area. A
vault-style link that only resolves by basename is expected to come back
`DANGLING`, and that is the correct result under this contract.

> Open question for the human before an agent starts: confirm this
> relative-path-only rule. The alternative - relative path first, then a
> unique-basename fallback across the index - is friendlier to real Obsidian
> vaults but introduces a second resolution mode and an ambiguity verdict.
> Recommendation: ship relative-path-only now, and file the basename fallback
> as its own item so it gets its own contract.

## 2. Invariants that must not change

- All 41 existing unit tests and all 38 existing evalbench fixtures stay green,
  unmodified. Changing an existing expectation is a contract violation, not a
  fix.
- Fenced code blocks stay skipped for the new forms, exactly as for `MD_REF`.
- `pin_span` for both new forms is the `(start, end)` of the **hex** within the
  source line, so `stamp` splices in place without reformatting the rest of the
  line. An empty group still means opted-in-but-unstamped.
- `PIN_STRIP` and `normalize` behavior is untouched. A pin on a new-form
  reference must be stripped from a target unit's text the same way, so adding
  a pin never changes a fingerprint.
- Non-markdown files are unaffected: neither form is parsed outside
  `.md` / `.markdown`.
- Inline code spans are not special-cased. `MD_REF` does not exempt them today,
  and this item does not change that.

## 3. Fixtures to add under `evalbench/fixtures/`

Named per the existing convention, each a real git repo plus a
`scenario.json`. Every one must fail before implementation.

Reference-style:

| Fixture | Asserts |
|---|---|
| `md-refstyle-ok` | definition resolving to a real file+anchor is `OK` |
| `md-refstyle-dangling-file` | `DANGLING`, reported at the definition line |
| `md-refstyle-dangling-anchor` | `DANGLING` with the `no anchor '#x' in y` detail |
| `md-refstyle-collapsed-form` | `[id][]` usage parses via its definition |
| `md-refstyle-usage-not-stamped` | `stamp` writes the pin on the definition line only, leaving usages byte-identical |
| `md-refstyle-drifted` | edit the target, `check` reports `DRIFTED` |
| `md-refstyle-shortcut-ignored` | a bare `[id]` with a matching definition yields exactly one `Ref` (the definition), never two |
| `md-refstyle-unused-definition` | a definition with no usage is still checked |
| `md-refstyle-in-fence-ignored` | a definition inside ``` is not parsed |

Wiki-links:

| Fixture | Asserts |
|---|---|
| `md-wikilink-ok` | `[[note]]` resolves to `note.md` beside the source |
| `md-wikilink-anchor` | `[[note#heading]]` resolves the anchor |
| `md-wikilink-alias` | `[[note#heading\|display]]` - alias excluded from target |
| `md-wikilink-dangling` | unresolvable target is `DANGLING` |
| `md-wikilink-basename-only-is-dangling` | locks in the resolution decision above |
| `md-wikilink-stamp-roundtrip` | `stamp` then `check` is `OK`; edit target, `check` is `DRIFTED` |
| `md-wikilink-in-fence-ignored` | inside ``` is not parsed |
| `md-wikilink-explicit-extension` | `[[note.md]]` works, no double-suffixing |

Mixed:

| Fixture | Asserts |
|---|---|
| `md-mixed-forms-one-line` | an inline link, a wiki-link and a ref-style usage on one line produce the right set of `Ref`s with correct `pin_span`s after `stamp` |

## 4. Unit tests to add in `test_reflock.py`

Direct `parse_refs` assertions, independent of the CLI:

- Full, collapsed, and shortcut ref-style forms - `Ref` count and `line`.
- A definition line with a pre-existing pin - `pin` and `pin_span` exact values.
- Wiki-link with every combination of anchor and alias present or absent.
- A wiki-link containing a `|` inside the alias text does not corrupt the target.
- Fence skipping for both forms.

## 5. Verification

```
make test && make bench && make check && make suspects
```

`make check` matters here specifically: this change makes reflock see link
forms in its own docs that were previously invisible, so new findings in
[README.md](../README.md), [NORTHSTARS.md](../NORTHSTARS.md),
[IDEAS.md](../IDEAS.md) and [DECISIONS.md](../DECISIONS.md) are an expected
outcome, not a regression. Resolve them by fixing the reference or stamping it -
never by adding an exclusion to [.reflockignore](../.reflockignore).

## 6. Definition of done

1. All fixtures and unit tests above exist and pass.
2. Nothing in section 2 changed.
3. Northstar #2 is **deleted** from [NORTHSTARS.md](../NORTHSTARS.md) - the
   doc's own rule is that a northstar which is already true is worse than none.
4. README's reference-grammar documentation covers both new forms, and the file
   is re-stamped.
5. `ROADMAP.yaml` marks NS-02 `done`.
6. A PR is open. Nothing is merged.
