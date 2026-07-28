---
kind: module
title: reflock_lib
up: ../AGENTS.md
dep:
  - { id: gh-actions-workflow-commands, at: "https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions", kind: external-doc, hint: "annotation syntax consumed by the github output renderer" }
docs: ./docs
updated: 2026-07-28
---

# reflock_lib

## Purpose
The actual implementation: reference grammar, resolution engine, subcommands, output
renderers, and CLI parsing. `reflock.py` at the repo root is a thin wrapper around this
package.

## Working here
- **Test:** from repo root, `just test` (`python3 -m unittest -v test_reflock`).
- **Entry points:** `grammar.py` (reference patterns + data model) → `engine.py`
  (resolution/fingerprinting) → `commands.py` (subcommands + renderers) → `cli.py`
  (argument parsing, completions, main entry).
- **Conventions:** stdlib only, no runtime dependencies; keep `reflock.py` importable via
  a plain symlink (path resolution goes through the real script directory, not the
  symlink location).

## Map
- `grammar.py` — reference patterns (markdown links, reference-style links, wiki-links,
  code `REF:` comments) and the `Ref`/`Index` data model.
- `engine.py` — resolution, fingerprinting, path/scope classification.
- `commands.py` — subcommand implementations (`check`, `stamp`, `suspects`, `explain`,
  `backlinks`) and output renderers (human, JSON, GitHub annotations).
- `cli.py` — argument parsing, shell completion generation, main entry point.

## Navigation (for agents)
- Follow **`up:`** for project-wide conventions, `make` targets, and the full module map.
- Follow **`dep:`** for the GitHub Actions annotation syntax the `github` renderer targets.

## Constraints
- No new runtime dependencies — stdlib only (project-wide constraint, see root
  `AGENTS.md` and `DECISIONS.md`).
- Tests patch `reflock` module functions via `mock.patch.object`; moving a function
  across these files requires updating the corresponding patch sites in `test_reflock.py`.
</content>
