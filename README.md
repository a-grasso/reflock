# reflock — a lockfile for cross-references

> Cross-references rot. When you change part A, the paragraph in part B that
> describes A goes quietly wrong — the link still resolves, so nothing complains.
> `reflock` makes that failure **mechanical to detect**: it records a content
> fingerprint of each reference's target and screams the moment the target drifts.

**The design invariant:** the mechanical layer runs *always* and is *free*; a
semantic layer (a human, or an LLM) runs *rarely* and only on what drifts. There
is no model in the hot path — everything is a grep, a hashmap lookup, and a byte
compare. One dependency-free Python file, milliseconds on a real repo.

```
$ reflock check
DANGLING (1)
  doc/adr/0011-….md:81   platform/research.sh   [no such file]
DRIFTED (1)
  doc/DESIGN.md:52   ../adr/0011-….md#decision   [pinned @a1b2c3d4, now @9f0e1d2c]

2 problem(s).
```

---

## The problem it solves

References break in two fundamentally different ways, and they need different tools.

**1. Structural staleness** — the target *moved or was deleted*. The reference
now points at nothing. This is decidable by asking one question: *does the target
resolve?* Ordinary link-checkers do this.

**2. Semantic staleness** — the target *still exists*, but its content changed so
that what B says about A is now wrong. B cites "ADR-0011's decision"; the decision
got superseded, but B's paragraph still describes the old one. The path resolves
fine — so a link-checker reports green while the meaning is broken. **This is the
one that actually bites**, and you cannot detect it by looking at the reference
alone. You have to know the target changed *since B last vouched for it*.

That single requirement dictates the whole design.

> **A worked example.** A repo deletes `platform/research.sh`. A link-checker
> catches nothing, because two references to it were written as *prose*, not
> links: one in an ADR, one in a sibling script's header comment. Both are now
> lies, and nothing in CI can see them. `reflock suspects` finds exactly these —
> path-shaped tokens in prose that resolve to nothing.

## The idea: treat references like dependencies

A `package-lock.json` doesn't re-resolve the dependency graph on every build. It
records a **content hash** taken at install time and fails the instant the real
content diverges. Do the same for references:

> A reference records a short fingerprint of its target's content, taken when the
> reference was last blessed. A checker recomputes the fingerprint and compares.
> Match → nobody touched A. Mismatch → A changed; B must be re-checked.

The mismatch *is* the "this needs updating" signal. It turns *"please remember to
update B"* (a human promise, always broken) into *"the check fails until someone
re-blesses B"* (a gate, never skipped).

## The convention

Two levels. Level 1 is nearly free and catches the deletion/move class today.
Level 2 is opt-in per reference and catches semantic drift.

### Level 1 — references are resolvable, never prose

One rule: **any load-bearing reference is an addressable link or ID a machine can
resolve — never a bare mention.** A bare `see research.sh` is uncatchable
*precisely because* it isn't a link. Make it one:

```markdown
The pipeline runs four stages — see [ADR-0011](../adr/0011-….md#decision).
```
```kotlin
// REF: doc/adr/0013-prompts-as-resources.md#loader
```

Then `reflock check` resolves every one and reports `DANGLING` on any miss.
`reflock suspects` helps you *find* the prose that should have been links.

### Level 2 — pin load-bearing references with a fingerprint

Where B makes a *claim* about A's content (not just "see also"), pin it. Two
surface forms, one concept — `target = path(#anchor)` plus an optional `@fp`:

```markdown
… runs four stages, per [ADR-0011](../adr/0011-….md#decision).<!--@a1b2c3d4-->
```
```kotlin
// REF: doc/adr/0013-….md#loader @a1b2c3d4
```

You opt in by writing an **empty** marker; `reflock stamp` fills the hash:

```
[ADR-0011](../adr/0011-….md#decision)<!--@-->     →  <!--@a1b2c3d4-->
// REF: …#loader @                                 →  @a1b2c3d4
```

The fingerprint hashes the **smallest stable unit** the reference points at — a
markdown *section* (heading to next same-or-higher heading), a `reflock-anchor`
*span* in code, or the whole file if there's no anchor. Not the whole file when
you anchored: hash a whole ADR and every typo flags all 20 references to it →
noise → everyone mutes it → dead convention. Anchor precision is what makes the
convention survive contact with a team.

### Verdicts

| Verdict | Meaning | Fix |
|---|---|---|
| `OK` | resolves; fingerprint matches (or unpinned) | — |
| `DANGLING` | path / anchor / span doesn't resolve | fix the link, or delete it |
| `DRIFTED` | resolves, but target changed since blessing | re-read B; edit if needed; `stamp --rebless` |
| `UNSTAMPED` | opted into pinning (`@`) but never stamped | `reflock stamp` |

## Quickstart

`reflock` is a single dependency-free file (Python 3.8+) and is not scoped to any
one project — install it once, use it from any repo.

**Homebrew** (macOS / Linuxbrew) — versioned, drops `reflock` onto `PATH`:

```sh
brew install a-grasso/tap/reflock
```

