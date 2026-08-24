"""Experiment 1: what the standard retrieval metric reports, and what it means.

The claim the README opens with. A retrieval metric is computed on the chunks the
chunker produced, so a chunk holding part of an answer counts as a hit. This
measures both quantities on the same rankings: the standard chunk level recall,
and the share of questions where some single retrieved chunk holds the answer
whole.

The second half matters more than the first. If the gap closed as k grew, the
answer would be to retrieve more chunks and the finding would be a tuning note.
It does not close, because retrieving more copies of a broken answer does not
assemble one.

Run: python experiments/exp01_the_gap_the_standard_metric_hides.py
"""

from __future__ import annotations

from _shared import COMMON_DEFAULTS, REPO, at, full_sweep, pct, setup, table, write_result

NAME = "exp01-the-gap-the-standard-metric-hides"
RETRIEVER = "bm25"


def main() -> None:
    policy, corpus = setup()
    rows = full_sweep(policy, corpus)
    top_k = policy.retrieval.top_k
    selected = sorted(at(rows, retriever=RETRIEVER, k=top_k), key=lambda row: row.ceiling)

    worst = selected[0]
    widest = max(selected, key=lambda row: row.gap)
    defaults = [row for row in selected if row.chunking in COMMON_DEFAULTS]

    print(f"{NAME}: {len(rows)} audited combinations, {corpus.questions.__len__()} questions")
    print(f"measured with {RETRIEVER} at k={top_k}")
    print()
    print(
        table(
            [
                "chunking",
                "chunks",
                "ceiling",
                "chunk recall",
                "span complete",
                "gap",
                "hits that cannot answer",
            ],
            [
                [
                    row.chunking,
                    row.chunk_count,
                    f"{row.ceiling:.4f}",
                    f"{row.chunk_recall:.4f}",
                    f"{row.span_complete_recall:.4f}",
                    f"{row.gap:.4f}",
                    f"{round(row.overstated * row.questions)} of {row.questions}",
                ]
                for row in selected
            ],
        )
    )
    print()
    print(
        f"the widest gap is {widest.gap:.4f} on {widest.chunking}, where the standard metric "
        f"reports {widest.chunk_recall:.4f} and "
        f"{round(widest.overstated * widest.questions)} of {widest.questions} of its hits "
        "cannot answer on their own"
    )

    k_rows = []
    for k in policy.retrieval.sweep_k:
        row = next(
            row for row in at(rows, retriever=RETRIEVER, k=k) if row.chunking == worst.chunking
        )
        k_rows.append(
            [
                k,
                f"{row.chunk_recall:.4f}",
                f"{row.span_complete_recall:.4f}",
                f"{row.assembled_recall:.4f}",
                f"{row.gap:.4f}",
            ]
        )
    print()
    print(f"the same chunking, {worst.chunking}, as k grows")
    print(table(["k", "chunk recall", "span complete", "assembled", "gap"], k_rows))
    first = k_rows[0]
    last = k_rows[-1]
    print()
    print(
        f"the gap goes from {first[4]} at k={first[0]} to {last[4]} at k={last[0]}. Retrieving "
        "more copies of a broken answer does not assemble one"
    )

    payload = {
        "experiment": NAME,
        "question": "how far apart are the standard metric and the one a reader assumes",
        "retriever": RETRIEVER,
        "top_k": top_k,
        "questions": len(corpus.questions),
        "combinations": len(rows),
        "by_chunking": {row.chunking: row.as_dict() for row in selected},
        "widest_gap": widest.as_dict(),
        "worst_ceiling": worst.as_dict(),
        "common_defaults": {row.chunking: row.as_dict() for row in defaults},
        "gap_by_k": {
            str(entry[0]): {
                "chunk_recall": float(entry[1]),
                "span_complete_recall": float(entry[2]),
                "assembled_recall": float(entry[3]),
                "gap": float(entry[4]),
            }
            for entry in k_rows
        },
        "boundary": (
            "the corpus is generated, so these rates are properties of it. What transfers "
            "is that the two metrics differ and that the difference is a function of the "
            "chunker rather than of the retriever"
        ),
    }
    print()
    print(f"wrote {write_result(NAME, payload).relative_to(REPO)}")
    print(
        f"share of the shipped defaults whose gap exceeds the policy threshold: "
        f"{pct(sum(1 for row in defaults if row.gap >= policy.audit.material_gap) / len(defaults))}"
    )


if __name__ == "__main__":
    main()
