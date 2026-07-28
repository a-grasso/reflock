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
    python3 -c "import re; p='README.md'; s=open(p).read(); open(p,'w').write(re.sub(r'rev: v[0-9.]+', 'rev: v{{version}}', s))"
    just gate
    git add reflock_lib/__init__.py README.md
    git commit -m "Bump version to {{version}}"
    git push origin main
    git tag -a v{{version}} -m v{{version}}
    git push origin v{{version}}
