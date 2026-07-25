#!/usr/bin/env python3
"""reflock — a lockfile for cross-references.

Referential integrity for a mixed docs+code tree. reflock finds every
reference, resolves it against a target index, and — for *pinned* references —
compares a content fingerprint of the target's smallest anchored unit against
the value recorded when the reference was last blessed.

The design invariant: the mechanical layer runs always and is free; a semantic
(human or LLM) layer runs rarely and only on what drifts. There is no model in
the hot path — everything here is grep, a hashmap lookup, and a byte compare.

Reference surface forms
-----------------------
  Markdown link (optionally pinned):
      [text](relative/path.md#anchor)<!--@a1b2c3d4-->
      [text](relative/path.md#anchor)<!--@-->        # opt-in, not yet stamped
      [text](relative/path.md#anchor).<!--@a1b2c3d4-->  # sentence punctuation
                                                        # before the pin is fine

  REF comment (any text or code file):
      # REF: relative/path.kt#Symbol @a1b2c3d4
      // REF: ../doc/adr/0011-....md#decision @-

A target is `path` or `path#anchor`, `path` resolved relative to the file the
reference lives in. An anchor resolves to a markdown heading slug, or to an
explicit `reflock-anchor: <name>` ... `reflock-anchor-end: <name>` span in any
file. With no anchor, the unit is the whole file.

Verdicts
--------
  OK          resolves; fingerprint matches (or the reference is unpinned)
  DANGLING    path / anchor / span does not resolve
  DRIFTED     resolves, but the target changed since the pin was blessed
  UNSTAMPED   opted into pinning (`@`) but never stamped

Commands
--------
  reflock check     [paths...]     report; exit 1 on any problem
  reflock stamp     [paths...]     fill empty pins (--rebless: re-hash all)
  reflock suspects  [paths...]     path-shaped prose that doesn't resolve
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

__version__ = "0.1.4"

FP_LEN = 8  # hex chars of sha256; 32 bits — a missed drift is ~1 in 4e9

# --- reference grammar -------------------------------------------------------
# A markdown link, with an optional trailing pin comment. The pin's hex is its
# own group so `stamp` can splice it in place (empty group == opted-in, unstamped).
MD_REF = re.compile(
    r"\[[^\]]*\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"(?:[\s.,;:!?]*<!--@(?P<pin>[0-9a-f]*)-->)?"
)
# A REF comment: a comment opener, then `REF: target`, optional ` @hex`.
# The opener requirement keeps `REF:` inside prose or string literals from matching.
CODE_REF = re.compile(
    r"(?:#|//|/\*|<!--|--|;|\*)\s*REF:\s*(?P<target>[^\s@]+)(?:\s+@(?P<pin>[0-9a-f]*))?"
)
# A reference-style link *definition* - `[id]: target "title"`. The pin lives
# here, on the definition line, since a definition names its target exactly
# once while usages (`[text][id]`, `[id][]`, the unsupported shortcut `[id]`)
# may repeat it many times.
REF_DEF = re.compile(
    r'^\s*\[[^\]]+\]:\s+(?P<target>\S+?)(?:\s+"[^"]*")?'
    r"(?:\s*<!--@(?P<pin>[0-9a-f]*)-->)?\s*$"
)
# A wiki-link: [[target]], [[target#anchor]], [[target|alias]], or both.
# Alias is display text and split off at the first `|` only.
WIKI_LINK = re.compile(
    r"\[\[(?P<target>[^\]|]+?)(?:\|[^\]]*)?\]\]"
    r"(?:[\s.,;:!?]*<!--@(?P<pin>[0-9a-f]*)-->)?"
)
ANCHOR_OPEN = re.compile(r"reflock-anchor:\s*(?P<name>[\w.\-/]+)")
ANCHOR_END = re.compile(r"reflock-anchor-end:\s*(?P<name>[\w.\-/]+)")
HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
# A path-shaped token for the `suspects` heuristic: has a slash and an extension.
PATHISH = re.compile(
    r"(?<![\w./])(?P<p>(?:\.\.?/)?(?:[\w.\-]+/)+[\w.\-]+\.[A-Za-z][A-Za-z0-9]{0,5})"
)
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.\-]*:|//|#)")  # url scheme, //, or same-page #
PIN_STRIP = re.compile(r"<!--@[0-9a-f]*-->|(?<=@)[0-9a-f]{%d}\b" % FP_LEN)


@dataclass
class Ref:
    src: str          # repo-relative path of the referring file
    line: int         # 1-based
    kind: str         # 'md' | 'code'
    target: str       # raw target string
    pin: str | None   # None=unpinned, ''=opted-in-unstamped, hex=pinned
    pin_span: tuple[int, int] | None  # (start,end) of hex within the source line
    wiki: bool = False  # True for [[wiki-link]] targets - enables basename fallback (D4)


@dataclass
class Index:
    root: str
    files: set[str] = field(default_factory=set)
    dirs: set[str] = field(default_factory=set)
    lines: dict[str, list[str]] = field(default_factory=dict)
    # path -> list of (slug, start_line0, level) in document order
    headings: dict[str, list[tuple[str, int, int]]] = field(default_factory=dict)
    # path -> {name: (start_line0, end_line0)}  span is exclusive of markers
    spans: dict[str, dict[str, tuple[int, int]]] = field(default_factory=dict)
    ignored: set[str] = field(default_factory=set)  # scanned as targets, not as sources


# --- helpers -----------------------------------------------------------------
def run(cmd: list[str], cwd: str) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).stdout


def git_ignored(root: str, paths: list[str]) -> set[str]:
    """Subset of paths git would ignore — i.e. intentionally absent, not stale."""
    if not paths:
        return set()
    try:
        out = subprocess.run(["git", "check-ignore", "--stdin", "-z"], cwd=root,
                             input="\0".join(paths), capture_output=True, text=True).stdout
    except OSError:
        return set()
    return {p for p in out.split("\0") if p}


def repo_root(start: str) -> str:
    top = run(["git", "rev-parse", "--show-toplevel"], start).strip()
    return top or os.path.abspath(start)


def list_files(root: str) -> list[str]:
    """Tracked plus untracked-not-ignored files, so .gitignore is honoured for free."""
    out = run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], root)
    if out:
        rels = [p for p in out.split("\0") if p]
    else:  # not a git repo — walk, skipping the usual noise
        skip = {".git", "node_modules", "target", "build", "dist", ".venv", "__pycache__"}
        rels = []
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in skip]
            for fn in fns:
                rels.append(os.path.relpath(os.path.join(dp, fn), root))
    paths = (p.replace(os.sep, "/") for p in rels)
    return sorted(p for p in paths
                  if not any(seg in (".git", "node_modules") for seg in p.split("/")))


def read_reflockignore(root: str) -> list[str]:
    """fnmatch globs (repo-relative) for files to skip as *sources* of references."""
    p = os.path.join(root, ".reflockignore")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as fh:
        return [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]


def is_text(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\0" not in fh.read(4096)
    except OSError:
        return False


def slugify(text: str) -> str:
    """GitHub-style heading slug for typical headings."""
    # Reduce `[t](u)` -> `t` only outside code spans: inside backticks, link
    # syntax is literal text and GitHub slugs it verbatim. Odd indices are the
    # captured spans, whose contents are kept but never re-parsed.
    parts = re.split(r"(`[^`]*`)", text)
    for i, p in enumerate(parts):
        parts[i] = p[1:-1] if i % 2 else re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", p)
    s = "".join(parts)
    s = re.sub(r"[*_~]", "", s)                     # emphasis markers
    s = s.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s, flags=re.UNICODE)
    s = s.replace(" ", "-")  # per-space, no collapse - GitHub keeps consecutive hyphens
    return s


def normalize(text: str) -> bytes:
    """Whitespace- and pin-invariant form for hashing."""
    text = PIN_STRIP.sub("", text)
    return re.sub(r"\s+", " ", text).strip().encode("utf-8")


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalize(text)).hexdigest()[:FP_LEN]


# --- indexing ----------------------------------------------------------------
def build_index(root: str) -> Index:
    idx = Index(root=root)
    ignore_patterns = read_reflockignore(root)
    for rel in list_files(root):
        ap = os.path.join(root, rel)
        if not os.path.isfile(ap):
            continue
        idx.files.add(rel)
        if any(fnmatch.fnmatch(rel, p) for p in ignore_patterns):
            idx.ignored.add(rel)
        parts = rel.split("/")
        for i in range(1, len(parts)):
            idx.dirs.add("/".join(parts[:i]))
        if not is_text(ap):
            continue
        with open(ap, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        idx.lines[rel] = lines
        if rel.endswith((".md", ".markdown")):
            hs, seen = [], {}
            in_fence = False
            for i, ln in enumerate(lines):
                if ln.lstrip().startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                m = HEADING.match(ln)
                if m:
                    slug = slugify(m.group("text"))
                    n = seen.get(slug, 0)
                    seen[slug] = n + 1
                    hs.append((slug if n == 0 else f"{slug}-{n}", i, len(m.group("hashes"))))
            idx.headings[rel] = hs
        # explicit anchor spans (any file type)
        spans, open_at = {}, {}
        for i, ln in enumerate(lines):
            mo = ANCHOR_OPEN.search(ln)
            if mo:
                open_at[mo.group("name")] = i
            me = ANCHOR_END.search(ln)
            if me and me.group("name") in open_at:
                spans[me.group("name")] = (open_at.pop(me.group("name")) + 1, i)
        if spans:
            idx.spans[rel] = spans
    return idx


def mask_code_spans(line: str) -> str:
    """Blank out inline backtick spans, same-length, so offsets are unaffected.

    A markdown renderer treats span content as literal text, so it must not be
    parsed for references - the same reasoning already applied to fenced
    blocks. An unterminated backtick has no matching close and is left as-is,
    so it cannot silence the rest of the line.
    """
    out = []
    i, n = 0, len(line)
    while i < n:
        if line[i] == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            ticks = j - i
            close = line.find("`" * ticks, j)
            if close != -1:
                end = close + ticks
                out.append("\0" * (end - i))
                i = end
                continue
        out.append(line[i])
        i += 1
    return "".join(out)


def parse_refs(idx: Index, rel: str) -> list[Ref]:
    refs: list[Ref] = []
    is_md = rel.endswith((".md", ".markdown"))
    in_fence = False
    for i, ln in enumerate(idx.lines.get(rel, [])):
        if is_md and ln.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:  # illustrative refs in fenced code aren't real references
            continue
        # Inline code spans are exempt on the same basis as fenced blocks;
        # masking (not stripping) keeps every other match's column correct.
        scan = mask_code_spans(ln) if is_md else ln
        patterns = [(MD_REF, "md"), (REF_DEF, "md"), (WIKI_LINK, "md")] if is_md else []
        patterns.append((CODE_REF, "code"))
        for pat, kind in patterns:
            for m in pat.finditer(scan):
                pin = m.group("pin")
                span = m.span("pin") if pin is not None else None
                refs.append(Ref(rel, i + 1, kind, m.group("target"), pin, span,
                                 wiki=(pat is WIKI_LINK)))
    return refs


# --- resolution --------------------------------------------------------------
def resolve_path(src: str, target: str) -> str | None:
    base = os.path.dirname(src)
    p = os.path.normpath(os.path.join(base, target)).replace(os.sep, "/")
    return None if p.startswith("..") else p


def resolve_wikilink(idx: Index, src: str, path_part: str) -> tuple[str | None, str | None]:
    """Relative-first, then unique-basename resolution for wiki-links (D4).

    Returns (path, detail); detail is set only when path is None, for the
    DANGLING message (plain no-match vs. ambiguous basename).
    """
    candidate = path_part if os.path.splitext(path_part)[1] else path_part + ".md"
    rel = resolve_path(src, candidate)
    if rel is not None and rel in idx.files:
        return rel, None
    base = os.path.basename(candidate)
    matches = sorted(f for f in idx.files if os.path.basename(f) == base)
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, f"ambiguous: {', '.join(matches)}"
    return None, f"no such file: {path_part}"


def unit_text(idx: Index, path: str, anchor: str | None) -> str | list | None:
    """Return the target unit's text, or None if the anchor doesn't resolve."""
    lines = idx.lines.get(path)
    if lines is None:
        return ""  # binary/unreadable file that exists — treat as empty unit
    if not anchor:
        return "\n".join(lines)
    for slug, start, level in idx.headings.get(path, []):
        if slug == anchor:
            end = len(lines)
            for s2, st2, lv2 in idx.headings[path]:
                if st2 > start and lv2 <= level:
                    end = st2
                    break
            return "\n".join(lines[start:end])
    span = idx.spans.get(path, {}).get(anchor)
    if span:
        return "\n".join(lines[span[0]:span[1]])
    return None


def classify(idx: Index, ref: Ref) -> tuple[str, str]:
    """Return (verdict, detail)."""
    tgt = ref.target
    if EXTERNAL.match(tgt) and not tgt.startswith("#"):
        return "OK", "external"
    if tgt.startswith("#"):
        path, anchor = ref.src, tgt[1:]
    else:
        path_part, _, anchor = tgt.partition("#")
        anchor = anchor or None
        if ref.wiki:
            path, detail = resolve_wikilink(idx, ref.src, path_part)
            if path is None:
                return "DANGLING", detail
        else:
            path = resolve_path(ref.src, path_part)
            if path is None:
                return "OK", "outside tree"
            if path not in idx.files:
                if path.rstrip("/") in idx.dirs:
                    return "OK", "dir"
                return "DANGLING", f"no such file: {path}"
    unit = unit_text(idx, path, anchor)
    if unit is None:
        return "DANGLING", f"no anchor '#{anchor}' in {path}"
    if ref.pin is None:
        return "OK", "unpinned"
    if ref.pin == "":
        return "UNSTAMPED", "run: reflock stamp"
    actual = fingerprint(unit)
    if actual != ref.pin:
        return "DRIFTED", f"pinned @{ref.pin}, now @{actual}"
    return "OK", "pinned"


# --- commands ----------------------------------------------------------------
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


def scoped_files(idx: Index, paths: list[str]) -> list[str]:
    if not paths:
        return sorted(f for f in idx.files if f in idx.lines and f not in idx.ignored)
    want = {os.path.normpath(os.path.relpath(os.path.abspath(p), idx.root)).replace(os.sep, "/")
            for p in paths}
    return sorted(f for f in idx.files if f in idx.lines and f not in idx.ignored
                  and (f in want or any(f.startswith(w + "/") for w in want)))


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


RENDERERS = {"human": render_human, "json": render_json}


class FormatConflict(Exception):
    pass


def resolve_format(args) -> str:
    """--json and --format may agree; if they disagree, that is an error, not
    a silent pick between the two."""
    fmt = getattr(args, "format", None) or "human"
    if getattr(args, "json", False):
        if args.format and args.format != "json":
            raise FormatConflict(
                f"error: --json conflicts with --format {args.format} "
                f"(--json implies --format json)")
        fmt = "json"
    return fmt


def cmd_check(idx: Index, args) -> int:
    try:
        fmt = resolve_format(args)
    except FormatConflict as e:
        print(e, file=sys.stderr)
        return 2
    if args.quiet and args.verbose:
        print("error: --quiet conflicts with --verbose", file=sys.stderr)
        return 2
    results = []
    total = 0
    for rel in scoped_files(idx, args.paths):
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
            verdict, _ = classify(idx, ref)
            if verdict == "DANGLING":
                continue
            path_part, _, anchor = ref.target.partition("#")
            if ref.target.startswith("#"):
                path = ref.src
            elif ref.wiki:
                path, _ = resolve_wikilink(idx, ref.src, path_part)
            else:
                path = resolve_path(ref.src, path_part)
            unit = unit_text(idx, path, (ref.target[1:] if ref.target.startswith("#") else anchor) or None)
            fp = fingerprint(unit)
            if fp != ref.pin:
                kind = "unstamped" if ref.pin == "" else "stale"
                edits_by_rel.setdefault(rel, {}).setdefault(ref.line - 1, []).append((*ref.pin_span, fp))
                report.append((rel, ref, kind, fp))
    return edits_by_rel, report


def cmd_stamp(idx: Index, args) -> int:
    edits_by_rel, report = plan_stamp(idx, args)
    if getattr(args, "check", False):
        for rel, ref, kind, fp in report:
            print(f"  {rel}:{ref.line}  {ref.target}   [{kind}]")
        if report:
            print(f"\n{len(report)} pin(s) would be stamped.")
            return 1
        print("\nNothing to stamp.")
        return 0
    changed = 0
    for rel, edits in edits_by_rel.items():
        lines = idx.lines[rel]
        for lineno, splices in edits.items():
            ln = lines[lineno]
            for s, e, fp in sorted(splices, reverse=True):
                ln = ln[:s] + fp + ln[e:]
            lines[lineno] = ln
            changed += len(splices)
        with open(os.path.join(idx.root, rel), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print(f"Stamped {changed} pin(s).")
    return 0


def render_backlinks_human(rows, target: str, args) -> int:
    if not rows:
        print(f"No backlinks to {target}.")
        return 0
    for rel, line, tgt, pin in rows:
        print(f"{rel}:{line}  {tgt}  {pin}")
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
        print(e, file=sys.stderr)
        return 2
    target_path, _, target_anchor = args.path.partition("#")
    target_anchor = target_anchor or None
    if target_path not in idx.files:
        print(f"error: no such file in index: {target_path}", file=sys.stderr)
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


def cmd_suspects(idx: Index, args) -> int:
    # Pass 1: collect path-shaped tokens that resolve to nothing.
    candidates = []  # (rel, lineno, token, [paths to test against .gitignore])
    for rel in scoped_files(idx, args.paths):
        if not args.all and not rel.endswith((".md", ".markdown")):
            continue
        refd = {r.target for r in parse_refs(idx, rel)}
        in_fence = False
        for i, ln in enumerate(idx.lines[rel]):
            if ln.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for m in PATHISH.finditer(ln):
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
    comp = sub.add_parser("completion", help="print a shell completion script")
    comp.add_argument("shell", choices=COMPLETION_SHELLS)
    comp.set_defaults(fn=cmd_completion, needs_index=False)
    return ap


def parser_spec() -> dict[str, list[str]]:
    """subcommand name -> sorted long/short flags, walked off the live parser.

    Used both to generate the completion scripts and, in tests, to assert they
    stay in parity with the parser - so a new subcommand or flag can't go
    stale in the shipped scripts without a test failing.
    """
    ap = build_parser()
    sub_action = next(a for a in ap._subparsers._group_actions
                       if isinstance(a, argparse._SubParsersAction))
    spec = {}
    for name, subparser in sub_action.choices.items():
        flags = sorted({opt for action in subparser._actions
                         for opt in action.option_strings if opt != "-h" and opt != "--help"})
        spec[name] = flags
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
            flags = " ".join(spec[name])
            lines.append(f'        {name}) COMPREPLY=( $(compgen -W "{flags}" -- "$cur") ) ;;')
        lines += [
            "    esac",
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
            flags = " ".join(f'"{f}"' for f in spec[name])
            lines.append(f"        {name}) _arguments {flags} '*:file:_files' ;;")
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
            for flag in spec[name]:
                opt = "-l " + flag[2:] if flag.startswith("--") else "-s " + flag[1:]
                lines.append(
                    f'complete -c reflock -n "__fish_seen_subcommand_from {name}" '
                    f'{opt}  # {flag}'
                )
            lines.append(
                f'complete -c reflock -n "__fish_seen_subcommand_from {name}" -a "(__fish_complete_path)"'
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
    return args.fn(build_index(root), args)


if __name__ == "__main__":
    sys.exit(main())
