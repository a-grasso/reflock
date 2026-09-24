"""How often has this unit of text actually changed?

A pin's whole cost is that it fires, and it fires when its unit changes. So
rather than predicting that from the prose, measure it: replay the target's
first-parent history and count the commits where the unit's fingerprint moved.

First-parent matters. A change that lands as both a topic commit and a merge
is one edit and would otherwise be counted twice - roughly a 2.3x overstatement
on a merge-heavy repository.

Each historical revision is cut into units by `engine.index_text`, the code
`build_index` itself uses, so the unit measured here is the unit `check` will
fingerprint - not a lookalike.
"""
from __future__ import annotations

import subprocess

from reflock_lib.engine import fingerprint, index_text, unit_text
from reflock_lib.grammar import Index


def git(repo: str, *args: str) -> str | None:
    # A path can have held binary content at some revision - an image later
    # replaced by a document - so history is decoded leniently rather than
    # letting one undecodable blob abort the walk.
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return p.stdout if p.returncode == 0 else None


class Churn:
    """Fingerprint changes per (path, anchor), cached across references."""

    def __init__(self, repo: str, since: str = "90 days ago"):
        self.repo = repo
        self.since = since
        self._counts: dict[tuple[str, str | None], tuple[int, int]] = {}
        self._revs: dict[str, list[str]] = {}
        self._blobs: dict[tuple[str, str], Index | None] = {}

    def _revisions(self, path: str) -> list[str]:
        if path not in self._revs:
            out = git(self.repo, "log", "--first-parent", "--since", self.since,
                      "--format=%H", "--", path) or ""
            self._revs[path] = out.split()
        return self._revs[path]

    def _index_at(self, rev: str, path: str) -> Index | None:
        key = (rev, path)
        if key not in self._blobs:
            text = git(self.repo, "show", "%s:%s" % (rev, path))
            if text is None:
                self._blobs[key] = None
            else:
                idx = Index(root=self.repo)
                index_text(idx, path, text)
                self._blobs[key] = idx
        return self._blobs[key]

    def _fp(self, rev: str, path: str, anchor: str | None) -> str | None:
        idx = self._index_at(rev, path)
        if idx is None:
            return None
        unit = unit_text(idx, path, anchor)
        return None if unit is None else fingerprint(unit)

    def of(self, path: str, anchor: str | None) -> tuple[int, int]:
        """(changes, commits observed) for one unit inside the window."""
        key = (path, anchor)
        if key not in self._counts:
            revs = self._revisions(path)
            n = sum(1 for rev in revs
                    if self._fp(rev, path, anchor) != self._fp(rev + "^", path, anchor))
            self._counts[key] = (n, len(revs))
        return self._counts[key]

    def rate(self, path: str, anchor: str | None) -> float:
        """Changes per commit, smoothed, so silence is not mistaken for calm.

        A vendored document with one commit and no edits looks perfectly quiet
        and is simply unobserved - unsmoothed, it beats a document watched over
        fifty commits that moved twice, and the first run of the prototype
        picked twelve such files. Laplace smoothing makes evidence count: the
        unobserved file scores (0+1)/(1+2) = 0.33, the watched one 3/52 = 0.06.
        """
        n, obs = self.of(path, anchor)
        return (n + 1.0) / (obs + 2.0)
