# Public-presentable plan

Working document. Delete once the tasks below are done and reflock has been
announced. `a-grasso/reflock` is **already public** (MIT, on a Homebrew tap,
v0.3.0) - this is not a switch-flip, it is making the public thing presentable.

**Status: all waves executed in one session (2026-08-09).** What each task
actually did, and where it diverged from the plan, is recorded inline below.
`just gate` is green throughout: 323 unit tests, 142 fixtures, all references OK.

---

## Wave 0 - done in this session, needs review only

- [x] **T0.1** CI workflow `.github/workflows/ci.yml` - tests + bench + self-check
  on Python 3.9-3.13, on push to main and on every PR. Previously the repo had
  *only* `release.yml`; nothing verified a PR.
- [x] **T0.2** `.gnhf/` (agent-harness run logs: prompts, transcripts) added to
  `.gitignore`. It was untracked but unignored - one `git add -A` from publishing.
- [x] **T0.3** Employer bleed scrubbed from tracked files: "kai-crm dogfooding"
  and a `com/deviceinsight/kaicrm/...` path in `docs/ROADMAP.yaml` and
  `docs/roadmap/BUG-08..13`. (History still contains them - see T4.3.)
- [x] **T0.4** `CONTRIBUTING.md` and `SECURITY.md` written.
- [x] **T0.5** Issue templates (bug/feature), issue-template config, PR template.
- [x] **T0.6** `.claude/settings.json` allowlist un-rotted (`make *` -> `just *`).
- [x] **T0.7** Docs reshuffle, first pass: `roadmap/` -> `docs/roadmap/`,
  `ROADMAP.yaml` -> `docs/ROADMAP.yaml`, `IDEAS.md` -> `docs/IDEAS.md`, with all
  ~125 references repaired. `DECISIONS.md` and `NORTHSTARS.md` deliberately stayed
  at root: the agent-docs standard treats them as authoritative and the README
  points at them.

---

## Wave 1 - correctness before an audience

### T1.1 - Reserve the stamp format version (NORTHSTARS #11) - **done**

**The one genuine pre-announcement blocker.** `NORTHSTARS.md` §11 is marked
*"Near, do before wide adoption"* and announcing is exactly what creates wide
adoption. A stamp is bare hex with no room for a version marker, so every repo
that adopts reflock bakes today's hash rule into its files permanently. Retrofit
cost rises with every adopter.

Implement the shape §11 already specifies: bare hex keeps meaning v1 (zero
behaviour change, zero migration), `@2:newhex` is reserved and parsed, `check`
and `stamp` dispatch on the prefix. Add fixtures for: a v1 bare stamp still
round-trips; an unknown version prefix produces a clear error rather than a
false `DRIFTED`. Then update `NORTHSTARS.md` - the file's own rule is that an
entry is deleted the moment reflock grows the capability.

**Done.** `FP_VERSION`/`PIN_BODY` in `grammar.py`, `split_pin` in `engine.py`,
a new `UNSUPPORTED` verdict wired through the human/JSON/GitHub renderers and the
exit-code set, and `stamp --rebless` now refuses to downgrade a pin it cannot
read. Three fixtures plus a `PinVersionTest` class. NORTHSTARS #11 is struck
through and kept as a stub, because the "freeze the wire format before any port"
sequencing note below it depends on the entry.

### T1.2 - Pre-announcement scope of NORTHSTARS #10 and #12 - **done, and #10 implemented**

Do not implement yet - produce a recommendation with evidence, as a short
writeup under `docs/roadmap/`.

- **§10** (re-blessing a `DRIFTED` reference is one flag from a rubber stamp,
  *Near*): a first-time reader will judge reflock on whether `stamp` can be
  abused into meaninglessness. Is a guard needed before the post, or is it an
  honest "known, tracked" entry?
- **§12** (a vendored doc carries stamps from its home repo, *Medium*): this one
  bites *because of* publishing - `examples/skill/refcheck/SKILL.md` is meant to
  be copied into other repos, which is precisely the scenario. Check whether the
  shipped example actually breaks on arrival; if it does, that is a bug in the
  example, fixable without §12.

