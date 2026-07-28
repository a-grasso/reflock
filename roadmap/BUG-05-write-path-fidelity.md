# BUG-05 acceptance contract: stamp rewrites bytes it is not stamping

Source: review 2026-07-28
Owner: agent · Tier: near · Touches: [reflock.py](../reflock.py), [test_reflock.py](../test_reflock.py), [run_bench.py](../evalbench/run_bench.py), [fixtures/](../evalbench/fixtures/)
Locked decisions: [D3](DECIDED.md#d3-zero-runtime-dependencies)

## The defect

`stamp` splices 8 hex characters into a line. It should be the most surgical
write in the tool. Instead `cmd_stamp` reconstructs the whole file from
`idx.lines` and rewrites it:

```python
with open(os.path.join(idx.root, rel), "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
```

`idx.lines` came from a universal-newline read, so every line terminator in the
file has already been normalized to `\n` by the time it is written back. On a
CRLF file, stamping one pin rewrites every line ending in the file:

```
before:  crlf [z](t.md)<!--@-->\r\n   second line\r\n
after:   crlf [z](t.md)<!--@cc733436-->\n   second line\n
```

"second line" holds no reference and was still rewritten. On a Windows or mixed
repo, a one-pin stamp is a whole-file diff. A file with no trailing newline also
gains one.

### The second defect, same write

`git ls-files` lists symlinks, `is_text()`/`open()` follow them, so a symlinked
file is a reference source like any other - and `open(path, "w")` writes
*through* the link. Reproduced with a link pointing outside the repository:

```
sym2/link.md -> ../outside/victim.md

$ reflock stamp
Stamped 1 pin(s).
$ git status --short
                       # empty
```

`../outside/victim.md` was modified, outside the tree, with git showing nothing.
It needs a repo carrying a symlink whose destination holds a stampable pin, so
it is not a likely accident - but "mutates files git will not show you" is not a
property a stamping tool may have.

## Required behavior

### Byte fidelity

After `stamp`, a file differs from its previous content **only** in the pin hex
spans that were filled or reblessed. Specifically preserved:

- every line terminator in the file, including `\r\n` and a mixed-ending file,
  on stamped and unstamped lines alike
- the absence of a trailing newline
- trailing blank lines, and any other whitespace outside the spliced span

The pin spans `plan_stamp` computed are offsets into the line *content*, so they
stay valid when the terminator is preserved rather than stripped; the write must
not rely on `idx.lines` having lost it.

### Symlinks are not reference sources

A symlinked file is excluded from the set of files scanned for references, so
`stamp` cannot write through one. It stays in the index as a *target*: a
reference pointing at a symlink still resolves and still fingerprints, because
that is a read and reading through a link is what the author asked for.

One policy point, in `scoped_files`, not a guard bolted onto the write - if the
plan and the write disagreed about which files are eligible, `stamp --check`
would report edits `stamp` then refuses to make, which is the BUG-03 shape
again.

Content reachable only through a symlink stays reachable as a target. Content
*inside* a symlinked file is checked via its real path when that path is
tracked; when it is not, it is out of scope, exactly as an untracked file is.

## Explicitly out of scope

- Line-ending normalization as a feature. reflock has no opinion on what a file
  uses; it must simply not change it. That is `.gitattributes`'s job.
- Symlinked *directories*. `git ls-files` does not descend them, so they never
  reach the index as sources today.
- Any change to how the index is built for hashing. `normalize()` collapses
  whitespace, so terminators never affected a fingerprint - this is purely a
  write-path defect.

## Invariants

- Existing unit tests and evalbench fixtures stay green, unmodified.
- `stamp` on an LF file with a trailing newline produces exactly what it
  produces today - the common case must be untouched.
- `stamp --check` still writes nothing, and still reports exactly what `stamp`
  writes.
- No new imports outside the stdlib (D3).

## Harness change this needs

`materialize()` copies fixture repos with `shutil.copytree(..., symlinks=False)`,
which replaces a symlink with a copy of its destination - so a symlink fixture
cannot exist. Copy with `symlinks=True`. No current fixture contains one, so
nothing else changes.

## Fixtures to add

| Fixture | Asserts |
|---|---|
| `stamp-preserves-crlf` | a CRLF file keeps `\r\n` on every line after stamping, including the stamped line |
| `stamp-preserves-no-trailing-newline` | a file not ending in a newline still does not after stamping |
| `stamp-ignores-symlinked-source` | a symlinked file is not scanned for references, so `check` reports the real path only once and `stamp` reports one edit, not two |

## Unit tests to add

- CRLF file: after `stamp`, the file's bytes differ from before only inside the
  pin span (assert on bytes, not on a decoded string).
- Mixed `\r\n` / `\n` file: each line keeps the terminator it started with.
- File with no trailing newline: still none afterwards.
- File with two trailing blank lines: still two.
- LF file, ordinary case: byte-for-byte what today's code produces.
- A symlinked source pointing **outside** the repository is not stamped, and the
  destination file is byte-identical afterwards. This is the security-shaped
  half and belongs in the unit tests, where the temp tree is controlled.
- A reference *to* a symlink still resolves and stamps (the read direction is
  unaffected).

## Verification

```
make gate
```

## Definition of done

1. Fixtures and tests above pass; nothing existing was modified.
2. README's `stamp` description states that it preserves line endings and does
   not follow symlinks. Re-stamp the file.
3. `ROADMAP.yaml` marks BUG-05 `done`.
