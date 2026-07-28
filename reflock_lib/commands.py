"""Subcommand implementations and their output renderers (human/JSON/GitHub
annotations). Each `cmd_*` is what a subparser's `fn` points at; each renders
through a format table so a new format is one function plus one entry, not a
new branch in every command.
"""
from __future__ import annotations

import json
import os
import sys

from reflock_lib.grammar import EXTERNAL, PATHISH, Index, Ref
from reflock_lib.engine import (
    classify,
    git_ignored,
    locate_anchor,
    mask_code_spans,
    parse_refs,
    resolve_path,
    resolve_target,
    resolve_wikilink,
    unit_fingerprint,
    unit_text,
)

BAD = {"DANGLING", "DRIFTED", "UNSTAMPED"}

VERDICT_COLOR = {
    "DANGLING": "\033[31m",   # red
    "DRIFTED": "\033[33m",    # yellow
    "UNSTAMPED": "\033[35m",  # magenta
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


def render_json(results, problems: int, args) -> int:
    print(json.dumps([{"verdict": v, "file": r.src, "line": r.line,
                       "target": r.target, "detail": d} for v, r, d in results], indent=2))
    return 1 if problems else 0


def render_human(results, problems: int, args) -> int:
    color = use_color(args)
    for v in ("DANGLING", "DRIFTED", "UNSTAMPED", "OK"):
        group = [(r, d) for vv, r, d in results if vv == v]
        if not group:
            continue
        print(f"\n{colorize(f'{v} ({len(group)})', v, color)}")
        for r, d in group:
            print(f"  {r.src}:{r.line}  {r.target}   [{d}]")
    msg = f"{problems} problem(s)." if problems else "All references OK."
    print(f"\n{colorize(msg, 'DANGLING' if problems else 'OK', color)}")
    return 1 if problems else 0


GITHUB_LEVEL = {"DANGLING": "error", "DRIFTED": "error", "UNSTAMPED": "warning"}


def github_escape_property(text: str) -> str:
    """Escape a workflow-command property value (e.g. file=, line=)."""
    return (text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                .replace(":", "%3A").replace(",", "%2C"))


def github_escape_message(text: str) -> str:
    """Escape workflow-command message data (no colon/comma escaping needed)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def render_github(results, problems: int, args) -> int:
    for v, r, d in results:
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


def render_error(message: str, fmt: str) -> None:
    """The one place a usage error becomes output, in whatever format the
    command's caller asked for - the error-path counterpart to RENDERERS.

    json/github land the error on stdout in their own shape, so a script or
    agent that requested a format gets something to parse even on failure;
    human keeps today's plain `error: <message>` line on stderr.
    """
    if fmt == "json":
        print(json.dumps({"error": message}))
    elif fmt == "github":
        print(f"::error::{github_escape_message(message)}")
    else:
        print(f"error: {message}", file=sys.stderr)


def cmd_check(idx: Index, args) -> int:
    try:
        fmt = resolve_format(args)
    except FormatConflict as e:
        render_error(str(e), intended_format(args))
        return 2
    if args.quiet and args.verbose:
        render_error("--quiet conflicts with --verbose", fmt)
        return 2
    results = []
    total = 0
    try:
        scoped = scoped_files(idx, args.paths)
    except ScopeError as e:
        render_error(str(e), fmt)
        return 2
    for rel in scoped:
        for ref in parse_refs(idx, rel):
            verdict, detail = classify(idx, ref)
            total += 1
            if verdict != "OK" or args.verbose:
                results.append((verdict, ref, detail))
    problems = sum(1 for v, _, _ in results if v in BAD)
    if args.quiet and fmt == "human":
        if problems:
            print(f"reflock: {problems} of {total} references failed", file=sys.stderr)
        return 1 if problems else 0
    return RENDERERS[fmt](results, problems, args)


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
        render_error("--warn requires --check", intended_format(args))
        return 2
    try:
        edits_by_rel, report = plan_stamp(idx, args)
    except ScopeError as e:
        render_error(str(e), intended_format(args))
        return 2
    if getattr(args, "check", False):
        for rel, ref, kind, fp in report:
            print(f"  {rel}:{ref.line}  {ref.target}   [{kind}]")
        if report:
            print(f"\n{len(report)} pin(s) would be stamped.")
            # --warn reports without judging: the exit code is the only
            # difference, so a pre-commit-framework hook can be advisory even
            # though pre-commit itself has no warn-only mode (D6).
            return 0 if warn else 1
        print("\nNothing to stamp.")
        return 0
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


def render_backlinks_human(rows, target: str, args) -> int:
    if not rows:
        print(f"No backlinks to {target}.")
        return 0
    for rel, line, tgt, pin in rows:
        print(f"{rel}:{line}  {tgt}  {pin}")
    print(f"\n{len(rows)} backlink(s).")
    return 0


def render_backlinks_json(rows, target: str, args) -> int:
    print(json.dumps([{"file": rel, "line": line, "target": tgt, "pin": pin}
                      for rel, line, tgt, pin in rows], indent=2))
    return 0


BACKLINKS_RENDERERS = {"human": render_backlinks_human, "json": render_backlinks_json}


def cmd_backlinks(idx: Index, args) -> int:
    try:
        fmt = resolve_format(args)
    except FormatConflict as e:
        render_error(str(e), intended_format(args))
        return 2
    arg_path, _, target_anchor = args.path.partition("#")
    target_anchor = target_anchor or None
    target_path = indexed_path(idx, arg_path)
    if target_path is None:
        render_error(f"no such file in index: {arg_path}", fmt)
        return 2
    if target_anchor is not None and locate_anchor(idx, target_path, target_anchor)[0] is None:
        # Same reasoning as the missing-file case: "nothing points at this
        # section" is the answer you act on before editing that section, so a
        # misspelled anchor must not be able to produce it.
        render_error(f"no anchor '#{target_anchor}' in {target_path}", fmt)
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
    return BACKLINKS_RENDERERS[fmt](rows, target_path, args)


def explain_entry(idx: Index, ref: Ref) -> dict:
    verdict, detail = classify(idx, ref)
    kind, path, anchor, _ = resolve_target(idx, ref)
    entry = {"file": ref.src, "line": ref.line, "target": ref.target, "verdict": verdict,
              "detail": detail, "resolves_to": None, "anchor": None, "pin": None, "current": None,
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


def render_explain_human(entries, args) -> int:
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


def render_explain_json(entries, args) -> int:
    print(json.dumps([{k: v for k, v in e.items() if k != "unit_text"} for e in entries], indent=2))
    return 1 if any(e["verdict"] in BAD for e in entries) else 0


EXPLAIN_RENDERERS = {"human": render_explain_human, "json": render_explain_json}


def cmd_explain(idx: Index, args) -> int:
    try:
        fmt = resolve_format(args)
    except FormatConflict as e:
        render_error(str(e), intended_format(args))
        return 2
    file_part, sep, line_part = args.spec.rpartition(":")
    if not sep or not line_part.isdigit() or int(line_part) < 1:
        render_error(f"invalid <file>:<line> spec: {args.spec}", fmt)
        return 2
    lineno = int(line_part)
    rel = indexed_path(idx, file_part)
    if rel is None:
        render_error(f"no such file in index: {file_part}", fmt)
        return 2
    lines = idx.lines.get(rel)
    if lines is None or lineno > len(lines):
        render_error(f"{rel} has no line {lineno}", fmt)
        return 2
    refs = [r for r in parse_refs(idx, rel) if r.line == lineno]  # parse_refs owns the order
    if not refs:
        render_error(f"no reference on {rel}:{lineno}", fmt)
        return 2
    entries = [explain_entry(idx, r) for r in refs]
    return EXPLAIN_RENDERERS[fmt](entries, args)


def cmd_suspects(idx: Index, args) -> int:
    # Pass 1: collect path-shaped tokens that resolve to nothing.
    candidates = []  # (rel, lineno, token, [paths to test against .gitignore])
    try:
        scoped = scoped_files(idx, args.paths)
    except ScopeError as e:
        render_error(str(e), intended_format(args))
        return 2
    for rel in scoped:
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
            scan = mask_code_spans(ln) if is_md else ln
            for m in PATHISH.finditer(scan):
                tok = m.group("p")
                if any(tok in t for t in refd):
                    continue
                rp = resolve_path(rel, tok)
                if rp and (rp in idx.files or rp.rstrip("/") in idx.dirs):
                    continue
                if tok in idx.files or tok.rstrip("/") in idx.dirs:
                    continue
                candidates.append((rel, i + 1, tok, [c for c in (rp, tok) if c]))
    # Pass 2: a path git would ignore is intentionally absent, not a stale ref.
    ignored = git_ignored(idx.root, sorted({c for *_, cs in candidates for c in cs}))
    hits = [(rel, lineno, tok) for rel, lineno, tok, cands in candidates
            if not any(c in ignored for c in cands)]
    if args.json:
        print(json.dumps([{"file": rel, "line": lineno, "target": tok}
                          for rel, lineno, tok in hits], indent=2))
    else:
        for rel, lineno, tok in hits:
            print(f"  {rel}:{lineno}  {tok}   [bare path, does not resolve]")
        print(f"\n{len(hits)} suspect(s)." if hits else "\nNo bare-path suspects.")
    return 1 if hits else 0
