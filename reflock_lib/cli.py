"""Argument parsing, shell completion, and the `main` entry point."""
from __future__ import annotations

import argparse
import sys

from reflock_lib import __version__
from reflock_lib.engine import build_index, repo_root
from reflock_lib.commands import (
    BACKLINKS_RENDERERS,
    EXPLAIN_RENDERERS,
    RENDERERS,
    ScopeError,
    UNIT_PREVIEW_LINES,
    cmd_backlinks,
    cmd_check,
    cmd_explain,
    cmd_stamp,
    cmd_suspects,
)

COMPLETION_SHELLS = ("bash", "zsh", "fish")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reflock", description="a lockfile for cross-references")
    ap.add_argument("--version", action="version", version=f"reflock {__version__}")
    ap.add_argument("--root", default=".", help="tree root (default: git toplevel)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="report reference problems")
    c.add_argument("paths", nargs="*")
    c.add_argument("--json", action="store_true")
    c.add_argument("--format", choices=sorted(RENDERERS), default=None,
                   help="output format (default: human); --json is an alias for --format json")
    c.add_argument("--verbose", "-v", action="store_true", help="also list OK refs")
    c.add_argument("--quiet", "-q", action="store_true",
                   help="print nothing on success; one summary line to stderr on failure")
    c.add_argument("--no-color", action="store_true", help="disable colored output")
    c.set_defaults(fn=cmd_check)
    s = sub.add_parser("stamp", help="fill / update fingerprints")
    s.add_argument("paths", nargs="*")
    s.add_argument("--rebless", action="store_true", help="re-hash existing pins too")
    s.add_argument("--check", action="store_true",
                   help="report what stamp would do; write nothing")
    s.add_argument("--warn", action="store_true",
                   help="with --check: report but always exit 0 (advisory)")
    s.set_defaults(fn=cmd_stamp)
    sp = sub.add_parser("suspects", help="bare path-shaped tokens that don't resolve")
    sp.add_argument("paths", nargs="*")
    sp.add_argument("--all", action="store_true", help="scan every file, not just markdown")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_suspects)
    bl = sub.add_parser("backlinks", help="list references pointing at a path")
    bl.add_argument("path", help="repo-relative path, optionally with #anchor")
    bl.add_argument("--format", choices=sorted(BACKLINKS_RENDERERS), default=None,
                    help="output format (default: human)")
    bl.set_defaults(fn=cmd_backlinks)
    ex = sub.add_parser("explain", help="everything about one reference")
    ex.add_argument("spec", help="<file>:<line>")
    ex.add_argument("--format", choices=sorted(EXPLAIN_RENDERERS), default=None,
                    help="output format (default: human)")
    ex.add_argument("--full", action="store_true",
                    help=f"print the whole unit text, not the first "
                         f"{UNIT_PREVIEW_LINES} lines")
    ex.set_defaults(fn=cmd_explain)
    comp = sub.add_parser("completion", help="print a shell completion script")
    comp.add_argument("shell", choices=COMPLETION_SHELLS)
    comp.set_defaults(fn=cmd_completion, needs_index=False)
    return ap


def parser_spec() -> dict[str, dict]:
    """A projection of the live parser, per subcommand:

        {"flags":              sorted long/short flags,
         "groups":             [(long, short), …] - one entry per option, so a
                               short flag is emitted as an alias of its long
                               form rather than an unrelated second option,
         "valued":             {flag: [choices]} for flags taking a value,
         "positional_choices": choices of any positional argument}

    Used both to generate the completion scripts and, in tests, to assert they
    stay in parity with the parser - so a new subcommand or flag can't go
    stale in the shipped scripts without a test failing.

    It reports more than flag names because flag names alone were not enough
    (TEST-01): positional `choices` were dropped, so `reflock completion <TAB>`
    offered file paths instead of the three shells, and zsh was told `--format`
    takes no argument, so it could not complete the format after it.
    """
    ap = build_parser()
    sub_action = next(a for a in ap._subparsers._group_actions
                       if isinstance(a, argparse._SubParsersAction))
    spec = {}
    for name, subparser in sub_action.choices.items():
        flags, groups, valued, positional_choices = set(), [], {}, []
        for action in subparser._actions:
            opts = [o for o in action.option_strings if o not in ("-h", "--help")]
            if not action.option_strings and action.choices:
                positional_choices.extend(sorted(action.choices))
                continue
            if opts:
                groups.append(tuple(sorted(opts, key=lambda o: (not o.startswith("--"), o))))
            for opt in opts:
                flags.add(opt)
                if action.nargs != 0:   # store_true has nargs == 0
                    valued[opt] = sorted(action.choices) if action.choices else []
        spec[name] = {"flags": sorted(flags), "groups": sorted(groups), "valued": valued,
                      "positional_choices": positional_choices}
    return spec


