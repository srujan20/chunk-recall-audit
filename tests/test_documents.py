"""The corpus, and the offsets everything else depends on."""

from __future__ import annotations

import pytest

from chunkaudit.documents import (
    Corpus,
    Document,
    Question,
    Span,
    _sentence_spans,
    build_corpus,
)
from chunkaudit.errors import UnanswerableError


def test_a_span_reports_its_length():
    assert Span(10, 25).length == 15


def test_a_span_cannot_start_before_the_document():
    with pytest.raises(UnanswerableError, match="cannot start before"):
        Span(-1, 5)


def test_an_empty_span_is_refused():
    with pytest.raises(UnanswerableError, match="at least one character"):
        Span(5, 5)


def test_a_reversed_span_is_refused():
    with pytest.raises(UnanswerableError, match="at least one character"):
        Span(9, 4)


def test_containment_is_not_overlap():
    """The distinction the whole repository rests on."""
    outer = Span(0, 100)
    inner = Span(10, 20)
    straddling = Span(90, 130)
    assert outer.contains(inner)
    assert not outer.contains(straddling)
    assert outer.overlaps(straddling)


def test_a_span_contains_itself():
    assert Span(4, 9).contains(Span(4, 9))


def test_touching_spans_do_not_overlap():
    """Half open intervals, so the boundary belongs to exactly one of them."""
    assert not Span(0, 10).overlaps(Span(10, 20))


def test_intersection_counts_shared_characters():
    assert Span(0, 10).intersection(Span(5, 20)) == 5
    assert Span(0, 10).intersection(Span(10, 20)) == 0


def test_a_document_with_a_sentence_past_its_end_is_refused():
    with pytest.raises(UnanswerableError, match="sentence ending at"):
        Document(doc_id="d", text="short", sentences=(Span(0, 99),))


def test_sentence_spans_cover_the_text():
    text = "One thing. Two things. Three."
    spans = _sentence_spans(text)
    assert [text[span.start : span.end] for span in spans] == [
        "One thing.",
        "Two things.",
        "Three.",
    ]


def test_sentence_spans_keep_a_trailing_fragment():
    spans = _sentence_spans("One thing. And then")
    assert spans[-1].end == len("One thing. And then")


def test_sentence_spans_of_a_single_fragment_is_one_span():
    assert len(_sentence_spans("no terminator here")) == 1


def test_a_corpus_with_no_questions_is_refused():
    document = Document(doc_id="d", text="Some text.", sentences=(Span(0, 10),))
    with pytest.raises(UnanswerableError, match="no questions"):
        Corpus(documents=(document,), questions=())


def test_a_question_naming_an_absent_document_is_refused():
    document = Document(doc_id="d", text="Some text.", sentences=(Span(0, 10),))
    question = Question(qid="q", text="?", doc_id="other", answer=Span(0, 4), band=40)
    with pytest.raises(UnanswerableError, match="which is absent"):
        Corpus(documents=(document,), questions=(question,))


def test_an_answer_past_the_end_of_its_document_is_refused():
    document = Document(doc_id="d", text="Some text.", sentences=(Span(0, 10),))
    question = Question(qid="q", text="?", doc_id="d", answer=Span(0, 99), band=40)
    with pytest.raises(UnanswerableError, match="answer ending at"):
        Corpus(documents=(document,), questions=(question,))


def test_the_corpus_has_the_requested_shape(corpus, small_policy):
    assert len(corpus.documents) == small_policy.corpus.documents
    assert len(corpus.questions) == small_policy.corpus.questions


def test_every_answer_span_holds_the_expected_text(corpus):
    for question in corpus.questions:
        assert corpus.answer_text(question).startswith("For ")


def test_every_answer_ends_a_sentence(corpus):
    for question in corpus.questions:
        assert corpus.answer_text(question).endswith(".")


def test_the_same_seed_builds_the_same_corpus():
    left = build_corpus(documents=6, questions_per_document=2, span_chars=(40, 150))
    right = build_corpus(documents=6, questions_per_document=2, span_chars=(40, 150))
    assert [document.text for document in left.documents] == [
        document.text for document in right.documents
    ]


def test_a_different_seed_builds_a_different_corpus():
    left = build_corpus(documents=6, questions_per_document=2, span_chars=(40, 150), seed=1)
    right = build_corpus(documents=6, questions_per_document=2, span_chars=(40, 150), seed=2)
    assert [document.text for document in left.documents] != [
        document.text for document in right.documents
    ]


def test_a_corpus_of_one_document_is_refused():
    with pytest.raises(UnanswerableError, match="at least two documents"):
        build_corpus(documents=1, questions_per_document=1, span_chars=(40, 150))


def test_a_corpus_with_no_questions_per_document_is_refused():
    with pytest.raises(UnanswerableError, match="at least one question"):
        build_corpus(documents=4, questions_per_document=0, span_chars=(40, 150))


def test_each_document_carries_a_token_that_identifies_it(corpus):
    """Pins the fix for a corpus that was unanswerable rather than hard.

    Eight topics and eight subjects repeat every sixty four documents, so a
    question naming only those two matched fifteen documents equally well and
    every retriever scored near chance. The failure attribution then reported a
    retrieval problem that was really a labelling problem.
    """
    for index, document in enumerate(corpus.documents):
        assert f"kx-{index:04d}" in document.text


def test_every_question_names_its_own_document_token(corpus):
    for question in corpus.questions:
        token = question.doc_id.replace("doc-", "kx-")
        assert token in question.text


def test_no_two_documents_share_an_identifying_token(corpus):
    tokens = {document.doc_id.replace("doc-", "kx-") for document in corpus.documents}
    assert len(tokens) == len(corpus.documents)


def test_long_answers_span_several_sentences(corpus):
    """Pins the second corpus fix.

    The first generator made every answer one sentence, which handed every
    sentence window strategy a containment ceiling of exactly one by
    construction. The comparison that produced was not a finding, it was a
    restatement of how the corpus had been built.
    """
    longest = max(corpus.questions, key=lambda question: question.answer_length)
    assert corpus.answer_text(longest).count(". ") >= 1


def test_short_answers_are_one_sentence(corpus):
    shortest = min(corpus.questions, key=lambda question: question.answer_length)
    assert corpus.answer_text(shortest).count(". ") == 0


def test_the_bands_order_the_answer_lengths(corpus, small_policy):
    medians = []
    for band in small_policy.corpus.span_chars:
        lengths = [q.answer_length for q in corpus.questions if q.band == band]
        medians.append(sum(lengths) / len(lengths))
    assert medians == sorted(medians)


def test_every_document_contains_a_distractor_for_its_own_topic(corpus):
    """Without these a lexical retriever scores too well to be informative."""
    for document in corpus.documents:
        assert "deprecation notice" in document.text


def test_the_generator_refuses_to_place_an_answer_outside_its_document(monkeypatch):
    """A guard on the generator itself, because a mislaid span is silent otherwise."""
    import chunkaudit.documents as module

    monkeypatch.setattr(module, "CONTINUATIONS", ("",))
    monkeypatch.setattr(module, "CLAUSES", ("",))
    corpus = module.build_corpus(documents=3, questions_per_document=1, span_chars=(40, 150))
    for question in corpus.questions:
        assert question.answer.end <= corpus.by_id[question.doc_id].length
