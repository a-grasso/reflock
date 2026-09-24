"""Does this link make a claim about its target, or only point at it?

A pin says "this sentence depends on what that text says". A navigation link -
a row of an index table, an entry under "See also" - depends on nothing but
the target existing, which `reflock check` already verifies without a pin. A
pin there fires on every edit of the target and is right never, which is how a
gate learns to be ignored.

This is shape, not meaning, on purpose: two cheap rules, measured against 585
references an LLM judge labelled on a real repository (kai-crm, 2026-09):

  * under a navigation heading  drops 203 not-worth-pinning,  27 worth it
  * index-table row             drops   4 not-worth-pinning,   0 worth it

Kept, 63% are worth a pin, against 42% before. Rules that looked promising
and were measured out: dropping short link-only list items (it took more
claims than navigation, since a principle list is a list of claims) and
exempting "supersedes"/annotated entries under navigation headings (it
restored four non-claims for every claim).
"""
from __future__ import annotations

import re

from reflock_lib.grammar import Index

# The whole heading, not a word in it: "References" and "Related work" name
# prose sections as often as link lists, and substring matching dropped
# claims wholesale.
NAV_HEADING = re.compile(
    r"(?:\d+[.)]?\s*)?(?:see also|related|related (?:docs|documents|documentation|reading"
    r"|pages|links|notes)|further reading|index|contents|table of contents|navigation"
    r"|reading order|start here|links|where to go next|next steps?)\s*:?",
    re.I)

LINK = re.compile(r"!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\([^)]*\)")


def section_title(idx: Index, rel: str, line: int) -> str:
    """Text of the nearest heading above `line` (1-based), bare."""
    title = ""
    lines = idx.lines.get(rel) or []
    for _slug, start, _level in idx.headings.get(rel, []):
        if start >= line - 1:
            break
        title = lines[start]
    return title.lstrip("#").strip().strip("*_ ").strip()


def index_row(raw: str, target: str) -> bool:
    """A table row whose first cell is the link itself - a catalogue entry."""
    s = raw.strip()
    if not s.startswith("|"):
        return False
    first = s.strip("|").split("|")[0]
    return target in first and len(LINK.sub("", first).split()) <= 2


def pin_worthy(idx: Index, ref: dict) -> bool:
    if NAV_HEADING.fullmatch(section_title(idx, ref["file"], ref["line"])):
        return False
    return not index_row(idx.lines[ref["file"]][ref["line"] - 1], ref["target"])
