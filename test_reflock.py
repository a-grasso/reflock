"""Tests for reflock. Run: python3 -m unittest -v test_reflock"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "reflock", os.path.join(os.path.dirname(__file__), "reflock.py"))
reflock = importlib.util.module_from_spec(_spec)
sys.modules["reflock"] = reflock  # let dataclasses resolve annotations at import
_spec.loader.exec_module(reflock)


class ReflockTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, rel, text):
        p = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(p) or self.d, exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)

    def read(self, rel):
        with open(os.path.join(self.d, rel)) as fh:
            return fh.read()

    def verdicts(self, rel):
        idx = reflock.build_index(self.d)
        return [reflock.classify(idx, r) for r in reflock.parse_refs(idx, rel)]

    def verdict(self, rel):
        return self.verdicts(rel)[0][0]

    def stamp(self, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            reflock.main(["--root", self.d, "stamp", *args])

    # --- structural (Level 1) --------------------------------------------
    def test_dangling_file(self):
        self.write("a.md", "See [x](missing.md).\n")
        self.assertEqual(self.verdict("a.md"), "DANGLING")

    def test_dangling_anchor(self):
        self.write("t.md", "# Title\n\n## Real\n\nbody\n")
        self.write("a.md", "See [x](t.md#ghost).\n")
        self.assertEqual(self.verdict("a.md"), "DANGLING")

    def test_ok_unpinned(self):
        self.write("t.md", "# Title\n\n## Real\n\nbody\n")
        self.write("a.md", "See [x](t.md#real).\n")
        self.assertEqual(self.verdict("a.md"), "OK")

    def test_external_ignored(self):
        self.write("a.md", "See [x](https://example.com/p.md).\n")
        self.assertEqual(self.verdict("a.md"), "OK")

    def test_slugify_matches_github_double_hyphen(self):
        # GitHub replaces each space independently and keeps consecutive
        # hyphens; punctuation stripped between words leaves them behind.
        cases = {
            "Modules, imports & visibility": "modules-imports--visibility",
            "Sum types & match": "sum-types--match",
            "Operators & parenthesization": "operators--parenthesization",
            "Memory-management model (GC / RC / borrow)":
                "memory-management-model-gc--rc--borrow",
        }
        for heading, slug in cases.items():
            self.assertEqual(reflock.slugify(heading), slug)

    def test_anchor_with_stripped_punctuation(self):
        self.write("t.md", "# H\n\n## Modules, imports & visibility\n\nbody\n")
        self.write("a.md", "See [x](t.md#modules-imports--visibility).\n")
        self.assertEqual(self.verdict("a.md"), "OK")

    # --- fingerprint (Level 2) -------------------------------------------
    def test_reflow_invariant(self):
        self.write("t.md", "# H\n\n## Sec\n\nOne two three four.\n")
        idx = reflock.build_index(self.d)
        fp1 = reflock.fingerprint(reflock.unit_text(idx, "t.md", "sec"))
        self.write("t.md", "# H\n\n## Sec\n\nOne two\nthree      four.\n")
        idx = reflock.build_index(self.d)
        fp2 = reflock.fingerprint(reflock.unit_text(idx, "t.md", "sec"))
        self.assertEqual(fp1, fp2, "whitespace/reflow must not change the fingerprint")

    def test_section_scoped(self):
        # editing a sibling section must not drift a ref pinned to this one
        self.write("t.md", "# H\n\n## A\n\nalpha\n\n## B\n\nbeta\n")
        idx = reflock.build_index(self.d)
        fp_a = reflock.fingerprint(reflock.unit_text(idx, "t.md", "a"))
        self.write("t.md", "# H\n\n## A\n\nalpha\n\n## B\n\nbeta CHANGED\n")
        idx = reflock.build_index(self.d)
        self.assertEqual(fp_a, reflock.fingerprint(reflock.unit_text(idx, "t.md", "a")))

    def test_drift_stamp_rebless(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "Per [d](t.md#decision)<!--@-->.\n")
        self.assertEqual(self.verdict("a.md"), "UNSTAMPED")
        self.stamp()
        self.assertRegex(self.read("a.md"), r"<!--@[0-9a-f]{8}-->")
        self.assertEqual(self.verdict("a.md"), "OK")
        self.write("t.md", "# H\n\n## Decision\n\nWe chose Y instead.\n")
        self.assertEqual(self.verdict("a.md"), "DRIFTED")
        self.stamp("--rebless")
        self.assertEqual(self.verdict("a.md"), "OK")

    def test_code_ref_and_span_anchor(self):
        self.write("lib.py", "# reflock-anchor: run\ndef run():\n    return 1\n# reflock-anchor-end: run\n")
        self.write("note.md", "impl: `run`\n")  # placeholder
        self.write("caller.py", "# REF: lib.py#run @\n")
        self.stamp()
        self.assertRegex(self.read("caller.py"), r"@[0-9a-f]{8}")
        self.assertEqual(self.verdict("caller.py"), "OK")
        self.write("lib.py", "# reflock-anchor: run\ndef run():\n    return 99\n# reflock-anchor-end: run\n")
        self.assertEqual(self.verdict("caller.py"), "DRIFTED")

    # --- suspects --------------------------------------------------------
    def test_suspects_catches_bare_path(self):
        self.write("a.md", "The twin of platform/research.sh does the same.\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "suspects"])
        self.assertEqual(rc, 1)
        self.assertIn("platform/research.sh", buf.getvalue())

    def test_suspects_ignores_version_string(self):
        self.write("a.md", "Runs on Opus 4.8/4.7/4.6 today.\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "suspects"])
        self.assertEqual(rc, 0)

    def test_suspects_json(self):
        self.write("a.md", "The twin of platform/research.sh does the same.\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "suspects", "--json"])
        self.assertEqual(rc, 1)
        hits = json.loads(buf.getvalue())
        self.assertEqual(hits, [{"file": "a.md", "line": 1, "target": "platform/research.sh"}])


if __name__ == "__main__":
    unittest.main()