Managing Homebrew declaratively with [nix-homebrew](https://github.com/zhaofengli/nix-homebrew)?
Add the tap and formula to your nix-darwin config instead of running `brew` by hand:

```nix
homebrew = {
  taps  = [ "a-grasso/homebrew-tap" ];
  brews = [ "a-grasso/tap/reflock" ];
};
```

**Or install from source onto `PATH`** (clones to `~/.local/share/reflock`,
symlinks into `~/.local/bin`; re-run any time to update):

```bash
curl -fsSL https://raw.githubusercontent.com/a-grasso/reflock/main/install.sh | bash
```

Already have a clone (e.g. you're hacking on reflock itself)? Point at it instead
of cloning a second copy — the installed command then *is* that checkout, no
separate update step:

```bash
REFLOCK_SRC=~/Projects/reflock ./install.sh
```

Then, from any repo:

```bash
reflock check          # report problems (exit 1 if any)
reflock stamp          # fill empty pins
reflock stamp --rebless doc/DESIGN.md   # accept current target state for these refs
reflock suspects --all # bare path-shaped tokens that resolve to nothing
```

`check` colors verdict labels by severity when stdout is a terminal; pass
`--no-color` or set `NO_COLOR` (https://no-color.org) to turn that off, or pipe
output anywhere and it's plain text automatically.

There is deliberately no vendoring path. One machine, one installed copy, used
by every repo — a per-repo checked-in copy is exactly the kind of duplicate
source of truth reflock exists to keep A and B from silently disagreeing about.
A hermetic CI image installs the same way (`install.sh`, or pin a commit via
`REFLOCK_HOME`) rather than checking in a copy.

It enumerates files with `git ls-files` (so `.gitignore` is honoured for free),
always skips `.git` and `node_modules`, and treats a path git *would* ignore as
intentionally absent rather than a stale reference. Add a `.reflockignore`
(fnmatch globs) to skip further files as *sources* while keeping them as targets.

## Three gates, three trust boundaries

Detection is worthless without enforcement. Put `reflock check` at every point
where a stale reference could escape:

**1. Pre-commit (the human).** `.git/hooks/pre-commit` or a `pre-commit` entry:
```bash
reflock check || { echo "Fix references before committing."; exit 1; }
```
Note this gate fires on partial work: a reference whose target lands in the
*next* commit is correctly `DANGLING` and will block a commit you consider
reasonable. Gate at pre-push instead if that friction outweighs catching
mistakes early - see
[what each gate can honestly promise](DECISIONS.md#3-where-to-gate-and-what-each-gate-can-honestly-promise)<!--@c770f4c8-->.

**2. CI (the server backstop).** One job step: `reflock check`. Nonzero exit fails
the build. Deterministic, cacheable, no secrets.

**3. The Stop hook (the agent).** The one people forget. When an AI coding agent
(e.g. Claude Code) edits your docs, it can *declare itself done* with references
broken. A **Stop hook** blocks the agent from ending its turn until `reflock check`
is clean — and feeds the failure back so the agent fixes it before finishing. See
[`examples/hooks/`](examples/hooks/). The key subtlety is the loop-guard: honour
the runner's "already retrying" flag so a genuinely unfixable state can't wedge
the agent.

## Why the two-layer split matters

```
              per reference        runs            cost
  mechanical  O(1) lookup + hash   every check     ~free
  semantic    read + judge         only on DRIFTED  a human minute / an LLM call
```

The mechanical layer is exact and cheap, so run it constantly. The semantic layer
— *"did A's change actually invalidate what B says?"* — is the only part that
needs judgment, and the convention's whole job is to keep that set **tiny and
precisely located**. When `check` reports three `DRIFTED` references, that's three
paragraphs to re-read, not a whole corpus to re-audit. An LLM can take the
`DRIFTED` list, diff each target's unit, and either edit B or just re-stamp —
touching nothing else.

## Caveats & non-goals

- **Don't pin everything.** "See also" links only need Level 1. Reserve `@fp` for
  references that assert something about the target. Over-pinning is the fast road
  to an ignored checker.
- **Prefer eliminating the reference.** If B can transclude or be generated from A
  (a single source of truth), there's nothing to keep in sync. reflock is the
  safety net for the duplication you *can't* remove — not a licence to duplicate.
- **`suspects` is a heuristic, not a gate.** It finds path-shaped prose that
  doesn't resolve. Expect some false positives (external citations); use it to
  *migrate* prose into links, not in CI.
- **Heading slugs are the fragile link.** Renaming a heading changes its
  auto-slug → `DANGLING`. That's caught, not silent; add an explicit
  `reflock-anchor` on hot sections if the churn annoys you.
- **Fingerprints are whitespace- and reflow-invariant.** Rewrapping a paragraph
  won't flag it; changing a word will.
- **Path arguments (`check`/`stamp`/`suspects [paths...]`) are resolved relative
  to the current working directory**, not `--root` - same convention as `git`,
  `find`, etc. Run from the repo root (or pass absolute paths) if you're
  scripting against a `--root` that differs from your CWD.

## Prior art

reflock is a synthesis, not an invention: **lockfiles** (`package-lock`,
`Cargo.lock`) for the record-a-hash-and-compare mechanism; **content-addressing**
and build systems like Bazel that hash inputs to decide staleness; **LaTeX
`\label`/`\ref`** and **Sphinx** for stable IDs over positional references;
Sphinx/`mkdocs` **linkcheck** for the structural layer; and **Obsidian backlinks**
for the "who points at me" instinct. The new bit is aiming all of that at a mixed
docs+code tree with a grammar simple enough to grep and a fingerprint scoped
tightly enough to stay quiet.

The nearest *living* neighbour is [fiberplane/drift](https://github.com/fiberplane/drift),
which independently arrived at the same thesis and reached several opposite
conclusions worth understanding - notably a central lockfile where reflock puts
pins inline. [DECISIONS.md](DECISIONS.md) records what reflock chose, what it
rejected, and the evidence, including what drift tried and abandoned.

## Not yet supported

See [NORTHSTARS.md](NORTHSTARS.md) for the full, prioritized list of
capabilities reflock doesn't have yet, the real-world scenario forcing each
one, and the rough shape of a fix. [IDEAS.md](IDEAS.md) is the wider, less
prioritized brainstorm those northstars are drawn from. Some absences are
deliberate rather than pending - [DECISIONS.md](DECISIONS.md) says which, and
why.
