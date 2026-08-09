check:
    python3 reflock.py check

stamp:
    python3 reflock.py stamp

suspects:
    python3 reflock.py suspects --all

test:
    python3 -m unittest -v test_reflock

bench:
    python3 evalbench/run_bench.py

# The authoritative gate: everything that must be green to commit.
# `suspects` is deliberately excluded - it is an advisory heuristic and exits
# nonzero whenever it has anything to say, which is most of the time.
gate: test bench check

# Bump the version, gate, commit, then tag and push to trigger release.yml
# (GitHub release + Homebrew tap formula). Usage: just release 0.1.7
release version:
    python3 -c "import re; p='reflock_lib/__init__.py'; s=open(p).read(); open(p,'w').write(re.sub(r'__version__ = \".*\"', '__version__ = \"{{version}}\"', s))"
    # README.md and docs/*.md only - docs/roadmap/ and docs/adr/ are historical
    # records, and DOC-01 quotes an old rev *as the bug it documents*.
    python3 -c "import re,glob; [open(p,'w').write(re.sub(r'rev: v[0-9.]+', 'rev: v{{version}}', open(p).read())) for p in ['README.md'] + glob.glob('docs/*.md')]"
    just gate
    git add reflock_lib/__init__.py README.md docs
    git commit -m "Bump version to {{version}}"
    git push origin main
    git tag -a v{{version}} -m v{{version}}
    git push origin v{{version}}
