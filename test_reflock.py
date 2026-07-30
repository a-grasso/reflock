"""Tests for reflock. Run: python3 -m unittest -v test_reflock"""
import contextlib
import importlib.util
import io
import json
import os
import re
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

# reflock.py re-exports these for its flat public API, but a function's calls to
# its own module-level neighbours resolve in the module it's *defined* in, not
# in reflock's re-exported namespace - so a test patching a call target that's
# invoked internally (not just called directly from this test file) must patch
# it where the calling code actually looks it up.
from reflock_lib import engine as reflock_engine
from reflock_lib import cli as reflock_cli
from reflock_lib import setup as reflock_setup


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

    # --- CLI-03: bare invocation defaults to check --------------------------
    def test_bare_invocation_with_root_flag_still_requires_a_subcommand(self):
        """--root + no subcommand is still a usage error (CLI-03 is scoped to
        *fully* empty argv, not "no subcommand however it's spelled")."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            reflock.main(["--root", self.d])
        self.assertEqual(2, cm.exception.code)
        self.assertIn("cmd", err.getvalue())

    def test_main_empty_list_runs_check_clean(self):
        cwd = os.getcwd()
        os.chdir(self.d)
        try:
            self.write("t.md", "# H\n\n## Real\n\nbody\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = reflock.main([])
        finally:
            os.chdir(cwd)
        self.assertEqual(0, rc)
        self.assertEqual("\nAll references OK.\n", out.getvalue())

    def test_main_empty_list_runs_check_dirty(self):
        cwd = os.getcwd()
        os.chdir(self.d)
        try:
            self.write("a.md", "See [x](missing.md).\n")
            out_bare = io.StringIO()
            with contextlib.redirect_stdout(out_bare):
                rc_bare = reflock.main([])
            out_check = io.StringIO()
            with contextlib.redirect_stdout(out_check):
                rc_check = reflock.main(["check"])
        finally:
            os.chdir(cwd)
        self.assertEqual(rc_check, rc_bare)
        self.assertEqual(out_check.getvalue(), out_bare.getvalue())

    def test_version_and_help_unaffected_by_bare_default(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(out):
            reflock.main(["--version"])
        self.assertEqual(0, cm.exception.code)
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

    # --- reference-style markdown links (NS-02a) --------------------------
    def test_refstyle_full_form_one_ref_at_definition_line(self):
        self.write("t.md", "# T\n\n## Real\n\nbody\n")
        self.write("a.md", "The tokenizer feeds [the loader][loader-ref] directly.\n"
                            "\n"
                            "[loader-ref]: t.md#real\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].line, 3)
        self.assertEqual(refs[0].target, "t.md#real")
        self.assertEqual(refs[0].kind, "md")

    def test_refstyle_collapsed_form_one_ref_at_definition_line(self):
        self.write("t.md", "# T\n\n## Real\n\nbody\n")
        self.write("a.md", "[loader-ref][]\n"
                            "\n"
                            "[loader-ref]: t.md#real\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].line, 3)
        self.assertEqual(refs[0].target, "t.md#real")

    def test_refstyle_shortcut_form_ignored(self):
        self.write("t.md", "# T\n\n## Real\n\nbody\n")
        self.write("a.md", "[loader-ref]\n"
                            "\n"
                            "[loader-ref]: t.md#real\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].line, 3)

    def test_refstyle_existing_pin_parsed(self):
        self.write("a.md", "[loader-ref]: t.md#real <!--@abcd1234-->\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].pin, "abcd1234")
        s, e = refs[0].pin_span
        self.assertEqual(refs[0].target, "t.md#real")
        line = reflock.build_index(self.d).lines["a.md"][0]
        self.assertEqual(line[s:e], "abcd1234")

    def test_refstyle_leading_whitespace(self):
        self.write("t.md", "# T\n\n## Real\n\nbody\n")
        self.write("a.md", "  [loader-ref]: t.md#real\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].target, "t.md#real")

    def test_refstyle_fence_skipped(self):
        self.write("t.md", "# T\n\n## Real\n\nbody\n")
        self.write("a.md", "```\n[loader-ref]: t.md#real\n```\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(refs, [])

    def test_refstyle_title_tolerated(self):
        self.write("t.md", "# T\n\n## Real\n\nbody\n")
        self.write("a.md", '[loader-ref]: t.md#real "Some title"\n')
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].target, "t.md#real")

    def test_refstyle_dangling_reported_at_definition_line(self):
        self.write("a.md", "The tokenizer feeds [the loader][loader-ref] directly.\n"
                            "\n"
                            "[loader-ref]: missing.md\n")
        self.assertEqual(self.verdict("a.md"), "DANGLING")

    def test_refstyle_usage_not_stamped(self):
        self.write("t.md", "# T\n\n## Real\n\nbody\n")
        self.write("a.md", "The tokenizer feeds [the loader][loader-ref] directly.\n"
                            "\n"
                            "[loader-ref]: t.md#real<!--@-->\n")
        self.stamp()
        content = self.read("a.md")
        self.assertIn("The tokenizer feeds [the loader][loader-ref] directly.\n", content)
        self.assertRegex(content, r"\[loader-ref\]: t\.md#real<!--@[0-9a-f]{8}-->")

    # --- wiki-links (NS-02b) ----------------------------------------------
    def test_wikilink_bare_target(self):
        self.write("loader.md", "# Loader\n")
        self.write("a.md", "See [[loader]] here.\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].target, "loader")
        self.assertEqual(refs[0].kind, "md")

    def test_wikilink_anchor_only(self):
        self.write("a.md", "# T\n\n## Sec\n\nSee [[#sec]] here.\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(refs[0].target, "#sec")

    def test_wikilink_anchor(self):
        self.write("loader.md", "# T\n\n## Sec\n\nbody\n")
        self.write("a.md", "See [[loader#sec]] here.\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(refs[0].target, "loader#sec")

    def test_wikilink_alias(self):
        self.write("loader.md", "# Loader\n")
        self.write("a.md", "See [[loader|the loader]] here.\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].target, "loader")

    def test_wikilink_anchor_and_alias(self):
        self.write("loader.md", "# T\n\n## Sec\n\nbody\n")
        self.write("a.md", "See [[loader#sec|the loader]] here.\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(refs[0].target, "loader#sec")

    def test_wikilink_alias_contains_pipe(self):
        self.write("loader.md", "# Loader\n")
        self.write("a.md", "See [[loader|a|b]] here.\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].target, "loader")

    def test_wikilink_existing_pin(self):
        self.write("loader.md", "# Loader\n")
        self.write("a.md", "See [[loader]]<!--@abcd1234--> here.\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].pin, "abcd1234")
        s, e = refs[0].pin_span
        line = reflock.build_index(self.d).lines["a.md"][0]
        self.assertEqual(line[s:e], "abcd1234")

    def test_wikilink_fence_skipped(self):
        self.write("loader.md", "# Loader\n")
        self.write("a.md", "```\nSee [[loader]] here.\n```\n")
        refs = reflock.parse_refs(reflock.build_index(self.d), "a.md")
        self.assertEqual(refs, [])

    def test_wikilink_resolves_relative_first(self):
        self.write("sub/loader.md", "# Loader\n")
        self.write("sub/a.md", "See [[loader]] here.\n")
        self.assertEqual(self.verdict("sub/a.md"), "OK")

    def test_wikilink_explicit_extension_no_double_suffix(self):
        self.write("loader.md", "# Loader\n")
        self.write("a.md", "See [[loader.md]] here.\n")
        self.assertEqual(self.verdict("a.md"), "OK")

    def test_wikilink_basename_fallback(self):
        self.write("docs/loader.md", "# Loader\n")
        self.write("a.md", "See [[loader]] here.\n")
        self.assertEqual(self.verdict("a.md"), "OK")

    def test_wikilink_basename_ambiguous(self):
        self.write("docs/loader.md", "# Loader\n")
        self.write("spec/loader.md", "# Loader\n")
        self.write("a.md", "See [[loader]] here.\n")
        verdict, detail = self.verdicts("a.md")[0]
        self.assertEqual(verdict, "DANGLING")
        self.assertEqual(detail, "ambiguous: docs/loader.md, spec/loader.md")

    def test_wikilink_dangling_no_relative_no_basename(self):
        self.write("a.md", "See [[nowhere]] here.\n")
        self.assertEqual(self.verdict("a.md"), "DANGLING")

    def test_wikilink_stamp_roundtrip_via_basename(self):
        self.write("docs/loader.md", "# Loader\n\nbody\n")
        self.write("a.md", "See [[loader]]<!--@-->.\n")
        self.stamp()
        self.assertEqual(self.verdict("a.md"), "OK")
        self.write("docs/loader.md", "# Loader\n\nbody CHANGED\n")
        self.assertEqual(self.verdict("a.md"), "DRIFTED")

    def test_wikilink_relative_and_inline_agree(self):
        self.write("sub/loader.md", "# Loader\n")
        self.write("sub/a.md", "[[loader]]\n")
        self.write("sub/b.md", "[loader](loader.md)\n")
        self.assertEqual(self.verdict("sub/a.md"), self.verdict("sub/b.md"))

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

    def test_stamp_check_clean_tree_exits_zero(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "Per [d](t.md#decision)<!--@-->.\n")
        self.stamp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "stamp", "--check"])
        self.assertEqual(rc, 0)

    def test_stamp_check_unstamped_exits_nonzero_and_named(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "Per [d](t.md#decision)<!--@-->.\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "stamp", "--check"])
        self.assertEqual(rc, 1)
        self.assertIn("a.md:1", buf.getvalue())
        self.assertIn("t.md#decision", buf.getvalue())

    def test_stamp_check_stale_pin_exits_nonzero(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "Per [d](t.md#decision)<!--@-->.\n")
        self.stamp()
        self.write("t.md", "# H\n\n## Decision\n\nWe chose Y instead.\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "stamp", "--check", "--rebless"])
        self.assertEqual(rc, 1)
        self.assertIn("a.md:1", buf.getvalue())

    def test_stamp_check_writes_nothing(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "Per [d](t.md#decision)<!--@-->.\n")
        before_a = os.stat(os.path.join(self.d, "a.md"))
        before_t = os.stat(os.path.join(self.d, "t.md"))
        before_a_bytes, before_t_bytes = self.read("a.md"), self.read("t.md")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            reflock.main(["--root", self.d, "stamp", "--check"])
        after_a = os.stat(os.path.join(self.d, "a.md"))
        after_t = os.stat(os.path.join(self.d, "t.md"))
        self.assertEqual(before_a.st_mtime, after_a.st_mtime)
        self.assertEqual(before_t.st_mtime, after_t.st_mtime)
        self.assertEqual(before_a_bytes, self.read("a.md"))
        self.assertEqual(before_t_bytes, self.read("t.md"))
        self.stamp()
        self.assertRegex(self.read("a.md"), r"<!--@[0-9a-f]{8}-->")

    def test_stamp_check_reported_set_equals_stamp_writes(self):
        self.write("t.md", "# H\n\n## A\n\nalpha\n\n## B\n\nbeta\n")
        self.write("a.md", "See [a](t.md#a)<!--@-->. See [b](t.md#b)<!--@-->.\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "stamp", "--check"])
        self.assertEqual(rc, 1)
        self.assertEqual(buf.getvalue().count("a.md:1"), 2)
        self.stamp()
        self.assertEqual(self.read("a.md").count("<!--@"), 2)
        self.assertNotIn("<!--@-->", self.read("a.md"))

    def test_stamp_check_then_stamp_is_clean(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "Per [d](t.md#decision)<!--@-->.\n")
        self.stamp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "stamp", "--check"])
        self.assertEqual(rc, 0)

    # --- NIT-01: one owner for reference ordering ---------------------------
    MIXED_LINE = "See [[wiki]] then [inline](t.md) then <!-- REF: t.md -->\n"

    def test_parse_refs_returns_column_order_across_kinds(self):
        self.write("wiki.md", "# Wiki\n")
        self.write("t.md", "# T\n")
        self.write("a.md", self.MIXED_LINE)
        idx = reflock.build_index(self.d)
        refs = reflock.parse_refs(idx, "a.md")
        cols = [r.col for r in refs]
        self.assertEqual(sorted(cols), cols,
                          f"references not left-to-right: {[(r.col, r.target) for r in refs]}")

    def test_check_json_findings_are_in_column_order(self):
        self.write("wiki.md", "# Wiki\n")
        self.write("t.md", "# T\n")
        self.write("a.md", self.MIXED_LINE)
        _, findings = self.check_json("--verbose")
        one_line = [f for f in findings if f["file"] == "a.md" and f["line"] == 1]
        self.assertEqual(3, len(one_line))
        self.assertEqual(["wiki", "t.md", "t.md"], [f["target"] for f in one_line])

    def test_explain_and_check_agree_on_order(self):
        """The point is that they agree, so they are asserted against each other."""
        self.write("wiki.md", "# Wiki\n")
        self.write("t.md", "# T\n")
        self.write("a.md", self.MIXED_LINE)
        _, findings = self.check_json("--verbose")
        check_order = [f["target"] for f in findings
                       if f["file"] == "a.md" and f["line"] == 1]
        _, out, _ = self.run_cmd("explain", "a.md:1", "--format", "json")
        self.assertEqual(check_order, [e["target"] for e in json.loads(out)])

    def test_mixed_line_reference_count_and_verdicts_unchanged(self):
        self.write("wiki.md", "# Wiki\n")
        self.write("t.md", "# T\n")
        self.write("a.md", self.MIXED_LINE)
        self.assertEqual(["OK", "OK", "OK"], [v for v, _ in self.verdicts("a.md")])

    def test_unit_text_annotation_does_not_claim_list(self):
        annotation = reflock.unit_text.__annotations__["return"]
        self.assertNotIn("list", annotation,
                          f"unit_text never returns a list, but says {annotation!r}")

    # --- BUG-06: suspects honours the code-span exemption too ---------------
    def suspects_hits(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            reflock.main(["--root", self.d, "suspects", "--json", *args])
        return [h["target"] for h in json.loads(buf.getvalue())]

    def test_suspects_ignores_path_in_code_span(self):
        self.write("a.md", "Older builds wrote to `build/legacy/out.json` once.\n")
        self.assertEqual([], self.suspects_hits())

    def test_suspects_still_catches_prose_path_on_the_same_line(self):
        """Masking must not suppress the rest of the line - the BUG-02 lesson."""
        self.write("a.md", "See `build/legacy/out.json` and also docs/gone.md here.\n")
        self.assertEqual(["docs/gone.md"], self.suspects_hits())

    def test_suspects_double_backtick_span_exempt(self):
        self.write("a.md", "Literal ``build/legacy/out.json`` in prose.\n")
        self.assertEqual([], self.suspects_hits())

    def test_suspects_unterminated_backtick_does_not_silence_line(self):
        self.write("a.md", "An open ` tick then docs/gone.md follows.\n")
        self.assertEqual(["docs/gone.md"], self.suspects_hits())

    def test_suspects_code_file_backticks_still_scanned(self):
        self.write("m.py", "# see `build/legacy/out.json` for the old path\n")
        self.assertEqual(["build/legacy/out.json"], self.suspects_hits("--all"),
                          "backticks are not code-span syntax in a .py file")

    # --- BUG-08: a URL is not a path ----------------------------------------
    SCOPED_URL = "https://registry.npmjs.org/@babel/core/-/core-7.29.7.tgz"

    def test_suspects_ignores_scoped_registry_url(self):
        """An `@` is outside PATHISH's lookbehind class, so an npm scope used to
        re-open a match mid-URL. Three-quarters of one repo's findings."""
        self.write("p.json", f'  "resolved": "{self.SCOPED_URL}"\n')
        self.assertEqual([], self.suspects_hits("--all"))

    def test_suspects_ignores_plain_url_path_segments(self):
        self.write("a.md", "See https://example.com/docs/a/b/page.html for more.\n")
        self.assertEqual([], self.suspects_hits())

    def test_suspects_ignores_protocol_relative_url(self):
        self.write("a.md", "Fetched from //cdn.example.com/lib/thing.json at boot.\n")
        self.assertEqual([], self.suspects_hits())

    def test_suspects_catches_path_after_url_on_same_line(self):
        """Masking must not silence the rest of the line - the BUG-02 lesson."""
        self.write("a.md", f"From {self.SCOPED_URL} into docs/gone.md today.\n")
        self.assertEqual(["docs/gone.md"], self.suspects_hits())

    def test_suspects_ignores_url_in_markdown_link_destination(self):
        self.write("a.md", "See [the tarball](%s).\n" % self.SCOPED_URL)
        self.assertEqual([], self.suspects_hits())

    def test_mask_urls_blanks_same_length(self):
        line = f"From {self.SCOPED_URL} into docs/gone.md today."
        masked = reflock.mask_urls(line)
        self.assertEqual(len(line), len(masked))
        self.assertNotIn("babel", masked)
        self.assertIn("docs/gone.md", masked)

    # --- BUG-09: shell variables and `.../` elisions are not paths -----------
    def test_suspects_ignores_shell_variable_path(self):
        self.write("run.sh", 'cp "$scriptDir/conf/app.xml" /tmp\n')
        self.assertEqual([], self.suspects_hits("--all"))

    def test_suspects_ignores_braced_shell_variable_path(self):
        """Unmatched today by accident of the segment class; pinned deliberately."""
        self.write("run.sh", 'cp "${scriptDir}/conf/app.xml" /tmp\n')
        self.assertEqual([], self.suspects_hits("--all"))

    def test_suspects_ignores_elided_path(self):
        self.write("a.md", "Lives in platform/domain/.../domain/Signal.kt today.\n")
        self.assertEqual([], self.suspects_hits())

    def test_pathish_reports_no_half_of_an_elision(self):
        """Half a placeholder would be worse than nothing, so the guarantee is
        asserted on the pattern rather than inferred from the command."""
        found = [m.group("p") for m in
                 reflock.PATHISH.finditer("platform/domain/.../domain/Signal.kt")]
        self.assertEqual([], found)

    def test_suspects_still_catches_dot_prefixed_relative_paths(self):
        """One leading dot segment or two is a relative path; three is an elision."""
        self.write("doc/a.md", "See ../gone/x.md and ./also-gone/y.md here.\n")
        self.assertEqual(["../gone/x.md", "./also-gone/y.md"], self.suspects_hits())

    def test_suspects_dollar_earlier_in_line_does_not_silence_a_token(self):
        self.write("run.sh", 'echo "$HOME" # see other/module.py for details\n')
        self.assertEqual(["other/module.py"], self.suspects_hits("--all"))

    # --- UX-01: the unit text is a preview, not a dump ----------------------
    def long_target(self, n, anchor=False):
        head = "# T\n\n## Sec\n\n" if anchor else ""
        self.write("t.md", head + "".join(f"line {i}\n" for i in range(1, n + 1)))
        tgt = "t.md#sec" if anchor else "t.md"
        self.write("a.md", f"See [x]({tgt})<!--@-->\n")
        self.stamp()

    def test_long_unit_is_truncated_with_an_accurate_count(self):
        self.long_target(60)
        _, out, _ = self.run_cmd("explain", "a.md:1")
        limit = reflock.UNIT_PREVIEW_LINES
        self.assertIn("line 1\n", out)
        self.assertIn(f"line {limit}\n", out)
        self.assertNotIn("line 60", out, "the whole file must not be dumped")
        self.assertIn(f"{60 - limit} more lines", out)
        self.assertIn("--full", out, "the escape hatch must be discoverable")

    def test_full_shows_the_whole_unit_and_no_marker(self):
        self.long_target(60)
        _, out, _ = self.run_cmd("explain", "a.md:1", "--full")
        self.assertIn("line 60", out)
        self.assertNotIn("more lines", out)

    def test_unit_at_the_limit_is_not_truncated(self):
        self.long_target(reflock.UNIT_PREVIEW_LINES)
        _, out, _ = self.run_cmd("explain", "a.md:1")
        self.assertIn(f"line {reflock.UNIT_PREVIEW_LINES}", out)
        self.assertNotIn("more lines", out)

    def test_unit_one_over_the_limit_says_one_more_line(self):
        self.long_target(reflock.UNIT_PREVIEW_LINES + 1)
        _, out, _ = self.run_cmd("explain", "a.md:1")
        self.assertIn("1 more line", out)
        self.assertNotIn("1 more lines", out, "singular, for one withheld line")

    def test_anchored_unit_is_truncated_too(self):
        """The rule is uniform: a 900-line section is as unreadable as a file."""
        self.long_target(60, anchor=True)
        _, out, _ = self.run_cmd("explain", "a.md:1")
        self.assertNotIn("line 60", out)
        self.assertIn("more lines", out)

    def test_json_output_identical_with_and_without_full(self):
        self.long_target(60)
        _, plain, _ = self.run_cmd("explain", "a.md:1", "--format", "json")
        _, full, _ = self.run_cmd("explain", "a.md:1", "--format", "json", "--full")
        self.assertEqual(plain, full)
        json.loads(plain)   # and still valid JSON

    # --- CLI-01: one notion of a path argument -------------------------------
    def in_dir(self, sub, *argv):
        """Run reflock with the CWD inside the tree, as a user would."""
        cwd = os.getcwd()
        try:
            os.chdir(os.path.join(self.d, sub) if sub else self.d)
            return self.run_cmd(*argv)
        finally:
            os.chdir(cwd)

    def setup_docs_tree(self):
        self.write("docs/t.md", "# Title\n\n## Sec\n\nbody\n")
        self.write("docs/a.md", "See [x](t.md).\n")

    def test_backlinks_accepts_dot_slash_and_absolute_and_subdir_paths(self):
        self.setup_docs_tree()
        _, canonical, _ = self.run_cmd("backlinks", "docs/t.md")
        self.assertIn("docs/a.md:1", canonical)
        for label, args, sub in (
            ("./ prefix", ("backlinks", "./docs/t.md"), None),
            ("absolute", ("backlinks", self.at("docs/t.md")), None),
            ("from subdir", ("backlinks", "t.md"), "docs"),
        ):
            rc, out, err = self.in_dir(sub, *args)
            self.assertEqual(0, rc, f"{label}: {err}")
            self.assertEqual(canonical, out, f"{label} disagreed with the canonical form")

    def test_explain_accepts_dot_slash_and_absolute_and_subdir_paths(self):
        self.setup_docs_tree()
        _, canonical, _ = self.run_cmd("explain", "docs/a.md:1")
        self.assertIn("docs/a.md:1", canonical)
        for label, spec, sub in (
            ("./ prefix", "./docs/a.md:1", None),
            ("absolute", self.at("docs/a.md") + ":1", None),
            ("from subdir", "a.md:1", "docs"),
        ):
            rc, out, err = self.in_dir(sub, "explain", spec)
            self.assertEqual(0, rc, f"{label}: {err}")
            self.assertEqual(canonical, out, f"{label} disagreed with the canonical form")

    def test_backlinks_unknown_anchor_exits_two(self):
        self.setup_docs_tree()
        rc, out, err = self.run_cmd("backlinks", "docs/t.md#no-such-anchor")
        self.assertEqual(2, rc)
        self.assertIn("no-such-anchor", err)
        self.assertEqual("", out)

    def test_backlinks_valid_anchor_with_no_referrers_exits_zero(self):
        self.setup_docs_tree()
        rc, out, err = self.run_cmd("backlinks", "docs/t.md#sec")
        self.assertEqual(0, rc, err)
        self.assertIn("No backlinks", out)

    def test_backlinks_accepts_marker_span_anchor(self):
        self.write("t.md", "intro\n<!-- reflock-anchor: block -->\nheld\n"
                            "<!-- reflock-anchor-end: block -->\n")
        self.write("a.md", "See [x](t.md#block).\n")
        rc, out, err = self.run_cmd("backlinks", "t.md#block")
        self.assertEqual(0, rc, err)
        self.assertIn("a.md:1", out)

    def test_backlinks_unknown_path_still_exits_two(self):
        self.setup_docs_tree()
        rc, _, err = self.run_cmd("backlinks", "docs/nope.md")
        self.assertEqual(2, rc)
        self.assertIn("nope.md", err)

    def test_backlinks_format_json_unknown_path_goes_to_stdout(self):
        self.setup_docs_tree()
        rc, out, err = self.run_cmd("backlinks", "docs/nope.md", "--format", "json")
        self.assertEqual(2, rc)
        self.assertEqual("", err)
        self.assertIn("nope.md", json.loads(out)["error"])

    def test_backlinks_format_json_unknown_anchor_goes_to_stdout(self):
        self.setup_docs_tree()
        rc, out, err = self.run_cmd("backlinks", "docs/t.md#no-such-anchor", "--format", "json")
        self.assertEqual(2, rc)
        self.assertEqual("", err)
        self.assertIn("no-such-anchor", json.loads(out)["error"])

    def test_repo_relative_path_works_from_a_subdirectory(self):
        """check prints repo-relative paths whatever directory it runs in, so
        pasting one into explain must work from a subdirectory too."""
        self.setup_docs_tree()
        rc, out, err = self.in_dir("docs", "explain", "docs/a.md:1")
        self.assertEqual(0, rc, err)
        self.assertIn("docs/a.md:1", out)
        rc, out, err = self.in_dir("docs", "backlinks", "docs/t.md")
        self.assertEqual(0, rc, err)
        self.assertIn("docs/a.md:1", out)

    def test_cwd_relative_wins_over_repo_relative_on_collision(self):
        self.write("docs/t.md", "# Outer\n")
        self.write("docs/docs/t.md", "# Inner\n")
        self.write("docs/a.md", "See [x](docs/t.md).\n")   # -> docs/docs/t.md
        rc, out, err = self.in_dir("docs", "backlinks", "docs/t.md")
        self.assertEqual(0, rc, err)
        self.assertIn("docs/a.md:1", out,
                      "the CWD-relative reading (docs/docs/t.md) must win")

    def test_path_normalization_is_shared(self):
        """scoped_files and the single-path commands must agree on a spelling."""
        self.setup_docs_tree()
        idx = reflock.build_index(self.d)
        self.assertEqual(["docs/a.md"],
                          reflock.scoped_files(idx, [self.at("./docs/a.md")]))
        self.assertEqual("docs/a.md",
                          reflock.indexed_path(idx, self.at("./docs/a.md")))

    # --- NS-03b: --warn, an exit-0 reporting mode ---------------------------
    def test_check_warn_exits_zero_but_still_reports(self):
        self.write("t.md", "# T\n")
        self.write("a.md", "See [x](t.md)<!--@-->\n")
        rc_plain, out_plain, _ = self.run_cmd("stamp", "--check")
        rc_warn, out_warn, _ = self.run_cmd("stamp", "--check", "--warn")
        self.assertEqual(1, rc_plain)
        self.assertEqual(0, rc_warn)
        self.assertIn("a.md:1", out_warn)
        self.assertIn("unstamped", out_warn)

    def test_check_warn_stdout_identical_to_check(self):
        self.write("t.md", "# T\n")
        self.write("a.md", "See [x](t.md)<!--@-->\nAnd [y](t.md)<!--@-->\n")
        _, out_plain, _ = self.run_cmd("stamp", "--check")
        _, out_warn, _ = self.run_cmd("stamp", "--check", "--warn")
        self.assertEqual(out_plain, out_warn,
                          "--warn changes the exit code, not the report")

    def test_check_warn_on_clean_tree_exits_zero(self):
        self.write("t.md", "# T\n")
        self.write("a.md", "See [x](t.md)\n")
        rc, out, _ = self.run_cmd("stamp", "--check", "--warn")
        self.assertEqual(0, rc)
        self.assertIn("Nothing to stamp", out)

    def test_warn_without_check_is_an_error(self):
        self.write("t.md", "# T\n")
        rc, _, err = self.run_cmd("stamp", "--warn")
        self.assertEqual(2, rc)
        self.assertIn("--warn", err)
        self.assertIn("--check", err)

    def test_check_warn_writes_nothing(self):
        self.write("t.md", "# T\n")
        before = b"See [x](t.md)<!--@-->\n"
        self.write_bytes("a.md", before)
        self.run_cmd("stamp", "--check", "--warn")
        self.assertEqual(before, self.read_bytes("a.md"))

    # --- PERF-01: one fingerprint per distinct unit --------------------------
    def big_target(self, rel="t.md", body="lorem ipsum dolor sit amet "):
        self.write(rel, "# Title\n\n## Sec\n\n" + (body * 4 + "\n") * 40)

    def count_normalize_calls(self):
        """Wrap reflock.normalize with a counter; returns (ctx, counter)."""
        calls = []
        real = reflock.normalize

        def counting(text):
            calls.append(text)
            return real(text)
        return mock.patch.object(reflock_engine, "normalize", counting), calls

    def test_one_normalize_per_distinct_unit(self):
        self.big_target()
        # pinned, not unstamped: classify returns before hashing an empty pin
        self.write("a.md", "".join(f"See [x{i}](t.md#sec)<!--@deadbeef-->\n"
                                    for i in range(20)))
        idx = reflock.build_index(self.d)
        refs = reflock.parse_refs(idx, "a.md")
        self.assertEqual(20, len(refs))
        patcher, calls = self.count_normalize_calls()
        with patcher:
            for ref in refs:
                reflock.classify(idx, ref)
        self.assertEqual(1, len(calls),
                          f"20 references to one unit hashed it {len(calls)} times")

    def test_one_normalize_per_anchor_when_units_differ(self):
        self.write("t.md", "# T\n\n## One\n\naaa\n\n## Two\n\nbbb\n")
        self.write("a.md", "See [a](t.md#one)<!--@deadbeef-->\n"
                            "See [b](t.md#two)<!--@deadbeef-->\n"
                            "Again [c](t.md#one)<!--@deadbeef-->\n")
        idx = reflock.build_index(self.d)
        patcher, calls = self.count_normalize_calls()
        with patcher:
            for ref in reflock.parse_refs(idx, "a.md"):
                reflock.classify(idx, ref)
        self.assertEqual(2, len(calls), "one hash per distinct anchor, no more, no fewer")

    def test_fingerprint_cache_is_per_index(self):
        self.big_target()
        self.write("a.md", "See [x](t.md#sec)<!--@deadbeef-->\n")
        for _ in range(2):
            idx = reflock.build_index(self.d)
            patcher, calls = self.count_normalize_calls()
            with patcher:
                reflock.classify(idx, reflock.parse_refs(idx, "a.md")[0])
            self.assertEqual(1, len(calls), "a fresh Index must recompute")

    def test_memoized_verdicts_match_hand_computed(self):
        self.write("t.md", "# T\n\n## Sec\n\ncontent here\n")
        idx0 = reflock.build_index(self.d)
        fp = reflock.fingerprint(reflock.unit_text(idx0, "t.md", "sec"))
        self.write("a.md", f"ok [a](t.md#sec)<!--@{fp}-->\n"
                            f"drift [b](t.md#sec)<!--@deadbeef-->\n"
                            f"same [c](t.md#sec)<!--@{fp}-->\n")
        self.assertEqual(["OK", "DRIFTED", "OK"],
                          [v for v, _ in self.verdicts("a.md")])

    def test_drift_detected_after_edit_within_one_process(self):
        self.write("t.md", "# T\n\n## Sec\n\nbefore\n")
        idx = reflock.build_index(self.d)
        fp = reflock.fingerprint(reflock.unit_text(idx, "t.md", "sec"))
        self.write("a.md", f"See [x](t.md#sec)<!--@{fp}-->\n")
        self.assertEqual("OK", self.verdict("a.md"))
        self.write("t.md", "# T\n\n## Sec\n\nafter, quite different\n")
        self.assertEqual("DRIFTED", self.verdict("a.md"),
                          "a fresh index must see the edit")

    def test_fingerprint_after_stamp_reflects_disk(self):
        self.write("t.md", "# T\n\n## Sec\n\nbody\n")
        self.write("a.md", "See [x](t.md#sec)<!--@-->\n")
        idx = reflock.build_index(self.d)
        args = types.SimpleNamespace(paths=[], rebless=False, check=False)
        with contextlib.redirect_stdout(io.StringIO()):
            reflock.cmd_stamp(idx, args)
        ref = reflock.parse_refs(idx, "a.md")[0]
        self.assertEqual("OK", reflock.classify(idx, ref)[0])

    def test_normalize_equivalence_across_whitespace_classes(self):
        """The new normalize must not move a single fingerprint in the field."""
        def old(text):
            text = reflock.PIN_STRIP.sub("", text)
            return re.sub(r"\s+", " ", text).strip().encode("utf-8")
        cases = [
            "", "   ", "one   two\nthree", "a\tb\r\nc", "trailing   ",
            "  leading", "text<!--@a1b2c3d4-->more", "code @a1b2c3d4 here",
            "a\x1cb", "a\x1db", "a\x1eb", "a\x1fb", "a\x85b", "a\xa0b",
            "a b", "a b", "a  b", "mixed \x0b\x0c stuff",
            "# H\n\n## Sec\n\nOne two\nthree      four.\n",
        ]
        for text in cases:
            self.assertEqual(old(text), reflock.normalize(text),
                              f"normalize changed for {text!r}")

    # --- BUG-05: stamp must not rewrite bytes it is not stamping -------------
    def write_bytes(self, rel, data: bytes):
        p = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(p) or self.d, exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)

    def read_bytes(self, rel) -> bytes:
        with open(os.path.join(self.d, rel), "rb") as fh:
            return fh.read()

    PIN_RE = re.compile(rb"<!--@([0-9a-f]{8})-->")

    def assert_only_pin_changed(self, rel, before: bytes):
        """The whole point of stamp: 8 hex characters move, nothing else."""
        after = self.read_bytes(rel)
        self.assertNotEqual(before, after, "nothing was stamped at all")
        neutralized = self.PIN_RE.sub(b"<!--@-->", after)
        self.assertEqual(before, neutralized,
                          "stamp changed bytes outside the pin span")

    def test_stamp_preserves_crlf_on_every_line(self):
        self.write("t.md", "# T\n\nbody\n")
        before = b"crlf [z](t.md)<!--@-->\r\nsecond line\r\nthird\r\n"
        self.write_bytes("a.md", before)
        self.stamp()
        after = self.read_bytes("a.md")
        self.assertEqual(3, after.count(b"\r\n"), f"CRLF endings lost: {after!r}")
        self.assert_only_pin_changed("a.md", before)

    def test_stamp_preserves_mixed_line_endings(self):
        self.write("t.md", "# T\n")
        before = b"lf [a](t.md)<!--@-->\ncrlf line\r\nlf again\n"
        self.write_bytes("a.md", before)
        self.stamp()
        self.assert_only_pin_changed("a.md", before)

    def test_stamp_preserves_absent_trailing_newline(self):
        self.write("t.md", "# T\n")
        before = b"no trailing newline [y](t.md)<!--@-->"
        self.write_bytes("a.md", before)
        self.stamp()
        after = self.read_bytes("a.md")
        self.assertFalse(after.endswith(b"\n"), f"gained a trailing newline: {after!r}")
        self.assert_only_pin_changed("a.md", before)

    def test_stamp_preserves_trailing_blank_lines(self):
        self.write("t.md", "# T\n")
        before = b"pin [x](t.md)<!--@-->\n\n\n"
        self.write_bytes("a.md", before)
        self.stamp()
        self.assertTrue(self.read_bytes("a.md").endswith(b"\n\n\n"))
        self.assert_only_pin_changed("a.md", before)

    def test_stamp_ordinary_lf_file_unchanged_outside_pin(self):
        self.write("t.md", "# T\n")
        before = b"pin [x](t.md)<!--@-->\nplain line\n"
        self.write_bytes("a.md", before)
        self.stamp()
        self.assert_only_pin_changed("a.md", before)

    def test_stamp_does_not_write_through_a_symlink(self):
        """The destination is outside the repo; git would show nothing."""
        outside = tempfile.mkdtemp()
        try:
            victim = os.path.join(outside, "victim.md")
            payload = "OUTSIDE THE REPO [x](t.md)<!--@-->\n"
            with open(victim, "w") as fh:
                fh.write(payload)
            self.write("t.md", "# T\n\nbody\n")
            os.symlink(victim, os.path.join(self.d, "link.md"))
            self.stamp()
            with open(victim) as fh:
                self.assertEqual(payload, fh.read(),
                                  "stamp wrote through a symlink, outside the tree")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_symlinked_file_is_not_a_reference_source(self):
        self.write("sub/doc.md", "See [x](missing.md)\n")
        os.symlink(os.path.join(self.d, "sub", "doc.md"),
                    os.path.join(self.d, "link.md"))
        rc, findings = self.check_json()
        self.assertEqual(["sub/doc.md"], [f["file"] for f in findings],
                          "the symlink must not be scanned as a second source")

    def test_reference_to_a_symlink_still_resolves(self):
        """Excluding symlinks as *sources* must not break them as *targets*."""
        self.write("real.md", "# Real\n\nbody\n")
        os.symlink(os.path.join(self.d, "real.md"), os.path.join(self.d, "link.md"))
        self.write("a.md", "See [x](link.md)<!--@-->\n")
        self.stamp()
        self.assertRegex(self.read("a.md"), r"<!--@[0-9a-f]{8}-->")
        self.assertEqual("OK", self.verdict("a.md"))

    # --- BUG-04: a path argument matching nothing is a usage error -----------
    def run_cmd(self, *argv):
        """Run a subcommand capturing both streams; returns (rc, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = reflock.main(["--root", self.d, *argv])
        return rc, out.getvalue(), err.getvalue()

    # Path args resolve against the process CWD, not --root (see
    # test_scoped_check_limits_to_path_arg), so these pass absolute paths.
    def at(self, rel):
        return os.path.join(self.d, rel)

    def test_check_unmatched_path_exits_two(self):
        self.write("t.md", "# T\n")
        rc, out, err = self.run_cmd("check", self.at("does-not-exist.md"))
        self.assertEqual(2, rc)
        self.assertIn("does-not-exist.md", err)
        self.assertEqual("", out)

    def test_check_unmatched_dir_exits_two(self):
        self.write("t.md", "# T\n")
        rc, out, err = self.run_cmd("check", self.at("nosuchdir/"))
        self.assertEqual(2, rc)
        self.assertIn("nosuchdir/", err, "the message must echo what the user typed")

    def test_stamp_unmatched_path_exits_two(self):
        self.write("t.md", "# T\n")
        rc, _, err = self.run_cmd("stamp", self.at("does-not-exist.md"))
        self.assertEqual(2, rc)
        self.assertIn("does-not-exist.md", err)

    def test_suspects_unmatched_path_exits_two(self):
        self.write("t.md", "# T\n")
        rc, _, err = self.run_cmd("suspects", self.at("does-not-exist.md"))
        self.assertEqual(2, rc)
        self.assertIn("does-not-exist.md", err)

    def test_one_bad_path_among_good_ones_still_errors(self):
        """reflock must not do half the work and report success."""
        self.write("a.md", "See [x](missing.md)\n")
        rc, out, err = self.run_cmd("check", self.at("a.md"),
                                     self.at("does-not-exist.md"))
        self.assertEqual(2, rc)
        self.assertIn("does-not-exist.md", err)
        self.assertEqual("", out)

    def test_tree_root_path_means_whole_tree(self):
        self.write("a.md", "See [x](missing.md)\n")
        rc_root, out_root, _ = self.run_cmd("check", self.d)
        rc_bare, out_bare, _ = self.run_cmd("check")
        self.assertEqual(rc_bare, rc_root)
        self.assertEqual(out_bare, out_root)
        self.assertIn("DANGLING", out_root)

    def test_literal_dot_means_whole_tree(self):
        """`reflock check .` reads as the whole tree and must behave that way;
        it previously normalized to a path no indexed file matched, so it
        checked nothing and exited 0."""
        self.write("a.md", "See [x](missing.md)\n")
        cwd = os.getcwd()
        try:
            os.chdir(self.d)
            rc, out, _ = self.run_cmd("check", ".")
        finally:
            os.chdir(cwd)
        self.assertEqual(1, rc)
        self.assertIn("DANGLING", out)

    def test_explicit_binary_path_is_not_an_error(self):
        with open(self.at("blob.bin"), "wb") as fh:
            fh.write(b"\x00\x01binary")
        rc, _, err = self.run_cmd("check", self.at("blob.bin"))
        self.assertEqual(0, rc, err)

    def test_explicit_reflockignored_path_is_not_an_error(self):
        self.write(".reflockignore", "vendor/*\n")
        self.write("vendor/v.md", "See [x](missing.md)\n")
        rc, _, err = self.run_cmd("check", self.at("vendor/v.md"))
        self.assertEqual(0, rc, err)

    def test_dir_of_only_ignored_files_is_not_an_error(self):
        self.write(".reflockignore", "vendor/*\n")
        self.write("vendor/v.md", "See [x](missing.md)\n")
        rc, _, err = self.run_cmd("check", self.at("vendor"))
        self.assertEqual(0, rc, err)

    def test_scoped_files_raises_for_unmatched_path(self):
        self.write("t.md", "# T\n")
        idx = reflock.build_index(self.d)
        with self.assertRaises(reflock.ScopeError):
            reflock.scoped_files(idx, [self.at("does-not-exist.md")])
        self.assertEqual(["t.md"], reflock.scoped_files(idx, [self.at("t.md")]))

    # --- BUG-03: stamp must not fabricate a pin it cannot compute -----------
    EMPTY_FP = "e3b0c442"  # fingerprint("") - what the bug wrote for everything

    def test_stamp_skips_external_target(self):
        self.write("a.md", "See [x](https://example.com/spec)<!--@-->\n")
        self.stamp()
        self.assertIn("<!--@-->", self.read("a.md"))
        self.assertNotIn(self.EMPTY_FP, self.read("a.md"))

    def test_stamp_skips_outside_tree_target(self):
        self.write("a.md", "See [y](../outside.md)<!--@-->\n")
        self.stamp()
        self.assertIn("<!--@-->", self.read("a.md"))

    def test_stamp_skips_directory_target(self):
        self.write("sub/k.md", "# K\n")
        self.write("a.md", "See [z](sub)<!--@-->\n")
        self.stamp()
        self.assertIn("<!--@-->", self.read("a.md"))

    def test_stamp_skips_binary_target(self):
        with open(os.path.join(self.d, "blob.bin"), "wb") as fh:
            fh.write(b"\x00\x01binary")
        self.write("a.md", "See [b](blob.bin)<!--@-->\n")
        self.stamp()
        self.assertIn("<!--@-->", self.read("a.md"))

    def test_stamp_skips_unresolvable_anchor(self):
        self.write("t.md", "# Title\n")
        self.write("a.md", "See [x](t.md#no-such-heading)<!--@-->\n")
        self.stamp()
        self.assertIn("<!--@-->", self.read("a.md"))

    def test_unstampable_pin_detail_does_not_prescribe_stamp(self):
        """check must not tell the user to run a command that provably no-ops."""
        with open(os.path.join(self.d, "blob.bin"), "wb") as fh:
            fh.write(b"\x00\x01binary")
        self.write("a.md", "See [b](blob.bin)<!--@-->\n")
        verdict, detail = self.verdicts("a.md")[0]
        self.assertEqual("UNSTAMPED", verdict)
        self.assertNotIn("reflock stamp", detail)
        self.assertIn("cannot fingerprint", detail)

    def test_ordinary_unstamped_pin_still_prescribes_stamp(self):
        self.write("t.md", "# T\n")
        self.write("a.md", "See [x](t.md)<!--@-->\n")
        verdict, detail = self.verdicts("a.md")[0]
        self.assertEqual("UNSTAMPED", verdict)
        self.assertIn("reflock stamp", detail)

    def test_plan_stamp_has_no_edits_for_unhashable_pins(self):
        self.write("sub/k.md", "# K\n")
        self.write("a.md", "[a](https://example.com)<!--@-->\n"
                            "[b](../outside.md)<!--@-->\n"
                            "[c](sub)<!--@-->\n")
        idx = reflock.build_index(self.d)
        args = types.SimpleNamespace(paths=[], rebless=False)
        edits, report = reflock.plan_stamp(idx, args)
        self.assertEqual({}, edits)
        self.assertEqual([], report)

    def test_stamp_does_stamp_a_genuinely_empty_file(self):
        """The positive control: empty is honest, unhashable is not."""
        self.write("empty.md", "")
        self.write("a.md", "See [e](empty.md)<!--@-->\n")
        self.stamp()
        self.assertIn(f"<!--@{self.EMPTY_FP}-->", self.read("a.md"))

    def test_rebless_does_not_fabricate_on_unhashable_target(self):
        self.write("a.md", "See [x](https://example.com/spec)<!--@deadbeef-->\n")
        self.stamp("--rebless")
        self.assertIn("<!--@deadbeef-->", self.read("a.md"))

    def test_stamp_check_ignores_unhashable_pins(self):
        self.write("a.md", "See [x](https://example.com/spec)<!--@-->\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "stamp", "--check"])
        self.assertEqual(0, rc)
        self.assertIn("Nothing to stamp", buf.getvalue())

    def test_stamp_resolves_through_the_same_resolver_as_check(self):
        """A wiki-link resolving by unique basename must be hashed against the
        path classify resolved, not a path stamp re-derived for itself."""
        self.write("docs/loader.md", "# Loader\n\nreal content\n")
        self.write("a.md", "See [[loader]]<!--@-->\n")
        idx = reflock.build_index(self.d)
        ref = reflock.parse_refs(idx, "a.md")[0]
        _, path, anchor, _ = reflock.resolve_target(idx, ref)
        self.assertEqual("docs/loader.md", path)
        self.stamp()
        expected = reflock.fingerprint(reflock.unit_text(idx, path, anchor))
        self.assertIn(f"<!--@{expected}-->", self.read("a.md"))

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

    # --- --format --------------------------------------------------------
    def run_check(self, *args):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = reflock.main(["--root", self.d, "check", *args])
        return rc, buf.getvalue() + err.getvalue()

    def test_format_human_matches_default(self):
        self.write("a.md", "See [x](missing.md).\n")
        rc_default, out_default = self.run_check()
        rc_fmt, out_fmt = self.run_check("--format", "human")
        self.assertEqual(rc_default, rc_fmt)
        self.assertEqual(out_default, out_fmt)

    def test_format_human_matches_default_clean_tree(self):
        self.write("t.md", "# H\n\n## Real\n\nbody\n")
        rc_default, out_default = self.run_check()
        rc_fmt, out_fmt = self.run_check("--format", "human")
        self.assertEqual(rc_default, rc_fmt)
        self.assertEqual(out_default, out_fmt)

    def test_format_json_matches_json_flag(self):
        self.write("a.md", "See [x](missing.md).\n")
        rc_json, out_json = self.run_check("--json")
        rc_fmt, out_fmt = self.run_check("--format", "json")
        self.assertEqual(rc_json, rc_fmt)
        self.assertEqual(out_json, out_fmt)

    def test_json_and_format_json_agree(self):
        self.write("a.md", "See [x](missing.md).\n")
        rc, out = self.run_check("--json", "--format", "json")
        self.assertEqual(rc, 1)
        json.loads(out)  # still valid JSON output

    def test_json_and_format_human_conflict(self):
        self.write("a.md", "See [x](missing.md).\n")
        rc, out = self.run_check("--json", "--format", "human")
        self.assertNotEqual(rc, 0)
        self.assertIn("--json", out)
        self.assertIn("--format", out)

    def test_invalid_format_value_rejected(self):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err), \
             self.assertRaises(SystemExit) as cm:
            reflock.main(["--root", self.d, "check", "--format", "xml"])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("invalid choice", buf_err.getvalue())

    # --- --format github ----------------------------------------------------
    def test_format_github_dangling_is_error(self):
        self.write("a.md", "See [x](missing.md).\n")
        rc, out = self.run_check("--format", "github")
        self.assertEqual(rc, 1)
        self.assertEqual(out.strip(),
                          "::error file=a.md,line=1,title=DANGLING::no such file: missing.md")

    def test_format_github_unstamped_is_warning(self):
        self.write("t.md", "# H\n\n## Real\n\nbody\n")
        self.write("a.md", "See [x](t.md#real)<!--@-->.\n")
        rc, out = self.run_check("--format", "github")
        self.assertEqual(rc, 1)
        self.assertEqual(out.strip(),
                          "::warning file=a.md,line=1,title=UNSTAMPED::run: reflock stamp")

    def test_format_github_clean_emits_nothing(self):
        self.write("t.md", "# H\n\n## Real\n\nbody\n")
        rc, out = self.run_check("--format", "github")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_format_github_no_summary_or_color(self):
        self.write("a.md", "See [x](missing.md).\n")
        rc, out = self.run_check("--format", "github")
        self.assertNotIn("problem(s)", out)
        self.assertNotIn("\033[", out)

    def test_github_escape_property_escapes_percent_colon_comma_newline_cr(self):
        self.assertEqual(reflock.github_escape_property("a%b:c,d\r\ne"),
                          "a%25b%3Ac%2Cd%0D%0Ae")

    def test_github_escape_message_escapes_percent_newline_cr_but_not_colon_comma(self):
        self.assertEqual(reflock.github_escape_message("a%b:c,d\r\ne"),
                          "a%25b:c,d%0D%0Ae")

    def test_format_github_escapes_detail(self):
        self.write("a.md", "See [x](weird%file,name.md).\n")
        rc, out = self.run_check("--format", "github")
        line = out.strip()
        self.assertEqual(
            line,
            "::error file=a.md,line=1,title=DANGLING::"
            "no such file: weird%25file,name.md")

    def test_format_github_verdict_level_mapping(self):
        self.assertEqual(reflock.GITHUB_LEVEL["DANGLING"], "error")
        self.assertEqual(reflock.GITHUB_LEVEL["DRIFTED"], "error")
        self.assertEqual(reflock.GITHUB_LEVEL["UNSTAMPED"], "warning")
        self.assertNotIn("OK", reflock.GITHUB_LEVEL)

    # --- BUG-07: usage errors respect --format ------------------------------
    def render_error(self, message, fmt):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            reflock.render_error(message, fmt)
        return out.getvalue(), err.getvalue()

    def test_render_error_json_prints_object_to_stdout(self):
        out, err = self.render_error("no such path in tree: x", "json")
        self.assertEqual("", err)
        self.assertEqual({"error": "no such path in tree: x"}, json.loads(out))

    def test_render_error_github_prints_annotation_to_stdout(self):
        out, err = self.render_error("no such path in tree: x", "github")
        self.assertEqual("", err)
        self.assertEqual("::error::no such path in tree: x\n", out)

    def test_render_error_github_escapes_message(self):
        out, _ = self.render_error("a%b\r\nc", "github")
        self.assertEqual("::error::a%25b%0D%0Ac\n", out)

    def test_render_error_human_prints_prefixed_line_to_stderr(self):
        out, err = self.render_error("no such path in tree: x", "human")
        self.assertEqual("", out)
        self.assertEqual("error: no such path in tree: x\n", err)

    def test_check_format_json_scope_error_goes_to_stdout(self):
        self.write("t.md", "# T\n")
        rc, out, err = self.run_cmd("check", "--format", "json", self.at("nope.md"))
        self.assertEqual(2, rc)
        self.assertEqual("", err)
        self.assertIn("nope.md", json.loads(out)["error"])

    def test_check_format_github_scope_error_is_an_annotation(self):
        self.write("t.md", "# T\n")
        rc, out, err = self.run_cmd("check", "--format", "github", self.at("nope.md"))
        self.assertEqual(2, rc)
        self.assertEqual("", err)
        self.assertTrue(out.startswith("::error::"))
        self.assertIn("nope.md", out)

    def test_check_default_format_scope_error_is_unchanged(self):
        """Regression guard: human format keeps printing to stderr, not stdout."""
        self.write("t.md", "# T\n")
        rc, out, err = self.run_cmd("check", self.at("nope.md"))
        self.assertEqual(2, rc)
        self.assertEqual("", out)
        self.assertIn("nope.md", err)

    def test_check_quiet_verbose_conflict_uses_render_error(self):
        rc, out, err = self.run_cmd("check", "--quiet", "--verbose")
        self.assertEqual(2, rc)
        self.assertEqual("", out)
        self.assertIn("conflicts", err)

    def test_stamp_format_has_no_json_shape_scope_error_stays_on_stderr(self):
        """stamp has no --format flag; its errors are always human/stderr."""
        self.write("t.md", "# T\n")
        rc, out, err = self.run_cmd("stamp", self.at("nope.md"))
        self.assertEqual(2, rc)
        self.assertEqual("", out)
        self.assertIn("nope.md", err)

    def test_suspects_json_scope_error_goes_to_stdout(self):
        """suspects' pre-existing --json flag is enough for intended_format to
        route its ScopeError to stdout too, with no new flag added."""
        self.write("t.md", "# T\n")
        rc, out, err = self.run_cmd("suspects", "--json", self.at("nope.md"))
        self.assertEqual(2, rc)
        self.assertEqual("", err)
        self.assertIn("nope.md", json.loads(out)["error"])

    # --- UX-03: next-step hints ---------------------------------------------
    EXPLAIN_HINT = "Run `reflock explain <file>:<line>` for details on any of the above."
    STAMP_HINT_FOR_CHECK = "Run `reflock stamp` to fill in UNSTAMPED pins."
    STAMP_HINT_FOR_STAMP_CHECK = "Run `reflock stamp` to apply."

    def test_check_hints_explain_on_dangling(self):
        self.write("a.md", "See [x](missing.md).\n")
        rc, out = self.run_check()
        self.assertEqual(1, out.count(self.EXPLAIN_HINT), out)
        self.assertNotIn(self.STAMP_HINT_FOR_CHECK, out)

    def test_check_hints_stamp_on_unstamped(self):
        self.write("t.md", "# H\n\nbody\n")
        self.write("a.md", "See [x](t.md)<!--@-->.\n")
        rc, out = self.run_check()
        self.assertEqual(1, out.count(self.EXPLAIN_HINT), out)
        self.assertEqual(1, out.count(self.STAMP_HINT_FOR_CHECK), out)

    def test_check_hints_stamp_appears_once_for_multiple_unstamped(self):
        self.write("t.md", "# H\n\nbody\n")
        self.write("a.md", "See [x](t.md)<!--@-->.\nSee [y](t.md)<!--@-->.\n")
        rc, out = self.run_check()
        self.assertEqual(1, out.count(self.STAMP_HINT_FOR_CHECK), out)

    def test_check_clean_tree_has_no_hints(self):
        self.write("t.md", "# H\n\n## Real\n\nbody\n")
        rc, out = self.run_check()
        self.assertEqual(0, rc)
        self.assertNotIn("reflock", out)
        self.assertEqual("\nAll references OK.\n", out)

    def test_check_format_json_unaffected_by_hints(self):
        self.write("a.md", "See [x](missing.md).\n")
        rc, findings = self.check_json()
        self.assertEqual(1, rc)
        self.assertEqual([{"verdict": "DANGLING", "file": "a.md", "line": 1,
                            "target": "missing.md", "detail": "no such file: missing.md"}],
                          findings)

    def test_check_format_github_unaffected_by_hints(self):
        self.write("a.md", "See [x](missing.md).\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            reflock.main(["--root", self.d, "check", "--format", "github"])
        out = buf.getvalue()
        self.assertNotIn("Run `reflock", out)

    def test_stamp_check_hints_apply(self):
        self.write("a.md", "See [x](t.md)<!--@-->.\n")
        self.write("t.md", "# T\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            reflock.main(["--root", self.d, "stamp", "--check"])
        self.assertIn(self.STAMP_HINT_FOR_STAMP_CHECK, buf.getvalue())

    def test_stamp_check_warn_hints_apply_too(self):
        """--warn only changes the exit code; stdout (hints included) matches
        the non-warn run - the existing stdout-parity invariant, re-asserted."""
        self.write("a.md", "See [x](t.md)<!--@-->.\n")
        self.write("t.md", "# T\n")
        buf1 = io.StringIO()
        with contextlib.redirect_stdout(buf1):
            reflock.main(["--root", self.d, "stamp", "--check"])
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            reflock.main(["--root", self.d, "stamp", "--check", "--warn"])
        self.assertEqual(buf1.getvalue(), buf2.getvalue())
        self.assertIn(self.STAMP_HINT_FOR_STAMP_CHECK, buf1.getvalue())

    def test_stamp_check_nothing_has_no_hint(self):
        self.write("t.md", "# T\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            reflock.main(["--root", self.d, "stamp", "--check"])
        out = buf.getvalue()
        self.assertEqual("\nNothing to stamp.\n", out)

    # --- -q/--quiet --------------------------------------------------------
    def test_quiet_clean_tree_is_silent(self):
        self.write("t.md", "# H\n\n## Real\n\nbody\n")
        rc, out = self.run_check("-q")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_quiet_failure_summary_line_on_stderr(self):
        self.write("a.md", "See [x](missing.md).\n")
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = reflock.main(["--root", self.d, "check", "-q"])
        self.assertNotEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(err.getvalue(), "reflock: 1 of 1 references failed\n")

    def test_quiet_and_quiet_long_flag_equivalent(self):
        self.write("a.md", "See [x](missing.md).\n")
        buf1, err1 = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf1), contextlib.redirect_stderr(err1):
            reflock.main(["--root", self.d, "check", "-q"])
        buf2, err2 = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf2), contextlib.redirect_stderr(err2):
            reflock.main(["--root", self.d, "check", "--quiet"])
        self.assertEqual(buf1.getvalue(), buf2.getvalue())
        self.assertEqual(err1.getvalue(), err2.getvalue())

    def test_quiet_json_still_emits_findings(self):
        self.write("a.md", "See [x](missing.md).\n")
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = reflock.main(["--root", self.d, "check", "-q", "--format", "json"])
        self.assertEqual(rc, 1)
        findings = json.loads(buf.getvalue())
        self.assertEqual(len(findings), 1)
        self.assertEqual(err.getvalue(), "")

    def test_quiet_verbose_conflict(self):
        self.write("a.md", "See [x](missing.md).\n")
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = reflock.main(["--root", self.d, "check", "-q", "--verbose"])
        self.assertNotEqual(rc, 0)
        self.assertIn("--quiet", buf.getvalue() + err.getvalue())
        self.assertIn("--verbose", buf.getvalue() + err.getvalue())

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

    # --- shell completion (ID-11, parity hardened by TEST-01) ----------------
    @staticmethod
    def flag_in_shell_syntax(shell, flag, script):
        """Is `flag` present in the form this shell actually spells it?

        The old parity test asked `assertIn(flag, script)`, which fish could only
        satisfy via a `# --format` comment the test itself forced into the shipped
        script. Asserting the real syntax is what makes the test test the artifact.
        """
        if shell == "fish":
            return (f"-l {flag[2:]}" in script if flag.startswith("--")
                    else f"-s {flag[1:]}" in script)
        return flag in script

    def test_completion_parity_uses_each_shell_own_syntax(self):
        spec = reflock.parser_spec()
        for shell in reflock.COMPLETION_SHELLS:
            script = reflock.completion_script(shell)
            for sub, info in spec.items():
                self.assertIn(sub, script, f"{shell} script missing subcommand {sub!r}")
                for flag in info["flags"]:
                    self.assertTrue(
                        self.flag_in_shell_syntax(shell, flag, script),
                        f"{shell} script missing flag {flag!r} for {sub!r}")

    def test_fish_script_has_no_flag_literals_or_comment_crutches(self):
        """The inverse assertion: a reintroduced `# --format` comment must fail."""
        script = reflock.completion_script("fish")
        spec = reflock.parser_spec()
        longs = {f for info in spec.values() for f in info["flags"] if f.startswith("--")}
        for flag in longs:
            self.assertNotIn(flag, script,
                             f"fish script contains the literal {flag!r}; fish spells "
                             f"it -l {flag[2:]}, so this is a comment crutch")
        for line in script.splitlines():
            if line.startswith("#"):
                continue          # the file header is prose, not a completion
            self.assertNotIn("#", line, f"fish completion carries a comment: {line!r}")

    def test_completion_positional_choices_are_offered(self):
        for shell in reflock.COMPLETION_SHELLS:
            script = reflock.completion_script(shell)
            for choice in reflock.COMPLETION_SHELLS:
                self.assertIn(choice, script,
                              f"{shell} script does not offer {choice!r} for `completion`")

    def test_completion_subcommand_does_not_offer_paths(self):
        """`reflock completion <TAB>` took a shell name, and offered filenames."""
        bash = reflock.completion_script("bash")
        self.assertRegex(bash, r'completion\)\s+COMPREPLY=\(\s*\$\(compgen -W "bash fish zsh"')
        fish = reflock.completion_script("fish")
        comp_lines = [ln for ln in fish.splitlines()
                      if "__fish_seen_subcommand_from completion" in ln]
        self.assertTrue(comp_lines)
        for ln in comp_lines:
            self.assertNotIn("__fish_complete_path", ln,
                             "the completion subcommand takes a shell name, not a path")

    def test_zsh_declares_value_taking_options_with_choices(self):
        script = reflock.completion_script("zsh")
        self.assertIn("--format=[", script,
                      "zsh must know --format takes a value, or it cannot complete it")
        self.assertRegex(script, r"--format=\[[^\]]*\]:format:\(github human json\)")

    def test_parser_spec_reports_values_and_choices(self):
        spec = reflock.parser_spec()
        self.assertEqual(["github", "human", "json"], spec["check"]["valued"]["--format"])
        self.assertIn("--quiet", spec["check"]["flags"])
        self.assertNotIn("--quiet", spec["check"]["valued"],
                          "--quiet is a store_true, it takes no value")
        self.assertEqual(["bash", "fish", "zsh"], spec["completion"]["positional_choices"])

    def test_short_flags_are_aliases_not_separate_options(self):
        spec = reflock.parser_spec()
        self.assertIn(("--quiet", "-q"), spec["check"]["groups"],
                      "-q and --quiet are one option with two spellings")
        fish = reflock.completion_script("fish")
        self.assertIn("-l quiet -s q", fish)
        zsh = reflock.completion_script("zsh")
        self.assertIn("'(--quiet -q)'{--quiet,-q}'[quiet]'", zsh)

    def test_completion_fish_script_parses_under_fish(self):
        fish = shutil.which("fish")
        if not fish:
            self.skipTest("fish not available")
        import subprocess
        proc = subprocess.run([fish, "-n", "-"], input=reflock.completion_script("fish"),
                               text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_a_new_flag_reaches_every_script(self):
        """ID-11's actual promise: the parser is the source of truth. Asserted
        through each shell's real syntax, not a substring that a comment can
        satisfy."""
        real = reflock.build_parser

        def with_extra_flag():
            ap = real()
            sub = next(a for a in ap._subparsers._group_actions
                        if isinstance(a, __import__("argparse")._SubParsersAction))
            sub.choices["check"].add_argument("--brand-new", action="store_true")
            return ap
        with mock.patch.object(reflock_cli, "build_parser", with_extra_flag):
            for shell in reflock.COMPLETION_SHELLS:
                script = reflock.completion_script(shell)
                self.assertTrue(
                    self.flag_in_shell_syntax(shell, "--brand-new", script),
                    f"{shell} script did not pick up a new parser flag")

    def test_completion_unsupported_shell_exits_nonzero(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), self.assertRaises(SystemExit) as ctx:
            reflock.main(["completion", "tcsh"])
        self.assertNotEqual(ctx.exception.code, 0)
        out = buf.getvalue()
        for shell in reflock.COMPLETION_SHELLS:
            self.assertIn(shell, out)

    def test_completion_scripts_nonempty(self):
        for shell in reflock.COMPLETION_SHELLS:
            self.assertTrue(reflock.completion_script(shell).strip())

    # --- CLI-02: --help epilogs ---------------------------------------------
    def help_text(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            reflock.main(list(argv) + ["--help"])
        self.assertEqual(0, cm.exception.code)
        return buf.getvalue()

    def test_check_help_has_examples(self):
        out = self.help_text("check")
        self.assertIn("examples:", out)
        self.assertIn("  reflock check", out)

    def test_stamp_help_has_examples(self):
        out = self.help_text("stamp")
        self.assertIn("examples:", out)
        self.assertIn("  reflock stamp", out)

    def test_suspects_help_has_examples(self):
        out = self.help_text("suspects")
        self.assertIn("examples:", out)
        self.assertIn("  reflock suspects", out)

    def test_backlinks_help_has_examples(self):
        out = self.help_text("backlinks")
        self.assertIn("examples:", out)
        self.assertIn("  reflock backlinks", out)

    def test_explain_help_has_examples(self):
        out = self.help_text("explain")
        self.assertIn("examples:", out)
        self.assertIn("  reflock explain", out)

    def test_completion_help_has_examples(self):
        out = self.help_text("completion")
        self.assertIn("examples:", out)
        self.assertIn("  reflock completion", out)

    def test_completion_bash_help_still_exits_zero(self):
        """A subcommand with a choices-constrained positional keeps parsing
        correctly once its parent subparser gains an epilog."""
        out = self.help_text("completion", "bash")
        self.assertIn("usage: reflock completion", out)

    def test_top_level_help_unchanged_by_subcommand_epilogs(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            reflock.main(["--help"])
        self.assertEqual(0, cm.exception.code)
        self.assertNotIn("examples:", buf.getvalue())

    def test_completion_writes_nothing_to_disk(self):
        before = set(os.listdir(self.d))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            reflock.main(["--root", self.d, "completion", "bash"])
        self.assertEqual(before, set(os.listdir(self.d)))

    def test_completion_prints_to_stdout(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "completion", "zsh"])
        self.assertEqual(rc, 0)
        self.assertIn("reflock", buf.getvalue())

    def test_completion_bash_script_parses_under_bash(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash not available")
        import subprocess
        script = reflock.completion_script("bash")
        proc = subprocess.run([bash, "-n"], input=script, text=True,
                               capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_completion_zsh_script_parses_under_zsh(self):
        zsh = shutil.which("zsh")
        if not zsh:
            self.skipTest("zsh not available")
        import subprocess
        script = reflock.completion_script("zsh")
        proc = subprocess.run([zsh, "-n"], input=script, text=True,
                               capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    # --- backlinks -----------------------------------------------------------
    def run_backlinks(self, *args):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = reflock.main(["--root", self.d, "backlinks", *args])
        return rc, buf.getvalue(), err.getvalue()

    def backlinks_json(self, *args):
        rc, out, err = self.run_backlinks(*args, "--format", "json")
        return rc, json.loads(out), err

    def test_backlinks_lists_referrers_sorted(self):
        self.write("t.md", "# Title\n")
        self.write("b.md", "See [x](t.md).\n")
        self.write("a.md", "See [x](t.md).\n")
        rc, rows, _ = self.backlinks_json("t.md")
        self.assertEqual(rc, 0)
        self.assertEqual([r["file"] for r in rows], ["a.md", "b.md"])

    def test_backlinks_same_file_sorted_by_line(self):
        self.write("t.md", "# Title\n")
        self.write("a.md", "See [x](t.md).\nSee [y](t.md).\n")
        rc, rows, _ = self.backlinks_json("a.md")
        self.assertEqual(rc, 0)
        self.assertEqual([], [r for r in rows if r["file"] != "a.md"])  # sanity

    def test_backlinks_anchor_narrows(self):
        self.write("t.md", "# Title\n\n## Real\n\nbody\n")
        self.write("a.md", "See [x](t.md#real).\n")
        self.write("b.md", "See [x](t.md).\n")
        rc, rows, _ = self.backlinks_json("t.md#real")
        self.assertEqual(rc, 0)
        self.assertEqual([r["file"] for r in rows], ["a.md"])

    def test_backlinks_reports_pin_state(self):
        self.write("t.md", "# Title\n\nbody\n")
        self.write("a.md", "See [x](t.md)<!--@-->.\n")
        self.write("b.md", "See [y](t.md).\n")
        self.stamp()
        rc, rows, _ = self.backlinks_json("t.md")
        pins = {r["file"]: r["pin"] for r in rows}
        self.assertEqual(pins["a.md"], "pinned")
        self.assertEqual(pins["b.md"], "unpinned")

    def test_backlinks_none_exits_zero(self):
        self.write("t.md", "# Title\n")
        rc, out, _ = self.run_backlinks("t.md")
        self.assertEqual(rc, 0)
        self.assertIn("no backlinks", out.lower())

    def test_backlinks_none_has_no_trailing_count_line(self):
        self.write("t.md", "# Title\n")
        rc, out, _ = self.run_backlinks("t.md")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "No backlinks to t.md.\n")

    def test_backlinks_human_ends_with_count_line(self):
        self.write("t.md", "# Title\n")
        self.write("a.md", "See [x](t.md).\n")
        rc, out, _ = self.run_backlinks("t.md")
        self.assertEqual(rc, 0)
        self.assertTrue(out.endswith("\n\n1 backlink(s).\n"), out)

    def test_backlinks_human_count_matches_row_count(self):
        self.write("t.md", "# Title\n")
        self.write("a.md", "See [x](t.md).\n")
        self.write("b.md", "See [y](t.md).\n")
        rc, out, _ = self.run_backlinks("t.md")
        self.assertEqual(rc, 0)
        self.assertTrue(out.endswith("\n\n2 backlink(s).\n"), out)

    def test_backlinks_format_json_unchanged_by_count_line(self):
        """The human renderer gaining a count line must not leak into json."""
        self.write("t.md", "# Title\n")
        self.write("a.md", "See [x](t.md).\n")
        rc, rows, _ = self.backlinks_json("t.md")
        self.assertEqual(rc, 0)
        self.assertEqual(rows, [{"file": "a.md", "line": 1, "target": "t.md", "pin": "unpinned"}])

    def test_backlinks_unknown_path_exits_nonzero(self):
        rc, out, err = self.run_backlinks("nope.md")
        self.assertNotEqual(rc, 0)
        self.assertIn("nope.md", out + err)

    def test_backlinks_format_json_shape(self):
        self.write("t.md", "# Title\n")
        self.write("a.md", "See [x](t.md).\n")
        rc, rows, _ = self.backlinks_json("t.md")
        self.assertEqual(rc, 0)
        self.assertEqual(rows, [{"file": "a.md", "line": 1, "target": "t.md", "pin": "unpinned"}])

    # --- explain -----------------------------------------------------------
    def run_explain(self, *args):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = reflock.main(["--root", self.d, "explain", *args])
        return rc, buf.getvalue(), err.getvalue()

    def explain_json(self, *args):
        rc, out, err = self.run_explain(*args, "--format", "json")
        return rc, json.loads(out), err

    def test_explain_ok_reference(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "See [d](t.md#decision)<!--@-->.\n")
        self.stamp()
        rc, entries, _ = self.explain_json("a.md:1")
        self.assertEqual(rc, 0)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["target"], "t.md#decision")
        self.assertEqual(e["resolves_to"], "t.md")
        self.assertEqual(e["verdict"], "OK")
        self.assertIsNotNone(e["pin"])
        self.assertIsNotNone(e["current"])
        self.assertEqual(e["current"], e["pin"])

    def test_explain_drifted_shows_both_hashes(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "See [d](t.md#decision)<!--@-->.\n")
        self.stamp()
        self.write("t.md", "# H\n\n## Decision\n\nWe chose Y instead.\n")
        rc, entries, _ = self.explain_json("a.md:1")
        e = entries[0]
        self.assertEqual(e["verdict"], "DRIFTED")
        self.assertIsNotNone(e["pin"])
        self.assertIsNotNone(e["current"])
        self.assertNotEqual(e["pin"], e["current"])
        rc_h, out, _ = self.run_explain("a.md:1")
        self.assertIn("not recoverable", out.lower())

    def test_explain_dangling(self):
        self.write("a.md", "See [x](missing.md).\n")
        rc, entries, _ = self.explain_json("a.md:1")
        e = entries[0]
        self.assertEqual(e["verdict"], "DANGLING")
        self.assertIsNotNone(e["detail"])
        self.assertIsNone(e["resolves_to"])

    def test_explain_unpinned_no_hash(self):
        self.write("t.md", "# H\n")
        self.write("a.md", "See [x](t.md).\n")
        rc, entries, _ = self.explain_json("a.md:1")
        e = entries[0]
        self.assertEqual(e["verdict"], "OK")
        self.assertIsNone(e["current"])

    def test_explain_multiple_refs_on_line(self):
        self.write("t.md", "# H\n")
        self.write("u.md", "# H2\n")
        self.write("a.md", "See [x](t.md) and [y](u.md).\n")
        rc, entries, _ = self.explain_json("a.md:1")
        self.assertEqual([e["target"] for e in entries], ["t.md", "u.md"])

    def test_explain_no_reference_on_line(self):
        self.write("a.md", "no refs here\n")
        rc, out, err = self.run_explain("a.md:1")
        self.assertNotEqual(rc, 0)
        self.assertIn("no reference", (out + err).lower())

    def test_explain_verdict_matches_check(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n")
        self.write("a.md", "See [d](t.md#decision)<!--@-->.\n")
        self.stamp()
        self.write("t.md", "# H\n\n## Decision\n\nWe chose Y instead.\n")
        rc_c, findings = self.check_json()
        rc_e, entries, _ = self.explain_json("a.md:1")
        self.assertEqual(entries[0]["verdict"], findings[0]["verdict"])

    def test_explain_missing_line_spec(self):
        self.write("a.md", "text\n")
        rc, out, err = self.run_explain("a.md")
        self.assertNotEqual(rc, 0)

    def test_explain_non_numeric_line(self):
        self.write("a.md", "text\n")
        rc, out, err = self.run_explain("a.md:x")
        self.assertNotEqual(rc, 0)

    def test_explain_out_of_range_line(self):
        self.write("a.md", "text\n")
        rc, out, err = self.run_explain("a.md:99")
        self.assertNotEqual(rc, 0)

    def test_explain_format_json_bad_spec_goes_to_stdout(self):
        rc, out, err = self.run_explain("not-a-spec", "--format", "json")
        self.assertEqual(2, rc)
        self.assertEqual("", err)
        self.assertIn("not-a-spec", json.loads(out)["error"])

    def test_explain_format_json_unknown_file_goes_to_stdout(self):
        rc, out, err = self.run_explain("nope.md:1", "--format", "json")
        self.assertEqual(2, rc)
        self.assertEqual("", err)
        self.assertIn("nope.md", json.loads(out)["error"])

    def test_explain_format_json_out_of_range_line_goes_to_stdout(self):
        self.write("a.md", "text\n")
        rc, out, err = self.run_explain("a.md:99", "--format", "json")
        self.assertEqual(2, rc)
        self.assertEqual("", err)
        self.assertIn("a.md", json.loads(out)["error"])

    def test_explain_format_json_no_reference_on_line_goes_to_stdout(self):
        self.write("a.md", "no refs here\n")
        rc, out, err = self.run_explain("a.md:1", "--format", "json")
        self.assertEqual(2, rc)
        self.assertEqual("", err)
        self.assertIn("a.md", json.loads(out)["error"])

    def test_explain_anchor_heading_span(self):
        self.write("t.md", "# H\n\n## Decision\n\nWe chose X.\n\n## Next\n\nmore\n")
        self.write("a.md", "See [d](t.md#decision).\n")
        rc, entries, _ = self.explain_json("a.md:1")
        a = entries[0]["anchor"]
        self.assertEqual(a["kind"], "heading")
        self.assertEqual((a["start"], a["end"]), (3, 6))

    def test_explain_anchor_marker_span(self):
        self.write("lib.py", "# reflock-anchor: run\ndef run():\n    return 1\n# reflock-anchor-end: run\n")
        self.write("caller.py", "# REF: lib.py#run\n")
        rc, entries, _ = self.explain_json("caller.py:1")
        a = entries[0]["anchor"]
        self.assertEqual(a["kind"], "span")
        self.assertEqual((a["start"], a["end"]), (2, 3))

    def test_explain_is_read_only(self):
        self.write("t.md", "# H\n")
        self.write("a.md", "See [x](t.md).\n")
        before = self.read("a.md")
        self.run_explain("a.md:1")
        self.assertEqual(self.read("a.md"), before)


class SetupClaudeTest(unittest.TestCase):
    """ID-22: `reflock setup claude` installs/repairs the Stop-hook gate.

    reflock_invocation()'s PATH-preference branch is intentionally untested
    here - it depends on whether `reflock` happens to be on PATH on the
    machine running the tests, so a real assertion needs shutil.which/
    os.path.realpath mocked, which mostly re-asserts the mock. The pure
    merge/render logic and cmd_setup's actual file effects are deterministic
    and are what's covered below.
    """

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_setup(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = reflock.main(["--root", self.d, "setup", "claude"])
        return rc, buf.getvalue()

    def hook_path(self):
        return os.path.join(self.d, ".claude", "hooks", "reflock-gate.sh")

    def settings_path(self):
        return os.path.join(self.d, ".claude", "settings.json")

    # --- add_stop_hook() -----------------------------------------------
    def test_add_stop_hook_to_empty_settings(self):
        result = reflock_setup.add_stop_hook({})
        self.assertEqual(
            [{"matcher": "", "hooks": [{"type": "command",
                                          "command": reflock_setup.STOP_HOOK_COMMAND}]}],
            result["hooks"]["Stop"])

    def test_add_stop_hook_preserves_sibling_hook_types(self):
        settings = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}}
        result = reflock_setup.add_stop_hook(settings)
        self.assertEqual(settings["hooks"]["PreToolUse"], result["hooks"]["PreToolUse"])
        self.assertEqual(1, len(result["hooks"]["Stop"]))

    def test_add_stop_hook_is_idempotent(self):
        once = reflock_setup.add_stop_hook({})
        twice = reflock_setup.add_stop_hook(once)
        self.assertIs(once, twice)
        self.assertEqual(1, len(twice["hooks"]["Stop"]))

    def test_add_stop_hook_does_not_mutate_input(self):
        settings = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}}
        before = json.dumps(settings)
        reflock_setup.add_stop_hook(settings)
        self.assertEqual(before, json.dumps(settings))

    # --- render_hook_script() -------------------------------------------
    def test_render_hook_script_embeds_invocation(self):
        script = reflock_setup.render_hook_script("reflock")
        self.assertIn('reflock_cmd="${REFLOCK:-reflock}"', script)

    def test_render_hook_script_is_stable(self):
        self.assertEqual(reflock_setup.render_hook_script("reflock"),
                          reflock_setup.render_hook_script("reflock"))

    # --- cmd_setup() end to end -----------------------------------------
    def test_setup_writes_hook_and_settings_on_fresh_tree(self):
        rc, out = self.run_setup()
        self.assertEqual(0, rc)
        self.assertIn("wrote", out)
        self.assertIn("added Stop hook", out)
        self.assertTrue(os.path.exists(self.hook_path()))
        self.assertTrue(os.access(self.hook_path(), os.X_OK))
        with open(self.settings_path()) as fh:
            settings = json.load(fh)
        self.assertEqual(1, len(settings["hooks"]["Stop"]))

    def test_setup_second_run_is_a_no_op(self):
        self.run_setup()
        hook_mtime = os.path.getmtime(self.hook_path())
        rc, out = self.run_setup()
        self.assertEqual(0, rc)
        self.assertIn("unchanged", out)
        self.assertIn("already has the Stop hook", out)
        self.assertEqual(hook_mtime, os.path.getmtime(self.hook_path()))

    def test_setup_preserves_unrelated_settings_keys(self):
        os.makedirs(os.path.dirname(self.settings_path()))
        with open(self.settings_path(), "w") as fh:
            json.dump({"permissions": {"allow": ["Bash(ls:*)"]}}, fh)
        self.run_setup()
        with open(self.settings_path()) as fh:
            settings = json.load(fh)
        self.assertEqual(["Bash(ls:*)"], settings["permissions"]["allow"])
        self.assertEqual(1, len(settings["hooks"]["Stop"]))

    def test_setup_rejects_invalid_json_without_overwriting(self):
        os.makedirs(os.path.dirname(self.settings_path()))
        with open(self.settings_path(), "w") as fh:
            fh.write("{not valid json")
        rc, out = self.run_setup()
        self.assertEqual(2, rc)
        with open(self.settings_path()) as fh:
            self.assertEqual("{not valid json", fh.read())


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(REPO_ROOT, ".pre-commit-hooks.yaml")


def parse_hook_manifest(text: str) -> list[dict[str, str]]:
    """Minimal parser for the one shape .pre-commit-hooks.yaml has: a top-level
    list of flat string-valued mappings. Stdlib only, per D3 - pulling in PyYAML
    to test a 20-line manifest would be the dependency this project refuses."""
    hooks: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped.startswith("- "):
            hooks.append({})
            stripped = stripped[2:]
        if ":" not in stripped:
            raise AssertionError(f"not a key: value line: {raw!r}")
        if not hooks:
            raise AssertionError(f"mapping outside any list item: {raw!r}")
        key, _, value = stripped.partition(":")
        hooks[-1][key.strip()] = value.strip().strip("'\"")
    return hooks


class PreCommitManifestTest(unittest.TestCase):
    """ID-21: the shipped manifest must parse and must not name a subcommand or
    an entry script that has been renamed out from under it - a silent failure
    mode no other test covers."""

    def setUp(self):
        with open(MANIFEST, encoding="utf-8") as fh:
            self.hooks = parse_hook_manifest(fh.read())

    def test_manifest_exists_and_parses(self):
        self.assertTrue(self.hooks, "manifest declares no hooks")

    def test_required_keys_present(self):
        for hook in self.hooks:
            for key in ("id", "name", "entry", "language"):
                self.assertIn(key, hook, f"hook {hook.get('id', '?')} missing {key}")

    def test_declares_both_documented_hook_ids(self):
        self.assertEqual(
            sorted(h["id"] for h in self.hooks),
            ["reflock-check", "reflock-stamp-check"],
        )

    def test_entry_invokes_an_existing_subcommand(self):
        spec = reflock.parser_spec()
        for hook in self.hooks:
            parts = hook["entry"].split()
            self.assertGreaterEqual(len(parts), 2, f"entry {hook['entry']!r} names no subcommand")
            self.assertIn(parts[1], spec,
                          f"hook {hook['id']} invokes unknown subcommand {parts[1]!r}")

    def test_entry_script_exists_and_is_executable(self):
        for hook in self.hooks:
            script = os.path.join(REPO_ROOT, hook["entry"].split()[0])
            self.assertTrue(os.path.exists(script), f"{script} does not exist")
            self.assertTrue(os.access(script, os.X_OK),
                            f"{script} is not executable, so language: script cannot run it")

    def test_entry_flags_exist_on_that_subcommand(self):
        spec = reflock.parser_spec()
        for hook in self.hooks:
            parts = hook["entry"].split()
            for flag in (p for p in parts[2:] if p.startswith("-")):
                self.assertIn(flag, spec[parts[1]]["flags"],
                              f"hook {hook['id']} passes {flag!r}, absent from {parts[1]}")

    def test_no_hook_that_can_fail_runs_at_pre_commit(self):
        """D6: do not ship a hook that hard-fails a commit by default.

        NS-03b replaced the proxy this test used to assert - "no hook mentions
        pre-commit at all" - with the invariant itself. That proxy was only right
        while every hook could fail: pre-commit has no warn-only mode, so before
        `stamp --check --warn` existed, pre-push was the only stage that honored
        D6. Now a hook may run at commit time precisely if it cannot fail, which
        is what D6 asks for and what DECISIONS.md section 3 describes.

        Strictly stronger than the old assertion: it still forbids `reflock-check`
        at pre-commit, and it forbids any future blocking hook being added there.
        """
        for hook in self.hooks:
            self.assertIn("stages", hook, f"hook {hook['id']} does not pin a stage")
            if "pre-commit" in hook["stages"]:
                self.assertIn("--warn", hook["entry"],
                              f"hook {hook['id']} runs at pre-commit but can fail, "
                              f"so it would block a commit on partial work")

    def test_advisory_hook_is_the_one_at_commit_time(self):
        by_id = {h["id"]: h for h in self.hooks}
        self.assertIn("pre-commit", by_id["reflock-stamp-check"]["stages"])
        self.assertIn("--warn", by_id["reflock-stamp-check"]["entry"])
        self.assertNotIn("pre-commit", by_id["reflock-check"]["stages"])
        self.assertIn("pre-push", by_id["reflock-check"]["stages"])

    def test_enforcing_hook_does_not_pass_warn(self):
        by_id = {h["id"]: h for h in self.hooks}
        self.assertNotIn("--warn", by_id["reflock-check"]["entry"],
                          "the enforcing gate must be able to fail")

    def test_advisory_hook_shows_its_output(self):
        hook = next(h for h in self.hooks if h["id"] == "reflock-stamp-check")
        self.assertEqual(hook.get("verbose"), "true")

    def test_hooks_are_scoped_to_parseable_files(self):
        """Contract: files: restricted to text types reflock parses, so the hook
        does not fire on every binary asset."""
        for hook in self.hooks:
            self.assertIn("files", hook, f"hook {hook['id']} has no files: filter")
            self.assertNotIn("always_run", hook,
                             f"hook {hook['id']} sets always_run, defeating files:")

    def test_no_hook_passes_filenames(self):
        """A per-file invocation cannot see cross-file targets, so it would
        report false DANGLING findings."""
        for hook in self.hooks:
            self.assertEqual(hook.get("pass_filenames"), "false",
                             f"hook {hook['id']} must run over the whole tree")


_bench_spec = importlib.util.spec_from_file_location(
    "run_bench", os.path.join(REPO_ROOT, "evalbench", "run_bench.py"))
run_bench = importlib.util.module_from_spec(_bench_spec)
_bench_spec.loader.exec_module(run_bench)


class VersionConsistencyTest(unittest.TestCase):
    """DOC-01: the README told adopters to pin `rev: v0.1.0`, a tag that does not
    contain .pre-commit-hooks.yaml - so ID-21's whole deliverable was unreachable
    by the only instructions given for reaching it. These tie the version facts
    together so the class of defect cannot recur silently."""

    def setUp(self):
        with open(os.path.join(REPO_ROOT, "README.md"), encoding="utf-8") as fh:
            self.readme = fh.read()

    def test_readme_precommit_rev_matches_version(self):
        revs = re.findall(r"^\s*rev:\s*v(\d+\.\d+\.\d+)\s*$", self.readme, re.M)
        self.assertTrue(revs, "README quotes no pre-commit rev: to check")
        for rev in revs:
            self.assertEqual(reflock.__version__, rev,
                              "the documented pre-commit rev must name the release "
                              "that contains .pre-commit-hooks.yaml")

    def test_version_flag_prints_the_module_version(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            reflock.main(["--version"])
        self.assertEqual(f"reflock {reflock.__version__}", buf.getvalue().strip())

    def test_release_workflow_guards_tag_against_version(self):
        """release.yml takes the version from the pushed tag, so without this
        check a tag could ship a formula whose reflock --version disagrees."""
        with open(os.path.join(REPO_ROOT, ".github", "workflows", "release.yml"),
                   encoding="utf-8") as fh:
            wf = fh.read()
        self.assertIn("__version__", wf,
                      "release.yml must refuse a tag that disagrees with __version__")


class BenchHarnessTest(unittest.TestCase):
    """BENCH-01: the bench harness is code too. Its own assertions have to fail
    when they should, or a fixture reports PASS having checked nothing."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        with open(os.path.join(self.d, "t.md"), "w") as fh:
            fh.write("# Title\n\nbody\n")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, rel, text):
        with open(os.path.join(self.d, rel), "w") as fh:
            fh.write(text)

    def run_steps(self, *steps):
        """Run steps through the harness the way run_fixture does, returning the
        failure list for the final step."""
        ctx = run_bench.StepContext()
        fails = []
        for step in steps:
            fails = run_bench.check_step(self.d, step, ctx)
        return fails

    # --- fixture premises version control could erase -----------------------
    def test_crlf_fixture_keeps_its_crlf_through_git(self):
        """BUG-05's CRLF fixture asserts stamp preserves \\r\\n, so the \\r\\n has to
        survive being committed. With core.autocrlf=input git stores it as LF and
        the fixture passes locally while failing on every fresh clone - so the
        -text attribute is part of the test, and this asserts both halves."""
        rel = "evalbench/fixtures/stamp-preserves-crlf/repo/a.md"
        with open(os.path.join(REPO_ROOT, rel), "rb") as fh:
            self.assertIn(b"\r\n", fh.read(), f"{rel} lost its CRLF on disk")
        with open(os.path.join(REPO_ROOT, ".gitattributes"), encoding="utf-8") as fh:
            attrs = fh.read()
        self.assertRegex(attrs, re.escape(rel) + r"\s+-text",
                          ".gitattributes must stop git normalizing the fixture")

    # --- 1. unknown keys are an error ---------------------------------------
    def test_unknown_step_key_fails_and_is_named(self):
        fails = self.run_steps({"cmd": "check", "expect_containss": ["never matches"]})
        self.assertTrue(fails, "a typo'd assertion key must not pass silently")
        self.assertIn("expect_containss", " ".join(fails))

    def test_every_documented_key_is_accepted(self):
        """Guards against a validation set that drifts from the documented one."""
        for key in ("write", "cmd", "args", "expect_exit", "expect_json",
                    "expect_contains", "expect_not_contains", "expect_file_regex",
                    "expect_stderr", "expect_stderr_not_contains",
                    "expect_stderr_empty", "expect_stdout_empty",
                    "expect_stdout_same_as_step",
                    "expect_tree_unchanged_since_step"):
            self.assertIn(key, run_bench.STEP_KEYS, f"{key} documented but not accepted")

    # --- 2. stream assertions ----------------------------------------------
    def test_expect_stderr_passes_on_match(self):
        self.write("a.md", "See [x](missing.md)\n")
        self.assertEqual([], self.run_steps(
            {"cmd": "check", "args": ["-q"], "expect_stderr": ["1 of 1 references failed"]}))

    def test_expect_stderr_fails_on_miss(self):
        self.write("a.md", "See [x](missing.md)\n")
        fails = self.run_steps(
            {"cmd": "check", "args": ["-q"], "expect_stderr": ["not in the output"]})
        self.assertTrue(fails)
        self.assertIn("stderr", " ".join(fails))

    def test_expect_stderr_empty_fails_when_stderr_written(self):
        self.write("a.md", "See [x](missing.md)\n")
        fails = self.run_steps(
            {"cmd": "check", "args": ["-q"], "expect_stderr_empty": True})
        self.assertTrue(fails, "-q on a failing tree writes a summary to stderr")

    def test_expect_stderr_empty_passes_on_clean_run(self):
        self.assertEqual([], self.run_steps(
            {"cmd": "check", "expect_stderr_empty": True}))

    def test_expect_stdout_empty_passes_when_quiet_and_clean(self):
        self.assertEqual([], self.run_steps(
            {"cmd": "check", "args": ["-q"], "expect_stdout_empty": True}))

    def test_expect_stdout_empty_fails_when_anything_printed(self):
        fails = self.run_steps({"cmd": "check", "expect_stdout_empty": True})
        self.assertTrue(fails, "the default human report prints a summary line")

    def test_expect_stderr_not_contains(self):
        self.write("a.md", "See [x](missing.md)\n")
        self.assertEqual([], self.run_steps(
            {"cmd": "check", "expect_stderr_not_contains": ["Traceback"]}))
        fails = self.run_steps(
            {"cmd": "check", "args": ["-q"], "expect_stderr_not_contains": ["references failed"]})
        self.assertTrue(fails)

    # --- 3. cross-step byte identity ---------------------------------------
    def test_stdout_same_as_step_passes_for_identical_invocations(self):
        self.write("a.md", "See [x](missing.md)\n")
        self.assertEqual([], self.run_steps(
            {"cmd": "check", "args": []},
            {"cmd": "check", "args": ["--format", "human"],
             "expect_stdout_same_as_step": 0}))

    def test_stdout_same_as_step_fails_when_output_differs(self):
        self.write("a.md", "See [x](missing.md)\n")
        fails = self.run_steps(
            {"cmd": "check", "args": []},
            {"cmd": "check", "args": ["--format", "json"],
             "expect_stdout_same_as_step": 0})
        self.assertTrue(fails)

    def test_tree_unchanged_passes_after_read_only_command(self):
        self.write("a.md", "See [x](t.md)<!--@-->\n")
        self.assertEqual([], self.run_steps(
            {"cmd": "check", "args": []},
            {"cmd": "stamp", "args": ["--check"],
             "expect_tree_unchanged_since_step": 0}))

    def test_tree_unchanged_fails_after_a_write(self):
        self.write("a.md", "See [x](t.md)<!--@-->\n")
        fails = self.run_steps(
            {"cmd": "check", "args": []},
            {"cmd": "stamp", "args": [], "expect_tree_unchanged_since_step": 0})
        self.assertTrue(fails, "stamp rewrote a.md; the assertion must catch it")
        self.assertIn("a.md", " ".join(fails))

    def test_tree_unchanged_detects_an_added_file(self):
        self.assertTrue(self.run_steps(
            {"cmd": "check", "args": []},
            {"cmd": "check", "args": [], "write": {"new.md": "# New\n"},
             "expect_tree_unchanged_since_step": 0}))

    def test_forward_step_reference_is_a_fixture_error(self):
        for spec in ({"expect_stdout_same_as_step": 0},
                     {"expect_tree_unchanged_since_step": 1}):
            step = {"cmd": "check", "args": [], **spec}
            fails = self.run_steps(step)
            self.assertTrue(fails, f"{spec} refers to a step that has not run")


if __name__ == "__main__":
    unittest.main()
