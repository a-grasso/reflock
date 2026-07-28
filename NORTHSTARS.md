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

Everything here is a capability to *add*. Questions already settled the other
way - what reflock deliberately does not do, and the evidence for it - live in
[DECISIONS.md](DECISIONS.md), which is also the one place a competing tool's
observed state is recorded, so entries below can cite it instead of each
carrying their own copy that ages separately.

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

**Fingerprint the AST, not the bytes.** When this lands, the unit hash for a
resolved symbol should be a *normalized syntax tree* rather than raw text:
node kinds plus token text, with whitespace and position stripped. Raw content
hashing is right for prose (a reflowed paragraph is the same paragraph) but
wrong for code, where a reformat or a rename in an adjacent line is not a
semantic change and shouldn't flag every reference to the function. This is
the approach [fiberplane/drift](DECISIONS.md#prior-art-under-observation)
takes, and it composes naturally with the Rust port discussed below, where
tree-sitter links statically.

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

**Demand signal:** this is the most-requested open issue on
[drift](DECISIONS.md#prior-art-under-observation) too - independent evidence
that config keys are a real documentation-drift hotspot and not just a
hypothetical one. Neither tool supports it today.

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
rename to offer (squashed history, moved outside a single commit); (c) for a
*pinned* reference, the recorded fingerprint is a third signal stronger than
either - recompute every candidate file's hash and prefer an exact content
match over a fuzzy name match, since reflock already has the hash on hand and
[fiberplane/drift](https://github.com/fiberplane/drift) has nothing
equivalent (a renamed target there just reports "not found," full stop).
Anything none of the three methods resolves stays `DANGLING`, unchanged from
today.

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

---

## 10. Re-blessing a `DRIFTED` reference is one flag away from a rubber stamp *(Near)*

**The scenario:** the whole pitch of the Stop-hook gate (README, "Three
gates") is that an agent can't declare itself done with references broken.
But `stamp --rebless` has no such friction: an agent (or a human on autopilot)
facing a red `check` can run `stamp --rebless` and go green without ever
reading what changed. That's not a bug in the mechanism - the mechanism did
exactly what it was asked - but it is a bug in the *gate*, because the whole
argument for reflock existing is that a DRIFTED verdict corresponds to a real
"someone should read this" event, and this command lets that event be
silently discarded.

**Why reflock can't do this today:** `--rebless` unconditionally accepts the
current target state as correct and writes the new hash. There's no diff
shown, no confirmation required, no distinction between "I read this and it's
fine" and "I want this error to go away."

**Shape of a solution:** `stamp --rebless` prints, per reference, the
referencing line/paragraph next to the target unit's current text (a real
before/after, not just a hash), and requires either an interactive
accept-per-item prompt (TTY) or an explicit `--reviewed` flag (non-TTY / CI /
agent) to actually write. Without it, exit nonzero with the diff on stderr -
forcing an agent to either engage with the content or fail visibly, never to
silently rubber-stamp.

**Prior art:** [drift](DECISIONS.md#prior-art-under-observation) shipped exactly
this - re-blessing refuses by default and requires an explicit
"the doc is still accurate" flag. The single most directly copyable idea from
watching a live competitor, and it closes a concrete hole in reflock's own
central claim rather than adding a new capability.

---

## 11. The stamp format has no version tag, and it's a published wire format now *(Near, do before wide adoption)*

**The scenario:** `FP_LEN` hex chars of truncated sha256 is not an
implementation detail - it's a contract every adopting repo bakes into its
files the moment `stamp` runs. If the hash function, truncation length, or
normalization rule ever needs to change (a collision-margin concern, a
mismatch discovered during the Rust port's differential testing against the
eval bench), there is currently no way for a stamp to say "I was computed
under the old rule." A change forces a choice between two bad options: freeze
the algorithm forever, or force a false `DRIFTED` wave across every repo that
adopted reflock in the meantime, the instant an update rolls out.

**Why reflock can't do this today:** a stamp is bare hex - `@a1b2c3d4` - with
no room for a version marker.

**Shape of a solution:** reserve the version now, while adoption is small
enough that this costs nothing: bare hex continues to mean "v1" (no behavior
change, no migration needed today), and a future algorithm ships as
`@2:newhex`; `check`/`stamp` read the prefix and dispatch to the matching
fingerprint function. Cheap to add before stamps exist widely in the wild,
expensive to retrofit after - this is exactly the kind of decision the
"freeze the wire format before any port" sequencing note (below) is warning
about, so it should land before, not during, that port.

**Prior art:** [drift](DECISIONS.md#prior-art-under-observation) has only a
coarse file-level lockfile version, no per-binding algorithm tag. The gap
matters *more* for reflock: a lockfile can be migrated by bumping one field,
whereas inline stamps (DECISIONS.md #1) are scattered across every referring
file and cannot be. The cost of not reserving this is paid at exactly the
moment adoption makes it expensive to fix.

---

## 12. A vendored copy of a doc carries stamps that don't belong to this repo *(Medium)*

**The scenario:** a doc with its own stamps gets copied wholesale into a
second repo - a shared onboarding guide, a vendored README, an agent skill
file distributed the way Claude Code skills are. The copy's pins were blessed
against the *original* repo's targets, which simply don't exist in the new
repo. Every one of those references goes `DANGLING` on arrival, even though
nothing is actually wrong - the doc is exactly as accurate as it was in its
home repo.

**Why reflock can't do this today:** there's no notion that a file's stamps
were computed against a different tree than the one `check` is currently
walking. This is a different gap from northstar #1 (a reference that *points
across* a repo boundary, but is evaluated in the repo it lives in); here the
whole file's origin is elsewhere.

**Shape of a solution:** an optional per-file or per-reference origin marker
(`<!-- reflock-origin: git@github.com:org/repo.git -->` near the top of a
doc, or an `@origin` suffix on a `REF:` line) that `check` compares against
the current repo's own `git remote get-url origin`. On a mismatch, treat the
reference the same way reflock already treats a target outside the tree
(`OK`, deliberately unchecked) rather than `DANGLING` - additive, and the
common single-repo case is untouched.

**Prior art:** [drift](DECISIONS.md#prior-art-under-observation) ships exactly
this - an `origin` field per binding - specifically so its own agent skill file
can be distributed into other repos without every binding going stale on
arrival. Note this cost is one reflock accepted knowingly when it chose inline
pins over a lockfile (DECISIONS.md #1); this entry is how it gets paid down.

---

## Language & runtime: when Python stops being the right host *(Far, cross-cutting)*

Not a capability - a constraint that sits underneath several of the entries
above. reflock today is ~1,350 lines of stdlib-only Python: `reflock.py`, the
single executable entry point install.sh symlinks onto PATH and the
pre-commit manifest invokes directly, plus `reflock_lib/`, a handful of small
modules (grammar, engine, commands, cli) it re-exports from since outgrowing
one file. Zero dependencies and zero model calls in the hot path are the load-
bearing halves of that legibility argument, and the split doesn't touch
either; what it gives up is literally-one-file, in exchange for each concern
being readable on its own rather than scrolled past inside twelve hundred
lines of everything else. Trading the *zero-dependency, no-model* half away
needs a reason, and several of the northstars above are that reason.

**Measured baseline (117 tracked files, this repo):** `reflock check` takes
~0.07s user + 0.04s sys but ~0.5s wall. Python interpreter startup is ~0.017s.
The tool is blocked on `git ls-files` and `git check-ignore` subprocesses, not
on Python. Today's latency is a design problem, not a language problem, and a
naive port that still shells out to git would be no faster. Fix the subprocess
round-trips first; they are cheap and need no rewrite.

### What actually forces a compiled language

Ranked by how decisive each one is:

1. **#5 (tree-sitter symbol anchors) - decisive.** Rust is tree-sitter's native
   home: grammars link statically at compile time, no cgo, no dynamic `.so`
   loading. In Python this means `py-tree-sitter` plus a per-language wheel
   matrix, which destroys the zero-dependency story that makes reflock cheap to
   trust. In Go it means cgo, which destroys the single-static-binary story.
2. **#8 (incremental indexing at scale).** The ripgrep crate lineage maps 1:1
   onto what reflock does: `ignore` for gitignore-aware walking (which deletes
   both git subprocesses *and* the hand-rolled `.reflockignore` `fnmatch` path,
   the same neighbourhood that produced the slugify/ignore class of bugs),
   plus `globset`, `memchr`, and `rayon` for parallel read-hash-parse. Python
   has a GIL, and multiprocessing overhead eats the gain at the file counts
   where the gain would matter.
3. **Distribution.** Already bitten once: brew install failing on
   `detected_python_shebang`. A single static binary makes that entire class of
   failure structurally impossible and simplifies bottling rather than
   complicating it. **Constraint on any port:** Python runs on Windows today,
   for free, and that is a live differentiator - the closest comparable tool
   still has no Windows build (DECISIONS.md, prior art). A port that ships
   macOS/Linux binaries and quietly drops Windows would trade a real advantage
   for a build-matrix convenience.
4. **#6 (config/data key-path anchors).** Python needs PyYAML, a real runtime
   dependency (`tomllib` is read-only and 3.11+). Rust compiles serde in and
   stays one binary.
5. **#9 (LSP).** `tower-lsp` is mature; a long-lived Python daemon is the
   heaviest of the options. Depends on #8 anyway, so it sequences last
   regardless.

**Rust over Go:** Go is a perfectly good fit on its own terms - fast compiles,
easy contribution, static binaries - but Rust wins the two decisions that
actually matter for *this* roadmap: tree-sitter without cgo, and the ripgrep
crates. Pick Go only if contributor accessibility comes to outrank roadmap fit.

**Not a solution, but a cheap escape hatch:** if *only* distribution is
hurting, `pyapp`/PyOxidizer ships today's Python as a single binary for near-
zero effort. It fixes the shebang/interpreter class of bug and buys nothing on
scale, tree-sitter, or LSP. A stopgap, not the answer.

### Concrete sequencing

1. **Stay in Python and finish the near work.** #2 (link grammars), #4
   (CI-native output) are grammar and formatting changes with zero language
   leverage - Python is the cheapest possible host for them, and they are what
   settles the semantics. Porting before the semantics settle means porting
   twice.
2. **Separately, kill the subprocess wall time.** One git invocation instead of
   two, or walk the tree directly. No rewrite required.
3. **Freeze the wire format before any port.** `normalize()` plus truncated
   sha256 is a *published format*: every stamp in every adopting repo turns
   `DRIFTED` if a reimplementation differs by one byte. Write the
   normalization rules down as a spec with golden fingerprint vectors, and make
   those vectors the port's hardest test.
4. **Port on a trigger, not a date.** Any one of: committing to #5, #6, or #9;
   `check` no longer feeling instant on a real repo *after* step 2; or
   distribution biting again.
5. **Port differentially.** The eval bench is already a language-neutral
   conformance suite - that is exactly the precondition a rewrite wants. Keep
   the CLI surface and the stamp bytes identical, and run both implementations
   against the bench throughout the transition.
