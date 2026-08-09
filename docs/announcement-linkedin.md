# LinkedIn announcement - reflock

Draft copy for introducing reflock. Two variants, plus a first comment carrying
the link. Not part of the tool; delete once the post is out.

House rules applied: no em dashes, no "excited to announce", no emoji rows, no
rule-of-three flourishes. Plain sentences.

---

## Variant A - short (~120 words)

> Your link checker says green. The paragraph is still wrong.
>
> A doc says "the pipeline runs four stages, see ADR-0011". Someone supersedes
> ADR-0011. The link still resolves, so nothing complains, and the sentence stays
> wrong for six months until someone acts on it.
>
> Link checkers answer "does this resolve". Nobody answers "did the thing I
> described change since I described it".
>
> So I built reflock. It borrows the idea from package-lock.json: record a
> content fingerprint of what a reference points at, and fail the check the
> moment that content drifts. One dependency-free Python file. No model, no
> network. It runs on every commit and costs nothing.
>
> Same story as portbook, the dev port dashboard I published earlier: yet another
> tool I needed for myself, it works, so it is public now.

---

## Variant B - longer (~250 words)

> Your link checker says green. The paragraph is still wrong.
>
> Here is the case that made me build this. A repo deletes `platform/research.sh`.
> Two things referred to it: an architecture decision record, and a comment at the
> top of a sibling script. Both were written as prose, not links, so no checker
> could see them. Both are now lies, and nothing in CI can tell.
>
> The worse version does not even involve a deletion. A doc says "the pipeline
> runs four stages, see ADR-0011". Someone supersedes ADR-0011. The link still
> resolves perfectly, so the checker reports green, while the sentence describing
> it has been wrong for six months.
>
> References break in two different ways. The target moved, which tools already
> catch. Or the target changed, which they do not, because you cannot see it by
> looking at the reference alone. You have to know the target changed since the
> referring text last vouched for it.
>
> reflock does exactly that, borrowing the mechanism from package-lock.json:
> record a short content fingerprint of the target when the reference is blessed,
> recompute it on every check, and fail on a mismatch. The mismatch is the "go
> re-read this paragraph" signal. It hashes the smallest anchored unit, a section
> rather than a whole document, so one typo does not flag twenty references and
> teach the team to mute it.
>
> One dependency-free Python file. No model in the hot path, no network, no
> daemon. Grep, a hashmap lookup, a byte compare.
>
> Same story as portbook, the dev port dashboard I published earlier: yet another
> tool I needed for myself, it works, so it is public now.

---

## First comment (carries the links)

> reflock: https://github.com/a-grasso/reflock
> portbook: https://github.com/a-grasso/portbook
>
> `brew install a-grasso/tap/reflock`, or drop it in as a pre-commit hook. The
> README explains the convention it asks you to adopt, and DECISIONS.md records
> what it deliberately does not do.

---

## Notes on the framing

- The hook is the problem, not the tool. "Your link checker says green, the
  paragraph is still wrong" is the entire pitch in one line, and it is a thing
  most engineers have personally been burned by.
- `package-lock.json` does the explaining. Everyone reading already understands
  lockfiles, so the mechanism needs no paragraph of its own.
- Do not lead with AI agents. It is a real use case (an agent can declare itself
  done with references broken, which is what the Stop hook gate is for) but
  leading with it reads as bandwagon and buries the older, more universal
  problem. Worth a reply if someone asks.
- The portbook sentence is deliberately flat. "I needed it, it works, here it is"
  is both true and more credible than positioning either tool as a product.
