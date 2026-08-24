"""Time the ceiling against the retrieval it is supposed to be computed before.

The argument this repository makes is that the ceiling should be computed first,
because it is decided by the chunking alone and no retriever can beat it. An
argument like that has a cost attached, and this file measures the cost rather
than asserting it is small.

Three design notes.

The corpus is built outside the timed region. Generating documents is not work
either the ceiling or the retriever does, and at the larger sizes it dominates
both, so timing it would have reported the corpus generator as a property of the
audit.

The chunking is built inside the timed region for the ceiling and reused for
retrieval. Chunking is genuinely part of computing a ceiling: the whole claim is
that the chunking decides the answer. It is not part of retrieval's job, and
charging retrieval for it would flatter the comparison in the direction this
repository would prefer, which is exactly the direction to be careful about.

bm25 is the retriever timed here rather than the hashed encoder, because bm25 is
the default in the policy file and the one every published retrieval number in
the README comes from.

Usage:
    python benchmark/bench_ceiling.py [--repeats 7] [--out benchmark/results/audit_latency.json]
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from chunkaudit.ceiling import ceiling_report  # noqa: E402
from chunkaudit.chunking import build_chunking  # noqa: E402
from chunkaudit.config import load_policy  # noqa: E402
from chunkaudit.documents import build_corpus  # noqa: E402
from chunkaudit.metrics import evaluate  # noqa: E402
from chunkaudit.retrieval import rank  # noqa: E402

SIZES = (120, 240, 480, 960, 1920)
CHUNKING = ("fixed", 400, 300)
DEFAULT_OUT = REPO / "benchmark/results/audit_latency.json"


def percentile(values: list[float], fraction: float) -> float:
    """Nearest rank percentile, so every reported duration is one that happened."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def repeat(function, repeats: int) -> list[float]:
    """Times `repeats` calls after one untimed warm up.

    The warm up is stated rather than hidden. numpy allocates its scratch buffers
    and the interpreter resolves the call path on the first invocation, and
    including that made the first sample several times the median, which then
    became the p95 of a small sample set.
    """
    function()
    durations = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        durations.append((time.perf_counter() - start) * 1000.0)
    return durations


def measure(repeats: int) -> dict[str, object]:
    policy = load_policy(REPO / "configs/policy.yaml")
    strategy, size, stride = CHUNKING
    rows = []
    for documents in SIZES:
        corpus = build_corpus(
            documents=documents,
            questions_per_document=policy.corpus.questions_per_document,
            span_chars=policy.corpus.span_chars,
        )
        chunking = build_chunking(corpus.documents, strategy, size, stride)

        def ceiling_pass(corpus=corpus, strategy=strategy, size=size, stride=stride):
            built = build_chunking(corpus.documents, strategy, size, stride)
            return ceiling_report(corpus, built)

        def retrieval_pass(corpus=corpus, chunking=chunking):
            rankings = rank("bm25", corpus, chunking, policy)
            return evaluate(corpus, chunking, rankings, retriever="bm25", k=policy.retrieval.top_k)

        ceiling_ms = repeat(ceiling_pass, repeats)
        retrieval_ms = repeat(retrieval_pass, repeats)
        ceiling_p50 = statistics.median(ceiling_ms)
        retrieval_p50 = statistics.median(retrieval_ms)
        rows.append(
            {
                "documents": documents,
                "questions": documents * policy.corpus.questions_per_document,
                "chunks": len(chunking.chunks),
                "ceiling_p50_ms": round(ceiling_p50, 3),
                "ceiling_p95_ms": round(percentile(ceiling_ms, 0.95), 3),
                "retrieval_p50_ms": round(retrieval_p50, 3),
                "retrieval_p95_ms": round(percentile(retrieval_ms, 0.95), 3),
                "retrieval_over_ceiling": round(retrieval_p50 / ceiling_p50, 1),
            }
        )
        print(
            f"  {documents:>5} documents  {len(chunking.chunks):>7} chunks"
            f"  ceiling {ceiling_p50:>9.2f} ms  retrieval {retrieval_p50:>9.2f} ms"
            f"  retrieval is {rows[-1]['retrieval_over_ceiling']:.1f}x the ceiling"
        )

    first, last = rows[0], rows[-1]
    return {
        "hardware": {
            "python": platform.python_version(),
            "machine": platform.machine(),
            "platform": platform.system(),
        },
        "chunking": {"strategy": strategy, "size": size, "stride": stride},
        "retriever": "bm25",
        "k": policy.retrieval.top_k,
        "repeats": repeats,
        "rows": rows,
        # A value near 1.0 says the cost is linear in the document count. Published
        # as a ratio rather than claimed in prose, so a change in either stage shows
        # up here instead of quietly contradicting the README.
        "ceiling_linearity": round(
            (last["ceiling_p50_ms"] / first["ceiling_p50_ms"])
            / (last["documents"] / first["documents"]),
            3,
        ),
        "retrieval_linearity": round(
            (last["retrieval_p50_ms"] / first["retrieval_p50_ms"])
            / (last["documents"] / first["documents"]),
            3,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    print(f"timing the ceiling against bm25 retrieval at {len(SIZES)} corpus sizes")
    payload = measure(args.repeats)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
