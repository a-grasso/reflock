# Northstars

Capabilities reflock cannot do yet, but will need to, because the scenario
that demands them is either already common or clearly coming. Each entry
names the concrete situation that forces the issue, why today's design falls
short of it, and the rough shape of a fix - without committing to an
implementation until one of these is actually picked up.

This is a living document. When reflock meets a real-world case it can't
handle, the fix belongs here before it belongs in an issue tracker: write down
the scenario while it's fresh, then let it sit until it's worth building.
Update or delete an entry the moment reflock grows the capability - a
northstar that's already true is worse than no northstar, for the same reason
reflock itself exists.

## Priority tiers

- **Near** - mechanical, additive, doesn't change the core model. Could land
  in a single focused PR.
- **Medium** - needs a real design decision (a new grammar element, a new
  kind of index) but stays inside reflock's existing invariants.
- **Far** - a genuinely bigger lift (a parser dependency, a daemon, a
  cross-repo registry). Worth naming now so scope creep doesn't sneak into a
  near-term PR instead.

---

## 1. Cross-repo references are silently OK, not even checked *(Medium, but do this first)*

**The scenario:** a platform team splits docs from code into sibling repos -
an `architecture-docs` repo with an ADR that says
`// REF: ../../services/payments/src/handler.py#process_refund`, pointing at
a file in a different checkout entirely. This is an extremely common polyrepo
shape, and it is *exactly* the kind of reference reflock exists to protect -
a doc making a specific claim about a specific piece of code.

**Why reflock can't do this today:** `resolve_path` normalizes the target and
returns `None` the instant it walks past the repo root (`path.startswith("..")`).
`classify` treats `None` as `"OK", "outside tree"` - the same verdict as a
target that's genuinely none of reflock's business (a URL, a path into
`/etc`). A reference that crosses a repo boundary is indistinguishable from
one reflock has deliberately decided not to look at. That's worse than
`DANGLING`: it *looks* checked in a green `reflock check` run, but isn't.

**Shape of a solution:** a `.reflock-roots` file (or a field in a future
config) mapping a path prefix to a sibling checkout - `../payments-service ->
$PAYMENTS_SERVICE_ROOT` (env var or a sibling-directory convention, since CI
checkouts don't share a parent directory by default). A reference resolving
into a registered root gets a real verdict against that root's index instead
of a free pass. Anything not registered keeps today's "outside tree" OK -
this is additive, not a breaking change to the common single-repo case.

**Non-goal:** don't build a general multi-repo dependency resolver. Just
close the silent-OK gap for the sibling-checkout case, which is the one that
actually occurs.

---

## 2. Markdown link forms beyond `[text](target)` *(Near)*

**The scenario:** two forms show up constantly in real docs and neither is
seen at all today:

- **Reference-style links** - `[the loader][loader-ref]` with a
  `[loader-ref]: doc/adr/0013.md#loader` definition elsewhere in the file.
  Writers use this style specifically in heavily-cross-referenced docs (ADRs,
  specs) to keep prose readable - precisely reflock's target audience.
- **Wiki-links** - `[[loader]]` or `[[0013-prompts-as-resources#loader|the
  loader]]`, the Obsidian/Foam/Logseq convention. reflock's own README already
  cites Obsidian backlinks as prior art; teams that keep engineering notes in
  an Obsidian vault next to (or inside) a code repo will write these by
  reflex.

**Why reflock can't do this today:** `MD_REF` only matches the inline
`[text](url)` form. A reference-style link or a wiki-link isn't parsed at
all - not `DANGLING`, not anything. It's invisible, the same failure mode as
#1: looks clean, isn't checked.

**Shape of a solution:** two more regexes (or one grammar table) alongside
`MD_REF`: a link-definition line (`^\[id\]:\s+(\S+)`) resolved against its
inline usages, and a wiki-link pattern with `#anchor` and `|alias` handled the
same way `[text](target)` already is. Both plug into the existing
`Ref`/`classify` pipeline unchanged - this is grammar surface area, not a
design change.

---

## 3. `stamp --check`: verify without mutating *(Near)*

**The scenario:** a CI job wants to fail if any reference *should* be
stamped but isn't up to date - the same "would this formatter change
anything" check `prettier --check`, `terraform fmt -check`, and `black --check`
already offer - without actually writing files in CI (which either requires
a follow-up commit-back step, or gets silently discarded, either way not
what you want in a gate).

**Why reflock can't do this today:** `stamp` always writes. The only
workaround is running it and then `git diff --exit-code`, which works but
means every CI config reimplements the same two-line dance instead of
reflock providing it directly, and it produces confusing diffs in CI logs
mixed with the job's own output.

**Shape of a solution:** `reflock stamp --check` computes the same edits
`stamp` would make, reports what's unstamped/stale (reusing the `check`
verdict machinery - an `UNSTAMPED` or a would-be `DRIFTED`-if-rebless-ran is
already the right signal), and exits nonzero without touching disk. Small,
mechanical, and closes a real CI ergonomics gap the "Three gates" section of
the README already promises but doesn't fully deliver.

---

## 4. CI-native output: inline annotations, not just a log block *(Near)*

**The scenario:** a reviewer wants a `DANGLING` or `DRIFTED` finding to show
up as an inline comment on the exact changed line in a GitHub PR diff - the
way ESLint, mypy, and most linters already integrate with GitHub Actions -
instead of a flat report buried in a build log that nobody opens unless the
job is already red.

