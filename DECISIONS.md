# Decisions

Standing design choices: what reflock does, the alternative it rejected, and
the evidence. This is the opposite kind of entry from its two siblings -
[NORTHSTARS.md](NORTHSTARS.md) is capabilities reflock lacks and will need,
[IDEAS.md](IDEAS.md) is the wider brainstorm feeding it, and both are lists of
things to *build*. A decision here is a question that's settled: it says what
not to build and why, so the same alternative doesn't get re-proposed every
six months.

Revisit an entry when its **evidence** changes, not when the roadmap moves.
Several entries below are anchored to the observed behaviour of a competing
tool; that tool will keep moving, so its state is captured once, dated, in
[Prior art under observation](#prior-art-under-observation) rather than
restated inside each decision.

---

## 1. Fingerprints live inline at the reference, not in a central lockfile

**Decision:** a pin is written next to the reference it protects -
`<!--@a1b2c3d4-->` after a markdown link, `@a1b2c3d4` on a `REF:` comment.
There is no `reflock.lock`.

**The alternative:** one lockfile per repo mapping (referring doc, target) ->
fingerprint, the literal `package-lock.json` shape the tool's own name borrows
from.

**Why inline wins:**

- **Merge conflicts.** A central lockfile is a single file every branch that
  touches any doc must edit, so disjoint doc edits collide in it. drift shipped
  a lockfile, hit this, and redesigned the format specifically to reduce it
  (one line per binding -> versioned TOML array-of-tables); their published
  figures put the improvement at roughly 44% of edits conflicting down to ~25%.
  A quarter of edits still conflicting is the *improved* state. An inline pin
  conflicts only when the same line of the same doc conflicts, which is a
  conflict a human already had to resolve.
- **Locality.** The pin is visible in the diff that changes the prose it
  protects. A reviewer sees "this paragraph was re-blessed" in the same hunk as
  the paragraph, not in a lockfile hunk 400 lines away in another file.
- **No second source of truth.** A lockfile is a copy of "which references
  exist," maintained in parallel with the references themselves, and able to
  disagree with them. That is the exact failure mode reflock exists to catch.

**The costs, accepted knowingly:** no cheap reverse lookup ("what points at
this file?" needs a scan, not a lookup - see IDEAS.md #15), scoped checks must
still parse candidate sources, a rename fan-out touches every referring file
rather than one lockfile, and a pin travels with a doc when the doc is copied
into another repo, where it doesn't belong (NORTHSTARS.md #12 addresses that
one).

Worth noting the direction of travel: drift *started* inline and migrated to a
lockfile for the reverse-lookup and fan-out reasons above. The costs are real.
This decision says they are cheaper than the conflict rate and the second
source of truth, not that they are zero.

---

## 2. A fingerprint is a content hash, never a git commit SHA

**Decision:** the pin records a hash of the target's normalized *content*.
Nothing in reflock records or compares commit identity.

**The alternative:** pin the commit the target was last blessed at, and ask git
whether the target changed since - superficially attractive, because git
already knows the answer and no normalization rules are needed.

**Why content hashing wins:** commit identity is not stable under normal git
use. Rebase, amend, squash, and cherry-pick all rewrite SHAs without changing
a byte of content, and every pin anchored to a rewritten commit becomes
spuriously stale. Worse, a commit-anchored check cannot evaluate *uncommitted*
work at all: the pre-commit gate - the one place a human is still holding the
change - is exactly where there is no commit to compare against yet. drift
shipped SHA-based provenance first and abandoned it for content hashes for
both of these reasons (their issues #9 and #10).

**Consequence:** the normalization rules are load-bearing, because they are
what make content hashing quiet enough to live with (whitespace and reflow
invariance). They are also a published wire format the moment anyone stamps a
repo - see NORTHSTARS.md #11 for the version-tag reservation that decision
implies.

---

## 3. Where to gate, and what each gate can honestly promise

**Decision:** reflock is offered at three gates (pre-commit, CI, agent Stop
hook - see the README) and is cheap enough to run at all three. Content
hashing (decision #2) is what makes the pre-commit gate viable at all, since
it evaluates the working tree rather than history.

**The caveat to keep honest:** a pre-commit gate fires on partial work. A
reference added in this commit whose target arrives in the next one is
correctly `DANGLING` and will block a commit a human considers reasonable.
drift moved its own enforcement to pre-push for adjacent reasons. reflock's
content hashing removes the *uncommitted-state* half of that problem, but not
the partial-work half. Two mitigations, neither yet built: scope the hook to
staged files, or gate at pre-push and leave pre-commit advisory
(NORTHSTARS.md #3's `stamp --check` is the piece that makes an advisory run
useful).

**Not a decision to relitigate:** the *Stop hook* gate is the one with no
substitute. CI catches what escapes a human; nothing but the Stop hook catches
an agent declaring itself done with references broken, because the agent's turn
ends before CI ever runs.

---

## 4. Agent integration is explicit and opt-in

**Decision:** anything that writes into a user's agent configuration -
`.claude/`, hooks, skills, an `.agents` directory - is opt-in and named as
such. `examples/hooks/` is copied deliberately, never installed silently.

**Why:** an installer that drops agent config where the user didn't ask for it
reads as overreach even when the content is wanted, and reflock's install path
already runs as a `curl | bash` one-liner where trust is the scarce resource.
drift auto-installs its skill into a universal agent location and drew a
complaint for it within weeks (their issue #7). Also: reflock is deliberately
tool-neutral about which agent runs it, and shipping one vendor's config layout
by default quietly picks a side.

---

## 5. No model, no network, no daemon in the hot path

**Decision:** `check` is a grep, a hashmap lookup, and a byte compare. No LLM
call, no HTTP request, no background process.

**The alternative:** the crowded 2024-2026 category of LLM-in-CI documentation
freshness tools that read a diff and judge whether the docs still hold.

**Why the mechanical layer stays mechanical:** it is the only version that can
run at every gate. An LLM check costs money and latency per run, needs a key in
CI, is non-deterministic (the same diff can pass twice and fail the third
time), and cannot be a pre-commit hook a human will tolerate. The two-layer
split in the README is the actual answer: the mechanical layer decides *where*
to look, and a human or an LLM decides *whether it matters* - on the tiny
`DRIFTED` set, not the whole corpus. Those tools are complements to reflock,
not competitors, and the boundary is deliberate.

External-link liveness is the same decision restated: it needs the network, so
it can never be part of default `check` (IDEAS.md #19 keeps it strictly opt-in).

---

## Prior art under observation

**[fiberplane/drift](https://github.com/fiberplane/drift)** - the closest
living neighbour, and the source of most of the evidence cited above.
Independently arrived at the same thesis: content-fingerprinted references as a
deterministic, no-LLM CI gate, explicitly motivated by coding agents rotting
docs.

**Snapshot as of July 2026** (this will age - re-verify before relying on it):
created March 2026, MIT, Zig, ~122 stars, v0.10.1 released June 2026, actively
developed by Fiberplane, who dogfood it. Third-party adoption looks minimal;
its issue tracker is driven largely by one engaged outside user, whose reports
caused both of the pivots cited in decisions #1 and #2.

- **Covers:** docs -> code bindings via a central `drift.lock`; code targets
  fingerprinted as a normalized tree-sitter AST hash (XxHash3), so formatting
  churn and refactors don't false-positive; markdown *section* targets too
  since v0.8.0, so doc -> doc drift is no longer reflock-only; `refs` reverse
  lookup; `--changed` scoping; git blame context in reports; granular reason
  codes and a versioned JSON schema; an `origin` field for vendored docs; a
  relink gate that refuses to re-bless without an explicit
  "the doc is still accurate" flag; an install-only GitHub Action; a Claude
  Code skill.
- **Does not cover (reflock does):** `REF:`-in-code -> docs references, pins
  inline at the reference site, the `suspects` heuristic for path-shaped prose,
  zero dependencies in one readable file, and Windows (their issue #35).
- **Does not cover (nobody does):** rename/move repair - a renamed target is
  simply "not found." reflock's recorded hash makes exact moved-file detection
  possible instead of a name guess (NORTHSTARS.md #7). Also no watch mode, no
  editor/LSP integration, no PR line annotations, and no structured-data
  (YAML/JSON key) targets, though the last is their most-requested open issue.
- **Tried and abandoned:** commit-SHA provenance (decision #2), inline stamps
  (decision #1) - in opposite directions, which is why both decisions cite it.

**What would change the picture:** drift adding `REF:`-in-code support or a
`suspects` equivalent would take most of what's left of reflock's distinct
surface. Re-check its releases before starting any large piece of
NORTHSTARS work, and treat its `docs/DECISIONS.md` as the fastest read on what
it has learned.
