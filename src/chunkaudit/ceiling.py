"""The containment ceiling: what no retriever can exceed, decided before retrieval.

This module is the reason the repository exists, and it contains no model, no
similarity and no ranking. Given a chunking and a question whose answer is a
character span, whether any chunk holds that span whole is an interval question
with an exact answer. Aggregated over the questions, that is the highest span
complete recall any retriever can ever reach on that chunking.

It bounds every retriever. Not the ones tested here: every retriever. A perfect
oracle cannot retrieve a chunk that does not exist, so a team improving its
embedding model above this number is spending effort on headroom that is not
there. That is the actionable finding, and it is available before a single vector
is computed.

The closed form is worth stating because it is short. For fixed windows of size S
advanced by stride T, an answer of length L is contained in some window at every
possible position if and only if L is at most S minus T plus one, which is the
overlap plus one. Above that threshold survival depends on where the answer
happens to sit, and this module computes the exact rate rather than the bound.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chunking import Chunk, Chunking
from .documents import Corpus, Question, Span
from .errors import UnanswerableError


@dataclass(frozen=True)
class Containment:
    """Whether one question's answer survived a chunking, and by how narrow a margin."""

    qid: str
    answer_length: int
    band: int
    contained: bool
    containing_chunks: int
    covering_chunks: int
    best_single_overlap: int

    @property
    def best_single_share(self) -> float:
        """The largest share of the answer any one chunk holds.

        Reported because the binary answer hides the difference between an answer
        split down the middle and one missing three characters, and a reader
        deciding whether to care needs that.
        """
        return self.best_single_overlap / self.answer_length

    @property
    def assemblable(self) -> bool:
        """True when the chunks jointly cover the answer, even if none holds it whole.

        Always true for a chunking that covers the document, which every strategy
        here does. Kept explicit because it is the assumption behind the common
        defence that a generator can stitch the pieces back together, and that
        defence is only available when every piece is retrieved.
        """
        return self.covering_chunks > 0


def guaranteed_length(chunking: Chunking) -> int | None:
    """The longest answer this chunking is guaranteed to preserve, at any position.

    Returns None for strategies whose windows are not uniform in characters, where
    the guarantee is not a single number and the measured rate is the only honest
    statement. That distinction is the point of returning None rather than zero.
    """
    if chunking.strategy != "fixed":
        return None
    return max(0, chunking.size - chunking.stride + 1)


def containment_for(question: Question, chunks: tuple[Chunk, ...], *, answer: Span) -> Containment:
    """Exact containment facts for one question against one document's chunks."""
    if not chunks:
        raise UnanswerableError(
            f"question {question.qid} has no chunks for document {question.doc_id}"
        )
    containing = 0
    covering = 0
    best = 0
    for chunk in chunks:
        overlap = chunk.span.intersection(answer)
        if overlap:
            covering += 1
            best = max(best, overlap)
        if chunk.span.contains(answer):
            containing += 1
    return Containment(
        qid=question.qid,
        answer_length=answer.length,
        band=question.band,
        contained=containing > 0,
        containing_chunks=containing,
        covering_chunks=covering,
        best_single_overlap=best,
    )


@dataclass(frozen=True)
class CeilingReport:
    """The ceiling for one chunking, with the parts a reader needs to act on it."""

    chunking: str
    strategy: str
    size: int
    stride: int
    overlap: int
    chunk_count: int
    guaranteed_length: int | None
    containments: tuple[Containment, ...]

    @property
    def questions(self) -> int:
        return len(self.containments)

    @property
    def ceiling(self) -> float:
        """Share of questions for which a single chunk holds the whole answer."""
        return sum(1 for item in self.containments if item.contained) / self.questions

    @property
    def destroyed(self) -> int:
        return sum(1 for item in self.containments if not item.contained)

    @property
    def resolution_floor(self) -> float:
        return 1.0 / self.questions

    def ceiling_by_band(self) -> dict[int, tuple[int, int]]:
        """Contained and total, per answer length band.

        A single ceiling averages over answer lengths, and the whole finding is
        that the damage is a function of length. Averaging it away would be the
        comfortable way to make the number look better.
        """
        counts: dict[int, list[int]] = {}
        for item in self.containments:
            entry = counts.setdefault(item.band, [0, 0])
            entry[1] += 1
            if item.contained:
                entry[0] += 1
        return {band: (values[0], values[1]) for band, values in sorted(counts.items())}

    def as_dict(self) -> dict[str, object]:
        return {
            "chunking": self.chunking,
            "strategy": self.strategy,
            "size": self.size,
            "stride": self.stride,
            "overlap": self.overlap,
            "chunk_count": self.chunk_count,
            "guaranteed_length": self.guaranteed_length,
            "questions": self.questions,
            "ceiling": self.ceiling,
            "destroyed": self.destroyed,
            "resolution_floor": self.resolution_floor,
            "ceiling_by_band": {
                str(band): {"contained": values[0], "total": values[1]}
                for band, values in self.ceiling_by_band().items()
            },
        }


def ceiling_report(corpus: Corpus, chunking: Chunking) -> CeilingReport:
    """Compute the containment ceiling for one chunking over the whole corpus."""
    grouped = chunking.by_document()
    containments = tuple(
        containment_for(question, grouped.get(question.doc_id, ()), answer=question.answer)
        for question in corpus.questions
    )
    return CeilingReport(
        chunking=chunking.name,
        strategy=chunking.strategy,
        size=chunking.size,
        stride=chunking.stride,
        overlap=chunking.overlap,
        chunk_count=chunking.count,
        guaranteed_length=guaranteed_length(chunking),
        containments=containments,
    )
