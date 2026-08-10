# AGT-01 acceptance contract: a versioned envelope for machine-readable output

Source: this contract (the agent-facing surface has no source entry in
NORTHSTARS.md; it was assumed shipped)
Owner: agent · Tier: near · Touches: [reflock_lib/commands.py](../../reflock_lib/commands.py)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format),
[D7](DECIDED.md#d7-the-machine-readable-output-envelope), [D3](DECIDED.md#d3-zero-runtime-dependencies)
Depends on: —
Blocks: AGT-02, AGT-03, AGT-05

## The problem

`check --format json` emits a bare array:

```json
[ { "verdict": "DRIFTED", "file": "a.md", "line": 1, "target": "b.md#head",
    "detail": "pinned @bf607b1d, now @e1fad960" } ]
```

Three consequences, all of which get worse the longer they ship:

1. **No version.** The *stamp wire format* is versioned (`FP_VERSION`, and the
   `UNSUPPORTED` verdict exists to say so out loud), but the *output* format is
   not. A consumer cannot tell v0.4 output from v0.9 output, and reflock cannot
   add a top-level field without a guess-and-check parse on the far side.
2. **Errors are a different top-level type.** Success is `[...]`; a scope error
   is `{"error": "..."}` ([commands.py:226](../../reflock_lib/commands.py)).
   Every consumer must type-switch array-vs-object, and the natural naive parse
   (`for f in json.load(fh)`) iterates the string `"error"` character by
   character rather than failing.
3. **No summary.** A hook that wants "how many DRIFTED" recounts the array, and
   an empty array is ambiguous between "clean" and "nothing was in scope".

This is the one item that must land before the surface is announced, because
fixing it afterwards is a breaking change to somebody's script.

## Required behavior

Every JSON emitter produces the envelope defined in [D7](DECIDED.md#d7-the-machine-readable-output-envelope).
For `check`:

```json
{
  "schema": 1,
  "reflock": "0.4.0",
  "command": "check",
  "root": "/abs/path/to/repo",
  "findings": [ { "verdict": "DRIFTED", "file": "a.md", "line": 1,
                  "target": "b.md#head", "detail": "pinned @bf607b1d, now @e1fad960" } ],
  "summary": { "OK": 3, "DANGLING": 1, "DRIFTED": 1, "UNSTAMPED": 0, "UNSUPPORTED": 0 },
  "problems": 2
}
```

- `findings` is **always an array**, on every exit path including errors. This
  is the property that makes the naive parse safe, and it is the point of the
  item; do not omit the key on the error path.
- An error emits the same envelope with `findings: []` and an `error` object:
  `{"error": {"kind": "scope", "message": "no such path in tree: docs/"}}`.
  `kind` is a closed vocabulary - `scope` (a path argument naming nothing) and
  `usage` (a rejected flag combination) are the two that exist today. Adding a
  third later is additive and does not bump `schema`.
- `summary` carries a key for **all five verdicts**, zeros included. A consumer
  branching on `summary["DRIFTED"] > 0` must not need a `.get` with a default.
- `problems` is the count that drives the exit code, so `problems > 0` and
  `exit 1` can never disagree. Assert that relationship in a test rather than
  computing it twice.
- `-q` still suppresses the human summary line but leaves the envelope intact
  on stdout - `-q --format json` is "quiet for humans", not "less JSON". This
  is today's behavior for the array and must survive.

Applies to `check`, `explain`, `backlinks`, and `suspects --json`. Per D1 this
is one change in the renderer; `command` distinguishes them. `explain` and
`backlinks` carry their payload under `findings` if it is finding-shaped, or a
command-specific key beside it if it is not - do not force an unnatural shape
onto them just to reuse the word.

Exit codes are **unchanged** (0/1/2). `--format human` and `--format github`
output stays byte-identical.

## Explicitly out of scope

- Changing any existing finding *field* (`verdict`, `file`, `line`, `target`,
  `detail`). Structuring `detail` is AGT-02 and lands as its own commit.
- A published JSON Schema file. Documenting the shape is AGT-03; shipping a
  `.schema.json` artifact is a separate decision about what reflock distributes.
- SARIF. Still the other plausible format, still a separate decision.
- A `--schema-version` flag or any negotiation mechanism. `schema` is emitted,
  not requested; a consumer that cannot handle version N fails loudly on its
  own side, exactly as `UNSUPPORTED` does for pins.

## Invariants

- `human` and `github` output byte-identical to before.
- Exit codes unchanged on every path.
- No new imports outside the stdlib (D3).
- `--json` remains an alias for `--format json` (D1).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `json-envelope-clean` | clean tree: `findings: []`, all-zero `summary`, `problems: 0`, exit 0 |
| `json-envelope-findings` | DRIFTED + DANGLING: `problems: 2`, `summary` counts match, exit 1 |
| `json-envelope-scope-error` | `check nosuchdir` in JSON: envelope with `findings: []`, `error.kind == "scope"`, exit 2, stderr empty |
| `json-envelope-quiet` | `-q --format json`: full envelope on stdout, human summary absent |
| `json-envelope-suspects` | `suspects --json` carries the same envelope with `command: "suspects"` |

Fixtures asserting a stream is empty must use `expect_stdout_empty` /
`expect_stderr_empty`, not a word list (see [evalbench/AGENTS.md](../../evalbench/AGENTS.md)).

## Unit tests to add

- The envelope parses as an object and `findings` is a `list` on all three exit
  paths (clean, problems, error). This is the regression that matters.
- `summary` has exactly the five verdict keys, no more, no fewer.
- `problems == len([f for f in findings if f.verdict != "OK"])` and matches the
  exit code.
- `reflock` field equals `__version__`.

## Verification

```
just gate
```

`suspects` is advisory and exits nonzero whenever it has anything to say, so it
is not part of the gate. Read its output, act on anything real, but do not
chain it.

Additionally, in the PR body: the before/after JSON for one DRIFTED finding,
and a one-line note that this is a **breaking change** to `--format json`, for
the release notes to pick up.

## Definition of done

1. Fixtures and tests above pass; existing `human`/`github` fixtures unmodified.
2. [docs/manual.md](../manual.md) shows the envelope in the output-format
   section. Re-stamp the file.
3. The breaking change is called out wherever release notes are drafted.
4. `ROADMAP.yaml` marks AGT-01 `done`.
