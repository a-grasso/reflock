# Grind iteration prompt

The objective handed to each autonomous iteration. One iteration produces one
commit, and one commit is one roadmap item.

Pass it as the objective, not as a file the agent must find:

```
gnhf --current-branch --push \
     --max-iterations 12 \
     --max-tokens <calibrate: see below> \
     --stop-when "no eligible item remains in ROADMAP.yaml" \
     "$(cat roadmap/GRIND-PROMPT.md)"
```

Calibrate `--max-tokens` rather than guessing: gnhf counts
`cache_read_input_tokens` inside its input total, so a single iteration on this
repo reports far more than intuition suggests. Run once with
`--max-iterations 1`, read the token total from the exit summary, then multiply
by the remaining item count plus roughly 40% for failed iterations.

---

## Objective

Read `ROADMAP.yaml`. Select the **first** item, in file order, whose `status` is
`ready` and every one of whose `blocked_by` ids has `status: done`.

If no such item exists, change nothing and report that no eligible item remains.
Do not invent work. Do not pick a `needs-spec`, `blocked`, `needs-decision` or
`human`-owned item under any circumstance.

Do exactly that **one** item. Never begin a second item in this iteration, even
if the first turns out to be trivial.

### Read the contract

Open the item's `contract` file. It is the definition of done. Also read
`roadmap/DECIDED.md` - it holds cross-cutting decisions you may not overturn.

You may not widen the contract, and you may not resolve an ambiguity by choosing
for yourself. If something is underspecified, or if satisfying it would require
contradicting `DECIDED.md` or `DECISIONS.md`:

1. Revert your code changes.
2. Set that item's `status` to `needs-decision` in `ROADMAP.yaml` and add a
   `note` stating the precise question a human needs to answer.
3. Commit only that change and stop.

That outcome is a success, not a failure. A cheap commit carrying a good question
is worth far more than a confident guess.

### Test-driven, not test-after

Mandatory, in this order:

1. Write the unit tests and evalbench fixtures the contract lists.
2. Run them. Confirm they **fail**, and that each fails for the intended reason -
   the behavior being missing, not a typo or an import error.
3. Only then write implementation.

Tests written after the code pass immediately and prove nothing. If you find you
have written implementation first, delete it and start from the tests.

### Do not modify existing tests or fixtures

Every contract states that existing unit tests and evalbench fixtures stay green
**unmodified**. Changing an existing expectation to make your work pass is a
contract violation, not a fix. If an existing expectation genuinely looks wrong,
that is a `needs-decision`.

### Before reporting success

```
make gate
```

All of it must pass. `make gate` is `test`, `bench` and `check`. `suspects` is
advisory and exits nonzero whenever it has anything to say - read its output and
act on anything real, but do not treat it as a gate.

A pre-commit hook also runs `make gate`, so a red tree cannot be committed. If
your commit is rejected, fix the cause; do not use `--no-verify`.

Then complete every step of the contract's "Definition of done", which typically
includes:

- Deleting the source entry from `NORTHSTARS.md` or `IDEAS.md`. A northstar that
  has become true is worse than no northstar - that is the document's own rule.
- Updating `README.md` for any user-visible change, and re-stamping it so
  `reflock check` stays green.
- Setting the item's `status` to `done` in `ROADMAP.yaml`.

Do not open a pull request. The loop owns the branch.

### Scope discipline

Touch only what the item requires. Do not refactor adjacent code, do not fix
unrelated nits, do not bump the version, do not reformat files you did not
otherwise change. A reviewer needs to read one commit and see one item.

If you notice a genuine problem outside the item's scope, add it to
`ROADMAP.yaml` as a new entry with `status: needs-spec` and a note. That is the
correct way to report it. Do not fix it in this iteration.
