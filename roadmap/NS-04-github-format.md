# NS-04 acceptance contract: `--format github`

Source: [northstar #4](../NORTHSTARS.md#4-ci-native-output-inline-annotations-not-just-a-log-block-near)
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format), [D3](DECIDED.md#d3-zero-runtime-dependencies)
Depends on: FMT-01, ID-13

## Required behavior

A `github` value for `--format`, emitting GitHub Actions workflow commands so a
finding lands as an inline annotation on the exact line of a PR diff:

```
::error file=docs/a.md,line=12,title=DANGLING::no such file: docs/gone.md
::warning file=docs/b.md,line=3,title=DRIFTED::target changed since pinning
```

- Verdict determines level: `DANGLING` and `DRIFTED` are `error`; `UNSTAMPED` is
  `warning`. Do not invent levels beyond those two.
- `title` carries the verdict; the message carries the existing detail string.
  Reuse the detail text `check` already produces - do not write new prose.
- Values must be escaped per GitHub's workflow-command rules. A detail string
  containing `%`, a newline, `:` or `,` must not corrupt the annotation. This is
  the one place this item can silently produce garbage, so it needs its own test.
- Emitted on stdout, one command per line, nothing else. No summary block, no
  colors, no `All references OK.` line. Exit codes unchanged.

Per D1 this is one function added to the renderer from FMT-01. If it requires
touching callers, the layer is wrong - report that rather than working around it.

## Explicitly out of scope

- SARIF. It is the other plausible format and it is a separate decision; do not
  add it speculatively.
- A published GitHub Action. That is idea #20.
- Auto-detecting CI and switching format implicitly. Explicit flag only - an
  implicit switch makes local reproduction of a CI failure harder, which is
  exactly what a debugging developer needs.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- `human` and `json` output byte-identical to before.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `format-github-dangling-is-error` | a `DANGLING` finding emits an `::error` line with correct file and line |
| `format-github-unstamped-is-warning` | an `UNSTAMPED` finding emits `::warning` |
| `format-github-clean-emits-nothing` | clean tree: empty stdout, exit 0 |
| `format-github-escapes-detail` | a target or detail containing `%`, `:` and `,` produces a well-formed annotation |

## Unit tests to add

- Escaping: assert the exact escaped output for a string containing `%`, `\r`,
  `\n`, `:` and `,`, checked against GitHub's documented rules.
- Verdict-to-level mapping for all four verdicts.

## Verification

```
make test && make bench && make check && make suspects
```

Additionally: paste one emitted line into a scratch workflow run, or cite
GitHub's workflow-command documentation for each escape, in the PR body. An
annotation format that is subtly wrong looks fine in tests and produces nothing
in a real PR, so this needs evidence beyond a passing assertion.

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. README's CI section documents `--format github` and shows the workflow snippet
   that uses it. Re-stamp the file.
3. Northstar #4 is **deleted** from [NORTHSTARS.md](../NORTHSTARS.md).
4. `ROADMAP.yaml` marks NS-04 `done`.
