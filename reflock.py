#!/usr/bin/env python3
"""reflock — a lockfile for cross-references.

Referential integrity for a mixed docs+code tree. reflock finds every
reference, resolves it against a target index, and — for *pinned* references —
compares a content fingerprint of the target's smallest anchored unit against
the value recorded when the reference was last blessed.

The design invariant: the mechanical layer runs always and is free; a semantic
(human or LLM) layer runs rarely and only on what drifts. There is no model in
the hot path — everything here is grep, a hashmap lookup, and a byte compare.

Reference surface forms
-----------------------
  Markdown link (optionally pinned):
      [text](relative/path.md#anchor)<!--@a1b2c3d4-->
      [text](relative/path.md#anchor)<!--@-->        # opt-in, not yet stamped
      [text](relative/path.md#anchor).<!--@a1b2c3d4-->  # sentence punctuation
                                                        # before the pin is fine

  REF comment (any text or code file):
      # REF: relative/path.kt#Symbol @a1b2c3d4
      // REF: ../doc/adr/0011-....md#decision @-

A target is `path` or `path#anchor`, `path` resolved relative to the file the
reference lives in. An anchor resolves to a markdown heading slug, or to an
explicit `reflock-anchor: <name>` ... `reflock-anchor-end: <name>` span in any
file. With no anchor, the unit is the whole file.

Verdicts
--------
  OK          resolves; fingerprint matches (or the reference is unpinned)
  DANGLING    path / anchor / span does not resolve
  DRIFTED     resolves, but the target changed since the pin was blessed
  UNSTAMPED   opted into pinning (`@`) but never stamped

Commands
--------
  reflock check     [paths...]     report; exit 1 on any problem
  reflock stamp     [paths...]     fill empty pins (--rebless: re-hash all)
  reflock suspects  [paths...]     path-shaped prose that doesn't resolve

This file is the single executable entry point (install.sh symlinks it onto
PATH, and the pre-commit manifest invokes it directly as a script); the
implementation lives in the reflock_lib package alongside it, split by concern
(grammar, engine, commands, cli) now that it has outgrown one file. Everything
below is re-exported so `import reflock` still exposes the whole flat API.
"""
from __future__ import annotations

import sys

from reflock_lib import __version__
from reflock_lib.grammar import (
    ANCHOR_END,
    ANCHOR_OPEN,
    CODE_REF,
    EXTERNAL,
    FP_LEN,
    HEADING,
    MD_REF,
    PATHISH,
    PIN_STRIP,
    REF_DEF,
    WIKI_LINK,
    Index,
    Ref,
)
from reflock_lib.engine import (
    build_index,
    classify,
    fingerprint,
    git_ignored,
    is_text,
    list_files,
    locate_anchor,
    mask_code_spans,
    normalize,
    parse_refs,
    read_reflockignore,
    repo_root,
    resolve_path,
    resolve_target,
    resolve_wikilink,
    run,
    slugify,
    unit_fingerprint,
    unit_text,
)
from reflock_lib.commands import (
    BACKLINKS_RENDERERS,
    BAD,
    COLOR_RESET,
    EXPLAIN_RENDERERS,
    GITHUB_LEVEL,
    RENDERERS,
    UNIT_PREVIEW_LINES,
    VERDICT_COLOR,
    FormatConflict,
    ScopeError,
    cmd_backlinks,
    cmd_check,
    cmd_explain,
    cmd_stamp,
    cmd_suspects,
    colorize,
    explain_entry,
    github_escape_message,
    github_escape_property,
    indexed_path,
    intended_format,
    plan_stamp,
    rel_to_root,
    render_backlinks_human,
    render_backlinks_json,
    render_error,
    render_explain_human,
    render_explain_json,
    render_github,
    render_human,
    render_json,
    resolve_format,
    scoped_files,
    stampable_fingerprint,
    unit_preview,
    use_color,
)
from reflock_lib.cli import (
    COMPLETION_SHELLS,
    build_parser,
    cmd_completion,
    completion_script,
    main,
    parser_spec,
)

if __name__ == "__main__":
    sys.exit(main())
