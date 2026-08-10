# AGT-02 acceptance contract: findings carry structure, not just prose

Source: this contract
Owner: agent · Tier: near · Touches: [reflock_lib/engine.py](../../reflock_lib/engine.py), [reflock_lib/commands.py](../../reflock_lib/commands.py)
Locked decisions: [D7](DECIDED.md#d7-the-machine-readable-output-envelope), [D8](DECIDED.md#d8-detail-is-prose-reason-is-vocabulary)
Depends on: AGT-01
Blocks: AGT-03

## The problem

The one field a consumer branches on is a human sentence:

```json
"detail": "pinned @bf607b1d, now @e1fad960"
"detail": "no anchor '#gone' in b.md"
```

An agent deciding whether a DRIFTED reference is worth re-reading wants the two
fingerprints. A repair loop wants to know whether a DANGLING target is a missing
*file* (repoint the link) or a missing *anchor* in a file that exists (fix the
fragment) - a different fix. Today both require a regex over prose that
[`classify`](../../reflock_lib/engine.py) is free to reword at any time,
and which AGT-01's `schema` deliberately does not promise to hold still.

## Required behavior

Every finding gains a `reason` field: a closed, stable vocabulary naming the
branch of `classify` that produced it. Per D8, `detail` stays exactly as it is -
prose for humans - and `reason` is what machines read.

| Verdict | `reason` | Extra fields |
|---|---|---|
| `OK` | `external`, `outside-tree`, `dir`, `unpinned`, `pinned` | — |
| `DANGLING` | `no-such-file`, `no-such-anchor`, `wiki-unresolved`, `wiki-ambiguous` | `candidates: []` on `wiki-ambiguous` |
| `DRIFTED` | `fingerprint-mismatch` | `pinned`, `current` (bare hex, no `@`) |
| `UNSTAMPED` | `empty-pin`, `no-indexed-text` | — |
| `UNSUPPORTED` | `future-fingerprint-version` | `pin_version`, `supported_version` |

- `reason` is derived from **the branch that produced the verdict**, not by
  parsing the detail string. A test must assert that every `return` site in
  `classify` maps to exactly one vocabulary member and that the vocabulary has
  no unreachable members - that is what stops the two drifting apart.
- `pinned` and `current` are the bare hex digests. Callers concatenating `"@"`
  is their business; the field is the value.
- `wiki-ambiguous` already lists candidates in its detail (D4). `candidates` is
  that same list, as an array, in resolution order.
- Fields listed as "extra" appear **only** on the verdicts that define them.
  Do not emit `pinned: null` on a DANGLING finding; absence is the signal.
- Human and github output are unchanged. `github` keeps using `detail` as its
  message (NS-04 requires it) and `title` as the verdict - `reason` does not
  appear there.

`reason` is additive to AGT-01's envelope and therefore does **not** bump
`schema`. That is the asymmetry AGT-01 exists to create; this item is the first
proof it works.

## Explicitly out of scope

- Changing any `detail` wording. If a detail string reads badly, that is a
  separate cosmetic item; changing it here would muddy the evidence that
  `reason` is independent of prose.
- A `fix` or `suggested_command` field. UX-03 already owns next-step hints, and
  [manual.md](../manual.md) is explicit that machine formats never carry
  them. Do not reopen that.
- Structuring the error object beyond AGT-01's `kind`.
- Exposing the resolved absolute path of the target. Plausible and additive;
  wait for someone to need it.

## Invariants

- Existing fixtures and tests stay green, unmodified, except where they assert
  the full JSON object literally - those gain the new key and nothing else.
- `human` and `github` output byte-identical to before.
- `schema` stays `1`.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `finding-reason-drifted` | DRIFTED carries `reason: "fingerprint-mismatch"`, `pinned` and `current` as bare hex matching the detail string |
| `finding-reason-dangling-file` | a deleted target file yields `no-such-file` |
| `finding-reason-dangling-anchor` | an existing file with a missing fragment yields `no-such-anchor`, distinct from the above |
| `finding-reason-wiki-ambiguous` | two same-basename targets: `wiki-ambiguous` plus `candidates` in resolution order |
| `finding-reason-unsupported` | a `2:` pin yields `future-fingerprint-version`, `pin_version: 2`, `supported_version: 1` |
| `finding-reason-absent-fields` | a DANGLING finding has no `pinned`/`current` keys at all |

## Unit tests to add

- Exhaustiveness both ways: every `classify` return site produces a `reason` in
  the table, and every member of the table is produced by some input. A member
  nobody can reach is a lie in the contract.
- `pinned`/`current` equal the digests embedded in the detail string, so the two
  representations cannot drift silently.

## Verification

```
just gate
```

`suspects` is advisory and exits nonzero whenever it has anything to say, so it
is not part of the gate.

## Definition of done

1. Fixtures and tests above pass.
2. The `reason` vocabulary is documented in [docs/manual.md](../manual.md)
   beside the verdict table, marked as contract per AGT-03. Re-stamp the file.
3. `ROADMAP.yaml` marks AGT-02 `done`.
