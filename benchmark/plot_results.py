"""Draw the latency chart from benchmark/results/audit_latency.json.

Nothing here computes a timing. It reads the JSON the benchmark wrote and draws
it, so the chart and the table in the README are two renderings of one
measurement rather than two numbers that have to be kept in step by hand.

Matplotlib lives in the evidence extra. A consumer auditing their own chunking
should not install a plotting library to get a ceiling.

Usage:
    python benchmark/plot_results.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "benchmark/results/audit_latency.json"
DEFAULT_OUT = REPO / "docs/charts/audit-latency.png"

INK = "#1c1c1a"
MUTED = "#6b6a66"


def draw(payload: dict, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = payload["rows"]
    documents = [row["documents"] for row in rows]

    figure, axes = plt.subplots(figsize=(9.0, 4.6), dpi=150)
    figure.patch.set_facecolor("white")
    axes.set_facecolor("white")

    axes.plot(
        documents,
        [row["retrieval_p50_ms"] for row in rows],
        marker="o",
        markersize=4,
        linewidth=1.8,
        color="#e34948",
        label=f"{payload['retriever']} retrieval and scoring, p50",
    )
    axes.plot(
        documents,
        [row["retrieval_p95_ms"] for row in rows],
        marker="",
        linewidth=1.0,
        linestyle="--",
        color="#e34948",
        alpha=0.55,
        label=f"{payload['retriever']} retrieval and scoring, p95",
    )
    axes.plot(
        documents,
        [row["ceiling_p50_ms"] for row in rows],
        marker="s",
        markersize=4,
        linewidth=1.8,
        color="#1baf7a",
        label="chunk and compute the ceiling, p50",
    )
    axes.plot(
        documents,
        [row["ceiling_p95_ms"] for row in rows],
        marker="",
        linewidth=1.0,
        linestyle="--",
        color="#1baf7a",
        alpha=0.55,
        label="chunk and compute the ceiling, p95",
    )

    axes.set_xscale("log")
    axes.set_yscale("log")
    axes.set_xlabel("documents in the corpus", color=INK)
    axes.set_ylabel("one pass over the whole corpus, milliseconds", color=INK)
    axes.set_title(
        "The ceiling is decided before retrieval, and costs a fraction of it"
        f"  (chunking {payload['chunking']['strategy']}"
        f" {payload['chunking']['size']}/{payload['chunking']['stride']},"
        f" k={payload['k']}, {payload['repeats']} repeats)",
        color=INK,
        fontsize=10,
        loc="left",
    )
    axes.set_xticks(documents)
    axes.set_xticklabels([f"{value:,}" for value in documents], color=INK, fontsize=8)
    axes.tick_params(colors=INK, labelsize=8)
    axes.grid(True, which="major", linewidth=0.4, color="#d8d7d3")
    axes.grid(True, which="minor", linewidth=0.2, color="#ebeae7")
    for spine in ("top", "right"):
        axes.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        axes.spines[spine].set_color(MUTED)

    last = rows[-1]
    axes.annotate(
        f"{last['retrieval_over_ceiling']:.0f}x apart at {last['documents']:,} documents",
        xy=(last["documents"], last["retrieval_p50_ms"]),
        xytext=(last["documents"] * 0.20, last["retrieval_p50_ms"] * 0.09),
        color=INK,
        fontsize=8,
        arrowprops={"arrowstyle": "->", "color": MUTED, "linewidth": 0.8},
    )
    axes.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper left")
    figure.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out, facecolor="white")
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if not args.results.is_file():
        raise SystemExit(f"no benchmark results at {args.results}, run: make bench")
    draw(json.loads(args.results.read_text(encoding="utf-8")), args.out)
    print(f"wrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
