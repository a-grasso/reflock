# SUG-05 acceptance contract: a companion Homebrew formula for `reflock suggest`

Source: [issue #20](https://github.com/a-grasso/reflock/issues/20)
Owner: agent · Tier: near · Touches: [packaging/brew.py](../../packaging/brew.py), [.github/workflows/release.yml](../../.github/workflows/release.yml), [.github/workflows/ci.yml](../../.github/workflows/ci.yml)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The problem

Homebrew formulae have no optional dependencies - `depends_on => :optional`
and `--with-*` were removed in Homebrew 2.0 and are not returning, because
bottles cannot exist if the dependency set varies per install. `pip install
reflock[suggest]` (SUG-04) has no Homebrew equivalent, so `reflock suggest`
needs its own formula rather than a flag on the existing one. Homebrew's own
`onnxruntime` formula is the C library only, with no Python bindings, and
ONNX Runtime publishes no source distribution - so the runtime has to come
from PyPI wheels, pinned and verified like any other formula resource.

## The decision

`packaging/brew.py` generates two formulae from one script, called with
`--url`/`--sha256`/`--out` at release time:

- **`reflock.rb`** - byte-identical to the previous hand-maintained heredoc.
  The standard-library tool; unchanged behavior, unchanged install.
- **`reflock-suggest.rb`** - the same source tarball, plus `onnxruntime` and
  `numpy` installed from PyPI wheels pinned by exact version and sha256
  (`WHEELS` in `packaging/brew.py`), into a private venv inside `libexec`,
  `--no-deps` (reflock needs only the inference session; ONNX Runtime's other
  declared dependencies serve its own converter tooling, not `reflock
  suggest`). `depends_on arch: :arm64` and a `macos:` floor derived from the
  oldest macOS the pinned wheels actually run on. Both formulae install the
  same `reflock` command into `bin`, and a formula cannot add packages to
  another formula's interpreter, so a user chooses one, not both. There is no
  `conflicts_with "reflock"`: Homebrew trusts a third-party tap per formula,
  so installing `reflock-suggest` trusts only that formula, and the
  conflict declaration then refuses to load the untrusted `reflock` formula
  and aborts the install (seen in CI). Installing both fails at `brew link`
  instead, naming `bin/reflock`.

Both formulae's `test do` blocks exercise a real `stamp`/`check` round trip,
not just `--help`, on the theory that a formula shipping an unimportable or
unrunnable command must fail in CI, not in a user's terminal.
`reflock-suggest`'s test additionally imports `numpy, onnxruntime` from the
private venv and runs `reflock suggest --dry-run` against a bare, empty git
repo - nothing to pin, so it exits 0 before ever touching the model download.

`.github/workflows/release.yml` calls `packaging/brew.py` to publish both
formulae to the tap. `.github/workflows/ci.yml` adds a `brew-formulae` job on
`macos-15` that installs and tests both formulae from the checkout on every
change, so what CI verifies is what ships - not a formula that only gets
exercised at release time.

## Explicitly out of scope

- Intel (`x86_64`) wheels/formula. `ARCH = "arm64"` only, for now; the model
  runtime formula tracks Apple Silicon first because that is the population
  CI and the maintainer's own machine cover.
- Publishing the model itself through Homebrew. `reflock suggest` downloads
  and sha256-verifies the model on first use (SUG-02/`fetch.py`) regardless
  of which formula installed the command.

## Definition of done

1. `packaging/brew.py --url ... --sha256 ... --out DIR` writes `reflock.rb`
   byte-identical to the prior heredoc, and a `reflock-suggest.rb` that
   installs without loading any other formula (no `conflicts_with`), and
   passes its `test do` block.
2. `.github/workflows/ci.yml`'s `brew-formulae` job (macOS) installs and
   tests both formulae from the checkout.
3. `.github/workflows/release.yml` calls `packaging/brew.py` to publish both
   formulae.
4. `just gate` is green.
5. `ROADMAP.yaml` lists SUG-05 under `done`.
