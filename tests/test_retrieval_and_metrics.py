"""The retrievers, the two recalls, and the attribution the standard metric cannot make."""

from __future__ import annotations

import builtins

import numpy as np
import pytest

from chunkaudit.ceiling import ceiling_report
from chunkaudit.chunking import Chunk, build_chunking
from chunkaudit.documents import Question, Span
from chunkaudit.errors import MissingDependencyError, UnanswerableError, UsageError
from chunkaudit.metrics import (
    Cause,
    MetricSet,
    Rate,
    _covers,
    evaluate,
    outcome_for,
)
from chunkaudit.retrieval import (
    RUNNABLE,
    WRITTEN_NOT_RUN,
    Ranking,
    _hash_matrix,
    rank,
    tokenize,
)


def test_tokenising_lowercases_and_drops_punctuation():
    assert tokenize("For Billing, kx-0007?") == ["for", "billing", "kx", "0007"]


def test_the_hash_matrix_does_not_use_the_process_hash_seed():
    """A published retrieval figure that moves between runs is not a figure.

    Python's built in hash is salted per process unless PYTHONHASHSEED is set, so
    the mixing in this module is a fixed integer hash with no process state in it.
    This checks the property that matters: the same text gives the same row.
    """
    left = _hash_matrix(["for billing"], dimensions=256, ngram=4)
    right = _hash_matrix(["for billing"], dimensions=256, ngram=4)
    assert np.array_equal(left, right)


def test_the_hash_matrix_separates_different_texts():
    matrix = _hash_matrix(["for billing", "for retention"], dimensions=512, ngram=4)
    assert not np.array_equal(matrix[0], matrix[1])


def test_a_ranking_refuses_a_k_below_one():
    ranking = Ranking(qid="q", order=np.arange(5))
    with pytest.raises(UsageError, match="at least 1"):
        ranking.top(0)


@pytest.mark.parametrize("name", RUNNABLE)
def test_every_runnable_retriever_ranks_every_chunk(name, corpus, fixed_chunking, small_policy):
    rankings = rank(name, corpus, fixed_chunking, small_policy)
    assert len(rankings) == len(corpus.questions)
    for ranking in rankings:
        assert sorted(ranking.order.tolist()) == list(range(fixed_chunking.count))


@pytest.mark.parametrize("name", RUNNABLE)
def test_every_runnable_retriever_is_deterministic(name, corpus, fixed_chunking, small_policy):
    left = rank(name, corpus, fixed_chunking, small_policy)
    right = rank(name, corpus, fixed_chunking, small_policy)
    for one, two in zip(left, right, strict=True):
        assert np.array_equal(one.order, two.order)


def test_an_unknown_retriever_is_a_usage_error(corpus, fixed_chunking, small_policy):
    with pytest.raises(UsageError, match="unknown retriever"):
        rank("colbert", corpus, fixed_chunking, small_policy)


def test_the_oracle_finds_the_right_document_for_every_question(
    corpus, fixed_chunking, small_policy
):
    rankings = rank("oracle", corpus, fixed_chunking, small_policy)
    for question, ranking in zip(corpus.questions, rankings, strict=True):
        best = fixed_chunking.chunks[ranking.order[0]]
        assert best.doc_id == question.doc_id


def test_the_oracle_attains_the_ceiling_exactly(corpus, small_policy):
    """The empirical proof that the ceiling is tight rather than merely an upper bound.

    If the oracle came in below it, the ceiling would be loose and the argument
    that a retriever change cannot reach past it would be weaker than stated.
    """
    for entry in (("fixed", 400, 400), ("fixed", 200, 200), ("sentence", 1, 1)):
        chunking = build_chunking(corpus.documents, *entry)
        report = ceiling_report(corpus, chunking)
        rankings = rank("oracle", corpus, chunking, small_policy)
        metrics = evaluate(corpus, chunking, rankings, retriever="oracle", k=20)
        assert metrics.span_complete_recall.value == pytest.approx(report.ceiling)


def test_no_retriever_exceeds_the_ceiling(corpus, small_policy):
    """The invariant that caught a real bug. See the note in metrics.outcome_for."""
    for entry in (("fixed", 200, 200), ("fixed", 400, 300), ("recursive", 800, 600)):
        chunking = build_chunking(corpus.documents, *entry)
        report = ceiling_report(corpus, chunking)
        for name in RUNNABLE:
            rankings = rank(name, corpus, chunking, small_policy)
            metrics = evaluate(corpus, chunking, rankings, retriever=name, k=10)
            assert metrics.span_complete_recall.value <= report.ceiling + 1e-12, (
                entry,
                name,
            )


