---
kind: project-index
title: reflock
topology: monorepo
ref:
  - { at: reflock_lib/AGENTS.md, hint: core engine, grammar, CLI, and output renderers }
  - { at: evalbench/AGENTS.md, hint: black-box eval harness running reflock as a subprocess }
docs: ./docs
updated: 2026-08-09
---

# reflock

## Purpose
A lockfile for cross-references: detects when a doc's pinned reference target
has moved, been deleted, or drifted in content since it was last blessed.
Distributes as a single dependency-free Python file (stdlib only).

## Working here
- **Check:** `just check` (`python3 reflock.py check`)
- **Stamp:** `just stamp` (`python3 reflock.py stamp`)
- **Test:** `just test` (`python3 -m unittest -v test_reflock`)
- **Bench:** `just bench` (`python3 evalbench/run_bench.py`)
- **Gate (all of the above except suspects):** `just gate`
- **Release:** `just release X.Y.Z` - bumps `__version__` and the pre-commit `rev:` pin
  in `README.md` and `docs/*.md`, gates, commits, tags, and pushes. `.github/workflows/release.yml` takes it
  from there: GitHub release + Homebrew tap formula (see its header comment).
- **Conventions:** stdlib-only Python; no runtime dependencies. `install.sh` symlinks
  `reflock.py` onto PATH, so the single-file entry point must keep working from any
  checkout location (see `reflock_lib/AGENTS.md` for the symlink-resolution constraint
  this places on the package).

## Map
- `ref:` above is the authoritative module list.
- `reflock.py` — thin wrapper/entry point re-exporting `reflock_lib` for the single-file
  distribution story.
- `test_reflock.py` — unit tests against `reflock_lib` (root-level so `just test` stays a
  one-liner; not a module of its own).
- `docs/manual.md` — the user-facing reference: every command, flag, exit code and gate.
  `README.md` is the landing page and links into it; keep the two from drifting.
- `docs/roadmap/` — per-feature specs and bug writeups (`BUG-*`, `ID-*`, `NS-*`, `PUB-*`,
  ...) plus `DECIDED.md`. Working documents feeding `DECISIONS.md`/`NORTHSTARS.md`, not a
  code module. Historical records: they quote the state of the world when written (DOC-01
  quotes an old `rev:` deliberately), so release automation must never rewrite them.
- `docs/ROADMAP.yaml`, `docs/IDEAS.md` — the prioritized backlog and the wider brainstorm.
- `examples/` — hook and skill snippets for consumers integrating reflock (pre-commit,
  Claude Code skill).
- `docs/adr/` — architecture decisions.
- `DECISIONS.md`, `NORTHSTARS.md` — standing design rationale and named gaps. They predate
  `docs/adr/` and remain authoritative; both are linked from the README, which is why they
  stay at the root rather than moving under `docs/`.
- `CONTRIBUTING.md`, `SECURITY.md`, `.github/` — the public-repo surface: CI, release
  automation, issue and PR templates, funding.

## Navigation (for agents)
- Follow **`ref:`** to enter a module. Read that module's `AGENTS.md` before editing it.
- This node has no `up:` — it is the root. Traversing `up:` from any module lands here.
- Read `docs/adr/` before making architectural changes; read `DECISIONS.md` and
  `NORTHSTARS.md` for standing design rationale that predates this doc.

## Constraints
- No runtime dependencies — stdlib only. See ADR-0001 and `DECISIONS.md`.
- Single-file distribution: `reflock.py` must remain runnable via a plain symlink from
  any checkout (see `install.sh`, `reflock_lib/engine.py:repo_root`/symlink resolution).
- `reflock suspects` is deliberately excluded from `just gate` — it's an advisory
  heuristic that exits nonzero almost always; see `Justfile` comment.
</content>
