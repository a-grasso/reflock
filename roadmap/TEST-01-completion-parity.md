# TEST-01 acceptance contract: the fish parity test is satisfied by a comment it forced

Source: review 2026-07-28
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

ID-11's selling point was that the completion scripts are generated from the
live argparse spec, so "a parity test blocks drift". For fish, that test is
satisfied by a comment the test itself forced into the shipped script:

```
complete -c reflock -n "__fish_seen_subcommand_from check" -l format  # --format
```

fish spells flags `-l format`, so the literal `--format` appears nowhere
naturally. The trailing `# --format` exists only so `assertIn(flag, script)`
passes. Deleting it as tidy-up breaks the suite; keeping it ships dead syntax to
users. A test whose assertion is met by a comment is not testing the artifact.

Three consequences follow from the same weakness - the test only ever compared
*flag name substrings*:

1. **No fish validation at all.** bash and zsh each get a `-n` syntax check;
   fish gets none, so its script is unverified beyond substring presence.
2. **Positional `choices` are never completed.** `parser_spec()` walks
   `option_strings` only, so `reflock completion <TAB>` offers file paths where
   the only valid values are `bash`, `zsh`, `fish` - a completion that actively
   misleads.
3. **zsh declares value-taking options as bare flags.** `_arguments "--format"`
   says `--format` takes no argument, so zsh cannot complete
   `human|json|github` after it, and `-q`/`--quiet` are declared as two
   unrelated options rather than aliases.

## Required behavior

### `parser_spec()` projects the parser, not just flag names

It returns, per subcommand: the flags, which flags take a value and what values
they accept, and the choices of any positional. That is the information all
three generators need and none of them had.

### Each script uses its own shell's syntax, with no comment crutch

- The `# --flag` comments come out of the fish script. Nothing may depend on a
  flag name appearing verbatim in a shell that does not spell it that way.
- `reflock completion <TAB>` offers `bash zsh fish` in all three shells, and
  does **not** offer file paths - the argument is not a path.
- zsh declares a value-taking option as such, with its choices:
  `'--format=[output format]:format:(github human json)'`.

### The parity test asserts the artifact, per shell

For each subcommand and flag, the test asserts the flag is present *in the form
that shell uses*: inside the subcommand's `compgen -W` word list for bash, in
its `_arguments` spec for zsh, as `-l long` / `-s s` for fish. And it asserts
the inverse for fish - the literal `--format` must be **absent**, which is what
makes a reintroduced comment crutch a failure rather than a pass.

A `fish -n` syntax check joins the bash and zsh ones, skipping when fish is not
installed exactly as those do.

## Authorized test changes

Two existing tests must change, and both are mechanical consequences of
`parser_spec()`'s richer return - neither weakens an assertion:

- `test_completion_parity_subcommands_and_flags` is replaced by the per-shell
  assertions above. This is the item.
- `test_entry_flags_exist_on_that_subcommand` (manifest) reads `spec[sub]` as a
  flag list; it becomes `spec[sub]["flags"]`.

## Explicitly out of scope

- Completing *values* for anything but declared `choices`. No file-content or
  git-aware completion.
- A fourth shell.
- Installing completions. `reflock completion <shell>` prints; the user
  redirects. Unchanged.

## Invariants

- Existing unit tests and evalbench fixtures stay green apart from the two named
  above. `test_completion_bash_script_parses_under_bash` and its zsh twin must
  still pass, unmodified.
- Every script stays static text generated at print time - no runtime
  introspection in the emitted script.
- No new imports outside the stdlib (D3).

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `completion-bash-lists-subcommands` | `completion bash` exits 0 and its output names every subcommand |
| `completion-fish-uses-fish-syntax` | `completion fish` emits `-l format` and does **not** contain `--format`, so the comment crutch cannot come back unnoticed |
| `completion-offers-shell-choices` | all three scripts offer `bash zsh fish` for the `completion` subcommand's positional |

## Unit tests to add

- Per shell, per subcommand, per flag: present in that shell's syntax.
- fish script contains no `--`-prefixed flag literal, and no `#` comment
  carrying a flag name.
- All three scripts offer the `completion` positional's choices, and the bash
  and fish ones do not fall back to path completion for that subcommand.
- zsh declares `--format` with a value and lists its choices.
- `parser_spec()` reports `--format` as value-taking with its three choices, and
  `--quiet` as a flag; and reports the `completion` positional's choices.
- `fish -n` parses the fish script (skip if fish is absent).
- A new flag added to the parser appears in all three scripts - the drift
  guarantee ID-11 claimed, now asserted through the real syntax.

## Verification

```
make gate
```

## Definition of done

1. Fixtures and tests above pass; the two authorized test changes are made and
   nothing else existing was modified.
2. No `# --flag` comments remain in any generated script.
3. `ROADMAP.yaml` marks TEST-01 `done`.
