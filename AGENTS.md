---
kind: project-index
title: reflock
topology: monorepo
ref:
  - { at: reflock_lib/AGENTS.md, hint: core engine, grammar, CLI, and output renderers }
  - { at: evalbench/AGENTS.md, hint: black-box eval harness running reflock as a subprocess }
docs: ./docs
updated: 2026-07-28
---

# reflock

## Purpose
A lockfile for cross-references: detects when a doc's pinned reference target
has moved, been deleted, or drifted in content since it was last blessed.
Distributes as a single dependency-free Python file (stdlib only).

## Working here
- **Check:** `make check` (`python3 reflock.py check`)
- **Stamp:** `make stamp` (`python3 reflock.py stamp`)
- **Test:** `make test` (`python3 -m unittest -v test_reflock`)
- **Bench:** `make bench` (`python3 evalbench/run_bench.py`)
- **Gate (all of the above except suspects):** `make gate`
- **Release:** bump `__version__` in `reflock_lib/__init__.py` and the README
  pre-commit `rev:` pin to match (a test enforces they agree), commit, then
  `git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`. `.github/workflows/release.yml`
  takes it from there: GitHub release + Homebrew tap formula (see its header comment).
- **Conventions:** stdlib-only Python; no runtime dependencies. `install.sh` symlinks
  `reflock.py` onto PATH, so the single-file entry point must keep working from any
  checkout location (see `reflock_lib/AGENTS.md` for the symlink-resolution constraint
  this places on the package).

## Map
- `ref:` above is the authoritative module list.
- `reflock.py` — thin wrapper/entry point re-exporting `reflock_lib` for the single-file
  distribution story.
- `test_reflock.py` — unit tests against `reflock_lib` (root-level so `make test` stays a
  one-liner; not a module of its own).
- `roadmap/` — per-feature specs and bug writeups (`BUG-*`, `ID-*`, `NS-*`, ...) plus
  `DECIDED.md`. Working documents feeding `DECISIONS.md`/`NORTHSTARS.md`, not a code module.
- `examples/` — hook and skill snippets for consumers integrating reflock (pre-commit,
  Claude Code skill).
- `docs/adr/` — architecture decisions.
- `docs/decisions/` — smaller decision log (see also root `DECISIONS.md` and
  `NORTHSTARS.md`, which predate this doc structure and remain authoritative for design
  rationale).

## Navigation (for agents)
- Follow **`ref:`** to enter a module. Read that module's `AGENTS.md` before editing it.
- This node has no `up:` — it is the root. Traversing `up:` from any module lands here.
- Read `docs/adr/` before making architectural changes; read `DECISIONS.md` and
  `NORTHSTARS.md` for standing design rationale that predates this doc.

## Constraints
- No runtime dependencies — stdlib only. See ADR-0001 and `DECISIONS.md`.
- Single-file distribution: `reflock.py` must remain runnable via a plain symlink from
  any checkout (see `install.sh`, `reflock_lib/engine.py:repo_root`/symlink resolution).
- `reflock suspects` is deliberately excluded from `make gate` — it's an advisory
  heuristic that exits nonzero almost always; see `Makefile` comment.
</content>
