# AGT-05 acceptance contract: `stamp --check --format json`

Source: this contract
Owner: agent · Tier: near · Touches: [reflock_lib/cli.py](../../reflock_lib/cli.py), [reflock_lib/commands.py](../../reflock_lib/commands.py)
Locked decisions: [D1](DECIDED.md#d1-one-reporting-layer-selected-by---format),
[D5](DECIDED.md#d5-stamp---check-follows-the---check-convention), [D7](DECIDED.md#d7-the-machine-readable-output-envelope)
Depends on: AGT-01

## The problem

The repair loop reflock ships - [`examples/skill/refcheck`](../../examples/skill/refcheck/SKILL.md) -
is: `check` (machine-readable), adjudicate each DRIFTED (judgment), then
`stamp --rebless --reviewed` (which prints `Stamped 1 pin(s).` and nothing
structured). The loop reads JSON at the start and prose at the end.

`stamp --check` already answers the right question - what would change, without
writing - and [manual.md](../manual.md) records that its exit code is what
CI reads. What it cannot do is tell a caller *which* pins, in a form the caller
can act on, which is what closes the loop: an agent that just re-blessed one
referrer wants to confirm exactly that pin moved and no other, without re-running
`check` and diffing two human reports.

## Required behavior

`stamp` accepts `--format <human|json>`, defaulting to `human`. Per D1 it goes
through the same renderer as `check`; per D7 it emits the same envelope.

```json
{
  "schema": 1,
  "reflock": "0.4.0",
  "command": "stamp",
  "root": "/abs/path",
  "findings": [ { "file": "a.md", "line": 1, "target": "b.md#head",
                  "action": "rebless", "pinned": "bf607b1d", "current": "e1fad960" } ],
  "summary": { "stamp": 0, "rebless": 1 },
  "problems": 1,
  "written": false
}
```

- `action` is a closed vocabulary: `stamp` (an empty `@` gaining its first
  digest) and `rebless` (an existing digest being replaced). These are already
  distinct concepts - `--rebless` and `--reviewed` exist precisely because the
  second is the dangerous one - so the output must not blur them.
- `pinned` is absent on `action: "stamp"`; there is no prior digest. Absence is
  the signal, per AGT-02.
- `written` distinguishes a real run from `--check`. Without it a caller cannot
  tell "these pins changed" from "these pins would change", which is the entire
  difference between the two invocations.
- `findings` is the array of pins acted on (or that would be), empty on a no-op.
  Reusing the key rather than inventing `pins` keeps one envelope shape; the
  entries are stamp-shaped, not check-shaped, and that is fine.
- Exit codes follow D5 and are unchanged by this item: `--check` exits nonzero
  iff it would write; a real `stamp` exits 0 on success. `problems` mirrors the
  `--check` exit code the same way AGT-01 requires for `check`.
- `--warn` still forces exit 0 (NS-03b) and must not alter the JSON body. The
  code softens; the report does not lie about what it found.
- Errors use AGT-01's envelope and `error.kind`. This closes the exception
  [manual.md](../manual.md) currently documents - that `stamp` has no
  `--format` and so always errors in the plain stderr form. Update that
  sentence; it becomes wrong the moment this ships.

## Explicitly out of scope

- `--format github` for `stamp`. Stamping is not a PR-annotation surface, and
  NS-04 deliberately scoped the levels to findings.
- A dry-run diff of the file bytes. `--check` reports pins, not patches.
- Relaxing `--reviewed` (NS-10) in any way for machine callers. The friction is
  the feature; a JSON caller is exactly who would be tempted to bypass it and
  exactly who must not.
- `suspects --format`. It has `--json` already (D1 records it as the exception)
  and its output is advisory, explicitly outside the stability contract (AGT-03).

## Invariants

- `stamp`'s human output byte-identical to before.
- Exit codes unchanged on every path, `--check` and `--warn` included.
- `schema` stays `1` - this is an additive `command` value.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `stamp-check-json-noop` | nothing to do: `findings: []`, `problems: 0`, `written: false`, exit 0 |
| `stamp-check-json-would-stamp` | an empty `@`: one finding with `action: "stamp"`, no `pinned` key, exit 1, file on disk unchanged |
| `stamp-check-json-would-rebless` | a drifted pin under `--rebless --check`: `action: "rebless"` with both digests, exit 1 |
| `stamp-json-written` | a real `stamp`: `written: true`, exit 0, and the file's pin equals the reported `current` |
| `stamp-check-json-warn` | `--check --warn`: identical JSON body to `stamp-check-json-would-stamp`, exit 0 |
| `stamp-json-error` | a scope error under `--format json`: envelope on stdout, `error.kind`, exit 2, stderr empty |

## Unit tests to add

- `written` is `false` for every `--check` invocation and `true` for every
  writing one, with no third state.
- `summary` keys are exactly the two actions, zeros included.
- The reported `current` for a `stamp` action equals the digest actually written
  to the file - the one way this command can report a plausible lie.

## Verification

```
just gate
```

Additionally: run the [refcheck skill](../../examples/skill/refcheck/SKILL.md)
loop end to end against a fixture with one DRIFTED reference, using JSON at both
ends, and paste the transcript in the PR body. The item exists to close that
loop; a green test suite does not show that it closed.

## Definition of done

1. Fixtures and tests above pass; `stamp`'s human output unchanged.
2. [manual.md](../manual.md) documents `stamp --format` and the sentence
   claiming `stamp` has no `--format` is corrected. Re-stamp.
3. The refcheck skill uses the JSON path where it helps, or a note records why
   it stays on prose.
4. `ROADMAP.yaml` marks AGT-05 `done`.
