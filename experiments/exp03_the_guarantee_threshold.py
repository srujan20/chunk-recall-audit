"""Experiment 3: the overlap is a guarantee threshold, not a tuning knob.

For fixed character windows of size S advanced by stride T, an answer of length L
sits inside some window wherever it falls if and only if L is at most S minus T
plus one, which is the overlap plus one. That is arithmetic rather than a
measurement, and this experiment checks it by exhaustion: every start position of
every length either side of the threshold, on a synthetic document, with no
retrieval involved.

Above the threshold, survival depends on where the answer happens to sit. The
second half measures that survival rate as a function of length, which is the
curve a person sizing a chunker actually needs and which no chunking library
prints.

Run: python experiments/exp03_the_guarantee_threshold.py
"""

from __future__ import annotations

from _shared import REPO, setup, table, write_result

from chunkaudit.ceiling import containment_for, guaranteed_length
from chunkaudit.chunking import Chunk, Chunking, chunk_document
from chunkaudit.documents import Document, Question, Span

NAME = "exp03-the-guarantee-threshold"
DOCUMENT_LENGTH = 4000
CONFIGURATIONS = ((400, 400), (400, 300), (400, 200), (800, 800), (800, 600))
LENGTHS = (10, 25, 50, 101, 102, 150, 201, 250, 400, 600)


def survival(size: int, stride: int, length: int) -> tuple[int, int]:
    """Contained and total, over every start position on a synthetic document."""
    document = Document(
        doc_id="d", text="x" * DOCUMENT_LENGTH, sentences=(Span(0, DOCUMENT_LENGTH),)
    )
    spans = chunk_document(document, "fixed", size, stride)
    chunks = tuple(Chunk("d", index, span) for index, span in enumerate(spans))
    contained = 0
    total = 0
    for start in range(DOCUMENT_LENGTH - length):
        answer = Span(start, start + length)
        question = Question(qid="q", text="?", doc_id="d", answer=answer, band=length)
        total += 1
        if containment_for(question, chunks, answer=answer).contained:
            contained += 1
    return contained, total


def main() -> None:
    policy, corpus = setup()
    del policy, corpus

    guarantees = {}
    verified = {}
    for size, stride in CONFIGURATIONS:
        chunking = Chunking(strategy="fixed", size=size, stride=stride, chunks=())
        threshold = guaranteed_length(chunking)
        guarantees[f"{size}-{stride}"] = threshold
        at_threshold = survival(size, stride, threshold)
        above = survival(size, stride, threshold + 1)
        verified[f"{size}-{stride}"] = {
            "overlap": chunking.overlap,
            "guaranteed_length": threshold,
            "at_threshold": {"contained": at_threshold[0], "total": at_threshold[1]},
            "one_above": {"contained": above[0], "total": above[1]},
        }

    print(
        f"{NAME}: the closed form checked by exhaustion on a {DOCUMENT_LENGTH} character document"
    )
    print()
    print(
        table(
            ["size", "stride", "overlap", "guaranteed", "at that length", "one longer"],
            [
                [
                    size,
                    stride,
                    entry["overlap"],
                    entry["guaranteed_length"],
                    f"{entry['at_threshold']['contained']} of {entry['at_threshold']['total']}",
                    f"{entry['one_above']['contained']} of {entry['one_above']['total']}",
                ]
                for (size, stride), entry in zip(CONFIGURATIONS, verified.values(), strict=True)
            ],
        )
    )
    print()
    print(
        "every answer at or below the threshold survives at every position, and one "
        "character longer is already a lottery"
    )

    curves: dict[str, dict[str, float]] = {}
    for size, stride in CONFIGURATIONS:
        name = f"{size}-{stride}"
        curves[name] = {}
        for length in LENGTHS:
            if length >= size:
                continue
            contained, total = survival(size, stride, length)
            curves[name][str(length)] = contained / total
    print()
    header = ["answer length", *[f"{size}-{stride}" for size, stride in CONFIGURATIONS]]
    body = []
    for length in LENGTHS:
        row: list[object] = [length]
        for size, stride in CONFIGURATIONS:
            value = curves[f"{size}-{stride}"].get(str(length))
            row.append("n/a" if value is None else f"{value:.3f}")
        body.append(row)
    print(table(header, body))
    print()
    print(
        "the column for a chunking with no overlap is not zero above its threshold: an "
        "answer still survives whenever it happens to sit inside one window, and that "
        "share falls linearly with the answer's length"
    )

    payload = {
        "experiment": NAME,
        "question": "what does the overlap actually guarantee",
        "document_length": DOCUMENT_LENGTH,
        "closed_form": (
            "an answer of length L survives at every position if and only if "
            "L is at most size minus stride plus one"
        ),
        "verified": verified,
        "survival_curves": curves,
        "lengths": list(LENGTHS),
        "boundary": (
            "this is arithmetic on a synthetic document and involves no retrieval and no "
            "corpus. It transfers exactly to any uniform character windowing, and not at "
            "all to a splitter whose windows are not uniform, which is why "
            "guaranteed_length returns None for those"
        ),
    }
    print()
    print(f"wrote {write_result(NAME, payload).relative_to(REPO)}")


if __name__ == "__main__":
    main()