def completion_script(shell: str) -> str:
    spec = parser_spec()
    subs = sorted(spec)
    if shell == "bash":
        lines = [
            "# reflock bash completion",
            "# Install: reflock completion bash > /etc/bash_completion.d/reflock",
            "_reflock_completion() {",
            "    local cur prev words cword",
            "    if type -t _init_completion >/dev/null 2>&1; then",
            "        _init_completion || return",
            "    else",
            '        cur="${COMP_WORDS[COMP_CWORD]}"',
            "        words=(\"${COMP_WORDS[@]}\")",
            "        cword=$COMP_CWORD",
            "    fi",
            f'    local subcommands="{" ".join(subs)}"',
            "    if [[ ${cword} -eq 1 ]]; then",
            '        COMPREPLY=( $(compgen -W "${subcommands}" -- "$cur") )',
            "        return",
            '    fi',
            '    case "${words[1]}" in',
        ]
        for name in subs:
            # A subcommand whose positional has choices completes those instead
            # of paths: `reflock completion <TAB>` takes a shell name.
            words = " ".join(spec[name]["positional_choices"] or spec[name]["flags"])
            lines.append(f'        {name}) COMPREPLY=( $(compgen -W "{words}" -- "$cur") ) ;;')
        path_subs = [n for n in subs if not spec[n]["positional_choices"]]
        lines += [
            "    esac",
            f'    case "${{words[1]}}" in {"|".join(path_subs)}) ;; *) return ;; esac',
            '    if [[ "$cur" != -* ]]; then',
            "        if type -t _filedir >/dev/null 2>&1; then",
            "            _filedir",
            "        else",
            '            COMPREPLY+=( $(compgen -f -- "$cur") )',
            "        fi",
            "    fi",
            "}",
            "complete -F _reflock_completion reflock",
            "",
        ]
        return "\n".join(lines)
    if shell == "zsh":
        lines = [
            "#compdef reflock",
            "# reflock zsh completion",
            "# Install: reflock completion zsh > ~/.zsh/completions/_reflock",
            "_reflock() {",
            "    local -a subcommands",
            "    subcommands=(",
        ]
        for name in subs:
            lines.append(f'        "{name}"')
        lines += [
            "    )",
            "    if (( CURRENT == 2 )); then",
            '        _describe "command" subcommands',
            "        return",
            "    fi",
            '    case "${words[2]}" in',
        ]
        for name in subs:
            info = spec[name]
            parts = []
            for group in info["groups"]:
                primary = group[0]
                label = primary.lstrip("-")
                choices = info["valued"].get(primary)
                if choices is not None:
                    # Tell zsh the option takes a value, and what values, or it
                    # cannot complete anything after `--format `.
                    values = f"({' '.join(choices)})" if choices else "( )"
                    parts.append(f"'{primary}=[{label}]:{label}:{values}'")
                elif len(group) > 1:
                    # One option with two spellings, not two options: zsh then
                    # stops offering -q once --quiet is on the line.
                    alts = " ".join(group)
                    parts.append(f"'({alts})'{{{','.join(group)}}}'[{label}]'")
                else:
                    parts.append(f'"{primary}"')    # a plain switch
            if info["positional_choices"]:
                parts.append(f"'1:{name}:({' '.join(info['positional_choices'])})'")
            else:
                parts.append("'*:file:_files'")
            lines.append(f"        {name}) _arguments {' '.join(parts)} ;;")
        lines += [
            "    esac",
            "}",
            "_reflock",
            "",
        ]
        return "\n".join(lines)
    if shell == "fish":
        lines = [
            "# reflock fish completion",
            "# Install: reflock completion fish > ~/.config/fish/completions/reflock.fish",
            f'complete -c reflock -n "__fish_use_subcommand" -a "{" ".join(subs)}"',
        ]
        for name in subs:
            info = spec[name]
            for group in info["groups"]:
                # One completion per option carrying every spelling, so fish
                # knows -q and --quiet are the same switch.
                opt = " ".join("-l " + f[2:] if f.startswith("--") else "-s " + f[1:]
                                for f in group)
                choices = info["valued"].get(group[0])
                # `-r` marks the flag as requiring a value; `-a` supplies them.
                if choices:
                    opt += f' -r -a "{" ".join(choices)}"'
                elif choices == []:
                    opt += " -r"
                lines.append(
                    f'complete -c reflock -n "__fish_seen_subcommand_from {name}" {opt}'
                )
            arg = (f'"{" ".join(info["positional_choices"])}"'
                   if info["positional_choices"] else '"(__fish_complete_path)"')
            lines.append(
                f'complete -c reflock -n "__fish_seen_subcommand_from {name}" -a {arg}'
            )
        lines.append("")
        return "\n".join(lines)
    raise ValueError(f"unsupported shell: {shell!r}")


def cmd_completion(args) -> int:
    print(completion_script(args.shell))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if getattr(args, "needs_index", True) is False:
        return args.fn(args)
    root = repo_root(args.root)
    try:
        return args.fn(build_index(root), args)
    except ScopeError as e:
        # Caught here rather than in each command: every path-scoped command
        # funnels through one call, and exit 2 keeps "misconfigured invocation"
        # distinct from 1 ("found problems") for CI.
        print(e, file=sys.stderr)
        return 2
