#!/usr/bin/env python3
"""Point `reflock suggest` at a newly exported model.

    python3 suggest-model/publish.py /tmp/anchor --tag suggest-model-v1

Hashes the three artifact files, rewrites MANIFEST in
reflock_lib/suggest/fetch.py to name them, and prints the `gh release`
command that uploads them. It does not upload: publishing is the one
irreversible step, so it stays a command a maintainer reads and runs.

The manifest's `name` is the tag, and is the cache directory, so users of an
older reflock keep their model and users of this one fetch the new one.
Stdlib only; runs anywhere.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FETCH = os.path.join(os.path.dirname(HERE), "reflock_lib", "suggest", "fetch.py")
FILES = ("anchor.onnx", "config.json", "tokenizer.json")
REPO = "a-grasso/reflock"


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("artifact", help="export.py's output directory")
    ap.add_argument("--tag", required=True, help="release tag, e.g. suggest-model-v1")
    args = ap.parse_args()

    files = {}
    for name in FILES:
        path = os.path.join(args.artifact, name)
        if not os.path.isfile(path):
            sys.exit("publish: %s is missing" % path)
        files[name] = {"sha256": sha256(path), "size": os.path.getsize(path)}
    manifest = {
        "name": args.tag,
        "url": "https://github.com/%s/releases/download/%s/" % (REPO, args.tag),
        "files": files,
    }
    with open(FETCH, encoding="utf-8") as fh:
        src = fh.read()
    body = json.dumps(manifest, indent=4)
    new, n = re.subn(r"^MANIFEST = \{.*?^\}\n", "MANIFEST = %s\n" % body, src,
                     count=1, flags=re.S | re.M)
    if n != 1:
        sys.exit("publish: no MANIFEST block found in %s" % FETCH)
    with open(FETCH, "w", encoding="utf-8") as fh:
        fh.write(new)
    print("updated %s" % os.path.relpath(FETCH))
    print("\nupload with:\n  gh release create %s --repo %s --title %s \\\n"
          "    --notes 'Anchor model for reflock suggest.' \\\n    %s"
          % (args.tag, REPO, args.tag,
             " ".join(os.path.join(args.artifact, f) for f in FILES)))


if __name__ == "__main__":
    main()
