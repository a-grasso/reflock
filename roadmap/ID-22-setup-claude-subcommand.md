# ID-22 acceptance contract: `reflock setup claude`

Source: AXI adoption review 2026-07-28 ([kunchenguid/axi](https://github.com/kunchenguid/axi) principle 7, "ambient context via session integrations")
Owner: agent · Tier: near · Touches: [reflock_lib/setup.py](../reflock_lib/setup.py) (new), [reflock_lib/cli.py](../reflock_lib/cli.py), [test_reflock.py](../test_reflock.py)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

The Claude Code `Stop`-hook gate exists only as copy-paste material -
`examples/hooks/reflock-gate.sh` + `settings.snippet.json` - wired by hand:
edit `.claude/settings.json`, `chmod +x` a script yourself. AXI principle 7
asks for an explicit, idempotent, path-repairing setup command for exactly
this. reflock has the integration; it never became a command.

Deliberately out of scope (decided when AXI adoption was scoped): a
`SessionStart` ambient dashboard - reflock's useful moment is "before you
finish/commit," which is why it's a `Stop` hook, not a per-session status
line with nothing new to say most of the time - and Codex/OpenCode support,
since reflock has no existing integration for either to promote.

## Required behavior

`reflock_lib/setup.py`: `STOP_HOOK_COMMAND`, `render_hook_script(invocation)`
(the hook body, `examples/hooks/reflock-gate.sh`'s own logic with
`invocation` substituted as `reflock_cmd`'s `${REFLOCK:-...}` default),
`reflock_invocation()` (bare `"reflock"` if `shutil.which` resolves it to
this same install, else `f"{sys.executable} {path}"`), `add_stop_hook`
(pure - merges one `Stop` entry into a settings dict, returns the same
object if already present), and `cmd_setup(args)` wiring it to
`<root>/.claude/{hooks/reflock-gate.sh,settings.json}` - write the script
(0o755) only if content differs, merge settings.json preserving every other
key, malformed JSON is a usage error (`render_error`, exit 2) rather than an
overwrite. `cli.py` adds `reflock setup <target>`, `target` constrained to
`choices=("claude",)`, `needs_index=False`.

## Explicitly out of scope

Same as "The defect" above, plus: a `--check` flag (no existing caller needs
a preview of a one-time setup action); installing the `SKILL.md` skill
(AXI treats the hook and the skill as independent, complementary paths -
the skill keeps its own `npx skills add` story); rewriting
`examples/hooks/`, which stays as the manual-install reference.

## Invariants

No new imports outside the stdlib (D3). `add_stop_hook` never mutates its
input. Every existing test/fixture/example is untouched.

## Tests

Pure functions (`add_stop_hook`, `render_hook_script`) and `cmd_setup`'s file
effects (fresh tree, idempotent re-run, unrelated `settings.json` keys
survive, malformed JSON doesn't overwrite) are unit-tested directly - no
mocking, no fixtures. `reflock_invocation()`'s PATH-preference branch is
*not* separately unit-tested: asserting it needs `shutil.which`/
`os.path.realpath` mocked, which mostly re-confirms the mock rather than
real behavior that legitimately varies by machine (whether `reflock` happens
to be on PATH) - the same judgment call CLI-02/CLI-03 already made for
`--help` output and bare-invocation behavior, both `test_reflock.py`-only.
No evalbench fixture: its harness never touches `.claude/`.

## Verification

```
make gate
```

## Definition of done

1. Unit tests pass; every existing test stays green unmodified.
2. README documents `reflock setup claude` next to the manual
   `examples/hooks/` instructions.
3. `ROADMAP.yaml` adds ID-22 as `done`.
