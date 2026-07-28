# BENCH-01 acceptance contract: evalbench stream and byte-identity primitives

Source: agent-reported during grind iterations 3, 5, 7, 8; specified after the branch review of 2026-07-28
Owner: agent · Tier: near · Touches: [run_bench.py](../evalbench/run_bench.py), [README.md](../evalbench/README.md), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## Why this is first

Four shipped items (FMT-01, NS-03, ID-13, NS-04) satisfied their contracts
*approximately* because the harness could not express what the contract asked
for. Until that is fixed, every later fixture in this queue inherits the same
weakness, and three of the queued review fixes assert exactly the things the
harness cannot currently check: that a message went to stderr rather than
stdout, and that a command left the tree byte-identical.

## Required behavior

### 1. Unknown step keys are an error

`check_step` currently reads its assertions with `.get()`, so a key it does not
recognise is silently ignored. A fixture asserting `expect_containss` (one typo)
reports `PASS` while asserting nothing:

```
step = {"cmd": "check", "expect_containss": ["NEVER MATCHES"]}
check_step(tmp, step)  ->  []      # no failures reported
```

Every scenario key must be validated against a known set, and an unrecognised
key must fail the fixture with a message naming it. This comes first because
without it the primitives below can be typo'd into silence, and because it is
the reason a weak assertion can masquerade as a passing one today.

### 2. Stream assertions

| Key | Asserts |
|---|---|
| `expect_stderr` | list of substrings that must appear in stderr |
| `expect_stderr_not_contains` | list of substrings that must not appear in stderr |
| `expect_stderr_empty` | `true`: stderr must be exactly empty |
| `expect_stdout_empty` | `true`: stdout must be exactly empty |

`expect_contains` / `expect_not_contains` keep their current stdout-only
meaning. A contract that says "on stderr" must be expressible as *both* present
on stderr and absent from stdout.

`expect_stdout_empty` is the stdout half of the same pair. "Prints nothing on
success" is a statement about the whole stream, and the two `-q` fixtures
currently approximate it with `expect_not_contains` lists of words that happen
not to appear - which passes just as well if the command prints something else
entirely.

### 3. Cross-step byte identity

| Key | Asserts |
|---|---|
| `expect_stdout_same_as_step` | integer step index; this step's stdout is byte-identical to that step's |
| `expect_tree_unchanged_since_step` | integer step index; every file in the tree is byte-identical to its content after that step, and no file was added or removed |

Step indices are 0-based and refer to steps within the same scenario, matching
the numbering `run_bench.py` already uses in its failure messages. Referring to
a step at or after the current one is a fixture error, not a silent pass.

`expect_tree_unchanged_since_step` compares content, not mtime: mtime is not a
promise reflock makes, and asserting it would make the suite flaky on
coarse-grained filesystems. Content identity is the assertion NS-03's contract
actually wanted.

## Explicitly out of scope

- Any change to reflock's behavior. This item touches the harness only.
- New fixture *scenarios*. Existing fixtures get stronger assertions; the
  behaviors they cover do not change.
- A diffing/reporting redesign. Failure messages stay plain strings.

## Invariants

- All 89 existing fixtures stay green. Fixtures may only be *strengthened*
  (see below); no expected value may be relaxed or deleted.
- Existing unit tests stay green, unmodified.
- No new imports outside the stdlib (D3).
- The harness stays a single file with no fixture-side plugin mechanism.

## Authorized fixture edits

This item is the one exception to "do not modify existing fixtures", because
replacing an approximation with the assertion it approximated *is* the item.
Tighten exactly these four, and state in the commit what each one now asserts
that it did not before:

| Fixture | Approximation to replace |
|---|---|
| `format-human-matches-default` | matching `expect_contains` snippets -> `expect_stdout_same_as_step` |
| `stamp-check-writes-nothing` | pin-marker regexes -> `expect_tree_unchanged_since_step` |
| `quiet-clean-is-silent` | stdout-only emptiness -> `expect_stderr_empty` |
| `quiet-failure-one-line-stderr` | "stdout does not contain it" -> `expect_stderr` plus `expect_not_contains` |

## Unit tests to add

Against `check_step` / the harness directly, in a `BenchHarnessTest` class:

- An unknown step key fails, and the failure message names the key.
- Every key this contract documents is accepted (guards against a validation
  set that drifts from the documented one).
- `expect_stderr` passes on a match and fails on a miss.
- `expect_stderr_empty` fails when the command wrote to stderr.
- `expect_stdout_same_as_step` passes for two identical invocations and fails
  for two that differ.
- `expect_tree_unchanged_since_step` passes after a read-only command and fails
  after one that rewrote a file.
- A forward or self step reference fails as a fixture error.

## Verification

```
make gate
```

## Definition of done

1. Unit tests above pass; the four named fixtures are tightened and green; the
   other 85 are green unmodified.
2. `evalbench/README.md`'s "Anatomy of a fixture" documents every new key.
3. `ROADMAP.yaml` marks BENCH-01 `done`.
