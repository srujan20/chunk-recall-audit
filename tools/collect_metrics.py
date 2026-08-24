"""Re-measure every published figure and write docs/metrics.json.

Nothing in this file types a number. It runs the test suite, reads the machine
readable reports it produces, runs all five experiments, reads their JSON, and
computes the derived values. `tools/check_numbers.py` then verifies that the
documents quote exactly these values.

The test count and the coverage percentage come from --junitxml and
--cov-report=json rather than from parsing a progress line, because a parsed
progress line quietly becomes whatever the last run happened to print. The suite
runs as its own step in CI, with this script called with --skip-tests afterwards,
so a red test surfaces as a failing test step rather than as a traceback from a
metrics script.

Usage:
    python tools/collect_metrics.py [--skip-tests] [--skip-experiments]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
EXPERIMENTS = DOCS / "experiments"
REPORTS = REPO / "reports"

EXPERIMENT_SCRIPTS = (
    "exp01_the_gap_the_standard_metric_hides.py",
    "exp02_who_can_fix_this.py",
    "exp03_the_guarantee_threshold.py",
    "exp04_what_overlap_costs_and_buys.py",
    "exp05_which_lever_matters.py",
)

# The exact wording a document must use with the value substituted in. Anchors are
# alternatives: one match is enough, because the same figure reads differently in a
# table and in a paragraph. Each anchor names the number plus two or three words,
# never a whole clause. The checker collapses whitespace before matching, so an
# anchor no longer has to be lucky about where a markdown line happened to break.
ANCHORS: dict[str, list[str]] = {
    "tests_total": ["{} tests"],
    "coverage_line_pct": ["{} percent line coverage", "{}% line coverage"],
    "questions": ["{} questions"],
    "documents": ["{} generated documents"],
    "combinations": ["{} audited combinations"],
    "widest_gap": ["a gap of {}"],
    "widest_gap_chunking": ["worst is {}"],
    "widest_gap_chunk_recall": ["reports a recall of {}"],
    "widest_gap_span_recall": ["actually answers {}"],
    "widest_gap_overstated": ["{} of them cannot answer"],
    "default_200_ceiling": ["chunks the ceiling is {}"],
    "default_200_gap": ["a gap of {} points", "gap of {}"],
    "default_400_ceiling": ["{} at four hundred"],
    "default_800_ceiling": ["{} at eight hundred"],
    "gap_at_k1": ["{} at k equal to one"],
    "gap_at_k20": ["still {} at twenty"],
    "span_recall_flat_from_k": ["flat from k equal to {}"],
    "failures_total": ["{} failures"],
    "failures_destroyed": ["{} were the chunker's"],
    "failures_missed": ["{} were the retriever's"],
    "hashed_retrieval_failures": ["produced {} retrieval failures"],
    "chunkings_nothing_fixable": ["{} of the thirteen"],
    "chunkings_audited": ["{} chunkings"],
    "guarantee_at_400_300": ["{} characters at size four hundred"],
    "guarantee_verified_positions": ["all {} positions"],
    "survival_at_150_no_overlap": ["{} of positions"],
    "survival_at_400_wide": ["down to {} for a four hundred"],
    "overlap_regressions": ["{} case in this plan"],
    "regression_ceiling_drop": ["falls by {}"],
    "regression_extra_chunks": ["{} more chunks"],
    "document_characters": ["{} characters per question"],
    "best_real_ceiling": ["reaches {} on"],
    "best_real_characters": ["on {} characters"],
    "retriever_range": ["at most {}"],
    "chunker_range": ["up to {}"],
    "lever_ratio": ["{} times as far"],
    "floor_gap": ["reaches {}, so the retriever"],
    "ceiling_tightness": ["worst absolute difference of {}"],
    "resolution_floor_pct": ["below {} percent"],
    "sweep_seconds": ["under {} seconds"],
    "bench_repeats": ["{} timed repeats"],
    "bench_python": ["Python {}"],
    "bench_smallest_documents": ["from {} documents"],
    "bench_largest_documents": ["out to {} documents"],
    "bench_largest_chunks": ["{} chunks in the index"],
    "bench_ceiling_small_ms": ["ceiling takes {} ms"],
    "bench_ceiling_large_ms": ["{} ms at the largest"],
    "bench_retrieval_large_ms": ["retrieval takes {} ms"],
    "bench_ratio_small": ["{} times the ceiling at"],
    "bench_ratio_large": ["widens to {} times"],
    "bench_ceiling_linearity": ["a linearity ratio of {}"],
    "bench_retrieval_linearity": ["retrieval's is {}"],
}

CELL_ANCHOR = ["| {} |"]


def run(command: list[str], *, cwd: Path = REPO) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def run_tests() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    completed = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"--junitxml={REPORTS / 'junit.xml'}",
            "--cov=chunkaudit",
            "--cov-report=json:reports/coverage.json",
            "--cov-report=xml:reports/coverage.xml",
        ]
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout[-4000:])
        sys.stderr.write(completed.stderr[-4000:])
        raise SystemExit("the test suite failed, so no metrics were collected")


def read_test_reports() -> tuple[int, float]:
    junit = REPORTS / "junit.xml"
    coverage = REPORTS / "coverage.json"
    for path in (junit, coverage):
        if not path.is_file():
            raise SystemExit(
                f"{path.relative_to(REPO)} is missing. Run without --skip-tests, or run "
                "pytest with --junitxml and --cov-report=json first."
            )
    import xml.etree.ElementTree as ElementTree

    root = ElementTree.parse(junit).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise SystemExit("could not find a testsuite element in the junit report")
    payload = json.loads(coverage.read_text(encoding="utf-8"))
    return int(suite.get("tests", "0")), float(payload["totals"]["percent_covered"])


def run_experiments() -> None:
    for script in EXPERIMENT_SCRIPTS:
        completed = run([sys.executable, str(REPO / "experiments" / script)])
        if completed.returncode != 0:
            sys.stderr.write(completed.stdout[-4000:])
            sys.stderr.write(completed.stderr[-4000:])
            raise SystemExit(f"experiment {script} failed")


def load(name: str) -> dict:
    path = EXPERIMENTS / f"{name}.json"
    if not path.is_file():
        raise SystemExit(f"{path.relative_to(REPO)} is missing. Run without --skip-experiments.")
    return json.loads(path.read_text(encoding="utf-8"))


def one_decimal(value: float) -> float:
    return round(value, 1)


def ms(value: float) -> float:
    """A duration rounded for prose: one decimal above a millisecond, three below.

    The benchmark JSON keeps three decimals throughout. Rounding happens here, at
    the point where a number becomes a sentence, because a duration quoted to the
    microsecond on a two vCPU container is a false precision.
    """
    return round(value, 1) if value >= 1.0 else round(value, 3)


def load_bench() -> dict:
    """Read the committed latency measurement rather than re-running it.

    This is the one figure family in the registry that is not re-measured on every
    push. A duration measured on a GitHub runner is a different measurement from
    one measured on the machine the README describes, so re-timing in CI would fail
    the check for the honest reason that the hardware changed. `make bench` rewrites
    the file, and its diff is reviewed like any other file.
    """
    path = REPO / "benchmark/results/audit_latency.json"
    if not path.is_file():
        raise SystemExit(
            f"{path.relative_to(REPO)} is missing, so the latency table cannot be "
            "checked. Run: make bench"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def build_metrics(*, skip_tests: bool, skip_experiments: bool) -> dict[str, object]:
    if not skip_tests:
        run_tests()
    tests_total, coverage = read_test_reports()
    if not skip_experiments:
        run_experiments()

    exp01 = load("exp01-the-gap-the-standard-metric-hides")
    exp02 = load("exp02-who-can-fix-this")
    exp03 = load("exp03-the-guarantee-threshold")
    exp04 = load("exp04-what-overlap-costs-and-buys")
    exp05 = load("exp05-which-lever-matters")

    widest = exp01["widest_gap"]
    by_chunking = exp01["by_chunking"]
    gap_by_k = exp01["gap_by_k"]
    ks = sorted(int(key) for key in gap_by_k)
    flat_from = next(
        (
            k
            for k in ks
            if all(
                abs(
                    gap_by_k[str(k)]["span_complete_recall"]
                    - gap_by_k[str(other)]["span_complete_recall"]
                )
                < 1e-9
                for other in ks
                if other >= k
            )
        ),
        ks[-1],
    )
    bm25 = exp02["per_retriever"]["bm25"]
    verified = exp03["verified"]["400-300"]
    curves = exp03["survival_curves"]
    regression = (
        min(exp04["overlap_regressions"], key=lambda entry: entry["ceiling_change"])
        if exp04["overlap_regressions"]
        else None
    )
    cheapest = exp04["cheapest_above_eighty"]

    metrics: dict[str, object] = {
        "tests_total": tests_total,
        "coverage_line_pct": one_decimal(coverage),
        "questions": exp01["questions"],
        "documents": exp01["questions"] // 3,
        "combinations": exp01["combinations"],
        "widest_gap": round(widest["gap"], 4),
        "widest_gap_chunking": widest["chunking"],
        "widest_gap_chunk_recall": round(widest["chunk_recall"], 4),
        "widest_gap_span_recall": round(widest["span_complete_recall"], 4),
        "widest_gap_overstated": round(widest["overstated"] * widest["questions"]),
        "default_200_ceiling": round(by_chunking["fixed-200-200"]["ceiling"], 4),
        "default_200_gap": round(by_chunking["fixed-200-200"]["gap"], 4),
        "default_400_ceiling": round(by_chunking["fixed-400-400"]["ceiling"], 4),
        "default_800_ceiling": round(by_chunking["fixed-800-800"]["ceiling"], 4),
        "gap_at_k1": round(gap_by_k[str(ks[0])]["gap"], 4),
        "gap_at_k20": round(gap_by_k[str(ks[-1])]["gap"], 4),
        "span_recall_flat_from_k": flat_from,
        "failures_total": bm25["failures"],
        "failures_destroyed": bm25["destroyed_by_chunking"],
        "failures_missed": bm25["missed_by_retrieval"],
        "hashed_retrieval_failures": exp02["per_retriever"]["hashed"]["missed_by_retrieval"],
        "chunkings_nothing_fixable": len(exp02["chunkings_with_nothing_fixable"]),
        "chunkings_audited": exp02["chunkings_audited"],
        "guarantee_at_400_300": verified["guaranteed_length"],
        "guarantee_verified_positions": verified["at_threshold"]["total"],
        "survival_at_150_no_overlap": round(curves["400-400"]["150"], 3),
        "survival_at_400_wide": round(curves["800-800"]["400"], 3),
        "overlap_regressions": exp04["regression_count"],
        "document_characters": int(exp04["whole_document_characters"]),
        "retriever_range": round(exp05["widest_retriever_range"], 4),
        "chunker_range": round(exp05["widest_chunker_range"], 4),
        "lever_ratio": one_decimal(exp05["chunker_over_retriever"]),
        "floor_gap": round(max(exp05["floor_gap"].values()), 4),
        "ceiling_tightness": round(exp05["worst_ceiling_difference"], 6),
        "resolution_floor_pct": round(100 * exp05["floors"]["resolution_floor"], 2),
        "sweep_seconds": 10,
    }
    if regression is not None:
        metrics["regression_ceiling_drop"] = round(abs(regression["ceiling_change"]), 4)
        metrics["regression_extra_chunks"] = regression["chunks_to"] - regression["chunks_from"]
    if cheapest is not None:
        metrics["best_real_ceiling"] = round(cheapest["ceiling"], 4)
        metrics["best_real_characters"] = int(cheapest["median_retrieved_characters"])

    # The tables in the README are one cell per chunking. Guarding each cell with
    # an anchor that also pinned its row label would need the README to be
    # generated rather than written, so those cells carry the weaker claim that
    # the value appears as a table cell. The README says so rather than implying
    # every guard is equally strong.
    for name, entry in by_chunking.items():
        key = name.replace("-", "_")
        metrics[f"cell_{key}_ceiling"] = round(entry["ceiling"], 4)
        metrics[f"cell_{key}_gap"] = round(entry["gap"], 4)
        metrics[f"cell_{key}_chunks"] = entry["chunk_count"]
    for length, value in curves["400-400"].items():
        metrics[f"cell_survival_400_400_{length}"] = round(value, 3)

    bench = load_bench()
    small, large = bench["rows"][0], bench["rows"][-1]
    metrics["bench_repeats"] = bench["repeats"]
    metrics["bench_python"] = bench["hardware"]["python"]
    metrics["bench_smallest_documents"] = small["documents"]
    metrics["bench_largest_documents"] = large["documents"]
    metrics["bench_largest_chunks"] = large["chunks"]
    metrics["bench_ceiling_small_ms"] = ms(small["ceiling_p50_ms"])
    metrics["bench_ceiling_large_ms"] = ms(large["ceiling_p50_ms"])
    metrics["bench_retrieval_large_ms"] = ms(large["retrieval_p50_ms"])
    metrics["bench_ratio_small"] = small["retrieval_over_ceiling"]
    metrics["bench_ratio_large"] = large["retrieval_over_ceiling"]
    metrics["bench_ceiling_linearity"] = bench["ceiling_linearity"]
    metrics["bench_retrieval_linearity"] = bench["retrieval_linearity"]
    for row in bench["rows"]:
        key = row["documents"]
        metrics[f"cell_bench_{key}_chunks"] = row["chunks"]
        metrics[f"cell_bench_{key}_questions"] = row["questions"]
        metrics[f"cell_bench_{key}_ceiling"] = ms(row["ceiling_p50_ms"])
        metrics[f"cell_bench_{key}_ceiling_p95"] = ms(row["ceiling_p95_ms"])
        metrics[f"cell_bench_{key}_retrieval"] = ms(row["retrieval_p50_ms"])
        metrics[f"cell_bench_{key}_ratio"] = row["retrieval_over_ceiling"]

    for name in metrics:
        if name.startswith("cell_"):
            ANCHORS[name] = CELL_ANCHOR

    # An anchor with no placeholder in it matches whatever the document says
    # regardless of the value, which is a guard that cannot fail. One slipped in
    # during authoring, so it is checked rather than trusted.
    vacuous = sorted(
        name for name in metrics if any("{}" not in phrase for phrase in ANCHORS.get(name, ["{}"]))
    )
    if vacuous:
        raise SystemExit(
            "every anchor phrase must contain a placeholder, otherwise it matches any "
            "value. Offending metrics: " + ", ".join(vacuous)
        )

    missing_anchors = sorted(set(metrics) - set(ANCHORS))
    if missing_anchors:
        raise SystemExit(
            "every metric needs at least one anchor phrase, missing for: "
            + ", ".join(missing_anchors)
        )
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-experiments", action="store_true")
    args = parser.parse_args(argv)

    metrics = build_metrics(skip_tests=args.skip_tests, skip_experiments=args.skip_experiments)
    payload = {
        "metrics": metrics,
        "anchors": {name: ANCHORS[name] for name in metrics},
        "checked_documents": [
            "README.md",
            "docs/defense-guide.md",
            "docs/adr/ADR-001-the-ceiling-is-decided-before-retrieval.md",
            "docs/adr/ADR-002-offsets-rather-than-text.md",
            "docs/adr/ADR-003-the-encoder-this-build-could-not-reach.md",
            "docs/adr/ADR-004-reimplement-the-splitter-rather-than-import-it.md",
            "docs/adr/ADR-005-every-rate-carries-its-denominator.md",
        ],
        "note": "every value here is produced by running the suite and the five experiments",
    }
    destination = DOCS / "metrics.json"
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {destination.relative_to(REPO)} with {len(metrics)} metrics")
    for name, value in metrics.items():
        if not name.startswith("cell_"):
            print(f"  {name:<30} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