**Why reflock can't do this today:** `check --json` is a fine machine format,
but nothing translates it into the annotation formats CI systems actually
render inline (`::error file=...,line=...::message` for GitHub Actions,
SARIF for GitHub's code-scanning tab, similar conventions for GitLab).
Every adopter has to write that translation layer themselves.

**Shape of a solution:** `reflock check --format=github` (or `--format=sarif`)
alongside the existing plain/`--json` output - a formatting concern only,
the verdict computation doesn't change at all.

---

## 5. Symbol-level code anchors without hand-placed markers *(Medium)*

**The scenario:** `// REF: src/auth/session.py#validate_token` should resolve
directly to the function, the way an IDE's "go to definition" does - no
`reflock-anchor: validate_token` / `reflock-anchor-end: validate_token`
comment pair required around it. Hand-placed span markers work but ask
every hot symbol to be pre-instrumented, which is exactly the kind of manual
convention that quietly stops happening under deadline pressure.

**Why reflock can't do this today:** the only non-markdown anchor mechanism
is the explicit span. reflock has no notion of a function, class, or
symbol - it's grep, not a parser, by design (see the README's stated
invariant: "no model in the hot path... a grep, a hashmap lookup, and a byte
compare").

**Shape of a solution:** an optional, per-language symbol index built with a
lightweight parser (tree-sitter is the obvious candidate - this codebase's
own tooling already leans on it for structural search) that resolves
`#symbol_name` against function/class/method definitions when no explicit
span exists, falling back to "no such anchor" otherwise. This is deliberately
last in priority among the near-term items because it's the one that
actually trades away the zero-dependency, pure-regex simplicity that makes
reflock cheap and trustworthy today - worth doing, but worth being honest
that it changes the tool's character.

**Non-goal:** don't reimplement a language server. Definition-line resolution
only, not call-graph or type-aware anything.

---

## 6. Anchors into config/data files by key path *(Medium)*

**The scenario:** an infra doc says "see `docker-compose.yml#services.web.ports`"
or `deploy.yaml#spec.replicas` - a claim about a specific key in a YAML/JSON/
TOML file, not the whole file and not a markdown heading (there isn't one).
Platform and SRE docs make this kind of reference constantly.

**Why reflock can't do this today:** the anchor grammar is headings-or-explicit-
span. A YAML file has neither. The only options today are pinning the whole
file (defeats the point - noisy, flags on unrelated key changes) or adding a
`reflock-anchor` comment into the config file, which is invasive for files
you may not want cluttered with tool-specific markers, and impossible for
files with no comment syntax (strict JSON).

**Shape of a solution:** a small per-format key-path resolver (dotted-path
into parsed YAML/JSON/TOML) that returns the sub-tree at that key as the
fingerprinted unit, same contract as `unit_text` today.

---

## 7. Reference repair on file move/rename *(Medium)*

**The scenario:** `git mv doc/adr/0011-old-name.md doc/adr/0011-new-name.md`.
Every reference to the old path is now `DANGLING`, even though - to a human -
nothing meaningful changed. Multiply by however many references point at a
frequently-reorganized doc tree and a routine rename becomes a wall of red
that has nothing to do with the actual content drift reflock is supposed to
surface.

**Why reflock can't do this today:** reflock has no notion of history. Every
run is a stateless index-and-compare; `DANGLING` is the technically-correct
verdict for "path doesn't exist," and it can't distinguish "deleted" from
"renamed."

**Shape of a solution:** `reflock stamp --repoint`, which for each `DANGLING`
reference: (a) asks `git log --follow`/rename-similarity detection whether
the old path became a tracked new path, and repoints the reference
automatically if so; (b) falls back to a fuzzy filename match (basename
similarity within the same subtree) when git history doesn't have a clean
rename to offer (squashed history, moved outside a single commit). Anything
neither method resolves stays `DANGLING`, unchanged from today.

---

## 8. Scale: incremental/cached indexing for large monorepos *(Far)*

**The scenario:** reflock's whole pitch is "no model in the hot path,
milliseconds on a real repo." That holds today because `build_index` reads
every tracked text file on every invocation. At monorepo scale (tens of
thousands of files) a full re-read on every `check` - every pre-commit hook,
every CI run, every agent Stop-hook check - stops being free, and "free" is
the load-bearing claim in this tool's whole design argument.

**Why reflock can't do this today:** there's no persistence between runs -
by design, for simplicity, and it's the right call until it measurably isn't.

**Shape of a solution:** an on-disk cache keyed by `(path, mtime, size)` (or a
content hash if mtime proves unreliable in CI checkouts) that skips re-reading
and re-hashing unchanged files, invalidated file-by-file rather than
wholesale. Only worth building once a real repo's `check` stops feeling
instant - this is explicitly not worth pre-optimizing for.

---

## 9. Editor/LSP integration: check-on-save, jump-to-reference *(Far)*

**The scenario:** a human or an agent (Claude Code, Cursor, etc.) editing a
doc sees a squiggly under a reference the moment it goes stale - not at the
next `reflock check`, whether that's a pre-commit hook or a Stop hook. "Peek
target" shows the pinned section inline; a quick-fix runs `stamp` on just
that reference.

**Why reflock can't do this today:** reflock is a batch CLI with no persistent
process, no file-watch, and no editor protocol implementation.

**Shape of a solution:** a thin LSP server wrapping the existing
`build_index`/`classify` pipeline unchanged, with a file-watcher to keep the
index warm between saves. This is the single biggest lift on this list and
depends on #8 (a watch-mode daemon needs the incremental index to stay cheap
per keystroke-adjacent save) - sequence it last.
