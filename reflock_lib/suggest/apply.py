"""Write the suggestions into the markdown.

Two edits per reference, both on its own line: `#anchor` appended to the link
target, and an empty `<!--@-->` pin after the link, which `reflock stamp` then
fills. Edits on a line are applied right to left, so earlier columns stay valid.

The edit is located with the parser's own match, not a second regex: the
column `parse_refs` reported is re-matched with the pattern that produced it,
on the same code-span-masked line. Afterwards the file is re-parsed, and if any
written reference is not seen by the engine as the opted-in pin it was meant to
be, the file is restored. A pin the checker cannot see is worse than none, so
disagreement between writer and parser fails loudly instead of landing.
"""
from __future__ import annotations

import collections
import os

from reflock_lib.engine import index_text, mask_code_spans, parse_refs, resolve_target, unit_text
from reflock_lib.grammar import MD_REF, REF_DEF, WIKI_LINK, Index

PIN = "<!--@-->"


def _edit(raw: str, col: int, target: str, anchor: str | None) -> str | None:
    """`raw` with one reference pinned (and narrowed), or None if it isn't there."""
    scan = mask_code_spans(raw)
    for pat in (MD_REF, WIKI_LINK, REF_DEF):
        m = pat.match(scan, col) if pat is not REF_DEF else pat.match(scan)
        if not m or m.start() != col or m.group("target") != target or m.group("pin") is not None:
            continue
        end = len(raw.rstrip()) if pat is REF_DEF else m.end()
        out = raw[:end] + PIN + raw[end:]
        if anchor:
            te = m.end("target")
            out = out[:te] + "#" + anchor + out[te:]
        return out
    return None


def apply(idx: Index, picks: list[tuple[dict, str | None]]) -> tuple[int, list[str]]:
    """picks: (candidate, anchor or None). Returns (written, skipped)."""
    by_file: dict[str, list[tuple[dict, str | None]]] = collections.defaultdict(list)
    for ref, anchor in picks:
        by_file[ref["file"]].append((ref, anchor))

    written, skipped = 0, []
    for rel, items in sorted(by_file.items()):
        lines = list(idx.lines[rel])
        done = []
        for ref, anchor in sorted(items, key=lambda t: (t[0]["line"], -t[0]["col"])):
            new = _edit(lines[ref["line"] - 1], ref["col"], ref["target"], anchor)
            if new is None:
                skipped.append("%s:%d" % (rel, ref["line"]))
                continue
            lines[ref["line"] - 1] = new
            done.append((ref, anchor))
        if not done:
            continue
        if not _engine_agrees(idx, rel, lines, done):
            skipped.extend("%s:%d" % (rel, r["line"]) for r, _ in done)
            continue
        path = os.path.join(idx.root, rel)
        with open(path, encoding="utf-8", newline="") as fh:
            original = fh.read()
        eol = "\r\n" if "\r\n" in original else "\n"
        text = eol.join(lines) + (eol if original.endswith(("\n", "\r")) else "")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        written += len(done)
    return written, skipped


def _engine_agrees(idx: Index, rel: str, lines: list[str], done) -> bool:
    """Whether the engine, reading the edited file, sees exactly the pins written."""
    probe = Index(root=idx.root, files=idx.files, dirs=idx.dirs, lines=dict(idx.lines),
                  headings=dict(idx.headings), spans=dict(idx.spans))
    index_text(probe, rel, "\n".join(lines))
    refs = {(r.line, r.target): r for r in parse_refs(probe, rel)}
    for ref, anchor in done:
        want = ref["target"] + ("#" + anchor if anchor else "")
        got = refs.get((ref["line"], want))
        if got is None or got.pin != "":
            return False
        kind, path, anc, _ = resolve_target(probe, got)
        if kind != "file" or path != ref["target_path"] or unit_text(probe, path, anc) is None:
            return False
    return True
