#!/usr/bin/env python3
"""Hold `reflock suggest`'s anchor path to laya's, reference by reference.

`reflock suggest` reimplements three things laya does with torch and
HuggingFace: the tokenizer (`reflock_lib/suggest/bpe.py`), the input layout
(`anchor.Anchorer.sequence`), and the forward pass (int8 ONNX instead of fp32
torch). Each could drift silently - a wrong token id still produces a
confident answer - so this runs every pinnable reference of a real repository
through both and compares:

  * the token sequence and marker positions, which must be identical;
  * the chosen option, which int8 may change only on near-ties;
  * the probability of the option laya chose.

    python3 suggest-model/parity.py --model ~/.cache/refpin/model \\
        --onnx /tmp/anchor ~/src/some-repo [more repos...]

Needs the same environment as export.py (torch, laya, onnxruntime).
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from reflock_lib.commands import scoped_files  # noqa: E402
from reflock_lib.engine import build_index  # noqa: E402
from reflock_lib.suggest import anchor as A  # noqa: E402
from reflock_lib.suggest.harvest import candidates  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True, help="fine-tuned laya checkpoint (torch)")
    ap.add_argument("--onnx", required=True, help="exported artifact directory")
    ap.add_argument("--min-agreement", type=float, default=0.97)
    ap.add_argument("repos", nargs="+")
    args = ap.parse_args()

    import laya
    from laya.common import build_sequence
    agent = laya.load(args.model, device="cpu")
    ours = A.Anchorer(args.onnx)

    n = same_ids = same_pick = 0
    worst = 0.0
    flips = []
    for repo in args.repos:
        idx = build_index(os.path.abspath(repo))
        for ref in candidates(idx, scoped_files(idx, [])):
            opts = A.options_for(idx, ref["target_path"])
            if not opts:
                continue
            crit = dict(opts)
            crit["none"] = A.WHOLE_DOC
            keys = list(crit)
            state = {"in_file": ref["file"], "link_text": ref["link_text"],
                     "target": ref["target"], "referring_text": ref["sentence"][:A.MAX_STATE]}
            q = {"type": "choice", "instructions": A.INSTRUCTIONS, "criteria": crit}

            want_seq = build_sequence(agent.tok, state, agent._to_internal(q),
                                      agent.cfg["max_len"], agent.cfg["head_max_len"])
            got_seq = ours.sequence(state, ["%s: %s" % kv for kv in crit.items()])
            same_ids += want_seq == (got_seq[0], got_seq[1])

            want = agent.system_one(state, {"a": q})["answers"]["a"]["probabilities"]
            got = ours.probabilities(state, ["%s: %s" % kv for kv in crit.items()])
            w_pick = max(keys, key=want.get)
            g_pick = keys[max(range(len(got)), key=got.__getitem__)]
            same_pick += w_pick == g_pick
            worst = max(worst, abs(want[w_pick] - got[keys.index(w_pick)]))
            if w_pick != g_pick:
                flips.append("%s:%d  laya %s %.3f  onnx %s %.3f" % (
                    ref["file"], ref["line"], w_pick, want[w_pick], g_pick, max(got)))
            n += 1
        print("%s: %d references" % (repo, n), file=sys.stderr)

    print("references         %d" % n)
    print("identical inputs   %d (%.1f%%)" % (same_ids, 100.0 * same_ids / n))
    print("same anchor        %d (%.1f%%)" % (same_pick, 100.0 * same_pick / n))
    print("worst p(laya pick) difference  %.3f" % worst)
    for f in flips:
        print("  flip  " + f)
    if same_ids != n or same_pick < args.min_agreement * n:
        sys.exit("parity: below the bar (inputs must be identical, "
                 "anchors must agree on >= %.0f%%)" % (100 * args.min_agreement))


if __name__ == "__main__":
    main()
