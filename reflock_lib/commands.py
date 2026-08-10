"""Subcommand implementations and their output renderers (human/JSON/GitHub
annotations). Each `cmd_*` is what a subparser's `fn` points at; each renders
through a format table so a new format is one function plus one entry, not a
new branch in every command.
"""
from __future__ import annotations

import json
import os
import sys

from reflock_lib import __version__
from reflock_lib.grammar import EXTERNAL, FP_VERSION, PATHISH, Index, Ref
from reflock_lib.engine import (
    classify,
    git_ignored,
    is_unauthored_source,
    locate_anchor,
    mask_code_spans,
    mask_urls,
    parse_refs,
    path_tails,
    resolve_path,
    resolve_target,
    resolve_wikilink,
    split_pin,
    strip_dot_segments,
    unit_fingerprint,
    unit_text,
)

BAD = {"DANGLING", "DRIFTED", "UNSTAMPED", "UNSUPPORTED"}

VERDICT_COLOR = {
    "DANGLING": "\033[31m",   # red
    "DRIFTED": "\033[33m",    # yellow
    "UNSTAMPED": "\033[35m",  # magenta
    "UNSUPPORTED": "\033[36m",  # cyan
    "OK": "\033[32m",         # green
}
COLOR_RESET = "\033[0m"


