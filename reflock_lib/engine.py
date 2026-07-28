"""The mechanical core: build an `Index` of a tree, parse references out of a
file, and resolve+classify a reference against the index. No model, no
network, no daemon - grep, a hashmap lookup, and a byte compare (DECISIONS.md
#5).
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import subprocess

from reflock_lib.grammar import (
    ANCHOR_END,
    ANCHOR_OPEN,
    CODE_REF,
    EXTERNAL,
    HEADING,
    MD_REF,
    PIN_STRIP,
    REF_DEF,
    WIKI_LINK,
    FP_LEN,
    Index,
    Ref,
)


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
    """Whitespace- and pin-invariant form for hashing.

    `" ".join(text.split())` rather than `re.sub(r"\\s+", " ", …).strip()`: the
    regex pass was the entire per-unit hashing cost (~0.14s for 4 MB, against
    ~5ms for the sha256 itself). str.split() collapses the same whitespace
    classes in C; a test asserts the two forms agree byte for byte, including on
    \\x1c-\\x1f, \\x85 and \\xa0, because a disagreement would silently invalidate
    every pin in the field.
    """
    return " ".join(PIN_STRIP.sub("", text).split()).encode("utf-8")


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalize(text)).hexdigest()[:FP_LEN]


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
        if os.path.islink(ap):
            # Indexed so it still resolves and fingerprints as a *target* -
            # reading through a link is what the author asked for. Excluded as a
            # source in scoped_files, because open(path, "w") writes through the
            # link and `stamp` would modify a file outside the tree (BUG-05).
            idx.symlinks.add(rel)
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
                                 wiki=(pat is WIKI_LINK), col=m.start()))
    # Patterns are applied in sequence, so a line carrying two *kinds* of
    # reference came out grouped by kind rather than left to right - invisible
    # for a single-kind line, since finditer is already left-to-right. Ordering
    # is owned here so every consumer inherits it: check and explain used to sort
    # differently and could list one line's references in different orders.
    refs.sort(key=lambda r: (r.line, r.col))
    return refs


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


def unit_text(idx: Index, path: str, anchor: str | None) -> str | None:
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


def unit_fingerprint(idx: Index, path: str, anchor: str | None) -> str | None:
    """Fingerprint of one unit, computed at most once per Index.

    The design is "many references, one authority", so the most-cited file in a
    tree is the one that was rehashed most: 400 references to a 4 MB file spent
    56s in classify(), all of it re-normalizing the same bytes.
    """
    key = (path, anchor)
    if key in idx.fps:
        return idx.fps[key]
    unit = unit_text(idx, path, anchor)
    fp = None if unit is None else fingerprint(unit)
    idx.fps[key] = fp
    return fp


def resolve_target(idx: Index, ref: Ref) -> tuple[str, str | None, str | None, str | None]:
    """Resolve ref.target down to (kind, path, anchor, detail).

    kind is one of 'external', 'outside', 'dir', 'dangling', 'file'. path and
    anchor are set only when kind == 'file'; detail explains a 'dangling'
    kind. Shared by classify (verdicts) and cmd_explain (display) so the two
    can't diverge on what a target resolves to.
    """
    tgt = ref.target
    if EXTERNAL.match(tgt) and not tgt.startswith("#"):
        return "external", None, None, None
    if tgt.startswith("#"):
        path, anchor = ref.src, tgt[1:]
    else:
        path_part, _, anchor = tgt.partition("#")
        anchor = anchor or None
        if ref.wiki:
            path, detail = resolve_wikilink(idx, ref.src, path_part)
            if path is None:
                return "dangling", None, None, detail
        else:
            path = resolve_path(ref.src, path_part)
            if path is None:
                return "outside", None, None, None
            if path not in idx.files:
                if path.rstrip("/") in idx.dirs:
                    return "dir", None, None, None
                return "dangling", None, None, f"no such file: {path}"
    return "file", path, anchor, None


def classify(idx: Index, ref: Ref) -> tuple[str, str]:
    """Return (verdict, detail)."""
    kind, path, anchor, detail = resolve_target(idx, ref)
    if kind == "external":
        return "OK", "external"
    if kind == "outside":
        return "OK", "outside tree"
    if kind == "dir":
        return "OK", "dir"
    if kind == "dangling":
        return "DANGLING", detail
    actual = unit_fingerprint(idx, path, anchor)
    if actual is None:
        return "DANGLING", f"no anchor '#{anchor}' in {path}"
    if ref.pin is None:
        return "OK", "unpinned"
    if ref.pin == "":
        if path not in idx.lines:
            # An indexed file with no text: `stamp` refuses to hash it (BUG-03),
            # so prescribing `reflock stamp` here would name a command that
            # provably does nothing.
            return "UNSTAMPED", f"cannot fingerprint: no indexed text in {path}"
        return "UNSTAMPED", "run: reflock stamp"
    if actual != ref.pin:
        return "DRIFTED", f"pinned @{ref.pin}, now @{actual}"
    return "OK", "pinned"


def locate_anchor(idx: Index, path: str, anchor: str) -> tuple[str, int, int] | tuple[None, None, None]:
    """Return (kind, start_line, end_line), 1-based inclusive, for a resolved anchor."""
    lines = idx.lines.get(path, [])
    for slug, start, level in idx.headings.get(path, []):
        if slug == anchor:
            end = len(lines)
            for s2, st2, lv2 in idx.headings[path]:
                if st2 > start and lv2 <= level:
                    end = st2
                    break
            return "heading", start + 1, end
    span = idx.spans.get(path, {}).get(anchor)
    if span:
        return "span", span[0] + 1, span[1]
    return None, None, None
