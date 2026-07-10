---
name: refcheck
description: Verify cross-reference integrity with reflock and repair what drifted. Runs the mechanical checker, then adjudicates each DRIFTED reference — did the target's change actually invalidate what the referrer says? — editing the referrer or re-blessing the pin. Use before finishing doc/code changes, or when the user asks to check references, links, or cross-refs.
---

# refcheck

Mechanical first; spend judgment only where the machine can't decide.

## 1. Run the checker (the free, always-on layer)

```
reflock check
```

Everything below acts on its output. If it prints "All references OK", stop —
there is nothing to adjudicate.

## 2. DANGLING → structural fix

The path, anchor, or span does not resolve. Either the target moved (repoint the
reference) or it was deleted (remove the reference, or restore the target). No
judgment call — just make it resolve.

## 3. DRIFTED → the only part that needs judgment

The target still exists but changed since the pin was blessed. For each one:

1. `git diff -- <target-file>` and read the specific unit the reference points at
   (the `#anchor` section or span), plus the referrer's sentence.
2. Decide: **does the change invalidate what the referrer says?**
   - **No** (wording moved, fact intact) → re-bless: `reflock stamp --rebless <referrer-file>`
   - **Yes** → edit the referrer's prose to match the new reality, *then*
     `reflock stamp --rebless <referrer-file>`.

Never run a blanket `reflock stamp --rebless` across the whole repo — that
blesses drift you never read, which defeats the point. Re-bless per referrer,
after you have looked.

## 4. UNSTAMPED → stamp it

Someone opted a reference into pinning (`@`) but never filled the hash:
`reflock stamp`.

## 5. suspects (migration aid, not a gate)

```
reflock suspects --all
```

Path-shaped prose that resolves to nothing — usually a bare mention that should
be a real link, or a reference to something now deleted. Convert the real ones to
links; expect some false positives from external citations.

## Finish

Re-run `reflock check` and confirm it is clean before reporting the work done.
