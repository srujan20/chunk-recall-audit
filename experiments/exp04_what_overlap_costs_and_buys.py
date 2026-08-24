"""Experiment 4: what overlap costs, what it buys, and when it does neither.

Overlap is the knob everybody turns. It costs index size linearly, because a
chunking that advances by less produces more chunks, and every chunk is a row to
store and, in a real pipeline, a vector to compute. What it buys is a higher
guarantee threshold, which is a real and exact gain.

What it does not do is monotonically raise the ceiling. Window starts are
multiples of the stride, so a smaller stride is not a superset of a larger one:
with a stride of 800 the starts are 0 and 800, and with 600 they are 0, 600 and
1200. An answer needing a window that starts between 710 and 810 is kept by the
first and destroyed by the second. Above the guarantee threshold, overlap moves
the lottery rather than winning it, and this experiment reports every case in the
plan where adding overlap made the ceiling worse.

Run: python experiments/exp04_what_overlap_costs_and_buys.py
"""

from __future__ import annotations

from _shared import REPO, at, full_sweep, pct, setup, table, write_result

NAME = "exp04-what-overlap-costs-and-buys"
FAMILIES = {
    "fixed-200": ("fixed-200-200", "fixed-200-150"),
    "fixed-400": ("fixed-400-400", "fixed-400-300", "fixed-400-200"),
    "fixed-800": ("fixed-800-800", "fixed-800-600"),
    "recursive": ("recursive-400-300", "recursive-800-600"),
}


def main() -> None:
    policy, corpus = setup()
    rows = full_sweep(policy, corpus)
    top_k = policy.retrieval.top_k
    lookup = {row.chunking: row for row in at(rows, retriever="bm25", k=top_k)}

    baseline = lookup["fixed-400-400"]
    trade = []
    for row in lookup.values():
        trade.append(
            [
                row.chunking,
                row.overlap,
                row.chunk_count,
                pct(row.chunk_count / baseline.chunk_count - 1.0, 0),
                "n/a" if row.guaranteed_length is None else row.guaranteed_length,
                f"{row.ceiling:.4f}",
            ]
        )
    trade.sort(key=lambda entry: entry[2])

    print(f"{NAME}: what each chunking stores, and what it keeps")
    print()
    print(
        table(
            [
                "chunking",
                "overlap",
                "chunks",
                "index vs fixed-400-400",
                "guaranteed",
                "ceiling",
            ],
            trade,
        )
    )

    regressions = []
    for family, names in FAMILIES.items():
        ordered = [lookup[name] for name in names if name in lookup]
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current.ceiling < previous.ceiling:
                regressions.append(
                    {
                        "family": family,
                        "from": previous.chunking,
                        "to": current.chunking,
                        "overlap_from": previous.overlap,
                        "overlap_to": current.overlap,
                        "ceiling_from": previous.ceiling,
                        "ceiling_to": current.ceiling,
                        "ceiling_change": current.ceiling - previous.ceiling,
                        "chunks_from": previous.chunk_count,
                        "chunks_to": current.chunk_count,
                    }
                )

    print()
    if regressions:
        print("cases in this plan where adding overlap lowered the ceiling")
        print(
            table(
                ["from", "to", "overlap", "ceiling", "extra chunks stored"],
                [
                    [
                        entry["from"],
                        entry["to"],
                        f"{entry['overlap_from']} to {entry['overlap_to']}",
                        f"{entry['ceiling_from']:.4f} to {entry['ceiling_to']:.4f}",
                        entry["chunks_to"] - entry["chunks_from"],
                    ]
                    for entry in regressions
                ],
            )
        )
        worst = min(regressions, key=lambda entry: entry["ceiling_change"])
        print()
        print(
            f"the worst is {worst['from']} to {worst['to']}: the ceiling falls by "
            f"{abs(worst['ceiling_change']):.4f} while the index grows by "
            f"{worst['chunks_to'] - worst['chunks_from']} chunks. Overlap bought nothing "
            "and cost storage"
        )
    else:
        print("no case in this plan lowered the ceiling when overlap was added")

    # The other price, and the reason a whole document chunk is not the obvious
    # answer despite a perfect ceiling: it ships the entire document for every
    # question. What that costs downstream is outside this repository, and saying
    # so is more useful than leaving a table in which one row dominates every
    # other for reasons the table cannot show.
    context = sorted(lookup.values(), key=lambda item: item.median_retrieved_characters)
    print()
    print("the other price: characters handed to whatever consumes the results, at this k")
    print(
        table(
            ["chunking", "ceiling", "median characters retrieved", "per point of ceiling"],
            [
                [
                    row.chunking,
                    f"{row.ceiling:.4f}",
                    int(row.median_retrieved_characters),
                    int(row.median_retrieved_characters / row.ceiling),
                ]
                for row in context
            ],
        )
    )
    whole = lookup["document"]
    cheapest_good = min(
        (row for row in lookup.values() if row.chunking != "document" and row.ceiling >= 0.80),
        key=lambda row: row.median_retrieved_characters,
        default=None,
    )
    print()
    if cheapest_good is not None:
        print(
            f"the whole document chunker has a perfect ceiling and ships "
            f"{int(whole.median_retrieved_characters)} characters per question. "
            f"{cheapest_good.chunking} reaches {cheapest_good.ceiling:.4f} on "
            f"{int(cheapest_good.median_retrieved_characters)}. What the extra characters "
            "cost downstream is not measured here, and the README says so"
        )

    payload = {
        "experiment": NAME,
        "question": "what does overlap cost, what does it buy, and when does it buy nothing",
        "top_k": top_k,
        "baseline": baseline.chunking,
        "by_chunking": {row.chunking: row.as_dict() for row in lookup.values()},
        "overlap_regressions": regressions,
        "regression_count": len(regressions),
        "context_cost": {
            row.chunking: {
                "ceiling": row.ceiling,
                "median_retrieved_characters": row.median_retrieved_characters,
            }
            for row in context
        },
        "whole_document_characters": whole.median_retrieved_characters,
        "cheapest_above_eighty": None if cheapest_good is None else cheapest_good.as_dict(),
        "mechanism": (
            "window starts are multiples of the stride, so a smaller stride is not a "
            "superset of a larger one. Above the guarantee threshold, overlap moves which "
            "positions survive rather than increasing how many do"
        ),
    }
    print()
    print(f"wrote {write_result(NAME, payload).relative_to(REPO)}")


if __name__ == "__main__":
    main()
