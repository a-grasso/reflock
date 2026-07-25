# NS-02a acceptance contract: reference-style markdown links

Source: northstar #2, markdown link forms beyond `[text](target)` (now resolved
and removed from [NORTHSTARS.md](../NORTHSTARS.md) - see [NS-02b](NS-02b-wiki-links.md))
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)
Locked decisions: [D2](DECIDED.md#d2-inline-code-spans-are-not-references), [D3](DECIDED.md#d3-zero-runtime-dependencies)

Northstar #2 covered two link forms. It was split because only one of them had
an open question: this half has none. Wiki-links are NS-02b.

## Required behavior

```markdown
The tokenizer feeds [the loader][loader-ref] directly.

[loader-ref]: doc/adr/0013.md#loader
```

**In scope:** the full form and the collapsed form.

```
[text][id]   full
[id][]       collapsed
```

**Out of scope:** the shortcut form - a lone `[id]` with no second bracket pair.
It is indistinguishable from ordinary bracketed prose and would fire on
anything. Do not implement it; do not add a heuristic for it.

**The reference lives on the definition line, not the usage.** A definition may
have many usages and names its target exactly once, so:

- `parse_refs` emits **one** `Ref` per link definition, with `line` set to the
  definition's 1-based line number.
- The pin is written on the definition line:
  `[loader-ref]: doc/adr/0013.md#loader <!--@a1b2c3d4-->`
- Usages emit no `Ref` and are never stamped.
- A definition with zero usages is still parsed and still checked. Reporting
  unused definitions is a separate lint and is out of scope.

Target resolution, anchors, `EXTERNAL` handling and verdicts are whatever the
existing inline form already does. This is the same target string in a different
syntactic position, nothing more. `kind` stays `md`.

Definition syntax to accept: optional leading whitespace, `[id]:`, whitespace,
target, then an optional title in quotes - the same title tolerance `MD_REF`
already has.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- Fenced blocks stay exempt. Code spans stay exempt if BUG-02 has landed; if it
  has not, do not implement the exemption here - that is BUG-02's job.
- `pin_span` is the `(start, end)` of the hex within the source line. An empty
  group still means opted-in-but-unstamped.
- `PIN_STRIP` and `normalize` untouched: pinning must never change a
  fingerprint.
- Parsed only in `.md` / `.markdown`.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `md-refstyle-ok` | definition resolving to a real file and anchor is `OK` |
| `md-refstyle-dangling-file` | `DANGLING`, reported at the definition line |
| `md-refstyle-dangling-anchor` | `DANGLING` with the existing no-anchor detail |
| `md-refstyle-collapsed-form` | the collapsed usage form parses via its definition |
| `md-refstyle-usage-not-stamped` | `stamp` writes the pin on the definition line only, leaving usage lines byte-identical |
| `md-refstyle-drifted` | edit the target, `check` reports `DRIFTED` |
| `md-refstyle-shortcut-ignored` | a lone bracketed id yields exactly one `Ref` (the definition), never two |
| `md-refstyle-unused-definition` | a definition with no usage is still checked |
| `md-refstyle-in-fence-ignored` | a definition inside a fence is not parsed |
| `md-refstyle-title-tolerated` | a quoted title after the target does not become part of it |

## Unit tests to add

Direct `parse_refs` assertions:

- Full, collapsed and shortcut forms - `Ref` count and `line`.
- A definition line with a pre-existing pin - exact `pin` and `pin_span`.
- A definition with leading whitespace.
- Fence skipping.

## Verification

```
make gate
```

`suspects` is advisory and exits nonzero whenever it has
anything to say, so it is not part of the gate. Read its output, act on
anything real, but do not chain it.

`make check` will newly see any reference-style links in this repo's own docs.
New findings are an expected outcome, not a regression. Resolve them by fixing
or stamping the reference - never by adding an exclusion to
[.reflockignore](../.reflockignore).

## Definition of done

1. All fixtures and unit tests above pass; nothing existing was modified.
2. README's reference-grammar section documents the form, including that the pin
   goes on the definition line and that the shortcut form is unsupported.
   Re-stamp the file.
3. Northstar #2's prose is updated to cover only the wiki-link half, since that
   half remains untrue. Do not delete the whole entry.
4. `ROADMAP.yaml` marks NS-02a `done`.
