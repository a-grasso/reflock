# SUG-04 acceptance contract: `[suggest]` is an extra, not a dependency

Source: [issue #20](https://github.com/a-grasso/reflock/issues/20)
Owner: agent · Tier: near · Touches: [pyproject.toml](../../pyproject.toml)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The problem

`reflock suggest` needs ONNX Runtime to run the anchor model, but `reflock
check` runs in every CI job on every commit and must stay pure stdlib (D3) -
the checker is the product; the suggester runs once, at adoption. Until now
reflock had no `pyproject.toml` at all (it distributes as a single symlinked
file); publishing to PyPI with an optional model runtime is the first thing
that needs one.

## The decision

`pip install reflock` stays dependency-free: `[project] dependencies = []`.
`pip install 'reflock[suggest]'` additionally installs `onnxruntime>=1.17`,
whose own dependency on `numpy` brings that in for free - so the extra names
one package, not two. `[project.optional-dependencies].suggest` is the only
place a third-party name appears in the package metadata, and the comment
above it points at `reflock_lib/suggest/runtime.py` as the one module that
actually imports it.

`[tool.setuptools].packages` lists both `reflock_lib` and
`reflock_lib.suggest` explicitly, so the subpackage ships in the wheel; the
single-file/symlink distribution story (`install.sh`, `reflock.py`) is
unaffected and remains the primary install path in the README.

## Explicitly out of scope

- Actually publishing to PyPI - this contract only gets the metadata right;
  publication is a release-process decision, not this item's.
- Version-pinning `onnxruntime` tightly. `>=1.17` is a floor; `packaging/brew.py`
  (SUG-05) pins an exact version for the Homebrew wheels independently, since
  that path has no resolver to fall back on.

## Definition of done

1. `pyproject.toml` exists at the repo root with `dependencies = []` for the
   core package and `optional-dependencies.suggest = ["onnxruntime>=1.17"]`.
2. `python3 -m pip install .` (core) succeeds without installing any
   third-party package; `python3 -m pip install '.[suggest]'` additionally
   installs `onnxruntime` and `numpy`.
3. `just gate` is green.
4. `docs/manual.md` and `README.md` mention `pip install 'reflock[suggest]'`
   as an install option for `reflock suggest`.
5. `ROADMAP.yaml` lists SUG-04 under `done`.
