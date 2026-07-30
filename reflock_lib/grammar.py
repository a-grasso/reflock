"""Reference grammar: the regexes that find a reference, and the data model
(`Ref`, `Index`) that indexing and resolution build on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

FP_LEN = 8  # hex chars of sha256; 32 bits — a missed drift is ~1 in 4e9

# A markdown link, with an optional trailing pin comment. The pin's hex is its
# own group so `stamp` can splice it in place (empty group == opted-in, unstamped).
MD_REF = re.compile(
    r"\[[^\]]*\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"(?:[\s.,;:!?]*<!--@(?P<pin>[0-9a-f]*)-->)?"
)
# A REF comment: a comment opener, then `REF: target`, optional ` @hex`.
# The opener requirement keeps `REF:` inside prose or string literals from matching.
CODE_REF = re.compile(
    r"(?:#|//|/\*|<!--|--|;|\*)\s*REF:\s*(?P<target>[^\s@]+)(?:\s+@(?P<pin>[0-9a-f]*))?"
)
# A reference-style link *definition* - `[id]: target "title"`. The pin lives
# here, on the definition line, since a definition names its target exactly
# once while usages (`[text][id]`, `[id][]`, the unsupported shortcut `[id]`)
# may repeat it many times.
REF_DEF = re.compile(
    r'^\s*\[[^\]]+\]:\s+(?P<target>\S+?)(?:\s+"[^"]*")?'
    r"(?:\s*<!--@(?P<pin>[0-9a-f]*)-->)?\s*$"
)
# A wiki-link: [[target]], [[target#anchor]], [[target|alias]], or both.
# Alias is display text and split off at the first `|` only.
WIKI_LINK = re.compile(
    r"\[\[(?P<target>[^\]|]+?)(?:\|[^\]]*)?\]\]"
    r"(?:[\s.,;:!?]*<!--@(?P<pin>[0-9a-f]*)-->)?"
)
ANCHOR_OPEN = re.compile(r"reflock-anchor:\s*(?P<name>[\w.\-/]+)")
ANCHOR_END = re.compile(r"reflock-anchor-end:\s*(?P<name>[\w.\-/]+)")
HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
# A path-shaped token for the `suspects` heuristic: has a slash and an extension.
PATHISH = re.compile(
    r"(?<![\w./])(?P<p>(?:\.\.?/)?(?:[\w.\-]+/)+[\w.\-]+\.[A-Za-z][A-Za-z0-9]{0,5})"
)
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.\-]*:|//|#)")  # url scheme, //, or same-page #
# A URL, for masking before the `suspects` scan: a URL's path segments are not
# repo paths. PATHISH only ever excluded them by accident of its lookbehind -
# inside `https://host/a/b.html` every candidate start is preceded by `/` or
# `.`, both excluded - and any character outside that class re-opens the hole
# (`@` in an npm scope did; `~`, `+`, `,` and `=` are all legal in a segment).
# Excluding the whole construct is the rule that holds.
# The protocol-relative form demands a dotted host with an alphabetic TLD so a
# `// see other/module.py` comment in a code file is not read as a URL and
# silently dropped from the scan.
URL = re.compile(
    r"[a-zA-Z][a-zA-Z0-9+.\-]*://\S+"
    r"|//[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z]{2,}/\S*"
)
PIN_STRIP = re.compile(r"<!--@[0-9a-f]*-->|(?<=@)[0-9a-f]{%d}\b" % FP_LEN)


@dataclass
class Ref:
    src: str          # repo-relative path of the referring file
    line: int         # 1-based
    kind: str         # 'md' | 'code'
    target: str       # raw target string
    pin: str | None   # None=unpinned, ''=opted-in-unstamped, hex=pinned
    pin_span: tuple[int, int] | None  # (start,end) of hex within the source line
    wiki: bool = False  # True for [[wiki-link]] targets - enables basename fallback (D4)
    col: int = 0      # 0-based column of the match start, for column-ordering multiple refs on a line


@dataclass
class Index:
    root: str
    files: set[str] = field(default_factory=set)
    dirs: set[str] = field(default_factory=set)
    lines: dict[str, list[str]] = field(default_factory=dict)
    # path -> list of (slug, start_line0, level) in document order
    headings: dict[str, list[tuple[str, int, int]]] = field(default_factory=dict)
    # path -> {name: (start_line0, end_line0)}  span is exclusive of markers
    spans: dict[str, dict[str, tuple[int, int]]] = field(default_factory=dict)
    ignored: set[str] = field(default_factory=set)  # scanned as targets, not as sources
    symlinks: set[str] = field(default_factory=set)  # ditto: readable, never written
    # (path, anchor) -> fingerprint, so N references to one unit hash it once.
    # On the Index, not module state: an Index is one snapshot of one tree.
    fps: dict[tuple[str, str | None], str] = field(default_factory=dict)
