"""`reflock suggest`: place the first pins in a repository that has none.

A pin earns its keep by firing when its target changes and by *not* firing
otherwise. Placed by hand, the first pins go on whatever the author happens to
be looking at. This picks them instead:

  1. harvest   every unpinned, whole-file markdown reference into indexed text
  2. filter    drop links that make no claim (index rows, see-also lists)
  3. anchor    the model narrows each link to the heading its sentence is
               about, or leaves it whole-file
  4. rank      by how often that unit actually changed in first-parent history,
               calmest first, so the first pins are the ones least likely to cry
               wolf
  5. write     `#anchor` plus an empty `<!--@-->`, which `reflock stamp` fills

Steps 1, 2, 4 and 5 are standard library and run before the model is touched,
so a repository with nothing to pin never needs the `[suggest]` extra at all.
Only `runtime` imports third-party code, and only once there is work for it.
"""
from __future__ import annotations

import os
import subprocess
import sys

from reflock_lib.commands import ScopeError, render_error, scoped_files
from reflock_lib.grammar import Index


def _in_git_repo(root: str) -> bool:
    try:
        p = subprocess.run(["git", "-C", root, "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True)
    except OSError:
        return False
    return p.returncode == 0 and p.stdout.strip() == "true"


def _fail(idx: Index, message: str, kind: str = "usage") -> int:
    render_error(message, "human", kind, "suggest", idx.root)
    return 2


def cmd_suggest(idx: Index, args) -> int:
    from reflock_lib.suggest import claims, harvest

    if args.max_pins < 1:
        return _fail(idx, "--max-pins must be at least 1")
    if not _in_git_repo(idx.root):
        # Churn is the ranking; without history there is nothing to rank by,
        # and a ranking that silently degrades to "file order" is a guess.
        return _fail(idx, "reflock suggest ranks by git history; %s is not a git "
                          "work tree" % idx.root)
    try:
        sources = scoped_files(idx, args.paths)
    except ScopeError as e:
        return _fail(idx, str(e), "scope")

    found = harvest.candidates(idx, sources)
    refs = [r for r in found if claims.pin_worthy(idx, r)]
    if not refs:
        print("nothing to suggest: %d unpinned reference(s), none a pin could bind to"
              % len(found) if found else
              "nothing to suggest: no unpinned references a pin could bind to")
        return 0
    print("%d unpinned reference(s) a pin could bind to (%d skipped as navigation)"
          % (len(refs), len(found) - len(refs)))

    from reflock_lib.suggest import runtime
    try:
        runtime.require()
    except runtime.MissingRuntime as e:
        sys.stdout.flush()
        print(str(e), file=sys.stderr)
        return 2

    from reflock_lib.suggest import fetch
    from reflock_lib.suggest.anchor import Anchorer
    from reflock_lib.suggest.churn import Churn
    try:
        model_dir = args.model or fetch.ensure()
    except fetch.FetchError as e:
        return _fail(idx, str(e))
    if not os.path.isfile(os.path.join(model_dir, "anchor.onnx")):
        return _fail(idx, "no model in %s (expected anchor.onnx, config.json, "
                          "tokenizer.json)" % model_dir)
    anchorer = Anchorer(model_dir)

    tty = sys.stderr.isatty()
    scored = []
    for i, ref in enumerate(refs, 1):
        anchor, conf = anchorer.anchor(idx, ref)
        scored.append((ref, anchor, conf))
        if tty:
            sys.stderr.write("\r  anchored %d/%d" % (i, len(refs)))
    if tty:
        sys.stderr.write("\n")

    churn = Churn(idx.root, since=args.since)
    ranked = sorted(scored, key=lambda t: (churn.rate(t[0]["target_path"], t[1]), -t[2],
                                           t[0]["file"], t[0]["line"], t[0]["col"]))
    chosen = ranked[:args.max_pins]

    narrowed = sum(1 for _, a, _ in chosen if a)
    print("\n%s %d reference(s), %d narrowed to a section:"
          % ("would pin" if args.dry_run else "pinning", len(chosen), narrowed))
    for ref, anchor, conf in chosen:
        n, obs = churn.of(ref["target_path"], anchor)
        where = "%s:%d" % (ref["file"], ref["line"])
        print("  %-40s %s%s   (%d change(s) in %d commit(s), conf %.2f)"
              % (where, ref["target"], "#" + anchor if anchor else "", n, obs, conf))
    if args.dry_run:
        print("\ndry run, nothing written")
        return 0

    from reflock_lib.suggest.apply import apply
    written, skipped = apply(idx, [(r, a) for r, a, _ in chosen])
    print("\nwrote %d empty pin(s)" % written)
    for s in skipped:
        print("  skipped %s (the line no longer parses as it did; left untouched)" % s)
    if written:
        print("\nnext:  reflock stamp && reflock check")
        print("       git diff   - read it, these are suggestions")
    return 0
