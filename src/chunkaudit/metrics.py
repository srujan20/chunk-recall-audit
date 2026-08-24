"""The two recalls, and the three causes the standard one collapses into one.

Every published retrieval metric is computed on the chunks the chunker produced.
A chunk that holds part of an answer counts as a hit, so a question whose answer
was cut in half by a boundary is scored the same as one whose answer sits whole
in the first result. That is not a flaw in anybody's implementation. It is what
the metric is a function of.

Three quantities are computed here instead of one:

    overlap_hit    any retrieved chunk touches the answer. This is the standard
                   metric, under its real name.
    contain_hit    some single retrieved chunk holds the answer whole, which is
                   what a chunk needs in order to answer on its own.
    assemble_hit   the retrieved chunks jointly cover the answer, which is the
                   most the stitching defence can claim.

And when a question fails containment, the cause is attributed to exactly one of
three mutually exclusive possibilities. Only the middle one can be fixed by
touching the retriever, and the standard metric cannot tell them apart, because
two of them look identical to a function of the chunks.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np

from .chunking import Chunk, Chunking
from .documents import Corpus, Question, Span
from .errors import UnanswerableError
from .retrieval import Ranking


class Cause(str, Enum):
    """Why a question's answer was not retrieved whole. Exactly one applies."""

    NONE = "answered"
    CHUNKING = "chunking-destroyed-it"
    RETRIEVAL = "retrieval-missed-it"
    CORPUS = "not-in-the-corpus"
    UNATTRIBUTABLE = "unattributable"


FIXABLE_BY_RETRIEVER = (Cause.RETRIEVAL,)


@dataclass(frozen=True)
class QuestionOutcome:
    """What happened to one question, at one k, under one chunking and retriever."""

    qid: str
    band: int
    answer_length: int
    k: int
    overlap_hit: bool
    contain_hit: bool
    assemble_hit: bool
    cause: Cause
    containing_chunks_in_corpus: int
    retrieved_overlap_share: float
    rank_of_first_containing: int | None

    @property
    def overstated(self) -> bool:
        """True when the standard metric reports a hit that cannot answer alone.

        The single most useful column in the whole repository: it is the set of
        questions a dashboard is currently counting as successes.
        """
        return self.overlap_hit and not self.contain_hit


def _covers(spans: Sequence[Span], answer: Span) -> bool:
    """True when the spans jointly cover every character of the answer.

    Implemented by sweeping sorted intervals rather than by building a set of
    character positions. The set version was the first implementation and it was
    correct; it also allocated an object per character, which on the longest
    answers in the corpus was most of the runtime of the whole audit.
    """
    reach = answer.start
    for span in sorted(spans, key=lambda item: item.start):
        if span.start > reach:
            return False
        reach = max(reach, span.end)
        if reach >= answer.end:
            return True
    return reach >= answer.end


def outcome_for(
    question: Question,
    ranking: Ranking,
    chunks: tuple[Chunk, ...],
    *,
    k: int,
    containing_in_corpus: int,
    answer_in_corpus: bool = True,
) -> QuestionOutcome:
    """Score one question at one k, and attribute its failure to one cause.

    Every span comparison is fenced by the document identifier, and that is not
    defensive coding. Offsets are per document, so a chunk covering characters 0
    to 800 of some other document numerically contains an answer at characters
    100 to 500 of this one. The first version compared spans alone and reported a
    span complete recall of 0.850 against a containment ceiling of 0.828, which
    cannot happen: the ceiling is an upper bound by construction. A measured value
    above it was proof the measurement was wrong rather than news about chunking.
    """
    if k < 1:
        raise UnanswerableError(f"k must be at least 1, got {k}")
    retrieved = [
        chunks[index] for index in ranking.top(k) if chunks[index].doc_id == question.doc_id
    ]
    touching = [chunk for chunk in retrieved if chunk.span.overlaps(question.answer)]
    containing = [chunk for chunk in retrieved if chunk.span.contains(question.answer)]
    overlap_hit = bool(touching)
    contain_hit = bool(containing)
    assemble_hit = _covers([chunk.span for chunk in touching], question.answer)
    covered = sum(chunk.span.intersection(question.answer) for chunk in touching)

    first_containing: int | None = None
    for position, index in enumerate(ranking.order):
        chunk = chunks[index]
        if chunk.doc_id == question.doc_id and chunk.span.contains(question.answer):
            first_containing = position
            break

    if not answer_in_corpus:
        cause = Cause.CORPUS
    elif contain_hit:
        cause = Cause.NONE
    elif containing_in_corpus == 0:
        cause = Cause.CHUNKING
    elif first_containing is not None:
        cause = Cause.RETRIEVAL
    else:
        # A containing chunk exists in the corpus and does not appear anywhere in
        # this ranking. That means the ranking does not cover the chunking, which
        # is a bug rather than a finding, so it is named rather than folded into
        # one of the real causes.
        cause = Cause.UNATTRIBUTABLE

    return QuestionOutcome(
        qid=question.qid,
        band=question.band,
        answer_length=question.answer_length,
        k=k,
        overlap_hit=overlap_hit,
        contain_hit=contain_hit,
        assemble_hit=assemble_hit,
        cause=cause,
        containing_chunks_in_corpus=containing_in_corpus,
        retrieved_overlap_share=min(1.0, covered / question.answer_length),
        rank_of_first_containing=first_containing,
    )


