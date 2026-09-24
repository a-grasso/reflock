"""Find the references a pin could bind to.

Not every link is pinnable. A pin binds to a *unit* of target text - a heading
section or a whole file - so links to directories, to anchors that do not
resolve, and to files reflock does not index are out. Asking the engine rather
than pattern-matching the markdown is what keeps this population identical to
the one `reflock check` reports on.
"""
from __future__ import annotations

import re

from reflock_lib.engine import parse_refs, resolve_target, unit_text
from reflock_lib.grammar import Index

LINK = re.compile(r"!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(([^)\s]+)[^)]*\)")


def link_sentence(context: str, target: str) -> str:
    """The one sentence carrying the link, which is all the model is shown."""
    flat = " ".join(context.split())
    for part in re.split(r"(?<=[.!?:])\s+(?=[A-Z(\[`])", flat):
        if target in part:
            return part
    return flat


def link_text(line: str, target: str) -> str:
    for m in LINK.finditer(line):
        if m.group(2) == target:
            return m.group(1).strip()
    return ""


def context_of(idx: Index, rel: str, line: int, window: int = 2) -> str:
    lines = idx.lines.get(rel) or []
    lo = max(0, line - 1 - window)
    return "\n".join(lines[lo:line + window])


def candidates(idx: Index, sources: list[str]) -> list[dict]:
    """Unpinned, whole-file markdown references into indexed text, as plain dicts.

    A reference that already names an anchor is left alone: someone narrowed
    it by hand, and that is a better answer than any the model has.
    """
    out = []
    for rel in sources:
        if not rel.endswith((".md", ".markdown")):
            continue
        for ref in parse_refs(idx, rel):
            if ref.kind != "md" or ref.pin is not None:
                continue
            kind, path, anchor, _ = resolve_target(idx, ref)
            if kind != "file" or anchor or path not in idx.lines:
                continue
            if unit_text(idx, path, None) is None:
                continue
            raw = idx.lines[rel][ref.line - 1]
            out.append({
                "file": rel,
                "line": ref.line,
                "col": ref.col,
                "target": ref.target,
                "target_path": path,
                "sentence": link_sentence(context_of(idx, rel, ref.line), ref.target),
                "link_text": link_text(raw, ref.target),
            })
    return out
