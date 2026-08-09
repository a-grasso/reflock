# reflock manual

Everything `reflock` does, in detail. The [README](../README.md) is the
introduction; this is the reference you come back to.

- [Commands and flags](#commands-and-flags)
- [Three gates, three trust boundaries](#three-gates-three-trust-boundaries)
- [Why the two-layer split matters](#why-the-two-layer-split-matters)
- [Caveats and non-goals](#caveats-and-non-goals)
- [Prior art](#prior-art)

## Commands and flags

```bash
reflock                # same as `reflock check` - the default with no subcommand
reflock check          # report problems (exit 1 if any)
reflock stamp          # fill empty pins
reflock stamp --rebless --reviewed doc/DESIGN.md   # accept current target state for these refs
reflock stamp --check  # report what stamp would do, write nothing (exit 1 if not a no-op)
reflock suspects --all # bare path-shaped tokens that resolve to nothing
reflock backlinks doc/DESIGN.md   # what points at this file, before you edit it
reflock explain doc/DESIGN.md:42  # everything about one reference
```

### Re-blessing requires --reviewed

`stamp --rebless` discards a drift signal - the thing reflock exists to raise -
so it will not write without an explicit `--reviewed` alongside it. Without the
flag it lists what it would re-bless, with the old and new fingerprint, and exits
nonzero. The rule is the same in a terminal and in CI: a gate that behaves
differently under a TTY is a gate people learn to distrust.

```bash
reflock stamp --rebless             # reports, writes nothing, exits 1
reflock stamp --rebless --reviewed  # writes
```

### Pin format and versioning

A stamp is `@` followed by 8 hex characters, and that bare form is fingerprint
**version 1**. The `@N:hex` form is reserved for a future fingerprint algorithm:
a pin whose version this reflock does not understand is reported `UNSUPPORTED`,
naming the version and the remedy, rather than as a false `DRIFTED` - and
`stamp --rebless` leaves it alone instead of silently downgrading it. Nothing
about a bare pin changes; the room to change the algorithm later is the point.

`stamp` is a surgical write: it changes the 8 hex characters of a pin and
nothing else. Line endings are preserved exactly as the file had them, `\r\n`
and mixed files included, and a file with no trailing newline does not gain one
— so stamping one pin never produces a whole-file diff. It does not follow
symlinks: a symlinked file is not scanned for references, because writing
through the link would modify a file outside the tree with nothing to show for
it in `git status`. A reference *pointing at* a symlink resolves and
fingerprints normally, since that direction is only a read.

`check` colors verdict labels by severity when stdout is a terminal; pass
`--no-color` or set `NO_COLOR` (https://no-color.org) to turn that off, or pipe
output anywhere and it's plain text automatically.

Human output with at least one problem ends with a next-step hint pointing at
`explain`, and a second one pointing at `stamp` if any finding is `UNSTAMPED`.
A clean tree stays exactly `"All references OK."` - no hint on the path that
needs none. `--format json`/`--format github` never carry hints; they're for
callers that already know what they're doing next.

`check --format <human|json|github>` selects the output format; `human` is the
default. `--json` is a retained alias for `--format json`. Passing both is
fine as long as they agree; passing `--json` with a conflicting `--format`
exits nonzero with an error naming both flags. `github` emits GitHub Actions
inline annotations - see [Three gates, three trust boundaries](#three-gates-three-trust-boundaries)
below for the CI usage.

A usage error (an unmatched path, a bad `explain` spec, an unknown `backlinks`
target) is rendered in the same format that was requested: `--format json`
prints `{"error": "..."}` on stdout, `--format github` prints one
`::error::` annotation on stdout, and the default `human` format keeps
printing `error: ...` to stderr. `stamp` and `suspects` have no `--format`
flag, so their errors are always the plain stderr form (`suspects --json`'s
pre-existing flag is the one exception - its errors follow `--json` too).

`check -q` / `check --quiet` prints nothing on success; on failure it prints
one summary line - `reflock: 1 of 137 references failed` - to **stderr** and
exits nonzero, for a CI log that only wants to hear from reflock when
something's wrong. With `--format json`, `-q` leaves the findings array on
stdout untouched and just suppresses the human summary line. `-q --verbose`
is contradictory and exits nonzero naming both flags.

`reflock completion {bash,zsh,fish}` prints a static completion script for the
named shell to stdout - it writes nothing and installs nothing itself:

```bash
reflock completion bash > /etc/bash_completion.d/reflock
reflock completion zsh  > ~/.zsh/completions/_reflock   # keep the directory on fpath
reflock completion fish > ~/.config/fish/completions/reflock.fish
```

`reflock backlinks <path>` answers "what points at this file" - the question
you want answered before editing a heavily-cited document, so you know what
you'd invalidate. `<path>` accepts an anchor (`doc/DESIGN.md#section`) to
narrow to references targeting that anchor specifically. Each line is the
referring file and line, the target as written, and its pin state
(`unpinned`, `unstamped`, or `pinned`) - pin state matters because an
unpinned reference won't notice your edit. Human output ends with a trailing
`N backlink(s).` count line, matching `check`/`stamp --check`/`suspects`. A
path with no backlinks prints a clear "no backlinks" line and exits 0; a path
absent from the index exits
nonzero, since silently reporting zero backlinks for a typo'd filename would
mislead. An `#anchor` that resolves to neither a heading nor a
`reflock-anchor:` span exits nonzero for the same reason — "nothing points at
this section" is precisely the answer you act on before rewriting that section,
so a typo must not be able to produce it. `backlinks` and `explain` both accept
any spelling of a path that names an indexed file: cwd-relative, `./`-prefixed,
absolute, or the repo-relative form `check` prints, so you can paste a
`file:line` straight out of a `check` report from any directory. It's read-only and supports `--format <human|json>` per the same
renderer `check` uses; the JSON shape is a list of
`{"file", "line", "target", "pin"}` objects.

`reflock explain <file>:<line>` prints everything about the reference(s) on
that line - resolved target, matched anchor and its line span, pin, current
fingerprint, verdict, and the actual unit text that was fingerprinted -
instead of making you reconstruct that by hand from a `check` line and a
manual diff. A line with more than one reference reports all of them, in
column order; a line with none exits nonzero. It's read-only and reuses the
same `classify` logic `check` uses, so the verdict it reports can never
disagree with `check`. When a reference is `DRIFTED`, only the *pinned
text's hash* was ever stored (see the fingerprinting decision above) -
`explain` shows the current text and both hashes, and says plainly that the
prior text is not recoverable; it does not shell out to git history to
reconstruct it. Supports `--format <human|json>` per the same renderer
pattern.

The unit text is a **preview**: up to 40 lines, then one line saying how many
were withheld. For an unanchored reference the unit is the whole file, so
without that a pinned reference to a 2000-line document printed 2000 lines —
unreadable exactly where a reference matters most, since a heavily-pinned
authority file is usually a long one. Pass `--full` for all of it. The rule is
the same for anchored units: a 900-line section is no more readable than a
900-line file.

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
[what each gate can honestly promise](../DECISIONS.md#3-where-to-gate-and-what-each-gate-can-honestly-promise)<!--@c770f4c8-->.

If you'd rather keep pre-commit advisory and enforce at pre-push, use
`stamp --check` there instead of `check`: it computes exactly the edits
`stamp` would make - a pin that's opted in but unstamped, or one whose hash
would be rewritten - reports them, and writes nothing. Exit 0 means `stamp`
would be a no-op. When it isn't, output ends with a "Run `reflock stamp` to
apply." hint - `"Nothing to stamp."` gets none, needing none.
```bash
reflock stamp --check || echo "Some pins are stale; run 'reflock stamp'."
```

Add `--warn` and it reports exactly the same thing but always exits 0, for a
hook or CI step that should inform without blocking. That's the difference
between the two flags: `--check` answers "would this change anything" with its
exit code, `--check --warn` answers it only in words.
```bash
reflock stamp --check --warn    # same report, never nonzero
```

If your team already runs the [`pre-commit`](https://pre-commit.com) framework,
reflock ships a `.pre-commit-hooks.yaml`, so you don't hand-roll either script:

```yaml
repos:
  - repo: https://github.com/a-grasso/reflock
    rev: v0.4.0
    hooks:
      - id: reflock-check
      - id: reflock-stamp-check
```

The two hooks land on different stages, which is the same advisory/enforcing
split as above:

| Hook | Runs | Stage | Can it stop you? |
|---|---|---|---|
| `reflock-stamp-check` | `stamp --check --warn` | `pre-commit` | never — always exits 0 |
| `reflock-check` | `check` | `pre-push` | yes |

Install both stages once:

```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

`reflock-stamp-check` can run at commit time *because* it cannot fail. That
matters: `pre-commit` has no warn-only mode — a failing hook blocks whatever
stage it runs in — so an advisory hook has to be advisory in the command it
invokes, which is what `--warn` is for. You get told about pins that need
stamping on every commit and are never blocked by one, since a reference whose
target lands in the *next* commit is correctly `DANGLING` and blocking that is
friction you're right to resent.

`reflock-check` enforces at push: a broken reference doesn't leave your machine.
If you'd rather enforce at commit time and accept the friction, override it:

```yaml
      - id: reflock-check
        stages: [pre-commit]
```

Both run over the whole tree, not the changed files: a per-file invocation
can't see cross-file targets and would report references as `DANGLING` purely
because the file defining the target wasn't passed in.

**2. CI (the server backstop).** One job step: `reflock check`. Nonzero exit fails
the build. Deterministic, cacheable, no secrets.

Three exit codes, and the distinction between the last two is the one CI cares
about:

| Code | Means |
|---|---|
| 0 | every reference checked out clean |
| 1 | reflock ran and found problems |
| 2 | reflock could not run as asked — bad flag combination, or a path argument naming nothing in the tree |

A path argument that matches nothing is code 2, not 0. Scoping a job to
`reflock check docs/` used to keep passing the day `docs/` was renamed, which is
the exact failure reflock exists to prevent — so a stale invocation now fails
loudly instead of reporting a clean tree it never looked at. `reflock check .`
means the whole tree, as it reads.

On GitHub Actions, `check --format github` emits
[workflow commands](https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions)
instead of the human report, so each finding lands as an inline annotation on
its exact line of the PR diff rather than a log block someone has to open:
```yaml
- run: reflock check --format github
```
`DANGLING` and `DRIFTED` findings emit `::error`; `UNSTAMPED` emits `::warning`.
A clean tree prints nothing on stdout. Exit codes are unchanged from the
default format.

**3. The Stop hook (the agent).** The one people forget. When an AI coding agent
(e.g. Claude Code) edits your docs, it can *declare itself done* with references
broken. A **Stop hook** blocks the agent from ending its turn until `reflock check`
is clean — and feeds the failure back so the agent fixes it before finishing. Run
`reflock setup claude` to install and repair it (idempotent - safe to re-run after
moving or reinstalling reflock), or see [`examples/hooks/`](../examples/hooks/) for
the raw files if you'd rather wire it by hand. The key subtlety is the loop-guard:
honour the runner's "already retrying" flag so a genuinely unfixable state can't
wedge the agent.

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

## Caveats and non-goals

- **Don't pin everything.** "See also" links only need Level 1. Reserve `@fp` for
  references that assert something about the target. Over-pinning is the fast road
  to an ignored checker.
- **Prefer eliminating the reference.** If B can transclude or be generated from A
  (a single source of truth), there's nothing to keep in sync. reflock is the
  safety net for the duplication you *can't* remove — not a licence to duplicate.
- **`suspects` is a heuristic, not a gate.** It finds path-shaped prose that
  doesn't resolve. Expect some false positives (external citations); use it to
  *migrate* prose into links, not in CI.
- **`suspects` skips files nobody authored references in.** Dependency locks
  (`*.lock`, `*-lock.json`, `go.sum`), build-tool wrappers (`mvnw`, `gradlew`
  and their `wrapper/` directories), pattern lists (`.gitignore`,
  `.dockerignore`, …) and `vendor/`/`third_party/` trees. A path in a generated
  file is a fact about a build tool, and a path in a `.gitignore` is a *pattern* -
  reporting either as a failed reference inverts its meaning. The skip is
  `suspects`-only: `check` still verifies an explicit `REF:` anywhere, because
  that is a claim someone wrote. For anything else your repo generates, add it
  to `.reflockignore`.
- **`suspects` will not claim a path is rot when it can't tell.** A bare path is
  resolved relative to the file it appears in, relative to the repo root, and
  against every path already in the tree; if any of those reads resolves - or
  git ignores it - the token is dropped. What stays out of reach is a path whose
  base is a *working directory*: `dist/out.json` in a `Justfile` recipe that
  `cd`s elsewhere first is relative to a directory only the recipe knows. Those
  are reported, and `.reflockignore` is the answer if a build file's paths are
  noise for you.
- **Heading slugs are the fragile link.** Renaming a heading changes its
  auto-slug → `DANGLING`. That's caught, not silent; add an explicit
  `reflock-anchor` on hot sections if the churn annoys you.
- **Fingerprints are whitespace- and reflow-invariant.** Rewrapping a paragraph
  won't flag it; changing a word will.
- **Path arguments (`check`/`stamp`/`suspects [paths...]`) are resolved relative
  to the current working directory**, not `--root` - same convention as `git`,
  `find`, etc. Run from the repo root (or pass absolute paths) if you're
  scripting against a `--root` that differs from your CWD.
- **Fenced code blocks and inline code spans aren't parsed for references.**
  A markdown renderer treats their content as literal text, so a link or
  `REF:` comment written there to illustrate the grammar - like the examples
  in this README - is not itself checked. The trade-off: a genuine reference
  someone wraps in backticks silently stops being checked too.

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
pins inline. [DECISIONS.md](../DECISIONS.md) records what reflock chose, what it
rejected, and the evidence, including what drift tried and abandoned.