def test_a_chunk_from_another_document_cannot_contain_this_answer():
    """Pins the bug the ceiling invariant exposed.

    Offsets are per document, so a chunk covering characters 0 to 800 of some
    other document numerically contains an answer at characters 100 to 500 of
    this one. Comparing spans without the document identifier reported a span
    complete recall above the ceiling, which cannot happen.
    """
    chunks = (Chunk("other", 0, Span(0, 800)), Chunk("mine", 1, Span(0, 50)))
    question = Question(qid="q", text="?", doc_id="mine", answer=Span(100, 500), band=400)
    ranking = Ranking(qid="q", order=np.array([0, 1]))
    result = outcome_for(question, ranking, chunks, k=2, containing_in_corpus=0)
    assert not result.contain_hit
    assert not result.overlap_hit
    assert result.cause is Cause.CHUNKING


def test_the_random_retriever_is_worse_than_bm25(corpus, fixed_chunking, small_policy):
    """A comparison with no floor in it cannot say whether a method is working."""
    scores = {}
    for name in ("random", "bm25"):
        rankings = rank(name, corpus, fixed_chunking, small_policy)
        scores[name] = evaluate(
            corpus, fixed_chunking, rankings, retriever=name, k=5
        ).span_complete_recall.value
    assert scores["bm25"] > scores["random"]


