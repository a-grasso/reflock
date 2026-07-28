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