def use_color(args) -> bool:
    """--no-color and NO_COLOR (https://no-color.org) both win over a tty; a
    non-tty stdout (redirected to a file, piped into another tool) never gets
    escape codes even if neither flag is set."""
    if getattr(args, "no_color", False) or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def colorize(text: str, verdict: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{VERDICT_COLOR[verdict]}{text}{COLOR_RESET}"


class ScopeError(Exception):
    """A path argument names nothing in the tree."""


def rel_to_root(idx: Index, arg: str) -> str:
    """A user-supplied path argument as a repo-relative path.

    Relative to the process CWD, like git and find - not to --root. realpath on
    both sides so a symlinked checkout, a `./` prefix and a `..` spelling all
    reduce to the same thing; on macOS a temp dir arrives as /var/… and resolves
    to /private/var/…, and comparing one resolved path against one unresolved one
    puts every argument outside the tree.

    Shared by scoped_files and indexed_path so `check`, `stamp`, `suspects`,
    `backlinks` and `explain` cannot disagree about what a path is (CLI-01).
    """
    root = os.path.realpath(idx.root)
    return os.path.normpath(os.path.relpath(os.path.realpath(arg), root)).replace(os.sep, "/")


def indexed_path(idx: Index, arg: str) -> str | None:
    """One indexed file named by a single-path argument, or None.

    CWD-relative first, then the repo-relative reading - the same
    relative-first-then-fallback shape D4 uses for wiki-links. The fallback is
    not a convenience: `check` *prints* repo-relative paths whatever directory it
    runs in, and pasting `docs/a.md:1` straight into `explain` is the obvious
    workflow. CWD-only resolution turns that paste into docs/docs/a.md as soon as
    the user is inside docs/. A command should accept the strings it prints.

    Used by backlinks and explain, which take an *identifier* for one file.
    scoped_files stays CWD-only: `check docs/` is a path to scope by, where
    git-like behavior is the whole expectation.
    """
    rel = rel_to_root(idx, arg)
    if rel in idx.files:
        return rel
    literal = os.path.normpath(arg).replace(os.sep, "/")
    return literal if literal in idx.files else None


def scoped_files(idx: Index, paths: list[str]) -> list[str]:
    """Reference *sources* under the requested paths; all of them if none given.

    An argument naming nothing in the tree raises rather than selecting an empty
    work list: `reflock check docs/` silently passed forever once docs/ was
    renamed, which is the rot reflock exists to catch (BUG-04). A path that
    exists but contributes no sources - binary, .reflockignore'd, or a directory
    of only those - is matched and simply empty, so explicit scoping and
    .reflockignore do not fight each other.
    """
    sources = sorted(f for f in idx.files
                      if f in idx.lines and f not in idx.ignored
                      and f not in idx.symlinks)
    if not paths:
        return sources
    selected: set[str] = set()
    unmatched = []
    for p in paths:
        w = rel_to_root(idx, p)
        if w == ".":
            return sources                      # the tree root, as it reads
        hits = [f for f in sources if f == w or f.startswith(w + "/")]
        if hits:
            selected.update(hits)
        elif w not in idx.files and w not in idx.dirs:
            unmatched.append(p)                 # echo the user's spelling
    if unmatched:
        raise ScopeError("no such path in tree: " + ", ".join(unmatched))
    return sorted(selected)


SCHEMA = 1

VERDICTS = ("OK", "DANGLING", "DRIFTED", "UNSTAMPED", "UNSUPPORTED")


def envelope(command: str, root: str, findings: list, summary: dict,
             problems: int, **extra) -> dict:
    """The one shape every JSON emitter produces (D7).

    `findings` is always an array, on every exit path including errors, so a
    consumer never has to type-switch on the top level and the naive
    `for f in json.load(fh)` cannot silently iterate the characters of an error
    string - which is what the previous bare-array-or-error-object shape did.

    `schema` is emitted, never negotiated. Additive changes (a new key, a new
    vocabulary member) leave it alone; removing or repurposing a key bumps it.
    That asymmetry is the whole reason it exists: it buys room to grow this
    surface later without a flag day.
    """
    env = {"schema": SCHEMA, "reflock": __version__, "command": command,
           "root": root, "findings": findings, "summary": summary,
           "problems": problems}
    env.update(extra)
    return env


def emit_json(env: dict) -> None:
    print(json.dumps(env, indent=2))


def verdict_summary(verdicts) -> dict:
    """Counts per verdict over the findings being reported, all five keys
    present so a consumer branching on `summary["DRIFTED"]` never needs a
    default. It counts the `findings` array, not every reference in the tree:
    a summary that disagreed with the array beside it would be a worse lie than
    no summary at all. Without --verbose, `check` reports only problems, so a
    clean tree is all zeros."""
    counts = dict.fromkeys(VERDICTS, 0)
    for v in verdicts:
        counts[v] = counts.get(v, 0) + 1
    return counts


def render_json(idx, results, problems: int, args) -> int:
    # `info` is spread into the finding rather than nested under a key of its
    # own: `reason` is what a consumer branches on, and burying it a level down
    # would make the machine-readable field the awkward one to reach (AGT-02).
    emit_json(envelope(
        "check", idx.root,
        [{"verdict": v, "file": r.src, "line": r.line,
          "target": r.target, "detail": d, **info} for v, r, d, info in results],
        verdict_summary(v for v, _, _, _ in results), problems))
    return 1 if problems else 0


def render_human(idx, results, problems: int, args) -> int:
    color = use_color(args)
    for v in ("DANGLING", "DRIFTED", "UNSUPPORTED", "UNSTAMPED", "OK"):
        group = [(r, d) for vv, r, d, _ in results if vv == v]
        if not group:
            continue
        print(f"\n{colorize(f'{v} ({len(group)})', v, color)}")
        for r, d in group:
            print(f"  {r.src}:{r.line}  {r.target}   [{d}]")
    msg = f"{problems} problem(s)." if problems else "All references OK."
    print(f"\n{colorize(msg, 'DANGLING' if problems else 'OK', color)}")
    if problems:
        print("\nRun `reflock explain <file>:<line>` for details on any of the above.")
        if any(v == "UNSTAMPED" for v, _, _, _ in results):
            print("Run `reflock stamp` to fill in UNSTAMPED pins.")
    return 1 if problems else 0


GITHUB_LEVEL = {"DANGLING": "error", "DRIFTED": "error", "UNSTAMPED": "warning",
                "UNSUPPORTED": "error"}


def github_escape_property(text: str) -> str:
    """Escape a workflow-command property value (e.g. file=, line=)."""
    return (text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                .replace(":", "%3A").replace(",", "%2C"))


def github_escape_message(text: str) -> str:
    """Escape workflow-command message data (no colon/comma escaping needed)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def render_github(idx, results, problems: int, args) -> int:
    # `reason` deliberately does not appear here: NS-04 fixes `detail` as the
    # annotation message and the verdict as its title, and an annotation is read
    # by a human in a PR, not branched on by a script.
    for v, r, d, _ in results:
        level = GITHUB_LEVEL.get(v)
        if level is None:
            continue
        file_ = github_escape_property(r.src)
        line = r.line
        title = github_escape_property(v)
        message = github_escape_message(d)
        print(f"::{level} file={file_},line={line},title={title}::{message}")
    return 1 if problems else 0


RENDERERS = {"human": render_human, "json": render_json, "github": render_github}


class FormatConflict(Exception):
    pass


def resolve_format(args) -> str:
    """--json and --format may agree; if they disagree, that is an error, not
    a silent pick between the two."""
    fmt = getattr(args, "format", None) or "human"
    if getattr(args, "json", False):
        if args.format and args.format != "json":
            raise FormatConflict(
                f"--json conflicts with --format {args.format} "
                f"(--json implies --format json)")
        fmt = "json"
    return fmt


def intended_format(args) -> str:
    """The format a command *meant* to use, without resolve_format's
    conflict-checking - for rendering an error raised before (or instead of)
    a successful resolve_format() call, so the error lands in the same shape
    the caller asked for even when that ask was itself the problem.

    Commands with no --format concept (stamp, suspects) always read "human"
    here: they have no JSON/github renderer to route an error through (D1).
    """
    fmt = getattr(args, "format", None)
    if fmt:
        return fmt
    return "json" if getattr(args, "json", False) else "human"


ERROR_KINDS = ("usage", "scope")


def render_error(message: str, fmt: str, kind: str = "usage",
                 command: str = "", root: str = "") -> None:
    """The one place a usage error becomes output, in whatever format the
    command's caller asked for - the error-path counterpart to RENDERERS.

    json/github land the error on stdout in their own shape, so a script or
    agent that requested a format gets something to parse even on failure;
    human keeps today's plain `error: <message>` line on stderr.

    The json form is the full envelope with an empty `findings` array, not a
    bare `{"error": ...}` object (D7): the error path is exactly where a
    consumer is least likely to have written a type check, so it must not be
    the one path that changes shape under it. `kind` is the closed vocabulary a
    caller branches on; `message` is prose and may be reworded (D8).
    """
    if fmt == "json":
        emit_json(envelope(command, root, [], verdict_summary(()), 0,
                           error={"kind": kind, "message": message}))
    elif fmt == "github":
        print(f"::error::{github_escape_message(message)}")
    else:
        print(f"error: {message}", file=sys.stderr)


def cmd_check(idx: Index, args) -> int:
    try:
        fmt = resolve_format(args)
    except FormatConflict as e:
        render_error(str(e), intended_format(args), "usage", "check", idx.root)
        return 2
    if args.quiet and args.verbose:
        render_error("--quiet conflicts with --verbose", fmt, "usage", "check", idx.root)
        return 2
    results = []
    total = 0
    try:
        scoped = scoped_files(idx, args.paths)
    except ScopeError as e:
        render_error(str(e), fmt, "scope", "check", idx.root)
        return 2
    for rel in scoped:
        for ref in parse_refs(idx, rel):
            verdict, detail, info = classify(idx, ref)
            total += 1
            if verdict != "OK" or args.verbose:
                results.append((verdict, ref, detail, info))
    problems = sum(1 for v, _, _, _ in results if v in BAD)
    if args.quiet and fmt == "human":
        if problems:
            print(f"reflock: {problems} of {total} references failed", file=sys.stderr)
        return 1 if problems else 0
    return RENDERERS[fmt](idx, results, problems, args)


def stampable_fingerprint(idx: Index, ref: Ref) -> str | None:
    """The fingerprint `stamp` would write for this reference, or None if there
    is nothing it can honestly hash.

    Resolution goes through resolve_target — the same function classify() uses —
    so a reference cannot resolve one way for `check` and another for `stamp`.
    Deriving the path here independently is what let `stamp` write
    fingerprint("") into external, outside-tree, directory and binary targets
    while `check` reported them OK and never contradicted the pin.

    None means "not hashable", which is not the same as "hashes to empty": a
    genuinely empty text file has fingerprint("") and is stamped normally.
    """
    kind, path, anchor, _ = resolve_target(idx, ref)
    if kind != "file":
        return None            # external, outside the tree, a dir, or dangling
    if path not in idx.lines:
        return None            # exists but carries no indexed text (binary)
    return unit_fingerprint(idx, path, anchor)   # None again if the anchor misses


def plan_stamp(idx: Index, args):
    """Compute the edits `stamp` would make, without writing anything.

    Returns (edits_by_rel, report): edits_by_rel maps rel -> {lineno: [(s, e,
    fp), ...]} for writing; report is an ordered list of (rel, ref, kind, fp)
    for display, where kind is "unstamped" or "stale". Shared by cmd_stamp's
    write path and its --check path so the two cannot diverge.
    """
    edits_by_rel: dict[str, dict[int, list[tuple[int, int, str]]]] = {}
    report = []
    for rel in scoped_files(idx, args.paths):
        for ref in parse_refs(idx, rel):
            if ref.pin is None:
                continue                       # not opted in
            if ref.pin != "" and not args.rebless:
                continue                       # existing pin, no --rebless
            if ref.pin and split_pin(ref.pin)[0] != FP_VERSION:
                # --rebless would splice a version-1 hex over a pin written by a
                # newer reflock, silently downgrading it. `check` already says
                # UNSUPPORTED; the honest move here is to leave it alone.
                continue
            fp = stampable_fingerprint(idx, ref)
            if fp is None:
                continue                       # nothing honest to hash
            if fp != ref.pin:
                kind = "unstamped" if ref.pin == "" else "stale"
                edits_by_rel.setdefault(rel, {}).setdefault(ref.line - 1, []).append((*ref.pin_span, fp))
                report.append((rel, ref, kind, fp))
    return edits_by_rel, report


def cmd_stamp(idx: Index, args) -> int:
    warn = getattr(args, "warn", False)
    if warn and not getattr(args, "check", False):
        # Plain `stamp` already exits 0, so accepting --warn there would imply it
        # did something.
        render_error("--warn requires --check", intended_format(args), "usage", "stamp", idx.root)
        return 2
    try:
        edits_by_rel, report = plan_stamp(idx, args)
    except ScopeError as e:
        render_error(str(e), intended_format(args), "scope", "stamp", idx.root)
        return 2
    if getattr(args, "check", False):
        for rel, ref, kind, fp in report:
            print(f"  {rel}:{ref.line}  {ref.target}   [{kind}]")
        if report:
            print(f"\n{len(report)} pin(s) would be stamped.")
            print("\nRun `reflock stamp` to apply.")
            # --warn reports without judging: the exit code is the only
            # difference, so a pre-commit-framework hook can be advisory even
            # though pre-commit itself has no warn-only mode (D6).
            return 0 if warn else 1
        print("\nNothing to stamp.")
        return 0
    if args.rebless and not getattr(args, "reviewed", False) and report:
        # The gate's whole claim is that a DRIFTED verdict is a real "someone
        # should read this" event. Unguarded, `--rebless` discards that event
        # with no friction, which is how a gate becomes decoration - so writing
        # takes a second, explicit statement that a human (or agent) engaged
        # with what changed. One rule in a TTY and in CI alike: a gate that
        # behaves differently under a terminal is a gate people learn to
        # distrust. See docs/roadmap/PUB-01-pre-announcement-scope.md.
        for rel, ref, kind, fp in report:
            if kind == "stale":
                print(f"  {rel}:{ref.line}  {ref.target}   [@{ref.pin} -> @{fp}]")
        print(f"\n{len(report)} pin(s) would be re-blessed, discarding the drift "
              f"signal that flagged them.")
        print("Read what changed (`reflock explain <file>:<line>`), then re-run "
              "with --reviewed to write.")
        return 1
    changed = 0
    for rel, edits in edits_by_rel.items():
        ap = os.path.join(idx.root, rel)
        # Re-read with newline="" and splice into the file's own lines, keeping
        # each terminator attached. Rebuilding from idx.lines - which came from a
        # universal-newline read - rewrote every \r\n in the file to \n, so
        # stamping one pin produced a whole-file diff, and a file with no
        # trailing newline gained one (BUG-05). Pin spans are offsets into the
        # line content, so they stay valid with the terminator left in place.
        with open(ap, encoding="utf-8", newline="") as fh:
            keep = fh.read().splitlines(keepends=True)
        for lineno, splices in edits.items():
            ln = keep[lineno]
            for s, e, fp in sorted(splices, reverse=True):
                ln = ln[:s] + fp + ln[e:]
            keep[lineno] = ln
            changed += len(splices)
        text = "".join(keep)
        with open(ap, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        idx.lines[rel] = text.splitlines()   # keep the index consistent
    # Belt and braces, not load-bearing: PIN_STRIP removes pins before hashing,
    # which is why stamping never cascades drift, so no cached fingerprint can
    # actually have been invalidated by the writes above. Dropping the cache
    # anyway keeps "the Index reflects the tree" true without needing that
    # argument to hold.
    idx.fps.clear()
    print(f"Stamped {changed} pin(s).")
    return 0


def render_backlinks_human(idx, rows, target: str, args) -> int:
    if not rows:
        print(f"No backlinks to {target}.")
        return 0
    for rel, line, tgt, pin in rows:
        print(f"{rel}:{line}  {tgt}  {pin}")
    print(f"\n{len(rows)} backlink(s).")
    return 0


def render_backlinks_json(idx, rows, target: str, args) -> int:
    emit_json(envelope(
        "backlinks", idx.root,
        [{"file": rel, "line": line, "target": tgt, "pin": pin}
         for rel, line, tgt, pin in rows],
        {"backlinks": len(rows)}, 0, queried=target))
    return 0


BACKLINKS_RENDERERS = {"human": render_backlinks_human, "json": render_backlinks_json}


def cmd_backlinks(idx: Index, args) -> int:
    try:
        fmt = resolve_format(args)
    except FormatConflict as e:
        render_error(str(e), intended_format(args), "usage", "backlinks", idx.root)
        return 2
    arg_path, _, target_anchor = args.path.partition("#")
    target_anchor = target_anchor or None
    target_path = indexed_path(idx, arg_path)
    if target_path is None:
        render_error(f"no such file in index: {arg_path}", fmt, "scope", "backlinks", idx.root)
        return 2
    if target_anchor is not None and locate_anchor(idx, target_path, target_anchor)[0] is None:
        # Same reasoning as the missing-file case: "nothing points at this
        # section" is the answer you act on before editing that section, so a
        # misspelled anchor must not be able to produce it.
        render_error(f"no anchor '#{target_anchor}' in {target_path}", fmt, "scope", "backlinks", idx.root)
        return 2
    rows = []
    for rel in scoped_files(idx, []):
        for ref in parse_refs(idx, rel):
            tgt = ref.target
            if EXTERNAL.match(tgt) and not tgt.startswith("#"):
                continue
            if tgt.startswith("#"):
                path, anchor = ref.src, tgt[1:]
            else:
                path_part, _, anchor = tgt.partition("#")
                anchor = anchor or None
                if ref.wiki:
                    path, _ = resolve_wikilink(idx, ref.src, path_part)
                else:
                    path = resolve_path(ref.src, path_part)
            if path != target_path:
                continue
            if target_anchor is not None and anchor != target_anchor:
                continue
            pin = "unpinned" if ref.pin is None else ("unstamped" if ref.pin == "" else "pinned")
            rows.append((ref.src, ref.line, ref.target, pin))
    rows.sort(key=lambda r: (r[0], r[1]))
    return BACKLINKS_RENDERERS[fmt](idx, rows, target_path, args)


def explain_entry(idx: Index, ref: Ref) -> dict:
    verdict, detail, info = classify(idx, ref)
    kind, path, anchor, _ = resolve_target(idx, ref)
    # `reason` only, not the rest of `info`: explain already reports `pin` and
    # `current` in its own shape, and a second copy of the same digests under
    # classify's names would be two sources of truth in one object.
    entry = {"file": ref.src, "line": ref.line, "target": ref.target, "verdict": verdict,
              "detail": detail, "reason": info["reason"],
              "resolves_to": None, "anchor": None, "pin": None, "current": None,
              "unit_text": None}
    if kind != "file":
        return entry
    entry["resolves_to"] = path
    if anchor:
        akind, start, end = locate_anchor(idx, path, anchor)
        if akind:
            entry["anchor"] = {"kind": akind, "start": start, "end": end}
    if ref.pin:
        entry["pin"] = ref.pin
    elif ref.pin == "":
        entry["pin"] = "unstamped"
    else:
        entry["pin"] = "unpinned"
    if ref.pin is not None:
        entry["unit_text"] = unit_text(idx, path, anchor)
        entry["current"] = unit_fingerprint(idx, path, anchor)
    return entry


UNIT_PREVIEW_LINES = 40


def unit_preview(unit: str, full: bool) -> str:
    """The unit text, previewed rather than dumped.

    `explain` exists to say everything about *one* reference, and for an
    unanchored one the unit is the whole file - so a pinned reference to a
    2000-line design doc printed 2000 lines, which is exactly where a reference
    matters most. The rule is uniform rather than whole-file-only: a 900-line
    section is as unreadable as a 900-line file, and one branch is easier to
    trust than two.
    """
    lines = unit.split("\n")
    if full or len(lines) <= UNIT_PREVIEW_LINES:
        return unit
    withheld = len(lines) - UNIT_PREVIEW_LINES
    noun = "line" if withheld == 1 else "lines"
    return "\n".join(lines[:UNIT_PREVIEW_LINES]
                     + [f"… {withheld} more {noun} (--full to show)"])


def render_explain_human(idx, entries, args) -> int:
    color = use_color(args)
    for e in entries:
        print(f"reference   {e['file']}:{e['line']}")
        print(f"target      {e['target']}")
        if e["resolves_to"]:
            print(f"resolves to {e['resolves_to']}")
        else:
            print(f"resolves to (unresolved) [{e['detail']}]")
        if e["anchor"]:
            a = e["anchor"]
            label = "matched heading" if a["kind"] == "heading" else "matched span"
            print(f"anchor      {label}, lines {a['start']}-{a['end']}")
        if e["pin"] is not None:
            print(f"pin         {e['pin']}")
        if e["current"] is not None:
            print(f"current     {e['current']}")
        print(f"verdict     {colorize(e['verdict'], e['verdict'], color)}")
        if e["verdict"] == "DRIFTED":
            print("note: the prior pinned text is not recoverable (only its hash "
                  "was stored) - showing the current text below.")
        if e["unit_text"] is not None:
            print()
            print(unit_preview(e["unit_text"], getattr(args, "full", False)))
        print()
    return 1 if any(e["verdict"] in BAD for e in entries) else 0


def render_explain_json(idx, entries, args) -> int:
    problems = sum(1 for e in entries if e["verdict"] in BAD)
    emit_json(envelope(
        "explain", idx.root,
        [{k: v for k, v in e.items() if k != "unit_text"} for e in entries],
        verdict_summary(e["verdict"] for e in entries), problems))
    return 1 if problems else 0


EXPLAIN_RENDERERS = {"human": render_explain_human, "json": render_explain_json}


def cmd_explain(idx: Index, args) -> int:
    try:
        fmt = resolve_format(args)
    except FormatConflict as e:
        render_error(str(e), intended_format(args), "usage", "explain", idx.root)
        return 2
    file_part, sep, line_part = args.spec.rpartition(":")
    if not sep or not line_part.isdigit() or int(line_part) < 1:
        render_error(f"invalid <file>:<line> spec: {args.spec}", fmt, "usage", "explain", idx.root)
        return 2
    lineno = int(line_part)
    rel = indexed_path(idx, file_part)
    if rel is None:
        render_error(f"no such file in index: {file_part}", fmt, "scope", "explain", idx.root)
        return 2
    lines = idx.lines.get(rel)
    if lines is None or lineno > len(lines):
        render_error(f"{rel} has no line {lineno}", fmt, "scope", "explain", idx.root)
        return 2
    refs = [r for r in parse_refs(idx, rel) if r.line == lineno]  # parse_refs owns the order
    if not refs:
        render_error(f"no reference on {rel}:{lineno}", fmt, "scope", "explain", idx.root)
        return 2
    entries = [explain_entry(idx, r) for r in refs]
    return EXPLAIN_RENDERERS[fmt](idx, entries, args)


def cmd_suspects(idx: Index, args) -> int:
    # Pass 1: collect path-shaped tokens that resolve to nothing.
    candidates = []  # (rel, lineno, token, [paths to test against .gitignore])
    try:
        scoped = scoped_files(idx, args.paths)
    except ScopeError as e:
        render_error(str(e), intended_format(args), "scope", "suspects", idx.root)
        return 2
    tails = path_tails(idx)  # once per run; a hashmap lookup per token (PERF-01)
    for rel in scoped:
        if is_unauthored_source(rel):
            continue
        is_md = rel.endswith((".md", ".markdown"))
        if not args.all and not is_md:
            continue
        refd = {r.target for r in parse_refs(idx, rel)}
        in_fence = False
        for i, ln in enumerate(idx.lines[rel]):
            if ln.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            # Code spans are exempt on the same basis as fenced blocks and as
            # references themselves (D2, BUG-02): a path in backticks is prose
            # *about* a path. Raw lines for non-markdown, exactly as parse_refs
            # does - a backtick in a .py file is not a code span.
            # URLs are masked in every file (BUG-08): a URL in a .json string
            # literal is no more a repo path than one in prose.
            scan = mask_urls(mask_code_spans(ln) if is_md else ln)
            for m in PATHISH.finditer(scan):
                tok = m.group("p")
                if any(tok in t for t in refd):
                    continue
                rp = resolve_path(rel, tok)
                if rp and (rp in idx.files or rp.rstrip("/") in idx.dirs):
                    continue
                if tok in idx.files or tok.rstrip("/") in idx.dirs:
                    continue
                # Resolves somewhere in the tree, just not from the base guessed
                # here - not evidence of rot (BUG-12, on D4's precedent).
                bare = strip_dot_segments(tok)
                if tok in tails or bare in tails:
                    continue
                # `bare` rather than `tok` for the gitignore probe: a path whose
                # base is a working directory is only ever ignored under its
                # root-relative reading, and `git check-ignore` has no
                # meaningful answer for a `..`-prefixed path.
                candidates.append((rel, i + 1, tok, [c for c in (rp, bare) if c]))
    # Pass 2: a path git would ignore is intentionally absent, not a stale ref.
    ignored = git_ignored(idx.root, sorted({c for *_, cs in candidates for c in cs}))
    hits = [(rel, lineno, tok) for rel, lineno, tok, cands in candidates
            if not any(c in ignored for c in cands)]
    if args.json:
        emit_json(envelope(
            "suspects", idx.root,
            [{"file": rel, "line": lineno, "target": tok}
             for rel, lineno, tok in hits],
            {"suspects": len(hits)}, len(hits)))
    else:
        for rel, lineno, tok in hits:
            print(f"  {rel}:{lineno}  {tok}   [bare path, does not resolve]")
        print(f"\n{len(hits)} suspect(s)." if hits else "\nNo bare-path suspects.")
    return 1 if hits else 0
