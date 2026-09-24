"""ModernBERT's tokenizer, in the standard library.

The anchor model reads token ids, and the reference implementation of the
tokenizer that produced its training data is HuggingFace `tokenizers`, a Rust
extension. Depending on it would put a compiled package with no Homebrew
formula into the `[suggest]` extra for the sake of one function. This is that
function: byte-level BPE, read from the same `tokenizer.json`, and held to
id-for-id agreement with `tokenizers` by `suggest-model/parity.py` on every
prompt of the evaluation repositories.

What `tokenizers` does, in order, and what each stage here mirrors:

  1. split the raw text on *special* added tokens (`[MASK]`, `[CLS]`, ...),
     longest match first; `[MASK]` also swallows the whitespace before it;
  2. NFC-normalize what is left;
  3. split that on the *normalized* added tokens - notably runs of 2-24
     spaces, which ModernBERT gives their own ids so indentation is cheap;
  4. pre-tokenize with the GPT-2 pattern and map bytes to printable symbols;
  5. merge each piece by BPE rank.

Stage 4's pattern is written with `\\p{L}` and `\\p{N}`, which `re` does not
have and which `re`'s `\\w` does not equal (it counts `²` and `Ⅻ` as letters
and drops no combining marks the Rust side keeps). The classes are therefore
built from `unicodedata` once, rather than approximated.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata

# Unicode's White_Space property - what the Rust regex means by \\s. Python's
# own \\s additionally matches U+001C..U+001F, which are not whitespace there.
WHITE_SPACE_CHARS = ("\t\n\x0b\x0c\r \x85\xa0\u1680" + "".join(map(chr, range(0x2000, 0x200b)))
                     + "\u2028\u2029\u202f\u205f\u3000")
WHITE_SPACE = re.escape(WHITE_SPACE_CHARS)


def _category_classes(*majors: str) -> list[str]:
    """Regex character-class bodies for whole general categories (`L`, `N`),
    built in one pass over the code space."""
    runs: dict[str, list[list[int]]] = {m: [] for m in majors}
    for cp in range(sys.maxunicode + 1):
        rs = runs.get(unicodedata.category(chr(cp))[0])
        if rs is None:
            continue
        if rs and rs[-1][1] == cp - 1:
            rs[-1][1] = cp
        else:
            rs.append([cp, cp])
    esc = lambda cp: re.escape(chr(cp))
    return ["".join(esc(a) if a == b else "%s-%s" % (esc(a), esc(b)) for a, b in runs[m])
            for m in majors]


def _bytes_to_unicode() -> dict[int, str]:
    """GPT-2's reversible byte -> printable-character table."""
    bs = (list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1))
          + list(range(ord("®"), ord("ÿ") + 1)))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, (chr(c) for c in cs)))


def _alternation(tokens) -> re.Pattern | None:
    """Leftmost-longest matching over literal tokens, as `tokenizers` does."""
    if not tokens:
        return None
    return re.compile("|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True)))


class Tokenizer:
    def __init__(self, path: str):
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)
        model = spec["model"]
        if model.get("type") != "BPE":
            raise ValueError("%s: expected a BPE model, got %r" % (path, model.get("type")))
        self.vocab = model["vocab"]
        self.ranks = {tuple(m if isinstance(m, list) else m.split(" ", 1)): i
                      for i, m in enumerate(model["merges"])}
        self.added = {t["content"]: t["id"] for t in spec.get("added_tokens", [])}
        special = [t for t in spec.get("added_tokens", []) if not t.get("normalized")]
        normal = [t for t in spec.get("added_tokens", []) if t.get("normalized")]
        self._special = _alternation([t["content"] for t in special])
        self._lstrip = {t["content"] for t in special if t.get("lstrip")}
        self._normal = _alternation([t["content"] for t in normal])
        (L, N), S = _category_classes("L", "N"), WHITE_SPACE
        self._pre = re.compile(
            r"'s|'t|'re|'ve|'m|'ll|'d"
            r"| ?[{L}]+| ?[{N}]+| ?[^{S}{L}{N}]+"
            r"|[{S}]+(?![^{S}])|[{S}]+".format(L=L, N=N, S=S))
        self._byte = _bytes_to_unicode()
        self._cache: dict[str, list[int]] = {}

    def encode(self, text: str) -> list[int]:
        """Token ids for `text`, with no [CLS]/[SEP] added."""
        ids: list[int] = []
        for piece, is_special in self._split_special(text):
            if is_special:
                ids.append(self.added[piece])
                continue
            piece = unicodedata.normalize("NFC", piece)
            for sub, is_added in self._split(piece, self._normal):
                if is_added:
                    ids.append(self.added[sub])
                else:
                    for word in self._pre.findall(sub):
                        ids.extend(self._bpe(word))
        return ids

    def _split_special(self, text: str):
        pieces = list(self._split(text, self._special))
        # An lstrip token owns the whitespace before it: drop it from the
        # preceding piece rather than tokenizing it as a space.
        for i in range(1, len(pieces)):
            if pieces[i][1] and pieces[i][0] in self._lstrip and not pieces[i - 1][1]:
                pieces[i - 1] = (pieces[i - 1][0].rstrip(WHITE_SPACE_CHARS), False)
        return [(p, s) for p, s in pieces if p]

    @staticmethod
    def _split(text: str, pat: re.Pattern | None):
        if pat is None:
            yield text, False
            return
        at = 0
        for m in pat.finditer(text):
            if m.start() > at:
                yield text[at:m.start()], False
            yield m.group(), True
            at = m.end()
        if at < len(text):
            yield text[at:], False

    def _bpe(self, word: str) -> list[int]:
        hit = self._cache.get(word)
        if hit is not None:
            return hit
        syms = [self._byte[b] for b in word.encode("utf-8")]
        while len(syms) > 1:
            best, at = None, -1
            for i in range(len(syms) - 1):
                r = self.ranks.get((syms[i], syms[i + 1]))
                if r is not None and (best is None or r < best):
                    best, at = r, i
            if best is None:
                break
            pair = (syms[at], syms[at + 1])
            merged, i = [], 0
            while i < len(syms):
                if i < len(syms) - 1 and (syms[i], syms[i + 1]) == pair:
                    merged.append(syms[i] + syms[i + 1])
                    i += 2
                else:
                    merged.append(syms[i])
                    i += 1
            syms = merged
        ids = [self.vocab[s] for s in syms]
        self._cache[word] = ids
        return ids

