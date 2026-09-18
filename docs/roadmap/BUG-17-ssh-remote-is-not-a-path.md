# BUG-17 acceptance contract: an SSH remote is not a repo path

Source: [issue #16](https://github.com/a-grasso/reflock/issues/16) and [issue #17](https://github.com/a-grasso/reflock/issues/17), reported against 0.4.0
Owner: agent · Tier: near · Touches: [reflock_lib/grammar.py](../../reflock_lib/grammar.py), [test_reflock.py](../../test_reflock.py), [fixtures/](../../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

One blind spot, reported twice: nothing in the grammar knows the SSH remote
form `git@github.com:acme/ng-ui.git`, which is the only reference-shaped
construct with no `scheme://`. The `@` lands before the colon, so every rule
keyed on a scheme misses it.

`check` (#16) truncates the target at the `@`, because `CODE_REF` spells the
pin separator and the userinfo separator with the same character:

```python
r"...REF:\s*(?P<target>[^\s@]+)(?:\s+@(?P<pin>%s))?"
```
```
AGENTS.md:3  git   [no such file: git]
```

Capturing the whole target is not enough on its own: `EXTERNAL` is
`^(?:[a-z][a-z0-9+.\-]*:|//|#)`, which `ssh://git@h/p` matches and
`git@github.com:acme/ng-ui.git` does not - so the finding would become
`[no such file: git@github.com:acme/ng-ui.git]`, wrong in a longer way.

`suspects` (#17) has the same gap one layer over: `mask_urls` blanks URLs so
their path segments are not read as repo paths, but `URL` knows only
`scheme://` and `//host/`. The remote survives masking and its path half is
reported as prose:

```
AGENTS.md:3  acme/ng-ui.git   [bare path, does not resolve]
```

With the #16 fixture both fire on one line - `DANGLING git` from the gate and a
bare path from the advisory scan. They are one item because the fix is one
shared notion of what a remote looks like, and two patterns that consult it.

## Required behavior

`grammar.py` names the form once, and the three rules that need it use that
name:

- `CODE_REF` splits the pin off the target only where a pin can be: after
  whitespace. The target is whatever non-space run precedes it, `@` included.
- `EXTERNAL` classifies an SSH remote as external, like any other off-repo
  target. reflock is in-repo only, so an external target is not checked, not
  reported.
- `URL` covers the form, so `mask_urls` blanks it before `suspects` scans.

```
<!-- REF: git@github.com:acme/ng-ui.git#AGENTS.md -->  -> external, no finding
<!-- REF: t.md @a1b2c3d4 -->                           -> target t.md, pin a1b2c3d4
<!-- REF: t.md -->                                     -> target t.md, no pin
prose quoting git@github.com:acme/ng-ui.git            -> no suspect
prose quoting docs/gone.md                             -> still a suspect
```

The form is `user@host:path` with a dotted host and an alphabetic TLD - the
same caution `URL`'s protocol-relative branch already takes, so an `a@b:c` in
prose is not silently swallowed.

## Explicitly out of scope

- Resolving into the remote. A cross-repo target is NS-01, still blocked on
  design; until then external means unchecked, which is the existing contract
  for every off-repo reference.
- Hosts with no dot (`git@internal:path`). Bounded gap, stated rather than
  guessed at: such a target keeps reporting as a missing file, and a shape
  loose enough to catch it would swallow ordinary prose.
- `scp`-style paths that are not remotes. Same shape, same treatment; there is
  nothing in the string to tell them apart.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- A pin still parses in every form that carries one, and `pin_span` offsets
  stay correct relative to the original line - `stamp` splices by column.
- `suspects` still reports a genuine bare path on a line that also carries a
  remote: masking must not silence the rest of the line (the BUG-02 lesson,
  restated for a third masker).
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `code-ref-ssh-remote-is-external` | the #16 fixture: `check` reports nothing, and `suspects` on the same tree reports nothing either |

## Unit tests to add

- `CODE_REF` captures `git@github.com:acme/ng-ui.git#AGENTS.md` whole.
- That target classifies as external, so `check` is clean.
- `REF: t.md @a1b2c3d4` still splits into target and pin, and `pin_span` still
  points at the hex in the original line.
- `mask_urls` blanks an SSH remote, same-length.
- A line carrying a remote *and* a dead bare path still yields the bare path.

## Verification

```
just gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. `ROADMAP.yaml` lists BUG-17 under `done`.
3. Issues #16 and #17 closed with the release that carries the fix.
