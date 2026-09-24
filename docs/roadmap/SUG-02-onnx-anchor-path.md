# SUG-02 acceptance contract: a stdlib path to a local anchor model

Source: [issue #20](https://github.com/a-grasso/reflock/issues/20)
Owner: agent · Tier: near · Touches: [reflock_lib/suggest/bpe.py](../../reflock_lib/suggest/bpe.py), [reflock_lib/suggest/anchor.py](../../reflock_lib/suggest/anchor.py), [reflock_lib/suggest/runtime.py](../../reflock_lib/suggest/runtime.py), [reflock_lib/suggest/fetch.py](../../reflock_lib/suggest/fetch.py), [suggest-model/export.py](../../suggest-model/export.py), [suggest-model/parity.py](../../suggest-model/parity.py), [test_reflock.py](../../test_reflock.py)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The problem

Churn (SUG-03) picks *which* references to pin; it has no concept of a
section, so it cannot pick *where* a pin binds. That needs a model - a local,
fine-tuned [laya](https://github.com/NandhaKishorM/laya) checkpoint that
answers a typed `choice` question ("which section is this claim about?") in
one forward pass, options rendered per call from the target's own headings.
Shipping it must not cost `check` its zero-dependency guarantee (D3): the
model, its tokenizer, and its runtime all have to live behind the one optional
extra, reachable only from `reflock suggest`.

## The decision

**Tokenizer, in the standard library.** `reflock_lib/suggest/bpe.py`
reimplements ModernBERT's byte-level BPE tokenizer from the same
`tokenizer.json` HuggingFace `tokenizers` reads, so the `[suggest]` extra
never needs a compiled Rust extension for one function. Held to id-for-id
agreement with `tokenizers`: 0 mismatches on 214 real cases.

**Anchor layout mirrors laya.** `anchor.Anchorer.sequence` reproduces laya's
own `build_sequence` input format token for token -
`[CLS] choice question: <instructions> [SEP] [MASK] opt0 [MASK] opt1 ... [SEP] <state> [SEP]`
- rather than importing laya, which would pull in torch. `suggest-model/parity.py`
holds this rendering to laya's, decision for decision, on every pinnable
reference of a real repository.

**`runtime.py` is the only third-party import in `reflock_lib.suggest`.**
`runtime.require()` probes for `numpy`/`onnxruntime` and raises
`MissingRuntime` with the install hint if either is absent; `Session` wraps
`onnxruntime.InferenceSession`. Every other module in the package is stdlib,
so a repository with nothing to pin never touches the extra at all.

**Model fetch: sha256 manifest, XDG cache.** `fetch.py` downloads the model as
a public GitHub release asset on first use, verifying every file's sha256
against `MANIFEST` before it is used - a truncated download, a proxy error
page, or a swapped asset fails here rather than silently loading. Cached under
`$XDG_CACHE_HOME/reflock/models` (or `~/.cache/reflock/models`); a matching
`manifest.json` plus file sizes let a later run skip re-hashing half a
gigabyte.

**Export: dynamo, opset 18 floor.** `suggest-model/export.py` uses PyTorch's
dynamo exporter rather than the legacy TorchScript exporter, which bakes the
traced sequence length into the attention reshape - fatal for a model whose
whole point is a variable number of options per call. Opset 18 is a floor:
at 17 the export completes but onnxruntime rejects the graph, because `Split`
only gains `num_outputs` at 18.

**Quantization, measured, not assumed.** Dynamic int8 (`quantize_dynamic`,
which also quantizes activations) agreed with the laya-torch reference on only
77.2% of 246 real references, worst probability gap 0.849 - too large to be
near-tie noise. Weight-only 8-bit instead: `MatMulNBits` block 32 for the
transformer weights, int8 for the token embedding with one fp32 scale per
block of 32 values. That lands at 483 MB, under the 500 MB budget, and agrees on
99.2% of the same references, worst gap 0.053. `suggest-model/parity.py`'s
gate requires input sequences 100% identical (tokenizer and layout correctness
are separable from quantization) and >= 97% same pick. `export.py`'s own
check compares the 8-bit graph's option probabilities and pick with torch's, not
its raw logits: the published checkpoint's wider logit range moves by 0.13
under the same rounding while every pick holds.

**The published model: public data only.** `suggest-model-v1`, a release
asset on a-grasso/reflock, is laya fine-tuned only on permissively licensed
public repositories. The first prototype checkpoint had been trained on a
private repository, so it was never published. The training repos were
opentelemetry-specification, backstage (docs/), argo-cd (docs/),
kubernetes/community, kubernetes/enhancements (keps/), prometheus/docs,
istio.io, dapr/docs and tensorflow/community (all Apache-2.0); rust-lang/rfcs
and rust-lang/book (Apache-2.0 OR MIT); golang/proposal (BSD-3-Clause); adr/madr
(MIT OR CC0-1.0); and reflock itself (MIT).
That gave 4,410 references, filtered through `claims.pin_worthy` as production
filters them, with frontier-model labels (227 anchor items). The held-out
repository was never trained on. On it, the published model agrees with the
labels on 0.439 of anchor picks and 0.671 of needs-pin calls, against 0.394 /
0.662 for the private-data checkpoint and 0.182 / 0.541 for zero-shot laya.
Parity of the published artifact: 167/167 references same pick on the held-out
repository (worst gap 0.008), 79/79 on reflock (worst gap 0.032).

## Explicitly out of scope

- Retraining or improving the underlying laya checkpoint - this contract is
  about the path from a checkpoint to bytes `reflock suggest` can run, not
  about the checkpoint's quality.
- Any provider other than `CPUExecutionProvider`. GPU inference is not a goal
  for a one-shot onboarding tool.
- A source distribution for ONNX Runtime; `packaging/brew.py` (SUG-05) pins
  PyPI wheels instead, since none exists.

## Definition of done

1. Unit tests in `SuggestTest` pass:
   `test_tokenizer_merges_by_rank_and_honours_special_tokens` (BPE merge order
   and `[MASK]` lstrip behavior), `test_whole_file_pick_is_left_unanchored`
   (`anchor.spans_whole_file` refuses a document's title heading, which spans
   the whole file), `test_confidence_is_one_minus_normalised_entropy`
   (`anchor.confidence` and `anchor._bucket`), `test_fetch_verifies_then_caches`,
   `test_fetch_refuses_a_file_that_does_not_verify`, and
   `test_fetch_without_a_published_model_says_so`.
2. `suggest-model/parity.py --min-agreement 0.97` passes against the published
   artifact on the evaluation repositories.
3. `runtime.require()` is the only place in `reflock_lib.suggest` that imports
   `numpy` or `onnxruntime` at module scope; `test_other_commands_never_import_the_suggester`
   stays green.
4. `just gate` is green.
5. `ROADMAP.yaml` lists SUG-02 under `done`.
