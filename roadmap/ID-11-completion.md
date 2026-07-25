# ID-11 acceptance contract: `reflock completion <shell>`

Source: idea #11 in [IDEAS.md](../IDEAS.md)
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## Correction to the idea entry

IDEAS.md #11 claims "`argparse` can generate bash/zsh/fish completions almost
for free". **It cannot** - argparse has no completion generation. The entry is
wrong and must be corrected as part of this work.

The options were a third-party dependency (`argcomplete`), which D3 forbids, or
hand-written static scripts. Hand-written was chosen, on the grounds that it is
additive and therefore the easier choice to reverse: adding the subcommand
commits to nothing, whereas a dependency in the Homebrew formula and install path
cannot be removed without breaking users.

## Required behavior

```
$ reflock completion zsh > ~/.zsh/completions/_reflock
$ reflock completion bash
$ reflock completion fish
```

- Prints a static completion script for the named shell to stdout. Writes
  nothing, installs nothing, touches no dotfile.
- Completes subcommands (`check`, `stamp`, `suspects`, and any added by then) and
  each subcommand's flags.
- File-path completion for positional path arguments, using the shell's native
  mechanism rather than calling back into reflock.
- An unsupported shell name exits nonzero listing the supported ones.

## The maintenance hazard, and the required guard

Hand-written scripts go stale the moment someone adds a subcommand or flag, and
nothing about a stale completion script fails visibly. So a **parity test is part
of this contract, not an extra**: walk the argparse parser and assert every
subcommand name and every long flag appears in each shell's script.

```
for sub in parser subcommands:
    for shell in (bash, zsh, fish):
        assert sub in completion_script(shell)
```

Without that test this item is a liability rather than a feature. If the parity
test cannot be written against the current parser structure, that is a finding
worth reporting - do not ship the scripts without a guard.

## Explicitly out of scope

- Installing into the user's shell configuration.
- Dynamic completion that shells out to reflock at completion time.
- Any dependency (D3).

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- No writes.
- No new imports outside the stdlib (D3).
- The scripts are data, not executed by reflock. Nothing in reflock evaluates
  them.

## Tests to add

- Parity test above, for all three shells, driven off the parser rather than a
  hardcoded list - a hardcoded list would go stale in exactly the way the test
  exists to prevent.
- `completion <unsupported>` exits nonzero and names the supported shells.
- Each script is non-empty and syntactically plausible for its shell (at minimum,
  bash and zsh scripts parse under `sh -n` where applicable).

No evalbench fixture is required: this command does not examine a tree, so a
fixture repo adds nothing. State that in the PR rather than adding an empty one.

## Verification

```
make gate
```

`suspects` is advisory and exits nonzero whenever it has
anything to say, so it is not part of the gate. Read its output, act on
anything real, but do not chain it.

Plus a manual check in at least one real shell, reported in the PR body. A
completion script that is syntactically valid and functionally useless passes
every automated test.

## Definition of done

1. Parity and error-path tests pass; nothing existing was modified.
2. Idea #11 is **deleted** from [IDEAS.md](../IDEAS.md), including its incorrect
   claim about argparse - do not leave the wrong statement behind in a reworded
   form.
3. README documents installation for all three shells.
4. `ROADMAP.yaml` marks ID-11 `done`.
