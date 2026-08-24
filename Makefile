PY ?= python3

.PHONY: help install lint test experiments bench charts receipts verify evidence pdf sweep clean

help:
	@echo "install      editable install with the dev extra"
	@echo "lint         ruff check and format check"
	@echo "test         pytest with coverage, writing reports/"
	@echo "experiments  re-run all five, writing docs/experiments/*.json"
	@echo "bench        time the ceiling against retrieval at five corpus sizes"
	@echo "charts       redraw the latency chart from the benchmark json"
	@echo "receipts     re-measure every figure, then check it against the documents"
	@echo "verify       lint, test, receipts. The one command the README promises."
	@echo "evidence     diagram, screenshots, demo video and the README image check."
	@echo "             Needs the evidence extra: pip install -e '.[evidence]'"
	@echo "pdf          lay out the defense guide for offline reading"

install:
	$(PY) -m pip install -e ".[dev]"

lint:
	$(PY) -m ruff check src tests tools experiments benchmark
	$(PY) -m ruff format --check src tests tools experiments benchmark

test:
	$(PY) -m pytest -q --junitxml=reports/junit.xml \
		--cov=chunkaudit --cov-report=json:reports/coverage.json \
		--cov-report=xml:reports/coverage.xml --cov-report=term-missing

experiments:
	$(PY) experiments/exp01_the_gap_the_standard_metric_hides.py
	$(PY) experiments/exp02_who_can_fix_this.py
	$(PY) experiments/exp03_the_guarantee_threshold.py
	$(PY) experiments/exp04_what_overlap_costs_and_buys.py
	$(PY) experiments/exp05_which_lever_matters.py

bench:
	$(PY) benchmark/bench_ceiling.py

# Reads benchmark/results/audit_latency.json rather than timing anything, so the
# chart and the README table can never disagree about a number.
charts:
	$(PY) benchmark/plot_results.py

# Reads the reports that `make test` produced rather than running pytest again,
# so a red test surfaces as a failing test target and not as a traceback from a
# metrics script.
receipts:
	$(PY) tools/collect_metrics.py --skip-tests
	$(PY) tools/check_numbers.py --strict

verify: lint test receipts

evidence:
	$(PY) tools/render_diagram.py
	$(PY) tools/capture_screenshots.py
	$(PY) tools/record_demo.py
	$(PY) tools/check_readme.py README.md

pdf:
	$(PY) tools/build_pdf.py docs/defense-guide.md

sweep:
	$(PY) -m chunkaudit sweep --html reports/sweep.html --json reports/sweep.json

clean:
	rm -rf reports .cache .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
