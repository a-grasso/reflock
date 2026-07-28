# BUG-07 acceptance contract: usage errors ignore `--format`/`--json`

Source: AXI adoption review 2026-07-28 ([kunchenguid/axi](https://github.com/kunchenguid/axi) principle 6, "structured errors & exit codes")
Owner: agent · Tier: near · Touches: [reflock_lib/commands.py](../reflock_lib/commands.py), [reflock_lib/cli.py](../reflock_lib/cli.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format), [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

Every usage error (`FormatConflict`, `ScopeError`, an unknown file/anchor in
`backlinks`, an invalid `<file>:<line>` spec or missing reference in
`explain`, `--quiet`/`--verbose` conflicting in `check`) is printed with a
bare `print(..., file=sys.stderr)`, regardless of the format the caller asked
for:

```
$ reflock check --format json badpath/
error: no such path in tree: badpath/          # plain text, on stderr
$ echo $?
2
```

A caller that requested `--format json` (a script, a CI step, an agent
parsing stdout) gets nothing on stdout when a command fails this way - no
JSON object to parse, no indication beyond the exit code of what went wrong.
The command's own contract ("give me JSON") is silently broken exactly when
it would matter most: a failure the caller has to explain to something
downstream. `--format github` has the same gap - a misconfigured invocation
in a workflow produces a bare stderr line instead of a `::error::` annotation
that shows up in the Actions UI.

Human format is correct today and stays that way: `error: ...` on stderr,
untouched.

## Required behavior

One function renders every usage error, in whatever format the command's own
resolved format is - the same "one reporting layer" `RENDERERS`/
`BACKLINKS_RENDERERS`/`EXPLAIN_RENDERERS` already give normal output (D1).

```python
def render_error(message: str, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps({"error": message}))
    elif fmt == "github":
        print(f"::error::{github_escape_message(message)}")
    else:
        print(f"error: {message}", file=sys.stderr)
```

- `message` carries no `error:` prefix and no trailing punctuation baked in;
  `render_error` owns the human-format prefix so the JSON/github shapes don't
  inherit it.
- **json**: stdout gets `{"error": "<message>"}` and nothing else for that
  invocation. Exit code is unchanged (2, as today).
- **github**: stdout gets one `::error::<message>` workflow-command line,
  escaped the same way verdict annotations already are
  (`github_escape_message`).
- **human**: byte-identical to today - `error: <message>` on stderr.
- Every existing error call site in `commands.py` (`cmd_check`,
  `cmd_backlinks`, `cmd_explain`) routes through `render_error` with that
  command's already-resolved `fmt`, rather than a raw `print(..., file=
  sys.stderr)`.
- `ScopeError`, currently caught once in `cli.py:main` after `fmt` has gone
  out of scope, is instead caught inside each command that can raise it
  (`cmd_check`, `cmd_stamp`, `cmd_suspects`) so the catch site knows the
  command's intended format. Add a small helper -
  `intended_format(args) -> str` - that reads `args.format`/`args.json`
  without needing `resolve_format`'s conflict-checking, for commands where a
  `FormatConflict` might itself be why `fmt` was never resolved.
- `intended_format` is used uniformly for the `ScopeError` catch in `cmd_check`,
  `cmd_stamp` and `cmd_suspects` - not hand-picked per command. `stamp` has
  neither `--json` nor `--format`, so `intended_format` falls back to
  `"human"` there with no special-casing, and its errors are unchanged.
  `suspects` already has a `--json` flag (pre-existing, not added by this
  contract); `intended_format` reads it, so a `ScopeError` under
  `suspects --json` now also lands as `{"error": ...}` on stdout - for free,
  since the same helper covers it, not as a new flag. Neither command gains
  `--format` or a `github` shape; that stays out of scope (D1's renderer
  table covers `check`/`backlinks`/`explain` only).

## Explicitly out of scope

- Adding `--format` to `stamp` or `suspects`. Neither has a JSON/github
  renderer to route an error through; that is a separate, larger decision
  (new output surface) this contract does not make.
- Changing any *non-error* output shape. `render_json`, `render_backlinks_json`,
  `render_explain_json`, and the human renderers are untouched.
- A structured error object beyond `{"error": "..."}` (no `code`, no `help`
  field). One key is enough to fix "nothing on stdout"; a richer shape is a
  future decision, not a silent expansion of this one.

## Invariants

- Human-format error text is byte-identical to today for every existing error
  message (same wording, same `error: ` prefix, same stderr stream).
- Exit codes are unchanged: `FormatConflict` and `ScopeError` still exit 2,
  every existing usage error still exits 2.
- No new imports outside the stdlib (D3).
- `check`'s and `backlinks`'/`explain`'s *successful*-path JSON shape is
  byte-identical to today (D1's "unchanged shape" applies to success output;
  this contract only touches the error path, which had no JSON shape before).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `check-format-json-scope-error` | `reflock check --format json nosuchpath/` prints `{"error": "..."}` on stdout, nothing on stderr, exit 2 |
| `check-format-github-scope-error` | same invocation with `--format github` prints one `::error::` line on stdout, exit 2 |
| `backlinks-format-json-unknown-path` | `reflock backlinks nosuch.md --format json` prints `{"error": "..."}` on stdout, exit 2 |
| `explain-format-json-bad-spec` | `reflock explain not-a-spec --format json` prints `{"error": "..."}` on stdout, exit 2 |
| `check-human-scope-error-unchanged` | `reflock check nosuchpath/` (default format) still prints `error: no such path in tree: nosuchpath/` on stderr, nothing on stdout, exit 2 - the regression guard for "human stays human" |

## Unit tests to add

- `render_error` with `fmt="json"` prints valid JSON `{"error": message}` to
  stdout and nothing to stderr.
- `render_error` with `fmt="github"` prints `::error::message` to stdout,
  with `%`/`\r`/`\n` in `message` escaped exactly like existing annotations.
- `render_error` with `fmt="human"` (and with an unrecognized/default fmt)
  prints `error: message` to stderr and nothing to stdout.
- `cmd_check` with `--format json` and a bad path: stdout is valid JSON with
  an `error` key, stderr is empty, return code 2.
- `cmd_check` with `--format github` and a bad path: stdout is one
  `::error::` line, return code 2.
- `cmd_check` with default (human) format and a bad path: unchanged from
  current behavior (stderr text, empty stdout, return 2) - proves no
  regression.
- `cmd_backlinks --format json` with an unknown path and with an unknown
  anchor: both produce `{"error": ...}` on stdout, return 2.
- `cmd_explain --format json` with an invalid spec, an unknown file, a
  line past EOF, and a line with no reference: all four produce
  `{"error": ...}` on stdout, return 2.
- `--quiet`/`--verbose` conflict in `cmd_check` still exits 2 via
  `render_error` (human only - `check` has no format concept for its own
  flag-conflict message beyond the one it's given).
- `stamp --warn` without `--check`: unchanged (stderr, human, exit 2) -
  proves `stamp` was correctly left out of this contract's format routing.
- `suspects --json` with an unmatched path: `{"error": ...}` on stdout,
  stderr empty, exit 2 - proves `intended_format` picks up the pre-existing
  `--json` flag without `suspects` gaining a new one.

## Verification

```
make gate
```

## Definition of done

1. Fixtures and unit tests above pass; every existing test stays green
   unmodified.
2. README documents that `--format json`/`--format github` errors land on
   stdout in the requested shape (wherever it currently documents `--format`).
3. `ROADMAP.yaml` adds BUG-07 as `done`.