@dataclass(frozen=True)
class Rate:
    """A count over a denominator, carrying the floor its sample can express."""

    numerator: int
    denominator: int

    @property
    def value(self) -> float:
        if self.denominator == 0:
            return float("nan")
        return self.numerator / self.denominator

    @property
    def floor(self) -> float:
        if self.denominator == 0:
            return float("nan")
        return 1.0 / self.denominator

    @property
    def is_measured_zero(self) -> bool:
        return self.denominator > 0 and self.numerator == 0

    def samples_needed_for(self, claimed: float) -> int:
        if claimed <= 0.0:
            raise ValueError(f"claimed rate must be positive, got {claimed}")
        return int(np.ceil(1.0 / claimed))

    def as_dict(self) -> dict[str, object]:
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
            "resolution_floor": self.floor,
            "is_measured_zero": self.is_measured_zero,
        }


@dataclass(frozen=True)
class MetricSet:
    """Every outcome for one chunking, retriever and k, reduced to rates."""

    chunking: str
    retriever: str
    k: int
    outcomes: tuple[QuestionOutcome, ...]

    @property
    def questions(self) -> int:
        return len(self.outcomes)

    @property
    def chunk_recall(self) -> Rate:
        """The standard metric, under its real name."""
        return Rate(sum(1 for item in self.outcomes if item.overlap_hit), self.questions)

    @property
    def span_complete_recall(self) -> Rate:
        return Rate(sum(1 for item in self.outcomes if item.contain_hit), self.questions)

    @property
    def assembled_recall(self) -> Rate:
        return Rate(sum(1 for item in self.outcomes if item.assemble_hit), self.questions)

    @property
    def overstated(self) -> Rate:
        return Rate(sum(1 for item in self.outcomes if item.overstated), self.questions)

    @property
    def gap(self) -> float:
        """How much the standard metric exceeds the one a reader assumes it is."""
        return self.chunk_recall.value - self.span_complete_recall.value

    @property
    def causes(self) -> dict[str, int]:
        counts = Counter(item.cause.value for item in self.outcomes)
        return {cause.value: counts[cause.value] for cause in Cause}

    @property
    def fixable_by_retriever(self) -> Rate:
        """Share of failures a retriever change could address.

        The number a team should see before it funds an embedding upgrade.
        """
        failures = [item for item in self.outcomes if not item.contain_hit]
        return Rate(
            sum(1 for item in failures if item.cause in FIXABLE_BY_RETRIEVER), len(failures)
        )

    @property
    def median_retrieved_share(self) -> float:
        """Median share of the answer the retrieved chunks held, over failures.

        Distinguishes a chunker that lost a clause from one that lost the answer.
        """
        failures = [item.retrieved_overlap_share for item in self.outcomes if not item.contain_hit]
        if not failures:
            return float("nan")
        return float(np.median(failures))

    def as_dict(self) -> dict[str, object]:
        return {
            "chunking": self.chunking,
            "retriever": self.retriever,
            "k": self.k,
            "questions": self.questions,
            "chunk_recall": self.chunk_recall.as_dict(),
            "span_complete_recall": self.span_complete_recall.as_dict(),
            "assembled_recall": self.assembled_recall.as_dict(),
            "overstated": self.overstated.as_dict(),
            "gap": self.gap,
            "causes": self.causes,
            "fixable_by_retriever": self.fixable_by_retriever.as_dict(),
            "median_retrieved_share": self.median_retrieved_share,
        }


def evaluate(
    corpus: Corpus,
    chunking: Chunking,
    rankings: list[Ranking],
    *,
    retriever: str,
    k: int,
) -> MetricSet:
    """Score every question in the corpus at one k."""
    if len(rankings) != len(corpus.questions):
        raise UnanswerableError(f"{len(rankings)} rankings for {len(corpus.questions)} questions")
    grouped = chunking.by_document()
    outcomes: list[QuestionOutcome] = []
    for question, ranking in zip(corpus.questions, rankings, strict=True):
        containing = sum(
            1 for chunk in grouped.get(question.doc_id, ()) if chunk.span.contains(question.answer)
        )
        outcomes.append(
            outcome_for(
                question,
                ranking,
                chunking.chunks,
                k=k,
                containing_in_corpus=containing,
            )
        )
    return MetricSet(chunking=chunking.name, retriever=retriever, k=k, outcomes=tuple(outcomes))
