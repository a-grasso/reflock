"""Get the anchor model onto disk, once, and only the bytes we published.

The model is a few hundred megabytes, so it is not shipped with reflock (a
pip wheel or a tap bottle would carry it on every upgrade). It is a release
asset on the reflock repository, downloaded on the first `reflock suggest` and
cached under the XDG cache directory.

Every file is checked against the sha256 in MANIFEST before it is used: a
truncated download, a proxy's error page, or a swapped asset fails here, and a
file that fails is never renamed into place. After a verified download the
manifest is written next to the files, so later runs compare that record and
the file sizes instead of re-hashing half a gigabyte each time.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request

# Bumped, with new hashes, whenever a model is published. The name is the
# cache directory, so an old model is never mistaken for a new one.
MANIFEST = {
    "name": "suggest-model-v1",
    "url": "https://github.com/a-grasso/reflock/releases/download/suggest-model-v1/",
    "files": {
        "anchor.onnx": {
            "sha256": "4da845813e6ce39296b754878b165e77ef0de0ce3698550681f1ac7fd75240e1",
            "size": 482919488
        },
        "config.json": {
            "sha256": "4ee95d17b513ae257de2f382e4aafad23eac4c31814adced022222c22269a1d3",
            "size": 496
        },
        "tokenizer.json": {
            "sha256": "6c8aaa9a542084f2457eab775d4eeb51f92a70c0fd9de28d5edb0ddec3c08d30",
            "size": 3583228
        }
    }
}


class FetchError(Exception):
    """The model could not be downloaded or did not verify."""


def cache_root() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "reflock", "models")


def _cached(path: str, manifest: dict) -> bool:
    try:
        with open(os.path.join(path, "manifest.json"), encoding="utf-8") as fh:
            if json.load(fh) != manifest:
                return False
        return all(os.path.getsize(os.path.join(path, f)) == meta["size"]
                   for f, meta in manifest["files"].items())
    except (OSError, ValueError):
        return False


def _download(url: str, dest: str, meta: dict, progress) -> None:
    part = dest + ".part"
    h = hashlib.sha256()
    done = 0
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                out.write(chunk)
                done += len(chunk)
                progress(os.path.basename(dest), done, meta["size"])
    except OSError as e:
        _remove(part)
        raise FetchError("could not download %s: %s" % (url, e)) from None
    if h.hexdigest() != meta["sha256"] or done != meta["size"]:
        _remove(part)
        raise FetchError("%s did not verify: got sha256 %s (%d bytes), expected %s (%d bytes)"
                         % (url, h.hexdigest(), done, meta["sha256"], meta["size"]))
    os.replace(part, dest)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _stderr_progress(name: str, done: int, total: int) -> None:
    if sys.stderr.isatty() and total:
        sys.stderr.write("\rdownloading %s  %3d%%" % (name, 100 * done // total))
        if done >= total:
            sys.stderr.write("\n")
        sys.stderr.flush()


def ensure(manifest: dict = MANIFEST, root: str | None = None, progress=_stderr_progress) -> str:
    """Directory holding a verified copy of the model, downloading it if needed."""
    path = os.path.join(root or cache_root(), manifest["name"])
    if _cached(path, manifest):
        return path
    if not all(meta["sha256"] for meta in manifest["files"].values()):
        raise FetchError("no model has been published for this version of reflock yet; "
                         "pass --model DIR to use a local one")
    os.makedirs(path, exist_ok=True)
    _remove(os.path.join(path, "manifest.json"))
    for name, meta in manifest["files"].items():
        _download(manifest["url"] + name, os.path.join(path, name), meta, progress)
    with open(os.path.join(path, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path
