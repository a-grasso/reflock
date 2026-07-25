# Ideas — expanding reflock

A wide brainstorm on making reflock more efficient, easier to use, and more
effective at catching reference rot. Where an idea overlaps a scenario
already worked out in [NORTHSTARS.md](NORTHSTARS.md), it's cross-referenced
rather than re-derived — this document is the broader, shallower pass;
NORTHSTARS is the deep one. Nothing here is committed to; it's raw material
for future prioritization, grouped by the angle it comes from rather than by
priority tier.

---

## Efficiency

1. **Cached/incremental index.** Already the deepest entry in NORTHSTARS
   ([#8](NORTHSTARS.md)) — full re-read on every invocation stops being free
   at monorepo scale.
2. **Content-address the cache by git blob hash, not mtime.** Git already
   content-addresses every tracked file; keying a future cache
   (`git hash-object` per path, or `git ls-files -s`) on blob SHA instead of
   `(mtime, size)` sidesteps the classic "CI checkout resets mtimes" cache
   invalidation trap entirely, and composes cleanly with idea #1.
3. **Parallel file reads in `build_index`.** Reading and hashing every
   tracked text file is I/O-bound and embarrassingly parallel; a thread pool
   (GIL releases during file I/O) would cut wall time on large repos with
   zero change to the single-file, no-dependency design.
4. **Lazy target-side parsing.** `check <path>` already scopes which files
   are treated as *sources*, but `build_index` still reads the whole tree to
   resolve *targets*. Deferring per-file parsing (headings, spans) until a
   reference actually resolves into that file would speed up narrowly-scoped
   invocations (a single pre-commit run touching 3 files in a 5,000-file repo).
5. **A cheap `--watch` mode as a stepping stone to LSP.** Full editor
   integration is rightly last on NORTHSTARS ([#9](NORTHSTARS.md)) because it
   depends on incremental indexing. A much smaller `reflock check --watch`
   (poll mtimes or use `watchdog`, rerun `check` on the scoped file, print a
   diff of the verdict list) gets most of the "see it break immediately"
   value today, without a daemon or a protocol.

## Ease of use

6. **`reflock init`.** One command that drops a starter `.reflockignore`, a
   `pre-commit` hook, a CI workflow snippet, and one commented example `REF:`
   marker into the current repo. Today all of that lives in `examples/` and
   has to be hand-copied; adoption friction is the whole game for a
   convention that only works if a team actually turns it on.
7. **"Did you mean?" suggestions on `DANGLING`.** When a target doesn't
   resolve, a fuzzy match (basename similarity, same directory first) against
   `idx.files` costs one extra pass and turns "no such file: x.md" into
   "no such file: x.md — did you mean y.md?", the same instinct git typo
   suggestions use. Pairs naturally with the rename-repair idea in
   NORTHSTARS ([#7](NORTHSTARS.md)) — the fuzzy matcher is shared machinery.
8. **Interactive `reflock fix`.** Walk `DANGLING`/`DRIFTED` findings one at a
   time, show the suggested new target or the drifted diff, prompt
   accept/skip/edit. A human-in-the-loop complement to the fully automatic
   `stamp --repoint` NORTHSTARS proposes.
9. ~~**Colorized terminal output.**~~ Implemented: `check`'s verdict labels
   are colored by severity, honoring `NO_COLOR`, `--no-color`, and non-tty
   auto-detection.
10. **`reflock explain <file>:<line>`.** One command that prints everything
    about a single reference — resolved target, anchor, current vs. pinned
    fingerprint, the actual unit text on both sides — instead of making
    someone reconstruct that by hand from a `check` line and a manual diff.
11. **Shell completion.** `argparse` can generate bash/zsh/fish completions
    almost for free; near-zero cost, standard expectation for any CLI a
    developer runs daily.
12. **A config file (`reflock.toml` / `.reflock.yml`).** `--root`, ignore
    patterns, default output format, and future per-path pin policy currently
    have to be repeated as flags in every hook and every CI step. One file,
    read once, checked in next to `.reflockignore`.

## Effectiveness — catching more real drift

13. **Fuzzy/percentage drift instead of only exact-hash mismatch.** Today
    `DRIFTED` is binary (hash matches or it doesn't), which is the right
    default (see the "whitespace-invariant" design note in the README) but
    can't distinguish a one-word tweak from a rewritten section. An optional
    similarity score (e.g. token-level diff ratio) surfaced in `--verbose`
    output would help a reviewer triage a long `DRIFTED` list by how much
    actually changed.
14. **`reflock backlinks <path>`.** "What points at this file" is the
    Obsidian instinct the README already names as prior art, but it's never
    surfaced as its own command — today you'd have to grep the whole index
    yourself. Directly useful before editing a heavily-cited file: "what
    would I invalidate?"
15. **Detect verbatim-pasted excerpts, not just links.** The README's own
    caveat says "prefer eliminating the reference — if B can transclude
    A, there's nothing to keep in sync." A checker that flags an
    N-line block in B that closely matches a block in A (and isn't a
    `REF:`-declared reference at all) surfaces the duplication reflock exists
    to discourage, not just the references that already declare themselves.
16. **Referenced commit SHAs / tags as targets.** Prose like "as of commit
    `a1b2c3d`" or "fixed in v1.2.0" is a reference to repo history, not a
    file. A lightweight check that such tokens still resolve
    (`git cat-file -e`, `git tag -l`) extends the same mechanical-verification
    idea to a reference *shape* that shows up constantly in changelogs and
    postmortems.
17. **Nudge toward pinning, don't just enforce it.** For an *unpinned*
    reference (Level 1 only) whose target changed since the reference's own
    line last changed (per `git log`), surface a low-severity "this looks
    like it could use `@fp`" suggestion — pure opt-in nudge, never a failing
    verdict, that helps a team find good pinning candidates instead of
    guessing where to add `@`.
18. **Opt-in, strictly separate external-link liveness check.** `check
    --external` (never part of default `check`, since it breaks the
    "no network in the hot path" invariant) that HEAD-requests `http(s)`
    targets with a timeout and rate limit — closes the one reference shape
    (external URLs) reflock explicitly can't and shouldn't check by default,
    without compromising the core guarantee.

## Ecosystem & integration

19. **A published GitHub Action, not just documented YAML.**
    `a-grasso/reflock-action@v1` as a real composite/Docker action turns
    adoption into one line in a workflow instead of "read the README and
    hand-write the steps" — matches how every other linter ships today.
20. **A `pre-commit` framework manifest (`.pre-commit-hooks.yaml`).** Most
    teams already run `black`/`ruff`/`mypy` through the `pre-commit` tool's
    `repos:` list, not hand-rolled `.git/hooks/pre-commit` scripts. Shipping
    the manifest lets reflock slot into that existing convention instead of
    asking every adopter to reinvent the hook-install step the README
    currently documents manually.
21. **A minimal VS Code extension ahead of full LSP.** Run
    `reflock check --json` on save, render results via VS Code's Diagnostics
    API. Much smaller than the full LSP in NORTHSTARS ([#9](NORTHSTARS.md))
    — no file-watch daemon, no incremental index dependency — and could ship
    as a stepping stone that delivers most of the "see it break on save"
    value years before #9 is justified.
22. **An Obsidian plugin.** The README already cites Obsidian backlinks as
    prior art, and wiki-links are a named grammar gap (NORTHSTARS
    [#2](NORTHSTARS.md)). A vault-side plugin surfacing reflock verdicts
    inline closes the loop for the exact audience the tool's own design
    language borrows from.
23. **A scheduled "drift bot."** A cron job that runs `check`, and for
    `DRIFTED` findings opens or updates a single tracking issue/PR
    summarizing what needs a human look — softer than failing CI red on
    every commit, useful for a doc tree that's checked but not yet gated.

## Reporting & observability

24. **`reflock stats`.** A corpus-level summary — total references, %
    opted into Level 2 pinning, oldest un-reblessed pin, files with the most
    inbound/outbound references. Answers "is this team actually using the
    convention" at a glance, which today requires manually diffing `check
    --json` output.
25. **Historical trend tracking.** Append each CI run's `check --json`
    output (verdict counts, not full detail) to a flat log artifact, so
    "is reference rot getting better or worse in this repo over the last
    quarter" becomes a chart instead of a guess — useful ammunition for a
    team deciding whether to invest in more pinning.
26. **Owner/severity annotations on references.** Let a marker optionally
    carry `@team-x` or a severity tag, so `check --json` results can be
    grouped and routed (auto-assign a PR comment to the right reviewer)
    instead of always being a flat, unowned list.

## Extensibility & architecture

27. **A documented resolver extension point.** An entry-point or
    `REFLOCK_RESOLVERS` env var pointing at a Python module lets a team add
    its own anchor resolver (a symbol index per NORTHSTARS
    [#5](NORTHSTARS.md), a key-path resolver per NORTHSTARS
    [#6](NORTHSTARS.md)) without waiting on upstream — keeps the shipped core
    dependency-free while letting teams opt into their own dependencies.
28. **A versioned JSON Schema for `--json` output.** As more consumers
    (CI annotators, dashboards, the stats/trend ideas above) start depending
    on `check --json`, a published, versioned schema turns that into a
    contract instead of "whatever `json.dumps` happens to emit today" —
    especially relevant once `--format=github`/`--format=sarif`
    (NORTHSTARS [#4](NORTHSTARS.md)) exist alongside it.
29. **Explicitly document and test more comment-marker forms.** `REF:`
    presumably targets `//`-style line comments today; writing down (and
    covering with fixtures) the equivalent for `#`, `--`, `<!-- -->`, and
    block-comment languages broadens adoption to Python/SQL/Lua/HTML without
    any code change — just convention + tests.

## Distribution

30. **A PyPI package installable via `pipx`.** Homebrew and `install.sh`
    cover macOS/Linuxbrew and "clone it yourself" well; a `pipx install
    reflock` on-ramp reaches Linux CI runners and developers without
    Homebrew who'd otherwise have to hand-roll the `curl | bash` step.
31. **A prebuilt container image.** `docker run ghcr.io/a-grasso/reflock
    check` removes any Python-version question from a CI runner entirely —
    single dependency-free file makes this a trivial image to build and
    keep small.

---

Total: **31 ideas** across six angles (efficiency, ease of use,
effectiveness, ecosystem/integration, reporting, extensibility/distribution).
None of these are scoped or scheduled — treat this as a wider net cast
around the same problem NORTHSTARS.md already prioritizes in depth; promote
an idea from here into NORTHSTARS (with a concrete scenario) before it
becomes an issue.