**Done:** [PUB-01](docs/roadmap/PUB-01-pre-announcement-scope.md).

- **§10: implemented.** The writeup recommended implementing rather than
  deferring, so it was implemented in the same pass. `stamp --rebless` now
  requires `--reviewed`; without it, it lists what it would re-bless with old and
  new fingerprints and exits nonzero. One rule in a TTY and in CI alike. This is
  a deliberate behaviour change to an existing flag, taken now precisely because
  adoption is still small.
- **§12: no action, and the premise was wrong.** `examples/skill/refcheck/SKILL.md`
  was checked directly: it contains no pins and no `REF:` comments, so copying it
  into a foreign repo breaks nothing. The entry stays open with a guard rail
  noted for the day an example does ship stamped references.

### T1.3 - Fresh-machine install audit - **done, found a broken install path**

**`brew install a-grasso/tap/reflock` was broken and had been for a release
cycle.** The formula installed `reflock.py` alone; the implementation has lived
in the `reflock_lib` package beside it since the modularization, so the installed
command died on import with `ModuleNotFoundError`. Reproduced by rebuilding the
formula's layout locally. Written up as
[BUG-14](docs/roadmap/BUG-14-homebrew-ships-entry-point-without-package.md).

Fixed in the formula template in `release.yml` (both files into `libexec`, a
symlink into `bin`, and a `test do` block that runs a real stamp/check round trip
instead of `--help`). **The published tap formula stays broken until the next
release is cut** - this is the strongest argument for tagging v0.4.0 before
announcing.

`install.sh` was never affected, in both modes: it symlinks the entry point, and
Python resolves the symlink before putting the script's directory on `sys.path`.
Version facts all agree (tag v0.3.0, `__version__`, README `rev:`).

Regression cover: a new `install-layouts` CI job rebuilds *both* distribution
layouts and drives `--version`, `stamp` and `check` from outside the checkout.
The lesson generalizes - verify the artifact from where a user runs it, never
from the tree that built it.

---

## Wave 2 - documentation pass

### T2.1 - README rewrite: essay -> landing page

`README.md` is 512 lines. The writing is good, which is the problem: it is a
design essay where a visitor needs a landing page. Cut to roughly 150 lines:
the hook, the `reflock check` demo block, install, the two levels of the
convention, a CLI table, and links out. Move the deep material - the full
grammar, the design rationale, the prior-art section, the limitations - into
`docs/`, losing no content. Keep the `rev: vX.Y.Z` line intact and in a form
`just release` can still rewrite (it regexes `rev: v[0-9.]+` in `README.md` -
if you move that line to another file, update the `Justfile` recipe too, or the
next release will silently stop updating it).

**Done.** README 512 -> 187 lines; the reference material moved to
[docs/manual.md](docs/manual.md) (343 lines) with nothing lost. The `rev:` pin now
appears in *two* files, so `just release` rewrites `README.md` and `docs/*.md`,
and `VersionConsistencyTest` checks every file the recipe reaches. Both exclude
`docs/roadmap/` and `docs/adr/` on purpose: those are historical records, and
DOC-01 quotes an old `rev:` *as the bug it documents*. The test caught that
distinction by failing when the first, broader rule was written.

### T2.2 - Documentation accuracy sweep

