"""Tests for reflock. Run: python3 -m unittest -v test_reflock"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "reflock", os.path.join(os.path.dirname(__file__), "reflock.py"))
reflock = importlib.util.module_from_spec(_spec)
sys.modules["reflock"] = reflock  # let dataclasses resolve annotations at import
_spec.loader.exec_module(reflock)


class _TTYBuffer(io.StringIO):
    """A StringIO that claims to be a terminal, for exercising the color path."""
    def isatty(self):
        return True


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

    def check_json(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "check", "--json", *args])
        return rc, json.loads(buf.getvalue())

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

    def test_version_flag(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(out):
            reflock.main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f"reflock {reflock.__version__}")

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

    def test_slugify_does_not_reparse_code_span_contents(self):
        # Inside a code span, link syntax is literal — GitHub never reduces
        # `[t](u)` to `t` there, so neither may we. A heading's genuine inline
        # links still reduce to their link text.
        cases = {
            "2. Markdown link forms beyond `[text](target)` *(Near)*":
                "2-markdown-link-forms-beyond-texttarget-near",
            "Use `[a](b)` here": "use-ab-here",
            "See [the loader](x.md)": "see-the-loader",
            "Mixed [real](r.md) and `[fake](f.md)`": "mixed-real-and-fakefmd",
            "`a` and `b`": "a-and-b",
        }
        for heading, slug in cases.items():
            self.assertEqual(reflock.slugify(heading), slug, heading)

    def test_anchor_with_stripped_punctuation(self):
        self.write("t.md", "# H\n\n## Modules, imports & visibility\n\nbody\n")
        self.write("a.md", "See [x](t.md#modules-imports--visibility).\n")
        self.assertEqual(self.verdict("a.md"), "OK")

    def test_dir_target_ok(self):
        self.write("assets/logo.png", "binary-ish\n")
        self.write("a.md", "See [x](assets).\n")
        verdict, detail = self.verdicts("a.md")[0]
        self.assertEqual(verdict, "OK")
        self.assertEqual(detail, "dir")

    def test_outside_tree_ok(self):
        self.write("a.md", "See [x](../outside.md).\n")
        verdict, detail = self.verdicts("a.md")[0]
        self.assertEqual(verdict, "OK")
        self.assertEqual(detail, "outside tree")

    def test_same_file_anchor_ok(self):
        self.write("a.md", "# Title\n\n## Sec\n\nSee [self](#sec).\n")
        self.assertEqual(self.verdict("a.md"), "OK")

    def test_duplicate_heading_slugs_disambiguated(self):
        # GitHub suffixes repeats of the same slug with -1, -2, ...
        self.write("t.md", "# Title\n\n## Sec\n\nfirst\n\n## Sec\n\nsecond\n")
        self.write("a.md", "[a](t.md#sec)<!--@-->\n[b](t.md#sec-1)<!--@-->\n")
        self.stamp()
        verdicts = self.verdicts("a.md")
        self.assertEqual([v for v, _ in verdicts], ["OK", "OK"])
        # each pin must be scoped to its own section, not the other one's
        self.write("t.md", "# Title\n\n## Sec\n\nfirst\n\n## Sec\n\nsecond CHANGED\n")
        verdicts = self.verdicts("a.md")
        self.assertEqual(verdicts[0][0], "OK")       # #sec (first) untouched
        self.assertEqual(verdicts[1][0], "DRIFTED")  # #sec-1 (second) changed

    def test_multiple_refs_per_line(self):
        self.write("t.md", "# T\n\n## Real\n\nbody\n")
        self.write("a.md", "See [ok](t.md#real) and [bad](missing.md) together.\n")
        verdicts = self.verdicts("a.md")
        self.assertEqual([v for v, _ in verdicts], ["OK", "DANGLING"])

    def test_fenced_code_block_refs_not_parsed(self):
        self.write("a.md", "Some text.\n\n```\nSee [x](missing.md) and # REF: also/missing.py\n```\n")
        self.assertEqual(self.verdicts("a.md"), [])

    def test_inline_code_span_link_not_a_reference(self):
        self.write("a.md", "See `[x](t.md)` for the syntax.\n")
        self.assertEqual(self.verdicts("a.md"), [])

    def test_inline_code_span_does_not_suppress_real_link(self):
        self.write("t.md", "# T\n")
        self.write("a.md", "See [x](t.md) for the thing.\n")
        self.assertEqual(self.verdict("a.md"), "OK")

    def test_inline_code_span_ref_comment_exempt_in_markdown(self):
        self.write("a.md", "`# REF: t.md` is how you write it.\n")
        self.assertEqual(self.verdicts("a.md"), [])

    def test_inline_code_span_ref_comment_still_live_in_code_file(self):
        self.write("a.py", "# `# REF: t.md`\n")
        verdicts = self.verdicts("a.py")
        self.assertEqual([v for v, _ in verdicts], ["DANGLING"])

    def test_inline_code_span_mixed_line(self):
        self.write("real.md", "# R\n")
        self.write("a.md", "Mixed `[a](skip.md)` and [b](real.md)\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].target, "real.md")
        self.assertEqual(self.verdicts("a.md"), [("OK", "unpinned")])

    def test_inline_code_span_double_backtick_exempt(self):
        self.write("a.md", "See ``[x](missing.md)`` here.\n")
        self.assertEqual(self.verdicts("a.md"), [])

    def test_inline_unterminated_backtick_still_yields_reference(self):
        self.write("a.md", "Odd ` mark then [x](missing.md).\n")
        self.assertEqual(self.verdict("a.md"), "DANGLING")

    def test_inline_code_span_pin_span_offset_preserved(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "See `[x](skip.md)` then [d](t.md#decision)<!--@-->.\n")
        self.stamp()
        content = self.read("a.md")
        self.assertIn("`[x](skip.md)`", content)
        self.assertRegex(content, r"\(t\.md#decision\)<!--@[0-9a-f]{8}-->")
        self.assertEqual(self.verdict("a.md"), "OK")

    def test_binary_target_treated_as_empty_unit(self):
        with open(os.path.join(self.d, "blob.bin"), "wb") as fh:
            fh.write(b"\x00\x01binary")
        self.write("a.md", "See [x](blob.bin).\n")
        # exists, unreadable-as-text -> resolves as an empty unit, not DANGLING
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

    def test_pin_after_sentence_punctuation(self):
        # the README's canonical form: `…#decision).<!--@-->` — punctuation
        # between the link and the pin must not silently demote it to unpinned
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "Per [d](t.md#decision).<!--@-->\n")
        self.assertEqual(self.verdict("a.md"), "UNSTAMPED")
        self.stamp()
        self.assertRegex(self.read("a.md"), r"\)\.<!--@[0-9a-f]{8}-->")
        self.assertEqual(self.verdict("a.md"), "OK")
        self.write("t.md", "# H\n\n## Decision\n\nWe chose Y instead.\n")
        self.assertEqual(self.verdict("a.md"), "DRIFTED")

    def test_pin_not_stolen_across_sentence(self):
        # a pin that belongs to a later link must not attach to an earlier one
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "See [a](t.md). Per [d](t.md#decision)<!--@-->.\n")
        vs = self.verdicts("a.md")
        self.assertEqual([v[0] for v in vs], ["OK", "UNSTAMPED"])

    def test_stamp_skips_dangling_ref(self):
        self.write("t.md", "# H\n\n## Real\n\nbody\n")
        self.write("a.md", "Per [d](t.md#ghost)<!--@-->.\n")
        self.stamp()
        self.assertIn("<!--@-->", self.read("a.md"))  # left empty, not filled
        self.assertEqual(self.verdict("a.md"), "DANGLING")

    def test_stamp_leaves_existing_pin_without_rebless(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "Per [d](t.md#decision)<!--@-->.\n")
        self.stamp()
        self.write("t.md", "# H\n\n## Decision\n\nWe chose Y instead.\n")
        self.assertEqual(self.verdict("a.md"), "DRIFTED")
        self.stamp()  # no --rebless
        self.assertEqual(self.verdict("a.md"), "DRIFTED")  # unchanged, still drifted

    def test_unpinned_code_ref_has_no_pin(self):
        self.write("t.md", "# H\n\n## Sec\n\nbody\n")
        self.write("caller.py", "# REF: t.md#sec\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "caller.py")
        self.assertIsNone(refs[0].pin)
        self.assertEqual(self.verdict("caller.py"), "OK")

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

    def test_suspects_all_flag_scans_code_files(self):
        self.write("lib.py", "# see other/module.py for details\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "suspects", "--json"])
        self.assertEqual(rc, 0)  # markdown-only by default: nothing scanned
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "suspects", "--all", "--json"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(buf.getvalue()),
                          [{"file": "lib.py", "line": 1, "target": "other/module.py"}])

    # --- ignore semantics --------------------------------------------------
    def test_reflockignore_skips_source_but_not_target(self):
        self.write(".reflockignore", "vendor/*.md\n")
        self.write("vendor/thirdparty.md", "See [x](missing.md).\n")  # would DANGLE if scanned
        self.write("a.md", "See [external](vendor/thirdparty.md) for details.\n")
        rc, findings = self.check_json()
        self.assertEqual(rc, 0)
        self.assertEqual(findings, [])

    # --- CLI / scoping -------------------------------------------------------
    def test_check_verbose_includes_ok(self):
        self.write("t.md", "# H\n\n## Real\n\nbody\n")
        self.write("a.md", "Good [x](t.md#real). Bad [y](missing.md).\n")
        rc, findings = self.check_json()
        self.assertEqual(rc, 1)
        self.assertEqual(len(findings), 1)  # OK hidden by default
        rc, findings = self.check_json("--verbose")
        self.assertEqual(rc, 1)
        self.assertEqual([f["verdict"] for f in findings], ["OK", "DANGLING"])

    def test_scoped_check_limits_to_path_arg(self):
        # path args are resolved relative to the process CWD (like git/find), not --root
        self.write("docs/a.md", "See [x](missing.md).\n")
        self.write("other/b.md", "See [y](missing2.md).\n")
        rc, findings = self.check_json(os.path.join(self.d, "docs"))
        self.assertEqual(rc, 1)
        self.assertEqual([f["file"] for f in findings], ["docs/a.md"])

    # --- colorized output ----------------------------------------------------
    def test_check_colors_verdict_labels_on_a_tty(self):
        self.write("a.md", "See [x](missing.md).\n")
        buf = _TTYBuffer()
        with contextlib.redirect_stdout(buf):
            reflock.main(["--root", self.d, "check"])
        self.assertIn(reflock.VERDICT_COLOR["DANGLING"], buf.getvalue())
        self.assertIn(reflock.COLOR_RESET, buf.getvalue())

    def test_no_color_flag_disables_color_on_a_tty(self):
        self.write("a.md", "See [x](missing.md).\n")
        buf = _TTYBuffer()
        with contextlib.redirect_stdout(buf):
            reflock.main(["--root", self.d, "check", "--no-color"])
        self.assertNotIn("\033[", buf.getvalue())

    def test_no_color_env_var_disables_color_on_a_tty(self):
        self.write("a.md", "See [x](missing.md).\n")
        buf = _TTYBuffer()
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}), \
             contextlib.redirect_stdout(buf):
            reflock.main(["--root", self.d, "check"])
        self.assertNotIn("\033[", buf.getvalue())

    def test_non_tty_stdout_has_no_color_by_default(self):
        # a plain io.StringIO().isatty() is False, so redirecting to a plain
        # buffer (the normal test setup, and any non-tty destination like a
        # file or pipe) never emits escape codes even without the flag/env var.
        self.write("a.md", "See [x](missing.md).\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            reflock.main(["--root", self.d, "check"])
        self.assertNotIn("\033[", buf.getvalue())

    def test_colorize_wraps_text_when_enabled(self):
        colored = reflock.colorize("DANGLING (1)", "DANGLING", True)
        self.assertIn("DANGLING (1)", colored)
        self.assertTrue(colored.startswith(reflock.VERDICT_COLOR["DANGLING"]))
        self.assertTrue(colored.endswith(reflock.COLOR_RESET))

    def test_colorize_is_noop_when_disabled(self):
        self.assertEqual(reflock.colorize("DANGLING (1)", "DANGLING", False), "DANGLING (1)")

    def test_use_color_true_when_tty_and_no_overrides(self):
        args = types.SimpleNamespace(no_color=False)
        with contextlib.redirect_stdout(_TTYBuffer()), \
             mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NO_COLOR", None)
            self.assertTrue(reflock.use_color(args))

    def test_use_color_false_when_no_color_flag_set(self):
        args = types.SimpleNamespace(no_color=True)
        with contextlib.redirect_stdout(_TTYBuffer()):
            self.assertFalse(reflock.use_color(args))

    # --- low-level helpers ---------------------------------------------------
    def test_resolve_path(self):
        self.assertEqual(reflock.resolve_path("docs/a.md", "b.md"), "docs/b.md")
        self.assertEqual(reflock.resolve_path("a.md", "sub/b.md"), "sub/b.md")
        self.assertIsNone(reflock.resolve_path("a.md", "../outside.md"))

    def test_normalize_strips_pin_and_collapses_whitespace(self):
        self.assertEqual(reflock.normalize("one   two\nthree"), b"one two three")
        self.assertEqual(reflock.normalize("text<!--@a1b2c3d4-->more"), b"textmore")


if __name__ == "__main__":
    unittest.main()
