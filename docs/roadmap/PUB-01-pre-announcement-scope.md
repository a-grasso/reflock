# PUB-01 - Pre-announcement scope for NORTHSTARS #10 and #12

Source: the public-presentable pass, 2026-08-09.
Question: which open northstars must land *before* reflock is announced, on the
grounds that announcing is what creates the adoption that makes them expensive?

The precedent is [NORTHSTARS.md](../../NORTHSTARS.md) #11, which said so of
itself ("do before wide adoption") and has now landed. #10 and #12 are the two
remaining candidates.

## #10 - re-blessing is one flag from a rubber stamp: **implement before announcing**

**Recommendation: implement.** Not because it is expensive to retrofit - it is
not, unlike #11 - but because it is the first thing an unsympathetic reader will
attack, and they would be right.

The argument for reflock is a single claim: a `DRIFTED` verdict corresponds to a
real "someone should read this" event. `stamp --rebless` currently discards that
event with no friction at all - no diff, no confirmation, no distinction between
"I read it and it is fine" and "I want the red to go away." An agent facing a red
`check` will find `--rebless` and use it, which converts the gate into
decoration. The README sells the Stop-hook gate on exactly the promise this
breaks.

It is also the one place where the competitor's behaviour is straightforwardly
better and publicly visible: drift refuses to re-bless by default and demands an
explicit "the doc is still accurate" flag. Shipping without it invites the
comparison on the worst possible ground.

**Scope for now** - deliberately less than the full northstar. `--rebless`
requires an explicit `--reviewed` alongside it; without it, it prints what it
*would* re-bless (reference, target, old pin, new pin) and exits nonzero.

One rule for TTY and non-TTY alike, rather than the northstar's
interactive-prompt-or-flag split. A per-item interactive prompt is more
friction-per-reference but it is also untestable in the fixture harness, and a
gate whose behaviour differs between a terminal and CI is a gate people learn to
distrust. The northstar's richer idea - printing the referencing paragraph beside
the target's current text, a real before/after rather than two hashes - stays
open, and is worth doing once there is a user asking for it.

**Cost of being wrong:** low and reversible. If `--reviewed` proves to be pure
ceremony, dropping the requirement is a one-line change that breaks nobody.

## #12 - a vendored doc carries stamps from its home repo: **no action, keep the entry**

**Recommendation: ship without it.**

The scenario that made this look publish-blocking is
[examples/skill/refcheck/SKILL.md](../../examples/skill/refcheck/SKILL.md) - a
file explicitly designed to be copied into other people's repos, which is
precisely the "vendored copy carries foreign pins" case. Checked directly: that
file contains **no pins and no `REF:` comments**. Copying it into a foreign repo
breaks nothing. The example is safe as shipped.

So the entry is real but hypothetical - it needs a user who has both adopted
reflock and vendored a *stamped* doc across repos. Nobody is in that position
yet, and the shape of the fix (an origin marker compared against `git remote get-url
origin`) deserves a real case to design against rather than a guessed one. It is
`Medium` for a reason: it introduces a new grammar element, and inventing one
speculatively the week before announcing is how a wire format acquires a mistake
that #11 then has to version around.

**Guard rail:** if a future example under `examples/` ever ships stamped
references, this entry becomes blocking for that example. Worth remembering when
the next one is written.

## Everything else in NORTHSTARS

Ship as-is. #1 (cross-repo), #5-#9 and the language/runtime section are honest
"not yet" entries, and a public roadmap that names its own gaps concretely reads
as confidence rather than incompleteness - which is the reason
[NORTHSTARS.md](../../NORTHSTARS.md) is linked from the README in the first
place.
