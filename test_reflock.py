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

    # --- shell completion (ID-11) --------------------------------------------
    def test_completion_parity_subcommands_and_flags(self):
        spec = reflock.parser_spec()
        for shell in reflock.COMPLETION_SHELLS:
            script = reflock.completion_script(shell)
            for sub, flags in spec.items():
                self.assertIn(sub, script, f"{shell} script missing subcommand {sub!r}")
                for flag in flags:
                    if flag.startswith("--"):
                        self.assertIn(flag, script,
                                      f"{shell} script missing flag {flag!r} for {sub!r}")

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
                self.assertIn(flag, spec[parts[1]],
                              f"hook {hook['id']} passes {flag!r}, absent from {parts[1]}")

    def test_no_hook_blocks_a_commit_by_default(self):
        """D6: do not ship a hook that hard-fails a commit by default. pre-commit
        has no warn-only mode - a failing hook always blocks the stage it runs in
        - so the only way to honor D6 is to default both hooks to pre-push."""
        for hook in self.hooks:
            self.assertIn("stages", hook, f"hook {hook['id']} does not pin a stage")
            self.assertNotIn("pre-commit", hook["stages"],
                             f"hook {hook['id']} would block commits on partial work")
            self.assertIn("pre-push", hook["stages"])

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
