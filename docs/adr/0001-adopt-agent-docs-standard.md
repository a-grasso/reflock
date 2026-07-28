---
id: ADR-0001
title: Adopt the Agent Docs Standard
status: accepted
date: 2026-07-28
supersedes: -
superseded-by: -
---

# ADR-0001: Adopt the Agent Docs Standard

## Context
reflock had no `AGENTS.md`/`CLAUDE.md` context files. Design rationale already lived in
`DECISIONS.md`, `NORTHSTARS.md`, and `roadmap/`, but nothing told an agent where to start,
what commands to run, or how the repo's pieces (`reflock_lib`, `evalbench`, `roadmap`,
`examples`) relate. The repo is a single git checkout with no workspace tooling
(no `pyproject.toml`/`package.json` per directory), but `reflock_lib` (the implementation)
and `evalbench` (a black-box eval harness with its own README and entry point) are real,
separately-runnable units worth documenting on their own.

## Decision
Adopt the Agent Docs Standard with `topology: monorepo` (single `.git`, modules as
subdirs). Root `AGENTS.md` is the `project-index`; `reflock_lib/` and `evalbench/` are
`module` nodes. `roadmap/`, `examples/`, and root-level `test_reflock.py` stay documented
in the root's `## Map` rather than becoming modules of their own — they are docs/config/
a single test file, not independently-runnable code units.

## Consequences
- **Positive:** an agent entering the repo cold has one file (`AGENTS.md`) that names the
  build/test/bench commands, points at the two real modules, and states the
  no-runtime-dependencies / single-file-distribution constraints that already governed
  the codebase informally.
- **Negative / cost:** one more file to keep in sync when `Makefile` targets or module
  boundaries change.
- **Follow-ups:** none required immediately; `docs/decisions/` is scaffolded empty and can
  take future lightweight decisions instead of growing `DECISIONS.md` further.

## Alternatives considered
- **Single root node only, no modules** — simpler, but `reflock_lib` and `evalbench` each
  have distinct entry points and commands; folding them into one file's `## Map` would
  either duplicate that detail or lose it.
- **Leave `DECISIONS.md`/`NORTHSTARS.md` as the only context files** — they capture *why*
  well but don't give an agent a *where do I start* entry point or a machine-checkable
  pointer graph.
</content>
