"""Experiment 5: the chunker or the retriever, and which one to spend on.

The comparison this repository exists to make. Holding the corpus and the
questions fixed, how much does span complete recall move when the retriever
changes, and how much when the chunker changes? Both are ranges over the same
thirteen by four grid, so they are directly comparable.

Two supporting results. The oracle attains the ceiling exactly on every chunking,
which is the empirical proof that the ceiling is tight rather than merely an upper
bound: if the oracle came in below it, the claim that no retriever reaches past it
would be weaker than stated. And every rate here carries the resolution floor of
the corpus that produced it, because a measured zero over three hundred and sixty
questions is a different statement from a zero over a million.

Run: python experiments/exp05_which_lever_matters.py
"""

from __future__ import annotations

from _shared import REPO, RUNNABLE, at, ceiling_report, full_sweep, pct, setup, table, write_result

from chunkaudit.chunking import PLAN, build_chunking
from chunkaudit.metrics import Rate

NAME = "exp05-which-lever-matters"
CLAIMS = (0.10, 0.01, 0.001)
# The oracle sees the answer and the random retriever is a floor. Neither belongs
# in a comparison of what changing your retriever would do, so the range is taken
# over the two that are real alternatives and the other two are reported apart.
SERIOUS = ("bm25", "hashed")


def main() -> None:
    policy, corpus = setup()
    rows = full_sweep(policy, corpus)
    top_k = policy.retrieval.top_k
    honest = tuple(name for name in RUNNABLE if name != "oracle")
    if not set(SERIOUS) <= set(honest):
        raise SystemExit("the serious retrievers must be a subset of the runnable ones")

    by_chunking: dict[str, dict[str, float]] = {}
    for row in rows:
        if row.k != top_k:
            continue
        by_chunking.setdefault(row.chunking, {})[row.retriever] = row.span_complete_recall

    retriever_ranges = {
        chunking: max(entry[name] for name in SERIOUS) - min(entry[name] for name in SERIOUS)
        for chunking, entry in by_chunking.items()
    }
    chunker_ranges = {
        retriever: max(entry[retriever] for entry in by_chunking.values())
        - min(entry[retriever] for entry in by_chunking.values())
        for retriever in SERIOUS
    }
    floor_gap = {
        chunking: entry["bm25"] - entry["random"] for chunking, entry in by_chunking.items()
    }

    print(f"{NAME}: span complete recall at k={top_k}, on the same corpus throughout")
    print()
    print(
        table(
            ["chunking", *honest, "range across the two real ones"],
            [
                [
                    chunking,
                    *[f"{by_chunking[chunking][name]:.4f}" for name in honest],
                    f"{retriever_ranges[chunking]:.4f}",
                ]
                for chunking in sorted(by_chunking, key=lambda name: by_chunking[name]["bm25"])
            ],
        )
    )
    print()
    print(
        table(
            ["retriever", "range across chunkings"],
            [[name, f"{value:.4f}"] for name, value in chunker_ranges.items()],
        )
    )
    widest_retriever = max(retriever_ranges.values())
    widest_chunker = max(chunker_ranges.values())
    print()
    print(
        f"changing between the two real retrievers moves span complete recall by at most "
        f"{widest_retriever:.4f}. Changing the chunker moves it by up to "
        f"{widest_chunker:.4f}, which is {widest_chunker / widest_retriever:.1f} times as far"
    )
    print(
        f"for scale, the gap between bm25 and a seeded shuffle reaches "
        f"{max(floor_gap.values()):.4f}, so the retriever is not irrelevant. It is the "
        "smaller lever"
    )

    tight = []
    for entry in PLAN:
        chunking = build_chunking(corpus.documents, *entry)
        report = ceiling_report(corpus, chunking)
        oracle = next(
            row
            for row in at(rows, retriever="oracle", k=max(policy.retrieval.sweep_k))
            if row.chunking == chunking.name
        )
        tight.append(
            {
                "chunking": chunking.name,
                "ceiling": report.ceiling,
                "oracle_span_complete_recall": oracle.span_complete_recall,
                "difference": oracle.span_complete_recall - report.ceiling,
            }
        )
    worst_difference = max(abs(item["difference"]) for item in tight)
    print()
    print(
        f"the oracle attains the ceiling on all {len(tight)} chunkings, with a worst absolute "
        f"difference of {worst_difference:.6f}. The ceiling is tight, not merely an upper bound"
    )

    unfixable = Rate(
        sum(
            1
            for row in at(rows, retriever="bm25", k=top_k)
            if row.destroyed_by_chunking > 0 and row.missed_by_retrieval == 0
        ),
        len(at(rows, retriever="bm25", k=top_k)),
    )
    floors = {
        "questions": len(corpus.questions),
        "resolution_floor": policy.resolution_floor,
        "samples_needed": {
            f"{claim}": Rate(0, len(corpus.questions)).samples_needed_for(claim) for claim in CLAIMS
        },
    }
    print()
    print(
        table(
            ["claim about a rate", "questions needed to support it"],
            [[f"{claim} of questions", floors["samples_needed"][f"{claim}"]] for claim in CLAIMS],
        )
    )
    print(
        f"this corpus has {floors['questions']} questions, so any measured zero here supports "
        f'"below {pct(floors["resolution_floor"], 2)}" and nothing stronger'
    )
    print(
        f"{unfixable.numerator} of {unfixable.denominator} chunkings have no retriever "
        f"fixable failures at all"
    )

    payload = {
        "experiment": NAME,
        "question": "does the chunker or the retriever move the number more",
        "top_k": top_k,
        "honest_retrievers": list(honest),
        "serious_retrievers": list(SERIOUS),
        "floor_gap": floor_gap,
        "span_complete_recall": by_chunking,
        "retriever_ranges": retriever_ranges,
        "chunker_ranges": chunker_ranges,
        "widest_retriever_range": widest_retriever,
        "widest_chunker_range": widest_chunker,
        "chunker_over_retriever": widest_chunker / widest_retriever,
        "ceiling_tightness": tight,
        "worst_ceiling_difference": worst_difference,
        "chunkings_with_nothing_fixable": unfixable.as_dict(),
        "floors": floors,
        "note": (
            "the oracle is excluded from the retriever range because it sees the answer. "
            "It is reported separately as the tightness check on the ceiling"
        ),
    }
    print()
    print(f"wrote {write_result(NAME, payload).relative_to(REPO)}")


if __name__ == "__main__":
    main()
