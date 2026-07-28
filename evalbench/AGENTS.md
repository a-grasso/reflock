---
kind: module
title: evalbench
up: ../AGENTS.md
docs: ./docs
updated: 2026-07-28
---

# evalbench

## Purpose
Black-box behavioral regression suite: runs `reflock` as a subprocess against real,
disposable git fixtures and asserts on its output. Complements `test_reflock.py`'s unit
tests by exercising git-specific behavior (`.gitignore`, untracked files, `git ls-files`
scoping) that a unit test against a plain directory can't reach.

## Working here
- **Run:** from repo root, `make bench` (`python3 evalbench/run_bench.py`).
- **Run a subset:** `python3 evalbench/run_bench.py <fixture-name> ...`
- **Verbose (show diffs on failure):** `python3 evalbench/run_bench.py -v`
- **Entry points:** `run_bench.py` (harness); `fixtures/<name>/scenario.json` (per-fixture
  expected command + output).

## Map
- `run_bench.py` — builds each fixture as a real git repo in a temp dir, runs the
  scenario's reflock command(s), diffs actual vs. expected output.
- `fixtures/<name>/repo/` — the fixture's source tree, plus `scenario.json` describing
  the command(s) to run and the expected output.

## Navigation (for agents)
- Follow **`up:`** for project-wide conventions and the full module map.
- See this module's `README.md` for fixture anatomy in more detail.

## Constraints
- Fixture assertions are stdout-only; a scenario that fails by writing to stderr instead
  would pass silently — keep this in mind when adding fixtures for new failure modes.
</content>
