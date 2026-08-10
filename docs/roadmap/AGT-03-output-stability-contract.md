# AGT-03 acceptance contract: say what is stable

Source: this contract
Owner: agent · Tier: near · Touches: [docs/manual.md](../manual.md), [README.md](../../README.md)
Locked decisions: [D7](DECIDED.md#d7-the-machine-readable-output-envelope), [D8](DECIDED.md#d8-detail-is-prose-reason-is-vocabulary)
Depends on: AGT-01, AGT-02

## The problem

reflock's pitch to an automated consumer is stable exit codes and
machine-readable output. The exit codes are *documented*
([manual.md](../manual.md), the CI section) but nowhere *promised*, and
nothing at all says which parts of the JSON a script may depend on. Someone
scripting against `detail` today has no way to know they are building on sand,
and reflock has no ground to stand on when it rewords it.

A promise that is only implied is a promise that gets broken by accident.

## Required behavior

A section in [docs/manual.md](../manual.md) - "Output contract", sited with
the other output material, not appended at the end - stating exactly this:

**Stable. Changing any of these is a breaking change and bumps `schema` (or the
major version, for exit codes):**

- The three exit codes and their meanings: 0 clean, 1 problems found, 2 could
  not run as asked. In particular the 1/2 split, which is what lets a caller
  distinguish "the docs are wrong" from "you invoked me wrong".
- The verdict vocabulary: `OK`, `DANGLING`, `DRIFTED`, `UNSTAMPED`,
  `UNSUPPORTED`. New verdicts are breaking - D4 already refuses one on these
  grounds, and this section is where that rule becomes visible to users rather
  than only to contract authors.
- The JSON envelope keys from AGT-01 and the `reason` vocabulary from AGT-02.
- `findings` being an array on every exit path, errors included.
- The GitHub Actions verdict-to-level mapping.

**Not stable. May change in any release, without a `schema` bump:**

- Everything about `--format human`: wording, ordering, grouping, colors, the
  summary line, next-step hints.
- The `detail` string on any finding. It is prose. `reason` is the machine
  answer (D8).
- The exact text of error messages, as distinct from `error.kind`.
- Anything `suspects` reports. It is an advisory heuristic, deliberately outside
  `just gate`; pinning its output would freeze a tuning surface.

**What bumps what:** adding a key or a `reason` member is additive and does not
bump `schema`. Removing or repurposing one bumps it. State this in one sentence
so the rule is checkable by whoever writes the next contract.

[README.md](../../README.md) gains one line in the CI/integration area pointing
at the section - the landing page should not restate it (the two are already
under instruction not to drift).

## Explicitly out of scope

- Any code change. If writing this reveals that reflock's behavior does not
  match what the section would have to claim, **stop and report it** rather than
  fixing it here - that is a bug with its own contract, and a documentation
  commit that quietly changes behavior is the worst of both.
- A machine-readable schema artifact (`.schema.json`).
- A deprecation policy or support window. That is a project-governance question
  and belongs to a human.
- Committing to semantic versioning for the whole tool. This section scopes its
  promise to the output surface; do not widen it.

## Invariants

- No behavior change whatsoever. The diff touches Markdown only.
- `just check` passes, including the pin on every file this item edits.

## Fixtures to add

None - this item ships no behavior.

## Unit tests to add

None. The claims are enforced by AGT-01's and AGT-02's fixtures, which is the
argument for sequencing this item after them rather than before: the section
describes tested behavior, not intended behavior.

## Verification

```
just gate
```

Additionally: for each bullet in the "stable" list, name the fixture or test
that enforces it, in the PR body. A stability claim with nothing behind it is
the failure mode of this item, and it is invisible in a green build.

## Definition of done

1. The section exists in [docs/manual.md](../manual.md); every stable claim
   maps to a named test.
2. README links to it without restating it.
3. Both files re-stamped; `just check` clean.
4. `ROADMAP.yaml` marks AGT-03 `done`.
