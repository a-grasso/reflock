---
name: refcheck
description: Verify cross-reference integrity with reflock and repair what drifted. Runs the mechanical checker, then adjudicates each DRIFTED reference — did the target's change actually invalidate what the referrer says? — editing the referrer or re-blessing the pin. Use before finishing doc/code changes, or when the user asks to check references, links, or cross-refs.
---

# refcheck

Mechanical first; spend judgment only where the machine can't decide.

## 1. Run the checker (the free, always-on layer)

```
reflock check --format json
```

Everything below acts on its output. Exit 0 means clean - stop, there is nothing
to adjudicate. Exit 1 means findings; exit 2 means reflock could not run as
asked (fix the invocation, don't interpret the output).

Read `findings[].reason`, not `detail`: `reason` is a closed vocabulary and
`detail` is prose that may be reworded. Every finding carries `file`, `line` and
`target`, so `<file>:<line>` is what you pass to `reflock explain`.

## 2. DANGLING → structural fix

The target does not resolve. `reason` says which repair applies:

- `no-such-file` — the path is wrong or the file is gone. Repoint the reference,
  or remove it if the target was deliberately deleted.
- `no-such-anchor` — the file is right, the `#fragment` is not. Fix the fragment
  (a renamed heading is the usual cause); the path needs no change.
- `wiki-ambiguous` — two files share the basename. Pick one from `candidates`
  and write a relative path instead.
- `wiki-unresolved` — no such note. Same call as `no-such-file`.

No judgment call in any of them - just make it resolve.

## 3. DRIFTED → the only part that needs judgment

The target still exists but changed since the pin was blessed. `reason` is
`fingerprint-mismatch`, with `pinned` and `current` as the two digests. For each
finding:

1. `git diff -- <target-file>` and read the specific unit the reference points at
   (the `#anchor` section or span), plus the referrer's sentence. `reflock
   explain <file>:<line>` prints the unit that was fingerprinted.
2. Decide: **does the change invalidate what the referrer says?**
   - **No** (wording moved, fact intact) → re-bless it.
   - **Yes** → edit the referrer's prose to match the new reality *first*, then
     re-bless.

Re-blessing requires saying you read the change:

```
reflock stamp --rebless --reviewed --format json <referrer-file>
```

The output confirms exactly what moved: `written: true`, and one finding per pin
with `action: "rebless"` plus its old and new digest. Confirm it names the pin
you adjudicated and no other - that is cheaper and more certain than re-running
`check` and diffing two reports.

Without `--reviewed`, reflock refuses and exits 1, reporting what it *would*
have re-blessed. That is deliberate: the gate's whole value is that a DRIFTED
verdict means someone read the change.

Never run a blanket `reflock stamp --rebless --reviewed` across the whole repo -
that blesses drift you never read, which defeats the point. Re-bless per
referrer, after you have looked.

## 4. UNSTAMPED → stamp it

Someone opted a reference into pinning (`@`) but never filled the hash:

```
reflock stamp --format json
```

`findings[].action` is `stamp` for each pin filled in, and `current` is the
digest written. If `reason` was `no-indexed-text`, stamping cannot help - the
target carries no text to hash, so drop the pin or repoint the reference.

## 5. suspects (migration aid, not a gate)

```
reflock suspects --all
```

Path-shaped prose that resolves to nothing - usually a bare mention that should
be a real link, or a reference to something now deleted. Convert the real ones to
links; expect some false positives from external citations. Its output is
advisory and, unlike the above, deliberately not a stable contract.

## Finish

Re-run `reflock check --format json` and confirm exit 0 before reporting the
work done.