Every claim in `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `DECISIONS.md`,
`NORTHSTARS.md`, `docs/IDEAS.md`, `evalbench/README.md` and each
`AGENTS.md` under a module, checked against the code as it is today. reflock
proves references *resolve*; nothing proves prose is still *true*, which is the
exact failure mode reflock exists to shame.

Priorities: CLI surface (flags, subcommands, exit codes) versus
`reflock_lib/cli.py`; every command in `AGENTS.md`/`CONTRIBUTING.md` actually
run; the Justfile-migration rot pattern (`make` survivors) grepped for
repo-wide; the doc-map sections still matching the tree after the Wave 0 move.
**Done.** Fixed: `AGENTS.md` still mapped `roadmap/` at the root and described a
`docs/decisions/` directory that turned out to be **empty and untracked** (removed,
and the claim with it); `reflock_lib/AGENTS.md` still pointed at `make` targets;
`reflock.py`'s module docstring listed four of the seven subcommands and was
missing the new `UNSUPPORTED` verdict.

One claim was corrected rather than confirmed: the README said Python 3.8+. The
floor is now stated as **3.9+**, which is what the CI matrix actually proves. The
sources parse under a 3.7 feature version, so 3.8 probably works, but an untested
claim is the thing this sweep exists to remove.

### T2.3 - Second docs-layout pass

**Done, and deliberately conservative.** `DECISIONS.md` and `NORTHSTARS.md` stay
at the root: both are linked from the README as the honest record of what reflock
rejected and what it cannot do yet, and the agent-docs standard treats them as
authoritative. `docs/decisions/` was an empty untracked directory and is gone, so
`docs/adr/` is now unambiguously the home for architecture decisions.
`CLAUDE.md -> AGENTS.md` stays a symlink. Final root: README, LICENSE,
CONTRIBUTING, SECURITY, AGENTS/CLAUDE, DECISIONS, NORTHSTARS, the entry point,
tests, and build files.

### T2.4 - Repo metadata

**Topics set** (cli, developer-tools, docs-as-code, documentation,
documentation-tool, link-checker, pre-commit, python, static-analysis).

**No CHANGELOG, and the task's own premise was wrong**: nothing in this repo ever
claimed changelogs were auto-generated - that rule lives in the *global* agent
instructions, not here. `release.yml` already publishes GitHub releases with
`--generate-notes`, which is a real changelog kept by the tag history. A
hand-maintained `CHANGELOG.md` would be a second source of truth for the same
facts, which is the duplication reflock exists to argue against.

**Homepage left unset** - there is no site, and pointing it back at the repo adds
nothing. Worth revisiting only if docs ever get a Pages build.

---

## Wave 3 - the coffee button and the announcement

### T3.1 - Funding

**Done, Buy Me a Coffee only** (`a.grasso`) - Ko-fi dropped at the maintainer's
call. `.github/FUNDING.yml` drives the native Sponsor button; the README carries
one line at the very end, after the license note.

### T3.2 - LinkedIn post

One post introducing reflock. The angle that earns attention is the *problem*,
not the tool: a link-checker reports green while the paragraph describing the
thing it links to has been wrong for six months, because the link still
resolves. Then the one-line mechanism - record a content fingerprint of the
target, fail when it drifts, `package-lock.json` for cross-references.

Constraints:
- Include one sentence linking [portbook](https://github.com/a-grasso/portbook)
  in the same voice: yet another tool I needed for myself, it works, so it is
  public now. That framing is the honest one and it is also the reason both are
  worth reading about.
- No em dashes. No hype vocabulary, no "excited to announce", no rule-of-three
  flourishes, no emoji rows.
- German-native, English post. Keep sentences plain.
- Deliver two variants (short ~120 words, longer ~250 with the worked example
  from the README) plus a suggested first comment carrying the repo link.

**Done, and deliberately not committed.** Both variants plus a first comment
carrying both repo links, handed over outside the repo: post copy is marketing
material with a shelf life of one day, and the repo is the product. Nothing here
should read as if the tool ships its own press release.

---

## Wave 4 - judgement calls for the maintainer

- **T4.1** Demo GIF or asciinema of `reflock check` -> `explain` -> `stamp`.
  **Still open** - it needs a terminal recording, which is a human's job, not
  something to fake. It is the single highest-value addition left for both the
  README and the post.
- **T4.2 - done.** A `stdlib-only` CI job imports reflock with `python3 -S` on a
  runner with nothing pip-installed, so the project's central promise now fails a
  build instead of a code review.
- **T4.3** Git history still contains the internal project name scrubbed in
  T0.3. A rewrite is disruptive for a repo already published and installed via
  Homebrew, and the exposure is an internal *project* name, not a secret.
  Recommendation: leave it. **Still needs an explicit decision.**

- **T4.4 - cut a release before announcing.** Not optional now: the published
  Homebrew formula is broken until a tag ships the fixed template (T1.3), and
  `--reviewed` plus the `UNSUPPORTED` verdict are behaviour changes worth a minor
  bump. `just release 0.4.0` after the working tree is committed.
