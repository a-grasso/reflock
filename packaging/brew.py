#!/usr/bin/env python3
"""Write the Homebrew formulae for a release: `reflock` and `reflock-suggest`.

    python3 packaging/brew.py --url URL --sha256 HEX --out tap/Formula

`reflock` is the standard-library tool. `reflock-suggest` is the same tool
plus the runtime `reflock suggest` needs - ONNX Runtime and numpy in a
private virtualenv - so a user opts into a few hundred megabytes by naming the
formula, and `brew install reflock` stays what it always was. The two install
the same `reflock` command, rather than one depending on the other: a formula
cannot add packages to another formula's interpreter. They declare no
`conflicts_with`, because Homebrew trusts a third-party tap one formula at a
time: `brew install a-grasso/tap/reflock-suggest` trusts that formula only,
and a `conflicts_with "reflock"` then refuses to load the other, untrusted
one, so the install dies. Installing both still fails, at `brew link`, whose
error names the file both want.

Homebrew's own `onnxruntime` is the C library with no Python bindings, and
ONNX Runtime publishes no source distribution, so the runtime is installed from
PyPI wheels pinned here by version and sha256. The model itself is not in
either formula; `reflock suggest` downloads and verifies it on first use.

Used by .github/workflows/release.yml to publish and by ci.yml to install
both formulae from the checkout on macOS, so what CI tests is what ships.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request

# The runtime `reflock-suggest` ships. Bump deliberately; parity.py is the
# check that a new ONNX Runtime still makes laya's picks.
WHEELS = {"onnxruntime": "1.30.0", "numpy": "2.5.3"}
PYTHON = "3.13"
PLATFORM = "macosx"
ARCH = "arm64"
MACOS = {11: "big_sur", 12: "monterey", 13: "ventura", 14: "sonoma", 15: "sequoia"}

COMMON_INSTALL = '''\
    # reflock.py is the entry point, but the implementation lives in
    # the reflock_lib package beside it - installing the script alone
    # ships a command that dies on import. Both go to libexec; the
    # symlink into bin is safe because Python resolves it before
    # putting the script's directory on sys.path, which is the same
    # property install.sh relies on.
    libexec.install "reflock.py", "reflock_lib"'''

COMMON_TEST = '''\
    # Exercising a real stamp/check round trip, not just --help: a
    # formula that ships an unimportable or unrunnable command must
    # fail here rather than in a user's terminal.
    assert_match "reflock #{version}", shell_output("#{bin}/reflock --version")
    (testpath/"t.md").write("# H\\n\\n## Decision\\n\\nWe chose X.\\n")
    (testpath/"a.md").write("Per [d](t.md#decision)<!--@-->.\\n")
    system bin/"reflock", "stamp"
    assert_match(/<!--@[0-9a-f]{8}-->/, (testpath/"a.md").read)
    system bin/"reflock", "check"'''


def header(cls: str, desc: str, url: str, sha256: str) -> str:
    return '''\
require "language/python"

class %s < Formula
  include Language::Python::Shebang

  desc "%s"
  homepage "https://github.com/a-grasso/reflock"
  url "%s"
  sha256 "%s"
  license "MIT"
''' % (cls, desc, url, sha256)


def reflock(url: str, sha256: str) -> str:
    return header("Reflock", "Lockfile for cross-references in a mixed docs and code tree",
                  url, sha256) + '''
  depends_on "python@%s"

  def install
%s
    rewrite_shebang detected_python_shebang, libexec/"reflock.py"
    bin.install_symlink libexec/"reflock.py" => "reflock"
  end

  test do
%s
  end
end
''' % (PYTHON, COMMON_INSTALL, COMMON_TEST)


def macos_floor(filename: str) -> int:
    return int(filename.split("-macosx_")[1].split("_")[0])


def wheel(name: str, version: str) -> tuple[str, str, int]:
    """(url, sha256, oldest macOS) of the widest-running wheel for PYTHON on ARCH."""
    with urllib.request.urlopen("https://pypi.org/pypi/%s/%s/json" % (name, version),
                                timeout=60) as r:
        files = json.load(r)["urls"]
    tag = "cp%s" % PYTHON.replace(".", "")
    hits = [f for f in files if f["packagetype"] == "bdist_wheel"
            and "-%s-%s-" % (tag, tag) in f["filename"]
            and PLATFORM in f["filename"] and f["filename"].endswith(ARCH + ".whl")]
    if not hits:
        raise SystemExit("brew.py: no %s %s wheel for %s on macOS %s"
                         % (name, version, tag, ARCH))
    # Several builds differ only in the oldest macOS they run on; the oldest
    # target runs on the most machines.
    best = min(hits, key=lambda f: macos_floor(f["filename"]))
    return best["url"], best["digests"]["sha256"], macos_floor(best["filename"])


def reflock_suggest(url: str, sha256: str, wheels: dict[str, tuple[str, str, int]]) -> str:
    resources = "".join('''
  resource "%s" do
    url "%s"
    sha256 "%s"
  end
''' % (name, u, s) for name, (u, s, _) in wheels.items())
    floor = MACOS[max(m for _, _, m in wheels.values())]
    return header("ReflockSuggest",
                  "Lockfile for cross-references, with `reflock suggest` and its model runtime",
                  url, sha256) + '''
  depends_on arch: :%s
  depends_on macos: :%s
  depends_on "python@%s"
%s
  def install
%s
    # ONNX Runtime has no source distribution, so these are wheels, and
    # --no-deps because reflock needs only its inference session: the
    # rest of its declared dependencies serve the converter tooling.
    python = Formula["python@%s"].opt_bin/"python%s"
    venv = libexec/"venv"
    system python, "-m", "venv", "--without-pip", venv
    wheels = resources.map do |r|
      whl = buildpath/File.basename(r.url)
      cp r.cached_download, whl
      whl
    end
    system python, "-m", "pip", "--python", venv/"bin/python", "install",
           "--no-deps", "--no-index", "--no-compile", *wheels
    rewrite_shebang python_shebang_rewrite_info(venv/"bin/python"), libexec/"reflock.py"
    bin.install_symlink libexec/"reflock.py" => "reflock"
  end

  test do
%s
    system libexec/"venv/bin/python", "-c", "import numpy, onnxruntime"
    # Nothing to pin: exits 0 before the model is needed, so no download.
    system "git", "init", "-q"
    system bin/"reflock", "suggest", "--dry-run"
  end
end
''' % (ARCH, floor, PYTHON, resources, COMMON_INSTALL, PYTHON, PYTHON, COMMON_TEST)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", required=True, help="source tarball")
    ap.add_argument("--sha256", required=True, help="of the source tarball")
    ap.add_argument("--out", required=True, help="the tap's Formula directory")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    wheels = {name: wheel(name, v) for name, v in WHEELS.items()}
    for name, text in (("reflock.rb", reflock(args.url, args.sha256)),
                       ("reflock-suggest.rb", reflock_suggest(args.url, args.sha256, wheels))):
        with open(os.path.join(args.out, name), "w") as fh:
            fh.write(text)
        print("wrote %s" % os.path.join(args.out, name))


if __name__ == "__main__":
    main()
