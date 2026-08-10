# reflock — a lockfile for cross-references

> Cross-references rot. When you change part A, the paragraph in part B that
> describes A goes quietly wrong — the link still resolves, so nothing complains.
> `reflock` makes that failure **mechanical to detect**: it records a content
> fingerprint of each reference's target and screams the moment the target drifts.

One dependency-free Python file. No model, no network, no daemon — everything is
a grep, a hashmap lookup, and a byte compare, so it runs on every commit and
costs nothing.

```
$ reflock check
DANGLING (1)
  doc/adr/0011-….md:81   platform/research.sh   [no such file]
DRIFTED (1)
  doc/DESIGN.md:52   ../adr/0011-….md#decision   [pinned @a1b2c3d4, now @9f0e1d2c]

2 problem(s).

Run `reflock explain <file>:<line>` for details on any of the above.
```

## The problem

References break in two ways, and they need different tools.

**Structural staleness** — the target moved or was deleted. Ordinary
link-checkers catch this.

**Semantic staleness** — the target still exists, but its content changed so
that what B says about A is now wrong. B cites "ADR-0011's decision"; the
decision got superseded, but B's paragraph still describes the old one. The path
resolves fine, so a link-checker reports green while the meaning is broken.
**This is the one that actually bites**, and you cannot see it by looking at the
reference alone. You have to know the target changed *since B last vouched for
it*.

That single requirement dictates the whole design.

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

**Level 1 — references are resolvable, never prose.** Any load-bearing reference
is a link or an ID a machine can resolve. A bare `see research.sh` is uncatchable
*precisely because* it isn't a link.

```markdown
The pipeline runs four stages — see [ADR-0011](../adr/0011-….md#decision).
```
```kotlin
// REF: doc/adr/0013-prompts-as-resources.md#loader
```

`reflock suspects` finds the prose you haven't converted yet: path-shaped tokens
that resolve to nothing.

**Level 2 — pin the load-bearing ones with a fingerprint.** Where B makes a
*claim* about A's content, not just "see also", opt in with an empty marker and
let `reflock stamp` fill the hash:

```
[ADR-0011](../adr/0011-….md#decision)<!--@-->     →  <!--@a1b2c3d4-->
// REF: …#loader @                                 →  @a1b2c3d4
```

The fingerprint hashes the **smallest stable unit** the reference points at — a
markdown section, a `reflock-anchor` span in code, or the whole file if there's
no anchor. Not the whole file when you anchored: hash a whole ADR and every typo
flags all 20 references to it → noise → everyone mutes it → dead convention.
Anchor precision is what makes the convention survive contact with a team.

### Verdicts

| Verdict | Meaning | Fix |
|---|---|---|
| `OK` | resolves; fingerprint matches (or unpinned) | — |
| `DANGLING` | path / anchor / span doesn't resolve | fix the link, or delete it |
| `DRIFTED` | resolves, but target changed since blessing | re-read B; edit if needed; `stamp --rebless --reviewed` |
| `UNSTAMPED` | opted into pinning (`@`) but never stamped | `reflock stamp` |
| `UNSUPPORTED` | pin written by a newer fingerprint version | upgrade reflock |

## Install

A single file, Python 3.9+, not scoped to any one project — install once, use
from any repo.

```sh
brew install a-grasso/tap/reflock
```

Or from source, cloning to `~/.local/share/reflock` and symlinking into
`~/.local/bin` (re-run any time to update):

```bash
curl -fsSL https://raw.githubusercontent.com/a-grasso/reflock/main/install.sh | bash
```

Already have a clone? Point at it instead, and the installed command *is* that
checkout: `REFLOCK_SRC=~/Projects/reflock ./install.sh`.

## Use

```bash
reflock                 # same as `reflock check` - the default with no subcommand
reflock check           # report problems (exit 1 if any)
reflock stamp           # fill empty pins
reflock explain doc/DESIGN.md:42    # everything about one reference
reflock backlinks doc/DESIGN.md     # what points at this file, before you edit it
reflock suspects --all  # bare path-shaped tokens that resolve to nothing
```

Files come from `git ls-files`, so `.gitignore` is honoured for free; a
`.reflockignore` skips further files as *sources* while keeping them as targets.
`stamp` is a surgical write — it changes the 8 hex characters of a pin and
nothing else, preserving line endings exactly.

The full command and flag reference is in the [manual](docs/manual.md).

## Gate it

Detection is worthless without enforcement. reflock is meant to sit at every
point where a stale reference could escape: **pre-commit** (the human), **CI**
(the server backstop), and the **Stop hook** (the agent — the one people forget:
an AI agent editing your docs can declare itself done with references broken).

With the [pre-commit](https://pre-commit.com) framework:

```yaml
repos:
  - repo: https://github.com/a-grasso/reflock
    rev: v0.4.0
    hooks:
      - id: reflock-check
      - id: reflock-stamp-check
```

For an agent, `reflock setup claude` installs the Stop hook. What each gate can
and cannot honestly promise — and why the pre-commit one is advisory by default —
is in [Three gates, three trust boundaries](docs/manual.md#three-gates-three-trust-boundaries).

Before scripting against reflock, read the
[output contract](docs/manual.md#output-contract): which exit codes and JSON
fields are promised to hold still, and which are prose that may be reworded.

## Why this stays quiet

```
              per reference        runs             cost
  mechanical  O(1) lookup + hash   every check      ~free
  semantic    read + judge         only on DRIFTED  a human minute / an LLM call
```

The mechanical layer is exact and cheap, so run it constantly. The semantic
layer — *"did A's change actually invalidate what B says?"* — is the only part
needing judgment, and the convention's job is to keep that set tiny and precisely
located. Three `DRIFTED` references means three paragraphs to re-read, not a
corpus to re-audit.

**Don't pin everything.** "See also" links only need Level 1. Over-pinning is the
fast road to an ignored checker. The rest of the
[caveats and non-goals](docs/manual.md#caveats-and-non-goals) are worth reading
before adopting.

## More

- [Manual](docs/manual.md) — every command, flag, exit code and gate.
- [DECISIONS.md](DECISIONS.md) — what reflock chose, what it rejected, and the
  evidence. Includes [fiberplane/drift](https://github.com/fiberplane/drift), the
  nearest living neighbour, which reached several opposite conclusions worth
  understanding.
- [NORTHSTARS.md](NORTHSTARS.md) — what it can't do yet, the scenario forcing
  each one, and the rough shape of a fix. [docs/IDEAS.md](docs/IDEAS.md) is the
  wider brainstorm behind it.
- [CONTRIBUTING.md](CONTRIBUTING.md) — the two constraints that decide most PRs.

MIT licensed. If it saved you an afternoon, you can
[buy me a coffee](https://buymeacoffee.com/a.grasso).
