"""Ask the anchor model which section of the target a reference is about.

One typed `choice` question per reference, one forward pass, nothing
generated - so nothing to parse and nothing to hallucinate. The options are
built per call from that target's own headings, so every reference is scored
against its own document rather than a fixed label set; that is the property
the design rests on.

The model is a fine-tuned laya checkpoint, and this module reproduces laya's
own input format rather than importing laya (which would bring torch):

    [CLS] choice question: <instructions> [SEP] [MASK] opt0 [MASK] opt1 ... [SEP] <state> [SEP]

The logit read at each `[MASK]` scores that option. `suggest-model/parity.py`
holds this rendering to laya's, decision for decision.

`none` is always an option and is a real answer: about a quarter of references
are about a document as a whole and should stay unanchored.
"""
from __future__ import annotations

import json
import math
import os

from reflock_lib.grammar import Index

INSTRUCTIONS = ("Which section of the target document is the referring text's "
                "claim about - the section that, if it changed, would make the "
                "text wrong?")

MAX_OPTIONS = 24       # headings offered; the 192-token option head fits them
MAX_DESC = 60          # characters of heading text per option
MAX_STATE = 900        # characters of referring sentence
OPTION_TOKENS = 48     # laya's per-option token cap
WHOLE_DOC = "the claim is about the document as a whole"


def options_for(idx: Index, target_path: str) -> dict[str, str]:
    """`slug -> "## Heading text"` for one target, in document order."""
    out: dict[str, str] = {}
    lines = idx.lines.get(target_path) or []
    for slug, start, level in idx.headings.get(target_path, []):
        text = lines[start].lstrip("#").strip() if start < len(lines) else slug
        out.setdefault(slug, ("#" * level + " " + text)[:MAX_DESC])
        if len(out) >= MAX_OPTIONS:
            break
    return out


def spans_whole_file(idx: Index, path: str, slug: str) -> bool:
    """Whether `#slug` would pin the whole file while reporting a section.

    A document's title heading runs from the title to the end of the file,
    because nothing after it is at its level. Anchoring to it narrows nothing
    and tells the reader of the diff that it did, so it is refused - the
    reference stays whole-file, which is what it effectively was.
    """
    hs = idx.headings.get(path, [])
    if not hs or hs[0][0] != slug:
        return False
    _, start, level = hs[0]
    return all(lv > level for _, _, lv in hs[1:])


class Anchorer:
    """laya's `choice` head over ONNX Runtime."""

    def __init__(self, model_dir: str):
        from reflock_lib.suggest.bpe import Tokenizer
        from reflock_lib.suggest.runtime import Session

        with open(os.path.join(model_dir, "config.json"), encoding="utf-8") as fh:
            self.cfg = json.load(fh)
        self.tok = Tokenizer(os.path.join(model_dir, "tokenizer.json"))
        self.session = Session(os.path.join(model_dir, "anchor.onnx"))
        t = self.cfg["tokens"]
        self.cls, self.sep, self.mask, self.mask_text = t["cls"], t["sep"], t["mask"], t["mask_text"]
        self.head_ids = self.tok.encode(
            "choice question: " + INSTRUCTIONS.replace(self.mask_text, " "))

    def sequence(self, state: dict, options: list[str]) -> tuple[list[int], list[int]]:
        """Token ids and `[MASK]` positions, exactly as laya's build_sequence lays them out."""
        max_len, head_max = self.cfg["max_len"], self.cfg["head_max_len"]
        opt_ids = [[self.mask] + self.tok.encode(" " + o.replace(self.mask_text, " "))[:OPTION_TOKENS]
                   for o in options]
        budget = head_max - sum(len(o) for o in opt_ids)
        if budget < 16:
            per = max(4, (head_max - 16) // max(1, len(opt_ids)))
            opt_ids = [o[:per] for o in opt_ids]
            budget = head_max - sum(len(o) for o in opt_ids)
        ids = [self.cls] + self.head_ids[:max(8, budget)] + [self.sep]
        markers = []
        for o in opt_ids:
            markers.append(len(ids))
            ids.extend(o)
        ids.append(self.sep)
        room = max(0, max_len - len(ids) - 1)
        text = json.dumps(state, ensure_ascii=False).replace(self.mask_text, " ")
        ids = ids + self.tok.encode(text)[:room] + [self.sep]
        return ids[:max_len], [m for m in markers if m < max_len]

    def probabilities(self, state: dict, options: list[str]) -> list[float]:
        ids, markers = self.sequence(state, options)
        if len(markers) != len(options):
            raise ValueError("options exceed the model's option budget")
        logits = self.session.logits(ids, markers)
        k = len(markers)
        t = self.cfg["temperature_by_options"].get(_bucket(k), self.cfg["temperature"][0])
        z = [x / t for x in logits[:k]]
        top = max(z)
        e = [math.exp(x - top) for x in z]
        s = sum(e)
        return [x / s for x in e]

    def anchor(self, idx: Index, ref: dict) -> tuple[str | None, float]:
        """(slug or None, confidence). None leaves the link whole-file."""
        opts = options_for(idx, ref["target_path"])
        if not opts:
            return None, 0.0
        crit = dict(opts)
        crit["none"] = WHOLE_DOC
        keys = list(crit)
        state = {"in_file": ref["file"], "link_text": ref["link_text"],
                 "target": ref["target"], "referring_text": ref["sentence"][:MAX_STATE]}
        p = self.probabilities(state, ["%s: %s" % (k, v) for k, v in crit.items()])
        best = max(range(len(p)), key=p.__getitem__)
        pick, conf = keys[best], confidence(p)
        if pick == "none" or spans_whole_file(idx, ref["target_path"], pick):
            return None, conf
        return pick, conf


def _bucket(k: int) -> str:
    return "choice:" + ("2" if k <= 2 else "3-5" if k <= 5 else "6-10" if k <= 10 else "11+")


def confidence(p: list[float]) -> float:
    """laya's calibrated confidence: 1 - H(p) / log(k)."""
    k = len(p)
    if k < 2:
        return 1.0
    h = -sum(x * math.log(min(max(x, 1e-12), 1.0)) for x in p)
    return min(1.0, max(0.0, 1.0 - h / math.log(k)))
