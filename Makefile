.PHONY: check stamp suspects test bench

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
