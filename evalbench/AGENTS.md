---
kind: module
title: evalbench
up: ../AGENTS.md
docs: ./docs
updated: 2026-08-09
---

# evalbench

## Purpose
Black-box behavioral regression suite: runs `reflock` as a subprocess against real,
disposable git fixtures and asserts on its output. Complements `test_reflock.py`'s unit
tests by exercising git-specific behavior (`.gitignore`, untracked files, `git ls-files`
scoping) that a unit test against a plain directory can't reach.

## Working here
- **Run:** from repo root, `just bench` (`python3 evalbench/run_bench.py`).
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
- Both streams are assertable (`expect_contains` etc. for stdout, `expect_stderr*` for
  stderr), but a step asserting only one stream says nothing about the other. A contract
  of the form "this goes to stderr" needs both halves: present on stderr *and* absent
  from stdout. Prefer `expect_stdout_empty` / `expect_stderr_empty` over a list of
  words that happen not to appear - an empty-stream claim is about the whole stream.
- Every invocation runs with `--root <tmp>` *and* `cwd=<tmp>`, so no fixture exercises a
  root that differs from the working directory.
</content>
