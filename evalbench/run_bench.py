#!/usr/bin/env python3
"""reflock eval bench — runs reflock against isolated fixture repos and checks
that the findings match what's expected.

Each fixture under fixtures/<name>/ is a real (temporary, disposable) git repo:
  fixtures/<name>/repo/          the tree to copy and git-init
  fixtures/<name>/scenario.json  what to run and what reflock must find

Why real git repos: reflock's file listing and gitignore-awareness
(list_files, git_ignored) only engage inside an actual git repository — a
plain temp directory silently falls back to a directory walk. Fixtures that
exercise .gitignore / untracked-file semantics need the real thing to mean
anything. See scenario.json's "git" block.

Usage:
  python3 evalbench/run_bench.py              # run every fixture
  python3 evalbench/run_bench.py dangling-file # run one fixture by name
  python3 evalbench/run_bench.py -v            # show a diff for failures
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BENCH_DIR)
REFLOCK = os.path.join(ROOT, "reflock.py")
FIXTURES_DIR = os.path.join(BENCH_DIR, "fixtures")


def load_scenario(name: str) -> dict:
    with open(os.path.join(FIXTURES_DIR, name, "scenario.json"), encoding="utf-8") as fh:
        return json.load(fh)


def materialize(name: str, scenario: dict, tmp: str) -> None:
    src = os.path.join(FIXTURES_DIR, name, "repo")
    # symlinks=True: the default replaces a link with a copy of its destination,
    # so a fixture could not express a symlink at all - which BUG-05 needs.
    shutil.copytree(src, tmp, dirs_exist_ok=True, symlinks=True)
    git = scenario.get("git", {})
    if git.get("skip", False):
        return  # fixture deliberately exercises the non-git walk fallback
    run = lambda *cmd: subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, check=True)
    run("git", "init", "-q")
    run("git", "-c", "user.email=bench@reflock.test", "-c", "user.name=reflock-bench",
        "commit", "--allow-empty", "-q", "-m", "init")
    track = git.get("track")
    if track is None:
        run("git", "add", "-A")
    elif track:
        run("git", "add", "--", *track)
    if track is None or track:
        run("git", "-c", "user.email=bench@reflock.test", "-c", "user.name=reflock-bench",
            "commit", "-q", "-m", "fixture")


def run_reflock(tmp: str, cmd: str, args: list[str]) -> tuple[int, str, str]:
    p = subprocess.run([sys.executable, REFLOCK, "--root", tmp, cmd, *args],
                        cwd=tmp, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


# Every key a step may carry. Validated rather than read with .get(), because a
# key the harness does not recognise used to be ignored in silence - one typo
# (`expect_containss`) turned an assertion into a fixture that passed having
# checked nothing.
STEP_KEYS = frozenset({
    "description", "write", "cmd", "args",
    "expect_exit", "expect_json",
    "expect_contains", "expect_not_contains", "expect_file_regex",
    "expect_stderr", "expect_stderr_not_contains", "expect_stderr_empty",
    "expect_stdout_empty",
    "expect_stdout_same_as_step", "expect_tree_unchanged_since_step",
})


class StepContext:
    """What a step needs to know about the steps before it.

    Populated as a scenario runs: `stdouts[i]` and `snapshots[i]` are step i's
    stdout and the tree's content immediately after step i finished.
    """
    def __init__(self):
        self.stdouts: list[str] = []
        self.snapshots: list[dict[str, bytes]] = []


def snapshot_tree(tmp: str) -> dict[str, bytes]:
    """Every file's bytes, keyed by repo-relative path. `.git` is excluded: it is
    the harness's own bookkeeping, not part of what a command promises to leave
    alone."""
    snap = {}
    for dirpath, dirnames, filenames in os.walk(tmp):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            ap = os.path.join(dirpath, fn)
            rel = os.path.relpath(ap, tmp).replace(os.sep, "/")
            try:
                with open(ap, "rb") as fh:
                    snap[rel] = fh.read()
            except OSError as e:
                snap[rel] = f"<unreadable: {e}>".encode()
    return snap


def diff_snapshots(before: dict[str, bytes], after: dict[str, bytes]) -> list[str]:
    """Human-readable description of every difference (empty = identical)."""
    diffs = []
    for rel in sorted(set(after) - set(before)):
        diffs.append(f"{rel} was created")
    for rel in sorted(set(before) - set(after)):
        diffs.append(f"{rel} was deleted")
    for rel in sorted(set(before) & set(after)):
        if before[rel] != after[rel]:
            diffs.append(f"{rel} changed:\n"
                          f"      before: {before[rel]!r}\n"
                          f"      after:  {after[rel]!r}")
    return diffs


def _step_ref(step: dict, key: str, current: int, have: int) -> tuple[int | None, str | None]:
    """Validate a step-index reference. Returns (index, error)."""
    n = step[key]
    if not isinstance(n, int) or isinstance(n, bool):
        return None, f"{key}: expected an integer step index, got {n!r}"
    if n < 0 or n >= current or n >= have:
        return None, (f"{key}: step {n} has not run yet (this is step {current}); "
                      f"a step may only refer to an earlier one")
    return n, None


def check_step(tmp: str, step: dict, ctx: StepContext) -> list[str]:
    """Run one step; return a list of human-readable failure descriptions (empty = pass)."""
    fails = []
    unknown = sorted(set(step) - STEP_KEYS)
    if unknown:
        fails.append(f"unknown step key(s): {', '.join(unknown)} "
                      f"(known: {', '.join(sorted(STEP_KEYS))})")
        return fails
    current = len(ctx.stdouts)
    for relpath, content in step.get("write", {}).items():
        path = os.path.join(tmp, relpath)
        os.makedirs(os.path.dirname(path) or tmp, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    code, out, err = run_reflock(tmp, step["cmd"], step.get("args", []))
    if "expect_exit" in step and code != step["expect_exit"]:
        fails.append(f"exit code: expected {step['expect_exit']}, got {code} (stderr: {err.strip()})")
    if "expect_json" in step:
        try:
            actual = json.loads(out)
        except json.JSONDecodeError as e:
            fails.append(f"stdout is not valid JSON: {e}\n--- stdout ---\n{out}")
        else:
            if actual != step["expect_json"]:
                fails.append("json mismatch:\n"
                              f"  expected: {json.dumps(step['expect_json'])}\n"
                              f"  actual:   {json.dumps(actual)}")
    for needle in step.get("expect_contains", []):
        if needle not in out:
            fails.append(f"expected stdout to contain {needle!r}\n--- stdout ---\n{out}")
    for needle in step.get("expect_not_contains", []):
        if needle in out:
            fails.append(f"expected stdout to NOT contain {needle!r}\n--- stdout ---\n{out}")
    for needle in step.get("expect_stderr", []):
        if needle not in err:
            fails.append(f"expected stderr to contain {needle!r}\n--- stderr ---\n{err}")
    for needle in step.get("expect_stderr_not_contains", []):
        if needle in err:
            fails.append(f"expected stderr to NOT contain {needle!r}\n--- stderr ---\n{err}")
    if step.get("expect_stderr_empty") and err != "":
        fails.append(f"expected stderr to be empty\n--- stderr ---\n{err}")
    if step.get("expect_stdout_empty") and out != "":
        fails.append(f"expected stdout to be empty\n--- stdout ---\n{out}")
    for relpath, pattern in step.get("expect_file_regex", {}).items():
        # newline="": a file-content assertion must see the file's real line
        # endings. Universal-newline decoding turns \r\n into \n, so a fixture
        # could not tell whether a command had rewritten them (BUG-05).
        with open(os.path.join(tmp, relpath), encoding="utf-8", newline="") as fh:
            content = fh.read()
        if not re.search(pattern, content):
            fails.append(f"expected {relpath} to match /{pattern}/\n--- content ---\n{content}")
    if "expect_stdout_same_as_step" in step:
        n, err_msg = _step_ref(step, "expect_stdout_same_as_step", current, len(ctx.stdouts))
        if err_msg:
            fails.append(err_msg)
        elif out != ctx.stdouts[n]:
            fails.append(f"stdout differs from step {n}'s\n"
                          f"--- step {n} ---\n{ctx.stdouts[n]}\n--- this step ---\n{out}")
    after = snapshot_tree(tmp)
    if "expect_tree_unchanged_since_step" in step:
        n, err_msg = _step_ref(step, "expect_tree_unchanged_since_step", current,
                                len(ctx.snapshots))
        if err_msg:
            fails.append(err_msg)
        else:
            diffs = diff_snapshots(ctx.snapshots[n], after)
            if diffs:
                fails.append(f"tree changed since step {n}:\n    "
                              + "\n    ".join(diffs))
    ctx.stdouts.append(out)
    ctx.snapshots.append(after)
    return fails


def run_fixture(name: str, verbose: bool) -> tuple[bool, list[str]]:
    scenario = load_scenario(name)
    with tempfile.TemporaryDirectory(prefix="reflock-bench-") as tmp:
        materialize(name, scenario, tmp)
        all_fails = []
        ctx = StepContext()
        for i, step in enumerate(scenario["steps"]):
            fails = check_step(tmp, step, ctx)
            for f in fails:
                all_fails.append(f"step {i} ({step['cmd']} {' '.join(step.get('args', []))}): {f}")
        return (not all_fails), all_fails


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="run only these fixtures (default: all)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print failure detail")
    args = ap.parse_args(argv)

    all_names = sorted(n for n in os.listdir(FIXTURES_DIR)
                        if os.path.isfile(os.path.join(FIXTURES_DIR, n, "scenario.json")))
    names = args.names or all_names
    unknown = [n for n in names if n not in all_names]
    if unknown:
        print(f"unknown fixture(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    passed, failed = 0, []
    for name in names:
        ok, fails = run_fixture(name, args.verbose)
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {name}")
        if ok:
            passed += 1
        else:
            failed.append(name)
            if args.verbose:
                for f in fails:
                    print(f"        {f}")

    print(f"\n{passed}/{len(names)} fixture(s) passed.")
    if failed:
        print(f"failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
