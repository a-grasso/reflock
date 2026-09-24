#!/usr/bin/env python3
"""Export a fine-tuned laya checkpoint to the int8 ONNX artifact `reflock suggest` runs.

A maintainer tool, not part of reflock: it needs torch, transformers and laya,
none of which a reflock user ever installs. Run it from an environment that has
them (`pip install laya onnx onnxruntime onnxscript`), then publish the output
directory with `publish.py`.

    python3 suggest-model/export.py --model ~/.cache/refpin/model --out /tmp/anchor

Three things here are load-bearing, and each was learned by breaking it:

  * **opset 18 is a floor.** At 17 the export completes and onnxruntime then
    rejects the graph, because `Split` only gains `num_outputs` at 18.
  * **Only the logits are exported.** laya's forward also computes an action
    head whose `p.size(-1) >= 2` branch Python evaluates once, at trace time,
    and bakes in. `suggest` never reads that head, so the wrapper below drops
    it rather than shipping a graph that is right only for the traced shape.
  * **8-bit weights, fp32 activations.** The fp32 weights are 1.6 GB, and the
    artifact must stay under 500 MB to be a tolerable first-run download.
    `quantize_dynamic` gets there by quantising *activations* to int8 too, and
    that broke the model: on 246 real references it made laya's pick only 77%
    of the time, worst probability gap 0.85. Weight-only 8-bit (`MatMulNBits`,
    block 32, symmetric) keeps activations in fp32 and agrees on 99.2%, worst
    gap 0.05. The token embedding, which that quantiser leaves at 206 MB of
    fp32, is stored as int8 rows with one fp32 scale each (`_embedding_int8`).

The marker axis (`k`, one position per option) must stay dynamic: every
reference is scored against its own target's headings, so the option count
changes per call. `verify()` checks exactly that, on option counts and sequence
lengths the trace never saw.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

import numpy as np
import torch

OPSET = 18
MAX_BYTES = 500 * 10**6        # first-run download budget
NAMES = ["input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype"]


class LogitsOnly(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype):
        return self.model(input_ids, attention_mask, marker_pos, marker_mask, qtype)[0]


def example(T, K, qtype=0, seed=0):
    g = torch.Generator().manual_seed(seed)
    return (
        torch.randint(1000, 2000, (1, T), generator=g),
        torch.ones(1, T, dtype=torch.long),
        torch.arange(2, 2 + K).unsqueeze(0),
        torch.ones(1, K, dtype=torch.bool),
        torch.full((1,), qtype, dtype=torch.long),
    )


def export(model, path):
    # The torch.export-based exporter, not the legacy TorchScript tracer: the
    # tracer bakes the traced sequence length into the decision head's
    # attention reshape, so the graph runs at exactly one input length.
    dyn = {"input_ids": {0: "b", 1: "t"}, "attention_mask": {0: "b", 1: "t"},
           "marker_pos": {0: "b", 1: "k"}, "marker_mask": {0: "b", 1: "k"},
           "qtype": {0: "b"}, "logits": {0: "b", 1: "k"}}
    torch.onnx.export(LogitsOnly(model).eval(), example(64, 5), path, input_names=NAMES,
                      output_names=["logits"], dynamic_axes=dyn, opset_version=OPSET,
                      do_constant_folding=True, dynamo=True)


def quantize(src, dst):
    import onnx
    from onnxruntime.quantization.matmul_nbits_quantizer import MatMulNBitsQuantizer
    q = MatMulNBitsQuantizer(onnx.load(src), bits=8, block_size=32, is_symmetric=True,
                             accuracy_level=0)      # 0: dequantise, compute in fp32
    q.process()
    model = q.model.model
    _embedding_int8(model)
    onnx.save_model(model, dst)


EMBED_BLOCK = 32


def _embedding_int8(model):
    """Replace the fp32 token-embedding table with int8 blocks and fp32 scales.

    Each token's vector is cut into blocks of EMBED_BLOCK values, each with its
    own scale S = max|block| / 127 and Q = round(W / S), so an outlier costs
    precision only inside its own block. One scale per whole row agreed with
    laya 1.6 points less often (97.6% against 99.2%); blocks cost 6 MB.
    Gather(W, ids) becomes Gather(Q, ids) * Gather(S, ids), reshaped by block.
    """
    from onnx import TensorProto, helper, numpy_helper
    g = model.graph
    inits = {t.name: t for t in g.initializer}
    gathers = [n for n in g.node if n.op_type == "Gather" and n.input[0] in inits
               and len(inits[n.input[0]].dims) == 2]
    table = max(gathers, key=lambda n: inits[n.input[0]].dims[0])
    name = table.input[0]
    if [n for n in g.node if name in n.input] != [table]:
        raise SystemExit("export: %s is read by more than the embedding Gather" % name)
    w = numpy_helper.to_array(inits[name]).astype(np.float32)
    vocab, dim = w.shape
    blocks = w.reshape(vocab, dim // EMBED_BLOCK, EMBED_BLOCK)
    scale = np.maximum(np.abs(blocks).max(axis=2, keepdims=True), 1e-12) / 127.0
    qw = np.clip(np.rint(blocks / scale), -127, 127).astype(np.int8).reshape(vocab, dim)
    g.initializer.remove(inits[name])
    g.initializer.extend([
        numpy_helper.from_array(qw, name + "_int8"),
        numpy_helper.from_array(scale.astype(np.float32), name + "_scale"),
        numpy_helper.from_array(np.array([0, 0, dim // EMBED_BLOCK, EMBED_BLOCK], np.int64),
                                name + "_blocked"),
        numpy_helper.from_array(np.array([0, 0, dim], np.int64), name + "_flat")])
    out, ids = table.output[0], table.input[1]
    at = list(g.node).index(table)
    g.node.remove(table)
    for i, node in enumerate([
            helper.make_node("Gather", [name + "_int8", ids], [out + "_q"], axis=0),
            helper.make_node("Cast", [out + "_q"], [out + "_f"], to=TensorProto.FLOAT),
            helper.make_node("Reshape", [out + "_f", name + "_blocked"], [out + "_b"]),
            helper.make_node("Gather", [name + "_scale", ids], [out + "_s"], axis=0),
            helper.make_node("Mul", [out + "_b", out + "_s"], [out + "_m"]),
            helper.make_node("Reshape", [out + "_m", name + "_flat"], [out])]):
        g.node.insert(at + i, node)


def softmax(x):
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def verify(model, path, tol, probabilities=False):
    """Run `path` against torch on shapes the trace never saw.

    fp32 must match logit for logit. The quantised graph is compared the way
    `suggest` reads it, as probabilities over the options, and must make the
    same pick: a raw-logit bound punishes a model for being confident, since
    a wider logit range moves more under the same weight rounding while the
    decision does not.
    """
    import onnxruntime as ort
    sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    worst, differs = 0.0, 0
    for T, K in ((64, 5), (96, 2), (160, 13), (300, 17), (512, 25)):
        ex = example(T, K, seed=T + K)
        with torch.no_grad():
            want = model(*ex)[0].numpy()
        got = sess.run(None, {n: v.numpy() for n, v in zip(NAMES, ex)})[0]
        if probabilities:
            want, got = softmax(want), softmax(got)
        d = float(np.abs(got - want).max())
        worst = max(worst, d)
        same = got.argmax() == want.argmax()
        differs += not same
        print("  T=%-3d K=%-2d  shape %s  max|diff| %.2e  argmax %s"
              % (T, K, list(got.shape), d, "agrees" if same else "DIFFERS"))
    what = "probabilities" if probabilities else "logits"
    if worst > tol:
        sys.exit("export: %s %s differ from torch by %.2e (tolerance %.0e)"
                 % (path, what, worst, tol))
    if probabilities and differs:
        sys.exit("export: %s changes the pick on %d shape(s)" % (path, differs))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True, help="fine-tuned laya checkpoint directory")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args()

    import laya
    agent = laya.load(args.model, device="cpu")
    model = agent.model.eval()
    # ModernBERT picks a fused attention path by default; tracing needs eager.
    model.encoder.config._attn_implementation = "eager"

    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(args.out, "fp32")
    os.makedirs(work, exist_ok=True)
    fp32 = os.path.join(work, "anchor.fp32.onnx")
    export(model, fp32)
    print("fp32 export: %s" % fp32)
    verify(model, fp32, tol=1e-3)

    int8 = os.path.join(args.out, "anchor.onnx")
    quantize(fp32, int8)
    size = os.path.getsize(int8)
    print("8-bit: %s (%.0f MB)" % (int8, size / 1e6))
    if size >= MAX_BYTES:
        sys.exit("export: %s is %.0f MB, over the %d MB budget"
                 % (int8, size / 1e6, MAX_BYTES // 10**6))
    # Quantisation moves logits; what must hold is the decision. The real
    # check is parity.py, on real references - this one only catches a graph
    # that quantisation broke outright.
    verify(model, int8, tol=0.1, probabilities=True)

    shutil.copy(os.path.join(args.model, "tokenizer", "tokenizer.json"),
                os.path.join(args.out, "tokenizer.json"))
    cfg = agent.cfg
    tok = agent.tok
    with open(os.path.join(args.out, "config.json"), "w") as fh:
        json.dump({
            "max_len": cfg.get("max_len", 512),
            "head_max_len": cfg.get("head_max_len", 192),
            # The clamped values laya itself applies, not the raw ones.
            "temperature": agent.temperature,
            "temperature_by_options": agent.temperature_by_options,
            "tokens": {"cls": tok.cls_token_id, "sep": tok.sep_token_id,
                       "mask": tok.mask_token_id, "pad": tok.pad_token_id,
                       "mask_text": tok.mask_token},
        }, fh, indent=2, sort_keys=True)
        fh.write("\n")
    shutil.rmtree(work)
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
