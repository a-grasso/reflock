# ID-21 acceptance contract: `.pre-commit-hooks.yaml`

Source: idea #21 in [IDEAS.md](../IDEAS.md)
Owner: agent · Tier: near · Touches: `.pre-commit-hooks.yaml` (new), [README.md](../README.md)
Locked decisions: [D6](DECIDED.md#d6-the-shipped-pre-commit-manifest-is-advisory), [D3](DECIDED.md#d3-zero-runtime-dependencies)
Depends on: NS-03 (the advisory hook needs `stamp --check`)

## Required behavior

Ship the manifest that lets reflock slot into the `pre-commit` framework's
`repos:` list, instead of asking every adopter to hand-roll a
`.git/hooks/pre-commit` script as the README currently documents.

Two hook ids:

- `reflock-check` - runs `check`. Fails the commit on a broken reference.
- `reflock-stamp-check` - runs `stamp --check`. **Advisory**, per D6.

Per D6 and section 3 of [DECISIONS.md](../DECISIONS.md), the manifest must not
present a configuration that hard-fails a commit on partial work by default. A
pre-commit gate fires mid-change: a reference added in this commit whose target
lands in the next is correctly `DANGLING` and will block a commit a human
considers reasonable. The README's guidance alongside this manifest must say so
and point at pre-push for enforcement.

Manifest specifics:

- `language: script`, `entry: reflock.py`, no additional dependencies (D3).

  Amended after an agent raised this as `needs-decision`. The original text said
  `language: python` / `entry: reflock`, which cannot work: pre-commit's
  `language: python` installs the hook repo as a package (`pip install .` into a
  venv) to obtain a `reflock` console script, and reflock ships no
  `pyproject.toml` or entry_points anywhere - D3 makes it a single stdlib file
  that `install.sh` symlinks. `language: script` runs the executable directly, so
  no packaging is needed and adopters need nothing on `PATH`.
- `stages: [pre-push]` on both hooks. pre-commit has no warn-only mode - a
  failing hook blocks whatever stage it runs in - so defaulting to pre-push is
  the only way to satisfy D6's "do not ship a hook that hard-fails a commit by
  default" while still shipping a hook that enforces. The README documents the
  `stages: [pre-commit]` override.
- `files:` restricted to text types reflock actually parses, so the hook does not
  fire on every binary asset.
- `pass_filenames` - decide deliberately and state why in the PR. reflock's
  `check` accepts paths, but a per-file invocation cannot see cross-file targets,
  which would produce false `DANGLING` findings. That points strongly at
  `pass_filenames: false` and a whole-tree run; if you conclude otherwise, the
  reasoning must be in the PR body.

## Explicitly out of scope

- A published GitHub Action (idea #20).
- Changing reflock's own `.git/hooks` setup or the Stop hook in
  [examples/](../examples/).
- Any hard-failing default (D6).

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- No change to reflock.py behavior. This item is a manifest plus documentation;
  if it turns out to need a code change, that is a finding to report.
- No new dependencies (D3).

## Tests to add

- The manifest parses as YAML and every hook entry has the keys the pre-commit
  framework requires (`id`, `name`, `entry`, `language`).
- Each declared `entry` invokes a subcommand that actually exists in the parser -
  a manifest referencing a renamed subcommand is the failure mode here, and it is
  silent.

Stdlib only, so parse the YAML with a minimal check rather than importing a YAML
library (D3). If that proves impractical, report it rather than adding the
dependency.

## Verification

```
make gate
```

`suspects` is advisory and exits nonzero whenever it has
anything to say, so it is not part of the gate. Read its output, act on
anything real, but do not chain it.

Plus an actual `pre-commit try-repo .` run against this repo, with output in the
PR body. A manifest that parses but does not run is the whole risk of this item,
and no unit test catches it.

## Definition of done

1. Tests above pass; nothing existing was modified.
2. `.pre-commit-hooks.yaml` exists at the repo root.
3. README's hook-installation section documents the `repos:` snippet, marks
   `reflock-stamp-check` as advisory, and states the partial-work caveat with a
   pointer to pre-push. Re-stamp the file.
4. Idea #21 is **deleted** from [IDEAS.md](../IDEAS.md).
5. `ROADMAP.yaml` marks ID-21 `done`.
