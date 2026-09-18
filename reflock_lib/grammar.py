"""Reference grammar: the regexes that find a reference, and the data model
(`Ref`, `Index`) that indexing and resolution build on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

FP_LEN = 8  # hex chars of sha256; 32 bits — a missed drift is ~1 in 4e9

# The fingerprint algorithm a *new* pin is written under. A stamp is a published
# wire format the moment `stamp` runs in someone else's repo, and inline pins
# cannot be migrated the way a single lockfile field can — so the version is
# reserved now, while it is free (NORTHSTARS #11).
#
# Bare hex (`@a1b2c3d4`) means version 1 and is what `stamp` writes; nothing in
# the field changes. A future algorithm ships as `@2:newhex`, and a reflock too
# old to know that version says so plainly instead of reporting a false DRIFTED.
FP_VERSION = 1
# The pin body, shared by every reference pattern: an optional `N:` version
# prefix, then hex. Empty still means opted-in-but-unstamped.
PIN_BODY = r"(?:[0-9]+:)?[0-9a-f]*"

# An SSH remote - `git@github.com:acme/ng-ui.git` - named once, consulted by
# every rule that needs it (BUG-17). It is the one reference-shaped construct
# with no scheme: the `@` lands before the colon, so EXTERNAL's `scheme:` rule
# and URL's `//` rule both miss it, while CODE_REF used to split its target at
# that same `@`. The host must be dotted with an alphabetic TLD - the caution
# URL's protocol-relative branch already takes - so an `a@b:c` in prose is not
# swallowed. A host with no dot (`git@internal:path`) is the bounded gap;
# a shape loose enough to catch it would eat ordinary text.
SSH_REMOTE = r"[\w.\-]+@[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z]{2,}:"

# A markdown link, with an optional trailing pin comment. The pin's hex is its
# own group so `stamp` can splice it in place (empty group == opted-in, unstamped).
#
# The link text admits one level of balanced brackets, as CommonMark does, so
# the "back to index" footer form `[[Back to README]](../README.md)` is the
# markdown link it renders as (BUG-15). A nested group followed by `(` is
# excluded, because then *it* is the label of an inline link and the inner link
# is the reference: `[![alt](i.png)](t.md)` keeps reporting the image target,
# unchanged. The rule both here and in WIKI_LINK is the same one - a `]`
# followed directly by `(` belongs to the innermost link.
MD_REF = re.compile(
    r"\[(?:[^\[\]]|\[[^\[\]]*\](?!\())*\]"
    r"\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"(?:[\s.,;:!?]*<!--@(?P<pin>%s)-->)?" % PIN_BODY
)
# A REF comment: a comment opener, then `REF: target`, optional ` @hex`.
# The opener requirement keeps `REF:` inside prose or string literals from matching.
#
# The target is a whole non-space run: only whitespace introduces a pin, so the
# `@` in `git@github.com:...` stays in the target where it belongs (BUG-17).
# Spelling it `[^\s@]+` split the pin off without a lookahead, and split an SSH
# remote after `git`. The trailing `(?=\s|$)` is what lets the lazy run stop at
# the pin instead of eating it.
CODE_REF = re.compile(
    r"(?:#|//|/\*|<!--|--|;|\*)\s*REF:\s*(?P<target>\S+?)"
    r"(?:\s+@(?P<pin>%s))?(?=\s|$)" % PIN_BODY
)
# A reference-style link *definition* - `[id]: target "title"`. The pin lives
# here, on the definition line, since a definition names its target exactly
# once while usages (`[text][id]`, `[id][]`, the unsupported shortcut `[id]`)
# may repeat it many times.
REF_DEF = re.compile(
    r'^\s*\[[^\]]+\]:\s+(?P<target>\S+?)(?:\s+"[^"]*")?'
    r"(?:\s*<!--@(?P<pin>%s)-->)?\s*$" % PIN_BODY
)
# A wiki-link: [[target]], [[target#anchor]], [[target|alias]], or both.
# Alias is display text and split off at the first `|` only.
#
# The `(?!\()` (BUG-15): `[[text]](target)` is a markdown link whose *text* is
# bracketed - the "back to index" footer form - and CommonMark and GitHub both
# render it that way, so the reference is `target` and `text` is display text.
# MD_REF owns the whole construct; without the lookahead this pattern matched it
# too and reported the display text as a missing file. The `(` must follow the
# `]]` with nothing between, which is exactly when MD_REF claims the
# construct - a merely adjacent parenthetical (`[[note]] (see also)`) is still a
# wiki-link, since MD_REF does not match there either.
WIKI_LINK = re.compile(
    r"\[\[(?P<target>[^\]|]+?)(?:\|[^\]]*)?\]\](?!\()"
    r"(?:[\s.,;:!?]*<!--@(?P<pin>%s)-->)?" % PIN_BODY
)
ANCHOR_OPEN = re.compile(r"reflock-anchor:\s*(?P<name>[\w.\-/]+)")
ANCHOR_END = re.compile(r"reflock-anchor-end:\s*(?P<name>[\w.\-/]+)")
HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
# A path-shaped token for the `suspects` heuristic: has a slash and an extension.
#
# The lookbehind's rule (BUG-08, BUG-13): no match may begin at a character the
# segment class `[\w.\-]` would itself have consumed, plus `/` and `$`.
# Otherwise the pattern restarts *inside* a token and reports a suffix of it -
# `@babel/core/...` out of an npm URL, `share/index.html` out of
# `{{ dir }}/dist-share/index.html`. Both arrived as one-off omissions of that
# rule, so it is written here as a rule; extend the class, never the incident
# list, if the segment class ever grows.
#
# Two shapes are deliberately not path-shaped (BUG-09):
#   `$` in the lookbehind - `$scriptDir/a/b.c` is a shell/Make/CI variable, and
#     its first segment is a runtime value, not a directory. (`${VAR}/a/b.c` and
#     `$(VAR)/a/b.c` never matched: `}` and `)` break the segment class.)
#   a `...` segment - `a/.../b.kt` is a human's elision placeholder, correctly
#     unresolvable. The lookbehind then also blocks a restart after the `/`, so
#     the trailing `b.kt` half is not reported either, which is the intent:
#     half a placeholder is worse than nothing.
# The extension is matched to its own end or not at all (BUG-10): the old
# {0,5} cap silently *truncated*, so `maven-wrapper.properties` was reported as
# `maven-wrapper.proper` - a string absent from the file, then asserted not to
# resolve. The trailing (?!\w) is what makes a match whole; the cap widened to
# 9 so the longest real extensions (.properties, .markdown) fit rather than
# vanishing. A cap still bounds *which* tokens match - it keeps
# `and/or something.Nevertheless` out - but never what a matched token looks
# like. Extensions past it are a bounded blind spot, which is the failure mode
# an advisory heuristic is allowed to have; reporting a token wrong is not.
PATHISH = re.compile(
    r"(?<![\w./$-])(?P<p>(?:\.\.?/)?(?:(?!\.\.\./)[\w.\-]+/)+[\w.\-]+\.[A-Za-z][A-Za-z0-9]{0,9})(?!\w)"
)
# url scheme, //, same-page #, or an SSH remote
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.\-]*:|//|#|%s)" % SSH_REMOTE)
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
    r"|%s\S*" % SSH_REMOTE
)
PIN_STRIP = re.compile(
    r"<!--@(?:[0-9]+:)?[0-9a-f]*-->|(?<=@)(?:[0-9]+:)?[0-9a-f]{%d}\b" % FP_LEN)


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