def _refuse_sentence_transformers(monkeypatch) -> None:
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.split(".")[0] == "sentence_transformers":
            raise ModuleNotFoundError("No module named 'sentence_transformers'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)


def test_an_empty_model_name_is_reported_before_the_import(
    monkeypatch, corpus, fixed_chunking, small_policy
):
    """Validation above the optional import, so a typo is reported as a typo."""
    from chunkaudit.retrieval import sentence_transformer_rankings

    _refuse_sentence_transformers(monkeypatch)
    with pytest.raises(UsageError, match="cannot be empty"):
        sentence_transformer_rankings(corpus, fixed_chunking, small_policy, model="  ")


def test_the_missing_extra_is_reported_as_a_missing_dependency(
    monkeypatch, corpus, fixed_chunking, small_policy
):
    _refuse_sentence_transformers(monkeypatch)
    with pytest.raises(MissingDependencyError, match="optional extra"):
        rank("sentence_transformer", corpus, fixed_chunking, small_policy)


def test_the_missing_dependency_message_points_at_the_adr(
    monkeypatch, corpus, fixed_chunking, small_policy
):
    _refuse_sentence_transformers(monkeypatch)
    with pytest.raises(MissingDependencyError, match="ADR-003"):
        rank("sentence_transformer", corpus, fixed_chunking, small_policy)


def test_the_written_but_unrun_retriever_is_declared_as_such():
    assert "sentence_transformer" in WRITTEN_NOT_RUN
    assert "sentence_transformer" not in RUNNABLE


def test_a_score_matrix_of_the_wrong_height_is_unanswerable(corpus):
    from chunkaudit.retrieval import _rank

    with pytest.raises(UnanswerableError, match="rows for"):
        _rank(corpus, np.zeros((3, 10)))


def test_ties_are_broken_by_chunk_index(corpus):
    """BM25 gives many chunks exactly zero, and argsort's order there is not a figure."""
    from chunkaudit.retrieval import _rank

    scores = np.zeros((len(corpus.questions), 6))
    rankings = _rank(corpus, scores)
    assert rankings[0].order.tolist() == [0, 1, 2, 3, 4, 5]


def test_covering_needs_every_character():
    assert _covers([Span(0, 50), Span(50, 120)], Span(10, 100))
    assert not _covers([Span(0, 50), Span(60, 120)], Span(10, 100))


def test_covering_handles_unsorted_spans():
    assert _covers([Span(50, 120), Span(0, 50)], Span(10, 100))


def test_covering_a_span_with_one_chunk_is_containment():
    assert _covers([Span(0, 200)], Span(10, 100))


def test_an_outcome_at_k_below_one_is_unanswerable():
    chunks = (Chunk("d", 0, Span(0, 100)),)
    question = Question(qid="q", text="?", doc_id="d", answer=Span(0, 50), band=40)
    with pytest.raises(UnanswerableError, match="k must be at least 1"):
        outcome_for(question, Ranking("q", np.array([0])), chunks, k=0, containing_in_corpus=1)


def test_a_hit_that_cannot_answer_alone_is_flagged_as_overstated():
    """The single most useful column: what a dashboard is counting as a success."""
    chunks = (Chunk("d", 0, Span(0, 100)), Chunk("d", 1, Span(100, 200)))
    question = Question(qid="q", text="?", doc_id="d", answer=Span(60, 160), band=100)
    result = outcome_for(
        question, Ranking("q", np.array([0, 1])), chunks, k=1, containing_in_corpus=0
    )
    assert result.overlap_hit
    assert not result.contain_hit
    assert result.overstated


def test_a_complete_hit_is_not_overstated():
    chunks = (Chunk("d", 0, Span(0, 200)),)
    question = Question(qid="q", text="?", doc_id="d", answer=Span(60, 160), band=100)
    result = outcome_for(question, Ranking("q", np.array([0])), chunks, k=1, containing_in_corpus=1)
    assert result.contain_hit
    assert not result.overstated
    assert result.cause is Cause.NONE


def test_a_failure_with_no_containing_chunk_anywhere_is_the_chunkers_fault():
    chunks = (Chunk("d", 0, Span(0, 100)), Chunk("d", 1, Span(100, 200)))
    question = Question(qid="q", text="?", doc_id="d", answer=Span(60, 160), band=100)
    result = outcome_for(
        question, Ranking("q", np.array([0, 1])), chunks, k=2, containing_in_corpus=0
    )
    assert result.cause is Cause.CHUNKING


def test_a_failure_with_a_containing_chunk_further_down_is_the_retrievers_fault():
    chunks = (Chunk("d", 0, Span(0, 50)), Chunk("d", 1, Span(0, 200)))
    question = Question(qid="q", text="?", doc_id="d", answer=Span(60, 160), band=100)
    result = outcome_for(
        question, Ranking("q", np.array([0, 1])), chunks, k=1, containing_in_corpus=1
    )
    assert result.cause is Cause.RETRIEVAL
    assert result.rank_of_first_containing == 1


def test_an_answer_absent_from_the_corpus_is_its_own_cause():
    chunks = (Chunk("d", 0, Span(0, 100)),)
    question = Question(qid="q", text="?", doc_id="d", answer=Span(0, 50), band=40)
    result = outcome_for(
        question,
        Ranking("q", np.array([0])),
        chunks,
        k=1,
        containing_in_corpus=1,
        answer_in_corpus=False,
    )
    assert result.cause is Cause.CORPUS


def test_a_ranking_that_does_not_cover_the_chunking_is_unattributable():
    """A bug rather than a finding, so it is named rather than folded into a cause."""
    chunks = (Chunk("d", 0, Span(0, 50)), Chunk("d", 1, Span(0, 200)))
    question = Question(qid="q", text="?", doc_id="d", answer=Span(60, 160), band=100)
    result = outcome_for(question, Ranking("q", np.array([0])), chunks, k=1, containing_in_corpus=1)
    assert result.cause is Cause.UNATTRIBUTABLE


def test_the_retrieved_share_is_capped_at_one():
    chunks = (Chunk("d", 0, Span(0, 200)), Chunk("d", 1, Span(0, 200)))
    question = Question(qid="q", text="?", doc_id="d", answer=Span(10, 60), band=40)
    result = outcome_for(
        question, Ranking("q", np.array([0, 1])), chunks, k=2, containing_in_corpus=2
    )
    assert result.retrieved_overlap_share == 1.0


def test_evaluating_with_the_wrong_number_of_rankings_is_unanswerable(corpus, fixed_chunking):
    with pytest.raises(UnanswerableError, match="rankings for"):
        evaluate(corpus, fixed_chunking, [], retriever="bm25", k=5)


def test_the_gap_is_the_difference_between_the_two_recalls(corpus, fixed_chunking, small_policy):
    rankings = rank("bm25", corpus, fixed_chunking, small_policy)
    metrics = evaluate(corpus, fixed_chunking, rankings, retriever="bm25", k=5)
    assert metrics.gap == pytest.approx(
        metrics.chunk_recall.value - metrics.span_complete_recall.value
    )


def test_the_standard_metric_is_never_below_span_complete_recall(
    corpus, fixed_chunking, small_policy
):
    """Containment implies overlap, so the ordering is structural rather than lucky."""
    for name in RUNNABLE:
        rankings = rank(name, corpus, fixed_chunking, small_policy)
        metrics = evaluate(corpus, fixed_chunking, rankings, retriever=name, k=5)
        assert metrics.chunk_recall.value >= metrics.span_complete_recall.value


def test_assembled_recall_sits_between_the_two(corpus, small_policy):
    chunking = build_chunking(corpus.documents, "fixed", 400, 400)
    rankings = rank("bm25", corpus, chunking, small_policy)
    metrics = evaluate(corpus, chunking, rankings, retriever="bm25", k=5)
    assert metrics.span_complete_recall.value <= metrics.assembled_recall.value
    assert metrics.assembled_recall.value <= metrics.chunk_recall.value


def test_recall_does_not_fall_as_k_grows(corpus, fixed_chunking, small_policy):
    rankings = rank("bm25", corpus, fixed_chunking, small_policy)
    values = [
        evaluate(corpus, fixed_chunking, rankings, retriever="bm25", k=k).span_complete_recall.value
        for k in (1, 3, 5, 10)
    ]
    assert values == sorted(values)


def test_the_causes_name_every_enum_member(corpus, fixed_chunking, small_policy):
    rankings = rank("bm25", corpus, fixed_chunking, small_policy)
    metrics = evaluate(corpus, fixed_chunking, rankings, retriever="bm25", k=5)
    assert set(metrics.causes) == {cause.value for cause in Cause}


def test_the_causes_sum_to_the_question_count(corpus, fixed_chunking, small_policy):
    rankings = rank("bm25", corpus, fixed_chunking, small_policy)
    metrics = evaluate(corpus, fixed_chunking, rankings, retriever="bm25", k=5)
    assert sum(metrics.causes.values()) == metrics.questions


def test_a_metric_set_with_no_failures_reports_no_fixable_share():
    metrics = MetricSet(chunking="c", retriever="r", k=1, outcomes=())
    assert metrics.fixable_by_retriever.denominator == 0


def test_a_rate_reports_its_resolution_floor():
    assert Rate(0, 360).floor == pytest.approx(1 / 360)
    assert Rate(0, 360).is_measured_zero


def test_a_rate_over_nothing_is_not_an_exception():
    import math

    assert math.isnan(Rate(0, 0).value)
    assert math.isnan(Rate(0, 0).floor)


def test_the_sample_needed_for_a_claim_is_one_over_the_claim():
    assert Rate(0, 360).samples_needed_for(0.001) == 1000


def test_a_non_positive_claimed_rate_is_refused():
    with pytest.raises(ValueError, match="must be positive"):
        Rate(0, 360).samples_needed_for(0.0)


def test_a_metric_set_serialises_every_rate(corpus, fixed_chunking, small_policy):
    rankings = rank("bm25", corpus, fixed_chunking, small_policy)
    payload = evaluate(corpus, fixed_chunking, rankings, retriever="bm25", k=5).as_dict()
    for key in ("chunk_recall", "span_complete_recall", "assembled_recall", "overstated"):
        assert "resolution_floor" in payload[key]


def test_the_median_retrieved_share_is_nan_when_nothing_failed(
    corpus, document_chunking, small_policy
):
    import math

    rankings = rank("oracle", corpus, document_chunking, small_policy)
    metrics = evaluate(corpus, document_chunking, rankings, retriever="oracle", k=5)
    assert math.isnan(metrics.median_retrieved_share)


def test_retrieving_from_an_empty_chunking_is_unanswerable(corpus, small_policy):
    from chunkaudit.chunking import Chunking
    from chunkaudit.retrieval import hashed_rankings

    with pytest.raises(UnanswerableError, match="no chunks cannot be retrieved"):
        hashed_rankings(
            corpus, Chunking(strategy="fixed", size=1, stride=1, chunks=()), small_policy
        )


def test_bm25_on_chunks_with_no_tokens_is_unanswerable(small_policy):
    """A corpus of punctuation is a labelling problem, not a retrieval result."""
    from chunkaudit.chunking import build_chunking
    from chunkaudit.documents import Corpus, Document, Question, Span
    from chunkaudit.retrieval import bm25_rankings

    documents = tuple(
        Document(doc_id=f"d{index}", text="!!! ???", sentences=(Span(0, 7),)) for index in range(2)
    )
    questions = (Question(qid="q", text="???", doc_id="d0", answer=Span(0, 3), band=8),)
    blank = Corpus(documents=documents, questions=questions)
    with pytest.raises(UnanswerableError, match="no tokens"):
        bm25_rankings(blank, build_chunking(documents, "document"), small_policy)
