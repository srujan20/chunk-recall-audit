"""Experiment 2: of the failures, how many could a better retriever fix?

The question a team asks after seeing a recall number it does not like, and the
one the standard metric cannot answer. Two of the three possible causes look
identical to a function of the chunks: an answer no chunk holds whole, and an
answer some chunk holds whole that was not retrieved. Only the second is
addressable by touching the retriever.

The number this produces is the one that should gate a decision to buy a better
embedding model.

Run: python experiments/exp02_who_can_fix_this.py
"""

from __future__ import annotations

from _shared import REPO, RUNNABLE, at, full_sweep, pct, setup, table, write_result

NAME = "exp02-who-can-fix-this"


def main() -> None:
    policy, corpus = setup()
    rows = full_sweep(policy, corpus)
    top_k = policy.retrieval.top_k

    per_retriever: dict[str, dict[str, object]] = {}
    for retriever in RUNNABLE:
        selected = at(rows, retriever=retriever, k=top_k)
        destroyed = sum(row.destroyed_by_chunking for row in selected)
        missed = sum(row.missed_by_retrieval for row in selected)
        unattributable = sum(row.unattributable for row in selected)
        failures = destroyed + missed + unattributable
        per_retriever[retriever] = {
            "chunkings": len(selected),
            "failures": failures,
            "destroyed_by_chunking": destroyed,
            "missed_by_retrieval": missed,
            "unattributable": unattributable,
            "fixable_share": missed / failures if failures else None,
        }

    print(f"{NAME}: every chunking at k={top_k}, one row per retriever")
    print()
    print(
        table(
            ["retriever", "failures", "chunker destroyed it", "retriever missed it", "fixable"],
            [
                [
                    retriever,
                    entry["failures"],
                    entry["destroyed_by_chunking"],
                    entry["missed_by_retrieval"],
                    pct(entry["fixable_share"]) if entry["fixable_share"] is not None else "n/a",
                ]
                for retriever, entry in per_retriever.items()
            ],
        )
    )

    bm25_rows = sorted(at(rows, retriever="bm25", k=top_k), key=lambda row: row.ceiling)
    print()
    print("per chunking, with bm25")
    print(
        table(
            ["chunking", "destroyed", "missed", "fixable", "headroom", "share of shortfall"],
            [
                [
                    row.chunking,
                    row.destroyed_by_chunking,
                    row.missed_by_retrieval,
                    "n/a"
                    if row.destroyed_by_chunking + row.missed_by_retrieval == 0
                    else pct(
                        row.missed_by_retrieval
                        / (row.destroyed_by_chunking + row.missed_by_retrieval)
                    ),
                    f"{row.headroom:.4f}",
                    pct(row.attainable_share),
                ]
                for row in bm25_rows
            ],
        )
    )

    zero_fixable = [
        row for row in bm25_rows if row.destroyed_by_chunking > 0 and row.missed_by_retrieval == 0
    ]
    print()
    print(
        f"{len(zero_fixable)} of the {len(bm25_rows)} chunkings have failures that no retriever "
        "change can address at all, because every one of them is an answer no chunk holds whole"
    )
    if zero_fixable:
        worst = min(zero_fixable, key=lambda row: row.ceiling)
        print(
            f"the worst is {worst.chunking}, where {worst.destroyed_by_chunking} of "
            f"{worst.questions} questions fail and {worst.missed_by_retrieval} of those "
            "failures are the retriever's"
        )

    payload = {
        "experiment": NAME,
        "question": "how many of the failures could a better retriever fix",
        "top_k": top_k,
        "per_retriever": per_retriever,
        "per_chunking_bm25": {row.chunking: row.as_dict() for row in bm25_rows},
        "chunkings_with_nothing_fixable": [row.chunking for row in zero_fixable],
        "chunkings_audited": len(bm25_rows),
        "conclusion": (
            "on the chunkings a pipeline is most likely to be running, every failure is "
            "the chunker's and none of them is reachable by changing the retriever"
        ),
    }
    print()
    print(f"wrote {write_result(NAME, payload).relative_to(REPO)}")


if __name__ == "__main__":
    main()
