# Locked decisions for queued items

Cross-cutting calls the contracts in this directory depend on. They live here
once so nine contracts do not each carry their own copy and drift apart, the
same reason [DECISIONS.md](../../DECISIONS.md) exists relative to
[NORTHSTARS.md](../../NORTHSTARS.md).

Scope note: these are implementation-level calls about queued work. A decision
here that turns out to be architectural belongs in DECISIONS.md instead, and
should be moved there rather than duplicated.

An agent may not overturn anything on this page. If an item cannot be built
without contradicting one of these, stop and report it.

---

## D1. One reporting layer, selected by `--format`

Four queued items add or change output. They all go through a single renderer.

```
reflock check --format human     # default: today's output, unchanged
reflock check --format json      # today's --json output, unchanged shape
reflock check --format github    # CI workflow commands
reflock check -q                 # summary only, to stderr
```

- `--json` stays as an alias for `--format json`. It is a documented flag and
  removing it is a breaking change for anyone who scripted it. Keeping it is
  not negotiable.
- New commands (`backlinks`, `explain`) accept `--format` and reuse the same
  renderer rather than printing ad hoc.
- Adding a format means adding one function in one place. If an item needs to
  touch more than that to add a format, the layer is wrong; say so.

**Why:** four items otherwise land four output conventions, and two of them
(`-q` and `--format github`) rewrite the same code path and would conflict.

## D2. Inline code spans are not references

Single-backtick spans are exempt from reference parsing, exactly as fenced
blocks already are.

```
See `[x](t.md)` for the syntax.   -> not a reference
See [x](t.md) for the thing.      -> a reference
```

**Why:** every markdown renderer treats code-span content as literal, and any
document explaining reflock's own grammar in prose otherwise produces false
`DANGLING` findings. False positives are what destroy trust in a gate, so this
is the same principle that motivated the tool.

**Accepted cost:** a genuine reference someone wrapped in backticks silently
stops being checked. Judged the better trade; do not add a warning for it
without a new decision.

## D3. Zero runtime dependencies

reflock stays pure-stdlib Python in one readable file. DECISIONS.md names this
as a live advantage over drift, and the Homebrew formula depends on it.

No item may add a third-party import. If an item appears to need one, that is a
finding to report, not a licence to add it.

## D4. Wiki-link resolution: relative first, then unique basename

For NS-02b. A wiki-link target resolves in this order:

1. As a path relative to the referring file, with `.md` appended when the
   target carries no extension.
2. Failing that, by basename across the index, when exactly one file matches.

An ambiguous basename is `DANGLING`, with the candidates listed in the detail:

```
ambiguous: docs/loader.md, spec/loader.md
```

**No fifth verdict.** `DANGLING` already means "does not resolve to one thing",
and an ambiguous basename is exactly that. Do not add an `AMBIGUOUS` verdict,
do not change the JSON schema, do not change exit codes.

**Why the fallback exists:** the scenario that motivates wiki-links at all is
engineering notes kept in an Obsidian vault beside a repo, and Obsidian resolves
by note name. Relative-only would report `DANGLING` on links that work in the
editor they were written in - a false positive, against D2's principle.

**Why not full Obsidian fidelity:** Obsidian also has a configurable link
format and proximity tie-breaking. Reimplementing that is a resolution engine,
not grammar surface area, and would push this item out of the Near tier.

**Direction of travel:** the fallback is strictly more permissive, so adding it
later is additive while removing it later is breaking. That asymmetry is why it
is worth getting right now.

## D5. `stamp --check` follows the `--check` convention

Exit nonzero if stamping would change anything, report what and why, write
nothing. Modelled on `black --check`, `terraform fmt -check`,
`prettier --check`.

Section 3 of [DECISIONS.md](../../DECISIONS.md) already assigns this its job: it is
the piece that makes an *advisory* pre-commit run useful, with enforcement at
pre-push. Contracts should not re-argue where the gate belongs.

## D6. The shipped pre-commit manifest is advisory

For ID-21. Per DECISIONS.md section 3, a pre-commit gate fires on partial work:
a reference added in this commit whose target arrives in the next one is
correctly `DANGLING` and will block a commit a human considers reasonable.

So the shipped `.pre-commit-hooks.yaml` offers `check` plus the advisory
`stamp --check`, and the README points teams at pre-push for enforcement. Do not
ship a hook that hard-fails a commit by default.

## D7. The machine-readable output envelope

Every JSON emitter wraps its payload in one object. Never a bare array, never a
different top-level type on the error path.

```json
{ "schema": 1, "reflock": "0.4.0", "command": "check", "root": "/abs/path",
  "findings": [], "summary": {}, "problems": 0 }
```

- `schema` is an integer, emitted and never negotiated. **Additive changes do
  not bump it**; removing or repurposing a key does. That asymmetry is the point
  of having it - it buys the freedom to add fields later without a flag day.
- `findings` is always present and always an array, including when `error` is
  set. A consumer must never have to type-switch on the top level, and the naive
  `for f in json.load(fh)` must not silently iterate a string.
- `error` is `{"kind": ..., "message": ...}` with `kind` a closed vocabulary.
  The message is prose (see D8); `kind` is what a caller branches on.
- Emitters affected: `check`, `stamp`, `explain`, `backlinks`, `suspects --json`.
  Per D1 that is one renderer, so this is one change in one place.

**Why now rather than after adoption:** the stamp *wire* format is versioned
(`FP_VERSION`, and `UNSUPPORTED` exists to announce a version reflock cannot
read) while the *output* format is not. The asymmetry is not principled - it is
that nobody wrote it down - and every day it ships, the eventual fix costs more.

**Accepted cost:** this is a breaking change to `--format json` for anyone
already scripting against the bare array. Taken once, deliberately, before the
surface is announced, rather than apologised for later.

## D8. `detail` is prose, `reason` is vocabulary

Findings carry both. `detail` is a human sentence and reflock may reword it in
any release. `reason` is a closed vocabulary derived from the branch that
produced the verdict, and changing a member is breaking.

```json
{ "verdict": "DANGLING", "reason": "no-such-anchor",
  "detail": "no anchor '#gone' in b.md" }
```

- A `reason` must be derived from control flow, not by parsing `detail`. If the
  two can disagree, the vocabulary is decoration.
- Structured operands (`pinned`, `current`, `candidates`, ...) appear only on
  the verdicts that define them. Absence is a signal; do not emit nulls.

**Why both:** the human report is read by people *and* by the model behind a
Stop hook, where a fluent sentence outperforms an enum. The JSON is read by
code, where an enum is the only honest option. Collapsing them either freezes
prose or forces machines to regex it - reflock currently does the latter, which
is how a wording fix becomes an outage for someone.

**Consequence for AGT-03:** `detail` is explicitly outside the stability
contract. Say so in the manual rather than leaving it implied.
